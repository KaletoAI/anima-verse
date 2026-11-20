"""Smoke: "texture from cut" — the clean island template and the debug pattern sheet (``app/core/garment_cut_texture.py``).

Usage:
    ./.venv/bin/python scripts/smoke_garment_cut_texture.py

No server, no world DB, no hub job: the render part is numpy + PIL on an ``islands.json`` payload. The synthetic
T-shirt payload of [2]/[3] is built through ``app/blender/scripts/uv_pattern.py`` (imported through ``sys.path`` the
way ``scripts/smoke_uv_pattern.py`` does; the core module itself never imports it). Every expectation is derived by
hand below.

[1] Raster: one axis-aligned 100 x 200 px rectangle island, corners on integer pixels (x 20..120, y 20..220) in a
    256 canvas, two fan triangles. A pixel (row i, column j) belongs to a triangle when its CENTRE (j + 0.5, i + 0.5)
    is inside; columns 20..119 (20 <= j + 0.5 < 120) and rows 20..219 -> the mask count is exactly 100 * 200 =
    20 000. The render: the centre pixel (row 120, column 70) is FILL, the canvas corner (0, 0) is white, the pixel
    just inside the left edge (row 120, column 20) is LINE; the outline is drawn INSIDE the mask (mask minus its
    2 px erosion), so the non-white count is exactly 20 000 and the LINE count is 20 000 - 96 * 196 = 1 184. The
    image is square (256 x 256), RGB.
    Half-open edges: a 10 x 10 square whose corners sit ON pixel centres ((0.5, 0.5) .. (10.5, 10.5)) covers
    exactly 10 * 10 = 100 pixels (top-left rule: the centres on its left and top edges are in, those on its right
    and bottom edges are out; its diagonal centres (i = j) are counted once): pixel (0, 0) in, (10, 10) out.
    Labels: islands "front" and "back" -> id = 1 + sorted name index: back = 1, front = 2; 0 = background.
[2] The render of the synthetic T-shirt payload (the five boxes of smoke_uv_pattern [7]: front 50 x 47, back
    50 x 45, sleeves 34 x 25, band 44 x 4 cm, margin 1.5 -> 19.59 px/cm; 4-connected regions) has exactly 5 connected
    non-white regions (the islands are >= 1.5 cm = 29 px apart) and 5 connected FILL regions (each island's FILL is
    its 2 px eroded interior, one rectangle; the band is 4 * 19.59 = 78 px high, so its interior survives).
[3] Debug pattern sheet (user request 2026-11-20): the same payload. 5 distinct pastel fill colours, each covering
    a large share of its island (>= 50 % of the island's mask pixels: text, arrow and outline take less). The front
    box's label text names "Front" and its bbox size: 50 * 19.59 = 979.5 px / 19.59 = 50.0 cm wide, 47 * 19.59 =
    920.73 px / 19.59 = 47.0 cm high (+-0.1). A sleeve label carries its cap height when the payload has one
    (sleeve_l -2.0 -> "cap -2.0 cm"). Seam letters: a payload with two seams gives letters A and B, each on both of
    its sides. The footer reads "19.59 px/cm · atlas 2048²". The sheet is never the model template: it differs
    from ``render_template`` of the same payload.
[4] Occasion + prompt file (plan Task 6): ``CUT_OCCASION`` / ``CUT_USE_CASE`` are "garment_cut_texture" and the
    occasion is in the catalog. ``prompt_pieces`` of the T-shirt payload (island names back, band, front, sleeve_l,
    sleeve_r) lists them in pattern order: front panel, back panel, left sleeve, right sleeve, neckband; a split part
    keeps its number ("front_2" -> "front panel 2"). The prompt renders for piece "T-shirt" and those pieces: it
    names "T-shirt", joins the pieces with ", ", carries "the first image" and "the second image" and no Jinja
    leftovers ("{{", "{#"). After ``prompt_adapters.reference_wording`` with model "p-h3-image" it contains
    "<Picture 1>" and "<Picture 2>" and no "first image"/"second image"; with "qwen-edit" it is byte-identical.
    ``PROMPT_SHA`` is the md5 of the shipped file text (32 hex).
[5] A missing variable raises (StrictUndefined): the template rendered with ``piece`` only raises
    ``jinja2.exceptions.UndefinedError``.
[6] ``prompt_compose.compose(use_case="garment_cut_texture", subject=<rendered>, backend=<model "P-H3-Image",
    image_family "natural">)``: the use case has empty style / negative / instruction for both families, so the
    prompt is the rendered text byte-identical, the negative is "" and there are no warnings (the prompt opens no
    sentence or clause with "no"/"without" — the negation guard moves nothing — and has no mid-sentence "no").
    Same for image_family "keywords".
"""
import os
import re
import sys
import tempfile
from collections import deque
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(1, str(ROOT / "app" / "blender" / "scripts"))
_tmp = tempfile.mkdtemp(prefix="smoke_cut_tex_")
os.environ.setdefault("STORAGE_DIR", os.path.join(_tmp, "world"))
os.environ.setdefault("INSTANCE_DIR", os.path.join(_tmp, "instance"))

