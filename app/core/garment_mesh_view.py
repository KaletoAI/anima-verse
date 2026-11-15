"""The Mesh row's 3D view of an own-mesh clothing piece (Ruling A48a): the mesh files, the base body as a ghost
in the mesh's placed pose, and the faces of the mesh that lie inside the body.

The Wardrobe's step grid shows the prepared mesh (``garments/prepared/{item}_{fsig}.glb``), its raw generator
output (``raw/``) and every kept refused attempt (``attempts/mesh/``, ``garment_mesh.keep_attempt``) in a viewer.
Two switches need the body:

- **Body**: the character's base body (the UNRIGGED base model the fit places the piece against,
  ``model3d/unrigged/<bsig>.glb``) as a translucent ghost.
- **Inside the body**: the faces of the shown mesh whose centroids lie inside that body, in red, and their share
  of the mesh's area as a number.

Both need the piece placed on the body the way the fit places it (``garment_fit.fit_clothing``): the shared image
framing of the bald front view and the ghost front (``garment_source.fit_masks``, ``garment_fit.place_by_framing``
on the welded mesh without its crumbs), then the depth of the torso band (``align_band_depth``). That placement is a
uniform scale ``s`` and an offset ``t`` (``Q = s·P + t``); it is taken BEFORE the fit's push-out, opening cut and
scale retry, so the view shows where the mesh lands before the fit moves anything — what the fit's push numbers
measure. The inside test is the fit's own body field (``garment_fit.body_sdf`` at ``VOX_M / k``, zero level on the
surface): a face is inside when the field at its centroid is negative. The share is area-weighted.

Everything the client draws is in the MESH's own frame, so the mesh file is served unchanged: the ghost is the body
mapped back by ``(X - t) / s`` and the red overlay is the inside faces of the mesh itself, each a small static GLB.

**The fit allowance (Ruling A48c).** The viewer previews the piece's width allowance (Ruling A47,
``garment_fit.scale_retry``) live against the body: the fit widens the PLACED piece about the body's torso axis
(``garment_fit.widen``: z scaled about the axis, x scaled within ``CLOTHING_BODY_HALF_X · height`` of it and shifted
beyond, y untouched) before its push. Placement is a uniform scale plus an offset, so the same widening in the
mesh's own frame is ``widen`` about the axis mapped back (``(c - t) / s``, half width ``/ s``) — the client runs
that one rule (``frontend/src/tabs/characters/fitWiden.ts``, a port with a parity smoke) on the shown mesh and the
red overlay. The server measures every factor the allowance can take (``allowance_factors``: the settable choices
and the automatic steps) once, with the same body field: the share inside the body, and the gap to the body over
the piece's trunk band (``trunk_band_rows``: the welded vertices within the widening's half width of the axis,
between the hips and the shoulder joints) as p50 and minimum in mm. The red overlay holds every face that is inside
at ANY factor; ``allowance.mask`` says per overlay face (a little-endian 16-bit word, bit ``i`` =
``allowance_factors()[i]``) at which factors it is inside, so the client shows exactly the faces of the factor being
previewed.

**The depth allowance (Ruling A68).** The fit adds room in front of and behind the trunk AFTER its push-out
(``garment_fit.depth_shift``: z away from the torso's depth centre by a percent of the torso's half depth, faded out
toward the sleeves and the collar). The axis carries its frame too (``ramp``, ``x_limit``, ``y_limit``,
``half_depth``, mapped into the mesh frame like the axis), so the client previews the same shift
(``fitWiden.ts`` ``easeInPlace``) on top of the widening. Per width factor the table adds, for every depth choice,
the gap in front of and behind the trunk (``depth_gaps``, aligned with ``allowance.depth.choices``): the median gap of
the trunk band's vertices within ``garment_fit.FRONT_BACK_DEG`` of straight ahead / behind, widened and shifted —
before the push-out, like the trunk gap (the fit adds the depth AFTER its push, so where the piece lies inside the
body the fit's result stands off by about the shift from its clearance; the fit records what it measured,
``metrics.trunk_front_gap_p50_m`` / ``trunk_back_gap_p50_m``).

Computed once per input set and cached on disk under ``<storage>/.cache/garment_mesh_view/<key>.{json,ghost.glb,
inside.glb}`` — ``key`` is a hash of ``VIEW_VERSION`` and the content versions of the mesh file, both base models,
the bald front view, the ghost front and the group's base copy (the inputs of the placement and the field). A key
is computed under ``keyed_lock("garment_mesh_view", key)``, so a second asker waits for the first and reads its
files. ``_INFO`` counts computations and cache hits (``scripts/smoke_garment_mesh_view.py``).
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np

from app.core.log import get_logger

logger = get_logger("garment_mesh_view")

#: The mesh files of the Mesh row: the decimated mesh the fit takes, and the generator's output.
WHICH: Tuple[str, ...] = ("prepared", "raw")
#: The two cached overlays (``overlay_path``).
OVERLAYS: Tuple[str, ...] = ("ghost", "inside")
#: Stamped into the cache key: a change of the placement or the inside rule computes every view again
#: (2: Ruling A48c, the allowance table and the union overlay; 3: Ruling A68, the depth frame and gaps; 4: Ruling A76,
#: the choices up to +20 % — nine factors, two mask bytes per face).
VIEW_VERSION = 4
#: The ghost's colour (RGBA) and the inside faces' (the client draws them translucent / on top).
GHOST_RGBA = [0.62, 0.70, 0.80, 1.0]
INSIDE_RGBA = [0.97, 0.32, 0.29, 1.0]

_INFO = {"computes": 0, "hits": 0}
_INFO_LOCK = threading.Lock()


class ViewUnavailable(Exception):
    """The body view cannot be made: no base model, no ghost front, a frame the fit refuses — the message says
    which, in plain words."""


def info() -> Dict[str, int]:
    with _INFO_LOCK:
        return dict(_INFO)


def _count(key: str) -> None:
    with _INFO_LOCK:
        _INFO[key] += 1


# --- Files ------------------------------------------------------------------------------------------------------------

def current_fsig(character_name: str, item_id: str) -> str:
    """The piece's current fsig; ValueError for an item that is no garment of the character."""
    from app.core import garment_store as gs
    return gs.garment_fsig(character_name, item_id)


