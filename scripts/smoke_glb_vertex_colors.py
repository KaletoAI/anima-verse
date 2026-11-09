#!/usr/bin/env python3
"""Vertex colours through ``app/core/glb_mesh.py`` (graft, assembly re-read, LOD) — HairDeck hair, plan
2026-11-09-hairdeck-hair Task 2. Expectations derived by hand below.

Usage:
    ./.venv/bin/python scripts/smoke_glb_vertex_colors.py [--no-blender]

No world, no server, no hub: a throwaway storage dir (``paths.init``), synthetic GLBs, the body/garment fixtures of
``scripts/smoke_glb_graft.py``. Section [4] runs real Blender (``refine.decimate_to`` -> ``lod.py``) when a usable
Blender (5.2) is found; ``--no-blender`` or no Blender skips it. Section [5] reads the real HairDeck result in
``~/claude-out/hairdeck`` when it exists (informational, skipped otherwise).

[1] ``card_arrays`` on a hand-built two-node GLB. Nodes: 0 ``Root`` (translation (0, 1, 0), scale (2, 2, 2),
    children [1]), 1 ``hair_cards`` (translation (0.1, 0, 0), rotation 90 deg about +Y = quaternion
    (0, s, 0, s), s = sqrt(0.5); mesh 0), 2 ``head_proxy`` (column-major matrix = uniform scale 0.5 + translation
    (0, 0.5, 0); mesh 1). Scene nodes [0, 2].
    hair_cards mesh: positions (1,0,0), (0,1,0), (0,0,1); one triangle; COLOR_0 UNSIGNED_BYTE normalized VEC4
    (51,102,153,255), (255,0,0,255), (0,0,255,128); TEXCOORD_0 (0,0), (1,0), (0,1); material
    {name "hair", doubleSided true, baseColorFactor (1,1,1,1)}.
    R_y(90) = [[0,0,1],[0,1,0],[-1,0,0]]:
      (1,0,0) -> (0,0,-1) -> +(0.1,0,0) = (0.1,0,-1) -> *2 = (0.2,0,-2) -> +(0,1,0) = (0.2, 1, -2)
      (0,1,0) -> (0,1,0)  -> (0.1,1,0)               -> (0.2,2,0)    -> (0.2, 3, 0)
      (0,0,1) -> (1,0,0)  -> (1.1,0,0)               -> (2.2,0,0)    -> (2.2, 1, 0)
    colours /255: (0.2, 0.4, 0.6, 1), (1, 0, 0, 1), (0, 0, 1, 128/255); faces [[0, 1, 2]]; uvs as written;
    material doubleSided true.
    head_proxy mesh: positions (1,1,1), (-1,1,1), (1,-1,1), no colour, no uv -> 0.5*p + (0,0.5,0) =
      (0.5,1,0.5), (-0.5,1,0.5), (0.5,0,0.5); colours None; uvs zeros (3, 2).
    node="" on this two-mesh-node file -> ValueError; node "nope" -> ValueError; node="" on a one-node copy
    (head_proxy dropped) -> the hair_cards result.
[2] Graft with colours: fixture garment G (4 vertices, BLEND doubleSided material) + colors
    C = [(0.2,0.4,0.6,1), (1,0,0,1), (0,0,1,0.5), (0.5,0.5,0.5,1)] -> the new primitive has COLOR_0, accessor
    componentType 5121 (UNSIGNED_BYTE), normalized true, type VEC4, count 4; raw bytes = round(C*255) =
    [51,102,153,255], [255,0,0,255], [0,0,255,128], [128,128,128,255] (0.5*255 = 127.5 rounds to 128: numpy
    round-half-even gives 128 too); material doubleSided true; validate_glb + rig_frames_preserved ok;
    garment_arrays(grafted).colors == the bytes / 255 (|d| <= 0.5/255); the assembly path (garment_arrays ->
    graft onto the bare body) keeps COLOR_0 with the same bytes. Values outside [0, 1] are clipped
    (C' = C with (1.5, -0.2, 0.3, 1) in row 0 -> bytes [255, 0, 76, 255]: 0.3*255 is exactly 76.5 in float64
    and numpy rounds half to even -> 76); colours of shape (4, 3) get alpha 1 -> 4th byte 255;
    shape (3, 4) and a NaN raise ValueError.
[3] Review Focus 4 — no colours, byte-identical to the pre-change code: ``glb_mesh.py`` at explicit commit
    05c8089f (never ``HEAD:``) is loaded as a temp module. On the fixture body + garment G (PNG):
      graft(new) == graft(old)    sha256 PINNED = 04c7e439ff2245f0e67fea1e1c21a8a9294c6fca5804a5901b7c2423587cee4b (PIL/zlib PNG bytes are part of the fixture: if this
                                  pin moves while the live old-vs-new comparison holds, the encoder moved, not us)
      WebP garment: graft(new) == graft(old)
      assembly path: graft(bare, garment_arrays(fit)) new == old; garment_arrays(fit).colors is None.
[4] Real Blender: body + a garment of 2 cards (each a 1x8-quad strip, 18 vertices, 16 tris; card A colour
    (0.8, 0.2, 0.1, 1), card B (0.1, 0.3, 0.9, 1); Head weight 1) grafted with colours -> 4 body tris + 32 =
    36 tris. ``decimate_to(fit, 18, low)`` (merge_vertices False, as ``garments._fit`` calls it): ratio
    18/36 = 0.5; the low file has a node ``garment_hair_hair_demo`` whose primitive carries COLOR_0; every
    vertex colour is within 2/255 of card A or card B (no bleeding between cards); both colours occur.
    The same with merge_vertices True (the raw->prepared path of the edit chain) is reported the same way.
    Observed with Blender 5.2.2: ``lod.py`` needs no change — the glTF importer wires COLOR_0 into the material, so
    the default ``export_vertex_color="MATERIAL"`` exports it again, as FLOAT VEC3 (alpha dropped; HairDeck alpha is
    1 everywhere and ``garment_arrays`` gives VEC3 alpha 1); the max deviation is ~1.2/255 (an 8-bit round trip).
[5] Real HairDeck hair (informational): card_arrays(hair_seed42_nohead.glb, node="hair_cards") -> 12736 vertices,
    30922 triangles (92766 indices / 3), colours (12736, 4) with alpha 1.
"""
import hashlib
import importlib.util
import math
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402

