"""Validation of uploaded 3D models (dependency-free).

The contract a 3D client relies on:

* humanoid  -> ONE .glb: 52-bone Mixamo rig, mesh AND textures embedded.
* generic   -> a rigged .fbx PLUS its basecolor .png (an FBX embeds no
  texture, and the PNG belongs to exactly that mesh — same run).
* none      -> ONE unrigged .glb with mesh and texture embedded (static
  props: the AV3D-9 building models — no skeleton is the point).

Both failure modes below have been seen in the wild and are silent:
a GLB whose only texture is a 2x2 placeholder (a known generation glitch —
the model renders flat grey), and an FBX shipped without its PNG.

Pure stdlib: a GLB is a 12-byte header + a JSON chunk + a BIN chunk, so the
structure can be read without a glTF library.
"""
import json
import math
import struct
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.core.log import get_logger

logger = get_logger(__name__)

MIXAMO_JOINT_COUNT = 52
# A texture this small is never real content — it is the known "empty texture"
# artefact of a failed bake.
MIN_TEXTURE_DIM = 8
# Above this many vertices a primitive is sampled instead of read completely —
# proportions do not get better from the last 100k points.
MAX_POSITION_SAMPLES = 200_000
# Triangles must be read WHOLE (sampling would tear them apart), so the walk
# analysis skips primitives above this vertex count and stops at this many
# triangles overall — a diorama has a few ten thousand.
MAX_TRIANGLE_VERTICES = 400_000
MAX_TRIANGLES = 300_000
# Walk-surface analysis (contract § B6 no. 7): a face counts as walkable floor
# from this upward-normal component on, heights are binned at this fraction of
# the model height, and the lowest layer only wins when no higher layer
# reaches this share of its area (otherwise a socket is always dominant).
WALK_NORMAL_MIN_Y = 0.7
WALK_BIN_FRACTION = 0.02
WALK_SOCKET_RATIO = 0.4


def _png_size(data: bytes) -> Optional[Tuple[int, int]]:
    """(width, height) of a PNG from its IHDR, or None if it isn't a PNG."""
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return struct.unpack(">II", data[16:24])


def _jpeg_size(data: bytes) -> Optional[Tuple[int, int]]:
    """(width, height) of a JPEG from its first SOF marker, or None."""
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        return None
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            return (w, h)
        seg_len = struct.unpack(">H", data[i + 2:i + 4])[0]
        i += 2 + seg_len
    return None


def _image_size(data: bytes) -> Optional[Tuple[int, int]]:
    return _png_size(data) or _jpeg_size(data)


def parse_glb(data: bytes) -> Dict[str, Any]:
    """Reads the glTF JSON + embedded image sizes out of a GLB container.

    Returns ``{gltf, images, joints, joint_count, bin}`` — ``bin`` is the raw
    BIN chunk (needed to decode geometry, see ``glb_bounds``); callers index
    by key, so the extra entry changes nothing for them.
    """
    if len(data) < 20 or data[:4] != b"glTF":
        raise ValueError("not a GLB file (magic missing)")
    _magic, version, _length = struct.unpack("<III", data[:12])
    if version != 2:
        raise ValueError(f"unsupported glTF version: {version}")

    gltf: Dict[str, Any] = {}
    bin_chunk = b""
    offset = 12
    while offset + 8 <= len(data):
        chunk_len, chunk_type = struct.unpack("<II", data[offset:offset + 8])
        body = data[offset + 8:offset + 8 + chunk_len]
        if chunk_type == 0x4E4F534A:      # 'JSON'
            gltf = json.loads(body.decode("utf-8"))
        elif chunk_type == 0x004E4942:    # 'BIN'
            bin_chunk = body
        offset += 8 + chunk_len + ((4 - chunk_len % 4) % 4)

    views = gltf.get("bufferViews") or []
    images: List[Dict[str, Any]] = []
    for img in (gltf.get("images") or []):
        entry: Dict[str, Any] = {"name": img.get("name", "")}
        idx = img.get("bufferView")
        if idx is not None and 0 <= idx < len(views):
            bv = views[idx]
            start = int(bv.get("byteOffset", 0))
            end = start + int(bv.get("byteLength", 0))
            size = _image_size(bin_chunk[start:end])
            entry["embedded"] = True
            entry["size"] = size
        else:
            # An external URI is not embedded — the client would have to fetch
            # a file we do not ship.
            entry["embedded"] = False
            entry["uri"] = img.get("uri", "")
        images.append(entry)

    joints: List[str] = []
    nodes = gltf.get("nodes") or []
    skins = gltf.get("skins") or []
    if skins:
        for j in (skins[0].get("joints") or []):
            if 0 <= j < len(nodes):
                joints.append(str(nodes[j].get("name", "")))
    return {"gltf": gltf, "images": images, "joints": joints,
            "joint_count": len(joints), "bin": bin_chunk}


