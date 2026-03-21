#!/usr/bin/env python3

import json
import sys
import time
from pathlib import Path

STATE_FILE = Path.home() / ".cache/pomodoro_state.json"

WORK = 30
# WORK = 25 * 60

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
    STATE_FILE.write_text(json.dumps(data))


cmd = sys.argv[1] if len(sys.argv) > 1 else None
data = load()

now = time.time()

# ---- RESET
if cmd == "reset":
    if data["state"] == "break":
        # determine correct break type
        if data.get("cycle", 0) % 4 == 0 and data.get("cycle", 0) != 0:
            data["duration"] = LONG_BREAK
        else:
            data["duration"] = SHORT_BREAK
    else:
        data["state"] = "work"
        data["duration"] = WORK

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
        data["state"] = "break"
        data["duration"] = SHORT_BREAK
    else:
        data["state"] = "work"
        data["duration"] = WORK

    data["start_time"] = now
    data["paused"] = False
    data["paused_at"] = None
    data["handled"] = False

save(data)
