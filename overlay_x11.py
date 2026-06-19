#!/usr/bin/env python3
# X11 / i3 break overlay — drop-in counterpart to overlay.py, which uses GTK
# Layer Shell (a Wayland-only wlr-layer-shell protocol that does nothing on X11).
#
# Same state-file logic and dismiss behaviour as overlay.py; only the windowing
# differs: instead of a layer surface we use a fullscreen, undecorated,
# keep-above GTK window with an RGBA visual. The semi-transparent fill needs a
# compositor for alpha — picom provides that on this i3 setup.

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")

from gi.repository import Gtk, Gdk, GLib  # noqa: E402 # type: ignore

import json  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402


WORK = 25 * 60
STATE_FILE = Path(f"/run/user/{os.getuid()}/pomodoro_state.json")


def load():
    if not STATE_FILE.exists():
        return None
    return json.loads(STATE_FILE.read_text())


class Overlay(Gtk.Window):
    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)

        # --- X11 fullscreen overlay (replaces the layer-shell setup) ---
        self.set_decorated(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_keep_above(True)
        self.set_type_hint(Gdk.WindowTypeHint.SPLASHSCREEN)
        self.set_app_paintable(True)
        self.fullscreen()

        # RGBA visual so on_draw can paint a translucent black (picom composites).
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.set_visual(visual)

        self.connect("draw", self.on_draw)

        # --- Content layout (same as overlay.py) ---
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.set_valign(Gtk.Align.CENTER)
        box.set_halign(Gtk.Align.CENTER)

        self.label = Gtk.Label()
        self.label.set_name("overlay-label")
        self.label.set_justify(Gtk.Justification.CENTER)

        box.add(self.label)
        self.add(box)

        # Big readable white text, no external CSS file needed.
        css = Gtk.CssProvider()
        css.load_from_data(
            b"#overlay-label{color:#ffffff;font-size:48px;font-weight:bold;}"
        )
        Gtk.StyleContext.add_provider_for_screen(
            screen, css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        # --- Dismiss on interaction. Arm after a short delay so the keyboard
        # grab / initial pointer motion doesn't instantly close the overlay. ---
        self._armed = False
        GLib.timeout_add(700, self._arm)

        self.add_events(
            Gdk.EventMask.KEY_PRESS_MASK
            | Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.POINTER_MOTION_MASK
        )
        self.connect("key-press-event", self.close)
        self.connect("button-press-event", self.close)
        self.connect("motion-notify-event", self.close)

        # Grab the keyboard so "press any key" works even over a fullscreen app.
        self.connect("map-event", self.on_map)

        # --- Timer loop ---
        self.update()
        GLib.timeout_add(1000, self.update)

    def _arm(self):
        self._armed = True
        return False

    def on_map(self, *args):
        try:
            seat = self.get_display().get_default_seat()
            seat.grab(
                self.get_window(),
                Gdk.SeatCapabilities.KEYBOARD,
                True,
                None,
                None,
                None,
            )
        except Exception:
            pass
        return False

    def on_draw(self, widget, cr):
        # Semi-transparent black overlay (same as overlay.py).
        cr.set_source_rgba(0, 0, 0, 0.1)
        cr.paint()
        return False

    def update(self):
        data = load()
        if not data:
            return True

        if data["state"] not in ("break", "waiting"):
            Gtk.main_quit()
            return False

        now = time.time()
        if data["state"] == "break":
            elapsed = now - data["start_time"]
            remaining = max(0, int(data["duration"] - elapsed))
        else:
            remaining = 0

        minutes = remaining // 60
        seconds = remaining % 60

        if data.get("cycle", 0) % 4 == 0:
            break_type = "Long Break"
        else:
            break_type = "Short Break"

        if data["state"] == "break":
            label = f"{break_type}\n{minutes:02}:{seconds:02}"
        else:
            label = "Break finished\nPress any key to continue"
        self.label.set_text(label)

        self.queue_draw()
        return True

    def close(self, *args):
        if not self._armed:
            return True

        data = load()
        if data and data["state"] in ("waiting", "break"):
            data["state"] = "work"
            data["duration"] = WORK
            data["start_time"] = time.time()
            data["paused"] = False
            data["paused_at"] = None
            data["handled"] = False

            STATE_FILE.write_text(json.dumps(data))

        Gtk.main_quit()


if __name__ == "__main__":
    win = Overlay()
    win.show_all()
    Gtk.main()
