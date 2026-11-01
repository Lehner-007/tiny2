"""One negotiated V4L2 stream feeds preview, photos and recordings with paired audio."""
from pathlib import Path
import os
import json
import subprocess
import threading
import time
from collections import deque
from .virtual_camera import VirtualCamera
import gi
gi.require_version('Gst','1.0')
gi.require_version('GstApp','1.0')
from gi.repository import Gst, GLib
Gst.init(None)


def cameras():
    from .uvc import inventory
    return [(d['path'],d['name']) for d in inventory()]


def _microphone_usb(properties):
    path=properties.get('sysfs.path','')
    if isinstance(path,str) and path.startswith('/devices/'):
        device=Path('/sys'+path).resolve()
    else:
        card=str(properties.get('alsa.card',properties.get('api.alsa.card','')))
        if not card.isdecimal():return None
        device=(Path('/sys/class/sound')/('card'+card)/'device').resolve()
    usb=next((p for p in (device,*device.parents) if (p/'idVendor').is_file()),None)
    return usb.name if usb else None


def microphones():
    """Read physical audio sources and their USB parent without changing defaults."""
    try:
        result=subprocess.run(['pactl','-f','json','list','sources'],capture_output=True,text=True,timeout=3,check=True)
        data=json.loads(result.stdout)
        return [dict(name=x['name'],label=x.get('description',x['name']),muted=bool(x.get('mute')),
                     usb_port=_microphone_usb(x.get('properties',{})))
                for x in data if isinstance(x.get('name'),str) and not x['name'].endswith('.monitor')
                and x.get('monitor_of_sink') in (None,4294967295,'4294967295')]
    except (OSError,ValueError,subprocess.SubprocessError,TypeError,KeyError):return []


def camera_microphone(camera,sources=None):
    """A microphone must share the camera's physical USB parent. No fallback."""
    if not camera or not camera.get('usb_port'):raise RuntimeError('audio_missing')
    matches=[m for m in (microphones() if sources is None else sources) if m.get('usb_port')==camera['usb_port']]
    if not matches:raise RuntimeError('audio_missing')
    source=sorted(matches,key=lambda m:(m['muted'],m['name']))[0]
    if source['muted']:raise RuntimeError('audio_muted')
    return source['name']


RECORDERS={
 'webm':dict(extension='.webm',mux='webmmux',video='vp8enc',audio='opusenc'),
 'mkv':dict(extension='.mkv',mux='matroskamux',video='vp8enc',audio='opusenc'),
 'avi':dict(extension='.avi',mux='avimux',video='jpegenc',audio=None),
 'mp4':dict(extension='.mp4',mux='mp4mux',video='x264enc',audio='voaacenc'),
}


def recording_formats():
    return [key for key,value in RECORDERS.items() if all(Gst.ElementFactory.find(name) for name in
        [value['mux'],value['video'],*([value['audio']] if value['audio'] else []),*(['h264parse','aacparse'] if key=='mp4' else [])])]


AUDIO_RECORDERS={
 'wav':dict(extension='.wav',elements=('wavenc',),chain='audio/x-raw,format=S16LE,rate=48000,channels=2 ! wavenc'),
 'ogg':dict(extension='.ogg',elements=('opusenc','oggmux'),chain='audio/x-raw,rate=48000,channels=2 ! opusenc bitrate=128000 ! oggmux'),
 'flac':dict(extension='.flac',elements=('flacenc',),chain='audio/x-raw,rate=44100,channels=2 ! flacenc'),
 'mp3':dict(extension='.mp3',elements=('lamemp3enc','id3v2mux'),chain='audio/x-raw,rate=44100,channels=2 ! lamemp3enc ! id3v2mux'),
}


def audio_recording_formats():
    required=('pulsesrc','audioconvert','audioresample','fdsink')
    if not all(Gst.ElementFactory.find(name) for name in required):return []
    return [name for name,info in AUDIO_RECORDERS.items()
            if all(Gst.ElementFactory.find(element) for element in info['elements'])]


