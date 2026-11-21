"""Smoke: texture from cut — the pre-fill colour, the answer gates and the sleeve fabric fill (user test 2026-11-21).

Usage:
    ./.venv/bin/python scripts/smoke_cut_texture_fabric.py
    CUT_REAL_DIR=<dir> ./.venv/bin/python scripts/smoke_cut_texture_fabric.py   # + the real pictures, see [R]

No server, no world DB, no hub job, no BiRefNet (the key matte). ``app/core/cut_texture_post.py`` (``fabric_colour``,
``delta_e00``, ``detail_density``, ``answer_gates``, ``fabric_patch`` / ``mirror_tile`` / ``tile_fill``) and
``app/core/garment_cut_texture.py`` (``prefill_colour``, ``render_template(fill=…)``, ``layout_words``, the prompts,
``fill_fabric``, ``_post_job``). Every expectation is derived by hand below.

[1] ``fabric_colour`` on synthetic pictures (white background, the garment a 300 x 400 block in a 400 x 500 picture):
    a) uniform (30, 90, 173): every pixel has the same L*a*b* -> the median is that colour -> back to sRGB (30, 90,
       173) +-1 (rounding of the Lab round trip).
    b) the same blue with a magenta (136, 25, 75) print block over the upper 40 % of the garment's width x 40 % of its
       height (16 % of its area): magenta's a*b* (~48, ~-1) lies ~60 from blue's (~12, ~-50) — far outside the
       12-unit radius — and the blue ground is the larger histogram peak -> still (30, 90, 173) +-1.
    c) dark green (19, 50, 29) with thin white "embroidery" lines (2 px every 12 px over the right third): the lines
       and every pixel within r of them are DETAIL (|L - local mean| > 6), the rest is plain green -> (19, 50, 29)
       +-1, and ``plain`` < 1 (the lines took a share).
    d) an empty mask -> None.
[2] ``delta_e00`` against the published CIEDE2000 test data (Sharma, Wu, Dalal 2005, table 1), +-1e-4:
    pair 1 (50, 2.6772, -79.7751) / (50, 0, -82.7485) = 2.0425; pair 7 (50, 0, 0) / (50, -1, 2) = 2.3669;
    pair 21 (50, 2.5, 0) / (73, 25, -18) = 27.1492. And by hand: two colours that differ only in L* (18 vs 28, a* b*
    the same): dE00 = dL / S_L, S_L = 1 + 0.015 (Lm - 50)^2 / sqrt(20 + (Lm - 50)^2) with Lm 23 -> (Lm-50)^2 = 729,
    sqrt(749) = 27.368 -> S_L = 1.39955 -> 10 / 1.39955 = 7.1452 (the "flat studio light lifts a dark fabric" case:
    well under the gate's 20).
[3] ``detail_density``: a uniform panel -> 0.0. A 256 x 256 panel black on the left half, white on the right: box-down
    2:1 -> 128 px, the step between columns 63 | 64; Gaussian sigma 1 then ``np.gradient`` (central differences) at a
    column centre c (distance from the step): 50 * (Phi(c + 1) - Phi(c - 1)) L*/px — c = 0.5: 50 * (Phi(1.5) -
    Phi(-0.5)) = 50 * (0.93319 - 0.30854) = 31.2; c = 1.5: 50 * (Phi(2.5) - Phi(0.5)) = 15.1; c = 2.5: 50 * (Phi(3.5) -
    Phi(1.5)) = 3.33 < 4 -> 4 edge columns (62..65); the eroded mask (4 px = round(0.03 * 128)) is 120 x 120 -> 4 *
    120 / 14 400 = 0.0333 (+-0.001).
    ``detail_limit``: 3 x reference + 0.04 (factor 3 since 2026-11-21) -> 0.0154 (Kai's item) -> 0.0862, 0.0976
    (Dario's) -> 0.3328, None -> None.
[4] ``answer_gates`` on a 200 x 200 panel against a blue item colour (30, 90, 173) and a reference detail 0.0:
    the panel in the item's blue -> colour ok (dE00 <= 1), detail 0.0 <= 0.04 ok; in red (181, 22, 30) -> colour fails
    (dE00 > 20, the text "colour ΔE00 …"); blue with a 4 px black/white stripe print over its whole area -> the detail
    gate fails ("invented content: detail …"), the colour (the blue ground in the gaps) stays ok... the stripes cover
    every pixel, so the colour is measured on the stripes' own a*b* peak: only the detail gate is asserted.
[5] Pre-fill: ``prefill_colour`` keeps (30, 90, 173) (its largest distance from white, 225, is >= 40); (250, 250,
    250) has distance 5 -> scaled to 40: 255 - 5 * 8 = 215 -> (215, 215, 215); (240, 245, 250) distance 15 -> factor
    40/15: 255 - 15 * 2.667 = 215, 255 - 10 * 2.667 = 228.3 -> 228, 255 - 5 * 2.667 = 241.7 -> 242. None -> None.
    ``render_template(fill=(30, 90, 173))`` of a 100 x 200 rectangle island: the centre is the fill, the non-white
    pixels are exactly the island mask (20 000), the outline (mask minus the 2 px erosion: 1 184 px) is the fill x 0.6
    (blue L* 39 >= 30): (18, 54, 103.8 -> 104). A dark fabric (19, 50, 29) (L* 18 < 30) gets an outline 0.4 of the way
    to white: 19 + 236 * 0.4 = 113.4 -> 113, 50 + 205 * 0.4 = 132, 29 + 226 * 0.4 = 119.4 -> 119.
[6] ``layout_words`` of a front job in a 1000 px atlas: front bbox (20, 20, 500, 450) -> centre (0.26, 0.235): "the
    large piece at the top left is the front panel"; sleeve_l (20, 700, 450, 950) -> (0.235, 0.825): "the piece at
    the bottom left is the left sleeve"; sleeve_r (550, 700, 980, 950) -> (0.765, 0.825): "the piece at the bottom
    right is the right sleeve"; band (200, 970, 800, 990) -> 600 / 20 = 30 >= 6 -> a strip, centre (0.5, 0.98) >
    0.9: "the long thin strip at the very bottom is the neckband". The front prompt rendered with them contains
    "In the first image, " + the four joined with "; ", the sleeve sentence "The left sleeve and right sleeve get
    only the plain fabric", "already filled with the plain fabric colour", "Do not invent text"; the back prompt with
    the back panel only has no sleeve sentence; ``prompt_compose.compose`` keeps both byte-identical (no negation
    moved, no warning).
[7] ``mirror_tile`` of a 3 x 3 patch over 12 x 12: period 6 in both directions; columns 3..5 are the patch mirrored
    left-right, rows 3..5 mirrored up-down; the seam is continuous (tile[:, 2] == tile[:, 3]: a pixel meets its own
    mirror). ``tile_fill`` of a uniform (100, 100, 100) patch onto target Lab of (19, 50, 29): the region becomes
    (19, 50, 29) +-1, outside unchanged.
    ``fabric_patch`` on a 200 x 200 panel at 5 px/cm (patch 8 cm = 40 px): the left half uniform green, the right half
    white 2 px stripes -> the window lies in the left half (x + 40 <= 100) with energy 0.0.
[8] ``fill_fabric`` / ``_post_job`` on a two-island payload (atlas 400 px, 10 px/cm): front (20..200 x 20..200) and
    sleeve_l (220..380 x 20..200). The answer: both islands dark green (19, 50, 29), the front with light grey (200)
    stripes (not near-white: 55 > ``WHITE_TOL`` 24, so they count as covered) in its right third, the sleeve with the same stripes all over (the embroidery painted onto the sleeve). Refs: colour =
    the green, detail 0.2 (limit 0.84: the embroidery is in the item too).
    - ``_post_job(sleeve_print="plain")``: ready; the sleeve's detail after the fill is 0.0 (before > 0.1) and its
      colour within dE76 3 of the front's base; the front keeps its stripes (detail > 0.05); ``fabric_fill.islands``
      ["sleeve_l"].
    - ``sleeve_print="picture"``: nothing filled (``islands`` []), the sleeve keeps its stripes (detail > 0.05).
    - Refs detail 0.0 (a plain item): the same answer is rejected by the detail gate; ``force=True`` posts it and marks
      it ``accepted``.
    - Refs colour blue (30, 90, 173): rejected "colour ΔE00 …".
[R] With ``CUT_REAL_DIR`` (the offline validation copies — never the live world): ``kai_item.png`` -> blue (b* < -30,
    B > R and B > G), ``dario_item.png`` -> dark green (L* < 30, a* < -5, G > R and G > B); the answers
    ``kai_adc0d92f.png`` and ``kai_dd179c81.png`` with ``kai.islands.json`` are rejected by the colour gate;
    ``dario_raw_front.png`` with ``dario.islands.json`` passes, and its right sleeve carries no detail after the fill
    (before > 0.1). Skipped (and said) without the directory.
"""
import io
import json
import os
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_tmp = tempfile.mkdtemp(prefix="smoke_cut_fabric_")
os.environ.setdefault("STORAGE_DIR", os.path.join(_tmp, "world"))
os.environ.setdefault("INSTANCE_DIR", os.path.join(_tmp, "instance"))

