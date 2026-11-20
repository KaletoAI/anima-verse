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

Task 8 — the job (``generate`` / ``start`` / ``status`` / ``item_source``), stubbed: ``current_drape`` returns a ready
drape whose islands are the [2] payload; ``routing.run_routed`` calls ``render`` once with a fake two-slot P-H3 backend
(or raises); ``get_image_service`` is a counter stub (upscale x4, ``run_on_backend`` / ``run_on_backend_channel`` call
straight through); ``inventory.get_item_image_path`` serves fixture files; the item matte is key-only (no BiRefNet).
[8.1] The fake backend answers the template it was given with every island pixel set to (150, 40, 40) (the item's
    fabric colour, a 1200 x 1100 RGBA picture with a (150, 40, 40) block on transparent): ``state`` "ready", IoU >= 0.98
    (the answer IS the mask, so the registration finds the identity map: IoU 1.0), ``.atlas.png`` exists at 2048 x
    2048; colour match moves nothing (atlas mean = fabric mean -> dE 0, the centre of the front island stays
    (150, 40, 40) +-2). ``csig`` = md5("|".join([islands sha, item sha, PROMPT_SHA, str(cut_texture_post.POST_VERSION)]))[:12]; the
    two references are file PATHS (str) in the order template, item; ``run_routed`` got the occasion, has_ref=True
    and the service's pool; the model is P-H3 without ``use_prompt_upsampler: false`` -> ``upsampler_on`` True;
    ``figure.invalidate`` ran once; the record keeps ``routing`` = route_meta (occasion garment_cut_texture,
    position 1).
[8.2] A white answer: ``rejected``, reason "coverage 0.00 < 0.97"; the raw answer is kept, no atlas — the atlas of
    [8.1] (same csig) is gone, so a record never sits next to an atlas it did not make.
[8.3] ``run_routed`` raises NoRouteError("garment_cut_texture", []) (its text points to /admin/settings -> Media
    Generation -> Routing): ``failed``, the reason contains "Routing"; no ``.raw.png`` / ``.atlas.png``, the record
    and the two input PNGs (template, item) exist. ``start`` with an empty ``chain_for`` raises NoRouteError before
    any thread or file (cut dir has no file of that item, no running entry); with media off it raises
    MediaGenerationDisabled; without a ready drape (or one without islands) it raises ``NotReady``.
[8.4] ``run_routed`` raises MediaGenerationDisabled: ``failed``, the reason contains "Media generation is off".
[8.5] ``socket.create_connection`` is replaced for the whole smoke and counts every attempt: 0 at the end.
[8.6] ``item_source``: a 300 x 256 item -> the (stubbed) upscaler runs once (status "applied", 1200 x 1024 out);
    1200 x 1100 -> not called ("not_needed", size kept); an upscaler that fails -> Lanczos to a 1024 long side
    ("lanczos"); BackendBusyError / MediaGenerationDisabled are re-raised.
[8.7] ``start`` runs ``generate`` in a thread: with a white answer the status ends not running, the record is
    "rejected", and a second ``start`` while running answers False.

Task 9 — the atlas assignment (``garment_template.texture`` / ``cut_info`` / ``atlas_for`` / ``texture_warning``,
``garment_assembly._state`` / ``_apply_cut_atlas``, ``figure_build._template_row``), same stubs; the drape record is a
dict whose ``islands.sha256`` is the [2] payload's sha.
[9.1] ``PARAM_SPEC["texture"]`` = ("choice", ("projection", "cut"), "projection"), a ``top`` field (another kind is
    reset to the default), an unknown value is an error; ``TEXTURE_ONLY`` = ("fly", "texture"), so a top's ``tsig``
    is the same for texture "projection" and "cut".
[9.2] ``generate`` with the filled answer -> ready; with the item's texture "cut", ``atlas_for`` returns the
    ``.atlas.png`` bytes and ``{texture "cut", csig, cut_state "ready", metrics (IoU >= 0.98), px_per_cm 19.59}``;
    texture "projection" -> (None, "off"); a drape record without ``islands`` (a grid kind) -> (None, "off"). While the
    cut atlas is in use the projection bake's warning is not shown (``texture_warning({coverage 0.43}, info)`` None:
    the projection is not what the figure shows).
