"""Shared boilerplate for the bpy scripts: read the job, write the result.

These scripts run inside Blender's OWN Python — the application's venv is not
importable here, so this module may only use the standard library and bpy.
"""
import json
import sys
import traceback
from pathlib import Path

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
    """Loads a model into the EMPTY current scene, by extension."""
    import bpy
    ext = Path(path).suffix.lower()
    kind = IMPORTERS.get(ext)
    if not kind:
        raise ValueError(f"unsupported model format: {ext}")
    if kind == "gltf":
        bpy.ops.import_scene.gltf(filepath=str(path))
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


def reset_scene():
    import bpy
    bpy.ops.wm.read_factory_settings(use_empty=True)
