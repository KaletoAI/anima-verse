"""A228 — the chest shaping of a shaping bodice (``app/core/bust_shaping.py``), checked against values derived by
hand from the field in the module docstring. No server, no world, no Blender.

Landmarks used throughout (not measured — given): under_y 1.10, band_y 1.25, centre_x 0, the chest wall flat at
z 0.10 (every bin), depth_m 0.10 (>= FULL_DEPTH_M 0.08, so the strength is the lift), lift 1.
Constants: LIFT_M 0.05, COMPRESS 0.5, LIFT_RAMP_M 0.06, BELOW_M 0.03, RISE_M 0.02, ABOVE_M 0.12,
SIDE_M (0.16, 0.20). The rise ramp runs 1.07..1.12, the fall ramp 1.25..1.37.

  A (0.05, 1.20, 0.16): p 0.06 -> lift ramp 1; w_v 1; w_x 1 -> base 1.
     y' = 1.20 + 0.05 = 1.25;  z' = 0.16 - 0.5 * 0.06 = 0.13
  B (0.05, 1.31, 0.16): fall t = 0.06 / 0.12 = 0.5 -> smoothstep 0.5 -> base 0.5.
     y' = 1.31 + 0.025 = 1.335;  z' = 0.16 - 0.5 * 0.5 * 0.06 = 0.145
  C (0.05, 1.20, 0.13): p 0.03 -> lift ramp t 0.5 -> 0.5; the gathering has no ramp (base 1).
     y' = 1.225;  z' = 0.13 - 0.5 * 0.03 = 0.115
  D (0.05, 1.20, 0.09): behind the wall -> unchanged
  E (0.05, 1.06, 0.16): under the rise ramp -> unchanged
  F (0.18, 1.20, 0.16): side t = 0.02 / 0.04 = 0.5 -> w_x 0.5.  y' = 1.225;  z' = 0.145
  G = A with depth_m 0.04: strength 0.04 / 0.08 = 0.5.  y' = 1.20 + 0.025 = 1.225;  z' = 0.16 - 0.5 * 0.5 * 0.06 = 0.145
  wall_at with wall [0.10, 0.12] (bin centres 0.01, 0.03): x 0.02 -> 0.11; x -0.02 -> 0.11; x 0.2 -> 0.12 (held).

No fold (review H1): the diagonal terms are bounded by hand — d y'/dy >= 1 - LIFT_M * 1.5 / ABOVE_M = 0.375
(smoothstep's slope peaks at 1.5 / width), d z'/dz = 1 - COMPRESS * base >= 0.5; the cross terms
(d y'/dz = LIFT_M * base * 1.5 / LIFT_RAMP_M <= 1.25, d z'/dy = -COMPRESS * p * d base/dy) are what the old 2 cm
ramp made fold (det -0.116). The full 3x3 Jacobian determinant is sampled at strength 1 on a (x, y, p) grid
(central differences, 0.1 mm) and must stay above 0.1 everywhere; a shaped dome (a sheet in front of the wall) must
keep every triangle's area ratio above 0.1 and no face normal may turn by more than 90 deg.

Capsule (review M3): a_pos = A, b_pos = D, r 0.05 -> a_pos (0.05, 1.25, 0.13), b_pos unchanged; the radius takes the
compression at the mid point (0.05, 1.20, 0.125): base 1 -> r = 0.05 x (1 - 0.5) = 0.025. A capsule without
positions stays as it is.

Lift resolver (review M4, ``extension_rig.piece_lift``) with defaults {underwear_top: 0.25, top: 0}: a bra-slot piece
without own lift 0.25; the same as a partial cover 0.125; own 1.0 on top 1.0; a skirt (no slot hit) None.

GLB: a skinned body primitive with A and D, a second skinned non-garment mesh (an extension part) with A, a garment
node with A, joints Base (0.05, 1.20, 0.05) -> Tip (0.05, 1.20, 0.16) under Root (0, 0, 0). After ``shape_glb``:
body A -> (0.05, 1.25, 0.13), D unchanged, the part's A moved alike, the garment's A unchanged; Tip's bind
position (0.05, 1.25, 0.13); Base is Tip's only parent, so the chain moves as a unit: Base takes Tip's displacement
(0, 0.05, -0.03) -> (0.05, 1.25, 0.02), Tip's node translation stays (0, 0, 0.11); every joint's
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
check("constants", (bs.LIFT_M, bs.COMPRESS, bs.LIFT_RAMP_M, bs.BELOW_M, bs.RISE_M, bs.ABOVE_M, bs.SIDE_M,
                    bs.FULL_DEPTH_M) == (0.05, 0.5, 0.06, 0.03, 0.02, 0.12, (0.16, 0.20), 0.08))

pts = np.array([[0.05, 1.20, 0.16], [0.05, 1.31, 0.16], [0.05, 1.20, 0.13], [0.05, 1.20, 0.09],
                [0.05, 1.06, 0.16], [0.18, 1.20, 0.16]])
want = np.array([[0.05, 1.25, 0.13], [0.05, 1.335, 0.145], [0.05, 1.225, 0.115], [0.05, 1.20, 0.09],
                 [0.05, 1.06, 0.16], [0.18, 1.225, 0.145]])
got = bs.displace(pts, LM, 1.0)
for name, g, w in zip("ABCDEF", got, want):
    check(f"point {name}", close(g, w), f"{g.round(5).tolist()} != {w.tolist()}")
g = bs.displace(pts[:1], {**LM, "depth_m": 0.04}, 1.0)[0]
check("point G (shallow chest, strength 0.5)", close(g, [0.05, 1.225, 0.145]), str(g.round(5).tolist()))
check("lift 0 moves nothing", close(bs.displace(pts, LM, 0.0), pts))

wl = {"centre_x": 0.0, "wall_z": [0.10, 0.12]}
check("wall_at interpolates and holds", close(bs.wall_at(np.array([0.02, -0.02, 0.2]), wl), [0.11, 0.11, 0.12]))

# --- no fold: the full Jacobian determinant on a grid at strength 1
xs, ys, ps = np.arange(-0.18, 0.181, 0.01), np.arange(1.0, 1.45, 0.002), np.arange(-0.01, 0.15, 0.002)
X, Y, Z = np.meshgrid(xs, ys, ps + 0.10, indexing="ij")
G = np.column_stack([X.ravel(), Y.ravel(), Z.ravel()])
h = 1e-4
J = np.zeros((len(G), 3, 3))
for k in range(3):
    d = np.zeros(3)
    d[k] = h
    J[:, :, k] = (bs.displace(G + d, LM, 1.0) - bs.displace(G - d, LM, 1.0)) / (2 * h)
det = np.linalg.det(J)
check("Jacobian determinant > 0.1 everywhere (strength 1)", det.min() > 0.1, f"min {det.min():.4f}")
print(f"     (det min {det.min():.4f})")

# a dome in front of the wall, triangulated: no face collapses or flips
u, v = np.meshgrid(np.linspace(-0.16, 0.16, 65), np.linspace(1.0, 1.42, 85), indexing="ij")
dome = 0.10 + 0.12 * np.exp(-(((np.abs(u) - 0.08) / 0.06) ** 2) - ((v - 1.17) / 0.07) ** 2)
S = np.column_stack([u.ravel(), v.ravel(), dome.ravel()])
nu, nv = u.shape
idx = np.arange(nu * nv).reshape(nu, nv)
F = np.concatenate([np.stack([idx[:-1, :-1].ravel(), idx[1:, :-1].ravel(), idx[1:, 1:].ravel()], 1),
                    np.stack([idx[:-1, :-1].ravel(), idx[1:, 1:].ravel(), idx[:-1, 1:].ravel()], 1)])


def face_n(P):
    return np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]])


n0, n1 = face_n(S), face_n(bs.displace(S, LM, 1.0))
ratio = np.linalg.norm(n1, axis=1) / np.linalg.norm(n0, axis=1)
turn = np.einsum("ij,ij->i", n0, n1)
check("dome: every face keeps > 0.1 of its area", ratio.min() > 0.1, f"min {ratio.min():.4f}")
check("dome: no face flips", turn.min() > 0, f"min dot {turn.min():.3g}")
print(f"     (dome area ratio min {ratio.min():.3f})")

# --- capsules
col = {"version": 9, "capsules": [{"id": "c", "a_pos": [0.05, 1.20, 0.16], "b_pos": [0.05, 1.20, 0.09], "r": 0.05},
                                  {"id": "leg", "a": "x", "b": "y", "r": 0.1}]}
sc = bs.shape_collision(col, bs.record(LM, 1.0))
check("capsule a_pos shaped", close(sc["capsules"][0]["a_pos"], [0.05, 1.25, 0.13], 1e-4), str(sc["capsules"][0]))
check("capsule b_pos kept", close(sc["capsules"][0]["b_pos"], [0.05, 1.20, 0.09], 1e-4))
check("capsule radius gathered", abs(sc["capsules"][0]["r"] - 0.025) < 1e-4, str(sc["capsules"][0]["r"]))
check("capsule without positions kept", sc["capsules"][1] == col["capsules"][1] and col["capsules"][0]["r"] == 0.05)

# --- the lift resolver and the worn set
from app.core import extension_rig  # noqa: E402
DEF = {"underwear_top": 0.25, "top": 0.0}
check("piece_lift: slot default", extension_rig.piece_lift(None, {"underwear_top"}, set(), DEF) == 0.25)
check("piece_lift: partial cover half", extension_rig.piece_lift(None, set(), {"underwear_top"}, DEF) == 0.125)
check("piece_lift: own value", extension_rig.piece_lift(1.0, {"top"}, set(), DEF) == 1.0)
check("piece_lift: no slot", extension_rig.piece_lift(1.0, {"legs"}, set(), DEF) is None)
extension_rig.clothing_lift_slots = lambda: dict(DEF)


def tpl(kind, lift=None, slots=("top",)):
    op = {"mesh_mode": "template", "slots": list(slots), "covers": [], "partially_covers": [],
          "template": {"params": {"kind": kind}}}
    if lift is not None:
        op["lift"] = lift
    return {"outfit_piece": op}


ITEMS = {"top1": tpl("top", 1.0), "top0": tpl("top"), "jacket": tpl("jacket", None, ("jacket",)),
         "skirt": tpl("skirt", None, ("legs",)), "dress5": tpl("dress", 0.5)}
import app.models.inventory as inventory  # noqa: E402
inventory.get_item = lambda iid: ITEMS.get(iid)
check("shapes_chest: top lift 1 yes, top default 0 no", bs.shapes_chest(ITEMS["top1"]) and not bs.shapes_chest(ITEMS["top0"]))
check("set_lift: strongest of the set", bs.set_lift(["top1", "dress5", "skirt"]) == 1.0 and bs.set_lift(["top0", "skirt"]) == 0.0)
tj = bs.key_tokens("jacket", ITEMS["jacket"], ["top1"])
tt = bs.key_tokens("top1", ITEMS["top1"], ["jacket"])
check("key: a jacket over a shaping top carries the set's token", len(tj) == 1 and tj == tt and tj[0].startswith("shape:"))
check("key: a skirt keeps its key", bs.key_tokens("skirt", ITEMS["skirt"], ["top1"]) == [])
check("key: no token without shaping", bs.key_tokens("jacket", ITEMS["jacket"], ["top0"]) == [])
check("key: changes with the set's lift", bs.key_tokens("jacket", ITEMS["jacket"], ["dress5"]) != tj)
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
    A, D = [0.05, 1.20, 0.16], [0.05, 1.20, 0.09]          # A -> (0.05, 1.25, 0.13), as above
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
check("Base (Tip's only parent) moves with its chain", close(heads["base"], [0.05, 1.25, 0.02], 1e-6),
      str(heads.get("base")))
check("Base node translation", close(gl["nodes"][1]["translation"], [0.05, 1.25, 0.02], 1e-6))
check("Tip node translation kept (the chain moved as a unit)", close(gl["nodes"][2]["translation"], [0.0, 0.0, 0.11], 1e-6),
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
