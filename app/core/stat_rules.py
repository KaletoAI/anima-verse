"""Template stat dynamics and shared settings with whole-entry world overrides."""
from copy import deepcopy
import json
import math
from pathlib import Path
from threading import RLock

_SHARED_FILE = Path(__file__).resolve().parents[2] / 'shared' / 'stats' / 'settings.json'
_snapshot_lock = RLock()
_snapshot_key = None
_snapshot = None


def round_half_away(x: float) -> int:
    """Round to the nearest integer, resolving ties away from zero."""
    return int(math.copysign(math.floor(abs(x) + 0.5), x))


def _rule(key: str, data: dict) -> dict:
    baseline = data.get('baseline')
    return {
        'key': key,
        'per_hour': int(data.get('per_hour') or 0),
        'baseline': None if baseline is None or baseline == '' else int(baseline),
        'pull': max(0.0, min(1.0, float(data.get('pull') or 0))),
        'rates': [dict(condition=str(rate.get('condition') or ''),
                       per_hour=int(rate.get('per_hour') or 0),
                       label=str(rate.get('label') or ''))
                  for rate in data.get('rates') or []],
        'thresholds': [
            {**{bound: int(threshold[bound]) for bound in ('min', 'max') if bound in threshold},
             'label': str(threshold.get('label') or ''),
             'text': str(threshold.get('text') or ''),
             **({'need': deepcopy(threshold['need'])} if 'need' in threshold else {})}
            for threshold in data.get('thresholds') or []],
    }


def field_rule(field: dict) -> dict:
    """Normalize one template field into its stat rule."""
    return _rule(str(field['key']), {
        'per_hour': field.get('bar_hourly'), 'baseline': field.get('bar_baseline'),
        'pull': field.get('bar_pull'), 'rates': field.get('bar_rates'),
        'thresholds': field.get('hint_thresholds'),
    })


def template_rules(template: dict) -> dict[str, dict]:
    """Return seed rules for status fields declared by a template."""
    return {field['key']: field_rule(field)
            for section in (template or {}).get('sections', []) or []
            for field in section.get('fields', []) or []
            if field.get('store') == 'status_effects' and field.get('key')}


def invalidate():
    """Clear the cached settings and world overrides after mutations."""
    global _snapshot_key, _snapshot
    with _snapshot_lock:
        _snapshot_key = None
        _snapshot = None


def _load_snapshot():
    global _snapshot_key, _snapshot
    from app.core import paths
    from app.core.db import get_connection
    with _snapshot_lock:
        stat = _SHARED_FILE.stat()
        key = (str(paths.get_storage_dir()), str(_SHARED_FILE), stat.st_mtime_ns, stat.st_size)
        if key != _snapshot_key:
            shipped = json.loads(_SHARED_FILE.read_text(encoding='utf-8'))['settings']
            overrides = {'stat': {}, 'setting': {}}
            for row in get_connection().execute('SELECT scope, key, data FROM stat_overrides'):
                if row['scope'] in overrides:
                    overrides[row['scope']][row['key']] = json.loads(row['data'])
            _snapshot = (shipped, overrides)
            _snapshot_key = key
        return deepcopy(_snapshot)


def world_stat_overrides() -> dict[str, dict]:
    """Return normalized world stat overrides, without template defaults."""
    return {key: _rule(key, data) for key, data in _load_snapshot()[1]['stat'].items()}


def rules_for_template(template: dict) -> dict[str, dict]:
    """Replace declared seed entries with complete world overrides."""
    overrides = world_stat_overrides()
    return {key: overrides.get(key, rule) for key, rule in template_rules(template).items()}


def rules_for_character(name: str, *, profile: dict | None = None,
                        config: dict | None = None) -> dict[str, dict]:
    """Resolve template, world and explicit character dynamics."""
    from app.models.character import get_character_profile, get_character_config
    from app.models.character_template import get_template
    if profile is None:
        profile = get_character_profile(name) or {}
    if config is None:
        config = get_character_config(name) or {}
    rules = rules_for_template(get_template(profile.get('template') or '') or {})
    for key, rule in rules.items():
        for suffix, target in (('_hourly', 'per_hour'), ('_baseline', 'baseline')):
            value = config.get(key + suffix)
            if value is None or value == '' or isinstance(value, bool):
                continue
            try:
                rule[target] = int(float(value))
            except (TypeError, ValueError):
                continue
    return rules


def seed_rule(key: str) -> dict | None:
    """Find the seed in the first template, sorted by template name."""
    from app.models.character_template import list_templates, get_template
    for entry in sorted(list_templates() or [], key=lambda entry: entry['name']):
        rules = template_rules(get_template(entry['name']) or {})
        if key in rules:
            return rules[key]
    return None


def _save(scope, key, value) -> bool:
    from app.core.db import transaction
    with _snapshot_lock:
        with transaction() as conn:
            conn.execute(
                'INSERT INTO stat_overrides (scope, key, data, updated_at) '
                "VALUES (?, ?, ?, CURRENT_TIMESTAMP) ON CONFLICT(scope, key) "
                'DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at',
                (scope, key, json.dumps(value, ensure_ascii=False)))
        invalidate()
    return True


def _delete(scope, key) -> bool:
    from app.core.db import transaction
    with _snapshot_lock:
        with transaction() as conn:
            conn.execute('DELETE FROM stat_overrides WHERE scope=? AND key=?', (scope, key))
        invalidate()
    return True


def save_stat_override(key: str, rule: dict) -> bool:
    """Save a complete replacement rule for one stat key."""
    return _save('stat', key, _rule(key, rule))


def delete_stat_override(key: str) -> bool:
    """Restore the template seed for one stat key."""
    return _delete('stat', key)


def shipped_settings() -> dict:
    """Return the shared settings seed."""
    return _load_snapshot()[0]


def _check_setting(name):
    if name not in shipped_settings():
        raise ValueError(f'Unknown stat setting: {name}')


def get_setting(name: str):
    """Return a setting, replacing the entire shared value when overridden."""
    _check_setting(name)
    shipped, overrides = _load_snapshot()
    return overrides['setting'].get(name, shipped[name])


def settings_with_source() -> dict:
    """Return effective and shipped settings with their origin."""
    shipped, overrides = _load_snapshot()
    return {name: {'value': overrides['setting'].get(name, value),
                   'shipped': value,
                   'source': 'world' if name in overrides['setting'] else 'shared'}
            for name, value in shipped.items()}


def save_setting(name: str, value) -> bool:
    """Save a known world setting as a whole-value replacement."""
    _check_setting(name)
    return _save('setting', name, value)


def delete_setting(name: str) -> bool:
    """Restore a known setting's shared seed."""
    _check_setting(name)
    return _delete('setting', name)
