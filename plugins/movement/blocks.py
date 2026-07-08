"""Movement prompt sections — package-owned thought-context contributions.

Moved out of app/core/thought_context.py (movement migration): the travel
status, the adjacent-tile overview and the travel-target list are rendered
into the agent's thought prompt via the generic ``thought_context_block``
skill hook, each including its own header and verb instruction. The core
knows no movement verb anymore; the movement ENGINE (pathfinder, movement
target, grid) stays core (R5) and is consumed here read-only.
"""
from typing import Any, Dict, List

from app.core.log import get_logger

logger = get_logger("movement_blocks")

# Cardinal directions on the grid. grid_y- = north (top of the map UI),
# grid_x+ = east. Orthogonal only — no diagonals (Move cannot step
# diagonally either).
_CARDINALS = (("North", 0, -1), ("East", 1, 0), ("South", 0, 1), ("West", -1, 0))


def _current_location_id(character_name: str) -> str:
    try:
        from app.models.character import get_character_current_location
        return (get_character_current_location(character_name) or "").strip()
    except Exception:
        return ""


def travel_section(character_name: str) -> str:
    """Active journey info: target name + remaining steps via known path.

    Empty string when no movement_target is set. Communicates that the
    system handles the movement automatically and re-issuing SetLocation
    is only needed to change the destination.
    """
    try:
        from app.models.character import get_movement_target
        target_id = get_movement_target(character_name)
        if not target_id:
            return ""
        from app.models.world import (
            get_location_name, find_path_through_known)
        from app.models.character import get_known_locations
        current_location_id = _current_location_id(character_name)
        target_name = get_location_name(target_id) or target_id
        known = get_known_locations(character_name) or []
        path = find_path_through_known(current_location_id, target_id, known) \
            if current_location_id else None
        if path and len(path) >= 2:
            steps = len(path) - 1
            body = (f"You are travelling to {target_name}. "
                    f"{steps} step(s) remaining — the system moves you one "
                    f"grid-cell per tick. RECONSIDER on every turn whether "
                    f"this journey still fits: if something here matters "
                    f"more now (a conversation, an event), cancel it with "
                    f"CancelTravel. Use SetLocation only to change the "
                    f"destination.")
        elif path and len(path) == 1:
            # already at target — will be cleared next tick
            body = f"You have arrived at {target_name}."
        else:
            body = (f"You wanted to travel to {target_name}, but the path "
                    f"through known places is no longer reachable. The "
                    f"destination will be cleared on the next tick.")
        return "=== On the road ===\n" + body
    except Exception as e:
        logger.debug("travel section failed for %s: %s", character_name, e)
        return ""


def surroundings_section(character_name: str) -> str:
    """The four orthogonally adjacent grid tiles, by cardinal direction.

    Known neighbours are named (incl. who is standing there, so the
    character can walk over on purpose). Unknown neighbours are only
    hinted at: passable terrain via its generic type name
    ("Forest (unexplored)"), unique landmarks stay hidden until
    discovered. Reachable one tile per turn via the Move tool.
    """
    try:
        current_location_id = _current_location_id(character_name)
        from app.models.world import list_locations, get_location_by_id
        from app.models.character import get_known_locations
        cur = get_location_by_id(current_location_id) if current_location_id else None
        if not cur or cur.get("grid_x") is None or cur.get("grid_y") is None:
            return ""
        gx, gy = cur["grid_x"], cur["grid_y"]
        by_cell: Dict[tuple, Dict[str, Any]] = {}
        for loc in list_locations():
            lx, ly = loc.get("grid_x"), loc.get("grid_y")
            if lx is not None and ly is not None:
                by_cell[(lx, ly)] = loc
        known = set(get_known_locations(character_name))
        lines: List[str] = []
        for label, dx, dy in _CARDINALS:
            nb = by_cell.get((gx + dx, gy + dy))
            if not nb:
                continue
            nid = nb.get("id") or ""
            if nid in known:
                name = (nb.get("name") or "?").strip()
                ann = ""
                try:
                    from app.models.group_chat import get_characters_at_location
                    people = [c.get("name") for c in get_characters_at_location(nid)
                              if c.get("name") and c.get("name") != character_name]
                    if people:
                        ann = f" ({', '.join(people)} here)"
                except Exception:
                    pass
                lines.append(f"- {label}: {name}{ann}")
            elif nb.get("passable"):
                tname = (nb.get("name") or "open terrain").strip()
                lines.append(f"- {label}: {tname} (unexplored)")
            else:
                lines.append(f"- {label}: somewhere unexplored")
        if not lines:
            return ""
        return ("=== Around you ===\n" + "\n".join(lines) + "\n"
                "Use Move <direction> (north/east/south/west) to step ONE "
                "tile — this is how you cross terrain or reach someone in an "
                "adjacent tile. Unexplored tiles become known once you step "
                "onto them.")
    except Exception as e:
        logger.debug("surroundings section failed for %s: %s", character_name, e)
        return ""


def known_locations_section(character_name: str) -> str:
    """Visibility-filtered location list the character can travel to.

    Uses ``list_locations_for_character`` (respects knowledge-item gating).
    Filters out passable tiles (transit cells) — the LLM never picks them
    as travel targets, but the pathfinder traverses them when known.
    Marks the current location with a chevron so the LLM doesn't propose
    "moving" there. Cap at 12 locations to keep the prompt slim.
    """
    try:
        current_location_id = _current_location_id(character_name)
        from app.models.world import list_locations_for_character
        locs = list_locations_for_character(character_name) or []
        if not locs:
            return ""
        lines: List[str] = []
        count = 0
        for loc in locs:
            if loc.get("passable"):
                continue
            if count >= 12:
                break
            lid = (loc.get("id") or "").strip()
            name = (loc.get("name") or lid or "?").strip()
            marker = " (you are here)" if lid and lid == current_location_id else ""
            lines.append(f"- {name}{marker}")
            count += 1
        if not lines:
            return ""
        return ("=== Places you can go ===\n" + "\n".join(lines) + "\n"
                "Use SetLocation to travel to one of these named places "
                "(the system walks you there over several ticks).")
    except Exception as e:
        logger.debug("known_locations section failed for %s: %s", character_name, e)
        return ""
