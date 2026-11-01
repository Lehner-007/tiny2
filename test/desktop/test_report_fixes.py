"""Regression cases from the Tiny 0.16.3 archive review; no physical devices."""
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
ROOT=Path(__file__).resolve().parents[2]
(ROOT/'work').mkdir(exist_ok=True)
sys.path[:0]=[str(ROOT),str(ROOT/'desktop/vendor')]
from josef_basis import Anwendung
state=tempfile.TemporaryDirectory(dir=ROOT/'work')
app=Anwendung(ROOT/'projekt.json',entwicklung=True,zustandsordner=state.name)
from desktop.gui import CameraWindow
from desktop.studio import STUDIO_DEFAULTS
from desktop.video import AudioRecorder,Gst
from desktop import uvc
from gi.repository import Gtk,GLib

class ReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application=app.gtk_anwendung(fensterklasse=CameraWindow);cls.application.register(None)
        with patch.object(CameraWindow,'refresh_devices'),patch.object(CameraWindow,'show_output',return_value=False):
            cls.window=CameraWindow(cls.application,auto_preview=False)
    @classmethod
    def tearDownClass(cls):
        cls.window.alive=False;cls.window.bridge.close();cls.window.destroy();cls.window.output_window.destroy();cls.application.quit()

    def test_audio_finalization_preserves_file_on_all_outcomes(self):
        for result in ('eos','error','timeout','previous-error','exception'):
            with self.subTest(result=result),tempfile.TemporaryDirectory(dir=ROOT/'work') as folder:
                path=Path(folder)/'recording.wav';path.write_bytes(b'recoverable-audio')
                recorder=AudioRecorder();recorder.path=path;recorder.fd=os.open(path,os.O_WRONLY)
                pipe=Mock();recorder.pipeline=pipe;pipe.get_by_name.return_value.send_event.return_value=True
                pipe.get_bus.return_value.timed_pop_filtered.return_value=(None if result=='timeout' else SimpleNamespace(type=Gst.MessageType.EOS if result=='eos' else Gst.MessageType.ERROR))
                if result=='previous-error':recorder.error='capture error'
                if result=='exception':pipe.get_by_name.return_value.send_event.side_effect=RuntimeError('disconnected')
                done=Mock()
                with patch('desktop.video.threading.Thread',side_effect=lambda target,**_:SimpleNamespace(start=target)),patch('desktop.video.GLib.idle_add',side_effect=lambda fn,*args:fn(*args)):
                    recorder.stop(done)
                done.assert_called_once_with(None if result=='eos' else 'audio_record_failed')
                self.assertEqual(path.read_bytes(),b'recoverable-audio')
                self.assertIsNone(recorder.fd);self.assertIsNone(recorder.pipeline)

    def test_audio_failed_start_only_removes_empty_files(self):
        for nonempty in (False,True):
            with tempfile.TemporaryDirectory(dir=ROOT/'work') as folder:
                path=Path(folder)/'start.wav';pipe=Mock();fds={}
                pipe.get_by_name.return_value.set_property.side_effect=lambda key,value:fds.update({key:value})
                def play(state):
                    if state==Gst.State.PLAYING and nonempty:os.write(fds['fd'],b'audio-data')
                    return Gst.StateChangeReturn.FAILURE
                pipe.set_state.side_effect=play
                with patch('desktop.video.audio_recording_formats',return_value=['wav']),patch('desktop.video.Gst.parse_launch',return_value=pipe):
                    with self.assertRaises(RuntimeError):AudioRecorder().start(path,'fake','wav')
                self.assertEqual(path.exists(),nonempty)

    def test_unreliable_control_cannot_write_or_fake_selection(self):
        control=dict(id=0x009A0901,key='exposure_auto',minimum=0,maximum=3,step=1,kind=3,flags=0,choices=[(1,'manual'),(2,'shutter')],value=0,default=0)
        w=self.window;old=w.selected_device
        try:
            w.selected_device=dict(path='/dev/test',kind='tiny2')
            w.set_uvc_controls([control])
            self.assertIsNone(w.uvc_get);self.assertFalse(w.uvc_widget.get_sensitive())
            with patch.object(w,'background') as start:w.apply_uvc();start.assert_not_called()
            with patch.object(uvc,'_validated',return_value='/dev/test'),patch.object(uvc.os,'open',return_value=42),patch.object(uvc.os,'close'),patch.object(uvc,'_query',return_value=control),patch.object(uvc.fcntl,'ioctl') as ioctl:
                with self.assertRaisesRegex(ValueError,'unreliable_control'):uvc.write_control('/dev/test',control['id'],1)
                ioctl.assert_not_called()
        finally:w.selected_device=old;w.set_uvc_controls([])

    def test_restore_failure_is_reported(self):
        control=dict(id=0x009A090C,key='focus_auto',minimum=0,maximum=1,step=1,kind=2,flags=0,choices=[],value=1,default=1)
        focus=dict(control,id=0x009A090A,key='focus')
        with patch.object(uvc,'read_controls',return_value=[control,focus]),patch.object(uvc,'write_control',side_effect=[0,OSError('write'),OSError('restore')]):
            with self.assertRaisesRegex(RuntimeError,'control_restore_failed'):uvc.apply_controls('/dev/test',{str(control['id']):1,str(focus['id']):1})

        with patch.object(uvc,'apply_controls',side_effect=RuntimeError('control_restore_failed')):
            with self.assertRaises(RuntimeError):self.window.apply_profile_controls('/dev/test',{})
        with patch('josef_basis.gui.MainWindow.notify') as notify:
            self.window.notify('profile_error')
            notify.assert_called_once_with('control_restore_failed')

    def test_empty_encoder_handlers_and_actions(self):
        w=self.window;model=w.output_codec.get_model();old=w.selected_device
        try:
            w.output_codec.set_model(Gtk.StringList.new([]));w.selected_device=dict(kind='uvc',path='/dev/test')
            with patch.object(w,'notify') as notify,patch.object(w,'save_path') as save:
                w.record();notify.assert_called_with('encoder_missing');save.assert_not_called()
                w.save_camera_profile();notify.assert_called_with('encoder_missing')
                with self.assertRaisesRegex(ValueError,'encoder_missing'):w.profile_options()
            w.update_actions();self.assertFalse(w.lookup_action('record_start').get_enabled())
            self.assertFalse(w.profile_save_button.get_sensitive())
        finally:w.output_codec.set_model(model);w.selected_device=old

    def test_series_uses_format_and_jpeg_quality_persists(self):
        w=self.window
        frame=(bytes([x%256 for x in range(96*54*3)]),96,54,96*3)
        with tempfile.TemporaryDirectory(dir=ROOT/'work') as folder,patch.object(w.video,'frame',return_value=frame),patch.object(w.video,'pipeline',Mock()):
            try:
                for fmt in ('jpeg','png'):
                    w.image_save_format.set_selected(w.image_format_codes.index(fmt));w.series_folder=Path(folder);w.series_count=0;w.series_remaining=1
                    w.series_tick()
                    extension='jpg' if fmt=='jpeg' else 'png'
                    data=next(Path(folder).glob('*.'+extension)).read_bytes()
                    self.assertTrue(data.startswith(b'\xff\xd8' if fmt=='jpeg' else b'\x89PNG'))
                w.image_save_format.set_selected(w.image_format_codes.index('jpeg'))
                sizes=[]
                for quality in (10,95):
                    w.image_quality_choice.set_value(quality)
                    path=Path(folder)/f'{quality}.jpg';w.save_frame(path,frame,'jpeg');sizes.append(path.stat().st_size)
                self.assertLess(sizes[0],sizes[1])
                from josef_basis.model import settings
                self.assertEqual(settings()['image_quality'],95)
                w.image_save_format.set_selected(w.image_format_codes.index('png'));self.assertFalse(w.image_quality_choice.get_sensitive())
            finally:w.image_save_format.set_selected(w.image_format_codes.index('png'))

    def test_mp4_quality_disabled_bitrate_available(self):
        w=self.window;model=w.output_codec.get_model();index=w.output_codec.get_selected()
        try:
            w.output_codec.set_model(Gtk.StringList.new(['mp4','webm']))
            w.output_codec.set_selected(0);w.update_actions()
            self.assertFalse(w.quality_choice.get_sensitive());self.assertTrue(w.bitrate_choice.get_sensitive())
            w.output_codec.set_selected(1);w.update_actions();self.assertTrue(w.quality_choice.get_sensitive())
        finally:w.output_codec.set_model(model);w.output_codec.set_selected(index)

    def test_reset_all_restores_studio_and_recording_defaults(self):
        w=self.window
        # Dirty every Studio control that the global reset is required to restore.
        w.interval_choice.set_value(9);w.count_choice.set_value(3)
        if 'jpeg' in w.image_format_codes:w.image_save_format.set_selected(w.image_format_codes.index('jpeg'))
        w.image_quality_choice.set_value(35)
        w.rotation_choice.set_selected(2);w.gray_choice.set_active(True)
        w.negative_choice.set_active(True);w.crosshair_choice.set_active(True)
        w.quality_choice.set_value(35);w.bitrate_choice.set_value(12300);w.duration_choice.set_value(44)
        if w.audio_format_codes:w.audio_format_choice.set_selected(len(w.audio_format_codes)-1)
        if w.audio_capture_formats:w.audio_capture_format.set_selected(len(w.audio_capture_formats)-1)
        w.profile_name.set_text('temporary profile')

        w.perform_reset_all_settings()

        self.assertEqual(w.interval_choice.get_value_as_int(),STUDIO_DEFAULTS['photo_interval'])
        self.assertEqual(w.count_choice.get_value_as_int(),STUDIO_DEFAULTS['photo_count'])
        self.assertEqual(w.image_save_format.get_selected(),STUDIO_DEFAULTS['image_format'])
        self.assertEqual(w.image_quality_choice.get_value_as_int(),w.opts['image_quality'])
        self.assertEqual(w.rotation_choice.get_selected(),STUDIO_DEFAULTS['rotation'])
        self.assertFalse(w.gray_choice.get_active())
        self.assertFalse(w.negative_choice.get_active())
        self.assertFalse(w.crosshair_choice.get_active())
        self.assertEqual(w.quality_choice.get_value_as_int(),STUDIO_DEFAULTS['video_quality'])
        self.assertEqual(w.bitrate_choice.get_value_as_int(),STUDIO_DEFAULTS['video_bitrate'])
        self.assertEqual(w.duration_choice.get_value_as_int(),STUDIO_DEFAULTS['recording_duration'])
        self.assertEqual(w.output_codec.get_selected(),0)
        self.assertEqual(w.audio_capture_format.get_selected(),STUDIO_DEFAULTS['audio_capture_format'])
        self.assertEqual(w.profile_name.get_text(),'')
        self.assertEqual(w.profile_options()['rotation'],0)
        self.assertFalse(w.profile_options()['grayscale'])
        self.assertFalse(w.profile_options()['negative'])
        self.assertFalse(w.profile_options()['crosshair'])
        self.assertEqual(w.profile_options()['quality'],STUDIO_DEFAULTS['video_quality'])
        self.assertEqual(w.profile_options()['bitrate'],STUDIO_DEFAULTS['video_bitrate'])
        self.assertEqual(w.profile_options()['duration'],STUDIO_DEFAULTS['recording_duration'])

        codec=w.selected_recording_codec()
        if codec is None:
            self.skipTest('Kein Videoencoder in dieser Umgebung vorhanden')
        captured={}
        output=Path(state.name)/'reset-defaults.webm'
        with patch.object(w,'available_recording_formats',return_value=[codec]), \
             patch.object(w,'save_path',side_effect=lambda *args,**kwargs:args[2](output)), \
             patch.object(w,'background',side_effect=lambda callback,done,**kwargs:captured.update(create=callback)), \
             patch('desktop.gui.camera_microphone',return_value=None), \
             patch.object(w.video,'record') as record:
            w.record()
            captured['create']()
        record.assert_called_once_with(output,audio=w.opts['audio_enabled'],audio_device=None,
            container=codec,quality=STUDIO_DEFAULTS['video_quality'],
            bitrate=STUDIO_DEFAULTS['video_bitrate']*1000)

if __name__=='__main__':
    try:unittest.main(verbosity=2)
    finally:state.cleanup()
