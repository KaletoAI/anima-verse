#!/usr/bin/env python3
"""The ghost registration of the garment chain: a piece-only image that the
edit model redrew a little off / a little larger is moved onto the worn
view's garment region before the position gates, which then measure the
residual (app/core/garment_gates.py ``register`` / ``warp`` / ``_touching``,
app/core/garment_images.py ``_register`` / ``_with_registration``, the kind
hooks ``position_reference`` of garment_clothing / garment_hair).

Usage:
    ./.venv/bin/python scripts/smoke_garment_ghost_registration.py

No world, no hub, no server: a throwaway storage root, synthetic images, the
real gates and the real chain glue (``_register`` rewrites an attempt file in
a temp dir).

Geometry, W 600 x H 1000 on grey 128:
  BASE   skin (200, 160, 140) cols [120, 480) rows [100, 900): base mask rows
         100 .. 899 -> y0 100, Hb 899 - 100 = 799. Margin at H 1000:
         round(8 x 1000 / 1536) = 5 iterations.
  T      the piece: torso cols [220, 380) rows [200, 600) + sleeves cols
         [140, 460) rows [200, 260). Area 160·400 + 320·60 − 160·60 = 73600;
         centroid col 299.5 (symmetric), row (64000·399.5 + 9600·229.5) /
         73600 = 377.326.
  WORN   BASE with T in green (40, 90, 50): |ΔRGB| 106.7 > 20 -> the garment
         region G = T (opening/closing only nibble the 90° corners, the
         extents stay): bbox [140, 200, 459, 599].
  GHOST(s, dy, dx) = grey + T in green mapped forward: a pixel q is green when
         its preimage c + (q − c − (dy, dx)) / s lies in T (pixel squares,
         c = the T centroid (377.326, 299.5)) — T scaled by s about its
         centroid and moved by (dy, dx).

[1] warp (pure numbers): a mask moved by shift_px (−9, +12), scale 1 equals
    the mask rolled 9 rows up and 12 columns right; a 2:1 factor doubles the
    shift (24 columns on a twice-as-wide array); the uncovered RGB border is
    the border median (grey 128).
[2] register(G, GHOST(1.04, −9, +12) mask, body_h 799): the inverse map —
    scale 1 / 1.04 = 0.96154 (± 0.004), shift_px = G's centroid − the ghost's
    centroid ≈ c − (c + (−9, 12)) = (+9, −12) (± 1 px; rasterising moves each
    centroid by < 0.5 px); shift (dx, dy) / Hb = (−0.01502, 0.01126),
    |shift| 15 / 799 = 0.01877 (± 0.0015); within the caps (0.04, [0.93,
    1.07]); the mean outline distance falls below 1 px.
[3] The chain glue on GHOST(1.04, −9, +12) (``_register`` + the clothing
    gate, as run_edit_step calls them):
    before (as rendered): ghost bbox — columns q with the preimage col in
    [139.5, 459.5): q − 311.5 in [1.04·(−160), 1.04·160) = [−166.4, 166.4)
    -> 146 .. 477; rows: q − 368.326 >= 1.04·(199.5 − 377.326) = −184.939
    -> first row 184, q − 368.326 < 1.04·(599.5 − 377.326) = 231.061 -> last
    row 599. top_dy (184 − 200) / 799 = −0.02003, centre_dx ((146 + 477) −
    (140 + 459)) / 2 / 799 = 0.01502, w_ratio (477 − 146) / (459 − 140) =
    331 / 319 = 1.038 -> refused as rendered (top, centre).
    after: the attempt file rewritten moved; residual |top_dy|, |centre_dx|
    <= 2 / 799 = 0.0025, |w_ratio − 1| <= 0.01 -> ok; the record carries
    registration.applied True, before.ok False, reg_shift = shift_abs,
    reg_scale = scale, residual = the record's own top_dy / centre_dx /
    w_ratio; the file on disk differs from the rendered one and its mask
    bbox matches G within 2 px.
[4] Within the cap: GHOST(1, 0, +24) (24 / 799 = 0.03004 Hb) -> before
    centre_dx 0.03004 refused; corrected (|shift| ≈ 0.03004 < 0.04) -> ok,
    residual |centre_dx| <= 0.0025.
[5] Beyond the cap: GHOST(1, 0, +64) (64 / 799 = 0.0801 Hb, the hand-made
    "0.08 Hb" case) -> refused with "garment centre moved"; whatever the
    estimate, a correction is applied only within the caps.
    GHOST(1.10, 0, 0) (10 % larger): scale 1/1.10 = 0.909 < 0.93 -> not
    applied ("beyond the correction caps"), refused for its width
    (w_ratio ≈ 1.10 > 1.05).
[6] Negligible: GHOST(1, 0, 0) = T itself -> registration negligible, the
    file is NOT rewritten (bytes equal), ok, residual 0.
[7] _touching: G + a separate patch cols [100, 120) rows [300, 340) (a
    re-shaded hand, 20 px from the sleeve end at col 140, beyond the 5 px
    margin) against GHOST(1, 0, 0): the patch is dropped -> bbox_garment
    [140, 200, 459, 599], centre_dx 0.0 (with the patch the bbox would start
    at col 100: centre_dx ((140 + 459) − (100 + 459)) / 2 / 799 = 0.02503);
    a patch the ghost overlaps stays (bbox starts at 100 when the ghost
    covers it).
[8] Hooks + limits: position_reference(ghost) = garment_region (clothing) /
    hair_ref (hair), None for worn / haired; limits() of both kinds list
    reg_shift (le 0.04) and reg_scale (range [0.93, 1.07]) under ghost.
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_TMP = tempfile.mkdtemp(prefix="smoke_ghost_reg_")
os.environ["STORAGE_DIR"] = _TMP
os.environ["INSTANCE_DIR"] = _TMP
from app.core import paths  # noqa: E402

paths.init(_TMP)

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from app.core import garment_clothing, garment_gates as gg, garment_hair, garment_images as gi  # noqa: E402

FAILS = []
W, H = 600, 1000
GREY = (128, 128, 128)
SKIN = (200, 160, 140)
GREEN = (40, 90, 50)
HB = 799
C = (377.326087, 299.5)


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f" — expected {want!r}"))
    if not ok:
        FAILS.append(label)


def near(label, got, want, tol):
    ok = got is not None and abs(got - want) <= tol
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r} (want {want} ± {tol})")
    if not ok:
        FAILS.append(label)


def in_t(r, c):
    torso = (c >= 219.5) & (c < 379.5) & (r >= 199.5) & (r < 599.5)
    sleeves = (c >= 139.5) & (c < 459.5) & (r >= 199.5) & (r < 259.5)
    return torso | sleeves


def t_mask(s=1.0, dy=0.0, dx=0.0):
    rr, cc = np.mgrid[0:H, 0:W].astype(np.float64)
    return in_t(C[0] + (rr - C[0] - dy) / s, C[1] + (cc - C[1] - dx) / s)


def canvas():
    return np.full((H, W, 3), GREY, dtype=np.uint8)


def mask_of(rgb):
    return np.abs(rgb.astype(np.int16) - 128).max(2) > 2


BASE = canvas()
BASE[100:900, 120:480] = SKIN
WORN = BASE.copy()
WORN[t_mask()] = GREEN
ARGS = {"base_rgb": BASE, "base_mask": mask_of(BASE), "source_rgb": WORN, "source_mask": mask_of(WORN),
        "item_id": None}
REGION = gg.garment_region(BASE, mask_of(BASE), WORN, mask_of(WORN))
TMP = Path(_TMP)


def ghost(s=1.0, dy=0.0, dx=0.0):
    img = canvas()
    img[t_mask(s, dy, dx)] = GREEN
    return img


def chain(name, rgb):
    """``_register`` + the clothing gate on an attempt file, as run_edit_step."""
    path = TMP / f"{name}.png"
    Image.fromarray(rgb).save(path)
    ref = garment_clothing.position_reference("ghost", base_rgb=BASE, base_mask=mask_of(BASE),
                                              source_rgb=WORN, source_mask=mask_of(WORN))
    er, em, reg = gi._register(garment_clothing, "ghost", "front", path, (W, H), ref, gate_args=ARGS,
                               edit_rgb=rgb, edit_mask=mask_of(rgb))
    record = garment_clothing.gate("ghost", "front", edit_rgb=er, edit_mask=em, **ARGS)
    if reg is not None:
        record = gi._with_registration(record, reg)
    return path, record, em


def main() -> int:
    print("[0] fixture")
    check("base zones", gg._zones(mask_of(BASE)), (100, HB))
    check("region bbox", gg._bbox(REGION), [140, 200, 459, 599])

    print("[1] warp")
    m = t_mask()
    moved = gg.warp(m, {"centre": [0, 0], "shift_px": [-9, 12], "scale": 1.0})
    rolled = np.zeros_like(m)
    rolled[:H - 9, 12:] = m[9:, :W - 12]
    check("pure shift = roll", bool(np.array_equal(moved, rolled)), True)
    wide = np.repeat(m, 2, axis=1)
    moved2 = gg.warp(wide, {"centre": [0, 0], "shift_px": [0, 12], "scale": 1.0}, factor=(1.0, 2.0))
    check("factor 2 doubles the shift", gg._bbox(moved2)[0] - gg._bbox(wide)[0], 24)
    rgb = gg.warp(ghost(), {"centre": [0, 0], "shift_px": [0, 30], "scale": 1.0})
    check("border fill grey", tuple(int(v) for v in rgb[500, 5]), GREY)

    print("[2] register")
    reg = gg.register(REGION, t_mask(1.04, -9, 12), body_h=HB)
    near("scale", reg["scale"], 1 / 1.04, 0.004)
    near("shift_px dy", reg["shift_px"][0], 9.0, 1.0)
    near("shift_px dx", reg["shift_px"][1], -12.0, 1.0)
    near("shift dx / Hb", reg["shift"][0], -12 / HB, 0.0015)
    near("shift dy / Hb", reg["shift"][1], 9 / HB, 0.0015)
    near("|shift| / Hb", reg["shift_abs"], 15 / HB, 0.0015)
    check("within caps, not negligible", (reg["within_caps"], reg["negligible"]), (True, False))
    check("outline distance falls below 1 px", (reg["fit_px"][0] > 3, reg["fit_px"][1] < 1.0), (True, True))
    check("empty -> None", gg.register(np.zeros_like(REGION), t_mask(), body_h=HB), None)

    print("[3] chain glue: 4 % larger, 9 px up, 12 px right")
    raw = ghost(1.04, -9, 12)
    rendered = raw.copy()
    path, rec, em = chain("big", raw)
    r = rec.get("registration") or {}
    before = r.get("before") or {}
    check("before bbox numbers", (before.get("top_dy"), before.get("centre_dx"), before.get("w_ratio"),
                                  before.get("ok")), (-0.02003, 0.01502, 1.038, False))
    check("accepted after registration", (rec["ok"], rec["reasons"]), (True, []))
    check("applied", r.get("applied"), True)
    near("residual top_dy", rec["top_dy"], 0.0, 2 / HB)
    near("residual centre_dx", rec["centre_dx"], 0.0, 2 / HB)
    near("residual w_ratio", rec["w_ratio"], 1.0, 0.01)
    check("residual = record numbers", r.get("residual"),
          {"top_dy": rec["top_dy"], "centre_dx": rec["centre_dx"], "w_ratio": rec["w_ratio"]})
    check("chip keys", (rec.get("reg_shift"), rec.get("reg_scale")), (r.get("shift_abs"), r.get("scale")))
    on_disk = np.asarray(Image.open(path).convert("RGB"))
    check("attempt file differs from the render", bool(np.array_equal(on_disk, rendered)), False)
    box = gg._bbox(mask_of(on_disk))
    check("file mask bbox ≈ G (± 2 px)", all(abs(a - b) <= 2 for a, b in zip(box, [140, 200, 459, 599])), True)
    check("returned mask = file mask (± 1 %)",
          float((em ^ mask_of(on_disk)).sum() / max(int(em.sum()), 1)) < 0.01, True)

    print("[4] within the cap: 24 px right")
    _, rec, _ = chain("right24", ghost(1.0, 0, 24))
    r = rec.get("registration") or {}
    check("before centre_dx", (r.get("before") or {}).get("centre_dx"), 0.03004)
    check("accepted", (rec["ok"], r.get("applied")), (True, True))
    near("|shift|", r.get("shift_abs"), 24 / HB, 0.0015)
    near("residual centre_dx", rec["centre_dx"], 0.0, 2 / HB)

    print("[5] beyond the cap")
    _, rec, _ = chain("right64", ghost(1.0, 0, 64))
    r = rec.get("registration") or {}
    check("0.08 Hb refused, centre moved", (rec["ok"], any("garment centre moved" in x for x in rec["reasons"])),
          (False, True))
    check("applied only within the caps", (not r.get("applied")) or bool(r.get("within_caps")), True)
    _, rec, _ = chain("big10", ghost(1.10, 0, 0))
    r = rec.get("registration") or {}
    near("10 % larger: scale", r.get("scale"), 1 / 1.10, 0.006)
    check("not applied", (r.get("applied"), r.get("note")), (False, "beyond the correction caps — gated as rendered"))
    check("refused for its width", (rec["ok"], any("garment width changed" in x for x in rec["reasons"])),
          (False, True))

    print("[6] negligible")
    exact = ghost()
    path, rec, _ = chain("exact", exact)
    data = path.read_bytes()
    r = rec.get("registration") or {}
    check("negligible, not applied", (r.get("negligible"), r.get("applied"), r.get("note")),
          (True, False, "negligible"))
    path2 = TMP / "exact_ref.png"
    Image.fromarray(exact).save(path2)
    check("file untouched", data == path2.read_bytes(), True)
    check("ok, residual 0", (rec["ok"], rec["top_dy"], rec["centre_dx"], rec["w_ratio"]), (True, 0.0, 0.0, 1.0))

    print("[7] _touching")
    hand = REGION.copy()
    hand[300:340, 100:120] = True
    g = gg.ghost_clothing_gate(BASE, mask_of(BASE), hand, exact, mask_of(exact), view="front")
    check("far patch dropped", (g["bbox_garment"], g["centre_dx"], g["ok"]), ([140, 200, 459, 599], 0.0, True))
    covering = exact.copy()
    covering[300:340, 100:120] = GREEN
    g = gg.ghost_clothing_gate(BASE, mask_of(BASE), hand, covering, mask_of(covering), view="front")
    check("covered patch kept", g["bbox_garment"][0], 100)

    print("[8] hooks + limits")
    none = {"base_rgb": BASE, "base_mask": mask_of(BASE), "source_rgb": WORN, "source_mask": mask_of(WORN)}
    check("clothing ghost = garment_region",
          bool(np.array_equal(garment_clothing.position_reference("ghost", **none), REGION)), True)
    check("clothing worn = None", garment_clothing.position_reference("worn", **none), None)
    check("hair ghost = hair_ref", bool(np.array_equal(
        garment_hair.position_reference("ghost", **none), gg.hair_ref(BASE, mask_of(BASE), WORN, mask_of(WORN)))),
        True)
    check("hair haired = None", garment_hair.position_reference("haired", **none), None)
    want = {"reg_shift": {"op": "le", "value": 0.04}, "reg_scale": {"op": "range", "value": [0.93, 1.07]}}
    for kind in ("clothing", "hair"):
        ghost_limits = gg.limits(kind)["ghost"]
        check(f"limits {kind}", {k: ghost_limits[k] for k in want}, want)

    if FAILS:
        print(f"FAILED: {', '.join(FAILS)}")
        return 1
    print("all ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
