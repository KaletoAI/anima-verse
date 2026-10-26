"""Write native/fixtures/pairs/low_box.glb: a minimal binary glTF with one box mesh,
x 0.1..0.5, y -0.3..0.55, z -0.2..0 (no material, no skin) -- a model whose mesh bottom
is NOT at its origin, for the bind-anchoring case of `--check pairs` (fixtures/README.md
"Pairs world").

Usage:  python3 native/tools/box_glb.py native/fixtures/pairs/low_box.glb
"""
import json, struct, sys
x0, x1, y0, y1, z0, z1 = 0.1, 0.5, -0.3, 0.55, -0.2, 0.0
v = [(x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]
# index of (ix, iy, iz) = ix*4 + iy*2 + iz
def i(ix, iy, iz): return ix * 4 + iy * 2 + iz
quads = [
    (i(0,0,0), i(0,0,1), i(0,1,1), i(0,1,0)),  # -x
    (i(1,0,0), i(1,1,0), i(1,1,1), i(1,0,1)),  # +x
    (i(0,0,0), i(1,0,0), i(1,0,1), i(0,0,1)),  # -y
    (i(0,1,0), i(0,1,1), i(1,1,1), i(1,1,0)),  # +y
    (i(0,0,0), i(0,1,0), i(1,1,0), i(1,0,0)),  # -z
    (i(0,0,1), i(1,0,1), i(1,1,1), i(0,1,1)),  # +z
]
idx = []
for a, b, c, d in quads: idx += [a, b, c, a, c, d]
pos = b''.join(struct.pack('<3f', *p) for p in v)
ind = b''.join(struct.pack('<H', k) for k in idx)
ind += b'\0' * ((4 - len(ind) % 4) % 4)
bin_ = pos + ind
gltf = {
    "asset": {"version": "2.0", "generator": "anima-native fixture box_glb.py"},
    "scene": 0, "scenes": [{"nodes": [0]}],
    "nodes": [{"name": "Box", "mesh": 0}],
    "meshes": [{"name": "Box", "primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}],
    "buffers": [{"byteLength": len(bin_)}],
    "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(pos), "target": 34962},
                    {"buffer": 0, "byteOffset": len(pos), "byteLength": len(idx) * 2, "target": 34963}],
    "accessors": [{"bufferView": 0, "componentType": 5126, "count": 8, "type": "VEC3",
                   "min": [x0, y0, z0], "max": [x1, y1, z1]},
                  {"bufferView": 1, "componentType": 5123, "count": len(idx), "type": "SCALAR"}],
}
js = json.dumps(gltf, separators=(',', ':')).encode()
js += b' ' * ((4 - len(js) % 4) % 4)
out = b'glTF' + struct.pack('<II', 2, 12 + 8 + len(js) + 8 + len(bin_))
out += struct.pack('<I', len(js)) + b'JSON' + js + struct.pack('<I', len(bin_)) + b'BIN\0' + bin_
open(sys.argv[1], 'wb').write(out)
