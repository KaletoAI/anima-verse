#!/usr/bin/env python3
"""Smoke: the geometric body cut under a fitted shoe (app/core/footwear_cut.py; plan
docs/superpowers/plans/2026-11-10-footwear-rigid-shoes.md Task 14; spec
docs/superpowers/specs/2026-11-10-footwear-rigid-shoes-design.md § 5.7 ``cut``, § 7.1) and the body-primitive
rewrite of app/core/glb_mesh.py (``body_primitive_arrays`` / ``rewrite_body_primitives``).

Usage:  ./.venv/bin/python scripts/smoke_footwear_cut.py

No storage, no world DB, no hub, no server: numpy on hand-built primitives and the synthetic meshes of
scripts/_footwear_fixtures.py.

A hand-built ``cut`` (X1-X5) uses the identity frame: Foot bind frame = identity, extension 0, toe counter 0,
so the cut frame IS the primitive's bind space (x forward, y up, z lateral). ``joints`` = {"leftfoot": I,
"lefttoebase": I}; every vertex 100 % LeftFoot.

Expected, by hand:
[X0] constants: CUT_VERSION 2 (the toe conform), THROAT_BAND_M 0.02, LATERAL_BAND_M 0.015, CLEARANCE_M 0.002,
     FADE_M 0.015, TOE_CLEARANCE_M 0.002, TOE_FADE_M 0.015, CUT_GATES {"deep_outside": ("max", 0.02), "visible_poke":
     ("max", 0.005), "throat_ledge_p95_mm": ("max", 4.0), "toe_conform_m": ("max", 0.025)}.
[X1] open cylinder r 0.05 about +y, 64 segments x 21 rings (y = 0, 0.01, ..., 0.20), 1344 vertices, 20 bands x
     64 quads x 2 = 2560 triangles; flat cap y = 0.055 over the stations, footprint disc r 0.06 (every vertex inside
     the prism, its half-width 0.06 - 0.002 > 0.05: no slimming), no throat. Rings 0..5 (y <= 0.05) lie below the cap: bands 0..4
     are removed whole (5 x 128 = 640), band 5 (y 0.05..0.06) is bisected (128 faces), bands 6..19 stay (14 x 128
     = 1792). A bisected quad (a, b on ring 5; c above b, d above a; triangles (a, d, b), (a, c, d), wound outward)
     gets a new vertex on each vertical edge and on the diagonal a-d: (a, d, b) has two removed vertices and keeps
     one triangle, (a, c, d) has one and keeps a quad (2 triangles) -> 3 triangles per quad, 192 for the band ->
     remaining triangles 1792 + 192 = 1984 (NOT the brief's 14*64*2 + 64*2 = 1920, which counts the bisected band
     as two triangles per quad; the kept pentagon of a quad cut mid-band needs three). New vertices: 64 on the
     verticals + 64 on the diagonals = 128; vertices 1344 - 6*64 + 128 = 1088. Every new vertex lies at y = 0.055 (|dy| <=
     1e-9), the diagonal's cut point lies on the flat prism face between its two verticals, so the cut edge is a
     64-gon of perimeter 64 * 2 * 0.05 * sin(pi/64) = 0.314033 (the 128 points sorted by angle, collinear
     mid-edge points add nothing). min y of the kept vertices = 0.055. New vertices are weighted 100 % LeftFoot
     (union of two identical influences). Attributes lerp at t = 0.5 on every cut edge (ring 5 -> 6 crosses
     0.055 at the middle): TEXCOORD_0 v = 5.5/20 = 0.275; a morph target with delta (0, 0.001 j, 0) gives
     0.0055 on every new vertex; the recomputed normal of a new vertex is the flat face normal (radial within
     cos(pi/64) = 0.99880 of the vertex direction).
[X2] sloped cap y = 0.055 + 0.08 x (stations [-0.1, 0.047], [0.1, 0.063]): every new vertex lies ON the cap
     (|y - (0.055 + 0.08 x)| <= 1e-9) - the per-vertex staircase of spike v4 deviated up to one ring (0.01).
[X3] slimming on a box foot x in [-0.06, 0.19], z = +-0.0425 (the fixture's half-width), y levels 0, 0.005, 0.01,
     0.015, 0.0225, 0.03, 0.04; cap at y = 0 (the sole: g = 0 keeps, nothing is removed), the footprint a rectangle
     z = +-0.03895 (the upper's inner half-width = the fixture insole's 0.0779/2, midline 0) -> target 0.03895 -
     0.002 = 0.036950, stations x_min = -0.1 so the heel seat (x_min + 0.04 =
     -0.06) is the box's heel back and the 10 mm smoothing of the station factor ends before x = -0.05. For x >=
     -0.05: vertices from the sole to cap + 0.015 end at |z| = 0.036950; at cap + 0.015 + 0.0075 = 0.0225 (mid-fade)
     |z| = 0.0425 - 0.5 * (0.0425 - 0.036950) = 0.039725; at y >= cap + 0.03 unchanged (0.0425); the interior columns
     (|z| = 0.02125) scale by the same factor 0.86941 -> 0.018475 in the band; x unchanged; share taken
     1 - 0.03695/0.0425 = 0.1306 <= 0.18 (stats slim_share.left).
[X4] throat conform: throat front x_t = 0.10, vamp edge y = 0.05; cap 0.03 behind it. A vertex 0.01 behind the
     throat front and 0.008 above the vamp edge (0.09, 0.058) moves down by 0.008 * (1 - smoothstep(0, 0.02,
     0.01)) = 0.008 * 0.5 = 0.004 -> y 0.054; at the throat front (0.10, 0.058) fully onto the edge -> 0.05 (kept:
     it sits on the cap, g = 0); 0.03 behind (0.07, 0.058) unchanged; below the edge (0.09, 0.045) unchanged.
[X5] a two-primitive GLB (prim 0 = the X1 cylinder with NORMAL, TEXCOORD_0, JOINTS_0 u16, WEIGHTS_0, u32 indices
     and one morph target; prim 1 = a 4-triangle patch with POSITION + indices; skin 0 with 2 joints):
     body_primitive_arrays gives the two Prims back (prim 0 == the cylinder arrays); rewrite_body_primitives with
     {0: the X1 result} keeps prim 1's accessor bytes identical and the skin's inverse bind matrices; prim 0 reads
     back as the cut Prim (positions within float32); the BIN chunk shrinks by exactly the removed vertex data:
     per vertex 12 + 12 + 8 + 8 + 16 + 12 (target) = 68 bytes, per face 12 -> old 1344*68 + 2560*12 = 122112, new
     1088*68 + 1984*12 = 97792, difference 24320 (every view is a multiple of 4, no padding changes); the file is
     shorter.
[X6] cut_description on the fixture fit (foot_body_glb + the wedge pump, fit_pair at cap 1.10; k = 0.8853366,
     width factor 1.10): both sides present with the body's joint names; the frame round trip: the fit's Foot-rigid
     shoe vertices (ToeBase weight 0) mapped by frame @ inv(J_LeftFoot) land on the raw wedge scaled by (k, k,
     1.1 k) within 1e-6 (the wedge's own frame is the identity); the throat front = the first station with a roof
     in the front half: station 166 at 0.1805858 raw -> x 0.159883 m, vamp edge = the wall top there (the walls
     and the roof at h + 0.03 = 0.04) k = 0.035413 m (within 1e-5); the cap behind it = the wall top (h(x) +
     0.03) k, cut exactly on every station plane and linear between the 240 stations: at 0.0999 raw (h = 0.09 -
     0.8 * 0.0499 = 0.05008) 0.08008 k = 0.070898 (within 1e-5); the footprint half-width at the ball (the
     slimming's target before the clearance) 0.04 k 1.1 = 0.038955 (within 1e-5); footprint x from 0 to 0.26 k =
     0.230188, z +-0.04 k 1.1 = +-0.038955; conform
     = the constants verbatim (slim + toe); toe_box = {x_from: the throat front, headroom 0.03, slack 0.015};
     vamp_inner = one [x, y] per roofed station with a profile (the wedge: roofed from the throat front on, 240 - 166
     = 74 stations), y = (profile + cavity) k — ON the cap there (within 1e-9): the fixture's roof is a sheet
     without thickness, so its inner surface is its outer one; the whole cut round-trips through json.
[X9] toe conform (CUT_VERSION 2) on a box foot x in [-0.06, 0.19] (10 mm steps), z = +-0.0425, levels 0, 0.01,
     0.02, 0.03 (the toe height 0.03), every vertex 100 % LeftFoot. Cut: cap 0.02 everywhere (wall top behind the
     throat and the vamp's outer surface in front), throat front x_t = 0.10 (vamp edge 0.02), vamp_inner 0.017
     (a 3 mm shell), footprint z = +-0.05 up to x = 0.10 (0.048 after the clearance > 0.0425: no slimming
     behind) narrowing linearly to +-0.01 at x = 0.19 (half-width hw(x) = 0.05 - 0.04 (x - 0.10) / 0.09), x_min
     -0.1 / x_max 0.3, the conform constants. By hand, after conform_body (positions before the removal):
     - vertical, x >= 0.12 (the ramp (x - 0.10) / 0.015 is 1 from 0.115): every vertex above the target 0.017 -
       0.002 = 0.015 lands on it (0.03 and 0.02 -> 0.015; 0.01 and 0 stay): push 0.03 - 0.015 = 0.015 = toe height -
       vamp inner + clearance = stats toe_conform.left (<= 0.025, the gate); x = 0.11 (ramp 2/3): 0.03 -> onto the
       cap 0.02 first (step 2's landing) then 2/3 of (0.02 - 0.015) -> 0.016667, 0.02 -> 0.016667, 0.01 stays;
       x = 0.10 (the throat front, d = 0): the throat conform lands 0.03 on the edge 0.02, nothing else.
     - lateral: x = 0.11: hw 0.045556 - 0.002 > 0.0425 -> |z| stays 0.0425; x = 0.12: hw 0.041111 -> target
       0.039111: the slimming's station factor is linear in x there, so its +-5 mm smoothing returns the station
       value 0.039111 / 0.0425 = 0.92026 and |z| = 0.039111; the toe clamp has nothing left to do (it agrees:
       +-1e-6); x = 0.19: the slimming is capped at 1 - 0.18 (|z| 0.03485), the toe clamp takes it the rest of the
       way to hw - 0.002 = 0.008 (within 1e-9). Stats toe_pull.left > 0.
     - after apply_cut nothing remains in front of the throat (every conformed toe vertex lies inside the toe box's
       prism + slack below the cap + headroom); behind it the vertices above the cap 0.02 remain (levels 0.03 and,
       in the throat band, their conformed heights) -> the box is not empty. On 6faafae0 the vertices from x = 0.17
       on stayed beyond the slack (|z| 0.03485 > hw + 0.015 once hw < 0.01985, i.e. x > 0.1678: 76 vertices with
       the bisection points, measured) and the stats had no toe_conform.
[X7] apply_cut + cut_gates on a CLOSED flat clog (the wedge is open at the toe-box front, so a flood fill
     enters it, and its sloped insole floats the straight box over the arch — neither is hand-derivable): sole
     solid x in [0.01, 0.26] with its top (the insole) at 0.01, a floor plate from x = 0, side walls z = +-0.04
     from the ground to 0.05 over x < 0.04 (the heel counter: the rear end must stand taller than the toe box
     for the analysis' heel rule, a flat insole cannot flip the frame), 0.035 behind the throat, 0.04 from
     x = 0.1825 on, a roof at 0.04 over [0.1825, 0.26], a heel-counter face at x = 0, the sole's end at 0.01,
     the toe-box front at 0.26 (walls tessellated every 0.0025). Fit: the insole starts at
     the first station >= 0.01, station 10 at 0.010879 raw, and runs flat to 0.26; the roof holds the toes (0.03
     k >= 0.02) -> arc 0.249121, k = 0.255 / 0.249121 = 1.023599; a flat chord -> extension 0, toe counter 0,
     lift = 0.01 k (the sole onto the insole); toe room = +5 mm by construction (arc = foot + ALLOW_M); insole
     width at the ball 0.08 k = 0.081888 -> width needed = 0.085 / 0.081888 = 1.0380 = the factor (under the
     cap) -> the widened insole half-width is 0.0425 = the foot's, target 0.0405, slim factor 0.0405 / 0.0425 =
     0.952941, share 0.047059 (both sides). Cut: throat front = the first roofed station >= 0.1825, station 168
     at 0.182762 raw -> 0.187075 m; vamp edge 0.04 k = 0.040944; cap behind it 0.035 k = 0.035826. In the cut
     frame the box runs x 0.011136 (= x0 k) .. 0.261136 inside the prism 0 .. 0.266136, |z| <= 0.0405 inside
     +-0.0425, y from 0.010236 (on the insole) to 0.030236 — below both caps everywhere, below the vamp edge
     (no throat move): every foot vertex goes, 2 x 516 = 1032 faces removed, nothing bisected, nothing new; the
     two leg columns (identity-weighted, y >= 0.110236 > cap) remain: 24 faces, 48 vertices. Gates: should be
     enclosed = all 384 foot vertices per side (below the wall top - 2 mm, in front of the heel), none outside
     (the shoe is closed; the slimmed box sits 2 mm inside the walls) -> deep_outside 0; no foot vertex remains
     -> visible_poke 0 (visible_n 0); throat ledge 0; every gate passes, no poke in any region.
[X8] the wedge fit (pitched 24.29 deg, counter-turned, the box floating over the arch): structure only — slim
     share 0.13047 per side (1 - (0.038955 - 0.002) / 0.0425: X3's box against X6's footprint half-width); both
     sides bisect (the box crosses the sloped wall top); every new vertex lies on its own side's cut surface
     (|g| <= 1e-9 in that side's cut frame) or on the throat-front wall x = x_t, where g jumps by the toe-box
     headroom and the bisection converges onto the jump (the last n_right vertices are the right side's, the
     n_left before them the left's); faces valid, no dangling vertex; the new vertices' weights sum to 1.
"""
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

