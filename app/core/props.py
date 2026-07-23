"""Prop library — single 3D objects (chair, table, plant, …) for room furnishing.

Plan: ``development_instructions/plan-room-props.md``. Unlike the room-diorama
models (``location_model3d.py``), a prop is ONE isolated object generated from a
dedicated product-shot render (use case ``prop``) → img2mesh (rig "none"). Each
prop carries OBJECT-LOCAL animation markers — a figure with a matching activity
snaps to the marker in the object's own space, so markers live on the OBJECT
instead of being set per room.

Storage: ``worlds/<world>/props/<prop_id>/``:

    model.glb     — the mesh (unrigged GLB, embedded texture)
    source.png    — the product-shot render the mesh was made from
    sidecar.json  — {name, category, width_m, depth_m, height_m,
                     dims_estimated, rotation{x,y,z}, tags[], markers[],
                     bbox[3], created_at, source, backend, prompt}

``prop_id`` = slug of the name + a short hash (stable, file-safe).

REAL SIZE. The mesh normalization destroys the real scale (the height_m /
width_m lesson), so the object's real extent is stored explicitly in metres —
as THREE dims after the orientation fix: ``width_m`` (x), ``height_m`` (y),
``depth_m`` (z), each in (0, 100]. ``dims_estimated`` marks a placeholder
cube that the model's proportions have not informed yet: it is True on
creation, and False as soon as a dim is edited or the mesh arrives and the
dims are redistributed over its proportions (largest edge kept).

``bbox`` = ``[bx, by, bz]``, the AABB edge lengths of model.glb in MESH units
on the RAW mesh axes (before the orientation fix), rounded to 5 decimals. It
is measured once when the model arrives (generation or upload) and lazily
backfilled for older props on the first listing; together with ``rotation``
it is what turns one real-world size into proportional dims
(``oriented_dims`` / ``_dims_from_size``).

``markers[].at`` is an OBJECT-LOCAL ``[u, v, w]`` (fractions of the model
bounding box, which MAY exceed 0..1 by half a box for seats and poses that
sit on or outside the hull — range ``[-0.5, 1.5]``); the vocabulary is
identical to ``layout.markers`` (animation + facing), only the frame is the
object instead of the room rectangle.
"""

import hashlib
import json
import math
import os
import random
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.log import get_logger
from app.core.model_validate import glb_bounds
from app.core.timeutils import utc_now_iso

logger = get_logger(__name__)

MODEL_NAME = "model.glb"
SOURCE_NAME = "source.png"
SIDECAR_NAME = "sidecar.json"

DEFAULT_DIM_M = 1.0
DIM_KEYS = ("width_m", "depth_m", "height_m")

# Marker fractions may leave the raw bounding box by half a box per axis —
# the HEIGHT axis reaches a full box below (deep seats in tall machines);
# see ``sanitize_markers``.
MARKER_AT_MIN = -0.5
MARKER_AT_MAX = 1.5
MARKER_AT_Y_MIN = -1.0

_PROP_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_SLUG_RE = re.compile(r"[^a-z0-9]+")

_lock = threading.Lock()
# Running generation job keys "<prop_id>|<backend glob>" (see A2 generation
# chain) — a prop may be regenerated on a DIFFERENT backend concurrently (each
# serializes on its own GPU channel); only the same prop+backend double-click
# is rejected.
_generating: set = set()
# Models whose bbox extraction already failed, keyed by (prop_id, model mtime)
# — keeps the lazy backfill from re-parsing an unmeasurable GLB on every
# listing. A restart or a re-upload retries.
_bbox_failed: set = set()


# ── Directories / id helpers ────────────────────────────────────────────

def _props_dir(*, create: bool = False) -> Path:
    from app.core.paths import get_storage_dir
    d = get_storage_dir() / "props"
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def safe_prop_id(prop_id: str) -> str:
    """Normalized prop id ('' = invalid) — lowercase, url/file-safe, no escapes."""
    prop_id = (prop_id or "").strip().lower()
    return prop_id if _PROP_ID_RE.match(prop_id) else ""


