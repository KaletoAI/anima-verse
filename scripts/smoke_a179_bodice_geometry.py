"""Smoke: A179 — a template bodice is built OUTSIDE the drape's collider (no vertex starts inside the body).

Usage:
    ./.venv/bin/python scripts/smoke_a179_bodice_geometry.py [data.json ...]

No server, no world DB, no LLM, no hub job. Part A runs here (``paths.init`` into a temp dir first). Part B needs
``mathutils`` and therefore runs this same file inside Blender (``runner.find_executable``; without a usable
Blender part B is reported as SKIPPED and the script fails, because nothing geometric was checked). Every body in
part B is made of boxes by hand, so every expected number below is arithmetic, not a recording.
``data.json`` files (the ``data`` of a real ``run_drape``) are judged by part C.

The functions of part B do not exist at d98133fca (``section_row``, ``neck_ring``, ``_surface_z``, ``_exit_out``,
``_lay_path``, ``window_cols``, ``sleeve_ring_count``, ``gd.signed_out``, ``gd.signed_depth``): there the bodice
rows above the chest band came from a torso-only radius.

PART A — core (app/core/garment_template.py)
[A1] TEMPLATE_VERSION is 5 (the same parameters drape differently since A179).
[A2] build_args: ``drape_quality`` = round(fabric quality x BODICE_DRAPE_QUALITY 1.5) for a piece with a bodice,
     the fabric's own for a skirt. top/medium: 6 -> 9; top/flowing: 7 -> round(10.5) = 10 (banker's rounding);
     top/stiff: 6 -> 9; skirt/medium: 6 -> 6; top/medium at quality_scale 2: fabric 12 -> 18.

PART B — geometry (app/blender/scripts/garment_template_build.py, garment_template_drape.py)
Constants read from the module: BODICE_CLEAR_M 0.01, MIN_COS 0.35, ARM_REACH_M 0.08, LAYER_GAP_M 0.015,
PATH_STEP_M 0.008, NECK_RING_CLEAR_M 0.012, SLEEVE_EDGE_M 0.015, WINDOW_COLS 5, WINDOW_COLS_MAX 9.

[B1] signed_out / signed_depth on the box x, y in [0, 1], z in [-1, 0]:
     * p = (1.02, 0.5, 0.01) lies off the box's edge: nearest point (1, 0.5, 0), distance
       sqrt(0.02^2 + 0.01^2) = 22.36 mm. offset . face-normal read 10 or 20 mm there (A178's navel bug: 33 mm read
       as 8). Expected signed depth +22.36 mm.
     * p = (0.5, 0.5, -0.005): 5 mm inside the top face -> -5.0 mm.
     * p = (0.5, 0.5, 0.5) with reach 0.15: nothing that close -> 0.15.
[B2] inside_report, thickness 4 mm (short = closer than 4 + 3 = 7 mm), region a = three points over the box's top
     at z = -0.005, +0.004, +0.02: verts 3, inside 1, max_inside_mm 5.0, short 2.
[B3] _surface_z. Chest box x, y in [-0.2, 0.2], z in [1.0, 1.4]; chin box x in [-0.05, 0.05], y in [-0.15, -0.05],
     z in [1.5, 1.6] (an overhang 0.1 above the chest); shirt box x, y in [0.05, 0.15], z in [1.405, 1.413]
     (a layer 5 mm over the chest):
     * (0, -0.1) from 1.55 — the ray starts INSIDE the chin: leaves it at 1.5, enters the chest at 1.4 -> 1.4, nz 1.
     * (0, -0.1) from 1.70 — enters the chin at 1.6, leaves at 1.5, gap 0.1 > 0.015 -> the chest: 1.4.
     * (0.1, 0.1) from 1.55 — enters the shirt at 1.413, gap to the chest 5 mm <= 15 mm -> stays 1.413.
     * (0.3, 0) from 1.55 to floor 1.3: nothing, and nothing above -> None.
     * (0.1, -0.1) from 1.35 to floor 1.30: inside the chest all the way, the chest's top is above -> INSIDE.
[B4] _exit_out from (0, 0, 1.2) along +x: the chest's wall at 0.2 -> (0.2, cos 1). With a shell x in [0.205, 0.213]
     (gap 5 mm) -> 0.213. With a shell x in [0.23, 0.24] (gap 30 mm) -> 0.2. From (0.3, 0, 1.2), outside -> None.
[B5] section_row on a cross-shaped prism (z 1.0..1.6): torso x in [-0.15, 0.15], y in [-0.10, 0.10], arms
     y in [-0.05, 0.05] out to x = +-0.60. Axis (0, 0), z 1.3, armhole planes x = +-0.20:
     * 0 deg, a window column: the plane is crossed inside the arm -> state 1, r0 = 0.20, xy (0.20, 0).
     * 12 deg, not a window column: the plane is crossed at 0.2 / cos 12 = 0.20447, y = 0.04251 < 0.05 (inside the
       arm); the arm's back face y = 0.05 is left at 0.05 / sin 12 = 0.24049, 0.03602 beyond the plane (< 0.08);
       the cosine there is sin 12 = 0.208 < MIN_COS, so the clearance is 0.01 / 0.35 = 0.02857 -> state 2,
       r0 = 0.24049 + 0.02857 = 0.26906.
     * 10 deg, not a window column: the exit lies 0.05 / sin 10 - 0.2 / cos 10 = 0.28794 - 0.20309 = 0.08485 beyond
       the plane, more than ARM_REACH_M -> state 1, r0 = 0.20309.
     * 15 deg: the plane is crossed at y = 0.05359, outside the arm; coming in, the arm's back face is met at
       0.05 / sin 15 = 0.19319 (cosine 0.2588 < 0.35) -> state 0, r0 = 0.19319 + 0.02857 = 0.22176.
     * 45 deg: the torso's back face y = 0.10 at 0.14142 (x = 0.10), cosine 0.7071 -> r0 = 0.14142 + 0.01414
       = 0.15556.
     * 90 deg: 0.10 + 0.01 = 0.11.
     * the axis at (0, 0.5), outside the body -> None (the caller keeps the torso-only rule).
[B6] _lay_path on the chest box, clear 8 mm: knots (-0.02, 0, 1.403) -> (0.02, 0, 1.403), 3 mm over the top:
     ceil(0.04 / 0.008) = 5 pieces -> 6 points 8 mm apart, knot indices [0, 5], every z = 1.408. The same knots at
     z 1.39 (10 mm INSIDE): every z = 1.408 again. At z 1.45 nothing moves.
[B7] neck_ring. Neck = a 64-sided prism of radius 0.06 round (0, -0.01), z 1.3..1.8; Neck joint (0, 0, 1.50), Head
     joint (0, -0.05, 1.60) (bent forward: the axis runs 0.5 forward per unit up); z_ring 1.52 -> centre
     (0, -0.01). Every column: 0.06 (0.05993 at a facet's middle) + 0.012 = 0.072.
     With a "trapezius" box x in [-0.2, 0.2], y in [0, 0.15], z in [1.0, 1.525] behind the neck: at z_ring the back
     column (90 deg) leaves the body at y = 0.15, 0.16 from the centre; 1 cm higher (1.53 > 1.525) only the neck
     is left: 0.06. The narrowest counts behind the neck -> 0.072 there too (0.16 + 0.012 would be capped at
     neck_r 0.115 + 0.03 = 0.145). A boat neck (neck_r 0.20) keeps 0.20 everywhere.
[B8] window_cols(need, 80 columns of 4.5 deg): an arm root 0.05 deep at 0.20 from the axis with the rows' 0.01
     clearance and 0.015 room -> atan2(0.075, 0.20) = 20.56 deg -> ceil(4.57) = 5; 0.09 deep (the two copies)
     -> atan2(0.115, 0.20) = 29.90 deg -> ceil(6.64) = 7; 80 deg -> capped at 9; 0 -> 5.
[B9] sleeve_ring_count: girths 0.45 and 0.39 -> mean 0.42 / 0.015 = 28 (loop of 48); girth 0.9, loop 36 -> 36
     (never more than the loop); girth 0.09 -> max(12, 6) = 12.

PART C — real drapes (optional ``data.json`` arguments): every region of ``bodice.inside`` has inside 0 and
max_inside_mm 0.0, the clearance pass moved nothing farther than 5 mm, stretch_max <= 1.3, and every re-spaced
neckline vertex keeps NECK_MIN_STEP_M: no built edge under 1 mm (``stretch_at.short_edges`` 0).
"""
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAILS = []


def check(label, ok, got=None):
    print(("ok   " if ok else "FAIL ") + label + ("" if ok else f"  (got {got!r})"))
    if not ok:
        FAILS.append(label)


def near(a, b, tol):
    return a is not None and abs(a - b) <= tol


def part_b():
    import numpy as np
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    sys.path.insert(0, str(ROOT / "app" / "blender" / "scripts"))
    import garment_template_build as gb
    import garment_template_drape as gd

    def box(x0, x1, y0, y1, z0, z1, verts, faces):
        o = len(verts)
        verts += [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
                  (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
        for f in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
            faces.append(tuple(o + i for i in f))          # wound outward

    def tree_of(*boxes):
        verts, faces = [], []
        for b in boxes:
            box(*b, verts, faces)
        return BVHTree.FromPolygons([Vector(v) for v in verts], faces)

    # [B1] / [B2]
    t = tree_of((0, 1, 0, 1, -1, 0))
    sd = gd.signed_depth(t, [(1.02, 0.5, 0.01), (0.5, 0.5, -0.005), (0.5, 0.5, 0.5)])
    check("[B1] off the edge: +22.36 mm", near(sd[0] * 1000, 22.36, 0.01), sd[0])
    check("[B1] 5 mm inside: -5.0 mm", near(sd[1] * 1000, -5.0, 0.001), sd[1])
    check("[B1] nothing within reach: 0.15", near(sd[2], 0.15, 1e-9), sd[2])
    rep = gb.inside_report(t, [(0.5, 0.5, -0.005), (0.5, 0.5, 0.004), (0.5, 0.5, 0.02)], {"a": [0, 1, 2], "b": []},
                           0.004)
    check("[B2] region report", rep == {"a": {"verts": 3, "inside": 1, "max_inside_mm": 5.0, "short": 2}}, rep)

    # [B3]
    chest, chin, shirt = (-0.2, 0.2, -0.2, 0.2, 1.0, 1.4), (-0.05, 0.05, -0.15, -0.05, 1.5, 1.6), \
        (0.05, 0.15, 0.05, 0.15, 1.405, 1.413)
    t = tree_of(chest, chin, shirt)
    z = gb._surface_z(t, 0.0, -0.1, 1.55, 1.3)
    check("[B3] a ray starting inside the chin finds the chest: 1.4", bool(z) and near(z[0], 1.4, 1e-6) and near(z[1], 1.0, 1e-6), z)
    z = gb._surface_z(t, 0.0, -0.1, 1.70, 1.3)
    check("[B3] over the chin: the chest under the 0.1 gap", bool(z) and near(z[0], 1.4, 1e-6), z)
    z = gb._surface_z(t, 0.1, 0.1, 1.55, 1.3)
    check("[B3] a layer 5 mm over the chest stays the surface: 1.413", bool(z) and near(z[0], 1.413, 1e-6), z)
    check("[B3] beside the body: None", gb._surface_z(t, 0.3, 0.0, 1.55, 1.3) is None)
    z = gb._surface_z(t, 0.1, -0.1, 1.35, 1.30)
    check("[B3] inside the chest all the way: INSIDE", z is not None and not z and z is gb.INSIDE, z)

    # [B4]
    e = gb._exit_out(tree_of(chest), (0, 0, 1.2), (1, 0, 0), 0.5)
    check("[B4] the chest's wall: 0.2, cos 1", e is not None and near(e[0], 0.2, 1e-6) and near(e[1], 1.0, 1e-6), e)
    e = gb._exit_out(tree_of(chest, (0.205, 0.213, -0.1, 0.1, 1.1, 1.3)), (0, 0, 1.2), (1, 0, 0), 0.5)
    check("[B4] through a layer 5 mm off: 0.213", e is not None and near(e[0], 0.213, 1e-6), e)
    e = gb._exit_out(tree_of(chest, (0.23, 0.24, -0.1, 0.1, 1.1, 1.3)), (0, 0, 1.2), (1, 0, 0), 0.5)
    check("[B4] not through a gap of 30 mm: 0.2", e is not None and near(e[0], 0.2, 1e-6), e)
    check("[B4] from outside: None", gb._exit_out(tree_of(chest), (0.3, 0, 1.2), (1, 0, 0), 0.5) is None)

    # [B5] the cross prism, built face by face (no face inside the body)
    V, F = [], []

    def wall(x0, y0, x1, y1):                               # a side face from (x0, y0) to (x1, y1), outward = right
        o = len(V)
        V.extend([(x0, y0, 1.0), (x1, y1, 1.0), (x1, y1, 1.6), (x0, y0, 1.6)])
        F.append((o, o + 1, o + 2, o + 3))
    outline = [(-0.15, -0.10), (0.15, -0.10), (0.15, -0.05), (0.60, -0.05), (0.60, 0.05), (0.15, 0.05), (0.15, 0.10),
               (-0.15, 0.10), (-0.15, 0.05), (-0.60, 0.05), (-0.60, -0.05), (-0.15, -0.05)]
    for a, b in zip(outline, outline[1:] + outline[:1]):   # counter-clockwise seen from above: outward on the right
        wall(*a, *b)
    for x0, x1, y0, y1 in ((-0.15, 0.15, -0.10, 0.10), (0.15, 0.60, -0.05, 0.05), (-0.60, -0.15, -0.05, 0.05)):
        o = len(V)
        V.extend([(x0, y0, 1.6), (x1, y0, 1.6), (x1, y1, 1.6), (x0, y1, 1.6),
                  (x0, y0, 1.0), (x0, y1, 1.0), (x1, y1, 1.0), (x1, y0, 1.0)])
        F.extend([(o, o + 1, o + 2, o + 3), (o + 4, o + 5, o + 6, o + 7)])
    cross = BVHTree.FromPolygons([Vector(v) for v in V], F)
    degs = [0, 12, 10, 15, 45, 90]
    ang = [math.radians(d) for d in degs]
    sec = gb.section_row(cross, (0.0, 0.0), ang, 1.3, (0.20, -0.20), {0})
    check("[B5] a section is read", sec is not None)
    if sec is not None:
        xy, r0, st = sec
        want = [(1, 0.20), (2, 0.26906), (1, 0.20309), (0, 0.22176), (0, 0.15556), (0, 0.11)]
        for d, (ws, wr), s_, r_ in zip(degs, want, st, r0):
            check(f"[B5] {d} deg: state {ws}, r0 {wr}", int(s_) == ws and near(float(r_), wr, 2e-5), (int(s_), float(r_)))
        check("[B5] the window column ends on the plane: (0.20, 0)", near(xy[0][0], 0.20, 1e-9) and near(xy[0][1], 0.0, 1e-9), xy[0])
    check("[B5] the axis outside the body: None", gb.section_row(cross, (0.0, 0.5), ang, 1.3, (0.20, -0.20), {0}) is None)

    # [B6]
    t = tree_of(chest)
    Q, idx = gb._lay_path(t, [(-0.02, 0, 1.403), (0.02, 0, 1.403)], 0.008)
    step = np.linalg.norm(np.diff(Q, axis=0), axis=1)
    check("[B6] 6 points, knots [0, 5], 8 mm apart", len(Q) == 6 and idx == [0, 5] and np.allclose(step, 0.008, atol=1e-6), (len(Q), idx, step))
    check("[B6] 3 mm over the top -> laid at 1.408", np.allclose(Q[:, 2], 1.408, atol=1e-6), Q[:, 2])
    Q, _ = gb._lay_path(t, [(-0.02, 0, 1.39), (0.02, 0, 1.39)], 0.008)
    check("[B6] 10 mm inside -> laid at 1.408", np.allclose(Q[:, 2], 1.408, atol=1e-6), Q[:, 2])
    Q, _ = gb._lay_path(t, [(-0.02, 0, 1.45), (0.02, 0, 1.45)], 0.008)
    check("[B6] clear of the body: unmoved", np.allclose(Q[:, 2], 1.45, atol=1e-9), Q[:, 2])

    # [B7] the bones are stubbed: neck_ring only asks for the Neck and Head joints
    bones = {"Neck": np.array((0.0, 0.0, 1.50)), "Head": np.array((0.0, -0.05, 1.60))}
    gb._bone_world = lambda arm, name, rest=True: bones[name]
    nv, nf = [], []
    n = 64
    for i in range(n):
        a = 2 * math.pi * i / n
        nv += [(0.06 * math.cos(a), -0.01 + 0.06 * math.sin(a), 1.3), (0.06 * math.cos(a), -0.01 + 0.06 * math.sin(a), 1.8)]
    for i in range(n):
        j = (i + 1) % n
        nf.append((2 * i, 2 * j, 2 * j + 1, 2 * i + 1))
    nf += [tuple(2 * i + 1 for i in range(n)), tuple(2 * i for i in reversed(range(n)))]
    cols = [1.5 * math.pi + c * 2 * math.pi / 16 for c in range(16)]        # column 0 = the front, 4 = left, 8 = back
    neck = BVHTree.FromPolygons([Vector(v) for v in nv], nf)
    q, r, info = gb.neck_ring(neck, None, {"neck_r": 0.115, "neckline": "crew"}, cols, 1.52)
    check("[B7] the centre follows the neck axis: (0, -0.01)", near(q[0], 0.0, 1e-9) and near(q[1], -0.01, 1e-9), q)
    check("[B7] every column 0.072 (0.0719 at a facet's middle)", info["source"] == "surface" and float(r.min()) > 0.0718 and float(r.max()) < 0.0721, (float(r.min()), float(r.max())))
    tv, tf = list(nv), list(nf)
    box(-0.2, 0.2, 0.0, 0.15, 1.0, 1.525, tv, tf)
    trap = BVHTree.FromPolygons([Vector(v) for v in tv], tf)
    q, r, info = gb.neck_ring(trap, None, {"neck_r": 0.115, "neckline": "crew"}, cols, 1.52)
    check("[B7] behind the neck the narrowest section counts: 0.072, not 0.145", near(float(r[8]), 0.072, 2e-4), float(r[8]))
    check("[B7] in front: 0.072", near(float(r[0]), 0.072, 2e-4), float(r[0]))
    q, r, info = gb.neck_ring(neck, None, {"neck_r": 0.20, "neckline": "boat"}, cols, 1.52)
    check("[B7] a boat neck keeps its 0.20", np.allclose(r, 0.20, atol=1e-9), (float(r.min()), float(r.max())))

    # [B8] / [B9]
    got = [gb.window_cols(math.atan2(0.05 + 0.01 + 0.015, 0.20), 80), gb.window_cols(math.atan2(0.09 + 0.01 + 0.015, 0.20), 80),
           gb.window_cols(math.radians(80), 80), gb.window_cols(0.0, 80)]
    check("[B8] window_cols 5 / 7 / 9 / 5", got == [5, 7, 9, 5], got)
    got = [gb.sleeve_ring_count([0.45, 0.39], 48), gb.sleeve_ring_count([0.9], 36), gb.sleeve_ring_count([0.09], 36)]
    check("[B9] sleeve_ring_count 28 / 36 / 12", got == [28, 36, 12], got)
    consts = (gb.BODICE_CLEAR_M, gb.MIN_COS, gb.ARM_REACH_M, gb.LAYER_GAP_M, gb.PATH_STEP_M, gb.NECK_RING_CLEAR_M,
              gb.SLEEVE_EDGE_M, gb.WINDOW_COLS, gb.WINDOW_COLS_MAX, gb.NECK_MIN_STEP_M)
    check("[B] the constants the numbers above were derived from", consts == (0.01, 0.35, 0.08, 0.015, 0.008, 0.012, 0.015, 5, 9, 0.010), consts)


def part_a():
    import os
    tmp = tempfile.mkdtemp(prefix="smoke_a179_")
    os.environ["STORAGE_DIR"] = tmp
    os.environ["INSTANCE_DIR"] = tmp
    sys.path.insert(0, str(ROOT))
    from app.core import paths
    paths.init(tmp)
    from app.core import garment_template as gt
    check("[A1] TEMPLATE_VERSION 5", gt.TEMPLATE_VERSION == 5, gt.TEMPLATE_VERSION)
    spec = {"row_y": [1.0], "measure": {}}

    def dq(scale=1.0, **p):
        params, errors = gt.validate_params(p)
        assert not errors, errors
        a = gt.build_args(params, spec, item_id="item_x", quality_scale=scale)
        return a["fabric"]["quality"], a["drape_quality"]
    got = [dq(kind="top", fabric="medium"), dq(kind="top", fabric="flowing"), dq(kind="top", fabric="stiff"),
           dq(kind="skirt", fabric="medium"), dq(2.0, kind="top", fabric="medium")]
    check("[A2] drape_quality 6->9, 7->10, 6->9, skirt 6->6, x2: 12->18", got == [(6, 9), (7, 10), (6, 9), (6, 6), (12, 18)], got)
    return gt


def part_c(files):
    for f in files:
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        b = d.get("bodice") or {}
        ins = b.get("inside") or {}
        tag = f"[C] {Path(f).parent.name}"
        check(f"{tag}: a bodice with an inside report", bool(ins), sorted(b))
        check(f"{tag}: no built vertex inside the body", all(v["inside"] == 0 and v["max_inside_mm"] == 0.0 for v in ins.values()),
              {k: (v["inside"], v["max_inside_mm"]) for k, v in ins.items()})
        check(f"{tag}: the clearance pass moved nothing farther than 5 mm", float((b.get("clear") or {}).get("max_push_mm", 99)) <= 5.0,
              b.get("clear"))
        dr = d.get("drape") or {}
        check(f"{tag}: stretch_max <= 1.3", float(dr.get("stretch_max", 9)) <= 1.3, dr.get("stretch_max"))
        check(f"{tag}: no built edge under 1 mm", int((dr.get("stretch_at") or {}).get("short_edges", 1)) == 0,
              (dr.get("stretch_at") or {}).get("short_edges"))


def main():
    try:
        import bpy  # noqa: F401
    except ImportError:
        bpy = None
    if bpy is not None:
        part_b()
        print("FAILED: " + ", ".join(FAILS) if FAILS else "part B passed")
        sys.exit(1 if FAILS else 0)
    part_a()
    from app.blender import runner
    exe = runner.find_executable()
    if not exe:
        check("[B] a usable Blender to run the geometry checks (SKIPPED)", False, "none found")
    else:
        res = subprocess.run([exe, "--background", "--factory-startup", "--python-exit-code", "1", "--python", str(Path(__file__).resolve())],
                             capture_output=True, text=True, timeout=300)
        lines = [ln for ln in res.stdout.splitlines() if ln.startswith(("ok   ", "FAIL ", "part B", "FAILED"))]
        print("\n".join(lines))
        seen = sum(1 for ln in lines if ln.startswith("ok   "))
        check(f"[B] part B ran in Blender and passed ({seen} checks)", res.returncode == 0 and seen >= 30,
              (res.returncode, seen, res.stderr[-400:]))
    part_c(sys.argv[1:])
    print()
    print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL CHECKS PASSED")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
