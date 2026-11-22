"""The template dialog's drawing per OPTION (``app/core/garment_preview.py``): every option is drawn the way the build
makes it, and the options of one parameter can be told apart (bug round 2026-11-20: "bei Körbchen sieht vieles
ähnlich aus" — molded and balconette, push-up 0 and 1 were the same polygons).

Usage: ./.venv/bin/python scripts/smoke_garment_preview_options.py [--sheets <dir>]
       (no server, no world, no GLB; ``--sheets`` also writes the synthetic body's contact sheets there)

A. The mirrored builder numbers. The Blender builders cannot be imported (bpy); ``garment_preview`` mirrors the values
   it draws by. Each is read back out of the builder source and compared (module constants by AST, the literals inside
   ``bra_region`` / ``tights_region`` / ``trousers_region`` / ``strap_path`` / ``panel_spec`` by their source line).

B. Key numbers on a synthetic body, derived by hand from the build's rules:

   Body: height 1.70, floor 0, x0 = 0 (hips / neck joints at x 0), shoulder_y 1.40, shoulder_w 0.40 (half 0.20),
   neck_y 1.46, neck_c = 2 pi 0.06 -> neck_r = 0.06 + NECK_CLEAR_M 0.012 = 0.072. Torso girth 0.80, 0.92 at 1.20 (the
   widest between waist + 5 cm and the band -> bust_y 1.20), 0.74 at 1.12 (the narrowest 14 .. 4 cm under it ->
   under_y 1.12), 1.00 at the shoulder line. Bra apex (0.09, 1.20) either side, no breast fold.

   * Bra (coverage 0.7): H = 1.20 - 1.12 = 0.08, zc = 1.20 + (0.7 - 0.5) 2 H = 1.232.
     molded: top at the apex 1.232, at the outer edge (u = 1, x = 0.09 + 0.075 = 0.165) 1.232 - H / 2 = 1.192;
     balconette: 1.232 at both; triangle: peak 1.232 + 0.8 H = 1.296, outer edge under + 0.015 = 1.135;
     bandeau: one band to 1.232, no gore.
     Cup inner edge = gore half: none 0.008, narrow 0.012, wide 0.022. Gore (GORE + 4 mm): none none; narrow half
     0.016 up to 1.12 + 0.03 = 1.15; wide half 0.026 up to 1.17.
     push_up 1: the apex top at 1.232 + 0.02 = 1.252, its x 0.09 - 0.012 = 0.078.
     Straps: start (0.09 + 0.005, top - 0.01) = (0.095, 1.222) molded, (0.095, 1.286) triangle; shoulder_x = 0.5 x
     (0.072 + 0.75 x 0.20) = 0.111; halter end (0.9 x 0.072, 1.46 + 0.04) = (0.0648, 1.50); thin back to (+0.111,
     1.12), cross back to (-0.111, 1.12) (an X).
   * Neckline (top, covered): torso half depth at the shoulder line: the ellipse of half width 0.20 with perimeter 1.00
     (Ramanujan) -> 0.1121 (> neck_r + CAP_MIN_M 0.102), so s_front = 0.1121 - 0.072 + depth = 0.0401 + depth;
     bottom = 1.40 - depth: crew 1.39, scoop 1.32, V 1.28; boat: depth 0 -> no cut, the opening widened to
     BOAT_SHARE x 0.20 = 0.124. Collar: 3 x 12 mm = 0.036 high, only where the cut <= 3 cm: on a V (s_front 0.1601)
     where 1 - |sin a| <= 0.187 -> |sin a| >= 0.813, so nothing within x = 0.813 x 0.072 = 0.0585 of the centre.
   * Gloves (fit 0.3): offset 0.004 + 0.012 x 0.3 = 0.0076; forearm 0.275 -> reach wrist 0.18 x 0.275 = 0.0495, the
     cuff edge at 0.55 - 0.0495 = 0.5005 from the shoulder; flared: there the half width + 0.015 over plain.
   * Tights: footless / stirrup end at the ankle joint 0.08 - 0.01 = 0.07; hold_up grip band 0.04, knee_high cuff
     0.025 under their tops (crotch 0.92 - 0.06 = 0.86 -> stocking top 0.86 - 0.07 = 0.79; knee 0.48 - 0.05 = 0.43).
   * Trousers stirrup: the leg ends at 0.07 too.
   * Skirt: the hem sags SKIRT_HEM_DIP_M = 0.02 at the centre (from the hem height of ``garment_template.outline``).
     The waistband (step 3b: the panels' top face rows, ``WAISTBAND_M``) is drawn as one line ``band_edge`` under the
     skirt's top: thin top - 0.012, wide top - 0.030; none draws no line.

C. Pairwise distinctness: for every parameter of every kind (``garment_preview_sheet.option_sets``), every two
   options differ — the cloth's mask IoU <= 0.97, or the guides' (lines / dashes) IoU <= 0.9, or a patch of cloth of at
   least 4 cm^2 (2 x 2 cm) is in one and not the other (a lacing, a gore, a slit). EXCEPTIONS are the options
   the build itself does not tell apart in a front view (listed below with their reason): the fabric, and the
   texture-only fields ``texture`` / ``sleeve_print`` (``garment_template.TEXTURE_ONLY`` — where the texture comes
   from, no drape: the cut is the same; ``fly`` is texture-only too but drawn, so it stays checked).
"""
import ast
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_tmp = tempfile.mkdtemp(prefix="gp-options-")
os.environ.setdefault("STORAGE_DIR", _tmp)
os.environ.setdefault("INSTANCE_DIR", _tmp)
from app.core import paths  # noqa: E402

