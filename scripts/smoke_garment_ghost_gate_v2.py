#!/usr/bin/env python3
"""Ghost gate version 2 (2026-11-12): the image stage of the clothing chain
refuses only what would put something WRONG into the mesh — body or skin
left, more than the garment, an empty or cut-off piece. Kai's "Black
Lederjacket" and "Jeans" backs were refused although every image was a
correct back (app/core/garment_gates.py ``ghost_clothing_gate`` /
``skin_colour`` / ``body_openings`` / ``_touching`` / ``register_waistband``,
app/core/garment_clothing.py ``GATE_VERSIONS``, app/core/garment_images.py
``_stale_gate``).

Usage:
    ./.venv/bin/python scripts/smoke_garment_ghost_gate_v2.py

No world, no hub, no server: a throwaway storage root, synthetic images, the
real gates. Needs git for [6] (the pinned old code).

Geometry, W 600 x H 1000 on grey 128 (the frame of
smoke_garment_ghost_registration.py). Margin at H 1000: round(8 x 1000 /
1536) = 5 iterations; opening round(2 x 1000 / 1536) = 1, closing 3.
  BASE  skin (200, 160, 140) cols [120, 480) rows [100, 900) with the back of
        a haired head: rows [100, 180) in hair (35, 30, 25). y0 100, Hb 799.
        Old skin sample (head rows int(100 + 0.04 x 799) = 131 ..
        int(100 + 0.10 x 799) = 179) = the hair (35, 30, 25); the new one
        (thigh rows int(100 + 0.60 x 799) = 579 .. int(100 + 0.66 x 799) =
        627, all skin) = (200, 160, 140).
  JACKET black (20, 20, 20) cols [140, 460) rows [200, 600). WORN_J = BASE +
        JACKET -> region G_J = the jacket (|ΔRGB| to skin 160 > 20), the
        opening (1 iteration) cuts 1 px off each corner: area 320 x 400 - 4 =
        127996.

[1] Skin sampled on the thighs. GHOST_HEM = JACKET + its dark inside
    (30, 28, 24) below the hem, cols [160, 440) rows [600, 620) (the inside
    shown at the hem). Beyond the 5 px margin: rows 605..619 x cols
    160..439 = 15 x 280 = 4200 px; outside 4200 / 127996 = 0.03281 <= 0.05.
    Inside vs the hair sample: (5 + 2 + 1) / 3 = 2.67 <= 30 -> old: "skin"
    0.03281 > 0.005 refused; vs the thigh sample: far -> skin_left 0.0, ok.
[2] Position recorded. GHOST_UP = JACKET 10 rows higher (rows [190, 590)):
    top_dy -10 / 799 = -0.01252 -> "garment top moved" in ``warnings``, not
    in ``reasons``; rows 190..194 beyond the margin: 5 x 320 = 1600 px, plus
    row 195 at cols 140 / 459 (G_J's cut corner pixel leaves them 6 steps
    from the nearest region pixel) = 1602 -> outside 1602 / 127996 =
    0.01252 -> ok. ``gate_version`` 2.
[3] Open front. WORN_OPEN = WORN_J with the slot cols [270, 330) in skin
    (the body shows) -> G_O = two panels cols [140, 270) + [330, 460) rows
    200..599, area 2 x 130 x 400 - 8 = 103992. GHOST_OPEN = the jacket with
    the slot in its lining (90, 40, 40) (the inside of the back; |ΔRGB| to
    skin 110 -> no skin). Beyond the margin: slot cols 275..324 x rows
    200..599 = 50 x 400 = 20000 px, plus the 4 slot-side pixels (rows 200 /
    599, cols 274 / 325) next to the panels' cut inner corners = 20004.
    Old: outside 20004 / 103992 = 0.19236 -> "more than the garment"
    refused. New: the slot is body between two ghost∩region pixels on its
    row (``body_openings``) -> outside 0.0, opening_seen 0.19236, ok.
    Counter-case — a gap that is background: BASE_LEGS = skin torso cols
    [200, 400) rows [100, 600) + legs [200, 260) and [340, 400) rows
    [600, 900); WORN_P = + trousers P (hip cols [240, 360) rows [500, 600),
    legs as the base's rows [600, 880)) in green (40, 90, 50). GHOST_SHUT =
    P with the gap cols [260, 340) rows [600, 880) filled (legs drawn
    together): the gap is not base -> no opening; beyond: cols 265..334 x
    rows 605..879 (rows 600..604 lie in the margin of the hip block) = 70 x
    275 = 19250 px over P's area 12000 + 2 x 60 x 280 = 45600 (+ the two
    crotch corners the closing fills, - the cut corners) -> outside 0.4221
    (± 0.005) -> refused "more than the garment" (old and new).
[4] Width: a cut-off piece still refuses, a wide one is ``outside``'s.
    GHOST_HALF = the jacket cols [140, 360): w_ratio 219 / 319 = 0.687 <
    0.80 -> "garment width changed"; centre_dx ((140 + 359) - (140 + 459))
    / 2 / 799 = -0.06258 recorded. GHOST_W112 = the jacket cols [121, 479)
    (w 357 / 319 = 1.119, the ±12 % of the ruling): inside [0.80, 1.25]. Its
    19 px each side lie on the base body but outside G_J's columns — no
    region pixel further out on the row, so no opening: beyond = 2 x 14 x
    400 = 11200 px + the 4 pixels beside G_J's cut corners (rows 200 / 599,
    cols 134 / 465) = 11204 -> outside 0.08753 > 0.05 -> refused for
    outside, NOT for its width.
[5] Waistband registration on a region with a re-shaded patch. REGION_PATCH =
    G_P (the [3] trousers region) + a patch cols [290, 310) rows [440, 480)
    (800 px, 20 rows above the waistband, beyond the margin).
    register_waistband(REGION_PATCH, P exact, Hb 799): the patch is below
    WAIST_PART_MIN 0.1 of G_P -> dropped; region top 500, band rows 508..532
    span 120, the ghost the same -> scale 1.0, shift 0, negligible.
    Old: region top 440 (the patch), band 448..472 span 20; start scale
    200 / 200 = 1 -> ghost band 508..532 span 120 -> 0.16667; band rows 500
    + round(47.94) = 548 .. 500 + round(191.76) = 692: 52 rows of 120 and 93
    of 200 -> median 200 -> 0.1; band 580..820 -> median 200 -> 0.1 (stable):
    scale 0.1, within_caps True -> applied (the live jeans: 0.056 / 0.040).
    New with the range alone: an estimate of 0.1 is outside
    WAIST_SCALE_RANGE [1/3, 3] -> within_caps False (not applied).
    _touching keeps the largest part: a ghost cols [291, 309) rows
    [440, 478) that touches only the patch is measured against the whole
    region (bbox [200, 440, 399, 879]): w_ratio 17 / 199 = 0.085 -> refused
    "garment width changed" (against the patch alone it was 17 / 19 = 0.895).
[6] Fails on the old code (garment_gates.py PINNED at 54cea23e, read with
    ``git show`` into a temp module): [1] refused "skin left in the image";
    [2] refused "garment top moved"; [3] refused "more than the garment in
    the image"; [5] scale 0.1 within the caps.
[7] Re-gate: garment_clothing.GATE_VERSIONS["ghost"] = GHOST_GATE_VERSION
    (3 since the gate audit); a stored ghost record without gate_version is
    stale (re-gated from its file on the next run), one of the current
    version is not; limits("clothing")["ghost"] has no top_dy / centre_dx
    (their chips are information).

Ghost gate version 3 (smoke_garment_gate_audit.py): the area numbers above
are ``outside_near`` now (a warning above 0.05); ``outside`` is the largest
part of those pixels more than 0.02 x 799 = 15.98 px (Euclidean) from the
region:
  [1] the inside below the hem, rows r - 599 >= 16 = 615..619 x 280 = 1400
      -> 1400 / 127996 = 0.01094.
  [2] the raised jacket: at most 10 px from the region -> 0.0.
  [3] legs drawn together: gap cols with min(c - 259, 340 - c) >= 16 =
      275..324 (50), rows r - 599 >= 16 = 615..879 (265) -> 13250 px over
      45600 (+ the crotch fills) = 0.2906 (± 0.005) -> still refused.
  [4] the ±12 % jacket: cols 140 - c >= 16 -> 121..124 and c - 459 >= 16
      -> 475..478, 4 x 400 = 1600 px each side, two parts -> 1600 / 127996
      = 0.0125 -> ACCEPTED (warning: near 0.08753): a uniformly wider ghost
      is the fit's to correct, not more garment.

Ghost gate version 4 (Ruling A17, smoke_ghost_hem_reference.py) changes [1]
and [7]: the hem is gated against the worn piece's (``centre_hem``, ± round(
0.04 x 799) = 32 columns around the base's shoulder-row centre (120 + 479) /
2 = 299.5 -> 300). GHOST_HEM's inside below the hem runs on from the jacket
in every band column, so its hem is row 619: (619 - 100) / 799 = 0.64956
against the region's 599: 0.62453 -> |Δ| 20 / 799 = 0.02503 > 0.02 —
refused for its hem alone (no skin: skin_left 0.0; the old code's skin
refusal of [6] still holds) — the dark underside below Kai's jacket hem in
miniature. [2]'s raised jacket moves its hem 10 / 799 = 0.0125: still ok.
[7]: GATE_VERSIONS["ghost"] = 4; a version 3 record is stale.
"""
import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_TMP = tempfile.mkdtemp(prefix="smoke_ghost_v2_")
os.environ["STORAGE_DIR"] = _TMP
os.environ["INSTANCE_DIR"] = _TMP
from app.core import paths  # noqa: E402