def _prop_dir(prop_id: str, *, create: bool = False) -> Optional[Path]:
    """``props/<prop_id>`` — created only on write paths (a read must not
    conjure a ghost directory). None for an invalid id."""
    pid = safe_prop_id(prop_id)
    if not pid:
        return None
    d = _props_dir() / pid
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def _slugify(name: str) -> str:
    slug = _SLUG_RE.sub("-", (name or "").strip().lower()).strip("-")
    return slug[:40] or "prop"


def _new_prop_id(name: str) -> str:
    """slug(name) + short hash; bumps the hash on the (very unlikely) collision."""
    slug = _slugify(name)
    n = 0
    while True:
        seed = f"{slug}:{time.time()}:{n}"
        pid = f"{slug}-{hashlib.md5(seed.encode()).hexdigest()[:6]}"
        if not (_props_dir() / pid).exists():
            return pid
        n += 1


# ── Sidecar read / write ────────────────────────────────────────────────

def _sidecar_path(prop_id: str) -> Optional[Path]:
    d = _prop_dir(prop_id)
    return (d / SIDECAR_NAME) if d else None


def read_sidecar(prop_id: str) -> Dict[str, Any]:
    sp = _sidecar_path(prop_id)
    if sp and sp.exists():
        try:
            meta = json.loads(sp.read_text(encoding="utf-8"))
            if isinstance(meta, dict):
                return meta
        except (OSError, ValueError):
            pass
    return {}


def _write_sidecar(prop_id: str, meta: Dict[str, Any]) -> None:
    d = _prop_dir(prop_id, create=True)
    if not d:
        raise ValueError("bad prop id")
    (d / SIDECAR_NAME).write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


# ── Field coercion ──────────────────────────────────────────────────────

