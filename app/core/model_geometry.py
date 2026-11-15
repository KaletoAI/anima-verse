"""Geometry identity of a rigged base model (Ruling A107).

A dependant of the base model that reads only its SHAPE — a garment / hair / own-mesh fit, a HAAR strand
verdict, a refused-fit record, an outfit body's posture match — must not go stale when only the model's
PIXELS change (face retexture, the matte floor of ``base_mesh_repair``, a refine that re-encodes a texture).
The file sha256 changes with every byte, so those dependants carry a GEOMETRY ID next to it.

What the geometry is (``descriptor``): the body mesh only (nodes that are not garment nodes) — every vertex's
``POSITION`` and skin weights by joint NAME, the triangles as sets of welded positions, and the skin's inverse
bind matrices by joint name. NOT in it: images, textures, materials and their factors, ``TEXCOORD_*``,
``NORMAL``, ``TANGENT``, ``COLOR_*``, morph targets, extras, vertex order, triangle order, the split of the
triangles into primitives.

Why not a plain hash: a face retexture today re-runs the rig chain on a new unrigged source whose only change
is the face texture; the rigged result has the same vertices, weights and bind matrices, but its export moves
the face triangles into a primitive of their own material, reorders vertices and leaves float noise of
~2e-7 m in positions (measured on a stored base, A107 report). An exact hash would flip; ``equivalent``
compares within ``POSITION_TOL_M`` / ``WEIGHT_TOL`` / ``BIND_TOL`` instead.

The LINEAGE (``lineage_id``): per character and base signature, ``model3d/geometry/<bsig>.json`` =
``{version, geometry_id, files: {file sha256: geometry id}}`` (``geometry_id`` = the id of the file judged
last) and ``<bsig>/<id>.npz`` = the descriptor of each of the last ``_IDS_KEPT`` ids. A base file not seen yet
is judged ONCE against those descriptors: equivalent to one → it gets that id, else it starts a new id (``"g"`` + 16 hex of a canonical hash of its descriptor). The judgement is
cached by file sha, so a file is read once per content.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

#: Bump when ``descriptor`` / ``equivalent`` change meaning: every lineage is judged anew.
GEOMETRY_VERSION = 1
POSITION_TOL_M = 1e-4      # 0.1 mm — export float noise is ~2e-7 m, a tip smoothing moves mm
WEIGHT_TOL = 2e-3          # a weight stored as u8 / u16 / float hashes within this
BIND_TOL = 1e-4
_FILES_KEPT = 64
_IDS_KEPT = 4             # descriptors kept per base signature (a file is compared with each)

_lock = threading.Lock()
_by_file_sha: Dict[str, str] = {}


# --- descriptor ------------------------------------------------------------------------------------------------

def descriptor(glb: bytes) -> Dict[str, Any]:
    """The geometry of the body mesh of GLB bytes (module doc): ``positions`` (n, 3) f4, the skin weights as
    ``weight_joints`` (n, 4) column indices into ``joints`` (k names, sorted) + ``weight_values`` (n, 4) f4, ``triangles`` (m, 3) of welded-position labels sorted per row and over
    rows, ``welded`` (w, 3) f4 the welded positions (sorted rows), ``binds`` (k, 4, 4) f4 the inverse bind
    matrices in ``joints`` order (zeros for a joint without one). ValueError when the bytes hold no skinned
    body mesh this reader decodes."""
    from app.core.glb_mesh import COMPRESSION_EXTENSIONS, _is_garment_node, accessor_array, mat4_array
    from app.core.model_validate import parse_glb
    parsed = parse_glb(glb)
    gltf = parsed["gltf"]
    used = set(gltf.get("extensionsUsed") or []) | set(gltf.get("extensionsRequired") or [])
    if used.intersection(COMPRESSION_EXTENSIONS):
        raise ValueError("compressed geometry")
    nodes = gltf.get("nodes") or []
    names = [str(n.get("name") or "") for n in nodes]
    skins = gltf.get("skins") or []
    if not skins:
        raise ValueError("no skin")
    skin_joints = [names[j] for j in skins[0].get("joints") or []]
    joints = sorted(set(skin_joints))
    column = {name: joints.index(name) for name in joints}
    binds = np.zeros((len(joints), 4, 4), np.float32)
    if "inverseBindMatrices" in skins[0]:
        for name, matrix in zip(skin_joints, mat4_array(parsed, skins[0]["inverseBindMatrices"])):
            binds[column[name]] = matrix
    meshes = sorted({n["mesh"] for n in nodes if "mesh" in n and not _is_garment_node(n)})
    positions, weights, triangles, offset = [], [], [], 0
    for m in meshes:
        for prim in gltf["meshes"][m].get("primitives") or []:
            attrs = prim.get("attributes") or {}
            if prim.get("mode", 4) != 4 or "POSITION" not in attrs:
                continue
            pos = np.asarray(accessor_array(parsed, attrs["POSITION"]), np.float32)
            dense = np.zeros((len(pos), max(len(joints), 1)), np.float32)
            if "JOINTS_0" in attrs and "WEIGHTS_0" in attrs:
                ji = np.asarray(accessor_array(parsed, attrs["JOINTS_0"]), np.int64)
                w = np.asarray(accessor_array(parsed, attrs["WEIGHTS_0"]), np.float64)
                to_column = np.array([column[name] for name in skin_joints] or [0], np.int64)
                cols = to_column[np.clip(ji, 0, len(to_column) - 1)]
                np.add.at(dense, (np.repeat(np.arange(len(pos)), ji.shape[1]), cols.reshape(-1)),
                          w.reshape(-1).astype(np.float32))
            flat = (accessor_array(parsed, prim["indices"]).reshape(-1).astype(np.int64)
                    if "indices" in prim else np.arange(len(pos), dtype=np.int64))
            positions.append(pos)
            weights.append(dense)
            triangles.append(flat[: len(flat) // 3 * 3].reshape(-1, 3) + offset)
            offset += len(pos)
    if not positions:
        raise ValueError("no body mesh")
    positions_all = np.concatenate(positions)
    welded, labels = np.unique(positions_all, axis=0, return_inverse=True)
    tris = np.sort(labels.reshape(-1)[np.concatenate(triangles)], axis=1)
    tris = tris[np.lexsort(tris.T[::-1])]
    dense_all = np.concatenate(weights)
    # Sparse: the 4 strongest joints per vertex (glTF carries at most 4 in JOINTS_0), by column.
    top = np.argsort(-dense_all, axis=1, kind="stable")[:, :4]
    top = np.sort(top, axis=1)
    return {"positions": positions_all, "weight_joints": top.astype(np.int16),
            "weight_values": np.take_along_axis(dense_all, top, axis=1).astype(np.float32),
            "joints": np.array(joints),
            "triangles": tris.astype(np.int64), "welded": welded.astype(np.float32), "binds": binds}


def canonical_id(desc: Dict[str, Any]) -> str:
    """``"g"`` + 16 hex: a hash of the descriptor (positions rounded to 0.1 mm) — the id a NEW geometry starts
    its lineage with. Two equivalent descriptors may hash apart; ``lineage_id`` never compares ids of two
    files by hash, only by ``equivalent``."""
    h = hashlib.sha256(f"geometry-v{GEOMETRY_VERSION}".encode())
    h.update(np.rint(np.asarray(desc["welded"], np.float64) / POSITION_TOL_M).astype("<i8").tobytes())
    h.update(np.ascontiguousarray(desc["triangles"], "<i8").tobytes())
    h.update("|".join(str(j) for j in desc["joints"]).encode())
    return "g" + h.hexdigest()[:16]


def _dense(desc: Dict[str, Any]) -> np.ndarray:
    n, k = len(desc["positions"]), max(len(desc["joints"]), 1)
    out = np.zeros((n, k), np.float32)
    np.put_along_axis(out, desc["weight_joints"].astype(np.int64), desc["weight_values"], axis=1)
    return out


def equivalent(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """Whether two descriptors describe the same skinned body within the tolerances (module doc): same joint
    names, bind matrices within ``BIND_TOL``, the same number of welded positions and triangles, every vertex of
    each within ``POSITION_TOL_M`` of a vertex of the other with weights within ``WEIGHT_TOL``, and the same
    triangles over the welded positions."""
    from scipy.spatial import cKDTree
    if list(a["joints"]) != list(b["joints"]):
        return False
    if a["binds"].shape != b["binds"].shape or np.abs(a["binds"] - b["binds"]).max(initial=0.0) > BIND_TOL:
        return False
    if len(a["triangles"]) != len(b["triangles"]) or len(a["welded"]) != len(b["welded"]):
        return False
    # Both ways: a vertex copied at a primitive split has a twin, never a vertex without a counterpart.
    for one, other in ((a, b), (b, a)):
        dist, nearest = cKDTree(other["positions"]).query(one["positions"])
        if float(dist.max(initial=0.0)) > POSITION_TOL_M:
            return False
        if float(np.abs(_dense(one) - _dense(other)[nearest]).max(initial=0.0)) > WEIGHT_TOL:
            return False
    wdist, wlabel = cKDTree(b["welded"]).query(a["welded"])
    if float(wdist.max(initial=0.0)) > POSITION_TOL_M:
        return False
    mapped = np.sort(wlabel[a["triangles"]], axis=1)
    mapped = mapped[np.lexsort(mapped.T[::-1])]
    return bool(np.array_equal(mapped, b["triangles"]))


def _save_desc(path: Path, desc: Dict[str, Any]) -> None:
    buffer = io.BytesIO()
    np.savez_compressed(buffer, **desc)
    tmp = path.with_suffix(".npz.tmp")
    tmp.write_bytes(buffer.getvalue())
    tmp.replace(path)


def _load_desc(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with np.load(path, allow_pickle=False) as data:
            return {key: data[key] for key in data.files}
    except Exception:  # noqa: BLE001 — a missing or broken descriptor starts a new lineage
        return None


# --- lineage ---------------------------------------------------------------------------------------------------

def lineage_dir(character_name: str) -> Path:
    from app.models.character import get_character_dir
    return get_character_dir(character_name) / "model3d" / "geometry"


def _read_lineage(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) and data.get("version") == GEOMETRY_VERSION else {}


def lineage_id(character_name: str, bsig: str, model: Path, file_sha: str) -> str:
    """The geometry id of the base model ``model`` (content ``file_sha``) of ``bsig`` (module doc); "" when
    it cannot be judged (unreadable, no skinned body). Writes ``model3d/geometry/`` only when the model file
    exists. Never raises."""
    if not file_sha:
        return ""
    with _lock:
        hit = _by_file_sha.get(file_sha)
    if hit:
        return hit
    from app.core.keyed_lock import keyed_lock
    try:
        folder = lineage_dir(character_name)
        with keyed_lock("model_geometry", f"{character_name}:{bsig}"):
            record_path = folder / f"{bsig}.json"
            record = _read_lineage(record_path)
            files = dict(record.get("files") or {})
            gid = str(files.get(file_sha) or "")
            if not gid:
                if not model.is_file():
                    return ""
                data = model.read_bytes()
                if hashlib.sha256(data).hexdigest() != file_sha:
                    return ""  # the file moved on meanwhile; the next call judges the new one
                desc = descriptor(data)
                for known in _known_ids(folder, bsig):
                    stored = _load_desc(folder / bsig / f"{known}.npz")
                    if stored is not None and equivalent(desc, stored):
                        gid = known
                        break
                if not gid:
                    gid = canonical_id(desc)
                    (folder / bsig).mkdir(parents=True, exist_ok=True)
                    _save_desc(folder / bsig / f"{gid}.npz", desc)
                    for old in _known_ids(folder, bsig)[_IDS_KEPT:]:
                        (folder / bsig / f"{old}.npz").unlink(missing_ok=True)
                files[file_sha] = gid
                if len(files) > _FILES_KEPT:
                    files = dict(list(files.items())[-_FILES_KEPT:])
                folder.mkdir(parents=True, exist_ok=True)
                tmp = record_path.with_suffix(".json.tmp")
                tmp.write_text(json.dumps({"version": GEOMETRY_VERSION, "geometry_id": gid, "files": files},
                                          indent=2, sort_keys=True), encoding="utf-8")
                tmp.replace(record_path)
        register(file_sha, gid)
        return gid
    except Exception as exc:  # noqa: BLE001 — without an id the file sha alone decides
        logger.warning("Geometry id of %s (%s) failed: %s", character_name, bsig, exc)
        return ""


def _known_ids(folder: Path, bsig: str) -> List[str]:
    """The geometry ids of ``bsig`` with a stored descriptor, newest first."""
    try:
        files = sorted((folder / bsig).glob("g*.npz"), key=lambda p: p.stat().st_mtime_ns, reverse=True)
    except OSError:
        return []
    return [p.stem for p in files]


def descriptor_of(character_name: str, bsig: str, geometry_id: str) -> Optional[Dict[str, Any]]:
    """The stored descriptor of the geometry id ``geometry_id`` of ``bsig`` (None without one)."""
    if not geometry_id:
        return None
    return _load_desc(lineage_dir(character_name) / bsig / f"{geometry_id}.npz")


# --- file sha -> geometry id ------------------------------------------------------------------------------------

def register(file_sha: str, geometry_id: str) -> None:
    """Remember that the base file of content ``file_sha`` has the geometry ``geometry_id``."""
    if file_sha and geometry_id:
        with _lock:
            _by_file_sha[file_sha] = geometry_id


def of_file_sha(file_sha: str) -> str:
    """The geometry id of a base file content judged in this process, "" when unknown."""
    with _lock:
        return _by_file_sha.get(file_sha or "", "")


def same_geometry(recorded_sha: Optional[str], recorded_geometry: Optional[str], current_sha: str) -> bool:
    """Whether a record made on the base of content ``recorded_sha`` (its geometry id ``recorded_geometry``,
    "" when the record has none) holds on the base of content ``current_sha``: the same file, or — the record
    carrying a geometry id — the same geometry. False without ``current_sha``."""
    if not current_sha:
        return False
    if recorded_sha and recorded_sha == current_sha:
        return True
    current = of_file_sha(current_sha)
    return bool(recorded_geometry) and bool(current) and recorded_geometry == current


#: The record field every geometry-only dependant of the base model carries next to ``base_model_sha256``.
FIELD = "base_geometry_id"


def record_matches(record: Dict[str, Any], current_sha: str, *, sha_key: str = "base_model_sha256") -> bool:
    """``same_geometry`` for a record that names its base by ``sha_key`` and ``FIELD``."""
    return same_geometry(str(record.get(sha_key) or ""), str(record.get(FIELD) or ""), current_sha)


def stamp(file_sha: str) -> Dict[str, str]:
    """``{FIELD: id}`` for a record made on the base of content ``file_sha`` ({} when its id is unknown)."""
    gid = of_file_sha(file_sha)
    return {FIELD: gid} if gid else {}


def stamp_on(character_name: str, bsig: str, file_sha: str) -> Dict[str, str]:
    """``stamp`` for a record made on base ``bsig`` of content ``file_sha``: the stored base of ``bsig`` is
    judged first (``base_body.base_model_sha256``), so a record written right after a rewrite gets its id."""
    if file_sha and not of_file_sha(file_sha) and bsig:
        from app.core.base_body import base_model_sha256
        base_model_sha256(character_name, bsig)
    return stamp(file_sha)
