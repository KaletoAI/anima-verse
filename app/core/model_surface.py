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

``stand_height_at`` at the bottom is the SERVER's reader (§ 7): the walk gate
of ``POST /play/pos`` stands on the same lattices the clients walk on, so a
crate is a step on both sides and a block a wall on both sides.
"""
import hashlib
import json
import logging
import math
import os
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from app.core.timeutils import utc_now_iso

logger = logging.getLogger(__name__)

#: 3 since 2026-08-28: a version-2 lattice compared the 1.2 m head-room in
#: MODEL units, so every node answered the mesh top (a hut's roof, a door's
#: lintel); nothing to convert, re-bake.
#: 2 since 2026-08-28: a lattice baked as version 1 took SURFACE_STEP_M for a
#: MODEL unit, so a normalised mesh scaled to 10 m got a node every 2.5 m. Every
#: older file therefore reads as stale and is re-baked (the button, or the
#: "Bake walkable surfaces" improvement) — there is nothing to convert, the
#: numbers were measured against the wrong unit.
SURFACE_VERSION = 3
#: The lattice resolution and the head-room a walkable cell needs, BOTH in
#: WORLD metres — what they are worth on the ground a figure walks on, not in
#: the model's own units (spec § 3). The bake divides both by the placement
#: scale before it walks the lattice.
SURFACE_STEP_M = 0.25
SURFACE_CLEARANCE_M = 1.2
MAX_SURFACE_CELLS = 40_000
SURFACE_SUFFIX = ".surface.json"

#: The fields the scene recipe ships (the rest is validity bookkeeping).
PAYLOAD_KEYS = ("step", "origin", "cols", "rows", "values",
                "box_min", "box_max", "extent_snapped")


def surface_path(model_path: Path) -> Path:
    """``room_1.glb`` -> ``room_1.glb.surface.json``: not a model name for the
    gallery's pattern, and deleted together with its model by
    ``ModelGallery.delete`` — the lattice dies with the mesh it measured."""
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


#: Why a bake produced no surface — ``bake_surface_result``'s second answer.
#: ``busy`` is the only TRANSIENT one: every Blender slot was taken, and the
#: very same call would succeed a minute later. Everything else is a defect of
#: this subject or of this installation.
BAKE_REASONS = ("ok", "unreadable", "no_blender", "busy", "failed", "unstorable")


def bake_surface_result(model_path: Path, rotation: Any, *,
                        wait_s: float = 0.0, target_m: float = 0.0,
                        measure: str = "xz") -> Tuple[Optional[Dict[str, Any]], str]:
    """Bake and store the surface of ``model_path`` under ``rotation``, and say
    WHY when there is none: ``(surface, reason)`` with ``reason`` one of
    :data:`BAKE_REASONS`.

    ``target_m`` is the WORLD size the model is placed at — the placement
    spec's ``max_m`` — and ``measure`` the word that spec uses to measure the
    extent it is met over (``"xz"`` for rooms, ``"xyz"`` for props). Together
    they are the scale ``s`` every renderer applies, and the bake needs them
    because :data:`SURFACE_STEP_M` is a world length while the lattice is laid
    out in the model's own units: a normalised mesh scaled to 10 m must get a
    node every 0.25/s of a unit, not every 0.25. A caller that cannot say how
    big the model will be leaves ``target_m`` at 0 and gets the step as it is —
    correct for a model that is already world-sized, coarse for a normalised one.

    The reason exists for the one caller that must tell load from defect: the
    improvements engine skips a candidate for good after two failed attempts,
    so a Blender slot that was taken twice would cost a model its floor
    permanently (spec § 10 — "no free slot" leaves the candidate MISSING, only
    a real failure counts). Every other caller wants :func:`bake_surface` and
    its plain ``Optional``.

    Never raises, one info log per branch: a missing surface is a legal state
    (the terrain answers), not an error.
    """
    from app.blender import refine, runner
    source = _source_of(model_path)
    if source is None:
        logger.info("surface bake skipped (model file unreadable): %s", model_path)
        return None, "unreadable"
    # Asked BEFORE the slot: without Blender the run would fail anyway, and
    # holding one of the few slots to find that out blocks the jobs that could
    # still do something.
    if not runner.is_available():
        logger.info("surface bake skipped (no Blender): %s", Path(model_path).name)
        return None, "no_blender"
    if not refine.take_lod_slot(wait_s):
        logger.info("surface bake skipped (no Blender slot): %s", Path(model_path).name)
        return None, "busy"
    try:
        res = runner.run("heightgrid", inputs={"model": Path(model_path)},
                         params={"rotation": _norm_rotation(rotation),
                                 "step": SURFACE_STEP_M,
                                 "clearance": SURFACE_CLEARANCE_M,
                                 "max_cells": MAX_SURFACE_CELLS,
                                 "target_m": float(target_m or 0.0),
                                 "measure": str(measure or "xz")})
    finally:
        refine.free_lod_slot()
    if not res.get("ok"):
        logger.info("surface bake failed (%s): %s", Path(model_path).name,
                    res.get("error"))
        return None, "failed"
    data = dict(res["data"])
    surface = {"version": SURFACE_VERSION, "source": source,
               "rotation": _norm_rotation(rotation),
               "baked_at": utc_now_iso(), "blender": runner.version(),
               **{k: data[k] for k in PAYLOAD_KEYS}, "hits": data.get("hits", 0),
               # The scale the lattice was cast at — bookkeeping, not payload:
               # the sampler works in model units and reads `step` alone, but a
               # file has to say at which world size its resolution was chosen.
               "target_m": float(target_m or 0.0), "measure": str(measure or "xz"),
               "step_world": data["step_world"]}
    # ATOMICALLY (Minor 5): a lattice is read by the scene route, by the walk
    # gate and by the improvements scan while it is being written, and a
    # half-written file is not merely "no surface" — ``_load`` would parse it
    # every time it is asked, and a reader that caught it mid-write would put
    # a figure on a truncated `values` row. ``os.replace`` swaps the whole file
    # in one step, so a reader sees either the old lattice or the new one.
    dest = surface_path(model_path)
    tmp = dest.with_name(dest.name + ".tmp")
    try:
        tmp.write_text(json.dumps(surface, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, dest)
    except OSError as e:
        logger.info("surface not stored (%s): %s", Path(model_path).name, e)
        try:
            tmp.unlink()
        except OSError:
            pass
        return None, "unstorable"
    _forget_loaded(dest)
    logger.info("surface baked: %s (%dx%d @ %.4f model units = %.2f m world, "
                "%d hits)", Path(model_path).name, surface["cols"],
                surface["rows"], surface["step"], surface["step_world"],
                surface["hits"])
    return surface, "ok"


def bake_surface(model_path: Path, rotation: Any, *,
                 wait_s: float = 0.0, target_m: float = 0.0,
                 measure: str = "xz") -> Optional[Dict[str, Any]]:
    """Bake and store the surface of ``model_path`` under ``rotation``.

    None when the model is unreadable, Blender is unavailable, no slot came
    free within ``wait_s``, the script failed or the lattice could not be
    stored — with ONE info log, never an exception: a missing surface is a
    legal state (the terrain answers), not an error. A caller that has to act
    on WHICH of those it was takes :func:`bake_surface_result`.

    ``target_m``/``measure`` are that function's — the world size the model is
    placed at and how its extent is measured.
    """
    return bake_surface_result(model_path, rotation, wait_s=wait_s,
                               target_m=target_m, measure=measure)[0]


# ── The parsed sidecars (Important 3) ───────────────────────────────────
#
# WHY A CACHE AT ALL. A lattice is a few hundred kilobytes of JSON, and almost
# nobody who parses one wants the numbers: composing a scene reads the sidecar
# of every room model and of every placed prop just to find out whether the
# spec carries a `surface` field at all, the walk gate composes a location
# afresh every 5 s per walker, and the improvements scan walks the whole stock
# in one pass. Without this, one walking player parsed every prop lattice of
# their location twelve times a minute.
#
# THE KEY IS THE FILE'S IDENTITY, not its path: size and nanosecond mtime come
# from the very ``stat`` the lookup needs anyway, so a re-bake, a hand edit or
# a restored backup can never be answered from the cache — the key simply is
# not the same one any more. ``_forget_loaded`` on top of that is belt and
# braces for a bake that lands inside one mtime tick.
#
# The parsed dict is handed out AS IS and every reader treats it as read-only
# (``payload_block`` copies the mapping, the samplers only index it).
_LOAD_CACHE_MAX = 256
_load_cache: "OrderedDict[Tuple[str, int, int], Dict[str, Any]]" = OrderedDict()


def _forget_loaded(path: Path) -> None:
    """Drop every cached parse of ONE surface file — the bake that overwrote
    it must not be shadowed by the version it replaced."""
    name = str(path)
    for key in [k for k in _load_cache if k[0] == name]:
        _load_cache.pop(key, None)


def _load(model_path: Path) -> Optional[Dict[str, Any]]:
    p = surface_path(model_path)
    try:
        st = p.stat()
    except OSError:
        return None
    key = (str(p), st.st_size, st.st_mtime_ns)
    hit = _load_cache.get(key)
    if hit is not None:
        return hit
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    _load_cache[key] = data
    while len(_load_cache) > _LOAD_CACHE_MAX:
        _load_cache.popitem(last=False)          # oldest entry goes first
    return data


def _valid(surface: Dict[str, Any], model_path: Path, rotation: Any) -> bool:
    if surface.get("version") != SURFACE_VERSION:
        return False
    # COMPLETE, not merely current: ``payload_block`` indexes all eight keys,
    # so a file that lost one — a truncated write, a hand-edit — would raise a
    # KeyError inside the scene route instead of reading as "no surface". A
    # missing surface is a legal state; a half one is not.
    if any(k not in surface for k in PAYLOAD_KEYS):
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
    """What the admin panels show: baked / missing / stale (+ lattice size).

    ``step`` is the WORLD step ("baked 81×81 @ 0.25 m") — the resolution the
    label promises is a length on the ground, not in the model's own units. The
    file's ``step`` is the same number divided by the placement scale, and a
    panel that printed it would read "@ 0.03 m" for the very lattice that
    resolves the ground every 25 cm.
    """
    if not model_path:
        return {"state": "missing"}
    surface = _load(model_path)
    if not surface:
        return {"state": "missing"}
    state = "baked" if _valid(surface, model_path, rotation) else "stale"
    return {"state": state, "cols": surface.get("cols"), "rows": surface.get("rows"),
            "step": surface.get("step_world", surface.get("step"))}


def delete_surface(model_path: Path) -> bool:
    """Remove the stored surface of ``model_path``: True when there was one and
    it is gone, False when there was none.

    A STATE, not an event — "this model has no lattice" is the answer either
    way, and the caller that has to tell the two apart (the admin panel says
    "removed" or "there was nothing") reads the bool. Never raises: a sidecar
    that cannot be removed is logged and answers False, exactly like the bake's
    "not stored".

    Valid or stale makes no difference. The file IS the surface — a stale one
    reads as "no surface" but is still what the panel shows and what a fixed
    fix would revive — so what the admin points at is what goes.

    The parsed sidecar goes with it: the cache is keyed on size and mtime and
    could never answer for a file that is gone, but nothing else would ever
    evict the entry, and a read/delete/re-bake inside one mtime tick would then
    be served the version that was deleted.
    """
    p = surface_path(model_path)
    try:
        p.unlink()
    except FileNotFoundError:
        return False
    except OSError as e:
        logger.info("surface not removed (%s): %s", Path(model_path).name, e)
        return False
    _forget_loaded(p)
    logger.info("surface removed: %s", Path(model_path).name)
    return True


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
                      x: float, z: float, lift: float = 0.0) -> Optional[float]:
    """Standing height (tile-local metres) of placement ``spec`` at (x, z), or
    None where the lattice does not answer. The exact inverse of
    placeModelSpec — see spec § 6.2; the TS twin is surfaceHeightAt.

    ``lift`` is the storey-0 terrain lift the placement was moved by after
    placement (§ A16.9): the lattice stands where its model stands.

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
        # A short/ragged values array reads as "no node", never an IndexError:
        # a corrupt sidecar must answer like a hole (the terrain takes over),
        # and the TS twin says the same by way of `undefined == null`.
        idx = j * cols + i
        val = vals[idx] if 0 <= idx < len(vals) else None
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
    return float(spec.get("bottom_y") or 0.0) + float(lift) + s * val / 100.0


