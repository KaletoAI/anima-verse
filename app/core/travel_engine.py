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
import math
from datetime import datetime, timedelta
from typing import Any, Dict, List

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
