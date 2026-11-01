"""Projektangaben und kontrolliert gespeicherte Entwicklungseinstellungen."""
import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from datetime import datetime, timezone

_configuration = None


def configure(project_file, *, development=False, state_dir=None):
    """Bind one application's resources before importing its GUI modules.

    One project per process is deliberate: imported template modules retain their
    project references. A second project is rejected instead of sharing state.
    """
    global ROOT, PROJECT, PROGRAM_ID, VERSION, DEFAULTS, _configuration, _state_dir
    from .project import load_project
    root, project, version = load_project(project_file)
    state = Path(state_dir).resolve() if state_dir is not None else (
        root / '.config' if development else
        Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))) / project['program_id'])
    if not state.is_absolute():
        raise ValueError('Der Konfigurationsordner muss absolut sein')
    identity = (root, state, bool(development))
    if _configuration is not None:
        if _configuration != identity:
            raise RuntimeError('Pro Prozess ist nur ein Projekt erlaubt; separates Programm starten')
        return
    ROOT, PROJECT, VERSION = root, project, version
    PROGRAM_ID = project['program_id']
    _state_dir = state
    # Debian's postrm hook needs to find a non-default XDG_CONFIG_HOME even
    # after dpkg has removed the application and cleared its environment.
    # Keep one user-owned registration in the standard XDG state tree.
    if root == Path('/usr/share/tiny') and not development:
        registry_dir = Path.home() / '.local' / 'state' / 'tiny'
        registry_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            registry_dir.chmod(0o700)
            registry = registry_dir / f'{PROGRAM_ID}-config-dir'
            fd = os.open(registry, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, 'O_NOFOLLOW', 0), 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                stream.write(str(state) + '\n')
                stream.flush()
                os.fsync(stream.fileno())
        except OSError:
            # Configuration must remain usable if a removable registration
            # cannot be recorded; the DEB hook reports the remaining cleanup.
            pass
    DEFAULTS = dict(config_version=4, language='de', update_check=False,
                    update_interval_value=1, update_interval_unit='weeks',
                    update_url=PROJECT['update_url'], source_url=PROJECT['source_url'],
                    last_update_check='', active_profile='', window_width=760, window_height=480,
                    window_x=0, window_y=0, window_position_known=False, window_maximized=False)
    DEFAULTS.update({field['key']: os.path.expanduser(field['default'])
                     if isinstance(field['default'], str) and field['default'].startswith('~/')
                     else field['default'] for field in PROJECT['settings']})
    _configuration = identity


def config_dir():
    if _configuration is None:
        raise RuntimeError('Zuerst Anwendung mit einer Projektdatei erstellen')
    return _state_dir


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def validate_settings(data):
    result = DEFAULTS.copy()
    if isinstance(data, dict):
        for key, default in DEFAULTS.items():
            value = data.get(key, default)
            if type(value) is type(default):
                result[key] = value
    result['config_version'] = DEFAULTS['config_version']
    result['update_url']=PROJECT['update_url']
    result['source_url']=PROJECT['source_url']
    for key in ('window_width', 'window_height'):
        result[key] = max(240, min(10000, result[key]))
    for key in ('window_x', 'window_y'):
        result[key] = max(-100000, min(100000, result[key]))
    result['update_interval_value'] = max(1, min(365, result['update_interval_value']))
    if result['update_interval_unit'] not in ('days', 'weeks', 'months'):
        result['update_interval_unit'] = 'weeks'
    for field in PROJECT['settings']:
        if field['type'] == 'number':
            result[field['key']] = max(field['min'], min(field['max'], result[field['key']]))
    if 'preview_width' in result and result['preview_width'] not in (640, 1280, 1920):
        result['preview_width'] = 1280
    return result


def settings():
    path = config_dir() / 'settings.json'
    try:
        return validate_settings(json.loads(path.read_text('utf-8')))
    except (OSError, ValueError, UnicodeError):
        return DEFAULTS.copy()


def save_settings(data):
    path = config_dir() / 'settings.json'
    if path.exists():
        try:
            old = json.loads(path.read_text('utf-8'))
            if not isinstance(old, dict):
                raise ValueError('Invalid settings')
        except (ValueError, UnicodeError):
            shutil.copy2(path, path.with_name(f'settings.invalid.{time.time_ns()}.json'))
    atomic_json(path, validate_settings(data))


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def update_due(options):
    if not options['update_check'] or not options['update_url'].strip():
        return False
    try:
        last = datetime.fromisoformat(options['last_update_check'])
        elapsed = (datetime.now(timezone.utc) - last).total_seconds()
    except (ValueError, TypeError):
        return True
    days = options['update_interval_value'] * {'days': 1, 'weeks': 7, 'months': 30}[options['update_interval_unit']]
    return elapsed >= days * 86400
