#!/usr/bin/env python3
"""Pomodoro timer daemon — the single driver of the state machine.

Detects a finished work/break session, fires the notification + sound, advances
the state, and launches the break overlay. Runs exactly once per login session
(see pomodoro.service).

This logic used to live inside pomodoro.py, the bar module. Polybar and waybar
both spawn one module process per connected output, so plugging in a second
monitor started a second copy of the state machine: two notifications, two
sounds, and two processes racing for the overlay lock. The bar module is now a
read-only renderer and this daemon is the only writer of transitions.
"""

import subprocess
import time
from pathlib import Path

from pomostate import begin_break, load, locked, save, spawn_overlay

ICON = Path(__file__).resolve().parent / "assets" / "pomodoro_icon.png"
SOUND = "/usr/share/sounds/freedesktop/stereo/complete.oga"


def due(data, now):
    """True if the running session has counted down to zero."""
    return (
        data["state"] in ("work", "break")
        and not data["paused"]
        and data["start_time"] is not None
        and now - data["start_time"] >= data["duration"]
    )


def advance(data, now):
    """Move a finished session on. Returns the notification text."""
    if data["state"] == "work":
        begin_break(data, now)
        return "Work session complete"

    # Break over. Park in `waiting` rather than auto-starting work: the next
    # session begins when you dismiss the overlay or click the bar.
    data["state"] = "waiting"
    data["start_time"] = None
    data["paused"] = False
    data["paused_at"] = None
    return "Break is over"


def notify(msg):
    # check=False: a missing notify-send or sound file must not kill the timer.
    subprocess.run(["notify-send", "-i", str(ICON), "Pomodoro", msg], check=False)
    subprocess.run(["paplay", SOUND], check=False)


def main():
    while True:
        fired = None
        with locked():
            data = load()
            now = time.time()
            if due(data, now):
                starting_break = data["state"] == "work"
                fired = (advance(data, now), starting_break)
                # Save before spawning: the overlay reads the state file on
                # startup and quits if the break isn't visible there yet.
                save(data)

        # Outside the lock: notify blocks on paplay, and the overlay takes the
        # lock itself when you dismiss it.
        if fired:
            msg, starting_break = fired
            if starting_break:
                spawn_overlay()
            notify(msg)

        time.sleep(1)


if __name__ == "__main__":
    main()
