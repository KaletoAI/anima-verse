"""GoToCharacter skill — move to where a specific person actually is.

Fixes the guessing game the thought path used to play: a character who
wanted to join someone else had only the "Places you can go" list to pick
from and chose the most similar-sounding entry (plan-room-conversation-
ergaenzungsplan.md, A10). This verb resolves the target person's ACTUAL
current location and room instead.

It adds no movement mechanics and no world knowledge of its own:

* the position it aims at is ``current_location``/``current_room`` of the
  target — for a travelling character that is the nearest cell, the game
  truth, NOT their journey destination;
* the move itself is delegated to ``SetLocationSkill.execute``, so leave
  rules, access rules, ``accessible_when``, transit-tile refusal and the
  journey engine all still apply, exactly once, in one place;
* a location the actor does not know stays unknown — the verb refuses and
  names the places the actor DOES know, rather than teaching it a new one.
"""
import json
from typing import Any, Dict, List, Tuple

from app.plugins.base import PluginSkill
from app.plugins.context import PluginContext
from app.skills.base import ToolSpec

from app.core.log import get_logger
logger = get_logger("go_to_character")

from app.models.character import (
    get_character_current_location,
    get_character_current_room,
    list_available_characters)
from app.models.world import (
    get_location_by_id, get_location_rooms, list_locations_for_character)

from plugins.movement.go_to_resolve import resolve_go_to


