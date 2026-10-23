"""Template stat dynamics and shared settings with whole-entry world overrides."""
from copy import deepcopy
import json
import math
import sqlite3
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
            try:
                rows = get_connection().execute(
                    'SELECT scope, key, data FROM stat_overrides').fetchall()
            except sqlite3.OperationalError:
                # A world DB without the table (not migrated yet, or a test DB
                # with a partial schema) simply has no overrides.
                rows = []
            for row in rows:
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


_chat_cap_lock = RLock()
_chat_movement: dict[tuple[str, str], tuple[int, int]] = {}


def cap_chat_deltas(name: str, deltas: dict[str, int]) -> dict[str, int]:
    """Limit absolute ordinary chat movement per stat and game hour.

    Turning points (magnitude at least 30) bypass and do not consume the
    budget. Only the current hour is retained for each character/stat.
    """
    from app.core.timeutils import game_time
    limit = get_setting("chat_cap_per_hour")
    if limit == 0:
        return dict(deltas)
    hour = game_time().total_seconds // 3600
    result = {}
    with _chat_cap_lock:
        for key, raw in deltas.items():
            try:
                delta = round_half_away(float(raw))
            except (TypeError, ValueError, OverflowError):
                continue
            if abs(delta) >= 30:
                result[key] = delta
                continue
            previous_hour, used = _chat_movement.get((name, key), (hour, 0))
            if previous_hour != hour:
                used = 0
            allowed = min(abs(delta), max(0, limit - used))
            if allowed:
                result[key] = allowed if delta > 0 else -allowed
            _chat_movement[(name, key)] = (hour, used + allowed)
    return result


CATEGORIES = ['ambient', 'social', 'disruption', 'danger']
OCCASIONS = ['intent_done', 'gift_received']


def build_admin_payload() -> dict:
    """Build the world values editor payload from declared template fields."""
    from app.models.character_template import list_templates, get_template
    from app.core.dependencies import get_skill_manager
    seeds = {}
    names = {}
    for entry in sorted(list_templates() or [], key=lambda entry: entry['name']):
        template = get_template(entry['name']) or {}
        for section in template.get('sections', []) or []:
            for field in section.get('fields', []) or []:
                if field.get('store') == 'status_effects' and field.get('key'):
                    key = field['key']
                    seeds.setdefault(key, field_rule(field))
                    names.setdefault(key, field.get('label') or key)
    overrides = world_stat_overrides()
    return {
        'stats': [{'key': key, 'name': names.get(key, key),
                   'shipped': seeds.get(key), 'override': overrides.get(key),
                   'effective': overrides.get(key, seeds.get(key)),
                   'source': 'world' if key in overrides else 'shared'}
                  for key in sorted(seeds.keys() | overrides.keys())],
        'settings': settings_with_source(),
        'skills': [{'id': skill.SKILL_ID, 'name': skill.name}
                   for skill in get_skill_manager().skills],
        'categories': list(CATEGORIES), 'occasions': list(OCCASIONS),
    }


def _integer(value, low, high):
    return type(value) is int and low <= value <= high