_TRIS: Dict[Tuple[str, str], Optional[int]] = {}
_TRIS_LOCK = threading.Lock()


def file_triangles(path: Path, version: str) -> Optional[int]:
    """The triangle count of the GLB at ``path`` as it is stored — read from its JSON chunk alone (the index
    accessors' counts / 3, a primitive without indices its positions / 3), not from the step record, which counts
    the decimator's output before the export drops degenerate triangles (Glut's slip: 59,562 recorded, 59,544 in
    the file — the number the viewer shows). Cached per path and ``version`` (its content version); None when the
    file cannot be read as a GLB."""
    import struct
    key = (str(path), version)
    with _TRIS_LOCK:
        if key in _TRIS:
            return _TRIS[key]
    count: Optional[int] = None
    try:
        with open(path, "rb") as fh:
            head = fh.read(20)
            magic, _v, _length, chunk_len, chunk_type = struct.unpack("<4sIIII", head)
            if magic == b"glTF" and chunk_type == 0x4E4F534A:
                gltf = json.loads(fh.read(chunk_len))
                accessors = gltf.get("accessors") or []
                total = 0
                for mesh in gltf.get("meshes") or []:
                    for prim in mesh.get("primitives") or []:
                        if prim.get("mode", 4) != 4:
                            continue
                        idx = prim.get("indices")
                        acc = accessors[idx] if idx is not None else accessors[(prim.get("attributes") or {})["POSITION"]]
                        total += int(acc.get("count") or 0) // 3
                count = total
    except (OSError, ValueError, KeyError, IndexError, TypeError, struct.error):
        count = None
    with _TRIS_LOCK:
        if len(_TRIS) > 512:
            _TRIS.clear()
        _TRIS[key] = count
    return count


