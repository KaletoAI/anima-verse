#!/usr/bin/env python3
"""Smoke check for the baked model surface (development_instructions/spec-surface-height.md).

Usage:  ./.venv/bin/python scripts/smoke_model_surface.py

Every expected number is derived BY HAND from the spec here, never recorded.

--- PART 0: the bake's reasons (no Blender needed) ---------------------------
`bake_surface_result` answers (surface, reason): the improvements engine skips a
candidate for good after two failed attempts, so it has to tell a busy machine —
retry, no attempt counted — from a real defect (spec § 10). A path with no file
behind it is stopped by `_source_of` before Blender is ever asked, so it answers
(None, "unreadable"); `bake_surface` is the same call reduced to its first half.

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
The storage side follows from § 4 alone: payload_block hands out exactly the eight fields the
placement spec carries, with the file's own numbers; block_sig is 8 hex chars, the same for the
same block and different once one number moves; surface_status reads "baked" with 9x9 @ 0.25 for
the file just written under its own fix, and "missing" for a path that has no file at all.
Under fix x = 90 (three's Rx: (x,y,z) -> (x, -z, y)): box_min [-1,-1,0], box_max
[1,1,1.6], extent_snapped [2,2,1.6]; the base's z=-1 side now faces UP at y=1:
node at (x=0.5, z=0.1) -> hits -1(down) 1(up) -> (1 - (-1))*100 = 200.

--- PART 2: the sampler (pure, no Blender) -----------------------------------
The SAME hand table drives client3d/scripts/smoke_surface_math.mjs — that equality is
the proof that client and server compute one height (spec § 6.2).

S1: step 1, origin [-1,-1], cols 3, rows 3, box_min [-1,0,-1], box_max [1,1,1],
    extent_snapped [2,1,2], values (j rows of i):
      j=0: [0, 100, 200]   j=1: [0, 100, 200]   j=2: [null, 100, 200]
    -> height = 100*(mx+1) cm on the model's x, one null node at (i=0, j=2).
P1: anchor [4,-3], yaw_deg 90, bottom_y 0.5, max_m 4, measure 'xz'
    s = 4 / max(2,2) = 2;  c = (0, 0.5, 0)
    inverse of three's Ry(+90): lx = -qz, lz = qx   (q = world - anchor)
    model coords m = l / s + c.xz;  u = m.x + 1,  v = m.z + 1
  A  (4,-3)    q=(0,0)      l=(0,0)      m=(0,0)       u=1,    v=1   -> 100 -> 0.5 + 2*1.00 = 2.5
  B  (4,-5)    q=(0,-2)     l=(2,0)      m=(1,0)       u=2,    v=1   -> 200 -> 0.5 + 2*2.00 = 4.5
  C  (2,-2.5)  q=(-2,0.5)   l=(-0.5,-2)  m=(-0.25,-1)  u=0.75, v=0   ->  75 -> 0.5 + 2*0.75 = 2.0
  D  (5,-2)    q=(1,1)      l=(-1,1)     m=(-0.5,0.5)  u=0.5,  v=1.5 -> null neighbour (0,2) -> null
  E  (4,-6)    q=(0,-3)     l=(3,0)      m=(1.5,0)     u=2.5 > cols-1        -> null
P2: like P1 but measure 'xyz', extent_snapped [2,3,2], max_m 4 -> s = 4/3
  F  (4,-3)    as A                                                  -> 100 -> 0.5 + (4/3)*1.00 = 1.8333333
P3: like P1 but yaw_deg 0, so l = q
  G  (3.5,-5)  q=(-0.5,-2)  l=(-0.5,-2)  m=(-0.25,-1)  u=0.75, v=0   ->  75 -> 0.5 + 2*0.75 = 2.0
  H  (4,-3) on S1 with `values` truncated to four entries [0,100,200,0]: A's corner
     indices are 4, 5, 7, 8 — all past the end -> no node -> null. A corrupt sidecar
     reads as a hole (terrain takes over), in Python as in TS, never as an error.
  I  (4,-3) = A with the § A16.9 terrain LIFT 0.75 the placement was moved by after
     placement: the lattice stands where its model stands, so the whole answer moves
     with it -> 2.5 + 0.75 = 3.25. Lift 0 reproduces A exactly.
Highest: [S1@P1, S1@P1 with bottom_y 1.0] at A -> max(2.5, 3.0) = 3.0
         [S1@P1, S1@P1 with bottom_y 1.0] at D -> both null -> null
         [S1@P1, S2] where S2 = S1 with values all null -> A -> 2.5
         lift_of per spec: [S1@P1 lift 0.75, S1@P1 lift 0] at A -> max(3.25, 2.5) =
         3.25, and without lift_of the same pair reads 2.5 — the caller owns the lift.
C and G sample v = 0 on purpose: a point at v = 1 sits in the cell spanning rows
j=1..2, which touches the null node (0,2) and is therefore null by design (D). The
bilinear reading is tested one row of nodes away from that hole, at the same u = 0.75.
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


def part0():
    """The bake's REASONS, without Blender: `bake_surface_result` says WHY there
    is no surface, because the improvements engine has to tell a busy machine
    (retry, no attempt counted) from a defect (skip after two).  A path with no
    file behind it never reaches Blender at all — `_source_of` cannot stat it —
    so the answer is (None, "unreadable"), and the plain wrapper reduces the
    same pair to None, which is every other caller's whole contract."""
    from app.core import model_surface as ms
    with tempfile.TemporaryDirectory() as tmp:
        absent = Path(tmp) / "absent.glb"
        surface, reason = ms.bake_surface_result(absent, {"x": 0}, wait_s=0)
        check("unreadable model: (None, 'unreadable')",
              (surface, reason) == (None, "unreadable"), f"{surface!r}, {reason!r}")
        check("the wrapper answers the surface alone",
              ms.bake_surface(absent, {"x": 0}) is None)
        check("'unreadable' is one of the declared reasons",
              reason in ms.BAKE_REASONS, str(ms.BAKE_REASONS))


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
        block = ms.payload_block(s)
        stored = json.loads(ms.surface_path(glb).read_text(encoding="utf-8"))
        check("payload_block: exactly the eight spec fields",
              tuple(block) == ("step", "origin", "cols", "rows", "values",
                               "box_min", "box_max", "extent_snapped"),
              str(tuple(block)))
        check("payload_block: the file's own numbers",
              all(block[k] == stored[k] for k in block))
        sig = ms.block_sig(block)
        check("block_sig: 8 hex chars", len(sig) == 8 and all(c in "0123456789abcdef" for c in sig), sig)
        check("block_sig: stable for the same block", ms.block_sig(dict(block)) == sig)
        check("block_sig: different after one changed value",
              ms.block_sig(dict(block, step=block["step"] * 2)) != sig)
        st = ms.surface_status(glb, {"x": 0, "y": 0, "z": 0})
        check("status baked, 9x9 @ 0.25",
              (st["state"], st["cols"], st["rows"], st["step"]) == ("baked", 9, 9, 0.25), str(st))
        check("status missing without a file",
              ms.surface_status(Path(tmp) / "absent.glb", {})["state"] == "missing")
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
        # A TRUNCATED FILE READS AS NO SURFACE, never as a KeyError.
        # `payload_block` indexes all eight PAYLOAD_KEYS, so validity has to
        # mean COMPLETE as well as current: dropping `values` from the file the
        # rebake above just wrote (still the right source and the right fix)
        # must turn `read_surface` into None and the state into "stale" — the
        # file is there, so it is not "missing", and it cannot be trusted, so
        # it is not "baked".
        sp = ms.surface_path(glb)
        whole = sp.read_text(encoding="utf-8")
        for lost in ("values", "origin", "extent_snapped"):
            partial = json.loads(whole)
            partial.pop(lost)
            sp.write_text(json.dumps(partial), encoding="utf-8")
            check(f"a file without `{lost}` reads as no surface",
                  ms.read_surface(glb, {"x": 90, "y": 0, "z": 0}) is None)
            check(f"...and its state is stale, not baked (`{lost}`)",
                  ms.surface_status(glb, {"x": 90})["state"] == "stale",
                  ms.surface_status(glb, {"x": 90})["state"])
        sp.write_text(whole, encoding="utf-8")
        check("the restored file is baked again",
              ms.surface_status(glb, {"x": 90})["state"] == "baked",
              ms.surface_status(glb, {"x": 90})["state"])
        glb.write_bytes(glb.read_bytes() + b"\0\0\0\0")
        check("status stale after model change", ms.surface_status(glb, {"x": 90})["state"] == "stale")


