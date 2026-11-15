#!/usr/bin/env python3
"""The HairDeck scalp fill is short hair growing from the scalp, and no card ends bluntly (Ruling A89b, FIT hair 18).

Usage: ./.venv/bin/python scripts/smoke_hairdeck_scalp_hair.py

No world, no server, no hub, no network: a throwaway storage dir (``paths.init`` first), every mesh is built here and
``garment_hairdeck.hair_flow`` / ``root_fade`` / ``scalp_fill_cards(flow=...)`` are called directly. The fails-on-old
proof reads ``app/core/garment_hairdeck.py`` of commit ``32020dc66`` (Ruling A89, FIT hair 17) with ``git show``.

User report 2026-11-15: above the forehead the cap reads as a flat striped band — a dark strip with vertical stripes
between the hairline and where the strands start; card ends show bluntly at the temple and the brow.

Constants (garment_hairdeck): FLOW_SIGMA_M 0.018, FLOW_CROWN_SHARE 0.25, FLOW_BEHIND_M 0.004, ROOT_FADE_M 0.012,
ROOT_FADE_SHARE 0.4, SCALP_ROOT_FADE_M 0.006, TIP_FADE_M 0.003, SCALP_SPACING_M 0.002, SCALP_TIP_SPAN_M (-0.005, 0.005), SCALP_ROOT_WIDTH 0.4, FILL_WIDTH_M 0.012,
SCALP_WIDTH_EDGE_M 0.006, FILL_OFFSET_M 0.0025, SCALP_LAYER_M 0.0008, SCALP_ROOT_LIFT_M 0.002, CAP_TUCK_M 0.003.

[1] ``hair_flow`` by hand: triangle (0,0,0) / (0.01,0,0) / (0,0.01,0) with v 1 / 1 / 0 -> v = 1 - y / 0.01, grad v
    = (0, -100, 0): root -> tip = (0, 1, 0) (+- 1e-12), weight = its area 0.5 * 0.01^2 = 5e-5, centroid
    (0.00333, 0.00333, 0). A triangle with v 0.5 on all three has no gradient: left out (one sample in all).
[2] ``root_fade`` by hand on two straight cards running down y: card 0 rows v 1, 0.75, 0.5, 0.25, 0 every 2.5 mm
    (length 0.010): L = min(0.012, 0.4 * 0.010) = 0.004 -> s 0: 0; s 0.0025: smoothstep(0.625) = 0.625^2 * (3 - 1.25)
    = 0.68359375; s 0.005 and on: 1. Card 1 rows every 3 mm over 0.099 m (L = min(0.012, 0.0396) = 0.012): s 0.003 ->
    smoothstep(0.25) = 0.0625 * 2.5 = 0.15625, s 0.006 -> smoothstep(0.5) = 0.5, s 0.012 -> 1. A vertex of card -1 (the cap): 1. Rows are found by v whatever the vertex order (card 1 reversed).
    (each +- 1e-12)
[3] ``scalp_fill_cards(flow=...)`` on a sphere head (radius 0.1 at (0, 1.6, 0), 61 bands x 120 segments): the cap =
    the faces with centroid z > 0.06, |x| < 0.045 and y > 1.643 (the cap's edge, floor 1.64 + CAP_TUCK_M), every cap
    point open (the only hair point sits behind the head at (0, 1.6, -0.2)).
    a) Flow sideways: samples on the sphere's front (radius 0.106, every 4 mm, x and y within +-0.06 of the front's
       (0, 1.66)), each the tangent of +x there, weight 1. At the front the tangent of +x is +x and the samples agree
       (coherence ~1), so a card's direction is normalize(+x + 0.25 * away-from-crown) — atan(0.25) = 14 deg below
       horizontal, x share cos 14 deg = 0.970: the median x share of the cards' first segment >= 0.9 (cards bend a
       little with the field); fewer than 10 % run more down than sideways.
    b) No flow samples (empty arrays): only the crown term. The crown point (0, 1.7, 0) is the sphere's top, so the
       away-from-crown tangent is the meridian: every first segment runs down its meridian — the dot of its
       direction with the analytic down-meridian at the root (-cos(lat) * (sin az, 0, cos az) ... normalised
       (p - crown) projected on the tangent plane) median >= 0.99, every one going down (dy < 0).
    c) Card ends (both runs): the root row's width = SCALP_ROOT_WIDTH 0.4 of the card's width, which lies in
       [0.006, 0.012] -> <= 0.0048 + 1e-6; the report's ``alpha`` (popped by the fit) is 0 on every card's root row
       and on its tip row (the vertex alpha fades both ends: SCALP_ROOT_FADE_M, TIP_FADE_M), max >= 0.5 on every
       card; v 1 on the root row, 0 on the tip row. The GPU interpolates the vertex alpha linearly between rows, so
       the root fade carries rows of its own at SCALP_ROOT_INSERT (0.25, 0.6) of SCALP_ROOT_FADE_M 0.006 = 1.5 mm and
       3.6 mm (when the first designed row lies past them): the row at 1.5 mm has smoothstep(0.25) = 0.15625, so the
       interpolated alpha 1 mm from the root is 0.15625 * 1 / 1.5 = 0.1042 (+- 0.01: a cut tip fade may lower it)
       — under the default cutoff 0.15 for every card at least 1.5 mm long, whatever the atlas; without the rows
       (row 1 at 5 mm, alpha smoothstep(5/6) = 0.926) it would be 0.185. Root rows lie FILL_OFFSET_M + layer [0, 0.0008] + lift [0, 0.002] over the sphere: [0.0025, 0.0053]
       (+- 1e-5); the lift falls linearly to 0 at the card's last DESIGNED row, so along a card the offset never rises
       (+- 2e-4: a cut tip row is interpolated on a chord), and a card that runs its whole length ends at
       [0.0025, 0.0033]: every tip row lies in [0.0025, 0.0053] (+- 2e-4), at least half of them in [0.0025, 0.0033].
    d) The hairline (run b, cards going straight down): a card running down stops at its own height over the edge,
       -0.005 + 0.01 * frac(k * 0.5698...) (k its seed number): every tip row at or above the edge - 0.005 - 1e-4,
       and some (>= 5) under the edge. Coverage thins towards the edge: a card crossing +7 mm on its way down goes
       on past +1 mm only when its stop lies under +1 mm, P(frac < 0.6) = 0.6 (fewer when its length ends first):
       the cards crossing +1 mm are at most 0.6 + 0.1 (the sequence over ~100 cards) of those crossing +7 mm.
    32020dc66 (hair 17, no ``flow``): the fill has no notion of the strands — every card runs away from the crown: of
    its cards rooted within |x| < 0.015 (x share there under sin(asin(0.015 / 0.09)) = 0.17) the median |x share| is
    <= 0.17 where a) needs >= 0.9 -> FAILS a); its root rows are the full FILL_WIDTH_M (0.012) -> FAILS "root rows
    <= 0.0048"; it has no root fade (no ``root_fade``) -> FAILS [2].
[4] Without ``flow`` the fill is hair 17's bit for bit (positions, faces, UVs, normals, cards of the old module).
[5] FIT_VERSION hair 18 (every HairDeck fit due: a CPU refit, no hub job).
"""
import importlib.util
import math
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