class AudioRecorder:
    """Independent PulseAudio capture to an explicitly selected file."""
    def __init__(self):
        self.pipeline=None;self.path=None;self.fd=None;self.started=0;self.error=None;self.stopping=False

    def start(self,path,device,format_):
        if self.pipeline:raise RuntimeError('recording_active')
        if format_ not in audio_recording_formats():raise RuntimeError('encoder_missing')
        info=AUDIO_RECORDERS[format_];path=Path(path)
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);pipe=None
        self.path=path
        try:
            description=('pulsesrc name=microphone buffer-time=40000 latency-time=10000 do-timestamp=true ! '
                'queue ! audioconvert ! audioresample ! '+info['chain']+' ! fdsink name=output')
            pipe=Gst.parse_launch(description)
            pipe.get_by_name('microphone').set_property('device',device)
            pipe.get_by_name('output').set_property('fd',fd)
            if pipe.set_state(Gst.State.PLAYING)==Gst.StateChangeReturn.FAILURE:raise RuntimeError('audio_record_failed')
        except Exception:
            if pipe:pipe.set_state(Gst.State.NULL)
            empty=os.fstat(fd).st_size==0
            os.close(fd)
            if empty:path.unlink(missing_ok=True)
            raise
        self.pipeline=pipe;self.path=path;self.fd=fd;self.started=time.monotonic();self.error=None;self.stopping=False

    def check_error(self):
        if not self.pipeline or self.stopping:return self.error
        message=self.pipeline.get_bus().pop_filtered(Gst.MessageType.ERROR)
        if message:
            error,_=message.parse_error();self.error=str(error)
        return self.error

    def stop(self,done):
        pipe=self.pipeline
        if not pipe or self.stopping:return
        self.stopping=True
        def worker():
            error='audio_record_failed'
            try:
                sent=pipe.get_by_name('microphone').send_event(Gst.Event.new_eos())
                message=None if self.error or not sent else pipe.get_bus().timed_pop_filtered(12*Gst.SECOND,Gst.MessageType.EOS|Gst.MessageType.ERROR)
                if message and message.type==Gst.MessageType.EOS and not self.error:error=None
            except Exception as failure:
                self.error=str(failure)
            finally:
                try:pipe.set_state(Gst.State.NULL)
                except Exception as failure:
                    self.error=str(failure);error='audio_record_failed'
                try:
                    if self.fd is not None:os.close(self.fd)
                except OSError as failure:
                    self.error=str(failure);error='audio_record_failed'
                self.fd=None;self.pipeline=None;self.stopping=False
                # Even an unfinalized recording can contain recoverable audio.
                GLib.idle_add(done,error)
        threading.Thread(target=worker,daemon=True).start()


def choose_mode(available,width=1280,fps=30):
    if not available:raise RuntimeError('no_supported_format')
    def score(m):
        rate=m['num']/m['den'] if m['num'] else fps
        return (abs(m['width']-width)+abs(m['height']-round(width*9/16)),abs(rate-fps),0 if m['fourcc']=='MJPG' else 1)
    return dict(min(available,key=score))


def camera_coordinates(arguments,rotation,mirrored,rectangle=False):
    """Undo display mirroring and rotation for native camera pixel commands."""
    args=dict(arguments);width,height=args['frameWidth'],args['frameHeight']
    x,y=args['x'],args['y'];w,h=(args['width'],args['height']) if rectangle else (1,1)
    if mirrored:x=width-x-w
    if rotation==90:x,y,w,h=y,width-x-w,h,w
    elif rotation==180:x,y=width-x-w,height-y-h
    elif rotation==270:x,y,w,h=height-y-h,x,h,w
    elif rotation!=0:raise ValueError('invalid_rotation')
    args.update(x=x,y=y)
    if rotation in (90,270):args.update(frameWidth=height,frameHeight=width)
    if rectangle:args.update(width=w,height=h)
    return args


