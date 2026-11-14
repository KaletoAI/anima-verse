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
[F0] constants: FOOTWEAR_FIT_VERSION 5 (the foot below the ankle, per-band contacts), BALL_SOLVE_STEPS 8, BALL_SOLVE_TOL_RAD 1e-7, ALLOW_M 0.005, BLEND_M 0.015, WIDTH_CAP 1.10, WIDTH_CAP_MIN 1.00,
     SHOE_WIDTH_CAP 1.65 (fit version 13), HEIGHT_CAP 1.5 (fit version 14), INSTEP_ROOF_SHARE 0.8 + INSTEP_FROM_SHARE 0.45 (fit version 15), SLIM_MAX_SHARE 0.18, FIT_GATES verbatim; every gate refuses (gating True), there is no ACTIVE_IN_P2 any more
     (fit version 3, Task 15).
[F9] joint_bind_matrices(glb) = inverse(inverseBindMatrix) per normalised joint name: the fixture's IBMs are
     the negated joint translations -> "leftfoot" = translation (0, 0.08, -0.10), "righttoebase" =
     (0.13, 0.01, 0.10), identity rotation. A GLB without a skin -> ValueError.
     measure_feet (fit version 5, the rule of spec 2026-11-11 § 13.1): the foot = the Foot + ToeBase-weighted
     vertices BELOW the Foot joint's height 0.08 (the leg column at y >= 0.10 is out whatever it weighs);
     down-facing = normal up < -0.4 = the sole grid (normal (0, -1, 0)). Foot axis = horizontal Foot ->
     ToeBase = +x; extent x in [-0.06, 0.19] -> length 0.25; heel contact = the down-facing vertices of the
     rear 0.045 (x < -0.06 + 0.045 = -0.015, i.e. x in {-0.06 .. -0.02}) within CONTACT_BAND_H_M 0.01 of
     their lowest (y = 0: all of them) -> mean -0.04 (height 0); d_heel = -0.04 - (-0.06) = 0.02; ball
     contact = the down-facing vertices with |x - 0.13| < 0.012 -> {0.12, 0.13, 0.14}, within 0.01 of their
     lowest -> 0.13 (height 0); heel_ball = 0.17; rest pitch 0; toe height = the y range at x = 0.19 = 0.02;
     ball width 0.085; plantar (the arch diagnostic) = the down-facing vertices within PLANTAR_BAND_M 0.03 of
     the lower contact (0) = the whole sole grid.
[F1] scale: the toes (0.02) fit under the roof (insole -> roof 0.03 raw x k ~ 0.0266) over [0.18, 0.26]; the
     unroofed stations in [0.156, 0.18] count as closed (front of 0.6 L) -> the cavity end is the last
     station, 0.26. Insole arc to it = 0.05 + sqrt(0.10^2 + 0.08^2) + 0.11 = 0.288062 ->
     k = (0.25 + 0.005) / 0.288062 = 0.88522. The arc is read on the 240-station polyline, which cuts the two
     kinks at 0.05 / 0.15 (arc 3.5e-5 short) -> k within 2e-4.
[F2] chord: heel contact on the insole at x_h = 0.02 / k = 0.022593 (flat part, height 0.09 k = 0.07967); the
     ball on the flat forepart (height 0.01 k = 0.00885): dy = 0.07082 whatever the chord length L, so the
     chord pitch is atan2(0.07082, sqrt(L^2 - 0.07082^2)). THE RIGID START: L = heel_ball 0.17 -> horizontal
     0.15455 -> 24.62 deg, rest pitch 0 -> theta_0 = 24.62. THE FIXED POINT on the SKINNED ball (fit version
     2): under a turn theta about the ankle (0, 0.08) (toes down, axis (0, 0, -1)) a Foot point (x, 0) lands
     at (x cos + 0.08 sin, 0.08 - x sin - 0.08 cos); the ToeBase column keeps its orientation and moves with
     the posed ball joint (0.13, 0.01): delta = (0.13 cos - 0.07 sin - 0.13, 0.07 - 0.13 sin - 0.07 cos). Heel
     contact H1 = (-0.04 cos - 0.08 sin, 0.08 + 0.04 sin - 0.08 cos); skinned ball B1s = (mean x of the posed
     columns 0.12, 0.13 (Foot) and 0.14 + delta_x (ToeBase), lowest y = the ToeBase column 0.07 - 0.13 sin
     - 0.07 cos); L = |B1s - H1|; posed pitch = atan2(H1_y - B1s_y, B1s_x - H1_x); theta += chord - pitch:
       theta 24.6200: H1 (-0.06969, 0.02394), B1s (0.08655, -0.04779), L 0.17192, chord 24.3263, pitch 24.6606
       theta 24.2857: H1 (-0.06936, 0.02353), B1s (0.08726, -0.04727), L 0.17188, chord 24.3314, pitch 24.3262
       theta 24.2910: chord 24.3314 = pitch 24.3314 -> converged: extension 24.29 deg both sides (+-0.05;
       the module reads k and the chord off the sampled insole, 0.003 deg from this closed form). Forepart
     flat -> slope 0 -> ToeBase turn -(24.29 + 0) = -24.29 deg. Axis = up x forward = y x x = (0, 0, -1).
[F3] the heel contact relative to the ankle (-0.04, -0.08) turned toe-down by 24.29 deg:
     x = -0.04 cos - 0.08 sin = -0.06937, y = 0.04 sin - 0.08 cos = -0.05646 -> it sits 0.05646 below the
     ankle; the shoe's heel point stands 0.07967 above the shoe ground -> lift = 0.07967 + 0.05646 - 0.08 (the
     rest ankle height over the floor y = 0) = 0.05613 m (+-0.5 mm), equal on both sides -> root lift
     0.05613, lift asymmetry 0.
[F4] ball placement: the shoe's chord ball point under the heel-anchored placement is L from the heel point
     in the vertical plane of d, at the chord pitch; the fixed point of [F2] made the posed heel -> skinned
     ball pitch equal to it -> the two coincide: error 0 (<= 0.01 mm; the z means agree). The shoe ground
     lands on the floor -> stand_floor 0 (+-0.01 mm); every active gate passes, ok True, no reasons.
     Re-posing the LEFT bind shoe with the stand pose built here by hand (Foot turned 24.29 deg about z = -1
     through the ankle): the wedge vertex (0, 0.09, 0.04) (heel end on the insole, the shoe's right edge,
     weight 100 % Foot) lands 0.02 behind the posed heel contact (x_h k = d_heel = 0.02) at its height, at
     the foot's centre + 0.04 k x 1.10 to the right: (-0.06937 - 0.02, 0.08 - 0.05646, -0.10 + 0.038950) =
     (-0.08937, 0.02354, -0.06105) (+-1e-4).
