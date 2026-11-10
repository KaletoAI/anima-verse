#!/usr/bin/env python3
"""GLB mesh IO + garment graft (``app/core/glb_mesh.py``) on a synthetic skinned body, expectations by hand.

Usage: ./.venv/bin/python scripts/smoke_glb_graft.py

No world, no server, no external assets.

Fixture body: every base joint of ``shared/models/rig/joints.json`` as ``mixamorig:<name>``, with one extension bone
``breast_L`` (parent Spine2) inserted in the MIDDLE of the skin's joint list (after Neck), so Head's skin index is
one higher than its base-list index. The body mesh node ``Body`` (skin 0, TRS translation (0, 0.1, 0), rotation
(0, 0, 0, 1), scale (1, 1, 1)) and the Hips joint are children of the root node ``Armature``; its four triangles are
weighted to Spine2/Head; one PNG base colour.

Garment: two triangles with joint names [mixamorig:Head, mixamorig:Spine2] (indices 0/1 = Head/Spine2), weights
(0.7, 0.3) and (1, 0), its own PNG or WebP texture, a BLEND double-sided material.

After ``graft(name="garment_hair_hair_demo")``:
- JOINTS_0 of the new primitive are the TARGET skin indices of Head (6 = 5 + the inserted bone) and Spine2 (3).
- The new node is named ``garment_hair_hair_demo``, has ``skin == 0``, ``extras.garment == extras``, the body node's
  TRS and is a child of ``Armature`` (the body node's parent).
- Every original accessor, bufferView byte range, node and the scene's node list keep their exact JSON/bytes;
  only ``Armature.children`` gains the new node index.
- ``validate_glb(grafted, extension_names={breast_L: {parent: mixamorig:Spine2, group: chest}})`` is ok,
  ``rig_frames_preserved(bare, grafted)`` is ok.
- The bare file still has exactly one base-colour image; the grafted one has two (R11: management paths never
  see an assembled file).
- ``garment_arrays(grafted)`` round-trips positions/uvs/normals/weights (+- 1e-6) and resolves every vertex's joints
  back to the same names; ``body_arrays`` of both files are identical (the garment node is not body).
- A target without Spine2 raises KeyError naming ``mixamorig:Spine2``; joints the target lacks but no vertex
  weights (> 0) map to index 0 with weight 0 (rows by hand in the code), a weighted one still raises KeyError;
  a meshopt/draco-flagged target is refused;
- A weighted EXTENSION joint the target lacks folds onto its nearest ancestor the target has, by the garment's
  ``joint_parents`` (2026-11-10, a chest-weighted garment fitted on a base whose tip bones the covered outfit
  model left out): row 0 [Head, ExtraTip, Head, Head] / (0.7, 0.3, 0, 0) with ExtraTip -> breast_L becomes
  [6, 5, 6, 6] (breast_L sits right after Neck 4, Head moved to 6) with the weights unchanged; through a missing
  middle link ExtraTip -> ExtraMid -> breast_L the same; ExtraTip -> mixamorig:Spine2 gives [6, 3, 6, 6]. A
  missing CONTRACT joint never folds: the target without Spine2 still raises KeyError although Spine2 names
  Hips as its parent. ``garment_arrays`` reads ``joint_parents`` from the file's node tree: breast_L ->
  mixamorig:Spine2, mixamorig:Hips -> Armature.
  a WebP garment image adds ``EXT_texture_webp`` to ``extensionsUsed``; a second graft under the same name is
  refused.
- ``static_arrays`` concatenates two primitives (indices of the second shifted by the first's vertex count 3).
"""
import copy
import io
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

FAILS = []


