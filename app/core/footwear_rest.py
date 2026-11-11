"""The BARE figure's rest measurements, shipped inside ``foot_pose`` (``rest``).

Why (Task 20b, 2026-11-11): the served (assembled) model carries the body CUT
under the shoe, and the renderers' bind-pose measurements — the figure box
that anchors the figure and sets its height, and the rest soles the foot
stance rule of the clip transplant reads — skip garment subtrees but read
the cut body: on the measured material the lowest bind point sat 11.5 mm
above the bare soles and the Foot/ToeBase rest corrections 6.2° / 9.8° off
the bare file's. So the server measures BOTH on the bare file of the same
body when it writes ``foot_pose`` and ships them as ``foot_pose.rest``;
``@anima/scene-render`` uses them whenever the record matches the shoes a
figure carries (``figureBox`` / ``restCorrections`` with the record), no
renderer guesses anything, and without a ``foot_pose`` nothing changes.

The definitions are the TypeScript ones, repeated here so that both sides
produce the same numbers on the same bytes (``scripts/smoke_foot_rest.py``
and ``scripts/smoke_foot_rest.mjs`` pin that on one fixture):

* ``box`` = ``figureBox`` (``packages/scene-render/src/figure.ts``): the
  union over every mesh primitive that is NOT inside a garment node
  (``garment_*`` name or ``extras.garment``, the node or an ancestor) of the
  axis-aligned box of its RAW positions, transformed by the node's world
  matrix the way ``Box3.applyMatrix4`` does (the eight corners, then the
  box) — the frame of the glTF scene, i.e. the root the renderer loads.
* ``soles`` = ``restSolesOf`` (``clipRetarget.ts``): per side, over the
  vertices of every non-garment skinned primitive whose DOMINANT skin joint
  (the largest of the four weights, the first on a tie) is ``<side>foot`` or
  a ``<side>toe*`` joint (``norm_bone_name``) with a positive weight, the
  vertex position (bind, node world matrix applied) rotated into the ROOT
  BONE's rest frame — the inverse of the accumulated node rotations down to
  the first skin joint whose parent is no joint — the lowest one BEHIND the
  ankle (``z < Foot joint z``) is the heel, the lowest one AHEAD of the ball
  (``z > ToeBase joint z``) the toe. Joint positions come from the
  accumulated node TRS matrices, the frame from the accumulated node
  rotations alone, as ``restPoseOf`` walks them. A side without both joints
  or without both points is left out.

Coordinates are rounded to 1e-7 m (``footwear_fit._r``'s precision).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.core import glb_mesh
from app.core.rig_contract import norm_bone_name

SIDES = ("left", "right")


def _quat_mul(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Hamilton product of two (x, y, z, w) quaternions — three's ``Quaternion.multiply`` order (a · b)."""
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return np.array([aw * bx + ax * bw + ay * bz - az * by,
                     aw * by - ax * bz + ay * bw + az * bx,
                     aw * bz + ax * by - ay * bx + az * bw,
                     aw * bw - ax * bx - ay * by - az * bz], np.float64)


def _quat_of(node: dict) -> np.ndarray:
    """A node's local rotation as (x, y, z, w): ``rotation``, else the rotation part of ``matrix``
    (``Matrix4.decompose``'s rule: the columns scaled to unit length), else identity."""
    if "rotation" in node:
        q = np.asarray(node["rotation"], np.float64)
        return q / np.linalg.norm(q)
    if "matrix" in node:
        m = glb_mesh._local_matrix(node)[:3, :3].copy()
        for c in range(3):
            n = np.linalg.norm(m[:, c])
            if n > 0:
                m[:, c] /= n
        if np.linalg.det(m) < 0:
            m[:, 0] *= -1
        return _quat_from_matrix(m)
    return np.array([0.0, 0.0, 0.0, 1.0])


