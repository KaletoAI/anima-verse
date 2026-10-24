"""Generic rule multipliers for core and package-registered quantities."""
from __future__ import annotations

import math
import threading
import time

_quantities: dict[str, dict[str, str]] = {}

# factor() is asked per character on hot paths (every travel tick asks the
# discovery range of every character). A result lives this long (technical
# cache, system time); every rule change clears it, so only a stat change
# takes up to this long to show.
_CACHE_TTL_S = 30.0
_cache: dict[tuple[str, str], tuple[float, float]] = {}
_cache_lock = threading.Lock()


def invalidate_cache() -> None:
    """Drop every cached factor (called whenever the rules change)."""
    with _cache_lock:
        _cache.clear()


def register_quantity(qid: str, label: str, description: str) -> None:
    """Register or replace a quantity by its stable ID (e.g. from on_load)."""
    _quantities[qid] = {'id': qid, 'label': label, 'description': description}


def quantities() -> list[dict]:
    """Return independent registry entries in registration order."""
    return [dict(entry) for entry in _quantities.values()]


def clamp_factor(value: object) -> float:
    """Normalize a single rule multiplier; invalid values are neutral."""
    try:
        number = float(value) if not isinstance(value, bool) else 1.0
    except (TypeError, ValueError, OverflowError):
        return 1.0
    return min(5.0, max(0.1, number)) if math.isfinite(number) else 1.0


def modify_rules() -> list[dict]:
    """The merged modify rules — load once when asking about many characters."""
    from app.models.rules import load_rules
    return [rule for rule in load_rules() if rule.get('type') == 'modify']


def factor(name: str, qid: str, *, profile: dict | None = None,
           rules: list[dict] | None = None) -> float:
    """Multiply matching rules, reading the merged rules exactly once.

    Conditions use the authoritative activity evaluator and current location
    and room. A comparison on a value the character does not have is not met
    (a modifier never fires on a missing stat). The optional profile matches
    consumer APIs; ``rules`` lets a caller reuse one ``modify_rules()`` load.
    """
    key = (name, qid)
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
    if hit is not None and hit[0] > now:
        return hit[1]
    from app.models.character import get_character_current_location, get_character_current_room
    from app.core.activity_engine import evaluate_condition, missing_stats_fail

    result = 1.0
    context = None
    for rule in (modify_rules() if rules is None else rules):
        if rule.get('type') != 'modify':
            continue
        modifier = rule.get('modify') or {}
        if modifier.get('quantity') != qid:
            continue
        character = (rule.get('character') or '').strip()
        if character and character != name:
            continue
        condition = rule.get('condition') or ''
        if condition:
            if context is None:
                context = (get_character_current_location(name) or '',
                           get_character_current_room(name) or '')
            with missing_stats_fail():
                passed = evaluate_condition(condition, name, *context)[0]
            if not passed:
                continue
        result *= clamp_factor(modifier.get('factor', 1))
    with _cache_lock:
        _cache[key] = (now + _CACHE_TTL_S, result)
    return result


register_quantity('travel_speed', 'Travel speed', 'Walking speed at journey start; a party uses its slowest member.')
register_quantity('discovery', 'Discovery', 'Item discovery value and outdoor discovery range.')
register_quantity('spell_success', 'Spell success', 'Spell success chance, capped at 100%.')
register_quantity('thought_frequency', 'Thought frequency', 'Relative weight of regular autonomous thought turns.')