def _coerce_dim_m(value: Any, fallback: float = DEFAULT_DIM_M) -> float:
    """One real edge in metres — mandatory > 0; clamped to (0, 100], round 3."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return fallback
    if v <= 0:
        return fallback
    return round(min(v, 100.0), 3)


def oriented_dims(bbox: Any, rotation: Any = None) -> List[float]:
    """``[width, height, depth]`` = the AABB extents of the raw mesh box AFTER
    the orientation fix: the 8 corners are rotated by Rx·Ry·Rz (degrees,
    three.js 'XYZ' Euler order) and re-measured. Empty list when the box is
    unusable.

    Rotating an AABB overestimates for non-90° fixes (it measures a box around
    the box), which is fine and deterministic — the numbers are used as
    PROPORTIONS, not as a hull. Kept in lockstep with
    ``frontend/src/tabs/props/dims.ts`` (``orientedDims``) — change both or
    neither.
    """
    try:
        b = [abs(float(bbox[i])) for i in range(3)]
    except (TypeError, ValueError, IndexError, KeyError):
        return []
    if max(b) <= 0:
        return []
    rot = rotation if isinstance(rotation, dict) else {}
    try:
        rx = math.radians(float(rot.get("x") or 0))
        ry = math.radians(float(rot.get("y") or 0))
        rz = math.radians(float(rot.get("z") or 0))
    except (TypeError, ValueError):
        rx = ry = rz = 0.0
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    # M = Rx · Ry · Rz
    m = [
        [cy * cz, -cy * sz, sy],
        [cx * sz + sx * sy * cz, cx * cz - sx * sy * sz, -sx * cy],
        [sx * sz - cx * sy * cz, sx * cz + cx * sy * sz, cx * cy],
    ]
    half = [v / 2 for v in b]
    lo = [math.inf] * 3
    hi = [-math.inf] * 3
    for i in (-1, 1):
        for j in (-1, 1):
            for k in (-1, 1):
                p = (i * half[0], j * half[1], k * half[2])
                for r in range(3):
                    v = m[r][0] * p[0] + m[r][1] * p[1] + m[r][2] * p[2]
                    lo[r] = min(lo[r], v)
                    hi[r] = max(hi[r], v)
    return [round(hi[r] - lo[r], 5) for r in range(3)]


def _dims_from_size(size_m: Any, bbox: Any = None,
                    rotation: Any = None) -> Dict[str, float]:
    """Spread ONE real size (the largest edge in metres) over the three dims
    using the model's proportions. Without a bbox every dim becomes that size
    (a placeholder cube). ESTIMATES round to 2 decimals — centimetres are
    plenty for furniture, longer tails just look like precision that is not
    there (admin-typed values keep the 3-decimal coercion)."""
    size = _coerce_dim_m(size_m, DEFAULT_DIM_M)
    od = oriented_dims(bbox, rotation) if bbox else []
    if od and max(od) > 0:
        f = size / max(od)
        return {"width_m": max(round(od[0] * f, 2), 0.01),
                "height_m": max(round(od[1] * f, 2), 0.01),
                "depth_m": max(round(od[2] * f, 2), 0.01)}
    return {"width_m": size, "depth_m": size, "height_m": size}


def _has_dims(meta: Dict[str, Any]) -> bool:
    """True when all three dims are stored and usable."""
    for key in DIM_KEYS:
        try:
            if float(meta.get(key)) <= 0:
                return False
        except (TypeError, ValueError):
            return False
    return True


def _effective_dims(meta: Dict[str, Any]) -> Dict[str, float]:
    """The dims to report: the stored ones, or — for a sidecar still carrying
    the legacy single ``size_m`` — derived in memory (not persisted here;
    ``_materialize_dims`` does that on the next write)."""
    if _has_dims(meta):
        return {key: _coerce_dim_m(meta.get(key)) for key in DIM_KEYS}
    return _dims_from_size(meta.get("size_m", DEFAULT_DIM_M),
                           meta.get("bbox"), meta.get("rotation"))


def _coerce_tags(raw: Any) -> List[str]:
    """Free-text tags — accepts a list or a comma/newline string; deduped
    case-insensitively, capped at 30."""
    if isinstance(raw, str):
        raw = re.split(r"[,\n]", raw)
    if not isinstance(raw, (list, tuple)):
        return []
    seen: set = set()
    out: List[str] = []
    for t in raw:
        t = str(t or "").strip()
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out[:30]


def _sanitize_rotation(raw: Any, cur: Optional[Dict[str, Any]] = None) -> Dict[str, float]:
    """Orientation fix {x,y,z} in degrees — FREE values, 0.1° resolution
    (meshes come out slightly tilted, not just axis-swapped; pattern
    ``location_model3d.set_rotation``). Whole numbers stay ints (no 90.0 noise)."""
    cur = cur if isinstance(cur, dict) else {}
    src = raw if isinstance(raw, dict) else {}
    rot: Dict[str, float] = {}
    for axis in ("x", "y", "z"):
        try:
            v = float(src.get(axis, cur.get(axis, 0)) or 0)
        except (TypeError, ValueError):
            try:
                v = float(cur.get(axis, 0) or 0)
            except (TypeError, ValueError):
                v = 0.0
        v = round(v % 360, 1)
        rot[axis] = int(v) if float(v).is_integer() else v
    return rot


def sanitize_markers(raw: Any) -> List[Dict[str, Any]]:
    """Object-local animation markers (A4). Same vocabulary as
    ``layout.markers`` — ``animation`` = a clip kind from the OPEN clip
    vocabulary, ``facing`` = degrees (0 south / 90 east / 180 north / 270 west,
    absent = client default) — but ``at`` is an OBJECT-LOCAL ``[u, v, w]``
    (three fractions of the model bounding box) instead of a room ``[x, y]``.

    The fractions may exceed 0..1 by half a box in each direction
    (``[-0.5, 1.5]``): a seat or lying surface often sits ON the hull edge or
    slightly outside it, and the old hard 0..1 clamp made those markers
    impossible to place (the Seated Row Machine finding). ``compose_prop_marker``
    multiplies the fractions linearly, so out-of-range values compose
    correctly without any change there.

    Invalid entries are dropped individually; capped at 50."""
    if not isinstance(raw, list):
        return []
    out: List[Dict[str, Any]] = []
    for m in raw:
        if not isinstance(m, dict):
            continue
        anim = str(m.get("animation") or "").strip()
        at = m.get("at")
        if not anim or not isinstance(at, (list, tuple)) or len(at) != 3:
            continue
        try:
            at3 = [round(min(max(float(at[i]),
                                 MARKER_AT_Y_MIN if i == 1 else MARKER_AT_MIN),
                             MARKER_AT_MAX), 4)
                   for i in range(3)]
        except (TypeError, ValueError):
            continue
        entry: Dict[str, Any] = {"animation": anim, "at": at3}
        fac = m.get("facing")
        if fac is not None and f"{fac}".strip() != "":
            try:
                entry["facing"] = int(round(float(fac))) % 360
            except (TypeError, ValueError):
                pass
        out.append(entry)
    return out[:50]


# ── CRUD ────────────────────────────────────────────────────────────────

def create_prop(*, name: str, category: str = "", width_m: Any = None,
                depth_m: Any = None, height_m: Any = None,
                tags: Any = None, description: str = "", prompt: str = "",
                source: str = "manual", backend: str = "") -> Dict[str, Any]:
    """Create a new prop record (sidecar only — the model/source files are
    added by upload or the generation chain). Returns ``{id, **sidecar}``.

    Dims: whatever is given is taken, every missing one becomes the LARGEST
    given value (a rough cube); nothing given = 1 m per dim. The record starts
    ``dims_estimated`` — the mesh's proportions refine it when the model
    arrives."""
    name = (name or "").strip() or "Prop"
    prop_id = _new_prop_id(name)
    dims: Dict[str, float] = {}
    for key, raw in (("width_m", width_m), ("depth_m", depth_m),
                     ("height_m", height_m)):
        if raw is None or f"{raw}".strip() == "":
            continue
        v = _coerce_dim_m(raw, 0.0)
        if v > 0:
            dims[key] = v
    base = max(dims.values()) if dims else DEFAULT_DIM_M
    for key in DIM_KEYS:
        dims.setdefault(key, base)
    meta = {
        "name": name,
        # Generation subject — the name stays free display text, the
        # description feeds the render prompt (surface-texture lesson).
        "description": (description or "").strip(),
        "category": (category or "").strip(),
        "width_m": dims["width_m"],
        "depth_m": dims["depth_m"],
        "height_m": dims["height_m"],
        "dims_estimated": True,
        "rotation": {"x": 0, "y": 0, "z": 0},
        "tags": _coerce_tags(tags),
        "markers": [],
        "created_at": utc_now_iso(),
        "source": (source or "manual").strip(),
        "backend": (backend or "").strip(),
        "prompt": (prompt or "").strip(),
    }
    _write_sidecar(prop_id, meta)
    logger.info("Prop %s created (%s)", prop_id, name)
    return {"id": prop_id, **meta}


def update_prop(prop_id: str, patch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Update the editable sidecar fields (name / category / width_m / depth_m
    / height_m / tags). Patching any dim clears ``dims_estimated`` — a value
    the admin set is never redistributed again. None when the prop does not
    exist."""
    pid = safe_prop_id(prop_id)
    meta = _materialize_dims(pid, read_sidecar(pid)) if pid else {}
    if not meta:
        return None
    if not isinstance(patch, dict):
        patch = {}
    if "name" in patch:
        nm = str(patch.get("name") or "").strip()
        if nm:
            meta["name"] = nm
    if "category" in patch:
        meta["category"] = str(patch.get("category") or "").strip()
    if "description" in patch:
        meta["description"] = str(patch.get("description") or "").strip()
    touched = False
    for key in DIM_KEYS:
        if key in patch:
            meta[key] = _coerce_dim_m(patch.get(key), _coerce_dim_m(meta.get(key)))
            touched = True
    if touched:
        meta["dims_estimated"] = False
    if "tags" in patch:
        meta["tags"] = _coerce_tags(patch.get("tags"))
    _write_sidecar(pid, meta)
    return {"id": pid, **meta}


