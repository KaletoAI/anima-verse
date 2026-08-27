#!/usr/bin/env python3
"""Smoke check for the baked model surface (development_instructions/spec-surface-height.md).

Usage:  ./.venv/bin/python scripts/smoke_model_surface.py

Every expected number is derived BY HAND from the spec here, never recorded.

--- PART 1: the bake (needs Blender; prints SKIP and exits 0 without it) -----
A GLB written in pure Python, four axis-aligned boxes (glTF axes, y up):
  base      x[-1,1]      y[0,0.2]    z[-1,1]
  block     x[0,1]       y[0.2,0.8]  z[0,1]
  overhang  x[-1,0]      y[1.5,1.6]  z[0,0.5]      (high: 1.3 m air over the base)
  ledge     x[-1,-0.5]   y[0.8,0.9]  z[-1,-0.5]    (low: 0.6 m air over the base)
Hull: box_min [-1,0,-1], box_max [1,1.6,1]; width 2 m / 0.25 + 1 = 9 nodes per axis;
node (i,j) sits at x = -1 + 0.25 i, z = -1 + 0.25 j; values in cm over box_min.y = 0.
Cell rule = lowest UP-facing hit with >= 1.2 m of air above it:
  node (6,6) = (0.5,0.5): hits 0(down) 0.2(up, base top) 0.2(down, block bottom)
               0.8(up) -> base top has 0 m air -> block top -> 80
  node (2,7) = (-0.5,0.75): base only -> 20
  node (2,5) = (-0.5,0.25): 0.2(up) then 1.5(down, overhang) -> 1.3 m >= 1.2 -> 20
  node (1,1) = (-0.75,-0.75): 0.2(up) then 0.8(down, ledge) -> 0.6 m < 1.2 -> ledge top -> 90
  node (8,0) = (1,-1): cast 1 mm inside the corner -> base only (the block starts at
               z = 0, the ledge ends at x = -0.5) -> 20; without the nudge the ray
               would graze the base's edge and the node would read null
  node (8,8) = (1,1): the OTHER corner, 1 mm inside -> the block covers x[0,1] z[0,1]
               there too -> block top -> 80
extent_snapped under fix 0/0/0 = [2, 1.6, 2].
Under fix x = 90 (three's Rx: (x,y,z) -> (x, -z, y)): box_min [-1,-1,0], box_max
[1,1,1.6], extent_snapped [2,2,1.6]; the base's z=-1 side now faces UP at y=1:
node at (x=0.5, z=0.1) -> hits -1(down) 1(up) -> (1 - (-1))*100 = 200.

--- PART 2: the sampler (pure, no Blender) — see the table in Task 2 ---------
"""
import json
import struct
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FAILURES = []


def check(label, ok, detail=""):
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


def near(a, b, eps=1e-3):
    return a is not None and b is not None and abs(float(a) - float(b)) <= eps


def box_tris(lo, hi):
    """12 outward-wound (CCW from outside) triangles of an axis-aligned box."""
    x0, y0, z0 = lo
    x1, y1, z1 = hi
    v = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
         (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    faces = [(4, 5, 6, 7),   # +z front
             (1, 0, 3, 2),   # -z back
             (5, 1, 2, 6),   # +x
             (0, 4, 7, 3),   # -x
             (7, 6, 2, 3),   # +y top
             (0, 1, 5, 4)]   # -y bottom
    tris = []
    for a, b, c, d in faces:
        tris += [(a, b, c), (a, c, d)]
    return v, tris


def write_glb(path, boxes):
    positions = []
    indices = []
    for lo, hi in boxes:
        v, tris = box_tris(lo, hi)
        base = len(positions)
        positions += v
        for t in tris:
            indices += [base + i for i in t]
    pos_bytes = b"".join(struct.pack("<fff", *p) for p in positions)
    idx_bytes = b"".join(struct.pack("<I", i) for i in indices)
    while len(pos_bytes) % 4:
        pos_bytes += b"\0"
    blob = pos_bytes + idx_bytes
    while len(blob) % 4:
        blob += b"\0"
    mins = [min(p[k] for p in positions) for k in range(3)]
    maxs = [max(p[k] for p in positions) for k in range(3)]
    gltf = {
        "asset": {"version": "2.0"},
        "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}],
        "buffers": [{"byteLength": len(blob)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(pos_bytes), "target": 34962},
            {"buffer": 0, "byteOffset": len(pos_bytes), "byteLength": len(idx_bytes), "target": 34963}],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": len(positions),
             "type": "VEC3", "min": mins, "max": maxs},
            {"bufferView": 1, "componentType": 5125, "count": len(indices), "type": "SCALAR"}],
    }
    js = json.dumps(gltf, separators=(",", ":")).encode()
    while len(js) % 4:
        js += b" "
    total = 12 + 8 + len(js) + 8 + len(blob)
    with open(path, "wb") as fh:
        fh.write(struct.pack("<III", 0x46546C67, 2, total))
        fh.write(struct.pack("<II", len(js), 0x4E4F534A) + js)
        fh.write(struct.pack("<II", len(blob), 0x004E4942) + blob)