def mesh_file(character_name: str, item_id: str, which: str, attempt: int = 0) -> Optional[Path]:
    """The mesh file ``which`` (``prepared`` / ``raw``) of the piece's CURRENT fsig — of the kept mesh
    ``attempt`` when > 0 (``garment_mesh.attempt_files``, Ruling A58) — or None when it is not there. The prepared mesh is
    served only with its accepted record (``garment_mesh``: it exists only then). ValueError for a bad ``which``,
    attempt or item."""
    from app.core import garment_mesh
    from app.core import garment_store as gs
    if which not in WHICH:
        raise ValueError(f"which must be one of {', '.join(WHICH)}")
    if isinstance(attempt, bool) or not isinstance(attempt, int) or not 0 <= attempt <= garment_mesh.KEPT_MAX:
        raise ValueError(f"attempt must be 0..{garment_mesh.KEPT_MAX}")
    fsig = current_fsig(character_name, item_id)
    if attempt:
        return garment_mesh.attempt_files(character_name, item_id, fsig, attempt)[which]
    path = gs.garment_path(character_name, item_id, fsig, which)
    if not path.is_file():
        return None
    if which == "prepared" and gs.read_record(path.with_suffix(".json")).get("accepted") is not True:
        return None
    return path


def _version(path: Optional[Path]) -> str:
    from app.core.http_files import content_version
    if path is None:
        return ""
    try:
        return content_version(path)
    except OSError:
        return ""


def _cache_dir() -> Path:
    from app.core import paths
    return paths.get_storage_dir() / ".cache" / "garment_mesh_view"


def _cache_files(key: str) -> Dict[str, Path]:
    folder = _cache_dir()
    return {"json": folder / f"{key}.json", "ghost": folder / f"{key}.ghost.glb",
            "inside": folder / f"{key}.inside.glb"}


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


# --- Pure parts (checked by the smoke) --------------------------------------------------------------------------------

def inside_faces(P, F, body_P, body_F, *, vox: float) -> Tuple[np.ndarray, float, float]:
    """``(inside mask per face, area share inside, face share inside)`` of the mesh ``(P, F)`` against the body
    ``(body_P, body_F)``, both in the body's frame: a face is inside when the body field (``garment_fit.body_sdf``,
    voxel ``vox``, zero level on the surface) is negative at its centroid. Degenerate faces count by number only."""
    from app.core.garment_fit import SDF_MARGIN_M, VOX_M, body_sdf, triangle_areas
    P = np.asarray(P, np.float64)
    F = np.asarray(F, np.int64).reshape(-1, 3)
    if len(F) == 0:
        return np.zeros(0, bool), 0.0, 0.0
    centroids = P[F].mean(axis=1)
    margin = SDF_MARGIN_M * vox / VOX_M
    sdf = body_sdf(np.asarray(body_P, np.float64), np.asarray(body_F, np.int64).reshape(-1, 3), vox=vox,
                   bounds=(centroids.min(0) - margin, centroids.max(0) + margin))
    mask = sdf.sample(centroids) < 0
    area = triangle_areas(P, F)
    total = float(area.sum())
    share = float(area[mask].sum() / total) if total > 0 else float(mask.mean())
    return mask, share, float(mask.mean())


