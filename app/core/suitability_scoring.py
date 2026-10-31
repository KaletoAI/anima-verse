"""Structural suitability evidence, independent of providers and world state."""
import copy
import hashlib
import json
import re
from pathlib import Path

SCORER_VERSION = 'suitability-3'
NOT_TESTED = 'not_tested'
ROOT = Path(__file__).resolve().parents[2]
# Regex parses protocol syntax only; free text is never matched against a golden.
TAG = re.compile(r'<tool\s+name="(\w+)">([\s\S]*?)</tool>')
MARKERS = re.compile(r'\[INTENT(?:_DONE|_PROGRESS)?:[^\]\n]+\]')
DIMENSIONS = ('format_valid', 'tool_available', 'args_valid', 'decision_correct',
              'required_action_missing', 'forbidden_extra_action', 'correct_abstention',
              'refusal', 'infra_error', 'invalid_input', 'truncated', 'fixture_conflict', 'semantic')


def fixture_version(cases):
    return hashlib.sha256(json.dumps(cases, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def prepare_case(case):
    """Normalize metadata; availability comes from declarations, never answers."""
    c = copy.deepcopy(case)
    group = c.setdefault('group', 'tools' if c.get('category') == 'tool' else
                         'vision' if c.get('task') in ('image_analysis', 'image_recognition') else 'helpers')
    c['category'] = 'tool' if group == 'tools' else 'helper'
    c.setdefault('label', c.get('id', c.get('task', 'case')))
    c.setdefault('repeats', 3)
    if group == 'tools' and 'allowed_tools' not in c:
        prompt = c.get('system', '') + '\n' + c.get('user', '')
        section = prompt.split('Tools offered this turn:', 1)[-1] if 'Tools offered this turn:' in prompt else prompt.split('=== AVAILABLE TOOLS ===', 1)[-1]
        c['allowed_tools'] = list(dict.fromkeys(re.findall(r'^- (\w+):', section, re.M)))
        if not c['allowed_tools'] and 'Tools offered this turn:' not in prompt:
            c['fixture_error'] = 'missing tool catalog'
    return c


def _json_value(text):
    try:
        return True, json.loads(text.strip())
    except (ValueError, TypeError):
        return False, None


def _text_valid(value, rule):
    values = value if isinstance(value, list) else [value]
    if not values:
        return False
    for text in values:
        if not isinstance(text, str) or not rule.get('min', 1) <= len(text.strip()) <= rule.get('max', 2000):
            return False
        lang = rule.get('lang')
        if lang:
            words = {''.join(ch for ch in word.lower() if ch.isalpha()) for word in text.split()}
            # A conservative language signal, not a topic or wording expectation.
            signals = {'de': {'der', 'die', 'das', 'ein', 'eine', 'sie', 'ich', 'ist', 'und', 'mit', 'steht', 'sind'},
                       'en': {'the', 'a', 'an', 'is', 'are', 'with', 'and', 'it', 'there'}}
            if lang not in signals or not words.intersection(signals[lang]):
                return False
    return True


def _fields_valid(obj, rule, sets):
    if not isinstance(obj, dict) or not all(key in obj for key in rule.get('required', rule.get('json_fields', []))):
        return False
    if any(key in obj for key in rule.get('forbid_fields', [])):
        return False
    for key, set_name in rule.get('in_sets', {}).items():
        value = obj.get(key)
        values = value if isinstance(value, list) else [value]
        if set_name not in sets or any(v not in sets[set_name] for v in values):
            return False
    for key, expected in rule.get('values', {}).items():
        if type(obj.get(key)) is not type(expected) or obj[key] != expected:
            return False
    for key, field_type in rule.get('types', {}).items():
        types = {'array': list, 'object': dict, 'string': str, 'boolean': bool}
        if field_type not in types or not isinstance(obj.get(key), types[field_type]):
            return False
    for key, minimum in rule.get('min_items', {}).items():
        if not isinstance(obj.get(key), list) or len(obj[key]) < minimum:
            return False
    for key, item_rule in rule.get('items_fields', {}).items():
        if not isinstance(obj.get(key), list) or not all(_fields_valid(item, item_rule, sets) for item in obj[key]):
            return False
    return all(_text_valid(obj.get(key), text_rule) for key, text_rule in rule.get('text_fields', {}).items())


def score_case(case, content, *, finish_reason=None, infra_error=False):
    """Check declared structure and offered sets; unreviewed logs prove format only."""
    case = prepare_case(case)
    r = {key: NOT_TESTED for key in DIMENSIONS}
    r.update(ok=None, hallucinated=False, infra=bool(infra_error), detail='')
    image = case.get('image')
    invalid = ('infra_error' if infra_error else 'invalid_fixture' if case.get('fixture_error') else
               'missing_input' if case['group'] == 'vision' and (not image or not (ROOT / image).is_file()) else None)
    if invalid:
        r.update(invalid_input=invalid, infra_error=bool(infra_error), detail=invalid)
        return r
    r.update(infra_error=False, invalid_input=False, truncated=finish_reason == 'length', refusal=finish_reason == 'content_filter')
    if r['refusal']:
        r.update(ok=False, detail='refused (finish_reason=content_filter)')
        return r
    if r['truncated']:
        r.update(ok=False, detail='truncated (finish_reason=length)')
        return r
    text = content if isinstance(content, str) else ''
    expect = case.get('expect', {}) if case.get('reviewed', True) else {}
    sets = case.get('sets', {})
    if case['group'] == 'tools':
        actions = TAG.findall(text)
        markers = MARKERS.findall(text)
        residual = MARKERS.sub('', TAG.sub('', text)).strip()
        none = residual == 'NONE'
        r['format_valid'] = bool(actions or markers or none) and (not residual or none) and not (none and actions)
        r['tool_available'] = all(name in case['allowed_tools'] for name, _ in actions)
        r['hallucinated'] = not r['tool_available']
        checks = []
        rules = expect.get('tools', {})
        for name, body in actions:
            rule = rules.get(name)
            if rule is not None and 'text_in' in rule:
                # Some real verbs (movement) take a plain-text menu entry.
                checks.append(body.strip() in sets.get(rule['text_in'], []))
            elif rule is not None:
                valid, obj = _json_value(body)
                normalized = {**rule, 'in_sets': dict(rule.get('in_sets', {}))}
                for key, set_name in rule.items():
                    if key.endswith('_in'):
                        normalized['in_sets'][key[:-3]] = set_name
                checks.append(valid and _fields_valid(obj, normalized, sets))
            else:
                checks.append(bool(body.strip()))
        r['format_valid'] = r['format_valid'] and all(bool(body.strip()) for _, body in actions)
        if expect:
            r['args_valid'] = all(checks)
        if expect:
            names = [name for name, _ in actions]
            missing = any(name not in names for name in rules)
            extra = len(names) != len(set(names)) or any(name not in rules or name in expect.get('forbid_tools', []) for name in names)
            marker_rules = expect.get('markers', {})
            parsed = [m[1:-1].split(':', 1) for m in markers]
            marker_ok = len(parsed) == len(marker_rules)
            for key, expected in marker_rules.items():
                matches = [body.strip() for kind, body in parsed if kind.lower() == key]
                marker_ok = marker_ok and len(matches) == 1 and (bool(matches[0]) if expected is True else matches[0].split('|', 1)[0].strip() == expected)
            abstention = none == expect.get('none', False)
            r.update(required_action_missing=missing, forbidden_extra_action=extra,
                     correct_abstention=abstention,
                     decision_correct=not missing and not extra and marker_ok and abstention)
            r['semantic'] = r['decision_correct']
    else:
        wants_json = case.get('fmt') == 'json' or 'json_fields' in expect
        if wants_json:
            valid, obj = _json_value(text)
            r['format_valid'] = valid
            if expect:
                rule = {**expect, 'json_fields': expect.get('json_fields', expect.get('keys', []))}
                r['args_valid'] = valid and _fields_valid(obj, rule, sets)
        else:
            r['format_valid'] = _text_valid(text, expect) and not TAG.search(text)
            if expect.get('plain_text'):
                # Protocol checks only: JSON and fenced/tagged output are not prose.
                valid_json, _ = _json_value(text)
                r['format_valid'] = (r['format_valid'] and not valid_json
                                     and not text.lstrip().startswith(('{', '['))
                                     and '```' not in text and '<tool' not in text.lower())
    checked = [r[k] for k in ('format_valid', 'tool_available', 'args_valid', 'decision_correct') if isinstance(r[k], bool)]
    r['ok'] = bool(checked) and all(checked)
    r['detail'] = '; '.join(f'{key}={r[key]}' for key in DIMENSIONS)
    return r


def curated_cases():
    """Load tracked SFW prompts; real-world log candidates stay world-local."""
    path = ROOT / 'shared/config/suitability_curated_cases.json'
    return [prepare_case(c) for c in json.loads(path.read_text(encoding='utf-8'))['cases']]
