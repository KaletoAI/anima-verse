"""A228 / user report 2026-11-22 — the chest shaping v3 (``app/core/bust_shaping.py``): a volume-keeping lift, checked
against values derived by hand from the field in the module docstring. No server, no world, no Blender.

Landmarks (given, not measured): centre_x 0, the chest wall flat at z 0.10 (every bin), apex l (0.08, 1.20, 0.20) /
r (-0.08, 1.20, 0.20), fold_y 1.10, apex_y 1.20, root_y 1.30, extent_m 0.20, depth_m 0.10 (>= FULL_DEPTH_M 0.08:
full strength). Constants: LIFT_SHARE 0.5, GATHER 0.1, BELOW_M 0.06, RISE_M 0.01, ABOVE_M 0.10, ABOVE_GAIN 0.6,
SIDE_PAST_M (0.06, 0.15), GATHER_SIDE_M (0.12, 0.24), BACK_M 0.04.

amounts(lift 1): D = 1 x 0.5 x 0.20 x 1 = 0.10 (50 % of the extent); G = 0.1; lo0 = 1.10 - 0.06 = 1.04,
lo1 = 1.11; up0 = max(1.30, 1.20 + 0.10) = 1.30; up1 = 1.30 + 0.10 + 0.6 x 0.10 = 1.46; off = 0.08 ->
side0 0.14, side1 0.23. amounts(lift 0.6): D = 0.06 (30 %). amounts(lift 0.5): D = 0.05, G = 0.05, up0 1.30.

The block (m = k = g' = 1, s = X): v_x = -G X, v_y = D, v_p = G (p + 0.02) — g(p) = 0.02 + p for p >= 0 (the
smoothstep over -0.04..0 integrates to half its width). Over unit time: X' = X e^-G, y' = y + D,
p' = (p + 0.02) e^G - 0.02 — an affine map with determinant e^-G x 1 x e^G = 1.
  A (0.05, 1.15, 0.15): p 0.05; stays in the block (y <= 1.25 <= up0, |X| <= 0.05 < 0.12) ->
     (0.05 e^-0.1, 1.25, 0.07 e^0.1 - 0.02 + 0.10) = (0.045242, 1.25, 0.157362)
  the apex (0.08, 1.20, 0.20): y' = 1.30 — the rise is exactly D = 50 % of the extent; at lift 0.6 y' = 1.26 (30 %)
  B (0.05, 1.20, 0.05): p -0.05 < -BACK_M -> v = 0 -> unchanged
  C (0.05, 1.00, 0.16): y < lo0 -> unchanged;  E (0.25, 1.20, 0.16): |X| > 0.24 -> unchanged
  wall_at with wall [0.10, 0.12] (bin centres 0.01, 0.03): x 0.02 -> 0.11; x -0.02 -> 0.11; x 0.2 -> 0.12 (held).

Volume and roundness: a closed ellipsoid in the block (centre (0.08, 1.18, 0.16), radii 0.03 / 0.05 / 0.05; p in
0.01..0.11, y' <= 1.28 < up0 at lift 0.5) goes through the affine map above: its volume ratio is 1 (>= 0.95
asked), its centroid rises by D = 0.05 and it stays an ellipsoid (radii x e^-0.05, x 1, x e^0.05 — round, never a
flat cap): no edge's dihedral angle changes by more than 3 deg. The Jacobian determinant of the whole flow is 1
(div v = 0); sampled at lift 1 on an (x, y, p) grid across every ramp it must stay within 0.05 of 1 (> 0.15 asked;
the rest is the 24-step Runge-Kutta's error on the 4 cm ramp behind the wall, measured 0.974 .. 1.017).
Old code (4ee6ac1ab, v2: COMPRESS 0.5, landmarks under_y 1.10 / bust_y 1.20 / band_y 1.25) flattened the same
ellipsoid at lift 1: z' = z - 0.5 p in its block -> volume ratio about 0.5 (< 0.95).

Capsule: a_pos = A -> A', b_pos = B unchanged, the radius kept (v3 keeps the volume: no compression).

Lift resolver (``extension_rig.piece_lift``) with defaults {underwear_top: 0.25, top: 0}: a bra-slot piece without own
lift 0.25; the same as a partial cover 0.125; own 1.0 on top 1.0; a skirt (no slot hit) None.

GLB: a skinned body primitive with A and B, a second skinned non-garment mesh (an extension part) with A, a garment
node with A, joints Base (0.05, 1.15, 0.05) -> Tip (0.05, 1.15, 0.15) under Root (0, 0, 0). After ``shape_glb``:
body A -> A', B unchanged, the part's A alike, the garment's A unchanged; Tip's bind position A'; Base is Tip's only
parent, so the chain moves as a unit: Base takes Tip's displacement (A' - A) -> (0.045242, 1.25, 0.057362), Tip's
node translation stays (0, 0, 0.10); every joint's rest skin matrix the identity; the BIN chunk length unchanged.

Usage: ./.venv/bin/python scripts/smoke_bust_shaping.py
"""
import importlib.util
import json
import math
import struct
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core import bust_shaping as bs  # noqa: E402  (pure numpy + glb_mesh, no storage)
from app.core import glb_mesh  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def close(a, b, tol=1e-6):
    return np.allclose(np.asarray(a, float), np.asarray(b, float), atol=tol)


