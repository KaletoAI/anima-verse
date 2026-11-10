"""GLB mesh IO with numpy: accessor reads, body/garment/static arrays and the garment graft.

No Blender and no trimesh (plan 2026-11-09 phase 4, R1): a garment fitted on the CPU is written into a skinned
character GLB by appending buffer data, accessors, an image/texture/material, one mesh and one node. Nothing that
was in the target file changes — body nodes, accessors and binary ranges stay byte-identical — so a grafted file
keeps every rig/face/base-colour property of its bare source except that it now carries a second mesh.

Node identity of a grafted garment (R12): node and mesh are named ``garment_<kind>_<item_id>``, the node carries
``extras.garment = {kind, item_id, fsig}``, is skinned to skin 0 and copies the body mesh node's parent and local
TRS. Joints are remapped by ``rig_contract.norm_bone_name`` onto the target's own skin order, never by index.
A weighted EXTENSION joint (not a rig-contract bone) the target lacks — a tip group the covered outfit model left
out, a group switched off for that signature — hands its weight to its nearest ancestor the target has, by the
garment source's own hierarchy (``GarmentMesh.joint_parents``, read by ``garment_arrays``); a missing contract
joint stays an error.

Vertex colours (HairDeck card hair, plan 2026-11-09-hairdeck-hair): a garment may carry ``colors`` — linear RGBA in
[0, 1] as glTF stores them. ``graft`` writes them as ``COLOR_0`` (UNSIGNED_BYTE normalized VEC4) and
``garment_arrays`` reads them back, so the assembly keeps them; without ``colors`` a graft is byte-identical to the
code before colours existed. ``card_arrays`` reads one named node of a HairDeck result (``hair_cards`` /
``head_proxy``) in its scene space.

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
class Prim:
    """One body primitive as arrays (``body_primitive_arrays``): raw accessor space, its own vertex order.

    ``attributes`` holds every vertex attribute except POSITION / JOINTS_0 / WEIGHTS_0 (NORMAL, TANGENT,
    TEXCOORD_n, COLOR_n, ...) as float64 (normalized integers converted to [0, 1] / [-1, 1]); ``targets`` the
    morph targets as ``{attribute: delta}`` dicts in the primitive's target order; ``joint_names`` = skin 0 in
    skin order (what ``joints`` index). ``rewrite_body_primitives`` writes it back.
    """
    positions: np.ndarray            # (n, 3) float64
    faces: np.ndarray                # (m, 3) int64
    attributes: Dict[str, np.ndarray] = field(default_factory=dict)
    joints: np.ndarray = field(default_factory=lambda: np.zeros((0, 4), np.int64))     # (n, 4) int64
    weights: np.ndarray = field(default_factory=lambda: np.zeros((0, 4), np.float64))  # (n, 4) float64
    targets: List[Dict[str, np.ndarray]] = field(default_factory=list)
    joint_names: List[str] = field(default_factory=list)


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
    colors: Optional[np.ndarray] = None   # (n, 4) linear RGBA in [0, 1] -> COLOR_0; None = no vertex colours
    joint_parents: Dict[str, str] = field(default_factory=dict)   # joint name -> its parent node's name (source GLB)


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


def _joint_parents(gltf: dict, skin_index: int = 0) -> Dict[str, str]:
    """Joint name -> the name of its parent node, for the joints of skin ``skin_index`` that have a parent."""
    skins, nodes = gltf.get("skins") or [], gltf.get("nodes") or []
    if not 0 <= skin_index < len(skins):
        return {}
    parent = {child: i for i, node in enumerate(nodes) for child in node.get("children") or []}
    return {str(nodes[j].get("name", "")): str(nodes[parent[j]].get("name", ""))
            for j in skins[skin_index].get("joints") or [] if j in parent}


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


def _vertex_colors(parsed: dict, primitive: dict, count: int) -> Optional[np.ndarray]:
    """``COLOR_0`` as (count, 4) float64 in [0, 1] (VEC3 gets alpha 1), None without one."""
    index = primitive.get("attributes", {}).get("COLOR_0")
    if index is None:
        return None
    accessor = parsed["gltf"]["accessors"][index]
    array = accessor_array(parsed, index)
    if accessor.get("componentType") != 5126 and not accessor.get("normalized"):
        raise ValueError("COLOR_0 integer accessor is not normalized")
    if array.shape not in ((count, 3), (count, 4)):
        raise ValueError("COLOR_0 accessor has the wrong shape")
    array = np.asarray(array, np.float64)
    if array.shape[1] == 3:
        array = np.hstack([array, np.ones((count, 1))])
    return array


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


def _body_prims(parsed: dict) -> List[dict]:
    """The body primitives of ``parsed`` (``face_retexture._body_primitives`` rule, garment nodes excluded), in
    ``_body_primitives`` order; the dicts of ``parsed['gltf']`` itself. ValueError without one."""
    from app.core.face_retexture import _body_primitives
    gltf = parsed["gltf"]
    garment_meshes = {node["mesh"] for node in gltf.get("nodes") or []
                      if "mesh" in node and _is_garment_node(node)}
    garment_prims = {id(p) for i, mesh in enumerate(gltf.get("meshes") or []) if i in garment_meshes
                     for p in mesh.get("primitives") or []}
    primitives = [p for p in _body_primitives(parsed) if id(p) not in garment_prims]
    if not primitives:
        raise ValueError("The GLB has no body primitive")
    return primitives


def body_arrays(glb: bytes) -> BodyMesh:
    """The body primitives (``face_retexture._body_primitives`` rule, garment nodes excluded), concatenated.

    Positions are raw accessor values: a skinned mesh lives in bind space, where its node transform does not apply,
    so the body and a garment grafted with the body node's TRS share one space.
    """
    parsed = _parse(glb, "Body")
    gltf = parsed["gltf"]
    primitives = _body_prims(parsed)
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


_PRIM_FIXED = ("POSITION", "JOINTS_0", "WEIGHTS_0")


def body_primitive_arrays(glb: bytes) -> List[Prim]:
    """The body primitives of ``glb`` as ``Prim`` arrays, one per primitive, in ``_body_primitives`` order (the
    same primitives ``body_arrays`` concatenates). Every attribute is read as float64 (normalized integers
    converted), morph targets as delta dicts; ``joint_names`` = skin 0."""
    parsed = _parse(glb, "Body")
    gltf = parsed["gltf"]
    names = _skin_joint_names(gltf, 0)
    out: List[Prim] = []
    for prim in _body_prims(parsed):
        pos = np.asarray(accessor_array(parsed, prim["attributes"]["POSITION"]), np.float64)
        n = len(pos)
        attributes: Dict[str, np.ndarray] = {}
        for name, index in prim.get("attributes", {}).items():
            if name in _PRIM_FIXED:
                continue
            attributes[name] = np.asarray(accessor_array(parsed, index), np.float64)
        targets = [{name: np.asarray(accessor_array(parsed, index), np.float64) for name, index in target.items()}
                   for target in prim.get("targets") or []]
        out.append(Prim(positions=pos, faces=_triangles(parsed, prim, n), attributes=attributes,
                        joints=_vertex_attr(parsed, prim, "JOINTS_0", n, 4, np.int64),
                        weights=_vertex_attr(parsed, prim, "WEIGHTS_0", n, 4, np.float64),
                        targets=targets, joint_names=list(names)))
    return out


_COMPONENT_DTYPE = {5120: "i1", 5121: "u1", 5122: "<i2", 5123: "<u2", 5125: "<u4", 5126: "<f4"}
_TYPE_WIDTH = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}


def _encode(array: np.ndarray, component: int, normalized: bool) -> np.ndarray:
    """``array`` (float64 / int64) as the accessor's component type; normalized integers are scaled back."""
    dtype = np.dtype(_COMPONENT_DTYPE[component])
    if dtype.kind == "f":
        return np.ascontiguousarray(array, dtype=dtype)
    if normalized:
        limits = np.iinfo(dtype)
        return np.ascontiguousarray(np.round(np.clip(array, -1.0 if dtype.kind == "i" else 0.0, 1.0) * limits.max),
                                    dtype=dtype)
    return np.ascontiguousarray(np.rint(array), dtype=dtype)


