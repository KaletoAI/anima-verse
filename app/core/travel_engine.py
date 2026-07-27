"""Travel engine — server-authoritative journeys across the location grid.

A journey turns a cross-location move into elapsed GAME time instead of an
instant state switch: the position is a pure function of the game clock, so
a frozen world freezes every journey with it and all clients derive the
same position from the same payload ("the server computes, clients render").

Stored on the character profile (see Task 2):
    profile["journey"] = {
        "target": "<location-id>",
        "path": ["<loc-id>", ...],      # incl. start and target cell
        "started_at_game": "<iso>",     # GAME clock stamp (game_now_iso)
        "seconds_per_cell": 60.0,       # GAME seconds per grid cell
    }
``movement_target`` stays the plain target-id field existing readers use.
"""
import asyncio
import math
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from app.core.log import get_logger
from app.core.timeutils import parse_iso

logger = get_logger("travel_engine")

# How many GAME seconds one grid cell takes. One knob for the whole world;
# it becomes a configurable game setting with the game-settings stage.
GAME_SECONDS_PER_CELL = 60.0


def journey_state(path: List[str], started_at_game: str, now_game: datetime,
                  seconds_per_cell: float) -> Dict[str, Any]:
    """Position on ``path`` at game time ``now_game`` — pure, no I/O.

    seg   index of the last passed node (0-based, max len-2)
    frac  0..1 progress from path[seg] toward path[seg+1] (1.0 when arrived)
    current_id  the NEAREST cell — that is where the character "is" for all
                game state (rules, perception, worldmap location_id)
    """
    total = max(len(path) - 1, 0)
    started = parse_iso(started_at_game)
    eta_game = (started + timedelta(seconds=total * seconds_per_cell)).isoformat()
    if total == 0:
        return {"seg": 0, "frac": 1.0, "progress_cells": 0.0,
                "current_id": path[0] if path else "", "arrived": True,
                "eta_game": eta_game}
    elapsed = (now_game - started).total_seconds()
    progress = max(0.0, elapsed / max(seconds_per_cell, 1e-9))
    if progress >= total:
        return {"seg": total - 1, "frac": 1.0, "progress_cells": float(total),
                "current_id": path[-1], "arrived": True, "eta_game": eta_game}
    seg = int(progress)
    frac = progress - seg
    # Nearest cell, ties going to the cell already left behind: a character
    # standing exactly between two cells still counts as being on the older
    # one, so the game state never flips a step early.
    current_id = path[min(max(math.ceil(progress - 0.5), 0), len(path) - 1)]
    return {"seg": seg, "frac": frac, "progress_cells": progress,
            "current_id": current_id, "arrived": False, "eta_game": eta_game}


def get_journey(character_name: str,
                profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any] | None:
    """The character's active journey dict, or None. A journey whose target
    does not match movement_target is stale (a manual teleport cleared the
    target, or a legacy writer re-pointed it) and is treated as absent.

    ``profile``: an already-loaded character profile to read from. Callers that
    hold one anyway (the worldmap loop) pass it and save a DB round-trip."""
    if not character_name:
        return None
    if profile is None:
        from app.models.character import get_character_profile
        profile = get_character_profile(character_name) or {}
    j = profile.get("journey")
    if not (isinstance(j, dict) and j.get("path") and j.get("target")
            and j.get("started_at_game")):
        return None
    if (profile.get("movement_target") or "").strip() != j.get("target"):
        return None
    return j


def start_journey(character_name: str, target_id: str) -> Dict[str, Any] | None:
    """Begin a timed journey to ``target_id`` along known locations.

    Returns the stored journey dict, or None when there is no path (or the
    character already stands on the target). Leave/access checks are the
    CALLER's job (SetLocation already does them) — this only handles the
    mechanics. Entry-room discipline: the character steps to the entry room
    of the current location, journeys always leave through it.
    """
    from app.models.character import (
        get_character_current_location, get_character_current_room,
        get_character_profile, get_known_locations,
        save_character_profile, save_character_current_room)
    from app.models.world import (
        find_path_through_known, get_entry_room_id, get_location_by_id)
    from app.core.timeutils import game_now_iso

    current = (get_character_current_location(character_name) or "").strip()
    if not current or current == target_id:
        return None
    known = get_known_locations(character_name) or []
    path = find_path_through_known(current, target_id, known)
    if not path or len(path) < 2:
        return None

    journey = {"target": target_id, "path": path,
               "started_at_game": game_now_iso(),
               "seconds_per_cell": GAME_SECONDS_PER_CELL}
    profile = get_character_profile(character_name)
    profile["journey"] = journey
    profile["movement_target"] = target_id
    save_character_profile(character_name, profile)

    loc = get_location_by_id(current)
    entry = get_entry_room_id(loc) if loc else ""
    cur_room = (get_character_current_room(character_name) or "").strip()
    if entry and cur_room and cur_room != entry:
        save_character_current_room(character_name, entry)

    try:
        from app.core.state_events import publish as _publish_state
        _publish_state("travel_started", character_name,
                       target_id=target_id, path=path,
                       eta_game=journey_state(path, journey["started_at_game"],
                                              _game_now(), GAME_SECONDS_PER_CELL)["eta_game"])
    except Exception:
        pass
    logger.info("Journey started: %s -> %s (%d cells)",
                character_name, target_id, len(path) - 1)
    return journey


