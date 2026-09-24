#!/usr/bin/env python3
"""Smoke check for the ROOT-MOTION maths of bridge clips
(``app/blender/scripts/_root_motion.py``) — pure, no Blender.

Usage:  ./.venv/bin/python scripts/smoke_root_motion_math.py

Frame of every case: clip frame, Y up, +Z forward, +X the figure's left, cm,
30 fps. The tracks are what the importer sees AFTER stripping the travel
(``strip``): the hips stay at the origin, so a foot that is planted in the
world slides BACKWARDS in these numbers by exactly the travel.

[1] ramp(v, lo=2, hi=5): 1 at or below lo, 0 at or above hi, linear between.
      ramp(1)=1, ramp(2)=1, ramp(3.5)=0.5, ramp(5)=0, ramp(6)=0, ramp(nan)=0.
[2] One planted point, sliding back 2 cm per frame (the chair case):
      LeftFoot y=8 (its rest height), x=0, z=-2f for f=0..10; rest 8.
      ground = min(p5(8…)=8, rest 8) = 8 → height weight 1; vy = 0 → weight 1.
      Δ(f→f+1) = −(−2) = +2 → path z = 2f, travel (0, 20).
      World track z + path = 0 for every frame → drift 0.
      With a zero path (the strip file) the drift is |−20 − 0| = 20.
[3] Point in the air the whole take: y=30, rest 8 → ground = min(30, 8) = 8,
      y − ground = 22 ≥ 5 → weight 0 → path all zero, travel (0, 0).
      (Without the rest guard the 5th percentile would call 30 cm "ground".)
[4] Air, then planted: f=0..4 y=30, f=5..10 y=8, z=-2f throughout, rest 8.
      Height weight: f≤4 → 0, f≥5 → 1.
      vy (central difference, one-sided at the ends, ×30 fps):
        f=4: (8−30)/2·30 = −330 → 0;  f=5: (8−30)/2·30 = −330 → 0;
        f=6: (8−8)/2·30 = 0 → 1.
      Pair weight min(w[f], w[f+1]): only f≥6 is 1.
      path z: f=0..6 → 0, f=7 → 2, f=8 → 4, f=9 → 6, f=10 → 8; travel (0, 8).
      contact_spans at full weight (w ≥ 0.999): [[6/30, 10/30]] = [[0.2, 0.333]].
[5] Two points: A planted (y=8, z=-2f), B in the air (y=30, z=+5f), rest 8.
      Only A carries weight → Δ = +2 per frame, path z = 2f (B is ignored).
[6] Two planted points that disagree: A z=-2f, B z=-4f, both y=8, rest 8.
      Δ = −(1·(−2) + 1·(−4)) / 2 = +3 per frame → path z = 3f, travel (0, 30).
[7] Degenerate: one frame → path [(0,0)], travel (0,0); a NaN position gets
      weight 0; a point name missing from the tracks is simply absent.
[8] rotate_travel((0, 40), yaw 90, 0, 0) → (40, 0)
      (x' = x cos a + z sin a, z' = −x sin a + z cos a — cmu_clip/clip_orient's
      yaw); (10, 0) at yaw 90 → (0, −10); (0, 40) at yaw 180 → (0, −40);
      (0, 40) at tilt 90: Rx(90) turns (0, 0, 40) into (0, −40, 0), so the
      horizontal part is (0, 0) within 1e-9.
[9] ONE vocabulary: the Blender side keeps its own copy of the modes
      (bpy scripts do not import the app package), so ``_root_motion.MODES``
      must equal ``animation_clips.ROOT_MOTION_MODES`` — the tuple the routes
      validate against — element for element, order included:
      ("strip", "keep", "foot_lock").
      (Importing animation_clips reads no storage: it only resolves clip
      directories when a function is called.)
[10] DOMINANT CONTACT — a fully planted point outranks a half-planted one.
      A planted: y=8 (rest 8), z=-2f → weight 1.
      B hovers: y=11.5, rest 8 → ground = min(11.5, 8) = 8, height 3.5 →
      ramp(3.5, 2, 5) = 0.5; vy = 0 → weight 0.5; it slides z=-6f.
      Old rule (plain weighted mean): Δ = −(1·(−2) + 0.5·(−6)) / 1.5 = +10/3
      per frame — the half-planted B drags the planted A by 4/3 cm a frame,
      13.33 cm over the take, although A is the only VERIFIED contact.
      New rule: while any point is in full contact (pair weight ≥ FULL), only
      full-contact points steer → Δ = +2, path z = 2f, travel (0, 20), drift
      of A = 0. (Real case: get-up-bed, a shuffling left foot at 2 cm height,
      weight 0.83–0.97, dragged the planted right foot by 2.02 cm.)
[11] NO full contact anywhere → the partial weights still steer, as before.
      A: y=11.5 (rest 8) → height 3.5 → weight 0.5, z=-2f;
      B: y=12.25 (rest 8) → height 4.25 → ramp = (5−4.25)/3 = 0.25, z=-5f.
      Δ = −(0.5·(−2) + 0.25·(−5)) / 0.75 = 2.25/0.75 = +3 → path z = 3f,
      travel (0, 30).
      [6] stays as derived: both points there are FULL, so the mean of the
      full points is the old mean (path z = 3f).
"""
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app/blender/scripts"))
import _root_motion as rm  # noqa: E402