FAILS = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global FAILS
    if not ok:
        FAILS += 1
    print(f"  [{'ok' if ok else 'FAIL'}] {label}{(' - ' + detail) if detail else ''}")


def near(a, b, tol) -> bool:
    return bool(np.all(np.abs(np.asarray(a, np.float64) - np.asarray(b, np.float64)) <= tol))


try:
    from app.core import footwear_cut as fc
    from app.core.footwear_cut import Prim
    from app.core import glb_mesh
except ImportError as exc:  # the module does not exist yet
    print(f"FAIL: {exc}")
    sys.exit(1)

I4 = np.eye(4)
JOINTS = {"leftfoot": I4.copy(), "lefttoebase": I4.copy()}
JOINT_NAMES = ["LeftFoot", "LeftToeBase"]


def _cut(cap, *, footprint, throat=None, stations=None):
    side = {
        "foot_joint": "LeftFoot", "toe_joint": "LeftToeBase", "frame": I4.tolist(),
        "extension": {"axis_local": [0.0, 0.0, -1.0], "deg": 0.0},
        "toe_counter": {"axis_local": [0.0, 0.0, -1.0], "deg": 0.0},
        "topline": [], "cap": cap, "footprint": footprint, "throat": throat,
        "stations": stations or {"heel_x": -0.1, "ball_x": 0.05, "x_min": -0.1, "x_max": 0.1},
        "conform": {"throat_band_m": fc.THROAT_BAND_M, "lateral_band_m": fc.LATERAL_BAND_M,
                    "slim": {"clearance_m": fc.CLEARANCE_M, "fade_m": fc.FADE_M, "max_share": 0.18}},
    }
    return {"version": fc.CUT_VERSION, "sides": {"left": side}}


