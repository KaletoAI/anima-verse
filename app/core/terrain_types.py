"""Terrain-type catalog (Seamless World, E1).

Data-driven ground vocabulary for the painted terrain areas: what a kind
looks like on the schematic 2D map (color), whether it can be walked on,
how fast, and — since finding 3 of the E8 acceptance — HOW one moves over
it (``meta.move_anim``, the clip that replaces walk/run), how one WAITS
on it (``meta.idle_anim``, the clip that replaces the standing one) and how
DEEP one stands in it while doing either (``meta.move_sink_m`` /
``meta.idle_sink_m`` — two depths, because a swimmer lies flat and a treader
hangs upright, and the same drop cannot serve both). Since
2026-08-13 also how BUMPY it is (``meta.relief_amplitude_m`` /
``meta.relief_wave_m``, the micro-relief baked into the world heightfield,
§ A16), since 2026-08-14 how far what grows on it WAVES in the wind
(``meta.sway_m``, § A9) and, since 2026-08-15, how much grows there WITHOUT
anybody authoring it (``meta.undergrowth``, § A9). NO terrain
property is ever hardcoded anywhere else — every consumer (passability,
pace, relief, payload, editor palette) reads this catalog.

Two layers, override-replace per kind (the activity-library rule): the
shared seed ``shared/terrain/types.json`` ships the defaults, a world row
in ``terrain_types`` replaces the whole entry of the same kind. Deleting a
world row brings the shared entry back; shared entries are never deleted.

``kind`` follows the surface-texture id rule and SHOULD match a
surface-texture kind so the 3D ground can pick up a real texture — that
link is a convention, never enforced here.
"""

import json
import math
import re
from pathlib import Path
from typing import Any, Dict, Optional

from app.core.db import get_connection, transaction
from app.core.log import get_logger
from app.core.timeutils import utc_now_iso

logger = get_logger(__name__)

_KIND_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
SPEED_MIN, SPEED_MAX = 0.0, 2.0
DEFAULT_COLOR = "#888888"

#: MICRO-RELIEF (decision 2026-08-13) — how high the random small hills of
#: this ground stand, in metres, as a half-swing around the authored level
#: (the noise runs in [−1, 1)). The upper clamp is a WALKABILITY limit, not a
#: taste one: two neighbouring support points may differ by at most 2·amp over
#: one grid step, i.e. atan(2·2.0 / 2.0) = 63° at the maximum on the tile grid
#: the rules read (45° while that step was 4 m) — past that the ground would
#: build slopes nobody can climb out of the noise alone. The
#: lower clamp is the smallest swing that is still visible at all; anything
#: below it means "no relief", and that is written by leaving the key out.
RELIEF_AMPLITUDE_MIN, RELIEF_AMPLITUDE_MAX = 0.05, 2.0

#: How wide ONE swell of that relief is, in metres — the edge length of the
#: noise lattice. The lower clamp is 2 × ``heightfield.TILE_STEP_M``: NYQUIST.
#: A wave shorter than two support points cannot be carried by the grid at all,
#: it would only alias into a different, coarser pattern that changes whenever
#: the raster step doubles. It follows the TILE step, never the overview's —
#: the tiles are the raster every rule reads, and since they went to 2 m
#: (2026-08-14) a 4 m wave is something an author may ask for.
RELIEF_WAVE_MIN, RELIEF_WAVE_MAX = 4.0, 200.0

#: HOW DEEP A FIGURE STANDS IN THIS GROUND, in metres — the clamp shared by
#: the two depth keys. The clip ground normalisation puts the LOWEST body point
#: of a terrain clip on the surface — for a swimmer that is a bent knee, so the
#: body lies on the water instead of in it. This is the extra drop on top, and
#: it is a property of the GROUND, not of the clip: the same stroke sits deeper
#: in a lake than in a ford. The upper clamp is a body length and a half: past
#: that the figure is under the ground rather than in it, and nothing would be
#: visible to correct it by. Zero means "no sinking" and is written by leaving
#: the key out.
SINK_MIN, SINK_MAX = 0.0, 1.5

#: THE TWO DEPTHS, one per pose (finding 13, 2026-08-13): one number could not
#: serve both. A moving swimmer lies HORIZONTAL, and its lowest point is an
#: angled knee a hand's width under the body; a waiting one treads water
#: UPRIGHT, and its lowest point is a foot a whole body length down. Normalised
#: onto the same surface, the same extra drop puts one of them right and the
#: other in the wrong world — the swimmer submerged or the treader standing on
#: the lake. So the ground says both, and the renderer picks by what the figure
#: is doing (§ A9).
SINK_KEYS = ("move_sink_m", "idle_sink_m")