# ── Geometry: raw-axis bounding box ─────────────────────────────────────
# Only the glTF node tree + POSITION accessors are needed, so this stays in
# the same dependency-free style as the validators above.


def _mat_identity() -> List[List[float]]:
    return [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]]


def _mat_mul(a: List[List[float]], b: List[List[float]]) -> List[List[float]]:
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)]
            for i in range(4)]


def _node_matrix(node: Dict[str, Any]) -> List[List[float]]:
    """Local transform of a glTF node as a row-major 4x4 — either its explicit
    ``matrix`` (16 floats, COLUMN-major per spec) or T·R·S from the separate
    translation / rotation (quaternion xyzw) / scale fields."""
    m = node.get("matrix")
    if isinstance(m, (list, tuple)) and len(m) == 16:
        return [[float(m[c * 4 + r]) for c in range(4)] for r in range(4)]
    t = node.get("translation") or [0.0, 0.0, 0.0]
    q = node.get("rotation") or [0.0, 0.0, 0.0, 1.0]
    s = node.get("scale") or [1.0, 1.0, 1.0]
    x, y, z, w = (float(q[0]), float(q[1]), float(q[2]), float(q[3]))
    rot = [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
           [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
           [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]
    sc = [float(s[0]), float(s[1]), float(s[2])]
    tr = [float(t[0]), float(t[1]), float(t[2])]
    return [[rot[r][0] * sc[0], rot[r][1] * sc[1], rot[r][2] * sc[2], tr[r]]
            for r in range(3)] + [[0.0, 0.0, 0.0, 1.0]]


def _mat_apply(m: List[List[float]], p: Sequence[float]) -> Tuple[float, float, float]:
    x, y, z = float(p[0]), float(p[1]), float(p[2])
    return (m[0][0] * x + m[0][1] * y + m[0][2] * z + m[0][3],
            m[1][0] * x + m[1][1] * y + m[1][2] * z + m[1][3],
            m[2][0] * x + m[2][1] * y + m[2][2] * z + m[2][3])


def _accessor_corners(acc: Dict[str, Any]) -> Optional[List[Tuple[float, float, float]]]:
    """The 8 corners of an accessor's declared min/max box (the glTF spec
    requires both on POSITION accessors, sparse and Draco included)."""
    mn, mx = acc.get("min"), acc.get("max")
    if not (isinstance(mn, (list, tuple)) and isinstance(mx, (list, tuple))):
        return None
    if len(mn) < 3 or len(mx) < 3:
        return None
    return [(float(a[0]), float(b[1]), float(c[2]))
            for a in (mn, mx) for b in (mn, mx) for c in (mn, mx)]


def _accessor_vec3(acc: Dict[str, Any], views: List[Dict[str, Any]],
                   bin_chunk: bytes, step: int = 1) -> List[Tuple[float, float, float]]:
    """Raw FLOAT/VEC3 data of an accessor out of the GLB's BIN chunk, every
    ``step``-th element. Sparse and Draco-compressed accessors cannot be read
    this way and yield []."""
    if acc.get("sparse") is not None:
        return []
    if acc.get("componentType") != 5126 or acc.get("type") != "VEC3":
        return []
    bv_idx = acc.get("bufferView")
    if not isinstance(bv_idx, int) or not (0 <= bv_idx < len(views)):
        return []
    bv = views[bv_idx]
    if int(bv.get("buffer", 0)) != 0:
        # Only buffer 0 is the embedded BIN chunk; an external buffer is a
        # file we do not have.
        return []
    stride = int(bv.get("byteStride") or 12)
    if stride < 12:
        return []
    base = int(bv.get("byteOffset", 0)) + int(acc.get("byteOffset", 0))
    count = int(acc.get("count") or 0)
    if count <= 0 or base < 0:
        return []
    out: List[Tuple[float, float, float]] = []
    for i in range(0, count, max(1, step)):
        off = base + i * stride
        if off < 0 or off + 12 > len(bin_chunk):
            break
        out.append(struct.unpack_from("<fff", bin_chunk, off))
    return out


def _accessor_positions(acc: Dict[str, Any], views: List[Dict[str, Any]],
                        bin_chunk: bytes) -> List[Tuple[float, float, float]]:
    """Positions of an accessor, SAMPLED down to ``MAX_POSITION_SAMPLES`` —
    the fallback for the (spec-violating) accessors without min/max, where
    only the extent matters."""
    count = int(acc.get("count") or 0)
    step = 1 if count <= MAX_POSITION_SAMPLES else math.ceil(count / MAX_POSITION_SAMPLES)
    return _accessor_vec3(acc, views, bin_chunk, step)


def _accessor_indices(acc: Dict[str, Any], views: List[Dict[str, Any]],
                      bin_chunk: bytes) -> Optional[List[int]]:
    """The index list of a primitive (SCALAR ubyte/ushort/uint), or None when
    it cannot be decoded — an un-indexed primitive is the caller's business."""
    fmt = {5121: "B", 5123: "H", 5125: "I"}.get(acc.get("componentType"))
    if fmt is None or acc.get("type") != "SCALAR" or acc.get("sparse") is not None:
        return None
    bv_idx = acc.get("bufferView")
    if not isinstance(bv_idx, int) or not (0 <= bv_idx < len(views)):
        return None
    bv = views[bv_idx]
    if int(bv.get("buffer", 0)) != 0:
        return None
    size = struct.calcsize("<" + fmt)
    stride = int(bv.get("byteStride") or size)
    base = int(bv.get("byteOffset", 0)) + int(acc.get("byteOffset", 0))
    count = int(acc.get("count") or 0)
    if count <= 0 or base < 0 or stride < size:
        return None
    if base + (count - 1) * stride + size > len(bin_chunk):
        return None
    return [struct.unpack_from("<" + fmt, bin_chunk, base + i * stride)[0]
            for i in range(count)]


def _iter_primitives(gltf: Dict[str, Any]):
    """Yields ``(primitive, world_matrix)`` for every mesh primitive of the
    default scene, node transforms already accumulated — the node walk exists
    once for the bounding box and the walk-surface analysis alike."""
    nodes = gltf.get("nodes") or []
    meshes = gltf.get("meshes") or []
    scenes = gltf.get("scenes") or []

    roots: List[Any] = []
    scene_idx = gltf.get("scene", 0)
    if scenes:
        if isinstance(scene_idx, int) and 0 <= scene_idx < len(scenes):
            roots = list(scenes[scene_idx].get("nodes") or [])
        else:
            for sc in scenes:
                roots.extend(sc.get("nodes") or [])
    if not roots:
        roots = list(range(len(nodes)))

    # (node index, world matrix of the PARENT, ancestor chain) — the chain
    # guards against a cyclic node graph.
    stack: List[Tuple[Any, List[List[float]], Tuple[int, ...]]] = [
        (i, _mat_identity(), ()) for i in roots]
    while stack:
        idx, parent, chain = stack.pop()
        if not isinstance(idx, int) or not (0 <= idx < len(nodes)) or idx in chain:
            continue
        node = nodes[idx]
        world = _mat_mul(parent, _node_matrix(node))
        mesh_idx = node.get("mesh")
        if isinstance(mesh_idx, int) and 0 <= mesh_idx < len(meshes):
            for prim in (meshes[mesh_idx].get("primitives") or []):
                yield prim, world
        for child in (node.get("children") or []):
            stack.append((child, world, chain + (idx,)))


def glb_bounds(data: bytes) -> Optional[Tuple[List[float], List[float]]]:
    """Raw-axis AABB (min, max) of all rendered POSITION data in a GLB —
    node transforms applied; None when nothing is measurable.

    "Raw-axis" means the MESH axes as they come out of the file: no
    orientation fix, no normalization. Callers turn (max - min) into the
    ``bbox`` edge lengths that the prop dims are derived from
    (``app/core/props.py``). Never raises — an unreadable or exotic file
    (Draco-only geometry, external buffers) simply yields None.
    """
    try:
        info = parse_glb(data)
        gltf: Dict[str, Any] = info["gltf"]
        bin_chunk: bytes = info.get("bin") or b""
        accessors = gltf.get("accessors") or []
        views = gltf.get("bufferViews") or []

        lo = [math.inf] * 3
        hi = [-math.inf] * 3
        for prim, world in _iter_primitives(gltf):
            acc_idx = (prim.get("attributes") or {}).get("POSITION")
            if not isinstance(acc_idx, int) or not (0 <= acc_idx < len(accessors)):
                continue
            acc = accessors[acc_idx]
            pts = _accessor_corners(acc)
            if pts is None:
                pts = _accessor_positions(acc, views, bin_chunk)
            for p in pts:
                wp = _mat_apply(world, p)
                for k in range(3):
                    if wp[k] < lo[k]:
                        lo[k] = wp[k]
                    if wp[k] > hi[k]:
                        hi[k] = wp[k]
    except (ValueError, KeyError, IndexError, TypeError, struct.error,
            json.JSONDecodeError):
        return None
    if any(not math.isfinite(v) for v in lo + hi):
        return None
    return (lo, hi)


# ── Geometry: walkable floor height (contract § B6 no. 7) ───────────────
# A diorama floor is modelled, not flat: podiums, sunken lounges and the
# well-known holes in generated meshes make "where does a figure stand"
# unmeasurable from the outside. Ray casting would fall through exactly those
# holes, so the analysis is AREA-WEIGHTED instead: collect every upward-facing
# triangle, bin the heights, and take the dominant large surface.


def _fix_matrix(rotation_fix: Any) -> List[List[float]]:
    """The orientation fix as a 3x3 rotation M = Rx·Ry·Rz (degrees, three.js
    'XYZ' Euler order, § A1) — identical to ``props.oriented_dims``."""
    rot = rotation_fix if isinstance(rotation_fix, dict) else {}
    try:
        rx = math.radians(float(rot.get("x") or 0))
        ry = math.radians(float(rot.get("y") or 0))
        rz = math.radians(float(rot.get("z") or 0))
    except (TypeError, ValueError):
        rx = ry = rz = 0.0
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    return [
        [cy * cz, -cy * sz, sy],
        [cx * sz + sx * sy * cz, cx * cz - sx * sy * sz, -sx * cy],
        [sx * sz - cx * sy * cz, sx * cz + cx * sy * sz, cx * cy],
    ]


def _rot_apply(m: List[List[float]], p: Sequence[float]) -> Tuple[float, float, float]:
    x, y, z = float(p[0]), float(p[1]), float(p[2])
    return (m[0][0] * x + m[0][1] * y + m[0][2] * z,
            m[1][0] * x + m[1][1] * y + m[1][2] * z,
            m[2][0] * x + m[2][1] * y + m[2][2] * z)


def _fixed_geometry(data: bytes, rotation_fix: Any = None):
    """``(triangles, lo, hi)`` of a GLB in FIXED model space (node transforms
    then the orientation fix), or None when nothing is readable. Triangles are
    read WHOLE — oversized or Draco/sparse primitives are skipped, which costs
    the analysis some faces but never a wrong number."""
    info = parse_glb(data)
    gltf: Dict[str, Any] = info["gltf"]
    bin_chunk: bytes = info.get("bin") or b""
    accessors = gltf.get("accessors") or []
    views = gltf.get("bufferViews") or []
    fix = _fix_matrix(rotation_fix)

    tris: List[Tuple[Tuple[float, float, float], ...]] = []
    lo = [math.inf] * 3
    hi = [-math.inf] * 3
    for prim, world in _iter_primitives(gltf):
        acc_idx = (prim.get("attributes") or {}).get("POSITION")
        if not isinstance(acc_idx, int) or not (0 <= acc_idx < len(accessors)):
            continue
        acc = accessors[acc_idx]
        if int(acc.get("count") or 0) > MAX_TRIANGLE_VERTICES:
            continue
        raw = _accessor_vec3(acc, views, bin_chunk)
        if not raw:
            continue
        pts = [_rot_apply(fix, _mat_apply(world, p)) for p in raw]
        for p in pts:
            for i in range(3):
                if p[i] < lo[i]:
                    lo[i] = p[i]
                if p[i] > hi[i]:
                    hi[i] = p[i]
        if int(prim.get("mode", 4)) != 4 or len(tris) >= MAX_TRIANGLES:
            continue
        idx_acc = prim.get("indices")
        if isinstance(idx_acc, int) and 0 <= idx_acc < len(accessors):
            indices = _accessor_indices(accessors[idx_acc], views, bin_chunk)
            if indices is None:
                continue
        else:
            indices = list(range(len(pts)))
        for i in range(0, len(indices) - 2, 3):
            if len(tris) >= MAX_TRIANGLES:
                break
            a, b, c = indices[i], indices[i + 1], indices[i + 2]
            if max(a, b, c) < len(pts):
                tris.append((pts[a], pts[b], pts[c]))
    if any(not math.isfinite(v) for v in lo + hi):
        return None
    return tris, lo, hi


def _walk_fraction_of(tris: List[Tuple[Tuple[float, float, float], ...]],
                      low_y: float, high_y: float) -> Optional[float]:
    """The dominant walkable surface as a fraction of the model height.

    Every upward-facing triangle contributes its HORIZONTAL (XZ-projected)
    area to a height bin; adjacent occupied bins merge into layers. The lowest
    layer is usually the socket/base plate and would always win on area alone,
    so it only does when no higher layer reaches ``WALK_SOCKET_RATIO`` of its
    area — a floor with holes stays the answer.
    """
    height = high_y - low_y
    if height <= 0 or not tris:
        return None
    bin_h = height * WALK_BIN_FRACTION
    if bin_h <= 0:
        return None
    bins: Dict[int, Tuple[float, float]] = {}   # index -> (area, area × y)
    for p0, p1, p2 in tris:
        ux, uy, uz = p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]
        vx, vy, vz = p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2]
        nx = uy * vz - uz * vy
        ny = uz * vx - ux * vz
        nz = ux * vy - uy * vx
        length = math.sqrt(nx * nx + ny * ny + nz * nz)
        if length <= 0 or ny / length < WALK_NORMAL_MIN_Y:
            continue
        area = ny / 2                      # the XZ-projected (horizontal) area
        y = (p0[1] + p1[1] + p2[1]) / 3
        key = int((y - low_y) / bin_h)
        prev = bins.get(key) or (0.0, 0.0)
        bins[key] = (prev[0] + area, prev[1] + area * y)
    if not bins:
        return None

    layers: List[Tuple[float, float]] = []   # (area, area-weighted height)
    run_area = run_sum = 0.0
    last = None
    for key in sorted(bins):
        if last is not None and key != last + 1:
            layers.append((run_area, run_sum / run_area))
            run_area = run_sum = 0.0
        area, wsum = bins[key]
        run_area += area
        run_sum += wsum
        last = key
    layers.append((run_area, run_sum / run_area))

    base = layers[0]
    higher = [lay for lay in layers[1:] if lay[0] >= base[0] * WALK_SOCKET_RATIO]
    winner = max(higher, key=lambda lay: lay[0]) if higher else base
    return min(max((winner[1] - low_y) / height, 0.0), 1.0)


