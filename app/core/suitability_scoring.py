"""Deterministic suitability evidence; independent of providers and world state.

True/False mean checked; ``not_tested`` means no evidence. ``ok`` is the
conjunction of checked quality dimensions, or None for invalid input. Semantic
quality is never inferred from format, a golden answer, or a tool name alone.
"""
import copy
import hashlib
import json
import re
from pathlib import Path

SCORER_VERSION = 'suitability-2'
NOT_TESTED = 'not_tested'
TAG = re.compile(r'<tool\s+name="(\w+)">([\s\S]*?)</tool>')
PLACEHOLDER = re.compile(r'^\s*(?:\[[^\]\n]*\]|<[^>\n]*>|\.\.\.|…|input|example)?\s*$', re.I)
MARKERS = re.compile(r'\*\*I (?:feel|do|am at) [^*\n]+\*\*|\[INTENT(?:_DONE|_PROGRESS)?:[^\]\n]+\]|\[EVENT_RESOLVED:[^\]\n]+\]', re.I)
DIMENSIONS = ('format_valid', 'tool_available', 'args_valid', 'decision_correct',
              'required_action_missing', 'forbidden_extra_action', 'correct_abstention',
              'refusal', 'infra_error', 'invalid_input', 'truncated', 'fixture_conflict', 'semantic')


