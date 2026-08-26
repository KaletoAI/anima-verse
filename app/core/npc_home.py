"""The HOME AREA of a temporary NPC (spec-npc-heimat-zeitfenster § E3).

A slot used to say "this place wants a barkeeper, put him in the taproom".
With a ``radius_m`` it says something else: "this place wants a poacher
SOMEWHERE AROUND IT". Such an NPC has no room and often no location at all —
it stands at a free metre point, and the action tick walks it to the next
point of the same area instead of into the next room.

That area is one dict on the profile, ``npc_home``::

    {"kind": "circle", "location_id": "loc_x", "cx": 0.0, "cz": 0.0,
     "radius_m": 60.0}

``kind`` is the whole extension point: stage 2 of the spec adds
``{"kind": "area", "area_id": …}`` (a painted terrain polygon) and every
function here dispatches on it, so nothing outside this module learns what
shapes exist.

Everything above the placement section is PURE geometry plus two world reads
(the painted terrain and the placed locations, both fetched ONCE per call) —
no clock, no ``datetime``, no side effects. The one impure function is
:func:`place_npc` at the bottom: the single placement helper all three entry
paths into the world share (``npc_pool.revive_from_pool``,
``npc_assets._place``, ``npc_ops.apply_npc``).

TWO RULES DECIDE WHETHER A POINT IS ACCEPTABLE, and both mirror what the
travel engine does at a journey GOAL (``start_journey_to_point``), because
that is where the NPC is sent afterwards:

* **The place wins.** Out in the open the painted terrain says whether one
  may stand somewhere (``terrain_query.passability_at``); inside a placed
  footprint the place brings its own floor and the terrain is not asked.
* **But only the OWN place.** A point journey runs no entry gate at its goal,
  so a point inside a DIFFERENT location's boundary is rejected outright —
  the mill's poacher must not be dropped into the neighbour's shed.
"""
from __future__ import annotations

import math
import random
from typing import Any, Dict, Optional, Tuple

from app.core.log import get_logger

logger = get_logger("npc_home")

#: One home area. ``kind`` says which shape the other keys describe.
Home = Dict[str, Any]

KIND_CIRCLE = "circle"

#: How many points a draw tries before it gives up. A circle is sampled
#: uniformly, so 40 rejections mean the walkable share is well under a
#: percent — for the caller that is "nowhere to go right now", and the
#: placement falls back to the room.
DEFAULT_ATTEMPTS = 40

#: The shortest walk the roaming tick will start, in metres. Without it a
#: draw may land next to the NPC's own feet, and the journey would be one
#: waypoint long — a step nobody sees and a tick spent on nothing.
MIN_ROAM_DIST_M = 3.0


# ---------------------------------------------------------------------------
# Building one
# ---------------------------------------------------------------------------

def circle_home(location_id: str, cx: float, cz: float,
                radius_m: float) -> Home:
    """The home area of a slot with ``radius_m``: a circle around its place.

    Raises ``ValueError`` on a coordinate or radius that is not a finite
    number — a NaN would sail through every later comparison (every NaN
    comparison is False) and put a poisoned dict on the profile.
    """
    values = []
    for raw in (cx, cz, radius_m):
        try:
            value = float(raw)
        except (TypeError, ValueError):
            raise ValueError(f"home coordinates must be numeric, got {raw!r}")
        if not math.isfinite(value):
            raise ValueError(f"home coordinates must be finite, got {raw!r}")
        values.append(round(value, 2))
    return {"kind": KIND_CIRCLE, "location_id": str(location_id or "").strip(),
            "cx": values[0], "cz": values[1], "radius_m": values[2]}


def _kind(home: Optional[Home]) -> str:
    return str((home or {}).get("kind") or "").strip()


# ---------------------------------------------------------------------------
# Asking about one — pure
# ---------------------------------------------------------------------------

def contains(home: Optional[Home], x: Any, z: Any) -> bool:
    """Whether (x, z) lies in this home area. An unknown kind contains nothing."""
    kind = _kind(home)
    try:
        px, pz = float(x), float(z)
    except (TypeError, ValueError):
        return False
    if not (math.isfinite(px) and math.isfinite(pz)):
        return False
    if kind == KIND_CIRCLE:
        home = home or {}
        try:
            return math.hypot(px - float(home.get("cx") or 0.0),
                              pz - float(home.get("cz") or 0.0)) <= float(
                                  home.get("radius_m") or 0.0)
        except (TypeError, ValueError):
            return False
    logger.debug("contains: unknown home kind %r", kind)
    return False


def describe(home: Optional[Home]) -> str:
    """The home area in words, for the prompt: "within 60 m of the Old Mill".

    "" when the dict describes no shape this module knows — the action tick
    reads that as "no home variant" and asks the ordinary room question.
    """
    kind = _kind(home)
    if kind != KIND_CIRCLE:
        if kind:
            logger.debug("describe: unknown home kind %r", kind)
        return ""
    home = home or {}
    from app.models.world import get_location_name
    location_id = str(home.get("location_id") or "")
    name = (get_location_name(location_id) if location_id else "") or location_id
    try:
        radius = float(home.get("radius_m") or 0.0)
    except (TypeError, ValueError):
        return ""
    return f"within {radius:.0f} m of {name}" if name else f"within {radius:.0f} m"


def _sample(home: Home, rng: Any) -> Optional[Tuple[float, float]]:
    """ONE raw candidate point of the shape, before any rule is applied."""
    if _kind(home) != KIND_CIRCLE:
        return None
    try:
        cx, cz = float(home.get("cx") or 0.0), float(home.get("cz") or 0.0)
        radius = float(home.get("radius_m") or 0.0)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(cx) and math.isfinite(cz)) or radius <= 0:
        return None
    # sqrt of the uniform draw, else the points crowd around the centre: the
    # area of a ring grows with its distance, so the radius has to as well.
    r = radius * math.sqrt(rng.random())
    angle = rng.random() * 2.0 * math.pi
    return cx + r * math.cos(angle), cz + r * math.sin(angle)


