#!/usr/bin/env python3
"""Smoke: the CPU fit of a rigid shoe onto both feet (app/core/footwear_fit.py; plan
docs/superpowers/plans/2026-11-10-footwear-rigid-shoes.md, Task 9; spec
docs/superpowers/specs/2026-11-10-footwear-rigid-shoes-design.md § 5.5 steps 1-7, § 5.7, § 6.1) and
glb_mesh.joint_bind_matrices.

Usage:  ./.venv/bin/python scripts/smoke_footwear_fit.py

No storage, no world DB, no hub, no server: numpy on the synthetic meshes of scripts/_footwear_fixtures.py.

The body (``foot_body_glb``): Y up, facing +x, right = forward x up = +z. Joints (identity rotation): Foot
(ankle) at (0, 0.08, zc), ToeBase at (0.13, 0.01, zc), zc = -0.10 left / +0.10 right. Each foot is a box
x in [-0.06, 0.19], y in [0, 0.02], width 0.085 (z), sole grid every 0.01 in x; x <= 0.13 on Foot, else
ToeBase; a leg column (y >= 0.10) on Leg. Left and right identical, mirrored about z = 0.
The shoe: the Task 5 wedge pump (length 0.26, width 0.08, insole h(x) = 0.09 on [0, 0.05], linear to 0.01 at
0.15, 0.01 to 0.26; side walls up to h + 0.03; vamp roof over [0.18, 0.26]), analysed by
footwear_insole.analyse_arrays (frame = the wedge's own coordinates).

Expected, by hand:
[F0] constants: FOOTWEAR_FIT_VERSION 1, ALLOW_M 0.005, BLEND_M 0.015, WIDTH_CAP 1.10, WIDTH_CAP_MIN 1.00,
     SLIM_MAX_SHARE 0.18, FIT_GATES / ACTIVE_IN_P2 verbatim.
[F9] joint_bind_matrices(glb) = inverse(inverseBindMatrix) per normalised joint name: the fixture's IBMs are
     the negated joint translations -> "leftfoot" = translation (0, 0.08, -0.10), "righttoebase" =
     (0.13, 0.01, 0.10), identity rotation. A GLB without a skin -> ValueError.
     measure_feet: plantar = the sole grid (normal (0, -1, 0), y = 0 < 0.03). Foot axis = horizontal Foot ->
     ToeBase = +x; extent x in [-0.06, 0.19] -> length 0.25; heel contact = the sole vertices with x <
     -0.06 + 0.045 = -0.015, i.e. x in {-0.06 .. -0.02} -> mean -0.04 (height 0); d_heel = -0.04 - (-0.06)
     = 0.02; ball contact = |x - 0.13| < 0.012 -> {0.12, 0.13, 0.14} -> 0.13; heel_ball = 0.17; rest pitch
     0; toe height = the y range at x = 0.19 = 0.02; ball width 0.085.
[F1] scale: the toes (0.02) fit under the roof (insole -> roof 0.03 raw x k ~ 0.0266) over [0.18, 0.26]; the
     unroofed stations in [0.156, 0.18] count as closed (front of 0.6 L) -> the cavity end is the last
     station, 0.26. Insole arc to it = 0.05 + sqrt(0.10^2 + 0.08^2) + 0.11 = 0.288062 ->
     k = (0.25 + 0.005) / 0.288062 = 0.88522. The arc is read on the 240-station polyline, which cuts the two
     kinks at 0.05 / 0.15 (arc 3.5e-5 short) -> k within 2e-4.
[F2] chord: heel contact on the insole at x_h = 0.02 / k = 0.022593 (flat part, height 0.09 k = 0.07967); the
     ball at the chord distance 0.17 on the forepart (height 0.01 k = 0.00885): dy = 0.07082, horizontal
     sqrt(0.17^2 - 0.07082^2) = 0.15455 -> chord pitch = atan2(0.07082, 0.15455) = 24.62 deg; rest pitch 0
     -> extension 24.62 deg both sides (+-0.05). Forepart flat -> slope 0 -> ToeBase turn -(24.62 + 0) =
     -24.62 deg. Axis = up x forward = y x x = (0, 0, -1) (a positive turn takes the toes down).
[F3] the heel contact relative to the ankle (-0.04, -0.08) turned toe-down by 24.62 deg:
     x = -0.04 cos - 0.08 sin = -0.06969, y = 0.04 sin - 0.08 cos = -0.05607 -> it sits 0.05607 below the
     ankle; the shoe's heel point stands 0.07967 above the shoe ground -> lift = 0.07967 + 0.05607 - 0.08 (the
     rest ankle height over the floor y = 0) = 0.05574 m (+-0.5 mm), equal on both sides -> root lift
     0.05574, lift asymmetry 0.
[F4] ball placement: the foot's heel -> ball line is the foot axis, so the turn about the lateral axis puts
     the ball exactly on the chord -> error <= 1e-4 m (0.1 mm). The shoe ground lands on the floor ->
     stand_floor 0 (+-0.01 mm); every active gate passes, ok True, no reasons.
     Re-posing the LEFT bind shoe with the stand pose built here by hand (Foot turned 24.62 deg about z = -1
     through the ankle): the wedge vertex (0, 0.09, 0.04) (heel end on the insole, the shoe's right edge,
     weight 100 % Foot) lands 0.02 behind the posed heel contact (x_h k = d_heel = 0.02) at its height, at
     the foot's centre + 0.04 k x 1.10 to the right: (-0.06969 - 0.02, 0.08 - 0.05607, -0.10 + 0.038950) =
     (-0.08969, 0.02393, -0.06105) (+-1e-4).
[F5] width: foot 0.085 vs insole 0.08 k = 0.07082 at the ball -> needed 0.085 / 0.07082 = 1.2003 (+-0.002)
     both sides, applied min(1.10, 1.2003) = 1.10, slim_needed = 1 - 0.07082 x 1.10 / 0.085 = 1 - 0.07790 /
     0.085 = 0.0835 (+-0.001). A 0.10 m wide foot: needed 1.4120, slim_needed 1 - 0.07790 / 0.10 = 0.2210
     > 0.18 -> the gate reads not ok but is not active in P2 -> the fit stays ok. A width cap of 1.05 ->
     width_factor 1.05; a cap of 1.5 is clamped to 1.10.
[F6] mirror: the bodies are mirror images about z = 0 and the right shoe is the left's mirror, so in bind
     space right.positions = left.positions x (1, 1, -1) (1e-9) and right.indices = left.indices with
     the winding flipped -> the signed volume (sum det(a, b, c) / 6) is equal; every shoe's vertex normals
     agree with its winding's face normals (dot > 0). Joints: [LeftFoot, LeftToeBase] / [RightFoot,
     RightToeBase] only, weights in columns 0 and 1 summing to 1 — no Leg anywhere. The ToeBase weight is
     the smoothstep of (x - (x_ball - 0.015 / k)) / (0.03 / k), x_ball = 0.022593 + 0.15455 / k = 0.19718 raw.
[F7] boot: walls over [0, 0.10] raised to 0.2098 raw -> topline 0.2098 k = 0.18572; the shod ankle stands
     at 0.08 + 0.05574 = 0.13574 -> 0.18572 - (0.13574 + 0.03) = +0.01998 m = +20.0 mm (+-0.5) > 0 ->
     ok False, reasons[0] = BOOT_REFUSED, record refusal BOOT_REFUSED. The pump: 0.12 k - 0.16574 =
     -59.5 mm (+-0.5) -> passes.
[F8] foot_pose (spec § 6.1 without source): bones["LeftFoot"] = {axis (0, 0, -1), deg 24.62},
     bones["LeftToeBase"].deg = -24.62, root_lift_m 0.05574; contacts per side heel (on Foot), ball and toe
     (on ToeBase). The record's sides carry the same extension, the lift, toe room = the shoe's front 0.26 k
     = 0.23016 minus the posed toe tip: the toes keep their rest orientation (net ToeBase turn 0) and move
     with the ToeBase head (0.13, 0.01) turned about the ankle: x 0.13 cos + (-0.07) sin = 0.08902 ->
     toe tip x = 0.19 - 0.04098 = 0.14902, 0.21871 in front of the posed heel contact (-0.06969), which
     sits 0.02 behind the shoe's heel end -> toe room 0.23016 - 0.02 - 0.21871 = -8.55 mm (+-0.3; the box
     toes poke out: the rigid foot is straight where the insole arc is curved). placement_bind maps the
     source vertex (0, 0.09, 0.04) to its bind position in the Foot's bind frame (bind - the ankle).
"""
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402

