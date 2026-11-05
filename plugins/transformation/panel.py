"""The Transformation panel on Game-Admin → Characters → <character> → Skills.

The panel provider of the package (``character_panel:transformation``,
registered in ``register.py``; contract: ``docs/plugins.md`` → "Character
panels"). One card per persona of the world — the personas whose power item
the character holds first — in five tabs: Persona (item, alias, enabled,
appearance), Transformation (phrases, durations, activity, effect), Suit &
images (suit pieces, image/T-pose backend and LoRAs), Behaviour (the prompt
fields the persona replaces, the routine pause) and In on the secret (the
knowers of (persona, character)); a create form; test actions (transform now,
revert now, give the item to this character).

Panel keys differ from the storage where the value lives inside a JSON column:
``_OVERRIDE_FIELDS`` maps into ``prompt_overrides``, ``_IMAGE_FIELDS`` into
``imagegen``.

The persona belongs to its ITEM, not to the character the panel is opened on:
every card is shown on every character, and whoever holds the item can
transform. Only the knowers field and the status line are about the panel's
character (she would be the bearer).

The core has already reduced the submitted values to the declared fields and
coerced their types (``app.core.character_panels.coerce_values``); this module
checks what is specific to personas (alias rules, one persona per item, a
worn persona's alias stays). Every string it answers goes through
``t(en, lang)``.
"""
from __future__ import annotations

import sqlite3
import unicodedata
from typing import Any, Dict, List, Optional

from app.core.character_name import CharacterNameError, localized_message, validate_character_name
from app.core.game_time import GameTime
from app.core.i18n import localized, t
from app.core.keyed_lock import keyed_lock
from app.core.log import get_logger
from app.core.timeutils import game_time
from app.models.character import list_available_characters
from app.models.inventory import (add_to_inventory, find_item_location, get_carried_item_ids,
                                  get_item, remove_from_inventory)

from plugins.transformation import definitions, engine, knowers, store
from plugins.transformation.definitions import (DEFAULT_COOLDOWN_MINUTES,
                                                DEFAULT_MAX_DURATION_MINUTES,
                                                DEFAULT_TRANSFORM_ACTIVITY)

logger = get_logger("transformation")

#: Serializes the validate-then-write of definitions (two admins saving the
#: same alias at once).
_LOCK_KEY = ("transformation_definitions", "*")

#: Item filter of the renderer for outfit pieces (``category == "outfit_piece"``).
_OUTFIT_FILTER = "outfit"

#: The stored columns the panel writes.
_EDITABLE = ("item_id", "alias", "description", "suit_items", "condition_id",
             "activation_phrase", "revert_phrase", "max_duration_minutes",
             "cooldown_minutes", "transform_activity", "enabled", "pause_routine",
             "prompt_overrides", "imagegen")

#: Panel key -> key inside the ``prompt_overrides`` column.
_OVERRIDE_FIELDS = {"personality": "character_personality", "dialogue_style": "dialogue_style",
                    "presence": "character_presence", "task": "character_task",
                    "goals": "character_goals"}

#: Panel key -> key inside the ``imagegen`` column.
_IMAGE_FIELDS = {"image_backend": "workflow", "tpose_backend": "tpose_workflow",
                 "image_loras": "loras", "tpose_loras": "tpose_loras"}

#: The columns whose panel keys are the column names.
_PLAIN = tuple(k for k in _EDITABLE if k not in ("prompt_overrides", "imagegen"))


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


def _cooldown_running(bearer: str, persona_id: str) -> str:
    """The cooldown stamp while it still runs, else ``""``."""
    stamp = store.cooldown_until(bearer, persona_id)
    if not stamp:
        return ""
    try:
        return stamp if game_time() < GameTime.parse(stamp) else ""
    except ValueError:
        return ""


def _item_name(item: Optional[Dict[str, Any]], item_id: str, lang: str) -> str:
    return str(localized(item, "name", lang) or item_id) if item else item_id


def _wearers(persona_id: str) -> List[str]:
    return sorted(r.bearer for r in store.all_active() if r.persona_id == persona_id)


def _tabs(lang: str) -> List[Dict[str, Any]]:
    return [
        {"id": "persona", "label": t("Persona", lang)},
        {"id": "transform", "label": t("Transformation", lang)},
        {"id": "suit", "label": t("Suit & images", lang)},
        {"id": "behaviour", "label": t("Behaviour", lang),
         "hint": t("Empty = unchanged. Filled = replaces it while transformed.", lang)},
        {"id": "knowers", "label": t("In on the secret", lang)},
    ]