LM = {"centre_x": 0.0, "wall_z": [0.10] * bs.WALL_BINS, "apex": {"l": [0.08, 1.20, 0.20], "r": [-0.08, 1.20, 0.20]},
      "fold_y": 1.10, "apex_y": 1.20, "root_y": 1.30, "extent_m": 0.20, "depth_m": 0.10}

check("constants", (bs.LIFT_SHARE, bs.GATHER, bs.BELOW_M, bs.RISE_M, bs.ABOVE_M, bs.ABOVE_GAIN, bs.SIDE_PAST_M,
                    bs.GATHER_SIDE_M, bs.BACK_M, bs.FULL_DEPTH_M)
      == (0.5, 0.1, 0.06, 0.01, 0.10, 0.6, (0.06, 0.15), (0.12, 0.24), 0.04, 0.08))
a1 = bs.amounts(LM, 1.0)
want_a = {"D": 0.10, "G": 0.1, "lo0": 1.04, "lo1": 1.11, "up0": 1.30, "up1": 1.46, "side0": 0.14, "side1": 0.23}
check("amounts at lift 1", all(abs(a1[k] - v) < 1e-9 for k, v in want_a.items()), str(a1))
check("lift 0.6 -> D 0.06 (30 %)", abs(bs.amounts(LM, 0.6)["D"] - 0.06) < 1e-9)
check("shallow chest (depth 0.04) -> half strength", abs(bs.amounts({**LM, "depth_m": 0.04}, 1.0)["D"] - 0.05) < 1e-9)

A1 = [0.05 * math.exp(-0.1), 1.25, 0.07 * math.exp(0.1) - 0.02 + 0.10]
pts = np.array([[0.05, 1.15, 0.15], [0.08, 1.20, 0.20], [0.05, 1.20, 0.05], [0.05, 1.00, 0.16], [0.25, 1.20, 0.16]])
got = bs.displace(pts, LM, 1.0)
check("A: the block's affine map", close(got[0], A1, 1e-5), f"{got[0].round(6).tolist()} != {np.round(A1, 6).tolist()}")
check("apex rises by D = 50 % of the extent (lift 1)", abs(got[1][1] - 1.30) < 1e-5, str(got[1]))
check("apex rises by 30 % at lift 0.6", abs(bs.displace(pts[1:2], LM, 0.6)[0][1] - 1.26) < 1e-5)
check("B behind the wall, C under the field, E beside it: unchanged", close(got[2:], pts[2:]))
check("lift 0 moves nothing", close(bs.displace(pts, LM, 0.0), pts))
wl = {"centre_x": 0.0, "wall_z": [0.10, 0.12]}
check("wall_at interpolates and holds", close(bs.wall_at(np.array([0.02, -0.02, 0.2]), wl), [0.11, 0.11, 0.12]))