import _footwear_fixtures as fx  # noqa: E402

FAILS = []


def check(cond: bool, label: str) -> None:
    print(("ok   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


def near(a, b, tol) -> bool:
    return a is not None and abs(float(a) - float(b)) <= tol


def signed_volume(P, F) -> float:
    a, b, c = P[F[:, 0]], P[F[:, 1]], P[F[:, 2]]
    return float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)


def main() -> int:
    from app.core import footwear_fit as ff
    from app.core import footwear_insole, glb_mesh

    # [F0]
    check(ff.FOOTWEAR_FIT_VERSION == 1 and ff.ALLOW_M == 0.005 and ff.BLEND_M == 0.015 and ff.WIDTH_CAP == 1.10
          and ff.WIDTH_CAP_MIN == 1.00 and ff.SLIM_MAX_SHARE == 0.18, "[F0] constants")
    check(ff.FIT_GATES == {"ball_placement_mm": ("max", 3.0), "lift_asymmetry_mm": ("max", 10.0),
                           "slim_needed": ("max", 0.18), "stand_floor_mm": ("range", (-3.0, 3.0)),
                           "boot": ("max", 0.0)}
          and ff.ACTIVE_IN_P2 == {"ball_placement_mm", "lift_asymmetry_mm", "stand_floor_mm", "boot"},
          "[F0] FIT_GATES / ACTIVE_IN_P2")

    # [F9] bind matrices + feet
    glb = fx.foot_body_glb()
    body = glb_mesh.body_arrays(glb)
    joints = glb_mesh.joint_bind_matrices(glb)
    check(np.allclose(joints["leftfoot"][:3, 3], (0, 0.08, -0.10), atol=1e-7)
          and np.allclose(joints["righttoebase"][:3, 3], (0.13, 0.01, 0.10), atol=1e-7)
          and np.allclose(joints["leftfoot"][:3, :3], np.eye(3), atol=1e-7), "[F9] joint_bind_matrices")
    try:
        glb_mesh.joint_bind_matrices(glb_mesh.static_glb(*fx.wedge(), np.zeros((len(fx.wedge()[0]), 2))))
        check(False, "[F9] a GLB without a skin raises")
    except ValueError:
        check(True, "[F9] a GLB without a skin raises")
    feet = ff.measure_feet(body, joints)
    for side in ("left", "right"):
        f = feet[side]
        check(near(f.length_m, 0.25, 1e-6) and near(f.d_heel_m, 0.02, 1e-6) and near(f.heel_ball_m, 0.17, 1e-6)
              and near(f.rest_pitch_deg, 0.0, 1e-6) and near(f.toe_height_m, 0.02, 1e-6)
              and near(f.ball_width_m, 0.085, 1e-6) and np.allclose(f.heel_contact[:2], (-0.04, 0.0), atol=1e-6),
              f"[F9] {side} foot: length {f.length_m:.5f}, d_heel {f.d_heel_m:.5f}, heel_ball {f.heel_ball_m:.5f}, "
              f"rest {f.rest_pitch_deg:.3f}, toe_h {f.toe_height_m:.4f}, ball width {f.ball_width_m:.4f}")

    P, F = fx.wedge()
    insole = footwear_insole.analyse_arrays(P, F)
    shoe = fx.shoe_garment(P, F)
    fit = ff.fit_pair(insole, shoe, body, joints)
    rec = fit.record
    k = rec["scale"]["k_m_per_unit"]

    # [F1]
    check(near(k, 0.88522, 2e-4), f"[F1] k {k:.6f} = 0.255 / 0.288062 = 0.88522")
    check(near(rec["insole"]["cavity_end_x_m"], 0.26 * k, 1e-6), "[F1] cavity end = the last station (0.26 raw)")

    # [F2]
    for side in ("left", "right"):
        sd = rec["sides"][side]
        check(near(sd["extension"]["deg"], 24.62, 0.05) and near(sd["toe_counter"]["deg"], -24.62, 0.05)
              and np.allclose(sd["extension"]["axis_local"], (0, 0, -1), atol=1e-6),
              f"[F2] {side} extension {sd['extension']['deg']:.4f} deg, toe turn {sd['toe_counter']['deg']:.4f}")

    # [F3]
    check(near(rec["root_lift_m"], 0.05574, 5e-4), f"[F3] root lift {rec['root_lift_m']:.6f} = 0.05574")
    check(near(rec["sides"]["left"]["lift_m"], rec["sides"]["right"]["lift_m"], 1e-9)
          and near(rec["gates"]["lift_asymmetry_mm"]["value"], 0.0, 1e-6), "[F3] equal sides, asymmetry 0")

    # [F4]
    g = rec["gates"]
    check(g["ball_placement_mm"]["value"] <= 0.1, f"[F4] ball placement {g['ball_placement_mm']['value']} mm <= 0.1")
    check(near(g["stand_floor_mm"]["value"], 0.0, 0.01), f"[F4] stand floor {g['stand_floor_mm']['value']} mm")
    check(fit.ok and fit.reasons == [], f"[F4] ok {fit.ok}, reasons {fit.reasons}")
    left, right = fit.shoes["left"], fit.shoes["right"]
    i = int(np.nonzero(np.all(np.abs(P - (0, 0.09, 0.04)) < 1e-9, axis=1))[0][0])
    theta = math.radians(rec["sides"]["left"]["extension"]["deg"])
    Bf = ff._about(np.array([0.0, 0.08, -0.10]), np.array([0.0, 0.0, -1.0]), theta)
    posed = ff._apply(Bf, left.positions[i])
    check(left.weights[i, 0] == 1.0 and np.allclose(posed, (-0.08969, 0.02393, -0.06105), atol=1e-4),
          f"[F4] re-posed heel-edge vertex {np.round(posed, 5)}")

    # [F5]
    sc = rec["scale"]
    check(near(sc["width_needed"]["left"], 1.2003, 2e-3) and near(sc["width_needed"]["right"], 1.2003, 2e-3)
          and sc["width_factor"] == 1.10 and near(sc["slim_needed"]["left"], 0.0835, 1e-3)
          and near(g["slim_needed"]["value"], 0.0835, 1e-3) and g["slim_needed"]["ok"],
          f"[F5] width needed {sc['width_needed']['left']}, applied {sc['width_factor']}, slim {sc['slim_needed']}")
    wide = fx.foot_body_glb(0.10)
    fw = ff.fit_pair(insole, shoe, glb_mesh.body_arrays(wide), glb_mesh.joint_bind_matrices(wide))
    gw = fw.record["gates"]["slim_needed"]
    check(near(gw["value"], 0.2210, 1e-3) and not gw["ok"] and not gw["gating"] and fw.ok,
          f"[F5] 0.10 m foot: slim {gw['value']} > 0.18 reported, not gating (ok {fw.ok})")
    f105 = ff.fit_pair(insole, shoe, body, joints, width_cap=1.05)
    f150 = ff.fit_pair(insole, shoe, body, joints, width_cap=1.5)
    check(f105.record["scale"]["width_factor"] == 1.05 and f150.record["scale"]["width_factor"] == 1.10,
          "[F5] width cap 1.05 applied, 1.5 clamped to 1.10")

    # [F6]
    check(np.allclose(right.positions, left.positions * (1, 1, -1), atol=1e-9)
          and np.array_equal(right.indices, left.indices[:, [0, 2, 1]]), "[F6] right = mirror of left, winding flipped")
    vl, vr = signed_volume(left.positions, left.indices), signed_volume(right.positions, right.indices)
    check(abs(vl - vr) <= 1e-12 and abs(vl) > 0, f"[F6] signed volume left {vl:.3e} = right {vr:.3e}")
    for side, gm in fit.shoes.items():
        Pg, Fg = gm.positions, gm.indices
        fn = np.cross(Pg[Fg[:, 1]] - Pg[Fg[:, 0]], Pg[Fg[:, 2]] - Pg[Fg[:, 0]])
        vn = gm.normals[Fg].sum(axis=1)
        cap = side.capitalize()
        check(bool(np.all(np.einsum("ij,ij->i", fn, vn) > 0)), f"[F6] {side} normals agree with the winding")
        check(gm.joint_names == [f"{cap}Foot", f"{cap}ToeBase"] and set(np.unique(gm.joints[:, :2])) <= {0, 1}
              and np.all(gm.weights[:, 2:] == 0) and np.allclose(gm.weights.sum(1), 1.0),
              f"[F6] {side} weights on {gm.joint_names} only")
    xb = rec["diagnostics"]["left"]["ball_x_m"] / k
    u = np.clip((P[:, 0] - (xb - 0.015 / k)) / (0.03 / k), 0, 1)
    check(np.allclose(left.weights[:, 1], u * u * (3 - 2 * u), atol=1e-9) and near(xb, 0.19718, 1e-4),
          f"[F6] ToeBase weight = smoothstep over +-0.015 m around the ball (x {xb:.5f} raw)")

    # [F7]
    Pb, Fb = fx.wedge(shaft=0.2098)
    boot = ff.fit_pair(footwear_insole.analyse_arrays(Pb, Fb), fx.shoe_garment(Pb, Fb), body, joints)
    bv = boot.record["gates"]["boot"]["value"]
    check(not boot.ok and boot.reasons[:1] == [footwear_insole.BOOT_REFUSED]
          and boot.record.get("refusal") == footwear_insole.BOOT_REFUSED and near(bv, 20.0, 0.5),
          f"[F7] boot {bv} mm -> refused {boot.reasons[:1]}")
    check(near(g["boot"]["value"], -59.5, 0.5) and g["boot"]["ok"], f"[F7] the pump: boot {g['boot']['value']} mm")

    # [F8]
    fp = fit.foot_pose
    check(fp["version"] == 1 and "source" not in fp and near(fp["bones"]["LeftFoot"]["deg"], 24.62, 0.05)
          and np.allclose(fp["bones"]["LeftFoot"]["axis"], (0, 0, -1), atol=1e-6)
          and near(fp["bones"]["LeftToeBase"]["deg"], -24.62, 0.05) and near(fp["root_lift_m"], 0.05574, 5e-4)
          and set(fp["bones"]) == {"LeftFoot", "LeftToeBase", "RightFoot", "RightToeBase"},
          f"[F8] foot_pose LeftFoot {fp['bones']['LeftFoot']}, lift {fp['root_lift_m']}")
    roles = {s: [(c["role"], c["bone"]) for c in fp["contacts"][s]] for s in ("left", "right")}
    check(roles["left"] == [("heel", "LeftFoot"), ("ball", "LeftToeBase"), ("toe", "LeftToeBase")]
          and roles["right"] == [("heel", "RightFoot"), ("ball", "RightToeBase"), ("toe", "RightToeBase")],
          f"[F8] contacts {roles['left']}")
    check(near(rec["sides"]["left"]["toe_room_mm"], -8.55, 0.3), f"[F8] toe room {rec['sides']['left']['toe_room_mm']} mm")
    pb = np.asarray(rec["sides"]["left"]["placement_bind"], np.float64)
    local = ff._apply(pb, P[i])
    check(np.allclose(local, left.positions[i] - (0, 0.08, -0.10), atol=1e-6), "[F8] placement_bind -> Foot bind frame")

    print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL PASS")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
