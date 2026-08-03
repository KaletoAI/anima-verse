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
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from app.core.log import get_logger

logger = get_logger(__name__)

MIXAMO_JOINT_COUNT = 52
# A texture this small is never real content — it is the known "empty texture"
# artefact of a failed bake.
MIN_TEXTURE_DIM = 8
# Above this many vertices a primitive is sampled instead of read completely —
# proportions do not get better from the last 100k points.
MAX_POSITION_SAMPLES = 200_000
# The triangle reader and the walk-surface analysis that used it are gone
# (2026-07-28): deciding from a mesh where a figure stands is an automatic
# repair, and it picked the campus ROOFS over the ground. Where the walkable
# surface sits is the admin's walk_y dial.


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


# ── Capability probe: what a stored mesh BRINGS ─────────────────────────
# Two mesh shapes reach our stores, and they are not interchangeable: a
# TEXTURED mesh (UVs + texture images) and a VERTEX-COLOURED one (colour in
# COLOR_0, material KHR_materials_unlit, no UVs, no image at all). Both render
# fine, but every post-process that re-bakes a texture — the mesh→mesh
# reduction, an FBX rigging, later maps — needs the textured shape. The probe
# answers that from the FILE; which alias produced it is irrelevant (and a
# name in the code would be a lie the moment a new alias appears).


class MeshNotShrinkable(ValueError):
    """A stored mesh cannot be reduced / re-textured — carries the reason.

    Raised by the ``trigger_shrink`` entry points so the reason reaches the
    route (and from there the admin) instead of turning into a bare False.
    """

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def read_glb_json(path: Union[str, Path]) -> Dict[str, Any]:
    """The glTF JSON of a GLB, read from the HEADER + JSON chunk ONLY.

    A GLB is a 12-byte header followed by length/type-prefixed chunks, and the
    JSON chunk comes first per spec — so everything the capability probe needs
    sits in the first few hundred kB of a file that may be >100 MB. Chunks
    before the JSON one are skipped by ``seek``, never read.

    Raises ValueError when the file is not a readable glTF 2 container.
    """
    with open(path, "rb") as fh:
        header = fh.read(12)
        if len(header) < 12 or header[:4] != b"glTF":
            raise ValueError("not a GLB file (magic missing)")
        _magic, version, _length = struct.unpack("<III", header)
        if version != 2:
            raise ValueError(f"unsupported glTF version: {version}")
        while True:
            head = fh.read(8)
            if len(head) < 8:
                raise ValueError("no JSON chunk in the GLB")
            chunk_len, chunk_type = struct.unpack("<II", head)
            if chunk_type == 0x4E4F534A:      # 'JSON'
                body = fh.read(chunk_len)
                if len(body) < chunk_len:
                    raise ValueError("truncated JSON chunk")
                return json.loads(body.decode("utf-8"))
            fh.seek(chunk_len + ((4 - chunk_len % 4) % 4), 1)


def gltf_capabilities(gltf: Dict[str, Any]) -> Dict[str, Any]:
    """What a glTF document brings: ``{images, uv, vertex_colors, unlit,
    meshes}``.

    ``images`` counts the texture images the document declares, ``uv`` is True
    as soon as ONE primitive carries a ``TEXCOORD_*`` attribute,
    ``vertex_colors`` likewise for ``COLOR_*``, ``unlit`` reports the
    ``KHR_materials_unlit`` extension. Every mesh of the document is looked at,
    not only the ones the default scene reaches — a re-bake would have to cope
    with all of them.
    """
    uv = False
    vertex_colors = False
    meshes = gltf.get("meshes") or []
    for mesh in meshes:
        for prim in (mesh.get("primitives") or []):
            attrs = prim.get("attributes") or {}
            if not isinstance(attrs, dict):
                continue
            for key in attrs:
                if str(key).startswith("TEXCOORD_"):
                    uv = True
                elif str(key).startswith("COLOR_"):
                    vertex_colors = True
    return {
        "images": len(gltf.get("images") or []),
        "uv": uv,
        "vertex_colors": vertex_colors,
        "unlit": "KHR_materials_unlit" in (gltf.get("extensionsUsed") or []),
        "meshes": len(meshes),
    }


def glb_capabilities(data: bytes) -> Dict[str, Any]:
    """``gltf_capabilities`` of a GLB held in memory (upload path)."""
    return gltf_capabilities(parse_glb(data)["gltf"])


def glb_capabilities_at(path: Union[str, Path]) -> Dict[str, Any]:
    """``gltf_capabilities`` of a STORED GLB — header + JSON chunk only, so a
    100-MB mesh costs a few hundred kB of reading."""
    return gltf_capabilities(read_glb_json(path))


def shrink_capability(path: Union[str, Path]) -> Dict[str, Any]:
    """Can this stored mesh be reduced / re-textured? ``{shrinkable, reason,
    caps}`` — ``reason`` is a short human sentence and empty when it can.

    The blocking condition is what the FILE lacks: no UV coordinates and/or no
    texture image means the reduction has nothing to bake the texture onto (or
    nothing to bake). A file we cannot read is NOT blocked — only a positive
    finding blocks, so an exotic or non-GLB entry keeps its action and the
    gateway stays the authority on it.
    """
    try:
        caps = glb_capabilities_at(path)
    except (OSError, ValueError, KeyError, struct.error,
            json.JSONDecodeError, UnicodeDecodeError):
        return {"shrinkable": True, "reason": "", "caps": {}}
    uv = bool(caps.get("uv"))
    images = int(caps.get("images") or 0)
    if uv and images:
        return {"shrinkable": True, "reason": "", "caps": caps}
    if not uv and caps.get("vertex_colors"):
        reason = ("vertex-coloured mesh without UVs — a reduction would have "
                  "nothing to re-bake")
    elif not uv and not images:
        reason = ("mesh without UVs and without a texture image — a reduction "
                  "would have nothing to re-bake")
    elif not uv:
        reason = ("mesh without UV coordinates — the reduction cannot bake the "
                  "texture onto the new topology")
    else:
        reason = ("mesh without an embedded texture image — the reduction has "
                  "nothing to re-bake")
    return {"shrinkable": False, "reason": reason, "caps": caps}


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