def highest_surface_at(specs: Iterable[Dict[str, Any]], x: float, z: float,
                       lift_of: Optional[Callable[[Dict[str, Any]], float]] = None
                       ) -> Optional[float]:
    """The highest answering surface among placement specs carrying one.

    ``lift_of`` names the § A16.9 terrain lift of ONE spec; without it every
    placement is read on its composed ``bottom_y`` (lift 0). The caller owns
    that number — the recipe composes the specs, the ground field lifts them.
    """
    best: Optional[float] = None
    for spec in specs:
        surface = spec.get("surface")
        if not surface:
            continue
        y = surface_height_at(surface, spec, x, z,
                              lift_of(spec) if lift_of else 0.0)
        if y is not None and (best is None or y > best):
            best = y
    return best


# ── The server's standing height (spec § 7) ─────────────────────────────
#
# The walk gate of ``POST /play/pos`` runs up to four times a second per
# walker and asks for TWO points per report, while composing a location's
# scene reads its rooms, its props and every model meta. So the rungs of a
# location are composed at most once per TTL — a window short enough that a
# freshly baked surface reaches the gate before any client has re-fetched the
# scene, and long enough that a walking party costs one compose, not fifty.
#
# A BARE DICT ON THE SHARED THREADPOOL, and that is safe without a lock: the
# reports run in worker threads, but a dict get/set is atomic under the GIL and
# the cached lists are only ever REPLACED, never mutated in place — a reader
# holds lists nobody writes into. The worst a race can do is let two walkers
# compose the same location once each, which is one wasted compose and never a
# wrong height.
_SURFACE_TTL_S = 5.0
_placed_cache: Dict[str, Tuple[float, List[Dict[str, Any]],
                               List[Dict[str, Any]]]] = {}
