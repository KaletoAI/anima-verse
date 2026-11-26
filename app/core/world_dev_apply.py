"""World Dev character apply — one character draft written through the core.

One character draft (profile fields, soul sections, config fields, body
slots, outfits, home and daily schedule) is written through the character
model savers. Called by the World Dev free mode (``world_dev_tools``) and by
the temp-NPC generator (``npc_ops.apply_npc``). Errors are ``ValueError``;
the free mode turns them into a refused tool call, the NPC generator into
its own error.

Also home of ``_map_world_context``, the one reader of the world facts the
map-layout sanitizer needs.
"""
from typing import Any, Callable, Dict, List, Optional, Tuple

from fastapi import HTTPException

from app.core.log import get_logger
from app.models.character import (
    add_character_outfit, get_character_config, get_character_profile,
    save_character_config, save_character_profile)

logger = get_logger("world_dev")


def _row_exists(char_name: str) -> bool:
    """Whether a ``characters`` row with exactly this name exists."""
    from app.models.character import character_row_exists
    try:
        return character_row_exists(char_name)
    except Exception:  # an unreadable DB reads as "new", as before the move
        return False


def _get_generable_fields(template_name: str) -> tuple[set, set]:
    """Returns (profile_fields, config_fields) that the LLM may set for a template.

    Reads the merged template and collects all field keys with llm_generable=True.
    Fields with store="config" go to config_fields, the rest to profile_fields.
    'character_name' and 'template' are always profile fields.
    """
    from app.models.character_template import get_template

    profile_fields = {"character_name", "template"}
    config_fields: set[str] = set()

    tmpl = get_template(template_name)
    if not tmpl:
        # Fallback: allow basic fields
        profile_fields.update({"language", "gender", "age",
                               "character_personality", "character_appearance"})
        return profile_fields, config_fields

    for section in tmpl.get("sections", []):
        for field in section.get("fields", []):
            if not field.get("llm_generable"):
                continue
            key = field.get("key", "")
            if not key:
                continue
            if field.get("store") == "config":
                config_fields.add(key)
            else:
                profile_fields.add(key)

    return profile_fields, config_fields


def status_field_keys(template_name: str) -> set:
    """Keys of the template's stat fields (``store == "status_effects"``):
    their values live in ``profile["status_effects"]``, never at the top
    level of the profile."""
    from app.models.character_template import get_template
    keys: set = set()
    for section in (get_template(template_name) or {}).get("sections", []) or []:
        for field in section.get("fields", []) or []:
            if field.get("store") == "status_effects" and field.get("key"):
                keys.add(str(field["key"]))
    return keys


def _stat_number(value: Any) -> bool:
    """A stat value the apply takes: a finite WHOLE number 0-100 (no bool) —
    a fractional value is skipped with a warning like any other, never
    truncated (the free-mode tool refuses it the same way)."""
    # Range before any float(): a huge JSON integer (10**400) would make
    # float() raise OverflowError; NaN fails the range comparison.
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and 0 <= value <= 100 and float(value).is_integer())