def set_rotation(prop_id: str, rotation: Any) -> Optional[Dict[str, Any]]:
    """Persist the orientation fix. None when the prop does not exist.

    The STORED dims stay untouched: re-orienting a prop does not silently
    rewrite numbers the admin can see — the editor recomputes its proportional
    suggestions live instead."""
    pid = safe_prop_id(prop_id)
    meta = _materialize_dims(pid, read_sidecar(pid)) if pid else {}
    if not meta:
        return None
    meta["rotation"] = _sanitize_rotation(rotation, meta.get("rotation"))
    _write_sidecar(pid, meta)
    return {"id": pid, **meta}


def set_markers(prop_id: str, markers: Any) -> Optional[Dict[str, Any]]:
    """Replace the object-local marker list. None when the prop does not exist."""
    pid = safe_prop_id(prop_id)
    meta = _materialize_dims(pid, read_sidecar(pid)) if pid else {}
    if not meta:
        return None
    meta["markers"] = sanitize_markers(markers)
    _write_sidecar(pid, meta)
    return {"id": pid, **meta}


def delete_prop(prop_id: str) -> bool:
    """Remove the whole prop directory (model + source + sidecar)."""
    d = _prop_dir(prop_id)
    if not d or not d.exists():
        return False
    shutil.rmtree(d, ignore_errors=True)
    logger.info("Prop %s deleted", safe_prop_id(prop_id))
    return True