# --- volume and roundness: a closed ellipsoid in the block
nu, nv = 48, 24
th, ph = np.meshgrid(np.linspace(0, 2 * np.pi, nu, endpoint=False), np.linspace(0, np.pi, nv + 1)[1:-1], indexing="ij")
ring = np.column_stack([0.08 + 0.03 * np.sin(ph).ravel() * np.cos(th).ravel(), 1.18 + 0.05 * np.cos(ph).ravel(),
                        0.16 + 0.05 * np.sin(ph).ravel() * np.sin(th).ravel()])
V = np.vstack([ring, [[0.08, 1.23, 0.16], [0.08, 1.13, 0.16]]])
top, bot = len(ring), len(ring) + 1
idx = np.arange(nu * (nv - 1)).reshape(nu, nv - 1)
F = []
for i in range(nu):
    j = (i + 1) % nu
    F.append([top, idx[j, 0], idx[i, 0]])
    F.append([bot, idx[i, -1], idx[j, -1]])
    for k in range(nv - 2):
        F += [[idx[i, k], idx[j, k], idx[j, k + 1]], [idx[i, k], idx[j, k + 1], idx[i, k + 1]]]
F = np.array(F)


def volume(P):
    return abs(np.einsum("ij,ij->i", P[F[:, 0]], np.cross(P[F[:, 1]], P[F[:, 2]])).sum() / 6.0)


def dihedrals(P):
    n = np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]])
    n /= np.linalg.norm(n, axis=1, keepdims=True)
    edges = {}
    for f, tri in enumerate(F):
        for a, b in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            edges.setdefault((min(a, b), max(a, b)), []).append(f)
    pairs = np.array([v for v in edges.values() if len(v) == 2])
    return np.degrees(np.arccos(np.clip(np.einsum("ij,ij->i", n[pairs[:, 0]], n[pairs[:, 1]]), -1, 1)))


S = bs.displace(V, LM, 0.5)
ratio = volume(S) / volume(V)
check("ellipsoid: volume kept (>= 0.95; the map's determinant is 1)", abs(ratio - 1.0) < 1e-3, f"ratio {ratio:.5f}")
check("ellipsoid: centroid rises by D 0.05", abs(S[:, 1].mean() - V[:, 1].mean() - 0.05) < 1e-5)
turn = np.abs(dihedrals(S) - dihedrals(V)).max()
check("ellipsoid: stays round (no dihedral changes by > 3 deg)", turn < 3.0, f"max {turn:.2f} deg")
ext = (S.max(0) - S.min(0)) / (V.max(0) - V.min(0))
check("ellipsoid: radii x e^-0.05, x 1, x e^0.05",
      close(ext, [math.exp(-0.05), 1.0, math.exp(0.05)], 2e-3), str(ext.round(4)))
print(f"     (volume ratio {ratio:.5f}, dihedral change max {turn:.2f} deg)")

# --- no fold: the full Jacobian determinant on a grid at lift 1, across every ramp
xs, ys, ps = np.arange(-0.26, 0.261, 0.02), np.arange(1.0, 1.50, 0.005), np.arange(-0.05, 0.14, 0.005)
X, Y, Z = np.meshgrid(xs, ys, ps + 0.10, indexing="ij")
G = np.column_stack([X.ravel(), Y.ravel(), Z.ravel()])
h = 1e-4
J = np.zeros((len(G), 3, 3))
for k in range(3):
    d = np.zeros(3)
    d[k] = h
    J[:, :, k] = (bs.displace(G + d, LM, 1.0) - bs.displace(G - d, LM, 1.0)) / (2 * h)
det = np.linalg.det(J)
check("Jacobian determinant within 0.05 of 1 everywhere (lift 1)", np.abs(det - 1).max() < 0.05,
      f"min {det.min():.4f} max {det.max():.4f}")
print(f"     (det {det.min():.4f} .. {det.max():.4f})")