def apply_character(char_data: Dict[str, Any],
                    selected_template: str = "",
                    created_by: str = "",
                    must_be_new: bool = False,
                    on_claim: Optional[Callable[[], None]] = None,
                    on_item: Optional[Callable[[str], None]] = None,
                    place_compliance: bool = True,
                    body_attributes: Optional[Callable[[Any], Dict[str, Dict[str, Any]]]] = None
                    ) -> Dict[str, Any]:
    """Apply character JSON in-process (profile + soul MD + outfits + config).

    Used by the temp-NPC generator (``npc_ops.apply_npc``) and the World Dev
    free mode. Caller
    is responsible for handing in a *normalized* dict — flat fields, no nested
    soul object. Sub-sections without a template source_file mapping (e.g.
    soul/soul.md, soul/tasks.md) can be passed via the special key
    ``_extra_soul_md`` as ``{"<section>": "<full markdown>"}``.

    Raises ``ValueError`` (a ``CharacterNameError`` for a name the rule
    refuses) — the caller reports its text. With ``must_be_new=True`` a
    character whose VALIDATED name already exists is a ``ValueError`` too,
    before anything is written. It is checked once more under the
    ``character_profile`` lock, right before the new row is stored; only
    then is ``on_claim()`` called — the caller's proof that a row found after
    a later failure is the one THIS call created, never a foreign one.
    ``on_item(item_id)`` is called right after ``add_item`` stored a new
    catalog piece for an outfit, before it is handed to the character — the
    caller can record the id durably before anything else happens.
    ``place_compliance=False``: a new character placed at its home is not
    run through the outfit compliance here — a caller that dresses it
    afterwards (the World Dev free mode's starting outfit) runs it once
    itself, on the outfit actually worn.
    ``body_attributes(spec)``: which attributes of a body slot ``body_slots``
    may set — default ``body_slots.llm_fillable_attributes`` (the temp-NPC
    generator); the free mode passes ``body_slots.editable_attributes`` (it
    checked the values against that set itself, the mesh-part switch only on
    the base-body pipeline).

    Returns {status, character, template, outfits, warnings, created_items};
    ``created_items`` are the catalog item ids the outfits created via
    ``add_item`` (reused pieces are not listed).
    """
    char_name = char_data["character_name"]
    template = char_data.get("template") or selected_template or "human-default"
    char_data["template"] = template

    # Detect whether this is a new character — if so, save_character_profile
    # needs create_new=True to bypass the ghost-character guard. Without
    # this, the very first save silently returns and we end up with a row
    # that only has config_json filled (created later by save_character_config
    # / add_character_outfit), but profile_json stays {} and template "".
    _is_new = not _row_exists(char_name)

    # THE name rule (app/core/character_name.py) — only for a NEW character.
    # An existing one is never re-validated, so a world built before the rule
    # keeps applying. The error is a CharacterNameError carrying the localized
    # text; the callers report every ValueError with that text (the free mode
    # as the refusal line the agent and the panel see).
    if _is_new:
        from app.core.character_name import (CharacterNameError,
                                             localized_message,
                                             validate_character_name)
        try:
            char_name = validate_character_name(char_name)
            char_data["character_name"] = char_name
        except CharacterNameError as err:
            from app.core.i18n import t
            from app.models.account import get_language_settings
            _lang = get_language_settings().get("system_language") or "en"
            text = t("Cannot create the character: {reason}", _lang
                     ).format(reason=localized_message(err, _lang))
            raise CharacterNameError(err.code, "{text}", {"text": text},
                                     char=err.char) from err

    # The free mode creates only: an existing character (by the name it would
    # be stored under) is refused instead of edited.
    if must_be_new and (not _is_new or _row_exists(char_name)):
        raise ValueError(f"Character '{char_name}' already exists")

    profile_fields, config_fields = _get_generable_fields(template)
    stat_keys = status_field_keys(template)
    stat_warnings: List[str] = []

    from app.models.character_template import get_template
    from app.models.character import get_character_dir

    # SERIALIZED PER CHARACTER (``character_profile``): from the read to the
    # save this is one read-modify-write of the whole profile. The apply runs
    # in a worker thread, so a concurrent writer of
    # the same character (a profile patch, an equip) would otherwise be
    # overwritten with the pre-state this call read.
    from app.core.keyed_lock import keyed_lock
    with keyed_lock("character_profile", char_name):
        profile = get_character_profile(char_name)
        if not profile.get("character_name"):
            profile["character_name"] = char_name
            profile["template"] = template
            profile["created_by"] = created_by or "world_dev"

        tmpl = get_template(template)
        soul_field_map: Dict[str, str] = {}
        if tmpl:
            for section in tmpl.get("sections", []):
                for field in section.get("fields", []):
                    fk = field.get("key", "")
                    sf = field.get("source_file", "")
                    if fk and sf:
                        soul_field_map[fk] = sf

        for key in profile_fields:
            if key in soul_field_map or key in stat_keys:
                continue
            if key in char_data:
                profile[key] = char_data[key]

        # Stats live in status_effects (where the hourly tick, the prompt and
        # the stat bars read them), never at the top level.
        status: Dict[str, Any] = {}
        if stat_keys:
            cur_status = profile.get("status_effects")
            status = dict(cur_status) if isinstance(cur_status, dict) else {}
            for key, value in char_data.items():
                if key not in stat_keys:
                    continue
                if _stat_number(value):
                    status[key] = int(value)
                else:
                    stat_warnings.append(f"{key}: {value} is not a whole number 0-100 — skipped.")

        if tmpl:
            for section in tmpl.get("sections", []):
                for field in section.get("fields", []):
                    key = field.get("key", "")
                    default = field.get("default")
                    if not key or default is None:
                        continue
                    if key in soul_field_map:
                        continue
                    if key in stat_keys:
                        status.setdefault(key, default)
                        continue
                    if key not in profile:
                        profile[key] = default
                    elif key == "roleplay_instructions" and isinstance(default, str) and default:
                        current = str(profile[key])
                        if default not in current:
                            profile[key] = default + "\n\n" + current

        if stat_keys and (status or "status_effects" in profile):
            profile["status_effects"] = status

        for k in list(profile.keys()):
            if k in soul_field_map:
                profile.pop(k, None)

        if must_be_new:
            if _row_exists(char_name):
                raise ValueError(f"Character '{char_name}' already exists")
            if on_claim is not None:
                on_claim()
        if not save_character_profile(char_name, profile, create_new=_is_new):
            raise ValueError(f"The profile of '{char_name}' was not stored")

    # A linked character's SHARED soul sections belong to its leader: an
    # applied JSON never writes them (neither the leader's file nor a dead
    # copy beside the body) — they are edited on the leader.
    # Soul markdown goes through soul_writer.write_text: atomic, under the
    # soul_file lock, source-file cache invalidated in a finally.
    from app.core import soul_writer
    from app.core.linked_characters import soul_owner

    if soul_field_map:
        get_character_dir(char_name, create=True)
        for fk, rel_path in soul_field_map.items():
            content = char_data.get(fk)
            if content is None or not str(content).strip():
                continue
            if soul_owner(char_name, rel_path) != char_name:
                logger.info("WorldDev: %s of %s is shared with %s — not applied",
                            rel_path, char_name, soul_owner(char_name, rel_path))
                continue
            soul_writer.write_text(char_name, rel_path, str(content))

    # Extra soul MDs (sections without template source_file mapping —
    # Smart import may render nested ``"# Soul"``/``"# Tasks"`` headings there).
    extra_md = char_data.get("_extra_soul_md") or {}
    if isinstance(extra_md, dict) and extra_md:
        from app.core.soul_sections import SECTION_FILE_MAP
        get_character_dir(char_name, create=True)
        for section_key, content in extra_md.items():
            rel = SECTION_FILE_MAP.get(section_key)
            if not rel or not str(content or "").strip():
                continue
            if soul_owner(char_name, rel) != char_name:
                logger.info("WorldDev: %s of %s is shared with %s — not applied",
                            rel, char_name, soul_owner(char_name, rel))
                continue
            soul_writer.write_text(char_name, rel, str(content))

    config = get_character_config(char_name)
    config_changed = False
    for key in config_fields:
        if key in char_data:
            config[key] = str(char_data[key])
            config_changed = True

    # Ignore the removed allowed_locations field if the LLM still emits it.
    char_data.pop("allowed_locations", None)

    # New characters explicitly start with empty known_locations. Otherwise
    # SetLocation's legacy missing-field bypass permits arbitrary travel
    # before the character is placed or guided.
    if _is_new and "known_locations" not in config:
        config["known_locations"] = []
        config_changed = True

    # Without an explicit mode a character runs `single` (dependencies.
    # get_chat_mode), which an RP model cannot drive: it announces a move and
    # never calls the tool. A new World-Dev character starts in `rp_first`; a
    # temporary NPC keeps the NPC pipeline's own setup.
    from app.models.character import is_temporary_npc
    if (_is_new and not config.get("chat_mode")
            and not is_temporary_npc(char_name)):
        config["chat_mode"] = "rp_first"
        config_changed = True

    if config_changed and not save_character_config(char_name, config):
        raise ValueError(f"The configuration of '{char_name}' was not stored")

    # Same starting repertoire as a character created in the Characters tab.
    # A temporary NPC gets its closed list from npc_ops.activate_default_skills.
    if _is_new and not is_temporary_npc(char_name):
        from app.core.character_ops import seed_default_skills
        seed_default_skills(char_name)

    outfits_applied = []
    created_items: List[str] = []
    # After the profile save: the slots that apply depend on the stored
    # template and gender.
    apply_warnings: List[str] = stat_warnings + _apply_body_slots(
        char_name, char_data.get("body_slots"), body_attributes)
    raw_outfits = char_data.get("outfits", []) or []
    if raw_outfits and not _template_has_wardrobe(template):
        apply_warnings.append(
            f"Template '{template}' has no outfit system — {len(raw_outfits)} "
            "outfit(s) dropped; clothing belongs in outfit_description.")
        logger.info("WorldDev: dropped %d outfit(s) for '%s' — template %s "
                    "has no outfit system", len(raw_outfits), char_name, template)
        raw_outfits = []
    for outfit in raw_outfits:
        applied = _apply_one_outfit(char_name, outfit, on_item=on_item)
        created_items.extend(applied.pop("created_items", []))
        apply_warnings.extend(applied.pop("warnings", []))
        outfits_applied.append(applied)
    # After the outfits: placing a new character at home runs the outfit
    # compliance of that place, which needs the wardrobe to exist.
    apply_warnings.extend(_apply_home_and_schedule(char_name, char_data, _is_new,
                                                   compliance=place_compliance))

    logger.info("WorldDev: Character '%s' (template=%s) applied", char_name, template)
    return {"status": "success", "character": char_name, "template": template,
            "outfits": outfits_applied, "warnings": apply_warnings,
            "created_items": created_items}


