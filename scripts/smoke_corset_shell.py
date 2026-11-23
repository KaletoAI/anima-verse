"""Corset v2/v3 (user report 2026-11-22: "lots of air below, thick at the top"): a strapless top's front rises over the
shaped chest (``garment_template.cup_rise`` / ``cup_drop``), it is laid on the body as a shell
(``build_args`` sends ``shell_clear_m`` / ``shell_gap_mm``) and its gaps are gated (``judge_build``). No server, no
world DB, no Blender. Every number below is derived by hand.

[1] ``cup_rise``: STRAPLESS_UNDERARM_M 0.02, CUP_COVER_M 0.035, CUP_RISE_MAX_M 0.10. Rosi's measures (band_y 1.2375,
    chest_apex_y 1.251 — the shaped apex at lift 1): the edge under the arms 1.2375 - 0.02 = 1.2175, the rise
    1.251 + 0.035 - 1.2175 = 0.0685 (the drape record of 2026-11-22 shows cup_rise_m 0.0685, top_y 1.286).
    chest_apex_y 1.40 -> 1.40 + 0.035 - 1.2175 = 0.2175 -> capped 0.10; chest_apex_y 1.10 -> negative -> 0;
    no chest_apex_y -> 0; a top with straps -> 0.
[2] ``cup_drop(0.05, 5)``: column offsets |pi c / 4 - pi / 2| = pi/2, pi/4, 0, pi/4, pi/2; CUP_HALF_RAD 0.6:
    pi/4 -> t = (0.785398 - 0.6) / (1.570796 - 0.6) = 0.190975, smoothstep 0.190975^2 x (3 - 0.381950) = 0.036471 x 2.618050 = 0.095484
    -> 0.05 x 0.095484 = 0.004774; pi/2 -> t 1 -> 0.05; 0 -> 0. Front [0.05, 0.00477, 0, 0.00477, 0.05] (5 places),
    back [0.05] x 5 (the back lies the whole rise lower than the front's top).
[3] ``build_args`` of a strapless top carries shell_clear_m = CORSET_CLEAR_M 0.0015 and shell_gap_mm = CORSET_GAP_MM
    {waist 3, hem 5, top_edge 2}; a skirt carries neither.
[4] ``judge_build`` with fit_gap waist 2.9 / hem 5.1 / top_edge 1.5 (p95): rows gap_waist_p95_mm ok, gap_hem_p95_mm
    NOT ok, gap_top_edge_p95_mm ok, all three gates; without fit_gap no gap row.

[5] Corset v3, the hem under a worn skirt's waistband (``_strapless_top_outline(tuck=...)``, STRAPLESS_TUCK_M 0.02):
    measures band_y 1.24, shoulder_y 1.37, waist_y 0.98, hip_y 0.88, floor 0, no chest measures (no rise, no fold);
    length 0.45. The edge under the arms 1.24 - 0.02 = 1.22, the length counts from 1.37 + SHOULDER_TOP_M 0.045 =
    1.415 -> hem min(1.22 - 0.08, max(0.2, 1.415 - 0.45)) = 0.965. Waist lines (``_waist_line``): natural 0.98,
    high 0.98 + 0.03 = 1.01, low 0.98 - 0.5 x 0.10 = 0.93.
    no tuck -> 0.965, no record; natural: 0.965 > 0.98 - 0.02 -> hem 0.96 {waist_line 0.98, from 0.965, hem 0.96};
    high: 0.965 <= 1.01 - 0.02 = 0.99 -> unchanged; low: hem 0.91; high + low: the lower line counts -> 0.91.
    ``tuck_lines``: the worn skirt (waist_height low) and trousers (natural) count, a bra does not, each line once,
    sorted -> ("low", "natural"); a skirt's own tuck_lines -> ().
[6] ``judge_build``: under_edge p95 5.27 > 5 fails, 3.17 ok (gate); hem_tucked {waist_line 0.98, hem 0.96} ->
    hem_under_waistband_m 0.02 ok, {0.98, 0.965} -> 0.015 NOT ok.

Usage: ./.venv/bin/python scripts/smoke_corset_shell.py
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_SCRATCH = Path(tempfile.mkdtemp(prefix="smoke-corset-shell-"))
from app.core import paths  # noqa: E402
paths.init(_SCRATCH / "world")
paths.init_instance(_SCRATCH / "instance")

from app.core import garment_template as gt  # noqa: E402

FAILS = []


def check(label, ok, detail=""):
    print(("OK   " if ok else "FAIL ") + label + (f"  ({detail})" if not ok and detail != "" else ""))
    if not ok:
        FAILS.append(label)


check("constants", (gt.STRAPLESS_UNDERARM_M, gt.CUP_COVER_M, gt.CUP_RISE_MAX_M, gt.CUP_HALF_RAD, gt.CORSET_CLEAR_M,
                    gt.CORSET_GAP_MM, gt.STRAPLESS_TUCK_M, gt.TUCK_KINDS)
      == (0.02, 0.035, 0.10, 0.6, 0.0015, {"waist": 3.0, "hem": 5.0, "top_edge": 2.0, "under_edge": 5.0}, 0.02,
          ("skirt", "trousers")))
corset = gt.validate_params({"kind": "top", "shoulders": "strapless", "neckline": "sweetheart", "fit": 0.0})[0]
strapped = gt.validate_params({"kind": "top"})[0]
skirt = gt.validate_params({"kind": "skirt"})[0]

# [1]
M = {"band_y": 1.2375, "chest_apex_y": 1.251}
check("[1] Rosi: rise 0.0685", gt.cup_rise(corset, M) == 0.0685, gt.cup_rise(corset, M))
check("[1] capped at 0.10", gt.cup_rise(corset, {**M, "chest_apex_y": 1.40}) == 0.10)
check("[1] a low chest: 0", gt.cup_rise(corset, {**M, "chest_apex_y": 1.10}) == 0.0)
check("[1] no chest measure: 0", gt.cup_rise(corset, {"band_y": 1.2375}) == 0.0)
check("[1] a top with straps: 0", gt.cup_rise(strapped, M) == 0.0)

# [2]
front, back = gt.cup_drop(0.05, 5)
check("[2] front falls to the arms", [round(v, 5) for v in front] == [0.05, 0.00477, 0.0, 0.00477, 0.05], front)
check("[2] back the whole rise lower", back == [0.05] * 5, back)

# [3]
src = (ROOT / "app" / "core" / "garment_template.py").read_text(encoding="utf-8")
check("[3] build_args sends shell_clear_m / shell_gap_mm for a strapless top only",
      '{"shell_clear_m": CORSET_CLEAR_M, "shell_gap_mm": dict(CORSET_GAP_MM)} if strapless_top(params) else {}' in src)
check("[3] a skirt is no strapless top", not gt.strapless_top(skirt) and gt.strapless_top(corset))

# [4]
rows = {r["check"]: r for r in gt.judge_build({"fit_gap": {"waist": {"p95_mm": 2.9}, "hem": {"p95_mm": 5.1},
                                                           "top_edge": {"p95_mm": 1.5}}})}
check("[4] waist 2.9 <= 3 ok", rows["gap_waist_p95_mm"]["ok"] and rows["gap_waist_p95_mm"]["gate"])
check("[4] hem 5.1 > 5 fails", not rows["gap_hem_p95_mm"]["ok"] and rows["gap_hem_p95_mm"]["gate"])
check("[4] top edge 1.5 <= 2 ok", rows["gap_top_edge_p95_mm"]["ok"])
check("[4] no fit_gap, no gap row", not any(r["check"].startswith("gap_") for r in gt.judge_build({})))

# [5]
MT = {"band_y": 1.24, "floor_y": 0.0, "shoulder_y": 1.37, "waist_y": 0.98, "hip_y": 0.88,
      "torso": [[0.8, 0.92], [1.0, 0.70], [1.2, 0.80], [1.36, 1.0]]}
c45 = gt.validate_params({"kind": "top", "shoulders": "strapless", "neckline": "sweetheart", "fit": 0.0,
                          "length_m": 0.45})[0]


def hem(tuck):
    o = gt._strapless_top_outline(c45, MT, 0.98, tuck)
    return round(o["top_y"] - o["length"], 4), o.get("hem_tucked")


check("[5] no tuck: hem 0.965, no record", hem(()) == (0.965, None), hem(()))
check("[5] natural: hem 0.96, recorded", hem(("natural",)) == (0.96, {"waist_line_y": 0.98, "from_y": 0.965,
                                                                      "hem_y": 0.96}), hem(("natural",)))
check("[5] high: already under, unchanged", hem(("high",)) == (0.965, None), hem(("high",)))
check("[5] low: hem 0.91", hem(("low",))[0] == 0.91, hem(("low",)))
check("[5] high + low: the lower line counts", hem(("high", "low"))[0] == 0.91, hem(("high", "low")))
from app.models import inventory as _inv  # noqa: E402
_ITEMS = {"sk": {"template": {"kind": "skirt", "waist_height": "low"}},
          "tr": {"template": {"kind": "trousers", "waist_height": "natural"}},
          "tr2": {"template": {"kind": "trousers", "waist_height": "natural"}},
          "br": {"template": {"kind": "bra"}}}
_orig_get = _inv.get_item
_orig_tk, _orig_po = gt._template_kind, gt.params_of
_inv.get_item = lambda i: _ITEMS.get(i)
gt._template_kind = lambda it: (it or {}).get("template", {}).get("kind")
gt.params_of = lambda it: (it or {}).get("template")
try:
    check("[5] tuck_lines: skirt + trousers, each once, sorted", gt.tuck_lines(corset, ["br", "tr", "sk", "tr2"])
          == ("low", "natural"), gt.tuck_lines(corset, ["br", "tr", "sk", "tr2"]))
    check("[5] a skirt has no tuck lines", gt.tuck_lines(skirt, ["tr"]) == ())
finally:
    _inv.get_item, gt._template_kind, gt.params_of = _orig_get, _orig_tk, _orig_po

# [6]
r6 = {r["check"]: r for r in gt.judge_build({"fit_gap": {"under_edge": {"p95_mm": 5.27}}})}
check("[6] under_edge 5.27 > 5 fails (gate)", not r6["gap_under_edge_p95_mm"]["ok"]
      and r6["gap_under_edge_p95_mm"]["gate"])
r6 = {r["check"]: r for r in gt.judge_build({"fit_gap": {"under_edge": {"p95_mm": 3.17}}})}
check("[6] under_edge 3.17 ok", r6["gap_under_edge_p95_mm"]["ok"])
r6 = {r["check"]: r for r in gt.judge_build({"outline": {"hem_tucked": {"waist_line_y": 0.98, "hem_y": 0.96}}})}
check("[6] 0.02 under the waistband ok", r6["hem_under_waistband_m"]["ok"]
      and r6["hem_under_waistband_m"]["value"] == 0.02, r6.get("hem_under_waistband_m"))
r6 = {r["check"]: r for r in gt.judge_build({"outline": {"hem_tucked": {"waist_line_y": 0.98, "hem_y": 0.965}}})}
check("[6] 0.015 under the waistband fails", not r6["hem_under_waistband_m"]["ok"])

print(f"\n{len(FAILS)} FAILED: {FAILS}" if FAILS else "\nALL OK")
sys.exit(1 if FAILS else 0)