def _item_field(lang: str) -> Dict[str, Any]:
    return {"key": "item_id", "type": "item", "label": t("Power item", lang), "required": True,
            "hint": t("Whoever holds it can transform.", lang)}


def _alias_field(lang: str) -> Dict[str, Any]:
    return {"key": "alias", "type": "text", "label": t("Alias", lang), "required": True,
            "hint": t("The name everyone else sees. Renaming later starts afresh: what others "
                      "remember stays with the old name.", lang)}


def _appearance_field(lang: str) -> Dict[str, Any]:
    return {"key": "description", "type": "textarea", "label": t("Persona appearance", lang),
            "hint": t("Body, face and hair as everyone — and every picture — sees them while "
                      "transformed. The suit comes from the suit pieces.", lang)}


def _fields(character: str, alias: str, lang: str) -> List[Dict[str, Any]]:
    unit = t("min", lang)

    def on(tab: str, width: str, field: Dict[str, Any], rows: int = 0) -> Dict[str, Any]:
        field.update(tab=tab, width=width)
        if rows:
            field["rows"] = rows
        return field

    return [
        on("persona", "m", _item_field(lang)),
        on("persona", "m", _alias_field(lang)),
        on("persona", "s", {"key": "enabled", "type": "bool", "label": t("Enabled", lang),
                            "hint": t("Off: the persona leaves the world and its alias is free.",
                                      lang)}),
        on("persona", "full", _appearance_field(lang), rows=3),
        on("transform", "l", {"key": "activation_phrase", "type": "text",
                              "label": t("Transform phrase", lang),
                              "hint": t("When the avatar says it, the avatar transforms.", lang)}),
        on("transform", "l", {"key": "revert_phrase", "type": "text",
                              "label": t("Revert phrase", lang),
                              "hint": t("When the avatar says it, the avatar turns back.", lang)}),
        on("transform", "s", {"key": "max_duration_minutes", "type": "int",
                              "label": t("Max duration", lang), "unit": unit, "min": 0,
                              "hint": t("0 = until reverted", lang)}),
        on("transform", "s", {"key": "cooldown_minutes", "type": "int",
                              "label": t("Cooldown", lang), "unit": unit, "min": 0,
                              "hint": t("Wait after turning back before the next "
                                        "transformation.", lang)}),
        on("transform", "m", {"key": "transform_activity", "type": "text",
                              "label": t("Activity while transforming", lang),
                              "placeholder": DEFAULT_TRANSFORM_ACTIVITY}),
        on("transform", "l", {"key": "condition_id", "type": "condition",
                              "label": t("Effect", lang),
                              "hint": t("Condition while transformed.", lang)}),
        on("suit", "full", {"key": "suit_items", "type": "items", "label": t("Suit", lang),
                            "filter": _OUTFIT_FILTER,
                            "hint": t("Worn while transformed; the old outfit returns "
                                      "afterwards.", lang)}),
        on("suit", "l", {"key": "image_backend", "type": "backend",
                         "label": t("Image backend", lang),
                         "hint": t("Empty = the character's own.", lang)}),
        on("suit", "l", {"key": "tpose_backend", "type": "backend",
                         "label": t("T-pose backend", lang),
                         "hint": t("Empty = image backend.", lang)}),
        on("suit", "l", {"key": "image_loras", "type": "loras", "label": t("LoRAs", lang),
                         "backend_field": "image_backend", "target": "render",
                         "hint": t("Replace the character's LoRAs while transformed.", lang)}),
        on("suit", "l", {"key": "tpose_loras", "type": "loras", "label": t("T-pose LoRAs", lang),
                         "backend_field": "tpose_backend", "fallback_field": "image_backend",
                         "target": "tpose", "hint": t("Empty = the LoRAs above.", lang)}),
        on("behaviour", "l", {"key": "personality", "type": "textarea",
                              "label": t("Personality", lang)}, rows=4),
        on("behaviour", "l", {"key": "dialogue_style", "type": "textarea",
                              "label": t("Speech", lang)}, rows=4),
        on("behaviour", "l", {"key": "presence", "type": "textarea",
                              "label": t("Presence", lang),
                              "hint": t("Also what others sense of the persona.", lang)}, rows=3),
        on("behaviour", "l", {"key": "task", "type": "textarea",
                              "label": t("Tasks", lang)}, rows=3),
        on("behaviour", "l", {"key": "goals", "type": "textarea",
                              "label": t("Goals", lang)}, rows=3),
        on("behaviour", "l", {"key": "pause_routine", "type": "bool",
                              "label": t("Daily routine rests", lang),
                              "hint": t("While transformed, her daily schedule is left out "
                                        "of her thoughts.", lang)}),
        on("knowers", "full", {"key": "knowers", "type": "characters",
                               "label": t("In on the secret", lang),
                               "hint": t("They know that {name} is {alias}.", lang).format(
                                   name=character, alias=alias)}),
    ]