#: HOW FAR THE SCATTER OF THIS GROUND BENDS IN THE WIND, in metres — the
#: maximum sideways deflection of a blade's TIP (decision 2026-08-14). The
#: number hangs on the KIND, so all scatter of a swaying kind moves, tufts and
#: props alike; the area FILL never moves (only the water class animates
#: there). The lower clamp is the smallest swing that reads as motion at all at
#: eye level; the upper one is a hand's breadth and a half, past which grass
#: does not bend but shears — the deflection is quadratic in the height above
#: the ground, so the tip carries the whole of it while the base stands still.
#: Frequency and wind direction are fixed in the renderer, not authored.
SWAY_MIN, SWAY_MAX = 0.01, 0.5

#: HOW MUCH GROWS ON THIS GROUND ALL BY ITSELF, as a share of the renderer's
#: full undergrowth density (decision 2026-08-15). A wood only reads as a wood
#: when something stands BETWEEN the trunks, and asking an author to paint a
#: second scatter row of tufts on every wood is authoring work for something
#: the KIND already says: forest is undergrown, a path is not. So this is a
#: dial and not a list — 0…1, where 1 is the client's full base density
#: (``UNDERGROWTH_DENSITY_PER_M2``, 0.40 instances per square metre) and every
#: value in between scales it linearly. No key means "bare ground", which is
#: what every kind without it stays; there is no lower limit but 0 because the
#: layer thins out continuously and a very small share is simply a few blades.
#: The renderer owns everything else about it — where the tufts stand (the
#: shared seed-stable sampler), how tall they are and how far they are drawn.
#:
#: THE NUMBER IS A RATE PER SQUARE METRE AND NOTHING ELSE, and since 2026-08-16
#: the renderer really pays it everywhere: the layer is grown per 64 m CELL
#: around the camera anchor rather than per painted shape, so a square
#: kilometre of forest is locally exactly as dense as a small meadow. Under the
#: old per-shape build a ceiling of 20 000 instances had to cap huge areas,
#: which turned this dial into a lie on exactly the grounds that need it most
#: (0.6 over a square kilometre came out at 0.02/m²) — that is why the base
#: density could be raised from 0.15 to 0.40 at the same time. Contract detail
#: for the renderers: ``docs/schnittstellen-3d.md`` § A9.
UNDERGROWTH_MIN, UNDERGROWTH_MAX = 0.0, 1.0

#: The wave a kind with an amplitude but no authored wave gets — a swell every
#: 32 m, eight grid cells wide at the default step: the gentle rolling the
#: user asked for ("just to make random small hills"), not a choppy field.
DEFAULT_RELIEF_WAVE_M = 32.0


def _shared_path() -> Path:
    from app.core.paths import get_shared_dir
    return get_shared_dir() / "terrain" / "types.json"


