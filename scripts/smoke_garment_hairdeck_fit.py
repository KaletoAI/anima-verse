#!/usr/bin/env python3
"""HairDeck fit (``app/core/garment_hairdeck.py``) on synthetic meshes, expectations derived by hand below.

Usage: ./.venv/bin/python scripts/smoke_garment_hairdeck_fit.py

No world, no server, no hub: a throwaway storage dir (``paths.init`` first), every GLB is built in this file.
Plan 2026-11-09-hairdeck-hair, Task 3 (+ fix round 1: no colour sampling from an image; inner-wall cap filter).
Every fit passes forward_m 0 and tilt_deg 0, so [1]-[5] see the plain head match (the placement correction of the
user test 2026-11-09 has its own smoke, smoke_hairdeck_placement.py).

Fixture (metres, +y up, the body faces +z)
- Rigged body, skin joints [mixamorig:Hips, mixamorig:Spine2, mixamorig:Head], no node transform:
  * head = UV sphere radius 0.1 centred (0, 1.6, 0), 61 latitude bands x 120 segments (an odd band count, so no
    ring lies on the equator), every vertex Head weight 1;
  * neck = closed cylinder radius 0.04, rings at y 1.30, 1.35, 1.40, 1.45, 1.50, 1.55 (+ two cap centres), rings at
    y >= 1.45 Head 1, the rest Spine2 1.
  -> chin (lowest Head > 0.5 vertex) = 1.45, top = 1.7, cranium threshold = 1.45 + 0.6 * (1.7 - 1.45) = 1.60:
  the cranium is exactly the head sphere's upper half (the neck ends at 1.55, inside the sphere).
  Head-weighted bbox: x, z in [-0.1, 0.1] (to 3e-5), y [1.45, 1.7] -> head centre (cx, cz) = (0, 0), width = depth
  = 0.2: the front hairline region is z > 0 + 0.25 * 0.2 = 0.05 and |x| < 0.15 * 0.2 = 0.03.
- Proxy (node ``head_proxy`` of the "with head" file) = UV sphere radius 0.05 centred (0, 0.4, 0), 45 bands x 96
  segments (another sampling than the head). Upper half = vertices above the bbox centre y 0.4.
- Hair (node ``hair_cards``, in both files, same space), COLOR_0 FLOAT VEC4 = (0.25, 0.25, 0.25, 1) everywhere:
  * outer shell radius 0.055 centred (0, 0.4, 0): rings at local heights h = 0.010, 0.013, ..., 0.052 above the
    centre (ring radius sqrt(0.055^2 - h^2)) + a pole, 96 segments;
  * an inner card layer radius 0.048, rings at h = 0.030 .. 0.046 + a pole (a separate piece), so the push-out has
    something to do. The [5] "plain" fit leaves it out (the brief's shell alone).
- Two-wall body (for [4] only): the body above plus an INNER head sphere radius 0.094 (6 mm inside the outer one,
  the generator's double wall), same 61 x 120 sampling, Head weight 1.

[1] Placement. Proxy upper half (hemisphere r 0.05 at y 0.4) onto the cranium (hemisphere r 0.1 at y 1.6), scale +
    translation: s * 0.05 = 0.1 -> s = 2.0; s * 0.4 + t_y = 1.6 -> t_y = 0.8; x and z centred -> t = (0, 0.8, 0).
    Expected icp_scale 2.0 +- 0.01, translation (0, 0.8, 0) +- 0.001 per axis.
[2] Push-out. After placement the outer shell sits at radius 2 * 0.055 = 0.110 from the head centre (clearance
    0.010 >= CARD_CLEAR_M 0.004), the inner layer at 2 * 0.048 = 0.096, i.e. 0.004 INSIDE the head, so it is
    pushed out (max_push_m > 0, moved_share > 0). Measured on the true sphere (every hair vertex is above y 1.6,
    where the neck cylinder is inside the sphere, so the distance to the body is |p - (0, 1.6, 0)| - 0.1): no hair
    vertex inside (min > 0) and the minimum clearance >= 0.003 (the push asks for 0.004; one voxel 0.0034 of
    SDF/gradient slack is allowed down to 0.003).
[3] Colour. target sRGB (0.8, 0.6, 0.3) -> linear ((c + 0.055) / 1.055)^2.4:
      0.8 -> 0.81043^2.4 = exp(2.4 * -0.21019) = 0.6038
      0.6 -> 0.62085^2.4 = exp(2.4 * -0.47666) = 0.3185
      0.3 -> 0.33649^2.4 = exp(2.4 * -1.08920) = 0.0732
    The median of COLOR_0 is 0.25 per channel, gains 2.415 / 1.274 / 0.293 -> every corrected hair colour (hence
    the median) = (0.6038, 0.3185, 0.0732) +- 0.01, alpha 1. The scalp cap's colour is the median (CAP_COLOUR_PERCENTILE
    50, FIT_VERSION hair 6) of the corrected colours = the same value. Without a target the colours stay 0.25 (+- 1e-9) and colour_target None.
    Since FIT_VERSION hair 14 the cap is shaded where fill cards lie on it ([7]; Ruling T-U2b: by the distance d to
    the nearest FILL vertex): 0.6 of the median for d <= FILL_SHADE_NEAR_M 0.006, the median for d >= 0.010,
    1 - 0.4 * (0.010 - d) / 0.004 between (recounted per vertex). The shell here lies 0.110 - 0.1015 = 8.5 mm off the
    cap, so most of the cap is open and filled: cap vertices at 0.6 exist, none darker.
[4] Scalp cap. Front hairline = lowest hair vertex with z > 0.05 and |x| < 0.03: the outer shell's lowest ring
    h = 0.010 -> y = 0.8 + 2 * (0.4 + 0.010) = 1.62 (its vertex at segment 0 is at x 0, z 0.108). The push leaves
    that ring where the placement put it (FIT_VERSION hair 7): the shell sits at the layer map's fixed point (see
    [5]) and the smoothed push, which weighs at most 0.033 there, has no crown spread any more, so it is 0 on the
    shell (0.010 out > CARD_CLEAR_M). -> hairline = icp_scale * 0.41 + icp t_y +- 0.0002 (the observed 1.9999 x 0.41
    + 0.80002 = 1.61998), and in [1.619, 1.625] (the [1] tolerances on scale and t_y). Until hair 6 the spread lifted
    the ring 1.3 mm (1.62134).
    Cap = head-sphere triangles (all three vertices Head > 0.5) reaching above the cap's edge, the hairline +
    CAP_TUCK_M 0.003 (FIT_VERSION hair 14, Ruling T-U2b), with a hair vertex within 0.03 of the centroid (the shell
    is 0.01 away), whose centroid is not deeper than CAP_INNER_DEPTH_M = VOX_M 0.0034 inside the body SDF; each CUT
    at the edge level (``clip_patch``): all three vertices at or above it -> 1 triangle, two -> 2, one -> 1. Rings
    of the outer sphere (r 0.1, polar angle pi i / 61): ring 25 at 1.6 + 0.1 cos(25 pi / 61) = 1.627951, ring 26 at
    1.622966. With the observed hairline 1.619974 the edge is 1.622974 (reported 1.62297): ring 26 lies 8 um below
    it, so the pole band
    120 + bands 1..24 x 240 + band 25 cut (120 triangles with two vertices on ring 25 -> 2 each, 120 with one -> 1
    each = 360) = 6240 triangles; the smoke recounts it by this rule from the fixture arrays and the reported
    hairline (``clip_count``). Until hair 14 whole triangles with the centroid above the hairline were kept (the same
    6240 here, by chance — on a real forehead their teeth hung up to 10.6 mm below their neighbours).
    cap_tris_below_hairline == 0, every cap centroid above the hairline, inner_wall_dropped 0; the cap
    vertices are offset 0.0015 along the outward normal -> radius 0.1015 +- 0.0005; every cap vertex Head 1.
    The cap's vertices follow the hair's in the merged mesh (``report.vertices`` hair / cap), the fill cards after it.
    Two-wall body, ``_scalp_cap`` called with the same hair positions and that body's SDF: the outer sphere's
    triangles are the same set (cap count unchanged, every cap vertex at radius 0.1015); every inner-sphere triangle
    above the hairline passes the other three tests (Head 1, nearest hair >= 0.104 - 0.094 = 0.010 <= 0.03) but
    lies ~0.006 > 0.0034 inside the solid -> all of them are dropped: inner_wall_dropped = their count by the same
    centroid rule (6240 again: same sampling), > 0.
[5] Gate. GATES = max_push_m <= 0.12, moved_share <= 0.90, icp_resid_p95_m <= 0.012 and no largest-component gate.
    {max_push_m 0.13, moved_share 0.5, icp_resid_p95_m 0.005} refuses with a reason naming max_push_m; at 0.12 it
    passes; fit metrics hold every key of the brief.
    On fits: the plain fixture (outer shell only, clearance 0.010 > 0.004 everywhere) is not pushed at all ->
    max_push_m 0, moved_share 0, passes. The fixture of [1]-[4] passes since FIT_VERSION hair 4 (the layer-keeping
    push on the head, ``garment_hairdeck.layer_push``): the outer shell (15 rings x 96 + pole = 1441 vertices)
    sits at 0.010 = CARD_CLEAR_M + LAYER_BAND_M, the map's fixed point, so the layer push leaves it; the inner layer
    (5 x 96 + 1 = 481) lies 0.004 inside and is pushed whole. The blended smoothed push weighs at most
    1 - (1.62 - (1.71 - 0.119)) / LAYER_BLEND_M = 0.033 on the shell's lowest ring (y 1.62, hair top 1.71).
    -> moved_share = 481 / 1922 = 0.2503 (+- 0.002: the lowest ring may carry that 3 %) <= 0.90. Before, the crown
    spread (the largest displacement within SPREAD_M 0.0085, iterated) carried the inner layer's push across the
    6 mm to the shell and over all of it: 1.0, refused — a correct fit refused for the flood.
[6] The face stays clear (``_clear_face``, FIT_VERSION hair 5): two hair ribbons in front of a face band move
    sideways out of the box, bent along the card; a fringe (front hairline at or below the brows) is kept. The
    numbers are derived in ``face_clear``. The [1]-[5] fixture has no landmarks, so nothing moves there.
    ``movable`` (Ruling B11a, the pass after the drape): only the +x ribbon's vertices below y 1.50 may move ->
    14 of them in the box (rows 1.43 .. 1.49, 2 columns), each leaves it; every other vertex keeps its bits; 26 stay
    in the box (the -x ribbon's 20 + the +x ribbon's rows 1.50 .. 1.52).
[7] Scalp fill (``scalp_fill_cards``, FIT_VERSION hair 14; user test 2026-11-14 T-U2, the open band over Ylva's
    forehead), called directly on a sphere: body = the exact sphere SDF r 0.1 at (0, 1.6, 0), crown (0, 1.7, 0), cap
    = the uv sphere (61 bands, 120 segments) at r 0.1015 with the triangles whose centroid lies above 1.65, floor
    1.65. Hair = the cap's vertices with x < 0 moved out to r 0.105 (3.5 mm over the cap). A cap triangle with a
    vertex at x < 0 is never open (its centroid lies at most ~4 mm from that vertex, edges <= 2 pi 0.1015 / 120 =
    5.3 mm, so its hair is within sqrt(4^2 + 3.5^2) = 5.3 mm < FILL_COVER_M 8 mm); each card:
    - row centres at FILL_OFFSET_M 2.5 mm over the sphere: radius 0.1025 (+- 1e-9); the row's two vertices
      FILL_WIDTH_M / 2 = 6 mm to either side in the tangent plane: 12 mm apart (+- 1e-9), radius
      sqrt(0.1025^2 + 0.006^2) = 0.1026755 (+- 1e-6);
    - away from the crown on a sphere centred under it = down the meridian: every row centre at its seed's azimuth
      atan2(z, x) (+- 1e-9), y falling from the root row on;
    - rows 0.04 / 8 = 5 mm apart along the tangent, put back on the 0.1025 sphere: chord 2 * 0.1025 *
      sin(atan(0.005 / 0.1025) / 2) = 0.205 * sin(0.0243710) = 0.0049955 (+- 1e-6); at most FILL_ROWS 9 rows, at least 3; none below 1.65;
    - v from 1 at the root row to 0 at the tip (below);
    - every card's root at x > 0 (the open side; the radial move keeps the azimuth);
    - no row turns: a card stops before a row whose direction turns by more than 60 deg (FILL_MAX_TURN_COS 0.5 —
      over the crown away-from-crown flips), so the meridian rule above holds for every card.
    Hair over the whole cap (every cap vertex at r 0.105): no open triangle, no card. With ``front`` = (-1, 1.66)
    (the hair-ending band, Ruling T-U2b) the cap triangles whose centroid lies below 1.66 are open whatever hair
    lies near: r 0.1015, rings 17..21 at y 1.66503 / 1.66090 / 1.65668 / 1.65227 / 1.64775; band 17's centroids
    (1.66365 / 1.66228) are above, bands 18 and 19 below (240 each), band 20's upper triangles (centroid 1.65076)
    in the cap (> 1.65) -> open_tris 240 + 240 + 120 = 600, cards > 0.
    v by the distance along the card (Ruling T-U2b: a card cut short still ends in the strip's tips): rows equally
    spaced -> v 1, 1 - 1/(n-1), .. 0 (+- 1e-9) on every card that does not reach the floor; a card that lands ends
    with a row on the floor: y 1.65 (+- 0.5 mm: the step is cut where its straight line crosses the floor, then put
    back on the sphere), its chord shorter than a full row's.
[8] ``clip_patch`` by hand: triangle (0,0,0) (1,0,0) (0,1,0). Level y - 0.25: vertex 2 alone above -> one triangle
    (2, (0,0.25,0), (0.75,0.25,0)), area 0.5 * 0.75^2 = 0.28125, normal +z kept. Level 0.25 - y: vertices 0, 1 above
    -> two triangles, area 0.5 - 0.28125 = 0.21875, normal +z. Two triangles (0,1,2) (1,3,2) with 3 = (1,1,0), level
    y - 0.5: the shared edge 1-2 is crossed once -> 3 new vertices, not 4: (0,0.5), (0.5,0.5), (1,0.5); kept area =
    the square's upper half 0.5.
"""
import json
import math
import struct
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