class GoToCharacterSkill(PluginSkill):
    """Moves the agent to the place another character currently occupies.

    Same visibility rules as SetLocation — a party follower is dragged
    along by its leader and therefore has neither verb.
    """
    SUPPRESS_IN_PERSON = True
    SINGLETON = True

    SKILL_ID = "go_to_character"

    def visible_for(self, character_name: str) -> bool:
        """Party followers do not steer themselves — identical gate to
        SetLocation (the leader moves, the followers are pulled along)."""
        try:
            from app.core.party_engine import get_party_of
            party = get_party_of(character_name)
            return not (party and party.get("role") == "follower")
        except Exception:
            return True

    def __init__(self, config: Dict[str, Any], ctx: PluginContext):
        super().__init__(config, ctx)
        # name/description come from templates/llm/skills/go_to_character.md
        self._defaults = {}

    def execute(self, raw_input: str) -> str:
        """Moves the agent to the current whereabouts of a named person.

        Input from the LLM: the person's name, e.g. "Lirien".
        """
        if not self.enabled:
            return "The GoToCharacter skill is disabled."
        try:
            return self._execute_inner(raw_input)
        except Exception as e:
            logger.error("GoToCharacter failed: %s", e)
            return f"Error while walking to the person: {e}"

    def _execute_inner(self, raw_input: str) -> str:
        ctx = self._parse_base_input(raw_input)
        character_name = (ctx.get("agent_name") or "").strip()
        requested = str(ctx.get("character") or ctx.get("input") or "").strip()
        # A model that packs everything into one line ("Lirien, hurry") —
        # only the first field is a name, the rest is prose.
        requested = requested.split(",")[0].strip().strip('"\'')

        if not character_name:
            return "Error: character_name missing."
        if not requested:
            return "Error: no person given. Name the character you want to go to."

        target = self._canonical_name(requested)
        if not target:
            # Deliberately NO first-/last-name resolution and no substring
            # magic (house rule): an ambiguous guess would send the
            # character to a stranger's place.
            return (f"There is no character called '{requested}' in this "
                    f"world. Use the exact name.")
        if target.lower() == character_name.lower():
            return "That is you — name someone else to go to."

        actor_loc = get_character_current_location(character_name) or ""
        actor_room = get_character_current_room(character_name) or ""
        target_loc = get_character_current_location(target) or ""
        target_room = get_character_current_room(target) or ""

        known_ids, known_names = self._known_places(character_name)
        kind, payload = resolve_go_to(actor_loc, actor_room,
                                      target_loc, target_room, known_ids)
        logger.info("GoToCharacter: %s -> %s (%s @ %s/%s) = %s",
                    character_name, target, kind, target_loc, target_room,
                    payload)

        if kind == "same_room":
            return f"You are already in the same room as {target}."

        if kind == "unknown":
            places = ", ".join(known_names) if known_names else "nowhere yet"
            return (f"You do not know where {target} is right now — you only "
                    f"know how to reach: {places}.")

        location = get_location_by_id(target_loc)
        if not location:
            return (f"You do not know where {target} is right now — you only "
                    f"know how to reach: "
                    f"{', '.join(known_names) if known_names else 'nowhere yet'}.")
        location_name = location.get("name", "") or target_loc

        # Delegate to the ONE movement path. "<Location>, <Room>" is the
        # canonical SetLocation input: for the same location it is the
        # instant room change, for another one the normal journey start
        # (which ignores the room — the arrival ticker picks it).
        wanted_room = payload if kind == "room" else target_room
        room_label = self._room_display_name(location, wanted_room)
        move_input = f"{location_name}, {room_label}" if room_label \
            else location_name

        from plugins.movement.skill_set_location import SetLocationSkill
        result = SetLocationSkill({"enabled": True}, self.ctx).execute(
            json.dumps({"input": move_input,
                        "agent_name": character_name,
                        "user_id": (ctx.get("user_id") or "").strip()}))
        return f"(going to {target}) {result}"

    @staticmethod
    def _canonical_name(requested: str) -> str:
        """Exact, case-insensitive name match — nothing else.

        Returns the character's name in its stored spelling, or "" when no
        character carries exactly that name.
        """
        wanted = (requested or "").strip().lower()
        if not wanted:
            return ""
        for name in list_available_characters():
            if name.lower() == wanted:
                return name
        return ""

    @staticmethod
    def _room_display_name(location: Dict[str, Any], room_id: str) -> str:
        """Room NAME for a room id, or "" when the id names no room here.

        SetLocation reads an unmatched second field as a free pose, so a raw
        id must never be handed to it — better no room than a pose called
        "room_7f3a".
        """
        if not room_id:
            return ""
        try:
            for room in get_location_rooms(location) or []:
                if room.get("id", "") == room_id:
                    return (room.get("name") or "").strip()
        except Exception as e:
            logger.debug("room name lookup failed for %s: %s", room_id, e)
        return ""

    @staticmethod
    def _known_places(character_name: str) -> Tuple[List[str], List[str]]:
        """(ids, display names) of the places the actor may travel to.

        Same source as the 'Places you can go' prompt block
        (``known_locations_section``): visibility-filtered, transit tiles
        dropped, so the refusal never lists a place the character could not
        walk to anyway.
        """
        ids: List[str] = []
        names: List[str] = []
        try:
            for loc in list_locations_for_character(character_name) or []:
                if loc.get("passable"):
                    continue
                lid = (loc.get("id") or "").strip()
                if not lid:
                    continue
                ids.append(lid)
                name = (loc.get("name") or lid).strip()
                if name not in names:
                    names.append(name)
        except Exception as e:
            logger.debug("known places failed for %s: %s", character_name, e)
        return ids, names[:12]

    def get_usage_instructions(self, format_name: str = "", **kwargs) -> str:
        from app.core.tool_formats import format_example
        fmt = format_name or "tag"
        return format_example(fmt, self.name, "Mira")

    def as_tool(self, **kwargs) -> ToolSpec:
        return ToolSpec(
            name=self.name,
            description=(
                f"{self.description} "
                f"Input: the exact name of the person, nothing else "
                f"(e.g. 'Mira'). Use this instead of SetLocation whenever "
                f"you want to be WITH someone — it resolves where that "
                f"person actually is right now, so you never have to guess "
                f"a place name. Same location, other room: you are there "
                f"instantly. Another place: a timed journey starts, and only "
                f"if you already know the way there."
            ),
            func=self.execute)