def mesh_metrics(data: bytes, rotation_fix: Any = None) -> Optional[Dict[str, Any]]:
    """``{bbox_fixed: [x, y, z], walk_frac: float | None}`` of a GLB — the
    edge lengths AFTER the orientation fix and the walkable-floor height as a
    fraction of the model height. None when the geometry is unreadable;
    ``walk_frac`` alone is None when no walkable surface can be told apart.
    Never raises."""
    try:
        geo = _fixed_geometry(data, rotation_fix)
    except (ValueError, KeyError, IndexError, TypeError, struct.error,
            json.JSONDecodeError, MemoryError):
        return None
    if not geo:
        return None
    tris, lo, hi = geo
    size = [hi[i] - lo[i] for i in range(3)]
    if max(size) <= 0:
        return None
    return {"bbox_fixed": [round(v, 5) for v in size],
            "walk_frac": _walk_fraction_of(tris, lo[1], hi[1])}


def walk_fraction(data: bytes, rotation_fix: Any = None) -> Optional[float]:
    """The walkable floor of a GLB as a fraction of its height (0 = the lower
    edge), measured after the orientation fix. None when unreadable."""
    metrics = mesh_metrics(data, rotation_fix)
    return metrics.get("walk_frac") if metrics else None


def _check_embedded_textures(info: Dict[str, Any], subject: str,
                             errors: List[str], warnings: List[str]) -> None:
    """Shared texture gate: at least one REAL embedded image (external URIs
    do not ship with the file; a tiny image is the known empty-texture
    artefact of a failed bake). Appends findings in place."""
    embedded = [i for i in info["images"] if i.get("embedded")]
    if not info["images"]:
        errors.append(f"no texture in the GLB — a {subject} must embed it")
    elif not embedded:
        errors.append("textures are referenced externally, not embedded")
    else:
        # At least ONE real-sized image must exist. Additional SMALL maps are
        # legitimate (a uniform 4x4 metallic-roughness map is valid glTF —
        # AV3D-14 GLBs ship one); the failed-bake artefact is a file whose
        # ONLY embedded texture is tiny.
        sizes = [img.get("size") for img in embedded]
        known = [sz for sz in sizes if sz]
        real = [sz for sz in known if max(sz) >= MIN_TEXTURE_DIM]
        if known and not real:
            sz = known[0]
            errors.append(
                f"texture is {sz[0]}x{sz[1]} px — that is the known "
                "empty-texture artefact of a failed generation, not a result")
        elif not known:
            warnings.append("embedded texture size could not be read")


