"""Application-side V4L2 virtual-camera output; no driver installation or source copying."""
import threading,time
import gi
gi.require_version('Gst','1.0')
from gi.repository import Gst
from . import uvc


class VirtualCamera:
    def __init__(self):
        self.pipeline=None;self.lock=threading.Lock();self.started=0
        self.frames=0;self.ready=False

    def start(self,path,mode,frame,rate,*,test=False):
        if self.pipeline:raise RuntimeError('virtual_active')
        if frame is None:raise RuntimeError('preview_required')
        if not test:
            devices=uvc.inventory(output=True)
            if path not in [d['path'] for d in devices]:raise RuntimeError('virtual_missing')
            if mode not in uvc.formats(path,output=True):raise RuntimeError('unsupported_format')
        if mode.get('fourcc') not in uvc.RAW_FORMATS or mode.get('num',0)<=0 or mode.get('den',0)<=0:raise ValueError('unsupported_format')
        _,width,height,_=frame
        num,den=rate
        if num<=0 or den<=0:raise ValueError('unsupported_format')
        caps=f"video/x-raw,format={uvc.RAW_FORMATS[mode['fourcc']]},width={mode['width']},height={mode['height']},framerate={mode['num']}/{mode['den']}"
        # Bounded queues keep a slow receiver from blocking the physical camera.
        sink='fakesink name=output enable-last-sample=true sync=false' if test else 'v4l2sink name=output sync=false'
        pipe=Gst.parse_launch('appsrc name=input is-live=true do-timestamp=true format=time max-buffers=2 max-bytes=0 leaky-type=downstream ! queue max-size-buffers=2 max-size-bytes=0 max-size-time=0 leaky=downstream ! videoconvert ! videoscale add-borders=true ! videorate ! '+caps+' ! '+sink)
        pipe.get_by_name('input').set_property('caps',Gst.Caps.from_string(f'video/x-raw,format=RGB,width={width},height={height},framerate={num}/{den}'))
        if not test:pipe.get_by_name('output').set_property('device',path)
        try:
            if pipe.set_state(Gst.State.PLAYING)==Gst.StateChangeReturn.FAILURE:raise RuntimeError('virtual_failed')
        except Exception:
            pipe.set_state(Gst.State.NULL);raise
        with self.lock:
            self.pipeline=pipe;self.size=(width,height);self.started=time.monotonic();self.frames=0;self.ready=False

    def push(self,frame):
        with self.lock:pipe=self.pipeline
        if not pipe or frame[1:3]!=self.size:return
        data=frame[0]
        result=pipe.get_by_name('input').emit('push-buffer',Gst.Buffer.new_wrapped(data))
        if result==Gst.FlowReturn.OK:self.frames+=1

    def check(self):
        with self.lock:pipe=self.pipeline
        if not pipe:return None
        message=pipe.get_bus().pop_filtered(Gst.MessageType.ERROR)
        if message:
            error,_=message.parse_error();return str(error)
        stats=pipe.get_by_name('output').get_property('stats')
        self.ready=bool(stats and stats.get_value('rendered')>0)
        if not self.ready and time.monotonic()-self.started>8:return 'virtual_no_frames'
        return None

    def stop(self):
        with self.lock:pipe,self.pipeline=self.pipeline,None
        if pipe:pipe.set_state(Gst.State.NULL)
        self.ready=False


def configuration_template():
    """An optional example file. Exporting does not apply system configuration."""
    return '''# Tiny: optional akvcam configuration example.
# Review and apply separately after installing a compatible akvcam driver.
# Device numbers are deliberately not fixed.
[Cameras]
cameras/size = 2
cameras/1/type = output
cameras/1/mode = mmap, rw
cameras/1/description = Tiny Bildausgabe
cameras/1/formats = 1, 2
cameras/2/type = capture
cameras/2/mode = mmap, rw
cameras/2/description = Tiny Virtuelle Kamera
cameras/2/formats = 1, 2

[Formats]
formats/size = 2
formats/1/format = YUY2
formats/1/width = 640
formats/1/height = 480
formats/1/fps = 30
formats/2/format = YUY2, RGB24
formats/2/width = 1280
formats/2/height = 720
formats/2/fps = 30

[Connections]
connections/size = 1
connections/1/connection = 1:2
'''
