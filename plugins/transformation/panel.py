"""The Transformation panel on Game-Admin → Characters → <character> → Skills.

The panel provider of the package (``character_panel:transformation``,
registered in ``register.py``; contract: ``docs/plugins.md`` → "Character
panels").

On a LEADER (any character that is not a linked body): one card per
definition the character leads — those whose power item it holds first — in
two tabs: **Transformation** (the linked character to become, picked from the
leader's bodies; power item, enabled; phrases; durations, activity, effect on
the body — short fields side by side) and **Knowers** (who knows that the body
is the leader). A panel-level action **Create linked character** asks only for
a name (``app.core.linked_characters.create_linked``); the new body opens in
the editor right away (``open_character``) and is selectable on the cards. Test actions per card: Transform now (ignores the cooldown),
Revert now, Give <item> to <leader>.

On a linked BODY: only status + "Revert now" per definition that turns its
leader into it, and a pointer to the leader's panel (the intro).

The core has already reduced the submitted values to the declared fields and
coerced their types (``app.core.character_panels.coerce_values`` — including
the body ``select`` against its options); this module checks what is specific
to transformations (one definition per leader and item, the item exists, the
body is still linked). Every string it answers goes through ``t(en, lang)``.
"""
from __future__ import annotations

import sqlite3
import unicodedata
from typing import Any, Dict, List, Optional

from app.core.game_time import GameTime
from app.core.i18n import localized, t
from app.core.keyed_lock import keyed_lock
from app.core.linked_characters import bodies_of, create_linked, leader_of
from app.core.log import get_logger
from app.core.timeutils import game_time
from app.models.character import DORMANT_STATUS, get_character_status
from app.models.inventory import (add_to_inventory, find_item_location, get_carried_item_ids,
                                  get_item, remove_from_inventory)

from plugins.transformation import definitions, engine, knowers, store
from plugins.transformation.definitions import (DEFAULT_COOLDOWN_MINUTES,
                                                DEFAULT_MAX_DURATION_MINUTES,
                                                DEFAULT_TRANSFORM_ACTIVITY)

logger = get_logger("transformation")

#: Serializes the validate-then-write of definitions (two admins binding the
#: same item at once).
_LOCK_KEY = ("transformation_definitions", "*")

#: The stored fields the panel writes (panel key = definition key).
_EDITABLE = ("body", "item_id", "enabled", "activation_phrase", "revert_phrase",
             "max_duration_minutes", "cooldown_minutes", "transform_activity", "condition_id")
_TEXT = ("body", "item_id", "activation_phrase", "revert_phrase", "transform_activity",
         "condition_id")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fold(text: str) -> str:
    return unicodedata.normalize("NFC", text or "").strip().casefold()


def _label_of(stamp: str, lang: str) -> str:
    try:
        return GameTime.parse(stamp).display_label(lang)
    except ValueError:
        return stamp


def _cooldown_running(leader: str, def_id: str) -> str:
    """The cooldown stamp while it still runs, else ``""``."""
    stamp = store.cooldown_until(leader, def_id)
    if not stamp:
        return ""
    try:
        return stamp if game_time() < GameTime.parse(stamp) else ""
    except ValueError:
        return ""


def _item_name(item: Optional[Dict[str, Any]], item_id: str, lang: str) -> str:
    return str(localized(item, "name", lang) or item_id) if item else item_id


def _tabs(lang: str) -> List[Dict[str, Any]]:
    return [{"id": "transform", "label": t("Transformation", lang)},
            {"id": "knowers", "label": t("Knowers", lang)}]


def _body_field(leader: str, lang: str) -> Dict[str, Any]:
    return {"key": "body", "type": "select", "label": t("Linked character", lang),
            "required": True,
            "options": [{"value": b, "label": b} for b in bodies_of(leader)],
            "hint": t("Who {name} turns into.", lang).format(name=leader)}


def _item_field(lang: str) -> Dict[str, Any]:
    return {"key": "item_id", "type": "item", "label": t("Power item", lang), "required": True,
            "hint": t("Needed to transform and to turn back.", lang)}


