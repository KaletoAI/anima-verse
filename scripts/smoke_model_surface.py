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
  base      x[-1,1]      y[0,0.2]     z[-1,1]
  block     x[0,1]       y[0.21,0.8]  z[0,1]     (1 cm CLEAR of the base, see below)
  overhang  x[-1,0]      y[1.5,1.6]   z[0,0.5]      (high: 1.3 of air over the base)
  ledge     x[-1,-0.5]   y[0.8,0.9]   z[-1,-0.5]    (low: 0.6 of air over the base)
Hull: box_min [-1,0,-1], box_max [1,1.6,1]; width 2 m / 0.25 + 1 = 9 nodes per axis;
node (i,j) sits at x = -1 + 0.25 i, z = -1 + 0.25 j; values in cm over box_min.y = 0.
THE BLOCK FLOATS 1 cm OVER THE BASE on purpose: `_hits_below` restarts its ray 10 µm
under the hit it just took, so two COPLANAR faces collapse into a single hit whose
recorded orientation is a matter of traversal order — a base top at 0.2 under a block
underside at 0.2 would make the node's answer an accident. The gap is far too small to
stand in at any scale used here (0.01 model units = 0.1 m at s = 10, see below), so the
block still answers its own top.
Cell rule = lowest UP-facing hit with at least the head-room of air above it. The
head-room is 1.2 WORLD metres and is divided by the placement scale s before the
lattice is walked (fix 2026-08-28); without a target_m, s = 1 and the two coincide:
  node (6,6) = (0.5,0.5): hits 0(down) 0.2(up, base top) 0.21(down, block bottom)
               0.8(up) -> base top has 0.01 of air -> block top -> 80
  node (2,7) = (-0.5,0.75): base only -> 20
  node (2,5) = (-0.5,0.25): 0.2(up) then 1.5(down, overhang) -> 1.3 >= 1.2 -> 20
  node (1,1) = (-0.75,-0.75): 0.2(up) then 0.8(down, ledge) -> 0.6 < 1.2 -> ledge top -> 90
  node (8,0) = (1,-1): cast 1 mm inside the corner -> base only (the block starts at
               z = 0, the ledge ends at x = -0.5) -> 20; without the nudge the ray
               would graze the base's edge and the node would read null
  node (8,8) = (1,1): the OTHER corner, 1 mm inside -> the block covers x[0,1] z[0,1]
               there too -> block top -> 80
extent_snapped under fix 0/0/0 = [2, 1.6, 2].

THE STEP IS 0.25 WORLD METRES AND THE HEAD-ROOM 1.2 WORLD METRES, while the lattice is
cast in MODEL units (fix 2026-08-28). The same fixture baked with target_m = 20,
measure 'xz': s = target_m / max(ex, ez) = 20 / 2 = 10, so step = 0.25 / 10 = 0.025
model units (step_world = 0.025 * 10 = 0.25) and the air the rule asks for is
1.2 / 10 = 0.12 model units.
cols = rows = ceil(2 / 0.025) + 1 = 81 (81*81 = 6561 <= max_cells 40000, so the doubling
loop never runs). Node (i, j) sits at x = -1 + 0.025 i, z = -1 + 0.025 j, so the three
hand-derived points above move — and one of them CHANGES ITS VALUE, because ten metres
of world are one model unit here:
  model (0.5, 0.5)     -> i = j = (0.5+1)/0.025 = 60  -> the base top has 0.01 of air
                          (0.1 m world), under 0.12 -> block top -> 80
  model (-0.5, 0.25)   -> i = 20, j = 50  -> the base top has 1.3 of air (13 m world)
                          under the high overhang -> the base -> 20
  model (-0.75,-0.75)  -> i = j = 10  -> the base top has 0.6 of air under the ledge,
                          and that is 6 WORLD metres, far over the 1.2 m a figure
                          needs -> the base wins -> 20  (this node read 90 for as long
                          as the 1.2 was compared against model coordinates)
