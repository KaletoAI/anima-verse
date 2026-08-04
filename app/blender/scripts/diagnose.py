"""Finds the geometry defects a bake leaves behind — before repairing any.

The symptom this exists for: a garment (a jacket, a coat hem) pulls single
triangles out of the surface into long thin spikes. They are not holes and not
loose parts, so neither a hole filler nor a fragment remover would touch them;
what marks them is that one edge is vastly longer than everything around it.

Measured per model, all lengths in metres:

    edge_median         the scale of the mesh's normal detail
    edge_p99 / edge_max
    spikes              edges longer than ``spike_factor`` x the median
    spike_worst         longest edge as a MULTIPLE of the median — the number
                        that separates a defect from a merely coarse mesh
    needles             triangles whose longest side is over ``needle_ratio``
                        times their shortest: thin slivers, the shape a
                        pulled-out triangle takes
    loose_parts         connected components; > 1 means the mesh is not one
                        piece (legitimate for a figure with separate garments,
                        suspicious for a single-object bake)
    tiny_parts          components under 1 % of the vertices — the fragments
                        that float beside a model
    boundary_edges      edges with only one face: holes, or intentional open
                        surfaces like a flat collar

Nothing is judged here and nothing is written. Which of these numbers means
"broken" is a question for whoever compares them across a real store, and that
comparison is the point of this script.
"""
import sys
from pathlib import Path

_SCRIPTS_DIR = str(Path(__file__).parent)
sys.path.insert(0, _SCRIPTS_DIR)
import _common                                                # noqa: E402
sys.path.remove(_SCRIPTS_DIR)

import bmesh                                                  # noqa: E402
import bpy                                                    # noqa: E402

DEFAULT_SPIKE_FACTOR = 8.0
DEFAULT_NEEDLE_RATIO = 20.0
# A component below this share of the vertices counts as a fragment.
TINY_PART_SHARE = 0.01


def _percentile(values, q):
    if not values:
        return 0.0
    s = sorted(values)
    idx = min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))
    return s[idx]


def _components(bm):
    seen, sizes = set(), []
    for v in bm.verts:
        if v.index in seen:
            continue
        stack, n = [v], 0
        seen.add(v.index)
        while stack:
            cur = stack.pop()
            n += 1
            for e in cur.link_edges:
                other = e.other_vert(cur)
                if other is not None and other.index not in seen:
                    seen.add(other.index)
                    stack.append(other)
        sizes.append(n)
    return sizes


def _skin_spread(obj, arm):
    """How far a bone's own vertices sit from the bone, per bone length.

    The measure that catches a bake which turned a garment into flat wings:
    the wings are still SKINNED to the arm bones, so the joints are all there
    and every count checks out — but their vertices sit a metre off a bone
    that is 30 cm long. On an intact figure this ratio stays near 1; a limb
    that dissolved into a surface pushes it far past that.

    Returns {bone: (ratio_p95, weighted_vertex_count)} for deforming bones
    that actually own vertices.
    """
    groups = {g.index: g.name for g in obj.vertex_groups}
    bones = {b.name: b for b in arm.data.bones}
    per_bone = {}
    mw = obj.matrix_world
    for v in obj.data.vertices:
        co = mw @ v.co
        for g in v.groups:
            if g.weight < 0.5:               # the bone that actually drives it
                continue
            name = groups.get(g.group)
            bone = bones.get(name) if name else None
            if bone is None or not bone.use_deform:
                continue
            head = arm.matrix_world @ bone.head_local
            tail = arm.matrix_world @ bone.tail_local
            seg = tail - head
            length = seg.length
            if length < 1e-6:
                continue
            # distance from the point to the bone SEGMENT, not to its head
            t = max(0.0, min(1.0, (co - head).dot(seg) / (length * length)))
            dist = (co - (head + seg * t)).length
            per_bone.setdefault(name, []).append(dist / length)
    out = {}
    for name, values in per_bone.items():
        if len(values) < 8:                  # too few to say anything
            continue
        out[name] = (_percentile(values, 0.95), len(values))
    return out