def _disc(r, n=64):
    a = np.linspace(0, 2 * math.pi, n, endpoint=False)
    return np.stack([r * np.cos(a), r * np.sin(a)], 1).tolist()


def cylinder(seg=64, rings=21, r=0.05):
    a = 2 * math.pi * np.arange(seg) / seg
    P, N, U, T = [], [], [], []
    for j in range(rings):
        for i in range(seg):
            P.append([r * math.cos(a[i]), 0.01 * j, r * math.sin(a[i])])
            N.append([math.cos(a[i]), 0.0, math.sin(a[i])])
            U.append([i / seg, j / (rings - 1)])
            T.append([0.0, 0.001 * j, 0.0])
    F = []
    for j in range(rings - 1):
        for i in range(seg):
            a0, b0 = j * seg + i, j * seg + (i + 1) % seg
            c0, d0 = a0 + seg, b0 + seg
            F.append([a0, d0, b0])          # wound outward (+radial), like the stored normals
            F.append([a0, c0, d0])
    n = len(P)
    jn = np.zeros((n, 4), np.int64)
    w = np.zeros((n, 4))
    w[:, 0] = 1.0
    return Prim(positions=np.array(P), faces=np.array(F, np.int64),
                attributes={"NORMAL": np.array(N), "TEXCOORD_0": np.array(U)}, joints=jn, weights=w,
                targets=[{"POSITION": np.array(T)}], joint_names=list(JOINT_NAMES))