def _apply_body_slots(char_name: str, raw: Any,
                      body_attributes: Optional[Callable[[Any], Dict[str, Dict[str, Any]]]] = None
                      ) -> List[str]:
    """Stores LLM-proposed body-slot values through the editor setter
    (``character_ops.apply_body_slot_values``, merge per attribute). Only the
    slots that apply to the character and the attributes ``body_attributes``
    offers (default ``llm_fillable_attributes``, the set of the prompt) are
    taken; everything skipped comes back as a warning."""
    if not raw:
        return []
    if not isinstance(raw, dict):
        return ["body_slots is not an object — skipped."]
    from app.core.body_slots import llm_fillable_attributes, slots_for_character
    if body_attributes is None:
        body_attributes = llm_fillable_attributes
    from app.core.character_ops import apply_body_slot_values
    specs = {spec.id: spec for spec in slots_for_character(char_name)}
    warnings: List[str] = []
    for slot_id, values in raw.items():
        spec = specs.get(str(slot_id))
        if spec is None or not isinstance(values, dict):
            warnings.append(f"Body slot '{slot_id}' does not apply to "
                            f"{char_name} — skipped.")
            continue
        allowed = body_attributes(spec)
        clean: Dict[str, str] = {}
        for key, value in values.items():
            decl = allowed.get(key)
            text = str(value if value is not None else "").strip()
            if decl is None:
                warnings.append(f"Body slot '{slot_id}': attribute '{key}' "
                                "cannot be set here — skipped.")
                continue
            if not text:
                continue
            options = [str(o) for o in (decl.get("options") or [])]
            if options and not decl.get("allow_custom") and text not in options:
                warnings.append(f"Body slot '{slot_id}': '{text}' is not a valid "
                                f"{key} — skipped.")
                continue
            clean[key] = text
        if not clean:
            continue
        try:
            apply_body_slot_values(char_name, spec.id, clean)
        except HTTPException as e:
            warnings.append(f"Body slot '{slot_id}': {e.detail}")
    return warnings


