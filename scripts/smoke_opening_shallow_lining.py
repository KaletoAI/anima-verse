"""Smoke: an opening the worn view shows as body is left out however flush the mesh fills it (Ruling A51).

Usage:
    ./.venv/bin/python scripts/smoke_opening_shallow_lining.py

No server, no world DB, no hub. ``garment_fit.opening_lining`` on synthetic meshes, plus the dense depth image
and the A51 due rule (``expected_fit_version``). Every number below is derived by hand.

FRAME (as smoke_fit_joint_frames [6]). Garment (metres, its own frame): x -0.20 .. 0.20, y 0 .. 0.60, grid step
0.005. Masks 400 x 400: the garment rows 50 .. 349, cols 100 .. 299 -> ``_frame``: 0.60 / 300 = 0.002 m per px, the
mask centre (200, 200) <-> the mesh bbox centre (0, 0.30, zc); col = 200 + x / 0.002, row = 200 - (y - 0.30) / 0.002,
depth = (z - zc) / 0.002 px toward the viewer.

THE PIECE (the remeshed blazer's V, reduced): a FRONT panel with a hole |x| < 0.05, 0.10 < y < 0.40 (faces skipped,
the vertices only they used dropped), at z 0.10 for |x| <= 0.06 and 0.11 for |x| >= 0.065 (the chest beside the
opening stands further out); a flush INSIDE panel at z 0.084, x -0.06 .. 0.06, y 0.10 .. 0.40 (25 x 61 = 1525
vertices, 24 x 60 x 2 = 2880 faces); a BACK panel at z -0.10. The bbox centre zc = (0.11 - 0.10) / 2 = 0.005, so the
depths are: front 47.5 px (the chest 52.5), inside 39.5, back -52.5. The opening mask: rows 150 .. 299, cols
175 .. 224 (= x -0.05 .. 0.048, y 0.40 .. 0.102) — 50 x 150 = 7500 px; the 3 px opening (a diamond of radius 3)
rounds its four corners by 3 + 2 + 1 = 6 px each: the component is 7476 px.

[1] Without the worn-view evidence (``shown`` None): the component's ring (6 px around it, outside the opening: the
    front panel at |x| <= 0.062) lies at 47.5, its front vertices at 39.5 (the 1200 inside vertices with a pixel in
    the opening — x -0.05 .. 0.045 = 20 columns, y 0.105 .. 0.40 = 60 rows — outnumber the 79 rim vertices of the
    hole at 47.5: 60 at x -0.05 and 19 at y 0.40), recess 47.5 - 39.5 = 8.0 px < OPEN_RECESS_PX 15: kept, NOTHING
    left out. This is the old behaviour and the user's black V.
[2] With the evidence over the whole opening (``shown`` = the opening; share 7476 / 7476 = 1.0 >= OPEN_SHOWN_SHARE
    0.5), a recess of 8.0 >= OPEN_SHOWN_RECESS_PX 5 and the ring (rows 144 .. 305, cols 169 .. 230) all inside the
    garment mask (outline 0.0 <= OPEN_SHOWN_OUTLINE_MAX 0.25): dropped ``by: shown``. Seeds: shown pixels, garment >= OPEN_LAYER_PX 30 behind (inside 39.5 - back -52.5 =
    92; the front rim 47.5 + 52.5 = 100 too, but the rim is not recessed), recessed >= OPEN_STEP_PX 10 behind the
    front within OPEN_LOCAL_PX 40 px (the chest at |x| >= 0.065 is within 0.08 m of every inside vertex: 52.5 -
    39.5 = 13; the rim: 52.5 - 47.5 = 5, not recessed). The growth reaches 10 px (manhattan) past the opening and
    the whole inside panel lies within it (x -0.06 = col 170, 5 px out; y 0.10 = row 300, 1 px out; the corner 6
    px), it is connected: EXACTLY the 1525 inside vertices, 2880 faces left out, no front or back panel vertex.
    No face has two inside vertices and one outside (the inside panel is its own component), so no bridge joins.
[3] Evidence over 2 / 5 of the opening only (rows 150 .. 209: 50 x 60 = 3000 px, the two top corners' 12 px not in
    the component: 2988 / 7476 = 0.3997, reported 0.4 < 0.5): kept, nothing.
[3b] The opening at the garment's edge (a slit at a hem, the belly above a waistband): the garment mask without
    rows 50 .. 149 over cols 160 .. 240 and without cols 160 .. 174 over rows 150 .. 349 (its bbox, so the framing,
    unchanged). Outside the mask now: the ring's top band (rows 144 .. 149 x cols 175 .. 224 = 300 px) and its left
    band (rows 150 .. 299 x cols 169 .. 174 = 900 px), at least 1200 px; the whole ring is at most the dilated
    rectangle minus the component, (50 + 12) x (150 + 12) - 7476 = 2568 px: outline >= 1200 / 2568 = 0.467 > 0.25 —
    kept, nothing left out, the evidence notwithstanding.
[3c] A recess under OPEN_SHOWN_RECESS_PX: the inside panel at z 0.094 (depth 44.5): recess 47.5 - 44.5 = 3.0 < 5 —
    kept, nothing left out.
[4] A single-layer back wall: the same front and inside panels WITHOUT the back panel — the inside is the only
    surface behind the opening (the back of a collar). Recess still 8.0, evidence 1.0, dropped ``by: shown`` — but no
    vertex has garment behind it (the inside is the deepest surface at its pixels): nothing left out, no hole.
    Likewise front + back panel only: through the opening the back panel is the only surface (recess 47.5 + 52.5 =
    100 -> ``by: recess``), never layered: nothing left out.
[5] Dense depth images (``_depth_images(dense=True)``): the back panel as TWO triangles (corners x +-0.20, y 0 / 0.60
    -> 200 x 300 px). The 4-step sampling gives at most 15 points per triangle, 30 points, 3 x 3 closing: at most
    270 of the opening's 7500 px see the back panel — the rest see only the inside as the deepest surface, a
    "back wall". Dense (one step per pixel of the longest edge — the diagonal, sqrt(200^2 + 300^2) = 361 px, under
    OPEN_DENSE_MAX 400 — so samples lie at most 1 px apart): all 7500 opening px
    see the back at -52.5 (within 0.01). With the two-triangle back panel [2] holds unchanged: 1525 vertices, 2880
    faces.
[6] The due rule (``expected_fit_version``): FIT_VERSION clothing 15 (13 was Ruling A51's openings, 14 Ruling A72's
    repaired donors — A51's exemption of a version 12 record without a deep opening went with it — and 15 Ruling
    A76's kept sheet order, which changes every clothing fit). Every clothing record below 15 expects 15 (stale) —
    version 12 with a kept deep component, with a shallow one, with all left out, without an opening report;
    versions 11, 13 and 14 — a version 15 record 15; hair / footwear unchanged.
[8] The evidence itself (``garment_source.shown_body``): a base copy 120 x 200 px with alpha — the figure rows
    20 .. 179, cols 30 .. 89 in skin (200, 160, 130), the rest transparent; the worn view on the neutral grey (128,
    128, 128): the same figure, a dark piece (30, 30, 40) over rows 40 .. 119, cols 30 .. 89 except a V window rows
    40 .. 79, cols 50 .. 69 where the skin shows. Shown body = the figure outside the piece the worn view adds: the
    window's interior (rows 42 .. 77, cols 52 .. 67, 36 x 16 = 576 px) all shown, the piece away from it (rows
    85 .. 115, cols 35 .. 84) none, the background none (outside the figure). Without the base copy: None.
[7] The old code (pinned at 33d69c57569c82987d949bc3abc46bf039830f67, the main HEAD this fix starts from): its
    ``opening_lining(P, F, opening, garment_mask)`` leaves NOTHING out of [2]'s piece (recess 8.0 < 15) — the V
    stays filled — while the new code leaves the 2880 faces out.
"""
import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_TMP = tempfile.mkdtemp(prefix="smoke_opening_shallow_lining_")
os.environ["STORAGE_DIR"] = _TMP
from app.core import paths  # noqa: E402

