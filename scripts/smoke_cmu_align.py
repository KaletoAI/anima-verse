#!/usr/bin/env python3
"""Smoke check for the CMU→Mixamo REST ALIGNMENT — ``_cmu.rest_align`` and the
bone sets of ``cmu_clip`` that call it.

Usage:  ./.venv/bin/python scripts/smoke_cmu_align.py
        (no Blender, no server, no world DB; the end-to-end section needs the
         local CMU mirror under shared/models/mocap-src/ and skips without it)

===========================================================================
WHY THIS FILE EXISTS
===========================================================================
Finding 2026-08-31: every figure in the 3D client stood on the OUTER EDGES of
its feet with the toes turned INWARDS, and every head leaned to one side — on
every model, from every image source. Measured through the whole chain (clip
file → `adaptExternalClips` → a real character GLB) the numbers were identical
to a tenth of a degree on four different rigs, which is the signature of a
defect in the CLIPS, not in the models:

    idle.fbx, median over 24 poses, on 3 server-generated rigs + Soldier.glb
        foot roll   L +18.0°   R −19.9°   (supination, sole on its outer edge)
        foot yaw    L −11.5°   R +19.4°   (both toes turned inwards)
        head lateral          +22°

The cause is one wrong assumption in ``cmu_clip._solve``: it drives the Mixamo
bone with the CMU bone's world rotation alone, which is only the rotation away
from rest if BOTH skeletons hold that segment in the same rest orientation.
For three groups of bones they do not, and the ASF says so itself:

  * FEET/TOES twist. A CMU bone's rest frame is its ``axis`` matrix ``C``, and
    every single .asf of the database carries the same hard-coded template
    ``axis -90 0 ±20`` for lfoot/ltoes/rfoot/rtoes: the rest foot is modelled
    20° SUPINATED. Proof that ``C``'s first column really is the foot's
    medio-lateral axis: over a take it stays HORIZONTAL (median −6.6°…+6.6° on
    subjects 07/113/137) while the world X axis the pipeline used instead
    wanders 13-22° off. Ignoring ``C`` transplants those 20° into the clip.
  * FEET stance splay. The .asf ``direction`` of lfoot/rfoot carries the
    actor's own toe-out (median +4.7° / −5.4°, min 1.3°, max 14.9° over the
    118 subjects mirrored locally). Dropping it turns the toes INWARDS.
  * NECK/HEAD lean. The .asf directions of lowerneck/upperneck carry the
    actor's calibration lean out of the sagittal plane: median +1.3° but up to
    +20.2° (subject 113 — the subject of idle.fbx, the clip a standing NPC
    plays most).

The fix aligns the whole rest FRAME (direction AND medio-lateral axis) for
those bones, and for the feet/toes divides the swing about the medio-lateral
axis back out, because the ankle PITCH is the one thing the two skeletons draw
differently on purpose (Mixamo: a fixed 34° down; CMU: 11-34° per actor) and
the floor fit is calibrated on the Mixamo one. Aligning the pitch as well is
what lifted the ball of the foot in the 2026-08-21 attempt.

---------------------------------------------------------------------------
[1] drop_swing — the pure rule, hand-derived
---------------------------------------------------------------------------
A rotation purely ABOUT the axis has to vanish, one purely perpendicular to it
has to survive, and the result must stay a rotation matrix.

---------------------------------------------------------------------------
[2] rest_align on the real numbers of the reference rig
---------------------------------------------------------------------------
Measured off ``shared/models/rig/reference.fbx`` (bone head → child head, and
the bone node's own X axis, in the armature's Y-up space):

    LeftFoot   direction (0, −0.554, 0.833)   medio-lateral axis (−1, 0, 0)
    RightFoot  direction (0, −0.554, 0.833)   medio-lateral axis (−1, 0, 0)
    Neck       direction (0,  0.966, 0.258)   medio-lateral axis ( 1, 0, 0)
    Head       direction (0,  0.993, 0.119)   medio-lateral axis ( 1, 0, 0)

and ``cross(direction, up)`` reproduces every one of those medio-lateral axes
— which is what makes the geometric definition in ``rest_align`` legitimate:
the Mixamo rest is a T-pose with flat, straight feet.

Against the CMU foot template (``axis -90 0 20``, ``direction`` at 5° splay,
13° down) the alignment must therefore
  * carry the Mixamo medio-lateral axis onto the CMU one (the 20° roll), and
  * leave the pitch of the direction where Mixamo drew it (≤ 1°),
while the plain direction alignment used for the limbs leaves the roll fully
in place.

---------------------------------------------------------------------------
[3] END-TO-END on the takes the library was cut from
---------------------------------------------------------------------------
``_cmu.solve_frame`` + the alignment, i.e. exactly the ``P = R·A·R_mix`` of
``cmu_clip._solve``, measured against the mocap's own answer for the segment
(``R·C·X`` for the roll, ``R·direction`` for heading and lean). Medians over
the take. Hand-derived from the diagnosis above:

    take            defect        today      after
    113_21 idle     foot roll     ±20.0°     0.0°
                    toe-in        ∓12.4°     ≤3°
                    head lateral  −21.6°     0.0°
    07_01  walk     foot roll     ±18.9°     0.0°
                    toe-in        ∓16.4°     ≤4°
                    head lateral   −7.5°     0.0°
    137_28 waiting  foot roll     ±19.7°     0.0°
    14_30  sit      foot roll     ±19.8°     0.0°

and the ankle PITCH must not run away: the change against today stays under
5° (the frame alignment WITHOUT keep_pitch would move it 11-21°, which is the
regression this check exists to prevent).
"""
import math
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app/blender/scripts"))
import _cmu  # noqa: E402

