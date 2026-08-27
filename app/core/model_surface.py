"""Baked walkable surfaces of models (spec-surface-height, 2026-08-27).

A model's surface lives in ``<model file>.surface.json`` next to the model —
a lattice of walkable heights in the model's OWN frame after the sidecar
orientation fix, baked by Blender (``app/blender/scripts/heightgrid.py``).
The scene recipe ships the lattice inline on the placement spec, and ONE
sampling formula (``surface_height_at`` here, ``surfaceHeightAt`` in
packages/scene-render) turns it into a standing height on both sides.

Validity is a property of the FILE: it names its format version, the model
file it was baked from (size + mtime) and the fix it was baked under. Anything
that disagrees reads as "no surface" — today's behaviour, never a stale floor.
"""
import hashlib
import json
import logging
import math
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from app.core.timeutils import utc_now_iso

logger = logging.getLogger(__name__)

SURFACE_VERSION = 1
SURFACE_STEP_M = 0.25
SURFACE_CLEARANCE_M = 1.2
MAX_SURFACE_CELLS = 40_000
SURFACE_SUFFIX = ".surface.json"

#: The fields the scene recipe ships (the rest is validity bookkeeping).
PAYLOAD_KEYS = ("step", "origin", "cols", "rows", "values",
                "box_min", "box_max", "extent_snapped")


def surface_path(model_path: Path) -> Path:
    """``room_1.glb`` -> ``room_1.glb.surface.json``: not a model name for the
    gallery's pattern, but purged with the model by its ``<name>.*`` glob."""
    p = Path(model_path)
    return p.with_name(p.name + SURFACE_SUFFIX)


def _norm_rotation(rotation: Any) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for axis in ("x", "y", "z"):
        try:
            v = float((rotation or {}).get(axis, 0) or 0)
        except (TypeError, ValueError, AttributeError):
            v = 0.0
        out[axis] = round(v % 360.0, 1)
    return out


def _source_of(model_path: Path) -> Optional[Dict[str, Any]]:
    try:
        st = Path(model_path).stat()
    except OSError:
        return None
    return {"name": Path(model_path).name, "size": st.st_size,
            "mtime": int(st.st_mtime)}


def bake_surface(model_path: Path, rotation: Any, *,
                 wait_s: float = 0.0) -> Optional[Dict[str, Any]]:
    """Bake and store the surface of ``model_path`` under ``rotation``.

    None when Blender is unavailable, no slot came free within ``wait_s``, or
    the script failed — with ONE info log, never an exception: a missing
    surface is a legal state (the terrain answers), not an error.
    """
    from app.blender import refine, runner
    source = _source_of(model_path)
    if source is None:
        logger.info("surface bake skipped (model file unreadable): %s", model_path)
        return None
    if not refine.take_lod_slot(wait_s):
        logger.info("surface bake skipped (no Blender slot): %s", Path(model_path).name)
        return None
    try:
        res = runner.run("heightgrid", inputs={"model": Path(model_path)},
                         params={"rotation": _norm_rotation(rotation),
                                 "step": SURFACE_STEP_M,
                                 "clearance": SURFACE_CLEARANCE_M,
                                 "max_cells": MAX_SURFACE_CELLS})
    finally:
        refine.free_lod_slot()
    if not res.get("ok"):
        logger.info("surface bake failed (%s): %s", Path(model_path).name,
                    res.get("error"))
        return None
    data = dict(res["data"])
    surface = {"version": SURFACE_VERSION, "source": source,
               "rotation": _norm_rotation(rotation),
               "baked_at": utc_now_iso(), "blender": runner.version(),
               **{k: data[k] for k in PAYLOAD_KEYS}, "hits": data.get("hits", 0)}
    try:
        surface_path(model_path).write_text(
            json.dumps(surface, ensure_ascii=False), encoding="utf-8")
    except OSError as e:
        logger.info("surface not stored (%s): %s", Path(model_path).name, e)
        return None
    logger.info("surface baked: %s (%dx%d @ %.2f m, %d hits)", Path(model_path).name,
                surface["cols"], surface["rows"], surface["step"], surface["hits"])
    return surface


def _load(model_path: Path) -> Optional[Dict[str, Any]]:
    p = surface_path(model_path)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _valid(surface: Dict[str, Any], model_path: Path, rotation: Any) -> bool:
    if surface.get("version") != SURFACE_VERSION:
        return False
    src = _source_of(model_path)
    if not src or surface.get("source") != src:
        return False
    return _norm_rotation(surface.get("rotation")) == _norm_rotation(rotation)