paths.init(_TMP)

import numpy as np  # noqa: E402

from app.core import garment_fit as gf  # noqa: E402

OLD_COMMIT = "33d69c57569c82987d949bc3abc46bf039830f67"
FAILS = []


def check(label, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + label + (f" — {detail}" if detail else ""))
    if not ok:
        FAILS.append(label)


def grid(x0, x1, y0, y1, z, step=0.005, skip=None):
    """A planar grid (z a number or a function of x), two faces per cell; ``skip(cx, cy)`` drops a cell's faces and
    with them the vertices only they used."""
    nx, ny = int(round((x1 - x0) / step)) + 1, int(round((y1 - y0) / step)) + 1
    gx, gy = np.meshgrid(np.linspace(x0, x1, nx), np.linspace(y0, y1, ny), indexing="ij")
    zz = np.vectorize(z)(gx) if callable(z) else np.full(gx.shape, z)
    P = np.stack([gx.ravel(), gy.ravel(), zz.ravel()], 1)
    F = []
    for i in range(nx - 1):
        for j in range(ny - 1):
            a, b, c, d = i * ny + j, (i + 1) * ny + j, i * ny + j + 1, (i + 1) * ny + j + 1
            cx, cy = 0.5 * (P[a, 0] + P[d, 0]), 0.5 * (P[a, 1] + P[d, 1])
            if skip is not None and skip(cx, cy):
                continue
            F += [(a, b, d), (a, d, c)]
    F = np.asarray(F, np.int64)
    used = np.unique(F)
    remap = np.full(len(P), -1, np.int64)
    remap[used] = np.arange(len(used))
    return P[used], remap[F]


