#!/usr/bin/env python3
"""Smoke: group A — the texture from cut switched on for the close-fitting kinds (briefs, bra, gloves, tights, trousers).

No server, no world DB, no Blender, no image job. Usage: ./.venv/bin/python scripts/smoke_cut_texture_group_a.py

Hand-derived expectations:

[1] ``KIND_FIELDS`` of every fitted kind carries "texture" and "sleeve_print" (the dialog renders them generically);
    ``validate_params`` keeps a trousers' ``texture`` "cut" (a field outside ``KIND_FIELDS`` would be reset to
    "projection"), and ``sleeve_print`` "picture".
[2] ``FITTED_VERSION`` is 1, so a fitted drape key carries ``"fitted": 1`` (every fitted drape is re-draped once): the
    trousers' ``tsig`` equals md5 of ``{params, version, base, texture, lower, fitted: 1}`` and differs from the same
    payload without the key; a top's ``tsig`` has no such key (md5 of the payload without it). ``texture`` is
    ``TEXTURE_ONLY``: "cut" and "projection" give the same trousers ``tsig``.
[3] Prompt families: ``prompt_family`` "top" for a top with a bodice, "fitted" for the five fitted kinds (and since
    group B a skirt and a strapless top, ``item_kind`` "strapless"); ``PROMPT_SHA`` (the
    top's) is still md5 of the three top files joined by NUL — a top atlas keeps its csig; the fitted sha is md5 of the
    three fitted files and differs; ``csig`` of the same inputs differs between the two families.
[4] ``main_words`` on a hand-made trousers FRONT payload (2048 px): front_r bbox [100, 100, 500, 1000] area 3000 cm²,
    front_l [600, 100, 1000, 1000] 2900 cm², waistband strip [100, 1100, 1600, 1160] 600 cm² -> the two main islands
    are the two largest: phrase "the two largest shapes", count 2, names "the right front leg panel and the left front
    leg panel" (pattern order: ``PROMPT_PIECE_NAMES`` has front_r before front_l). A briefs front payload with one main
    island, bbox centre (300, 300) / 2048 = (0.146, 0.146) < ``LAYOUT_SIDE`` 0.36 on both axes -> "the top left shape".
    A bra whose right strap (area 300) is larger than the left cup (area 200): the cups are not the two largest, so
    the phrase names their places — cup_r centre (300, 200) -> "at the top left", cup_l centre (1700, 200) -> "at the
    top right": "the shapes at the top left and at the top right".
[5] Parts: the front job's MAIN parts are front / front_l / front_r / leg_* / cup_* / glove_back_* (group B adds
    skirt_front / left_front / right_front), the back job's back / back_l / back_r / palm_* (group B: skirt_back); ``model_parts("front", "plain")`` holds front_l, cup_top_r (a balconette's upper
    cup), but no collar (group B phases C / D: a jacket's / dress's collar strip is a held trim like the waistband;
    no top emits one), no waistband / gusset / strap / thumb / sleeve; with "picture" all of ``TRIM_PARTS`` join
    (waistband, gusset, strap_l, thumb_r, sleeve_l, cuff_r) — and a top's neckband "band" is never one of them.
[6] The fabric patch is cut from the MAIN parts: on a 100 px raster of the trousers payload scaled 1/20.48
    (front_r [5, 5, 24, 49) -> 19 x 44 px, front_l [29, 5, 49, 49) -> 20 x 44 px, waistband [5, 54, 78, 57) -> 73 x 3
    px; pixel centres, half-open), ``_part_mask(.., MAIN_PARTS["front"])`` covers 19*44 + 20*44 = 1716 px and none of
    the waistband's 219 (corners of an axis-aligned box on pixel edges: centres j + 0.5 in [x0, x1)).
[7] ``kind_has_back`` (the estimate before the cut): top, trousers, briefs, gloves, a bandeau True; tights and a
    molded / balconette bra False (decisions D2 / D4).
[8] ``a_piece``: "elbow-length gloves" -> "a pair of elbow-length gloves", "high-leg briefs" -> "a pair of high-leg
    briefs", "tights" -> "a pair of tights", "balconette bra" -> "a balconette bra", "arm warmers" -> "a pair of arm
    warmers", "thong" -> "a thong".
[9] The fitted decorated FRONT prompt of [4] per dialect: P-H3 "Edit <Picture 1>. In <Picture 1>, the two largest
    shapes are the right front leg panel and the left front leg panel of the trousers in <Picture 2>, laid flat. Paint
    them as in <Picture 2>: …"; MiniMax names <Subject 1> and "left and right are the wearer's" and keeps the waistband
    plain ("The waistband of <Subject 1> carry only the plain fabric" is the template's grammar for a list — checked
    only for "waistband of <Subject 1>"); Qwen ``<image1>`` / ``<image2>``; ordinal "the first image" / "the second
    image"; no section carries ``<ref``. The fitted BACK prompt for two palms says "shapes" (P-H3).
    A plain front lists two trims joined "A and B" ("right thumb and left thumb").
[10] The colour gate of an all-over pattern: a flat red answer (180, 40, 30) on a 64 x 64 panel against an item
    colour of the dark scale gaps (lab of (19, 8, 3)) is far over ``ANSWER_GATE["de00"]`` 20; with the item's
    ``plain`` 0.0024 (< ``FABRIC_MIN_PLAIN`` 0.05, Glut's scale briefs live) the gate is ``skipped`` and ok, with
    ``plain`` 0.5 it fails as before.
"""
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TEMP = tempfile.TemporaryDirectory(prefix="smoke-cut-group-a-")
os.environ["STORAGE_DIR"] = TEMP.name
os.environ["INSTANCE_DIR"] = TEMP.name
from app.core import paths  # noqa: E402