paths.init(_TMP)

import numpy as np  # noqa: E402

from app.core import garment_clothing, garment_gates as gg, garment_images as gi  # noqa: E402

PINNED = "54cea23e"
#: [1] under ghost gate version 4 (Ruling A17, docstring).
HEM_A17 = ("garment ends at another height than the worn piece: |Δ| 0.025 Hb > 0.02 Hb "
           "(ghost 0.64956, worn 0.62453)")
FAILS = []
W, H = 600, 1000
HB = 799
GREY = (128, 128, 128)
SKIN = (200, 160, 140)
HAIR = (35, 30, 25)
BLACK = (20, 20, 20)
INSIDE = (30, 28, 24)
LINING = (90, 40, 40)
GREEN = (40, 90, 50)
TMP = Path(_TMP)


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


def canvas():
    return np.full((H, W, 3), GREY, dtype=np.uint8)


def mask_of(rgb):
    return np.abs(rgb.astype(np.int16) - 128).max(2) > 2


def has(record, key, text):
    return any(text in x for x in record.get(key) or [])


BASE = canvas()
BASE[100:900, 120:480] = SKIN
BASE[100:180, 120:480] = HAIR
WORN_J = BASE.copy()
WORN_J[200:600, 140:460] = BLACK


def jacket(top=200, bottom=600, x0=140, x1=460):
    img = canvas()
    img[top:bottom, x0:x1] = BLACK
    return img