With target_m = 0 the bake knows no world size and keeps the step as handed in: 9x9 @ 0.25,
i.e. exactly the lattice of the first bake above.
The max_cells cap runs AFTER the conversion, on the converted step: with max_cells = 100 and
target_m = 20, step 0.025 gives 81*81 = 6561 > 100, so the step doubles — 0.05 -> 41*41 = 1681,
0.1 -> 21*21 = 441, 0.2 -> 11*11 = 121, all still over 100 — until 0.4 -> ceil(2/0.4)+1 = 6,
6*6 = 36 <= 100. Result: step 0.4 model units, step_world 0.4 * 10 = 4.0 m, 6x6 nodes.
`surface_status` reports the WORLD step, because that is what its label says ("@ 0.25 m"):
81x81 @ 0.25 for that bake, not @ 0.025.
A stored file that names version 2 is a lattice whose head-room was compared in model
units — SURFACE_VERSION is 3 — so it reads back as no surface and its state is "stale",
not "baked".

THE HUT is the head-room's own fixture: a closed shell, written by the same pure-Python
GLB writer, inner height 1.0 model units (glTF axes, y up):
  floor      x,z[-0.8,0.8]   y[-0.1,0]                (INTERIOR ONLY, see below)
  threshold  x[-0.25,0.25]   y[-0.1,0]     z[-1,-0.8]
  walls      the ring where |x| or |z| is in [0.8,1.0], y[0,1.0], with a full-height
             door through the -z wall over x[-0.25,0.25]
  roof       x,z[-1.25,1.25] y[1.0,1.1]                (0.25 of eaves on all four sides)
THE FLOOR STOPS AT THE WALLS, again because this is a box soup and not a watertight
shell: a slab continued under the walls would leave an up-facing face inside solid wall
with the whole room's air over it, and a wall node would answer the floor.
Hull: box_min [-1.25,-0.1,-1.25], box_max [1.25,1.1,1.25], extent_snapped [2.5,1.2,2.5].
Baked at target_m = 5, measure 'xz': s = 5 / 2.5 = 2, so step = 0.25 / 2 = 0.125 model
units, head-room = 1.2 / 2 = 0.6 model units, cols = rows = ceil(2.5/0.125) + 1 = 21, and
node (i,j) sits at x = -1.25 + 0.125 i, z = -1.25 + 0.125 j. Values are cm over
box_min.y = -0.1, so the floor top (y = 0) reads 10 and the roof top (y = 1.1) reads 120.
  inside (10,10) = (0,0): hits -0.1(down) 0(up, floor) 1.0(down, roof underside) 1.1(up)
      -> the floor has 1.0 model units of air = 2.0 WORLD metres, over the 1.2 m a figure
      needs -> the floor -> 10.  (The whole bug: 1.0 < 1.2 read as model units -> 120.)
  doorway (10,3) = (0,-0.875): inside the door gap, over the threshold — the same four
      hits -> 10. The wall band is 0.2 thick, so the plan's -0.95 is not a node; -0.875
      is the nearest node whose ray grazes neither a wall face nor the box edge.
  wall (10,17) = (0,0.875): no floor here; hits 0(down, wall bottom), 1.0, 1.1(up). The
      wall top and the roof underside are COPLANAR at 1.0 and collapse into one hit
      (see the block above): recorded up it has 0.1 of air under the roof, under the 0.6
      asked for, and is skipped; recorded down it is skipped for facing down. Either way
      the roof top answers -> 120.
  eaves (10,1) = (0,-1.125): outside the walls, under the overhang — the roof is the
      only up-facing hit and the topmost hit has infinite air -> 120. That is rule R2 as
      it stands: a figure under a free-standing eave is put on top of it.
  crawlspace: the same shell with inner height 0.25 (walls y[0,0.25], roof y[0.25,0.35],
      hull y[-0.1,0.35]) — the floor's air is 0.25 model units = 0.5 WORLD metres, UNDER
      the 1.2 m, so the ledge wins and the interior node answers the roof top,
      (0.35 + 0.1) * 100 = 45. The two huts pin the unit from both sides.
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
         ((0, 0.21, 0), (1, 0.8, 1)),
         ((-1, 1.5, 0), (0, 1.6, 0.5)),
         ((-1, 0.8, -1), (-0.5, 0.9, -0.5))]


