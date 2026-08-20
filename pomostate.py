"""Shared state for the pomodoro tools.

Four programs touch the same JSON file — the daemon (pomodorod.py), the bar
renderer (pomodoro.py), the CLI (pomodoroctl.py) and the break overlay
(overlay_x11.py). They each used to carry their own copy of STATE_FILE, the
durations and load/save, which had already drifted: the overlay wrote the file
with a plain write_text() while everyone else wrote it atomically, so a reader
polling once a second could catch a half-written document. One copy here.
"""

import fcntl
import json
import os
import subprocess
from contextlib import contextmanager
from pathlib import Path

STATE_FILE = Path(f"/run/user/{os.getuid()}/pomodoro_state.json")
STATE_LOCK = Path(f"/run/user/{os.getuid()}/pomodoro_state.lock")
OVERLAY_LOCK = "/tmp/pomodoro_overlay.lock"

WORK = 25 * 60
SHORT_BREAK = 5 * 60
LONG_BREAK = 15 * 60

IDLE = {
    "state": "idle",
    "cycle": 0,
    "start_time": None,
    "duration": WORK,
    "paused": False,
    "paused_at": None,
}


def load():
    if not STATE_FILE.exists():
        return dict(IDLE)
    return json.loads(STATE_FILE.read_text())


def save(data):
    # Atomic rename: readers poll this file every second and must never see a
    # partially written JSON document. The temp name carries the pid because a
    # shared one is not safe under concurrent writers — two saves racing on the
    # same temp path renamed a half-written file into place.
    tmp = STATE_FILE.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(STATE_FILE)


@contextmanager
def locked():
    """Hold the state lock across a read-modify-write.

    save() alone only stops a reader seeing a torn file; it does not stop two
    writers losing each other's work. Click pause in the same second the daemon
    finishes a work session and the click, holding the older snapshot, writes
    `work`+`paused` over the `break` the daemon just stored — the notification
    has already fired but the break is gone.

    Readers (the bar, the overlay's tick) don't need this; the atomic rename is
    enough for them.

    ponytail: one lock over the whole file. The only contention is a human
    clicking at the same instant the daemon ticks.
    """
    with open(STATE_LOCK, "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        yield


def begin_break(data, now):
    """Advance a finished work session into its break. Every 4th one is long."""
    data["cycle"] = data.get("cycle", 0) + 1
    data["state"] = "break"
    data["duration"] = LONG_BREAK if data["cycle"] % 4 == 0 else SHORT_BREAK
    data["start_time"] = now
    data["paused"] = False
    data["paused_at"] = None
    return data


def spawn_overlay():
    """Launch the break overlay: GTK Layer Shell on Wayland, plain GTK on X11.

    Callers MUST save() the break state first. The overlay reads the state file
    the moment it starts and exits if it doesn't see a break yet.
    """
    here = Path(__file__).resolve().parent
    use_wayland = (
        bool(os.environ.get("WAYLAND_DISPLAY"))
        and os.environ.get("XDG_SESSION_TYPE") != "x11"
    )
    overlay = "overlay.py" if use_wayland else "overlay_x11.py"

    env = os.environ.copy()
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    if use_wayland:
        env.setdefault("WAYLAND_DISPLAY", "wayland-0")

    # flock -n: never stack two overlays, whoever asks second is dropped.
    subprocess.Popen(
        ["flock", "-n", OVERLAY_LOCK, "python3", str(here / overlay)],
        env=env,
    )