_HOME_SCHEDULE_KEYS = ("home_location", "home_room", "daily_schedule")


def _resolve_world_location(identifier: Any) -> Optional[Dict[str, Any]]:
    """A location by exact id or exact (case-insensitive) name. Deliberately no
    substring match (``resolve_location`` has one): an LLM naming a place that
    does not exist must become a warning, not the nearest similar name."""
    from app.models.world import list_locations
    ident = str(identifier or "").strip()
    if not ident:
        return None
    locations = list_locations()
    for loc in locations:
        if loc.get("id") == ident:
            return loc
    folded = ident.casefold()
    for loc in locations:
        if str(loc.get("name") or "").strip().casefold() == folded:
            return loc
    return None


def _resolve_room_id(location: Dict[str, Any], identifier: Any) -> str:
    """A named room of the location by id or case-insensitive name; "" when
    none matches. The reserved ground/corridor rooms carry no name and are
    never a home room."""
    ident = str(identifier or "").strip()
    if not ident:
        return ""
    folded = ident.casefold()
    for room in location.get("rooms") or []:
        name = str(room.get("name") or "").strip()
        if name and (room.get("id") == ident or name.casefold() == folded):
            return str(room.get("id") or "")
    return ""


def _apply_home_and_schedule(char_name: str, data: Dict[str, Any],
                             is_new: bool, compliance: bool = True) -> List[str]:
    """Home, daily schedule and known places from a World-Dev draft.

    Writes only what the draft carries. ``known_locations`` gains the home and
    every schedule place — for a NEW character that is the whole list, an edit
    only adds. Only a new character is placed at its home; an edit never moves
    anybody. A temporary NPC is left alone (its home and rhythm come from its
    slot; ``npc_ops`` places it). Returns warnings for everything skipped.

    The first placement of a new character is SILENT: no movement narration
    (it never left anywhere — the lines would also land in the perception of
    everyone already in that room) and no compliance run per step, which
    would judge a half-placed character and leave a notification behind.
    With ``compliance`` the compliance runs once, after the placement."""
    from app.models.character import (add_known_location, is_temporary_npc,
                                      save_character_current_location,
                                      save_character_current_room,
                                      save_character_daily_schedule,
                                      set_known_locations)
    if not any(data.get(k) for k in _HOME_SCHEDULE_KEYS):
        return []
    if is_temporary_npc(char_name):
        return ["Home and daily schedule are ignored for a temporary NPC."]
    warnings: List[str] = []
    places: List[str] = []

    home = None
    home_room = ""
    if data.get("home_location"):
        home = _resolve_world_location(data["home_location"])
        if home is None:
            warnings.append(f"Home '{data['home_location']}' is no place of this "
                            "world — skipped.")
        else:
            places.append(home["id"])
            if data.get("home_room"):
                home_room = _resolve_room_id(home, data["home_room"])
                if not home_room:
                    warnings.append(f"Room '{data['home_room']}' does not exist in "
                                    f"{home.get('name')} — home without a room.")
            cfg = get_character_config(char_name)
            # The same home again without a room (an edit draft that left the
            # room out) keeps the room; a NEW home starts without the old one.
            if not data.get("home_room") and cfg.get("home_location") == home["id"]:
                home_room = str(cfg.get("home_room") or "")
            cfg["home_location"] = home["id"]
            cfg["home_room"] = home_room
            if not save_character_config(char_name, cfg):
                raise ValueError(f"The home of '{char_name}' was not stored")
    elif data.get("home_room"):
        # A room alone (a patch) refers to the home the character already has.
        cfg = get_character_config(char_name)
        current = _resolve_world_location(cfg.get("home_location"))
        home_room = _resolve_room_id(current, data["home_room"]) if current else ""
        if home_room:
            cfg["home_room"] = home_room
            if not save_character_config(char_name, cfg):
                raise ValueError(f"The home room of '{char_name}' was not stored")
        else:
            warnings.append(f"Room '{data['home_room']}' is not a room of the "
                            "character's home — skipped.")

    raw_slots = data.get("daily_schedule")
    if raw_slots:
        slots: Dict[int, Dict[str, Any]] = {}
        for raw in raw_slots if isinstance(raw_slots, list) else []:
            if not isinstance(raw, dict):
                continue
            try:
                hour = int(raw.get("hour"))
            except (TypeError, ValueError):
                warnings.append(f"Schedule slot without a valid hour — skipped: {raw}")
                continue
            if not 0 <= hour <= 23:
                warnings.append(f"Schedule hour {hour} is outside 0-23 — skipped.")
                continue
            if raw.get("sleep"):
                slots[hour] = {"hour": hour, "location": "", "role": "", "sleep": True}
                continue
            role = str(raw.get("role") or "").strip()
            loc_id = ""
            if raw.get("location"):
                loc = _resolve_world_location(raw["location"])
                if loc is None:
                    warnings.append(f"Schedule {hour}:00 — '{raw['location']}' is no "
                                    "place of this world, hour left free.")
                    continue
                loc_id = loc["id"]
                if loc_id not in places:
                    places.append(loc_id)
            if not loc_id and not role:
                continue
            slots[hour] = {"hour": hour, "location": loc_id, "role": role, "sleep": False}
        if not isinstance(raw_slots, list):
            warnings.append("daily_schedule is not a list — skipped.")
        elif slots:
            schedule = {"enabled": True, "slots": [slots[h] for h in sorted(slots)]}
            if save_character_daily_schedule(char_name, schedule):
                try:
                    from app.scheduler.scheduler_manager import get_scheduler_manager
                    get_scheduler_manager().sync_daily_schedule(char_name, schedule)
                except Exception as e:  # the row is stored; the marker is cosmetic
                    logger.warning("WorldDev: schedule marker for %s failed: %s",
                                   char_name, e)
            else:
                warnings.append("Daily schedule was not stored.")

    if places:
        if is_new:
            set_known_locations(char_name, places)
        else:
            for loc_id in places:
                add_known_location(char_name, loc_id)

    if is_new and home is not None:
        save_character_current_location(char_name, home["id"],
                                        _skip_compliance=True)
        if home_room:
            save_character_current_room(char_name, home_room,
                                        _initial_placement=True)
        if compliance:
            try:
                from app.core.outfit_compliance import apply_outfit_compliance
                apply_outfit_compliance(char_name)
            except Exception as e:  # noqa: BLE001 — placement is stored
                logger.warning("WorldDev: outfit compliance for %s failed: %s",
                               char_name, e)
    return warnings