def _create_fields(lang: str) -> List[Dict[str, Any]]:
    return [_item_field(lang), _alias_field(lang), _appearance_field(lang)]


def _values(row: Dict[str, Any]) -> Dict[str, Any]:
    """The card values under the panel keys, every field filled."""
    values = {key: row[key] for key in _PLAIN}
    overrides = row["prompt_overrides"]
    for key, stored in _OVERRIDE_FIELDS.items():
        values[key] = overrides.get(stored, "")
    image = row["imagegen"]
    for key, stored in _IMAGE_FIELDS.items():
        values[key] = [dict(e) for e in image[stored]] if stored in store.IMAGEGEN_LORA_KEYS \
            else image[stored]
    return values


def _status(character: str, row: Dict[str, Any], active, lang: str) -> str:
    pid = row["id"]
    if active is not None and active.persona_id == pid:
        return t("Transformed into {alias} since {time}", lang).format(
            alias=row["alias"], time=_label_of(active.started_game, lang))
    if active is not None:
        worn = store.get_definition(active.persona_id)
        alias = (worn or {}).get("alias") or str(active.outfit_snapshot.get("alias") or "")
        return t("Currently transformed into {alias}", lang).format(alias=alias)
    cooldown = _cooldown_running(character, pid)
    if cooldown:
        return t("On cooldown until {time}", lang).format(time=_label_of(cooldown, lang))
    return t("Ordinary self", lang)


# ---------------------------------------------------------------------------
# describe
# ---------------------------------------------------------------------------

def describe(character: str, lang: str) -> Dict[str, Any]:
    rows = store.list_definitions()
    usable = definitions.load()
    carried = get_carried_item_ids(character)
    active = store.get_active(character)
    cards = []
    for row in rows:
        pid, item_id = row["id"], row["item_id"]
        holds = item_id in carried
        item = get_item(item_id) if item_id else None
        badges: List[str] = []
        if holds:
            badges.append(t("holds the item", lang))
        if not row["enabled"]:
            badges.append(t("disabled", lang))
        elif pid not in usable:
            badges.append(t("not usable", lang))
        if holds:
            subtitle = t("Held by {name}", lang).format(name=character)
            holder = character
        else:
            where = find_item_location(item_id) if item else None
            holder = where.get("character", "") if where and where.get("kind") == "character" else ""
            subtitle = (t("Held by {name}", lang).format(name=holder) if holder
                        else t("Nobody holds the item", lang))
        actions: List[Dict[str, Any]] = []
        wears_this = active is not None and active.persona_id == pid
        if holds and active is None and pid in usable:
            actions.append({"id": "transform", "label": t("Transform now", lang), "primary": True})
        if wears_this:
            actions.append({"id": "revert", "label": t("Revert now", lang), "primary": True})
        if not holds and item:
            give = {"id": "give", "label": t("Give {item} to {name}", lang).format(
                item=_item_name(item, item_id, lang), name=character)}
            if holder:
                give["confirm"] = t("{name} loses the item.", lang).format(name=holder)
            actions.append(give)
        values = _values(row)
        values["knowers"] = knowers.knower_names(character, pid)
        cards.append(((0 if holds else 1, _fold(row["alias"])), {
            "id": pid, "title": row["alias"] or pid, "subtitle": subtitle, "badges": badges,
            "fields": _fields(character, row["alias"], lang), "values": values,
            "status": _status(character, row, active, lang), "actions": actions,
            "deletable": True,
            "delete_confirm": t("The persona {alias} is removed for good, with its knowers "
                                "and cooldowns.", lang).format(alias=row["alias"] or pid),
        }))
    cards.sort(key=lambda pair: pair[0])
    return {
        "title": t("Transformation", lang),
        "intro": t("The power belongs to the item: whoever holds it can transform.", lang),
        "tabs": _tabs(lang),
        "cards": [c for _, c in cards],
        "create": {"label": t("New transformation", lang), "fields": _create_fields(lang)},
    }


