"""Round 2026-11-25b ("the straps are not attached"): a bra's strap strip is sewn onto the cloth at its ends
(``garment_template_fitted.stitch_strip_end`` + ``zipper``) instead of ending as a loose piece over the cup. Every
expectation is derived by hand below; Blender runs headless (no server, no world DB). Skipped with a note when no
Blender is installed.

[Z1] ``zipper`` of run a = (0,0) (1,0) (2,0) (3,0) and run b = (0,1) (1.5,1) (3,1). Arc parameters: a 0, 1/3, 2/3, 1;
     b 0, 1/2, 1. The walk steps along a while a's next parameter <= b's next: 1/3 <= 1/2 -> (a0,a1,b0); 2/3 > 1/2 ->
     (a1,b1,b0); 2/3 <= 1 -> (a1,a2,b1); 1 <= 1 -> (a2,a3,b1); a is done -> (a3,b2,b1). Five triangles,
     (4 - 1) + (3 - 1), exactly these, in this order.
[S1] A cloth sheet on the plane z = 0: x from -0.05 to 0.05, y from -0.05 to 0, a 5 mm grid of quads (its free top
     edge on y = 0 has a vertex every 5 mm). A strip of 5 vertices across (x = -0.01, -0.005, 0, 0.005, 0.01, width
     20 mm) in rows every 5 mm from y = -0.015 to y = 0.1: 24 rows, 23 x 4 quads = 92 quads, 184 triangles.
     Distance of a row to the cloth: rows y = -0.015, -0.010, -0.005 lie on it (0), row y = 0 on its edge (0), row
     y = 0.005 is 5 mm off (>= STITCH_CLEAR_M 3 mm): the end row is index 4, 4 rows are trimmed. Its outer vertices
     (+-0.01, 0.005) meet the edge at (+-0.01, 0) — grid vertices, taken as they are (no split). The run between them
     is the 4 edges through x = -0.01 .. 0.01: 5 vertices, 20 mm = the strip's width (inside STITCH_RUN 0.5 .. 2.5 x).
     Bridge: (5 - 1) + (5 - 1) = 8 triangles; its widest gap is 5 mm (each end-row vertex lies 5 mm over the run).
     The strip keeps rows 4 .. 23 = 20 rows -> 19 x 4 x 2 = 152 triangles, + 8 bridge = 160 faces of its part. The
     four run edges then have two faces each (no longer free), the whole mesh is ONE connected piece (before: two),
     the cloth's own 20 x 10 = 200 quads are untouched and no vertex was added (no split): 21 x 11 = 231 cloth + 24 x 5 =
     120 strip vertices = 351, less the 4 x 5 = 20 trimmed = 331.
[S2] The same strip moved to start at y = 0.03 (never over the cloth): its first row is the end row (0 trimmed), its
     outer vertices lie 30 mm from the free edge (> STITCH_MAX_M 25 mm): the end stays loose — "no free edge near",
     gap 30.0 mm — and the mesh keeps its two pieces.
[S3] ``build_fitted`` sews a strip at its front and — unless a halter (no band end) — at its back
     (``("front", "back") if strips["extend_end"] else ("front",)``), and no longer winds a sewn strip by its own
     vote; the code at main 9c73e57cfc728f90f473aa1b37f0cea6a4865877 had no ``stitch_strip_end`` (the strips stayed
     pieces of their own, its comment: "... it is not joined to the cup or the band it overlaps").

Usage: ./.venv/bin/python scripts/smoke_strap_stitch.py
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_SCRATCH = Path(tempfile.mkdtemp(prefix="smoke-strap-stitch-"))
from app.core import paths  # noqa: E402
paths.init(_SCRATCH / "world")
paths.init_instance(_SCRATCH / "instance")

FAILS = []
OLD = "9c73e57cfc728f90f473aa1b37f0cea6a4865877"


def check(name, ok, detail=""):
    print(("OK   " if ok else "FAIL ") + name + ("" if ok else f"  {detail}"))
    if not ok:
        FAILS.append(name)


src = (ROOT / "app" / "blender" / "scripts" / "garment_template_fitted.py").read_text()
check("[S3] build_fitted sews the front and (not a halter) the back end",
      '(("front", "back") if strips["extend_end"] else ("front",))' in src and "stitch_strip_end(bm, strip_rows[k]" in src)
check("[S3] a sewn strip is not wound by its own vote", "continue                        # sewn on" in src)
old = subprocess.run(["git", "show", f"{OLD}:app/blender/scripts/garment_template_fitted.py"], cwd=ROOT,
                     capture_output=True, text=True)
check(f"[S3] the code at {OLD[:9]} had no stitch (the strips stayed loose)",
      old.returncode == 0 and "stitch_strip_end" not in old.stdout and "joined to the cup or the band it overlaps" in old.stdout,
      old.stderr[-300:])

PROBE = r"""
import sys, json
sys.path.insert(0, sys.argv[-1])
import bmesh
import garment_template_fitted as gf

