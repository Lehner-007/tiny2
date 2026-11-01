"""Linux V4L2 capability and control adapter for capture cameras. No shell or vendor commands."""
import errno
import fcntl
import os
import struct
from pathlib import Path

# Linux videodev2.h ABI: queryctrl=68 bytes, querymenu=44, control=8.
QUERYCTRL=0xC0445624
QUERYMENU=0xC02C5625
G_CTRL=0xC008561B
S_CTRL=0xC008561C
QUERY_FORMAT='=II32siiiiIII'
CONTROLS={
 0x00980900:'brightness',0x00980901:'contrast',0x00980902:'saturation',
 0x00980903:'hue',0x0098090C:'white_balance_auto',0x00980913:'gain',
 0x00980918:'power_line',0x0098091A:'temperature',0x0098091B:'sharpness',
 0x0098091C:'backlight',0x009A0901:'exposure_auto',0x009A0902:'exposure',
 0x009A0903:'exposure_dynamic',0x009A090A:'focus',0x009A090C:'focus_auto',
 0x009A090D:'zoom',0x00980910:'gamma',0x00980914:'hflip',0x00980915:'vflip',
 0x009A0904:'pan_relative',0x009A0905:'tilt_relative',0x009A090B:'focus_relative',
 0x009A090E:'zoom_relative',0x009A090F:'zoom_continuous',0x009A0911:'iris',0x009A0912:'iris_relative',
 0x009A0920:'pan_speed',0x009A0921:'tilt_speed',
 0x00980922:'rotate',0x009A0908:'pan',0x009A0909:'tilt',0x009A0910:'privacy',
}


VIRTUAL_DRIVERS={'akvcam','v4l2 loopback','v4l2loopback'}
TINY_EXPOSURE_CONTROLS={'exposure_auto','exposure','exposure_dynamic'}
MOTION_CONTROLS={'pan','tilt','pan_speed','tilt_speed','pan_relative','tilt_relative'}
TRANSIENT_CONTROLS={'pan_speed','tilt_speed','pan_relative','tilt_relative','zoom_relative','zoom_continuous','focus_relative','iris_relative'}


def safe_image_control(camera,control):
    return control['key'] not in TRANSIENT_CONTROLS and not (camera['kind']=='tiny2' and control['key'] in MOTION_CONTROLS|TINY_EXPOSURE_CONTROLS)


def query_capabilities(path,*,output=False):
    fd=os.open(path,os.O_RDONLY|os.O_NONBLOCK)
    try:
        raw=bytearray(104);fcntl.ioctl(fd,0x80685600,raw,True)
        driver,card,bus,version,caps,device_caps,*_=struct.unpack('=16s32s32sIIIIII',raw)
        flags=device_caps if caps&0x80000000 else caps
        if not flags&((2|0x2000) if output else (1|0x1000)):return None
        return dict(driver=driver.split(b'\0')[0].decode('utf-8','replace'),name=card.split(b'\0')[0].decode('utf-8','replace'),
                    buffer_type=(2 if flags&2 else 10) if output else (1 if flags&1 else 9),capabilities=flags)
    finally:os.close(fd)


def inventory(sys_root=Path('/sys/class/video4linux'),dev_root=Path('/dev'),*,output=False):
    result=[]
    for node in sorted(Path(sys_root).glob('video*')):
        try:
            path=str(Path(dev_root)/node.name)
            capabilities=query_capabilities(path,output=True) if output else query_capabilities(path)
            if not capabilities:continue
            driver=capabilities.get('driver','')
            if output and driver not in VIRTUAL_DRIVERS:continue
            label=(node/'name').read_text().strip()
            real=node.resolve()
            usb=next((p for p in real.parents if (p/'idVendor').is_file()),None)
            vid=(usb/'idVendor').read_text().strip().lower() if usb else ''
            pid=(usb/'idProduct').read_text().strip().lower() if usb else ''
            product=(usb/'product').read_text().strip() if usb and (usb/'product').is_file() else label
            kind='tiny2' if (vid,pid)==('3564','fef8') else (
                 'c922' if vid=='046d' and 'c922' in (label+' '+product).lower() else
                 'virtual' if driver in VIRTUAL_DRIVERS else 'uvc')
            serial=(usb/'serial').read_text().strip() if usb and (usb/'serial').is_file() else ''
            result.append(dict(path=path,name=label,kind=kind,driver=driver,serial=serial,
                               usb_port=usb.name if usb else None,buffer_type=capabilities['buffer_type']))
        except OSError:continue
    return result


