#!/usr/bin/env python3
"""HairDeck spring chains (``app/core/hair_chains.py``): load, card match, binding (port of HairDeck
``sim.skin`` / ``sim.skin_blend``), placement + follow, joint names / parents / frames, merged weights, and the
wiring into ``garment_hairdeck.fit_hairdeck`` (plan 2026-11-12-hairdeck-spring-chains, Task 2; Ruling H8: the
chains are bound to today's fitted rest, the static fit stays as it was).

Usage: ./.venv/bin/python scripts/smoke_hair_chains_bind.py

No world, no server, no hub: a throwaway storage dir (``paths.init`` first), every mesh / GLB is built in this
file (the GLB body and proxy come from ``scripts/smoke_garment_hairdeck_fit.py``).

Units: HairDeck's head frame (y up, face +z). W = W_HEAD = 0.12759823777166274,
A = ASSIGN * W = 0.4 * W = 0.0510393, R = RAMP * W = 0.15 * W = 0.0191397 (RAMP from spike Ruling H1a).

Fixture
- Chains file, three entries:
  chain 0: joints (0, 0.40, -0.05), (0, 0.35, -0.05), (0, 0.35, -0.05) [a zero-length segment], (0, 0.30, -0.05),
           stiffness 0.4 -> cleaned to 3 joints;
  chain 1: (0.2, 0.4, 0), (0.2, 0.3, 0), stiffness 0.2 (binds nothing);
  chain 2: (0.1, 0.4, 0) twice, stiffness 0.3 -> one joint left after the clean -> dropped by ``load_chains``.
- Card a: rows y = 0.40, 0.395, 0.375, 0.36, 0.35, 0.34, 0.32, 0.30 (root first), each row two vertices at
  x 0.005, z -0.05 -+ 0.001; quads between rows. Card b: rows y 0.40, 0.35, 0.30 at x 0.08, z -0.05 -+ 0.001.
  Cards file: per card ``seq`` = the row centres (x, y, -0.05) padded to 8 columns.

[1] Assignment. Card a's centreline (16 samples of x 0.005, z -0.05, y 0.40 -> 0.30): its lower 60 % (samples 6..15)
    lies 0.005 from chain 0 (a vertical line at x 0, z -0.05) < A -> chain 0; from chain 1 sqrt(0.195^2 + 0.05^2)
    = 0.2013 > A. Card b: 0.08 from chain 0 and sqrt(0.12^2 + 0.05^2) = 0.13 from chain 1, both > A -> rigid.
    Card a's vertex rows (lower 60 % = vertices 6..15) lie sqrt(0.005^2 + 0.001^2) = 0.0051 < A from chain 0, so
    the vertex-level test agrees. load_chains: indices [0, 1], chain 0 with 3 joints. Expected: kept == [0],
    chain 1 dropped, cards bound 1 / rigid 1, mismatch 0.
[2] Card a's vertices (the chain is vertical, so u depends on y only; segment 0 = y 0.40 .. 0.35, segment 1 =
    0.35 .. 0.30, each 0.05 long), (y -> seg, u, seg2, alpha) by skin_blend's rule (u < 0.5 and k > 0: k - 1,
    0.5 + u; u > 0.5 and k < last: k + 1, 1.5 - u; else k, 1):
      0.375 -> 0, 0.5, 0, 1;   0.36 -> 0, 0.8, 1, 0.7;   0.35 -> 0, 1.0, 1, 0.5 (a tie, argmin takes segment 0);
      0.34 -> 1, 0.2, 0, 0.7;  0.32 -> 1, 0.6, 1, 1 (the last segment).
    Weight w = clip(arc / R, 0, 1), arc = 0.40 - y: y 0.40 -> 0, y 0.395 -> 0.005 / R = 0.261237, y <= 0.38 -> 1.
    Card b: chain -1, w 0.
[3] card_centrelines: the matching file -> ``match`` "ok", 2 centrelines of 16 points; one entry less -> None,
    "count"; card b's seq moved 2 mm along x -> centroid offset 0.002 > CARD_MATCH_TOL 0.001 -> None, "offset".
[4] Placement: s 1.5, t (0, 1.0, 0.02): the joint (0, 0.40, -0.05) -> (0, 1.5 * 0.40 + 1.0, 1.5 * -0.05 + 0.02)
    = (0, 1.60, -0.055) +- 1e-9, also through ``adjust_placement`` with forward 0, tilt 0 (the identity).
    ``follow`` with X1 = X0 + (0, 0, -0.01): every IDW weight set sums to 1, so every joint moves by exactly
    (0, 0, -0.01) +- 1e-12. A hand IDW case: a joint at the origin, bound vertices (1, 0, 0) and (0, 2, 0) moved by
    (0.3, 0, 0) and (0, 0.6, 0): k 2 -> weights 1/1 and 1/2 normalised 2/3, 1/3 -> (0.2, 0.2, 0); k 1 -> (0.3, 0, 0).
[5] Names, parents, frames, weights:
    names of chain 0: HairGen_c00_00, HairGen_c00_01, HairGen_c00_end (a chain index 12 -> HairGen_c12_00);
    parents: _00 -> mixamorig:Head, _01 -> _00, _end -> _01; frames: identity rotation, translation = the joint.
    chain_weights on a stand-in skin [Head, Neck, Spine2] whose every row is (0.5, 0.3, 0.2) on joints (0, 1, 2):
    names + the 3 chain names (columns 3, 4, 5); card a's row y 0.36 (w 1, seg 0, seg2 1, alpha 0.7) -> joints
    (0, 3, 4, 0), weights (0, 0.7, 0.3, 0); y 0.395 -> (1 - 0.261237, 0.261237, 0, 0); every row sums to 1 +- 1e-6;
    the Head column = 1 - w, the chain columns w * alpha and w * (1 - alpha); card b keeps (0.5, 0.3, 0.2, 0) on
    (0, 1, 2, 0); _end is never weighted -> weighted bones [_00, _01].
[6] fit_hairdeck on the skinned GLB fixture of smoke_garment_hairdeck_fit.py (head sphere r 0.1 at (0, 1.6, 0),
    neck cylinder, skin Hips / Spine2 / Head; proxy sphere r 0.05 at (0, 0.4, 0) -> s 2, t (0, 0.8, 0)), the hair =
    the two cards of [1] (COLOR_0 0.25 grey), placement forward 0.01, tilt 5, width 0.9:
    - without chains_json / cards_json: positions, joints, weights and joint names identical to BASE 54cea23e's
      fit_hairdeck (loaded from ``git show``), ``report.chains.count`` 0, no joint_parents;
    - with the files: the positions are those of the fit without (Ruling H8: no settle); joint names = BASE's + the
      3 chain names; joint_parents as in [5]; report.chains = count 1, dropped 2 (3 listed, chain 0 kept), cards
      bound 1 / rigid 1, match "ok", chains [{index 0, bones [_00, _01, _end], weighted [_00, _01], stiffness 0.4,
      rigid []}] (those keys; Task 3's rest depth keys are checked in smoke_hair_chains_depth.py); card a's rows weighted as in [5] (Head 1 - w; the chain columns w * alpha, w * (1 - alpha));
      card b's rows and the cap rows identical to the fit without chains;
    - ``_place_and_push(chain_points=…)`` returns ``chain_points`` = adjust_placement(s * J + t, pivot, 0.01, 5)
      (x 0 lies inside the head's half width: ``narrow_sides`` leaves it) +- 1e-12;
    - a cards file with one entry less: ``match`` "count", count 0, weights identical to the fit without chains;
    - ``glb_mesh.graft`` of the chain fit onto the body: no bind frames yet (Task 4), so the chain joints fold onto
      Head through ``joint_parents`` — the grafted skin has no HairGen joint;
    - fails on the old code: BASE 54cea23e's fit_hairdeck raises TypeError on ``chains_json`` (printed).
"""
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402