paths.init(_tmp)
import math  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

from app.core import front_camera  # noqa: E402
from app.core import garment_preview as gp  # noqa: E402
from app.core import garment_preview_sheet as gs  # noqa: E402
from app.core import garment_template as gt  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FAILS = []


def check(name, got, want, tol=1e-3):
    if isinstance(want, bool) or want is None:
        ok = got == want
    elif isinstance(want, (list, tuple)):
        ok = len(got) == len(want) and all(abs(a - b) <= tol for a, b in zip(got, want))
    else:
        ok = abs(got - want) <= tol
    print(("ok  " if ok else "FAIL"), name, got, "want", want)
    if not ok:
        FAILS.append(name)


# --- A. the mirrored builder numbers ------------------------------------------------------------------------------
BUILD = (ROOT / "app/blender/scripts/garment_template_build.py").read_text()
FITTED = (ROOT / "app/blender/scripts/garment_template_fitted.py").read_text()
GT = (ROOT / "app/core/garment_template.py").read_text()


def module_const(src, name):
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    return None


def func_src(src, name):
    for node in ast.parse(src).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(src, node)
    return ""


for name, mine in (("NECK_RING_UP_M", gp.NECK_RING_UP_M), ("CAP_MIN_M", gp.CAP_MIN_M),
                   ("COLLAR_RINGS", gp.COLLAR_RINGS), ("COLLAR_STEP_M", gp.COLLAR_STEP_M),
                   ("COLLAR_CUT_MAX_M", gp.COLLAR_CUT_MAX_M), ("NECK_ROUND_POW", gp.NECK_ROUND_POW)):
    check(f"A build {name}", module_const(BUILD, name), mine, 0)
for name, mine in (("FOLD_SCAN_M", gp.FOLD_SCAN_M), ("FOLD_STEP_M", gp.FOLD_STEP_M),
                   ("CLOSURE_HALF_M", gp.CLOSURE_HALF_M)):
    check(f"A fitted {name}", module_const(FITTED, name), mine, 0)