def _validated(path,*,output=False):
    devices=inventory(output=True) if output else inventory()
    if path not in {x['path'] for x in devices}:raise ValueError('unsupported_camera')
    return path


RAW_FORMATS={'YUYV':'YUY2','UYVY':'UYVY','NV12':'NV12','YU12':'I420','RGB3':'RGB','BGR3':'BGR','GREY':'GRAY8'}


def _rates(fd,pixel,width,height):
    result=[]
    for index in range(128):
        raw=bytearray(52);struct.pack_into('=IIII',raw,0,index,pixel,width,height)
        try:fcntl.ioctl(fd,0xC034564B,raw,True)
        except OSError as error:
            if error.errno in (errno.EINVAL,errno.ENOTTY):break
            raise
        kind=struct.unpack_from('=I',raw,16)[0]
        if kind==1:
            numerator,denominator=struct.unpack_from('=II',raw,20)
            if numerator and denominator:result.append((denominator,numerator))
        else:
            minimum_n,minimum_d,maximum_n,maximum_d,step_n,step_d=struct.unpack_from('=6I',raw,20)
            if minimum_n and minimum_d and maximum_n and maximum_d:
                result.extend([(minimum_d,minimum_n),(maximum_d,maximum_n)])
            break
    return list(dict.fromkeys(result)) or [(0,1)]


def formats(path,*,output=False):
    fd=os.open(_validated(path,output=True) if output else _validated(path),os.O_RDONLY|os.O_NONBLOCK)
    try:
        caps=query_capabilities(path,output=True) if output else query_capabilities(path)
        result=[]
        for index in range(128):
            raw=bytearray(64);struct.pack_into('=II',raw,0,index,caps['buffer_type'])
            try:fcntl.ioctl(fd,0xC0405602,raw,True)
            except OSError as error:
                if error.errno==errno.EINVAL:break
                raise
            pixel=struct.unpack_from('=I',raw,44)[0]
            fourcc=struct.pack('=I',pixel).decode('ascii','replace')
            if fourcc not in RAW_FORMATS and fourcc not in ('MJPG','JPEG','H264'):continue
            sizes=[]
            for size_index in range(256):
                raw=bytearray(44);struct.pack_into('=II',raw,0,size_index,pixel)
                try:fcntl.ioctl(fd,0xC02C564A,raw,True)
                except OSError as error:
                    if error.errno in (errno.EINVAL,errno.ENOTTY):break
                    raise
                kind=struct.unpack_from('=I',raw,8)[0]
                if kind==1:sizes.append(struct.unpack_from('=II',raw,12))
                else:
                    min_w,max_w,step_w,min_h,max_h,step_h=struct.unpack_from('=6I',raw,12)
                    candidates=[(min_w,min_h),(max_w,max_h),(640,480),(640,360),(1280,720),(1920,1080),(3840,2160)]
                    sizes.extend((w,h) for w,h in candidates if min_w<=w<=max_w and min_h<=h<=max_h and (w-min_w)%max(1,step_w)==0 and (h-min_h)%max(1,step_h)==0)
                    break
            for width,height in dict.fromkeys(sizes):
                if width<=0 or height<=0:continue
                for num,den in _rates(fd,pixel,width,height):
                    result.append(dict(fourcc=fourcc,width=width,height=height,num=num,den=den))
        return result
    finally:os.close(fd)


def _query(fd,identifier):
    query=bytearray(struct.pack(QUERY_FORMAT,identifier,0,b'',0,0,0,0,0,0,0))
    fcntl.ioctl(fd,QUERYCTRL,query,True)
    ident,kind,name,low,high,step,default,flags,_,_=struct.unpack(QUERY_FORMAT,query)
    if flags&(1|64) or kind not in (1,2,3,9):return None
    raw=bytearray(struct.pack('=Ii',identifier,0))
    fcntl.ioctl(fd,G_CTRL,raw,True)
    current=struct.unpack('=Ii',raw)[1]
    choices=[]
    if kind in (3,9):
        for index in range(low,min(high,256)+1):
            menu=bytearray(struct.pack('=II32sI',identifier,index,b'',0))
            try:
                fcntl.ioctl(fd,QUERYMENU,menu,True)
                choices.append((index,str(struct.unpack_from('=q',menu,8)[0]) if kind==9 else bytes(menu[8:40]).split(b'\0')[0].decode('utf-8','replace')))
            except OSError as exc:
                if exc.errno!=errno.EINVAL:raise
    return dict(id=ident,key=CONTROLS.get(ident,'control_'+str(ident)),name=name.split(b'\0')[0].decode('utf-8','replace'),kind=kind,minimum=low,maximum=high,
                step=max(1,step),default=default,value=current,flags=flags,choices=choices)


