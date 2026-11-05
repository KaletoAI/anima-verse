"""Transform / revert — the trigger of a persona.

``transform`` sets the ``is_transformed`` flag, applies the persona's
condition, strikes the transform activity, records the active row and tells
the present knowers. ``revert`` undoes it in reverse and starts the cooldown.
``tick`` (the ``world_tick`` hook) ends transformations whose GAME-time
duration ran out or whose bearer no longer holds the power item. The worn
outfit is not touched.

Locks: one ``keyed_lock("transformation", bearer)`` spans a whole transform or
revert (two of them for the same bearer never interleave); inside it the
profile part runs under ``keyed_lock("character_profile", bearer)``. The pose
setters take the places lock, which comes BEFORE the profile lock, so they run
after the profile lock is released. No LLM or HTTP call happens under either.

The active row's ``snapshot`` holds everything a revert needs even when the
persona was edited or removed meanwhile: ``condition_id`` and ``alias`` (as
applied) and ``pose_key`` (the catalog key the transform activity resolved
to; the pose is cleared on revert only while it is still that one).
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict, Optional

from app.core.effect_application import apply_character_effects
from app.core.game_time import GameDuration, GameTime
from app.core.keyed_lock import keyed_lock
from app.core.log import get_logger
from app.core.perception import addressable_for, record_private_line
from app.core.pose_catalog import PairPoseWithoutPartner
from app.core.prompt_templates import render
from app.core.timeutils import game_time
from app.models.character import (clear_pose_intent, get_character_current_location,
                                  get_character_current_room, get_character_profile,
                                  list_available_characters, set_pose_intent,
                                  set_state_flag)
from app.models.inventory import get_carried_item_ids

from plugins.transformation import definitions, knowers, store
from plugins.transformation.definitions import Definition
from plugins.transformation.store import ActiveRow

logger = get_logger("transformation")

FLAG = "is_transformed"
SOURCE = "transformation"
REVERT_REASONS = ("verb", "phrase", "expired", "item_lost", "admin")

TransformResult = Dict[str, Any]


def _result(ok: bool, reason: str = "", alias: str = "") -> TransformResult:
    return {"ok": ok, "reason": reason, "alias": alias}


def _condition(bearer: str, condition_id: str, add: bool) -> None:
    if not condition_id:
        return
    effect: Dict[str, Any] = {"id": "transform", "condition_id": condition_id}
    if add:
        # duration 0 = never expires on its own; revert removes it.
        effect.update(type="condition_add", duration_game_s=0, source=SOURCE)
    else:
        effect.update(type="condition_remove")
    apply_character_effects(bearer, [effect], game_time(), source=SOURCE)


def _restore(bearer: str, snapshot: Dict[str, Any]) -> None:
    """Undo the profile part of a transform. Caller holds the profile lock."""
    set_state_flag(bearer, FLAG, False)
    _condition(bearer, str(snapshot.get("condition_id") or ""), add=False)


def _narrate(bearer: str, persona_id: str, alias: str, template: str,
             *, source: str, reason: str = "") -> None:
    """A narrator line for the bearer and the present knowers only."""
    present = [n for n in addressable_for(bearer) if knowers.knows(n, bearer, persona_id)]
    meta = {"transformation": template, "persona_id": persona_id}
    if reason:
        meta["reason"] = reason
    try:
        content = render(f"transformation/narration_{template}.md", bearer=bearer, alias=alias)
    except Exception as e:  # noqa: BLE001 — a missing line must not undo the act
        logger.warning("transformation narration %s for %s failed: %s", template, bearer, e)
        return
    record_private_line(recipients=[bearer, *present], content=content,
                        location_id=get_character_current_location(bearer),
                        room_id=get_character_current_room(bearer),
                        source=f"{SOURCE}:{source}", perception_meta=meta)


def _strike_activity(bearer: str, activity: str) -> str:
    """Set the transform activity; the catalog key it resolved to, or ``""``."""
    if not activity:
        return ""
    try:
        if not set_pose_intent(bearer, activity):
            return ""
    except PairPoseWithoutPartner:
        return ""
    except Exception as e:  # noqa: BLE001 — the transformation stands without it
        logger.warning("transform activity for %s not set: %s", bearer, e)
        return ""
    return str(get_character_profile(bearer).get("pose_key") or "")


def transform(bearer: str, persona_id: str, *, source: str,
              ignore_cooldown: bool = False) -> TransformResult:
    """Transform ``bearer`` into persona ``persona_id``.

    Returns ``{"ok", "reason", "alias"}``; reasons on refusal:
    ``unknown_persona``, ``not_holding_item``, ``already_transformed``,
    ``cooldown``. ``source`` (verb, phrase, admin, ...) goes into the log and
    the narration's meta. ``ignore_cooldown``: a running cooldown does not
    refuse (the admin's "Transform now"); the in-game paths keep it. An
    unexpected error undoes the partial profile changes and propagates.
    """
    d: Optional[Definition] = definitions.load().get(persona_id)
    if d is None or not bearer:
        return _result(False, "unknown_persona")
    with keyed_lock("transformation", bearer):
        if d.item_id not in get_carried_item_ids(bearer):
            return _result(False, "not_holding_item", d.alias)
        if store.get_active(bearer) is not None:
            return _result(False, "already_transformed", d.alias)
        now = game_time()
        cooldown = "" if ignore_cooldown else store.cooldown_until(bearer, d.id)
        if cooldown:
            try:
                if now < GameTime.parse(cooldown):
                    return _result(False, "cooldown", d.alias)
            except ValueError:
                logger.warning("unusable cooldown stamp %r for %s/%s — ignored",
                               cooldown, bearer, d.id)

        snapshot: Dict[str, Any] = {"condition_id": d.condition_id, "alias": d.alias,
                                    "pose_key": ""}
        with keyed_lock("character_profile", bearer):
            try:
                set_state_flag(bearer, FLAG, True)
                _condition(bearer, d.condition_id, add=True)
            except Exception:
                logger.exception("transform of %s into %s failed — undoing", bearer, d.id)
                _restore(bearer, snapshot)
                raise

        until = ""
        if d.max_duration_minutes > 0:
            until = (now + GameDuration.of(minutes=d.max_duration_minutes)).canonical()
        row = ActiveRow(bearer=bearer, persona_id=d.id, started_game=now.canonical(),
                        until_game=until, snapshot=snapshot)
        try:
            store.set_active(row)
        except Exception:
            logger.exception("transform of %s into %s not recorded — undoing", bearer, d.id)
            with keyed_lock("character_profile", bearer):
                _restore(bearer, snapshot)
            raise
        pose_key = _strike_activity(bearer, d.transform_activity)
        if pose_key:
            store.set_active(replace(row, snapshot={**snapshot, "pose_key": pose_key}))
        logger.info("%s transforms into %s (%s, source=%s, until=%s)",
                    bearer, d.alias, d.id, source, until or "revert")
        _narrate(bearer, d.id, d.alias, "transform", source=source)
    return _result(True, "", d.alias)


def revert(bearer: str, *, reason: str) -> bool:
    """End ``bearer``'s transformation. False when there is none.

    ``reason``: one of ``REVERT_REASONS`` (log + narration meta). Clears the
    flag and the condition, clears the transform activity if it is still the
    current pose, starts the cooldown (GAME time) and tells the present
    knowers.
    """
    if reason not in REVERT_REASONS:
        logger.warning("revert of %s with unknown reason %r", bearer, reason)
    with keyed_lock("transformation", bearer):
        row = store.get_active(bearer)
        if row is None:
            return False
        d = definitions.load().get(row.persona_id)
        snapshot = dict(row.snapshot or {})
        now = game_time()
        with keyed_lock("character_profile", bearer):
            _restore(bearer, snapshot)
            pose_key = str(snapshot.get("pose_key") or "")
            pose_now = str(get_character_profile(bearer).get("pose_key") or "")
        store.clear_active(bearer)
        if d is not None and d.cooldown_minutes > 0:
            store.set_cooldown(bearer, row.persona_id,
                               (now + GameDuration.of(minutes=d.cooldown_minutes)).canonical())
        if pose_key and pose_now == pose_key:
            try:
                clear_pose_intent(bearer)
            except Exception as e:  # noqa: BLE001 — the revert stands without it
                logger.warning("transform activity of %s not cleared: %s", bearer, e)
        alias = str(snapshot.get("alias") or (d.alias if d else ""))
        logger.info("%s turns back from %s (%s, reason=%s)", bearer, alias, row.persona_id, reason)
        if alias:
            _narrate(bearer, row.persona_id, alias, "revert", source=reason, reason=reason)
    return True


def tick() -> None:
    """``world_tick``: end what ran out or lost its item; seed holders' secrets.

    A row ends ``expired`` once ``game_time() >= until_game``, ``item_lost``
    when its bearer no longer carries the power item or the persona is no
    longer configured. Every current holder of a persona's item gets the
    knower secret, so knowers can be edited before the first transform.
    """
    defs = definitions.load()
    now = game_time()
    for row in store.all_active():
        try:
            d = defs.get(row.persona_id)
            if row.until_game and now >= GameTime.parse(row.until_game):
                revert(row.bearer, reason="expired")
            elif d is None or d.item_id not in get_carried_item_ids(row.bearer):
                revert(row.bearer, reason="item_lost")
        except Exception:
            logger.exception("transformation tick for %s failed", row.bearer)
    if not defs:
        return
    by_item: Dict[str, Definition] = {}
    for d in defs.values():
        by_item.setdefault(d.item_id, d)
    for name in list_available_characters():
        for iid in get_carried_item_ids(name) & by_item.keys():
            try:
                knowers.ensure_secret(name, by_item[iid])
            except Exception:
                logger.exception("transformation secret for %s failed", name)