out = {"clear": gf.STITCH_CLEAR_M, "max": gf.STITCH_MAX_M}
# Z1
bm = bmesh.new()
a = [bm.verts.new((x, 0.0, 0.0)) for x in (0.0, 1.0, 2.0, 3.0)]
b = [bm.verts.new((x, 1.0, 0.0)) for x in (0.0, 1.5, 3.0)]
name = {**{v: f"a{i}" for i, v in enumerate(a)}, **{v: f"b{i}" for i, v in enumerate(b)}}
out["z1"] = [[name[v] for v in t] for t in gf.zipper(a, b)]


def scene(y0):
    bm = bmesh.new()
    part = bm.faces.layers.int.new("uv_part")
    g = {}
    for i in range(21):
        for j in range(11):
            g[i, j] = bm.verts.new((-0.05 + 0.005 * i, -0.05 + 0.005 * j, 0.0))
    for i in range(20):
        for j in range(10):
            fa = bm.faces.new((g[i, j], g[i + 1, j], g[i + 1, j + 1], g[i, j + 1]))
            fa[part] = 18
    rows = []
    y = y0
    while y <= 0.1 + 1e-9:
        rows.append([bm.verts.new((x, y, 0.0)) for x in (-0.01, -0.005, 0.0, 0.005, 0.01)])
        y += 0.005
    strip = []
    for r in range(len(rows) - 1):
        for k in range(4):
            for tri in ((rows[r][k], rows[r + 1][k], rows[r + 1][k + 1]), (rows[r][k], rows[r + 1][k + 1], rows[r][k + 1])):
                fa = bm.faces.new(tri)
                fa[part] = 25
                strip.append(fa)
    return bm, part, rows, strip, g


def pieces(bm):
    seen, n = set(), 0
    for v0 in bm.verts:
        if v0 in seen:
            continue
        n += 1
        st = [v0]
        seen.add(v0)
        while st:
            v = st.pop()
            for e in v.link_edges:
                w = e.other_vert(v)
                if w not in seen:
                    seen.add(w)
                    st.append(w)
    return n


for tag, y0 in (("s1", -0.015), ("s2", 0.03)):
    bm, part, rows, strip, g = scene(y0)
    nv0 = len(bm.verts)
    n_rows = len(rows)
    before = pieces(bm)
    rows2, rec = gf.stitch_strip_end(bm, rows, "front", set(strip), part, 25)
    run_free = [bm.edges.get((g[i, 10], g[i + 1, 10])).is_boundary for i in range(8, 12)]
    out[tag] = {"rec": rec, "rows_before": n_rows, "strip_tris_before": len(strip), "pieces_before": before,
                "pieces": pieces(bm), "strip_faces": sum(1 for fa in bm.faces if fa[part] == 25),
                "cloth_faces": sum(1 for fa in bm.faces if fa[part] == 18),
                "run_free": run_free, "end_row_y": [round(v.co.y, 6) for v in rows2[1]] if len(rows2) > 1 else [],
                "verts_before": nv0, "verts": len(bm.verts),
                "first_row": [[round(v.co.x, 6), round(v.co.y, 6)] for v in rows2[0]]}