BASELINE_COMMIT = "05c8089f"
PIN_GRAFT = "04c7e439ff2245f0e67fea1e1c21a8a9294c6fca5804a5901b7c2423587cee4b"
FAILS = []


def check(label, got, want):
    ok = got == want
    print(("OK   " if ok else "FAIL ") + f"{label}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        FAILS.append(label)


def near(label, got, want, tol):
    got, want = np.asarray(got, np.float64), np.asarray(want, np.float64)
    ok = got.shape == want.shape and bool(np.all(np.abs(got - want) <= tol))
    print(("OK   " if ok else "FAIL ") + label + ("" if ok else f": {got.tolist()} != {want.tolist()}"))
    if not ok:
        FAILS.append(label)


def raises(label, fn, exc=ValueError):
    try:
        fn()
    except exc as e:
        print(f"OK   {label}: {type(e).__name__}: {e}")
        return
    except Exception as e:  # noqa: BLE001
        print(f"FAIL {label}: {type(e).__name__}: {e}")
        FAILS.append(label)
        return
    print(f"FAIL {label}: no exception")
    FAILS.append(label)


def old_glb_mesh():
    """``app/core/glb_mesh.py`` as of BASELINE_COMMIT, as a private module."""
    src = subprocess.run(["git", "-C", str(ROOT), "show", f"{BASELINE_COMMIT}:app/core/glb_mesh.py"],
                         check=True, capture_output=True, text=True).stdout
    spec = importlib.util.spec_from_loader("glb_mesh_baseline", loader=None)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod   # dataclasses resolve annotations through sys.modules
    exec(compile(src, f"{BASELINE_COMMIT}:app/core/glb_mesh.py", "exec"), mod.__dict__)
    return mod


def build_glb(doc, arrays):
    """``arrays``: list of (np array, componentType, type, normalized) -> accessors 0.. in order."""
    import smoke_glb_graft as fx
    blob = bytearray()
    views, accs = [], []
    for arr, ctype, typ, normalized in arrays:
        raw = arr.tobytes()
        blob.extend(b"\0" * (-len(blob) % 4))
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(raw)})
        blob.extend(raw)
        a = {"bufferView": len(views) - 1, "componentType": ctype,
             "count": int(arr.shape[0]) if arr.ndim > 1 else int(arr.size), "type": typ}
        if normalized:
            a["normalized"] = True
        accs.append(a)
    doc = dict(doc, accessors=accs, bufferViews=views)
    return fx.pack(doc, blob)


