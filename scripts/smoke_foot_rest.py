#!/usr/bin/env python3
"""Smoke: the BARE rest measurements shipped in ``foot_pose.rest`` (Task 20b).

Usage:  ./.venv/bin/python scripts/smoke_foot_rest.py            # check
        ./.venv/bin/python scripts/smoke_foot_rest.py --write    # (re)write the two fixture GLBs

Pure CPU: ``app.core.footwear_rest`` on two tiny GLBs built here (no server, no
world DB, no clip files). The TypeScript twin ``scripts/smoke_foot_rest.mjs``
reads the SAME fixtures and the SAME vector (``scripts/fixtures/foot_rest_vector.json``)
through ``figureBox`` / ``restSolesOf`` / ``restCorrections`` of
``@anima/scene-render`` — the two sides must give the same numbers, because
the server measures on the bare file what the renderers used to measure on
the loaded (cut) one.

THE FIXTURE (metres; ``scripts/fixtures/foot_rest_bare.glb``), hand-laid:
  Armature (identity) → Body (mesh, skin 0, identity) and the joints
  Hips (0, 0.9, 0) → LeftFoot (0.1, 0.08, 0) → LeftToeBase (0.1, 0.02, 0.13),
  and the mirror RightFoot / RightToeBase at x = −0.1; every joint rotation
  identity, inverse bind matrices = the inverse of the joint world matrices,
  so the rest pose IS the bind pose. The root bone frame is the world frame.
  Body vertices (position, dominant joint, weights):
    A  ( 0.1,  0.03,  −0.05)  LeftFoot 1          heel candidate (z < ankle z 0), the lowest
    B  ( 0.1,  0.04,  −0.08)  LeftFoot 1          heel candidate, higher
    C  ( 0.1,  0.0,    0.17)  LeftToeBase 1       toe candidate (z > ball z 0.13), the lowest
    D  ( 0.1,  0.02,   0.15)  LeftToeBase 1       toe candidate, higher
    E  ( 0.1, −0.005,  0.10)  LeftFoot 0.4 / LeftToeBase 0.6 → ToeBase; neither behind the ankle nor
                                                  ahead of the ball: NO sole point, but the box's floor
    A' (−0.1,  0.033, −0.05)  RightFoot 1         heel: the first of three equal-y candidates
    F  (−0.1,  0.033, −0.06)  RightFoot 1
    G  (−0.1,  0.033, −0.04)  RightFoot 1
    C' (−0.1,  0.0,    0.17)  RightToeBase 1      toe
    H  ( 0.0,  1.7,    0.05)  Hips 1              the crown
  A hair garment node ``garment_hair_h`` (extras.garment, skin 0) with (0, 1.8, 0) on Hips and
  (0.1, −0.03, −0.05) on LeftFoot: NEVER read (not in the box, not a sole).
EXPECTED (the vector's ``bare``):
  box  min (−0.1, −0.005, −0.08)  max (0.1, 1.7, 0.17)
  soles left  heel A (0.1, 0.03, −0.05)  toe C (0.1, 0, 0.17)
        right heel A' (−0.1, 0.033, −0.05) toe C' (−0.1, 0, 0.17)
  sole tilts (``footStance``, atan2(heel.y − toe.y, |toe.z − heel.z|)): left atan2(0.03, 0.22) =
  7.765166°, right atan2(0.033, 0.22) = 8.530766°, mean 8.147966° > 6° → the foot stance rule FIRES on
  the bare body (the TS smoke checks the corrections it produces).

THE CUT FIXTURE (``foot_rest_cut.glb``): the same file without A, C, E, A', C' (the body cut under the
shoe) and with the two shoe nodes ``garment_footwear_i_left`` / ``_right`` (extras.garment kind footwear,
item_id i, fsig abc; a vertex each under the sole on the Foot, skin 0). Measured on IT the numbers are
different — that is the finding:
  box  min (−0.1, 0.02, −0.08) (the floor 25 mm higher: D)  max (0.1, 1.7, 0.15)
  soles left heel B (0.1, 0.04, −0.08), toe D (0.1, 0.02, 0.15); right: heel F but NO toe → the side is
  left out (tilt left −4.97°; the pair incomplete → no stance correction at all).

CHECKS
  [1] the committed fixtures are byte-identical to this builder (``--write`` refreshes them);
  [2] ``rest_measurement(bare)`` equals the vector's ``bare`` to 1e-7 (sides, roles, every coordinate);
  [3] ``rest_measurement(cut)`` equals the vector's ``cut`` (box raised, right soles absent);
  [4] the writers ship it: ``garment_assembly._build`` measures ``rest_measurement(data)`` (the bare file
      it assembles) and ``garment_footwear`` the fit's ``rigged`` body — a text pin on the two call sites.
FAILS BEFORE / PASSES AFTER: on bf0c2f78 ``app.core.footwear_rest`` does not exist and neither writer
ships a ``rest`` block.
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

FIXTURES = REPO / "scripts" / "fixtures"
BARE = FIXTURES / "foot_rest_bare.glb"
CUT = FIXTURES / "foot_rest_cut.glb"
VECTOR = FIXTURES / "foot_rest_vector.json"

JOINTS = ["mixamorig:Hips", "mixamorig:LeftFoot", "mixamorig:LeftToeBase", "mixamorig:RightFoot",
          "mixamorig:RightToeBase"]
JOINT_WORLD = {"mixamorig:Hips": (0.0, 0.9, 0.0), "mixamorig:LeftFoot": (0.1, 0.08, 0.0),
               "mixamorig:LeftToeBase": (0.1, 0.02, 0.13), "mixamorig:RightFoot": (-0.1, 0.08, 0.0),
               "mixamorig:RightToeBase": (-0.1, 0.02, 0.13)}
PARENT = {"mixamorig:LeftFoot": "mixamorig:Hips", "mixamorig:LeftToeBase": "mixamorig:LeftFoot",
          "mixamorig:RightFoot": "mixamorig:Hips", "mixamorig:RightToeBase": "mixamorig:RightFoot"}

#: (name, position, {joint: weight})
BODY = [
    ("A", (0.1, 0.03, -0.05), {"mixamorig:LeftFoot": 1.0}),
    ("B", (0.1, 0.04, -0.08), {"mixamorig:LeftFoot": 1.0}),
    ("C", (0.1, 0.0, 0.17), {"mixamorig:LeftToeBase": 1.0}),
    ("D", (0.1, 0.02, 0.15), {"mixamorig:LeftToeBase": 1.0}),
    ("E", (0.1, -0.005, 0.10), {"mixamorig:LeftFoot": 0.4, "mixamorig:LeftToeBase": 0.6}),
    ("A'", (-0.1, 0.033, -0.05), {"mixamorig:RightFoot": 1.0}),
    ("F", (-0.1, 0.033, -0.06), {"mixamorig:RightFoot": 1.0}),
    ("G", (-0.1, 0.033, -0.04), {"mixamorig:RightFoot": 1.0}),
    ("C'", (-0.1, 0.0, 0.17), {"mixamorig:RightToeBase": 1.0}),
    ("H", (0.0, 1.7, 0.05), {"mixamorig:Hips": 1.0}),
]
CUT_AWAY = {"A", "C", "E", "A'", "C'"}
HAIR = [((0.0, 1.8, 0.0), {"mixamorig:Hips": 1.0}), ((0.1, -0.03, -0.05), {"mixamorig:LeftFoot": 1.0}),
        ((0.0, 1.75, 0.02), {"mixamorig:Hips": 1.0})]
SHOE = {"left": [((0.1, -0.03, -0.06), {"mixamorig:LeftFoot": 1.0}), ((0.1, -0.03, 0.16), {"mixamorig:LeftToeBase": 1.0}),
                 ((0.1, 0.05, 0.0), {"mixamorig:LeftFoot": 1.0})],
        "right": [((-0.1, -0.03, -0.06), {"mixamorig:RightFoot": 1.0}), ((-0.1, -0.03, 0.16), {"mixamorig:RightToeBase": 1.0}),
                  ((-0.1, 0.05, 0.0), {"mixamorig:RightFoot": 1.0})]}

_failures: list[str] = []
_checks = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global _checks
    _checks += 1
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        _failures.append(label)


def build(cut: bool) -> bytes:
    """The fixture GLB (module docstring): ``cut`` = without the cut-away vertices, with the shoe nodes."""
    from app.core import glb_mesh
    blob = bytearray()
    views: list[dict] = []
    accessors: list[dict] = []

    def add(array: np.ndarray, comp: int, typ: str, target: int | None = None, minmax: bool = False) -> int:
        data = np.ascontiguousarray(array).tobytes()
        while len(blob) % 4:
            blob.append(0)
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(data),
                      **({"target": target} if target else {})})
        blob.extend(data)
        acc = {"bufferView": len(views) - 1, "componentType": comp, "count": len(array), "type": typ}
        if minmax:
            acc["min"], acc["max"] = np.asarray(array).min(0).tolist(), np.asarray(array).max(0).tolist()
        accessors.append(acc)
        return len(accessors) - 1

    def primitive(verts: list) -> dict:
        pos = np.array([v[0] for v in verts], "<f4")
        jn = np.zeros((len(verts), 4), "<u2")
        wt = np.zeros((len(verts), 4), "<f4")
        for i, (_, weights) in enumerate(verts):
            for k, (joint, w) in enumerate(weights.items()):
                jn[i, k] = JOINTS.index(joint)
                wt[i, k] = w
        n = len(verts)
        faces = np.array([[i, (i + 1) % n, (i + 2) % n] for i in range(0, max(n - 2, 1))], "<u2") if n >= 3 \
            else np.array([[0, 0, 0]], "<u2")
        return {"attributes": {"POSITION": add(pos, 5126, "VEC3", 34962, True),
                               "JOINTS_0": add(jn, 5123, "VEC4", 34962),
                               "WEIGHTS_0": add(wt, 5126, "VEC4", 34962)},
                "indices": add(faces.reshape(-1), 5123, "SCALAR", 34963), "mode": 4}

    body = [(p, w) for name, p, w in BODY if not (cut and name in CUT_AWAY)]
    meshes = [{"name": "body", "primitives": [primitive(body)]},
              {"name": "garment_hair_h", "primitives": [primitive(HAIR)]}]
    nodes = [{"name": "Armature", "children": [1, 2, 3]},
             {"name": "Body", "mesh": 0, "skin": 0},
             {"name": "mixamorig:Hips", "translation": list(JOINT_WORLD["mixamorig:Hips"]), "children": [4, 6]},
             {"name": "garment_hair_h", "mesh": 1, "skin": 0, "extras": {"garment": {"kind": "hair", "item_id": "h", "fsig": "g"}}},
             {"name": "mixamorig:LeftFoot", "children": [5]},
             {"name": "mixamorig:LeftToeBase"},
             {"name": "mixamorig:RightFoot", "children": [7]},
             {"name": "mixamorig:RightToeBase"}]
    for name in JOINTS[1:]:
        node = next(n for n in nodes if n["name"] == name)
        node["translation"] = (np.array(JOINT_WORLD[name]) - np.array(JOINT_WORLD[PARENT[name]])).tolist()
    if cut:
        for side in ("left", "right"):
            meshes.append({"name": f"garment_footwear_i_{side}", "primitives": [primitive(SHOE[side])]})
            nodes[0]["children"].append(len(nodes))
            nodes.append({"name": f"garment_footwear_i_{side}", "mesh": len(meshes) - 1, "skin": 0,
                          "extras": {"garment": {"kind": "footwear", "item_id": "i", "fsig": "abc", "side": side}}})
    ibm = []
    for name in JOINTS:
        m = np.eye(4)
        m[:3, 3] = -np.array(JOINT_WORLD[name])          # the inverse of a pure translation
        ibm.append(m.T.astype("<f4"))                  # column-major
    ibm_acc = add(np.stack(ibm).reshape(len(JOINTS), 16), 5126, "MAT4")
    joint_index = [next(i for i, n in enumerate(nodes) if n["name"] == name) for name in JOINTS]
    while len(blob) % 4:
        blob.append(0)
    gltf = {"asset": {"version": "2.0", "generator": "scripts/smoke_foot_rest.py"}, "scene": 0,
            "scenes": [{"nodes": [0]}], "nodes": nodes, "meshes": meshes,
            "skins": [{"joints": joint_index, "inverseBindMatrices": ibm_acc, "skeleton": 2}],
            "bufferViews": views, "accessors": accessors, "buffers": [{"byteLength": len(blob)}]}
    return glb_mesh.pack_glb(gltf, bytes(blob))


def near(a, b, eps=1e-7) -> bool:
    return len(a) == len(b) and all(abs(float(x) - float(y)) <= eps for x, y in zip(a, b))


def same(measured: dict, expected: dict) -> tuple[bool, str]:
    if not near(measured["box"]["min"], expected["box"]["min"]) or not near(measured["box"]["max"], expected["box"]["max"]):
        return False, f"box {measured['box']} vs {expected['box']}"
    if set(measured["soles"]) != set(expected["soles"]):
        return False, f"sides {sorted(measured['soles'])} vs {sorted(expected['soles'])}"
    for side, s in expected["soles"].items():
        for role in ("heel", "toe"):
            if not near(measured["soles"][side][role], s[role]):
                return False, f"{side} {role} {measured['soles'][side][role]} vs {s[role]}"
    return True, ""


def main() -> int:
    from app.core.footwear_rest import rest_measurement
    write = "--write" in sys.argv[1:]
    bare, cut = build(False), build(True)
    if write:
        FIXTURES.mkdir(parents=True, exist_ok=True)
        BARE.write_bytes(bare)
        CUT.write_bytes(cut)
        print(f"wrote {BARE.name} ({len(bare)} B), {CUT.name} ({len(cut)} B)")
    vector = json.loads(VECTOR.read_text(encoding="utf-8"))

    print("[1] the committed fixtures are this builder's bytes")
    check("foot_rest_bare.glb", BARE.exists() and BARE.read_bytes() == bare)
    check("foot_rest_cut.glb", CUT.exists() and CUT.read_bytes() == cut)

    print("[2] the bare fixture measures as the vector says")
    measured = rest_measurement(bare)
    ok, why = same(measured, vector["bare"])
    check("box + soles == vector.bare (1e-7)", ok, why)
    check("float32 positions read back exactly (0.1 → 0.1000000)",
          abs(measured["soles"]["left"]["heel"][0] - struct.unpack("f", struct.pack("f", 0.1))[0]) <= 1e-7)

    print("[3] the cut fixture measures differently — the finding")
    measured_cut = rest_measurement(cut)
    ok, why = same(measured_cut, vector["cut"])
    check("box raised to D, right side without a toe → left out", ok, why)
    check("the floor differs by the vector's 25 mm",
          abs((measured_cut["box"]["min"][1] - measured["box"]["min"][1]) - 0.025) <= 1e-7)

    print("[4] the writers ship it")
    assembly = (REPO / "app/core/garment_assembly.py").read_text(encoding="utf-8")
    fit = (REPO / "app/core/garment_footwear.py").read_text(encoding="utf-8")
    check("garment_assembly._build: rest_measurement(data)", '"rest": rest_measurement(data)' in assembly)
    check("garment_footwear fit record: rest_measurement(rigged)", "footwear_rest.rest_measurement(rigged)" in fit)

    print()
    if _failures:
        print(f"FAIL: {len(_failures)} of {_checks} checks failed")
        return 1
    print(f"OK: {_checks} checks passed — the bare rest is measured on the bare file and shipped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
