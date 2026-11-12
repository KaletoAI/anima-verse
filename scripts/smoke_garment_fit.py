#!/usr/bin/env python3
"""Garment fit math (``app/core/garment_fit.py``) on synthetic meshes, expectations derived by hand.

Usage: ./.venv/bin/python scripts/smoke_garment_fit.py

No world, no server, no external assets: every mesh below is built in this file.

The hair edit chain's parts — ``align_depth``, ``transfer``, the hair metrics (bib, poke, scalp) and ``fit_hair``
— are gone with that method (hair-from-body spec 2026-11-11, Task 2), and so are their sections (c), (e), (f).

(w) Weld + components.
    Two triangles share an edge through duplicated seam vertices (same position, other UV): 6 vertices weld to 4,
    both faces survive, a face that collapses onto two welded vertices is dropped.
    Three loose squares with areas 0.99, 0.009 and 0.001 (shares of the total 1.0): the largest share is 0.99;
    ``drop_small`` at the default 0.002 removes only the 0.001 square; at 0.01 it removes the 0.009 one too.

(a) Framing (spike ``mmap``: mesh units per pixel = mesh height / mask pixel height).
    Body mesh bbox y [0, 1.0], x [-0.2, 0.2], z [-0.1, 0.1]; body mask bbox x [400, 600), y [100, 900)
    -> s_b = 1.0 / 800, body mask centre (500, 500), body mesh centre (0, 0.5, 0).
    Garment mesh bbox y [-1, 1], x [-0.5, 0.5], z [-0.1, 0.1]; garment mask x [450, 550), y [100, 300)
    -> s_d = 2 / 200 = 0.01, mask centre (500, 200), mesh centre (0, 0, 0).
    Vertex (0.5, 1.0, 0): px = 500 + 0.5 / 0.01 = 550, py = 200 - 1.0 / 0.01 = 100
    -> x = 0 + (550 - 500) / 800 = 0.0625, y = 0.5 - (100 - 500) / 800 = 1.0, z = 0.
    The z scale equals the xy scale s_b / s_d = 0.125: vertex (0, 0, 0.1) -> z 0.0125.

(b) Push-out on a double-walled sphere head.
    Body = outer UV sphere R 0.100 at (0, 0.9, 0) + inner sphere R 0.098 with reversed winding (normals and winding
    are never trusted: the voxel fill closes both walls into one solid). Units: clear 0.004, vox 0.002.
    The SDF's zero level is the body surface, so a vertex ends at radius R + clear = 0.104.
    - An inner cap shell (elevation >= 0) at r 0.095 ends at r = 0.104 +- 0.001.
    - An outer cap shell at r 0.120 has clearance 0.020 > 0.004 and stays put (+- 1e-6).
    - Spread 0.005, outer shell at 0.107 instead: after the first push the inner shell is at 0.104, 0.003 below the
      outer one (< 0.005), so the outer one takes the inner displacement 0.009 and ends at 0.116 +- 0.0015.
      Without spread it has clearance 0.007 > 0.004 and stays at 0.107.
    The caps use 3-degree steps (31 rings, 120 longitudes): the displacement is smoothed 6 passes in each of the
    first 6 iterations, and averaging radial vectors 3 degrees apart keeps (1 + cos 3deg) / 2 = 0.99931 of the
    magnitude per pass, 0.99931^36 = 0.975 overall, so the outer shell (never pushed again once it is clear) keeps
    ~0.975 * 0.0087 = 0.0085 (the first push comes from the voxel EDT inside, ~0.3 voxel short) -> ~0.1155,
    inside the tolerance (6-degree steps would lose 9 %).

(d) Weights (collision ruling C7, 2026-11-10). Rig Hips, Spine2, Neck, Head, LeftShoulder, RightShoulder:
    Head vertices on a column at x 0, y 1.45..1.70 -> chin 1.45, crown 1.70, ear line 1.45 + 0.25 x 0.25 = 1.5125;
    LeftShoulder-dominated vertices at x 0.10 up to y 1.44, RightShoulder up to 1.42 -> shoulder top (1.44 + 1.42) / 2
    = 1.43; Spine2 below. t = (1.5125 - y) / 0.0825, s = t^2 (3 - 2t), Head (1-s)^2, Neck 2s(1-s), Spine2 s^2:
    y 1.60 and 1.5125 -> Head 1; y 1.491875 (t 0.25, s 0.15625) -> Head 0.711914 / Neck 0.263672 / Spine2 0.024414;
    y 1.47125 (t 0.5, s 0.5) -> 0.25 / 0.5 / 0.25; y 1.43 and 1.30 -> Spine2 1. Names [Head, Neck, Spine2].
    Reduced rig (Hips, Spine2, Head; grid x +-0.05, y 1.00..1.70 step 0.005, Head at y >= 1.45): no Shoulder bone ->
    shoulder top = the highest Spine2 vertex 1.445; no Neck -> Spine2 takes the Neck share: y 1.47875 (t 0.5) ->
    Head 0.25 / Spine2 0.75. Shoulder vertices raised by 0.17 (top 1.60, above the ear line) -> refused.

(g) A hollow body is sealed (``body_sdf`` / ``_seal_cavities``, 2026-11-10). A closed cylinder r 0.10 (y 0.80..1.40)
    and inside it a closed cylinder r 0.09 (y 0.81..1.39) — a shell 1 cm thick around a cavity — with both walls
    opened by a slit: the faces whose centre has z > 0 and |x| < 0.0105 between y 1.00 and 1.20 (64 segments of
    9.8 mm / 8.8 mm: both triangles of the two segments either side of angle 90 deg — centres at |x| 3.3 and 6.5 mm
    outside, the next segment's from 11.7 mm — go, a slit ~2 cm wide). vox 0.004: the dilated surface (one
    voxel) leaves ~1.2 cm of it open, so the hole fill keeps only the wall. The probe (0.05, 1.30, 0) lies in the
    cavity and off every axis line through the slit (the slit is at x ~ 0, y 1.00..1.20).
    - Without the seal (``_seal_cavities`` AND ``fit_kernels.fill_slices`` replaced by the identity — since
      fit-sdf-speed-drape Task 1 every slice along x, y and z is hole-filled in 2D too, and the probe's y-slice at
      1.30 is two complete rings that fill alone): the probe reads OUTSIDE, sdf > 0 (it lies 0.09 - 0.05 = 0.04
      from the inner wall).
    - With it: the cavity (18 cm across, > 2 x 10 + 1 voxels = 8.4 cm) is enclosed along all six axis directions ->
      inside; the nearest outside is the outer surface 0.10 - 0.05 = 0.05 away (the slit's column at x ~ 0 lies
      sqrt(0.05^2 + 0.1^2) = 0.11 away) -> sdf < -0.03.
    - The closed double-walled head of (b) gains nothing: the field with and without the seal (and the slice
      fill) is identical.
"""
import io
import json
import math
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

