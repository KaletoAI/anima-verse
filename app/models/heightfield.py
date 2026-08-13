"""Authored height areas and the rastered world grid (Relief, E8 task 2).

The world relief has TWO shapes, and only one of them is authored.

* A **height area** is what a person draws: a polygon in world metres plus
  ``height_m`` (how high the ground stands inside it) and ``falloff_m`` (over
  how many metres it climbs there from the surrounding level). It is the
  source of truth and the only thing the editor writes.
* The **grid** (``world_heightfield``) is derived from those areas by
  :mod:`app.core.heightfield` and is a cache, never an authoring surface. It
  is stored rather than recomputed per process because rastering a world-sized
  field costs cell × edge work that no walk report may pay.

This module owns the DB side of both. Everything is validated ON WRITE, the
``terrain`` rule: the readers downstream fail closed on malformed vertices
without a word in the log, so junk must never reach the DB in the first place.

There is no ``kind`` and no ``z_order`` here on purpose. Heights are not
terrain: the ground under a painted meadow may rise, and which of two
overlapping height areas wins is not a layer decision but an arithmetic one
(the STRONGEST deflection from the flat world, see
``app/core/heightfield.rasterize``).
"""

import hashlib
import json
import math
import secrets
from typing import Any, Dict, List, Optional, Tuple

from app.core.db import get_connection, transaction
from app.core.timeutils import utc_now_iso

#: Outline limits — the same ones a painted terrain area has
#: (``app/models/terrain.py``), because both are polygons in world metres that
#: every renderer parses.
MAX_POINTS = 256
MAX_COORD = 100_000.0

#: How far the ground may leave the flat world, in metres, in either
#: direction. It is a RENDERING limit as much as an authoring one: the 3D
#: client raycasts its tiles from a fixed height above the plate, and a
#: mountain taller than that start height would be invisible to the ray.
MAX_HEIGHT_M = 50.0

#: Longest ramp an area may declare. A falloff wider than the area itself
#: simply never reaches the full height — that is legal (a gentle dome), so
#: this is only a sanity cap against a number that would swamp the raster.
MAX_FALLOFF_M = 1_000.0


def _finite(value: Any) -> Optional[float]:
    """``value`` as a finite float, or None — NaN/inf are junk, not numbers."""
    try:
        num = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return num if math.isfinite(num) else None


def _sanitize_polygon(raw: Any) -> List[List[float]]:
    """The outline, 3..256 finite ``[x, z]`` points on the 2-decimal metre
    grid. Identical rules to a terrain area's polygon — same reasons, listed
    in ``app/models/terrain._sanitize_polygon``."""
    if not isinstance(raw, list) or not 3 <= len(raw) <= MAX_POINTS:
        raise ValueError("polygon needs 3..256 points")
    pts: List[List[float]] = []
    for pt in raw:
        try:
            x, z = float(pt[0]), float(pt[1])
        except (TypeError, ValueError, IndexError, KeyError, OverflowError):
            raise ValueError("polygon points must be [x, z] numbers")
        # isfinite FIRST: every NaN comparison is False, so a plain range check
        # would wave NaN through and poison every later JSON response
        # (Starlette encodes with allow_nan=False -> 500).
        if not (math.isfinite(x) and math.isfinite(z)):
            raise ValueError("polygon coordinate must be a finite number")
        if abs(x) > MAX_COORD or abs(z) > MAX_COORD:
            raise ValueError("polygon coordinate out of range")
        pts.append([round(x, 2), round(z, 2)])
    return pts


def sanitize_height_area(raw: Any) -> Dict[str, Any]:
    """Whitelist + coerce one height area; raises ValueError on junk.

    ``height_m`` is CLAMPED rather than refused (an authoring slip should move
    the ground to the limit, not lose the shape someone drew), negative values
    are legal — that is a hollow, not a mistake — and a missing or unreadable
    number is 0.0, a flat area that changes nothing.

    ``falloff_m`` is a WIDTH and can only be positive; 0 means "no ramp at
    all", a wall at the outline. That is allowed and the editor warns about it,
    because a wall no walker can climb is a legitimate thing to build (a
    plateau reached through an opening) and an accident otherwise.
    """
    if not isinstance(raw, dict):
        raise ValueError("height area must be an object")
    area_id = str(raw.get("id") or "").strip() or f"ha_{secrets.token_hex(4)}"
    height = _finite(raw.get("height_m")) or 0.0
    height = min(max(height, -MAX_HEIGHT_M), MAX_HEIGHT_M)
    falloff = _finite(raw.get("falloff_m")) or 0.0
    falloff = min(max(falloff, 0.0), MAX_FALLOFF_M)
    meta = dict(raw.get("meta")) if isinstance(raw.get("meta"), dict) else {}
    return {"id": area_id,
            "polygon": _sanitize_polygon(raw.get("polygon")),
            "height_m": round(height, 3),
            "falloff_m": round(falloff, 3),
            "meta": meta}