MOCAP = ROOT / "shared/models/mocap-src/cmu"
DEG = 180.0 / math.pi

# The reference rig, measured (see the docstring).
MIX = {
    "LeftFoot": (0.0, -0.554, 0.833),
    "RightFoot": (0.0, -0.554, 0.833),
    "Neck": (0.0, 0.966, 0.258),
    "Head": (0.0, 0.993, 0.119),
}
MIX_ML = {"LeftFoot": (-1.0, 0.0, 0.0), "RightFoot": (-1.0, 0.0, 0.0),
          "Neck": (1.0, 0.0, 0.0), "Head": (1.0, 0.0, 0.0)}
BONE_OF = {"LeftFoot": "lfoot", "RightFoot": "rfoot",
           "Neck": "lowerneck", "Head": "upperneck"}

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


def near(label, actual, expected, eps):
    check(label, math.isfinite(actual) and abs(actual - expected) <= eps,
          f"{actual:.3f} (expected {expected} ±{eps})")


def at_most(label, actual, limit):
    check(label, math.isfinite(actual) and abs(actual) <= limit,
          f"{actual:.3f} (expected |x| <= {limit})")


def ang_h(v):
    """Angle of a vector off the horizontal plane, degrees."""
    return math.asin(max(-1.0, min(1.0, _cmu.normalize(v)[1]))) * DEG


def yaw(v):
    return math.atan2(v[0], v[2]) * DEG


class _FakeBone:
    """What rest_align reads off a bone."""

    def __init__(self, direction, axis, order="XYZ"):
        self.direction = direction
        self.C = _cmu.euler(axis, order)


print("[1] drop_swing — the pure rule")
ax = (0.0, 0.0, 1.0)
near("a rotation purely about the axis vanishes",
     max(abs(_cmu.drop_swing(_cmu.rot_z(30), ax)[i][j] - _cmu.identity()[i][j])
         for i in range(3) for j in range(3)), 0.0, 1e-9)
near("a rotation perpendicular to the axis survives",
     max(abs(_cmu.drop_swing(_cmu.rot_z(30), (1.0, 0.0, 0.0))[i][j] - _cmu.rot_z(30)[i][j])
         for i in range(3) for j in range(3)), 0.0, 1e-9)
_m = _cmu.drop_swing(_cmu.mat_mul(_cmu.rot_x(20), _cmu.rot_z(35)), ax)
near("the result stays orthonormal",
     max(abs(_cmu.dot(_cmu.mat_vec(_m, e), _cmu.mat_vec(_m, e)) - 1.0)
         for e in ((1, 0, 0), (0, 1, 0), (0, 0, 1))), 0.0, 1e-9)

