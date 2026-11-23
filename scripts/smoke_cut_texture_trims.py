"""Smoke: the trims' own colour from the item text (stage "layers", 2026-11-22: Glut's bra — the picture's straps and
band are black with gold edges, the fabric fill gave them the cups' scales).

Usage:
    ./.venv/bin/python scripts/smoke_cut_texture_trims.py

No server, no world DB, no Blender, no hub job: ``garment_cut_texture.trim_style`` / ``paint_trims`` /
``composed_as_now`` on literals, ``get_item`` stubbed. Every expectation is derived by hand below.

[1] ``trim_style`` (segments split at ",", ";" and "with"; a segment with a trim noun takes its first colour word, a
    trim segment without one right after it joins it, an edge colour stands before an edge noun or after an edge
    participle):
    [1.1] "push-up bra of glowing ember-red metal scales, molded half-cups ..., black straps, band and gore with gold
          edges" -> parts strap_l, strap_r, band_l, band_r, gore; colour black (24, 22, 22); edge gold (196, 152, 64);
          words ["black", "gold"]. ("ember-red" stands in a segment without a trim noun.)
    [1.2] Glut's text as it is in the world ("push-up bra of glowing ember-red metal scales, molded half-cups lifting
          her breasts together into deep cleavage") -> None: no trim noun, the trims keep the fabric fill.
    [1.3] "molded cups of red scales with black straps" -> straps only, black, no edge (the "with" split keeps the
          red with the cups).
    [1.4] "a cream blouse with a white collar edged in gold" -> collar, white (236, 234, 230), edge gold.
    [1.5] "black lether jacket, slim fit, zipper", "blue jeans", the gloves' "fingerless black leather opera gloves
          ..., glowing ember-red seams" -> None (no trim noun; "seams" is none).
    [1.6] "black straps, red band" -> the first colour group stands: straps black, the red band is not taken.
    [1.7] "band and gore with gold edges" (no colour of their own) -> None (an edge alone names no trim colour).
[2] ``paint_trims`` on a 512 px atlas, 10 px/cm, every pixel (200, 40, 40) (uniform: the grain is 0, so the painted
    colours are exact up to the Lab round trip, +-1). Islands (boxes, ``verts_px`` corners): cup_r x 10..110,
    y 10..110; strap_r x 200..220, y 10..210; band_r x 10..210, y 300..330. Style [1.3] + edge gold (parts strap_l,
    strap_r): bleed = round(1.0 cm * 10) = 10 px, edge band = round(0.25 * 10) = 2 px (Python rounds half to even).
    - the strap's middle (210, 110): 10 px from its sides -> black (24, 22, 22);
    - its left rim (200, 110) and one px inside (201, 110): within 2 px of the outline -> gold (196, 152, 64);
    - 5 px left of it (195, 110): background, nearest island the strap (the cup ends at x 110), within the bleed ->
      the edge colour, gold;
    - 15 px right of it (235, 110): outside the bleed -> unchanged (200, 40, 40);
    - the cup (60, 60) and the band (100, 315): not named -> unchanged;
    - info: islands ["strap_r"] (strap_l is not in the pattern), edge_px > 0.
    Without an edge colour the rim (200, 110) is black too. ``style`` None -> the atlas unchanged, islands [].
[3] ``composed_as_now``: a ready record composed before the stage (no "trim_style" key) of an item whose text names
    no trim colour -> True (nothing recomposes, nothing is re-rendered); the same record when the text names one ->
    False (the Build's step "compose": ``recompose``, CPU, 0 image jobs); a record with that style -> True; another
    ``sleeve_print`` -> False.
[4] Source: ``_finish`` paints the trims after ``compose`` only when the record's ``sleeve_print`` is not "picture"
    (then the small pieces come from the answer); ``generate`` and ``recompose`` store ``trim_style_of``.
"""
import inspect
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FAILS = []


def check(label, ok, detail=""):
    print(("OK   " if ok else "FAIL ") + label + (f"  ({detail})" if not (isinstance(detail, str) and detail == "") else ""))
    if not ok:
        FAILS.append(label)


from app.core import garment_cut_texture as gct  # noqa: E402

BLACK, GOLD, WHITE = [24, 22, 22], [196, 152, 64], [236, 234, 230]
GLUT = "push-up bra of glowing ember-red metal scales, molded half-cups lifting her breasts together into deep cleavage"

# [1]
st = gct.trim_style(GLUT + ", black straps, band and gore with gold edges")
check("[1.1] straps, band and gore black with gold edges",
      st == {"parts": ["strap_l", "strap_r", "band_l", "band_r", "gore"], "colour": BLACK, "edge": GOLD,
             "words": ["black", "gold"]}, st)
check("[1.2] Glut's text as it is: None", gct.trim_style(GLUT) is None, gct.trim_style(GLUT))
st = gct.trim_style("molded cups of red scales with black straps")
check("[1.3] the red stays with the cups", st == {"parts": ["strap_l", "strap_r"], "colour": BLACK, "edge": None,
                                                   "words": ["black"]}, st)
