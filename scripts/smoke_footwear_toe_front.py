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
[T3] The limits from the measured distribution (footwear_fit docstring), read on the foot reaching furthest (the
     smaller side): TOE_FRONT_MAX = 0.06 (0.048 x 1.2 = 0.0576, rounded up to 0.06) above every right-looking value
     0.048 and below every Sneekers value 0.118; TOE_FRONT_TARGET = 0.048 < TOE_FRONT_MAX; the gate is a closed
     shoe's ("max", 0.06).
[T4] fit_compute: a first attempt refused by ``toe_front`` alone with ``height_ready`` False gets the second attempt
     with ``fit_height=True`` (calls: fit_height False, then True); a first attempt refused by ``ball_placement_mm``
     with ``height_ready`` False gets none (one call); an accepted first attempt gets none (one call).
[T5] skin_seen on a box shoe (glTF axes: x across, y up, z forward; walls x = +-0.03, z = 0 .. 0.10, y = 0 .. 0.05,
     a floor at y = 0, open on top; every face cut into tiles of at most 10 mm) around a box foot (x +-0.025,
     z 0.005 .. 0.095, y 0.002 .. 0.08 — standing out of the rim like a leg), pixels of SKIN_SEEN_PX_M 1 mm from
     4 px outside the shoe's lower corner (lo = (-0.034, -0.004)):
     - no hole: 0 mm2 from every side (the foot above the rim hangs together with the empty pixels around it);
     - a 10 x 10 mm hole in the back wall (x -0.0055 .. 0.0045, y 0.0205 .. 0.0305): from the back (camera at -z)
       the hole's edges lie in the middle of pixel columns 28 / 38 ((-0.0055 + 0.034) / 0.001 = 28.5, 38.5) and
       rows 24 / 34 ((0.0205 + 0.004) / 0.001 = 24.5, 34.5); the wall's samples on the edges cover those, so the
       free pixels are columns 29 .. 37 and rows 25 .. 33 = 9 x 9 = 81 px x 1 mm2 = 81 mm2 of foot seen through
       it (the foot at z 0.005 lies nearer than the front wall behind it); a 9 x 9 square survives the 2 x 2
       opening whole; every other side 0; worst 81.
[T5b] THROUGH THE WALL (fit version 23): the box shoe without a hole, 0.0505 high (so its top edge lies in the middle
     of a pixel row), around a box foot x +-0.0255, z -0.002 .. 0.088, y 0.0025 .. 0.08 — its heel 2 mm out through
     the back wall (z 0) and standing out of the rim. lo = (-0.034, -0.004). From the back (depth -z): the foot's back
     face (depth 0.002) is nearer than the wall (depth 0), the gap 0.002 <= SKIN_POKE_M 0.003 and more than
     SKIN_SEEN_EPS_M -> seen and through the wall where both are: columns floor((-0.0255 + 0.034) / 0.001) = 8 ..
     floor((0.0255 + 0.034) / 0.001) = 59 (52), rows floor((0.0025 + 0.004) / 0.001) = 6 .. floor((0.0505 + 0.004) /
     0.001) = 54 (49) -> 52 x 49 = 2548 px = 2548 mm2, a rectangle the 4 x 4 opening keeps whole. The foot above the
     rim hangs together with it and touches empty pixels: the ENCLOSED term reads 0 (so did skin_seen on 0c27b0b70,
     which had only that term). Front: the front wall (0.10) lies in front of the foot (0.088); the sides: the side
     walls (0.03) in front of the foot (0.0255); the foot seen above the rim or behind the back wall has no shoe in
     its pixel -> 0 from every other side.
[T6] The skin gate from the distribution over every stored shoe on every body through the chain (footwear_cut
     comment): SKIN_SEEN_PX_M 1 mm, SKIN_SEEN_EPS_M 0.25 mm, SKIN_SEEN_OPEN_PX 2, SKIN_SEEN_MAX_MM2 8; the 81 mm2
     hole of [T5] is above it, no hole below. Auto answers it with heel room: AUTO_LENGTH_GATES = ("visible_poke",
     "skin_seen_mm2").
