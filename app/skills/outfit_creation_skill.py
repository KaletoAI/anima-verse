"""Outfit Creation Skill — creates new outfit pieces (items) via the LLM.

The skill generates single garments (outfit_piece items) with a slots list
(e.g. ["top"] or multi-slot ["top","bottom"] for dresses), a prompt_fragment
and outfit_types. The pieces go into the character's inventory and are
equipped right away.

The sister skill ChangeOutfit switches between pieces that already exist.
"""
import json
import os
import re
from datetime import datetime

from app.core.timeutils import utc_now
from typing import Any, Dict, List, Optional, Set

from .base import BaseSkill

from app.core.log import get_logger
from app.core.outfit_coherence import (
    CANONICAL_OUTFIT_TYPES, DEFAULT_OUTFIT_TYPE, normalize_outfit_types)
from app.core.task_queue import get_task_queue
from app.models.character import (
    get_character_appearance,
    get_character_personality,
    get_character_current_location,
    get_effective_activity,
    get_character_current_feeling)
from app.models.inventory import (
    add_item, add_to_inventory, get_character_inventory,
    equip_piece,
    find_inventory_piece_by_name_slot,
    VALID_PIECE_SLOTS)
from app.models.world import get_location

logger = get_logger("outfit_creation")


def build_context_block(*, location_label: str = "", location_desc: str = "",
                        activity: str = "", feeling: str = "",
                        style_hint: str = "", decency: str = "",
                        lang: str = "en") -> str:
    """The ``context_block`` of ``tasks/outfit_generation.md``.

    Everything the dressing LLM knows about the situation, one fact per line.
    The last two come from the world calendar: the template has always told
    the model to add outerwear "when context (weather/activity) fits" —
    without ever saying what the weather IS. Season and atmosphere are pure
    prompt info, nothing in the code checks the resulting outfit against
    them. Localized like every other prompt line the character sees: season
    names are localized data fields, the atmosphere levels go through
    ``t(en, lang)``.

    Pulled out of ``execute()`` so it can be rendered without a world
    (``scripts/smoke_game_weather_prompts.py``).
    """
    from app.core.timeutils import game_time

    lines: List[str] = []
    if location_label:
        lines.append(f"Location: {location_label}"
                     + (f" ({location_desc})" if location_desc else ""))
    if activity:
        lines.append(f"Activity: {activity}")
    if feeling:
        lines.append(f"Mood: {feeling}")
    if style_hint:
        lines.append(f"Style: {style_hint}")
    if decency:
        lines.append(f"Decency: {decency}")

    now = game_time()
    season = now.season_name(lang)
    if season:
        lines.append(f"Season: {season}")
    lines.append(f"Weather: {now.atmosphere(lang)['label']}")
    return "\n".join(lines) or "(no specific context)"


def _ensure_outfit_types(raw: Any, piece_name: str) -> List[str]:
    """The piece's tags, guaranteed non-empty.

    Normalising first drops anything outside the closed vocabulary. If nothing
    survives — after the correction retry above — the piece still gets created,
    with a documented default: an untagged piece would be a wildcard in every
    coherence check, and blocking the creation would be worse than a slightly
    wrong tag the admin can fix.
    """
    types = normalize_outfit_types(raw)
    if types:
        return types
    logger.warning("Outfit-Piece '%s' ohne verwertbare outfit_types — "
                   "Default '%s'", piece_name, DEFAULT_OUTFIT_TYPE)
    return [DEFAULT_OUTFIT_TYPE]


