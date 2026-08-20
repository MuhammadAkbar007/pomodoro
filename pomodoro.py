#!/usr/bin/env python3
"""Bar module: prints the pomodoro state as one JSON line per second.

READ-ONLY on purpose. Polybar and waybar both spawn one module process per
connected output, so anything that writes state or fires a side effect here
happens once per monitor. The timer itself lives in pomodorod.py.
"""

import json
import time

from pomostate import load


def remaining_seconds(data, now):
    if data["state"] == "idle":
        return data["duration"]
    if data["paused"] and data["paused_at"] is not None:
        return int(data["paused_at"])
    if data["start_time"] is not None:
        return max(0, int(data["duration"] - (now - data["start_time"])))
    return data["duration"]


def dots(data):
    """Four-dot cycle indicator: filled = done, hollow = to go."""
    cycle_raw = data.get("cycle", 0)
    completed = cycle_raw % 4

    if data["state"] == "work":
        current = completed + 1 if completed < 4 else 4
        return "󰜋" * completed + "󰨑" + "󰜌" * (4 - current)
    if data["state"] == "break":
        if completed == 0 and cycle_raw != 0:
            completed = 4
        return "󰜋" * completed + "󰜌" * (4 - completed)
    return "󰜌" * 4


def render(data, now):
    """Return the (text, class) pair for the bar."""
    state = data["state"]

    # `waiting` = break done, next work session not started. No countdown to
    # show and no dots either — this is what the module has always printed.
    if state == "waiting":
        return " --:--", state

    minutes, seconds = divmod(remaining_seconds(data, now), 60)

    if state == "work":
        text = f"󱎫 {minutes:02}:{seconds:02} {dots(data)}"  # 󰔛
    elif state == "break":
        text = f" {minutes:02}:{seconds:02} {dots(data)}"
    else:
        text = " pomodoro "

    return text, "paused" if data["paused"] else state


def main():
    while True:
        text, output_class = render(load(), time.time())
        print(json.dumps({"text": text, "class": output_class}), flush=True)
        time.sleep(1)


if __name__ == "__main__":
    main()
