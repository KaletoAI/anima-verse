"""Transform / revert — the mechanics of wearing a persona.

``transform`` remembers the worn outfit, grants and puts on the suit, locks
the outfit, sets the ``is_transformed`` flag, applies the persona's condition,
strikes the transform activity, records the active row and tells the present
knowers. ``revert`` undoes all of it in reverse and starts the cooldown.
``tick`` (the ``world_tick`` hook) ends transformations whose GAME-time
duration ran out or whose bearer no longer holds the power item.

Locks: one ``keyed_lock("transformation", bearer)`` spans a whole transform or
revert (two of them for the same bearer never interleave); inside it the
profile part runs under ``keyed_lock("character_profile", bearer)``. The pose
setters take the places lock, which comes BEFORE the profile lock, so they run
after the profile lock is released. No LLM or HTTP call happens under either.

The active row's ``outfit_snapshot`` holds everything a revert needs even when
the persona was edited or removed meanwhile: ``pieces`` / ``items`` (the
outfit worn before), ``condition_id`` and ``alias`` (as applied) and
``pose_key`` (the catalog key the transform activity resolved to; the pose is
cleared on revert only while it is still that one).
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict, List, Optional

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
                                  is_outfit_locked, list_available_characters,
                                  set_outfit_locked, set_pose_intent, set_state_flag)
from app.models.inventory import (add_to_inventory, apply_equipped_pieces,
                                  get_carried_item_ids, get_item, remove_from_inventory)

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


def _piece_slots(item_id: str) -> Optional[List[str]]:
    """The slots of an outfit piece, ``None`` for any other item."""
    item = get_item(item_id)
    if not item or item.get("category") != "outfit_piece":
        return None
    raw = (item.get("outfit_piece") or {}).get("slots") or []
    return [str(s).strip().lower() for s in raw if str(s).strip()]


def _suit_outfit(snap_pieces: Dict[str, str], snap_items: List[str],
                 suit: tuple) -> tuple:
    """Target ``(pieces, items)``: the snapshot with the suit put over it.

    A snapshot piece is dropped as a whole when the suit covers ANY of its
    slots (a dress under a suit top must not keep the top slot), so the suit
    wins every slot it names. Suit pieces go in by their first slot;
    ``apply_equipped_pieces`` mirrors the rest. A suit item that is no outfit
    piece is worn as equipment next to the snapshot's.
    """
    covered: set = set()
    suit_pieces: Dict[str, str] = {}
    items = list(snap_items)
    for iid in suit:
        slots = _piece_slots(iid)
        if slots is None:
            if iid not in items:
                items.append(iid)
            continue
        if not slots:
            continue
        covered.update(slots)
        suit_pieces.setdefault(slots[0], iid)
    slots_of: Dict[str, set] = {}
    for slot, iid in snap_pieces.items():
        if iid:
            slots_of.setdefault(iid, set()).add(slot)
    pieces = {slot: iid for slot, iid in snap_pieces.items()
              if iid and not (slots_of[iid] & covered)}
    pieces.update(suit_pieces)
    return pieces, items


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


def _restore(bearer: str, snapshot: Dict[str, Any], granted: tuple,
             lock_before: bool) -> None:
    """Undo the profile part of a transform. Caller holds the profile lock.

    The outfit is restored FIRST: the granted suit pieces are still worn and
    would otherwise be taken out of an inventory that still equips them."""
    apply_equipped_pieces(bearer, pieces=dict(snapshot.get("pieces") or {}),
                          items=list(snapshot.get("items") or []),
                          source="transformation_revert")
    for iid in granted:
        remove_from_inventory(bearer, iid, force=True)
    set_outfit_locked(bearer, lock_before)
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


def transform(bearer: str, persona_id: str, *, source: str) -> TransformResult:
    """Transform ``bearer`` into persona ``persona_id``.

    Returns ``{"ok", "reason", "alias"}``; reasons on refusal:
    ``unknown_persona``, ``not_holding_item``, ``already_transformed``,
    ``cooldown``. ``source`` (verb, phrase, admin, ...) goes into the log and
    the narration's meta. An unexpected error undoes the partial profile
    changes and propagates.
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
        cooldown = store.cooldown_until(bearer, d.id)
        if cooldown:
            try:
                if now < GameTime.parse(cooldown):
                    return _result(False, "cooldown", d.alias)
            except ValueError:
                logger.warning("unusable cooldown stamp %r for %s/%s — ignored",
                               cooldown, bearer, d.id)

        with keyed_lock("character_profile", bearer):
            profile = get_character_profile(bearer)
            snapshot: Dict[str, Any] = {
                "pieces": dict(profile.get("equipped_pieces") or {}),
                "items": list(profile.get("equipped_items") or []),
                "condition_id": d.condition_id,
                "alias": d.alias,
                "pose_key": "",
            }
            lock_before = is_outfit_locked(bearer)
            granted: List[str] = []
            try:
                carried = get_carried_item_ids(bearer)
                for iid in d.suit_items:
                    if iid in carried or iid in granted:
                        continue
                    if add_to_inventory(bearer, iid, obtained_from=SOURCE, obtained_method="manual"):
                        granted.append(iid)
                    else:
                        logger.warning("suit item %s could not be granted to %s", iid, bearer)
                pieces, items = _suit_outfit(snapshot["pieces"], snapshot["items"], d.suit_items)
                apply_equipped_pieces(bearer, pieces=pieces, items=items, source=SOURCE)
                set_outfit_locked(bearer, True)
                set_state_flag(bearer, FLAG, True)
                _condition(bearer, d.condition_id, add=True)
            except Exception:
                logger.exception("transform of %s into %s failed — undoing", bearer, d.id)
                _restore(bearer, snapshot, tuple(granted), lock_before)
                raise

        until = ""
        if d.max_duration_minutes > 0:
            until = (now + GameDuration.of(minutes=d.max_duration_minutes)).canonical()
        row = ActiveRow(bearer=bearer, persona_id=d.id, started_game=now.canonical(),
                        until_game=until, outfit_snapshot=snapshot,
                        granted_items=tuple(granted), lock_before=lock_before)
        try:
            store.set_active(row)
        except Exception:
            logger.exception("transform of %s into %s not recorded — undoing", bearer, d.id)
            with keyed_lock("character_profile", bearer):
                _restore(bearer, snapshot, tuple(granted), lock_before)
            raise
        pose_key = _strike_activity(bearer, d.transform_activity)
        if pose_key:
            store.set_active(replace(row, outfit_snapshot={**snapshot, "pose_key": pose_key}))
        logger.info("%s transforms into %s (%s, source=%s, until=%s)",
                    bearer, d.alias, d.id, source, until or "revert")
        _narrate(bearer, d.id, d.alias, "transform", source=source)
    return _result(True, "", d.alias)


def revert(bearer: str, *, reason: str) -> bool:
    """End ``bearer``'s transformation. False when there is none.

    ``reason``: one of ``REVERT_REASONS`` (log + narration meta). Restores the
    outfit before the granted suit pieces are taken back, restores the outfit
    lock, clears the flag and the condition, clears the transform activity if
    it is still the current pose, starts the cooldown (GAME time) and tells
    the present knowers.
    """
    if reason not in REVERT_REASONS:
        logger.warning("revert of %s with unknown reason %r", bearer, reason)
    with keyed_lock("transformation", bearer):
        row = store.get_active(bearer)
        if row is None:
            return False
        d = definitions.load().get(row.persona_id)
        snapshot = dict(row.outfit_snapshot or {})
        now = game_time()
        with keyed_lock("character_profile", bearer):
            _restore(bearer, snapshot, row.granted_items, row.lock_before)
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
