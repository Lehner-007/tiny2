"""Versioned camera-specific data profiles; no executable configuration."""
import hashlib,json
from pathlib import Path
from . import uvc


def camera_key(camera):
    identity=[camera['kind'],camera.get('control_serial') or camera.get('serial') or camera.get('usb_port') or camera['path'],camera['name']]
    return hashlib.sha256(json.dumps(identity).encode()).hexdigest()


class Profiles:
    def __init__(self,folder):self.path=Path(folder)/'camera_profiles.json'

    def read(self):
        if not self.path.exists():return dict(version=1,cameras={})
        data=json.loads(self.path.read_text('utf-8'))
        if not isinstance(data,dict) or data.get('version')!=1 or not isinstance(data.get('cameras'),dict):raise ValueError('invalid_profile_file')
        return data

    def names(self,camera):return sorted(self.read()['cameras'].get(camera_key(camera),{}))

    def save(self,camera,name,mode,options):
        name=name.strip()
        if not name or len(name)>80 or any(ord(c)<32 for c in name):raise ValueError('invalid_profile_name')
        controls=uvc.read_controls(camera['path'])
        values={str(c['id']):c['value'] for c in controls if not c['flags']&(1|2|4) and uvc.reversible(c) and uvc.safe_image_control(camera,c)}
        data=self.read();profiles=data['cameras'].setdefault(camera_key(camera),{})
        profiles[name]=dict(mode=mode,options=options,controls=values)
        from josef_basis.model import atomic_json
        atomic_json(self.path,data)

    def get(self,camera,name):
        profile=self.read()['cameras'][camera_key(camera)][name]
        if not isinstance(profile,dict) or not isinstance(profile.get('controls'),dict) or not isinstance(profile.get('options'),dict):raise ValueError('invalid_profile')
        return profile

    def delete(self,camera,name):
        data=self.read();del data['cameras'][camera_key(camera)][name]
        from josef_basis.model import atomic_json
        atomic_json(self.path,data)