[T7] fit_compute with Auto length, both attempts cut ("replaced"): the first attempt at every step is refused by
     ``toe_front`` alone (whole, only long), the toe box attempt by ``visible_poke`` (the heel through the counter).
     Auto reads both attempts' refusals: ``visible_poke`` is among them, so it tries every heel room step
     2, 4, 6, 8, 10, 12, 15, 20 (``tried_length`` [0, 2, ..., 20], 2 calls per step = 18). None is accepted -> the
     refusal kept is the first attempt of +0 (its reasons: the ``toe_front`` one alone), never the toe box attempt.
     When the toe box attempt at +8 is accepted -> that one, ``tried_length`` [0, 2, 4, 6, 8], 10 calls.
     When the first attempt is refused by ``toe_front`` AND ``visible_poke`` at every step -> no shoe is whole: the
     refusal of +0's toe box attempt stands (``visible_poke``).
[T8] toe_box_size on a straight insole (arc_at(x) = x, raw units = metres at k 1, x1 = 0.40) with a toe station that
     moves with the length it is read for: front_end(L, k) = 0.25 - (L - 0.24) (a longer read leaves more area in
     front, the station lies further back). Foot 0.24 m, ALLOW_M 0.005, ``_scale``'s answer (0.9, 0.2):
     - room 0: xw = 0.25 + 0.005 / k, k = 0.245 / xw -> k xw = 0.245 = 0.25 k + 0.005 -> k = 0.96,
       xw = 0.25 + 0.005 / 0.96 = 0.2552083; the toe tip (0.24 / k from the heel) at 0.25 = the station;
     - room 0.024 (+10 %): k xw = 0.269 = 0.25 k + 0.005 -> k = 1.056, xw = 0.2547348; the heel room moves the foot
       forward: its tip at (0.024 + 0.24) / 1.056 = 0.25 — the same station. Read for L + room (0.264) the station
       would be 0.226 and the tip 24 raw-mm further back;
     - a station behind ``_scale``'s end (front_end 0.15): (0.9, 0.2) kept.
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


def quads(rects, tile=0.01):
    """Axis-aligned rectangles -> (positions, faces): each (axis, value, (a0, a1), (b0, b1)) with the two other axes
    in order, cut into tiles of at most ``tile`` m (``garment_fit._raster`` samples a triangle at most 64 steps per
    edge: a 1-mm raster needs edges under 32 mm to leave no pixel without a sample)."""
    P, F = [], []
    for axis, value, (a0, a1), (b0, b1) in rects:
        others = [i for i in range(3) if i != axis]
        na, nb = max(1, int(np.ceil((a1 - a0) / tile - 1e-9))), max(1, int(np.ceil((b1 - b0) / tile - 1e-9)))
        for i in range(na):
            for j in range(nb):
                ta0, ta1 = a0 + (a1 - a0) * i / na, a0 + (a1 - a0) * (i + 1) / na
                tb0, tb1 = b0 + (b1 - b0) * j / nb, b0 + (b1 - b0) * (j + 1) / nb
                base = len(P)
                for a, b in ((ta0, tb0), (ta1, tb0), (ta1, tb1), (ta0, tb1)):
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
        rects += [(2, 0.0, (-X, X), (0.0, 0.0205)), (2, 0.0, (-X, X), (0.0305, H)),
                  (2, 0.0, (-X, -0.0055), (0.0205, 0.0305)), (2, 0.0, (0.0045, X), (0.0205, 0.0305))]
    else:
        rects += [(2, 0.0, (-X, X), (0.0, H))]
    return quads(rects)