def placement(P, F, body_P, masks) -> Tuple[float, np.ndarray]:
    """``(s, t)`` with ``Q = s·P + t``: the mesh ``(P, F)`` placed on the unrigged body ``body_P`` as the fit places
    it before its push (``garment_fit.fit_clothing``: welded, crumbs dropped, ``place_by_framing`` with ``masks``
    ``{"body", "garment"}``, ``align_band_depth``). Both steps are a uniform scale plus an offset, so ``(s, t)`` is
    read off the placed vertices."""
    from app.core import garment_fit as gf
    body_P = np.asarray(body_P, np.float64)
    Pw, Fw, _inv = gf.weld(P, F)
    Pk, _Fk, _keep = gf.drop_small(Pw, Fw)
    if len(Pk) < 2:
        raise ViewUnavailable("The mesh has no faces to place")
    body_mask, garment_mask = gf._mask(masks["body"]), gf._mask(masks["garment"])
    Q = gf.place_by_framing(Pk, body_P, body_mask, garment_mask)
    Q, _dz = gf.align_band_depth(Q, body_P, height_u=float(np.ptp(body_P[:, 1])))
    span = float(np.ptp(Pk[:, 1]))
    if not span > 0:
        raise ViewUnavailable("The mesh has no height to place")
    s = float(np.ptp(Q[:, 1]) / span)
    t = Q.mean(0) - s * Pk.mean(0)
    return s, t


def allowance_factors() -> Tuple[float, ...]:
    """Every width factor the fit allowance can apply (Ruling A47): 1.0, the settable choices
    (``garment_fit.ALLOWANCE_CHOICES`` in percent) and the automatic steps (``SCALE_RETRY_STEPS``), sorted —
    at most 16, so one 16-bit mask word per face holds them all (Ruling A76: nine since the choices reach +20 %)."""
    from app.core import garment_fit as gf
    out = {1.0} | {round(float(v), 4) for v in gf.SCALE_RETRY_STEPS}
    out |= {round(1.0 + float(c) / 100.0, 4) for c in gf.ALLOWANCE_CHOICES if c != "auto"}
    factors = tuple(sorted(out))
    assert len(factors) <= 16
    return factors


def widen_axis(P, F, s: float, t, body_P, body_r=None) -> Dict[str, float]:
    """The axis the fit widens about (``garment_fit.torso_axis`` on the placed welded mesh without its crumbs, half
    width ``CLOTHING_BODY_HALF_X`` of the body height — ``fit_clothing``'s ``scale_retry`` call), in the MESH's
    own frame (``(c - t) / s``, half width ``/ s``): ``{centre_x, centre_z, half_width}``; with the rigged body
    ``body_r`` also the depth allowance's frame (Ruling A68, ``fit_clothing``'s ``depth_shift`` arguments):
    ``ramp``, ``x_limit``, ``half_depth`` (lengths, ``/ s``) and ``y_limit`` (a height, ``(y - t_y) / s``)."""
    from app.core import garment_fit as gf
    body_P = np.asarray(body_P, np.float64)
    Pw, Fw, _inv = gf.weld(P, F)
    Pk, _Fk, _keep = gf.drop_small(Pw, Fw)
    height_u = float(np.ptp(body_P[:, 1]))
    t = np.asarray(t, np.float64)
    Q = Pk * s + t
    cx, cz = gf.torso_axis(Q, body_P, height_u=height_u)
    out = {"centre_x": float((cx - t[0]) / s), "centre_z": float((cz - t[2]) / s),
           "half_width": float(gf.CLOTHING_BODY_HALF_X * height_u / s)}
    if body_r is not None:
        x_limit, y_limit = gf.depth_limits(body_P, body_r, height_u=height_u)
        out.update(ramp=float(gf.DEPTH_RAMP * height_u / s), x_limit=float(x_limit / s),
                   y_limit=float((y_limit - t[1]) / s),
                   half_depth=float(gf.torso_half_depth(Q, body_P, height_u=height_u) / s))
    return out


