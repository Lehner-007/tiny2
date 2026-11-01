"""Projektvertrag und mitgelieferte Ressourcen; ohne GTK importierbar."""
import json
import re
from pathlib import Path
from string import Formatter


def resource_dir():
    return Path(__file__).resolve().parent / 'resources'


def read_strings(root, code):
    result = {}
    override = Path(root) / 'lang' / f'{code}.json'
    if override.is_file():
        values = json.loads(override.read_text('utf-8'))
        if not isinstance(values, dict) or any(not isinstance(v, str) for v in values.values()):
            raise ValueError('Sprachdateien müssen ausschließlich Textwerte enthalten')
        for key, value in values.items():
            placeholders = {field for _, field, _, _ in Formatter().parse(value) if field is not None}
            if key in result:
                expected = {field for _, field, _, _ in Formatter().parse(result[key]) if field is not None}
                if placeholders != expected:
                    raise ValueError(f'Abweichende Übersetzungsplatzhalter: {key}')
        result.update(values)
    return result


def load_project(project_file):
    path = Path(project_file).resolve()
    if path.name != 'projekt.json':
        raise ValueError('Die Projektdatei muss projekt.json heißen')
    root = path.parent
    data = json.loads(path.read_text('utf-8'))
    if not isinstance(data, dict):
        raise ValueError('Projektangaben müssen ein Objekt sein')
    for key in ('program_id', 'name'):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise ValueError(f'Fehlende Projektangabe: {key}')
    if not re.fullmatch(r'[a-z][a-z0-9_]{1,63}', data['program_id']):
        raise ValueError('Ungültige Programmkennung')
    version = (root / 'VERSION').read_text('utf-8').strip()
    if not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', version):
        raise ValueError('VERSION muss MAJOR.MINOR.PATCH enthalten')
    data.setdefault('authors', [])
    if not isinstance(data['authors'], list) or any(not isinstance(x, str) for x in data['authors']):
        raise ValueError('Mitwirkende müssen eine Textliste sein')
    data.setdefault('license', 'GPL-3.0-only')
    if data['license'] not in ('GPL-3.0-only', 'MIT'):
        raise ValueError('Dieser Basisstand unterstützt GPL-3.0-only im Infofenster')
    for key in ('update_url', 'source_url'):
        data.setdefault(key, '')
        if not isinstance(data[key], str):
            raise ValueError(f'{key} muss Text sein')
    for key in ('profiles_enabled', 'demo_enabled'):
        data.setdefault(key, False)
        if type(data[key]) is not bool:
            raise ValueError(f'{key} muss boolesch sein')
    for key, default in [('image', 'assets/programmbild.png'), ('watermark', 'assets/report_watermark.png')]:
        data.setdefault(key, default)
        value = data[key]
        if not isinstance(value, str) or not value or Path(value).is_absolute() or not (root / value).resolve().is_relative_to(root):
            raise ValueError(f'{key} muss innerhalb des Projekts liegen')
        if not (root / value).is_file():
            raise ValueError(f'Bild fehlt: {value}')
    data.setdefault('settings', [])
    if not isinstance(data['settings'], list):
        raise ValueError('settings muss eine Liste sein')
    keys = set()
    reserved = {'config_version','language','update_check','update_interval_value','update_interval_unit',
                'update_url','source_url','last_update_check','active_profile','window_width','window_height',
                'window_x','window_y','window_position_known','window_maximized'}
    for field in data['settings']:
        if not isinstance(field, dict) or not isinstance(field.get('key'), str) or not field['key']:
            raise ValueError('Ungültiges Einstellungsfeld')
        if field['key'] in keys | reserved:
            raise ValueError('Doppelter oder reservierter Einstellungsschlüssel')
        keys.add(field['key'])
        if not isinstance(field.get('label'), str):
            raise ValueError('Ungültige Beschriftung')
        if field.get('type') == 'boolean':
            if type(field.get('default')) is not bool:
                raise ValueError('Ungültiger boolescher Standardwert')
        elif field.get('type') == 'string':
            if not isinstance(field.get('default'), str):
                raise ValueError('Ungültiger Textstandardwert')
        elif field.get('type') == 'number':
            if any(type(field.get(k)) is not int for k in ('min','max','default')):
                raise ValueError('Ungültiges Zahlenfeld')
            if not field['min'] <= field['default'] <= field['max']:
                raise ValueError('Ungültiger Wertebereich')
        else:
            raise ValueError('Nicht unterstützter Einstellungstyp')
    data.setdefault('tool_info', [])
    if not isinstance(data['tool_info'], list) or any(not isinstance(t, dict) for t in data['tool_info']):
        raise ValueError('tool_info muss eine Objektliste sein')
    for code in ('de', 'en'):
        read_strings(root, code)
    return root, data, version
