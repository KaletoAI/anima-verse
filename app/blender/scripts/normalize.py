"""Normalises a model in place: real height, feet on the ground, origin
under the feet, transforms baked into the geometry.

What today every renderer corrects at runtime (scale from the profile height,
ground offset from the bounding box, Z-up uprighting) is done ONCE here, so a
number read anywhere outside a renderer is the real one — the architecture
rule behind ``scene_recipe.py``: geometry lives in exactly one place.

    target_height_m   the height the model must end up with (> 0, metres)

Height basis (plan-blender-veredelung.md § 2.0, decided 2026-08-06): a Mixamo
rig is measured at its CROWN JOINT (``HeadTop_End``) — hair, hats and horns
above the crown must not shrink the body, which is exactly what a bounding-box
scale does. The gateway's 52-joint rigs END AT ``Head`` (no crown joint), so
for them the crown is ESTIMATED: measured over the whole store (73 models,
2026-08-07), the head joint sits at median 0.877 of the visual height with a
0.82..0.92 spread — the estimate ``(head - floor) / 0.875`` is therefore only
trusted when the box is CLEARLY taller than anatomy allows (head ratio below
0.80, i.e. headwear adds more than ~9 %); inside the normal band the box is
exact and anatomy would only add noise. Anything without a head joint
(generic rigs, props) keeps the box.

Steps, in order:

    1. measure   bounding box, crown joint, triangles, joints
    2. scale     measured height -> target_height_m, uniformly
    3. ground    X/Y centre of the box to 0, lowest point to z=0
    4. bake      transforms applied, so scale/rotation live in the geometry
                 and no importer heuristic ("is this Z-up?") has to guess

Reported under ``data``: ``height_basis`` ("crown"|"bbox"), ``scale``, and
``before``/``after`` with {dims_m, center_xy, min_z, tris, joints} each —
the numbers the sidecar keeps against double normalisation.

The exporter writes the same format the input had (GLB in practice — the
caller gates on it). Nothing here validates the result; the application side
holds it to the same check as a fresh delivery and keeps the original if the
export broke anything (§ 2.2).
"""
import sys
from pathlib import Path

_SCRIPTS_DIR = str(Path(__file__).parent)
sys.path.insert(0, _SCRIPTS_DIR)
import _common                                                # noqa: E402
sys.path.remove(_SCRIPTS_DIR)

import bpy                                                    # noqa: E402
from mathutils import Matrix, Vector                          # noqa: E402


def _mesh_objects():
    return [o for o in bpy.context.scene.objects if o.type == "MESH"]


def _world_bounds(objects):
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


def _joints():
    return sum(len(o.data.bones) for o in bpy.context.scene.objects
               if o.type == "ARMATURE")


# The head joint's anatomical share of standing height, and the band below
# which a bounding box is considered inflated by headwear — both derived from
# the 2026-08-07 store survey (see the module docstring).
HEAD_SHARE = 0.875
HEAD_RATIO_TRUSTED = 0.80


def _head_joints():
    """(crown_z, head_z) world heights — either may be None.

    ``HeadTop_End`` is the exact crown where a rig has one; ``Head`` (the
    skull base) is what the gateway's 52-joint rigs end at and feeds the
    estimate."""
    crown = head = None
    for arm in bpy.context.scene.objects:
        if arm.type != "ARMATURE":
            continue
        for bone in arm.data.bones:
            name = bone.name.lower().replace(":", "").replace("_", "")
            z = (arm.matrix_world @ bone.head_local).z
            if "headtopend" in name:
                crown = z
            elif name.endswith("head"):
                head = z
    return crown, head


def _snapshot(bounds):
    lo, hi = bounds
    return {
        "dims_m": [round(hi[i] - lo[i], 4) for i in range(3)],
        "center_xy": [round((hi[0] + lo[0]) / 2, 4),
                      round((hi[1] + lo[1]) / 2, 4)],
        "min_z": round(lo[2], 4),
        "tris": _tris(),
        "joints": _joints(),
    }


def normalize(args):
    src = args["inputs"].get("model")
    if not src:
        raise ValueError("no input 'model'")
    target = float(args["params"].get("target_height_m") or 0)
    if target <= 0:
        raise ValueError("target_height_m must be > 0")

    _common.reset_scene()
    _common.import_model(src)

    bounds = _world_bounds(_mesh_objects())
    if not bounds:
        raise ValueError("model contains no mesh")
    before = _snapshot(bounds)
    lo, hi = bounds

    crown, head = _head_joints()
    box_height = hi.z - lo.z
    if crown is not None and crown > lo.z + 1e-6:
        basis, height_now = "crown", crown - lo.z
    elif (head is not None and box_height > 1e-6
          and (head - lo.z) / box_height < HEAD_RATIO_TRUSTED):
        # The box is taller than anatomy allows — headwear. Estimate the
        # crown from the head joint instead of letting the box shrink the
        # body (the Ondina case: box 2.33 m, head at 0.65 of it).
        basis, height_now = "head-est", (head - lo.z) / HEAD_SHARE
    else:
        basis, height_now = "bbox", box_height
    if height_now <= 1e-6:
        raise ValueError("model has no measurable height")
    scale = target / height_now
    if not 0.001 <= scale <= 1000:
        raise ValueError(f"refusing implausible scale {scale:.5f} "
                         f"(height {height_now:.4f} m -> {target:.4f} m)")

    # Scale and ground the TOP-LEVEL objects: children follow their parents,
    # and touching both would apply the factor twice.
    roots = [o for o in bpy.context.scene.objects if o.parent is None]
    for obj in roots:
        obj.matrix_world = Matrix.Scale(scale, 4) @ obj.matrix_world
    bpy.context.view_layer.update()
    lo, hi = _world_bounds(_mesh_objects())
    shift = Vector(((hi.x + lo.x) / -2, (hi.y + lo.y) / -2, -lo.z))
    for obj in roots:
        obj.matrix_world = Matrix.Translation(shift) @ obj.matrix_world
    bpy.context.view_layer.update()

    # Bake the transforms into the data. Selection-based: the operator wants
    # the objects selected and one active.
    bpy.ops.object.select_all(action="SELECT")
    if roots:
        bpy.context.view_layer.objects.active = roots[0]
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    bpy.context.view_layer.update()

    after = _snapshot(_world_bounds(_mesh_objects()))

    out_dir = Path(args["out_dir"])
    name = Path(src).name
    path = out_dir / name
    if Path(src).suffix.lower() in (".glb", ".gltf"):
        bpy.ops.export_scene.gltf(filepath=str(path), export_format="GLB")
    else:
        bpy.ops.export_scene.fbx(filepath=str(path))

    return {
        "height_basis": basis,
        "scale": round(scale, 6),
        "target_height_m": target,
        "before": before,
        "after": after,
    }, {"model": str(path)}


_common.main(normalize)
