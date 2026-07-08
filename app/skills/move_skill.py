"""Move Skill — Schritt auf ein orthogonal angrenzendes Grid-Tile.

Ergaenzt SetLocation: waehrend SetLocation zu bekannten Unikat-Orten ueber
einen Walk-Pfad reist, bewegt Move den Character EIN einzelnes Tile in eine
Himmelsrichtung (N/O/S/W) — auch auf passable Terrain-Tiles (Wald, Meer …),
die SetLocation als Durchgangsorte ablehnt. So lassen sich Gelaende queren und
Personen auf Terrain-Tiles erreichen. Ein Tile pro Aufruf, kein Diagonal-Move.
"""
from typing import Any, Dict

from .base import BaseSkill, ToolSpec
from app.core.log import get_logger

logger = get_logger("move")

# grid_y- = Norden (oben in der Karten-UI), grid_x+ = Osten. NUR orthogonal —
# keine Diagonalen.
_DIRECTIONS = {
    "north": (0, -1), "n": (0, -1), "norden": (0, -1), "nord": (0, -1),
    "south": (0, 1), "s": (0, 1), "sueden": (0, 1), "süden": (0, 1),
    "sued": (0, 1), "süd": (0, 1),
    "east": (1, 0), "e": (1, 0), "osten": (1, 0), "ost": (1, 0), "o": (1, 0),
    "west": (-1, 0), "w": (-1, 0), "westen": (-1, 0),
}
_LABEL = {(0, -1): "north", (0, 1): "south", (1, 0): "east", (-1, 0): "west"}


class MoveSkill(BaseSkill):
    """Bewegt den Agenten ein Tile in eine Himmelsrichtung (Grid-Nachbar)."""
    SUPPRESS_IN_PERSON = True

    SKILL_ID = "move"
    ALWAYS_LOAD = True  # immer geladen, Aktivierung per Character

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        from app.core.prompt_templates import load_skill_meta
        meta = load_skill_meta("move")
        self.name = meta["name"]
        self.description = meta["description"]
        self._defaults = {}

    def execute(self, raw_input: str) -> str:
        if not self.enabled:
            return "Move Skill ist nicht verfuegbar."
        try:
            return self._execute_inner(raw_input)
        except Exception as e:
            logger.error("Fehler in Move: %s", e)
            return f"Fehler beim Bewegen: {e}"

    def _execute_inner(self, raw_input: str) -> str:
        ctx = self._parse_base_input(raw_input)
        input_text = (ctx.get("input", raw_input) or "").strip()
        character_name = (ctx.get("agent_name", "") or "").strip()
        if not character_name:
            return "Fehler: Agent-Name fehlt."

        # Erste erkannte Richtung nehmen — toleriert "north", "go north",
        # "nach Norden", etc.
        token = ""
        for w in input_text.lower().replace(",", " ").split():
            if w in _DIRECTIONS:
                token = w
                break
        if not token:
            return ("No valid direction. Use one of: north, east, south, west "
                    f"(got: '{input_text}').")
        dx, dy = _DIRECTIONS[token]
        label = _LABEL[(dx, dy)]

        from app.models.character import (
            get_character_current_location, save_character_current_location,
            save_character_current_room)
        from app.models.world import (
            list_locations, get_location_by_id, get_entry_room_id)

        cur_id = get_character_current_location(character_name) or ""
        cur = get_location_by_id(cur_id) if cur_id else None
        if not cur or cur.get("grid_x") is None or cur.get("grid_y") is None:
            return ("You can't tell which way to go from here "
                    "(no position on the map).")
        gx, gy = cur["grid_x"], cur["grid_y"]
        tx, ty = gx + dx, gy + dy
        target = None
        for loc in list_locations():
            if loc.get("grid_x") == tx and loc.get("grid_y") == ty:
                target = loc
                break
        if not target:
            return f"There is nothing to the {label} from here."
        target_id = target.get("id") or ""
        target_name = target.get("name") or target_id

        # Leave-/Zugangs-/Rules-Checks wie SetLocation — aber OHNE die
        # Passable-Ablehnung (genau die soll Move umgehen koennen).
        from app.models.rules import check_leave, check_access
        from app.core.danger_system import check_location_access
        leave_ok, leave_reason = check_leave(
            character_name, target_location_id=target_id)
        if not leave_ok:
            return leave_reason
        allowed, deny = check_location_access(character_name, target)
        if not allowed:
            return deny
        rules_ok, rules_reason = check_access(character_name, target_id)
        if not rules_ok:
            return rules_reason

        # Schritt ausfuehren. Auto-Discovery passiert in
        # save_character_current_location (kennt den Ort ab Betreten).
        save_character_current_location(character_name, target_id)
        room_id = get_entry_room_id(target)
        if room_id:
            save_character_current_room(character_name, room_id)

        # Decency-Compliance nach Orts-/Raumwechsel (analog SetLocation).
        try:
            from app.core.outfit_compliance import apply_outfit_compliance
            apply_outfit_compliance(character_name)
        except Exception:
            logger.debug("outfit compliance after move failed", exc_info=True)

        logger.info("Move: %s -> %s (%s)", character_name, target_name, label)
        result = f"You move {label} to {target_name}."
        if target.get("description"):
            result += f"\n{target['description']}"
        return result

    def get_usage_instructions(self, format_name: str = "", **kwargs) -> str:
        from app.core.tool_formats import format_example
        fmt = format_name or "tag"
        return format_example(fmt, self.name, "north")

    def as_tool(self, **kwargs) -> ToolSpec:
        return ToolSpec(
            name=self.name,
            description=(
                f"{self.description} "
                f"Input: a single direction — north, east, south, or west."
            ),
            func=self.execute)

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

