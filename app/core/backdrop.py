"""The FAR BACKDROP — the world-edge mountain ring, as world settings.

PURE OPTICS. The ring is a silhouette the 3D client draws around the camera;
it blocks nothing, carries no collision and never touches routing. What keeps
a walker out of the distance is painted impassable terrain, not this.

Three world settings author it (``game.backdrop_*``), and this module is the
only place that reads them — the ``relief.py`` getter pattern: missing,
unusable or out-of-range values fall back to the documented default, with ONE
warning per setting (the payload runs on a 3-second poll, a warning per read
would drown the log).

THE ARCS ARE RESOLVED HERE, not in the renderer (§ A17). The setting names
COMPASS SEGMENTS ("N", "N,NE,NW", empty = the full ring); the payload carries
finished degree ranges, so both a renderer and a future second one only sweep
what they are given. The degrees are this contract's own figure compass
(§ A1.8): **0 = South, 90 = East, 180 = North, 270 = West**, i.e. a direction
of ``(x, z) = (sin a, cos a)`` on the ground plane where x grows east and z
grows south. Each segment covers 45° centred on its direction, adjacent
segments merge into ONE arc, and an arc may run past 360 rather than wrap:
``[start, end]`` always has ``0 <= start < 360`` and ``start < end <= start +
360``, so the renderer sweeps increasing degrees and never needs a wrap case.
"""

import math
from typing import Any, Dict, List, Optional, Tuple

from app.core.log import get_logger

logger = get_logger("backdrop")

#: Height of the ridge line in world metres when ``game.backdrop_height_m`` is
#: missing or unusable — a mountain range seen from far away, not a wall.
DEFAULT_HEIGHT_M = 120.0
_MIN_HEIGHT_M = 20.0
_MAX_HEIGHT_M = 300.0

#: Seed of the procedural ridge profile when ``game.backdrop_seed`` is missing
#: or unusable. The profile is a pure function of it, so the same seed draws
#: the same mountains on every client, every reload.
DEFAULT_SEED = 1
_SEED_MODULO = 2 ** 32

#: Compass direction -> centre degree in the figure compass (0 = South,
#: 90 = East, 180 = North, 270 = West). The ring is walked in this order, so
#: index i of a selected slot covers ``[45i - 22.5, 45i + 22.5]``.
_SEGMENTS: Tuple[str, ...] = ("S", "SE", "E", "NE", "N", "NW", "W", "SW")
_SEGMENT_DEG = 360.0 / len(_SEGMENTS)          # 45°
_HALF_SEGMENT_DEG = _SEGMENT_DEG / 2.0         # 22.5°

_warned: Dict[str, bool] = {}


def _reject(setting: str, raw: Any, default: Any) -> Any:
    """Log a discarded world setting ONCE and return the default."""
    if not _warned.get(setting):
        _warned[setting] = True
        logger.warning("Unusable %s (%r) — using the default %s",
                       setting, raw, default)
    return default


def get_backdrop_enabled() -> bool:
    """Is the backdrop drawn at all (``game.backdrop_enabled``, default off)?

    Anything but a real boolean or a number reads as off — an unset world has
    no backdrop, and a typo must not conjure a mountain range.
    """
    from app.core import config
    raw = config.get("game.backdrop_enabled", False)
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return False
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return bool(raw)
    return bool(_reject("game.backdrop_enabled", raw, False))


def get_backdrop_height_m() -> float:
    """Ridge height in world metres from ``game.backdrop_height_m``.

    Clamped into [20, 300]: below 20 m the ring disappears into the fog band,
    above 300 m it stands over the sky rather than at the horizon. Zero counts
    as garbage on purpose — an emptied admin field arrives as 0, and a ring of
    height 0 is an enabled feature that draws nothing.
    """
    from app.core import config
    raw = config.get("game.backdrop_height_m", DEFAULT_HEIGHT_M)
    if raw is None:
        return DEFAULT_HEIGHT_M
    if isinstance(raw, bool):
        return _reject("game.backdrop_height_m", raw, DEFAULT_HEIGHT_M)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return _reject("game.backdrop_height_m", raw, DEFAULT_HEIGHT_M)
    if not math.isfinite(value) or value <= 0:
        return _reject("game.backdrop_height_m", raw, DEFAULT_HEIGHT_M)
    return min(max(value, _MIN_HEIGHT_M), _MAX_HEIGHT_M)


def get_backdrop_seed() -> int:
    """Seed of the ridge profile from ``game.backdrop_seed``, as a uint32.

    Whole numbers only (a fractional seed is a typo, not a choice); negatives
    and oversized values wrap into [0, 2³²) rather than being thrown away, so
    every accepted number names exactly one mountain range.
    """
    from app.core import config
    raw = config.get("game.backdrop_seed", DEFAULT_SEED)
    if raw is None:
        return DEFAULT_SEED
    if isinstance(raw, bool):
        return _reject("game.backdrop_seed", raw, DEFAULT_SEED)
    if isinstance(raw, float):
        if not math.isfinite(raw) or raw != int(raw):
            return _reject("game.backdrop_seed", raw, DEFAULT_SEED)
        raw = int(raw)
    if not isinstance(raw, int):
        try:
            raw = int(str(raw).strip())
        except (TypeError, ValueError):
            return _reject("game.backdrop_seed", raw, DEFAULT_SEED)
    return raw % _SEED_MODULO


def resolve_arcs(raw: Any) -> List[List[float]]:
    """Compass segments -> finished degree ranges (the renderer stays dumb).

    PURE — no config, no world. ``raw`` is the comma-separated setting; case
    and blanks do not matter, unknown words are dropped. EMPTY (or all-junk)
    means the FULL RING, which is the honest reading of "a backdrop is on but
    no direction was named".

    The compass is § A1.8's: 0 = South, 90 = East, 180 = North, 270 = West.
    Segment ``i`` of ``_SEGMENTS`` covers ``[45i - 22.5, 45i + 22.5]``,
    adjacent selected segments merge into one arc, and a run that crosses 0 is
    reported as ``start`` in [0, 360) with ``end`` past 360 instead of
    wrapping. The full ring is the single arc ``[0, 360]``.
    """
    words = [w.strip().upper() for w in str(raw or "").split(",")]
    selected = [w in words for w in _SEGMENTS]
    if not any(selected) or all(selected):
        return [[0.0, 360.0]]
    n = len(_SEGMENTS)
    arcs: List[List[float]] = []
    for i in range(n):
        # A run STARTS where a selected segment follows an unselected one.
        if not selected[i] or selected[i - 1]:
            continue
        length = 0
        while length < n and selected[(i + length) % n]:
            length += 1
        start = (i * _SEGMENT_DEG - _HALF_SEGMENT_DEG) % 360.0
        arcs.append([round(start, 6),
                     round(start + length * _SEGMENT_DEG, 6)])
    arcs.sort(key=lambda arc: arc[0])
    return arcs


def get_backdrop() -> Optional[Dict[str, Any]]:
    """The whole backdrop block for the worldmap payload, or ``None``.

    ``None`` when the feature is off — the payload then leaves the key out
    entirely, which is also what an older server sends, so "absent" and "off"
    are the same state for a client (the walk-limits ride-along pattern).
    """
    if not get_backdrop_enabled():
        return None
    from app.core import config
    return {
        "height_m": get_backdrop_height_m(),
        "seed": get_backdrop_seed(),
        "arcs": resolve_arcs(config.get("game.backdrop_arc", "")),
    }
