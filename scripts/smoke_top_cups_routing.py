"""Round 2026-11-25 (plan "cups in a top", task 2): every build decision reads the one switch
``garment_template.build_kind`` — a top with cups (``cups`` "bra") is routed through the bra build everywhere, every
other piece exactly as before. Pure functions on a synthetic body (the measure ``M`` of
``scripts/smoke_garment_template_fitted.py``), no server, no world DB, no Blender.

The table (derived by hand from the predicates; "D" = the corset top with straps of r25garm D, ``corset_straps``):

| case                        | build_kind | has_bodice | corset_top | panel_piece | corset_straps | fitted in tsig | measured_poses           | shape_groups | prompt_kind |
|-----------------------------|------------|------------|------------|-------------|---------------|----------------|--------------------------|--------------|-------------|
| top covered, short sleeves  | top        | True       | False      | False       | False         | no             | MEASURED_UPPER_POSES     | 2 arm groups | top         |
| top straps + sweetheart (D) | top        | False      | True       | True        | True          | no             | MEASURED_POSES           | []           | strapless   |
| top strapless               | top        | False      | True       | True        | False         | no             | MEASURED_POSES           | []           | strapless   |
| top with cups bra           | bra        | False      | False      | False       | False         | yes            | FITTED_POSES["bra"]      | []           | bra         |
| bra                         | bra        | False      | False      | False       | False         | yes            | FITTED_POSES["bra"]      | []           | bra         |
| dress with straps           | dress      | True       | False      | True        | False         | no             | MEASURED_POSES + arms    | legs + 2 arm | dress       |

(the cupped top is stored with ``shoulders`` straps and ``neckline`` sweetheart, parked: it must NOT read as the D
corset — ``validate_params`` puts the parked fields to their defaults and every predicate reads ``build_kind``.)

Also, for the cupped top on ``M``:
- ``panel_spec(...)["fitted"]["kind"] == "bra"`` (the fitted branch, built as a bra);
- ``build_args(...)``: "kind" "bra", "frames" == ``FITTED_FRAMES`` (15, from the fitted spec), no ``shell_clear_m``
  (not a corset shell), no ``straight_straps``, no ``neck_rules``;
- the cut key's payload carries ``fitted`` and ``fitted_pattern`` (its cut follows the fitted part rules) and no
  ``corset`` / ``corset_straps``; ``uv_pattern_key == UV_PATTERN_SHA``;
- ``garment_cut_texture.prompt_family("bra") == "fitted"``; ``kind_has_back`` False for balconette cups (a cupped
  bra has no back job, D4) and True for a bandeau;
- the piece name: length 0.30 < ``CUPPED_BUSTIER_LENGTH_M`` 0.375 -> "balconette crop top"; 0.40 -> "balconette
  bustier top"; triangle -> "triangle-cup crop top";
- ``template_lines``: the cups line is said for the cupped top; a top without cups gives the same lines as at
  d0bae1f34 (no line for "none").
- ``body_regions`` of the cupped top stays a top's (chest, waist; the kind is the piece's, ``LAYER_RANK`` 1).

Lint (review focus 2): ``git grep`` in ``app/core`` for ``["kind"] in FITTED_KINDS`` / ``get("kind") in
(gt.)FITTED_KINDS`` finds 0 lines — every such decision reads ``build_kind``.

Usage: ./.venv/bin/python scripts/smoke_top_cups_routing.py
"""
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_SCRATCH = Path(tempfile.mkdtemp(prefix="smoke-top-cups-routing-"))
from app.core import paths  # noqa: E402
paths.init(_SCRATCH / "world")
paths.init_instance(_SCRATCH / "instance")

from app.core import garment_template as gt  # noqa: E402
from app.core import garment_template_cut as gtc  # noqa: E402
from app.core import garment_cut_texture as gct  # noqa: E402
from app.core import garment_template_views as gtv  # noqa: E402

FAILS = []


def check(label, ok, detail=""):
    print(("OK   " if ok else "FAIL ") + label + (f"  ({detail})" if not ok and detail != "" else ""))
    if not ok:
        FAILS.append(label)