def two_node_glb(*, drop_proxy=False):
    s = math.sqrt(0.5)
    nodes = [{"name": "Root", "translation": [0, 1, 0], "scale": [2, 2, 2], "children": [1]},
             {"name": "hair_cards", "mesh": 0, "translation": [0.1, 0, 0], "rotation": [0, s, 0, s]}]
    scene = [0]
    meshes = [{"name": "hair_cards", "primitives": [{"attributes": {"POSITION": 0, "COLOR_0": 1, "TEXCOORD_0": 2},
                                                     "indices": 3, "material": 0, "mode": 4}]}]
    arrays = [(np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1]], "<f4"), 5126, "VEC3", False),
              (np.array([[51, 102, 153, 255], [255, 0, 0, 255], [0, 0, 255, 128]], "u1"), 5121, "VEC4", True),
              (np.array([[0, 0], [1, 0], [0, 1]], "<f4"), 5126, "VEC2", False),
              (np.array([0, 1, 2], "<u4"), 5125, "SCALAR", False)]
    if not drop_proxy:
        nodes.append({"name": "head_proxy", "mesh": 1,
                      "matrix": [0.5, 0, 0, 0, 0, 0.5, 0, 0, 0, 0, 0.5, 0, 0, 0.5, 0, 1]})
        scene.append(2)
        meshes.append({"name": "head_proxy", "primitives": [{"attributes": {"POSITION": 4}, "indices": 5,
                                                             "material": 1, "mode": 4}]})
        arrays += [(np.array([[1, 1, 1], [-1, 1, 1], [1, -1, 1]], "<f4"), 5126, "VEC3", False),
                   (np.array([0, 1, 2], "<u4"), 5125, "SCALAR", False)]
    doc = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": scene}], "nodes": nodes,
           "meshes": meshes,
           "materials": [{"name": "hair", "doubleSided": True,
                          "pbrMetallicRoughness": {"baseColorFactor": [1, 1, 1, 1]}},
                         {"name": "head", "doubleSided": False}]}
    return build_glb(doc, arrays)


def prim_of(glb, name):
    from app.core.model_validate import parse_glb
    parsed = parse_glb(glb)
    g = parsed["gltf"]
    node = next(n for n in g["nodes"] if n.get("name") == name)
    return parsed, g["meshes"][node["mesh"]]["primitives"][0]


def raw_bytes(parsed, accessor_index):
    from app.core.glb_mesh import accessor_array
    acc = parsed["gltf"]["accessors"][accessor_index]
    if acc.get("normalized"):
        a = dict(acc)
        a.pop("normalized")
        parsed = {"gltf": dict(parsed["gltf"], accessors=list(parsed["gltf"]["accessors"])), "bin": parsed["bin"]}
        parsed["gltf"]["accessors"][accessor_index] = a
    return np.asarray(accessor_array(parsed, accessor_index))


def card_garment():
    """Two cards, each a 1x8-quad strip (18 vertices, 16 triangles), Head weight 1."""
    from app.core.glb_mesh import GarmentMesh
    P, U, I, C = [], [], [], []
    for card, (x0, z, col) in enumerate([(0.0, 0.10, (0.8, 0.2, 0.1, 1.0)), (0.05, 0.12, (0.1, 0.3, 0.9, 1.0))]):
        base = len(P)
        for row in range(9):
            for col_i in range(2):
                P.append([x0 + 0.02 * col_i, 1.76 - 0.02 * row, z])
                U.append([col_i, row / 8.0])
                C.append(col)
        for row in range(8):
            a, b = base + 2 * row, base + 2 * row + 1
            c, d = a + 2, b + 2
            I += [[a, c, b], [b, c, d]]
    n = len(P)
    return GarmentMesh(positions=np.array(P), normals=np.array([[0, 0, 1.0]] * n), uvs=np.array(U),
                       indices=np.array(I), joints=np.zeros((n, 4), np.int64),
                       weights=np.array([[1.0, 0, 0, 0]] * n), joint_names=["mixamorig:Head"],
                       material={"name": "hair", "doubleSided": True,
                                 "pbrMetallicRoughness": {"baseColorFactor": [1, 1, 1, 1], "metallicFactor": 0.0}},
                       colors=np.array(C))


