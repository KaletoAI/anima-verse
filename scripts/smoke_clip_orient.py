#!/usr/bin/env python3
"""Numeric check of the ORIENTATION of an already imported clip —
`app/blender/scripts/clip_orient.py` and `animation_clips.orient_clip`.

Usage:
    ./.venv/bin/python scripts/smoke_clip_orient.py

Needs Blender (auto-discovered, or image_generation.blender_executable, same
as the other blender smokes) and the reference rig — it rewrites FBX files,
which no pure-Python check can do. No server, no world DB. The clip library
is a TEMP directory (`ANIMATION_CLIPS_DIR`), the fixture clips are BUILT here
from the reference skeleton, and the real `shared/models/clips*` are never
read and never touched.

THE FIXTURE
===========
Three frames on the reference rig, exported through `cmu_clip._export` — the
same file shape a library clip has. The root (`mixamorig:Hips`) carries a
known pose in ARMATURE SPACE (Y up, +Z forward, +X to the actor's left,
centimetres, floor at y = 0):

    frame 1   root (10, 40, 20), rotation Ry(35 deg)
    frame 2   root (12, 40, 23), same rotation
    frame 3   root (14, 40, 26), same rotation

and `mixamorig:LeftArm` is rolled 40 deg off its rest, so the take is a POSE
and not the bare T-pose — a transform that only worked on the rest skeleton
would not be caught. The pair fixture is the same take twice, the B half
shifted +60 cm along X: root_b frame 1 = (70, 40, 20), frame 2 = (72, 40, 23).

THE ROTATION, WRITTEN OUT
=========================
The rule under test (docstring of `clip_orient`), applied rigidly to every
pose about the origin of the clip frame ON THE FLOOR:

    R = Ry(yaw) . Rx(tilt) . Rz(roll)          (roll first, then tilt, then yaw)
    p' = R . p + (0, height_cm, 0)

with Blender's own axis conventions, which are three.js' too:

    Ry(a):  x' =  x cos a + z sin a      y' = y                z' = -x sin a + z cos a
    Rx(a):  x' =  x                      y' = y cos a - z sin a  z' =  y sin a + z cos a
    Rz(a):  x' =  x cos a - y sin a      y' = x sin a + y cos a  z' =  z

This smoke writes those three formulas out by hand instead of calling the
helper, so a flipped sign or a swapped order inside the script cannot pass.

EXPECTATIONS, DERIVED BY HAND FROM (10, 40, 20)
===============================================
cos 10 = 0.98481, sin 10 = 0.17365; cos 20 = 0.93969, sin 20 = 0.34202.

[1] THE FIXTURE IS WHAT THIS DOCSTRING SAYS. Read back out of the written
    file, the root of frame 1 is (10, 40, 20) cm.

[2] YAW 90 IS THE IMPORT DIAL'S TURN.
        x' = 10 . cos 90 + 20 . sin 90 =  20
        z' = -10 . sin 90 + 20 . cos 90 = -10
    -> (20, 40, -10). A turn about the VERTICAL moves no height, so the
    lowest point of the figure is unchanged.

[3] TILT 10 TIPS THE FIGURE FORWARD, about +X.
        y' = 40 . 0.98481 - 20 . 0.17365 = 39.39240 - 3.47300 = 35.91940
        z' = 40 . 0.17365 + 20 . 0.98481 =  6.94600 + 19.69620 = 26.64220
    -> (10, 35.91940, 26.64220). The head of a standing figure leans towards
    +Z, which is forward — the sign the dial promises.

[4] HEIGHT 5 IS A PURE LIFT. -> (10, 45, 20), and the lowest point of the
    figure rises by exactly 5 cm.

[5] THE COMBINATION IS ROLL, THEN TILT, THEN YAW, THEN THE LIFT.
        Rz(20) . (10, 40, 20)
          x = 10 . 0.93969 - 40 . 0.34202 =  9.39690 - 13.68080 = -4.28390
          y = 10 . 0.34202 + 40 . 0.93969 =  3.42020 + 37.58760 = 41.00780
          z = 20
        Rx(10) . (-4.28390, 41.00780, 20)
          y = 41.00780 . 0.98481 - 20 . 0.17365 = 40.38489 - 3.47300 = 36.91189
          z = 41.00780 . 0.17365 + 20 . 0.98481 =  7.12100 + 19.69620 = 26.81720
        Ry(90) . (-4.28390, 36.91189, 26.81720)
          x = -4.28390 . 0 + 26.81720 . 1 = 26.81720
          z =  4.28390 . 1 + 26.81720 . 0 =  4.28390
        + (0, 5, 0)
    -> (26.81720, 41.91189, 4.28390).

[6] THE TAKE MOVES RIGIDLY AND THE FILE CARRIES IT. Every run's own
    verification (`max_pos_dev_cm`, every bone against the arithmetic) stays
    inside its limit, and the WRITTEN files, re-measured in a second Blender
    start, report exactly the root positions of [2]-[5] — the turn is in the
    file, not only in the scene.

[7] THE SIDECAR ADDS UP. A clip whose sidecar already says `yaw_deg: 30` and
    `floor_shift_cm: 2.0`, turned by +90 and lifted by 5 cm, ends at
    `yaw_deg: 120` and `floor_shift_cm: 7.0`; a further -120 leaves 0, and a
    dial at 0 is DROPPED from the sidecar, exactly as the import omits an
    unturned one. Neither `tilt_deg` nor `roll_deg` appears while they are 0.

[8] A PAIR TURNS AS ONE AND IS RE-MEASURED. Both halves go into one run and
    get the same rotation; the sidecar's role geometry is then read off the
    WRITTEN files (`start_xz_m` at frame 1, `anchor_xz_m` at the sidecar's
    `anchor_frame`, here index 1 = frame 2), in metres:
        A frame 1 (10, 20) -> yaw 90 -> ( 20, -10) cm = ( 0.200, -0.100) m
        B frame 1 (70, 20) -> yaw 90 -> ( 20, -70) cm = ( 0.200, -0.700) m
        A frame 2 (12, 23) -> yaw 90 -> ( 23, -12) cm = ( 0.230, -0.120) m
        B frame 2 (72, 23) -> yaw 90 -> ( 23, -72) cm = ( 0.230, -0.720) m
        root_distance_m = |(0.230, -0.120) - (0.230, -0.720)| = 0.600
    The stale numbers the fixture sidecar carries (9.99) are gone.

[9] ALL DIALS AT 0 IS A NO-OP: no Blender start, the file's bytes unchanged.
"""
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FREE = Path(tempfile.mkdtemp(prefix="clip-orient-free-"))
LICENSED = Path(tempfile.mkdtemp(prefix="clip-orient-licensed-"))
WORLD = Path(tempfile.mkdtemp(prefix="clip-orient-world-"))
WORK = Path(tempfile.mkdtemp(prefix="clip-orient-work-"))
# MUST be set before paths is imported — otherwise the smoke would edit the
# repo's real clip libraries.
os.environ["ANIMATION_CLIPS_DIR"] = str(FREE)
os.environ["ANIMATION_CLIPS_LICENSED_DIR"] = str(LICENSED)