def _int_component(values: np.ndarray, original: Optional[int]) -> int:
    """The original unsigned component type when every value fits it, else the smallest that does."""
    top = int(values.max()) if values.size else 0
    for component in ((original,) if original in (5121, 5123, 5125) else ()) + (5121, 5123, 5125):
        if top <= np.iinfo(_COMPONENT_DTYPE[component]).max:
            return component
    raise ValueError("An index exceeds 32 bits")


def _walk_accessor_refs(gltf: dict):
    """Yield ``(container, key)`` of every accessor reference in ``gltf`` (primitives, targets, skins, animations)."""
    for mesh in gltf.get("meshes") or []:
        for prim in mesh.get("primitives") or []:
            for key in list(prim.get("attributes") or {}):
                yield prim["attributes"], key
            if "indices" in prim:
                yield prim, "indices"
            for target in prim.get("targets") or []:
                for key in list(target):
                    yield target, key
    for skin in gltf.get("skins") or []:
        if "inverseBindMatrices" in skin:
            yield skin, "inverseBindMatrices"
    for animation in gltf.get("animations") or []:
        for sampler in animation.get("samplers") or []:
            for key in ("input", "output"):
                if key in sampler:
                    yield sampler, key


def rewrite_body_primitives(glb: bytes, replaced: Dict[int, Prim]) -> bytes:
    """``glb`` with the body primitives ``replaced[i]`` (``i`` = the index in ``body_primitive_arrays`` order)
    rewritten from their ``Prim`` arrays. A primitive not in ``replaced`` keeps its accessors, and their bytes stay
    identical (only offsets move); the accessors used only by replaced primitives are dropped together with the
    bufferViews only they used, and the buffer is repacked. Attributes keep their accessor's component type
    (joint and index widths widen when the new values need it); a replaced primitive must carry the same
    attribute and target names as before."""
    parsed = _parse(glb, "Body")
    source = parsed["gltf"]
    binary = parsed["bin"]
    buffers = source.get("buffers") or []
    if len(buffers) != 1 or "uri" in buffers[0]:
        raise ValueError("The GLB must keep all data in its one embedded buffer")
    prims = _body_prims(parsed)
    located: Dict[int, Tuple[int, int]] = {}
    for mi, mesh in enumerate(source.get("meshes") or []):
        for pi, prim in enumerate(mesh.get("primitives") or []):
            for order, body_prim in enumerate(prims):
                if prim is body_prim:
                    located[order] = (mi, pi)
    for order in replaced:
        if order not in located:
            raise ValueError(f"No body primitive {order}")

    gltf = copy.deepcopy(source)
    views: List[dict] = gltf.setdefault("bufferViews", [])
    accessors: List[dict] = gltf.setdefault("accessors", [])
    old_views, old_accessors = len(views), len(accessors)
    new_blobs: List[bytes] = []            # one per new view, in view order
    freed: set = set()                     # accessors referenced by a replaced primitive before the rewrite

    def add_view(raw: bytes, target: Optional[int]) -> int:
        view = {"buffer": 0, "byteOffset": 0, "byteLength": len(raw)}
        if target:
            view["target"] = target
        views.append(view)
        new_blobs.append(raw)
        return len(views) - 1

    def add_accessor(array: np.ndarray, component: int, kind: str, target: int, *, minmax: bool,
                     normalized: bool) -> int:
        entry: Dict[str, Any] = {"bufferView": add_view(array.tobytes(), target), "componentType": component,
                                 "count": int(array.shape[0]), "type": kind}
        if normalized:
            entry["normalized"] = True
        if minmax and len(array):
            entry["min"] = [v.item() for v in array.reshape(len(array), -1).min(0)]
            entry["max"] = [v.item() for v in array.reshape(len(array), -1).max(0)]
        accessors.append(entry)
        return len(accessors) - 1

    def encode_attr(name: str, array: np.ndarray, original: Optional[dict]) -> int:
        arr = np.asarray(array)
        if arr.ndim == 1:
            arr = arr.reshape(-1, 1)
        kind = {1: "SCALAR", 2: "VEC2", 3: "VEC3", 4: "VEC4"}[arr.shape[1]]
        if original is not None and _TYPE_WIDTH.get(original.get("type")) != arr.shape[1]:
            raise ValueError(f"{name} changed its component count")
        if name == "JOINTS_0":
            component, normalized = _int_component(np.asarray(arr, np.int64), original and original.get("componentType")), False
        elif original is None:
            component, normalized = 5126, False
        else:
            component, normalized = int(original["componentType"]), bool(original.get("normalized"))
        has_minmax = name == "POSITION" or (original is not None and "min" in original)
        return add_accessor(_encode(arr, component, normalized), component, kind, _ARRAY_BUFFER,
                            minmax=has_minmax, normalized=normalized)

    for order, prim in replaced.items():
        mi, pi = located[order]
        target_prim = gltf["meshes"][mi]["primitives"][pi]
        old_attrs = dict(target_prim.get("attributes") or {})
        old_targets = list(target_prim.get("targets") or [])
        freed.update(old_attrs.values())
        if "indices" in target_prim:
            freed.add(target_prim["indices"])
        for target in old_targets:
            freed.update(target.values())
        P = np.asarray(prim.positions, np.float64)
        n = len(P)
        F = np.asarray(prim.faces, np.int64).reshape(-1, 3)
        if n == 0 or (len(F) and (F.min() < 0 or F.max() >= n)):
            raise ValueError("A replaced primitive has no vertices or faces out of range")
        wanted = {"POSITION"} | set(prim.attributes)
        if len(prim.joints) == n and "JOINTS_0" in old_attrs:
            wanted |= {"JOINTS_0", "WEIGHTS_0"}
        if wanted != set(old_attrs):
            raise ValueError(f"Replaced primitive {order} must keep the attributes {sorted(old_attrs)}")
        new_attrs: Dict[str, int] = {}
        for name in old_attrs:
            if name == "POSITION":
                array = P
            elif name == "JOINTS_0":
                array = np.asarray(prim.joints, np.int64)
            elif name == "WEIGHTS_0":
                array = np.asarray(prim.weights, np.float64)
            else:
                array = np.asarray(prim.attributes[name], np.float64)
            if len(array) != n:
                raise ValueError(f"{name} has {len(array)} rows for {n} vertices")
            new_attrs[name] = encode_attr(name, array, source["accessors"][old_attrs[name]])
        target_prim["attributes"] = new_attrs
        if len(prim.targets) != len(old_targets):
            raise ValueError(f"Replaced primitive {order} must keep its {len(old_targets)} morph targets")
        new_targets = []
        for old_target, target in zip(old_targets, prim.targets):
            if set(target) != set(old_target):
                raise ValueError("A morph target must keep its attribute names")
            new_targets.append({name: encode_attr(name, np.asarray(target[name], np.float64),
                                                  source["accessors"][old_target[name]]) for name in old_target})
        if new_targets:
            target_prim["targets"] = new_targets
        component = _int_component(F, source["accessors"][target_prim["indices"]]["componentType"]
                                   if "indices" in target_prim else None)
        target_prim["indices"] = add_accessor(_encode(F.reshape(-1, 1), component, False), component, "SCALAR",
                                              _ELEMENT_ARRAY_BUFFER, minmax=False, normalized=False)

    used_accessors = {container[key] for container, key in _walk_accessor_refs(gltf)}
    drop_accessors = {i for i in freed if i not in used_accessors}
    view_users: Dict[int, set] = {}
    for i, accessor in enumerate(accessors):
        if "bufferView" in accessor:
            view_users.setdefault(accessor["bufferView"], set()).add(i)
    for image in gltf.get("images") or []:
        if "bufferView" in image:
            view_users.setdefault(image["bufferView"], set()).add(-1)
    drop_views = {v for v, users in view_users.items() if v < old_views and users and users <= drop_accessors}

    # repack: kept old views in order (bytes identical), then the new ones
    blob = bytearray()
    view_map: Dict[int, int] = {}
    kept_views: List[dict] = []
    for i, view in enumerate(views):
        if i in drop_views:
            continue
        if i < old_views:
            start = int(view.get("byteOffset", 0))
            raw = bytes(binary[start:start + int(view["byteLength"])])
        else:
            raw = new_blobs[i - old_views]
        blob.extend(b"\0" * (-len(blob) % 4))
        entry = dict(view)
        entry["byteOffset"] = len(blob)
        blob.extend(raw)
        view_map[i] = len(kept_views)
        kept_views.append(entry)
    accessor_map: Dict[int, int] = {}
    kept_accessors: List[dict] = []
    for i, accessor in enumerate(accessors):
        if i in drop_accessors:
            continue
        entry = dict(accessor)
        if "bufferView" in entry:
            entry["bufferView"] = view_map[entry["bufferView"]]
        accessor_map[i] = len(kept_accessors)
        kept_accessors.append(entry)
    for container, key in _walk_accessor_refs(gltf):
        container[key] = accessor_map[container[key]]
    for image in gltf.get("images") or []:
        if "bufferView" in image:
            image["bufferView"] = view_map[image["bufferView"]]
    gltf["bufferViews"], gltf["accessors"] = kept_views, kept_accessors
    blob.extend(b"\0" * (-len(blob) % 4))
    gltf["buffers"] = [{"byteLength": len(blob)}]
    return pack_glb(gltf, bytes(blob))


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
                       image=image, mime=mime, material=material, colors=_vertex_colors(parsed, prim, n),
                       joint_parents=_joint_parents(gltf, node["skin"]) if "skin" in node else {})


