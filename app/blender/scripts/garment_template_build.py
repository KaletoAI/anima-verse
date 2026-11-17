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
sys.path.pop(0)

#: Angle of each slit side (0 = +X = the character's left, front = -Y).
SLIT_ANGLE = {"left": 0.0, "back": math.pi / 2, "right": math.pi, "front": 3 * math.pi / 2}
TOP_CLEAR_M = 0.006
ROW_CLEAR_M = 0.02


def wrap(spec, btree, centre):
    """Vertices / quads / UVs of the panels wrapped round the body axis."""
    rows, cols = spec["rows"], spec["cols"]
    row_y = spec["row_y"]
    spans = {"front": (math.pi, 2 * math.pi), "back": (0.0, math.pi)}
    verts, faces, uvs, angles = [], [], [], []
    allg = np.array([p["grid_m"] for p in spec["panels"]])
    xmin, xmax = allg[..., 0].min(), allg[..., 0].max()
    ymax = allg[..., 1].max()
    for pi_, p in enumerate(spec["panels"]):
        g = np.array(p["grid_m"])
        a0, a1 = spans[p["name"]]
        for r in range(rows):
            row = g[r]
            circ = 2 * float(np.sum(np.linalg.norm(np.diff(row, axis=0), axis=1)))
            z = row_y[r]
            for c in range(cols):
                ang = a0 + (a1 - a0) * c / (cols - 1)
                body_r = gd.body_radius(btree, centre, ang, z)
                if r == 0:
                    rad = body_r + TOP_CLEAR_M if body_r > 0 else circ / (2 * math.pi)
                else:
                    rad = max(circ / (2 * math.pi), body_r + ROW_CLEAR_M)
                verts.append((centre[0] + rad * math.cos(ang), centre[1] + rad * math.sin(ang), z))
                uvs.append((0.02 + 0.47 * (row[c, 0] - xmin) / max(1e-6, xmax - xmin) + 0.5 * pi_,
                            0.02 + 0.96 * row[c, 1] / max(1e-6, ymax)))
                angles.append(ang)
        base = pi_ * rows * cols
        for r in range(rows - 1):
            for c in range(cols - 1):
                i = base + r * cols + c
                faces.append((i, i + 1, i + cols + 1, i + cols))
    return verts, faces, uvs, angles


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
#: Edges built shorter than this are left out of the stretch ratio.
MIN_EDGE_M = 0.001
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
UV_TORSO = (0.30, 0.86)
UV_CAP = (0.87, 0.98)
UV_COLLAR = (0.985, 0.995)
UV_SLEEVE = (0.02, 0.28)


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




def _surface_z(tree, x, y, z_hi, floor):
    """A179 — the height of the body's top surface under (x, y), seen from ``z_hi`` down to ``floor``, and the Z of
    its normal: the first upward-facing entry, unless an air gap larger than LAYER_GAP_M opens below it — then what
    was met is an overhang (the chin or beard of a head bent forward; a ray that STARTS inside it leaves it first)
    and the entry under the gap is the surface (A178's tongue: the yoke climbed 13 cm to the chin there). None when
    the ray starts inside the body and never leaves it, or meets nothing."""
    cand, last_exit, z = None, None, z_hi
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


def _exit_out(tree, o, d, reach):
    """A179 — the distance from ``o`` (inside the body) along ``d`` to where the ray leaves the body for good within
    ``reach``: the first exit, carried through any re-entry closer than LAYER_GAP_M (a lower garment layer).
    ``(distance, cosine between the normal there and d)``, or None when ``o`` is not inside along this ray."""
    o, d = Vector(o), Vector(d)
    t, out = 0.0, None
    for _ in range(6):
        hit = tree.ray_cast(o + d * t, d, reach - t)
        if hit[0] is None:
            break
        nd = float(hit[1].dot(d))
        if nd > 0:
            out = (t + hit[3], nd)
        elif out is None or t + hit[3] - out[0] > LAYER_GAP_M:
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