from app.core import cut_texture_post as post  # noqa: E402
from app.core import garment_cut_texture as gct  # noqa: E402

FAILS = []


def check(label, ok, detail=""):
    print(f"{'OK  ' if ok else 'FAIL'} {label}" + (f"  ({detail})" if detail != "" else ""))
    if not ok:
        FAILS.append(label)


def near(rgb, want, tol=1):
    return rgb is not None and max(abs(int(a) - int(b)) for a, b in zip(rgb, want)) <= tol


def picture(colour, size=(400, 500), box=(50, 50, 350, 450)):
    img = np.full((size[1], size[0], 3), 255, np.uint8)
    x0, y0, x1, y1 = box
    img[y0:y1, x0:x1] = colour
    mask = np.zeros(img.shape[:2], bool)
    mask[y0:y1, x0:x1] = True
    return img, mask


# [1] fabric_colour
img, m = picture((30, 90, 173))
fa = post.fabric_colour(img, m)
check("[1a] uniform blue -> (30, 90, 173) +-1", near(fa["rgb"], (30, 90, 173)), fa)
img_b = img.copy()
img_b[50:210, 50:170] = (136, 25, 75)          # 40 % of 400 high x 40 % of 300 wide = 16 % of the garment
fb = post.fabric_colour(img_b, m)
check("[1b] blue with a magenta print block -> still (30, 90, 173) +-1", near(fb["rgb"], (30, 90, 173)), fb)
img_c, m_c = picture((19, 50, 29))
for x in range(250, 350, 12):
    img_c[60:440, x:x + 2] = (235, 235, 235)
