"""Painted terrain areas (Seamless World, E1).

A terrain area is one painted polygon on the free world map: a ``kind``
from the terrain-type catalog plus its outline in world metres. Areas may
overlap; ``z_order`` (then paint order) decides which one answers a point
query — the topmost wins, mirroring how the editor paints.

Everything is validated ON WRITE: the readers downstream
(``world_geometry.point_in_polygon``) fail closed on malformed vertices
without a word in the log, so junk must never reach the DB in the first
place.
"""

import hashlib
import json
import math
import secrets
from typing import Any, Dict, List

from app.core.db import get_connection, transaction
from app.core.timeutils import utc_now_iso

MAX_POINTS = 256
MAX_COORD = 100_000.0
MAX_Z_ORDER = 10_000


def _sanitize_polygon(raw: Any) -> List[List[float]]:
    if not isinstance(raw, list) or not 3 <= len(raw) <= MAX_POINTS:
        raise ValueError("polygon needs 3..256 points")
    pts: List[List[float]] = []
    for pt in raw:
        # A vertex may be any 2-element sequence of numbers. Everything else
        # is junk — including dicts, which raise KeyError on pt[0], and huge
        # integer literals (a JSON body may carry 400 digits), which raise
        # OverflowError. Both would otherwise escape as a 500 instead of a 400.
        try:
            x, z = float(pt[0]), float(pt[1])
        except (TypeError, ValueError, IndexError, KeyError, OverflowError):
            raise ValueError("polygon points must be [x, z] numbers")
        # isfinite first: every NaN comparison is False, so a plain range
        # check would wave NaN through and poison every later JSON response
        # (Starlette encodes with allow_nan=False -> 500).
        if not (math.isfinite(x) and math.isfinite(z)):
            raise ValueError("polygon coordinate must be a finite number")
        if abs(x) > MAX_COORD or abs(z) > MAX_COORD:
            raise ValueError("polygon coordinate out of range")
        pts.append([round(x, 2), round(z, 2)])
    return pts


def sanitize_area(raw: Any) -> Dict[str, Any]:
    """Whitelist + coerce one area; raises ValueError on junk."""
    from app.core.terrain_types import effective_catalog
    if not isinstance(raw, dict):
        raise ValueError("terrain area must be an object")
    kind = str(raw.get("kind") or "").strip()
    if kind not in effective_catalog():
        raise ValueError(f"unknown terrain kind: {kind!r}")
    area_id = str(raw.get("id") or "").strip() or f"ta_{secrets.token_hex(4)}"
    # OverflowError included: stdlib json accepts the `Infinity` literal, and
    # int(inf) raises it — that happens BEFORE the clamp below, so without the
    # catch the body would 500 instead of falling back to the default layer.
    try:
        z_order = int(raw.get("z_order") or 0)
    except (TypeError, ValueError, OverflowError):
        z_order = 0
    # Clamped so an absurd layer number cannot blow past SQLite's 64-bit
    # INTEGER on insert.
    z_order = min(max(z_order, -MAX_Z_ORDER), MAX_Z_ORDER)
    meta = raw.get("meta")
    return {"id": area_id, "kind": kind,
            "polygon": _sanitize_polygon(raw.get("polygon")),
            "z_order": z_order,
            "meta": meta if isinstance(meta, dict) else {}}


def list_areas() -> List[Dict[str, Any]]:
    """All areas bottom-to-top: z_order, then paint order (rowid = insert
    order, which an update keeps). The LAST entry is drawn on top."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, kind, polygon, z_order, meta FROM terrain_areas "
        "ORDER BY z_order ASC, created_at ASC, rowid ASC").fetchall()
    out = []
    for r in rows:
        try:
            polygon = json.loads(r[2])
            meta = json.loads(r[4] or "{}")
        except (TypeError, ValueError):
            continue
        out.append({"id": r[0], "kind": r[1], "polygon": polygon,
                    "z_order": int(r[3] or 0),
                    "meta": meta if isinstance(meta, dict) else {}})
    return out


def save_area(raw: Any) -> Dict[str, Any]:
    """Create (no ``id``) or replace (with ``id``) one area; returns the
    sanitized entry. Raises ValueError when the area is not usable."""
    area = sanitize_area(raw)
    now = utc_now_iso()
    with transaction() as conn:
        conn.execute(
            "INSERT INTO terrain_areas (id, kind, polygon, z_order, meta, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET kind=excluded.kind, "
            "polygon=excluded.polygon, z_order=excluded.z_order, "
            "meta=excluded.meta, updated_at=excluded.updated_at",
            (area["id"], area["kind"],
             json.dumps(area["polygon"], ensure_ascii=False), area["z_order"],
             json.dumps(area["meta"], ensure_ascii=False), now, now))
    return area


def delete_area(area_id: str) -> bool:
    """Remove one area; False when there was nothing to delete."""
    with transaction() as conn:
        cur = conn.execute("DELETE FROM terrain_areas WHERE id=?",
                           ((area_id or "").strip(),))
        deleted = cur.rowcount > 0
    return deleted


def terrain_sig() -> str:
    """10-char signature over areas + world type rows — bumps whenever the
    painted world changes, so polling clients know when to refetch."""
    from app.core.terrain_types import _world_types
    basis = json.dumps({"areas": list_areas(), "types": _world_types()},
                       sort_keys=True, default=str)
    return hashlib.md5(basis.encode()).hexdigest()[:10]