# ── Files ───────────────────────────────────────────────────────────────

def model_path(prop_id: str) -> Optional[Path]:
    d = _prop_dir(prop_id)
    if not d:
        return None
    p = d / MODEL_NAME
    return p if p.exists() else None


def source_path(prop_id: str) -> Optional[Path]:
    d = _prop_dir(prop_id)
    if not d:
        return None
    p = d / SOURCE_NAME
    return p if p.exists() else None


def save_uploaded_glb(prop_id: str, contents: bytes) -> bool:
    """Store an uploaded GLB as the prop's model. The prop record must already
    exist (created first); validation is the caller's job."""
    if not read_sidecar(prop_id):
        return False
    d = _prop_dir(prop_id, create=True)
    if not d:
        return False
    (d / MODEL_NAME).write_bytes(contents)
    logger.info("Prop %s: model uploaded (%d bytes)", safe_prop_id(prop_id), len(contents))
    _store_bbox(prop_id)
    return True


# ── Model bounding box ──────────────────────────────────────────────────

def _extract_bbox(prop_id: str) -> Optional[List[float]]:
    """Edge lengths ``[bx, by, bz]`` of the model's AABB in MESH units on the
    RAW mesh axes (no orientation fix applied), round 5 — None when the model
    is missing, unreadable or degenerate (a zero-volume box carries no
    proportions)."""
    mp = model_path(prop_id)
    if not mp:
        return None
    try:
        bounds = glb_bounds(mp.read_bytes())
    except OSError:
        return None
    if not bounds:
        return None
    lo, hi = bounds
    sizes = [round(hi[i] - lo[i], 5) for i in range(3)]
    return sizes if max(sizes) > 0 else None


def _store_bbox(prop_id: str) -> None:
    """Measure the model and persist ``bbox`` on the sidecar (one
    read-modify-write), redistributing still-estimated dims over the fresh
    proportions. A failed measurement leaves the sidecar untouched."""
    bbox = _extract_bbox(prop_id)
    if not bbox:
        return
    pid = safe_prop_id(prop_id)
    meta = _materialize_dims(pid, read_sidecar(pid)) if pid else {}
    if not meta:
        return
    meta["bbox"] = bbox
    _redistribute_dims(meta)
    try:
        _write_sidecar(pid, meta)
    except (OSError, ValueError):
        pass


def _ensure_bbox(prop_id: str, meta: Dict[str, Any]) -> Dict[str, Any]:
    """Lazy backfill for props whose model predates the ``bbox`` field: measure
    once on the first read, persist it, and remember failures per model mtime
    so an unmeasurable GLB is not re-parsed on every listing. Returns the
    (possibly updated) meta."""
    if meta.get("bbox") or not meta:
        return meta
    mp = model_path(prop_id)
    if not mp:
        return meta
    try:
        key = (safe_prop_id(prop_id), mp.stat().st_mtime_ns)
    except OSError:
        return meta
    if key in _bbox_failed:
        return meta
    bbox = _extract_bbox(prop_id)
    if not bbox:
        _bbox_failed.add(key)
        return meta
    meta["bbox"] = bbox
    try:
        _write_sidecar(prop_id, meta)
    except (OSError, ValueError):
        pass
    return meta