def _fields(leader: str, body: str, lang: str) -> List[Dict[str, Any]]:
    unit = t("min", lang)

    def on(tab: str, width: str, field: Dict[str, Any]) -> Dict[str, Any]:
        field.update(tab=tab, width=width)
        return field

    return [
        on("transform", "m", _body_field(leader, lang)),
        on("transform", "m", _item_field(lang)),
        on("transform", "s", {"key": "enabled", "type": "bool", "label": t("Enabled", lang),
                              "hint": t("Off: this transformation cannot start.", lang)}),
        on("transform", "l", {"key": "activation_phrase", "type": "text",
                              "label": t("Transform phrase", lang),
                              "hint": t("When the avatar says it, the avatar transforms.", lang)}),
        on("transform", "l", {"key": "revert_phrase", "type": "text",
                              "label": t("Revert phrase", lang),
                              "hint": t("When the transformed avatar says it, it turns back.",
                                        lang)}),
        on("transform", "s", {"key": "max_duration_minutes", "type": "int",
                              "label": t("Max duration", lang), "unit": unit, "min": 0,
                              "hint": t("0 = until reverted", lang)}),
        on("transform", "s", {"key": "cooldown_minutes", "type": "int",
                              "label": t("Cooldown", lang), "unit": unit, "min": 0,
                              "hint": t("Wait after turning back before the next "
                                        "transformation.", lang)}),
        on("transform", "s", {"key": "transform_activity", "type": "text",
                              "label": t("Activity while transforming", lang),
                              "placeholder": DEFAULT_TRANSFORM_ACTIVITY}),
        on("transform", "s", {"key": "condition_id", "type": "condition",
                              "label": t("Effect", lang),
                              "hint": t("Condition on the body while transformed.", lang)}),
        on("knowers", "full", {"key": "knowers", "type": "characters",
                               "label": t("Knowers", lang),
                               "hint": t("They know that {body} is {leader}.", lang).format(
                                   body=body or "…", leader=leader)}),
    ]


def _values(row: Dict[str, Any]) -> Dict[str, Any]:
    """The card values under the panel keys, every field filled."""
    out = {key: row[key] for key in _EDITABLE}
    out["knowers"] = knowers.knower_names(row["body"]) if row["body"] else []
    return out


def _leader_status(leader: str, row: Dict[str, Any], lang: str) -> str:
    active = store.get_active(leader)
    if active is not None and active.def_id == row["id"]:
        return t("Transformed into {body} since {time}", lang).format(
            body=active.body, time=_label_of(active.started_game, lang))
    if active is not None:
        return t("Currently transformed into {body}", lang).format(body=active.body)
    cooldown = _cooldown_running(leader, row["id"])
    if cooldown:
        return t("On cooldown until {time}", lang).format(time=_label_of(cooldown, lang))
    return t("Ordinary self", lang)


def _create_action(leader: str, lang: str) -> Dict[str, Any]:
    return {"id": "create_linked", "label": t("Create linked character", lang),
            "input": {"label": t("Name", lang),
                      "message": t("A new character linked to {name}, built from {name}'s "
                                   "template. It opens for editing right away.", lang).format(
                                       name=leader)}}


# ---------------------------------------------------------------------------
# describe
# ---------------------------------------------------------------------------

def _describe_body(body: str, leader: str, lang: str) -> Dict[str, Any]:
    cards = []
    for row in store.list_definitions(leader=leader):
        if row["body"] != body:
            continue
        active = store.get_active(leader)
        actions: List[Dict[str, Any]] = []
        if active is not None and active.def_id == row["id"] and active.body == body:
            status = t("{body} stands in the world for {leader} since {time}", lang).format(
                body=body, leader=leader, time=_label_of(active.started_game, lang))
            actions.append({"id": "revert", "label": t("Revert now", lang), "primary": True})
        elif get_character_status(body) == DORMANT_STATUS:
            status = t("Dormant — {leader} stands in the world.", lang).format(leader=leader)
        else:
            status = t("Not transformed", lang)
        cards.append({"id": row["id"], "title": t("From {leader}", lang).format(leader=leader),
                      "subtitle": "", "badges": [] if row["enabled"] else [t("disabled", lang)],
                      "fields": [], "values": {}, "status": status, "actions": actions})
    return {
        "title": t("Transformation", lang),
        "intro": t("{body} is a linked character of {leader} — set the transformation up on "
                   "{leader}'s panel.", lang).format(body=body, leader=leader),
        "cards": cards,
        "create": None,
    }