# --- the old code (4ee6ac1ab) flattened the same ellipsoid
try:
    old_src = subprocess.run(["git", "show", "4ee6ac1ab:app/core/bust_shaping.py"], cwd=ROOT, capture_output=True,
                             text=True, check=True).stdout
    spec = importlib.util.spec_from_loader("bust_shaping_v2", loader=None)
    old = importlib.util.module_from_spec(spec)
    exec(compile(old_src, "bust_shaping_v2", "exec"), old.__dict__)
    LM2 = {"under_y": 1.10, "bust_y": 1.20, "band_y": 1.25, "centre_x": 0.0, "wall_z": [0.10] * old.WALL_BINS,
           "depth_m": 0.10}
    r_old = volume(old.displace(V, LM2, 1.0)) / volume(V)
    check("old code (4ee6ac1ab) lost the volume (ratio < 0.95)", r_old < 0.95, f"ratio {r_old:.3f}")
    print(f"     (old v2 volume ratio {r_old:.3f})")
except subprocess.CalledProcessError:
    print("skip old-code proof: commit 4ee6ac1ab not in this clone")

# --- capsules: the endpoints follow, the radius stays
col = {"version": 9, "capsules": [{"id": "c", "a_pos": [0.05, 1.15, 0.15], "b_pos": [0.05, 1.20, 0.05], "r": 0.05},
                                  {"id": "leg", "a": "x", "b": "y", "r": 0.1}]}
sc = bs.shape_collision(col, bs.record(LM, 1.0))
check("capsule a_pos shaped", close(sc["capsules"][0]["a_pos"], A1, 1e-4), str(sc["capsules"][0]))
check("capsule b_pos kept", close(sc["capsules"][0]["b_pos"], [0.05, 1.20, 0.05], 1e-4))
check("capsule radius kept", sc["capsules"][0]["r"] == 0.05)
check("capsule without positions kept", sc["capsules"][1] == col["capsules"][1])

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
    A, D = [0.05, 1.15, 0.15], [0.05, 1.15, 0.05]          # A -> A1 (block point), D behind the wall
    meshes = [{"name": "body", "primitives": [prim([A, D, [0.0, 0.5, 0.0]])]},
              {"name": "part", "primitives": [prim([A, [0.0, 0.5, 0.0], [0.0, 0.6, 0.0]])]},
              {"name": "garment_clothing_x", "primitives": [prim([A, [0.0, 0.5, 0.0], [0.0, 0.6, 0.0]])]}]
    world = {"Root": [0, 0, 0], "Base": [0.05, 1.15, 0.05], "Tip": [0.05, 1.15, 0.15]}
    nodes = [{"name": "Root", "children": [1, 4, 5, 6]},
             {"name": "Base", "translation": world["Base"], "children": [2]},
             {"name": "Tip", "translation": [0.0, 0.0, 0.10]},
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


BASE1 = [A1[0], 1.25, A1[2] - 0.10]
check("in-place: same BIN chunk length", bin_len(out) == bin_len(src))
parsed = glb_mesh._parse(out, "x")
gl = parsed["gltf"]
pos = [np.asarray(glb_mesh.accessor_array(parsed, m["primitives"][0]["attributes"]["POSITION"])) for m in gl["meshes"]]
check("body A shaped", close(pos[0][0], A1, 1e-5), str(pos[0][0]))
check("body B (behind the wall) unchanged", close(pos[0][1], [0.05, 1.15, 0.05], 1e-6))
check("part A shaped alike", close(pos[1][0], A1, 1e-5))
check("garment A untouched", close(pos[2][0], [0.05, 1.15, 0.15], 1e-6))
acc = gl["accessors"][gl["meshes"][0]["primitives"][0]["attributes"]["POSITION"]]
check("POSITION max follows", close(acc["max"], [0.05, 1.25, A1[2]], 1e-5), str(acc["max"]))
heads = glb_mesh.body_arrays(out).joint_positions
check("Tip bind moved", close(heads["tip"], A1, 1e-5), str(heads.get("tip")))
check("Base (Tip's only parent) moves with its chain", close(heads["base"], BASE1, 1e-5), str(heads.get("base")))
check("Base node translation", close(gl["nodes"][1]["translation"], BASE1, 1e-5))
check("Tip node translation kept (the chain moved as a unit)", close(gl["nodes"][2]["translation"], [0.0, 0.0, 0.10], 1e-6),
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
