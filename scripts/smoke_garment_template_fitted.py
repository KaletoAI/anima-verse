"""A223 — the fitted garment templates (briefs, bra, gloves): parameters, kind guess, the cut numbers, the drawing.

No server, no world DB, no Blender: ``app.core.garment_template`` and ``app.core.garment_preview`` on a synthetic
body measure. Usage: ./.venv/bin/python scripts/smoke_garment_template_fitted.py

Hand-derived expectations (the synthetic measure ``M``: waist_y 1.05, hip_y 0.90, neck_c 0.33, shoulder_w 0.40, ...):

[B1] briefs top_y = hip + RISE_SHARE x (waist - hip): low 0.90 + 0.3 x 0.15 = 0.945; mid 0.90 + 0.65 x 0.15 = 0.9975;
     high = 1.05. Pinned band: thin 0.012, wide 0.030, none -> MIN_PIN_BAND_M 0.012 (waistband_m 0).
[B2] validate: leg_cut 1.7 -> clamped to 1.5 (step 3a: high-leg up to 1.5) and reported; side_width_m 0.2 -> 0.10; an unknown rise -> "mid" + error.
[B3] a briefs answer keeps only its kind's fields: length_m 0.9 given -> back to the default 0.5.
[B4] default_kind: slots [underwear_bottom] -> briefs; [bottom, underwear_bottom] named "Schuppenslip" -> briefs;
     "Bikini bottom" on [bottom] -> briefs; jeans on [bottom] -> trousers; a skirt on [bottom] -> skirt.
[B5] measured poses of briefs = rest, walk, sit, kneel; no pose-shape groups.
[R1] bust lines of M (torso girth 0.90 from 1.18 to 1.22, else 0.80): bust 1.18, underbust 1.04.
[R2] strap shoulder point = (neck_c / 2pi + 0.012 + 0.75 x shoulder_w / 2) / 2 = 0.10726; cross -> back_x -0.10726;
     the bodice's strap_x is the same number (shared ``strap_shoulder_x``).
[R3] the bra's spec numbers; [R4] its kind guess (a bustier stays a top, A221); [R5] its drawing's fills.
[G1] glove reach on M (forearm 0.25, upper arm 0.25): wrist 0.18 x 0.25 = 0.045, forearm 0.55 x 0.25 = 0.1375,
     elbow 0.25 + 0.12 x 0.25 = 0.28, opera 0.25 + 0.7 x 0.25 = 0.425.
[G2] gap 0.004 + 0.012 x 0.1 = 0.0052, fingers 0.0015. [G3] kind guess. [G4] a body without arm joints is refused.
[T1] tights: full top = waist 1.05, gap 0.0035, waistband thin 0.012; hold-up band 0.04; knee sock 0.025; tabs
     only on thigh-highs. [T2] kind guess (legs / hosiery words). [T3] drawing fills, tab top = 0.80 - 0.07 + 0.04.
[B6] the drawing: briefs give one cloth fill whose top edge lies at top_y (the registration's y of 0.945 m) and whose
     lowest point is the gusset (crotch = hip joints 0.86 - 0.06 = 0.80 m, the lowest y of the fill).
[B7] Step 3a, the high-leg cut (``brief_leg_shape``; Glut: hip_half 0.1687, gusset half g 0.03, so hip_half - g =
     0.1387, HIGH_LEG 0.6): reach(1.0) = 0.1687; reach(1.25) = 0.1687 - 0.25 / 0.5 x 0.6 x 0.1387 = 0.1687 - 0.04161 =
     0.12709; reach(1.5) = 0.1687 - 0.6 x 0.1387 = 0.08548 (+-1e-5); the power past 1 stays 0.4 (1.6 - 1.2 x 1), the
     side share 1; at leg_cut 0.5: share 0.5, power 1.0, reach 0.1687.
[B8] The back's half width (``brief_back_width`` = 0.4 g + bc x 0.9 x (hip_half - 0.4 g)): gusset_m 0.03 (g 0.015),
     bc 0 -> 0.4 x 0.015 = 0.006 (a 1.2 cm string); gusset_m 0.06 (g 0.03), bc 0.2, hip_half 0.1687 ->
     0.012 + 0.18 x (0.1687 - 0.012) = 0.012 + 0.18 x 0.1567 = 0.040206.
[B9] A default brief's ``fitted_spec``: gusset_half_m = 0.06 / 2 = 0.03 (the deleted constant's value: the default
     drape shape is unchanged), high_leg 0.6; gusset_m 0.03 -> 0.015.
[B10] The drawing of a leg_cut 1.5 brief on M: the front fill reaches the side's height at x = reach short of the hip's
     side and then runs along it to the side (one point more on each leg than at leg_cut 1.0: 10 instead of 9).
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
p, e = gt.validate_params({"kind": "briefs", "leg_cut": 1.7, "side_width_m": 0.2, "rise": "ultra"})
check("[B2] leg_cut clamped to 1.5 + reported", p["leg_cut"] == 1.5 and any("leg_cut" in x for x in e), (p, e))
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

# [R1] the bust lines of M: the widest torso slice between waist + 5 cm (1.10) and the band (1.275) is 0.90 from
# 1.18 (the first of the equal ones), the narrowest 14..4 cm under it (1.04..1.14, all 0.80) the first, 1.04
check("[R1] bust lines (1.04, 1.18)", gt._bust_lines(M) == (1.04, 1.18), gt._bust_lines(M))


def bra(**kw):
    return gt.validate_params({"kind": "bra", **kw})[0]


# [R2] straps: neck_r = 0.33 / 2pi + 0.012 = 0.064521; shoulder_x = (0.064521 + 0.75 x 0.20) / 2 = 0.107261
st = gt.strap_spec(bra(straps="cross"), M)
check("[R2] strap shoulder_x 0.10726", close(st["shoulder_x"], 0.10726), st)
check("[R2] cross: back_x on the other side", close(st["back_x"], -0.10726), st)
check("[R2] cross width 0.014", close(st["width_m"], 0.014), st)
check("[R2] straps none -> no strap record", gt.strap_spec(bra(straps="none"), M) is None)
check("[R2] the dress / corset top straps use the same shoulder point",
      close(gt.bodice_spec(gt.validate_params({"kind": "dress", "shoulders": "straps"})[0], M)["strap_x"], 0.10726))
f = gt.fitted_spec(bra(underband_m=0.0, center_gore="wide", cup_style="molded"), M)["fitted"]
check("[R3] bra spec: under 1.04, bust 1.18, gore (0.022, 0.05), molded rigid",
      (f["under_y"], f["bust_y"], f["gore_half_m"], f["gore_h_m"], f["rigid_cups"]) == (1.04, 1.18, 0.022, 0.05, True), f)
check("[R3] bra built", "bra" in gt.BUILT_KINDS)
check("[R3] bra measured poses", gt.measured_poses(bra()) == ("rest", "walk", "arms_down", "arms_up"))
for it, want in ((item("Schuppen-BH", ["top", "underwear_top"]), "bra"), (item("Bikini top", ["top"]), "bra"),
                 (item("Silk blouse", ["top"]), "top"), (item("Leather bustier", ["top"]), "top"),
                 (item("Lace", ["underwear_top"]), "bra")):
    check(f"[R4] default_kind {it['name']} -> {want}", gt.default_kind(it) == want, gt.default_kind(it))
# [R5] drawing: molded with thin straps and the default narrow gore = band + 2 cups + gore + 2 straps; a bandeau (no
# gore) = band + 1 band-cup + 2 straps
n = len([s for s in gp.shapes(bra(), M, Reg())["shapes"] if s["kind"] == "fill"])
check("[R5] molded bra: 6 fills", n == 6, n)
n = len([s for s in gp.shapes(bra(cup_style="bandeau"), M, Reg())["shapes"] if s["kind"] == "fill"])
check("[R5] bandeau: 4 fills", n == 4, n)



# [G1] gloves on M: forearm = |leftforearm - lefthand| = 0.25, upper arm = 0.25; reach = a x 0.25 + b x 0.25
def gloves(**kw):
    return gt.validate_params({"kind": "gloves", **kw})[0]


for ln, want in (("wrist", 0.045), ("forearm", 0.1375), ("elbow", 0.28), ("opera", 0.425)):
    f = gt.fitted_spec(gloves(length=ln), M)["fitted"]
    check(f"[G1] {ln} reach {want}", close(f["reach_m"], want), f["reach_m"])
# [G2] the gap: FITTED_OFFSET_M 0.004 + GLOVE_FIT_M 0.012 x fit; the default fit 0.1 -> 0.0052; fingers 0.0015
f = gt.fitted_spec(gt.kind_defaults("gloves"), M)["fitted"]
check("[G2] default fit 0.1: offset 0.0052, fingers 0.0015", close(f["offset_m"], 0.0052) and
      close(f["finger_offset_m"], 0.0015), f)
check("[G2] gloves built", "gloves" in gt.BUILT_KINDS)
for it, want in ((item("Stulpen", ["hands"]), "gloves"), (item("Leather gauntlets", ["outer"]), "gloves")):
    check(f"[G3] default_kind {it['name']} -> {want}", gt.default_kind(it) == want, gt.default_kind(it))
try:
    gt.fitted_spec(gloves(), {**M, "joints": {}})
    check("[G4] no arm joints -> ValueError", False)
except ValueError:
    check("[G4] no arm joints -> ValueError", True)



# [T1] tights: full tights top at the waist 1.05; the gap HOSIERY_OFFSET_M 0.0035; bands per style
def tights(**kw):
    return gt.validate_params({"kind": "tights", **kw})[0]


f = gt.fitted_spec(tights(), M)["fitted"]
check("[T1] full tights: top 1.05, offset 0.0035, thin waistband 0.012",
      (f["top_y"], f["offset_m"], f["waistband_m"], f["band_m"]) == (1.05, 0.0035, 0.012, 0.0), f)
f = gt.fitted_spec(tights(tights_style="hold_up", waistband="wide"), M)["fitted"]
check("[T1] hold-up: per-leg top, grip band 0.04, no waistband", (f["top_y"], f["band_m"], f["waistband_m"]) ==
      (None, 0.04, 0.0), f)
f = gt.fitted_spec(tights(tights_style="hold_up", garters="tabs"), M)["fitted"]
check("[T1] garter tabs only on thigh-highs", f["garters"] == "none", f)
f = gt.fitted_spec(tights(tights_style="thigh_high", garters="tabs"), M)["fitted"]
check("[T1] thigh-high with tabs", f["garters"] == "tabs" and f["band_m"] == 0.0, f)
check("[T1] knee sock cuff 0.025", gt.fitted_spec(tights(tights_style="knee_high"), M)["fitted"]["band_m"] == 0.025)
check("[T1] tights defaults: sheer 0.5", (gt.kind_defaults("tights")["fabric"], gt.kind_defaults("tights")["opacity"])
      == ("sheer", 0.5))
for it, want in ((item("Black stockings", ["legs"]), "tights"), (item("Plain", ["legs", "feet"]), "tights"),
                 (item("Strumpfhose", ["legs"]), "tights"), (item("Leggings", ["bottom"]), "trousers")):
    check(f"[T2] default_kind {it['name']} {it['outfit_piece']['slots']} -> {want}", gt.default_kind(it) == want,
          gt.default_kind(it))
# [T3] drawing on M (no leg runs: legs +-0.06 round x 0.09): full tights = seat + 2 legs; thigh-high with tabs =
# 2 legs + 2 tabs, the tab's top 0.04 over the leg top (crotch 0.80 - 0.07 = 0.73 -> 0.77)
sh = [s for s in gp.shapes(tights(), M, Reg())["shapes"] if s["kind"] == "fill"]
check("[T3] full tights: 3 fills", len(sh) == 3, len(sh))
sh = [s for s in gp.shapes(tights(tights_style="thigh_high", garters="tabs"), M, Reg())["shapes"] if s["kind"] == "fill"]
check("[T3] thigh-high with tabs: 4 fills", len(sh) == 4, len(sh))
tab_top = max(2.0 - q[1] / 1000.0 for s in sh for q in s["points"])
check("[T3] tab top 0.77", close(tab_top, 0.77), tab_top)

# [B7] high-leg reach
for lc, want in ((1.0, 0.1687), (1.25, 0.12709), (1.5, 0.08548)):
    sh_, pw_, re_ = gt.brief_leg_shape(lc, 0.1687, 0.03)
    check(f"[B7] reach({lc}) = {want}", abs(re_ - want) < 1e-5 and abs(pw_ - 0.4) < 1e-12 and sh_ == 1.0, (sh_, pw_, re_))
sh_, pw_, re_ = gt.brief_leg_shape(0.5, 0.1687, 0.03)
check("[B7] leg_cut 0.5: share 0.5, power 1.0, reach 0.1687", (sh_, round(pw_, 9), re_) == (0.5, 1.0, 0.1687),
      (sh_, pw_, re_))
# [B8] back width
check("[B8] w_back(g 0.015, bc 0) = 0.006", abs(gt.brief_back_width(0.015, 0.0, 0.1687) - 0.006) < 1e-9,
      gt.brief_back_width(0.015, 0.0, 0.1687))
check("[B8] w_back(g 0.03, bc 0.2, 0.1687) = 0.040206", abs(gt.brief_back_width(0.03, 0.2, 0.1687) - 0.040206) < 1e-9,
      gt.brief_back_width(0.03, 0.2, 0.1687))
# [B9] the spec
f = gt.fitted_spec(briefs(), M)["fitted"]
check("[B9] default gusset_half_m 0.03, high_leg 0.6", f["gusset_half_m"] == 0.03 and f["high_leg"] == 0.6, f)
check("[B9] gusset_m 0.03 -> 0.015", gt.fitted_spec(briefs(gusset_m=0.03), M)["fitted"]["gusset_half_m"] == 0.015)
# [B10] the drawing
n10 = {lc: [len(s["points"]) for s in gp.shapes(briefs(leg_cut=lc), M, Reg())["shapes"] if s["kind"] == "fill"]
       for lc in (1.0, 1.5)}
check("[B10] high-leg front: 2 points more (one per leg)", n10[1.5][0] == n10[1.0][0] + 2, n10)

print()
print("all checks passed" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