def read_surface(model_path: Path, rotation: Any) -> Optional[Dict[str, Any]]:
    """The stored surface, or None when absent or no longer valid."""
    surface = _load(model_path)
    if not surface or not _valid(surface, model_path, rotation):
        return None
    return surface


def surface_status(model_path: Optional[Path], rotation: Any) -> Dict[str, Any]:
    """What the admin panels show: baked / missing / stale (+ lattice size)."""
    if not model_path:
        return {"state": "missing"}
    surface = _load(model_path)
    if not surface:
        return {"state": "missing"}
    state = "baked" if _valid(surface, model_path, rotation) else "stale"
    return {"state": state, "cols": surface.get("cols"), "rows": surface.get("rows"),
            "step": surface.get("step")}


def payload_block(surface: Dict[str, Any]) -> Dict[str, Any]:
    """The eight fields the placement spec carries (§ 6.1)."""
    return {k: surface[k] for k in PAYLOAD_KEYS}


def block_sig(block: Dict[str, Any]) -> str:
    """Eight hex chars over a payload block — for the scene signature."""
    raw = json.dumps(block, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.md5(raw).hexdigest()[:8]


def _extent(surface: Dict[str, Any], measure: str) -> float:
    ex, ey, ez = (float(v) for v in surface["extent_snapped"])
    if measure == "xyz":
        return max(ex, ey, ez)
    return max(ex, ez)


def surface_scale(surface: Dict[str, Any], spec: Dict[str, Any]) -> float:
    """``max_m`` over the snapped extent — the factor placeModelSpec applies."""
    return float(spec.get("max_m") or 1.0) / (_extent(surface, str(spec.get("measure") or "xz")) or 1.0)


def surface_height_at(surface: Dict[str, Any], spec: Dict[str, Any],
                      x: float, z: float) -> Optional[float]:
    """Standing height (tile-local metres) of placement ``spec`` at (x, z), or
    None where the lattice does not answer. The exact inverse of
    placeModelSpec — see spec § 6.2; the TS twin is surfaceHeightAt.

    The bake's outermost lattice ring is cast 1 mm inside the box but read at
    its nominal node coordinate, so when the box extent is not a whole multiple
    of ``step`` the last ring's value extrapolates outward over up to one step
    of ground the model does not cover.
    """
    s = surface_scale(surface, spec)
    bmin, bmax = surface["box_min"], surface["box_max"]
    cx = (float(bmin[0]) + float(bmax[0])) / 2.0
    cz = (float(bmin[2]) + float(bmax[2])) / 2.0
    ax, az = spec["anchor"]
    qx, qz = float(x) - float(ax), float(z) - float(az)
    th = math.radians(float(spec.get("yaw_deg") or 0.0))
    c, sn = math.cos(th), math.sin(th)
    lx = qx * c - qz * sn
    lz = qx * sn + qz * c
    step = float(surface["step"])
    u = (lx / s + cx - float(surface["origin"][0])) / step
    v = (lz / s + cz - float(surface["origin"][1])) / step
    cols, rows = int(surface["cols"]), int(surface["rows"])
    if not (0.0 <= u <= cols - 1 and 0.0 <= v <= rows - 1):
        return None
    i0 = min(int(math.floor(u)), cols - 2) if cols > 1 else 0
    j0 = min(int(math.floor(v)), rows - 2) if rows > 1 else 0
    fu, fv = u - i0, v - j0
    vals = surface["values"]

    def at(i: int, j: int) -> Optional[float]:
        val = vals[j * cols + i]
        return None if val is None else float(val)

    i1 = min(i0 + 1, cols - 1)
    j1 = min(j0 + 1, rows - 1)
    corners = (at(i0, j0), at(i1, j0), at(i0, j1), at(i1, j1))
    if any(cv is None for cv in corners):
        return None
    a, b, cc, d = corners  # type: ignore[misc]
    top = a + (b - a) * fu
    bot = cc + (d - cc) * fu
    val = top + (bot - top) * fv
    return float(spec.get("bottom_y") or 0.0) + s * val / 100.0


def highest_surface_at(specs: Iterable[Dict[str, Any]],
                       x: float, z: float) -> Optional[float]:
    """The highest answering surface among placement specs carrying one."""
    best: Optional[float] = None
    for spec in specs:
        surface = spec.get("surface")
        if not surface:
            continue
        y = surface_height_at(surface, spec, x, z)
        if y is not None and (best is None or y > best):
            best = y
    return best
