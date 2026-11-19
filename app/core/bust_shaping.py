"""A228 — a shaping bodice lifts and gathers the chest under it (push-up / corset).

A template top or dress whose ``outfit_piece.lift`` (the "Lift" slider, 0..1) is above zero shapes the BODY under it
before it is draped: the chest tissue in front of the chest wall is lifted ``LIFT_M`` x lift and its protrusion is
compressed by ``COMPRESS`` x lift. The cloth then drapes over the shaped body (``garment_template._build_drape``
drapes on a shaped copy of the plain body), and the assembly of a worn set that holds the piece moves the shown body
the same way (``garment_assembly``), so the figure under the piece, the skin the piece leaves open and the drape agree.
Only positions move: faces, UVs, skin weights and morph targets stay, so the skinning is the plain body's. The bare
body file is never changed — the shaping exists only in a drape's scratch copy and in an assembled worn set.

The displacement is a pure function of a vertex's position (bind space, glTF Y-up, front = +Z) and the
``landmarks`` measured once on the plain body, so the full and the low tier (different vertices) shape alike.

    p   = z - wall(x)                              (protrusion in front of the chest wall, ``wall_at``)
    w_p = smoothstep(p; 0, PROTRUSION_FULL_M)
    w_v = smoothstep(y; under_y - BELOW_M, under_y + RISE_M) * (1 - smoothstep(y; band_y, band_y + ABOVE_M))
    w_x = 1 - smoothstep(|x - centre_x|; SIDE_M[0], SIDE_M[1])
    w   = lift * min(1, depth_m / FULL_DEPTH_M) * w_p * w_v * w_x
    y'  = y + LIFT_M * w
    z'  = z - COMPRESS * w * max(p, 0)

The ramps are gentle enough that the map never folds: d y'/dy >= 1 - LIFT_M * 1.5 / ABOVE_M and
d z'/dz >= 1 - COMPRESS * (1 + 8/9) (both > 0; ``scripts/smoke_bust_shaping.py`` derives them).
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Optional

import numpy as np

#: Bump when the field changes: it is part of every shaped drape's key.
VERSION = 1
#: The lift of the chest tissue at lift 1 (metres, upward).
LIFT_M = 0.05
#: The share of the protrusion in front of the chest wall taken away at lift 1.
COMPRESS = 0.5
#: The chest depth (``landmarks`` ``depth_m``: the largest protrusion in front of the chest wall between the
#: underbust line and the band) from which the shaping is full; a shallower chest takes the share it has.
FULL_DEPTH_M = 0.10
#: The protrusion at which a vertex takes the full shaping (metres).
PROTRUSION_FULL_M = 0.02
#: The vertical ramps round the underbust line and above the chest band (metres).
BELOW_M = 0.03
RISE_M = 0.02
ABOVE_M = 0.08
#: The sideways fade from the body's middle (metres): full inside the first, none beyond the second.
SIDE_M = (0.17, 0.21)
#: The kinds of template piece that shape the chest.
SHAPING_KINDS = ("top", "dress")
#: The chest-wall bins (``landmarks``): this wide, this many from the middle out.
WALL_STEP_M = 0.02
WALL_BINS = 11
WALL_SLICE_M = 0.005


def _smoothstep(v, a: float, b: float):
    t = np.clip((np.asarray(v, np.float64) - a) / (b - a), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def lift_of(item: Optional[Dict[str, Any]]) -> float:
    """The piece's ``outfit_piece.lift`` (0 when absent or invalid)."""
    try:
        value = float(((item or {}).get("outfit_piece") or {}).get("lift") or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return min(1.0, max(0.0, value)) if np.isfinite(value) else 0.0


def applies(params: Optional[Dict[str, Any]], lift: float) -> bool:
    """Whether a template piece with ``params`` and ``lift`` shapes the chest under it."""
    return bool(params) and params.get("kind") in SHAPING_KINDS and lift > 0.0


def bust_lines(meas: Dict[str, Any]):
    """``(underbust_y, bust_y)`` off the torso profile of ``garment_template.measure_body``: the bust line is the
    widest torso slice between the waist + 5 cm and the chest band; the underbust line the narrowest 4..14 cm under it.
    Without a profile: the band less 15 / 7 cm."""
    prof = [p for p in meas.get("torso") or [] if meas["waist_y"] + 0.05 <= p[0] <= meas["band_y"]]
    if len(prof) < 3:
        return meas["band_y"] - 0.15, meas["band_y"] - 0.07
    bust_y = max(prof, key=lambda p: p[1])[0]
    under = [p for p in meas.get("torso") or [] if bust_y - 0.14 <= p[0] <= bust_y - 0.04]
    return (min(under, key=lambda p: p[1])[0] if under else bust_y - 0.08), bust_y


def landmarks(positions, meas: Dict[str, Any]) -> Dict[str, float]:
    """The plain body's chest landmarks (glTF Y-up metres): ``under_y`` / ``bust_y`` (``bust_lines``),
    ``band_y``, ``depth_m`` (``FULL_DEPTH_M``), ``centre_x`` (the spine's x) and ``wall_z`` = the front of the chest wall per ``WALL_STEP_M`` of distance from
    the middle: the most forward point of the 2 cm slice at the underbust line in that bin (+- half a bin, both
    sides; ``WALL_SLICE_M`` thick) — under the chest the slice is the rib cage, so the side of the chest protrudes from
    it as the front does. A bin past the rib cage's side holds the last one."""
    P = np.asarray(positions, np.float64)
    under_y, bust_y = bust_lines(meas)
    centre_x = float(((meas.get("joints") or {}).get("spine2") or [0.0])[0])
    sl = P[(np.abs(P[:, 1] - under_y) < WALL_SLICE_M) & (np.abs(P[:, 0] - centre_x) < WALL_BINS * WALL_STEP_M)]
    wall: list = []
    for k in range(WALL_BINS):
        d = np.abs(sl[:, 0] - centre_x)
        near = sl[(d >= k * WALL_STEP_M) & (d < (k + 1) * WALL_STEP_M)]
        wall.append(float(near[:, 2].max()) if len(near) else None)
    known = [k for k, w in enumerate(wall) if w is not None]
    if not known:
        raise ValueError("the body has no chest wall at the underbust line")
    # past the rib cage's side the last bin holds (a falling extrapolation reached the flanks and the back)
    for k in range(WALL_BINS):
        if wall[k] is None:
            wall[k] = wall[known[0]] if k < known[0] else wall[known[-1]]
    wall = [round(float(w), 4) for w in wall]
    lm = {"centre_x": centre_x, "wall_z": wall}
    region = (P[:, 1] > under_y) & (P[:, 1] < float(meas["band_y"])) & (np.abs(P[:, 0] - centre_x) < SIDE_M[0])
    depth = float((P[region, 2] - wall_at(P[region, 0], lm)).max()) if region.any() else 0.0
    return {"under_y": round(float(under_y), 4), "bust_y": round(float(bust_y), 4),
            "band_y": round(float(meas["band_y"]), 4), "centre_x": round(centre_x, 4), "wall_z": wall,
            "depth_m": round(max(0.0, depth), 4)}


def wall_at(x, lm: Dict[str, float]) -> np.ndarray:
    """The chest wall's front ``z`` at ``x``: ``wall_z`` (one value per ``WALL_STEP_M`` of distance from the middle,
    bin centres) interpolated, the last bin held beyond."""
    wall = lm["wall_z"]
    if not isinstance(wall, (list, tuple)):
        return np.full(np.shape(x), float(wall))
    centres = (np.arange(len(wall)) + 0.5) * WALL_STEP_M
    return np.interp(np.abs(np.asarray(x, np.float64) - lm["centre_x"]), centres, np.asarray(wall, np.float64))


def weights(positions, lm: Dict[str, float], lift: float) -> np.ndarray:
    """``w`` of the module docstring per vertex."""
    P = np.asarray(positions, np.float64)
    p = P[:, 2] - wall_at(P[:, 0], lm)
    w_p = _smoothstep(p, 0.0, PROTRUSION_FULL_M)
    w_v = (_smoothstep(P[:, 1], lm["under_y"] - BELOW_M, lm["under_y"] + RISE_M)
           * (1.0 - _smoothstep(P[:, 1], lm["band_y"], lm["band_y"] + ABOVE_M)))
    w_x = 1.0 - _smoothstep(np.abs(P[:, 0] - lm["centre_x"]), SIDE_M[0], SIDE_M[1])
    return strength(lm, lift) * w_p * w_v * w_x


def strength(lm: Dict[str, float], lift: float) -> float:
    """``lift`` x min(1, ``depth_m`` / ``FULL_DEPTH_M``): a small chest is lifted and gathered less."""
    return float(lift) * min(1.0, float(lm.get("depth_m", FULL_DEPTH_M)) / FULL_DEPTH_M)


def displace(positions, lm: Dict[str, float], lift: float) -> np.ndarray:
    """The shaped positions (module docstring); vertices outside the chest region come back unchanged."""
    P = np.array(positions, np.float64, copy=True)
    w = weights(P, lm, lift)
    p = np.maximum(P[:, 2] - wall_at(P[:, 0], lm), 0.0)
    P[:, 1] += LIFT_M * w
    P[:, 2] -= COMPRESS * w * p
    return P


def record(lm: Dict[str, float], lift: float) -> Dict[str, Any]:
    """What a drape record keeps (``shaping``) and the assembly re-applies."""
    return {"version": VERSION, "lift": round(float(lift), 4), "landmarks": dict(lm)}


def signature(params: Optional[Dict[str, Any]], lift: float) -> Optional[str]:
    """The drape-key token of the shaping (None when the piece does not shape): a changed lift re-drapes."""
    if not applies(params, lift):
        return None
    raw = json.dumps({"v": VERSION, "lift": round(float(lift), 4)}, sort_keys=True)
    return "shape:" + hashlib.md5(raw.encode("utf-8")).hexdigest()[:8]


def shape_glb(blob: bytes, rec: Dict[str, Any]) -> bytes:
    """``blob`` (a body GLB, or an assembled one) with every skinned non-garment primitive — the body and its
    extension parts alike, a part that stayed where it was would stand through the piece — shaped by ``rec``
    (``record``). The POSITION (and NORMAL, recomputed for the faces touching a moved vertex) bytes are overwritten
    in place, so the buffer layout, skin, UVs and morph targets stay byte-identical; the accessors' min/max follow.
    The skin joints whose bind position lies in the shaped region move with the tissue (``_shape_joints``): a chest
    bone left at its old place would stand outside the shaped surface, and the extension motion would swing the
    tissue round a point in front of it.
    Returns ``blob`` unchanged when nothing moves."""
    import struct
    from app.core import glb_mesh
    if len(blob) < 20 or blob[:4] != b"glTF":
        raise ValueError("not a GLB")
    jlen = struct.unpack_from("<I", blob, 12)[0]
    gltf = json.loads(blob[20:20 + jlen].decode("utf-8"))
    bin_at = 20 + jlen + 8
    bin_len = struct.unpack_from("<I", blob, 20 + jlen)[0]
    data = bytearray(blob[bin_at:bin_at + bin_len])
    lm, lift = rec["landmarks"], float(rec["lift"])
    views, accessors = gltf.get("bufferViews") or [], gltf.get("accessors") or []

    def locate(index: int):
        acc = accessors[index]
        if acc.get("componentType") != 5126 or acc.get("type") != "VEC3" or "bufferView" not in acc \
                or "sparse" in acc:
            raise ValueError("a body POSITION / NORMAL accessor must be a dense float VEC3")
        view = views[acc["bufferView"]]
        start = int(view.get("byteOffset", 0)) + int(acc.get("byteOffset", 0))
        stride = int(view.get("byteStride") or 12)
        return start, stride, int(acc["count"])

    def read(index: int) -> np.ndarray:
        start, stride, n = locate(index)
        raw = np.frombuffer(bytes(data), np.uint8, count=stride * (n - 1) + 12, offset=start)
        return np.lib.stride_tricks.as_strided(raw.view(np.uint8), (n, 12), (stride, 1)).copy().view("<f4") \
            .reshape(n, 3).astype(np.float64)

    def write(index: int, values: np.ndarray) -> None:
        start, stride, n = locate(index)
        rows = np.asarray(values, "<f4").reshape(n, 3)
        for k in range(n):
            data[start + k * stride:start + k * stride + 12] = rows[k].tobytes()

    def faces_of(prim: dict, n: int) -> np.ndarray:
        if "indices" not in prim:
            return np.arange(n - n % 3, dtype=np.int64).reshape(-1, 3)
        acc = accessors[prim["indices"]]
        view = views[acc["bufferView"]]
        dt = {5121: "u1", 5123: "<u2", 5125: "<u4"}[acc["componentType"]]
        start = int(view.get("byteOffset", 0)) + int(acc.get("byteOffset", 0))
        return np.frombuffer(bytes(data), dt, count=int(acc["count"]), offset=start).astype(np.int64).reshape(-1, 3)

    skinned = {node["mesh"] for node in gltf.get("nodes") or []
               if "mesh" in node and "skin" in node and not glb_mesh._is_garment_node(node)}
    done: set = set()
    changed = False
    for mi, mesh in enumerate(gltf.get("meshes") or []):
        if mi not in skinned:
            continue
        for prim in mesh.get("primitives") or []:
            pi = prim.get("attributes", {}).get("POSITION")
            if pi is None or pi in done:
                continue
            done.add(pi)
            P = read(pi)
            Q = displace(P, lm, lift)
            mask = np.any(np.abs(Q - P) > 1e-7, axis=1)
            if not mask.any():
                continue
            changed = True
            write(pi, Q)
            accessors[pi]["min"] = [float(v) for v in Q.min(axis=0).astype(np.float32)]
            accessors[pi]["max"] = [float(v) for v in Q.max(axis=0).astype(np.float32)]
            ni = prim.get("attributes", {}).get("NORMAL")
            if ni is not None:
                write(ni, _normals(Q, faces_of(prim, len(Q)), read(ni), mask))
    moved_joints = _shape_joints(gltf, data, views, accessors, lm, lift)
    if not changed and not moved_joints:
        return blob
    text = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    text += b" " * ((4 - len(text) % 4) % 4)
    rest = blob[bin_at + bin_len + ((4 - bin_len % 4) % 4):]
    body = (struct.pack("<I", len(text)) + b"JSON" + text + struct.pack("<I", bin_len) + b"BIN\0" + bytes(data)
            + b"\0" * ((4 - bin_len % 4) % 4) + rest)
    return b"glTF" + struct.pack("<II", 2, 12 + len(body)) + body


def _normals(P, faces, old, moved_mask) -> np.ndarray:
    """Area-weighted vertex normals of ``P``; only the vertices of faces touching a moved vertex take them."""
    F = np.asarray(faces, np.int64)
    fn = np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]])
    acc = np.zeros_like(P)
    for k in range(3):
        np.add.at(acc, F[:, k], fn)
    length = np.linalg.norm(acc, axis=1, keepdims=True)
    new = np.where(length > 1e-12, acc / np.maximum(length, 1e-12), old)
    touched = np.zeros(len(P), bool)
    touched[F[moved_mask[F].any(axis=1)].ravel()] = True
    out = np.array(old, np.float64, copy=True)
    out[touched] = new[touched]
    return out


