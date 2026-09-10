#!/usr/bin/env python3
"""Numeric check of the HEAD LEVELLER — `_cmu.level_head`, the import switch
that puts a mis-placed head upright on the neck.

Usage:
    ./.venv/bin/python scripts/smoke_head_level.py

No Blender, no server, no world DB, no clip library: `_cmu` is plain stdlib
and the fixture is a synthetic take built here. Every expectation below is
derived by hand from the rule, never recorded from a run.

WHY THE SWITCH EXISTS
=====================
A generated animation can simply hold the head wrong for the whole take. On
the Meshy AI biped that prompted this, the figure stands upright — feet at
0.20 m, hips 0.66, neck base 1.06 — and the head goes DOWN from there: head
joint 1.02 m, crown 0.89 m, i.e. the crown hangs 17 cm BELOW the neck base.
Measured against the torso axis, the neck-base → crown vector sits at
−107.7 deg where the library's own standing clips sit at −4.4 (walk.fbx).
The retarget passes that on faithfully — a hanging head is what the source
says — so the repair belongs at the import, not in the converter's maths.

THE RULE, WRITTEN OUT
=====================
The MEDIAN sagittal pitch over the kept frames is taken out of EVERY frame,
rigidly, about the body's own medio-lateral axis at that frame:

  * the head chain (`lowerneck`, `upperneck`, `head`) swings about the NECK
    BASE, which stays put;
  * the same constant everywhere, so the head's own motion — nod, turn,
    the frame-to-frame variation — survives untouched;
  * only where the chain POINTS changes, never the relation inside it.

THE FIXTURE, AND THE EXPECTATIONS DERIVED BY HAND
=================================================
A standing figure in centimetres, CMU space (Y up, +X left, +Z forward),
five frames. Pelvis at (0, 100, 0), chest 30 cm above it, hips 10 cm to
either side, so the torso frame is exactly `up = +Y`, `right = -X` (CMU's +X
is the actor's LEFT, so `rfemur - lfemur` points to its right) and
`forward = up × right = +Z` — an anatomical frame, see `_cmu.torso_frame`.

The neck base sits at (0, 145, 0). The head chain is built DROOPING by a
known amount: the crown is placed 100 deg forward of the torso axis, with a
per-frame wobble of −4, −2, 0, +2, +4 deg on top, and the head joint half way
along that same direction. So by construction

    pitch(frame i) = 100 + (2*i - 4)  =  96, 98, 100, 102, 104 deg
    median          = 100 deg

[1] THE MEASUREMENT READS THE FIXTURE BACK. `head_pitch_deg` returns exactly
    those five angles, and the torso frame is the axis-aligned one above.

[2] THE MEDIAN IS WHAT COMES OUT. `level_head` returns −100.0 (the correction
    applied, i.e. minus the median), and afterwards the pitches are
    −4, −2, 0, +2, +4: the median frame stands exactly upright.

[3] THE MOTION SURVIVES. The spread of the pitches is 8 deg before and 8 deg
    after, frame for frame — the switch removes an offset, not the animation.

[4] THE CHAIN STAYS RIGID. The distance from the neck base to the head joint
    and on to the crown is unchanged, and so is the angle at the head joint:
    the head keeps its own relation to the neck, whatever it was.

[5] NOTHING ELSE MOVES. Pelvis, chest, both hips and the arms are identical
    to the cm before and after, and the neck base itself has not moved.

[6] AN UPRIGHT HEAD IS LEFT ALONE. The same fixture built at a median of
    0 deg returns None and is not touched at all.

[7] THE ROTATIONS TRAVEL WITH THE JOINTS. `cmu_clip._solve` orients the rig
    from `rot`, not from the joint positions, so a correction that moved only
    the positions would look right in a measurement and wrong in the clip.
    The turn hidden in the rotations — `rot_after · rot_beforeᵀ` — must
    therefore be the very rotation the positions took: applied to the chain
    direction before, it has to give the chain direction after, to 1e-9.
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app/blender/scripts"))

import _cmu                                             # noqa: E402

TOL = 1e-6          # degrees / cm — plain float arithmetic, no FBX in the way

failures = []


def check(label, got, want, tol=TOL):
    ok = abs(got - want) <= tol
    print(f"  {'ok  ' if ok else 'FAIL'} {label} — {got:+.6f} (expected {want:+.6f} ± {tol})")
    if not ok:
        failures.append(label)


def check_le(label, got, limit):
    ok = got <= limit
    print(f"  {'ok  ' if ok else 'FAIL'} {label} — {got:.6f} (limit {limit})")
    if not ok:
        failures.append(label)


NECK_BASE = (0.0, 145.0, 0.0)
NECK_LEN = 8.0          # neck base → head joint
HEAD_LEN = 14.0         # head joint → crown


def make_pose(pitch_deg):
    """A standing figure whose head chain leans `pitch_deg` out of the spine.

    The chain is built STRAIGHT — head joint and crown on one line — so the
    angle at the head joint is 180 deg and any bend the leveller might add
    would show at once.
    """
    p = _cmu.Pose()
    a = math.radians(pitch_deg)
    # up = +Y, forward = +Z (see the docstring): the chain direction is
    # (0, cos a, sin a).
    d = (0.0, math.cos(a), math.sin(a))
    p.pos["root"] = (0.0, 100.0, 0.0)
    p.pos["thorax"] = (0.0, 130.0, 0.0)
    p.pos["lfemur"] = (10.0, 100.0, 0.0)      # +X is LEFT in CMU space
    p.pos["rfemur"] = (-10.0, 100.0, 0.0)
    p.pos["lhumerus"] = (18.0, 128.0, 0.0)
    p.pos["rhumerus"] = (-18.0, 128.0, 0.0)
    p.pos["lowerneck"] = NECK_BASE
    p.pos["upperneck"] = tuple(NECK_BASE[i] + d[i] * NECK_LEN for i in range(3))
    p.pos["head"] = tuple(NECK_BASE[i] + d[i] * (NECK_LEN + HEAD_LEN) for i in range(3))
    for name in ("lowerneck", "upperneck", "head"):
        # the chain's own rotation: the same lean, about the medio-lateral
        # axis. `right` is -X here, so a POSITIVE pitch is a rotation about
        # -X by `a` (see [7]).
        p.rot[name] = _cmu.axis_angle((-1.0, 0.0, 0.0), a)
    p.rot["root"] = _cmu.identity()
    return p


def pitches(poses):
    return [_cmu.head_pitch_deg(p) for p in poses]


def dist(a, b):
    return math.dist(a, b)


def main() -> int:
    wobble = (-4.0, -2.0, 0.0, 2.0, 4.0)
    poses = [make_pose(100.0 + w) for w in wobble]
    before = [dict(p.pos) for p in poses]
    rot_before = [[list(r) for r in p.rot["upperneck"]] for p in poses]

    print("[1] the measurement reads the fixture back")
    fr = _cmu.torso_frame(poses[0])
    check("torso up · +Y", _cmu.dot(fr[1], (0.0, 1.0, 0.0)), 1.0)
    check("torso right · −X", _cmu.dot(fr[0], (-1.0, 0.0, 0.0)), 1.0)
    check("torso forward · +Z", _cmu.dot(fr[2], (0.0, 0.0, 1.0)), 1.0)
    check("right × up is −forward (anatomical, not a handed basis)",
          _cmu.dot(_cmu.cross(fr[0], fr[1]), fr[2]), -1.0)
    for i, w in enumerate(wobble):
        check(f"pitch of frame {i}", pitches(poses)[i], 100.0 + w)

    print("\n[2] the median is what comes out")
    applied = _cmu.level_head([p for p in poses])
    check("the correction the switch reports", applied, -100.0, 0.005)
    after = pitches(poses)
    for i, w in enumerate(wobble):
        check(f"pitch of frame {i} after", after[i], w, 1e-4)

    print("\n[3] the head's own motion survives")
    check("spread before", max(100.0 + w for w in wobble) - min(100.0 + w for w in wobble), 8.0)
    check("spread after", max(after) - min(after), 8.0, 1e-4)

    print("\n[4] the chain stays rigid")
    worst_len, worst_bend = 0.0, 0.0
    for p in poses:
        worst_len = max(worst_len,
                        abs(dist(p.pos["lowerneck"], p.pos["upperneck"]) - NECK_LEN),
                        abs(dist(p.pos["upperneck"], p.pos["head"]) - HEAD_LEN))
        u = [p.pos["upperneck"][i] - p.pos["lowerneck"][i] for i in range(3)]
        v = [p.pos["head"][i] - p.pos["upperneck"][i] for i in range(3)]
        c = _cmu.dot(_cmu.normalize(u), _cmu.normalize(v))
        worst_bend = max(worst_bend, abs(math.degrees(math.acos(max(-1, min(1, c))))))
    check_le("segment length change (cm)", worst_len, 1e-9)
    check_le("bend introduced at the head joint (deg)", worst_bend, 1e-6)

    print("\n[5] nothing else moves")
    worst = 0.0
    for old, p in zip(before, poses):
        for name in ("root", "thorax", "lfemur", "rfemur", "lhumerus", "rhumerus", "lowerneck"):
            worst = max(worst, dist(old[name], p.pos[name]))
    check_le("largest move of a joint outside the head chain (cm)", worst, 1e-9)

    print("\n[6] an upright head is left alone")
    upright = [make_pose(w) for w in wobble]
    snapshot = [dict(p.pos) for p in upright]
    check("the switch reports nothing to do",
          1.0 if _cmu.level_head(upright) is None else 0.0, 1.0, 0.0)
    worst = 0.0
    for old, p in zip(snapshot, upright):
        for name in old:
            worst = max(worst, dist(old[name], p.pos[name]))
    check_le("largest move (cm)", worst, 1e-9)

    print("\n[7] the rotations travel with the joints")
    worst = 0.0
    for old_rot, old_pos, p in zip(rot_before, before, poses):
        turn = _cmu.mat_mul(p.rot["upperneck"], _cmu.transpose(old_rot))
        was = [old_pos["head"][i] - old_pos["upperneck"][i] for i in range(3)]
        now = [p.pos["head"][i] - p.pos["upperneck"][i] for i in range(3)]
        moved = _cmu.mat_vec(turn, was)
        worst = max(worst, max(abs(moved[i] - now[i]) for i in range(3)))
    check_le("the turn in `rot` against the turn the joints took (cm)", worst, 1e-9)

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): " + ", ".join(failures))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