FAILS = []
# Every fit here checks the placement of the plain head match: no forward shift, no tilt (the placement correction
# has its own smoke, scripts/smoke_hairdeck_placement.py).
NO_PLACEMENT = {"forward_m": 0.0, "tilt_deg": 0.0}


def check(cond, label):
    print(("OK   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


# --- GLB building ---------------------------------------------------------------------------------------------------

def pack(doc, blob):
    blob = bytes(blob) + b"\0" * (-len(blob) % 4)
    doc["buffers"] = [{"byteLength": len(blob)}]
    raw = json.dumps(doc).encode()
    raw += b" " * (-len(raw) % 4)
    body = struct.pack("<II", len(raw), 0x4E4F534A) + raw + struct.pack("<II", len(blob), 0x004E4942) + blob
    return b"glTF" + struct.pack("<II", 2, 12 + len(body)) + body


class Builder:
    def __init__(self):
        self.blob, self.views, self.accs = bytearray(), [], []

    def add(self, arr, ctype, typ, normalized=False, minmax=False):
        raw = arr.tobytes()
        self.blob.extend(b"\0" * (-len(self.blob) % 4))
        self.views.append({"buffer": 0, "byteOffset": len(self.blob), "byteLength": len(raw)})
        self.blob.extend(raw)
        a = {"bufferView": len(self.views) - 1, "componentType": ctype,
             "count": int(arr.shape[0]) if arr.ndim > 1 else int(arr.size), "type": typ}
        if normalized:
            a["normalized"] = True
        if minmax:
            a["min"], a["max"] = arr.min(0).tolist(), arr.max(0).tolist()
        self.accs.append(a)
        return len(self.accs) - 1

    def glb(self, doc):
        return pack(dict(doc, accessors=self.accs, bufferViews=self.views), self.blob)


def uv_sphere(r, c, bands, segs):
    P = [[0.0, r, 0.0]]
    for i in range(1, bands):
        th = math.pi * i / bands
        for j in range(segs):
            ph = 2 * math.pi * j / segs
            P.append([r * math.sin(th) * math.sin(ph), r * math.cos(th), r * math.sin(th) * math.cos(ph)])
    P.append([0.0, -r, 0.0])
    F = []
    for j in range(segs):
        F.append([0, 1 + j, 1 + (j + 1) % segs])
    for i in range(bands - 2):
        a, b = 1 + i * segs, 1 + (i + 1) * segs
        for j in range(segs):
            k = (j + 1) % segs
            F += [[a + j, b + j, b + k], [a + j, b + k, a + k]]
    last, s = len(P) - 1, 1 + (bands - 2) * segs
    for j in range(segs):
        F.append([s + j, last, s + (j + 1) % segs])
    return np.array(P) + np.asarray(c, float), np.array(F)


def cylinder(r, ys, segs):
    P = [[r * math.sin(2 * math.pi * j / segs), y, r * math.cos(2 * math.pi * j / segs)]
         for y in ys for j in range(segs)]
    F = []
    for i in range(len(ys) - 1):
        a, b = i * segs, (i + 1) * segs
        for j in range(segs):
            k = (j + 1) % segs
            F += [[a + j, a + k, b + k], [a + j, b + k, b + j]]
    bot, top = len(P), len(P) + 1
    P += [[0, ys[0], 0], [0, ys[-1], 0]]
    last = (len(ys) - 1) * segs
    for j in range(segs):
        k = (j + 1) % segs
        F += [[bot, k, j], [top, last + j, last + k]]
    return np.array(P, float), np.array(F)


def cap_shell(r, heights, segs, c):
    """Rings at local heights ``heights`` of a sphere of radius ``r`` (+ a pole), centre ``c``."""
    P = []
    for h in heights:
        rr = math.sqrt(r * r - h * h)
        P += [[rr * math.sin(2 * math.pi * j / segs), h, rr * math.cos(2 * math.pi * j / segs)] for j in range(segs)]
    P.append([0.0, r, 0.0])
    F = []
    for i in range(len(heights) - 1):
        a, b = i * segs, (i + 1) * segs
        for j in range(segs):
            k = (j + 1) % segs
            F += [[a + j, a + k, b + k], [a + j, b + k, b + j]]
    pole, last = len(P) - 1, (len(heights) - 1) * segs
    for j in range(segs):
        F.append([last + j, last + (j + 1) % segs, pole])
    return np.array(P) + np.asarray(c, float), np.array(F)


def body_glb(inner_wall=False):
    Ps, Fs = uv_sphere(0.1, (0, 1.6, 0), 61, 120)
    if inner_wall:
        Pi, Fi = uv_sphere(0.094, (0, 1.6, 0), 61, 120)
        Ps, Fs = np.vstack([Ps, Pi]), np.vstack([Fs, Fi + len(Ps)])
    ys = [1.30, 1.35, 1.40, 1.45, 1.50, 1.55]
    Pc, Fc = cylinder(0.04, ys, 48)
    P = np.vstack([Ps, Pc])
    F = np.vstack([Fs, Fc + len(Ps)])
    head = np.r_[np.ones(len(Ps), bool), Pc[:, 1] >= 1.45 - 1e-9]
    J = np.zeros((len(P), 4), "<u2")
    J[:, 0] = np.where(head, 2, 1)
    W = np.zeros((len(P), 4), "<f4")
    W[:, 0] = 1
    b = Builder()
    attrs = {"POSITION": b.add(P.astype("<f4"), 5126, "VEC3", minmax=True),
             "JOINTS_0": b.add(J, 5123, "VEC4"), "WEIGHTS_0": b.add(W, 5126, "VEC4")}
    ind = b.add(F.astype("<u4").ravel(), 5125, "SCALAR")
    nodes = [{"name": "Armature", "children": [1, 2]},
             {"name": "Body", "mesh": 0, "skin": 0},
             {"name": "mixamorig:Hips", "children": [3]},
             {"name": "mixamorig:Spine2", "children": [4], "translation": [0, 1.3, 0]},
             {"name": "mixamorig:Head", "translation": [0, 0.2, 0]}]
    doc = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}], "nodes": nodes,
           "meshes": [{"name": "Body", "primitives": [{"attributes": attrs, "indices": ind, "material": 0}]}],
           "skins": [{"joints": [2, 3, 4]}], "materials": [{"name": "Skin"}]}
    return b.glb(doc)