GHOST_HEM = jacket()
GHOST_HEM[600:620, 160:440] = INSIDE
GHOST_UP = jacket(190, 590)
WORN_OPEN = WORN_J.copy()
WORN_OPEN[200:600, 270:330] = SKIN
GHOST_OPEN = jacket()
GHOST_OPEN[200:600, 270:330] = LINING
GHOST_HALF = jacket(x1=360)
GHOST_W112 = jacket(x0=121, x1=479)

BASE_LEGS = canvas()
BASE_LEGS[100:600, 200:400] = SKIN
BASE_LEGS[600:900, 200:260] = SKIN
BASE_LEGS[600:900, 340:400] = SKIN


def trousers(img):
    img[500:600, 240:360] = GREEN
    img[600:880, 200:260] = GREEN
    img[600:880, 340:400] = GREEN
    return img


WORN_P = trousers(BASE_LEGS.copy())
GHOST_P = trousers(canvas())
GHOST_SHUT = GHOST_P.copy()
GHOST_SHUT[600:880, 260:340] = GREEN


def pinned(commit, name):
    """app/core/<name>.py at ``commit`` as a throwaway module."""
    src = subprocess.run(["git", "-C", str(ROOT), "show", f"{commit}:app/core/{name}.py"],
                         check=True, capture_output=True, text=True).stdout
    path = TMP / f"{name}_{commit}.py"
    path.write_text(src)
    spec = importlib.util.spec_from_file_location(f"{name}_{commit}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def gate(module, base, worn, ghost, length_free=False):
    region = module.garment_region(base, mask_of(base), worn, mask_of(worn))
    kw = {"length_free": True} if length_free else {}
    return module.ghost_clothing_gate(base, mask_of(base), region, ghost, mask_of(ghost), view="back", **kw)


def main() -> int:
    region_j = gg.garment_region(BASE, mask_of(BASE), WORN_J, mask_of(WORN_J))
    check("G_J area", int(region_j.sum()), 127996)

    print("[1] skin sampled on the thighs")
    check("skin sample", [float(v) for v in gg.skin_colour(BASE, mask_of(BASE))], [200.0, 160.0, 140.0])
    hem = gate(gg, BASE, WORN_J, GHOST_HEM)
    check("hem inside: no skin, refused only for its hem (A17)",
          (hem["ok"], hem["skin_left"], hem["outside_near"], hem["outside"], hem["reasons"]),
          (False, 0.0, 0.03281, 0.01094, [HEM_A17]))

    print("[2] position recorded")
    up = gate(gg, BASE, WORN_J, GHOST_UP)
    check("raised: ok, warning", (up["ok"], up["top_dy"], up["outside_near"], up["outside"],
                                  has(up, "warnings", "garment top moved"),
                                  has(up, "reasons", "garment top moved"), up["gate_version"]),
          (True, -0.01252, 0.01252, 0.0, True, False, gg.GHOST_GATE_VERSION))

    print("[3] open front")
    region_o = gg.garment_region(BASE, mask_of(BASE), WORN_OPEN, mask_of(WORN_OPEN))
    check("G_O area", int(region_o.sum()), 103992)
    opened = gate(gg, BASE, WORN_OPEN, GHOST_OPEN)
    check("open: ok, the lining is no 'more'", (opened["ok"], opened["outside"], opened["opening_seen"],
                                                opened["skin_left"], opened["w_ratio"]),
          (True, 0.0, 0.19236, 0.0, 1.0))
    shut = gate(gg, BASE_LEGS, WORN_P, GHOST_SHUT)
    near("legs drawn together: outside_near", shut["outside_near"], 19250 / 45600, 0.005)
    near("legs drawn together: outside (far part)", shut["outside"], 13250 / 45600, 0.005)
    check("legs drawn together: refused, no opening", (shut["ok"], has(shut, "reasons", "more than the garment"),
                                                       shut["opening_seen"]), (False, True, 0.0))

    print("[4] width: cut off refuses, wide is outside's")
    half = gate(gg, BASE, WORN_J, GHOST_HALF)
    check("half: refused for width, centre recorded",
          (half["ok"], half["w_ratio"], has(half, "reasons", "garment width changed"), half["centre_dx"],
           has(half, "warnings", "garment centre moved")), (False, 0.687, True, -0.06258, True))
    w112 = gate(gg, BASE, WORN_J, GHOST_W112)
    check("±12 %: not for its width; its rim a warning (gate version 3)",
          (w112["ok"], w112["w_ratio"], has(w112, "reasons", "garment width changed"),
           w112["outside_near"], w112["outside"], has(w112, "warnings", "garment rim beyond the worn piece")),
          (True, 1.119, False, 0.08753, 0.0125, True))

    print("[5] waistband registration on a region with a patch")
    region_p = gg.garment_region(BASE_LEGS, mask_of(BASE_LEGS), WORN_P, mask_of(WORN_P))
    patched = region_p.copy()
    patched[440:480, 290:310] = True
    est = gg.register_waistband(patched, mask_of(GHOST_P), body_h=HB)
    check("patch dropped: exact", (est["scale"], est["shift_px"], est["negligible"], est["within_caps"]),
          (1.0, [0.0, 0.0], True, True))
    old = pinned(PINNED, "garment_gates")
    old_est = old.register_waistband(patched, mask_of(GHOST_P), body_h=HB)
    near("old: scale on the patch", old_est["scale"], 0.1, 0.001)
    check("old: within the caps (applied)", old_est["within_caps"], True)
    lo, hi = gg.WAIST_SCALE_RANGE
    check("new range refuses 0.1", lo <= old_est["scale"] <= hi, False)
    tiny = canvas()
    tiny[440:478, 291:309] = GREEN
    g = gg.ghost_clothing_gate(BASE_LEGS, mask_of(BASE_LEGS), patched, tiny, mask_of(tiny), view="back",
                               length_free=True)
    check("largest part kept: refused for width", (g["ok"], g["bbox_garment"], g["w_ratio"],
                                                   has(g, "reasons", "garment width changed")),
          (False, [200, 440, 399, 879], 0.085, True))

    print(f"[6] fails on the old code ({PINNED})")
    check("old [1]: skin refused", has(gate(old, BASE, WORN_J, GHOST_HEM), "reasons", "skin left in the image"),
          True)
    check("old [2]: top refused", has(gate(old, BASE, WORN_J, GHOST_UP), "reasons", "garment top moved"), True)
    old_open = gate(old, BASE, WORN_OPEN, GHOST_OPEN)
    check("old [3]: open refused", (has(old_open, "reasons", "more than the garment"), old_open["outside"]),
          (True, 0.19236))

    print("[7] re-gate + limits")
    check("GATE_VERSIONS ghost", (garment_clothing.GATE_VERSIONS.get("ghost"), gg.GHOST_GATE_VERSION), (6, 6))
    check("record without version stale", gi._stale_gate(garment_clothing, "ghost", {"ok": False}), True)
    check("version 3 stale", gi._stale_gate(garment_clothing, "ghost", {"ok": False, "gate_version": 3}), True)
    check("current version not stale", gi._stale_gate(garment_clothing, "ghost", {"ok": False, "gate_version": 6}),
          False)
    ghost_limits = gg.limits("clothing")["ghost"]
    check("no position limits", ("top_dy" in ghost_limits, "centre_dx" in ghost_limits), (False, False))
    check("width limit", ghost_limits["w_ratio"], {"op": "range", "value": [0.8, 1.25]})

    if FAILS:
        print(f"FAILED: {', '.join(FAILS)}")
        return 1
    print("all ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
