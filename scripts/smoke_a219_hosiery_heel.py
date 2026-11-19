"""A219 — see-through shell colour, the misregistered limb strip, the shoe's heel taper.

Usage: ./.venv/bin/python scripts/smoke_a219_hosiery_heel.py   (no server, no world DB, no storage)

Expected values derived by hand:
[S0] ``garment_shell.see_through_text``: "black lace stockings", "Fishnet Tights", "sheer black hosiery",
     "see-through blouse", "Spitzenstrümpfe" -> True; "grey melange sweater", "white ribbed knit top", "black glitter
     dress", "cabinet", "bonnet", "" -> False (an opaque textured piece never loses its backdrop: ``build_shell``
     unmixes only a NAMED see-through piece whose views pass the gate).
[S1] ``unmix_backdrop`` on a lace: a 60x60 RGB image, backdrop (200, 200, 200), the ghost mask = rows/cols 10..49.
     Inside, 2-px column stripes: cols with (j // 2) even fabric (10, 10, 10), the others a 50 % mix
     10 + 0.5 * 190 = 105. Inner (eroded 3 px) = rows/cols 13..46 = 34 x 34 = 1156 px; mixed columns among 13..46
     (j // 2 odd): 13, 14, 15, 18, 19, ..., 42, 43, 46 -> 17 of 34 -> mixed 0.5, pure 0.5; F = 10 (the pure
     cluster), bg 200 neutral, interleave 1.0 -> gate True; applied (None = by the gate): a mixed pixel becomes
     105 - 0.5 * 190 = 10, fabric stays 10, the backdrop 200. ``apply=False``: unchanged (105 stays).
[S2] opaque pieces, the gate (the name gate of S0 comes first in ``build_shell``):
     (a) a smooth highlight: left half (cols 10..29) 10, right half (30..49) 105 -> inner mixed cols 30..46 = 17 of
         34 -> 0.5; within 4 px of fabric (col 29): cols 30..33 -> interleave 4 / 17 = 0.235 < 0.4 -> gate False.
     (b) black glitter: fabric 10 with a white (255) speck every 10th column and row -> the specks lie off the line
         (T = 245/190 = 1.29 > 1.05) and are no mix: mixed 0 -> gate False, nothing changes.
     (c) a tinted backdrop (200, 150, 100): channel spread 100 > 12 -> gate False even for the lace of S1.
[S3] ``misregistered_strip`` (mm_px 1, MISREG_MM 30 -> 30 px, dilation ceil(30/3) = 10 px, span 150 px): the body
     = rows 0..99, cols 20..79 of a 100x120 view.
     (a) the ghost shifted: cols 35..94 -> body cols 20..34 bare; depth (EDT inside the body) 1..15 <= 30, row
         distance to the ghost 15..1 <= 30; ghost outside the 10-px dilated body (cols 10..89) = cols 90..94, row
         distance from col 20 = 70 <= 150 -> the strip = cols 20..34 x 100 rows = 1500 px.
     (b) a cut-out: the ghost = the body without rows 40..59 x cols 40..59 -> hole-filled outline covers it -> 0.
     (c) a slit at the edge, the ghost fitting the body: the body without rows 30..69 x cols 20..29 -> no ghost
         outside the body anywhere -> 0.
     (d) a hem / a toeless foot: the shifted ghost of (a) in rows 0..49 only -> rows 50..99 have no ghost in the row
         -> only rows 0..49: 15 x 50 = 750.
[S4] ``ring_closed``: 10 rings (y = 0.003 + 0.004 i), per ring 4 front head-on, 4 back head-on, 1 side point; front
     members everywhere. (a) back members in rings 4..9 (median of 5 keeps ring 4), every BACK point on the strip ->
     both-worn rings 4..9, carried down to 0 (front worn) -> the 40 back head-on points, never a side or front point
     (front not on the strip). (b) the same, no point on the strip -> 0. (c) back members 0..5 -> rings 0..5 (ring
     6's window [1,1,0,0,0] -> 0), nothing carried upward -> 24.
[S5] ``footwear_fit.width_taper``: stations 0..5 raw, k 1, factor 1.25, ball at 4, clearance 0.002; insole edges
     (-0.025, 0.025) at 0, (-0.03, 0.03) after -> middle 0, halves 0.025 / 0.03; foot edges (raw; metres = raw ·
     1.25) NaN, (-0.02, 0.02), (-0.016, 0.032), (-0.0232, 0.0232), (-0.05, 0.05), NaN.
     1. centred needs (half m + 0.002) / (0.03): st1 0.027/0.03 = 0.9 -> 1; st2 half 0.024 raw = 0.03 m ->
        0.032/0.03 = 1.06667; st3 0.029 m -> 1.03333; st4, 5 -> 1.25; st0 unmeasured -> the first measured.
        Running max [1, 1, 1.06667, 1.06667, 1.25, 1.25] -> share0 [0.8, 0.8, 0.853333, 0.853333, 1, 1].
     2. w = (1 - share0) / 0.2 = [1, 1, 0.733333, 0.733333, 0, 0]; the foot's middle st2 0.008 -> shift
        0.008 · 0.733333 = 0.005867; st1 / st3 middle 0 -> 0.
     3. st2: rest |0.008 - 0.005867| · 1.25 = 0.002667 -> (0.03 + 0.002667 + 0.002) / (0.03 · 1.25) = 0.924444
        > 0.853333; st1 0.72 -> 0.8 (the floor 1/1.25); st3 (0.029 + 0.002) / 0.0375 = 0.826667 < 0.853333.
        Running max -> share [0.8, 0.8, 0.924444, 0.924444, 1, ...]. Kept x 0..4: share [0.8, 0.8, 0.924444,
        0.924444, 1.0], mid [0, 0, 0, 0, 0], centre [0, 0, 0.005867, 0, 0], min_factor 1.0.
     The map: (0.5, 0.03, 0.01) -> z 0.008 (normal (0, 0, 1) stays: flat there); (2, 0, 0.01) -> 0.005867 + 0.01 ·
     0.924444 = 0.015111; (9, 0, 0.01) -> 0.01; a foot needing the full factor everywhere -> None; factor 1 -> None.
[S6] a fixture fit (scripts/_footwear_fixtures.py: the closed clog, walls z = ±0.04 raw, no shaft; the box feet 0.12
     wide, k 1.023599, factor 0.12 / 0.081888 = 1.46542 as smoke_footwear_fit [F13] (a) — +-3e-3: the narrow heel tilts
     the fitted midline, the ball band reads 0.2 % wider) with the HEEL narrowed: foot
     box vertices at x <= -0.03 at z = zc ± 0.03 (0.06 wide). Heel stations: the centred need (0.03 + 0.006) /
     (0.04 · 1.023599) = 0.879 -> 1 -> share 1 / factor (0.682398 at 1.46542), the foot centred -> no shift. So the right shoe's
     vertices behind body x -0.045 stand at z 0.10 ± 0.04 · 1.023599 = ±0.040944 (+-2e-4) — the uniform factor
     (commit baac1102c, the module read by ``git show`` and run on the same fixture: the pre-fix proof) left them at
     ±0.06; the gap a side 0.06 - 0.03 = 30 mm -> 10.9 mm. The fit is accepted, every cut gate 0 / ok, and the cut's
     footprint at the heel (cut-frame x <= 0.02 m) stands at ±0.040944 too — the cut and the walls agree.
[S7] versions: ``garment_shell.SHELL_VERSION`` 8 (A219 set 5, A220 6, A226 7, A235 8), ``footwear_fit.FOOTWEAR_FIT_VERSION`` 20.
"""
import subprocess
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import numpy as np  # noqa: E402