bra = func_src(FITTED, "bra_region")
apex = func_src(FITTED, "_apex")
literals = [
    ("r_out", bra, rf"r_out = {gp.CUP_R_OUT_M}\b"),
    ("triangle rim", bra, rf"under \+ {gp.TRIANGLE_RIM_M}\)\) \* u"),
    ("cup top min", bra, rf"np\.maximum\(z, under \+ {gp.CUP_TOP_MIN_M}\)"),
    ("gore extra", bra, rf"gore_half \+ {gp.GORE_EXTRA_M}\)"),
    ("strap start", bra, rf"a\[0\] \+ s \* {gp.STRAP_START_IN_M}, a\[1\], float\(zt\[0\]\) - {gp.STRAP_START_DROP_M}\]"),
    ("collar shrink", BUILD, rf"sh = {gp.COLLAR_SHRINK} \*\* \(k - K\)"),
    ("halter share", func_src(FITTED, "strap_path"), rf"float\(st\[\"neck_r\"\]\) \* {gp.HALTER_NECK_SHARE}\b"),
    ("apex window", apex, rf"> {gp.APEX_X_M[0]}\) & \(s \* \(co\[:, 0\] - cx\) < {gp.APEX_X_M[1]}\)"),
    ("apex up", apex, rf"bust \+ {gp.APEX_UP_M}\)"),
    ("apex fallback", apex, rf"cx \+ s \* {gp.APEX_FALLBACK_X_M}, "),
    ("tights foot cut", func_src(FITTED, "tights_region"), rf"ank - {gp.FOOT_CUT_M}\)"),
    ("tights stirrup", func_src(FITTED, "tights_region"), rf"mid\[:, 1\]\) < {gp.STIRRUP_HALF_M}\b"),
    ("trousers foot cut", func_src(FITTED, "trousers_region"), rf"ank - {gp.FOOT_CUT_M}\)"),
    ("trousers stirrup", func_src(FITTED, "trousers_region"), rf"mid\[:, 1\]\) < {gp.STIRRUP_HALF_M}\)"),
    ("skirt hem dip", func_src(GT, "panel_spec"), rf"\(\"front\", {gp.SKIRT_HEM_DIP_M / 2}\)"),
    ("skirt hem dip x200", func_src(GT, "panel_spec"), r"-dip \* 200"),
]
for name, src, pat in literals:
    check(f"A source {name}", bool(re.search(pat, src)), True)

# --- the synthetic body ------------------------------------------------------------------------------------------


def girth(y):
    table = {1.20: 0.92, 1.18: 0.88, 1.22: 0.88, 1.12: 0.74, 1.40: 1.00}
    return table.get(round(y, 2), 0.80 if y > 1.0 else 0.95)


J = {"hips": [0.0, 0.95, 0.0], "neck": [0.0, 1.46, 0.0], "head": [0.0, 1.6, 0.0],
     "leftarm": [0.18, 1.40, 0.0], "rightarm": [-0.18, 1.40, 0.0], "leftforearm": [0.455, 1.40, 0.0],
     "rightforearm": [-0.455, 1.40, 0.0], "lefthand": [0.73, 1.40, 0.0], "righthand": [-0.73, 1.40, 0.0],
     "leftupleg": [0.09, 0.92, 0.0], "rightupleg": [-0.09, 0.92, 0.0], "leftleg": [0.09, 0.48, 0.0],
     "rightleg": [-0.09, 0.48, 0.0], "leftfoot": [0.10, 0.08, 0.0], "rightfoot": [-0.10, 0.08, 0.0]}
MEAS = {"height": 1.70, "floor_y": 0.0, "waist_y": 1.05, "waist_c": 0.70, "hip_y": 0.90, "hip_c": 0.95,
        "band_y": 1.275, "band_c": 0.80, "shoulder_y": 1.40, "shoulder_w": 0.40, "neck_y": 1.46,
        "neck_c": round(2 * math.pi * 0.06, 6), "arm_len": 0.55,
        "arm_c": [[0.05, 0.30], [0.25, 0.28], [0.5, 0.25], [0.97, 0.16]], "upper_arm_c": 0.28, "wrist_c": 0.16,
        "torso": [[round(y, 2), girth(round(y, 2))] for y in np.arange(0.68, 1.4001, 0.02)], "joints": J,
        "bra_apex": {"1": [0.09, 1.20, 0.12], "-1": [-0.09, 1.20, 0.12]}, "bra_fold": []}


