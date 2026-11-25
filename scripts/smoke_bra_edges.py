"""Round 2026-11-25 review of the top with cups: a bra's free edges (``BRA_EDGE_VERSION``). The bra region keeps the
collider's faces by their centroids, so an edge the region predicate draws across the triangles follows them in a
sawtooth (a light fringe along the back band's top edge and the hem, from every view). The builder now cuts the
collider along the underbust line first and smooths the free edges along themselves
(``garment_template_fitted._relax_edges``). Every expectation is derived by hand below; Blender runs headless (no
server, no world DB). Skipped with a note when no Blender is installed.

[E1] A closed boundary loop on the plane z = 0: a regular 16-gon of radius 0.1 m whose vertices are pushed out and in
     by a = 0.004 m in turn (a sawtooth round a circle). One relax step moves a vertex to
     0.5 v + 0.25 (v_prev + v_next). For the alternating part (+a, -a, +a ...) that is 0.5 a + 0.25 (-a - a) = 0: one
     step removes the sawtooth entirely; the circle part shrinks a little (a chord average): the radius of a regular
     n-gon after one step is r (0.5 + 0.5 cos(2 pi / n)) = 0.1 x 0.9619 = 0.09619 m. Projection onto the plane z = 0
     keeps every vertex on it. After ``EDGE_RELAX_STEPS`` (6) steps the radius is 0.1 x 0.9619^6 = 0.0792 m on the
     plane (the collider here is the plane z = 0, so the projection keeps z = 0). Checked: the spread of the radii after the steps (max - min) <= 0.1 mm (sawtooth gone), every z = 0, the
     radius equals 0.1 x 0.9619^6 within 0.1 mm.
[E2] A straight boundary run stays on its line: a strip of 40 quads along x on z = 0 whose long edges lie on y = 0
     and y = 0.01 (the bisected band top is such a line). Its outline is one closed loop; the four corners move
     (each has one neighbour on a short edge — the band's ends round off) and a step carries a move one neighbour
     further, so after ``EDGE_RELAX_STEPS`` (6) steps every vertex at least 7 from a corner (indices 7..33) keeps y
     within 1 µm of its line (the mean of two points on a line is on it; Blender keeps float32 coordinates),
     and a corner did move (> 1 mm).
[E3] ``garment_template.tsig`` of a bra and of a top with cups carries ``bra_edges`` (proved in
     ``smoke_top_cups_params`` [P6] and ``smoke_garment_template`` [16]); here only: ``BRA_EDGE_VERSION`` is 2 (1: cut + relaxed edges; 2: owner rulings 1 and 6 —
     straps as strips, cups inside the back outline).

Usage: ./.venv/bin/python scripts/smoke_bra_edges.py
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_SCRATCH = Path(tempfile.mkdtemp(prefix="smoke-bra-edges-"))
from app.core import paths  # noqa: E402
paths.init(_SCRATCH / "world")
paths.init_instance(_SCRATCH / "instance")
from app.core import garment_template as gt  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(("OK   " if ok else "FAIL ") + name + ("" if ok else f"  {detail}"))
    if not ok:
        FAILS.append(name)


check("[E3] BRA_EDGE_VERSION is 2", getattr(gt, "BRA_EDGE_VERSION", None) == 2, getattr(gt, "BRA_EDGE_VERSION", None))

PROBE = r"""
import sys, math, json
sys.path.insert(0, sys.argv[-1])
import bmesh
from mathutils import Vector
from mathutils.bvhtree import BVHTree
import garment_template_fitted as gf

def plane_tree():
    bm = bmesh.new()
    vs = [bm.verts.new((x, y, 0.0)) for x, y in ((-0.3, -0.3), (0.3, -0.3), (0.3, 0.3), (-0.3, 0.3))]
    bm.faces.new(vs)
    return BVHTree.FromBMesh(bm)

out = {}
# E1: a fan of triangles round a sawtooth 16-gon (centre vertex inside, the rim is the boundary loop)
n, r, a = 16, 0.1, 0.004
bm = bmesh.new()
c = bm.verts.new((0.0, 0.0, 0.0))
rim = []
for i in range(n):
    t = 2 * math.pi * i / n
    rr = r + (a if i % 2 == 0 else -a)
    rim.append(bm.verts.new((rr * math.cos(t), rr * math.sin(t), 0.0)))
for i in range(n):
    bm.faces.new((c, rim[i], rim[(i + 1) % n]))
bm.verts.ensure_lookup_table()
gf._relax_edges(bm, plane_tree())
rad = [math.hypot(v.co.x, v.co.y) for v in rim]
out["e1"] = {"spread": max(rad) - min(rad), "mean": sum(rad) / n, "zmax": max(abs(v.co.z) for v in rim),
             "steps": gf.EDGE_RELAX_STEPS}
# E2: a strip of quads along x, its long edges on y = 0 and y = 0.01
bm = bmesh.new()
lo = [bm.verts.new((0.01 * i, 0.0, 0.0)) for i in range(41)]
hi = [bm.verts.new((0.01 * i, 0.01, 0.0)) for i in range(41)]
for i in range(40):
    bm.faces.new((lo[i], lo[i + 1], hi[i + 1], hi[i]))
bm.verts.ensure_lookup_table()
gf._relax_edges(bm, plane_tree())
out["e2"] = max(max(abs(v.co.y) for v in lo[7:34]), max(abs(v.co.y - 0.01) for v in hi[7:34]))
out["e2_corner"] = (lo[0].co - Vector((0.0, 0.0, 0.0))).length
print("RESULT " + json.dumps(out))
"""

from app.blender import runner  # noqa: E402
exe = next(iter(runner._candidates()), None)
if exe is None:
    print("SKIP [E1] [E2] no Blender installed")
else:
    script = _SCRATCH / "probe.py"
    script.write_text(PROBE)
    res = subprocess.run([exe, "-b", "--factory-startup", "--python", str(script), "--",
                          str(ROOT / "app" / "blender" / "scripts")], capture_output=True, text=True, timeout=600)
    line = next((ln for ln in res.stdout.splitlines() if ln.startswith("RESULT ")), None)
    if line is None:
        check("[E1] [E2] Blender probe ran", False, (res.stdout[-1500:], res.stderr[-1500:]))
    else:
        got = json.loads(line[7:])
        e1 = got["e1"]
        want = 0.1 * (0.5 + 0.5 * 0.9238795325112867) ** e1["steps"]    # cos(2 pi / 16) = 0.92388
        check("[E1] the sawtooth is gone (radius spread <= 0.1 mm)", e1["spread"] <= 1e-4, e1)
        check("[E1] every vertex stays on the plane", e1["zmax"] <= 1e-9, e1)
        check(f"[E1] radius = 0.1 x 0.9619^{e1['steps']} = {want:.4f} m (within 0.1 mm)",
              abs(e1["mean"] - want) <= 1e-4, e1)
        check("[E2] a straight boundary run stays on its line (7+ from a corner)", got["e2"] <= 1e-6, got["e2"])
        check("[E2] a corner rounds off (moved > 1 mm)", got["e2_corner"] > 1e-3, got["e2_corner"])

print("FAILED: " + ", ".join(FAILS) if FAILS else "all checks passed")
sys.exit(1 if FAILS else 0)