def _quat_from_matrix(m: np.ndarray) -> np.ndarray:
    """(x, y, z, w) of a rotation matrix (``Quaternion.setFromRotationMatrix``)."""
    t = m[0, 0] + m[1, 1] + m[2, 2]
    if t > 0:
        s = 0.5 / np.sqrt(t + 1.0)
        return np.array([(m[2, 1] - m[1, 2]) * s, (m[0, 2] - m[2, 0]) * s, (m[1, 0] - m[0, 1]) * s, 0.25 / s])
    if m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = 2.0 * np.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2])
        return np.array([0.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s, (m[2, 1] - m[1, 2]) / s])
    if m[1, 1] > m[2, 2]:
        s = 2.0 * np.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2])
        return np.array([(m[0, 1] + m[1, 0]) / s, 0.25 * s, (m[1, 2] + m[2, 1]) / s, (m[0, 2] - m[2, 0]) / s])
    s = 2.0 * np.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1])
    return np.array([(m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, 0.25 * s, (m[1, 0] - m[0, 1]) / s])


def _rotate(q: np.ndarray, v: np.ndarray) -> np.ndarray:
    """``v`` (…, 3) turned by the unit quaternion ``q`` (x, y, z, w) — ``Vector3.applyQuaternion``."""
    x, y, z, w = q
    qv = np.array([x, y, z])
    t = 2.0 * np.cross(qv, v)
    return v + w * t + np.cross(qv, t)


def _walk(gltf: dict) -> Tuple[Dict[int, np.ndarray], Dict[int, np.ndarray], Dict[int, int], Dict[int, bool]]:
    """World matrices (TRS accumulated), world rotations (rotations accumulated, no scale), parent index and
    the in-garment flag of every node reachable from scene 0 — the walk of ``restPoseOf`` / ``inGarment``."""
    nodes = gltf.get("nodes") or []
    scene = (gltf.get("scenes") or [{}])[int(gltf.get("scene", 0))]
    matrices: Dict[int, np.ndarray] = {}
    rotations: Dict[int, np.ndarray] = {}
    parents: Dict[int, int] = {}
    garment: Dict[int, bool] = {}

    def visit(i: int, above_m: np.ndarray, above_q: np.ndarray, above_g: bool, parent: int) -> None:
        node = nodes[i]
        matrices[i] = above_m @ glb_mesh._local_matrix(node)
        rotations[i] = _quat_mul(above_q, _quat_of(node))
        parents[i] = parent
        garment[i] = above_g or glb_mesh._is_garment_node(node)
        for child in node.get("children") or []:
            visit(int(child), matrices[i], rotations[i], garment[i], i)

    for root in scene.get("nodes") or []:
        visit(int(root), np.eye(4), np.array([0.0, 0.0, 0.0, 1.0]), False, -1)
    return matrices, rotations, parents, garment


def _box_corners(lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    return np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])


def _r(v: Any) -> Any:
    return [round(float(x), 7) + 0.0 for x in v]   # + 0.0: never a -0.0 in the payload