def main() -> int:
    use_blender = "--no-blender" not in sys.argv
    tmp = Path(tempfile.mkdtemp(prefix="smoke-vcol-"))
    from app.core import paths
    paths.init(str(tmp / "storage"))

    import smoke_glb_graft as fx
    from app.core import glb_mesh as gm
    from app.core.model_validate import parse_glb, rig_frames_preserved, validate_glb

    print("[1] card_arrays")
    two = two_node_glb()
    P, F, U, C, mat = gm.card_arrays(two, node="hair_cards")
    near("hair_cards positions", P, [[0.2, 1, -2], [0.2, 3, 0], [2.2, 1, 0]], 1e-6)
    check("hair_cards faces", np.asarray(F).tolist(), [[0, 1, 2]])
    near("hair_cards uvs", U, [[0, 0], [1, 0], [0, 1]], 1e-9)
    near("hair_cards colours", C, [[0.2, 0.4, 0.6, 1], [1, 0, 0, 1], [0, 0, 1, 128 / 255]], 1e-9)
    check("hair_cards material", (mat.get("name"), mat.get("doubleSided")), ("hair", True))
    P2, F2, U2, C2, mat2 = gm.card_arrays(two, node="head_proxy")
    near("head_proxy positions", P2, [[0.5, 1, 0.5], [-0.5, 1, 0.5], [0.5, 0, 0.5]], 1e-6)
    check("head_proxy colours None", C2 is None, True)
    near("head_proxy uvs zero", U2, np.zeros((3, 2)), 0)
    check("head_proxy material", mat2.get("name"), "head")
    raises("node '' on two mesh nodes", lambda: gm.card_arrays(two))
    raises("unknown node", lambda: gm.card_arrays(two, node="nope"))
    one = two_node_glb(drop_proxy=True)
    P3, F3, U3, C3, _m = gm.card_arrays(one)
    near("node '' on one mesh node = hair_cards", P3, P, 1e-9)
    near("node '' colours", C3, C, 1e-9)

    print("[2] graft with colours")
    bare, _names = fx.body_fixture()
    g = fx.garment()
    want_bytes = [[51, 102, 153, 255], [255, 0, 0, 255], [0, 0, 255, 128], [128, 128, 128, 255]]
    g.colors = np.array([[0.2, 0.4, 0.6, 1], [1, 0, 0, 1], [0, 0, 1, 0.5], [0.5, 0.5, 0.5, 1]])
    out = gm.graft(bare, g, name=fx.NAME, extras=fx.EXTRAS)
    parsed, prim = prim_of(out, fx.NAME)
    check("COLOR_0 present", "COLOR_0" in prim["attributes"], True)
    if "COLOR_0" in prim["attributes"]:
        acc = parsed["gltf"]["accessors"][prim["attributes"]["COLOR_0"]]
        check("COLOR_0 accessor", (acc["componentType"], acc.get("normalized"), acc["type"], acc["count"]),
              (5121, True, "VEC4", 4))
        check("COLOR_0 bytes", raw_bytes(parsed, prim["attributes"]["COLOR_0"]).tolist(), want_bytes)
    mat = parsed["gltf"]["materials"][prim["material"]]
    check("doubleSided", mat.get("doubleSided"), True)
    ext = {"breast_L": {"parent": "mixamorig:Spine2", "group": "chest"}}
    check("validate_glb ok", validate_glb(out, extension_names=ext).get("ok"), True)
    check("rig frames preserved", rig_frames_preserved(bare, out).get("ok"), True)
    back = gm.garment_arrays(out)
    near("garment_arrays colours", back.colors if back.colors is not None else np.zeros((1, 4)),
         np.array(want_bytes) / 255.0, 0.5 / 255)
    again = gm.graft(bare, back, name=fx.NAME, extras=fx.EXTRAS)
    parsed2, prim2 = prim_of(again, fx.NAME)
    check("assembly path keeps COLOR_0 bytes",
          raw_bytes(parsed2, prim2["attributes"]["COLOR_0"]).tolist() if "COLOR_0" in prim2["attributes"] else None,
          want_bytes)
    g.colors = np.array([[1.5, -0.2, 0.3, 1], [1, 0, 0, 1], [0, 0, 1, 0.5], [0.5, 0.5, 0.5, 1]])
    pc, pp = prim_of(gm.graft(bare, g, name=fx.NAME, extras=fx.EXTRAS), fx.NAME)
    check("clipped row 0", raw_bytes(pc, pp["attributes"]["COLOR_0"]).tolist()[0], [255, 0, 76, 255])
    g.colors = np.array([[0.2, 0.4, 0.6], [1, 0, 0], [0, 0, 1], [0.5, 0.5, 0.5]])
    pc, pp = prim_of(gm.graft(bare, g, name=fx.NAME, extras=fx.EXTRAS), fx.NAME)
    check("rgb gets alpha 255", [r[3] for r in raw_bytes(pc, pp["attributes"]["COLOR_0"]).tolist()],
          [255, 255, 255, 255])
    g.colors = np.ones((3, 4))
    raises("colours (3, 4) for 4 vertices", lambda: gm.graft(bare, g, name=fx.NAME, extras=fx.EXTRAS))
    g.colors = np.array([[np.nan, 0, 0, 1]] + [[0, 0, 0, 1]] * 3)
    raises("NaN colour", lambda: gm.graft(bare, g, name=fx.NAME, extras=fx.EXTRAS))

    print(f"[3] no colours: byte-identical to {BASELINE_COMMIT}")
    old = old_glb_mesh()
    new_png = gm.graft(bare, fx.garment(), name=fx.NAME, extras=fx.EXTRAS)
    old_png = old.graft(bare, old.GarmentMesh(**{k: v for k, v in vars(fx.garment()).items() if k != "colors"}),
                        name=fx.NAME, extras=fx.EXTRAS)
    check("graft new == old (PNG)", new_png == old_png, True)
    check("graft sha pinned", hashlib.sha256(new_png).hexdigest(), PIN_GRAFT)
    gw = fx.garment("WEBP")
    new_webp = gm.graft(bare, gw, name=fx.NAME, extras=fx.EXTRAS)
    old_webp = old.graft(bare, old.GarmentMesh(**{k: v for k, v in vars(gw).items() if k != "colors"}),
                         name=fx.NAME, extras=fx.EXTRAS)
    check("graft new == old (WebP)", new_webp == old_webp, True)
    re_new = gm.garment_arrays(new_png)
    check("garment_arrays(no COLOR_0).colors is None", re_new.colors, None)
    assembled_new = gm.graft(bare, re_new, name=fx.NAME, extras=fx.EXTRAS)
    assembled_old = old.graft(bare, old.garment_arrays(old_png), name=fx.NAME, extras=fx.EXTRAS)
    check("assembly path new == old", assembled_new == assembled_old, True)

    print("[4] real Blender: decimate_to keeps COLOR_0")
    from app.blender import refine, runner
    if not use_blender or not runner.is_available():
        print("  SKIP (no usable Blender or --no-blender)")
    else:
        cards = card_garment()
        colours = np.array([[0.8, 0.2, 0.1, 1.0], [0.1, 0.3, 0.9, 1.0]])
        fit = tmp / "fit.glb"
        fit.write_bytes(gm.graft(bare, cards, name=fx.NAME, extras=fx.EXTRAS))
        for merge in (False, True):
            low = tmp / f"low_merge{int(merge)}.glb"
            res = refine.decimate_to(fit, 18, low, merge_vertices=merge)
            tag = f"merge_vertices={merge}"
            check(f"{tag}: ok", res.get("ok"), True)
            check(f"{tag}: tris_before / ratio", (res.get("tris_before"), res.get("ratio")), (36, 0.5))
            if not low.is_file():
                FAILS.append(f"{tag}: no output")
                continue
            print(f"  {tag}: tris after {res.get('tris')}")
            blob = low.read_bytes()
            lp = parse_glb(blob)
            names = [n.get("name") for n in lp["gltf"]["nodes"] if "mesh" in n]
            check(f"{tag}: garment node present", fx.NAME in names, True)
            if fx.NAME not in names:
                continue
            _p, lprim = prim_of(blob, fx.NAME)
            check(f"{tag}: COLOR_0 on the garment node", "COLOR_0" in lprim["attributes"], True)
            if "COLOR_0" not in lprim["attributes"]:
                continue
            got = gm.garment_arrays(blob).colors
            check(f"{tag}: garment_arrays colours read", got is not None, True)
            if got is None:
                continue
            got4 = got if got.shape[1] == 4 else np.hstack([got, np.ones((len(got), 1))])
            dist = np.min(np.abs(got4[:, None, :] - colours[None, :, :]).max(2), axis=1)
            check(f"{tag}: every colour within 2/255 of card A or B (max {dist.max():.5f})",
                  bool(dist.max() <= 2 / 255), True)
            nearest = np.argmin(np.abs(got4[:, None, :] - colours[None, :, :]).max(2), axis=1)
            check(f"{tag}: both card colours occur", sorted(set(nearest.tolist())), [0, 1])

    print("[5] real HairDeck file (informational)")
    real = Path.home() / "claude-out" / "hairdeck" / "hair_seed42_nohead.glb"
    if not real.is_file():
        print("  SKIP (no ~/claude-out/hairdeck/hair_seed42_nohead.glb)")
    else:
        Pr, Fr, Ur, Cr, mr = gm.card_arrays(real.read_bytes(), node="hair_cards")
        check("real: vertices / triangles", (len(Pr), len(Fr)), (12736, 30922))
        check("real: colours shape", None if Cr is None else Cr.shape, (12736, 4))
        check("real: alpha 1", bool(Cr is not None and np.all(Cr[:, 3] == 1.0)), True)
        check("real: doubleSided", mr.get("doubleSided"), True)

    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
