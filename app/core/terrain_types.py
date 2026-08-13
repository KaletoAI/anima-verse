"""Terrain-type catalog (Seamless World, E1).

Data-driven ground vocabulary for the painted terrain areas: what a kind
looks like on the schematic 2D map (color), whether it can be walked on,
how fast, and — since finding 3 of the E8 acceptance — HOW one moves over
it (``meta.move_anim``, the clip that replaces walk/run) and how one WAITS
on it (``meta.idle_anim``, the clip that replaces the standing one). Since
2026-08-13 also how BUMPY it is (``meta.relief_amplitude_m`` /
``meta.relief_wave_m``, the micro-relief baked into the world heightfield,
§ A16). NO terrain
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
#: one grid step, i.e. atan(2·2.0 / 4.0) = 45° at the maximum — past that the
#: ground would build slopes nobody can climb out of the noise alone. The
#: lower clamp is the smallest swing that is still visible at all; anything
#: below it means "no relief", and that is written by leaving the key out.
RELIEF_AMPLITUDE_MIN, RELIEF_AMPLITUDE_MAX = 0.05, 2.0

#: How wide ONE swell of that relief is, in metres — the edge length of the
#: noise lattice. The lower clamp is 2 × ``heightfield.DEFAULT_STEP_M``:
#: NYQUIST. A wave shorter than two support points cannot be carried by the
#: grid at all, it would only alias into a different, coarser pattern that
#: changes whenever the raster step doubles.
RELIEF_WAVE_MIN, RELIEF_WAVE_MAX = 8.0, 200.0

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
    """
    num = _finite(meta.get(key))
    if num is None or num <= 0:
        meta.pop(key, None)
        return
    meta[key] = round(min(max(num, low), high), 2)


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