def describe(character: str, lang: str) -> Dict[str, Any]:
    leader = leader_of(character)
    if leader:
        return _describe_body(character, leader, lang)
    usable = definitions.load()
    carried = get_carried_item_ids(character)
    active = store.get_active(character)
    cards = []
    for row in store.list_definitions(leader=character):
        did, item_id = row["id"], row["item_id"]
        holds = item_id in carried
        item = get_item(item_id) if item_id else None
        badges: List[str] = []
        if holds:
            badges.append(t("holds the item", lang))
        if not row["enabled"]:
            badges.append(t("disabled", lang))
        elif did not in usable:
            badges.append(t("not usable", lang))
        where = find_item_location(item_id) if item else None
        holder = where.get("character", "") if where and where.get("kind") == "character" else ""
        subtitle = (t("Held by {name}", lang).format(name=holder) if holder
                    else t("Nobody holds the item", lang))
        actions: List[Dict[str, Any]] = []
        if active is None and holds and did in usable:
            actions.append({"id": "transform", "label": t("Transform now", lang), "primary": True})
        if active is not None and active.def_id == did:
            actions.append({"id": "revert", "label": t("Revert now", lang), "primary": True})
        if active is None and not holds and item:
            give = {"id": "give", "label": t("Give {item} to {name}", lang).format(
                item=_item_name(item, item_id, lang), name=character)}
            if holder:
                give["confirm"] = t("{name} loses the item.", lang).format(name=holder)
            actions.append(give)
        body = row["body"]
        cards.append(((0 if holds else 1, _fold(body or did)), {
            "id": did, "title": body or did, "subtitle": subtitle, "badges": badges,
            "fields": _fields(character, body, lang), "values": _values(row),
            "status": _leader_status(character, row, lang), "actions": actions,
            "deletable": True,
            "delete_confirm": t("The transformation into {body} is removed for good, with its "
                                "cooldowns. Who knows that {body} is {leader} stays.",
                                lang).format(body=body or did, leader=character),
        }))
    cards.sort(key=lambda pair: pair[0])
    bodies = bodies_of(character)
    return {
        "title": t("Transformation", lang),
        "intro": t("{name} turns into a linked character through a power item.", lang).format(
            name=character),
        "tabs": _tabs(lang),
        "actions": [_create_action(character, lang)],
        "cards": [c for _, c in cards],
        "create": ({"label": t("New transformation", lang),
                    "fields": [_body_field(character, lang), _item_field(lang)]}
                   if bodies else None),
    }


# ---------------------------------------------------------------------------
# save
# ---------------------------------------------------------------------------

def _required(label_en: str, lang: str) -> str:
    return t("{label} is required.", lang).format(label=t(label_en, lang))


def _check(leader: str, record: Dict[str, Any], own: Optional[Dict[str, Any]],
           lang: str) -> str:
    """The first rule ``record`` breaks, as a translated sentence, or ``""``.
    ``own`` = the stored row on an update (``None`` on create)."""
    body, item_id = record["body"], record["item_id"]
    if not body:
        return _required("Linked character", lang)
    if not item_id:
        return _required("Power item", lang)
    if (own is None or own["body"] != body) and leader_of(body) != leader:
        return t("{body} is not a linked character of {leader}.", lang).format(
            body=body, leader=leader)
    if own is not None and own["body"] != body:
        active = store.get_active(leader)
        if active is not None and active.def_id == own["id"]:
            return t("Revert first: {leader} is transformed into {body}.", lang).format(
                leader=leader, body=active.body)
    own_id = own["id"] if own else ""
    for other in store.list_definitions(leader=leader):
        if other["id"] != own_id and other["item_id"] == item_id:
            return t("This item already turns {leader} into {body}.", lang).format(
                leader=leader, body=other["body"] or other["id"])
    if (own is None or own["item_id"] != item_id) and get_item(item_id) is None:
        return t("This item does not exist.", lang)
    for key in ("max_duration_minutes", "cooldown_minutes"):
        if int(record[key]) < 0:
            return t("Minutes cannot be negative.", lang)
    return ""


