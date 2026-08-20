# Pomodoro

A pomodoro timer for i3 + polybar: a bar module, a break overlay that dims every
monitor, and a daemon that drives the clock.

## Architecture

One file writes the clock, everything else reads it.

```
pomodorod.py   daemon     the ONLY thing that advances state, notifies, spawns overlays
pomodoro.py    renderer   prints one JSON line per second for the bar (read-only)
pomodoroctl.py CLI        one-shot commands: toggle / next / reset / lock / unlock
overlay_x11.py overlay    dims every monitor during a break (X11 / i3)
overlay.py     overlay    same, for Wayland via GTK Layer Shell
pomostate.py   shared     state file, durations, load/save, overlay launching
```

State lives in `/run/user/$UID/pomodoro_state.json`:

```json
{"state": "work", "cycle": 3, "start_time": 1787230835.19,
 "duration": 1500, "paused": false, "paused_at": null}
```

`state` is one of `idle`, `work`, `break`, `waiting`, `paused` being a separate
boolean. `waiting` means the break is over and the next work session hasn't been
started yet.

Every writer uses `pomostate.save()`, which writes to a pid-unique temp file and
renames, so a reader polling once a second never sees half a document — and
every writer wraps its read-modify-write in `pomostate.locked()`, an `fcntl`
lock on a sibling file. The rename alone only protects readers; without the lock
a bar click landing in the same second as a daemon tick overwrites the
transition the daemon just stored. Readers don't take the lock and don't need
to. `test_pomodoro.py` pins this with four concurrent writers.

### Why the daemon is separate

Polybar and waybar both spawn **one module process per connected output**. When
the driving logic lived inside `pomodoro.py`, plugging in a second monitor
started a second copy of the state machine: two notifications, two sounds, and
two processes racing for the overlay lock. The bar module is now strictly a
renderer — it can run once per monitor forever without consequence — and
`pomodorod.py` is the single writer.

## Install

```sh
ln -s "$PWD/pomodoro.service" ~/.config/systemd/user/pomodoro.service
systemctl --user daemon-reload
```

Then add to `~/.config/i3/config`, **after** the
`dbus-update-activation-environment` line:

```
exec_always --no-startup-id systemctl --user restart pomodoro.service
```

Reload i3 (`$mod+Shift+r`) and it's running.

### Do NOT `systemctl --user enable` it

The unit has no `[Install]` section on purpose. `default.target` is reached
before i3 runs `dbus-update-activation-environment`, so an enabled unit starts
with no `DISPLAY` in its environment. Notifications and sound would still work —
they go over the session bus — but every break overlay for the rest of that
session would silently fail to open. Starting it from i3 guarantees the X11
environment exists first.

`exec_always` also means an i3 reload restarts the daemon, which is what you want
after editing this project. That is why the unit sets `KillMode=process`:
`spawn_overlay()` uses `Popen`, so a live break overlay sits in the daemon's
cgroup, and the default `control-group` would tear it off the screen on every
`$mod+Shift+r`. `KillMode=mixed` does not help — it still SIGKILLs the rest of
the cgroup.

### Polybar module

```ini
[module/pomodoro]
type = custom/script
exec = ~/.config/polybar/pomodoro.sh
tail = true
click-left = python3 /path/to/pomodoroctl.py toggle
click-right = python3 /path/to/pomodoroctl.py next
click-middle = python3 /path/to/pomodoroctl.py reset
```

Include it on every bar you like — the module is read-only.

## Usage

| | |
|---|---|
| left click | start / pause / resume |
| right click | skip to the next session |
| middle click | restart the current session |
| any key or mouse move during a break | end the break, start working |

25 min work, 5 min break, 15 min break after every 4th session. Change the
constants at the top of `pomostate.py`.

The i3 lock hook (`~/.config/i3/lock.sh`) calls `pomodoroctl.py lock` and
`unlock`, which freeze the timer while the screen is locked and drop you into a
fresh work session on login rather than counting down while you're away.

## Monitors

Nothing to reconfigure when you plug or unplug an external monitor.

- The **daemon** never looks at monitors at all.
- The **overlay** enumerates outputs when it launches and creates one dimmed
  window per monitor, so a break covers every screen. One window takes the seat
  grab (X11 grabs are exclusive) and that grab routes events from all monitors to
  it, so a key or mouse move anywhere dismisses the whole set.
- The **bar** is polybar's business; `~/.config/polybar/polybar_launcher.sh`
  relaunches one bar per output on i3 reload.

Monitor changes *during* a break aren't handled — the overlay picks its outputs
at launch. Breaks are five minutes; dismiss and take the next one.

## Development

```sh
python3 test_pomodoro.py    # state machine self-check, no framework
uvx ruff check .
uvx ruff format --check .
```

`uvx pyright .` reports `Import "gi" could not be resolved` for both overlays.
That's an artifact of uvx running pyright in an isolated venv — PyGObject and
pycairo are system packages, not pip ones. Not a real error.

To exercise the overlay without disturbing your session, run it against a nested
X server:

```sh
Xephyr :9 -screen 1600x900 & DISPLAY=:9 python3 overlay_x11.py
```

### Known gap

`overlay.py` (Wayland) still covers a single output. GTK Layer Shell needs an
explicit `set_monitor` per surface to span monitors. Unreachable on X11, so it's
untested and unfixed.