def synthetic_frame():
    """The mannequin's front (exact ``front_camera`` mapping): torso girth / pi x 0.6 wide, T-posed arms, legs, feet,
    neck and head."""
    from PIL import Image, ImageDraw
    cam = front_camera.camera_for((-0.95, 0.95, 0.0, 1.70), 1000)
    im = Image.new("L", (cam["w"], cam["h"]), 0)
    d = ImageDraw.Draw(im)

    def poly(pts):
        d.polygon([front_camera.to_px(cam, x, y) for x, y in pts], fill=255)
    ys = np.arange(0.84, 1.42, 0.02)
    half = [min(0.2, girth(round(y, 2)) / math.pi * 0.6) for y in ys]
    poly([(h, y) for h, y in zip(half, ys)] + [(-h, y) for h, y in zip(half[::-1], ys[::-1])])
    poly([(-0.2, 1.37), (0.2, 1.37), (0.2, 1.45), (-0.2, 1.45)])
    for s in (1, -1):
        poly([(s * 0.15, 1.36), (s * 0.91, 1.375), (s * 0.91, 1.425), (s * 0.15, 1.45)])      # arm + hand
        poly([(s * 0.03, 0.86), (s * 0.15, 0.86), (s * 0.13, 0.08), (s * 0.06, 0.08)])        # leg
        poly([(s * 0.05, 0.0), (s * 0.16, 0.0), (s * 0.13, 0.09), (s * 0.06, 0.09)])          # foot
    poly([(-0.05, 1.40), (0.05, 1.40), (0.05, 1.56), (-0.05, 1.56)])
    poly([(-0.09, 1.55), (0.09, 1.55), (0.09, 1.70), (-0.09, 1.70)])
    mask = np.asarray(im) > 0
    return dict(gp.frame_of_mask(mask), camera=cam), im


FRAME, BASE = synthetic_frame()
REG = gp.register(FRAME, MEAS)


def P(**kw):
    p, _e = gt.validate_params(kw)
    return p


# --- B. key numbers ----------------------------------------------------------------------------------------------


def bra_geo(**kw):
    p = P(kind="bra", **kw)
    return gp.bra_geometry(p, MEAS, gt.fitted_spec(p, MEAS)["fitted"], 0.0)


def top_at(g, x):
    pts = g["tops"][1]
    return float(np.interp(x, [q[0] for q in pts], [q[1] for q in pts]))


for style, apex_top, outer_top in (("molded", 1.232, 1.192), ("balconette", 1.232, 1.232),
                                   ("triangle", 1.296, 1.135)):
    g = bra_geo(cup_style=style)
    check(f"B bra {style} top at apex", top_at(g, 0.09), apex_top)
    check(f"B bra {style} top at outer edge", g["tops"][1][-1], [0.165, outer_top])
g = bra_geo(cup_style="bandeau")
check("B bra bandeau band top", g["band_top"], 1.232)
check("B bra bandeau no gore", g["gore"], None)
for gore, inner, gw, gh in (("none", 0.008, None, None), ("narrow", 0.012, 0.016, 1.15), ("wide", 0.022, 0.026, 1.17)):
    g = bra_geo(center_gore=gore)
    check(f"B bra gore {gore} cup inner edge", g["tops"][1][0][0], inner)
    if gw is None:
        check(f"B bra gore {gore} none drawn", g["gore"], None)
    else:
        check(f"B bra gore {gore} rect", [g["gore"][1][0], g["gore"][2][1]], [gw, gh])
