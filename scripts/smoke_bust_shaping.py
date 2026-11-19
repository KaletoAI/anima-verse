"""A228 — the chest shaping of a shaping bodice (``app/core/bust_shaping.py``), checked against values derived by
hand from the field in the module docstring. No server, no world, no Blender.

Landmarks used throughout (not measured — given): under_y 1.10, band_y 1.25, centre_x 0, the chest wall flat at
z 0.10 (every bin), depth_m 0.10 (= FULL_DEPTH_M, so the strength is the lift), lift 1.
Constants: LIFT_M 0.05, COMPRESS 0.5, PROTRUSION_FULL_M 0.02, BELOW_M 0.03, RISE_M 0.02, ABOVE_M 0.08,
SIDE_M (0.17, 0.21). The rise ramp runs 1.07..1.12, the fall ramp 1.25..1.33.

  A (0.05, 1.20, 0.16): p 0.06 -> w_p 1; w_v 1 * (1 - 0) = 1; w_x 1 -> w 1.
     y' = 1.20 + 0.05 = 1.25;  z' = 0.16 - 0.5 * 0.06 = 0.13
  B (0.05, 1.29, 0.16): fall t = 0.04 / 0.08 = 0.5 -> smoothstep 0.5 -> w 0.5.
     y' = 1.29 + 0.025 = 1.315;  z' = 0.16 - 0.5 * 0.5 * 0.06 = 0.145
  C (0.05, 1.20, 0.11): p 0.01 -> t 0.5 -> w_p 0.5.
     y' = 1.225;  z' = 0.11 - 0.5 * 0.5 * 0.01 = 0.1075
  D (0.05, 1.20, 0.09): behind the wall -> unchanged
  E (0.05, 1.06, 0.16): under the rise ramp -> unchanged
  F (0.19, 1.20, 0.16): side t = 0.02 / 0.04 = 0.5 -> w_x 0.5.  y' = 1.225;  z' = 0.145
  G = A with depth_m 0.04: strength 0.4.  y' = 1.20 + 0.02 = 1.22;  z' = 0.16 - 0.5 * 0.4 * 0.06 = 0.148
  wall_at with wall [0.10, 0.12] (bin centres 0.01, 0.03): x 0.02 -> 0.11; x -0.02 -> 0.11; x 0.2 -> 0.12 (held).

No fold: along y, dy'/dy >= 1 - LIFT_M * 1.5 / ABOVE_M = 1 - 0.9375 = 0.0625 (smoothstep's slope peaks at 1.5 / width);
along z, dz'/dz = 1 - COMPRESS * (w + p dw/dp) >= 1 - 0.5 * (1 + 8/9) = 0.0556 (p dw/dp = 6 t^2 (1 - t) peaks at
8/9, t = 2/3). Sampled on a 1 mm grid below.

GLB: a skinned body primitive with A and D, a second skinned non-garment mesh (an extension part) with A, a garment
node with A, joints Base (0.05, 1.20, 0.05) -> Tip (0.05, 1.20, 0.16) under Root (0, 0, 0). After ``shape_glb``:
body A -> (0.05, 1.25, 0.13), D unchanged, the part's A moved alike, the garment's A unchanged; Tip's bind
position (0.05, 1.25, 0.13), its node translation (0, 0.05, 0.08) (relative to Base, which stays), every joint's
rest skin matrix (node world x inverse bind) the identity; the BIN chunk length unchanged (in-place rewrite).

Usage: ./.venv/bin/python scripts/smoke_bust_shaping.py
"""
import json
import struct
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import bust_shaping as bs  # noqa: E402  (pure numpy + glb_mesh, no storage)
from app.core import glb_mesh  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def close(a, b, tol=1e-6):
    return np.allclose(np.asarray(a, float), np.asarray(b, float), atol=tol)


LM = {"under_y": 1.10, "bust_y": 1.20, "band_y": 1.25, "centre_x": 0.0, "wall_z": [0.10] * bs.WALL_BINS,
      "depth_m": 0.10}

# --- constants the hand values above assume
check("constants", (bs.LIFT_M, bs.COMPRESS, bs.PROTRUSION_FULL_M, bs.BELOW_M, bs.RISE_M, bs.ABOVE_M, bs.SIDE_M,
                    bs.FULL_DEPTH_M) == (0.05, 0.5, 0.02, 0.03, 0.02, 0.08, (0.17, 0.21), 0.10))

pts = np.array([[0.05, 1.20, 0.16], [0.05, 1.29, 0.16], [0.05, 1.20, 0.11], [0.05, 1.20, 0.09],
                [0.05, 1.06, 0.16], [0.19, 1.20, 0.16]])
