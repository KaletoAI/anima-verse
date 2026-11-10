#!/usr/bin/env python3
"""Face cleanup before the face retexture (``app/core/face_cleanup.py``) on a synthetic head, expectations by hand.

Usage: ./.venv/bin/python scripts/smoke_face_cleanup.py

No world, no server, no Blender, no external assets.

Fixture: a box torso (y -0.5 .. 0.33) under a UV sphere head of radius R = 0.055 units centred at y = 0.42, so the
figure is 0.975 units tall and one millimetre of the 1.70 m reference figure is 0.975 / 1700 units. The front
hemisphere is planar-mapped into the left half of a 1024^2 PNG, the back into the right half; the texture is painted
in the SAME planar coordinates, so a vertex samples exactly the class its position falls in:
- skin (200, 150, 130) everywhere, except
- lash paint (20, 20, 20): an ellipse 22 x 7 mm around each eye centre (x = +-0.02 units = +-34.9 mm, y = 0.415)
  — the locator must read a half width of 18..26 mm (the 3..97 percentile of the painted x of a tapering ellipse
  trims ~3 mm a side) and an eye separation of 69.7 mm,
- lips (197, 50, 70): an ellipse 20 x 6 mm around (0, 0.375) — 1.0 interpupillary distance below the eye line.

Geometry defects, both inside the paint:
- a LASH RIDGE: the band |x - cx| < 15 mm, -9 mm <= y - cy < -6 mm of each eye is pushed 8 mm out along the sphere
  radius (the lower lash flap),
- an EYE OPENING: the disc of radius 5 mm around each eye centre is pushed 3 mm IN (what lies below the lid must
  never move).

Hand-derived expectations:
- the lid is the slope-limited lower envelope (CONE_SLOPE 1 mm/mm) of the relief of the ray-cast depth map over
  the region; the sphere is smooth (its relief against the 8 mm Gaussian base is ~0), the 3 mm wide ridge is a
  relief feature whose cells lie within 1.5 mm of its edge, so the envelope rises at most 1.5 mm into it and the
  ridge reads 8 - 1.5 .. 8 mm (+ the grid's 1 mm blur) = 6 .. 8.6 mm proud BEFORE; the opening (-3 mm) is a pit
  and never proud;
- AFTER (version 2 folds a flap onto its root instead of pressing it back in place): every ridge vertex stands
  more than EYE_FREE_MM = 2.5 mm proud, so the whole band is the flap set, and nothing else is (the rim of the
  opening reads 1.5-2.0 mm, under the threshold); its rows touch the unmoved sphere rows above (y - cy = -5.x mm)
  and below (-9.x mm), which read ~0 mm against the envelope and are the anchors — and, where the top row at
  x = cx has only the opening's rim as a neighbour (hypot 4.9 mm < 5), that rim at -3 mm. Each ridge vertex takes
  the position of an anchor INSET_MM = 0.6 mm under it along the fit normal (radial on the sphere within a few
  degrees): its radius ends between R - 0.9 mm and R - 0.3 mm on a sphere anchor, R - 3.9 .. R - 3.3 on a rim
  anchor, i.e. it moved 8 + 0.6 (+ 3 on the rim) mm straight back — 5 .. 12 mm along the radius is the tolerant
  gate; against the same lid the folded vertices read at most EYE_LIMIT_MM = 2.0 mm (an anchor is at most 2.5 mm
  proud, the fold ends 0.6 mm under it); the ridge's triangles end collapsed (no area) or flat under the surface,
  at most 8 faces turned over (regression guard); the opening's vertices keep their exact bytes; vertices outside
  both eye regions keep their exact positions; nothing but the ridge moves (moved == ridge vertices); indices,
  UVs and the triangle count are unchanged; the result still passes ``validate_source``;
- MOUTH: HSV saturation (max - min) / max — skin (200-130)/200 = 0.35, lips (197-50)/197 = 0.746 -> ratio 2.13
  before (> 1.3, applied);
  after at most LIP_RATIO_LIMIT = 1.3 on the same texels; the eye-paint texels and a far skin texel are untouched;
- a head WITHOUT paint is skipped (reason names the lash paint) and the bytes come back untouched;
- the overview row (``model_overview._face_cleanup_step``): done with "lashes" and "lips/skin saturation" in the
  detail, missing without a record, failed for a failed record; ``summary`` is one non-empty line.
"""
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

FAILS = []


