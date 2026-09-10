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
        target_id = j.get("target") or ""
        # A POINT journey (E3-0) walks to a free (x, z) instead of a place, so
        # there is no name to look up — "a spot out in the open" is what the
        # character would say about it, and the metres + ETA below stay true
        # either way.
        target_name = (get_location_name(target_id) or target_id
                       if target_id else "a spot out in the open")
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

    Uses ``list_locations_for_character`` (knowledge-item gating AND
    ``known_locations``, the same gate ``travel_engine.start_journey``
    applies — so nothing is offered here that the journey would refuse).
    Marks the current location with "(you are here)" so the LLM doesn't
    propose "moving" there. Cap at 12 locations to keep the prompt slim.

    The closing line depends on whether there is anywhere ELSE to go: with
    somewhere to travel to it names the everyday occasions for a trip, and
    with nothing but the character's own place on the list it says exactly
    that instead of pointing at a verb that has no target.
    """
    try:
        current_location_id = _current_location_id(character_name)
        from app.models.world import list_locations_for_character
        locs = list_locations_for_character(character_name) or []
        if not locs:
            return ""
        lines: List[str] = []
        count = 0
        elsewhere = 0
        for loc in locs:
            if count >= 12:
                break
            lid = (loc.get("id") or "").strip()
            name = (loc.get("name") or lid or "?").strip()
            here = bool(lid) and lid == current_location_id
            marker = " (you are here)" if here else ""
            lines.append(f"- {name}{marker}")
            if not here:
                elsewhere += 1
            count += 1
        if not lines:
            return ""
        if not elsewhere:
            # The only place on the list is the one under the character's own
            # feet. Naming a travel verb here would send it against a wall —
            # say what the situation actually is instead, so the character can
            # act on it (ask to be taken along, follow someone out).
            closing = ("You know no other place yet — someone would have to "
                       "take you along, or you would have to come across one.")
        else:
            # The old wording only said HOW to travel, and the verb's own hint
            # named flight and privacy as the occasions; between the two, going
            # anywhere read as an emergency measure. Ordinary reasons are what
            # a day is made of, so they are the ones spelled out here.
            closing = ("Use SetLocation to travel to one of these named "
                       "places. Going somewhere is an ordinary part of a day "
                       "— work, a class, an errand, visiting someone, heading "
                       "home — not only something you do when you are driven "
                       "away. The system walks you there as game time passes, "
                       "so set off when the hour or your own plans call for "
                       "it.")
        return ("=== Places you can go ===\n" + "\n".join(lines) + "\n"
                + closing)
    except Exception as e:
        logger.debug("known_locations section failed for %s: %s", character_name, e)
        return ""
