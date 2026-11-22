#!/usr/bin/env python3
"""Smoke: the fitted cut-texture prompt names every piece of its template by a place NO other piece shares
(review 2026-11-22: "the piece at the top left" named both front leg panels of Lirien's trousers, the cup and the gore
of a bra, both backs of the hand — MiniMax could not tell them apart).

No server, no world DB, no Blender, no image job. Usage: ./.venv/bin/python scripts/smoke_cut_texture_fitted_layout.py

The fixtures are the REAL pattern layouts (``uv_pattern.ROWS``) of the group-A cut-only runs of 2026-11-21 (atlas 2048
px; name, ``bbox_px`` and ``area_cm2`` copied from their ``islands.json``), plus two hand-made cases. Cells are thirds
(``FITTED_CELL`` 1/3 = 682.67 px): centre = bbox centre / 2048; "top" < 0.3333 < "middle" < 0.6667 < "bottom", the same
for left / centre / right. "large" = the job's largest bbox (w x h). Rows (``_rows_of``): pieces sorted by bbox top;
a piece whose top lies above the row's lowest bottom joins the row.

[1] Trousers FRONT job (front_l, front_r, waistband): front_l [502, 22, 974, 1379] centre (0.360, 0.342) -> the
    middle row (0.342 > 0.3333), centre column -> "in the centre"; front_r [22, 22, 481, 1385] (0.123, 0.343) -> "in
    the middle left"; waistband [554, 1407, 1493, 1847] (0.500, 0.794) -> "at the bottom centre", 939 / 440 = 2.1 < 6 is
    no strip. Largest bbox: front_l 472 x 1357 = 640 504 > front_r 459 x 1363 = 625 617 -> "the large piece in the
    centre is the left front leg panel". Mains front_r / front_l (areas 1828 / 1878 > waistband 383) are the two largest
    -> "the two largest shapes".
    BACK job: back_l (0.609, 0.340) "in the centre", back_r (0.866, 0.341) "in the middle right", largest back_r
    505 x 1354 = 683 770 > 504 x 1349 = 679 896.
[2] Bra FRONT job (all nine pieces): top centre holds cup_r (0.357, 0.056), cup_l (0.570, 0.059), cup_top_r (0.406,
    0.154), cup_top_l (0.593, 0.143). Rows by top: cup_l 31..208 and cup_r 31..198 share a row (bottom 208); cup_top_*
    start at 240 > 208 -> a second row. Two rows -> "upper" / "lower", each ordered by x: "the left one of the two upper
    pieces at the top centre is the right cup", "the right one ... is the left cup", "the left one of the two lower
    pieces at the top centre is the right upper cup", "the right one ... is the left upper cup". Top right: gore
    (0.713, 0.052) 31..181 and band_l (0.678, 0.262) 421..651 -> two rows of one: "the upper piece at the top right is
    the centre gore", "the lower piece at the top right is the left band". band_r (0.324, 0.256) alone: "the piece at
    the top left is the right band". strap_r (0.253, 0.411) "in the middle left", the largest bbox (975 x 320 = 312 000 >
    strap_l 979 x 300 = 293 700): "the large piece in the middle left is the right strap"; strap_l (0.746, 0.406): "the
    piece in the middle right is the left strap". Mains cup_r / cup_l (areas 98 / 100) are NOT the two largest (the
    straps 162 / 143 are larger), not alone, and exactly the upper row -> "the two upper pieces at the top centre".
[3] Gloves FRONT job: glove_back_r (0.133, 0.316) "at the top left", the larger bbox (466 x 1215 = 566 190 > 418 x 1221
    = 510 378) -> "the large piece at the top left is the back of the right hand"; glove_back_l (0.368, 0.318) -> "the
    piece at the top centre is the back of the left hand" (before: both "at the top left" / "at the top").
    BACK job: palm_l (0.604, 0.331) "at the top centre", palm_r (0.859, 0.328) "at the top right", largest palm_r
    498 x 1264 = 629 472 > 468 x 1278 = 598 104.
[4] Tights FRONT job: leg_r (0.219, 0.430) "in the middle left"; leg_l (0.648, 0.428) "in the centre", the larger bbox
    (859 x 1708 = 1 467 172 > 851 x 1714 = 1 458 614). Bottom left: gusset (0.321, 0.875) 1761..1823; gusset_2 (0.180,
    0.940) and gusset_3 (0.294, 0.942) start at 1877 > 1823 -> a second row, gusset_3 joins it (1877 < 1975): "the upper
    piece at the bottom left is the crotch gusset", "the left one of the two lower pieces at the bottom left is the
    crotch gusset 2", "the right one ... is the crotch gusset 3". Bottom centre: waistband (0.471, 0.882) 1761..1854;
    gusset_4 (0.447, 0.952) and waistband_2 (0.626, 0.935) from 1877: "the upper piece at the bottom centre is the
    waistband", "the left one of the two lower pieces at the bottom centre is the crotch gusset 4", "the right one ...
    is the waistband 2". (waistband 442 / 93 = 4.75 and waistband_2 393 / 78 = 5.04 are < 6: no strip.)
[5] Hand-made — the live trousers case (both fronts in one cell): front_r [22, 22, 470, 700] centre (0.115, 0.176),
    front_l [480, 22, 880, 700] (0.332, 0.176), both "at the top left", one row (equal height ranges) -> ordered by
    x: "the left one of the two pieces at the top left is the right front leg panel", "the right one ... is the left
    front leg panel"; waistband [100, 1500, 1900, 1560] (0.488, 0.747) 1800 / 60 = 30 >= 6 -> "the long thin strip at
    the bottom centre is the waistband". Mains areas 900 / 880 > waistband 300 -> "the two largest shapes".
    A brief whose gusset shares the front panel's cell: front [100, 100, 500, 500] (0.146, 0.146), gusset
    [550, 100, 650, 400] (0.293, 0.122), one row -> the main phrase is the front's ref "the left one of the two pieces
    at the top left". Three pieces in one row at the bottom centre: [700, 1400, 800, 1500], [900, 1400, 1000, 1500],
    [1100, 1400, 1200, 1500] (centres 0.366 / 0.464 / 0.562, all 0.708) -> "the first / second / third from the left of
    the three pieces at the bottom centre".
[6] Every fixture job: no two pieces share a layout sentence's place phrase (the text before " is the ").
[7] The top family is unchanged: ``layout_words`` without ``family`` on the trousers front gives the old
    ``LAYOUT_SIDE`` words — front_l (0.360) is "at the top" (0.342 < 0.36, 0.36 not < 0.36 so no "left").
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_T = Path(tempfile.mkdtemp(prefix="smoke-fitted-layout-"))
os.environ.setdefault("STORAGE_DIR", str(_T / "world"))
os.environ.setdefault("INSTANCE_DIR", str(_T / "instance"))
from app.core import paths  # noqa: E402
paths.init(_T / "world")
paths.init_instance(_T / "instance")
from app.core import garment_cut_texture as gct  # noqa: E402

FAILS = []


def check(name, got, want):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + name + ("" if ok else f"\n       got  {got!r}\n       want {want!r}"))
    if not ok:
        FAILS.append(name)


def payload(*isl):
    return {"atlas_px": 2048, "islands": [{"name": n, "bbox_px": list(b), "area_cm2": a} for n, b, a in isl]}


def by_name(p):
    return dict(zip(gct._pattern_order(p), gct.layout_words(p, "fitted")))


TROUSERS_FRONT = payload(("front_l", (502, 22, 974, 1379), 1878), ("front_r", (22, 22, 481, 1385), 1828),
                         ("waistband", (554, 1407, 1493, 1847), 383))
TROUSERS_BACK = payload(("back_l", (995, 22, 1499, 1371), 2100), ("back_r", (1521, 22, 2026, 1376), 2105))
BRA = payload(("cup_l", (963, 31, 1373, 208), 100), ("cup_r", (531, 31, 931, 198), 98),
              ("cup_top_l", (1038, 240, 1391, 348), 60), ("cup_top_r", (656, 240, 1007, 389), 56),
              ("gore", (1404, 31, 1517, 181), 17), ("band_l", (1043, 421, 1734, 651), 69),
              ("band_r", (314, 421, 1012, 628), 66), ("strap_l", (1037, 682, 2016, 982), 143),
              ("strap_r", (31, 682, 1006, 1002), 162))
GLOVES_FRONT = payload(("glove_back_l", (545, 40, 963, 1261), 455), ("glove_back_r", (40, 40, 506, 1255), 459))
GLOVES_BACK = payload(("palm_l", (1002, 40, 1470, 1318), 670), ("palm_r", (1510, 40, 2008, 1304), 656))
TIGHTS = payload(("waistband", (744, 1761, 1186, 1854), 60), ("waistband_2", (1085, 1877, 1478, 1955), 48),
                 ("gusset", (594, 1761, 721, 1823), 21), ("gusset_2", (301, 1877, 434, 1975), 35),
                 ("gusset_3", (458, 1877, 745, 1980), 61), ("gusset_4", (769, 1877, 1062, 2024), 93),
                 ("leg_l", (897, 23, 1756, 1731), 4439), ("leg_r", (23, 23, 874, 1737), 4331))
LIVE_TROUSERS = payload(("front_r", (22, 22, 470, 700), 900), ("front_l", (480, 22, 880, 700), 880),
                        ("waistband", (100, 1500, 1900, 1560), 300))
BRIEF_SHARED = payload(("front", (100, 100, 500, 500), 600), ("gusset", (550, 100, 650, 400), 700))
THREE = payload(("waistband", (700, 1400, 800, 1500), 1), ("cuff_r", (900, 1400, 1000, 1500), 1),
                ("cuff_l", (1100, 1400, 1200, 1500), 1))

# [1]
check("[1] trousers front", by_name(TROUSERS_FRONT), {
    "front_r": "the piece in the middle left is the right front leg panel",
    "front_l": "the large piece in the centre is the left front leg panel",
    "waistband": "the piece at the bottom centre is the waistband"})
check("[1] trousers front main", gct.main_words(TROUSERS_FRONT, "front")["phrase"], "the two largest shapes")
check("[1] trousers back", by_name(TROUSERS_BACK), {
    "back_l": "the piece in the centre is the left back leg panel",
    "back_r": "the large piece in the middle right is the right back leg panel"})
# [2]
check("[2] bra", by_name(BRA), {
    "cup_r": "the left one of the two upper pieces at the top centre is the right cup",
    "cup_l": "the right one of the two upper pieces at the top centre is the left cup",
    "cup_top_r": "the left one of the two lower pieces at the top centre is the right upper cup",
    "cup_top_l": "the right one of the two lower pieces at the top centre is the left upper cup",
    "gore": "the upper piece at the top right is the centre gore",
    "band_l": "the lower piece at the top right is the left band",
    "band_r": "the piece at the top left is the right band",
    "strap_r": "the large piece in the middle left is the right strap",
    "strap_l": "the piece in the middle right is the left strap"})
check("[2] bra main", gct.main_words(BRA, "front"),
      {"phrase": "the two upper pieces at the top centre", "count": 2, "names": "the right cup and the left cup"})
# [3]
check("[3] gloves front", by_name(GLOVES_FRONT), {
    "glove_back_r": "the large piece at the top left is the back of the right hand",
    "glove_back_l": "the piece at the top centre is the back of the left hand"})
check("[3] gloves back", by_name(GLOVES_BACK), {
    "palm_l": "the piece at the top centre is the left palm",
    "palm_r": "the large piece at the top right is the right palm"})
# [4]
check("[4] tights", by_name(TIGHTS), {
    "leg_r": "the piece in the middle left is the right leg",
    "leg_l": "the large piece in the centre is the left leg",
    "gusset": "the upper piece at the bottom left is the crotch gusset",
    "gusset_2": "the left one of the two lower pieces at the bottom left is the crotch gusset 2",
    "gusset_3": "the right one of the two lower pieces at the bottom left is the crotch gusset 3",
    "waistband": "the upper piece at the bottom centre is the waistband",
    "gusset_4": "the left one of the two lower pieces at the bottom centre is the crotch gusset 4",
    "waistband_2": "the right one of the two lower pieces at the bottom centre is the waistband 2"})
# [5]
check("[5] live trousers", by_name(LIVE_TROUSERS), {
    "front_r": "the left one of the two pieces at the top left is the right front leg panel",
    "front_l": "the right one of the two pieces at the top left is the left front leg panel",
    "waistband": "the long thin strip at the bottom centre is the waistband"})
check("[5] live trousers main", gct.main_words(LIVE_TROUSERS, "front")["phrase"], "the two largest shapes")
check("[5] brief sharing a cell main", gct.main_words(BRIEF_SHARED, "front")["phrase"],
      "the left one of the two pieces at the top left")
check("[5] three in a row", [gct.fitted_places(THREE)[n]["ref"] for n in ("waistband", "cuff_r", "cuff_l")],
      [f"the {w} from the left of the three pieces at the bottom centre" for w in ("first", "second", "third")])
# [6]
for label, p in (("trousers front", TROUSERS_FRONT), ("trousers back", TROUSERS_BACK), ("bra", BRA),
                 ("gloves front", GLOVES_FRONT), ("gloves back", GLOVES_BACK), ("tights", TIGHTS),
                 ("live trousers", LIVE_TROUSERS), ("brief shared", BRIEF_SHARED), ("three", THREE)):
    places = [s.split(" is the ")[0] for s in gct.layout_words(p, "fitted")]
    check(f"[6] {label}: every place phrase unique", len(set(places)), len(places))
# [7]
check("[7] top family unchanged", gct.layout_words(TROUSERS_FRONT), [
    "the piece at the top left is the right front leg panel",
    "the large piece at the top is the left front leg panel",
    "the piece at the bottom is the waistband"])

print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL OK")
sys.exit(1 if FAILS else 0)