g = bra_geo(push_up=1.0)
check("B bra push-up apex top", top_at(g, 0.078), 1.252)
check("B bra push-up keeps the plain top as a guide", g["plain_tops"][1][gp.CURVE_N // 2], [0.09, 1.232])
for style, start_y in (("molded", 1.222), ("triangle", 1.286)):
    g = bra_geo(cup_style=style)
    check(f"B bra strap start {style}", g["straps"][1]["front"][0], [0.095, start_y])
g = bra_geo(straps="thin")
check("B bra thin strap end", g["straps"][1]["front"][1][0], 0.111)
check("B bra thin back", g["straps"][1]["back"][1], [0.111, 1.12])
g = bra_geo(straps="cross")
check("B bra cross back (crosses over)", g["straps"][1]["back"][1], [-0.111, 1.12])
g = bra_geo(straps="halter")
check("B bra halter end", g["straps"][1]["front"][1], [0.0648, 1.50])

check("B torso depth", gp.torso_depth(MEAS), 0.1121, 2e-4)
for nl, bottom, cut in (("crew", 1.39, True), ("scoop", 1.32, True), ("v", 1.28, True), ("boat", 1.40, False)):
    p = P(kind="top", shoulders="covered", neckline=nl)
    spec = gt.bodice_spec(p, MEAS)
    neck = gp.neckline_geometry(spec, MEAS, 0.0)
    check(f"B neckline {nl} cut", neck["cut"], cut)
    check(f"B neckline {nl} bottom", neck["bottom_y"], bottom)
    if cut:
        check(f"B neckline {nl} s_front", neck["s_front"], 0.0401 + spec["depth_m"], 3e-4)
        check(f"B neckline {nl} centre of the edge", neck["edge"][gp.CURVE_N // 2], [0.0, bottom])
    else:
        check(f"B neckline {nl} opening", neck["r_ring"], 0.124)
p = P(kind="jacket", neckline="v", collar="stand")
neck = gp.neckline_geometry(gt.bodice_spec(p, MEAS), MEAS, 0.0)
col = gp.collar_geometry(neck, 0.0)
check("B collar height", col["height_m"], 0.036)
check("B collar ends where the V runs down", min(abs(x) for poly in col["front"] for x, _y in poly) >= 0.0585 * 0.97 ** 3
      - 1e-3, True)

for length, start in (("wrist", 0.5005), ("elbow", 0.55 - (0.275 + 0.12 * 0.275))):
    p = P(kind="gloves", length=length)
    g = gp.glove_geometry(p, MEAS, gt.fitted_spec(p, MEAS)["fitted"], 0.18)
    check(f"B glove {length} cuff edge", g["start"], start)
p = P(kind="gloves")
plain = gp.glove_geometry(p, MEAS, gt.fitted_spec(p, MEAS)["fitted"], 0.18)
p = P(kind="gloves", cuff="flared")
flared = gp.glove_geometry(p, MEAS, gt.fitted_spec(p, MEAS)["fitted"], 0.18)
check("B glove offset", plain["stations"][-1][1] - gp._arm_width(MEAS, 0.55) / 2, 0.0076)
check("B glove flared cuff edge", flared["stations"][0][1] - plain["stations"][0][1], 0.015)
check("B glove fingerless tip", gp.glove_geometry(P(kind="gloves", fingers="fingerless"), MEAS,
                                                  gt.fitted_spec(P(kind="gloves", fingers="fingerless"),
                                                                 MEAS)["fitted"], 0.18)["tip"], 0.55 + 0.09)


def drawn(p):
    return gp.shapes(p, MEAS, REG)


def lowest(d, role):
    return min(REG.metres(*q)[1] for s in d["shapes"] if s["role"] == role for q in s["points"])


def role_ys(d, role):
    return sorted({round(REG.metres(*q)[1], 3) for s in d["shapes"] if s["role"] == role for q in s["points"]})


for feet, low in (("footless", 0.07), ("stirrup", 0.07)):
    check(f"B tights {feet} leg ends at the ankle - 1 cm", lowest(drawn(P(kind="tights", feet=feet)), "leg"), low, 2e-3)
check("B tights stirrup band", bool(role_ys(drawn(P(kind="tights", feet="stirrup")), "stirrup")), True)
check("B tights hold_up grip band", role_ys(drawn(P(kind="tights", tights_style="hold_up")), "band_edge"),
      [0.79 - 0.04], 2e-3)
check("B tights knee_high cuff", role_ys(drawn(P(kind="tights", tights_style="knee_high")), "band_edge"),
      [0.43 - 0.025], 2e-3)
check("B tights thigh_high has no band", role_ys(drawn(P(kind="tights", tights_style="thigh_high")), "band_edge"), [])
check("B trousers stirrup leg end", lowest(drawn(P(kind="trousers", leg_shape="skinny", seat="fitted",
                                                  hem="stirrup")), "leg"), 0.07, 2e-3)
sk = P(kind="skirt")
d = drawn(sk)
body = [REG.metres(*q) for s in d["shapes"] if s["role"] == "body" for q in s["points"]]
shape = gt.outline(sk, MEAS)
hem_y = shape["top_y"] - shape["knots"][-1][0]
check("B skirt hem sag", hem_y - min(y for _x, y in body), gp.SKIRT_HEM_DIP_M, 2e-3)
for wb, below in (("thin", 0.012), ("wide", 0.030)):
    check(f"B skirt waistband {wb} edge", role_ys(drawn(P(kind="skirt", waistband=wb)), "band_edge"),
          [round(shape["top_y"] - below, 3)], 2e-3)
check("B skirt waistband none draws no edge", role_ys(drawn(P(kind="skirt", waistband="none")), "band_edge"), [])

# --- C. pairwise distinctness ------------------------------------------------------------------------------------
#: (kind, param, a, b) the build does not tell apart from the front, and why.
EXCEPTIONS = {
    # the fabric is the cloth run's (drape) and the material's only — the cut is the same (``FABRICS``)
    **{(k, "fabric"): "drape / material only" for k in gt.BUILT_KINDS},
    # where the texture comes from (``TEXTURE_ONLY``): no drape, the cut is the same
    **{(k, f): "texture only" for k in gt.BUILT_KINDS for f in ("texture", "sleeve_print")},
}
#: The smallest patch of cloth that counts as a visible difference (2 x 2 cm).
XOR_MIN_CM2 = 4.0
w, h = BASE.size
for opt in gs.option_sets():
    key = (opt["kind"], opt["param"])
    if key in EXCEPTIONS:
        print("skip", key, "—", EXCEPTIONS[key])
        continue
    got = []
    for v in opt["values"]:
        p = gs.params_for(opt["kind"], opt["param"], v, opt["context"])
        if p is not None:
            d = drawn(p)
            got.append((v, gs.cloth_mask(d, w, h), gs.line_mask(d, w, h), d))
    for i in range(len(got)):
        for j in range(i + 1, len(got)):
            (va, ma, la, _da), (vb, mb, lb, _db) = got[i], got[j]
            iou = (ma & mb).sum() / max(1, (ma | mb).sum())
            liou = (la & lb).sum() / max(1, (la | lb).sum()) if (la | lb).any() else 1.0
            # a named feature: a patch of cloth at least XOR_MIN_CM2 in one and not the other (a slit, a lacing, a gore)
            xor_cm2 = float((ma ^ mb).sum()) / REG.scale ** 2 * 1e4
            ok = iou <= 0.97 or liou <= 0.9 or xor_cm2 >= XOR_MIN_CM2
            print(("ok  " if ok else "FAIL"), f"C {opt['kind']}.{opt['label']} {va} vs {vb}: cloth IoU {iou:.3f}"
                                              f" guides IoU {liou:.3f} differing cloth {xor_cm2:.1f} cm2")
            if not ok:
                FAILS.append(f"C {opt['kind']}.{opt['label']} {va}/{vb}")

if "--sheets" in sys.argv:
    out = Path(sys.argv[sys.argv.index("--sheets") + 1])
    out.mkdir(parents=True, exist_ok=True)
    for opt in gs.option_sets():
        ds = [(v, drawn(p)) for v in opt["values"]
              if (p := gs.params_for(opt["kind"], opt["param"], v, opt["context"])) is not None]
        if len(ds) > 1:
            box = gs.crop_box([d for _v, d in ds], w, h)
            base = BASE.convert("RGBA")
            gs.sheet([(f"{opt['param']} = {v}", gs.render(base, d).crop(box)) for v, d in ds],
                     f"{opt['kind']} · {opt['label']}").save(out / f"{opt['kind']}_{opt['label'].replace(' ', '_')}.png")

print("FAILED:" if FAILS else "all passed", FAILS or "")
sys.exit(1 if FAILS else 0)