def _shared_types() -> Dict[str, Dict[str, Any]]:
    try:
        raw = json.loads(_shared_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("shared terrain types unreadable — empty catalog base")
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for entry in (raw.get("types") or []):
        try:
            entry = sanitize_type(entry)
        except ValueError:
            continue
        out[entry["kind"]] = entry
    return out


def _finite(value: Any) -> Optional[float]:
    """``value`` as a finite float, or None — NaN/inf are junk, not numbers.

    They must never reach a clamp: every NaN comparison is False, so min/max
    hand them straight through and the un-encodable value poisons every later
    JSON response (Starlette encodes with ``allow_nan=False`` -> 500).
    """
    try:
        num = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return num if math.isfinite(num) else None


def _clamped_meta_number(meta: Dict[str, Any], key: str,
                         low: float, high: float) -> None:
    """One optional numeric ``meta`` key, IN PLACE — clamped or gone.

    The ``move_anim`` shape rule for numbers: a value that says nothing
    (absent, junk, zero, negative) leaves NO key behind, so no reader ever has
    to tell "authored as 0" from "not authored". Everything else is CLAMPED
    rather than refused — an authoring slip should move the ground to the
    limit, not lose the whole catalog entry — and rounded to two decimals,
    which is the precision the editor offers.

    A NUMBER THAT ROUNDS TO ZERO SAYS NOTHING EITHER (review 2026-08-13). Where
    the lower clamp is 0 — the sink depths — 0.004 survived the "> 0" test and
    then rounded to a stored 0.0, exactly the "authored as 0" the rule above is
    written to make impossible. The test belongs AFTER the rounding, because
    the rounding is what makes the value what it is.
    """
    num = _finite(meta.get(key))
    if num is None or num <= 0:
        meta.pop(key, None)
        return
    value = round(min(max(num, low), high), 2)
    if value <= 0:
        meta.pop(key, None)
        return
    meta[key] = value


def _trimmed_meta_string(meta: Dict[str, Any], key: str,
                         limit: int = 40) -> None:
    """One optional string ``meta`` key, IN PLACE — trimmed, capped or GONE.

    The shape rule of the animation keys: they name a clip KIND out of the
    open vocabulary of ``shared/models/clips``, so nothing is validated against
    a list; what is enforced is the shape (a trimmed string, ``limit``
    characters like a ``kind``) and that an empty one leaves no key behind —
    "no animation" must not be an empty string every reader has to test for.
    """
    if key not in meta:
        return
    value = str(meta.get(key) or "").strip()[:limit]
    if value:
        meta[key] = value
    else:
        meta.pop(key)


def sanitize_type(raw: Any) -> Dict[str, Any]:
    """Whitelist + coerce one catalog entry; raises ValueError on junk."""
    if not isinstance(raw, dict):
        raise ValueError("terrain type must be an object")
    kind = str(raw.get("kind") or "").strip()
    if not _KIND_RE.match(kind):
        raise ValueError(f"invalid terrain kind: {kind!r}")
    name = str(raw.get("name") or "").strip()[:60] or kind
    color = str(raw.get("color") or "").strip()
    if color and not _COLOR_RE.match(color):
        raise ValueError(f"invalid color for {kind}: {color!r}")
    try:
        speed = float(raw.get("speed_factor", 1.0))
    except (TypeError, ValueError):
        speed = 1.0
    # NaN/inf must never reach the clamp: every NaN comparison is False, so
    # min/max hand it straight through and the un-renderable value poisons
    # every later JSON response. Non-finite is junk — fall back to the default.
    if not math.isfinite(speed):
        speed = 1.0
    speed = min(max(speed, SPEED_MIN), SPEED_MAX)
    # `meta` is free-form and stays that way: a type declares how ground
    # LOOKS and how it is walked, nothing about what grows on it. Scatter used
    # to be whitelisted here and moved to the AREA with finding B17 — see
    # `app/models/terrain._sanitize_scatter_list`.
    meta = dict(raw.get("meta")) if isinstance(raw.get("meta"), dict) else {}
    # TWO keys inside it are whitelisted as CLIPS (§ A9): `move_anim`, what a
    # figure MOVING over this ground plays instead of walk/run (finding 3 of
    # the E8 acceptance — water is swum through), and since the water round of
    # 2026-08-13 `idle_anim`, what it plays STANDING there instead of its idle
    # (treading water instead of standing in the lake). Same shape rule for
    # both, `_trimmed_meta_string` — the kinds come out of an open vocabulary
    # and are never checked against a list.
    _trimmed_meta_string(meta, "move_anim")
    _trimmed_meta_string(meta, "idle_anim")
    # TWO MORE belong to the same picture (2026-08-13): `move_sink_m` and
    # `idle_sink_m`, how deep a figure stands in this ground while it MOVES
    # over it and while it WAITS on it. The clips are normalised onto the
    # surface, which is right for a walker and too high for a swimmer — the
    # ground says how much of the body belongs below it, once per pose, because
    # a horizontal swimmer and an upright treader do not share a depth
    # (finding 13). There is no third key averaging them: the renderer knows
    # which of the two clips is running.
    for _sink_key in SINK_KEYS:
        if _sink_key in meta:
            _clamped_meta_number(meta, _sink_key, SINK_MIN, SINK_MAX)
    # TWO MORE since the micro-relief decision (2026-08-13): the random small
    # hills this ground carries, baked into the WORLD HEIGHTFIELD by
    # ``app/core/heightfield`` (§ A16) rather than rendered by anyone — server
    # gates, client mirror and both renderers read the one ``heights`` array.
    # Only the two numbers live here; the formula and the seed do not (the
    # seed is a hash of the kind name, ``heightfield.relief_seed``).
    if "relief_amplitude_m" in meta:
        _clamped_meta_number(meta, "relief_amplitude_m",
                             RELIEF_AMPLITUDE_MIN, RELIEF_AMPLITUDE_MAX)
    if "relief_wave_m" in meta:
        _clamped_meta_number(meta, "relief_wave_m",
                             RELIEF_WAVE_MIN, RELIEF_WAVE_MAX)
    # AND ONE MORE since the terrain-animation decision (2026-08-14): how far
    # what GROWS on this ground bends in the wind. Same shape rule as every
    # other number here — no key means "stands still", which is what every
    # kind without it does. The renderer reads it off the AREA's kind, so a
    # meadow's tufts and its trees sway together or not at all.
    if "sway_m" in meta:
        _clamped_meta_number(meta, "sway_m", SWAY_MIN, SWAY_MAX)
    # AND ONE MORE since the undergrowth decision (2026-08-15): how much grows
    # on this ground without anybody authoring it. Same shape rule again — no
    # key means bare, which is what a value of 0 would have to mean anyway.
    # NOTHING about the layer itself is stored: this is the density DIAL, the
    # client owns the sampler, the height and the distances (§ A9).
    if "undergrowth" in meta:
        _clamped_meta_number(meta, "undergrowth",
                             UNDERGROWTH_MIN, UNDERGROWTH_MAX)
    return {
        "kind": kind,
        "name": name,
        "color": color or DEFAULT_COLOR,
        "passable": bool(raw.get("passable", True)),
        "speed_factor": round(speed, 2),
        "meta": meta,
    }


def _world_types() -> Dict[str, Dict[str, Any]]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT kind, name, color, passable, speed_factor, meta "
        "FROM terrain_types").fetchall()
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        try:
            meta = json.loads(r[5] or "{}")
        except ValueError:
            meta = {}
        out[r[0]] = {"kind": r[0], "name": r[1] or r[0],
                     "color": r[2] or DEFAULT_COLOR, "passable": bool(r[3]),
                     "speed_factor": float(r[4]),
                     "meta": meta if isinstance(meta, dict) else {}}
    return out


