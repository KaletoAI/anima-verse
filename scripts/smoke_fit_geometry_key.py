#!/usr/bin/env python3
"""Ruling A107: fits are keyed on the base model's GEOMETRY, not its file bytes.

Usage:
    ./.venv/bin/python scripts/smoke_fit_geometry_key.py

Runs against a THROWAWAY storage directory, synthetic GLBs only — no world, no server, no hub.

Fixture: a skinned grid GLB "B" — 3 x 3 vertices 0.1 m apart in the XY plane (9 vertices, 8 triangles,
one primitive), two joints "Hips" / "Spine", vertex weights (1 - y/0.2, y/0.2) on (Hips, Spine), inverse bind
matrices identity / translate(0, -0.1, 0), one material with a 2 x 2 PNG.

[1] model_geometry.descriptor / equivalent (tolerances 0.1 mm, weight 2e-3, bind 1e-4):
    a. B with the PNG recoloured (pixels only)              -> file sha differs, equivalent  (nothing geometric moved)
    b. B re-split into two primitives (tris 0-3 / 4-7, each with its own copy of the vertices it uses), the
       vertex order reversed in each, 2e-7 m noise on every x  -> equivalent (2e-7 < 1e-4; the welded positions
       are the same 9; the same 8 triangles over them) — what the face-retexture re-rig does (A107 report)
    c. vertex 4 (the centre) moved 1 mm in z                 -> NOT equivalent (1e-3 > 1e-4)
    d. vertex 4's weights (0.5, 0.5) -> (0.49, 0.51)         -> NOT equivalent (0.01 > 2e-3)
    e. a hole fill: triangle 0 split at its centroid into 3  -> NOT equivalent (10 vertices / 10 triangles vs 9 / 8)
    f. Spine's inverse bind translation -0.1 -> -0.101       -> NOT equivalent (1e-3 > 1e-4)
[2] lineage + store judgement (character "Demo", BSIG "base0123abcd" at model3d/BSIG.glb):
    B stored                         -> id G; a fit record {accepted, base_model_sha256: sha(B), base_geometry_id: G}
    rewrite with a (texture only)    -> base sha changes, id still G -> garment_store._accepted_on True,
                                        chain_failure of a failed fit on sha(B)+G still holds,
                                        garment_assembly.built_on_fit_base(bare sha = sha(a)) True,
                                        garments._haar_result_current True
    rewrite with b (re-split)        -> id still G -> _accepted_on True
    rewrite with c (geometry)        -> another id -> _accepted_on False, chain_failure None, built_on_fit_base False
    a record WITHOUT base_geometry_id on sha(B) with base a -> False (judged by file sha until the judgement)
[3] fit_geometry_migration.judge_character (base = a, record shas name the old B which is gone):
    fit "hair_x_a1a1a1a1a1a1" (GLB = B, record sha(B), no id)          -> stamped G (its body is B, equivalent to a)
    fit "hair_y_a2a2a2a2a2a2" (GLB = c, record sha(c), no id)          -> kept (its body moved 1 mm)
    failed/hair_x_a3a3a3a3a3a3.json {step fit, sha(B)}                  -> stamped G (sha(B) judged equivalent via hair_x_a1a1a1a1a1a1)
    raw/hair_x_s1/record.json results {"1": {sha(B)}}         -> stamped G
    second call                                               -> skipped "already judged"
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="smoke_fit_geometry_"))
os.environ["STORAGE_DIR"] = str(TMP / "world")
os.environ["INSTANCE_DIR"] = str(TMP / "instance")
(TMP / "world" / "characters" / "Demo" / "model3d").mkdir(parents=True)

from app.core import paths  # noqa: E402

paths.init(str(TMP / "world"))

import hashlib  # noqa: E402

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from app.core import base_body, garment_store as gs, model_geometry as mg  # noqa: E402
from app.core.glb_mesh import pack_glb  # noqa: E402

FAILS = 0


def check(label, got, want):
    global FAILS
    ok = got == want
    FAILS += 0 if ok else 1
    print(f"{'ok  ' if ok else 'FAIL'} {label}: {got!r}" + ("" if ok else f" (want {want!r})"))


def png(colour) -> bytes:
    out = io.BytesIO()
    Image.new("RGBA", (2, 2), colour).save(out, "PNG")
    return out.getvalue()


def grid():
    pos = np.array([[x * 0.1, y * 0.1, 0.0] for y in range(3) for x in range(3)], np.float32)
    tris = []
    for y in range(2):
        for x in range(2):
            i = y * 3 + x
            tris += [[i, i + 1, i + 4], [i, i + 4, i + 3]]
    w_spine = pos[:, 1] / 0.2
    weights = np.stack([1 - w_spine, w_spine, np.zeros(9), np.zeros(9)], 1).astype(np.float32)
    joints = np.tile(np.array([0, 1, 0, 0], np.uint16), (9, 1))
    return pos, np.array(tris, np.uint32), joints, weights


def build(prims, *, image=None, spine_y=-0.1) -> bytes:
    """``prims`` = [(positions, triangles, joints, weights)]."""
    binary = bytearray()
    views, accessors = [], []

    def add(array, component, kind, target=None):
        data = np.ascontiguousarray(array).tobytes()
        while len(binary) % 4:
            binary.append(0)
        views.append({"buffer": 0, "byteOffset": len(binary), "byteLength": len(data),
                      **({"target": target} if target else {})})
        binary.extend(data)
        acc = {"bufferView": len(views) - 1, "componentType": component, "count": len(array), "type": kind}
        if kind == "VEC3" and component == 5126:
            acc.update(min=np.asarray(array).min(0).tolist(), max=np.asarray(array).max(0).tolist())
        accessors.append(acc)
        return len(accessors) - 1

    primitives = []
    for pos, tris, joints, weights in prims:
        primitives.append({"attributes": {"POSITION": add(pos, 5126, "VEC3"),
                                          "TEXCOORD_0": add(pos[:, :2].copy(), 5126, "VEC2"),
                                          "JOINTS_0": add(joints, 5123, "VEC4"),
                                          "WEIGHTS_0": add(weights, 5126, "VEC4")},
                           "indices": add(tris.reshape(-1), 5125, "SCALAR"), "material": 0})
    ibm = np.stack([np.eye(4), np.eye(4)]).astype(np.float32)
    ibm[1, 1, 3] = spine_y
    ibm_acc = add(ibm.transpose(0, 2, 1).reshape(2, 16), 5126, "MAT4")
    img = image or png((200, 150, 120, 255))
    while len(binary) % 4:
        binary.append(0)
    views.append({"buffer": 0, "byteOffset": len(binary), "byteLength": len(img)})
    binary.extend(img)
    gltf = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0, 2]}],
            "nodes": [{"name": "Hips", "children": [1]}, {"name": "Spine", "translation": [0, 0.1, 0]},
                      {"name": "Body", "mesh": 0, "skin": 0}],
            "meshes": [{"primitives": primitives}], "skins": [{"joints": [0, 1], "inverseBindMatrices": ibm_acc}],
            "materials": [{"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}],
            "textures": [{"source": 0}], "images": [{"bufferView": len(views) - 1, "mimeType": "image/png"}],
            "accessors": accessors, "bufferViews": views, "buffers": [{"byteLength": len(binary)}]}
    return pack_glb(gltf, bytes(binary))


def split_reversed(pos, tris, joints, weights):
    out = []
    for part in (tris[:4], tris[4:]):
        used = np.unique(part)[::-1]                     # reversed vertex order
        remap = {int(v): i for i, v in enumerate(used)}
        p = pos[used].copy()
        p[:, 0] += 2e-7
        out.append((p, np.vectorize(remap.get)(part).astype(np.uint32), joints[used], weights[used]))
    return out


def main() -> int:
    pos, tris, joints, weights = grid()
    B = build([(pos, tris, joints, weights)])
    a = build([(pos, tris, joints, weights)], image=png((20, 150, 120, 255)))
    b = build(split_reversed(pos, tris, joints, weights))
    p2 = pos.copy(); p2[4, 2] += 0.001
    c = build([(p2, tris, joints, weights)])
    w2 = weights.copy(); w2[4, :2] = [0.49, 0.51]
    d = build([(pos, tris, joints, w2)])
    centroid = pos[tris[0]].mean(0, keepdims=True)
    t0 = tris[0]
    e_tris = np.vstack([[[t0[0], t0[1], 9], [t0[1], t0[2], 9], [t0[2], t0[0], 9]], tris[1:]]).astype(np.uint32)
    e = build([(np.vstack([pos, centroid]).astype(np.float32), e_tris, np.vstack([joints, joints[:1]]),
                np.vstack([weights, weights[:1]]))])
    f = build([(pos, tris, joints, weights)], spine_y=-0.101)

    print("[1] descriptor / equivalent")
    dB = mg.descriptor(B)
    check("a: file sha differs", hashlib.sha256(a).hexdigest() != hashlib.sha256(B).hexdigest(), True)
    for label, glb, want in [("a texture only", a, True), ("b re-split + reversed + 2e-7 noise", b, True),
                             ("c vertex moved 1 mm", c, False), ("d weight 0.01", d, False),
                             ("e hole fill", e, False), ("f bind matrix 1 mm", f, False)]:
        check(f"{label} equivalent", mg.equivalent(mg.descriptor(glb), dB), want)

    print("[2] lineage + store judgement")
    from app.core import garment_assembly, garments
    bsig = "base0123abcd"
    check("BSIG is a base signature", base_body.is_base_signature(bsig), True)
    model = TMP / "world" / "characters" / "Demo" / "model3d" / f"{bsig}.glb"
    garments_root = TMP / "world" / "characters" / "Demo" / "garments"

    def put(data: bytes) -> str:
        model.write_bytes(data)
        st = model.stat()
        os.utime(model, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
        return base_body.base_model_sha256("Demo", bsig)

    shaB = put(B)
    G = mg.of_file_sha(shaB)
    check("B has a geometry id", G.startswith("g") and len(G) == 17, True)
    record = {"accepted": True, "kind": "hair", "base_model_sha256": shaB, mg.FIELD: G}
    gs.write_record(garments_root / "failed" / "hair_x_a0a0a0a0a0a0.json",
                    {"item_id": "hair_x", "fsig": "a0a0a0a0a0a0", "step": "fit", "error": "refused",
                     "base_model_sha256": shaB, **mg.stamp(shaB)})
    haar = {"base_model_sha256": shaB, mg.FIELD: G, "fit_version": None, "strands_sha256": "s"}
    from app.core.garment_haar import HAAR_FIT_VERSION
    haar["fit_version"] = HAAR_FIT_VERSION
    sha_a = put(a)
    check("a: base sha changed", sha_a != shaB, True)
    check("a: same geometry id", mg.of_file_sha(sha_a), G)
    check("a: _accepted_on", gs._accepted_on(record, sha_a), True)
    check("a: chain_failure holds", gs.chain_failure("Demo", "hair_x", "a0a0a0a0a0a0", base_model_sha=sha_a) is not None, True)
    check("a: built_on_fit_base", garment_assembly.built_on_fit_base({"base_model_sha256": sha_a}, record), True)
    check("a: _haar_result_current", garments._haar_result_current(haar, sha_a, "s"), True)
    check("a: a record without an id is judged by file sha",
          gs._accepted_on({"accepted": True, "kind": "hair", "base_model_sha256": shaB}, sha_a), False)
    sha_b = put(b)
    check("b: same geometry id", mg.of_file_sha(sha_b), G)
    check("b: _accepted_on", gs._accepted_on(record, sha_b), True)
    sha_c = put(c)
    check("c: another geometry id", mg.of_file_sha(sha_c) not in ("", G), True)
    check("c: _accepted_on", gs._accepted_on(record, sha_c), False)
    check("c: chain_failure", gs.chain_failure("Demo", "hair_x", "a0a0a0a0a0a0", base_model_sha=sha_c), None)
    check("c: built_on_fit_base", garment_assembly.built_on_fit_base({"base_model_sha256": sha_c}, record), False)

    print("[3] one-time judgement")
    from app.core import fit_geometry_migration as fm
    import shutil
    shutil.rmtree(garments_root)
    shaC = hashlib.sha256(c).hexdigest()
    (garments_root / "raw" / "hair_x_s1").mkdir(parents=True)
    (garments_root / "hair_x_a1a1a1a1a1a1.glb").write_bytes(B)
    gs.write_record(garments_root / "hair_x_a1a1a1a1a1a1.json", {"accepted": True, "kind": "hair", "item_id": "hair_x",
                                                       "base_model_sha256": shaB})
    (garments_root / "hair_y_a2a2a2a2a2a2.glb").write_bytes(c)
    gs.write_record(garments_root / "hair_y_a2a2a2a2a2a2.json", {"accepted": True, "kind": "hair", "item_id": "hair_y",
                                                       "base_model_sha256": shaC})
    gs.write_record(garments_root / "failed" / "hair_x_a3a3a3a3a3a3.json",
                    {"item_id": "hair_x", "fsig": "a3a3a3a3a3a3", "step": "fit", "base_model_sha256": shaB})
    gs.write_record(garments_root / "raw" / "hair_x_s1" / "record.json",
                    {"results": {"1": {"accepted": True, "base_model_sha256": shaB}}})
    sha_a = put(a)
    base_body.current_base = lambda name, profile=None: (bsig, base_body.base_model_sha256(name, bsig))
    res = fm.judge_character("Demo")
    check("stamped", sorted(res["stamped"]), sorted(["hair_x_a1a1a1a1a1a1.json", "hair_x_a3a3a3a3a3a3.json", "hair_x_s1#s1"]))
    check("kept", res["kept"], ["hair_y_a2a2a2a2a2a2.json"])
    current = mg.of_file_sha(sha_a)
    check("hair_x_a1a1a1a1a1a1 id", gs.read_record(garments_root / "hair_x_a1a1a1a1a1a1.json").get(mg.FIELD), current)
    check("hair_x_a1a1a1a1a1a1 now served on a", gs._accepted_on(gs.read_record(garments_root / "hair_x_a1a1a1a1a1a1.json"), sha_a), True)
    check("hair_y_a2a2a2a2a2a2 stays stale", gs._accepted_on(gs.read_record(garments_root / "hair_y_a2a2a2a2a2a2.json"), sha_a), False)
    check("HAAR verdict id", json.loads((garments_root / "raw" / "hair_x_s1" / "record.json").read_text())
          ["results"]["1"].get(mg.FIELD), current)
    check("second call", fm.judge_character("Demo")["skipped"], "already judged")
    shutil.rmtree(TMP, ignore_errors=True)
    print("FAILED" if FAILS else "all checks passed", f"({FAILS} failures)")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
