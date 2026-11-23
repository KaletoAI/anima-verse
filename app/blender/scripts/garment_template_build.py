"""Drape one garment template onto a plain rigged body (P1, Ruling A138).

Runner contract (``app/blender/runner.py``): ``inputs`` {body: the plain rigged
base GLB, front / back: the piece's views (cut-outs or the item picture)},
``params`` from ``app.core.garment_template.build_args``:

* ``spec``    the sampled pygarment panels (``panel_spec``): rows x cols grids per
              panel (front, back; each half the circumference), ``row_y`` = the
              world height of every row (Blender Z = glTF Y), row 0 = the pinned top;
* ``fabric``  bending / mass / quality / shrink of the cloth run;
* ``slit``    {side: none|left|right|front|back, depth_m}: vertical edges at that
              angle are split from the hem up;
* ``node``    the name of the exported garment node (``garment_…``);
* ``poses``   the poses measured after the drape (spike evaluator), ``render``.

Steps: wrap the panel rows round the body axis (radius = the pattern's own, never
closer than 2 cm outside the body; the pinned top row FOLLOWS the body at 6 mm —
the spike's open point), merge the side seams, split the slit, pin the top row,
cloth-drape on the voxel-remeshed posed body (spike ``drape``), measure stretch,
Solidify 1.5 mm, project the views onto the panel UVs, skin by Data Transfer,
measure the poses, export armature + garment. Wall and CPU seconds are reported
for the drape and the whole script.

``cut_only`` (``app.core.garment_template_cut``): the run stops right after the
panels are cut, laid out of the body (``clear_of_body``) and given their pattern UVs — no drape, no pose shapes, no
bake, no export. Its only output is ``islands.json``, byte-identical to the one the full run writes for the same
inputs (the UVs are assigned before the cloth run, which only moves vertices). The inputs the cut reads are the body,
the lower layers (colliders), ``spec``, ``torso_half_m``, ``thickness`` and ``slit``; ``fabric``,
``drape_quality``, ``frames``, ``poses``, ``shape_groups``, ``render`` and the views are read only after it.
"""
import math
import sys
import time
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).parent))
from _common import main  # noqa: E402
import garment_template_drape as gd  # noqa: E402
import bake_register as br  # noqa: E402
import garment_template_fitted as gf  # noqa: E402
import stretch_gate as sg  # noqa: E402
import uv_pattern as uvp  # noqa: E402
import corset_darts as cdarts  # noqa: E402
sys.path.pop(0)

#: Angle of each slit side (0 = +X = the character's left, front = -Y).
#: Step 3b (B3): front left / right lie 6 columns (6 * pi / 40 = 0.471239 rad) either side of the front centre, on a
#: column of the 2 x 40-step wrap, so ``split_slit`` (half a column of tolerance) finds them.
SLIT_ANGLE = {"left": 0.0, "back": math.pi / 2, "right": math.pi, "front": 3 * math.pi / 2,
              "front_left": 3 * math.pi / 2 + 6 * math.pi / 40, "front_right": 3 * math.pi / 2 - 6 * math.pi / 40}
TOP_CLEAR_M = 0.006
ROW_CLEAR_M = 0.02
#: Round geometry (plan group B, stage "geometry"): under the crotch the legs of the bind pose run BACKWARD (the leg
#: section's middle lies 8-15 cm behind the waist's centre at mid-calf on the world's bodies). A row wrapped round the
#: waist's centre had to reach round the calves at the back only: Ylva's straight skirt hemmed at a back arc of 0.99 m
#: beside a front of 0.51 m (its back panel 95.7 cm wide, the dress's skirt back 98.5 cm). Each row under the crotch is
#: wrapped round the centre on the front-back line that gives it the SHORTEST girth (the smallest shift within
#: GIRTH_TOL_M of it): a row the pattern's circle already clears keeps the waist's centre (every shift gives the same
#: circle), a row the legs force is shared by front and back.
#: The body's centre line strip (|x - centre| under this) holds no vertex under the crotch.
CROTCH_X_M = 0.015
#: Rows from this far under the crotch on are re-centred (at the crotch the section still holds the seat).
CROTCH_BELOW_M = 0.01
#: The shifts tried (metres along +Y, back), nearest to 0 first among equals.
CENTRE_SHIFTS_M = tuple(round(0.005 * k, 3) for k in range(-20, 51))
GIRTH_TOL_M = 0.001
#: A piece is re-centred only when some row's girth shortens by at least this much (measured: Vallerie's short flared
#: dress at most 8 mm — it keeps its cut byte for byte; Lirien's dress 9 cm, Tilda's wool skirt 17 cm, Ylva's straight
#: skirt 46 cm).
GIRTH_GAIN_MIN_M = 0.02
#: The shift changes by at most this much per metre of height between rows (the rows over the crotch are lifted into
#: it), so the panels lean without a step: the girth-shortest shift jumps to 5 cm in the first row under the crotch.
SHIFT_SLOPE = 0.5


def leg_centres(bco, centre, row_y, radii_of):
    """The wrap centre per row (see CROTCH_X_M), or None when the piece keeps ``centre`` for every row. Under
    ``CROTCH_BELOW_M`` below the crotch (the lowest body vertex on the centre line) each row takes the
    ``CENTRE_SHIFTS_M`` shift along Y whose girth (the closed polygon of ``radii_of(cen, r)`` = ``(angles, radii)``
    round ``cen``) is within ``GIRTH_TOL_M`` of the shortest — the smallest |shift| among those; None when no row
    gains ``GIRTH_GAIN_MIN_M`` by it (or the body has no vertex on the centre line). The shifts are then evened to
    ``SHIFT_SLOPE`` both ways (only ever raised), rows over the crotch included. A row with shift 0 gets ``centre``
    itself (its arithmetic, float32 included, as without a shift)."""
    cx, cy = centre[0], centre[1]
    line = bco[np.abs(bco[:, 0] - cx) < CROTCH_X_M]
    if not len(line):
        return None
    below = float(line[:, 2].min()) - CROTCH_BELOW_M
    shift, gain = [0.0] * len(row_y), 0.0
    for r, z in enumerate(row_y):
        if z >= below:
            continue
        girth = {}
        for sh in CENTRE_SHIFTS_M:
            ang, rad = radii_of((cx, cy + sh), r)
            ang, rad = np.asarray(ang), np.asarray(rad)
            x, y = rad * np.cos(ang), rad * np.sin(ang)
            girth[sh] = float(np.sum(np.hypot(np.diff(np.r_[x, x[:1]]), np.diff(np.r_[y, y[:1]]))))
        best = min(girth.values())
        shift[r] = min((k for k, g in girth.items() if g <= best + GIRTH_TOL_M), key=lambda k: (abs(k), k))
        gain = max(gain, girth[0.0] - girth[shift[r]])
    if gain < GIRTH_GAIN_MIN_M:
        return None
    for order in (range(len(row_y) - 2, -1, -1), range(1, len(row_y))):
        for r in order:
            o = r + 1 if order.step < 0 else r - 1
            lim = SHIFT_SLOPE * abs(float(row_y[r]) - float(row_y[o]))
            if abs(shift[o]) - lim > abs(shift[r]) and shift[o] * shift[r] >= 0:
                shift[r] = shift[o] - math.copysign(lim, shift[o])
    return [centre if sh == 0 else (cx, cy + sh) for sh in shift]


def centre_at(row_c, row_y):
    """``z -> (x, y)``: the row centres of ``leg_centres`` between the rows (linear in Z, the end rows held)."""
    zs = np.asarray(row_y, float)[::-1]
    ys = np.asarray([c[1] for c in row_c], float)[::-1]
    cx = float(row_c[0][0])
    return lambda z: (cx, float(np.interp(z, zs, ys)))


def wrap_radii(spec, btree, row_c_r, r, z=None):
    """The radius per column of row ``r`` of ``wrap`` round ``row_c_r`` (both panels, the band rows' rule aside):
    ``(angles, radii)`` — the girth ``leg_centres`` compares."""
    spans = {"front": (math.pi, 2 * math.pi), "back": (0.0, math.pi)}
    z = spec["row_y"][r] if z is None else z
    ang_all, rad_all = [], []
    for p in spec["panels"]:
        row = np.array(p["grid_m"][r])
        circ = 2 * float(np.sum(np.linalg.norm(np.diff(row, axis=0), axis=1)))
        a0, a1 = spans[p["name"]]
        cols = spec["cols"]
        for c in range(cols - 1):
            ang = a0 + (a1 - a0) * c / (cols - 1)
            ang_all.append(ang)
            rad_all.append(max(circ / (2 * math.pi), gd.body_radius(btree, row_c_r, ang, z) + ROW_CLEAR_M))
    return ang_all, rad_all


def wrap(spec, btree, centre, band_rows=0, row_c=None):
    """Vertices / quads of the panels wrapped round the body axis, and the indices of the top row (the pin).
    A221: ``spec["top_drop"]`` {panel: [metres per column]} lowers a panel's top edge per column (a sweetheart
    dip); the rows of that column are pressed together linearly between the hem (unmoved) and the lowered top.
    Step 3b (plan group B): the ``band_rows`` vertex rows under the top (a skirt's waistband,
    ``uv_pattern.wrap_parts``) hug the body like the top row (``TOP_CLEAR_M``) — a waistband is fitted, and a band
    standing off by ``ROW_CLEAR_M`` under a top row at 6 mm was a cone its ring strip could not unroll (area 0.59-0.71,
    stretch p95 1.6-4.4 on five skirts).
    Stage "geometry": ``row_c`` (``leg_centres``) = the centre each row is wrapped round (None: ``centre``)."""
    rows, cols = spec["rows"], spec["cols"]
    row_y = spec["row_y"]
    drops = spec.get("top_drop") or {}
    hem_z, top_z = row_y[-1], row_y[0]
    spans = {"front": (math.pi, 2 * math.pi), "back": (0.0, math.pi)}
    verts, faces, angles, top = [], [], [], []
    for pi_, p in enumerate(spec["panels"]):
        g = np.array(p["grid_m"])
        a0, a1 = spans[p["name"]]
        drop = drops.get(p["name"]) or [0.0] * cols
        for r in range(rows):
            row = g[r]
            circ = 2 * float(np.sum(np.linalg.norm(np.diff(row, axis=0), axis=1)))
            for c in range(cols):
                z = row_y[r] - float(drop[c]) * (row_y[r] - hem_z) / max(1e-6, top_z - hem_z)
                if r == 0:
                    top.append(len(verts))
                ang = a0 + (a1 - a0) * c / (cols - 1)
                cen = row_c[r] if row_c else centre
                body_r = gd.body_radius(btree, cen, ang, z)
                if r <= band_rows:
                    rad = body_r + TOP_CLEAR_M if body_r > 0 else circ / (2 * math.pi)
                else:
                    rad = max(circ / (2 * math.pi), body_r + ROW_CLEAR_M)
                verts.append((cen[0] + rad * math.cos(ang), cen[1] + rad * math.sin(ang), z))
                angles.append(ang)
        base = pi_ * rows * cols
        for r in range(rows - 1):
            for c in range(cols - 1):
                i = base + r * cols + c
                faces.append((i, i + 1, i + cols + 1, i + cols))
    return verts, faces, angles, top


def bodice_radii(spec, btree, row_c_r, r):
    """The radius per column of ``build_bodice``'s torso row ``r`` (a row under the chest band: ``row_radii`` with
    its blend weight) round ``row_c_r``: ``(angles, radii)`` — the girth ``leg_centres`` compares."""
    N = 2 * (spec["cols"] - 1)
    angles = np.array([1.5 * math.pi + c * 2 * math.pi / N for c in range(N)])
    z = spec["row_y"][r]
    circ = sum(float(np.sum(np.linalg.norm(np.diff(np.array(p_["grid_m"][r]), axis=0), axis=1)))
               for p_ in spec["panels"])
    w = min(1.0, max(0.0, (z - spec["bodice"]["band_y"]) / ROW_BLEND_M))
    return angles, row_radii(btree, row_c_r, angles, z, circ, w=w)


#: Stage "geometry": an outer layer's sleeve rings are built round the lower layers' collider (``build_bodice``).
OUTER_SLEEVE_CLEAR = True
#: Stage "geometry": how far under the band top a border vertex of a strapped piece is still drawn up onto it — the
#: kept faces' lower corners one row down left notches beside the straps' feet (Lirien's dress: rows ~1 cm apart).
BAND_SNAP_M = 0.012
#: Stage "geometry": a strapped piece's armhole is scooped: the top edge drops by ARMHOLE_DROP_M towards the side seam,
#: from ARMHOLE_DROP_FROM_M outside the strap's outer edge over ARMHOLE_DROP_RAMP_M (Lirien's dress: the band's ends
#: stood up to the armpit and hung out 7 cm from the body as flaps).
ARMHOLE_DROP_M = 0.03
ARMHOLE_DROP_FROM_M = 0.02
ARMHOLE_DROP_RAMP_M = 0.05
#: Stage "geometry": a border edge of a strapped piece's drawn top shorter than this is merged into one point.
STRAP_MERGE_M = 0.008


#: Corset v2 (user report 2026-11-22): a shell vertex standing farther than this outside the surface its own ray met
#: (beyond the clearance) bridges a hollow of the row — the neckline's middle between the cups; such vertices are
#: left out of the top edge's gap and counted on their own.
SHELL_BRIDGE_M = 0.004


#: Corset v2: the hull bridges only the front between the cups — this far round from the front centre (radians; the
#: sweetheart's cups lie within ``garment_template.CUP_HALF_RAD``); elsewhere the shell follows the body itself (a
#: hull over the spine's groove or the folds of a waistband under the hem only added air).
SHELL_HULL_RAD = 0.6
#: Corset v6 (review 2026-11-23 of v5: the cups read as one wide box — the convex hull of the section spanned the
#: whole front between the cups as one flat plane, up to 7 cm off the cleavage): the front's section is CLOSED by a
#: disc of this radius instead (``_close_radius``) — the cloth spans a hollow narrower than the disc and dips into a
#: wider one along an arc of this radius, so two round cups stay two (the cleavage's top 4 cm instead of 7 cm over the
#: skin, under the cups 2 cm instead of 5.5).
SHELL_CLOSE_M = 0.05
SHELL_CLOSE_SAMPLES = 8


def _close_section(angles, radii, rho):
    """Corset v6: the section through the points ``radii * (cos, sin)`` at ``angles`` round the centre (a radius <= 0
    = no point) prepared for ``_close_radius``: its edges and the centres of the discs of radius ``rho`` that touch
    it from outside (``rho`` out along each edge's normal, kept where they stay ``rho`` from every edge); None with
    fewer than 3 points."""
    a = np.asarray(angles, float) % (2 * math.pi)
    r = np.asarray(radii, float)
    ok = r > 0
    order = np.argsort(a[ok])
    a, r = a[ok][order], r[ok][order]
    if len(a) < 3:
        return None
    P = np.c_[np.cos(a) * r, np.sin(a) * r]
    A = P
    AB = np.roll(P, -1, axis=0) - P
    t = (np.arange(SHELL_CLOSE_SAMPLES) + 0.5) / SHELL_CLOSE_SAMPLES
    S = (A[:, None, :] + AB[:, None, :] * t[None, :, None]).reshape(-1, 2)
    N = np.repeat(np.c_[AB[:, 1], -AB[:, 0]], SHELL_CLOSE_SAMPLES, axis=0)      # outward: the points run anticlockwise
    N /= np.linalg.norm(N, axis=1)[:, None] + 1e-15
    sec = {"A": A, "AB": AB, "rho": float(rho)}
    Q = S + N * rho
    sec["Q"] = Q[_section_dist(sec, Q) >= rho * (1 - 1e-6)]
    return sec


def _section_dist(sec, X):
    """Corset v6: the distance of each point of ``X`` (n x 2, round the centre) to the edges of ``sec``."""
    A, AB = sec["A"], sec["AB"]
    AX = X[:, None, :] - A[None]
    t = np.clip((AX * AB[None]).sum(2) / ((AB * AB).sum(1)[None] + 1e-15), 0.0, 1.0)
    return np.linalg.norm(AX - AB[None] * t[..., None], axis=2).min(1)


def _close_radius(sec, ang):
    """Corset v6: the distance from the centre along ``ang`` to the boundary of the section ``sec``
    (``_close_section``) CLOSED by its disc: the smallest radius on the ray that a disc of radius ``rho`` lying wholly
    outside the section still reaches (a point at least ``rho`` from the section, or within ``rho`` of one of the
    touching discs' centres). Never inside the section; 0 without a section."""
    if sec is None:
        return 0.0
    A, AB, rho, Q = sec["A"], sec["AB"], sec["rho"], sec["Q"]
    d = np.array([math.cos(ang), math.sin(ang)])
    den = d[0] * AB[:, 1] - d[1] * AB[:, 0]
    good = np.abs(den) > 1e-15
    tt = np.where(good, (A[:, 0] * AB[:, 1] - A[:, 1] * AB[:, 0]) / np.where(good, den, 1.0), -1.0)
    ss = np.where(good, (A[:, 0] * d[1] - A[:, 1] * d[0]) / np.where(good, den, 1.0), -1.0)
    hit = good & (tt > 0) & (ss >= -1e-9) & (ss <= 1 + 1e-9)
    r0 = float(tt[hit].max()) if hit.any() else 0.0
    lo, hi = r0, r0 + 2 * rho + 0.05
    for _ in range(32):
        mid = (lo + hi) / 2.0
        x = d * mid
        if _section_dist(sec, x[None])[0] >= rho or (len(Q) and (np.linalg.norm(Q - x, axis=1) <= rho).any()):
            hi = mid
        else:
            lo = mid
    return max(r0, hi)


#: Corset v2: each stretch between two rows of a column is checked at this many heights against the body's profile
#: there (``corset_shell``: the row rays alone never see the underside of a lifted chest, which then stood through
#: the chord between two rows).
SHELL_PROFILE_SAMPLES = 8
#: Corset v3 (review 2026-11-22: 1..3 cm under the top edge the shell stood 6..12 mm off the body at the cups' top and
#: under the arms): the build's rays are horizontal, so where the body's surface is nearly horizontal itself (the top of
#: the lifted chest, the underside of the armpit) a stretch cleared along the ray stands far off the surface along its
#: normal. ``corset_shell`` then settles: each vertex farther than ``clear`` + ``SHELL_SETTLE_TOL_M`` from the body
#: moves to ``clear`` off its nearest point (its height by at most ``SHELL_SETTLE_DZ_M``, a third of a row: rows never
#: cross), and the stretches are cleared again — ``SHELL_SETTLE_ROUNDS`` times.
SHELL_SETTLE_TOL_M = 0.001
#: Corset v3: the stretches from the top edge in are raised only where the body stands through them, to this far
#: over the surface (metres; ``corset_shell``'s last pass).
SHELL_EDGE_SKIN_M = 0.0003
#: Corset v3: the front's hull down from the chest (``corset_shell``) ends this far over the waist line, so the waist
#: itself hugs (a hull down to the waist row stood up to 29 mm off the belly just above it). Corset v5: 1.5 cm (was
#: 3.5): the stiff strip (``boned_profile``) turns onto the belly smoothly, and ending it 3.5 cm up left the bend to
#: the settle below it (front_fold 71 degrees there on Rosi, 57 with 1.5 cm).
SHELL_FRONT_WAIST_M = 0.015
SHELL_SETTLE_DZ_M = 0.005
SHELL_SETTLE_ROUNDS = 4
#: Corset v5: the rounds of the top edge's last move onto the skin (``corset_shell``).
SHELL_EDGE_ROUNDS = 4
SHELL_EDGE_TOL_M = 0.0002
#: Corset v5: the top edge's own distance to the skin after that move (metres): under the shell's ``clear``, so the
#: line between two edge vertices stays within 2 mm where it spans a hollow of the skin (the spine's groove, the
#: shoulder blade's edge; ``edge_loop`` measures the line, not only the vertices).
SHELL_EDGE_CLEAR_M = 0.0008
SHELL_EDGE_LINE_M = 0.0017
#: Corset v5: rounds of the (1, 2, 1) smoothing across the front's boned strips (``corset_shell``).
SHELL_STRIP_SMOOTH_ROUNDS = 4
#: Corset v6: rounds of the (1, 2, 1) spread of the stretch pass's raise over the front (``corset_shell``).
SHELL_SPREAD_ROUNDS = 2
#: Corset v6: the rows next to the top edge keep their own raise only (the band ``UNDER_EDGE_M`` under the edge lies
#: on the skin; spread there, the raises of the stretches at the side seam's step stood the band 8 mm off the flank).
SHELL_SPREAD_FROM_ROW = 3


#: Corset v4 (review 2026-11-23): ``cup_edge`` scans a column's edge upward in steps of this many metres, and reads
#: the skin over a candidate edge up to ``CUP_EDGE_LOOK_M`` higher.
CUP_EDGE_STEP_M = 0.002
CUP_EDGE_LOOK_M = 0.03


#: Corset v4: ``chest_tissue`` compares the radius at the apex with the radius this far under it (under the tissue,
#: on the rib cage) as well as at the top row — the cleavage and the flank stand no farther out than either.
CUP_UNDER_M = 0.12


def chest_tissue(btree, centre, ang, apex_z, top_z, tissue_m):
    """Corset v4: whether the body at angle ``ang`` holds chest tissue — its radius at the apex height stands
    ``tissue_m`` over the larger of its radii at the front's top row ``top_z`` and ``CUP_UNDER_M`` under the apex
    (the cleavage and the flank under the arm do not; the build's body tree has no arms, so the flank's top row may
    read a hole)."""
    wall = max(gd.body_radius(btree, centre, ang, top_z), gd.body_radius(btree, centre, ang, apex_z - CUP_UNDER_M))
    return gd.body_radius(btree, centre, ang, apex_z) - wall >= tissue_m


def edge_clears(btree, centre, ang, z, top_z, recede_m, spill_m):
    """Corset v4: whether a top edge at height ``z`` lies on the chest's upper slope at angle ``ang``: the skin 1 cm
    over it recedes by ``recede_m`` and nothing over it, up to ``CUP_EDGE_LOOK_M``, stands out more than ``spill_m``
    beyond it (the skin of a lifted chest standing over the cup edge read as spilling over the cup)."""
    r = gd.body_radius(btree, centre, ang, z)
    if r - gd.body_radius(btree, centre, ang, z + 0.01) < recede_m:
        return False
    for dz in np.arange(0.004, CUP_EDGE_LOOK_M + 1e-9, 0.004):
        if gd.body_radius(btree, centre, ang, z + float(dz)) > r + spill_m:
            return False
    return True


def cup_edge(spec, btree, centre):
    """Corset v4 (review 2026-11-23: the cups covered only the lower half of the lifted chest; at the outer cup the
    skin stood over the edge): raise each front column's top edge (``spec["top_drop"]["front"]``, metres under the top
    row) from its default cup line to the top of the chest tissue at its angle — the lowest height where the edge
    clears (``edge_clears``), at most the top row; only on columns with chest tissue (``chest_tissue``); each such
    column takes the largest raise of its tissue neighbours, smoothed; the columns between take the raise linearly
    between the nearest tissue columns, 0 at the side seams and in the sweetheart dip (raised, never lowered). In place; returns ``{tissue_cols, raised_cols, max_raise_m}``
    and stores ``tissue_cols`` in ``spec["cup_edge"]`` (``corset_shell``'s vertical hull and ``shell_gaps`` read it)."""
    ce = spec.get("cup_edge")
    drops = spec.get("top_drop") or {}
    if not ce or "front" not in drops:
        return None
    cols = int(spec["cols"])
    top_z = float(spec["row_y"][0])
    apex_z = float(ce["apex_y"])
    front = [float(d) for d in drops["front"]]
    dip = [float(d) for d in ce.get("dip") or [0.0] * cols]
    edge = [top_z - d for d in front]
    tissue = []
    raise_ = [0.0] * cols
    for c in range(cols):
        ang = math.pi + math.pi * c / (cols - 1)
        if not chest_tissue(btree, centre, ang, apex_z, top_z, float(ce["tissue_m"])):
            continue
        tissue.append(c)
        z = edge[c]
        while z < top_z and not edge_clears(btree, centre, ang, z, top_z, float(ce["recede_m"]), float(ce["spill_m"])):
            z += CUP_EDGE_STEP_M
        raise_[c] = max(0.0, min(top_z, z) - edge[c])
    # the raise of a tissue column: the largest of its tissue neighbours', then smoothed (1, 2, 1) among them; every
    # other column takes it linearly between the nearest tissue columns either side, 0 at the side seams (the edge
    # meets the back's edge under the arms) and 0 inside the sweetheart dip
    tset = set(tissue)
    up = [0.0] * cols
    for c in tissue:
        up[c] = max(raise_[k] for k in (c - 1, c, c + 1) if 0 <= k < cols and k in tset)
    sm = list(up)
    for c in tissue:
        nb = [(w, up[k]) for w, k in ((1, c - 1), (2, c), (1, c + 1)) if 0 <= k < cols and k in tset]
        sm[c] = max(raise_[c], sum(w * v for w, v in nb) / sum(w for w, _v in nb))
    anchors = sorted(set(tissue) | {0, cols - 1})
    val = {k: (sm[k] if k in tset else 0.0) for k in anchors}
    new = list(edge)
    for c in range(cols):
        if c in tset:
            new[c] = edge[c] + sm[c]
            continue
        if dip[c] > 0:
            continue
        lo = max(k for k in anchors if k <= c)
        hi = min(k for k in anchors if k >= c)
        t = 0.0 if hi == lo else (c - lo) / (hi - lo)
        new[c] = edge[c] + val[lo] * (1 - t) + val[hi] * t
    new = [min(top_z, z) for z in new]
    drops["front"] = [round(top_z - z, 5) for z in new]
    ce["tissue_cols"] = tissue
    raised = [new[c] - edge[c] for c in range(cols)]
    return {"tissue_cols": len(tissue), "raised_cols": int(sum(1 for r in raised if r > 1e-4)),
            "max_raise_m": round(max(raised), 4), "edge_z": [round(z, 4) for z in new],
            "tissue": sorted(tissue), "centre": [round(float(v), 4) for v in centre[:2]]}


#: Corset v5 (review 2026-11-23: two red flaps under the arms — the side and back edge lay on the skin of the fold
#: from the back to the arm, which flares out there): the skin's flare at a top edge — how far it stands out at the
#: edge beyond the straight line through the skin ``UNDERARM_BELOW_M`` under it at the same angle (metres; the gate
#: ``edge_loop_flare`` reads the same flare of the cloth itself, at most 3 mm).
UNDERARM_FLARE_M = 0.0025
UNDERARM_BELOW_M = (0.015, 0.03)
#: ``underarm_edge`` lowers a column's edge in steps of this many metres, at most ``UNDERARM_DROP_MAX_M``.
UNDERARM_STEP_M = 0.002
UNDERARM_DROP_MAX_M = 0.08
#: Corset v5: ``underarm_edge`` also lowers an edge until the skin over the ``UNDERARM_BELOW_M[1]`` under it widens
#: outward by at most this much per metre of height (measured on Rosi: the fold to the arm 0.6-0.75 at its back, a
#: flank 0.25-0.45): an edge on such a slope stands out as a flap even where the slope is straight, so the flare alone
#: does not see it.
UNDERARM_SLOPE_MAX = 0.6
#: Corset v6 (review 2026-11-23 of v5: the edge still dropped into a pointed V beside the side seam, 3.6 cm within a
#: few columns, and the two sides differed): each column's lowering is spread round the waist as a raised cosine of
#: this half-width (columns; ``underarm_edge``) — one wide, round scoop whose bottom is flat — and both sides take the
#: larger lowering of the column and its mirror.
UNDERARM_SPREAD_COLS = 10
#: Corset v5/v6: (1, 2, 1) passes over the EDGE HEIGHT round the waist after the spread (``underarm_edge``), the
#: front's cup edge held as it is: the scoop runs into the cup edge's rise without a corner, never above a column's
#: own need.
UNDERARM_SMOOTH_PASSES = 8


