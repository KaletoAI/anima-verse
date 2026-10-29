"""Deterministic profile effects and the prop executor's same-connection adapter.

The pure transformation does no catalog, clock or storage I/O. Adapters resolve
real definitions first. Lock order is execution -> sorted profiles -> DB write;
no separately committing character save helper is called inside a transaction.
"""
from copy import deepcopy
import math

from app.core.game_time import GameTime
from app.core.stat_rules import round_half_away


def merge_changes(aggregate: dict, changes: dict) -> None:
    """Retain the first old value and the last new value across effects/phases."""
    for key, change in changes.items():
        aggregate[key] = dict(change, old=aggregate.get(key, change)['old'])


def _expired(entry: dict, now: GameTime) -> bool:
    duration = entry.get('duration_hours', 0)
    if duration:
        try:
            return (now - GameTime.parse(entry['started_at'])).hours > float(duration)
        except (ValueError, KeyError, TypeError):
            pass  # Same policy as existing cleanup/boost readers: keep bad stamps.
    return False


def apply_effects_to_profile(profile: dict, effects: list[dict], now: GameTime) -> dict:
    """Return {profile, changes, results}, leaving the input untouched.

    Numeric writes only touch readable, already present actor stats (0..100).
    Conditions use the existing active_conditions representation; ignore never
    refreshes, refresh replaces one entry and never stacks a second boost.
    Definition/reference validation belongs to the I/O adapter.
    """
    result = deepcopy(profile)
    status = result.setdefault('status_effects', {})
    changes, results = {}, {}
    for effect in effects:
        typ = effect['type']
        row = dict(type=typ, applied=False)
        if typ == 'stat_delta':
            key = effect['stat']
            old = status.get(key)
            amount = effect['amount']
            if (isinstance(old, (int, float)) and not isinstance(old, bool) and math.isfinite(old)
                    and isinstance(amount, (int, float)) and not isinstance(amount, bool) and math.isfinite(amount)):
                new = max(0, min(100, old + round_half_away(amount)))
                status[key] = new
                row.update(stat=key, old=old, new=new, delta=new - old, applied=new != old)
                if new != old:
                    changes[key] = dict(old=changes.get(key, {}).get('old', old), new=new)
            else:
                row.update(stat=key, delta=0, reason='missing_character_stat')
        elif typ == 'mood':
            old = result.get('current_feeling', '')
            result['current_feeling'] = effect['mood']
            row.update(old=old, new=effect['mood'], applied=old != effect['mood'])
        elif typ in ('condition_add', 'condition_remove'):
            name = effect['condition_id']
            active = result.setdefault('active_conditions', [])
            matches = [entry for entry in active if isinstance(entry, dict) and entry.get('name') == name]
            live = [entry for entry in matches if not _expired(entry, now)]
            if typ == 'condition_remove':
                result['active_conditions'] = [entry for entry in active if entry not in matches]
                row.update(condition_id=name, applied=bool(matches), removed=len(matches))
            elif not live or effect.get('repeat', 'refresh') == 'refresh':
                entry = dict(name=name, source=effect.get('source', ''),
                             source_character=effect.get('source_character', ''),
                             started_at=now.canonical(), duration_hours=effect['duration_game_s'] / 3600)
                result['active_conditions'] = [entry for entry in active if entry not in matches] + [entry]
                row.update(condition_id=name, applied=True, refreshed=bool(live), **entry)
            else:
                row.update(condition_id=name, reason='repeat_ignored')
        else:
            raise ValueError('unsupported_effect_type')
        results[effect['id']] = row
    return dict(profile=result, changes=changes, results=results)


def effect_catalogs() -> dict:
    """Resolve definitions before entering profile locks / a DB write span."""
    from app.core.prompt_filters import load_filters
    from app.core.stat_rules import template_rules
    from app.models.character_template import list_templates, get_template
    return dict(conditions={f['id'] for f in load_filters() if f.get('enabled', True)},
                templates={entry['name']: set(template_rules(get_template(entry['name']) or {}))
                           for entry in list_templates()})


