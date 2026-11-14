#!/usr/bin/env python3
"""The hair card writer (``app/core/hair_cards.py``) and the world setting ``base_body.hair_alpha_cutoff`` —
strand-hair plan 2026-11-13, Task 1 (spec § 6.1). Expectations by hand.

Usage: ./.venv/bin/python scripts/smoke_hair_alpha_cards.py

No server, no world DB, no hub: a throwaway storage dir holds the temp world's ``config.json`` for [4].

Texel convention (glTF, what three's GLTFLoader reads with ``flipY = false``): the texel of UV (u, v) is column
``floor(u * 1024)``, row ``floor(v * 1024)`` — v = 0 is the TOP row.

[1] The atlas: PNG signature, PIL mode RGBA, size (1024, 1024).
    SOLID_UV is the centre of the 64 px patch in the bottom-right corner: ((1024 - 32) / 1024, (1024 - 32) / 1024)
    = (0.96875, 0.96875) -> texel (992, 992), alpha 255.
    Per variant column (128 px wide: 1024 / 8, columns 128 k .. 128 k + 127): the tip band v in [0, 0.04] = rows
    0 .. 40 (floor(0.04 * 1024) = 40, exclusive 41) has a smaller mean alpha than the band v in [0.48, 0.52] =
    rows 491 .. 532 (floor(0.48 * 1024) = 491, floor(0.52 * 1024) = 532): every line ends at 80-100 % of the length
    measured from the root (v = 1), so at v <= 0.04 (>= 96 % from the root) a line is either ended or inside its
    last 18 % fade, while at v = 0.5 every line runs at full alpha.
    Determinism: sha256 of ``strip_atlas()`` equals the sha256 after ``cache_clear()`` and a rebuild (seed 7).
[2] variant_uvs (FIT hair 14: STRIP_VARIANTS 7 — the 8th column holds the cap's opaque patch at its root end):
    card 9, uv (0.5, 1.0) -> ((9 % 7 + 0.5) / 8, 1.0) = (2.5 / 8, 1.0) = (0.3125, 1.0); card 7, uv (0.5, 1.0) ->
    (0.5 / 8, 1.0) = (0.0625, 1.0) (not the 8th column's 7.5 / 8); card 0, uv (1.0, 0.0) -> ((0 + 1.0) / 8, 0.0)
    = (0.125, 0.0); card -1, uv (0.3, 0.7) -> SOLID_UV.
    texture_garment of a 3-vertex garment with these cards: image == strip_atlas(), mime "image/png", the UVs
    above, positions / indices / colours unchanged, the input garment untouched (a copy).
[3] hairdeck_cards: two disjoint square tubes of 3 rows x 4 vertices (12 vertices each: tube A 0..11, tube B
    12..23; per row r and side k the quad (4r + k, 4r + (k+1) % 4, 4(r+1) + (k+1) % 4, 4(r+1) + k) = 2 triangles,
    16 side triangles per tube; plus, as HairDeck's tubes have, a cross-section quad per row (4r, 4r+2, 4r+1),
    (4r, 4r+3, 4r+2) = 6 triangles per tube) + a 4-vertex cap (24..27, 2 triangles) with n_hair 24, n_total 28 ->
    components of the hair faces in order of their first vertex: tube A (first vertex 0) = 0, tube B (first
    vertex 12) = 1, the cap = -1: ids [0]*12 + [1]*12 + [-1]*4. The cap's faces are ignored (indices >= n_hair).
    UVs as HairDeck's (u around the tube 0 / 0.5 / 1 / 0.5, v = 1 / 0.5 / 0 per row; cap (0, 0)):
    ``card_faces`` drops the 2 x 6 = 12 cross-section triangles (one card, one v) and keeps the 2 x 16 side
    triangles and the 2 cap triangles (the cap's four vertices share one v too, but card -1 is never dropped):
    46 -> 34 faces, in order; ``texture_garment`` carries those 34. The same faces with every UV (0, 0) (no
    strand UVs, as some fixtures and non-HairDeck cards have): no card has a v run, nothing is dropped (46).
[4] The setting: schema field type "float", default 0.15, min 0.05, max 0.5, step 0.01 (= CUTOFF_LIMITS);
    ``field_default("base_body", "hair_alpha_cutoff") == 0.15``; ``alpha_cutoff()`` in a temp world without the
    key = 0.15; with {"base_body": {"hair_alpha_cutoff": 0.12}} = 0.12; with 0.9 = 0.5 (clamped to the max);
    with 0.12: ``alpha_overrides() == {"alphaMode": "MASK", "alphaCutoff": 0.12, "doubleSided": True}`` and
    ``alpha_overrides(0.18)["alphaCutoff"] == 0.18``.
[5] width_uvs (FIT hair 14; user test 2026-11-14 T-U1, thin stray threads at the tips): card 0 a diamond tube like
    HairDeck's, rows v 1 / 0.5 / 0 at y 0 / -0.05 / -0.10 with half widths 0.010 / 0.005 / 0.001, per row the four
    vertices (-w, y, 0) u 0, (0, y, w) u 0.5, (w, y, 0) u 1, (0, y, -w) u 0.5 -> the row's mean is (0, y, 0) and its
    width share w / 0.010 = 1 / 0.5 / 0.1: u 0 -> 0.5 - 0.5 * share = 0 / 0.25 / 0.45, u 1 -> 1 / 0.75 / 0.55, u 0.5
    stays 0.5; v unchanged. Card 1, three rows each a single point (no width): its UVs kept. A cap vertex (card -1):
    kept. ``texture_garment`` of that garment = ``variant_uvs(width_uvs(...))``: card 0's row v 0.5 u 0 at
    (0 + 0.25) / 8 = 0.03125.
"""
import hashlib
import io
import json
import shutil
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