def list_height_areas() -> List[Dict[str, Any]]:
    """All height areas in a STABLE order (insert order). The order carries no
    meaning for the result — the raster resolves overlaps by value, not by
    layer — it only has to be reproducible, or the signature would flap."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, polygon, height_m, falloff_m, meta FROM height_areas "
        "ORDER BY created_at ASC, rowid ASC").fetchall()
    out: List[Dict[str, Any]] = []
    for r in rows:
        try:
            polygon = json.loads(r[1])
            meta = json.loads(r[4] or "{}")
        except (TypeError, ValueError):
            continue
        out.append({"id": r[0], "polygon": polygon,
                    "height_m": float(r[2] or 0.0),
                    "falloff_m": float(r[3] or 0.0),
                    "meta": meta if isinstance(meta, dict) else {}})
    return out


def height_area_exists(area_id: str) -> bool:
    """True when an area with this id is stored — the PUT route's ONE lookup,
    so a stale write answers 404 instead of resurrecting a deleted area."""
    area_id = (area_id or "").strip()
    if not area_id:
        return False
    conn = get_connection()
    return conn.execute("SELECT 1 FROM height_areas WHERE id=?",
                        (area_id,)).fetchone() is not None


def save_height_area(raw: Any) -> Dict[str, Any]:
    """Create (no ``id``) or replace (with ``id``) one height area; returns the
    sanitized entry. Raises ValueError when it is not usable."""
    area = sanitize_height_area(raw)
    now = utc_now_iso()
    with transaction() as conn:
        conn.execute(
            "INSERT INTO height_areas (id, polygon, height_m, falloff_m, "
            "meta, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET polygon=excluded.polygon, "
            "height_m=excluded.height_m, falloff_m=excluded.falloff_m, "
            "meta=excluded.meta, updated_at=excluded.updated_at",
            (area["id"], json.dumps(area["polygon"], ensure_ascii=False),
             area["height_m"], area["falloff_m"],
             json.dumps(area["meta"], ensure_ascii=False), now, now))
    _invalidate()
    return area


def delete_height_area(area_id: str) -> bool:
    """Remove one height area; False when there was nothing to delete."""
    with transaction() as conn:
        cur = conn.execute("DELETE FROM height_areas WHERE id=?",
                           ((area_id or "").strip(),))
        deleted = cur.rowcount > 0
    if deleted:
        _invalidate()
    return deleted


def _invalidate() -> None:
    """Every write drops the rastered field this process holds.

    HERE and not in the routes: ``ground_y`` is asked on every walk report and
    in every routing loop, so the sampler may not re-hash the areas per call —
    which makes a forgotten invalidation a silently stale world. One writer,
    one place. The nav grid is dropped along with it: its cells carry terrain
    AND (from E8) the ground under them.
    """
    from app.core.heightfield import invalidate_cache
    from app.core.nav_grid import invalidate_nav_cache
    invalidate_cache()
    invalidate_nav_cache()


def height_sig() -> str:
    """10-char signature over the authored height areas.

    The refetch trigger of every client (worldmap ``height_sig``) AND the
    validity token of the stored raster: the grid row carries the signature it
    was built from, so "the areas changed" and "the grid is stale" are the same
    question asked once.
    """
    basis = json.dumps({"areas": list_height_areas()}, sort_keys=True,
                       default=str)
    return hashlib.md5(basis.encode()).hexdigest()[:10]


# ── The derived raster ───────────────────────────────────────────────────

def load_grid() -> Optional[Dict[str, Any]]:
    """The stored raster, or None when there is none / it is unreadable.

    An unreadable row is treated exactly like a missing one: the grid is a
    derived cache, and the areas it comes from are still there.
    """
    conn = get_connection()
    row = conn.execute(
        "SELECT origin_x, origin_z, step_m, n_rows, n_cols, heights, sig "
        "FROM world_heightfield WHERE id=1").fetchone()
    if row is None:
        return None
    try:
        heights = json.loads(row[5])
    except (TypeError, ValueError):
        return None
    if not isinstance(heights, list):
        return None
    return {"origin_x": float(row[0]), "origin_z": float(row[1]),
            "step_m": float(row[2]), "rows": int(row[3]),
            "cols": int(row[4]), "heights": heights, "sig": str(row[6] or "")}


def store_grid(field: Dict[str, Any]) -> None:
    """Persist the rastered grid (one row, id = 1)."""
    with transaction() as conn:
        conn.execute(
            "INSERT INTO world_heightfield (id, origin_x, origin_z, step_m, "
            "n_rows, n_cols, heights, sig, updated_at) "
            "VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET origin_x=excluded.origin_x, "
            "origin_z=excluded.origin_z, step_m=excluded.step_m, "
            "n_rows=excluded.n_rows, n_cols=excluded.n_cols, "
            "heights=excluded.heights, sig=excluded.sig, "
            "updated_at=excluded.updated_at",
            (field["origin_x"], field["origin_z"], field["step_m"],
             field["rows"], field["cols"],
             json.dumps(field["heights"], ensure_ascii=False),
             field["sig"], utc_now_iso()))


def polygon_bounds(polygon: Any) -> Optional[Tuple[float, float, float, float]]:
    """(min_x, min_z, max_x, max_z) over an outline, or None when it has no
    usable points. Unreadable vertices are skipped, never counted — the same
    rule ``world_bounds`` follows."""
    xs: List[float] = []
    zs: List[float] = []
    for pt in (polygon or []):
        try:
            x, z = float(pt[0]), float(pt[1])
        except (TypeError, ValueError, IndexError, KeyError, OverflowError):
            continue
        if not (math.isfinite(x) and math.isfinite(z)):
            continue
        xs.append(x)
        zs.append(z)
    if not xs:
        return None
    return (min(xs), min(zs), max(xs), max(zs))
