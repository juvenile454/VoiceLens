"""Bounded native Cairo visualizer. Static at rest; no audio access of its own."""
from __future__ import annotations

import math
import sys
import time

import cairo
from gi.repository import GdkPixbuf, GLib, Gtk


class VoiceVisualizer(Gtk.Image):
    def __init__(self):
        super().__init__()
        self.set_size_request(148, 148)
        self.phase = 'idle'
        self.level = self.energy = 0.0
        self._source = None
        self._started = time.monotonic()
        self.connect('map', self._sync_animation)
        self.connect('unmap', self._stop)
        self.connect('destroy', self._stop)
        self._render()

    def set_phase(self, phase):
        if phase == self.phase:
            return
        self.phase = phase
        self._started = time.monotonic()
        if phase != 'recording':
            self.level = 0
        self._sync_animation()
        self._render()

    def _sync_animation(self, *_):
        self._stop()
        if self.get_mapped() and self.phase != 'idle':
            reduced = not self.get_settings().get_property('gtk-enable-animations')
            self._source = GLib.timeout_add(200 if reduced else 34, self._frame)

    def _stop(self, *_):
        if self._source is not None:
            GLib.source_remove(self._source)
            self._source = None

    def _frame(self):
        self.energy += (self.level - self.energy) * (0.48 if self.level > self.energy else 0.19)
        self._render()
        return GLib.SOURCE_CONTINUE

    def _render(self):
        # Gtk's cairo foreign-struct bridge is optional on Ubuntu. Own the Cairo
        # surface here and hand GTK packed pixels, avoiding another dependency.
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 148, 148)
        cr = cairo.Context(surface)
        cr.set_source_rgb(14 / 255, 21 / 255, 27 / 255)
        cr.paint()
        self._draw(cr)
        surface.flush()
        data = bytes(surface.get_data())
        pixels = bytearray(len(data))
        if sys.byteorder == 'little':
            pixels[0::4], pixels[1::4], pixels[2::4], pixels[3::4] = data[2::4], data[1::4], data[0::4], data[3::4]
        else:
            pixels[0::4], pixels[1::4], pixels[2::4], pixels[3::4] = data[1::4], data[2::4], data[3::4], data[0::4]
        pixbuf = GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(bytes(pixels)),
            GdkPixbuf.Colorspace.RGB, True, 8, 148, 148, 148 * 4)
        self.set_from_pixbuf(pixbuf)

    def _draw(self, cr):
        w, h = 148, 148
        reduced = not self.get_settings().get_property('gtk-enable-animations')
        t = 0 if self.phase == 'idle' or reduced else time.monotonic() - self._started
        e = self.energy if self.phase == 'recording' else 0
        busy = self.phase in ('stopping', 'transcribing', 'loading', 'settling')
        x, y = w / 2, h / 2
        scale = 1.0
        if self.phase == 'settling' and not reduced:
            scale = max(0.04, 1 - min(1, t / 0.42) ** 2)
        r = (29 + e * 10) * scale
        mint = (0.66, 0.62, 1) if busy else (0.40, 0.98, 0.86)

        def glow(gx, gy, radius, color, alpha):
            gradient = cairo.RadialGradient(gx, gy, 0, gx, gy, radius)
            gradient.add_color_stop_rgba(0, *color, alpha)
            gradient.add_color_stop_rgba(0.4, *color, alpha * 0.4)
            gradient.add_color_stop_rgba(1, *color, 0)
            cr.set_source(gradient)
            cr.arc(gx, gy, radius, 0, math.tau)
            cr.fill()

        cr.set_line_width(0.7)
        for radius in (53, 67):
            cr.set_source_rgba(0.55, 0.76, 0.78, 0.10)
            cr.arc(x, y, radius, 0, math.tau)
            cr.stroke()
        glow(x, y, r * 2.3, mint, 0.22 + e * 0.12)
        glow(x + r * 0.3, y + r * 0.2, r * 1.7, (0.38, 0.55, 1), 0.32)
        cr.set_source_rgba(0.04, 0.11, 0.16, 0.8)
        cr.arc(x, y, r, 0, math.tau)
        cr.fill()
        for band in range(3):
            cr.new_path()
            for i in range(73):
                a = i / 72 * math.tau
                radius = r * (0.9 + band * 0.06 + math.sin(a * 3 + t + band * 1.9) * (0.04 + e * 0.12))
                px, py = x + math.cos(a) * radius, y + math.sin(a) * radius * (0.90 + band * 0.04)
                cr.move_to(px, py) if i == 0 else cr.line_to(px, py)
            cr.close_path()
            cr.set_source_rgba(*(mint if band != 1 else (0.38, 0.55, 1)), 0.5 + band * 0.18)
            cr.set_line_width((1.3 if band == 2 else 0.8) * scale)
            cr.stroke()
        glow(x - 3, y - 3, r * 0.8, mint, 0.4)
        glow(x, y, r * 0.32, (0.9, 1, 0.98), 0.65)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        if busy:
            cr.set_source_rgba(*mint, 0.8)
            cr.set_line_width(1.2 * scale)
            for i in range(2):
                a = t * 1.8 + i * math.pi
                cr.arc(x, y, r * 1.35, a, a + 1.2)
                cr.stroke()
        else:
            for i in range(5):
                bh = (2 + e * (6 + 5 * math.sin(t * 7 + i))) * scale
                bx = x + (i - 2) * 5 * scale
                cr.set_source_rgba(0.91, 1, 0.98, 0.8)
                cr.set_line_width(1.6 * scale)
                cr.move_to(bx, y - bh)
                cr.line_to(bx, y + bh)
                cr.stroke()
        return False
