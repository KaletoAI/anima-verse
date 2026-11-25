"""Smoke: round 2026-11-25 (A) — a piece is under another only when their body regions overlap
(``garment_template.body_regions`` / ``regions_overlap`` in ``inner_pieces``).

Usage: ./.venv/bin/python scripts/smoke_layer_regions.py   (no server; a temp storage dir, no world data)

Hand-derived from ``garment_set.LAYER_STACKS`` (underwear_top < top < outer; hands < outer; underwear_bottom < legs <
bottom < outer), ``LAYER_RANK`` (bra / briefs / tights 0, gloves / top / skirt / trousers / dress 1, jacket 2) and the
region table (``body_regions``: gloves = hand + arm, bra = chest, briefs = hip, skirt = waist + hip + leg, trousers =
waist + hip + leg + foot, top / jacket = chest + waist, + hip from a hem ``TOP_HIP_REACH_M`` = 0.32 m below the
shoulder line, + arm with sleeves; own-mesh pieces by their slots: feet + legs = foot + leg + hip).

Items (Glut's set): BH template bra (underwear_top), SL template briefs (underwear_bottom), ST own-mesh boots (feet +
legs = clothing, not footwear: a multi-slot piece with feet), GO template gloves worn on ``outer`` (as Glut's are),
GH the same gloves on ``hands``. Others: JL template jacket with long sleeves (outer), JV template jacket without
sleeves (a vest, outer), TC template top length 0.27 (Lirien's crop top, top), TL template top length 0.6 (top),
SK template skirt (bottom), TR template trousers (bottom).

[1] GO on outer, set {BH, SL, ST, GO}: the stacks put GO over BH (outer over underwear_top), over SL and ST (outer
    over underwear_bottom / legs), and by rank over BH and SL (1 > 0). No region overlaps (hand + arm against chest,
    hip, foot + leg + hip) -> ([], []). At f70077f3c: templates [BH, SL], own [ST] (the diagnosis' dry run).
[2] GH on hands, same set: the stacks put nothing under it, rank still puts BH and SL -> now ([], []); at f70077f3c
    templates [BH, SL] (by rank alone).
[3] ``key_for(GO)`` with BH's ``cup_style`` changed molded -> balconette, and SL's ``rise`` mid -> high: unchanged
    (no under tokens, so no ``cut:body`` either). At f70077f3c it changes (BH's tsig is in GO's key).
[4] A223: JL over GH (outer over hands, hand + arm against chest + waist + hip + arm: arm) -> templates [GH].
    JV (no sleeves: chest + waist + hip) over GH -> [] (a vest never touches a glove).
[5] A237-like: TR over ST (bottom over legs; foot + leg overlap) -> own [ST]; TR over BH (rank 1 > 0, chest against
    waist + hip + leg + foot) -> not there.
[6] A jacket over a top: JL over TL (outer over top, chest) -> templates [TL]; ``key_for(JL)`` changes when TL's
    ``neckline`` changes crew -> v (TL's tsig is in JL's key).
[7] SK over BH (rank 1 > 0; waist + hip + leg against chest) -> []; SK over SL (bottom over underwear_bottom, hip)
    -> [SL]. TC (0.27 m: chest + waist) over SL -> []; TL (0.6 m: + hip) over SL -> [SL]; TC over BH (top over
    underwear_top, chest) -> [BH].
"""
from __future__ import annotations

import copy
import subprocess
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core import paths  # noqa: E402

TMP = tempfile.mkdtemp(prefix="smoke_layer_regions_")
paths.init(TMP)

from app.core import body_slots, garment_store, garment_template  # noqa: E402
from app.models import inventory  # noqa: E402

PRE_FIX = "f70077f3c"
FAILS: list = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got}" + ("" if ok else f" — expected {want}"))
    if not ok:
        FAILS.append(label)


def piece(name, slots, mode, kind=None, **params):
    p = {"slots": list(slots), "covers": [], "partially_covers": [], "mesh_mode": mode}
    if kind:
        p["template"] = {"params": {**garment_template.kind_defaults(kind), "kind": kind, **params}}
    return {"id": name, "name": name, "category": "outfit_piece", "outfit_piece": p}


ITEMS = {
    "BH": piece("BH", ["underwear_top"], "template", "bra"),
    "SL": piece("SL", ["underwear_bottom"], "template", "briefs"),
    "ST": piece("ST", ["feet", "legs"], "own_mesh"),
    "GO": piece("GO", ["outer"], "template", "gloves", length="opera"),
    "GH": piece("GH", ["hands"], "template", "gloves", length="opera"),
    "JL": piece("JL", ["outer"], "template", "jacket", sleeves="long"),
    "JV": piece("JV", ["outer"], "template", "jacket", sleeves="none"),
    "TC": piece("TC", ["top"], "template", "top", length_m=0.27, shoulders="straps", sleeves="none",
                neckline="sweetheart"),
    "TL": piece("TL", ["top"], "template", "top", length_m=0.6),
    "SK": piece("SK", ["bottom"], "template", "skirt"),
    "TR": piece("TR", ["bottom"], "template", "trousers"),
}
inventory.get_item = lambda item_id, *a, **k: ITEMS.get(str(item_id))
body_slots.piece_slots_for_character = lambda *a, **k: list(inventory.VALID_PIECE_SLOTS)
pic = Path(TMP) / "pic.png"
pic.write_bytes(b"picture")
garment_template.texture_sources = lambda c, i: {"front": str(pic), "back": str(pic), "source": "cutout"}
garment_store.accepted_fit = lambda *a, **k: None


