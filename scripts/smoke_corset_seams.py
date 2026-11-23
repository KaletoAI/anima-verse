"""Corset v3 (review 2026-11-22: the item's picture shows princess seams and boning, the cut atlas was plain): a
corset top's sewn seams are cut-mark lines (``corset_darts.seam_lines`` -> the cut's ``marks.json``) painted onto the
cut atlas at assembly (``cut_texture_post.draw_seams``, keyed by ``garment_cut_texture.placket_key``). No server, no
world DB, no Blender. Every number below is derived by hand.

[1] ``seam_lines(5, 81)``: c0 = 40; front offsets DART_COLS 8 and SEAM_FRONT_OUTER_COLS 16 per 40 columns ->
    round(8 x 80 / 40) = 16, round(16 x 80 / 40) = 32 -> columns 8, 24, 56, 72 (part 1, base 0); back SEAM_BACK_COLS
    10 -> round(10 x 80 / 40) = 20 -> columns 20, 60 (part 2, base 5 x 81 = 405). seam_front_0 = [8, 89, 170, 251,
    332]; seam_back_1 = [465, 546, 627, 708, 789]; six lines; the front ones on the bust darts' columns 24 / 56
    (``dart_seams``: round(8 x 80 / 40) = 16 off the centre).
[2] ``draw_seams`` on a 60 x 60 grey atlas sRGB (119, 119, 119) (L* 50.0), island A = columns 0..29, px_per_cm 20,
    a vertical ``seam_front_0`` on A at x = 20 from y 5 to 55 (a pixel's centre is x + 0.5): the groove SEAM_GROOVE_CM
    0.12 x 20 / 2 = 1.2 px either side -> centres 19.5 / 20.5 (0.5 off), not 18.5 / 21.5 (1.5 off) -> pixels 19, 20
    at L* 50 - SEAM_DL 16 = 34; the stitches SEAM_HALF_CM 0.35 x 20 = 7 px off (x 13 / 27, half 0.5) -> pixels 12,
    13 and 26, 27 at L* 50 - STITCH_DL 12 = 38; x 16 between them unchanged (L* 50); a second seam on A at x = 45
    (outside A's pixels) changes nothing there; a ``seam_back_0`` on island B (no mask) and a ``centre_back`` line
    are not painted; info seams == ["seam_front_0", "seam_front_1"] (both lines of A are walked, the one outside paints nothing).
    A red atlas sRGB (150, 80, 80) (L* 42.5 — under 50, where ``_shade`` would lighten; its darker shade stays
    inside sRGB, a saturated red would clip): the groove is DARKER, L* 42.5 - 16 = 26.5 (SEAM_DARK_MIN_L 25); a
    near-black sRGB (30, 30, 30) (L* 11.3) gets a LIGHTER groove, 11.3 + 16 = 27.3.
[3] ``placket_key``: a strapless top without a placket -> ":seams3" (SEAM_VERSION 3, corset v7: the seam under the
    cups is smoothed); with a lacing (3 buttons ignored by lacing) -> ":placket<PLACKET_VERSION>-lacing-0:seams3"; a
    skirt -> "".

Usage: ./.venv/bin/python scripts/smoke_corset_seams.py
"""
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app" / "blender" / "scripts"))

_SCRATCH = Path(tempfile.mkdtemp(prefix="smoke-corset-seams-"))
from app.core import paths  # noqa: E402
paths.init(_SCRATCH / "world")
paths.init_instance(_SCRATCH / "instance")

import corset_darts as cd  # noqa: E402
from app.core import cut_texture_post as ctp  # noqa: E402
from app.core import garment_cut_texture as gct  # noqa: E402
from app.core import garment_template as gt  # noqa: E402

FAILS = []


def check(label, ok, detail=""):
    print(("OK   " if ok else "FAIL ") + label + (f"  ({detail})" if not ok and detail != "" else ""))
    if not ok:
        FAILS.append(label)


# [1]
sl = cd.seam_lines(5, 81)
check("[1] six lines", sorted(sl) == ["seam_back_0", "seam_back_1", "seam_front_0", "seam_front_1", "seam_front_2",
                                      "seam_front_3"], sorted(sl))
