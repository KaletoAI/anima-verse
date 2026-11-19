"""A232 smoke: briefs with legs (boxers) — params, drape key, fitted spec, preview outline.

Usage: ./.venv/bin/python scripts/smoke_garment_boxers.py

Expected numbers derived by hand from the spec:
* ``leg_length_m`` default 0 -> a brief's params and drape key are those of the code before A232: tsig drops the
  field when 0, and ``fit`` of a brief without legs is reset to its default 0.3 (it was not a briefs field before).
* boxers (leg 0.14, fit 0.1): ``leg_cut`` reset to 0.5 (ignored); offset = 0.004 + 0.02 x 0.1 = 0.006 m; fit 0.1
  <= 0.3 -> hems pinned; loose fit 0.8 -> offset 0.004 + 0.016 = 0.020, hems not pinned.
* rows bottom = hip_y - 0.2 - leg: hip 0.95 -> 0.95 - 0.2 - 0.14 = 0.61.
* preview: crotch = leftupleg y - 0.06 = 0.90 - 0.06 = 0.84; hem = 0.84 - 0.14 = 0.70 (the "hem" dash line's y).
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.core import paths  # noqa: E402

paths.init(tempfile.mkdtemp())
from app.core import garment_template as gt  # noqa: E402
from app.core import garment_preview as gp  # noqa: E402

fails = []


def check(name, got, want):
    ok = got == want if not isinstance(want, float) else abs(got - want) < 1e-6
    print(("ok  " if ok else "FAIL"), name, got, "want", want)
    if not ok:
        fails.append(name)


brief, _ = gt.validate_params({"kind": "briefs", "leg_cut": 0.8, "fit": 0.9})
check("brief leg_length default", brief["leg_length_m"], 0.0)
check("brief fit reset", brief["fit"], 0.3)
check("brief leg_cut kept", brief["leg_cut"], 0.8)
old = dict(brief)
old.pop("leg_length_m")
check("brief key unchanged", gt.tsig(brief, base_sha="b", texture_sha="t", lower=[]),
      gt._md5({"params": {k: v for k, v in old.items() if k not in gt.MATERIAL_ONLY
                          and k not in gt.OFF_SHOULDER_FIELDS},
               "version": gt.TEMPLATE_VERSION, "base": "b", "texture": "t", "lower": []}))
skirt, _ = gt.validate_params({"kind": "skirt"})
check("skirt has no leg_length in key", "leg_length_m" in skirt and skirt["leg_length_m"] == 0.0, True)

box, _ = gt.validate_params({"kind": "briefs", "leg_length_m": 0.14, "fit": 0.1, "leg_cut": 0.9})
check("boxer leg_cut reset", box["leg_cut"], 0.5)
check("boxer key differs", gt.tsig(box, base_sha="b", texture_sha="t", lower=[]) !=
      gt.tsig(brief, base_sha="b", texture_sha="t", lower=[]), True)
meas = {"hip_y": 0.95, "waist_y": 1.05, "joints": {"leftupleg": [0.09, 0.90, 0.0], "rightupleg": [-0.09, 0.90, 0.0]}}
sp = gt.fitted_spec(box, meas)
check("boxer offset", sp["fitted"]["offset_m"], 0.006)
check("boxer hems pinned", sp["fitted"]["hem_pinned"], True)
check("rows bottom", sp["row_y"][1], 0.61)
loose, _ = gt.validate_params({"kind": "briefs", "leg_length_m": 0.12, "fit": 0.8})
sl = gt.fitted_spec(loose, meas)["fitted"]
check("loose offset", sl["offset_m"], 0.02)
check("loose hangs", sl["hem_pinned"], False)
check("brief spec has no legs", "leg_length_m" in gt.fitted_spec(brief, meas)["fitted"], False)


class Reg:
    x0 = 0.0

    def body_half(self, y, cap):
        return 0.17, 0.17

    def leg_run(self, y, guess):
        return guess - 0.08, guess + 0.08


shapes, marks = [], []
gp._fitted(box, meas, Reg(), 0.3, lambda r, k, pts: shapes.append((r, pts)), lambda *a: marks.append(a))
hem = [pts for r, pts in shapes if r == "hem"]
check("preview hem y", round(hem[0][0][1], 4) if hem else None, 0.70)
check("preview two legs", sum(1 for r, _ in shapes if r == "leg"), 2)
legs = [pts for r, pts in shapes if r == "leg"]
check("preview leg bottom y", round(min(p[1] for p in legs[0]), 4), 0.70)
print("FAILED:" if fails else "all passed", fails or "")
sys.exit(1 if fails else 0)
