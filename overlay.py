#!/usr/bin/env python3

import time

import gi

from pomostate import WORK, load, locked, save

# Must run before gi.repository is imported, hence the import below it.
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")

from gi.repository import Gdk, GLib, Gtk, GtkLayerShell  # type: ignore


def quit_overlay():
    # Deferred: see the same helper in overlay_x11.py. Gtk.main_quit() called
    # before Gtk.main() starts is dropped, stranding the process.
    GLib.idle_add(Gtk.main_quit)


class Overlay(Gtk.Window):
    def __init__(self):
        super().__init__()

        self.set_can_focus(True)
        self.grab_focus()

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
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.EXCLUSIVE)

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
        if data["state"] not in ("break", "waiting"):
            quit_overlay()
            return False

        now = time.time()
        if data["state"] == "break":
            elapsed = now - data["start_time"]
            remaining = max(0, int(data["duration"] - elapsed))
        else:
            remaining = 0

        minutes = remaining // 60
        seconds = remaining % 60

        # Break type logic
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
        with locked():
            data = load()
            if data["state"] in ("waiting", "break"):
                data["state"] = "work"
                data["duration"] = WORK
                data["start_time"] = time.time()
                data["paused"] = False
                data["paused_at"] = None

                save(data)

        quit_overlay()


if __name__ == "__main__":
    win = Overlay()
    win.show_all()
    Gtk.main()