from app.blender import runner                              # noqa: E402
from app.core import paths                                  # noqa: E402

paths.init(WORLD)

from app.core import animation_clips as ac                  # noqa: E402

FAILURES = []

#: Position limit, cm. Every number below goes through an FBX write and read
#: (float32 bone maths), and the hand-derived expectations use five-digit
#: trigonometry — 0.01 cm is 0.1 mm on a 1.70 m figure, two orders above both
#: and far below anything a wrong axis or sign could hide in.
TOL_CM = 0.01
#: Metre limit for the sidecar numbers, which the core rounds to 3 decimals.
TOL_M = 0.001

SCRIPTS = Path(__file__).resolve().parents[1] / "app/blender/scripts"

PROBE = r'''
import json, math, sys
sys.path.insert(0, {scripts!r})
import bpy
import cmu_clip
from mathutils import Matrix, Vector

RIG = {rig!r}
OUT = {out!r}
PREFIX = cmu_clip.PREFIX
ROOT = PREFIX + "Hips"
ARM = PREFIX + "LeftArm"
NF = 3


def key(action, path, index, frame, value):
    fc = action.fcurves.find(path, index=index)
    if fc is None:
        fc = action.fcurves.new(data_path=path, index=index)
    fc.keyframe_points.insert(float(frame), value, options={{"FAST"}})
    fc.update()


def build(name, dx):
    arm = cmu_clip._load_rig(RIG)
    rest = {{b.name: b.matrix_local.copy() for b in arm.data.bones}}
    action = bpy.data.actions.new(name="Armature|fixture")
    arm.animation_data_create()
    arm.animation_data.action = action
    for f in range(1, NF + 1):
        M = Matrix.Rotation(math.radians(35.0), 3, "Y").to_4x4()
        M.translation = Vector((10.0 + 2 * (f - 1) + dx, 40.0, 20.0 + 3 * (f - 1)))
        basis = rest[ROOT].inverted() @ M
        q = basis.to_quaternion()
        t = basis.to_translation()
        for i, v in enumerate((q.w, q.x, q.y, q.z)):
            key(action, 'pose.bones["%s"].rotation_quaternion' % ROOT, i, f, v)
        for i, v in enumerate((t.x, t.y, t.z)):
            key(action, 'pose.bones["%s"].location' % ROOT, i, f, v)
    qa = Matrix.Rotation(math.radians(40.0), 3, "Z").to_quaternion()
    for f in range(1, NF + 1):
        for i, v in enumerate((qa.w, qa.x, qa.y, qa.z)):
            key(action, 'pose.bones["%s"].rotation_quaternion' % ARM, i, f, v)
    for pb in arm.pose.bones:
        pb.rotation_mode = "QUATERNION"
    scene = bpy.context.scene
    scene.render.fps = 30
    scene.frame_start, scene.frame_end = 1, NF
    cmu_clip.DRIVEN.clear()
    cmu_clip.DRIVEN.update({{"Hips", "LeftArm"}})
    cmu_clip._export(arm, "%s/%s.fbx" % (OUT, name))


for nm, off in (("solo", 0.0), ("pair__a", 0.0), ("pair__b", 60.0)):
    build(nm, off)
print("SMOKE_JSON " + json.dumps({{"built": True}}))
'''


