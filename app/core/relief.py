"""Height relief of the walkable world — limits, sampler and the walk rule.

THE FIRST CONSUMER OF A HEIGHT (E8 task 1). Until now every height in this
world was a rendering detail: the scene payload lifted props and the renderers
draped the ground, but no RULE ever asked how high anything was. This module is
where the ground starts pushing back — a step too high and a slope too steep
stop a walker, on the relief the detail scenes already have and, since task 2,
on the authored world relief under them (``world_geometry.ground_y``).

Three things live here, and they are deliberately separate:

* the two WORLD SETTINGS (``game.max_step_height_m`` / ``game.max_slope_deg``)
  with the validating getters every other world dial has;
* :func:`scene_ground_lift` — the height of the scene relief at a WORLD point,
  sampled from the very grid ``compose_scene`` ships to the renderers (one
  grid construction, ``scene_recipe.compose_terrain``);
* :func:`slope_blocks` — the RULE as a pure predicate, so the client mirror
  (``client3d/src/game/walk.ts`` ``slopeBlocks``) and this side can be checked
  against the same hand-derived table.

The rule itself, in one sentence: the SLOPE limit (``max_slope_deg``) holds
over EVERY distance, and below a metre the STEP limit (``max_step_height_m``)
holds ON TOP of it. Two limits rather than one because a 1 m wall and a 1 m
rise over 20 m are not the same obstacle — the first is unclimbable at any
pace, the second is a gentle hill; and they hold together rather than
either/or because each one alone can be walked round (see
:func:`slope_blocks`).
"""

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

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

    THE TWO LIMITS APPLY TOGETHER, and the step is the ADDITIONAL one:

      * the SLOPE limit holds at every distance — blocked when
        ``atan(|dh| / dist)`` exceeds ``max_slope_deg``;
      * BELOW ``STEP_DISTANCE_M`` the step limit holds on top of it — blocked
        when ``|dh| > max_step``, however gentle the angle would call it.

    It was an either/or once (step under a metre, slope above it), and that
    was wrong twice over (review 2026-08-13). First, the two sides of the
    mirror measure over DIFFERENT lengths: the client tests a walking lead of
    ~0.15 m, the server a report step of ~1.12 m. With an either/or the whole
    band between ``max_slope_deg`` and the angle the same rise makes over a
    lead — 40° to 69° at the defaults — was invisible to the client and
    refused by the server, which is a figure walking on while the server
    snaps it back three times a second. Second, an either/or makes EVERY slope
    climbable by walking slowly: report 0.1 m at a time and a 76° wall passes
    as a legal "step". A limit one gets round by being patient is not a limit.

    Direction does not matter — falling down a cliff is as impossible as
    climbing it, and a walker who may go down somewhere it cannot come back up
    is a walker one can strand. Level ground (``dh == 0``) is never blocked,
    which also makes the whole gate inert in a world without relief.
    """
    rise = abs(float(dh))
    if not rise:
        return False
    dist = float(dist)
    return (dist < STEP_DISTANCE_M and rise > float(max_step)) \
        or math.degrees(math.atan2(rise, dist)) > float(max_slope_deg)


# ── The scene relief as a height over the world ─────────────────────────

#: location id -> (fingerprint, footprint width, grid, terrain frame). The
#: grid is a pure
#: function of the location's plan, and the gate samples it up to twice per
#: report at ~4 reports a second per avatar — recomposing the room recipes
#: each time would tessellate every curved room edge for a lookup. The
#: fingerprint covers everything the field is built from, so an author's edit
#: reaches the rule with the next report.
_grid_cache: Dict[str, Tuple[str, float, List[List[float]],
                              Tuple[float, float, float]]] = {}


def _fingerprint(map3d: Dict[str, Any], rooms: List[Dict[str, Any]],
                 variant: int) -> str:
    """Everything the height field is built from, hashed.

    ``scene_recipe.layout_signature`` is the shared part — the ``map3d`` blob
    (relief seed/amplitude/wave, ``area_detail``, the drawn boundary, the
    scale anchor) plus every room layout (the flat hulls); it is the same signature
    the worldmap payload ships as ``layout_sig``, so there is ONE answer to
    "what shapes this scene". The clone VARIANT is added on top and is exactly
    why the payload's own ``layout_sig`` cannot be reused as it stands: it does
    not cover ``variant_seed``, and two clones of one template differ in
    nothing else — their fields would collide in this cache.
    """
    from app.core.scene_recipe import layout_signature
    return f"{layout_signature(map3d, rooms)}:{variant}"


def _terrain_of(loc: Dict[str, Any], width_m: float
                ) -> Optional[Tuple[List[List[float]],
                                    Tuple[float, float, float]]]:
    """The location's height field as the CLIENT gets it plus the frame it is
    spanned over (``scene_recipe.terrain_frame``), or ``None`` when the
    location has no relief."""
    from app.core.room_recipe import compose_recipe
    from app.core.scene_recipe import (compose_terrain, derive_scalars,
                                       terrain_frame)
    map3d = loc.get("map3d") or {}
    if not isinstance(map3d.get("relief"), dict) or not map3d.get("area_detail"):
        return None
    rooms = [r for r in (loc.get("rooms") or []) if isinstance(r, dict)]
    variant = int(loc.get("variant_seed") or 0)
    key = str(loc.get("id") or "")
    fp = _fingerprint(map3d, rooms, variant)
    cached = _grid_cache.get(key) if key else None
    if cached and cached[0] == fp and cached[1] == width_m:
        return cached[2], cached[3]
    # ``extent_m`` IS the footprint width (k = 1 since E4), so the width the
    # gate measured the point against is also the edge of the terrain frame.
    extent, _k, _storey = derive_scalars(map3d, width_m)
    recipes = [rec for rec in
               (compose_recipe(room, [r for r in rooms if r is not room],
                               variant_seed=variant, map3d=map3d)
                for room in rooms) if rec]
    terrain, _relief_rooms = compose_terrain(map3d, recipes, extent, variant)
    if not terrain:
        return None
    # The field the renderers hold IS this one: since v6 (Nr. 4) nothing turns
    # the finished payload any anymore — a location faces the way its pin says
    # (§ A1.1), so the gate and the picture read the very same grid.
    grid = terrain["grid"]
    frame = terrain_frame(map3d, extent)
    if key:
        _grid_cache[key] = (fp, width_m, grid, frame)
    return grid, frame


def scene_ground_lift(loc: Optional[Dict[str, Any]], x: float,
                      z: float) -> float:
    """Height of a location's scene relief at the WORLD point (x, z), metres.

    0.0 everywhere else — on a location without a drawn boundary (it has no
    area, so it has no scene ground either), on a location without an
    ``area_detail`` relief, and on the pinned border of the field itself. This
    is the SCENE half of the height alone: what the world ground does under it
    is ``world_geometry.ground_y``, and ``ground_lift_at`` adds the two.

    THE FRAME, the one thing that can silently be wrong here. The payload is
    anchored in the location's own turned frame around its PIN, and the client
    samples it exactly that way (``scene/tiles.terrainLiftAt`` →
    ``worldToLocalXZ`` → ``sampleTerrain``). So does this: turn the world point
    into the location's local frame, then read the lattice coordinate off the
    TERRAIN FRAME (``scene_recipe.terrain_frame``: the square of edge
    ``extent_m`` over the boundary's bounding box — since v6 Nr. 2 that box,
    not the pin, is what the field is spanned over) and sample the same
    bilinear field (``scatter_curves.terrain_height``). Both turns are the
    SAME formula (``world_geometry.world_to_local`` and ``scene-render``
    ``worldToLocalXZ``), which is what keeps the rule and the picture on one
    ground.
    """
    if not loc:
        return 0.0
    from app.core.scatter_curves import terrain_height
    from app.core.world_geometry import (effective_boundary,
                                         polygon_plan_width_m, world_to_local)
    eff = effective_boundary(loc)
    if eff is None:
        return 0.0
    cx, cz, yaw, pts = eff
    width = polygon_plan_width_m(pts)
    found = _terrain_of(loc, width)
    if not found:
        return 0.0
    grid, (tx0, tz0, tsize) = found
    lx, lz = world_to_local(x, z, cx, cz, yaw)
    return terrain_height(grid, (lx - tx0) / tsize, (lz - tz0) / tsize)


def has_relief(loc: Optional[Dict[str, Any]]) -> bool:
    """Does this location carry a height field of its own? An ``area_detail``
    location with a ``relief`` block and a real amplitude — the same three
    conditions ``compose_terrain`` composes on, so "has a relief" and "ships a
    terrain grid" cannot mean two different things."""
    map3d = (loc or {}).get("map3d") or {}
    relief = map3d.get("relief")
    if not isinstance(relief, dict) or not map3d.get("area_detail"):
        return False
    try:
        return float(relief.get("amplitude_m") or 0) > 0
    except (TypeError, ValueError):
        return False