#: Location ids whose lattice lookup already failed once — the gate must not
#: write a traceback per report for one malformed sidecar.
_read_warned: Dict[str, bool] = {}


def forget_surfaces(location_id: str = "") -> None:
    """Drop the cached scene rungs of ONE location, or of all of them.

    The failure flag goes with them: a re-bake, a fixed sidecar or a repaired
    scene deserves a fresh traceback if it is still broken, and a flag that is
    never cleared silences the gate for the rest of the process.

    The bare call also empties the PARSED-SIDECAR cache: it is the call every
    bake makes, and "forget what you know about surfaces" must not leave a
    lattice behind that a reader could still be answered from.
    """
    if location_id:
        _placed_cache.pop(location_id, None)
        _read_warned.pop(location_id, None)
    else:
        _placed_cache.clear()
        _read_warned.clear()
        _load_cache.clear()


def _room_declarations(scene: Dict[str, Any],
                       models: Iterable[Dict[str, Any]],
                       ) -> List[Dict[str, Any]]:
    """RUNG 1 of the server ladder as data: one ``{spec, hull}`` per storey-0
    room that DECLARES a walking height.

    The hull is the room's ``floor_plan`` polygon — the very entry the client
    builds its ``declaredFloors`` from (``sceneRecipe.ts``), so both sides
    judge the declaration inside the same shape. A room whose polygon the
    composer did not emit (an unplaced location has none) declares nothing:
    without a hull there is no point at which the declaration would apply.
    """
    hulls: Dict[str, Any] = {}
    for entry in scene.get("floor_plan") or []:
        if not isinstance(entry, dict):
            continue
        rid = str(entry.get("room_id") or "")
        poly = entry.get("polygon_world")
        if rid and isinstance(poly, list) and len(poly) >= 3:
            hulls[rid] = poly
    out: List[Dict[str, Any]] = []
    for spec in models:
        if spec.get("role") != "room" or int(spec.get("level") or 0) != 0:
            continue
        if spec.get("walk_y_world") is None:
            continue
        hull = hulls.get(str(spec.get("room_id") or ""))
        if hull:
            out.append({"spec": spec, "hull": hull})
    return out