[F1]-[F8] run at the Wardrobe width cap 1.10 given EXPLICITLY (fit_pair(width_cap=1.10)): since fit version 13 the
     DEFAULT (None) widens a shoe without a shaft to the foot ([F13]) — the wedge to 1.2003 — and these numbers are
     the capped fit's.
[F5] width: foot 0.085 vs insole 0.08 k = 0.07082 at the ball -> needed 0.085 / 0.07082 = 1.2003 (+-0.002)
     both sides, applied min(1.10, 1.2003) = 1.10, slim_needed = 1 - 0.07082 x 1.10 / 0.085 = 1 - 0.07790 /
     0.085 = 0.0835 (+-0.001). A 0.10 m wide foot: needed 1.4120, slim_needed 1 - 0.07790 / 0.10 = 0.2210
     > 0.18 -> refused (at the cap 1.10). A width cap of 1.05 -> width_factor 1.05; a cap of 1.5 is clamped to
     1.10 (a Wardrobe cap never goes past WIDTH_CAP; only the default widens past it, [F13]).
[F6] mirror: the bodies are mirror images about z = 0 and the right shoe is the left's mirror, so in bind
     space right.positions = left.positions x (1, 1, -1) (1e-9) and right.indices = left.indices with
     the winding flipped -> the signed volume (sum det(a, b, c) / 6) is equal; every shoe's vertex normals
     agree with its winding's face normals (dot > 0). Joints: [LeftFoot, LeftToeBase] / [RightFoot,
     RightToeBase] only, weights in columns 0 and 1 summing to 1 — no Leg anywhere. The ToeBase weight is
     the smoothstep of (x - (x_ball - 0.015 / k)) / (0.03 / k), x_ball = 0.022593 + sqrt(0.17188^2 - 0.07082^2) / k
     = 0.022593 + 0.15663 / k = 0.19952 raw.
[F7] boot (fit version 6, boots plan Task 6 — the round-1 refusal is retired, the shaft is split at the
     ankle, scripts/smoke_footwear_split.py has the split's own numbers): walls over [0, 0.10] raised to 0.2098
     raw -> topline 0.2098 k = 0.18572; the shod ankle stands at y_split = 0.08 + 0.05613 = 0.13613 above the
     shoe's ground -> collar_above_ankle_mm = 0.18572 - 0.13613 = +49.6 mm (+-0.5; the old boot gate's +19.6
     plus its 30-mm margin) > SPLIT_MARGIN_M 10 mm -> split: ok True, no refusal, parts foot + shaft, no
     "boot" gate. The pump: 0.12 k - 0.13613 = -29.9 mm (+-0.5) -> not split, one part, no shaft gates.
[F8] foot_pose (spec § 6.1 without source): bones["LeftFoot"] = {axis (0, 0, -1), deg 24.29},
     bones["LeftToeBase"].deg = -24.29, root_lift_m 0.05613; contacts per side heel (on Foot), ball and toe
     (on ToeBase). The record's sides carry the same extension, the lift, toe room = the shoe's front 0.26 k
     = 0.23016 minus the posed toe tip: the toes keep their rest orientation (net ToeBase turn 0) and move
     with the ToeBase head (0.13, 0.01) turned about the ankle: x 0.13 cos + (-0.07) sin = 0.08902 ->
     toe tip x = 0.19 - 0.04098 = 0.14902, 0.21871 in front of the posed heel contact (-0.06969), which
     sits 0.02 behind the shoe's heel end -> toe room 0.23016 - 0.02 - 0.21871 = -8.55 mm (+-0.3; the box
     toes poke out: the rigid foot is straight where the insole arc is curved). placement_bind maps the
     source vertex (0, 0.09, 0.04) to its bind position in the Foot's bind frame (bind - the ankle).

The heel-up foot (boots plan docs/superpowers/plans/2026-11-11-footwear-boots-mens.md Task 1; spec
docs/superpowers/specs/2026-11-11-footwear-boots-mens-design.md § 5 F1-F3, § 13.1-13.2): ``foot_body_glb(heel_up=0.04,
shin_foot_weight=0.6)`` — the foot box's heel band x <= -0.02 stands 0.04 up, a ramp runs down to y = 0 at x = 0.03,
the forefoot is on the floor, and the leg column (x in [-0.03, 0.03], y in [0.10, 0.45]) carries Foot weight 0.6 >
FOOT_WEIGHT_MIN like the auto-weighted male shins.
[F10] On ad341e95 (the shipped rule) measure_feet raises "no plantar heel or ball vertices": the heel band's
     underside at 0.04 lies above PLANTAR_BAND_M 0.03 over the floor (F1), and the Foot-weighted leg column counts
     as foot (F2). The rule of fit version 5 measures it: the leg column (y >= 0.10 > the ankle 0.08) is excluded
     -> the foot is the box, length_m 0.25 (+-1e-6), no foot vertex at or above y = 0.08; heel band = the
     down-facing rows x in {-0.06 .. -0.02}, all at y = 0.04 = their lowest -> heel contact (-0.04, 0.04); ball
     band rows {0.12, 0.13, 0.14} at y = 0 -> ball contact (0.13, 0); d_heel 0.02; heel_ball = hypot(0.17, 0.04)
     = 0.174642; rest_pitch_deg = atan2(0.04, 0.17) = 13.24 (+-0.05); ball_width_m 0.085; toe height 0.02;
     plantar = the down-facing vertices within 0.03 of the lower contact (0): the ramp rows with
     0.04 (0.03 - x) / 0.05 < 0.03, i.e. x >= 0 (the row x = -0.01 sits at 0.032) -> x in {0.00 .. 0.19}.
