"""Profilliste links, ausgewählte Profilangaben rechts."""
from gi.repository import Gtk
from .model import PROJECT, save_settings
from .profiles import ProfileStore


def show_profiles(owner):
    if not PROJECT.get('profiles_enabled', False):
        return None
    for dialog in owner.dialogs:
        if dialog.get_name() == 'profiles_dialog' and dialog.get_visible():
            dialog.present()
            return dialog
    try:
        store = ProfileStore()
    except (OSError, ValueError, UnicodeError):
        owner.notify('profiles_error')
        return None
    window = owner.track(Gtk.Window(title=owner.tr('profiles'), transient_for=owner,
                                   modal=True, default_width=720, default_height=440))
    window.set_name('profiles_dialog')
    layout = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                     margin_top=16, margin_bottom=16, margin_start=16, margin_end=16)
    window.set_child(layout)
    panes = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, vexpand=True)
    panes.set_position(220)
    layout.append(panes)
    left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    left.append(owner.label('profiles', xalign=0))
    list_ = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
    scroll = Gtk.ScrolledWindow(vexpand=True, min_content_height=120)
    scroll.set_child(list_)
    left.append(scroll)
    panes.set_start_child(left)
    right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_start=16)
    panes.set_end_child(right)
    right.append(owner.label('profile_name', xalign=0))
    name = Gtk.Entry()
    right.append(name)
    fields = {}
    for field in PROJECT['settings']:
        if field['type'] == 'boolean':
            widget = Gtk.CheckButton(label=owner.tr(field['label']))
        elif field['type'] == 'number':
            right.append(owner.label(field['label'], xalign=0, wrap=True))
            widget = Gtk.SpinButton.new_with_range(field['min'], field['max'], 1)
        else:
            right.append(owner.label(field['label'], xalign=0, wrap=True))
            widget = Gtk.Entry(hexpand=True)
        fields[field['key']] = widget
        right.append(widget)
    state = {'key': None, 'refreshing': False}
    def options():
        result = owner.opts.copy()
        for key, widget in fields.items():
            if isinstance(widget, Gtk.SpinButton):
                widget.update()
                result[key] = widget.get_value_as_int()
            elif isinstance(widget, Gtk.CheckButton):
                result[key] = widget.get_active()
            else:
                result[key] = widget.get_text()
        return result
    def commit():
        if state['key'] is not None:
            store.update(state['key'], name.get_text(), options())
    def refresh(selected=None):
        state['refreshing'] = True
        child = list_.get_first_child()
        while child:
            following = child.get_next_sibling()
            list_.remove(child)
            child = following
        target = None
        for key, item in sorted(store.items.items(), key=lambda entry: entry[1]['name'].casefold()):
            row = Gtk.ListBoxRow()
            row.profile_id = key
            row.set_child(Gtk.Label(label=item['name'], xalign=0,
                                   margin_start=8, margin_end=8, margin_top=6, margin_bottom=6))
            list_.append(row)
            if key == selected:
                target = row
        state['refreshing'] = False
        list_.select_row(target)
        if target is None:
            selected_row(list_, None)
    def selected_row(_list, row):
        if state['refreshing']:
            return
        previous = state['key']
        try:
            commit()
        except ValueError:
            owner.notify('profile_name_error')
            state['refreshing'] = True
            for child in children(list_):
                if child.profile_id == previous:
                    list_.select_row(child)
            state['refreshing'] = False
            return
        key = row.profile_id if row else None
        state['key'] = key
        right.set_sensitive(key is not None)
        delete.set_sensitive(key is not None)
        apply.set_sensitive(key is not None)
        name.set_text(store.items[key]['name'] if key else '')
        if key:
            values = store.items[key]['options']
            for field_key, widget in fields.items():
                if isinstance(widget, Gtk.SpinButton):
                    widget.set_value(values[field_key])
                else:
                    widget.set_active(values[field_key])
    def create(*_):
        try:
            commit()
            number = 1
            names = {item['name'].casefold() for item in store.items.values()}
            while owner.tr('new_profile_name', number=number).casefold() in names:
                number += 1
            key = store.create(owner.tr('new_profile_name', number=number), owner.opts)
            state['key'] = None
            refresh(key)
            name.grab_focus()
        except ValueError:
            owner.notify('profile_name_error')
    def remove(*_):
        key = state['key']
        if key:
            del store.items[key]
            state['key'] = None
            refresh()
    def save(use=False):
        try:
            commit()
            new = owner.opts.copy()
            if use and state['key']:
                new = store.apply(state['key'], new)
            elif new['active_profile'] not in store.items:
                new['active_profile'] = ''
            store.save()
            save_settings(new)
            owner.opts = new
            owner.close_dialog(window)
            owner.set_status('profile_applied' if use else 'profiles_saved')
        except ValueError:
            owner.notify('profile_name_error')
        except OSError:
            owner.notify('write_error')
    actions = Gtk.Box(spacing=8)
    new = owner.button('profile_new', create)
    delete = owner.button('profile_delete', remove)
    actions.append(new)
    actions.append(delete)
    left.append(actions)
    footer = Gtk.Box(spacing=8, halign=Gtk.Align.END)
    footer.append(owner.button('cancel', lambda *_: owner.close_dialog(window)))
    save_button = owner.button('profiles_save', lambda *_: save())
    footer.append(save_button)
    apply = owner.button('profile_apply', lambda *_: save(True))
    footer.append(apply)
    layout.append(footer)
    list_.connect('row-selected', selected_row)
    refresh(owner.opts['active_profile'] or None)
    window.profile_controls = dict(new=new, delete=delete, save=save_button, apply=apply,
                                   name=name, list=list_, store=store, fields=fields)
    window.present()
    return window


def children(widget):
    child = widget.get_first_child()
    while child:
        yield child
        child = child.get_next_sibling()
