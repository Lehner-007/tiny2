"""External strings, English fallback, and validated personal language packs."""
from pathlib import Path
from string import Formatter
import json
import re
from .model import ROOT, config_dir
from .project import resource_dir, read_strings

def fields(value):
    return {x[1] for x in Formatter().parse(value) if x[1] is not None}

class Strings:
    def __init__(self, language='de'):
        self.en = read_strings(ROOT, 'en')
        if not isinstance(language,str) or not re.fullmatch(r'[a-z]{2,3}(?:[-_][A-Za-z0-9]{2,8})?',language): language="en"
        self.code = language
        self.values = self.en.copy()
        candidates = [resource_dir()/'lang'/f'{language}.json', ROOT/'lang'/f'{language}.json', config_dir()/'languages'/language/'strings.json'] if re.fullmatch(r'[a-z]{2,3}(?:[-_][A-Za-z0-9]{2,8})?',language) else []
        for p in candidates:
            try:
                data = json.loads(p.read_text('utf-8'))
                if not isinstance(data,dict): continue
                for key,value in data.items():
                    if key in self.en and isinstance(value,str) and fields(value)==fields(self.en[key]): self.values[key] = value
            except (OSError,ValueError): pass

    def __call__(self,key,**kwargs):
        text = self.values.get(key,self.en.get(key,key))
        try: return text.format(**kwargs)
        except (ValueError,KeyError,IndexError): return self.en.get(key,key)

    def language_name(self, code, fallback=None):
        key = 'language_name_' + code
        if key in self.values:
            return self.values[key]
        if re.fullmatch(r'[a-z]{2,3}(?:[-_][A-Za-z0-9]{2,8})?', code):
            try:
                data = json.loads((config_dir()/'languages'/code/'metadata.json').read_text('utf-8'))
                name = data.get('name')
                if isinstance(name, str) and name.strip(): return name
            except (OSError, ValueError, AttributeError):
                pass
        return fallback or code

    def help_path(self):
        paths = [config_dir()/'languages'/self.code/'help.html',ROOT/'help'/self.code/'index.html',resource_dir()/'help'/self.code/'index.html', resource_dir()/'help/en/index.html']
        return next(p for p in paths if p.is_file())

    @staticmethod
    def languages():
        codes = {'de','en'}
        base = config_dir()/'languages'
        if base.exists():
            codes.update(p.parent.name for p in base.glob('*/strings.json') if re.fullmatch(r'[a-z]{2,3}(?:[-_][A-Za-z0-9]{2,8})?',p.parent.name))
        return sorted(codes)