check("[1] seam_front_0 column 8", sl["seam_front_0"] == (1, [8, 89, 170, 251, 332]), sl["seam_front_0"])
check("[1] seam_back_1 column 60 of the back", sl["seam_back_1"] == (2, [465, 546, 627, 708, 789]), sl["seam_back_1"])
check("[1] front columns 8, 24, 56, 72", [sl[f"seam_front_{k}"][1][0] for k in range(4)] == [8, 24, 56, 72])
darts = {a for a, _b in cd.dart_seams(5, 81)}
check("[1] the inner front seams continue the bust darts", {24, 56} <= darts, sorted(darts))

# [2]
atlas = np.full((60, 60, 3), 119, np.uint8)
mask_a = np.zeros((60, 60), bool)
mask_a[:, :30] = True
marks = {"seam_front_0": {"island": "A", "px": [[20, 5], [20, 55]]},
         "seam_front_1": {"island": "A", "px": [[45, 5], [45, 55]]},
         "seam_back_0": {"island": "B", "px": [[10, 5], [10, 55]]},
         "centre_back": {"island": "A", "px": [[5, 5], [5, 55]]}}
out, info = ctp.draw_seams(atlas, {"A": mask_a}, marks, px_per_cm=20.0)


def L(y, x):
    return float(ctp.srgb_to_lab(out[y, x].astype(np.float64))[0])


base_l = float(ctp.srgb_to_lab(np.array([119.0, 119.0, 119.0]))[0])
check("[2] the grey is L* 50", abs(base_l - 50.0) < 0.3, base_l)
check("[2] groove pixels 19, 20 at L* 34, 18 / 21 not", all(abs(L(30, x) - 34.0) < 0.6 for x in (19, 20))
      and all(abs(L(30, x) - 50.0) < 0.3 for x in (18, 21)),
      [round(L(30, x), 2) for x in (18, 19, 20, 21, 22)])
check("[2] stitches x 13 / 27 at L* 38", abs(L(30, 13) - 38.0) < 0.6 and abs(L(30, 27) - 38.0) < 0.6,
      (round(L(30, 13), 2), round(L(30, 27), 2)))
check("[2] x 16 unchanged", (out[30, 16] == 119).all())
check("[2] nothing outside A changes", (out[:, 30:] == 119).all())
check("[2] centre_back / island B not painted", (out[:, 5] == 119).all() and (out[:, 10] == 119).all())
check("[2] info names the seams of A", info["seams"] == ["seam_front_0", "seam_front_1"], info)

for rgb, want in (((150, 80, 80), -16.0), ((30, 30, 30), 16.0)):
    at = np.zeros((60, 60, 3), np.uint8)
    at[:] = rgb
    o2, _i = ctp.draw_seams(at, {"A": mask_a}, {"seam_front_0": marks["seam_front_0"]}, px_per_cm=20.0)
    l0 = float(ctp.srgb_to_lab(np.array(rgb, np.float64))[0])
    l1 = float(ctp.srgb_to_lab(o2[30, 20].astype(np.float64))[0])
    check(f"[2] fabric L* {l0:.1f}: the groove moves {want:+.0f}", abs((l1 - l0) - want) < 0.8, round(l1 - l0, 2))

# [3]
corset = gt.validate_params({"kind": "top", "shoulders": "strapless", "neckline": "sweetheart", "fit": 0.0})[0]
laced = {**corset, "placket": "lacing", "buttons": 3}
skirt = gt.validate_params({"kind": "skirt"})[0]
_items = {"c": {"template": corset}, "l": {"template": laced}, "s": {"template": skirt}}
from app.models import inventory as _inv  # noqa: E402
_orig = (_inv.get_item, gt.params_of)
_inv.get_item = lambda i: _items.get(i)
gt.params_of = lambda it: (it or {}).get("template")
_orig_po = gct.placket_of
try:
    gct.placket_of = lambda i: ("none", 0, "top", "none") if i != "l" else ("lacing", 0, "top", "none")
    check("[3] corset without placket -> :seams3", gct.placket_key("c") == ":seams3", gct.placket_key("c"))
    check("[3] laced corset", gct.placket_key("l") == f":placket{ctp.PLACKET_VERSION}-lacing-0:seams3",
          gct.placket_key("l"))
    check("[3] a skirt -> ''", gct.placket_key("s") == "", gct.placket_key("s"))
finally:
    _inv.get_item, gt.params_of = _orig
    gct.placket_of = _orig_po

print(f"\n{len(FAILS)} FAILED: {FAILS}" if FAILS else "\nALL OK")
sys.exit(1 if FAILS else 0)