def hair_arrays(inner=True):
    hs = [round(0.010 + 0.003 * i, 6) for i in range(15)]           # 0.010 .. 0.052
    Po, Fo = cap_shell(0.055, hs, 96, (0, 0.4, 0))
    if not inner:
        return Po, Fo
    Pi, Fi = cap_shell(0.048, [0.030, 0.034, 0.038, 0.042, 0.046], 96, (0, 0.4, 0))
    return np.vstack([Po, Pi]), np.vstack([Fo, Fi + len(Po)])


def hair_glbs(inner=True):
    """``(nohead_glb, proxy_glb)``."""
    P, F = hair_arrays(inner)
    C = np.tile(np.array([0.25, 0.25, 0.25, 1.0], "<f4"), (len(P), 1))
    U = np.zeros((len(P), 2), "<f4")
    hair_mat = {"name": "hair", "doubleSided": True,
                "pbrMetallicRoughness": {"baseColorFactor": [1, 1, 1, 1], "roughnessFactor": 0.75,
                                         "metallicFactor": 0.0}}
    out = []
    for with_proxy in (False, True):
        b = Builder()
        attrs = {"POSITION": b.add(P.astype("<f4"), 5126, "VEC3", minmax=True),
                 "COLOR_0": b.add(C, 5126, "VEC4"), "TEXCOORD_0": b.add(U, 5126, "VEC2")}
        ind = b.add(F.astype("<u4").ravel(), 5125, "SCALAR")
        nodes = [{"name": "hair_cards", "mesh": 0}]
        meshes = [{"name": "hair_cards", "primitives": [{"attributes": attrs, "indices": ind, "material": 0}]}]
        mats = [hair_mat]
        if with_proxy:
            Pp, Fp = uv_sphere(0.05, (0, 0.4, 0), 45, 96)
            pa = b.add(Pp.astype("<f4"), 5126, "VEC3", minmax=True)
            pi = b.add(Fp.astype("<u4").ravel(), 5125, "SCALAR")
            nodes.append({"name": "head_proxy", "mesh": 1})
            meshes.append({"name": "head_proxy", "primitives": [{"attributes": {"POSITION": pa}, "indices": pi,
                                                                 "material": 1}]})
            mats.append({"name": "head", "doubleSided": False})
        doc = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": list(range(len(nodes)))}],
               "nodes": nodes, "meshes": meshes, "materials": mats}
        out.append(b.glb(doc))
    return out[0], out[1]


