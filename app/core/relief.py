"""Height relief of the walkable world — limits, sampler and the walk rule.

THE FIRST CONSUMER OF A HEIGHT (E8 task 1). Until now every height in this
world was a rendering detail: the scene payload lifted props and the renderers
draped the ground, but no RULE ever asked how high anything was
(``world_geometry.ground_y`` is still the flat v1 reservation). This module is
where the ground starts pushing back — a step too high and a slope too steep
stop a walker, on the relief the detail scenes already have.

Three things live here, and they are deliberately separate:

* the two WORLD SETTINGS (``game.max_step_height_m`` / ``game.max_slope_deg``)
  with the validating getters every other world dial has;
* :func:`scene_ground_lift` — the height of the scene relief at a WORLD point,
  sampled from the very grid ``compose_scene`` ships to the renderers (one
  grid construction, ``scene_recipe.compose_terrain``);
* :func:`slope_blocks` — the RULE as a pure predicate, so the client mirror
  (``client3d/src/game/walk.ts`` ``slopeBlocks``) and this side can be checked
  against the same hand-derived table.

The rule itself, in one sentence: over a SHORT report (< 1 m) a height change
is a STEP and is capped by ``max_step_height_m``; over anything longer it is a
SLOPE and is capped by ``max_slope_deg``. Two rules rather than one because a
1 m wall and a 1 m rise over 20 m are not the same obstacle — the first is
unclimbable at any pace, the second is a gentle hill.
"""

import hashlib
import json
import math
from typing import Any, Dict, List, Optional, Tuple

from app.core.log import get_logger

logger = get_logger("relief")

#: Highest step a walker takes in one go, in metres, when the world setting
#: ``game.max_step_height_m`` is missing or unusable — a high kerb, half a
#: staircase step more than a comfortable one.
DEFAULT_MAX_STEP_M = 0.4
_MIN_STEP_M = 0.05
_MAX_STEP_M = 5.0

#: Steepest slope a walker climbs, in degrees, when ``game.max_slope_deg`` is
#: missing or unusable. 40° is a scramble but still walkable; a cliff is not.
DEFAULT_MAX_SLOPE_DEG = 40.0
_MIN_SLOPE_DEG = 10.0
_MAX_SLOPE_DEG = 89.0

#: Below this horizontal distance a height change counts as a STEP, above it
#: as a SLOPE (metres). One metre is the scale of the reports themselves: a
#: client walking at 3.4 m/s and reporting ~3 times a second moves about a
#: metre between two points, so "shorter than one report" is exactly the
#: length over which a rise is something one has to climb rather than walk up.
#: Mirrored in ``client3d/src/game/walk.ts``.
STEP_DISTANCE_M = 1.0


def _reject(setting: str, raw: Any, default: float) -> float:
    """Log a discarded world setting ONCE and return the default — the getters
    sit on a per-report path, a warning per report would spam the log."""
    if not _warned.get(setting):
        _warned[setting] = True
        logger.warning("Unusable %s (%r) — using the default %s",
                       setting, raw, default)
    return default


_warned: Dict[str, bool] = {}


def _limit(setting: str, default: float, low: float, high: float) -> float:
    """One validating world-setting reader (the ``get_travel_speed_m_s``
    pattern): missing, non-numeric, bool, NaN/inf, zero or negative -> the
    default; anything else clamped into [``low``, ``high``]."""
    from app.core import config
    raw = config.get(setting, default)
    if raw is None:
        return default
    if isinstance(raw, bool):
        return _reject(setting, raw, default)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return _reject(setting, raw, default)
    if not math.isfinite(value) or value <= 0:
        return _reject(setting, raw, default)
    return min(max(value, low), high)


def get_max_step_height_m() -> float:
    """Highest step a walker takes, from ``game.max_step_height_m``.

    Zero counts as garbage on purpose: an emptied admin field arrives as 0,
    and reading that as "no step at all is ever allowed" would nail every
    walker to the spot without anyone asking for it.
    """
    return _limit("game.max_step_height_m", DEFAULT_MAX_STEP_M,
                  _MIN_STEP_M, _MAX_STEP_M)


def get_max_slope_deg() -> float:
    """Steepest slope a walker climbs, from ``game.max_slope_deg``. Capped at
    89°: 90° is a vertical wall, where the tangent explodes and the rule would
    stop meaning anything."""
    return _limit("game.max_slope_deg", DEFAULT_MAX_SLOPE_DEG,
                  _MIN_SLOPE_DEG, _MAX_SLOPE_DEG)


def slope_blocks(dh: float, dist: float, max_step: float,
                 max_slope_deg: float) -> bool:
    """Does a height change of ``dh`` over ``dist`` metres stop a walker?

    PURE — no config, no world, no state. The client owns the identical
    predicate (``slopeBlocks``), and both are checked against the same
    hand-derived table (``scripts/smoke_slope_gate.py``,
    ``client3d/scripts/smoke_walk_math.mjs``).

      * ``dist < STEP_DISTANCE_M`` -> a STEP: blocked when ``|dh| > max_step``.
      * otherwise a SLOPE: blocked when ``atan(|dh| / dist)`` exceeds
        ``max_slope_deg``.

    Direction does not matter — falling down a cliff is as impossible as
    climbing it, and a walker who may go down somewhere it cannot come back up
    is a walker one can strand. Level ground (``dh == 0``) is never blocked,
    which also makes the whole gate inert in a world without relief.
    """
    rise = abs(float(dh))
    if not rise:
        return False
    if float(dist) < STEP_DISTANCE_M:
        return rise > float(max_step)
    return math.degrees(math.atan2(rise, float(dist))) > float(max_slope_deg)