def _shape_joints(gltf: dict, data: bytearray, views: list, accessors: list, lm: Dict[str, float],
                  lift: float) -> int:
    """Move the bind position of every joint of skin 0 that the field displaces (in place: the inverse bind matrix
    in ``data`` and the node's ``translation`` in ``gltf``), keeping each joint's skin matrix at rest (node world x
    inverse bind) unchanged, so the rest pose still shows the shaped bind positions. A child joint keeps its world
    place (its local translation is re-derived). Returns how many joints moved."""
    from app.core.glb_mesh import _local_matrix
    skins = gltf.get("skins") or []
    if not skins or "inverseBindMatrices" not in skins[0]:
        return 0
    nodes = gltf.get("nodes") or []
    joints = list(skins[0].get("joints") or [])
    acc = accessors[skins[0]["inverseBindMatrices"]]
    if acc.get("componentType") != 5126 or acc.get("type") != "MAT4" or "bufferView" not in acc:
        return 0
    view = views[acc["bufferView"]]
    start = int(view.get("byteOffset", 0)) + int(acc.get("byteOffset", 0))
    stride = int(view.get("byteStride") or 64)
    ibm = [np.frombuffer(bytes(data[start + k * stride:start + k * stride + 64]), "<f4").astype(np.float64)
           .reshape(4, 4).T for k in range(len(joints))]
    bind = np.array([np.linalg.inv(m)[:3, 3] for m in ibm])
    target = displace(bind, lm, lift)
    move = [k for k in range(len(joints)) if np.linalg.norm(target[k] - bind[k]) > 1e-7]
    if not move:
        return 0
    parent = {c: i for i, n in enumerate(nodes) for c in n.get("children") or []}

    def world(i: int, cache: dict) -> np.ndarray:
        if i not in cache:
            local = _local_matrix(nodes[i])
            cache[i] = local if i not in parent else world(parent[i], cache) @ local
        return cache[i]
    before: dict = {}
    for i in range(len(nodes)):
        world(i, before)
    after = dict(before)
    for k in move:
        j = joints[k]
        skin = before[j] @ ibm[k]                     # the joint's skin matrix at rest — kept
        b2 = np.linalg.inv(ibm[k])
        b2[:3, 3] = target[k]
        after[j] = skin @ b2
        ibm[k] = np.linalg.inv(b2)
        data[start + k * stride:start + k * stride + 64] = np.asarray(ibm[k].T, "<f4").tobytes()
    touched = {joints[k] for k in move}
    touched |= {c for j in list(touched) for c in nodes[j].get("children") or []}
    for i in sorted(touched):
        local = (np.linalg.inv(after[parent[i]]) @ after[i]) if i in parent else after[i]
        node = nodes[i]
        if "matrix" in node:
            node["matrix"] = [float(v) for v in local.T.ravel()]
        else:
            node["translation"] = [float(v) for v in local[:3, 3]]
    return len(move)


