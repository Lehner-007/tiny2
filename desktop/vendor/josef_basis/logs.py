"""Begrenzte Protokollierung und eine lesende Protokollanzeige."""
import logging
from logging.handlers import RotatingFileHandler
from gi.repository import Gtk
from .model import config_dir, PROGRAM_ID
from .file_dialogs import choose


class SessionFormatter(logging.Formatter):
    def format(self, record):
        text = super().format(record)
        if getattr(record, 'session_start', False):
            line = '=' * 72
            return '\n' + line + '\n' + text + '\n' + line
        return text


def log_path():
    return config_dir() / 'logs' / (PROGRAM_ID + '.log')


def setup_logging():
    logger = logging.getLogger(PROGRAM_ID + '.application')
    logger.setLevel(logging.INFO)
    logger.propagate = False
    # Mehrere Fenster erzeugen keine doppelten Handler.
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    try:
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(path, maxBytes=500_000, backupCount=2, encoding='utf-8')
        handler.setFormatter(SessionFormatter('%(asctime)s %(message)s', datefmt='%d.%m.%Y %H:%M:%S'))
    except OSError:
        handler = logging.NullHandler()
    logger.addHandler(handler)
    return logger


def read_log():
    path = log_path()
    if not path.exists():
        return ''
    with path.open('rb') as stream:
        stream.seek(0, 2)
        length = stream.tell()
        start = max(0, length - 1_000_000)
        stream.seek(start)
        if start:
            stream.readline()
        return stream.read().decode('utf-8', errors='replace')


def show_log(owner):
    for dialog in owner.dialogs:
        if dialog.get_name() == 'log_dialog' and dialog.get_visible():
            dialog.present()
            return dialog
    window = owner.track(Gtk.Window(title=owner.tr('log'), transient_for=owner,
                         default_width=780, default_height=480))
    window.set_name('log_dialog')
    owner.bindings.append((window, 'set_title', 'log'))
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10,
                  margin_top=16, margin_bottom=16, margin_start=16, margin_end=16)
    window.set_child(box)
    box.append(Gtk.Label(label=str(log_path()), xalign=0, wrap=True, selectable=True))
    box.append(owner.label('log_readonly', xalign=0, wrap=True))
    view = Gtk.TextView(editable=False, cursor_visible=False, monospace=True,
                        wrap_mode=Gtk.WrapMode.WORD_CHAR)
    scroll = Gtk.ScrolledWindow(vexpand=True)
    scroll.set_child(view)
    box.append(scroll)
    def reload(*_):
        try:
            view.get_buffer().set_text(read_log())
        except OSError:
            owner.notify('log_error')
    def export(*_):
        # Exportiert den sichtbaren Stand, ohne das aktive Protokoll zu verändern.
        buffer = view.get_buffer()
        text = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)
        def save(path):
            path.write_text(text, encoding='utf-8')
            owner.set_status('log_exported')
        choose(owner, 'log_export', save, action=Gtk.FileChooserAction.SAVE,
               parent=window, filename=PROGRAM_ID + '-protokoll.txt', filters=(('Text', ('*.txt',)),))
    buttons = Gtk.Box(spacing=8)
    reload_button = owner.button('log_reload', reload)
    export_button = owner.button('log_export', export)
    buttons.append(reload_button)
    buttons.append(export_button)
    buttons.append(owner.button('close', lambda *_: owner.close_dialog(window)))
    box.append(buttons)
    window.log_controls = dict(view=view, reload=reload_button, export=export_button)
    reload()
    window.present()
    return window