[9.3] The drape's islands sha changed -> no record for the new csig, a ready one for the old -> "stale", texture
    "projection", the warning's ``cut.text`` "Texture from cut is out of date — make it again (1 image job)" (the bake
    flags stay false on a good bake). Only the drape's ``tsig`` changed (a re-rendered piece-only view, same islands)
    -> still "cut", same csig. An item with no cut record at all -> "missing", which is not a warning.
[9.4] Item "shirt" (its current csig's record is the [8.2] rejection) -> "rejected" with reason "coverage 0.00 <
    0.97"; the warning's ``cut`` names it. ``_template_row`` (drape_state / current_base stubbed): ``metrics.cut.state``
    "rejected" with the reason, ``metrics.texture`` stays the projection's source ("views"); for "shirt9"
    ``metrics.texture`` "cut", ``metrics.cut`` {state "ready", reason, iou >= 0.98, de_after, px_per_cm 19.59}, no
    warning, ``cost.hub_jobs`` 0.
[9.5] ``garment_assembly._state`` of the template piece: ``texture`` "projection", then "cut:<csig>" once the item
    says "cut"; the two entries differ only in ``texture`` (the GLB sha256 is the same file's). ``_apply_cut_atlas``
    puts the atlas bytes (mime image/png) on the mesh with "cut" and leaves the GLB's image with "projection".
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

# [8.5] the outbound guard: any network connection attempt during the whole smoke fails (and is counted)
import socket  # noqa: E402

OUTBOUND = []


def _no_outbound(*a, **k):
    OUTBOUND.append(a[:1])
    raise OSError("smoke_garment_cut_texture: outbound connection refused")


socket.create_connection = _no_outbound

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

# ---------------------------------------------------------------------------------------------------- Task 8: the job
import io  # noqa: E402
import json  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from unittest.mock import patch  # noqa: E402

from PIL import Image  # noqa: E402

from app.core import paths  # noqa: E402

_world = Path(_tmp) / "world"
_inst = Path(_tmp) / "instance"
paths.init(_world)
paths.init_instance(_inst)
(_world / "config.json").write_text("{}", encoding="utf-8")
(_inst / "config.json").write_text("{}", encoding="utf-8")
_cfg.load(_world / "config.json", _inst / "config.json")

from app.imagegen.base import BackendBusyError, MediaGenerationDisabled  # noqa: E402
from app.imagegen.routing import NoRouteError, Route  # noqa: E402
from app.models.character import get_character_dir  # noqa: E402

CHAR = "demo"
get_character_dir(CHAR, create=True)
_items = Path(_tmp) / "items"
_items.mkdir()


def _png(im):
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def _item_picture(w, h):
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    im.paste((150, 40, 40, 255), (w // 6, h // 6, w - w // 6, h - h // 6))
    return im


ITEM_FILES = {}
for _iid, (_w, _h) in {"shirt": (1200, 1100), "shirt3": (1200, 1100), "shirt4": (1200, 1100),
                       "shirt5": (1200, 1100), "tiny": (300, 256), "shirt9": (1200, 1100)}.items():
    ITEM_FILES[_iid] = _items / f"{_iid}.png"
    _item_picture(_w, _h).save(ITEM_FILES[_iid])

_islands_file = Path(_tmp) / "drape.islands.json"
_islands_file.write_text(json.dumps(pl2), encoding="utf-8")
ISLANDS_SHA = hashlib.sha256(_islands_file.read_bytes()).hexdigest()
DRAPES = {iid: {"state": "ready", "reason": "", "tsig": "tsig0", "islands_path": _islands_file,
                "islands_sha": ISLANDS_SHA} for iid in ITEM_FILES}


def fake_current_drape(character_name, item_id):
    return DRAPES.get(item_id) or {"state": "missing", "reason": "Not draped yet", "tsig": None,
                                   "islands_path": None, "islands_sha": ""}


class CutBackend:
    name = "FakeCut"
    api_type = "fake"
    image_family = "natural"
    model = "P-H3-Image"
    ref_slot_count = 2
    max_side = 2048
    extra_params = {}

    def __init__(self):
        self.calls = []
        self.answer = None

    def generate(self, prompt, negative, params, log_meta=None):
        self.calls.append({"prompt": prompt, "negative": negative, "params": params})
        return [self.answer(params)]


class Service:
    def __init__(self):
        self.pool = object()
        self.upscales = 0
        self.upscale_fail = None

    def upscale_image(self, image_bytes, *, character_name="", **_kw):
        self.upscales += 1
        if self.upscale_fail is not None:
            raise self.upscale_fail
        with Image.open(io.BytesIO(image_bytes)) as im:
            big = im.convert("RGB").resize((im.width * 4, im.height * 4), Image.NEAREST)
        return {"bytes": _png(big), "backend": "FakeUp", "scale": 4, "status": "applied",
                "in": [big.width // 4, big.height // 4], "out": [big.width, big.height],
                "routing": {"occasion": "upscale", "position": 1, "spec": "FakeUp*"}}

    def run_on_backend(self, backend, op, character_name=""):
        return op(backend), backend

    def run_on_backend_channel(self, backend, gen_fn, **_kw):
        return gen_fn()


def answer_filled(params):
    with Image.open(params["reference_images"]["input_reference_image_1"]) as t:
        arr = np.asarray(t.convert("RGB")).copy()
    m = ~rgb_eq(arr, gct.BACKGROUND)
    arr[:] = 255
    arr[m] = (150, 40, 40)
    return _png(Image.fromarray(arr, "RGB"))


def answer_white(params):
    return _png(Image.new("RGB", (2048, 2048), (255, 255, 255)))


backend = CutBackend()
svc = Service()
ROUTED = []
RAISE = {"exc": None}
INVALIDATED = []
CHAIN = {"rows": [("FakeCut*", "rule", 1)]}
MEDIA = {"on": True}


def fake_run_routed(occasion, render, *, character="", has_ref=False, pool=None, **_kw):
    ROUTED.append({"occasion": occasion, "has_ref": has_ref, "pool_is_svc": pool is svc.pool})
    if RAISE["exc"] is not None:
        raise RAISE["exc"]
    result = render(backend)
    return result, Route(occasion=occasion, backend=backend, position=1, spec="FakeCut*",
                         intended_spec="FakeCut*", first_position=1)


def files_of(item_id):
    d = gct.cut_dir(CHAR)
    return sorted(p.name for p in d.glob(f"{item_id}_*")) if d.is_dir() else []


SLEEVES = {"shirt": "short", "long": "long"}
TEXTURES = {}       # Task 9: the item's stored ``texture`` param (absent = the default "projection")


def fake_get_item(iid):
    params = {"kind": "top", "sleeves": SLEEVES.get(iid, "short")}
    if iid in TEXTURES:
        params["texture"] = TEXTURES[iid]
    return {"id": iid, "category": "outfit_piece",
            "outfit_piece": {"template": {"params": params, "source": "user"}}}


with patch("app.models.inventory.get_item_image_path", lambda iid: str(ITEM_FILES.get(iid, ""))), \
        patch("app.models.inventory.get_item", fake_get_item), \
        patch("app.imagegen.service.get_image_service", lambda: svc), \
        patch("app.imagegen.routing.run_routed", fake_run_routed), \
        patch("app.imagegen.routing.chain_for", lambda occasion, *a, **k: list(CHAIN["rows"])), \
        patch("app.imagegen.base.media_generation_enabled", lambda: MEDIA["on"]), \
        patch("app.core.figure.invalidate", lambda: INVALIDATED.append(1)), \
        patch.object(gct, "current_drape", fake_current_drape), \
        patch.object(gct, "_item_matte", lambda: None):

    item_sha = hashlib.sha256(ITEM_FILES["shirt"].read_bytes()).hexdigest()
    want_csig = hashlib.md5("|".join([ISLANDS_SHA, item_sha, gct.PROMPT_SHA,
                                      str(gct.cut_texture_post.POST_VERSION)]).encode()).hexdigest()[:12]
    check("[8.1] csig formula", gct.csig(ISLANDS_SHA, item_sha) == want_csig, gct.csig(ISLANDS_SHA, item_sha))
    check("[8.1] current_csig", gct.current_csig(CHAR, "shirt") == want_csig, gct.current_csig(CHAR, "shirt"))

    # [8.1] a filled template -> ready
    backend.answer = answer_filled
    t0 = time.time()
    rec = gct.generate(CHAR, "shirt")
    print(f"     (generate took {time.time() - t0:.1f} s)")
    check("[8.1] ready", rec.get("state") == "ready", (rec.get("state"), rec.get("reason")))
    check("[8.1] IoU >= 0.98", (rec.get("metrics") or {}).get("iou", 0) >= 0.98, rec.get("metrics"))
    stem = gct.cut_dir(CHAR) / f"shirt_{want_csig}"
    atlas = Path(f"{stem}.atlas.png")
    check("[8.1] atlas exists", atlas.is_file(), files_of("shirt"))
    if atlas.is_file():
        with Image.open(atlas) as a_im:
            a_arr = np.asarray(a_im.convert("RGB"))
            check("[8.1] atlas 2048 x 2048", a_im.size == (2048, 2048), a_im.size)
        front = next(i for i in pl2["islands"] if i["name"] == "front")
        x0, y0, x1, y1 = front["bbox_px"]
        cpx = a_arr[int((y0 + y1) / 2), int((x0 + x1) / 2)].astype(int)
        check("[8.1] colour kept (150, 40, 40) +-2", np.abs(cpx - [150, 40, 40]).max() <= 2, cpx.tolist())
    check("[8.1] record on disk", json.loads(Path(f"{stem}.json").read_text()).get("state") == "ready")
    check("[8.1] record fields", rec.get("csig") == want_csig and rec.get("islands_sha") == ISLANDS_SHA
          and rec.get("tsig") == "tsig0" and rec.get("prompt_sha") == gct.PROMPT_SHA
          and rec.get("item_px") == [1200, 1100] and (rec.get("upscale") or {}).get("status") == "not_needed"
          and abs(rec.get("px_per_cm", 0) - 19.59) < 1e-6, rec)
    check("[8.1] metrics keys", set(rec.get("metrics") or {}) >= {"iou", "coverage", "island_coverage", "spill",
                                                                 "de_before", "de_after", "clamped", "seam_de"},
          sorted(rec.get("metrics") or {}))
    check("[8.1] routing = route_meta", (rec.get("routing") or {}).get("routing")
          == {"occasion": "garment_cut_texture", "position": 1, "spec": "FakeCut*"}, rec.get("routing"))
    check("[8.1] run_routed occasion / has_ref / pool", ROUTED[-1] == {"occasion": "garment_cut_texture",
                                                                       "has_ref": True, "pool_is_svc": True}, ROUTED)
    refs = backend.calls[-1]["params"].get("reference_images") or {}
    check("[8.1] references: template then item, as str paths",
          list(refs) == ["input_reference_image_1", "input_reference_image_2"]
          and all(isinstance(v, str) for v in refs.values())
          and refs.get("input_reference_image_1") == f"{stem}.template.png"
          and refs.get("input_reference_image_2") == f"{stem}.item.png", refs)
    check("[8.1] no image_use_case in params", "image_use_case" not in backend.calls[-1]["params"])
    check("[8.1] the prompt is the rendered file, ordinal wording kept for the handoff",
          "the first image" in backend.calls[-1]["prompt"] and backend.calls[-1]["negative"] == "",
          backend.calls[-1]["prompt"][:80])
    check("[8.1] piece name from kind + sleeves", backend.calls[-1]["prompt"].count("T-shirt") == 2
          and gct.piece_name("long") == "long-sleeve shirt", gct.piece_name("long"))
    check("[8.1] upsampler_on noted", rec.get("upsampler_on") is True, rec.get("upsampler_on"))
    check("[8.1] figure invalidated once", len(INVALIDATED) == 1, len(INVALIDATED))
    st = gct.status(CHAR, "shirt")
    check("[8.1] status: the current record", st.get("csig") == want_csig and st.get("running") is False
          and (st.get("record") or {}).get("state") == "ready", st)

    # [8.2] white -> rejected, the old atlas of this csig gone
    backend.answer = answer_white
    rec2 = gct.generate(CHAR, "shirt")
    check("[8.2] rejected", rec2.get("state") == "rejected", rec2.get("state"))
    check("[8.2] reason", rec2.get("reason") == "coverage 0.00 < 0.97", rec2.get("reason"))
    check("[8.2] raw kept, no atlas", Path(f"{stem}.raw.png").is_file() and not atlas.is_file(), files_of("shirt"))
    check("[8.2] no invalidate on a rejection", len(INVALIDATED) == 1, len(INVALIDATED))

    # [8.3] NoRouteError -> failed
    RAISE["exc"] = NoRouteError("garment_cut_texture", [])
    rec3 = gct.generate(CHAR, "shirt3")
    c3 = gct.csig(ISLANDS_SHA, hashlib.sha256(ITEM_FILES["shirt3"].read_bytes()).hexdigest())
    check("[8.3] failed, reason names Routing", rec3.get("state") == "failed" and "Routing" in rec3.get("reason", ""),
          (rec3.get("state"), rec3.get("reason")))
    check("[8.3] record + inputs, no raw / atlas", files_of("shirt3") == sorted(
        [f"shirt3_{c3}.json", f"shirt3_{c3}.item.png", f"shirt3_{c3}.template.png"]), files_of("shirt3"))

    # [8.4] media off inside the job -> failed
    RAISE["exc"] = MediaGenerationDisabled("Media generation is disabled for this world")
    rec4 = gct.generate(CHAR, "shirt3")
    check("[8.4] failed, media off", rec4.get("state") == "failed"
          and "Media generation is off" in rec4.get("reason", ""), (rec4.get("state"), rec4.get("reason")))
    RAISE["exc"] = None

    # [8.3] start(): synchronous refusals, nothing started, nothing written
    CHAIN["rows"] = []
    try:
        gct.start(CHAR, "shirt4")
        check("[8.3] start with an empty chain raises", False, "no exception")
    except NoRouteError as e:
        check("[8.3] start with an empty chain raises NoRouteError (Routing)", "Routing" in str(e), e)
    check("[8.3] nothing written, nothing running", files_of("shirt4") == []
          and (CHAR, "shirt4") not in gct._running, (files_of("shirt4"), dict(gct._running)))
    CHAIN["rows"] = [("FakeCut*", "rule", 1)]
    MEDIA["on"] = False
    try:
        gct.start(CHAR, "shirt4")
        check("[8.3] start with media off raises", False, "no exception")
    except MediaGenerationDisabled as e:
        check("[8.3] start with media off raises MediaGenerationDisabled", "Media generation is off" in str(e), e)
    MEDIA["on"] = True
    DRAPES["shirt4"] = {"state": "missing", "reason": "Not draped yet", "tsig": "t", "islands_path": None,
                        "islands_sha": ""}
    try:
        gct.start(CHAR, "shirt4")
        check("[8.3] start without a ready drape raises", False, "no exception")
    except gct.NotReady as e:
        check("[8.3] start without a ready drape raises NotReady", True, e)
    DRAPES["shirt4"] = {"state": "ready", "reason": "", "tsig": "t", "islands_path": None, "islands_sha": ""}
    try:
        gct.start(CHAR, "shirt4")
        check("[8.3] start with a drape without islands raises", False, "no exception")
    except gct.NotReady as e:
        check("[8.3] start with a drape without islands raises NotReady", True, e)
    check("[8.3] still nothing written", files_of("shirt4") == [], files_of("shirt4"))

    # [8.7] the thread
    backend.answer = answer_white
    gate_evt = threading.Event()
    real_answer = backend.answer

    def slow_white(params):
        gate_evt.wait(10)
        return real_answer(params)

    backend.answer = slow_white
    started = gct.start(CHAR, "shirt5")
    again = gct.start(CHAR, "shirt5")
    check("[8.7] start -> True, a second start while running -> False", started is True and again is False,
          (started, again))
    check("[8.7] status running", gct.status(CHAR, "shirt5").get("running") is True)
    gate_evt.set()
    for _ in range(600):
        if not gct.status(CHAR, "shirt5").get("running"):
            break
        time.sleep(0.05)
    st5 = gct.status(CHAR, "shirt5")
    check("[8.7] thread done, record rejected", st5.get("running") is False
          and (st5.get("record") or {}).get("state") == "rejected", st5)

    # [8.6] item_source
    n0 = svc.upscales
    data, info = gct.item_source("tiny")
    with Image.open(io.BytesIO(data)) as im:
        size_t = im.size
    check("[8.6] 300 x 256 -> upscaled once", svc.upscales == n0 + 1 and (info.get("upscale") or {}).get("status")
          == "applied" and size_t == (1200, 1024), (svc.upscales - n0, info, size_t))
    data, info = gct.item_source("shirt")
    with Image.open(io.BytesIO(data)) as im:
        size_s = im.size
    check("[8.6] 1200 x 1100 -> not upscaled", svc.upscales == n0 + 1 and (info.get("upscale") or {}).get("status")
          == "not_needed" and size_s == (1200, 1100), (svc.upscales - n0, info, size_s))
    svc.upscale_fail = RuntimeError("upscaler broken")
    data, info = gct.item_source("tiny")
    with Image.open(io.BytesIO(data)) as im:
        size_l = im.size
    check("[8.6] failed upscale -> Lanczos to 1024", (info.get("upscale") or {}).get("status") == "lanczos"
          and max(size_l) == 1024, (info, size_l))
    for exc in (BackendBusyError("busy"), MediaGenerationDisabled("off")):
        svc.upscale_fail = exc
        try:
            gct.item_source("tiny")
            check(f"[8.6] {type(exc).__name__} re-raised", False, "swallowed")
        except type(exc):
            check(f"[8.6] {type(exc).__name__} re-raised", True)
    svc.upscale_fail = None

    # ------------------------------------------------------------------------------- Task 9: the atlas assignment
    from types import SimpleNamespace as NS  # noqa: E402

    from app.core import figure_build  # noqa: E402
    from app.core import garment_assembly as ga  # noqa: E402
    from app.core import garment_template as gt  # noqa: E402

    # [9.1] the param, out of tsig
    p_proj, e_proj = gt.validate_params({"kind": "top", "texture": "projection"})
    p_cut, e_cut = gt.validate_params({"kind": "top", "texture": "cut"})
    check("[9.1] texture: a top field, choices projection / cut, default projection",
          gt.PARAM_SPEC.get("texture") == ("choice", ("projection", "cut"), "projection")
          and "texture" in gt.KIND_FIELDS["top"] and p_cut.get("texture") == "cut" and not e_proj and not e_cut
          and gt.validate_params({"kind": "top"})[0].get("texture") == "projection", gt.PARAM_SPEC.get("texture"))
    check("[9.1] another kind keeps the default",
          gt.validate_params({"kind": "skirt", "texture": "cut"})[0].get("texture") == "projection")
    check("[9.1] an unknown value is an error", gt.validate_params({"kind": "top", "texture": "paint"})[1] != [])
    check("[9.1] texture is TEXTURE_ONLY", gt.TEXTURE_ONLY == ("fly", "texture"), gt.TEXTURE_ONLY)
    k_proj = gt.tsig(p_proj, base_sha="b", texture_sha="t", lower=[])
    k_cut = gt.tsig(p_cut, base_sha="b", texture_sha="t", lower=[])
    check("[9.1] switching texture leaves tsig unchanged", k_proj == k_cut, (k_proj, k_cut))

    # [9.2] a ready cut atlas is used only with texture == "cut"
    backend.answer = answer_filled
    rec9 = gct.generate(CHAR, "shirt9")
    c9 = rec9.get("csig")
    atlas9_file = gct.cut_dir(CHAR) / f"shirt9_{c9}.atlas.png"
    DRAPE_REC = {"islands": {"file": "shirt9_tsig0.islands.json", "sha256": ISLANDS_SHA, "px_per_cm": 19.59},
                 "tsig": "tsig0"}
    TEXTURES["shirt9"] = "cut"
    a9, i9 = gt.atlas_for(CHAR, "shirt9", DRAPE_REC)
    check("[9.2] ready -> the atlas bytes", rec9.get("state") == "ready" and a9 is not None
          and a9 == atlas9_file.read_bytes(), (rec9.get("state"), None if a9 is None else len(a9)))
    check("[9.2] info: cut, csig, metrics", i9.get("texture") == "cut" and i9.get("csig") == c9
          and i9.get("cut_state") == "ready" and (i9.get("metrics") or {}).get("iou", 0) >= 0.98
          and abs((i9.get("px_per_cm") or 0) - 19.59) < 1e-6, i9)
    TEXTURES["shirt9"] = "projection"
    a9p, i9p = gt.atlas_for(CHAR, "shirt9", DRAPE_REC)
    check("[9.2] texture projection -> None, off", a9p is None and i9p.get("texture") == "projection"
          and i9p.get("cut_state") == "off", i9p)
    TEXTURES["shirt9"] = "cut"
    a9g, i9g = gt.atlas_for(CHAR, "shirt9", {"tsig": "tsig0"})
    check("[9.2] a drape without islands (grid kind) -> None, off", a9g is None and i9g.get("cut_state") == "off",
          i9g)
    check("[9.2] the cut atlas in use: no projection warning", gt.texture_warning({"coverage": 0.43}, i9) is None)

    # [9.3] stale: new islands -> the projection and the warning; a new tsig alone keeps the cut
    a9s, i9s = gt.atlas_for(CHAR, "shirt9", {**DRAPE_REC, "islands": {**DRAPE_REC["islands"], "sha256": "f" * 64}})
    check("[9.3] new islands -> stale, projection", a9s is None and i9s.get("cut_state") == "stale"
          and i9s.get("texture") == "projection", i9s)
    w9s = gt.texture_warning({"coverage": 0.9, "iou": 0.9}, i9s) or {}
    check("[9.3] the stale warning text", (w9s.get("cut") or {}).get("text")
          == "Texture from cut is out of date — make it again (1 image job)", w9s)
    check("[9.3] stale: the bake flags stay false", w9s.get("low_coverage") is False and w9s.get("low_iou") is False,
          w9s)
    a9t, i9t = gt.atlas_for(CHAR, "shirt9", {**DRAPE_REC, "tsig": "tsig1"})
    check("[9.3] a new tsig alone (a re-rendered view) -> still cut", a9t is not None and i9t.get("csig") == c9, i9t)
    TEXTURES["shirt4"] = "cut"
    a4, i4 = gt.atlas_for(CHAR, "shirt4", DRAPE_REC)
    check("[9.3] nothing made yet -> missing, no warning", a4 is None and i4.get("cut_state") == "missing"
          and gt.texture_warning({"coverage": 0.9, "iou": 0.9}, i4) is None, i4)

    # [9.4] rejected: the reason in the warning and in the figure row
    TEXTURES["shirt"] = "cut"
    a1r, i1r = gt.atlas_for(CHAR, "shirt", DRAPE_REC)
    check("[9.4] rejected -> projection with the reason", a1r is None and i1r.get("cut_state") == "rejected"
          and i1r.get("reason") == "coverage 0.00 < 0.97", i1r)
    w1r = gt.texture_warning({"coverage": 0.9, "iou": 0.9}, i1r) or {}
    check("[9.4] the warning carries the reason", (w1r.get("cut") or {}).get("state") == "rejected"
          and "coverage 0.00 < 0.97" in (w1r.get("cut") or {}).get("text", ""), w1r)

    def fake_drape_state(character_name, item_id, **_kw):
        return {"state": "ready", "reason": "", "tsig": "tsig0", "path": None,
                "record": {**DRAPE_REC, "created_at": "now", "texture": {"source": "views"},
                           "metrics": {"bake": {"coverage": 0.9, "iou": 0.9}, "drape": {}}}}

    with patch.object(gt, "drape_state", fake_drape_state), \
            patch("app.core.base_body.current_base", lambda *a, **k: ("bsig", "bsha")):
        row1 = figure_build._template_row(CHAR, "shirt", fake_get_item("shirt"), NS(own=[]), {})
        row9 = figure_build._template_row(CHAR, "shirt9", fake_get_item("shirt9"), NS(own=[]), {})
    m1r, m9 = row1.get("metrics") or {}, row9.get("metrics") or {}
    check("[9.4] figure row: cut rejected, projection source kept", (m1r.get("cut") or {}).get("state") == "rejected"
          and (m1r.get("cut") or {}).get("reason") == "coverage 0.00 < 0.97" and m1r.get("texture") == "views"
          and ((m1r.get("texture_warning") or {}).get("cut") or {}).get("state") == "rejected", m1r)
    check("[9.4] figure row: cut in use", m9.get("texture") == "cut" and (m9.get("cut") or {}).get("state") == "ready"
          and (m9.get("cut") or {}).get("iou", 0) >= 0.98 and abs(((m9.get("cut") or {}).get("px_per_cm") or 0)
                                                                   - 19.59) < 1e-6
          and set(m9.get("cut") or {}) >= {"state", "reason", "iou", "de_after", "px_per_cm"}
          and m9.get("texture_warning") is None and row9.get("cost", {}).get("hub_jobs") == 0, m9)

    # [9.5] the assembly state and the graft swap
    fit9 = Path(_tmp) / "shirt9.glb"
    fit9.write_bytes(b"glb")
    g9 = {"item_id": "shirt9", "kind": "clothing", "fsig": "tsig0", "fit": fit9, "low": None, "record": DRAPE_REC,
          "template": True}
    with patch.object(ga, "_material", lambda gm: ("m", None)):
        TEXTURES["shirt9"] = "projection"
        st_p = ga._state([{**g9, "item": fake_get_item("shirt9")}], "full", character_name=CHAR)["shirt9"]
        TEXTURES["shirt9"] = "cut"
        st_c = ga._state([{**g9, "item": fake_get_item("shirt9")}], "full", character_name=CHAR)["shirt9"]
    check("[9.5] state: projection, then cut:<csig>", st_p.get("texture") == "projection"
          and st_c.get("texture") == f"cut:{c9}", (st_p.get("texture"), st_c.get("texture")))
    check("[9.5] the two states differ, the GLB sha does not", st_p != st_c and st_p.get("sha256") == st_c.get("sha256")
          and {k: v for k, v in st_p.items() if k != "texture"} == {k: v for k, v in st_c.items() if k != "texture"},
          (st_p, st_c))
    mesh_c = NS(image=b"projection", mime="image/jpeg")
    ga._apply_cut_atlas(CHAR, {**g9, "item": fake_get_item("shirt9")}, mesh_c)
    check("[9.5] graft: the cut atlas replaces the image", mesh_c.image == atlas9_file.read_bytes()
          and mesh_c.mime == "image/png", (len(mesh_c.image), mesh_c.mime))
    TEXTURES["shirt9"] = "projection"
    mesh_p = NS(image=b"projection", mime="image/jpeg")
    ga._apply_cut_atlas(CHAR, {**g9, "item": fake_get_item("shirt9")}, mesh_p)
    check("[9.5] graft: projection keeps the GLB's image", mesh_p.image == b"projection" and mesh_p.mime == "image/jpeg")

check("[8.5] no outbound connection attempt", OUTBOUND == [], OUTBOUND)

print(f"\n{len(FAILS)} FAILED: {FAILS}" if FAILS else "\nALL OK")
sys.exit(1 if FAILS else 0)