def skin_flare(btree, centre, ang, z):
    """Corset v5: how far the skin at height ``z`` (angle ``ang``) stands out beyond the straight line through the
    skin ``UNDERARM_BELOW_M`` under it (metres; < 0 where it recedes, 0 where the ray meets nothing)."""
    lo, hi = UNDERARM_BELOW_M
    r0 = gd.body_radius(btree, centre, ang, z)
    r1 = gd.body_radius(btree, centre, ang, z - lo)
    r2 = gd.body_radius(btree, centre, ang, z - hi)
    if min(r0, r1, r2) <= 0:
        return 0.0
    return r0 - (r1 + (r1 - r2) * lo / (hi - lo))


def skin_slope(btree, centre, ang, z):
    """Corset v5: how much the skin at angle ``ang`` widens outward per metre of height over ``UNDERARM_BELOW_M[1]``
    under ``z`` (0 where the ray meets nothing)."""
    hi = UNDERARM_BELOW_M[1]
    r0 = gd.body_radius(btree, centre, ang, z)
    r2 = gd.body_radius(btree, centre, ang, z - hi)
    return (r0 - r2) / hi if min(r0, r2) > 0 else 0.0


def underarm_edge(spec, btree, centre):
    """Corset v5 (review 2026-11-23: at both sides under the arms the top edge of the side and back panels stood off
    the torso's outline as two flaps): every column of the back panel and every front column without chest tissue
    (``cup_edge``'s ``tissue_cols``) and outside the sweetheart dip lowers its top edge until the skin there no
    longer flares out (``skin_flare`` <= ``UNDERARM_FLARE_M``) — the edge then runs under the fold from the back
    to the arm, as a corset's edge does, instead of following it outward — nor on skin that widens outward more
    steeply than ``UNDERARM_SLOPE_MAX`` under it (``skin_slope``).
    Corset v6 (review of v5: a pointed V beside the side seam, the two sides uneven): each column's need is the larger
    of its own and its mirror's (the column at the same angle on the other side); the lowering of the ring is the
    largest need spread by a raised cosine of ``UNDERARM_SPREAD_COLS`` columns (round the waist, across the side
    seams); then the EDGE HEIGHT of every free column is smoothed (1, 2, 1) ``UNDERARM_SMOOTH_PASSES`` times with the
    locked front columns (chest tissue, the dip) held, never above a column's own need. A column that ends on the fold
    is lowered on from there and the ring done again. In place on ``spec["top_drop"]``; returns ``{lowered_cols,
    max_drop_m, drops}``."""
    drops = spec.get("top_drop")
    if not drops or "front" not in drops:
        return None
    cols = int(spec["cols"])
    top_z = float(spec["row_y"][0])
    drops.setdefault("back", [0.0] * cols)
    ce = spec.get("cup_edge") or {}
    tissue = set(ce.get("tissue_cols") or ())
    dip = [float(d) for d in ce.get("dip") or [0.0] * cols]
    # the ring round the waist: back columns 0..cols-1 (angles 0..pi), then front 1..cols-2 (pi..2 pi); the side
    # seams are back 0 = front cols-1 and back cols-1 = front 0
    ring = [("back", c, math.pi * c / (cols - 1)) for c in range(cols)] + \
           [("front", c, math.pi + math.pi * c / (cols - 1)) for c in range(1, cols - 1)]
    n = len(ring)
    index = {(p, c): k for k, (p, c, _a) in enumerate(ring)}
    # the mirror (angle a -> pi - a): back c <-> back cols-1-c, front c <-> front cols-1-c
    mirror = [index.get((p, cols - 1 - c), k) for k, (p, c, _a) in enumerate(ring)]
    locked = [p == "front" and (c in tissue or dip[c] > 0) for p, c, _a in ring]
    top0 = [top_z - float(drops[p][c]) for p, c, _a in ring]

    def bad(k, z):
        ang = ring[k][2]
        return (skin_flare(btree, centre, ang, z) > UNDERARM_FLARE_M
                or skin_slope(btree, centre, ang, z) > UNDERARM_SLOPE_MAX)

    def scan(k, low):
        """The least lowering from ``low`` on at which column ``k``'s edge lies clear of the fold."""
        while bad(k, top0[k] - low) and low < UNDERARM_DROP_MAX_M - 1e-9:
            low += UNDERARM_STEP_M
        return low

    def kernel(d):
        return 0.5 * (1.0 + math.cos(math.pi * d / UNDERARM_SPREAD_COLS)) if d < UNDERARM_SPREAD_COLS else 0.0

    need = [0.0 if locked[k] else scan(k, 0.0) for k in range(n)]
    wide = list(need)
    for _round in range(6):
        need = [0.0 if locked[k] else max(need[k], 0.0 if locked[mirror[k]] else need[mirror[k]]) for k in range(n)]
        spread = [0.0 if locked[k] else max(need[j] * kernel(min(abs(k - j), n - abs(k - j))) for j in range(n))
                  for k in range(n)]
        z = [top0[k] - spread[k] for k in range(n)]
        for _ in range(UNDERARM_SMOOTH_PASSES):
            z = [z[k] if locked[k] else min(top0[k] - need[k], (z[(k - 1) % n] + 2 * z[k] + z[(k + 1) % n]) / 4.0)
                 for k in range(n)]
        wide = [max(0.0, top0[k] - z[k]) for k in range(n)]
        # a column the spread or the smoothing left on the fold goes on down from there (the next round again)
        moved = [k for k in range(n) if not locked[k] and wide[k] > need[k] + 1e-6 and bad(k, top0[k] - wide[k])]
        if not moved:
            break
        for k in moved:
            need[k] = scan(k, wide[k])
    for (p, c, _a), low in zip(ring, wide):
        drops[p][c] = round(float(drops[p][c]) + low, 5)
        if p == "back" and c == 0:
            drops["front"][cols - 1] = drops["back"][0]
        if p == "back" and c == cols - 1:
            drops["front"][0] = drops["back"][cols - 1]
    return {"lowered_cols": int(sum(1 for w in wide if w > 1e-4)), "max_drop_m": round(max(wide), 4),
            "drops": [round(w, 4) for w in wide]}


#: Corset v5: ``boned_profile`` solves its strip on heights this far apart (metres) and clamps it on the body over
#: ``BONE_CLAMP_M`` under the waist end, so it leaves the body there along the body's own slope.
BONE_STEP_M = 0.003
BONE_CLAMP_M = 0.03
#: Corset v6 (review 2026-11-23 of v5: the cups read as a box — a flat front, a hard lower corner, a straight wedge
#: from the apex to the waist in the side view): the strip is also drawn onto the body (or the closed section over the
#: cleavage) with this weight per metre of strip (``bone_bend``'s ``pull``). Against the bending it sets a length of
#: about (1 / pull) ** 0.25 (3.3 cm): the strip follows the cup round its apex and curves in under it instead of
#: running straight from the apex to the rib cage.
BONE_PULL = 1e6
#: Corset v6: the band under the top edge (metres, the depth of ``UNDER_EDGE_M``) is drawn on with this weight
#: instead (length about 1.5 cm): the edge band lies on the skin, where the light pull left it standing up to 6 mm off.
BONE_PULL_EDGE_M = 0.05
BONE_PULL_EDGE = 2e7
#: Corset v6: rounds of ``boned_profile``'s re-solve against the straight stretches between its rows, and the shortfall
#: (metres) it leaves.
BONE_CHORD_ROUNDS = 6
BONE_CHORD_TOL_M = 0.0002


def bone_bend(z, lo, fixed, pull=0.0):
    """Corset v5: the radii ``r`` over the heights ``z`` (descending) of least bending — the sum over the inner
    points of the squared second difference (in metres, for uneven spacing), weighted by its spacing — with ``r >= lo``
    everywhere and ``r = lo`` at the indices ``fixed`` (an active-set solve: points pressed against ``lo`` join the
    fixed ones; a pressed point whose bending pulls it off ``lo`` is let go again). Corset v6: plus ``pull`` x the sum
    of (r - lo)^2 x its spacing (the strip drawn onto ``lo``; 0 = the plain least bending; one weight per point or
    one for all)."""
    z = np.asarray(z, float)
    lo = np.asarray(lo, float)
    n = len(z)
    D = np.zeros((max(0, n - 2), n))
    for i in range(1, n - 1):
        h0, h1 = z[i - 1] - z[i], z[i] - z[i + 1]
        a, c = 2.0 / (h0 * (h0 + h1)), 2.0 / (h1 * (h0 + h1))
        wgt = math.sqrt((h0 + h1) / 2.0)
        D[i - 1, i - 1], D[i - 1, i], D[i - 1, i + 1] = a * wgt, -(a + c) * wgt, c * wgt
    # the spacing of each point (half its two neighbours' distances) weights its pull
    span = np.zeros(n)
    if n > 1:
        dz = np.abs(np.diff(z))
        span[:-1] += dz / 2.0
        span[1:] += dz / 2.0
    wpull = np.broadcast_to(np.asarray(pull, float), (n,)) * span
    A = D.T @ D + np.diag(wpull)
    b = wpull * lo
    fixed = set(int(i) for i in fixed)
    pressed = set()
    r = lo.copy()
    for _it in range(4 * n):
        F = sorted(fixed | pressed)
        U = [i for i in range(n) if i not in fixed and i not in pressed]
        r = lo.copy()
        if U:
            r[U] = np.linalg.solve(A[np.ix_(U, U)], b[U] - A[np.ix_(U, F)] @ lo[F])
        low = [i for i in U if r[i] < lo[i] - 1e-7]
        if low:
            pressed.update(low)
            continue
        g = A @ r - b
        let = [i for i in pressed if g[i] < -1e-6 * max(1.0, float(np.abs(g).max()))]
        if not let:
            break
        pressed.discard(min(let, key=lambda i: g[i]))
    return r


def boned_profile(btree, centre, ang, zs, rads, clear, bot=None):
    """Corset v5: the radii at the heights ``zs`` (one column of the shell from its top edge down to its waist end,
    descending) of a stiff strip laid over the body along the column's ray: never closer than ``clear`` to the skin
    (sampled every ``BONE_STEP_M``) nor inside the radii ``rads`` the shell gave the rows (the row's closed section
    between the cups), fixed at the top edge, and clamped on the body from the waist end down ``BONE_CLAMP_M``
    (``bone_bend``). A straight hull from the chest to the rib cage turned at a corner at either end: a crease in the
    render. Corset v6: the waist end ``bot`` is one height for every column (v5 took each column's own row nearest it,
    so the strips ended up to a row apart: a pinch at the centre front where one ended early), the rows of ``zs``
    under it come out on the body, and the strip is drawn onto the body (``BONE_PULL``)."""
    top = float(zs[0])
    bot = float(zs[-1]) if bot is None else float(bot)
    z = np.arange(top, min(bot, float(zs[-1])) - BONE_CLAMP_M - 1e-9, -BONE_STEP_M)
    z[0] = top
    lo = np.array([gd.body_radius(btree, centre, ang, float(h)) + clear for h in z])
    order = np.argsort(zs)
    inside = z >= bot - 1e-9
    lo[inside] = np.maximum(lo[inside], np.interp(z[inside], np.asarray(zs, float)[order],
                                                  np.asarray(rads, float)[order]))
    lo[0] = float(rads[0])
    fixed = [0] + [i for i in range(len(z)) if z[i] <= bot + 1e-9]
    # corset v6: the mesh runs straight between the rows ``zs``, so where the strip curves tightly (round the cup's
    # underside) the straight stretch between two rows cut into the body and the shell's stretch pass raised its ends
    # into a bump (a 7 mm ridge one row under the cup edge): the strip is solved again with ``lo`` raised by what the
    # rows' straight line still lacks, ``BONE_CHORD_ROUNDS`` times
    # the band under the top edge (``BONE_PULL_EDGE_M``) is drawn on hard, the rest lightly: a hard pull all the way
    # down tucked the strip in a sharp turn under the cup (a dark crescent in the render)
    pullv = np.where(z >= top - BONE_PULL_EDGE_M, BONE_PULL_EDGE, BONE_PULL)
    zr = np.asarray(zs, float)[::-1]
    extra = np.zeros(len(z))
    for _round in range(BONE_CHORD_ROUNDS):
        r = bone_bend(z, lo + extra, fixed, pullv)
        chord = np.interp(z, zr, np.interp(zr, z[::-1], r[::-1]))
        lack = np.where(z > bot + 1e-9, lo - chord, 0.0)
        lack[0] = 0.0
        if lack.max() <= BONE_CHORD_TOL_M:
            break
        extra += np.maximum(lack, 0.0)
    return np.interp(zs, z[::-1], r[::-1])


def corset_shell(verts, angles, spec, btree, centre, clear, edge=()):
    """Corset v2 (user report 2026-11-22, "lots of air below, thick at the top"): lay a strapless top's ``wrap``
    vertices ON the body instead of hanging them as a tube — each at its own angle and height ``clear`` outside the
    surface the build's ray meets there (``gd.body_radius``, so a layer the piece is draped over — a collider —
    counts as the surface); within ``SHELL_HULL_RAD`` of the front centre outside its height's section closed by a
    disc (``_close_radius``, corset v6; v2..v5 the convex hull: the neckline's middle spans the hollow between the
    cups). Then every
    stretch between two vertices — two rows of a column (a chest's underside), two columns of a row (a chord across the
    rounded chest) and either diagonal of a quad — is raised until it clears the body by ``clear`` at
    ``SHELL_PROFILE_SAMPLES`` points, by the least change of its two ends, all of it on the inner end where the other
    is on the top ``edge`` (that edge stays on the skin: no visible step). The waist hugs, the hem does not flare, the
    top edge lies on the skin. In place; returns ``{rows, bridged, raised}`` (vertices standing over a hollow,
    ``SHELL_BRIDGE_M``; stretches raised)."""
    rows, cols = spec["rows"], spec["cols"]
    n = len(verts)
    panels = n // (rows * cols)
    body_r = np.array([gd.body_radius(btree, centre, angles[i], verts[i][2]) for i in range(n)])
    rad = body_r + clear
    front = [k for k, p in enumerate(spec["panels"]) if p["name"] == "front"]
    bridged = 0
    hollow = []
    edge_set = set(int(i) for i in edge)
    ring_ang = [angles[k * rows * cols + c] for k in range(panels) for c in range(cols)]
    slices = {}

    def slice_hull(i):
        """Corset v5: the hull of the body's slice at vertex ``i``'s OWN height, at its angle. The rows of a corset
        lie at a different height in every column (the cup edge, the sweetheart dip, the edge under the arms): the
        hull of a row through those heights gave the dip's column the radius of the cups' rows 2-3 cm higher — a
        keel standing 3 cm out of the front's middle. Corset v6: the slice closed by a disc of ``SHELL_CLOSE_M``
        (``_close_radius``) instead of its convex hull."""
        key = round(float(verts[i][2]), 3)
        if key not in slices:
            radii = [gd.body_radius(btree, centre, a, key) for a in ring_ang]
            slices[key] = (_close_section(ring_ang, radii, SHELL_CLOSE_M), {})
        sec, cache = slices[key]
        a = round(float(angles[i]), 6)
        if a not in cache:
            cache[a] = float(_close_radius(sec, angles[i]))
        return cache[a]

    for r in range(rows):
        idx = np.array([k * rows * cols + r * cols + c for k in range(panels) for c in range(cols)])
        hull = np.zeros(len(idx))
        for j, i in enumerate(idx):
            off = abs(((angles[i] - 1.5 * math.pi) + math.pi) % (2 * math.pi) - math.pi)
            if i // (rows * cols) in front and off <= SHELL_HULL_RAD:
                hull[j] = max(slice_hull(i), body_r[i])
        for j, i in enumerate(idx):
            off = abs(((angles[i] - 1.5 * math.pi) + math.pi) % (2 * math.pi) - math.pi)
            if i // (rows * cols) in front and off <= SHELL_HULL_RAD and hull[j] > body_r[i]:
                if int(i) in edge_set and hull[j] - body_r[i] <= SHELL_BRIDGE_M:
                    continue        # corset v4: the top edge stays on the skin where the hull only grazes it
                rad[i] = hull[j] + clear
                if hull[j] - body_r[i] > SHELL_BRIDGE_M:
                    bridged += 1
                    hollow.append(int(i))
    # corset v3 (review 2026-11-22: a step under the lifted chest in the side view): down the front, from the top
    # edge of a column to ``SHELL_FRONT_WAIST_M`` over the waist, the cloth runs from the chest to the rib cage over
    # the fold under it, as a corset's front does; the waist stays on the body. Corset v5 (review 2026-11-23: a dark
    # crease where the cup met the straight panel under it): not a straight hull with a corner at either end but a
    # stiff strip (``boned_profile``: the least bending over the body, clamped on the body under it), so the cloth
    # turns smoothly from the cup into the panel. The column's vertices from the edge down to there are left out of the
    # settle (``boned``: it would bend the strip back into the corners); those standing farther than
    # ``SHELL_BRIDGE_M`` off the body count as over a hollow (out of the band gap)
    waist_y = (spec.get("outline") or {}).get("waist_y")
    tissue_cols = set((spec.get("cup_edge") or {}).get("tissue_cols") or ())
    boned = []
    strips = {}
    zz0 = [float(v[2]) for v in verts]

    if waist_y is not None:
        for k in front:
            base = k * rows * cols
            for c in range(cols):
                i0 = base + c
                off = abs(((angles[i0] - 1.5 * math.pi) + math.pi) % (2 * math.pi) - math.pi)
                # corset v4 (review 2026-11-23: a dent under the outer cup in the side view): every column with chest
                # tissue (``cup_edge``) runs from the chest to the rib cage too
                if off > SHELL_HULL_RAD and c not in tissue_cols:
                    continue
                col = [base + r * cols + c for r in range(rows)]
                zs = np.array([verts[i][2] for i in col])
                # corset v6: one waist end for every column (``boned_profile``), the rows down to its clamp
                bot = float(waist_y) + SHELL_FRONT_WAIST_M
                span = [r for r in range(rows) if zs[r] >= bot - BONE_CLAMP_M]
                if len([r for r in span if zs[r] > bot]) < 3:
                    continue
                new_r = boned_profile(btree, centre, angles[i0], zs[span], rad[[col[r] for r in span]], clear, bot)
                for r, v in zip(span, new_r):
                    if r == 0:
                        continue                         # the top edge stays where it lies (on the skin)
                    if v - rad[col[r]] > SHELL_BRIDGE_M:
                        hollow.append(int(col[r]))       # spans the fold: out of the band gap
                    rad[col[r]] = max(rad[col[r]], float(v))
                    if zs[r] > bot + 1e-6:
                        boned.append(int(col[r]))
                strips[(k, c)] = col[:span[-1] + 1]
        # corset v5 (review 2026-11-23: vertical streaks down the centre front): each strip is solved on its own
        # column's row heights, which differ from column to column under the sweetheart edge, so neighbouring strips
        # met the steep stretch over the rib cage at different radii; the strips are smoothed across (1, 2, 1) at each
        # vertex's own height, never into the body
        boned_s = set(boned)
        own = rad.copy()
        for _round in range(SHELL_STRIP_SMOOTH_ROUNDS):
            prof = {key: (np.array([zz0[i] for i in ids[::-1]]), np.array([rad[i] for i in ids[::-1]]))
                    for key, ids in strips.items()}
            new = {}
            for (k, c), ids in strips.items():
                if (k, c - 1) not in prof or (k, c + 1) not in prof:
                    continue
                for i in ids[1:]:
                    if i not in boned_s:
                        continue
                    zl, rl = prof[(k, c - 1)]
                    zr, rr = prof[(k, c + 1)]
                    avg = (np.interp(zz0[i], zl, rl) + 2 * rad[i] + np.interp(zz0[i], zr, rr)) / 4.0
                    new[i] = max(float(avg), own[i])
            for i, v in new.items():
                rad[i] = v
        # corset v6: a strip the smoothing lifted off its own line by more than ``SHELL_BRIDGE_M`` spans the hollow
        # beside the cleavage with its neighbours (out of the band gap, as the bridge itself)
        hollow.extend(int(i) for i in boned_s if rad[i] - own[i] > SHELL_BRIDGE_M)
    raised = 0
    fixed = set(int(i) for i in edge)
    zz = np.array([float(v[2]) for v in verts])

    def lift(a, b, pa, pb, edge_pass=False):
        """Raise the stretch a-b (radii ``rad``, points ``pa``/``pb`` at those radii) until every sample on it clears
        the body by ``clear``; the least change that does it (``(1-t, t)`` share, exact at the worst sample)."""
        worst, wt = 0.0, 0.5
        for t in (np.arange(SHELL_PROFILE_SAMPLES) + 0.5) / SHELL_PROFILE_SAMPLES:
            x, y, z = pa[0] + (pb[0] - pa[0]) * t, pa[1] + (pb[1] - pa[1]) * t, pa[2] + (pb[2] - pa[2]) * t
            ang = math.atan2(y - centre[1], x - centre[0])
            need = gd.body_radius(btree, centre, ang, z) + clear - math.hypot(x - centre[0], y - centre[1])
            if need > worst:
                worst, wt = need, t
        if worst <= 1e-4:
            return 0
        if (a in fixed or b in fixed) and not edge_pass:
            return 0
        if edge_pass and a in fixed and b in fixed:
            # corset v4: a chord ALONG the top edge across the rounded upper cup is left as it is (raising both its ends
            # stood the edge 2-3 mm off the skin); the stretches from the edge inward are still raised
            return 0
        if edge_pass:
            # only where the body really stands through the stretch, and only up to the body's surface
            if worst <= clear:
                return 0
            worst -= clear - SHELL_EDGE_SKIN_M
        wa, wb = 1 - wt, wt
        if edge_pass:
            # corset v4: the edge end stays on the skin; the inner end takes the raise (its sample share exact)
            share = wt if a in fixed else 1 - wt
            worst = worst / max(share, 0.25)
            wa, wb = (0.0, 1.0) if a in fixed else (1.0, 0.0)
            rad[a] += worst * wa
            rad[b] += worst * wb
            return 1
        k = worst / (wa * wa + wb * wb)
        rad[a] += k * wa
        rad[b] += k * wb
        return 1

    def point(i):
        return (centre[0] + rad[i] * math.cos(angles[i]), centre[1] + rad[i] * math.sin(angles[i]), zz[i])

    def clear_stretches(edge_pass=False):
        count = 0
        for k in range(panels):
            base = k * rows * cols
            for c in range(cols):
                col = [base + r * cols + c for r in range(rows)]
                for a, b in zip(col[:-1], col[1:]):
                    count += lift(a, b, point(a), point(b), edge_pass)
            for r in range(rows):
                row = [base + r * cols + c for c in range(cols)]
                for a, b in zip(row[:-1], row[1:]):
                    count += lift(a, b, point(a), point(b), edge_pass)
            for r in range(rows - 1):
                for c in range(cols - 1):
                    # both diagonals of the quad (its triangles' inner edge, whichever way it is split)
                    for a, b in ((base + r * cols + c, base + (r + 1) * cols + c + 1),
                                 (base + r * cols + c + 1, base + (r + 1) * cols + c)):
                        count += lift(a, b, point(a), point(b), edge_pass)
        return count

    pre = rad.copy()
    for _pass in range(3):
        raised += clear_stretches()
    # corset v6 (review 2026-11-23 of v5: a 7 mm ridge one row under the outer cup edge): the stretch pass raises the
    # two ends of a stretch the body stands through — at the cup's outer rim, which turns sharper than the columns
    # are apart, a single row. On the front that raise is spread over its neighbours (``SHELL_SPREAD_ROUNDS``: the
    # largest of each 3 x 3, then (1, 2, 1) both ways, never under the raise itself): a broad swell, no ridge
    for k in front:
        ids = np.arange(k * rows * cols, (k + 1) * rows * cols).reshape(rows, cols)
        dlt = (rad[ids] - pre[ids])
        dlt[0] = 0.0
        if dlt.max() <= 1e-5:
            continue
        pad = np.pad(dlt, 1, mode="edge")
        spread = np.max([pad[1 + dr:rows + 1 + dr, 1 + dc:cols + 1 + dc] for dr in (-1, 0, 1) for dc in (-1, 0, 1)],
                        axis=0)
        for _ in range(SHELL_SPREAD_ROUNDS):
            pad = np.pad(spread, 1, mode="edge")
            spread = (pad[:-2, 1:-1] + 2 * pad[1:-1, 1:-1] + pad[2:, 1:-1]) / 4.0
            pad = np.pad(spread, 1, mode="edge")
            spread = (pad[1:-1, :-2] + 2 * pad[1:-1, 1:-1] + pad[1:-1, 2:]) / 4.0
        spread = np.maximum(spread, dlt)
        spread[:SHELL_SPREAD_FROM_ROW] = dlt[:SHELL_SPREAD_FROM_ROW]
        rad[ids] = pre[ids] + spread
    raised += clear_stretches()
    keep = fixed | set(hollow) | set(boned)
    settled = 0
    for _round in range(SHELL_SETTLE_ROUNDS):
        for i in range(n):
            if i in keep:
                continue
            q = Vector(point(i))
            loc, nrm, _f, dist = btree.find_nearest(q)
            if loc is None or dist <= clear + SHELL_SETTLE_TOL_M:
                continue
            out = (q - loc).normalized() if dist > 1e-9 else nrm
            t = loc + out * clear
            zz[i] = verts[i][2] + max(-SHELL_SETTLE_DZ_M, min(SHELL_SETTLE_DZ_M, t.z - verts[i][2]))
            # the radius along the vertex's own ray at its new height: the point of the offset surface there
            rad[i] = max(gd.body_radius(btree, centre, angles[i], zz[i]) + clear,
                         min(rad[i], math.hypot(t.x - centre[0], t.y - centre[1])))
            settled += 1
        raised += clear_stretches()
    # last, the stretches from the top edge in: left out above (all of their raise fell on the inner end, which then
    # rolled out as a flap at the cups' side), they are raised here by both ends where the body stands through them
    # (``SHELL_EDGE_SKIN_M``) — so no skin shows through between the edge and the next row
    edge_raised = clear_stretches(edge_pass=True)
    # corset v4 (review 2026-11-23: the edge stood up to 3 mm off the upper slope of the lifted chest after the edge
    # pass): an edge vertex farther than ``clear`` from its nearest surface point moves in along its ray by the
    # difference, never closer than ``SHELL_EDGE_SKIN_M`` over the surface its ray meets
    # corset v5: repeated — on the inner slope of a cup the ray meets the skin at a slant, so one step along it closed
    # only part of the gap (3.1 mm left beside the cleavage)
    bridge = set(hollow)
    for _round in range(SHELL_EDGE_ROUNDS):
        for i in fixed:
            if i in bridge:
                continue            # corset v5: the bridge over the cleavage stays on its hull (no fold into it)
            q = Vector(point(i))
            loc, _nrm, _f, dist = btree.find_nearest(q)
            if loc is not None and dist > SHELL_EDGE_CLEAR_M + SHELL_EDGE_TOL_M:
                rad[i] = max(body_r[i] + SHELL_EDGE_SKIN_M if zz[i] == verts[i][2] else 0.0,
                             gd.body_radius(btree, centre, angles[i], zz[i]) + SHELL_EDGE_SKIN_M,
                             rad[i] - (dist - SHELL_EDGE_CLEAR_M))
    # corset v5: where the line between two neighbouring edge vertices spans a hollow of the skin (the shoulder
    # blade's edge) farther than ``SHELL_EDGE_LINE_M``, both ends move in by the excess, never closer than
    # ``SHELL_EDGE_SKIN_M`` over the skin along their rays
    ring = sorted(fixed, key=lambda i: angles[i] % (2 * math.pi))
    step = math.pi / (cols - 1)
    for _round in range(SHELL_EDGE_ROUNDS):
        moved = 0
        for a, b in zip(ring, ring[1:] + ring[:1]):
            if (angles[b] - angles[a]) % (2 * math.pi) > 1.5 * step or a in bridge or b in bridge:
                continue
            pa, pb = Vector(point(a)), Vector(point(b))
            far = max((pa.lerp(pb, t) - btree.find_nearest(pa.lerp(pb, t))[0]).length for t in (0.25, 0.5, 0.75))
            if far <= SHELL_EDGE_LINE_M:
                continue
            for i in (a, b):
                rad[i] = max(gd.body_radius(btree, centre, angles[i], zz[i]) + SHELL_EDGE_SKIN_M,
                             rad[i] - (far - SHELL_EDGE_LINE_M))
            moved += 1
        if not moved:
            break
    for i in range(n):
        verts[i] = (centre[0] + rad[i] * math.cos(angles[i]), centre[1] + rad[i] * math.sin(angles[i]), zz[i])
    return {"rows": int(rows), "bridged": int(bridged), "raised": int(raised), "settled": int(settled),
            "edge_raised": int(edge_raised),
            "hollow": hollow}