class Video:
    def __init__(self, on_error):
        self.on_error = on_error
        self.pipeline = None
        self.virtual=VirtualCamera()
        self.latest = None
        self.lock = threading.Lock()
        self.recorder = None
        self.record_path = None
        self.record_frames = 0
        self.record_started = 0
        self.record_stopping = False
        self.frame_time = 0
        self.mirrored = False
        self.record_audio = False
        self.record_fd = None
        self.record_error = None
        self.timestamps=deque(maxlen=180)
        self.frame_count=0
        self.negative=False

    def start(self, device, width=1280, fps=30, *, test=False, mirrored=False, mode=None, rotation=0, grayscale=False, negative=False):
        if self.recorder:
            raise RuntimeError('recording_active')
        self.stop()
        width=int(width);fps=int(fps);height=round(width*9/16)
        if test:
            mode=dict(fourcc='RGB3',width=width,height=height,num=fps,den=1)
            source=f'videotestsrc is-live=true ! video/x-raw,width={width},height={height},framerate={fps}/1'
        else:
            from . import uvc
            selected=next((d for d in uvc.inventory() if d['path']==device),None)
            if selected is None:raise RuntimeError('camera_missing')
            available=uvc.formats(device)
            mode=dict(mode) if mode else choose_mode(available,width,fps)
            if mode not in available:raise RuntimeError('unsupported_format')
            fourcc=mode['fourcc']
            caps='image/jpeg' if fourcc in ('MJPG','JPEG') else 'video/x-h264' if fourcc=='H264' else 'video/x-raw,format='+uvc.RAW_FORMATS[fourcc]
            caps+=f",width={mode['width']},height={mode['height']}"
            if mode['num']:caps+=f",framerate={mode['num']}/{mode['den']}"
            decoder=' ! jpegdec' if fourcc in ('MJPG','JPEG') else ' ! h264parse ! avdec_h264' if fourcc=='H264' else ''
            source='v4l2src name=camera ! '+caps+decoder
        pipe=Gst.parse_launch(source+' ! videoconvert ! videoflip name=rotation ! videoflip name=mirror ! videobalance name=color ! video/x-raw,format=RGB ! appsink name=frames emit-signals=true max-buffers=1 drop=true sync=false')
        if not test:
            pipe.get_by_name('camera').set_property('device',device)
        self.mode=mode
        self.rate_num=mode['num'] or fps
        self.rate_den=mode['den']
        self.fps=self.rate_num/self.rate_den
        self.timestamps.clear();self.frame_count=0
        pipe.get_by_name('frames').connect('new-sample',self._sample)
        bus = pipe.get_bus()
        bus.add_signal_watch()
        bus.connect('message::error',self._error)
        self.pipeline = pipe
        self.set_mirror(mirrored)
        self.set_effects(rotation,grayscale,negative)
        self.started = time.monotonic()
        self.frame_time = 0
        if pipe.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            self.stop()
            raise RuntimeError('video_failed')

    def _sample(self, sink):
        sample = sink.emit('pull-sample')
        if sample is None:
            return Gst.FlowReturn.ERROR
        buf = sample.get_buffer()
        caps = sample.get_caps().get_structure(0)
        width, height = caps.get_value('width'), caps.get_value('height')
        ok, mapped = buf.map(Gst.MapFlags.READ)
        if not ok:
            return Gst.FlowReturn.ERROR
        data = bytes(mapped.data)
        if self.negative:data=data.translate(bytes(range(255,-1,-1)))
        buf.unmap(mapped)
        with self.lock:
            self.latest = (data,width,height,len(data)//height)
            self.frame_time = time.monotonic()
            self.timestamps.append(self.frame_time);self.frame_count+=1
            ok,num,den=caps.get_fraction('framerate')
            if ok and num>0:self.rate_num,self.rate_den=num,den;self.fps=num/den
            self.virtual.push(self.latest)
            if self.recorder and not self.record_stopping:
                out = Gst.Buffer.new_wrapped(data)
                out.duration = int(Gst.SECOND*self.rate_den/self.rate_num)
                self.record_frames += 1
                self.recorder.get_by_name('input').emit('push-buffer',out)
        return Gst.FlowReturn.OK

    def _error(self, _bus, message):
        if not self.pipeline or _bus != self.pipeline.get_bus():return
        error, debug = message.parse_error()
        self.on_error(str(error))

    def frame(self):
        with self.lock:
            if self.latest and self.latest[1:3]!=self.expected_size():return None
            return self.latest

    def expected_size(self):
        width,height=self.mode['width'],self.mode['height']
        return (height,width) if self.rotation in (90,270) else (width,height)

    def set_mirror(self, enabled):
        if self.virtual.pipeline:raise RuntimeError('virtual_active')
        if self.recorder:
            raise RuntimeError('recording_active')
        self.mirrored = bool(enabled)
        if self.pipeline:
            self.pipeline.get_by_name('mirror').set_property('video-direction',4 if enabled else 0)

    def set_effects(self,rotation=0,grayscale=False,negative=False):
        if self.virtual.pipeline:raise RuntimeError('virtual_active')
        if self.recorder:raise RuntimeError('recording_active')
        if rotation not in (0,90,180,270):raise ValueError('invalid_rotation')
        self.rotation=rotation
        self.negative=bool(negative)
        if self.pipeline:
            self.pipeline.get_by_name('rotation').set_property('video-direction',{0:0,90:1,180:2,270:3}[rotation])
            self.pipeline.get_by_name('color').set_property('saturation',0.0 if grayscale else 1.0)

    def measured_fps(self):
        with self.lock:
            times=list(self.timestamps)
        times=[t for t in times if time.monotonic()-t<3]
        return (len(times)-1)/(times[-1]-times[0]) if len(times)>1 else 0.0

    def record(self, path, *, audio=False, audio_device=None, test_audio=False, container='webm', quality=80, bitrate=4000000):
        with self.lock:
            if self.recorder or self.latest is None:
                raise RuntimeError('preview_required')
            data,w,h,stride = self.latest
            if (w,h)!=self.expected_size():raise RuntimeError('preview_required')
            if audio and not test_audio:
                if not audio_device:
                    raise RuntimeError('audio_missing')
                found = next((x for x in microphones() if x['name']==audio_device),None)
                if found is None:
                    raise RuntimeError('audio_missing')
                if found['muted']:
                    raise RuntimeError('audio_muted')
            if container not in recording_formats():raise RuntimeError('encoder_missing')
            if type(quality) is not int or not 1<=quality<=100 or type(bitrate) is not int or not 100000<=bitrate<=100000000:raise ValueError('invalid_quality')
            path = Path(path)
            fd = os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            pipe = None
            try:
                preset=RECORDERS[container]
                mux=preset['mux']
                video=(f'vp8enc deadline=1 cpu-used=8 target-bitrate={bitrate} end-usage=cq cq-level={round((100-quality)*63/100)}' if preset['video']=='vp8enc' else
                       f'jpegenc quality={quality}' if container=='avi' else
                       f'x264enc bitrate={bitrate//1000} speed-preset=ultrafast tune=zerolatency ! h264parse')
                description=(mux+' name=mux ! fdsink name=output '
                    'appsrc name=input is-live=true do-timestamp=true min-latency=0 format=time max-buffers=4 max-bytes=0 leaky-type=downstream ! queue ! '
                    f'videoconvert ! videorate ! video/x-raw,framerate={self.rate_num}/{self.rate_den} ! '+video+' ! queue ! mux.video_0 ')
                if audio:
                    source='audiotestsrc is-live=true wave=sine' if test_audio else 'pulsesrc buffer-time=40000 latency-time=10000'
                    encoder='opusenc bitrate=128000 ! ' if container in ('webm','mkv') else 'voaacenc bitrate=128000 ! aacparse ! ' if container=='mp4' else ''
                    audio_caps='audio/x-raw,rate=48000,channels=2'+(',format=S16LE,layout=interleaved' if container=='avi' else '')
                    description+=source+' name=microphone do-timestamp=true ! audioconvert ! audioresample ! '+audio_caps+' ! '+encoder+'queue ! mux.audio_0'
                pipe = Gst.parse_launch(description)
                if audio and not test_audio:
                    pipe.get_by_name('microphone').set_property('device',audio_device)
                pipe.get_by_name('input').set_property('caps',Gst.Caps.from_string(
                    f'video/x-raw,format=RGB,width={w},height={h},framerate={self.rate_num}/{self.rate_den}'))
                pipe.get_by_name('output').set_property('fd',fd)
                if pipe.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
                    raise RuntimeError('record_failed')
            except Exception:
                if pipe:pipe.set_state(Gst.State.NULL)
                os.close(fd)
                path.unlink(missing_ok=True)
                raise
            self.recorder = pipe
            self.record_fd = fd
            self.record_path = path
            self.record_audio = bool(audio)
            self.record_frames = 0
            self.record_error = None
            self.record_started = time.monotonic()

    def check_recording(self):
        """Nonblocking error check; finish_record owns the bus once stopping."""
        if not self.recorder or self.record_stopping:
            return None
        message = self.recorder.get_bus().pop_filtered(Gst.MessageType.ERROR)
        if message:
            error,_ = message.parse_error()
            self.record_error = str(error)
        return self.record_error

    def finish_record(self, done):
        with self.lock:
            pipe = self.recorder
            if not pipe or self.record_stopping:
                return
            self.record_stopping = True
            pipe.get_by_name('input').emit('end-of-stream')
            microphone = pipe.get_by_name('microphone')
            if microphone:
                microphone.send_event(Gst.Event.new_eos())
        def worker():
            message = None if self.record_error else pipe.get_bus().timed_pop_filtered(
                8*Gst.SECOND,Gst.MessageType.EOS|Gst.MessageType.ERROR)
            error = None if message and message.type == Gst.MessageType.EOS else 'record_failed'
            if self.record_error:error='record_failed'
            pipe.set_state(Gst.State.NULL)
            with self.lock:
                if self.record_fd is not None:os.close(self.record_fd)
                self.record_fd = None
                self.recorder = None
                self.record_stopping = False
            GLib.idle_add(done,error)
        threading.Thread(target=worker,daemon=True).start()

    def stop(self):
        if self.recorder:
            raise RuntimeError('recording_active')
        self.virtual.stop()
        pipe, self.pipeline = self.pipeline, None
        if pipe:
            pipe.get_bus().remove_signal_watch()
            pipe.set_state(Gst.State.NULL)
        with self.lock:
            self.latest = None