def mat4_array(parsed: dict, index: int) -> np.ndarray:
    """A dense float MAT4 accessor as ``(n, 4, 4)`` row-major matrices (glTF stores them column-major)."""
    gltf, binary = parsed["gltf"], parsed["bin"]
    accessor = gltf["accessors"][index]
    if accessor.get("type") != "MAT4" or accessor.get("componentType") != 5126 or accessor.get("sparse"):
        raise ValueError("A matrix accessor must be a dense float MAT4 accessor")
    view = gltf["bufferViews"][accessor["bufferView"]]
    count = int(accessor["count"])
    stride = int(view.get("byteStride", 64))
    start = int(view.get("byteOffset", 0)) + int(accessor.get("byteOffset", 0))
    if (view.get("buffer", 0) != 0 or count <= 0 or stride < 64
            or start + (count - 1) * stride + 64 > len(binary)):
        raise ValueError("The matrix accessor is truncated or invalid")
    array = np.ndarray((count, 16), dtype="<f4", buffer=binary, offset=start, strides=(stride, 4))
    return np.asarray(array, np.float64).reshape(count, 4, 4).transpose(0, 2, 1)


def joint_bind_matrices(glb: bytes) -> Dict[str, np.ndarray]:
    """``norm_bone_name(joint) -> inverse(inverseBindMatrix)`` for the joints of skin 0: each joint's bind frame
    (4x4) in the body's accessor space — the space ``body_arrays`` positions live in. The first joint of a
    normalised name wins. ValueError for a GLB without a skin with inverse bind matrices."""
    from app.core.rig_contract import norm_bone_name
    parsed = _parse(glb, "Body")
    gltf = parsed["gltf"]
    skins = gltf.get("skins") or []
    if not skins or "inverseBindMatrices" not in skins[0]:
        raise ValueError("The GLB has no skin with inverse bind matrices")
    names = _skin_joint_names(gltf, 0)
    ibm = mat4_array(parsed, skins[0]["inverseBindMatrices"])
    if len(ibm) != len(names) or not names:
        raise ValueError("The skin's inverse bind matrices do not match its joints")
    out: Dict[str, np.ndarray] = {}
    for name, matrix in zip(names, np.linalg.inv(ibm)):
        out.setdefault(norm_bone_name(name), matrix)
    return out


