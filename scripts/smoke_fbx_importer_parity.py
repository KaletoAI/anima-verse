#!/usr/bin/env python3
"""Compare clip import results with a pinned legacy-importer revision.

Usage: ALSOFT_DRIVERS=null .venv/bin/python scripts/smoke_fbx_importer_parity.py

Requires Blender 5.2, git and the local reference fixtures. All artifacts live
in a temporary directory. The baseline is the explicit revision below.
Checks walk and the reference rig through clip_measure and clip_orient, then
exports two synthetic actions with bake_anim_use_all_actions and checks both
fbx_clip take indices. The synthetic root moves +10 and -20 cm over three
frames: take 0 must travel +0.1 m and take 1 -0.2 m, and each index must match
the pinned output. The reference has no animation; both scripts must reject
it as a clip.
Every output bone matrix is sampled at every integer frame, with the same
C++ importer for both files. Bone sets, action and scene frame ranges, and
fps must be EXACTLY equal. Rest heads/tails use TOL_REST_CM = 1e-3 cm;
pose matrix components use TOL_POSE = 1e-3 (translation in cm for these
clip rigs, rotation part unitless; 1e-3 radians is about 0.057 degrees).

Hand derivation: float32 has 24 significant binary digits, so spacing near
100 cm is 2**(6 - 23) = 7.6e-6 cm and near 200 cm is
2**(7 - 23) = 1.5e-5 cm. The two importers already differ by up to about
1.2e-4 in a bare import before our processing. A few chained matrix
products accumulate that rounding; a 1e-3 bound covers it and the measured
processed maxima (rest <= 2.8e-4 cm, pose components <= 5.4e-4). This
separates importer rounding from a real behaviour change: a wrong take,
lost slot, or bone-axis flip changes motion by >= 1 cm or several degrees.
The synthetic two-take check keeps this distinction observable: a wrong
take mapping swaps +10 cm with -20 cm, a 30 cm error, far above the bound.

A second synthetic file has A animating the armature and its parent empty,
and B animating only the armature. The parent's static Blender translation
is (0.25, -0.15, 0.05) m, with zero rotation and unit scale. Converting
Z-up metres to Y-up centimetres gives (25, 5, 15) cm by hand. A moves from
+10 to +50 cm on X relative to that position; B has no parent tracks and must keep the
static transform, including after sampling A. B also omits one finger's
tracks: its static basis is identity, while A translates it by 3 cm.
B alone and B after A must have identical fps/ranges and all positions,
rotations, parent matrices and omitted-bone bases within TOL_POSE = 1e-3.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BASELINE = "a98f9ed543e0493e55790104ad2533d90e0bb2fd"
TOL_REST_CM = 1e-3
TOL_POSE = 1e-3
os.environ["ALSOFT_DRIVERS"] = "null"
sys.path.insert(0, str(ROOT))
from app.blender import runner


MEASURE = r'''import bpy, json, sys
from pathlib import Path
job = json.loads(Path(sys.argv[-1]).read_text())
results = {}
for label, path in job["inputs"].items():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.wm.fbx_import(filepath=path, anim_offset=0.0)
    scene = bpy.context.scene
    arms = sorted((o for o in scene.objects if o.type == "ARMATURE"), key=lambda o: o.name)
    actions = [o.animation_data.action for o in arms
               if o.animation_data and o.animation_data.action]
    span = [min(a.frame_range[0] for a in actions), max(a.frame_range[1] for a in actions)] if actions else None
    frames = range(int(round(span[0])), int(round(span[1])) + 1) if span else [1]
    rigs = []
    for arm in arms:
        names = sorted(b.name for b in arm.data.bones)
        rest = {name: [list(arm.data.bones[name].head_local), list(arm.data.bones[name].tail_local)] for name in names}
        poses = []
        for frame in frames:
            scene.frame_set(frame)
            bpy.context.view_layer.update()
            poses.append([[float(v) for row in arm.pose.bones[name].matrix for v in row] for name in names])
        rigs.append({"names": names, "rest": rest, "poses": poses})
    results[label] = {"range": span, "scene_range": [scene.frame_start, scene.frame_end],
                      "fps": [scene.render.fps, scene.render.fps_base], "rigs": rigs}
Path(job["result"]).write_text(json.dumps({"ok": True, "data": results, "outputs": {}}))
'''

BUILD = r'''import bpy, json, sys
from pathlib import Path
job = json.loads(Path(sys.argv[-1]).read_text())
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.wm.fbx_import(filepath=job["inputs"]["rig"], use_anim=False)
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
for o in list(bpy.data.objects):
    if o is not arm:
        bpy.data.objects.remove(o, do_unlink=True)
for bone in arm.data.bones:
    bone.name = bone.name.removeprefix("mixamorig:")
root = arm.pose.bones["Hips"]
for name, distance in (("alpha", 10.0), ("zulu", -20.0)):
    arm.animation_data_clear()
    for pb in arm.pose.bones:
        pb.matrix_basis.identity()
    for frame in (1, 2, 3):
        root.location = (distance * (frame - 1) / 2, 0, 0)
        root.keyframe_insert("location", frame=frame)
    arm.animation_data.action.name = name
    arm.animation_data.action.use_fake_user = True
scene = bpy.context.scene
scene.render.fps = 30
scene.frame_start, scene.frame_end = 1, 3
out = str(Path(job["out_dir"]) / "two-takes.fbx")
bpy.ops.export_scene.fbx(filepath=out, object_types={"ARMATURE"}, add_leaf_bones=False,
                         bake_anim=True, bake_anim_use_all_actions=True, bake_anim_use_nla_strips=False,
                         bake_anim_simplify_factor=0.0)

# Export the same takes with a static parent. Add parent tracks to A and
# remove B's finger curve nodes below to produce a genuinely sparse take.
parent = bpy.data.objects.new("TakeParent", None)
scene.collection.objects.link(parent)
parent.location = (0.25, -0.15, 0.05)
arm.parent = parent
sparse = str(Path(job["out_dir"]) / "sparse-takes.fbx")
bpy.ops.export_scene.fbx(filepath=sparse, object_types={"ARMATURE", "EMPTY"}, add_leaf_bones=False,
                         bake_anim=True, bake_anim_use_all_actions=True, bake_anim_use_nla_strips=False,
                         bake_anim_simplify_factor=0.0)
from io_scene_fbx import parse_fbx, encode_bin, data_types
from copy import deepcopy
tree, version = parse_fbx.parse(sparse)
objects = next(e for e in tree.elems if e.id == b"Objects")
connections = next(e for e in tree.elems if e.id == b"Connections")
models = {e.props[1].split(b"\x00")[0]: e.props[0]
          for e in objects.elems if e.id == b"Model"}
targets = {models[b"TakeParent"], models[b"LeftHandIndex1"]}
stacks = [e.props[0] for e in objects.elems if e.id == b"AnimationStack"]
assert len(stacks) == 2
layers = {c.props[1]: c.props[2] for c in connections.elems
          if c.props[0] == b"OO" and c.props[2] in stacks}
nodes = {e.props[0] for e in objects.elems if e.id == b"AnimationCurveNode"}
node_targets = {c.props[1]: c.props[2] for c in connections.elems
                if c.props[0] == b"OP" and c.props[1] in nodes and c.props[2] in targets}
node_stacks = {c.props[1]: layers[c.props[2]] for c in connections.elems
               if c.props[1] in nodes and c.props[2] in layers}
removed = {n for n in node_targets if node_stacks[n] == stacks[1]}
assert len(removed) == 3, "B must omit finger translation/rotation/scale"
curves = {e.props[0]: e for e in objects.elems if e.id == b"AnimationCurve"}
next_id = max(e.props[0] for e in objects.elems) + 1
parent_model = next(e for e in objects.elems if e.props[0] == models[b"TakeParent"])
defaults = {e.props[0]: e.props[4:] for e in
            next(e for e in parent_model.elems if e.id == b"Properties70").elems}
# Clone A's finger tracks, retarget to the parent and replace their values
# with the model's static transform plus a 10..50 cm X translation.
for c in list(connections.elems):
    if c.props[1] not in node_targets or c.props[1] in removed or c.props[0] != b"OP":
        continue
    original = c.props[1]
    node = deepcopy(next(e for e in objects.elems if e.props[0] == original))
    node.props[0] = next_id
    next_id += 1
    objects.elems.append(node)
    target = deepcopy(c)
    target.props[1:3] = [node.props[0], models[b"TakeParent"]]
    connections.elems.append(target)
    layer = deepcopy(next(e for e in connections.elems
                          if e.props[1] == original and e.props[2] in layers))
    layer.props[1] = node.props[0]
    connections.elems.append(layer)
    for link in list(connections.elems):
        if link.props[1] not in curves or link.props[2] != original:
            continue
        curve = deepcopy(curves[link.props[1]])
        curve.props[0] = next_id
        next_id += 1
        axis = (b"d|X", b"d|Y", b"d|Z").index(link.props[3])
        value = defaults[c.props[3]][axis]
        values = next(e for e in curve.elems if e.id == b"KeyValueFloat").props[0]
        for i in range(len(values)):
            values[i] = value
            if c.props[3] == b"Lcl Translation" and axis == 0:
                values[i] += 10.0 + 40.0 * i / (len(values) - 1)
        objects.elems.append(curve)
        connection = deepcopy(link)
        connection.props[1:3] = [curve.props[0], node.props[0]]
        connections.elems.append(connection)
translation_nodes = {c.props[1] for c in connections.elems
                     if c.props[1] in node_targets and len(c.props) == 4
                     and c.props[3] == b"Lcl Translation"}
for c in connections.elems:
    if (c.props[1] in curves and c.props[2] in translation_nodes
            and c.props[2] not in removed and c.props[3] == b"d|X"):
        values = next(e for e in curves[c.props[1]].elems if e.id == b"KeyValueFloat").props[0]
        for i in range(len(values)):
            values[i] += 3.0 * i / (len(values) - 1)
objects.elems[:] = [e for e in objects.elems if e.props[0] not in removed]
connections.elems[:] = [c for c in connections.elems
                        if c.props[1] not in removed and c.props[2] not in removed]

def encode(elem):
    result = encode_bin.FBXElem(elem.id)
    for kind, value in zip(elem.props_type, elem.props):
        method = next(name.lower() for name in vars(data_types)
                      if name.isupper() and getattr(data_types, name) == kind)
        getattr(result, "add_" + method)(value)
    result.elems = [encode(e) for e in elem.elems]
    return result

encode_bin.write(sparse, encode(tree), version)
Path(job["result"]).write_text(json.dumps({"ok": True, "data": {},
                                         "outputs": {"pack": out, "sparse": sparse}}))
'''

SELECT = r'''import bpy, json, sys
from pathlib import Path
job = json.loads(Path(sys.argv[-1]).read_text())
sys.path.insert(0, job["params"]["scripts"])
import fbx_clip

def capture(source):
    fps, span, positions, rotations = source.sample()
    parent = bpy.data.objects["TakeParent"]
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    parent_frames, basis_frames = [], []
    for frame in range(span[0], span[1] + 1):
        bpy.context.scene.frame_set(frame)
        bpy.context.view_layer.update()
        matrix = parent.matrix_world.copy()
        matrix.translation *= 100.0
        parent_frames.append([list(row) for row in matrix])
        basis_frames.append([list(row) for row in arm.pose.bones["LeftHandIndex1"].matrix_basis])
    return {"fps": fps, "range": span,
            "positions": [{k: list(v) for k, v in p.items()} for p in positions],
            "rotations": [{k: [list(row) for row in v] for k, v in r.items()} for r in rotations],
            "parent": parent_frames, "basis": basis_frames}

handlers = list(bpy.app.handlers.depsgraph_update_pre)
source = fbx_clip._Source(job["inputs"]["src"], "auto")
assert list(bpy.app.handlers.depsgraph_update_pre) == handlers, "import callback must be removed"
assert [len(a.slots) for a in source.actions] == [2, 1], "fixture must have a sparse B"
try:
    source.select(0, 3)
except ValueError as error:
    assert "multi-layer takes are unsupported" in str(error), str(error)
else:
    raise AssertionError("take-count mismatch must be rejected")
source.select(1, 2)
alone = capture(source)
source.select(0, 2)
animated = capture(source)
source.select(1, 2)
after = capture(source)
Path(job["result"]).write_text(json.dumps({"ok": True, "outputs": {},
                                         "data": {"alone": alone, "animated": animated, "after": after}}))
'''


def export_baseline(destination):
    """Extract only the pinned Blender scripts without mutating the worktree."""
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / "scripts.tar"
    with archive.open("wb") as stream:
        subprocess.run(["git", "archive", BASELINE, "app/blender/scripts"],
                       cwd=ROOT, stdout=stream, check=True)
    with tarfile.open(archive) as stream:
        stream.extractall(destination, filter="data")
    archive.unlink()
    return destination / "app/blender/scripts"


def run_at(scripts, script, **kwargs):
    """Temporarily select a script directory for one synchronous runner call."""
    previous = runner.SCRIPTS_DIR
    try:
        runner.SCRIPTS_DIR = Path(scripts)
        return runner.run(script, timeout_s=900, **kwargs)
    finally:
        runner.SCRIPTS_DIR = previous


def max_delta(a, b):
    """Maximum numeric difference, requiring identical nested structure."""
    if isinstance(a, dict):
        assert a.keys() == b.keys(), "dictionary keys differ"
        return max((max_delta(a[k], b[k]) for k in a), default=0.0)
    if isinstance(a, (list, tuple)):
        assert len(a) == len(b), "sequence lengths differ"
        return max((max_delta(x, y) for x, y in zip(a, b)), default=0.0)
    if isinstance(a, (float, int)) and not isinstance(a, bool):
        assert isinstance(b, (float, int))
        assert abs(a - b) < float("inf"), "non-finite numeric result"
        return abs(a - b)
    assert a == b, "non-numeric values differ"
    return 0.0


def compare_fbx(helper_dir, old, new, *, enforce=True):
    """Measure both files in one Blender run, always with the C++ importer."""
    result = run_at(helper_dir, "parity_measure", inputs={"old": old, "new": new})
    assert result["ok"], result["error"]
    a, b = (result["data"][key] for key in ("old", "new"))
    for key in ("range", "scene_range", "fps"):
        assert a[key] == b[key], f"{key} differs"
    assert len(a["rigs"]) == len(b["rigs"]), "armature count differs"
    rest = pose = 0.0
    for x, y in zip(a["rigs"], b["rigs"]):
        assert x["names"] == y["names"], "bone sets differ"
        rest = max(rest, max_delta(x["rest"], y["rest"]))
        pose = max(pose, max_delta(x["poses"], y["poses"]))
    if enforce:
        assert rest <= TOL_REST_CM, f"rest delta {rest:g} cm > {TOL_REST_CM:g} cm"
        assert pose <= TOL_POSE, f"pose matrix delta {pose:g} > {TOL_POSE:g}"
    return {"rest": rest, "pose": pose}, a


def pair(old_scripts, current, script, inputs, params, out):
    results = []
    for label, scripts in (("old", old_scripts), ("new", current)):
        result = run_at(scripts, script, inputs=inputs, params=params, out_dir=out / label)
        assert result["ok"], f"{script}/{label}: {result['error']}"
        results.append(result)
    # The label of the largest verification residual can change when
    # several residuals differ only by floating-point roundoff.
    def comparable(data):
        if isinstance(data, dict):
            return {k: comparable(v) for k, v in data.items()
                    if k not in ("worst_bone", "worst_pos_bone")}
        if isinstance(data, list):
            return [comparable(v) for v in data]
        return data
    assert max_delta(comparable(results[0]["data"]), comparable(results[1]["data"])) <= 1e-4, f"{script}: result data differs"
    return results


def main():
    assert runner.is_available(), "Blender 5.2 is required"
    current = runner.SCRIPTS_DIR
    failures = []

    def check_motion(label, a, b, helpers):
        delta, motion = compare_fbx(helpers, Path(a), Path(b), enforce=False)
        print(f"{label}: {delta}")
        assert len(motion["rigs"]) == 1 and len(motion["rigs"][0]["names"]) == 69
        assert motion["fps"] == [30, 1.0], "output rate must remain 30 fps"
        if delta["rest"] > TOL_REST_CM or delta["pose"] > TOL_POSE:
            failures.append(f"{label}: {delta}")
        return motion

    with tempfile.TemporaryDirectory(prefix="fbx-importer-parity-") as td:
        tmp = Path(td)
        old = export_baseline(tmp / "baseline")
        helpers = tmp / "helpers"
        helpers.mkdir()
        (helpers / "parity_measure.py").write_text(MEASURE)
        (helpers / "parity_build.py").write_text(BUILD)
        (helpers / "parity_select.py").write_text(SELECT)
        rig = ROOT / "shared/models/rig/reference.fbx"
        walk = ROOT / "shared/models/clips/walk.fbx"
        for label, source in (("walk", walk), ("reference", rig)):
            measured = [run_at(s, "clip_measure", inputs={"clip": source}) for s in (old, current)]
            assert measured[0]["ok"] == measured[1]["ok"]
            if label == "reference":
                assert not measured[0]["ok"] and measured[0]["error"] == measured[1]["error"] == "ValueError: clip has no action"
            else:
                assert measured[0]["ok"], measured[0]["error"]
                for key, value in measured[0]["data"].items():
                    tolerance = 1e-4 if key == "head_tilt_deg_median" else 1e-6
                    assert max_delta(value, measured[1]["data"][key]) <= tolerance, f"walk {key} differs"
                assert len(measured[1]["data"]["bones"]) == 69
            # A rest-only file cannot be oriented as a clip. Check the same
            # rejection, then compare both scripts' reference-rig path on walk.
            if label == "reference":
                rejected = [run_at(s, "clip_orient", inputs={"rig": rig, "src": rig},
                                   params={"yaw_deg": 90}, out_dir=tmp / label / v)
                            for s, v in ((old, "old"), (current, "new"))]
                assert not rejected[0]["ok"] and not rejected[1]["ok"]
                assert rejected[0]["error"] == rejected[1]["error"]
                assert measured[0]["data"] == measured[1]["data"] == {}
                assert rejected[0]["data"] == rejected[1]["data"] == {}
                print("PASS reference: both scripts reject a clip without animation")
                continue
            a, b = pair(old, current, "clip_orient", {"rig": rig, "src": source},
                        {"yaw_deg": 90}, tmp / label)
            check_motion(f"{label} clip_orient", a["outputs"]["src"], b["outputs"]["src"], helpers)
            print(f"PASS {label}: numeric clip_measure data")
        built = run_at(helpers, "parity_build", inputs={"rig": rig}, out_dir=tmp / "fixture")
        assert built["ok"], built["error"]
        selected = run_at(helpers, "parity_select", inputs={"src": Path(built["outputs"]["sparse"])},
                          params={"scripts": str(current)})
        assert selected["ok"], selected["error"]
        alone, animated, after = (selected["data"][key] for key in ("alone", "animated", "after"))
        assert alone["fps"] == after["fps"] and alone["range"] == after["range"]
        delta = max_delta(alone, after)
        assert delta <= TOL_POSE, f"B after A differs from B alone by {delta:g} > {TOL_POSE:g}"
        static = [[1, 0, 0, 25], [0, 1, 0, -15], [0, 0, 1, 5], [0, 0, 0, 1]]
        identity = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
        for result in (alone, after):
            assert all(max_delta(m, static) <= TOL_POSE for m in result["parent"]), "B parent must stay static"
            assert all(max_delta(m, identity) <= TOL_POSE for m in result["basis"]), "B omitted bone must stay static"
        assert max_delta(animated["parent"], alone["parent"]) >= 49.9, "A must animate its parent"
        assert max_delta(animated["basis"], alone["basis"]) >= 2.9, "A must animate the omitted bone"
        print(f"PASS sparse takes: B after A equals B alone (max delta {delta:g}), parent and omitted bone stay static")
        pack = Path(built["outputs"]["pack"])
        from app.core.fbx_import import fbx_takes
        listing = fbx_takes(pack)
        assert len(listing) == 2, "two actions must export two takes"
        motions = []
        for take in listing:
            params = {"kind": "synthetic", "bone_map": "auto", "root_motion": "keep",
                      "source_name": ["two-takes.fbx"],
                      "takes": [{"take": take["index"], "take_count": 2, "take_name": take["name"]}]}
            a, b = pair(old, current, "fbx_clip", {"rig": rig, "src": pack}, params,
                        tmp / f"take-{take['index']}")
            assert a["data"]["frames"] == 3, "three keyed frames must survive"
            expected_travel = [0.1 if take["index"] == 0 else -0.2, 0.0]
            for result in (a, b):
                travel = result["data"]["geometry"]["root_motion"]["travel_m"]
                assert max_delta(travel, expected_travel) <= 1e-6, "synthetic take order differs"
            motions.append(check_motion(f"synthetic take {take['index']}",
                                        a["outputs"]["synthetic"], b["outputs"]["synthetic"], helpers))
        assert max_delta(motions[0], motions[1]) > 1.0, "the two motions must differ"
    if failures:
        print("FAIL smoke_fbx_importer_parity: " + "; ".join(failures))
        return 1
    print("OK smoke_fbx_importer_parity")
    return 0


if __name__ == "__main__":
    sys.exit(main())
