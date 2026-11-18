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
  [6] Only the hair over the raster is sampled, in chunks (review 07b#3). The raster on this head: x0 = the head's
      x min -0.1 - 0.01 = -0.11, y0 = 1.61 - TINT_FADE_M 0.005 - 0.01 = 1.595, rows ceil((1.70 + 0.01 - 1.595) /
      0.001) = 115 (to y 1.71), cols ceil((0.1 + 0.01 + 0.11) / 0.001) = ceil(220) — 220, or 221 when the float
      quotient lands a hair above 220 (to x 0.11 or 0.111). Cards as HairDeck's (``garment_hairdeck`` keeps them as
      separate pieces; a fitted real HairDeck hair has a median triangle edge of 14 mm): vertical strips 2 cm wide,
      16 rows x 3 columns of quads, at z 0.11 (in front of the sphere), x centres
      spread over -0.09 .. 0.07, the root row at y 1.70 (card c offset +0.1 mm x (c mod 7) in z).
      "old" = the previous code's composition ``_front_raster(_surface_samples(hair, TINT_CELL_M / 2), ...)``
      patched in for ``_surface_raster``.
      (a) 60 cards 10 cm long (y 1.60 .. 1.70: every triangle inside the raster): tinted GLB bytes and report
          IDENTICAL to "old" (all triangles kept; the per-cell maximum does not depend on the chunking).
      (b) The same 60 cards 30 cm long (y 1.40 .. 1.70; rows 1.875 cm: rows 0..5 reach y >= y0 - 1 cell = 1.594 —
          row 5's top 1.70 - 5 x 0.01875 = 1.60625, row 6's 1.5875 — so 10 of 16 rows hang outside and are never
          sampled): the front-hair grid and the tinted GLB again IDENTICAL to "old" — what is not sampled is exactly
          what ``_front_raster`` never kept. Nothing differs, not only "inside the band". The hanging part alone
          (the 60 cards' rows 6..15: root y 1.5875, 18.75 cm, 10 rows = 3600 triangles, each 861 samples as in (c)
          -> 3.1 M points if sampled) is not sampled at all: the grid stays empty and the peak stays under the
          per-triangle term of (c) plus 1 MiB = 600 x 3600 + 1 MiB = 3.06 MiB — one sampled chunk alone would be
          6 MiB.
      (c) Peak memory (tracemalloc) of ``_surface_raster`` on the reviewer's hair: 400 cards 30 cm x 2 cm, 16 x 3
          quads = 38 400 triangles. Each triangle: edge = the quad diagonal sqrt(0.02/3 ^ 2 + 0.01875 ^ 2) = 19.9 mm
          -> n = ceil(19.9 / 0.5) = 40 -> 41 x 42 / 2 = 861 samples; the old code held them all at once:
          38 400 x 861 = 33.06 M points x 24 B = 757 MiB for the sample array alone. The bound now, by counting
          arrays: per input triangle N at most 600 B (T = P[F] 72, lo/hi 48, the filtered F/T copies 96, the edge
          temporaries: roll + difference 144, norms 24 + 8 + 8, np.unique of the corners ~56, masks ~8 -> 464,
          rounded up); per chunk point at most 80 B with M = SAMPLE_CHUNK_POINTS (the sample array 24 + the
          expression's two other live temporaries 48, or in the splat the sample array 24 + ix / iy 16 + one float
          temporary 8 + the fancy-indexed copies 24 + masks ~4 = 76); the grid 8 B x 115 x 221; plus 1 MiB for the
          small arrays -> 600 x 38 400 + 80 x 262 144 + 8 x 25 415 + 1 MiB = 23.0 + 21.0 + 0.2 + 1.0 MiB ~ 43.2 MiB.
          Measured peak <= that bound (and so < 757 MiB / 17).
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