def ids(pairs):
    return [i for i, _it in pairs]


def inner(mod, item_id, worn):
    kind = garment_template.params_of(ITEMS[item_id])["kind"]
    t, o = mod.inner_pieces(item_id, kind, sorted(worn))
    return ids(t), ids(o)


def old_module(rel, name):
    src = subprocess.run(["git", "-C", str(ROOT), "show", f"{PRE_FIX}:{rel}"], capture_output=True, text=True)
    if src.returncode:
        return None
    mod = types.ModuleType(name)
    mod.__file__ = str(ROOT / rel)
    exec(compile(src.stdout, rel, "exec"), mod.__dict__)
    return mod


GLUT = ["BH", "SL", "ST", "GO"]
GLUT_H = ["BH", "SL", "ST", "GH"]
gt = garment_template

# [1] / [2]
check("[1] GO on outer over Glut's set", inner(gt, "GO", GLUT), ([], []))
check("[2] GH on hands over Glut's set", inner(gt, "GH", GLUT_H), ([], []))


# [3]
def key(mod, item_id, worn):
    mod.texture_sources = garment_template.texture_sources
    return mod.key_for("c", item_id, base_sha="base", lower=sorted(worn))[0]


k1, b1 = key(gt, "GO", GLUT), key(gt, "BH", GLUT)
saved = copy.deepcopy(ITEMS)
ITEMS["BH"]["outfit_piece"]["template"]["params"]["cup_style"] = "balconette"
ITEMS["SL"]["outfit_piece"]["template"]["params"]["rise"] = "high"
k2, b2 = key(gt, "GO", GLUT), key(gt, "BH", GLUT)
ITEMS.update(copy.deepcopy(saved))
check("[3] the bra's own key changes", b1 != b2, True)
check("[3] changing the bra and briefs leaves the gloves' key unchanged", k1 == k2 and k1 is not None, True)
check("[3] no under tokens for the gloves", gt.under_tokens("c", "GO", gt.params_of(ITEMS["GO"]), base_sha="base",
                                                             lower=sorted(GLUT)), [])

# [4]
check("[4] A223: JL (long sleeves) over GH", inner(gt, "JL", ["JL", "GH"]), (["GH"], []))
check("[4] JV (no sleeves) over GH", inner(gt, "JV", ["JV", "GH"]), ([], []))

# [5]
check("[5] A237-like: TR over the boots", inner(gt, "TR", ["TR", "ST"]), ([], ["ST"]))
check("[5] TR never over the bra", inner(gt, "TR", ["TR", "BH"]), ([], []))

# [6]
check("[6] JL over TL", inner(gt, "JL", ["JL", "TL"]), (["TL"], []))
j1 = key(gt, "JL", ["JL", "TL"])
ITEMS["TL"]["outfit_piece"]["template"]["params"]["neckline"] = "v"
j2 = key(gt, "JL", ["JL", "TL"])
ITEMS.update(copy.deepcopy(saved))
check("[6] a changed top re-drapes the jacket over it", j1 != j2 and None not in (j1, j2), True)

# [7]
check("[7] SK over BH", inner(gt, "SK", ["SK", "BH"]), ([], []))
check("[7] SK over SL", inner(gt, "SK", ["SK", "SL"]), (["SL"], []))
check("[7] TC (0.27 m) over SL", inner(gt, "TC", ["TC", "SL"]), ([], []))
check("[7] TL (0.6 m) over SL", inner(gt, "TL", ["TL", "SL"]), (["SL"], []))
check("[7] TC over BH", inner(gt, "TC", ["TC", "BH"]), (["BH"], []))

# the old code, pinned
old = old_module("app/core/garment_template.py", "old_garment_template")
if old is not None:
    check(f"[1] {PRE_FIX}: GO over BH, SL and the boots", inner(old, "GO", GLUT), (["BH", "SL"], ["ST"]))
    check(f"[2] {PRE_FIX}: GH over BH and SL by rank", inner(old, "GH", GLUT_H), (["BH", "SL"], []))
    o1 = key(old, "GO", GLUT)
    ITEMS["BH"]["outfit_piece"]["template"]["params"]["cup_style"] = "balconette"
    o2 = key(old, "GO", GLUT)
    ITEMS.update(copy.deepcopy(saved))
    check(f"[3] {PRE_FIX}: a changed bra re-keyed the gloves", o1 != o2, True)
    check(f"[7] {PRE_FIX}: SK over BH by rank", inner(old, "SK", ["SK", "BH"]), (["BH"], []))
else:
    print(f"  (skip: {PRE_FIX} not in this checkout)")

print("all passed" if not FAILS else f"FAILED: {len(FAILS)}")
sys.exit(1 if FAILS else 0)