FPS = 30.0
EPS = 1e-6
N = 11  # frames 0..10

failed = 0
passed = 0


def check(label, ok, detail=""):
    global failed, passed
    if ok:
        passed += 1
        print(f"  ok   {label}" + (f" — {detail}" if detail else ""))
    else:
        failed += 1
        print(f"  FAIL {label}" + (f" — {detail}" if detail else ""))


def near(label, actual, expected, eps=EPS):
    check(label, math.isfinite(actual) and abs(actual - expected) <= eps,
          f"got {actual!r}, expected {expected!r}")


def near_path(label, path, expected, eps=EPS):
    ok = len(path) == len(expected) and all(
        abs(p[0] - e[0]) <= eps and abs(p[1] - e[1]) <= eps
        for p, e in zip(path, expected))
    check(label, ok, f"got {path!r}, expected {expected!r}")


def solve(tracks, rest):
    """The full chain: ground → weights → path."""
    ground = rm.ground_heights(tracks, rest)
    weights = rm.contact_weights(tracks, ground, FPS)
    return ground, weights, rm.foot_lock_path(tracks, weights)


# ---------------------------------------------------------------- [0] consts
print("[0] constants")
check("MODES", rm.MODES == ("strip", "keep", "foot_lock"), repr(rm.MODES))
check("CONTACT_POINTS",
      rm.CONTACT_POINTS == ("LeftFoot", "LeftToeBase", "RightFoot", "RightToeBase"),
      repr(rm.CONTACT_POINTS))

# ------------------------------------------------------------------ [1] ramp
print("[1] ramp(v, 2, 5)")
for v, want in ((1, 1.0), (2, 1.0), (3.5, 0.5), (5, 0.0), (6, 0.0)):
    near(f"ramp({v})", rm.ramp(v, 2.0, 5.0), want)
near("ramp(nan)", rm.ramp(float("nan"), 2.0, 5.0), 0.0)

# ---------------------------------------------------- [2] one planted point
print("[2] one planted point sliding back 2 cm/frame")
tracks = {"LeftFoot": [(0.0, 8.0, -2.0 * f) for f in range(N)]}
rest = {"LeftFoot": 8.0}
ground, weights, path = solve(tracks, rest)
near("ground = 8", ground["LeftFoot"], 8.0)
check("every weight is 1", all(abs(w - 1.0) <= EPS for w in weights["LeftFoot"]),
      repr(weights["LeftFoot"]))
near_path("path z = 2f", path, [(0.0, 2.0 * f) for f in range(N)])
near("travel x = 0", path[-1][0], 0.0)
near("travel z = 20", path[-1][1], 20.0)
near("drift with the foot-lock path = 0",
     rm.max_planted_drift(tracks, weights, path), 0.0)
near("drift with a zero path (strip) = 20",
     rm.max_planted_drift(tracks, weights, [(0.0, 0.0)] * N), 20.0)

# ----------------------------------------------------- [3] air all the take
print("[3] point in the air the whole take")
tracks = {"LeftFoot": [(0.0, 30.0, -2.0 * f) for f in range(N)]}
ground, weights, path = solve(tracks, {"LeftFoot": 8.0})
near("ground = min(30, rest 8) = 8", ground["LeftFoot"], 8.0)
check("every weight is 0", all(w == 0.0 for w in weights["LeftFoot"]),
      repr(weights["LeftFoot"]))
near_path("path all zero", path, [(0.0, 0.0)] * N)

# --------------------------------------------------- [4] air, then planted
print("[4] air f=0..4, planted f=5..10")
tracks = {"LeftFoot": [(0.0, 30.0 if f <= 4 else 8.0, -2.0 * f) for f in range(N)]}
ground, weights, path = solve(tracks, {"LeftFoot": 8.0})
w = weights["LeftFoot"]
near("ground = 8", ground["LeftFoot"], 8.0)
for f in (0, 4, 5):
    near(f"w[{f}] = 0", w[f], 0.0)
for f in (6, 7, 10):
    near(f"w[{f}] = 1", w[f], 1.0)
near_path("path z 0×7, 2, 4, 6, 8", path,
          [(0.0, 0.0)] * 7 + [(0.0, 2.0), (0.0, 4.0), (0.0, 6.0), (0.0, 8.0)])
near("travel z = 8", path[-1][1], 8.0)
spans = rm.contact_spans(weights, FPS)
check("one contact span", len(spans) == 1, repr(spans))
if spans:
    near("span start = 6/30 = 0.2", spans[0][0], 0.2)
    near("span end = round(10/30, 3) = 0.333", spans[0][1], 0.333)

# ------------------------------------------- [5] one planted, one in the air
print("[5] A planted, B in the air")
tracks = {"LeftFoot": [(0.0, 8.0, -2.0 * f) for f in range(N)],
          "RightFoot": [(0.0, 30.0, 5.0 * f) for f in range(N)]}