def _template_has_wardrobe(template_name: str) -> bool:
    """False when the character template disables the outfit system
    (``outfit_system_enabled: false`` — e.g. ``npc-temporary``, whose clothing
    is the ``outfit_description`` prompt text, never wardrobe pieces).
    Applying wardrobe pieces for such a template would litter the global item
    catalog with throwaway clothing, one heap per disposable NPC."""
    from app.models.character_template import get_template
    tmpl = get_template(template_name) or {}
    return (tmpl.get("features") or {}).get("outfit_system_enabled") is not False


def _apply_one_outfit(char_name: str, outfit: Dict[str, Any],
                      on_item: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """Create one outfit using deduplicated pieces or a free-text fallback.

    ``on_item(item_id)``: see :func:`apply_character`.

    Returns: {name, pieces_created, pieces_reused, created_items, warnings} —
    ``created_items`` are the ids of the catalog items ``add_item`` created,
    ``warnings`` name every piece that was skipped (also logged).
    """
    if not outfit.get("name"):
        return {"name": "", "pieces_created": 0, "pieces_reused": 0,
                "created_items": [], "warnings": []}
    raw_pieces = outfit.get("pieces") or []
    if raw_pieces and isinstance(raw_pieces[0], dict):
        from app.models.inventory import (
            add_item, add_to_inventory, find_inventory_piece_by_name_slot,
            get_item, has_item, VALID_PIECE_SLOTS)
        piece_ids: List[str] = []
        created_ids: List[str] = []
        warnings: List[str] = []
        created = reused = 0
        for p in raw_pieces:
            # An EXISTING catalog piece, named by its id (the World Dev free
            # mode dresses a new character in pieces the world already has):
            # handed to the character, never created, never in created_items.
            ref = str(p.get("item_id") or "").strip()
            if ref:
                ref_item = get_item(ref)
                if not ref_item or ref_item.get("category") != "outfit_piece":
                    logger.warning("WorldDev outfit '%s': no outfit piece %r — skipped",
                                   outfit.get("name"), ref)
                    warnings.append(f"Outfit '{outfit.get('name')}': no outfit piece "
                                    f"'{ref}' — skipped.")
                    continue
                if not has_item(char_name, ref):
                    add_to_inventory(character_name=char_name, item_id=ref,
                                     obtained_method="generated",
                                     obtained_from="world_dev")
                piece_ids.append(ref)
                reused += 1
                continue
            # Schema: {slots: [...], name, prompt_fragment, outfit_types, covers, partially_covers}.
            # Do not interpret legacy slot/additional_slots input;
            # add_item rejects it with "needs non-empty 'slots' list".
            slots = [str(s or "").strip().lower() for s in (p.get("slots") or []) if s]
            slots = [s for s in slots if s in VALID_PIECE_SLOTS]
            name = (p.get("name") or "").strip()
            fragment = (p.get("prompt_fragment") or "").strip()
            if not slots or not name:
                logger.warning("WorldDev outfit '%s': Piece skipped (slots=%r, name=%r)",
                               outfit.get("name"), slots, name)
                warnings.append(f"Outfit '{outfit.get('name')}': a piece without a "
                                "valid slot or name — skipped.")
                continue
            existing = find_inventory_piece_by_name_slot(
                char_name, name, slots[0], prompt_fragment=fragment)
            if existing:
                piece_ids.append(existing)
                reused += 1
                continue
            item = add_item(
                name=name,
                description=(p.get("description") or "").strip(),
                category="outfit_piece",
                image_prompt="",
                prompt_fragment=fragment,
                outfit_piece={
                    "slots": slots,
                    "covers": p.get("covers") or [],
                    "partially_covers": p.get("partially_covers") or [],
                })
            iid = item.get("id")
            if not iid:
                logger.warning("WorldDev outfit '%s': add_item failed for '%s'",
                               outfit.get("name"), name)
                warnings.append(f"Outfit '{outfit.get('name')}': piece '{name}' "
                                "could not be created — skipped.")
                continue
            if on_item is not None:
                on_item(str(iid))
            add_to_inventory(character_name=char_name, item_id=iid,
                obtained_method="generated", obtained_from="world_dev")
            piece_ids.append(iid)
            created_ids.append(iid)
            created += 1
        frags = [str((get_item(str(p["item_id"]).strip()) or {}).get("prompt_fragment")
                     or "").strip() if p.get("item_id")
                 else (p.get("prompt_fragment") or "").strip()
                 for p in raw_pieces if isinstance(p, dict)]
        outfit_text = "wearing: " + ", ".join(f for f in frags if f) if any(frags) else ""
        add_character_outfit(char_name, {
            "name": outfit["name"],
            "outfit": outfit_text,
            "pieces": piece_ids,
            "locations": outfit.get("locations") or [],
            "activities": outfit.get("activities") or [],
            "excluded_locations": outfit.get("excluded_locations") or [],
        })
        logger.info("WorldDev outfit '%s': %d new, %d reused", outfit["name"], created, reused)
        return {"name": outfit["name"], "pieces_created": created,
                "pieces_reused": reused, "created_items": created_ids,
                "warnings": warnings}
    # Old path: free-text outfit.
    add_character_outfit(char_name, outfit)
    return {"name": outfit["name"], "pieces_created": 0, "pieces_reused": 0,
            "created_items": [], "warnings": []}


def _map_world_context() -> Tuple[Dict[str, Any], Dict[str, Any], Any, str]:
    """(catalog, locations_by_id, world bounds, default terrain kind).

    The four world facts ``map_layout_apply.sanitize_map_layout`` needs handed
    in — it is a pure function on purpose, so this is the ONE place that reads
    them out of the world.
    """
    from app.core.location_model3d import derive_plan_width_m
    from app.core.map_layout_apply import current_world_bounds
    from app.core.terrain_types import effective_catalog
    from app.models.world import list_locations

    locations_by_id: Dict[str, Any] = {}
    for loc in list_locations():
        loc_id = loc.get("id") or ""
        if not loc_id:
            continue
        map3d = loc.get("map3d") or {}
        locations_by_id[loc_id] = {
            "name": loc.get("name") or loc_id,
            # The DRAWN outline (contract v6) — the ONLY shape a location
            # has since 2026-08-19; a place without one has no area and the
            # overlap test simply skips it. ``plan_width_m`` rides along as
            # the derived bounding-box width the prompt quotes, never as a
            # shape of its own.
            "boundary": map3d.get("boundary"),
            "plan_width_m": derive_plan_width_m(loc_id, map3d),
        }
    return (effective_catalog(), locations_by_id, current_world_bounds(),
            default_terrain_kind())


def default_terrain_kind() -> str:
    """The terrain kind of ground no area covers (``game.default_terrain_kind``).

    Split out of :func:`_map_world_context` for readers that need only the
    ground, not every location's outline and the world bounds.
    """
    from app.core import config
    return str(config.get("game.default_terrain_kind", "grass") or "grass")