def build_bodice(spec, btree, ftree, centre, arm, ctree=None, clear=0.008):
    """Ruling A142 — the vertices, faces and per-corner UVs of a piece with a bodice (Blender world, Z up, front =
    -Y): the torso rows wrapped round the body like a skirt (row 0 = the shoulder line), a yoke ("cap") from the
    shoulder line in to the neck opening, laid on the shoulders, the armholes cut at the side seams with the sleeves
    grown out of the armhole loops along the arm bones, the neckline cut at the front, straps, an open front and a
    stand collar. Returns ``(verts, faces, face_uvs, info)``; info carries the vertex groups the caller needs.

    A179 — with ``ctree`` (the BVH tree of ``gd.rest_collider``: the closed collider the drape meets) every vertex
    is built at least ``clear`` outside it: the rows above the armhole's bottom from the full body section
    (``section_row``), the armhole loop on the arm root, the neck opening from the neck surface (``neck_ring``), the
    yoke on the body's top surface (``_surface_z``), every meridian laid along the collider (``_lay_path``). Without
    it the A144 rules stand (torso-only radius, a circle round the neck joint)."""
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
    verts, faces, fuv = [], [], []
    tid = np.zeros((rows, nc), int)
    band_y = bod["band_y"]
    r_band = max(r for r in range(rows) if row_y[r] >= band_y - 1e-6) if any(y >= band_y for y in row_y) else rows - 1
    side_c = {"l": N // 4, "r": 3 * N // 4}
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
                ex = _exit_out(ctree, A + t_ * d_, (0.0, 0.0, -1.0), 0.3)
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
        wcols = min(WINDOW_COLS_MAX, max(WINDOW_COLS, int(math.ceil(need / (2 * math.pi / N)))))
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
            rad = row_radii(btree, centre, angles[:N], z, circ[r], w=w)
            xy = np.c_[centre[0] + rad * np.cos(angles[:N]), centre[1] + rad * np.sin(angles[:N])]
            if ctree is not None:
                # A179: the collider closes the crease between the arm's underside and the lat that the body mesh
                # leaves open: a chest-band vertex built in that crease stood 12-22 mm inside the collider. Such a
                # vertex is laid on the nearest point outside it (under the arm), not farther out along its ray —
                # there the T-posed arm is in the way
                for c in range(N):
                    v = Vector((xy[c, 0], xy[c, 1], z))
                    loc, out = gd.signed_out(ctree, v, 0.12)
                    if loc is not None and (v - loc).dot(out) < clear:
                        laid[(r, c)] = tuple(loc + out * clear)
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

    def u_of(c):
        return 0.01 + 0.98 * c / N

    def v_rows(r):
        return UV_TORSO[0] + (UV_TORSO[1] - UV_TORSO[0]) * (1.0 - r / (rows - 1))
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
                if zs is None:             # under a ridge that stands above the ceiling: its top
                    zs = _surface_z(ctree, xy[0], xy[1], z_hi + 0.08, z_hi)
                capz[k, c] = max(floor_z, zs[0] + CAP_CLEAR_M / max(0.5, zs[1])) if zs is not None else floor_z
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
            u1 = u_of(c + 1)
            fuv.append(((u_of(c), v_rows(r)), (u1, v_rows(r)), (u1, v_rows(r + 1)), (u_of(c), v_rows(r + 1))))
    collar = bod.get("collar") in ("stand", "lapel")
    nring = K + (COLLAR_RINGS if collar else 0)
    for k in range(K + 1, nring + 1):
        for c in range(nc):
            x, y, z = verts[cid[K, c]]
            sh = 0.97 ** (k - K)
            cid[k, c] = len(verts)
            verts.append((ncx + (x - ncx) * sh, ncy + (y - ncy) * sh, z + COLLAR_STEP_M * (k - K)))
    for k in range(nring):
        v0 = UV_CAP[0] + (UV_CAP[1] - UV_CAP[0]) * k / K if k < K else UV_COLLAR[0]
        v1 = UV_CAP[0] + (UV_CAP[1] - UV_CAP[0]) * (k + 1) / K if k + 1 <= K else UV_COLLAR[1]
        for c in range(span):
            c2 = (c + 1) % nc
            if k >= K and max(cut_s[c], cut_s[c2]) > COLLAR_CUT_MAX_M:
                continue                   # the collar ends where the neckline runs down the front (its gorge)
            faces.append((cid[k, c], cid[k, c2], cid[k + 1, c2], cid[k + 1, c]))
            u1 = u_of(c + 1)
            fuv.append(((u_of(c), v0), (u1, v0), (u1, v1), (u_of(c), v1)))
    # the binding: the neck rim and the next ring in (the innermost two rings of every meridian, or the collar)
    rib_ids = sorted({int(cid[k, c]) for c in range(nc) for k in (nring, nring - 1)})
    # sleeves: ring 0 = the armhole loop
    sleeve_rows = {}
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
            ring_ds = [(d, c) for d, c in sl["rings"] if d > d0 + 0.02]
            if not ring_ds or ring_ds[-1][0] < sl["len_m"] - 1e-3:
                ring_ds.append((max(sl["len_m"], d0 + 0.03), sl["rings"][-1][1]))
            M = len(loop)
            S = len(ring_ds)
            # A179: a sleeve ring has as many vertices as its girth asks for (SLEEVE_EDGE_M apart), not as many as
            # the armhole loop: Blender's cloth mass is PER VERTEX, so a ring of 48 vertices 7-10 mm apart (the loop
            # of a wide armhole) weighed twice the torso's cloth and stretched the sleeve's top to 1.33. The first
            # ring is joined to the loop by quads and triangles.
            Ms = min(M, max(12, int(round(float(np.mean([c for _d, c in ring_ds])) / SLEEVE_EDGE_M))))
            at = np.arange(Ms) * M / Ms                                  # each ring vertex's place along the loop
            phi_c = np.r_[phi, phi[0] + turn]
            L_c = np.vstack([L, L[:1]])
            phi_m = np.interp(at, np.arange(M + 1), phi_c)
            L_m = np.c_[[np.interp(at, np.arange(M + 1), L_c[:, k]) for k in range(3)]].T
            # Ruling A144: along the sleeve the ring vertices spread evenly round the arm (the armhole loop's spacing
            # is uneven: bunched vertices made 4.7 mm edges that took the drape's largest stretch at the cuff)
            even = phi[0] + turn * np.arange(Ms) / Ms
            prev = loop
            u_lo, u_hi = (0.01, 0.49) if side == "l" else (0.51, 0.99)
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
                hang = max(0.0, r_ring - (_ray_in(ftree, Q, f2) + SLEEVE_CLEAR_M))
                cur = []
                for i in range(Ms):
                    ang = (1 - w) * phi_m[i] + w * even[i]
                    dirv = math.cos(ang) * f1 + math.sin(ang) * f2
                    target = Q - hang * f2 + r_ring * dirv
                    off = target - Q
                    dist = float(np.linalg.norm(off))
                    need = _ray_in(ftree, Q, off / max(dist, 1e-9)) + SLEEVE_CLEAR_M
                    if dist < need:
                        target = Q + off / max(dist, 1e-9) * need
                    moved = L_m[i] + (Q - Q0)
                    p = (1 - w) * moved + w * target
                    if ctree is not None and float(np.dot(p - Q, f2)) > 0:
                        # the armhole's top carried out along a thinning arm floats over it: lowered onto the arm
                        zs = _surface_z(ctree, p[0], p[1], float(p[2]) + 1e-3, float(Q[2]))
                        if zs is not None:
                            p[2] = min(p[2], zs[0] + SLEEVE_CLEAR_M / max(0.5, zs[1]))
                    cur.append(len(verts))
                    verts.append(tuple(p))
                va = UV_SLEEVE[0] + (UV_SLEEVE[1] - UV_SLEEVE[0]) * (j - 1) / S
                vb = UV_SLEEVE[0] + (UV_SLEEVE[1] - UV_SLEEVE[0]) * j / S
                P = len(prev)
                for i in range(P):
                    i2 = (i + 1) % P
                    a_, b_ = (i * Ms) // P, ((i + 1) * Ms) // P
                    ua = u_lo + (u_hi - u_lo) * i / P
                    ub = u_lo + (u_hi - u_lo) * (i + 1) / P
                    if a_ == b_:           # two loop vertices share this ring vertex
                        faces.append((prev[i], prev[i2], cur[a_]))
                        fuv.append(((ua, va), (ub, va), (ua, vb)))
                    else:
                        faces.append((prev[i], prev[i2], cur[b_ % Ms], cur[a_]))
                        fuv.append(((ua, va), (ub, va), (ub, vb), (ua, vb)))
                prev = cur
                rows_ids.append(cur)
            sleeve_rows[side] = rows_ids
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
    for f, uv in zip(faces, fuv):
        cen = V[list(f)].mean(0)
        x, z = cen[0] - ncx, cen[2]
        if straps and z > band_y + 0.005 and abs(abs(x) - bod["strap_x"]) > bod["strap_w"] / 2:
            continue
        keep.append((f, uv))
    faces = [f for f, _ in keep]
    fuv = [uv for _, uv in keep]
    used = {i for f in faces for i in f}
    cap_ids = sorted(cap_set & used)
    loops = {int(i) for rows_ids in sleeve_rows.values() for i in rows_ids[0]}
    slv = {int(i) for rows_ids in sleeve_rows.values() for ring in rows_ids[1:] for i in ring}
    yoke = {int(i) for i in cid[1:nring + 1].ravel()}
    upper = {int(i) for i in tid[:r_band].ravel()} - loops
    regions = {"yoke": yoke, "upper_rows": upper, "armhole": loops, "sleeves": slv,
               "lower_rows": {int(i) for i in tid[r_band:].ravel()} - loops}
    info = {"cap_ids": cap_ids, "rib_ids": sorted(set(rib_ids) & used),
            "regions": {k: sorted(v & used) for k, v in regions.items()},
            "cut_s": [round(x, 3) for x in cut_s], "sleeve_rings": {k: len(v) - 1 for k, v in sleeve_rows.items()}, "cap_rings": K,
            "collar_rings": nring - K, "columns": nc, "window_cols": wcols, "r_band": r_band, "arm_under_z": None if arm_under is None else round(arm_under, 4), "section_rows": sections, "neck_ring": ring_info}
    return verts, faces, fuv, info


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


def split_slit(obj, angles, slit, hem_z, centre):
    """Split the vertical edges at the slit's angle from the hem up to ``depth_m``."""
    side, depth = slit.get("side"), float(slit.get("depth_m") or 0)
    if side not in SLIT_ANGLE or depth <= 0:
        return 0
    target = SLIT_ANGLE[side]
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.verts.ensure_lookup_table()

    def ang_of(v):
        a = math.atan2(v.co.y - centre[1], v.co.x - centre[0]) % (2 * math.pi)
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
                                prebuilt=collider)
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


