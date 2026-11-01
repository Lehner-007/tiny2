"""Import a single data-only JSON language pack, locally or from a GitHub URL."""
import json
import re
import time
from pathlib import Path
from urllib.parse import urlsplit
import requests
from bs4 import BeautifulSoup
from .model import ROOT,VERSION,PROGRAM_ID,config_dir,atomic_json
from .i18n import fields
from .project import read_strings

MAX_PACK=2_000_000

class ProgramIdentityError(ValueError):
    """A downloaded/imported document does not identify this application."""


def validate_program(data):
    if not isinstance(data,dict) or data.get('program_id') != PROGRAM_ID:
        raise ProgramIdentityError(f'Missing or incorrect program_id; expected {PROGRAM_ID}')


def validate_version(data):
    validate_program(data)
    version=data.get('version')
    if not isinstance(version,str) or not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)',version):
        raise ValueError('JSON requires a MAJOR.MINOR.PATCH version')
    return version


def download_version(url):
    return validate_version(github_json(url))


def validate_pack(data):
    validate_program(data)
    code=data.get('code','')
    if not re.fullmatch(r'[a-z]{2,3}(?:[-_][A-Za-z0-9]{2,8})?',code):raise ValueError('Invalid language code')
    if code in ('de','en'):raise ValueError('DE/EN are maintained with the application')
    strings=data.get('strings')
    if not isinstance(strings,dict) or not strings:raise ValueError('Missing translations')
    en=read_strings(ROOT, 'en')
    if set(strings) != set(en):raise ValueError('Incomplete translations')
    for k,v in strings.items():
        if k not in en or not isinstance(v,str) or fields(v)!=fields(en[k]):raise ValueError('Invalid key or placeholder: '+str(k))
    help_=data.get('help_html')
    if not isinstance(help_,str) or not help_.strip():raise ValueError('Missing HTML help')
    soup=BeautifulSoup(help_,'html.parser')
    allowed={'html','head','title','body','main','section','h1','h2','h3','p','ul','ol','li','pre','code','table','tr','th','td','br','hr','strong','em','span','a','meta'}
    for tag in list(soup.find_all(True)):
        if tag.name is None:continue
        if tag.name in ('script','style','iframe','object','embed','form','input','link','img','svg','math'):
            tag.decompose();continue
        if tag.name not in allowed:tag.unwrap();continue
        attrs={}
        if tag.name=='html':
            attrs['lang']=code
            if code.split('-')[0].split('_')[0] in ('ar','he','fa','ur'):attrs['dir']='rtl'
        if tag.name=='meta':attrs={'charset':'utf-8'}
        if tag.name=='a' and str(tag.get('href','')).startswith('#'):attrs['href']=tag['href']
        tag.attrs=attrs
    name = data.get('name')
    if not isinstance(name,str) or not name.strip() or len(name)>100:raise ValueError('Missing language name')
    return code,strings,'<!doctype html>\n'+str(soup)

def install_pack(data):
    code,strings,help_=validate_pack(data)
    folder=config_dir()/'languages'/code
    if folder.exists():raise FileExistsError('Language already exists; existing files were preserved')
    import tempfile,os,shutil
    folder.parent.mkdir(parents=True,exist_ok=True)
    temp=Path(tempfile.mkdtemp(prefix='.import-',dir=folder.parent))
    try:
        atomic_json(temp/'strings.json',strings)
        name = data.get('name')
        if isinstance(name, str) and 0 < len(name.strip()) <= 100:
            atomic_json(temp/'metadata.json', {'name': name.strip()})
        (temp/'help.html').write_text(help_,'utf-8')
        os.rename(temp,folder)
    finally:
        if temp.exists():shutil.rmtree(temp)
    return code

def import_pack(path):
    path=Path(path)
    if path.stat().st_size>MAX_PACK:raise ValueError('Pack too large')
    return install_pack(json.loads(path.read_text('utf-8')))

def github_json(url):
    p=urlsplit(url)
    if 'xxxx' in p.path.split('/'):raise ValueError('Repository placeholder')
    if p.scheme!='https' or p.hostname not in ('raw.githubusercontent.com','github.com','api.github.com') or p.username or p.password:
        raise ValueError('Use an HTTPS GitHub JSON URL')
    with requests.Session() as session:
        session.trust_env=False
        with session.get(url,timeout=15,stream=True,allow_redirects=False,headers={'User-Agent':f'{PROGRAM_ID}/{VERSION}'}) as response:
            response.raise_for_status()
            if response.is_redirect:raise ValueError('Use the direct raw JSON URL')
            data=bytearray()
            started=time.monotonic()
            for chunk in response.iter_content(65536):
                if time.monotonic()-started>20:raise TimeoutError("Download timeout")
                data.extend(chunk)
                if len(data)>MAX_PACK:raise ValueError('Pack too large')
            return json.loads(data)

def download_pack(base,code):
    if not base.strip():raise ValueError('No GitHub source configured')
    if not re.fullmatch(r'[a-z]{2,3}(?:[-_][A-Za-z0-9]{2,8})?',code):raise ValueError('Invalid language code')
    data=github_json(base.rstrip('/')+'/'+code+'.json')
    validate_program(data)
    if data.get('code')!=code:raise ValueError('Unexpected language code')
    return install_pack(data)


def download_catalog(base):
    if not base.strip(): raise ValueError('No GitHub source configured')
    data = github_json(base.rstrip('/') + '/catalog.json')
    validate_program(data)
    entries = data.get('languages')
    if not isinstance(entries, list) or len(entries) > 200:
        raise ValueError('Invalid language catalog')
    result = []
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict): raise ValueError('Invalid language entry')
        code, name = entry.get('code'), entry.get('name')
        if not isinstance(code, str) or not re.fullmatch(r'[a-z]{2,3}(?:[-_][A-Za-z0-9]{2,8})?', code):
            raise ValueError('Invalid language code')
        if code in seen: raise ValueError('Duplicate language code')
        if not isinstance(name, str) or not name.strip() or len(name) > 100:
            raise ValueError('Missing language name')
        seen.add(code)
        if code not in ('de', 'en'): result.append({'code': code, 'name': name.strip()})
    return result