import uv_pattern as up  # noqa: E402
from app.core import garment_cut_texture as gct  # noqa: E402

FAILS = []


def check(label, ok, detail=""):
    print(f"{'OK  ' if ok else 'FAIL'} {label}" + (f"  ({detail})" if detail != "" else ""))
    if not ok:
        FAILS.append(label)


def regions(mask):
    """4-connected component count of a boolean mask."""
    seen = np.zeros_like(mask, bool)
    h, w = mask.shape
    n = 0
    for i0, j0 in zip(*np.nonzero(mask)):
        if seen[i0, j0]:
            continue
        n += 1
        seen[i0, j0] = True
        q = deque([(i0, j0)])
        while q:
            i, j = q.popleft()
            for a, b in ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)):
                if 0 <= a < h and 0 <= b < w and mask[a, b] and not seen[a, b]:
                    seen[a, b] = True
                    q.append((a, b))
    return n


def rgb_eq(arr, colour):
    return np.all(arr == np.array(colour, np.uint8), axis=-1)


# [1] raster
rect = {"name": "front", "part": 1, "verts_px": [[20, 20], [120, 20], [120, 220], [20, 220]],
        "tris": [[0, 1, 2], [0, 2, 3]], "loops_px": [[[20, 20], [120, 20], [120, 220], [20, 220]]],
        "bbox_px": [20, 20, 120, 220]}
pl1 = {"version": 1, "atlas_px": 256, "px_per_cm": 10.0, "margin_cm": 1.5, "islands": [rect], "seams": []}
m1 = gct.island_mask(pl1, 256)
check("[1] mask count 20 000", int(m1.sum()) == 20000, int(m1.sum()))
img1 = gct.render_template(pl1)
a1 = np.asarray(img1)
check("[1] square RGB 256", img1.size == (256, 256) and img1.mode == "RGB", (img1.size, img1.mode))
check("[1] centre is FILL", tuple(a1[120, 70]) == gct.TEMPLATE_FILL, tuple(a1[120, 70]))
check("[1] corner is white", tuple(a1[0, 0]) == gct.BACKGROUND, tuple(a1[0, 0]))
check("[1] just inside the left edge is LINE", tuple(a1[120, 20]) == gct.TEMPLATE_LINE, tuple(a1[120, 20]))
nonwhite = int((~rgb_eq(a1, gct.BACKGROUND)).sum())
check("[1] non-white count 20 000 (outline inside the mask)", nonwhite == 20000, nonwhite)
nline = int(rgb_eq(a1, gct.TEMPLATE_LINE).sum())
check("[1] LINE count 1 184", nline == 20000 - 96 * 196, nline)
check("[1] only FILL, LINE, white", nonwhite == nline + int(rgb_eq(a1, gct.TEMPLATE_FILL).sum()))

