"""Fensterdaten gegen die aktuell erreichbaren Monitorflächen prüfen."""
import ctypes
import ctypes.util
from gi.repository import Gdk, GLib


def reachable_bounds(rect, monitors):
    if not monitors:
        return (0, 0, 760, 480)
    x, y, width, height = rect
    def overlap(m):
        left, top, w, h = m
        return max(0, min(x + width, left + w) - max(x, left)) * max(0, min(y + height, top + h) - max(y, top))
    monitor = max(monitors, key=overlap)
    left, top, mw, mh = monitor
    # Platz für Titelzeile und Desktopleisten lassen; negative Monitorursprünge sind gültig.
    width = min(max(360, width), max(1, mw - 32))
    height = min(max(240, height), max(1, mh - 80))
    if overlap(monitor) == 0:
        x, y = left + (mw - width) // 2, top + (mh - height - 40) // 2
    x = max(left + 16, min(x, left + mw - width - 16))
    y = max(top + 16, min(y, top + mh - height - 64))
    return (x, y, width, height)


def monitor_rects():
    display = Gdk.Display.get_default()
    result = []
    if display:
        monitors = display.get_monitors()
        for i in range(monitors.get_n_items()):
            r = monitors.get_item(i).get_geometry()
            result.append((r.x, r.y, r.width, r.height))
    return result


def x11_position(widget, target=None):
    try:
        import gi
        gi.require_version('GdkX11', '4.0')
        from gi.repository import GdkX11
        surface = widget.get_surface()
        if not isinstance(surface, GdkX11.X11Surface):
            return None
        name = ctypes.util.find_library('X11')
        if not name:
            return None
        lib = ctypes.CDLL(name)
        pointer, ulong, integer = ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int
        lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
        lib.XOpenDisplay.restype = pointer
        lib.XCloseDisplay.argtypes = [pointer]
        lib.XQueryTree.argtypes = [pointer, ulong, ctypes.POINTER(ulong), ctypes.POINTER(ulong), ctypes.POINTER(pointer), ctypes.POINTER(ctypes.c_uint)]
        lib.XTranslateCoordinates.argtypes = [pointer, ulong, ulong, integer, integer, ctypes.POINTER(integer), ctypes.POINTER(integer), ctypes.POINTER(ulong)]
        lib.XMoveWindow.argtypes = [pointer, ulong, integer, integer]
        lib.XFlush.argtypes = [pointer]
        lib.XFree.argtypes = [pointer]
        lib.XInternAtom.argtypes = [pointer, ctypes.c_char_p, integer]
        lib.XInternAtom.restype = ulong
        lib.XGetWindowProperty.argtypes = [pointer, ulong, ulong, ctypes.c_long, ctypes.c_long,
            integer, ulong, ctypes.POINTER(ulong), ctypes.POINTER(integer), ctypes.POINTER(ulong),
            ctypes.POINTER(ulong), ctypes.POINTER(pointer)]
        connection = lib.XOpenDisplay(None)
        if not connection:
            return None
        try:
            xid = GdkX11.X11Surface.get_xid(surface)
            scale = surface.get_scale_factor()
            if target:
                lib.XMoveWindow(connection, xid, round(target[0] * scale), round(target[1] * scale))
                lib.XFlush(connection)
                return target
            root, parent, child = ulong(), ulong(), ulong()
            children, count = pointer(), ctypes.c_uint()
            if not lib.XQueryTree(connection, xid, ctypes.byref(root), ctypes.byref(parent), ctypes.byref(children), ctypes.byref(count)):
                return None
            if children:
                lib.XFree(children)
            x, y = integer(), integer()
            if not lib.XTranslateCoordinates(connection, xid, root.value, 0, 0, ctypes.byref(x), ctypes.byref(y), ctypes.byref(child)):
                return None
            left, top = 0, 0
            atom = lib.XInternAtom(connection, b'_NET_FRAME_EXTENTS', 1)
            if atom:
                actual, remaining, size = ulong(), ulong(), ulong()
                format_, data = integer(), pointer()
                result = lib.XGetWindowProperty(connection, xid, atom, 0, 4, 0, 0,
                    ctypes.byref(actual), ctypes.byref(format_), ctypes.byref(size), ctypes.byref(remaining), ctypes.byref(data))
                try:
                    if result == 0 and data and format_.value == 32 and size.value >= 4:
                        extents = ctypes.cast(data, ctypes.POINTER(ulong))
                        left, top = extents[0], extents[2]
                finally:
                    if data:
                        lib.XFree(data)
            return (round((x.value - left) / scale), round((y.value - top) / scale))
        finally:
            lib.XCloseDisplay(connection)
    except (ImportError, ValueError, OSError, AttributeError):
        return None


class WindowState:
    def __init__(self, window):
        self.window = window
        options = window.opts
        self.rect = reachable_bounds((options['window_x'], options['window_y'],
                                      options['window_width'], options['window_height']), monitor_rects())
        window.set_default_size(self.rect[2], self.rect[3])
        self.position_known = options['window_position_known']
        self.restored = False
        window.connect('map', self.on_map)
        self.timer = GLib.timeout_add(500, self.remember)
        self.monitors = Gdk.Display.get_default().get_monitors()
        self.monitor_handler = self.monitors.connect('items-changed', self.monitors_changed)

    def monitors_changed(self, *_):
        if not self.window.alive:
            return
        self.remember()
        self.rect = reachable_bounds(self.rect, monitor_rects())
        if not self.window.is_maximized():
            self.window.set_default_size(self.rect[2], self.rect[3])
            if self.window.get_visible():
                x11_position(self.window, self.rect[:2])

    def on_map(self, *_):
        if not self.restored:
            self.restored = True
            GLib.timeout_add(120, self.restore)

    def restore(self):
        if self.window.get_visible():
            if self.position_known:
                x11_position(self.window, self.rect[:2])
            if self.window.opts['window_maximized']:
                self.window.maximize()
        return False

    def remember(self):
        if self.window.get_visible() and not self.window.is_maximized() and not self.window.is_fullscreen():
            position = x11_position(self.window)
            if position:
                self.position_known = True
            x, y = position or self.rect[:2]
            self.rect = (x, y, self.window.get_width(), self.window.get_height())
        return self.window.alive

    def save(self):
        self.remember()
        GLib.source_remove(self.timer)
        self.monitors.disconnect(self.monitor_handler)
        x, y, width, height = self.rect
        self.window.opts.update(window_x=x, window_y=y, window_width=width, window_height=height,
                                window_position_known=self.position_known, window_maximized=self.window.is_maximized())