def fixture_version(cases):
    return hashlib.sha256(json.dumps(cases, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def prepare_case(case):
    """Derive catalog/contracts exclusively from the frozen prompt, not examples."""
    c = copy.deepcopy(case)
    if c.get('category') != 'tool':
        return c
    system = c.get('system', '')
    sections = re.findall(r'=== AVAILABLE TOOLS ===\s*([\s\S]*?)(?=\n===|\Z)', system)
    if len(sections) != 1:
        c['fixture_error'] = 'ambiguous or missing catalog section'
        return c
    entries = re.findall(r'^- (\w+):\s*([\s\S]*?)(?=\n- \w+:|\Z)', sections[0], re.M)
    names = [n for n, _ in entries]
    if not names or len(names) != len(set(names)) or 'ToolName' in names:
        c['fixture_error'] = 'ambiguous or empty catalog'
        return c
    c['allowed_tools'] = names
    contracts = {}
    for name, desc in entries:
        json_input = 'JSON' in desc or name == 'Act'
        plain = bool(re.search(r"plain|cleartext|free.text|Klartext|Input: target character name|or JSON|\(b\) just", desc, re.I))
        example = re.search(r'JSON\s*:?\s*(\{[^}]*\})', desc)
        fields = re.findall(r"[\"'](\w+)[\"']\s*:", example.group(1)) if example else []
        if name == 'Act':
            fields = ['text']
        if name == 'RecordVideo':
            fields = ['prompt', 'action_prompt']
        contracts[name] = {'format': 'json_or_text' if json_input and plain else 'json' if json_input else 'text',
                           'keys': list(dict.fromkeys(fields)) if json_input and not plain else [],
                           'json_keys': fields[:2] if name in ('TalkTo', 'SendMessage') else [],
                           'text_pattern': r'^\s*[^,]+,\s*\S[\s\S]*$' if re.search(r"(?:name, comma, message|CharacterName, message)", desc) else None}
    c['arg_contracts'] = contracts
    # Keep conflicting examples separate from candidate argument mistakes.
    # Format-template placeholders such as ``[input]`` are not examples.
    examples = [(n, body) for n, body in TAG.findall(system)
                if n in contracts and not PLACEHOLDER.match(body)]
    conflicts = {n for n, body in examples
                 if contracts[n]['format'] == 'json' and not _json_value(body)[0]}
    if re.search(r'(?:all|every) tool (?:inputs?|arguments?).{0,30}(?:must|only).{0,20}JSON', system, re.I):
        conflicts.update(n for n, body in examples if not _json_value(body)[0])
    c['fixture_conflicts'] = sorted(conflicts)
    c['fixture_conflict'] = bool(conflicts)
    c.pop('fixture_error', None)
    semantic = c.get('expect', {}).get('semantic')
    if semantic is not None:
        try:
            for group in ('required', 'forbidden', 'allow_extra'):
                for rule in semantic.get(group, []):
                    if rule['tool'] not in names:
                        raise ValueError('semantic tool absent from catalog')
                    for patterns in rule.get('args_match', {}).values():
                        for pattern in patterns if isinstance(patterns, list) else [patterns]:
                            re.compile(pattern)
        except (KeyError, TypeError, ValueError, re.error):
            c['fixture_error'] = 'invalid semantic expectations'
    return c


def _json_value(text):
    try:
        return True, json.loads(text.strip())
    except (ValueError, TypeError):
        return False, None


def _matches(action, rule):
    name, body = action
    if name != rule.get('tool'):
        return False
    valid, obj = _json_value(body)
    for key, pattern in rule.get('args_match', {}).items():
        value = body if key == '$text' else obj.get(key, '') if valid and isinstance(obj, dict) else ''
        patterns = pattern if isinstance(pattern, list) else [pattern]
        if not any(re.search(p, str(value), re.I) for p in patterns):
            return False
    return True


def score_case(case, content, *, finish_reason=None, infra_error=False):
    """Score only supplied evidence. No image payload is sent by this runner."""
    r = {k: NOT_TESTED for k in DIMENSIONS}
    r.update(ok=None, hallucinated=False, infra=bool(infra_error), detail='')
    invalid = ('infra_error' if infra_error else 'missing_input' if case.get('task') == 'image_analysis'
               else 'invalid_fixture' if case.get('fixture_error') else None)
    if invalid:
        r.update(invalid_input=invalid, infra_error=bool(infra_error), detail=invalid)
        return r
    if finish_reason == 'length':
        # The model did not finish within the budget: a failure, but neither a
        # refusal nor a hallucination, and never excluded from the denominator.
        r.update(infra_error=False, invalid_input=False, truncated=True, ok=False,
                 detail='truncated (finish_reason=length)')
        return r
    r['infra_error'] = False
    r['invalid_input'] = False
    r['truncated'] = False
    text = content or ''
    refusal_text = MARKERS.sub('', TAG.sub('', text)) if case.get('category') == 'tool' else text
    r['refusal'] = bool(re.search(r"\b(?:as an ai|i cannot|i can't|i'm sorry, but|als ki|ich kann (?:das|dies) nicht|leider kann ich nicht)\b", refusal_text, re.I))
    if case.get('category') == 'tool':
        actions = TAG.findall(text)
        residual = MARKERS.sub('', TAG.sub('', text)).strip()
        abstain = residual in ('NONE', 'SKIP')
        r['format_valid'] = bool((actions or abstain or MARKERS.search(text)) and (not residual or abstain) and not (abstain and actions))
        allowed = case.get('allowed_tools')
        if allowed is None:
            return score_case(prepare_case(case), content, finish_reason=finish_reason, infra_error=infra_error)
        r['tool_available'] = all(n in allowed for n, _ in actions) if actions else NOT_TESTED
        r['hallucinated'] = r['tool_available'] is False
        arg_checks = []
        for name, body in actions:
            contract = case.get('arg_contracts', {}).get(name)
            if contract is None or name in case.get('fixture_conflicts', []):
                continue
            valid, obj = _json_value(body)
            if contract['format'] == 'json':
                arg_checks.append(valid and isinstance(obj, dict) and all(
                    isinstance(obj.get(k), str) and (bool(obj[k].strip()) or k == 'detail')
                    for k in contract.get('keys', []))
                    and (name != 'Act' or obj.get('scope', 'here') in ('here', 'location')))
            elif contract['format'] == 'json_or_text' and body.lstrip().startswith('{'):
                arg_checks.append(valid and isinstance(obj, dict) and bool(obj) and all(
                    isinstance(obj.get(k), str) and bool(obj[k].strip()) for k in contract.get('json_keys', [])))
            else:
                arg_checks.append(bool(re.match(contract['text_pattern'], body)) if contract.get('text_pattern') else bool(body.strip()))
        r['args_valid'] = (False if any(v is False for v in arg_checks) else
                           True if actions and len(arg_checks) == len(actions) else NOT_TESTED)
        r['fixture_conflict'] = bool(case.get('fixture_conflict'))
        semantic = case.get('expect', {}).get('semantic')
        if semantic is not None:
            required = semantic.get('required', [])
            remaining = list(actions)
            missing = False
            for rule in required:
                match = next((i for i, a in enumerate(remaining) if _matches(a, rule)), None)
                if match is None:
                    missing = True
                else:
                    remaining.pop(match)
            forbidden = any(_matches(a, rule) for a in actions for rule in semantic.get('forbidden', []))
            extra = any(not any(_matches(a, rule) for rule in semantic.get('allow_extra', [])) for a in remaining)
            r.update(required_action_missing=missing, forbidden_extra_action=forbidden or extra,
                     decision_correct=not (missing or forbidden or extra),
                     correct_abstention=not actions if not required else NOT_TESTED,
                     semantic=not (missing or forbidden or extra))
    else:
        if case.get('fmt') == 'json':
            # Match the helper's documented extraction contract, without claiming semantics.
            from app.core.model_suitability import _v_json
            r['format_valid'] = _v_json(text, case.get('expect', {}), [])[0]
        else:
            r['format_valid'] = bool(text.strip()) and not TAG.search(text)
    checked = [r[k] for k in ('format_valid', 'tool_available', 'args_valid', 'decision_correct') if isinstance(r[k], bool)]
    # A prompt conflict only suspends the argument check of the conflicting
    # tools (flagged above); format, availability and decisions still count.
    r['ok'] = bool(checked) and all(checked) and not r['refusal']
    r['detail'] = '; '.join(f'{k}={r[k]}' for k in DIMENSIONS)
    return r


def semantic_cases():
    """Minimal synthetic prompts use the same catalog/tag/marker contract."""
    path = Path(__file__).resolve().parents[2] / 'shared/config/suitability_semantic_cases.json'
    return [prepare_case(c) for c in json.loads(path.read_text())['cases']]