#: Corset v3 (review 2026-11-22: the side cup edge rolled out as a flap the top-edge row alone did not see): the band
#: under the top edge whose gap is gated per side (``under_edge``), metres under the edge at the same angle.
UNDER_EDGE_M = (0.01, 0.03)
#: Corset v4: the outer part of the cups' top edge (radians off the front centre) whose gap is gated on its maximum
#: (``edge_outer``).
EDGE_OUTER_RAD = (0.6, 1.2)


def shell_gaps(obj, ftree, btree, centre, spec, clear, gap_mm, hollow=()):
    """Corset v2: the distance of the single layer to the nearest surface under it (``ftree``: the body and the
    layers under the piece) in millimetres, p50 / p95 / max per part: the waist (within 12 mm of ``waist_y``), the hem
    (its row) and the top edge (its row, ``pin_top`` where it is lowered; those over a hollow — farther than
    ``clear`` + ``SHELL_BRIDGE_M`` outside the surface their own ray meets — are left out and counted as ``bridge``).
    Corset v3: ``under_edge`` = the band ``UNDER_EDGE_M`` under the top edge (under the edge vertex nearest in angle),
    the vertices the shell laid over the hollow between the cups (``hollow``, ``corset_shell``) left out, per side
    (``under_edge_left`` / ``_right``: x over / under the centre) and the worse side as ``under_edge``."""
    co, _n, _t = gd.world_coords(obj)
    dist = np.array([(Vector(c) - ftree.find_nearest(Vector(c))[0]).length for c in co])
    hem_z = float(spec["row_y"][-1])
    waist_z = float((spec.get("outline") or {}).get("waist_y", -9.0))
    border = np.zeros(len(co), bool)
    border[gd.boundary_verts(obj)] = True
    hem = border & (np.abs(co[:, 2] - hem_z) < 0.002)
    vg = obj.vertex_groups.get("pin_top")
    if vg is not None:
        # a lowered top edge (A221): its row by name (seam borders are no top edge)
        top = np.zeros(len(co), bool)
        for v in obj.data.vertices:
            if any(g.group == vg.index for g in v.groups):
                top[v.index] = True
    else:
        top = border & (np.abs(co[:, 2] - float(spec["row_y"][0])) < 0.002)
    over = np.zeros(len(co), bool)
    # corset v4: with a cup edge (``cup_edge``) the whole cleavage between the innermost tissue columns is the bridge
    tc = (spec.get("cup_edge") or {}).get("tissue_cols") or []
    cleave = (min(abs(math.pi * c / (int(spec["cols"]) - 1) - math.pi / 2) for c in tc) if tc else 0.0)
    for i in np.where(top)[0]:
        ang = math.atan2(co[i, 1] - centre[1], co[i, 0] - centre[0])
        r = math.hypot(co[i, 0] - centre[0], co[i, 1] - centre[1])
        off = abs(((ang - 1.5 * math.pi) + math.pi) % (2 * math.pi) - math.pi)
        over[i] = (r - gd.body_radius(btree, centre, ang, float(co[i, 2])) > clear + SHELL_BRIDGE_M
                   or (off < cleave and co[i, 1] < centre[1]))
    band = np.zeros(len(co), bool)
    ti = np.where(top)[0]
    if len(ti):
        ang_all = np.arctan2(co[:, 1] - centre[1], co[:, 0] - centre[0])
        ang_top = ang_all[ti]
        diff = np.abs((ang_all[:, None] - ang_top[None, :] + math.pi) % (2 * math.pi) - math.pi)
        dz = co[ti[np.argmin(diff, axis=1)], 2] - co[:, 2]
        band = (dz >= UNDER_EDGE_M[0]) & (dz <= UNDER_EDGE_M[1])
        band[np.asarray(list(hollow), int)] = False
    out = {}
    parts = [("waist", np.abs(co[:, 2] - waist_z) < 0.012), ("hem", hem), ("top_edge", top & ~over),
             ("under_edge_left", band & (co[:, 0] > centre[0])), ("under_edge_right", band & (co[:, 0] < centre[0]))]
    for name, m in parts:
        if m.any():
            v = dist[m] * 1000
            out[name] = {"n": int(m.sum()), "p50_mm": round(float(np.percentile(v, 50)), 2),
                         "p95_mm": round(float(np.percentile(v, 95)), 2), "max_mm": round(float(v.max()), 2),
                         "limit_mm": gap_mm.get(name.replace("_left", "").replace("_right", ""))}
    ce = spec.get("cup_edge")
    if ce and top.any():
        # corset v4 (review 2026-11-23): the outer cup edge on its maximum gap, and the skin over the top edge of a
        # column with chest tissue standing out beyond ``recede_m`` inside the edge (the spill the p95 never saw)
        top_z = float(spec["row_y"][0])
        apex_z = float(ce["apex_y"])
        outer, spill = [], []
        for i in np.where(top & ~over)[0]:
            ang = math.atan2(co[i, 1] - centre[1], co[i, 0] - centre[0])
            off = abs(((ang - 1.5 * math.pi) + math.pi) % (2 * math.pi) - math.pi)
            if EDGE_OUTER_RAD[0] <= off <= EDGE_OUTER_RAD[1]:
                outer.append(dist[i] * 1000)
            if off < math.pi / 2 and chest_tissue(btree, centre, ang, apex_z, top_z, float(ce["tissue_m"])):
                r = gd.body_radius(btree, centre, ang, float(co[i, 2]))
                stand = max(gd.body_radius(btree, centre, ang, float(co[i, 2]) + float(dz))
                            for dz in np.arange(0.004, CUP_EDGE_LOOK_M + 1e-9, 0.004))
                spill.append(max(0.0, stand - r) * 1000)
        te = [(round(float(dist[i] * 1000), 2), round(abs(((math.atan2(co[i, 1] - centre[1], co[i, 0] - centre[0])
                                                          - 1.5 * math.pi) + math.pi) % (2 * math.pi) - math.pi), 2),
               round(float(co[i, 2]), 3)) for i in np.where(top & ~over)[0]]
        out["top_edge_worst"] = sorted(te, reverse=True)[:6]
        for name, v in (("edge_outer", outer), ("edge_spill", spill)):
            if v:
                v = np.array(v)
                out[name] = {"n": int(len(v)), "p50_mm": round(float(np.percentile(v, 50)), 2),
                             "p95_mm": round(float(np.percentile(v, 95)), 2), "max_mm": round(float(v.max()), 2),
                             "limit_mm": gap_mm.get(name)}
    sides = [out[k] for k in ("under_edge_left", "under_edge_right") if k in out]
    if sides:
        out["under_edge"] = dict(max(sides, key=lambda r: r["p95_mm"]))
        # corset v6: where the band stands off (off-front degrees, height, mm), for a reviewer to find it
        bi = np.where(band)[0]
        worst = bi[np.argsort(-dist[bi])[:8]]
        out["under_edge"]["worst"] = [[round(math.degrees(_angle_off(math.atan2(co[i, 1] - centre[1],
                                                                                 co[i, 0] - centre[0]))), 1)
                                       * (1 if co[i, 0] > centre[0] else -1), round(float(co[i, 2]), 3),
                                       round(float(dist[i]) * 1000, 2)] for i in worst]
    if top.any():
        out.update(edge_loop(obj, co, ftree, centre, spec, np.where(top & ~over)[0], gap_mm))
    out.update(front_folds(obj, co, centre, spec))
    out["bridge"] = {"n": int((top & over).sum()),
                     "p95_mm": round(float(np.percentile(dist[top & over] * 1000, 95)), 2) if (top & over).any()
                     else None}
    return out


#: Corset v5 (review 2026-11-23: the gaps of the top edge were gated on their p95 and on the outer cup only, so two
#: flaps under the arms passed): ``edge_loop`` walks the whole top edge round the body (the cleavage bridge between the
#: cups left out, ``shell_gaps``' ``over``) and takes the MAXIMUM per ``EDGE_LOOP_SEG_M`` of its length, sampled every
#: ``EDGE_LOOP_STEP_M`` along the edge.
EDGE_LOOP_SEG_M = 0.02
EDGE_LOOP_STEP_M = 0.002


def _angle_off(ang):
    """Radians off the front centre (1.5 pi) of an angle round the axis."""
    return abs(((ang - 1.5 * math.pi) + math.pi) % (2 * math.pi) - math.pi)


