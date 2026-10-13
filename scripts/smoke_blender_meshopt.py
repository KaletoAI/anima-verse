#!/usr/bin/env python3
"""Check lossless delivery compression and Blender import compatibility.

Usage: ALSOFT_DRIVERS=null .venv/bin/python scripts/smoke_blender_meshopt.py [--out-dir /tmp/meshopt-smoke]

Hand-derived expectations: 64 cubes, each with six faces * four vertices =
1536 vertices. Interleaved POSITION/NORMAL/TEXCOORD_0 uses (3+3+2)*4 = 32
bytes per vertex: view 0 is ATTRIBUTES/count 1536/stride 32. Each face has
six uint16 indices: 64*6*6 = 2304 indices, view 1 is TRIANGLES/2304/2.
A VEC3 float morph target is view 2, ATTRIBUTES/1536/12. Views 3 and 4
are image and animation data, respectively, and must remain raw. JSON
indices and all fields outside buffers/views/extension declarations stay
identical. Decoder output must equal every source byte. Real puppet output
must be <95% of input, with unchanged node/mesh/accessor/skin counts.
The absent filter defaults to NONE; explicitly writing NONE crashes Blender
5.2's importer. Since decoded bytes, accessor layouts, topology and skin/node
metadata are unchanged, importing original and copy with identical Blender
settings must yield equal mesh vertex/triangle counts and joint (bone) names.

Eligibility guards by hand: sharing accessor 0 with animation, skin, an image,
an extension or an unused accessor leaves only views {1,2} eligible. Sparse
indices/values in views 1/2 plus base view 0 leaves zero eligible views.
A line primitive's uint32 view 1 has 2304 indices at stride 4, mode INDICES.
A single triangle with three VEC3 positions (36 bytes) plus three uint16
indices (6 bytes) is too small to cover extension overhead: it must skip.
"""
import argparse
import copy
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.blender import runner

EXT = "EXT_meshopt_compression"


def pack_glb(g, binary):
    j = json.dumps(g, separators=(",", ":")).encode()
    j += b" " * (-len(j) % 4)
    binary += b"\0" * (-len(binary) % 4)
    return (struct.pack("<III", 0x46546C67, 2, 28 + len(j) + len(binary))
            + struct.pack("<II", len(j), 0x4E4F534A) + j
            + struct.pack("<II", len(binary), 0x004E4942) + binary)


def unpack_glb(data):
    n = struct.unpack_from("<I", data, 12)[0]
    return json.loads(data[20:20+n]), data[28+n:]