def check(cond, label):
    print(("OK   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


def image(fmt="PNG", color=(200, 30, 30)):
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (16, 16), color).save(out, fmt, **({"lossless": True} if fmt == "WEBP" else {}))
    return out.getvalue()


def pack(doc, blob):
    blob = bytes(blob) + b"\0" * (-len(blob) % 4)
    doc["buffers"] = [{"byteLength": len(blob)}]
    raw = json.dumps(doc).encode()
    raw += b" " * (-len(raw) % 4)
    body = struct.pack("<II", len(raw), 0x4E4F534A) + raw + struct.pack("<II", len(blob), 0x004E4942) + blob
    return b"glTF" + struct.pack("<II", 2, 12 + len(body)) + body


def body_fixture(*, drop=None, extensions=None):
    from app.core.rig_contract import BASE_JOINT_NAMES
    names = ["mixamorig:" + n for n in BASE_JOINT_NAMES if n != drop]
    mid = names.index("mixamorig:Neck") + 1
    names.insert(mid, "breast_L")
    # node 0 = Armature, node 1 = Body, nodes 2.. = joints in skin order
    nodes = [{"name": "Armature", "children": [1, 2]},
             {"name": "Body", "mesh": 0, "skin": 0, "translation": [0, 0.1, 0], "rotation": [0, 0, 0, 1],
              "scale": [1, 1, 1]}]
    jidx = {n: 2 + i for i, n in enumerate(names)}
    joints = [{"name": n} for n in names]
    hips = joints[0]
    hips["children"] = [jidx[n] for n in names[1:] if n != "breast_L"]
    if "mixamorig:Spine2" in jidx:
        joints[names.index("mixamorig:Spine2")]["children"] = [jidx["breast_L"]]
    nodes += joints
    sk = {n: i for i, n in enumerate(names)}
    spine2 = sk.get("mixamorig:Spine2", 0)
    P = np.array([[0, 1.3, 0], [0.1, 1.3, 0], [0, 1.4, 0], [0, 1.5, 0], [0.1, 1.5, 0], [0, 1.6, 0]], "<f4")
    U = np.array([[0, 0], [1, 0], [0, 1], [0.5, 0.5], [1, 1], [0, 0.5]], "<f4")
    J = np.array([[spine2, 0, 0, 0]] * 3 + [[sk["mixamorig:Head"], spine2, 0, 0]] * 3, "<u2")
    W = np.array([[1, 0, 0, 0]] * 3 + [[0.8, 0.2, 0, 0]] * 3, "<f4")
    I = np.array([0, 1, 2, 3, 4, 5, 2, 1, 3, 3, 1, 4], "<u4")
    blob = bytearray()
    views, accs = [], []

    def add(arr, ctype, typ, target, minmax=False):
        raw = arr.tobytes()
        blob.extend(b"\0" * (-len(blob) % 4))
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(raw), "target": target})
        blob.extend(raw)
        a = {"bufferView": len(views) - 1, "componentType": ctype, "count": len(arr) if arr.ndim > 1 else arr.size,
             "type": typ}
        if minmax:
            a["min"], a["max"] = arr.min(0).tolist(), arr.max(0).tolist()
        accs.append(a)
        return len(accs) - 1
    attrs = {"POSITION": add(P, 5126, "VEC3", 34962, True), "TEXCOORD_0": add(U, 5126, "VEC2", 34962),
             "JOINTS_0": add(J, 5123, "VEC4", 34962), "WEIGHTS_0": add(W, 5126, "VEC4", 34962)}
    ind = add(I, 5125, "SCALAR", 34963)
    png = image()
    blob.extend(b"\0" * (-len(blob) % 4))
    views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(png)})
    blob.extend(png)
    doc = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}], "nodes": nodes,
           "meshes": [{"name": "Body", "primitives": [{"attributes": attrs, "indices": ind, "material": 0}]}],
           "skins": [{"joints": [jidx[n] for n in names]}],
           "accessors": accs, "bufferViews": views,
           "images": [{"bufferView": len(views) - 1, "mimeType": "image/png"}], "textures": [{"source": 0}],
           "materials": [{"name": "Skin", "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}]}
    if extensions:
        doc["extensionsUsed"] = list(extensions)
    return pack(doc, blob), names


def garment(fmt="PNG"):
    from app.core.glb_mesh import GarmentMesh
    return GarmentMesh(
        positions=np.array([[0, 1.6, 0.1], [0.1, 1.6, 0.1], [0, 1.7, 0.1], [0.1, 1.7, 0.1]]),
        normals=np.array([[0, 0, 1.0]] * 4),
        uvs=np.array([[0, 0], [1, 0], [0, 1], [1, 1.0]]),
        indices=np.array([[0, 1, 2], [2, 1, 3]]),
        joints=np.array([[0, 1, 0, 0], [0, 1, 0, 0], [0, 0, 0, 0], [1, 0, 0, 0]]),
        weights=np.array([[0.7, 0.3, 0, 0], [0.7, 0.3, 0, 0], [1, 0, 0, 0], [1, 0, 0, 0]]),
        joint_names=["mixamorig:Head", "mixamorig:Spine2"],
        image=image(fmt, (90, 60, 30)), mime="image/webp" if fmt == "WEBP" else "image/png",
        material={"name": "hair_src", "pbrMetallicRoughness": {"baseColorTexture": {"index": 3},
                                                               "metallicRoughnessTexture": {"index": 4},
                                                               "metallicFactor": 0.0},
                  "normalTexture": {"index": 5}, "alphaMode": "BLEND", "doubleSided": True})


EXTRAS = {"kind": "hair", "item_id": "hair_demo", "fsig": "0123456789ab"}
NAME = "garment_hair_hair_demo"


def view_bytes(parsed, accessor_index):
    gltf = parsed["gltf"]
    v = gltf["bufferViews"][gltf["accessors"][accessor_index]["bufferView"]]
    s = v.get("byteOffset", 0)
    return bytes(parsed["bin"][s:s + v["byteLength"]])


def main():
    from app.core import glb_mesh as gm
    from app.core.base_body import _base_color_targets
    from app.core.model_validate import parse_glb, rig_frames_preserved, validate_glb

    bare, names = body_fixture()
    ext = {"breast_L": {"parent": "mixamorig:Spine2", "group": "chest"}}
    check(validate_glb(bare, extension_names=ext)["ok"], "fixture: bare body validates")
    g = garment()
    grafted = gm.graft(bare, g, name=NAME, extras=EXTRAS)
    pb, pg = parse_glb(bare), parse_glb(grafted)
    jb, jg = pb["gltf"], pg["gltf"]

    node_i = next(i for i, n in enumerate(jg["nodes"]) if n.get("name") == NAME)
    node = jg["nodes"][node_i]
    prim = jg["meshes"][node["mesh"]]["primitives"][0]
    J = gm.accessor_array(pg, prim["attributes"]["JOINTS_0"]).astype(int)
    head, spine2 = names.index("mixamorig:Head"), names.index("mixamorig:Spine2")
    check(head == 6 and spine2 == 3, f"fixture: Head 6 / Spine2 3 in the target skin ({head}, {spine2})")
    check(J[0, :2].tolist() == [head, spine2] and J[3, 0] == spine2,
          f"graft: JOINTS_0 remapped by name onto the target order ({J.tolist()})")
    check(node.get("skin") == 0 and node["extras"] == {"garment": EXTRAS}, "graft: node skin 0 + extras.garment")
    check(jg["meshes"][node["mesh"]].get("name") == NAME, "graft: mesh named like the node")
    body = jb["nodes"][1]
    check(all(node.get(k) == body.get(k) for k in ("translation", "rotation", "scale", "matrix")),
          "graft: TRS copied from the body node")
    check(node_i in jg["nodes"][0]["children"], "graft: child of the body node's parent (Armature)")
    same_nodes = jg["nodes"][1:len(jb["nodes"])] == jb["nodes"][1:]
    arm = dict(jg["nodes"][0])
    arm["children"] = [c for c in arm["children"] if c != node_i]
    check(same_nodes and arm == jb["nodes"][0], "graft: original nodes unchanged (only Armature.children grows)")
    check(jg["accessors"][:len(jb["accessors"])] == jb["accessors"]
          and jg["bufferViews"][:len(jb["bufferViews"])] == jb["bufferViews"]
          and jg["scenes"] == jb["scenes"] and jg["skins"] == jb["skins"], "graft: original JSON entries unchanged")
    check(all(view_bytes(pb, i) == view_bytes(pg, i) for i in range(len(jb["accessors"]))),
          "graft: body accessors' bytes unchanged")
    check(bytes(pg["bin"][:len(pb["bin"])]) == bytes(pb["bin"]), "graft: original binary range byte-identical")
    check(all(v["byteOffset"] % 4 == 0 for v in jg["bufferViews"]), "graft: every bufferView 4-byte aligned")
    pos_acc = jg["accessors"][prim["attributes"]["POSITION"]]
    check(np.allclose(pos_acc["min"], [0, 1.6, 0.1]) and np.allclose(pos_acc["max"], [0.1, 1.7, 0.1]),
          "graft: POSITION min/max")
    mat = jg["materials"][prim["material"]]
    check(mat["alphaMode"] == "OPAQUE" and mat["doubleSided"] is True and "normalTexture" not in mat
          and "metallicRoughnessTexture" not in mat["pbrMetallicRoughness"],
          "graft: material OPAQUE, doubleSided kept, foreign texture slots dropped")
    tex = jg["textures"][mat["pbrMetallicRoughness"]["baseColorTexture"]["index"]]
    img = jg["images"][tex["source"]]
    check(bytes(pg["bin"][jg["bufferViews"][img["bufferView"]]["byteOffset"]:][:len(g.image)]) == g.image,
          "graft: garment image embedded")
    v = validate_glb(grafted, extension_names=ext)
    check(v["ok"], f"graft: validate_glb ok ({v['errors']})")
    r = rig_frames_preserved(bare, grafted)
    check(r["ok"], f"graft: rig frames preserved ({r['errors']})")
    check(len(_base_color_targets(jb)[1]) == 1, "bare: exactly one base-colour image")
    try:
        _base_color_targets(jg)
        two = False
    except ValueError:
        two = True
    check(two, "grafted: two base-colour images (assembled files stay out of the management paths)")

    back = gm.garment_arrays(grafted)
    check(np.allclose(back.positions, g.positions, atol=1e-6) and np.allclose(back.uvs, g.uvs, atol=1e-6)
          and np.allclose(back.normals, g.normals, atol=1e-6), "round trip: positions/uvs/normals")
    check(np.allclose(back.weights, g.weights, atol=1e-6), "round trip: weights")
    ok = all(back.joint_names[back.joints[i, k]] == g.joint_names[g.joints[i, k]]
             for i in range(4) for k in range(4) if g.weights[i, k] > 0)
    check(ok, "round trip: every weighted joint resolves to the same name")
    check(np.array_equal(back.indices, g.indices), "round trip: indices")
    check(back.image == g.image and back.mime == "image/png", "round trip: image")
    bb, bg = gm.body_arrays(bare), gm.body_arrays(grafted)
    check(all(np.array_equal(getattr(bb, k), getattr(bg, k)) for k in ("positions", "faces", "uvs", "joints",
                                                                         "weights"))
          and bb.joint_names == bg.joint_names == names and len(bb.positions) == 6,
          "body_arrays: the garment node is not body")
    check(np.allclose(bb.weights[3], [0.8, 0.2, 0, 0]) and bb.faces.shape == (4, 3), "body_arrays: arrays read")

    no_spine, _ = body_fixture(drop="Spine2")
    try:
        gm.graft(no_spine, g, name=NAME, extras=EXTRAS)
        check(False, "graft: missing Spine2 raises KeyError")
    except KeyError as exc:
        check("mixamorig:Spine2" in str(exc), f"graft: KeyError names the missing joint ({exc})")
    # A garment fitted on a base with extension bones the target lacks (the
    # covered variant of a base body) keeps those joints in its list; only a
    # joint with weight > 0 must exist. Joint list [Head, Spine2, ExtraTip,
    # ExtraTip2]: vertex 0 names ExtraTip in slot 2 with weight 0, ExtraTip2
    # is never referenced. By hand: JOINTS_0 rows 0/3 ([0, 1, 2, 0] / [1, 0, 0, 0])
    # -> [6, 3, 0, 6] / [3, 6, 6, 6] (Head 6, Spine2 3, unused -> 0),
    # WEIGHTS_0 row 0 unchanged (0.7, 0.3, 0, 0).
    unused = garment()
    unused.joint_names = [*unused.joint_names, "mixamorig:ExtraTip", "mixamorig:ExtraTip2"]
    unused.joints = np.array([[0, 1, 2, 0], [0, 1, 0, 0], [0, 0, 0, 0], [1, 0, 0, 0]])
    try:
        loose = gm.graft(bare, unused, name=NAME, extras=EXTRAS)
        pl = parse_glb(loose)
        nl = next(n for n in pl["gltf"]["nodes"] if n.get("name") == NAME)
        pr = pl["gltf"]["meshes"][nl["mesh"]]["primitives"][0]
        JL = gm.accessor_array(pl, pr["attributes"]["JOINTS_0"]).astype(int)
        WL = gm.accessor_array(pl, pr["attributes"]["WEIGHTS_0"])
        check(JL[0].tolist() == [6, 3, 0, 6] and JL[3].tolist() == [3, 6, 6, 6]
              and np.allclose(WL[0], [0.7, 0.3, 0, 0]),
              f"graft: unweighted missing joints map to 0 with weight 0 ({JL[0].tolist()}, {WL[0].tolist()})")
        check(validate_glb(loose, extension_names=ext)["ok"], "graft: file with unweighted extra joints validates")
    except KeyError as exc:
        check(False, f"graft: unweighted missing joints refused ({exc})")
    weighted = garment()
    weighted.joint_names = [*weighted.joint_names, "mixamorig:ExtraTip"]
    weighted.joints = np.array([[0, 2, 0, 0], [0, 1, 0, 0], [0, 0, 0, 0], [1, 0, 0, 0]])
    try:
        gm.graft(bare, weighted, name=NAME, extras=EXTRAS)
        check(False, "graft: a WEIGHTED missing joint raises KeyError")
    except KeyError as exc:
        check("mixamorig:ExtraTip" in str(exc), f"graft: KeyError names the weighted missing joint ({exc})")
    # Fold of a weighted extension joint onto its nearest ancestor in the target (module docstring).
    def folded_rows(parents):
        tip = garment()
        tip.joint_names = [*tip.joint_names, "mixamorig:ExtraTip"]
        tip.joints = np.array([[0, 2, 0, 0], [0, 1, 0, 0], [0, 0, 0, 0], [1, 0, 0, 0]])
        tip.joint_parents = parents
        pf = parse_glb(gm.graft(bare, tip, name=NAME, extras=EXTRAS))
        nf = next(n for n in pf["gltf"]["nodes"] if n.get("name") == NAME)
        pr = pf["gltf"]["meshes"][nf["mesh"]]["primitives"][0]
        return (gm.accessor_array(pf, pr["attributes"]["JOINTS_0"]).astype(int)[0].tolist(),
                gm.accessor_array(pf, pr["attributes"]["WEIGHTS_0"])[0])
    for parents, want, label in (
            ({"mixamorig:ExtraTip": "breast_L"}, [6, 5, 6, 6], "onto its parent breast_L"),
            ({"mixamorig:ExtraTip": "mixamorig:ExtraMid", "mixamorig:ExtraMid": "breast_L"}, [6, 5, 6, 6],
             "through a missing middle link"),
            ({"mixamorig:ExtraTip": "mixamorig:Spine2"}, [6, 3, 6, 6], "onto a contract parent")):
        try:
            rows, wrow = folded_rows(parents)
            check(rows == want and np.allclose(wrow, [0.7, 0.3, 0, 0]),
                  f"graft: a weighted missing extension joint folds {label} ({rows}, {wrow.tolist()})")
        except KeyError as exc:
            check(False, f"graft: a weighted missing extension joint folds {label} ({exc})")
    contract_missing = garment()
    contract_missing.joint_parents = {"mixamorig:Spine2": "mixamorig:Hips"}
    try:
        gm.graft(no_spine, contract_missing, name=NAME, extras=EXTRAS)
        check(False, "graft: a missing contract joint never folds")
    except KeyError as exc:
        check("mixamorig:Spine2" in str(exc), f"graft: a missing contract joint never folds ({exc})")
    jp = gm.garment_arrays(grafted).joint_parents
    check(jp.get("breast_L") == "mixamorig:Spine2" and jp.get("mixamorig:Hips") == "Armature",
          f"garment_arrays: joint_parents from the node tree (breast_L -> {jp.get('breast_L')}, "
          f"Hips -> {jp.get('mixamorig:Hips')})")
    for flag in ("EXT_meshopt_compression", "KHR_draco_mesh_compression"):
        flagged, _ = body_fixture(extensions=[flag])
        try:
            gm.graft(flagged, g, name=NAME, extras=EXTRAS)
            check(False, f"graft: {flag} target refused")
        except ValueError as exc:
            check(flag in str(exc), f"graft: {flag} target refused ({exc})")
        try:
            gm.body_arrays(flagged)
            check(False, f"body_arrays: {flag} refused")
        except ValueError:
            check(True, f"body_arrays: {flag} refused")
    try:
        gm.graft(grafted, g, name=NAME, extras=EXTRAS)
        check(False, "graft: same name twice refused")
    except ValueError:
        check(True, "graft: same name twice refused")
    webp = gm.graft(bare, garment("WEBP"), name=NAME, extras=EXTRAS)
    jw = parse_glb(webp)["gltf"]
    check("EXT_texture_webp" in jw.get("extensionsUsed", []), "graft: WebP image -> EXT_texture_webp used")
    vw = validate_glb(webp, extension_names=ext)
    check(vw["ok"], f"graft: WebP grafted file validates ({vw['errors']})")
    check(gm.garment_arrays(webp).mime == "image/webp", "round trip: WebP mime")

    doc = copy.deepcopy(jb)
    mesh = doc["meshes"][0]
    second = copy.deepcopy(mesh["primitives"][0])
    I = gm.accessor_array(pb, second["indices"]).reshape(-1)
    blob = bytearray(pb["bin"])
    blob.extend(b"\0" * (-len(blob) % 4))
    raw = np.array([0, 1, 2], "<u4").tobytes()
    doc["bufferViews"].append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(raw)})
    blob.extend(raw)
    doc["accessors"].append({"bufferView": len(doc["bufferViews"]) - 1, "componentType": 5125, "count": 3,
                             "type": "SCALAR"})
    second["indices"] = len(doc["accessors"]) - 1
    mesh["primitives"].append(second)
    P, F, U, img_bytes, mime, material = gm.static_arrays(pack(doc, blob))
    check(len(P) == 12 and len(F) == len(I) // 3 + 1 and F[-1].tolist() == [6, 7, 8],
          f"static_arrays: two primitives concatenated (last face {F[-1].tolist()})")
    check(img_bytes == image() and mime == "image/png" and material.get("name") == "Skin",
          "static_arrays: image + material")

    if FAILS:
        print(f"\n{len(FAILS)} FAILED")
        sys.exit(1)
    print("\nALL OK")


if __name__ == "__main__":
    main()