sq = {"name": "front", "part": 1, "verts_px": [[0.5, 0.5], [10.5, 0.5], [10.5, 10.5], [0.5, 10.5]],
      "tris": [[0, 1, 2], [0, 2, 3]]}
msq = gct.island_mask({"atlas_px": 16, "islands": [sq]}, 16)
check("[1] half-open: 10 x 10 square on pixel centres covers 100", int(msq.sum()) == 100, int(msq.sum()))
check("[1] half-open: top-left in, bottom-right out", bool(msq[0, 0]) and not bool(msq[10, 10])
      and not bool(msq[0, 10]) and not bool(msq[10, 0]))
two = {"atlas_px": 64, "islands": [
    {"name": "front", "part": 1, "verts_px": [[2, 2], [20, 2], [20, 20], [2, 20]], "tris": [[0, 1, 2], [0, 2, 3]]},
    {"name": "back", "part": 2, "verts_px": [[30, 2], [50, 2], [50, 20], [30, 20]], "tris": [[0, 1, 2], [0, 2, 3]]}]}
lab = gct.rasterise_islands(two, 64)
check("[1] labels: uint8, back = 1, front = 2, background 0",
      lab.dtype == np.uint8 and lab[10, 40] == 1 and lab[10, 10] == 2 and lab[40, 40] == 0
      and set(np.unique(lab).tolist()) == {0, 1, 2}, np.unique(lab).tolist())
check("[1] label ids", gct.island_ids(two) == {"back": 1, "front": 2}, gct.island_ids(two))


# [2] synthetic T-shirt payload through uv_pattern
def tshirt_payload(caps=None):
    boxes = {"front": (50, 47, 1), "back": (50, 45, 2), "sleeve_l": (34, 25, 3), "sleeve_r": (34, 25, 4),
             "band": (44, 4, 5)}
    xyz, faces, part, uvm = [], [], [], {}
    for k, (name, (w, h, p)) in enumerate(boxes.items()):
        o = len(xyz)
        w_m, h_m = w / 100.0, h / 100.0
        xyz += [(0, k, 0), (w_m, k, 0), (w_m, k, h_m), (0, k, h_m)]
        faces.append((o, o + 1, o + 2, o + 3))
        part.append(p)
        uvm[name] = np.array([(0, 0), (w_m, 0), (w_m, h_m), (0, h_m)], float)
    xyz = np.array(xyz, float)
    isl = up.split_islands(len(xyz), faces, np.array(part), set(), xyz=xyz)
    return up.islands_payload(isl, uvm, xyz, 2048, 1.5, cap_heights=caps)


pl2 = tshirt_payload({"sleeve_l": -2.0})
check("[2] payload: 5 islands at 19.59 px/cm", len(pl2["islands"]) == 5 and abs(pl2["px_per_cm"] - 19.59) < 1e-9,
      ([i["name"] for i in pl2["islands"]], pl2["px_per_cm"]))
img2 = gct.render_template(pl2)
a2 = np.asarray(img2)
check("[2] square 2048", img2.size == (2048, 2048), img2.size)
nw2 = ~rgb_eq(a2, gct.BACKGROUND)
check("[2] non-white = the island mask", np.array_equal(nw2, gct.island_mask(pl2, 2048)))
r_nw = regions(nw2)
check("[2] 5 connected non-white regions", r_nw == 5, r_nw)
r_fill = regions(rgb_eq(a2, gct.TEMPLATE_FILL))
check("[2] 5 connected FILL regions", r_fill == 5, r_fill)

# [3] debug pattern sheet
labels = gct.pattern_sheet_labels(pl2)
front_txt = " ".join(labels.get("front", []))
nums = [float(x) for x in re.findall(r"\d+\.\d", front_txt)]
check("[3] front label names the piece", "Front" in front_txt, front_txt)
check("[3] front label 50.0 x 47.0 cm (+-0.1)", len(nums) >= 2 and abs(nums[0] - 50.0) <= 0.1
      and abs(nums[1] - 47.0) <= 0.1, front_txt)