def save(character: str, card_id: Optional[str], values: Dict[str, Any],
         lang: str) -> Dict[str, Any]:
    if leader_of(character):
        return {"ok": False, "error": t("This entry no longer exists.", lang)}
    with keyed_lock(*_LOCK_KEY):
        own = store.get_definition(card_id) if card_id else None
        if card_id and (own is None or own["leader"] != character):
            return {"ok": False, "error": t("This entry no longer exists.", lang)}
        base: Dict[str, Any] = dict(own) if own else {
            "body": "", "item_id": "", "condition_id": "",
            "activation_phrase": "", "revert_phrase": "",
            "max_duration_minutes": DEFAULT_MAX_DURATION_MINUTES,
            "cooldown_minutes": DEFAULT_COOLDOWN_MINUTES,
            "transform_activity": DEFAULT_TRANSFORM_ACTIVITY, "enabled": True,
        }
        record = dict(base)
        for key in _EDITABLE:
            if key in values:
                record[key] = values[key]
        for key in _TEXT:
            record[key] = str(record.get(key) or "").strip()
        if record["max_duration_minutes"] is None:
            record["max_duration_minutes"] = DEFAULT_MAX_DURATION_MINUTES
        if record["cooldown_minutes"] is None:
            record["cooldown_minutes"] = DEFAULT_COOLDOWN_MINUTES
        record["transform_activity"] = record["transform_activity"] or DEFAULT_TRANSFORM_ACTIVITY
        record["enabled"] = bool(record["enabled"])
        try:
            record["max_duration_minutes"] = int(record["max_duration_minutes"])
            record["cooldown_minutes"] = int(record["cooldown_minutes"])
        except (TypeError, ValueError):
            return {"ok": False, "error": t("Minutes cannot be negative.", lang)}
        error = _check(character, record, own, lang)
        if error:
            return {"ok": False, "error": error}
        try:
            if own is None:
                did = store.create_definition({"leader": character,
                                               **{k: record[k] for k in _EDITABLE}})
            else:
                did = own["id"]
                changes = {k: record[k] for k in _EDITABLE if record[k] != own.get(k)}
                if changes:
                    store.update_definition(did, changes)
        except sqlite3.IntegrityError:
            logger.exception("transformation definition not saved")
            return {"ok": False, "error": t("This item already turns {leader} into another "
                                            "character.", lang).format(leader=character)}
    if "knowers" in values and record["body"]:
        wanted = [n for n in values.get("knowers") or [] if isinstance(n, str)]
        knowers.set_knowers(record["body"], wanted)
    return {"ok": True, "card_id": did}


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------

def delete(character: str, card_id: str, lang: str) -> Dict[str, Any]:
    with keyed_lock(*_LOCK_KEY):
        own = store.get_definition(card_id)
        if own is None or own["leader"] != character:
            return {"ok": False, "error": t("This entry no longer exists.", lang)}
        active = store.get_active(character)
        if active is not None and active.def_id == card_id:
            return {"ok": False, "error": t("Revert first: {leader} is transformed into {body}.",
                                            lang).format(leader=character, body=active.body)}
        store.delete_definition(card_id)
    logger.info("transformation %s (%s -> %s) deleted", card_id, character, own["body"])
    return {"ok": True}


# ---------------------------------------------------------------------------
# action
# ---------------------------------------------------------------------------