def box(levels, x0=-0.06, x1=0.19, hw=0.0425):
    xs = np.arange(x0, x1 + 1e-9, 0.01)
    P, F = [], []

    def grid(pts_fn, nu, nv):
        base = len(P)
        for i in range(nu + 1):
            for j in range(nv + 1):
                P.append(pts_fn(i, j))
        for i in range(nu):
            for j in range(nv):
                a = base + i * (nv + 1) + j
                b = a + nv + 1
                F.append([a, b, b + 1])
                F.append([a, b + 1, a + 1])
    for z in (-hw, hw):
        grid(lambda i, j, z=z: [xs[i], levels[j], z], len(xs) - 1, len(levels) - 1)
    zc = np.linspace(-hw, hw, 5)
    for y in (levels[0], levels[-1]):
        grid(lambda i, j, y=y: [xs[i], y, zc[j]], len(xs) - 1, 4)
    n = len(P)
    jn = np.zeros((n, 4), np.int64)
    w = np.zeros((n, 4))
    w[:, 0] = 1.0
    return Prim(positions=np.array(P), faces=np.array(F, np.int64), attributes={}, joints=jn, weights=w,
                targets=[], joint_names=list(JOINT_NAMES))


def two_prim_glb(prim: Prim) -> bytes:
    """A GLB: mesh 0 with the cylinder (prim 0) and a 4-triangle patch (prim 1), node skinned to skin 0."""
    blob = bytearray()
    views, accessors = [], []

    def add(array, comp, typ, target=None, minmax=False):
        data = np.ascontiguousarray(array).tobytes()
        while len(blob) % 4:
            blob.append(0)
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(data), **({"target": target} if target else {})})
        blob.extend(data)
        acc = {"bufferView": len(views) - 1, "componentType": comp, "count": len(array), "type": typ}
        if minmax:
            acc["min"], acc["max"] = np.asarray(array).min(0).tolist(), np.asarray(array).max(0).tolist()
        accessors.append(acc)
        return len(accessors) - 1

    p0 = {"attributes": {
        "POSITION": add(prim.positions.astype("<f4"), 5126, "VEC3", 34962, True),
        "NORMAL": add(prim.attributes["NORMAL"].astype("<f4"), 5126, "VEC3", 34962),
        "TEXCOORD_0": add(prim.attributes["TEXCOORD_0"].astype("<f4"), 5126, "VEC2", 34962),
        "JOINTS_0": add(prim.joints.astype("<u2"), 5123, "VEC4", 34962),
        "WEIGHTS_0": add(prim.weights.astype("<f4"), 5126, "VEC4", 34962)},
        "indices": add(prim.faces.reshape(-1).astype("<u4"), 5125, "SCALAR", 34963), "mode": 4,
        "targets": [{"POSITION": add(prim.targets[0]["POSITION"].astype("<f4"), 5126, "VEC3", 34962, True)}]}
    patch = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0.5, 0.5, 0.2]], "<f4")
    pf = np.array([[0, 1, 4], [1, 2, 4], [2, 3, 4], [3, 0, 4]], "<u2")
    p1 = {"attributes": {"POSITION": add(patch, 5126, "VEC3", 34962, True)},
          "indices": add(pf.reshape(-1), 5123, "SCALAR", 34963), "mode": 4}
    ibm = np.stack([np.eye(4, dtype="<f4").T for _ in JOINT_NAMES])
    ibm_acc = add(ibm.reshape(len(JOINT_NAMES), 16), 5126, "MAT4")
    while len(blob) % 4:
        blob.append(0)
    gltf = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0, 1]}],
            "nodes": [{"name": "Body", "mesh": 0, "skin": 0}, {"name": "LeftFoot", "children": [2]},
                      {"name": "LeftToeBase"}],
            "meshes": [{"name": "mesh", "primitives": [p0, p1], "weights": [0.0]}],
            "skins": [{"joints": [1, 2], "inverseBindMatrices": ibm_acc}],
            "bufferViews": views, "accessors": accessors, "buffers": [{"byteLength": len(blob)}]}
    return glb_mesh.pack_glb(gltf, bytes(blob))


def accessor_bytes(glb: bytes, index: int) -> bytes:
    from app.core.model_validate import parse_glb
    parsed = parse_glb(glb)
    acc = parsed["gltf"]["accessors"][index]
    view = parsed["gltf"]["bufferViews"][acc["bufferView"]]
    start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    return bytes(parsed["bin"][start:start + view["byteLength"] - acc.get("byteOffset", 0)])


