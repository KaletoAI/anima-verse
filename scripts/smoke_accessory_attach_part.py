"""Smoke: a linked part placed by its link (plan-anhaenger Task 3, ``accessory_build.curve_point_at`` /
``attach_part`` / ``attach_parts``).

Usage: ./.venv/bin/python scripts/smoke_accessory_attach_part.py   (no server, no world; synthetic geometry)

The part: a box 30 (x) × 40 (y) × 5 (z) mm — already thinnest in z, so ``normalise`` keeps its axes (size 40 mm =
its longest side). The body: the double-walled tube of ``smoke_accessory_outer_wall.py`` scaled to the belt here —
outer wall a closed 64-sided prism of R = 0.150 round the y axis (y 0.8..1.2), an inward-facing inner wall r = 0.140
(y 0.806..1.194). The test poses are replaced by the REST pose only (a monkeypatched ``_poses``: signed distance to the
faces it is given) — this smoke pins the placement and which faces each step gets; the posing is
``smoke_accessory_outer_wall.py``'s.

Expected values, derived by hand:

[1] a circle r = 0.15 round (0, 1, 0), 64 points, point k at θ = k·2π/64 with x = r·sin θ, z = r·cos θ (point 0 at +z,
    turning towards +x). Its azimuth atan2(x, z) is θ: ``curve_point_at`` 0° → 0, +90° → 16, −90° → 48, 45° → 8.
[2] flat at the front, band thickness 0.004 on that circle (the centre line): the part's back lies at
    z = 0.15 + 0.002 + 0.0005 = 0.1525 (its whole back face), its front at 0.1525 + 0.005 = 0.1575; centred in x and
    in height at the curve point (x 0, y 1.0).
[3] flat at +90°: the back at x = 0.1525, the thinnest extent (5 mm) along x.
[4] hang with drop 2 cm at the point y = 1.000 of the circle: the anchor (the top centre of the back) at
    y = 1.000 − 0.020 = 0.980; the push runs along the HORIZONTAL outward direction, so it never changes y — the
    anchor's y is 0.980 (± 0.1 mm) after the push too.
[4b] which faces each step gets: a hang part against the double-walled tube, its anchor 1 mm outside the outer wall
    (the curve on R = 0.151 minus the band offset: the band centre line r = 0.151 − 0.0025 = 0.1485 with thickness
    0.004 → back at 0.1485 + 0.002 + 0.0005 = 0.151). Part 5 mm deep, ``accessory_pendant.GAP_M`` = 0.003: the top
    back edge is 1 mm off the outer wall at every tilt ≥ 0, so the least push is 3.0 − 1.0 = 2.0 mm; the inner wall lies
    10 mm deeper and never decides it (the box carries the centre of its top back edge as a vertex — the gap is
    measured at vertices, the corners alone lie 15 mm to the side where the wall curves away) — the push against ``Fw`` (all faces) equals the one against ``Fo`` (outer wall
    only) within 0.01 mm. ``accessory_pendant.place`` is called with ``Fw``; ``_poses`` gets ``Fo``.
[5] flat on the tube with the band centre line at r = 0.1495 → back at 0.1495 + 0.002 + 0.0005 = 0.152 (2 mm outside the
    outer wall) → passes the rest pose. The same part 20 mm in (centre line r = 0.1295 → back at 0.132, inside the
    cavity between the walls — "outside" for all faces, inside for the outer wall) → ValueError "would sink into the
    body in the rest pose".
[6] two parts at the front (30 × 40 mm boxes): the second has ``part_errors[1]`` "it overlaps the buckle" (after a
    buckle) and "it overlaps the charm" (after a charm); the first is placed; nothing raises.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

from app.core import accessory_build as ab, accessory_pendant as ap  # noqa: E402
from app.core.garment_shell import signed_distance  # noqa: E402

FAILS = []


def check(label, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + label + (f"  ({detail})" if detail else ""))
    if not ok:
        FAILS.append(label)


def circle(r, y=1.0, n=64):
    t = 2 * np.pi * np.arange(n) / n
    return np.c_[r * np.sin(t), np.full(n, y), r * np.cos(t)]


def box(ex, ey, ez):
    V = np.array([[sx * ex / 2, sy * ey / 2, sz * ez / 2] for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)])
    # plus the centre of its top back edge (no face uses it): the gap is measured at the vertices, and a box's corners
    # alone sit 15 mm to the side, where the tube's wall curves away
    V = np.vstack([V, [[0.0, ey / 2, -ez / 2]]])
    F = np.array([[0, 1, 3], [0, 3, 2], [4, 6, 7], [4, 7, 5], [0, 4, 5], [0, 5, 1], [2, 3, 7], [2, 7, 6],
                  [0, 2, 6], [0, 6, 4], [1, 5, 7], [1, 7, 3]])
    return {"V": V, "F": F, "UV": np.zeros((9, 2)), "image": b"", "mime": "", "material": {}}


def prism(radius, y0, y1, n=64, inward=False):
    ang = 2 * np.pi * np.arange(n) / n
    ring = np.c_[radius * np.cos(ang), np.zeros(n), radius * np.sin(ang)]
    V = np.vstack([ring + [0, y0, 0], ring + [0, y1, 0], [[0, y0, 0], [0, y1, 0]]])
    F = []
    for i in range(n):
        j = (i + 1) % n
        F += [(i, n + i, j), (j, n + i, n + j), (2 * n, i, j), (2 * n + 1, n + j, n + i)]
    F = np.asarray(F, np.int64)
    vol = np.einsum("ij,ij->i", V[F[:, 0]], np.cross(V[F[:, 1]], V[F[:, 2]])).sum()
    if (vol < 0) != inward:
        F = F[:, [0, 2, 1]]
    return V, F


Vo, Fo_ = prism(0.150, 0.8, 1.2)
Vi, Fi = prism(0.140, 0.806, 1.194, inward=True)
PW = np.vstack([Vo, Vi])
FW = np.vstack([Fo_, Fi + len(Vo)])
FO = Fo_.copy()
BODY = SimpleNamespace(joint_names=["Hips", "Spine"])
SEEN = {"poses": [], "place": []}


def rest_only(rigged, body, dense, Pw, Fo, first, V, J, W):
    SEEN["poses"].append(Fo)
    sd = signed_distance(V, Pw, Fo, kq=48)
    return {"rest": {"gap_min_mm": round(float(sd.min()) * 1000, 2), "inside_share": float((sd < -0.0005).mean())}}


ab._poses = rest_only
_place = ap.place


def spy_place(Vn, anchor, outward, Pb, Fb, *a, **k):
    SEEN["place"].append(Fb)
    return _place(Vn, anchor, outward, Pb, Fb, *a, **k)


ap.place = spy_place


def attach(curve, link, thickness=0.004, placed=None, mesh=None):
    V = curve
    J = np.zeros((len(V), 4), np.int64)
    W = np.zeros((len(V), 4))
    W[:, 0] = 1.0
    return ab.attach_part(b"", BODY, None, PW, FW, FO, None, curve, V, J, W, link, mesh or box(0.030, 0.040, 0.005),
                          40.0, False, thickness, placed if placed is not None else [])


def link(role="charm", at=0.0, mount="flat", drop=0.0):
    return {"role": role, "index": 0, "item": "item_p", "size_mm": 40.0, "at_deg": at, "mount": mount,
            "drop_cm": drop}


print("[1] curve_point_at")
C = circle(0.15)
for deg, want in ((0.0, 0), (90.0, 16), (-90.0, 48), (45.0, 8)):
    got = ab.curve_point_at(C, deg)
    check(f"[1] {deg}° → {want}", got == want, str(got))

print("[2] flat at the front")
h = attach(C, link(at=0.0))
V = h["V"]
check("[2] back at z 0.1525", abs(float(V[:, 2].min()) - 0.1525) < 1e-6, f"{V[:, 2].min():.6f}")
check("[2] front at z 0.1575", abs(float(V[:, 2].max()) - 0.1575) < 1e-6, f"{V[:, 2].max():.6f}")
mid = (V.max(0) + V.min(0)) / 2
check("[2] centred x / y (box centre)", abs(float(mid[0])) < 1e-6 and abs(float(mid[1]) - 1.0) < 1e-6,
      f"{mid[0]:.6f} {mid[1]:.6f}")

print("[3] flat at +90°")
h = attach(C, link(at=90.0))
e = h["V"].max(0) - h["V"].min(0)
check("[3] back at x 0.1525", abs(float(h["V"][:, 0].min()) - 0.1525) < 1e-6, f"{h['V'][:, 0].min():.6f}")
check("[3] thinnest along x", abs(float(e[0]) - 0.005) < 1e-6, str(np.round(e, 5)))

print("[4] hang with drop 2 cm")
h = attach(circle(0.1485), link(at=0.0, mount="hang", drop=2.0))
anchor = h["metrics"]["anchor"]
check("[4] anchor y 0.980", abs(anchor[1] - 0.980) < 1e-4, str(anchor))
check("[4] push keeps y (top of the part ≤ 0.980 + 5 mm tilt)", float(h["V"][:, 1].max()) <= 0.980 + 0.005 + 1e-6,
      f"{h['V'][:, 1].max():.5f}")

print("[4b] Fw for the placement, Fo for the poses")
SEEN["place"].clear()
SEEN["poses"].clear()
h = attach(circle(0.1485), link(at=0.0, mount="hang"))
check("[4b] place got Fw", len(SEEN["place"]) == 1 and SEEN["place"][0] is FW)
check("[4b] _poses got Fo", len(SEEN["poses"]) == 1 and SEEN["poses"][0] is FO)
push_w = h["metrics"]["push_mm"]
anchor = np.asarray(h["metrics"]["anchor"])
Vn = ap.normalise(box(0.030, 0.040, 0.005)["V"], 40.0)
_v, how_o = _place(Vn, anchor, np.array([0.0, 0.0, 1.0]), PW, FO)
check("[4b] push 2.0 mm against Fw", abs(push_w - 2.0) < 0.05, str(push_w))
check("[4b] the same against Fo", abs(push_w - how_o["push_mm"]) <= 0.01, f"{push_w} vs {how_o['push_mm']}")
check("[4b] under PENDANT_MAX_PUSH_MM 6.0", push_w < ab.PENDANT_MAX_PUSH_MM)

print("[5] the outer wall decides")
h = attach(circle(0.1495), link(at=0.0))
check("[5] 2 mm outside passes", abs(float(h["V"][:, 2].min()) - 0.152) < 1e-6, f"{h['V'][:, 2].min():.6f}")
try:
    attach(circle(0.1295), link(at=0.0))
    check("[5] 20 mm in refused", False, "no error")
except ValueError as err:
    check("[5] 20 mm in refused", "would sink into the body in the rest pose" in str(err), str(err))

print("[6] two parts at the same point")
for first_role in ("buckle", "charm"):
    parts = [({**link(role=first_role), "index": 0}, box(0.030, 0.040, 0.005)),
             ({**link(role="charm"), "index": 1}, box(0.030, 0.040, 0.005))]
    J = np.zeros((len(C), 4), np.int64)
    W = np.zeros((len(C), 4))
    W[:, 0] = 1.0
    hung, errors = ab.attach_parts(b"", BODY, None, PW, FW, FO, None, circle(0.1495), circle(0.1495), J, W, parts,
                                   0.004)
    check(f"[6] after a {first_role}: the first placed", hung[0] is not None)
    check(f"[6] after a {first_role}: the second overlaps", hung[1] is None
          and errors.get(1) == f"it overlaps the {first_role}", str(errors))

print(f"\n{len(FAILS)} failed" if FAILS else "\nall passed")
sys.exit(1 if FAILS else 0)