def fixture():
    vertices, indices = bytearray(), []
    corners = [(-1,-1), (1,-1), (1,1), (-1,1)]
    for cube in range(64):
        for face in range(6):
            for x, y in corners:
                vertices.extend(struct.pack("<8f", x, y, float(face), 0, 0, 1, (x+1)/2, (y+1)/2))
            base = cube*24 + face*4
            indices.extend(base+i for i in (0,1,2,0,2,3))
    streams = [bytes(vertices), struct.pack("<2304H", *indices),
               struct.pack("<3f", 0, 0, 0)*1536, b"image-preserved!"*16,
               struct.pack("<4f", 0, 1, 2, 3)]
    binary, views = bytearray(), []
    for data in streams:
        binary.extend(b"\0" * (-len(binary) % 4))
        views.append({"buffer": 0, "byteOffset": len(binary), "byteLength": len(data)})
        binary.extend(data)
    views[0]["byteStride"] = 32
    g = {"asset": {"version": "2.0"}, "buffers": [{"byteLength": len(binary)}],
         "bufferViews": views,
         "accessors": [
             {"bufferView": 0, "byteOffset": 0, "componentType": 5126, "count": 1536, "type": "VEC3"},
             {"bufferView": 0, "byteOffset": 12, "componentType": 5126, "count": 1536, "type": "VEC3"},
             {"bufferView": 0, "byteOffset": 24, "componentType": 5126, "count": 1536, "type": "VEC2"},
             {"bufferView": 1, "componentType": 5123, "count": 2304, "type": "SCALAR"},
             {"bufferView": 2, "componentType": 5126, "count": 1536, "type": "VEC3"},
             {"bufferView": 4, "componentType": 5126, "count": 4, "type": "SCALAR"}],
         "meshes": [{"name": "Cubes", "primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1, "TEXCOORD_0": 2}, "indices": 3, "targets": [{"POSITION": 4}]}]}],
         "nodes": [{"mesh": 0, "name": "Fixture"}], "images": [{"bufferView": 3, "mimeType": "image/png"}],
         "animations": [{"samplers": [{"input": 5, "output": 5}], "channels": []}],
         "extras": {"preserved": [1, "fixture"]}, "extensionsUsed": ["EXAMPLE_metadata"],
         "extensions": {"EXAMPLE_metadata": {"name": "unchanged"}}}
    return g, bytes(binary)


def decoder():
    # Independent verification uses the bundled shared library, without bpy.
    exe = Path(runner.status()["executable"])
    lib = ctypes.CDLL(str(exe.parent / "lib/libbf_intern_meshopt_bridge.so"))
    for name in ("decodeVertexBuffer", "decodeIndexBuffer", "decodeIndexSequence"):
        fn = getattr(lib, name)
        fn.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t]
        fn.restype = ctypes.c_int
    return lib


def verify(source, output):
    sg, sb = unpack_glb(source.read_bytes())
    g, binary = unpack_glb(output.read_bytes())
    lib = decoder()
    for key in sg:
        if key not in ("buffers", "bufferViews", "extensionsUsed", "extensionsRequired"):
            assert g[key] == sg[key], key
    assert len(g["bufferViews"]) == len(sg["bufferViews"])
    assert len(g["buffers"]) == 2 and "uri" not in g["buffers"][1]
    assert g["buffers"][1]["extensions"][EXT] == {"fallback": True}
    assert EXT in g["extensionsUsed"] and g["extensionsRequired"] == [EXT]
    for i, v in enumerate(g["bufferViews"]):
        old = sg["bufferViews"][i]
        raw = sb[old.get("byteOffset", 0):old.get("byteOffset", 0)+old["byteLength"]]
        ext = v.get("extensions", {}).get(EXT)
        if ext:
            assert v["buffer"] == 1
            for key in ("byteOffset", "byteLength", "byteStride", "target", "name", "extras"):
                assert v.get(key) == old.get(key), (i, key)
            assert ext["buffer"] == 0 and ext["byteOffset"] % 4 == 0
            assert "filter" not in ext, (i, ext)
            assert ext["count"]*ext["byteStride"] == v["byteLength"]
            assert v.get("byteOffset", 0)+v["byteLength"] <= g["buffers"][1]["byteLength"]
            encoded = binary[ext["byteOffset"]:ext["byteOffset"]+ext["byteLength"]]
            dst = ctypes.create_string_buffer(len(raw))
            fn = getattr(lib, {"ATTRIBUTES": "decodeVertexBuffer", "TRIANGLES": "decodeIndexBuffer", "INDICES": "decodeIndexSequence"}[ext["mode"]])
            assert fn(dst, ext["count"], ext["byteStride"], encoded, len(encoded)) == 0
            assert dst.raw == raw, i
        else:
            assert v["buffer"] == 0 and v.get("byteOffset", 0) % 4 == 0
            assert binary[v.get("byteOffset", 0):v.get("byteOffset", 0)+v["byteLength"]] == raw, i
    return g


def verify_blender_import(source, output):
    # Reset between imports so object and bone naming cannot gain suffixes.
    program = """
import bpy
import sys

assert bpy.app.version[:2] == (5, 2), bpy.app.version_string
def summary(path):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    assert bpy.ops.import_scene.gltf(filepath=path) == {'FINISHED'}, path
    meshes, joints = [], []
    for obj in bpy.context.scene.objects:
        if obj.type == 'MESH':
            obj.data.calc_loop_triangles()
            meshes.append((obj.name, len(obj.data.vertices), len(obj.data.loop_triangles)))
        elif obj.type == 'ARMATURE':
            joints.append((obj.name, sorted(bone.name for bone in obj.data.bones)))
    assert meshes and joints and any(bones for _, bones in joints), path
    assert all(vertices > 0 and triangles > 0 for _, vertices, triangles in meshes), path
    return sorted(meshes), sorted(joints)

source, output = sys.argv[sys.argv.index('--') + 1:]
original = summary(source)
compressed = summary(output)
assert original == compressed, (original, compressed)
print('Blender import parity:', original)
"""
    result = subprocess.run(
        [runner.status()["executable"], "--background", "--factory-startup",
         "--python-exit-code", "1", "--python-expr", program,
         "--", str(source), str(output)],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    print(next(line for line in result.stdout.splitlines() if line.startswith("Blender import parity:")))


def eligibility_guards():
    spec = importlib.util.spec_from_file_location("delivery_meshopt_job", Path(__file__).resolve().parents[1] / "app/blender/scripts/meshopt.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    g, _ = fixture()
    assert set(module.candidates(g)) == {0, 1, 2}
    for role in ("animation", "skin", "image", "extension", "unused"):
        doc = copy.deepcopy(g)
        if role == "animation":
            doc["animations"][0]["samplers"][0]["output"] = 0
        elif role == "skin":
            doc["skins"] = [{"inverseBindMatrices": 0}]
        elif role == "image":
            doc["images"].append({"bufferView": 0})
        elif role == "extension":
            doc["nodes"][0]["extensions"] = {"EXT_mesh_gpu_instancing": {"attributes": {"TRANSLATION": 0}}}
        else:
            doc["accessors"].append(dict(doc["accessors"][0]))
        assert set(module.candidates(doc)) == {1, 2}, role
    doc = copy.deepcopy(g)
    doc["accessors"][0]["sparse"] = {"count": 1, "indices": {"bufferView": 1}, "values": {"bufferView": 2}}
    assert not module.candidates(doc)
    for stride in (6, 260):
        doc = copy.deepcopy(g)
        doc["bufferViews"][0]["byteStride"] = stride
        assert set(module.candidates(doc)) == {1, 2}
    # A failed byte check is fatal, even if the native decoder reports success.
    class BadDecoder:
        def encodeVertexBufferBound(self, count, stride):
            return 16
        def encodeVertexBuffer(self, *args):
            return 16
        def decodeVertexBuffer(self, *args):
            return 0
    try:
        module.encode(BadDecoder(), b"x"*32, "ATTRIBUTES", 1, 32)
    except RuntimeError as error:
        assert "byte equality" in str(error)
    else:
        raise AssertionError("byte mismatch was accepted")


def main():
    os.environ["ALSOFT_DRIVERS"] = "null"
    eligibility_guards()
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("--out-dir", type=Path)
    opts = args.parse_args()
    with tempfile.TemporaryDirectory(prefix="smoke-meshopt-") as tmp:
        root = opts.out_dir or Path(tmp)
        root.mkdir(parents=True, exist_ok=True)
        g, b = fixture()
        src = root / "fixture.glb"
        src.write_bytes(pack_glb(g, b))
        digest = hashlib.sha256(src.read_bytes()).digest()
        res = runner.run("meshopt", inputs={"model": src}, out_dir=root / "fixture-out")
        assert res["ok"] and res["outputs"], res
        output = Path(res["outputs"]["model"])
        out = verify(src, output)
        assert [(v["extensions"][EXT]["mode"], v["extensions"][EXT]["count"], v["extensions"][EXT]["byteStride"]) for v in out["bufferViews"][:3]] == [("ATTRIBUTES", 1536, 32), ("TRIANGLES", 2304, 2), ("ATTRIBUTES", 1536, 12)]
        assert all(EXT not in v.get("extensions", {}) for v in out["bufferViews"][3:])
        assert hashlib.sha256(src.read_bytes()).digest() == digest
        # Non-triangle uint32 indices exercise the sequence codec directly.
        lines = copy.deepcopy(g)
        lines["meshes"][0]["primitives"][0]["mode"] = 1
        lines["accessors"][3]["componentType"] = 5125
        start = g["bufferViews"][1]["byteOffset"]
        end = start + g["bufferViews"][1]["byteLength"]
        wide = struct.pack("<2304I", *struct.unpack("<2304H", b[start:end]))
        lb = b[:start] + wide + b[end:]
        lines["bufferViews"][1]["byteLength"] = 9216
        for v in lines["bufferViews"][2:]:
            v["byteOffset"] += 4608
        lines["buffers"][0]["byteLength"] = len(lb)
        line_src = root / "lines.glb"
        line_src.write_bytes(pack_glb(lines, lb))
        res = runner.run("meshopt", inputs={"model": line_src}, out_dir=root / "lines-out")
        assert res["ok"] and res["outputs"], res
        lg = verify(line_src, Path(res["outputs"]["model"]))
        assert lg["bufferViews"][1]["extensions"][EXT]["mode"] == "INDICES"
        assert lg["bufferViews"][1]["extensions"][EXT]["byteStride"] == 4
        # Extension overhead exceeds any saving on this 42-byte geometry.
        tiny = {"asset": {"version": "2.0"}, "buffers": [{"byteLength": 44}],
                "bufferViews": [{"buffer": 0, "byteLength": 36}, {"buffer": 0, "byteOffset": 36, "byteLength": 6}],
                "accessors": [{"bufferView": 0, "componentType": 5126, "type": "VEC3", "count": 3}, {"bufferView": 1, "componentType": 5123, "type": "SCALAR", "count": 3}],
                "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}]}
        tiny_src = root / "tiny.glb"
        tiny_src.write_bytes(pack_glb(tiny, struct.pack("<9f3H", 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 1, 2)))
        res = runner.run("meshopt", inputs={"model": tiny_src}, out_dir=root / "tiny-out")
        assert res["ok"] and res["data"].get("skipped") == "delivery copy saves less than 5 percent" and not res["outputs"], res
        puppet = Path(__file__).resolve().parents[1] / "shared/models/rig/puppet.glb"
        res = runner.run("meshopt", inputs={"model": puppet}, out_dir=root / "puppet-out")
        assert res["ok"] and res["outputs"], res
        target = Path(res["outputs"]["model"])
        assert target.stat().st_size < puppet.stat().st_size * .95
        pg = verify(puppet, target)
        original, _ = unpack_glb(puppet.read_bytes())
        for key in ("nodes", "meshes", "accessors", "skins"):
            assert len(pg.get(key, [])) == len(original.get(key, []))
        verify_blender_import(puppet, target)
        for name, doc, binary in [("nothing", {"asset": {"version": "2.0"}, "buffers": [{"byteLength": 16}], "bufferViews": [{"buffer": 0, "byteLength": 16}], "images": [{"bufferView": 0}]}, b"x"*16), ("required", dict(g, extensionsRequired=["EXAMPLE_metadata"]), b), ("compressed", *unpack_glb(target.read_bytes()))]:
            p = root / f"{name}.glb"
            p.write_bytes(pack_glb(doc, binary))
            res = runner.run("meshopt", inputs={"model": p}, out_dir=root / f"{name}-out")
            assert res["ok"] and res["data"].get("skipped") and not res["outputs"], res
        print(f"Puppet: {puppet.stat().st_size} -> {target.stat().st_size} bytes")
    print("PASS: meshopt layout, omitted filter, lossless bytes, Blender puppet import and skip gates")


if __name__ == "__main__":
    main()
