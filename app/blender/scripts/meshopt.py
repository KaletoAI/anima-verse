"""Lossless EXT_meshopt_compression delivery copy; never load a bpy scene.

The source JSON indices and geometry bytes are stable. Only buffer storage,
bufferView locations and extension declarations change. The bridge decoder
must reproduce each source view byte-for-byte before any output is written.
"""
import ctypes
import json
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import main
sys.path.pop(0)

EXT = "EXT_meshopt_compression"
_COMPONENT = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4}
_ELEMENTS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}


def read_glb(data):
    if len(data) < 20 or struct.unpack_from("<III", data) != (0x46546C67, 2, len(data)):
        raise ValueError("invalid GLB header")
    chunks, pos = [], 12
    while pos < len(data):
        length, kind = struct.unpack_from("<II", data, pos)
        pos += 8
        if length % 4 or pos + length > len(data):
            raise ValueError("invalid GLB chunk")
        chunks.append((kind, data[pos:pos+length]))
        pos += length
    if len(chunks) != 2 or [c[0] for c in chunks] != [0x4E4F534A, 0x004E4942]:
        raise ValueError("expected JSON and BIN chunks only")
    return json.loads(chunks[0][1]), chunks[1][1]


def write_glb(doc, binary):
    encoded = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    encoded += b" " * (-len(encoded) % 4)
    binary = bytes(binary) + b"\0" * (-len(binary) % 4)
    return (struct.pack("<III", 0x46546C67, 2, 28 + len(encoded) + len(binary))
            + struct.pack("<II", len(encoded), 0x4E4F534A) + encoded
            + struct.pack("<II", len(binary), 0x004E4942) + binary)


def has_compression(value):
    if isinstance(value, dict):
        return any("compression" in name.lower() or name == "KHR_texture_basisu"
                   for name in value.get("extensions", {})) or any(has_compression(v) for v in value.values())
    if isinstance(value, list):
        return any(has_compression(v) for v in value)
    return False


def bridge():
    from io_scene_gltf2.io.com.library import dll_path
    path = dll_path("bf_intern_meshopt_bridge", "MeshOptimizer")
    if path is None or not path.is_file():
        raise RuntimeError("meshopt bridge is unavailable")
    lib = ctypes.CDLL(str(path.resolve()))
    for name, version in (("encodeVertexVersion", 0), ("encodeIndexVersion", 1)):
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = [ctypes.c_int], None
        fn(version)
    for name in ("VertexBuffer", "IndexBuffer", "IndexSequence"):
        bound = getattr(lib, "encode" + name + "Bound")
        bound.argtypes, bound.restype = [ctypes.c_size_t, ctypes.c_size_t], ctypes.c_size_t
        encode = getattr(lib, "encode" + name)
        encode.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t]
        if name == "VertexBuffer":
            encode.argtypes.append(ctypes.c_size_t)
        encode.restype = ctypes.c_size_t
        decode = getattr(lib, "decode" + name)
        decode.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t]
        decode.restype = ctypes.c_int
    return lib


