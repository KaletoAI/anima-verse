#!/usr/bin/env python3
"""HairDeck fit (``app/core/garment_hairdeck.py``) on synthetic meshes, expectations derived by hand below.

Usage: ./.venv/bin/python scripts/smoke_garment_hairdeck_fit.py

No world, no server, no hub: a throwaway storage dir (``paths.init`` first), every GLB is built in this file.
Plan 2026-11-09-hairdeck-hair, Task 3 (+ fix round 1: no colour sampling from an image; inner-wall cap filter).

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
    the median) = (0.6038, 0.3185, 0.0732) +- 0.01, alpha 1. The scalp cap's colour is the 20th percentile of the
    corrected colours = the same value. Without a target the colours stay 0.25 (+- 1e-9) and colour_target None.
[4] Scalp cap. Front hairline = lowest hair vertex with z > 0.05 and |x| < 0.03: the outer shell's lowest ring
    h = 0.010 -> y = 0.8 + 2 * (0.4 + 0.010) = 1.62 (its vertex at segment 0 is at x 0, z 0.108). The push may lift
    it a little (smoothing carries the inner layer's push along the shell) -> hairline in [1.62, 1.625].
    Cap = head-sphere triangles (all three vertices Head > 0.5) with centroid above the hairline and a hair vertex
    within 0.03 (the shell is 0.01 away), whose centroid is not deeper than CAP_INNER_DEPTH_M = VOX_M 0.0034 inside
    the body SDF. Centroids of the outer sphere's triangles: band k (polar angles pi k/61 .. pi (k+1)/61) has two
    triangles per segment at y = 1.6 + 0.1 (2 cos a + cos b) / 3 and 1.6 + 0.1 (cos a + 2 cos b) / 3; a chord
    centroid lies < 0.1 mm inside the sphere, so the depth filter keeps all of them. Band 25: 1.62629 / 1.62463,
    band 26: 1.62129 / 1.61961. With the observed hairline 1.62134 (pushed 1.3 mm up) that is the pole band 120 +
    bands 1..25 x 240 = 6120 triangles; the smoke recounts it by this rule from the fixture arrays and the reported
    hairline. cap_tris_below_hairline == 0, every cap centroid above the hairline, inner_wall_dropped 0; the cap
    vertices are offset 0.0015 along the outward normal -> radius 0.1015 +- 0.0005; every cap vertex Head 1.
    Two-wall body, ``_scalp_cap`` called with the same hair positions and that body's SDF: the outer sphere's
    triangles are the same set (cap count unchanged, every cap vertex at radius 0.1015); every inner-sphere triangle
    above the hairline passes the other three tests (Head 1, nearest hair >= 0.104 - 0.094 = 0.010 <= 0.03) but
    lies ~0.006 > 0.0034 inside the solid -> all of them are dropped: inner_wall_dropped = their count by the same
    centroid rule (6120 again: same sampling), > 0.
[5] Gate. GATES = max_push_m <= 0.12, moved_share <= 0.90, icp_resid_p95_m <= 0.012 and no largest-component gate.
    {max_push_m 0.13, moved_share 0.5, icp_resid_p95_m 0.005} refuses with a reason naming max_push_m; at 0.12 it
    passes; fit metrics hold every key of the brief.
    On fits: the plain fixture (outer shell only, clearance 0.010 > 0.004 everywhere) is not pushed at all ->
    max_push_m 0, moved_share 0, passes. The fixture of [1]-[4] refuses, naming moved_share: the whole shell lies
    within the crown band (spread_depth 0.119 > its 0.09 height) and is ONE connected mesh smoothed 6 passes in
    each of the first 6 iterations, so the inner layer's push reaches every shell vertex above MOVED_EPS_M
    0.00017 m -> moved_share 1.0 > 0.90. (The real spike hair, 97 separate cards: 0.685.)
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


def centroid_count(r, hairline):
    """Triangles of the fixture head sphere of radius ``r`` whose centroid lies above ``hairline``."""
    P, F = uv_sphere(r, (0, 1.6, 0), 61, 120)
    return int((P[F].mean(1)[:, 1] > hairline).sum())


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
        res = gh.fit_hairdeck(nohead, proxy, body, colour_target=target)
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
        Cc = np.asarray(g.colors[n_hair:])
        check(len(Cc) > 0 and bool(np.all(np.abs(Cc[:, :3] - lin) <= 0.01)), "cap colour = 20th percentile = target")
        plain = gh.fit_hairdeck(nohead, proxy, body, colour_target=None)
        check(bool(np.all(np.abs(np.asarray(plain.garment.colors[:n_hair])[:, :3] - 0.25) <= 1e-9))
              and plain.metrics["colour_target"] is None, "no target: colours untouched, colour_target None")
        try:
            gh.fit_hairdeck(nohead, proxy, body, colour_target=(1.2, 0.5, 0.5))
            check(False, "target outside 0..1 refused")
        except ValueError as e:
            check(True, f"target outside 0..1 refused: {e}")

        # [4] scalp cap
        print("[4] scalp cap")
        hl = rep["cap"]["hairline_y"]
        check(1.62 - 1e-6 <= hl <= 1.625, f"hairline {hl} in [1.62, 1.625]")
        want = centroid_count(0.1, hl)
        check(m["cap_tris"] == want and want > 0,
              f"cap_tris {m['cap_tris']} == {want} (outer triangles above the hairline)")
        check(rep["cap"]["inner_wall_dropped"] == 0, "single wall: nothing dropped as inner wall")
        check(m["cap_tris_below_hairline"] == 0, f"cap_tris_below_hairline {m['cap_tris_below_hairline']} == 0")
        I = np.asarray(g.indices)
        cap_f = I[I.min(1) >= n_hair]
        check(len(cap_f) == m["cap_tris"], f"{len(cap_f)} cap faces in the merged mesh")
        P = np.asarray(g.positions)
        check(bool((P[cap_f].mean(1)[:, 1] > hl).all()), "every cap centroid above the hairline")
        r = np.linalg.norm(P[n_hair:] - [0, 1.6, 0], axis=1)
        check(bool(np.all(np.abs(r - 0.1015) <= 0.0005)), f"cap offset 1.5 mm (radius {r.min():.5f}..{r.max():.5f})")
        Jc, Wc = np.asarray(g.joints[n_hair:]), np.asarray(g.weights[n_hair:])
        head_i = g.joint_names.index("mixamorig:Head")
        check(bool(np.all(Jc[:, 0] == head_i) and np.all(Wc[:, 0] == 1) and np.all(Wc[:, 1:] == 0)),
              "cap weighted Head 1")
        B = body_arrays(body)
        check(abs(rep["cranium"]["chin_y"] - 1.45) < 1e-6
              and int((dense_weights(B)[:, joint_index(B, "head")] > 0.5).sum()) > 0, "chin 1.45")
        B2 = body_arrays(body_glb(inner_wall=True))
        Xh = np.asarray(g.positions[:n_hair])
        sdf2 = body_sdf(B2.positions, B2.faces, vox=VOX_M,
                        bounds=(Xh.min(0) - SDF_MARGIN_M, Xh.max(0) + SDF_MARGIN_M))
        V2, F2, _, hl2, info2 = gh._scalp_cap(B2, dense_weights(B2)[:, joint_index(B2, "head")], Xh, sdf2)
        r2 = np.linalg.norm(V2 - [0, 1.6, 0], axis=1)
        inner_want = centroid_count(0.094, hl2)
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
        check(not res.ok and len(res.reasons) == 1 and res.reasons[0].startswith("moved_share")
              and m["moved_share"] > 0.9, f"the inner-layer fit refuses on moved_share: {res.reasons}")
        plain_nohead, plain_proxy = hair_glbs(inner=False)
        pf = gh.fit_hairdeck(plain_nohead, plain_proxy, body, colour_target=None)
        check(pf.metrics["max_push_m"] == 0 and pf.metrics["moved_share"] == 0 and pf.ok and not pf.reasons,
              f"the plain shell is not pushed and passes ({pf.metrics['max_push_m']}, "
              f"{pf.metrics['moved_share']}, {pf.reasons})")

    print("ALL OK" if not FAILS else "FAILED: " + ", ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
