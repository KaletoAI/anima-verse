#!/usr/bin/env python3
"""Smoke: texture from cut, stage "details" (2026-11-23) — the back prompt names a striped front's stripes, a back
striped along the same axis gets the stripe level limit, the painted buttons take the item's colour, and an invented
texture field round a decorated front's motif becomes the plain fabric.

Usage:
    ./.venv/bin/python scripts/smoke_cut_texture_details.py

No server, no world DB (a throwaway ``paths.init``), no Blender, no hub job. Every expectation is derived by hand:

[1] ``weave_axis`` / ``stripe_words``. sRGB grey 110 / 130 give L* 46.435 / 54.368 (see
    ``smoke_cut_texture_detail_gates.py`` [1]): 2-px rows of them are hp = +-3.966, level 3.966, grain 0.0. Rows are
    constant along x, so np.gradient gives gx = 0, the mean tensor is diag(0, syy): (major - minor) / (major + minor)
    = 1 -> coherence 1.0, the gradient's angle 0.5 atan2(0, -syy) = 90 deg (along y), the LINES run across it: 90 deg
    from the vertical = horizontal -> "fine horizontal stripes". The same picture transposed: gy = 0, gradient angle 0,
    lines at 0 deg -> "fine vertical stripes". The 2-px checker: gx^2 = gy^2 everywhere, gx gy averages to 0 (it is a
    period-2 checker of signs) -> coherence 0 -> "fine weave" (and its grain 3.966 = its level fails the share
    0.22 first). Faint rows 118 / 122 (L* 49.6 / 51.2, d = 0.8 < ``min_level`` 1.5) -> "fine weave". Diagonal lines
    (45 deg) -> "fine weave". No levels (an old record) -> "fine weave".
[2] ``weave_gates`` with axes. Dario's linen front 3.198 / 0.538 (coherence 0.96, 0.6 deg: vertical stripes). The
    stripe limit 3.0 x 3.198 + 1.0 = 10.594: the P-H3 back of the A/B, 7.471 / 0.959 (coherence 0.967, 0 deg), passes
    the weave (1.25 x would be 4.998: rejected) and the grain (1.25 x 0.538 + 0.5 = 1.1725); the MiniMax candy stripes
    17.155 / 0.681 fail the weave at 10.594. A speckled back (5.347 / 3.471, coherence 0.03) is not striped: the
    limit stays 4.998, rejected. A back without an axis keeps 1.25 x as well.
[3] The back prompt: with the default weave words every dialect renders byte for byte what the template of 4ee6ac1ab
    renders (written from ``git show 4ee6ac1ab:shared/templates/image/garment_cut_texture_back.md``); with "fine
    vertical stripes" the P-H3 prompt reads "Add only the fine vertical stripes of the fabric" and the MiniMax one
    "its colour and fine vertical stripes,".
[4] Buttons. ``button_text_colour``: "black tailored blazer, fitted, two silver buttons" -> silver (184, 184, 190);
    "dark green linen shirt with nordic silver embroidery, loose fit" names no button -> None (the silver belongs to
    the embroidery's segment); "shirt with brown wooden buttons" -> the first word, brown (104, 66, 38).
    ``picture_buttons`` on a 512 px picture (scale 1): a green garment (40, 100, 60) x 100..399 (width 300), five
    copper discs (140, 70, 20) of radius 6.5 centred on x 250.5 (pixels 244..256, d 13 px in 3.6..18 = 0.012..0.06 x
    300, fill ~0.79), two discs at x 150.5 and 330.5, a white stroke 2 x 40 px (aspect 20 > 1.6). The biggest column
    within 0.04 x 300 = 12 px is the five at 250.5 -> count 5, x 250.5 / 512 = 0.489, the eroded discs' median
    (140, 70, 20) exactly. Without the five (only 2 in any column < ``min_count`` 3) -> None.
    ``button_colours`` with an rgb: the disc IS that rgb, the rim 15 L* darker (L* >= 30) or lighter (L* < 30).
    ``button_rgb`` (``get_item`` / ``_item_path`` stubbed, the cut directory under the throwaway storage): a text
    without buttons and the cut's ``<stem>.item.png`` = the five-disc picture -> (140, 70, 20) "picture"; with the
    raw item picture the two-disc one and no stem file -> None; the text "two silver buttons" wins over both.
[5] ``busy_halo`` at 20 px/cm on a 400 px square panel of flat green (40, 100, 60): the energy of a flat panel is 0,
    the quiet level 0, the limit the floor 2.0; the panel is eroded by ``edge_cm`` 0.9 cm = 18 px. A field of 3 x 3 px dark dots (10, 40, 20) every 6 px, 120 x 120 px
    (6 x 6 cm, at x/y 240..359): a dot share p = 9 / 36 = 0.25 of a step dL ~ 24, rms sqrt(p (1 - p)) x 24 ~ 10 > 2
    inside it; each dot is 0.15 cm < ``deco_cm`` 1 cm, never decoration. A white stroke 4 x 200 px (10 cm, dE > 30,
    long >= 1 cm: decoration) at x 60..63. Expected: busy covers >= 0.8 of the field eroded by the energy Gaussian
    (15 px), nothing farther than 30 px outside the field, nothing within ``near_cm`` 0.6 cm = 12 px of the stroke.
    The panel with the stroke alone: nothing busy. The panel ALL dotted: its quiet level is the field's -> nothing
    busy.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core import paths  # noqa: E402

paths.init(tempfile.mkdtemp(prefix="smoke_cut_details_"))

from app.core import cut_texture_post as post  # noqa: E402
from app.core import garment_cut_texture as gct  # noqa: E402

FAIL: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'OK  ' if ok else 'FAIL'} {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        FAIL.append(label)


print("[1] weave_axis / stripe_words")
mask = np.zeros((140, 140), bool)
mask[20:120, 20:120] = True
u = np.where((np.arange(140) // 2) % 2 == 0, 1, -1)
rows = np.repeat(np.where(u > 0, 110, 130).astype(np.uint8)[:, None], 140, axis=1)
rows = np.repeat(rows[..., None], 3, axis=2)
cols = np.ascontiguousarray(rows.transpose(1, 0, 2))
checker = np.repeat(np.where((u[:, None] * u[None, :]) > 0, 110, 130).astype(np.uint8)[..., None], 3, axis=2)
for name, img, want_words, want_angle in (("rows", rows, "fine horizontal stripes", 90.0),
                                          ("columns", cols, "fine vertical stripes", 0.0)):
    lv, ax = post.weave_levels(img, mask, 10.0), post.weave_axis(img, mask, 10.0)
    check(f"{name}: coherence 1, lines at {want_angle:.0f} deg", ax is not None and ax["coherence"] > 0.999
          and abs(ax["angle"] - want_angle) < 0.5, f"{ax}")
    check(f"{name}: {want_words!r}", post.stripe_words(lv, ax) == want_words, post.stripe_words(lv, ax))
lv, ax = post.weave_levels(checker, mask, 10.0), post.weave_axis(checker, mask, 10.0)
check("checker: coherence ~0", ax is not None and ax["coherence"] < 0.05, f"{ax}")
check("checker: 'fine weave'", post.stripe_words(lv, ax) == "fine weave")
faint = np.repeat(np.repeat(np.where(u > 0, 118, 122).astype(np.uint8)[:, None], 140, axis=1)[..., None], 3, axis=2)
lv = post.weave_levels(faint, mask, 10.0)
check("faint rows: level < 1.5 -> 'fine weave'", lv["level"] < 1.5
      and post.stripe_words(lv, post.weave_axis(faint, mask, 10.0)) == "fine weave", f"{lv}")
yy, xx = np.mgrid[0:140, 0:140]
diag = np.repeat(np.where(((xx + yy) // 2) % 2 == 0, 110, 130).astype(np.uint8)[..., None], 3, axis=2)
ax = post.weave_axis(diag, mask, 10.0)
check("diagonal lines: 45 deg -> 'fine weave'", abs(ax["angle"] - 45.0) < 1.0
      and post.stripe_words(post.weave_levels(diag, mask, 10.0), ax) == "fine weave", f"{ax}")
check("no levels -> 'fine weave'", post.stripe_words(None, None) == "fine weave")

print("[2] weave_gates with axes")
front = {"level": 3.198, "grain": 0.538, "axis": {"coherence": 0.96, "angle": 0.6}}


def gates(back):
    return {g["gate"]: g for g in post.weave_gates(back, front)}


g = gates({"level": 7.471, "grain": 0.959, "axis": {"coherence": 0.967, "angle": 0.0}})
check("P-H3 striped back passes at the stripe limit 10.594", g["weave"]["ok"] and g["weave"]["striped"]
      and abs(g["weave"]["limit"] - 10.594) < 1e-3 and g["grain"]["ok"], f"{g}")
g = gates({"level": 17.155, "grain": 0.681, "axis": {"coherence": 0.998, "angle": 0.0}})
check("MiniMax candy stripes rejected (17.155 > 10.594)", not g["weave"]["ok"], f"{g['weave']}")
g = gates({"level": 5.347, "grain": 3.471, "axis": {"coherence": 0.03, "angle": 50.0}})
check("speckled back: not striped, limit 4.998, rejected", not g["weave"]["striped"]
      and abs(g["weave"]["limit"] - 4.998) < 1e-3 and not g["weave"]["ok"] and not g["grain"]["ok"], f"{g}")
g = gates({"level": 7.471, "grain": 0.959})
check("a back without an axis keeps 1.25 x", abs(g["weave"]["limit"] - 4.998) < 1e-3 and not g["weave"]["ok"])

print("[3] the back prompt")
old = subprocess.run(["git", "-C", str(ROOT), "show", "4ee6ac1ab:shared/templates/image/garment_cut_texture_back.md"],
                     capture_output=True, text=True, check=True).stdout
tmp_old = Path(tempfile.mkdtemp(prefix="smoke_cut_details_old_")) / "garment_cut_texture_back.md"
tmp_old.write_text(old, encoding="utf-8")
real = gct.PROMPT_SETS["top"]["back"]
dialects = ("picture_edit", "picture_subject", "image_tag", "ordinal")
new_default = {d: gct.render_prompt(piece="elbow-sleeve shirt", side="back", dialect=d) for d in dialects}
gct.PROMPT_SETS["top"]["back"] = tmp_old
try:
    old_render = {d: gct.render_prompt(piece="elbow-sleeve shirt", side="back", dialect=d) for d in dialects}
finally:
    gct.PROMPT_SETS["top"]["back"] = real
for d in dialects:
    check(f"{d}: the default renders as at 4ee6ac1ab", new_default[d] == old_render[d])
st = gct.edit_prompt(piece="elbow-sleeve shirt", side="back", weave="fine vertical stripes")
check("P-H3: 'Add only the fine vertical stripes of the fabric'",
      "Add only the fine vertical stripes of the fabric" in st.render("picture_edit"))
check("MiniMax: 'its colour and fine vertical stripes,'",
      "its colour and fine vertical stripes," in st.render("picture_subject"))

print("[4] buttons")
check("text: silver buttons", gct.button_text_colour("black tailored blazer, fitted, two silver buttons")
      == (184, 184, 190))
check("text: silver embroidery is no button colour",
      gct.button_text_colour("dark green linen shirt with nordic silver embroidery, loose fit") is None)
check("text: brown wooden buttons -> brown", gct.button_text_colour("shirt with brown wooden buttons") == (104, 66, 38))


def disc(img, cx, cy, r, rgb):
    m = (xx5 + 0.5 - cx) ** 2 + (yy5 + 0.5 - cy) ** 2 <= r * r
    img[m] = rgb


yy5, xx5 = np.mgrid[0:512, 0:512]
pic = np.full((512, 512, 3), 255, np.uint8)
pic[60:460, 100:400] = (40, 100, 60)
for cy in (150.5, 200.5, 250.5, 300.5, 350.5):
    disc(pic, 250.5, cy, 6.5, (140, 70, 20))
disc(pic, 150.5, 200.5, 6.5, (140, 70, 20))
disc(pic, 330.5, 300.5, 6.5, (140, 70, 20))
pic[300:340, 170:172] = (240, 240, 240)
found = post.picture_buttons(pic)
check("five copper discs in one column", found is not None and found["count"] == 5
      and abs(found["x"] - 0.489) < 0.003 and found["rgb"] == [140, 70, 20], f"{found}")
pic2 = np.full((512, 512, 3), 255, np.uint8)
pic2[60:460, 100:400] = (40, 100, 60)
disc(pic2, 150.5, 200.5, 6.5, (140, 70, 20))
disc(pic2, 330.5, 300.5, 6.5, (140, 70, 20))
check("two lone discs: no buttons", post.picture_buttons(pic2) is None)
col = post.button_colours([40.0, -30.0, 20.0], [140, 70, 20])
check("own colour: the disc is the rgb, the rim 15 L* darker", list(col["disc"]) == [140, 70, 20]
      and abs(col["disc_l"] - col["rim_l"] - 15.0) < 0.6, f"{col['disc_l']:.2f} / {col['rim_l']:.2f}")
col = post.button_colours([40.0, -30.0, 20.0], [20, 20, 24])
check("a dark own colour: the rim 15 L* lighter", abs(col["rim_l"] - col["disc_l"] - 15.0) < 0.6)

from app.models import inventory  # noqa: E402
from PIL import Image  # noqa: E402

texts = {"it": "dark green linen shirt with nordic silver embroidery"}
raw_pic = Path(tempfile.mkdtemp(prefix="smoke_cut_details_item_")) / "raw.png"
Image.fromarray(pic2).save(raw_pic)
inventory.get_item = lambda iid: {"prompt_fragment": texts[iid]}
gct._item_path = lambda iid: raw_pic
stem_png = gct._file(gct._stem("Smoke", "it", "0123456789ab"), ".item.png")
stem_png.parent.mkdir(parents=True, exist_ok=True)
check("no stem picture: the raw picture's two discs -> None", gct.button_rgb("it", "Smoke", "0123456789ab")
      == (None, ""))
Image.fromarray(pic).save(stem_png)
check("the cut's own picture: copper from the picture", gct.button_rgb("it", "Smoke", "0123456789ab")
      == ([140, 70, 20], "picture"), f"{gct.button_rgb('it', 'Smoke', '0123456789ab')}")
texts["it"] = "black tailored blazer, fitted, two silver buttons"
check("the text wins", gct.button_rgb("it", "Smoke", "0123456789ab") == ([184, 184, 190], "text"))

print("[5] busy_halo")
size = 440
panel = np.zeros((size, size), bool)
panel[20:420, 20:420] = True
base_rgb = np.array([40, 100, 60], np.uint8)
base_lab = post.srgb_to_lab(base_rgb.astype(np.float64))
flat = np.full((size, size, 3), 255, np.uint8)
flat[panel] = base_rgb
stroke = flat.copy()
stroke[120:320, 60:64] = (236, 234, 230)
dots = stroke.copy()
field = np.zeros((size, size), bool)
field[240:360, 240:360] = True
dotmask = field & ((yy5[:size, :size] % 6) < 3) & ((xx5[:size, :size] % 6) < 3)
dots[dotmask] = (10, 40, 20)
busy, info = post.busy_halo(dots, panel, base_lab, 20.0)
from scipy import ndimage  # noqa: E402
inner = ndimage.binary_erosion(field, iterations=15)
outer = ndimage.binary_dilation(field, iterations=30)
near = ndimage.distance_transform_edt(~((stroke != flat).any(-1))) < 12
check("the dot field is busy (>= 0.8 of its inner part)", (busy & inner).sum() >= 0.8 * inner.sum(),
      f"{(busy & inner).sum()} / {inner.sum()} {info}")
check("nothing busy beyond 30 px of the field", not (busy & ~outer).any(), f"{(busy & ~outer).sum()}")
check("nothing busy within 0.6 cm of the stroke", not (busy & near).any())
check("the limit is the floor 2.0 on a flat panel", abs(info["limit"] - 2.0) < 1e-6 and info["quiet"] < 0.1, f"{info}")
busy2, info2 = post.busy_halo(stroke, panel, base_lab, 20.0)
check("stroke alone: nothing busy", not busy2.any(), f"{info2}")
alldots = flat.copy()
alldots[panel & ((yy5[:size, :size] % 6) < 3) & ((xx5[:size, :size] % 6) < 3)] = (10, 40, 20)
busy3, info3 = post.busy_halo(alldots, panel, base_lab, 20.0)
check("all-over dots: nothing busy against itself", busy3.sum() < 0.01 * panel.sum(), f"{busy3.sum()} {info3}")

print("FAILED: " + ", ".join(FAIL) if FAIL else "ALL OK")
sys.exit(1 if FAIL else 0)