def declared_floor_of(declarations: Iterable[Dict[str, Any]],
                      x: float, z: float) -> Optional[Dict[str, Any]]:
    """The declaration that applies at tile-local (x, z), or None.

    The Python twin of ``declaredFloorAt`` (``client3d/src/game/ground.ts``),
    tie-break included: where several hulls contain the point the SMALLEST one
    wins — the innermost answer, the same most-specific-first rule the
    footprints use. Rooms are not supposed to overlap, but an always-visible
    outdoor zone spanning half the location legally contains a hut standing in
    it, and the hut's floor is the one a figure inside it stands on.

    Containment first and the area only for the hulls that answer at all: the
    overlap is the rare case and must not cost a shoelace pass over every room
    of the location.
    """
    from app.core.world_geometry import point_in_polygon, polygon_area
    best: Optional[Dict[str, Any]] = None
    best_area = -1.0                       # < 0 = not measured yet
    for dec in declarations:
        if not point_in_polygon(x, z, dec["hull"]):
            continue
        if best is None:
            best = dec
            continue
        if best_area < 0:
            best_area = polygon_area(best["hull"])
        area = polygon_area(dec["hull"])
        if area > 0 and (best_area <= 0 or area < best_area):
            best = dec
            best_area = area
    return best


def _scene_specs(location: Dict[str, Any],
                 ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """What the walk gate reads off a location's scene: ``(lattices,
    declarations)`` — the placement specs that carry a baked ``surface``, and
    the storey-0 rooms that declare a ``walk_y_world`` with the hull it
    applies inside. Everything in tile-local metres, like every scene number.

    The same composition ``GET /play/locations/{id}/scene`` serves, down to
    its 404 gate: a location with no room layout, no building outline and no
    building model composes nothing, and that empty answer is cached too.

    EVERYTHING that reads is inside the guard, ``scene_inputs`` included: it
    goes to disk for the model metas, and a failure there that escaped the
    cache would send every single report down the same failing disk reads,
    four times a second per walker.
    """
    loc_id = str(location.get("id") or "")
    now = time.monotonic()
    hit = _placed_cache.get(loc_id)
    if hit and hit[0] > now:
        return hit[1], hit[2]
    specs: List[Dict[str, Any]] = []
    declarations: List[Dict[str, Any]] = []
    try:
        from app.core.scene_recipe import compose_scene, scene_inputs
        from app.core.surface_textures import library_kinds
        map3d = location.get("map3d") or {}
        has_layout = any(isinstance(r, dict) and r.get("layout")
                         for r in location.get("rooms") or [])
        plan_width_m, building_meta, room_metas = scene_inputs(location, loc_id)
        if has_layout or len(map3d.get("outline") or []) >= 3 or building_meta:
            scene = compose_scene(location, plan_width_m=plan_width_m,
                                  building_meta=building_meta,
                                  room_metas=room_metas,
                                  surface_kinds=library_kinds())
            models = scene.get("models") or []
            specs = [m for m in models if m.get("surface")]
            declarations = _room_declarations(scene, models)
    except Exception:          # a broken scene must not block walking
        specs, declarations = [], []
        logger.exception("surfaces: compose failed for %s", loc_id)
    _placed_cache[loc_id] = (now + _SURFACE_TTL_S, specs, declarations)
    return specs, declarations


def _datum_y(location: Dict[str, Any]) -> Optional[float]:
    """The ground under the location's PIN, which is the zero every scene
    number is measured from — ``tile.center.y`` in the client
    (``footprintCentre`` asks the height field at ``pos_x``/``pos_z``).

    ``None`` when there is no usable pin or the field answers nothing finite
    there. NOT 0.0: the client's ``storeyGroundLift`` gives a placement no lift
    at all without a finite datum (``packages/scene-render/src/storeyGround.ts``),
    and reading the missing datum as sea level would lift every lattice by the
    absolute height of its own anchor instead.
    """
    from app.core.relief import ground_at
    try:
        px = float(location.get("pos_x"))
        pz = float(location.get("pos_z"))
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(px) and math.isfinite(pz)):
        return None
    g = ground_at(px, pz)
    return g if math.isfinite(g) else None


