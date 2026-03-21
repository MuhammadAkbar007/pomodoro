#!/usr/bin/env python3

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")

from gi.repository import Gtk, Gdk, GLib, GtkLayerShell  # noqa: E402

import json  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402


STATE_FILE = Path.home() / ".cache/pomodoro_state.json"


def load():
    if not STATE_FILE.exists():
        return None
    return json.loads(STATE_FILE.read_text())


class Overlay(Gtk.Window):
    def __init__(self):
        super().__init__()

        # --- Layer shell init ---
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)

        # Anchor to all edges (true fullscreen)
        for edge in (
            GtkLayerShell.Edge.TOP,
            GtkLayerShell.Edge.BOTTOM,
            GtkLayerShell.Edge.LEFT,
            GtkLayerShell.Edge.RIGHT,
        ):
            GtkLayerShell.set_anchor(self, edge, True)

        # Stay above everything
        GtkLayerShell.set_exclusive_zone(self, -1)

        # Optional: appear on all outputs
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.ON_DEMAND)

        # --- Transparency ---
        self.set_app_paintable(True)
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.set_visual(visual)

        self.connect("draw", self.on_draw)

        # --- Content layout ---
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.set_valign(Gtk.Align.CENTER)
        box.set_halign(Gtk.Align.CENTER)

        self.label = Gtk.Label()
        self.label.set_name("overlay-label")
        self.label.set_justify(Gtk.Justification.CENTER)

        box.add(self.label)
        self.add(box)

        # --- Input to dismiss ---
        self.add_events(
            Gdk.EventMask.KEY_PRESS_MASK
            | Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.POINTER_MOTION_MASK
        )

        self.connect("key-press-event", self.close)
        self.connect("button-press-event", self.close)
        self.connect("motion-notify-event", self.close)

        # --- Timer loop ---
        self.update()
        GLib.timeout_add(1000, self.update)

    def on_draw(self, widget, cr):
        # Semi-transparent black overlay
        cr.set_source_rgba(0, 0, 0, 0.7)
        cr.paint()

    def update(self):
        data = load()
        if not data:
            return True

        if data["state"] != "break":
            Gtk.main_quit()
            return False

        now = time.time()
        elapsed = now - data["start_time"]
        remaining = max(0, int(data["duration"] - elapsed))

        minutes = remaining // 60
        seconds = remaining % 60

        # Break type logic
        if data.get("cycle", 0) % 4 == 0:
            break_type = "Long Break"
        else:
            break_type = "Short Break"

        self.label.set_text(f"{break_type}\n{minutes:02}:{seconds:02}")

        self.queue_draw()
        return True

    def close(self, *args):
        Gtk.main_quit()


if __name__ == "__main__":
    win = Overlay()
    win.show_all()
    Gtk.main()
