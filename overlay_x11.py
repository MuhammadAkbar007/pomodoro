#!/usr/bin/env python3
# X11 / i3 break overlay — drop-in counterpart to overlay.py, which uses GTK
# Layer Shell (a Wayland-only wlr-layer-shell protocol that does nothing on X11).
#
# Same state-file logic and dismiss behaviour as overlay.py; only the windowing
# differs: instead of a layer surface we use override-redirect (POPUP) GTK
# windows sized to each monitor, with an RGBA visual. Override-redirect keeps
# the windows out of i3's control so they neither steal the focused app's
# fullscreen nor get tiled. The semi-transparent fill needs a compositor for
# alpha — picom provides that on this i3 setup.
#
# One window per monitor: a break should dim every screen, not just whichever
# one the pointer happened to be on. Input is grabbed by a single window (a seat
# grab is exclusive) and that grab routes events from all monitors to it, so a
# key or mouse move anywhere dismisses the whole set.

import subprocess
import time

import cairo
import gi

from pomostate import WORK, load, locked, save

# Must run before gi.repository is imported, hence the import below it.
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")

from gi.repository import Gdk, GLib, Gtk  # type: ignore

CSS = b"#overlay-label{color:#ffffff;font-size:48px;font-weight:bold;}"

# Dim level: 0.0 clear .. 1.0 solid black.
DIM = 0.85

# Ignore input for this long after mapping, so the seat grab and whatever
# pointer motion is already in flight don't dismiss the overlay instantly.
ARM_DELAY_MS = 700

_windows = []
_armed = False


def screen_locked():
    # i3lock (spawned by ~/.config/i3/lock.sh via xss-lock) takes an EXCLUSIVE
    # X11 keyboard + pointer grab. An override-redirect overlay mapped on top of
    # it can never acquire that grab, so it receives no input and its dismiss
    # handlers never fire — it just sits there forever. The lock always wins, so
    # we simply skip the overlay whenever the screen is locked.
    return (
        subprocess.run(
            ["pgrep", "-x", "i3lock"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,  # rc 1 just means "not locked"
        ).returncode
        == 0
    )


def quit_overlay():
    # Deferred on purpose. Gtk.main_quit() called before Gtk.main() has started
    # is silently dropped, and the process then sits in Gtk.main() forever with
    # an invisible window and a live input grab. idle_add defers the quit until
    # the loop is actually running, so an early exit decision still lands.
    GLib.idle_add(Gtk.main_quit)


class Overlay(Gtk.Window):
    """One dimmed window covering exactly one monitor."""

    def __init__(self, monitor, grab_input):
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
        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)

        # An override-redirect window gets no WM geometry, so we place and size
        # it over its monitor ourselves.
        geo = monitor.get_geometry()
        self.move(geo.x, geo.y)
        self.set_size_request(geo.width, geo.height)
        self.resize(geo.width, geo.height)

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

        self.add_events(
            Gdk.EventMask.KEY_PRESS_MASK
            | Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.POINTER_MOTION_MASK
        )
        self.connect("key-press-event", dismiss)
        self.connect("button-press-event", dismiss)
        self.connect("motion-notify-event", dismiss)

        if grab_input:
            self.connect("map-event", self.on_map)

    def on_map(self, *args):
        try:
            seat = self.get_display().get_default_seat()
            # Grab keyboard AND pointer: a pointer grab routes every motion /
            # click to this window regardless of which monitor it happens on, so
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
        except Exception:  # noqa: BLE001, S110
            # Deliberately broad and silent: if the grab fails for any reason
            # the overlay must still show. It then dismisses on events delivered
            # to it directly, which is the pre-grab behaviour.
            pass
        return False

    def on_draw(self, widget, cr):
        # Semi-transparent black overlay. Use the SOURCE operator (replace), not
        # the default OVER (blend): this window redraws every second, and on the
        # iGPU/glx path the override-redirect window's backing buffer is not
        # reliably cleared between frames. With OVER that means each redraw
        # stacks another layer, creeping to solid black over a long break.
        # SOURCE writes exactly rgba(0, 0, 0, DIM) every frame -> stable.
        # save/restore so the label child still composites with OVER on top.
        cr.save()
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, DIM)
        cr.paint()
        cr.restore()
        return False

    def set_label(self, text):
        self.label.set_text(text)
        self.queue_draw()


def label_for(data):
    if data["state"] != "break":
        return "Break finished\nPress any key to continue"

    remaining = max(0, int(data["duration"] - (time.time() - data["start_time"])))
    minutes, seconds = divmod(remaining, 60)
    break_type = "Long Break" if data.get("cycle", 0) % 4 == 0 else "Short Break"
    return f"{break_type}\n{minutes:02}:{seconds:02}"


def tick():
    """Repaint every monitor once a second, or tear the overlay down."""
    # If the screen gets locked while a break is on screen, yield to i3lock
    # (which owns the input grab) rather than hang on top of it, undismissable.
    if screen_locked():
        quit_overlay()
        return False

    data = load()
    if data["state"] not in ("break", "waiting"):
        quit_overlay()
        return False

    text = label_for(data)
    for win in _windows:
        win.set_label(text)
    return True


def arm():
    global _armed
    _armed = True
    return False


def dismiss(*args):
    """Any key, click or mouse move on any monitor starts the next work session."""
    if not _armed:
        return True

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
    return True


def main():
    # Don't map over the lock screen — see screen_locked() for why.
    if screen_locked():
        raise SystemExit(0)

    display = Gdk.Display.get_default()
    _, px, py = display.get_default_seat().get_pointer().get_position()

    monitors = [display.get_monitor(i) for i in range(display.get_n_monitors())]

    # A seat grab is exclusive, so exactly one window may take it. Give it to
    # the monitor holding the pointer; if the pointer is somewhere no monitor
    # claims, the first window takes it.
    grab_index = 0
    for i, monitor in enumerate(monitors):
        geo = monitor.get_geometry()
        if geo.x <= px < geo.x + geo.width and geo.y <= py < geo.y + geo.height:
            grab_index = i
            break

    # One provider for the whole screen, not one per window.
    css = Gtk.CssProvider()
    css.load_from_data(CSS)
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )

    for i, monitor in enumerate(monitors):
        win = Overlay(monitor, grab_input=(i == grab_index))
        _windows.append(win)
        win.show_all()

    tick()  # paint before the first second elapses
    GLib.timeout_add(1000, tick)
    GLib.timeout_add(ARM_DELAY_MS, arm)
    Gtk.main()


if __name__ == "__main__":
    main()