def box_foot(x=0.025, z0=0.005, z1=0.095, y0=0.002, y1=0.08):
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
    check(ff.TOE_FRONT_MAX == 0.06 and 0.048 * 1.2 <= ff.TOE_FRONT_MAX < 0.118,
          "[T3] TOE_FRONT_MAX 0.06 between 0.0576 and 0.118")
    check(ff.TOE_FRONT_TARGET == 0.048 < ff.TOE_FRONT_MAX, "[T3] TOE_FRONT_TARGET 0.048")
    check(ff.CLOSED_GATES == {"toe_front": ("max", 0.06)}, "[T3] the closed shoe's gate")

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

    # [T7]
    def run_auto(first_reasons, second_ok_at=None):
        calls = []

        def fake_fit_pair(*a, fit_height=False, allowance=None, **k):
            calls.append((fit_height, allowance["length"]))
            gates = {} if fit_height else {"toe_front": {"value": 0.15, "ok": False}}
            return Result(gates, False)

        def fake_attempt(result, prims, joints, insole=None):
            fit_height, step = calls[-1]
            if fit_height:
                ok_ = step == second_ok_at
                reasons = [] if ok_ else ["visible_poke 0.04 > 0.005 (...)"]
            else:
                ok_, reasons = False, list(first_reasons)
            out = {"ok": ok_, "result": result, "replaced": {}, "cut_stats": {}, "step": step,
                   "second": fit_height, "gates": {"ok": ok_, "reasons": reasons}}
            if not ok_:
                out["reasons"] = reasons
            return out

        kept = {}

        def fake_out(att, *a, **k):
            kept.update(step=att["step"], second=att["second"], reasons=att.get("reasons"))
            return {"record": att["result"].record}

        with patch.object(glb_mesh, "static_arrays", lambda b: (np.zeros((3, 3)), np.zeros((1, 3), int), None, None,
                                                                 None, None)), \
                patch.object(glb_mesh, "body_arrays", lambda b: None), \
                patch.object(glb_mesh, "joint_bind_matrices", lambda b: {}), \
                patch.object(glb_mesh, "body_primitive_arrays", lambda b: []), \
                patch.object(ff, "fit_pair", fake_fit_pair), \
                patch.object(ff, "too_flat_reason", lambda r: None), \
                patch.object(garment_footwear, "_fit_attempt", fake_attempt), \
                patch.object(garment_footwear, "_attempt_out", fake_out):
            out = garment_footwear.fit_compute(b"", {}, b"", None, "footwear", "i", "f", "/nonexistent",
                                               allowance={"width": "auto", "length": "auto"})
        tried = ((out.get("record") or (out.get("attempt") or {}).get("record") or {}).get("scale") or {})
        return out, calls, kept, ((tried.get("allowance") or {}).get("auto") or {}).get("tried_length")

    toe = ["toe_front 0.15 > 0.06 (...)"]
    out, calls, kept, tried = run_auto(toe)
    check(not out["ok"] and len(calls) == 18 and tried == [0, 2, 4, 6, 8, 10, 12, 15, 20],
          f"[T7] no step accepted: 18 calls ({len(calls)}), tried {tried}")
    check(kept == {"step": 0, "second": False, "reasons": toe} and out["reasons"] == toe,
          f"[T7] the kept refusal is the whole first attempt of +0 ({kept})")
    out, calls, kept, tried = run_auto(toe, second_ok_at=8)
    check(out["ok"] and len(calls) == 10 and tried == [0, 2, 4, 6, 8] and kept["step"] == 8 and kept["second"],
          f"[T7] the toe box attempt at +8 accepted ({len(calls)} calls, tried {tried}, {kept})")
    both = toe + ["visible_poke 0.03 > 0.005 (...)"]
    out, calls, kept, tried = run_auto(both)
    check(not out["ok"] and kept == {"step": 0, "second": True, "reasons": ["visible_poke 0.04 > 0.005 (...)"]},
          f"[T7] no whole shoe: +0's toe box attempt stands ({kept})")

    # [T8]
    arc = lambda x: x  # noqa: E731
    station = lambda L, k: 0.25 - (L - 0.24)  # noqa: E731
    k, xw = ff.toe_box_size(arc, station, 0.40, 0.24, 0.0, 0.9, 0.2)
    check(abs(k - 0.96) < 1e-9 and abs(xw - (0.25 + 0.005 / 0.96)) < 1e-9 and abs(0.24 / k - 0.25) < 1e-9,
          f"[T8] room 0: k {k:.6f}, x_end {xw:.7f}, tip {0.24 / k:.6f}")
    k, xw = ff.toe_box_size(arc, station, 0.40, 0.24, 0.024, 0.9, 0.2)
    check(abs(k - 1.056) < 1e-9 and abs(xw - (0.25 + 0.005 / 1.056)) < 1e-9 and abs(0.264 / k - 0.25) < 1e-9,
          f"[T8] room 0.024: k {k:.6f}, x_end {xw:.7f}, tip {0.264 / k:.6f} on the same station")
    check(ff.toe_box_size(arc, lambda L, k: 0.15, 0.40, 0.24, 0.0, 0.9, 0.2) == (0.9, 0.2),
          "[T8] a station behind _scale's end keeps (0.9, 0.2)")

    # [T5]
    Pf, Ff = box_foot()
    body = glb_mesh.Prim(positions=Pf, faces=Ff)
    for hole, want in ((False, 0.0), (True, 81.0)):
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

    # [T5b]
    import subprocess
    import types
    Pf, Ff = box_foot(x=0.0255, z0=-0.002, z1=0.088, y0=0.0025)
    body = glb_mesh.Prim(positions=Pf, faces=Ff)
    X, Z, H = 0.03, 0.10, 0.0505
    Ps, Fs = quads([(1, 0.0, (-X, X), (0.0, Z)), (0, -X, (0.0, H), (0.0, Z)), (0, X, (0.0, H), (0.0, Z)),
                    (2, Z, (-X, X), (0.0, H)), (2, 0.0, (-X, X), (0.0, H))])
    shoe = glb_mesh.GarmentMesh(positions=Ps, normals=None, uvs=np.zeros((len(Ps), 2)), indices=Fs.reshape(-1),
                                joints=np.zeros((len(Ps), 4), np.int64), weights=np.zeros((len(Ps), 4)),
                                joint_names=[], image=None, mime=None, material=None)
    seen = footwear_cut.skin_seen(body, {"left": {"foot": shoe}})
    views = seen["mm2"]["left"]
    others = {v: a for v, a in views.items() if v != "back"}
    check(abs(views["back"] - 2548.0) < 1e-6 and all(a == 0.0 for a in others.values()),
          f"[T5b] heel 2 mm through the back wall up to the rim: back {views['back']} mm2 (want 2548), others {others}")
    src = subprocess.run(["git", "-C", str(ROOT), "show", "0c27b0b70:app/core/footwear_cut.py"],
                         capture_output=True, text=True)
    if src.returncode == 0:
        old_cut = types.ModuleType("footwear_cut_0c27b0b70")
        exec(compile(src.stdout, "footwear_cut@0c27b0b70", "exec"), old_cut.__dict__)
        was = old_cut.skin_seen(body, {"left": {"foot": shoe}})["mm2"]["left"]["back"]
        check(was == 0.0, f"[T5b] on 0c27b0b70 (enclosed spots only) the same heel read {was} mm2 (want 0)")
    else:
        print("skip [T5b] old-code proof: commit 0c27b0b70 not in this repository")
    check((footwear_cut.SKIN_POKE_M, footwear_cut.SKIN_POKE_OPEN_PX) == (0.003, 4) and 2548.0 > 8.0,
          "[T5b] through the wall: 3 mm, 4-px opening; the [T5b] heel is far above the limit 8 mm2")

    # [T6]
    check((footwear_cut.SKIN_SEEN_PX_M, footwear_cut.SKIN_SEEN_EPS_M, footwear_cut.SKIN_SEEN_OPEN_PX,
           footwear_cut.SKIN_SEEN_MAX_MM2) == (0.001, 0.00025, 2, 8.0) and 8.0 < 81.0,
          "[T6] 1-mm raster, 0.25-mm tolerance, 2-px opening, limit 8 mm2 (below the [T5] hole)")
    check(garment_footwear.AUTO_LENGTH_GATES == ("visible_poke", "skin_seen_mm2"), "[T6] Auto answers skin_seen_mm2")

    print("\n" + ("ALL OK" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}"))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
