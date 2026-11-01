"""Native desktop front end; camera commands run outside the GTK main thread."""
from pathlib import Path
from datetime import datetime
import json
import os
import time
import threading
import gi
gi.require_version('Gtk','4.0')
gi.require_version('GdkPixbuf','2.0')
from gi.repository import Gtk, Gdk, GdkPixbuf, Gio, GLib
from josef_basis.gui import MainWindow, vertical
from josef_basis.model import ROOT, PROJECT, VERSION, DEFAULTS, save_settings, config_dir, atomic_json
from josef_basis.menus import compact_menus
from josef_basis.logs import show_log
from .studio import Studio
from .speech import SpeechControls
from .video import RECORDERS,camera_coordinates
from .display import response_text
from . import uvc
from .backend import Backend
from .video import Video,AudioRecorder,AUDIO_RECORDERS,microphones,cameras,camera_microphone

GROUPS = {
 'steering':['gimbal_move','gimbal_recenter','zoom_uvc','zoom_vendor','gimbal_position','aim_at_pixel','zoom_to_fit'],
 'tracking':['ai_track','ai_track_speed','focus_face'],
 'image':['focus_auto','focus_manual','image_fov','image_hdr','image_wb_auto','image_wb_manual','image_adjust','image_exposure_auto','image_exposure_manual'],
 'presets':['preset_list','preset_save','preset_recall','preset_update','preset_rename','preset_delete'],
}

# These actions either move the gimbal or capture a pose that AI tracking may
# change while the action runs. Keep them unavailable until tracking is off.
TRACKING_CONFLICTS = {
 'gimbal_move','gimbal_recenter','aim_at_pixel','zoom_to_fit',
 'preset_save','preset_recall','preset_update',
}