def random_point(home: Optional[Home], *, rng: Any = None,
                 attempts: int = DEFAULT_ATTEMPTS,
                 min_dist_from: Optional[Tuple[float, float]] = None
                 ) -> Optional[Tuple[float, float]]:
    """A random point of the home area an NPC may stand on, or ``None``.

    Rejection sampling against the two rules in the module docstring (the
    place wins; but only the own place), plus ``min_dist_from``: a point
    within :data:`MIN_ROAM_DIST_M` of that position is rejected, which is how
    the roaming tick avoids starting a journey to where the NPC already
    stands. Every test runs on the ROUNDED point, :func:`contains` included —
    what this function returns is what the world stores.

    ``None`` means "nowhere to go right now" — every attempt was rejected.
    The caller decides what that means: the placement falls back to the room,
    the action tick simply writes the activity and skips the walk.

    The painted areas, the terrain catalog and the placed locations are read
    ONCE for the whole draw, not once per attempt.
    """
    if _kind(home) not in (KIND_CIRCLE,):
        if _kind(home):
            logger.warning("random_point: unknown home kind %r", _kind(home))
        return None
    home = home or {}
    rng = rng or random
    from app.core.terrain_query import passability_at
    from app.core.terrain_types import effective_catalog
    from app.core.world_geometry import location_at_point
    from app.models.terrain import list_areas
    from app.models.world import list_locations

    areas = list_areas()
    catalog = effective_catalog()
    locations = list_locations()
    own_id = str(home.get("location_id") or "").strip()

    for _ in range(max(1, int(attempts or 1))):
        candidate = _sample(home, rng)
        if candidate is None:
            return None
        x, z = round(candidate[0], 2), round(candidate[1], 2)
        # THE ROUNDED POINT IS THE ANSWER, so the rounded point is what has to
        # pass. A draw near the rim rounds outward often enough to matter (a
        # point at 45° on a 25 m rim lands on 17.68/17.68, i.e. 25.0033 m out),
        # and then this function and :func:`contains` would disagree about
        # their own circle — the caller stores the point and every later
        # containment test says it is not in the home area.
        if not contains(home, x, z):
            continue
        if min_dist_from is not None:
            try:
                if math.hypot(x - float(min_dist_from[0]),
                              z - float(min_dist_from[1])) < MIN_ROAM_DIST_M:
                    continue
            except (TypeError, ValueError, IndexError):
                pass          # an unusable reference point simply does not gate
        here = location_at_point(x, z, locations)
        here_id = (str(here.get("id") or "") if here else "")
        if here_id and here_id != own_id:
            continue          # a different place — nobody may be dropped in it
        if not here_id and not passability_at(x, z, areas, catalog)[0]:
            continue          # out in the open the ground decides
        return x, z
    logger.debug("random_point: no walkable point in %s after %d attempts",
                 describe(home) or home, attempts)
    return None


# ---------------------------------------------------------------------------
# Placement — the one impure function
# ---------------------------------------------------------------------------

def place_npc(name: str, location_id: str, room_id: str = "",
              radius_m: Any = 0) -> str:
    """Put an NPC into the world at its slot's place. THE shared helper.

    All three ways into the world call exactly this — the pool return
    (``npc_pool.revive_from_pool``), the finish gate's job
    (``npc_assets._place``) and the generator (``npc_ops.apply_npc``) — so
    "a slot with a radius stands in the open" is decided once.

    ``radius_m > 0`` WINS OVER ``room_id``: the NPC is placed at a random
    point of the circle around its location and carries the area as
    ``npc_home``. ``set_character_pos`` is what writes it — the point is the
    truth there, and ``current_location`` is DERIVED from it (inside a
    boundary: that place; out in the open: "").

    Returns how it was placed: ``"point"``, ``"room"``, or ``""`` when
    nothing was written at all. A radius whose circle holds no walkable point
    right now falls back to the room WITH A WARNING — an NPC that stands
    nowhere is worse than one that stands indoors.
    """
    from app.models.character import (get_character_profile,
                                      save_character_current_location,
                                      save_character_current_room,
                                      save_character_profile,
                                      set_character_pos)
    from app.models.world import get_location_by_id

    if not name or not location_id:
        return ""
    try:
        radius = float(radius_m or 0)
    except (TypeError, ValueError):
        radius = 0.0

    try:
        if radius > 0:
            location = get_location_by_id(location_id) or {}
            cx, cz = location.get("pos_x"), location.get("pos_z")
            if cx is None or cz is None:
                logger.warning("NPC '%s': %s is not placed on the map — its "
                               "home radius %g is ignored", name, location_id,
                               radius)
            else:
                home = circle_home(location_id, cx, cz, radius)
                point = random_point(home)
                if point is None:
                    logger.warning("NPC '%s': nowhere to stand %s — placed in "
                                   "a room instead", name, describe(home))
                else:
                    profile = get_character_profile(name) or {}
                    profile["npc_home"] = home
                    save_character_profile(name, profile)
                    set_character_pos(name, point[0], point[1])
                    logger.info("NPC '%s' roams %s — placed at %s", name,
                                describe(home), point)
                    return "point"
        save_character_current_location(name, location_id)
        if room_id:
            save_character_current_room(name, room_id)
        return "room"
    except Exception as e:  # noqa: BLE001 — the caller reports the failure
        logger.warning("NPC '%s' could not be placed at %s: %s", name,
                       location_id, e)
        return ""
