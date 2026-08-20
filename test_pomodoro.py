#!/usr/bin/env python3
"""Self-check for the state machine moved out of the bar module.

Run: python3 test_pomodoro.py
"""

import pomodoro
import pomodoroctl
import pomodorod
from pomostate import LONG_BREAK, SHORT_BREAK, WORK


def running(state, duration, started_ago, **kw):
    return {
        "state": state,
        "cycle": 0,
        "start_time": 1000.0 - started_ago,
        "duration": duration,
        "paused": False,
        "paused_at": None,
        **kw,
    }


NOW = 1000.0


def test_work_finishes_into_a_short_break():
    data = running("work", WORK, WORK)
    assert pomodorod.due(data, NOW)
    assert pomodorod.advance(data, NOW) == "Work session complete"
    assert data["state"] == "break"
    assert data["duration"] == SHORT_BREAK
    assert data["cycle"] == 1


def test_every_fourth_work_session_earns_a_long_break():
    for cycle, expected in (
        (0, SHORT_BREAK),
        (1, SHORT_BREAK),
        (2, SHORT_BREAK),
        (3, LONG_BREAK),
    ):
        data = running("work", WORK, WORK, cycle=cycle)
        pomodorod.advance(data, NOW)
        assert data["duration"] == expected, f"cycle {cycle} -> {data['duration']}"


def test_break_finishes_into_waiting():
    data = running("break", SHORT_BREAK, SHORT_BREAK, cycle=1)
    assert pomodorod.due(data, NOW)
    assert pomodorod.advance(data, NOW) == "Break is over"
    assert data["state"] == "waiting"
    assert data["start_time"] is None


def test_nothing_is_due_early_or_while_paused_or_idle():
    assert not pomodorod.due(running("work", WORK, WORK - 1), NOW)
    assert not pomodorod.due(running("work", WORK, WORK, paused=True, paused_at=0), NOW)
    assert not pomodorod.due(running("waiting", WORK, WORK), NOW)
    assert not pomodorod.due(running("idle", WORK, WORK), NOW)
    # After a lock, work is primed but not started: no start_time to count from.
    assert not pomodorod.due(
        {
            **running("work", WORK, 0),
            "start_time": None,
            "paused": True,
            "paused_at": WORK,
        },
        NOW,
    )


def test_renderer_never_reports_a_negative_countdown():
    text, cls = pomodoro.render(running("work", WORK, WORK + 600), NOW)
    assert "00:00" in text, text
    assert cls == "work"


def test_renderer_shows_paused_class_and_frozen_time():
    data = running("work", WORK, 999, paused=True, paused_at=90)
    text, cls = pomodoro.render(data, NOW)
    assert cls == "paused"
    assert "01:30" in text, text


def test_renderer_waiting_has_no_countdown():
    text, cls = pomodoro.render(running("waiting", WORK, 0), NOW)
    assert text == " --:--"
    assert cls == "waiting"


def test_pause_then_resume_preserves_the_remaining_time():
    data = running("work", WORK, 400)  # 1100s left
    assert not pomodoroctl.run("toggle", NOW, data)
    assert data["paused"] and data["paused_at"] == 1100

    # Resume 300s later; the countdown must pick up at 1100, not 800.
    assert not pomodoroctl.run("toggle", NOW + 300, data)
    assert not data["paused"]
    assert int(data["duration"] - (NOW + 300 - data["start_time"])) == 1100


def test_lock_freezes_a_full_work_session_and_unlock_starts_it():
    data = running("break", SHORT_BREAK, 10, cycle=2)
    assert not pomodoroctl.run("lock", NOW, data)
    # The in-progress break is abandoned; nothing may count down while locked.
    assert data["state"] == "work"
    assert data["paused"] and data["paused_at"] == WORK
    assert data["start_time"] is None

    assert not pomodoroctl.run("unlock", NOW, data)
    assert data["state"] == "work" and not data["paused"]
    assert data["start_time"] == NOW


def test_lock_and_unlock_never_start_a_timer_from_idle():
    for cmd in ("lock", "unlock"):
        data = running("idle", WORK, 0)
        assert not pomodoroctl.run(cmd, NOW, data)
        assert data == running("idle", WORK, 0), f"{cmd} disturbed idle"


def test_next_from_work_asks_for_an_overlay_but_from_break_does_not():
    data = running("work", WORK, 60)
    assert pomodoroctl.run("next", NOW, data) is True
    assert data["state"] == "break"

    data = running("break", SHORT_BREAK, 10, cycle=1)
    assert pomodoroctl.run("next", NOW, data) is False
    assert data["state"] == "work" and data["duration"] == WORK


def test_reset_keeps_a_long_break_long():
    data = running("break", LONG_BREAK, 200, cycle=4)
    assert not pomodoroctl.run("reset", NOW, data)
    assert data["duration"] == LONG_BREAK
    assert data["start_time"] == NOW
    assert data["cycle"] == 4, "reset must not touch the cycle"


def test_toggle_starts_work_from_both_idle_and_waiting():
    for state in ("idle", "waiting"):
        data = running(state, WORK, 0)
        assert not pomodoroctl.run("toggle", NOW, data)
        assert data["state"] == "work", state
        assert data["duration"] == WORK
        assert data["start_time"] == NOW


def test_concurrent_writers_do_not_lose_updates():
    """The lock's reason for existing: load -> modify -> save from two writers."""
    import multiprocessing
    import tempfile
    from pathlib import Path

    import pomostate

    workers, bumps = 4, 60
    with tempfile.TemporaryDirectory() as tmp:
        pomostate.STATE_FILE = Path(tmp) / "state.json"
        pomostate.STATE_LOCK = Path(tmp) / "state.lock"
        pomostate.save({**pomostate.IDLE, "cycle": 0})

        procs = [
            multiprocessing.Process(target=_bump, args=(bumps,)) for _ in range(workers)
        ]
        for p in procs:
            p.start()
        for p in procs:
            p.join()

        got = pomostate.load()["cycle"]
    assert got == workers * bumps, f"lost updates: {got} != {workers * bumps}"


def _bump(times):
    import pomostate

    for _ in range(times):
        with pomostate.locked():
            data = pomostate.load()
            data["cycle"] += 1
            pomostate.save(data)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("all passed")