# ---------------------------------------------------------------------------
# save
# ---------------------------------------------------------------------------

def _required(label_en: str, lang: str) -> str:
    return t("{label} is required.", lang).format(label=t(label_en, lang))


def _check(record: Dict[str, Any], own: Optional[Dict[str, Any]], lang: str) -> str:
    """The first rule ``record`` breaks, as a translated sentence, or ``""``.
    ``own`` = the stored row on an update (``None`` on create)."""
    item_id, alias = record["item_id"], record["alias"]
    if not item_id:
        return _required("Power item", lang)
    if not alias:
        return _required("Alias", lang)
    own_id = own["id"] if own else ""
    folded = _fold(alias)
    for other in store.list_definitions():
        if other["id"] == own_id:
            continue
        if _fold(other["alias"]) == folded:
            return t("Another persona already uses the alias {alias}.", lang).format(alias=alias)
        if other["item_id"] == item_id:
            return t("This item already grants the persona {alias}.", lang).format(
                alias=other["alias"] or other["id"])
    try:
        validate_character_name(alias)
    except CharacterNameError as err:
        # A persona alias is a reserved character name — its OWN alias may stay.
        if not (err.code == "reserved" and own and _fold(own["alias"]) == folded):
            return localized_message(err, lang)
    if folded in {_fold(n) for n in list_available_characters(include_pooled=True)}:
        return t("{alias} is the name of a character.", lang).format(alias=alias)
    if (own is None or own["item_id"] != item_id) and get_item(item_id) is None:
        return t("This item does not exist.", lang)
    for key in ("max_duration_minutes", "cooldown_minutes"):
        if int(record[key]) < 0:
            return t("Minutes cannot be negative.", lang)
    if own and _fold(own["alias"]) != folded:
        wearers = _wearers(own["id"])
        if wearers:
            return t("Revert first: {name} currently wears this persona.", lang).format(
                name=", ".join(wearers))
    return ""


def save(character: str, card_id: Optional[str], values: Dict[str, Any],
         lang: str) -> Dict[str, Any]:
    with keyed_lock(*_LOCK_KEY):
        own = store.get_definition(card_id) if card_id else None
        if card_id and own is None:
            return {"ok": False, "error": t("This entry no longer exists.", lang)}
        base: Dict[str, Any] = dict(own) if own else {
            "item_id": "", "alias": "", "description": "", "suit_items": [], "condition_id": "",
            "activation_phrase": "", "revert_phrase": "",
            "max_duration_minutes": DEFAULT_MAX_DURATION_MINUTES,
            "cooldown_minutes": DEFAULT_COOLDOWN_MINUTES,
            "transform_activity": DEFAULT_TRANSFORM_ACTIVITY, "enabled": True,
            "pause_routine": True, "prompt_overrides": {},
            "imagegen": store.normalize_imagegen({}),
        }
        record = dict(base)
        for key in _PLAIN:
            if key in values:
                record[key] = values[key]
        overrides = dict(record["prompt_overrides"])
        for key, stored in _OVERRIDE_FIELDS.items():
            if key in values:
                overrides[stored] = values[key]
        record["prompt_overrides"] = store.normalize_overrides(overrides)
        image = dict(record["imagegen"])
        for key, stored in _IMAGE_FIELDS.items():
            if key in values:
                image[stored] = values[key]
        record["imagegen"] = store.normalize_imagegen(image)
        for key in ("item_id", "alias", "description", "condition_id", "activation_phrase",
                    "revert_phrase", "transform_activity"):
            record[key] = str(record.get(key) or "").strip()
        record["alias"] = unicodedata.normalize("NFC", record["alias"])
        if record["max_duration_minutes"] is None:
            record["max_duration_minutes"] = DEFAULT_MAX_DURATION_MINUTES
        if record["cooldown_minutes"] is None:
            record["cooldown_minutes"] = DEFAULT_COOLDOWN_MINUTES
        record["transform_activity"] = record["transform_activity"] or DEFAULT_TRANSFORM_ACTIVITY
        record["enabled"] = bool(record["enabled"])
        record["pause_routine"] = bool(record["pause_routine"])
        try:
            record["max_duration_minutes"] = int(record["max_duration_minutes"])
            record["cooldown_minutes"] = int(record["cooldown_minutes"])
        except (TypeError, ValueError):
            return {"ok": False, "error": t("Minutes cannot be negative.", lang)}
        error = _check(record, own, lang)
        if error:
            return {"ok": False, "error": error}
        try:
            if own is None:
                pid = store.create_definition({k: record[k] for k in _EDITABLE})
            else:
                pid = own["id"]
                changes = {k: record[k] for k in _EDITABLE if record[k] != own.get(k)}
                if changes:
                    store.update_definition(pid, changes)
        except sqlite3.IntegrityError:
            logger.exception("transformation definition not saved")
            return {"ok": False, "error": t("This item already grants another persona.", lang)}
        if own is not None and own["alias"] != record["alias"]:
            knowers.rename_alias(pid, record["alias"])
    if "knowers" in values:
        wanted = [n for n in values.get("knowers") or [] if isinstance(n, str)]
        if {_fold(n) for n in wanted} != {_fold(n) for n in knowers.knower_names(character, pid)}:
            knowers.set_knowers(character, pid, wanted)
    return {"ok": True, "card_id": pid}


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------