st = gct.trim_style("a cream blouse with a white collar edged in gold")
check("[1.4] a white collar edged in gold", st == {"parts": ["collar"], "colour": WHITE, "edge": GOLD,
                                                    "words": ["white", "gold"]}, st)
for text in ("black lether jacket, slim fit, zipper", "blue jeans",
             "fingerless black leather opera gloves reaching above her elbows, glowing ember-red seams"):
    check(f"[1.5] no trim noun: {text[:30]!r}", gct.trim_style(text) is None, gct.trim_style(text))
st = gct.trim_style("black straps, red band")
check("[1.6] the first colour group stands", st and st["parts"] == ["strap_l", "strap_r"] and st["colour"] == BLACK, st)
check("[1.7] an edge alone names no trim colour", gct.trim_style("band and gore with gold edges") is None)

# [2]
PPC, SIZE = 10.0, 512


def box(name, x0, y0, x1, y1):
    v = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
    return {"name": name, "part": 1, "verts_px": v, "tris": [[0, 1, 2], [0, 2, 3]], "bbox_px": [x0, y0, x1, y1],
            "loops_px": [v], "area_cm2": 0.0, "distortion": {}}


ISL = {"version": 1, "atlas_px": SIZE, "px_per_cm": PPC, "margin_cm": 1.5, "seams": [],
       "islands": [box("cup_r", 10, 10, 110, 110), box("strap_r", 200, 10, 220, 210), box("band_r", 10, 300, 210, 330)]}
ATLAS = np.zeros((SIZE, SIZE, 3), np.uint8)
ATLAS[:] = (200, 40, 40)
style = {"parts": ["strap_l", "strap_r"], "colour": BLACK, "edge": GOLD, "words": ["black", "gold"]}
out, info = gct.paint_trims(ATLAS, ISL, SIZE, PPC, style)


def near(px, want):
    return bool(np.all(np.abs(np.asarray(px, int) - np.asarray(want)) <= 1))


def at(img, x, y):
    return img[y, x].tolist()


check("[2] the strap's middle is black", near(at(out, 210, 110), BLACK), at(out, 210, 110))
check("[2] its rim is gold", near(at(out, 200, 110), GOLD) and near(at(out, 201, 110), GOLD),
      (at(out, 200, 110), at(out, 201, 110)))
check("[2] the bleed 5 px beside it is gold", near(at(out, 195, 110), GOLD), at(out, 195, 110))
check("[2] 15 px beside it is unchanged", near(at(out, 235, 110), (200, 40, 40)), at(out, 235, 110))
check("[2] the cup and the band are unchanged", near(at(out, 60, 60), (200, 40, 40))
      and near(at(out, 100, 315), (200, 40, 40)), (at(out, 60, 60), at(out, 100, 315)))
check("[2] info names the strap only, with an edge", info["islands"] == ["strap_r"] and info["edge_px"] > 0, info)
out2, _ = gct.paint_trims(ATLAS, ISL, SIZE, PPC, {**style, "edge": None})
check("[2] without an edge colour the rim is black", near(at(out2, 200, 110), BLACK), at(out2, 200, 110))
out3, info3 = gct.paint_trims(ATLAS, ISL, SIZE, PPC, None)
check("[2] no style: unchanged", np.array_equal(out3, ATLAS) and info3 == {"islands": []}, info3)

# [3]
TEXT = {"v": GLUT}
import app.models.inventory as inv  # noqa: E402

_saved = inv.get_item
inv.get_item = lambda iid, **_k: {"id": iid, "prompt_fragment": TEXT["v"]}
try:
    old = {"state": "ready", "sleeve_print": "plain"}
    check("[3] an old record, no trim words: composed as now", gct.composed_as_now(old, "i1", {"sleeve_print": "plain"}))
    TEXT["v"] = GLUT + ", black straps, band and gore with gold edges"
    check("[3] the text names a trim colour: recompose", not gct.composed_as_now(old, "i1", {"sleeve_print": "plain"}))
    new = {**old, "trim_style": gct.trim_style(TEXT["v"])}
    check("[3] composed with that style", gct.composed_as_now(new, "i1", {"sleeve_print": "plain"}))
    check("[3] another sleeve option", not gct.composed_as_now(new, "i1", {"sleeve_print": "picture"}))
finally:
    inv.get_item = _saved

# [4]
fin = inspect.getsource(gct._finish)
check("[4] _finish paints the trims after compose, not with 'picture'",
      fin.index("compose(") < fin.index("paint_trims(") and 'sleeve_print") != "picture"' in fin)
check("[4] generate and recompose store trim_style_of",
      "trim_style_of(item_id)" in inspect.getsource(gct.generate)
      and "trim_style_of(item_id)" in inspect.getsource(gct.recompose))

print("ALL OK" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}")
sys.exit(1 if FAILS else 0)