fc = post.fabric_colour(img_c, m_c)
check("[1c] dark green with white embroidery lines -> (19, 50, 29) +-1, plain < 1",
      near(fc["rgb"], (19, 50, 29)) and fc["plain"] < 1.0, fc)
check("[1d] empty mask -> None", post.fabric_colour(img, np.zeros_like(m)) is None)

# [2] CIEDE2000
for label, l1, l2, want in (("pair 1", (50, 2.6772, -79.7751), (50, 0, -82.7485), 2.0425),
                            ("pair 7", (50, 0, 0), (50, -1, 2), 2.3669),
                            ("pair 21", (50, 2.5, 0), (73, 25, -18), 27.1492),
                            ("L* only 18 vs 28", (18, -17, 10), (28, -17, 10), 7.1452)):
    got = post.delta_e00(l1, l2)
    check(f"[2] dE00 {label} = {want}", abs(got - want) <= 1e-4, round(got, 5))

# [3] detail density
check("[3] a uniform panel -> 0.0", post.detail_density(img, m) == 0.0, post.detail_density(img, m))
step = np.zeros((256, 256, 3), np.uint8)
step[:, 128:] = 255
dd = post.detail_density(step, np.ones((256, 256), bool))
check("[3] a black | white step -> 4 x 120 / 14 400 = 0.0333", dd is not None and abs(dd - 4 * 120 / 14400) <= 0.001,
      dd)
check("[3] detail_limit 0.0154 -> 0.0862, 0.0976 -> 0.3328, None -> None",
      post.detail_limit(0.0154) == 0.0862 and post.detail_limit(0.0976) == 0.3328 and post.detail_limit(None) is None,
      (post.detail_limit(0.0154), post.detail_limit(0.0976)))

# [4] answer gates
blue = post.fabric_colour(*picture((30, 90, 173)))
panel = np.zeros((200, 200), bool)
panel[10:190, 10:190] = True


def panel_img(colour):
    a = np.full((200, 200, 3), 255, np.uint8)
    a[panel] = colour
    return a