def rest_measurement(glb: bytes) -> Dict[str, Any]:
    """The ``rest`` block of ``foot_pose`` for the BARE file ``glb`` (module docstring):
    ``{"box": {"min": [x, y, z], "max": [x, y, z]}, "soles": {"left": {"heel": [x, y, z], "toe": [x, y, z]},
    "right": {…}}}`` — a side the body lacks is left out of ``soles``."""
    parsed = glb_mesh._parse(glb, "Body")
    gltf = parsed["gltf"]
    nodes = gltf.get("nodes") or []
    meshes = gltf.get("meshes") or []
    matrices, rotations, _parents, garment = _walk(gltf)

    # THE BOX: every non-garment mesh node, per primitive the raw AABB through the node's world matrix.
    lo = np.array([np.inf] * 3)
    hi = np.array([-np.inf] * 3)
    for i, node in enumerate(nodes):
        if i not in matrices or garment[i] or "mesh" not in node:
            continue
        for prim in meshes[node["mesh"]].get("primitives") or []:
            if "POSITION" not in prim.get("attributes", {}):
                continue
            pos = np.asarray(glb_mesh.accessor_array(parsed, prim["attributes"]["POSITION"]), np.float64)
            if not len(pos):
                continue
            corners = _box_corners(pos.min(0), pos.max(0))
            world = corners @ matrices[i][:3, :3].T + matrices[i][:3, 3]
            lo = np.minimum(lo, world.min(0))
            hi = np.maximum(hi, world.max(0))
    out: Dict[str, Any] = {"box": {"min": _r(lo), "max": _r(hi)}, "soles": {}}

    # THE SOLES: skin 0's joints, the root bone's frame, the dominant-joint vertices of the feet.
    skins = gltf.get("skins") or []
    if not skins:
        return out
    joints: List[int] = [int(j) for j in skins[0].get("joints") or []]
    joint_set = set(joints)
    names = [norm_bone_name(str(nodes[j].get("name", ""))) for j in joints]
    root_bone: Optional[int] = next((j for j in joints if _parents.get(j, -1) not in joint_set), None)
    if root_bone is None or root_bone not in rotations:
        return out
    inverse_root = rotations[root_bone] * np.array([-1.0, -1.0, -1.0, 1.0])
    position_of: Dict[str, np.ndarray] = {}
    for name, j in zip(names, joints):
        if j in matrices:
            position_of.setdefault(name, _rotate(inverse_root, matrices[j][:3, 3]))
    sides: Dict[str, Dict[str, Any]] = {}
    for side in SIDES:
        ankle = position_of.get(f"{side}foot")
        ball = position_of.get(f"{side}toebase")
        if ankle is None or ball is None:
            continue
        sides[side] = {"ankle_z": float(ankle[2]), "ball_z": float(ball[2]),
                       "heel": None, "toe": None, "heel_y": np.inf, "toe_y": np.inf}
    if not sides:
        return out
    owner_of = [next((s for s in sides if n == f"{s}foot" or n.startswith(f"{s}toe")), None) for n in names]
    for i, node in enumerate(nodes):
        if i not in matrices or garment[i] or "mesh" not in node or node.get("skin") != 0:
            continue
        for prim in meshes[node["mesh"]].get("primitives") or []:
            attrs = prim.get("attributes", {})
            if not {"POSITION", "JOINTS_0", "WEIGHTS_0"} <= set(attrs):
                continue
            pos = np.asarray(glb_mesh.accessor_array(parsed, attrs["POSITION"]), np.float64)
            jn = np.asarray(glb_mesh.accessor_array(parsed, attrs["JOINTS_0"]), np.int64)
            wt = np.asarray(glb_mesh.accessor_array(parsed, attrs["WEIGHTS_0"]), np.float64)
            if not len(pos):
                continue
            dominant = np.argmax(wt, axis=1)                       # the first of equal weights
            rows = np.arange(len(pos))
            weight = wt[rows, dominant]
            owner = np.array([owner_of[k] if 0 <= k < len(owner_of) else None for k in jn[rows, dominant]],
                             dtype=object)
            world = pos @ matrices[i][:3, :3].T + matrices[i][:3, 3]
            local = _rotate(inverse_root, world)
            for side, s in sides.items():
                mask = (owner == side) & (weight > 0)
                for key, cond in (("heel", local[:, 2] < s["ankle_z"]), ("toe", local[:, 2] > s["ball_z"])):
                    sel = np.flatnonzero(mask & cond)
                    if not len(sel):
                        continue
                    k = sel[np.argmin(local[sel, 1])]
                    if local[k, 1] < s[f"{key}_y"]:
                        s[f"{key}_y"] = float(local[k, 1])
                        s[key] = local[k]
    for side, s in sides.items():
        if s["heel"] is not None and s["toe"] is not None:
            out["soles"][side] = {"heel": _r(s["heel"]), "toe": _r(s["toe"])}
    return out
