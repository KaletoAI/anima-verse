"""Effective stat values derived from base stats and timed state boosts."""
from app.core.game_time import GameTime
from app.core.timeutils import game_time


def active_boosts(profile: dict, *, now: GameTime | None = None) -> dict[str, list[dict]]:
    """Collect boosts from enabled, unexpired active condition entries.

    Expiry matches condition cleanup: strictly beyond the duration expires;
    an unreadable start remains active. No expression-triggered state boosts.
    """
    conditions = profile.get('active_conditions') or []
    if not conditions:
        return {}
    from app.core.prompt_filters import load_filters
    definitions = {f['id'].strip().lower(): f for f in load_filters()
                   if f.get('enabled', True)}
    now = now if now is not None else game_time()
    result: dict[str, list[dict]] = {}
    for entry in conditions:
        if not isinstance(entry, dict):
            continue
        state = definitions.get((entry.get('name') or '').strip().lower())
        if not state or not state.get('stat_boosts'):
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
        for key, amount in state['stat_boosts'].items():
            result.setdefault(key, []).append({
                'condition': state['id'], 'label': state.get('label') or state['id'],
                'amount': amount, 'remaining_hours': remaining})
    return result


def effective_stat(profile: dict, key: str) -> int | None:
    """Return a stat's base plus active boosts, floored at zero, or None."""
    status = profile.get('status_effects') or {}
    if key not in status:
        return None
    boosts = active_boosts(profile).get(key, [])
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