def delete(character: str, card_id: str, lang: str) -> Dict[str, Any]:
    with keyed_lock(*_LOCK_KEY):
        own = store.get_definition(card_id)
        if own is None:
            return {"ok": False, "error": t("This entry no longer exists.", lang)}
        wearers = _wearers(card_id)
        if wearers:
            return {"ok": False, "error": t("Revert first: {name} currently wears this persona.",
                                            lang).format(name=", ".join(wearers))}
        store.delete_definition(card_id)
    knowers.forget_persona(card_id)
    logger.info("persona %s (%s) deleted from the panel of %s", card_id, own["alias"], character)
    return {"ok": True}


# ---------------------------------------------------------------------------
# action
# ---------------------------------------------------------------------------

def _transform(character: str, row: Dict[str, Any], lang: str) -> Dict[str, Any]:
    result = engine.transform(character, row["id"], source="admin")
    if result.get("ok"):
        return {"ok": True, "message": t("{name} is now {alias}.", lang).format(
            name=character, alias=result.get("alias") or row["alias"])}
    reason = str(result.get("reason") or "")
    if reason == "not_holding_item":
        error = t("{name} does not hold the power item.", lang).format(name=character)
    elif reason == "already_transformed":
        error = t("{name} is already transformed.", lang).format(name=character)
    elif reason == "cooldown":
        stamp = store.cooldown_until(character, row["id"])
        error = t("{name} is on cooldown until {time}.", lang).format(
            name=character, time=_label_of(stamp, lang))
    else:
        error = t("This persona is switched off or not usable.", lang)
    return {"ok": False, "error": error}


def _revert(character: str, row: Dict[str, Any], lang: str) -> Dict[str, Any]:
    active = store.get_active(character)
    if active is None or active.persona_id != row["id"]:
        return {"ok": False, "error": t("{name} does not wear this persona.", lang).format(
            name=character)}
    if not engine.revert(character, reason="admin"):
        return {"ok": False, "error": t("{name} does not wear this persona.", lang).format(
            name=character)}
    return {"ok": True, "message": t("{name} has turned back.", lang).format(name=character)}


def _give(character: str, row: Dict[str, Any], lang: str) -> Dict[str, Any]:
    item_id = row["item_id"]
    item = get_item(item_id)
    if item is None:
        return {"ok": False, "error": t("This item does not exist.", lang)}
    if item_id in get_carried_item_ids(character):
        return {"ok": False, "error": t("{name} already holds the item.", lang).format(
            name=character)}
    where = find_item_location(item_id, exclude_character=character)
    holder = where.get("character", "") if where and where.get("kind") == "character" else ""
    if not add_to_inventory(character, item_id, obtained_from=holder,
                            obtained_method="given" if holder else "manual"):
        return {"ok": False, "error": t("The item could not be given.", lang)}
    if holder:
        remove_from_inventory(holder, item_id, force=True)
    return {"ok": True, "message": t("{name} now holds {item}.", lang).format(
        name=character, item=_item_name(item, item_id, lang))}


_ACTIONS = {"transform": _transform, "revert": _revert, "give": _give}


def action(character: str, card_id: str, action_id: str, lang: str) -> Dict[str, Any]:
    row = store.get_definition(card_id)
    if row is None:
        return {"ok": False, "error": t("This entry no longer exists.", lang)}
    fn = _ACTIONS.get(action_id)
    if fn is None:
        return {"ok": False, "error": t("Unknown action.", lang)}
    return fn(character, row, lang)