print("\n[2] rest_align on the reference rig's own rest")
near("cross(direction, up) reproduces the LeftFoot medio-lateral axis",
     max(abs(a - b) for a, b in zip(_cmu.normalize(_cmu.cross(MIX["LeftFoot"], _cmu.UP)),
                                    MIX_ML["LeftFoot"])), 0.0, 1e-3)
near("cross(direction, up) reproduces the Neck medio-lateral axis",
     max(abs(a - b) for a, b in zip(_cmu.normalize(_cmu.cross(MIX["Neck"], _cmu.UP)),
                                    (-1.0, 0.0, 0.0))), 0.0, 1e-3)
# The direction has to come from the mapped CHILD's rest head, never from the
# Blender bone's tail: the reference rig draws Neck and Head straight up, and
# for a vertical bone the cross product above is noise whose SIGN flips.
check("a bone along the vertical is refused rather than aligned",
      _cmu.rest_align((0.0, 1.0, 0.0), _FakeBone((0.345, 0.935, -0.085), (0.0, 0.0, 0.0))) is None,
      "rest_align((0,1,0), …) is None")
check("...and one 2° off the vertical too (the cross product is still noise)",
      _cmu.rest_align((0.0, 0.9994, 0.035), _FakeBone((0.345, 0.935, -0.085), (0.0, 0.0, 0.0))) is None,
      "rest_align((0,0.9994,0.035), …) is None")
check("the real Neck direction (15° forward) is aligned",
      _cmu.rest_align(MIX["Neck"], _FakeBone((-0.175, 0.982, -0.076), (0.0, 0.0, 0.0))) is not None)

foot = _FakeBone((0.084, -0.232, 0.969), (-90.0, 0.0, 20.0))     # subject 113, lfoot
a_keep = _cmu.rest_align(MIX["LeftFoot"], foot, keep_pitch=True)
a_full = _cmu.rest_align(MIX["LeftFoot"], foot, keep_pitch=False)
cmu_ml = (foot.C[0][0], foot.C[1][0], foot.C[2][0])
near("the CMU foot rest is modelled 20° supinated", ang_h(cmu_ml), 20.0, 0.1)
near("keep_pitch carries the Mixamo medio-lateral axis onto the CMU one",
     ang_h(_cmu.mat_vec(a_keep, MIX_ML["LeftFoot"])), -20.0, 0.2)
near("...and so does the full frame alignment",
     ang_h(_cmu.mat_vec(a_full, MIX_ML["LeftFoot"])), -20.0, 0.2)
at_most("keep_pitch leaves the ankle pitch where Mixamo drew it",
        ang_h(_cmu.mat_vec(a_keep, MIX["LeftFoot"])) - ang_h(MIX["LeftFoot"]), 3.0)
check("the full frame alignment would lift the ball instead",
      abs(ang_h(_cmu.mat_vec(a_full, MIX["LeftFoot"])) - ang_h(MIX["LeftFoot"])) > 15.0,
      f"pitch moves {ang_h(_cmu.mat_vec(a_full, MIX['LeftFoot'])) - ang_h(MIX['LeftFoot']):.1f}°")
near("the plain direction alignment (what the limbs use) leaves the roll in place",
     ang_h(_cmu.mat_vec(_cmu.rot_between(MIX["LeftFoot"], foot.direction), MIX_ML["LeftFoot"])),
     0.0, 3.0)
# The heading: the alignment is not a pure yaw — carrying the medio-lateral
# axis over is a 20° roll about the foot's own axis, and that moves the
# heading with it. All this case pins down is the SIDE and the order of
# magnitude; what the clip ends up with is measured end to end in [3].
check("keep_pitch turns the foot towards the actor's stance splay",
      0.0 < yaw(_cmu.mat_vec(a_keep, MIX["LeftFoot"])) < 20.0,
      f"{yaw(_cmu.mat_vec(a_keep, MIX['LeftFoot'])):.1f}° "
      f"(the actor's splay is {yaw(foot.direction):.1f}°, Mixamo's rest 0°)")

