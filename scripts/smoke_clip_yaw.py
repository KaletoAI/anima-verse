#!/usr/bin/env python3
"""Numeric check of the IMPORT ORIENTATION DIAL — `yaw_deg` in
`app/blender/scripts/cmu_clip.py._frame_takes`.

Usage:
    ./.venv/bin/python scripts/smoke_clip_yaw.py

Needs Blender (auto-discovered, or image_generation.blender_executable, same
as the other blender smokes) because `_apply_rigid` builds its rotation with
mathutils. No server, no world DB, no clip library, no mocap source: the
fixture is a synthetic take built here, and every expectation below is derived
by hand from the frame-of-reference rules, not recorded from a previous run.

WHY THE DIAL EXISTS
===================
The import normalises a SOLO take so the ROOT's forward axis points +Z at the
first kept frame. For an upright actor that is the body's facing. For an actor
who is already LYING it is the direction the belly faces, and the body's long
axis lands wherever it happens to — measured over the shipped lying clips:
+8 deg (laying), +70 (sleeping-side), +90 (getting-up-side), +178
(sleeping-back). There is no convention to fall back on, so the angle is
dialled by eye in the import preview and baked here.

THE FIXTURE
===========
Three frames, in centimetres, CMU space (Y up, +X left, +Z forward). Every
frame carries the SAME root rotation Ry(35 deg), so the root's forward axis is
(sin 35, 0, cos 35) throughout; the joints travel (+2, 0, +3) cm per frame and
the third frame rises 1 cm:

    frame 0   root (10, 40, 20)  spine (10, 60, 20)  head (10, 90, 20)
              lfoot (20,  5, 20) rfoot ( 0,  5, 20)
    frame 1   every joint +(2, 0, 3)
    frame 2   every joint +(4, 1, 6)

The floor is the lowest joint over the whole take: y = 5 (frames 0 and 1).

THE ROTATION, WRITTEN OUT
=========================
Ry(a) is the right-handed turn about the vertical that both Blender's
`Matrix.Rotation(a, 3, "Y")` and three.js' `rotation.y = a` apply — the
preview and the bake therefore agree on the sign of the dial:

    x' = x cos a + z sin a          +Z --a=90--> +X
    z' = -x sin a + z cos a         +X --a=90--> -Z

This smoke writes that formula out itself instead of calling the helper, so a
flipped sign inside `_frame_takes` cannot pass.

EXPECTATIONS, DERIVED BY HAND
=============================
[1] WITHOUT A DIAL THE OLD RULE STANDS. yaw_deg = 0 turns the take by -35 deg,
    so the root's forward axis is exactly +Z: forward_xz(frame 0) = (0, 1).
    The root sits at the XZ origin in frame 0, and the take is lifted by the
    floor, so the lowest joint of the whole take is y = 0.

[2] THE DIAL IS THAT ROTATION, EXACTLY. With yaw_deg = a the root's forward
    axis is (sin a, cos a), and since both variants put frame 0's root on the
    XZ origin, the whole take is the yaw-0 take turned about that origin:
    every joint position and every joint rotation of the yaw-a run equals
    Ry(a) applied to the yaw-0 run. Checked for a = 90 and a = 143.

[3] THE DIAL IS ADDITIVE. Ry(90) applied to the yaw-90 run equals the yaw-180
    run, joint for joint — the angle is one rotation, not a special case per
    quadrant.

[4] THE DIAL TOUCHES NOTHING ELSE. Heights are untouched (y identical in every
    run), the take stays rigid (the head-to-foot distance is the same in every
    frame of every run), and root_motion `strip` still pins the root's XZ at
    the origin in EVERY frame, not just the first.

[5] A PAIR TURNS WITH IT. A pair is framed by its own rule — the A->B
    direction at the anchor frame falls on +X — and the dial turns that frame
    further: A->B lands on Ry(a) . (+X) = (cos a, 0, -sin a). Checked for
    a = 0 and a = 90, with the anchor left to the automatic search (the frame
    where the two roots are closest, which the fixture puts at frame 1).
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.blender import runner            # noqa: E402

TOL = 1e-6          # unit vector components — pure arithmetic, no FBX
#: Position limit, cm. The frame of reference is built with mathutils, whose
#: matrices carry single-precision floats, so a 100 cm figure turned about the
#: origin lands within ~1e-6 cm of the analytic result. 1e-4 cm is one micron —
#: five orders below anything a renderer could show, and still tight enough to
#: catch a wrong angle, a wrong axis or a wrong sign by many orders.
TOL_CM = 1e-4

PROBE = r'''
import json, math, sys
sys.path.insert(0, {scripts!r})
import bpy                                     # noqa: F401  (mathutils needs it)
import _cmu
import cmu_clip

JOINTS = ["root", "spine", "head", "lfoot", "rfoot"]
BASE = {{"root": (10.0, 40.0, 20.0), "spine": (10.0, 60.0, 20.0),
        "head": (10.0, 90.0, 20.0), "lfoot": (20.0, 5.0, 20.0),
        "rfoot": (0.0, 5.0, 20.0)}}
STEP = [(0.0, 0.0, 0.0), (2.0, 0.0, 3.0), (4.0, 1.0, 6.0)]
YAW0 = 35.0


def ry(deg):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return [[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]]


class Pose:
    """Duck-typed `_cmu.Pose`: the bone ends coincide with the joints, which
    is all `lowest_point_cm` needs."""

    def __init__(self, rot, pos):
        self.rot, self.pos = rot, pos

    def end(self, sk, name):
        return self.pos[name]


class Take:
    def __init__(self, poses, role=""):
        self.poses, self.role, self.sk = poses, role, None

    def root_xz(self, i):
        p = self.poses[i].pos["root"]
        return (p[0], p[2])

    def lowest(self):
        return min(_cmu.lowest_point_cm(self.sk, p) for p in self.poses)


def make_take(offset=(0.0, 0.0, 0.0), role="", yaw=YAW0):
    poses = []
    for dx, dy, dz in STEP:
        pos = {{n: (BASE[n][0] + dx + offset[0], BASE[n][1] + dy + offset[1],
                   BASE[n][2] + dz + offset[2]) for n in JOINTS}}
        rot = {{n: ry(yaw) for n in JOINTS}}
        poses.append(Pose(rot, pos))
    return Take(poses, role)


def frame_solo(yaw_deg, root_motion="strip"):
    take = make_take()
    geo = cmu_clip._frame_takes([take], {{"root_motion": root_motion, "yaw_deg": yaw_deg}})
    fx, fz = _cmu.forward_xz(take.poses[0])
    return {{
        "geometry": geo,
        "forward": [fx, fz],
        "frames": [{{n: list(p.pos[n]) for n in JOINTS}} for p in take.poses],
        "rot0": [list(r) for r in take.poses[0].rot["root"]],
    }}


def frame_pair(yaw_deg):
    # B stands 60 cm to the actor's -X at the closest moment (frame 1).
    a = make_take(role="a")
    b = make_take(offset=(-60.0, 0.0, 40.0), role="b")
    b.poses[1].pos = {{n: (v[0] + 20.0, v[1], v[2] - 40.0)
                      for n, v in b.poses[1].pos.items()}}
    geo = cmu_clip._frame_takes([a, b], {{"fps": 30, "yaw_deg": yaw_deg}})
    ai = geo["anchor_frame"]
    ax, az = a.root_xz(ai)
    bx, bz = b.root_xz(ai)
    d = math.hypot(bx - ax, bz - az) or 1.0
    return {{"anchor_frame": ai, "ab_unit": [(bx - ax) / d, (bz - az) / d],
            "geometry": geo}}


out = {{
    "solo": {{str(a): frame_solo(a) for a in (0.0, 90.0, 143.0, 180.0)}},
    "solo_free": frame_solo(90.0, root_motion="keep"),
    "solo_free0": frame_solo(0.0, root_motion="keep"),
    "pair": {{str(a): frame_pair(a) for a in (0.0, 90.0)}},
}}
print("SMOKE_JSON " + json.dumps(out))
'''

failures = []


def check(label, got, want, tol=TOL):
    ok = abs(got - want) <= tol
    print(f"  {'ok  ' if ok else 'FAIL'} {label} — {got:+.9f} (expected {want:+.9f} ± {tol})")
    if not ok:
        failures.append(label)


def check_le(label, got, limit):
    ok = got <= limit
    print(f"  {'ok  ' if ok else 'FAIL'} {label} — {got:.9f} (limit {limit})")
    if not ok:
        failures.append(label)


def rotate(p, deg):
    """Ry(deg) applied to a point — the formula written out in the docstring."""
    import math
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return [p[0] * c + p[2] * s, p[1], -p[0] * s + p[2] * c]


def max_dev(frames_a, frames_b, deg):
    """Largest deviation between run A turned by `deg` and run B, in cm."""
    worst = 0.0
    for fa, fb in zip(frames_a, frames_b):
        for name, pa in fa.items():
            want = rotate(pa, deg)
            got = fb[name]
            worst = max(worst, max(abs(want[i] - got[i]) for i in range(3)))
    return worst


def main() -> int:
    import math
    exe = runner.find_executable()
    if not exe:
        print("Blender not found — nothing was checked")
        return 1
    with tempfile.TemporaryDirectory(prefix="smoke-clip-yaw-") as tmp:
        probe = Path(tmp) / "probe.py"
        probe.write_text(PROBE.format(
            scripts=str(Path(__file__).resolve().parents[1] / "app/blender/scripts")))
        res = subprocess.run([exe, "-b", "--factory-startup", "--python", str(probe)],
                             capture_output=True, text=True, timeout=600)
    line = next((ln for ln in res.stdout.splitlines() if ln.startswith("SMOKE_JSON ")), "")
    if not line:
        print(res.stdout[-3000:])
        print(res.stderr[-3000:])
        print("the probe produced no result")
        return 1
    d = json.loads(line[len("SMOKE_JSON "):])
    solo = d["solo"]

    print("[1] without a dial the old rule stands: the root faces +Z")
    check("forward x (yaw 0)", solo["0.0"]["forward"][0], 0.0)
    check("forward z (yaw 0)", solo["0.0"]["forward"][1], 1.0)
    check("root x, frame 0", solo["0.0"]["frames"][0]["root"][0], 0.0)
    check("root z, frame 0", solo["0.0"]["frames"][0]["root"][2], 0.0)
    lowest = min(p[1] for f in solo["0.0"]["frames"] for p in f.values())
    check("lowest joint of the take", lowest, 0.0)
    check("floor shift written to the sidecar (cm)",
          solo["0.0"]["geometry"]["floor_shift_cm"], -5.0)

    print("\n[2] the dial IS that rotation — forward = (sin a, cos a), "
          "the take = Ry(a) . (the yaw-0 take)")
    for a in (90.0, 143.0):
        run = solo[str(a)]
        check(f"forward x (yaw {a:g})", run["forward"][0], math.sin(math.radians(a)))
        check(f"forward z (yaw {a:g})", run["forward"][1], math.cos(math.radians(a)))
        check_le(f"joint deviation from Ry({a:g}) . yaw-0 (cm)",
                 max_dev([f for f in solo["0.0"]["frames"]], run["frames"], a), TOL_CM)
        check(f"sidecar records the dial (yaw {a:g})",
              float(run["geometry"].get("yaw_deg", 0.0)), a, 0.051)
    check("no yaw_deg in the sidecar without a dial",
          1.0 if "yaw_deg" not in solo["0.0"]["geometry"] else 0.0, 1.0, 0.0)

    print("\n[3] the dial is additive: Ry(90) . (yaw 90) == yaw 180")
    check_le("joint deviation (cm)",
             max_dev(solo["90.0"]["frames"], solo["180.0"]["frames"], 90.0), TOL_CM)

    print("\n[4] the dial touches nothing else")
    worst_y = 0.0
    for a in ("90.0", "143.0", "180.0"):
        for f0, fa in zip(solo["0.0"]["frames"], solo[str(a)]["frames"]):
            for name in f0:
                worst_y = max(worst_y, abs(f0[name][1] - fa[name][1]))
    check_le("height change over every run (cm)", worst_y, TOL_CM)
    worst_rigid = 0.0
    for a in ("0.0", "90.0", "143.0", "180.0"):
        for f in solo[a]["frames"]:
            dist = math.dist(f["head"], f["lfoot"])
            worst_rigid = max(worst_rigid, abs(dist - math.dist(
                solo["0.0"]["frames"][0]["head"], solo["0.0"]["frames"][0]["lfoot"])))
    check_le("head-to-foot distance change (cm)", worst_rigid, TOL_CM)
    worst_pin = 0.0
    for a in ("0.0", "90.0", "143.0", "180.0"):
        for f in solo[a]["frames"]:
            worst_pin = max(worst_pin, abs(f["root"][0]), abs(f["root"][2]))
    check_le("strip: root XZ off the origin, any frame (cm)", worst_pin, TOL_CM)
    # …and with keep the travel survives, turned by the dial.
    check_le("free root travel follows the dial (cm)",
             max_dev(d["solo_free0"]["frames"], d["solo_free"]["frames"], 90.0), TOL_CM)
    # …and there WAS travel to follow: the fixture moves the root (4, 1, 6) cm
    # over three frames, so its last frame is 7.2 cm off the origin.
    last = d["solo_free0"]["frames"][2]["root"]
    check("free root travel, last frame (cm)", math.hypot(last[0], last[2]),
          math.hypot(4.0, 6.0), TOL_CM)

    print("\n[5] a pair turns with it: A->B lands on Ry(a) . (+X)")
    for a in (0.0, 90.0):
        pair = d["pair"][str(a)]
        ux, uz = pair["ab_unit"]
        check(f"A->B x (yaw {a:g})", ux, math.cos(math.radians(a)))
        check(f"A->B z (yaw {a:g})", uz, -math.sin(math.radians(a)))
    check("the anchor is the frame where the roots are closest",
          float(d["pair"]["0.0"]["anchor_frame"]), 1.0, 0.0)

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): " + ", ".join(failures))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
