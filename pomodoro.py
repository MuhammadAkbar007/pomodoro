#!/usr/bin/env python3

import time
import json
import os
import subprocess
from pathlib import Path

# STATE_FILE = Path.home() / ".cache/pomodoro_state.json"
STATE_FILE = Path(f"/run/user/{os.getuid()}/pomodoro_state.json")

WORK = 30
# WORK = 25 * 60  # 25 minutes

SHORT_BREAK = 30
# SHORT_BREAK = 5 * 60

LONG_BREAK = 30
# LONG_BREAK = 15 * 60


def load():
    if not STATE_FILE.exists():
        return {
            "state": "idle",
            "cycle": 0,
            "start_time": None,
            "duration": WORK,
            "paused": False,
            "paused_at": None,
        }
    return json.loads(STATE_FILE.read_text())


def save(data):
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(STATE_FILE)


while True:
    data = load()
    now = time.time()

    state = data["state"]
    if state == "idle":
        remaining = data["duration"]
    elif state == "waiting":
        print(
            json.dumps(
                {
                    "text": " --:--",  # or reuse your existing formatting
                    "class": state,
                }
            ),
            flush=True,
        )
        time.sleep(1)
        continue
    elif data["paused"] and data["paused_at"] is not None:
        remaining = int(data["paused_at"])
    elif data["start_time"] is not None:
        elapsed = now - data["start_time"]
        remaining = max(0, int(data["duration"] - elapsed))
    else:
        remaining = data["duration"]

    minutes = remaining // 60
    seconds = remaining % 60

    cycle_raw = data.get("cycle", 0)

    # Normalize to 1–4
    cycle = cycle_raw % 4
    cycle = 4 if cycle == 0 and cycle_raw != 0 else cycle

    # Build dots: ●  = done, ○  = remaining 󰨑
    dots = "󰜋" * (cycle - 1) + "󰨑"
    # dots = "" * cycle
    # dots = "" * cycle + "" * (4 - cycle) # out of 4
    # dots = "" * (cycle - 1) + "◉" + "" * (4 - cycle) # currently

    if state == "work":
        text = f"󱎫 {minutes:02}:{seconds:02} {dots}"  # 󰔛
    elif state == "break":
        text = f" {minutes:02}:{seconds:02} {dots}"
    elif state == "waiting":
        text = f" -- : -- {dots}"  # 󰞌 󰚭
    else:
        text = f" -- : -- {dots}"

    print(
        json.dumps(
            {
                "text": text,
                "class": state,
            }
        ),
        flush=True,
    )

    if (
        remaining == 0
        and state not in ("idle", "waiting")
        and not data.get("handled", False)
    ):
        data["handled"] = True

        if state == "work":
            msg = "Work session complete"
        else:
            msg = "Break is over"

        subprocess.run(["notify-send", "Pomodoro", msg])
        subprocess.run(["paplay", "/usr/share/sounds/freedesktop/stereo/complete.oga"])

        if state == "work":
            data["start_time"] = now
            data["cycle"] = data.get("cycle", 0) + 1

            # every 4th work session → long break
            if data["cycle"] % 4 == 0:
                data["state"] = "break"
                data["duration"] = LONG_BREAK
                data["cycle"] = 0
            else:
                data["state"] = "break"
                data["duration"] = SHORT_BREAK

            # 👇 launch overlay
            env = os.environ.copy()
            env.setdefault("WAYLAND_DISPLAY", "wayland-0")
            env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")

            subprocess.Popen(
                [
                    "flock",
                    "-n",
                    "/tmp/pomodoro_overlay.lock",
                    "python3",
                    "/home/akbar/akbarDev/pet-projects/pomodoro/overlay.py",
                ],
                env=env,
            )

        elif state == "break":
            data["state"] = "waiting"
            data["start_time"] = None
            data["paused"] = False
            data["paused_at"] = None

        data["paused"] = False
        data["paused_at"] = None
        data["handled"] = False

        save(data)

    time.sleep(1)