def cards(count, length, *, x_from=-0.09, x_to=0.07, y_top=1.70, z=0.11, width=0.02, rows=16, cols=3):
    """``count`` HairDeck-like cards (block [6]) as a coloured ``GarmentMesh``: vertical strips ``width`` wide,
    ``rows`` x ``cols`` quads, root row at ``y_top``, hanging ``length``; x centres evenly over ``x_from .. x_to``."""
    from app.core.glb_mesh import GarmentMesh
    P, F = [], []
    for c, xc in enumerate(np.linspace(x_from, x_to, count)):
        base = len(P)
        for r in range(rows + 1):
            for k in range(cols + 1):
                P.append((xc - width / 2 + k * width / cols, y_top - r * length / rows, z + 0.0001 * (c % 7)))
        for r in range(rows):
            for k in range(cols):
                a = base + r * (cols + 1) + k
                b, d, e = a + 1, a + cols + 1, a + cols + 2
                F += [(a, d, b), (b, d, e)]
    P, F = np.array(P, np.float64), np.array(F, np.int64)
    n = len(P)
    return GarmentMesh(positions=P, normals=np.tile([0.0, 0.0, 1.0], (n, 1)), uvs=np.zeros((n, 2)), indices=F,
                       joints=np.zeros((n, 4), np.int64), weights=np.tile([1.0, 0, 0, 0], (n, 1)),
                       joint_names=["mixamorig:Head"], image=b"", mime="", material={},
                       colors=np.tile([0.2, 0.2, 0.2, 1.0], (n, 1)))


def bounded(glb: bytes) -> None:
    """Block [6] of the docstring."""
    import tracemalloc
    from app.core import hair_scalp_tint as hst
    new_raster = hst._surface_raster
    seen = {}

    def old_raster(P, F, step_m, x0, y0, shape):
        return hst._front_raster(hst._surface_samples(P, F, step_m), x0, y0, shape)

    def spy(fn, key):
        def run(P, F, step_m, x0, y0, shape):
            seen[key] = (fn(P, F, step_m, x0, y0, shape), (x0, y0, shape))
            return seen[key][0]
        return run

    def both(hair):
        try:
            hst._surface_raster = spy(new_raster, "new")
            got = hst.tint_scalp(glb, hair)
            hst._surface_raster = spy(old_raster, "old")
            was = hst.tint_scalp(glb, hair)
        finally:
            hst._surface_raster = new_raster
        return got, was

    print("[6] only the hair over the raster, in chunks")
    (out_a, rep_a), (old_a, oldrep_a) = both(cards(60, 0.10))
    x0, y0, shape = seen["new"][1]
    check(f"raster x0 -0.11 / y0 1.595 / 115 x 220-221: {x0:.5f} / {y0:.5f} / {shape}",
          abs(x0 + 0.11) < 1e-6 and abs(y0 - 1.595) < 1e-6 and shape[0] == 115 and shape[1] in (220, 221))
    check(f"(a) hair inside the raster: tint identical to the old code ({rep_a.get('covered_cells')} covered cells)",
          out_a == old_a and rep_a == oldrep_a and rep_a.get("covered_cells", 0) > 0
          and np.array_equal(seen["new"][0], seen["old"][0]))
    (out_b, rep_b), (old_b, oldrep_b) = both(cards(60, 0.30))
    check(f"(b) 30 cm cards, 10 of 16 rows never sampled: grid and tint identical ({rep_b.get('covered_cells')} cells)",
          np.array_equal(seen["new"][0], seen["old"][0]) and out_b == old_b and rep_b == oldrep_b)
    hanging = cards(60, 0.30 * 10 / 16, y_top=1.70 - 6 * 0.30 / 16, rows=10)
    Fh = np.asarray(hanging.indices).reshape(-1, 3)
    tracemalloc.start()
    grid_h = new_raster(np.asarray(hanging.positions, np.float64), Fh, hst.TINT_CELL_M / 2, x0, y0, shape)
    peak_h = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    check(f"(b) the hanging rows alone ({len(Fh)} triangles): nothing sampled — grid empty, peak "
          f"{peak_h / 2 ** 20:.2f} MiB <= 3.06 MiB",
          len(Fh) == 3600 and not np.isfinite(grid_h).any() and peak_h <= 600 * len(Fh) + 2 ** 20)
    big = cards(400, 0.30)
    F = np.asarray(big.indices).reshape(-1, 3)
    P = np.asarray(big.positions, np.float64)
    tracemalloc.start()
    grid = new_raster(P, F, hst.TINT_CELL_M / 2, x0, y0, shape)
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    bound = 600 * len(F) + 80 * hst.SAMPLE_CHUNK_POINTS + 8 * shape[0] * shape[1] + 2 ** 20
    check(f"(c) 400 cards = 38400 triangles ({len(F)}): peak {peak / 2 ** 20:.1f} MiB <= bound "
          f"{bound / 2 ** 20:.1f} MiB (old: >= 757 MiB)",
          len(F) == 38400 and peak <= bound and bound < 757 * 2 ** 20 / 17 and np.isfinite(grid).any())


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
        bounded(glb)
    print("ALL OK" if not FAILS else "FAILED: " + ", ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
