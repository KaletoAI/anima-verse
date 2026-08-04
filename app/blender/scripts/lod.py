"""Builds reduced-triangle versions of a model — the LOD stages.

Unlike welding (which glTF undoes on export) this removes real geometry, so
the saving is real too. It also changes the silhouette, which is the point and
the risk: how far a model can be reduced before it shows depends on the model,
so the caller states the targets and nothing is decided here.

    ratios      list of target fractions of the original triangle count,
                e.g. [0.5, 0.25, 0.1]
    keep_uvs    preserve UV boundaries while collapsing (default on) — without
                it the texture slides across the reduced surface

One file per ratio, named ``<stem>_lod<N>`` with N the achieved triangle
count, so a caller can tell the stages apart without opening them. Blender's
Decimate hits the ratio approximately, never exactly; the name carries what
was ACHIEVED, and ``data.stages[].tris`` repeats it.

A skinned mesh keeps its armature and its vertex weights — the modifier
interpolates them onto the surviving vertices. The joint count therefore does
not change, which is what the humanoid validation checks; whether the skinning
still deforms cleanly at a heavy reduction is a judgement call for whoever
looks at the render.
"""
import sys
from pathlib import Path

_SCRIPTS_DIR = str(Path(__file__).parent)
sys.path.insert(0, _SCRIPTS_DIR)
import _common                                                # noqa: E402
sys.path.remove(_SCRIPTS_DIR)

import bpy                                                    # noqa: E402


def _mesh_objects():
    return [o for o in bpy.context.scene.objects if o.type == "MESH"]


def _tris():
    total = 0
    for obj in _mesh_objects():
        me = obj.data
        try:
            me.calc_loop_triangles()
            total += len(me.loop_triangles)
        except Exception:
            total += sum(max(0, len(p.vertices) - 2) for p in me.polygons)
    return total


def lod(args):
    src = args["inputs"].get("model")
    if not src:
        raise ValueError("no input 'model'")
    p = args["params"]
    ratios = [float(r) for r in (p.get("ratios") or []) if 0 < float(r) < 1]
    if not ratios:
        raise ValueError("no usable ratios given")
    keep_uvs = bool(p.get("keep_uvs", True))
    out_dir = Path(args["out_dir"])
    stem = Path(src).stem

    stages, outputs = [], {}
    for ratio in sorted(ratios, reverse=True):
        # Fresh import per stage: decimating an already decimated mesh would
        # compound the error, and the ratios are meant to be of the ORIGINAL.
        _common.reset_scene()
        _common.import_model(src)
        before = _tris()
        for obj in _mesh_objects():
            mod = obj.modifiers.new(name="LOD", type="DECIMATE")
            mod.decimate_type = "COLLAPSE"
            mod.ratio = ratio
            mod.use_collapse_triangulate = True
            if keep_uvs:
                mod.delimit = {"UV"}
            # Applying needs the object to be the active one.
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.modifier_apply(modifier=mod.name)
        after = _tris()
        name = f"{stem}_lod{after}.glb"
        path = out_dir / name
        bpy.ops.export_scene.gltf(filepath=str(path), export_format="GLB")
        stages.append({
            "ratio": ratio,
            "tris_before": before,
            "tris": after,
            "file": name,
            "file_bytes": path.stat().st_size,
        })
        outputs[f"lod{after}"] = str(path)

    return {"stages": stages, "source_tris": stages[0]["tris_before"]}, outputs


_common.main(lod)
