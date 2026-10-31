"""One availability and success-only cost boundary for character skills."""
from collections.abc import Callable, Iterable
from contextvars import ContextVar
from typing import Any, TypeVar
from time import perf_counter

from app.core.tool_call_log import record, classify

_Result = TypeVar('_Result')
_running: ContextVar[frozenset[tuple[str, str]]] = ContextVar('gated_skill_calls', default=frozenset())


def costs(skill_id: str) -> dict[str, int]:
    """Positive configured deductions; an empty entry means free."""
    from app.core.stat_rules import get_setting
    configured = (get_setting('skill_costs') or {}).get(skill_id) or {}
    return {key: value for key, value in configured.items()
            if isinstance(value, int) and not isinstance(value, bool) and value > 0}


def _stat_label(key: str) -> str:
    from app.models.character_template import list_templates, get_template
    for entry in sorted(list_templates() or [], key=lambda item: item['name']):
        for section in (get_template(entry['name']) or {}).get('sections', []):
            for field in section.get('fields', []):
                if field.get('store') == 'status_effects' and field.get('key') == key:
                    return field.get('label') or key
    return key


def stat_costs_shortfall(profile: dict, costs: dict) -> str | None:
    """Describe the first unmet cost; stats absent from the profile are free."""
    from app.core.stat_boosts import effective_stat
    for key, amount in costs.items():
        value = effective_stat(profile, key)
        if value is not None and value < amount:
            return f'needs {amount} {_stat_label(key)}'
    return None


def _cost_reason(name: str, skill_id: str, profile: dict) -> str:
    from app.core.dependencies import get_skill_manager
    shortfall = stat_costs_shortfall(profile, costs(skill_id))
    if shortfall:
        skill = get_skill_manager().get_skill(skill_id)
        tool_name = skill.name if skill else skill_id
        return f'Too exhausted for {tool_name} ({shortfall})'
    return ''


def _skill_rules() -> list[dict]:
    """Block rules that target skills (one load per gate question batch)."""
    from app.models.rules import load_rules
    return [rule for rule in load_rules()
            if rule.get('type') == 'block'
            and (rule.get('target') or {}).get('scope') == 'skill']


def blocked_reason(name: str, skill_id: str, *, profile: dict | None = None,
                   rules: list[dict] | None = None) -> str:
    """Return a rule message or cost shortfall; empty means allowed.

    ``rules`` lets a caller asking about many skills load the rules once.
    """
    from app.models.character import (get_character_profile, get_character_current_location,
                                      get_character_current_room)
    from app.models.rules import _user_lang
    from app.core.i18n import localized
    from app.core.activity_engine import evaluate_condition
    for rule in (_skill_rules() if rules is None else rules):
        target = rule.get('target') or {}
        if skill_id not in (target.get('skills') or []):
            continue
        character = (rule.get('character') or '').strip()
        if character and character != name:
            continue
        condition = rule.get('condition') or ''
        if not condition or evaluate_condition(condition, name,
                get_character_current_location(name) or '', get_character_current_room(name) or '')[0]:
            return localized(rule, 'message', _user_lang()) or 'Skill unavailable.'
    if profile is None:
        profile = get_character_profile(name) or {}
    return _cost_reason(name, skill_id, profile)


def blocked_skills(name: str, skill_ids: Iterable[str]) -> dict[str, str]:
    """Reasons keyed by stable skill ID, omitting available skills."""
    from app.models.character import get_character_profile
    rules = _skill_rules()
    profile = get_character_profile(name) or {}
    return {sid: reason for sid in skill_ids
            if (reason := blocked_reason(name, sid, profile=profile, rules=rules))}


def charge(name: str, skill_id: str) -> dict:
    """Deduct only existing stats and record skill provenance."""
    from app.models.character import adjust_status_effects
    return adjust_status_effects(name, {key: -amount for key, amount in costs(skill_id).items()},
                                 source=f'skill:{skill_id}')


def run_gated(name: str, skill_id: str, call: Callable[[], _Result], *,
              tool_input: Any = "", source: str = "", tool_name: str = "") -> _Result | str:
    """Recheck immediately before execution and charge only non-error results.

    Intent handlers return dictionaries; their explicit failure status obeys
    the same contract as the string errors returned by tools. No profile lock
    spans a skill call, which may make network requests.
    """
    from app.core.streaming import is_error_result
    key = (name, skill_id)
    if key in _running.get():
        return call()
    display_name = tool_name or skill_id
    if not tool_name:
        try:
            from app.core.dependencies import get_skill_manager
            skill = get_skill_manager().get_skill(skill_id)
            display_name = skill.name if skill else skill_id
        except Exception:
            pass
    started = perf_counter()
    def outcome(status, result):
        record(character=name, tool=display_name, status=status, result=result,
               tool_input=tool_input, source=source,
               duration_ms=(perf_counter() - started) * 1000)
    # PropAction owns admission and charging; preserve its direct execution.
    if skill_id != 'prop_action':
        reason = blocked_reason(name, skill_id)
        if reason:
            result = f'Error: {reason}'
            outcome('blocked', result)
            return result
    token = _running.set(_running.get() | {key})
    try:
        try:
            result = call()
        except Exception as exc:
            outcome('exception', exc)
            raise
        outcome(classify(result), result)
        if skill_id != 'prop_action':
            failed = (isinstance(result, dict) and
                      (result.get('success') is False or result.get('ok') is False or bool(result.get('error'))))
            if not failed and not is_error_result(result):
                charge(name, skill_id)
        return result
    finally:
        _running.reset(token)


def run_tool(name: str, tool_name: str, call: Callable[[], _Result], *,
             tool_input: Any = "", source: str = "") -> _Result | str:
    """Resolve a display tool name for generic execution adapters."""
    from app.core.dependencies import get_skill_manager
    skill = get_skill_manager().get_skill_by_name(tool_name)
    if skill:
        return run_gated(name, skill.SKILL_ID, call, tool_input=tool_input,
                         source=source, tool_name=tool_name)
    key = (name, tool_name)
    if key in _running.get():
        return call()
    token = _running.set(_running.get() | {key})
    started = perf_counter()
    try:
        try:
            result = call()
        except Exception as exc:
            record(character=name, tool=tool_name, status='exception', result=exc,
                   tool_input=tool_input, source=source,
                   duration_ms=(perf_counter() - started) * 1000)
            raise
        record(character=name, tool=tool_name, status=classify(result), result=result,
               tool_input=tool_input, source=source,
               duration_ms=(perf_counter() - started) * 1000)
        return result
    finally:
        _running.reset(token)


def prompt_lines(name: str, *, turn: str = '', check_limits: bool = False) -> list[str]:
    """Explain only skills the character would otherwise have this turn."""
    from app.core.dependencies import get_skill_manager
    skills = get_skill_manager()._get_agent_skills(name, check_limits=check_limits,
                                                  turn=turn, apply_gate=False)
    blocks = blocked_skills(name, [skill.SKILL_ID for skill in skills])
    return [f'- Unavailable right now: {skill.name} — {blocks[skill.SKILL_ID]}'
            for skill in skills if skill.SKILL_ID in blocks]


def tool_blocked_reason(name: str, tool_name: str) -> str:
    """Explain even a tool omitted from the advertised executable list."""
    from app.core.dependencies import get_skill_manager
    skill = get_skill_manager().get_skill_by_name(tool_name)
    return blocked_reason(name, skill.SKILL_ID) if skill else ''