g_ok, _ = post.answer_gates(panel_img((30, 90, 173)), panel, blue, 0.0)
check("[4] the item's blue: both gates pass", [g["ok"] for g in g_ok] == [True, True]
      and g_ok[0]["value"] <= 1.0, g_ok)
g_red, info_red = post.answer_gates(panel_img((181, 22, 30)), panel, blue, 0.0)
check("[4] red: the colour gate fails (> 20) with its text", g_red[0]["gate"] == "colour" and not g_red[0]["ok"]
      and g_red[0]["value"] > 20 and g_red[0]["text"].startswith("colour ΔE00"), g_red)
striped = panel_img((30, 90, 173))
for y in range(10, 190, 8):
    striped[y:y + 4, 10:190] = (0, 0, 0)
g_pr, _ = post.answer_gates(striped, panel, blue, 0.0)
gd = next(g for g in g_pr if g["gate"] == "detail")
check("[4] a stripe print on a plain item: the detail gate fails", not gd["ok"]
      and gd["text"].startswith("invented content: detail"), gd)

# [5] pre-fill
check("[5] prefill keeps a coloured fabric", gct.prefill_colour({"rgb": [30, 90, 173]}) == (30, 90, 173))
check("[5] near-white (250, 250, 250) -> (215, 215, 215)", gct.prefill_colour({"rgb": [250, 250, 250]})
      == (215, 215, 215), gct.prefill_colour({"rgb": [250, 250, 250]}))
check("[5] (240, 245, 250) -> (215, 228, 242)", gct.prefill_colour({"rgb": [240, 245, 250]}) == (215, 228, 242),
      gct.prefill_colour({"rgb": [240, 245, 250]}))
check("[5] None -> None", gct.prefill_colour(None) is None)
rect = {"name": "front", "verts_px": [[20, 20], [120, 20], [120, 220], [20, 220]], "tris": [[0, 1, 2], [0, 2, 3]],
        "bbox_px": [20, 20, 120, 220]}
pl1 = {"atlas_px": 256, "px_per_cm": 10.0, "islands": [rect], "seams": []}
t5 = np.asarray(gct.render_template(pl1, fill=(30, 90, 173)))
nw = ~np.all(t5 == 255, axis=-1)
line = np.all(t5 == np.array(gct.outline_for((30, 90, 173)), np.uint8), axis=-1)
check("[5] pre-filled template: centre = fill, non-white = mask (20 000), outline 1 184 px of (18, 54, 104)",
      tuple(t5[120, 70]) == (30, 90, 173) and int(nw.sum()) == 20000 and int(line.sum()) == 1184
      and gct.outline_for((30, 90, 173)) == (18, 54, 104), (tuple(t5[120, 70]), int(nw.sum()), int(line.sum())))
check("[5] a dark fabric (19, 50, 29), L* 18 < 30: the outline 0.4 of the way to white = (113, 132, 119)",
      gct.outline_for((19, 50, 29)) == (113, 132, 119), gct.outline_for((19, 50, 29)))

# [6] layout words + prompts
lay_pl = {"atlas_px": 1000, "islands": [
    {"name": "front", "bbox_px": [20, 20, 500, 450]}, {"name": "sleeve_l", "bbox_px": [20, 700, 450, 950]},
    {"name": "sleeve_r", "bbox_px": [550, 700, 980, 950]}, {"name": "band", "bbox_px": [200, 970, 800, 990]}]}
words = gct.layout_words(lay_pl)
want_words = ["the large piece at the top left is the front panel", "the piece at the bottom left is the left sleeve",
              "the piece at the bottom right is the right sleeve",
              "the long thin strip at the very bottom is the neckband"]
check("[6] layout words", words == want_words, words)
pf = gct.render_prompt(piece="T-shirt", pieces=gct.prompt_pieces(lay_pl), layout=words)
check("[6] front prompt: layout, sleeve rule, pre-fill, no invention",
      "In the first image, " + "; ".join(want_words) + "." in pf
      and "The left sleeve and right sleeve get only the plain fabric" in pf
      and "already filled with the plain fabric colour" in pf and "Do not invent text" in pf
      and "{{" not in pf and "{%" not in pf, pf)
pb = gct.render_prompt(piece="T-shirt", pieces=["back panel"], side="back",
                       layout=["the piece at the top right is the back panel"])
