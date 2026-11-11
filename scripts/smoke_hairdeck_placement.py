#!/usr/bin/env python3
"""HairDeck placement correction (``app/core/garment_hairdeck.py``; user test 2026-11-09, finding 5 "hair too far
back, long forehead"): forward shift, forward tilt, and the automatic "hairline to the brow line".

Usage: ./.venv/bin/python scripts/smoke_hairdeck_placement.py

No world, no server, no hub: a throwaway storage dir (``paths.init`` first); every mesh is built in this file or by
scripts/smoke_garment_hairdeck_fit.py (imported). Expectations derived by hand below, from the numbers the finding
measured on Kira's record (``hair_kira_3f3e184afa64.json``) and on her base ``base233fdd2a.glb``.

[1] Hairline target = brow + 0.25 * (crown - brow). The finding's profile: brow ridge 1.61, crown 1.70
    -> 1.61 + 0.25 * 0.09 = 1.6325 (the finding's "y ~ 1.632"). Today's hairline 1.645 sits at
    (1.645 - 1.61) / 0.09 = 0.3889 of that span (the finding's "today 0.39").
[2] Landmarks on a synthetic centre profile shaped like the finding's table (chin 1.46, crown 1.70, all points
    Head-weighted, x = 0 unless noted): (y, z) = (1.461, 0.120) chin, (1.531, 0.168) nose tip, (1.561, 0.154)
    nasion, (1.611, 0.162) brow ridge, (1.641, 0.156), (1.671, 0.133), (1.700, 0.060) crown; plus two side points
    (+-0.085, 1.60, 0.06) and a back point (0, 1.60, -0.033) that span the head box: cx 0, width 0.17,
    cz (-0.033 + 0.168) / 2 = 0.0675, depth 0.201. The back point lies in the centre strip (x 0) but behind cz,
    so the profile (front half only) leaves it out — with it, its bin 1.6025 (z -0.033) would be the "nasion".
    Bins of 5 mm from the chin: nose = bin of 1.531 -> (1.531 - 1.46) / 0.005 = 14.2 -> bin 14, centre
    1.46 + 14.5 * 0.005 = 1.5325 (only bins with a centre <= 1.46 + 0.5 * 0.24 = 1.58 count: 1.461, 1.531, 1.561;
    z 0.168 is the largest). Nasion band: centres in (1.5325, 1.5325 + 0.5 * (1.70 - 1.5325) = 1.61625]: the bins
    of 1.561 (bin 20, centre 1.5625, z 0.154) and 1.611 (bin 30, centre 1.6125, z 0.162) -> nasion 1.5625.
    Brow = the profile vertex of largest z at y >= 1.46 + 21 * 0.005 = 1.565: 1.611 (z 0.162).
    -> target 1.611 + 0.25 * (1.70 - 1.611) = 1.63325. A plain sphere head has no nose: None.
[3] adjust_placement: pivot p = (-0.00336, 1.6054, 0.06191) (Kira's placed proxy centre); the front point
    p + (0, 0, 0.095) at 6 deg, forward 0.006 -> p + (0, -0.095 sin 6 deg, 0.095 cos 6 deg + 0.006)
    = p + (0, -0.0099301, 0.1004796): the finding's "about 1 cm lower at radius 0.095"; the back point
    p + (0, 0, -0.095) goes UP by the same 0.0099301 (z p - 0.0944796 + 0.006).
[4] solve_tilt on an arc of hair points around p in the plane x = 0: radius 0.095, elevation phi = 20..90 deg
    in 1-deg steps (z = p_z + 0.095 cos phi, y = p_y + 0.095 sin phi). Head box of [2]: a point is in the front
    strip when z > 0.0675 + 0.25 * 0.201 = 0.11775, i.e. 0.06191 + 0.095 cos(phi - t) > 0.11775
    -> phi - t < 53.99 deg, so the phi = 20 point is always in it and is the lowest: hairline(t) =
    1.6054 + 0.095 sin(20 deg - t). t = 0: 1.6054 + 0.0324919 = 1.6378919 (Kira's pre-push 1.6385).
    - target 1.63503 (Kira's): sin(20 - t) = (1.63503 - 1.6054) / 0.095 = 0.311895 -> 20 - t = 18.1726
      -> t = 1.8274 deg +- 0.02, "solved".
    - target 1.64 (above 1.63789): t = 0, "at_or_below_target".
    - target 1.60: hairline(15) = 1.6054 + 0.095 sin 5 deg = 1.61368 > 1.60 -> t = 15, "clamped".
    - the arc mirrored to the back (z = p_z - 0.095 cos phi): no point in the strip -> 0, "no_hairline".
[5] The push-out lifts the front cards (Kira: 1.6385 placed -> 1.64785 pushed), so the auto tilt re-aims at the
    PUSHED hairline. With ``_push`` replaced by a stand-in that lifts every point by 0.006 m, the [2] profile
    (target 1.63325) and the [4] arc (forward 0.006 = the default, auto tilt):
    round 1 aims at 1.63325: sin(20 - t) = (1.63325 - 1.6054) / 0.095 = 0.293158 -> t = 20 - 17.0475
      = 2.9525 deg; pushed hairline 1.63325 + 0.006 = 1.63925, miss 0.006 > 0.001;
    round 2 aims at 1.62725: sin(20 - t) = 0.230000 -> t = 20 - 13.2971 = 6.7029 deg; pushed 1.63325 = target
      -> stop: rounds 2, tilt 6.703 +- 0.02, hairline_pushed_y 1.63325 +- 0.0002, hairline_aim_y 1.62725 +- 0.0002,
      forward 0.006 "default", tilt "auto"/"solved".
    Manual tilt 4 (forward 0.002): no aiming, one round, tilt 4 "manual", forward 0.002 "manual",
    hairline_aim_y None; pushed = 1.6054 + 0.095 sin 16 deg + 0.006 = 1.6054 + 0.0261854 + 0.006 = 1.6375854
    (the report rounds to 1e-5).
[7] Fix round (Kira's new base ``base20d5701a``, refused with max_push_m 0.1349): three rules.
    a) Landmarks of a head pitched back (chin up). Profile (chin 1.45, crown 1.70; the new base's own values):
       (1.461, 0.200), (1.501, 0.252) nose, (1.531, 0.243) nasion, (1.571, 0.265), (1.606, 0.270) forehead,
       (1.651, 0.249), (1.700, 0.156); box points (+-0.083, 1.60, 0.17) and (0, 1.60, 0.069) -> cz 0.1695, the
       profile (z > cz) keeps every face point. Bin centres: 1.4625, 1.5025, 1.5325, 1.5725, 1.6075, 1.6525,
       1.6975. The OLD rule (nose = largest z of the lower half, centres <= 1.575) takes 1.5725 (0.265): its
       nasion band (1.5725, 1.63625] holds only 1.6075 (0.270 > 0.265) -> no face (None) -> tilt 0.
       The deepest-dip rule: candidate 1.5025 (0.252): band (1.5025, 1.60125] = {1.5325: 0.243, 1.5725: 0.265}
       -> nasion 1.5325, dip 0.009 >= 0.003; brow = largest z at y >= 1.45 + 17 * 0.005 = 1.535: 1.606 (0.270),
       0.270 - 0.243 = 0.027 >= 0.003 -> valid. 1.4625 (dip 0.200 - 0.243 < 0), 1.5325 (band min 0.265 > 0.243),
       1.5725 (band min 0.270 > 0.265): no dip. -> nose 1.5025, nasion 1.5325, brow 1.606, target
       1.606 + 0.25 * 0.094 = 1.6295.
    b) Nasion floor: the [4] arc plus one strand vertex (p_x, 1.45, 0.20) in the front strip of the [2] box
       (0.20 > 0.11775): without a floor the hairline is that strand, 1.45 (HairDeck seed 43 on Kira: 1.445, and
       the scalp cap covered the face); with the floor 1.5625 (the [2] nasion) it is the arc's 1.6378919.
    c) The push gate first. ``_push`` stand-in returns no lift and, call by call, a largest push of 0.1349,
       0.147, 0.1198 (Kira's seed-43 numbers at tilt 0 / 1.5 / 3, forward 0.006). The arc lowered by 0.01
       (hairline 1.6278919 < the [2] target 1.63325) -> auto tilt 0 "at_or_below_target"; 0.1349 > 0.12 ->
       candidates nearest first: 1.5 (0.147, refused), 3.0 (0.1198 <= 0.12, passes) -> tilt 3.0,
       "at_or_below_target+push_gate", gate_search tried [[0, 0.1349], [1.5, 0.147], [3.0, 0.1198]], picked 3.0.
       Every push 0.2: all 11 tilts 0, 1.5 .. 15 tried, picked None, tilt stays 0 (the fit then refuses).
       Manual tilt 0 with push 0.2: no search (gate_search None).
[6] The whole fit on the sphere fixture of smoke_garment_hairdeck_fit (head sphere r 0.1 at (0, 1.6, 0), plain
    shell): auto finds no landmarks -> tilt 0 "no_landmarks", forward 0.006 "default", hairline_target_y None,
    metrics forward_m 0.006 / tilt_deg 0; the head match itself is unchanged (icp_scale 2.0 +- 0.01). The shell's
    lowest ring stays at y 0.8 + 2 * 0.41 = 1.62 (a shift along z moves no y): hairline_unadjusted_y ==
    hairline_placed_y == 1.62 +- 1e-4. A manual tilt 15.5 or forward 0.031 is a ValueError (bounds 15 / 0.03).
    landmark_source "none" (no face, nothing rejected).
[8] Landmark plausibility (Kai 2026-11-09, base634402e5 with the beard modelled: the auto tilt 13.3 deg pulled the
    hairline 2-3 cm below his brow). Eye line = chin + 0.5 * (crown - chin); brow 8-13 cm below the crown and above
    the eye line, nose tip below it.
    a) Kai's recorded reading: chin 1.58058, crown 1.86, nose 1.61308, brow 1.68363 -> eye 1.58058 + 0.13971 =
       1.72029; gap 1.86 - 1.68363 = 0.17637 -> "brow 17.6 cm below the crown (plausible 8-13 cm)" and
       "brow 1.684 not above the eye line 1.720"; the nose 1.613 is below it -> exactly these two doubts.
       Kira's reading (base20d5701a: chin 1.4504, crown 1.70, nose 1.5029, brow 1.60648): eye 1.5752, gap 0.09352,
       brow above, nose below -> no doubt. The [2] profile (chin 1.46, crown 1.70, nose 1.5325, brow 1.611: eye
       1.58, gap 0.089) and the [7a] one (chin 1.45: eye 1.575, nose 1.5025, brow 1.606, gap 0.094) -> no doubt,
       placement_landmarks source "profile" with the same landmarks.
    b) A bearded profile shaped like Kai's (chin 1.58, crown 1.86; x = 0): (1.581, 0.080) beard, (1.613, 0.137)
       lower lip, (1.633, 0.131) mouth, (1.683, 0.172) nose tip, (1.733, 0.151) nasion, (1.743, 0.155) brow
       ridge, (1.768, 0.148) forehead, (1.788, 0.147), (1.833, 0.115), (1.858, 0.067); box points
       (+-0.097, 1.75, 0.055), (0, 1.75, -0.06) -> cx 0, cz (0.172 - 0.06) / 2 = 0.056, depth 0.232; the profile
       keeps z > 0.056 (the box points drop out). Bins from 1.58: 1.613 -> 6 (centre 1.6125), 1.633 -> 10
       (1.6325), 1.683 -> 20 (1.6825), 1.733 -> 30 (1.7325), 1.743 -> 32 (1.7425), 1.768 -> 37 (1.7675).
       Nose candidates: centre <= 1.72 and z >= 0.056 + 0.3 * 0.232 = 0.1256: bins 6, 10, 20.
       bin 6: band (1.6125, 1.73625] = {10: 0.131, 20: 0.172, 30: 0.151} -> nasion 10, dip 0.006; brow = largest z
         at y >= 1.635 = 1.683 (0.172), 0.041 above the nasion -> valid, dip 0.006.
       bin 10: band min 0.151 > 0.131 -> no dip.
       bin 20: band (1.6825, 1.77125] = {30: 0.151, 32: 0.155, 37: 0.148} -> nasion 37, dip 0.024; brow = largest
         z at y >= 1.77 = 1.788 (0.147) < 0.148 + 0.003 -> invalid (the forehead slopes back below the nasion).
       -> the reading nose 1.6125, nasion 1.6325, brow 1.683 (Kai's misreading); gap 0.177 -> "17.7 cm", brow
       1.683 <= eye 1.72 -> two doubts. Source "proportions": brow 1.58 + 0.6 * 0.28 = 1.748, floor (nasion)
       1.58 + 0.4 * 0.28 = 1.692, crown 1.86; target 1.748 + 0.25 * 0.112 = 1.776 (the misreading's: 1.683 +
       0.25 * 0.177 = 1.72725).
    c) _place_and_push on b with an arc around Kai's pivot p = (0, 1.7555, 0.0448) (radius 0.095, phi 20..90
       deg, plane x = 0) and a push stand-in that moves nothing: front strip z > 0.056 + 0.25 * 0.232 = 0.114;
       the phi = 20 point (z 0.0448 + 0.0893 + 0.006 = 0.140) is the lowest -> hairline(t) = 1.7555 + 0.095
       sin(20 - t). t = 0: 1.787992 > 1.776 -> sin(20 - t) = (1.776 - 1.7555) / 0.095 = 0.215789 -> 20 - t =
       12.4615 -> t = 7.538 +- 0.02 "solved", one round (the pushed hairline is the placed one), landmark_source
       "proportions", hairline_floor_y 1.692, landmarks_rejected.landmarks.brow_y 1.683. The misreading's target
       1.72725 would have needed sin(20 - t) = -0.29737, t = 37.3 deg -> "clamped" at 15.
[9] moved_share per length class: gates_for(None / "medium" / "long") keep 0.90 (Kira medium: 0.65-0.69),
    "short" 0.97, "very short" 1.0, the other two gates unchanged. Kai's metrics {max_push_m 0.0162, moved_share
    0.93, icp_resid_p95_m 0.0074} (seed 43 of the bearded run): refused without a class ("moved_share 0.93 >
    0.9"), passed as "short". _push_passes on 100 displacements, 93 of 0.01 m (> MOVED_EPS_M) and 7 of 0: share
    0.93 -> False by default, True with gates_for("short"). The [6] fixture's inner layer passes as "short" since
    FIT_VERSION hair 4: only the inner layer moves (moved_share 481 / 1922 = 0.2503, see smoke_garment_hairdeck_fit
    [5]) <= 0.97.
[10] Colour (CIELAB D65, CIE76). White (1, 1, 1) -> (100, 0, 0) (the matrix rows sum to the white point).
    Kai's HairDeck median linear (0.0431, 0.0314, 0.0235): Y = 0.2126729 * 0.0431 + 0.7151522 * 0.0314 +
    0.072175 * 0.0235 = 0.033318 -> L = 116 cbrt(Y) - 16 = 21.33; X / 0.95047 = 0.034977, Z / 1.08883 = 0.024713
    -> a = 500 (0.32700 - 0.32178) = 2.61, b = 200 (0.32178 - 0.29130) = 6.10. "brunette" #5c3b26: linear
    (0.107032, 0.043734, 0.019384) (+- 1e-5) -> Y 0.055442, X/Xn 0.066581, Z/Zn 0.023607 -> (28.23, 12.00, 18.89).
    ΔE = sqrt(6.90^2 + 9.39^2 + 12.79^2) = 17.30 (+- 0.05).
    _transfer_colours on three vertices at Kai's median Lab with L -5 / 0 / +5: delta_e_before 17.30, applied,
    the new median = brunette (delta_e_after <= 0.05), the L offsets -5 / 0 / +5 kept (+- 0.05), alpha untouched.
    A target 3 L units from the median (ΔE 3 <= AUTO_RECOLOUR_MIN_DE 5): not applied, colours unchanged.
    The whole fit on the [6] fixture (COLOR_0 0.25 grey -> L 116 cbrt(0.25) - 16 = 57.08, a = b = 0) with
    colour_profile brunette: report colour method "lab_transfer", delta_e_before sqrt(28.85^2 + 12^2 + 18.89^2)
    = 36.51 (+- 0.05), every hair colour = brunette linear (+- 1e-3), metrics colour_delta_e <= 0.05; with a
    colour_target too, the target wins (method "gain").
"""
import math
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402

