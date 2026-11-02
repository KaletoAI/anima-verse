"""Effective stat values derived from base stats, timed state boosts and passive items."""
from app.core.game_time import GameTime
from app.core.timeutils import game_time


def _item_boosts(profile: dict, *, strict: bool = False) -> dict[str, list[dict]]:
    """Use profile equipment and cached definitions; only carried mode reads inventory."""
    from app.core.motion_item_cache import passive_bonus_snapshot
    from app.models.inventory import get_carried_item_ids
    definitions, carried_ids = passive_bonus_snapshot(strict=strict)
    equipped = set(profile.get('equipped_items') or [])
    equipped.update((profile.get('equipped_pieces') or {}).values())
    eligible = {iid for iid in equipped if
                (definitions.get(iid, {}).get('properties') or {}).get('bonus_when', 'equipped') == 'equipped'}
    name = profile.get('character_name')
    if carried_ids and name:
        eligible.update(get_carried_item_ids(name) & carried_ids)
    result: dict[str, list[dict]] = {}
    for iid in sorted(eligible):
        item = definitions.get(iid)
        if not item:
            continue
        for key, amount in ((item.get('properties') or {}).get('stat_bonuses') or {}).items():
            result.setdefault(key, []).append({
                'condition': iid, 'label': item.get('name') or iid,
                'amount': amount, 'remaining_hours': 0.0, 'source': 'item'})
    return result


def active_states(profile: dict, *, now: GameTime | None = None,
                  strict: bool = False):
    """Yield ``(state, entry, remaining_hours)`` for every enabled, unexpired
    condition the profile carries in ``active_conditions``.

    ``state`` is the state definition (``prompt_filters``), ``entry`` the
    profile's condition row. Expiry matches condition cleanup: strictly beyond
    the duration expires; an unreadable start remains active. A state that
    fires only through its ``condition`` expression is not listed — what a
    state CHANGES (stat boosts, field overrides) needs the tag on the profile.
    The one loop both stat boosts and ``field_overrides`` read, so the two can
    never disagree about which states are active.
    """
    conditions = profile.get('active_conditions') or []
    if not conditions:
        return
    from app.core.prompt_filters import load_filters
    definitions = {f['id'].strip().lower(): f for f in load_filters(strict=strict)
                   if f.get('enabled', True)}
    if now is None:
        now = game_time(strict=True) if strict else game_time()
    for entry in conditions:
        if not isinstance(entry, dict):
            continue
        state = definitions.get((entry.get('name') or '').strip().lower())
        if not state:
            continue
        duration = entry.get('duration_hours', 0)
        remaining = 0.0
        if duration:
            try:
                elapsed = (now - GameTime.parse(entry['started_at'])).hours
                if elapsed > float(duration):
                    continue
                remaining = max(0.0, float(duration) - elapsed)
            except (ValueError, KeyError, TypeError):
                try:
                    remaining = max(0.0, float(duration))
                except (ValueError, TypeError):
                    pass
        yield state, entry, remaining


def active_boosts(profile: dict, *, now: GameTime | None = None,
                  strict: bool = False) -> dict[str, list[dict]]:
    """Collect passive item boosts and the boosts of the active states
    (``active_states``). No expression-triggered state boosts."""
    result = _item_boosts(profile, strict=strict)
    for state, _entry, remaining in active_states(profile, now=now, strict=strict):
        for key, amount in (state.get('stat_boosts') or {}).items():
            result.setdefault(key, []).append({
                'condition': state['id'], 'label': state.get('label') or state['id'],
                'amount': amount, 'remaining_hours': remaining})
    return result


def effective_stat(profile: dict, key: str, *, strict: bool = False) -> int | None:
    """Return a stat's base plus active boosts, floored at zero, or None."""
    status = profile.get('status_effects') or {}
    if key not in status:
        return None
    boosts = active_boosts(profile, strict=strict).get(key, [])
    return max(0, int(status[key]) + sum(b['amount'] for b in boosts))


def effective_stats(profile: dict) -> dict[str, dict]:
    """Describe every base stat with its total boost and effective value."""
    boosts = active_boosts(profile)
    result = {}
    for key, raw in (profile.get('status_effects') or {}).items():
        base = int(raw)
        entries = boosts.get(key, [])
        boost = sum(b['amount'] for b in entries)
        result[key] = dict(base=base, boost=boost, value=max(0, base + boost), boosts=entries)
    return result