neck = _FakeBone((0.345, 0.935, -0.085), (0.0, 0.0, 0.0))        # subject 113, upperneck
a_neck = _cmu.rest_align(MIX["Head"], neck)
near("the head alignment reproduces the actor's lean exactly",
     math.asin(max(-1.0, min(1.0, _cmu.normalize(_cmu.mat_vec(a_neck, MIX["Head"]))[0]))) * DEG,
     math.asin(neck.direction[0]) * DEG, 0.1)

print("\n[3] end-to-end on the takes the library was cut from")
CASES = [("idle", "113", "113_21", 20.0, 12.4, 21.6),
         ("walk", "07", "07_01", 18.9, 16.4, 7.5),
         ("waiting", "137", "137_28", 19.7, 9.9, 1.0),
         ("sit", "14", "14_30", 19.8, 13.1, 2.3)]


def measure(subject, take):
    sk = _cmu.parse_asf((MOCAP / subject / f"{subject}.asf").read_text(errors="replace"))
    frames = _cmu.parse_amc((MOCAP / subject / f"{take}.amc").read_text(errors="replace"))
    poses = [_cmu.solve_frame(sk, f) for f in frames[::8]]
    align = {}
    for mixname, cmuname in BONE_OF.items():
        b = sk.bones[cmuname]
        align[mixname] = {
            "none": _cmu.identity(),
            "fixed": _cmu.rest_align(MIX[mixname], b,
                                     keep_pitch=mixname in ("LeftFoot", "RightFoot")),
            "nokeep": _cmu.rest_align(MIX[mixname], b, keep_pitch=False),
        }
    out = {}
    for mode in ("none", "fixed", "nokeep"):
        acc = {}
        for pose in poses:
            chest = pose.rot["thorax"]
            for mixname, cmuname in BONE_OF.items():
                r = _cmu.mat_mul(pose.rot[cmuname], align[mixname][mode])
                b = sk.bones[cmuname]
                cml = (b.C[0][0], b.C[1][0], b.C[2][0])
                if _cmu.dot(cml, MIX_ML[mixname]) < 0:
                    cml = tuple(-c for c in cml)
                if mixname in ("LeftFoot", "RightFoot"):
                    acc.setdefault(mixname + ".roll", []).append(
                        ang_h(_cmu.mat_vec(r, MIX_ML[mixname])) - ang_h(_cmu.mat_vec(pose.rot[cmuname], cml)))
                    acc.setdefault(mixname + ".yaw", []).append(
                        yaw(_cmu.mat_vec(r, MIX[mixname])) - yaw(_cmu.mat_vec(pose.rot[cmuname], b.direction)))
                    acc.setdefault(mixname + ".pitch", []).append(
                        ang_h(_cmu.mat_vec(r, MIX[mixname])))
                if mixname == "Head":
                    inv = _cmu.transpose(chest)

                    def lat(v):
                        return math.asin(max(-1.0, min(1.0, _cmu.normalize(_cmu.mat_vec(inv, v))[0]))) * DEG
                    acc.setdefault("Head.lat", []).append(
                        lat(_cmu.mat_vec(r, MIX[mixname]))
                        - lat(_cmu.mat_vec(pose.rot[cmuname], b.direction)))
        out[mode] = {k: statistics.median(v) for k, v in acc.items()}
    return out


if not (MOCAP / "113" / "113_21.amc").is_file():
    print(f"  SKIP the CMU mirror is not present under {MOCAP}")