def check(cond, label):
    print(("OK   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


R = 0.055
HEAD_Y = 0.42
EYE_Y = 0.415
EYE_X = 0.02
MOUTH_Y = 0.375
TOP, BOTTOM = HEAD_Y + R, -0.5
MM = (TOP - BOTTOM) / 1700.0

SKIN = (200, 150, 130)
LASH = (20, 20, 20)
LIPS = (197, 50, 70)


def planar_uv(x, y, front):
    u = (0.25 if front else 0.75) + 0.2 * x / R
    v = 0.5 - 0.2 * (y - HEAD_Y) / R
    return u, v


def paint_class(x, y):
    """The texture class at planar face coordinates (front hemisphere)."""
    for cx in (EYE_X, -EYE_X):
        if ((x - cx) / (22 * MM)) ** 2 + ((y - EYE_Y) / (7 * MM)) ** 2 < 1:
            return LASH
    if (x / (20 * MM)) ** 2 + ((y - MOUTH_Y) / (6 * MM)) ** 2 < 1:
        return LIPS
    return SKIN


def texture_png(painted=True):
    from PIL import Image
    size = 1024
    img = np.zeros((size, size, 3), np.uint8)
    img[:] = SKIN
    if painted:
        cols = (np.arange(size) + 0.5) / size
        rows = (np.arange(size) + 0.5) / size
        xs = (cols - 0.25) * R / 0.2
        ys = HEAD_Y - (rows - 0.5) * R / 0.2
        for j, y in enumerate(ys):
            for i, x in enumerate(xs):
                if 0.05 <= cols[i] <= 0.45:
                    img[j, i] = paint_class(x, y)
    out = io.BytesIO()
    Image.fromarray(img).save(out, "PNG")
    return out.getvalue()


def build_head(painted=True, defects=True):
    rings, segments = 160, 320
    P, U = [], []
    for i in range(rings + 1):
        theta = np.pi * i / rings
        for j in range(segments):
            phi = 2 * np.pi * j / segments
            x = R * np.sin(theta) * np.sin(phi)
            y = HEAD_Y + R * np.cos(theta)
            z = R * np.sin(theta) * np.cos(phi)
            P.append((x, y, z))
            U.append(planar_uv(x, y, z >= 0))
    P = np.array(P, np.float64)
    U = np.array(U, np.float64)
    F = []
    for i in range(rings):
        for j in range(segments):
            a = i * segments + j
            b = i * segments + (j + 1) % segments
            c = (i + 1) * segments + j
            d = (i + 1) * segments + (j + 1) % segments
            F.append((a, c, b))
            F.append((b, c, d))
    F = np.array(F, np.int64)
    ridge = np.zeros(len(P), bool)
    opening = np.zeros(len(P), bool)
    if defects:
        for cx in (EYE_X, -EYE_X):
            front = P[:, 2] > 0
            dy = P[:, 1] - EYE_Y
            ridge |= front & (np.abs(P[:, 0] - cx) < 15 * MM) & (dy >= -9 * MM) & (dy < -6 * MM)
            opening |= front & (np.hypot(P[:, 0] - cx, dy) < 5 * MM)
        radial = (P - np.array([0, HEAD_Y, 0])) / R
        P = P + radial * (8 * MM) * ridge[:, None] - radial * (3 * MM) * opening[:, None]
    # torso: a box under the head
    bx, by0, by1, bz = 0.12, BOTTOM, 0.33, 0.06
    box = np.array([(sx * bx, y, sz * bz) for y in (by0, by1) for sx in (-1, 1) for sz in (-1, 1)], np.float64)
    box_f = np.array([(0, 1, 2), (1, 3, 2), (4, 6, 5), (5, 6, 7), (0, 4, 1), (1, 4, 5),
                      (2, 3, 6), (3, 7, 6), (0, 2, 4), (2, 6, 4), (1, 5, 3), (3, 5, 7)], np.int64) + len(P)
    P = np.vstack([P, box])
    U = np.vstack([U, np.full((8, 2), (0.5, 0.95))])
    F = np.vstack([F, box_f])
    N = P - np.array([0, HEAD_Y, 0])
    N /= np.linalg.norm(N, axis=1)[:, None]
    ridge = np.concatenate([ridge, np.zeros(8, bool)])
    opening = np.concatenate([opening, np.zeros(8, bool)])
    return pack(P, N, U, F, texture_png(painted)), P, F, U, ridge, opening


def pack(P, N, U, F, png):
    from app.core.glb_mesh import pack_glb
    blobs, views, accessors = [], [], []
    offset = 0

    def view(data, target=None):
        nonlocal offset
        data = bytes(data)
        data += b"\0" * (-len(data) % 4)
        v = {"buffer": 0, "byteOffset": offset, "byteLength": len(data)}
        if target:
            v["target"] = target
        views.append(v)
        blobs.append(data)
        offset += len(data)
        return len(views) - 1

    def accessor(array, ctype, atype, target, bounds=False):
        arr = np.ascontiguousarray(array)
        acc = {"bufferView": view(arr.tobytes(), target), "componentType": ctype, "count": int(len(arr)), "type": atype}
        if bounds:
            acc["min"] = [float(v) for v in arr.min(0)]
            acc["max"] = [float(v) for v in arr.max(0)]
        accessors.append(acc)
        return len(accessors) - 1

    pos = accessor(P.astype("<f4"), 5126, "VEC3", 34962, bounds=True)
    nrm = accessor(N.astype("<f4"), 5126, "VEC3", 34962)
    uv = accessor(U.astype("<f4"), 5126, "VEC2", 34962)
    idx = accessor(F.reshape(-1).astype("<u4"), 5125, "SCALAR", 34963)
    img_view = view(png)
    gltf = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": offset}],
        "bufferViews": views,
        "accessors": accessors,
        "images": [{"bufferView": img_view, "mimeType": "image/png"}],
        "textures": [{"source": 0}],
        "materials": [{"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}, "metallicFactor": 0.0}}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": pos, "NORMAL": nrm, "TEXCOORD_0": uv},
                                    "indices": idx, "material": 0, "mode": 4}]}],
        "nodes": [{"mesh": 0, "name": "geometry_0"}],
        "scenes": [{"nodes": [0]}],
        "scene": 0,
    }
    return pack_glb(gltf, b"".join(blobs))