# ── Dims migration / redistribution ─────────────────────────────────────

def _materialize_dims(prop_id: str, meta: Dict[str, Any]) -> Dict[str, Any]:
    """Turn a legacy sidecar's single ``size_m`` into the three dims, in place.
    Called at the START of every write path that begins with ``read_sidecar``,
    so a legacy record migrates on its first write instead of needing a
    migration pass. With a measurable model the dims come out proportional
    (and count as informed), without one they are a cube (still estimated)."""
    if not meta or _has_dims(meta):
        meta.pop("size_m", None)
        return meta
    meta = _ensure_bbox(prop_id, meta)
    bbox = meta.get("bbox")
    meta.update(_dims_from_size(meta.get("size_m", DEFAULT_DIM_M), bbox,
                                meta.get("rotation")))
    meta["dims_estimated"] = not bool(bbox)
    meta.pop("size_m", None)
    return meta


def _redistribute_dims(meta: Dict[str, Any]) -> None:
    """Re-derive the dims from the model's proportions, keeping the largest
    edge — ONLY for a still-estimated placeholder cube. Dims the admin set
    (``dims_estimated`` False) are never touched."""
    if not meta.get("dims_estimated") or not meta.get("bbox"):
        return
    dims = _effective_dims(meta)
    meta.update(_dims_from_size(max(dims.values()), meta["bbox"],
                                meta.get("rotation")))
    meta["dims_estimated"] = False


# ── Listing ─────────────────────────────────────────────────────────────

def _all_prop_ids() -> List[str]:
    d = _props_dir()
    if not d.is_dir():
        return []
    out = []
    for p in d.iterdir():
        if p.is_dir() and safe_prop_id(p.name) and (p / SIDECAR_NAME).exists():
            out.append(p.name)
    return sorted(out)


def _prop_record(prop_id: str, meta: Dict[str, Any], *, full: bool) -> Dict[str, Any]:
    meta = _ensure_bbox(prop_id, meta)
    has_model = model_path(prop_id) is not None
    dims = _effective_dims(meta)
    rec: Dict[str, Any] = {
        "id": prop_id,
        "name": meta.get("name") or prop_id,
        "category": meta.get("category") or "",
        "width_m": dims["width_m"],
        "depth_m": dims["depth_m"],
        "height_m": dims["height_m"],
        # The client applies the fix before measuring/scaling the mesh —
        # same role as the room-model meta rotation.
        "rotation": meta.get("rotation") or {"x": 0, "y": 0, "z": 0},
        "tags": meta.get("tags") or [],
        "marker_count": len(meta.get("markers") or []),
        "has_model": has_model,
    }
    if full:
        has_source = source_path(prop_id) is not None
        rec.update({
            "description": meta.get("description") or "",
            "rotation": meta.get("rotation") or {"x": 0, "y": 0, "z": 0},
            "markers": meta.get("markers") or [],
            "has_source": has_source,
            "created_at": meta.get("created_at") or "",
            "source": meta.get("source") or "",
            "backend": meta.get("backend") or "",
            "prompt": meta.get("prompt") or "",
            "model_url": f"/assets/props/{prop_id}/model" if has_model else "",
            "source_url": f"/assets/props/{prop_id}/source" if has_source else "",
        })
        if meta.get("bbox"):
            rec["bbox"] = meta["bbox"]
        rec["dims_estimated"] = (bool(meta.get("dims_estimated"))
                                 if _has_dims(meta) else not bool(meta.get("bbox")))
    return rec


def list_props(*, full: bool = False) -> List[Dict[str, Any]]:
    """All props. ``full`` adds the sidecar detail + file urls (admin);
    otherwise the lean client shape (id, name, category, width_m, depth_m,
    height_m, tags, marker_count, has_model)."""
    out = []
    for pid in _all_prop_ids():
        meta = read_sidecar(pid)
        if meta:
            out.append(_prop_record(pid, meta, full=full))
    return out


def get_prop(prop_id: str) -> Optional[Dict[str, Any]]:
    """Full detail of ONE prop, or None."""
    pid = safe_prop_id(prop_id)
    meta = read_sidecar(pid) if pid else {}
    if not meta:
        return None
    return _prop_record(pid, meta, full=True)


