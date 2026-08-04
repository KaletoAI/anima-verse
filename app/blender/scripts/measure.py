"""Measures a model. Changes nothing, writes no file.

This is the deliberately consequence-free first stage: it proves the runner on
real store models and gives the UI real numbers, while every byte in the store
stays as it was. Everything the header parser in ``app/core/model_validate.py``
can only guess at is measured here for real — world-space size, triangle
count, bone NAMES, whether UVs exist at all.

Reported under ``data``:

    dims_m        [x, y, z] world-space bounding box of all mesh objects
    center_xy     [x, y] of that box — how far off the origin the model sits
    min_z         lowest point; 0 means "stands on the ground plane"
    tris          triangle count after triangulation — the count worth
                  comparing across formats
    verts         vertex count AS STORED, which is format-dependent: glTF
                  splits a corner whose adjacent faces disagree on normals or
                  UVs, so a plain cube reads 24 rather than 8
    objects       mesh object count
    materials     material names
    images        [{name, size, packed}] — packed False means the texture does
                  NOT travel with the file
    bones         armature bone count
    bone_names    first bones, for spotting a foreign rig by name
    mixamo_bones  how many carry the mixamorig prefix
    uv_layers     UV set count — 0 with vertex_colors > 0 is the Triposplat
                  signature (no UVs, colour in the vertices, not shrinkable)
    vertex_colors colour attribute count
    actions       animation count

Units: one Blender unit is taken as one metre, which is what glTF specifies.
An FBX is imported unscaled, so a rig authored in centimetres shows up as a
100x reading here rather than being silently corrected — that is a finding,
not noise.
"""
import sys
from pathlib import Path

# The scripts directory is on the search path for the sibling import ONLY, and
# comes straight back off it: Blender's add-ons import stdlib modules while
# they load, and a file here that shares a stdlib name would shadow it.
_SCRIPTS_DIR = str(Path(__file__).parent)
sys.path.insert(0, _SCRIPTS_DIR)
import _common                                                # noqa: E402
sys.path.remove(_SCRIPTS_DIR)

import bpy                                                    # noqa: E402
from mathutils import Vector                                  # noqa: E402

# How many bone names travel back — enough to recognise a rig, short enough to
# keep the result readable in a log line.
BONE_NAME_SAMPLE = 8


def _mesh_objects():
    return [o for o in bpy.context.scene.objects if o.type == "MESH"]


def _world_bounds(objects):
    """World-space bounding box over all objects, or None when there is none."""
    lo = Vector((float("inf"),) * 3)
    hi = Vector((float("-inf"),) * 3)
    found = False
    for obj in objects:
        for corner in obj.bound_box:
            p = obj.matrix_world @ Vector(corner)
            for i in range(3):
                lo[i] = min(lo[i], p[i])
                hi[i] = max(hi[i], p[i])
            found = True
    return (lo, hi) if found else None


def _triangles(mesh):
    """Triangle count — the honest one, after triangulation."""
    try:
        mesh.calc_loop_triangles()
        return len(mesh.loop_triangles)
    except Exception:
        # Older/newer API shifts: a polygon of n corners is n-2 triangles.
        return sum(max(0, len(p.vertices) - 2) for p in mesh.polygons)


def inspect(args):
    src = args["inputs"].get("model")
    if not src:
        raise ValueError("no input 'model'")

    _common.reset_scene()
    _common.import_model(src)

    meshes = _mesh_objects()
    bounds = _world_bounds(meshes)
    tris = verts = uv_layers = vcols = 0
    for obj in meshes:
        me = obj.data
        tris += _triangles(me)
        verts += len(me.vertices)
        uv_layers += len(me.uv_layers)
        try:
            vcols += len(me.color_attributes)
        except AttributeError:
            pass

    armatures = [o for o in bpy.context.scene.objects if o.type == "ARMATURE"]
    bone_names = []
    for arm in armatures:
        bone_names.extend(b.name for b in arm.data.bones)
    mixamo = sum(1 for n in bone_names if "mixamorig" in n.lower())

    images = []
    for img in bpy.data.images:
        if img.name in ("Render Result", "Viewer Node"):
            continue
        images.append({
            "name": img.name,
            "size": [int(img.size[0]), int(img.size[1])],
            "packed": bool(img.packed_file),
        })

    data = {
        "format": Path(src).suffix.lower().lstrip("."),
        "file_bytes": Path(src).stat().st_size,
        "objects": len(meshes),
        "tris": tris,
        "verts": verts,
        "materials": sorted({m.name for m in bpy.data.materials}),
        "images": images,
        "bones": len(bone_names),
        "bone_names": bone_names[:BONE_NAME_SAMPLE],
        "mixamo_bones": mixamo,
        "uv_layers": uv_layers,
        "vertex_colors": vcols,
        "actions": len(bpy.data.actions),
    }
    if bounds:
        lo, hi = bounds
        data["dims_m"] = [round(hi[i] - lo[i], 4) for i in range(3)]
        data["center_xy"] = [round((hi[0] + lo[0]) / 2, 4),
                             round((hi[1] + lo[1]) / 2, 4)]
        data["min_z"] = round(lo[2], 4)
    else:
        data["dims_m"] = [0.0, 0.0, 0.0]
        data["center_xy"] = [0.0, 0.0]
        data["min_z"] = 0.0
    return data, {}


_common.main(inspect)
