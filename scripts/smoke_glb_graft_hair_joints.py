#!/usr/bin/env python3
"""HairDeck spring-chain joints through the graft, the assembly path and the validator (``glb_mesh.graft`` /
``garment_arrays`` / ``GarmentMesh.joint_binds``, ``rig_contract.HAIR_CHAIN_JOINT_RE`` / ``hair_chain_parent``,
``model_validate.validate_glb``) — plan 2026-11-12-hairdeck-spring-chains, Task 4. Expectations by hand.

Usage: ./.venv/bin/python scripts/smoke_glb_graft_hair_joints.py

No world, no server, no hub (a throwaway storage dir for the one ``fit_hairdeck`` call in [6]).

Fixture body (built here, in the style of ``smoke_glb_graft.py::body_fixture``): every base joint of
``shared/models/rig/joints.json`` as ``mixamorig:<name>``; ``pack=True`` inserts the extension bone ``breast_L``
(parent Spine2) after Neck, so Head's skin index moves up by one. Node 0 ``Armature`` (children Body, Hips), node 1
``Body`` (skin 0, identity TRS), then the joints in skin order; Hips at the origin with every other base joint as
its direct child (identity TRS) — except Head: translation (0, 1.5, 0), rotation 90 deg about y (quaternion
(0, s, 0, s), s = sqrt(0.5)). Inverse bind matrices = inv(world) per joint (identity except Head's). Head's world =
T(0, 1.5, 0) R_y(90). One 256 px PNG base colour (the validator wants a real embedded texture).

Hair garment: joint names [mixamorig:Head, HairGen_c00_00, HairGen_c00_01, HairGen_c00_end] (``_end`` unweighted),
rows v0 Head 0.5 / _00 0.5, v1 Head 0.4 / _01 0.6, v2 Head 1, v3 _00 0.5 / _01 0.5; ``joint_binds`` = identity
rotation at (0, 1.6, -0.1), (0, 1.5, -0.12), (0, 1.4, -0.12) for _00 / _01 / _end; ``joint_parents`` _00 -> Head,
_01 -> _00, _end -> _01 (what ``fit_hairdeck`` emits).

[1] After ``graft`` onto the bare body (no pack): three new nodes _00, _01, _end, in that order (parents first);
    Head's children = [_00], _00's = [_01], _01's = [_end].
    - _00 local = inv(world(Head)) * bind: translation R_y(-90) (0, 1.6 - 1.5, -0.1 - 0) = R_y(-90) (0, 0.1, -0.1)
      = (0.1, 0.1, 0.0) +- 1e-6 (R_y(-90) maps (x, y, z) -> (-z, y, x)), rotation R_y(-90) = quaternion
      (0, -s, 0, s); _00's world rotation is then identity, so _01 local = (0, 1.5 - 1.6, -0.12 + 0.1) =
      (0, -0.1, -0.02) with identity rotation, _end local = (0, -0.1, 0).
    - The world of each new node from the node chain equals its bind (1e-6).
    - ``skins[0].joints`` = the old list + [_00, _01, _end]; ``inverseBindMatrices`` names a NEW accessor whose
      first rows are the old matrices byte for byte and whose last three are inv(bind) (1e-6, float32); every old
      accessor (JSON and bytes) and bufferView is unchanged, and the old nodes are unchanged except Head (+ child)
      and Armature (+ the garment node).
    - JOINTS_0: v0 [Head, _00], v1 [Head, _01], v3 [_00, _01] with _00 / _01 at the old joint count + 0 / + 1;
      weights unchanged.
[2] ``validate_glb(blob, extension_names={})``: ok, rig ``mixamo`` (the bare body too). The same file with _01
    re-parented to Head: ``wrong parent for HairGen_c00_01: expected HairGen_c00_00, got mixamorig:Head``. A
    joint ``Foo`` under Head: ``undeclared joints: Foo``. ``hair_chain_parent``: _00 -> mixamorig:Head, _07 -> _06,
    _end -> the highest _KK present (c03 with _00, _02 -> _02; none -> None), "Foo" -> None.
[3] A pack tip joint the target lacks still folds onto its ancestor — BASE ``54cea23e``'s behaviour, asserted against
    the BASE module: garment [Head, breast_L_tip] weighted to the tip, joint_parents tip -> breast_L, onto the pack
    body: the tip's influence lands on breast_L's index (5, right after Neck 4), no node besides the garment's is
    added, and the bytes equal BASE's graft. The hair garment WITHOUT joint_binds folds its chain joints onto Head
    exactly as BASE does (bytes equal).
[4] Round trip = the assembly path of both tiers (``garment_assembly`` reads ``garment_arrays`` of the tier's fit
    and grafts it onto that tier's bare file): ``garment_arrays([1])`` carries joint_binds for the three names
    (= the binds, 1e-6); grafted onto the PACK body (other skin indices) it appends the same three joints with the
    same parents, local TRS and world positions as [1] (1e-6) and validates with breast_L declared. Grafting it
    once more onto that result (a second garment on a file that already has the joints) adds no node, keeps the
    skin length and remaps the second garment's influences onto the existing joints (never duplicated).
[5] Fails on the old code: BASE ``54cea23e``'s graft of the hair garment adds no HairGen node and folds _01's
    weight onto Head (v1's JOINTS_0 [Head, Head]) — printed.
[6] ``fit_hairdeck`` (smoke_hair_chains_bind's fixture + its T2 chains file) sets ``garment.joint_binds`` for every
    chain joint it names in ``joint_parents``; grafted onto the fit body, each appended joint's world translation
    equals its bind (1e-6).
Ruling H11: every fit here runs with ``swing=True`` — Swing is a fit input and only a Swing-on fit binds the
chains (with Swing off the garment is today's skin, smoke_hair_chains_bind.py).
"""
import copy
import importlib.util
import json
import math
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402