def depth_frame_body(axis: Dict[str, float], s: float, t) -> Optional[Dict[str, float]]:
    """``garment_fit.depth_shift``'s frame in the BODY's frame from a mesh-frame ``axis`` (``widen_axis``), plus
    ``half_depth``; None without the depth fields."""
    if "x_limit" not in axis:
        return None
    t = np.asarray(t, np.float64)
    return {"centre_x": axis["centre_x"] * s + t[0], "centre_z": axis["centre_z"] * s + t[2],
            "x_limit": axis["x_limit"] * s, "y_limit": axis["y_limit"] * s + t[1], "ramp": axis["ramp"] * s,
            "half_depth": axis["half_depth"] * s}


def depth_gaps(Qb, sdf, frame: Dict[str, float], *, k: float, depths=None) -> list:
    """Per depth choice ``[front, back]``: the median gap (mm, ``sdf`` the body field) of the trunk-band vertices
    ``Qb`` (body frame, already widened) in front of / behind the trunk (``garment_fit.front_back_rows`` about
    ``(centre_x, centre_z)``, taken before the shift) after the depth shift (``garment_fit.depth_ease``) — before the
    fit's push-out, like the trunk gap; None for an empty sector."""
    from app.core import garment_fit as gf
    Qb = np.asarray(Qb, np.float64)
    depths = gf.DEPTH_CHOICES if depths is None else depths
    front, back = gf.front_back_rows(Qb, frame["centre_x"], frame["centre_z"])
    args = {key: frame[key] for key in ("centre_x", "centre_z", "x_limit", "y_limit", "ramp")}
    out = []
    for depth in depths:
        gap = sdf.sample(gf.depth_ease(Qb, depth / 100.0 * frame["half_depth"], **args)) * k * 1000.0 \
            if len(Qb) else np.zeros(0)
        out.append([round(float(np.median(gap[m])), 1) if m.any() else None for m in (front, back)])
    return out


def trunk_band_rows(Q, axis_body: Dict[str, float], trunk_y: Optional[Tuple[float, float]]) -> np.ndarray:
    """The rows of the placed vertices ``Q`` (body frame) the gap is read over: within the widening's half width of
    the axis in x (the part the allowance scales; a sleeve beyond it is only shifted) and, with ``trunk_y``
    ``(hips y, shoulder y)`` in the same frame, between them (``garment_fit.trunk_band``'s heights)."""
    Q = np.asarray(Q, np.float64)
    rows = np.abs(Q[:, 0] - axis_body["centre_x"]) <= axis_body["half_width"]
    if trunk_y is not None:
        rows &= (Q[:, 1] > trunk_y[0]) & (Q[:, 1] < trunk_y[1])
    return rows


def trunk_heights(body_u_P, body_r) -> Optional[Tuple[float, float]]:
    """``(hips y, lowest shoulder y)`` of the rigged body's joints carried to the unrigged body's frame by their
    share of the height (the two frames differ by the scale ``k`` and may differ in origin); None without them."""
    from app.core.rig_contract import norm_bone_name
    joints = {norm_bone_name(k): np.asarray(v, np.float64) for k, v in (body_r.joint_positions or {}).items()}
    hips = joints.get("hips")
    shoulders = [joints[k][1] for k in ("leftarm", "rightarm") if k in joints]
    if hips is None or not shoulders:
        return None
    yr = np.asarray(body_r.positions, np.float64)[:, 1]
    yu = np.asarray(body_u_P, np.float64)[:, 1]
    span_r, span_u = float(np.ptp(yr)), float(np.ptp(yu))
    if not (span_r > 0 and span_u > 0):
        return None
    to_u = lambda y: float(yu.min() + (y - yr.min()) / span_r * span_u)  # noqa: E731
    return to_u(float(hips[1])), to_u(float(min(shoulders)))