def diagnose(args):
    src = args["inputs"].get("model")
    if not src:
        raise ValueError("no input 'model'")
    p = args["params"]
    spike_factor = float(p.get("spike_factor") or DEFAULT_SPIKE_FACTOR)
    needle_ratio = float(p.get("needle_ratio") or DEFAULT_NEEDLE_RATIO)

    _common.reset_scene()
    _common.import_model(src)

    lengths, needles, boundary = [], 0, 0
    parts, verts_total = [], 0
    spike_out = []
    for obj in [o for o in bpy.context.scene.objects if o.type == "MESH"]:
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        # Weld FIRST, for the measurement only — nothing is written back.
        # glTF splits every vertex whose faces disagree on normals or UVs, so
        # on the imported mesh "connected component" counts UV islands, not
        # physical parts, and every seam reads as a hole. Both numbers are
        # meaningless without this.
        bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-5)
        bm.verts.index_update()
        scale = obj.matrix_world.to_scale()
        factor = (abs(scale.x) + abs(scale.y) + abs(scale.z)) / 3.0
        for e in bm.edges:
            lengths.append(e.calc_length() * factor)
            if len(e.link_faces) == 1:
                boundary += 1
        for f in bm.faces:
            sides = [e.calc_length() for e in f.edges]
            lo = min(sides)
            if lo > 1e-12 and max(sides) / lo > needle_ratio:
                needles += 1
        # How far each vertex sits from where its neighbours would put it,
        # measured in its OWN local edge length. This is what a pulled-out
        # triangle actually is: one corner displaced off the surface its
        # neighbours describe. A long edge alone does not say that — a coarse
        # but intact mesh has long edges everywhere, which is why comparing
        # the longest edge against the median found nothing.
        for v in bm.verts:
            links = list(v.link_edges)
            if len(links) < 3:
                continue
            neighbours = [e.other_vert(v) for e in links]
            neighbours = [n for n in neighbours if n is not None]
            if not neighbours:
                continue
            centre = sum((n.co for n in neighbours), neighbours[0].co * 0.0)
            centre = centre / len(neighbours)
            local = sum(e.calc_length() for e in links) / len(links)
            if local > 1e-9:
                spike_out.append((v.co - centre).length / local)
        parts.extend(_components(bm))
        verts_total += len(bm.verts)
        bm.free()

    # Skin spread, for rigged models only.
    arms = [o for o in bpy.context.scene.objects if o.type == "ARMATURE"]
    spread = {}
    if arms:
        for obj in [o for o in bpy.context.scene.objects if o.type == "MESH"]:
            if any(mod.type == "ARMATURE" for mod in obj.modifiers) or obj.parent in arms:
                spread.update(_skin_spread(obj, arms[0]))
    worst_bone, worst_spread = "", 0.0
    for name, (ratio, _n) in spread.items():
        if ratio > worst_spread:
            worst_bone, worst_spread = name, ratio

    median = _percentile(lengths, 0.5)
    longest = max(lengths) if lengths else 0.0
    spikes = sum(1 for x in lengths if median > 0 and x > spike_factor * median)
    tiny = sum(1 for n in parts if verts_total and n < TINY_PART_SHARE * verts_total)
    # The displacement measure is what ranks models against each other: how
    # many vertices stand off their neighbours' surface, and how far the worst
    # one does. A clean surface sits near 0.5; a pulled-out corner goes past 2.
    out_p999 = _percentile(spike_out, 0.999)
    return {
        "edges": len(lengths),
        "edge_median": round(median, 5),
        "edge_p99": round(_percentile(lengths, 0.99), 5),
        "edge_max": round(longest, 5),
        "spikes": spikes,
        "spike_worst": round(longest / median, 1) if median > 0 else 0,
        "off_surface_max": round(max(spike_out), 2) if spike_out else 0,
        "off_surface_p999": round(out_p999, 2),
        "off_surface_over2": sum(1 for x in spike_out if x > 2.0),
        "skin_spread_max": round(worst_spread, 2),
        "skin_spread_bone": worst_bone,
        "skin_spread_over3": sum(1 for r, _n in spread.values() if r > 3.0),
        "bones_with_verts": len(spread),
        "needles": needles,
        "loose_parts": len(parts),
        "tiny_parts": tiny,
        "boundary_edges": boundary,
        "spike_factor": spike_factor,
        "needle_ratio": needle_ratio,
    }, {}


_common.main(diagnose)