def check(label, got, want, tol=TOL_CM):
    ok = abs(got - want) <= tol
    print(f"  {'ok  ' if ok else 'FAIL'} {label} — {got:+.5f} (expected {want:+.5f} ± {tol})")
    if not ok:
        FAILURES.append(label)


def check_true(label, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


def check_le(label, got, limit):
    ok = got <= limit
    print(f"  {'ok  ' if ok else 'FAIL'} {label} — {got:.6f} (limit {limit})")
    if not ok:
        FAILURES.append(label)


def check_xyz(label, got, want, tol=TOL_CM):
    for axis, g, w in zip("xyz", got, want):
        check(f"{label} {axis}", g, w, tol)


# ── the rotation, written out by hand (never the helper under test) ──────

def ry(p, deg):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return [p[0] * c + p[2] * s, p[1], -p[0] * s + p[2] * c]


def rx(p, deg):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return [p[0], p[1] * c - p[2] * s, p[1] * s + p[2] * c]


def rz(p, deg):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return [p[0] * c - p[1] * s, p[0] * s + p[1] * c, p[2]]


def orient(p, yaw=0.0, tilt=0.0, roll=0.0, height=0.0):
    """R . p + (0, height, 0) — roll first, then tilt, then yaw."""
    q = ry(rx(rz(p, roll), tilt), yaw)
    return [q[0], q[1] + height, q[2]]


def build_fixture(rig: Path) -> bool:
    probe = WORK / "probe.py"
    probe.write_text(PROBE.format(scripts=str(SCRIPTS), rig=str(rig), out=str(WORK)))
    res = subprocess.run([runner.find_executable(), "-b", "--factory-startup",
                          "--python", str(probe)],
                         capture_output=True, text=True, timeout=900)
    if not any(ln.startswith("SMOKE_JSON ") for ln in res.stdout.splitlines()):
        print(res.stdout[-3000:])
        print(res.stderr[-3000:])
        return False
    return all((WORK / f"{n}.fbx").is_file() for n in ("solo", "pair__a", "pair__b"))


def turn(src: Path, out: Path, **dials) -> dict:
    """One clip_orient run over one file; returns its per-slot data."""
    out.mkdir(parents=True, exist_ok=True)
    res = runner.run("clip_orient", inputs={"rig": paths.get_rig_file(), "src": src},
                     params=dials, out_dir=out, timeout_s=900)
    if not res["ok"]:
        check_true(f"run {dials}", False, str(res.get("error")))
        return {}
    written = Path((res.get("outputs") or {}).get("src") or "")
    data = (res["data"].get("clips") or {}).get("src") or {}
    data["_written"] = written
    return data


def main() -> int:
    exe = runner.find_executable()
    if not exe:
        print("Blender not found — nothing was checked")
        return 1
    rig = paths.get_rig_file()
    if not rig.is_file():
        print(f"the reference rig is missing ({rig}) — nothing was checked")
        return 1
    print(f"Blender {runner.version(exe)} — building the fixture from {rig.name}")
    if not build_fixture(rig):
        print("the fixture could not be built — nothing was checked")
        return 1

    base = [10.0, 40.0, 20.0]
    runs = {
        "yaw 90": {"yaw_deg": 90.0},
        "tilt 10": {"tilt_deg": 10.0},
        "height 5": {"height_cm": 5.0},
        "yaw 90 / tilt 10 / roll 20 / height 5":
            {"yaw_deg": 90.0, "tilt_deg": 10.0, "roll_deg": 20.0, "height_cm": 5.0},
    }
    print("\n[1] the fixture is what the docstring says")
    first = turn(WORK / "solo.fbx", WORK / "out-probe", dry_run=True)
    check_xyz("root of frame 1, read back out of the file",
              first.get("root_before") or [0, 0, 0], base)

    results = {}
    for i, (label, dials) in enumerate(runs.items()):
        print(f"\n[{i + 2}] {label}")
        d = turn(WORK / "solo.fbx", WORK / f"out-{i}", **dials)
        results[label] = d
        if not d:
            continue
        want = orient(base, dials.get("yaw_deg", 0.0), dials.get("tilt_deg", 0.0),
                      dials.get("roll_deg", 0.0), dials.get("height_cm", 0.0))
        check_xyz("root of frame 1 after the turn", d["root_after"], want)
        if not (dials.get("tilt_deg") or dials.get("roll_deg")):
            # A turn about the VERTICAL moves no height, and a lift moves every
            # height by exactly itself — so the lowest point of the figure is
            # the one number that follows from the dials alone. A tilt or roll
            # swings the body and is not predictable without the whole mesh.
            check("lowest point of the figure", d["floor_min_cm_after"],
                  d["floor_min_cm_before"] + dials.get("height_cm", 0.0), 0.02)
        check_le("the take moved rigidly (every bone, cm)",
                 d["verify"]["max_pos_dev_cm"], TOL_CM)
        check_true("the run declared a file", d["_written"].is_file())

    print("\n[6] the WRITTEN files carry the turn (a second Blender start)")
    inputs = {"rig": paths.get_rig_file()}
    slots = {}
    for i, label in enumerate(runs):
        w = results.get(label, {}).get("_written")
        if w and w.is_file():
            slots[f"src_{i}"] = label
            inputs[f"src_{i}"] = w
    res = runner.run("clip_orient", inputs=inputs, params={"dry_run": True}, timeout_s=900)
    if not res["ok"]:
        check_true("re-measuring the written files", False, str(res.get("error")))
    else:
        for slot, label in slots.items():
            got = ((res["data"].get("clips") or {}).get(slot) or {}).get("root_before")
            check_xyz(f"{label}: the file's own root of frame 1",
                      got or [0, 0, 0], results[label]["root_after"])

    print("\n[7] the sidecar adds up (orient_clip, temp library)")
    shutil.copy2(WORK / "solo.fbx", FREE / "turn.fbx")
    (FREE / "turn.json").write_text(json.dumps({
        "kind": "turn", "pair": False, "roles": [], "fps": 30, "frames": 3,
        "duration_s": 0.1, "loop": False,
        "geometry": {"floor_shift_cm": 2.0, "in_place": True, "yaw_deg": 30.0},
    }, indent=1), encoding="utf-8")
    ac.orient_clip("free", "turn.fbx", yaw_deg=90.0, height_cm=5.0)
    geo = json.loads((FREE / "turn.json").read_text(encoding="utf-8"))["geometry"]
    check("yaw_deg accumulated (30 + 90)", float(geo.get("yaw_deg", 0.0)), 120.0, 0.05)
    check("floor_shift_cm shifted (2.0 + 5)", float(geo.get("floor_shift_cm", 0.0)), 7.0, 0.005)
    check_true("no tilt_deg / roll_deg while both are 0",
               "tilt_deg" not in geo and "roll_deg" not in geo, str(sorted(geo)))
    ac.orient_clip("free", "turn.fbx", yaw_deg=-120.0)
    geo = json.loads((FREE / "turn.json").read_text(encoding="utf-8"))["geometry"]
    check_true("a dial back at 0 is dropped from the sidecar",
               "yaw_deg" not in geo, str(sorted(geo)))
    check("floor_shift_cm untouched by a pure turn",
          float(geo.get("floor_shift_cm", 0.0)), 7.0, 0.005)

    print("\n[8] a pair turns as one and is re-measured")
    for role in ("a", "b"):
        shutil.copy2(WORK / f"pair__{role}.fbx", FREE / f"pair__{role}.fbx")
    (FREE / "pair.json").write_text(json.dumps({
        "kind": "pair", "pair": True, "roles": ["a", "b"], "fps": 30, "frames": 3,
        "duration_s": 0.1, "loop": True,
        "geometry": {"anchor_frame": 1, "anchor_s": 0.033, "root_distance_m": 9.99,
                     "floor_shift_cm": 0.0,
                     "roles": {"a": {"start_xz_m": [9.99, 9.99], "anchor_xz_m": [9.99, 9.99]},
                               "b": {"start_xz_m": [9.99, 9.99], "anchor_xz_m": [9.99, 9.99]}}},
    }, indent=1), encoding="utf-8")
    before = {r: (FREE / f"pair__{r}.fbx").read_bytes() for r in ("a", "b")}
    views = ac.orient_clip("free", "pair__a.fbx", yaw_deg=90.0)
    check_true("both halves were rewritten in one call",
               len(views) == 2 and all((FREE / f"pair__{r}.fbx").read_bytes() != before[r]
                                       for r in ("a", "b")),
               str(sorted(v["filename"] for v in views)))
    geo = json.loads((FREE / "pair.json").read_text(encoding="utf-8"))["geometry"]
    roles = geo.get("roles") or {}
    want = {("a", "start_xz_m"): [0.200, -0.100], ("b", "start_xz_m"): [0.200, -0.700],
            ("a", "anchor_xz_m"): [0.230, -0.120], ("b", "anchor_xz_m"): [0.230, -0.720]}
    for (role, field), w in want.items():
        got = (roles.get(role) or {}).get(field) or [0.0, 0.0]
        check(f"{role}.{field} x", got[0], w[0], TOL_M)
        check(f"{role}.{field} z", got[1], w[1], TOL_M)
    check("root_distance_m re-measured", float(geo.get("root_distance_m", 0.0)), 0.600, TOL_M)

    print("\n[9] all dials at 0 is a no-op")
    was = (FREE / "turn.fbx").read_bytes()
    ac.orient_clip("free", "turn.fbx")
    check_true("the file is untouched", (FREE / "turn.fbx").read_bytes() == was)

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s): " + ", ".join(FAILURES))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        for d in (FREE, LICENSED, WORLD, WORK):
            shutil.rmtree(d, ignore_errors=True)
