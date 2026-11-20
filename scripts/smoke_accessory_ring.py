"""Smoke: A238 — the ring, sized from the skeleton (``app/core/accessory_ring.py``, ``accessory_build.make_ring``).

Usage: ./.venv/bin/python scripts/smoke_accessory_ring.py   (no server, no world; synthetic skeletons)

Expected values, derived by hand from the module docstring (reference hand: radius 8.75 mm on the ring finger at a
hand width of 60 mm and a ring-finger bone of 31.5 mm; thumb 10.25 mm at 32 mm; range 7–11 mm at 1.70 m):

[1] ``normalize({"kind": "ring"})``: finger "ring", side "left" (a ring is on one hand; "both" is stored as left),
    ring {along 0.5}, band width 0.3 cm, thickness 2.0 mm. A width outside the ring's 0.15–1.2 cm is another kind's
    band and becomes the default 0.3, not clamped: 0.05 → 0.3, 5 → 0.3, and a ring stored before A238 with the old
    band default {width_cm 4.0} → 0.3 (clamping would give 1.2); the range ends 0.15 and 1.2 are kept; along
    0.95 → 0.85, 0.0 → 0.15; finger "thumb" and side "right" are kept. ``BUILT_KINDS`` holds "ring".
    ``shape_inputs`` = {finger, side, along, width_cm, thickness_mm} (no layer, no height); ``_wants_under`` False.
[2] ``size`` — LeftHandIndex1 (0, 0, 0), LeftHandPinky1 (0.06, 0, 0) → hand width 60 mm; LeftHandRing1 (0.03, 0, 0)
    → LeftHandRing2 (0.03, 0, 0.0315) → bone 31.5 mm; height 1.70: r = 8.75 · sqrt(1 · 1) = 8.75 mm, range
    [7, 11], not clamped. Every length doubled (hand 120 mm, bone 63 mm): r = 8.75 · sqrt(2 · 2) = 17.5 → clamped to
    11.0 mm at 1.70 m, to 11 · 1.87 / 1.70 = 12.1 mm at 1.87 m. Thumb (Thumb2 (0, 0, 0) → Thumb3 (0, 0, 0.032), hand
    60 mm): 10.25 · 1 = 10.25 mm. No LeftHandRing2 bone → KeyError('lefthandring2'); a 5 mm bone → ValueError
    ("too short").
[3] ``frame`` along 0.25 of Ring1 → Ring2 above: centre (0.03, 0, 0.007875), axis (0, 0, 1), front (0, 1, 0) (the
    back of the hand, square to the axis), bone "lefthandring1".
[4] ``band`` r 0.00875, width 0.003, thickness 0.002, 48 angles: 48 · 4 = 192 vertices, 48 · 4 · 2 = 384 triangles;
    every vertex lies 0.00875 or 0.01075 from the axis (±1e-12); the extent along the axis is 0.003; signed volume
    π (0.01075² − 0.00875²) · 0.003 · (48 / 2π) sin(2π / 48) = 3.6757e-7 · 0.99715 = 3.6652e-7 m³ (± 0.1 %), positive.
    ``centre_line``: 48 points 0.00875 + 0.001 = 0.00975 from the axis.
[5] ``check`` with range [7, 11] on the box (−0.01, −0.02, −0.02)–(0.07, 0.02, 0.05): r 8.75 mm, centre inside the
    hand box → passes; the centre at z 0.0625, 1.25 cm past the box's z max 0.05 and 1.05 cm past the gated edge
    0.05 + 0.002 (``BOX_MARGIN_M``) → "its centre lies outside the hand"; r 12 mm → "inner radius 12.0 mm, expected 7.0–11.0 mm"; no hand skin →
    "the hand has no skin".
[6] ``make_ring`` on a synthetic body (``glb_mesh.body_arrays`` replaced): the skeleton of [2], a hand box of 8
    points skinned to LeftHand from (−0.01, −0.02, −0.02) to (0.07, 0.02, 0.05), a foot point at y 0 and a head
    point at y 1.70 skinned to Hips (height 1.70). Spec ring / left / along 0.5: inner_radius_mm 8.75, clamped
    False, every vertex weight 1.0 on joint 2 (LeftHandRing1), metrics joints {"mixamorig:LeftHandRing1": 1.0},
    length_m {"left": 2π · 0.00875 = 0.055}, 384 triangles, landmark centre (0.03, 0, 0.01575). The same body without
    the hand points → ValueError ("the hand has no skin").
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import numpy as np  # noqa: E402
from app.core import accessory_build as ab, accessory_ring as ar, accessory_spec as s, glb_mesh  # noqa: E402

FAIL = []


def check(name, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{name}: {got!r}" + ("" if ok else f" (expected {want!r})"))
    if not ok:
        FAIL.append(name)


# [1] the description
n = s.normalize({"kind": "ring"})
check("[1] defaults", (n["finger"], n["side"], n["ring"], n["band"]["width_cm"], n["chain"]["thickness_mm"]),
      ("ring", "left", {"along": 0.5}, 0.3, 2.0))
check("[1] both -> left", s.normalize({"kind": "ring", "side": "both"})["side"], "left")
check("[1] width outside -> default", tuple(s.normalize({"kind": "ring", "band": {"width_cm": w}})["band"]["width_cm"]
                                            for w in (0.05, 5, 4.0)), (0.3, 0.3, 0.3))
check("[1] width range ends kept", tuple(s.normalize({"kind": "ring", "band": {"width_cm": w}})["band"]["width_cm"]
                                         for w in (0.15, 1.2)), (0.15, 1.2))
old_ring = {"kind": "ring", "band": {"height_cm": 0.0, "width_cm": 4.0, "layer": "auto", "material": "from_image",
                                     "at": "thigh"}, "side": "both", "finger": "ring"}
check("[1] pre-A238 ring", s.normalize(old_ring)["band"]["width_cm"], 0.3)
check("[1] along clamp", (s.normalize({"kind": "ring", "ring": {"along": 0.95}})["ring"]["along"],
                          s.normalize({"kind": "ring", "ring": {"along": 0.0}})["ring"]["along"]), (0.85, 0.15))
t = s.normalize({"kind": "ring", "finger": "thumb", "side": "right"})
check("[1] thumb right", (t["finger"], t["side"]), ("thumb", "right"))
check("[1] built", "ring" in s.BUILT_KINDS, True)
check("[1] shape inputs", ab.shape_inputs(n), {"finger": "ring", "side": "left", "along": 0.5, "width_cm": 0.3,
                                               "thickness_mm": 2.0})
check("[1] no layer under it", ab._wants_under(n), False)

# [2] the size
BONES = {"mixamorig:LeftHandIndex1": [0, 0, 0], "mixamorig:LeftHandPinky1": [0.06, 0, 0],
         "mixamorig:LeftHandRing1": [0.03, 0, 0], "mixamorig:LeftHandRing2": [0.03, 0, 0.0315],
         "mixamorig:LeftHandThumb2": [0, 0, 0], "mixamorig:LeftHandThumb3": [0, 0, 0.032]}
z = ar.size(BONES, "ring", "left", 1.70)
check("[2] reference", (round(z["radius_m"] * 1000, 6), [round(x, 6) for x in z["range_mm"]], z["clamped"]),
      (8.75, [7.0, 11.0], False))
BIG = {k: [2 * c for c in v] for k, v in BONES.items()}
check("[2] doubled, clamped", (round(ar.size(BIG, "ring", "left", 1.70)["radius_m"] * 1000, 6),
                               ar.size(BIG, "ring", "left", 1.70)["clamped"]), (11.0, True))
check("[2] doubled at 1.87 m", round(ar.size(BIG, "ring", "left", 1.87)["radius_m"] * 1000, 6), 12.1)
check("[2] thumb", round(ar.size(BONES, "thumb", "left", 1.70)["radius_m"] * 1000, 6), 10.25)
try:
    ar.size({k: v for k, v in BONES.items() if not k.endswith("Ring2")}, "ring", "left", 1.70)
    check("[2] missing bone", "no error", "KeyError")
except KeyError as e:
    check("[2] missing bone", e.args[0], "lefthandring2")
try:
    ar.size({**BONES, "mixamorig:LeftHandRing2": [0.03, 0, 0.005]}, "ring", "left", 1.70)
    check("[2] short bone", "no error", "ValueError")
except ValueError as e:
    check("[2] short bone", "too short" in str(e), True)

# [3] the frame
fr = ar.frame(BONES, "ring", "left", 0.25)
check("[3] frame", (np.round(fr["centre"], 9).tolist(), np.round(fr["axis"], 9).tolist(),
                    np.round(fr["front"], 9).tolist(), fr["bone"]),
      ([0.03, 0.0, 0.007875], [0.0, 0.0, 1.0], [0.0, 1.0, 0.0], "lefthandring1"))

# [4] the band
V, F, N = ar.band(fr, 0.00875, 0.003, 0.002)
d = V - fr["centre"]
radial = np.linalg.norm(d - np.outer(d @ fr["axis"], fr["axis"]), axis=1)
check("[4] counts", (len(V), len(F)), (192, 384))
check("[4] radii", bool(np.all(np.minimum(np.abs(radial - 0.00875), np.abs(radial - 0.01075)) < 1e-12)), True)
check("[4] width", round(float(np.ptp(d @ fr["axis"])), 9), 0.003)
a_, b_, c_ = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
vol = float(np.einsum("ij,ij->i", a_, np.cross(b_, c_)).sum()) / 6.0
want = np.pi * (0.01075 ** 2 - 0.00875 ** 2) * 0.003 * (48 / (2 * np.pi)) * np.sin(2 * np.pi / 48)
check("[4] volume", bool(vol > 0 and abs(vol - want) / want < 1e-3), True)
cl = ar.centre_line(fr, 0.00875, 0.002)
dc = cl - fr["centre"]
check("[4] centre line", (len(cl), bool(np.allclose(np.linalg.norm(dc - np.outer(dc @ fr["axis"], fr["axis"]), axis=1),
                                                    0.00975, atol=1e-12))), (48, True))

# [5] the gate
HAND = np.array([[x, y, zz] for x in (-0.01, 0.07) for y in (-0.02, 0.02) for zz in (-0.02, 0.05)])


def gate(centre, radius_m, hand=HAND):
    try:
        ar.check(np.asarray(centre, float), hand, {"radius_m": radius_m, "range_mm": [7.0, 11.0]})
        return "passes"
    except ValueError as e:
        return str(e)


check("[5] passes", gate([0.03, 0, 0.01], 0.00875), "passes")
check("[5] outside", "its centre lies outside the hand" in gate([0.03, 0, 0.0625], 0.00875), True)
check("[5] radius", "inner radius 12.0 mm, expected 7.0–11.0 mm" in gate([0.03, 0, 0.01], 0.012), True)
check("[5] no skin", "the hand has no skin" in gate([0.03, 0, 0.01], 0.00875, HAND[:0]), True)

# [6] make_ring on a synthetic body
NAMES = ["mixamorig:Hips", "mixamorig:LeftHand", "mixamorig:LeftHandRing1", "mixamorig:LeftHandIndex1",
         "mixamorig:LeftHandPinky1", "mixamorig:LeftHandRing2"]


def body(with_hand=True):
    pts = np.vstack([HAND if with_hand else np.zeros((0, 3)), [[0.0, 0.0, 0.0], [0.0, 1.70, 0.0]]])
    joints = np.zeros((len(pts), 4), np.int64)
    weights = np.zeros((len(pts), 4))
    weights[:, 0] = 1.0
    if with_hand:
        joints[:8, 0] = 1
    jp = {k.split(":")[-1].lower(): np.asarray(v, float) for k, v in BONES.items()}
    return glb_mesh.BodyMesh(positions=pts, faces=np.zeros((0, 3), np.int64), uvs=np.zeros((len(pts), 2)),
                             joints=joints, weights=weights, joint_names=NAMES, joint_positions=jp)


real = glb_mesh.body_arrays
try:
    glb_mesh.body_arrays = lambda blob: body()
    out = ab.make_ring(b"", n)
    m = out["metrics"]
    check("[6] radius", (m["inner_radius_mm"], m["clamped"]), (8.75, False))
    check("[6] rigid", (bool(np.all(out["J"][:, 0] == 2)), bool(np.all(out["W"][:, 0] == 1.0)),
                        bool(np.all(out["W"][:, 1:] == 0.0))), (True, True, True))
    check("[6] joints", m["joints"], {"mixamorig:LeftHandRing1": 1.0})
    check("[6] length", m["length_m"], {"left": 0.055})
    check("[6] triangles", m["triangles"], 384)
    check("[6] centre", out["landmarks"]["left"]["centre"], [0.03, 0.0, 0.01575])
    glb_mesh.body_arrays = lambda blob: body(with_hand=False)
    try:
        ab.make_ring(b"", n)
        check("[6] no hand", "no error", "ValueError")
    except ValueError as e:
        check("[6] no hand", "the hand has no skin" in str(e), True)
finally:
    glb_mesh.body_arrays = real

print()
print(f"{len(FAIL)} check(s) failed: {FAIL}" if FAIL else "all checks passed")
sys.exit(1 if FAIL else 0)