def allowance_table(P, F, body_P, body_F, *, s: float, t, axis: Dict[str, float], vox: float, k: float,
                    trunk_y: Optional[Tuple[float, float]] = None) -> Dict[str, Any]:
    """Per factor of ``allowance_factors`` the widened piece against the body (block above): ``{factors, steps
    [{factor, share, face_share, inside_faces, gap_p50_mm, gap_min_mm, depth_gaps}], depth {choices, ease_mm},
    band_vertices, union (mask of the faces inside at any factor), bits (per face, bit i = inside at factors[i])}``.
    ``P, F`` in the mesh frame, ``(s, t)`` the placement, ``axis`` in the mesh frame (``widen_axis``), ``k`` metres
    per body unit. ``depth_gaps`` (Ruling A68, ``depth_gaps``) only with the depth frame in ``axis``."""
    from app.core import garment_fit as gf
    P = np.asarray(P, np.float64)
    F = np.asarray(F, np.int64).reshape(-1, 3)
    t = np.asarray(t, np.float64)
    factors = allowance_factors()
    axis_body = {"centre_x": axis["centre_x"] * s + t[0], "centre_z": axis["centre_z"] * s + t[2],
                 "half_width": axis["half_width"] * s}
    Q = P * s + t
    frame = depth_frame_body(axis, s, t)

    def widened(X, f):
        return gf.widen(X, f, centre_x=axis_body["centre_x"], centre_z=axis_body["centre_z"],
                        half_width=axis_body["half_width"])
    Pw, _Fw, _inv = gf.weld(P, F)
    Qw = Pw * s + t
    rows = trunk_band_rows(Qw, axis_body, trunk_y)
    lo = np.minimum(Q.min(0), widened(Q, factors[-1]).min(0))
    hi = np.maximum(Q.max(0), widened(Q, factors[-1]).max(0))
    if frame is not None:
        # The field must reach the largest depth shift too (it samples clamped beyond its bounds).
        ease_max = max(gf.DEPTH_CHOICES) / 100.0 * frame["half_depth"]
        lo, hi = lo - np.array([0.0, 0.0, ease_max]), hi + np.array([0.0, 0.0, ease_max])
    margin = gf.SDF_MARGIN_M * vox / gf.VOX_M
    sdf = gf.body_sdf(np.asarray(body_P, np.float64), np.asarray(body_F, np.int64).reshape(-1, 3), vox=vox,
                      bounds=(lo - margin, hi + margin))
    area = None
    bits = np.zeros(len(F), np.uint16)
    steps = []
    for i, f in enumerate(factors):
        Qf = widened(Q, f)
        centroids = Qf[F].mean(axis=1) if len(F) else np.zeros((0, 3))
        mask = sdf.sample(centroids) < 0 if len(F) else np.zeros(0, bool)
        bits |= (mask.astype(np.uint16) << i)
        area = gf.triangle_areas(Qf, F)
        total = float(area.sum())
        share = float(area[mask].sum() / total) if total > 0 else (float(mask.mean()) if len(mask) else 0.0)
        band = widened(Qw[rows], f) if rows.any() else np.zeros((0, 3))
        gap = sdf.sample(band) * k * 1000.0 if rows.any() else np.zeros(0)
        step = {"factor": f, "share": round(share, 4),
                "face_share": round(float(mask.mean()) if len(mask) else 0.0, 4),
                "inside_faces": int(mask.sum()),
                "gap_p50_mm": round(float(np.median(gap)), 1) if len(gap) else None,
                "gap_min_mm": round(float(gap.min()), 1) if len(gap) else None}
        if frame is not None:
            step["depth_gaps"] = depth_gaps(band, sdf, frame, k=k)
        steps.append(step)
    out = {"factors": list(factors), "steps": steps, "band_vertices": int(rows.sum()), "union": bits > 0,
           "bits": bits}
    if frame is not None:
        out["depth"] = {"choices": list(gf.DEPTH_CHOICES),
                        "ease_mm": [round(c / 100.0 * frame["half_depth"] * k * 1000.0, 1) for c in gf.DEPTH_CHOICES]}
    return out


