"""Character fields an active STATE overrides (plan-intim-privatsphaere.md, part A).

A character-template field opts in with ``"state_override": true``
(``character_template.state_override_fields`` — a ``select`` stored in the
profile). A state (``prompt_filters``) names its overrides in
``field_overrides: {key: value}``, edited in Game-Admin → States next to the
stat boosts.

Which states count is the stat-boost rule (``stat_boosts.active_states``):
enabled, carried as a tag in ``active_conditions``, not expired. When two
active states set the same field, the one STARTED LATEST wins
(``started_at``, the canonical sortable game stamp; a row without a start
counts as the oldest); on a tie the alphabetically first state id wins. A
value the field does not (or no longer) offer is ignored, so a state saved
before an option was removed never yields an invalid value.

The core names no field here — every package can declare its own.
"""
from typing import Any, Dict, Optional, Tuple


def _fields() -> Dict[str, Dict[str, Any]]:
    from app.models.character_template import state_override_fields
    return {f["key"]: f for f in state_override_fields()}


def active_overrides(profile: dict, *, strict: bool = False,
                     fields: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Dict[str, Any]]:
    """``{key: {value, state, label, icon}}`` — the override in effect per
    field, for the fields some active state overrides."""
    from app.core.stat_boosts import active_states
    fields = _fields() if fields is None else fields
    candidates: Dict[str, list] = {}
    for state, entry, _remaining in active_states(profile, strict=strict):
        for key, value in (state.get("field_overrides") or {}).items():
            field = fields.get(key)
            if not field or str(value) not in {o["value"] for o in field["options"]}:
                continue
            sid = (state.get("id") or "").strip()
            candidates.setdefault(key, []).append((str(entry.get("started_at") or ""), sid, {
                "value": str(value), "state": sid,
                "label": state.get("label") or sid, "icon": state.get("icon") or ""}))
    # Sorted by id first: ``max`` returns the FIRST maximal start, so a tie
    # goes to the alphabetically first state id.
    return {key: max(sorted(rows, key=lambda r: r[1]), key=lambda r: r[0])[2]
            for key, rows in candidates.items()}


def effective_field(profile: dict, key: str, *,
                    strict: bool = False) -> Tuple[Any, Optional[Dict[str, Any]]]:
    """``(value, source)`` of an overridable field: the active override, else
    the stored value, else the template default. ``source`` is the override
    info of ``active_overrides`` or None when no state overrides the field.
    A key that is no overridable field yields the stored value unchanged."""
    fields = _fields()
    field = fields.get(key)
    if field:
        hit = active_overrides(profile, strict=strict, fields=fields).get(key)
        if hit:
            return hit["value"], hit
    stored = profile.get(key)
    if (stored is None or stored == "") and field:
        stored = field.get("default")
    return stored, None
