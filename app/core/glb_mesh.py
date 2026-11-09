"""GLB mesh IO with numpy: accessor reads, body/garment/static arrays and the garment graft.

No Blender and no trimesh (plan 2026-11-09 phase 4, R1): a garment fitted on the CPU is written into a skinned
character GLB by appending buffer data, accessors, an image/texture/material, one mesh and one node. Nothing that
was in the target file changes — body nodes, accessors and binary ranges stay byte-identical — so a grafted file
keeps every rig/face/base-colour property of its bare source except that it now carries a second mesh.

Node identity of a grafted garment (R12): node and mesh are named ``garment_<kind>_<item_id>``, the node carries
``extras.garment = {kind, item_id, fsig}``, is skinned to skin 0 and copies the body mesh node's parent and local
TRS. Joints are remapped by ``rig_contract.norm_bone_name`` onto the target's own skin order, never by index.

Compressed geometry (``EXT_meshopt_compression`` / ``KHR_draco_mesh_compression``) is refused on every read and
graft: the accessor reader would read compressed bytes as raw data.
"""
from __future__ import annotations

import copy
import json
import struct
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

GARMENT_NODE_PREFIX = "garment_"
COMPRESSION_EXTENSIONS = ("EXT_meshopt_compression", "KHR_meshopt_compression", "KHR_draco_mesh_compression")
_TRS_KEYS = ("translation", "rotation", "scale", "matrix")
_ARRAY_BUFFER, _ELEMENT_ARRAY_BUFFER = 34962, 34963


@dataclass
class BodyMesh:
    """The body primitives of a GLB, concatenated, in raw accessor space (node transforms ignored)."""
    positions: np.ndarray            # (n, 3) float64
    faces: np.ndarray                # (m, 3) int64
    uvs: np.ndarray                  # (n, 2) float64, zeros without TEXCOORD_0
    joints: np.ndarray               # (n, 4) int64, zeros when unskinned
    weights: np.ndarray              # (n, 4) float64, zeros when unskinned
    joint_names: List[str] = field(default_factory=list)   # skin 0, in skin order


@dataclass
class GarmentMesh:
    """One garment primitive: geometry, skinning (indices into ``joint_names``) and its base-colour image."""
    positions: np.ndarray            # (n, 3)
    normals: Optional[np.ndarray]    # (n, 3) or None
    uvs: np.ndarray                  # (n, 2)
    indices: np.ndarray              # (m, 3)
    joints: np.ndarray               # (n, 4) indices into joint_names
    weights: np.ndarray              # (n, 4)
    joint_names: List[str]
    image: bytes = b""
    mime: str = ""
    material: Dict[str, Any] = field(default_factory=dict)


def accessor_array(parsed: dict, index: int) -> np.ndarray:
    """Read packed or interleaved GLB accessors without reading stride padding.

    ``parsed`` is ``model_validate.parse_glb`` output. Returns an ``(count, components)`` view (or a float64 copy
    for normalized integer data). Sparse accessors and anything outside buffer 0 are refused.
    """
    gltf, binary = parsed['gltf'], parsed['bin']
    accessor = gltf['accessors'][index]
    if accessor.get('sparse') is not None:
        raise ValueError('Sparse geometry accessors are unsupported')
    dtype = np.dtype({5120: 'i1', 5121: 'u1', 5122: '<i2', 5123: '<u2',
                      5125: '<u4', 5126: '<f4'}[accessor['componentType']])
    components = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4}[accessor['type']]
    view = gltf['bufferViews'][accessor['bufferView']]
    width = dtype.itemsize * components
    count = int(accessor['count'])
    offset = int(accessor.get('byteOffset', 0))
    stride = int(view.get('byteStride', width))
    start = int(view.get('byteOffset', 0))
    if (view.get('buffer', 0) != 0 or count <= 0 or offset < 0 or start < 0
            or stride < width or offset + (count - 1) * stride + width > view['byteLength']
            or start + view['byteLength'] > len(binary)):
        raise ValueError('Geometry accessor is truncated or invalid')
    array = np.ndarray((count, components), dtype=dtype, buffer=binary,
                       offset=start + offset, strides=(stride, dtype.itemsize))
    if accessor.get('normalized') and dtype.kind in 'iu':
        limits = np.iinfo(dtype)
        array = array.astype(np.float64) / limits.max
        if dtype.kind == 'i':
            array = np.maximum(array, -1)
    return array


