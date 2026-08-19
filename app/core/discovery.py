"""Discovery by SIGHT — a place becomes known by coming close to it (E6).

Before the metre world, a location entered a character's ``known_locations``
two ways: by ENTERING it (``save_character_current_location`` writes it — the
first way, untouched and still there) or through a ``discover`` RULE that
rolled over the GRID NEIGHBOURS of the cell one stood in. The seamless world
has no grid and no neighbour lists, so that rule walked an always-empty list:
a dead mechanic with a UI in front of it.

Sight range replaces the neighbour list with a DISTANCE. Everything whose
footprint lies within ``game.discovery_range_m`` metres of where a character
stands becomes known — walking past a hut is enough, walking INTO it is no
longer required. Additive only: this module never removes anything, and a
shrinking range never un-knows a place (``known_locations`` stays strict — a
missing list means "knows nothing", never "knows everything").

WHO ASKS. Two hooks feed it, both at the place where a character's point
actually changes:
  * ``travel_engine.advance_all_journeys`` — the travel ticker, every few real
    seconds, for EVERY character with a point (not only for travellers: a
    scheduler, a spell or an admin can put someone down beside a hut too),
  * ``routes/play.py`` ``POST /play/pos`` — the avatar's own report, after it
    was ACCEPTED. A refused report moved nobody and must reveal nothing.
``rules.check_discover_rules`` uses the same geometry through
:func:`locations_within`, but keeps its own semantics: condition-gated, a
probability roll, exactly ONE random place, and a player-visible message.

The geometry itself is ``world_geometry.boundary_distance_m`` — measured to the
location's drawn OUTLINE (contract v6 "Gebiete"; a legacy square dial is just
that outline's four corners), not to its centre, so a wide plaza is "close" as
soon as its edge is, and 0 inside.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional

from app.core.log import get_logger

logger = get_logger("discovery")

DEFAULT_DISCOVERY_RANGE_M = 50.0
_MIN_DISCOVERY_RANGE_M = 0.0
_MAX_DISCOVERY_RANGE_M = 1000.0


def get_discovery_range_m() -> float:
    """How close a character has to come before a place is discovered, in
    world metres, from the world setting ``game.discovery_range_m``.

    The boundary between "garbage" and "extreme but meant":
      * missing, non-numeric, bool, NaN/inf, **negative** -> the default,
      * **zero is MEANT** and switches discovery off. This is the one place
        where 0 differs from the hearing radius (whose 0 is an emptied admin
        field): the schema minimum here is 0 and its label says so, because a
        world that wants its map handed out by other means — rules, quests, a
        prepared ``known_locations`` — must be able to say that,
      * anything above 1000 m is clamped down; at that point the whole map is
        in sight anyway and the number only costs distance checks.
    """
    from app.core import config
    raw = config.get("game.discovery_range_m", DEFAULT_DISCOVERY_RANGE_M)
    if raw is None:
        return DEFAULT_DISCOVERY_RANGE_M
    if isinstance(raw, bool):
        return _reject_range(raw)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return _reject_range(raw)
    if not math.isfinite(value) or value < 0:
        return _reject_range(raw)
    return min(max(value, _MIN_DISCOVERY_RANGE_M), _MAX_DISCOVERY_RANGE_M)


_range_warned = False


def _reject_range(raw: Any) -> float:
    """Log the discarded setting ONCE and return the default — this sits in
    the travel ticker's inner loop, a warning per character per tick would
    drown the log."""
    global _range_warned
    if not _range_warned:
        _range_warned = True
        logger.warning("Unusable game.discovery_range_m (%r) — using the "
                       "default %.1f m", raw, DEFAULT_DISCOVERY_RANGE_M)
    return DEFAULT_DISCOVERY_RANGE_M


def locations_within(x: float, z: float, range_m: float,
                     locations: Optional[List[Dict[str, Any]]] = None,
                     *, exclude: Iterable[str] = ()) -> List[str]:
    """IDs of PLACED locations whose BOUNDARY is within ``range_m`` of the
    point — the ONE distance expression discovery has.

    ``locations`` is the prefetched ``list_locations()`` snapshot; ``None``
    reads it. ``exclude`` drops ids before the geometry runs (the caller's
    ``known_locations``), so the common "knows everything nearby already" case
    costs no distance checks at all.

    A location without area (no point, and neither a drawn ``map3d.boundary``
    nor a legacy width dial) is never in range — ``boundary_distance_m``
    answers ``inf`` for it, so no separate "is it placed" test is needed.
    """
    from app.core.world_geometry import boundary_distance_m
    if range_m < 0 or not (math.isfinite(x) and math.isfinite(z)):
        return []
    if locations is None:
        from app.models.world import list_locations
        locations = list_locations()
    skip = set(exclude or ())
    out: List[str] = []
    for loc in locations or []:
        loc_id = (loc.get("id") or "").strip()
        if not loc_id or loc_id in skip:
            continue
        if boundary_distance_m(loc, x, z) <= range_m:
            out.append(loc_id)
    return out


def discover_in_range(character_name: str, x: float, z: float, *,
                      locations: Optional[List[Dict[str, Any]]] = None
                      ) -> List[str]:
    """Discover everything in sight of (x, z) for a character. Returns the
    ids that were NEW — an empty list means nothing changed.

    Idempotent by construction: what is already known is excluded before the
    geometry, and ``add_known_location`` is idempotent on top of that. A range
    of 0 switches the whole thing off (see :func:`get_discovery_range_m`).

    ``locations`` lets a hot loop prefetch the snapshot ONCE (the travel
    ticker reads it per tick, not per character).
    """
    from app.models.character import add_known_location, get_known_locations
    if not character_name:
        return []
    range_m = get_discovery_range_m()
    if range_m <= 0:
        return []
    known = get_known_locations(character_name)
    found = locations_within(x, z, range_m, locations, exclude=known)
    for loc_id in found:
        add_known_location(character_name, loc_id)
    if found:
        logger.info("Discovered by sight: %s -> %s", character_name,
                    ", ".join(found))
    return found
