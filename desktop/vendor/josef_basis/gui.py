"""Gemeinsame GTK-Dialoge; projektspezifische Felder kommen aus projekt.json."""
import json
import logging
from datetime import datetime
from pathlib import Path
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gio, GLib, Gdk, Pango
from .model import PROJECT, ROOT, VERSION, config_dir, settings, save_settings, now, update_due
from .i18n import Strings
from .updates import release_info, download_update
from .languages import download_catalog, download_pack, import_pack
from .menus import compact_menus
from .jobs import JobRunner, Cancelled
from .logs import setup_logging, show_log
from .file_dialogs import choose
from .results import ResultList, example_rows
from .window_state import WindowState


def vertical(spacing=10, margin=16):
    return Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing,
                   margin_top=margin, margin_bottom=margin,
                   margin_start=margin, margin_end=margin)


class Application(Gtk.Application):
    def __init__(self, window_factory=None):
        self.window_factory = window_factory or MainWindow
        super().__init__(application_id='de.lehner.' + PROJECT['program_id'].replace('_', ''),
                         flags=Gio.ApplicationFlags.NON_UNIQUE)

    def do_activate(self):
        window = self.get_active_window()
        if window is None:
            window = self.window_factory(self)
        window.present()


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title=PROJECT['name'], default_width=760, default_height=480)
        self.opts = settings()
        languages = Strings.languages()
        self.tr = Strings(self.opts['language'] if self.opts['language'] in languages else 'en')
        self.bindings = []
        self.dialogs = []
        self.file_dialogs = []
        self.busy = False
        self.alive = True
        self.closing = False
        self.jobs = JobRunner(lambda callback: GLib.idle_add(lambda: (callback(), False)[1]))
        self.status_state = ('ready', {})
        self.progress_state = None
        self.job_progress_key = 'job_progress'
        self.pulse_timer = None
        self.progress_dialog = None
        self.job_title_key = 'loading'
        self.update_info=None
        self.update_status_key='software_checking'
        self.logger = setup_logging()
        self.logger.info(self.tr('started'), extra={'session_start': True})
        self.layout = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_child(self.layout)
        self.menu = Gtk.PopoverMenuBar()
        self.layout.append(self.menu)
        for name, callback in [('quit', lambda *_: self.request_quit()), ('settings', self.show_settings),
                               ('profiles', self.show_profiles),
                               ('log', lambda *_: show_log(self)),
                               ('export_results', self.export_results),
                               ('demo', self.start_demo), ('cancel_job', self.cancel_job),
                               ('choose_file', lambda *_: self.test_file_dialog('open')),
                               ('choose_folder', lambda *_: self.test_file_dialog('folder')),
                               ('save_file', lambda *_: self.test_file_dialog('save')),
                               ('help', self.show_help), ('tool_info',self.show_tool_info), ('about', self.show_about)]:
            action = Gio.SimpleAction.new(name, None)
            action.connect('activate', callback)
            self.add_action(action)
        app.set_accels_for_action('win.quit', ['<Primary>q'])
        app.set_accels_for_action('win.settings', ['<Primary>comma'])
        app.set_accels_for_action('win.help', ['F1'])
        app.set_accels_for_action('win.cancel_job', ['Escape'])
        area = Gtk.Overlay(vexpand=True)
        content = vertical()
        self.work = self.label('workspace', wrap=True, xalign=0, valign=Gtk.Align.START)
        content.append(self.work)
        self.results = ResultList(self, [('name', 'result_name'), ('status', 'result_status'), ('details', 'result_details')])
        content.append(self.results)
        if PROJECT.get('demo_enabled', False):
            self.results.set_rows(example_rows(self.tr))
        area.set_child(content)
        image = ROOT / PROJECT.get('watermark', 'assets/report_watermark.png')
        if image.is_file():
            watermark = Gtk.Picture.new_for_filename(str(image))
            watermark.set_size_request(200, 200)
            watermark.set_halign(Gtk.Align.CENTER)
            watermark.set_valign(Gtk.Align.CENTER)
            watermark.set_opacity(0.1)
            watermark.set_can_target(False)
            area.add_overlay(watermark)
        self.layout.append(area)
        self.progress = None
        self.status = self.label('ready', xalign=0, margin_start=16, margin_end=16, margin_bottom=12)
        self.layout.append(self.status)
        self.apply_language(self.tr.code)
        self.connect('close-request', self.on_close)
        self.timer = GLib.timeout_add_seconds(60, self.automatic_update)
        GLib.idle_add(self.initial_update)
        self.window_state = WindowState(self)

    def request_quit(self):
        """Request an explicit application exit; projects may override this."""
        self.close()

    def on_close(self, *_):
        if self.jobs.running:
            self.closing = True
            self.jobs.cancel()
            self.set_status('waiting_close')
            self.update_actions()
            return True
        self.alive = False
        self.window_state.save()
        try:
            save_settings(self.opts)
        except OSError:
            self.logger.error(self.tr('write_error'))
        GLib.source_remove(self.timer)
        for dialog in list(self.file_dialogs):
            dialog.destroy()
        self.file_dialogs.clear()
        for dialog in list(self.dialogs):
            dialog.destroy()
        self.logger.info(self.tr('ended'))
        for handler in list(self.logger.handlers):
            self.logger.removeHandler(handler)
            handler.close()
        return False

    def set_status(self, key, **values):
        self.status_state = (key, values)
        self.status.set_label(self.tr(key, **values))

    def update_actions(self):
        for name in ('demo', 'choose_file', 'choose_folder', 'save_file', 'profiles', 'export_results'):
            enabled = not self.busy and not self.closing
            if name == 'profiles':
                enabled = enabled and PROJECT.get('profiles_enabled', False)
            self.lookup_action(name).set_enabled(enabled)
        self.lookup_action('cancel_job').set_enabled(self.jobs.running and self.jobs.cancellable and not self.closing and not self.jobs.cancel_event.is_set())

    def label(self, key, **kwargs):
        widget = Gtk.Label(label=self.tr(key), **kwargs)
        self.bindings.append((widget, 'set_label', key))
        return widget

    def button(self, key, callback):
        widget = Gtk.Button(label=self.tr(key))
        widget.connect('clicked', callback)
        self.bindings.append((widget, 'set_label', key))
        return widget

    def track(self, window):
        self.dialogs.append(window)
        window.connect('close-request', lambda *_: self.forget_dialog(window))
        return window

    def forget_dialog(self, window):
        if window in self.dialogs:
            self.dialogs.remove(window)
        self.bindings[:] = [(widget, method, key) for widget, method, key in self.bindings
                            if widget.get_root() != window]
        return False

    def close_dialog(self, window):
        self.forget_dialog(window)
        window.destroy()

    def apply_language(self, code):
        self.tr = Strings(code)
        direction = Gtk.TextDirection.RTL if code.split('-')[0].split('_')[0] in ('ar', 'he', 'fa', 'ur') else Gtk.TextDirection.LTR
        Gtk.Widget.set_default_direction(direction)
        for widget, method, key in self.bindings:
            getattr(widget, method)(self.tr(key))
        for dialog in self.dialogs:
            if hasattr(dialog,'refresh_info'):dialog.refresh_info()
        self.set_status(self.status_state[0], **self.status_state[1])
        if self.progress_state:
            self.render_progress(*self.progress_state)
        if self.progress_dialog:
            self.progress_dialog.set_title(self.tr('progress_title'))
            self.progress_dialog.task_label.set_label(self.tr(self.job_title_key))
            self.progress_dialog.cancel_button.set_label(self.tr('job_cancel'))
        self.update_actions()
        self.refresh_update_controls()
        if hasattr(self, 'results'):
            if PROJECT.get('demo_enabled', False):
                self.results.set_rows(example_rows(self.tr))
            self.results.translate()
        model = Gio.Menu()
        file_menu = Gio.Menu()
        output = Gio.Menu()
        output.append(self.tr('results_export'), 'win.export_results')
        file_menu.append_section(None, output)
        if PROJECT.get('profiles_enabled', False):
            profiles = Gio.Menu()
            profiles.append(self.tr('profiles'), 'win.profiles')
            file_menu.append_section(None, profiles)
        preferences = Gio.Menu()
        preferences.append(self.tr('settings'), 'win.settings')
        if callable(getattr(self, 'reset_all_settings', None)):
            preferences.append(self.tr('reset_all_settings'), 'win.reset_all_settings')
        file_menu.append_section(None, preferences)
        ending = Gio.Menu()
        ending.append(self.tr('quit'), 'win.quit')
        file_menu.append_section(None, ending)
        model.append_submenu(self.tr('file'), file_menu)
        if PROJECT.get('demo_enabled', False):
            tools = Gio.Menu()
            run = Gio.Menu()
            run.append(self.tr('demo_start'), 'win.demo')
            run.append(self.tr('job_cancel'), 'win.cancel_job')
            tools.append_section(None, run)
            dialogs = Gio.Menu()
            for label, action in [('choose_file', 'choose_file'), ('choose_folder', 'choose_folder'), ('save_file', 'save_file')]:
                dialogs.append(self.tr(label), 'win.' + action)
            tools.append_section(None, dialogs)
            model.append_submenu(self.tr('tools'), tools)
        for title, actions in [('help', [('help', 'help'), ('log', 'log'), ('about', 'about')])]:
            submenu = Gio.Menu()
            if PROJECT.get('tool_info'):
                actions=actions[:-1]+[('info','tool_info')]+actions[-1:]
            for label, action in actions:
                entry=Gio.MenuItem.new(self.tr(label),'win.'+action)
                if action=='tool_info':entry.set_icon(Gio.ThemedIcon.new('dialog-information-symbolic'))
                submenu.append_item(entry)
            model.append_submenu(self.tr(title), submenu)
        self.menu.set_menu_model(model)
        compact_menus(self.menu)

    def notify(self, key, **values):
        dialog = self.track(Gtk.Window(title=PROJECT['name'], transient_for=self, modal=True,
                                       default_width=460))
        box = vertical()
        box.append(Gtk.Label(label=self.tr(key, **values), wrap=True, selectable=True))
        box.append(self.button('close', lambda *_: self.close_dialog(dialog)))
        dialog.set_child(box)
        dialog.present()

    def background(self, task, done, error_key='network_error', control=None, title_key='loading'):
        return self.start_job(lambda context: task(), done, error_key=error_key, control=control, title_key=title_key)

    def start_job(self, task, done, *, cancellable=False, error_key='job_error',
                  control=None, progress_key='job_progress', title_key='loading'):
        if self.busy or self.closing:
            return False
        def finish(result, error):
            self.busy = False
            if self.pulse_timer is not None:
                GLib.source_remove(self.pulse_timer)
                self.pulse_timer = None
            self.progress_state = None
            self.progress.set_visible(False)
            if self.progress_dialog:
                self.close_dialog(self.progress_dialog)
                self.progress_dialog = None
            if not self.alive:
                return
            if control and control.get_root() is not None:
                control.set_sensitive(True)
            self.update_actions()
            if isinstance(error, Cancelled):
                self.set_status('job_cancelled')
                self.logger.info(self.tr('job_cancelled'))
            elif error:
                if title_key=='checking_version':
                    self.update_info=None;self.update_status_key='software_check_failed'
                self.set_status('job_failed')
                self.logger.error('%s [%s]', self.tr(error_key), type(error).__name__,
                                  exc_info=(type(error), error, error.__traceback__))
                if not self.closing:
                    self.notify(error_key)
            elif not self.closing:
                self.set_status('job_completed')
                self.logger.info(self.tr('job_completed'))
                try:
                    done(result)
                except Exception as exc:
                    self.logger.error('%s [%s]', self.tr('write_error'), type(exc).__name__)
                    self.notify('write_error')
            self.refresh_update_controls()
            if self.closing:
                self.close()
        started = self.jobs.start(task, self.render_progress, finish, cancellable=cancellable)
        if started:
            self.busy = True
            self.job_progress_key = progress_key
            self.job_title_key = title_key
            self.progress_state = None
            self.show_progress_dialog(cancellable)
            self.progress.set_fraction(0)
            self.progress.set_text(self.tr('loading'))
            self.progress.set_visible(True)
            self.pulse_timer = GLib.timeout_add(120, self.pulse_progress)
            self.set_status('loading')
            self.logger.info(self.tr('job_started'))
            if control:
                control.set_sensitive(False)
            self.update_actions()
        return started

    def show_progress_dialog(self, cancellable):
        from .windows import center_after_map
        dialog = Gtk.Window(title=self.tr('progress_title'), transient_for=self,
                            modal=True, default_width=440, resizable=False)
        self.dialogs.append(dialog)
        box = vertical(spacing=14)
        dialog.set_child(box)
        dialog.task_label = Gtk.Label(label=self.tr(self.job_title_key), wrap=True, xalign=0)
        dialog.task_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        dialog.task_label.set_width_chars(45)
        context=dialog.task_label.get_pango_context()
        metrics=context.get_metrics(context.get_font_description(),context.get_language())
        height=4*((metrics.get_ascent()+metrics.get_descent()+Pango.SCALE-1)//Pango.SCALE)
        text_scroll=Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER,min_content_height=height,max_content_height=height)
        text_scroll.set_child(dialog.task_label)
        box.append(text_scroll)
        self.progress = Gtk.ProgressBar(show_text=True)
        box.append(self.progress)
        dialog.cancel_button = Gtk.Button(label=self.tr('job_cancel'), sensitive=cancellable)
        dialog.cancel_button.connect('clicked', self.cancel_job)
        if not cancellable:
            dialog.cancel_button.set_tooltip_text(self.tr('cannot_cancel'))
        box.append(dialog.cancel_button)
        def close_request(*_):
            self.cancel_job()
            return True  # erst schließen, wenn die Hintergrundarbeit tatsächlich beendet ist
        dialog.connect('close-request', close_request)
        self.progress_dialog = dialog
        dialog.present()
        center_after_map(dialog, self)

    def pulse_progress(self):
        if self.busy and self.progress_state is None:
            self.progress.pulse()
        return self.busy and self.alive

    def render_progress(self, current, total):
        self.progress_state = (current, total)
        self.progress.set_fraction(current / total)
        self.progress.set_text(self.tr(self.job_progress_key, current=current, total=total,
                                      percent=round(100 * current / total)))

    def cancel_job(self, *_):
        if self.jobs.cancel():
            self.set_status('job_cancelling')
            self.lookup_action('cancel_job').set_enabled(False)
            if self.progress_dialog:
                self.progress_dialog.cancel_button.set_sensitive(False)
                self.progress_dialog.task_label.set_label(self.tr('job_cancelling'))

    def start_demo(self, *_):
        from .demo import idle_demo
        return self.start_job(idle_demo, lambda duration: self.set_status('demo_finished', seconds=duration),
                              cancellable=True, progress_key='demo_progress', title_key='demo_title')

    def test_file_dialog(self, mode):
        if self.busy or self.closing:
            return
        actions = {'open': Gtk.FileChooserAction.OPEN, 'folder': Gtk.FileChooserAction.SELECT_FOLDER,
                   'save': Gtk.FileChooserAction.SAVE}
        keys = {'open': 'choose_file', 'folder': 'choose_folder', 'save': 'save_file'}
        def selected(path):
            if mode == 'save':
                path.write_text(self.tr('demo_file_text') + '\n', encoding='utf-8')
                self.set_status('file_saved', path=str(path))
            else:
                self.set_status('path_selected', path=str(path))
        return choose(self, keys[mode], selected, action=actions[mode],
                      filename=PROJECT['program_id'] + '-test.txt' if mode == 'save' else None,
                      filters=() if mode == 'folder' else ((self.tr('all_files'), ('*',)),))

    def source_ok(self, source):
        if not source.strip():
            self.notify('no_source')
            return False
        if 'xxxx' in source.split('/'):
            self.notify('repository_placeholder')
            return False
        return True

    def initial_update(self):
        if not self.busy:
            self.check_update(PROJECT['update_url'],automatic=True)
        return False

    def automatic_update(self):
        if not self.busy and update_due(self.opts) and 'xxxx' not in self.opts['update_url'].split('/'):
            self.check_update(self.opts['update_url'], automatic=True)
        return self.alive

    def refresh_update_controls(self):
        for dialog in self.dialogs:
            controls=getattr(dialog,'template_controls',{})
            if 'update_status' in controls:
                controls['update_status'].set_label(self.tr(self.update_status_key))
                newer=self.update_info and tuple(map(int,self.update_info['version'].split('.')))>tuple(map(int,VERSION.split('.')))
                controls['download'].set_sensitive(bool(newer and self.update_info.get('deb') and not self.busy))

    def check_update(self, source=None, automatic=False):
        source=PROJECT['update_url']
        if not source.strip() or 'xxxx' in source.split('/'):
            self.update_status_key='software_unconfigured';self.refresh_update_controls();return
        self.update_status_key='software_checking';self.refresh_update_controls()
        def done(info):
            self.update_info=info
            self.opts['last_update_check']=now();save_settings(self.opts)
            newer=tuple(map(int,info['version'].split('.')))>tuple(map(int,VERSION.split('.')))
            self.update_status_key='software_update' if newer else 'software_current'
            self.set_status(self.update_status_key)
            self.refresh_update_controls()
        self.background(lambda:release_info(source),done,title_key='checking_version',error_key='update_error')

    def download_available_update(self, *_):
        if not self.update_info:return
        info=self.update_info.copy()
        def done(path):
            self.notify('update_downloaded',path=str(path))
            self.refresh_update_controls()
        self.start_job(lambda context:download_update(info,context),done,cancellable=True,
                       error_key='update_download_error',title_key='update_download')
        self.refresh_update_controls()

    def show_help(self, *_):
        try:
            Gio.AppInfo.launch_default_for_uri(self.tr.help_path().as_uri(), None)
        except (GLib.Error, OSError):
            self.notify('help_error')

    def show_tool_info(self, *_):
        from .tool_info import show_tool_info
        return show_tool_info(self)

    def show_about(self, *_):
        dialog = self.track(Gtk.AboutDialog(transient_for=self, modal=True,
                        program_name=PROJECT['name'], version=VERSION, authors=PROJECT['authors'],
                        comments=self.tr('app_subtitle'), license_type=Gtk.License.GPL_3_0_ONLY))
        image = ROOT / PROJECT['image']
        if image.is_file():
            dialog.set_logo(Gdk.Texture.new_from_filename(str(image)))
        dialog.present()
        return dialog

    def show_profiles(self, *_):
        from .profile_dialog import show_profiles
        return show_profiles(self)

    def export_results(self, *_):
        from .export import show_export
        return show_export(self)

    def show_settings(self, *_):
        for existing in self.dialogs:
            if existing.get_name() == 'settings_dialog' and existing.get_visible():
                existing.present()
                return existing
        window = self.track(Gtk.Window(title=self.tr('settings'), transient_for=self, modal=True,
                                       default_width=650, default_height=700))
        window.set_name('settings_dialog')
        layout = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        window.set_child(layout)
        scroll = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        layout.append(scroll)
        box = vertical()
        scroll.set_child(box)
        controls = {}
        def group(key):
            if box.get_first_child() is not None:
                box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
            box.append(self.label(key, xalign=0, wrap=True))
        codes = Strings.languages()
        language = Gtk.DropDown.new_from_strings([self.tr.language_name(code) for code in codes])
        language.set_selected(codes.index(self.tr.code))
        def refresh(code):
            if window not in self.dialogs:
                return
            codes[:] = Strings.languages()
            language.set_model(Gtk.StringList.new([self.tr.language_name(c) for c in codes]))
            language.set_selected(codes.index(code))
            self.set_status('installed')
        if PROJECT['settings']:
            group('program_settings')
            for field in PROJECT['settings']:
                if field.get('settings_visible', True) is False:
                    continue
                if field['type'] == 'boolean':
                    widget = Gtk.CheckButton(label=self.tr(field['label']))
                    widget.set_active(self.opts[field['key']])
                    box.append(widget)
                elif field['type'] == 'number':
                    row = Gtk.Box(spacing=8)
                    row.append(self.label(field['label'], xalign=0, hexpand=True, wrap=True))
                    widget = Gtk.SpinButton.new_with_range(field['min'], field['max'], 1)
                    widget.set_value(self.opts[field['key']])
                    row.append(widget)
                    box.append(row)
                else:
                    row = Gtk.Box(spacing=8)
                    row.append(self.label(field['label'], xalign=0, hexpand=True, wrap=True))
                    widget = Gtk.Entry(hexpand=True)
                    widget.set_text(self.opts[field['key']])
                    row.append(widget)
                    box.append(row)
                controls[field['key']] = widget
        group('update_settings')
        automatic = Gtk.CheckButton(label=self.tr('update_check'), active=self.opts['update_check'])
        box.append(automatic)
        box.append(self.label('update_interval_label', xalign=0, wrap=True))
        row = Gtk.Box(spacing=8)
        row.append(self.label('every'))
        interval = Gtk.SpinButton.new_with_range(1, 365, 1)
        interval.set_value(self.opts['update_interval_value'])
        row.append(interval)
        units = ('days', 'weeks', 'months')
        unit = Gtk.DropDown.new_from_strings([self.tr(u) for u in units])
        unit.set_selected(units.index(self.opts['update_interval_unit']))
        row.append(unit)
        box.append(row)
        box.append(self.label('update_interval_help', xalign=0, wrap=True))
        update_status=Gtk.Label(xalign=0,wrap=True)
        box.append(update_status)
        download=self.button('update_download',self.download_available_update)
        download.set_sensitive(False);box.append(download)
        group('language_extensions')
        box.append(self.label('language', xalign=0))
        box.append(language)
        box.append(self.button('import_language', lambda *_: self.import_language(window, refresh)))
        box.append(self.button('download_language', lambda *_: self.download_language(PROJECT['source_url'], window, refresh)))
        def save(*_):
            new = self.opts.copy()
            interval.update()
            new.update(language=codes[language.get_selected()], update_check=automatic.get_active(),
                       update_interval_value=interval.get_value_as_int(),
                       update_interval_unit=units[unit.get_selected()])
            for key, widget in controls.items():
                if isinstance(widget, Gtk.SpinButton):
                    widget.update()
                    new[key] = widget.get_value_as_int()
                elif isinstance(widget, Gtk.CheckButton):
                    new[key] = widget.get_active()
                else:
                    new[key] = widget.get_text()
            try:
                save_settings(new)
            except OSError:
                self.notify('write_error')
                return
            self.opts = new
            self.close_dialog(window)
            self.apply_language(new['language'])
            self.set_status('saved')
            self.logger.info(self.tr('saved'))
        layout.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        footer = Gtk.Box(spacing=10, halign=Gtk.Align.END, margin_top=12, margin_bottom=12,
                         margin_start=16, margin_end=16)
        cancel = self.button('cancel', lambda *_: self.close_dialog(window))
        save_button = self.button('save_settings', save)
        footer.append(cancel)
        footer.append(save_button)
        layout.append(footer)
        # Prüfzugang und Erweiterungspunkt für Projekte.
        window.template_controls = dict(language=language, codes=codes, fields=controls,
                        interval=interval, unit=unit, update_status=update_status, download=download,
                        automatic=automatic, save=save_button, cancel=cancel)
        self.refresh_update_controls()
        window.present()
        return window

    def import_language(self, parent, refresh):
        return choose(self, 'import_language',
               lambda path: self.background(lambda: import_pack(path), refresh, 'pack_error', title_key='installing_language'),
               parent=parent, filters=(('JSON', ('*.json',)),))

    def download_language(self, source, parent, refresh):
        if not self.source_ok(source):
            return
        def catalog_loaded(entries):
            if parent not in self.dialogs:
                return
            entries = [entry for entry in entries if entry['code'] not in Strings.languages()]
            if not entries:
                self.notify('no_downloads')
                return
            window = self.track(Gtk.Window(title=self.tr('choose_language'), transient_for=parent,
                                           modal=True, default_width=420))
            box = vertical()
            choose = Gtk.DropDown.new_from_strings([entry['name'] for entry in entries])
            box.append(choose)
            def install(*_):
                code = entries[choose.get_selected()]['code']
                def done(code):
                    self.close_dialog(window)
                    refresh(code)
                self.background(lambda: download_pack(source, code), done, 'pack_error', button, title_key='installing_language')
            button = self.button('download_language', install)
            box.append(button)
            box.append(self.button('cancel', lambda *_: self.close_dialog(window)))
            window.set_child(box)
            window.present()
        self.background(lambda: download_catalog(source), catalog_loaded, title_key='loading_languages')
