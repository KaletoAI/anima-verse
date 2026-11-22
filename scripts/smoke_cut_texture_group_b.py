#!/usr/bin/env python3
"""Smoke: texture from cut, group B phase A — skirts and the strapless top (plan
``docs/superpowers/plans/2026-11-22-schnitt-gruppe-b.md``).

Usage:
    ./.venv/bin/python scripts/smoke_cut_texture_group_b.py

No server, no world DB (a throwaway ``paths.init``), no Blender, no hub job. Every expectation is derived by hand:

[1] Piece names (``piece_name_of``, A4): a skirt by flare and length — flare >= 0.6 "circle skirt", flare <= 0.1 and
    length <= 0.45 "pencil skirt", flare <= 0.1 longer "straight skirt", else "A-line skirt"; length >= 0.75 puts
    "long " in front (never before "pencil skirt"); a slit does not change it. The world's skirts: Kira (0.34 / 0.0)
    "pencil skirt", Gelina (0.76 / 0.68) "long circle skirt", Tilda (0.80 / 0.30) "long A-line skirt", Ylva (0.69 /
    0.0) "straight skirt", Rosi (0.23 / 0.0) "pencil skirt". A strapless top with a sweetheart or straight edge and
    fit <= 0.2 is a "corset top" (Rosi: sweetheart, fit 0.0), with fit 0.4 a "strapless top"; a covered top keeps
    its sleeve name ("T-shirt" for short sleeves).
[2] Jobs and parts: ``job_of("skirt_back")`` is "back", ``job_of("skirt_front")`` / ``job_of("waistband")`` "front";
    ``kind_has_back`` of a skirt and of a strapless top True (back panels exist before the cut).
[3] Families: ``prompt_family`` of "skirt" and "strapless" is "fitted" (``prompt_sha_of`` = the fitted family's sha),
    of "top" "top" — a top's atlases keep their csig (``PROMPT_SHA`` unchanged).
[4] A skirt payload laid out as Kira's real cut (2048 px): skirt_front bbox [238, 38, 1547, 920], skirt_back
    [84, 958, 1701, 1935], waistband [38, 1973, 1747, 2010]. ``split_islands`` puts skirt_front + waistband into the
    front job and skirt_back alone into the back job. The front job's main island is skirt_front alone; its bbox
    centre (892.5 / 2048, 479 / 2048) = (0.436, 0.234): the middle third across, the top third down -> alone in "at
    the top centre" -> ``main_words`` {"phrase": "the top centre shape", "count": 1, "names": "the front skirt panel"};
    the plain pieces kept plain: ["waistband"]. The decorated FRONT prompt in P-H3 begins "Edit <Picture 1>. In
    <Picture 1>, the top centre shape is the front skirt panel of the pencil skirt in <Picture 2>, laid flat. Paint it
    as in <Picture 2>:"; MiniMax names "waistband, front skirt panel" as the pieces (pattern order: ``PROMPT_PIECE_NAMES``
    lists the waistband before the step 3b parts) and "The waistband of <Subject 1>";
    no dialect carries ``<ref``. The back job's main is skirt_back: names "the back skirt panel".
[5] Held trims (live test 2026-11-22, Tilda): ``held_trims`` True for "skirt" / "strapless", False with
    ``sleeve_print`` "picture" and for "top" / "trousers" (their tested templates stay). On a 400 px payload at 10
    px/cm — skirt_front [40, 20, 240, 220], skirt_back [260, 20, 380, 220], waistband [20, 300, 380, 310] —
    ``sent_islands(.., "front")`` keeps all three names (the label ids are the sorted names: back 1, front 2,
    waistband 3) and empties the waistband; with ``drop`` the front job says only skirt_front. The held front frame
    is the skirt_front box alone: w = h = 200, side = ceil(200 * 1.24) = 248, ox = floor(140 - 124) = 16, oy =
    floor(120 - 124) = -4 (k = 400 / 248); without ``zoom_front`` the front has none. A flat green answer painted
    on that zoomed panel posts "ready" through ``post_job(held=True)``: the gates saw island 2 alone (``islands`` keys
    ["2"]), ``fabric_fill`` filled ["waistband"], and every waistband pixel of the atlas-frame image is the green
    (each channel within 3 of (19, 50, 29)) — the trim never sent, still painted.
"""
import io
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TEMP = tempfile.TemporaryDirectory(prefix="smoke-cut-group-b-")
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


def skirt(length, flare, **kw):
    return gt.validate_params({"kind": "skirt", "length_m": length, "flare": flare, **kw})[0]


# [1]
check("[1] Kira", gct.piece_name_of(skirt(0.34, 0.0, slit="front_left", slit_m=0.06)), "pencil skirt")
check("[1] Gelina", gct.piece_name_of(skirt(0.76, 0.68)), "long circle skirt")
check("[1] Tilda", gct.piece_name_of(skirt(0.80, 0.30)), "long A-line skirt")
check("[1] Ylva", gct.piece_name_of(skirt(0.69, 0.0)), "straight skirt")
check("[1] Rosi", gct.piece_name_of(skirt(0.23, 0.0)), "pencil skirt")
corset = gt.validate_params({"kind": "top", "shoulders": "strapless", "neckline": "sweetheart", "fit": 0.0})[0]
check("[1] Rosi's corset", gct.piece_name_of(corset), "corset top")
check("[1] a loose strapless top", gct.piece_name_of({**corset, "fit": 0.4}), "strapless top")
check("[1] a covered top", gct.piece_name_of(gt.validate_params({"kind": "top", "shoulders": "covered",
                                                                 "sleeves": "short"})[0]), "T-shirt")

