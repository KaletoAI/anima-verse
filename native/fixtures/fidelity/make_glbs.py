#!/usr/bin/env python3
"""Writes the three tiny GLBs of the Task 17 fidelity world (native/fixtures/fidelity/), stdlib only.

Usage: python3 native/fixtures/fidelity/make_glbs.py   (rewrites the files next to this script)

  hull_full.glb  a closed box 10 x 2 x 10 m (x/z centred, y 0..2), 24 vertices / 36 indices, ONE material
                 "hull" with baseColorFactor (0.8, 0.7, 0.6, 1) and NO metallicFactor (glTF default 1.0 ->
                 the client neutralises it to 0, glbMaterials.ts), node extras
                 {"interior_cutout_padding_m": 0.25} (the hull builder's extra, app/core/hull_model.py)
  hull_low.glb   the same box, material "hull_low" (0.6, 0.6, 0.6, 1), same extras — the low tier
  box.glb        a 1 m cube centred on the origin, material "metal" with metallicFactor 1.0 and a 2 x 2
                 metallicRoughnessTexture (a real metal map: the client keeps metalness 1), no extras
"""
import json
import os
import struct
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))


def png_rgba(w, h, rgba):
    raw = b"".join(b"\x00" + bytes(rgba) * w for _ in range(h))
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def box(sx, sy, sz, y0):
    """24 vertices (4 per face, own normals), 36 indices, counter-clockwise seen from outside."""
    hx, hz = sx / 2, sz / 2
    y1 = y0 + sy
    faces = [  # (normal, four corners counter-clockwise from outside)
        ((1, 0, 0), [(hx, y0, hz), (hx, y0, -hz), (hx, y1, -hz), (hx, y1, hz)]),
        ((-1, 0, 0), [(-hx, y0, -hz), (-hx, y0, hz), (-hx, y1, hz), (-hx, y1, -hz)]),
        ((0, 1, 0), [(-hx, y1, hz), (hx, y1, hz), (hx, y1, -hz), (-hx, y1, -hz)]),
        ((0, -1, 0), [(-hx, y0, -hz), (hx, y0, -hz), (hx, y0, hz), (-hx, y0, hz)]),
        ((0, 0, 1), [(-hx, y0, hz), (hx, y0, hz), (hx, y1, hz), (-hx, y1, hz)]),
        ((0, 0, -1), [(hx, y0, -hz), (-hx, y0, -hz), (-hx, y1, -hz), (hx, y1, -hz)]),
    ]
    pos, nor, uv, idx = [], [], [], []
    for n, quad in faces:
        base = len(pos)
        pos += quad
        nor += [n] * 4
        uv += [(0, 1), (1, 1), (1, 0), (0, 0)]
        idx += [base, base + 1, base + 2, base, base + 2, base + 3]
    return pos, nor, uv, idx


def glb(path, mesh_name, material, extras=None, image=None):
    pos, nor, uv, idx = box(*mesh_name)
    bin_ = bytearray()
    views, accessors = [], []

    def add_view(data, target=None):
        while len(bin_) % 4:
            bin_.append(0)
        view = {"buffer": 0, "byteOffset": len(bin_), "byteLength": len(data)}
        if target:
            view["target"] = target
        bin_.extend(data)
        views.append(view)
        return len(views) - 1

    def add_acc(values, comps, ctype, typ, target, minmax=False):
        fmt = {5126: "f", 5123: "H"}[ctype]
        flat = [c for v in values for c in (v if isinstance(v, tuple) else (v,))]
        data = struct.pack("<" + fmt * len(flat), *flat)
        acc = {"bufferView": add_view(data, target), "componentType": ctype, "count": len(values), "type": typ}
        if minmax:
            acc["min"] = [min(v[i] for v in values) for i in range(comps)]
            acc["max"] = [max(v[i] for v in values) for i in range(comps)]
        accessors.append(acc)
        return len(accessors) - 1

    a_pos = add_acc(pos, 3, 5126, "VEC3", 34962, minmax=True)
    a_nor = add_acc(nor, 3, 5126, "VEC3", 34962)
    a_uv = add_acc(uv, 2, 5126, "VEC2", 34962)
    a_idx = add_acc(idx, 1, 5123, "SCALAR", 34963)
    doc = {
        "asset": {"version": "2.0", "generator": "anima native fixtures make_glbs.py"},
        "scene": 0, "scenes": [{"nodes": [0]}],
        "nodes": [{"name": "hull" if extras else "box", "mesh": 0, **({"extras": extras} if extras else {})}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": a_pos, "NORMAL": a_nor, "TEXCOORD_0": a_uv},
                                    "indices": a_idx, "material": 0}]}],
        "materials": [material],
        "accessors": accessors, "bufferViews": views,
    }
    if image is not None:
        doc["images"] = [{"bufferView": add_view(image), "mimeType": "image/png"}]
        doc["samplers"] = [{"magFilter": 9729, "minFilter": 9987}]
        doc["textures"] = [{"sampler": 0, "source": 0}]
    while len(bin_) % 4:
        bin_.append(0)
    doc["buffers"] = [{"byteLength": len(bin_)}]
    js = json.dumps(doc, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    out = (struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(bin_))
           + struct.pack("<II", len(js), 0x4E4F534A) + js + struct.pack("<II", len(bin_), 0x004E4942) + bytes(bin_))
    with open(path, "wb") as f:
        f.write(out)


PAD = {"interior_cutout_padding_m": 0.25}
glb(os.path.join(HERE, "hull_full.glb"), (10, 2, 10, 0),
    {"name": "hull", "pbrMetallicRoughness": {"baseColorFactor": [0.8, 0.7, 0.6, 1]}}, PAD)
glb(os.path.join(HERE, "hull_low.glb"), (10, 2, 10, 0),
    {"name": "hull_low", "pbrMetallicRoughness": {"baseColorFactor": [0.6, 0.6, 0.6, 1]}}, PAD)
glb(os.path.join(HERE, "box.glb"), (1, 1, 1, -0.5),
    {"name": "metal", "pbrMetallicRoughness": {"metallicFactor": 1.0, "roughnessFactor": 0.5,
                                               "metallicRoughnessTexture": {"index": 0}}},
    None, png_rgba(2, 2, (255, 128, 255, 255)))
print("wrote hull_full.glb, hull_low.glb, box.glb")
