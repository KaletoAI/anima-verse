"""Smoke: garment-template spike S0 (Ruling A135) - thresholds and the judge.

Usage:
    ./.venv/bin/python scripts/smoke_garment_template_spike.py            # pure checks
    ./.venv/bin/python scripts/smoke_garment_template_spike.py RESULT...  # + judge spike result.json files

No server, no world, no Blender needed for the pure part. The Blender part of the
spike is ``app/blender/scripts/garment_template_drape.py``; its ``result.json``
files (runner contract: ``{"ok", "data", ...}``) can be passed to print pass/fail.

Thresholds (spec 2026-11-16-garment-templates-design.md section 8), derived by hand:

* drape_cpu_s < 60. Spec section 4 budgets a piece at 20-60 s total on the existing
  Blender runner; the cloth run is the dominant part, so it alone must fit the upper
  end. 60.0 is exclusive: 59.99 passes, 60.0 fails.
* poke_share < 0.005. Kira's body has ~20 000 skin vertices under a jacket (measured
  region 15 113 at rest for her blazer). 0.5 % = ~75-100 vertices; at the body's ~8 mm
  vertex spacing that is one patch of about 7 x 7 cm, the largest a hide-body mask
  (spec section 6) can cover without a visible hole. 0.004 passes, 0.005 fails.
* pin_drift_mm < 5. Collision distance is 4 mm (thickness in the script); a pinned
  vertex that moved more than that plus 1 mm has left its ring: the waistband slid.
* stretch_max < 1.3. Longest edge after the drape over its pre-drape length. Woven
  fabric elongates a few percent; 30 % on one edge already reads as rubber, and a
  value in the thousands is an exploded simulation. 1.29 passes, 1.3 fails.
* bake_coverage > 0.85. Two orthographic views (front, back) of a roughly cylindrical
  piece see every surface point except where the view grazes it. With the view kept
  where |cos(angle)| >= 0.23 (77 deg off-normal at most) the lost band is
  4 * asin(0.23) = 4 * 0.2321 = 0.928 rad of 2 * pi = 6.283 rad = 14.8 %, so a
  correct registration covers 85.2 %. Below 0.85 the views did not land on the piece.
  0.86 passes, 0.85 fails (strict).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core import garment_template as gt  # noqa: E402

FAILS = []


def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        FAILS.append(name)


# --- thresholds as derived above
check("drape_cpu_s = 60", gt.THRESHOLDS["drape_cpu_s"] == 60.0)
check("poke_share = 0.005", gt.THRESHOLDS["poke_share"] == 0.005)
check("pin_drift_mm = 5", gt.THRESHOLDS["pin_drift_mm"] == 5.0)
check("stretch_max = 1.3", gt.THRESHOLDS["stretch_max"] == 1.3)
check("bake_coverage = 0.85", gt.THRESHOLDS["bake_coverage"] == 0.85)
import math  # noqa: E402
lost = 4 * math.asin(0.23) / (2 * math.pi)
check("coverage derivation 1 - 4*asin(0.23)/2pi = 0.852", abs((1 - lost) - 0.852) < 0.001)

# --- judge on hand-made results: the boundary values from the docstring
good = {"drape": {"cpu_s": 59.99, "pin_drift_mm": 4.9, "stretch_max": 1.29},
        "draped": {"rest": {"poke_share": 0.004}}, "bake": {"coverage": 0.86}}
bad = {"drape": {"cpu_s": 60.0, "pin_drift_mm": 5.0, "stretch_max": 1.3},
       "draped": {"rest": {"poke_share": 0.005}}, "bake": {"coverage": 0.85}}
rows_g = gt.judge(good)
rows_b = gt.judge(bad)
check("judge: 5 rows each", len(rows_g) == 5 and len(rows_b) == 5)
check("judge: all boundary-good pass", all(r["ok"] for r in rows_g))
check("judge: all boundary-bad fail", not any(r["ok"] for r in rows_b))

# --- mesh args: the pin ring follows the kind
check("skirt pins the waist", gt.mesh_args(Path("a"), Path("b"), "skirt", "t")["pin"] == "waist")
check("jacket pins the shoulders", gt.mesh_args(Path("a"), Path("b"), "jacket", "t")["pin"] == "shoulders")

# --- the Blender script at least parses and names the modes the core relies on
src = (ROOT / "app/blender/scripts" / gt.SCRIPT).read_text(encoding="utf-8")
import ast  # noqa: E402
ast.parse(src)
for mode in ("mesh", "panels", "from_body", "necklace"):
    check(f"script has mode {mode}", f'"{mode}": run_' in src)

# --- optional: judge real spike results
for arg in sys.argv[1:]:
    res = json.loads(Path(arg).read_text(encoding="utf-8"))
    if not res.get("ok"):
        print(f"--- {arg}: run failed: {res.get('error')}")
        continue
    print(f"--- {arg} ({res['data'].get('tag')})")
    for r in gt.judge(res["data"]):
        print(f"   {'PASS' if r['ok'] else 'fail'} {r['check']:22s} {r['value']} (limit {r['limit']})")

print("FAILED: " + ", ".join(FAILS) if FAILS else "all checks passed")
sys.exit(1 if FAILS else 0)