def load_lower(path, arm, payload):
    """Import a lower drape GLB (Ruling A142 layering) and skin its garment to OUR armature (same bone names)."""
    import json
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(path))
    new = [o for o in bpy.data.objects if o not in before]
    garment = max((o for o in new if o.type == "MESH"), key=lambda o: len(o.data.vertices))
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
    return garment


def _set_arm_angle(arm, deg):
    """The arms lowered ``deg`` from the T-pose (the bake pose search)."""
    gd.POSES["_bake"] = [("LeftArm", "Y", deg), ("RightArm", "Y", -deg)]
    gd.set_pose(arm, "_bake")


#: Arm angles (degrees below the T-pose) tried for the projection of a bodice's views.
BAKE_ARM_DEG = (0, 20, 35, 50, 65, 80)


#: Silhouette grid of the bake pose search (columns x rows over the alpha / outline box).
SIL_W, SIL_H = 48, 64


def _silhouette(xs, zs):
    """Boolean SIL_H x SIL_W grid of points normalised to their own box, closed by a 1-cell dilation."""
    g = np.zeros((SIL_H, SIL_W), bool)
    fx = (xs - xs.min()) / max(1e-9, xs.max() - xs.min())
    fz = (zs - zs.min()) / max(1e-9, zs.max() - zs.min())
    g[np.clip((fz * (SIL_H - 1)).astype(int), 0, SIL_H - 1), np.clip((fx * (SIL_W - 1)).astype(int), 0, SIL_W - 1)] = True
    d = g.copy()
    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        d |= np.roll(np.roll(g, dy, 0), dx, 1)
    return d


