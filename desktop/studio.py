"""Additional camera-format, output and profile pages and their menu actions."""
from datetime import datetime
from pathlib import Path
from gi.repository import Gtk,Gio,GLib,GdkPixbuf
from josef_basis.gui import vertical
from josef_basis.model import config_dir,save_settings
from josef_basis.file_dialogs import choose
from .profiles import Profiles
from .virtual_controls import VirtualControls
from .video import RECORDERS,recording_formats,audio_recording_formats,choose_mode
from . import uvc


STUDIO_DEFAULTS = {
    'image_format': 0,
    'photo_interval': 5,
    'photo_count': 10,
    'rotation': 0,
    'grayscale': False,
    'negative': False,
    'crosshair': False,
    'video_quality': 80,
    'video_bitrate': 4000,
    'recording_duration': 0,
    'audio_format': 0,
    'audio_capture_format': 0,
}


class Studio(VirtualControls):
    def build_studio(self):
        self.build_virtual_page()
        self.profile_names=[]
        self.profile_store=Profiles(config_dir())
        self.format_list=[];self.resolution_groups=[];self.fps_values=[];self.pixel_modes=[];self.format_values=[]
        self.format_loading=False;self.series_timer=None;self.record_timer=None
        self.series_remaining=0;self.series_count=0
        self.output_codec=Gtk.DropDown.new_from_strings(recording_formats())
        self.interval_choice=Gtk.SpinButton.new_with_range(1,3600,1);self.interval_choice.set_value(5)
        self.count_choice=Gtk.SpinButton.new_with_range(1,10000,1);self.count_choice.set_value(10)
        page=vertical(margin=8)
        page.append(self.label('format_heading',xalign=0))
        image_row=Gtk.Box(spacing=12)
        image_row.append(self.label('image_save_format',xalign=0,hexpand=True))
        available_image_formats={fmt.get_name() for fmt in GdkPixbuf.Pixbuf.get_formats() if fmt.is_writable()}
        self.image_format_codes=[name for name in ('png','jpeg','bmp','ico','tiff','webp') if name in available_image_formats]
        image_labels={'png':'PNG','jpeg':'JPEG','bmp':'BMP','ico':'ICO/CUR','tiff':'TIFF','webp':'WebP'}
        self.image_save_format=Gtk.DropDown.new_from_strings([image_labels[name] for name in self.image_format_codes] or ['PNG'])
        image_row.append(self.image_save_format)
        page.append(image_row)
        self.image_quality_choice=Gtk.SpinButton.new_with_range(1,100,1)
        self.image_quality_choice.set_value(self.opts['image_quality'])
        row=Gtk.Box(spacing=12)
        row.append(self.label('image_quality',xalign=0,hexpand=True,wrap=True))
        row.append(self.image_quality_choice);page.append(row)
        self.image_save_format.connect('notify::selected',lambda *_:self.sync_image_quality())
        self.image_quality_choice.connect('value-changed',self.image_quality_changed)
        self.sync_image_quality()
        for key,widget in (('photo_interval',self.interval_choice),('photo_count',self.count_choice)):
            row=Gtk.Box(spacing=12);row.append(self.label(key,xalign=0,hexpand=True,wrap=True));row.append(widget);page.append(row)
        self.snapshot_button=self.button('snapshot_button',lambda *_:self.snapshot_selected_format())
        page.append(self.snapshot_button)
        image_path_row=Gtk.Box(spacing=8)
        self.image_directory_entry=Gtk.Entry(editable=False,hexpand=True)
        self.image_directory_entry.set_text(self.opts['image_directory'])
        image_path_row.append(self.label('image_directory',xalign=0))
        image_path_row.append(self.image_directory_entry)
        image_path_row.append(self.button('choose_image_directory',lambda *_:self.choose_output_directory('image_directory')))
        page.append(image_path_row)
        self.pages['format']=self.add_stack_page(page,'format')
        page=vertical(margin=8)
        page.append(self.label('video_heading',xalign=0))
        page.append(self.label('video_hint',xalign=0,wrap=True))
        page.append(self.label('video_format_heading',xalign=0))
        for key, attribute, handler in (
            ('resolution','resolution_choice','resolution_changed'),
            ('frame_rate','fps_choice','fps_changed'),
            ('camera_format','format_choice','format_changed'),
        ):
            row=Gtk.Box(spacing=12)
            row.append(self.label(key,xalign=0,hexpand=True,wrap=True))
            choice=Gtk.DropDown.new_from_strings([self.tr('no_formats')])
            setattr(self,attribute,choice)
            choice.connect('notify::selected',getattr(self,handler))
            row.append(choice)
            page.append(row)
        page.append(self.label('format_hint',xalign=0,wrap=True))
        page.append(self.label('video_options_heading',xalign=0))
        self.rotation_choice=Gtk.DropDown.new_from_strings(['0°','90°','180°','270°'])
        self.gray_choice=Gtk.CheckButton(label=self.tr('grayscale'))
        self.negative_choice=Gtk.CheckButton(label=self.tr('negative'))
        self.crosshair_choice=Gtk.CheckButton(label=self.tr('crosshair'))
        for widget,key in [(self.gray_choice,'grayscale'),(self.negative_choice,'negative'),(self.crosshair_choice,'crosshair')]:self.bindings.append((widget,'set_label',key))
        self.quality_choice=Gtk.SpinButton.new_with_range(1,100,1);self.quality_choice.set_value(80)
        self.bitrate_choice=Gtk.SpinButton.new_with_range(100,100000,100);self.bitrate_choice.set_value(4000)
        self.duration_choice=Gtk.SpinButton.new_with_range(0,86400,1)
        for key,widget in [('output_codec',self.output_codec),('quality',self.quality_choice),('bitrate',self.bitrate_choice),('rotation',self.rotation_choice),('duration',self.duration_choice)]:
            row=Gtk.Box(spacing=12);row.append(self.label(key,xalign=0,hexpand=True,wrap=True));row.append(widget);page.append(row)
        for widget in (self.gray_choice,self.negative_choice,self.crosshair_choice):page.append(widget)
        page.append(self.label('output_hint',xalign=0,wrap=True))
        page.append(self.label('video_capture_heading',xalign=0))
        self.video_capture_status=self.label('video_ready',xalign=0,wrap=True)
        page.append(self.video_capture_status)
        buttons=Gtk.Box(spacing=8)
        self.video_capture_start=self.button('record_start',lambda *_:self.record())
        self.video_capture_stop=self.button('record_stop',lambda *_:self.stop_record())
        buttons.append(self.video_capture_start);buttons.append(self.video_capture_stop)
        page.append(buttons)
        self.pages['video']=self.add_stack_page(page,'video')
        self.effect_widgets=[self.rotation_choice,self.gray_choice,self.negative_choice,self.crosshair_choice]
        for w in self.effect_widgets:
            w.connect('notify::selected' if isinstance(w,Gtk.DropDown) else 'toggled',lambda *_:self.effects_changed())
        self.output_codec.connect('notify::selected',lambda *_:self.sync_audio_format())
        page=vertical(margin=8)
        page.append(self.label('audio_heading',xalign=0))
        self.audio_enabled_choice=Gtk.CheckButton(label=self.tr('audio_enabled'))
        self.bindings.append((self.audio_enabled_choice,'set_label','audio_enabled'))
        self.audio_enabled_choice.set_active(self.opts['audio_enabled'])
        self.audio_enabled_choice.connect('toggled',self.audio_enabled_changed)
        page.append(self.audio_enabled_choice)
        audio_row=Gtk.Box(spacing=12)
        audio_row.append(self.label('audio_format',xalign=0,hexpand=True,wrap=True))
        self.audio_format_codes=[];self.audio_format_labels=[]
        supported_containers=set(recording_formats())
        for code,label,containers in (('opus','Opus · WebM/MKV',('webm','mkv')),('aac','AAC · MP4',('mp4',)),('pcm','PCM · AVI',('avi',))):
            matches=[container for container in containers if container in supported_containers]
            if matches:self.audio_format_codes.append((code,matches));self.audio_format_labels.append(label)
        self.audio_format_choice=Gtk.DropDown.new_from_strings(self.audio_format_labels or [self.tr('no_audio_formats')])
        self.audio_format_choice.set_sensitive(bool(self.audio_format_codes))
        self.audio_format_choice.connect('notify::selected',self.audio_format_changed)
        audio_row.append(self.audio_format_choice);page.append(audio_row)
        page.append(self.label('audio_format_hint',xalign=0,wrap=True))
        source_row=Gtk.Box(spacing=8)
        source_row.append(self.label('audio_source',xalign=0,hexpand=True))
        self.audio_device_choice=Gtk.DropDown.new_from_strings([self.tr('no_audio_source')])
        source_row.append(self.audio_device_choice)
        source_row.append(self.button('refresh_audio_sources',lambda *_:self.refresh_audio_sources()))
        page.append(source_row)
        self.audio_device_choice.connect('notify::selected',lambda *_:self.studio_update_actions())
        self.audio_sources=[]
        capture_row=Gtk.Box(spacing=12)
        capture_row.append(self.label('audio_file_format',xalign=0,hexpand=True))
        self.audio_capture_formats=audio_recording_formats()
        labels={'wav':'WAV · PCM','ogg':'OGG · Opus','flac':'FLAC','mp3':'MP3'}
        self.audio_capture_format=Gtk.DropDown.new_from_strings([labels[x] for x in self.audio_capture_formats] or [self.tr('no_audio_formats')])
        self.audio_capture_format.connect('notify::selected',lambda *_:self.studio_update_actions())
        capture_row.append(self.audio_capture_format);page.append(capture_row)
        audio_path_row=Gtk.Box(spacing=8)
        self.audio_directory_entry=Gtk.Entry(editable=False,hexpand=True)
        self.audio_directory_entry.set_text(self.opts['audio_directory'])
        audio_path_row.append(self.label('audio_directory',xalign=0))
        audio_path_row.append(self.audio_directory_entry)
        audio_path_row.append(self.button('choose_audio_directory',lambda *_:self.choose_output_directory('audio_directory')))
        page.append(audio_path_row)
        capture_buttons=Gtk.Box(spacing=8)
        self.audio_capture_start=self.button('audio_capture_start',lambda *_:self.start_audio_capture())
        self.audio_capture_stop=self.button('audio_capture_stop',lambda *_:self.stop_audio_capture())
        capture_buttons.append(self.audio_capture_start);capture_buttons.append(self.audio_capture_stop);page.append(capture_buttons)
        page.append(self.label('audio_capture_hint',xalign=0,wrap=True))
        self.pages['audio']=self.add_stack_page(page,'audio')
        self.sync_audio_format()
        page=vertical(margin=8)
        page.append(self.label('camera_profiles_heading',xalign=0))
        self.profile_choice=Gtk.DropDown.new_from_strings([]);page.append(self.profile_choice)
        self.profile_choice.connect('notify::selected',lambda *_:self.studio_update_actions())
        self.profile_name=Gtk.Entry();page.append(self.label('profile_name',xalign=0));page.append(self.profile_name)
        profile_buttons=Gtk.Box(spacing=8)
        self.profile_save_button=self.button('profile_save',lambda *_:self.save_camera_profile())
        self.profile_load_button=self.button('profile_load',lambda *_:self.load_camera_profile())
        self.profile_delete_button=self.button('profile_delete',lambda *_:self.delete_camera_profile())
        profile_buttons.append(self.profile_save_button)
        profile_buttons.append(self.profile_load_button)
        profile_buttons.append(self.profile_delete_button)
        page.append(profile_buttons)
        page.append(self.label('camera_profiles_hint',xalign=0,wrap=True))
        self.pages['camera_profiles']=self.add_stack_page(page,'camera_profiles')
        self.crosshair=Gtk.DrawingArea(hexpand=True,vexpand=True,can_target=False)
        self.crosshair.set_draw_func(self.draw_crosshair)
        self.preview_overlay.add_overlay(self.crosshair)
        for name,callback in [('profile_save',self.save_camera_profile),('profile_load',self.load_camera_profile),('profile_delete',self.delete_camera_profile),('camera_defaults',self.reset_camera_defaults),('series_start',self.start_series),('series_stop',self.stop_series)]:
            action=Gio.SimpleAction.new(name,None);action.connect('activate',lambda *_,callback=callback:callback());self.add_action(action)

    def draw_crosshair(self,area,context,width,height):
        if not self.crosshair_choice.get_active():return
        context.set_source_rgba(1,1,1,.9);context.set_line_width(2)
        context.move_to(width/2-18,height/2);context.line_to(width/2+18,height/2)
        context.move_to(width/2,height/2-18);context.line_to(width/2,height/2+18);context.stroke()

    def effects_changed(self):
        if not hasattr(self,'crosshair'):return
        self.crosshair.queue_draw()
        if not self.video.recorder and not self.video.virtual.pipeline:self.video.set_effects(*self.effect_values())

    def effect_values(self):return (self.rotation_choice.get_selected()*90,self.gray_choice.get_active(),self.negative_choice.get_active())

    def selected_mode(self):
        resolution_index=self.resolution_choice.get_selected()
        fps_index=self.fps_choice.get_selected()
        format_index=self.format_choice.get_selected()
        if (resolution_index>=len(self.resolution_groups) or
                fps_index>=len(self.fps_values) or format_index>=len(self.format_values)):
            return None
        rate=self.fps_values[fps_index]
        fourcc=self.format_values[format_index]
        return next((dict(mode) for mode in self.resolution_groups[resolution_index]
            if (mode['num'],mode['den'])==rate and mode['fourcc']==fourcc),None)

    def set_formats(self,modes,preferred=None):
        self.format_loading=True;self.format_list=list(modes)
        groups={}
        for mode in modes:
            key=(mode['width'],mode['height'])
            groups.setdefault(key,[]).append(mode)
        self.resolution_groups=list(groups.values())
        labels=[f'{width} × {height}' for width,height in groups]
        self.resolution_choice.set_model(Gtk.StringList.new(labels or [self.tr('no_formats')]))
        self.format_values=list(dict.fromkeys(mode['fourcc'] for mode in modes))
        self.format_choice.set_model(Gtk.StringList.new(self.format_values or [self.tr('no_formats')]))
        if modes:
            wanted=preferred if preferred in modes else choose_mode(modes,self.opts['preview_width'],self.opts['preview_fps'])
            resolution_index=next(i for i,group in enumerate(self.resolution_groups)
                if (group[0]['width'],group[0]['height'])==(wanted['width'],wanted['height']))
            self.resolution_choice.set_selected(resolution_index)
            self.format_choice.set_selected(self.format_values.index(wanted['fourcc']))
            self._set_frame_rates((wanted['num'],wanted['den']),wanted['fourcc'])
        else:
            self.fps_values=[]
            self.pixel_modes=[]
            self.format_values=[]
            self.format_choice.set_model(Gtk.StringList.new([self.tr('no_formats')]))
            self.fps_choice.set_model(Gtk.StringList.new([self.tr('no_formats')]))
        self.format_loading=False

    def _set_frame_rates(self,preferred_rate=None,preferred_format=None):
        index=self.resolution_choice.get_selected()
        modes=self.resolution_groups[index] if index<len(self.resolution_groups) else []
        rates=list(dict.fromkeys((mode['num'],mode['den']) for mode in modes))
        labels=[f'{num/den:.2f} fps' if num and den else self.tr('frame_rate_unknown') for num,den in rates]
        self.fps_values=rates
        self.fps_choice.set_model(Gtk.StringList.new(labels or [self.tr('no_formats')]))
        if preferred_rate in rates:
            rate_index=rates.index(preferred_rate)
        elif rates and preferred_rate and preferred_rate[1]:
            wanted_fps=preferred_rate[0]/preferred_rate[1]
            rate_index=min(range(len(rates)),key=lambda i:abs(rates[i][0]/rates[i][1]-wanted_fps) if rates[i][1] else float('inf'))
        else:
            rate_index=0
        self.fps_choice.set_selected(rate_index)
        self._set_pixel_formats(preferred_format)

    def _set_pixel_formats(self,preferred=None):
        resolution_index=self.resolution_choice.get_selected()
        rate_index=self.fps_choice.get_selected()
        rate=self.fps_values[rate_index] if rate_index<len(self.fps_values) else None
        modes=self.resolution_groups[resolution_index] if resolution_index<len(self.resolution_groups) else []
        self.pixel_modes=[mode for mode in modes if (mode['num'],mode['den'])==rate]
        available=[mode['fourcc'] for mode in self.pixel_modes]
        current=self.format_values[self.format_choice.get_selected()] if self.format_choice.get_selected()<len(self.format_values) else None
        chosen=preferred if preferred in available else current if current in available else available[0] if available else None
        if chosen in self.format_values:
            self.format_choice.set_selected(self.format_values.index(chosen))

    def resolution_changed(self,*_):
        if self.format_loading:return
        old_rate=self.fps_values[self.fps_choice.get_selected()] if self.fps_choice.get_selected()<len(self.fps_values) else None
        old_format=self.format_values[self.format_choice.get_selected()] if self.format_choice.get_selected()<len(self.format_values) else None
        self.format_loading=True
        self._set_frame_rates(old_rate,old_format)
        self.format_loading=False
        self._format_selection_changed()

    def fps_changed(self,*_):
        if self.format_loading:return
        old_format=self.format_values[self.format_choice.get_selected()] if self.format_choice.get_selected()<len(self.format_values) else None
        self.format_loading=True
        self._set_pixel_formats(old_format)
        self.format_loading=False
        self._format_selection_changed()

    def format_changed(self,*_):
        if self.format_loading:return
        format_index=self.format_choice.get_selected()
        if format_index>=len(self.format_values):return
        fourcc=self.format_values[format_index]
        current=self.selected_mode()
        if not current or current['fourcc']!=fourcc:
            candidates=[mode for mode in self.format_list if mode['fourcc']==fourcc]
            if not candidates:return
            current_size=self.resolution_groups[self.resolution_choice.get_selected()][0] if self.resolution_choice.get_selected()<len(self.resolution_groups) else None
            current_rate=self.fps_values[self.fps_choice.get_selected()] if self.fps_choice.get_selected()<len(self.fps_values) else (0,1)
            wanted=min(candidates,key=lambda mode:(
                abs(mode['width']-(current_size['width'] if current_size else mode['width']))+
                abs(mode['height']-(current_size['height'] if current_size else mode['height'])),
                abs(mode['num']/mode['den']-current_rate[0]/current_rate[1]) if mode['den'] and current_rate[1] else 0,
            ))
            self.format_loading=True
            resolution_index=next(i for i,group in enumerate(self.resolution_groups)
                if (group[0]['width'],group[0]['height'])==(wanted['width'],wanted['height']))
            self.resolution_choice.set_selected(resolution_index)
            self._set_frame_rates((wanted['num'],wanted['den']),fourcc)
            self.format_loading=False
        self._format_selection_changed()

    def _format_selection_changed(self):
        if not self.selected_device or self.video.recorder:return
        if self.video.pipeline:self.stop_preview()
        if self.auto_preview:self.schedule_preview()

    def update_studio_camera(self):
        self.set_formats(self.selected_device.get('formats',[]) if self.selected_device else [])
        self.refresh_profile_names()

    def studio_update_actions(self):
        if not hasattr(self,'profile_choice'):return
        self.virtual_update_actions()
        idle=not self.busy and not self.closing and not self.shutdown_requested;recording=bool(self.video.recorder or self.video.virtual.pipeline)
        connected=bool(self.selected_device)
        for name in ('profile_save','profile_load','profile_delete','camera_defaults','series_start'):
            self.lookup_action(name).set_enabled(idle and connected and not recording and (bool(self.video.pipeline and self.video.frame()) and not self.series_timer if name=='series_start' else self.selected_recording_codec() is not None if name=='profile_save' else True))
        self.camera_defaults_button.set_sensitive(idle and connected and not recording)
        self.profile_save_button.set_sensitive(idle and connected and not recording and self.selected_mode() is not None and self.selected_recording_codec() is not None)
        selected_profile=self.profile_choice.get_selected()<len(self.profile_names)
        self.lookup_action('profile_load').set_enabled(idle and connected and not recording and selected_profile)
        self.lookup_action('profile_delete').set_enabled(idle and connected and not recording and selected_profile)
        self.profile_load_button.set_sensitive(idle and connected and not recording and selected_profile)
        self.profile_delete_button.set_sensitive(idle and connected and not recording and selected_profile)
        self.lookup_action('series_stop').set_enabled(bool(self.series_timer))
        self.resolution_choice.set_sensitive(idle and not recording)
        self.fps_choice.set_sensitive(idle and not recording and bool(self.fps_values))
        self.format_choice.set_sensitive(idle and not recording and bool(self.format_values))
        for w in self.effect_widgets+[self.output_codec,self.quality_choice,self.bitrate_choice,self.duration_choice]:w.set_sensitive(idle and not recording)
        self.quality_choice.set_sensitive(idle and not recording and self.selected_recording_codec() not in (None,'mp4'))
        self.audio_enabled_choice.set_sensitive(idle and not recording)
        self.audio_format_choice.set_sensitive(idle and not recording and bool(self.audio_format_codes))
        audio_recording=bool(self.audio_recorder.pipeline)
        source_index=self.audio_device_choice.get_selected()
        source_available=source_index<len(self.audio_sources) and not self.audio_sources[source_index]['muted']
        self.audio_capture_format.set_sensitive(idle and not recording and not audio_recording and bool(self.audio_capture_formats))
        self.audio_device_choice.set_sensitive(idle and not recording and not audio_recording and bool(self.audio_sources))
        self.audio_capture_start.set_sensitive(idle and not recording and not audio_recording and source_available and bool(self.audio_capture_formats))
        self.audio_capture_stop.set_sensitive(audio_recording and not self.audio_recorder.stopping)
        if hasattr(self,'video_capture_start'):
            live=bool(self.video.pipeline and self.video.frame())
            self.video_capture_start.set_sensitive(idle and live and not recording and not audio_recording and self.selected_recording_codec() is not None)
            self.video_capture_stop.set_sensitive(bool(self.video.recorder) and not self.video.record_stopping)
            self.video_capture_status.set_label(self.tr('video_recording_status') if self.video.recorder else self.tr('video_ready'))

    def studio_menus(self,model):
        file=self.make_menu([[('profile_save','profile_save'),('profile_load','profile_load'),('profile_delete','profile_delete')]])
        fm=Gio.Menu();fm.append_submenu(self.tr('camera_profiles'),file)
        for title,action in [('settings','settings'),('quit','quit')]:
            part=Gio.Menu();part.append(self.tr(title),'win.'+action);fm.append_section(None,part)
        model.remove(0);model.insert_submenu(0,self.tr('file'),fm)
        extra=self.make_menu([[('series_start','series_start'),('series_stop','series_stop')]])
        extra.append_submenu(self.tr('virtual_camera'),self.make_menu([[('virtual_start','virtual_start'),('virtual_stop','virtual_stop')],[('virtual_refresh','virtual_refresh'),('virtual_export','virtual_export')]]))
        model.insert_submenu(model.get_n_items()-1,self.tr('extras'),extra)

    def refresh_profile_names(self):
        self.profile_names=[]
        if self.selected_device:
            try:self.profile_names=self.profile_store.names(self.selected_device)
            except (ValueError,OSError):self.set_status('profile_error')
        self.profile_choice.set_model(Gtk.StringList.new(self.profile_names or [self.tr('no_profiles')]))

    @staticmethod
    def available_recording_formats():
        return recording_formats()

    def selected_recording_codec(self):
        item=self.output_codec.get_selected_item()
        return item.get_string() if item and item.get_string() in RECORDERS else None

    def sync_image_quality(self):
        self.image_quality_choice.set_sensitive(self.selected_image_format()[0]=='jpeg')

    def image_quality_changed(self,*_):
        old=self.opts['image_quality']
        value=self.image_quality_choice.get_value_as_int()
        if value==old:return
        self.opts['image_quality']=value
        try:save_settings(self.opts)
        except OSError:
            self.opts['image_quality']=old
            self.image_quality_choice.set_value(old)
            self.notify('write_error')

    def profile_options(self):
        if self.selected_recording_codec() is None:raise ValueError('encoder_missing')
        return dict(rotation=self.rotation_choice.get_selected()*90,grayscale=self.gray_choice.get_active(),negative=self.negative_choice.get_active(),mirror=self.opts['mirror_horizontal'],crosshair=self.crosshair_choice.get_active(),duration=self.duration_choice.get_value_as_int(),interval=self.interval_choice.get_value_as_int(),count=self.count_choice.get_value_as_int(),codec=self.selected_recording_codec(),quality=self.quality_choice.get_value_as_int(),bitrate=self.bitrate_choice.get_value_as_int())

    def sync_audio_format(self):
        self.quality_choice.set_sensitive(not self.busy and self.selected_recording_codec() not in (None,'mp4') and not self.video.recorder)
        if not hasattr(self,'audio_format_codes'):return
        selected_item=self.output_codec.get_selected_item()
        if selected_item is None:return
        container=selected_item.get_string()
        selected=next((i for i,(_,containers) in enumerate(self.audio_format_codes) if container in containers),0)
        if self.audio_format_codes and self.audio_format_choice.get_selected()!=selected:self.audio_format_choice.set_selected(selected)

    def reset_studio_settings(self):
        """Restore every Studio control to the same defaults used at startup."""
        if self.series_timer:
            self.stop_series()
        self.interval_choice.set_value(STUDIO_DEFAULTS['photo_interval'])
        self.count_choice.set_value(STUDIO_DEFAULTS['photo_count'])
        self.image_save_format.set_selected(min(STUDIO_DEFAULTS['image_format'], max(0, len(self.image_format_codes)-1)))
        self.image_quality_choice.set_value(self.opts['image_quality'])
        self.rotation_choice.set_selected(STUDIO_DEFAULTS['rotation'])
        self.gray_choice.set_active(STUDIO_DEFAULTS['grayscale'])
        self.negative_choice.set_active(STUDIO_DEFAULTS['negative'])
        self.crosshair_choice.set_active(STUDIO_DEFAULTS['crosshair'])
        self.quality_choice.set_value(STUDIO_DEFAULTS['video_quality'])
        self.bitrate_choice.set_value(STUDIO_DEFAULTS['video_bitrate'])
        self.duration_choice.set_value(STUDIO_DEFAULTS['recording_duration'])
        self.output_codec.set_selected(0)
        if self.audio_format_codes:
            self.audio_format_choice.set_selected(STUDIO_DEFAULTS['audio_format'])
        if self.audio_capture_formats:
            self.audio_capture_format.set_selected(STUDIO_DEFAULTS['audio_capture_format'])
        self.audio_device_choice.set_selected(0)
        self.profile_name.set_text('')
        self.set_formats(self.selected_device.get('formats', []) if self.selected_device else [])
        self.sync_audio_format()
        self.sync_image_quality()
        self.effects_changed()
        self.studio_update_actions()

    def audio_format_changed(self,*_):
        index=self.audio_format_choice.get_selected()
        if index>=len(self.audio_format_codes):return
        _,containers=self.audio_format_codes[index]
        selected_item=self.output_codec.get_selected_item()
        if selected_item is None:return
        current=selected_item.get_string()
        chosen=current if current in containers else containers[0]
        if chosen!=current:self.output_codec.set_selected(recording_formats().index(chosen))

    def choose_output_directory(self,key):
        entry=self.image_directory_entry if key=='image_directory' else self.audio_directory_entry
        title='choose_image_directory' if key=='image_directory' else 'choose_audio_directory'
        choose(self,title,lambda path:self.set_output_directory(key,path),
               action=Gtk.FileChooserAction.SELECT_FOLDER,folder=entry.get_text())

    def set_output_directory(self,key,path):
        path=Path(path).resolve()
        old=self.opts[key];self.opts[key]=str(path)
        try:save_settings(self.opts)
        except OSError:
            self.opts[key]=old;self.notify('write_error');return
        entry=self.image_directory_entry if key=='image_directory' else self.audio_directory_entry
        entry.set_text(str(path))

    def apply_profile_controls(self,path,values):
        self.control_restore_failed=False
        try:return uvc.apply_controls(path,values)
        except RuntimeError as error:
            self.control_restore_failed=str(error)=='control_restore_failed'
            raise

    def save_camera_profile(self):
        if not self.selected_device or self.video.recorder:return
        if self.selected_recording_codec() is None:self.notify('encoder_missing');return
        camera=dict(self.selected_device);name=self.profile_name.get_text().strip();mode=self.selected_mode();options=self.profile_options()
        if mode is None:self.notify('no_supported_format');return
        def run():self.profile_store.save(camera,name,mode,options)
        def done(_):self.refresh_profile_names();self.set_status('profile_saved')
        if name in self.profile_names:self.confirm('profile_overwrite',lambda:self.background(run,done,error_key='profile_error'))
        else:self.background(run,done,error_key='profile_error')

    def load_camera_profile(self):
        i=self.profile_choice.get_selected()
        if not self.selected_device or i>=len(self.profile_names) or self.video.recorder:return
        camera=dict(self.selected_device);name=self.profile_names[i]
        try:
            profile=self.profile_store.get(camera,name);mode=profile['mode'];options=profile['options']
            if mode not in camera.get('formats',[]):raise ValueError('profile_format_changed')
            self.validate_profile_options(options)
        except (ValueError,OSError,KeyError):self.notify('profile_error');return
        was_live=bool(self.video.pipeline)
        def run():return self.apply_profile_controls(camera['path'],profile['controls'])
        def done(controls):
            if was_live:self.stop_preview()
            self.selected_device['controls']=controls;self.set_uvc_controls(controls)
            self.set_formats(camera['formats'],mode)
            self.rotation_choice.set_selected(options['rotation']//90)
            self.gray_choice.set_active(options['grayscale']);self.negative_choice.set_active(options['negative'])
            self.set_media_option('mirror_horizontal',options['mirror'])
            self.output_codec.set_selected(recording_formats().index(options['codec']))
            self.quality_choice.set_value(options['quality']);self.bitrate_choice.set_value(options['bitrate'])
            self.crosshair_choice.set_active(options.get('crosshair',False))
            self.duration_choice.set_value(options.get('duration',0));self.interval_choice.set_value(options.get('interval',5));self.count_choice.set_value(options.get('count',10))
            self.profile_name.set_text(name);self.set_status('profile_loaded')
            if was_live:self.schedule_preview()
        self.background(run,done,error_key='profile_error')

    @staticmethod
    def validate_profile_options(options):
        if not isinstance(options,dict) or options.get('rotation') not in (0,90,180,270):raise ValueError('invalid_profile')
        if any(type(options.get(k)) is not bool for k in ('grayscale','negative','mirror')):raise ValueError('invalid_profile')
        if type(options.get('crosshair',False)) is not bool:raise ValueError('invalid_profile')
        for key,low,high,default in [('duration',0,86400,0),('interval',1,3600,5),('count',1,10000,10)]:
            if type(options.get(key,default)) is not int or not low<=options.get(key,default)<=high:raise ValueError('invalid_profile')
        if options.get('codec') not in recording_formats():raise ValueError('encoder_missing')
        if type(options.get('quality')) is not int or not 1<=options['quality']<=100 or type(options.get('bitrate')) is not int or not 100<=options['bitrate']<=100000:raise ValueError('invalid_profile')

    def delete_camera_profile(self):
        i=self.profile_choice.get_selected()
        if not self.selected_device or i>=len(self.profile_names):return
        def delete():
            try:self.profile_store.delete(self.selected_device,self.profile_names[i]);self.refresh_profile_names()
            except (ValueError,OSError,KeyError):self.notify('profile_error')
        self.confirm('profile_delete_confirm',delete)

    def reset_camera_defaults(self):
        if not self.selected_device or self.video.recorder:return
        camera=dict(self.selected_device)
        def reset():
            def run():
                controls=uvc.read_controls(camera['path'])
                values={str(c['id']):c['default'] for c in controls if not c['flags']&(1|2|4) and uvc.reversible(c) and uvc.safe_image_control(camera,c)}
                return self.apply_profile_controls(camera['path'],values)
            def done(controls):self.selected_device['controls']=controls;self.set_uvc_controls(controls);self.set_status('defaults_done')
            self.background(run,done,error_key='camera_error')
        self.confirm('defaults_confirm',reset)

    def start_series(self):
        if not self.video.pipeline or self.video.frame() is None or self.series_timer:return
        def selected(folder):
            self.series_folder=folder;self.series_remaining=self.count_choice.get_value_as_int();self.series_count=0
            self.series_timer=GLib.timeout_add_seconds(self.interval_choice.get_value_as_int(),self.series_tick)
            self.series_tick();self.update_actions()
        choose(self,'series_start',selected,action=Gtk.FileChooserAction.SELECT_FOLDER)

    def series_tick(self):
        if not self.alive or not self.video.pipeline:self.stop_series();return False
        try:
            self.series_count+=1
            format_,extension=self.selected_image_format()
            path=self.series_folder/('foto-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')+f'-{self.series_count:04d}.{extension}')
            self.save_frame(path,format_=format_)
        except (OSError,RuntimeError,GLib.Error):self.stop_series();self.notify('write_error');return False
        self.series_remaining-=1;self.set_status('series_running',remaining=self.series_remaining)
        if self.series_remaining<=0:self.stop_series();return False
        return True

    def stop_series(self):
        if self.series_timer:GLib.source_remove(self.series_timer);self.series_timer=None
        self.update_actions()

    def start_record_timer(self):
        seconds=self.duration_choice.get_value_as_int()
        if seconds:self.record_timer=GLib.timeout_add_seconds(seconds,self.timed_stop_record)

    def timed_stop_record(self):
        self.record_timer=None
        if self.video.recorder:self.stop_record()
        return False

    def cancel_record_timer(self):
        if self.record_timer:GLib.source_remove(self.record_timer);self.record_timer=None