S1 = {"step": 1, "origin": [-1, -1], "cols": 3, "rows": 3,
      "box_min": [-1, 0, -1], "box_max": [1, 1, 1], "extent_snapped": [2, 1, 2],
      "values": [0, 100, 200, 0, 100, 200, None, 100, 200]}
P1 = {"anchor": [4, -3], "yaw_deg": 90, "bottom_y": 0.5, "max_m": 4, "measure": "xz"}


def part2():
    from app.core.model_surface import highest_surface_at, surface_height_at as h
    check("A anchor node", near(h(S1, P1, 4, -3), 2.5, 1e-6), str(h(S1, P1, 4, -3)))
    check("B node (2,1)", near(h(S1, P1, 4, -5), 4.5, 1e-6), str(h(S1, P1, 4, -5)))
    check("C bilinear 0.75", near(h(S1, P1, 2, -2.5), 2.0, 1e-6), str(h(S1, P1, 2, -2.5)))
    check("D null neighbour", h(S1, P1, 5, -2) is None)
    check("E outside", h(S1, P1, 4, -6) is None)
    s2 = dict(S1, extent_snapped=[2, 3, 2])
    p2 = dict(P1, measure="xyz")
    check("F measure xyz", near(h(s2, p2, 4, -3), 0.5 + 4 / 3, 1e-6), str(h(s2, p2, 4, -3)))
    p3 = dict(P1, yaw_deg=0)
    check("G yaw 0", near(h(S1, p3, 3.5, -5), 2.0, 1e-6), str(h(S1, p3, 3.5, -5)))
    short = dict(S1, values=[0, 100, 200, 0])
    check("H truncated values", h(short, P1, 4, -3) is None)
    check("I lift 0.75 = 3.25", near(h(S1, P1, 4, -3, 0.75), 3.25, 1e-6),
          str(h(S1, P1, 4, -3, 0.75)))
    check("I lift 0 = A", near(h(S1, P1, 4, -3, 0.0), 2.5, 1e-6))
    lifted = dict(P1, bottom_y=1.0)
    both = [dict(P1, surface=S1), dict(lifted, surface=S1)]
    check("highest at A = 3.0", near(highest_surface_at(both, 4, -3), 3.0, 1e-6))
    check("highest at D = None", highest_surface_at(both, 5, -2) is None)
    blank = dict(S1, values=[None] * 9)
    check("highest skips all-null", near(highest_surface_at([dict(P1, surface=S1), dict(P1, surface=blank)], 4, -3), 2.5, 1e-6))
    # lift_of names ONE spec's lift — the pair below is the same spec twice, so
    # the callable keys on identity, exactly as the client keys on its entry.
    a = dict(P1, surface=S1)
    b = dict(P1, surface=S1)
    lifts = {id(a): 0.75, id(b): 0.0}
    check("highest with lift_of = 3.25",
          near(highest_surface_at([a, b], 4, -3, lambda s: lifts[id(s)]), 3.25, 1e-6))
    check("highest without lift_of = 2.5",
          near(highest_surface_at([a, b], 4, -3), 2.5, 1e-6))


def main():
    print("smoke_model_surface — part 0: the bake's reasons")
    part0()
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
