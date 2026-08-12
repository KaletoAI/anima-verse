"""SetLocation skill — changing place by chat.

A lightweight skill that lets an agent change its location, room and pose.
The chat system surfaces it whenever the conversation asks for a move
("you are at home now", "travel to the office").

A cross-location move does NOT teleport: it starts a timed journey
(``travel_engine.start_journey``) that the travel ticker advances on the game
clock. Only a room change within the same location is instant. The gates in
front of it are the same ones ``POST /play/travel`` and the arrival ticker
apply — leave rules, access rules, ``accessible_when`` — because a movement
path that skips one of them is a hole in every rule the world has.
"""
import random
from typing import Any, Dict

from app.plugins.base import PluginSkill
from app.plugins.context import PluginContext
from app.skills.base import ToolSpec

from app.core.log import get_logger
logger = get_logger("set_location")

from app.models.character import (
    save_character_current_location,
    set_pose_intent,
    save_character_current_room,
    get_character_current_location,
    get_character_config,
    get_movement_target)
from app.models.world import (
    list_locations, get_location_rooms, get_room_by_name,
    get_location_by_id)


class SetLocationSkill(PluginSkill):
    """Sets an agent's location, room and pose.

    The agent uses this skill when the conversation asks for a move. The
    requested place is validated against the world's locations; the room and
    the pose follow from the input or from the location's arrival rule.
    """
    SUPPRESS_IN_PERSON = True
    SINGLETON = True

    SKILL_ID = "setlocation"

    def visible_for(self, character_name: str) -> bool:
        """Party followers are dragged along by the leader and cannot
        move on their own (wave 4 — replaces the skill-id whitelist
        in the skill manager)."""
        try:
            from app.core.party_engine import get_party_of
            party = get_party_of(character_name)
            return not (party and party.get("role") == "follower")
        except Exception:
            return True

    def __init__(self, config: Dict[str, Any], ctx: PluginContext):
        super().__init__(config, ctx)
        # name/description/action_hint come from templates/llm/skills/set_location.md
        self._defaults = {}

    def thought_context_block(self, character_name: str) -> str:
        """'Places you can go' — the visibility-filtered travel-target list
        plus the SetLocation instruction (package-owned prompt section)."""
        from plugins.movement.blocks import known_locations_section
        return known_locations_section(character_name)

    def execute(self, raw_input: str) -> str:
        """Sets location, room and pose for the agent.

        Input format (from the LLM):
            location name, e.g. "home" or "office"
            with a room: "home, kitchen"
            with room + pose: "home, kitchen, cooking"
            with a pose (the room is derived): "home, cooking"
        """
        if not self.enabled:
            return "SetLocation Skill ist nicht verfuegbar."

        try:
            return self._execute_inner(raw_input)
        except Exception as e:
            logger.error("SetLocation failed: %s", e)
            return f"Fehler beim Setzen der Location: {e}"

    def _execute_inner(self, raw_input: str) -> str:
        ctx = self._parse_base_input(raw_input)
        input_text = ctx.get("input", raw_input).strip()
        character_name = ctx.get("agent_name", "").strip()
        user_id = ctx.get("user_id", "").strip()

        if not character_name:
            return "Fehler: Agent-Name fehlt."
        if not input_text:
            return "Fehler: Kein Ort angegeben."

        # Parse the input: "location, room/pose, pose"
        parts = [p.strip() for p in input_text.split(",")]
        requested_location = parts[0]
        requested_second = parts[1] if len(parts) > 1 else None
        requested_third = parts[2] if len(parts) > 2 else None

        logger.info(f"Move requested for {character_name}")
        logger.info(f"Requested: location='{requested_location}', "
              f"second='{requested_second}', third='{requested_third}'")

        # Look the name up in the world's locations
        locations = list_locations()
        matched_location = None
        for loc in locations:
            if loc["name"].lower() == requested_location.lower():
                matched_location = loc
                break

        # Fuzzy match: substring search as a fallback
        if not matched_location:
            for loc in locations:
                if requested_location.lower() in loc["name"].lower() or loc["name"].lower() in requested_location.lower():
                    matched_location = loc
                    break

        # Description match: the search term inside a location description
        if not matched_location:
            for loc in locations:
                desc = loc.get("description", "").lower()
                if desc and requested_location.lower() in desc:
                    matched_location = loc
                    break

        # Fallback: match a room at the current location
        if not matched_location:
            current_loc_id = get_character_current_location(character_name)
            current_loc = get_location_by_id(current_loc_id) if current_loc_id else None
            if current_loc:
                current_rooms = get_location_rooms(current_loc)
                matched_room_fallback = None
                # Exact
                for room in current_rooms:
                    if room.get("name", "").lower() == requested_location.lower():
                        matched_room_fallback = room
                        break
                # Fuzzy
                if not matched_room_fallback:
                    for room in current_rooms:
                        rn = room.get("name", "").lower()
                        rl = requested_location.lower()
                        if rl in rn or rn in rl:
                            matched_room_fallback = room
                            break
                if matched_room_fallback:
                    # A room at the current location — keep the location,
                    # change the room only
                    matched_location = current_loc
                    requested_second = matched_room_fallback.get("name", "")
                    requested_third = None  # the room decides the pose
                    logger.info(f"Room '{requested_location}' found at the "
                          f"current location '{current_loc.get('name', '')}'")

        # Home alias: "home", "zu hause", "zuhause" … resolve to the
        # home_location of the character config
        if not matched_location:
            home_aliases = {"home", "zu hause", "zuhause", "nach hause", "daheim"}
            if requested_location.lower() in home_aliases:
                cfg = get_character_config(character_name)
                home_loc_id = cfg.get("home_location", "")
                # Offmap sentinel: the character has no home on the map and
                # simply disappears from it. enter_offmap_sleep stores the
                # last position for the wakeup.
                from app.models.character import (
                    OFFMAP_SLEEP_SENTINEL, enter_offmap_sleep)
                if home_loc_id == OFFMAP_SLEEP_SENTINEL:
                    if enter_offmap_sleep(character_name):
                        return f"{character_name} hat sich zurueckgezogen — offmap."
                    return f"{character_name} ist bereits offmap."
                if home_loc_id:
                    matched_location = get_location_by_id(home_loc_id)
                    if matched_location:
                        home_room_id = cfg.get("home_room", "")
                        if home_room_id and not requested_second:
                            # Use the home room as the second part unless one
                            # was named explicitly
                            rooms = get_location_rooms(matched_location)
                            for r in rooms:
                                if r.get("id", "") == home_room_id:
                                    requested_second = r.get("name", "")
                                    break
                        logger.info(f"Home alias '{requested_location}' -> location '{matched_location.get('name', '')}' (id: {home_loc_id})")

        if not matched_location:
            available_parts = [loc["name"] for loc in locations] if locations else []
            # Append the rooms of the current location
            current_loc_id = get_character_current_location(character_name)
            current_loc = get_location_by_id(current_loc_id) if current_loc_id else None
            if current_loc:
                current_rooms = get_location_rooms(current_loc)
                room_names = [r.get("name", "") for r in current_rooms if r.get("name")]
                if room_names:
                    available_parts.extend(room_names)
            available = ", ".join(available_parts) if available_parts else "keine definiert"
            logger.warning(f"Location not found: '{requested_location}'. Available: {available}")
            return f"Ort '{requested_location}' nicht gefunden. Verfuegbare Orte: {available}"

        location_name = matched_location["name"]
        location_id = matched_location.get("id", location_name)

        # Leave check: may the character leave its current location/room at
        # all? Applies to pinning/confine rules (action="leave").
        # Cross-location: room AND location scope. Same-location: room scope
        # only (the location is not left). The target room is matched up
        # front so confine SETS (several room_ids in one rule) can allow free
        # movement within the set.
        from app.models.rules import check_leave, check_access
        cur_loc_for_leave = get_character_current_location(character_name) or ""
        is_same_loc = bool(cur_loc_for_leave) and cur_loc_for_leave == location_id
        target_room_preview = ""
        if requested_second:
            _peek = get_room_by_name(matched_location, requested_second)
            if _peek:
                target_room_preview = _peek.get("id", "")
        if cur_loc_for_leave:
            leave_ok, leave_reason = check_leave(
                character_name,
                room_only=is_same_loc,
                target_location_id=location_id,
                target_room_id=target_room_preview)
            if not leave_ok:
                logger.info("Leave blocked: %s wants %s -> %s: %s",
                            character_name, cur_loc_for_leave, location_id, leave_reason)
                try:
                    from app.models.character import record_access_denied
                    from app.models.world import get_location_name as _gln
                    cur_name = _gln(cur_loc_for_leave) or cur_loc_for_leave
                    record_access_denied(character_name, cur_loc_for_leave,
                                          cur_name, leave_reason, action="leave")
                except Exception:
                    logger.debug("record_access_denied(leave) failed", exc_info=True)
                _trigger_access_denied_thought(character_name, location_name, leave_reason)
                return leave_reason

        # Restrictions check: may the character enter this place?
        from app.core.danger_system import check_location_access
        allowed, deny_reason = check_location_access(character_name, matched_location)
        if not allowed:
            logger.info("Location access denied: %s -> %s: %s", character_name, location_name, deny_reason)
            return deny_reason

        # Rules engine: the block rules
        rules_ok, rules_reason = check_access(character_name, location_id)
        if not rules_ok:
            logger.info("Rule blocks access: %s -> %s: %s", character_name, location_name, rules_reason)
            try:
                from app.models.character import record_access_denied
                record_access_denied(character_name, location_id, location_name, rules_reason)
            except Exception:
                logger.debug("record_access_denied failed", exc_info=True)
            _trigger_access_denied_thought(character_name, location_name, rules_reason)
            return rules_reason

        # ``accessible_when`` — the field the world map greys a place out with,
        # and NO rule row backs it. Its enforcement points are the travel route
        # (``routes/play.py``), the arrival ticker
        # (``travel_engine._arrival_gate``) and this skill; all three ask the
        # very same reader, ``world_ops.conditions_pass``, so a condition can
        # never mean one thing for the avatar and another for an NPC. Checked
        # BEFORE the journey starts: a character must not set off for a place it
        # may not enter — the ticker would only turn it away at the door.
        from app.core.world_ops import conditions_pass
        if not conditions_pass(matched_location.get("accessible_when") or [],
                               character_name, location_id):
            from app.core.i18n import t as _t
            from app.models.character import get_character_language
            cond_reason = _t("This place is not accessible to you.",
                             get_character_language(character_name) or "de")
            logger.info("accessible_when blocks access: %s -> %s",
                        character_name, location_name)
            try:
                from app.models.character import record_access_denied
                record_access_denied(character_name, location_id,
                                     location_name, cond_reason)
            except Exception:
                logger.debug("record_access_denied failed", exc_info=True)
            _trigger_access_denied_thought(character_name, location_name,
                                           cond_reason)
            return cond_reason

        # Passable tiles (transit places) are no destinations — the LLM must
        # not walk there directly. The pathfinder may still use them as an
        # intermediate step when the character knows them.
        if matched_location.get("passable"):
            logger.info("SetLocation onto a transit place refused: %s -> %s",
                        character_name, location_name)
            return (f"{location_name} is a place to pass THROUGH, not a "
                    f"destination. Pick a real place to travel to.")

        # Journey mode: a cross-location move starts a timed journey
        # (start_journey; the travel ticker advances it as game time
        # passes). Same-location moves (room change only) stay instant.
        current_loc_id_now = get_character_current_location(character_name) or ""
        is_cross_location = bool(current_loc_id_now and current_loc_id_now != location_id)
        # Journeys apply to NPCs only — the player avatar still moves
        # instantly here; timed avatar travel runs over the /play route
        # (Seamless World, E3 Task 5).
        from app.models.account import is_player_controlled as _is_player
        if is_cross_location and not _is_player(character_name):
            from app.core.travel_engine import start_journey, journey_state
            from app.core.timeutils import game_now, to_world_tz
            j, reason = start_journey(character_name, location_id)
            if j is None:
                logger.info("No journey %s -> %s for %s: %s",
                            current_loc_id_now, location_id, character_name,
                            reason)
                # Diary entry: a failed travel attempt. The REASON is
                # recorded verbatim, the TEXT is not: a character cannot
                # tell "I have never been told about this place" from "the
                # place stands on no map at all", so both read alike.
                try:
                    from app.models.character import _record_state_change
                    _record_state_change(character_name, "travel_failed",
                        location_name,
                        metadata={"location_id": location_id,
                                  "reason": reason})
                except Exception:
                    logger.debug("travel_failed record failed", exc_info=True)
                if reason == "no_route":
                    return (f"There is no passable route to {location_name} "
                            f"from here — water, cliffs or walls block every "
                            f"way. You have to find another approach.")
                return (f"You do not know the way to {location_name} (yet). "
                        f"You have to be led there first or discover a place "
                        f"nearby.")
            st = journey_state(j["waypoints"], j["started_at_game"], game_now())
            eta_local = to_world_tz(st["eta_game"])
            logger.info("Journey: %s -> %s (%.0f m, ETA %s)",
                        character_name, location_name, st["total_m"],
                        st["eta_game"])
            return (f"You set off for {location_name} "
                    f"({st['total_m']:.0f} m of road). Estimated arrival: "
                    f"{eta_local:%H:%M} (game time). The journey continues "
                    f"automatically.")

        rooms = get_location_rooms(matched_location)

        # Determine room and (free) pose. There is no activity library any
        # more — an optional pose part is free text, and the room only points
        # a direction through activity_hint (the LLM decides).
        matched_room = None
        pose = ""

        if requested_second:
            # 1. Try the second part as a room name
            matched_room = get_room_by_name(matched_location, requested_second)

            if matched_room:
                # Rules check for the room
                room_rules_ok, room_rules_reason = check_access(character_name, location_id, room_id=matched_room.get("id", ""))
                if not room_rules_ok:
                    room_label = matched_room.get("name", "")
                    logger.info("Rule blocks the room: %s -> %s: %s",
                               character_name, room_label, room_rules_reason)
                    try:
                        from app.models.character import record_access_denied
                        record_access_denied(character_name, location_id,
                            f"{location_name} / {room_label}" if room_label else location_name,
                            room_rules_reason)
                    except Exception:
                        logger.debug("record_access_denied failed", exc_info=True)
                    _trigger_access_denied_thought(character_name,
                        f"{location_name} / {room_label}" if room_label else location_name,
                        room_rules_reason)
                    return room_rules_reason
                # Third part = the free pose in that room
                if requested_third:
                    pose = requested_third
            else:
                # 2. The second part is no room → read it as a free pose
                pose = requested_second

        # No room named: land where every arrival lands — the declared entry
        # room, or the location's ground (plan-grundflaeche.md § 6). Never a
        # random first room.
        if not matched_room:
            from app.models.world import get_arrival_room_id
            _arrival_id = get_arrival_room_id(matched_location)
            matched_room = next(
                (r for r in rooms if r.get("id") == _arrival_id),
                {"id": _arrival_id, "name": ""})

        room_id = matched_room.get("id", "") if matched_room else ""
        room_name = matched_room.get("name", "") if matched_room else ""

        # Write the state: the location ID, never the name
        save_character_current_location(character_name, location_id)
        save_character_current_room(character_name, room_id)
        if pose:
            set_pose_intent(character_name, pose)

        # Avatar follow: a LOCATION change is no longer taken over (the
        # avatar stays where the user put it). Only a ROOM change follows,
        # and only when the avatar is already at the same location.
        try:
            from app.models.account import get_active_character
            player = get_active_character()
            if player and player != character_name:
                player_loc = get_character_current_location(player)
                if player_loc and player_loc == location_id:
                    save_character_current_room(player, room_id)
                    logger.info("Avatar %s follows %s -> room %s", player, character_name, room_id)
        except Exception as _e:
            logger.warning("Avatar room follow failed: %s", _e)

        # Decency compliance for the new room/location.
        from app.core.outfit_compliance import apply_outfit_compliance
        _comp = apply_outfit_compliance(character_name)
        if _comp.get("auto_filled") or _comp.get("forbidden_cleared"):
            logger.info(
                "Outfit-Compliance [%s] decency=%s: filled=%d, cleared=%d",
                character_name, _comp.get("decency"),
                len(_comp.get("auto_filled", [])),
                len(_comp.get("forbidden_cleared", [])),
            )

        logger.info(f"Set: location='{location_name}' (id: {location_id}), "
              f"room='{room_name}' (id: {room_id}), pose='{pose}'")

        # The confirmation
        result = f"Standort aktualisiert: {location_name}"
        if room_name:
            result += f", Raum: {room_name}"
        if pose:
            result += f" ({pose})"
        if matched_location.get("description"):
            result += f"\nOrt-Beschreibung: {matched_location['description']}"
        if matched_room and matched_room.get("description"):
            result += f"\nRaum-Beschreibung: {matched_room['description']}"

        return result

    def get_usage_instructions(self, format_name: str = "", **kwargs) -> str:
        from app.core.tool_formats import format_example
        fmt = format_name or "tag"
        return format_example(fmt, self.name, "Büro, Küche, kaffee_kochen")

    def _build_locations_hint(self, character_name: str) -> str:
        """Builds the list of available locations for the tool description.

        While a leave block is active (pinning/confine rule) only the current
        place is offered to the LLM — the hard gate stays in place on top, in
        case the LLM hallucinates anyway.
        """
        try:
            # Soft hint: when the character may not leave at all, offer the
            # current place only.
            if character_name:
                try:
                    from app.models.rules import check_leave
                    leave_ok, leave_reason = check_leave(character_name)
                except Exception:
                    leave_ok, leave_reason = True, ""
                if not leave_ok:
                    cur_loc_id = get_character_current_location(character_name) or ""
                    cur_loc = get_location_by_id(cur_loc_id) if cur_loc_id else None
                    cur_name = (cur_loc or {}).get("name", "") if cur_loc else ""
                    if cur_name:
                        rooms = get_location_rooms(cur_loc) if cur_loc else []
                        # Per-room probe: which room change would be allowed?
                        # Confine sets (several room_ids in one rule) allow
                        # free movement WITHIN the set — those rooms belong on
                        # the list.
                        allowed_room_names = []
                        for r in rooms:
                            r_id = r.get("id", "")
                            r_name = r.get("name", "")
                            if not r_id or not r_name:
                                continue
                            try:
                                ok_r, _ = check_leave(character_name,
                                                      room_only=True,
                                                      target_location_id=cur_loc_id,
                                                      target_room_id=r_id)
                            except Exception:
                                ok_r = True
                            if ok_r:
                                allowed_room_names.append(r_name)
                        if allowed_room_names:
                            return (f" You cannot leave your current location right now"
                                    f" ({leave_reason}). Available: {cur_name}"
                                    f" (rooms: {', '.join(allowed_room_names)}).")
                        return (f" You cannot leave your current location right now"
                                f" ({leave_reason}). You must stay at {cur_name}.")

            locations = list_locations()
            if not locations:
                return ""
            # Same display name = same travel target for the LLM: the input is
            # matched by NAME (_execute_inner, first exact hit wins), so only
            # the first entry of a name is reachable anyway. Terrain tiles of
            # the metre world share their names and blew the line up to
            # several times its length (A3.1: 51 entries, 15 distinct names).
            hints = []
            seen = set()
            for loc in locations:
                name = loc.get("name", "")
                if not name:
                    continue
                key = name.lower()
                if key in seen:
                    continue
                seen.add(key)
                rooms = get_location_rooms(loc)
                room_names = [r.get("name", "") for r in rooms if r.get("name")]
                if room_names:
                    hints.append(f"{name} (rooms: {', '.join(room_names)})")
                else:
                    hints.append(name)
            if hints:
                return (" Available locations: " + "; ".join(hints) + "."
                        " The location name is only the part BEFORE the"
                        " parenthesis — never copy the '(rooms: ...)' listing"
                        " into your input.")
            return ""
        except Exception:
            return ""

    def as_tool(self, **kwargs) -> ToolSpec:
        user_id = kwargs.get("user_id", "")
        character_name = kwargs.get("agent_name", "")
        locations_hint = self._build_locations_hint(character_name)
        return ToolSpec(
            name=self.name,
            description=(
                f"{self.description}. "
                f"Input: location name, optionally with room and/or activity "
                f"(e.g. 'Büro, Küche' or 'home, bedroom, sleeping'). "
                f"Cross-location moves start a timed journey along locations "
                f"you already know — you set the destination once and the "
                f"journey proceeds automatically as game time passes. Within "
                f"the same location (room change), the move is instant. "
                f"IMPORTANT: You MUST use one of the available location names exactly as listed. "
                f"Do NOT invent location names."
                f"{locations_hint}"
            ),
            func=self.execute)


