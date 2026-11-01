"""Gemeinsame native Datei- und Ordnerauswahl ohne blockierende Dialogschleife."""
import os
from pathlib import Path
from gi.repository import Gtk, Gio, GLib
from .model import ROOT, config_dir


def initial_folder(folder=None):
    candidate = Path(folder) if folder else (ROOT if config_dir() == ROOT / '.config' else Path.home())
    return candidate if candidate.is_dir() else Path.home()


def check_export_target(path):
    target = Path(path).resolve()
    library = Path(__file__).resolve().parent
    if target == library or library in target.parents:
        raise ValueError('Protected library source')
    if target == config_dir().resolve() or config_dir().resolve() in target.parents:
        raise ValueError('Protected application data')
    if ROOT.resolve() in target.parents and (target.suffix in ('.py', '.sh') or target.name in ('VERSION', 'projekt.json', 'LICENSE')):
        raise ValueError('Protected application source')
    for resource in ('lang', 'help', 'assets', 'modules', 'src'):
        protected = (ROOT / resource).resolve()
        if target == protected or protected in target.parents:
            raise ValueError('Protected application resource')
    return target


def choose(owner, title_key, callback, *, action=Gtk.FileChooserAction.OPEN,
           parent=None, folder=None, filters=(), filename=None, on_cancel=None,
           protected_save=True, show=True):
    parent = parent or owner
    dialog = Gtk.FileChooserNative(title=owner.tr(title_key), transient_for=parent,
            modal=True, action=action, accept_label=owner.tr('choose_save' if action == Gtk.FileChooserAction.SAVE else 'choose_open'),
            cancel_label=owner.tr('cancel'))
    try:
        dialog.set_current_folder(Gio.File.new_for_path(str(initial_folder(folder))))
    except GLib.Error:
        owner.notify('file_dialog_error')
    for label, patterns in filters:
        filter_ = Gtk.FileFilter()
        filter_.set_name(label)
        for pattern in patterns:
            filter_.add_pattern(pattern)
        dialog.add_filter(filter_)
    if action == Gtk.FileChooserAction.SAVE and filename:
        dialog.set_current_name(filename)
    owner.file_dialogs.append(dialog)
    def response(chooser, result):
        file = chooser.get_file()
        path = file.get_path() if file else None
        if chooser in owner.file_dialogs:
            owner.file_dialogs.remove(chooser)
        chooser.destroy()
        if not owner.alive:
            return
        if result == Gtk.ResponseType.ACCEPT and path:
            try:
                selected = Path(path)
                if action == Gtk.FileChooserAction.SAVE and protected_save:
                    selected = check_export_target(selected)
                callback(selected)
            except ValueError:
                owner.notify('protected_target')
            except OSError:
                owner.notify('write_error')
        elif on_cancel:
            on_cancel()
    dialog.connect('response', response)
    if show:
        dialog.show()
    return dialog