# ── The scene relief as a height over the world ─────────────────────────

#: location id -> (fingerprint, rotated grid, extent). The grid is a pure
#: function of the location's plan, and the gate samples it up to twice per
#: report at ~4 reports a second per avatar — recomposing the room recipes
#: each time would tessellate every curved room edge for a lookup. The
#: fingerprint covers everything the field is built from, so an author's edit
#: reaches the rule with the next report.
_grid_cache: Dict[str, Tuple[str, List[List[float]], float]] = {}


def _fingerprint(map3d: Dict[str, Any], rooms: List[Dict[str, Any]],
                 variant: int) -> str:
    """Everything the height field is built from, hashed: the ``map3d`` blob
    (relief seed/amplitude/wave, ``area_detail``, ``tile_rotation``, the scale
    anchor) plus every room layout (the flat hulls) plus the clone variant."""
    payload = {
        "map3d": map3d or {},
        "rooms": [[str(r.get("id") or ""), r.get("layout") or {}]
                  for r in rooms if isinstance(r, dict)],
        "variant": variant,
    }
    return hashlib.md5(json.dumps(payload, sort_keys=True,
                                  default=str).encode()).hexdigest()


def _terrain_of(loc: Dict[str, Any], width_m: float
                ) -> Optional[List[List[float]]]:
    """The location's height field as the CLIENT gets it (tile rotation
    applied), or ``None`` when the location has no relief."""
    from app.core.room_recipe import compose_recipe
    from app.core.scene_recipe import (compose_terrain, derive_scalars,
                                       rotate_terrain_grid)
    map3d = loc.get("map3d") or {}
    if not isinstance(map3d.get("relief"), dict) or not map3d.get("area_detail"):
        return None
    rooms = [r for r in (loc.get("rooms") or []) if isinstance(r, dict)]
    variant = int(loc.get("variant_seed") or 0)
    key = str(loc.get("id") or "")
    fp = _fingerprint(map3d, rooms, variant)
    cached = _grid_cache.get(key) if key else None
    if cached and cached[0] == fp and cached[2] == width_m:
        return cached[1]
    # The reference square IS the footprint (k = 1 since E4), so the width the
    # gate measured the point against is also the scale the field is built on.
    extent, _k, _storey = derive_scalars(map3d, width_m)
    recipes = [rec for rec in
               (compose_recipe(room, [r for r in rooms if r is not room],
                               width_m, variant_seed=variant)
                for room in rooms) if rec]
    terrain, _relief_rooms = compose_terrain(map3d, recipes, extent, variant)
    if not terrain:
        return None
    # ``tile_rotation`` is applied to the FINISHED payload, so the grid the
    # renderers hold is the rotated one — the gate has to judge that field,
    # not the template's.
    rotation = int(float((map3d.get("tile_rotation") or 0) or 0))
    grid = rotate_terrain_grid(terrain["grid"], rotation // 90
                               if rotation in (90, 180, 270) else 0)
    if key:
        _grid_cache[key] = (fp, grid, width_m)
    return grid


def scene_ground_lift(loc: Optional[Dict[str, Any]], x: float,
                      z: float) -> float:
    """Height of a location's scene relief at the WORLD point (x, z), metres.

    0.0 everywhere else — outside a placed footprint, on a location without an
    ``area_detail`` relief, and on the pinned border of the field itself. That
    is not a placeholder: the world plate is flat until the E8 heightmap
    lands, and the only heights that exist today are the detail scenes'.

    THE FRAME, the one thing that can silently be wrong here. The payload is
    anchored around the TILE CENTRE in the location's own turned frame, and
    the client samples it exactly that way (``scene/tiles.terrainLiftAt`` →
    ``worldToLocalXZ`` → ``sampleTerrain``). So does this: turn the world point
    into the footprint's local frame, then read the plan fraction off the
    reference square (``u = lx / extent + 0.5``, ``v = lz / extent + 0.5``) and
    sample the same bilinear field (``scatter_curves.terrain_height``). Both
    turns are the SAME formula (``world_geometry.world_to_local`` and
    ``scene-render`` ``worldToLocalXZ``), which is what keeps the rule and the
    picture on one ground.
    """
    if not loc:
        return 0.0
    from app.core.scatter_curves import terrain_height
    from app.core.world_geometry import placed_footprint, world_to_local
    fp = placed_footprint(loc)
    if fp is None:
        return 0.0
    cx, cz, width, yaw = fp
    grid = _terrain_of(loc, width)
    if not grid:
        return 0.0
    lx, lz = world_to_local(x, z, cx, cz, yaw)
    return terrain_height(grid, lx / width + 0.5, lz / width + 0.5)