paths.init(TEMP.name)
from app.core import garment_cut_texture as gct  # noqa: E402
from app.core import garment_template as gt  # noqa: E402

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"))
    if not ok:
        FAILS.append(label)


# [1]
for kind in gt.FITTED_KINDS:
    check(f"[1] {kind} has texture + sleeve_print", all(f in gt.KIND_FIELDS[kind] for f in ("texture", "sleeve_print")),
          True)
params, errors = gt.validate_params({"kind": "trousers", "texture": "cut", "sleeve_print": "picture"})
check("[1] trousers keep texture cut", params["texture"], "cut")
check("[1] trousers keep sleeve_print picture", params["sleeve_print"], "picture")

# [2]
check("[2] FITTED_VERSION", gt.FITTED_VERSION, 1)


def md5(payload):
    return gt._md5(payload)


tp = gt.validate_params({"kind": "trousers"})[0]
base = {"params": gt.keyed_params(tp), "version": gt.TEMPLATE_VERSION, "base": "b", "texture": "t", "lower": []}
check("[2] trousers tsig carries fitted 1", gt.tsig(tp, base_sha="b", texture_sha="t", lower=[]),
      md5({**base, "fitted": 1}))
check("[2] ... and differs without it", md5(base) != gt.tsig(tp, base_sha="b", texture_sha="t", lower=[]), True)
top = gt.validate_params({"kind": "top", "shoulders": "covered", "sleeves": "short"})[0]
check("[2] a top's tsig has no fitted key", gt.tsig(top, base_sha="b", texture_sha="t", lower=[]),
      md5({"params": gt.keyed_params(top), "version": gt.TEMPLATE_VERSION, "base": "b", "texture": "t", "lower": []}))
check("[2] texture is TEXTURE_ONLY", gt.tsig({**tp, "texture": "cut"}, base_sha="b", texture_sha="t", lower=[]),
      gt.tsig({**tp, "texture": "projection"}, base_sha="b", texture_sha="t", lower=[]))

# [3]
check("[3] families", [gct.prompt_family(k) for k in ("top", "skirt", "strapless", *gt.FITTED_KINDS)],
      ["top", "fitted", "fitted"] + ["fitted"] * len(gt.FITTED_KINDS))
