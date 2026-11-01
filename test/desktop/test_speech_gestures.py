"""Real GTK navigation/form checks without opening a camera."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'desktop/vendor')]
from josef_basis import Anwendung
state=tempfile.TemporaryDirectory(dir=ROOT/'work')
app=Anwendung(ROOT/'projekt.json',entwicklung=True,zustandsordner=state.name)
from desktop.gui import CameraWindow
from desktop.backend import Backend
from josef_basis.model import config_dir
from gi.repository import Gtk,GLib

class SpeechGestureTests(unittest.TestCase):
    def test_navigation_and_fields(self):
        application=app.gtk_anwendung(fensterklasse=CameraWindow)
        application.register(None)
        with patch.object(CameraWindow,'refresh_devices'),patch.object(CameraWindow,'show_output',return_value=False):
            window=CameraWindow(application,auto_preview=False)
        try:
            window.catalog={x['name']:x for x in window.bridge.tools()}
            row=window.nav_rows['speech_gestures']
            window.nav_list.select_row(row)
            self.assertEqual(window.stack.get_visible_child_name(),'speech_gestures')
            self.assertEqual(window.pages['speech_gestures'].get_title(),'Sprache/Gestik')
            self.assertEqual(window.pages['steering'].get_title(),'Bewegung & Zoom')
            self.assertEqual(window.speech_notebook.get_n_pages(),2)
            self.assertEqual(len(window.speech_controls),12)
            from gi.repository import GdkPixbuf
            for gesture in ('target','zoom','dynamic-zoom','mirror'):
                image=window.speech_rows['gesture_control:'+gesture].get_child().get_first_child()
                self.assertIsInstance(image,Gtk.Image)
                pixbuf=GdkPixbuf.Pixbuf.new_from_file(str(ROOT/'assets/gestures'/f'{gesture}.svg'))
                self.assertGreater(pixbuf.get_width(),0)
            wake=window.speech_controls['voice_control:wake'][2]
            track=window.speech_controls['voice_control:track'][2]
            wake.set_active(True)
            track.set_active(True)
            wake.set_active(False)
            self.assertTrue(track.get_active())
            self.assertEqual(window.tracking_values['voice_control:wake'],{'enabled':False})
            self.assertEqual(window.tracking_values['voice_control:track'],{'enabled':True})
            language=window.speech_controls['voice_language'][2]
            language.set_selected(1)
            with patch.object(window,'command') as command:
                window.apply_tool()
                command.assert_called_once_with('voice_language',{'language':'chinese'})
            window.speech_notebook.set_current_page(1)
            gesture=window.speech_controls['gesture_control:zoom'][2]
            gesture.set_active(True)
            with patch.object(window,'command') as command:
                window.apply_tool()
                command.assert_called_once_with('gesture_control',{'gesture':'zoom','enabled':True})
            window.apply_language('en')
            self.assertEqual(window.pages['speech_gestures'].get_title(),'Voice/Gestures')
            self.assertTrue(track.get_active())
            self.assertEqual(language.get_selected(),1)
            self.assertEqual(window.speech_notebook.get_current_page(),1)
            # A second window reloads each individual value from disk.
            with patch.object(CameraWindow,'refresh_devices'),patch.object(CameraWindow,'show_output',return_value=False):
                restored=CameraWindow(application,auto_preview=False)
            try:
                self.assertFalse(restored.speech_controls['voice_control:wake'][2].get_active())
                self.assertTrue(restored.speech_controls['voice_control:track'][2].get_active())
                self.assertTrue(restored.speech_controls['gesture_control:zoom'][2].get_active())
                self.assertEqual(restored.speech_controls['voice_language'][2].get_selected(),1)
            finally:
                restored.bridge.close()
                restored.alive=False
                restored.destroy()
                restored.output_window.destroy()
            import json
            saved=json.loads((config_dir()/'tracking.json').read_text())
            self.assertEqual(saved['voice_control:track'],{'enabled':True})
            self.assertEqual(saved['gesture_control:zoom'],{'enabled':True})
        finally:
            window.bridge.close()
            window.alive=False
            window.destroy()
            window.output_window.destroy()
            application.quit()

if __name__=='__main__':
    try:unittest.main()
    finally:state.cleanup()
