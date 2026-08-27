"""Shared boilerplate for the bpy scripts: read the job, write the result.

These scripts run inside Blender's OWN Python — the application's venv is not
importable here, so this module may only use the standard library and bpy.
Blender's BUNDLED numpy is allowed too (ruling 2026-08-27, spec-picture-props
§ 2): pixel access over ``image.pixels`` is hopeless in pure Python, and the
bundle ships numpy with every Blender release.

``app_root_on_path()`` puts the repository root on ``sys.path`` so a script
can import a module of the application — ONLY modules that are stdlib-only
by contract (``app.core.picture_areas`` is the one such module today). Any
other ``app.*`` import would drag the venv's dependencies in and fail on the
first ``import numpy``-style line that resolves against the wrong interpreter.
"""
import json
import sys
import traceback
from pathlib import Path

# <repo>/app/blender/scripts/_common.py -> <repo>
_APP_ROOT = Path(__file__).resolve().parents[3]


def app_root_on_path():
    """Makes ``app.core.<stdlib-only module>`` importable; idempotent.

    The root goes to the END of the path, not the front: nothing of the
    repository may shadow a stdlib module Blender's add-ons import while they
    load (the same reason the scripts directory itself is only on the path
    for the sibling import and comes straight back off it).
    """
    root = str(_APP_ROOT)
    if root not in sys.path:
        sys.path.append(root)
    return _APP_ROOT

# Blender's importers are addons; their operators live under bpy.ops.
IMPORTERS = {
    ".glb": "gltf", ".gltf": "gltf", ".fbx": "fbx", ".obj": "obj",
    ".ply": "ply", ".stl": "stl",
}


def read_args():
    """The job description the runner wrote (everything after ``--``)."""
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if not argv:
        raise SystemExit("no args file given")
    return json.loads(Path(argv[0]).read_text(encoding="utf-8"))


def write_result(args, ok, data=None, outputs=None, error=""):
    Path(args["result"]).write_text(json.dumps({
        "ok": bool(ok), "error": str(error),
        "data": data or {}, "outputs": outputs or {},
    }, ensure_ascii=False, indent=1), encoding="utf-8")


def main(fn):
    """Runs ``fn(args)`` and turns anything it raises into a failed result.

    A crashing script that wrote no result is indistinguishable from a
    Blender crash on the runner side; writing the traceback here makes the
    cause visible in the caller's log instead of only in Blender's stdout.
    """
    args = None
    try:
        args = read_args()
        data, outputs = fn(args)
        write_result(args, True, data=data, outputs=outputs)
    except BaseException as e:                    # noqa: BLE001 - last resort
        tb = traceback.format_exc()
        print(tb, file=sys.stderr)
        if args:
            write_result(args, False, error=f"{type(e).__name__}: {e}")
        raise SystemExit(1)


def import_model(path):
    """Loads a model into the EMPTY current scene, by extension.

    glTF: the importer keeps its DEFAULT bone heuristic (BLENDER) on purpose —
    it is the one that PRESERVES the source's joint orientations through an
    import/export round trip. TEMPERANCE looked attractive because it creates
    no display objects, but it RE-DERIVES every bone frame from the child
    positions: positions and bind stay consistent (rest pose looks right),
    while the exported joint rotations land in a different convention — and
    the clients apply the shared Mixamo clips INTO those local frames, so a
    rig whose source frames do not match the heuristic animates broken
    (2026-08-06 incident: 57 of 83 store files, hips pitched ~90-180°).
    The one real problem of the BLENDER heuristic — the Icosphere display
    object that falsified measurements — is solved by DELETING the bone
    custom shapes after import instead.
    """
    import bpy
    ext = Path(path).suffix.lower()
    kind = IMPORTERS.get(ext)
    if not kind:
        raise ValueError(f"unsupported model format: {ext}")
    if kind == "gltf":
        bpy.ops.import_scene.gltf(filepath=str(path))
        _drop_bone_shape_objects(bpy)
    elif kind == "fbx":
        # global_scale stays 1.0 on purpose: many rigs (Mixamo among them) are
        # authored in centimetres, and silently rescaling on import would hide
        # exactly the discrepancy this pipeline exists to measure.
        bpy.ops.import_scene.fbx(filepath=str(path), global_scale=1.0)
    elif kind == "obj":
        bpy.ops.wm.obj_import(filepath=str(path))
    elif kind == "ply":
        bpy.ops.wm.ply_import(filepath=str(path))
    elif kind == "stl":
        bpy.ops.wm.stl_import(filepath=str(path))


def _drop_bone_shape_objects(bpy):
    """Removes objects that exist only as bone display shapes.

    They are visual aids for a human in the viewport; in a headless pipeline
    they only falsify counts and bounds."""
    shapes = set()
    for obj in list(bpy.context.scene.objects):
        if obj.type != "ARMATURE" or obj.pose is None:
            continue
        for pb in obj.pose.bones:
            if pb.custom_shape is not None:
                shapes.add(pb.custom_shape.name)
    for obj in list(bpy.context.scene.objects):
        if obj.name in shapes:
            bpy.data.objects.remove(obj, do_unlink=True)


def reset_scene():
    import bpy
    bpy.ops.wm.read_factory_settings(use_empty=True)
