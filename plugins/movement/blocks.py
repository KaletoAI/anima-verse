"""Movement prompt sections — package-owned thought-context contributions.

Moved out of app/core/thought_context.py (movement migration): the travel
status and the travel-target list are rendered into the agent's thought
prompt via the generic ``thought_context_block`` skill hook, each including
its own header and verb instruction. The core knows no movement verb
anymore; the movement ENGINE (nav grid, travel engine, movement target)
stays core (R5) and is consumed here read-only.
"""
from typing import List

from app.core.log import get_logger

logger = get_logger("movement_blocks")


def _current_location_id(character_name: str) -> str:
    try:
        from app.models.character import get_character_current_location
        return (get_character_current_location(character_name) or "").strip()
    except Exception:
        return ""


def travel_section(character_name: str) -> str:
    """Active journey info: target name + remaining METRES + ETA, derived
    from the stored journey (no route recomputation).

    Empty string when no journey is active. Communicates that the system
    handles the movement automatically and re-issuing SetLocation is only
    needed to change the destination.
    """
    try:
        from app.core.travel_engine import get_journey, journey_state
        j = get_journey(character_name)
        if not j:
            return ""
        from app.models.world import get_location_name
        from app.core.game_time import GameTime
        from app.core.timeutils import game_time
        target_name = get_location_name(j["target"]) or j["target"]
        now = game_time()
        st = journey_state(j["waypoints"], j["started_at_game"], now)
        if st["arrived"]:
            body = f"You have arrived at {target_name}."
        else:
            remaining = max(0.0, st["total_m"] - st["progress_m"])
            eta = GameTime.parse(st["eta_game"])
            # The world knows one clock, so no "(game time)" disclaimer is
            # needed — but an arrival on a LATER day has to say so, or the
            # bare HH:MM reads as "in a moment".
            eta_text = (eta.time_hhmm() if eta.day_index == now.day_index
                        else eta.label())
            body = (f"You are travelling to {target_name} — about "
                    f"{remaining:.0f} m to go, arriving around "
                    f"{eta_text}. The journey continues "
                    f"automatically. RECONSIDER on every turn whether it "
                    f"still fits: if something here matters more now (a "
                    f"conversation, an event), cancel it with CancelTravel. "
                    f"Use SetLocation only to change the destination.")
        return "=== On the road ===\n" + body
    except Exception as e:
        logger.debug("travel section failed for %s: %s", character_name, e)
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
                "(the system walks you there as game time passes).")
    except Exception as e:
        logger.debug("known_locations section failed for %s: %s", character_name, e)
        return ""