def ground_lift_at(x: float, z: float,
                   locations: Sequence[Dict[str, Any]]) -> float:
    """Height of the ground at a WORLD point over the WHOLE world, metres.

    THE ONE HEIGHT SOURCE the rules ask. Not "the height of the location the
    point derives to": a place that carries NO relief of its own does not
    flatten the ground it stands on — it stands ON that ground. A hut placed on
    a village square whose relief rises 2 m would otherwise sit in a hole of
    its own making: the square answers 2 m, the hut answers 0, and the step
    between them is an artificial 63° cliff sealing an openingless hut from
    every side (review finding F3, 2026-08-13).

    So the answer is the INNERMOST ENCLOSING location that HAS a relief:
    the smallest AREA wins among those that do (contract v6, E1.2), the way
    ``location_at_point`` resolves nesting, and a location without one is
    simply transparent to the question.

    THE WORLD GROUND IS UNDER ALL OF IT (E8 task 2). ``ground_y`` is the
    authored world relief, and a scene's own field is a lift ON TOP of it: its
    border is pinned to 0, so a location standing on a hill rides up with the
    hill instead of cutting a flat shelf into it. Outside every scene relief
    the answer is the world ground alone, and in a world nobody has shaped it
    is 0.0 — the flat plate as before.
    """
    from app.core.world_geometry import (boundary_area_m2, boundary_contains,
                                         ground_y)
    best: Optional[Dict[str, Any]] = None
    best_area: Optional[float] = None
    for loc in locations or []:
        if not has_relief(loc):
            continue
        if not boundary_contains(loc, x, z):
            continue
        area = boundary_area_m2(loc)
        if best_area is None or area < best_area:
            best, best_area = loc, area
    return ground_y(x, z) + scene_ground_lift(best, x, z)