def _local_matrix(node: dict) -> np.ndarray:
    """A node's local 4x4 transform (``matrix`` is column-major; else T * R * S)."""
    if "matrix" in node:
        return np.asarray(node["matrix"], np.float64).reshape(4, 4).T
    x, y, z, w = (float(v) for v in node.get("rotation", (0, 0, 0, 1)))
    rotation = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                         [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                         [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    m = np.eye(4)
    m[:3, :3] = rotation * np.asarray(node.get("scale", (1, 1, 1)), np.float64)[None, :]
    m[:3, 3] = np.asarray(node.get("translation", (0, 0, 0)), np.float64)
    return m


def card_arrays(glb: bytes, *, node: str = "") -> Tuple[np.ndarray, np.ndarray, np.ndarray,
                                                         Optional[np.ndarray], Dict[str, Any]]:
    """``(positions, faces, uvs, colors | None, material)`` of ONE mesh node of a HairDeck result.

    ``node`` names it (``hair_cards`` or ``head_proxy``); empty = the file's only mesh node. Positions are in scene
    space: the node's transform and its parents' are applied. All primitives of its mesh are concatenated; uvs are
    zeros without ``TEXCOORD_0``; colours are ``COLOR_0`` (linear RGBA in [0, 1]) — None when no primitive has one,
    white for a primitive without one beside one that has. The material is that of the first primitive.
    """
    parsed = _parse(glb, "Card")
    gltf = parsed["gltf"]
    nodes = gltf.get("nodes") or []
    picked = [i for i, n in enumerate(nodes) if "mesh" in n and (not node or n.get("name") == node)]
    if len(picked) != 1:
        raise ValueError(f"Expected exactly one mesh node {node!r}" if node else
                         f"Expected exactly one mesh node, found {len(picked)}")
    index = picked[0]
    parent = {c: i for i, n in enumerate(nodes) for c in n.get("children") or []}
    world, at, seen = np.eye(4), index, set()
    while at is not None:
        if at in seen:
            raise ValueError("The node hierarchy has a cycle")
        seen.add(at)
        world = _local_matrix(nodes[at]) @ world
        at = parent.get(at)
    P, F, U, C, base, any_color = [], [], [], [], 0, False
    material: Dict[str, Any] = {}
    for k, prim in enumerate(gltf["meshes"][nodes[index]["mesh"]].get("primitives") or []):
        pos = np.asarray(accessor_array(parsed, prim["attributes"]["POSITION"]), np.float64)
        n = len(pos)
        P.append(pos)
        F.append(_triangles(parsed, prim, n) + base)
        U.append(_vertex_attr(parsed, prim, "TEXCOORD_0", n, 2, np.float64))
        colors = _vertex_colors(parsed, prim, n)
        any_color = any_color or colors is not None
        C.append(colors if colors is not None else np.ones((n, 4)))
        base += n
        if k == 0 and "material" in prim:
            material = copy.deepcopy((gltf.get("materials") or [])[prim["material"]])
    if not P:
        raise ValueError("The mesh node has no primitive")
    positions = np.concatenate(P)
    positions = positions @ world[:3, :3].T + world[:3, 3]
    return (positions, np.concatenate(F), np.concatenate(U),
            np.concatenate(C) if any_color else None, material)


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


def static_glb(positions, faces, uvs, *, image: bytes = b"", mime: str = "", material: Optional[Dict[str, Any]] = None,
               name: str = "Mesh") -> bytes:
    """A static one-primitive GLB (what ``static_arrays`` reads back): POSITION, TEXCOORD_0, uint32 indices and,
    with ``image``, a base-colour texture. Of ``material`` only the PBR factors, ``doubleSided`` and ``name`` are
    kept (its texture references belong to another file); the image is the base colour."""
    P = np.ascontiguousarray(np.asarray(positions, np.float64), dtype="<f4").reshape(-1, 3)
    U = np.ascontiguousarray(np.asarray(uvs, np.float64), dtype="<f4").reshape(-1, 2)
    F = np.ascontiguousarray(np.asarray(faces, np.int64).reshape(-1), dtype="<u4")
    if len(U) != len(P):
        raise ValueError("UV count differs from the vertex count")
    if len(F) and int(F.max()) >= len(P):
        raise ValueError("A face index is out of range")
    binary = bytearray()
    views: List[dict] = []
    accessors: List[dict] = []

    def add(raw: bytes, target: Optional[int]) -> int:
        binary.extend(b"\0" * (-len(binary) % 4))
        view = {"buffer": 0, "byteOffset": len(binary), "byteLength": len(raw)}
        if target:
            view["target"] = target
        views.append(view)
        binary.extend(raw)
        return len(views) - 1

    def accessor(arr: np.ndarray, ctype: int, typ: str, target: int, minmax: bool = False) -> int:
        entry = {"bufferView": add(arr.tobytes(), target), "componentType": ctype,
                 "count": int(len(arr)), "type": typ}
        if minmax and len(arr):
            entry["min"], entry["max"] = arr.min(0).tolist(), arr.max(0).tolist()
        accessors.append(entry)
        return len(accessors) - 1

    attributes = {"POSITION": accessor(P, 5126, "VEC3", 34962, True),
                  "TEXCOORD_0": accessor(U, 5126, "VEC2", 34962)}
    primitive = {"attributes": attributes, "indices": accessor(F, 5125, "SCALAR", 34963), "mode": 4}
    gltf: Dict[str, Any] = {"asset": {"version": "2.0", "generator": "anima glb_mesh.static_glb"}, "scene": 0,
                            "scenes": [{"nodes": [0]}], "nodes": [{"name": name, "mesh": 0}],
                            "meshes": [{"name": name, "primitives": [primitive]}],
                            "bufferViews": views, "accessors": accessors, "buffers": []}
    source = material or {}
    pbr = {k: copy.deepcopy(v) for k, v in (source.get("pbrMetallicRoughness") or {}).items()
           if k in ("baseColorFactor", "metallicFactor", "roughnessFactor")}
    mat: Dict[str, Any] = {"name": str(source.get("name") or name), "doubleSided": bool(source.get("doubleSided", True))}
    if image:
        if mime not in ("image/png", "image/jpeg", "image/webp"):
            raise ValueError(f"Unsupported image type {mime!r}")
        gltf["images"] = [{"bufferView": add(bytes(image), None), "mimeType": mime}]
        if mime == "image/webp":
            gltf["textures"] = [{"extensions": {"EXT_texture_webp": {"source": 0}}}]
            gltf["extensionsUsed"] = ["EXT_texture_webp"]
        else:
            gltf["textures"] = [{"source": 0}]
        pbr["baseColorTexture"] = {"index": 0}
    mat["pbrMetallicRoughness"] = pbr
    gltf["materials"] = [mat]
    primitive["material"] = 0
    binary.extend(b"\0" * (-len(binary) % 4))
    gltf["buffers"] = [{"byteLength": len(binary)}]
    return pack_glb(gltf, bytes(binary))


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


def _check_colors(g: GarmentMesh, n: int) -> Optional[np.ndarray]:
    """``colors`` as (n, 4) UNSIGNED_BYTE (clipped to [0, 1], RGB gets alpha 1), None without colours."""
    if g.colors is None:
        return None
    C = np.asarray(g.colors, np.float64)
    if C.ndim != 2 or C.shape[0] != n or C.shape[1] not in (3, 4):
        raise ValueError("Garment colours must have shape (n, 3) or (n, 4)")
    if not np.isfinite(C).all():
        raise ValueError("Garment colours contain non-finite values")
    if C.shape[1] == 3:
        C = np.hstack([C, np.ones((n, 1))])
    return np.round(np.clip(C, 0.0, 1.0) * 255).astype("u1")


def graft(target_glb: bytes, garment: GarmentMesh, *, name: str, extras: dict) -> bytes:
    """``target_glb`` + one skinned garment node ``name`` (see the module docstring). A weighted extension joint the
    target lacks hands its weight to its nearest ancestor (``joint_parents``) the target has. Raises ``KeyError``
    naming a WEIGHTED garment joint the target skin lacks and that has no such ancestor (a listed joint without
    weight > 0 maps to target index 0 with weight 0), ``ValueError`` for compressed geometry, a name already present
    or broken garment arrays."""
    from app.core.rig_contract import BASE_JOINT_KEYS, norm_bone_name
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
    C = _check_colors(garment, len(P))

    target_names = _skin_joint_names(gltf, 0)
    lookup: Dict[str, int] = {}
    for i, joint in enumerate(target_names):
        lookup.setdefault(norm_bone_name(joint), i)
    # Only a joint that carries weight somewhere in the garment must exist in
    # the target: a garment fitted on a skin with extra joints (e.g. a pack's
    # tip group on the bare base) still lists them, unweighted. Such an unused
    # joint is remapped to target index 0 and its influences get weight 0.
    weighted = set(np.unique(J[W > 0]).tolist())
    remap = []
    unused = []
    parents = {norm_bone_name(str(k)): str(v) for k, v in (garment.joint_parents or {}).items()}

    def ancestor(key: str) -> Optional[int]:
        """The target index of the nearest ancestor of an extension joint the target has."""
        seen = {key}
        while key not in BASE_JOINT_KEYS and key in parents:
            key = norm_bone_name(parents[key])
            if key in seen:
                return None
            seen.add(key)
            if key in lookup:
                return lookup[key]
        return None
    for index, joint in enumerate(garment.joint_names):
        key = norm_bone_name(str(joint))
        if key in lookup:
            remap.append(lookup[key])
        elif index in weighted:
            folded = ancestor(key) if key not in BASE_JOINT_KEYS else None
            if folded is None:
                raise KeyError(f"Garment joint {joint} is missing from the target skin")
            remap.append(folded)
        else:
            remap.append(0)
            unused.append(index)
    if unused:
        W = np.where(np.isin(J, unused), 0.0, W)
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

    def add_accessor(array: np.ndarray, component: int, kind: str, target: int, minmax: bool = False,
                     normalized: bool = False) -> int:
        accessor = {"bufferView": add_view(array.tobytes(), target), "componentType": component,
                    "count": int(array.shape[0]), "type": kind}
        if normalized:
            accessor["normalized"] = True
        if minmax:
            accessor["min"] = [float(v) for v in array.min(0)]
            accessor["max"] = [float(v) for v in array.max(0)]
        accessors.append(accessor)
        return len(accessors) - 1

    attributes = {"POSITION": add_accessor(P.astype("<f4"), 5126, "VEC3", _ARRAY_BUFFER, minmax=True)}
    if N is not None:
        attributes["NORMAL"] = add_accessor(N.astype("<f4"), 5126, "VEC3", _ARRAY_BUFFER)
    attributes["TEXCOORD_0"] = add_accessor(U.astype("<f4"), 5126, "VEC2", _ARRAY_BUFFER)
    if C is not None:
        attributes["COLOR_0"] = add_accessor(C, 5121, "VEC4", _ARRAY_BUFFER, normalized=True)
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