BOXES = [((-1, 0, -1), (1, 0.2, 1)),
         ((0, 0.2, 0), (1, 0.8, 1)),
         ((-1, 1.5, 0), (0, 1.6, 0.5)),
         ((-1, 0.8, -1), (-0.5, 0.9, -0.5))]


def node(surface, i, j):
    return surface["values"][j * surface["cols"] + i]


def part1():
    from app.blender import runner
    from app.core import model_surface as ms
    if not runner.is_available():
        print("  SKIP part 1 — Blender not available")
        return
    print(f"  Blender {runner.version()}")
    with tempfile.TemporaryDirectory() as tmp:
        glb = Path(tmp) / "fixture.glb"
        write_glb(glb, BOXES)
        s = ms.bake_surface(glb, {"x": 0, "y": 0, "z": 0}, wait_s=60)
        check("bake returns a surface", s is not None)
        if not s:
            return
        check("surface file exists", ms.surface_path(glb).exists())
        check("cols/rows 9x9", (s["cols"], s["rows"]) == (9, 9), f"{s['cols']}x{s['rows']}")
        check("box_min", all(near(a, b) for a, b in zip(s["box_min"], [-1, 0, -1])), str(s["box_min"]))
        check("box_max", all(near(a, b) for a, b in zip(s["box_max"], [1, 1.6, 1])), str(s["box_max"]))
        check("extent_snapped fix 0", all(near(a, b) for a, b in zip(s["extent_snapped"], [2, 1.6, 2])), str(s["extent_snapped"]))
        check("origin", all(near(a, b) for a, b in zip(s["origin"], [-1, -1])), str(s["origin"]))
        check("block top (6,6) = 80", node(s, 6, 6) == 80, str(node(s, 6, 6)))
        check("free base (2,7) = 20", node(s, 2, 7) == 20, str(node(s, 2, 7)))
        check("under high overhang (2,5) = 20", node(s, 2, 5) == 20, str(node(s, 2, 5)))
        check("under low ledge (1,1) = 90", node(s, 1, 1) == 90, str(node(s, 1, 1)))
        check("corner (8,0) nudged inside = 20", node(s, 8, 0) == 20, str(node(s, 8, 0)))
        check("corner (8,8) nudged inside, block above = 80", node(s, 8, 8) == 80, str(node(s, 8, 8)))
        check("read_surface valid", ms.read_surface(glb, {"x": 0, "y": 0, "z": 0}) is not None)
        check("read_surface stale under another fix", ms.read_surface(glb, {"x": 90, "y": 0, "z": 0}) is None)
        check("status stale", ms.surface_status(glb, {"x": 90})["state"] == "stale")
        r = ms.bake_surface(glb, {"x": 90, "y": 0, "z": 0}, wait_s=60)
        check("rebake under fix x=90", r is not None)
        if r:
            check("x90 box_min", all(near(a, b) for a, b in zip(r["box_min"], [-1, -1, 0])), str(r["box_min"]))
            check("x90 box_max", all(near(a, b) for a, b in zip(r["box_max"], [1, 1, 1.6])), str(r["box_max"]))
            check("x90 extent_snapped", all(near(a, b) for a, b in zip(r["extent_snapped"], [2, 2, 1.6])), str(r["extent_snapped"]))
            # node nearest (x=0.5, z=0.1): i = (0.5+1)/0.25 = 6, j = (0.1-0)/0.25 = 0.4 -> j=0 is z=0
            # (cast 1 mm inside) — the base's side face at y=1 answers: 200
            check("x90 side face up (6,0) = 200", node(r, 6, 0) == 200, str(node(r, 6, 0)))
        glb.write_bytes(glb.read_bytes() + b"\0\0\0\0")
        check("status stale after model change", ms.surface_status(glb, {"x": 90})["state"] == "stale")


def part2():
    pass  # Task 2 fills this in


def main():
    print("smoke_model_surface — part 1: bake")
    part1()
    print("smoke_model_surface — part 2: sampler")
    part2()
    if FAILURES:
        print(f"\n{len(FAILURES)} FAILED: {FAILURES}")
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
