#!/usr/bin/env python3
"""A boot's collar height on an outfit body rides the side's Leg joint, resolved by NAME (review 07b#1).

Usage:
    ./.venv/bin/python scripts/smoke_footwear_derive_collar.py

Runs on ``shared/models/rig/puppet.glb`` (read-only) in memory — no storage, no world, no server.

``garment_footwear.derive_compute`` carries the base fit's ``split.collar_bind_m`` onto a body shape through the
Leg joint's ``J_shape · J_base^-1`` (``moved``). It used to pick that joint as ``shaft.joint_names[2]`` — slot 2 of
``footwear_fit.fit_pair``'s 4-joint list ``[Foot, ToeBase, Leg, UpLeg]``. But derive reads the shaft part back from
the base fit GLB, and ``glb_mesh.graft`` writes the part on the body's skin 0: read back, its ``joint_names`` are
the body's WHOLE joint list, in the rig contract's order (``shared/models/rig/joints.json``: Hips, Spine, Spine1,
...) — slot 2 is ``mixamorig:Spine1``. Now ``garment_footwear.derived_collar_bind`` takes the joint
``norm_bone_name(f"{side}Leg")``.

[1] The grafted order. A 4-joint shaft part ``[LeftFoot, LeftToeBase, LeftLeg, LeftUpLeg]`` (puppet spelling)
    grafted into puppet.glb and read back with ``garment_arrays(..., exact=True)`` (as derive does): slot 2 of the
    fit_pair list is ``mixamorig:LeftLeg``, slot 2 of the read-back list is ``mixamorig:Spine1`` (joints.json
    index 2), and the read-back list is the body's whole skin.
[2] The mapping, by hand. Jb = puppet's bind frames; collar c = the side's Leg joint height L_y − 0.20 (20 cm under
    the knee). ``moved`` (world transforms):
    - Spine1: translation +0.10 in y;
    - LeftLeg: translation +0.03 in y -> left collar = c + 0.03 exactly (a translation moves every point alike);
    - RightLeg: rotation by 10 deg about the z axis through the right Leg joint R -> the collar point
      (R_x, c, R_z) is (0, c − R_y, 0) from R; rotated about z its y offset is (c − R_y) cos 10 deg, so the right
      collar = R_y + (c − R_y) cos 10 deg = R_y − 0.20 · 0.984808 = R_y − 0.196962.
    The old slot-2 rule on the read-back list maps BOTH sides through Spine1: c + 0.10 — wrong on the left (+0.07
    too high) and on the right (+0.10 instead of the rotation's +0.003038), which [3] shows by running the old
    expression inline.
[3] Old rule, inline: ``norm_bone_name(read_back.joint_names[2])`` is "spine1" -> collar c + 0.10 on both sides,
    and with Spine1 NOT moved (only the legs) it left both collars unchanged (c) — the leg's move lost.
[4] A body lacking the side's Leg in ``moved`` keeps the collar unchanged (the guard).
"""
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from app.core import glb_mesh  # noqa: E402
from app.core.footwear_fit import _apply  # noqa: E402
from app.core.garment_footwear import derived_collar_bind  # noqa: E402
from app.core.rig_contract import norm_bone_name  # noqa: E402

FAILS = []


def check(label, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + label + (f" — {detail}" if detail else ""))
    if not ok:
        FAILS.append(label)


blob = (ROOT / "shared/models/rig/puppet.glb").read_bytes()
body = glb_mesh.body_arrays(blob)
names = list(body.joint_names)
by_key = {norm_bone_name(n): n for n in names}

# --- [1] the grafted order ------------------------------------------------------------------------------------------
fit_pair_names = [by_key["leftfoot"], by_key["lefttoebase"], by_key["leftleg"], by_key["leftupleg"]]
P = np.array([[0.0, 0.0, 0.0], [0.01, 0.0, 0.0], [0.0, 0.01, 0.0]])
part = glb_mesh.GarmentMesh(positions=P, normals=None, uvs=np.zeros((3, 2)), indices=np.array([[0, 1, 2]]),
                            joints=np.tile(np.array([0, 1, 2, 3]), (3, 1)),
                            weights=np.tile(np.array([0.0, 0.0, 1.0, 0.0]), (3, 1)),
                            joint_names=fit_pair_names, image=b"", mime="", material={})