[F11] That foot in the closed flat clog (``clog()``: insole flat at 0.01 raw over [0.01, 0.26], roof 0.04 over
     [0.1825, 0.26] -> cavity 0.03 k >= the toes 0.02 -> cavity end 0.26; the analysis' first profile station is
     0.0108787 on its 240-station grid (smoke_footwear_fit_step.py), so the arc is 0.26 - 0.0108787 = 0.2491213 ->
     k = (0.25 + 0.005) / 0.2491213 = 1.023599 (+-1e-5), insole height 0.01 k = 0.010236). The chord of a flat
     insole is 0 -> the rigid start theta = 0 - 13.24 = -13.24 deg; the fixed point then levels the posed heel
     with the LOWEST vertex of the skinned ball band (rows 0.12 / 0.13 on Foot, 0.14 on ToeBase; [F2]) — under a
     toes-UP turn that is the rear row x = 0.12 (the box tilts heel-down about the ankle; the ToeBase row keeps
     its orientation and rides on the posed ball joint, higher), so it converges on heel (-0.04, 0.04) level
     with (0.12, 0): theta = -atan2(0.04, 0.16) = -14.036 deg (+-0.05) both sides (0.8 deg beyond the chord
     minus rest pitch, the same 1-cm effect [F2] carries toe-down), toe turn +14.036 (the forepart is flat, slope
     0), the toes level again. Lift by hand: the heel contact relative to the ankle is (-0.04, -0.04); the toes
     turned UP by phi = 14.036 deg (sin 0.24254, cos 0.97014; a negative turn about the axis (0, 0, -1) = a
     positive one about +z) gives y' = -0.04 sin - 0.04 cos = -0.048507 -> the posed heel stands at 0.08 -
     0.048507 = 0.031493 (check: the row x = 0.12 at (0.12, -0.08) lands at 0.12 sin - 0.08 cos = -0.048507 too,
     level); the shoe ground is one insole height lower, 0.021257 above the body floor (y = 0, the forefoot) ->
     lift_m = 0 - 0.021257 = -0.02126 (+-0.3 mm) per side, root_lift_m -0.02126, lift_asymmetry_mm 0,
     stand_floor_mm 0 (by construction: the clog's floor plate is the shoe ground), width needed 0.085 /
     (0.08 x 1.023599 = 0.081888) = 1.0380 -> slim 0; the fit ok. foot_pose.root_lift_m carries the NEGATIVE
     number (spec § 13.2: the root descends because the bare body stands on its forefoot).
[F12] Regression: ``foot_body()`` (heel_up 0, the shins 100 % Leg) through [F1]-[F8] gives the SAME numbers as
     before this task — the constants in this docstring (k 0.88522, extension 24.29, lift 0.05613, ...) are
     unchanged, the version-5 rule changes nothing on a foot whose heel is on the floor; FOOTWEAR_FIT_VERSION 5,
     CONTACT_BAND_H_M 0.01, PLANTAR_BAND_M 0.03 (the arch diagnostic keeps it).
[F13] a shoe without a shaft is widened to the foot (fit version 13, boots plan Ruling 15g). The closed clog
     (scripts/_footwear_fixtures.clog, class none: insole shaft.has_shaft False) on foot_body_glb(ball_width=w):
     k 1.023599, the insole's ball width 0.08 k = 0.081888, so needed = w / 0.081888 (the foot box is w wide).
     applied_width_cap(clog insole) = 1.65 (default), (…, 1.05) = 1.05, (…, 1.5) = 1.10; the flat boot's
     (class ankle, has_shaft True) = 1.10; an insole dict without has_shaft = 1.10.
     (a) w 0.12: needed 0.12 / 0.081888 = 1.46542 (+-1e-4) -> width_factor = needed, slim 0, width_cap 1.10
         recorded (the fingerprint's default), width_cap_applied 1.65, the fit ok; the cut: every gate 0
         (deep_outside, visible_poke, throat_ledge_p95_mm, toe_conform_m), ok. The right shoe's widest bind
         x-section: the clog's walls z +-0.04 raw -> +-0.04 k 1.46542 = +-0.060000 about the foot's midline
         (z 0.10; +-1e-5) — exactly the foot box's +-0.06. (On 80cdcd96 — fit version 12 — the factor stays
         1.10 and the fit is refused: slim_needed 1 - 1.10 / 1.46542 = 0.2494 > 0.18.)
     (b) the same at the Wardrobe cap 1.05: width_factor 1.05, slim 1 - 1.05 / 1.46542 = 0.2835 -> refused
         (a set cap still keeps the item's look).
     (c) w 0.14: needed 1.70966 > 1.65 -> width_factor 1.65 (never past it), slim 1 - 1.65 / 1.70966 = 0.0349,
         the fit ok.
     (d) the flat boot (flat_boot(), a shaft) on the w 0.12 foot: width_factor 1.10 (the boot's cap),
         slim 0.2494 -> refused, as before.
     On these flat feet (FOOT_H 0.02 everywhere) the clog's toe box is tall enough: height_needed = (0.02 +
     0.002) / (0.03 x 1.023599) = 0.71643 per side -> height_factor 1, scale.height None (the fit unchanged).
[F14] the upper fitted to the foot's height (fit version 14, boots plan Ruling 15h), since fit version 15 (Ruling
     15i) only for a CLOSED toe box and only when the fit without it is refused. Measured on fit version 15's foot:
     ``FOOT_FLOOR_SHARES`` is patched to 1.0 (a floor as tall as the foot is long), which switches the vertical
     slimming of fit version 16 off in the fit and in the cut alike (scripts/smoke_footwear_sole_layers.py has it on). The feet: foot_body_glb() whose top
     (y = FOOT_H) is raised to Ht for x <= 0.15 (the instep and the toe joints; the last 0.04 to the tip keep 0.02,
     so toe_height_m stays 0.02 and the scale step's k = 1.023599 with it). The foot's sole stands on the insole
     (y 0.01 raw); per roofed station height_needed = (Ht + TOE_CLEARANCE_M 0.002) / (cavity x k), the worst one.
     The OPEN clog (fx.clog()): a roof only from the throat x 0.1825 on (insole share (0.1825 - 0.01) / 0.25 = 0.69),
     none over the instep stations 0.45 .. BALL_SHARE 0.62 -> instep_roof_share 0 -> height_ready False, never fitted
     in height (a pump or a heel exposes the instep by design).
     (a) the open clog, Ht 0.04: fit_pair(fit_height=True) measures height_needed 0.042 / (0.03 k = 0.030708) =
         1.36772 but keeps height_factor 1, scale.height None; garment_footwear.fit_compute accepts it with
         toe_conform 0.04 - (0.030708 - 0.002) = 0.011292 m — fit version 13's number (on 1401c3f0, fit version 14,
         the factor is 1.36772 and toe_conform 0: this check fails there).
     (b) the open clog, Ht 0.06: fit_compute refuses, toe_conform 0.06 - 0.028708 = 0.031292 > 0.025, and does not
         name the mesh (not a closed toe box).
     The CLOSED clog closed_clog(S): fx.clog() with every point above the insole (y > 0.01) stretched x S about
     it, plus an instep roof at the wall top 0.01 + 0.025 S over x 0.1 .. 0.1825 and a riser at 0.1825 up to the
     toe roof 0.01 + 0.03 S (closed everywhere). Instep cavity 0.025 S, toe cavity 0.03 S.
     (c) S 1.5, Ht 0.06: instep_roof_share 1 (cavity 0.0375 k = 38 mm >= CAVITY_MIN_M 15 mm), height_needed
         0.062 / (0.0375 k = 0.038385) = 1.61522 (ready); the first attempt is accepted: toe_conform 0.06 -
         (0.038385 - 0.002) = 0.023615 <= 0.025 -> fit_compute returns it, height_factor 1, scale.height None,
         and its GLB is byte-identical to fit_compute with HEIGHT_CAP 1.0 (the height fit switched off = fit
         version 13). fit_pair(fit_height=True) alone would have taken x1.5 (what fit version 14 delivered).
     (d) S 1.5, Ht 0.07: the first attempt is refused (toe_conform 0.07 - 0.036385 = 0.033615); the second fits the
         height: needed 0.072 / 0.038385 = 1.87574 -> HEIGHT_CAP 1.5, toe_conform 0.07 - (0.0375 x 1.5 x k - 0.002)
         = 0.07 - 0.055577 = 0.014423 -> accepted, height_factor 1.5.
     (e) S 1.0, Ht 0.065: needed at the instep roof 0.067 / (0.025 k = 0.025590) = 2.61822 > 1.5; the second
         attempt (x1.5) leaves toe_conform 0.065 - (0.025 x 1.5 x k - 0.002) = 0.065 - 0.036385 = 0.028615 > 0.025,
         refused, and the first reason is the toe box's (fit version 16: the insole has no image comparison, so the
         mesh reads as the shoe its image shows): "Foot too high for this shoe even after slimming (foot 65 mm, shoe
         26 mm at the instep)" (65 = Ht, the slimming off; 26 = 25.590 mm; the worst station is the first of the
         instep roof the height map reads, station 127 at x 0.138159 raw, the foot's toe tip at 0.261135 m in the
         shoe frame -> u = (0.261135 - 0.138159 k) / 0.25 = 0.479 >= 0.40: "the instep"). (At Ht 0.055 the x1.5 second attempt passes,
         0.018615: a needed factor past the cap is no refusal by itself — the gates decide.)
     (f) S 1.5, Ht 0.07 under the Wardrobe width cap 1.05: height_ready False (the item keeps its look) -> refused
         as in (d)'s first attempt, no mesh reason; the flat boot (a shaft) on the Ht 0.04 feet: height_ready False.
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
    check(ff.FOOTWEAR_FIT_VERSION == 18 and ff.HEIGHT_CAP == 1.5 and ff.BALL_SOLVE_STEPS == 8 and ff.BALL_SOLVE_TOL_RAD == 1e-7
          and ff.INSTEP_ROOF_SHARE == 0.8 and ff.INSTEP_FROM_SHARE == 0.45
          and ff.ALLOW_M == 0.005 and ff.BLEND_M == 0.015 and ff.WIDTH_CAP == 1.10 and ff.SHOE_WIDTH_CAP == 1.65
          and ff.WIDTH_CAP_MIN == 1.00 and ff.SLIM_MAX_SHARE == 0.18, "[F0] constants")
    check(ff.FIT_GATES == {"ball_placement_mm": ("max", 3.0), "lift_asymmetry_mm": ("max", 10.0),
                           "slim_needed": ("max", 0.18), "stand_floor_mm": ("range", (-3.0, 3.0))}
          and not hasattr(ff, "ACTIVE_IN_P2"), "[F0] FIT_GATES without boot (fit version 6), no ACTIVE_IN_P2")

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
    fit = ff.fit_pair(insole, shoe, body, joints, width_cap=1.10)   # [F1]-[F8]: the capped fit (docstring)
    rec = fit.record
    k = rec["scale"]["k_m_per_unit"]

    # [F1]
    check(near(k, 0.88522, 2e-4), f"[F1] k {k:.6f} = 0.255 / 0.288062 = 0.88522")
    check(near(rec["insole"]["cavity_end_x_m"], 0.26 * k, 1e-6), "[F1] cavity end = the last station (0.26 raw)")

    # [F2]
    for side in ("left", "right"):
        sd = rec["sides"][side]
        check(near(sd["extension"]["deg"], 24.29, 0.05) and near(sd["toe_counter"]["deg"], -24.29, 0.05)
              and np.allclose(sd["extension"]["axis_local"], (0, 0, -1), atol=1e-6),
              f"[F2] {side} extension {sd['extension']['deg']:.4f} deg, toe turn {sd['toe_counter']['deg']:.4f}")

    # [F3]
    check(near(rec["root_lift_m"], 0.05613, 5e-4), f"[F3] root lift {rec['root_lift_m']:.6f} = 0.05613")
    check(near(rec["sides"]["left"]["lift_m"], rec["sides"]["right"]["lift_m"], 1e-9)
          and near(rec["gates"]["lift_asymmetry_mm"]["value"], 0.0, 1e-6), "[F3] equal sides, asymmetry 0")

    # [F4]
    g = rec["gates"]
    check(g["ball_placement_mm"]["value"] <= 0.01,
          f"[F4] ball placement {g['ball_placement_mm']['value']:.5f} mm <= 0.01 (the shoe's chord point on the skinned ball)")
    check(near(g["stand_floor_mm"]["value"], 0.0, 0.01), f"[F4] stand floor {g['stand_floor_mm']['value']} mm")
    check(fit.ok and fit.reasons == [], f"[F4] ok {fit.ok}, reasons {fit.reasons}")
    left, right = fit.parts["left"]["foot"], fit.parts["right"]["foot"]
    i = int(np.nonzero(np.all(np.abs(P - (0, 0.09, 0.04)) < 1e-9, axis=1))[0][0])
    theta = math.radians(rec["sides"]["left"]["extension"]["deg"])
    Bf = ff._about(np.array([0.0, 0.08, -0.10]), np.array([0.0, 0.0, -1.0]), theta)
    posed = ff._apply(Bf, left.positions[i])
    check(left.weights[i, 0] == 1.0 and np.allclose(posed, (-0.08937, 0.02354, -0.06105), atol=1e-4),
          f"[F4] re-posed heel-edge vertex {np.round(posed, 5)}")

    # [F5]
    sc = rec["scale"]
    check(near(sc["width_needed"]["left"], 1.2003, 2e-3) and near(sc["width_needed"]["right"], 1.2003, 2e-3)
          and sc["width_factor"] == 1.10 and near(sc["slim_needed"]["left"], 0.0835, 1e-3)
          and near(g["slim_needed"]["value"], 0.0835, 1e-3) and g["slim_needed"]["ok"],
          f"[F5] width needed {sc['width_needed']['left']}, applied {sc['width_factor']}, slim {sc['slim_needed']}")
    wide = fx.foot_body_glb(0.10)
    fw = ff.fit_pair(insole, shoe, glb_mesh.body_arrays(wide), glb_mesh.joint_bind_matrices(wide), width_cap=1.10)
    gw = fw.record["gates"]["slim_needed"]
    check(near(gw["value"], 0.2210, 1e-3) and not gw["ok"] and gw["gating"] and not fw.ok
          and fw.reasons[:1] == ["slim_needed 0.2209 > 0.18 (share of the ball width the forefoot slimming must take off, "
                                 "worse side)"] and "cut" not in fw.record,
          f"[F5] 0.10 m foot: slim {gw['value']} > 0.18 refuses (ok {fw.ok}, {fw.reasons[:1]}); a refused fit carries no cut")
    check(all(v["gating"] is True for v in g.values()) and set(fit.record["cut"]["sides"]) == {"left", "right"}
          and fit.record["cut"]["version"] == 7,
          "[F5] every gate gating; the accepted fit carries the cut description (both sides, cut version 7)")
    f105 = ff.fit_pair(insole, shoe, body, joints, width_cap=1.05)
    f150 = ff.fit_pair(insole, shoe, body, joints, width_cap=1.5)
    check(f105.record["scale"]["width_factor"] == 1.05 and f150.record["scale"]["width_factor"] == 1.10,
          "[F5] width cap 1.05 applied, 1.5 clamped to 1.10")

    # [F6]
    check(np.allclose(right.positions, left.positions * (1, 1, -1), atol=1e-9)
          and np.array_equal(right.indices, left.indices[:, [0, 2, 1]]), "[F6] right = mirror of left, winding flipped")
    vl, vr = signed_volume(left.positions, left.indices), signed_volume(right.positions, right.indices)
    check(abs(vl - vr) <= 1e-12 and abs(vl) > 0, f"[F6] signed volume left {vl:.3e} = right {vr:.3e}")
    for side, gm in ((s_, fit.parts[s_]["foot"]) for s_ in ("left", "right")):
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
    check(np.allclose(left.weights[:, 1], u * u * (3 - 2 * u), atol=1e-9) and near(xb, 0.19952, 1e-4),
          f"[F6] ToeBase weight = smoothstep over +-0.015 m around the ball (x {xb:.5f} raw)")

    # [F7] (fit version 6: the shaft wedge is SPLIT, not refused)
    Pb, Fb = fx.wedge(shaft=0.2098)
    boot = ff.fit_pair(footwear_insole.analyse_arrays(Pb, Fb), fx.shoe_garment(Pb, Fb), body, joints)
    bl = boot.record["sides"]["left"]
    check(boot.ok and boot.reasons == [] and "refusal" not in boot.record and "boot" not in boot.record["gates"]
          and bl["split"]["is_boot"] is True and near(bl["split"]["collar_above_ankle_mm"], 49.6, 0.5)
          and near(boot.record["diagnostics"]["left"]["collar_above_ankle_mm"], 49.6, 0.5)
          and sorted(boot.parts["left"]) == ["foot", "shaft"] and boot.record["split"]["is_boot"] is True,
          f"[F7] boot: split (collar {bl['split']['collar_above_ankle_mm']} mm above the ankle), ok {boot.ok}, "
          f"parts {sorted(boot.parts['left'])}")
    pl = rec["sides"]["left"]
    check(pl["split"]["is_boot"] is False and near(pl["split"]["collar_above_ankle_mm"], -29.9, 0.5)
          and sorted(fit.parts["left"]) == ["foot"] and near(pl["split"]["y_m"], 0.13613, 5e-4)
          and "shaft_push_p95_m" not in rec["gates"],
          f"[F7] the pump: collar {pl['split']['collar_above_ankle_mm']} mm, y_split {pl['split']['y_m']}, no split")

    # [F8]
    fp = fit.foot_pose
    check(fp["version"] == 1 and "source" not in fp and near(fp["bones"]["LeftFoot"]["deg"], 24.29, 0.05)
          and np.allclose(fp["bones"]["LeftFoot"]["axis"], (0, 0, -1), atol=1e-6)
          and near(fp["bones"]["LeftToeBase"]["deg"], -24.29, 0.05) and near(fp["root_lift_m"], 0.05613, 5e-4)
          and set(fp["bones"]) == {"LeftFoot", "LeftToeBase", "RightFoot", "RightToeBase"},
          f"[F8] foot_pose LeftFoot {fp['bones']['LeftFoot']}, lift {fp['root_lift_m']}")
    roles = {s: [(c["role"], c["bone"]) for c in fp["contacts"][s]] for s in ("left", "right")}
    check(roles["left"] == [("heel", "LeftFoot"), ("ball", "LeftToeBase"), ("toe", "LeftToeBase")]
          and roles["right"] == [("heel", "RightFoot"), ("ball", "RightToeBase"), ("toe", "RightToeBase")],
          f"[F8] contacts {roles['left']}")
    check(near(rec["sides"]["left"]["toe_room_mm"], -8.90, 0.3), f"[F8] toe room {rec['sides']['left']['toe_room_mm']} mm")
    pb = np.asarray(rec["sides"]["left"]["placement_bind"], np.float64)
    local = ff._apply(pb, P[i])
    check(np.allclose(local, left.positions[i] - (0, 0.08, -0.10), atol=1e-6), "[F8] placement_bind -> Foot bind frame")

    # [F10] the heel-up foot with Foot-weighted shins
    hu = fx.foot_body_glb(heel_up=0.04, shin_foot_weight=0.6)
    hb, hj = glb_mesh.body_arrays(hu), glb_mesh.joint_bind_matrices(hu)
    Ph = np.asarray(hb.positions, np.float64)
    try:
        feet_hu = ff.measure_feet(hb, hj)
    except ValueError as exc:
        feet_hu = None
        check(False, f"[F10] measure_feet on the heel-up foot raises: {exc}")
    for side in ("left", "right") if feet_hu else ():
        f = feet_hu[side]
        zc = -0.10 if side == "left" else 0.10
        check(near(f.length_m, 0.25, 1e-6) and float(Ph[f.vertex_ids, 1].max()) < 0.08
              and np.allclose(f.heel_contact, (-0.04, 0.04, zc), atol=1e-6)
              and np.allclose(f.ball_contact, (0.13, 0.0, zc), atol=1e-6) and near(f.d_heel_m, 0.02, 1e-6)
              and near(f.heel_ball_m, 0.174642, 1e-6) and near(f.rest_pitch_deg, 13.24, 0.05)
              and near(f.ball_width_m, 0.085, 1e-6) and near(f.toe_height_m, 0.02, 1e-6),
              f"[F10] {side}: length {f.length_m:.5f}, heel {np.round(f.heel_contact, 4)}, ball {np.round(f.ball_contact, 4)}, "
              f"d_heel {f.d_heel_m:.4f}, heel_ball {f.heel_ball_m:.6f}, rest {f.rest_pitch_deg:.3f}, width {f.ball_width_m:.4f}")
        px = np.round((Ph[f.plantar] - f.ankle) @ f.forward, 6)
        check(near(px.min(), 0.0, 1e-6) and near(px.max(), 0.19, 1e-6) and len(f.plantar) == 20 * 5,
              f"[F10] {side}: plantar = the down-facing rows x in [{px.min():.2f}, {px.max():.2f}] ({len(f.plantar)} vertices)")

    # [F11] the heel-up foot in the flat clog
    if feet_hu:
        Pc, Fc = fx.clog()
        fit_hu = ff.fit_pair(footwear_insole.analyse_arrays(Pc, Fc), fx.shoe_garment(Pc, Fc), hb, hj)
        rh = fit_hu.record
        check(near(rh["scale"]["k_m_per_unit"], 1.023599, 1e-5), f"[F11] k {rh['scale']['k_m_per_unit']:.6f} = 0.255 / 0.2491213")
        for side in ("left", "right"):
            sd = rh["sides"][side]
            check(near(sd["extension"]["deg"], -14.036, 0.05) and near(sd["toe_counter"]["deg"], 14.036, 0.05)
                  and near(sd["lift_m"], -0.021257, 3e-4),
                  f"[F11] {side}: extension {sd['extension']['deg']:.3f}, toe turn {sd['toe_counter']['deg']:.3f}, lift {sd['lift_m']:.6f}")
        gh = rh["gates"]
        check(near(rh["root_lift_m"], -0.021257, 3e-4) and near(gh["lift_asymmetry_mm"]["value"], 0.0, 1e-6)
              and near(gh["stand_floor_mm"]["value"], 0.0, 0.01) and near(gh["slim_needed"]["value"], 0.0, 1e-9)
              and near(rh["scale"]["width_needed"]["left"], 1.0380, 1e-3),
              f"[F11] root lift {rh['root_lift_m']:.6f}, asymmetry {gh['lift_asymmetry_mm']['value']:.3f}, "
              f"stand floor {gh['stand_floor_mm']['value']:.3f}, width needed {rh['scale']['width_needed']['left']:.4f}")
        check(fit_hu.ok and fit_hu.reasons == [] and near(fit_hu.foot_pose["root_lift_m"], -0.021257, 3e-4),
              f"[F11] ok {fit_hu.ok}, reasons {fit_hu.reasons}, foot_pose root lift {fit_hu.foot_pose.get('root_lift_m')}")

    # [F12] the version and the two band constants ([F1]-[F8] above are the unchanged regression)
    check(ff.FOOTWEAR_FIT_VERSION == 18 and ff.CONTACT_BAND_H_M == 0.01 and ff.PLANTAR_BAND_M == 0.03,
          "[F12] FOOTWEAR_FIT_VERSION 18, CONTACT_BAND_H_M 0.01, PLANTAR_BAND_M 0.03")

    # [F13] a shoe without a shaft is widened to the foot
    from app.core import footwear_cut
    Pc, Fc = fx.clog()
    ins_c = footwear_insole.analyse_arrays(Pc, Fc)
    Pb2, Fb2 = fx.flat_boot()
    ins_b = footwear_insole.analyse_arrays(Pb2, Fb2)
    check((ins_c["shaft"].get("has_shaft"), ins_b["shaft"].get("has_shaft"), ff.applied_width_cap(ins_c),
           ff.applied_width_cap(ins_c, 1.05), ff.applied_width_cap(ins_c, 1.5), ff.applied_width_cap(ins_b),
           ff.applied_width_cap({"shaft": {"class": "none"}}))
          == (False, True, 1.65, 1.05, 1.10, 1.10, 1.10),
          "[F13] applied_width_cap: clog 1.65 / 1.05 / 1.5 -> 1.10, boot 1.10, no has_shaft 1.10")

    def wide_fit(w, Pw_, Fw_, ins_, cap=None):
        g_ = fx.foot_body_glb(w)
        j_ = glb_mesh.joint_bind_matrices(g_)
        return ff.fit_pair(ins_, fx.shoe_garment(Pw_, Fw_), glb_mesh.body_arrays(g_), j_, width_cap=cap), g_, j_
    fa, ga, ja = wide_fit(0.12, Pc, Fc, ins_c)
    sa = fa.record["scale"]
    check(fa.ok and near(sa["k_m_per_unit"], 1.023599, 2e-6) and near(sa["width_needed"]["left"], 0.12 / 0.081888, 1e-4)
          and near(sa["width_factor"], 1.46542, 1e-4) and sa["slim_needed"] == {"left": 0.0, "right": 0.0}
          and sa["width_cap"] == 1.10 and sa["width_cap_applied"] == 1.65,
          f"[F13] (a) w 0.12: widened x{sa['width_factor']:.5f} = needed, slim 0, cap 1.10 recorded, 1.65 applied "
          f"(80cdcd96: x1.10, slim 0.2494 refused) — ok {fa.ok} {fa.reasons}")
    pr_a = glb_mesh.body_primitive_arrays(ga)[0]
    cut_a = footwear_cut.cut_description(fa, ins_c)
    after_a, _st = footwear_cut.apply_cut(pr_a, cut_a, ja)
    ga_ = footwear_cut.cut_gates(after_a, fa.parts, cut_a, joints=ja, body_before=pr_a)
    check(ga_["ok"] and all(v["value"] == 0.0 for v in ga_["gates"].values()),
          f"[F13] (a) the cut: every gate 0 — {({k: v['value'] for k, v in ga_['gates'].items()})}")
    zr = fa.parts["right"]["foot"].positions[:, 2]
    check(near(zr.min(), 0.10 - 0.06, 1e-5) and near(zr.max(), 0.10 + 0.06, 1e-5),
          f"[F13] (a) the right shoe z {zr.min():.6f}..{zr.max():.6f} = 0.10 +- 0.04 k x1.46542 = +-0.06 (the foot box)")
    fb_, _g, _j = wide_fit(0.12, Pc, Fc, ins_c, cap=1.05)
    check(not fb_.ok and fb_.record["scale"]["width_factor"] == 1.05
          and near(fb_.record["gates"]["slim_needed"]["value"], 1 - 1.05 / 1.46542, 1e-3),
          f"[F13] (b) Wardrobe cap 1.05: x1.05, slim {fb_.record['gates']['slim_needed']['value']:.4f} = 0.2835 refused")
    fc_, _g, _j = wide_fit(0.14, Pc, Fc, ins_c)
    check(fc_.ok and fc_.record["scale"]["width_factor"] == 1.65
          and near(fc_.record["gates"]["slim_needed"]["value"], 1 - 1.65 / (0.14 / 0.081888), 1e-3),
          f"[F13] (c) w 0.14: needed {fc_.record['scale']['width_needed']['left']:.5f} -> x1.65, slim "
          f"{fc_.record['gates']['slim_needed']['value']:.4f} = 0.0349, ok {fc_.ok}")
    fd_, _g, _j = wide_fit(0.12, Pb2, Fb2, ins_b)
    check(not fd_.ok and fd_.record["scale"]["width_factor"] == 1.10
          and near(fd_.record["gates"]["slim_needed"]["value"], 0.2494, 1e-3),
          f"[F13] (d) the flat boot on w 0.12: x{fd_.record['scale']['width_factor']} (boot cap), slim "
          f"{fd_.record['gates']['slim_needed']['value']:.4f} refused")

    # [F14] the upper fitted to the foot's height — on fit version 15's foot: the vertical slimming (fit version 16,
    # footwear_cut step 1b) is switched off by a floor as tall as the foot is long (smoke_footwear_sole_layers.py has it on)
    from app.core.footwear_cut import TOE_CLEARANCE_M
    real_floor = ff.FOOT_FLOOR_SHARES
    ff.FOOT_FLOOR_SHARES = ((0.0, 1.0), (1.0, 1.0))
    real_body = fx.foot_body

    def tall_glb(ht):
        def tall(*a, **kw):
            Pt, Ft, Jt, Wt, Nt = real_body(*a, **kw)
            Pt = np.array(Pt, np.float64)
            Pt[(np.abs(Pt[:, 1] - fx.FOOT_H) < 1e-9) & (Pt[:, 0] <= 0.15 + 1e-9), 1] = ht
            return Pt, Ft, Jt, Wt, Nt
        fx.foot_body = tall
        try:
            return fx.foot_body_glb()
        finally:
            fx.foot_body = real_body

    def tall_fit(ht, Pt_, Ft_, ins_, cap=None, fit_height=False):
        g_ = tall_glb(ht)
        j_ = glb_mesh.joint_bind_matrices(g_)
        return ff.fit_pair(ins_, fx.shoe_garment(Pt_, Ft_), glb_mesh.body_arrays(g_), j_, width_cap=cap,
                           fit_height=fit_height), g_, j_

    def cut_of(fit_, g_, j_, ins_):
        pr_ = glb_mesh.body_primitive_arrays(g_)[0]
        cd_ = footwear_cut.cut_description(fit_, ins_)
        after_, _st_ = footwear_cut.apply_cut(pr_, cd_, j_)
        return cd_, footwear_cut.cut_gates(after_, fit_.parts, cd_, joints=j_, body_before=pr_)

    check(fa.record["scale"]["height_factor"] == 1.0 and fa.record["scale"]["height"] is None
          and near(fa.record["scale"]["height_needed"]["left"], 0.022 / (0.03 * 1.023599), 1e-4),
          f"[F13] flat feet: height_needed {fa.record['scale']['height_needed']['left']:.5f} = 0.71643, factor 1")
    import tempfile
    from app.core import garment_footwear
    kh = 1.023599

    def closed_clog(S):
        Pq, Fq = fx.clog()
        Pq = np.array(Pq, np.float64)
        up = Pq[:, 1] > 0.01 + 1e-9
        Pq[up, 1] = 0.01 + (Pq[up, 1] - 0.01) * S
        Pl, Fl = [tuple(v) for v in Pq], [tuple(f) for f in Fq]
        lo, hi = 0.01 + 0.025 * S, 0.01 + 0.03 * S

        def quad(a, b, c, d):
            n = len(Pl)
            Pl.extend([a, b, c, d])
            Fl.extend([(n, n + 2, n + 1), (n, n + 3, n + 2)])
        xs = [round(0.1 + 0.0025 * i, 10) for i in range(34)]
        for x0, x1 in zip(xs[:-1], xs[1:]):
            quad((x0, lo, -0.04), (x1, lo, -0.04), (x1, lo, 0.04), (x0, lo, 0.04))
        quad((0.1825, lo, -0.04), (0.1825, hi, -0.04), (0.1825, hi, 0.04), (0.1825, lo, 0.04))
        return np.asarray(Pl, np.float64), np.asarray(Fl, np.int64)

    def compute(ht, Pt_, Ft_, ins_, cap=None):
        g_ = tall_glb(ht)
        prep = glb_mesh.static_glb(Pt_, Ft_, np.zeros((len(Pt_), 2)))
        with tempfile.TemporaryDirectory() as td:
            return garment_footwear.fit_compute(prep, ins_, g_, cap, "footwear", "item_f14", "f14", td + "/fit.glb")

    def first(ht, Pt_, Ft_, ins_, cap=None, fit_height=False):
        fit_, g_, j_ = tall_fit(ht, Pt_, Ft_, ins_, cap, fit_height)
        return fit_, (cut_of(fit_, g_, j_, ins_)[1] if fit_.ok else None)

    def conform(out_):
        return out_["record"]["gates"]["toe_conform_m"]["value"]

    # (a) / (b) the open clog
    fh, gth = first(0.04, Pc, Fc, ins_c, fit_height=True)
    sh = fh.record["scale"]
    check(fh.ok and near(sh["k_m_per_unit"], kh, 2e-6) and sh["instep_roof_share"] == 0.0 and not sh["height_ready"]
          and near(sh["height_needed"]["left"], 0.042 / (0.03 * kh), 2e-4) and sh["height_factor"] == 1.0
          and sh["height"] is None,
          f"[F14] (a) open clog Ht 0.04: instep roof {sh['instep_roof_share']}, ready {sh['height_ready']}, needed "
          f"{sh['height_needed']['left']:.5f} = 1.36772 measured, factor {sh['height_factor']}")
    oa = compute(0.04, Pc, Fc, ins_c)
    check(oa["ok"] and oa["record"]["scale"]["height_factor"] == 1.0
          and near(conform(oa), 0.04 - (0.03 * kh - TOE_CLEARANCE_M), 2e-5),
          f"[F14] (a) fit_compute accepted, toe_conform {conform(oa) if oa['ok'] else None} = 0.011292 (fit v13; "
          f"1401c3f0: 0)")
    ob = compute(0.06, Pc, Fc, ins_c)
    check(not ob["ok"] and ob["reasons"][0].startswith("toe_conform_m 0.03129")
          and not any("too flat" in r for r in ob["reasons"]),
          f"[F14] (b) open clog Ht 0.06 refused, no mesh reason: {ob['reasons']}")

    # (c) .. (f) the closed clog
    P15, F15 = closed_clog(1.5)
    ins15 = footwear_insole.analyse_arrays(P15, F15)
    f1, gt1 = first(0.06, P15, F15, ins15)
    s1 = f1.record["scale"]
    oc = compute(0.06, P15, F15, ins15)
    real_cap = ff.HEIGHT_CAP
    ff.HEIGHT_CAP = 1.0
    try:
        oc_off = compute(0.06, P15, F15, ins15)
    finally:
        ff.HEIGHT_CAP = real_cap
    fv14, _gt = first(0.06, P15, F15, ins15, fit_height=True)
    check(s1["instep_roof_share"] == 1.0 and s1["height_ready"] and near(s1["height_needed"]["left"], 0.062 / (0.0375 * kh), 2e-4)
          and gt1["ok"] and near(gt1["gates"]["toe_conform_m"]["value"], 0.06 - (0.0375 * kh - TOE_CLEARANCE_M), 2e-5),
          f"[F14] (c) closed S 1.5 Ht 0.06: instep roof {s1['instep_roof_share']}, needed "
          f"{s1['height_needed']['left']:.5f} = 1.61522, first attempt ok {gt1['ok']}, toe_conform "
          f"{gt1['gates']['toe_conform_m']['value']:.6f} = 0.023615")
    check(oc["ok"] and oc["record"]["scale"]["height_factor"] == 1.0 and oc["record"]["scale"]["height"] is None
          and oc_off["ok"] and oc["glb_sha256"] == oc_off["glb_sha256"]
          and fv14.record["scale"]["height_factor"] == 1.5,
          f"[F14] (c) fit_compute keeps the accepted look: factor {oc['record']['scale']['height_factor']}, GLB "
          f"{oc['glb_sha256'][:12]} == height fit off {oc_off['glb_sha256'][:12]} (fit_height=True alone: "
          f"x{fv14.record['scale']['height_factor']})")
    _f2, gt2 = first(0.07, P15, F15, ins15)
    od = compute(0.07, P15, F15, ins15)
    check(not gt2["ok"] and near(gt2["gates"]["toe_conform_m"]["value"], 0.07 - (0.0375 * kh - TOE_CLEARANCE_M), 2e-5)
          and od["ok"] and od["record"]["scale"]["height_factor"] == 1.5
          and near(od["record"]["scale"]["height_needed"]["left"], 0.072 / (0.0375 * kh), 2e-4)
          and near(conform(od), 0.07 - (0.0375 * 1.5 * kh - TOE_CLEARANCE_M), 2e-5),
          f"[F14] (d) closed S 1.5 Ht 0.07: first toe_conform {gt2['gates']['toe_conform_m']['value']:.6f} = 0.033615 "
          f"refused, second x{od['record']['scale']['height_factor'] if od['ok'] else None} toe_conform "
          f"{conform(od) if od['ok'] else od['reasons']} = 0.014423 accepted")
    P10, F10 = closed_clog(1.0)
    oe = compute(0.065, P10, F10, footwear_insole.analyse_arrays(P10, F10))
    check(not oe["ok"] and oe["reasons"][0] == ("Foot too high for this shoe even after slimming (foot 65 mm, shoe "
                                                "26 mm at the instep)")
          and oe["gates"]["reasons"][0] == oe["reasons"][0]
          and oe["reasons"][1].startswith("toe_conform_m 0.0286"),
          f"[F14] (e) closed S 1.0 Ht 0.065 refused: {oe.get('reasons', ['accepted'])[:2]}")
    ff_cap, _gt = first(0.07, P15, F15, ins15, cap=1.05)
    of_ = compute(0.07, P15, F15, ins15, cap=1.05)
    fbt, _gt = first(0.04, Pb2, Fb2, ins_b, fit_height=True)
    check(not ff_cap.record["scale"]["height_ready"] and not of_["ok"]
          and not any("too flat" in r for r in of_["reasons"])
          and not fbt.record["scale"]["height_ready"] and fbt.record["scale"]["height_factor"] == 1.0,
          f"[F14] (f) Wardrobe cap 1.05 and the boot: not ready, {of_['reasons'][:1]}")
    ff.FOOT_FLOOR_SHARES = real_floor

    print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL PASS")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