def read_controls(path):
    fd=os.open(_validated(path),os.O_RDWR|os.O_NONBLOCK)
    try:
        controls=[]
        identifiers=[];identifier=0
        for _ in range(512):
            raw=bytearray(struct.pack(QUERY_FORMAT,identifier|0x80000000,0,b'',0,0,0,0,0,0,0))
            try:fcntl.ioctl(fd,QUERYCTRL,raw,True)
            except OSError as error:
                if error.errno in (errno.EINVAL,errno.ENOTTY):break
                raise
            next_id=struct.unpack_from('=I',raw,0)[0]
            if next_id<=identifier:break
            identifiers.append(next_id);identifier=next_id
        for identifier in identifiers or CONTROLS:
            try:
                value=_query(fd,identifier)
                if value:controls.append(value)
            except OSError as exc:
                if exc.errno not in (errno.EINVAL,errno.ENOTTY,errno.EACCES,errno.EPERM):raise
        return controls
    finally:os.close(fd)


def valid_value(control,value):
    if type(value) is not int or not control['minimum']<=value<=control['maximum']:return False
    if control['kind'] in (3,9):return value in [x[0] for x in control['choices']]
    return control['step']>0 and (value-control['minimum'])%control['step']==0


def reversible(control):
    return valid_value(control,control.get('value')) and valid_value(control,control.get('default',control.get('value')))


def write_control(path,identifier,value):
    if type(identifier) is not int or not 0x00980000<=identifier<0x80000000 or type(value) is not int:
        raise ValueError('invalid_control')
    fd=os.open(_validated(path),os.O_RDWR|os.O_NONBLOCK)
    try:
        control=_query(fd,identifier)
        if not control or control['flags']&(1|2|4|16):raise ValueError('inactive_control')
        if not reversible(control):raise ValueError('unreliable_control')
        if control.get('key') in TINY_EXPOSURE_CONTROLS and any(d['path']==path and d['kind']=='tiny2' for d in inventory()):
            raise ValueError('unreliable_control')
        if not control['minimum']<=value<=control['maximum']:
            raise ValueError('invalid_control_value')
        if control['kind'] in (3,9):
            if value not in [x[0] for x in control['choices']]:raise ValueError('invalid_control_value')
        elif (value-control['minimum'])%control['step']:
            raise ValueError('invalid_control_step')
        raw=bytearray(struct.pack('=Ii',identifier,value))
        fcntl.ioctl(fd,S_CTRL,raw,True)
        fcntl.ioctl(fd,G_CTRL,raw,True)
        return struct.unpack('=Ii',raw)[1]
    finally:os.close(fd)


def apply_controls(path,values):
    """Validate the complete set before writing. Restore automatics last."""
    current={c['id']:c for c in read_controls(path)}
    selected=[]
    for identifier,value in values.items():
        identifier=int(identifier)
        if identifier not in current:raise ValueError('profile_controls_changed')
        c=current[identifier]
        if type(value) is not int or not c['minimum']<=value<=c['maximum']:raise ValueError('invalid_control_value')
        if c['flags']&(1|2|4):continue
        if not reversible(c):raise ValueError('unreliable_control')
        if c['kind'] in (3,9) and value not in [x[0] for x in c['choices']]:raise ValueError('invalid_control_value')
        if c['kind'] not in (3,9) and (value-c['minimum'])%c['step']:raise ValueError('invalid_control_step')
        selected.append((c,value))
    automatic={'focus_auto','white_balance_auto','exposure_auto'}
    # Restore automatic modes even if a dependent driver write fails.
    changed=[];completed=False
    try:
        for c,value in selected:
            if c['key'] in automatic:
                manual=1 if c['key']=='exposure_auto' else 0
                if c['kind']!=3 or manual in [x[0] for x in c['choices']]:
                    write_control(path,c['id'],manual);changed.append((c,value))
        for c,value in selected:
            if c['key'] in automatic:continue
            fresh=next(x for x in read_controls(path) if x['id']==c['id'])
            if fresh['flags']&16:continue
            write_control(path,c['id'],value)
        completed=True
    finally:
        restore_errors=[]
        for c,value in changed:
            try:write_control(path,c['id'],value if completed else c['value'])
            except (OSError,ValueError) as error:restore_errors.append(error)
        if restore_errors:raise RuntimeError('control_restore_failed') from restore_errors[0]
    return read_controls(path)
