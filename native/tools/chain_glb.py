"""Write native/fixtures/secondary/chain.glb: a minimal skinned binary glTF for `--check secondary`
(fixtures/README.md "Secondary motion").

Joints (all bind rotations identity, world positions at bind):
  Root (0,0,0)
    anchor (0,0,0) -> c1 (0,0,0) -> c2 (0,-1,0)      the chain of shared/test-vectors/secondary_chain.json
    mixamorig:Spine1 (0,0,0) -> mixamorig:Spine2 (0,1,0) -> B (0,1,1)
                                                      the rig of scripts/smoke_extension_rig_anchor_blend.mjs;
                                                      B carries extras {"anchor_blend": {Spine1: .5, Spine2: .5,
                                                      Missing: .3}}
Vertices: c1's ring (+-0.1, -0.5, 0) / (0, -0.5, +-0.1), c2's ring at y -1.5 (both two triangles), one triangle
at (0, 1, 1.5) on B. One plain material (base colour, double sided) so the normal correction has a surface.

Usage:  python3 native/tools/chain_glb.py native/fixtures/secondary/chain.glb
"""
import json, struct, sys

joints = [("Root", None, (0, 0, 0)), ("anchor", 0, (0, 0, 0)), ("c1", 1, (0, 0, 0)), ("c2", 2, (0, -1, 0)),
          ("mixamorig:Spine1", 0, (0, 0, 0)), ("mixamorig:Spine2", 4, (0, 1, 0)), ("B", 5, (0, 0, 1))]
world = {}
for i, (name, parent, t) in enumerate(joints):
    base = world[parent] if parent is not None else (0, 0, 0)
    world[i] = tuple(base[k] + t[k] for k in range(3))

ring = lambda y: [(0.1, y, 0), (-0.1, y, 0), (0, y, 0.1), (0, y, -0.1)]
verts = ring(-0.5) + ring(-1.5) + [(0, 1, 1.5), (0.01, 1, 1.5), (0, 1.01, 1.5)]
vjoint = [2] * 4 + [3] * 4 + [6] * 3
idx = [0, 2, 1, 1, 3, 0, 4, 6, 5, 5, 7, 4, 8, 9, 10]

P = b''.join(struct.pack('<3f', *v) for v in verts)
J = b''.join(struct.pack('<4B', j, 0, 0, 0) for j in vjoint)
W = b''.join(struct.pack('<4f', 1, 0, 0, 0) for _ in verts)
IB = b''.join(struct.pack('<16f', 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, -world[i][0], -world[i][1], -world[i][2], 1)
              for i in range(len(joints)))
I = b''.join(struct.pack('<H', k) for k in idx)
I += b'\0' * ((4 - len(I) % 4) % 4)
blobs = [P, J, W, IB, I]
views, off = [], 0
for b in blobs:
    views.append({"buffer": 0, "byteOffset": off, "byteLength": len(b)})
    off += len(b)
bin_ = b''.join(blobs)

nodes = []
for i, (name, parent, t) in enumerate(joints):
    node = {"name": name, "translation": list(t)}
    kids = [k for k, j in enumerate(joints) if j[1] == i]
    if kids:
        node["children"] = kids
    if name == "B":
        node["extras"] = {"anchor_blend": {"mixamorig:Spine1": 0.5, "mixamorig:Spine2": 0.5, "mixamorig:Missing": 0.3}}
    nodes.append(node)
nodes.append({"name": "Body", "mesh": 0, "skin": 0})
xs = [v[0] for v in verts]; ys = [v[1] for v in verts]; zs = [v[2] for v in verts]
gltf = {
    "asset": {"version": "2.0", "generator": "anima-native fixture chain_glb.py"},
    "scene": 0, "scenes": [{"nodes": [0, len(joints)]}],
    "nodes": nodes,
    "skins": [{"joints": list(range(len(joints))), "inverseBindMatrices": 3, "skeleton": 0}],
    "materials": [{"name": "Plain", "doubleSided": True,
                   "pbrMetallicRoughness": {"baseColorFactor": [0.8, 0.6, 0.5, 1], "metallicFactor": 0, "roughnessFactor": 0.9}}],
    "meshes": [{"name": "Body", "primitives": [{"attributes": {"POSITION": 0, "JOINTS_0": 1, "WEIGHTS_0": 2},
                                                "indices": 4, "material": 0}]}],
    "buffers": [{"byteLength": len(bin_)}],
    "bufferViews": views,
    "accessors": [
        {"bufferView": 0, "componentType": 5126, "count": len(verts), "type": "VEC3",
         "min": [min(xs), min(ys), min(zs)], "max": [max(xs), max(ys), max(zs)]},
        {"bufferView": 1, "componentType": 5121, "count": len(verts), "type": "VEC4"},
        {"bufferView": 2, "componentType": 5126, "count": len(verts), "type": "VEC4"},
        {"bufferView": 3, "componentType": 5126, "count": len(joints), "type": "MAT4"},
        {"bufferView": 4, "componentType": 5123, "count": len(idx), "type": "SCALAR"},
    ],
}
js = json.dumps(gltf, separators=(',', ':')).encode()
js += b' ' * ((4 - len(js) % 4) % 4)
out = b'glTF' + struct.pack('<II', 2, 12 + 8 + len(js) + 8 + len(bin_))
out += struct.pack('<I', len(js)) + b'JSON' + js + struct.pack('<I', len(bin_)) + b'BIN\0' + bin_
open(sys.argv[1], 'wb').write(out)
