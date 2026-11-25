"""A228 / user report 2026-11-22 — the chest shaping v4 (``app/core/bust_shaping.py``): the chest tissue is LIFTED,
not pressed flat, and nothing above the shoulder line moves. Checked against values derived by hand from the field
in the module docstring. No server, no world, no Blender.

Landmarks (given, not measured): centre_x 0, the chest wall flat at z 0.10 (every bin), apex l (0.08, 1.20, 0.20) /
r (-0.08, 1.20, 0.20), fold_y 1.10, apex_y 1.20, root_y 1.30, extent_m 0.20, depth_m 0.10 (>= FULL_DEPTH_M 0.08:
full strength), cap_y (the shoulder line) 1.40. Constants: LIFT_SHARE 0.5, ROOM_SHARE 0.4, GATHER 0.1, BELOW_M 0.06,
RISE_M 0.01, UPPER_START_M 0.06, RAMP_ROUND_M 0.05, FILL_CAP_M 0.04, SIDE_PAST_M (0.06, 0.15), GATHER_SIDE_M
(0.12, 0.24), BACK_M 0.06, FRONT_M 0.02.

The asked rise (share_of): share = min(lift x 0.5 x 1, 0.4 x (cap_y - apex_y) / extent_m = 0.4 x 0.20 / 0.20 = 0.4).
  lift 1 -> 0.4 (the room caps the 50 %): the apex rises 0.08 = 40 % of the extent
  lift 0.6 -> 0.3: rises 0.06 (30 %);  lift 0.25 -> 0.125: rises 0.025
  with cap_y 1.50 the room is 0.4 x 0.30 / 0.20 = 0.6 -> lift 1 -> 0.5 (50 %); with cap_y 1.30 -> 0.2
amounts: G = lift x 0.1; lo0 = 1.04, lo1 = 1.11; up0 = min(1.20 + 0.06, 1.40 - 2 x 0.05) = 1.26; off 0.08 -> side0
0.14, side1 0.23.

The block (m = k = g' = 1, s = X; y in lo1 .. up0, |X| < 0.12, p >= FRONT_M): g(p) = 0.04 + (p - 0.02) = p + 0.02
(the smoothstep over -0.06..0.02 integrates to half its width), m' = 0, so v = (-G X, D, G (p + 0.02)) — the fill
cap only scales the m' term. Over unit time: X' = X e^-G, y' = y + D, p' = (p + 0.02) e^G - 0.02 — an affine map,
determinant 1. At lift 0.25 the apex (y 1.20) needs to rise 0.025, stays in the block (1.225 < up0 1.26), so the
solved D is exactly 0.025 and G 0.025:
  A (0.05, 1.15, 0.15): p 0.05 -> (0.05 e^-0.025, 1.175, 0.07 e^0.025 - 0.02 + 0.10)
  B (0.05, 1.20, 0.03): p -0.07 < -BACK_M -> v = 0 -> unchanged
  C (0.05, 1.00, 0.16): y < lo0 -> unchanged;  E (0.25, 1.20, 0.16): |X| > 0.24 -> unchanged
  H (0.05, 1.40, 0.12), (0.0, 1.45, 0.11): y >= cap_y -> m = 0 -> unchanged at every lift (m = 0 at cap_y, so the
  flow never carries a point across it: every shaped y stays < 1.40)
  wall_at with wall [0.10, 0.12] (bin centres 0.01, 0.03): x 0.02 -> 0.11; x -0.02 -> 0.11; x 0.2 -> 0.12 (held).

Volume and roundness, in the block: a closed ellipsoid (centre (0.08, 1.17, 0.17), radii 0.03 / 0.03 / 0.04; p in
0.03..0.11, y' <= 1.225 < up0 at lift 0.25) goes through the affine map: volume ratio 1, centroid +0.025, radii
x e^-0.025, x 1, x e^0.025 — round, never a flat cap; no dihedral changes by more than 3 deg.
Across the ramp (lift 1, the apex lifted 40 %): a mound ellipsoid round the apex (centre (0.08, 1.20, 0.15), radii
0.05 / 0.08 / 0.06) must rise with its centroid by more than half the apex's 0.08, and no edge between two faces
may turn by more than 30 deg more than it did (a hard rim). (Alone it loses volume in the ramp — the fill cap moves
the compressed part's volume onto the skin in front of the wall above it, which a lone ellipsoid does not have: the
volume gate is on the mesh below.) The Jacobian determinant on an (x, y, p) grid across every ramp stays > 0.15.
A hanging mound mesh (rings of radius 0.06 .. 0.075 .. 0 round a centre line that sags 3 cm, so its underside
overhangs the wall — where v3's 4 cm depth fade sheared faces over) plus a wall sheet up to 1.50: at lift 1 no face
turns over, no face keeps less than 0.15 of its area, the volume in front of the wall (mound + sheet, the sheet under
the mound's base left out) keeps >= 0.95, and the sheet above cap_y does not move.
Old code (4ee6ac1ab, v2: COMPRESS 0.5, landmarks under_y 1.10 / bust_y 1.20 / band_y 1.25) flattened the block
ellipsoid at lift 1: z' = z - 0.5 p in its block -> volume ratio about 0.5 (< 0.95).

Capsule (lift 0.25): a_pos = A -> A', b_pos = B unchanged, the radius kept.

Lift resolver (``extension_rig.piece_lift``) with defaults {underwear_top: 0.25, top: 0}: a bra-slot piece without own
lift 0.25; the same as a partial cover 0.125; own 1.0 on top 1.0; a skirt (no slot hit) None.

GLB (lift 0.25): a skinned body primitive with A and B, a second skinned non-garment mesh (an extension part) with A,
a garment node with A, joints Base (0.05, 1.15, 0.03) -> Tip (0.05, 1.15, 0.15) under Root (0, 0, 0). After
``shape_glb``: body A -> A', B unchanged, the part's A alike, the garment's A unchanged; Tip's bind position A';
Base (behind the wall, unmoved) is Tip's only parent, so the chain moves as a unit: Base takes Tip's displacement
-> A' - (0, 0, 0.12), Tip's node translation stays (0, 0, 0.12); every joint's rest skin matrix the identity; the
BIN chunk length unchanged.

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
      "fold_y": 1.10, "apex_y": 1.20, "root_y": 1.30, "extent_m": 0.20, "depth_m": 0.10, "cap_y": 1.40}

check("constants", (bs.LIFT_SHARE, bs.ROOM_SHARE, bs.GATHER, bs.BELOW_M, bs.RISE_M, bs.UPPER_START_M,
                    bs.RAMP_ROUND_M, bs.FILL_CAP_M, bs.SIDE_PAST_M, bs.GATHER_SIDE_M, bs.BACK_M, bs.FRONT_M,
                    bs.FULL_DEPTH_M)
      == (0.5, 0.4, 0.1, 0.06, 0.01, 0.06, 0.05, 0.04, (0.06, 0.15), (0.12, 0.24), 0.06, 0.02, 0.08))
check("share: lift 1 capped by the room at 0.4", abs(bs.share_of(LM, 1.0) - 0.4) < 1e-12)
check("share: lift 0.6 -> 0.3, lift 0.25 -> 0.125",
      abs(bs.share_of(LM, 0.6) - 0.3) < 1e-12 and abs(bs.share_of(LM, 0.25) - 0.125) < 1e-12)
check("share: more room (cap 1.50) -> 0.5, less (cap 1.30) -> 0.2",
      abs(bs.share_of({**LM, "cap_y": 1.50}, 1.0) - 0.5) < 1e-12 and abs(bs.share_of({**LM, "cap_y": 1.30}, 1.0) - 0.2)
      < 1e-12)
check("share: shallow chest (depth 0.04) -> half strength", abs(bs.share_of({**LM, "depth_m": 0.04}, 0.6) - 0.15) < 1e-12)
a1 = bs.amounts(LM, 1.0)
want_a = {"G": 0.1, "lo0": 1.04, "lo1": 1.11, "up0": 1.26, "cap": 1.40, "side0": 0.14, "side1": 0.23, "rise": 0.08}
check("amounts at lift 1", all(abs(a1[k] - v) < 1e-9 for k, v in want_a.items()), str(a1))
a25 = bs.amounts(LM, 0.25)
check("lift 0.25: D solved to exactly 0.025 (the apex stays in the block)", abs(a25["D"] - 0.025) < 1e-7, str(a25["D"]))

A1 = [0.05 * math.exp(-0.025), 1.175, 0.07 * math.exp(0.025) - 0.02 + 0.10]
pts = np.array([[0.05, 1.15, 0.15], [0.08, 1.20, 0.20], [0.05, 1.20, 0.03], [0.05, 1.00, 0.16], [0.25, 1.20, 0.16]])
got = bs.displace(pts, LM, 0.25)
check("A: the block's affine map (lift 0.25)", close(got[0], A1, 1e-6), f"{got[0].round(6).tolist()} != {np.round(A1, 6).tolist()}")
check("apex rises 0.025 at lift 0.25", abs(got[1][1] - 1.225) < 1e-6, str(got[1]))
for lift, rise in ((1.0, 0.08), (0.6, 0.06)):
    ap = bs.displace(np.array(list(LM["apex"].values())), LM, lift)
    check(f"apex rises {rise} = {rise / 0.2:.0%} of the extent at lift {lift}", abs(ap[:, 1].mean() - 1.20 - rise) < 1e-6,
          str(ap[:, 1]))
check("B behind the wall, C under the field, E beside it: unchanged", close(got[2:], pts[2:]))
check("lift 0 moves nothing", close(bs.displace(pts, LM, 0.0), pts))
H = np.array([[0.05, 1.40, 0.12], [0.0, 1.45, 0.11]])
check("above the shoulder line nothing moves (lift 1)", close(bs.displace(H, LM, 1.0), H))
wl = {"centre_x": 0.0, "wall_z": [0.10, 0.12]}
check("wall_at interpolates and holds", close(bs.wall_at(np.array([0.02, -0.02, 0.2]), wl), [0.11, 0.11, 0.12]))


# --- closed ellipsoids
def ellipsoid(c, r, nu=48, nv=24):
    th, ph = np.meshgrid(np.linspace(0, 2 * np.pi, nu, endpoint=False), np.linspace(0, np.pi, nv + 1)[1:-1],
                         indexing="ij")
    ring = np.column_stack([c[0] + r[0] * np.sin(ph).ravel() * np.cos(th).ravel(), c[1] + r[1] * np.cos(ph).ravel(),
                            c[2] + r[2] * np.sin(ph).ravel() * np.sin(th).ravel()])
    V = np.vstack([ring, [[c[0], c[1] + r[1], c[2]], [c[0], c[1] - r[1], c[2]]]])
    top, bot = len(ring), len(ring) + 1
    idx = np.arange(nu * (nv - 1)).reshape(nu, nv - 1)
    F = []
    for i in range(nu):
        j = (i + 1) % nu
        F.append([top, idx[j, 0], idx[i, 0]])
        F.append([bot, idx[i, -1], idx[j, -1]])
        for k in range(nv - 2):
            F += [[idx[i, k], idx[j, k], idx[j, k + 1]], [idx[i, k], idx[j, k + 1], idx[i, k + 1]]]
    return V, np.array(F)


def volume(P, F):
    return abs(np.einsum("ij,ij->i", P[F[:, 0]], np.cross(P[F[:, 1]], P[F[:, 2]])).sum() / 6.0)


def dihedrals(P, F):
    n = np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]])
    n /= np.linalg.norm(n, axis=1, keepdims=True)
    edges = {}
    for f, tri in enumerate(F):
        for a, b in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            edges.setdefault((min(a, b), max(a, b)), []).append(f)
    pairs = np.array([v for v in edges.values() if len(v) == 2])
    return np.degrees(np.arccos(np.clip(np.einsum("ij,ij->i", n[pairs[:, 0]], n[pairs[:, 1]]), -1, 1)))


V, F = ellipsoid((0.08, 1.17, 0.17), (0.03, 0.03, 0.04))
S = bs.displace(V, LM, 0.25)
ratio = volume(S, F) / volume(V, F)
check("block ellipsoid: volume kept (the map's determinant is 1)", abs(ratio - 1.0) < 1e-3, f"ratio {ratio:.5f}")
check("block ellipsoid: centroid rises by 0.025", abs(S[:, 1].mean() - V[:, 1].mean() - 0.025) < 1e-6)
turn = np.abs(dihedrals(S, F) - dihedrals(V, F)).max()
check("block ellipsoid: stays round (no dihedral changes by > 3 deg)", turn < 3.0, f"max {turn:.2f} deg")
ext = (S.max(0) - S.min(0)) / (V.max(0) - V.min(0))
check("block ellipsoid: radii x e^-0.025, x 1, x e^0.025",
      close(ext, [math.exp(-0.025), 1.0, math.exp(0.025)], 2e-3), str(ext.round(4)))

M, FM = ellipsoid((0.08, 1.20, 0.15), (0.05, 0.08, 0.06))
SM = bs.displace(M, LM, 1.0)
r_m = volume(SM, FM) / volume(M, FM)
rise_m = SM[:, 1].mean() - M[:, 1].mean()
crease = (dihedrals(SM, FM) - dihedrals(M, FM)).max()
check("mound: the centroid rises by more than half the apex's 0.08", rise_m > 0.04, f"{rise_m:.4f}")
check("mound: no edge turns by > 30 deg more (no hard rim)", crease < 30.0, f"{crease:.1f} deg")
print(f"     (mound volume ratio {r_m:.4f}, centroid +{rise_m * 100:.2f} cm, crease max {crease:.1f} deg)")

# --- no fold: the Jacobian determinant on a grid at lift 1, across every ramp
xs, ys, ps = np.arange(-0.26, 0.261, 0.02), np.arange(1.0, 1.45, 0.005), np.arange(-0.07, 0.14, 0.005)
X, Y, Z = np.meshgrid(xs, ys, ps + 0.10, indexing="ij")
G = np.column_stack([X.ravel(), Y.ravel(), Z.ravel()])
h = 1e-4
J = np.zeros((len(G), 3, 3))
for k in range(3):
    d = np.zeros(3)
    d[k] = h
    J[:, :, k] = (bs.displace(G + d, LM, 1.0) - bs.displace(G - d, LM, 1.0)) / (2 * h)
det = np.linalg.det(J)
check("Jacobian determinant > 0.15 everywhere (lift 1)", det.min() > 0.15, f"min {det.min():.4f}")
print(f"     (det {det.min():.4f} .. {det.max():.4f})")

# --- a hanging mound mesh with an overhanging underside, plus a wall sheet up past the shoulder line
nr, nt = 24, 48
u = np.linspace(0.0, 1.0, nr + 1)
rad = 0.06 + 0.06 * u - 0.12 * u ** 2.5 + 1e-4             # 0.06 at the wall, ~0.075 out, ~0 at the tip
rad[-1] = 0.0
depth = 0.09 * u
sag = -0.03 * u ** 1.5                                     # the centre line sags 3 cm: the underside overhangs
th = np.linspace(0, 2 * np.pi, nt, endpoint=False)
MP = np.array([[0.08 + rad[i] * np.cos(t), 1.18 + sag[i] + rad[i] * np.sin(t), 0.10 + depth[i]]
               for i in range(nr + 1) for t in th])
MF = []
for i in range(nr):
    for j in range(nt):
        a, b = i * nt + j, i * nt + (j + 1) % nt
        MF += [[a, b, b + nt], [a, b + nt, a + nt]]
gx, gy = np.meshgrid(np.arange(-0.20, 0.201, 0.01), np.arange(1.00, 1.501, 0.01), indexing="ij")
WP = np.column_stack([gx.ravel(), gy.ravel(), np.full(gx.size, 0.10)])
ny = gx.shape[1]
WF = []
for i in range(gx.shape[0] - 1):
    for j in range(ny - 1):
        a = i * ny + j
        WF += [[a, a + ny, a + ny + 1], [a, a + ny + 1, a + 1]]
P0 = np.vstack([MP, WP])
F0 = np.vstack([np.array(MF), np.array(WF) + len(MP)])
P1 = bs.displace(P0, LM, 1.0)


def face_n(P):
    n = np.cross(P[F0[:, 1]] - P[F0[:, 0]], P[F0[:, 2]] - P[F0[:, 0]])
    return n, np.linalg.norm(n, axis=1)


n0, ar0 = face_n(P0)
n1, ar1 = face_n(P1)
ok = ar0 > 1e-12
flipped = int(((n0 * n1).sum(1)[ok] < 0).sum())
r_min = float((ar1[ok] / ar0[ok]).min())
check("hanging mound + sheet: no face turns over (lift 1)", flipped == 0, f"{flipped} flipped")
check("hanging mound + sheet: every face keeps >= 0.15 of its area", r_min >= 0.15, f"min {r_min:.3f}")
# the volume in front of the wall: sum over faces of p x (area projected onto the wall plane), signed by facing (the
# divergence theorem for the field (0, 0, p)); the sheet under the mound's base is left out (it would count twice)
c0 = P0[F0].mean(1)
keep = np.ones(len(F0), bool)
keep[len(MF):] = np.hypot(c0[len(MF):, 0] - 0.08, c0[len(MF):, 1] - 1.18) > 0.062


def front_volume(P):
    n = np.cross(P[F0[:, 1]] - P[F0[:, 0]], P[F0[:, 2]] - P[F0[:, 0]])[:, 2] / 2.0
    pp = P[F0].mean(1)[:, 2] - 0.10
    return float((pp * n)[keep].sum())


r_front = front_volume(P1) / front_volume(P0)
check("hanging mound + sheet: the volume in front of the wall >= 0.95 (lift 1)", r_front >= 0.95, f"{r_front:.4f}")
above = P0[:, 1] >= 1.40
check("sheet above the shoulder line unchanged", close(P1[above], P0[above], 1e-12))
check("nothing is carried across the shoulder line", (P1[~above, 1] < 1.40).all())
print(f"     (mesh: flipped {flipped}, min area ratio {r_min:.3f}, front volume ratio {r_front:.4f})")

# --- the old code (4ee6ac1ab) flattened the same block ellipsoid
VO, FO = ellipsoid((0.08, 1.18, 0.16), (0.03, 0.05, 0.05))
try:
    old_src = subprocess.run(["git", "show", "4ee6ac1ab:app/core/bust_shaping.py"], cwd=ROOT, capture_output=True,
                             text=True, check=True).stdout
    spec = importlib.util.spec_from_loader("bust_shaping_v2", loader=None)
    old = importlib.util.module_from_spec(spec)
    exec(compile(old_src, "bust_shaping_v2", "exec"), old.__dict__)
    LM2 = {"under_y": 1.10, "bust_y": 1.20, "band_y": 1.25, "centre_x": 0.0, "wall_z": [0.10] * old.WALL_BINS,
           "depth_m": 0.10}
    r_old = volume(old.displace(VO, LM2, 1.0), FO) / volume(VO, FO)
    check("old code (4ee6ac1ab) lost the volume (ratio < 0.95)", r_old < 0.95, f"ratio {r_old:.3f}")
    print(f"     (old v2 volume ratio {r_old:.3f})")
except subprocess.CalledProcessError:
    print("skip old-code proof: commit 4ee6ac1ab not in this clone")

# --- capsules: the endpoints follow, the radius stays
col = {"version": 9, "capsules": [{"id": "c", "a_pos": [0.05, 1.15, 0.15], "b_pos": [0.05, 1.20, 0.03], "r": 0.05},
                                  {"id": "leg", "a": "x", "b": "y", "r": 0.1}]}
sc = bs.shape_collision(col, bs.record(LM, 0.25))
check("capsule a_pos shaped", close(sc["capsules"][0]["a_pos"], A1, 1e-4), str(sc["capsules"][0]))
check("capsule b_pos kept", close(sc["capsules"][0]["b_pos"], [0.05, 1.20, 0.03], 1e-4))
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
# the wearer's gate (``character_shaped``) has its own smoke (smoke_chest_shaping_male.py); here every wearer is shaped
_REAL_SHAPED = bs.character_shaped
bs.character_shaped = lambda name, profile=None: True
check("set_lift: strongest of the set", bs.set_lift(["top1", "dress5", "skirt"], character_name="demo") == 1.0
      and bs.set_lift(["top0", "skirt"], character_name="demo") == 0.0)
tj = bs.key_tokens("jacket", ITEMS["jacket"], ["top1"], character_name="demo")
tt = bs.key_tokens("top1", ITEMS["top1"], ["jacket"], character_name="demo")
check("key: a jacket over a shaping top carries the set's token", len(tj) == 1 and tj == tt and tj[0].startswith("shape:"))
check("key: a skirt keeps its key", bs.key_tokens("skirt", ITEMS["skirt"], ["top1"], character_name="demo") == [])
check("key: no token without shaping", bs.key_tokens("jacket", ITEMS["jacket"], ["top0"], character_name="demo") == [])
check("key: changes with the set's lift", bs.key_tokens("jacket", ITEMS["jacket"], ["dress5"], character_name="demo") != tj)
r_hi, r_lo = bs.record(LM, 1.0), bs.record(LM, 0.4)
worn = [{"template": True, "record": {"shaping": r_lo}}, {"template": True, "record": {"shaping": r_hi}},
        {"template": False, "record": {"shaping": bs.record(LM, 1.0)}}, {"template": True, "record": {}}]
check("worn_record: the strongest lift of the template drapes", bs.worn_record(worn) == r_hi)
check("worn_record: none", bs.worn_record([{"template": True, "record": {}}]) is None)


# --- round 2026-11-25: a top with cups is a bra with a long band (plan E3) — it never shapes; its cups' push-up lifts
# the cloth. Derived: ``applies`` reads ``garment_template.build_kind`` ("bra" for a cupped top, not in SHAPING_KINDS).
def tplp(params, lift=None, slots=("top",), covers=()):
    it = tpl(params["kind"], lift, slots)
    it["outfit_piece"]["template"]["params"] = dict(params)
    it["outfit_piece"]["covers"] = list(covers)
    return it


CUP = {"kind": "top", "cups": "bra", "cup_style": "balconette", "push_up": 0.8, "shoulders": "straps"}
ITEMS.update({"cup7": tplp(CUP, 0.7), "cupd": tplp(CUP, None, covers=("underwear_top",)),
              "dress_l5": tplp({"kind": "dress"}, 0.5), "dress_l0": tplp({"kind": "dress"}, 0.0),
              "top_slot": tplp({"kind": "top", "shoulders": "straps"}, None, covers=("underwear_top",)),
              "trousers": tplp({"kind": "trousers"}, None, ("bottom",)),
              "necklace": {"outfit_piece": {"mesh_mode": "accessory", "slots": ["neck"]}},
              "belt": {"outfit_piece": {"mesh_mode": "accessory", "slots": ["outer"]}}})
# [S-C1] a cupped top with lift 0.7: no shaping, no token of its own
check("[S-C1] cupped top lift 0.7: shapes_chest False", not bs.shapes_chest(ITEMS["cup7"]))
check("[S-C1] cupped top alone: key_tokens []", bs.key_tokens("cup7", ITEMS["cup7"], [], character_name="demo") == [])
# [S-C2] a dress lift 0.5 with a cupped top, a wearer who is shaped: set_lift 0.5; the cupped top drapes on the shaped
# body (it is a CHEST_KINDS top) -> its token is the set's
check("[S-C2] set {dress 0.5, cupped top}: set_lift 0.5",
      bs.set_lift(["dress_l5", "cup7"], character_name="demo") == 0.5)
tc = bs.key_tokens("cup7", ITEMS["cup7"], ["dress_l5"], character_name="demo")
check("[S-C2] the cupped top carries the set's token", len(tc) == 1 and tc[0].startswith("shape:"), tc)
# [S-C3] the same set on a male wearer (``base_skin.is_male`` of the profile's gender): never shaped
bs.character_shaped = _REAL_SHAPED
male = {"gender": "male"}
check("[S-C3] male wearer: set_lift 0",
      bs.set_lift(["dress_l5", "cup7"], character_name="demo", profile=male) == 0.0)
bs.character_shaped = lambda name, profile=None: not name.startswith("male")
check("[S-C3] male wearer: key_tokens []", bs.key_tokens("cup7", ITEMS["cup7"], ["dress_l5"],
                                                         character_name="male demo") == [])
bs.character_shaped = lambda name, profile=None: True
# [S-C4] a top without cups and the slot lift 0.25 (covers underwear_top) shapes as before
check("[S-C4] top without cups, slot lift 0.25: shapes_chest True", bs.shapes_chest(ITEMS["top_slot"])
      and bs.effective_lift(ITEMS["top_slot"]) == 0.25)
# [S-C5] knock-on (E3), Lirien's set as literals: before (top without cups, slot lift 0.25) set_lift 0.25, after (the
# same top with cups) 0; a dress lift 0 laid with it: token before, none after; drape records without ``shaping``
# -> worn_record None (the shown body is unshaped)
before = ["top_slot", "trousers", "necklace", "belt"]
after = ["cupd", "trousers", "necklace", "belt"]
check("[S-C5] before: set_lift 0.25", bs.set_lift(before, character_name="demo") == 0.25)
check("[S-C5] after: set_lift 0", bs.set_lift(after, character_name="demo") == 0.0)
kb = bs.key_tokens("dress_l0", ITEMS["dress_l0"], before, character_name="demo")
ka = bs.key_tokens("dress_l0", ITEMS["dress_l0"], after, character_name="demo")
check("[S-C5] another chest piece of the set is re-keyed: token before, none after",
      len(kb) == 1 and kb[0].startswith("shape:") and ka == [], (kb, ka))
check("[S-C5] worn_record of drapes without shaping: None",
      bs.worn_record([{"template": True, "record": {}}, {"template": True, "record": {"params": CUP}}]) is None)


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
    A, D = [0.05, 1.15, 0.15], [0.05, 1.15, 0.03]          # A -> A1 (block point), D behind the wall
    meshes = [{"name": "body", "primitives": [prim([A, D, [0.0, 0.5, 0.0]])]},
              {"name": "part", "primitives": [prim([A, [0.0, 0.5, 0.0], [0.0, 0.6, 0.0]])]},
              {"name": "garment_clothing_x", "primitives": [prim([A, [0.0, 0.5, 0.0], [0.0, 0.6, 0.0]])]}]
    world = {"Root": [0, 0, 0], "Base": [0.05, 1.15, 0.03], "Tip": [0.05, 1.15, 0.15]}
    nodes = [{"name": "Root", "children": [1, 4, 5, 6]},
             {"name": "Base", "translation": world["Base"], "children": [2]},
             {"name": "Tip", "translation": [0.0, 0.0, 0.12]},
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
out = bs.shape_glb(src, bs.record(LM, 0.25))


def bin_len(b):
    j = struct.unpack_from("<I", b, 12)[0]
    return struct.unpack_from("<I", b, 20 + j)[0]


BASE1 = [A1[0], A1[1], A1[2] - 0.12]
check("in-place: same BIN chunk length", bin_len(out) == bin_len(src))
parsed = glb_mesh._parse(out, "x")
gl = parsed["gltf"]
pos = [np.asarray(glb_mesh.accessor_array(parsed, m["primitives"][0]["attributes"]["POSITION"])) for m in gl["meshes"]]
check("body A shaped", close(pos[0][0], A1, 1e-5), str(pos[0][0]))
check("body B (behind the wall) unchanged", close(pos[0][1], [0.05, 1.15, 0.03], 1e-6))
check("part A shaped alike", close(pos[1][0], A1, 1e-5))
check("garment A untouched", close(pos[2][0], [0.05, 1.15, 0.15], 1e-6))
acc = gl["accessors"][gl["meshes"][0]["primitives"][0]["attributes"]["POSITION"]]
check("POSITION max follows", close(acc["max"], [0.05, A1[1], A1[2]], 1e-5), str(acc["max"]))
heads = glb_mesh.body_arrays(out).joint_positions
check("Tip bind moved", close(heads["tip"], A1, 1e-5), str(heads.get("tip")))
check("Base (Tip's only parent) moves with its chain", close(heads["base"], BASE1, 1e-5), str(heads.get("base")))
check("Base node translation", close(gl["nodes"][1]["translation"], BASE1, 1e-5))
check("Tip node translation kept (the chain moved as a unit)", close(gl["nodes"][2]["translation"], [0.0, 0.0, 0.12], 1e-6),
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
