#!/usr/bin/env python3
"""HairDeck spring chains: the rest depth check of the placed chain joints against the body surface and its
repair (``hair_chains.repair_depth`` / ``nearest_outside`` / ``card_centroid_line`` / ``unbind``, wired into
``garment_hairdeck.fit_hairdeck``) — plan 2026-11-12-hairdeck-spring-chains, Task 3 in its Ruling H8 form: no
rest-pose settle, the cards and every fit step stay as they are; a joint more than SETTLE_TOL_M inside the body
moves onto its card-centroid line at the nearest point outside the body, a chain without one is unbound (its cards
keep today's rigid weights). Never a refusal. Task 4 adds Ruling H9: a repair that would move a joint more than
max(3 x its depth, 30 mm), or leave one of its segments shorter than 40 % of its original length, truncates the chain
at that joint (the repairs run from the root down; fewer than two joints left = unbound, reason "truncated").

Usage: ./.venv/bin/python scripts/smoke_hair_chains_depth.py

No world, no server, no hub: a throwaway storage dir (``paths.init`` first); every mesh / GLB is built in code (the
body and hair fixtures of ``smoke_garment_hairdeck_fit.py`` / ``smoke_hair_chains_bind.py``).

[1] Units, against an ANALYTIC sphere body: centre (0, 0, 0), r 0.1, sdf(x) = |x| - 0.1 (negative inside).
    SETTLE_TOL_M = 0.005 (spike Ruling H1a). ``repair_depth(..., k=1)``: each joint's centroid is its single
    nearest bound vertex.
    - joint_depth: (0, 0, 0) -> 0.1; (0.2, 0, 0) -> 0 (outside counts 0).
    - card_centroid_line: one joint at the origin, vertices (1, 0, 0), (0, 2, 0), (5, 5, 5), k 2 -> the mean of the
      two nearest = (0.5, 1, 0).
    - nearest_outside, line A = (0, 0.15, 0.06) -> (0, 0.05, 0.06) -> (0, -0.15, 0.06) (vertical, x 0, z 0.06):
      a point of it is outside iff y^2 + 0.06^2 >= 0.1^2 iff |y| >= 0.08.
      p (0.2, 0.12, 0): its projection (0, 0.12, 0.06) is outside (|.| = sqrt(0.0144 + 0.0036) = 0.1342) -> itself.
      p (0, 0.05, 0): its projection (0, 0.05, 0.06) is inside (0.0781); the outside intervals end at y 0.08
      (distance sqrt(0.03^2 + 0.06^2) = 0.06708) and y -0.08 (sqrt(0.13^2 + 0.06^2) = 0.14318), the end points
      (0, +-0.15, 0.06) are farther -> (0, 0.08, 0.06) +- 1e-9.
      A line wholly inside ((0, 0.02, 0.03) -> (0, -0.02, 0.03), |.| <= 0.036) -> None.
    - repair_depth on four chains (bound vertices = the line points, k 1):
      A  joints (0, 0.15, 0), (0, 0.05, 0), (0, -0.15, 0); line A. Depths 0.05 outside -> 0, 0.05, 0 -> joint 1 deep
         (0.05 > 0.005) -> (0, 0.08, 0.06) as above; joints 0 and 2 keep their exact bytes. Depth after 0, 0, 0.
      B  joints (0, 0.02, 0), (0, -0.02, 0) (depth 0.08 each); line = the inside line above -> no outside point ->
         unbound, reason "unreachable", joints unchanged.
      C  joints (0.12, 0, 0), (0.097, 0, 0): depths 0 and 0.003 <= 0.005 -> clean, untouched (exact bytes), depth
         after 0, 0.003.
      D  joints (0, 0.15, 0), (0, 0.05, 0), (0, -0.05, 0); line (0, 0.15|0.05|-0.05, 0.06): joint 1 -> (0, 0.08,
         0.06) as for A (move 0.06708 <= max(3 * 0.05, 0.03) = 0.15; its segments 0.0922 / 0.1432 against 0.1 / 0.1
         originally, both >= 40 %); joint 2 (depth 0.05): segment 0.05 .. -0.05 lies wholly inside (|.| <= 0.0781),
         segment 0.15 .. 0.05 is outside for y >= 0.08 -> (0, 0.08, 0.06), distance 0.14318 <= 0.15 (the end
         (0, 0.15, 0.06) is 0.2088 away) -> the same point as the repaired joint 1 -> segment 1 would be 0 < 40 % of
         0.1 -> Ruling H9 truncates at joint 2 (was "collapsed" before H9): D keeps (0, 0.15, 0), (0, 0.08, 0.06),
         moved [1], truncated_at 2, truncate "segment".
      Expected: unbound [1], moved_joints 2 (A's and D's joint 1), per chain ``moved`` [1], [], [], [1].
[2] ``unbind`` on smoke_hair_chains_bind's fixture binding (card a on chain 0, card b rigid): unbind [0] -> every
    vertex chain -1, w 0, alpha 1, kept [], card_counts (0, 2); ``chain_weights`` then returns the stand-in skin
    unchanged.
[3] ``fit_hairdeck`` on smoke_hair_chains_bind's fit fixture (head sphere r 0.1 at (0, 1.6, 0), neck cylinder r
    0.04; hair = cards a and b, proxy -> s 2, t (0, 0.8, 0); placement forward 0.01, tilt 5, width 0.9).
    DEEP chains file (Task 4: two joints, so that the root's repair passes Ruling H9): chain 0 = (0, 0.40, -0.03),
    (0, 0.30, -0.05), stiffness 0.4 (card a still binds: its lower 60 % lies within ~0.015 of the segment, below
    ASSIGN * W = 0.051; the vertex rows the same). Mapped s J + t, then forward +0.01 (z) and the tilt about the
    head centre (distance-preserving): the root -> |z| = 2 * 0.03 - 0.01 = 0.05 from the head centre -> 0.05 inside
    the head sphere. ``follow`` moves it by the IDW mean push of card a (the card sits on the sphere, moved 1 cm
    forward into it, pushed back out by ~1.4 cm: |push| < 0.02) -> still >= 0.03 > SETTLE_TOL_M deep. Joint 1 at
    (0, 1.4, -0.09) lies 0.05 outside the neck cylinder. Card a has 16 vertices = FOLLOW_K, so every joint's
    centroid is the centroid of card a, at (~0.01, ~1.51, ~-0.1): 0.14 from the head centre, outside -> the root
    moves there: ~0.11 <= 3 x its depth (>= 0.035 -> >= 0.105 .. the measured depth is printed), and segment 0
    goes from ~0.204 to ~0.10 (>= 40 %).
    DEEP3 (the T3 file, three joints, the middle at (0, 0.35, -0.05) -> (0, 1.5, -0.09), next to card a's centroid):
    the root's repair would leave segment 0 at ~0.01 of ~0.108 < 40 % -> Ruling H9 truncates at joint 0 -> fewer
    than two joints -> unbound, reason "truncated", repair.truncated_chains [{index 0, at 0, why "segment"}]; the
    skin is that of the fit without chains.
    - report.chains: joint_depth_before_max_m >= 0.02, repair.moved_joints 1, unbound_chains [], joint_depth_max_m
      0.0 (the repaired root samples >= 0 by construction, the others are outside), per chain moved [0];
    - the garment (positions, normals, uvs, colours, indices, joints, weights, joint names, joint_parents) is
      byte-identical to the fit of e6f179ae with the same files — moving a joint changes no card — and the
      positions are those of the fit without chains;
    - unreachable wiring: with ``hair_chains.nearest_outside`` patched to None, the chain is unbound (reason
      "unreachable"): report.chains count 0, cards_bound 0 / rigid 2, chains [], joint_depth_max_m 0.0; joints,
      weights and joint names identical to the fit WITHOUT chains, no joint_parents; positions unchanged;
    - without chains: report.chains joint_depth_max_m 0.0, repair moved 0 / unbound []; garment and metrics
      identical to e6f179ae's;
    - the T2 chains file (root at z -0.05 -> on the head sphere, forward 0.01 -> ~0.01 inside before the follow):
      per chain ``moved`` is non-empty exactly when depth_before_max_m > SETTLE_TOL_M, and joint_depth_max_m
      <= SETTLE_TOL_M; the garment again byte-identical to e6f179ae's.
[4] Fails on the old code: e6f179ae's hair_chains has no ``repair_depth`` (AttributeError, printed), and its
    fit_hairdeck reports no ``joint_depth_max_m`` for the DEEP file (the root stays 0.03+ inside).
[5] Ruling H9 (Task 4), against the analytic sphere (centre 0, r 0.1), ``repair_depth(..., k=1)``. Line Z = the
    vertical x 0, z -0.06: a point of it is outside iff |y| >= 0.08 (y^2 + 0.0036 >= 0.01).
    E — the Kira 42 chain 3 shape (a shallow tip whose card-centroid line runs inside the body up to far above it;
       measured: depth 8.5 mm, move 113 mm, last segment 122.5 -> 10.1 mm): joints (0, 0.3225 | 0.2225 | 0.1225 | 0,
       -0.0915), vertices (= the line, one per joint) (0, same y, -0.06), each joint's nearest (0.0315 away; the
       next is >= 0.1). Depths: |(0, 0, -0.0915)| = 0.0915 -> the tip 0.0085 deep, the others outside (|.| >=
       0.1529). The tip's projection onto the line is (0, 0, -0.06), inside; the only outside part near it starts at
       y 0.08 -> q = (0, 0.08, -0.06), move sqrt(0.08^2 + 0.0315^2) = 0.085978 > max(3 * 0.0085, 0.03) = 0.03 ->
       truncated at 3 ("move"): the chain keeps its first three joints with their exact bytes, moved [], unbound
       none, depth after (0, 0, 0), move_m[3] = 0.085978.
    F — the segment rule: joints (0, 0.192, -0.06), (0, 0.092, -0.06), (0, 0.06, -0.07), (0, -0.04, -0.12);
       vertices (0, 0.192 | 0.092 | 0.06 | -0.04, -0.06), nearest to joints 0..3 (0 / 0 / 0.01 / 0.06 away; the next
       0.0335 / 0.1166 for joints 2 / 3). Depths: joint 2 |.| = sqrt(0.0036 + 0.0049) = 0.092195 -> 0.007805 deep,
       the others outside (0.2012, 0.1124, 0.1265). Joint 2's nearest outside point: the crossing (0, 0.08, -0.06)
       (0.022361 away; the outside end (0, 0.092, -0.06) is 0.033526) -> move 0.022361 <= max(0.023416, 0.03);
       segment 1 would be |(0, 0.08) - (0, 0.092)| = 0.012 < 0.4 * 0.033526 = 0.013410 -> truncated at 2
       ("segment"): keeps joints 0 and 1 (exact bytes), moved [].
    G — F's first two joints plus a deep tip only: (0, 0.192, -0.06), (0, 0.092, -0.06), (0, 0, -0.06) (depth 0.04,
       the line through the same three points): the tip's nearest outside point is (0, 0.08, -0.06), move 0.08 <=
       max(0.12, 0.03), segment 1 0.012 < 0.4 * 0.092 = 0.0368 -> truncated at 2 -> keeps 2 joints. A tip the same but
       on a ONE-segment chain (0, 0.092, -0.06), (0, 0, -0.06): segment 0 0.012 < 0.0368 -> truncated at 1 -> one
       joint left -> unbound, reason "truncated".
    ``truncate`` on a hand-made binding (chain 0 with 4 joints = 3 segments; rows (seg, seg2, alpha): (0, 0, 1),
    (1, 0, 0.8), (1, 2, 0.7), (2, 1, 0.6), (2, 2, 1); one vertex on chain 1 (2, 1, 0.9) stays): keep 3 joints (2
    segments, last bone 1) -> (0, 0, 1), (1, 0, 0.8), (1, 1, 1), (1, 1, 1), (1, 1, 1); chain 1 unchanged; w
    unchanged. Keeping 1 joint raises ValueError.
    fit_hairdeck with chain TIP (HairDeck space) (0, 0.40, -0.06), (0, 0.35, -0.06), (0, 0.43, -0.03) (a strand
    tip bent back up into the crown): mapped the root (0, 1.6, -0.11) and joint 1 (0, 1.5, -0.11) lie outside the
    head (0.11 / 0.149 from its centre) and the neck; the tip (0, 1.66, -0.05) is sqrt(0.06^2 + 0.05^2) = 0.0781
    from the head centre (the tilt keeps that) -> ~0.022 inside (measured 0.028 after the follow, printed). Its line
    is card a's centroid (~0.01, ~1.52, ~-0.10) three times -> move ~0.15 > max(3 * ~0.03, 0.03) -> truncated at 2
    ("move"): report.chains count 1,
    truncated_chains [{index 0, at 2, kept_joints 2}], bones [HairGen_c00_00, HairGen_c00_end], weighted
    [HairGen_c00_00]; joint_parents {_00: Head, _end: _00}; joint_binds = those two names with identity rotation;
    every chain-bound vertex's two segment columns name _00 (the tip's segment 1 is gone); the positions are the
    fit's without chains.
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

BASE_COMMIT = "e6f179ae"
FAILS = []


def check(cond, label):
    print(("OK   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


class SphereSdf:
    """Analytic signed distance of a sphere (negative inside), the ``Sdf.sample`` interface."""

    def __init__(self, centre, r):
        self.c, self.r = np.asarray(centre, np.float64), float(r)

    def sample(self, X):
        return np.linalg.norm(np.asarray(X, np.float64).reshape(-1, 3) - self.c, axis=1) - self.r


def load_base(tmp: Path, rel: str, name: str):
    src = subprocess.run(["git", "-C", str(ROOT), "show", f"{BASE_COMMIT}:{rel}"],
                         check=True, capture_output=True, text=True).stdout
    path = tmp / f"{name}.py"
    path.write_text(src)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod      # dataclasses look their module up while the class is built
    spec.loader.exec_module(mod)
    return mod


def same_garment(a, b, *, skin=True):
    keys = ["positions", "normals", "uvs", "colors", "indices"] + (["joints", "weights"] if skin else [])
    return all(np.array_equal(getattr(a, k), getattr(b, k)) for k in keys) and (
        not skin or (a.joint_names == b.joint_names and a.joint_parents == b.joint_parents))


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="hair-chains-depth-") as tmp:
        from app.core import paths
        paths.init(Path(tmp) / "world")
        from app.core import hair_chains as hc
        from app.core import garment_hairdeck as gh

        check(hc.SETTLE_TOL_M == 0.005, f"SETTLE_TOL_M {hc.SETTLE_TOL_M} == 0.005 (H1a)")
        sd = SphereSdf((0, 0, 0), 0.1)

        # [1]
        print("[1] units")
        d = hc.joint_depth([np.array([[0.0, 0, 0], [0.2, 0, 0]])], sd)[0]
        check(np.allclose(d, [0.1, 0.0], atol=1e-12), f"joint_depth {d.tolist()} == [0.1, 0]")
        cl = hc.card_centroid_line(np.zeros((1, 3)), np.array([[1.0, 0, 0], [0, 2.0, 0], [5.0, 5, 5]]),
                                   np.arange(3), k=2)
        check(np.allclose(cl, [[0.5, 1.0, 0]], atol=1e-12), f"card_centroid_line k 2 -> {cl.tolist()}")
        lineA = np.array([[0, 0.15, 0.06], [0, 0.05, 0.06], [0, -0.15, 0.06]])
        q = hc.nearest_outside(np.array([0.2, 0.12, 0]), lineA, sd)
        check(q is not None and np.abs(q - [0, 0.12, 0.06]).max() < 1e-12, f"projection outside -> {q}")
        q = hc.nearest_outside(np.array([0, 0.05, 0]), lineA, sd)
        check(q is not None and np.abs(q - [0, 0.08, 0.06]).max() < 1e-9 and sd.sample(q)[0] >= 0,
              f"projection inside -> {None if q is None else q.tolist()} == (0, 0.08, 0.06), sdf >= 0")
        inner = np.array([[0, 0.02, 0.03], [0, -0.02, 0.03]])
        check(hc.nearest_outside(np.zeros(3), inner, sd) is None, "line wholly inside -> None")

        JA = np.array([[0, 0.15, 0], [0, 0.05, 0], [0, -0.15, 0]])
        JB = np.array([[0, 0.02, 0], [0, -0.02, 0]])
        JC = np.array([[0.12, 0, 0], [0.097, 0, 0]])
        JD = np.array([[0, 0.15, 0], [0, 0.05, 0], [0, -0.05, 0]])
        lineD = np.array([[0, 0.15, 0.06], [0, 0.05, 0.06], [0, -0.05, 0.06]])
        X = np.vstack([lineA, inner, np.array([[0.13, 0, 0], [0.13, -0.05, 0]]), lineD])
        bound = [np.arange(0, 3), np.arange(3, 5), np.arange(5, 7), np.arange(7, 10)]
        joints = [JA.copy(), JB.copy(), JC.copy(), JD.copy()]
        out, unbound, info = hc.repair_depth(joints, X, bound, sd, k=1)
        check(unbound == [1], f"unbound {unbound} == [1]")
        check(info["moved_joints"] == 2 and [c["moved"] for c in info["chains"]] == [[1], [], [], [1]],
              f"moved_joints {info['moved_joints']}, per chain {[c['moved'] for c in info['chains']]}")
        check(np.abs(out[0][1] - [0, 0.08, 0.06]).max() < 1e-9, f"A joint 1 -> {out[0][1].tolist()} (0, 0.08, 0.06)")
        check(out[0][0].tobytes() == JA[0].tobytes() and out[0][2].tobytes() == JA[2].tobytes(),
              "A joints 0 and 2 keep their exact bytes")
        check(np.allclose(info["chains"][0]["depth_before"], [0, 0.05, 0], atol=1e-12)
              and np.allclose(info["chains"][0]["depth_after"], 0, atol=1e-12),
              f"A depth before {info['chains'][0]['depth_before'].round(6).tolist()}, after "
              f"{info['chains'][0]['depth_after'].round(9).tolist()}")
        check(info["chains"][1]["reason"] == "unreachable" and out[1].tobytes() == JB.tobytes()
              and np.allclose(info["chains"][1]["depth_before"], [0.08, 0.08], atol=1e-12),
              f"B unbound (unreachable), joints unchanged, depth {info['chains'][1]['depth_before'].tolist()}")
        check(out[2].tobytes() == JC.tobytes() and info["chains"][2]["reason"] is None
              and np.allclose(info["chains"][2]["depth_after"], [0, 0.003], atol=1e-12),
              f"C clean: untouched, depth {info['chains'][2]['depth_after'].round(6).tolist()} == [0, 0.003]")
        check(info["chains"][3]["reason"] is None and info["chains"][3]["truncated_at"] == 2
              and info["chains"][3]["truncate"] == "segment" and len(out[3]) == 2
              and out[3][0].tobytes() == JD[0].tobytes() and np.abs(out[3][1] - [0, 0.08, 0.06]).max() < 1e-9,
              f"D truncated at 2 (segment): {out[3].round(6).tolist()}")
        check(all(j.tobytes() == o.tobytes() for j, o in zip(joints, [JA, JB, JC, JD])), "inputs not mutated")

        # [2]
        print("[2] unbind")
        import smoke_hair_chains_bind as sb
        P, F, na = sb.hair()
        chains = hc.load_chains(json.dumps(sb.CHAINS).encode())
        cls, _info = hc.card_centrelines(sb.cards_file(), P, F)
        b = hc.bind(P, F, cls, chains)
        ub = hc.unbind(b, [0])
        check((ub.chain == -1).all() and (ub.w == 0).all() and (ub.alpha == 1).all() and ub.kept == []
              and hc.card_counts(ub) == (0, 2) and b.kept == [0],
              f"unbind [0]: kept {ub.kept}, card_counts {hc.card_counts(ub)}; the original keeps {b.kept}")
        n = len(P)
        Js = np.tile(np.array([0, 1, 2, 0], np.int64), (n, 1))
        Ws = np.tile(np.array([0.5, 0.3, 0.2, 0.0]), (n, 1))
        base_names = ["mixamorig:Head", "mixamorig:Neck", "mixamorig:Spine2"]
        nm, J2, W2 = hc.chain_weights(base_names, Js, Ws, ub, chains)
        check(nm == base_names and np.array_equal(J2, Js) and np.array_equal(W2, Ws),
              "chain_weights of the unbound binding = the stand-in skin")

        # [3]
        print("[3] fit_hairdeck")
        import smoke_garment_hairdeck_fit as fx
        body_glb = fx.body_glb()
        nohead, proxy = sb.hair_glbs(fx, P, F)
        kw = {"colour_target": None, "forward_m": 0.01, "tilt_deg": 5.0, "width_scale": 0.9}
        deep = [{"joints": [[0, 0.40, -0.03], [0, 0.30, -0.05]], "stiffness": 0.4}]
        deep3 = [{"joints": [[0, 0.40, -0.03], [0, 0.35, -0.05], [0, 0.30, -0.05]], "stiffness": 0.4}]
        deep_json, cards_json = json.dumps(deep).encode(), sb.cards_file()
        base = load_base(Path(tmp), "app/core/garment_hairdeck.py", "garment_hairdeck_base")

        r0 = gh.fit_hairdeck(nohead, proxy, body_glb, **kw)
        rb0 = base.fit_hairdeck(nohead, proxy, body_glb, **kw)
        rep0 = r0.report["chains"]
        check(rep0["joint_depth_max_m"] == 0.0 and rep0["repair"]["moved_joints"] == 0
              and rep0["repair"]["unbound_chains"] == [], f"without chains: {rep0}")
        check(same_garment(r0.garment, rb0.garment) and r0.metrics == rb0.metrics,
              f"without chains: garment and metrics identical to {BASE_COMMIT}")

        r1 = gh.fit_hairdeck(nohead, proxy, body_glb, chains_json=deep_json, cards_json=cards_json, **kw)
        rb1 = base.fit_hairdeck(nohead, proxy, body_glb, chains_json=deep_json, cards_json=cards_json, **kw)
        rep = r1.report["chains"]
        print(f"       deep: report.chains {json.dumps({k: v for k, v in rep.items() if k != 'chains'})}")
        print(f"             chains {rep['chains']}")
        check(rep["count"] == 1 and rep["joint_depth_before_max_m"] >= 0.02 and rep["repair"]["moved_joints"] == 1
              and rep["repair"]["unbound_chains"] == [] and rep["joint_depth_max_m"] == 0.0
              and rep["chains"][0]["moved"] == [0],
              f"deep: before {rep['joint_depth_before_max_m']} >= 0.02, moved 1 (the root), unbound [], after 0.0")
        check(same_garment(r1.garment, rb1.garment) and r1.metrics == rb1.metrics,
              f"deep: garment (incl. skin, joint_parents) and metrics byte-identical to {BASE_COMMIT}")
        check(np.array_equal(r1.garment.positions, r0.garment.positions), "deep: positions = the fit without chains")

        r4 = gh.fit_hairdeck(nohead, proxy, body_glb, chains_json=json.dumps(deep3).encode(), cards_json=cards_json,
                             **kw)
        rep4 = r4.report["chains"]
        print(f"       deep3: {json.dumps({k: v for k, v in rep4.items() if k != 'chains'})}")
        tr4 = rep4["repair"]["truncated_chains"]
        check(rep4["count"] == 0 and rep4["chains"] == []
              and [(u["index"], u["reason"]) for u in rep4["repair"]["unbound_chains"]] == [(0, "truncated")]
              and [(t["index"], t["at"], t["why"]) for t in tr4] == [(0, 0, "segment")],
              "deep3 (H9): truncated at the root -> unbound 'truncated'")
        check(same_garment(r4.garment, r0.garment) and not r4.garment.joint_parents and not r4.garment.joint_binds,
              "deep3: garment incl. skin identical to the fit without chains, no joint_parents / joint_binds")

        real = hc.nearest_outside
        hc.nearest_outside = lambda *a, **k: None
        try:
            r2 = gh.fit_hairdeck(nohead, proxy, body_glb, chains_json=deep_json, cards_json=cards_json, **kw)
        finally:
            hc.nearest_outside = real
        rep2 = r2.report["chains"]
        print(f"       unreachable: {json.dumps({k: v for k, v in rep2.items() if k != 'chains'})}")
        check(rep2["count"] == 0 and rep2["cards_bound"] == 0 and rep2["cards_rigid"] == 2 and rep2["chains"] == []
              and rep2["joint_depth_max_m"] == 0.0 and rep2["joint_depth_before_max_m"] >= 0.02
              and [(u["index"], u["reason"]) for u in rep2["repair"]["unbound_chains"]] == [(0, "unreachable")],
              "unreachable: chain 0 unbound, count 0, cards bound 0 / rigid 2")
        check(same_garment(r2.garment, r0.garment) and not r2.garment.joint_parents,
              "unreachable: garment incl. skin identical to the fit without chains, no joint_parents")

        r3 = gh.fit_hairdeck(nohead, proxy, body_glb, chains_json=json.dumps(sb.CHAINS).encode(),
                             cards_json=cards_json, **kw)
        rb3 = base.fit_hairdeck(nohead, proxy, body_glb, chains_json=json.dumps(sb.CHAINS).encode(),
                                cards_json=cards_json, **kw)
        rep3 = r3.report["chains"]
        print(f"       T2 file: {json.dumps({k: v for k, v in rep3.items() if k != 'chains'})}")
        check(all(bool(c["moved"]) == (c["depth_before_max_m"] > hc.SETTLE_TOL_M) for c in rep3["chains"])
              and rep3["joint_depth_max_m"] <= hc.SETTLE_TOL_M and rep3["repair"]["unbound_chains"] == [],
              "T2 file: moved iff deeper than the tolerance, depth after <= SETTLE_TOL_M")
        check(same_garment(r3.garment, rb3.garment), f"T2 file: garment byte-identical to {BASE_COMMIT}")

        # [4]
        print("[4] fails on the old code")
        old_hc = load_base(Path(tmp), "app/core/hair_chains.py", "hair_chains_base")
        try:
            old_hc.repair_depth
            check(False, f"{BASE_COMMIT} hair_chains has no repair_depth")
        except AttributeError as e:
            print(f"       {BASE_COMMIT} hair_chains: AttributeError: {e}")
        check("joint_depth_max_m" not in rb1.report["chains"],
              f"{BASE_COMMIT} fit_hairdeck reports no joint_depth_max_m for the deep file")
        # [5]
        print("[5] Ruling H9")
        check((hc.TRUNCATE_MOVE_DEPTHS, hc.TRUNCATE_MOVE_MIN_M, hc.TRUNCATE_SEGMENT_SHARE) == (3.0, 0.03, 0.4),
              "H9 constants 3 x depth / 30 mm / 40 %")
        JE = np.array([[0, 0.3225, -0.0915], [0, 0.2225, -0.0915], [0, 0.1225, -0.0915], [0, 0.0, -0.0915]])
        XE = JE.copy()
        XE[:, 2] = -0.06
        JF = np.array([[0, 0.192, -0.06], [0, 0.092, -0.06], [0, 0.06, -0.07], [0, -0.04, -0.12]])
        XF = np.array([[0, 0.192, -0.06], [0, 0.092, -0.06], [0, 0.06, -0.06], [0, -0.04, -0.06]])
        JG = np.array([[0, 0.192, -0.06], [0, 0.092, -0.06], [0, 0.0, -0.06]])
        JG1 = np.array([[0, 0.092, -0.06], [0, 0.0, -0.06]])
        X5 = np.vstack([XE, XF, JG, JG1])
        b5 = [np.arange(0, 4), np.arange(4, 8), np.arange(8, 11), np.arange(11, 13)]
        out5, unb5, info5 = hc.repair_depth([JE, JF, JG, JG1], X5, b5, sd, k=1)
        e, f, g, g1 = info5["chains"]
        check(abs(e["depth_before"][3] - 0.0085) < 1e-12 and e["truncated_at"] == 3 and e["truncate"] == "move"
              and abs(e["move_m"][3] - 0.085978) < 1e-6 and e["reason"] is None and e["moved"] == []
              and len(out5[0]) == 3 and out5[0].tobytes() == JE[:3].tobytes()
              and np.allclose(e["depth_after"], 0, atol=1e-12),
              f"E (Kira 42 c3 shape): depth {e['depth_before'][3]:.4f}, move {e['move_m'][3]:.6f} > 0.03 -> "
              f"truncated at {e['truncated_at']} ({e['truncate']}), keeps {len(out5[0])} joints unchanged")
        check(f["truncated_at"] == 2 and f["truncate"] == "segment" and abs(f["move_m"][2] - 0.022361) < 1e-6
              and abs(f["depth_before"][2] - 0.007805) < 1e-6 and f["reason"] is None and f["moved"] == []
              and out5[1].tobytes() == JF[:2].tobytes(),
              f"F: move {f['move_m'][2]:.6f} within, segment 0.012 < 0.013410 -> truncated at {f['truncated_at']} "
              f"({f['truncate']})")
        check(g["truncated_at"] == 2 and g["truncate"] == "segment" and out5[2].tobytes() == JG[:2].tobytes()
              and g1["truncated_at"] == 1 and g1["reason"] == "truncated" and out5[3].tobytes() == JG1.tobytes(),
              f"G: truncated at 2 keeps 2; the one-segment chain -> unbound 'truncated' ({g1['reason']})")
        check(unb5 == [3] and info5["moved_joints"] == 0, f"unbound {unb5} == [3], moved_joints 0")

        tb = hc.Binding(card=np.zeros(6, np.int64), chain=np.array([0, 0, 0, 0, 0, 1]),
                        seg=np.array([0, 1, 1, 2, 2, 2]), w=np.array([0.1, 0.2, 0.3, 0.4, 0.5, 0.6]),
                        seg2=np.array([0, 0, 2, 1, 2, 1]), alpha=np.array([1, 0.8, 0.7, 0.6, 1, 0.9]),
                        kept=[0, 1], cards=1)
        tt = hc.truncate(tb, {0: 3})
        check(tt.seg.tolist() == [0, 1, 1, 1, 1, 2] and tt.seg2.tolist() == [0, 0, 1, 1, 1, 1]
              and np.allclose(tt.alpha, [1, 0.8, 1, 1, 1, 0.9]) and np.array_equal(tt.w, tb.w)
              and tb.seg.tolist() == [0, 1, 1, 2, 2, 2],
              f"truncate keep 3: seg {tt.seg.tolist()}, seg2 {tt.seg2.tolist()}, alpha {tt.alpha.tolist()}")
        try:
            hc.truncate(tb, {0: 1})
            check(False, "truncate to one joint raises")
        except ValueError:
            check(True, "truncate to one joint raises ValueError")

        tip = [{"joints": [[0, 0.40, -0.06], [0, 0.35, -0.06], [0, 0.43, -0.03]], "stiffness": 0.4}]
        r5 = gh.fit_hairdeck(nohead, proxy, body_glb, chains_json=json.dumps(tip).encode(), cards_json=cards_json,
                             **kw)
        rep5 = r5.report["chains"]
        g5 = r5.garment
        print(f"       tip: {json.dumps({k: v for k, v in rep5.items() if k != 'chains'})}")
        print(f"            chains {rep5['chains']}")
        tr5 = rep5["repair"]["truncated_chains"]
        names5 = ["HairGen_c00_00", "HairGen_c00_end"]
        check(rep5["count"] == 1 and [(t["index"], t["at"], t["kept_joints"], t["why"]) for t in tr5]
              == [(0, 2, 2, "move")] and rep5["repair"]["unbound_chains"] == []
              and rep5["chains"][0]["bones"] == names5 and rep5["chains"][0]["weighted"] == names5[:1]
              and rep5["chains"][0]["truncated_at"] == 2,
              "tip: truncated at 2 (move), bones [_00, _end], weighted [_00]")
        check(g5.joint_parents == {"HairGen_c00_00": "mixamorig:Head", "HairGen_c00_end": "HairGen_c00_00"}
              and sorted(g5.joint_binds) == names5
              and all(np.allclose(g5.joint_binds[n][:3, :3], np.eye(3)) for n in names5),
              f"tip: joint_parents {g5.joint_parents}, joint_binds {sorted(g5.joint_binds)} (identity rotation)")
        col = g5.joint_names.index("HairGen_c00_00")
        bound_rows = np.flatnonzero(np.isin(g5.joints[:, 1:3], [g5.joint_names.index(n) for n in names5]).any(1))
        check(len(bound_rows) > 0 and (g5.joints[bound_rows, 1] == col).all()
              and (g5.joints[bound_rows, 2] == col).all() and np.allclose(g5.weights.sum(1), 1),
              f"tip: {len(bound_rows)} chain-bound vertices, both segment columns = _00, rows sum to 1")
        check(np.array_equal(g5.positions, r0.garment.positions), "tip: positions = the fit without chains")
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