# --- reading -------------------------------------------------------------------------------------------------------

def _parse(glb: bytes, side: str) -> dict:
    from app.core.model_validate import parse_glb
    parsed = parse_glb(glb)
    gltf = parsed["gltf"]
    used = set(gltf.get("extensionsUsed") or []) | set(gltf.get("extensionsRequired") or [])
    bad = sorted(used.intersection(COMPRESSION_EXTENSIONS))
    if bad:
        raise ValueError(f"{side} GLB uses compressed geometry ({', '.join(bad)}); decompress it first")
    return parsed


def _is_garment_node(node: dict) -> bool:
    return (str(node.get("name") or "").startswith(GARMENT_NODE_PREFIX)
            or "garment" in (node.get("extras") or {}))


def _skin_joint_names(gltf: dict, skin_index: int = 0) -> List[str]:
    skins, nodes = gltf.get("skins") or [], gltf.get("nodes") or []
    if not 0 <= skin_index < len(skins):
        return []
    return [str(nodes[j].get("name", "")) for j in skins[skin_index].get("joints") or []]


def _triangles(parsed: dict, primitive: dict, count: int) -> np.ndarray:
    if primitive.get("mode", 4) != 4:
        raise ValueError("Only triangle primitives are supported")
    if "indices" in primitive:
        flat = accessor_array(parsed, primitive["indices"]).reshape(-1).astype(np.int64)
    else:
        flat = np.arange(count, dtype=np.int64)
    if len(flat) % 3 or (len(flat) and (flat.min() < 0 or flat.max() >= count)):
        raise ValueError("Triangle indices are invalid")
    return flat.reshape(-1, 3)


def _vertex_attr(parsed: dict, primitive: dict, name: str, count: int, width: int, dtype) -> np.ndarray:
    index = primitive.get("attributes", {}).get(name)
    if index is None:
        return np.zeros((count, width), dtype)
    array = accessor_array(parsed, index)
    if array.shape != (count, width):
        raise ValueError(f"{name} accessor has the wrong shape")
    return np.asarray(array, dtype)


def _primitive_image(parsed: dict, primitive: dict) -> Tuple[bytes, str, Dict[str, Any]]:
    """``(image bytes, mime, material dict)`` of a primitive's base colour; empty when it has none."""
    from app.core.model_validate import texture_image_index
    gltf = parsed["gltf"]
    if "material" not in primitive:
        return b"", "", {}
    material = copy.deepcopy((gltf.get("materials") or [])[primitive["material"]])
    info = (material.get("pbrMetallicRoughness") or {}).get("baseColorTexture")
    if not isinstance(info, dict):
        return b"", "", material
    image = gltf["images"][texture_image_index(gltf, gltf["textures"][info["index"]])]
    if "bufferView" not in image:
        raise ValueError("The base-colour image is not embedded")
    view = gltf["bufferViews"][image["bufferView"]]
    start = int(view.get("byteOffset", 0))
    if view.get("buffer", 0) != 0 or start + int(view["byteLength"]) > len(parsed["bin"]):
        raise ValueError("The base-colour bufferView is invalid")
    return bytes(parsed["bin"][start:start + int(view["byteLength"])]), image.get("mimeType", ""), material


def body_arrays(glb: bytes) -> BodyMesh:
    """The body primitives (``face_retexture._body_primitives`` rule, garment nodes excluded), concatenated.

    Positions are raw accessor values: a skinned mesh lives in bind space, where its node transform does not apply,
    so the body and a garment grafted with the body node's TRS share one space.
    """
    from app.core.face_retexture import _body_primitives
    parsed = _parse(glb, "Body")
    gltf = parsed["gltf"]
    garment_meshes = {node["mesh"] for node in gltf.get("nodes") or []
                      if "mesh" in node and _is_garment_node(node)}
    garment_prims = {id(p) for i, mesh in enumerate(gltf.get("meshes") or []) if i in garment_meshes
                     for p in mesh.get("primitives") or []}
    primitives = [p for p in _body_primitives(parsed) if id(p) not in garment_prims]
    if not primitives:
        raise ValueError("The GLB has no body primitive")
    P, F, U, J, W, base = [], [], [], [], [], 0
    for prim in primitives:
        pos = np.asarray(accessor_array(parsed, prim["attributes"]["POSITION"]), np.float64)
        n = len(pos)
        P.append(pos)
        F.append(_triangles(parsed, prim, n) + base)
        U.append(_vertex_attr(parsed, prim, "TEXCOORD_0", n, 2, np.float64))
        J.append(_vertex_attr(parsed, prim, "JOINTS_0", n, 4, np.int64))
        W.append(_vertex_attr(parsed, prim, "WEIGHTS_0", n, 4, np.float64))
        base += n
    return BodyMesh(positions=np.concatenate(P), faces=np.concatenate(F), uvs=np.concatenate(U),
                    joints=np.concatenate(J), weights=np.concatenate(W), joint_names=_skin_joint_names(gltf, 0))