def validate_glb(data: bytes) -> Dict[str, Any]:
    """Validates a humanoid GLB: 52-joint Mixamo rig + a real embedded texture.

    Returns {"ok", "errors": [...], "warnings": [...], "joint_count", "rig"}.
    """
    errors: List[str] = []
    warnings: List[str] = []
    try:
        info = parse_glb(data)
    except (ValueError, KeyError, struct.error, json.JSONDecodeError) as e:
        return {"ok": False, "errors": [f"GLB unreadable: {e}"],
                "warnings": [], "joint_count": 0, "rig": "generic"}

    joints = info["joints"]
    count = info["joint_count"]
    mixamo = sum(1 for j in joints if "mixamorig" in j.lower())
    if count == 0:
        errors.append("no skin/skeleton in the GLB — the model cannot be animated")
    elif count != MIXAMO_JOINT_COUNT:
        errors.append(
            f"{count} joints instead of {MIXAMO_JOINT_COUNT} — not the Mixamo rig")
    if count and not mixamo:
        warnings.append("no 'mixamorig' joint names — a foreign rig with the "
                        "same joint count will not match the animation clips")

    _check_embedded_textures(info, "humanoid model", errors, warnings)

    rig = "mixamo" if (count == MIXAMO_JOINT_COUNT and mixamo) else "generic"
    return {"ok": not errors, "errors": errors, "warnings": warnings,
            "joint_count": count, "rig": rig}


