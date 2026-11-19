"""A223 — the fitted garment templates (briefs, bra, gloves): parameters, kind guess, the cut numbers, the drawing.

No server, no world DB, no Blender: ``app.core.garment_template`` and ``app.core.garment_preview`` on a synthetic
body measure. Usage: ./.venv/bin/python scripts/smoke_garment_template_fitted.py

Hand-derived expectations (the synthetic measure ``M``: waist_y 1.05, hip_y 0.90, neck_c 0.33, shoulder_w 0.40, ...):

[B1] briefs top_y = hip + RISE_SHARE x (waist - hip): low 0.90 + 0.3 x 0.15 = 0.945; mid 0.90 + 0.65 x 0.15 = 0.9975;
     high = 1.05. Pinned band: thin 0.012, wide 0.030, none -> MIN_PIN_BAND_M 0.012 (waistband_m 0).
[B2] validate: leg_cut 1.4 -> clamped to 1.0 and reported; side_width_m 0.2 -> 0.10; an unknown rise -> "mid" + error.
[B3] a briefs answer keeps only its kind's fields: length_m 0.9 given -> back to the default 0.5.
[B4] default_kind: slots [underwear_bottom] -> briefs; [bottom, underwear_bottom] named "Schuppenslip" -> briefs;
     "Bikini bottom" on [bottom] -> briefs; jeans on [bottom] -> trousers; a skirt on [bottom] -> skirt.
[B5] measured poses of briefs = rest, walk, sit, kneel; no pose-shape groups.
[B6] the drawing: briefs give one cloth fill whose top edge lies at top_y (the registration's y of 0.945 m) and whose
     lowest point is the gusset (crotch = hip joints 0.86 - 0.06 = 0.80 m, the lowest y of the fill).
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import garment_template as gt  # noqa: E402

FAILED = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"   [{detail}]" if not ok and detail else ""))
    if not ok:
        FAILED.append(name)


def close(a, b, tol=1e-4):
    return abs(float(a) - float(b)) <= tol


M = {"height": 1.70, "floor_y": 0.0, "waist_y": 1.05, "waist_c": 0.70, "hip_y": 0.90, "hip_c": 0.96,
     "band_y": 1.275, "band_c": 0.86, "shoulder_y": 1.40, "shoulder_w": 0.40, "neck_y": 1.47, "neck_c": 0.33,
     "arm_len": 0.50, "arm_c": [[0.05, 0.30], [0.97, 0.16]], "upper_arm_c": 0.28, "wrist_c": 0.16,
     "torso": [[round(0.68 + 0.02 * i, 3), 0.80 + (0.10 if 1.18 <= 0.68 + 0.02 * i <= 1.22 else 0.0)]
               for i in range(37)],
     "joints": {"leftarm": [0.16, 1.40, 0.0], "rightarm": [-0.16, 1.40, 0.0], "leftforearm": [0.41, 1.40, 0.0],
                "rightforearm": [-0.41, 1.40, 0.0], "lefthand": [0.66, 1.40, 0.0], "righthand": [-0.66, 1.40, 0.0],
                "neck": [0.0, 1.47, 0.0], "spine2": [0.0, 1.25, 0.0], "leftupleg": [0.09, 0.86, 0.0]}}


def briefs(**kw):
    return gt.validate_params({"kind": "briefs", **kw})[0]


# [B1]
for rise, want in (("low", 0.945), ("mid", 0.9975), ("high", 1.05)):
    f = gt.fitted_spec(briefs(rise=rise), M)["fitted"]
    check(f"[B1] {rise} rise top_y {want}", close(f["top_y"], want), f["top_y"])
for band, want, wb in (("thin", 0.012, 0.012), ("wide", 0.03, 0.03), ("none", 0.012, 0.0)):
    f = gt.fitted_spec(briefs(waistband=band), M)["fitted"]
    check(f"[B1] waistband {band}: pinned band {want}, band {wb}", close(f["band_m"], want) and close(f["waistband_m"], wb),
          f)
check("[B1] briefs are built", "briefs" in gt.BUILT_KINDS and "briefs" in gt.FITTED_KINDS)

# [B2]
p, e = gt.validate_params({"kind": "briefs", "leg_cut": 1.4, "side_width_m": 0.2, "rise": "ultra"})
check("[B2] leg_cut clamped to 1.0 + reported", p["leg_cut"] == 1.0 and any("leg_cut" in x for x in e), (p, e))
check("[B2] side_width_m clamped to 0.10", p["side_width_m"] == 0.1, p["side_width_m"])
check("[B2] unknown rise -> mid + error", p["rise"] == "mid" and any("rise" in x for x in e), e)

# [B3]
p, _e = gt.validate_params({"kind": "briefs", "length_m": 0.9})
check("[B3] length_m not a briefs field -> default 0.5", p["length_m"] == 0.5, p["length_m"])


# [B4]
def item(name, slots):
    return {"name": name, "outfit_piece": {"slots": slots}}


for it, want in ((item("Plain", ["underwear_bottom"]), "briefs"),
                 (item("Schuppenslip", ["bottom", "underwear_bottom"]), "briefs"),
                 (item("Bikini bottom", ["bottom"]), "briefs"),
                 (item("Blue jeans", ["bottom"]), "trousers"),
                 (item("Pleated skirt", ["bottom"]), "skirt")):
    check(f"[B4] default_kind {it['name']} {it['outfit_piece']['slots']} -> {want}", gt.default_kind(it) == want,
          gt.default_kind(it))

# [B5]
check("[B5] briefs measured poses", gt.measured_poses(briefs()) == ("rest", "walk", "sit", "kneel"))
check("[B5] briefs: no pose-shape groups", gt.shape_groups(briefs()) == [])


# [B6] the drawing on a registration that maps metres to pixels 1:1000 (y down)
class Reg:
    x0 = 0.0
    exact = True

    def px(self, x, y):
        return [x * 1000.0, (2.0 - y) * 1000.0]

    def body_half(self, y, cap_m):
        return 0.17, 0.17

    def joint_arm_axis(self, side):
        return (side * 0.16, 1.40), (float(side), 0.0)


from app.core import garment_preview as gp  # noqa: E402
out = gp.shapes(briefs(rise="low"), M, Reg())
fills = [s for s in out["shapes"] if s["kind"] == "fill"]
check("[B6] briefs: one cloth fill", len(fills) == 1, out["shapes"])
ys = [2.0 - q[1] / 1000.0 for q in fills[0]["points"]] if fills else [0]
check("[B6] briefs fill top at 0.945 m", close(max(ys), 0.945), max(ys))
check("[B6] briefs fill bottom at the gusset 0.80 m", close(min(ys), 0.80), min(ys))

print()
print("all checks passed" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
