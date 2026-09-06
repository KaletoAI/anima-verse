#!/usr/bin/env python3
"""Numeric check of the PALM AXIS a fingerless rig gets from its own skin —
`_palm_axes` / `_hand_direction` / `_synth_hand_targets` in
`app/blender/scripts/fbx_clip.py`, and the palm table's route through `run`.

Usage:
    ./.venv/bin/python scripts/smoke_palm_axes.py [REST_FBX ...]

Needs Blender (auto-discovered, or image_generation.blender_executable, same as
the other blender smokes). No server, no world DB, no clip library.

THE RIG FILES ARE LOCAL, THE CHECKS ARE NOT. Sections [1]-[5] measure two
skinned rest rigs from `shared/models/clips-inbox/`, which is user-provided
material that is NOT in the repository:

    MotusMan_v55.fbx                                   (mixamo-noprefix, HAS
                                                        finger bones)
    Meshy_AI_The_Young_Adventurer_biped/..._Character_output.fbx
                                                       (meshy-biped, has NONE)

Pass other rest FBXs as arguments to measure those instead. When a file is
absent its section is skipped with a line saying so, and the run still checks
[6] and [7], which need no file at all. A skip is not a pass and says so.

WHAT IS BEING PINNED
====================
A bone's roll comes from its secondary axis, and for the forearm and the hand
that axis is the palm: "pinky knuckle to index knuckle". A rig with no finger
joints has no knuckles, so `_palm_axes` measures the axis off the SKINNED HAND
MESH in the rest file — the hand is a flat slab, its thinnest direction is the
palm normal, and the palm axis is perpendicular to that and to the hand — and
`_synth_hand_targets` plants two knuckles along it on every animation frame.

The rig that HAS knuckles is what makes this checkable: its Index1 and Pinky1
bone heads ARE the answer, so the same measurement, run on it, can be held
against the truth. That is where every expected number below comes from — the
rig's own bones, not a recorded output.

THE EXPECTATIONS, DERIVED BY HAND
=================================
[1] ONE SPACE, NOT TWO. The vertices arrive in Blender's WORLD space, the bone
    matrices are ARMATURE space, and the FBX importer puts the Y-up -> Z-up
    conversion (rot X 90 deg) plus the unit scale on the ARMATURE OBJECT. The
    scale and the wrong-space wrist fall out of a covariance fit; the 90 deg
    does not. So on MotusMan, whose armature carries the full rotation:

        palm normal, vertices read in world space :  80.6 / 81.8 deg off truth
        palm normal, vertices read in armature space: 10.2 / 10.0 deg off

    where "truth" is the normal of the plane through the real hand — the
    wrist->middle-root direction crossed with the real knuckle line. The check
    is >= 45 deg for the first and <= 15 deg for the second. The residual 10
    deg is the fit's own: 265 and 275 vertices of palm, and a palm is only
    approximately flat.

    On the Meshy rig the importer left the conversion on the MESH and the
    armature is rotation-free, so both routes agree there to 0.0 deg — which is
    why the defect could live in the code that was written for that rig.

[2] AND THE AXIS THEN LANDS ON THE KNUCKLE LINE. Same rig, the returned axis
    against Index1 - Pinky1: 15.9 deg (left) and 15.0 deg (right); the check is
    <= 20 deg. It cannot be tighter than [1] is: the axis is the normal turned
    90 deg, so the plane's 10 deg is in it, plus the hand's own direction.
    Before the space fix the same measurement gave 107.6 / 102.5 deg — a palm
    on edge — so the bar sits far below the defect and above the fit.

    The hand's direction is the middle-finger root where the rig has one and
    the bone's local Y otherwise. Both are needed: MotusMan's imported hand
    bones point straight DOWN (84.0 / 96.0 deg away from the hand), and the
    Meshy rig has no finger root to ask.

[3] THE TWO HANDS ARE MIRROR IMAGES. Carried to armature space and reflected
    through the sagittal plane (the shoulder line is its normal), the left axis
    must point where the right one does: dot +1.000 on both rigs (measured
    +0.9996 and +0.9999), checked as >= 0.99. This is the check that the sign
    was decided at all, and `_palm_axes` raises when it fails.

[4] WHICH IS WHY THE SHOULDER LINE CANNOT DECIDE THE SIGN. Mirror images have
    OPPOSITE components along the shoulder line, so a rule that sends both
    hands to the same side of it must turn exactly one of them over. Measured
    dot of the correct axes with the shoulder line:

        MotusMan  +0.039 / -0.042      (89 / 92 deg — no signal at all)
        Meshy     -0.355 / +0.363      (111 / 69 deg — a signal, opposite)

    Checked as: the two hands disagree in SIGN on every rig, and |cos| stays
    below 0.5 on both. The old rule read the Meshy pair's 69/69 deg as
    agreement, having already flipped one of them to get it.

[5] THE THUMB DECIDES IT INSTEAD. The thumb hangs off the index side and
    reaches further from the wrist than the little finger's edge does, so the
    side the hand stands off further on is the index side. Read at the
    5th/95th percentile of the projection, as (near + far) / width:

        MotusMan  -0.144 / -0.131      Meshy  -0.178 / -0.172

    all four the same sign as their rig's knuckle line where there is one;
    checked as |value| >= 0.03 (the floor `_palm_axes` refuses below). The run
    reports them positive: it reads them back off the axis the sign already
    turned, which is the point. The reach is read on the hand AND its finger
    bones, the plane on the hand bone alone: MotusMan's palm-only cloud has had
    the thumb cut out of it and then decides nothing — its mean sits 0.033 to
    the PINKY side and its reach 0.02 off centre, and it is the digits that put
    both hands right.

[6] THE KNUCKLES ARE GATED ON THE KNUCKLES. `_synth_hand_targets` plants a
    middle root when the middle root is missing and the two knuckles when the
    KNUCKLES are missing — one absence does not imply the other. Fixture, in
    clip space (cm, Y up), hand node matrix identity:

        lradius (45,150,0)   lhand (70,150,0)   LeftHandMiddle1 (78,150,0)
        palm axis (0,0,1) in the hand's local frame

        reach = |lhand - lradius| / 3 = 25/3 = 8.3333
        _blender_to_clip((0,0,1)) = (0,100,0) -> the knuckles part along +Y
        Index1 = lhand + (0,1,0)*reach/2 = (70, 154.1667, 0)
        Pinky1 = lhand - (0,1,0)*reach/2 = (70, 145.8333, 0)

    with the middle root ALREADY THERE — which is the case that used to leave
    the forearm's roll on the shoulder line. Two more: with the middle root
    absent it is planted along the node's own Y,
    _blender_to_clip((0,1,0)) = (0,0,-100), so (70,150,-8.3333); and a hand
    that brings its own knuckles keeps them untouched.

[7] A PAIR MEASURES BOTH HALVES. `run` hands the SAME palm table to every
    source — the rest file's, or None — and never rebinds it from what a source
    returned. Half A of a pair is an animation export with no mesh, so it
    answers {}, and {} is not None: passed on to half B it reads as "already
    measured" and half B, a different body, never measures itself. Checked by
    recording the argument `_load_source` is called with:

        pair + rest file  ->  [rest table, rest table]
        pair, no rest     ->  [None, None]
        solo, no rest     ->  [None]

WHAT THIS DOES NOT PROMISE
==========================
That the sign survives a hand modelled with the thumb tucked into a fist,
where the reach that decides it is gone. Both hands of such a rig would fail
the same way, so the mirror check in [3] would not catch it either — the floor
in [5] is the only guard, and it is a floor on the measurement, not on the
anatomy.
"""
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.blender import runner            # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RIGS = [
    ROOT / "shared/models/clips-inbox/MotusMan_v55.fbx",
    ROOT / ("shared/models/clips-inbox/Meshy_AI_The_Young_Adventurer_biped/"
            "Meshy_AI_The_Young_Adventurer_biped_Character_output.fbx"),
]