# [2]
check("[2] jobs", [gct.job_of(n) for n in ("skirt_back", "skirt_front", "waistband")], ["back", "front", "front"])
check("[2] kind_has_back", [gct.kind_has_back(skirt(0.5, 0.3)), gct.kind_has_back(corset)], [True, True])

# [3]
check("[3] families", [gct.prompt_family(k) for k in ("skirt", "strapless", "top")], ["fitted", "fitted", "top"])
check("[3] shas", [gct.prompt_sha_of("skirt") == gct.PROMPT_SHAS["fitted"], gct.prompt_sha_of("top") == gct.PROMPT_SHA],
      [True, True])


# [4]
def isl(name, bbox, area):
    x0, y0, x1, y1 = bbox
    return {"name": name, "bbox_px": list(bbox), "area_cm2": area,
            "verts_px": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]], "tris": [[0, 1, 2], [0, 2, 3]]}


SKIRT = {"atlas_px": 2048, "px_per_cm": 24.56, "seams": [],
         "islands": [isl("skirt_front", (238, 38, 1547, 920), 1539.0), isl("skirt_back", (84, 958, 1701, 1935), 1902.0),
                     isl("waistband", (38, 1973, 1747, 2010), 100.0)]}
jobs = gct.split_islands(SKIRT)
check("[4] jobs", {j: sorted(i["name"] for i in jobs[j]["islands"]) for j in jobs},
      {"front": ["skirt_front", "waistband"], "back": ["skirt_back"]})
main = gct.main_words(jobs["front"], "front")
check("[4] front main", main, {"phrase": "the top centre shape", "count": 1, "names": "the front skirt panel"})
plain = gct.prompt_plain_pieces(jobs["front"])
check("[4] plain pieces", plain, ["waistband"])
ep = gct.edit_prompt(piece="pencil skirt", side="front", decorated=True, pieces=gct.prompt_pieces(jobs["front"]),
                     layout=gct.layout_words(jobs["front"], "fitted"), sleeves=plain, family="fitted", main=main)
check("[4] P-H3", ep.render("picture_edit").startswith(
    "Edit <Picture 1>. In <Picture 1>, the top centre shape is the front skirt panel of the pencil skirt in "
    "<Picture 2>, laid flat. Paint it as in <Picture 2>:"), True)
sub = ep.render("picture_subject")
check("[4] MiniMax", ["waistband, front skirt panel" in sub, "The waistband of <Subject 1>" in sub], [True, True])
check("[4] no <ref", any("<ref" in ep.render(d) for d in ("picture_edit", "picture_subject", "image_tag", "ordinal")),
      False)
check("[4] back main", gct.main_words(jobs["back"], "back")["names"], "the back skirt panel")

# [5]
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from app.core import cut_texture_post as post  # noqa: E402

check("[5] held_trims", [gct.held_trims("skirt"), gct.held_trims("strapless"), gct.held_trims("skirt", "picture"),
                         gct.held_trims("top"), gct.held_trims("trousers")], [True, True, False, False, False])


def box(name, x0, y0, x1, y1):
    return {"name": name, "verts_px": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]], "tris": [[0, 1, 2], [0, 2, 3]],
            "bbox_px": [x0, y0, x1, y1]}


PAY = {"atlas_px": 400, "px_per_cm": 10.0, "seams": [],
       "islands": [box("skirt_front", 40, 20, 240, 220), box("skirt_back", 260, 20, 380, 220),
                   box("waistband", 20, 300, 380, 310)]}
sent = gct.sent_islands(PAY, "front")
check("[5] ids kept", gct.island_ids(sent), {"skirt_back": 1, "skirt_front": 2, "waistband": 3})
check("[5] waistband emptied", [i["verts_px"] for i in sent["islands"] if i["name"] == "waistband"], [[]])
check("[5] drop", [i["name"] for i in gct.split_islands(gct.sent_islands(PAY, "front", drop=True))["front"]["islands"]],
      ["skirt_front"])
frame = gct.job_frame(sent, "front", 400, zoom_front=True)
check("[5] frame", {k: frame[k] for k in ("ox", "oy", "side")}, {"ox": 16, "oy": -4, "side": 248})
check("[5] no front frame without zoom_front", gct.job_frame(sent, "front", 400), None)
zl = gct.rasterise_islands(gct.zoom_payload(sent, "front", frame, 400), 400)
ans = np.full((400, 400, 3), 255, np.uint8)
ans[zl == 2] = (19, 50, 29)
buf = io.BytesIO()
Image.fromarray(ans).save(buf, format="PNG")
green = post.fabric_colour(ans, zl == 2)
refs = {"colour": green, "detail": {"front": 0.2}, "fabric": ans[zl == 2].astype(float)}
res = gct.post_job(buf.getvalue(), PAY, 400, 10.0, "front", refs, held=True)
check("[5] ready", (res["state"], res["reason"]), ("ready", ""))
if res["state"] == "ready":
    check("[5] gates saw the panel alone", sorted(res["metrics"]["islands"]), ["2"])
    check("[5] waistband filled", res["metrics"]["fabric_fill"].get("islands"), ["waistband"])
    wb = gct.rasterise_islands(PAY, 400) == 3
    dev = np.abs(res["_image"][wb].astype(int) - np.array([19, 50, 29])).max()
    check("[5] waistband pixels are the green", bool(dev <= 3), True)

print()
print("ALL OK" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}")
sys.exit(1 if FAILS else 0)