else:
    for name, subject, take, roll_now, toein_now, head_now in CASES:
        if not (MOCAP / subject / f"{take}.amc").is_file():
            print(f"  SKIP {name}: {take}.amc not mirrored")
            continue
        m = measure(subject, take)
        print(f"  -- {name} ({take})")
        near(f"{name}: today's LEFT foot roll error", m["none"]["LeftFoot.roll"], roll_now, 2.0)
        near(f"{name}: today's RIGHT foot roll error", m["none"]["RightFoot.roll"], -roll_now, 2.0)
        near(f"{name}: fixed LEFT foot roll error", m["fixed"]["LeftFoot.roll"], 0.0, 0.01)
        near(f"{name}: fixed RIGHT foot roll error", m["fixed"]["RightFoot.roll"], 0.0, 0.01)
        near(f"{name}: today's toe-in (left)", m["none"]["LeftFoot.yaw"], -toein_now, 4.0)
        at_most(f"{name}: fixed toe-in (left)", m["fixed"]["LeftFoot.yaw"], 4.0)
        at_most(f"{name}: fixed toe-in (right)", m["fixed"]["RightFoot.yaw"], 9.0)
        near(f"{name}: today's head lean error", m["none"]["Head.lat"], -head_now, 3.0)
        near(f"{name}: fixed head lean error", m["fixed"]["Head.lat"], 0.0, 0.01)
        at_most(f"{name}: the ankle pitch barely moves",
                m["fixed"]["LeftFoot.pitch"] - m["none"]["LeftFoot.pitch"], 5.0)
        check(f"{name}: RED COUNTER-PROBE — aligning the pitch too would lift the ball",
              abs(m["nokeep"]["LeftFoot.pitch"] - m["none"]["LeftFoot.pitch"]) > 8.0,
              f"{m['nokeep']['LeftFoot.pitch'] - m['none']['LeftFoot.pitch']:+.1f}°")

print("\n[4] the SAGITTAL pitch must never be aligned (regression 2026-08-31)")
# Aligning the neck/head pitch as well tipped every figure's gaze UP while
# walking. The rest difference is a DRAWING difference, one-sided over all 109
# mirrored subjects: ankle +20.8/+18.5 median, Neck +9.7 mean ±4.3 (never
# below -0.2), Head +14.3 mean ±5.7 (never below +0.8). Hand values for the
# head shift the pitch-aligning variant would produce, measured per take:
#     07_01 walk +19.4째   14_30 sit +17.2째   79_69 victory +19.3째
#     114_11 laying +22.6째   137_28 waiting +7.0째
PITCH_CASES = [("walk", "07", "07_01", 19.4), ("sit", "14", "14_30", 17.2),
               ("victory", "79", "79_69", 19.3), ("waiting", "137", "137_28", 7.0)]


def head_sagittal(subject, take, keep_pitch):
    """Median sagittal angle of the Mixamo head direction in the chest frame;
    positive = the head tips BACK. keep_pitch=None means no alignment."""
    sk = _cmu.parse_asf((MOCAP / subject / f"{subject}.asf").read_text(errors="replace"))
    frames = _cmu.parse_amc((MOCAP / subject / f"{take}.amc").read_text(errors="replace"))
    b = sk.bones["upperneck"]
    a = (_cmu.identity() if keep_pitch is None
         else _cmu.rest_align(MIX["Head"], b, keep_pitch=keep_pitch))
    out = []
    for f in frames[::8]:
        pose = _cmu.solve_frame(sk, f)
        v = _cmu.normalize(_cmu.mat_vec(_cmu.transpose(pose.rot["thorax"]),
                                        _cmu.mat_vec(_cmu.mat_mul(pose.rot["upperneck"], a),
                                                     MIX["Head"])))
        out.append(-math.atan2(v[2], v[1]) * DEG)
    return statistics.median(out)


if not (MOCAP / "07" / "07_01.amc").is_file():
    print(f"  SKIP the CMU mirror is not present under {MOCAP}")
else:
    for name, subject, take, shift in PITCH_CASES:
        if not (MOCAP / subject / f"{take}.amc").is_file():
            print(f"  SKIP {name}")
            continue
        base = head_sagittal(subject, take, None)
        kept = head_sagittal(subject, take, True)
        aligned = head_sagittal(subject, take, False)
        at_most(f"{name}: keep_pitch leaves the head's sagittal pitch alone",
                kept - base, 1.0)
        near(f"{name}: RED COUNTER-PROBE — aligning it tips the gaze up",
             aligned - base, shift, 1.5)

print(f"\n{passed} ok, {failed} failed")
sys.exit(1 if failed else 0)
