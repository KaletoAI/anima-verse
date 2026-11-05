"""Transform / revert — a body swap between a leader and one of its linked
characters (``app.core.linked_characters``).

``transform(leader, def_id)`` checks that the definition is the leader's, the
leader holds the power item, no transformation runs, the cooldown (the
admin's "Transform now" ignores it) and that the body is linked to the leader;
then ``swap_presence(leader, body, items=[item_id])`` — refused in a swap
refusal state — puts the body exactly where the leader stood and moves the
item to it. Afterwards the condition goes onto the BODY, the state flag
``is_transformed`` is set on it, the transform activity is struck, the active
row is recorded and the present knowers are told.

``revert(leader, reason=...)`` swaps back (``swap_presence(body, leader,
items=[item_id])``). The in-game paths (verb, phrase) need the item on the
body; the automatic ones (``expired``, ``disabled``, ``item_lost``) and the admin's
"Revert now" do not. A refused swap leaves everything as it is and answers
the refusal — ``tick`` retries it on every following tick, never forcing it.
After a revert the condition and flag leave the body, the transform activity
is cleared on the leader if the swap carried it back, and the leader's
cooldown starts.

``tick`` (the ``world_tick`` hook) reverts what ran out (``expired``), a
transformation whose definition was switched off or removed (``disabled``)
and a body that no longer holds the power item (``item_lost``, wherever it
stands).

Locks: one ``keyed_lock("transformation", leader)`` spans a whole transform or
revert. ``swap_presence`` takes the family, places and profile locks itself,
so no profile lock is held around it; the profile part (flag) runs under
``keyed_lock("character_profile", body)`` afterwards. No LLM or HTTP call
happens under either.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from app.core.effect_application import apply_character_effects
from app.core.game_time import GameDuration, GameTime
from app.core.keyed_lock import keyed_lock
from app.core.linked_characters import leader_of, swap_presence
from app.core.log import get_logger
from app.core.perception import addressable_for, record_private_line
from app.core.pose_catalog import PairPoseWithoutPartner
from app.core.prompt_templates import render
from app.core.timeutils import game_time
from app.models.character import (DORMANT_STATUS, clear_pose_intent,
                                  get_character_current_location, get_character_current_room,
                                  get_character_profile, get_character_status, set_pose_intent,
                                  set_state_flag)
from app.models.inventory import get_carried_item_ids

from plugins.transformation import definitions, knowers, store
from plugins.transformation.definitions import Definition
from plugins.transformation.store import ActiveRow

logger = get_logger("transformation")

FLAG = "is_transformed"
SOURCE = "transformation"
REVERT_REASONS = ("verb", "phrase", "expired", "item_lost", "disabled", "admin")
#: Revert reasons that need the power item on the body.
_ITEM_NEEDED = ("verb", "phrase")

Result = Dict[str, Any]

#: (leader, refusal) of the last refused automatic revert — logged once.
_refused_logged: Dict[str, str] = {}


def _result(ok: bool, reason: str = "", *, body: str = "", error: str = "",
            refusal: str = "") -> Result:
    out: Result = {"ok": ok, "reason": reason, "body": body, "error": error}
    if refusal:
        out["refusal"] = refusal
    return out


def _condition(name: str, condition_id: str, add: bool) -> None:
    if not condition_id:
        return
    effect: Dict[str, Any] = {"id": "transform", "condition_id": condition_id}
    if add:
        # duration 0 = never expires on its own; revert removes it.
        effect.update(type="condition_add", duration_game_s=0, source=SOURCE)
    else:
        effect.update(type="condition_remove")
    apply_character_effects(name, [effect], game_time(), source=SOURCE)


def _narrate(present: str, body: str, leader: str, template: str,
             *, source: str, def_id: str, reason: str = "") -> None:
    """A narrator line for the character now present and the present knowers."""
    others = [n for n in addressable_for(present) if knowers.knows(n, body)]
    meta = {"transformation": template, "def_id": def_id}
    if reason:
        meta["reason"] = reason
    try:
        content = render(f"transformation/narration_{template}.md", leader=leader, body=body)
    except Exception as e:  # noqa: BLE001 — a missing line must not undo the act
        logger.warning("transformation narration %s for %s failed: %s", template, leader, e)
        return
    record_private_line(recipients=[present, *others], content=content,
                        location_id=get_character_current_location(present),
                        room_id=get_character_current_room(present),
                        source=f"{SOURCE}:{source}", perception_meta=meta)


def _strike_activity(name: str, activity: str) -> str:
    """Set the transform activity; the catalog key it resolved to, or ``""``."""
    if not activity:
        return ""
    try:
        if not set_pose_intent(name, activity):
            return ""
    except PairPoseWithoutPartner:
        return ""
    except Exception as e:  # noqa: BLE001 — the transformation stands without it
        logger.warning("transform activity for %s not set: %s", name, e)
        return ""
    return str(get_character_profile(name).get("pose_key") or "")


def _cooldown_running(leader: str, def_id: str, now: GameTime) -> bool:
    stamp = store.cooldown_until(leader, def_id)
    if not stamp:
        return False
    try:
        return now < GameTime.parse(stamp)
    except ValueError:
        logger.warning("unusable cooldown stamp %r for %s/%s — ignored", stamp, leader, def_id)
        return False


def transform(leader: str, def_id: str, *, source: str,
              ignore_cooldown: bool = False) -> Result:
    """Turn ``leader`` into the body of definition ``def_id``.

    Returns ``{"ok", "reason", "body", "error"}`` (+ ``"refusal"`` = the swap
    refusal code). Reasons on refusal: ``unknown_definition`` (none, disabled,
    or not ``leader``'s), ``already_transformed``, ``not_holding_item``,
    ``cooldown``, ``body_not_linked``, ``refused`` (a swap refusal state —
    ``error`` is its text), ``failed`` (the swap failed otherwise — ``error``).
    ``source`` (verb, phrase, admin, ...) goes into the log and the
    narration's meta. ``ignore_cooldown``: the admin's "Transform now".
    """
    d: Optional[Definition] = definitions.load().get(def_id)
    if d is None or not leader or d.leader != leader:
        return _result(False, "unknown_definition")
    with keyed_lock("transformation", leader):
        if store.get_active(leader) is not None:
            return _result(False, "already_transformed", body=d.body)
        if d.item_id not in get_carried_item_ids(leader):
            return _result(False, "not_holding_item", body=d.body)
        now = game_time()
        if not ignore_cooldown and _cooldown_running(leader, d.id, now):
            return _result(False, "cooldown", body=d.body)
        if leader_of(d.body) != leader:
            return _result(False, "body_not_linked", body=d.body)
        swap = swap_presence(leader, d.body, items=[d.item_id],
                             reason=f"transformation {d.id} ({source})")
        if not swap.get("ok"):
            refusal = str(swap.get("refusal") or "")
            return _result(False, "refused" if refusal else "failed", body=d.body,
                           error=str(swap.get("error") or ""), refusal=refusal)

        until = ""
        if d.max_duration_minutes > 0:
            until = (now + GameDuration.of(minutes=d.max_duration_minutes)).canonical()
        snapshot: Dict[str, Any] = {"item_id": d.item_id, "condition_id": d.condition_id,
                                    "pose_key": ""}
        row = ActiveRow(leader=leader, body=d.body, def_id=d.id, started_game=now.canonical(),
                        until_game=until, snapshot=snapshot)
        store.set_active(row)
        with keyed_lock("character_profile", d.body):
            set_state_flag(d.body, FLAG, True)
        try:
            _condition(d.body, d.condition_id, add=True)
        except Exception as e:  # noqa: BLE001 — the swap stands without its condition
            logger.error("condition %s on %s not applied: %s", d.condition_id, d.body, e)
        pose_key = _strike_activity(d.body, d.transform_activity)
        if pose_key:
            store.set_active(ActiveRow(leader=leader, body=d.body, def_id=d.id,
                                       started_game=row.started_game, until_game=until,
                                       snapshot={**snapshot, "pose_key": pose_key}))
        logger.info("%s transforms into %s (%s, source=%s, until=%s)",
                    leader, d.body, d.id, source, until or "revert")
        _narrate(d.body, d.body, leader, "transform", source=source, def_id=d.id)
    return _result(True, "", body=d.body)


def _finish(row: ActiveRow, now: GameTime, *, reason: str) -> None:
    """After the swap back: the body's condition and flag go, the leader's
    transform activity is cleared when the swap carried it back, the cooldown
    starts, the active row goes."""
    snapshot = dict(row.snapshot or {})
    try:
        _condition(row.body, str(snapshot.get("condition_id") or ""), add=False)
    except Exception as e:  # noqa: BLE001
        logger.error("condition of %s not removed: %s", row.body, e)
    with keyed_lock("character_profile", row.body):
        set_state_flag(row.body, FLAG, False)
    pose_key = str(snapshot.get("pose_key") or "")
    if pose_key and str(get_character_profile(row.leader).get("pose_key") or "") == pose_key:
        try:
            clear_pose_intent(row.leader)
        except Exception as e:  # noqa: BLE001 — the revert stands without it
            logger.warning("transform activity of %s not cleared: %s", row.leader, e)
    store.clear_active(row.leader)
    d = store.get_definition(row.def_id)
    minutes = int((d or {}).get("cooldown_minutes") or 0)
    if minutes > 0:
        store.set_cooldown(row.leader, row.def_id,
                           (now + GameDuration.of(minutes=minutes)).canonical())


def revert(leader: str, *, reason: str) -> Result:
    """End ``leader``'s transformation — ``{"ok", "reason", "error"}``
    (+ ``"refusal"``).

    ``reason``: one of ``REVERT_REASONS`` (log + narration meta). Refusals:
    ``not_transformed``; ``not_holding_item`` (verb/phrase only: the body must
    carry the power item); ``refused`` (the body is in a swap refusal state —
    ``error`` is its text; nothing changes, ``tick`` retries an automatic
    revert); ``failed`` (the swap failed otherwise). A family whose leader
    already stands in the world again (the body dormant) is only cleaned up.
    """
    if reason not in REVERT_REASONS:
        logger.warning("revert of %s with unknown reason %r", leader, reason)
    with keyed_lock("transformation", leader):
        row = store.get_active(leader)
        if row is None:
            return {"ok": False, "reason": "not_transformed", "error": ""}
        item_id = str((row.snapshot or {}).get("item_id") or "")
        now = game_time()
        already_back = (get_character_status(row.body) == DORMANT_STATUS
                        and get_character_status(leader) != DORMANT_STATUS)
        if not already_back:
            if reason in _ITEM_NEEDED and item_id not in get_carried_item_ids(row.body):
                return {"ok": False, "reason": "not_holding_item", "error": ""}
            swap = swap_presence(row.body, leader, items=[item_id] if item_id else [],
                                 reason=f"transformation {row.def_id} revert ({reason})")
            if not swap.get("ok"):
                refusal = str(swap.get("refusal") or "")
                out = {"ok": False, "reason": "refused" if refusal else "failed",
                       "error": str(swap.get("error") or "")}
                if refusal:
                    out["refusal"] = refusal
                return out
        else:
            logger.warning("revert of %s: %s is dormant already — cleaning up only",
                           leader, row.body)
        _finish(row, now, reason=reason)
        _refused_logged.pop(leader, None)
        logger.info("%s turns back into %s (%s, reason=%s)", row.body, leader, row.def_id, reason)
        if not already_back:
            _narrate(leader, row.body, leader, "revert", source=reason, def_id=row.def_id,
                     reason=reason)
    return {"ok": True, "reason": "", "error": ""}


def _due(row: ActiveRow, now: GameTime) -> Tuple[bool, str]:
    """Whether ``row`` ends now, and why (``expired`` / ``disabled`` /
    ``item_lost``)."""
    if row.until_game:
        try:
            if now >= GameTime.parse(row.until_game):
                return True, "expired"
        except ValueError:
            logger.warning("unusable until stamp %r for %s — ignored", row.until_game, row.leader)
    d = store.get_definition(row.def_id)
    if d is None or not d.get("enabled"):
        return True, "disabled"
    item_id = str((row.snapshot or {}).get("item_id") or "")
    if item_id and item_id not in get_carried_item_ids(row.body):
        return True, "item_lost"
    return False, ""


def tick() -> None:
    """``world_tick``: end what ran out, was switched off, or whose body lost
    the power item.

    A refused revert (the body is travelling, asleep, busy, ...) stays as it
    is and is tried again on the next tick — never forced. The refusal is
    logged once per leader and refusal code.
    """
    now = game_time()
    for row in store.all_active():
        try:
            due, why = _due(row, now)
            if not due:
                continue
            res = revert(row.leader, reason=why)
            if not res.get("ok"):
                code = str(res.get("refusal") or res.get("reason") or "")
                if _refused_logged.get(row.leader) != code:
                    _refused_logged[row.leader] = code
                    logger.info("%s cannot turn back into %s yet (%s: %s) — retried next tick",
                                row.body, row.leader, code, res.get("error") or "")
        except Exception:
            logger.exception("transformation tick for %s failed", row.leader)


def expected_present(leader: str) -> Optional[str]:
    """``linked.expected_present``: the body while a transformation runs."""
    row = store.get_active(leader)
    return row.body if row is not None else None
