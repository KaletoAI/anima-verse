#!/usr/bin/env python3
"""HairDeck cards as alpha MASK with the world cutoff, written by the fit publisher and by the assembly
(``garments._publish_fit``, ``garment_assembly._build`` / ``_state`` / ``_hair_image``) — strand-hair plan
2026-11-13, Task 2 (spec § 6.1, § 6.4 H1). Expectations by hand.

Usage: ./.venv/bin/python scripts/smoke_hair_alpha_assembly.py

No server, no world DB, no hub, no Blender: a throwaway storage dir (``paths.init``) holds the temp world's
``config.json`` (``base_body.hair_alpha_cutoff`` 0.12 — a NON-default value, so a hard-coded 0.15 fails) and the
garment files of the character ``demo``; the distance tier's Blender decimation is stubbed (``refine.decimate_to``
answers "not built"), the refit pool runs in-process, the assembly's validator is stubbed (the fixture body is no
full figure) — ``rig_frames_preserved`` runs for real. Outbound connections are refused (``socket.connect``).

Fixture body (built here, the style of ``smoke_glb_graft_hair_joints.py::body_fixture``): every base joint of
``shared/models/rig/joints.json`` as ``mixamorig:<name>``, node 0 ``Armature`` (children Body, Hips), node 1
``Body`` (skin 0), Hips at the origin with every other base joint as its direct child; Head translated to
(0, 1.5, 0); inverse bind matrices = inv(world); one 256 px PNG base colour.

Hair garment: Task 1's [3] — two square tubes (3 rows x 4 vertices; rows at y 1.7 / 1.6 / 1.5, v = 1 / 0.5 / 0,
u around the tube 0 / 0.5 / 1 / 0.5 as HairDeck's) + a 4-vertex cap at y 1.75; every vertex weighted 1 to
``mixamorig:Head``; ``COLOR_0`` (0.4, 0.3, 0.2, 1). ``texture_garment(g, hairdeck_cards(F, 24, 28))``.

The four facts of an alpha card (glTF material of the node): ``alphaMode`` "MASK", ``alphaCutoff`` 0.12 (the
temp world's), ``doubleSided`` true, ``pbrMetallicRoughness.baseColorTexture`` present with its image's
``mimeType`` "image/png".

[1] The fit publisher: ``refit_pool.graft_file(target, garment, "garment_hair_h1", extras, out,
    material_overrides=alpha_overrides())`` — the four facts; and ``garments._publish_fit`` itself (kind "hair")
    hands ``material_overrides == {"alphaMode": "MASK", "alphaCutoff": 0.12, "doubleSided": True}`` to the pool and
    the published fit GLB carries the four facts. A clothing publish hands ``None`` (stays OPAQUE).
[2] The assembly: ``garment_assembly._build`` of the full tier (bare = the fixture body, the fit of [1]) — the
    grafted ``garment_hair_hair_h1`` node has the four facts; the sha256 of its image = sha256(strip_atlas()).
[3] The far tier: a ``low`` file = the fit's garment with its image stripped, grafted without overrides (what a
    Blender decimation may leave). ``_hair_image(g, "low")`` returns the FULL fit's image bytes (sha equal to the
    atlas) and "image/png"; ``_hair_image(g, "full")`` the same. ``_build`` of the low tier: the hair node has the
    four facts and the atlas image — never an untextured (white) card.
[4] ``_state(wanted, "full")[item]["alpha_cutoff"] == 0.12``; the full assembly of [2] written with its sidecar
    is ``_current``; with the world setting changed to 0.18 the same files are no longer ``_current``
    (True -> False) — the change re-assembles on the CPU; a clothing piece carries no ``alpha_cutoff``.
[5] Fails on the old code: BASE ``e1ad6a344``'s ``glb_mesh.graft`` of the same textured garment without
    overrides writes ``alphaMode`` "OPAQUE" (and no cutoff); BASE's ``garment_assembly._state`` has no
    ``alpha_cutoff`` (read from the BASE source text: the key does not occur in it) and BASE's
    ``FIT_VERSION["hair"]`` is 12 (now 15).
"""
import copy
import hashlib
import importlib.util
import json
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

BASE_COMMIT = "e1ad6a344"
FAILS = []
CHAR = "demo"
ITEM = "hair_h1"
FSIG = "0123456789ab"
NAME = f"garment_hair_{ITEM}"


