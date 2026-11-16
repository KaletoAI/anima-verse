#!/usr/bin/env python3
"""The matte floor of a base body's roughness (``base_mesh_repair.matte_floor``, Ruling A97): hair, a beard or brows
the mesher modelled into the body and painted glossier than the skin are mirrored about a floor below the skin's
roughness; the skin keeps its values.

Usage:
    ./.venv/bin/python scripts/smoke_base_matte_floor.py
    RUN_A97_REAL=1 A97_MODELS=<dir> ./.venv/bin/python scripts/smoke_base_matte_floor.py

No world, no server, no Blender, no network. The optional real-data section reads a COPY of Rurik's base model
(``<A97_MODELS>/Rurik_Asgerson_model3d_basee46edcf9.glb``).

Fixture: a GLB with one body mesh of 10 vertices; vertex i has TEXCOORD_0 = ((i + 0.5) / 10, 0.25), so it samples
column i of a 10 x 2 PNG metallic-roughness texture (lossless: every value below is exact). The G (roughness)
column values: 140 for i = 0..6 (the "skin"), 10, 40, 100 for i = 7, 8, 9 (the glossy "hair"). Expected, derived
by hand (``MATTE_MARGIN`` = 0.05):

[1] Sorted samples 10, 40, 100, 140 x 7: the median of 10 values is the mean of the 5th and 6th = 140 -> anchor
    140 / 255 = 0.549 (rounded 0.549), floor 0.549 - 0.05 = 0.499. The 8-bit level is ceil(0.49902 x 255) =
    ceil(127.25) = 128. The three glossy columns are mirrored about it: 2 x 128 - g = 246, 216, 156; the seven
    skin columns stay 140 exactly. lifted = 3 / 10 = 0.3; p10_before = 10th percentile (linear) of the samples
    = 10/255 + 0.9 x (40 - 10)/255 = 0.145; p10_after = 0.549 (the mirrored values 0.96 / 0.84 / 0.61 all lie
    above the skin's 0.549, which is now the lowest). status "applied". R and B (metallic) of every texel are as
    before (128 and 0 in the fixture).
[2] All ten columns at 140: nothing below the floor -> THE SAME bytes object back, status "unchanged", lifted 0.
[3] No metallic-roughness texture on the material -> the same bytes object, status "skipped".
[4] roughnessFactor 0.5 on the material: the samples count halved, anchor 0.5 x 140/255 = 0.2745, floor 0.2245;
    the level in texture units is ceil(0.2245 / 0.5 x 255) = ceil(114.5) = 115, so 10, 40, 100 -> 220, 190,
    130; 140 stays.
[5] A garment node (``garment_shirt_x``, ``glb_mesh._body_prims`` leaves it out) with its own roughness image all
    at 10: its image bytes are byte-identical after the floor (Ruling A36 — a garment keeps its generator map), and
    its UVs do not enter the anchor (anchor still 0.549).
[6] ``repair_glb`` with the hole fill switched off: hole-fill status "skipped", yet ``record["matte"]["status"]``
    "applied" (the floor is not a hole repair). VERSION is at least 2 (3 since Ruling A137), and the settings fingerprint of the defaults under
    VERSION 1 is ``332a2bb4fd247881`` — the value every stored base record of the test world carries (read from
    their sidecars 2026-11-15) — while under VERSION 2 it differs: every stored base body is due, the Build's local
    "Base mesh repair" step applies the floor (``figure_build._mesh_repair_due``), no hub job.
[7] Real data (RUN_A97_REAL=1): Rurik's base model, measured 2026-11-15 — anchor 0.549 (+-0.005), floor 0.499,
    lifted 0.11 (+-0.01); the vertices whose base colour luminance lies in [50, 90) (the hair and beard) had a
    median roughness of 0.33 and end at >= 0.60; those with luminance >= 90 (the skin) keep their median 0.55
    (+-0.005).
"""
import io
import json
import os
import struct
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []


def check(label, ok, detail=""):
    print(("  OK   " if ok else "  FAIL ") + label + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(label)


def png(columns, height=2):
    """A 10 x ``height`` RGB PNG whose column i has G = columns[i], R 128, B 0."""
    from PIL import Image
    arr = np.zeros((height, len(columns), 3), np.uint8)
    arr[..., 0] = 128
    arr[..., 1] = np.array(columns, np.uint8)[None, :]
    out = io.BytesIO()
    Image.fromarray(arr).save(out, "PNG")
    return out.getvalue()


def build_glb(columns, *, factor=None, mr=True, garment_columns=None):
    """The fixture GLB (module docstring)."""
    n = len(columns)
    blobs, views, accessors = [], [], []

    def add(data, target=None):
        offset = sum(len(b) for b in blobs)
        pad = b"\0" * (-len(data) % 4)
        blobs.append(data + pad)
        view = {"buffer": 0, "byteOffset": offset, "byteLength": len(data)}
        if target:
            view["target"] = target
        views.append(view)
        return len(views) - 1

    def mesh_accessors():
        P = np.array([[i * 0.1, (i % 2) * 0.1, 0.0] for i in range(n)], np.float32)
        U = np.array([[(i + 0.5) / n, 0.25] for i in range(n)], np.float32)
        F = np.array([[0, 1, 2], [3, 4, 5], [6, 7, 8], [9, 0, 1]], np.uint16)
        pv = add(P.tobytes(), 34962)
        accessors.append({"bufferView": pv, "componentType": 5126, "count": n, "type": "VEC3",
                          "min": P.min(0).tolist(), "max": P.max(0).tolist()})
        uv = add(U.tobytes(), 34962)
        accessors.append({"bufferView": uv, "componentType": 5126, "count": n, "type": "VEC2"})
        iv = add(F.tobytes(), 34963)
        accessors.append({"bufferView": iv, "componentType": 5123, "count": F.size, "type": "SCALAR"})
        return {"POSITION": len(accessors) - 3, "TEXCOORD_0": len(accessors) - 2}, len(accessors) - 1

    images, textures, materials, meshes, nodes = [], [], [], [], []
    base = add(png([200] * n))
    images.append({"bufferView": base, "mimeType": "image/png"})
    textures.append({"source": 0})
    pbr = {"baseColorTexture": {"index": 0}, "metallicFactor": 0}
    if mr:
        images.append({"bufferView": add(png(columns)), "mimeType": "image/png"})
        textures.append({"source": len(images) - 1})
        pbr["metallicRoughnessTexture"] = {"index": len(textures) - 1}
    if factor is not None:
        pbr["roughnessFactor"] = factor
    materials.append({"name": "Material_0", "pbrMetallicRoughness": pbr})
    attrs, idx = mesh_accessors()
    meshes.append({"name": "body", "primitives": [{"attributes": attrs, "indices": idx, "material": 0}]})
    nodes.append({"name": "body", "mesh": 0})
    if garment_columns is not None:
        images.append({"bufferView": add(png(garment_columns)), "mimeType": "image/png"})
        textures.append({"source": len(images) - 1})
        materials.append({"name": "garment", "pbrMetallicRoughness": {
            "baseColorTexture": {"index": 0}, "metallicRoughnessTexture": {"index": len(textures) - 1},
            "metallicFactor": 0}})
        attrs, idx = mesh_accessors()
        meshes.append({"name": "garment_shirt_x", "primitives": [{"attributes": attrs, "indices": idx,
                                                                  "material": len(materials) - 1}]})
        nodes.append({"name": "garment_shirt_x", "mesh": 1, "extras": {"garment": {"kind": "shirt"}}})
    binary = b"".join(blobs)
    gltf = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": list(range(len(nodes)))}],
            "nodes": nodes, "meshes": meshes, "materials": materials, "textures": textures, "images": images,
            "accessors": accessors, "bufferViews": views, "buffers": [{"byteLength": len(binary)}]}
    from app.core.glb_mesh import pack_glb
    return pack_glb(gltf, binary)


def image_of(glb, image_index):
    from PIL import Image
    from app.core.model_validate import parse_glb
    parsed = parse_glb(glb)
    view = parsed["gltf"]["bufferViews"][parsed["gltf"]["images"][image_index]["bufferView"]]
    start = int(view.get("byteOffset", 0))
    raw = bytes(parsed["bin"][start:start + int(view["byteLength"])])
    return raw, np.asarray(Image.open(io.BytesIO(raw)).convert("RGB"))