# ── Generation state (populated by the generation chain, A2) ─────────────

def _gen_key(prop_id: str, backend_glob: str) -> str:
    return f"{prop_id}|{(backend_glob or '').strip().lower()}"


def is_pending(prop_id: str = "") -> List[str]:
    """Prop ids with at least one running generation (any backend)."""
    with _lock:
        ids = sorted({k.split("|", 1)[0] for k in _generating})
    if not prop_id:
        return ids
    return [prop_id] if prop_id in ids else []


# ── Generation chain: prompt → txt2img source.png → img2mesh GLB ─────────
# The interior counterpart of location_model3d for single objects. Two GPU
# steps, both on the backend queue channel like every render: a txt2img
# product-shot render (use case ``prop``) becomes source.png, then
# ``service.generate_mesh(rig="none")`` turns it into model.glb (NEVER a
# mesh-backend fallback — the existing rule). Runs on a worker thread with the
# per-job double-start guard (prop_id|mesh backend).

def compose_prompt(subject: str, backend) -> Dict[str, str]:
    """Final source-render prompt + negative for a prop on a backend — the
    ``prop`` use-case style (per image family) plus the object subject
    (usually the prop name). The dialog shows exactly this and may edit it
    (final-prompt rule); ``style`` is returned separately so the UI can
    recompose it per object."""
    from app.core import config as _cfg
    ucp = _cfg.resolve_use_case_style(
        "prop",
        backend_model=getattr(backend, "model", "") or "",
        backend_family=getattr(backend, "image_family", ""))
    subject = (subject or "").strip() or "a single object"
    style = (ucp.get("prompt_style") or "").strip()
    return {
        "style": style,
        "prompt": f"{style}, {subject}" if style else subject,
        "negative": ucp.get("prompt_negative", ""),
    }


def _render_source(prop_id: str, backend_glob: str,
                   prompt: str, negative: str) -> bool:
    """txt2img render of the product shot → source.png. Runs the GPU job on
    the backend queue channel (like every render). Records the image backend
    + final prompt on the sidecar. Returns True on success."""
    from app.imagegen.service import get_image_service
    svc = get_image_service()
    backend = None
    if backend_glob.strip():
        backend = svc.resolve_imagegen_target(backend_glob)
    if not backend:
        # Admin default for prop product shots (/admin/settings → Media
        # Generation → "Prop Default") — the ✨ Furnish job passes no glob.
        default_glob = os.environ.get("PROP_IMAGEGEN_DEFAULT", "").strip()
        if default_glob:
            backend = svc.resolve_imagegen_target(default_glob)
    if not backend:
        backend = svc._select_backend()
    if not backend:
        logger.warning("Prop %s: no image backend available", prop_id)
        return False

    if not prompt.strip():
        # The stored description is the generation subject; the name is only
        # the display fallback when no description was written.
        meta0 = read_sidecar(prop_id)
        composed = compose_prompt(
            meta0.get("description") or meta0.get("name", ""), backend)
        prompt = composed["prompt"]
        if not negative.strip():
            negative = composed["negative"]

    params: Dict[str, Any] = {
        "width": 1024, "height": 1024,
        "seed": random.randint(1, 2**31 - 1),
    }
    from app.core.llm_queue import get_llm_queue, Priority
    images = get_llm_queue().submit_gpu_task(
        provider_name=backend.name,
        task_type="prop_source",
        priority=Priority.IMAGE_GEN,
        callable_fn=lambda: backend.generate(prompt, negative, params),
        agent_name="system",
        label=f"Prop source: {prop_id}",
        gpu_type=backend.api_type)
    if not images:
        logger.warning("Prop %s: empty source render", prop_id)
        return False

    import io
    from PIL import Image
    img = Image.open(io.BytesIO(images[0])).convert("RGB")
    if max(img.size) > 1024:
        img.thumbnail((1024, 1024))
    d = _prop_dir(prop_id, create=True)
    img.save(d / SOURCE_NAME, "PNG")
    meta = _materialize_dims(prop_id, read_sidecar(prop_id))
    meta["backend_image"] = backend.name
    meta["prompt"] = prompt
    meta["negative"] = negative
    _write_sidecar(prop_id, meta)
    return True