def validate_profile_effects(profile, effects, catalogs):
    for effect in effects:
        if effect['type'] == 'stat_delta':
            key = effect['stat']
            if key not in catalogs['templates'].get(profile.get('template', ''), set()):
                return 'unknown_stat'
            value = (profile.get('status_effects') or {}).get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                return 'missing_character_stat'
        elif effect['type'] in ('condition_add', 'condition_remove'):
            if effect['condition_id'] not in catalogs['conditions']:
                return 'unknown_condition'
    return ''


def legacy_effects(effects: dict, *, source="", include_condition=False, giver="") -> list[dict]:
    """Translate existing activity/item fields without changing item repeat rules."""
    result = []
    for key, amount in effects.items():
        if key.endswith("_change") and amount:
            try:
                delta = int(amount)
            except (ValueError, TypeError, OverflowError):
                continue
            result.append(dict(id=key, type="stat_delta", stat=key[:-7], amount=delta, source=source))
    if effects.get("mood_influence"):
        result.append(dict(id="mood", type="mood", mood=effects["mood_influence"], source=source))
    name = str(effects.get("apply_condition") or "").strip()
    if include_condition and name:
        try:
            duration = max(1, int(effects.get("condition_duration_hours") or 2))
        except (TypeError, ValueError, OverflowError) as exc:
            from app.core.log import get_logger
            get_logger("effect_application").warning(
                "Condition-Apply fuer %s (%s) fehlgeschlagen: invalid condition_duration_hours: %s",
                source, name, exc)
        else:
            result.append(dict(id="condition", type="condition_add", condition_id=name,
                               duration_game_s=duration * 3600, repeat="ignore",
                               source=source, source_character=giver.strip()))
    return result


def notify_effects(changes, source):
    """Only called after the owning transaction commits and profile locks exit."""
    from app.core import sync_topics
    from app.core.keyed_lock import _after_locks
    from app.models.character import record_state_change
    def notify():
        for name, result in changes.items():
            if any(r.get('applied') for r in result['results'].values()):
                record_state_change(name, 'effects', source,
                                    metadata={'changes': result['changes'], 'effects': result['results'], 'source': source})
                sync_topics.changed_at(name, topics=('presence', 'self'))
    _after_locks(notify)


def apply_character_effects(name, effects, now, *, source=''):
    """Item/activity adapter: same pure logic, no change to repeat policy."""
    from app.core.keyed_lock import keyed_lock
    from app.core import prop_action_store as store
    from app.models import character as C
    catalogs = effect_catalogs()
    with keyed_lock('character_profile', name):
        with store.transaction() as conn:
            profile = C.read_effect_profile(conn, name)
            # Legacy item/danger deltas ignore unknown/missing actor stats, not
            # manufacture new values. Unknown conditions never become state text.
            valid = [effect for effect in effects if not validate_profile_effects(profile, [effect], catalogs)]
            result = apply_effects_to_profile(profile, valid, now)
            C.write_effect_profile(conn, name, result['profile'])
    notify_effects({name: result}, source)
    return result


def _active_amount(rate, seconds, previous):
    """Exact decimal-rate credit, bounded before conversion to actor units.

    Rational carry avoids tick-partition rounding loss. At most 100 whole
    points can affect a 0..100 stat; anything beyond that is spent, not banked.
    Even the largest accepted finite rate never passes through float overflow.
    """
    from fractions import Fraction
    fraction = previous.get("carry_fraction")
    carry = Fraction(*fraction) if fraction is not None else Fraction(str(previous.get("carry", 0)))
    earned = Fraction(str(rate)) * Fraction(str(seconds)) / 60 + carry
    if earned >= 100:
        return 100, Fraction(0)
    if earned <= -100:
        return -100, Fraction(0)
    whole = int(earned)
    return whole, earned - whole


