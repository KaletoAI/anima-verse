"""Smoke: the test poses of an accessory judge a side by the body's OUTER wall only
(``accessory_build.outer_wall_faces``, used through ``_body_context`` → ``_poses`` / ``attach_pendant``).

Usage: ./.venv/bin/python scripts/smoke_accessory_outer_wall.py   (no server, no world; synthetic geometry)

The body: a double-walled tube round the y axis, like every generated base body (an inward-facing second wall under
the skin). Outer wall: a closed 64-sided prism of radius R = 0.100, y 0..0.4, wound outward. Inner wall: a closed
64-sided prism of radius r = 0.094 (6 mm under the skin), y 0.006..0.394, wound INWARD (its normals face the axis).
Each prism: 64 sides × 2 triangles + 2 caps × 64 fan triangles = 256 faces → 512 faces in all. Bones: Hips (0, 0.05, 0)
→ Spine (0, 0.35, 0), one segment on the axis, ending inside both caps.

Expected values, derived by hand:

[1] The mask keeps exactly the 256 faces of the outer prism. A side face of the outer prism: normal radial out, the
    nearest segment point is on the axis at the face's height → dot > 0 → outer. Its top cap (y 0.4, normal +y): the
    nearest segment point is the Spine head (y 0.35), centroid − point has y +0.05 → dot > 0 → outer; bottom cap the
    same with y −0.05. The inner prism: sides face the axis (dot < 0); its top cap at y 0.394 faces −y, centroid − Spine
    head has y +0.044 → dot < 0 → inner; bottom cap likewise. So 256 outer faces, the first 256 indices.
[2] Signed distances, every point at the middle angle of a side (where a side lies at its apothem: R·cos(π/64) =
    0.1 · 0.998795 = 0.0998795, r·cos(π/64) = 0.094 · 0.998795 = 0.0938867), at y 0.2:
    ρ = 0.102 (2 mm out):   all faces +0.0021205, outer wall +0.0021205;
    ρ = 0.097 (in the wall): nearest is the skin (2.8795 mm < 3.1133 mm to the inner wall) → −0.0028795 both ways;
    ρ = 0.080 (20 mm in, in the cavity): all faces → the inner wall at 0.0938867 − 0.080 = 0.0138867, its normal faces
    the axis, the point lies on that side → +0.0138867 ("outside": the blind spot); outer wall only → −(0.0998795 −
    0.080) = −0.0198795.
    ρ = 0.070 (30 mm in): all faces +0.0238867, outer wall −0.0298795.
[3] Micro faces: a triangle with legs a in the plane x = 0.1 at y 0.2 (its normal +x, away from the axis): a = 0.374 mm
    → area a²/2 = 0.0699 mm² < 0.5 mm² → left out; a = 1.414 mm → 0.9997 mm² ≥ 0.5 → kept.
[4] Without any base bone pair (no parents) the mask keeps every face (nothing to judge by).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

from app.core.accessory_build import SIGN_MIN_AREA_M2, outer_wall_faces  # noqa: E402
from app.core.garment_shell import signed_distance  # noqa: E402

FAILS = []


def check(label, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + label + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        FAILS.append(label)


def prism(radius, y0, y1, n=64, inward=False):
    """A closed n-sided prism round the y axis, wound outward (or inward)."""
    ang = 2 * np.pi * np.arange(n) / n
    ring = np.c_[radius * np.cos(ang), np.zeros(n), radius * np.sin(ang)]
    V = np.vstack([ring + [0, y0, 0], ring + [0, y1, 0], [[0, y0, 0], [0, y1, 0]]])
    F = []
    for i in range(n):
        j = (i + 1) % n
        F += [(i, n + i, j), (j, n + i, n + j)]          # sides (outward: (b - a) × (c - a) points radially out)
        F += [(2 * n, i, j), (2 * n + 1, n + j, n + i)]  # bottom cap (−y), top cap (+y)
    F = np.asarray(F, np.int64)
    # orient: the outward choice has a positive volume
    vol = np.einsum("ij,ij->i", V[F[:, 0]], np.cross(V[F[:, 1]], V[F[:, 2]])).sum()
    if (vol < 0) != inward:
        F = F[:, [0, 2, 1]]
    return V, F


Vo, Fo_ = prism(0.100, 0.0, 0.4)
Vi, Fi = prism(0.094, 0.006, 0.394, inward=True)
P = np.vstack([Vo, Vi])
F = np.vstack([Fo_, Fi + len(Vo)])
HEADS = {"mixamorig:Hips": np.array([0.0, 0.05, 0.0]), "mixamorig:Spine": np.array([0.0, 0.35, 0.0])}
PARENTS = {"mixamorig:Spine": "mixamorig:Hips"}

print("[1] the mask")
mask = outer_wall_faces(P, F, HEADS, PARENTS)
check("[1] 512 faces in all", len(F) == 512, str(len(F)))
check("[1] exactly the 256 faces of the outer prism", mask.sum() == 256 and mask[:256].all(), str(mask.sum()))

print("[2] signed distances at the middle angle of a side, y 0.2")
mid = np.pi / 64
Fo = F[mask]
for rho, all_want, outer_want in ((0.102, 0.0021205, 0.0021205), (0.097, -0.0028795, -0.0028795),
                                  (0.080, 0.0138867, -0.0198795), (0.070, 0.0238867, -0.0298795)):
    X = np.array([[rho * np.cos(mid), 0.2, rho * np.sin(mid)]])
    got_all = float(signed_distance(X, P, F, kq=48)[0])
    got_outer = float(signed_distance(X, P, Fo, kq=48)[0])
    check(f"[2] rho {rho}: all faces {all_want:+.7f}", abs(got_all - all_want) < 2e-7, f"{got_all:+.7f}")
    check(f"[2] rho {rho}: outer wall {outer_want:+.7f}", abs(got_outer - outer_want) < 2e-7, f"{got_outer:+.7f}")

print("[3] micro faces")
check("[3] the threshold is 0.5 mm²", abs(SIGN_MIN_AREA_M2 - 0.5e-6) < 1e-15)
for a, keep in ((0.374e-3, False), (1.414e-3, True)):
    T = np.array([[0.1, 0.2, 0.0], [0.1, 0.2 + a, 0.0], [0.1, 0.2, a]])
    tri = np.array([[0, 1, 2]])
    # wound so its normal is +x (away from the axis): (b - a) × (c - a) = (0, a, 0) × (0, 0, a) = (a², 0, 0)
    m = outer_wall_faces(T, tri, HEADS, PARENTS)
    check(f"[3] a = {a * 1000:.3f} mm (area {a * a / 2 * 1e6:.4f} mm²) {'kept' if keep else 'left out'}",
          bool(m[0]) == keep, str(m))

print("[4] no bone pair")
check("[4] every face kept", outer_wall_faces(P, F, HEADS, {}).all())

print(f"\n{len(FAILS)} failed" if FAILS else "\nall passed")
sys.exit(1 if FAILS else 0)