want = np.array([[0.05, 1.25, 0.13], [0.05, 1.315, 0.145], [0.05, 1.225, 0.1075], [0.05, 1.20, 0.09],
                 [0.05, 1.06, 0.16], [0.19, 1.225, 0.145]])
got = bs.displace(pts, LM, 1.0)
for name, g, w in zip("ABCDEF", got, want):
    check(f"point {name}", close(g, w), f"{g.round(5).tolist()} != {w.tolist()}")
g = bs.displace(pts[:1], {**LM, "depth_m": 0.04}, 1.0)[0]
check("point G (shallow chest, strength 0.4)", close(g, [0.05, 1.22, 0.148]), str(g.round(5).tolist()))
check("lift 0 moves nothing", close(bs.displace(pts, LM, 0.0), pts))

wl = {"centre_x": 0.0, "wall_z": [0.10, 0.12]}
check("wall_at interpolates and holds", close(bs.wall_at(np.array([0.02, -0.02, 0.2]), wl), [0.11, 0.11, 0.12]))

# --- no fold (1 mm grid through the region)
ys = np.arange(1.0, 1.40, 0.001)
col = bs.displace(np.column_stack([np.full_like(ys, 0.05), ys, np.full_like(ys, 0.16)]), LM, 1.0)[:, 1]
dy = np.diff(col) / 0.001
check("y' grows with y", dy.min() > 0.0625 - 0.02, f"min slope {dy.min():.4f}")
zs = np.arange(0.08, 0.30, 0.001)
row = bs.displace(np.column_stack([np.full_like(zs, 0.05), np.full_like(zs, 1.20), zs]), LM, 1.0)[:, 2]
dz = np.diff(row) / 0.001
check("z' grows with z", dz.min() > 0.0556 - 0.02, f"min slope {dz.min():.4f}")

# --- the gate: which pieces shape, the key token, the worn record
top = {"kind": "top"}
check("applies: top with lift", bs.applies(top, 1.0) and bs.applies({"kind": "dress"}, 0.3))
check("applies not: lift 0 / a skirt", not bs.applies(top, 0.0) and not bs.applies({"kind": "skirt"}, 1.0))
check("lift_of reads outfit_piece.lift", bs.lift_of({"outfit_piece": {"lift": 1.0}}) == 1.0
      and bs.lift_of({"outfit_piece": {}}) == 0.0 and bs.lift_of({"outfit_piece": {"lift": "x"}}) == 0.0)
check("key: no token without shaping", bs.key_tokens(top, {"outfit_piece": {}}) == [])
t1 = bs.key_tokens(top, {"outfit_piece": {"lift": 1.0}})
t5 = bs.key_tokens(top, {"outfit_piece": {"lift": 0.5}})
check("key: one token, changes with the lift", len(t1) == 1 and t1[0].startswith("shape:") and t1 != t5)
r_hi, r_lo = bs.record(LM, 1.0), bs.record(LM, 0.4)
worn = [{"template": True, "record": {"shaping": r_lo}}, {"template": True, "record": {"shaping": r_hi}},
        {"template": False, "record": {"shaping": bs.record(LM, 1.0)}}, {"template": True, "record": {}}]
check("worn_record: the strongest lift of the template drapes", bs.worn_record(worn) == r_hi)
check("worn_record: none", bs.worn_record([{"template": True, "record": {}}]) is None)