def merged(*meshes):
    P, F, base = [], [], 0
    for p, f in meshes:
        P.append(p)
        F.append(f + base)
        base += len(p)
    return np.concatenate(P), np.concatenate(F)


def in_opening(x, y):
    return abs(x) < 0.05 and 0.10 < y < 0.40


front = grid(-0.20, 0.20, 0.0, 0.60, lambda x: 0.10 if abs(x) <= 0.06 + 1e-9 else 0.11, skip=in_opening)
inside = grid(-0.06, 0.06, 0.10, 0.40, 0.084)
back = grid(-0.20, 0.20, 0.0, 0.60, -0.10)
back2 = (np.array([[-0.20, 0.0, -0.10], [0.20, 0.0, -0.10], [0.20, 0.60, -0.10], [-0.20, 0.60, -0.10]]),
         np.array([[0, 1, 2], [0, 2, 3]], np.int64))

gm = np.zeros((400, 400), bool)
gm[50:350, 100:300] = True
op = np.zeros((400, 400), bool)
op[150:300, 175:225] = True

P, F = merged(front, inside, back)
n_front, n_inside = len(front[0]), len(inside[0])
inside_part = np.zeros(len(P), bool)
inside_part[n_front:n_front + n_inside] = True
check("[0] the inside panel: 25 x 61 = 1525 vertices, 2880 faces", n_inside == 1525 and len(inside[1]) == 2880,
      f"{n_inside} / {len(inside[1])}")

# [1] no evidence
lining1, rep1 = gf.opening_lining(P, F, op, gm)
c1 = rep1["components"]
check("[1] one component of 7476 px, recess 8.0 px, kept", len(c1) == 1 and c1[0]["pixels"] == 7476
      and abs(c1[0]["recess_px"] - 8.0) <= 0.05 and not c1[0]["dropped"], f"{c1}")
check("[1] without the evidence nothing is left out", not lining1.any() and rep1["faces"] == 0
      and rep1["shown"] is False, f"{int(lining1.sum())} / {rep1}")

# [2] evidence over the whole opening
lining2, rep2 = gf.opening_lining(P, F, op, gm, op.copy())
c2 = rep2["components"]
check("[2] dropped by the evidence: share 1.0, outline 0.0, by shown", len(c2) == 1 and c2[0]["shown"] == 1.0
      and c2[0]["outline"] == 0.0
      and c2[0]["by"] == "shown" and c2[0]["dropped"] and abs(c2[0]["recess_px"] - 8.0) <= 0.05, f"{c2}")
check("[2] exactly the 1525 inside vertices", int(lining2.sum()) == 1525 and np.array_equal(lining2, inside_part),
      f"{int(lining2.sum())}, outside the inside panel {int((lining2 & ~inside_part).sum())}")
check("[2] 2880 faces left out, the panels whole", rep2["faces"] == 2880
      and int(gf._open_faces(F, lining2).sum()) == len(F) - 2880, f"{rep2['faces']}")