def main():
    from app.core import face_cleanup as fc
    from app.core.glb_mesh import static_arrays
    from app.core.mesh_source import validate_source
    from app.core.model_overview import _face_cleanup_step, DONE, FAILED, NOT_RECORDED

    glb, P0, F0, U0, ridge, opening = build_head()
    check(validate_source(glb)["ok"], "fixture passes validate_source")
    before = fc.measure_face(glb)
    eyes = before["eyes"]
    check(eyes.get("status") == "measured" and eyes.get("front_axis") == "+z", f"eyes located, front +z: {eyes.get('status')} {eyes.get('front_axis')}")
    rows = eyes.get("eyes") or []
    check(len(rows) == 2 and {r["side"] for r in rows} == {"left", "right"}, "two eyes, left and right")
    for r in rows:
        check(30 <= abs(r["centre_mm"][0]) <= 40 and 18 <= r["half_width_mm"] <= 26,
              f"{r['side']} eye centre x {r['centre_mm'][0]} mm, half width {r['half_width_mm']} mm (expected +-34.9, ~22)")
        check(6.0 <= r["lash_outer_max_mm"] <= 8.6 and r["depth_cells_hit"] >= 1000,
              f"{r['side']} ridge measures {r['lash_outer_max_mm']} mm proud before (expected 6 .. 8.6), {r['depth_cells_hit']} depth cells")
        check(r["flap_vertices"] >= int(ridge.sum() / 2) - 5, f"{r['side']}: flap set {r['flap_vertices']} vertices (ridge has {int(ridge.sum() / 2)} per eye)")
    mouth = before.get("mouth") or {}
    check(mouth.get("ratio_before") is not None and 2.0 <= mouth["ratio_before"] <= 2.25,
          f"lips/skin saturation before {mouth.get('ratio_before')} (expected 2.13)")

    out, record = fc.clean_face(glb)
    check(record["status"] == "applied" and record["eyes"]["status"] == "applied" and record["mouth"]["status"] == "applied",
          f"cleanup applied: {record['status']} / eyes {record['eyes']['status']} / mouth {record['mouth']['status']}")
    for e in record["eyes"]["eyes"]:
        b, a = e.get("before_mm") or {}, e.get("after_mm") or {}
        check(a.get("lash_weighted_max") is not None and a["lash_weighted_max"] <= fc.EYE_LIMIT_MM,
              f"{e['side']}: lash tier after {a.get('lash_weighted_max')} mm <= {fc.EYE_LIMIT_MM} (before {b.get('lash_outer_max')})")
        check(e["moved_vertices"] >= int(ridge.sum() / 2) - 5, f"{e['side']}: moved {e['moved_vertices']} vertices (ridge has {int(ridge.sum() / 2)} per eye)")
    P1, F1, U1, img1, *_ = static_arrays(out)
    P0, F0, U0, img0, *_ = static_arrays(glb)
    check(np.array_equal(F0, F1) and np.array_equal(U0, U1) and len(P1) == len(P0), "indices, UVs and vertex count unchanged")
    check(validate_source(out)["ok"], "cleaned mesh passes validate_source")
    radial = (P0 - np.array([0, HEAD_Y, 0]))
    radial /= np.linalg.norm(radial, axis=1)[:, None]
    moved = np.linalg.norm(P1 - P0, axis=1) / MM
    back = -((P1 - P0) * radial).sum(1) / MM
    check(np.all(back[ridge] >= 5.0) and np.all(back[ridge] <= 12.0),
          f"ridge vertices folded back 5 .. 12 mm (min {back[ridge].min():.2f}, max {back[ridge].max():.2f})")
    radius = np.linalg.norm(P1[ridge] - np.array([0, HEAD_Y, 0]), axis=1)
    under = (R - radius) / MM
    on_sphere = (under >= 0.3) & (under <= 0.9)
    on_rim = (under >= 3.3) & (under <= 3.9)
    check(np.all(on_sphere | on_rim) and on_sphere.sum() >= 0.8 * len(under),
          f"folded ridge vertices lie 0.3 .. 0.9 mm under the sphere ({int(on_sphere.sum())}) or 3.3 .. 3.9 under the opening's rim ({int(on_rim.sum())}) of {len(under)}")
    turned = max(int((e.get("flipped_faces") or {}).get("after") or 0) for e in record["eyes"]["eyes"])
    check(turned <= 8, f"turned faces left after the fold: {turned} (regression guard)")
    check(int((moved > 0).sum()) == int(ridge.sum()), f"exactly the ridge moved ({int((moved > 0).sum())} of {int(ridge.sum())} vertices)")
    check(np.array_equal(P1[opening], P0[opening]), "eye-opening vertices (below the lid) keep their exact bytes")
    outside = np.ones(len(P0), bool)
    for cx in (EYE_X, -EYE_X):
        outside &= ((P0[:, 0] - cx) / (34 * MM)) ** 2 + ((P0[:, 1] - EYE_Y) / (27 * MM)) ** 2 >= 1
    check(np.array_equal(P1[outside], P0[outside]), f"vertices outside both eye regions unchanged ({int(outside.sum())} vertices)")

    m = record["mouth"]
    check(m["ratio_after"] <= fc.LIP_RATIO_LIMIT, f"lips/skin saturation after {m['ratio_after']} <= {fc.LIP_RATIO_LIMIT} (before {m['ratio_before']})")
    from PIL import Image
    t0 = np.asarray(Image.open(io.BytesIO(img0)).convert("RGB"))
    t1 = np.asarray(Image.open(io.BytesIO(img1)).convert("RGB"))
    changed = np.any(t0 != t1, axis=2)
    eye_u, eye_v = planar_uv(EYE_X, EYE_Y, True)
    check(not changed[int(eye_v * 1024), int(eye_u * 1024)] and not changed[int(0.95 * 1024), int(0.5 * 1024)]
          and not changed[int(eye_v * 1024), int(0.75 * 1024)],
          "eye paint, torso texel and back-of-head texel untouched by the mouth step")
    rows_changed, cols_changed = np.nonzero(changed)
    mouth_u, mouth_v = planar_uv(0, MOUTH_Y, True)
    check(len(rows_changed) > 0 and np.all(np.abs(rows_changed - mouth_v * 1024) < 60) and np.all(np.abs(cols_changed - mouth_u * 1024) < 120),
          f"texture changed only around the mouth ({len(rows_changed)} texels)")
    lips_texel = t1[int(mouth_v * 1024), int(mouth_u * 1024)].astype(float)
    sat = (lips_texel.max() - lips_texel.min()) / lips_texel.max()
    check(sat <= 0.35 * 1.3 + 0.02, f"lip centre texel saturation {sat:.2f} (skin 0.35, limit 1.3 x)")

    plain, *_ = build_head(painted=False)
    same, rec = fc.clean_face(plain)
    check(same is plain and rec["status"] == "skipped" and "lash paint" in rec["eyes"].get("reason", ""),
          f"unpainted head: skipped, bytes untouched ({rec['eyes'].get('reason')})")

    row = _face_cleanup_step({"face_cleanup": record})
    check(row["status"] == DONE and "lashes" in row["detail"] and "lips/skin saturation" in row["detail"], f"overview row: {row['status']} · {row['detail']}")
    check(_face_cleanup_step({})["status"] == NOT_RECORDED, "overview row without a record: missing")
    check(_face_cleanup_step({"face_cleanup": {"status": "failed", "error": "boom"}})["status"] == FAILED, "overview row of a failed record: failed")
    check(bool(fc.summary(record).strip()), f"summary: {fc.summary(record)}")

    print()
    print("FAILED" if FAILS else "ALL OK", f"({len(FAILS)} failures)")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
