#!/usr/bin/env python3
"""Smoke check for the FOOT-PLANT maths of the clip importer
(``app/blender/scripts/_foot_plant.py``) — pure, no Blender.

Usage:  ./.venv/bin/python scripts/smoke_foot_plant_math.py

An actor's legs and the rig's differ in length and the importer copies
rotations only, so a foot the actor planted can stand off the rig's floor.
``_foot_plant`` decides WHERE the source says a foot is planted (weights per
frame) and bends the rig's leg so the foot reaches the floor (two-bone IK).
Every expected number below is derived by hand.

[P1] planted_frames: 30 fps, heights [0.5]*10 + [10]*10 + [0.5]*3 (frames
     0..22), floor 0, vy by central difference (one-sided at the ends):
     frames 0..8: 0.5 cm ≤ 1.5 and vy 0 → raw 1; frame 9: vy =
     (10 − 0.5)/2·30 = 142.5 → 0; frames 10..19: 10 cm → 0; frame 20: vy =
     (0.5 − 10)/2·30 → 0; frames 21..22: a run of 2 frames = 0.067 s < 0.2 s
     → 0. The run 0..8 (9 frames = 0.3 s) qualifies. Fade F = round(0.1·30)
     = 3 frames: w(f) = min(1, (f − a + 1)/(F + 1), (b − f + 1)/(F + 1)) for
     the run [a, b] — but a run that touches the TAKE's first or last frame
     does not fade on that side: the take's start is not a touchdown, and
     the last frame is the pose a bridge clip holds (the first version faded
     in at frame 0 — [0.25, 0.5, 0.75, …] — which left the corrected foot of
     get-up-chair only a quarter corrected on its final frame). The run
     [0, 8] starts at frame 0 → only the fade-out: w(f) = min(1,
     (8 − f + 1)/4) → [1, 1, 1, 1, 1, 1, 0.75, 0.5, 0.25, 0, …, 0].
[P1b] the fade on both sides, a run inside the take: heights [10]*3 +
     [0.5]*9 + [10]*3 (frames 0..14), floor 0. Frame 2: 10 cm → 0; frame 3:
     vy (0.5 − 10)/2·30 = −142.5 → 0; frames 4..10: 0.5 cm, vy 0 → raw 1;
     frame 11: vy (10 − 0.5)/2·30 → 0. Run [4, 10] = 7 frames = 0.233 s ≥
     0.2 s → w = (f − 3)/4 rising, (11 − f)/4 falling →
     [0, 0, 0, 0, 0.25, 0.5, 0.75, 1, 0.75, 0.5, 0.25, 0, 0, 0, 0].
[P2] two_bone_ik, a REACHABLE pull-down: hip H (0,100,0), knee K (0,50,15),
     ankle A (0,0,0), target T (0,−2,0), pole = K.
     Segment lengths l1 = |H−K| = √(50² + 15²) = √2725 = 52.2015 and
     l2 = |K−A| = √2725 = 52.2015; d = |H−T| = 102 < l1 + l2 = 104.4031.
     Equal segments → the new knee sits above the midpoint of H–T:
     y = 100 − d/2 = 49, and its distance off the line is
     √(l1² − (d/2)²) = √(2725 − 2601) = √124 = 11.1355, on the pole's side
     (+z) → knee (0, 49, 11.1355). Applying Δupper to K−H about H and
     Δlower·Δupper to A−K about the new knee: the ankle reaches (0,−2,0)
     within 1e-6, the knee stays in the plane x = 0 at (0, 49, 11.1355) and
     both segment lengths stay 52.2015 (all ±1e-6).
     (The brief's first version used K (0,50,5) with this target: its
     segments are √(50² + 5²) = 50.2494, l1 + l2 = 100.4988 < d = 102, so
     that target is OUT of reach — the case [P3] covers, not a reach test.)
[P3] target (0,−5,0) with K (0,50,5) is out of reach: hip→target is
     105 > 2·50.2494 = 100.4988 → fully stretched along the hip→target line,
     the ankle at (0, 100 − 100.4988, 0) = (0, −0.4988, 0) (±1e-6), the knee
     at (0, 100 − 50.2494, 0) = (0, 49.7506, 0).
[P4] a source foot held 3.5 cm up for 2 s (drinking, 60 frames at 30 fps):
     3.5 ≥ PLANT_BAND_HI 3.0 → raw 0 in every frame → weight 0 everywhere.
[P4b] a source foot HOVERING at 2.8 cm for 2 s (drinking's first second:
     the right ball at 2.6 … 3.0 cm, measured on 13_09): inside the ramp,
     raw = (3.0 − 2.8)/(3.0 − 1.5) = 0.1333 > 0 in every frame — but never
     at full weight. The 0.2 s the rule asks for are 0.2 s of the CONDITION
     (≤ 1.5 cm and ≤ 15 cm/s, i.e. raw 1); the ramps only soften the edges
     of such a contact → no full core → weight 0 everywhere.
[P5] foot_planted_frames ORs the points BEFORE the run rule: ankle planted
     on frames 0..3 (4 frames = 0.133 s, too short alone), ball planted on
     frames 3..8 (6 frames = 0.2 s — exactly PLANT_MIN_S), both over their
     own floor (ankle floor 5, ball floor 0), everything else 10 cm up.
     vy: every change is ≥ 5 cm between neighbours → the frame next to a
     jump gets |vy| ≥ 5/2·30 = 75 → raw 0. Ankle heights: 5 on 0..3,
     15 on 4..22 → raw 1 on 0..2, frame 3 vy (15 − 5)/2·30 = 150 → 0.
     Ball heights: 10 on 0..2, 0 on 3..8, 10 on 9..22 → frame 3 vy
     (0 − 10)/2·30 → 0, frames 4..7 raw 1, frame 8 vy (10 − 0)/2·30 → 0.
     So the ankle alone is planted 0..2 (0.1 s → 0), the ball alone 4..7
     (0.133 s → 0); per-point runs give nothing. The OR of the raw
     weights is 1 on 0..2 and 4..7 with frame 3 at 0 — two runs, 3 and 4
     frames, both < 6 frames → still all 0. Moving the ankle's release one
     frame later (ankle 5 on 0..4) makes frame 3 raw 1 (vy (5 − 5)/2·30 =
     0) and frame 4 raw 0 (vy (15 − 5)/2·30) — ball raw 1 on 4..7, so the
     OR is 1 on 0..7: one run of 8 frames = 0.267 s ≥ 0.2 → weights
     [1, 1, 1, 1, 1, 0.75, 0.5, 0.25] on frames 0..7 (F = 3, [a, b] =
     [0, 7], starting at the take's first frame → fade-out only:
     (7 − f + 1)/4 → f=4 → 1; f=5 → 3/4; f=7 → 1/4).
[P6] foot_lift: the lowest point over its own rest height decides —
     ankle 8.0 (rest 7.32), ball 2.5 (rest 0.08), tip 3.9 (rest 0.0) →
     lifts 0.68 / 2.42 / 3.9 → 0.68 (the ankle; the foot stands on its heel).
     A foot lower than rest: ankle 7.0 / ball −0.2 / tip 0.1 → −0.32 / −0.28 /
     0.1 → −0.32.
[P7] ankle_floor: the ankle's height while the SAME foot's ball is fully
     planted — the median of those frames; ankle heights [6, 6, 7, 9, 9],
     ball weights [1, 1, 1, 0, 0.5] → median(6, 6, 7) = 6. Ball never
     fully planted → None (the ankle is then not a detection point).
"""
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app" / "blender" / "scripts"))