def validate_rule(rule) -> list[str]:
    """Reject malformed rule shapes, ranges and condition references."""
    import re
    from app.core.activity_engine import validate_condition_references
    errors = []
    if not isinstance(rule, dict):
        return ['Rule must be an object']
    for key, low, high in (('per_hour', -100, 100), ('baseline', 0, 100)):
        if key in rule and not (key == 'baseline' and rule[key] is None):
            if not _integer(rule[key], low, high):
                errors.append(f'{key} must be an integer in {low}..{high}')
    pull = rule.get('pull', 0)
    if type(pull) not in (int, float) or not 0 <= pull <= 1 or not math.isfinite(pull):
        errors.append('pull must be a finite number in 0..1')
    for collection in ('rates', 'thresholds'):
        entries = rule.get(collection, [])
        if not isinstance(entries, list):
            errors.append(f'{collection} must be a list')
            continue
        for index, entry in enumerate(entries):
            prefix = f'{collection}[{index}]'
            if not isinstance(entry, dict):
                errors.append(f'{prefix} must be an object')
                continue
            for text_key in ('label', 'text'):
                if text_key in entry and not isinstance(entry[text_key], str):
                    errors.append(f'{prefix}.{text_key} must be a string')
            if collection == 'rates':
                if not _integer(entry.get('per_hour'), -100, 100):
                    errors.append(f'{prefix}.per_hour must be an integer in -100..100')
                condition = entry.get('condition')
                if not isinstance(condition, str) or not condition.strip():
                    errors.append(f'{prefix}.condition must be a non-empty string')
                    continue
                for atom in re.split(r'\b(?:AND|OR)\b', condition, flags=re.IGNORECASE):
                    atom = re.sub(r'^NOT\s+', '', atom.strip(), flags=re.IGNORECASE).strip()
                    if not atom or atom.upper() == 'NOT':
                        errors.append(f'{prefix}.condition has an empty atom')
                    elif re.search(r'[<>=]', atom) and not re.fullmatch(r'[^<>=]+[<>=]-?\d+', atom):
                        errors.append(f'{prefix}.condition has an invalid comparison: {atom}')
                errors.extend(validate_condition_references(condition))
            else:
                if not any(bound in entry for bound in ('min', 'max')):
                    errors.append(f'{prefix} needs a min or max bound')
                for bound in ('min', 'max'):
                    if bound in entry and not _integer(entry[bound], 0, 100):
                        errors.append(f'{prefix}.{bound} must be an integer in 0..100')
                if 'min' in entry and 'max' in entry and all(type(entry[b]) is int for b in ('min', 'max')):
                    if entry['min'] > entry['max']:
                        errors.append(f'{prefix}.min must not exceed max')
                if 'need' in entry:
                    need = entry['need']
                    if not isinstance(need, dict) or not isinstance(need.get('text'), str) or need.get('urgency') not in ('urgent', 'felt'):
                        errors.append(f'{prefix}.need requires text and urgency urgent or felt')
    return errors


def validate_setting(name: str, value) -> list[str]:
    """Validate the complete replacement value for a known stat setting."""
    if name not in shipped_settings():
        return [f'Unknown stat setting: {name}']
    if name == 'chat_cap_per_hour':
        valid = _integer(value, 0, 100)
    elif name == 'perception_gate':
        valid = (isinstance(value, dict) and set(value) == {'enabled', 'stat', 'below'}
                 and type(value['enabled']) is bool and isinstance(value['stat'], str)
                 and bool(value['stat'].strip()) and _integer(value['below'], 0, 100))
    else:
        valid = isinstance(value, dict)
        if valid:
            if name == 'rewards':
                valid = set(value) == set(OCCASIONS)
            elif name == 'event_effects':
                valid = set(value) <= set(CATEGORIES)
            low = 0 if name == 'skill_costs' else -100
            valid = valid and all(
                isinstance(key, str) and bool(key.strip()) and isinstance(stats, dict)
                and all(isinstance(stat, str) and bool(stat.strip()) and _integer(delta, low, 100)
                        for stat, delta in stats.items())
                for key, stats in value.items())
    return [] if valid else [f'Invalid value for {name}']


def describe_source(source: str, metadata: dict | None = None) -> str:
    """Explain a history source using its recorded parts, without stat names."""
    if source == 'hourly':
        parts = []
        for entries in ((metadata or {}).get('parts') or {}).values():
            for part in entries:
                delta = part.get('delta', 0)
                if not delta:
                    continue
                text = f"{part.get('label', '')} {'+' if delta > 0 else '−'}{abs(delta)}"
                if text not in parts:
                    parts.append(text)
        # Explain active sources before the common base drift.
        parts.sort(key=lambda text: text.startswith('Base '))
        return ', '.join(parts) or source
    labels = {'chat': 'Chat', 'activity': 'Activity', 'event_resolved': 'Event resolved',
              'intent_done': 'Plan done', 'gift_received': 'Gift'}
    for prefix, label in (('item:', ''), ('skill:', 'Skill '), ('spell:', ''), ('event:', 'Event')):
        if source.startswith(prefix):
            return label if prefix == 'event:' else label + source[len(prefix):]
    return labels.get(source, source)