# [3] evidence over 2/5 of the opening
part = np.zeros_like(op)
part[150:210, 175:225] = True
lining3, rep3 = gf.opening_lining(P, F, op, gm, part)
c3 = rep3["components"]
check("[3] share 0.4 < 0.5: kept, nothing left out", len(c3) == 1 and c3[0]["shown"] == 0.4
      and not c3[0]["dropped"] and not lining3.any(), f"{c3}, {int(lining3.sum())}")

# [3b] an opening at the garment's edge
gm_edge = gm.copy()
gm_edge[50:150, 160:241] = False
gm_edge[150:350, 160:175] = False
lining3b, rep3b = gf.opening_lining(P, F, op, gm_edge, op.copy())
c3b = rep3b["components"]
check("[3b] at the garment's edge (outline >= 0.467): kept, nothing left out",
      len(c3b) == 1 and c3b[0]["outline"] >= 0.467 and not c3b[0]["dropped"] and not lining3b.any(),
      f"{c3b}, {int(lining3b.sum())}")

# [3c] a recess under OPEN_SHOWN_RECESS_PX
P3c, F3c = merged(front, grid(-0.06, 0.06, 0.10, 0.40, 0.094), back)
lining3c, rep3c = gf.opening_lining(P3c, F3c, op, gm, op.copy())
c3c = rep3c["components"]
check("[3c] recess 3.0 < 5: kept, nothing left out", len(c3c) == 1 and abs(c3c[0]["recess_px"] - 3.0) <= 0.05
      and not c3c[0]["dropped"] and not lining3c.any(), f"{c3c}, {int(lining3c.sum())}")

# [4] single-layer back walls
P4, F4 = merged(front, inside)
lining4, rep4 = gf.opening_lining(P4, F4, op, gm, op.copy())
c4 = rep4["components"]
check("[4] the flush inside as the only layer: dropped by shown, yet nothing left out",
      len(c4) == 1 and c4[0]["by"] == "shown" and not lining4.any() and rep4["faces"] == 0, f"{c4}, {rep4['faces']}")
P4b, F4b = merged(front, back)
lining4b, rep4b = gf.opening_lining(P4b, F4b, op, gm, op.copy())
c4b = rep4b["components"]
check("[4] the back panel seen through the opening: recess 100 by recess, never left out",
      len(c4b) == 1 and abs(c4b[0]["recess_px"] - 100.0) <= 0.05 and c4b[0]["by"] == "recess"
      and not lining4b.any(), f"{c4b}, {int(lining4b.sum())}")

# [5] dense depth images
P5, F5 = merged(front, inside, back2)
sd, cd, md = gf._frame(P5, gm)
S5 = np.stack([cd[0] + (P5[:, 0] - md[0]) / sd, cd[1] - (P5[:, 1] - md[1]) / sd, (P5[:, 2] - md[2]) / sd], 1)
_f, back_sparse = gf._depth_images(S5, F5, (400, 400))
_f, back_dense = gf._depth_images(S5, F5, (400, 400), dense=True)
sees_sparse = int((back_sparse[op] <= -52.5 + 0.01).sum())
sees_dense = int((np.abs(back_dense[op] + 52.5) <= 0.01).sum())
check("[5] sparse sampling: at most 270 of the 7500 opening px see the back panel", sees_sparse <= 270,
      f"{sees_sparse}")
check("[5] dense sampling: all 7500 opening px see the back at -52.5", sees_dense == 7500, f"{sees_dense}")
inside5 = np.zeros(len(P5), bool)
inside5[n_front:n_front + n_inside] = True
lining5, rep5 = gf.opening_lining(P5, F5, op, gm, op.copy())
check("[5] with the two-triangle back the inside still goes: 1525 vertices, 2880 faces",
      np.array_equal(lining5, inside5) and rep5["faces"] == 2880, f"{int(lining5.sum())} / {rep5['faces']}")