BASE_COMMIT = "54cea23e"
FAILS = []
S = math.sqrt(0.5)
CHAIN = ["HairGen_c00_00", "HairGen_c00_01", "HairGen_c00_end"]
JOINTS = {"HairGen_c00_00": (0, 1.6, -0.1), "HairGen_c00_01": (0, 1.5, -0.12), "HairGen_c00_end": (0, 1.4, -0.12)}
EXTRAS = {"kind": "hair", "item_id": "hair_demo", "fsig": "0123456789ab"}
NAME = "garment_hair_hair_demo"
PACK_EXT = {"breast_L": {"parent": "mixamorig:Spine2", "group": "chest"}}


def check(cond, label):
    print(("OK   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


def pack(doc, blob):
    blob = bytes(blob) + b"\0" * (-len(blob) % 4)
    doc["buffers"] = [{"byteLength": len(blob)}]
    raw = json.dumps(doc).encode()
    raw += b" " * (-len(raw) % 4)
    body = struct.pack("<II", len(raw), 0x4E4F534A) + raw + struct.pack("<II", len(blob), 0x004E4942) + blob
    return b"glTF" + struct.pack("<II", 2, 12 + len(body)) + body


def texture():
    """A 256 px PNG base colour (the validator refuses a model without a real embedded texture)."""
    import io
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (256, 256), (200, 160, 140)).save(out, "PNG")
    return out.getvalue()


def head_world():
    M = np.eye(4)
    M[:3, :3] = [[0, 0, 1], [0, 1, 0], [-1, 0, 0]]          # R_y(+90): (x, y, z) -> (z, y, -x)
    M[:3, 3] = (0, 1.5, 0)
    return M


def body_fixture(pack_bone=False):
    from app.core.rig_contract import BASE_JOINT_NAMES
    names = ["mixamorig:" + n for n in BASE_JOINT_NAMES]
    if pack_bone:
        names.insert(names.index("mixamorig:Neck") + 1, "breast_L")
    jidx = {n: 2 + i for i, n in enumerate(names)}
    nodes = [{"name": "Armature", "children": [1, 2]}, {"name": "Body", "mesh": 0, "skin": 0}]
    joints = [{"name": n} for n in names]
    joints[0]["children"] = [jidx[n] for n in names[1:] if n != "breast_L"]
    head = joints[names.index("mixamorig:Head")]
    head["translation"], head["rotation"] = [0, 1.5, 0], [0, S, 0, S]
    if pack_bone:
        joints[names.index("mixamorig:Spine2")]["children"] = [jidx["breast_L"]]
    nodes += joints
    sk = {n: i for i, n in enumerate(names)}
    ibm = np.tile(np.eye(4), (len(names), 1, 1))
    ibm[sk["mixamorig:Head"]] = np.linalg.inv(head_world())
    P = np.array([[0, 1.3, 0], [0.1, 1.3, 0], [0, 1.4, 0], [0, 1.5, 0], [0.1, 1.5, 0], [0, 1.6, 0]], "<f4")
    J = np.array([[sk["mixamorig:Spine2"], 0, 0, 0]] * 3 + [[sk["mixamorig:Head"], 0, 0, 0]] * 3, "<u2")
    W = np.array([[1, 0, 0, 0]] * 6, "<f4")
    I = np.array([0, 1, 2, 3, 4, 5], "<u4")
    blob = bytearray()
    views, accs = [], []

    def add(arr, ctype, typ, target=None, minmax=False):
        raw = arr.tobytes()
        blob.extend(b"\0" * (-len(blob) % 4))
        view = {"buffer": 0, "byteOffset": len(blob), "byteLength": len(raw)}
        if target:
            view["target"] = target
        views.append(view)
        blob.extend(raw)
        count = {"MAT4": len(arr) // 16, "SCALAR": arr.size}.get(typ, len(arr))
        a = {"bufferView": len(views) - 1, "componentType": ctype, "count": count, "type": typ}
        if minmax:
            a["min"], a["max"] = arr.min(0).tolist(), arr.max(0).tolist()
        accs.append(a)
        return len(accs) - 1
    attrs = {"POSITION": add(P, 5126, "VEC3", 34962, True), "JOINTS_0": add(J, 5123, "VEC4", 34962),
             "WEIGHTS_0": add(W, 5126, "VEC4", 34962)}
    ind = add(I, 5125, "SCALAR", 34963)
    ibm_acc = add(np.ascontiguousarray(ibm.transpose(0, 2, 1).reshape(-1), "<f4"), 5126, "MAT4")
    png = texture()
    blob.extend(b"\0" * (-len(blob) % 4))
    views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(png)})
    blob.extend(png)
    doc = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}], "nodes": nodes,
           "meshes": [{"name": "Body", "primitives": [{"attributes": attrs, "indices": ind, "material": 0}]}],
           "skins": [{"joints": [jidx[n] for n in names], "inverseBindMatrices": ibm_acc}],
           "accessors": accs, "bufferViews": views,
           "images": [{"bufferView": len(views) - 1, "mimeType": "image/png"}], "textures": [{"source": 0}],
           "materials": [{"name": "Skin", "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}]}
    return pack(doc, blob), names


def binds():
    out = {}
    for n, p in JOINTS.items():
        M = np.eye(4)
        M[:3, 3] = p
        out[n] = M
    return out


def hair_garment(with_binds=True):
    from app.core.glb_mesh import GarmentMesh
    g = GarmentMesh(
        positions=np.array([[0, 1.6, -0.11], [0.02, 1.5, -0.13], [0, 1.65, 0.05], [0.01, 1.55, -0.12]]),
        normals=None, uvs=np.zeros((4, 2)), indices=np.array([[0, 1, 2], [0, 3, 1]]),
        joints=np.array([[0, 1, 0, 0], [0, 2, 0, 0], [0, 0, 0, 0], [1, 2, 0, 0]]),
        weights=np.array([[0.5, 0.5, 0, 0], [0.4, 0.6, 0, 0], [1, 0, 0, 0], [0.5, 0.5, 0, 0]]),
        joint_names=["mixamorig:Head"] + CHAIN, material={"name": "hair"},
        joint_parents={"HairGen_c00_00": "mixamorig:Head", "HairGen_c00_01": "HairGen_c00_00",
                       "HairGen_c00_end": "HairGen_c00_01"})
    g.joint_binds = binds() if with_binds else {}      # set after construction: the old dataclass lacks the field
    return g


def load_base(tmp: Path):
    src = subprocess.run(["git", "-C", str(ROOT), "show", f"{BASE_COMMIT}:app/core/glb_mesh.py"],
                         check=True, capture_output=True, text=True).stdout
    path = tmp / "glb_mesh_base.py"
    path.write_text(src)
    spec = importlib.util.spec_from_file_location("glb_mesh_base", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["glb_mesh_base"] = mod
    spec.loader.exec_module(mod)
    return mod


def node_index(gltf, name):
    return next(i for i, n in enumerate(gltf["nodes"]) if n.get("name") == name)


def view_bytes(parsed, accessor_index):
    gltf = parsed["gltf"]
    v = gltf["bufferViews"][gltf["accessors"][accessor_index]["bufferView"]]
    s = v.get("byteOffset", 0)
    return bytes(parsed["bin"][s:s + v["byteLength"]])


def garment_joints(gm, parsed, name):
    gltf = parsed["gltf"]
    node = gltf["nodes"][node_index(gltf, name)]
    prim = gltf["meshes"][node["mesh"]]["primitives"][0]
    return (gm.accessor_array(parsed, prim["attributes"]["JOINTS_0"]).astype(int),
            np.asarray(gm.accessor_array(parsed, prim["attributes"]["WEIGHTS_0"]), np.float64))


def chain_state(gm, parsed):
    """Per chain joint: (parent name, local translation, local rotation, world)."""
    gltf = parsed["gltf"]
    nodes = gltf["nodes"]
    parent = {c: i for i, n in enumerate(nodes) for c in n.get("children") or []}
    out = {}
    for name in CHAIN:
        i = node_index(gltf, name)
        out[name] = (nodes[parent[i]]["name"], np.asarray(nodes[i].get("translation", (0, 0, 0)), np.float64),
                     np.asarray(nodes[i].get("rotation", (0, 0, 0, 1)), np.float64), gm._world_matrix(nodes, i))
    return out


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="graft-hair-joints-") as tmp:
        from app.core import paths
        paths.init(Path(tmp) / "world")
        from app.core import glb_mesh as gm
        from app.core.model_validate import parse_glb, validate_glb
        base = load_base(Path(tmp))
        B = binds()

        # [1]
        print("[1] graft appends the chain joints")
        bare, names = body_fixture()
        n_old = len(names)
        head = names.index("mixamorig:Head")
        try:
            blob = gm.graft(bare, hair_garment(), name=NAME, extras=EXTRAS)
        except Exception as e:          # noqa: BLE001 — the old code raises nothing, but report anything
            print(f"FAIL graft raised {type(e).__name__}: {e}")
            return 1
        pb, pg = parse_glb(bare), parse_glb(blob)
        jb, jg = pb["gltf"], pg["gltf"]
        new = [n["name"] for n in jg["nodes"][len(jb["nodes"]):]]
        if "HairGen_c00_00" not in new:
            print("FAIL no node HairGen_c00_00")
            FAILS.append("no node HairGen_c00_00")
        else:
            check(new == CHAIN + [NAME], f"new nodes {new} == {CHAIN + [NAME]}")
            idx = {n: node_index(jg, n) for n in CHAIN}
            head_node = jg["skins"][0]["joints"][head]
            check(jg["nodes"][head_node].get("children") == [idx["HairGen_c00_00"]]
                  and jg["nodes"][idx["HairGen_c00_00"]].get("children") == [idx["HairGen_c00_01"]]
                  and jg["nodes"][idx["HairGen_c00_01"]].get("children") == [idx["HairGen_c00_end"]]
                  and not jg["nodes"][idx["HairGen_c00_end"]].get("children"),
                  "hierarchy Head -> _00 -> _01 -> _end")
            st = chain_state(gm, pg)
            t00, q00 = st["HairGen_c00_00"][1], st["HairGen_c00_00"][2]
            check(np.abs(t00 - [0.1, 0.1, 0.0]).max() < 1e-6, f"_00 local translation {t00.round(9).tolist()}")
            check(np.abs(q00 - [0, -S, 0, S]).max() < 1e-6, f"_00 local rotation {q00.round(9).tolist()} = R_y(-90)")
            check(np.abs(st["HairGen_c00_01"][1] - [0, -0.1, -0.02]).max() < 1e-6
                  and np.abs(st["HairGen_c00_01"][2] - [0, 0, 0, 1]).max() < 1e-6
                  and np.abs(st["HairGen_c00_end"][1] - [0, -0.1, 0]).max() < 1e-6,
                  f"_01 local {st['HairGen_c00_01'][1].round(9).tolist()}, _end local "
                  f"{st['HairGen_c00_end'][1].round(9).tolist()}")
            check(all(np.abs(st[n][3] - B[n]).max() < 1e-6 for n in CHAIN), "world from the node chain = bind")
            check(all("scale" not in jg["nodes"][idx[n]] for n in CHAIN), "no scale written (unit worlds)")
            skin_b, skin_g = jb["skins"][0], jg["skins"][0]
            check(skin_g["joints"] == skin_b["joints"] + [idx[n] for n in CHAIN],
                  "skins[0].joints = old + [_00, _01, _end]")
            check(skin_g["inverseBindMatrices"] == len(jb["accessors"]) and
                  jg["accessors"][skin_g["inverseBindMatrices"]]["count"] == n_old + 3,
                  f"a NEW inverse-bind accessor of {n_old + 3} matrices")
            new_ibm = gm.mat4_array(pg, skin_g["inverseBindMatrices"])
            old_raw = view_bytes(pb, skin_b["inverseBindMatrices"])
            check(view_bytes(pg, skin_g["inverseBindMatrices"])[:len(old_raw)] == old_raw,
                  "old IBM rows byte-identical in the new accessor")
            check(all(np.abs(new_ibm[n_old + k] - np.linalg.inv(B[n])).max() < 1e-6 for k, n in enumerate(CHAIN)),
                  "new IBM rows = inv(bind)")
            check(jg["accessors"][:len(jb["accessors"])] == jb["accessors"]
                  and jg["bufferViews"][:len(jb["bufferViews"])] == jb["bufferViews"]
                  and all(view_bytes(pb, i) == view_bytes(pg, i) for i in range(len(jb["accessors"]))),
                  "every old accessor (JSON + bytes) and bufferView unchanged")
            changed = [i for i in range(len(jb["nodes"])) if jg["nodes"][i] != jb["nodes"][i]]
            check(changed == [0, head_node], f"old nodes changed: {changed} == [Armature 0, Head {head_node}]")
            J, W = garment_joints(gm, pg, NAME)
            c0, c1 = n_old, n_old + 1
            check(J[0, :2].tolist() == [head, c0] and J[1, :2].tolist() == [head, c1]
                  and J[3, :2].tolist() == [c0, c1] and J[2, 0] == head,
                  f"JOINTS_0 rows {J[:, :2].tolist()} (Head {head}, _00 {c0}, _01 {c1})")
            check(np.allclose(W, hair_garment().weights, atol=1e-7), "weights unchanged")

            # [2]
            print("[2] validator")
            from app.core.rig_contract import HAIR_CHAIN_JOINT_RE, hair_chain_parent
            check(validate_glb(bare, extension_names={})["ok"], "bare fixture validates")
            v = validate_glb(blob, extension_names={})
            check(v["ok"] and v["rig"] == "mixamo", f"grafted: ok {v['ok']}, rig {v['rig']}, errors {v['errors']}")
            doc = copy.deepcopy(jg)
            doc["nodes"][idx["HairGen_c00_00"]]["children"] = []
            doc["nodes"][head_node]["children"].append(idx["HairGen_c00_01"])
            v = validate_glb(gm.pack_glb(doc, bytes(pg["bin"])), extension_names={})
            check(not v["ok"] and "wrong parent for HairGen_c00_01: expected HairGen_c00_00, got mixamorig:Head"
                  in v["errors"], f"re-parented _01: {v['errors']}")
            doc = copy.deepcopy(jg)
            doc["nodes"].append({"name": "Foo"})
            doc["nodes"][head_node]["children"].append(len(doc["nodes"]) - 1)
            doc["skins"][0]["joints"].append(len(doc["nodes"]) - 1)
            v = validate_glb(gm.pack_glb(doc, bytes(pg["bin"])), extension_names={})
            check(not v["ok"] and "undeclared joints: Foo" in v["errors"], f"Foo: {v['errors']}")
            check(hair_chain_parent("HairGen_c00_00", []) == "mixamorig:Head"
                  and hair_chain_parent("HairGen_c12_07", []) == "HairGen_c12_06"
                  and hair_chain_parent("HairGen_c03_end", ["HairGen_c03_00", "HairGen_c03_02", "HairGen_c04_05"])
                  == "HairGen_c03_02"
                  and hair_chain_parent("HairGen_c03_end", ["HairGen_c04_00"]) is None
                  and hair_chain_parent("Foo", CHAIN) is None
                  and HAIR_CHAIN_JOINT_RE.match("HairGen_c00_end") and not HAIR_CHAIN_JOINT_RE.match("HairGen_c0_00"),
                  "hair_chain_parent / HAIR_CHAIN_JOINT_RE by hand")

            # [4]
            print("[4] round trip = the assembly path (both tiers)")
            mesh = gm.garment_arrays(blob)
            check(sorted(mesh.joint_binds) == sorted(CHAIN)
                  and all(np.abs(mesh.joint_binds[n] - B[n]).max() < 1e-6 for n in CHAIN),
                  f"garment_arrays reads joint_binds {sorted(mesh.joint_binds)}")
            target2, names2 = body_fixture(pack_bone=True)
            blob2 = gm.graft(target2, mesh, name=NAME, extras=EXTRAS)
            p2 = parse_glb(blob2)
            st2 = chain_state(gm, p2)
            check(all(st2[n][0] == st[n][0] and np.abs(st2[n][1] - st[n][1]).max() < 1e-6
                      and np.abs(st2[n][2] - st[n][2]).max() < 1e-6 and np.abs(st2[n][3] - st[n][3]).max() < 1e-6
                      for n in CHAIN), "pack body: same parents, local TRS and worlds as [1]")
            skin2 = p2["gltf"]["skins"][0]["joints"]
            check([p2["gltf"]["nodes"][j]["name"] for j in skin2[len(names2):]] == CHAIN,
                  f"pack body: appended after its {len(names2)} joints")
            v = validate_glb(blob2, extension_names=PACK_EXT)
            check(v["ok"], f"pack body graft validates with breast_L declared ({v['errors']})")
            blob3 = gm.graft(blob2, gm.garment_arrays(blob2), name="garment_hair_second", extras=EXTRAS)
            p3 = parse_glb(blob3)
            hair_nodes = [n["name"] for n in p3["gltf"]["nodes"] if HAIR_CHAIN_JOINT_RE.match(n.get("name", ""))]
            J3, _ = garment_joints(gm, p3, "garment_hair_second")
            J2, _ = garment_joints(gm, p2, NAME)
            check(sorted(hair_nodes) == sorted(CHAIN) and p3["gltf"]["skins"][0]["joints"] == skin2
                  and np.array_equal(J3, J2) and validate_glb(blob3, extension_names=PACK_EXT)["ok"],
                  "joints already present: remapped, never duplicated")

        # [3]
        print(f"[3] other extension joints still fold ({BASE_COMMIT} behaviour)")
        from app.core.glb_mesh import GarmentMesh
        target_p, names_p = body_fixture(pack_bone=True)
        tip = GarmentMesh(positions=np.array([[0.05, 1.3, 0.1], [0.1, 1.3, 0.1], [0.05, 1.35, 0.1]]), normals=None,
                          uvs=np.zeros((3, 2)), indices=np.array([[0, 1, 2]]),
                          joints=np.array([[0, 1, 0, 0]] * 3), weights=np.array([[0.3, 0.7, 0, 0]] * 3),
                          joint_names=["mixamorig:Head", "breast_L_tip"], material={"name": "top"},
                          joint_parents={"breast_L_tip": "breast_L"})
        new_t = gm.graft(target_p, tip, name="garment_clothing_top", extras=EXTRAS)
        old_t = base.graft(target_p, tip, name="garment_clothing_top", extras=EXTRAS)
        pt = parse_glb(new_t)
        Jt, _ = garment_joints(gm, pt, "garment_clothing_top")
        check(Jt[0, 1] == names_p.index("breast_L") == 5 and len(pt["gltf"]["nodes"]) == len(names_p) + 3
              and new_t == old_t,
              f"pack tip folds onto breast_L ({Jt[0, 1]}), one node added, bytes == {BASE_COMMIT}")
        no_binds = hair_garment(with_binds=False)
        check(gm.graft(bare, no_binds, name=NAME, extras=EXTRAS) == base.graft(bare, no_binds, name=NAME,
                                                                                extras=EXTRAS),
              f"hair chain joints without joint_binds fold exactly as {BASE_COMMIT}")

        # [5]
        print("[5] fails on the old code")
        old = parse_glb(base.graft(bare, hair_garment(), name=NAME, extras=EXTRAS))
        Jo, Wo = garment_joints(gm, old, NAME)
        has = any(n.get("name") == "HairGen_c00_00" for n in old["gltf"]["nodes"])
        print(f"       {BASE_COMMIT} graft: node HairGen_c00_00 present {has}; v1 JOINTS_0 {Jo[1, :2].tolist()} "
              f"weights {Wo[1, :2].round(3).tolist()} (Head = {head})")
        check(not has and Jo[1, :2].tolist() == [head, head], f"{BASE_COMMIT} folds _01 onto Head, adds no node")

        # [6]
        print("[6] fit_hairdeck sets joint_binds; the graft hangs them at their binds")
        import smoke_garment_hairdeck_fit as fx
        import smoke_hair_chains_bind as sb
        from app.core import garment_hairdeck as gh
        P, F, _na = sb.hair()
        nohead, proxy = sb.hair_glbs(fx, P, F)
        body = fx.body_glb()
        r = gh.fit_hairdeck(nohead, proxy, body, swing=True, chains_json=json.dumps(sb.CHAINS).encode(),
                            cards_json=sb.cards_file(), colour_target=None, forward_m=0.01, tilt_deg=5.0,
                            width_scale=0.9)
        g = r.garment
        check(getattr(g, "joint_binds", None) and sorted(g.joint_binds) == sorted(g.joint_parents),
              f"joint_binds {sorted(g.joint_binds)} == the joint_parents names")
        pf = parse_glb(gm.graft(body, g, name=NAME, extras=EXTRAS))
        nf = pf["gltf"]["nodes"]
        worlds = {nm: gm._world_matrix(nf, node_index(pf["gltf"], nm)) for nm in g.joint_binds}
        check(all(np.abs(worlds[nm][:3, 3] - g.joint_binds[nm][:3, 3]).max() < 1e-6 for nm in worlds),
              "every appended joint's world translation = its bind")
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
