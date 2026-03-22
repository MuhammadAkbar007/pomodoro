#!/usr/bin/env python3

import json
import os
import subprocess
import sys
import time
from pathlib import Path

# STATE_FILE = Path.home() / ".cache/pomodoro_state.json"
STATE_FILE = Path(f"/run/user/{os.getuid()}/pomodoro_state.json")

WORK = 10
# WORK = 25 * 60

SHORT_BREAK = 10
# SHORT_BREAK = 5 * 60

LONG_BREAK = 10
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


cmd = sys.argv[1] if len(sys.argv) > 1 else None
data = load()

now = time.time()

# ---- RESET
if cmd == "reset":
    # if data["state"] == "break":
    #     # determine correct break type
    #     if data.get("cycle", 0) % 4 == 0 and data.get("cycle", 0) != 0:
    #         data["duration"] = LONG_BREAK
    #     else:
    #         data["duration"] = SHORT_BREAK
    # else:
    #     data["state"] = "work"
    #     data["duration"] = WORK
    #     data["cycle"] = 0

    data["state"] = "work"
    data["duration"] = WORK
    data["cycle"] = 0
    data["start_time"] = now
    data["paused"] = False
    data["paused_at"] = None
    data["handled"] = False

# ---- TOGGLE
elif cmd == "toggle":
    if data["state"] == "idle":
        data["state"] = "work"
        data["start_time"] = now
        data["paused"] = False
        data["paused_at"] = None
        data["handled"] = False

    elif data["state"] == "waiting":
        data["state"] = "work"
        data["duration"] = WORK
        data["start_time"] = now
        data["paused"] = False
        data["paused_at"] = None
        data["handled"] = False

    elif data["paused"]:
        # RESUME
        data["paused"] = False
        data["start_time"] = now - (data["duration"] - data["paused_at"])
        data["paused_at"] = None
        data["handled"] = False

    else:
        # PAUSE
        elapsed = now - data["start_time"]
        remaining = max(0, int(data["duration"] - elapsed))

        data["paused"] = True
        data["paused_at"] = remaining
        data["handled"] = False

# ---- NEXT
elif cmd == "next":
    if data["state"] == "work":
        data["cycle"] = data.get("cycle", 0) + 1

        # every 4th work session → long break
        if data["cycle"] % 4 == 0:
            data["state"] = "break"
            data["duration"] = LONG_BREAK
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
    else:
        data["state"] = "work"
        data["duration"] = WORK

    data["start_time"] = now
    data["paused"] = False
    data["paused_at"] = None
    data["handled"] = False

save(data)
