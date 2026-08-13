"""Painted terrain areas (Seamless World, E1).

A terrain area is one painted polygon on the free world map: a ``kind``
from the terrain-type catalog plus its outline in world metres. Areas may
overlap; ``z_order`` (then paint order) decides which one answers a point
query — the topmost wins, mirroring how the editor paints.

An area also declares what GROWS on it: ``meta.scatter`` is a LIST of prop
scatters (model, density, target height), authored per area since finding
B17 — a forest with two kinds of tree and a clearing without any is one
painted shape each, and a terrain TYPE cannot say that.

Since 2026-08-13 a painted area may also shape the GROUND ITSELF: if its kind
carries a micro-relief in the type catalog, the world heightfield gets that
kind's random small hills wherever the area lies (§ A16.2) — which is why the
writers here ring ``models.heightfield.note_world_write``.

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
#: Scatter entries one area may carry. What GROWS on a painted area is
#: authored per area since finding B17 — several props on one meadow are the
#: point of the move, an unbounded list is a payload every client parses.
MAX_SCATTER_ENTRIES = 8
#: Longest ``model`` URL a scatter entry may name. Truncating one would only
#: produce a 404 that looks like a configured model.
MODEL_URL_MAX = 300


def _finite(value: Any) -> Any:
    """``value`` as a finite float, or None — NaN/inf are junk, not numbers."""
    try:
        num = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return num if math.isfinite(num) else None


def _sanitize_scatter_entry(raw: Any) -> Dict[str, Any]:
    """One entry of ``meta.scatter``, whitelisted to EXACTLY the three fields
    the renderers read (``packages/scene-render/src/scatter.ts`` and the
    editor's preview + area dialog).

    * ``density_per_100m2`` — instances per 100 m2 of the painted area. Always
      present: a junk, negative or absent density means "scatter nothing"
      (0.0), which is how both renderers read it.
    * ``height_m`` — TARGET height of the placed prop in metres: the model is
      scaled uniformly until its bounding box is this tall, and the built-in
      tuft is built this high. Only a value > 0 is a height; anything else
      loses the key, and then the RENDERER's default applies (2 m for a model,
      0.8 m for the tuft) — never the model's authored size, which says
      nothing in a world measured in metres.
    * ``model`` — URL of the prop mesh to instance (``/assets/props/<id>/model``,
      the very URL ``props.model_url`` hands out). A non-string, blank or
      over-long value loses the key and the tuft stands in its place.

    Raises ValueError when the entry is not an object at all — a list of junk
    is an authoring mistake worth a 400, not something to silently drop.
    """
    if not isinstance(raw, dict):
        raise ValueError("scatter entry must be an object")
    density = _finite(raw.get("density_per_100m2"))
    out: Dict[str, Any] = {
        "density_per_100m2": round(density, 3) if density and density > 0 else 0.0,
    }
    height = _finite(raw.get("height_m"))
    if height is not None and height > 0:
        out["height_m"] = round(height, 3)
    model = raw.get("model")
    if isinstance(model, str) and model.strip():
        url = model.strip()
        if len(url) <= MODEL_URL_MAX:
            out["model"] = url
    return out


def _sanitize_scatter_list(raw: Any) -> List[Dict[str, Any]]:
    """``meta.scatter`` as a whitelisted LIST — what this ground grows.

    The rest of ``meta`` stays free-form: a foreign key next to ``scatter``
    survives untouched. ``scatter`` does not, because it is a rendering
    contract — a stray key or a NaN density would travel from the editor to
    every client.

    Anything that is not a list at all raises: the field moved from the
    terrain TYPE to the area with finding B17 and it moved as a LIST, so a
    single object here is an old client, not an entry to be guessed at.
    """
    if not isinstance(raw, list):
        raise ValueError("meta.scatter must be a list of entries")
    if len(raw) > MAX_SCATTER_ENTRIES:
        raise ValueError(f"at most {MAX_SCATTER_ENTRIES} scatter entries")
    return [_sanitize_scatter_entry(entry) for entry in raw]


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
    meta = dict(raw.get("meta")) if isinstance(raw.get("meta"), dict) else {}
    # The ONE key of `meta` this module owns (finding B17). An empty list is
    # not "no scatter authored" but "authored to nothing", and it costs one
    # pair of brackets — so it is kept as sent rather than dropped.
    if "scatter" in meta:
        meta["scatter"] = _sanitize_scatter_list(meta["scatter"])
    return {"id": area_id, "kind": kind,
            "polygon": _sanitize_polygon(raw.get("polygon")),
            "z_order": z_order,
            "meta": meta}


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


def area_exists(area_id: str) -> bool:
    """True when an area with this id is stored.

    ``save_area`` is an upsert, so the PUT route needs this ONE cheap lookup
    to answer 404 instead of resurrecting a just-deleted area under its old id.
    """
    area_id = (area_id or "").strip()
    if not area_id:
        return False
    conn = get_connection()
    row = conn.execute("SELECT 1 FROM terrain_areas WHERE id=?",
                       (area_id,)).fetchone()
    return row is not None


def _note_relief_write() -> None:
    """A painted area may have moved the WORLD HEIGHTFIELD — check, then act.

    Since the micro-relief (decision 2026-08-13) a terrain KIND can carry
    random small hills, and they are baked into the world grid wherever that
    kind is painted (``app/core/heightfield``, § A16.2). So painting is an
    authoring act on the RELIEF too, and the same hook that answers a moved
    location answers it: ``note_world_write`` compares the signature of the
    cached field against the current one and only pays for a raster when the
    ground really moved. Painting a kind without relief — the normal case —
    costs that comparison and nothing more.
    """
    from app.models.heightfield import note_world_write
    note_world_write()


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
    _note_relief_write()
    return area


def delete_area(area_id: str) -> bool:
    """Remove one area; False when there was nothing to delete."""
    with transaction() as conn:
        cur = conn.execute("DELETE FROM terrain_areas WHERE id=?",
                           ((area_id or "").strip(),))
        deleted = cur.rowcount > 0
    if deleted:
        _note_relief_write()
    return deleted


def terrain_sig() -> str:
    """10-char signature over areas + the EFFECTIVE type catalog — bumps
    whenever the painted world changes, so polling clients know when to
    refetch (and the nav-grid cache key inherits it).

    The effective catalog, not the world rows alone (round 2 of the E8
    acceptance): the shared seed ``shared/terrain/types.json`` is half the
    answer every consumer gets, so a seed edit that changes a passability, a
    speed factor or a ``move_anim`` has to reach a running client and a
    running router the same way a world row does. It used to sit outside the
    signature, which meant a seed change was invisible until a restart while
    ``GET /play/terrain`` already served the new numbers under the old
    ``sig``.
    """
    from app.core.terrain_types import effective_catalog
    basis = json.dumps({"areas": list_areas(), "types": effective_catalog()},
                       sort_keys=True, default=str)
    return hashlib.md5(basis.encode()).hexdigest()[:10]
