"""Smoke: owner rulings 2 and 3 of round 2026-11-25 for a top with cups (``garment_template.cupped_top``).

Usage: ./.venv/bin/python scripts/smoke_top_cups_cover.py   (no server; a temp storage dir, no world data)

Hand-derived (``garment_set.LAYER_STACKS``: underwear_top < top < outer; ``TOP_HIP_REACH_M`` 0.32).
Items: BR template bra (underwear_top), CT template top with cups ("bra") 0.45 m long (top), PT template top without
cups 0.45 m long and P3 0.30 m long (top, both sleeveless: a sleeve adds the arm), JT template jacket (outer), GL template gloves (hands), BQ a second template bra worn on
underwear_top too (a set with two bras only to prove each is named).

[1] ``garment_template.hidden_by_cups`` (ruling 2: a bra under a top with cups is hidden):
    * {BR, CT} -> {BR: CT}: CT is on ``top``, BR on ``underwear_top`` — the stack puts BR under CT, and both touch the
      chest.
    * {BR, PT} -> {}: PT has no cups — a plain top drapes over the bra as before.
    * {BR} -> {}, {CT} -> {}: nothing to hide / nothing hiding.
    * {BR, CT, JT} -> {BR: CT}: the jacket hides nothing (it is no cupped top) and is not hidden.
    * {GL, CT} -> {}: gloves are no bra (and touch no chest).
    * {BR, BQ, CT} -> {BQ: CT, BR: CT}.
[2] ``figure.worn_sets`` with BR on underwear_top and CT on top (pipeline on, stubs below): ``template`` == (CT,) —
    BR is not draped; ``unformed`` == {BR: HIDDEN_BY_CUPS}; BR is not in ``own``. With PT instead of CT: ``template``
    == (BR, PT), nothing unformed.
[3] ``garment_template.body_regions`` (ruling 3: a cupped top never reaches the hip): CT 0.45 m (>= 0.32) ->
    {chest, waist}; PT 0.45 m -> {chest, waist, hip}; PT 0.30 m -> {chest, waist}. Before the ruling (commit
    a240c0382) CT 0.45 m -> {chest, waist, hip} — proved below against that commit's file.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core import paths  # noqa: E402

TMP = tempfile.mkdtemp(prefix="smoke_top_cups_cover_")
paths.init(TMP)

from app.core import base_body, body_slots, figure, garment_hair, garment_set, garment_template  # noqa: E402
from app.models import inventory  # noqa: E402

PRE_FIX = "a240c0382"
FAILS: list = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got}" + ("" if ok else f" — expected {want}"))
    if not ok:
        FAILS.append(label)


def piece(name, slots, kind, **params):
    p = {"slots": list(slots), "covers": [], "partially_covers": [], "mesh_mode": "template",
         "template": {"params": {**garment_template.kind_defaults(kind), "kind": kind, **params}}}
    return {"id": name, "name": name, "category": "outfit_piece", "outfit_piece": p}


ITEMS = {"BR": piece("BR", ["underwear_top"], "bra"), "BQ": piece("BQ", ["underwear_top"], "bra"),
         "CT": piece("CT", ["top"], "top", cups="bra", length_m=0.45),
         "PT": piece("PT", ["top"], "top", length_m=0.45, sleeves="none"),
         "P3": piece("P3", ["top"], "top", length_m=0.30, sleeves="none"),
         "JT": piece("JT", ["outer"], "jacket"), "GL": piece("GL", ["hands"], "gloves")}
inventory.get_item = lambda item_id, *a, **k: ITEMS.get(str(item_id))
body_slots.piece_slots_for_character = lambda *a, **k: list(inventory.VALID_PIECE_SLOTS)

# [1]
H = garment_template.hidden_by_cups
check("[1] {BR, CT}", H(["BR", "CT"]), {"BR": "CT"})
check("[1] {BR, PT}", H(["BR", "PT"]), {})
check("[1] {BR}", H(["BR"]), {})
check("[1] {CT}", H(["CT"]), {})
check("[1] {BR, CT, JT}", H(["BR", "CT", "JT"]), {"BR": "CT"})
check("[1] {GL, CT}", H(["GL", "CT"]), {})
check("[1] {BR, BQ, CT}", H(["BR", "BQ", "CT"]), {"BQ": "CT", "BR": "CT"})

# [2] — the pipeline on, no own-mesh garments, no hair
garment_set.worn_garments = lambda *a, **k: []
base_body.is_base_pipeline = lambda *a, **k: True
garment_hair.hair_mode = lambda *a, **k: ""
garment_hair.shape_hair = lambda *a, **k: ""
garment_hair.hair_style_id = lambda *a, **k: ""
s = figure.worn_sets("c", pieces={"underwear_top": "BR", "top": "CT"}, profile={"name": "c"}, piece_state={})
check("[2] template with CT", s.template, ("CT",))
check("[2] unformed with CT", s.unformed, {"BR": garment_template.HIDDEN_BY_CUPS})
check("[2] BR not in own", "BR" in s.own, False)
s = figure.worn_sets("c", pieces={"underwear_top": "BR", "top": "PT"}, profile={"name": "c"}, piece_state={})
check("[2] template with PT", s.template, ("BR", "PT"))
check("[2] unformed with PT", s.unformed, {})

# [3]
R = lambda i: sorted(garment_template.body_regions(garment_template.params_of(ITEMS[i]), ITEMS[i]))  # noqa: E731
check("[3] CT 0.45 m", R("CT"), ["chest", "waist"])
check("[3] PT 0.45 m", R("PT"), ["chest", "hip", "waist"])
check("[3] P3 0.30 m", R("P3"), ["chest", "waist"])

PROBE = r"""
import sys
sys.path.insert(0, sys.argv[1])
from app.core import paths
paths.init(sys.argv[2])
from app.core import garment_template as gt
p = {**gt.kind_defaults("top"), "kind": "top", "cups": "bra", "length_m": 0.45}
print(sorted(gt.body_regions(gt.validate_params(p)[0])))
"""
old = Path(tempfile.mkdtemp(prefix="smoke_top_cups_cover_old_"))
res = subprocess.run(["git", "-C", str(ROOT), "archive", PRE_FIX, "app"], capture_output=True)
if res.returncode != 0:
    print(f"  SKIP [3] pre-fix proof: commit {PRE_FIX} not in this repository")
else:
    subprocess.run(["tar", "-x", "-C", str(old)], input=res.stdout, check=True)
    out = subprocess.run([sys.executable, "-c", PROBE, str(old), str(old / "world")], capture_output=True, text=True,
                         cwd=str(old))
    check(f"[3] before the ruling ({PRE_FIX}) CT 0.45 m reached the hip", out.stdout.strip(),
          "['chest', 'hip', 'waist']")

print("FAILED: " + ", ".join(FAILS) if FAILS else "all checks passed")
sys.exit(1 if FAILS else 0)
