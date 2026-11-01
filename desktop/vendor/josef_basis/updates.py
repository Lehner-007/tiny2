"""Projektgebundene Versionsdaten und geprüfter DEB-Download auf Benutzeraktion."""
import hashlib
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit
import requests
from gi.repository import GLib
from .model import PROJECT, VERSION, PROGRAM_ID
from .languages import github_json, validate_version

MAX_DEB=300*1024*1024
REDIRECT_HOSTS={'release-assets.githubusercontent.com','objects.githubusercontent.com'}


def release_info(source):
    data=github_json(source)
    version=validate_version(data)
    result={'version':version,'deb':None}
    deb=data.get('deb')
    if deb is None:return result
    if not isinstance(deb,dict):raise ValueError('Invalid DEB metadata')
    parts=urlsplit(source).path.strip('/').split('/')
    if len(parts)<2:raise ValueError('Missing repository')
    url=deb.get('url','');parsed=urlsplit(url)
    filename=deb.get('filename','')
    prefix='/'+parts[0]+'/'+parts[1]+'/releases/download/v'+version+'/'
    if (parsed.scheme!='https' or parsed.hostname!='github.com' or parsed.username or parsed.password
        or parsed.query or parsed.fragment or parsed.path!=prefix+filename
        or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._+-]*\.deb',filename)
        or not re.fullmatch(r'[a-fA-F0-9]{64}',deb.get('sha256',''))):
        raise ValueError('Invalid project download')
    result['deb']=dict(url=url,filename=filename,sha256=deb['sha256'].lower())
    return result


def download_directory():
    configured=GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOWNLOAD)
    return Path(configured) if configured else Path.home()/'Downloads'


def check_package(path,info,context):
    context.check_cancel()
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        while chunk:=stream.read(1024*1024):context.check_cancel();digest.update(chunk)
    if digest.hexdigest()!=info['deb']['sha256']:raise ValueError('Checksum mismatch')
    context.check_cancel()
    result=subprocess.run(['dpkg-deb','--field',str(path),'Package','Version','Architecture'],capture_output=True,text=True,timeout=15,check=True)
    fields=dict(line.split(': ',1) for line in result.stdout.splitlines() if ': ' in line)
    architecture=subprocess.run(['dpkg','--print-architecture'],capture_output=True,text=True,timeout=5,check=True).stdout.strip()
    if (fields.get('Package')!=PROJECT['deb']['package'] or fields.get('Version')!=info['version']
        or fields.get('Architecture') not in ('all',architecture)):raise ValueError('Wrong package, version or architecture')


def download_update(info,context,directory=None):
    if not info.get('deb') or tuple(map(int,info['version'].split('.')))<=tuple(map(int,VERSION.split('.'))):raise ValueError('No newer download')
    folder=Path(directory) if directory is not None else download_directory()
    folder.mkdir(parents=True,exist_ok=True)
    target=folder/info['deb']['filename']
    if target.exists() or target.is_symlink():
        if target.is_symlink() or not target.is_file():raise FileExistsError('Existing download')
        check_package(target,info,context);return target
    descriptor,name=tempfile.mkstemp(prefix='.'+PROGRAM_ID+'-update-',suffix='.part',dir=folder)
    temporary=Path(name)
    try:
        with os.fdopen(descriptor,'wb') as output,requests.Session() as session:
            session.trust_env=False
            url=info['deb']['url'];started=time.monotonic()
            for redirect in range(6):
                context.check_cancel()
                with session.get(url,stream=True,timeout=(10,15),allow_redirects=False,headers={'User-Agent':PROGRAM_ID+'/'+VERSION}) as response:
                    response.raise_for_status()
                    if response.is_redirect:
                        location=response.headers.get('Location','');parsed=urlsplit(location)
                        if parsed.scheme!='https' or parsed.hostname not in REDIRECT_HOSTS or parsed.username or parsed.password:raise ValueError('Unsafe download redirect')
                        url=location;continue
                    total=response.headers.get('Content-Length','0')
                    total=int(total) if total.isdecimal() else 0
                    if total>MAX_DEB:raise ValueError('Download too large')
                    received=0
                    for chunk in response.iter_content(65536):
                        context.check_cancel()
                        if time.monotonic()-started>300:raise TimeoutError('Download timeout')
                        received+=len(chunk)
                        if received>MAX_DEB:raise ValueError('Download too large')
                        output.write(chunk)
                        if total and received<=total:context.progress(received,total)
                    output.flush();os.fsync(output.fileno());break
            else:raise ValueError('Too many redirects')
        check_package(temporary,info,context)
        context.check_cancel()
        os.link(temporary,target)  # Exclusive publication: never overwrite an existing file.
        return target
    finally:temporary.unlink(missing_ok=True)
