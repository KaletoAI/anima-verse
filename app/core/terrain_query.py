"""Point queries against the painted terrain (Seamless World, E1).

Answers "what ground is at (x, z)", "can one walk there" and "how fast"
from the painted areas + the terrain-type catalog. Every caller may pass
pre-fetched areas/catalog (hot loops fetch ONCE per request); without
them the current world state is read.

The default ground of the unpainted world is the ``game.default_terrain_kind``
config value ("grass" unless configured) — the world is walkable by
default, painting is the exception (design decision: Standard-Boden).

ONE READING PER POINT. :func:`entry_at` walks the areas once and hands back
the kind TOGETHER with its effective catalog entry; :func:`passability_at`
and :func:`speed_at` are its two readers. A second loop somewhere else is how
two answers about one square metre start to drift.

THE PACE RULE LIVES HERE AND NOWHERE ELSE (finding 3 of the E8 acceptance,
2026-08-13) — :func:`effective_speed_factor`. Passability is a WILDERNESS
question (the footprint of a place replaces the ground for the "may I stand
here"), the PACE is not: painted water slows a walker down inside a village
on a lake exactly as it does outside it. The one exception is a factor of 0
under a footprint, which is not a pace but a "this ground was never meant to
be walked" — there the plate really does replace the ground, at the neutral
1.0. The client mirror is ``client3d/src/game/walk.terrainPace``.
"""

from typing import Any, Dict, List, Optional, Tuple

from app.core.log import get_logger
from app.core.world_geometry import point_in_polygon

logger = get_logger(__name__)

FALLBACK_KIND = "grass"

# The catalog entry of a kind the catalog does not know (area painted, type
# deleted afterwards): walkable at normal speed, no animation. A hole in the
# catalog must never strand a character.
FALLBACK_ENTRY: Dict[str, Any] = {"passable": True, "speed_factor": 1.0,
                                  "meta": {}}

# Lower clamp on the pace factor. A terrain type may be configured passable
# with factor 0, and a rescued start may sit on impassable ground — neither
# may produce an infinite travel time. It is a COST clamp, which is why the
# client's mirror clamps higher (0.25 there: a walking lead below a quarter of
# its length is swallowed by the stall detector).
MIN_SPEED_FACTOR = 0.1

# The pace INSIDE a footprint whose ground carries no pace at all (factor 0).
# Not the world's default terrain: what is inside a location is a floor, not
# another patch of world.
NEUTRAL_SPEED_FACTOR = 1.0


def _config_default_kind() -> str:
    """The configured default ground — one config read per call.

    Private so :func:`kind_at` can keep a parameter named ``default_kind``
    without shadowing the public function of the same name.
    """
    from app.core import config
    return str(config.get("game.default_terrain_kind", FALLBACK_KIND)
               or FALLBACK_KIND)


def default_kind() -> str:
    return _config_default_kind()


def kind_at(x: float, z: float,
            areas: Optional[List[Dict[str, Any]]] = None,
            default_kind: Optional[str] = None) -> str:
    """Terrain kind at a world point — the topmost containing area wins.

    ``list_areas()`` returns ascending z_order/paint order, so the LAST
    containing entry is the topmost one.

    ``default_kind`` is the answer for a point no area covers. Hot loops
    (nav grid) prefetch it ONCE and pass it in; ``None`` reads it from the
    config as before.
    """
    if areas is None:
        from app.models.terrain import list_areas
        areas = list_areas()
    hit = ""
    for area in areas:
        if point_in_polygon(x, z, area.get("polygon")):
            hit = area.get("kind") or ""
    return hit or default_kind or _config_default_kind()


def entry_at(x: float, z: float,
             areas: Optional[List[Dict[str, Any]]] = None,
             catalog: Optional[Dict[str, Dict[str, Any]]] = None,
             default_kind: Optional[str] = None) -> Tuple[str, Dict[str, Any]]:
    """(kind, effective catalog entry) at a world point — ONE reading.

    A kind missing from the catalog (area painted, type deleted later)
    degrades to :data:`FALLBACK_ENTRY`: walkable at normal speed, so a
    catalog hole never strands a character. ``default_kind`` is passed
    through to :func:`kind_at` for callers that prefetched it.
    """
    if catalog is None:
        from app.core.terrain_types import effective_catalog
        catalog = effective_catalog()
    kind = kind_at(x, z, areas=areas, default_kind=default_kind)
    entry = catalog.get(kind)
    if entry is None:
        logger.warning("terrain kind %r has no catalog entry — treating "
                       "as walkable", kind)
        return kind, dict(FALLBACK_ENTRY)
    return kind, entry


def passability_at(x: float, z: float,
                   areas: Optional[List[Dict[str, Any]]] = None,
                   catalog: Optional[Dict[str, Dict[str, Any]]] = None,
                   default_kind: Optional[str] = None) -> Tuple[bool, float]:
    """(passable, RAW speed_factor) at a world point.

    The factor is the catalog's own, unclamped and without the footprint
    rule — callers that need the PACE ask :func:`speed_at` or hand this
    number to :func:`effective_speed_factor`.
    """
    _kind, entry = entry_at(x, z, areas=areas, catalog=catalog,
                            default_kind=default_kind)
    return bool(entry.get("passable", True)), float(
        entry.get("speed_factor", 1.0))


def effective_speed_factor(factor: float, in_footprint: bool) -> float:
    """THE PACE RULE (finding 3, 2026-08-13) — the one place it exists.

    The topmost terrain's ``speed_factor`` counts EVERYWHERE, inside a
    placed footprint as much as out in the wilderness: a hall standing in
    a lake is waded through, and painting the ground of a place is how one
    says so. Two clamps sit on top of it:

    * ``factor <= 0`` INSIDE a footprint is the one case where the plate
      really replaces the ground — a factor of 0 says "this was never meant
      to be walked" (rock, water in the old catalog), not "one metre costs
      forever". There the neutral :data:`NEUTRAL_SPEED_FACTOR` applies.
    * everything else is clamped up to :data:`MIN_SPEED_FACTOR`, so no
      sample can make a route infinitely expensive.

    ``in_footprint`` is the caller's lookup (nav grid: the exempt footprints
    of the route; costs: any placed footprint) — what is derivable is the
    RULE, and only the rule lives here.
    """
    if in_footprint and factor <= 0.0:
        return NEUTRAL_SPEED_FACTOR
    return max(factor, MIN_SPEED_FACTOR)


def speed_at(x: float, z: float, *, in_footprint: bool,
             areas: Optional[List[Dict[str, Any]]] = None,
             catalog: Optional[Dict[str, Dict[str, Any]]] = None,
             default_kind: Optional[str] = None) -> float:
    """The effective pace factor at a world point — :func:`entry_at` read
    through :func:`effective_speed_factor`."""
    _kind, entry = entry_at(x, z, areas=areas, catalog=catalog,
                            default_kind=default_kind)
    return effective_speed_factor(float(entry.get("speed_factor", 1.0)),
                                  in_footprint)
