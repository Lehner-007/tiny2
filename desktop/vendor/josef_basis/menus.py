"""GTK-Menüs ohne Leerraum durch die Mindesthöhe einer Scrollleiste."""
from gi.repository import Gtk, Gdk


_separator_provider = None


def style_menu_separators(menu_bar):
    global _separator_provider
    menu_bar.add_css_class('template-menubar')
    if _separator_provider is None:
        _separator_provider = Gtk.CssProvider()
        _separator_provider.load_from_data(b'''
            .template-menubar popover.menu separator {
                min-height: 1px;
                background-color: alpha(@theme_fg_color, 0.45);
                margin-top: 4px;
                margin-bottom: 4px;
            }
        ''')
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(),
            _separator_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)


def descendants(widget):
    yield widget
    child = widget.get_first_child()
    while child is not None:
        yield from descendants(child)
        child = child.get_next_sibling()


def fit_menu_scroll_area(scroll):
    # AUTOMATIC berücksichtigt auch bei unsichtbarer Scrollleiste deren
    # Mindesthöhe. Eine einzelne Menüzeile ist niedriger als diese Reserve.
    # Für solche kurzen Menüs sind Scrollleisten nicht erforderlich.
    scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    child = scroll.get_child()
    if child is None:
        return
    natural = child.measure(Gtk.Orientation.VERTICAL, -1).natural
    scrollbar_minimum = scroll.get_vscrollbar().measure(Gtk.Orientation.VERTICAL, -1).minimum
    if natural < scrollbar_minimum:
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.NEVER)


def compact_menus(menu_bar):
    # Nur die Menüleiste behandeln, niemals ScrolledWindows in Dialogen.
    style_menu_separators(menu_bar)
    for widget in descendants(menu_bar):
        if isinstance(widget, Gtk.ScrolledWindow):
            fit_menu_scroll_area(widget)
            if not getattr(widget, '_template_compact_menu', False):
                widget.connect('map', fit_menu_scroll_area)
                widget._template_compact_menu = True