def main() -> int:
    print("[X0] constants")
    check("CUT_VERSION 2", fc.CUT_VERSION == 2)
    check("bands", (fc.THROAT_BAND_M, fc.LATERAL_BAND_M, fc.CLEARANCE_M, fc.FADE_M, fc.TOE_CLEARANCE_M, fc.TOE_FADE_M)
          == (0.02, 0.015, 0.002, 0.015, 0.002, 0.015))
    check("CUT_GATES", fc.CUT_GATES == {"deep_outside": ("max", 0.02), "visible_poke": ("max", 0.005), "toe_conform_m": ("max", 0.025),
                                         "throat_ledge_p95_mm": ("max", 4.0)})

    print("[X1] flat cap on the cylinder")
    cyl = cylinder()
    check("cylinder 1344 vertices / 2560 faces", (len(cyl.positions), len(cyl.faces)) == (1344, 2560))
    cut1 = _cut([[-0.1, 0.055], [0.1, 0.055]], footprint=_disc(0.06))
    out, stats = fc.apply_cut(cyl, cut1, JOINTS)
    check("stats removed 640 / bisected 128 / new 128",
          (stats["removed_faces"], stats["bisected_faces"], stats["new_vertices"]) == (640, 128, 128), str(stats))
    check("remaining triangles 1984", len(out.faces) == 1984, str(len(out.faces)))
    check("vertices 1088", len(out.positions) == 1088, str(len(out.positions)))
    check("min y of the kept vertices 0.055", abs(float(out.positions[:, 1].min()) - 0.055) <= 1e-9)
    new = out.positions[1344 - 384:] if len(out.positions) == 1088 else out.positions[-128:]
    check("every new vertex at y = 0.055", near(new[:, 1], 0.055, 1e-9))
    ang = np.arctan2(new[:, 2], new[:, 0])
    ring = new[np.argsort(ang)]
    per = float(np.sum(np.linalg.norm(np.roll(ring, -1, 0) - ring, axis=1)))
    check("cut edge perimeter 0.314033", abs(per - 0.314033) <= 2e-6, f"{per:.6f}")
    nj, nw = out.joints[-128:], out.weights[-128:]
    check("new vertices 100 % LeftFoot", bool(np.all(nj[:, 0] == 0) and near(nw[:, 0], 1.0, 1e-12)
                                               and near(nw[:, 1:], 0.0, 1e-12)))
    check("TEXCOORD_0 v lerp 0.275", near(out.attributes["TEXCOORD_0"][-128:, 1], 0.275, 1e-9))
    check("morph delta lerp 0.0055", near(out.targets[0]["POSITION"][-128:, 1], 0.0055, 1e-9))
    nn = out.attributes["NORMAL"][-128:]
    rad = new.copy()
    rad[:, 1] = 0
    rad /= np.linalg.norm(rad, axis=1, keepdims=True)
    cosang = np.sum(nn * rad, axis=1)
    check("recomputed normals radial within cos(pi/64)", bool(np.all(cosang >= math.cos(math.pi / 64) - 1e-9)),
          f"min {cosang.min():.5f}")
    check("faces index the compacted vertices", int(out.faces.max()) < len(out.positions) and int(out.faces.min()) >= 0)
    used = np.zeros(len(out.positions), bool)
    used[out.faces.ravel()] = True
    check("no dangling vertex", bool(used.all()))

    print("[X2] sloped cap")
    cut2 = _cut([[-0.1, 0.047], [0.1, 0.063]], footprint=_disc(0.06))
    out2, stats2 = fc.apply_cut(cyl, cut2, JOINTS)
    nv = stats2["new_vertices"]
    new2 = out2.positions[-nv:]
    dev = new2[:, 1] - (0.055 + 0.08 * new2[:, 0])
    check("every cut vertex ON the sloped cap (|d| <= 1e-9)", nv > 0 and float(np.abs(dev).max()) <= 1e-9,
          f"n {nv} max {np.abs(dev).max() if nv else 0:.2e}")

    print("[X3] forefoot slimming on the box foot")
    levels = [0.0, 0.005, 0.01, 0.015, 0.0225, 0.03, 0.04]
    bx = box(levels)
    rect = [[-0.1, -0.1], [0.3, -0.1], [0.3, 0.1], [-0.1, 0.1]]
    narrow = [[-0.1, -0.03895], [0.3, -0.03895], [0.3, 0.03895], [-0.1, 0.03895]]
    cut3 = _cut([[-0.1, 0.0], [0.3, 0.0]], footprint=narrow,
                stations={"heel_x": -0.1, "ball_x": 0.13, "x_min": -0.1, "x_max": 0.3})
    out3, stats3 = fc.apply_cut(bx, cut3, JOINTS)
    check("nothing removed at a cap on the sole", stats3["removed_faces"] == 0 and stats3["bisected_faces"] == 0, str(stats3))
    P0, P3 = bx.positions, out3.positions
    sel = P0[:, 0] >= -0.05 - 1e-9
    outer = sel & (np.abs(P0[:, 2]) > 0.0425 - 1e-9)
    band = outer & (P0[:, 1] <= 0.015 + 1e-9)
    check("band |z| -> 0.036950", band.any() and near(np.abs(P3[band, 2]), 0.036950, 1e-6),
          f"{np.abs(P3[band, 2]).min():.6f}..{np.abs(P3[band, 2]).max():.6f}")
    mid = outer & (np.abs(P0[:, 1] - 0.0225) <= 1e-9)
    check("mid-fade |z| -> 0.039725", mid.any() and near(np.abs(P3[mid, 2]), 0.039725, 1e-6),
          f"{np.abs(P3[mid, 2]).min() if mid.any() else -1:.6f}")
    top = outer & (P0[:, 1] >= 0.03 - 1e-9)
    check("above cap + 0.03 unchanged", top.any() and near(np.abs(P3[top, 2]), 0.0425, 1e-9))
    inner = sel & (np.abs(np.abs(P0[:, 2]) - 0.02125) <= 1e-9) & (P0[:, 1] <= 0.015 + 1e-9)
    check("interior columns scale by the same factor (0.018475)", inner.any() and near(np.abs(P3[inner, 2]), 0.018475, 1e-6))
    check("x and y untouched by the slimming", near(P3[:, [0, 1]], P0[:, [0, 1]], 1e-12))
    check("slim share 0.1306", abs(stats3["slim_share"]["left"] - 0.1306) <= 1e-4, str(stats3.get("slim_share")))

    print("[X4] throat conform")
    pts = np.array([[0.09, 0.058, 0.0], [0.10, 0.058, 0.0], [0.07, 0.058, 0.0], [0.09, 0.045, 0.0],
                    [0.085, 0.058, 0.01], [0.095, 0.058, 0.01]])
    faces = np.array([[0, 4, 5], [0, 5, 1], [2, 4, 0], [3, 0, 1]], np.int64)
    pr = Prim(positions=pts.copy(), faces=faces, attributes={}, joints=np.zeros((6, 4), np.int64),
              weights=np.tile([1.0, 0, 0, 0], (6, 1)), targets=[], joint_names=list(JOINT_NAMES))
    cap4 = [[0.0, 0.03], [0.0999, 0.03], [0.10, 0.05], [0.3, 0.05]]
    cut4 = _cut(cap4, footprint=rect, throat={"x": 0.10, "y": 0.05},
                stations={"heel_x": -0.1, "ball_x": 0.05, "x_min": -0.1, "x_max": 0.3})
    out4, stats4 = fc.apply_cut(pr, cut4, JOINTS)
    check("nothing removed", stats4["removed_faces"] == 0 and len(out4.positions) == 6, str(stats4))
    P4 = out4.positions
    check("0.01 behind the throat front: 0.058 -> 0.054", abs(P4[0, 1] - 0.054) <= 1e-9, f"{P4[0, 1]:.6f}")
    check("at the throat front: onto the vamp edge 0.05", abs(P4[1, 1] - 0.05) <= 1e-9, f"{P4[1, 1]:.6f}")
    check("0.03 behind: unchanged", abs(P4[2, 1] - 0.058) <= 1e-12)
    check("below the edge: unchanged", abs(P4[3, 1] - 0.045) <= 1e-12)
    check("x, z untouched", near(P4[:, [0, 2]], pts[:, [0, 2]], 1e-12))

    print("[X5] body_primitive_arrays / rewrite_body_primitives")
    glb = two_prim_glb(cyl)
    prims = glb_mesh.body_primitive_arrays(glb)
    check("two primitives", len(prims) == 2)
    p0 = prims[0]
    check("prim 0 == the cylinder (f32)", near(p0.positions, cyl.positions.astype("<f4"), 0) and np.array_equal(p0.faces, cyl.faces)
          and set(p0.attributes) == {"NORMAL", "TEXCOORD_0"} and np.array_equal(p0.joints, cyl.joints)
          and near(p0.weights, cyl.weights, 0) and len(p0.targets) == 1 and near(p0.targets[0]["POSITION"], cyl.targets[0]["POSITION"].astype("<f4"), 0))
    check("prim 0 joint names", list(p0.joint_names) == JOINT_NAMES)
    check("prim 1 has no skin data", len(prims[1].positions) == 5 and len(prims[1].faces) == 4)
    cut_p0, st = fc.apply_cut(p0, cut1, JOINTS)
    new_glb = glb_mesh.rewrite_body_primitives(glb, {0: cut_p0})
    from app.core.model_validate import parse_glb
    old, nw_ = parse_glb(glb), parse_glb(new_glb)
    check("file shorter", len(new_glb) < len(glb), f"{len(glb)} -> {len(new_glb)}")
    check("BIN shrinks by 24320", len(old["bin"]) - len(nw_["bin"]) == 24320, f"{len(old['bin']) - len(nw_['bin'])}")
    op1, np1 = old["gltf"]["meshes"][0]["primitives"][1], nw_["gltf"]["meshes"][0]["primitives"][1]
    same = all(accessor_bytes(glb, op1["attributes"][k]) == accessor_bytes(new_glb, np1["attributes"][k]) for k in op1["attributes"]) \
        and accessor_bytes(glb, op1["indices"]) == accessor_bytes(new_glb, np1["indices"])
    check("untouched prim 1: accessor bytes identical", same)
    old_ibm = accessor_bytes(glb, old["gltf"]["skins"][0]["inverseBindMatrices"])
    new_ibm = accessor_bytes(new_glb, nw_["gltf"]["skins"][0]["inverseBindMatrices"])
    check("skin IBM bytes identical", old_ibm == new_ibm)
    back = glb_mesh.body_primitive_arrays(new_glb)
    b0 = back[0]
    check("prim 0 reads back as the cut Prim", len(back) == 2 and near(b0.positions, cut_p0.positions, 1e-6)
          and np.array_equal(b0.faces, cut_p0.faces) and near(b0.weights, cut_p0.weights, 1e-6)
          and np.array_equal(b0.joints, cut_p0.joints) and near(b0.targets[0]["POSITION"], cut_p0.targets[0]["POSITION"], 1e-6)
          and near(b0.attributes["TEXCOORD_0"], cut_p0.attributes["TEXCOORD_0"], 1e-6))
    check("no orphan accessor / view", len(nw_["gltf"]["accessors"]) == len(old["gltf"]["accessors"])
          and len(nw_["gltf"]["bufferViews"]) == len(old["gltf"]["bufferViews"]))
    check("body_arrays and joint_bind_matrices still read", len(glb_mesh.body_arrays(new_glb).positions) == 1088 + 5
          and set(glb_mesh.joint_bind_matrices(new_glb)) == {"leftfoot", "lefttoebase"})

    print("[X6] cut_description on the fixture fit")
    from _footwear_fixtures import clog, wedge, shoe_garment, foot_body_glb
    from app.core import footwear_fit as ff, footwear_insole as fi
    Pw, Fw = wedge()
    ins = fi.analyse_arrays(Pw, Fw)
    bglb = foot_body_glb()
    body = glb_mesh.body_arrays(bglb)
    joints = glb_mesh.joint_bind_matrices(bglb)
    fit = ff.fit_pair(ins, shoe_garment(Pw, Fw), body, joints)
    check("fixture fit ok", fit.ok, str(fit.reasons))
    k = fit.record["scale"]["k_m_per_unit"]
    cut = fc.cut_description(fit, ins)
    check("version + both sides", cut["version"] == 2 and set(cut["sides"]) == {"left", "right"})
    L = cut["sides"]["left"]
    check("joint names", (L["foot_joint"], L["toe_joint"]) == ("LeftFoot", "LeftToeBase"))
    frame = np.asarray(L["frame"], np.float64)
    shoe = fit.shoes["left"]
    rigid = shoe.weights[:, 1] == 0
    Qm = Pw * np.array([k, k, 1.1 * k])
    mapped = (shoe.positions[rigid] @ (frame @ np.linalg.inv(joints["leftfoot"]))[:3, :3].T
              + (frame @ np.linalg.inv(joints["leftfoot"]))[:3, 3])
    check("frame round trip: Foot-rigid shoe -> raw wedge x (k, k, 1.1k)", near(mapped, Qm[rigid], 1e-6),
          f"max {np.abs(mapped - Qm[rigid]).max():.2e}")
    check("throat front x 0.159883 / vamp edge 0.035413", near(L["throat"]["x"], 0.1805858 * k, 1e-5)
          and near(L["throat"]["y"], 0.04 * k, 1e-5), str(L["throat"]))
    cap = np.asarray(L["cap"], np.float64)
    at = float(np.interp(0.0999 * k, cap[:, 0], cap[:, 1]))
    check("cap behind the throat = the wall top (0.070898 at 0.0999 raw)", abs(at - 0.08008 * k) <= 1e-5, f"{at:.6f}")
    hw = float(fc._Side(L).hw(np.array([fit.record["diagnostics"]["left"]["ball_x_m"]]))[0])
    check("footprint half-width at the ball 0.038955", abs(hw - 0.04 * k * 1.1) <= 1e-5, f"{hw:.6f}")
    fp = np.asarray(L["footprint"], np.float64)
    check("footprint x 0..0.230188, z +-0.038955", near([fp[:, 0].min(), fp[:, 0].max()], [0.0, 0.26 * k], 1e-6)
          and near([fp[:, 1].min(), fp[:, 1].max()], [-0.044 * k, 0.044 * k], 1e-6))
    check("conform constants", L["conform"] == {"throat_band_m": 0.02, "lateral_band_m": 0.015,
                                                "slim": {"clearance_m": 0.002, "fade_m": 0.015, "max_share": 0.18},
                                                "toe": {"clearance_m": 0.002, "fade_m": 0.015}})
    vi = np.asarray(L["vamp_inner"], np.float64).reshape(-1, 2)
    check("vamp_inner: 74 roofed stations, on the cap (the fixture's roof is a sheet: inner = outer)", len(vi) == 74
          and bool(np.all(vi[:, 0] >= L["throat"]["x"] - 1e-9))
          and near(vi[:, 1], np.interp(vi[:, 0], np.asarray(L["cap"])[:, 0], np.asarray(L["cap"])[:, 1]), 1e-9), str(len(vi)))
    check("toe box from the throat front, headroom 0.03, slack 0.015",
          L["toe_box"] == {"x_from": L["throat"]["x"], "headroom_m": 0.03, "slack_m": 0.015}, str(L["toe_box"]))
    check("topline polyline present", len(L["topline"]) > 100 and len(L["topline"][0]) == 3)
    check("json round trip", json.loads(json.dumps(cut)) == cut)
    R = cut["sides"]["right"]
    check("right side mirrors to the same cut-frame geometry", near(R["cap"], L["cap"], 1e-9) and near(R["footprint"], L["footprint"], 1e-9))

    print("[X9] toe conform on a box foot")
    bx9 = box([0.0, 0.01, 0.02, 0.03])
    fp9 = [[-0.1, -0.05], [0.10, -0.05], [0.19, -0.01], [0.3, -0.01], [0.3, 0.01], [0.19, 0.01], [0.10, 0.05], [-0.1, 0.05]]
    cut9 = _cut([[-0.1, 0.02], [0.3, 0.02]], footprint=fp9, throat={"x": 0.10, "y": 0.02},
                stations={"heel_x": -0.1, "ball_x": 0.05, "x_min": -0.1, "x_max": 0.3})
    cut9["sides"]["left"]["vamp_inner"] = [[0.10, 0.017], [0.3, 0.017]]
    cut9["sides"]["left"]["toe_box"] = {"x_from": 0.10, "headroom_m": fc.VAMP_HEADROOM_M, "slack_m": fc.VAMP_SLACK_M}
    con9, info9 = fc.conform_body(bx9, cut9, JOINTS)
    P0, P9 = bx9.positions, con9.positions
    at = lambda x_, y_=None: (np.abs(P0[:, 0] - x_) <= 1e-9) & ((np.abs(P0[:, 1] - y_) <= 1e-9) if y_ is not None else True)  # noqa: E731
    check("x >= 0.12: 0.03 and 0.02 -> 0.015, 0.01 and 0 stay", near(P9[(P0[:, 0] >= 0.12 - 1e-9) & (P0[:, 1] >= 0.02 - 1e-9), 1], 0.015, 1e-9)
          and near(P9[(P0[:, 0] >= 0.12 - 1e-9) & (P0[:, 1] <= 0.01 + 1e-9), 1], P0[(P0[:, 0] >= 0.12 - 1e-9) & (P0[:, 1] <= 0.01 + 1e-9), 1], 1e-12))
    check("toe_conform.left 0.015 = toe height - vamp inner + clearance", abs(info9["toe_conform"]["left"] - 0.015) <= 1e-9, str(info9["toe_conform"]))
    check("x = 0.11 (ramp 2/3): 0.03 and 0.02 -> 0.016667, 0.01 stays", near(P9[at(0.11, 0.03), 1], 0.0166667, 1e-6)
          and near(P9[at(0.11, 0.02), 1], 0.0166667, 1e-6) and near(P9[at(0.11, 0.01), 1], 0.01, 1e-12))
    check("x = 0.10 (the front): 0.03 onto the edge 0.02", near(P9[at(0.10, 0.03), 1], 0.02, 1e-9))
    side9 = at(0.11) & (np.abs(P0[:, 2]) >= 0.0425 - 1e-9)
    check("x = 0.11: |z| stays 0.0425", near(np.abs(P9[side9, 2]), 0.0425, 1e-9))
    side9 = at(0.12) & (np.abs(P0[:, 2]) >= 0.0425 - 1e-9)
    check("x = 0.12: |z| 0.039111 (the slimming's linear station, the clamp agrees)", near(np.abs(P9[side9, 2]), 0.0391111, 1e-6),
          str(np.abs(P9[side9, 2]).min()) + ".." + str(np.abs(P9[side9, 2]).max()))
    side9 = at(0.19) & (np.abs(P0[:, 2]) >= 0.0425 - 1e-9)
    check("x = 0.19: |z| 0.008 (clamp past the slimming's 18 %)", near(np.abs(P9[side9, 2]), 0.008, 1e-9),
          str(np.abs(P9[side9, 2]).min()) + ".." + str(np.abs(P9[side9, 2]).max()))
    check("toe_pull.left > 0.02 (0.03485 - 0.008 = 0.02685 at the tip)", abs(info9["toe_pull"]["left"] - 0.02685) <= 1e-4, str(info9["toe_pull"]))
    check("x untouched", near(P9[:, 0], P0[:, 0], 1e-12))
    out9, st9 = fc.apply_cut(bx9, cut9, JOINTS)
    check("stats carry toe_conform / toe_pull", st9["toe_conform"] == info9["toe_conform"] and st9["toe_pull"] == info9["toe_pull"])
    check("nothing remains in front of the throat", bool(np.all(out9.positions[:, 0] <= 0.10 + 1e-9)), f"max x {out9.positions[:, 0].max():.4f}")
    check("the box is not empty behind it", len(out9.positions) > 0 and bool(np.any(out9.positions[:, 1] > 0.02 + 1e-9)), str(len(out9.positions)))

    print("[X7] apply_cut + cut_gates on the closed clog")
    Pc, Fc = clog()
    insc = fi.analyse_arrays(Pc, Fc)
    fitc = ff.fit_pair(insc, shoe_garment(Pc, Fc), body, joints)
    check("clog fit ok", fitc.ok, str(fitc.reasons))
    kc = fitc.record["scale"]["k_m_per_unit"]
    sl = fitc.record["sides"]["left"]
    check("k 1.023599", abs(kc - 1.023599) <= 2e-4, f"{kc:.6f}")
    check("extension 0, toe room 5.0 mm, width factor 1.0380",
          abs(sl["extension"]["deg"]) <= 1e-6 and abs(sl["toe_room_mm"] - 5.0) <= 0.05
          and abs(fitc.record["scale"]["width_factor"] - 1.0380) <= 2e-3,
          f"{sl['extension']['deg']} {sl['toe_room_mm']} {fitc.record['scale']['width_factor']}")
    cutc = fc.cut_description(fitc, insc)
    Lc = cutc["sides"]["left"]
    check("throat front 0.187075 / vamp edge 0.040944", near(Lc["throat"]["x"], 0.182762 * kc, 1e-4)
          and near(Lc["throat"]["y"], 0.04 * kc, 1e-5), str(Lc["throat"]))
    capc = np.asarray(Lc["cap"], np.float64)
    check("cap behind the throat 0.035826", abs(float(np.interp(0.10 * kc, capc[:, 0], capc[:, 1])) - 0.035 * kc) <= 1e-6)
    prim = glb_mesh.body_primitive_arrays(bglb)[0]
    after, st7 = fc.apply_cut(prim, cutc, joints)
    check("removed 1032 / bisected 0 / new 0", (st7["removed_faces"], st7["bisected_faces"], st7["new_vertices"]) == (1032, 0, 0), str(st7))
    check("slim share 0.047059 per side", near([st7["slim_share"]["left"], st7["slim_share"]["right"]], 0.047059, 1e-4), str(st7["slim_share"]))
    check("no throat move", st7["throat_moved"] == {"left": 0, "right": 0}, str(st7["throat_moved"]))
    check("only the two leg columns remain (24 faces, 48 vertices)", (len(after.faces), len(after.positions)) == (24, 48),
          f"{len(after.faces)} {len(after.positions)}")
    gates = fc.cut_gates(after, fitc.shoes, cutc, joints=joints, body_before=prim)
    g = gates["gates"]
    check("should-enclosed 384 per side, deep_outside 0", all(gates["sides"][s]["should_enclosed"] == 384
          and gates["sides"][s]["deep_outside"] == 0.0 for s in ("left", "right")),
          str({s: (gates["sides"][s]["should_enclosed"], gates["sides"][s]["deep_outside"]) for s in gates["sides"]}))
    check("visible_poke 0 (no foot vertex left)", all(gates["sides"][s]["visible_n"] == 0 and gates["sides"][s]["visible_poke"] == 0.0
          for s in ("left", "right")), str({s: gates["sides"][s]["visible_n"] for s in gates["sides"]}))
    check("throat ledge 0", g["throat_ledge_p95_mm"]["value"] == 0.0)
    check("all gates ok", gates["ok"] is True and gates["reasons"] == [], str(gates["reasons"]))
    check("no poke in any region", all(gates["sides"][s]["poke_by_region"] == {"heel": 0, "mid": 0, "toe": 0} for s in ("left", "right")))

    print("[X8] the wedge (pitched, counter-turned, floating box): structure")
    after8, st8 = fc.apply_cut(prim, cut, joints)
    check("slim share 0.13047 per side", near([st8["slim_share"]["left"], st8["slim_share"]["right"]], 0.13047, 1e-4), str(st8["slim_share"]))
    check("both sides bisect", all(st8["sides"][s]["bisected_faces"] > 0 and st8["sides"][s]["new_vertices"] > 0 for s in ("left", "right")), str(st8["sides"]))
    n_r, n_l = st8["sides"]["right"]["new_vertices"], st8["sides"]["left"]["new_vertices"]
    ids = {"right": np.arange(len(after8.positions) - n_r, len(after8.positions)),
           "left": np.arange(len(after8.positions) - n_r - n_l, len(after8.positions) - n_r)}
    worst = 0.0
    for s in ("left", "right"):
        desc = cut["sides"][s]
        m8 = fc._Map(desc, joints, after8)
        C8 = m8.to_cut(after8.positions[ids[s]], m8.wF[ids[s]], m8.wT[ids[s]])
        gval = fc._Side(desc).g(C8)
        on_wall = np.abs(C8[:, 0] - desc["toe_box"]["x_from"]) <= 1e-9       # the throat-front wall: g jumps there
        worst = max(worst, float(np.abs(gval[~on_wall]).max()) if (~on_wall).any() else 0.0)
    check("every new vertex lies on its side's cut surface (|g| <= 1e-9) or on the throat-front wall", worst <= 1e-9,
          f"{worst:.2e}")
    used = np.zeros(len(after8.positions), bool)
    used[after8.faces.ravel()] = True
    check("faces valid, no dangling vertex", bool(used.all()) and int(after8.faces.max()) < len(after8.positions))
    check("weights of new vertices sum to 1 on Foot / ToeBase", near(after8.weights[ids["left"]].sum(1), 1.0, 1e-9)
          and near(after8.weights[ids["right"]].sum(1), 1.0, 1e-9))

    print(f"\n{'ALL PASS' if not FAILS else f'{FAILS} FAILED'}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