def cancel_journey(character_name: str) -> None:
    """Drop journey + movement target — the character stays where they are."""
    from app.models.character import clear_movement_target
    clear_movement_target(character_name)   # clears journey too (see character.py)
    try:
        from app.core.state_events import publish as _publish_state
        _publish_state("travel_cancelled", character_name)
    except Exception:
        pass


def _game_now():
    from app.core.timeutils import game_now
    return game_now()


def advance_all_journeys() -> None:
    """Apply elapsed game time to every active journey: step
    ``current_location`` to the nearest path cell, settle arrivals.
    Called by the TravelTicker (Task 4); each call is cheap when no one
    travels. Leave rules are re-checked per advance — a rule created
    mid-route cancels the journey exactly like the old walk-step did."""
    from app.models.character import (
        get_character_current_location, list_available_characters,
        save_character_current_location)
    now = _game_now()
    for name in list_available_characters():
        j = get_journey(name)
        if not j:
            continue
        try:
            st = journey_state(j["path"], j["started_at_game"], now,
                               float(j.get("seconds_per_cell") or GAME_SECONDS_PER_CELL))
            cur = (get_character_current_location(name) or "").strip()
            if not st["arrived"] and st["current_id"] == cur:
                continue                       # nothing to apply this tick
            try:
                from app.models.rules import check_leave
                leave_ok, leave_reason = check_leave(name)
            except Exception:
                leave_ok, leave_reason = True, ""
            if not leave_ok:
                cancel_journey(name)
                logger.info("Journey blocked (leave rule): %s — %s",
                            name, leave_reason)
                continue
            if st["arrived"] or st["current_id"] == j["target"]:
                # Within the last half cell the NEAREST cell already is the
                # target — settle the arrival here. (A plain step-write of the
                # target would clear movement_target + journey inside save_…
                # anyway, but silently, skipping discover check and bump.)
                # save_… clears movement_target (location == target) and the
                # journey dict with it; entry room of the target is set inside.
                save_character_current_location(name, j["target"],
                                                _preserve_movement_target=True)
                try:
                    from app.models.rules import check_discover_rules
                    check_discover_rules(name)
                except Exception:
                    logger.debug("discover check failed for %s", name,
                                 exc_info=True)
                try:
                    from app.core.agent_loop import get_agent_loop
                    get_agent_loop().bump(name)    # think at the destination
                except Exception:
                    pass
                logger.info("Journey arrived: %s @ %s", name, j["target"])
            else:
                save_character_current_location(name, st["current_id"],
                                                _preserve_movement_target=True)
        except Exception as e:
            logger.warning("advance journey failed for %s: %s", name, e)


_TICK_SECONDS = 5.0


class TravelTicker:
    """Background loop that settles journeys every few seconds.

    Runs independently of the AgentLoop: positions must advance even while
    every character is idle or the loop is paused. A frozen world needs no
    special casing — the game clock stands still, so journey_state simply
    stops moving."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="travel-ticker")
            logger.info("TravelTicker started (%.0fs interval)", _TICK_SECONDS)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
            logger.info("TravelTicker stopped")

    async def _run(self) -> None:
        while True:
            try:
                advance_all_journeys()
            except Exception:
                logger.exception("travel tick failed")
            await asyncio.sleep(_TICK_SECONDS)


_ticker: TravelTicker | None = None


def get_travel_ticker() -> TravelTicker:
    global _ticker
    if _ticker is None:
        _ticker = TravelTicker()
    return _ticker
