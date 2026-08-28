"""Height relief of the walkable world — limits, sampler and the walk rule.

THE FIRST CONSUMER OF A HEIGHT (E8 task 1). Until then every height in this
world was a rendering detail: the scene payload lifted props and the renderers
draped the ground, but no RULE ever asked how high anything was. This module is
where the ground starts pushing back — a step too high and a slope too steep
stop a walker, on the ONE authored world relief (``world_geometry.ground_y``).

Three things live here, and they are deliberately separate:

* the two WORLD SETTINGS (``game.max_step_height_m`` / ``game.max_slope_deg``)
  with the validating getters every other world dial has;
* :func:`ground_at` — the height of the ground at a WORLD point. Since "Ein
  Boden" E5a it is ``ground_y`` and nothing else: the per-scene 17 x 17 relief
  and its ``scene_ground_lift`` sampler are deleted (user decision 1);
* :func:`slope_blocks` — the RULE as a pure predicate, so the client mirror
  (``client3d/src/game/walk.ts`` ``slopeBlocks``) and this side can be checked
  against the same hand-derived table.

The rule itself, in one sentence: the SLOPE limit (``max_slope_deg``) holds
over EVERY distance, and below a metre the STEP limit (``max_step_height_m``)
holds ON TOP of it. Two limits rather than one because a 1 m wall and a 1 m
rise over 20 m are not the same obstacle — the first is unclimbable at any
pace, the second is a gentle hill; and they hold together rather than
either/or because each one alone can be walked round (see
:func:`slope_blocks`). Both limits judge a CLIMB only — since 2026-08-28 a
descent always passes (user rule).
"""

import math
from typing import Any, Dict

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
        ``atan(dh / dist)`` exceeds ``max_slope_deg``;
      * BELOW ``STEP_DISTANCE_M`` the step limit holds on top of it — blocked
        when ``dh > max_step``, however gentle the angle would call it.

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

    DIRECTION DOES MATTER (user rule, 2026-08-28): ``dh`` is SIGNED — the
    ground under the target minus the ground under the point one stands on —
    and ONLY CLIMBING is judged. A descent (``dh <= 0``) always passes, however
    deep, because a figure walking downhill is doing the one thing bodies do
    without asking, and a gate that refuses it reads as the world holding the
    walker back for no visible reason. The price is named and accepted: a
    walker can go down somewhere it cannot come back up and be stranded there
    — until now the symmetric gate was what prevented exactly that. Level
    ground (``dh == 0``) is never blocked either, which also makes the whole
    gate inert in a world without relief.

    So the two limits above read on the RISE, and there is only a rise when
    ``dh > 0``.
    """
    rise = float(dh)
    if rise <= 0:
        return False
    dist = float(dist)
    return (dist < STEP_DISTANCE_M and rise > float(max_step)) \
        or math.degrees(math.atan2(rise, dist)) > float(max_slope_deg)


# ── The ground of the WORLD, and there is only one ──────────────────────

def ground_at(x: float, z: float) -> float:
    """Height of the ground at a WORLD point, in metres — ``h_final``.

    THE ONE HEIGHT SOURCE THE RULES ASK, and since "Ein Boden" E5a it is one
    line: ``world_geometry.ground_y``, i.e. the baked heightfield
    (``core.heightfield.world_height``).

    WHAT WAS HERE BEFORE, and why it is gone. A location used to carry a SECOND
    height field of its own — a 17 x 17 procedural relief composed per scene
    (``scene_recipe.compose_terrain``), sampled by ``scene_ground_lift`` and
    ADDED to the world ground here. That was the second of the two grounds the
    plan was written against: it existed only inside a location's own frame, the
    world relief knew nothing about it, and the resolution rule it needed
    ("the innermost ENCLOSING location that HAS a relief wins") was a whole
    containment search on the walk-report path. User decision 1 of
    plan-ein-boden.md § 5 struck it: local relief is authored as HEIGHT AREAS of
    the map, which is the field this function reads.

    Kept as a named function rather than inlined at the call sites: it is the
    RULE side of the height, and the walking gate, the router and the smokes all
    say "the ground under this point" rather than naming a module.
    """
    from app.core.world_geometry import ground_y
    return ground_y(x, z)
