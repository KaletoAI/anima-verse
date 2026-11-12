#!/usr/bin/env python3
"""HairDeck spring chains: the rest depth check of the placed chain joints against the body surface and its
repair (``hair_chains.repair_depth`` / ``nearest_outside`` / ``card_centroid_line`` / ``unbind``, wired into
``garment_hairdeck.fit_hairdeck``) — plan 2026-11-12-hairdeck-spring-chains, Task 3 in its Ruling H8 form: no
rest-pose settle, the cards and every fit step stay as they are; a joint more than SETTLE_TOL_M inside the body
moves onto its card-centroid line at the nearest point outside the body, a chain without one is unbound (its cards
keep today's rigid weights). Never a refusal.

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
         0.06) as for A; joint 2 (depth 0.05): segment 0.05 .. -0.05 lies wholly inside (|.| <= 0.0781), segment
         0.15 .. 0.05 is outside for y >= 0.08 -> (0, 0.08, 0.06), distance 0.14318 (the end (0, 0.15, 0.06) is
         0.2088 away) -> the same point as joint 1 -> segment 1 collapses -> unbound, reason "collapsed".
      Expected: unbound [1, 3], moved_joints 1 (A's joint 1; an unbound chain moves nothing), per chain ``moved``
      [1], [], [], [].
[2] ``unbind`` on smoke_hair_chains_bind's fixture binding (card a on chain 0, card b rigid): unbind [0] -> every
    vertex chain -1, w 0, alpha 1, kept [], card_counts (0, 2); ``chain_weights`` then returns the stand-in skin
    unchanged.
[3] ``fit_hairdeck`` on smoke_hair_chains_bind's fit fixture (head sphere r 0.1 at (0, 1.6, 0), neck cylinder r
    0.04; hair = cards a and b, proxy -> s 2, t (0, 0.8, 0); placement forward 0.01, tilt 5, width 0.9).
    DEEP chains file: chain 0 = (0, 0.40, -0.03), (0, 0.35, -0.05), (0, 0.30, -0.05), stiffness 0.4 (card a still
    binds: its lower 60 % lies 0.005 from segment 1; the vertex rows the same). Mapped s J + t, then forward
    +0.01 (z) and the tilt about the head centre (distance-preserving): the root -> |z| = 2 * 0.03 - 0.01 = 0.05
    from the head centre -> 0.05 inside the head sphere. ``follow`` moves it by the IDW mean push of card a (the
    card sits on the sphere, moved 1 cm forward into it, pushed back out by ~1.4 cm: |push| < 0.02) -> still
    >= 0.03 > SETTLE_TOL_M deep. Joints 1 and 2 at (0, 1.5 | 1.4, -0.09) lie >= 0.034 outside the head sphere and
    0.05 outside the neck cylinder. Card a has 16 vertices = FOLLOW_K, so every joint's centroid is the centroid
    of card a, at (~0.01, ~1.5, ~-0.1): 0.14 from the head centre, outside -> the root moves there.
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
        check(unbound == [1, 3], f"unbound {unbound} == [1, 3]")
        check(info["moved_joints"] == 1 and [c["moved"] for c in info["chains"]] == [[1], [], [], []],
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
        check(info["chains"][3]["reason"] == "collapsed" and out[3].tobytes() == JD.tobytes(),
              "D unbound (collapsed), joints unchanged")
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
        deep = [{"joints": [[0, 0.40, -0.03], [0, 0.35, -0.05], [0, 0.30, -0.05]], "stiffness": 0.4}]
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
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