BASE_COMMIT = "54cea23e"
FAILS = []
W = 0.12759823777166274
R = 0.15 * W
CARD_A_Y = (0.40, 0.395, 0.375, 0.36, 0.35, 0.34, 0.32, 0.30)
CARD_B_Y = (0.40, 0.35, 0.30)
CHAINS = [
    {"joints": [[0, 0.40, -0.05], [0, 0.35, -0.05], [0, 0.35, -0.05], [0, 0.30, -0.05]], "stiffness": 0.4,
     "n_joints": 4},
    {"joints": [[0.2, 0.4, 0], [0.2, 0.3, 0]], "stiffness": 0.2, "n_joints": 2},
    {"joints": [[0.1, 0.4, 0], [0.1, 0.4, 0]], "stiffness": 0.3, "n_joints": 2},
]
NAMES = ["HairGen_c00_00", "HairGen_c00_01", "HairGen_c00_end"]
PARENTS = {"HairGen_c00_00": "mixamorig:Head", "HairGen_c00_01": "HairGen_c00_00",
           "HairGen_c00_end": "HairGen_c00_01"}


def check(cond, label):
    print(("OK   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


def strip(x, ys):
    """Rows ``ys`` (root first), two vertices each at (x, y, -0.05 -+ 0.001), quads between rows."""
    P = [[x, y, z] for y in ys for z in (-0.051, -0.049)]
    F = []
    for i in range(len(ys) - 1):
        a0, a1, b0, b1 = 2 * i, 2 * i + 1, 2 * i + 2, 2 * i + 3
        F += [[a0, b0, b1], [a0, b1, a1]]
    return np.array(P, np.float64), np.array(F, np.int64)


def hair():
    Pa, Fa = strip(0.005, CARD_A_Y)
    Pb, Fb = strip(0.08, CARD_B_Y)
    return np.vstack([Pa, Pb]), np.vstack([Fa, Fb + len(Pa)]), len(Pa)


def cards_file(shift_b=0.0, drop_last=False):
    out = []
    for x, ys in ((0.005, CARD_A_Y), (0.08 + shift_b, CARD_B_Y)):
        out.append({"shape": "strip", "seq": [[x, y, -0.05, 0, 0, 0, 0, 0] for y in ys], "colors": []})
    return json.dumps(out[:-1] if drop_last else out).encode()


def hair_glbs(fx, P, F):
    """``(nohead_glb, proxy_glb)`` of the hair cards ``P``/``F`` (COLOR_0 grey) + the proxy sphere of ``fx``."""
    C = np.tile(np.array([0.25, 0.25, 0.25, 1.0], "<f4"), (len(P), 1))
    U = np.zeros((len(P), 2), "<f4")
    out = []
    for with_proxy in (False, True):
        b = fx.Builder()
        attrs = {"POSITION": b.add(P.astype("<f4"), 5126, "VEC3", minmax=True),
                 "COLOR_0": b.add(C, 5126, "VEC4"), "TEXCOORD_0": b.add(U, 5126, "VEC2")}
        ind = b.add(F.astype("<u4").ravel(), 5125, "SCALAR")
        nodes = [{"name": "hair_cards", "mesh": 0}]
        meshes = [{"name": "hair_cards", "primitives": [{"attributes": attrs, "indices": ind, "material": 0}]}]
        mats = [{"name": "hair", "doubleSided": True}]
        if with_proxy:
            Pp, Fp = fx.uv_sphere(0.05, (0, 0.4, 0), 45, 96)
            pa = b.add(Pp.astype("<f4"), 5126, "VEC3", minmax=True)
            pi = b.add(Fp.astype("<u4").ravel(), 5125, "SCALAR")
            nodes.append({"name": "head_proxy", "mesh": 1})
            meshes.append({"name": "head_proxy", "primitives": [{"attributes": {"POSITION": pa}, "indices": pi,
                                                                 "material": 1}]})
            mats.append({"name": "head"})
        doc = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": list(range(len(nodes)))}],
               "nodes": nodes, "meshes": meshes, "materials": mats}
        out.append(b.glb(doc))
    return out[0], out[1]


def load_base(tmp: Path):
    src = subprocess.run(["git", "-C", str(ROOT), "show", f"{BASE_COMMIT}:app/core/garment_hairdeck.py"],
                         check=True, capture_output=True, text=True).stdout
    path = tmp / "garment_hairdeck_base.py"
    path.write_text(src)
    spec = importlib.util.spec_from_file_location("garment_hairdeck_base", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="hair-chains-bind-") as tmp:
        from app.core import paths
        paths.init(Path(tmp) / "world")
        from app.core import hair_chains as hc
        from app.core import garment_hairdeck as gh
        from app.core import glb_mesh

        P, F, na = hair()
        A = 0.4 * W
        check(abs(A - 0.0510393) < 1e-7 and abs(R - 0.0191397) < 1e-7, f"fixture: A {A:.7f}, R {R:.7f}")
        check(hc.W_HEAD == W and hc.ASSIGN == 0.4 and hc.RAMP == 0.15 and hc.NPT == 16 and hc.FOLLOW_K == 16
              and hc.CARD_MATCH_TOL == 0.001 and hc.HEAD_PARENT == "mixamorig:Head",
              "constants W_HEAD / ASSIGN / RAMP 0.15 / NPT / FOLLOW_K 16 / CARD_MATCH_TOL / HEAD_PARENT")

        # [1]
        print("[1] assignment")
        chains = hc.load_chains(json.dumps(CHAINS).encode())
        check([c.index for c in chains] == [0, 1] and len(chains[0].joints) == 3
              and np.allclose(chains[0].joints[:, 1], [0.40, 0.35, 0.30]) and chains[0].stiffness == 0.4,
              f"load_chains: indices {[c.index for c in chains]}, chain 0 joints {len(chains[0].joints)} (3)")
        cls, info = hc.card_centrelines(cards_file(), P, F)
        check(cls is not None and info["match"] == "ok", f"[3] matching cards file: {info}")
        b = hc.bind(P, F, cls, chains)
        check(b.kept == [0], f"kept {b.kept} == [0] (chain 1 dropped)")
        check(hc.card_counts(b) == (1, 1) and b.mismatch == 0,
              f"cards bound / rigid {hc.card_counts(b)} (1, 1), mismatch {b.mismatch}")
        check(b.card[:na].tolist() == [0] * na and b.card[na:].tolist() == [1] * (len(P) - na),
              "cards = components in first-vertex order")
        check((b.chain[:na] == 0).all() and (b.chain[na:] == -1).all() and (b.w[na:] == 0).all(),
              "card a on chain 0, card b rigid (w 0)")

        # [2]
        print("[2] binding per vertex")
        want = {0.375: (0, 0.5, 0, 1.0), 0.36: (0, 0.8, 1, 0.7), 0.35: (0, 1.0, 1, 0.5), 0.34: (1, 0.2, 0, 0.7),
                0.32: (1, 0.6, 1, 1.0)}
        _d, _k, _arc, u = hc.project(P[:na], chains[0].joints)
        for y, (sg, uu, sg2, al) in want.items():
            rows = np.flatnonzero(np.abs(P[:na, 1] - y) < 1e-12)
            got = [(int(b.seg[i]), round(float(u[i]), 9), int(b.seg2[i]), round(float(b.alpha[i]), 9)) for i in rows]
            check(all(g[0] == sg and abs(g[1] - uu) < 1e-9 and g[2] == sg2 and abs(g[3] - al) < 1e-9 for g in got),
                  f"y {y} -> seg, u, seg2, alpha {got[0]} == {(sg, uu, sg2, al)}")
        for y, ww in ((0.40, 0.0), (0.395, 0.005 / R), (0.375, 1.0), (0.30, 1.0)):
            rows = np.flatnonzero(np.abs(P[:na, 1] - y) < 1e-12)
            check(np.allclose(b.w[rows], ww, atol=1e-9), f"y {y}: w {b.w[rows[0]]:.6f} == {ww:.6f}")

        # [3]
        print("[3] card match")
        check(len(cls) == 2 and all(c.shape == (16, 3) for c in cls), "2 centrelines of 16 points")
        c0, i0 = hc.card_centrelines(cards_file(drop_last=True), P, F)
        check(c0 is None and i0["match"] == "count", f"one entry less -> None, count: {i0}")
        c1, i1 = hc.card_centrelines(cards_file(shift_b=0.002), P, F)
        check(c1 is None and i1["match"] == "offset", f"card b shifted 2 mm -> None, offset: {i1}")

        # [4]
        print("[4] placement + follow")
        s, t = 1.5, np.array([0.0, 1.0, 0.02])
        Jp = s * chains[0].joints + t
        check(np.abs(Jp[0] - [0, 1.60, -0.055]).max() < 1e-9, f"s J + t: {Jp[0].tolist()} == (0, 1.60, -0.055)")
        Ja = gh.adjust_placement(Jp, np.array([0.0, 1.6, 0.0]), 0.0, 0.0)
        check(np.abs(Ja - Jp).max() < 1e-9, "adjust_placement forward 0, tilt 0: unchanged")
        X0 = s * P + t
        X1 = X0 + np.array([0.0, 0.0, -0.01])
        bound = [np.flatnonzero(b.chain == ci) for ci in b.kept]
        moved = hc.follow([Jp], X0, X1, bound)
        check(np.abs(moved[0] - Jp - [0, 0, -0.01]).max() < 1e-12, "follow: every joint moves (0, 0, -0.01)")
        Xa = np.array([[1.0, 0, 0], [0, 2.0, 0]])
        Xb = Xa + np.array([[0.3, 0, 0], [0, 0.6, 0]])
        j2 = hc.follow([np.zeros((1, 3))], Xa, Xb, [np.array([0, 1])], k=2)[0][0]
        j1 = hc.follow([np.zeros((1, 3))], Xa, Xb, [np.array([0, 1])], k=1)[0][0]
        check(np.abs(j2 - [0.2, 0.2, 0]).max() < 1e-12 and np.abs(j1 - [0.3, 0, 0]).max() < 1e-12,
              f"IDW: k 2 -> {j2.tolist()} (0.2, 0.2, 0); k 1 -> {j1.tolist()} (0.3, 0, 0)")

        # [5]
        print("[5] names, parents, frames, weights")
        check(hc.joint_names(chains[0]) == NAMES, f"names {hc.joint_names(chains[0])}")
        check(hc.joint_names(hc.Chain(12, np.zeros((2, 3)) + [[0, 0, 0], [0, 1, 0]], 0.5))[0] == "HairGen_c12_00",
              "chain index 12 -> HairGen_c12_00")
        check(hc.joint_parents([chains[0]]) == PARENTS, f"parents {hc.joint_parents([chains[0]])}")
        fr = hc.joint_frames([chains[0]])
        check(set(fr) == set(NAMES) and all(np.allclose(fr[n][:3, :3], np.eye(3)) for n in NAMES)
              and all(np.allclose(fr[n][:3, 3], chains[0].joints[i]) and np.allclose(fr[n][3], [0, 0, 0, 1])
                      for i, n in enumerate(NAMES)), "frames: identity rotation, translation = the joint")
        n = len(P)
        Js = np.tile(np.array([0, 1, 2, 0], np.int64), (n, 1))
        Ws = np.tile(np.array([0.5, 0.3, 0.2, 0.0]), (n, 1))
        base_names = ["mixamorig:Head", "mixamorig:Neck", "mixamorig:Spine2"]
        names, J2, W2 = hc.chain_weights(base_names, Js, Ws, b, chains)
        check(names == base_names + NAMES, f"names {names}")
        check(np.abs(W2.sum(1) - 1).max() < 1e-6, "every row sums to 1")
        on = np.arange(na)
        head = np.where(J2[on] == 0, W2[on], 0).sum(1)
        c_seg = np.where(J2[on] == 3 + b.seg[on, None], W2[on], 0).sum(1)
        c_seg2 = np.where((J2[on] == 3 + b.seg2[on, None]) & (b.seg2[on, None] != b.seg[on, None]), W2[on], 0).sum(1)
        check(np.allclose(head, 1 - b.w[on], atol=1e-12), "Head column = 1 - w")
        check(np.allclose(c_seg, np.where(b.seg2[on] == b.seg[on], b.w[on], b.w[on] * b.alpha[on]), atol=1e-12)
              and np.allclose(c_seg2, np.where(b.seg2[on] == b.seg[on], 0, b.w[on] * (1 - b.alpha[on])), atol=1e-12),
              "chain columns w * alpha and w * (1 - alpha)")
        r36 = int(np.flatnonzero(np.abs(P[:na, 1] - 0.36) < 1e-12)[0])
        r395 = int(np.flatnonzero(np.abs(P[:na, 1] - 0.395) < 1e-12)[0])
        check(J2[r36].tolist() == [0, 3, 4, 0] and np.allclose(W2[r36], [0, 0.7, 0.3, 0], atol=1e-12),
              f"y 0.36: joints {J2[r36].tolist()} weights {W2[r36].round(6).tolist()}")
        check(np.allclose(W2[r395], [1 - 0.005 / R, 0.005 / R, 0, 0], atol=1e-9),
              f"y 0.395: weights {W2[r395].round(6).tolist()}")
        check(np.array_equal(J2[na:], Js[na:]) and np.array_equal(W2[na:], Ws[na:]), "card b keeps its row")
        check(5 not in set(J2[W2 > 0].tolist()) and hc.weighted_bones(names, J2, W2, chains[0]) == NAMES[:2],
              "_end never weighted; weighted bones [_00, _01]")

        # [6]
        print("[6] fit_hairdeck")
        import smoke_garment_hairdeck_fit as fx
        body_glb = fx.body_glb()
        nohead, proxy = hair_glbs(fx, P, F)
        kw = {"colour_target": None, "forward_m": 0.01, "tilt_deg": 5.0, "width_scale": 0.9}
        base = load_base(Path(tmp))
        rb = base.fit_hairdeck(nohead, proxy, body_glb, **kw)
        r0 = gh.fit_hairdeck(nohead, proxy, body_glb, **kw)
        g0, gb = r0.garment, rb.garment
        same = (np.array_equal(g0.positions, gb.positions) and np.array_equal(g0.joints, gb.joints)
                and np.array_equal(g0.weights, gb.weights) and g0.joint_names == gb.joint_names
                and np.array_equal(g0.indices, gb.indices))
        check(same, f"without chains: positions / joints / weights / names identical to BASE {BASE_COMMIT}")
        check(r0.report["chains"]["count"] == 0 and r0.report["chains"]["chains"] == [] and not g0.joint_parents,
              f"without chains: report.chains {r0.report['chains']}, no joint_parents")
        check(r0.metrics == rb.metrics, "without chains: metrics identical to BASE")

        chains_json, cards_json = json.dumps(CHAINS).encode(), cards_file()
        r1 = gh.fit_hairdeck(nohead, proxy, body_glb, chains_json=chains_json, cards_json=cards_json, **kw)
        g1, rep = r1.garment, r1.report["chains"]
        print(f"       report.chains {rep}")
        check(np.array_equal(g1.positions, g0.positions) and np.array_equal(g1.indices, g0.indices),
              "with chains: positions identical to the fit without (no settle)")
        check(g1.joint_names == g0.joint_names + NAMES, f"with chains: names {g1.joint_names}")
        check(g1.joint_parents == PARENTS, f"with chains: joint_parents {g1.joint_parents}")
        check(rep["count"] == 1 and rep["dropped"] == 2 and rep["cards_bound"] == 1 and rep["cards_rigid"] == 1
              and rep["match"] == "ok", "report.chains: count 1, dropped 2, cards bound 1 / rigid 1, match ok")
        t2_keys = ("index", "bones", "weighted", "stiffness", "rigid")   # Task 3 adds the depth keys
        check([{k: c[k] for k in t2_keys} for c in rep["chains"]]
              == [{"index": 0, "bones": NAMES, "weighted": NAMES[:2], "stiffness": 0.4, "rigid": []}],
              f"report.chains.chains {rep['chains']}")
        nh = len(P)
        k0 = len(g0.joint_names)
        Wg = g1.weights[:na]
        Jg = g1.joints[:na]
        head_col = np.where(Jg == 0, Wg, 0).sum(1)
        ch_a = np.where(Jg == k0 + b.seg[:na, None], Wg, 0).sum(1)
        check(g0.joint_names[0] == "mixamorig:Head" and np.allclose(head_col, 1 - b.w[:na], atol=1e-6)
              and np.allclose(ch_a, np.where(b.seg2[:na] == b.seg[:na], b.w[:na], b.w[:na] * b.alpha[:na]),
                              atol=1e-6), "card a: Head 1 - w, chain column w * alpha")
        check(np.array_equal(g1.weights[na:], g0.weights[na:]) and np.array_equal(g1.joints[na:], g0.joints[na:]),
              f"card b ({nh - na} vertices) and the cap ({len(g1.weights) - nh} vertices) keep their rows")

        # chain_points through _place_and_push: the same correction with the final forward / tilt / width
        from app.core.garment_fit import chin_height, dense_weights, joint_index
        body = glb_mesh.body_arrays(body_glb)
        Ph = glb_mesh.card_arrays(nohead, node="hair_cards")[0].astype(np.float64)
        proxy_pts = glb_mesh.card_arrays(proxy, node="head_proxy")[0]
        head_w = dense_weights(body)[:, joint_index(body, "head")]
        head_v = head_w > 0.5
        chin = chin_height(body)
        top = float(body.positions[head_v, 1].max())
        cranium = body.positions[head_v & (body.positions[:, 1] > chin + gh.CRANIUM_FROM * (top - chin))]
        s6, t6, _icp = gh.place_proxy(proxy_pts, cranium)
        pivot = s6 * (proxy_pts.min(0) + proxy_pts.max(0)) / 2 + t6
        check(abs(s6 - 2.0) < 0.01 and np.abs(t6 - [0, 0.8, 0]).max() < 0.002, f"placement s {s6:.4f}, t {t6}")
        cp = s6 * chains[0].joints + t6
        pushed, placement = gh._place_and_push(s6 * Ph + t6, pivot, F, None, body, head_v, chin, top, 0.01, 5.0,
                                               None, 0.9, chain_points=cp)
        want_cp = gh.adjust_placement(cp, pivot, 0.01, 5.0)
        check(placement["tilt_deg"] == 5.0 and np.abs(pushed["chain_points"] - want_cp).max() < 1e-12,
              f"_place_and_push chain_points = adjust_placement(s J + t, pivot, 0.01, 5): "
              f"{np.abs(pushed['chain_points'] - want_cp).max():.2e}")

        r2 = gh.fit_hairdeck(nohead, proxy, body_glb, chains_json=chains_json,
                             cards_json=cards_file(drop_last=True), **kw)
        check(r2.report["chains"]["match"] == "count" and r2.report["chains"]["count"] == 0
              and np.array_equal(r2.garment.weights, g0.weights) and r2.garment.joint_names == g0.joint_names,
              f"cards file one short: {r2.report['chains']}, weights as without chains")

        grafted = glb_mesh.graft(body_glb, g1, name="garment_hair_smoke", extras={"kind": "hair"})
        gltf = glb_mesh._parse(grafted, "Target")["gltf"]
        joint_nodes = [gltf["nodes"][j]["name"] for j in gltf["skins"][0]["joints"]]
        check(not any(nm.startswith("HairGen_") for nm in joint_nodes),
              f"graft folds the chain joints onto Head (skin {joint_nodes})")

        try:
            base.fit_hairdeck(nohead, proxy, body_glb, chains_json=chains_json, cards_json=cards_json, **kw)
            check(False, f"BASE {BASE_COMMIT} fit_hairdeck refuses chains_json")
        except TypeError as e:
            print(f"       fails on the old code (BASE {BASE_COMMIT}): TypeError: {e}")
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