PROBE = r'''
import json, math, sys
sys.path.insert(0, {scripts!r})
import bpy
from mathutils import Matrix, Vector
import fbx_clip
import cmu_clip

out = {{"rigs": [], "unit": {{}}}}


def measure(path):
    r = {{"file": path}}
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=path, global_scale=1.0)
    family = fbx_clip._detect_family(set(fbx_clip._scene_nodes()))
    bone_map = fbx_clip.BONE_MAPS[family]()
    src_of = {{i: s for s, i in bone_map.items()}}
    r["family"] = family
    arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    if not arms or not meshes:
        r["error"] = "no skinned armature in this file"
        return r
    arm, bones = arms[0], arms[0].data.bones
    axes = fbx_clip._palm_axes(bone_map)
    lat = (bones[src_of["lhumerus"]].matrix_local.translation
           - bones[src_of["rhumerus"]].matrix_local.translation).normalized()
    to_arm = arm.matrix_world.inverted()
    in_arm = {{}}
    r["hands"] = {{}}
    for inter, axis in axes.items():
        side = "Left" if inter == "lhand" else "Right"
        name = src_of[inter]
        bone = bones[name]
        rest = bone.matrix_local.to_3x3()
        inv = rest.inverted()
        head = bone.matrix_local.translation
        in_arm[inter] = (rest @ axis).normalized()
        h = {{"dot_shoulders": in_arm[inter].dot(lat)}}
        # the two clouds again, to report the fit's own inputs
        digits = {{name}} | {{c.name for c in bone.children_recursive}}
        palm_w, palm_a, whole = [], [], []
        for ob in meshes:
            group = ob.vertex_groups.get(name)
            if group is None:
                continue
            hand = {{ob.vertex_groups[g].index for g in digits if g in ob.vertex_groups}}
            for v in ob.data.vertices:
                if sum(g.weight for g in v.groups if g.group in hand) <= 0.5:
                    continue
                w = ob.matrix_world @ v.co
                whole.append(inv @ (to_arm @ w - head))
                if next((g.weight for g in v.groups
                         if g.group == group.index), 0.0) > 0.5:
                    palm_a.append(inv @ (to_arm @ w - head))
                    palm_w.append(inv @ (w - head))          # the OLD, wrong space
        h["n_palm"], h["n_whole"] = len(palm_a), len(whole)
        along = fbx_clip._hand_direction(bones, src_of, inter, bone)
        h["normal_arm_space"] = list(fbx_clip._pca_smallest(palm_a))
        h["normal_world_space"] = list(fbx_clip._pca_smallest(palm_w))
        proj = sorted(p.dot(axis) for p in whole)
        k = int(fbx_clip._PALM_REACH_PCT * (len(proj) - 1))
        near, far = proj[k], proj[len(proj) - 1 - k]
        h["reach_skew"] = (far + near) / (far - near)
        idx, pky = src_of.get(side + "HandIndex1"), src_of.get(side + "HandPinky1")
        mid = src_of.get(side + "HandMiddle1")
        if idx and idx in bones and pky in bones:
            truth = (bones[idx].head_local - bones[pky].head_local).normalized()
            h["truth_angle"] = math.degrees(in_arm[inter].angle(truth))
            h["truth_dot_shoulders"] = truth.dot(lat)
            if mid and mid in bones:
                hd = (bones[mid].head_local - bone.head_local).normalized()
                h["hand_dir_vs_local_y"] = math.degrees(
                    hd.angle((rest @ Vector((0.0, 1.0, 0.0))).normalized()))
                tn = hd.cross(truth).normalized()
                for key, nrm in (("normal_arm_space", h["normal_arm_space"]),
                                 ("normal_world_space", h["normal_world_space"])):
                    a = math.degrees(tn.angle((rest @ Vector(nrm)).normalized()))
                    h[key + "_err"] = min(a, 180.0 - a)
        r["hands"][inter] = h
    if len(in_arm) == 2:
        left = in_arm["lhand"]
        mirrored = left - lat * (2.0 * left.dot(lat))
        r["mirror_dot"] = mirrored.dot(in_arm["rhand"])
    return r


for path in json.loads({rigs!r}):
    try:
        out["rigs"].append(measure(path))
    except Exception as e:
        out["rigs"].append({{"file": path, "error": f"{{type(e).__name__}}: {{e}}"}})


# ---------------------------------------------------------------- [6] gating
class _Node:
    def __init__(self, m):
        self.matrix_world = m


def synth(seed):
    P = {{k: Vector(v) for k, v in seed.items()}}
    fbx_clip._synth_hand_targets(P, {{"lhand": _Node(Matrix.Identity(4))}},
                                 {{"lhand": Vector((0.0, 0.0, 1.0))}})
    return {{k: list(v) for k, v in P.items()}}


BASE = {{"lradius": (45, 150, 0), "lhand": (70, 150, 0)}}
out["unit"]["with_middle"] = synth(dict(BASE, LeftHandMiddle1=(78, 150, 0)))
out["unit"]["no_middle"] = synth(dict(BASE))
out["unit"]["own_knuckles"] = synth(dict(
    BASE, LeftHandMiddle1=(78, 150, 0),
    LeftHandIndex1=(77, 150, 3), LeftHandPinky1=(77, 150, -3)))


# ------------------------------------------------------------- [7] pair route
class _Sk:
    bones = {{}}


class _Take:
    sk = _Sk()


REST_TABLE = {{"lhand": Vector((1.0, 0.0, 0.0))}}
seen = []


def fake_load(path, family, palm=None):
    seen.append("REST" if palm is REST_TABLE else ("None" if palm is None else repr(palm)))
    return 30.0, (1, 2), [{{}}], family, [{{}}], {{}}


def probe_run(inputs):
    del seen[:]
    fbx_clip._load_source = fake_load
    fbx_clip._mixamo_rest = lambda rig: ({{}}, {{}})
    fbx_clip._rest_reference = lambda p, f, m: ({{}}, REST_TABLE)
    fbx_clip._build_take = lambda *a, **k: _Take()
    cmu_clip.run_takes = lambda takes, args, fps, source: source
    fbx_clip.run({{"inputs": inputs, "params": {{"bone_map": "meshy-biped"}},
                  "out_dir": "."}})
    return list(seen)


out["unit"]["pair_rest"] = probe_run(
    {{"rig": "r.fbx", "src_a": "a.fbx", "src_b": "b.fbx", "rest": "t.fbx"}})
out["unit"]["pair_norest"] = probe_run(
    {{"rig": "r.fbx", "src_a": "a.fbx", "src_b": "b.fbx"}})
out["unit"]["solo_norest"] = probe_run({{"rig": "r.fbx", "src": "a.fbx"}})

print("SMOKE_JSON " + json.dumps(out))
'''