node = "garment_footwear_x_left_shaft"
grafted = glb_mesh.graft(blob, part, name=node, extras={})
back = glb_mesh.garment_arrays(grafted, node_prefix=node, exact=True)
check("[1] fit_pair slot 2 is the LeftLeg", fit_pair_names[2] == "mixamorig:LeftLeg", fit_pair_names[2])
check("[1] read back, slot 2 is Spine1 and the list is the body's whole skin",
      back.joint_names[2] == "mixamorig:Spine1" and list(back.joint_names) == names,
      f"{back.joint_names[2]}, {len(back.joint_names)} of {len(names)}")

# --- [2] the mapping, by hand ---------------------------------------------------------------------------------------
Jb = glb_mesh.joint_bind_matrices(blob)


def translate(dy):
    T = np.eye(4)
    T[1, 3] = dy
    return T


def rot_z_about(point, deg):
    a = math.radians(deg)
    R = np.eye(4)
    R[:2, :2] = [[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]]
    To, Tb = np.eye(4), np.eye(4)
    To[:3, 3], Tb[:3, 3] = point, -np.asarray(point)
    return To @ R @ Tb


Ly, Ry = float(Jb["leftleg"][1, 3]), float(Jb["rightleg"][1, 3])
cL, cR = Ly - 0.20, Ry - 0.20
moved = {k: np.eye(4) for k in Jb}
moved["spine1"] = translate(0.10)
moved["leftleg"] = translate(0.03)
moved["rightleg"] = rot_z_about(Jb["rightleg"][:3, 3], 10.0)
want_L, want_R = cL + 0.03, Ry - 0.20 * math.cos(math.radians(10.0))
got_L = derived_collar_bind("left", cL, Jb, moved)
got_R = derived_collar_bind("right", cR, Jb, moved)
check("[2] left collar = c + 0.03 (the LeftLeg's translation)", abs(got_L - want_L) < 1e-9, f"{got_L} vs {want_L}")
check("[2] right collar = R_y - 0.196962 (10 deg about the RightLeg)",
      abs(got_R - want_R) < 1e-9 and abs((want_R - Ry) + 0.196962) < 1e-6, f"{got_R} vs {want_R}")


# --- [3] the old rule, inline ---------------------------------------------------------------------------------------
def old_rule(collar, joint_names, moved_):
    leg = norm_bone_name(joint_names[2]) if len(joint_names) > 2 else ""
    if leg in moved_:
        p = np.array([Jb[leg][0, 3], float(collar), Jb[leg][2, 3]])
        return float(_apply(moved_[leg], p)[1])
    return float(collar)


old_L, old_R = old_rule(cL, back.joint_names, moved), old_rule(cR, back.joint_names, moved)
check("[3] old rule reads Spine1: both collars + 0.10, the new ones differ",
      abs(old_L - (cL + 0.10)) < 1e-9 and abs(old_R - (cR + 0.10)) < 1e-9
      and abs(old_L - got_L) > 0.05 and abs(old_R - got_R) > 0.05, f"{old_L - cL:+.6f} / {old_R - cR:+.6f}")
legs_only = dict(moved, spine1=np.eye(4))
check("[3] old rule with only the legs moved: collars unchanged (the move lost); new rule moves them",
      old_rule(cL, back.joint_names, legs_only) == cL
      and abs(derived_collar_bind("left", cL, Jb, legs_only) - want_L) < 1e-9)

# --- [4] the guard --------------------------------------------------------------------------------------------------
no_leg = {k: v for k, v in moved.items() if k != "leftleg"}
check("[4] no LeftLeg in moved: the collar unchanged", derived_collar_bind("left", cL, Jb, no_leg) == cL)

print(f"\n{len(FAILS)} failed" if FAILS else "\nall passed")
sys.exit(1 if FAILS else 0)