BEFORE_A89B = "32020dc66"
FAILS = []


def check(cond, label):
    print(("OK   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


def uv_sphere(r, c, bands, segs):
    P = [[0.0, r, 0.0]]
    for i in range(1, bands):
        th = math.pi * i / bands
        for j in range(segs):
            ph = 2 * math.pi * j / segs
            P.append([r * math.sin(th) * math.sin(ph), r * math.cos(th), r * math.sin(th) * math.cos(ph)])
    P.append([0.0, -r, 0.0])
    F = []
    for j in range(segs):
        F.append([0, 1 + j, 1 + (j + 1) % segs])
    for i in range(bands - 2):
        a, b = 1 + i * segs, 1 + (i + 1) * segs
        for j in range(segs):
            k = (j + 1) % segs
            F += [[a + j, b + j, b + k], [a + j, b + k, a + k]]
    last, s = len(P) - 1, 1 + (bands - 2) * segs
    for j in range(segs):
        F.append([s + j, last, s + (j + 1) % segs])
    return np.array(P) + np.asarray(c, float), np.array(F)


class SphereSDF:
    def __init__(self, c, r):
        self.c, self.r = np.asarray(c, float), float(r)

    def sample(self, X):
        return np.linalg.norm(np.asarray(X, float).reshape(-1, 3) - self.c, axis=1) - self.r

    def grad(self, X):
        v = np.asarray(X, float).reshape(-1, 3) - self.c
        return v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-12)


def old_module(tmp, commit):
    src = subprocess.run(["git", "-C", str(ROOT), "show", f"{commit}:app/core/garment_hairdeck.py"],
                         check=True, capture_output=True, text=True).stdout
    name = f"garment_hairdeck_{commit}"
    path = Path(tmp) / f"{name}.py"
    path.write_text(src)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def cards_of(V, card):
    """Per card its row centres (rows are emitted as (left, right) pairs, root row first) and row widths."""
    out = []
    for k in np.unique(card):
        idx = np.flatnonzero(card == k)
        L, R = V[idx[0::2]], V[idx[1::2]]
        out.append((idx, (L + R) / 2, np.linalg.norm(R - L, axis=1)))
    return out


def first_x_share(cards):
    share = []
    for _, C, _ in cards:
        d = C[1] - C[0]
        share.append(d[0] / max(np.linalg.norm(d), 1e-12))
    return np.array(share)


def main():
    tmp = tempfile.mkdtemp(prefix="smoke_hairdeck_scalp_hair_")
    from app.core import paths
    paths.init(tmp)
    from app.core import garment_hairdeck as gh
    from app.core.garment_fit import FIT_VERSION
    old = old_module(tmp, BEFORE_A89B)

    print("[1] hair_flow by hand")
    X = np.array([[0, 0, 0], [0.01, 0, 0], [0, 0.01, 0], [0.02, 0, 0], [0.03, 0, 0], [0.02, 0.01, 0]], float)
    F = np.array([[0, 1, 2], [3, 4, 5]])
    U = np.array([[0, 1], [1, 1], [0, 0], [0, 0.5], [1, 0.5], [0, 0.5]], float)
    c, d, w = gh.hair_flow(X, F, U)
    check(len(c) == 1, f"[1] one sample (the constant-v face left out): {len(c)}")
    check(len(c) == 1 and np.abs(d[0] - [0, 1, 0]).max() < 1e-12, f"[1] root -> tip (0, 1, 0): {d.round(12).tolist()}")
    check(len(c) == 1 and abs(w[0] - 5e-5) < 1e-12 and np.abs(c[0] - [0.01 / 3, 0.01 / 3, 0]).max() < 1e-12,
          f"[1] weight 5e-5, centroid (0.00333, 0.00333, 0): {w.tolist()} {c.round(6).tolist()}")

    print("[2] root_fade by hand")
    rows0 = [(v, -0.0025 * i) for i, v in enumerate((1.0, 0.75, 0.5, 0.25, 0.0))]
    rows1 = [(1.0 - i / 33.0, -0.003 * i) for i in range(34)]
    P, Uv, card = [], [], []
    for k, rows in ((0, rows0), (1, rows1[::-1])):
        for v, y in rows:
            for x in (0.0, 0.004):
                P.append([x + 0.1 * k, y, 0.0])
                Uv.append([x / 0.004, v])
                card.append(k)
    P.append([0, 0, 0.1])
    Uv.append([0.5, 0.5])
    card.append(-1)
    P, Uv, card = np.array(P), np.array(Uv), np.array(card)
    if hasattr(gh, "root_fade"):
        a = gh.root_fade(P, Uv, card)
        want0 = {1.0: 0.0, 0.75: 0.68359375, 0.5: 1.0, 0.25: 1.0, 0.0: 1.0}
        got0 = {v: float(a[(card == 0) & (np.abs(Uv[:, 1] - v) < 1e-9)][0]) for v in want0}
        check(all(abs(got0[v] - want0[v]) < 1e-12 for v in want0), f"[2] card 0: {got0}")
        v1 = {1.0: 0.0, 1.0 - 1 / 33.0: 0.15625, 1.0 - 2 / 33.0: 0.5, 1.0 - 4 / 33.0: 1.0}
        got1 = {round(v, 6): float(a[(card == 1) & (np.abs(Uv[:, 1] - v) < 1e-9)][0]) for v in v1}
        check(all(abs(got1[round(v, 6)] - v1[v]) < 1e-12 for v in v1), f"[2] card 1 (reversed order): {got1}")
        check(a[-1] == 1.0, "[2] the cap vertex keeps alpha 1")
    else:
        check(False, "[2] root_fade exists")
    check(not hasattr(old, "root_fade"), f"[2] {BEFORE_A89B} has no root fade (the old cards start bluntly)")

    print("[3] scalp hair on a sphere head")
    Ps, Fs = uv_sphere(0.1, (0, 1.6, 0), 61, 120)
    cen = Ps[Fs].mean(1)
    Fc = Fs[(cen[:, 2] > 0.06) & (np.abs(cen[:, 0]) < 0.045) & (cen[:, 1] > 1.643)]
    sdf = SphereSDF((0, 1.6, 0), 0.1)
    crown = np.array([0, 1.7, 0])
    hair = np.array([[0, 1.6, -0.2]])
    floor = gh.cap_floor(1.64, None, (0.0, 0.0))
    fc, fd = [], []
    for x in np.arange(-0.06, 0.0601, 0.004):
        for y in np.arange(1.60, 1.7201, 0.004):
            z2 = 0.106 ** 2 - x * x - (y - 1.6) ** 2
            if z2 <= 0:
                continue
            p = np.array([x, y, math.sqrt(z2)])
            n = (p - [0, 1.6, 0]) / 0.106
            t = np.array([1.0, 0, 0]) - n[0] * n
            fc.append(p)
            fd.append(t / np.linalg.norm(t))
    side = (np.array(fc), np.array(fd), np.ones(len(fc)))
    none = (np.zeros((0, 3)), np.zeros((0, 3)), np.zeros(0))
    Va, Fa, Ua, Na, ca, ra = gh.scalp_fill_cards(Ps, Fc, hair, sdf, crown, floor, flow=side)
    Vb, Fb, Ub, Nb, cb, rb = gh.scalp_fill_cards(Ps, Fc, hair, sdf, crown, floor, flow=none)
    A, B = cards_of(Va, ca), cards_of(Vb, cb)
    print(f"       a) {len(A)} cards, b) {len(B)} cards; report b", {k: v for k, v in rb.items() if k != "alpha"})
    xa = first_x_share(A)
    check(len(A) > 50 and float(np.median(xa)) >= 0.9, f"[3a] flow sideways: median x share {np.median(xa):.3f} >= 0.9")
    downish = np.array([C[1][1] - C[0][1] < -abs(C[1][0] - C[0][0]) for _, C, _ in A])
    check(float(downish.mean()) < 0.1, f"[3a] fewer than 10 % run more down than sideways: {downish.mean():.3f}")
    dots = []
    for _, C, _ in B:
        p = C[0]
        n = (p - [0, 1.6, 0]) / np.linalg.norm(p - [0, 1.6, 0])
        t = (p - crown) - ((p - crown) @ n) * n
        d = C[1] - C[0]
        dots.append(float(d @ t / np.linalg.norm(d) / np.linalg.norm(t)))
    check(len(B) > 50 and float(np.median(dots)) >= 0.99, f"[3b] no flow: down the meridian, median dot {np.median(dots):.4f}")
    check(all(C[1][1] < C[0][1] for _, C, _ in B), "[3b] every first segment goes down")
    for tag, cards, V, Uf, rep in (("a", A, Va, Ua, ra), ("b", B, Vb, Ub, rb)):
        alpha = np.asarray(rep.get("alpha", np.ones(len(V))))
        root_w = max(W[0] for _, _, W in cards)
        check(root_w <= 0.0048 + 1e-6, f"[3c-{tag}] root rows <= 0.4 * 0.012 = 0.0048 wide: widest {root_w:.5f}")
        ends0 = all(alpha[idx[0]] == 0 and alpha[idx[1]] == 0 and alpha[idx[-1]] == 0 and alpha[idx[-2]] == 0
                    for idx, _, _ in cards)
        check(ends0, f"[3c-{tag}] alpha 0 on every root row and tip row")
        check(all(alpha[idx].max() >= 0.5 for idx, _, _ in cards), f"[3c-{tag}] every card shows (max alpha >= 0.5)")
        a1 = []
        for idx, C, _ in cards:
            run = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(C, axis=0), axis=1))]
            if run[-1] >= 0.0015:
                a1.append(float(np.interp(0.001, run, alpha[idx[0::2]])))
        check(len(a1) > 20 and max(a1) <= 0.1042 + 0.01,
              f"[3c-{tag}] interpolated alpha 1 mm from the root <= 0.1042: max {max(a1):.4f} over {len(a1)} cards")
        check(all(abs(Uf[idx[0], 1] - 1) < 1e-12 and abs(Uf[idx[-1], 1]) < 1e-12 for idx, _, _ in cards),
              f"[3c-{tag}] v 1 on the root row, 0 on the tip row")
        r_off = np.array([sdf.sample(C[:1])[0] for _, C, _ in cards])
        t_off = np.array([sdf.sample(C[-1:])[0] for _, C, _ in cards])
        check(r_off.min() >= 0.0025 - 1e-5 and r_off.max() <= 0.0053 + 1e-5,
              f"[3c-{tag}] root rows {r_off.min():.5f}..{r_off.max():.5f} over the head in [0.0025, 0.0053]")
        check(t_off.min() >= 0.0025 - 2e-4 and t_off.max() <= 0.0053 + 2e-4
              and float((t_off <= 0.0033 + 2e-4).mean()) >= 0.5,
              f"[3c-{tag}] tip rows {t_off.min():.5f}..{t_off.max():.5f}, "
              f"{(t_off <= 0.0033 + 2e-4).mean():.2f} of them in [0.0025, 0.0033]")
        rises = max(float(np.diff(sdf.sample(C)).max()) if len(C) > 1 else 0.0 for _, C, _ in cards)
        check(rises <= 2e-4, f"[3c-{tag}] the offset never rises along a card (largest step up {rises * 1000:.3f} mm)")
    edge = 1.643
    tips = np.array([C[-1][1] - edge for _, C, _ in B])
    roots = np.array([C[0][1] - edge for _, C, _ in B])
    check(tips.min() >= -0.005 - 1e-4, f"[3d] every tip at or above the edge - 5 mm: lowest {tips.min() * 1000:+.2f} mm")
    check(int((tips < 0).sum()) >= 5, f"[3d] some tips under the edge: {int((tips < 0).sum())}")
    cross7 = int(((roots > 0.007) & (tips < 0.007)).sum())
    cross1 = int(((roots > 0.001) & (tips < 0.001)).sum())
    check(cross7 >= 30 and cross1 <= 0.7 * cross7,
          f"[3d] cards crossing +1 mm {cross1} <= 0.7 * those crossing +7 mm {cross7} ({cross1 / max(cross7, 1):.2f})")
    print(f"[3] {BEFORE_A89B} (hair 17)")
    Vo, Fo, Uo, No, co, ro = old.scalp_fill_cards(Ps, Fc, hair, sdf, crown, floor)
    O = cards_of(Vo, co)
    mid = [k for k, (_, C, _) in enumerate(O) if abs(C[0][0]) < 0.015]
    xo = np.abs(first_x_share(O))[mid]
    wo = max(W[0] for _, _, W in O) if O else 0.0
    print(f"       old: {len(O)} cards, {len(mid)} in the middle, median |x share| {np.median(xo):.3f}, widest root row {wo:.5f}")
    check(len(mid) > 10 and float(np.median(xo)) <= 0.17 and wo > 0.0048 + 1e-6,
          f"[3] {BEFORE_A89B} runs its fill away from the crown whatever the strands do, its roots full width "
          "(fails [3a] and [3c])")
    mid_a = [k for k, (_, C, _) in enumerate(A) if abs(C[0][0]) < 0.015]
    check(float(np.median(xa[mid_a])) >= 0.9, f"[3a] the same middle cards now: median x share {np.median(xa[mid_a]):.3f}")
    print("[4] without flow: hair 17's fill bit for bit")
    front = (0.05, gh.CAP_TUCK_M + gh.FILL_EDGE_BAND_M)
    new = gh.scalp_fill_cards(Ps, Fc, hair, sdf, crown, floor, front=front, land_jitter=gh.FILL_LAND_JITTER_M)
    ref = old.scalp_fill_cards(Ps, Fc, hair, sdf, crown, floor, front=front, land_jitter=old.FILL_LAND_JITTER_M)
    check(all(np.array_equal(a, b) for a, b in zip(new[:5], ref[:5])) and new[5] == ref[5],
          f"[4] equal to {BEFORE_A89B} ({ref[5]})")

    print("[5] fit version")
    check(FIT_VERSION["hair"] == 18, f"[5] FIT_VERSION hair {FIT_VERSION['hair']} == 18")
    check(gh.SCALP_HAIR_ON is True, "[5] SCALP_HAIR_ON")

    print()
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