def _trigger_access_denied_thought(character_name: str, location_label: str, reason: str) -> None:
    """Bumps the character in the AgentLoop so they handle the access-
    denied event in their next thought turn. The state_history entry
    written by the caller carries the actual context (location, reason);
    the recent_activity block in agent_thought.md surfaces it.
    """
    try:
        from app.core.agent_loop import get_agent_loop
        get_agent_loop().bump(character_name)
        logger.info("Access-Denied -> AgentLoop bump: %s @ %s",
                    character_name, location_label)
    except Exception as e:
        logger.debug("access_denied bump failed: %s", e)


class CancelTravelSkill(PluginSkill):
    """Aborts the active journey — the character stays where they are.

    Surfaced so a character can RECONSIDER a running journey on every loop
    turn (the travel block in the thought prompt points here): plans
    legitimately change mid-route, e.g. when a conversation starts at the
    current place. A journey runs to arrival on its own — the travel ticker
    advances it on the game clock regardless of loop turns — so without this
    tool a character could not change their mind about a trip mid-route.
    """

    SKILL_ID = "cancel_travel"
    ALWAYS_LOAD = True

    def __init__(self, config: Dict[str, Any], ctx: PluginContext):
        super().__init__(config, ctx)
        # name/description/action_hint come from templates/llm/skills/cancel_travel.md
        self._defaults = {"enabled": True}

    def thought_context_block(self, character_name: str) -> str:
        """'On the road' — active journey status incl. the CancelTravel
        reconsideration nudge (package-owned prompt section)."""
        from plugins.movement.blocks import travel_section
        return travel_section(character_name)

    def execute(self, raw_input: str) -> str:
        if not self.enabled:
            return "The CancelTravel skill is disabled."
        ctx = self._parse_base_input(raw_input)
        character_name = (ctx.get("agent_name") or "").strip()
        if not character_name:
            return "Error: character_name missing."
        target_id = get_movement_target(character_name)
        if not target_id:
            return "You are on no journey — there is nothing to cancel."
        target_name = target_id
        try:
            from app.models.world import get_location_name
            target_name = get_location_name(target_id) or target_id
        except Exception:
            pass
        from app.core.travel_engine import cancel_journey
        cancel_journey(character_name)
        logger.info("Journey cancelled: %s (target was %s)",
                    character_name, target_name)
        return (f"You have called off your journey to {target_name} "
                f"and stay where you are.")

    def as_tool(self, **kwargs) -> ToolSpec:
        return ToolSpec(name=self.name, description=self.description,
                        func=self.execute)