M = {"height": 1.70, "floor_y": 0.0, "waist_y": 1.05, "waist_c": 0.70, "hip_y": 0.90, "hip_c": 0.96,
     "band_y": 1.275, "band_c": 0.86, "shoulder_y": 1.40, "shoulder_w": 0.40, "neck_y": 1.47, "neck_c": 0.33,
     "arm_len": 0.50, "arm_c": [[0.05, 0.30], [0.97, 0.16]], "upper_arm_c": 0.28, "wrist_c": 0.16,
     "torso": [[round(0.68 + 0.02 * i, 3), 0.80 + (0.10 if 1.18 <= 0.68 + 0.02 * i <= 1.22 else 0.0)]
               for i in range(37)],
     "joints": {"leftarm": [0.16, 1.40, 0.0], "rightarm": [-0.16, 1.40, 0.0], "leftforearm": [0.41, 1.40, 0.0],
                "rightforearm": [-0.41, 1.40, 0.0], "lefthand": [0.66, 1.40, 0.0], "righthand": [-0.66, 1.40, 0.0],
                "neck": [0.0, 1.47, 0.0], "spine2": [0.0, 1.25, 0.0], "leftupleg": [0.09, 0.86, 0.0]}}

V = lambda **kw: gt.validate_params(kw)[0]  # noqa: E731
CASES = {
    "top covered": V(kind="top", shoulders="covered", sleeves="short", length_m=0.5),
    "top straps (D)": V(kind="top", shoulders="straps", neckline="sweetheart", length_m=0.27),
    "top strapless": V(kind="top", shoulders="strapless", neckline="straight", length_m=0.45),
    "top cups bra": V(kind="top", cups="bra", cup_style="balconette", shoulders="straps", neckline="sweetheart",
                      length_m=0.30, straps="wide", center_gore="wide", closure="none", push_up=0.8,
                      cup_coverage=0.6),
    "bra": V(kind="bra", cup_style="balconette", straps="wide"),
    "dress straps": V(kind="dress", shoulders="straps", length_m=0.6),
}
DRESS_POSES = (*gt.MEASURED_POSES, "arms_down", "arms_up")
TABLE = {  # build_kind, has_bodice, corset_top, panel_piece, corset_straps, fitted, poses, groups, prompt
    "top covered": ("top", True, False, False, False, False, gt.MEASURED_UPPER_POSES, ["arm_l", "arm_r"], "top"),
    "top straps (D)": ("top", False, True, True, True, False, gt.MEASURED_POSES, [], "strapless"),
    "top strapless": ("top", False, True, True, False, False, gt.MEASURED_POSES, [], "strapless"),
    "top cups bra": ("bra", False, False, False, False, True, gt.FITTED_POSES["bra"], [], "bra"),
    "bra": ("bra", False, False, False, False, True, gt.FITTED_POSES["bra"], [], "bra"),
    "dress straps": ("dress", True, False, True, False, False, DRESS_POSES, ["legs", "arm_l", "arm_r"], "dress"),
}


def tsig_payload_has_fitted(p):
    """Whether ``tsig`` carries the fitted version: the key with FITTED_VERSION changed differs."""
    a = gt.tsig(p, base_sha="b", texture_sha="t", lower=[])
    old = gt.FITTED_VERSION
    gt.FITTED_VERSION = old + 1000
    try:
        b = gt.tsig(p, base_sha="b", texture_sha="t", lower=[])
    finally:
        gt.FITTED_VERSION = old
    return a != b


for name, p in CASES.items():
    want = TABLE[name]
    got = (gt.build_kind(p), gt.has_bodice(p), gt.corset_top(p), gt.panel_piece(p), gt.corset_straps(p),
           tsig_payload_has_fitted(p), tuple(gt.measured_poses(p)), [g["name"] for g in gt.shape_groups(p)],
           gct.prompt_kind(p))
    labels = ("build_kind", "has_bodice", "corset_top", "panel_piece", "corset_straps", "fitted in tsig",
              "measured_poses", "shape_groups", "prompt_kind")
    for lab, g, w in zip(labels, got, want):
        check(f"[table] {name}: {lab}", (tuple(g) if isinstance(g, (list, tuple)) and lab == "measured_poses"
                                         else g) == (tuple(w) if lab == "measured_poses" else w), (g, w))

