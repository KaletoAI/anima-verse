#!/usr/bin/env python3
"""Smoke: the studio's numeric checks on HAND-MADE measurements (no Blender).

Usage: ./.venv/bin/python scripts/smoke_animstudio_checks.py

Every case builds a tiny measure dict whose numbers are chosen so exactly
one check trips; the expectation is written next to it:
- clean standing (feet at y 0/1 cm, still)           -> every check ok
- a toe at y -2.0 cm                                  -> floor fails (-2.0 < -1.0)
- left ball in contact (y 1 cm) sliding 0 -> 3 cm in x -> slide fails (3.0 > 2.0)
- loop with last frame's hand 1.5 cm off frame 0      -> loop fails (1.5 > 1.0)
- tracks 7                                            -> tracks fails (7 < 8)
- seat with hips at 80 cm                             -> seat fails (80 not in 61..71)
- lie with hips at 20 cm                              -> lie ok
- compiled ik error 5 cm                              -> ik fails
- compiled loop_problems ["..."]                      -> loop_layers fails
- compiled extrema l_elbow_flex (0, 170)              -> limits fails (170 > 150)
- a measure whose frame 3 lacks LeftToeBase           -> StudioError naming
  LeftToeBase and the frame (not a bare KeyError)
- ground (kneeling): feet/toes at y 10/5 cm, knees (LeftLeg/RightLeg heads)
  at y 2 cm in every frame                            -> ok (min 2 <= 3.0)
- the same with the knees at y 5 cm                   -> ground_contact fails
  (min over feet, toes and knees = 5 > 3.0)
- sidecar {fps 30, frames 10, loop false, duration_s 0.333} for the 10
  still frames of a non-loop                          -> ok (0.333 =
  round(10/30, 3))
- sidecar frames 11 (measure has 10)                  -> sidecar fails
- sidecar loop true on a non-loop anim                -> sidecar fails
- sidecar fps 120                                     -> sidecar fails
  (and duration 0.333 != round(10/120, 3) = 0.083 — one check, one fail)
- sidecar duration_s 1.0 (10/30 = 0.333)              -> sidecar fails
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "animation-studio"))

from animstudio.checks import run_checks                              # noqa: E402
from animstudio.compile import Compiled                               # noqa: E402
from animstudio.dsl import Animation, Catalog                         # noqa: E402

FAIL = []


def frame(**over):
    f = {"Hips": [0, 100, 0], "LeftUpLeg": [9, 95, 0], "RightUpLeg": [-9, 95, 0],
         "LeftLeg": [9, 50, 0], "RightLeg": [-9, 50, 0],
         "LeftFoot": [9, 8, 0], "RightFoot": [-9, 8, 0],
         "LeftToeBase": [9, 1, 12], "RightToeBase": [-9, 1, 12],
         "LeftToe_End": [9, 0, 20], "RightToe_End": [-9, 0, 20],
         "LeftHand": [70, 100, 0], "RightHand": [-70, 100, 0], "Head": [0, 160, 0]}
    f.update(over)
    return f


def anim(group="stand", loop=False):
    return Animation(kind="s", duration_s=1.0, loop=loop,
                     catalog=Catalog(key="s", group=group, prompt="p"))


def comp(**kw):
    c = Compiled(frames=[], fps=30, loop=False, fingers=False)
    for k, v in kw.items():
        setattr(c, k, v)
    return c


def failing(checks):
    return sorted(c.name for c in checks if not c.ok)


def expect(name, checks, want):
    got = failing(checks)
    if got != want:
        FAIL.append(f"{name}: failing {got}, expected {want}")


still = {"tracks": 22, "frames": [frame() for _ in range(10)]}
expect("clean", run_checks(anim(), comp(), still), [])
expect("floor", run_checks(anim(), comp(), {"tracks": 22, "frames":
       [frame(LeftToe_End=[9, -2.0, 20])] + [frame()] * 9}), ["floor"])
slide = [frame(LeftToeBase=[9 + 3.0 * i / 9, 1, 12]) for i in range(10)]
expect("slide", run_checks(anim(), comp(), {"tracks": 22, "frames": slide}), ["foot_slide"])
lp = [frame()] * 9 + [frame(LeftHand=[71.5, 100, 0])]
expect("loop", run_checks(anim(loop=True), comp(), {"tracks": 22, "frames": lp}), ["loop_seam"])
expect("tracks", run_checks(anim(), comp(), {"tracks": 7, "frames": still["frames"]}), ["tracks"])
seat = [frame(Hips=[0, 80, 0], LeftUpLeg=[9, 78, 0], RightUpLeg=[-9, 78, 0],
              LeftLeg=[9, 78, 40], RightLeg=[-9, 78, 40])] * 10
expect("seat", run_checks(anim("seat"), comp(), {"tracks": 22, "frames": seat}), ["seat_height"])
lie = [frame(Hips=[0, 20, 0])] * 10
expect("lie", run_checks(anim("lie"), comp(), {"tracks": 22, "frames": lie}), [])
expect("ik", run_checks(anim(), comp(ik_error_cm={"l_hand": 5.0}), still), ["ik"])
expect("loop_layers", run_checks(anim(), comp(loop_problems=["x"]), still), ["loop_layers"])
expect("limits", run_checks(anim(), comp(extrema={"l_elbow_flex": (0.0, 170.0)}), still), ["limits"])

kneel = dict(Hips=[0, 40, 0], LeftLeg=[9, 2, 20], RightLeg=[-9, 2, 20],
             LeftFoot=[9, 10, -20], RightFoot=[-9, 10, -20],
             LeftToeBase=[9, 5, -30], RightToeBase=[-9, 5, -30])
ground = [frame(**kneel) for _ in range(10)]
expect("ground", run_checks(anim("ground"), comp(), {"tracks": 22, "frames": ground}), [])
hover = [frame(**{**kneel, "LeftLeg": [9, 5, 20], "RightLeg": [-9, 5, 20]}) for _ in range(10)]
expect("ground_hover", run_checks(anim("ground"), comp(), {"tracks": 22, "frames": hover}),
       ["ground_contact"])

side_ok = {"fps": 30, "frames": 10, "loop": False, "duration_s": 0.333}
expect("sidecar_ok", run_checks(anim(), comp(), still, side_ok), [])
for label, over in (("frames", {"frames": 11}), ("loop", {"loop": True}),
                    ("fps", {"fps": 120}), ("duration", {"duration_s": 1.0})):
    expect(f"sidecar_{label}", run_checks(anim(), comp(), still, {**side_ok, **over}),
           ["sidecar"])

from animstudio import StudioError                                    # noqa: E402

gap = [frame() for _ in range(10)]
del gap[3]["LeftToeBase"]
try:
    run_checks(anim(), comp(), {"tracks": 22, "frames": gap})
    FAIL.append("missing joint: run_checks accepted it")
except StudioError as e:
    if "LeftToeBase" not in str(e) or "3" not in str(e):
        FAIL.append(f"missing joint: message does not name it: {e}")
except Exception as e:                                                # noqa: BLE001
    FAIL.append(f"missing joint: {e!r} instead of StudioError")

print("FAIL:\n" + "\n".join(FAIL) if FAIL else "OK smoke_animstudio_checks")
sys.exit(1 if FAIL else 0)