top_texts = [gct.PROMPT_FILES[v].read_text(encoding="utf-8") for v in ("front_plain", "front_decorated", "back")]
fit_texts = [gct.FITTED_PROMPT_FILES[v].read_text(encoding="utf-8") for v in ("front_plain", "front_decorated", "back")]
check("[3] PROMPT_SHA = md5 of the top files", gct.PROMPT_SHA, hashlib.md5("\0".join(top_texts).encode()).hexdigest())
check("[3] fitted sha = md5 of the fitted files", gct.prompt_sha_of("trousers"),
      hashlib.md5("\0".join(fit_texts).encode()).hexdigest())
check("[3] the two differ", gct.prompt_sha_of("trousers") != gct.prompt_sha_of("top"), True)
check("[3] csig differs per family", gct.csig("i", "s", "", gct.prompt_sha_of("bra")) != gct.csig("i", "s", ""), True)


# [4]
def isl(name, bbox, area):
    x0, y0, x1, y1 = bbox
    return {"name": name, "bbox_px": list(bbox), "area_cm2": area,
            "verts_px": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]], "tris": [[0, 1, 2], [0, 2, 3]]}


TROUSERS = {"atlas_px": 2048, "px_per_cm": 14.0, "seams": [],
            "islands": [isl("front_r", (100, 100, 500, 1000), 3000.0), isl("front_l", (600, 100, 1000, 1000), 2900.0),
                        isl("waistband", (100, 1100, 1600, 1160), 600.0)]}
check("[4] trousers", gct.main_words(TROUSERS, "front"),
      {"phrase": "the two largest shapes", "count": 2,
       "names": "the right front leg panel and the left front leg panel"})
BRIEFS = {"atlas_px": 2048, "islands": [isl("front", (100, 100, 500, 500), 400.0), isl("gusset", (900, 100, 950, 300), 30.0)]}
check("[4] briefs", gct.main_words(BRIEFS, "front"), {"phrase": "the top left shape", "count": 1,
                                                      "names": "the front panel"})
BRA = {"atlas_px": 2048, "islands": [isl("cup_r", (100, 100, 500, 300), 210.0), isl("cup_l", (1500, 100, 1900, 300), 200.0),
                                     isl("strap_r", (100, 900, 300, 1800), 300.0)]}
check("[4] bra (a strap larger than a cup)", gct.main_words(BRA, "front")["phrase"],
      "the shapes at the top left and at the top right")

# [5]
check("[5] main front", gct.MAIN_PARTS["front"], ("front", "front_r", "front_l", "leg_r", "leg_l", "cup_r", "cup_l",
                                                  "glove_back_r", "glove_back_l", "skirt_front", "left_front",
                                                  "right_front"))
check("[5] main back", gct.MAIN_PARTS["back"], ("back", "back_l", "back_r", "palm_l", "palm_r", "skirt_back"))
plain = gct.model_parts("front", "plain")
check("[5] plain model parts", [p in plain for p in ("front_l", "cup_top_r", "collar", "waistband", "gusset", "strap_l",
                                                     "thumb_r", "sleeve_l")],
      [True, True, False, False, False, False, False, False])
pic = gct.model_parts("front", "picture")
check("[5] picture adds the trims", all(p in pic for p in ("waistband", "gusset", "strap_l", "thumb_r", "sleeve_l",
                                                           "cuff_r")), True)
check("[5] the neckband is never a trim", "band" in gct.TRIM_PARTS, False)

# [6]
labels = gct.rasterise_islands(TROUSERS, 100)
mask = gct._part_mask(TROUSERS, labels, gct.MAIN_PARTS["front"])
check("[6] main mask px", int(mask.sum()), 19 * 44 + 20 * 44)
wb = labels == gct.island_ids(TROUSERS)["waistband"]
check("[6] waistband px", int(wb.sum()), 73 * 3)
check("[6] no waistband in the main mask", int((mask & wb).sum()), 0)

# [7]
check("[7] kind_has_back", [gct.kind_has_back(p) for p in (
    {"kind": "top"}, {"kind": "trousers"}, {"kind": "briefs"}, {"kind": "gloves"}, {"kind": "bra", "cup_style": "bandeau"},
    {"kind": "tights"}, {"kind": "bra", "cup_style": "molded"}, {"kind": "bra", "cup_style": "balconette"})],
      [True, True, True, True, True, False, False, False])

