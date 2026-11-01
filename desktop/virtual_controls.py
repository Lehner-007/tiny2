"""GTK menu controls for an already configured virtual camera."""
from gi.repository import Gtk,Gio
from josef_basis.gui import vertical
from . import uvc
from .video import choose_mode
from .virtual_camera import configuration_template


class VirtualControls:
    def build_virtual_page(self):
        self.virtual_devices=[];self.virtual_modes=[];self.virtual_failure=False
        page=vertical(margin=8)
        page.append(self.label('virtual_explanation',xalign=0,wrap=True))
        page.append(self.label('virtual_target',xalign=0))
        self.virtual_choice=Gtk.DropDown.new_from_strings([self.tr('virtual_no_target')])
        self.virtual_choice.connect('notify::selected',lambda *_:self.virtual_target_changed())
        page.append(self.virtual_choice)
        page.append(self.label('format',xalign=0))
        self.virtual_format=Gtk.DropDown.new_from_strings([self.tr('no_formats')]);page.append(self.virtual_format)
        self.virtual_status=self.label('virtual_missing',xalign=0,wrap=True);page.append(self.virtual_status)
        page.append(self.label('virtual_hint',xalign=0,wrap=True))
        self.pages['virtual_camera']=self.add_stack_page(page,'virtual_camera')
        for name,callback in [('virtual_start',self.start_virtual_camera),('virtual_stop',self.stop_virtual_camera),('virtual_refresh',self.refresh_virtual_cameras),('virtual_export',self.export_virtual_configuration)]:
            action=Gio.SimpleAction.new(name,None);action.connect('activate',lambda *_,callback=callback:callback());self.add_action(action)

    @staticmethod
    def scan_virtual_cameras():
        devices=uvc.inventory(output=True)
        for device in devices:
            try:device['formats']=[m for m in uvc.formats(device['path'],output=True) if m['fourcc'] in uvc.RAW_FORMATS and m['num']>0]
            except (OSError,ValueError):device['formats']=[]
        return devices

    def set_virtual_cameras(self,devices):
        self.virtual_devices=list(devices);self.virtual_failure=False
        self.virtual_choice.set_model(Gtk.StringList.new([d['name'] for d in devices] or [self.tr('virtual_no_target')]))
        self.virtual_target_changed();self.update_actions()

    def virtual_target_changed(self):
        index=self.virtual_choice.get_selected()
        self.virtual_modes=self.virtual_devices[index]['formats'] if index<len(self.virtual_devices) else []
        self.virtual_format.set_model(Gtk.StringList.new([f"{m['width']} × {m['height']} · {m['num']/m['den']:.2f} fps · {m['fourcc']}" for m in self.virtual_modes] or [self.tr('no_formats')]))
        if self.virtual_modes:
            frame=self.video.frame();width=frame[1] if frame else 1280
            mode=choose_mode(self.virtual_modes,width,30);self.virtual_format.set_selected(self.virtual_modes.index(mode))
        self.update_actions()

    def refresh_virtual_cameras(self):
        if self.busy or self.video.virtual.pipeline:return
        self.background(self.scan_virtual_cameras,self.set_virtual_cameras,error_key='virtual_failed',title_key='virtual_refresh')

    def virtual_update_actions(self):
        if not hasattr(self,'virtual_choice'):return
        idle=not self.busy and not self.closing and not self.shutdown_requested
        active=bool(self.video.virtual.pipeline)
        source=self.selected_device
        physical=bool(source and source.get('kind')!='virtual' and source.get('driver','') not in uvc.VIRTUAL_DRIVERS)
        ready=bool(self.video.pipeline and self.video.frame() and self.virtual_modes)
        self.lookup_action('virtual_start').set_enabled(idle and physical and ready and not active)
        self.lookup_action('virtual_stop').set_enabled(idle and active)
        self.lookup_action('virtual_refresh').set_enabled(idle and not active)
        self.lookup_action('virtual_export').set_enabled(idle)
        self.virtual_choice.set_sensitive(idle and not active and bool(self.virtual_devices))
        self.virtual_format.set_sensitive(idle and not active and bool(self.virtual_modes))

    def start_virtual_camera(self):
        index=self.virtual_choice.get_selected();mode_index=self.virtual_format.get_selected()
        if self.busy or self.video.virtual.pipeline:return
        if index>=len(self.virtual_devices) or mode_index>=len(self.virtual_modes):self.notify('virtual_missing');return
        source=self.selected_device;target=self.virtual_devices[index]
        if not source or source.get('kind')=='virtual' or source.get('driver','') in uvc.VIRTUAL_DRIVERS or source['path']==target['path']:
            self.notify('virtual_loop');return
        frame=self.video.frame()
        if frame is None:self.notify('preview_required');return
        mode=dict(self.virtual_modes[mode_index]);rate=(self.video.rate_num,self.video.rate_den)
        self.virtual_failure=False
        def create():self.video.virtual.start(target['path'],mode,frame,rate)
        def done(_):self.virtual_status.set_label(self.tr('virtual_starting'));self.update_actions()
        self.background(create,done,error_key='virtual_failed',title_key='virtual_starting')

    def stop_virtual_camera(self):
        self.video.virtual.stop();self.virtual_failure=False
        self.virtual_status.set_label(self.tr('virtual_idle'));self.set_status('virtual_idle');self.update_actions()

    def render_virtual_camera(self):
        output=self.video.virtual
        if output.pipeline:
            error=output.check()
            if error:
                self.logger.warning('%s: %s',self.tr('virtual_failed'),error)
                output.stop();self.virtual_failure=True;self.update_actions()
                if not self.shutdown_requested:self.set_status('virtual_failed');self.notify('virtual_failed')
        key='virtual_failed' if self.virtual_failure else ('virtual_running' if output.ready else 'virtual_starting') if output.pipeline else 'virtual_idle' if self.virtual_devices else 'virtual_missing'
        self.virtual_status.set_label(self.tr(key))

    def export_virtual_configuration(self):
        def write(path):
            try:
                with open(path,'x',encoding='utf-8') as target:target.write(configuration_template())
                self.set_status('file_saved',path=str(path))
            except OSError:self.notify('write_error')
        self.save_path('virtual_export','.ini',write)