# --- a skinned GLB
def make_glb():
    blob = bytearray()
    views, accessors = [], []

    def add(arr, comp, typ, target=None, minmax=False):
        while len(blob) % 4:
            blob.append(0)
        raw = np.ascontiguousarray(arr).tobytes()
        view = {"buffer": 0, "byteOffset": len(blob), "byteLength": len(raw)}
        if target:
            view["target"] = target
        views.append(view)
        blob.extend(raw)
        acc = {"bufferView": len(views) - 1, "componentType": comp, "count": len(arr), "type": typ}
        if minmax:
            acc["min"] = np.asarray(arr).min(0).tolist()
            acc["max"] = np.asarray(arr).max(0).tolist()
        accessors.append(acc)
        return len(accessors) - 1

    def prim(points):
        p = np.asarray(points, "<f4")
        n = len(p)
        j = np.zeros((n, 4), "<u2")
        j[:, 0] = 2                                   # all on Tip
        w = np.zeros((n, 4), "<f4")
        w[:, 0] = 1.0
        f = np.array([0, 1, 2], "<u2") if n >= 3 else np.array([0, 0, 0], "<u2")
        return {"attributes": {"POSITION": add(p, 5126, "VEC3", 34962, True), "JOINTS_0": add(j, 5123, "VEC4", 34962),
                               "WEIGHTS_0": add(w, 5126, "VEC4", 34962)},
                "indices": add(f, 5123, "SCALAR", 34963), "mode": 4}
    A, D = [0.05, 1.20, 0.16], [0.05, 1.20, 0.09]
    meshes = [{"name": "body", "primitives": [prim([A, D, [0.0, 0.5, 0.0]])]},
              {"name": "part", "primitives": [prim([A, [0.0, 0.5, 0.0], [0.0, 0.6, 0.0]])]},
              {"name": "garment_clothing_x", "primitives": [prim([A, [0.0, 0.5, 0.0], [0.0, 0.6, 0.0]])]}]
    world = {"Root": [0, 0, 0], "Base": [0.05, 1.20, 0.05], "Tip": [0.05, 1.20, 0.16]}
    nodes = [{"name": "Root", "children": [1, 4, 5, 6]},
             {"name": "Base", "translation": world["Base"], "children": [2]},
             {"name": "Tip", "translation": [0.0, 0.0, 0.11]},
             {"name": "unused"},
             {"name": "Body", "mesh": 0, "skin": 0},
             {"name": "Part", "mesh": 1, "skin": 0},
             {"name": "garment_clothing_x", "mesh": 2, "skin": 0,
              "extras": {"garment": {"kind": "clothing", "item_id": "x", "fsig": "f"}}}]
    ibm = []
    for name in ("Root", "Base", "Tip"):
        m = np.eye(4)
        m[:3, 3] = -np.array(world[name])
        ibm.append(m.T.astype("<f4").reshape(16))
    ibm_acc = add(np.stack(ibm), 5126, "MAT4")
    while len(blob) % 4:
        blob.append(0)
    gltf = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}], "nodes": nodes, "meshes": meshes,
            "skins": [{"joints": [0, 1, 2], "inverseBindMatrices": ibm_acc}],
            "accessors": accessors, "bufferViews": views, "buffers": [{"byteLength": len(blob)}]}
    text = json.dumps(gltf).encode()
    text += b" " * ((4 - len(text) % 4) % 4)
    body = struct.pack("<I", len(text)) + b"JSON" + text + struct.pack("<I", len(blob)) + b"BIN\0" + bytes(blob)
    return b"glTF" + struct.pack("<II", 2, 12 + len(body)) + body


src = make_glb()
out = bs.shape_glb(src, bs.record(LM, 1.0))
def bin_len(b):
    j = struct.unpack_from("<I", b, 12)[0]
    return struct.unpack_from("<I", b, 20 + j)[0]


check("in-place: same BIN chunk length", bin_len(out) == bin_len(src))
parsed = glb_mesh._parse(out, "x")
gl = parsed["gltf"]
pos = [np.asarray(glb_mesh.accessor_array(parsed, m["primitives"][0]["attributes"]["POSITION"])) for m in gl["meshes"]]
check("body A shaped", close(pos[0][0], [0.05, 1.25, 0.13], 1e-6), str(pos[0][0]))
check("body D unchanged", close(pos[0][1], [0.05, 1.20, 0.09], 1e-6))
check("part A shaped alike", close(pos[1][0], [0.05, 1.25, 0.13], 1e-6))
check("garment A untouched", close(pos[2][0], [0.05, 1.20, 0.16], 1e-6))
acc = gl["accessors"][gl["meshes"][0]["primitives"][0]["attributes"]["POSITION"]]
check("POSITION max follows", close(acc["max"], [0.05, 1.25, 0.13], 1e-6), str(acc["max"]))
heads = glb_mesh.body_arrays(out).joint_positions
check("Tip bind moved", close(heads["tip"], [0.05, 1.25, 0.13], 1e-6), str(heads.get("tip")))
check("Base bind kept", close(heads["base"], [0.05, 1.20, 0.05], 1e-6))
check("Tip node translation", close(gl["nodes"][2]["translation"], [0.0, 0.05, 0.08], 1e-6),
      str(gl["nodes"][2]["translation"]))
ibm = glb_mesh.mat4_array(parsed, gl["skins"][0]["inverseBindMatrices"])
parent = {c: i for i, n in enumerate(gl["nodes"]) for c in n.get("children") or []}


def world_of(i):
    m = glb_mesh._local_matrix(gl["nodes"][i])
    return m if i not in parent else world_of(parent[i]) @ m


check("rest skin matrices stay identity",
      all(close(world_of(j) @ ibm[k], np.eye(4), 1e-5) for k, j in enumerate(gl["skins"][0]["joints"])))
check("nothing to shape returns the same bytes", bs.shape_glb(src, bs.record(LM, 0.0)) is src)

print(f"\n{len(FAILS)} failed" if FAILS else "\nall passed")
sys.exit(1 if FAILS else 0)