print("RESULT " + json.dumps(out))
"""

from app.blender import runner  # noqa: E402
exe = next(iter(runner._candidates()), None)
if exe is None:
    print("SKIP [Z1] [S1] [S2] no Blender installed")
else:
    script = _SCRATCH / "probe.py"
    script.write_text(PROBE)
    res = subprocess.run([exe, "-b", "--factory-startup", "--python", str(script), "--",
                          str(ROOT / "app" / "blender" / "scripts")], capture_output=True, text=True, timeout=600)
    line = next((ln for ln in res.stdout.splitlines() if ln.startswith("RESULT ")), None)
    if line is None:
        check("[Z1] [S1] [S2] Blender probe ran", False, (res.stdout[-1500:], res.stderr[-1500:]))
    else:
        got = json.loads(line[7:])
        check("[S1] STITCH_CLEAR_M 3 mm, STITCH_MAX_M 25 mm (the numbers below use them)",
              (got["clear"], got["max"]) == (0.003, 0.025), (got["clear"], got["max"]))
        check("[Z1] zipper: the five triangles in order",
              got["z1"] == [["a0", "a1", "b0"], ["a1", "b1", "b0"], ["a1", "a2", "b1"], ["a2", "a3", "b1"],
                            ["a3", "b2", "b1"]], got["z1"])
        s1 = got["s1"]
        r = s1["rec"]
        check("[S1] 24 rows, 184 strip triangles, two pieces before",
              (s1["rows_before"], s1["strip_tris_before"], s1["pieces_before"]) == (24, 184, 2), s1)
        check("[S1] sewn: 4 rows trimmed", r.get("stitched") is True and r.get("trimmed_rows") == 4, r)
        check("[S1] the run: 5 vertices, 20 mm, the strip 20 mm wide",
              r.get("run_verts") == 5 and abs(r.get("run_mm", 0) - 20.0) <= 0.05
              and abs(r.get("width_mm", 0) - 20.0) <= 0.05, r)
        check("[S1] bridge: 8 triangles, widest gap 5 mm",
              r.get("bridge_faces") == 8 and abs(r.get("bridge_mm", 0) - 5.0) <= 0.05, r)
        check("[S1] the run is the strip's end row: x -0.01 .. 0.01 on y = 0",
              s1["first_row"] == [[-0.01, 0.0], [-0.005, 0.0], [0.0, 0.0], [0.005, 0.0], [0.01, 0.0]], s1["first_row"])
        check("[S1] the next row is the old end row at y = 0.005", s1["end_row_y"] == [0.005] * 5, s1["end_row_y"])
        check("[S1] 152 + 8 = 160 strip faces, the cloth's 200 quads untouched",
              (s1["strip_faces"], s1["cloth_faces"]) == (160, 200), s1)
        check("[S1] the four run edges are no longer free", s1["run_free"] == [False] * 4, s1["run_free"])
        check("[S1] one piece after the stitch", s1["pieces"] == 1, s1["pieces"])
        check("[S1] 231 cloth + 120 strip vertices, 20 trimmed, none added: 351 -> 331",
              (s1["verts_before"], s1["verts"]) == (351, 331), (s1["verts_before"], s1["verts"]))
        s2 = got["s2"]
        check("[S2] 30 mm off the edge: loose, 'no free edge near', gap 30.0 mm",
              s2["rec"] == {"stitched": False, "why": "no free edge near", "gap_mm": 30.0}, s2["rec"])
        check("[S2] still two pieces", s2["pieces"] == 2, s2["pieces"])

print("FAILED: " + ", ".join(FAILS) if FAILS else "all checks passed")
sys.exit(1 if FAILS else 0)