def _transform(leader: str, row: Dict[str, Any], lang: str) -> Dict[str, Any]:
    # The admin's "Transform now" overrides a running cooldown.
    result = engine.transform(leader, row["id"], source="admin", ignore_cooldown=True)
    if result.get("ok"):
        return {"ok": True, "message": t("{leader} is now {body}.", lang).format(
            leader=leader, body=result.get("body") or row["body"])}
    reason = str(result.get("reason") or "")
    if reason == "not_holding_item":
        error = t("{name} does not hold the power item.", lang).format(name=leader)
    elif reason == "already_transformed":
        error = t("{name} is already transformed.", lang).format(name=leader)
    elif reason == "body_not_linked":
        error = t("{body} is not a linked character of {leader}.", lang).format(
            body=row["body"], leader=leader)
    elif reason in ("refused", "failed"):
        error = t(str(result.get("error") or ""), lang) or t("That did not work.", lang)
    else:
        error = t("This transformation is switched off or not usable.", lang)
    return {"ok": False, "error": error}


def _revert(leader: str, row: Dict[str, Any], lang: str) -> Dict[str, Any]:
    active = store.get_active(leader)
    if active is None or active.def_id != row["id"]:
        return {"ok": False, "error": t("{leader} is not transformed into {body}.", lang).format(
            leader=leader, body=row["body"])}
    result = engine.revert(leader, reason="admin")
    if result.get("ok"):
        return {"ok": True, "message": t("{body} has turned back into {leader}.", lang).format(
            body=active.body, leader=leader)}
    if result.get("reason") in ("refused", "failed"):
        return {"ok": False, "error": t(str(result.get("error") or ""), lang)
                or t("That did not work.", lang)}
    return {"ok": False, "error": t("{leader} is not transformed into {body}.", lang).format(
        leader=leader, body=row["body"])}


def _give(leader: str, row: Dict[str, Any], lang: str) -> Dict[str, Any]:
    item_id = row["item_id"]
    item = get_item(item_id)
    if item is None:
        return {"ok": False, "error": t("This item does not exist.", lang)}
    if item_id in get_carried_item_ids(leader):
        return {"ok": False, "error": t("{name} already holds the item.", lang).format(
            name=leader)}
    where = find_item_location(item_id, exclude_character=leader)
    holder = where.get("character", "") if where and where.get("kind") == "character" else ""
    if not add_to_inventory(leader, item_id, obtained_from=holder,
                            obtained_method="given" if holder else "manual"):
        return {"ok": False, "error": t("The item could not be given.", lang)}
    if holder:
        remove_from_inventory(holder, item_id, force=True)
    return {"ok": True, "message": t("{name} now holds {item}.", lang).format(
        name=leader, item=_item_name(item, item_id, lang))}


def _create_linked(leader: str, name: str, lang: str) -> Dict[str, Any]:
    result = create_linked(leader, name)
    if not result.get("ok"):
        return {"ok": False, "error": t(str(result.get("error") or ""), lang)
                or t("That did not work.", lang)}
    created = str(result.get("name") or name)
    return {"ok": True, "open_character": created,
            "message": t("{name} was created as a linked character of {leader}.",
                         lang).format(name=created, leader=leader)}


_LEADER_ACTIONS = {"transform": _transform, "revert": _revert, "give": _give}


def action(character: str, card_id: str, action_id: str, lang: str,
           value: str = "") -> Dict[str, Any]:
    leader = leader_of(character)
    if not card_id:
        if action_id == "create_linked" and not leader:
            return _create_linked(character, value, lang)
        return {"ok": False, "error": t("Unknown action.", lang)}
    row = store.get_definition(card_id)
    owner = leader or character
    if row is None or row["leader"] != owner or (leader and row["body"] != character):
        return {"ok": False, "error": t("This entry no longer exists.", lang)}
    if leader:
        if action_id != "revert":
            return {"ok": False, "error": t("Unknown action.", lang)}
        return _revert(leader, row, lang)
    fn = _LEADER_ACTIONS.get(action_id)
    if fn is None:
        return {"ok": False, "error": t("Unknown action.", lang)}
    return fn(character, row, lang)