def stand_height_at(location: Optional[Dict[str, Any]],
                    x: float, z: float) -> float:
    """Where a figure stands at WORLD (x, z), in metres: the world ground,
    raised by what the location's scene puts over it at that point.

    THE SERVER LADDER HAS THREE RUNGS, and it is the client's ground ladder
    (``tileWalkY``) minus the one rung that cannot apply here:

    0. THE BAKED LATTICE — ``highest_surface_at`` over the storey-0 specs that
       carry a ``surface``. Highest answering lattice wins (Ruling R3).
    1. THE DECLARATION — where no lattice answers (a ``null`` cell, a point
       beside every model), the ``walk_y_world`` a storey-0 room states, taken
       inside its ``floor_plan`` hull and the smallest hull first
       (:func:`declared_floor_of`). ``walk_y_world`` is tile-local like
       ``bottom_y``, so it takes the SAME storey-0 terrain lift as the
       placement it belongs to (§ A16.9) — the declaration stands where its
       diorama stands.
    2. THE TERRAIN — ``ground_at``, and it is the lower bound of the two rungs
       above as well (Entscheid 5): a hollow in a diorama never sinks a figure
       below the ground it stands on.

    THE PLATES (the client's rung 2) ARE DELIBERATELY ABSENT. Since E5a the
    recipe draws a plate for DECLARED STOREYS only — storey 0 has none — and
    this gate is storey-0 only (see below). There is nothing for that rung to
    answer here, and adding it would mean measuring a walker on the ground
    plane against the slab of the floor above them.

    The whole thing is the server's copy of the client's
    ``standY(tileWalkY, worldGround)`` (spec § 7).

    STOREY 0 ONLY, exactly like the client's GROUND ladder (``tileWalkY``): a
    walker reports a point on the ground plane, and the diorama of an upper
    floor must not be what it is measured against. A figure on an upper floor
    got there through a room, not through this route.

    A location that composes no scene, a location without a usable datum and a
    point no rung answers at all leave the bare ground — as does anything that
    goes wrong while reading: the walk gate is a plausibility check on a step,
    and a malformed sidecar must never be the reason a player cannot walk.
    """
    from app.core.relief import ground_at
    ground = ground_at(x, z)
    if not location:
        return ground
    loc_id = str(location.get("id") or "")
    try:
        specs, declarations = _scene_specs(location)
        if not specs and not declarations:
            return ground
        from app.core.world_geometry import local_to_world, world_to_local
        cx = float(location.get("pos_x") or 0.0)
        cz = float(location.get("pos_z") or 0.0)
        yaw = float(location.get("yaw_deg") or 0.0)
        datum = _datum_y(location)
        if datum is None:
            return ground
        lx, lz = world_to_local(x, z, cx, cz, yaw)

        def lift_of(spec: Dict[str, Any]) -> float:
            """§ A16.9: a storey-0 placement stands on the ground under ITS
            OWN anchor, not under the pin — ``storeyGroundLift`` in the
            client, and the lattice stands where its model stands."""
            ax, az = spec["anchor"]
            wx, wz = local_to_world(float(ax), float(az), cx, cz, yaw)
            g = ground_at(wx, wz)
            return (g - datum) if math.isfinite(g) else 0.0

        baked = highest_surface_at(
            (s for s in specs if int(s.get("level") or 0) == 0),
            lx, lz, lift_of)
        if baked is None:
            # RUNG 1: no lattice covers the point — a hole in the bake, a
            # ``null`` cell, or a room that has no lattice at all. The room's
            # own declaration is what the client falls to here, so the gate
            # falls to it too: without this the server judged a step onto a
            # declared podium against the terrain under it and refused what
            # every renderer draws as a floor.
            dec = declared_floor_of(declarations, lx, lz)
            if dec is not None:
                baked = (lift_of(dec["spec"])
                         + float(dec["spec"]["walk_y_world"]))
    except Exception:
        if not _read_warned.get(loc_id):
            _read_warned[loc_id] = True
            logger.exception("surfaces: unreadable lattice at %s — the walk "
                             "gate falls back to the ground", loc_id)
        return ground
    if baked is None:
        return ground
    return max(ground, datum + baked)