def _apply_on_connection(conn, run, phase, now, profiles, catalogs):
    """Caller owns sorted profile locks AND this connection's transaction."""
    from app.core import prop_action_store as store
    from app.core.timeutils import utc_now_iso
    effects = [e for e in run['definition']['effects'] if e['when'] == phase]
    changed, outcomes = {}, {}
    for effect in effects:
        prior = conn.execute('SELECT result FROM prop_action_effect_receipts '
                             'WHERE execution_id=? AND effect_id=? AND phase=?',
                             (run['execution_id'], effect['id'], phase)).fetchone()
        import json
        receipt = json.loads(prior[0]) if prior else dict(targets={}, active_game_s=0)
        if prior and phase != 'active':
            outcomes[effect['id']] = receipt
            continue
        seconds = float(run['data'].get('active_game_s', 0))
        delta_s = max(0.0, seconds - receipt.get('active_game_s', 0)) if phase == 'active' else 0
        if prior and phase == 'active' and not delta_s:
            outcomes[effect['id']] = receipt
            continue
        names = [run['actor'], run['partner']] if effect['target'] == 'both' else [run[effect['target']]]
        for name in names:
            actual = dict(effect, source='prop_action:' + run['execution_id'])
            previous = receipt['targets'].get(name, {})
            from fractions import Fraction
            carry = Fraction(0)
            if phase == 'active':
                actual['amount'], carry = _active_amount(effect['amount'], delta_s, previous)
            reason = validate_profile_effects(profiles[name], [actual], catalogs)
            if reason:
                transformed = dict(profile=profiles[name], changes={}, results={
                    effect['id']: dict(type=effect['type'], applied=False, delta=0, reason=reason)})
            else:
                transformed = apply_effects_to_profile(profiles[name], [actual], now)
            profiles[name] = transformed['profile']
            applied = transformed['results'][effect['id']]
            if phase == 'active':
                # Whole capped overflow and a fractional credit pointing past
                # a cap are both spent, never banked for a later free refill.
                if (applied.get('delta') != actual['amount'] or
                        (applied.get('new') == 100 and carry > 0) or
                        (applied.get('new') == 0 and carry < 0)):
                    carry = Fraction(0)
                applied.update(carry=float(carry), carry_fraction=[carry.numerator, carry.denominator],
                               interval_delta=applied.get('delta', 0),
                               delta=previous.get('delta', 0) + applied.get('delta', 0),
                               old=previous.get('old', applied.get('old')))
            receipt['targets'][name] = applied
            aggregate = changed.setdefault(name, dict(changes={}, results={}))
            merge_changes(aggregate['changes'], transformed['changes'])
            aggregate['results'].update(transformed['results'])
        receipt['active_game_s'] = seconds if phase == 'active' else 0
        conn.execute('INSERT INTO prop_action_effect_receipts (execution_id,effect_id,phase,result,applied_at) VALUES (?,?,?,?,?) '
                     'ON CONFLICT(execution_id,effect_id,phase) DO UPDATE SET result=excluded.result,applied_at=excluded.applied_at',
                     (run['execution_id'], effect['id'], phase, store.encode(receipt), utc_now_iso()))
        outcomes[effect['id']] = receipt
    return dict(effects=outcomes, changed=changed)


def apply_execution_effects(execution_id: str, phase: str, now: GameTime, *,
                            conn=None, run=None, profiles=None, catalogs=None) -> dict:
    """Apply only an actual executor lifecycle signal, with durable receipts.

    Internal callers supply the transaction connection and freshly read locked
    profiles, then save run progress on that SAME connection. The public form
    serializes through the executor and cannot fabricate start/success signals.
    """
    if phase not in ('start', 'success', 'active'):
        raise ValueError('invalid_effect_phase')
    if conn is not None:
        if run is None or profiles is None or catalogs is None or run['execution_id'] != execution_id:
            raise ValueError('missing_effect_transaction_authority')
        return _apply_on_connection(conn, run, phase, now, profiles, catalogs)
    from app.core import prop_action_engine
    return prop_action_engine.apply_execution_effects(execution_id, phase, now)