failures = []


def check(label, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


def near(label, got, want, tol):
    check(label, abs(got - want) <= tol, f"{got:.4f} (expected {want} +- {tol})")


def main() -> int:
    exe = runner.find_executable()
    if not exe:
        print("Blender not found — nothing was checked")
        return 1
    wanted = [Path(a).resolve() for a in sys.argv[1:]] or DEFAULT_RIGS
    rigs, missing = [], []
    for r in wanted:
        (rigs if r.is_file() else missing).append(r)
    for m in missing:
        print(f"SKIPPED (not a file, local material): {m}")

    with tempfile.TemporaryDirectory() as tmp:
        probe = Path(tmp) / "probe.py"
        probe.write_text(PROBE.format(
            scripts=str(ROOT / "app/blender/scripts"),
            rigs=json.dumps([str(r) for r in rigs])))
        res = subprocess.run([exe, "-b", "--factory-startup", "--python", str(probe)],
                             capture_output=True, text=True, timeout=900)
    line = next((ln for ln in res.stdout.splitlines() if ln.startswith("SMOKE_JSON ")), "")
    if not line:
        print(res.stdout[-3000:])
        print(res.stderr[-3000:])
        print("the probe produced no result")
        return 1
    d = json.loads(line[len("SMOKE_JSON "):])

    for r in d["rigs"]:
        name = Path(r["file"]).name
        print(f"\n=== {name} ({r.get('family', '?')})")
        if r.get("error"):
            print(f"  FAIL could not be measured — {r['error']}")
            failures.append(name)
            continue
        hands = r.get("hands", {})
        check(f"{name}: both hands measured", len(hands) == 2,
              f"{sorted(hands)}")
        fingered = any("truth_angle" in h for h in hands.values())
        for inter, h in sorted(hands.items()):
            tag = f"{name}/{inter}"
            print(f"  [{inter}] {h['n_palm']} palm / {h['n_whole']} hand vertices")
            if "normal_arm_space_err" in h:
                print("[1] the palm plane is fitted in ONE space")
                check(f"{tag}: normal, armature space, <= 15 deg off the real palm",
                      h["normal_arm_space_err"] <= 15.0,
                      f"{h['normal_arm_space_err']:.2f} deg")
                check(f"{tag}: normal, world space (the defect), >= 45 deg off",
                      h["normal_world_space_err"] >= 45.0,
                      f"{h['normal_world_space_err']:.2f} deg")
                print("[2] and the axis lands on the real knuckle line")
                check(f"{tag}: axis <= 20 deg off Index1-Pinky1",
                      h["truth_angle"] <= 20.0, f"{h['truth_angle']:.2f} deg")
                check(f"{tag}: local Y is NOT the hand's direction here",
                      h["hand_dir_vs_local_y"] > 45.0,
                      f"{h['hand_dir_vs_local_y']:.2f} deg to the middle root")
            print("[5] the thumb's reach decides the sign")
            check(f"{tag}: |reach skew| >= 0.03",
                  abs(h["reach_skew"]) >= 0.03, f"{h['reach_skew']:+.4f}")
            if "truth_angle" in h:
                check(f"{tag}: and the side it chose is the knuckle line's",
                      h["truth_angle"] < 90.0,
                      f"{h['truth_angle']:.2f} deg, not {180.0 - h['truth_angle']:.2f}")
        if len(hands) == 2:
            print("[3] the two hands are mirror images")
            check(f"{name}: mirrored left . right >= 0.99",
                  r.get("mirror_dot", -1.0) >= 0.99, f"{r.get('mirror_dot'):+.4f}")
            print("[4] the shoulder line cannot decide the sign")
            dl, dr = (hands["lhand"]["dot_shoulders"], hands["rhand"]["dot_shoulders"])
            check(f"{name}: the two hands lie on OPPOSITE sides of it",
                  dl * dr < 0.0, f"{dl:+.4f} / {dr:+.4f}")
            check(f"{name}: and neither is decisive (|cos| < 0.5)",
                  max(abs(dl), abs(dr)) < 0.5,
                  f"{math.degrees(math.acos(max(-1.0, min(1.0, dl)))):.1f} / "
                  f"{math.degrees(math.acos(max(-1.0, min(1.0, dr)))):.1f} deg")
        if not fingered:
            print("  (no finger bones — nothing to hold the axis against here)")

    u = d["unit"]
    print("\n[6] the knuckles are gated on the KNUCKLES, not on the middle root")
    got = u["with_middle"]
    check("a hand that already has its middle root still gets knuckles",
          "LeftHandIndex1" in got and "LeftHandPinky1" in got, f"{sorted(got)}")
    if "LeftHandIndex1" in got:
        near("  index at (70, 154.1667, 0), Y", got["LeftHandIndex1"][1], 154.1667, 1e-3)
        near("  pinky at (70, 145.8333, 0), Y", got["LeftHandPinky1"][1], 145.8333, 1e-3)
        check("  and the middle root it brought is untouched",
              got["LeftHandMiddle1"] == [78.0, 150.0, 0.0], f"{got['LeftHandMiddle1']}")
    no_mid = u["no_middle"]
    check("a hand without one gets it along the node's own Y",
          [round(v, 4) for v in no_mid.get("LeftHandMiddle1", [])]
          == [70.0, 150.0, -8.3333], f"{no_mid.get('LeftHandMiddle1')}")
    own = u["own_knuckles"]
    check("a hand that brings real knuckles keeps them",
          own["LeftHandIndex1"] == [77.0, 150.0, 3.0]
          and own["LeftHandPinky1"] == [77.0, 150.0, -3.0],
          f"{own['LeftHandIndex1']} / {own['LeftHandPinky1']}")

    print("\n[7] every source of a pair is handed the SAME palm table")
    check("pair with a rest file: both halves get the rest table",
          u["pair_rest"] == ["REST", "REST"], f"{u['pair_rest']}")
    check("pair without one: both halves measure themselves",
          u["pair_norest"] == ["None", "None"], f"{u['pair_norest']}")
    check("solo without one: it measures itself",
          u["solo_norest"] == ["None"], f"{u['solo_norest']}")

    print()
    if missing and not rigs:
        print("No rest rig was available — [1]-[5] were NOT checked.")
    if failures:
        print(f"FAILED: {len(failures)} check(s): {', '.join(failures)}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