import _footwear_fixtures as fx  # noqa: E402
from app.core import footwear_cut, footwear_insole, glb_mesh  # noqa: E402
from app.core import footwear_fit as ff  # noqa: E402
from app.core import garment_shell as gs  # noqa: E402

fails = []


def check(name, got, want, tol=None):
    ok = (abs(got - want) <= tol) if tol is not None else (got == want)
    print(("OK   " if ok else "FAIL ") + f"{name}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        fails.append(name)


print("[S0] the name gate")
for text, want in (("black lace stockings", True), ("Fishnet Tights", True), ("sheer black hosiery", True),
                   ("see-through blouse", True), ("Spitzenstrümpfe", True), ("grey melange sweater", False),
                   ("white ribbed knit top", False), ("black glitter dress", False), ("cabinet", False),
                   ("bonnet", False), ("", False)):
    check(f"[S0] {text!r}", gs.see_through_text(text), want)

print("[S1] lace on the backdrop")
mask = np.zeros((60, 60), bool)
mask[10:50, 10:50] = True
cols = np.arange(60)


def lace(bg=(200.0, 200.0, 200.0)):
    img = np.empty((60, 60, 3))
    img[:] = bg
    stripe = np.where((cols // 2) % 2 == 0, 10.0, 105.0)
    img[10:50, 10:50] = stripe[10:50][None, :, None]
    return img


out, info = gs.unmix_backdrop(lace(), mask)
check("[S1] gate", info["gate"], True)
check("[S1] mixed 0.5", info["mixed_share"], 0.5)
check("[S1] pure 0.5", info["pure_share"], 0.5)
check("[S1] interleave 1.0", info["interleave"], 1.0)
check("[S1] mixed pixel -> 10", float(out[20, 14, 0]), 10.0, 1e-6)
check("[S1] fabric stays 10", float(out[20, 12, 0]), 10.0, 1e-6)
check("[S1] backdrop stays 200", float(out[2, 2, 0]), 200.0, 1e-6)
out_n, info_n = gs.unmix_backdrop(lace(), mask, apply=False)
check("[S1] apply False: unchanged", (float(out_n[20, 14, 0]), info_n["see_through"]), (105.0, False))

print("[S2] opaque pieces")
img2 = np.full((60, 60, 3), 200.0)
img2[10:50, 10:30] = 10.0
img2[10:50, 30:50] = 105.0
out2, info2 = gs.unmix_backdrop(img2, mask)
check("[S2a] highlight: gate False", info2["gate"], False)
check("[S2a] interleave 4/17", info2["interleave"], round(4 / 17, 3))
check("[S2a] highlight unchanged", float(out2[20, 40, 0]), 105.0, 1e-6)
img3 = np.full((60, 60, 3), 200.0)
img3[10:50, 10:50] = 10.0
img3[10:50:10, 10:50:10] = 255.0
out3, info3 = gs.unmix_backdrop(img3, mask)
check("[S2b] glitter: mixed 0", info3["mixed_share"], 0.0)
check("[S2b] glitter: gate False, speck kept", (info3["gate"], float(out3[20, 20, 0])), (False, 255.0))
_, info4 = gs.unmix_backdrop(lace((200.0, 150.0, 100.0)), mask)
check("[S2c] tinted backdrop: gate False", info4["gate"], False)

print("[S3] the misregistered strip")
body = np.zeros((100, 120), bool)
body[:, 20:80] = True
shifted = np.zeros_like(body)
shifted[:, 35:95] = True
check("[S3a] shifted ghost: 1500 px", int(gs.misregistered_strip(shifted, body, 1.0).sum()), 1500)
check("[S3a] the strip is cols 20..34",
      bool(gs.misregistered_strip(shifted, body, 1.0)[:, 20:35].all()), True)
cut_out = body.copy()
cut_out[40:60, 40:60] = False
check("[S3b] cut-out: 0", int(gs.misregistered_strip(cut_out, body, 1.0).sum()), 0)
slit = body.copy()
slit[30:70, 20:30] = False
check("[S3c] slit, ghost fits the body: 0", int(gs.misregistered_strip(slit, body, 1.0).sum()), 0)
hem = shifted.copy()
hem[50:] = False
check("[S3d] hem / toeless: 750", int(gs.misregistered_strip(hem, body, 1.0).sum()), 750)

print("[S4] ring_closed")
ys, hf, hb, ring = [], [], [], []
for i in range(10):
    for kind in ["f"] * 4 + ["b"] * 4 + ["s"]:
        ys.append(0.003 + 0.004 * i)
        hf.append(kind == "f")
        hb.append(kind == "b")
        ring.append(i)
y, hf, hb, ring = np.array(ys), np.array(hf), np.array(hb), np.array(ring)
limb = np.ones(len(y), bool)
none = np.zeros(len(y), bool)
c_a = gs.ring_closed(y, limb, hf, hf, hb, hb & (ring >= 4), none, hb)
check("[S4a] 40 back points", (int(c_a.sum()), bool((c_a & ~hb).any())), (40, False))
check("[S4b] nothing on the strip: 0", int(gs.ring_closed(y, limb, hf, hf, hb, hb & (ring >= 4), none, none).sum()),
      0)
c_c = gs.ring_closed(y, limb, hf, hf, hb, hb & (ring <= 5), none, hb)
check("[S4c] back worn 0..5: 24", (int(c_c.sum()), bool(c_c[ring >= 6].any())), (24, False))

print("[S5] width_taper")
st = np.arange(6, dtype=float)
il = np.array([(-0.025, 0.025)] + [(-0.03, 0.03)] * 5)
fl = np.array([(np.nan, np.nan), (-0.02, 0.02), (-0.016, 0.032), (-0.0232, 0.0232), (-0.05, 0.05),
               (np.nan, np.nan)])
tp = ff.width_taper(st, il, fl, 1.0, 1.25, 4.0, 0.002)
check("[S5] x_raw", tp["x_raw"], [0.0, 1.0, 2.0, 3.0, 4.0])
check("[S5] share", tp["share"], [0.8, 0.8, 0.924444, 0.924444, 1.0])
check("[S5] mid", tp["mid_raw"], [0.0, 0.0, 0.0, 0.0, 0.0])
check("[S5] centre", tp["centre_raw"], [0.0, 0.0, 0.005867, 0.0, 0.0])
check("[S5] min_factor", tp["min_factor"], 1.0)
Q = np.array([[0.5, 0.03, 0.01], [2.0, 0.0, 0.01], [9.0, 0.0, 0.01]])
Qt, nt = ff.width_taper_map(Q, tp, np.array([[0.0, 0.0, 1.0]] * 3))
check("[S5] z at 0.5", float(Qt[0, 2]), 0.008, 1e-9)
check("[S5] x, y kept", (float(Qt[0, 0]), float(Qt[0, 1])), (0.5, 0.03))
check("[S5] z at 2", float(Qt[1, 2]), 0.015111, 1e-6)
check("[S5] z in front", float(Qt[2, 2]), 0.01, 1e-12)
check("[S5] normal at 0.5", [round(float(v), 9) for v in nt[0]], [0.0, 0.0, 1.0])
check("[S5] full need -> None", ff.width_taper(st, il, np.array([(-0.05, 0.05)] * 6), 1.0, 1.25, 4.0, 0.002), None)
check("[S5] factor 1 -> None", ff.width_taper(st, il, fl, 1.0, 1.0, 4.0, 0.002), None)

print("[S6] the fixture fit with a narrow heel")
real_body = fx.foot_body


def narrow_heel(*a, **kw):
    P_, F_, J_, W_, N_ = real_body(*a, **kw)
    P_ = np.array(P_, np.float64)
    for zc in fx.FOOT_ZC.values():
        box = (np.abs(P_[:, 2] - zc) <= 0.06 + 1e-9) & (P_[:, 1] <= fx.FOOT_H + 1e-9) & (P_[:, 0] <= -0.03 + 1e-9)
        P_[box, 2] = zc + np.sign(P_[box, 2] - zc) * 0.03
    return P_, F_, J_, W_, N_


fx.foot_body = narrow_heel
try:
    glb = fx.foot_body_glb(0.12)
finally:
    fx.foot_body = real_body
joints = glb_mesh.joint_bind_matrices(glb)
Pc, Fc = fx.clog()
ins_c = footwear_insole.analyse_arrays(Pc, Fc)


def heel_half(module):
    fit_ = module.fit_pair(ins_c, fx.shoe_garment(Pc, Fc), glb_mesh.body_arrays(glb), joints)
    pr = fit_.parts["right"]["foot"].positions
    return fit_, float(np.abs(pr[pr[:, 0] <= -0.045, 2] - 0.10).max())


fit, half = heel_half(ff)
sc = fit.record["scale"]
check("[S6] accepted", (fit.ok, fit.reasons), (True, []))
check("[S6] factor 1.46542 (+-3e-3)", sc["width_factor"], 1.46542, 3e-3)
check("[S6] heel share = 1 / factor", sc["width_taper"]["share"][0], 1.0 / sc["width_factor"], 2e-6)
check("[S6] heel walls ±0.040944", half, 0.040944, 2e-4)
prim = glb_mesh.body_primitive_arrays(glb)[0]
cut = footwear_cut.cut_description(fit, ins_c)
after, _st = footwear_cut.apply_cut(prim, cut, joints)
gates = footwear_cut.cut_gates(after, fit.parts, cut, joints=joints, body_before=prim)
check("[S6] cut gates ok", (gates["ok"], {k: v["value"] for k, v in gates["gates"].items()}),
      (True, {k: 0.0 for k in gates["gates"]}))
fp = np.asarray(cut["sides"]["right"]["footprint"], np.float64).reshape(-1, 2)
check("[S6] footprint at the heel ±0.040944", float(np.abs(fp[fp[:, 0] <= 0.02, 1]).max()), 0.040944, 2e-4)
old_src = subprocess.run(["git", "show", "baac1102c:app/core/footwear_fit.py"], cwd=ROOT, capture_output=True,
                         text=True).stdout
old = types.ModuleType("footwear_fit_baac1102c")
old.__file__ = str(ROOT / "app/core/footwear_fit.py")
exec(compile(old_src, old.__file__, "exec"), old.__dict__)
_fit_old, half_old = heel_half(old)
check("[S6] baac1102c: heel walls ±0.06 (the uniform factor)", half_old, 0.06, 2e-4)

print("[S7] versions")
check("[S7] SHELL_VERSION 8 (A235)", gs.SHELL_VERSION, 8)
check("[S7] FOOTWEAR_FIT_VERSION 20", ff.FOOTWEAR_FIT_VERSION, 20)

print("ALL OK" if not fails else f"{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