def candidates(doc):
    """Classify every accessor use, rejecting sparse and mixed-use storage."""
    accessors = doc.get("accessors", [])
    views = doc.get("bufferViews", [])
    uses = [[] for _ in accessors]
    blocked = set()
    for mesh in doc.get("meshes", []):
        for primitive in mesh.get("primitives", []):
            for a in primitive.get("attributes", {}).values():
                uses[a].append("ATTRIBUTES")
            for target in primitive.get("targets", []):
                for a in target.values():
                    uses[a].append("ATTRIBUTES")
            if "indices" in primitive:
                uses[primitive["indices"]].append("TRIANGLES" if primitive.get("mode", 4) == 4 else "INDICES")
    for animation in doc.get("animations", []):
        for sampler in animation.get("samplers", []):
            for key in ("input", "output"):
                uses[sampler[key]].append("RAW")
    for skin in doc.get("skins", []):
        if "inverseBindMatrices" in skin:
            uses[skin["inverseBindMatrices"]].append("RAW")
    for image in doc.get("images", []):
        if "bufferView" in image:
            blocked.add(image["bufferView"])

    # Extension-owned storage is not known geometry. Preserve its views and
    # accessor references rather than guessing the semantics of an extension.
    def extension_refs(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "bufferView" and isinstance(item, int):
                    blocked.add(item)
                elif key in ("accessor", "indices", "attributes"):
                    ids = item.values() if isinstance(item, dict) else [item]
                    for a in ids:
                        if isinstance(a, int) and 0 <= a < len(uses):
                            uses[a].append("RAW")
                extension_refs(item)
        elif isinstance(value, list):
            for item in value:
                extension_refs(item)

    def walk(value):
        if isinstance(value, dict):
            extension_refs(value.get("extensions", {}))
            for key, item in value.items():
                if key != "extras":
                    walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    walk(doc)
    by_view = [[] for _ in views]
    for i, accessor in enumerate(accessors):
        view = accessor.get("bufferView")
        if view is not None:
            by_view[view].append((accessor, uses[i]))
        sparse = accessor.get("sparse")
        if sparse:
            if view is not None:
                blocked.add(view)
            for key in ("indices", "values"):
                blocked.add(sparse[key]["bufferView"])
    result = {}
    for i, users in enumerate(by_view):
        v = views[i]
        if i in blocked or not users or v.get("extensions"):
            continue
        roles = [role for _, entries in users for role in entries]
        if any(not entries for _, entries in users) or "RAW" in roles:
            continue
        if all(role == "ATTRIBUTES" for role in roles):
            sizes = {_COMPONENT.get(a["componentType"], 0) * _ELEMENTS.get(a["type"], 0) for a, _ in users}
            stride = v.get("byteStride") or (next(iter(sizes)) if len(sizes) == 1 else 0)
            if not stride or stride % 4 or stride > 256 or v["byteLength"] % stride:
                continue
            count = v["byteLength"] // stride
            if any(a["count"] <= 0 or a["count"] > count
                   or not _ELEMENTS.get(a["type"])
                   or a.get("byteOffset", 0) + (a["count"]-1)*stride
                   + _COMPONENT[a["componentType"]]*_ELEMENTS[a["type"]] > v["byteLength"] for a, _ in users):
                continue
            mode = "ATTRIBUTES"
        elif all(role in ("TRIANGLES", "INDICES") for role in roles):
            # No packing/reordering of accessor ranges: one tight stream only.
            layouts = {(a["componentType"], a["type"], a["count"], a.get("byteOffset", 0)) for a, _ in users}
            if len(layouts) != 1 or "byteStride" in v:
                continue
            component, kind, count, offset = next(iter(layouts))
            stride = _COMPONENT.get(component, 0)
            if component not in (5123, 5125) or kind != "SCALAR" or offset or count <= 0 or count*stride != v["byteLength"]:
                continue
            mode = "TRIANGLES" if all(role == "TRIANGLES" for role in roles) and count % 3 == 0 else "INDICES"
        else:
            continue
        result[i] = (mode, count, stride)
    return result


def encode(lib, raw, mode, count, stride):
    name = {"ATTRIBUTES": "VertexBuffer", "TRIANGLES": "IndexBuffer", "INDICES": "IndexSequence"}[mode]
    if mode == "ATTRIBUTES":
        source, second = raw, stride
    else:
        values = struct.unpack("<" + ("H" if stride == 2 else "I")*count, raw)
        source = (ctypes.c_uint32*count)(*values)
        second = max(values) + 1
    bound = getattr(lib, "encode" + name + "Bound")(count, second)
    dst = ctypes.create_string_buffer(bound)
    args = [dst, bound, source, count]
    if mode == "ATTRIBUTES":
        args.append(stride)
    length = getattr(lib, "encode" + name)(*args)
    if not 0 < length <= bound:
        raise RuntimeError("meshopt encoding failed")
    encoded = dst.raw[:length]
    decoded = ctypes.create_string_buffer(len(raw))
    rc = getattr(lib, "decode" + name)(decoded, count, stride, encoded, length)
    if rc:
        raise RuntimeError(f"meshopt decoding failed for {mode}: {rc}")
    if decoded.raw != raw and mode == "TRIANGLES":
        # The triangle codec may cyclically rotate corners. Use the sequence
        # codec in that case to preserve the complete index array exactly.
        return encode(lib, raw, "INDICES", count, stride)
    if decoded.raw != raw:
        raise RuntimeError(f"meshopt byte equality failed for {mode}")
    return encoded, mode


def run(args):
    source = Path(args["inputs"]["model"]).read_bytes()
    doc, binary = read_glb(source)
    stats = {"input_bytes": len(source), "counts": {"ATTRIBUTES": 0, "TRIANGLES": 0, "INDICES": 0}}
    def skip(reason):
        return dict(stats, skipped=reason), {}
    if (doc.get("extensionsRequired") or has_compression(doc)
            or any("compression" in name.lower() or name == "KHR_texture_basisu"
                   for name in doc.get("extensionsUsed", []))):
        return skip("input has compression or required extensions")
    buffers = doc.get("buffers", [])
    if len(buffers) != 1 or "uri" in buffers[0] or any(v.get("buffer", 0) != 0 for v in doc.get("bufferViews", [])):
        return skip("only single embedded-buffer GLBs are supported")
    eligible = candidates(doc)
    if not eligible:
        return skip("no compressible geometry bufferViews")
    lib, output = bridge(), bytearray()
    fallback_length = 0
    for i, v in enumerate(doc.get("bufferViews", [])):
        start, length = v.get("byteOffset", 0), v["byteLength"]
        if start < 0 or length <= 0 or start+length > buffers[0]["byteLength"] or start+length > len(binary):
            raise ValueError("bufferView is out of bounds")
        raw = binary[start:start+length]
        output.extend(b"\0" * (-len(output) % 4))
        offset = len(output)
        if i in eligible:
            mode, count, stride = eligible[i]
            encoded, mode = encode(lib, raw, mode, count, stride)
            output.extend(encoded)
            v["buffer"] = 1
            # NONE is the default; an explicit NONE crashes Blender 5.2's importer.
            v.setdefault("extensions", {})[EXT] = {"buffer": 0, "byteOffset": offset, "byteLength": len(encoded), "byteStride": stride, "mode": mode, "count": count}
            fallback_length = max(fallback_length, start+length)
            stats["counts"][mode] += 1
        else:
            output.extend(raw)
            v["byteOffset"] = offset
    buffers[0]["byteLength"] = len(output)
    buffers.append({"byteLength": fallback_length, "extensions": {EXT: {"fallback": True}}})
    doc.setdefault("extensionsUsed", []).append(EXT)
    doc.setdefault("extensionsRequired", []).append(EXT)
    result = write_glb(doc, output)
    stats["output_bytes"] = len(result)
    if len(result) > len(source)*.95:
        return skip("delivery copy saves less than 5 percent")
    target = Path(args["out_dir"]) / "meshopt.glb"
    target.write_bytes(result)
    return stats, {"model": target.name}


if __name__ == "__main__":
    main(run)