FAILS = []


def check(cond, label):
    print(("OK   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


def near(a, b, tol):
    return a is not None and b is not None and abs(a - b) <= tol


PIVOT = np.array([-0.00336, 1.6054, 0.06191])
PROFILE = [(1.461, 0.120), (1.531, 0.168), (1.561, 0.154), (1.611, 0.162), (1.641, 0.156), (1.671, 0.133),
           (1.700, 0.060)]
CHIN, CROWN = 1.46, 1.70


def profile_body():
    P = [(0.0, y, z) for y, z in PROFILE] + [(-0.085, 1.60, 0.06), (0.085, 1.60, 0.06), (0.0, 1.60, -0.033)]
    P = np.array(P, np.float64)
    return P, np.ones(len(P), bool)


def arc(back=False):
    phi = np.radians(np.arange(20, 91, 1.0))
    z = -0.095 * np.cos(phi) if back else 0.095 * np.cos(phi)
    return PIVOT + np.column_stack([np.zeros_like(phi), 0.095 * np.sin(phi), z])


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="hairdeck-placement-") as tmp:
        from app.core import paths
        paths.init(Path(tmp) / "world")
        from app.core import garment_hairdeck as gh

        # [1]
        print("[1] hairline target")
        check(near(gh.hairline_target(1.61, 1.70), 1.6325, 1e-9), f"brow 1.61, crown 1.70 -> 1.6325 "
              f"({gh.hairline_target(1.61, 1.70)})")
        check(near((1.645 - 1.61) / 0.09, 0.3889, 1e-4), "today's ratio 0.389")
        check(gh.HAIRLINE_BROW_RATIO == 0.25 and gh.DEFAULT_FORWARD_M == 0.006, "constants 0.25 / 0.006")

        # [2]
        print("[2] landmarks")
        P, head_v = profile_body()
        lm = gh.head_landmarks(P, head_v, CHIN, CROWN)
        print("   ", lm)
        check(lm is not None and near(lm["nose_tip_y"], 1.5325, 1e-6) and near(lm["nose_tip_z"], 0.168, 1e-6),
              "nose tip bin 1.5325, z 0.168")
        check(lm is not None and near(lm["nasion_y"], 1.5625, 1e-6) and near(lm["nasion_z"], 0.154, 1e-6),
              "nasion bin 1.5625, z 0.154")
        check(lm is not None and near(lm["brow_y"], 1.611, 1e-6) and near(lm["brow_z"], 0.162, 1e-6),
              "brow 1.611, z 0.162")
        check(lm is not None and near(gh.hairline_target(lm["brow_y"], lm["crown_y"]), 1.63325, 1e-6),
              "target 1.63325")
        box = gh._head_box(P, head_v)
        check(all(near(a, b, 1e-9) for a, b in zip(box, (0.0, 0.0675, 0.17, 0.201))),
              f"head box (0, 0.0675, 0.17, 0.201): {box}")
        th = np.radians(np.arange(0, 181, 3.0))[:, None]
        ph = np.radians(np.arange(0, 360, 6.0))[None, :]
        sphere = (np.stack([np.sin(th) * np.cos(ph), np.cos(th) + 0 * ph, np.sin(th) * np.sin(ph)], -1)
                  .reshape(-1, 3) * 0.1 + [0, 1.6, 0])
        check(gh.head_landmarks(sphere, np.ones(len(sphere), bool), 1.5, 1.7) is None, "a sphere has no face: None")

        # [3]
        print("[3] adjust_placement")
        Q = np.array([PIVOT + [0, 0, 0.095], PIVOT + [0, 0, -0.095]])
        A = gh.adjust_placement(Q, PIVOT, 0.006, 6.0)
        check(np.allclose(A[0] - PIVOT, [0, -0.0099301, 0.1004796], atol=2e-7), f"front point {A[0] - PIVOT}")
        check(np.allclose(A[1] - PIVOT, [0, 0.0099301, -0.0944796 + 0.006], atol=2e-7), f"back point {A[1] - PIVOT}")

        # [4]
        print("[4] solve_tilt")
        H = arc()
        check(near(gh.front_hairline(H, box), 1.6378919, 1e-6), f"t = 0 hairline {gh.front_hairline(H, box)}")
        t, how = gh.solve_tilt(H, PIVOT, 0.006, box, 1.63503)
        check(near(t, 1.8274, 0.02) and how == "solved", f"Kira's target -> 1.8274 deg solved ({t:.4f}, {how})")
        check(gh.solve_tilt(H, PIVOT, 0.006, box, 1.64) == (0.0, "at_or_below_target"), "1.64 -> 0 at_or_below")
        check(gh.solve_tilt(H, PIVOT, 0.006, box, 1.60) == (15.0, "clamped"), "1.60 -> 15 clamped")
        check(gh.solve_tilt(arc(back=True), PIVOT, 0.0, box, 1.63) == (0.0, "no_hairline"), "back arc -> no_hairline")

        # [5]
        print("[5] the auto tilt aims at the pushed hairline")
        real_push = gh._push
        gh._push = lambda Q, F, U, body: {"Qp": np.asarray(Q) + [0, 0.006, 0], "disp": np.zeros((len(Q), 3))}
        try:
            body = SimpleNamespace(positions=P)
            F = np.zeros((0, 3), np.int64)
            _, pl = gh._place_and_push(H, PIVOT, F, None, body, head_v, CHIN, CROWN, None, None)
            print("   ", {k: v for k, v in pl.items() if k != "landmarks"})
            check(pl["rounds"] == 2 and near(pl["tilt_deg"], 6.7029, 0.02) and pl["tilt_solve"] == "solved"
                  and pl["tilt_source"] == "auto", "two rounds, tilt 6.703 auto/solved")
            check(near(pl["hairline_pushed_y"], 1.63325, 2e-4) and near(pl["hairline_aim_y"], 1.62725, 2e-4)
                  and near(pl["hairline_target_y"], 1.63325, 1e-5), "pushed 1.63325 = target, aim 1.62725")
            check(pl["forward_m"] == 0.006 and pl["forward_source"] == "default", "forward 0.006 default")
            _, pl = gh._place_and_push(H, PIVOT, F, None, body, head_v, CHIN, CROWN, 0.002, 4.0)
            check(pl["rounds"] == 1 and pl["tilt_deg"] == 4.0 and pl["tilt_solve"] == "manual"
                  and pl["tilt_source"] == "manual" and pl["forward_m"] == 0.002 and pl["forward_source"] == "manual"
                  and pl["hairline_aim_y"] is None, "manual: one round, values as given")
            check(near(pl["hairline_pushed_y"], 1.6054 + 0.095 * math.sin(math.radians(16)) + 0.006, 1e-5)
                  and near(pl["hairline_pushed_y"], 1.6375854, 1e-5), f"manual pushed 1.6375854 "
                  f"({pl['hairline_pushed_y']})")
        finally:
            gh._push = real_push

        # [7]
        print("[7] pitched-back head, nasion floor, push gate first")
        pitched = [(1.461, 0.200), (1.501, 0.252), (1.531, 0.243), (1.571, 0.265), (1.606, 0.270), (1.651, 0.249),
                   (1.700, 0.156)]
        P7 = np.array([(0.0, y, z) for y, z in pitched] + [(-0.083, 1.60, 0.17), (0.083, 1.60, 0.17),
                                                             (0.0, 1.60, 0.069)])
        lm7 = gh.head_landmarks(P7, np.ones(len(P7), bool), 1.45, 1.70)
        print("   ", lm7)
        check(lm7 is not None and near(lm7["nose_tip_y"], 1.5025, 1e-6) and near(lm7["nasion_y"], 1.5325, 1e-6)
              and near(lm7["brow_y"], 1.606, 1e-6), "pitched back: nose 1.5025, nasion 1.5325, brow 1.606")
        check(lm7 is not None and near(gh.hairline_target(lm7["brow_y"], lm7["crown_y"]), 1.6295, 1e-6),
              "pitched back: target 1.6295")
        strand = np.vstack([H, [PIVOT[0], 1.45, 0.20]])
        check(near(gh.front_hairline(strand, box), 1.45, 1e-9), "no floor: the strand at 1.45 is the hairline")
        check(near(gh.front_hairline(strand, box, 1.5625), 1.6378919, 1e-6), "floor 1.5625: the arc's 1.63789")

        def push_seq(values):
            calls = iter(values)

            def fake(Q, F, U, body):
                disp = np.zeros((len(Q), 3))
                disp[0, 0] = next(calls)
                return {"Qp": np.asarray(Q), "disp": disp}
            return fake

        try:
            body = SimpleNamespace(positions=P)
            F = np.zeros((0, 3), np.int64)
            low = H - [0, 0.01, 0]
            gh._push = push_seq([0.1349, 0.147, 0.1198])
            _, pl = gh._place_and_push(low, PIVOT, F, None, body, head_v, CHIN, CROWN, None, None)
            check(pl["tilt_deg"] == 3.0 and pl["tilt_solve"] == "at_or_below_target+push_gate"
                  and pl["gate_search"] == {"tried": [[0.0, 0.1349], [1.5, 0.147], [3.0, 0.1198]], "picked": 3.0},
                  f"gate search picks 3.0: {pl['tilt_solve']} {pl['gate_search']}")
            gh._push = push_seq([0.2] * 11)
            _, pl = gh._place_and_push(low, PIVOT, F, None, body, head_v, CHIN, CROWN, None, None)
            gs7 = pl["gate_search"] or {}
            check(pl["tilt_deg"] == 0 and gs7.get("picked") is None
                  and [t for t, _ in gs7.get("tried", [])] == [0.0] + [1.5 * k for k in range(1, 11)],
                  f"nothing passes: 11 tilts tried, tilt 0 kept ({gs7})")
            gh._push = push_seq([0.2])
            _, pl = gh._place_and_push(low, PIVOT, F, None, body, head_v, CHIN, CROWN, None, 0.0)
            check(pl["gate_search"] is None and pl["tilt_deg"] == 0, "manual tilt: no search")
        finally:
            gh._push = real_push

        # [6]
        print("[6] the whole fit on the sphere fixture")
        import smoke_garment_hairdeck_fit as fx
        body_glb = fx.body_glb()
        nohead, proxy = fx.hair_glbs(inner=False)
        res = gh.fit_hairdeck(nohead, proxy, body_glb, colour_target=None)
        pl = res.report["placement"]
        print("   ", {k: v for k, v in pl.items() if k != "landmarks"})
        check(pl["tilt_solve"] == "no_landmarks" and pl["tilt_deg"] == 0 and pl["forward_m"] == 0.006
              and pl["forward_source"] == "default" and pl["hairline_target_y"] is None, "no face: tilt 0, fwd 0.006")
        check(res.metrics["forward_m"] == 0.006 and res.metrics["tilt_deg"] == 0, "metrics carry forward/tilt")
        check(near(res.metrics["icp_scale"], 2.0, 0.01), f"head match unchanged ({res.metrics['icp_scale']})")
        check(near(pl["hairline_unadjusted_y"], 1.62, 1e-4) and near(pl["hairline_placed_y"], 1.62, 1e-4),
              f"forward moves no y: {pl['hairline_unadjusted_y']} / {pl['hairline_placed_y']}")
        for kwargs in ({"tilt_deg": 15.5}, {"forward_m": 0.031}, {"tilt_deg": float("nan")}):
            try:
                gh.fit_hairdeck(nohead, proxy, body_glb, colour_target=None, **kwargs)
                check(False, f"{kwargs} refused")
            except ValueError:
                check(True, f"{kwargs} -> ValueError")
        check(pl["landmark_source"] == "none" and pl["landmarks_rejected"] is None, "no face: landmark_source none")

        # [8]
        print("[8] landmark plausibility")
        kai = {"nose_tip_y": 1.61308, "nasion_y": 1.63308, "brow_y": 1.68363, "crown_y": 1.86}
        doubts = gh.landmark_doubts(kai, 1.58058, 1.86)
        check(doubts == ["brow 17.6 cm below the crown (plausible 8-13 cm)", "brow 1.684 not above the eye line 1.720"],
              f"Kai's reading: two doubts {doubts}")
        kira = {"nose_tip_y": 1.5029, "nasion_y": 1.5329, "brow_y": 1.60648, "crown_y": 1.70}
        check(gh.landmark_doubts(kira, 1.4504, 1.70) == [], "Kira's reading: plausible")
        lm2, src2, rej2 = gh.placement_landmarks(P, head_v, CHIN, CROWN)
        check(src2 == "profile" and rej2 is None and lm2 == lm, "[2] profile: source profile, same landmarks")
        lm7b, src7, _ = gh.placement_landmarks(P7, np.ones(len(P7), bool), 1.45, 1.70)
        check(src7 == "profile" and lm7b == lm7, "[7a] profile: source profile")
        beard = [(1.581, 0.080), (1.613, 0.137), (1.633, 0.131), (1.683, 0.172), (1.733, 0.151), (1.743, 0.155),
                 (1.768, 0.148), (1.788, 0.147), (1.833, 0.115), (1.858, 0.067)]
        P8 = np.array([(0.0, y, z) for y, z in beard] + [(-0.097, 1.75, 0.055), (0.097, 1.75, 0.055),
                                                           (0.0, 1.75, -0.06)])
        hv8 = np.ones(len(P8), bool)
        read = gh.head_landmarks(P8, hv8, 1.58, 1.86)
        print("   ", read)
        check(read is not None and near(read["nose_tip_y"], 1.6125, 1e-6) and near(read["nasion_y"], 1.6325, 1e-6)
              and near(read["brow_y"], 1.683, 1e-6), "bearded profile misread: nose 1.6125, nasion 1.6325, brow 1.683")
        lm8, src8, rej8 = gh.placement_landmarks(P8, hv8, 1.58, 1.86)
        print("   ", lm8, src8, rej8)
        check(src8 == "proportions" and near(lm8["brow_y"], 1.748, 1e-6) and near(lm8["nasion_y"], 1.692, 1e-6)
              and near(lm8["crown_y"], 1.86, 1e-9), "fallback: proportions, brow 1.748, floor 1.692")
        check(rej8 is not None and rej8["landmarks"] == read
              and rej8["doubts"] == ["brow 17.7 cm below the crown (plausible 8-13 cm)",
                                     "brow 1.683 not above the eye line 1.720"], f"rejected reading kept: {rej8}")
        check(near(gh.hairline_target(lm8["brow_y"], lm8["crown_y"]), 1.776, 1e-6)
              and near(gh.hairline_target(read["brow_y"], read["crown_y"]), 1.72725, 1e-6),
              "targets: 1.776 (fallback) vs 1.72725 (misreading)")
        pivot8 = np.array([0.0, 1.7555, 0.0448])
        phi = np.radians(np.arange(20, 91, 1.0))
        H8 = pivot8 + np.column_stack([np.zeros_like(phi), 0.095 * np.sin(phi), 0.095 * np.cos(phi)])
        try:
            gh._push = lambda Q, F, U, body: {"Qp": np.asarray(Q), "disp": np.zeros((len(Q), 3))}
            _, pl8 = gh._place_and_push(H8, pivot8, np.zeros((0, 3), np.int64), None,
                                        SimpleNamespace(positions=P8), hv8, 1.58, 1.86, None, None)
        finally:
            gh._push = real_push
        print("   ", {k: v for k, v in pl8.items() if k not in ("landmarks", "landmarks_rejected")})
        check(near(pl8["tilt_deg"], 7.538, 0.02) and pl8["tilt_solve"] == "solved" and pl8["rounds"] == 1,
              f"bearded head: tilt 7.538 solved in one round ({pl8['tilt_deg']}, {pl8['tilt_solve']})")
        check(pl8["landmark_source"] == "proportions" and near(pl8["hairline_floor_y"], 1.692, 1e-6)
              and near(pl8["hairline_target_y"], 1.776, 1e-5)
              and near((pl8["landmarks_rejected"] or {}).get("landmarks", {}).get("brow_y"), 1.683, 1e-6),
              "report: proportions, floor 1.692, target 1.776, rejected brow 1.683")
        check(near(pl8["hairline_pushed_y"], 1.776, 2e-4), f"hairline at the target ({pl8['hairline_pushed_y']})")
        t_old, how_old = gh.solve_tilt(H8, pivot8, 0.006, gh._head_box(P8, hv8), 1.72725, 1.6325)
        check((t_old, how_old) == (15.0, "clamped"), f"the misreading's target clamps at 15 ({t_old}, {how_old})")

        # [9]
        print("[9] moved_share per length class")
        for cls, want in ((None, 0.90), ("medium", 0.90), ("long", 0.90), ("short", 0.97), ("very short", 1.0)):
            g = gh.gates_for(cls)
            check(g["moved_share"][1] == want and g["max_push_m"] == gh.GATES["max_push_m"]
                  and g["icp_resid_p95_m"] == gh.GATES["icp_resid_p95_m"], f"{cls}: moved_share <= {want}")
        m9 = {"max_push_m": 0.0162, "moved_share": 0.93, "icp_resid_p95_m": 0.0074}
        ok9, why9 = gh.gate(m9)
        check(not ok9 and len(why9) == 1 and why9[0].startswith("moved_share 0.93 > 0.9"), f"no class: refused {why9}")
        check(gh.gate(m9, "short") == (True, []), "short: Kai's 0.93 passes")
        disp = np.zeros((100, 3))
        disp[:93, 0] = 0.01
        check(not gh._push_passes({"disp": disp}) and gh._push_passes({"disp": disp}, gh.gates_for("short")),
              "_push_passes: 0.93 refused by default, passed as short")
        inner_nohead, inner_proxy = fx.hair_glbs(inner=True)
        r9 = gh.fit_hairdeck(inner_nohead, inner_proxy, body_glb, colour_target=None, length_class="short",
                             **fx.NO_PLACEMENT)
        check(r9.ok and abs(r9.metrics["moved_share"] - 481 / 1922) <= 0.002,
              f"inner layer passes as short, only it moves: {r9.metrics['moved_share']} {r9.reasons}")

        # [10]
        print("[10] colour transfer")
        check(np.allclose(gh.linear_to_lab([1.0, 1.0, 1.0]), [100, 0, 0], atol=1e-3), "white -> (100, 0, 0)")
        kai_lab = gh.linear_to_lab([0.0431, 0.0314, 0.0235])
        brunette = (0x5c / 255, 0x3b / 255, 0x26 / 255)
        br_lab = gh.linear_to_lab(gh.srgb_to_linear(brunette))
        check(np.allclose(kai_lab, [21.33, 2.61, 6.10], atol=0.02), f"Kai's median Lab {kai_lab}")
        check(np.allclose(gh.srgb_to_linear(brunette), [0.107032, 0.043734, 0.019384], atol=1e-5)
              and np.allclose(br_lab, [28.23, 12.00, 18.89], atol=0.02), f"brunette Lab {br_lab}")
        check(near(gh.delta_e(kai_lab, br_lab), 17.30, 0.05), f"ΔE 17.30 ({gh.delta_e(kai_lab, br_lab):.3f})")
        lab3 = kai_lab + np.array([[-5.0, 0, 0], [0, 0, 0], [5.0, 0, 0]])
        C3 = np.column_stack([gh.lab_to_linear(lab3), np.full(3, 0.5)])
        out3, info3 = gh._transfer_colours(C3, brunette)
        new3 = gh.linear_to_lab(out3[:, :3])
        check(info3["applied"] and near(info3["delta_e_before"], 17.30, 0.05) and info3["delta_e_after"] <= 0.05,
              f"applied, ΔE 17.30 -> {info3['delta_e_after']}")
        check(np.allclose(new3[1], br_lab, atol=0.05) and np.allclose(new3[:, 0] - new3[1, 0], [-5, 0, 5], atol=0.05)
              and np.allclose(out3[:, 3], 0.5), f"median on brunette, L offsets kept: {new3[:, 0] - new3[1, 0]}")
        near3 = gh.lab_to_linear(lab3[1] + [3.0, 0, 0])
        out3b, info3b = gh._transfer_colours(C3, tuple(np.where(near3 <= 0.0031308, near3 * 12.92,
                                                                1.055 * near3 ** (1 / 2.4) - 0.055)))
        check(not info3b["applied"] and near(info3b["delta_e_before"], 3.0, 0.02) and np.array_equal(out3b, C3),
              f"within ΔE 5: kept ({info3b['delta_e_before']})")
        r10 = gh.fit_hairdeck(nohead, proxy, body_glb, colour_target=None, colour_profile=brunette, **fx.NO_PLACEMENT)
        c10 = r10.report["colour"]
        hair_cols = r10.garment.colors[:r10.report["vertices"]["hair"], :3]
        check(c10["method"] == "lab_transfer" and near(c10["delta_e_before"], 36.51, 0.05)
              and r10.metrics["colour_delta_e"] <= 0.05, f"fit: lab_transfer, ΔE 36.51 -> {r10.metrics['colour_delta_e']}")
        check(np.allclose(hair_cols, [0.107032, 0.043734, 0.019384], atol=1e-3), "every hair colour = brunette linear")
        r10b = gh.fit_hairdeck(nohead, proxy, body_glb, colour_target=(1.0, 0.5, 0.0), colour_profile=brunette,
                               **fx.NO_PLACEMENT)
        check(r10b.report["colour"]["method"] == "gain", "a manual target wins over the profile colour")

    print("ALL OK" if not FAILS else "FAILED: " + ", ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