def overlay_glb(P, F, rgba, *, name: str) -> bytes:
    """A static GLB of the faces ``F`` over ``P`` (only the vertices they use), one flat colour, double-sided."""
    from app.core.glb_mesh import static_glb
    P = np.asarray(P, np.float64)
    F = np.asarray(F, np.int64).reshape(-1, 3)
    used, inverse = np.unique(F.ravel(), return_inverse=True)
    return static_glb(P[used], inverse.reshape(-1, 3), np.zeros((len(used), 2)),
                      material={"name": name, "doubleSided": True,
                                "pbrMetallicRoughness": {"baseColorFactor": list(rgba), "metallicFactor": 0.0,
                                                         "roughnessFactor": 0.9}},
                      name=name)


# --- The view ---------------------------------------------------------------------------------------------------------

def _inputs(character_name: str, item_id: str, which: str, attempt: int) -> Dict[str, Any]:
    """The files the view of ``which`` / ``attempt`` is made from and its cache key. ``LookupError`` without the
    mesh file, ``ViewUnavailable`` without a base model or a ghost front."""
    from app.core import base_body, garment_source
    from app.core import garment_store as gs
    from app.core.model_refs import find_ref_image
    from app.models.character import get_character_dir
    mesh = mesh_file(character_name, item_id, which, attempt)
    if mesh is None:
        raise LookupError("No such mesh")
    fsig = current_fsig(character_name, item_id)
    base = base_body.current_base(character_name)
    if base is None or not base[1]:
        raise ViewUnavailable("No base model yet — the body cannot be shown")
    bsig = base[0]
    model_dir = get_character_dir(character_name) / "model3d"
    unrigged = model_dir / "unrigged" / f"{bsig}.glb"
    rigged = model_dir / f"{bsig}.glb"
    front = find_ref_image(character_name, base_body._kind("front"), bsig)
    if front is None:
        raise ViewUnavailable("The base front view is missing — the piece cannot be placed on the body")
    ghost = gs.garment_path(character_name, item_id, fsig, "image", step="ghost", view="front")
    if not ghost.is_file():
        raise ViewUnavailable("No piece-only front view — the piece cannot be placed on the body")
    copy = garment_source.base_copy(character_name, item_id, fsig, "front")
    versions = [_version(p) for p in (mesh, unrigged, rigged, Path(front), ghost)]
    if not all(versions[1:3]):
        raise ViewUnavailable("No base model yet — the body cannot be shown")
    raw = f"a48a-v{VIEW_VERSION}|{'|'.join(versions)}|{_version(copy if copy.is_file() else None)}"
    return {"mesh": mesh, "fsig": fsig, "bsig": bsig, "front": Path(front), "versions": versions,
            "key": hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]}