# [8]
check("[8] a_piece", [gct.a_piece(p) for p in ("elbow-length gloves", "high-leg briefs", "tights", "balconette bra",
                                                "arm warmers", "thong")],
      ["a pair of elbow-length gloves", "a pair of high-leg briefs", "a pair of tights", "a balconette bra",
       "a pair of arm warmers", "a thong"])

# [9]
main = gct.main_words(TROUSERS, "front")
ep = gct.edit_prompt(piece="trousers", side="front", decorated=True, pieces=gct.prompt_pieces(TROUSERS),
                     layout=gct.layout_words(TROUSERS), sleeves=gct.prompt_plain_pieces(TROUSERS), family="fitted",
                     main=main)
ph3 = ep.render("picture_edit")
check("[9] P-H3", ph3.startswith("Edit <Picture 1>. In <Picture 1>, the two largest shapes are the right front leg "
                                 "panel and the left front leg panel of the trousers in <Picture 2>, laid flat. Paint "
                                 "them as in <Picture 2>:"), True)
sub = ep.render("picture_subject")
check("[9] MiniMax", ["<Subject 1>" in sub, "left and right are the wearer's" in sub, "waistband of <Subject 1>" in sub,
                      "a pair of trousers" in sub], [True, True, True, True])
qw = ep.render("image_tag")
check("[9] Qwen", ["<image1>" in qw, "<image2>" in qw, "<Picture" in qw], [True, True, False])
od = ep.render("ordinal")
check("[9] ordinal", ["the first image" in od.lower(), "the second image" in od], [True, True])
check("[9] no <ref", any("<ref" in ep.render(d) for d in ("picture_edit", "picture_subject", "image_tag", "ordinal")),
      False)
GLOVES_BACK = {"atlas_px": 2048, "islands": [isl("palm_l", (100, 100, 500, 900), 600.0),
                                             isl("palm_r", (600, 100, 1000, 900), 600.0)]}
bk = gct.edit_prompt(piece="gloves", side="back", family="fitted", main=gct.main_words(GLOVES_BACK, "back"))
check("[9] back: shapes", bk.render("picture_edit").startswith("Edit <Picture 1>. Texture the shapes in <Picture 1>"),
      True)
GLOVES = {"atlas_px": 2048, "islands": [isl("glove_back_r", (100, 100, 500, 900), 600.0),
                                        isl("glove_back_l", (600, 100, 1000, 900), 600.0),
                                        isl("thumb_r", (100, 1000, 300, 1100), 80.0),
                                        isl("thumb_l", (400, 1000, 600, 1100), 80.0)]}
pl = gct.edit_prompt(piece="gloves", side="front", pieces=gct.prompt_pieces(GLOVES), family="fitted",
                     sleeves=gct.prompt_plain_pieces(GLOVES), main=gct.main_words(GLOVES, "front"))
check("[9] plain: trims joined", "The right thumb and left thumb of <Subject 1>" in pl.render("picture_subject"), True)

# [10]
import numpy as np  # noqa: E402
from app.core import cut_texture_post as ctp  # noqa: E402

red = np.zeros((64, 64, 3), np.uint8)
red[...] = (180, 40, 30)
panel = np.ones((64, 64), bool)
dark = [round(float(v), 2) for v in ctp.srgb_to_lab(np.array([[19.0, 8.0, 3.0]]))[0]]
g_pat, _ = ctp.answer_gates(red, panel, {"lab": dark, "plain": 0.0024}, None)
g_pl, _ = ctp.answer_gates(red, panel, {"lab": dark, "plain": 0.5}, None)
check("[10] all-over pattern: colour gate skipped and ok", (g_pat[0]["ok"], g_pat[0].get("skipped"),
                                                            g_pat[0]["value"] > 20), (True, True, True))
check("[10] plain item: the colour gate fails", g_pl[0]["ok"], False)

print(json.dumps({"fails": FAILS}))
print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL OK")
sys.exit(1 if FAILS else 0)