def check(cond, label):
    print(("OK   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


def _no_net(*_a, **_k):
    raise OSError("smoke: outbound connections are refused")


def pack(doc, blob):
    blob = bytes(blob) + b"\0" * (-len(blob) % 4)
    doc["buffers"] = [{"byteLength": len(blob)}]
    raw = json.dumps(doc).encode()
    raw += b" " * (-len(raw) % 4)
    body = struct.pack("<II", len(raw), 0x4E4F534A) + raw + struct.pack("<II", len(blob), 0x004E4942) + blob
    return b"glTF" + struct.pack("<II", 2, 12 + len(body)) + body


def png(size, colour):
    import io
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (size, size), colour).save(out, "PNG")
    return out.getvalue()


def body_fixture():
    from app.core.rig_contract import BASE_JOINT_NAMES
    names = ["mixamorig:" + n for n in BASE_JOINT_NAMES]
    jidx = {n: 2 + i for i, n in enumerate(names)}
    nodes = [{"name": "Armature", "children": [1, 2]}, {"name": "Body", "mesh": 0, "skin": 0}]
    joints = [{"name": n} for n in names]
    joints[0]["children"] = [jidx[n] for n in names[1:]]
    joints[names.index("mixamorig:Head")]["translation"] = [0, 1.5, 0]
    nodes += joints
    sk = {n: i for i, n in enumerate(names)}
    ibm = np.tile(np.eye(4), (len(names), 1, 1))
    ibm[sk["mixamorig:Head"], 1, 3] = -1.5
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
    tex = png(256, (200, 160, 140))
    blob.extend(b"\0" * (-len(blob) % 4))
    views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(tex)})
    blob.extend(tex)
    doc = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}], "nodes": nodes,
           "meshes": [{"name": "Body", "primitives": [{"attributes": attrs, "indices": ind, "material": 0}]}],
           "skins": [{"joints": [jidx[n] for n in names], "inverseBindMatrices": ibm_acc}],
           "accessors": accs, "bufferViews": views,
           "images": [{"bufferView": len(views) - 1, "mimeType": "image/png"}], "textures": [{"source": 0}],
           "materials": [{"name": "Skin", "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}]}
    return pack(doc, blob)


def tube_faces(offset):
    F = []
    for r in range(2):
        for k in range(4):
            a, b = 4 * r + k, 4 * r + (k + 1) % 4
            c, d = 4 * (r + 1) + (k + 1) % 4, 4 * (r + 1) + k
            F += [[a, b, c], [a, c, d]]
    return np.asarray(F) + offset


def hair_garment():
    from app.core.glb_mesh import GarmentMesh
    ring = np.array([[-0.005, 0, -0.005], [0.005, 0, -0.005], [0.005, 0, 0.005], [-0.005, 0, 0.005]])
    P, U = [], []
    for cx in (-0.05, 0.05):
        for r, y in enumerate((1.7, 1.6, 1.5)):
            P += (ring + [cx, y, -0.08]).tolist()
            U += [[u, 1 - r / 2] for u in (0, 0.5, 1, 0.5)]
    P += [[-0.02, 1.75, -0.02], [0.02, 1.75, -0.02], [0.02, 1.75, 0.02], [-0.02, 1.75, 0.02]]
    U += [[0, 0]] * 4
    F = np.vstack([tube_faces(0), tube_faces(12), np.array([[24, 25, 26], [24, 26, 27]])])
    n = len(P)
    g = GarmentMesh(positions=np.asarray(P, np.float64), normals=None, uvs=np.asarray(U, np.float64), indices=F,
                    joints=np.zeros((n, 4), np.int64), weights=np.tile([1.0, 0, 0, 0], (n, 1)),
                    joint_names=["mixamorig:Head"], material={"name": "hair", "doubleSided": True},
                    colors=np.tile([0.4, 0.3, 0.2, 1.0], (n, 1)))
    return g, F


def material_of(blob, name):
    from app.core.model_validate import parse_glb, texture_image_index
    gltf = parse_glb(blob)["gltf"]
    node = next(n for n in gltf["nodes"] if n.get("name") == name)
    mat = gltf["materials"][gltf["meshes"][node["mesh"]]["primitives"][0]["material"]]
    tex = (mat.get("pbrMetallicRoughness") or {}).get("baseColorTexture")
    mime = None
    if isinstance(tex, dict):
        mime = gltf["images"][texture_image_index(gltf, gltf["textures"][tex["index"]])].get("mimeType")
    return mat, mime


def four_facts(blob, name, cutoff, label):
    mat, mime = material_of(blob, name)
    check(mat.get("alphaMode") == "MASK", f"{label}: alphaMode MASK (got {mat.get('alphaMode')})")
    check(mat.get("alphaCutoff") == cutoff, f"{label}: alphaCutoff {cutoff} (got {mat.get('alphaCutoff')})")
    check(mat.get("doubleSided") is True, f"{label}: doubleSided")
    check(mime == "image/png", f"{label}: baseColorTexture with a PNG image (got {mime})")


def node_image_sha(blob, name):
    from app.core import glb_mesh
    return hashlib.sha256(glb_mesh.garment_arrays(blob, node_prefix=name, exact=True).image).hexdigest()


def base_module(tmp, rel, modname):
    src = subprocess.run(["git", "-C", str(ROOT), "show", f"{BASE_COMMIT}:{rel}"], check=True,
                         capture_output=True, text=True).stdout
    path = tmp / f"{modname}.py"
    path.write_text(src)
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod            # dataclasses look their module up
    spec.loader.exec_module(mod)
    return mod, src


def main():
    tmp = Path(tempfile.mkdtemp(prefix="smoke_hair_alpha_assembly_"))
    try:
        return run_checks(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run_checks(tmp):
    socket.socket.connect = _no_net
    socket.create_connection = _no_net
    from app.core import paths
    paths.init(tmp / "world")
    paths.init_instance(tmp / "instance")
    from app.core import config
    cfg = paths.get_config_path()
    cfg.parent.mkdir(parents=True, exist_ok=True)

    def set_cutoff(value):
        cfg.write_text(json.dumps({"base_body": {"hair_alpha_cutoff": value}}))
        config.load(cfg, instance_path=tmp / "instance" / "config.json")

    set_cutoff(0.12)
    from app.blender import refine
    from app.core import garment_assembly as ga, garment_fit, garment_store as gs, garments, glb_mesh
    from app.core import hair_cards, refit_pool
    from app.models.character import get_character_dir
    get_character_dir(CHAR, create=True)
    target = body_fixture()
    g, F = hair_garment()
    textured = hair_cards.texture_garment(g, hair_cards.hairdeck_cards(F, 24, 28))
    atlas_sha = hashlib.sha256(hair_cards.strip_atlas()).hexdigest()
    extras = {"kind": "hair", "item_id": ITEM, "fsig": FSIG}

    # [1] the fit publisher
    out = tmp / "graft" / "fit.glb"
    refit_pool.graft_file(target, textured, NAME, extras, str(out), material_overrides=hair_cards.alpha_overrides())
    four_facts(out.read_bytes(), NAME, 0.12, "[1] graft_file")
    seen = []
    real_run = refit_pool.run

    def run(fn, *args, **kwargs):
        seen.append(kwargs.get("material_overrides"))
        return fn(*args, **kwargs)
    refit_pool.run = run
    refine.decimate_to = lambda *a, **k: {"ok": False, "error": "smoke: no Blender"}
    try:
        fit = garments._publish_fit(CHAR, ITEM, "hair", FSIG, "base0123abcd", target,
                                    SimpleNamespace(garment=textured, metrics={}), {"kind": "hair"}, schedule=False)
        garments._publish_fit(CHAR, "item_c1", "clothing", FSIG, "base0123abcd", target,
                              SimpleNamespace(garment=g, metrics={}), {"kind": "clothing"}, schedule=False)
    finally:
        refit_pool.run = real_run
    check(seen[0] == {"alphaMode": "MASK", "alphaCutoff": 0.12, "doubleSided": True},
          f"[1] _publish_fit hands the hair overrides to the pool (got {seen[0]})")
    check(seen[1] is None, f"[1] _publish_fit: clothing gets no overrides (got {seen[1]})")
    check(fit == gs.garment_path(CHAR, ITEM, FSIG, "fit"), "[1] the fit lands at its garment path")
    four_facts(fit.read_bytes(), NAME, 0.12, "[1] published fit")
    check(gs.read_record(fit.with_suffix(".json")).get("fit_version") == garment_fit.FIT_VERSION["hair"] == 15,
          "[1] record fit_version 15")

    # [2] the assembly, full tier
    directory = tmp / "model3d"
    directory.mkdir()
    sig = "outfit0123ab"
    bare = ga.bare_path(directory, sig, ga.FULL)
    bare.write_bytes(target)
    bare.with_suffix(".json").write_text(json.dumps({"rig": "mixamo"}))
    (directory / ga.LOW).mkdir()
    ga.bare_path(directory, sig, ga.LOW).write_bytes(target)
    ga.bare_path(directory, sig, ga.LOW).with_suffix(".json").write_text(json.dumps({"rig": "mixamo"}))
    ga._model3d = lambda: SimpleNamespace(_validator_for=lambda rig, name: (lambda blob: {"ok": True}),
                                          ASSEMBLED_DIR="assembled")
    wanted = [{"item_id": ITEM, "kind": "hair", "fsig": FSIG, "fit": fit, "low": None, "record": {}}]
    blob, side, _rev = ga._build(CHAR, directory, bare, wanted, ga.FULL)
    four_facts(blob, NAME, 0.12, "[2] assembly full")
    check(node_image_sha(blob, NAME) == atlas_sha, "[2] assembly full: the image is the strip atlas")

    # [3] the far tier lost its image
    stripped = copy.copy(glb_mesh.garment_arrays(fit.read_bytes()))
    stripped.image, stripped.mime = b"", ""
    low = gs.garment_path(CHAR, ITEM, FSIG, "low")
    low.parent.mkdir(parents=True, exist_ok=True)
    low.write_bytes(glb_mesh.graft(target, stripped, name=NAME, extras=extras))
    check(not glb_mesh.garment_arrays(low.read_bytes()).image, "[3] fixture: the low file has no image")
    wanted_low = [dict(wanted[0], low=low)]
    image, mime = ga._hair_image(wanted_low[0], ga.LOW)
    check(hashlib.sha256(image).hexdigest() == atlas_sha and mime == "image/png",
          "[3] _hair_image(low): the full fit's image")
    image, mime = ga._hair_image(wanted_low[0], ga.FULL)
    check(hashlib.sha256(image).hexdigest() == atlas_sha, "[3] _hair_image(full): the fit's image")
    blob_low, _side, _ = ga._build(CHAR, directory, ga.bare_path(directory, sig, ga.LOW), wanted_low, ga.LOW)
    four_facts(blob_low, NAME, 0.12, "[3] assembly low")
    check(node_image_sha(blob_low, NAME) == atlas_sha, "[3] assembly low: the atlas, never an untextured card")

    # [4] the cutoff is part of the assembly's state
    state = ga._state(wanted, ga.FULL)
    check(state[ITEM].get("alpha_cutoff") == 0.12, f"[4] _state alpha_cutoff 0.12 (got {state[ITEM]})")
    check(side["garments"] == state, "[4] the build's sidecar carries that state")
    assembled = ga.assembled_path(directory, sig, ga.FULL)
    assembled.parent.mkdir(parents=True, exist_ok=True)
    assembled.write_bytes(blob)
    assembled.with_suffix(".json").write_text(json.dumps(side))
    check(ga._current(assembled, bare, ga._state(wanted, ga.FULL)) is True, "[4] _current at 0.12")
    set_cutoff(0.18)
    check(ga._state(wanted, ga.FULL)[ITEM]["alpha_cutoff"] == 0.18, "[4] _state follows the setting (0.18)")
    check(ga._current(assembled, bare, ga._state(wanted, ga.FULL)) is False, "[4] 0.18: no longer _current")
    cloth = [{"item_id": "item_c1", "kind": "clothing", "fsig": FSIG,
              "fit": gs.garment_path(CHAR, "item_c1", FSIG, "fit"), "low": None, "record": {}}]
    check("alpha_cutoff" not in ga._state(cloth, ga.FULL)["item_c1"], "[4] clothing: no alpha_cutoff")
    set_cutoff(0.12)

    # [5] the old code
    base_glb, _ = base_module(tmp, "app/core/glb_mesh.py", "glb_mesh_base")
    old = base_glb.graft(target, textured, name=NAME, extras=extras)
    mat, _mime = material_of(old, NAME)
    print(f"     BASE {BASE_COMMIT} graft: alphaMode {mat.get('alphaMode')}, alphaCutoff {mat.get('alphaCutoff')}")
    check(mat.get("alphaMode") == "OPAQUE" and "alphaCutoff" not in mat, "[5] BASE graft writes OPAQUE")
    old_asm = subprocess.run(["git", "-C", str(ROOT), "show", f"{BASE_COMMIT}:app/core/garment_assembly.py"],
                             check=True, capture_output=True, text=True).stdout
    check("alpha_cutoff" not in old_asm, "[5] BASE _state has no alpha_cutoff")
    old_fit = subprocess.run(["git", "-C", str(ROOT), "show", f"{BASE_COMMIT}:app/core/garment_fit.py"],
                             check=True, capture_output=True, text=True).stdout
    check('FIT_VERSION: Dict[str, int] = {"hair": 12,' in old_fit, "[5] BASE FIT_VERSION hair 12")

    print("PASS" if not FAILS else f"FAIL ({len(FAILS)})")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