def _generate(prop_id: str, prompt: str, negative: str,
              image_backend_glob: str, mesh_backend_glob: str,
              face_num: Any = None, texture_size: Any = None) -> Dict[str, Any]:
    """Blocking chain on a worker thread — source render then img2mesh. ONE
    tracked header task wraps the whole chain (the actual GPU jobs show in the
    queue panel via their channel entries)."""
    from app.core.task_queue import get_task_queue
    name = read_sidecar(prop_id).get("name") or prop_id
    task_id = ""
    try:
        task_id = get_task_queue().track_start(
            "model3d_generation", f"Prop: {name}", start_running=True)
    except Exception:
        task_id = ""

    error = ""
    try:
        if not _render_source(prop_id, image_backend_glob, prompt, negative):
            error = "source render failed"
            return {"ok": False, "error": error}
        src = source_path(prop_id)
        if not src:
            error = "source image missing"
            return {"ok": False, "error": error}

        from app.imagegen.service import get_image_service
        if not mesh_backend_glob.strip():
            # Same admin default the character 3D tab uses — without it the
            # pool picks the cheapest mesh backend, which is arbitrary when
            # several share cost 0.
            from app.core import config
            mesh_backend_glob = str(config.get(
                "image_generation.mesh_imagegen_default", "") or "").strip()
        d = _prop_dir(prop_id, create=True)
        res = get_image_service().generate_mesh(
            source_image_path=str(src),
            output_path=str(d / MODEL_NAME),
            backend_glob=mesh_backend_glob,
            mesh_name=prop_id,
            rig="none",
            face_num=face_num,
            texture_size=texture_size)
        if not res.get("ok"):
            error = str(res.get("error") or "mesh generation failed")
            logger.error("Prop %s mesh failed: %s", prop_id, error)
            return {"ok": False, "error": error}

        # rig="none" always yields a GLB (buildings/props contract), so the
        # output stays model.glb; the rename is a safety net if the sniffed
        # suffix ever differed (our serving expects exactly model.glb).
        path = Path(res["path"])
        target = d / MODEL_NAME
        if path != target and path.exists():
            path.replace(target)

        meta = _materialize_dims(prop_id, read_sidecar(prop_id))
        meta["source"] = "generated"
        meta["backend"] = res.get("backend", "") or meta.get("backend", "")
        # Per-run overrides, recorded for transparency (None = backend default).
        if face_num:
            meta["face_num"] = int(face_num)
        if texture_size:
            meta["texture_size"] = int(texture_size)
        bbox = _extract_bbox(prop_id)
        if bbox:
            meta["bbox"] = bbox
            _redistribute_dims(meta)
        _write_sidecar(prop_id, meta)
        logger.info("Prop %s: model generated (backend %s)",
                    prop_id, meta.get("backend", ""))
        return {"ok": True}
    finally:
        if task_id:
            try:
                get_task_queue().track_finish(task_id, error=error)
            except Exception:
                pass


def trigger_generation(prop_id: str, *, prompt: str = "", negative: str = "",
                       image_backend_glob: str = "",
                       mesh_backend_glob: str = "",
                       face_num: Any = None,
                       texture_size: Any = None) -> bool:
    """Start the source→mesh chain in the background. Different mesh backends
    for the same prop run concurrently (each queues on its own GPU channel);
    False only while THIS prop+backend combination is already generating
    (double-click guard), or when the prop does not exist."""
    pid = safe_prop_id(prop_id)
    if not pid or not read_sidecar(pid):
        return False
    key = _gen_key(pid, mesh_backend_glob)
    with _lock:
        if key in _generating:
            return False
        _generating.add(key)

    def _run() -> None:
        try:
            _generate(pid, prompt, negative, image_backend_glob,
                      mesh_backend_glob, face_num=face_num,
                      texture_size=texture_size)
        except Exception as e:
            logger.error("Prop generation for %s failed: %s", pid, e)
        finally:
            with _lock:
                _generating.discard(key)

    threading.Thread(target=_run, daemon=True).start()
    return True