def main() -> int:
    from app.core import base_mesh_repair as R
    columns = [140] * 7 + [10, 40, 100]

    print("[1] glossy columns mirrored about the floor")
    glb = build_glb(columns)
    out, rec = R.matte_floor(glb)
    check("status applied", rec.get("status") == "applied", str(rec))
    check("anchor 0.549", rec.get("anchor") == 0.549, str(rec))
    check("floor 0.499", rec.get("floor") == 0.499, str(rec))
    check("lifted 0.3", rec.get("lifted") == 0.3, str(rec))
    check("p10_before 0.145", rec.get("p10_before") == 0.145, str(rec))
    check("p10_after 0.549", rec.get("p10_after") == 0.549, str(rec))
    _raw, arr = image_of(out, 1)
    check("G = 140 x 7, 246, 216, 156", arr[0, :, 1].tolist() == [140] * 7 + [246, 216, 156], str(arr[0, :, 1]))
    check("both rows the same", arr[1, :, 1].tolist() == arr[0, :, 1].tolist())
    check("R and B unchanged", bool((arr[..., 0] == 128).all() and (arr[..., 2] == 0).all()))
    _raw, base = image_of(out, 0)
    check("base colour unchanged", bool((base[..., 1] == 200).all()))

    print("[2] nothing below the floor")
    flat = build_glb([140] * 10)
    out, rec = R.matte_floor(flat)
    check("same bytes object", out is flat)
    check("status unchanged, lifted 0", rec.get("status") == "unchanged" and rec.get("lifted") == 0.0, str(rec))

    print("[3] no metallic-roughness texture")
    bare = build_glb(columns, mr=False)
    out, rec = R.matte_floor(bare)
    check("same bytes object, skipped", out is bare and rec.get("status") == "skipped", str(rec))

    print("[4] roughnessFactor 0.5")
    out, rec = R.matte_floor(build_glb(columns, factor=0.5))
    _raw, arr = image_of(out, 1)
    check("anchor 0.275 (0.2745), floor 0.225", rec.get("anchor") in (0.274, 0.275) and rec.get("floor") in (0.224, 0.225),
          str(rec))
    check("G = 140 x 7, 220, 190, 130", arr[0, :, 1].tolist() == [140] * 7 + [220, 190, 130], str(arr[0, :, 1]))

    print("[5] a garment keeps its map")
    dressed = build_glb(columns, garment_columns=[10] * 10)
    before_raw, _ = image_of(dressed, 2)
    out, rec = R.matte_floor(dressed)
    after_raw, _ = image_of(out, 2)
    check("garment image byte-identical", before_raw == after_raw)
    check("anchor without the garment 0.549", rec.get("anchor") == 0.549, str(rec))
    _raw, arr = image_of(out, 1)
    check("body still mirrored", arr[0, :, 1].tolist() == [140] * 7 + [246, 216, 156], str(arr[0, :, 1]))

    print("[6] repair_glb, VERSION")
    out, rec = R.repair_glb(glb, {"enabled": False})
    check("hole fill skipped", rec.get("status") == "skipped", str(rec))
    check("matte applied anyway", (rec.get("matte") or {}).get("status") == "applied", str(rec))
    check("VERSION >= 2", R.VERSION >= 2)
    current = R.settings_fingerprint({})
    kept, R.VERSION = R.VERSION, 1
    old = R.settings_fingerprint({})
    R.VERSION = kept
    check("v1 default fingerprint is the stored records' 332a2bb4fd247881", old == "332a2bb4fd247881", old)
    check("v2 fingerprint differs (every stored base due)", current != old, current)

    if os.environ.get("RUN_A97_REAL") == "1":
        print("[7] real data: Rurik's base")
        from PIL import Image
        from app.core import glb_mesh as G
        from app.core.model_validate import texture_image_index
        data = (Path(os.environ["A97_MODELS"]) / "Rurik_Asgerson_model3d_basee46edcf9.glb").read_bytes()
        out, rec = R.matte_floor(data)
        check("anchor 0.549", abs(rec["anchor"] - 0.549) <= 0.005, str(rec))
        check("floor 0.499", abs(rec["floor"] - 0.499) <= 0.005, str(rec))
        check("lifted 0.11", abs(rec["lifted"] - 0.11) <= 0.01, str(rec))

        def samples(blob):
            parsed = G._parse(blob, "x")
            gltf = parsed["gltf"]
            rough, lum = [], []
            for prim in G._body_prims(parsed):
                pbr = gltf["materials"][prim["material"]]["pbrMetallicRoughness"]
                arrays = []
                for key in ("baseColorTexture", "metallicRoughnessTexture"):
                    image = gltf["images"][texture_image_index(gltf, gltf["textures"][pbr[key]["index"]])]
                    view = gltf["bufferViews"][image["bufferView"]]
                    start = int(view.get("byteOffset", 0))
                    raw = bytes(parsed["bin"][start:start + int(view["byteLength"])])
                    arrays.append(np.asarray(Image.open(io.BytesIO(raw)).convert("RGB"), np.float64))
                uv = G.accessor_array(parsed, prim["attributes"]["TEXCOORD_0"])
                h, w = arrays[0].shape[:2]
                x = np.clip((np.mod(uv[:, 0], 1) * w).astype(int), 0, w - 1)
                y = np.clip((np.mod(uv[:, 1], 1) * h).astype(int), 0, h - 1)
                lum.append(arrays[0][y, x] @ np.array([0.2126, 0.7152, 0.0722]))
                rough.append(arrays[1][y, x, 1] / 255.0)
            return np.concatenate(rough), np.concatenate(lum)

        r0, lum = samples(data)
        r1, _ = samples(out)
        hair = (lum >= 50) & (lum < 90)
        skin = lum >= 90
        check("hair median 0.33 before", abs(np.median(r0[hair]) - 0.33) <= 0.01, f"{np.median(r0[hair]):.3f}")
        check("hair median >= 0.60 after", np.median(r1[hair]) >= 0.60, f"{np.median(r1[hair]):.3f}")
        check("skin median kept 0.55", abs(np.median(r1[skin]) - np.median(r0[skin])) <= 0.005
              and abs(np.median(r0[skin]) - 0.55) <= 0.01, f"{np.median(r0[skin]):.3f} -> {np.median(r1[skin]):.3f}")
    else:
        print("[7] real data skipped (RUN_A97_REAL=1 A97_MODELS=<dir>)")

    print("\nALL OK" if not FAILS else f"\n{len(FAILS)} FAILED: {FAILS}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
