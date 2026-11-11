"""Scalp tint under the hair (``app/core/hair_scalp_tint.py``), expectations derived by hand below.

Usage: ./.venv/bin/python scripts/smoke_hair_scalp_tint.py
No server, no world, no hub, no GPU.

GEOMETRY (metres, bind space, +z = the face)
  Head: a sphere R 0.1 at (0, 1.6, 0), 90 latitude rows x 181 longitude columns (the seam column duplicated at the
  BACK, phi = +-pi), point (R cos la sin phi, 1.6 + R sin la, R cos la cos phi); UV u = (phi + pi) / 2 pi,
  v = (pi/2 - la) / pi; a white 1024 x 512 PNG. All of it Head-weighted; a neck cylinder r 0.04 y 1.30 .. 1.55
  (Head from y 1.45 up, Spine2 below) as in smoke_garment_hairdeck_fit -> chin 1.45, top 1.7. The sphere has no
  face profile -> landmarks "none" -> the proportions' brow: 1.45 + FALLBACK_BROW_RATIO 0.6 x 0.25 = 1.60; the tint
  starts at 1.60 + TINT_ABOVE_BROW_M 0.01 = 1.61.
  Hair (vertex colours linear 0.2 -> sRGB 1.055 x 0.2^(1/2.4) - 0.055 = 0.48452 -> 123.55):
    plate A z 0.12, x -0.05 .. 0.0, y 1.64 .. 1.75; plate B z 0.12, x 0.02 .. 0.06, y 1.50 .. 1.75.
  From the front both plates lie in front of the sphere (its front z <= 0.1) -> covered cells = the plates.

EXPECTED, BY HAND (texel = the nearest to the front-sphere point (x, y))
  [1] A covered texel (x -0.025, y 1.66): weight 1 -> 123.55 -> 124 (+-1).
  [2] The fade below plate A at x -0.025: y 1.6375 is 2.5 mm below its edge -> weight 1 - 2.5 / 5 = 0.5 ->
      0.5 x 255 + 0.5 x 123.55 = 189.3 (+- 30: the 1 mm cells move the distance by up to 1.4 mm = 0.28 of weight);
      y 1.62 (20 mm below) -> 255.
  [3] Plate B reaches below the brow line: y 1.58 (< 1.61) stays 255; y 1.63 -> 124 (+-1).
  [4] Not seen from the front: the back point (x 0.01, y 1.66, z < 0) stays 255; x 0.075 at y 1.64 (15 mm beside
      plate B) stays 255.
  [5] The GLB stays valid: positions identical, the image PNG; a hair without colours or image -> skipped
      "no_hair_colour", bytes unchanged.
"""
import io
import json
import math
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402

FAILS = []
R, C = 0.1, np.array([0.0, 1.6, 0.0])
W, H = 1024, 512


def check(label, ok):
    print(("OK   " if ok else "FAIL ") + label)
    if not ok:
        FAILS.append(label)


def head_sphere(nlat=90, nlon=180):
    la = np.linspace(-np.pi / 2, np.pi / 2, nlat + 1)
    phi = np.linspace(-np.pi, np.pi, nlon + 1)
    L, Ph = np.meshgrid(la, phi, indexing="ij")
    P = np.stack([R * np.cos(L) * np.sin(Ph), C[1] + R * np.sin(L), R * np.cos(L) * np.cos(Ph)], -1).reshape(-1, 3)
    UV = np.stack([(Ph + np.pi) / (2 * np.pi), (np.pi / 2 - L) / np.pi], -1).reshape(-1, 2)
    F = []
    for i in range(nlat):
        for j in range(nlon):
            a, b = i * (nlon + 1) + j, i * (nlon + 1) + j + 1
            c, d = (i + 1) * (nlon + 1) + j + 1, (i + 1) * (nlon + 1) + j
            F += [(a, c, b), (a, d, c)]
    return P, np.array(F), UV


