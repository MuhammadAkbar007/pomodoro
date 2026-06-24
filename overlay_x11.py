#!/usr/bin/env python3
# X11 / i3 break overlay — drop-in counterpart to overlay.py, which uses GTK
# Layer Shell (a Wayland-only wlr-layer-shell protocol that does nothing on X11).
#
# Same state-file logic and dismiss behaviour as overlay.py; only the windowing
# differs: instead of a layer surface we use an override-redirect (POPUP) GTK
# window sized to the monitor, with an RGBA visual. Override-redirect keeps the
# window out of i3's control so it neither steals the focused app's fullscreen
# nor gets tiled. The semi-transparent fill needs a compositor for alpha —
# picom provides that on this i3 setup.

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")

from gi.repository import Gtk, Gdk, GLib  # noqa: E402 # type: ignore

import cairo  # noqa: E402
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
        # POPUP => override-redirect: i3 does not manage this window. That
        # matters because i3 allows only one *managed* fullscreen window per
        # output, so the old self.fullscreen() call kicked whatever app was
        # fullscreen out of fullscreen. An override-redirect window is unmanaged
        # and simply stacks above everything — including a fullscreen app — the
        # same way rofi/dmenu/dunst do, without disturbing its state.

        super().__init__(type=Gtk.WindowType.POPUP)

        # Tag the window as a tooltip. picom is (despite blur-background=false in
        # the on-disk config) blurring translucent windows on this running
        # instance, which frosts the overlay so you can't see through it. picom's
        # blur-background-exclude list already contains window_type='tooltip', so
        # advertising that type makes picom skip the blur — a code-only opt-out,
        # no picom.conf change. (Verified: without it the view behind is smeared;
        # with it the view behind stays sharp.)
        self.set_type_hint(Gdk.WindowTypeHint.TOOLTIP)

        self.set_app_paintable(True)

        # RGBA visual so on_draw can paint a translucent black (picom composites).
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.set_visual(visual)

        # Manually cover the monitor under the pointer (no WM fullscreen).
        self._cover_pointer_monitor(screen)

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

    def _cover_pointer_monitor(self, screen):
        # Size/position the window to exactly cover the monitor the pointer is
        # on. Replaces self.fullscreen(); an override-redirect window gets no
        # WM geometry, so we set it ourselves.
        display = self.get_display()
        pointer = display.get_default_seat().get_pointer()
        _screen, px, py = pointer.get_position()
        monitor = display.get_monitor_at_point(px, py)
        if monitor is None:
            monitor = display.get_primary_monitor()
        geo = monitor.get_geometry()
        self.move(geo.x, geo.y)
        self.set_size_request(geo.width, geo.height)
        self.resize(geo.width, geo.height)

    def on_map(self, *args):
        try:
            seat = self.get_display().get_default_seat()
            # Grab keyboard AND pointer: a pointer grab routes every motion /
            # click to this window regardless of where it happens on screen, so
            # "press any key or move the mouse" dismisses from anywhere — not
            # only when the pointer is over the centered text.
            seat.grab(
                self.get_window(),
                Gdk.SeatCapabilities.ALL,
                True,
                None,
                None,
                None,
            )
        except Exception:
            pass
        return False

    def on_draw(self, widget, cr):
        # Semi-transparent black overlay. Use the SOURCE operator (replace), not
        # the default OVER (blend): this window redraws every second, and on the
        # iGPU/glx path the override-redirect window's backing buffer is not
        # reliably cleared between frames. With OVER that means each redraw
        # stacks another 0.1 black layer, creeping to solid black over a long
        # break. SOURCE writes exactly rgba(0,0,0,0.1) every frame -> stable.
        # save/restore so the label child still composites with OVER on top.
        cr.save()
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(
            0, 0, 0, 0.85
        )  # last value = dim level (0.0 clear .. 1.0 black)
        cr.paint()
        cr.restore()
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