def clip_count(r, edge):
    """Triangles of the fixture head sphere of radius ``r`` cut at y ``edge``: three vertices at or above -> 1,
    two -> 2, one -> 1."""
    P, F = uv_sphere(r, (0, 1.6, 0), 61, 120)
    up = (np.asarray(P)[F][:, :, 1] >= edge).sum(1)
    return int((up == 3).sum() + 2 * (up == 2).sum() + (up == 1).sum())


def reach_count(r, edge):
    """Triangles of the fixture head sphere of radius ``r`` with a vertex above y ``edge`` (the cap's candidates)."""
    P, F = uv_sphere(r, (0, 1.6, 0), 61, 120)
    return int((np.asarray(P)[F][:, :, 1].max(1) > edge).sum())


class _SphereSDF:
    """Signed distance to a sphere (centre ``c``, radius ``r``) — the stub ``_clamp`` needs."""
    def __init__(self, c, r):
        self.c, self.r = np.asarray(c, float), float(r)

    def sample(self, X):
        return np.linalg.norm(X - self.c, axis=1) - self.r

    def grad(self, X):
        v = X - self.c
        return v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-12)


def face_clear(gh):
    """``_clear_face`` by hand. Face band: a grid x = -0.075..0.075 (51 columns) x y 1.43..1.52 x z -0.05/+0.05,
    all Head -> centre x 0, mid plane z 0, half width = (p98 - p2)/2 of x = 0.075 - 0.02 * 0.15 = 0.072, reach
    0.8 * 0.072 = 0.0576. Hair: a ribbon x 0.02 / 0.03 (and its mirror at -0.02 / -0.03), z 0.09, y 1.60 .. 1.40 in
    0.01 steps. Brow 1.53, chin 1.42: the box holds y 1.43 .. 1.52 (10 rows x 2 columns per ribbon); need = reach -
    |x| = 0.0376 on the inner column, so it moves to x 0.0576 (the box edge, outside: |x| < reach is strict); the
    spread is need x 0.85 per ring: the inner column's top vertex y 1.60 lies 8 rings above y 1.52 -> 0.0376 x
    0.85^8 = 0.010246. The sphere (centre y 1.5, r 0.06) never comes within 4 mm, so the clamp moves nothing.
    A front hairline at 1.50 (at or below the brow) is a fringe: nothing moves."""
    from types import SimpleNamespace
    xs = np.linspace(-0.075, 0.075, 51)
    G = np.array([[x, y, z] for x in xs for y in np.linspace(1.43, 1.52, 10) for z in (-0.05, 0.05)])
    body = SimpleNamespace(positions=G)
    head_w = np.ones(len(G))
    ys = np.round(np.linspace(1.60, 1.40, 21), 5)
    V, F = [], []
    for sx in (1, -1):
        base = len(V)
        for y in ys:
            V += [[sx * 0.02, y, 0.09], [sx * 0.03, y, 0.09]]
        for i in range(len(ys) - 1):
            a, b, c2, d = base + 2 * i, base + 2 * i + 1, base + 2 * i + 2, base + 2 * i + 3
            F += [[a, b, c2], [b, d, c2]]
    V, F = np.array(V), np.array(F)
    sdf = _SphereSDF([0, 1.5, 0], 0.06)
    Q, rep = gh._clear_face(F, V, sdf, body, head_w, {"brow_y": 1.53}, 1.42, None)
    check(rep["in_box"] == 40 and rep["in_box_after"] == 0, f"40 vertices in the face box, none after ({rep})")
    check(abs(rep["half_width_m"] - 0.072) < 1e-4, f"half width {rep['half_width_m']} = 0.072")
    dx = Q[:, 0] - V[:, 0]
    i_mid = 2 * int(np.nonzero(ys == 1.48)[0][0])
    check(abs(dx[i_mid] - 0.0376) < 1e-6 and abs(Q[i_mid, 0] - 0.0576) < 1e-6,
          f"inner column at y 1.48 moves 0.0376 to the box edge ({dx[i_mid]:.6f})")
    check(abs(dx[0] - 0.0376 * 0.85 ** 8) < 1e-6, f"top vertex y 1.60 bends 0.0376 x 0.85^8 = 0.010246 ({dx[0]:.6f})")
    j_mid = 2 * len(ys) + i_mid
    check(abs(dx[j_mid] + 0.0376) < 1e-6, f"the mirrored ribbon moves to -x ({dx[j_mid]:.6f})")
    check(np.allclose(Q[:, 1:], V[:, 1:]), "only x changes (y, z kept; no clamp)")
    mov = (np.arange(len(V)) < 2 * len(ys)) & (V[:, 1] < 1.495)
    Qm, repm = gh._clear_face(F, V, sdf, body, head_w, {"brow_y": 1.53}, 1.42, None, movable=mov, clear=0.008)
    check(repm["in_box"] == 14 and repm["in_box_after"] == 26, f"movable: 14 in the box, 26 after ({repm})")
    check(np.array_equal(Qm[~mov], V[~mov]), "movable: every other vertex keeps its bits")
    check(abs(Qm[i_mid, 0] - 0.0576) < 1e-6, f"movable: inner column at y 1.48 to the box edge ({Qm[i_mid, 0]:.6f})")
    Qf, repf = gh._clear_face(F, V, sdf, body, head_w, {"brow_y": 1.53}, 1.42, 1.50)
    check(repf.get("skipped") == "fringe" and np.array_equal(Qf, V), f"a hairline at 1.50 <= brow is a fringe: kept {repf}")


