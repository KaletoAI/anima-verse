"""A174 items 2+3: the fit's room allowance acts over the WHOLE piece and may be negative (tighter).

Usage: ./.venv/bin/python scripts/smoke_fit_room_allowance.py

``garment_fit.room_offset`` moves each vertex along the body's outward unit normal n by ``(width·n_x, 0,
depth·n_z)``, smoothed, an inward move limited to the vertex's distance above the clearance (CLEAR_M 11.9 mm).
Everything below is derived by hand on cylinders (voxel 1 mm: ± 0.5 mm for the field's trilinear sampling):

[1] Trunk: body = closed cylinder R 0.150 (256 sides), piece = tube r 0.170 (96 sides) -> gap 20.0 mm all round.
    width = depth = e: n is radial, so every vertex — the hip SIDES (n = ±x) and the front/back (n = ±z) alike —
    moves by e: gap 20 + e.
      e +6 mm -> 26.0 at the side and at the front;  e −5 mm -> 15.0;  e −10 mm -> the inward limit 20 − 11.9 = 8.1
      mm -> 11.9 (never into the body, never closer than the clearance).
    Before A174 the depth shift was ``ease·wz`` with ``wz = clip((z − centre_z)/ramp)``: at a hip side z = centre_z
    -> 0.0 mm (the yellow region of the report did not respond).
[2] Legs (the inner thighs / crotch side): body = two closed cylinders R 0.070 at x = ±0.090 (the legs' inner
    surfaces at x = ±0.020), piece = a tube r 0.082 about the LEFT leg -> gap 12.0 mm. width 5 mm, depth 0:
      inner-thigh vertex (x = −0.008, n = +x)  -> moves +5 mm toward the middle: own-leg gap 17.0; the other leg is
      then 23 mm away, so the field reads 17.0;
      outer vertex (x = −0.172, n = −x) -> 17.0;  front vertex (z = +0.082, n = +z) -> 12.0 (depth 0: unmoved).
    Before A174: ``depth_shift`` at the inner thigh (z = 0 = centre_z) -> 0.0 mm.
[3] Settings: allowance −10 / −6 / −3 and depth −10 / −6 / −3 validate; −5 and −20 are refused.
"""
import sys, tempfile
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.core import paths
paths.init(tempfile.mkdtemp())
from app.core import garment_fit as gf, garment_fit_settings as gfs
sys.path.insert(0, str(ROOT / "scripts"))
from smoke_garment_mesh_view import cylinder

fails = 0
def near(label, got, want, tol=0.5):
    global fails
    ok = abs(got - want) <= tol
    fails += not ok
    print(('OK  ' if ok else 'FAIL'), f"{label}: {got:.2f} (want {want:.2f} ± {tol})")
def check(label, got, want):
    global fails
    ok = got == want
    fails += not ok
    print(('OK  ' if ok else 'FAIL'), label, got, '' if ok else f'(want {want})')

def field(P, F, X):
    return gf.body_sdf(P, F, vox=0.001, bounds=(X.min(0) - 0.03, X.max(0) + 0.03))

print("[1] trunk: room all round, negative clamped at the clearance")
B, BF = cylinder(0.150, 256, 0.0, 0.4, rings=201, closed=True)
T, TF = cylinder(0.170, 96, 0.15, 0.25, rings=11)
sdf = field(B, BF, T)
adj = gf._adjacency(TF, len(T))
mid = 5 * 96
side, front = mid + 0, mid + 24          # angle 0 (x = +r, the hip side), angle 90° (z = +r, the front)
near("gap before (side)", sdf.sample(T[[side]])[0] * 1000, 20.0)
for e, want in ((0.006, 26.0), (-0.005, 15.0), (-0.010, 11.9)):
    X = T + gf.room_offset(T, sdf, width=e, depth=e, adjacency=adj)
    d = field(B, BF, X).sample(X[[side, front]]) * 1000
    near(f"e {e * 1000:+.0f} mm: hip side gap", d[0], want)
    near(f"e {e * 1000:+.0f} mm: front gap", d[1], want)
near("old depth_shift at the hip side", float(gf.depth_shift(T[[side]], 0.006, centre_x=0.0, centre_z=0.0,
                                                         x_limit=1.0, y_limit=1.0, ramp=0.0051)[0]) * 1000, 0.0, 1e-9)

print("[2] legs: the inner thigh takes the width")
L1, LF1 = cylinder(0.070, 256, 0.0, 0.4, rings=201, closed=True)
L2 = L1.copy(); L1 = L1 + [-0.09, 0, 0]; L2 = L2 + [0.09, 0, 0]
legs_P = np.vstack([L1, L2]); legs_F = np.vstack([LF1, LF1 + len(L1)])
G, GF = cylinder(0.082, 96, 0.15, 0.25, rings=11)
G = G + [-0.09, 0, 0]
sdf = field(legs_P, legs_F, G)
adj = gf._adjacency(GF, len(G))
inner, outer, frontv = mid + 0, mid + 48, mid + 24
near("gap before (inner thigh)", sdf.sample(G[[inner]])[0] * 1000, 12.0)
X = G + gf.room_offset(G, sdf, width=0.005, depth=0.0, adjacency=adj)
d = field(legs_P, legs_F, X).sample(X[[inner, outer, frontv]]) * 1000
near("inner thigh gap at width +5 mm", d[0], 17.0)
near("outer thigh gap at width +5 mm", d[1], 17.0)
near("front gap at width +5 mm, depth 0", d[2], 12.0)
near("old depth_shift at the inner thigh", float(gf.depth_shift(G[[inner]], 0.005, centre_x=0.0, centre_z=0.0,
                                                             x_limit=1.0, y_limit=1.0, ramp=0.0051)[0]) * 1000, 0.0, 1e-9)

print("[3] negative settings")
check("allowance -10/-6/-3", [gfs.validate({"allowance": v})["allowance"] for v in (-10, -6, -3)], [-10, -6, -3])
check("depth -10/-6/-3", [gfs.validate({"depth": v})["depth"] for v in (-10, -6, -3)], [-10, -6, -3])
for key, bad in (("allowance", -5), ("depth", -20)):
    try:
        gfs.validate({key: bad}); check(f"{key} {bad} refused", False, True)
    except ValueError:
        check(f"{key} {bad} refused", True, True)
check("normalise keeps -6", (gf.allowance_choice({"allowance": -6}), gf.depth_choice({"depth": -6})), (-6, -6))
print('FAILED' if fails else 'ALL OK')
sys.exit(1 if fails else 0)
