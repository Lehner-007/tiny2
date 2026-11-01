"""Tracking form regression checks with real GTK widgets and isolated state."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'desktop/vendor')]
from josef_basis import Anwendung
state=tempfile.TemporaryDirectory(dir=ROOT/'work')
app=Anwendung(ROOT/'projekt.json',entwicklung=True,zustandsordner=state.name)
from desktop.gui import CameraWindow
from gi.repository import Gtk
from josef_basis.model import config_dir

class TrackingTests(unittest.TestCase):
    def test_rebuild_and_restart(self):
        Gtk.init()
        choice=Gtk.ListBox()
        rows=[]
        for _ in range(3):
            row=Gtk.ListBoxRow();rows.append(row);choice.append(row)
        choice.select_row(choice.get_row_at_index(0))
        section=dict(choice=choice,fields=Gtk.Box(orientation=Gtk.Orientation.VERTICAL),widgets={},hint=Gtk.Label())
        schemas={
            'ai_track':{'enabled':{'type':'boolean'},'mode':{'enum':['normal','upper-body'],'default':'normal'}},
            'ai_track_speed':{'speed':{'enum':['standard','sport'],'default':'standard'}},
            'focus_face':{'enabled':{'type':'boolean'}}}
        section['tool_rows']=rows
        owner=SimpleNamespace(selection={'tracking':section},tr=lambda key:key,tracking_values={},
            resetting_settings=False,
            catalog={'obsbot_'+key:{'inputSchema':{'properties':value}} for key,value in schemas.items()})
        owner.tool_for_row=lambda group,row:CameraWindow.tool_for_row(owner,group,row)
        CameraWindow.build_fields(owner,'tracking')
        section['widgets']['enabled'][0].set_active(True)
        section['widgets']['mode'][0].set_selected(1)
        choice.select_row(choice.get_row_at_index(1))
        CameraWindow.build_fields(owner,'tracking')
        section['widgets']['speed'][0].set_selected(1)
        # Reload the on-disk values just as a fresh process does.
        owner.tracking_values=json.loads((config_dir()/'tracking.json').read_text())
        choice.select_row(choice.get_row_at_index(0))
        CameraWindow.build_fields(owner,'tracking')
        self.assertTrue(section['widgets']['enabled'][1]())
        self.assertEqual(section['widgets']['mode'][1](),'upper-body')
        choice.select_row(choice.get_row_at_index(1))
        CameraWindow.build_fields(owner,'tracking')
        self.assertEqual(section['widgets']['speed'][1](),'sport')
        owner.tracking_values={'ai_track':{'enabled':'bad','mode':'invalid'}}
        choice.select_row(choice.get_row_at_index(0))
        CameraWindow.build_fields(owner,'tracking')
        self.assertFalse(section['widgets']['enabled'][1]())
        self.assertEqual(section['widgets']['mode'][1](),'normal')

if __name__=='__main__':
    try:unittest.main()
    finally:state.cleanup()
