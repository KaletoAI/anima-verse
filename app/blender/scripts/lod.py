"""Builds reduced-triangle versions of a model — the LOD stages.

Unlike welding (which glTF undoes on export) this removes real geometry, so
the saving is real too. It also changes the silhouette, which is the point and
the risk: how far a model can be reduced before it shows depends on the model,
so the caller states the targets and nothing is decided here.

    ratios      list of target fractions of the original triangle count,
                e.g. [0.5, 0.25, 0.1]
    keep_uvs    preserve UV boundaries while collapsing (default on) — without
                it the texture slides across the reduced surface
    merge_vertices
                import the glTF with its vertices welded at the UV seams
                (default off = the character LODs as before). glTF stores a
                vertex per UV, so the imported mesh is cut at every seam and
                each island is decimated on its own: the cut edges shrink
                apart and the surface tears (a garment mesh went from 0.982
                to 0.724 largest-component share). Welded, the seams are
                ordinary edges and ``keep_uvs`` keeps them in place.

One file per ratio, named ``<stem>_lod<N>`` with N the achieved triangle
count, so a caller can tell the stages apart without opening them. Blender's
Decimate hits the ratio approximately, never exactly; the name carries what
was ACHIEVED, and ``data.stages[].tris`` repeats it.

A skinned mesh keeps its armature and its vertex weights — the modifier
interpolates them onto the surviving vertices. The joint count therefore does
not change, which is what the humanoid validation checks; whether the skinning
still deforms cleanly at a heavy reduction is a judgement call for whoever
looks at the render.

Meshes marked by the GLB node extra ``lod_preserve`` are kept intact: collapsing
joined thin panes can remove whole windows, not merely simplify their shape.

    protect_hands
                keep the fingers of a skinned humanoid out of the collapse
                (default off). Collapsing across the narrow gaps between the
                fingers fuses them into a paddle at distance ratios where the
                rest of the body is still fine (hand analysis 2026-11-18,
                § 1.3). The guarded set is every vertex skinned to a finger
                bone (``<Side>Hand<Finger><1-3>``) by at least
                ``HAND_GUARD_MIN_WEIGHT``, widened by ``HAND_GUARD_RINGS``
                edge rings so the webs between the fingers stay too. The
                guard is the Decimate modifier's own vertex group (inverted,
                factor ``HAND_GUARD_FACTOR``): an edge touching the set costs
                its length times the factor on top of its quadric error, so it
                is collapsed only after every other edge — the ratio is still
                met as a whole, the rest of the mesh pays for the hands. A
                mesh without finger groups (an animal, a ``generic`` or
                ``none`` rig, a prop) gets no group and decimates exactly as
                without the switch.
"""
import re
import sys
from pathlib import Path

_SCRIPTS_DIR = str(Path(__file__).parent)
sys.path.insert(0, _SCRIPTS_DIR)
import _common                                                # noqa: E402
sys.path.remove(_SCRIPTS_DIR)

import bpy                                                    # noqa: E402

# A finger joint of the Mixamo contract, after stripping the ``mixamorig`` prefix and the colon.
_FINGER_GROUP = re.compile(r"^(left|right)hand(thumb|index|middle|ring|pinky)[123]$")
HAND_GUARD_MIN_WEIGHT = 0.01   # a vertex with any real finger influence moves with the finger
HAND_GUARD_RINGS = 2           # edge rings around it: the webs and the knuckle crease
# Extra collapse cost per metre of edge length at a guarded vertex. Quadric errors of a body mesh are squared
# metres (1e-8..1e-4 for the edges a 0.4 ratio removes); an edge of 3 mm then costs 3 on top — no unguarded
# edge comes near that, so the guarded ones go last (Blender's maximum is 1000).
HAND_GUARD_FACTOR = 1000.0
HAND_GUARD_GROUP = "__lod_hand_guard__"


def _hand_guard(obj):
    """The guard vertex group of ``obj`` (weight 1 on the fingers and their rings), or None without finger
    groups — the caller then decimates exactly as without protection."""
    fingers = {g.index for g in obj.vertex_groups
               if _FINGER_GROUP.match(g.name.lower().replace("mixamorig", "").replace(":", ""))}
    if not fingers:
        return None
    me = obj.data
    guarded = set()
    for v in me.vertices:
        if sum(g.weight for g in v.groups if g.group in fingers) >= HAND_GUARD_MIN_WEIGHT:
            guarded.add(v.index)
    if not guarded:
        return None
    neighbours = {}
    for e in me.edges:
        a, b = e.vertices
        neighbours.setdefault(a, []).append(b)
        neighbours.setdefault(b, []).append(a)
    front = set(guarded)
    for _ in range(HAND_GUARD_RINGS):
        front = {n for v in front for n in neighbours.get(v, ())} - guarded
        guarded |= front
    group = obj.vertex_groups.new(name=HAND_GUARD_GROUP)
    group.add(sorted(guarded), 1.0, "REPLACE")
    return group


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
    merge_vertices = bool(p.get("merge_vertices", False))
    protect_hands = bool(p.get("protect_hands", False))
    out_dir = Path(args["out_dir"])
    stem = Path(src).stem

    stages, outputs = [], {}
    for level, ratio in enumerate(sorted(ratios, reverse=True), 1):
        _common.progress("levels", level, len(ratios))
        # Fresh import per stage: decimating an already decimated mesh would
        # compound the error, and the ratios are meant to be of the ORIGINAL.
        _common.reset_scene()
        _common.import_model(src, gltf_merge_vertices=merge_vertices)
        before = _tris()
        guarded_tris = 0
        for obj in _mesh_objects():
            if obj.get("lod_preserve"):
                continue
            guard = _hand_guard(obj) if protect_hands else None
            mod = obj.modifiers.new(name="LOD", type="DECIMATE")
            mod.decimate_type = "COLLAPSE"
            mod.ratio = ratio
            mod.use_collapse_triangulate = True
            if keep_uvs:
                mod.delimit = {"UV"}
            if guard is not None:
                mod.vertex_group = guard.name
                mod.invert_vertex_group = True
                mod.vertex_group_factor = HAND_GUARD_FACTOR
            # Applying needs the object to be the active one.
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.modifier_apply(modifier=mod.name)
            guard = obj.vertex_groups.get(HAND_GUARD_GROUP) if guard is not None else None
            if guard is not None:
                # Counted on the reduced mesh, then dropped: the exporter must not meet a group no bone owns.
                # (Looked up again by name: applying the modifier invalidates the old reference.)
                members = {v.index for v in obj.data.vertices
                           if any(g.group == guard.index and g.weight > 0.5 for g in v.groups)}
                obj.data.calc_loop_triangles()
                guarded_tris += sum(1 for t in obj.data.loop_triangles if all(i in members for i in t.vertices))
                obj.vertex_groups.remove(guard)
        after = _tris()
        name = f"{stem}_lod{after}.glb"
        path = out_dir / name
        # Geometry extras (such as interior cutout margins) must survive tier swaps.
        bpy.ops.export_scene.gltf(filepath=str(path), export_format="GLB", export_extras=True)
        _common.body_meshes_first(path)
        stage = {
            "ratio": ratio,
            "tris_before": before,
            "tris": after,
            "file": name,
            "file_bytes": path.stat().st_size,
        }
        if protect_hands:
            stage["hand_guard_tris"] = guarded_tris
        stages.append(stage)
        outputs[f"lod{after}"] = str(path)

    return {"stages": stages, "source_tris": stages[0]["tris_before"]}, outputs


_common.main(lod)
