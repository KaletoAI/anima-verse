"""Makes a vertex-colour mesh (the Triposplat signature) usable: UV-unwrap,
bake the colours to a texture, optionally close holes.

A Gaussian-splat bake carries its colour in ``COLOR_0`` and has no UVs — no
engine with texture materials can use it, nothing can re-encode or shrink it
(``MeshNotShrinkable``), and the store treats the whole alias family as a
dead end. After this script the mesh is a NORMAL textured model: one UV set
(Smart UV Project — automated seams, good enough for baked colour), one
packed basecolor image, vertex colours removed (they would only bloat the
file next to the texture that replaces them).

    texture_size   edge length of the baked image (default 1024)
    fill_holes     close boundary loops first (default true) — splat meshes
                   leak holes, and the count before/after is reported so the
                   caller can see what happened
    target_tris    decimate down to roughly this triangle count BEFORE the
                   unwrap (0 = off). A splat bake carries hundreds of
                   thousands of triangles; unwrapping that first splits
                   vertices at every island seam and QUADRUPLES the file
                   (measured: 20.8 MB -> 93.9 MB on a real bar-stool splat).
                   Decimating first is safe exactly here because there are no
                   UVs to preserve yet, and the corner colours interpolate
                   through the collapse.

The bake itself renders EMISSION on Cycles CPU with 1 sample: the vertex
colour is wired into an emission shader, so the image receives the colours
untouched by any lighting. For export the material is rewired to a Principled
BSDF with the baked image as base colour — the shape the glTF exporter
understands.

Reported under ``data``: ``objects``, ``tris``, ``texture_size``,
``vcols_before``, ``boundary_before``/``boundary_after``, ``filled`` and
``baked`` (object count). Declares no output when NO object carries a vertex
colour — an already-textured model is not this script's business.
"""
import sys
from pathlib import Path

_SCRIPTS_DIR = str(Path(__file__).parent)
sys.path.insert(0, _SCRIPTS_DIR)
import _common                                                # noqa: E402
sys.path.remove(_SCRIPTS_DIR)

import bmesh                                                  # noqa: E402
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


def _boundary_edges():
    total = 0
    for obj in _mesh_objects():
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        total += sum(1 for e in bm.edges if len(e.link_faces) == 1)
        bm.free()
    return total


def _weld(obj):
    """Merges duplicate vertices (0.01 mm) so topology is real again.

    The glTF format splits every vertex whose faces disagree on an attribute
    — on an imported mesh EVERY edge of a flat-shaded surface reads as a
    boundary and a hole loop is not even connected (same lesson as in
    diagnose.py, which welds for measuring only). Corner colour attributes
    live per loop and survive the weld."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-5)
    bm.to_mesh(obj.data)
    bm.free()


def _fill_holes(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    edges = [e for e in bm.edges if len(e.link_faces) == 1]
    if edges:
        bmesh.ops.holes_fill(bm, edges=edges, sides=0)
        bm.to_mesh(obj.data)
    bm.free()


def _unwrap(obj):
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=1.15192, island_margin=0.003)
    bpy.ops.object.mode_set(mode="OBJECT")


def _bake(obj, size, index):
    """Bakes the object's first colour attribute into a packed image and
    leaves a Principled material carrying it as base colour."""
    color_name = obj.data.color_attributes[0].name
    img = bpy.data.images.new(f"baked_vc_{index}", size, size, alpha=False)

    mat = bpy.data.materials.new(f"baked_vc_mat_{index}")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    emit = nt.nodes.new("ShaderNodeEmission")
    attr = nt.nodes.new("ShaderNodeAttribute")
    attr.attribute_name = color_name
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = img
    nt.links.new(attr.outputs["Color"], emit.inputs["Color"])
    nt.links.new(emit.outputs["Emission"], out.inputs["Surface"])
    nt.nodes.active = tex                       # the bake target

    obj.data.materials.clear()
    obj.data.materials.append(mat)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.ops.object.bake(type="EMIT")
    img.pack()

    # Rewire for export: Principled with the baked image as base colour.
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = img
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    # The colours now live in the texture; the per-vertex copy would only
    # bloat the file.
    while obj.data.color_attributes:
        obj.data.color_attributes.remove(obj.data.color_attributes[0])


def bake_vc(args):
    src = args["inputs"].get("model")
    if not src:
        raise ValueError("no input 'model'")
    p = args["params"]
    size = int(p.get("texture_size") or 1024)
    fill = bool(p.get("fill_holes", True))

    _common.reset_scene()
    _common.import_model(src)

    targets = [o for o in _mesh_objects() if o.data.color_attributes]
    vcols = sum(len(o.data.color_attributes) for o in targets)
    data = {
        "objects": len(_mesh_objects()),
        "vcols_before": vcols,
        "texture_size": size,
    }
    if not targets:
        # An already-textured model — nothing to convert, keep the original.
        return {**data, "baked": 0, "filled": False,
                "boundary_before": _boundary_edges(),
                "boundary_after": _boundary_edges(), "tris": _tris()}, {}

    # Weld FIRST: boundary counts and hole loops only mean anything on real
    # topology (see _weld).
    for obj in targets:
        _weld(obj)
    data["boundary_before"] = _boundary_edges()

    if fill:
        for obj in targets:
            _fill_holes(obj)
    data["filled"] = fill
    data["boundary_after"] = _boundary_edges()

    target = int(p.get("target_tris") or 0)
    tris_now = _tris()
    if target > 0 and tris_now > target:
        ratio = target / tris_now
        for obj in targets:
            mod = obj.modifiers.new(name="BAKE_LOD", type="DECIMATE")
            mod.decimate_type = "COLLAPSE"
            mod.ratio = ratio
            mod.use_collapse_triangulate = True
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.modifier_apply(modifier=mod.name)
    data["tris_before_bake"] = tris_now

    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 1
    for i, obj in enumerate(targets):
        _unwrap(obj)
        _bake(obj, size, i)

    data["baked"] = len(targets)
    data["tris"] = _tris()

    out_dir = Path(args["out_dir"])
    path = out_dir / Path(src).name
    bpy.ops.export_scene.gltf(filepath=str(path), export_format="GLB")
    return data, {"model": str(path)}


_common.main(bake_vc)