check("[3] part names", labels.get("sleeve_l", [""])[0] == "Sleeve left" and labels.get("back", [""])[0] == "Back"
      and labels.get("band", [""])[0] == "Neckband", {k: v[0] for k, v in labels.items()})
sl = " ".join(labels.get("sleeve_l", []))
check("[3] sleeve cap height in the label", "cap -2.0 cm" in sl, sl)
check("[3] no cap line without a cap value", not any("cap" in t for t in labels.get("sleeve_r", [])))
check("[3] footer", gct.pattern_sheet_footer(pl2) == "19.59 px/cm · atlas 2048²", gct.pattern_sheet_footer(pl2))

sheet = gct.render_pattern_sheet(pl2)
sa = np.asarray(sheet.convert("RGB"))
mask2 = gct.island_mask(pl2, 2048)
labs2 = gct.rasterise_islands(pl2, 2048)
ids2 = gct.island_ids(pl2)
fills = {}
for name, iid in ids2.items():
    region = labs2 == iid
    px = sa[:2048][region]
    cols, counts = np.unique(px.reshape(-1, 3), axis=0, return_counts=True)
    top = tuple(int(c) for c in cols[np.argmax(counts)])
    fills[name] = (top, float(counts.max()) / float(region.sum()))
check("[3] 5 distinct fill colours", len({c for c, _ in fills.values()}) == 5, fills)
check("[3] each fill covers >= 50 % of its island", all(share >= 0.5 for _, share in fills.values()),
      {k: round(v[1], 3) for k, v in fills.items()})
check("[3] fills are pastel (every channel >= 150)", all(min(c) >= 150 for c, _ in fills.values()), fills)
check("[3] the sheet is not the model template", sa.shape[1] == 2048 and not np.array_equal(sa[:2048], a2))
check("[3] background outside the islands is white", tuple(sa[5, 5]) == gct.BACKGROUND, tuple(sa[5, 5]))

# seam letters: a cylinder cut in two halves has two seams
import math  # noqa: E402

R, H, S, NR = 0.15, 0.50, 40, 10
cx = np.array([(R * math.cos(2 * math.pi * k / S), R * math.sin(2 * math.pi * k / S), H * j / NR)
               for j in range(NR + 1) for k in range(S)])