check("[6] back prompt: its layout, no sleeve sentence", "the piece at the top right is the back panel" in pb
      and "sleeve" not in pb and "Do not invent text" in pb, pb)
from types import SimpleNamespace  # noqa: E402

from app.core.prompt_compose import compose  # noqa: E402

for fam in ("natural", "keywords"):
    for label, text in (("front", pf), ("back", pb)):
        c = compose(use_case="garment_cut_texture", subject=text,
                    backend=SimpleNamespace(model="P-H3-Image", image_family=fam))
        check(f"[6] compose keeps the {label} prompt byte-identical ({fam})", c.prompt == text and c.negative == ""
              and not c.warnings, (c.negative, c.warnings))

# [7] tiling + patch
patch = np.arange(27, dtype=np.uint8).reshape(3, 3, 3)
tile = post.mirror_tile(patch, 12, 12)
check("[7] mirror tile: period 6, mirrored halves, continuous seam",
      np.array_equal(tile[:6], tile[6:]) and np.array_equal(tile[:, :6], tile[:, 6:])
      and np.array_equal(tile[:3, 3:6], patch[:, ::-1]) and np.array_equal(tile[3:6, :3], patch[::-1])
      and np.array_equal(tile[:, 2], tile[:, 3]))
canvas = np.full((50, 50, 3), 255, np.uint8)
reg = np.zeros((50, 50), bool)
reg[10:40, 10:40] = True
green_lab = post.srgb_to_lab(np.array([19, 50, 29], float))
filled, _ = post.tile_fill(canvas, reg, np.full((8, 8, 3), 100, np.uint8), green_lab)
check("[7] tile_fill moves the tile onto the target colour, outside unchanged",
      near(filled[25, 25], (19, 50, 29)) and tuple(filled[0, 0]) == (255, 255, 255), filled[25, 25].tolist())
pimg = np.full((200, 200, 3), 255, np.uint8)
pimg[:, :] = (19, 50, 29)
for x in range(100, 200, 4):
    pimg[:, x:x + 2] = (235, 235, 235)
found = post.fabric_patch(pimg, np.ones((200, 200), bool), 5.0, green_lab)
check("[7] the patch (40 px) comes from the plain left half, energy 0", found is not None and found[1]["px"] == 40
      and found[1]["xy"][0] + 40 <= 100 and found[1]["energy"] == 0.0, found and found[1])


# [8] fill_fabric / _post_job
def isl(name, x0, y0, x1, y1):
    return {"name": name, "verts_px": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]], "tris": [[0, 1, 2], [0, 2, 3]],
            "bbox_px": [x0, y0, x1, y1]}


pay = {"atlas_px": 400, "px_per_cm": 10.0, "islands": [isl("front", 20, 20, 200, 200),
                                                         isl("sleeve_l", 220, 20, 380, 200)], "seams": []}
labels = gct.rasterise_islands(pay, 400)
ids = gct.island_ids(pay)
ans = np.full((400, 400, 3), 255, np.uint8)
ans[labels > 0] = (19, 50, 29)
for x in range(140, 200, 8):
    ans[20:200, x:x + 2] = (200, 200, 200)
for x in range(220, 380, 8):
    ans[20:200, x:x + 2] = (200, 200, 200)
buf = io.BytesIO()
Image.fromarray(ans).save(buf, format="PNG")
answer = buf.getvalue()
green = post.fabric_colour(ans, labels == ids["front"])
fabric = ans[labels > 0].astype(float)      # the colour match's fabric = the answer's own colours: an identity move
refs = {"colour": green, "detail": {"front": 0.2}, "fabric": fabric}
sleeve = labels == ids["sleeve_l"]
before = post.detail_density(ans, sleeve)
r_plain = gct._post_job(answer, pay, 400, 10.0, "front", refs)
after = post.detail_density(r_plain["_image"], sleeve) if r_plain["state"] == "ready" else None
sl_col = post.fabric_colour(r_plain["_image"], sleeve) if r_plain["state"] == "ready" else None
de_sl = float(np.linalg.norm(np.array(sl_col["lab"]) - np.array(green["lab"]))) if sl_col else 99
check("[8] plain sleeves: ready, the sleeve's embroidery gone (detail 0.0, before > 0.1), its colour the front's",
      r_plain["state"] == "ready" and before > 0.1 and after == 0.0 and de_sl <= 3.0
      and r_plain["metrics"]["fabric_fill"]["islands"] == ["sleeve_l"], (r_plain["reason"], before, after, de_sl))
