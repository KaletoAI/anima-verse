"""Smoke: A234 — the accessory kinds around the body and on a bone (``app/core/accessory_band.py``, the spec additions
in ``accessory_spec.py`` and the gates in ``accessory_build.py``).

Usage: ./.venv/bin/python scripts/smoke_accessory_around.py   (no server, no world; synthetic geometry)

Expected values, derived by hand:

[1] ``normalize``: belt width 4.0 cm, choker 1.5, strap 2.5 (``KIND_WIDTH_CM``), strap place "thigh"; bracelet
    thickness 2.5 mm, anklet 1.5, ring 2.0 (``KIND_THICKNESS_MM``), a bracelet in a cord material 2.5 (the cord
    default); earring {stud, 6.0}. ``image_part_mm``: a belt with the default buckle 50.0, with buckle None → None;
    earrings stud → None, drop → 18.0 (``PENDANT_DEFAULTS``), drop with pendant 25 → 25.0; necklace pendant 20 → 20.0.
    ``part_name``: belt → "Buckle", earrings → "Earring drop", necklace → "Pendant".
[2] ``frame`` on the bones hips (0, 0.9, 0), spine (0, 1.1, 0), spine1 (0, 1.2, 0): belt centre y = 0.9 + 0.5 · 0.2
    = 1.0; with a waistband top at 1.06 and the 4 cm width: 1.06 − 0.004 − 0.02 = 1.036; a top at 1.25 (above spine1)
    is no waistband → 1.0; height 3 cm → 1.03. Bracelet, forearm (0.4, 1.4, 0) → hand (0.65, 1.4, 0): axis (−1, 0, 0)
    (toward the trunk), centre = hand + 0.025 · axis = (0.625, 1.4, 0); height 1 cm → x 0.615.
    Choker, neck (0, 1.45, 0.05) → head (0, 1.525, 0.08): axis (0, 0.075, 0.03) / 0.080777 = (0, 0.928477, 0.371391),
    centre = neck + 0.45 · (0, 0.075, 0.03) = (0, 1.48375, 0.0635).
[3] ``section`` of a closed 64-sided cylinder of radius 0.1 round the y axis (y 0.8..1.2), 96 rays at y 1.0: every
    ray hits a side between its corners — the distance lies in [0.1 · cos(π/64), 0.1] = [0.099880, 0.1].
[4] ``surface_radius`` over that body with a garment cylinder of radius 0.12 under the band: every ray sits on it
    (0.12 ≤ 0.1 + ``UNDER_MAX_M`` 0.06) → t in [0.119855, 0.12], ``under_share`` 1.0; a garment at 0.2 is 0.1 beyond
    the skin (> 0.06) → ignored: t stays in [0.099880, 0.1], share 0.0.
[5] ``band_mesh``, inner radius 0.102 everywhere, 3 mm deep, rows ±2 cm, 96 angles: a closed ring of volume
    π (0.105² − 0.102²) · 0.04 · (96 / 2π) sin(2π / 96) = 7.8037e-5 · 0.99929 = 7.7982e-5 m³ (± 0.1 %), positive
    (outward faces).
[6] ``belt_top``: a bottom whose front-middle vertices reach y 1.07 → 1.07; a garment on slot "top" only → None.
[7] ``around_plausible``: a belt 0.8 m round, joints Hips/Spine, every pose clear → passes; 0.4 m → "40 cm round,
    expected 50–170 cm"; LeftArm 0.3 → "move with leftarm"; sit inside 0.01 → "inside in the sit pose"; a ring with
    LeftHandRing1 + LeftHand → passes, with Spine2 → "move with spine2".
[8] ``icosphere(0.003)``: 42 vertices (1 subdivision: 12 + 30 edges), every one 3 mm from the centre; ``torus``
    major 0.01, minor 0.001 across +x: the x extent is 2 · 0.001 · cos(π/8)… ≤ 0.002, the y / z extents
    2 · (0.01 + 0.001) = 0.022 at most and at least 2 · 0.011 · cos(π/32) = 0.02189.
[9] J4: ``graft_accessory`` of a ring record on the distance tier returns the blob it was given (no ring node).
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import numpy as np  # noqa: E402
from app.core import accessory_band as ab, accessory_build as build, accessory_spec as spec  # noqa: E402

FAIL = []


def check(name, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{name}: {got!r}" + ("" if ok else f" (expected {want!r})"))
    if not ok:
        FAIL.append(name)


def near(name, got, want, tol):
    check(name, float(want) if abs(float(got) - float(want)) <= tol else round(float(got), 6), want)


# [1] spec
n = spec.normalize
check("[1] belt width / at", (n({"kind": "belt"})["band"]["width_cm"], n({"kind": "strap"})["band"]["at"]), (4.0, "thigh"))
check("[1] choker / strap width", (n({"kind": "choker"})["band"]["width_cm"], n({"kind": "strap"})["band"]["width_cm"]),
      (1.5, 2.5))
check("[1] tube thickness", tuple(n({"kind": k})["chain"]["thickness_mm"] for k in ("bracelet", "anklet", "ring")),
      (2.5, 1.5, 2.0))
check("[1] cord bracelet", n({"kind": "bracelet", "metal": "leather"})["chain"]["thickness_mm"], 2.5)
check("[1] earring default", n({"kind": "earrings"})["earring"], {"style": "stud", "size_mm": 6.0})
check("[1] image part belt", spec.image_part_mm(n({"kind": "belt"})), 50.0)
check("[1] image part belt off", spec.image_part_mm(n({"kind": "belt", "buckle": None})), None)
check("[1] image part stud", spec.image_part_mm(n({"kind": "earrings"})), None)
check("[1] image part drop", spec.image_part_mm(n({"kind": "earrings", "earring": {"style": "drop"}})), 18.0)
check("[1] image part drop 25", spec.image_part_mm(n({"kind": "earrings", "earring": {"style": "drop"},
                                                      "pendant": {"size_mm": 25}})), 25.0)
check("[1] image part necklace", spec.image_part_mm(n({"kind": "necklace", "pendant": {"size_mm": 20}})), 20.0)
check("[1] part names", tuple(spec.part_name({"kind": k}) for k in ("belt", "earrings", "necklace")),
      ("Buckle", "Earring drop", "Pendant"))

# [2] frame
BONES = {"mixamorig:Hips": [0, 0.9, 0], "mixamorig:Spine": [0, 1.1, 0], "mixamorig:Spine1": [0, 1.2, 0],
         "mixamorig:LeftForeArm": [0.4, 1.4, 0], "mixamorig:LeftHand": [0.65, 1.4, 0]}
belt = n({"kind": "belt"})
near("[2] belt centre y", ab.frame(belt, BONES)["centre"][1], 1.0, 1e-9)
near("[2] belt under waistband", ab.frame(belt, BONES, belt_top_y=1.06)["centre"][1], 1.036, 1e-9)
near("[2] belt top above spine1", ab.frame(belt, BONES, belt_top_y=1.25)["centre"][1], 1.0, 1e-9)
near("[2] belt height 3", ab.frame(n({"kind": "belt", "band": {"height_cm": 3}}), BONES)["centre"][1], 1.03, 1e-9)
fr = ab.frame(n({"kind": "bracelet"}), BONES, "left")
check("[2] bracelet axis / centre", (np.round(fr["axis"], 9).tolist(), np.round(fr["centre"], 9).tolist()),
      ([-1.0, 0.0, 0.0], [0.625, 1.4, 0.0]))
near("[2] bracelet height 1", ab.frame(n({"kind": "bracelet", "band": {"height_cm": 1}}), BONES, "left")["centre"][0],
     0.615, 1e-9)

NECK = {"mixamorig:Neck": [0, 1.45, 0.05], "mixamorig:Head": [0, 1.525, 0.08]}
fr = ab.frame(n({"kind": "choker"}), NECK)
check("[2] choker axis / centre", (np.round(fr["axis"], 6).tolist(), np.round(fr["centre"], 6).tolist()),
      ([0.0, 0.928477, 0.371391], [0.0, 1.48375, 0.0635]))


# [3] / [4] section on a cylinder
def cylinder(r, y0=0.8, y1=1.2, k=64):
    a = 2 * np.pi * np.arange(k) / k
    ring = np.c_[r * np.sin(a), np.zeros(k), r * np.cos(a)]
    P = np.vstack([ring + [0, y0, 0], ring + [0, y1, 0], [[0, y0, 0], [0, y1, 0]]])
    F = []
    for i in range(k):
        j = (i + 1) % k
        F += [[i, j, k + j], [i, k + j, k + i], [2 * k, j, i], [2 * k + 1, k + i, k + j]]
    return P, np.array(F)


P, F = cylinder(0.1)
fr = ab.frame(belt, BONES)
fr["centre"] = np.array([0.0, 1.0, 0.0])
t, dirs = ab.section(P, F, fr, [0.0], reach=0.3, pick="outer")
check("[3] cylinder section", (bool(np.all(t >= 0.1 * np.cos(np.pi / 64) - 1e-9)), bool(np.all(t <= 0.1 + 1e-9))),
      (True, True))
Pg, Fg = cylinder(0.12)
s = ab.surface_radius(P, F, [(Pg, Fg)], fr, [0.0], reach=0.3, what="belt")
check("[4] on the garment", (bool(np.all(s["t"] >= 0.12 * np.cos(np.pi / 64) - 1e-9)),
                             bool(np.all(s["t"] <= 0.12 + 1e-9)), s["under_share"]), (True, True, 1.0))
Pf, Ff = cylinder(0.2)
s = ab.surface_radius(P, F, [(Pf, Ff)], fr, [0.0], reach=0.3, what="belt")
check("[4] far garment ignored", (bool(np.all(s["t"] <= 0.1 + 1e-9)), s["under_share"]), (True, 0.0))

# [5] band mesh volume
offsets = np.array([-0.02, -0.01, 0.0, 0.01, 0.02])
_t, dirs = ab.section(P, F, fr, [0.0], reach=0.3, pick="outer")
V, Fm, _N = ab.band_mesh(fr, offsets, np.full((5, 96), 0.102), dirs, 0.003)
vol = float(np.einsum("ij,ij->i", V[Fm[:, 0]], np.cross(V[Fm[:, 1]], V[Fm[:, 2]])).sum()) / 6
want = np.pi * (0.105 ** 2 - 0.102 ** 2) * 0.04 * (96 / (2 * np.pi)) * np.sin(2 * np.pi / 96)
check("[5] band volume within 0.1 %", bool(abs(vol - want) <= 1e-3 * want and vol > 0), True)
print(f"       volume {vol:.5e} (hand {want:.5e})")

# [6] belt_top
front = np.array([[0.0, 1.07, 0.1], [0.01, 1.05, 0.1], [0.0, 0.9, -0.1]])
check("[6] waistband top", build.belt_top([{"P": front, "slots": ["bottom"], "footwear": False}], BONES), 1.07)
check("[6] a top is no waistband", build.belt_top([{"P": front, "slots": ["top"], "footwear": False}], BONES), None)


# [7] gates
def gate(key, **m):
    base = {"length_m": {"": 0.8}, "max_segment_ratio": 1.2, "joints": {"mixamorig:Hips": 0.9, "mixamorig:Spine": 0.4},
            "inside_share": 0.0, "poses": {p: {"gap_min_mm": 2.0, "inside_share": 0.0} for p in ("rest", "walk", "sit", "run")}}
    base.update(m)
    try:
        build.around_plausible(key, base)
        return "passes"
    except ValueError as e:
        return str(e)


check("[7] belt passes", gate("belt"), "passes")
check("[7] belt too short", "40 cm round, expected 50–170 cm" in gate("belt", length_m={"": 0.4}), True)
check("[7] belt on the arm", "move with leftarm" in gate("belt", joints={"mixamorig:LeftArm": 0.3}), True)
check("[7] belt inside sitting", "inside in the sit pose" in gate("belt", poses={
    "rest": {"gap_min_mm": 2, "inside_share": 0.0}, "sit": {"gap_min_mm": -1, "inside_share": 0.01}}), True)
check("[7] ring passes", gate("ring", length_m={"left": 0.055},
                              joints={"mixamorig:LeftHandRing1": 0.9, "mixamorig:LeftHand": 0.3}), "passes")
check("[7] ring on the spine", "move with spine2" in gate("ring", length_m={"left": 0.055},
                                                         joints={"mixamorig:Spine2": 0.5}), True)

# [8] primitives
Vs, Fs = ab.icosphere(0.003)
check("[8] icosphere", (len(Vs), bool(np.allclose(np.linalg.norm(Vs, axis=1), 0.003))), (42, True))
Vt, Ft, _ = ab.torus(np.zeros(3), np.array([1.0, 0, 0]), 0.01, 0.001)
ext = np.ptp(Vt, 0)
check("[8] torus extents", (bool(ext[0] <= 0.002 + 1e-12), bool(0.022 * np.cos(np.pi / 32) - 1e-9 <= ext[1] <= 0.022 + 1e-9),
                            bool(0.022 * np.cos(np.pi / 32) - 1e-9 <= ext[2] <= 0.022 + 1e-9)), (True, True, True))

# [9] LOD
check("[9] ring off the distance tier", build.graft_accessory(b"X", "c", "item", {"kind": "ring", "asig": "a"}, "a",
                                                           low=True), b"X")

print()
print(f"{len(FAIL)} check(s) failed: {FAIL}" if FAIL else "all checks passed")
sys.exit(1 if FAIL else 0)