def scalp_fill(gh):
    Ps, Fs = uv_sphere(0.1015, (0, 1.6, 0), 61, 120)
    Ps, Fs = np.asarray(Ps, float), np.asarray(Fs)
    Fc = Fs[Ps[Fs].mean(1)[:, 1] > 1.65]
    sdf = _SphereSDF([0, 1.6, 0], 0.1)
    out = (Ps[Ps[:, 0] < 0] - [0, 1.6, 0]) * (0.105 / 0.1015) + [0, 1.6, 0]
    V, F, UV, N, card, info = gh.scalp_fill_cards(Ps, Fc, out, sdf, np.array([0, 1.7, 0]), 1.65)
    print("       " + json.dumps(info))
    check(info["cards"] > 0 and len(V) == len(UV) == len(N) == len(card), f"{info['cards']} cards")
    rows_ok = width_ok = edge_ok = az_ok = down_ok = step_ok = v_ok = land_ok = True
    seeds, n_landed = [], 0
    for c in range(int(card.max()) + 1):
        Vk, Uk = V[card == c], UV[card == c]
        L, R = Vk[0::2], Vk[1::2]
        M = (L + R) / 2 - [0, 1.6, 0]
        n = len(M)
        rows_ok &= 3 <= n <= 9 and bool((M[:, 1] + 1.6 >= 1.65).all())
        width_ok &= bool(np.allclose(np.linalg.norm(R - L, axis=1), 0.012, atol=1e-9))
        edge_ok &= bool(np.allclose(np.linalg.norm(Vk - [0, 1.6, 0], axis=1), math.hypot(0.1025, 0.006), atol=1e-6))
        rows_ok &= bool(np.allclose(np.linalg.norm(M, axis=1), 0.1025, atol=1e-9))
        az = np.arctan2(M[:, 2], M[:, 0])
        az_ok &= bool(np.allclose(az, az[0], atol=1e-9))
        down_ok &= bool(np.all(np.diff(M[:, 1]) < 0))
        v = Uk[0::2, 1]
        chords = np.linalg.norm(np.diff(M, axis=0), axis=1)
        landed = bool(chords[-1] < 0.0049955 - 1e-6)
        if landed:
            land_ok &= abs(M[-1, 1] + 1.6 - 1.65) <= 0.0005
            step_ok &= bool(np.allclose(chords[:-1], 0.0049955, atol=1e-6))
            n_landed += 1
        else:
            v_ok &= bool(np.allclose(v, 1 - np.arange(n) / (n - 1), atol=1e-9))
            step_ok &= bool(np.allclose(chords, 0.0049955, atol=1e-6))
        v_ok &= bool(np.isclose(v[0], 1.0) and np.isclose(v[-1], 0.0) and np.all(np.diff(v) < 0))
        seeds.append(M[0] + [0, 1.6, 0])
    check(rows_ok, "3..9 rows, none below 1.65, row centres at r 0.1025")
    check(width_ok and edge_ok, "rows 12 mm wide, their vertices at r 0.1026755")
    check(az_ok and down_ok, "every card down its seed's meridian (away from the crown)")
    check(step_ok, "rows 4.9955 mm apart (a landing row shorter)")
    check(land_ok and n_landed > 0, f"{n_landed} cards land with a row on the floor 1.65 (+- 0.5 mm)")
    check(v_ok, "v from 1 at the root to 0 at the tip, by the distance along the card")
    S = np.asarray(seeds)
    check(gh.FILL_MAX_TURN_COS == 0.5 and bool((S[:, 0] > 0).all()),
          f"every card on the open side (root x min {S[:, 0].min():.4f})")
    full = (Ps - [0, 1.6, 0]) * (0.105 / 0.1015) + [0, 1.6, 0]
    V2, _, _, _, _, info2 = gh.scalp_fill_cards(Ps, Fc, full, sdf, np.array([0, 1.7, 0]), 1.65)
    check(len(V2) == 0 and info2["open_tris"] == 0 and info2["cards"] == 0, f"hair over all of the cap: none {info2}")
    V3, _, _, _, _, info3 = gh.scalp_fill_cards(Ps, Fc, full, sdf, np.array([0, 1.7, 0]), 1.65, front=(-1.0, 1.66))
    check(info3["open_tris"] == 600 and info3["cards"] > 0, f"front band below 1.66: 600 open triangles {info3}")