def hut_boxes(inner_h):
    """The hut of the docstring: floor, threshold, four walls with a door in
    the -z one, and a roof with 0.25 of eaves — ``inner_h`` model units of air
    between the floor top and the roof underside."""
    roof_top = inner_h + 0.1
    return [((-0.8, -0.1, -0.8), (0.8, 0.0, 0.8)),               # floor (interior)
            ((-0.25, -0.1, -1.0), (0.25, 0.0, -0.8)),            # threshold
            ((-1.0, 0.0, -1.0), (-0.25, inner_h, -0.8)),         # -z wall, left of door
            ((0.25, 0.0, -1.0), (1.0, inner_h, -0.8)),           # -z wall, right of door
            ((-1.0, 0.0, 0.8), (1.0, inner_h, 1.0)),             # +z wall
            ((-1.0, 0.0, -0.8), (-0.8, inner_h, 0.8)),           # -x wall
            ((0.8, 0.0, -0.8), (1.0, inner_h, 0.8)),             # +x wall
            ((-1.25, inner_h, -1.25), (1.25, roof_top, 1.25))]   # roof + eaves


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

        # ── THE WORLD STEP (fix 2026-08-28) ─────────────────────────────
        # A SECOND, untouched copy of the same fixture: the file above has been
        # truncated, restored and finally had four bytes appended, so it is no
        # longer the mesh the hand table describes.
        scaled = Path(tmp) / "scaled.glb"
        write_glb(scaled, BOXES)
        w = ms.bake_surface(scaled, {"x": 0, "y": 0, "z": 0}, wait_s=60,
                            target_m=20, measure="xz")
        check("bake at target_m=20 returns a surface", w is not None)
        if w:
            check("step 0.25 m world / s 10 = 0.025 model units",
                  near(w["step"], 0.025, 1e-9), str(w["step"]))
            check("step_world is the 0.25 m it was asked for",
                  near(w["step_world"], 0.25, 1e-9), str(w["step_world"]))
            check("target_m/measure are recorded",
                  (w["target_m"], w["measure"]) == (20.0, "xz"),
                  f"{w['target_m']}, {w['measure']}")
            check("cols/rows 81x81", (w["cols"], w["rows"]) == (81, 81),
                  f"{w['cols']}x{w['rows']}")
            check("block top (60,60) = 80", node(w, 60, 60) == 80, str(node(w, 60, 60)))
            check("under high overhang (20,50) = 20", node(w, 20, 50) == 20, str(node(w, 20, 50)))
            check("under the ledge (10,10) = 20 — 6 m of world air, not 0.6 m",
                  node(w, 10, 10) == 20, str(node(w, 10, 10)))
            # The admin line promises METRES on the ground: 81x81 @ 0.25 m,
            # not @ 0.025 (which is the same resolution in model units).
            wst = ms.surface_status(scaled, {"x": 0, "y": 0, "z": 0})
            check("status baked, 81x81 @ 0.25 m WORLD",
                  (wst["state"], wst["cols"], wst["rows"], wst["step"])
                  == ("baked", 81, 81, 0.25), str(wst))
            check("the payload block is still the eight spec fields",
                  tuple(ms.payload_block(w)) == ("step", "origin", "cols", "rows",
                                                 "values", "box_min", "box_max",
                                                 "extent_snapped"))
        u = ms.bake_surface(scaled, {"x": 0, "y": 0, "z": 0}, wait_s=60)
        check("without a target the step stays as handed in: 9x9 @ 0.25",
              u is not None and (u["cols"], u["rows"]) == (9, 9)
              and near(u["step"], 0.25, 1e-9),
              str(u and (u["cols"], u["rows"], u["step"])))
        # THE CAP RUNS AFTER THE CONVERSION, on the converted step.
        cells = ms.MAX_SURFACE_CELLS
        ms.MAX_SURFACE_CELLS = 100
        try:
            c = ms.bake_surface(scaled, {"x": 0, "y": 0, "z": 0}, wait_s=60,
                                target_m=20, measure="xz")
        finally:
            ms.MAX_SURFACE_CELLS = cells
        check("the cap doubles the CONVERTED step: 6x6 @ 0.4 model units = 4 m world",
              c is not None and (c["cols"], c["rows"]) == (6, 6)
              and near(c["step"], 0.4, 1e-9) and near(c["step_world"], 4.0, 1e-9),
              str(c and (c["cols"], c["rows"], c["step"], c["step_world"])))
        # A v2 file compared its head-room in MODEL units — it must not be read
        # back as a floor, it must be re-baked.
        sp2 = ms.surface_path(scaled)
        old = json.loads(sp2.read_text(encoding="utf-8"))
        old["version"] = 2
        sp2.write_text(json.dumps(old), encoding="utf-8")
        check("a version-2 file reads as no surface",
              ms.read_surface(scaled, {"x": 0, "y": 0, "z": 0}) is None)
        check("...and its state is stale",
              ms.surface_status(scaled, {"x": 0})["state"] == "stale",
              ms.surface_status(scaled, {"x": 0})["state"])

        # ── THE HEAD-ROOM IS A WORLD LENGTH TOO (fix 2026-08-28) ────────
        # The hut of the docstring, baked at the size it is placed at: inside
        # it a figure has 2 m of world air over the floor, so the floor is what
        # the lattice answers — while the eaves outside still answer the roof.
        hut = Path(tmp) / "hut.glb"
        write_glb(hut, hut_boxes(1.0))
        hs = ms.bake_surface(hut, {"x": 0, "y": 0, "z": 0}, wait_s=60,
                             target_m=5, measure="xz")
        check("the hut bakes", hs is not None)
        if hs:
            check("hut box_min", all(near(a, b) for a, b in zip(hs["box_min"], [-1.25, -0.1, -1.25])), str(hs["box_min"]))
            check("hut box_max", all(near(a, b) for a, b in zip(hs["box_max"], [1.25, 1.1, 1.25])), str(hs["box_max"]))
            check("hut cols/rows 21x21", (hs["cols"], hs["rows"]) == (21, 21),
                  f"{hs['cols']}x{hs['rows']}")
            check("hut step 0.25 m world / s 2 = 0.125 model units",
                  near(hs["step"], 0.125, 1e-9) and near(hs["step_world"], 0.25, 1e-9),
                  f"{hs['step']}, {hs['step_world']}")
            check("inside the hut (10,10) = 10 — the FLOOR, 2 m of air over it",
                  node(hs, 10, 10) == 10, str(node(hs, 10, 10)))
            check("in the doorway (10,3) = 10 — the floor as well",
                  node(hs, 10, 3) == 10, str(node(hs, 10, 3)))
            check("on the wall (10,17) = 120 — the roof top",
                  node(hs, 10, 17) == 120, str(node(hs, 10, 17)))
            check("under the eaves (10,1) = 120 — the roof top (R2 as it stands)",
                  node(hs, 10, 1) == 120, str(node(hs, 10, 1)))
        # THE COUNTER-PROOF: 0.5 m of world air is too little to stand up in,
        # so the crawlspace's interior answers its roof, not its floor.
        crawl = Path(tmp) / "crawlspace.glb"
        write_glb(crawl, hut_boxes(0.25))
        cs = ms.bake_surface(crawl, {"x": 0, "y": 0, "z": 0}, wait_s=60,
                             target_m=5, measure="xz")
        check("the crawlspace bakes", cs is not None)
        if cs:
            check("inside the crawlspace (10,10) = 45 — the roof top, 0.5 m is too low",
                  node(cs, 10, 10) == 45, str(node(cs, 10, 10)))


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