FAILS = []


def check(cond, label):
    print(("OK   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


# --- synthetic meshes --------------------------------------------------------

def uv_sphere(radius, centre, nlat=48, nlon=96, flip=False):
    lat = np.linspace(-np.pi / 2, np.pi / 2, nlat + 1)
    lon = np.linspace(0, 2 * np.pi, nlon, endpoint=False)
    la, lo = np.meshgrid(lat, lon, indexing="ij")
    P = np.stack([np.cos(la) * np.cos(lo), np.sin(la), np.cos(la) * np.sin(lo)], -1).reshape(-1, 3)
    P = P * radius + np.asarray(centre, float)
    F = []
    for i in range(nlat):
        for j in range(nlon):
            a, b = i * nlon + j, i * nlon + (j + 1) % nlon
            c, d = (i + 1) * nlon + (j + 1) % nlon, (i + 1) * nlon + j
            F += [(a, b, c), (a, c, d)]
    F = np.array(F)
    return P, (F[:, ::-1] if flip else F)


def cap(radius, centre, n_el=16, nlon=60):
    """Upper half sphere shell (elevation 0..90 degrees in n_el rings), same angular grid for every radius."""
    el = np.radians(np.linspace(0, 90, n_el))
    lon = np.radians(np.arange(nlon) * 360 / nlon)
    e, lo = np.meshgrid(el, lon, indexing="ij")
    P = np.stack([np.cos(e) * np.cos(lo), np.sin(e), np.cos(e) * np.sin(lo)], -1).reshape(-1, 3)
    P = P * radius + np.asarray(centre, float)
    F = []
    for i in range(n_el - 1):
        for j in range(nlon):
            a, b = i * nlon + j, i * nlon + (j + 1) % nlon
            c, d = (i + 1) * nlon + (j + 1) % nlon, (i + 1) * nlon + j
            F += [(a, b, c), (a, c, d)]
    return P, np.array(F)


def cylinder(radius, y0, y1, nseg=64, nrings=20):
    """Closed cylinder around the y axis (side + two fan caps)."""
    ys = np.linspace(y0, y1, nrings)
    ang = np.arange(nseg) * 2 * np.pi / nseg
    side = np.array([(radius * math.cos(a), y, radius * math.sin(a)) for y in ys for a in ang])
    F = []
    for i in range(nrings - 1):
        for j in range(nseg):
            a, b = i * nseg + j, i * nseg + (j + 1) % nseg
            c, d = (i + 1) * nseg + (j + 1) % nseg, (i + 1) * nseg + j
            F += [(a, b, c), (a, c, d)]
    P = list(side)
    for y, ring in ((y0, 0), (y1, nrings - 1)):
        rings = []
        for r in np.linspace(radius, 0, 12)[1:]:
            rings.append(len(P))
            P += [(r * math.cos(a), y, r * math.sin(a)) for a in ang]
        prev = ring * nseg
        for start in rings:
            for j in range(nseg):
                a, b = prev + j, prev + (j + 1) % nseg
                c, d = start + (j + 1) % nseg, start + j
                F += [(a, b, c), (a, c, d)]
            prev = start
    return np.array(P, float), np.array(F)


def merge(*parts):
    P, F, off = [], [], 0
    for p, f in parts:
        P.append(p)
        F.append(f + off)
        off += len(p)
    return np.concatenate(P), np.concatenate(F)


def head_body():
    outer = uv_sphere(0.100, (0, 0.9, 0))
    inner = uv_sphere(0.098, (0, 0.9, 0), flip=True)
    return merge(outer, inner)


def body_mesh(P, F, head_mask, names=("mixamorig:Hips", "mixamorig:Spine2", "mixamorig:Head")):
    from app.core.glb_mesh import BodyMesh
    n = len(P)
    J = np.zeros((n, 4), np.int64)
    W = np.zeros((n, 4))
    J[:, 0] = np.where(head_mask, 2, 1)
    W[:, 0] = 1.0
    uv = np.stack([(np.arange(n) % 1000) / 1000.0, (np.arange(n) // 1000) / 1000.0], 1)
    return BodyMesh(positions=P.astype(float), faces=F.astype(np.int64), uvs=uv,
                    joints=J, weights=W, joint_names=list(names))


def radii(X, centre):
    return np.linalg.norm(X - np.asarray(centre, float), axis=1)


# --- (w) weld + components -----------------------------------------------------

def test_weld():
    from app.core import garment_fit as gf
    P = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0],          # triangle A
                  [1, 0, 0], [0, 1, 0], [1, 1, 0],          # triangle B, seam duplicates of A's 1 and 2
                  [1, 0, 0.0000001]], float)                 # rounds onto vertex 1
    F = np.array([[0, 1, 2], [3, 5, 4], [1, 6, 2]])
    U = np.arange(14, dtype=float).reshape(7, 2)
    Pw, Fw, inv = gf.weld(P, F, U)
    check(len(Pw) == 4, f"weld: 7 vertices -> 4 (got {len(Pw)})")
    check(len(Fw) == 2, f"weld: degenerate face dropped, 2 faces left (got {len(Fw)})")
    check(np.allclose(Pw[inv], np.round(P, 6), atol=1e-6), "weld: inv maps every vertex onto its welded twin")

    def square(x0, side):
        p = np.array([[x0, 0, 0], [x0 + side, 0, 0], [x0 + side, side, 0], [x0, side, 0]], float)
        return p, np.array([[0, 1, 2], [0, 2, 3]])
    Pc, Fc = merge(square(0, math.sqrt(0.99)), square(5, math.sqrt(0.009)), square(9, math.sqrt(0.001)))
    labels, share = gf.components(Pc, Fc)
    check(len(share) == 3 and abs(share.max() - 0.99) < 1e-9, f"components: largest share 0.99 (got {share.max():.4f})")
    check(len(set(labels.tolist())) == 3, "components: three labels")
    Pk, Fk, keep = gf.drop_small(Pc, Fc)
    check(len(Fk) == 4 and len(Pk) == 8, f"drop_small(0.002): only the 0.001 square goes ({len(Fk)} faces)")
    check(np.array_equal(Pk, Pc[keep]), "drop_small: keep indexes the kept vertices")
    Pk, Fk, keep = gf.drop_small(Pc, Fc, min_share=0.01)
    check(len(Fk) == 2 and len(Pk) == 4, f"drop_small(0.01): 0.009 square goes too ({len(Fk)} faces)")


# --- (a) framing ------------------------------------------------------------------

def test_framing():
    from app.core import garment_fit as gf
    body = np.array([[x, y, z] for x in (-0.2, 0.2) for y in (0.0, 1.0) for z in (-0.1, 0.1)])
    bm = np.zeros((1000, 1000), bool)
    bm[100:900, 400:600] = True
    gar = np.array([[x, y, z] for x in (-0.5, 0.5) for y in (-1.0, 1.0) for z in (-0.1, 0.1)]
                   + [[0.5, 1.0, 0.0], [0.0, 0.0, 0.1]])
    gm = np.zeros((1000, 1000), bool)
    gm[100:300, 450:550] = True
    Q = gf.place_by_framing(gar, body, bm, gm)
    check(np.allclose(Q[8], [0.0625, 1.0, 0.0], atol=1e-9), f"framing: (0.5, 1, 0) -> (0.0625, 1, 0) (got {Q[8]})")
    check(abs(Q[9, 2] - 0.0125) < 1e-9, f"framing: z scale = xy scale 0.125 (got {Q[9, 2] / 0.1:.4f})")
    check(abs(np.ptp(Q[:, 0]) - 0.125) < 1e-9, "framing: garment width 1.0 -> 0.125")


# --- (b) push-out ----------------------------------------------------------------

def test_push():
    from app.core import garment_fit as gf
    c = np.array([0, 0.9, 0])
    Pb, Fb = head_body()
    sdf = gf.body_sdf(Pb, Fb, vox=0.002, bounds=(c - 0.15, c + 0.15))
    inner, outer = cap(0.095, c, n_el=31, nlon=120), cap(0.120, c, n_el=31, nlon=120)
    Q0, Fd = merge(inner, outer)
    Q, disp = gf.push_out(Q0, Fd, sdf, clear=0.004)
    n = len(inner[0])
    ri, ro = radii(Q[:n], c), radii(Q[n:], c)
    check(np.all(np.abs(ri - 0.104) <= 0.001), f"push: inner shell 0.095 -> 0.104 +- 0.001 "
          f"(got {ri.min():.4f}..{ri.max():.4f})")
    check(np.abs(Q[n:] - Q0[n:]).max() <= 1e-6, "push: outer shell at 0.120 unmoved")
    check(np.allclose(Q, Q0 + disp), "push: Q = Q0 + disp")

    Q0, Fd = merge(inner, cap(0.107, c, n_el=31, nlon=120))
    Q, _ = gf.push_out(Q0, Fd, sdf, clear=0.004, spread=0.005, spread_depth=0.3)
    ro = radii(Q[n:], c)
    check(np.all(np.abs(ro - 0.116) <= 0.0015), f"push+spread: outer shell 0.107 -> 0.116 +- 0.0015 "
          f"(got {ro.min():.4f}..{ro.max():.4f})")
    Q, _ = gf.push_out(Q0, Fd, sdf, clear=0.004)
    ro = radii(Q[n:], c)
    check(np.all(np.abs(ro - 0.107) <= 1e-6), f"push without spread: outer shell stays at 0.107 "
          f"(got {ro.min():.6f}..{ro.max():.6f})")
    return sdf


# --- (d) weights -------------------------------------------------------------------------

def test_weights():
    from app.core import garment_fit as gf
    from app.core.glb_mesh import BodyMesh
    names6 = ["mixamorig:Hips", "mixamorig:Spine2", "mixamorig:Neck", "mixamorig:Head", "mixamorig:LeftShoulder",
              "mixamorig:RightShoulder"]
    parts = [(np.array([[0, y, 0] for y in np.linspace(1.45, 1.70, 26)]), 3),
             (np.array([[0.10, y, 0] for y in np.linspace(1.38, 1.44, 7)]), 4),
             (np.array([[-0.10, y, 0] for y in np.linspace(1.38, 1.42, 5)]), 5),
             (np.array([[0, y, 0] for y in np.linspace(1.00, 1.40, 41)]), 1)]
    P = np.concatenate([p for p, _ in parts])
    Jb = np.zeros((len(P), 4), np.int64)
    Jb[:, 0] = np.concatenate([np.full(len(p), j) for p, j in parts])
    Wb = np.zeros((len(P), 4))
    Wb[:, 0] = 1
    br = BodyMesh(positions=P, faces=np.zeros((0, 3), np.int64), uvs=np.zeros((len(P), 2)), joints=Jb, weights=Wb,
                  joint_names=names6)
    check(abs(gf.ear_line_height(br) - 1.5125) < 1e-9, f"weights: ear line 1.5125 (got {gf.ear_line_height(br)})")
    check(abs(gf.shoulder_top_height(br) - 1.43) < 1e-9, f"weights: shoulder top 1.43 (got {gf.shoulder_top_height(br)})")
    ys = [1.60, 1.5125, 1.491875, 1.47125, 1.43, 1.30]
    names, J, W = gf.hair_weights(np.array([[0, y, 0] for y in ys]), br)
    check(names == ["mixamorig:Head", "mixamorig:Neck", "mixamorig:Spine2"],
          f"weights: joint names Head, Neck, Spine2 (got {names})")

    def w(row, name):
        return float(sum(W[row, k] for k in range(4) if names[J[row, k]] == name and W[row, k] > 0))
    want = [(1, 0, 0), (1, 0, 0), (0.711914, 0.263672, 0.024414), (0.25, 0.5, 0.25), (0, 0, 1), (0, 0, 1)]
    for row, (h, n, s2) in enumerate(want):
        got = (w(row, "mixamorig:Head"), w(row, "mixamorig:Neck"), w(row, "mixamorig:Spine2"))
        check(np.allclose(got, (h, n, s2), atol=1e-6),
              f"weights: y {ys[row]} -> Head {h} / Neck {n} / Spine2 {s2} (got {np.round(got, 6).tolist()})")
    check(np.allclose(W.sum(1), 1), "weights: rows sum to 1")

    grid = np.array([[x, y, 0.0] for y in np.linspace(1.0, 1.7, 141) for x in (-0.05, 0.05)])
    small = body_mesh(grid, np.zeros((0, 3), np.int64), grid[:, 1] >= 1.45 - 1e-9)
    check(abs(gf.shoulder_top_height(small) - 1.445) < 1e-9,
          f"weights: reduced rig shoulder top = highest Spine2 vertex 1.445 (got {gf.shoulder_top_height(small)})")
    names, J, W = gf.hair_weights(np.array([[0, 1.47875, 0]]), small)
    check(names == ["mixamorig:Head", "mixamorig:Spine2"] and np.allclose(W[0, :2], [0.25, 0.75]),
          f"weights: reduced rig y 1.47875 -> Head 0.25 / Spine2 0.75 (got {names} {np.round(W[0], 6).tolist()})")
    high = BodyMesh(positions=P + np.where(Jb[:, :1] >= 4, [0.0, 0.17, 0.0], 0.0), faces=br.faces, uvs=br.uvs,
                    joints=Jb, weights=Wb, joint_names=names6)   # shoulder tops 1.61 / 1.59 -> 1.60 > ear 1.5125
    try:
        gf.hair_weights(np.zeros((1, 3)), high)
        check(False, "weights: shoulder top above the ear line refused")
    except ValueError:
        check(True, "weights: shoulder top above the ear line refused")


# --- GLB fixture (also used by the chain smokes) ---------------------------------------

def make_glb(P, F, U, *, image=None, joints=None, weights=None, joint_names=None):
    blob = bytearray()
    doc = {"asset": {"version": "2.0"}, "bufferViews": [], "accessors": [], "scene": 0}

    def acc(arr, ctype, typ, target=None, minmax=False):
        raw = arr.tobytes()
        blob.extend(b"\0" * (-len(blob) % 4))
        view = {"buffer": 0, "byteOffset": len(blob), "byteLength": len(raw)}
        if target:
            view["target"] = target
        doc["bufferViews"].append(view)
        blob.extend(raw)
        a = {"bufferView": len(doc["bufferViews"]) - 1, "componentType": ctype, "count": len(arr), "type": typ}
        if minmax:
            a["min"], a["max"] = arr.min(0).tolist(), arr.max(0).tolist()
        doc["accessors"].append(a)
        return len(doc["accessors"]) - 1
    attrs = {"POSITION": acc(P.astype("<f4"), 5126, "VEC3", 34962, True),
             "TEXCOORD_0": acc(U.astype("<f4"), 5126, "VEC2", 34962)}
    if joints is not None:
        attrs["JOINTS_0"] = acc(joints.astype("<u2"), 5123, "VEC4", 34962)
        attrs["WEIGHTS_0"] = acc(weights.astype("<f4"), 5126, "VEC4", 34962)
    prim = {"attributes": attrs, "indices": acc(F.astype("<u4").reshape(-1), 5125, "SCALAR", 34963)}
    if image is not None:
        blob.extend(b"\0" * (-len(blob) % 4))
        doc["bufferViews"].append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(image)})
        blob.extend(image)
        doc["images"] = [{"bufferView": len(doc["bufferViews"]) - 1, "mimeType": "image/png"}]
        doc["textures"] = [{"source": 0}]
        doc["materials"] = [{"name": "hair", "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}},
                             "alphaMode": "BLEND", "doubleSided": True}]
        prim["material"] = 0
    doc["meshes"] = [{"primitives": [prim]}]
    doc["nodes"] = [{"name": "Body", "mesh": 0}]
    doc["scenes"] = [{"nodes": [0]}]
    if joint_names:
        doc["nodes"][0]["skin"] = 0
        doc["nodes"] += [{"name": n} for n in joint_names]
        doc["skins"] = [{"joints": list(range(1, 1 + len(joint_names)))}]
        doc["scenes"][0]["nodes"] += list(range(1, 1 + len(joint_names)))
    blob.extend(b"\0" * (-len(blob) % 4))
    doc["buffers"] = [{"byteLength": len(blob)}]
    raw = json.dumps(doc).encode()
    raw += b" " * (-len(raw) % 4)
    body = struct.pack("<II", len(raw), 0x4E4F534A) + raw + struct.pack("<II", len(blob), 0x004E4942) + bytes(blob)
    return b"glTF" + struct.pack("<II", 2, 12 + len(body)) + body


