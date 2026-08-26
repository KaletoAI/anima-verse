"""The HOME AREA of a temporary NPC (spec-npc-heimat-zeitfenster § E3).

A slot used to say "this place wants a barkeeper, put him in the taproom".
With a ``radius_m`` it says something else: "this place wants a poacher
SOMEWHERE AROUND IT". Such an NPC has no room and often no location at all —
it stands at a free metre point, and the action tick walks it to the next
point of the same area instead of into the next room.

That area is one dict on the profile, ``npc_home``::

    {"kind": "circle", "location_id": "loc_x", "cx": 0.0, "cz": 0.0,
     "radius_m": 60.0}

``kind`` is the whole extension point, and stage 2 of the spec uses it for the
second shape — a PAINTED TERRAIN POLYGON::

    {"kind": "area", "area_id": "ta_1a2b3c4d"}

Every function here dispatches on ``kind``, so nothing outside this module
learns what shapes exist. The area home stores only the id: the polygon, the
label and the slots live on the painted area (``models.terrain``), and an area
that is reshaped or renamed must move its NPCs with it rather than leave a
frozen copy on every profile.

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
  the mill's poacher must not be dropped into the neighbour's shed. An AREA
  home has no own place at all, so for it EVERY location is a different one.
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
KIND_AREA = "area"

#: How many points a draw tries before it gives up. A circle is sampled
#: uniformly, so 40 rejections mean the walkable share is well under a
#: percent — for the caller that is "nowhere to go right now", and the
#: placement falls back to the room. A polygon is sampled in its BOUNDING
#: BOX, so the same number buys less on a very thin shape — an acceptable
#: price for one rule instead of a triangulation.
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


def area_home(area_id: str) -> Home:
    """The home area of a slot authored on a PAINTED AREA (spec § E3.2).

    Only the id is stored — see the module docstring. Raises ``ValueError`` on
    an empty one: a home that names no area is a dict every later question
    answers "no" to, which would put an NPC on the map with an invisible
    defect instead of failing at the one place that can report it.
    """
    ident = str(area_id or "").strip()
    if not ident:
        raise ValueError("an area home needs the id of a painted area")
    return {"kind": KIND_AREA, "area_id": ident}


def _kind(home: Optional[Home]) -> str:
    return str((home or {}).get("kind") or "").strip()


def _area_of(home: Optional[Home],
             areas: Optional[Any] = None) -> Optional[Dict[str, Any]]:
    """The painted area this home names, or None when it is gone.

    ``areas`` is the list a caller already holds (``random_point`` reads the
    painted world ONCE for the whole draw); without it this asks the store for
    the single row. A deleted area answers None everywhere — the spec's rule
    for it is "the slots are gone, the living NPCs run out on their TTL or
    their window", so nothing here has to raise.
    """
    area_id = str((home or {}).get("area_id") or "").strip()
    if not area_id:
        return None
    if areas is None:
        from app.models.terrain import get_area
        return get_area(area_id)
    for area in areas or []:
        if str(area.get("id") or "") == area_id:
            return area
    return None


def _polygon_of(home: Optional[Home],
                areas: Optional[Any] = None) -> Optional[Any]:
    """The outline of the area home, or None (deleted, or not a polygon)."""
    polygon = (_area_of(home, areas) or {}).get("polygon")
    if isinstance(polygon, list) and len(polygon) >= 3:
        return polygon
    return None


# ---------------------------------------------------------------------------
# Asking about one — pure
# ---------------------------------------------------------------------------

def _contains(home: Optional[Home], px: float, pz: float,
              areas: Optional[Any] = None) -> bool:
    """:func:`contains` on an already-coerced point, with an optional
    pre-read area list — the shared half of the public test and the draw."""
    kind = _kind(home)
    if kind == KIND_CIRCLE:
        home = home or {}
        try:
            return math.hypot(px - float(home.get("cx") or 0.0),
                              pz - float(home.get("cz") or 0.0)) <= float(
                                  home.get("radius_m") or 0.0)
        except (TypeError, ValueError):
            return False
    if kind == KIND_AREA:
        from app.core.world_geometry import point_in_polygon
        polygon = _polygon_of(home, areas)
        return bool(polygon) and point_in_polygon(px, pz, polygon)
    logger.debug("contains: unknown home kind %r", kind)
    return False


def contains(home: Optional[Home], x: Any, z: Any) -> bool:
    """Whether (x, z) lies in this home area. An unknown kind contains nothing.

    An AREA home is asked of the painted world, so a deleted area contains
    nothing either — the same answer the unknown kind gets, and the same one
    the callers already handle.
    """
    try:
        px, pz = float(x), float(z)
    except (TypeError, ValueError):
        return False
    if not (math.isfinite(px) and math.isfinite(pz)):
        return False
    return _contains(home, px, pz)


def describe(home: Optional[Home]) -> str:
    """The home area in words, for the prompt: "within 60 m of the Old Mill".

    "" when the dict describes no shape this module knows — the action tick
    reads that as "no home variant" and asks the ordinary room question.

    An AREA home is its painted LABEL, nothing else: the polygon has no centre
    worth naming and no radius, and the label is the one thing an author wrote
    for exactly this purpose (which is why ``terrain.sanitize_area`` refuses
    slots without one). A deleted area has no label and therefore no
    description — the NPC falls back to the ordinary question.
    """
    kind = _kind(home)
    if kind == KIND_AREA:
        label = str(((_area_of(home) or {}).get("meta") or {}).get("label")
                    or "").strip()
        if not label:
            logger.debug("describe: area %r is gone or unnamed",
                         (home or {}).get("area_id"))
        return label
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


def _sample_circle(home: Home, rng: Any) -> Optional[Tuple[float, float]]:
    """ONE raw candidate point of the circle, before any rule is applied."""
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
    kind = _kind(home)
    if kind not in (KIND_CIRCLE, KIND_AREA):
        if kind:
            logger.warning("random_point: unknown home kind %r", kind)
        return None
    home = home or {}
    rng = rng or random
    from app.core.terrain_query import passability_at
    from app.core.terrain_types import effective_catalog
    from app.core.world_geometry import location_at_point, polygon_bounds
    from app.models.terrain import list_areas
    from app.models.world import list_locations

    areas = list_areas()
    catalog = effective_catalog()
    locations = list_locations()
    # An AREA home has no own place: it is a painted shape, not a footprint,
    # so every location its polygon happens to cover is a foreign one.
    own_id = (str(home.get("location_id") or "").strip()
              if kind == KIND_CIRCLE else "")

    if kind == KIND_AREA:
        polygon = _polygon_of(home, areas)
        bounds = polygon_bounds(polygon) if polygon else None
        if bounds is None:
            logger.debug("random_point: area %r is gone",
                         home.get("area_id"))
            return None
        min_x, min_z, max_x, max_z = bounds

        def _draw() -> Optional[Tuple[float, float]]:
            # The BOUNDING BOX, filtered by ``point_in_polygon`` below — the
            # same rejection sampling the circle runs, one shape further out.
            return (min_x + rng.random() * (max_x - min_x),
                    min_z + rng.random() * (max_z - min_z))
    else:
        def _draw() -> Optional[Tuple[float, float]]:
            return _sample_circle(home, rng)

    for _ in range(max(1, int(attempts or 1))):
        candidate = _draw()
        if candidate is None:
            return None
        x, z = round(candidate[0], 2), round(candidate[1], 2)
        # THE ROUNDED POINT IS THE ANSWER, so the rounded point is what has to
        # pass. A draw near the rim rounds outward often enough to matter (a
        # point at 45° on a 25 m rim lands on 17.68/17.68, i.e. 25.0033 m out),
        # and then this function and :func:`contains` would disagree about
        # their own circle — the caller stores the point and every later
        # containment test says it is not in the home area.
        if not _contains(home, x, z, areas):
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

def _put_at_point(name: str, home: Home) -> bool:
    """Stamp the home and set the NPC's position. False = nowhere to stand.

    The order matters: the profile carries the home BEFORE the position is
    written, because ``set_character_pos`` derives ``current_location`` and
    runs the ordinary side effects of standing somewhere, and everything that
    looks at the NPC afterwards must already see which area it belongs to.
    """
    from app.models.character import (get_character_profile,
                                      save_character_profile,
                                      set_character_pos)
    point = random_point(home)
    if point is None:
        return False
    profile = get_character_profile(name) or {}
    profile["npc_home"] = home
    save_character_profile(name, profile)
    set_character_pos(name, point[0], point[1])
    logger.info("NPC '%s' roams %s — placed at %s", name,
                describe(home) or home, point)
    return True


def place_npc(name: str, location_id: str = "", room_id: str = "",
              radius_m: Any = 0, home: Optional[Home] = None) -> str:
    """Put an NPC into the world at its slot's place. THE shared helper.

    All three ways into the world call exactly this — the pool return
    (``npc_pool.revive_from_pool``), the finish gate's job
    (``npc_assets._place``) and the generator (``npc_ops.apply_npc``) — so
    "a slot with a home area stands in the open" is decided once.

    Three placements, in this order of precedence:

    * ``home`` — a READY home dict, which today means the AREA home of a slot
      authored on a painted polygon (spec § E3.2). It needs no location at
      all and it has NO ROOM TO FALL BACK ON: an area whose ground is
      unwalkable right now yields "" and the caller reports the failure. That
      is the honest answer — the alternative would be dropping the NPC into
      an arbitrary place it has nothing to do with.
    * ``radius_m > 0`` — the CIRCLE around ``location_id`` (§ E3.1). It wins
      over ``room_id``, and an unwalkable circle falls back to the room WITH
      A WARNING, because here there is a room that belongs to the same slot.
    * otherwise the plain location + room, exactly as before.

    ``set_character_pos`` is what writes a point — the point is the truth
    there, and ``current_location`` is DERIVED from it (inside a boundary:
    that place; out in the open: "").

    Returns how it was placed: ``"point"``, ``"room"``, or ``""`` when
    nothing was written at all.
    """
    from app.models.character import (save_character_current_location,
                                      save_character_current_room)
    from app.models.world import get_location_by_id

    if not name or not (location_id or home):
        return ""
    try:
        radius = float(radius_m or 0)
    except (TypeError, ValueError):
        radius = 0.0

    try:
        if home is not None:
            if _put_at_point(name, home):
                return "point"
            logger.warning("NPC '%s': nowhere to stand in %s — not placed",
                           name, describe(home) or home)
            return ""
        if radius > 0:
            location = get_location_by_id(location_id) or {}
            cx, cz = location.get("pos_x"), location.get("pos_z")
            if cx is None or cz is None:
                logger.warning("NPC '%s': %s is not placed on the map — its "
                               "home radius %g is ignored", name, location_id,
                               radius)
            else:
                circle = circle_home(location_id, cx, cz, radius)
                if _put_at_point(name, circle):
                    return "point"
                logger.warning("NPC '%s': nowhere to stand %s — placed in "
                               "a room instead", name, describe(circle))
        save_character_current_location(name, location_id)
        if room_id:
            save_character_current_room(name, room_id)
        return "room"
    except Exception as e:  # noqa: BLE001 — the caller reports the failure
        logger.warning("NPC '%s' could not be placed at %s: %s", name,
                       location_id, e)
        return ""