check("[8] the front keeps its embroidery", r_plain["state"] == "ready"
      and post.detail_density(r_plain["_image"], labels == ids["front"]) > 0.05)
r_pic = gct._post_job(answer, pay, 400, 10.0, "front", refs, sleeve_print="picture")
check("[8] sleeves from the picture: nothing filled, the sleeve keeps its stripes",
      r_pic["state"] == "ready" and r_pic["metrics"]["fabric_fill"]["islands"] == []
      and post.detail_density(r_pic["_image"], sleeve) > 0.05, r_pic["metrics"].get("fabric_fill"))
r_rej = gct._post_job(answer, pay, 400, 10.0, "front", {**refs, "detail": {"front": 0.0}})
check("[8] a plain item: the embroidered answer is rejected by the detail gate",
      r_rej["state"] == "rejected" and r_rej["reason"].startswith("invented content"), r_rej["reason"])
r_force = gct._post_job(answer, pay, 400, 10.0, "front", {**refs, "detail": {"front": 0.0}}, force=True)
check("[8] force (Use this answer): ready and accepted", r_force["state"] == "ready" and r_force["accepted"] is True)
r_col = gct._post_job(answer, pay, 400, 10.0, "front", {**refs, "colour": blue})
check("[8] a blue item: rejected by the colour gate", r_col["state"] == "rejected"
      and r_col["reason"].startswith("colour ΔE00"), r_col["reason"])

# [R] the real pictures (optional)
real = os.environ.get("CUT_REAL_DIR")
if not real or not Path(real).is_dir():
    print("SKIP [R] the real pictures (set CUT_REAL_DIR)")
else:
    R = Path(real)

    def item_ref(name):
        with Image.open(R / name) as im:
            return post.picture_reference(np.asarray(im.convert("RGBA")), matte=None)

    kai, dario = item_ref("kai_item.png"), item_ref("dario_item.png")
    kr, dr = kai["colour"], dario["colour"]
    check("[R] Kai's item is blue", kr["lab"][2] < -30 and kr["rgb"][2] > kr["rgb"][0] and kr["rgb"][2] > kr["rgb"][1],
          kr)
    check("[R] Dario's item is dark green", dr["lab"][0] < 30 and dr["lab"][1] < -5 and dr["rgb"][1] > dr["rgb"][0]
          and dr["rgb"][1] > dr["rgb"][2], dr)
    kpl = json.loads((R / "kai.islands.json").read_text())
    for name in ("kai_adc0d92f.png", "kai_dd179c81.png"):
        res = gct._post_job((R / name).read_bytes(), kpl, kpl["atlas_px"], kpl["px_per_cm"], "front",
                            {"colour": kr, "detail": {"front": kai["detail"]}, "fabric": kai["fabric"]})
        check(f"[R] {name} rejected by the colour gate", res["state"] == "rejected"
              and any(f.startswith("colour ΔE00") for f in res["metrics"]["failures"]), res["metrics"]["failures"])
    dpl = json.loads((R / "dario.islands.json").read_text())
    res = gct._post_job((R / "dario_raw_front.png").read_bytes(), dpl, dpl["atlas_px"], dpl["px_per_cm"], "front",
                        {"colour": dr, "detail": {"front": dario["detail"]}, "fabric": dario["fabric"]})
    dl_ = gct.rasterise_islands(dpl, dpl["atlas_px"])
    sr = dl_ == gct.island_ids(dpl)["sleeve_r"]
    with Image.open(R / "dario_raw_front.png") as im:
        raw_reg = post.resample_register(im, gct.job_labels(dpl, dpl["atlas_px"], "front") > 0)[0]
    check("[R] Dario's answer passes; its right sleeve's embroidery is gone after the fill",
          res["state"] == "ready" and post.detail_density(raw_reg, sr) > 0.1
          and post.detail_density(res["_image"], sr) <= 0.01, (res["reason"], post.detail_density(raw_reg, sr)))

print(f"\n{len(FAILS)} FAILED: {FAILS}" if FAILS else "\nALL OK")
sys.exit(1 if FAILS else 0)