def garment_arrays(glb: bytes, *, node_prefix: str = GARMENT_NODE_PREFIX) -> GarmentMesh:
    """The ONE garment node whose name starts with ``node_prefix``: its single primitive, skin and image."""
    parsed = _parse(glb, "Garment")
    gltf = parsed["gltf"]
    nodes = [n for n in gltf.get("nodes") or [] if "mesh" in n and str(n.get("name") or "").startswith(node_prefix)]
    if len(nodes) != 1:
        raise ValueError(f"Expected exactly one garment node '{node_prefix}*', found {len(nodes)}")
    node = nodes[0]
    prims = gltf["meshes"][node["mesh"]].get("primitives") or []
    if len(prims) != 1:
        raise ValueError(f"A garment mesh must have exactly one primitive, found {len(prims)}")
    prim = prims[0]
    pos = np.asarray(accessor_array(parsed, prim["attributes"]["POSITION"]), np.float64)
    n = len(pos)
    normals = (_vertex_attr(parsed, prim, "NORMAL", n, 3, np.float64)
               if "NORMAL" in prim.get("attributes", {}) else None)
    image, mime, material = _primitive_image(parsed, prim)
    return GarmentMesh(positions=pos, normals=normals,
                       uvs=_vertex_attr(parsed, prim, "TEXCOORD_0", n, 2, np.float64),
                       indices=_triangles(parsed, prim, n),
                       joints=_vertex_attr(parsed, prim, "JOINTS_0", n, 4, np.int64),
                       weights=_vertex_attr(parsed, prim, "WEIGHTS_0", n, 4, np.float64),
                       joint_names=_skin_joint_names(gltf, node["skin"]) if "skin" in node else [],
                       image=image, mime=mime, material=material)


def static_arrays(glb: bytes) -> Tuple[np.ndarray, np.ndarray, np.ndarray, bytes, str, Dict[str, Any]]:
    """``(positions, faces, uvs, image, mime, material)`` of a generator/prepared GLB.

    All primitives of all meshes are concatenated and node transforms are ignored (a generator mesh has none).
    The image and material are those of the first primitive with a base-colour texture.
    """
    parsed = _parse(glb, "Mesh")
    gltf = parsed["gltf"]
    P, F, U, base = [], [], [], 0
    image, mime, material = b"", "", {}
    for mesh in gltf.get("meshes") or []:
        for prim in mesh.get("primitives") or []:
            pos = np.asarray(accessor_array(parsed, prim["attributes"]["POSITION"]), np.float64)
            n = len(pos)
            P.append(pos)
            F.append(_triangles(parsed, prim, n) + base)
            U.append(_vertex_attr(parsed, prim, "TEXCOORD_0", n, 2, np.float64))
            base += n
            if not image:
                image, mime, mat = _primitive_image(parsed, prim)
                material = mat or material
    if not P:
        raise ValueError("The GLB has no mesh primitive")
    return np.concatenate(P), np.concatenate(F), np.concatenate(U), image, mime, material


# --- writing ---------------------------------------------------------------------------------------------------------

def pack_glb(gltf: dict, binary: bytes) -> bytes:
    """A GLB container: JSON chunk padded with spaces, BIN chunk padded with zeros."""
    binary = bytes(binary) + b"\0" * (-len(binary) % 4)
    raw = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    raw += b" " * (-len(raw) % 4)
    body = struct.pack("<II", len(raw), 0x4E4F534A) + raw
    if binary:
        body += struct.pack("<II", len(binary), 0x004E4942) + binary
    return b"glTF" + struct.pack("<II", 2, 12 + len(body)) + body


