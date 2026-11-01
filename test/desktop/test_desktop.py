"""Hardware-independent integration checks; all temporary data stays in work/."""
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import time
import unittest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'desktop/vendor'))
from josef_basis import Anwendung
app=Anwendung(ROOT/'projekt.json',entwicklung=True,zustandsordner=ROOT/'work/desktop-test-state')
from desktop.backend import Backend,BackendError
from desktop.video import Video
from desktop.gui import CameraWindow,GROUPS
from gi.repository import Gtk,Gdk,GLib,Gst,Gsk,Gio
from josef_basis.model import validate_settings,atomic_json,settings,config_dir
from josef_basis.i18n import Strings
from josef_basis.menus import descendants


def pump(seconds=.1):
    until=time.monotonic()+seconds
    while time.monotonic()<until:
        while GLib.MainContext.default().pending():
            GLib.MainContext.default().iteration(False)
        time.sleep(.01)

class DesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application=app.gtk_anwendung(fensterklasse=CameraWindow)
        cls.application.register(None)
        cls.window=CameraWindow(cls.application,auto_preview=False)
        cls.window.present()
        deadline=time.monotonic()+15
        while cls.window.busy and time.monotonic()<deadline:pump()
        if cls.window.busy:raise AssertionError('Startup timed out')

    @classmethod
    def tearDownClass(cls):
        cls.window.close()
        pump(.3)
        cls.application.quit()

    def test_backend_catalog(self):
        self.assertEqual(len(self.window.catalog),37)
        self.assertEqual(self.window.bridge.runtime_dir,config_dir()/'ipc')
        self.assertEqual(self.window.get_icon_name(),'tiny')
        self.assertTrue(Gtk.IconTheme.get_for_display(self.window.get_display()).has_icon('tiny'))
        for group,names in GROUPS.items():
            for name in names:self.assertIn('obsbot_'+name,self.window.catalog)
        self.assertNotIn('obsbot_gimbal_move_speed',self.window.catalog)

    def test_schema_fields_and_translation(self):
        w=self.window
        # The safety gate may have restored persisted tracking state from a prior
        # run. Exercise the complete tool schemas in the explicitly safe mode.
        w.ai_mode='no-tracking';w.update_tool_availability()
        for group,names in GROUPS.items():
            for index,name in enumerate(names):
                w.selection[group]['choice'].select_row(w.selection[group]['choice'].get_row_at_index(index))
                w.build_fields(group)
                expected=set(w.catalog['obsbot_'+name]['inputSchema'].get('properties',{}))-{'camera','source','roll'}
                self.assertEqual(set(w.selection[group]['widgets']),expected,name)
                if name=='preset_save':
                    slot_widget=w.selection[group]['widgets']['slot'][0]
                    self.assertIsInstance(slot_widget,Gtk.DropDown)
                    self.assertEqual(
                        [slot_widget.get_model().get_item(i).get_string()
                         for i in range(slot_widget.get_model().get_n_items())],
                        ['1','2','3'],
                    )
                    self.assertEqual(w.selection[group]['widgets']['slot'][1](),1)
                if name=='image_adjust':
                    self.assertIsInstance(w.selection[group]['widgets']['level'][0],Gtk.SpinButton)
                for field in expected:
                    self.assertNotEqual(w.tr('field_'+field),'field_'+field)
        group=w.selection['steering'];group['choice'].select_row(group['choice'].get_row_at_index(0));w.build_fields('steering')
        group['widgets']['yaw'][0].set_value(31)
        w.apply_language('en');pump()
        self.assertEqual(group['widgets']['yaw'][1](),31)
        self.assertEqual(w.output_window.get_title(),'Tiny – Live view')
        w.apply_language('de');pump()
        self.assertEqual(group['widgets']['yaw'][1](),31)
        self.assertEqual(w.output_window.get_title(),'Tiny – Livebild')

    def test_snapshot_and_settings_dialog(self):
        w=self.window
        w.video.start('',640,15,test=True);pump(.7)
        with tempfile.TemporaryDirectory(dir=ROOT/'work') as directory:
            path=Path(directory)/'frame.png'
            original=w.save_path
            def save_photo(title,suffix,callback,folder=None):
                self.assertEqual(folder,w.opts['image_directory'])
                callback(path)
            w.save_path=save_photo
            w.snapshot()
            w.save_path=original
            self.assertEqual(path.read_bytes()[:8],b'\x89PNG\r\n\x1a\n')
            from PIL import Image
            with Image.open(path) as image:self.assertEqual(image.size,(640,360))
        w.video.stop()
        w.show_settings();pump(.2)
        dialog=w.dialogs[-1]
        self.assertIn('language',dialog.template_controls)
        self.assertIn('preview_width',dialog.template_controls['fields'])
        w.close_dialog(dialog)
        # A data-only third language exercises live RTL/LTR without changing production state.
        from josef_basis.languages import install_pack
        from josef_basis.project import read_strings
        folder=config_dir()/'languages/ar'
        if not folder.exists():
            install_pack({'program_id':'obsbot','code':'ar','name':'العربية',
                'strings':read_strings(ROOT,'en'),'help_html':'<html><body><h1>اختبار</h1></body></html>'})
        w.apply_language('ar');pump(.1)
        self.assertEqual(w.get_direction(),Gtk.TextDirection.RTL)
        w.apply_language('de');pump(.1)
        self.assertEqual(w.get_direction(),Gtk.TextDirection.LTR)

    def test_mirrored_pixel_commands(self):
        from unittest.mock import patch
        w=self.window
        w.ai_mode='no-tracking';w.update_tool_availability()
        w.opts['mirror_horizontal']=True
        w.stack.set_visible_child_name('steering')
        section=w.selection['steering']
        for tool,expected in [('aim_at_pixel',1269),('zoom_to_fit',630)]:
            section['choice'].select_row(section['choice'].get_row_at_index(GROUPS['steering'].index(tool)));w.build_fields('steering')
            section['widgets']['x'][0].set_value(10)
            section['widgets']['frameWidth'][0].set_value(1280)
            if tool=='zoom_to_fit':section['widgets']['width'][0].set_value(640)
            with patch.object(w,'command') as command:
                w.apply_tool()
                self.assertEqual(command.call_args.args[0],tool)
                self.assertEqual(command.call_args.args[1]['x'],expected)
        w.opts['mirror_horizontal']=False
        w.stack.set_visible_child_name('format')

    def test_settings_and_corrupt_preservation(self):
        from josef_basis.model import save_settings
        invalid=dict(preview_width=999,preview_fps=-1,status_seconds='bad',language='de')
        validated=validate_settings(invalid)
        self.assertEqual(validated['preview_width'],1280)
        self.assertEqual(validated['preview_fps'],5)
        self.assertEqual(validated['status_seconds'],5)
        path=config_dir()/'settings.json';path.parent.mkdir(exist_ok=True,parents=True)
        path.write_text('{broken',encoding='utf-8')
        self.assertEqual(settings()['language'],'de')
        save_settings(validated)
        self.assertTrue(list(path.parent.glob('settings.invalid.*.json')))
        self.assertEqual(json.loads(path.read_text())['preview_width'],1280)

    def test_real_gtk_menus_themes_and_sizes(self):
        w=self.window
        settings=Gtk.Settings.get_default()
        model=w.menu.get_menu_model()
        model.append_submenu('Test',w.make_menu([[('apply_tool','apply_tool')]]))
        from josef_basis.menus import compact_menus
        compact_menus(w.menu)
        for dark in (False,True):
            settings.set_property('gtk-application-prefer-dark-theme',dark)
            for size in ((1180,800),(800,600)):
                w.set_default_size(*size);pump(.3)
                # Open a genuine one-item menu (Controls) and measure actual allocation.
                items=[x for x in descendants(w.menu) if isinstance(x,Gtk.Popover)]
                one=None
                for pop in items:
                    # one leaf in its model is visible as one accessible text label.
                    labels=[x.get_text() for x in descendants(pop) if isinstance(x,Gtk.Label) and x.get_text() in ('Ausführen','Apply')]
                    if labels:one=pop;break
                self.assertIsNotNone(one)
                one.popup();pump(.3)
                measured=False
                for scroll in descendants(one):
                    if isinstance(scroll,Gtk.ScrolledWindow) and scroll.get_mapped():
                        child=scroll.get_child()
                        natural=child.measure(Gtk.Orientation.VERTICAL,-1).natural
                        self.assertLessEqual(child.get_height(),natural+8)
                        measured=True
                self.assertTrue(measured)
                one.popdown();pump(.1)
                # Render a real GTK frame for internal visual inspection.
                from PIL import ImageGrab
                ImageGrab.grab().save(ROOT/f'work/gui-{"dark" if dark else "light"}-{size[0]}.png')
        settings.set_property('gtk-application-prefer-dark-theme',False)
        model.remove(model.get_n_items()-1)

    def test_video_record_and_existing_file(self):
        errors=[];video=Video(errors.append)
        video.start('',640,15,test=True)
        pump(1)
        self.assertIsNotNone(video.frame())
        with tempfile.TemporaryDirectory(dir=ROOT/'work') as directory:
            path=Path(directory)/'clip.webm'
            path.write_bytes(b'preserve')
            with self.assertRaises(FileExistsError):video.record(path)
            self.assertEqual(path.read_bytes(),b'preserve')
            path.unlink()
            video.record(path)
            pump(1)
            with self.assertRaises(RuntimeError):video.stop()
            finished=[];video.finish_record(lambda error:finished.append(error))
            deadline=time.monotonic()+10
            while not finished and time.monotonic()<deadline:pump()
            self.assertEqual(finished,[None])
            self.assertGreater(path.stat().st_size,1000)
            self.assertEqual(path.read_bytes()[:4],b'\x1aE\xdf\xa3')
            # Decode the actual finalized recording to EOS.
            pipe=Gst.parse_launch('filesrc name=source ! matroskademux ! vp8dec ! fakesink sync=false')
            pipe.get_by_name('source').set_property('location',str(path));pipe.set_state(Gst.State.PLAYING)
            msg=pipe.get_bus().timed_pop_filtered(5*Gst.SECOND,Gst.MessageType.EOS|Gst.MessageType.ERROR)
            pipe.set_state(Gst.State.NULL)
            self.assertIsNotNone(msg);self.assertEqual(msg.type,Gst.MessageType.EOS)
        video.stop();self.assertFalse(errors)

    def test_mirror_and_audio_recording(self):
        import array
        from unittest.mock import patch
        video=Video(lambda error:self.fail(error))
        video.start('',640,15,test=True)
        try:
            pump(.5)
            normal=video.frame()
            video.set_mirror(True);pump(.3)
            mirrored=video.frame()
            # Upper SMPTE bars are stable: compare actual opposing RGB pixels.
            for x in (10,100,200,400,600):
                y=30
                a=normal[0][y*normal[3]+x*3:y*normal[3]+x*3+3]
                b=mirrored[0][y*mirrored[3]+(639-x)*3:y*mirrored[3]+(639-x)*3+3]
                self.assertEqual(a,b)
            with tempfile.TemporaryDirectory(dir=ROOT/'work') as directory:
                path=Path(directory)/'audio.webm'
                with patch('desktop.video.microphones',return_value=[]):
                    with self.assertRaisesRegex(RuntimeError,'audio_missing'):
                        video.record(path,audio=True,audio_device='missing')
                    self.assertFalse(path.exists())
                with patch('desktop.video.microphones',return_value=[dict(name='muted',muted=True)]):
                    with self.assertRaisesRegex(RuntimeError,'audio_muted'):
                        video.record(path,audio=True,audio_device='muted')
                    self.assertFalse(path.exists())
                video.record(path,audio=True,test_audio=True)
                pump(1.5)
                with self.assertRaisesRegex(RuntimeError,'recording_active'):video.set_mirror(False)
                self.assertIsNone(video.check_recording())
                finished=[];video.finish_record(lambda error:finished.append(error))
                deadline=time.monotonic()+10
                while not finished and time.monotonic()<deadline:pump()
                self.assertEqual(finished,[None])
                probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)]))
                self.assertEqual({x['codec_type'] for x in probe['streams']},{'video','audio'})
                self.assertEqual(next(x['codec_name'] for x in probe['streams'] if x['codec_type']=='audio'),'opus')
                starts=[float(x['start_time']) for x in probe['streams']]
                self.assertLess(max(starts)-min(starts),.25)
                self.assertLess(abs(float(probe['format']['duration'])-1.5),.4)
                decoded=subprocess.check_output(['ffmpeg','-v','error','-i',str(path),'-map','0:a:0','-f','s16le','-ac','1','-ar','8000','-'])
                samples=array.array('h');samples.frombytes(decoded)
                self.assertGreater(max(abs(x) for x in samples),1000)
                # First recorded frame must use the same horizontal flip as preview.
                pixels=subprocess.check_output(['ffmpeg','-v','error','-i',str(path),'-map','0:v:0','-frames:v','1','-pix_fmt','rgb24','-f','rawvideo','-'])
                for x in (10,100,200,400,600):
                    start=30*mirrored[3]+x*3
                    expected=mirrored[0][start:start+3]
                    actual=pixels[start:start+3]
                    self.assertTrue(all(abs(a-b)<20 for a,b in zip(actual,expected)))
        finally:
            if video.recorder:
                done=[];video.finish_record(lambda error:done.append(True))
                deadline=time.monotonic()+10
                while not done and time.monotonic()<deadline:pump()
            video.stop()

    def test_media_preferences(self):
        w=self.window
        from unittest.mock import patch
        from desktop.video import camera_microphone
        sources=[dict(name='tiny-mic',usb_port='1-4',muted=False),dict(name='logi-mic',usb_port='1-5',muted=False),dict(name='system',usb_port=None,muted=False)]
        self.assertEqual(camera_microphone(dict(usb_port='1-4'),sources),'tiny-mic')
        self.assertEqual(camera_microphone(dict(usb_port='1-5'),sources),'logi-mic')
        with self.assertRaisesRegex(RuntimeError,'audio_missing'):camera_microphone(dict(usb_port='1-6'),sources)
        sources[1]['muted']=True
        with self.assertRaisesRegex(RuntimeError,'audio_muted'):camera_microphone(dict(usb_port='1-5'),sources)
        self.assertFalse(hasattr(w,'audio_choice'))
        self.assertNotIn('audio_source',settings())
        w.set_media_option('mirror_horizontal',True)
        self.assertTrue(w.video.mirrored)
        self.assertTrue(settings()['mirror_horizontal'])
        w.apply_language('en');pump()
        self.assertTrue(w.lookup_action('mirror_horizontal').get_state().get_boolean())
        w.set_media_option('mirror_horizontal',False)
        w.set_media_option('audio_enabled',False)
        self.assertFalse(settings()['audio_enabled'])
        w.set_media_option('audio_enabled',True)
        w.apply_language('de')

    def test_supported_camera_inventory(self):
        from desktop.uvc import inventory
        with tempfile.TemporaryDirectory(dir=ROOT/'work') as directory:
            base=Path(directory);sys=base/'class';sys.mkdir()
            for number,vendor,product,index in [(0,'3564','OBSBOT Tiny 2',0),(1,'3564','OBSBOT Tiny 2',1),(2,'046d','C922 Pro Stream Webcam',0),(3,'046d','C920',0)]:
                usb=base/f'usb{number}';usb.mkdir()
                for key,value in dict(idVendor=vendor,idProduct='fef8' if vendor=='3564' else '085c',product=product,serial=f'serial{number}').items():(usb/key).write_text(value)
                node=usb/'video4linux'/f'video{number}';node.mkdir(parents=True)
                (node/'name').write_text(product);(node/'index').write_text(str(index))
                (sys/f'video{number}').symlink_to(node,target_is_directory=True)
            from unittest.mock import patch
            from desktop import uvc
            def capability(path):
                if str(path).endswith('1'):raise OSError(19,'metadata node')
                return dict(buffer_type=1)
            with patch.object(uvc,'query_capabilities',side_effect=capability):found=inventory(sys,Path('/dev'))
            self.assertEqual([(x['kind'],x['path']) for x in found],[('tiny2','/dev/video0'),('c922','/dev/video2'),('uvc','/dev/video3')])
            self.assertEqual(found[1]['serial'],'serial2')

    def test_uvc_write_validation(self):
        from unittest.mock import patch
        from desktop import uvc
        import struct
        control=dict(id=0x009A090A,minimum=0,maximum=250,step=5,kind=1,flags=0,choices=[],value=10)
        def ioctl(fd,operation,raw,mutate):
            if operation==uvc.G_CTRL:struct.pack_into('=i',raw,4,10)
        with patch.object(uvc,'_validated',return_value='/dev/test'),patch.object(uvc.os,'open',return_value=42),patch.object(uvc.os,'close'),patch.object(uvc,'_query',return_value=control),patch.object(uvc.fcntl,'ioctl',side_effect=ioctl) as call:
            for value in (-1,251,7):
                with self.assertRaises(ValueError):uvc.write_control('/dev/test',control['id'],value)
            call.assert_not_called()
            self.assertEqual(uvc.write_control('/dev/test',control['id'],10),10)
            control['flags']=16
            with self.assertRaisesRegex(ValueError,'inactive_control'):uvc.write_control('/dev/test',control['id'],10)
        with self.assertRaises(ValueError):uvc.write_control('/dev/null',123,10)

    def test_c922_ui_and_selected_video_path(self):
        from unittest.mock import patch
        w=self.window
        previous=w.camera_devices
        previous_labels=w.camera_names
        previous_index=w.camera_choice.get_selected()
        controls=[dict(id=9963776,key='brightness',kind=1,minimum=0,maximum=255,step=1,value=128,flags=0,choices=[])]
        try:
            w.camera_devices=[dict(path='/dev/c922-test',name='C922',kind='c922',serial='',controls=controls)]
            w.camera_choice.set_model(Gtk.StringList.new(['C922']));w.camera_choice.set_selected(0);w.select_camera()
            self.assertEqual(w.selected_device['kind'],'c922')
            self.assertTrue(w.pages['uvc'].get_visible())
            for group in GROUPS:self.assertFalse(w.pages[group].get_visible())
            self.assertFalse(w.lookup_action('wake').get_enabled())
            self.assertFalse(w.lookup_action('sleep').get_enabled())
            self.assertEqual(w.uvc_get(),128)
            w.uvc_widget.set_value(143)
            w.apply_language('en')
            self.assertEqual(w.uvc_get(),143)
            w.apply_language('de')
            self.assertEqual(w.uvc_get(),143)
            with patch.object(w.video,'start') as start,patch.object(w,'command') as command:
                w.start_preview()
                self.assertEqual(start.call_args.args[0],'/dev/c922-test')
                command.assert_not_called()
        finally:
            w.camera_devices=previous
            w.camera_choice.set_model(Gtk.StringList.new(previous_labels or [w.tr('no_camera')]))
            w.camera_choice.set_selected(previous_index);w.select_camera()
            w.stop_preview()

    def test_verified_wake_and_german_feedback(self):
        from unittest.mock import patch
        from desktop.display import response_text
        backend=Backend()
        responses=[dict(ok=True,state='run'),dict(awake=False),dict(awake=True)]
        with patch.object(backend,'call',side_effect=responses) as call,patch('desktop.backend.time.sleep'):
            value=backend.wake_verified('test-camera')
            self.assertTrue(value['verified'])
            self.assertEqual(call.call_args.args,('obsbot_status',{'camera':'test-camera'}))
        with patch.object(backend,'call',return_value=dict(awake=False)),patch('desktop.backend.time.sleep'):
            with self.assertRaisesRegex(BackendError,'wake_not_confirmed'):backend.wake_verified(timeout=.01)
        text=response_text(dict(ok=True,state='run',awake=True,focusMode='auto',aiMode='upper-body'),Strings('de'))
        for english in ('"ok"','run','true','focusMode','upper-body'):self.assertNotIn(english,text)
        self.assertIn('Ergebnis: Erfolgreich',text)
        self.assertIn('Zustand: Wach',text)
        self.assertIn('Fokusmodus: Automatisch',text)
        w=self.window
        old=w.polling;previous_device=w.selected_device
        w.selected_device=dict(kind='uvc',name='Test camera',path='/dev/test')
        w.polling=True;w.update_actions()
        self.assertTrue(w.lookup_action('preview_start').get_enabled(),dict(alive=w.alive,closing=w.closing,shutdown=w.shutdown_requested,busy=w.busy,live=bool(w.video.pipeline),camera=bool(w.selected_device)))
        w.polling=old;w.selected_device=previous_device;w.update_actions()

    def test_camera_change_starts_preview_automatically(self):
        from unittest.mock import patch
        w=self.window
        previous=w.auto_preview;w.auto_preview=True
        try:
            with patch.object(w,'select_camera') as select,patch.object(w,'schedule_preview') as start:
                w.on_camera_selected()
                select.assert_called_once();start.assert_called_once()
            w.camera_loading=True
            with patch.object(w,'schedule_preview') as start:w.on_camera_selected();start.assert_not_called()
        finally:
            w.camera_loading=False;w.auto_preview=previous

    def test_backend_timeout_and_recovery_bound(self):
        backend=Backend(command=[sys.executable,'-u','-c','import time;time.sleep(10)'])
        try:
            # Skip handshake to specifically cover the bounded waiting path.
            backend.start=lambda:None
            backend.process=subprocess.Popen(backend.command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            with self.assertRaisesRegex(BackendError,'backend_timeout'):
                backend.request('x',timeout=.1,start=False)
            self.assertIsNone(backend.process)
        finally:backend.close()


    def test_all_recording_containers_decodable_with_audio(self):
        from desktop.video import recording_formats
        errors=[];video=Video(errors.append);video.start('',640,15,test=True)
        pump(.3)
        try:
            with tempfile.TemporaryDirectory(dir=ROOT/'work') as folder:
                for codec in recording_formats():
                    path=Path(folder)/('sample.'+codec)
                    video.record(path,audio=True,test_audio=True,container=codec,quality=75,bitrate=1500000)
                    pump(.8);done=[];video.finish_record(done.append)
                    deadline=time.monotonic()+10
                    while not done and time.monotonic()<deadline:pump(.1)
                    self.assertEqual(done,[None],codec)
                    probe=subprocess.run(['ffprobe','-v','error','-show_streams','-of','json',str(path)],capture_output=True,text=True,check=True)
                    streams=json.loads(probe.stdout)['streams']
                    self.assertEqual({x['codec_type'] for x in streams},{'audio','video'},codec)
                    subprocess.run(['ffmpeg','-v','error','-i',str(path),'-f','null','-'],capture_output=True,check=True)
                    self.assertEqual(next(x for x in streams if x['codec_type']=='video')['width'],640)
        finally:video.stop()
        self.assertFalse(errors)

    def test_rotation_grayscale_negative_and_measured_rate(self):
        from PIL import Image,ImageChops,ImageStat
        video=Video(lambda e:self.fail(e));video.start('',640,15,test=True)
        def image():
            data,w,h,stride=video.frame();return Image.frombytes('RGB',(w,h),data,'raw','RGB',stride)
        try:
            pump(.4);self.assertGreater(video.measured_fps(),10)
            video.set_effects(90,True,False);pump(.3)
            gray=image();self.assertEqual(gray.size,(360,640))
            r,g,b=gray.split();self.assertLess(max(ImageStat.Stat(ImageChops.difference(r,g)).mean),1)
            self.assertLess(max(ImageStat.Stat(ImageChops.difference(g,b)).mean),1)
            video.set_effects(90,True,True);pump(.2)
            negative=image()
            # Color-bar region is stable even though the test-pattern clock moves.
            expected=ImageChops.invert(gray).crop((20,20,250,400))
            difference=ImageStat.Stat(ImageChops.difference(negative.crop((20,20,250,400)),expected)).mean
            self.assertLess(max(difference),5)
        finally:video.stop()

    def test_formats_preserve_fractional_rates_and_sizes(self):
        from unittest.mock import patch
        from desktop import uvc
        import struct,errno
        pixel=struct.unpack('=I',b'MJPG')[0]
        def ioctl(fd,operation,raw,mutate):
            index=struct.unpack_from('=I',raw)[0]
            if operation==0xC0405602:
                if index:raise OSError(errno.EINVAL,'end')
                struct.pack_into('=I',raw,44,pixel)
            elif operation==0xC02C564A:
                if index>1:raise OSError(errno.EINVAL,'end')
                struct.pack_into('=III',raw,8,1,*[(640,480),(1920,1080)][index])
            elif operation==0xC034564B:
                if index>1:raise OSError(errno.EINVAL,'end')
                struct.pack_into('=III',raw,16,1,*[(1,30),(1001,60000)][index])
        with patch.object(uvc,'_validated',return_value='/dev/test'),patch.object(uvc,'query_capabilities',return_value=dict(buffer_type=1)),patch.object(uvc.os,'open',return_value=42),patch.object(uvc.os,'close'),patch.object(uvc.fcntl,'ioctl',side_effect=ioctl):
            modes=uvc.formats('/dev/test')
        self.assertEqual(len(modes),4)
        self.assertEqual(modes[-1],dict(fourcc='MJPG',width=1920,height=1080,num=60000,den=1001))

    def test_profile_isolation_and_automatic_mode_restoration_on_error(self):
        from unittest.mock import patch
        from desktop import uvc
        from desktop.profiles import Profiles
        auto=dict(id=0x009A090C,key='focus_auto',minimum=0,maximum=1,step=1,kind=2,flags=0,choices=[],value=1,default=1)
        focus=dict(id=0x009A090A,key='focus',minimum=0,maximum=250,step=5,kind=1,flags=0,choices=[],value=25,default=0)
        controls=[auto,focus]
        writes=[]
        def write(path,identifier,value):
            writes.append((identifier,value))
            if identifier==focus['id']:raise OSError('disconnected')
        with patch.object(uvc,'read_controls',return_value=controls),patch.object(uvc,'write_control',side_effect=write):
            with self.assertRaises(OSError):uvc.apply_controls('/dev/test',{str(auto['id']):1,str(focus['id']):100})
        self.assertEqual(writes,[(auto['id'],0),(focus['id'],100),(auto['id'],1)])
        with tempfile.TemporaryDirectory(dir=ROOT/'work') as directory,patch.object(uvc,'read_controls',return_value=controls):
            profiles=Profiles(directory)
            camera=dict(kind='uvc',name='Generic webcam',serial='a',path='/dev/test')
            profiles.save(camera,'Desk',dict(width=640),dict(codec='webm'))
            self.assertEqual(profiles.names(camera),['Desk'])
            self.assertEqual(profiles.names(dict(camera,serial='b')),[])
            self.assertEqual(profiles.get(camera,'Desk')['controls'][str(focus['id'])],25)
            with self.assertRaises(ValueError):profiles.save(camera,'',{},{} )
            profiles.delete(camera,'Desk');self.assertEqual(profiles.names(camera),[])

    def test_timed_capture_series_and_no_camera_response_pane(self):
        from unittest.mock import patch
        w=self.window
        self.assertFalse(hasattr(w,'detail_expander'));self.assertFalse(hasattr(w,'result_label'))
        w.video.start('',640,15,test=True);pump(.3)
        with tempfile.TemporaryDirectory(dir=ROOT/'work') as directory:
            try:
                def choose(owner,title,callback,**kwargs):callback(Path(directory))
                with patch('desktop.studio.choose',side_effect=choose):
                    w.interval_choice.set_value(1);w.count_choice.set_value(2);w.start_series()
                pump(2.3)
                files=list(Path(directory).glob('*.png'));self.assertEqual(len(files),2)
                self.assertIsNone(w.series_timer)
                w.video.record(Path(directory)/'limited.webm')
                w.duration_choice.set_value(1);w.start_record_timer();pump(2.5)
                deadline=time.monotonic()+10
                while w.video.recorder and time.monotonic()<deadline:pump(.1)
                self.assertIsNone(w.video.recorder);self.assertIsNone(w.record_timer)
                subprocess.run(['ffmpeg','-v','error','-i',str(Path(directory)/'limited.webm'),'-f','null','-'],capture_output=True,check=True)
            finally:w.stop_series();w.cancel_record_timer();w.video.stop();w.duration_choice.set_value(0)



    def test_rotated_pixel_command_coordinates(self):
        from desktop.video import camera_coordinates
        point=dict(x=0,y=0,frameWidth=720,frameHeight=1280)
        self.assertEqual(camera_coordinates(point,90,False),dict(x=0,y=719,frameWidth=1280,frameHeight=720))
        self.assertEqual(camera_coordinates(point,90,True),dict(x=0,y=0,frameWidth=1280,frameHeight=720))
        box=dict(x=100,y=200,width=50,height=80,frameWidth=720,frameHeight=1280)
        self.assertEqual(camera_coordinates(box,90,False,True),dict(x=200,y=570,width=80,height=50,frameWidth=1280,frameHeight=720))
        self.assertEqual(camera_coordinates(box,270,False,True),dict(x=1000,y=100,width=80,height=50,frameWidth=1280,frameHeight=720))



    def test_shutdown_during_wake_and_during_record_finalization(self):
        from unittest.mock import patch,Mock
        import threading
        def window():
            with patch.object(CameraWindow,'refresh_devices'):other=CameraWindow(self.application,auto_preview=False)
            other.bridge.close()
            other.bridge=Mock()
            other.bridge.call.return_value={'cameras':[{'serial':'test-tiny'}]}
            other.present();pump(.05)
            return other
        other=window();started=threading.Event();release=threading.Event()
        def wake(serial):started.set();release.wait(2);return dict(awake=True)
        other.bridge.wake_verified.side_effect=wake
        other.camera_serial='test-tiny'
        other.command('wake',{})
        self.assertTrue(started.wait(1));other.request_quit();release.set()
        deadline=time.monotonic()+4
        while other.alive and time.monotonic()<deadline:pump(.05)
        self.assertFalse(other.alive)
        other.bridge.sleep_verified.assert_called_once_with('test-tiny')
        other=window();other.video.start('',640,15,test=True);pump(.3)
        with tempfile.TemporaryDirectory(dir=ROOT/'work') as directory:
            path=Path(directory)/'finalizing.webm';other.video.record(path);pump(.3)
            other.stop_record();other.request_quit()
            deadline=time.monotonic()+10
            while other.alive and time.monotonic()<deadline:pump(.05)
            self.assertFalse(other.alive)
            subprocess.run(['ffmpeg','-v','error','-i',str(path),'-f','null','-'],capture_output=True,check=True)
        pump(.1)



    def test_virtual_output_receives_processed_pixels_and_stops_with_preview(self):
        from PIL import Image
        video=Video(lambda error:self.fail(error));video.start('',640,15,test=True,grayscale=True,negative=True)
        pump(.4)
        mode=dict(fourcc='RGB3',width=320,height=180,num=15,den=1)
        try:
            video.virtual.start('',mode,video.frame(),(15,1),test=True)
            deadline=time.monotonic()+3
            while not video.virtual.ready and time.monotonic()<deadline:
                pump(.1);self.assertIsNone(video.virtual.check())
            self.assertTrue(video.virtual.ready);self.assertGreater(video.virtual.frames,0)
            sample=video.virtual.pipeline.get_by_name('output').get_property('last-sample')
            caps=sample.get_caps().get_structure(0)
            self.assertEqual((caps.get_value('width'),caps.get_value('height')),(320,180))
            buffer=sample.get_buffer();ok,mapped=buffer.map(Gst.MapFlags.READ);self.assertTrue(ok)
            try:output=Image.frombytes('RGB',(320,180),bytes(mapped.data),'raw','RGB',len(mapped.data)//180)
            finally:buffer.unmap(mapped)
            data,width,height,stride=video.frame();source=Image.frombytes('RGB',(width,height),data,'raw','RGB',stride)
            for x in (30,80,130,180,230):
                actual=output.getpixel((x,10));expected=source.getpixel((x*2,20))
                self.assertLessEqual(max(abs(a-b) for a,b in zip(actual,expected)),3)
                self.assertLessEqual(max(actual)-min(actual),1)
            with self.assertRaisesRegex(RuntimeError,'virtual_active'):video.set_mirror(True)
            video.stop();self.assertIsNone(video.virtual.pipeline)
        finally:video.stop()

    def test_virtual_capture_and_output_are_separate_and_physical_outputs_excluded(self):
        from unittest.mock import patch
        from desktop import uvc
        with tempfile.TemporaryDirectory(dir=ROOT/'work') as directory:
            root=Path(directory)
            for number,name in [(10,'Studio output'),(11,'Studio virtual camera'),(12,'Physical camera')]:
                node=root/f'video{number}';node.mkdir();(node/'name').write_text(name)
            def capabilities(path,*,output=False):
                number=int(str(path).rsplit('video',1)[1])
                if output and number==11 or not output and number==10:return None
                return dict(driver='uvcvideo' if number==12 else 'akvcam',buffer_type=2 if output else 1)
            with patch.object(uvc,'query_capabilities',side_effect=capabilities):
                capture=uvc.inventory(root,Path('/dev'));output=uvc.inventory(root,Path('/dev'),output=True)
            self.assertEqual([(d['path'],d['kind']) for d in capture],[('/dev/video11','virtual'),('/dev/video12','uvc')])
            self.assertEqual([(d['path'],d['driver']) for d in output],[('/dev/video10','akvcam')])
            with patch.object(uvc,'inventory',return_value=output) as inventory:
                self.assertEqual(uvc._validated('/dev/video10',output=True),'/dev/video10')
                inventory.assert_called_once_with(output=True)

    def test_virtual_menu_guards_feedback_and_exports_configuration_without_install(self):
        from unittest.mock import patch
        from desktop.virtual_camera import configuration_template
        import configparser
        parser=configparser.ConfigParser();parser.read_string(configuration_template())
        self.assertEqual(parser['Connections']['connections/1/connection'],'1:2')
        w=self.window;previous=w.selected_device
        devices=w.virtual_devices
        try:
            mode=dict(fourcc='RGB3',width=640,height=360,num=15,den=1)
            w.set_virtual_cameras([dict(path='/dev/output-test',name='Virtual output',formats=[mode])])
            w.selected_device=dict(path='/dev/capture-test',name='Virtual capture',kind='virtual',driver='akvcam')
            with patch.object(w,'notify') as notify,patch.object(w.video.virtual,'start') as start:
                w.start_virtual_camera();notify.assert_called_once_with('virtual_loop');start.assert_not_called()
            with tempfile.TemporaryDirectory(dir=ROOT/'work') as directory:
                path=Path(directory)/'example.ini'
                with patch.object(w,'save_path',side_effect=lambda title,suffix,callback:callback(path)):
                    w.export_virtual_configuration()
                self.assertEqual(path.read_text(),configuration_template())
        finally:w.selected_device=previous;w.set_virtual_cameras(devices)

if __name__=='__main__':unittest.main(verbosity=2)