ground, weights, path = solve(tracks, {"LeftFoot": 8.0, "RightFoot": 8.0})
check("B carries no weight", all(x == 0.0 for x in weights["RightFoot"]),
      repr(weights["RightFoot"]))
near_path("path z = 2f (B ignored)", path, [(0.0, 2.0 * f) for f in range(N)])

# --------------------------------------------- [6] two planted, disagreeing
print("[6] two planted points that disagree")
tracks = {"LeftFoot": [(0.0, 8.0, -2.0 * f) for f in range(N)],
          "RightFoot": [(0.0, 8.0, -4.0 * f) for f in range(N)]}
ground, weights, path = solve(tracks, {"LeftFoot": 8.0, "RightFoot": 8.0})
near_path("path z = 3f", path, [(0.0, 3.0 * f) for f in range(N)])
near("travel z = 30", path[-1][1], 30.0)

# ------------------------------------------------------------ [7] degenerate
print("[7] degenerate inputs")
tracks = {"LeftFoot": [(0.0, 8.0, 0.0)]}
ground, weights, path = solve(tracks, {"LeftFoot": 8.0})
near_path("one frame → path [(0, 0)]", path, [(0.0, 0.0)])
near("one frame → travel z = 0", path[-1][1], 0.0)
nan = float("nan")
tracks = {"LeftFoot": [(0.0, 8.0, 0.0), (nan, nan, nan), (0.0, 8.0, 0.0)]}
ground, weights, path = solve(tracks, {"LeftFoot": 8.0, "RightFoot": 8.0})
near("NaN position → weight 0", weights["LeftFoot"][1], 0.0)
check("NaN frame keeps the path finite",
      all(math.isfinite(c) for p in path for c in p), repr(path))
check("point missing from the tracks is absent from ground",
      "RightFoot" not in ground, repr(sorted(ground)))
check("point missing from the tracks is absent from weights",
      "RightFoot" not in weights, repr(sorted(weights)))
check("empty tracks → empty path", rm.foot_lock_path({}, {}) == [])

# -------------------------------------------------------------- [8] rotation
print("[8] rotate_travel")
for args, want, eps in ((((0.0, 40.0), 90, 0, 0), (40.0, 0.0), EPS),
                        (((10.0, 0.0), 90, 0, 0), (0.0, -10.0), EPS),
                        (((0.0, 40.0), 180, 0, 0), (0.0, -40.0), EPS),
                        (((0.0, 40.0), 0, 90, 0), (0.0, 0.0), 1e-9)):
    got = rm.rotate_travel(*args)
    near(f"rotate_travel{args} x", got[0], want[0], eps)
    near(f"rotate_travel{args} z", got[1], want[1], eps)

# ------------------------------------------------------- [9] mode parity
print("[9] the Blender copy of the modes matches the app's")
sys.path.insert(0, str(ROOT))
from app.core import animation_clips  # noqa: E402

check("_root_motion.MODES == animation_clips.ROOT_MOTION_MODES",
      tuple(rm.MODES) == tuple(getattr(animation_clips, "ROOT_MOTION_MODES", ())),
      f"{rm.MODES!r} vs {getattr(animation_clips, 'ROOT_MOTION_MODES', None)!r}")
check("and both are ('strip', 'keep', 'foot_lock')",
      tuple(rm.MODES) == ("strip", "keep", "foot_lock"), repr(rm.MODES))

# ----------------------------------------------------- [10] dominant contact
print("[10] a fully planted point outranks a half-planted one")
tracks = {"LeftFoot": [(0.0, 8.0, -2.0 * f) for f in range(N)],
          "RightFoot": [(0.0, 11.5, -6.0 * f) for f in range(N)]}
ground, weights, path = solve(tracks, {"LeftFoot": 8.0, "RightFoot": 8.0})
check("B weighs 0.5 in every frame",
      all(abs(x - 0.5) <= EPS for x in weights["RightFoot"]), repr(weights["RightFoot"]))
near_path("path z = 2f (A alone steers)", path, [(0.0, 2.0 * f) for f in range(N)])
near("travel z = 20", path[-1][1], 20.0)
near("drift of A = 0", rm.max_planted_drift({"LeftFoot": tracks["LeftFoot"]},
                                             weights, path), 0.0)

# ------------------------------------------------- [11] only partial contact
print("[11] no full contact anywhere: the partial weights steer")
tracks = {"LeftFoot": [(0.0, 11.5, -2.0 * f) for f in range(N)],
          "RightFoot": [(0.0, 12.25, -5.0 * f) for f in range(N)]}
ground, weights, path = solve(tracks, {"LeftFoot": 8.0, "RightFoot": 8.0})
near("A weighs 0.5", weights["LeftFoot"][3], 0.5)
near("B weighs 0.25", weights["RightFoot"][3], 0.25)
near_path("path z = 3f", path, [(0.0, 3.0 * f) for f in range(N)])
near("travel z = 30", path[-1][1], 30.0)

print(f"\n{passed} ok, {failed} failed")
sys.exit(1 if failed else 0)