def _body_node_index(parsed: dict) -> int:
    """Index of the body mesh node skinned to skin 0 (read on ``parsed`` itself: primitives match by identity)."""
    from app.core.face_retexture import _body_primitives
    gltf = parsed["gltf"]
    body_prims = {id(p) for p in _body_primitives(parsed)}
    meshes = gltf.get("meshes") or []
    candidates = [i for i, node in enumerate(gltf.get("nodes") or [])
                  if "mesh" in node and not _is_garment_node(node)
                  and any(id(p) in body_prims for p in meshes[node["mesh"]].get("primitives") or [])]
    skinned = [i for i in candidates if gltf["nodes"][i].get("skin") == 0]
    if not skinned:
        raise ValueError("The target GLB has no body mesh node skinned to skin 0")
    return skinned[0]


def _check_garment(g: GarmentMesh) -> Tuple[np.ndarray, ...]:
    P = np.asarray(g.positions, np.float64)
    n = len(P)
    I = np.asarray(g.indices, np.int64).reshape(-1, 3)
    U = np.asarray(g.uvs, np.float64)
    J = np.asarray(g.joints, np.int64)
    W = np.asarray(g.weights, np.float64)
    if (P.ndim != 2 or P.shape[1] != 3 or n == 0 or U.shape != (n, 2) or J.shape != (n, 4)
            or W.shape != (n, 4) or len(I) == 0):
        raise ValueError("Garment arrays have inconsistent shapes")
    if not np.isfinite(P).all() or not np.isfinite(U).all() or not np.isfinite(W).all():
        raise ValueError("Garment arrays contain non-finite values")
    if I.min() < 0 or I.max() >= n:
        raise ValueError("Garment indices exceed the vertex count")
    if J.min() < 0 or J.max() >= len(g.joint_names):
        raise ValueError("Garment joint indices exceed its joint names")
    sums = W.sum(1)
    if (W < 0).any() or (sums <= 0).any():
        raise ValueError("Garment weights must be nonnegative with a positive sum per vertex")
    N = None
    if g.normals is not None:
        N = np.asarray(g.normals, np.float64)
        if N.shape != (n, 3) or not np.isfinite(N).all():
            raise ValueError("Garment normals have the wrong shape")
        N = N / np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12)
    return P, N, U, I, J, W / sums[:, None]


