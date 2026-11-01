"""Zentrierung eines GTK-4-Dialogs in Linux-Mint/X11 ohne Systemänderungen."""
import ctypes
import ctypes.util
from gi.repository import GLib


def center_on_parent(dialog, parent):
    # GTK 4 überlässt die Position normalerweise dem Fenstermanager. Unter
    # Cinnamon/X11 kann dieser einen transienten Dialog deutlich zu hoch setzen.
    # Unter Wayland bleiben die regulären Regeln des Compositors maßgeblich.
    try:
        import gi
        gi.require_version('GdkX11', '4.0')
        from gi.repository import GdkX11
        if not isinstance(dialog.get_surface(), GdkX11.X11Surface):
            return False
        library = ctypes.util.find_library('X11')
        if not library:
            return False
        x = ctypes.CDLL(library)
        pointer, ulong, integer, uint = ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_uint
        x.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x.XOpenDisplay.restype = pointer
        x.XCloseDisplay.argtypes = [pointer]
        x.XGetGeometry.argtypes = [pointer, ulong, ctypes.POINTER(ulong), ctypes.POINTER(integer),
            ctypes.POINTER(integer), ctypes.POINTER(uint), ctypes.POINTER(uint), ctypes.POINTER(uint), ctypes.POINTER(uint)]
        x.XTranslateCoordinates.argtypes = [pointer, ulong, ulong, integer, integer,
                                            ctypes.POINTER(integer), ctypes.POINTER(integer), ctypes.POINTER(ulong)]
        x.XMoveWindow.argtypes = [pointer, ulong, integer, integer]
        x.XFlush.argtypes = [pointer]
        x.XInternAtom.argtypes = [pointer, ctypes.c_char_p, integer]
        x.XInternAtom.restype = ulong
        x.XGetWindowProperty.argtypes = [pointer, ulong, ulong, ctypes.c_long, ctypes.c_long,
            integer, ulong, ctypes.POINTER(ulong), ctypes.POINTER(integer), ctypes.POINTER(ulong),
            ctypes.POINTER(ulong), ctypes.POINTER(pointer)]
        x.XFree.argtypes = [pointer]
        connection = x.XOpenDisplay(None)
        if not connection:
            return False
        try:
            def extents(window):
                atom = x.XInternAtom(connection, b'_NET_FRAME_EXTENTS', 1)
                actual, count, remaining = ulong(), ulong(), ulong()
                format_ = integer()
                data = pointer()
                values = (0, 0, 0, 0)
                if atom:
                    result = x.XGetWindowProperty(connection, window, atom, 0, 4, 0, 0,
                        ctypes.byref(actual), ctypes.byref(format_), ctypes.byref(count),
                        ctypes.byref(remaining), ctypes.byref(data))
                    try:
                        if result == 0 and data and format_.value == 32 and count.value >= 4:
                            values = tuple(ctypes.cast(data, ctypes.POINTER(ulong))[i] for i in range(4))
                    finally:
                        if data:
                            x.XFree(data)
                return values
            def geometry(widget):
                window = GdkX11.X11Surface.get_xid(widget.get_surface())
                root, child = ulong(), ulong()
                left, top = integer(), integer()
                width, height, border, depth = uint(), uint(), uint(), uint()
                if not x.XGetGeometry(connection, window, ctypes.byref(root), ctypes.byref(left),
                    ctypes.byref(top), ctypes.byref(width), ctypes.byref(height), ctypes.byref(border), ctypes.byref(depth)):
                    return None
                if not x.XTranslateCoordinates(connection, window, root.value, 0, 0,
                    ctypes.byref(left), ctypes.byref(top), ctypes.byref(child)):
                    return None
                return window, left.value, top.value, width.value, height.value
            p, d = geometry(parent), geometry(dialog)
            if p is None or d is None:
                return False
            pe, de = extents(p[0]), extents(d[0])
            # ConfigureRequest-Koordinaten beziehen sich beim Fenstermanager auf
            # den Rahmen; XTranslateCoordinates liefert die Inhaltskoordinaten.
            left = p[1] - pe[0] + (p[3] + pe[0] + pe[1] - d[3] - de[0] - de[1]) // 2
            top = p[2] - pe[2] + (p[4] + pe[2] + pe[3] - d[4] - de[2] - de[3]) // 2
            x.XMoveWindow(connection, d[0], left, top)
            x.XFlush(connection)
            return True
        finally:
            x.XCloseDisplay(connection)
    except (ImportError, ValueError, OSError, AttributeError):
        return False


def center_after_map(dialog, parent):
    def position():
        if dialog.get_visible() and parent.get_visible():
            center_on_parent(dialog, parent)
        return False
    GLib.timeout_add(100, position)
