#!/usr/bin/env python3
"""One-shot commands against the pomodoro state — bar clicks and lock hooks.

Writes the state file and exits; pomodorod.py picks the change up on its next
tick. See pomostate.py for the state shape.
"""

import sys
import time

from pomostate import (
    LONG_BREAK,
    SHORT_BREAK,
    WORK,
    begin_break,
    load,
    locked,
    save,
    spawn_overlay,
)


def run(cmd, now, data):
    """Apply `cmd` to `data` in place. Returns True if a break overlay is due.

    Pure: no I/O, no clock, no exits — so the self-check can drive it directly.
    """
    # ---- LOCK / UNLOCK (screen-locker hooks, from ~/.config/i3/lock.sh)
    # Freeze the timer while the screen is locked and drop into a fresh work
    # session on login, rather than counting down while you're away.
    if cmd in ("lock", "unlock"):
        # Never conjure a pomodoro out of nothing: if the timer is idle (never
        # started / stopped), lock and unlock both leave it idle.
        if data["state"] == "idle":
            return False

        data["state"] = "work"
        data["duration"] = WORK
        if cmd == "lock":
            # Prime the START of the next WORK session, paused, so nothing
            # counts down while locked. Abandons any partial work or
            # in-progress break — the countdown must not run while you're away.
            data["start_time"] = None
            data["paused"] = True
            data["paused_at"] = WORK
        else:
            # Auto-start that work session the moment you log back in.
            data["start_time"] = now
            data["paused"] = False
            data["paused_at"] = None
        return False

    # ---- RESET — restart the current session from the top, keeping the cycle.
    if cmd == "reset":
        if data["state"] == "break":
            # Restore the break length this cycle is owed; a reset must not turn
            # a long break into a short one.
            cycle = data.get("cycle", 0)
            if cycle % 4 == 0 and cycle != 0:
                data["duration"] = LONG_BREAK
            else:
                data["duration"] = SHORT_BREAK
        else:
            data["state"] = "work"
            data["duration"] = WORK

        data["start_time"] = now
        data["paused"] = False
        data["paused_at"] = None

    # ---- TOGGLE
    elif cmd == "toggle":
        if data["state"] in ("idle", "waiting"):
            data["state"] = "work"
            data["duration"] = WORK
            data["start_time"] = now
            data["paused"] = False
            data["paused_at"] = None

        elif data["paused"]:
            # RESUME — rebase start_time so the remaining time survives the pause.
            data["paused"] = False
            data["start_time"] = now - (data["duration"] - data["paused_at"])
            data["paused_at"] = None

        else:
            # PAUSE
            elapsed = now - data["start_time"]
            data["paused"] = True
            data["paused_at"] = max(0, int(data["duration"] - elapsed))

    # ---- NEXT — skip the rest of this session.
    elif cmd == "next":
        if data["state"] == "work":
            begin_break(data, now)
            return True

        data["state"] = "work"
        data["duration"] = WORK
        data["start_time"] = now
        data["paused"] = False
        data["paused_at"] = None

    return False


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else None

    with locked():
        data = load()
        spawn = run(cmd, time.time(), data)
        # Save before spawning: the overlay reads the state file on startup and
        # quits if the break isn't visible there yet.
        save(data)

    # Outside the lock — the overlay takes it itself when you dismiss it.
    if spawn:
        spawn_overlay()


if __name__ == "__main__":
    main()