def bake_pose(arm, obj, views):
    """Ruling A142 — the arm angle whose posed front silhouette matches the front view's alpha best (IoU on a
    SIL_W x SIL_H grid, both normalised to their own box): an item picture shows a top with its sleeves hanging, a
    T-posed drape would project its sleeve pixels onto the torso. Returns ``(deg, co, nr, info)`` (world positions /
    normals in that pose)."""
    im = bpy.data.images.load(views["view_front"])
    w, h = im.size
    px = np.array(im.pixels[:]).reshape(h, w, im.channels)
    alpha = px[..., 3] if im.channels == 4 else np.ones((h, w))
    ys, xs = np.where(alpha > 0.5)
    want = np.zeros((SIL_H, SIL_W), bool)
    fx = (xs - xs.min()) / max(1, xs.max() - xs.min())
    fz = (ys - ys.min()) / max(1, ys.max() - ys.min())        # row 0 = bottom (Blender pixels)
    want[np.clip((fz * (SIL_H - 1)).astype(int), 0, SIL_H - 1), np.clip((fx * (SIL_W - 1)).astype(int), 0, SIL_W - 1)] = True
    best, scores = None, {}
    for deg in BAKE_ARM_DEG:
        _set_arm_angle(arm, deg)
        co, nr, _t = gd.world_coords(obj)
        front = nr[:, 1] <= 0
        sil = _silhouette(co[front, 0], co[front, 2])
        iou = float((sil & want).sum() / max(1, (sil | want).sum()))
        scores[deg] = round(iou, 3)
        if best is None or iou > best[0]:
            best = (iou, deg, co, nr)
    gd.set_pose(arm, "rest")
    return best[1], best[2], best[3], {"iou": scores}


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
    for i, payload in enumerate(prm.get("lower_shapes") or []):
        key = f"lower_{i}"
        if inp.get(key):
            lower.append(load_lower(inp[key], arm, payload))
    bco, _bn, btri = gd.world_coords(body)
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
    if bod:
        # the torso axis of a bodice is the spine (the slice at the shoulder line holds the arms' roots)
        # A179: its Y is the arm joints' (the armhole windows open either side of the axis: an axis 3 cm in front of
        # the arms put the back border of each window 5 cm out on the upper arm)
        sp = _bone_world(arm, "Spine2")
        centre = np.array([sp[0], (_bone_world(arm, "LeftArm")[1] + _bone_world(arm, "RightArm")[1]) / 2])
        thickness = float(prm.get("thickness", 0.004))
        col, ctree = gd.rest_collider(body, extra=lower)
        verts, faces, fuv, binfo = build_bodice(spec, btree, ftree, centre, arm, ctree=ctree,
                                                clear=thickness + gd.BUILD_CLEAR_EXTRA_M)
        binfo["inside"] = inside_report(ctree, verts, binfo.pop("regions"), thickness)
        me = bpy.data.meshes.new("template")
        me.from_pydata(verts, [], faces)
        uvl = me.uv_layers.new(name="UVMap")
        for poly, uvs in zip(me.polygons, fuv):
            for lp, uv in zip(poly.loop_indices, uvs):
                uvl.data[lp].uv = uv
        obj = bpy.data.objects.new(prm["node"], me)
        bpy.context.scene.collection.objects.link(obj)
        obj.vertex_groups.new(name="cap").add(binfo.pop("cap_ids"), 1.0, "REPLACE")
        obj.vertex_groups.new(name="rib").add(binfo.pop("rib_ids"), 1.0, "REPLACE")
        bm = bmesh.new()
        bm.from_mesh(me)
        loose = [v for v in bm.verts if not v.link_faces]
        bmesh.ops.delete(bm, geom=loose, context="VERTS")
        # Ruling A144: edges under MIN_EDGE_M (an armhole corner where two re-spaced rows meet, carried along the whole
        # sleeve) are collapsed; an open front's two seam columns share positions but no edge and stay apart
        bmesh.ops.dissolve_degenerate(bm, dist=MIN_EDGE_M, edges=bm.edges[:])
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        bm.to_mesh(me)
        bm.free()
        slit_edges = 0
        # A178: a bodice built inside the arm root (armhole window, neckline chords through a high shoulder) is laid
        # out of the body smoothly here, before its rest lengths are taken
        binfo["clear"] = gd.clear_of_body(obj, ctree, thickness=thickness)
    else:
        binfo = {}
        col = None
        verts, faces, uvs, angles = wrap(spec, btree, centre)
        me = bpy.data.meshes.new("template")
        me.from_pydata(verts, [], faces)
        uvl = me.uv_layers.new(name="UVMap")
        for lp in me.loops:
            uvl.data[lp.index].uv = uvs[lp.vertex_index]
        obj = bpy.data.objects.new(prm["node"], me)
        bpy.context.scene.collection.objects.link(obj)
        bm = bmesh.new()
        bm.from_mesh(me)
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.004)   # the two side seams
        bm.to_mesh(me)
        bm.free()
        hem_z = spec["row_y"][-1]
        slit_edges = split_slit(obj, angles, prm.get("slit") or {}, hem_z, centre)
    me = obj.data
    co0 = np.array([v.co for v in me.vertices])
    # outward normals (Solidify and the projection side test read them)
    nrm = np.array([v.normal for v in me.vertices])
    radial = co0[:, :2] - centre
    if float(np.mean(np.einsum("ij,ij->i", nrm[:, :2], radial))) < 0:
        bm = bmesh.new()
        bm.from_mesh(me)
        bmesh.ops.reverse_faces(bm, faces=bm.faces)
        bm.to_mesh(me)
        bm.free()
    edges = gd.edges_of(obj)
    rest_len = np.linalg.norm(co0[edges[:, 0]] - co0[edges[:, 1]], axis=1)
    if bod:
        nj = bod["joints"].get("neck")
        pin = bodice_pins(obj, bod, nj[0] if nj else centre[0], -nj[2] if nj else centre[1])
    else:
        pin = np.where(co0[:, 2] > top_z - 0.004)[0]
    fab = prm["fabric"]
    thickness = float(prm.get("thickness", 0.004))
    gd.progress(stage="drape", frame=0, frames=int(prm.get("frames", 50)))
    # A179: the skinned collider of the arm shapes is this piece's rest collider, kept as a mesh copy (``drape``
    # crops and removes the object it is given)
    rest_me = col.data.copy() if col is not None and not lower else None
    cpu, wall, drift = gd.drape(obj, body, pin, int(prm.get("frames", 50)),
                                quality=int(prm.get("drape_quality") or fab["quality"]),
                                bending=float(fab["bending"]), shrink=float(fab.get("shrink", 0.0)),
                                self_collision=False, thickness=thickness, extra=lower, crop_m=CROP_M, collider=col)
    me = obj.data
    co1 = np.array([v.co for v in me.vertices])
    st = np.linalg.norm(co1[edges[:, 0]] - co1[edges[:, 1]], axis=1) / np.maximum(rest_len, 1e-6)
    # an edge built shorter than MIN_EDGE_M (where re-spaced columns meet an armhole corner) is no fabric: its ratio
    # says nothing (0.1 mm -> 0.19 mm read as stretch 1.87, A144)
    st = np.where(rest_len < MIN_EDGE_M, 1.0, st)
    worst = co0[edges[int(st.argmax())]].mean(0)
    worst_at = {"z": round(float(worst[2]), 3),
                "deg": round(math.degrees(math.atan2(worst[1] - centre[1], worst[0] - centre[0])) % 360, 1),
                "over_1_3": int((st > 1.3).sum()), "short_edges": int((rest_len < MIN_EDGE_M).sum()),
                "over_at": [[round(float(x), 2) for x in co0[e].mean(0)] for e in edges[np.argsort(-st)[:8]]], "rest_mm": round(float(rest_len[int(st.argmax())]) * 1000, 1),
                "x": round(float(worst[0]), 3), "y": round(float(worst[1]), 3)}
    n_single = len(me.vertices)
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
    views = {"view_front": inp["front"], "view_back": inp["back"]}
    bake_info = {}
    if bod:
        deg, bco_, bnr_, sil = bake_pose(arm, obj, views)
        bake_info = {"arm_deg": deg, **sil}
        tex = gd.project_bake(obj, views, out / "template_atlas.png", size=1024, co=bco_, nr=bnr_)
    else:
        tex = gd.project_bake(obj, views, out / "template_atlas.png", size=1024)
    tex.update(bake_info)
    tex["wall_s"] = round(time.time() - t_bake, 2)
    edges2 = gd.edges_of(obj)
    rest2 = np.linalg.norm(co2[edges2[:, 0]] - co2[edges2[:, 1]], axis=1)
    rim = gd.boundary_verts(obj)
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
            "bodice": binfo, "neck": neck, "lower_layers": len(lower),
            "drape": {"cpu_s": cpu, "wall_s": wall, "pin_drift_mm": drift,
                      "stretch_max": round(float(st.max()), 3), "stretch_at": worst_at, "stretch_p99": round(float(np.percentile(st, 99)), 3),
                      "quality": int(prm.get("drape_quality") or fab["quality"])},
            "weights": weights, "shapes": {"wall_s": shape_wall, **shape_info}, "collider_s": list(gd.COLLIDER_S), "pose_shapes": pose_shapes,
            "hem_verts": int(len(hem)),
            "bake": tex, "draped": measured, "measure_wall_s": meas_s, "render_wall_s": round(render_s, 2),
            "script_wall_s": round(time.time() - t_all, 2), "script_cpu_s": round(time.process_time() - c_all, 2)}
    return gd._plain(data), outputs


def rest_world_local(obj, rest_world):
    """The bind-pose world coordinates in the object's own space."""
    inv = np.array(obj.matrix_world.inverted())
    return rest_world @ inv[:3, :3].T + inv[:3, 3]


if __name__ == "__main__":
    main(run)