def _compute(character_name: str, item_id: str, inputs: Dict[str, Any]) -> Dict[str, Any]:
    """Place the mesh, test its faces against the body field, write the JSON and the two overlays."""
    from app.core import base_body, garment_fit, garment_source
    from app.core.glb_mesh import body_arrays, static_arrays
    from app.core.timeutils import utc_now_iso
    started = time.monotonic()
    _count("computes")
    snapshot = base_body._snapshot_base_model(character_name, inputs["bsig"])
    body_u, body_r = body_arrays(snapshot["unrigged"]), body_arrays(snapshot["rigged"])
    height_u = float(np.ptp(body_u.positions[:, 1]))
    height_r = float(np.ptp(body_r.positions[:, 1]))
    k = height_r / height_u if height_u > 0 else float("nan")
    if not (k > 0 and np.isfinite(k)):
        raise ViewUnavailable("The base model's height cannot be measured")
    try:
        body_mask, ghost_mask, _frame = garment_source.fit_masks(character_name, item_id, inputs["fsig"],
                                                                 body_front=inputs["front"],
                                                                 base_front=inputs["front"])
    except garment_source.FrameRefused as e:
        raise ViewUnavailable(f"The piece cannot be placed on this body: {e}")
    P, F, _U, _image, _mime, _material = static_arrays(inputs["mesh"].read_bytes())
    s, t = placement(P, F, body_u.positions, {"body": body_mask, "garment": ghost_mask})
    vox = garment_fit.VOX_M / k
    mask, share, face_share = inside_faces(P * s + t, F, body_u.positions, body_u.faces, vox=vox)
    # Ruling A48c: the allowance table; the red overlay holds the faces inside at ANY factor, ``mask`` names which.
    axis = widen_axis(P, F, s, t, body_u.positions, body_r)
    table = allowance_table(P, F, body_u.positions, body_u.faces, s=s, t=t, axis=axis, vox=vox, k=k,
                            trunk_y=trunk_heights(body_u.positions, body_r))
    union = table.pop("union") | mask
    bits = table.pop("bits")[union]
    files = _cache_files(inputs["key"])
    _write_atomic(files["ghost"], overlay_glb((body_u.positions - t) / s, body_u.faces, GHOST_RGBA, name="body"))
    if union.any():
        _write_atomic(files["inside"], overlay_glb(P, F[union], INSIDE_RGBA, name="inside"))
    allowance = {"axis": axis, **table, "mask_faces": int(union.sum()),
                 "mask": base64.b64encode(bits.astype("<u2").tobytes()).decode("ascii")}
    result = {"key": inputs["key"], "share": round(share, 4), "face_share": round(face_share, 4),
              "faces": int(len(F)), "inside_faces": int(mask.sum()), "bsig": inputs["bsig"],
              "placement": {"scale": s, "offset": [float(v) for v in t], "k": float(k)},
              "allowance": allowance,
              "computed_at": utc_now_iso(), "seconds": round(time.monotonic() - started, 2)}
    _write_atomic(files["json"], json.dumps(result).encode("utf-8"))
    logger.info("Mesh view %s/%s %s: %d of %d faces inside the body (%.1f %% of the area) in %.1f s",
                character_name, item_id, inputs["mesh"].name, result["inside_faces"], result["faces"],
                share * 100, result["seconds"])
    return result


def _cached(key: str) -> Optional[Dict[str, Any]]:
    files = _cache_files(key)
    try:
        result = json.loads(files["json"].read_text("utf-8"))
    except (OSError, ValueError):
        return None
    if not files["ghost"].is_file() or (((result.get("allowance") or {}).get("mask_faces") or result.get("inside_faces"))
                                        and not files["inside"].is_file()):
        return None
    return result


def body_view(character_name: str, item_id: str, which: str, attempt: int = 0) -> Dict[str, Any]:
    """The body view of the mesh ``which`` / ``attempt``: ``{key, share, face_share, faces, inside_faces, bsig,
    placement {scale, offset, k}, allowance {axis, factors, steps, depth, band_vertices, mask_faces, mask}, computed_at,
    seconds}`` — from the cache, or computed now (blocking; Blender is
    not involved, the body field is numpy). ``LookupError`` without the mesh, ``ViewUnavailable`` when the body
    cannot be shown, ValueError for a bad ``which`` / attempt / item."""
    from app.core.keyed_lock import keyed_lock
    inputs = _inputs(character_name, item_id, which, attempt)
    key = inputs["key"]
    hit = _cached(key)
    if hit is not None:
        _count("hits")
        return hit
    with keyed_lock("garment_mesh_view", key):
        hit = _cached(key)
        if hit is not None:
            _count("hits")
            return hit
        return _compute(character_name, item_id, inputs)


def overlay_path(character_name: str, item_id: str, which: str, attempt: int, overlay: str) -> Optional[Path]:
    """The cached overlay GLB (``ghost`` / ``inside``) of the CURRENT view of ``which`` / ``attempt`` — computed
    first when it is not cached — or None (no inside faces). Raises like ``body_view``."""
    if overlay not in OVERLAYS:
        raise ValueError(f"overlay must be one of {', '.join(OVERLAYS)}")
    result = body_view(character_name, item_id, which, attempt)
    path = _cache_files(result["key"])[overlay]
    return path if path.is_file() else None