class OutfitCreationSkill(BaseSkill):
    """Generates new outfit pieces and creates them right away.

    Flow:
    1. Gather context (location + outfit_type, activity, mood,
       personality, existing pieces)
    2. The LLM generates a list of piece drafts (slots, name,
       prompt_fragment, outfit_types)
    3. Each piece is created as an outfit_piece item + put into the inventory
    4. equip_piece clears displaced pieces in the target slots
       symmetrically (multi-slot pieces occupy all their slots).
    """

    SKILL_ID = "outfit_creation"
    ALWAYS_LOAD = True

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        from app.core.prompt_templates import load_skill_meta
        meta = load_skill_meta("outfit_creation")
        self.name = meta["name"]
        self.description = meta["description"]
        self.action_hint = meta.get("action_hint", "")
        self._defaults = {
            "enabled": True,
            "outfit_language": os.environ.get('SKILL_OUTFIT_CREATION_LANGUAGE', 'en'),
            # The daily limit counts created PIECES, not outfits.
            "max_daily_items": int(os.environ.get('SKILL_OUTFIT_CREATION_MAX_DAILY_ITEMS', '8')),
            # Inventory limit: at most this many outfit_piece items per character
            "max_inventory_pieces": int(os.environ.get('SKILL_OUTFIT_CREATION_MAX_INVENTORY', '60')),
        }
        logger.info("OutfitCreation Skill initialized (piece-based)")

    def get_config_fields(self) -> dict:
        fields = super().get_config_fields()
        if "max_daily_items" in fields:
            fields["max_daily_items"]["label"] = "Max. pieces per day"
        if "max_inventory_pieces" in fields:
            fields["max_inventory_pieces"]["label"] = "Max. pieces in inventory"
        if "outfit_language" in fields:
            fields["outfit_language"]["label"] = "Language of piece names"
        return fields

    # ------------------------------------------------------------------
    # Limits
    # ------------------------------------------------------------------

    def is_limit_reached(self, character_name: str) -> bool:
        cfg = self._get_effective_config(character_name)
        if not cfg.get("enabled", True):
            return True
        max_daily = cfg.get("max_daily_items", 8)
        if max_daily <= 0:
            return False
        return self._count_today_items(character_name) >= max_daily

    def _count_today_items(self, character_name: str) -> int:
        """Count the outfit_piece items that landed in the character's
        inventory today (obtained_at starts with today's date)."""
        today = utc_now().strftime("%Y-%m-%d")
        try:
            inv_data = get_character_inventory(character_name, include_equipped=True)
            items = (inv_data or {}).get("inventory", [])
        except Exception:
            return 0
        count = 0
        for e in items:
            if e.get("item_category") != "outfit_piece":
                continue
            obtained = (e.get("obtained_at") or "").strip()
            if obtained.startswith(today):
                count += 1
        return count

    def _count_inventory_pieces(self, character_name: str) -> int:
        try:
            inv = get_character_inventory(character_name, include_equipped=True)
            return sum(1 for e in (inv or {}).get("inventory", [])
                       if e.get("item_category") == "outfit_piece")
        except Exception:
            return 0

    # ------------------------------------------------------------------
    # Context — the wanted outfit type from location/room
    # ------------------------------------------------------------------

    def _resolve_style_context(self, character_name: str):
        """Return (style_hint, decency) from the current room (fallback: the
        location). Replaces the former outfit_type model — decency is the
        hard coverage rule, style_hint the free style direction.
        """
        try:
            from app.models.character import (get_character_current_location,
                                              get_character_current_room)
            from app.models.world import get_location_by_id
            loc_id = get_character_current_location(character_name) or ""
            if not loc_id:
                return "", ""
            loc = get_location_by_id(loc_id) or {}
            room_id = get_character_current_room(character_name) or ""
            style, decency = "", ""
            if room_id:
                for r in (loc.get("rooms") or []):
                    if r.get("id") == room_id or r.get("name") == room_id:
                        style = (r.get("style_hint") or "").strip()
                        decency = (r.get("decency") or "").strip()
                        break
            if not style:
                style = (loc.get("style_hint") or "").strip()
            if not decency:
                decency = (loc.get("decency") or "").strip()
            return style, decency
        except Exception:
            return "", ""

    # ------------------------------------------------------------------
    # LLM call
    # ------------------------------------------------------------------

    def _generate_pieces_via_llm(self, character_name: str, personality: str, appearance: str,
                                  context_block: str, style_hint: str, decency: str,
                                  decency_pref: str,
                                  existing_pieces: List[Dict[str, Any]],
                                  hint: str, language: str,
                                  max_pieces: int) -> Optional[List[Dict[str, Any]]]:
        """The LLM produces a list of piece drafts.

        Returns a list of dicts {slots, name, prompt_fragment, covers,
        partially_covers} or None on failure. (No outfit_types any more —
        style comes from style_hint/decency_pref, coverage from decency.)
        """
        # Load the equipped state: occupied slots are marked in the prompt so
        # the LLM knows what is worn right now
        # (→ no needless duplicates, a clear sense of the delta).
        equipped_iids: Set[str] = set()
        try:
            from app.models.inventory import get_equipped_pieces as _gep
            for _slot, _iid in (_gep(character_name) or {}).items():
                if _iid:
                    equipped_iids.add(_iid)
        except Exception:
            equipped_iids = set()

        # Existing pieces as context (the LLM should avoid duplicates).
        # Slots + an [EQUIPPED] marker per piece (no outfit_types any more).
        existing_lines = []
        for p in existing_pieces[-20:]:  # letzte 20 reichen als Kontext
            op = p.get("outfit_piece") or {}
            slot_list = op.get("slots") or []
            slot_str = "+".join(slot_list) if slot_list else "?"
            frag = (p.get("item_prompt_fragment") or "").strip()
            name = p.get("item_name") or p.get("item_id") or "?"
            equipped_marker = " [EQUIPPED]" if p.get("item_id") in equipped_iids else ""
            line = f"- [{slot_str}]{equipped_marker} {name}"
            if frag:
                line += f": {frag}"
            existing_lines.append(line)
        existing_block = "\n".join(existing_lines) if existing_lines else "(none)"

        # Coverage block from decency (replaces the former outfit_type
        # required-slots computation). Decency is the hard rule; the LLM
        # decides everything else by style.
        if decency == "public":
            required_block = ("Decency (public location): top AND bottom MUST be "
                              "covered. Always include a top and a bottom piece "
                              "(unless already [EQUIPPED]).")
        elif decency == "private":
            required_block = ("Decency (private location): coverage is optional — "
                              "dress to the style/mood, partial or full nudity is fine.")
        elif decency == "nude_ok":
            required_block = "Decency (nude_ok): no coverage requirement at all."
        else:
            required_block = ""

        # Style guideline: the room's style_hint + the character's personal
        # decency_preference (replaces outfit_types dress code + outfit_exceptions).
        _style_parts = []
        if style_hint:
            _style_parts.append(f"Match the location's style: '{style_hint}'.")
        else:
            _style_parts.append("Pick one coherent outfit style that fits the context.")
        if decency_pref:
            _style_parts.append(f"{character_name}'s personal dressing preference: {decency_pref}.")
        type_hint = " ".join(_style_parts)
        lang_hint = f"Use {language} for the `name` field." if language and language != "en" else ""

        # Species topology (body-slot packages): the LLM only sees the slots
        # this character's species actually has (a cat gets collar/headwear,
        # not tops and shoes). Falls back to the core list without a package.
        from app.core.body_slots import piece_slots_for_character
        _species_slots = piece_slots_for_character(character_name)
        _species_slot_set = set(_species_slots)
        allowed_slots = ", ".join(_species_slots)

        from app.core.prompt_templates import render_task
        sys_prompt, user_prompt = render_task(
            "outfit_generation",
            character_name=character_name,
            personality=personality or "(not specified)",
            appearance=appearance or "(not specified)",
            context_block=context_block,
            hint_block=f"User hint: {hint}" if hint else "",
            existing_block=existing_block,
            type_hint=type_hint,
            required_block=required_block,
            max_pieces=max_pieces,
            allowed_slots=allowed_slots,
            language_hint=lang_hint,
            outfit_types_vocab=", ".join(CANONICAL_OUTFIT_TYPES))

        try:
            from app.core.llm_router import llm_call

            def _ask(extra: str = "") -> Optional[Dict[str, Any]]:
                response = llm_call(
                    task="outfit_generation",
                    system_prompt=sys_prompt,
                    user_prompt=user_prompt + extra,
                    agent_name=character_name,
                    label="piece_generation")
                return self._extract_json((response.content or "").strip())

            data = _ask()
            if not data or not isinstance(data.get("pieces"), list):
                logger.warning("LLM-Antwort ohne 'pieces'-Liste")
                return None
            # One correction retry when the model ignored the tags: they are
            # what the coherence rule runs on, so a whole outfit of untagged
            # pieces would silently become wildcards.
            if not any(normalize_outfit_types(p.get("outfit_types"))
                       for p in data["pieces"] if isinstance(p, dict)):
                logger.warning("Outfit-Generierung: kein Piece mit gültigem "
                               "outfit_types — ein Korrektur-Versuch")
                retry = _ask(
                    "\n\nCORRECTION: your previous answer had no usable "
                    "`outfit_types`. Every piece needs 1-3 of exactly these "
                    f"words: {', '.join(CANONICAL_OUTFIT_TYPES)}. Return the "
                    "COMPLETE JSON again, with outfit_types on every piece.")
                if retry and isinstance(retry.get("pieces"), list) and any(
                        normalize_outfit_types(p.get("outfit_types"))
                        for p in retry["pieces"] if isinstance(p, dict)):
                    data = retry
            # Slot keyword map: catch obvious LLM slot mistakes.
            # When the name/fragment clearly sounds like another slot,
            # the piece is moved.
            slot_keywords = {
                "outer": ["jacket", "coat", "blazer", "cardigan", "hoodie",
                          "vest", "bolero", "jacke", "mantel"],
                "feet": ["shoes", "boots", "sneakers", "heels", "sandals",
                         "loafers", "pumps", "schuhe", "stiefel"],
                "head": ["hat", "cap", "headband", "fascinator", "hut", "muetze"],
                "neck": ["necklace", "choker", "scarf", "tie", "bowtie",
                         "halskette", "schal", "krawatte"],
                "legs": ["stockings", "pantyhose", "tights", "socks",
                         "struempfe", "strumpf"],
                "underwear_top": ["bra ", "bralette", "nipple", "bh "],
                "underwear_bottom": ["panties", "thong", "briefs", "boxers",
                                     "g-string", "slip", "string"],
            }

            def _infer_slot(name: str, frag: str) -> str:
                combo = (name + " " + frag).lower()
                for slot, kws in slot_keywords.items():
                    for kw in kws:
                        if kw in combo:
                            return slot
                return ""

            # Validate + clean up
            cleaned: List[Dict[str, Any]] = []
            seen_slots = set()  # alle bereits beanspruchten Slots (auch Mirrors)

            def _clean_slot_list(raw, exclude: set) -> List[str]:
                if not isinstance(raw, list):
                    return []
                out: List[str] = []
                seen_ls = set()
                for s in raw:
                    s = str(s or "").strip().lower()
                    if not s or s not in _species_slot_set:
                        continue
                    if s in exclude or s in seen_ls:
                        continue
                    seen_ls.add(s)
                    out.append(s)
                return out

            for p in data["pieces"]:
                if not isinstance(p, dict):
                    continue
                # New schema: slots: [...]. Empty → skip.
                slots = _clean_slot_list(p.get("slots"), exclude=set())
                if not slots:
                    continue
                name = str(p.get("name") or "").strip()
                frag = str(p.get("prompt_fragment") or "").strip()
                if not name or not frag:
                    continue

                # Slot sanity: when the name/fragment clearly sounds like
                # another slot AND the LLM proposed only one slot, correct it.
                # Multi-slot pieces (e.g. a dress top+bottom) stay untouched.
                if len(slots) == 1:
                    inferred = _infer_slot(name, frag)
                    if inferred and inferred != slots[0]:
                        logger.info("Slot-Korrektur: '%s' %s→%s (name/fragment deutet auf %s)",
                                    name, slots[0], inferred, inferred)
                        slots = [inferred]

                # Slot conflict with a piece already placed → skip it entirely.
                if any(s in seen_slots for s in slots):
                    continue

                # covers/partially_covers must not overlap the slots
                # (a slot is physically occupied → nothing to cover).
                covers = _clean_slot_list(p.get("covers"), exclude=set(slots))
                partially = _clean_slot_list(p.get("partially_covers"), exclude=set(slots))

                cleaned.append({
                    "slots": slots, "name": name,
                    "prompt_fragment": frag,
                    "covers": covers,
                    "partially_covers": partially,
                    "outfit_types": _ensure_outfit_types(
                        p.get("outfit_types"), name),
                })
                seen_slots.update(slots)
            if not cleaned:
                return None
            return cleaned[:max_pieces]
        except Exception as e:
            logger.error("LLM Piece-Generierung fehlgeschlagen: %s", e)
            return None

    @staticmethod
    def _extract_json(raw: str) -> Optional[Dict[str, Any]]:
        if not raw:
            return None
        m = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', raw)
        js = m.group(1) if m else None
        if not js:
            s = raw.find('{')
            e = raw.rfind('}')
            if s != -1 and e > s:
                js = raw[s:e + 1]
        if not js:
            return None
        try:
            return json.loads(js)
        except json.JSONDecodeError:
            return None

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------

    def execute(self, raw_input: str) -> str:
        ctx = self._parse_base_input(raw_input)
        character_name = (ctx.get("agent_name") or "").strip()
        hint = (ctx.get("input") or "").strip()
        skip_daily_limit = bool(ctx.get("skip_daily_limit"))
        if not character_name:
            return "Fehler: character_name fehlt."

        from app.models.character import is_outfit_locked
        if is_outfit_locked(character_name):
            return f"Outfit-Generierung fuer {character_name} uebersprungen: Outfit ist gesperrt."

        cfg = self._get_effective_config(character_name)
        if not cfg.get("enabled", True):
            return f"CreateOutfit is disabled for {character_name}."

        max_daily = cfg.get("max_daily_items", 8)
        max_inventory = cfg.get("max_inventory_pieces", 60)
        language = cfg.get("outfit_language", "en")

        # Daily limit (pieces, not outfits)
        today_count = self._count_today_items(character_name)
        remaining_today = max(0, max_daily - today_count) if max_daily > 0 else 999
        if max_daily > 0 and not skip_daily_limit and remaining_today <= 0:
            return (f"Tageslimit erreicht: {today_count}/{max_daily} Pieces "
                    f"heute erzeugt. Morgen wieder moeglich.")

        inv_count = self._count_inventory_pieces(character_name)
        if max_inventory > 0 and inv_count >= max_inventory:
            return (f"Inventar-Limit erreicht: {inv_count}/{max_inventory} Pieces. "
                    f"Erst alte Pieces loeschen.")

        _tq = get_task_queue()
        _track_id = _tq.track_start("outfit_create", "Outfit-Pieces generieren",
                                      agent_name=character_name)
        try:
            # Gather the context. A worn persona's personality / look
            # replace her own.
            from app.core.identity_view import self_field
            personality = (self_field(character_name, "character_personality")
                           or get_character_personality(character_name) or "")
            appearance = (self_field(character_name, "character_appearance")
                          or get_character_appearance(character_name) or "")
            loc_id = get_character_current_location(character_name) or ""
            activity = get_effective_activity(character_name) or ""
            feeling = get_character_current_feeling(character_name) or ""
            style_hint, decency = self._resolve_style_context(character_name)
            from app.models.character import get_character_profile as _gcp_pref
            decency_pref = (_gcp_pref(character_name) or {}).get("decency_preference", "") or ""

            location_label = ""
            location_desc = ""
            if loc_id:
                loc = get_location(loc_id) or {}
                location_label = loc.get("name") or loc_id
                location_desc = loc.get("description", "")
            from app.models.character import get_character_language as _gcl
            context_block = build_context_block(
                location_label=location_label, location_desc=location_desc,
                activity=activity, feeling=feeling, style_hint=style_hint,
                decency=decency, lang=_gcl(character_name) or "en")

            # How many pieces may the LLM still create today?
            max_pieces = min(remaining_today, 6)  # an outfit rarely has > 6 parts
            if max_pieces <= 0:
                return f"Tageslimit erreicht: keine weiteren Pieces heute."

            # Load the existing pieces (for context)
            existing = []
            try:
                inv_data = get_character_inventory(character_name, include_equipped=True)
                existing = [e for e in (inv_data or {}).get("inventory", [])
                            if e.get("item_category") == "outfit_piece"]
            except Exception:
                pass

            _tq.track_update_label(_track_id, "LLM: Piece-Liste generieren")
            pieces = self._generate_pieces_via_llm(
                character_name=character_name,
                personality=personality, appearance=appearance,
                context_block=context_block, style_hint=style_hint,
                decency=decency, decency_pref=decency_pref,
                existing_pieces=existing, hint=hint, language=language,
                max_pieces=max_pieces)
            if not pieces:
                _tq.track_finish(_track_id, error="LLM lieferte keine Pieces")
                return "Fehler: Konnte keine Pieces generieren."

            # Create + equip the pieces. Existing inventory pieces with the same
            # name+slot are reused instead of created anew (dedupe).
            _tq.track_update_label(_track_id, f"{len(pieces)} Pieces anlegen")
            created = []
            reused = []
            equipped = []
            failed = []
            for p in pieces:
                try:
                    slots_list = p.get("slots") or []
                    primary_slot = slots_list[0] if slots_list else ""
                    existing_iid = find_inventory_piece_by_name_slot(
                        character_name, p.get("name") or "", primary_slot,
                        prompt_fragment=p.get("prompt_fragment") or "")
                    if existing_iid:
                        iid = existing_iid
                        reused.append({"id": iid, "slots": slots_list, "name": p["name"]})
                        logger.info("Piece '%s' (slots=%s) bereits im Inventar, reuse %s",
                                    p["name"], slots_list, iid)
                    else:
                        item = add_item(
                            name=p["name"],
                            description="",
                            category="outfit_piece",
                            image_prompt="",
                            prompt_fragment=p["prompt_fragment"],
                            outfit_piece={
                                "slots": slots_list,
                                "covers": p.get("covers") or [],
                                "partially_covers": p.get("partially_covers") or [],
                                "outfit_types": p.get("outfit_types") or [],
                            })
                        iid = item.get("id")
                        if not iid:
                            failed.append(p["name"])
                            continue
                        add_to_inventory(
                            character_name=character_name,
                            item_id=iid,
                            obtained_method="generated",
                            obtained_from="outfit_creation")
                        created.append({"id": iid, "slots": slots_list, "name": p["name"]})
                    # equip_piece clears displaced pieces (multi-slot too) by itself.
                    r = equip_piece(character_name, iid, source="outfit_creation")
                    if (r or {}).get("status") == "ok":
                        for s in slots_list:
                            equipped.append(s)
                except Exception as e:
                    logger.warning("Piece anlegen fehlgeschlagen (%s): %s", p.get("name"), e)
                    failed.append(p.get("name") or "?")

            # Create the set automatically — holds every piece (new + reused)
            set_name = ""
            set_pieces = created + reused
            if set_pieces:
                try:
                    from app.models.character import add_character_outfit
                    piece_ids = [c["id"] for c in set_pieces]
                    # Set name: outfit type + short list (e.g. "Business: Blazer, Heels")
                    short_names = ", ".join(c["name"] for c in set_pieces[:3])
                    set_name = f"{style_hint}: {short_names}" if style_hint else short_names
                    if len(set_name) > 60:
                        set_name = set_name[:57] + "..."
                    # Outfit free text from the fragments (backwards compat)
                    frags = [p["prompt_fragment"] for p in pieces if p.get("prompt_fragment")]
                    outfit_text = "wearing: " + ", ".join(frags) if frags else ""
                    add_character_outfit(character_name, {
                        "name": set_name,
                        "outfit": outfit_text,
                        "pieces": piece_ids,
                    })
                    logger.info("Outfit-Set '%s' gespeichert mit %d Pieces", set_name, len(piece_ids))
                except Exception as e:
                    logger.warning("Set-Erstellung fehlgeschlagen: %s", e)

            # Push the item images asynchronously into the GPU queue
            # (fire-and-forget). Every piece gets its own product photo.
            if created:
                import threading
                def _gen_item_images():
                    from app.routes.inventory import generate_item_image_sync
                    for c in created:
                        try:
                            generate_item_image_sync(c["id"])
                        except Exception as _e:
                            logger.warning("Item-Bild fuer '%s' fehlgeschlagen: %s", c["name"], _e)
                threading.Thread(target=_gen_item_images, daemon=True,
                                  name=f"outfit-item-images-{character_name}").start()
                logger.info("Item-Bild-Generierung fuer %d Pieces gestartet (Background)", len(created))

            _tq.track_finish(_track_id)
            if reused and created:
                head = f"{len(created)} neue + {len(reused)} bestehende Piece(s) fuer {character_name}"
            elif reused and not created:
                head = f"{len(reused)} Piece(s) aus Inventar wiederverwendet fuer {character_name}"
            else:
                head = f"{len(created)} Piece(s) fuer {character_name} erzeugt"
            parts = [head]
            if set_name:
                parts[0] += f" als Set '{set_name}'"
            elif style_hint:
                parts[0] += f" (Stil: {style_hint})"
            if equipped:
                parts.append("Slots angezogen: " + ", ".join(equipped))
            if failed:
                parts.append("Fehlgeschlagen: " + ", ".join(failed))
            return ". ".join(parts)
        except Exception as e:
            logger.exception("OutfitCreation Fehler: %s", e)
            try:
                _tq.track_finish(_track_id, error=str(e))
            except Exception:
                pass
            return f"Fehler bei Outfit-Generierung: {e}"
