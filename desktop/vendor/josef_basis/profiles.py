"""Optionale Profile; globale Sprache und GitHub-Einstellungen bleiben getrennt."""
import json
import uuid
from .model import PROJECT, config_dir, atomic_json, validate_settings


def profile_options(options):
    validated = validate_settings(options)
    return {field['key']: validated[field['key']] for field in PROJECT['settings']}


class ProfileStore:
    def __init__(self):
        self.path = config_dir() / 'profiles.json'
        self.items = {}
        if self.path.exists():
            data = json.loads(self.path.read_text('utf-8'))
            if not isinstance(data, dict) or data.get('profile_version') != 1 or not isinstance(data.get('items'), dict):
                raise ValueError('Invalid profiles')
            for key, item in data['items'].items():
                if not isinstance(key, str) or not isinstance(item, dict) or not isinstance(item.get('options'), dict):
                    raise ValueError('Invalid profile')
                self.check_name(item.get('name'), key)
                self.items[key] = {'name': item['name'], 'options': profile_options(item['options'])}

    def check_name(self, name, current=None):
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 100:
            raise ValueError('Invalid profile name')
        if any(key != current and item['name'].casefold() == name.strip().casefold()
               for key, item in self.items.items()):
            raise ValueError('Duplicate profile name')

    def create(self, name, options):
        self.check_name(name)
        key = uuid.uuid4().hex
        self.items[key] = {'name': name.strip(), 'options': profile_options(options)}
        return key

    def update(self, key, name, options):
        if key not in self.items:
            raise ValueError('Unknown profile')
        self.check_name(name, key)
        self.items[key] = {'name': name.strip(), 'options': profile_options(options)}

    def save(self):
        atomic_json(self.path, {'profile_version': 1, 'items': self.items})

    def apply(self, key, global_options):
        result = global_options.copy()
        result.update(self.items[key]['options'])
        result['active_profile'] = key
        return validate_settings(result)
