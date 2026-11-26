#!/usr/bin/env python3
"""Smoke: the forepart in front of the toes (gate ``toe_front``, ``footwear_fit.TOE_FRONT_MAX``), the toe box attempt
(``TOE_FRONT_TARGET``, ``garment_footwear.fit_compute``'s second attempt) and the skin seen through the shoe
(``footwear_cut.skin_seen``) — 2026-11-26.

Usage:  ./.venv/bin/python scripts/smoke_footwear_toe_front.py

No storage, no hub, no server, no Blender: pure functions on hand-made arrays, ``fit_compute`` with its mesh readers
and ``fit_pair`` / ``_fit_attempt`` replaced by stand-ins that only record their calls.

Expected, by hand:

[T1] forepart_area over stations gx = 0, 1, 2, 3, 4, 5 with widths 0, 1, 1, 1, 0.5, 0: the trapezoids between the
     stations are 0.5, 1, 1, 0.75, 0.25; the area in front of each station is their sum from it on:
     3.5, 3.0, 2.0, 1.0, 0.25, 0.
[T2] front_station(room 1.0) -> the first station with at most 1.0 in front: x = 3; room 0.2 -> x = 5; room 0.25
     -> x = 4 (equal counts); stations 3 and 4 not usable (ok False) with room 1.0 -> x = 5; room -1 -> the
     fallback 9.
[T3] The limits from the measured distribution (footwear_fit docstring): TOE_FRONT_MAX = 0.08 (0.065 x 1.2 = 0.078,
     rounded up to 0.08) above every right-looking value 0.065 and below every Sneekers value 0.128;
     TOE_FRONT_TARGET = 0.065 < TOE_FRONT_MAX; the gate is a closed shoe's ("max", 0.08).
[T4] fit_compute: a first attempt refused by ``toe_front`` alone with ``height_ready`` False gets the second attempt
     with ``fit_height=True`` (calls: fit_height False, then True); a first attempt refused by ``ball_placement_mm``
     with ``height_ready`` False gets none (one call); an accepted first attempt gets none (one call).
[T5] skin_seen on a box shoe (glTF axes: x across, y up, z forward; walls x = +-0.03, z = 0 .. 0.10, y = 0 .. 0.05,
     a floor at y = 0, open on top) around a box foot (x +-0.025, z 0.005 .. 0.095, y 0.002 .. 0.08 — standing
     out of the rim like a leg), pixels of 2 mm from 4 px outside the shoe's lower corner:
     - no hole: 0 mm2 from every side (the foot above the rim hangs together with the empty pixels around it);
     - a 10 x 10 mm hole in the back wall (x -0.005 .. 0.005, y 0.021 .. 0.031): from the back (camera at -z)
       the hole's edges lie in the middle of pixel columns 16 / 21 ((-0.005 + 0.038) / 0.002 = 16.5, 21.5) and
       rows 14 / 19 ((0.021 + 0.008) / 0.002 = 14.5, 19.5); the wall's samples on the edges cover those, so the
       free pixels are columns 17 .. 20 and rows 15 .. 18 = 4 x 4 = 16 px x 4 mm2 = 64 mm2 of foot seen through
       it (the foot at z 0.005 lies nearer than the front wall behind it); every other side 0; worst 64.
[T6] The skin gate from the measured distribution (footwear_cut docstring): right-looking closed shoes 0 - 4 mm2,
     skin seen in the renders from 36 mm2 on -> SKIN_SEEN_MAX_MM2 = 20 (five 2-mm pixels); the 64 mm2 hole of [T5]
     is above it, no hole below. Auto answers it with heel room: AUTO_LENGTH_GATES = ("visible_poke",
     "skin_seen_mm2").
"""
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

FAILS = []


