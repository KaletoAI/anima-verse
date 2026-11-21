"""Smoke: step 3a — the close-fitting kinds' pattern pieces in the texture-from-cut data (``garment_cut_texture``).

No server, no world DB, no Blender, no image job. Usage: ./.venv/bin/python scripts/smoke_cut_texture_fitted_parts.py

Hand-derived expectations (the job split is ``BACK_PARTS`` = back, back_l, back_r, palm_l, palm_r; everything else
goes with the front job; ``split_islands`` leaves a job without islands out):

[1] Trousers (islands front_l, front_r, back_l, back_r, waistband): front job {front_l, front_r, waistband}, back job
    {back_l, back_r}; ``has_back`` True. Its front pieces in pattern order: "right front leg panel", "left front leg
    panel", "waistband" (the wearer's right first, as the front view shows it at image left).
[2] Tights (leg_l, leg_r, gusset, waistband) and a bra (cup_l, cup_r, cup_top_l, cup_top_r, gore, band_l, band_r,
    strap_l, strap_r): the front job only, ``has_back`` False (no back view is made for them).
[3] Gloves (glove_back_l, glove_back_r, palm_l, palm_r, thumb_l, thumb_r): front {glove_back_l, glove_back_r, thumb_l,
    thumb_r} (the item picture shows the backs of the hands and the thumbs), back {palm_l, palm_r}.
[4] ``piece_name_of``: briefs leg_cut 1.5 -> "high-leg briefs"; back_coverage 0.1 -> "thong"; sides string -> "string
    briefs"; leg_length_m 0.1 -> "boxer briefs"; gloves elbow / full -> "elbow-length gloves"; fingers none -> "arm
    warmers"; tights knee_high -> "knee-high socks"; trousers capri -> "capri trousers", skinny + stirrup hem ->
    "stirrup leggings"; a bra balconette -> "balconette bra"; a top with short sleeves still "T-shirt".
[5] Every part of ``uv_pattern.PARTS`` from 8 on (the cuffs and the fitted pieces 10..36) has a prompt name and a
    sheet label (no part is spoken as its raw id).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app" / "blender" / "scripts"))

from app.core import garment_cut_texture as gct  # noqa: E402
import uv_pattern as up  # noqa: E402

FAILS = []


def check(label, ok, detail=""):
    print(("OK   " if ok else "FAIL ") + label + (f"  ({detail})" if not ok and detail != "" else ""))
    if not ok:
        FAILS.append(label)


def payload(names):
    return {"atlas_px": 2048, "px_per_cm": 14.0, "islands": [{"name": n} for n in names], "seams": []}


def jobs(names):
    sp = gct.split_islands(payload(names))
    return {j: sorted(str(i["name"]) for i in p["islands"]) for j, p in sp.items()}


# [1] trousers
tr = ["front_l", "front_r", "back_l", "back_r", "waistband"]
check("[1] trousers: front {front_l, front_r, waistband}, back {back_l, back_r}",
      jobs(tr) == {"front": ["front_l", "front_r", "waistband"], "back": ["back_l", "back_r"]}, jobs(tr))
check("[1] trousers have a back job", gct.has_back(payload(tr)))
fr = gct.split_islands(payload(tr))["front"]
check("[1] front pieces in pattern order", gct.prompt_pieces(fr) == ["right front leg panel", "left front leg panel",
                                                                     "waistband"], gct.prompt_pieces(fr))

# [2] tights, bra
for nm, names in (("tights", ["leg_l", "leg_r", "gusset", "waistband"]),
                  ("bra", ["cup_l", "cup_r", "cup_top_l", "cup_top_r", "gore", "band_l", "band_r", "strap_l",
                           "strap_r"])):
    check(f"[2] {nm}: the front job only", list(jobs(names)) == ["front"], jobs(names))
    check(f"[2] {nm}: no back job", not gct.has_back(payload(names)))

# [3] gloves
gl = ["glove_back_l", "glove_back_r", "palm_l", "palm_r", "thumb_l", "thumb_r"]
check("[3] gloves: front backs + thumbs, back palms",
      jobs(gl) == {"front": ["glove_back_l", "glove_back_r", "thumb_l", "thumb_r"], "back": ["palm_l", "palm_r"]},
      jobs(gl))

# [4] piece names
for params, want in (({"kind": "briefs", "leg_cut": 1.5}, "high-leg briefs"),
                     ({"kind": "briefs", "back_coverage": 0.1}, "thong"),
                     ({"kind": "briefs", "sides": "string"}, "string briefs"),
                     ({"kind": "briefs", "leg_length_m": 0.1}, "boxer briefs"),
                     ({"kind": "briefs"}, "briefs"),
                     ({"kind": "gloves", "length": "elbow", "fingers": "full"}, "elbow-length gloves"),
                     ({"kind": "gloves", "fingers": "none"}, "arm warmers"),
                     ({"kind": "tights", "tights_style": "knee_high"}, "knee-high socks"),
                     ({"kind": "trousers", "trouser_length": "capri"}, "capri trousers"),
                     ({"kind": "trousers", "leg_shape": "skinny", "hem": "stirrup"}, "stirrup leggings"),
                     ({"kind": "bra", "cup_style": "balconette"}, "balconette bra"),
                     ({"kind": "top", "sleeves": "short"}, "T-shirt")):
    got = gct.piece_name_of(params)
    check(f"[4] {params} -> {want}", got == want, got)

# [5] names and labels
missing = [n for i, n in sorted(up.PARTS.items()) if i >= 8
           and (n not in gct.PROMPT_PIECE_NAMES or n not in gct.PART_LABELS)]
check("[5] every cuff / fitted part has a prompt name and a label", not missing, missing)

print(f"\n{len(FAILS)} FAILED: {FAILS}" if FAILS else "\nALL OK")
sys.exit(1 if FAILS else 0)