class CameraWindow(SpeechControls,Studio,MainWindow):
    def __init__(self, app, *, auto_preview=True):
        self.resetting_settings=False
        self.used_tiny=set()
        self.shutdown_requested=False
        self.explicit_quit=False
        self.shutdown_in_progress=False
        self.shutdown_ready=False
        self.close_timer=None
        self.camera_ready = False
        self.catalog = {}
        self.video = None
        self.bridge = None
        self.camera_serial = ''
        self.ai_mode = None
        self.camera_devices = []
        self.selected_device = None
        self.uvc_controls = []
        self.uvc_get = None
        self.auto_preview=auto_preview
        self.output_window=None
        self.output_is_fullscreen=False
        self.camera_loading=True
        self.preview_request=0
        self.last_result = None
        self.command_error_detail = None
        self.pages = {}
        self.selection = {}
        try:
            saved = json.loads((config_dir()/'tracking.json').read_text('utf-8'))
            self.tracking_values = saved if isinstance(saved,dict) else {}
        except (OSError,ValueError,UnicodeError):
            self.tracking_values = {}
        super().__init__(app)
        self.set_title(f"{PROJECT['name']} – {self.tr('settings')} {VERSION}")
        Gtk.IconTheme.get_for_display(self.get_display()).add_search_path(str(ROOT/"assets"))
        self.set_icon_name("tiny")
        if not (config_dir()/'settings.json').is_file():
            self.set_default_size(1180,800)
        self.bridge = Backend(self.logger,runtime_dir=config_dir()/'ipc')
        self.video = Video(self.video_error)
        self.audio_recorder=AudioRecorder()
        self.frame_seen = None
        self.last_camera_response = None
        self.video_failure_pending = False
        self.last_poll = time.monotonic()
        self.polling = False
        old = self.layout.get_first_child().get_next_sibling()
        self.layout.remove(old)
        self.body = vertical(margin=16)
        self.layout.insert_child_after(self.body,self.menu)
        self.heading=Gtk.Label(label=self.tr('camera'),xalign=0)
        self.heading.add_css_class('title-1')
        self.body.append(self.heading)
        self.device_row = Gtk.Box(spacing=12)
        self.device_row.append(self.label('camera',xalign=0))
        self.camera_choice = Gtk.DropDown.new_from_strings([self.tr('no_camera')])
        self.camera_choice.set_hexpand(True)
        self.device_row.append(self.camera_choice)
        self.body.append(self.device_row)
        self.camera_state = self.label('no_live_status',xalign=0,wrap=True)
        self.camera_state.add_css_class('camera-status')
        self.body.append(self.camera_state)
        self.camera_choice.connect('notify::selected',self.on_camera_selected)
        self.device_paths = []
        self.device_serials = []
        self.stack = Gtk.Stack(vexpand=True,hexpand=True)
        self.stack.set_transition_type(Gtk.StackTransitionType.NONE)
        self.nav_rows={}
        self.nav_list=Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.nav_list.add_css_class('camera-nav')
        self.nav_list.connect('row-selected',self.on_navigation_selected)
        self.stack.connect('notify::visible-child-name',self.sync_navigation)
        split=Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL,vexpand=True)
        side_scroll=Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        side_scroll.set_child(self.nav_list);side_scroll.set_size_request(230,-1)
        split.set_start_child(side_scroll);split.set_end_child(self.stack)
        split.set_position(235);split.set_shrink_start_child(False)
        self.body.append(split)
        self.build_live()
        for group in GROUPS:
            self.build_tool_page(group)
            if group=='tracking':self.build_speech_page()
        self.build_uvc_page()
        self.diagnostics = Gtk.TextView(editable=False,cursor_visible=False,monospace=True,wrap_mode=Gtk.WrapMode.WORD_CHAR)
        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.set_child(self.diagnostics)
        page = vertical(margin=8)
        page.append(self.label('diagnostics_heading',xalign=0))
        page.append(scroll)
        self.pages['diagnostics'] = self.add_stack_page(page,'diagnostics')
        self.build_studio()
        # Keep diagnostics omitted; the existing camera-control pages are
        # available in the sidebar again.
        self.pages['diagnostics'].set_visible(False)
        self.nav_rows['diagnostics'].set_visible(False)
        self.stack.set_visible_child_name('format')
        self.camera_ready = True
        self.add_camera_actions()
        for key in ('mirror_horizontal','audio_enabled'):
            action = Gio.SimpleAction.new_stateful(key,None,GLib.Variant('b',self.opts[key]))
            action.connect('activate',lambda action,_,key=key:self.set_media_option(key,not action.get_state().get_boolean()))
            self.add_action(action)
        self.apply_language(self.tr.code)
        self.render_timer = GLib.timeout_add(40,self.render)
        self.refresh_devices()
        # Wait until Gtk.Application has presented the settings window, then
        # raise the separate live-output window as well.
        GLib.idle_add(self.show_output)

    def add_stack_page(self,content,name):
        # Scrollable pages let the window shrink enough for Cinnamon tiling.
        scroll=Gtk.ScrolledWindow(hexpand=True,vexpand=True,
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            vscrollbar_policy=Gtk.PolicyType.AUTOMATIC)
        scroll.set_min_content_width(0)
        scroll.set_min_content_height(0)
        scroll.set_child(content)
        page=self.stack.add_titled(scroll,name,self.tr(name))
        row=Gtk.ListBoxRow()
        row.set_name(name)
        item=Gtk.Box(spacing=10,margin_top=5,margin_bottom=5,margin_start=7,margin_end=7)
        icon_path=ROOT/'assets'/'nav'/f'{name}.svg'
        icon=Gtk.Image.new_from_file(str(icon_path))
        icon.set_pixel_size(48)
        icon.set_size_request(48,48)
        icon.add_css_class('camera-nav-icon')
        label=Gtk.Label(label=self.tr(name),xalign=0,hexpand=True,wrap=True)
        self.bindings.append((label,'set_label',name))
        item.append(icon)
        item.append(label)
        row.set_child(item)
        self.nav_list.append(row)
        self.nav_rows[name]=row
        self.sync_navigation()
        return page

    def on_navigation_selected(self,_list,row):
        if row:
            self.stack.set_visible_child_name(row.get_name())

    def sync_navigation(self,*_):
        name=self.stack.get_visible_child_name()
        row=self.nav_rows.get(name)
        if row and row.get_visible():
            self.nav_list.select_row(row)

    def build_live(self):
        self.output_window = Gtk.ApplicationWindow(
            application=self.get_application(),
            title=f"{PROJECT['name']} – {self.tr('live')}",
            default_width=960,
            default_height=600,
        )
        self.output_window.set_icon_name('tiny')
        self.output_window.connect('close-request',self.on_output_close)
        key_controller=Gtk.EventControllerKey()
        key_controller.connect('key-pressed',self.on_output_key_pressed)
        self.output_window.add_controller(key_controller)
        self.preview = Gtk.Picture(hexpand=True,vexpand=True,can_shrink=True)
        self.preview.set_content_fit(Gtk.ContentFit.CONTAIN)
        self.preview.add_css_class('camera-preview')
        self.preview.set_size_request(240,135)
        self.preview.set_alternative_text(self.tr('preview_alt'))
        overlay = Gtk.Overlay(vexpand=True)
        overlay.set_margin_start(20)
        overlay.set_margin_end(20)
        overlay.set_margin_bottom(20)
        self.preview_overlay=overlay
        overlay.set_child(self.preview)
        watermark = Gtk.Picture.new_for_paintable(Gdk.Texture.new_for_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_scale(str(ROOT/'assets/report_watermark.png'),90,90,True)))
        watermark.set_size_request(90,90)
        watermark.set_halign(Gtk.Align.END)
        watermark.set_valign(Gtk.Align.END)
        watermark.set_margin_end(16)
        watermark.set_margin_bottom(16)
        watermark.set_opacity(.1)
        watermark.set_can_target(False)
        overlay.add_overlay(watermark)
        self.output_window.set_child(overlay)
        css = Gtk.CssProvider()
        css.load_from_data(b'''
            .camera-preview { background: #121b27; border-radius: 8px; }
            .camera-preview.fullscreen { border-radius: 0; }
            .camera-nav { padding: 6px; background: linear-gradient(to right, #f5f8fb, #e4eaf1); border-right: 1px solid #b8c4cf; }
            .camera-nav row { margin: 4px 5px; padding: 7px; border: 1px solid #c5d0da; border-radius: 9px; background: linear-gradient(to bottom, #ffffff, #e8eef4); box-shadow: 0 2px 4px rgba(22, 43, 61, 0.22); }
            .camera-nav row:selected { background: linear-gradient(to bottom, #49b8e5, #168fc2); border-color: #087cac; color: #ffffff; box-shadow: 0 3px 6px rgba(8, 76, 108, 0.35); }
            .camera-nav image { color: #078bb8; }
            .camera-nav row:selected image { color: #ffffff; }
            .camera-status { padding: 9px 13px; border: 1px solid #158bb6; border-radius: 9px; background: linear-gradient(to bottom, #e8f8fd, #c7eaf5); color: #16394a; font-weight: 700; box-shadow: 0 2px 5px rgba(12, 93, 124, 0.2); }
            .camera-status-awake { border-color: #278554; background: linear-gradient(to bottom, #e9f8ee, #ccebd6); color: #17442b; }
            .camera-status-asleep { border-color: #c27b19; background: linear-gradient(to bottom, #fff6e4, #f5e2bc); color: #503607; }
            .title-1 { color: #3584e4; }
            .tool-card { padding: 12px; border: 1px solid #c5d0da; border-radius: 10px; }
            .tool-choice-card { background: linear-gradient(to bottom, #edf8fc, #e5f0f6); }
            .tool-settings-card { background: #f5f7fa; }
            .tool-result-card { padding: 10px; border: 1px solid #8ebbd0; border-radius: 8px; background: #e8f5fa; }
            .tool-card-title { color: #145c7a; font-weight: 700; }
        ''')
        Gtk.StyleContext.add_provider_for_display(self.get_display(),css,Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def on_output_close(self,*_):
        # Closing the preview must not stop its stream or close the settings window.
        self.output_window.set_visible(False)
        if not self.get_visible():
            self.present()
        return True

    def on_output_key_pressed(self,_controller,keyval,_keycode,_state):
        if keyval==Gdk.KEY_F11:
            self.toggle_output_fullscreen()
            return True
        return False

    def show_output(self,*_):
        if self.output_window:
            self.output_window.present()

    def toggle_output_fullscreen(self,*_):
        if not self.output_window:
            return
        self.output_is_fullscreen=not self.output_is_fullscreen
        if self.output_is_fullscreen:
            self.preview_overlay.set_margin_start(0)
            self.preview_overlay.set_margin_end(0)
            self.preview_overlay.set_margin_bottom(0)
            self.preview.add_css_class('fullscreen')
            self.output_window.fullscreen()
        else:
            self.output_window.unfullscreen()
            self.preview_overlay.set_margin_start(20)
            self.preview_overlay.set_margin_end(20)
            self.preview_overlay.set_margin_bottom(20)
            self.preview.remove_css_class('fullscreen')

    def request_quit(self):
        self.explicit_quit=True
        self.close()

    def build_tool_page(self, group):
        page = vertical(margin=8)
        title = self.label(group+'_heading',xalign=0,wrap=True)
        title.add_css_class('title-2')
        page.append(title)
        if group == 'steering':
            self.linux_note = self.label('linux_hint',xalign=0,wrap=True)
            page.append(self.linux_note)
        choice_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=8)
        choice_card.add_css_class('tool-card')
        choice_card.add_css_class('tool-choice-card')
        choice_title = self.label('tool_selection',xalign=0)
        choice_title.add_css_class('tool-card-title')
        choice_card.append(choice_title)
        choice = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        tool_rows=[]
        for name in GROUPS[group]:
            tool_row=Gtk.ListBoxRow(child=Gtk.Label(label=self.tr(name),xalign=0,wrap=True))
            choice.append(tool_row)
            tool_rows.append(tool_row)
        choice_card.append(choice)
        availability_note=Gtk.Label(xalign=0,wrap=True)
        availability_note.add_css_class('dim-label')
        availability_note.set_visible(False)
        choice_card.append(availability_note)
        page.append(choice_card)
        if GROUPS[group]:choice.select_row(choice.get_row_at_index(0))
        settings_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=8)
        settings_card.add_css_class('tool-card')
        settings_card.add_css_class('tool-settings-card')
        settings_title = self.label('tool_settings',xalign=0)
        settings_title.add_css_class('tool-card-title')
        settings_card.append(settings_title)
        settings_card.append(self.label('tool_hint',xalign=0,wrap=True))
        hint = Gtk.Label(xalign=0,wrap=True)
        settings_card.append(hint)
        result_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=4)
        result_box.add_css_class('tool-result-card')
        result_box.append(self.label('tool_result',xalign=0))
        result_text = Gtk.Label(xalign=0,wrap=True,selectable=True)
        result_box.append(result_text)
        result_box.set_visible(False)
        settings_card.append(result_box)
        fields = vertical(margin=0)
        scroll = Gtk.ScrolledWindow(vexpand=True,hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroll.set_child(fields)
        settings_card.append(scroll)
        apply_button = self.button('apply_tool', lambda *_: self.apply_tool())
        apply_button.set_halign(Gtk.Align.START)
        settings_card.append(apply_button)
        page.append(settings_card)
        self.selection[group] = dict(choice=choice,fields=fields,widgets={},hint=hint,
            choice_title=choice_title,settings_title=settings_title,
            result_box=result_box,result_text=result_text,tool_rows=tool_rows,
            availability_note=availability_note,apply_button=apply_button)
        choice.connect('row-selected',lambda _choice,row:self.on_tool_row_selected(group,row))
        self.build_fields(group)
        self.update_tool_availability()
        self.pages[group] = self.add_stack_page(page,group)

    def on_tool_row_selected(self,group,row):
        if row is None:
            return
        tool=self.tool_for_row(group,row)
        if not tool:return
        if tool in TRACKING_CONFLICTS and self.ai_mode!='no-tracking':
            # A row may have been selected before the camera status arrived,
            # or GTK may report a stale selection after it became unavailable.
            self.update_tool_availability()
            return
        self.build_fields(group)

    def tool_for_row(self,group,row):
        """Resolve a choice row by its position; GtkListBoxRow.get_name() is a GTK type name."""
        section=self.selection.get(group)
        if not section or row is None:return None
        try:index=section['tool_rows'].index(row)
        except ValueError:return None
        return GROUPS[group][index] if index<len(GROUPS[group]) else None

    def update_tool_availability(self):
        tracking_on=self.ai_mode not in (None,'unknown','no-tracking')
        status_unknown=self.ai_mode in (None,'unknown')
        for group,section in self.selection.items():
            selected=section['choice'].get_selected_row()
            selected_tool=self.tool_for_row(group,selected)
            has_conflicts=any(tool in TRACKING_CONFLICTS for tool in GROUPS[group])
            if has_conflicts:
                note=section['availability_note']
                note.set_label(self.tr('tracking_conflict' if tracking_on else 'tracking_status_unknown'))
                note.set_visible(tracking_on or status_unknown)
            for index,tool in enumerate(GROUPS[group]):
                if tool not in TRACKING_CONFLICTS:continue
                row=section['tool_rows'][index]
                blocked=tracking_on or status_unknown
                row.set_sensitive(not blocked)
                row.set_selectable(not blocked)
                row.set_activatable(not blocked)
                row.set_tooltip_text(self.tr('tracking_conflict' if tracking_on else 'tracking_status_unknown') if blocked else None)
            blocked=tracking_on or status_unknown
            needs_fallback=blocked and (
                selected_tool in TRACKING_CONFLICTS or (selected_tool is None and has_conflicts))
            if needs_fallback:
                if selected:
                    section['choice'].unselect_row(selected)
                fallback='gimbal_position' if group=='steering' else next(
                    (tool for tool in GROUPS[group] if tool not in TRACKING_CONFLICTS),None)
                if fallback:
                    section['choice'].select_row(section['tool_rows'][GROUPS[group].index(fallback)])
            selected=section['choice'].get_selected_row()
            selected_tool=self.tool_for_row(group,selected)
            section['apply_button'].set_sensitive(
                selected_tool not in TRACKING_CONFLICTS or not (tracking_on or status_unknown))

    def build_fields(self, group):
        section = self.selection[group]
        row=section['choice'].get_selected_row()
        if row is None:return
        tool = self.tool_for_row(group,row)
        if not tool:return
        section['hint'].set_label(self.tr('hint_'+tool))
        box = section['fields']
        while box.get_first_child():
            box.remove(box.get_first_child())
        section['widgets'] = {}
        definition = self.catalog.get('obsbot_'+tool)
        if not definition:
            box.append(Gtk.Label(label=self.tr('backend_unavailable'),xalign=0,wrap=True))
            return
        schema = definition['inputSchema']
        for name, spec in schema.get('properties',{}).items():
            # Tiny 2 exposes yaw/pitch movement, but no controllable roll axis.
            # The backend schema keeps its zero default for transport compatibility;
            # don't present a fixed, non-functional input in the desktop UI.
            if name == 'roll':
                continue
            # zod preprocess/pipe emits numeric constraints inside allOf.
            combined = {}
            for part in spec.get('allOf',[]):
                combined.update(part)
            combined.update({k:v for k,v in spec.items() if k != 'allOf'})
            spec = combined
            if name in ('camera','source'):
                continue
            row = Gtk.Box(spacing=16)
            label = Gtk.Label(label=self.tr('field_'+name),xalign=0,hexpand=True,wrap=True)
            row.append(label)
            kind = spec.get('type')
            options = spec.get('enum')
            if options is None and spec.get('anyOf'):
                options = [x['const'] for x in spec['anyOf'] if 'const' in x]
            if options:
                widget = Gtk.DropDown.new_from_strings([self.tr('value_'+str(x)) for x in options])
                default = spec.get('default')
                if default in options:
                    widget.set_selected(options.index(default))
                get = lambda widget=widget,options=options: options[widget.get_selected()]
            elif kind == 'boolean':
                widget = Gtk.Switch(active=spec.get('default',False),valign=Gtk.Align.CENTER)
                get = widget.get_active
            elif kind in ('number','integer'):
                limits = {'yaw':(-150,150,0),'pitch':(-90,90,0),'roll':(0,0,0),
                    'ratio':(1,2,1),'speed':(0,100,0),'temperature':(2000,10000,5000),
                    'x':(0,7680,0),'y':(0,4320,0),'width':(1,7680,640),'height':(1,4320,360),
                    'frameWidth':(1,7680,1280),'frameHeight':(1,4320,720),'margin':(0,1,.1)}
                low,high,default = limits.get(name,(0,100,50))
                # JSON Schema represents the preset slot's numeric union
                # (1 | 2 | 3) as anyOf/const values rather than minimum and
                # maximum. Preserve that constraint in the editor instead of
                # showing the generic 0–100 range with an invalid value of 50.
                numeric_choices = [
                    part['const'] for part in spec.get('anyOf',[])
                    if isinstance(part.get('const'), (int,float))
                    and not isinstance(part.get('const'), bool)
                ]
                # The generated MCP schema currently drops the literal union
                # constraint for preset slots, so retain the device contract
                # in the UI as well: OBSBOT presets only have slots 1–3.
                if tool == 'preset_save' and name == 'slot':
                    numeric_choices = [1,2,3]
                if numeric_choices:
                    low, high = min(numeric_choices), max(numeric_choices)
                    default = low
                else:
                    low,high = spec.get('minimum',low),spec.get('maximum',high)
                widget = Gtk.SpinButton.new_with_range(low,high,.01 if name in ('ratio','margin') else 1)
                widget.set_digits(2 if name in ('ratio','margin') else 0)
                widget.set_value(spec.get('default',default))
                get = widget.get_value_as_int if kind=='integer' else widget.get_value
            else:
                widget = Gtk.Entry()
                widget.set_text(str(spec.get('default','')))
                if name == 'name':
                    widget.set_max_length(40)
                get = widget.get_text
            widget.set_size_request(180,-1)
            row.append(widget)
            box.append(row)
            section['widgets'][name] = (widget,get)
            if group == 'tracking':
                saved = self.tracking_values.get(tool,{})
                value = saved.get(name) if isinstance(saved,dict) else None
                if options and value in options:
                    widget.set_selected(options.index(value))
                elif kind == 'boolean' and type(value) is bool:
                    widget.set_active(value)
                signal = 'notify::selected' if options else 'notify::active' if kind == 'boolean' else None
                if signal:
                    def remember(*_,tool=tool,name=name,get=get):
                        if self.resetting_settings:return
                        values = self.tracking_values.get(tool)
                        if not isinstance(values,dict):
                            values = {}; self.tracking_values[tool] = values
                        values[name] = get()
                        try:atomic_json(config_dir()/'tracking.json',self.tracking_values)
                        except OSError:
                            self.logger.exception('Tracking-Einstellungen konnten nicht gespeichert werden')
                            self.notify('write_error')
                    widget.connect(signal,remember)

    def build_uvc_page(self):
        page=vertical(margin=8)
        title=self.label('uvc_heading',xalign=0);title.add_css_class('title-2');page.append(title)
        page.append(self.label('uvc_hint',xalign=0,wrap=True))
        self.uvc_choice=Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.uvc_choice.connect('row-selected',lambda *_:self.build_uvc_field())
        page.append(self.uvc_choice)
        self.uvc_fields=vertical(margin=0)
        page.append(self.uvc_fields)
        self.camera_defaults_button=self.button('camera_defaults',lambda *_:self.reset_camera_defaults())
        self.camera_defaults_button.set_halign(Gtk.Align.START)
        page.append(self.camera_defaults_button)
        self.pages['uvc']=self.add_stack_page(page,'uvc')

    def build_uvc_field(self):
        if not hasattr(self,'uvc_fields'):return
        box=self.uvc_fields
        while box.get_first_child():box.remove(box.get_first_child())
        self.uvc_get=None
        row=self.uvc_choice.get_selected_row()
        index=row.get_index() if row else -1
        if index<0 or index>=len(self.uvc_controls):
            box.append(Gtk.Label(label=self.tr('uvc_no_controls'),xalign=0,wrap=True))
            return
        control=self.uvc_controls[index]
        if not uvc.reversible(control) or (self.selected_device and self.selected_device['kind']=='tiny2' and control['key'] in uvc.TINY_EXPOSURE_CONTROLS):
            self.uvc_widget=Gtk.Label(label=self.tr('uvc_unreliable'),xalign=0,wrap=True)
            self.uvc_widget.set_sensitive(False)
            box.append(self.uvc_widget)
            box.append(Gtk.Label(label=self.tr('uvc_range',minimum=control['minimum'],maximum=control['maximum'],step=control['step'],value=control['value']),xalign=0,wrap=True))
            return
        if control['kind']==2:
            widget=Gtk.Switch(active=bool(control['value']),halign=Gtk.Align.START)
            self.uvc_get=lambda:int(widget.get_active())
        elif control['kind'] in (3,9):
            choices=control['choices']
            names=[self.uvc_menu_label(control['key'],value,label) for value,label in choices]
            widget=Gtk.DropDown.new_from_strings(names)
            values=[x[0] for x in choices]
            if control['value'] in values:widget.set_selected(values.index(control['value']))
            self.uvc_get=lambda:values[widget.get_selected()]
        else:
            widget=Gtk.SpinButton.new_with_range(control['minimum'],control['maximum'],control['step'])
            widget.set_value(control['value'])
            widget.set_snap_to_ticks(True)
            self.uvc_get=widget.get_value_as_int
        widget.set_sensitive(not bool(control['flags']&(2|4|16)))
        self.uvc_widget=widget
        box.append(widget)
        box.append(Gtk.Label(label=self.tr('uvc_range',minimum=control['minimum'],maximum=control['maximum'],step=control['step'],value=control['value']),xalign=0,wrap=True))
        if not uvc.valid_value(control,control['value']) or not uvc.valid_value(control,control.get('default',control['value'])):
            box.append(Gtk.Label(label=self.tr('uvc_unreliable'),xalign=0,wrap=True))
        if control['flags']&16:
            box.append(Gtk.Label(label=self.tr('uvc_inactive'),xalign=0,wrap=True))

    def control_label(self,control):
        key='uvc_'+control['key'];label=self.tr(key)
        return control.get('name',key) if label==key else label

    def uvc_menu_label(self,key,value,fallback):
        translation={'exposure_auto':{1:'manual',3:'auto'},'power_line':{0:'off',1:'50hz',2:'60hz'}}
        token=translation.get(key,{}).get(value)
        return self.tr('uvc_value_'+token) if token else fallback

    def set_uvc_controls(self,controls,selected_id=None):
        controls=[c for c in controls if not (self.selected_device and self.selected_device['kind']=='tiny2' and c['key'] in uvc.MOTION_CONTROLS)]
        self.uvc_controls=list(controls)
        while self.uvc_choice.get_first_child():self.uvc_choice.remove(self.uvc_choice.get_first_child())
        for control in controls:
            self.uvc_choice.append(Gtk.ListBoxRow(child=Gtk.Label(label=self.control_label(control),xalign=0,wrap=True)))
        ids=[c['id'] for c in controls]
        if controls:self.uvc_choice.select_row(self.uvc_choice.get_row_at_index(ids.index(selected_id) if selected_id in ids else 0))
        self.build_uvc_field()

    def apply_uvc(self):
        row=self.uvc_choice.get_selected_row()
        index=row.get_index() if row else -1
        if not self.selected_device or index<0 or index>=len(self.uvc_controls) or not self.uvc_get:return
        control=self.uvc_controls[index]
        if control['flags']&(1|2|4|16) or not uvc.reversible(control):
            self.notify('uvc_inactive');return
        path=self.selected_device['path'];value=self.uvc_get()
        def work():
            actual=uvc.write_control(path,control['id'],value)
            return actual,uvc.read_controls(path)
        def done(data):
            actual,controls=data
            self.selected_device['controls']=controls
            self.set_uvc_controls(controls,control['id'])
            self.last_result=('uvc_applied',dict(control=control['key'],value=actual))
            self.last_camera_response=dict(camera=self.camera_name(self.selected_device),control=control['key'],value=actual)
            details=response_text(self.last_camera_response,self.tr)
            self.results.set_rows([dict(name=self.tr('uvc_'+control['key']),status='ok',details=details)])
            self.logger.info(self.tr('uvc_applied',control=self.tr('uvc_'+control['key']),value=actual))
            self.refresh_result()
        self.background(work,done,error_key='camera_error',title_key='camera_working')

    def add_camera_actions(self):
        for name, fn in [('refresh',self.refresh_devices),('preview_start',self.start_preview),
                ('preview_stop',self.stop_preview),('snapshot',self.snapshot),('record_start',self.record),
                ('record_stop',self.stop_record),('apply_tool',self.apply_tool),
                ('wake',lambda:self.command('wake',{})),('sleep',self.sleep_camera),
                ('check_environment',self.environment),('show_output',self.show_output),
                ('toggle_output_fullscreen',self.toggle_output_fullscreen),
                ('reset_all_settings',self.reset_all_settings)]:
            action = Gio.SimpleAction.new(name,None)
            action.connect('activate',lambda *_,fn=fn:fn())
            self.add_action(action)
        for name,shortcut in [('refresh','F5'),('preview_start','<Primary>l'),('snapshot','<Primary>s'),
                              ('record_start','<Primary>r'),('record_stop','<Primary><Shift>r'),('apply_tool','<Primary>Return')]:
            self.get_application().set_accels_for_action('win.'+name,[shortcut])
        self.get_application().set_accels_for_action('win.toggle_output_fullscreen',['F11'])

    def set_media_option(self, key, enabled):
        if self.video.recorder or (key=='mirror_horizontal' and self.video.virtual.pipeline):
            self.notify('recording_active' if self.video.recorder else 'virtual_active')
            return
        old = self.opts[key]
        self.opts[key] = bool(enabled)
        try:
            save_settings(self.opts)
        except OSError:
            self.opts[key] = old
            self.notify('write_error')
            return
        if key=='mirror_horizontal':
            self.video.set_mirror(enabled)
        self.lookup_action(key).set_state(GLib.Variant('b',bool(enabled)))
        if key=='audio_enabled' and hasattr(self,'audio_enabled_choice') and self.audio_enabled_choice.get_active()!=bool(enabled):
            self.audio_enabled_choice.set_active(bool(enabled))
        self.set_status(key+'_on' if enabled else key+'_off')

    def reset_all_settings(self):
        if self.busy or self.closing or self.shutdown_requested:
            return
        if self.video.recorder or self.video.virtual.pipeline or self.audio_recorder.pipeline:
            self.notify('reset_settings_busy')
            return
        self.confirm('reset_all_settings_confirm',self.perform_reset_all_settings)

    def perform_reset_all_settings(self):
        old_options=self.opts.copy()
        old_tracking=self.tracking_values.copy()
        profiles_path=config_dir()/'camera_profiles.json'
        try:old_profiles=profiles_path.read_bytes() if profiles_path.exists() else None
        except OSError:
            self.notify('write_error')
            return
        was_live=bool(self.video.pipeline)
        self.resetting_settings=True
        try:
            save_settings(DEFAULTS.copy())
            atomic_json(config_dir()/'tracking.json',{})
            atomic_json(profiles_path,{'version':1,'cameras':{}})
        except OSError:
            try:
                save_settings(old_options)
                atomic_json(config_dir()/'tracking.json',old_tracking)
                if old_profiles is None:
                    profiles_path.unlink(missing_ok=True)
                else:
                    profiles_path.write_bytes(old_profiles)
            except OSError:
                self.logger.exception('Tiny-Einstellungen konnten nach einem fehlgeschlagenen Zurücksetzen nicht vollständig wiederhergestellt werden')
            self.resetting_settings=False
            self.notify('write_error')
            return

        self.opts=DEFAULTS.copy()
        self.tracking_values={}
        if self.window_state:
            self.window_state.rect=(0,0,DEFAULTS['window_width'],DEFAULTS['window_height'])
            self.window_state.position_known=False
        if self.is_maximized():self.unmaximize()
        self.set_default_size(DEFAULTS['window_width'],DEFAULTS['window_height'])

        # Restore UI defaults without sending commands to the physical camera.
        for key,(_,_,widget,_) in self.speech_controls.items():
            if key=='voice_language':widget.set_selected(0)
            elif isinstance(widget,Gtk.Switch):widget.set_active(False)

        self.apply_language(self.opts['language'])
        for group in GROUPS:self.build_fields(group)
        self.image_directory_entry.set_text(self.opts['image_directory'])
        self.audio_directory_entry.set_text(self.opts['audio_directory'])
        self.image_quality_choice.set_value(self.opts['image_quality'])
        self.lookup_action('mirror_horizontal').set_state(GLib.Variant('b',False))
        self.lookup_action('audio_enabled').set_state(GLib.Variant('b',True))
        self.audio_enabled_choice.set_active(True)
        self.reset_studio_settings()
        self.refresh_profile_names()
        if was_live:
            self.stop_preview()
            self.video.set_mirror(False)
            self.schedule_preview()
        else:
            self.video.set_mirror(False)
        self.resetting_settings=False
        self.set_status('settings_reset')

    def audio_enabled_changed(self,widget):
        enabled=widget.get_active()
        if self.video.recorder:
            widget.set_active(self.opts['audio_enabled'])
            return
        if enabled!=self.opts['audio_enabled']:
            self.set_media_option('audio_enabled',enabled)
            if widget.get_active()!=self.opts['audio_enabled']:
                widget.set_active(self.opts['audio_enabled'])

    def schedule_preview(self):
        self.preview_request+=1
        request=self.preview_request
        def start():
            if request!=self.preview_request or not self.alive or self.closing or self.shutdown_requested:return False
            if self.busy:return True
            self.start_preview()
            return False
        GLib.timeout_add(80,start)

    def on_camera_selected(self,*_):
        if self.camera_loading:return
        if self.video.recorder or self.video.virtual.pipeline:return
        if self.video.pipeline:self.stop_preview()
        self.select_camera()
        if self.auto_preview:self.schedule_preview()

    def show_settings(self,*_):
        window = super().show_settings()
        if self.video and (self.video.recorder or self.video.virtual.pipeline):
            for key in ('mirror_horizontal','audio_enabled'):
                window.template_controls['fields'][key].set_sensitive(False)
        return window

    def on_close(self,*_):
        # The settings window may be hidden while the live output keeps running.
        # Only File → Quit requests the full camera shutdown sequence.
        if not self.explicit_quit:
            self.set_visible(False)
            if self.output_window and not self.output_window.get_visible():
                self.output_window.present()
            return True
        return self._shutdown_on_close()

    def apply_language(self, code):
        uvc_state=None
        uvc_row=self.uvc_choice.get_selected_row() if self.camera_ready else None
        if self.camera_ready and self.uvc_get and uvc_row and uvc_row.get_index()<len(self.uvc_controls):
            uvc_state=(self.uvc_controls[uvc_row.get_index()]['id'],self.uvc_get())
        super().apply_language(code)
        if not self.camera_ready:
            return
        self.refresh_speech_language()
        for name,page in self.pages.items():
            page.set_title(self.tr(name))
        for group,section in self.selection.items():
            row=section['choice'].get_selected_row()
            index=row.get_index() if row else 0
            old = {k:get() for k,(_,get) in section['widgets'].items()}
            old_indices = {k:w.get_selected() for k,(w,_) in section['widgets'].items() if isinstance(w,Gtk.DropDown)}
            while section['choice'].get_first_child():section['choice'].remove(section['choice'].get_first_child())
            tool_rows=[]
            for name in GROUPS[group]:
                tool_row=Gtk.ListBoxRow(child=Gtk.Label(label=self.tr(name),xalign=0,wrap=True))
                section['choice'].append(tool_row)
                tool_rows.append(tool_row)
            section['tool_rows']=tool_rows
            if GROUPS[group]:section['choice'].select_row(section['choice'].get_row_at_index(min(index,len(GROUPS[group])-1)))
            # Preserve typed values across language changes.
            self.build_fields(group)
            for key,value in old.items():
                if key in section['widgets']:
                    w,_ = section['widgets'][key]
                    if isinstance(w,Gtk.SpinButton):w.set_value(value)
                    elif isinstance(w,Gtk.Switch):w.set_active(value)
                    elif isinstance(w,Gtk.Entry):w.set_text(value)
                    elif isinstance(w,Gtk.DropDown) and key in old_indices:w.set_selected(old_indices[key])
        self.preview.set_alternative_text(self.tr('preview_alt'))
        self.set_title(f"{PROJECT['name']} – {self.tr('settings')} {VERSION}")
        self.output_window.set_title(f"{PROJECT['name']} – {self.tr('live')}")
        self.refresh_camera_heading()
        for key in ('mirror_horizontal','audio_enabled'):
            self.lookup_action(key).set_state(GLib.Variant('b',self.opts[key]))
        if hasattr(self,'audio_enabled_choice'):
            self.audio_enabled_choice.set_active(self.opts['audio_enabled'])
        if not self.video.recorder and not self.video.virtual.pipeline:self.video.set_mirror(self.opts['mirror_horizontal'])
        self.set_uvc_controls(self.uvc_controls,uvc_state[0] if uvc_state else None)
        if uvc_state and self.uvc_get:
            widget=self.uvc_widget;value=uvc_state[1]
            if isinstance(widget,Gtk.SpinButton):widget.set_value(value)
            elif isinstance(widget,Gtk.Switch):widget.set_active(bool(value))
            elif isinstance(widget,Gtk.DropDown):
                selected=self.uvc_choice.get_selected_row()
                choices=self.uvc_controls[selected.get_index()]['choices'] if selected else []
                values=[x[0] for x in choices]
                if value in values:widget.set_selected(values.index(value))
        if not self.virtual_devices:self.virtual_choice.set_model(Gtk.StringList.new([self.tr('virtual_no_target')]))
        if not self.virtual_modes:self.virtual_format.set_model(Gtk.StringList.new([self.tr('no_formats')]))
        if not self.format_list:
            self.resolution_choice.set_model(Gtk.StringList.new([self.tr('no_formats')]))
            self.fps_choice.set_model(Gtk.StringList.new([self.tr('no_formats')]))
            self.format_choice.set_model(Gtk.StringList.new([self.tr('no_formats')]))
        if not self.profile_names:self.profile_choice.set_model(Gtk.StringList.new([self.tr('no_profiles')]))
        self.rebuild_menu()
        self.refresh_result()
        self.update_actions()

    def rebuild_menu(self):
        model = self.menu.get_menu_model()
        # The inherited File and Help menus keep standard settings, language import and logs.
        actions=[('refresh','refresh')]
        if not self.selected_device or self.selected_device['kind']=='tiny2':
            actions += [('wake','wake'),('sleep','sleep')]
        model.insert_submenu(1,self.tr('view'),self.make_menu([
            [('show_output','show_output')],
            [('toggle_fullscreen','toggle_output_fullscreen')]]))
        model.insert_submenu(2,self.tr('camera'),self.make_menu([
            actions,
            [('preview_start','preview_start'),('preview_stop','preview_stop')],
            [('mirror_horizontal','mirror_horizontal')],
            [('camera_defaults','camera_defaults')]]))
        model.insert_submenu(3,self.tr('capture'),self.make_menu([
            [('snapshot','snapshot')],[('audio_enabled','audio_enabled')],
            [('record_start','record_start'),('record_stop','record_stop')]]))
        self.studio_menus(model)
        compact_menus(self.menu)

    def make_menu(self, groups):
        menu = Gio.Menu()
        for group in groups:
            section = Gio.Menu()
            for label,action in group:
                section.append(self.tr(label),'win.'+action)
            menu.append_section(None,section)
        return menu

    def update_actions(self):
        super().update_actions()
        if not self.camera_ready or not self.lookup_action('refresh'):
            return
        idle = not self.busy and not self.closing and not self.shutdown_requested
        live = bool(self.video and self.video.pipeline)
        recording = bool(self.video and self.video.recorder)
        connected = bool(self.selected_device)
        reset_action=self.lookup_action('reset_all_settings')
        if reset_action:
            reset_action.set_enabled(idle and not self.video.recorder and
                                     not self.audio_recorder.pipeline and not self.video.virtual.pipeline)
        for name in ('refresh','wake','sleep','apply_tool','check_environment'):
            self.lookup_action(name).set_enabled(idle and (name in ('refresh','check_environment') or connected))
        tiny=connected and self.selected_device['kind']=='tiny2'
        for name in ('wake','sleep'):self.lookup_action(name).set_enabled(idle and tiny and bool(self.camera_serial))
        self.lookup_action('sleep').set_enabled(
            idle and tiny and bool(self.camera_serial) and self.ai_mode=='no-tracking')
        self.lookup_action('refresh').set_enabled(idle and not live)
        self.lookup_action('preview_start').set_enabled(idle and connected and not live)
        self.lookup_action('preview_stop').set_enabled(idle and live and not recording)
        snapshot_ready=idle and live and self.video.frame() is not None
        self.lookup_action('snapshot').set_enabled(snapshot_ready)
        if hasattr(self,'snapshot_button'):self.snapshot_button.set_sensitive(snapshot_ready)
        self.lookup_action('record_start').set_enabled(idle and live and not recording and not self.audio_recorder.pipeline and self.video.frame() is not None and self.selected_recording_codec() is not None)
        self.lookup_action('record_stop').set_enabled(recording and not self.video.record_stopping)
        self.camera_choice.set_sensitive(idle and not recording and not self.video.virtual.pipeline and not self.shutdown_requested)
        self.studio_update_actions()
        for key in ('mirror_horizontal','audio_enabled'):
            self.lookup_action(key).set_enabled(idle and not recording and (key!='mirror_horizontal' or not self.video.virtual.pipeline))

    def refresh_devices(self):
        if self.busy or (self.video and self.video.pipeline):return
        previous=self.selected_device['path'] if self.selected_device else None
        def load():
            found=uvc.inventory()
            for device in found:
                try:device['controls']=uvc.read_controls(device['path'])
                except (OSError,ValueError) as error:
                    device['controls']=[]
                    self.logger.warning('%s: %s',device['name'],error)
            for device in found:
                try:device['formats']=uvc.formats(device['path'])
                except (OSError,ValueError) as error:
                    device['formats']=[];self.logger.warning('%s: %s',device['name'],error)
            catalog=[];devices={'cameras':[]}
            try:
                catalog=self.bridge.tools()
                if any(d['kind']=='tiny2' for d in found):devices=self.bridge.call('obsbot_devices')
            except Exception as error:
                self.logger.warning('MCP: %s',error)
            outputs=self.scan_virtual_cameras()
            return catalog,devices,found,outputs
        def done(data):
            catalog,devices,found,outputs=data
            self.set_virtual_cameras(outputs)
            self.catalog={x['name']:x for x in catalog}
            listed=devices.get('cameras',[])
            self.device_serials=[x['serial'] for x in listed if x.get('serial')]
            tiny=[d for d in found if d['kind']=='tiny2']
            for device in tiny:
                serial=device['serial']
                if serial not in self.device_serials:
                    serial=self.device_serials[0] if len(tiny)==1 and len(self.device_serials)==1 else ''
                device['control_serial']=serial
            self.camera_devices=found
            self.device_paths=[(d['path'],d['name']) for d in found]
            self.camera_names=[self.camera_name(d) for d in found]
            paths=[d['path'] for d in found]
            self.camera_loading=True
            self.camera_choice.set_model(Gtk.StringList.new(self.camera_names or [self.tr('no_camera')]))
            self.camera_choice.set_selected(paths.index(previous) if previous in paths else 0)
            self.select_camera()
            self.camera_loading=False
            for group in GROUPS:self.build_fields(group)
            self.last_result=('devices_result',dict(count=len(found)))
            self.refresh_result()
            self.set_status('connected' if found else 'no_camera')
            self.update_actions()
            if self.camera_serial:
                self.last_poll=time.monotonic()
                self.poll_status()
            if self.auto_preview and found:self.schedule_preview()
            # The shared background-job runner handles one task at a time.
            # Start microphone discovery only after camera discovery finishes.
            self.refresh_audio_sources()
        self.background(load,done,error_key='camera_error',title_key='searching_cameras')

    @staticmethod
    def camera_name(device):
        return {'tiny2':'OBSBOT Tiny 2','c922':'Logitech C922 Pro'}.get(device['kind'],device['name'])

    def refresh_camera_heading(self):
        self.heading.set_label(self.camera_name(self.selected_device) if self.selected_device else self.tr('camera'))

    def select_camera(self,*_):
        if self.video and self.video.pipeline:return
        index=self.camera_choice.get_selected()
        self.selected_device=self.camera_devices[index] if index<len(self.camera_devices) else None
        self.camera_serial=self.selected_device.get('control_serial','') if self.selected_device else ''
        self.ai_mode=None
        self.update_tool_availability()
        self.refresh_camera_heading()
        tiny=self.selected_device and self.selected_device['kind']=='tiny2'
        self.pages['diagnostics'].set_visible(False)
        self.nav_rows['diagnostics'].set_visible(False)
        for group in (*GROUPS,'speech_gestures'):
            visible=not self.selected_device or self.selected_device['kind']=='tiny2'
            self.pages[group].set_visible(visible)
            self.nav_rows[group].set_visible(visible)
        self.set_uvc_controls(self.selected_device.get('controls',[]) if self.selected_device else [])
        self.update_studio_camera()
        self.reset_camera_status_style()
        self.camera_state.set_label(self.tr('no_live_status' if tiny else 'uvc_status' if self.selected_device else 'no_camera'))
        self.stack.set_visible_child_name('format')
        if self.camera_ready and self.lookup_action('refresh'):
            # Rebuild via apply_language to avoid duplicated menu entries.
            super().apply_language(self.tr.code)
            self.rebuild_menu()
            self.update_actions()

    def command(self, tool, args, done=None):
        if self.busy:
            return
        self.command_error_detail = None
        if self.selected_device and self.selected_device['kind']!='tiny2':
            self.notify('tiny_only');return
        parameters = dict(args)
        # Capture and devices have no per-camera selector; all controls do.
        if self.camera_serial and tool not in ('devices','capture_list','capture_stop'):
            parameters['camera'] = self.camera_serial
        # Track the wake attempt before starting: close may suppress the completion callback.
        if self.camera_serial:self.used_tiny.add(self.camera_serial)
        def completed(value):
            self.command_error_detail = None
            self.last_result = ('command_done',{'operation':tool})
            self.last_camera_response=value
            if tool=='ai_track':
                if isinstance(value,dict) and value.get('verified') and value.get('matched'):
                    self.ai_mode=value.get('mode') if value.get('enabled') else 'no-tracking'
                else:
                    self.ai_mode=None
                self.update_tool_availability()
            self.show_tool_result(tool,value)
            self.refresh_result()
            self.results.set_rows([{'name':self.tr(tool),'status':'ok',
                'details':response_text(value,self.tr)}])
            self.logger.info('%s %s',self.tr('command_done',operation=self.tr(tool)),response_text(value,self.tr))
            if done:done(value)
            elif tool=='wake' and not self.video.pipeline:
                self.last_result=('awake_no_preview',{})
                self.refresh_result()
                self.set_status('awake_no_preview')
            self.update_actions()
        def run_command():
            try:
                return (self.bridge.wake_verified(self.camera_serial) if tool=='wake'
                        else self.bridge.call('obsbot_'+tool,parameters))
            except Exception as error:
                self.command_error_detail = (tool, str(error)[:500])
                self.logger.error('Kamerabefehl %s fehlgeschlagen: %s', tool, error)
                raise
        self.background(run_command,completed,
                        error_key='wake_error' if tool=='wake' else 'camera_error',title_key='camera_working')

    def show_tool_result(self, tool, value):
        """Show the latest tool response on the page where the tool is listed."""
        group=next((name for name,tools in GROUPS.items() if tool in tools),None)
        if not group or group not in self.selection:return
        section=self.selection[group]
        section['result_text'].set_label(response_text(value,self.tr))
        section['result_box'].set_visible(True)

    def notify(self, key, **values):
        if key in ('camera_error','profile_error') and getattr(self,'control_restore_failed',False):
            self.control_restore_failed=False
            return super().notify('control_restore_failed')
        if key=='audio_record_failed' and getattr(self,'audio_recorder',None):
            path=self.audio_recorder.path
            try:preserved=path and path.is_file() and path.stat().st_size>0
            except OSError:preserved=False
            if preserved:return super().notify('audio_record_incomplete',path=str(path))
        if key != 'camera_error' or not self.command_error_detail:
            return super().notify(key, **values)
        tool, detail = self.command_error_detail
        self.command_error_detail = None
        dialog = self.track(Gtk.Window(title=PROJECT['name'], transient_for=self, modal=True,
                                       default_width=540))
        box = vertical(spacing=12)
        box.append(Gtk.Label(label=self.tr(key), wrap=True, selectable=True, xalign=0))
        box.append(Gtk.Label(label=self.tr('command_error_detail', operation=self.tr(tool), detail=detail),
                             wrap=True, selectable=True, xalign=0))
        box.append(self.button('close', lambda *_: self.close_dialog(dialog)))
        dialog.set_child(box)
        dialog.present()

    def apply_tool(self):
        if self.stack.get_visible_child_name()=='uvc':
            self.apply_uvc();return
        if self.selected_device and self.selected_device['kind']!='tiny2':
            self.notify('choose_uvc_page');return
        group = self.stack.get_visible_child_name()
        if group=='speech_gestures':
            self.apply_speech();return
        if group not in GROUPS:
            self.notify('choose_tool_page')
            return
        section = self.selection[group]
        row=section['choice'].get_selected_row()
        if row is None:return
        tool = self.tool_for_row(group,row)
        if not tool:return
        if tool in TRACKING_CONFLICTS and self.ai_mode!='no-tracking':
            self.notify('tracking_conflict' if self.ai_mode not in (None,'unknown') else 'tracking_status_unknown')
            return
        args = {key:get() for key,(_,get) in section['widgets'].items()}
        if tool in ('aim_at_pixel','zoom_to_fit'):
            args=camera_coordinates(args,self.rotation_choice.get_selected()*90,self.opts['mirror_horizontal'],tool=='zoom_to_fit')
        if tool.startswith('preset_') and tool in ('preset_delete','preset_update','preset_rename'):
            self.confirm('preset_confirm',lambda:self.command(tool,args))
        else:
            self.command(tool,args)

    def confirm(self,key,callback):
        window = self.track(Gtk.Window(title=self.tr('confirmation'),transient_for=self,modal=True))
        box = vertical()
        box.append(self.label('confirmation',xalign=0))
        box.append(self.label(key,xalign=0,wrap=True))
        buttons = Gtk.Box(spacing=12,halign=Gtk.Align.END)
        buttons.append(self.button('cancel',lambda *_:self.close_dialog(window)))
        def accept(*_):
            self.close_dialog(window)
            callback()
        buttons.append(self.button('continue',accept))
        box.append(buttons)
        window.set_child(box)
        window.present()

    def start_preview(self):
        device=self.selected_device
        if not device or self.video.pipeline:return
        def ready(_=None):
            try:
                self.video.start(device['path'],self.opts['preview_width'],self.opts['preview_fps'],mirrored=self.opts['mirror_horizontal'],mode=self.selected_mode(),rotation=self.effect_values()[0],grayscale=self.effect_values()[1],negative=self.effect_values()[2])
                self.frame_seen=None
                self.set_status('preview_starting')
                self.show_output()
            except (RuntimeError,GLib.Error,OSError) as error:
                if str(error) in ('unsupported_format','camera_missing','no_supported_format'):self.notify(str(error))
                else:self.video_error(str(error))
            self.update_actions()
        if device['kind']=='tiny2':
            if not self.camera_serial:
                self.notify('camera_error');return
            self.command('wake',{},ready)
        else:ready()

    def stop_preview(self):
        if hasattr(self,'series_timer') and self.series_timer:self.stop_series()
        if self.video.recorder:
            self.notify('recording_active')
            return
        self.video.stop()
        self.preview.set_paintable(None)
        self.frame_seen=None
        self.set_status('preview_stopped')
        self.update_actions()

    def sleep_camera(self):
        if self.ai_mode!='no-tracking':
            self.notify('tracking_conflict' if self.ai_mode not in (None,'unknown') else 'tracking_status_unknown')
            return
        if self.video.recorder:
            self.notify('recording_active')
            return
        if self.video.pipeline:self.stop_preview()
        self.command('sleep',{})

    def render(self):
        if not self.alive:
            return False
        self.render_virtual_camera()
        frame = self.video.frame()
        if frame and frame is not self.frame_seen:
            data,w,h,stride = frame
            self.preview.set_paintable(Gdk.MemoryTexture.new(w,h,Gdk.MemoryFormat.R8G8B8,GLib.Bytes.new(data),stride))
            first_frame=self.frame_seen is None
            self.frame_seen = frame
            if first_frame:self.set_status('preview_running')
        if self.video.recorder:
            elapsed = int(time.monotonic()-self.video.record_started)
            self.set_status('recording_audio' if self.video.record_audio else 'recording',seconds=elapsed)
            if self.video.check_recording():
                self.logger.warning('%s: %s',self.tr('record_failed'),self.video.record_error)
                self.stop_record()
        elif self.audio_recorder.pipeline:
            elapsed=int(time.monotonic()-self.audio_recorder.started)
            self.set_status('audio_capture_running',seconds=elapsed)
            if self.audio_recorder.check_error():
                self.logger.warning('%s: %s',self.tr('audio_record_failed'),self.audio_recorder.error)
                self.stop_audio_capture()
        if self.video.pipeline and time.monotonic()-max(self.video.frame_time,self.video.started)>8:
            # Missing first frames are also treated as a stream failure.
            self.video_error('video_stalled')
        if not self.shutdown_requested and self.camera_serial and not self.busy and time.monotonic()-self.last_poll>=self.opts['status_seconds']:
            self.last_poll = time.monotonic()
            # Polling remains read-only and must not wake a sleeping device.
            self.poll_status()
        self.update_actions()
        return True

    def poll_status(self):
        if self.polling or self.closing:return
        self.polling = True
        serial = self.camera_serial
        def complete(value,error):
            self.polling = False
            if not self.alive or self.camera_serial!=serial:return False
            if error:
                self.ai_mode=None
                self.update_tool_availability()
                self.logger.warning('%s: %s',self.tr('camera_error'),error)
                self.reset_camera_status_style()
                self.camera_state.set_label(self.tr('no_camera'))
            else:
                self.display_status(value)
            self.update_actions()
            return False
        def worker():
            try:
                value = self.bridge.call('obsbot_status',{'camera':serial})
                GLib.idle_add(complete,value,None)
            except Exception as error:
                GLib.idle_add(complete,None,str(error))
        threading.Thread(target=worker,daemon=True).start()

    def display_status(self,value):
        if isinstance(value,dict):
            self.ai_mode=value.get('aiMode')
            self.update_tool_availability()
            self.camera_state.remove_css_class('camera-status-awake')
            self.camera_state.remove_css_class('camera-status-asleep')
            self.camera_state.add_css_class('camera-status-awake' if value.get('awake') else 'camera-status-asleep')
            self.camera_state.set_label(self.tr('camera_status',power=self.tr('awake' if value.get('awake') else 'asleep'),
                zoom=value.get('zoomPercent','?'),focus=self.tr('value_'+str(value.get('focusMode','unknown'))),
                tracking=self.tr('value_'+str(value.get('aiMode','unknown')))))

    def reset_camera_status_style(self):
        self.camera_state.remove_css_class('camera-status-awake')
        self.camera_state.remove_css_class('camera-status-asleep')

    def video_error(self,detail):
        if not self.alive or self.video_failure_pending:return
        self.video_failure_pending=True
        self.logger.warning('%s: %s',self.tr('video_failed'),detail)
        def finish():
            if not self.alive:return
            self.stop_preview()
            self.last_result=('video_failed',{})
            self.refresh_result()
            self.set_status('video_failed')
            self.video_failure_pending=False
            self.notify('video_failed')
        def show():
            if not self.alive:return False
            if self.video.recorder:self.stop_record(finish)
            else:finish()
            return False
        GLib.idle_add(show)

    def save_frame(self,path,frame=None,format_='png'):
        frame=frame or self.video.frame()
        if frame is None:raise RuntimeError('preview_required')
        data,w,h,stride=frame
        pixbuf=GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(data),GdkPixbuf.Colorspace.RGB,False,8,w,h,stride)
        options=['quality'] if format_=='jpeg' else []
        values=[str(self.opts['image_quality'])] if format_=='jpeg' else []
        ok,encoded=pixbuf.save_to_bufferv(format_,options,values)
        if not ok:raise OSError(f'{format_.upper()} encoding failed')
        with open(path,'xb') as target:target.write(encoded)

    def snapshot(self):
        self.snapshot_as('png')

    def selected_image_format(self):
        index=self.image_save_format.get_selected()
        format_=self.image_format_codes[index] if index<len(self.image_format_codes) else 'png'
        extension={'jpeg':'jpg','tiff':'tif','ico':'ico'}.get(format_,format_)
        return format_,extension

    def snapshot_selected_format(self):
        self.snapshot_as(*self.selected_image_format())

    def snapshot_as(self,format_,extension=None):
        frame=self.video.frame()
        if frame is None:self.notify('preview_required');return
        def save(path):
            try:self.save_frame(path,frame,format_);self.set_status('file_saved',path=str(path))
            except (OSError,GLib.Error):self.notify('write_error')
        self.save_path('snapshot','.'+(extension or format_),save,folder=self.opts['image_directory'])

    def save_path(self,title,suffix,callback,folder=None):
        dialog = Gtk.FileChooserNative(title=self.tr(title),transient_for=self,modal=True,
            action=Gtk.FileChooserAction.SAVE,accept_label=self.tr('save'),cancel_label=self.tr('cancel'))
        dialog.set_current_name('tiny-'+datetime.now().strftime('%Y%m%d-%H%M%S')+suffix)
        initial=folder or ROOT
        try:dialog.set_current_folder(Gio.File.new_for_path(str(initial)))
        except GLib.Error:dialog.set_current_folder(Gio.File.new_for_path(str(ROOT)))
        filt = Gtk.FileFilter()
        filt.set_name(suffix.upper()[1:])
        filt.add_pattern('*'+suffix)
        dialog.add_filter(filt)
        self.file_dialogs.append(dialog)
        def response(chooser,result):
            file = chooser.get_file()
            self.file_dialogs.remove(dialog)
            chooser.destroy()
            if result==Gtk.ResponseType.ACCEPT and file and file.get_path():
                path = Path(file.get_path())
                if path.suffix.lower()!=suffix:path=path.with_name(path.name+suffix)
                if path.exists() or path.is_symlink():
                    self.notify('target_exists')
                    return
                callback(path)
        dialog.connect('response',response)
        dialog.show()

    def record(self):
        codec=self.selected_recording_codec()
        if codec is None:self.notify('encoder_missing');return
        if self.audio_recorder.pipeline:
            self.notify('audio_capture_active');return
        def start(path):
            audio = self.opts['audio_enabled']
            camera=dict(self.selected_device) if self.selected_device else None
            if codec not in self.available_recording_formats():self.notify('encoder_missing');return
            quality=self.quality_choice.get_value_as_int();bitrate=self.bitrate_choice.get_value_as_int()*1000
            def create():
                device=camera_microphone(camera) if audio else None
                self.video.record(path,audio=audio,audio_device=device,container=codec,quality=quality,bitrate=bitrate)
            def done(_):
                self.set_status('recording_audio' if audio else 'recording',seconds=0)
                self.start_record_timer()
                self.update_actions()
            # Opening a sound source and validating it must not block GTK.
            self.background(create,done,error_key='audio_record_failed' if audio else 'record_failed',title_key='record_preparing')
        self.save_path('record_start',RECORDERS[codec]['extension'],start)

    def refresh_audio_sources(self):
        def done(sources):
            self.audio_sources=sources
            self.audio_device_choice.set_model(Gtk.StringList.new([item['label'] for item in sources] or [self.tr('no_audio_source')]))
            self.audio_device_choice.set_selected(0)
            self.studio_update_actions()
        self.background(microphones,done,error_key='audio_record_failed')

    def start_audio_capture(self):
        if self.video.recorder or self.audio_recorder.pipeline:return
        source_index=self.audio_device_choice.get_selected()
        if source_index>=len(self.audio_sources):self.notify('audio_missing');return
        source=self.audio_sources[source_index]
        if source['muted']:self.notify('audio_muted');return
        format_index=self.audio_capture_format.get_selected()
        if format_index>=len(self.audio_capture_formats):self.notify('encoder_missing');return
        format_=self.audio_capture_formats[format_index]
        def start(path):
            def done(_):
                self.set_status('audio_capture_running',seconds=0);self.update_actions()
            self.background(lambda:self.audio_recorder.start(path,source['name'],format_),done,error_key='audio_record_failed')
        self.save_path('audio_capture_start',AUDIO_RECORDERS[format_]['extension'],start,folder=self.opts['audio_directory'])

    def stop_audio_capture(self,after=None):
        if not self.audio_recorder.pipeline or self.audio_recorder.stopping:return
        def finished(error):
            if not self.alive:return False
            if error:
                self.set_status('audio_record_incomplete',path=str(self.audio_recorder.path))
                self.notify('audio_record_incomplete',path=str(self.audio_recorder.path))
            else:self.set_status('file_saved',path=str(self.audio_recorder.path))
            self.update_actions()
            if after:after()
            return False
        self.audio_recorder.stop(finished)
        self.update_actions()

    def stop_record(self,after=None):
        self.cancel_record_timer()
        def finished(error):
            if not self.alive:return False
            if error:self.notify(error)
            else:self.set_status('file_saved',path=str(self.video.record_path))
            self.update_actions()
            if after:after()
            return False
        self.video.finish_record(finished)
        self.update_actions()

    def refresh_result(self):
        # Camera replies remain in the bounded log; no response pane in the UI.
        return

    def environment(self):
        import shutil
        from .backend import node_command
        from .video import Gst
        items = [(self.tr('environment_readonly'),''),('Python',os.sys.version.split()[0]),
            ('GTK',f'{Gtk.get_major_version()}.{Gtk.get_minor_version()}'),('Node.js',node_command()),
            ('MCP',self.tr('available' if (ROOT/'dist/index.js').is_file() else 'missing')),
            ('Linux Helper',self.tr('available' if (ROOT/'native/prebuilt/linux-x64/obsbot-helper').is_file() else 'missing'))]
        for name in ('v4l2src','appsink','jpegdec','videoconvert','videoflip','videorate','vp8enc','webmmux','pulsesrc','opusenc','audioconvert','audioresample'):
            items.append((name,self.tr('available' if Gst.ElementFactory.find(name) else 'missing')))
        items.append(('FFmpeg',shutil.which('ffmpeg') or self.tr('optional_missing')))
        items.append((self.tr('camera'),str(len(cameras()))))
        items.append(('Kernel',os.uname().release))
        self.diagnostics.get_buffer().set_text('\n'.join(f'{a}: {b}' if b else a for a,b in items))
        self.stack.set_visible_child_name('diagnostics')
        self.set_status('environment_readonly')

    def show_about(self,*_):
        dialog = self.track(Gtk.AboutDialog(transient_for=self,modal=True,program_name=PROJECT['name'],
            version=VERSION,authors=PROJECT['authors'],comments=self.tr('app_subtitle'),license_type=Gtk.License.MIT_X11))
        dialog.set_logo(Gdk.Texture.new_from_filename(str(ROOT/'assets/tiny.png')))
        dialog.present()

    def _shutdown_on_close(self,*_):
        self.shutdown_requested=True;self.preview_request+=1;self.set_sensitive(False)
        if hasattr(self,'series_timer'):self.stop_series();self.cancel_record_timer()
        if self.video and self.video.recorder:
            if self.video.record_stopping:
                if not self.close_timer:self.close_timer=GLib.timeout_add(100,self._wait_close)
            else:self.stop_record(self.close)
            return True
        if self.audio_recorder and self.audio_recorder.pipeline:
            if self.audio_recorder.stopping:
                if not self.close_timer:self.close_timer=GLib.timeout_add(100,self._wait_close)
            else:self.stop_audio_capture(self.close)
            return True
        if self.jobs.running:
            self.closing=True;self.jobs.cancel();self.set_status('waiting_close');return True
        if self.polling:
            if not self.close_timer:self.close_timer=GLib.timeout_add(100,self._wait_close)
            return True
        if self.shutdown_in_progress:return True
        if self.video and self.video.pipeline:self.video.stop()
        if self.used_tiny and not self.shutdown_ready:
            self.shutdown_in_progress=True;self.set_sensitive(False);self.set_status('sleeping_on_exit')
            serials=set(self.used_tiny)
            def done(error):
                self.shutdown_in_progress=False;self.set_sensitive(True)
                if error:
                    self.logger.error('%s: %s',self.tr('sleep_failed_exit'),error)
                    self.shutdown_requested=False;self.closing=False
                    self.confirm('sleep_failed_exit',self.force_close_after_sleep_error)
                else:
                    self.shutdown_ready=True;self.close()
                return False
            def worker():
                error=None
                try:
                    present={x.get('serial') for x in self.bridge.call('obsbot_devices').get('cameras',[])}
                    for serial in serials&present:self.bridge.sleep_verified(serial)
                except Exception as exc:error=str(exc)
                GLib.idle_add(done,error)
            threading.Thread(target=worker,daemon=False).start()
            return True
        if self.bridge:self.bridge.close()
        if hasattr(self,'render_timer'):GLib.source_remove(self.render_timer)
        if self.output_window:
            self.output_window.destroy()
        return super().on_close()

    def force_close_after_sleep_error(self):
        self.shutdown_ready=True;self.close()

    def _wait_close(self):
        if self.polling or self.jobs.running or self.video.record_stopping or self.audio_recorder.stopping:return True
        self.close_timer=None;self.close();return False
