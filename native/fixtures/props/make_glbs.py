#!/usr/bin/env python3
"""Writes the GLBs and the picture of the Task 18 props world (native/fixtures/props/), stdlib only.

Usage: python3 native/fixtures/props/make_glbs.py   (rewrites the files next to this script)

Every quad is wound counter-clockwise seen from +z (its glTF front), two triangles (a,b,c) (a,c,d).

  frame.glb   ONE mesh, three primitives: "wood" a quad x -0.5..0.5, y 0..1 at z 0; "slot_picture_1" a quad
              x -0.4..0.4, y 0.1..0.9 at z 0.001; "slot_glass_1" the same quad at z 0.002. Box x 1, y 1, z 0.002
              -> extent 1 (xyz), so max_m 1 places it at scale 1.
  mirror.glb  ONE mesh, two primitives: "wood" a quad x -0.25..0.45, y -0.3..0.9 at z 0.1; "slot_glass_1" the
              rectangle of scripts/smoke_mirror_plane.mjs [1]: x -0.15..0.35, y -0.2..0.8 at z 0.2 (centroid
              (0.1, 0.3, 0.2), normal +z by winding). Box x 0.7, y 1.2, z 0.1 -> extent 1.2.
  door.glb    TWO nodes: "frame" (a quad x 0..0.9, y 0..2.1 at z -0.05, material "frame") and "leaf" (a quad
              x 0.05..0.85, y 0..2 at z 0, material "leaf"; the node has no transform). The leaf's box is
              min (0.05, 0, 0), max (0.85, 2, 0) — the scene's door.leaf_bbox.
  poster.png  2 x 2 RGBA, every pixel (200, 40, 40, 255).
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


def quad(x0, x1, y0, y1, z):
    """Four corners ccw from +z, normal +z, UV (0,1) bottom-left ... glTF v runs down from the image top."""
    pos = [(x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z)]
    nor = [(0.0, 0.0, 1.0)] * 4
    uv = [(0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0)]
    return pos, nor, uv, [0, 1, 2, 0, 2, 3]


def write_glb(path, nodes, materials):
    """nodes: [(name, [(material_index, quad), ...])], one mesh per node."""
    bin_ = bytearray()
    views, accessors, meshes = [], [], []

    def add_view(data, target):
        while len(bin_) % 4:
            bin_.append(0)
        views.append({"buffer": 0, "byteOffset": len(bin_), "byteLength": len(data), "target": target})
        bin_.extend(data)
        return len(views) - 1

    def add_acc(values, comps, ctype, typ, target, minmax=False):
        fmt = {5126: "f", 5123: "H"}[ctype]
        flat = [c for v in values for c in (v if isinstance(v, tuple) else (v,))]
        acc = {"bufferView": add_view(struct.pack("<" + fmt * len(flat), *flat), target), "componentType": ctype,
               "count": len(values), "type": typ}
        if minmax:
            acc["min"] = [min(v[i] for v in values) for i in range(comps)]
            acc["max"] = [max(v[i] for v in values) for i in range(comps)]
        accessors.append(acc)
        return len(accessors) - 1

    for _, prims in nodes:
        out = []
        for mat, (pos, nor, uv, idx) in prims:
            out.append({"attributes": {"POSITION": add_acc(pos, 3, 5126, "VEC3", 34962, True),
                                       "NORMAL": add_acc(nor, 3, 5126, "VEC3", 34962),
                                       "TEXCOORD_0": add_acc(uv, 2, 5126, "VEC2", 34962)},
                        "indices": add_acc(idx, 1, 5123, "SCALAR", 34963), "material": mat})
        meshes.append({"primitives": out})
    while len(bin_) % 4:
        bin_.append(0)
    doc = {
        "asset": {"version": "2.0", "generator": "anima native fixtures props/make_glbs.py"},
        "scene": 0, "scenes": [{"nodes": list(range(len(nodes)))}],
        "nodes": [{"name": name, "mesh": i} for i, (name, _) in enumerate(nodes)],
        "meshes": meshes, "materials": materials, "accessors": accessors, "bufferViews": views,
        "buffers": [{"byteLength": len(bin_)}],
    }
    js = json.dumps(doc, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    with open(path, "wb") as f:
        f.write(struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(bin_))
                + struct.pack("<II", len(js), 0x4E4F534A) + js + struct.pack("<II", len(bin_), 0x004E4942) + bytes(bin_))


def mat(name, rgba):
    return {"name": name, "pbrMetallicRoughness": {"baseColorFactor": rgba, "metallicFactor": 0.0, "roughnessFactor": 0.8}}


write_glb(os.path.join(HERE, "frame.glb"),
          [("frame", [(0, quad(-0.5, 0.5, 0, 1, 0)), (1, quad(-0.4, 0.4, 0.1, 0.9, 0.001)), (2, quad(-0.4, 0.4, 0.1, 0.9, 0.002))])],
          [mat("wood", [0.4, 0.25, 0.1, 1]), mat("slot_picture_1", [0.5, 0.5, 0.5, 1]), mat("slot_glass_1", [0.9, 0.95, 1, 1])])
write_glb(os.path.join(HERE, "mirror.glb"),
          [("mirror", [(0, quad(-0.25, 0.45, -0.3, 0.9, 0.1)), (1, quad(-0.15, 0.35, -0.2, 0.8, 0.2))])],
          [mat("wood", [0.4, 0.25, 0.1, 1]), mat("slot_glass_1", [0.8, 0.8, 0.8, 1])])
write_glb(os.path.join(HERE, "door.glb"),
          [("frame", [(0, quad(0, 0.9, 0, 2.1, -0.05))]), ("leaf", [(1, quad(0.05, 0.85, 0, 2, 0))])],
          [mat("frame", [0.3, 0.2, 0.1, 1]), mat("leaf", [0.5, 0.35, 0.2, 1])])
with open(os.path.join(HERE, "poster.png"), "wb") as f:
    f.write(png_rgba(2, 2, (200, 40, 40, 255)))
print("wrote frame.glb, mirror.glb, door.glb, poster.png")