def body_glb():
    import smoke_garment_hairdeck_fit as hd
    from PIL import Image
    Ps, Fs, Us = head_sphere()
    Pc, Fc = hd.cylinder(0.04, [1.30, 1.35, 1.40, 1.45, 1.50, 1.55], 48)
    P = np.vstack([Ps, Pc])
    F = np.vstack([Fs, Fc + len(Ps)])
    U = np.vstack([Us, np.full((len(Pc), 2), 0.999)])
    head = np.r_[np.ones(len(Ps), bool), Pc[:, 1] >= 1.45 - 1e-9]
    J = np.zeros((len(P), 4), "<u2")
    J[:, 0] = np.where(head, 2, 1)
    Wt = np.zeros((len(P), 4), "<f4")
    Wt[:, 0] = 1
    b = hd.Builder()
    attrs = {"POSITION": b.add(P.astype("<f4"), 5126, "VEC3", minmax=True),
             "TEXCOORD_0": b.add(U.astype("<f4"), 5126, "VEC2"),
             "JOINTS_0": b.add(J, 5123, "VEC4"), "WEIGHTS_0": b.add(Wt, 5126, "VEC4")}
    ind = b.add(F.astype("<u4").ravel(), 5125, "SCALAR")
    png = io.BytesIO()
    Image.new("RGB", (W, H), (255, 255, 255)).save(png, format="PNG")
    raw = png.getvalue()
    b.blob.extend(b"\0" * (-len(b.blob) % 4))
    b.views.append({"buffer": 0, "byteOffset": len(b.blob), "byteLength": len(raw)})
    b.blob.extend(raw)
    nodes = [{"name": "Armature", "children": [1, 2]},
             {"name": "Body", "mesh": 0, "skin": 0},
             {"name": "mixamorig:Hips", "children": [3]},
             {"name": "mixamorig:Spine2", "children": [4], "translation": [0, 1.3, 0]},
             {"name": "mixamorig:Head", "translation": [0, 0.2, 0]}]
    doc = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}], "nodes": nodes,
           "meshes": [{"name": "Body", "primitives": [{"attributes": attrs, "indices": ind, "material": 0}]}],
           "skins": [{"joints": [2, 3, 4]}],
           "materials": [{"name": "Skin", "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}],
           "textures": [{"source": 0}],
           "images": [{"bufferView": len(b.views) - 1, "mimeType": "image/png"}]}
    return b.glb(doc)


def plate(x0, x1, y0, y1, z=0.12, n=20):
    xs, ys = np.linspace(x0, x1, n + 1), np.linspace(y0, y1, n + 1)
    X, Y = np.meshgrid(xs, ys)
    P = np.stack([X.ravel(), Y.ravel(), np.full(X.size, z)], 1)
    F = []
    for i in range(n):
        for j in range(n):
            a, b, c, d = i * (n + 1) + j, i * (n + 1) + j + 1, (i + 1) * (n + 1) + j + 1, (i + 1) * (n + 1) + j
            F += [(a, b, c), (a, c, d)]
    return P, np.array(F)


def hair_mesh(colours=True):
    from app.core.glb_mesh import GarmentMesh
    pa, fa = plate(-0.05, 0.0, 1.64, 1.75)
    pb, fb = plate(0.02, 0.06, 1.50, 1.75)
    P = np.vstack([pa, pb])
    F = np.vstack([fa, fb + len(pa)])
    n = len(P)
    return GarmentMesh(positions=P, normals=np.tile([0.0, 0.0, 1.0], (n, 1)), uvs=np.zeros((n, 2)), indices=F,
                       joints=np.zeros((n, 4), np.int64), weights=np.tile([1.0, 0, 0, 0], (n, 1)),
                       joint_names=["mixamorig:Head"], image=b"", mime="", material={},
                       colors=np.tile([0.2, 0.2, 0.2, 1.0], (n, 1)) if colours else None)


def texel_at(tex, x, y, front=True):
    la = math.asin((y - C[1]) / R)
    phi = math.asin(x / (R * math.cos(la)))
    if not front:
        phi = math.pi - phi if phi >= 0 else -math.pi - phi
    u, v = (phi + math.pi) / (2 * math.pi), (math.pi / 2 - la) / math.pi
    return float(tex[int(round(v * H - 0.5)), int(round(u * W - 0.5)), 0])


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="scalp-tint-") as tmp:
        os.environ["STORAGE_DIR"] = str(Path(tmp) / "world")
        os.environ["INSTANCE_DIR"] = str(Path(tmp) / "instance")
        from app.core import paths
        paths.init(Path(tmp) / "world")
        from PIL import Image
        from app.core import glb_mesh
        from app.core.hair_scalp_tint import tint_scalp
        from app.core.model_validate import parse_glb
        glb = body_glb()
        out, rep = tint_scalp(glb, hair_mesh())
        print("       report", json.dumps(rep))
        parsed = parse_glb(out)
        img = parsed["gltf"]["images"][0]
        view = parsed["gltf"]["bufferViews"][img["bufferView"]]
        start = int(view.get("byteOffset", 0))
        tex = np.asarray(Image.open(io.BytesIO(bytes(parsed["bin"][start:start + view["byteLength"]]))).convert("RGB"),
                         np.float64)
        print("[1] covered")
        v = texel_at(tex, -0.025, 1.66)
        check(f"plate A at y 1.66: {v} = 124 +- 1", abs(v - 124) <= 1)
        check(f"brow line from proportions 1.60 ({rep.get('brow_y')}, {rep.get('landmarks')})",
              rep.get("landmarks") == "none" and abs(rep.get("brow_y", 0) - 1.60) < 1e-6)
        print("[2] fade below the edge")
        v = texel_at(tex, -0.025, 1.6375)
        check(f"2.5 mm below plate A: {v} = 189.3 +- 30", abs(v - 189.3) <= 30)
        v = texel_at(tex, -0.025, 1.62)
        check(f"20 mm below plate A: {v} = 255", v == 255)
        print("[3] the brow line")
        v = texel_at(tex, 0.04, 1.58)
        check(f"plate B below the brow line (y 1.58): {v} = 255", v == 255)
        v = texel_at(tex, 0.04, 1.63)
        check(f"plate B above it (y 1.63): {v} = 124 +- 1", abs(v - 124) <= 1)
        print("[4] not seen from the front")
        v = texel_at(tex, 0.01, 1.66, front=False)
        check(f"the back at y 1.66: {v} = 255", v == 255)
        v = texel_at(tex, 0.075, 1.64)
        check(f"x 0.075, 15 mm beside plate B: {v} = 255", v == 255)
        print("[5] the GLB")
        same = np.array_equal(glb_mesh.body_arrays(out).positions, glb_mesh.body_arrays(glb).positions)
        check("positions identical, image PNG", same and img.get("mimeType") == "image/png")
        out2, rep2 = tint_scalp(glb, hair_mesh(colours=False))
        check(f"no colours, no image: skipped {rep2}", rep2.get("skipped") == "no_hair_colour" and out2 == glb)
    print("ALL OK" if not FAILS else "FAILED: " + ", ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
