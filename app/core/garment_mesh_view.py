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

Computed once per input set and cached on disk under ``<storage>/.cache/garment_mesh_view/<key>.{json,ghost.glb,
inside.glb}`` — ``key`` is a hash of ``VIEW_VERSION`` and the content versions of the mesh file, both base models,
the bald front view, the ghost front and the group's base copy (the inputs of the placement and the field). A key
is computed under ``keyed_lock("garment_mesh_view", key)``, so a second asker waits for the first and reads its
files. ``_INFO`` counts computations and cache hits (``scripts/smoke_garment_mesh_view.py``).
"""
from __future__ import annotations

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
#: Stamped into the cache key: a change of the placement or the inside rule computes every view again.
VIEW_VERSION = 1
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
    mask, share, face_share = inside_faces(P * s + t, F, body_u.positions, body_u.faces, vox=garment_fit.VOX_M / k)
    files = _cache_files(inputs["key"])
    _write_atomic(files["ghost"], overlay_glb((body_u.positions - t) / s, body_u.faces, GHOST_RGBA, name="body"))
    if mask.any():
        _write_atomic(files["inside"], overlay_glb(P, F[mask], INSIDE_RGBA, name="inside"))
    result = {"key": inputs["key"], "share": round(share, 4), "face_share": round(face_share, 4),
              "faces": int(len(F)), "inside_faces": int(mask.sum()), "bsig": inputs["bsig"],
              "placement": {"scale": s, "offset": [float(v) for v in t], "k": float(k)},
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
    if not files["ghost"].is_file() or (result.get("inside_faces") and not files["inside"].is_file()):
        return None
    return result


def body_view(character_name: str, item_id: str, which: str, attempt: int = 0) -> Dict[str, Any]:
    """The body view of the mesh ``which`` / ``attempt``: ``{key, share, face_share, faces, inside_faces, bsig,
    placement {scale, offset, k}, computed_at, seconds}`` — from the cache, or computed now (blocking; Blender is
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
