"""Point queries against the painted terrain (Seamless World, E1).

Answers "what ground is at (x, z)" and "can one walk there" from the
painted areas + the terrain-type catalog. Every caller may pass
pre-fetched areas/catalog (hot loops fetch ONCE per request); without
them the current world state is read.

The default ground of the unpainted world is the ``game.default_terrain_kind``
config value ("grass" unless configured) — the world is walkable by
default, painting is the exception (design decision: Standard-Boden).
"""

from typing import Any, Dict, List, Optional, Tuple

from app.core.log import get_logger
from app.core.world_geometry import point_in_polygon

logger = get_logger(__name__)

FALLBACK_KIND = "grass"


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


def passability_at(x: float, z: float,
                   areas: Optional[List[Dict[str, Any]]] = None,
                   catalog: Optional[Dict[str, Dict[str, Any]]] = None,
                   default_kind: Optional[str] = None) -> Tuple[bool, float]:
    """(passable, speed_factor) at a world point.

    A kind missing from the catalog (area painted, type deleted later)
    degrades to walkable at normal speed — a catalog hole must never
    strand a character. ``default_kind`` is passed through to
    :func:`kind_at` for callers that prefetched it.
    """
    if catalog is None:
        from app.core.terrain_types import effective_catalog
        catalog = effective_catalog()
    kind = kind_at(x, z, areas=areas, default_kind=default_kind)
    entry = catalog.get(kind)
    if entry is None:
        logger.warning("terrain kind %r has no catalog entry — treating "
                       "as walkable", kind)
        return True, 1.0
    return bool(entry.get("passable", True)), float(
        entry.get("speed_factor", 1.0))