# [6] the due rule
kept = {"components": [{"pixels": 100, "recess_px": 5.0, "dropped": False}], "faces": 0}
shallow = {"components": [{"pixels": 100, "recess_px": 3.0, "dropped": False}], "faces": 0}
gone = {"components": [{"pixels": 100, "recess_px": 50.0, "dropped": True}], "faces": 12}
cases = [
    ({"kind": "clothing", "fit_version": 12, "report": {"opening": kept}}, 15),
    ({"kind": "clothing", "fit_version": 12, "report": {"opening": shallow}}, 15),
    ({"kind": "clothing", "fit_version": 12, "report": {"opening": gone}}, 15),
    ({"kind": "clothing", "fit_version": 12, "report": {"opening": None}}, 15),
    ({"kind": "clothing", "fit_version": 12}, 15),
    ({"kind": "clothing", "fit_version": 11, "report": {"opening": gone}}, 15),
    ({"kind": "clothing", "fit_version": 13, "report": {"opening": kept}}, 15),
    ({"kind": "clothing", "fit_version": 14, "report": {"opening": kept}}, 15),
    ({"kind": "clothing", "fit_version": 15, "report": {"opening": kept}}, 15),
    ({"kind": "hair", "fit_version": 12}, gf.FIT_VERSION["hair"]),
    ({"kind": "footwear", "fit_version": 12, "method": "shoe"}, gf.FIT_VERSION["footwear"]),
]
got = [gf.expected_fit_version(r) for r, _want in cases]
check("[6] FIT_VERSION clothing 15, no A51 exemption left",
      gf.FIT_VERSION["clothing"] == 15 and not hasattr(gf, "CLOTHING_OPENING_UNCHANGED"), f"{gf.FIT_VERSION}")
check("[6] expected versions: every clothing record -> 15, other kinds as before",
      got == [want for _r, want in cases], f"{got}")

# [8] the evidence: worn minus base
from PIL import Image  # noqa: E402
from app.core import garment_source as gsrc  # noqa: E402

copy = gsrc.base_copy("Demo", "item_demo", "f" * 12, "front")
copy.parent.mkdir(parents=True, exist_ok=True)
rgba = np.zeros((200, 120, 4), np.uint8)
rgba[20:180, 30:90] = (200, 160, 130, 255)
Image.fromarray(rgba, "RGBA").save(copy)
worn = np.full((200, 120, 3), 128, np.uint8)
worn[20:180, 30:90] = (200, 160, 130)
worn[40:120, 30:90] = (30, 30, 40)
worn[40:80, 50:70] = (200, 160, 130)
shown8 = gsrc.shown_body("Demo", "item_demo", "f" * 12, worn)
check("[8] the V window's interior is shown body (576 px)", shown8 is not None
      and bool(shown8[42:78, 52:68].all()), f"{None if shown8 is None else int(shown8[42:78, 52:68].sum())}")
check("[8] the piece away from the window and the background are not",
      shown8 is not None and not shown8[85:116, 35:85].any() and not shown8[:, :25].any(),
      f"{None if shown8 is None else (int(shown8[85:116, 35:85].sum()), int(shown8[:, :25].sum()))}")
check("[8] without the base copy: no evidence", gsrc.shown_body("Demo", "item_demo", "e" * 12, worn) is None)

# [7] the old code
try:
    src = subprocess.run(["git", "-C", str(ROOT), "show", f"{OLD_COMMIT}:app/core/garment_fit.py"],
                         capture_output=True, text=True, check=True).stdout
except (subprocess.CalledProcessError, OSError) as e:
    src = ""
    check("[7] the pinned old garment_fit.py is readable", False, str(e))
if src:
    path = Path(_TMP) / "garment_fit_old.py"
    path.write_text(src)
    spec = importlib.util.spec_from_file_location("garment_fit_old", path)
    old = importlib.util.module_from_spec(spec)
    sys.modules["garment_fit_old"] = old      # its dataclasses look their module up
    spec.loader.exec_module(old)
    lining_old, rep_old = old.opening_lining(P, F, op, gm)
    check("[7] the old code leaves nothing out of the flush inside (the V stays filled)",
          not lining_old.any() and rep_old["faces"] == 0 and not rep_old["components"][0]["dropped"],
          f"{rep_old}")
    check("[7] ... the new code with the evidence leaves the 2880 faces out", rep2["faces"] == 2880, f"{rep2['faces']}")

print()
if FAILS:
    print(f"FAILED: {len(FAILS)} — " + "; ".join(FAILS))
    sys.exit(1)
print("ALL PASSED")