def graft(target_glb: bytes, garment: GarmentMesh, *, name: str, extras: dict) -> bytes:
    """``target_glb`` + one skinned garment node ``name`` (see the module docstring). Raises ``KeyError`` naming a
    garment joint the target skin lacks, ``ValueError`` for compressed geometry, a name already present or broken
    garment arrays."""
    from app.core.rig_contract import norm_bone_name
    if not name or not isinstance(extras, dict):
        raise ValueError("graft needs a node name and an extras dict")
    parsed = _parse(target_glb, "Target")
    gltf = copy.deepcopy(parsed["gltf"])
    buffers = gltf.get("buffers") or []
    if len(buffers) != 1 or "uri" in buffers[0]:
        raise ValueError("The target GLB must keep all data in its one embedded buffer")
    nodes = gltf.setdefault("nodes", [])
    if any(n.get("name") == name for n in nodes) or any(m.get("name") == name for m in gltf.get("meshes") or []):
        raise ValueError(f"The target GLB already has a node or mesh named {name!r}")
    P, N, U, I, J, W = _check_garment(garment)

    target_names = _skin_joint_names(gltf, 0)
    lookup: Dict[str, int] = {}
    for i, joint in enumerate(target_names):
        lookup.setdefault(norm_bone_name(joint), i)
    remap = []
    for joint in garment.joint_names:
        key = norm_bone_name(str(joint))
        if key not in lookup:
            raise KeyError(f"Garment joint {joint} is missing from the target skin")
        remap.append(lookup[key])
    J = np.asarray(remap, np.int64)[J]
    if J.max() > 0xFFFF:
        raise ValueError("Joint index exceeds 16 bits")

    body_i = _body_node_index(parsed)
    binary = bytearray(parsed["bin"])
    views = gltf.setdefault("bufferViews", [])
    accessors = gltf.setdefault("accessors", [])

    def add_view(raw: bytes, target: Optional[int]) -> int:
        binary.extend(b"\0" * (-len(binary) % 4))
        view = {"buffer": 0, "byteOffset": len(binary), "byteLength": len(raw)}
        if target:
            view["target"] = target
        views.append(view)
        binary.extend(raw)
        return len(views) - 1

    def add_accessor(array: np.ndarray, component: int, kind: str, target: int, minmax: bool = False) -> int:
        accessor = {"bufferView": add_view(array.tobytes(), target), "componentType": component,
                    "count": int(array.shape[0]), "type": kind}
        if minmax:
            accessor["min"] = [float(v) for v in array.min(0)]
            accessor["max"] = [float(v) for v in array.max(0)]
        accessors.append(accessor)
        return len(accessors) - 1

    attributes = {"POSITION": add_accessor(P.astype("<f4"), 5126, "VEC3", _ARRAY_BUFFER, minmax=True)}
    if N is not None:
        attributes["NORMAL"] = add_accessor(N.astype("<f4"), 5126, "VEC3", _ARRAY_BUFFER)
    attributes["TEXCOORD_0"] = add_accessor(U.astype("<f4"), 5126, "VEC2", _ARRAY_BUFFER)
    attributes["JOINTS_0"] = add_accessor(J.astype("<u2"), 5123, "VEC4", _ARRAY_BUFFER)
    attributes["WEIGHTS_0"] = add_accessor(W.astype("<f4"), 5126, "VEC4", _ARRAY_BUFFER)
    indices = add_accessor(I.reshape(-1, 1).astype("<u4"), 5125, "SCALAR", _ELEMENT_ARRAY_BUFFER)

    material = copy.deepcopy(garment.material or {})
    for key in ("normalTexture", "occlusionTexture", "emissiveTexture", "extensions", "alphaCutoff"):
        material.pop(key, None)
    pbr = dict(material.get("pbrMetallicRoughness") or {})
    pbr.pop("metallicRoughnessTexture", None)
    pbr.pop("baseColorTexture", None)
    if garment.image:
        if garment.mime not in ("image/png", "image/jpeg", "image/webp"):
            raise ValueError(f"Unsupported garment image type {garment.mime!r}")
        images = gltf.setdefault("images", [])
        images.append({"bufferView": add_view(garment.image, None), "mimeType": garment.mime})
        if garment.mime == "image/webp":
            texture = {"extensions": {"EXT_texture_webp": {"source": len(images) - 1}}}
            used = gltf.setdefault("extensionsUsed", [])
            if "EXT_texture_webp" not in used:
                used.append("EXT_texture_webp")
        else:
            texture = {"source": len(images) - 1}
        textures = gltf.setdefault("textures", [])
        textures.append(texture)
        pbr["baseColorTexture"] = {"index": len(textures) - 1}
    material["pbrMetallicRoughness"] = pbr
    material["name"] = name
    material["alphaMode"] = "OPAQUE"
    materials = gltf.setdefault("materials", [])
    materials.append(material)

    meshes = gltf.setdefault("meshes", [])
    meshes.append({"name": name, "primitives": [{"attributes": attributes, "indices": indices,
                                                  "material": len(materials) - 1, "mode": 4}]})
    body = nodes[body_i]
    node = {"name": name, "mesh": len(meshes) - 1, "skin": 0, "extras": {"garment": copy.deepcopy(extras)}}
    node.update({k: copy.deepcopy(body[k]) for k in _TRS_KEYS if k in body})
    nodes.append(node)
    new_i = len(nodes) - 1
    parents = [n for n in nodes[:new_i] if body_i in (n.get("children") or [])]
    if parents:
        parents[0]["children"].append(new_i)
    else:
        scenes = [s for s in gltf.get("scenes") or [] if body_i in (s.get("nodes") or [])]
        if not scenes:
            raise ValueError("The body mesh node is in no scene")
        for scene in scenes:
            scene["nodes"].append(new_i)

    binary.extend(b"\0" * (-len(binary) % 4))
    buffers[0]["byteLength"] = len(binary)
    return pack_glb(gltf, bytes(binary))
