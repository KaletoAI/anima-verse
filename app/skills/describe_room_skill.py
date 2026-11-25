"""DescribeRoom skill - a character may change room descriptions and add rooms.

Lets characters describe the rooms of the locations they are allowed to design
and add new ones (up to max_custom_rooms per location).

The location travels as a parameter (it is no longer tied to the character's
current position). Works as a chat tool and via intent (proactively).

Every room has a `description` (its content) and an optional `image_prompt`
(an English prompt for image generation). After saving, a new room image is
generated automatically.
"""
import json
import os
from typing import Any, Dict, Optional

from .base import BaseSkill, ToolSpec

from app.core.log import get_logger
from app.core.tool_formats import format_example

logger = get_logger("describe_room")

from app.models.world import (
    GROUND_ROOM_ID,
    floor_room_display_name,
    get_location_by_id,
    get_location_rooms,
    get_room_by_id,
    get_room_by_name,
    is_floor_room,
    update_room_description,
    add_room)


class DescribeRoomSkill(BaseSkill):
    """Skill for changing/creating room descriptions at allowed locations.

    Input format (JSON):
        {
            "location_id": "hex id of the location",
            "room": "room name (existing or new)",
            "description": "what the room is like (the user's language)",
            "image_prompt": "English image generation prompt for the room scene (used as day view)"
        }

    - Every room of an allowed location can be described
    - Exactly ONE room is edited per call
    - New rooms can be created (up to the location's max_custom_rooms)
    - A room that does not exist is created automatically
    - After saving, a room image is generated automatically

    The reserved rooms are described, never created: the ground and the
    corridor of a storey are rooms like any other here, but a name that hits a
    corridor's display name lands ON the corridor and does not count against
    max_custom_rooms (spec 2026-09-09-etagen-flur § 4).
    """

    SKILL_ID = "describe_room"
    # [INTENT: describe_room | description=...] (F6) — the default
    # handle_intent passthrough matches the JSON input of this skill.
    INTENT_TYPES = ("describe_room",)
    INTENT_PAYLOAD_KEYS = ("description",)
    ALWAYS_LOAD = True

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        from app.core.prompt_templates import load_skill_meta
        meta = load_skill_meta("describe_room")
        self.name = meta["name"]
        self.description = meta["description"]
        self.action_hint = meta.get("action_hint", "")
        self._defaults = {
            "enabled": True,
            "max_custom_rooms": int(os.environ.get("SKILL_DESCRIBEROOM_MAX_ROOMS", "3")),
            "design_locations": [],  # locations the character may design (empty = every allowed one)
        }

    def get_config_fields(self) -> dict:
        return {
            "max_custom_rooms": {
                "type": "int",
                "default": self._defaults["max_custom_rooms"],
                "label": "Max. new rooms per location",
            },
            "design_locations": {
                "type": "locations",
                "default": [],
                "label": "Locations to design",
            },
        }

    def _get_allowed_location_ids(self, character_name: str) -> list:
        """The location ids the character may design.

        Reads design_locations from the skill config.
        Empty list = every visitable location is allowed.
        """
        cfg = self._get_effective_config(character_name)
        design_locs = cfg.get("design_locations", [])
        if design_locs:
            return design_locs

        # Fallback: every location the character sees thanks to knowledge items
        from app.models.world import list_locations_for_character
        visible = list_locations_for_character(character_name)
        return [loc.get("id") for loc in visible if loc.get("id")]

    def execute(self, raw_input: str) -> str:
        if not self.enabled:
            return "Fehler: DescribeRoom Skill ist nicht verfuegbar."

        try:
            return self._execute_inner(raw_input)
        except Exception as e:
            logger.error("Fehler in DescribeRoom: %s", e, exc_info=True)
            return f"Fehler: {e}"

    def _execute_inner(self, raw_input: str) -> str:
        ctx = self._parse_base_input(raw_input)
        character_name = ctx.get("agent_name", "").strip()
        user_id = ctx.get("user_id", "").strip()

        if not character_name:
            return "Fehler: Agent-Name fehlt."

        # Parse the JSON input
        location_id = ctx.get("location_id", "").strip()
        room_name = ctx.get("room", "").strip()
        new_description = ctx.get("description", "").strip()
        new_image_prompt = ctx.get("image_prompt", "").strip()

        # Fallback: legacy format "room name: description" in the input field
        input_text = ctx.get("input", "").strip()
        if not location_id and not room_name and input_text:
            # Try to parse the old format
            return self._execute_legacy(input_text, character_name)

        if not location_id:
            logger.warning("location_id missing in the tool input (agent=%s)", character_name)
            return "Fehler: location_id fehlt."
        if not room_name:
            logger.warning("room missing in the tool input (agent=%s, location=%s)", character_name, location_id)
            return "Fehler: room (Raumname) fehlt."
        if not new_description and not new_image_prompt:
            logger.warning("description and image_prompt are both missing (agent=%s, room=%s)", character_name, room_name)
            return "Fehler: description oder image_prompt muss angegeben werden."

        # Clean the description: drop character references, tool tags, JSON
        if new_description:
            new_description = self._sanitize_room_description(new_description, character_name)
            if not new_description and not new_image_prompt:
                logger.warning("description empty after cleaning (agent=%s, room=%s)", character_name, room_name)
                return "Fehler: Beschreibung wurde bereinigt und ist leer — sie enthielt keine gueltige Raum-Beschreibung."

        # Check the permission
        allowed_ids = self._get_allowed_location_ids(character_name)
        location_id = self._resolve_location_id(location_id, allowed_ids)
        if location_id not in allowed_ids:
            logger.warning(
                "location '%s' not allowed for %s (allowed: %s)",
                location_id, character_name, allowed_ids)
            return f"Fehler: Location '{location_id}' ist fuer {character_name} nicht erlaubt."

        # Load the location
        location = get_location_by_id(location_id)
        if not location:
            logger.warning("location '%s' not found (agent=%s)", location_id, character_name)
            return f"Fehler: Location '{location_id}' nicht gefunden."

        location_name = location.get("name", "?")
        rooms = get_location_rooms(location)

        # Look the room up (fuzzy)
        room = get_room_by_name(location, room_name)
        if not room:
            # An unnamed corridor answers with the translated default of its
            # storey, which the name lookup above cannot see. A hit lands the
            # description ON the corridor instead of creating a second room
            # carrying its word.
            room = self._match_floor_room(location, room_name, character_name)

        if room:
            # Update the existing room
            actual_room_name = room.get("name") or room_name
            if actual_room_name.lower() != room_name.lower():
                logger.info(
                    "fuzzy match: '%s' -> existing room '%s' (%s)",
                    room_name, actual_room_name, location_name)
            old_desc = room.get("description", "")
            room_id = room.get("id", "")
            old_render_prompt = self._room_image_prompt(room)

            # Update the description and/or the image prompt
            final_description = new_description if new_description else old_desc
            success = update_room_description(location_id, room_id, final_description,
                image_prompt_day=new_image_prompt if new_image_prompt else None
            )
            if not success:
                return "Fehler: Raum-Beschreibung konnte nicht aktualisiert werden."

            logger.info(
                "%s updated the room '%s' (%s): desc='%s', image_prompt='%s'",
                character_name, actual_room_name, location_name,
                final_description[:60], (new_image_prompt or "")[:60])

            # Render only when the room has no image yet or the prompt the
            # render uses (image prompt, else description) changed — the tool
            # is always loaded, and re-sending the same text used to render
            # (and append a background) again every time.
            new_render_prompt = self._room_image_prompt({
                "image_prompt_day": new_image_prompt or room.get("image_prompt_day", ""),
                "description": final_description})
            render = (new_render_prompt != old_render_prompt
                      or not self._room_has_image(location_id, room_id))
            if render:
                self._trigger_room_image(location_id, room_id)
            else:
                logger.debug("Room image skipped for %s/%s: the image prompt is "
                             "unchanged and the room already has an image",
                             location_id, room_id)

            parts = [f"Raum aktualisiert: {actual_room_name} ({location_name})"]
            if new_description:
                parts.append(f"Beschreibung: {new_description}")
            if new_image_prompt:
                parts.append(f"Image-Prompt: {new_image_prompt}")
            if render:
                parts.append("Bildgenerierung gestartet.")
            return "\n".join(parts)
        else:
            # Create a new room. The reserved rooms do not count: the ground
            # and the corridors are the server's, not the character's, and a
            # location with three storeys must not be "full" because of them.
            cfg = self._get_effective_config(character_name)
            max_custom = cfg.get("max_custom_rooms", 3)
            custom_rooms = [
                r for r in rooms
                if str(r.get("id") or "") != GROUND_ROOM_ID
                and not is_floor_room(str(r.get("id") or ""))
            ]
            if max_custom > 0 and len(custom_rooms) >= max_custom:
                room_names_list = [r.get("name", "") for r in custom_rooms if r.get("name")]
                return (
                    f"Fehler: Maximum von {max_custom} Raeumen in '{location_name}' erreicht. "
                    f"Vorhandene Raeume: {', '.join(room_names_list)}"
                )

            new_room = add_room(location_id, room_name, new_description,
                                image_prompt_day=new_image_prompt or "", sync_world=False)
            if not new_room:
                return f"Fehler: Raum '{room_name}' konnte nicht angelegt werden."

            from app.core import sync_topics
            sync_topics.notify("scene", to=sync_topics.AtLocation(location_id))

            logger.info(
                "%s created the new room '%s' in '%s': desc='%s', image_prompt='%s'",
                character_name, room_name, location_name,
                new_description[:60], (new_image_prompt or "")[:60])

            # Generate the image
            room_id = new_room.get("id", "")
            if room_id:
                self._trigger_room_image(location_id, room_id)

            parts = [f"Neuer Raum erstellt: {room_name} ({location_name})"]
            if new_description:
                parts.append(f"Beschreibung: {new_description}")
            if new_image_prompt:
                parts.append(f"Image-Prompt: {new_image_prompt}")
            if room_id:
                parts.append("Bildgenerierung gestartet.")
            return "\n".join(parts)

    @staticmethod
    def _match_floor_room(location: Dict[str, Any], room_name: str,
                          character_name: str) -> Optional[Dict[str, Any]]:
        """The corridor room whose DISPLAY name the character just used.

        A corridor is usually unnamed and answers with the translated default
        of its storey ("Diele", "Flur (2. Stock)"), so the name lookup over
        ``rooms[].name`` never finds it. The language is resolved with the
        SAME expression the system prompt was built from
        (``system_prompt_builder`` → ``get_character_language(...) or "de"``),
        or a character without a language field would read "Diele" in the
        prompt while only "Hallway" is compared here. English stays in the
        compared set: a model writes the word it read, and not every prompt
        path is localized. None when no corridor carries that name.
        """
        wanted = room_name.strip().lower()
        corridors = [r for r in (location.get("rooms") or [])
                     if isinstance(r, dict) and is_floor_room(str(r.get("id") or ""))]
        if not (wanted and corridors):
            return None
        from app.models.character import get_character_language
        lang = get_character_language(character_name) or "de"
        for room in corridors:
            names = {floor_room_display_name(room, "").lower(),
                     floor_room_display_name(room, lang).lower()}
            if wanted in names:
                return room
        return None

    @staticmethod
    def _room_image_prompt(room: Dict[str, Any]) -> str:
        """The subject a room image renders from: its day image prompt, else
        its description."""
        return (room.get("image_prompt_day", "") or room.get("description", "") or "").strip()

    @staticmethod
    def _room_has_image(location_id: str, room_id: str) -> bool:
        """Whether a gallery image of the location is assigned to the room."""
        from app.models.world import get_gallery_image_rooms
        return room_id in set((get_gallery_image_rooms(location_id) or {}).values())

    @staticmethod
    def _trigger_room_image(location_id: str, room_id: str):
        """Starts the image generation for a room (fire-and-forget) on the
        "location" chain of the image routing.

        Works from async contexts (chat route) as well as from synchronous
        worker threads (proactive/intent via the TaskQueue).
        """
        import threading

        def _generate():
            import time
            import uuid
            try:
                from app.models.world import get_location_by_id, get_room_by_id
                from app.models.world import get_gallery_dir, save_gallery_prompt, \
                    toggle_background_image, set_gallery_image_room
                from app.models.world import set_gallery_image_meta

                location = get_location_by_id(location_id)
                if not location:
                    return
                room = get_room_by_id(location, room_id)
                if not room:
                    return

                # SUBJECT only — framing, "no people" and the photographic
                # tail are the location style's job (legacy tail, N7).
                prompt = DescribeRoomSkill._room_image_prompt(room)
                if not prompt:
                    return

                # The image SERVICE, not the skill-manager lookup: that one
                # found the TakePhoto VERB (SKILL_ID "image_generation", no
                # pool) and the room image never rendered.
                from app.imagegen.routing import route_meta, run_routed
                from app.imagegen.base import MediaGenerationDisabled
                from app.imagegen.routing import NoRouteError
                from app.imagegen.service import get_image_service
                svc = get_image_service()
                if not svc.enabled:
                    logger.warning("Image service not available for the room image")
                    return
                from app.core.prompt_compose import compose as _compose
                # The room scene image is a background — full size, no
                # downscale.
                try:
                    _bg_w = int(os.environ.get("LOCATION_IMAGE_WIDTH", "1280"))
                except (TypeError, ValueError):
                    _bg_w = 1280
                try:
                    _bg_h = int(os.environ.get("LOCATION_IMAGE_HEIGHT", "720"))
                except (TypeError, ValueError):
                    _bg_h = 720
                _agent = location.get("name", location_id)

                def _render(b):
                    """Style/negative for ``b`` — a re-run after a failure
                    composes for the next backend of the chain."""
                    composed = _compose(use_case="location", subject=prompt, backend=b)
                    # Random seed for a fresh render each time.
                    import random as _rnd
                    params = {"width": _bg_w, "height": _bg_h,
                              "seed": _rnd.randint(1, 2**31 - 1)}
                    _log_meta = {"agent_name": _agent, "original_prompt": prompt,
                                 "auto_enhance": False, "compose": composed.meta}

                    # Through the service's ONE handoff: the per-backend
                    # channel (two renders never run in parallel on one
                    # backend) and the world's media master switch both live
                    # there. This runs on its own daemon thread, never in a
                    # queue worker, so the submission cannot nest into its own
                    # channel.
                    def _op(bb):
                        return svc.run_on_backend_channel(
                            bb, lambda: bb.generate(composed.prompt, composed.negative,
                                                    params, log_meta=_log_meta),
                            task_type="image_generation",
                            label=f"Room image: {location_id}/{room_id}")
                    images, used = svc.run_on_backend(b, op=_op)
                    return images, used, composed.prompt

                logger.info("Room image generation started for %s/%s", location_id, room_id)
                try:
                    (images, backend, full_prompt), route = run_routed(
                        "location", _render, pool=svc.pool)
                except (NoRouteError, MediaGenerationDisabled) as _cfg_state:
                    # Configuration states (no usable chain entry, media
                    # switched off) — not a defect, no traceback.
                    logger.warning("Room image for %s/%s not rendered: %s",
                                   location_id, room_id, _cfg_state)
                    return

                loc_id = location.get("id", location_id)
                gallery_dir = get_gallery_dir(loc_id)
                gallery_dir.mkdir(parents=True, exist_ok=True)
                # Timestamp + short random suffix: two room images finished in
                # the same second must not overwrite each other.
                image_name = f"{int(time.time())}_{uuid.uuid4().hex[:6]}.png"
                image_path = gallery_dir / image_name
                image_path.write_bytes(images[0])

                save_gallery_prompt(loc_id, image_name, full_prompt)
                toggle_background_image(loc_id, image_name)
                set_gallery_image_room(loc_id, image_name, room_id)

                # Clear the prompt_changed flag — the image was made from the prompt
                from app.models.world import clear_room_prompt_changed
                clear_room_prompt_changed(location_id, room_id)
                _model_used = (getattr(backend, 'last_used_checkpoint', '')
                               or getattr(backend, 'model', '')
                               or getattr(backend, 'checkpoint', '') or '')
                set_gallery_image_meta(loc_id, image_name, {
                    "backend": backend.name,
                    "backend_type": backend.api_type,
                    "model": _model_used,
                    "loras": [],
                    **route_meta(route),
                })

                logger.info(
                    "Room image generated: %s/%s -> %s",
                    location.get("name", "?"), room.get("name", "?"), image_name)
            except Exception as e:
                logger.error("Room image generation failed for %s/%s: %s",
                             location_id, room_id, e, exc_info=True)

        thread = threading.Thread(target=_generate, daemon=True)
        thread.start()

    @staticmethod
    def _sanitize_room_description(description: str, character_name: str) -> str:
        """Cleans unwanted content out of a room description.

        Removes:
        - embedded JSON objects (hallucinated tool calls)
        - tool-call tags (<tool name=...>)
        - character appearance descriptions
        - sentences about characters
        """
        import re

        text = description.strip()
        if not text:
            return text

        # 1. Remove embedded JSON objects (hallucinated tool calls)
        #    e.g. {"location_id": "...", "room": "...", ...}
        if text.startswith("{"):
            # The whole text is a JSON object — not a valid description
            try:
                import json as _json
                parsed = _json.loads(text)
                if isinstance(parsed, dict) and ("location_id" in parsed or "room" in parsed):
                    logger.info("Raum-Beschreibung ist ein JSON-Objekt — abgelehnt (LLM-Halluzination, Sanitizer hat uebernommen)")
                    return ""
            except Exception:
                pass
            # Try to strip a JSON prefix (JSON followed by text)
            brace_depth = 0
            json_end = -1
            for i, ch in enumerate(text):
                if ch == "{":
                    brace_depth += 1
                elif ch == "}":
                    brace_depth -= 1
                    if brace_depth == 0:
                        json_end = i
                        break
            if json_end > 0:
                remainder = text[json_end + 1:].strip()
                # Check whether the rest contains tool tags too
                remainder = re.sub(r'<tool\s+name="[^"]*">[^<]*(?:</tool>)?', '', remainder).strip()
                if remainder:
                    logger.warning("JSON-Praefix aus Raum-Beschreibung entfernt (%d Zeichen)", json_end + 1)
                    text = remainder
                else:
                    logger.warning("Raum-Beschreibung besteht nur aus JSON + Tool-Tags — abgelehnt")
                    return ""

        # 2. Remove tool-call tags (<tool name="...">...</tool> or unclosed)
        text = re.sub(r'<tool\s+name="[^"]*">.*?</tool>', '', text, flags=re.DOTALL).strip()
        text = re.sub(r'<tool\s+name="[^"]*">.*', '', text, flags=re.DOTALL).strip()
        # Also remove the [ToolName](...) format
        text = re.sub(r'\[[A-Z][A-Za-z]+\]\([^)]*\)', '', text).strip()

        if not text:
            logger.warning("Raum-Beschreibung besteht nur aus Tool-Tags — abgelehnt")
            return ""

        # 3. Detect appearance patterns (physical character descriptions)
        appearance_patterns = [
            r'\b\d+\s*years?\s*(young|old)\b',
            r'\b(blonde|brunette|redhead)\b.*\b(hair|eyes)\b',
            r'\b(short|tall|athletic|slim)\s+(frame|build|body)\b',
            r'\b(large|small|round|perfect)\s+(breasts?|butt|chest)\b',
            r'\bwearing\s+a\b',
            r'\bprofessional\s+portrait\b',
        ]
        appearance_score = sum(1 for p in appearance_patterns if re.search(p, text, re.IGNORECASE))
        if appearance_score >= 2:
            logger.warning("Raum-Beschreibung enthaelt Appearance-Daten (score=%d) — abgelehnt", appearance_score)
            return ""

        # 4. Drop sentences about characters
        sentences = re.split(r'(?<=[.!?])\s+', text)
        agent_lower = character_name.lower()

        character_indicators = [
            agent_lower,
            " steht ", " sitzt ", " liegt ", " kniet ",
            " er steht", " sie steht", " er sitzt", " sie sitzt",
            " seine augen", " ihre augen", " seinen ", " ihren ",
        ]

        filtered = []
        for sentence in sentences:
            s_lower = sentence.lower()
            if any(indicator in s_lower for indicator in character_indicators):
                logger.debug("Raum-Beschreibung bereinigt — Satz entfernt: %s", sentence[:60])
                continue
            filtered.append(sentence)

        result = " ".join(filtered).strip()
        if not result:
            logger.warning("Alle Saetze aus Raum-Beschreibung entfernt — Original beibehalten")
            return description
        return result

    def _execute_legacy(self, input_text: str, character_name: str) -> str:
        """Fallback for the old format without an explicit location_id.

        Uses the character's current location.
        """
        from app.models.character import (
            get_character_current_location,
            get_character_current_room)

        location_id = get_character_current_location(character_name)
        if not location_id:
            return "Fehler: Kein aktueller Standort und keine location_id angegeben."

        location = get_location_by_id(location_id)
        if not location:
            return "Fehler: Standort nicht gefunden."

        # "room name: description" or just "description"
        room = None
        new_description = input_text

        if ":" in input_text:
            parts = input_text.split(":", 1)
            candidate_room_name = parts[0].strip()
            candidate_desc = parts[1].strip()
            matched = get_room_by_name(location, candidate_room_name)
            if matched and candidate_desc:
                room = matched
                new_description = candidate_desc

        if not room:
            room_id = get_character_current_room(character_name)
            if room_id:
                room = get_room_by_id(location, room_id)
            if not room:
                rooms = get_location_rooms(location)
                room_names = [r.get("name", "") for r in rooms if r.get("name")]
                return (
                    f"Fehler: Kein Raum angegeben. Verfuegbare Raeume: {', '.join(room_names)}. "
                    f"Format: 'Raumname: neue Beschreibung'"
                )

        old_desc = room.get("description", "")
        room_name = room.get("name", "?")
        room_id = room.get("id", "")
        location_name = location.get("name", "?")

        # Sanitize in the legacy path too
        new_description = self._sanitize_room_description(new_description, character_name)
        if not new_description:
            return "Fehler: Beschreibung wurde bereinigt und ist leer — sie enthielt keine gueltige Raum-Beschreibung."

        success = update_room_description(location_id, room_id, new_description)
        if not success:
            return "Fehler: Raum-Beschreibung konnte nicht aktualisiert werden."

        logger.info(
            "%s hat Raum '%s' (%s) aktualisiert: '%s' -> '%s'",
            character_name, room_name, location_name,
            old_desc[:60], new_description[:60])
        return (
            f"Raum-Beschreibung aktualisiert: {room_name} ({location_name})\n"
            f"Neu: {new_description}"
        )

    def get_usage_instructions(self, format_name: str = "", character_name: str = "") -> str:
        fmt = format_name or "tag"
        return format_example(
            fmt, self.name,
            '{"location_id": "2964cf7c", "room": "Toilette", '
            '"description": "Der Boden ist nass und es riecht nach Reinigungsmittel", '
            '"image_prompt": "Wet tiled bathroom floor, industrial cleaning supplies, fluorescent lighting, '
            'mop bucket in corner, water puddles reflecting harsh light"}'
        )

    def _location_lines(self, character_name: str) -> list:
        """The allowed locations, one "<id> = <name> (rooms: ...)" each.

        A corridor is listed with its DISPLAY name — unnamed it has no other
        one, and a room the model is never shown is a room it cannot describe
        (spec 2026-09-09-etagen-flur § 4). The language is the character's own,
        the same expression the system prompt uses.
        """
        if not character_name:
            return []
        try:
            from app.models.character import get_character_language
            lang = get_character_language(character_name) or "de"
            hints = []
            for loc_id in self._get_allowed_location_ids(character_name):
                loc = get_location_by_id(loc_id)
                if loc:
                    name = loc.get("name", "?")
                    rooms = get_location_rooms(loc)
                    room_names = []
                    for r in rooms:
                        if is_floor_room(str(r.get("id") or "")):
                            room_names.append(floor_room_display_name(r, lang))
                        elif r.get("name"):
                            room_names.append(r.get("name"))
                    if room_names:
                        hints.append(f"{loc_id} = {name} (rooms: {', '.join(room_names)})")
                    else:
                        hints.append(f"{loc_id} = {name}")
            return hints
        except Exception as e:
            logger.debug("could not load the location hints: %s", e)
        return []

    def _build_locations_hint(self, character_name: str) -> str:
        """The allowed locations with id and rooms, for the tool description."""
        hints = self._location_lines(character_name)
        return (" Allowed locations: " + "; ".join(hints) + ".") if hints else ""

    decision_menu_heading = ("takes these location ids — copy the id in front "
                             "of = exactly; a room named in brackets is a room "
                             "of that location")

    def decision_menu(self, character_name: str) -> list:
        """The allowed location ids for the rp_first tool step, which renders
        only the brief: without them the tool LLM copied the brief's shape or
        took a place name out of the prose (2026-11-25)."""
        return self._location_lines(character_name)

    def _resolve_location_id(self, requested: str, allowed_ids: list) -> str:
        """An allowed id as given, else the id of the ONE allowed location
        whose name equals `requested` exactly (case-insensitive) — a tool
        model that writes the place name instead of its id. Nothing fuzzy, no
        partial names: anything else comes back unchanged and is refused."""
        if requested in allowed_ids:
            return requested
        wanted = requested.strip().casefold()
        if not wanted:
            return requested
        hits = []
        for loc_id in allowed_ids:
            loc = get_location_by_id(loc_id)
            if loc and (loc.get("name") or "").strip().casefold() == wanted:
                hits.append(loc_id)
        if len(hits) == 1:
            logger.info("location name '%s' resolved to its id %s", requested, hits[0])
            return hits[0]
        return requested

    def as_tool(self, character_name: str = "") -> ToolSpec:
        locations_hint = self._build_locations_hint(character_name)
        return ToolSpec(
            name=self.name,
            description=(
                f"{self.description.rstrip('.')}. "
                "Input JSON: {\"location_id\": \"<id>\", \"room\": \"<room name>\", "
                "\"description\": \"<plain text description>\", "
                "\"image_prompt\": \"<english image prompt>\"}. "
                "Updates an existing room or creates a new one if the name doesn't exist yet. "
                "Only one room per call. Only rooms at allowed locations can be changed. "
                "A new room image is automatically generated after saving."
                f"{locations_hint} "
                "IMPORTANT field rules: "
                "'description' MUST be plain natural text (e.g. 'Ein gemütliches Café mit Holztischen und warmem Licht'), "
                "NEVER nested JSON, NEVER tool tags, NEVER code. "
                "'image_prompt' MUST be plain English text (e.g. 'Cozy cafe with wooden tables, warm lighting, potted plants'), "
                "NEVER nested JSON. "
                "Both fields describe ONLY the room/environment — NO characters, NO actions, NO people."
            ),
            func=self.execute)
