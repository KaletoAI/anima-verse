"""A235 smoke: string briefs — params, drape key, fitted spec, preview outline.

Usage: ./.venv/bin/python scripts/smoke_garment_string_briefs.py

Expected numbers derived by hand from the spec:
* ``sides`` default "fabric", ``string_width_m`` default 0.008: a fabric brief's drape key is the one before A235
  (tsig drops both fields unless ``sides`` is "string").
* string (``string_width_m`` 0.006, ``leg_length_m`` 0.1 asked): legs reset to 0 (a string has none), side_width_m
  reset to its default 0.05; the key differs from the fabric brief's; the spec carries sides "string", the width and
  ``string_corner`` (0.35, 0.35); a width of 0.03 is clamped to 0.02 and reported.
* preview (hip 0.95, waist 1.05, rise mid 0.65): top = 0.95 + 0.65 x 0.10 = 1.015; band bottom = 1.015 - 0.006 =
  1.009; leg_cut 0.8 -> corner share 0.35 + 0.35 x 0.2 = 0.42; body half 0.17, gusset 0.03 -> corner x = 0.03 +
  0.14 x 0.42 = 0.0888; the right band = [[0.0888, 1.015], [0.17, 1.015], [0.17, 1.009], [0.0888, 1.009]], two bands.
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


brief, _ = gt.validate_params({"kind": "briefs", "leg_cut": 0.8})
check("sides default", brief["sides"], "fabric")
check("string width default", brief["string_width_m"], 0.008)
old = {k: v for k, v in brief.items() if k not in ("leg_length_m", "sides", "string_width_m")
       and k not in gt.TROUSER_FIELDS}  # A233: the trouser fields key only trousers
check("fabric brief key unchanged", gt.tsig(brief, base_sha="b", texture_sha="t", lower=[]),
      gt._md5({"params": {k: v for k, v in old.items() if k not in gt.MATERIAL_ONLY
                          and k not in gt.TEXTURE_ONLY and k not in gt.OFF_SHOULDER_FIELDS},
               "version": gt.template_version(brief), "base": "b", "texture": "t", "lower": []}))
s, errs = gt.validate_params({"kind": "briefs", "sides": "string", "string_width_m": 0.006, "leg_length_m": 0.1,
                              "leg_cut": 0.8, "back_coverage": 0.05, "side_width_m": 0.02})
check("string: no legs", s["leg_length_m"], 0.0)
check("string: side width reset", s["side_width_m"], 0.05)
check("string: no errors", errs, [])
check("string key differs", gt.tsig(s, base_sha="b", texture_sha="t", lower=[]) !=
      gt.tsig(brief, base_sha="b", texture_sha="t", lower=[]), True)
_, errs = gt.validate_params({"kind": "briefs", "sides": "string", "string_width_m": 0.03})
check("width clamped + reported", len(errs) == 1 and "string_width_m" in errs[0], True)
meas = {"hip_y": 0.95, "waist_y": 1.05, "joints": {"leftupleg": [0.09, 0.90, 0.0], "rightupleg": [-0.09, 0.90, 0.0]}}
f = gt.fitted_spec(s, meas)["fitted"]
check("spec sides", f.get("sides"), "string")
check("spec width", f.get("string_width_m"), 0.006)
check("spec corner", f.get("string_corner"), [0.35, 0.35])
check("fabric spec has no sides", "sides" in gt.fitted_spec(brief, meas)["fitted"], False)
skirt, _ = gt.validate_params({"kind": "skirt", "sides": "string"})
check("skirt: sides reset", skirt["sides"], "fabric")


class Reg:
    x0 = 0.0

    def body_half(self, y, cap):
        return 0.17, 0.17


shapes, marks = [], []
gp._fitted(s, meas, Reg(), 0.3, lambda r, k, pts: shapes.append((r, pts)), lambda *a: marks.append(a))
bands = [pts for r, pts in shapes if r == "band"]
check("two bands", len(bands), 2)
want = [[0.0888, 1.015], [0.17, 1.015], [0.17, 1.009], [0.0888, 1.009]]
check("right band", [[round(x, 4), round(y, 4)] for x, y in bands[0]] if bands else None, want)
body = [pts for r, pts in shapes if r == "body"][0]
check("panel top corners", [[round(x, 4), round(y, 4)] for x, y in body[:2]], [[-0.0888, 1.015], [0.0888, 1.015]])
print("FAILED:" if fails else "all passed", fails or "")
sys.exit(1 if fails else 0)
