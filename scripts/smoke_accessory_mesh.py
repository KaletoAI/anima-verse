"""Smoke: Ruling A118 / A216 — the accessory tube and its skin (``app/core/accessory_mesh.py``).

Usage: ./.venv/bin/python scripts/smoke_accessory_mesh.py   (no server, no world; pure numpy)

Expected values, derived by hand:

[1] A closed circle of radius R = 0.1 m in the xz plane, k = 12 points, tube radius r = 0.01 m, 8 sides:
    V = 12 · 8 = 96 vertices, F = 2 · 12 · 8 = 192 triangles; every vertex lies exactly r from its ring's centre
    point (the ring is built as centre + r · unit direction), ±1e-12.
[2] Outward winding: the signed volume Σ (a · (b × c)) / 6 is POSITIVE. Its size by Pappus with the polygons:
    cross-section octagon area 8/2 · r² · sin 45° = 2.8284 r² = 2.8284e-4 m²; centre-line
    12-gon perimeter 12 · 2R sin 15° = 0.62117 m → ≈ 2.8284e-4 · 0.62117 = 1.757e-4 m³; accepted 1.6e-4 … 1.9e-4
    (the octagon's offset from the 12-gon corners makes the exact value differ by a few %).
[3] Vertex normals are unit and point away from the centre line: (V − centre point) · N = r for every vertex.
[4] ``skin_weights``: body vertices (0,0,0), (1,0,0), (0,1,0) with one-hot weights on joints 0, 2, 4 of 5;
    X = (1,0,0) (coincident with vertex 1) → joint 2 with weight 1.0 (the coincident rule), the other three
    weights 0. X = (0.5, 0, 0) (k = 2 nearest: vertices 0 and 1, both at 0.5, inverse-square weights equal) →
    joints {0, 2} at 0.5 each.
[6] A216 review H1 — ``fold_to_base``: the body fixture of ``smoke_glb_graft`` (base skeleton + an extension joint
    ``breast_L`` under Spine2). Accessory weights {breast_L 0.6, Neck 0.4} → {Spine2 0.6, Neck 0.4} (breast_L's
    parent); ``onto`` {head: neck} moves {Head 1.0} → {Neck 1.0}. A garment weighted on a joint the target skin lacks
    and that has no parent (``mixamorig:LeftBreastTip``) → ``graft`` raises KeyError (the reported failure); the
    same garment folded first grafts (its joint is the target's Spine2).
[5] ``node_name("item_1")`` = "garment_accessory_item_1_c"; side "l" → "garment_accessory_item_1_l".
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import numpy as np  # noqa: E402
from app.core import accessory_mesh as am  # noqa: E402

FAIL = []


def check(name, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{name}: {got!r}" + ("" if ok else f" (expected {want!r})"))
    if not ok:
        FAIL.append(name)


R, r, k = 0.1, 0.01, 12
a = 2 * np.pi * np.arange(k) / k
curve = np.stack([R * np.cos(a), np.zeros(k), R * np.sin(a)], 1)
V, F, N = am.tube(curve, r, sides=8)
check("[1] vertices", V.shape, (96, 3))
check("[1] triangles", F.shape, (192, 3))
centres = np.repeat(curve, 8, axis=0)
check("[1] radius", bool(np.allclose(np.linalg.norm(V - centres, axis=1), r, atol=1e-12)), True)
A, B, C = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
vol = float(np.einsum("ij,ij->i", A, np.cross(B, C)).sum() / 6.0)
print(f"       signed volume {vol:.4e}")
check("[2] outward (volume > 0)", vol > 0, True)
check("[2] volume 1.6e-4..1.9e-4", 1.6e-4 <= vol <= 1.9e-4, True)
check("[3] unit normals", bool(np.allclose(np.linalg.norm(N, axis=1), 1.0)), True)
check("[3] normals away from the centre line", bool(np.allclose(np.einsum("ij,ij->i", V - centres, N), r)), True)

Pb = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], float)
Wb = np.zeros((3, 5))
Wb[0, 0] = Wb[1, 2] = Wb[2, 4] = 1.0
J, W = am.skin_weights(np.array([[1.0, 0, 0]]), Pb, Wb, k=2)
check("[4] coincident joint", int(J[0, int(np.argmax(W[0]))]), 2)
check("[4] coincident weights", sorted(np.round(W[0], 6).tolist()), [0.0, 0.0, 0.0, 1.0])
J, W = am.skin_weights(np.array([[0.5, 0, 0]]), Pb, Wb, k=2)
got = {int(j): round(float(w), 6) for j, w in zip(J[0], W[0]) if w > 0}
check("[4] midpoint", got, {0: 0.5, 2: 0.5})

check("[5] node name", am.node_name("item_1"), "garment_accessory_item_1_c")
check("[5] node name l", am.node_name("item_1", "l"), "garment_accessory_item_1_l")

sys.path.insert(0, os.path.join(ROOT, "scripts"))
from smoke_glb_graft import body_fixture  # noqa: E402
from app.core import glb_mesh  # noqa: E402
from app.core.rig_contract import norm_bone_name  # noqa: E402
glb, names = body_fixture()
parents = glb_mesh.skin_joint_parents(glb)
ix = {n: i for i, n in enumerate(names)}
J = np.array([[ix["breast_L"], ix["mixamorig:Neck"], 0, 0]])
W = np.array([[0.6, 0.4, 0, 0]])
J2, W2 = am.fold_to_base(J, W, names, parents)
check("[6] breast_L -> Spine2", {names[j]: round(float(w), 6) for j, w in zip(J2[0], W2[0]) if w > 0},
      {"mixamorig:Spine2": 0.6, "mixamorig:Neck": 0.4})
J3, W3 = am.fold_to_base(np.array([[ix["mixamorig:Head"], 0, 0, 0]]), np.array([[1.0, 0, 0, 0]]), names, parents,
                         onto={"head": "neck"})
check("[6] head onto neck", names[int(J3[0, 0])], "mixamorig:Neck")
tip_names = names + ["mixamorig:LeftBreastTip"]
Vt, Ft, Nt = am.tube(curve + [0, 1.4, 0], r, sides=8)
Jt = np.zeros((len(Vt), 4), np.int64)
Jt[:, 0] = len(names)
Wt = np.zeros((len(Vt), 4))
Wt[:, 0] = 1.0
try:
    glb_mesh.graft(glb, am.garment_mesh(Vt, Ft, Nt, Jt, Wt, tip_names, color="#d4af37", roughness=0.25),
                   name="garment_accessory_x_c", extras={"kind": "accessory"})
    check("[6] unfolded tip joint fails", "no error", "KeyError")
except KeyError:
    check("[6] unfolded tip joint fails", "KeyError", "KeyError")
tip_parents = {**parents, "mixamorig:LeftBreastTip": "breast_L"}
Jf, Wf = am.fold_to_base(Jt, Wt, tip_names, tip_parents)
out = glb_mesh.graft(glb, am.garment_mesh(Vt, Ft, Nt, Jf, Wf, tip_names, color="#d4af37", roughness=0.25),
                     name="garment_accessory_x_c", extras={"kind": "accessory"})
check("[6] folded grafts", norm_bone_name(tip_names[int(Jf[0, 0])]), "spine2")
check("[6] graft output is a GLB", out[:4], b"glTF")

if FAIL:
    print(f"\n{len(FAIL)} check(s) failed: {FAIL}")
    sys.exit(1)
print("\nall checks passed")