def check(cond, label):
    print(("ok   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


def quads(rects):
    """Axis-aligned rectangles -> (positions, faces): each (axis, value, (a0, a1), (b0, b1)) with the two other axes
    in order."""
    P, F = [], []
    for axis, value, (a0, a1), (b0, b1) in rects:
        others = [i for i in range(3) if i != axis]
        base = len(P)
        for a, b in ((a0, b0), (a1, b0), (a1, b1), (a0, b1)):
            v = [0.0, 0.0, 0.0]
            v[axis], v[others[0]], v[others[1]] = value, a, b
            P.append(v)
        F += [[base, base + 1, base + 2], [base, base + 2, base + 3]]
    return np.array(P, np.float64), np.array(F, np.int64)


def box_shoe(hole: bool):
    X, Z, H = 0.03, 0.10, 0.05
    rects = [(1, 0.0, (-X, X), (0.0, Z)),           # floor (x, z)
             (0, -X, (0.0, H), (0.0, Z)), (0, X, (0.0, H), (0.0, Z)),   # sides (y, z)
             (2, Z, (-X, X), (0.0, H))]              # front (x, y)
    if hole:   # the back wall around a 10 x 10 mm hole
        rects += [(2, 0.0, (-X, X), (0.0, 0.021)), (2, 0.0, (-X, X), (0.031, H)),
                  (2, 0.0, (-X, -0.005), (0.021, 0.031)), (2, 0.0, (0.005, X), (0.021, 0.031))]
    else:
        rects += [(2, 0.0, (-X, X), (0.0, H))]
    return quads(rects)


def box_foot():
    x, z0, z1, y0, y1 = 0.025, 0.005, 0.095, 0.002, 0.08
    return quads([(0, -x, (y0, y1), (z0, z1)), (0, x, (y0, y1), (z0, z1)),
                  (2, z0, (-x, x), (y0, y1)), (2, z1, (-x, x), (y0, y1)),
                  (1, y0, (-x, x), (z0, z1)), (1, y1, (-x, x), (z0, z1))])


def main() -> int:
    from app.core import footwear_cut, footwear_fit as ff, garment_footwear, glb_mesh

    # [T1] / [T2]
    gx = np.arange(6.0)
    front = ff.forepart_area(gx, np.array([0, 1, 1, 1, 0.5, 0]))
    check(np.allclose(front, [3.5, 3.0, 2.0, 1.0, 0.25, 0.0]), f"[T1] forepart_area {front.tolist()}")
    ok = np.ones(6, bool)
    check(ff.front_station(gx, front, ok, 1.0, 9) == 3.0, "[T2] room 1.0 -> 3")
    check(ff.front_station(gx, front, ok, 0.2, 9) == 5.0, "[T2] room 0.2 -> 5")
    check(ff.front_station(gx, front, ok, 0.25, 9) == 4.0, "[T2] room 0.25 -> 4")
    check(ff.front_station(gx, front, np.array([1, 1, 1, 0, 0, 1], bool), 1.0, 9) == 5.0, "[T2] unusable 3, 4 -> 5")
    check(ff.front_station(gx, front, ok, -1.0, 9) == 9.0, "[T2] none -> fallback")

    # [T3]
    check(ff.TOE_FRONT_MAX == 0.08 and 0.065 < ff.TOE_FRONT_MAX < 0.128, "[T3] TOE_FRONT_MAX 0.08 between 0.065 and 0.128")
    check(ff.TOE_FRONT_TARGET == 0.065 < ff.TOE_FRONT_MAX, "[T3] TOE_FRONT_TARGET 0.065")
    check(ff.CLOSED_GATES == {"toe_front": ("max", 0.08)}, "[T3] the closed shoe's gate")

    # [T4]
    class Result:
        def __init__(self, gates, ready):
            self.record = {"gates": gates, "scale": {"height_ready": ready}}

    def run(first_gates, ok_first):
        calls = []

        def fake_fit_pair(*a, fit_height=False, **k):
            calls.append(fit_height)
            return Result(first_gates if not fit_height else {}, False)

        def fake_attempt(result, prims, joints, insole=None):
            ok_ = ok_first if len(calls) == 1 else True
            return {"ok": ok_, "result": result, "reasons": [] if ok_ else ["refused"],
                    "gates": {"ok": ok_, "reasons": []}}

        with patch.object(glb_mesh, "static_arrays", lambda b: (np.zeros((3, 3)), np.zeros((1, 3), int), None, None,
                                                                 None, None)), \
                patch.object(glb_mesh, "body_arrays", lambda b: None), \
                patch.object(glb_mesh, "joint_bind_matrices", lambda b: {}), \
                patch.object(glb_mesh, "body_primitive_arrays", lambda b: []), \
                patch.object(ff, "fit_pair", fake_fit_pair), \
                patch.object(ff, "too_flat_reason", lambda r: None), \
                patch.object(garment_footwear, "_fit_attempt", fake_attempt), \
                patch.object(garment_footwear, "_attempt_out", lambda *a, **k: {}):
            garment_footwear.fit_compute(b"", {}, b"", None, "footwear", "i", "f", "/nonexistent",
                                         allowance={"width": 0, "length": 0})
        return calls

    check(run({"toe_front": {"value": 0.15, "ok": False}}, False) == [False, True],
          "[T4] toe_front refused -> the toe box attempt")
    check(run({"ball_placement_mm": {"value": 9.0, "ok": False}}, False) == [False],
          "[T4] another refusal, not height ready -> no second attempt")
    check(run({"toe_front": {"value": 0.03, "ok": True}}, True) == [False], "[T4] accepted -> one attempt")

    # [T5]
    Pf, Ff = box_foot()
    body = glb_mesh.Prim(positions=Pf, faces=Ff)
    for hole, want in ((False, 0.0), (True, 64.0)):
        Ps, Fs = box_shoe(hole)
        shoe = glb_mesh.GarmentMesh(positions=Ps, normals=None, uvs=np.zeros((len(Ps), 2)), indices=Fs.reshape(-1),
                                    joints=np.zeros((len(Ps), 4), np.int64), weights=np.zeros((len(Ps), 4)),
                                    joint_names=[], image=None, mime=None, material=None)
        seen = footwear_cut.skin_seen(body, {"left": {"foot": shoe}})
        views = seen["mm2"]["left"]
        others = {v: a for v, a in views.items() if v != "back"}
        check(abs(views["back"] - want) < 1e-6 and all(a == 0.0 for a in others.values())
              and abs(seen["worst_mm2"] - want) < 1e-6,
              f"[T5] {'hole' if hole else 'no hole'}: back {views['back']} mm2 (want {want}), others {others}")

    # [T6]
    check(footwear_cut.SKIN_SEEN_MAX_MM2 == 20.0 and 4.0 < footwear_cut.SKIN_SEEN_MAX_MM2 < 36.0,
          "[T6] SKIN_SEEN_MAX_MM2 20 between 4 and 36")
    check(garment_footwear.AUTO_LENGTH_GATES == ("visible_poke", "skin_seen_mm2"), "[T6] Auto answers skin_seen_mm2")

    print("\n" + ("ALL OK" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}"))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
