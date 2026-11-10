"""Stands a rigged humanoid at a given posture: the whole figure (armature
and skin) is turned RIGIDLY so its hips->head line leans exactly as much
forward/back and sideways as ``forward_deg`` / ``side_deg`` say, then put
back on the ground and baked — the outfit body's posture match to its base
body (``app/core/outfit_body_posture.py`` holds the why).

    forward_deg   target lean of the rest hips->head line, degrees, positive
                  = head in front of the hips (the figure faces -Y)
    side_deg      target sideways lean, degrees, positive = head toward +X
    tolerance_deg a turn smaller than this exports nothing (default 0.05)

Measured on the REST bones (``bone.head_local`` in world space), exactly as
the application measures from the GLB's node tree. The turn is the minimal
rotation taking the current hips->head direction onto the target direction,
so both components land at once and nothing turns about the vertical. It is
applied to the top-level objects and baked with ``transform_apply``, the
same mechanism normalize's scale uses: only the ROOT bone's rest frame
changes (by the turn angle), every joint keeps its frame relative to its
parent — skin, weights and extension bones stay valid by construction.
Afterwards the box is re-centred in X/Y and its lowest point set to z = 0,
as normalize leaves a model.

Reported under ``data``: ``before`` / ``after`` / ``target`` (``forward_deg``,
``side_deg``), ``applied_deg`` (the turn's angle), ``axis`` (unit, world),
``root`` (the root bone's name) — the frame gate allows exactly
``applied_deg`` on that one joint.
"""
import math
import sys
from pathlib import Path

_SCRIPTS_DIR = str(Path(__file__).parent)
sys.path.insert(0, _SCRIPTS_DIR)
import _common                                                # noqa: E402
sys.path.remove(_SCRIPTS_DIR)

import bpy                                                    # noqa: E402
from mathutils import Matrix, Vector                          # noqa: E402


def _key(name):
    return name.lower().replace("mixamorig", "").replace(":", "")


def _lean(arm):
    bones = {_key(b.name): b for b in arm.data.bones}
    if "hips" not in bones or "head" not in bones:
        raise ValueError("posture match needs the Hips and Head bones")
    hips = arm.matrix_world @ bones["hips"].head_local
    head = arm.matrix_world @ bones["head"].head_local
    d = head - hips
    if d.z <= 1e-6:
        raise ValueError("the head is not above the hips")
    return {"forward_deg": round(math.degrees(math.atan2(-d.y, d.z)), 4),
            "side_deg": round(math.degrees(math.atan2(d.x, d.z)), 4)}, d.normalized(), hips


def _mesh_bounds():
    """World AABB of every mesh's VERTICES as the skin stands (evaluated).
    Not ``bound_box``: its 8 corners are the LOCAL box, and a turned local
    box reaches below the geometry (measured: 2.4 cm on a 9° turn)."""
    import numpy as np
    dg = bpy.context.evaluated_depsgraph_get()
    chunks = []
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        ev = obj.evaluated_get(dg)
        me = ev.to_mesh()
        n = len(me.vertices)
        if n:
            buf = np.empty(n * 3, dtype=np.float64)
            me.vertices.foreach_get("co", buf)
            mw = np.array(obj.matrix_world, dtype=np.float64)
            chunks.append(buf.reshape(-1, 3) @ mw[:3, :3].T + mw[:3, 3])
        ev.to_mesh_clear()
    if not chunks:
        raise ValueError("model contains no mesh")
    points = np.concatenate(chunks)
    lo, hi = points.min(axis=0), points.max(axis=0)
    return Vector(tuple(float(v) for v in lo)), Vector(tuple(float(v) for v in hi))


def posture_match(args):
    src = args["inputs"].get("model")
    if not src:
        raise ValueError("no input 'model'")
    params = args["params"]
    forward = float(params["forward_deg"])
    side = float(params["side_deg"])
    tolerance = float(params.get("tolerance_deg", 0.05))
    if not (abs(forward) < 60 and abs(side) < 60):
        raise ValueError(f"implausible target lean {forward:+.1f} / {side:+.1f} degrees")

    _common.reset_scene()
    _common.import_model(src)
    arms = [o for o in bpy.context.scene.objects if o.type == "ARMATURE"]
    if len(arms) != 1:
        raise ValueError("posture match needs exactly one armature")
    arm = arms[0]
    before, current, _hips = _lean(arm)
    target = Vector((math.tan(math.radians(side)), -math.tan(math.radians(forward)), 1.0)).normalized()
    turn = current.rotation_difference(target)
    angle = math.degrees(turn.angle)
    root = next((b.name for b in arm.data.bones if b.parent is None), "")
    data = {"before": before, "target": {"forward_deg": forward, "side_deg": side},
            "applied_deg": 0.0, "axis": [0.0, 0.0, 0.0], "root": root, "after": dict(before)}
    if angle < tolerance:
        return data, {}

    lo, hi = _mesh_bounds()
    pivot = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))
    rotation = Matrix.Translation(pivot) @ turn.to_matrix().to_4x4() @ Matrix.Translation(-pivot)
    # Top-level objects only: children follow their parents, touching both
    # would turn them twice (the same rule as normalize's scale).
    roots = [o for o in bpy.context.scene.objects if o.parent is None]
    for obj in roots:
        obj.matrix_world = rotation @ obj.matrix_world
    bpy.context.view_layer.update()
    lo, hi = _mesh_bounds()
    shift = Vector(((hi.x + lo.x) / -2, (hi.y + lo.y) / -2, -lo.z))
    for obj in roots:
        obj.matrix_world = Matrix.Translation(shift) @ obj.matrix_world
    bpy.context.view_layer.update()
    bpy.ops.object.select_all(action="SELECT")
    bpy.context.view_layer.objects.active = roots[0]
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    bpy.context.view_layer.update()

    after, _d, _h = _lean(arm)
    data.update(after=after, applied_deg=round(angle, 4),
                axis=[round(v, 6) for v in turn.axis], ground_shift_m=[round(v, 5) for v in shift])
    path = Path(args["out_dir"]) / Path(src).name
    bpy.ops.export_scene.gltf(filepath=str(path), export_format="GLB")
    return data, {"model": str(path)}


_common.main(posture_match)