cv = lambda k, j: j * S + (k % S)  # noqa: E731
cf = [(cv(k, j), cv(k + 1, j), cv(k + 1, j + 1), cv(k, j + 1)) for j in range(NR) for k in range(S)]
cs = {tuple(sorted((cv(k, j), cv(k, j + 1)))) for k in (0, S // 2) for j in range(NR)}
cisl = up.split_islands(len(cx), cf, np.ones(len(cf), int), cs, xyz=cx)
cuv = {}
for i in cisl:
    lx = cx[i.vmap]
    tris = np.array([t for poly in i.corner_vid for t in up.fan(poly)], dtype=np.int64)
    uv = up.arap(lx, tris, up.lscm(lx, tris), iters=20)
    cuv[i.name] = up.orient(uv, lx, tris, np.array([0, 0, 1.0]), np.zeros(3), None)
cpl = up.islands_payload(cisl, cuv, cx)
marks = gct.seam_marks(cpl)
letters = sorted({m["letter"] for m in marks})
check("[3] two seams -> letters A, B", letters == ["A", "B"], letters)
check("[3] each letter on both sides", all({m["island"] for m in marks if m["letter"] == L} == {"front", "front_2"}
                                           for L in letters), marks)
csheet = gct.render_pattern_sheet(cpl)
check("[3] cylinder sheet renders", csheet.size[0] == 2048, csheet.size)

# [4] occasion + prompt file
import hashlib  # noqa: E402

from app.core import prompt_adapters  # noqa: E402
from app.imagegen import occasions as occ  # noqa: E402

check("[4] occasion constant", gct.CUT_OCCASION == "garment_cut_texture" and gct.CUT_USE_CASE == "garment_cut_texture",
      (getattr(gct, "CUT_OCCASION", None), getattr(gct, "CUT_USE_CASE", None)))
check("[4] occasion in the catalog", gct.CUT_OCCASION in occ.occasion_ids())
pieces = gct.prompt_pieces(pl2)
check("[4] prompt pieces in pattern order", pieces == ["front panel", "back panel", "left sleeve", "right sleeve",
                                                       "neckband"], pieces)
check("[4] a split part keeps its number",
      gct.prompt_pieces({"islands": [{"name": "front_2"}, {"name": "back"}, {"name": "front"}]})
      == ["front panel", "front panel 2", "back panel"],
      gct.prompt_pieces({"islands": [{"name": "front_2"}, {"name": "back"}, {"name": "front"}]}))
want_pieces = ["front panel", "back panel", "left sleeve", "right sleeve", "neckband"]
prompt = gct.render_prompt(piece="T-shirt", pieces=want_pieces)
check("[4] prompt names the piece and its pieces", "T-shirt" in prompt and ", ".join(want_pieces) in prompt, prompt)
check("[4] prompt has the ordinal wording", "the first image" in prompt and "the second image" in prompt, prompt)
check("[4] no Jinja leftovers", "{{" not in prompt and "{#" not in prompt and prompt == prompt.strip())
ph3 = prompt_adapters.reference_wording(prompt, "p-h3-image")
check("[4] P-H3 wording", "<Picture 1>" in ph3 and "<Picture 2>" in ph3 and "first image" not in ph3
      and "second image" not in ph3, ph3)
check("[4] other backends keep the text", prompt_adapters.reference_wording(prompt, "qwen-edit") == prompt)
shipped = (ROOT / "shared" / "templates" / "image" / "garment_cut_texture.md").read_text(encoding="utf-8")
check("[4] PROMPT_SHA = md5 of the shipped file", gct.PROMPT_SHA == hashlib.md5(shipped.encode("utf-8")).hexdigest()
      and re.fullmatch(r"[0-9a-f]{32}", gct.PROMPT_SHA) is not None, gct.PROMPT_SHA)

# [5] StrictUndefined
import jinja2  # noqa: E402

try:
    gct.prompt_template().render(piece="T-shirt")
    check("[5] a missing variable raises", False, "rendered without 'pieces'")
except jinja2.exceptions.UndefinedError as e:
    check("[5] a missing variable raises", True, e)

# [6] compose keeps the prompt byte-identical
from types import SimpleNamespace  # noqa: E402

from app.core import config as _cfg  # noqa: E402
from app.core.prompt_compose import compose  # noqa: E402

for fam in ("keywords", "natural"):
    ucp = _cfg.get_use_case_prompts("garment_cut_texture", "qwen" if fam == "natural" else "z_image")
    check(f"[6] use case empty ({fam})", ucp == {"prompt_style": "", "prompt_negative": "", "prompt_instruction": ""},
          ucp)
    check(f"[6] use case shipped ({fam})", _cfg._DEFAULT_IMAGE_USE_CASES.get("garment_cut_texture", {}).get(fam)
          == {"prompt_style": "", "prompt_negative": "", "prompt_instruction": ""})
    c = compose(use_case="garment_cut_texture", subject=prompt,
                backend=SimpleNamespace(model="P-H3-Image", image_family=fam))
    check(f"[6] compose byte-identical ({fam})", c.prompt == prompt, c.prompt)
    check(f"[6] compose negative empty, no warnings ({fam})", c.negative == "" and c.warnings == [],
          (c.negative, c.warnings))

print(f"\n{len(FAILS)} FAILED: {FAILS}" if FAILS else "\nALL OK")
sys.exit(1 if FAILS else 0)
