"""World Dev character apply — the core behind the World Dev routes.

One character draft (profile fields, soul sections, config fields, body
slots, outfits, home and daily schedule) is written through the character
model savers. Called by the World Dev routes (``/apply-character``,
``/apply-json``, the outfit and profile-patch routes), by the temp-NPC
generator (``npc_ops.apply_npc``) and by the World Dev free mode. Errors are
``ValueError``; the routes map them to HTTP 400.

Also home of ``_map_world_context``, the one reader of the world facts the
map-layout sanitizer needs.
"""
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException

from app.core.log import get_logger
from app.models.character import (
    add_character_outfit, get_character_config, get_character_profile,
    save_character_config, save_character_profile)

logger = get_logger("world_dev")


def _row_exists(char_name: str) -> bool:
    """Whether a ``characters`` row with exactly this name exists."""
    from app.core.db import get_connection
    from app.models.character import _character_row_exists
    try:
        return _character_row_exists(get_connection(), char_name)
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


def apply_character(char_data: Dict[str, Any],
                    selected_template: str = "",
                    created_by: str = "",
                    must_be_new: bool = False) -> Dict[str, Any]:
    """Apply character JSON in-process (profile + soul MD + outfits + config).

    Used by /apply-character (HTTP), /apply-json (smart import), the temp-NPC
    generator (``npc_ops.apply_npc``) and the World Dev free mode. Caller
    is responsible for handing in a *normalized* dict — flat fields, no nested
    soul object. Sub-sections without a template source_file mapping (e.g.
    soul/soul.md, soul/tasks.md) can be passed via the special key
    ``_extra_soul_md`` as ``{"<section>": "<full markdown>"}``.

    Raises ``ValueError`` (a ``CharacterNameError`` for a name the rule
    refuses) — the routes map it to a 400. With ``must_be_new=True`` a
    character whose VALIDATED name already exists is a ``ValueError`` too,
    before anything is written.

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
    # text; the routes turn every ValueError into a 400 with that text, so the
    # World Dev tab shows it in its error toast as before.
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

    from app.models.character_template import get_template
    from app.models.character import get_character_dir

    # SERIALIZED PER CHARACTER (``character_profile``): from the read to the
    # save this is one read-modify-write of the whole profile. The apply runs
    # in the threadpool like every other route body, so a concurrent writer of
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
            if key in soul_field_map:
                continue
            if key in char_data:
                profile[key] = char_data[key]

        if tmpl:
            for section in tmpl.get("sections", []):
                for field in section.get("fields", []):
                    key = field.get("key", "")
                    default = field.get("default")
                    if not key or default is None:
                        continue
                    if key in soul_field_map:
                        continue
                    if key not in profile:
                        profile[key] = default
                    elif key == "roleplay_instructions" and isinstance(default, str) and default:
                        current = str(profile[key])
                        if default not in current:
                            profile[key] = default + "\n\n" + current

        for k in list(profile.keys()):
            if k in soul_field_map:
                profile.pop(k, None)

        save_character_profile(char_name, profile, create_new=_is_new)

    # A linked character's SHARED soul sections belong to its leader: an
    # applied JSON never writes them (neither the leader's file nor a dead
    # copy beside the body) — they are edited on the leader.
    from app.core.linked_characters import soul_owner
    from app.models.character_template import invalidate_source_file

    if soul_field_map:
        char_dir = get_character_dir(char_name, create=True)
        for fk, rel_path in soul_field_map.items():
            content = char_data.get(fk)
            if content is None or not str(content).strip():
                continue
            if soul_owner(char_name, rel_path) != char_name:
                logger.info("WorldDev: %s of %s is shared with %s — not applied",
                            rel_path, char_name, soul_owner(char_name, rel_path))
                continue
            md_path = char_dir / rel_path
            md_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                md_path.write_text(str(content).rstrip() + "\n", encoding="utf-8")
            finally:
                invalidate_source_file(md_path)

    # Extra soul MDs (sections without template source_file mapping —
    # Smart import may render nested ``"# Soul"``/``"# Tasks"`` headings there).
    extra_md = char_data.get("_extra_soul_md") or {}
    if isinstance(extra_md, dict) and extra_md:
        from app.core.soul_sections import SECTION_FILE_MAP
        char_dir = get_character_dir(char_name, create=True)
        for section_key, content in extra_md.items():
            rel = SECTION_FILE_MAP.get(section_key)
            if not rel or not str(content or "").strip():
                continue
            if soul_owner(char_name, rel) != char_name:
                logger.info("WorldDev: %s of %s is shared with %s — not applied",
                            rel, char_name, soul_owner(char_name, rel))
                continue
            md_path = char_dir / rel
            md_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                md_path.write_text(str(content).rstrip() + "\n", encoding="utf-8")
            finally:
                invalidate_source_file(md_path)

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

    if config_changed:
        save_character_config(char_name, config)

    # Same starting repertoire as a character created in the Characters tab.
    # A temporary NPC gets its closed list from npc_ops.activate_default_skills.
    if _is_new and not is_temporary_npc(char_name):
        from app.core.character_ops import seed_default_skills
        seed_default_skills(char_name)

    outfits_applied = []
    created_items: List[str] = []
    # After the profile save: the slots that apply depend on the stored
    # template and gender.
    apply_warnings: List[str] = _apply_body_slots(char_name,
                                                  char_data.get("body_slots"))
    raw_outfits = char_data.get("outfits", []) or []
    if raw_outfits and not _template_has_wardrobe(template):
        apply_warnings.append(
            f"Template '{template}' has no outfit system — {len(raw_outfits)} "
            "outfit(s) dropped; clothing belongs in outfit_description.")
        logger.info("WorldDev: dropped %d outfit(s) for '%s' — template %s "
                    "has no outfit system", len(raw_outfits), char_name, template)
        raw_outfits = []
    for outfit in raw_outfits:
        applied = _apply_one_outfit(char_name, outfit)
        created_items.extend(applied.pop("created_items", []))
        outfits_applied.append(applied)
    # After the outfits: placing a new character at home runs the outfit
    # compliance of that place, which needs the wardrobe to exist.
    apply_warnings.extend(_apply_home_and_schedule(char_name, char_data, _is_new))

    logger.info("WorldDev: Character '%s' (template=%s) applied", char_name, template)
    return {"status": "success", "character": char_name, "template": template,
            "outfits": outfits_applied, "warnings": apply_warnings,
            "created_items": created_items}


def _apply_body_slots(char_name: str, raw: Any) -> List[str]:
    """Stores LLM-proposed body-slot values through the editor setter
    (``character_ops.apply_body_slot_values``, merge per attribute). Only the
    slots that apply to the character and the attributes offered in the prompt
    are taken; everything skipped comes back as a warning."""
    if not raw:
        return []
    if not isinstance(raw, dict):
        return ["body_slots is not an object — skipped."]
    from app.core.body_slots import llm_fillable_attributes, slots_for_character
    from app.core.character_ops import apply_body_slot_values
    specs = {spec.id: spec for spec in slots_for_character(char_name)}
    warnings: List[str] = []
    for slot_id, values in raw.items():
        spec = specs.get(str(slot_id))
        if spec is None or not isinstance(values, dict):
            warnings.append(f"Body slot '{slot_id}' does not apply to "
                            f"{char_name} — skipped.")
            continue
        allowed = llm_fillable_attributes(spec)
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


def _home_schedule_for_edit(char_name: str) -> Dict[str, Any]:
    """The character's current home and daily schedule in the draft's own
    shape — place and room NAMES, as the LLM writes them — for the edit
    context. Empty keys are left out."""
    from app.models.character import get_character_daily_schedule
    from app.models.world import get_location_by_id

    def place_name(loc_id: str) -> str:
        loc = get_location_by_id(loc_id) if loc_id else None
        return str((loc or {}).get("name") or loc_id or "")

    out: Dict[str, Any] = {}
    cfg = get_character_config(char_name) or {}
    home_id = str(cfg.get("home_location") or "").strip()
    home = get_location_by_id(home_id) if home_id else None
    if home:
        out["home_location"] = home.get("name") or home_id
        room_id = str(cfg.get("home_room") or "").strip()
        room = next((r for r in home.get("rooms") or [] if r.get("id") == room_id), None)
        if room and room.get("name"):
            out["home_room"] = room["name"]
    schedule = get_character_daily_schedule(char_name) or {}
    if schedule.get("enabled") and schedule.get("slots"):
        out["daily_schedule"] = [
            {"hour": s["hour"], "sleep": True} if s.get("sleep") else
            {"hour": s["hour"], "location": place_name(s.get("location") or ""),
             "role": s.get("role") or ""}
            for s in schedule["slots"]]
    return out


def _apply_home_and_schedule(char_name: str, data: Dict[str, Any],
                             is_new: bool) -> List[str]:
    """Home, daily schedule and known places from a World-Dev draft.

    Writes only what the draft carries. ``known_locations`` gains the home and
    every schedule place — for a NEW character that is the whole list, an edit
    only adds. Only a new character is placed at its home; an edit never moves
    anybody. A temporary NPC is left alone (its home and rhythm come from its
    slot; ``npc_ops`` places it). Returns warnings for everything skipped."""
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
            save_character_config(char_name, cfg)
    elif data.get("home_room"):
        # A room alone (a patch) refers to the home the character already has.
        cfg = get_character_config(char_name)
        current = _resolve_world_location(cfg.get("home_location"))
        home_room = _resolve_room_id(current, data["home_room"]) if current else ""
        if home_room:
            cfg["home_room"] = home_room
            save_character_config(char_name, cfg)
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
        save_character_current_location(char_name, home["id"])
        if home_room:
            save_character_current_room(char_name, home_room)
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


def _apply_one_outfit(char_name: str, outfit: Dict[str, Any]) -> Dict[str, Any]:
    """Create one outfit using deduplicated pieces or a free-text fallback.

    Returns: {name, pieces_created, pieces_reused, created_items} —
    ``created_items`` are the ids of the catalog items ``add_item`` created.
    """
    if not outfit.get("name"):
        return {"name": "", "pieces_created": 0, "pieces_reused": 0,
                "created_items": []}
    raw_pieces = outfit.get("pieces") or []
    if raw_pieces and isinstance(raw_pieces[0], dict):
        from app.models.inventory import (
            add_item, add_to_inventory, find_inventory_piece_by_name_slot,
            VALID_PIECE_SLOTS)
        piece_ids: List[str] = []
        created_ids: List[str] = []
        created = reused = 0
        for p in raw_pieces:
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
                continue
            add_to_inventory(character_name=char_name, item_id=iid,
                obtained_method="generated", obtained_from="world_dev")
            piece_ids.append(iid)
            created_ids.append(iid)
            created += 1
        frags = [(p.get("prompt_fragment") or "").strip()
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
                "pieces_reused": reused, "created_items": created_ids}
    # Old path: free-text outfit.
    add_character_outfit(char_name, outfit)
    return {"name": outfit["name"], "pieces_created": 0, "pieces_reused": 0,
            "created_items": []}


def _map_world_context() -> Tuple[Dict[str, Any], Dict[str, Any], Any, str]:
    """(catalog, locations_by_id, world bounds, default terrain kind).

    The four world facts ``map_layout_apply.sanitize_map_layout`` needs handed
    in — it is a pure function on purpose, so this is the ONE place that reads
    them out of the world.
    """
    from app.core import config
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
    default_kind = str(config.get("game.default_terrain_kind", "grass")
                       or "grass")
    return (effective_catalog(), locations_by_id, current_world_bounds(),
            default_kind)