cup = CASES["top cups bra"]
spec = gt.panel_spec(cup, M)
check("[spec] panel_spec of a cupped top is the bra's fitted spec", (spec.get("fitted") or {}).get("kind") == "bra",
      spec.get("fitted"))
args = gt.build_args(cup, spec, item_id="item_x")
check("[args] kind bra, frames FITTED_FRAMES, no shell / straight straps / neck rules",
      args["kind"] == "bra" and args["frames"] == gt.FITTED_FRAMES and "shell_clear_m" not in args
      and "straight_straps" not in args and "neck_rules" not in args,
      {k: args.get(k) for k in ("kind", "frames", "shell_clear_m", "straight_straps", "neck_rules")})


def cut_payload_keys(p):
    """The optional parts of the cut key: each one's constant bumped changes the key."""
    base = gtc.cut_sig(p, base_sha="b", lower=[])
    out = set()
    for mod, attr, part in ((gt, "FITTED_VERSION", "fitted"), (gtc, "FITTED_PATTERN_SHA", "fitted_pattern"),
                            (gt, "CORSET_VERSION", "corset"), (gt, "CORSET_STRAPS_VERSION", "corset_straps"),
                            (gt, "PANEL_VERSION", "panels")):
        old = getattr(mod, attr)
        setattr(mod, attr, (old + 1000) if isinstance(old, int) else old + "x")
        try:
            if gtc.cut_sig(p, base_sha="b", lower=[]) != base:
                out.add(part)
        finally:
            setattr(mod, attr, old)
    return out


parts = cut_payload_keys(cup)
check("[cut] the cut key carries fitted + fitted_pattern, no corset / panels", parts == {"fitted", "fitted_pattern"},
      sorted(parts))
check("[cut] uv_pattern_key is the live uv_pattern.py", gtc.uv_pattern_key(cup) == gtc.UV_PATTERN_SHA)
check("[cut] prompt family of bra is fitted", gct.prompt_family("bra") == "fitted")
check("[cut] balconette cups: no back job; bandeau: a back job",
      gct.kind_has_back(cup) is False and gct.kind_has_back(V(kind="top", cups="bra", cup_style="bandeau")) is True)

check("[name] 0.30 balconette -> crop top", gct.piece_name_of(cup) == "balconette crop top", gct.piece_name_of(cup))
longer = V(kind="top", cups="bra", cup_style="balconette", length_m=0.40)
check("[name] 0.40 balconette -> bustier top", gct.piece_name_of(longer) == "balconette bustier top",
      gct.piece_name_of(longer))
tri = V(kind="top", cups="bra", cup_style="triangle", length_m=0.30)
check("[name] triangle -> triangle-cup crop top", gct.piece_name_of(tri) == "triangle-cup crop top",
      gct.piece_name_of(tri))

lines = gtv.template_lines(cup)
check("[lines] the cups line is said", gtv.TEMPLATE_LINES["cups"]["bra"] in lines, lines)
for name in ("top covered", "top straps (D)", "top strapless"):
    check(f"[lines] {name}: no cups line", not any("cups" in ln for ln in gtv.template_lines(CASES[name])))
check("[regions] a cupped top's regions are a top's", gt.body_regions(cup) == frozenset({"chest", "waist"}),
      sorted(gt.body_regions(cup)))
check("[rank] layer rank of the piece's kind (top 1)", gt.LAYER_RANK[cup["kind"]] == 1)

# lint (review focus 2)
pat = r'(\["kind"\]|\.get\("kind"\)) in (gt\.)?FITTED_KINDS'
hits = subprocess.run(["git", "-C", str(ROOT), "grep", "-nE", pat, "--", "app/core"], capture_output=True, text=True)
lines_ = [ln for ln in hits.stdout.splitlines() if ln.strip()]
check("[lint] no kind-in-FITTED_KINDS decision outside build_kind", not lines_, lines_)

print()
print("all checks passed" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}")
sys.exit(1 if FAILS else 0)