def tube(offset, cross=False):
    F = []
    for r in range(2):
        for k in range(4):
            a, b = 4 * r + k, 4 * r + (k + 1) % 4
            c, d = 4 * (r + 1) + (k + 1) % 4, 4 * (r + 1) + k
            F += [[a, b, c], [a, c, d]]
    if cross:
        for r in range(3):
            F += [[4 * r, 4 * r + 2, 4 * r + 1], [4 * r, 4 * r + 3, 4 * r + 2]]
    return np.asarray(F) + offset


def main():
    tmp = Path(tempfile.mkdtemp(prefix="smoke_hair_alpha_cards_"))
    try:
        return run_checks(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run_checks(tmp):
    from PIL import Image
    from app.core import paths
    paths.init(tmp / "world")
    paths.init_instance(tmp / "instance")
    from app.core import config, hair_cards
    from app.core.config_schema import SECTIONS, field_default

    # [1] the atlas
    png = hair_cards.strip_atlas()
    check(png[:8] == b"\x89PNG\r\n\x1a\n", "[1] atlas is a PNG")
    img = Image.open(io.BytesIO(png))
    check(img.mode == "RGBA" and img.size == (1024, 1024), f"[1] RGBA 1024x1024 (got {img.mode} {img.size})")
    check(hair_cards.SOLID_UV == (0.96875, 0.96875), f"[1] SOLID_UV (0.96875, 0.96875) (got {hair_cards.SOLID_UV})")
    a = np.asarray(img)[..., 3].astype(np.float64)
    u, v = hair_cards.SOLID_UV
    check(a[int(v * 1024), int(u * 1024)] == 255, "[1] alpha 255 at the texel of SOLID_UV (992, 992)")
    for k in range(8):
        cols = slice(128 * k, 128 * k + 128)
        tip, mid = a[0:41, cols].mean() / 255, a[491:532, cols].mean() / 255
        check(tip < mid, f"[1] variant {k}: tip band alpha {tip:.3f} < mid band {mid:.3f}")
    sha1 = hashlib.sha256(png).hexdigest()
    hair_cards.strip_atlas.cache_clear()
    sha2 = hashlib.sha256(hair_cards.strip_atlas()).hexdigest()
    check(sha1 == sha2, f"[1] deterministic: rebuilt atlas has the same sha256 ({sha1[:12]})")

    # [2] variant UVs and the textured copy
    uv = hair_cards.variant_uvs(np.array([[0.5, 1.0], [1.0, 0.0], [0.3, 0.7]]), np.array([9, 0, -1]))
    check(np.allclose(uv[0], (0.3125, 1.0)), f"[2] card 9 (0.5, 1) -> (0.3125, 1) (got {uv[0].tolist()})")
    check(hair_cards.STRIP_VARIANTS == 7
          and np.allclose(hair_cards.variant_uvs(np.array([[0.5, 1.0]]), np.array([7]))[0], (0.0625, 1.0)),
          "[2] card 7 -> column 0 (0.0625), never the cap's column")
    check(np.allclose(uv[1], (0.125, 0.0)), f"[2] card 0 (1, 0) -> (0.125, 0) (got {uv[1].tolist()})")
    check(np.allclose(uv[2], hair_cards.SOLID_UV), f"[2] card -1 -> SOLID_UV (got {uv[2].tolist()})")
    from app.core.glb_mesh import GarmentMesh
    g = GarmentMesh(positions=np.eye(3), normals=None, uvs=np.array([[0.5, 1.0], [1.0, 0.0], [0.3, 0.7]]),
                    indices=np.array([[0, 1, 2]]), joints=np.zeros((3, 4), np.int64), weights=np.eye(3, 4),
                    joint_names=["mixamorig:Head"], colors=np.full((3, 4), 0.5))
    t = hair_cards.texture_garment(g, np.array([9, 0, -1]))
    check(t.image == hair_cards.strip_atlas() and t.mime == "image/png", "[2] texture_garment: atlas PNG")
    check(np.allclose(t.uvs, uv), "[2] texture_garment: the variant UVs")
    check(np.array_equal(t.positions, g.positions) and np.array_equal(t.indices, g.indices)
          and np.array_equal(t.colors, g.colors), "[2] texture_garment: geometry and colours unchanged")
    check(g.image == b"" and np.allclose(g.uvs[0], (0.5, 1.0)), "[2] texture_garment: the input is untouched")

    # [3] cards of a HairDeck garment
    F = np.vstack([tube(0), tube(12), np.array([[24, 25, 26], [24, 26, 27]])])
    ids = hair_cards.hairdeck_cards(F, 24, 28)
    check(ids.tolist() == [0] * 12 + [1] * 12 + [-1] * 4, f"[3] card ids (got {ids.tolist()})")
    cap = np.array([[24, 25, 26], [24, 26, 27]])
    Fx = np.vstack([tube(0, cross=True), tube(12, cross=True), cap])
    ids_x = hair_cards.hairdeck_cards(Fx, 24, 28)
    check(ids_x.tolist() == ids.tolist(), "[3] the cross sections change no card id")
    U = np.array([[u, 1 - r / 2] for _ in range(2) for r in range(3) for u in (0, 0.5, 1, 0.5)] + [[0, 0]] * 4)
    kept = hair_cards.card_faces(Fx, U, ids_x)
    check(len(Fx) == 46 and kept.tolist() == np.vstack([tube(0), tube(12), cap]).tolist(),
          f"[3] card_faces: 46 -> 34 faces, the sides and the cap in order (got {len(kept)})")
    from app.core.glb_mesh import GarmentMesh as GM
    gx = GM(positions=np.zeros((28, 3)), normals=None, uvs=U, indices=Fx, joints=np.zeros((28, 4), np.int64),
            weights=np.tile([1.0, 0, 0, 0], (28, 1)), joint_names=["mixamorig:Head"])
    tx = hair_cards.texture_garment(gx, ids_x)
    check(len(tx.indices) == 34 and len(gx.indices) == 46, "[3] texture_garment carries the 34 faces")
    flat = hair_cards.card_faces(Fx, np.zeros((28, 2)), ids_x)
    check(len(flat) == 46, f"[3] card_faces without strand UVs drops nothing (got {len(flat)})")

    # [4] the setting
    field = SECTIONS["base_body"]["fields"]["hair_alpha_cutoff"]
    check((field["type"], field["default"], field["min"], field["max"], field["step"])
          == ("float", 0.15, 0.05, 0.5, 0.01), f"[4] schema field (got {field})")
    check((field["min"], field["max"]) == hair_cards.CUTOFF_LIMITS, "[4] the clamp is the schema's min/max")
    check(field_default("base_body", "hair_alpha_cutoff") == 0.15, "[4] field_default 0.15")
    cfg = paths.get_config_path()
    cfg.parent.mkdir(parents=True, exist_ok=True)

    def world(doc):
        cfg.write_text(json.dumps(doc))
        config.load(cfg, instance_path=tmp / "instance" / "config.json")
        return hair_cards.alpha_cutoff()

    check(world({}) == 0.15, "[4] no key -> 0.15")
    check(world({"base_body": {"hair_alpha_cutoff": 0.9}}) == 0.5, "[4] 0.9 -> clamped 0.5")
    got = world({"base_body": {"hair_alpha_cutoff": 0.12}})
    check(got == 0.12, f"[4] 0.12 -> 0.12 (got {got})")
    check(hair_cards.alpha_overrides() == {"alphaMode": "MASK", "alphaCutoff": 0.12, "doubleSided": True},
          f"[4] alpha_overrides() (got {hair_cards.alpha_overrides()})")
    check(hair_cards.alpha_overrides(0.18)["alphaCutoff"] == 0.18, "[4] alpha_overrides(0.18)")

    # [5] the strip at the card's own width
    P5, U5 = [], []
    for v, y, w in ((1.0, 0.0, 0.010), (0.5, -0.05, 0.005), (0.0, -0.10, 0.001)):
        P5 += [(-w, y, 0), (0, y, w), (w, y, 0), (0, y, -w)]
        U5 += [(0, v), (0.5, v), (1, v), (0.5, v)]
    for v, y in ((1.0, 0.0), (0.5, -0.05), (0.0, -0.10)):
        P5.append((0.3, y, 0))
        U5.append((0.2, v))
    P5.append((0, 0.2, 0))
    U5.append((0.7, 0.4))
    P5, U5 = np.array(P5, float), np.array(U5, float)
    card5 = np.array([0] * 12 + [1] * 3 + [-1])
    w5 = hair_cards.width_uvs(U5, P5, card5)
    want = np.array([0, 0.5, 1, 0.5, 0.25, 0.5, 0.75, 0.5, 0.45, 0.5, 0.55, 0.5])
    check(np.allclose(w5[:12, 0], want) and np.array_equal(w5[:, 1], U5[:, 1]),
          f"[5] card 0: u per row 0/0.5/1, 0.25/0.5/0.75, 0.45/0.5/0.55, v kept (got {w5[:12, 0].round(4).tolist()})")
    check(np.array_equal(w5[12:], U5[12:]), "[5] a card without width and the cap keep their UVs")
    t5 = hair_cards.texture_garment(GarmentMesh(positions=P5, normals=None, uvs=U5, indices=np.array([[0, 1, 2]]),
                                                joints=np.zeros((16, 4), np.int64), weights=np.eye(16, 4),
                                                joint_names=["mixamorig:Head"], colors=np.full((16, 4), 0.5)), card5)
    check(np.isclose(t5.uvs[4, 0], 0.03125), f"[5] texture_garment: row v 0.5, u 0 -> 0.03125 (got {t5.uvs[4, 0]})")

    print("PASS" if not FAILS else f"FAIL ({len(FAILS)})")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