def clip_by_hand(gh):
    def area(P, F):
        return float(0.5 * np.linalg.norm(np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]]), axis=1).sum())

    def normals_z(P, F):
        return bool((np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]])[:, 2] > 0).all())
    T = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], float)
    F = np.array([[0, 1, 2]])
    P1, F1 = gh.clip_patch(T, F, T[:, 1] - 0.25)
    check(len(F1) == 1 and np.isclose(area(P1, F1), 0.28125) and normals_z(P1, F1)
          and np.allclose(sorted(map(tuple, P1[F1[0]].round(9).tolist())), [(0, 0.25, 0), (0, 1, 0), (0.75, 0.25, 0)]),
          f"one vertex above: 1 triangle, area 0.28125 ({area(P1, F1)})")
    P2, F2 = gh.clip_patch(T, F, 0.25 - T[:, 1])
    check(len(F2) == 2 and np.isclose(area(P2, F2), 0.21875) and normals_z(P2, F2),
          f"two above: 2 triangles, area 0.21875 ({area(P2, F2)})")
    Q = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]], float)
    P3, F3 = gh.clip_patch(Q, np.array([[0, 1, 2], [1, 3, 2]]), Q[:, 1] - 0.5)
    new = P3[4:]
    check(len(new) == 3 and np.allclose(sorted(map(tuple, new[:, :2].round(9).tolist())), [(0, 0.5), (0.5, 0.5), (1, 0.5)])
          and np.isclose(area(P3, F3), 0.5) and normals_z(P3, F3),
          f"shared edge crossed once: 3 new vertices, area 0.5 ({len(new)}, {area(P3, F3)})")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="hairdeck-fit-") as tmp:
        root = Path(tmp)
        from app.core import paths
        paths.init(root / "world")
        try:
            from app.core import garment_hairdeck as gh
        except ImportError as e:
            check(False, f"garment_hairdeck importable ({e})")
            print("FAILED: " + ", ".join(FAILS))
            return 1
        from app.core.garment_fit import SDF_MARGIN_M, VOX_M, body_sdf, dense_weights, joint_index
        from app.core.glb_mesh import body_arrays

        body = body_glb()
        nohead, proxy = hair_glbs()
        target = (0.8, 0.6, 0.3)
        res = gh.fit_hairdeck(nohead, proxy, body, colour_target=target, **NO_PLACEMENT)
        m, rep = res.metrics, res.report
        g = res.garment
        n_hair = len(hair_arrays()[0])
        print("metrics:", json.dumps(m))

        # [1] placement
        print("[1] placement")
        check(abs(m["icp_scale"] - 2.0) <= 0.01, f"icp scale {m['icp_scale']} = 2.0 +- 0.01")
        t = np.asarray(rep["icp"]["translation"])
        check(bool(np.all(np.abs(t - [0, 0.8, 0]) <= 0.001)),
              f"translation {t.round(5).tolist()} = (0, 0.8, 0) +- 1 mm")
        check(abs(rep["cranium"]["threshold_y"] - 1.60) < 1e-6,
              f"cranium threshold {rep['cranium']['threshold_y']} = 1.60")

        # [2] push-out
        print("[2] push-out")
        X = np.asarray(g.positions[:n_hair])
        clear = np.linalg.norm(X - [0, 1.6, 0], axis=1) - 0.1
        check(bool((X[:, 1] > 1.6).all()), "every hair vertex above y 1.6 (sphere distance applies)")
        check(float(clear.min()) > 0, f"no hair vertex inside the head (min {clear.min():.5f})")
        check(float(clear.min()) >= 0.003, f"min clearance {clear.min():.5f} >= 0.003")
        check(m["max_push_m"] > 0.003 and 0 < m["moved_share"] <= 1, f"the inner layer was pushed "
              f"(max {m['max_push_m']}, share {m['moved_share']})")

        # [3] colour
        print("[3] colour")
        lin = np.array([0.6038, 0.3185, 0.0732])
        Ch = np.asarray(g.colors[:n_hair])
        check(bool(np.all(np.abs(np.median(Ch[:, :3], 0) - lin) <= 0.01)),
              f"corrected median {np.median(Ch[:, :3], 0).round(4).tolist()} = {lin.tolist()} +- 0.01")
        check(bool(np.all(Ch[:, 3] == 1)), "alpha 1")
        check(m["colour_target"] == list(target), f"colour_target recorded {m['colour_target']}")
        n_cap = rep["vertices"]["cap"]
        Cc = np.asarray(g.colors[n_hair:n_hair + n_cap])
        from scipy.spatial import cKDTree
        d_cap, _ = cKDTree(np.asarray(g.positions[n_hair + n_cap:])).query(np.asarray(g.positions[n_hair:n_hair + n_cap]))
        shade = 1 - 0.4 * np.clip((0.010 - d_cap) / 0.004, 0, 1)
        check(len(Cc) > 0 and bool(np.all(np.abs(Cc[:, :3] - lin * shade[:, None]) <= 0.01)),
              "cap colour = median = target, shaded by the fill rule")
        check(rep["vertices"]["fill"] > 0 and bool((shade == 0.6).any()) and float(shade.min()) >= 0.6,
              f"fill cards on the open cap ({rep['fill']}), the cap under them 0.6, none darker")
        check(gh.CAP_COLOUR_PERCENTILE == 50, "the cap takes the median colour (CAP_COLOUR_PERCENTILE 50)")
        plain = gh.fit_hairdeck(nohead, proxy, body, colour_target=None, **NO_PLACEMENT)
        check(bool(np.all(np.abs(np.asarray(plain.garment.colors[:n_hair])[:, :3] - 0.25) <= 1e-9))
              and plain.metrics["colour_target"] is None, "no target: colours untouched, colour_target None")
        try:
            gh.fit_hairdeck(nohead, proxy, body, colour_target=(1.2, 0.5, 0.5), **NO_PLACEMENT)
            check(False, "target outside 0..1 refused")
        except ValueError as e:
            check(True, f"target outside 0..1 refused: {e}")

        # [4] scalp cap
        print("[4] scalp cap")
        hl = rep["cap"]["hairline_y"]
        placed_ring = m["icp_scale"] * 0.41 + rep["icp"]["translation"][1]
        check(abs(hl - placed_ring) <= 0.0002 and 1.619 <= hl <= 1.625,
              f"hairline {hl} = the placed ring {placed_ring:.5f} +- 0.2 mm (not pushed), in [1.619, 1.625]")
        edge = hl + 0.003
        check(gh.CAP_TUCK_M == 0.003 and abs(rep["cap"]["edge_y"] - edge) < 1e-5, f"cap edge {rep['cap']['edge_y']}")
        want = clip_count(0.1, edge)
        check(m["cap_tris"] == want and want == 6240,
              f"cap_tris {m['cap_tris']} == {want} == 6240 (outer triangles cut at the edge)")
        check(rep["cap"]["inner_wall_dropped"] == 0, "single wall: nothing dropped as inner wall")
        check(m["cap_tris_below_hairline"] == 0, f"cap_tris_below_hairline {m['cap_tris_below_hairline']} == 0")
        I = np.asarray(g.indices)
        cap_f = I[(I.min(1) >= n_hair) & (I.max(1) < n_hair + n_cap)]
        check(len(cap_f) == m["cap_tris"], f"{len(cap_f)} cap faces in the merged mesh")
        P = np.asarray(g.positions)
        check(bool((P[cap_f].mean(1)[:, 1] > hl).all()), "every cap centroid above the hairline")
        r = np.linalg.norm(P[n_hair:n_hair + n_cap] - [0, 1.6, 0], axis=1)
        check(bool(np.all(np.abs(r - 0.1015) <= 0.0005)), f"cap offset 1.5 mm (radius {r.min():.5f}..{r.max():.5f})")
        Jc, Wc = np.asarray(g.joints[n_hair:]), np.asarray(g.weights[n_hair:])
        head_i = g.joint_names.index("mixamorig:Head")
        check(bool(np.all(Jc[:, 0] == head_i) and np.all(Wc[:, 0] == 1) and np.all(Wc[:, 1:] == 0)),
              "cap (and fill) weighted Head 1")
        B = body_arrays(body)
        check(abs(rep["cranium"]["chin_y"] - 1.45) < 1e-6
              and int((dense_weights(B)[:, joint_index(B, "head")] > 0.5).sum()) > 0, "chin 1.45")
        B2 = body_arrays(body_glb(inner_wall=True))
        Xh = np.asarray(g.positions[:n_hair])
        sdf2 = body_sdf(B2.positions, B2.faces, vox=VOX_M,
                        bounds=(Xh.min(0) - SDF_MARGIN_M, Xh.max(0) + SDF_MARGIN_M))
        V2, F2, _, hl2, info2 = gh._scalp_cap(B2, dense_weights(B2)[:, joint_index(B2, "head")], Xh, sdf2)
        r2 = np.linalg.norm(V2 - [0, 1.6, 0], axis=1)
        inner_want = reach_count(0.094, hl2 + 0.003)
        check(abs(hl2 - hl) <= 1e-5 and len(F2) == want, f"two walls: cap {len(F2)} == {want} outer triangles")
        check(bool(np.all(np.abs(r2 - 0.1015) <= 0.0005)), f"two walls: every cap vertex on the outer wall "
              f"(radius {r2.min():.5f}..{r2.max():.5f})")
        check(info2["inner_wall_dropped"] == inner_want and inner_want > 0,
              f"two walls: inner_wall_dropped {info2['inner_wall_dropped']} == {inner_want}")
        check(int((V2[F2].mean(1)[:, 1] < hl2).sum()) == 0, "two walls: no cap triangle below the hairline")

        # [5] gate
        print("[5] gate")
        keys = ("max_push_m", "moved_share", "icp_scale", "icp_resid_median_m", "icp_resid_p95_m", "cap_tris",
                "cap_tris_below_hairline", "colour_target")
        check(all(k in m for k in keys), "fit metrics hold every key")
        check(set(gh.GATES) == {"max_push_m", "moved_share", "icp_resid_p95_m"}
              and gh.GATES["max_push_m"][1] == 0.12 and gh.GATES["moved_share"][1] == 0.90
              and gh.GATES["icp_resid_p95_m"][1] == 0.012, "GATES = the HairDeck gate")
        ok, reasons = gh.gate({"max_push_m": 0.13, "moved_share": 0.5, "icp_resid_p95_m": 0.005})
        check(not ok and len(reasons) == 1 and "max_push_m" in reasons[0], f"0.13 refuses: {reasons}")
        ok, reasons = gh.gate({"max_push_m": 0.12, "moved_share": 0.5, "icp_resid_p95_m": 0.005})
        check(ok and not reasons, "0.12 passes")
        check(res.ok and abs(m["moved_share"] - 481 / 1922) <= 0.002,
              f"the inner-layer fit: only the inner layer moves, {m['moved_share']} = 481/1922 {res.reasons}")
        plain_nohead, plain_proxy = hair_glbs(inner=False)
        pf = gh.fit_hairdeck(plain_nohead, plain_proxy, body, colour_target=None, **NO_PLACEMENT)
        check(pf.metrics["max_push_m"] == 0 and pf.metrics["moved_share"] == 0 and pf.ok and not pf.reasons,
              f"the plain shell is not pushed and passes ({pf.metrics['max_push_m']}, "
              f"{pf.metrics['moved_share']}, {pf.reasons})")

        print("[6] the face stays clear")
        face_clear(gh)

        print("[7] scalp fill")
        scalp_fill(gh)

        print("[8] clip_patch")
        clip_by_hand(gh)

    print("ALL OK" if not FAILS else "FAILED: " + ", ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