def effective_catalog() -> Dict[str, Dict[str, Any]]:
    """shared overlaid by world rows — override-replace per kind."""
    catalog = _shared_types()
    catalog.update(_world_types())
    return catalog


def sources() -> Dict[str, str]:
    """Where each effective kind comes from: ``"shared"`` or ``"world"``."""
    shared = set(_shared_types())
    world = set(_world_types())
    return {k: ("world" if k in world else "shared")
            for k in shared | world}


def get_type(kind: str) -> Optional[Dict[str, Any]]:
    """One effective entry, or None when the kind is unknown."""
    return effective_catalog().get((kind or "").strip())


def _note_relief_write() -> None:
    """A catalog write may have moved the WORLD HEIGHTFIELD — check, then act.

    Since the micro-relief (2026-08-13) a terrain KIND carries a height: its
    ``relief_amplitude_m``/``relief_wave_m`` are baked into the world grid
    wherever that kind is painted. So editing the catalog changes the ground
    itself, exactly as moving a height area does — and the same hook answers
    it: ``note_world_write`` compares the signature the cached field was built
    from against the current one and only pays for a raster when the answer
    really moved. A colour or a name change costs the comparison and nothing
    else.
    """
    from app.models.heightfield import note_world_write
    note_world_write()


def save_world_type(raw: Any) -> Dict[str, Any]:
    """Create/replace the WORLD override of one kind; returns the sanitized
    entry. Raises ValueError when the entry is not usable."""
    entry = sanitize_type(raw)
    with transaction() as conn:
        conn.execute(
            "INSERT INTO terrain_types (kind, name, color, passable, "
            "speed_factor, meta, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(kind) DO UPDATE SET name=excluded.name, "
            "color=excluded.color, passable=excluded.passable, "
            "speed_factor=excluded.speed_factor, meta=excluded.meta, "
            "updated_at=excluded.updated_at",
            (entry["kind"], entry["name"], entry["color"],
             1 if entry["passable"] else 0, entry["speed_factor"],
             json.dumps(entry["meta"], ensure_ascii=False), utc_now_iso()))
    _note_relief_write()
    return entry


def delete_world_type(kind: str) -> bool:
    """Drop the world override of one kind. A shared entry of the same kind
    stays untouched and becomes effective again."""
    with transaction() as conn:
        cur = conn.execute("DELETE FROM terrain_types WHERE kind=?",
                           ((kind or "").strip(),))
        deleted = cur.rowcount > 0
    if deleted:
        # The SHARED entry becomes effective again — including its relief, or
        # its lack of one. Dropping an override is a ground change like any
        # other.
        _note_relief_write()
    return deleted
