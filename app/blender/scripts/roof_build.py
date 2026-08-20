"""Builds ONE roof from a finished vertex list — the dumb half.

Everything this script does was decided in ``app/core/roof_model.py``: it
receives a job JSON with the mesh's vertices (already in Blender's Z-up
frame), its faces, one material index per face and the materials themselves.
It builds the mesh, paints it, exports ONE unrigged GLB — it computes no
geometry, so every number in the result can be traced back to a function on
the server side and the smoke can check the same numbers WITHOUT Blender
(the pattern of ``scene_context.py``).

Job (``inputs["job"]``)::

    mesh       {name, vertices [[x, y, z], ...], faces [[i, ...], ...],
                face_material [int, ...]}
    materials  [ {name, tone, color [linear r, g, b], roughness} ]
    export     {glb}

Output: ``glb`` — the roof, one object, no rig, no texture (a roof tone is a
material, not an image; model contract v2 wants an unrigged GLB and that is
what this is).
"""
import json
import sys
from pathlib import Path

_SCRIPTS_DIR = str(Path(__file__).parent)
sys.path.insert(0, _SCRIPTS_DIR)
import _common                                                # noqa: E402
sys.path.remove(_SCRIPTS_DIR)

import bpy                                                    # noqa: E402


def _material(spec, index):
    mat = bpy.data.materials.new(str(spec.get("name") or f"m{index}"))
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        r, g, b = (list(spec.get("color") or []) + [0.5, 0.5, 0.5])[:3]
        bsdf.inputs["Base Color"].default_value = (float(r), float(g),
                                                   float(b), 1.0)
        try:
            bsdf.inputs["Roughness"].default_value = float(
                spec.get("roughness", 0.8))
        except KeyError:
            pass
        # A roof is not a mirror: whatever the tone, the metal look comes from
        # the roughness, not from a metallic surface nobody asked for.
        try:
            bsdf.inputs["Metallic"].default_value = 0.0
        except KeyError:
            pass
    return mat


def build(args):
    job_file = args["inputs"].get("job")
    if not job_file:
        raise ValueError("no input 'job'")
    job = json.loads(Path(job_file).read_text(encoding="utf-8"))
    mesh_spec = job.get("mesh") or {}
    verts = [tuple(float(c) for c in v) for v in mesh_spec.get("vertices") or []]
    faces = [list(int(i) for i in f) for f in mesh_spec.get("faces") or []]
    if len(verts) < 3 or not faces:
        raise ValueError("job carries no mesh")

    _common.reset_scene()
    me = bpy.data.meshes.new(str(mesh_spec.get("name") or "roof"))
    me.from_pydata(verts, [], faces)
    me.update()
    # A face list the server got wrong must not travel on as a broken GLB.
    me.validate(verbose=False)

    obj = bpy.data.objects.new(str(mesh_spec.get("name") or "roof"), me)
    bpy.context.scene.collection.objects.link(obj)

    materials = job.get("materials") or [{"name": "roof",
                                          "color": [0.2, 0.2, 0.2],
                                          "roughness": 0.8}]
    for i, spec in enumerate(materials):
        obj.data.materials.append(_material(spec, i))
    per_face = mesh_spec.get("face_material") or []
    for i, poly in enumerate(me.polygons):
        idx = int(per_face[i]) if i < len(per_face) else 0
        poly.material_index = max(0, min(idx, len(materials) - 1))
        # Flat shading: a roof has creases, and a smoothed ridge reads as a
        # dent from every distance the far view uses.
        poly.use_smooth = False

    out_dir = Path(args["out_dir"])
    glb = out_dir / str((job.get("export") or {}).get("glb") or "roof.glb")
    bpy.ops.export_scene.gltf(filepath=str(glb), export_format="GLB")

    # What was actually built — the server compares it against what it asked
    # for (§ B5a: numbers, not screenshots).
    lo = [min(v[i] for v in verts) for i in range(3)]
    hi = [max(v[i] for v in verts) for i in range(3)]
    return ({"vertices": len(me.vertices), "faces": len(me.polygons),
             "tris": len(me.loop_triangles) or sum(
                 max(0, len(f) - 2) for f in faces),
             "materials": len(materials),
             # Blender frame, the frame the job speaks.
             "bbox": [round(v, 5) for v in lo + hi],
             "bytes": glb.stat().st_size},
            {"glb": str(glb)})


_common.main(build)