def edge_loop(obj, co, ftree, centre, spec, top_ids, gap_mm):
    """Corset v5: the top edge's gap to the nearest surface under it (``ftree``) and its flare, each on its MAXIMUM
    per ``EDGE_LOOP_SEG_M`` of the edge (mm): ``edge_loop_gap`` = the largest distance of the edge line (sampled every
    ``EDGE_LOOP_STEP_M`` between neighbouring edge vertices) to the surface; ``edge_loop_flare`` = how far an edge
    vertex stands out beyond the straight line through the cloth ``UNDERARM_BELOW_M`` under it at its angle (a flap
    rolls out; the top of a cup turns in, < 0). ``top_ids`` are the edge vertices without the cleavage bridge; two of
    them are neighbours when they lie less than 1.5 column steps apart round the axis. Each with its worst segments
    ``[off-front degrees, height, mm]``."""
    ids = np.asarray(top_ids, int)
    if len(ids) < 3:
        return {}
    ang = np.arctan2(co[ids, 1] - centre[1], co[ids, 0] - centre[0]) % (2 * math.pi)
    order = np.argsort(ang)
    ids, ang = ids[order], ang[order]
    step = math.pi / (int(spec["cols"]) - 1)
    allang = np.arctan2(co[:, 1] - centre[1], co[:, 0] - centre[0]) % (2 * math.pi)
    allrad = np.hypot(co[:, 0] - centre[0], co[:, 1] - centre[1])
    lo, hi = UNDERARM_BELOW_M
    samples = []          # (arc position, gap mm, off-front, z)
    arc = 0.0
    flares = []
    for k in range(len(ids)):
        i, j = ids[k], ids[(k + 1) % len(ids)]
        da = (ang[(k + 1) % len(ids)] - ang[k]) % (2 * math.pi)
        a, b = Vector(co[i]), Vector(co[j])
        n = max(1, int(math.ceil((b - a).length / EDGE_LOOP_STEP_M))) if da < 1.5 * step else 1
        for t in range(n):
            q = a.lerp(b, t / n)
            loc = ftree.find_nearest(q)[0]
            samples.append((arc + (b - a).length * t / n if n > 1 else arc,
                            (q - loc).length * 1000 if loc is not None else 0.0, _angle_off(ang[k]), q.z))
        arc += (b - a).length if n > 1 else EDGE_LOOP_SEG_M      # a gap in the edge starts a new segment
        # the flare: the cloth of this column (within half a column step) at lo and hi under the edge vertex
        near = np.where((np.abs((allang - ang[k] + math.pi) % (2 * math.pi) - math.pi) < 0.5 * step)
                        & (co[:, 2] < co[i, 2] - 0.002) & (co[:, 2] > co[i, 2] - hi - 0.02))[0]
        if len(near) >= 2:
            zo = np.argsort(co[near, 2])
            zz, rr = co[near, 2][zo], allrad[near][zo]
            r1 = float(np.interp(co[i, 2] - lo, zz, rr))
            r2 = float(np.interp(co[i, 2] - hi, zz, rr))
            flares.append(((float(allrad[i]) - (r1 + (r1 - r2) * lo / (hi - lo))) * 1000, _angle_off(ang[k]),
                           float(co[i, 2])))
    out = {}
    seg = {}
    for pos, g, off, z in samples:
        key = int(pos // EDGE_LOOP_SEG_M)
        if key not in seg or g > seg[key][0]:
            seg[key] = (g, off, z)
    worst = sorted(seg.values(), reverse=True)
    out["edge_loop_gap"] = {"n": len(seg), "max_mm": round(worst[0][0], 2),
                            "p50_mm": round(float(np.median([v[0] for v in worst])), 2),
                            "limit_mm": gap_mm.get("edge_loop_gap"),
                            "worst": [[round(math.degrees(o), 1), round(z, 3), round(g, 2)] for g, o, z in worst[:6]]}
    if flares:
        fl = sorted(flares, reverse=True)
        out["edge_loop_flare"] = {"n": len(fl), "max_mm": round(fl[0][0], 2),
                                  "p50_mm": round(float(np.median([f[0] for f in fl])), 2),
                                  "limit_mm": gap_mm.get("edge_loop_flare"),
                                  "worst": [[round(math.degrees(o), 1), round(z, 3), round(f, 2)] for f, o, z in fl[:6]]}
    return out


#: Corset v5 (review 2026-11-23: a dark crease where the lifted cup met the straight panel under it): ``front_folds``
#: reads the bend of the front between the hem and the top edge, across each inner edge of the single layer.
FOLD_LIMIT_KEY = "front_fold"


def front_folds(obj, co, centre, spec):
    """Corset v5: the angle between the normals of the two faces at every inner edge of the front (off the front
    centre by less than ``SHELL_HULL_RAD`` + 0.3 rad, the cups and the panel under them; the top edge's own faces and
    the hem row left out), degrees: ``front_fold`` = max / p99 / count over 20, with the worst edges ``[off-front
    degrees, height, degrees]``. A crease between the cup and the panel shows as a run of large angles."""
    me = obj.data
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.normal_update()
    top_z, hem_z = float(spec["row_y"][0]), float(spec["row_y"][-1])
    vals = []
    for e in bm.edges:
        if len(e.link_faces) != 2:
            continue
        a, b = e.verts
        if any(v.is_boundary for v in (a, b)):
            continue
        m = (co[a.index] + co[b.index]) / 2
        off = _angle_off(math.atan2(m[1] - centre[1], m[0] - centre[0]))
        if off > SHELL_HULL_RAD + 0.3 or m[2] < hem_z + 0.01 or m[2] > top_z + 0.01:
            continue
        f0, f1 = e.link_faces
        d = math.degrees(f0.normal.angle(f1.normal, 0.0))
        vals.append((d, off, float(m[2])))
    bm.free()
    if not vals:
        return {}
    v = np.array([x[0] for x in vals])
    worst = sorted(vals, reverse=True)[:6]
    return {FOLD_LIMIT_KEY: {"n": int(len(v)), "max_deg": round(float(v.max()), 2),
                             "p99_deg": round(float(np.percentile(v, 99)), 2), "over_20": int((v > 20).sum()),
                             "worst": [[round(math.degrees(o), 1), round(z, 3), round(d, 1)] for d, o, z in worst]}}


# --- Ruling A142: the bodice (top, jacket, dress with straps or sleeves) -------------------------------------
#: Columns either side of each side seam (angle 0 = the character's left, pi = right) removed between the chest
#: band and the shoulder line: the armhole (5 of 80 columns = 0.39 rad, ~7 cm at a 0.18 m torso radius — wider than
#: the T-posed arm's depth). A179: at least this many; widened up to WINDOW_COLS_MAX until the window's border columns
#: pass in front of / behind the arm root (a deltoid 9-10 cm deep at 0.21 m from the spine fills 0.45 rad: the
#: border columns ran INTO it and met their neighbours' vertices there, 1.2 mm apart).
WINDOW_COLS = 5
WINDOW_COLS_MAX = 9
#: A179: the border columns pass the arm root with this much room.
WINDOW_ROOM_M = 0.015
BODICE_CLEAR_M = 0.01
CAP_CLEAR_M = 0.008
SLEEVE_CLEAR_M = 0.012
#: A179: the vertices of a sleeve ring stand this far apart on average (the torso's grid is 15 mm).
SLEEVE_EDGE_M = 0.015
#: Over this distance along the arm the sleeve turns from the armhole's shape into a ring round the arm.
SLEEVE_BLEND_M = 0.06
#: A stand collar: rings above the neck opening.
COLLAR_RINGS = 3
#: Ruling A144: below the neckline cut a column's vertices are re-spaced over this arc length (or twice the cut).
NECK_BLEND_M = 0.08
#: A178: the re-spaced vertices of a meridian stand at least this far apart (where the column is long enough).
NECK_MIN_STEP_M = 0.010
#: Edges built shorter than this are left out of the stretch ratio (``stretch_gate``, which also leaves edges under
#: 3 mm or grown under 1 mm out of the gated maximum).
MIN_EDGE_M = sg.MIN_EDGE_M
#: The yoke reaches at least this far outward from the neck opening.
CAP_MIN_M = 0.03
COLLAR_STEP_M = 0.012
#: A179: the neck opening is the body's own section this far above the neck joint (the neck proper: at the joint's
#: height the section still holds the trapezius), read from the neck axis (neck joint -> head joint, so a head bent
#: forward keeps its ring round the neck), plus NECK_RING_CLEAR_M.
NECK_RING_UP_M = 0.02
NECK_RING_CLEAR_M = 0.012
#: A179: beside and behind the neck (columns whose cosine from the front is under NECK_FRONT_COS) the ring is the
#: narrowest of the sections at these heights above ``neck_y + NECK_RING_UP_M``.
NECK_RING_SCAN_M = (0.0, 0.01, 0.02, 0.03)
NECK_FRONT_COS = 0.3
#: A179: the ring never stands closer than this to the section it was read from (after its smoothing).
NECK_RING_MIN_CLEAR_M = 0.006
#: A179: the opening is at most this much wider than the spec's ``neck_r`` (a section that still holds the shoulders).
NECK_RING_MAX_OVER_M = 0.03
#: A179: an air gap under an overhang (the chin of a head bent forward) is larger than this; a smaller one is the gap
#: between the body and a lower garment layer, whose top stays the surface.
LAYER_GAP_M = 0.015
#: A179: the armhole plane stands this far outward of the arm joint (across the arm, the bind pose is the T-pose).
ARMHOLE_OUT_M = 0.0
#: A179: a column outside the armhole window whose ray crosses the armhole plane inside the arm root follows the arm
#: this far beyond the plane to its surface.
ARM_REACH_M = 0.08
#: A179: a meridian's path is sampled this densely and every sample is laid outside the collider.
PATH_STEP_M = 0.008
#: A179: the top of the armhole runs over the arm root between these angles either side of straight up (radians);
#: its sides run on down the arm root to the joint's height, then along the window's border columns.
ARMHOLE_TOP_RAD = math.radians(60)
#: A179: the neck rim's height round the opening is the surface height at the ring, smoothed from above over this
#: many passes of a 1-2-1 filter (the cloth bridges the hollow between the trapezius and the collarbone: on the
#: surface itself the rim dropped 5 cm within two columns, a notch either side of the front).
NECK_ENV_PASSES = 24
#: A179: the exponent of the cosine in a round neckline's shape (1 = a half ellipse seen from the front, with a
#: corner where it meets the ring; 2 = a pointed bottom).
NECK_ROUND_POW = 1.4
#: A179: where the arm's underside is read (metres out from the arm joint along the upper arm; the lowest counts).
ARM_UNDER_AT_M = (0.08, 0.12, 0.16)
#: A236: under the arm the bottom of the armhole is read through every lower layer hanging within this distance below
#: the arm (a loose short sleeve of a blouse droops 2.6 cm under the T-posed arm; a jacket's armhole read from the arm
#: itself ran its side through that sleeve — stretch 4.1). The hip below the arm is farther.
ARM_LAYER_GAP_M = 0.08
#: A179: passes of the evening-out of the yoke and the upper rows (``build_bodice``).
RELAX_PASSES = 8
#: A179: a yoke line leaves the ring at most this far (radians) off the direction of its shoulder-line point.
YOKE_SKEW_RAD = 0.6
#: A179: from a rim that stands above the surface the yoke comes down outward at this slope until it lies on it.
NECK_BRIDGE_SLOPE = 0.6
#: A179: a path sample is laid this much farther out than the clearance pass asks for (a vertex between two samples
#: stands a little inside their chord's ends).
PATH_EXTRA_M = 0.002
#: A179: a clearance measured along a ray is divided by the cosine between the ray and the surface normal, at most
#: 1 / this (a ray grazing a slope would stand off for ever).
MIN_COS = 0.35
#: Ruling A144: a stand collar runs only where the neckline is cut less than this (down a V it stood as a 3 mm band
#: the lower layer stretched to 4x).
COLLAR_CUT_MAX_M = 0.03
#: Step 3c (B8): the deepest scoop that keeps a jacket's / dress's neckband (a deeper one, a V, an open front or a
#: collar: the innermost yoke ring belongs to the panels — a band there measured area 1.3-1.5, stretch p95 3-4 and up).
BAND_SCOOP_MAX_M = 0.08
#: Pattern UV (every kind; plan group B, B17 removed the grid UV): the atlas edge in pixels and the margin round every
#: island — the bake writes the atlas at this size too.
PATTERN_ATLAS_PX = 2048
PATTERN_MARGIN_CM = 1.5


def _bone_world(arm, name, rest=True):
    b = arm.data.bones[gd.P + name]
    return np.array(arm.matrix_world @ b.head_local)


def _ray_down(tree, x, y, top=2.5):
    hit = tree.ray_cast(Vector((x, y, top)), Vector((0, 0, -1)), top + 1)
    return None if hit[0] is None else float(hit[0].z)


def _ray_in(tree, q, d, reach=0.25):
    """Distance from the axis point ``q`` to the first surface met coming in from ``q + d * reach`` (0 if none)."""
    o = Vector(q) + Vector(d) * reach
    hit = tree.ray_cast(o, -Vector(d), reach)
    return (reach - hit[3]) if hit[0] is not None else 0.0


#: Ruling A144: above the chest band a bodice row follows the body's own cross-section (its radius per angle +
#: BODICE_CLEAR_M) and takes the pattern's ease as one even offset, at most ROW_EASE_MAX_M (a circle of the row's
#: girth stood 13 cm off the front of the neck at the shoulder line on the reference body: the box-shaped stand of
#: A142). Below the band the cloth hangs from the bust: the circle of the girth (never inside the body), blended over
#: ROW_BLEND_M (body-shaped rows down to the hem clung to the waist and folded into the groin).
ROW_EASE_MAX_M = 0.05
ROW_BLEND_M = 0.06


def row_radii(btree, centre, angles, z, circ, w=1.0):
    """The radius per angle of one bodice row: ``w`` x the body-shaped row + (1 - w) x the circle rule (see
    ROW_EASE_MAX_M). A ray that misses the body takes its nearest hit neighbour's radius; a row without any hit is the
    circle of its girth."""
    br = np.array([gd.body_radius(btree, centre, a, z) for a in angles])
    hit = br > 0
    circle = np.maximum(circ / (2 * math.pi), br + BODICE_CLEAR_M)
    if not hit.any() or w <= 0.0:
        return np.where(hit, circle, circ / (2 * math.pi))
    idx = np.where(hit)[0]
    n = len(angles)
    for i in np.where(~hit)[0]:
        d = np.minimum(np.abs(idx - i), n - np.abs(idx - i))
        br[i] = br[idx[int(np.argmin(d))]]
    r0 = br + BODICE_CLEAR_M
    xs, ys = r0 * np.cos(angles), r0 * np.sin(angles)
    perim = float(np.sum(np.hypot(np.diff(np.r_[xs, xs[:1]]), np.diff(np.r_[ys, ys[:1]]))))
    shaped = r0 + min(ROW_EASE_MAX_M, max(0.0, (circ - perim) / (2 * math.pi)))
    return w * shaped + (1 - w) * np.maximum(circle, r0)




#: ``_surface_z``: the ray starts inside the body and never leaves it.
INSIDE = ()


def _surface_z(tree, x, y, z_hi, floor):
    """A179 — the height of the body's top surface under (x, y), seen from ``z_hi`` down to ``floor``, and the Z of
    its normal: the first upward-facing entry, unless an air gap larger than LAYER_GAP_M opens below it — then what
    was met is an overhang (the chin or beard of a head bent forward; a ray that STARTS inside it leaves it first)
    and the entry under the gap is the surface (A178's tongue: the yoke climbed 13 cm to the chin there). None when
    there is no surface down to ``floor`` (beside the body, or under an overhang in front of it); INSIDE when the ray
    starts inside the body and never leaves it (hair hanging over a shoulder, a ridge above ``z_hi``)."""
    cand, last_exit, z = None, None, z_hi
    first = tree.ray_cast(Vector((x, y, z_hi)), Vector((0, 0, -1)), z_hi - floor)
    if first[0] is None:
        up = tree.ray_cast(Vector((x, y, z_hi)), Vector((0, 0, 1)), 1.0)
        return INSIDE if up[0] is not None and up[1].z > 0 else None
    for _ in range(16):
        if z <= floor:
            break
        hit = tree.ray_cast(Vector((x, y, z)), Vector((0, 0, -1)), z - floor)
        if hit[0] is None:
            break
        hz = float(hit[0].z)
        if hit[1].z > 0:                   # an entry (the collider is closed and wound outward)
            if cand is None or (last_exit is not None and last_exit - hz > LAYER_GAP_M):
                cand = (hz, float(hit[1].z))
            last_exit = None
        else:
            last_exit = hz
        z = hz - 1e-4
    return cand


def _exit_out(tree, o, d, reach, gap=None):
    """A179 — the distance from ``o`` (inside the body) along ``d`` to where the ray leaves the body for good within
    ``reach``: the first exit, carried through any re-entry closer than LAYER_GAP_M (a lower garment layer).
    ``(distance, cosine between the normal there and d)``, or None when ``o`` is not inside along this ray. ``gap``
    (A236) replaces LAYER_GAP_M as the widest re-entry carried through."""
    hits = 6 if gap is None else 16        # A236: a drooping sleeve is several folds of two-sided cloth
    gap = LAYER_GAP_M if gap is None else gap
    o, d = Vector(o), Vector(d)
    t, out = 0.0, None
    for _ in range(hits):
        hit = tree.ray_cast(o + d * t, d, reach - t)
        if hit[0] is None:
            break
        nd = float(hit[1].dot(d))
        if nd > 0:
            out = (t + hit[3], nd)
        elif out is None or t + hit[3] - out[0] > gap:
            break                          # an entry: either o was outside, or the layers end here
        t += hit[3] + 1e-4
    return out


def neck_ring(tree, arm, bod, angles, z_ring):
    """A179 — the neck opening taken from the NECK SURFACE: the centre (the neck axis at ``z_ring``) and, per
    column angle, the radius of the body's section there + NECK_RING_CLEAR_M, smoothed (never closer than
    NECK_RING_MIN_CLEAR_M to the section, at most NECK_RING_MAX_OVER_M over the spec's ``neck_r``; a boat neck keeps
    the spec's wider radius). A circle of the neck's hull girth round the neck JOINT cut through the front of a neck
    bent forward: the yoke rays started inside it (A178, finding 4)."""
    nk = _bone_world(arm, "Neck")
    try:
        ax = _bone_world(arm, "Head") - nk
    except KeyError:
        ax = np.array((0.0, 0.0, 1.0))
    def axis_at(z):
        p = nk + ax * ((z - nk[2]) / ax[2]) if ax[2] > 1e-3 else nk
        return np.array((p[0], p[1]))
    q = axis_at(z_ring)
    spec_r = float(bod["neck_r"])
    raw = np.full(len(angles), np.nan)
    for i, a in enumerate(angles):
        d = (math.cos(a), math.sin(a), 0.0)
        # beside and behind the neck the section at z_ring may still hold the top of the trapezius (a wing 14 cm
        # out on one copy: the rim stood 6 cm off the neck there): the narrowest of the sections up to
        # NECK_RING_SCAN_M higher counts. In front only z_ring is read — above it comes the chin.
        for dz in ((0.0,) if -d[1] > NECK_FRONT_COS else NECK_RING_SCAN_M):
            o = axis_at(z_ring + dz)
            ex = _exit_out(tree, (o[0], o[1], z_ring + dz), d, 0.3)
            if ex is not None:             # measured from the ring's own centre
                r_ = float(np.hypot(o[0] + ex[0] * d[0] - q[0], o[1] + ex[0] * d[1] - q[1]))
                raw[i] = r_ if np.isnan(raw[i]) else min(raw[i], r_)
    if np.isnan(raw).all():
        return q, np.full(len(angles), spec_r), {"source": "spec"}
    raw = np.where(np.isnan(raw), spec_r - NECK_RING_CLEAR_M, raw)
    r = raw + NECK_RING_CLEAR_M
    for _ in range(3):                     # a smooth ring: the section's corners (trapezius) are rounded off
        r = (np.roll(r, 1) + 2 * r + np.roll(r, -1)) / 4
        r = np.maximum(r, raw + NECK_RING_MIN_CLEAR_M)
    r = np.minimum(r, spec_r + NECK_RING_MAX_OVER_M)
    if bod.get("neckline") == "boat":
        r = np.maximum(r, spec_r)
    return q, r, {"source": "surface", "z": round(float(z_ring), 4), "r_min": round(float(r.min()), 4),
                  "r_max": round(float(r.max()), 4), "centre": [round(float(q[0]), 4), round(float(q[1]), 4)]}


def section_row(tree, centre, angles, z, planes, window):
    """A179 — one bodice row above the chest band read from the FULL body section (arm roots included) bounded by
    the two armhole planes (``planes`` = the world X of the left / right one): per column the outermost surface
    between the spine axis and the plane, met from the plane inward (the outermost one, so a lower garment layer or
    the wall of the armpit is not gone under), + BODICE_CLEAR_M along its normal. A ray that crosses the plane INSIDE
    the body runs into the arm root: a column of the armhole ``window`` ends on the plane (state 1: its rows are cut
    away or laid on the armhole ring by the caller), any other column follows the arm at most ARM_REACH_M to its
    surface (state 2). Returns ``(xy [n, 2], r0 [n], state [n])`` — r0 = the distance from the axis — or None when
    the axis is not inside the body at this height (the caller keeps the torso-only rule)."""
    cx, cy = centre
    n = len(angles)
    xy, r0, state = np.zeros((n, 2)), np.zeros(n), np.zeros(n, int)
    o = Vector((cx, cy, z))
    for c, a in enumerate(angles):
        d = Vector((math.cos(a), math.sin(a), 0.0))
        first = _exit_out(tree, o, d, 0.9)
        if first is None:
            return None
        rho_p = 9.0
        if d.x > 1e-6:
            rho_p = (planes[0] - cx) / d.x
        elif d.x < -1e-6:
            rho_p = (planes[1] - cx) / d.x
        start = min(0.6, rho_p)
        hit = tree.ray_cast(o + d * start, -d, start)
        if hit[0] is not None and hit[1].dot(d) > 0:
            r0[c] = start - hit[3] + BODICE_CLEAR_M / max(MIN_COS, float(hit[1].dot(d)))
        elif rho_p > 0.6:
            r0[c] = first[0] + BODICE_CLEAR_M / max(MIN_COS, first[1])
        else:
            r0[c], state[c] = rho_p, 1     # inside the arm root, on the armhole plane
            if c not in window:
                ex = _exit_out(tree, o + d * rho_p, d, ARM_REACH_M)
                if ex is not None:
                    r0[c], state[c] = rho_p + ex[0] + BODICE_CLEAR_M / max(MIN_COS, ex[1]), 2
        xy[c] = (cx + r0[c] * d.x, cy + r0[c] * d.y)
    return xy, r0, state


def _lay_path(tree, knots, clear):
    """A179 — a meridian's path as a dense polyline: the knots joined by straight pieces sampled every PATH_STEP_M,
    and every sample that stands closer than ``clear`` to the collider laid ``clear`` outside it
    (the chord from the shoulder line to the next row cut through a deltoid that stands high: A176). Returns
    ``(points, the index of every knot in them)``."""
    pts, idx = [np.array(knots[0], float)], [0]
    for a, b in zip(knots[:-1], knots[1:]):
        a, b = np.array(a, float), np.array(b, float)
        m = max(1, int(math.ceil(float(np.linalg.norm(b - a)) / PATH_STEP_M)))
        pts.extend(a + (b - a) * i / m for i in range(1, m + 1))
        idx.append(len(pts) - 1)
    Q = np.array(pts)
    if tree is not None:
        for i, p in enumerate(Q):
            v = Vector(p)
            loc, out = gd.signed_out(tree, v, 0.12)
            if loc is not None and (v - loc).dot(out) < clear:
                Q[i] = loc + out * clear
    return Q, idx


def window_cols(need_rad, n):
    """A179 — the half width of the armhole window in columns: enough of the ``n`` columns round the body to span
    ``need_rad`` either side of the side seam, between WINDOW_COLS and WINDOW_COLS_MAX."""
    return min(WINDOW_COLS_MAX, max(WINDOW_COLS, int(math.ceil(need_rad / (2 * math.pi / n) - 1e-9))))


def sleeve_ring_count(girths, loop_n):
    """A179 — the vertices of a sleeve ring: the sleeve's mean girth at SLEEVE_EDGE_M a vertex, at least 12 and at
    most the armhole loop's ``loop_n``."""
    return min(int(loop_n), max(12, int(round(float(np.mean(girths)) / SLEEVE_EDGE_M))))


def build_bodice(spec, btree, ftree, centre, arm, ctree=None, clear=0.008, kind=None, waist_y=None, row_c=None,
                 straight_straps=False):
    """Ruling A142 — the vertices and faces of a piece with a bodice (Blender world, Z up, front =
    -Y): the torso rows wrapped round the body like a skirt (row 0 = the shoulder line), a yoke ("cap") from the
    shoulder line in to the neck opening, laid on the shoulders, the armholes cut at the side seams with the sleeves
    grown out of the armhole loops along the arm bones, the neckline cut at the front, straps, an open front and a
    stand collar. Returns ``(verts, faces, info)``; info carries the vertex groups the caller needs.

    Pattern UV (plan 2026-11-20-template-cut-uv-texture): every face is labelled with its pattern part WHEN it is
    built (``info["face_part"]``, the ``uv_pattern.PARTS`` ids): a torso or yoke face of column c (between columns c
    and c + 1) is front (1) when c < N/4 or c >= 3N/4, else back (2) — the side seam runs down column N/4 / 3N/4
    below the armhole, the shoulder seam along that column's yoke meridian, whose shoulder-line vertex is the top of
    the armhole; the innermost yoke ring (k = K - 1) is the band (5) when the piece has a neck ring (no straps, not
    off-shoulder); collar rings are 6; sleeves 3 (l) / 4 (r). ``info["seam_edges"]`` = the cut edges that are no part
    border (each sleeve's underarm, the band's back centre), ``info["band_strip"]`` = the band's [outer, inner]
    vertex rows in u order, ``info["uv_caps"]`` = per sleeve side (armhole loop, shoulder vertex, underarm vertex) —
    all construction vertex ids. The UVs come from these labels alone (``pattern_uv_of``).

    A179 — with ``ctree`` (the BVH tree of ``gd.rest_collider``: the closed collider the drape meets) every vertex
    is built at least ``clear`` outside it: the rows above the armhole's bottom from the full body section
    (``section_row``), the armhole loop on the arm root, the neck opening from the neck surface (``neck_ring``), the
    yoke on the body's top surface (``_surface_z``), every meridian laid along the collider (``_lay_path``). Without
    it the A144 rules stand (torso-only radius, a circle round the neck joint).

    Step 3c / 3d (plan group B, phases C and D) — ``kind`` "jacket" or "dress", and since phases E + F a "top" with a
    collar or a placket (``garment_template.neck_rules``, the build arg ``neck_rules``; a top without either is built
    with ``kind`` None, its islands the bytes from before the phases; an off-shoulder or strapped top has no neck ring
    and is unchanged byte for byte either way): an open front's two fronts are ``left_front`` (39, columns c < N/4, the wearer's left, +X) and
    ``right_front`` (40, c >= 3N/4) (B7); the innermost yoke ring is the band only for a closed front without a collar
    and a crew / boat neckline or a scoop at most ``BAND_SCOOP_MAX_M`` deep (B8), else it belongs to the panel of its
    column; a dress's torso faces at or under the row nearest ``waist_y`` (the outline's waist, world Z) are the skirt
    part (37 front, 38 back; B6); a stand collar is cut at the back centre (``info["seam_edges"]``) when its ring is
    whole and its rows go to ``info["collar_rows"]`` (top to bottom, construction ids, u order) for a strip relaxed
    like the waistband (B9); ``info["marks"]`` = {line: (part, construction ids top to bottom)} — the closed front's
    centre line, an open front's two edges, from the neckline down to the hem (a dress: to the waist seam) — for the
    painted placket (B10, ``uv_pattern.mark_px``).

    Stage "geometry": ``row_c`` (``leg_centres``) = the centre a row under the chest band is wrapped round (a dress's
    skirt rows under the crotch; None: ``centre``)."""
    rows, cols = spec["rows"], spec["cols"]
    bod = spec["bodice"]
    N = 2 * (cols - 1)
    open_front = bool(bod.get("front_open"))
    nc = N + 1 if open_front else N
    angles = [1.5 * math.pi + c * 2 * math.pi / N for c in range(nc)]
    row_y = spec["row_y"]
    circ = []
    for r in range(rows):
        tot = 0.0
        for p_ in spec["panels"]:
            row = np.array(p_["grid_m"][r])
            tot += float(np.sum(np.linalg.norm(np.diff(row, axis=0), axis=1)))
        circ.append(tot)
    verts, faces, face_part = [], [], []
    tid = np.zeros((rows, nc), int)
    band_y = bod["band_y"]
    r_band = max(r for r in range(rows) if row_y[r] >= band_y - 1e-6) if any(y >= band_y for y in row_y) else rows - 1
    side_c = {"l": N // 4, "r": 3 * N // 4}

    panel_kind = kind in ("jacket", "dress", "top")
    fronts = kind in ("jacket", "dress") and open_front

    def col_part(c):
        """The pattern part of a torso / yoke face of column c: front (1) or back (2), the side seams at N/4, 3N/4;
        an open jacket's fronts left_front (39) / right_front (40) (B7)."""
        if fronts:
            return 39 if c < side_c["l"] else 40 if c >= side_c["r"] else 2
        return 1 if c < side_c["l"] or c >= side_c["r"] else 2
    waist_row = None
    if kind == "dress" and waist_y is not None:
        waist_row = int(min(range(rows), key=lambda r: abs(float(row_y[r]) - float(waist_y))))

    def torso_part(r, c):
        """A torso face's part: a dress's faces at or under the waist row are its skirt part (B6)."""
        p_ = col_part(c)
        if waist_row is not None and r >= waist_row:
            return 37 if p_ == 1 else 38
        return p_
    straps = bod["shoulders"] == "straps"
    # A179 — the armhole's bottom row lies UNDER the arms. The chest band is a share of the body height: on a body
    # with thick upper arms it met the T-posed arm's underside (5 mm above it on one copy), so the band's row ran 10
    # cm out along the arm and its vertices hung under the arm from their neighbours — the largest stretch left.
    arm_under = None
    if ctree is not None and not straps:
        for names in (("LeftArm", "LeftForeArm"), ("RightArm", "RightForeArm")):
            A, E = (_bone_world(arm, n) for n in names)
            t_ = (E - A) / max(1e-9, float(np.linalg.norm(E - A)))
            for d_ in ARM_UNDER_AT_M:
                ex = _exit_out(ctree, A + t_ * d_, (0.0, 0.0, -1.0), 0.3, gap=ARM_LAYER_GAP_M)
                if ex is not None:
                    zu = float(A[2] + t_[2] * d_ - ex[0])
                    arm_under = zu if arm_under is None else min(arm_under, zu)
        if arm_under is not None:
            under = [r for r in range(rows - 2) if row_y[r] <= arm_under - BODICE_CLEAR_M + 1e-4]
            if under:
                r_band = max(r_band, under[0])
    sleeves = bod.get("sleeve") is not None and not straps
    planes = (float(_bone_world(arm, "LeftArm")[0]) + ARMHOLE_OUT_M, float(_bone_world(arm, "RightArm")[0]) - ARMHOLE_OUT_M)

    def arm_ring(side, phi):
        """The arm-root section in the armhole plane at ``phi`` (from straight up, positive towards the front, -Y):
        its point + the rows' clearance, or None."""
        A = _bone_world(arm, "LeftArm" if side == "l" else "RightArm")
        xs = planes[0] if side == "l" else planes[1]
        d = (0.0, -math.sin(phi), math.cos(phi))
        ex = _exit_out(ctree, (xs, A[1], A[2]), d, 0.3)
        if ex is None:
            return None
        rr = ex[0] + BODICE_CLEAR_M / max(MIN_COS, ex[1])
        return np.array((xs, A[1] + rr * d[1], A[2] + rr * d[2]))
    wcols = WINDOW_COLS
    if ctree is not None and not straps:
        need = 0.0
        for side in side_c:
            xs = planes[0] if side == "l" else planes[1]
            for phi in (math.pi / 2, -math.pi / 2):
                p = arm_ring(side, phi)
                if p is not None:      # the angle about the bodice axis under which this side of the arm root lies
                    need = max(need, math.atan2(abs(p[1] - centre[1]) + WINDOW_ROOM_M, abs(xs - centre[0])))
        wcols = window_cols(need, N)
    window, border, interior = set(), set(), set()
    if not straps:
        for sc_ in side_c.values():
            window.update(range(sc_ - wcols, sc_ + wcols))      # face columns c..c+1
            border.update((sc_ - wcols, sc_ + wcols))
            interior.update(range(sc_ - wcols + 1, sc_ + wcols))
    # A179 — the rows above the chest band come from the full body section, arm roots included (``section_row``):
    # on the torso-only radius the armhole window and every column re-spaced through it stood 5-9 cm INSIDE the
    # shoulder, and the push out of the body was the stretch (A176 / A178)
    sections, laid = 0, {}
    for r in range(rows):
        z = row_y[r]
        w = min(1.0, max(0.0, (z - band_y) / ROW_BLEND_M))
        sec = section_row(ctree, centre, angles[:N], z, planes, interior) if ctree is not None and r < r_band else None
        if sec is None:
            cen = row_c[r] if row_c else centre
            rad = row_radii(btree, cen, angles[:N], z, circ[r], w=w)
            xy = np.c_[cen[0] + rad * np.cos(angles[:N]), cen[1] + rad * np.sin(angles[:N])]
            if ctree is not None:
                # A179: the collider closes the crease between the arm's underside and the lat that the body mesh
                # leaves open: a chest-band vertex built in that crease stood 12-22 mm inside the collider. Such a
                # vertex is laid on the nearest point outside it (under the arm), not farther out along its ray —
                # there the T-posed arm is in the way
                # (where the surface faces outward the vertex only moves out along its own ray, so two neighbours
                # never land on one point: under a bust they stood 1.4 mm apart and that edge read 2.07)
                for c in range(N):
                    d = Vector((math.cos(angles[c]), math.sin(angles[c]), 0.0))
                    v = Vector((xy[c, 0], xy[c, 1], z))
                    for _ in range(3):
                        loc, out = gd.signed_out(ctree, v, 0.12)
                        if loc is None or (v - loc).dot(out) >= clear - 1e-5:
                            break
                        if out.dot(d) < MIN_COS:
                            v = loc + out * clear
                            laid[(r, c)] = tuple(v)
                            break
                        v = v + d * ((clear - (v - loc).dot(out)) / out.dot(d))
                        xy[c] = (v.x, v.y)
        else:
            sections += 1
            xy, r0, state = sec
            perim = float(np.sum(np.linalg.norm(np.diff(np.vstack([xy, xy[:1]]), axis=0), axis=1)))
            ease = min(ROW_EASE_MAX_M, max(0.0, (circ[r] - perim) / (2 * math.pi)))
            # the same rule as ``row_radii``: the body-shaped row + the even ease, blended into the circle of the girth
            more = w * ease + (1 - w) * np.maximum(0.0, circ[r] / (2 * math.pi) - r0)
            for c in range(N):
                if state[c] != 1:          # 1 = on the armhole plane
                    xy[c] += more[c] * np.array((math.cos(angles[c]), math.sin(angles[c])))
        for c in range(nc):
            tid[r, c] = len(verts)
            verts.append(laid.get((r, c % N)) or (float(xy[c % N, 0]), float(xy[c % N, 1]), z))

    # A179 — the armhole loop lies on the arm root. Its top (the shoulder-line vertices of the window's columns)
    # runs over the arm-root section in the armhole plane, ARMHOLE_TOP_RAD either side of straight up. Each side
    # (a border column's rows down to the row under the arm) runs on down that section to the arm joint's height
    # and from there along the border column's own surface points — in front of / behind the arm root — to the
    # bottom row. Its bottom is that row under the arm.
    armhole = {}
    if ctree is not None and sections and not straps:
        for side, sc_ in side_c.items():
            fs = -1.0 if side == "l" else 1.0          # the sign of (c - sc_) on the front side of this window
            c0, c1 = sc_ - wcols, sc_ + wcols
            top = {c: arm_ring(side, ARMHOLE_TOP_RAD * fs * (c - sc_) / wcols) for c in range(c0, c1 + 1)}
            sides = {}
            for cb in (c0, c1):
                sg = 1.0 if (cb - sc_) * fs > 0 else -1.0
                sides[cb] = [arm_ring(side, sg * ph) for ph in np.linspace(ARMHOLE_TOP_RAD, math.pi / 2, 4)]
            if any(p is None for p in top.values()) or any(p is None for arc in sides.values() for p in arc):
                continue                   # no arm root to read: the section rows stay as they are
            for c, p in top.items():
                verts[tid[0, c]] = tuple(float(v) for v in p)
                armhole[c] = float(p[2])
            for cb, arc in sides.items():
                own = [np.array(verts[tid[r, cb]]) for r in range(1, r_band + 1) if row_y[r] < arc[-1][2] - 0.015]
                Qa, _ = _lay_path(ctree, arc + own if own else arc + [np.array(verts[tid[r_band, cb]])],
                                  clear + PATH_EXTRA_M)
                sa = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(Qa, axis=0), axis=1))]
                for r in range(1, r_band):
                    at = sa[-1] * r / r_band
                    verts[tid[r, cb]] = tuple(float(np.interp(at, sa, Qa[:, k])) for k in range(3))

    nj = bod["joints"].get("neck")
    ncx, ncy = (nj[0], -nj[2]) if nj else (centre[0], centre[1])
    depth = float(bod.get("depth_m") or 0.0)
    front_y = float(bod.get("front_y") or (row_y[0] - 0.045))
    top_z = row_y[0]
    span = nc - 1 if open_front else nc
    # A179 — the neck opening is read from the neck surface (``neck_ring``); every yoke line runs radially from its
    # centre, from the shoulder line's point in to the ring
    z_ring = bod["neck_y"] + NECK_RING_UP_M
    ring_info = {"source": "spec"}
    ring_a = np.array(angles[:N])
    ring_r = np.full(N, float(bod["neck_r"]))
    if ctree is not None:
        (ncx, ncy), ring_r, ring_info = neck_ring(ctree, arm, bod, angles[:N], z_ring)
    nxy = np.array((ncx, ncy))

    def ring_at(u):
        a = math.atan2(u[1], u[0])
        return float(np.interp((a - ring_a[0]) % (2 * math.pi), ring_a - ring_a[0], ring_r, period=2 * math.pi))
    inner, outer = [], []
    front, side = np.zeros(nc), np.zeros(nc)   # cosine / |sine| of each column's angle from the front, at the ring
    for c in range(nc):
        p = np.array(verts[tid[0, c]][:2])
        d = p - nxy
        rho = float(np.linalg.norm(d))
        u = d / max(rho, 1e-9)
        # the yoke runs at least CAP_MIN_M outward from the neck opening (a row hugging the neck lies inside it)
        outer.append(nxy + u * max(rho, ring_at(u) + CAP_MIN_M))
        # on the ring the columns keep their own angles, evenly round the opening (the shoulder line's points beside
        # a neck that stands in front of the arms all lie in ONE direction from it: yoke lines drawn radially to
        # them ran 1.5 mm apart), at most YOKE_SKEW_RAD off the direction of the column's shoulder-line point
        psi = math.atan2(u[1], u[0])
        skew = (angles[c] - psi + math.pi) % (2 * math.pi) - math.pi
        ai = psi + min(YOKE_SKEW_RAD, max(-YOKE_SKEW_RAD, skew))
        ui = np.array((math.cos(ai), math.sin(ai)))
        inner.append(nxy + ring_at(ui) * ui)
        front[c], side[c] = -ui[1], abs(ui[0])
    reach = max(float(np.linalg.norm(outer[c] - inner[c])) for c in range(nc))
    K = max(3, int(round(reach / 0.015)))
    cid = np.zeros((K + 1 + COLLAR_RINGS, nc), int)
    cid[0] = tid[0]
    # the yoke lies on the body's top surface under a ceiling that opens like a cone from the ring (the neck base +
    # NECK_RING_UP_M at the ring: the yoke never climbs onto the head; the full height over the shoulders)
    capz = np.zeros((K + 1, nc))
    capxy = np.zeros((K + 1, nc, 2))
    floor_z = top_z - 0.08
    for k in range(0, K + 1):
        t = k / K
        for c in range(nc):
            xy = (1 - t) * outer[c] + t * inner[c]
            capxy[k, c] = xy
            if k == 0 and c in armhole:
                capz[k, c] = armhole[c]    # the top of the armhole, on the arm-root ring
            elif ctree is not None:
                z_hi = z_ring + min(0.10, float(np.linalg.norm(xy - inner[c])))
                zs = _surface_z(ctree, xy[0], xy[1], z_hi, floor_z)
                if zs:
                    capz[k, c] = max(floor_z, zs[0] + CAP_CLEAR_M / max(0.5, zs[1]))
                elif zs is None:           # beside the body, or in front of it under the chin
                    capz[k, c] = floor_z
                else:
                    # INSIDE the body there (hair hanging over the shoulder, a ridge of the trapezius): the point
                    # keeps the height of the ring before it (the shoulder line's own height at the outer end) and
                    # ``_lay_path`` lays it outside
                    capz[k, c] = capz[k - 1, c] if k else top_z
            else:
                zs = _ray_down(ftree, xy[0], xy[1], top=max(top_z, bod["neck_y"]) + 0.035)
                capz[k, c] = max(floor_z, (zs + CAP_CLEAR_M) if zs is not None else floor_z)
    # A179 — the neck rim. Its height round the opening is the surface height at the ring smoothed from above
    # (``env``): where the surface lies under it the yoke bridges up to it (NECK_BRIDGE_SLOPE).
    hr = capz[K, :N].copy()
    env = hr.copy()
    for _ in range(NECK_ENV_PASSES):
        env = np.maximum((np.roll(env, 1) + 2 * env + np.roll(env, -1)) / 4, hr)
    for c in range(nc):
        for k in range(1, K + 1):
            away = float(np.linalg.norm(capxy[k, c] - inner[c]))
            capz[k, c] = max(capz[k, c], env[c % N] - NECK_BRIDGE_SLOPE * away)
    for k in range(1, K + 1):
        for c in range(nc):
            cid[k, c] = len(verts)
            verts.append((float(capxy[k, c, 0]), float(capxy[k, c, 1]), float(capz[k, c])))
    # Ruling A144 — the neckline is ONE smooth curve. Every column is a meridian: from the neck ring out over the
    # yoke ("cap") to the shoulder line and down the torso rows to the hem. A179: the path the cloth takes is laid
    # on the collider (``_lay_path``): the yoke on the shoulders, the shoulder line's point at the surface height
    # there, then the rows below it (a row above the surface there is air: the A142 stand wall); a column of the
    # armhole window ends at the shoulder line's point — the top of the armhole, on the arm root.
    paths = []
    for c in range(nc):
        ids = [cid[k, c] for k in range(K, 0, -1)] + [tid[r, c] for r in range(rows)]
        z_surf = capz[0, c]
        ends = c in interior or c in armhole
        knots = [verts[i] for i in ids[:K]] + [(outer[c][0], outer[c][1], z_surf)]
        low = [] if ends else [r for r in range(rows) if row_y[r] < z_surf - 0.005]
        knots += [verts[tid[r, c]] for r in low]
        Q, kidx = _lay_path(ctree, knots, clear + PATH_EXTRA_M)
        s = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(Q, axis=0), axis=1))]
        paths.append((ids, z_surf, ends, low, Q, kidx, s))
    # A179 — the cut is measured ALONG the meridian: the front-centre meridian is cut where it first runs below
    # ``front_y - depth`` (front_y = the jugular notch, the shoulder-joint height), every other meridian of the front
    # half at that length x the neckline's shape over its angle from the front (crew / scoop / boat: cos^NECK_ROUND_POW, a round
    # opening that meets the ring without a corner; V: 1 - |sin|, straight edges seen from the front). A cut where
    # the meridian reaches a HEIGHT ran 5 cm out over the flat top of the shoulder beside the neck — a notch either
    # side of the front — and a cut by the column's distance from the centre ended in a step behind the neck.
    c_front = int(np.argmax(front))
    Qf, sf = paths[c_front][4], paths[c_front][6]
    below = np.where(Qf[:, 2] <= front_y - depth)[0]
    s_front = 0.0
    if len(below) and below[0] > 0:
        j = int(below[0])
        f_ = (Qf[j - 1, 2] - (front_y - depth)) / max(1e-9, Qf[j - 1, 2] - Qf[j, 2])
        s_front = float(sf[j - 1] + f_ * (sf[j] - sf[j - 1]))
    cut_s = [0.0] * nc
    cap_set = set()
    for c in range(nc):
        ids, z_surf, ends, low, Q, kidx, s = paths[c]
        sk = s[kidx]                       # the arc length at every knot
        cap_set.update(int(i) for i in ids[:K])
        sc_ = 0.0
        if front[c] > 0:
            sc_ = s_front * ((1 - side[c]) if bod["neckline"] == "v" else front[c] ** NECK_ROUND_POW)
        cut_s[c] = sc_ if sc_ >= 0.002 else 0.0
        if ends:
            n_move, s_end = K, float(sk[K])
            verts[tid[0, c]] = tuple(float(v) for v in Q[kidx[K]])
        else:
            z_lo = min(z_surf, float(np.interp(cut_s[c], s, Q[:, 2]))) - NECK_BLEND_M
            keep = [r for r in low if row_y[r] <= z_lo]
            if len(keep) < 2:
                continue                   # never on a sane body: the cut would eat the column
            if waist_row is not None and any(r <= waist_row for r in keep):
                # B6: a dress's re-spaced stretch ends at its waist row at the latest — the waist seam is a construction
                # row, and rows re-spaced past it carried the skirt part's top up into a deep V (Ylva: an 8 cm notch)
                keep = [r for r in keep if r <= waist_row]
            # A178: the re-spaced stretch reaches down until its vertices stand NECK_MIN_STEP_M apart (crowded into
            # a short arc under a deep front cut they stood 4-7 mm apart, and a short edge takes the drape's pull as
            # a large ratio: p99 1.23 against 1.03 for 14-30 mm edges on the copies)
            for rk in keep:
                s_end = float(sk[K + 1 + low.index(rk)])
                if (s_end - cut_s[c]) / (K + rk) >= NECK_MIN_STEP_M:
                    break
            n_move = K + rk                # ids[:n_move] are re-spaced over [cut, s_end)
        ns = cut_s[c] + (s_end - cut_s[c]) * np.arange(n_move) / n_move
        newp = np.c_[np.interp(ns, s, Q[:, 0]), np.interp(ns, s, Q[:, 1]), np.interp(ns, s, Q[:, 2])]
        for i, p, si in zip(ids[:n_move], newp, ns):
            verts[i] = tuple(float(v) for v in p)
            if si < sk[K]:
                cap_set.add(int(i))
            else:
                cap_set.discard(int(i))
    # A179 — the yoke and the rows above the armhole's bottom are evened out: every vertex moves half-way to the mean
    # of its grid neighbours and is laid outside the collider again, RELAX_PASSES times. The rim, the armhole loop
    # and the rows from the armhole's bottom down stay. (Section radii read through a grazing deltoid jump from row to
    # row and neighbouring meridians are re-spaced over different lengths: the cells stood as a faceted, folded
    # patch in front of and behind each armhole, and the yoke is pinned as built.)
    if ctree is not None and sections:
        G = np.vstack([cid[K:0:-1], tid[:r_band + 1]])        # [meridian index, column]
        nm = G.shape[0]
        free = np.zeros(G.shape, bool)
        free[1:nm - 1] = True
        loose = np.zeros(G.shape, bool)
        for c in range(nc):
            if c in interior:
                free[K:, c] = False
                loose[K + 1:nm - 1, c] = True
            elif c in armhole:
                free[K:, c] = False
        P = np.array([[verts[G[m, c]] for c in range(nc)] for m in range(nm)], float)
        for _ in range(RELAX_PASSES):
            acc = np.zeros_like(P)
            cnt = np.zeros(G.shape)
            for dm, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                src = np.roll(P, (-dm, -dc), axis=(0, 1))
                ok = np.roll(~loose, (-dm, -dc), axis=(0, 1))
                if dm:                     # no neighbour beyond the first / last meridian index
                    ok[-1 if dm > 0 else 0] = False
                if dc and open_front:      # the two front edges of an open front are not neighbours
                    ok[:, -1 if dc > 0 else 0] = False
                acc += np.where(ok[..., None], src, 0.0)
                cnt += ok
            new = np.where((free & (cnt > 0))[..., None], 0.5 * P + 0.5 * acc / np.maximum(cnt, 1)[..., None], P)
            for m, c in zip(*np.where(free)):
                v = Vector(new[m, c])
                loc, out = gd.signed_out(ctree, v, 0.12)
                if loc is not None and (v - loc).dot(out) < clear:
                    new[m, c] = loc + out * clear
            P = new
        for m in range(nm):
            for c in range(nc):
                if free[m, c]:
                    verts[G[m, c]] = tuple(float(x) for x in P[m, c])
    for r in range(rows - 1):
        for c in range(span):
            c2 = (c + 1) % nc
            if r < r_band and c in window:
                continue
            faces.append((tid[r, c], tid[r, c2], tid[r + 1, c2], tid[r + 1, c]))
            face_part.append(torso_part(r, c))
    collar = bod.get("collar") in ("stand", "lapel")
    nring = K + (COLLAR_RINGS if collar else 0)
    for k in range(K + 1, nring + 1):
        rad, need, ang, zs = [], [], [], []
        for c in range(nc):
            x, y, z = verts[cid[K, c]]
            sh = 0.97 ** (k - K)
            a_ = math.atan2(y - ncy, x - ncx)
            zk = z + COLLAR_STEP_M * (k - K)
            rad.append(math.hypot(x - ncx, y - ncy) * sh)
            ang.append(a_)
            zs.append(zk)
            ex = _exit_out(ctree, (ncx, ncy, zk), (math.cos(a_), math.sin(a_), 0.0), 0.3) \
                if ctree is not None and collar else None
            need.append(ex[0] + clear if ex is not None else 0.0)
        rad, need = np.array(rad), np.array(need)
        if ctree is not None and need.any():
            # Phase F: a ring that stands inside the neck is laid out of it as a SMOOTH ring — the radius is the
            # larger of the construction's and the neck section's + ``clear``, then evened out by the neck ring's own
            # rule (1-2-1 passes, never below the section). ``clear_of_body`` used to push the inside vertices out one
            # by one: a stand collar on Dario's crew neck came out wavy (stretch p95 1.24, flattened from its strip).
            r_ = np.maximum(rad, need)
            for _ in range(3):
                r_ = np.maximum((np.roll(r_, 1) + 2 * r_ + np.roll(r_, -1)) / 4, need)
            rad = r_
        for c in range(nc):
            cid[k, c] = len(verts)
            verts.append((ncx + rad[c] * math.cos(ang[c]), ncy + rad[c] * math.sin(ang[c]), zs[c]))
    # the band: the innermost yoke ring, whenever the piece has a neck ring; a jacket's / dress's only under B8
    neck_band = not straps and not bod.get("off_shoulder")
    if panel_kind:
        nl, dep = bod.get("neckline"), float(bod.get("depth_m") or 0.0)
        neck_band = neck_band and not open_front and bod.get("collar") in (None, "none") and (
            nl in ("crew", "boat", "scoop") and dep <= BAND_SCOOP_MAX_M + 1e-9)
    collar_cols = set()
    for k in range(nring):
        for c in range(span):
            c2 = (c + 1) % nc
            if k >= K and max(cut_s[c], cut_s[c2]) > COLLAR_CUT_MAX_M:
                continue                   # the collar ends where the neckline runs down the front (its gorge)
            if k >= K:
                collar_cols.add(c)
            faces.append((cid[k, c], cid[k, c2], cid[k + 1, c2], cid[k + 1, c]))
            face_part.append(6 if k >= K else 5 if (k == K - 1 and neck_band) else col_part(c))
    seam_edges, band_strip = [], None
    if neck_band:
        # u from the back centre through the wearer's right (3N/4), the front (0) and left (N/4) back to the back
        # centre — the order seen from outside; the neck edge (ring K) is the strip's inner (up) row. A closed band
        # is cut at the back centre; an open front is already open there.
        order = list(range(0, nc)) if open_front else [(N // 2 + i) % N for i in range(N + 1)]
        band_strip = [[int(cid[K - 1, c]) for c in order], [int(cid[K, c]) for c in order]]
        if not open_front:
            seam_edges.append((int(cid[K - 1, N // 2]), int(cid[K, N // 2])))
    collar_rows = None
    if panel_kind and bod.get("collar") == "stand" and collar_cols:
        # B9: the stand collar is a strip (``uv_pattern.rows_strip_uv``), u in the band's order (c growing: from the
        # back centre through the wearer's right, the front and the left — to the right as seen from outside); a
        # whole ring is cut at the back centre, a ring the gorge opened runs from the gorge's left edge round the back
        # to its right edge
        if len(collar_cols) == span and not open_front:
            order = [(N // 2 + i) % N for i in range(N + 1)]
            seam_edges.extend((int(cid[k, N // 2]), int(cid[k + 1, N // 2])) for k in range(K, nring))
        else:
            starts = [c for c in sorted(collar_cols) if (c - 1) % nc not in collar_cols]
            order = []
            if len(starts) == 1:           # one piece of collar (two would be two islands: flattened as panels)
                c = starts[0]
                while c in collar_cols:
                    order.append(c)
                    c = (c + 1) % nc
                order.append(c)
        if order:
            collar_rows = [[int(cid[k, c]) for c in order] for k in range(nring, K - 1, -1)]
    # the binding: the neck rim and the next ring in (the innermost two rings of every meridian, or the collar)
    rib_ids = sorted({int(cid[k, c]) for c in range(nc) for k in (nring, nring - 1)})
    # sleeves: ring 0 = the armhole loop
    sleeve_rows = {}
    uv_caps = {}
    if sleeves:
        sl = bod["sleeve"]
        for side, sc_ in side_c.items():
            c0, c1 = sc_ - wcols, sc_ + wcols
            loop = [tid[0, c] for c in range(c0, c1 + 1)]
            loop += [tid[r, c1] for r in range(1, r_band + 1)]
            loop += [tid[r_band, c] for c in range(c1 - 1, c0 - 1, -1)]
            loop += [tid[r, c0] for r in range(r_band - 1, 0, -1)]
            names = ("LeftArm", "LeftForeArm", "LeftHand") if side == "l" else ("RightArm", "RightForeArm", "RightHand")
            A, E, H = (_bone_world(arm, n) for n in names)
            seg = [(A, E), (E, H)]
            lens = [float(np.linalg.norm(b - a)) for a, b in seg]

            def axis_at(d):
                if d <= lens[0]:
                    a, b = seg[0]
                    return a + (b - a) * d / lens[0], (b - a) / lens[0]
                a, b = seg[1]
                t = min(1.0, (d - lens[0]) / lens[1])
                return a + (b - a) * t, (b - a) / lens[1]
            L = np.array([verts[i] for i in loop])
            t0 = (E - A) / lens[0]
            d0 = float(np.dot(L.mean(0) - A, t0))
            Q0, _ = axis_at(max(0.0, d0))
            e1 = np.cross(t0, [0.0, 0.0, 1.0])
            e1 /= np.linalg.norm(e1)
            e2 = np.cross(e1, t0)
            phi = np.unwrap(np.arctan2((L - Q0) @ e2, (L - Q0) @ e1))
            turn = math.copysign(2 * math.pi, phi[-1] - phi[0])
            # stage "geometry" (Tilda's cardigan over an elbow-sleeved blouse, 1.462): an outer layer's sleeve
            # (``layer_ease``: a jacket over a sleeved layer) hangs from and clears the LOWER sleeve, not the bare arm
            # — built round the arm it hung from the arm's top, inside the blouse sleeve that hangs from there too
            stree = ctree if (spec.get("layer_ease") and ctree is not None and OUTER_SLEEVE_CLEAR) else ftree
            ring_ds = [(d, c) for d, c in sl["rings"] if d > d0 + 0.02]
            if not ring_ds or ring_ds[-1][0] < sl["len_m"] - 1e-3:
                ring_ds.append((max(sl["len_m"], d0 + 0.03), sl["rings"][-1][1]))
            M = len(loop)
            # A179: a sleeve ring has as many vertices as its girth asks for (SLEEVE_EDGE_M apart), not as many as
            # the armhole loop: Blender's cloth mass is PER VERTEX, so a ring of 48 vertices 7-10 mm apart (the loop
            # of a wide armhole) weighed twice the torso's cloth and stretched the sleeve's top to 1.33. The first
            # ring is joined to the loop by quads and triangles.
            Ms = sleeve_ring_count([c for _d, c in ring_ds], M)
            at = np.arange(Ms) * M / Ms                                  # each ring vertex's place along the loop
            phi_c = np.r_[phi, phi[0] + turn]
            L_c = np.vstack([L, L[:1]])
            phi_m = np.interp(at, np.arange(M + 1), phi_c)
            L_m = np.c_[[np.interp(at, np.arange(M + 1), L_c[:, k]) for k in range(3)]].T
            # Ruling A144: along the sleeve the ring vertices spread evenly round the arm (the armhole loop's spacing
            # is uneven: bunched vertices made 4.7 mm edges that took the drape's largest stretch at the cuff)
            even = phi[0] + turn * np.arange(Ms) / Ms
            prev = loop
            rows_ids = [loop]
            f_start = len(faces)
            for j, (d, cj) in enumerate(ring_ds, start=1):
                Q, t = axis_at(d)
                f1 = np.cross(t, [0.0, 0.0, 1.0])
                f1 /= np.linalg.norm(f1)
                f2 = np.cross(f1, t)
                w = min(1.0, max(0.0, (d - d0) / SLEEVE_BLEND_M))
                w = w * w * (3 - 2 * w)
                # A179: a ring wider than the arm HANGS from the arm's top as built (its centre lowered until its top
                # stands SLEEVE_CLEAR_M over the arm). Built round the arm's axis it fell 1-2 cm in the drape, landed
                # on its top two vertices and the collider's friction kept the pull of the fall in the edge between
                # them: 1.31 on one edge of an otherwise slack ring.
                r_ring = cj / (2 * math.pi)
                hang = max(0.0, r_ring - (_ray_in(stree, Q, f2) + SLEEVE_CLEAR_M))
                cur = []
                for i in range(Ms):
                    ang = (1 - w) * phi_m[i] + w * even[i]
                    dirv = math.cos(ang) * f1 + math.sin(ang) * f2
                    target = Q - hang * f2 + r_ring * dirv
                    off = target - Q
                    dist = float(np.linalg.norm(off))
                    need = _ray_in(stree, Q, off / max(dist, 1e-9)) + SLEEVE_CLEAR_M
                    if dist < need:
                        target = Q + off / max(dist, 1e-9) * need
                    moved = L_m[i] + (Q - Q0)
                    p = (1 - w) * moved + w * target
                    if ctree is not None and float(np.dot(p - Q, f2)) > 0:
                        # the armhole's top carried out along a thinning arm floats over it: lowered onto the arm
                        zs = _surface_z(ctree, p[0], p[1], float(p[2]) + 1e-3, float(Q[2]))
                        if zs:
                            p[2] = min(p[2], zs[0] + SLEEVE_CLEAR_M / max(0.5, zs[1]))
                    cur.append(len(verts))
                    verts.append(tuple(p))
                P = len(prev)
                for i in range(P):
                    i2 = (i + 1) % P
                    a_, b_ = (i * Ms) // P, ((i + 1) * Ms) // P
                    if a_ == b_:           # two loop vertices share this ring vertex
                        faces.append((prev[i], prev[i2], cur[a_]))
                    else:
                        faces.append((prev[i], prev[i2], cur[b_ % Ms], cur[a_]))
                    face_part.append(3 if side == "l" else 4)
                prev = cur
                rows_ids.append(cur)
            sleeve_rows[side] = rows_ids
            # the underarm cut: the loop index of tid[r_band, sc_] is i0 = 3 wcols + r_band (row 0 over c0..c1:
            # 2 wcols + 1 entries, column c1 down: r_band, row r_band back from c1 - 1: sc_ is the wcols-th). The first
            # strip's face i0 closes with the edge loop[i0] - ring1[k0], k0 = (i0 Ms) // M; every later strip has
            # P = Ms, so the cut runs on as ring_j[k0] - ring_j+1[k0] to the cuff.
            i0 = 3 * wcols + r_band
            k0 = (i0 * Ms) // M
            seam_edges.append((int(loop[i0]), int(rows_ids[1][k0])))
            for ra, rb in zip(rows_ids[1:], rows_ids[2:]):
                seam_edges.append((int(ra[k0]), int(rb[k0])))
            uv_caps[side] = ([int(v) for v in loop], int(tid[0, sc_]), int(loop[i0]))
            if ctree is not None:
                # A179: the rings blended from the armhole loop (the first SLEEVE_BLEND_M) are evened out like the
                # yoke — each vertex half-way to the mean of its neighbours — and every ring vertex is laid outside
                # the collider (a ring carried out from the loop may dip into the arm)
                blend = [ring_ids for (d, _c), ring_ids in zip(ring_ds, rows_ids[1:]) if d - d0 < SLEEVE_BLEND_M]
                mov = sorted({int(i) for ring_ids in blend for i in ring_ids})
                nb = {i: set() for i in mov}
                for f in faces[f_start:]:
                    for a_, b_ in zip(f, f[1:] + f[:1]):
                        if a_ in nb:
                            nb[a_].add(int(b_))
                        if b_ in nb:
                            nb[b_].add(int(a_))
                for _ in range(RELAX_PASSES if mov else 0):
                    new = {i: 0.5 * np.array(verts[i]) + 0.5 * np.mean([verts[j] for j in nb[i]], axis=0)
                           for i in mov if nb[i]}
                    for i, p_ in new.items():
                        verts[i] = tuple(float(x) for x in p_)
                    for i in mov:
                        v = Vector(verts[i])
                        loc, out = gd.signed_out(ctree, v, 0.12)
                        if loc is not None and (v - loc).dot(out) < clear:
                            verts[i] = tuple(loc + out * clear)
                for ring_ids in rows_ids[1:]:
                    for i in ring_ids:
                        v = Vector(verts[i])
                        loc, out = gd.signed_out(ctree, v, 0.12)
                        if loc is not None and (v - loc).dot(out) < clear:
                            verts[i] = tuple(loc + out * clear)
    # straps: above the chest band only the strap strips stay
    V = np.array(verts)
    keep = []
    edge = bod.get("top_edge") or {}
    dip, half_rad = float(edge.get("dip_m") or 0.0), float(edge.get("half_rad") or 0.5)
    off_cut = off_shoulder_cutter(bod.get("off_shoulder"), arm, ncx, ncy)

    def side_drop(dx):
        """Stage "geometry": how far a strapped piece's top edge is lowered |x - centre| = ``dx`` out (0 to the strap's
        outer edge + ARMHOLE_DROP_FROM_M, ARMHOLE_DROP_M at the side, smoothstep between)."""
        w_ = (dx - bod["strap_x"] - bod["strap_w"] / 2 - ARMHOLE_DROP_FROM_M) / ARMHOLE_DROP_RAMP_M
        w_ = min(1.0, max(0.0, w_))
        return ARMHOLE_DROP_M * w_ * w_ * (3 - 2 * w_)
    for f, fp in zip(faces, face_part):
        cen = V[list(f)].mean(0)
        x, z = cen[0] - ncx, cen[2]
        if off_cut is not None and off_cut(cen):
            continue
        if straps and z > band_y + 0.005 and abs(abs(x) - bod["strap_x"]) > bod["strap_w"] / 2:
            continue
        if (straps and straight_straps and abs(x) > bod["strap_x"] + bod["strap_w"] / 2
                and z > band_y + 0.005 - side_drop(abs(x))):
            continue                        # stage "geometry": the armhole scooped down towards the side seam
        if straps and dip > 0 and cen[1] < centre[1]:
            # A221: a sweetheart top edge — round the front centre (1.5 pi about the axis) the band is lowered by
            # dip * (1 - |angle off centre| / half_rad)^2, the drop of the strapless top's ``top_drop``
            off = abs((math.atan2(cen[1] - centre[1], cen[0] - centre[0]) % (2 * math.pi)) - 1.5 * math.pi)
            if off < half_rad and z > band_y + 0.005 - dip * (1.0 - off / half_rad) ** 2:
                continue
        keep.append((f, fp))
    faces = [f for f, _ in keep]
    face_part = [fp for _, fp in keep]
    if straps and (edge or straight_straps):
        # A221 (stage "geometry": every strapped piece with ``straight_straps``, Lirien's dress): a corset top's straps are cut along the columns, which cross the strap's edge at a slant (a saw-tooth
        # border): every vertex only of strap faces (centre above the band) is drawn in to the strap's straight edge |x - strap_x| <= w / 2
        # (two vertices drawn onto one point leave a degenerate edge the caller dissolves)
        hw = bod["strap_w"] / 2
        V = np.array(verts)
        up = [V[list(f)].mean(0)[2] > band_y + 0.005 for f in faces]
        strap_v = {i for f, u in zip(faces, up) if u for i in f} - {i for f, u in zip(faces, up) if not u for i in f}
        for i in strap_v:
            x, y, z = verts[i]
            d = x - ncx
            sx = math.copysign(bod["strap_x"], d)
            verts[i] = (ncx + sx + max(-hw, min(hw, d - sx)), y, z)
        if straight_straps:
            # stage "geometry" (Lirien's dress, live 2026-11-22: saw-tooth straps and a stepped top edge): the faces are
            # kept by their centre, so the open border still steps one column / one row at a time. Every BORDER vertex
            # above the band is drawn onto the line it belongs to — one of a strap face onto the strap's nearer edge
            # (x = strap_x +- w / 2), one of band faces only (and a strap's foot) down onto the band top (band_y +
            # 5 mm) — a straight strap and a straight top edge in the cloth and so in the pattern.
            count = {}
            for f in faces:
                for a_, b_ in zip(f, f[1:] + f[:1]):
                    e_ = (min(a_, b_), max(a_, b_))
                    count[e_] = count.get(e_, 0) + 1
            border = {i for e_, n_ in count.items() if n_ == 1 for i in e_}
            on_strap = {i for f, u in zip(faces, up) if u for i in f}
            on_band = {i for f, u in zip(faces, up) if not u for i in f}
            top = band_y + 0.005
            for i in border:
                x, y, z = verts[i]
                if z <= band_y - side_drop(abs(x - ncx)) - BAND_SNAP_M:
                    continue
                v0 = Vector((x, y, z))
                loc, out = gd.signed_out(ctree, v0, 0.12) if ctree is not None else (None, None)
                gap = (v0 - loc).dot(out) if loc is not None else None
                for _ in range(3):
                    # drawn onto its line, then back onto its own distance from the body (a strap over the shoulder
                    # blade moved in x alone stood off or sank in: a saw-tooth in depth the flattening kept)
                    d = x - ncx
                    sx = math.copysign(bod["strap_x"], d)
                    if i in on_strap:
                        x = ncx + sx + math.copysign(hw, d - sx)
                    if i in on_band:
                        z = top - side_drop(abs(x - ncx))
                    if gap is None:
                        break
                    loc, out = gd.signed_out(ctree, Vector((x, y, z)), 0.12)
                    if loc is None:
                        break
                    x, y, z = (float(c) for c in loc + out * gap)
                d = x - ncx
                sx = math.copysign(bod["strap_x"], d)
                if i in on_strap:
                    x = ncx + sx + math.copysign(hw, d - sx)
                if i in on_band:
                    z = top - side_drop(abs(x - ncx))
                verts[i] = (x, y, z)
            # a step's two corners drawn onto one line stand a few mm apart: a border edge that short took the
            # drape's stretch (Lirien's dress 1.459 on a 3.5 mm edge) — its two ends become one point, which the
            # caller's ``dissolve_degenerate`` merges
            for (a_, b_), n_ in count.items():
                if n_ != 1 or a_ not in border or b_ not in border:
                    continue
                pa, pb = np.array(verts[a_]), np.array(verts[b_])
                if max(pa[2], pb[2]) > band_y - ARMHOLE_DROP_M - BAND_SNAP_M and float(np.linalg.norm(pa - pb)) < STRAP_MERGE_M:
                    mid = tuple(float(c) for c in (pa + pb) / 2)
                    verts[a_] = verts[b_] = mid
    used = {i for f in faces for i in f}
    cap_ids = sorted(cap_set & used)
    loops = {int(i) for rows_ids in sleeve_rows.values() for i in rows_ids[0]}
    slv = {int(i) for rows_ids in sleeve_rows.values() for ring in rows_ids[1:] for i in ring}
    yoke = {int(i) for i in cid[1:nring + 1].ravel()}
    upper = {int(i) for i in tid[:r_band].ravel()} - loops
    regions = {"yoke": yoke, "upper_rows": upper, "armhole": loops, "sleeves": slv,
               "lower_rows": {int(i) for i in tid[r_band:].ravel()} - loops}
    marks = {}
    if panel_kind:
        # B10 / B11: the placket's lines as construction ids, top (the neckline) to bottom (the hem; a dress: the waist
        # seam) — a closed front's centre meridian (column 0), an open front's two edges (columns 0 and nc - 1)
        last = waist_row if waist_row is not None else rows - 1

        def meridian(c):
            return [int(cid[k, c]) for k in range(K, 0, -1)] + [int(tid[r, c]) for r in range(last + 1)]
        if open_front:
            marks = {"edge_left": (39, meridian(0)), "edge_right": (40, meridian(nc - 1))}
        else:
            marks = {"centre_front": (1, meridian(0))}
    info = {"cap_ids": cap_ids, "rib_ids": sorted(set(rib_ids) & used),
            "regions": {k: sorted(v & used) for k, v in regions.items()},
            "cut_s": [round(x, 3) for x in cut_s], "sleeve_rings": {k: len(v) - 1 for k, v in sleeve_rows.items()}, "cap_rings": K,
            "collar_rings": nring - K, "columns": nc, "window_cols": wcols, "r_band": r_band, "arm_under_z": None if arm_under is None else round(arm_under, 4), "section_rows": sections, "neck_ring": ring_info,
            "face_part": face_part, "seam_edges": seam_edges, "band_strip": band_strip, "uv_caps": uv_caps,
            "collar_rows": collar_rows, "marks": marks, "waist_row": waist_row}
    return verts, faces, info


def _off_arm_lat(arm, ncx, off):
    """A229: where the band crosses each upper arm, sideways from the neck joint (left, right; metres)."""
    return tuple(abs(float(_bone_world(arm, n)[0]) - ncx) + float(off["arm_out_m"]) for n in ("LeftArm", "RightArm"))


def off_shoulder_cutter(off, arm, ncx, ncy):
    """A229 — the face test of an off-shoulder piece (None for every other piece): a face goes when its centre lies
    above the band's top edge ``line_y`` (Blender Z) within the band's crossing of the upper arm (``_off_arm_lat``) —
    the yoke, the shoulders and the top of each sleeve's cap; the sleeve beyond the crossing stays whole, and under
    the line the armpit joins the sleeve to the body as built. With front lacing also the faces of the centre front
    (``-Y`` of the neck joint) within ``gap_m`` / 2 of the centre, from the band down ``depth_m``."""
    if not off:
        return None
    line = float(off["line_y"])
    lat_l, lat_r = _off_arm_lat(arm, ncx, off)
    lace = off.get("lace") or None

    def cut(cen):
        x = float(cen[0]) - ncx
        z = float(cen[2])
        if z > line and abs(x) < (lat_l if x >= 0 else lat_r):
            return True
        if lace and float(cen[1]) < ncy and abs(x) < float(lace["gap_m"]) / 2 and z > line - float(lace["depth_m"]):
            return True
        return False
    return cut


def off_shoulder_pins(obj, off, arm, ncx):
    """A229 — the pins of an off-shoulder piece: the elastic band, every vertex within ``band_m`` under the top edge
    ``line_y`` across the chest and the back and up to ``band_m`` beyond the band's crossing of each upper arm (the
    band's strip round the top of the arm). The band holds the piece below the shoulders and carries the sleeves;
    the rest (the body, the sleeves, the lacing's edges) hangs free."""
    co = np.array([v.co for v in obj.data.vertices])
    line, band = float(off["line_y"]), float(off["band_m"])
    lat_l, lat_r = _off_arm_lat(arm, ncx, off)
    x = co[:, 0] - ncx
    lat = np.where(x >= 0, lat_l, lat_r)
    return np.where((co[:, 2] >= line - band) & (np.abs(x) <= lat + band))[0]


def inside_report(tree, verts, regions, thickness):
    """A179 — where the piece stands against the drape's collider AS BUILT (before the clearance pass), per region
    (``yoke``, ``upper_rows`` = the torso rows above the chest band, ``armhole`` = the armhole loops, ``sleeves``,
    ``lower_rows``): ``verts``, ``inside`` (vertices inside the body) with ``max_inside_mm`` (the deepest), and
    ``short`` (vertices closer than the pre-inflate's ``thickness`` + 3 mm) — the pre-inflate moves exactly those."""
    V = np.array(verts, float)
    out = {}
    for name, ids in regions.items():
        if not ids:
            continue
        sd = gd.signed_depth(tree, V[ids])
        out[name] = {"verts": len(ids), "inside": int((sd < 0).sum()),
                     "max_inside_mm": round(float(max(0.0, -sd.min())) * 1000, 1),
                     "short": int((sd < thickness + 0.003).sum())}
    return out


#: The pinned shoulder strip reaches this far in front of / behind the neck opening: farther, the front and back
#: of a yoke built 1 cm off the chest would be held there as a step (seen A142, first run).
PIN_DEPTH_M = 0.025


def bodice_pins(obj, bod, ncx, ncy):
    """Ruling A142 pin rule (spike A135): the collar and the shoulder line — the yoke (vertex group "cap") and the top
    ``pin_band_m`` of the piece within ``pin_half_x`` of the neck, the torso rows front to back only across the
    shoulder (``PIN_DEPTH_M``), plus the rim of the
    neck opening down to the neckline's depth (an unpinned neckline sags into a deep scoop: seen A142). The sleeves
    and the rest of the body hang free."""
    co = np.array([v.co for v in obj.data.vertices])
    top = co[:, 2].max()
    cap = _group_mask(obj, "cap")
    rib = _group_mask(obj, "rib")
    # the yoke lying on the shoulders is pinned whole within pin_half_x; the torso rows only across the shoulder
    strip = (np.abs(co[:, 0] - ncx) < bod["pin_half_x"]) & (
        cap | ((co[:, 2] > top - bod["pin_band_m"]) & (np.abs(co[:, 1] - ncy) < bod["neck_r"] + PIN_DEPTH_M)))
    rim = np.zeros(len(co), bool)
    rim[gd.boundary_verts(obj)] = True
    reach = bod["neck_r"] + 0.04
    near_neck = (np.hypot(co[:, 0] - ncx, co[:, 1] - ncy) < reach + float(bod.get("depth_m") or 0.0)) \
        & (co[:, 2] > top - float(bod.get("depth_m") or 0.0) - 0.08)
    return np.where(strip | rib | (rim & near_neck))[0]


def _group_mask(obj, name):
    out = np.zeros(len(obj.data.vertices), bool)
    g = obj.vertex_groups.get(name)
    if g is not None:
        for v in obj.data.vertices:
            if any(ge.group == g.index for ge in v.groups):
                out[v.index] = True
    return out


#: Ruling A144 neckline metric: the rim loop resampled to NECK_SAMPLES points by arc length, low-passed to its first
#: NECK_HARMONICS Fourier harmonics (a clean scoop / crew / V is smooth at that scale; a staircase or a flap is not).
NECK_SAMPLES = 128
NECK_HARMONICS = 6


def boundary_loops(obj, co):
    """The boundary loops of ``obj`` as ordered vertex index lists."""
    E = {}
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    for e in bm.edges:
        if e.is_boundary:
            a, b = e.verts[0].index, e.verts[1].index
            E.setdefault(a, []).append(b)
            E.setdefault(b, []).append(a)
    bm.free()
    seen, loops = set(), []
    for start in E:
        if start in seen:
            continue
        loop, prev, cur = [start], None, start
        seen.add(start)
        while True:
            nxt = [n for n in E[cur] if n != prev and n not in seen]
            if not nxt:
                break
            prev, cur = cur, nxt[0]
            seen.add(cur)
            loop.append(cur)
        loops.append(loop)
    return loops


def neck_loop(obj, co, ncx, ncy):
    """The neckline: the boundary loop closest to the neck axis at the top (vertex indices in loop order)."""
    loops = [lp for lp in boundary_loops(obj, co) if len(lp) >= 8]
    if not loops:
        return []
    top = co[:, 2].max()

    def score(lp):
        p = co[lp]
        return float(np.hypot(p[:, 0].mean() - ncx, p[:, 1].mean() - ncy)) + 2.0 * float(top - p[:, 2].max())
    return min(loops, key=score)


def neck_metrics(p):
    """Waviness of a neckline loop (``p`` = its points in loop order): ``max_dev_mm`` / ``rms_dev_mm`` from its
    low-passed curve, ``z_turns`` (sign changes of the height along the loop beyond 1.5 mm steps: 2 for a clean
    neckline that is high at the back and low at the front), ``drop_mm`` (front-to-back height of the smooth curve)."""
    if len(p) < 8:
        return {}
    closed = np.vstack([p, p[:1]])
    s = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(closed, axis=0), axis=1))]
    t = np.linspace(0, s[-1], NECK_SAMPLES, endpoint=False)
    q = np.c_[[np.interp(t, s, closed[:, k]) for k in range(3)]].T
    F = np.fft.rfft(q, axis=0)
    F[NECK_HARMONICS + 1:] = 0
    lp_q = np.fft.irfft(F, n=NECK_SAMPLES, axis=0)
    dev = np.linalg.norm(q - lp_q, axis=1)
    dz = np.diff(np.r_[lp_q[:, 2], lp_q[:1, 2]])
    raw_dz = np.diff(np.r_[q[:, 2], q[:1, 2]])
    sg = np.sign(raw_dz[np.abs(raw_dz) > 0.0015])
    turns = int((sg != np.roll(sg, 1)).sum()) if len(sg) else 0
    return {"max_dev_mm": round(float(dev.max() * 1000), 1), "rms_dev_mm": round(float(np.sqrt((dev ** 2).mean()) * 1000), 2),
            "z_turns": turns, "loop_verts": len(p), "length_m": round(float(s[-1]), 3),
            "drop_mm": round(float((lp_q[:, 2].max() - lp_q[:, 2].min()) * 1000), 1)}


def split_slit(obj, angles, slit, hem_z, centre, centre_of=None):
    """Split the vertical edges at the slit's angle from the hem up to ``depth_m``. ``centre_of`` (``centre_at``):
    the angle of a vertex is taken round the centre its row was built round (None: ``centre``)."""
    side, depth = slit.get("side"), float(slit.get("depth_m") or 0)
    if side not in SLIT_ANGLE or depth <= 0:
        return 0
    target = SLIT_ANGLE[side]
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.verts.ensure_lookup_table()

    def ang_of(v):
        cen = centre_of(v.co.z) if centre_of else centre
        a = math.atan2(v.co.y - cen[1], v.co.x - cen[0]) % (2 * math.pi)
        d = abs(a - target)
        return min(d, 2 * math.pi - d)
    step = 2 * math.pi / 80
    cut = [e for e in bm.edges
           if all(ang_of(v) < step * 0.5 for v in e.verts)
           and max(v.co.z for v in e.verts) <= hem_z + depth + 1e-4
           and abs(e.verts[0].co.z - e.verts[1].co.z) > 1e-4]
    if cut:
        bmesh.ops.split_edges(bm, edges=cut)
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    return len(cut)


#: Ruling A141 — pose-space corrective shapes. The skinned drape is right only near the pose it was
#: draped in; a pose that bends the legs far (sit, kneel) lifts the hem off like a plate. Each pose of
#: ``SHAPE_POSES`` is draped again (cloth, starting from the skinned drape in that pose, against the
#: posed body + a floor, and a seat for sit), the result taken back through the inverse skinning into
#: the bind pose and stored as a morph target. ``ANCHOR_POSES`` are samples WITHOUT a shape (the
#: skinned drape is kept there). The renderers blend the targets by the leg directions
#: (``driver_features`` / ``blend``; the same rule in ``packages/scene-render/src/poseShapes.ts``).
SHAPE_POSES = ("sit", "kneel")
ANCHOR_POSES = ("rest", "walk")
#: The driver: four leg segments (joint head to joint head), thighs first.
DRIVER_SEGMENTS = (("LeftUpLeg", "LeftLeg"), ("RightUpLeg", "RightLeg"),
                   ("LeftLeg", "LeftFoot"), ("RightLeg", "RightFoot"))
#: Gaussian width of the sample blend (radians of summed segment angle).
DRIVER_SIGMA = 0.5
SHAPE_FRAMES = 40
#: Weight inpainting: a cloth vertex within NEAR_M of the body keeps its transferred weights, beyond
#: FAR_M it takes the weights diffused from its neighbours (linear in between).
NEAR_M = 0.02
FAR_M = 0.05
SMOOTH_ITER = 600
#: A hem vertex higher than its upward neighbour by more than this is flipped up.
HEM_UP_M = 0.005
#: A hem vertex stands off like a plate when the cloth runs into it less than PLATE_DEG below the
#: horizontal while it is more than PLATE_OFF_M from the body (nothing holds it up there).
PLATE_DEG = 30.0
PLATE_OFF_M = 0.03
#: The corrective drapes use at least this bending (a settle from the skinned pose crumples a soft
#: fabric into folds a static shape cannot carry well).
SHAPE_MIN_BENDING = 0.5
#: A corrective drape that moved its cloth this far at p90 exploded (good ones move 6–32 mm, A141/A142): the shape is
#: dropped (the skinned drape stays in that pose) and the drop is recorded.
SHAPE_MAX_MOVE_P90_MM = 100.0
#: Ruling A144 wall budget: the collider keeps only the faces within CROP_M of the cloth's box (a top never meets the
#: shins or the head); a corrective drape collides at SHAPE_COLLISION_QUALITY.
CROP_M = 0.12
SHAPE_COLLISION_QUALITY = 4


def to_gltf(v):
    """Blender Z-up world -> glTF Y-up model axes."""
    return (float(v[0]), float(v[2]), float(-v[1]))


def driver_features(arm, segments=DRIVER_SEGMENTS, frame="Hips"):
    """The segment directions (joint head to joint head) with the ``frame`` joint's rotation since rest taken out,
    glTF axes."""
    P = gd.P
    hb = arm.pose.bones[P + frame]
    rot = ((arm.matrix_world @ hb.matrix).to_3x3().normalized()
           @ (arm.matrix_world @ hb.bone.matrix_local).to_3x3().normalized().inverted())
    inv = rot.inverted()
    out = []
    for a, b in segments:
        ha = arm.matrix_world @ arm.pose.bones[P + a].head
        hb2 = arm.matrix_world @ arm.pose.bones[P + b].head
        d = inv @ (hb2 - ha)
        d.normalize()
        out.append([round(x, 5) for x in to_gltf(d)])
    return out


def mirror_features(f):
    """The pose mirrored left <-> right (glTF x negated, the sides swapped)."""
    m = [[-x, y, z] for x, y, z in f]
    return [m[1], m[0], m[3], m[2]]


def blend(features, samples, sigma=DRIVER_SIGMA):
    """``{target: influence}``: normalised Gaussian weights of the samples by the summed squared
    segment angles; a target's influence = the share of its samples (anchors carry none)."""
    g = []
    for s in samples:
        d2 = 0.0
        for u, v in zip(features, s["dirs"]):
            c = max(-1.0, min(1.0, sum(a * b for a, b in zip(u, v))))
            d2 += math.acos(c) ** 2
        g.append(math.exp(-d2 / (2 * sigma * sigma)))
    total = sum(g) or 1.0
    out = {}
    for s, w in zip(samples, g):
        if s.get("target"):
            out[s["target"]] = out.get(s["target"], 0.0) + w / total
    return out


def weight_matrix(obj):
    names = [g.name for g in obj.vertex_groups]
    W = np.zeros((len(obj.data.vertices), len(names)))
    for v in obj.data.vertices:
        for ge in v.groups:
            W[v.index, ge.group] = ge.weight
    return names, W


def write_weights(obj, W):
    for j, g in enumerate(obj.vertex_groups):
        g.remove(list(range(len(obj.data.vertices))))
        idx = np.where(W[:, j] > 0)[0]
        for i in idx:
            g.add([int(i)], float(W[i, j]), "REPLACE")


def smooth_weights(obj, body):
    """Inpaint the bone weights of the cloth that hangs free (robust weight transfer): vertices near
    the body keep the nearest-face weights, the rest take weights diffused over the mesh (Jacobi,
    the near ones fixed). Between the legs a skirt no longer jumps from one thigh to the other.
    Returns ``{fixed_share, free_share}``."""
    names, W = weight_matrix(obj)
    used = np.where(W.max(0) > 0)[0]
    Wu = W[:, used]
    n = len(Wu)
    bco, _bn, btri = gd.world_coords(body)
    tree = gd.bvh_of(bco, btri)
    co = np.array([obj.matrix_world @ v.co for v in obj.data.vertices])
    d = np.array([(tree.find_nearest(Vector(c))[3] or 1.0) for c in co])
    conf = np.clip((FAR_M - d) / (FAR_M - NEAR_M), 0.0, 1.0)
    fixed = conf >= 0.999
    E = gd.edges_of(obj)
    deg = np.bincount(E.ravel(), minlength=n).astype(float)
    S = Wu.copy()
    if fixed.any():
        for _ in range(SMOOTH_ITER):
            acc = np.zeros_like(S)
            np.add.at(acc, E[:, 0], S[E[:, 1]])
            np.add.at(acc, E[:, 1], S[E[:, 0]])
            S = np.where(fixed[:, None], Wu, acc / np.maximum(deg, 1.0)[:, None])
    out = conf[:, None] * Wu + (1 - conf[:, None]) * S
    # four strongest, normalised
    order = np.argsort(-out, axis=1)[:, 4:]
    np.put_along_axis(out, order, 0.0, axis=1)
    out /= np.maximum(out.sum(1, keepdims=True), 1e-9)
    W2 = np.zeros_like(W)
    W2[:, used] = out
    write_weights(obj, W2)
    return {"fixed_share": round(float(fixed.mean()), 4), "free_share": round(float((conf <= 0).mean()), 4)}


#: Ruling A144 layering: a piece's vertex within LAYER_NEAR_M of a lower layer takes that layer's bone weights
#: (linear to its own weights at LAYER_FAR_M), so the two layers deform alike and the lower one cannot slide out
#: through the upper one in a skinned pose (the body's weights at 3–4 cm from the skin had diffused differently).
LAYER_NEAR_M = 0.025
LAYER_FAR_M = 0.05


def layer_weights(obj, lower):
    """Blend ``obj``'s weights towards the nearest lower-layer vertex's (see LAYER_NEAR_M); returns the share taken."""
    from mathutils.kdtree import KDTree
    names, W = weight_matrix(obj)
    col = {n: j for j, n in enumerate(names)}
    co = np.array([obj.matrix_world @ v.co for v in obj.data.vertices])
    best_d = np.full(len(co), np.inf)
    best_w = np.zeros_like(W)
    for lo in lower:
        lco, _ln, _lt = gd.world_coords(lo)
        lnames, LW = weight_matrix(lo)
        LW2 = np.zeros((len(LW), W.shape[1]))
        for j, n in enumerate(lnames):
            if n in col:
                LW2[:, col[n]] = LW[:len(LW), j]
        kd = KDTree(len(lco))
        for i, p in enumerate(lco[:len(LW)]):
            kd.insert(Vector(p), i)
        kd.balance()
        for i, p in enumerate(co):
            _q, k, d = kd.find(Vector(p))
            if k is not None and d < best_d[i]:
                best_d[i], best_w[i] = d, LW2[k]
    conf = np.clip((LAYER_FAR_M - best_d) / (LAYER_FAR_M - LAYER_NEAR_M), 0.0, 1.0)
    conf[best_w.sum(1) <= 0] = 0.0
    out = conf[:, None] * best_w + (1 - conf[:, None]) * W
    order = np.argsort(-out, axis=1)[:, 4:]
    np.put_along_axis(out, order, 0.0, axis=1)
    out /= np.maximum(out.sum(1, keepdims=True), 1e-9)
    write_weights(obj, out)
    return {"taken_share": round(float((conf >= 0.999).mean()), 4), "blend_share": round(float((conf > 0).mean()), 4)}


def hem_sets(obj, top_z):
    """Hem vertices (boundary, not the waistband) and, per hem vertex, its upward neighbour."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    hem, up = [], []
    for v in bm.verts:
        if v.co.z > top_z - 0.03 or not any(e.is_boundary for e in v.link_edges):
            continue
        best = max((e.other_vert(v) for e in v.link_edges), key=lambda o: o.co.z)
        if best.co.z > v.co.z + 0.002:
            hem.append(v.index)
            up.append(best.index)
    bm.free()
    return np.array(hem, int), np.array(up, int)


def hem_metrics(obj, body, hem, up):
    """The hem in the current pose: ``hem_plate_share`` (see PLATE_DEG), ``hem_up_share`` = hem vertices above their upward neighbour
    by > HEM_UP_M (the cloth climbs to the hem = flipped up), ``hem_lift_p90_mm`` = that rise,
    ``hem_standoff_mm`` = median distance of the hem from the body surface."""
    if not len(hem):
        return {}
    gco, _gn, _gt = gd.world_coords(obj)
    bco, _bn, btri = gd.world_coords(body)
    tree = gd.bvh_of(bco, btri)
    rise = gco[hem, 2] - gco[up, 2]
    dist = np.array([tree.find_nearest(Vector(gco[i]))[3] or 0.0 for i in hem])
    seg = gco[hem] - gco[up]
    descent = np.degrees(np.arcsin(np.clip(-seg[:, 2] / np.maximum(np.linalg.norm(seg, axis=1), 1e-9), -1, 1)))
    plate = (descent < PLATE_DEG) & (dist > PLATE_OFF_M)
    return {"hem_plate_share": round(float(plate.mean()), 4),
            "hem_up_share": round(float((rise > HEM_UP_M).mean()), 4),
            "hem_lift_p90_mm": round(float(max(0.0, np.percentile(rise, 90)) * 1000), 1),
            "hem_standoff_mm": round(float(np.median(dist) * 1000), 1)}


def skin_matrices(arm, names):
    amw = arm.matrix_world
    inv = amw.inverted()
    M = np.zeros((len(names), 4, 4))
    for j, nm in enumerate(names):
        pb = arm.pose.bones.get(nm)
        M[j] = np.eye(4) if pb is None else np.array(amw @ pb.matrix @ pb.bone.matrix_local.inverted() @ inv)
    return M


def _box(name, lo, hi):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co = Vector([lo[k] + (v.co[k] + 0.5) * (hi[k] - lo[k]) for k in range(3)])
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    ob.modifiers.new("col", "COLLISION")
    ob.collision.thickness_outer = 0.004
    ob.collision.cloth_friction = 5.0
    return ob


def supports(arm, body, pose):
    """What the pose rests on: the floor under the body's lowest point; for sit a seat under the
    thighs from the knee pits back."""
    bco, _bn, _bt = gd.world_coords(body)
    lo = bco.min(0)
    hi = bco.max(0)
    out = [_box("floor", (lo[0] - 1, lo[1] - 1, lo[2] - 0.1), (hi[0] + 1, hi[1] + 1, lo[2] - 0.002))]
    if pose == "sit":
        names = [gd.P + n for n in ("Hips", "LeftUpLeg", "RightUpLeg")]
        idx = set()
        for nm in names:
            g = body.vertex_groups.get(nm)
            if g is None:
                continue
            for v in body.data.vertices:
                for ge in v.groups:
                    if ge.group == g.index and ge.weight > 0.5:
                        idx.add(v.index)
        if idx:
            pts = bco[sorted(idx)]
            knee_y = max((arm.matrix_world @ arm.pose.bones[gd.P + s + "Leg"].head).y for s in ("Left", "Right"))
            top = float(pts[:, 2].min()) - 0.002
            out.append(_box("seat", (pts[:, 0].min() - 0.08, knee_y + 0.06, top - 0.05),
                            (pts[:, 0].max() + 0.08, pts[:, 1].max() + 0.25, top)))
    return out


def pose_shape(arm, body, obj, pose, pin, names, W, rest_world, fab, thickness, lower=(), frames=SHAPE_FRAMES,
               collider=None):
    """The corrective of one pose, as world-space deltas at the bind pose (n x 3) + its numbers."""
    gd.set_pose(arm, pose)
    for lo in lower:
        apply_shapes(lo, arm)
    M = skin_matrices(arm, names)
    Mv = np.einsum("ng,gij->nij", W, M)
    ph = np.c_[rest_world, np.ones(len(rest_world))]
    skinned = np.einsum("nij,nj->ni", Mv, ph)[:, :3]
    ev, _n, _t = gd.world_coords(obj)
    skin_err = float(np.abs(ev[:len(skinned)] - skinned).max() * 1000)
    me = bpy.data.meshes.new("pose_" + pose)
    me.from_pydata(skinned.tolist(), [], [tuple(p.vertices) for p in obj.data.polygons])
    tmp = bpy.data.objects.new("pose_" + pose, me)
    bpy.context.scene.collection.objects.link(tmp)
    held = supports(arm, body, pose)
    cpu, wall, drift = gd.drape(tmp, body, pin, frames, quality=int(fab["quality"]),
                                bending=max(float(fab["bending"]), SHAPE_MIN_BENDING),
                                shrink=float(fab.get("shrink", 0.0)), self_collision=False, thickness=thickness,
                                extra=lower, crop_m=CROP_M, collision_quality=SHAPE_COLLISION_QUALITY,
                                prebuilt=collider,
                                mass=float(fab.get("cloth_mass", 0.3)), air_damping=float(fab.get("air_damping", 5.0)),
                                **gd.spring_kwargs(fab))
    draped = np.array([tmp.matrix_world @ v.co for v in tmp.data.vertices])
    for o in [tmp, *held]:
        bpy.data.objects.remove(o)
    back = np.einsum("nij,nj->ni", np.linalg.inv(Mv), np.c_[draped, np.ones(len(draped))])[:, :3]
    delta = back - rest_world
    moved = np.linalg.norm(draped - skinned, axis=1)
    return delta, {"cpu_s": cpu, "wall_s": wall, "pin_drift_mm": drift, "skin_err_mm": round(skin_err, 3),
                   "moved_p90_mm": round(float(np.percentile(moved, 90) * 1000), 1),
                   "moved_max_mm": round(float(moved.max() * 1000), 1)}


def export_glb(path, objs):
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.ops.export_scene.gltf(filepath=str(path), use_selection=True, export_skins=True, export_morph=True,
                              export_morph_normal=False, export_animations=False)


def blend_groups(arm, groups):
    """``{target: influence}`` over every pose-shape group (each blended by its own segments and frame)."""
    out = {}
    for g in groups:
        out.update(blend(driver_features(arm, g["segments"], g["frame"]), g["samples"], g["sigma"]))
    return out


def apply_shapes(obj, arm):
    """Set a lower layer's shape-key values for the armature's current pose (its own payload, Ruling A142)."""
    payload = obj.get("pose_shapes_json")
    keys = obj.data.shape_keys
    if not payload or keys is None:
        return
    import json
    inf = blend_groups(arm, json.loads(payload).get("groups") or [])
    for kb in keys.key_blocks[1:]:
        kb.value = float(inf.get(kb.name, 0.0))
    bpy.context.view_layer.update()


#: A237: a lower layer under a fitted piece is clipped this far above the piece's top edge.
CLIP_OVER_M = 0.02
#: A237: ... where it stands farther than this from the skin (a loose top); a close layer (briefs under tights) stays
#: a collider the piece lies over.
CLIP_LOOSE_M = 0.012


def _squeeze_under(lower, fitted, btree):
    """A237 — a layer under a fitted piece (a top tucked into trousers, briefs under tights) is CLIPPED at the
    piece's top edge (+ ``CLIP_OVER_M``): its faces below are removed from the collider and the measured layer. A
    loose layer is a shell round air — the piece's vertices between it and the skin counted as outside the collider
    and stood inside the layer (Kai tucked: layer poke 35 %, stretch 6.5), and pressing the layer onto the skin made
    the collider fold into itself (Kira: the cloth run exploded). What the piece covers of the layer is hidden at the
    assembly anyway (``garment_assembly._hide_under_upper``); the layer's own drape keeps its shape. Returns the
    count of removed vertices. Only a LOOSE layer is clipped (its median gap to the skin below the edge farther than
    ``CLIP_LOOSE_M``, ``btree``): a close layer — briefs under tights — stays a collider the piece is laid out over."""
    if not fitted or fitted.get("top_y") is None:
        return 0
    top = gf._gltf_y(fitted["top_y"]) + CLIP_OVER_M
    n = 0
    for lo in lower:
        if lo.get("footwear"):                  # a boot is rigid: the leg goes over it or into it, never clips it
            continue
        mw = lo.matrix_world
        bm = bmesh.new()
        bm.from_mesh(lo.data)
        below = [v for v in bm.verts if (mw @ v.co).z < top]
        gap = [btree.find_nearest(mw @ v.co)[3] for v in below]
        gap = [g for g in gap if g is not None]
        # the whole part below goes when the layer stands loose there (median gap): a ragged clip of only the loose
        # vertices left islands of the top in the collider (Kai: stretch 8.0 at the band)
        gone = below if gap and float(np.median(gap)) > CLIP_LOOSE_M else []
        n += len(gone)
        bmesh.ops.delete(bm, geom=gone, context="VERTS")
        bm.to_mesh(lo.data)
        bm.free()
        lo.data.update()
    return n


def _boot_hulls(obj):
    """A237 — a boot collider is the convex hull of each side (foot + shaft): the fit is an open shell (the collar,
    a pull tab, laces), and a leg hanging over it caught on the back of the collar (Lirien straight leg: 25 edges at
    0.15-0.17 m, stretch 25.95). The hull is closed and has no thin parts; the vertices it keeps keep their weights."""
    mw = obj.matrix_world
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    keep, hull_faces = set(), set()
    for sd in (1, -1):
        side = [v for v in bm.verts if (mw @ v.co).x * sd > 0]
        if len(side) < 4:
            continue
        res = bmesh.ops.convex_hull(bm, input=side, use_existing_faces=False)
        keep |= {v for v in res["geom"] if isinstance(v, bmesh.types.BMVert)}
        hull_faces |= {f for f in res["geom"] if isinstance(f, bmesh.types.BMFace)}
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if f not in hull_faces], context="FACES_ONLY")
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if v not in keep], context="VERTS")
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()


def load_lower(path, arm, payload):
    """Import a lower drape GLB (Ruling A142 layering) or an own-mesh piece's fit GLB (A200) and skin its garment to
    OUR armature (same bone names)."""
    import json
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(path))
    new = [o for o in bpy.data.objects if o not in before]
    meshes = [o for o in new if o.type == "MESH"]
    # A200: an own-mesh piece's fit GLB carries the rigged body too — its garment node is the collider
    named = [o for o in meshes if o.name.startswith("garment_")]
    garment = max(named or meshes, key=lambda o: len(o.data.vertices))
    shoe = [o for o in named if o.name.startswith("garment_footwear_")]
    if len(shoe) > 1:
        # A237: a boot's fit is one node per side and part (foot, shaft) — the collider is all of them
        with bpy.context.temp_override(active_object=garment, selected_editable_objects=shoe):
            bpy.ops.object.join()
        new = [o for o in bpy.data.objects if o not in before]     # the joined nodes are gone
    if shoe:
        _boot_hulls(garment)
    mw = garment.matrix_world.copy()
    garment.parent = arm
    garment.matrix_world = mw
    for m in garment.modifiers:
        if m.type == "ARMATURE":
            m.object = arm
    for o in new:
        if o is not garment:
            bpy.data.objects.remove(o)
    garment.name = "lower_" + Path(path).stem
    garment["pose_shapes_json"] = json.dumps(payload or {})
    garment.hide_render = True
    garment["footwear"] = bool(shoe)
    return garment


def _set_arm_angle(arm, deg):
    """The arms lowered ``deg`` from the T-pose (the bake pose search)."""
    gd.POSES["_bake"] = [("LeftArm", "Y", deg), ("RightArm", "Y", -deg)]
    gd.set_pose(arm, "_bake")


#: Arm angles (degrees below the T-pose) tried for the projection of a bodice's views.
BAKE_ARM_DEG = (0, 20, 35, 50, 65, 80)


#: Bug round 2026-11-20: the arm angles tried for gloves — the T-pose and RAISED (negative): a picture of a pair of
#: gloves shows them upright, fingers up (the piece-only view asks for that, ``garment_template_views.prompt_for``),
#: i.e. the arms raised over the head. Raised and lowered are never searched together: hanging, a glove's silhouette
#: is the raised one upside down, and the IoU tells the two apart by a few hundredths only (Glut's gloves: 0.826
#: hanging, 0.817 raised), so the cuff of the picture would be painted onto the hand. The PICTURE decides instead
#: (review of the round): ``bake_register.fingers_end`` reads which end holds the fingers; a pair pictured fingers
#: down (an older or an uploaded view) searches GLOVE_ARM_DEG_DOWN, one it cannot read (fingerless) the upright set.
GLOVE_ARM_DEG = (0, -35, -65, -90)
GLOVE_ARM_DEG_DOWN = (0, 35, 65, 90)


def glove_arm_degs(front_alpha):
    """``(degs, fingers)``: the arm angles the gloves' pose search tries for this front view (row 0 = bottom) and the
    finger end read from it (``"up"`` / ``"down"`` / ``"unknown"``)."""
    fingers = br.fingers_end(front_alpha) or "unknown"
    return (GLOVE_ARM_DEG_DOWN if fingers == "down" else GLOVE_ARM_DEG), fingers


def bake_pose(arm, obj, views, degs=BAKE_ARM_DEG, polys=None, paired=False):
    """Ruling A142 — the arm angle whose posed front silhouette matches the front view best: an item picture shows a
    top with its sleeves hanging, a T-posed drape would project its sleeve pixels onto the torso. Bug round
    2026-11-20: the score is the REGISTERED silhouette IoU (``gd.silhouette_iou``: scale + offset searched, per part
    for a ``paired`` piece), no longer the IoU of both outlines stretched onto their own boxes; ``degs`` the angles
    tried (gloves: ``GLOVE_ARM_DEG``). ``views`` = ``gd.bake_views``. Returns ``(deg, co, nr, info)`` (world
    positions / normals in that pose)."""
    tri_v, _tl = gd._tri_layout(obj, polys)
    best, scores = None, {}
    for deg in degs:
        _set_arm_angle(arm, deg)
        co, nr, _t = gd.world_coords(obj)
        iou = gd.silhouette_iou(np.asarray(co, np.float64), np.asarray(nr, np.float64), tri_v, views,
                                paired=paired)
        scores[deg] = round(iou, 3)
        if best is None or iou > best[0]:
            best = (iou, deg, co, nr)
    gd.set_pose(arm, "rest")
    return best[1], best[2], best[3], {"pose_iou": scores}


def _part_counts(parts):
    """{part name: faces} of a list of ``uv_part`` ids (``uv_pattern.PARTS``)."""
    out = {}
    for p_ in parts:
        name = uvp.PARTS.get(int(p_), f"part{int(p_)}")
        out[name] = out.get(name, 0) + 1
    return out


def _int_layer(me, name, n):
    """The int attribute ``name`` of ``me`` as an (n,) array — zeros when the mesh has no such layer: a bodice without
    one marked cut (Lirien's strapped dress with a slit) wrote an all-zero ``uv_seam`` edge layer, and Blender's
    bmesh round trip in ``split_slit`` dropped it (plan group B, B23)."""
    out = np.zeros(n, np.int32)
    if name in me.attributes:
        me.attributes[name].data.foreach_get("value", out)
    return out


def _drop_layers(me, names):
    for name in names:
        if name in me.attributes:
            me.attributes.remove(me.attributes[name])


def pattern_uv_of(obj, arm, centre, pattern, islands_json, kind=None):
    """Pattern-piece UV of a bodice: read the faces, their ``uv_part`` / ``uv_seam`` /
    ``uv_cid`` layers and the rest coordinates as ``clear_of_body`` (and a slit) left them, run
    ``uv_pattern.pattern_uv`` (panels flattened, the band a construction strip, every island at one px/cm), write the
    ``UVMap`` loops and ``islands_json`` (the payload; no PNG), drop the helper layers. Returns ``data["uv"]``.

    Axes (``orient``): front / back +Z up round the vertical line through ``centre``; a sleeve up from the hand to the
    shoulder round the arm line A -> H of its Arm / Hand bones. The construction ids of ``pattern`` (band rows, cut
    edges, cap vertices) are mapped through ``uv_cid``; a vertex ``dissolve_degenerate`` merged away maps to -1.

    Step 3c / 3d (``kind`` "jacket" / "dress"): the kind's rows (``uv_pattern.ROWS`` / ``ROWS_ALT``), the skirt part
    and an open front's fronts flattened round the same vertical line, a stand collar's rows as a relaxed strip
    (``bands``), and the placket lines (``pattern["marks"]``) written to ``marks.json`` beside ``islands_json`` —
    ``{"version", "atlas_px", "px_per_cm", "lines": {line: {"island", "px"}}}`` (never part of the islands' bytes).
    Phases E + F: a top the same way (its rows stay ``ROW_ORDER``: ``ROWS`` has no "top"). A strip row whose vertex
    ``dissolve_degenerate`` merged away takes its nearest surviving neighbour (``m_row``)."""
    import json
    t0 = time.time()
    me = obj.data
    nv = len(me.vertices)
    co = np.empty(nv * 3)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    polys = [tuple(p_.vertices) for p_ in me.polygons]
    part = np.empty(len(me.polygons), np.int32)
    me.attributes["uv_part"].data.foreach_get("value", part)
    cid = np.empty(nv, np.int32)
    me.attributes["uv_cid"].data.foreach_get("value", cid)
    flag = _int_layer(me, "uv_seam", len(me.edges))
    ev = np.empty(len(me.edges) * 2, np.int32)
    me.edges.foreach_get("vertices", ev)
    ev = ev.reshape(-1, 2)
    seams = {(int(a_), int(b_)) for (a_, b_), f_ in zip(ev, flag) if f_}
    cmap = {int(c): i for i, c in enumerate(cid)}

    def m(ids):
        return [cmap.get(int(c), -1) for c in ids]

    def m_row(ids):
        """A strip row mapped like ``m``; a vertex ``dissolve_degenerate`` merged away (its edge was under
        ``MIN_EDGE_M``: it now lies on its neighbour) takes the nearest surviving neighbour in the row (phase F: one
        merged rim vertex on Tilda's neck sent the whole collar to the panel flattening, and a band row's -1 read the
        last vertex of the mesh)."""
        got = m(ids)
        alive = [k for k, g in enumerate(got) if g >= 0]
        if not alive:
            return got
        return [g if g >= 0 else got[min(alive, key=lambda j: (abs(j - k), j))] for k, g in enumerate(got)]
    axes = {1: ((0.0, 0.0, 1.0), (float(centre[0]), float(centre[1]), 0.0), None),
            2: ((0.0, 0.0, 1.0), (float(centre[0]), float(centre[1]), 0.0), None)}
    panel_kind = kind in ("jacket", "dress", "top")
    if panel_kind:
        for p_ in (37, 38, 39, 40):
            axes[p_] = axes[1]
    caps = {}
    for side, part_id, names in (("l", 3, ("LeftArm", "LeftHand")), ("r", 4, ("RightArm", "RightHand"))):
        A, H = (np.asarray(_bone_world(arm, n), float) for n in names)
        axes[part_id] = (tuple(A - H), tuple(A), tuple(H - A))
        if side in pattern["uv_caps"]:
            loop, sh, ua = pattern["uv_caps"][side]
            caps[part_id] = ([g for g in m(loop) if g >= 0], cmap.get(sh, -1), cmap.get(ua, -1))
    strips = {5: [(m_row if panel_kind else m)(r_) for r_ in pattern["band_strip"]]} if pattern["band_strip"] else {}
    if panel_kind:
        bands = {}
        if strips:
            # B24: a jacket's / dress's neckband is relaxed from its strip like the waistband (the bare one-row strip
            # stretched 1.57 round Vallerie's crew neck); ``rows_strip_uv`` wants the rows top (the neck edge) first
            bands[5] = strips.pop(5)[::-1]
        if pattern.get("collar_rows"):
            rows6 = [m_row(r_) for r_ in pattern["collar_rows"]]
            if all(g >= 0 for r_ in rows6 for g in r_):
                bands[6] = rows6
            else:
                print("uv.collar a collar vertex was merged away: the collar is flattened as a panel", flush=True)
        marks = {k: (int(p_), [g for g in m(ids) if g >= 0]) for k, (p_, ids) in (pattern.get("marks") or {}).items()}
        res = uvp.pattern_uv(polys, part, seams, co, axes=axes, strips=strips, caps=caps, size_px=PATTERN_ATLAS_PX,
                             margin_cm=PATTERN_MARGIN_CM, rows=uvp.ROWS.get(kind), rows_alt=uvp.ROWS_ALT.get(kind),
                             bands=bands, marks=marks)
    else:
        res = uvp.pattern_uv(polys, part, seams, co, axes=axes, strips=strips, caps=caps, size_px=PATTERN_ATLAS_PX,
                             margin_cm=PATTERN_MARGIN_CM)
    # the shoulder seam: the yoke ("cap" group) vertices shared by front and back. It runs the yoke meridian of the
    # side column from the top of the armhole to the neck ring's side point (the high point of the shoulder); a neck
    # standing in front of the torso centre takes its neck end that far forward (``uv_pattern.shoulder_seam``)
    fr = {v for p_, f in zip(part, polys) if p_ in (1, 39, 40) for v in f}
    bk = {v for p_, f in zip(part, polys) if p_ == 2 for v in f}
    gi = obj.vertex_groups["cap"].index if "cap" in obj.vertex_groups else None
    yoke = {v.index for v in me.vertices if any(g.group == gi for g in v.groups)} if gi is not None else set()
    shared = sorted(fr & bk & yoke)
    seam = uvp.shoulder_seam(co, shared, centre, m(pattern["band_strip"][0]) if pattern["band_strip"] else None)
    flat = np.zeros(len(me.loops) * 2)
    for p_ in me.polygons:
        for j, li in enumerate(p_.loop_indices):
            flat[2 * li:2 * li + 2] = res["corner_uv"][p_.index][j]
    me.uv_layers["UVMap"].data.foreach_set("uv", flat)
    _drop_layers(me, ("uv_part", "uv_seam", "uv_cid"))
    Path(islands_json).write_text(json.dumps(res["payload"], sort_keys=True, separators=(",", ":")))
    if res.get("marks"):
        Path(islands_json).with_name("marks.json").write_text(json.dumps(
            {"version": 1, "atlas_px": res["payload"]["atlas_px"], "px_per_cm": res["payload"]["px_per_cm"],
             "lines": res["marks"]}, sort_keys=True, separators=(",", ":")))
    info = {"mode": "pattern", "px_per_cm": res["payload"]["px_per_cm"], "atlas_px": res["payload"]["atlas_px"],
            "islands": res["islands"], "faces_per_part": res["faces_per_part"],
            "area_ratio_min": res["area_ratio_min"], "area_ratio_max": res["area_ratio_max"],
            "stretch_p95_max": res["stretch_p95_max"], "strip_stretch_p95": res["strip_stretch_p95"],
            "strip_area_ratio": {i["name"]: i["distortion"]["area_ratio"] for i in res["payload"]["islands"]
                                 if i["part"] in uvp.STRIP_PARTS},
            "marks": sorted(res.get("marks") or {}),
            "cap_height_cm": {n: res["cap_height_cm"].get(n) for n in ("sleeve_l", "sleeve_r")},
            "seam_edges": len(seams),
            "shoulder_seam_dy_cm": max((v["max_dy_cm"] for v in seam.values()), default=None),
            "shoulder_seam": seam,
            "uv_s": round(time.time() - t0, 2)}
    print(f"uv.islands {res['islands']} faces {res['faces_per_part']} px/cm {info['px_per_cm']} "
          f"area {info['area_ratio_min']}..{info['area_ratio_max']} p95 {info['stretch_p95_max']} "
          f"caps {info['cap_height_cm']} shoulder seam {seam} {info['uv_s']} s", flush=True)
    return info


#: Step 3a: the adaptive stop of ARAP on a fitted piece (4-41 k vertices; decision D12).
FITTED_ARAP_TOL = 1e-3


def pattern_uv_of_fitted(obj, pattern, islands_json):
    """Pattern-piece UV of a fitted piece (step 3a): read the faces, their ``uv_part`` / ``uv_seam`` layers
    (``garment_template_fitted._cut_pattern``) and the rest coordinates as ``clear_of_body`` left them, run
    ``uv_pattern.pattern_uv`` with the kind's axes, ring frames and rows (``fitted_pattern``; panels by LSCM + ARAP with
    the adaptive stop, rings as strips), write the ``UVMap`` loops and ``islands_json``, drop the helper layers.
    Returns ``data["uv"]``."""
    import json
    t0 = time.time()
    me = obj.data
    nv = len(me.vertices)
    co = np.empty(nv * 3)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    polys = [tuple(p_.vertices) for p_ in me.polygons]
    part = np.empty(len(me.polygons), np.int32)
    me.attributes["uv_part"].data.foreach_get("value", part)
    flag = _int_layer(me, "uv_seam", len(me.edges))
    ev = np.empty(len(me.edges) * 2, np.int32)
    me.edges.foreach_get("vertices", ev)
    ev = ev.reshape(-1, 2)
    seams = {(int(a_), int(b_)) for (a_, b_), f_ in zip(ev, flag) if f_}
    res = uvp.pattern_uv(polys, part, seams, co, axes=pattern["axes"], rings=pattern["rings"], rows=pattern["rows"],
                         size_px=PATTERN_ATLAS_PX, margin_cm=PATTERN_MARGIN_CM, tol=FITTED_ARAP_TOL)
    flat = np.zeros(len(me.loops) * 2)
    for p_ in me.polygons:
        for j, li in enumerate(p_.loop_indices):
            flat[2 * li:2 * li + 2] = res["corner_uv"][p_.index][j]
    me.uv_layers["UVMap"].data.foreach_set("uv", flat)
    _drop_layers(me, ("uv_part", "uv_seam"))
    Path(islands_json).write_text(json.dumps(res["payload"], sort_keys=True, separators=(",", ":")))
    info = {"mode": "pattern", "px_per_cm": res["payload"]["px_per_cm"], "atlas_px": res["payload"]["atlas_px"],
            "islands": res["islands"], "faces_per_part": res["faces_per_part"],
            "area_ratio_min": res["area_ratio_min"], "area_ratio_max": res["area_ratio_max"],
            "stretch_p95_max": res["stretch_p95_max"], "strip_stretch_p95": res["strip_stretch_p95"],
            "seam_edges": len(seams), "arap_iters": res["arap_iters"], "slivers": pattern.get("slivers", []),
            "opened": pattern.get("opened", []), "cut_edges": pattern.get("cut_edges"),
            "uv_s": round(time.time() - t0, 2)}
    print(f"uv.islands {res['islands']} faces {res['faces_per_part']} px/cm {info['px_per_cm']} "
          f"area {info['area_ratio_min']}..{info['area_ratio_max']} p95 {info['stretch_p95_max']} "
          f"strips {info['strip_stretch_p95']} iters {info['arap_iters']} slivers {info['slivers']} "
          f"opened {info['opened']} {info['uv_s']} s", flush=True)
    return info


def pattern_uv_of_wrap(obj, centre, top_z, rows_key, islands_json, band=None, marks=None):
    """Pattern-piece UV of a piece cut by ``wrap`` (step 3b, plan group B: a skirt, a strapless top, a strapless
    dress): read the faces, their ``uv_part`` / ``uv_seam`` layers (``uv_pattern.wrap_parts``, set before the side
    seams were merged) and the rest coordinates, run ``uv_pattern.pattern_uv`` — the panels flattened round the
    vertical line through ``centre`` (+Z up), the waistband a ring strip opened at the back centre (+Y) round the same
    line at ``top_z``, the layout ``ROWS[rows_key]``, ``ROWS_ALT[rows_key]`` or a nested one (``NEST[rows_key]``; the
    larger px/cm) — write the ``UVMap``
    loops and ``islands_json``, drop the helper layers. Returns ``data["uv"]``. ``band`` = the waistband's vertex rows
    as construction ids (``wrap_parts``): mapped through ``uv_cid`` (a side-seam vertex merged onto its twin takes the
    twin's id, ``_wrap_twin``) into a construction strip (``uv_pattern.rows_strip_uv``). Phase G: ``marks`` =
    {line: (part, construction ids top to bottom)} (a corset top's ``centre_back``) -> ``marks.json`` beside
    ``islands_json`` as ``pattern_uv_of`` writes it."""
    import json
    t0 = time.time()
    me = obj.data
    nv = len(me.vertices)
    co = np.empty(nv * 3)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    polys = [tuple(p_.vertices) for p_ in me.polygons]
    part = _int_layer(me, "uv_part", len(me.polygons))
    flag = _int_layer(me, "uv_seam", len(me.edges))
    cid = _int_layer(me, "uv_cid", nv)
    ev = np.empty(len(me.edges) * 2, np.int32)
    me.edges.foreach_get("vertices", ev)
    ev = ev.reshape(-1, 2)
    seams = {(int(a_), int(b_)) for (a_, b_), f_ in zip(ev, flag) if f_}
    cmap = {int(c): i for i, c in enumerate(cid)}
    bands = {}
    if band:
        bands[14] = [[cmap.get(int(c), cmap.get(_wrap_twin(int(c)), -1)) for c in row] for row in band]
        if any(g < 0 for row in bands[14] for g in row):
            raise RuntimeError("the waistband lost a vertex in the seam merge")
    cx, cy = float(centre[0]), float(centre[1])
    vertical = ((0.0, 0.0, 1.0), (cx, cy, 0.0), None)
    axes = {p_: vertical for p_ in (1, 2, 37, 38)}
    rings = {14: ((cx, cy, float(top_z)), (0.0, 0.0, 1.0), (0.0, 1.0, 0.0))}
    lines = {k: (int(p_), [g for g in (cmap.get(int(c), cmap.get(_wrap_twin(int(c)), -1)) for c in ids) if g >= 0])
             for k, (p_, ids) in (marks or {}).items()}
    res = uvp.pattern_uv(polys, part, seams, co, axes=axes, rings=rings, rows=uvp.ROWS.get(rows_key),
                         rows_alt=uvp.ROWS_ALT.get(rows_key), size_px=PATTERN_ATLAS_PX,
                         margin_cm=PATTERN_MARGIN_CM, tol=FITTED_ARAP_TOL, bands=bands,
                         nest=uvp.NEST.get(rows_key), marks=lines or None)
    flat = np.zeros(len(me.loops) * 2)
    for p_ in me.polygons:
        for j, li in enumerate(p_.loop_indices):
            flat[2 * li:2 * li + 2] = res["corner_uv"][p_.index][j]
    me.uv_layers["UVMap"].data.foreach_set("uv", flat)
    _drop_layers(me, ("uv_part", "uv_seam", "uv_cid"))
    Path(islands_json).write_text(json.dumps(res["payload"], sort_keys=True, separators=(",", ":")))
    if res.get("marks"):
        Path(islands_json).with_name("marks.json").write_text(json.dumps(
            {"version": 1, "atlas_px": res["payload"]["atlas_px"], "px_per_cm": res["payload"]["px_per_cm"],
             "lines": res["marks"]}, sort_keys=True, separators=(",", ":")))
    info = {"mode": "pattern", "px_per_cm": res["payload"]["px_per_cm"], "atlas_px": res["payload"]["atlas_px"],
            "islands": res["islands"], "faces_per_part": res["faces_per_part"],
            "area_ratio_min": res["area_ratio_min"], "area_ratio_max": res["area_ratio_max"],
            "stretch_p95_max": res["stretch_p95_max"], "strip_stretch_p95": res["strip_stretch_p95"],
            "strip_area_ratio": {i["name"]: i["distortion"]["area_ratio"] for i in res["payload"]["islands"]
                                 if i["part"] in uvp.STRIP_PARTS},
            "marks": sorted(res.get("marks") or {}),
            "seam_edges": len(seams), "arap_iters": res["arap_iters"], "rows": rows_key,
            "uv_s": round(time.time() - t0, 2)}
    print(f"uv.islands {res['islands']} faces {res['faces_per_part']} px/cm {info['px_per_cm']} "
          f"area {info['area_ratio_min']}..{info['area_ratio_max']} p95 {info['stretch_p95_max']} "
          f"strips {info['strip_stretch_p95']} {info['uv_s']} s", flush=True)
    return info


#: Step 3b: the atlas rows of a piece cut by ``wrap`` (``uv_pattern.ROWS`` key) per kind.
WRAP_ROWS = {"skirt": "skirt", "top": "strapless", "dress": "dress"}
_WRAP_GRID = {}


def _wrap_twin(cid):
    """The construction id of the side-seam twin of ``cid`` (``wrap``: the front's last column lies on the back's first,
    the back's last on the front's first), -1 for a vertex off the side seams. ``_WRAP_GRID`` = {rows, cols} of the
    current ``wrap``."""
    rows, cols = _WRAP_GRID["rows"], _WRAP_GRID["cols"]
    p, rem = divmod(cid, rows * cols)
    r, c = divmod(rem, cols)
    if c == cols - 1:
        return (1 - p) * rows * cols + r * cols
    if c == 0:
        return (1 - p) * rows * cols + r * cols + cols - 1
    return -1


def run(a):
    t_all, c_all = time.time(), time.process_time()
    inp, prm = a["inputs"], a["params"]
    out = Path(a["out_dir"])
    gd.PROGRESS["file"] = prm.get("progress_file") or None
    gd.progress(stage="setup", frame=None, frames=None, index=None, count=None, pose=None)
    arm, body, _g = gd.load_fit(inp["body"])
    spec = prm["spec"]
    bod = spec.get("bodice")
    lower = []
    offsets = list(prm.get("lower_offsets") or [])
    for i, payload in enumerate(prm.get("lower_shapes") or []):
        key = f"lower_{i}"
        if inp.get(key):
            lo = load_lower(inp[key], arm, payload)
            off = float(offsets[i]) if i < len(offsets) and offsets[i] else 0.0
            if off:
                # A200 fallback: an own-mesh collider shrunk toward the body (negative = inward, along its normals)
                lo.data.update()
                for v in lo.data.vertices:
                    v.co = v.co + v.normal * off
                lo.data.update()
            lower.append(lo)
    bco, _bn, btri = gd.world_coords(body)
    squeezed = _squeeze_under(lower, spec.get("fitted"), gd.bvh_of(bco, [tuple(t) for t in btri])) if lower else 0
    for lo in [lo for lo in lower if not len(lo.data.polygons)]:      # a layer clipped away whole is no collider
        lower.remove(lo)
        bpy.data.objects.remove(lo)
    # the radius tree is the torso + legs only: a T-posed arm beside the chest band would
    # otherwise be the "body" a ray from outside meets first (the band then spans the arms)
    half = float(prm.get("torso_half_m") or 0.24)
    tri = np.asarray(btri)
    keep = np.all(np.abs(bco[tri][..., 0]) < half, axis=1)
    tri_t = [tuple(t) for t in tri[keep]]
    co_all, tri_all = bco, [tuple(t) for t in tri]
    for lo in lower:                       # a jacket starts outside the top it is worn over
        lco, _ln, ltri = gd.world_coords(lo)
        off = len(co_all)
        co_all = np.vstack([co_all, lco])
        lt = np.asarray(ltri) + off
        tri_all += [tuple(t) for t in lt]
        tri_t += [tuple(t) for t in lt[np.all(np.abs(co_all[lt][..., 0]) < half, axis=1)]]
    btree = gd.bvh_of(co_all, tri_t)
    ftree = gd.bvh_of(co_all, tri_all)
    top_z = spec["row_y"][0]
    sl = bco[np.abs(bco[:, 2] - top_z) < 0.01]
    centre = sl[:, :2].mean(0) if len(sl) else bco[:, :2].mean(0)
    if (spec.get("outline") or {}).get("side_top_y") is not None:
        # corset v4: a strapless top whose front rises over the cups takes its axis from the torso's box at the edge
        # under the arms (``side_top_y``): its top row reached the T-posed arms, and the vertex mean of a slice through
        # the dense, lifted chest stood 12 cm in front of the spine (the rays from the axis then missed the body)
        tz = bco[(np.abs(bco[:, 2] - float(spec["outline"]["side_top_y"])) < 0.01) & (np.abs(bco[:, 0]) < half)]
        if len(tz):
            centre = (tz[:, :2].min(0) + tz[:, :2].max(0)) / 2.0
    fitted = spec.get("fitted")
    uv_info = None
    cut_only = bool(prm.get("cut_only"))
    if fitted:
        # A223: a close-fitting piece cut from the body's surface (``garment_template_fitted``)
        col, ctree = gd.rest_collider(body, extra=lower)
        # A237: the cut keeps collider faces by the body's bone weights and planes, so a layer in the collider gave
        # the piece its faces (a top under trousers: stretch 3307). A loose layer is clipped at the piece's top edge
        # (``_squeeze_under``); a boot is never cut into the leg — the piece is cut without it and only laid out over
        # it (``ctree``, body + every layer); the drape still meets them all. A close layer (briefs under tights)
        # stays in the cut: the piece is cut from its outside as before (cut from the body alone: stretch 1.42 vs 1.24)
        boots = [lo for lo in lower if lo.get("footwear")]
        cut = gd.rest_collider(body, extra=[lo for lo in lower if not lo.get("footwear")])[0] if boots else None
        obj, fit_pin, binfo = gf.build_fitted(prm, spec, arm, body, ctree, col=col, cut=cut,
                                               boots=boots)
        if squeezed:
            binfo["clipped_under_verts"] = squeezed
        if cut is not None:
            binfo["cut_from"] = "without footwear"
            bpy.data.objects.remove(cut)
        slit_edges = 0
        # step 3a: the fitted kinds' sewing-pattern islands, from the parts cut in ``build_fitted`` (the drape below
        # only moves vertices, so a ``cut_only`` run writes the same islands bytes)
        pattern = binfo.pop("pattern")
        uv_info = pattern_uv_of_fitted(obj, pattern, out / "islands.json")
        uv_info["planes"] = pattern["planes"]
        uv_info["parts_cut"] = pattern["faces_per_part"]
        if cut_only:
            return gd._plain({"cut_only": True, "uv": uv_info, "bodice": binfo, "slit_edges": 0,
                              "lower_layers": len(lower), "verts": len(obj.data.vertices),
                              "script_wall_s": round(time.time() - t_all, 2),
                              "script_cpu_s": round(time.process_time() - c_all, 2)}), \
                {"islands": str(out / "islands.json")}
    elif bod:
        # the torso axis of a bodice is the spine (the slice at the shoulder line holds the arms' roots)
        # A179: its Y is the arm joints' (the armhole windows open either side of the axis: an axis 3 cm in front of
        # the arms put the back border of each window 5 cm out on the upper arm)
        sp = _bone_world(arm, "Spine2")
        centre = np.array([sp[0], (_bone_world(arm, "LeftArm")[1] + _bone_world(arm, "RightArm")[1]) / 2])
        thickness = float(prm.get("thickness", 0.004))
        # stage "geometry": an outer layer over a sleeved one (``layer_ease``) meets the lower sleeves' hems ramped
        col, ctree = gd.rest_collider(body, extra=lower, hem_ramp=bool(spec.get("layer_ease")) and OUTER_SLEEVE_CLEAR)
        # phases E + F: a top is cut by the neck-ring rules only with a collar or a placket (``neck_rules``); without
        # them it takes the path from before the phases (kind None), its islands the same bytes
        bodice_kind = prm.get("kind") if prm.get("kind") != "top" or prm.get("neck_rules") else None
        row_c = leg_centres(bco[np.abs(bco[:, 0] - centre[0]) < half], centre, spec["row_y"],
                            lambda cen, r: bodice_radii(spec, btree, cen, r)) if prm.get("leg_centres") else None
        verts, faces, binfo = build_bodice(spec, btree, ftree, centre, arm, ctree=ctree,
                                           clear=thickness + gd.BUILD_CLEAR_EXTRA_M, kind=bodice_kind,
                                           waist_y=(spec.get("outline") or {}).get("waist_y"), row_c=row_c,
                                           straight_straps=bool(prm.get("straight_straps")))
        binfo["leg_shift_m"] = [round(float(c[1] - centre[1]), 3) for c in row_c] if row_c else None
        pattern = {k: binfo.pop(k) for k in ("face_part", "seam_edges", "band_strip", "uv_caps", "collar_rows",
                                             "marks")}
        binfo["inside"] = inside_report(ctree, verts, binfo.pop("regions"), thickness)
        me = bpy.data.meshes.new("template")
        me.from_pydata(verts, [], faces)
        me.uv_layers.new(name="UVMap")         # filled by ``pattern_uv_of`` below
        obj = bpy.data.objects.new(prm["node"], me)
        bpy.context.scene.collection.objects.link(obj)
        obj.vertex_groups.new(name="cap").add(binfo.pop("cap_ids"), 1.0, "REPLACE")
        obj.vertex_groups.new(name="rib").add(binfo.pop("rib_ids"), 1.0, "REPLACE")
        bm = bmesh.new()
        bm.from_mesh(me)
        # the pattern part per face, the cut edges and every vertex's construction id ride through the bmesh ops
        # as int layers (face / edge / vertex custom data survives on the surviving elements); never face indices
        lay_part = bm.faces.layers.int.new("uv_part")
        lay_seam = bm.edges.layers.int.new("uv_seam")
        lay_cid = bm.verts.layers.int.new("uv_cid")
        bm.verts.ensure_lookup_table()
        for f, fp in zip(bm.faces, pattern["face_part"]):
            f[lay_part] = int(fp)
        for v in bm.verts:
            v[lay_cid] = v.index
        for a_, b_ in pattern["seam_edges"]:
            e = bm.edges.get((bm.verts[a_], bm.verts[b_]))
            if e is not None:
                e[lay_seam] = 1
        parts_built = _part_counts(pattern["face_part"])
        loose = [v for v in bm.verts if not v.link_faces]
        bmesh.ops.delete(bm, geom=loose, context="VERTS")
        # Ruling A144: edges under MIN_EDGE_M (an armhole corner where two re-spaced rows meet, carried along the whole
        # sleeve) are collapsed; an open front's two seam columns share positions but no edge and stay apart
        bmesh.ops.dissolve_degenerate(bm, dist=MIN_EDGE_M, edges=bm.edges[:])
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        parts_kept = _part_counts([f[lay_part] for f in bm.faces])
        print(f"uv.islands parts built {parts_built} after dissolve_degenerate {parts_kept}", flush=True)
        bm.to_mesh(me)
        bm.free()
        slit_edges = 0
        # A178: a bodice built inside the arm root (armhole window, neckline chords through a high shoulder) is laid
        # out of the body smoothly here, before its rest lengths are taken
        binfo["clear"] = gd.clear_of_body(obj, ctree, thickness=thickness)
        # A198 (review 03 #5): a dress with a bodice keeps its slit — the bodice's columns lie on the same 80-step
        # angles from 1.5 pi as the skirt's wrap (``split_slit``'s step), measured up from its lowest row (the hem)
        if prm.get("slit"):
            hem_b = float(min(v.co.z for v in obj.data.vertices))
            slit_edges = split_slit(obj, None, prm.get("slit") or {}, hem_b, centre,
                                    centre_of=centre_at(row_c, spec["row_y"]) if row_c else None)
        uv_info = pattern_uv_of(obj, arm, centre, pattern, out / "islands.json", kind=bodice_kind)
        uv_info["parts_built"] = parts_built
        uv_info["parts_kept"] = parts_kept
        if cut_only:
            # the cut ends here: the panels are cut, laid out of the body and given their pattern UVs — the drape
            # below only moves vertices, so the islands it would write are these bytes
            files = {"islands": str(out / "islands.json")}
            if (out / "marks.json").is_file():
                files["marks"] = str(out / "marks.json")
            return gd._plain({"cut_only": True, "uv": uv_info, "bodice": binfo, "slit_edges": int(slit_edges),
                              "lower_layers": len(lower), "verts": len(obj.data.vertices),
                              "script_wall_s": round(time.time() - t_all, 2),
                              "script_cpu_s": round(time.process_time() - c_all, 2)}), files
    else:
        binfo = {}
        col = None
        # step 3b: the part of every face and the waistband's back-centre cut (``uv_pattern.wrap_parts``)
        fpart, fseams, winfo = uvp.wrap_parts(spec["rows"], spec["cols"], spec["row_y"], prm.get("kind"),
                                              float(prm.get("waistband_m") or 0.0),
                                              (spec.get("outline") or {}).get("waist_y"))
        binfo["wrap_parts"] = winfo
        wrap_marks = None
        if prm.get("kind") == "top":
            # phase G: a corset top's front is cut open at the centre and two bust darts (UV only), its back
            # centre is the placket line (``corset_darts``)
            fseams = list(fseams) + cdarts.dart_seams(spec["rows"], spec["cols"])
            wrap_marks = {"centre_back": (2, cdarts.back_line(spec["rows"], spec["cols"]))}
            if prm.get("shell_clear_m") is not None:
                # corset v3: its sewn seams, painted onto the cut atlas at assembly (``corset_darts.seam_lines``)
                wrap_marks.update(cdarts.seam_lines(spec["rows"], spec["cols"]))
        if prm.get("shell_clear_m") is not None and spec.get("cup_edge"):
            # corset v4: each front column's edge on the top of the chest tissue (``cup_edge``) — before ``wrap``, so
            # the cut and the drape lay the same rows
            binfo["cup_edge"] = cup_edge(spec, btree, centre)
            # corset v5: the side and back edge runs under the fold to the arm (``underarm_edge``)
            binfo["underarm_edge"] = underarm_edge(spec, btree, centre)
        row_c = leg_centres(bco[np.abs(bco[:, 0] - centre[0]) < half], centre, spec["row_y"],
                            lambda cen, r: wrap_radii(spec, btree, cen, r)) if prm.get("leg_centres") else None
        binfo["leg_shift_m"] = [round(float(c[1] - centre[1]), 3) for c in row_c] if row_c else None
        verts, faces, angles, top_ids = wrap(spec, btree, centre, band_rows=winfo["waistband_rows"], row_c=row_c)
        if prm.get("shell_clear_m") is not None:
            # corset v2: a strapless top lies on the body as a shell (``corset_shell``)
            binfo["shell"] = corset_shell(verts, angles, spec, btree, centre, float(prm["shell_clear_m"]), top_ids)
            shell_hollow = binfo["shell"].pop("hollow")
        me = bpy.data.meshes.new("template")
        me.from_pydata(verts, [], faces)
        me.uv_layers.new(name="UVMap")         # filled by ``pattern_uv_of_wrap`` below
        obj = bpy.data.objects.new(prm["node"], me)
        bpy.context.scene.collection.objects.link(obj)
        if spec.get("top_drop"):
            # A221: a lowered top edge is no longer one height — its row is pinned by name (survives the seam merge)
            obj.vertex_groups.new(name="pin_top").add(top_ids, 1.0, "REPLACE")
        bm = bmesh.new()
        bm.from_mesh(me)
        # set on the bmesh BEFORE the side seams are merged (face / edge custom data rides through
        # remove_doubles and split_slit)
        lay_part = bm.faces.layers.int.new("uv_part")
        lay_seam = bm.edges.layers.int.new("uv_seam")
        lay_cid = bm.verts.layers.int.new("uv_cid")
        bm.verts.ensure_lookup_table()
        for f, fp in zip(bm.faces, fpart):
            f[lay_part] = int(fp)
        for v in bm.verts:
            v[lay_cid] = v.index
        _WRAP_GRID.update(rows=spec["rows"], cols=spec["cols"])
        for a_, b_ in fseams:
            e = bm.edges.get((bm.verts[a_], bm.verts[b_]))
            if e is not None:
                e[lay_seam] = 1
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.004)   # the two side seams
        bm.to_mesh(me)
        bm.free()
        hem_z = spec["row_y"][-1]
        slit_edges = split_slit(obj, angles, prm.get("slit") or {}, hem_z, centre,
                                centre_of=centre_at(row_c, spec["row_y"]) if row_c else None)
        uv_info = pattern_uv_of_wrap(obj, centre, top_z, WRAP_ROWS.get(prm.get("kind"), "skirt"),
                                     out / "islands.json", band=winfo["band"], marks=wrap_marks)
        if cut_only:
            files = {"islands": str(out / "islands.json")}
            if (out / "marks.json").is_file():
                files["marks"] = str(out / "marks.json")
            return gd._plain({"cut_only": True, "uv": uv_info, "bodice": binfo, "slit_edges": int(slit_edges),
                              "lower_layers": len(lower), "verts": len(obj.data.vertices),
                              "script_wall_s": round(time.time() - t_all, 2),
                              "script_cpu_s": round(time.process_time() - c_all, 2)}), files
    me = obj.data
    co0 = np.array([v.co for v in me.vertices])
    # outward normals (Solidify and the projection side test read them)
    nrm = np.array([v.normal for v in me.vertices])
    radial = co0[:, :2] - centre
    if not fitted and float(np.mean(np.einsum("ij,ij->i", nrm[:, :2], radial))) < 0:
        bm = bmesh.new()
        bm.from_mesh(me)
        bmesh.ops.reverse_faces(bm, faces=bm.faces)
        bm.to_mesh(me)
        bm.free()
    edges = gd.edges_of(obj)
    rest_len = np.linalg.norm(co0[edges[:, 0]] - co0[edges[:, 1]], axis=1)
    if fitted:
        pin = fit_pin
    elif bod:
        nj = bod["joints"].get("neck")
        if bod.get("off_shoulder"):
            pin = off_shoulder_pins(obj, bod["off_shoulder"], arm, nj[0] if nj else centre[0])
        else:
            pin = bodice_pins(obj, bod, nj[0] if nj else centre[0], -nj[2] if nj else centre[1])
    elif "shell" in binfo:
        pin = np.arange(len(me.vertices))          # corset v2: the shell is pinned whole — it lies where it was laid
    elif "pin_top" in obj.vertex_groups:
        gi = obj.vertex_groups["pin_top"].index
        pin = np.array([v.index for v in me.vertices if any(g.group == gi for g in v.groups)], int)
    else:
        pin = np.where(co0[:, 2] > top_z - 0.004)[0]
    fab = prm["fabric"]
    thickness = float(prm.get("thickness", 0.004))
    gd.progress(stage="drape", frame=0, frames=int(prm.get("frames", 50)))
    # A179: the skinned collider of the arm shapes is this piece's rest collider, kept as a mesh copy (``drape``
    # crops and removes the object it is given)
    rest_me = col.data.copy() if col is not None and not lower else None
    cpu, wall, drift = (0.0, 0.0, 0.0) if "shell" in binfo else gd.drape(obj, body, pin, int(prm.get("frames", 50)),
                                quality=int(prm.get("drape_quality") or fab["quality"]),
                                bending=float(fab["bending"]), shrink=float(fab.get("shrink", 0.0)),
                                self_collision=False, thickness=thickness, extra=lower, crop_m=CROP_M, collider=col,
                                mass=float(fab.get("cloth_mass", 0.3)), air_damping=float(fab.get("air_damping", 5.0)),
                                **gd.spring_kwargs(fab))
    me = obj.data
    co1 = np.array([v.co for v in me.vertices])
    # ``stretch_gate``: the gated ratio ``st`` leaves out edges built under 3 mm and edges that grew under 1 mm (a
    # 1.33 mm edge at a deep V's bottom drawn to 2.43 mm read as stretch 1.82, bug round 2026-11-20); ``st_all``
    # only the degenerate ones under MIN_EDGE_M (A144) — the p99 and the raw maximum come from it
    st, st_all = sg.stretch(rest_len, np.linalg.norm(co1[edges[:, 0]] - co1[edges[:, 1]], axis=1))
    worst = co0[edges[int(st.argmax())]].mean(0)
    worst_at = {"z": round(float(worst[2]), 3),
                "deg": round(math.degrees(math.atan2(worst[1] - centre[1], worst[0] - centre[0])) % 360, 1),
                "over_1_3": int((st > 1.3).sum()), "short_edges": int((rest_len < MIN_EDGE_M).sum()),
                "over_1_3_all": int((st_all > 1.3).sum()), "min_rest_mm": round(float(rest_len.min()) * 1000, 2),
                "over_at": [[round(float(x), 2) for x in co0[e].mean(0)] for e in edges[np.argsort(-st)[:8]]], "rest_mm": round(float(rest_len[int(st.argmax())]) * 1000, 1),
                "x": round(float(worst[0]), 3), "y": round(float(worst[1]), 3)}
    n_single = len(me.vertices)
    # corset v2: how close the shell lies (``shell_gaps``; gated in ``garment_template.judge_build``)
    fit_gap = shell_gaps(obj, ftree, btree, centre, spec, float(prm["shell_clear_m"]),
                         prm.get("shell_gap_mm") or {}, shell_hollow) if "shell" in binfo else None
    if fitted and fitted["kind"] == "briefs":
        binfo["cover"] = gf.part_cover(body, obj)
    neck = {}
    nlp = []
    if bod:
        nj = bod["joints"].get("neck")
        built = np.array([obj.matrix_world @ Vector(c) for c in co0])
        nlp = neck_loop(obj, built, *((nj[0], -nj[2]) if nj else (centre[0], centre[1])))
        neck["built"] = neck_metrics(built[nlp])
        neck["draped"] = neck_metrics(gd.world_coords(obj)[0][nlp])
    skirtish = prm.get("kind") in ("skirt", "dress")
    hem, up = hem_sets(obj, top_z) if skirtish else (np.zeros(0, int), np.zeros(0, int))
    if bod and len(hem):                   # the hem only: armholes, straps and the neckline are boundaries too
        low = co0[hem, 2] < (spec.get("outline") or {}).get("waist_y", top_z) - 0.05
        hem, up = hem[low], up[low]
    # skin the single layer (the corrective drapes need it), inpaint the free cloth's weights
    gd.bind_to_armature(obj, body, arm)
    weights = smooth_weights(obj, body) if prm.get("smooth_weights", True) else {}
    if lower and prm.get("smooth_weights", True):
        weights["layer"] = layer_weights(obj, lower)
    if fitted:
        weights["fitted"] = gf.even_weights(obj, weight_matrix, write_weights)
    names, W = weight_matrix(obj)
    rest_world = np.array([obj.matrix_world @ v.co for v in obj.data.vertices])
    groups = [dict(g) for g in (prm.get("shape_groups") or [])]
    deltas, shape_info = {}, {}
    collider = None
    t_shape = time.time()
    xs, zs = rest_world[:, 0], rest_world[:, 2]
    ncx = (bod["joints"].get("neck") or [centre[0]])[0] if bod else centre[0]
    band = bod["band_y"] if bod else 9.0
    waist_z = (spec.get("outline") or {}).get("waist_y", -9.0)
    shape_todo = list(dict.fromkeys(p for g in groups for p in g.get("poses") or []))
    for g in groups:
        g["targets"] = []
        for pose in g["poses"]:
            if pose not in deltas.get("_raw", {}):
                frames = int(g.get("frames") or SHAPE_FRAMES)
                # the arm poses collide with the skinned rest collider; a leg pose bends the hips far, where the
                # skinned surface folds into itself (sit poke 0.64 % with it, 0 with a fresh remesh: A144)
                arm_pose = g["name"] != "legs"
                if arm_pose and collider is None and not lower:
                    collider = gd.skinned_collider(body, arm, rest=rest_me)
                gd.progress(stage="shapes", pose=pose, index=shape_todo.index(pose) + 1 if pose in shape_todo else None,
                            count=len(shape_todo), frame=0, frames=None)
                d, info = pose_shape(arm, body, obj, pose, pin, names, W, rest_world, fab, thickness, lower=lower,
                                     frames=frames, collider=collider if arm_pose else None)
                deltas.setdefault("_raw", {})[pose] = d
                shape_info[pose] = info
            d = deltas["_raw"][pose]
            if shape_info[pose]["moved_p90_mm"] > SHAPE_MAX_MOVE_P90_MM:
                shape_info[pose]["dropped"] = f"moved p90 {shape_info[pose]['moved_p90_mm']} mm"
                continue
            if g["name"] == "legs":
                mask = np.clip((band - zs) / 0.05, 0.0, 1.0) if bod else np.ones(len(zs))
                name = pose
            else:
                side = np.clip((xs - ncx) / 0.04 + 0.5, 0.0, 1.0)
                side = side if g["side"] == "l" else 1.0 - side
                below = np.clip((zs - (waist_z - 0.05)) / 0.1, 0.0, 1.0) if prm.get("kind") == "dress" else 1.0
                mask = side * below
                name = f"{pose}_{g['side']}"
            deltas[name] = d * mask[:, None]
            g["targets"].append(name)
    deltas.pop("_raw", None)
    if collider is not None:
        bpy.data.objects.remove(collider)
    gd.set_pose(arm, "rest")
    shape_wall = round(time.time() - t_shape, 2)
    # Solidify without the armature in the stack: its copy layer follows the original vertex order
    for m in list(obj.modifiers):
        obj.modifiers.remove(m)
    # A198 (review 03 #1, #6): the single layer's faces and open borders, read BEFORE the Solidify — after it the
    # copy layer shares the UVs (the projection must paint layer 0 only) and the rim closes every border edge
    n_faces_single = len(obj.data.polygons)
    rim_single = gd.boundary_verts(obj)
    sol = obj.modifiers.new("sol", "SOLIDIFY")
    sol.thickness = 0.0015
    sol.offset = 1
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=sol.name)
    # cloth is smooth: flat faces would also split every vertex four ways in the export (four times the
    # morph data)
    obj.data.polygons.foreach_set("use_smooth", [True] * len(obj.data.polygons))
    co2 = np.array([v.co for v in obj.data.vertices])
    layers = len(co2) // n_single if len(co2) % n_single == 0 else 0
    ref = rest_world_local(obj, rest_world)
    layer_err = [float(np.abs(co2[k * n_single:(k + 1) * n_single] - ref).max()) for k in range(layers)]
    if deltas and not (layers >= 1 and min(layer_err) < 0.003):
        raise RuntimeError(f"solidify changed the vertex order ({len(co2)} verts from {n_single}, {layer_err})")
    arm_mod = obj.modifiers.new("arm", "ARMATURE")
    arm_mod.object = arm
    rot_inv = np.array(obj.matrix_world.to_3x3().inverted())
    targets = []
    if deltas:
        obj.shape_key_add(name="Basis", from_mix=False)
        for g in groups:
            for name in g["targets"]:
                kb = obj.shape_key_add(name=name, from_mix=False)
                dl = (deltas[name] @ rot_inv.T)
                full = np.tile(dl, (layers, 1))
                flat = (co2 + full).astype(np.float32).ravel()
                kb.data.foreach_set("co", flat)
                kb.value = 0.0
                targets.append(name)
    out_groups = []
    for g in groups:
        samples = []
        for pose in [*g["anchors"], *g["poses"]]:
            gd.set_pose(arm, pose)
            f = driver_features(arm, g["segments"], g["frame"])
            target = (pose if g["name"] == "legs" else f"{pose}_{g['side']}") if pose in g["poses"] else None
            if target not in g["targets"]:
                target = None              # an anchor, or a shape that was dropped
            samples.append({"pose": pose, "target": target, "dirs": f})
            if g.get("mirror"):
                mf = mirror_features(f)
                if max(abs(a - b) for u, v in zip(f, mf) for a, b in zip(u, v)) > 1e-3:
                    samples.append({"pose": pose + "_mirror", "target": target, "dirs": mf})
        out_groups.append({"name": g["name"], "frame": g["frame"], "segments": [list(x) for x in g["segments"]],
                           "sigma": g["sigma"], "targets": list(g["targets"]), "samples": samples})
    gd.set_pose(arm, "rest")
    pose_shapes = {"version": 2, "targets": targets, "groups": out_groups} if targets else None
    gd.progress(stage="bake", pose=None, index=None, count=None, frame=None, frames=None)
    t_bake = time.time()
    views = {"view_front": inp["front"], "view_back": inp["back"],
             "open_front": inp.get("front_open"), "open_back": inp.get("back_open")}
    loaded = gd.bake_views(views)
    bake_info = {}
    gloves = bool(fitted) and fitted.get("kind") == "gloves"
    # every fitted piece may be a pair (gloves; tights of the hold-up / thigh-high / knee-high styles are two leg
    # pieces): each part is registered on its own wherever both the mesh and the picture fall apart into two
    # (``bake_register.islands`` / ``alpha_parts``); a piece that does not (full tights, trousers, a bra) keeps one map
    paired = bool(fitted)
    # every piece bakes at its atlas size (the islands are packed at one px/cm into it)
    bake_px = int(uv_info["atlas_px"])
    if bod or gloves:
        # bug round 2026-11-20: gloves search the arm pose too (the way the picture shows them), each glove on its own
        degs, fingers = glove_arm_degs(loaded["front"]["alpha"]) if gloves else (BAKE_ARM_DEG, None)
        deg, bco_, bnr_, sil = bake_pose(arm, obj, loaded, degs=degs, polys=n_faces_single, paired=paired)
        bake_info = {"arm_deg": deg, **sil, **({"fingers": fingers} if gloves else {})}
        tex = gd.project_bake(obj, views, out / "template_atlas.png", size=bake_px, co=bco_, nr=bnr_,
                              polys=n_faces_single, paired=paired, views=loaded)
    else:
        tex = gd.project_bake(obj, views, out / "template_atlas.png", size=bake_px, polys=n_faces_single,
                              paired=paired, views=loaded)
    tex.update(bake_info)
    tex["wall_s"] = round(time.time() - t_bake, 2)
    edges2 = gd.edges_of(obj)
    rest2 = np.linalg.norm(co2[edges2[:, 0]] - co2[edges2[:, 1]], axis=1)
    rim = rim_single   # layer 0 keeps the single layer's vertex order (checked above)
    view = gd.frame_of(co2)
    t_meas = time.time()
    render_s = 0.0
    measured = {}
    measure_poses = list(prm.get("poses") or ["rest"])
    for pose in measure_poses:
        gd.progress(stage="measure", pose=pose, index=measure_poses.index(pose) + 1, count=len(measure_poses))
        gd.set_pose(arm, pose)
        inf = blend_groups(arm, out_groups) if pose_shapes else {}
        for name in targets:
            obj.data.shape_keys.key_blocks[name].value = float(inf.get(name, 0.0))
        for lo in lower:
            apply_shapes(lo, arm)
        measured[pose] = gd.measure_pose(arm, body, obj, pose, rest2, edges2, rim)
        if skirtish:
            measured[pose].update(hem_metrics(obj, body, hem, up))
        for k, lo in enumerate(lower):
            lm = gd.measure_pose(arm, lo, obj, pose, rest2, edges2, rim)
            measured[pose][f"layer_poke_share_{k}"] = lm["poke_share"]
            measured[pose][f"layer_region_{k}"] = lm["region_body_verts"]
        if len(nlp):
            measured[pose]["neck"] = neck_metrics(gd.world_coords(obj)[0][nlp])
        measured[pose]["shapes"] = {k: round(v, 4) for k, v in inf.items()}
        if prm.get("render"):
            t_r = time.time()
            for lo in lower:
                lo.hide_render = False
            gd.render(out / f"template_{pose}.png", view)
            gd.render(out / f"template_{pose}_left.png", view, side=0.55)
            render_s += time.time() - t_r
            # the posed garment (glTF axes, float32) for checks of a renderer against this pose
            gco, _gn, _gt = gd.world_coords(obj)
            np.ascontiguousarray(np.c_[gco[:, 0], gco[:, 2], -gco[:, 1]], np.float32).tofile(
                str(out / f"template_{pose}_posed.f32"))
    for name in targets:
        obj.data.shape_keys.key_blocks[name].value = 0.0
    gd.set_pose(arm, "rest")
    meas_s = round(time.time() - t_meas, 2)
    glb = out / "template.glb"
    export_glb(glb, [arm, obj])
    outputs = {"glb": str(glb), "atlas": str(out / "template_atlas.png")}
    if uv_info:
        outputs["islands"] = str(out / "islands.json")
    for pose in measured:
        p = out / f"template_{pose}.png"
        if p.is_file():
            outputs[f"render_{pose}"] = str(p)
        p = out / f"template_{pose}_left.png"
        if p.is_file():
            outputs[f"render_{pose}_left"] = str(p)
        q = out / f"template_{pose}_posed.f32"
        if q.is_file():
            outputs[f"posed_{pose}"] = str(q)
    data = {"verts": len(obj.data.vertices), "pins": int(len(pin)), "slit_edges": int(slit_edges),
            "bodice": binfo, "neck": neck, "lower_layers": len(lower), **({"fit_gap": fit_gap} if fit_gap else {}),
            "drape": {"cpu_s": cpu, "wall_s": wall, "pin_drift_mm": drift,
                      "stretch_max": round(float(st.max()), 3), "stretch_at": worst_at,
                      "stretch_max_all": round(float(st_all.max()), 3),
                      "stretch_p99": round(float(np.percentile(st_all, 99)), 3),
                      "quality": int(prm.get("drape_quality") or fab["quality"])},
            "weights": weights, "shapes": {"wall_s": shape_wall, **shape_info}, "collider_s": list(gd.COLLIDER_S),
            "collider_inner": list(gd.COLLIDER_INNER), "collider_outer": list(gd.COLLIDER_OUTER),
            "outer_body_verts": {k: int(v.sum()) for k, v in gd.OUTER_BODY.items()}, "pose_shapes": pose_shapes,
            "hem_verts": int(len(hem)), **({"uv": uv_info} if uv_info else {}),
            "bake": tex, "draped": measured, "measure_wall_s": meas_s, "render_wall_s": round(render_s, 2),
            "script_wall_s": round(time.time() - t_all, 2), "script_cpu_s": round(time.process_time() - c_all, 2)}
    return gd._plain(data), outputs


def rest_world_local(obj, rest_world):
    """The bind-pose world coordinates in the object's own space."""
    inv = np.array(obj.matrix_world.inverted())
    return rest_world @ inv[:3, :3].T + inv[:3, 3]


if __name__ == "__main__":
    main(run)