# --- the two places that use it -----------------------------------------------------------------------------

def key_tokens(params: Optional[Dict[str, Any]], item: Optional[Dict[str, Any]]) -> list:
    """What ``garment_template.key_for`` folds into a drape's key: [] for a piece that does not shape (its key
    stays what it was before A228), else the one ``signature`` token."""
    sig = signature(params, lift_of(item))
    return [sig] if sig else []


def prepare(body_glb, params: Optional[Dict[str, Any]], item: Optional[Dict[str, Any]], scratch):
    """``(body path, shaping record or None)`` for a drape: a shaping piece drapes on a shaped copy of the plain
    body written into ``scratch``; every other piece on ``body_glb`` itself."""
    from pathlib import Path
    from app.core import glb_mesh
    from app.core.garment_template import measure_body
    lift = lift_of(item)
    if not applies(params, lift):
        return Path(body_glb), None
    blob = Path(body_glb).read_bytes()
    lm = landmarks(glb_mesh.body_arrays(blob).positions, measure_body(blob))
    rec = record(lm, lift)
    target = Path(scratch) / "shaped_body.glb"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(shape_glb(blob, rec))
    return target, rec


def worn_record(garments) -> Optional[Dict[str, Any]]:
    """The shaping an assembly applies to the shown body: of the worn template drapes whose record carries one
    (``garment_template`` writes ``shaping``), the one with the strongest lift — two shaping pieces never add up."""
    best = None
    for g in garments or []:
        rec = (g.get("record") or {}).get("shaping") if g.get("template") else None
        if isinstance(rec, dict) and rec.get("version") == VERSION and float(rec.get("lift") or 0) > 0:
            if best is None or float(rec["lift"]) > float(best["lift"]):
                best = rec
    return best