import _foot_plant as fp                  # noqa: E402

TOL = 1e-6
failures = []


def check(label, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        failures.append(label)


def close(a, b, tol=TOL):
    return len(a) == len(b) and all(abs(x - y) <= tol for x, y in zip(a, b))


def qmat(q):
    w, x, y, z = q
    return ((1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)),
            (2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)),
            (2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)))


def rot(q, v):
    m = qmat(q)
    return tuple(sum(m[i][j] * v[j] for j in range(3)) for i in range(3))


def sub(a, b):
    return tuple(x - y for x, y in zip(a, b))


def add(a, b):
    return tuple(x + y for x, y in zip(a, b))


def solve(hip, knee, ankle, target):
    """Applies the IK the way the importer does: Δupper turns the thigh about
    the hip, Δlower·Δupper the shin about the new knee."""
    du, dl = fp.two_bone_ik(hip, knee, ankle, target, knee)
    k2 = add(hip, rot(du, sub(knee, hip)))
    a2 = add(k2, rot(dl, rot(du, sub(ankle, knee))))
    return du, dl, k2, a2


def main() -> int:
    print("[P1] planted_frames: run rule and fade")
    h = [0.5] * 10 + [10.0] * 10 + [0.5] * 3
    w = fp.planted_frames(h, 0.0, 30.0)
    want = [1, 1, 1, 1, 1, 1, 0.75, 0.5, 0.25] + [0.0] * 14
    check("weights (no fade-in at the take's start)", close(w, want),
          str([round(x, 3) for x in w]))
    h = [10.0] * 3 + [0.5] * 9 + [10.0] * 3
    w = fp.planted_frames(h, 0.0, 30.0)
    want = [0, 0, 0, 0, 0.25, 0.5, 0.75, 1, 0.75, 0.5, 0.25, 0, 0, 0, 0]
    check("[P1b] a run inside the take fades on both sides", close(w, want),
          str([round(x, 3) for x in w]))
    check("constants", (fp.PLANT_BAND_CM, fp.PLANT_BAND_HI_CM, fp.PLANT_VY_CM_S,
                        fp.PLANT_VY_HI_CM_S, fp.PLANT_MIN_S, fp.PLANT_FADE_S)
          == (1.5, 3.0, 15.0, 30.0, 0.2, 0.1))

    print("\n[P2] two_bone_ik: a reachable pull-down")
    hip, knee, ankle, target = (0, 100, 0), (0, 50, 15), (0, 0, 0), (0, -2, 0)
    _du, _dl, k2, a2 = solve(hip, knee, ankle, target)
    check("ankle reaches the target", close(a2, target), str(a2))
    check("knee at (0, 49, 11.1355)", close(k2, (0, 49, math.sqrt(124)), 1e-6), str(k2))
    check("knee in the plane x = 0", abs(k2[0]) <= TOL, str(k2))
    l = math.sqrt(2725)
    check("|hip − knee| = 52.2015", abs(math.dist(hip, k2) - l) <= TOL, str(math.dist(hip, k2)))
    check("|knee − ankle| = 52.2015", abs(math.dist(k2, a2) - l) <= TOL, str(math.dist(k2, a2)))

    print("\n[P3] two_bone_ik: out of reach → stretched along hip→target")
    hip, knee, ankle, target = (0, 100, 0), (0, 50, 5), (0, 0, 0), (0, -5, 0)
    _du, _dl, k2, a2 = solve(hip, knee, ankle, target)
    l = math.sqrt(2525)
    check("ankle at (0, −0.4988, 0)", close(a2, (0, 100 - 2 * l, 0)), str(a2))
    check("knee at (0, 49.7506, 0)", close(k2, (0, 100 - l, 0)), str(k2))

    print("\n[P4] a foot held 3.5 cm up is never planted")
    w = fp.planted_frames([3.5] * 60, 0.0, 30.0)
    check("weight 0 everywhere", w == [0.0] * 60, str(max(w)))

    print("\n[P4b] a hovering foot has no full contact → never planted")
    w = fp.planted_frames([2.8] * 60, 0.0, 30.0)
    check("weight 0 everywhere", w == [0.0] * 60, str(max(w)))

    print("\n[P5] foot_planted_frames: the points are ORed before the run rule")
    ball = [10.0] * 3 + [0.0] * 6 + [10.0] * 14
    ankle_short = [5.0] * 4 + [15.0] * 19
    w = fp.foot_planted_frames([(ankle_short, 5.0), (ball, 0.0)], 30.0)
    check("a gap frame splits the contact → too short → 0", w == [0.0] * 23,
          str([round(x, 3) for x in w]))
    ankle_long = [5.0] * 5 + [15.0] * 18
    w = fp.foot_planted_frames([(ankle_long, 5.0), (ball, 0.0)], 30.0)
    want = [1, 1, 1, 1, 1, 0.75, 0.5, 0.25] + [0.0] * 15
    check("one ORed run of 8 frames", close(w, want), str([round(x, 3) for x in w]))
    check("each point alone gives nothing",
          max(fp.planted_frames(ankle_long, 5.0, 30.0)) == 0.0
          and max(fp.planted_frames(ball, 0.0, 30.0)) == 0.0)

    print("\n[P6] foot_lift: the lowest point over its own rest height")
    rest = {"ankle": 7.32, "ball": 0.08, "tip": 0.0}
    v = fp.foot_lift({"ankle": 8.0, "ball": 2.5, "tip": 3.9}, rest)
    check("lift 0.68 (the ankle)", abs(v - 0.68) <= TOL, str(v))
    v = fp.foot_lift({"ankle": 7.0, "ball": -0.2, "tip": 0.1}, rest)
    check("lift −0.32 (below rest)", abs(v + 0.32) <= TOL, str(v))

    print("\n[P7] ankle_floor: the ankle's height while the ball is planted")
    v = fp.ankle_floor([6, 6, 7, 9, 9], [1, 1, 1, 0, 0.5])
    check("median of the planted frames = 6", v == 6, str(v))
    v = fp.ankle_floor([6, 6, 7], [0.5, 0, 0.9])
    check("ball never fully planted → None", v is None, str(v))

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): " + ", ".join(failures))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