def validate_static_glb(data: bytes) -> Dict[str, Any]:
    """Validates an UNRIGGED GLB (rig "none" — the AV3D-9 building models):
    readable container, at least one mesh, a real embedded texture. No
    skeleton requirement, and a present skin is not an error either — the
    client simply never animates these.

    Returns the same shape as validate_glb, with rig fixed to "none".
    """
    errors: List[str] = []
    warnings: List[str] = []
    try:
        info = parse_glb(data)
    except (ValueError, KeyError, struct.error, json.JSONDecodeError) as e:
        return {"ok": False, "errors": [f"GLB unreadable: {e}"],
                "warnings": [], "joint_count": 0, "rig": "none"}

    if not (info["gltf"].get("meshes") or []):
        errors.append("no mesh in the GLB — an empty scene is not a model")

    _check_embedded_textures(info, "building model", errors, warnings)

    return {"ok": not errors, "errors": errors, "warnings": warnings,
            "joint_count": info["joint_count"], "rig": "none"}


def validate_fbx(data: bytes, texture: Optional[bytes]) -> Dict[str, Any]:
    """Validates a generic FBX: it must come WITH its basecolor texture."""
    errors: List[str] = []
    warnings: List[str] = []
    if not data.startswith(b"Kaydara FBX Binary"):
        warnings.append("no binary-FBX signature — ASCII FBX may not load "
                        "in every client")
    if texture is None:
        errors.append("FBX without a texture PNG — an FBX embeds no texture, "
                      "so the basecolor image of the SAME run must be uploaded "
                      "with it")
    else:
        size = _image_size(texture)
        if not size:
            errors.append("the texture is not a readable PNG/JPEG")
        elif max(size) < MIN_TEXTURE_DIM:
            errors.append(
                f"texture is {size[0]}x{size[1]} px — that is the known "
                "empty-texture artefact of a failed generation, not a result")
    return {"ok": not errors, "errors": errors, "warnings": warnings,
            "joint_count": 0, "rig": "generic"}