def png(size=16):
    """A small solid PNG (smoke_garment_clothing_fit's texture image)."""
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (size, size), (120, 80, 40)).save(out, "PNG")
    return out.getvalue()


def test_seal():
    from app.core import garment_fit as gf
    outer = cylinder(0.10, 0.80, 1.40, nseg=64, nrings=61)
    inner = cylinder(0.09, 0.81, 1.39, nseg=64, nrings=59)
    P, F = merge(outer, inner)
    centre = P[F].mean(1)
    slit = (centre[:, 2] > 0) & (np.abs(centre[:, 0]) < 0.0105) & (centre[:, 1] > 1.0) & (centre[:, 1] < 1.2)
    F = F[~slit]
    check(int(slit.sum()) > 0, f"seal: the slit removes faces ({int(slit.sum())})")
    probe = np.array([[0.05, 1.30, 0.0]])
    bounds = (np.array([-0.15, 0.75, -0.15]), np.array([0.15, 1.45, 0.15]))
    from app.core import fit_kernels
    real, real_slices = gf._seal_cavities, fit_kernels.fill_slices

    def unsealed_field(*args, **kwargs):
        try:
            gf._seal_cavities = lambda surf, inside, **_kw: inside
            fit_kernels.fill_slices = lambda surf, axis: surf
            return gf.body_sdf(*args, **kwargs)
        finally:
            gf._seal_cavities, fit_kernels.fill_slices = real, real_slices
    unsealed = float(unsealed_field(P, F, vox=0.004, bounds=bounds).sample(probe)[0])
    sealed = float(gf.body_sdf(P, F, vox=0.004, bounds=bounds).sample(probe)[0])
    check(unsealed > 0, f"seal: without it the cavity reads outside (sdf {unsealed:+.4f} > 0)")
    check(sealed < -0.03, f"seal: with it the cavity is inside (sdf {sealed:+.4f} < -0.03)")
    Pb, Fb = head_body()
    c = np.array([0, 0.9, 0])
    with_seal = gf.body_sdf(Pb, Fb, vox=0.002, bounds=(c - 0.15, c + 0.15)).field
    without = unsealed_field(Pb, Fb, vox=0.002, bounds=(c - 0.15, c + 0.15)).field
    check(np.array_equal(with_seal, without), "seal: the closed double-walled head is unchanged")


def main():
    test_weld()
    test_framing()
    test_push()
    test_weights()
    test_seal()
    if FAILS:
        print(f"\n{len(FAILS)} FAILED")
        sys.exit(1)
    print("\nALL OK")


if __name__ == "__main__":
    main()
