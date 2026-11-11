#!/usr/bin/env python3
"""HairDeck push-out (``garment_hairdeck._push``): no step round the head where the layer push meets the smoothed one.

Usage: ./.venv/bin/python scripts/smoke_hairdeck_ring_step.py

No world, no server, no hub: a throwaway storage dir (``paths.init`` first), every mesh is built in this file.

The defect (Rosi 2026-11-11, ~/claude-out/rosi-hair): ``_push`` blends the layer-keeping push (``layer_push``, w = 1)
with the smoothed ``push_out`` (w = 0) over ``LAYER_BLEND_M`` 3 cm below ``top - SPREAD_DEPTH_M``. The smoothed push
ran WITH its crown spread (each crown vertex takes the largest displacement within SPREAD_M, iterated): the flood
``layer_push`` replaced came back through (1 - w) in the band and, via the mesh smoothing, down the cards below it —
a ring round the head at eye level (Rosi: push p50 32.5 mm at y 1.55 against 4.6 mm at 1.58). Since FIT_VERSION
hair 7 the smoothed push runs without the spread.

Fixture (metres, +y up)
- Body: head = UV sphere radius R = 0.1 centred (0, 1.6, 0), 61 bands x 120 segments; neck = closed cylinder
  radius 0.04 from y 1.30 to 1.55 (inside the sphere at its top). Only ``positions`` / ``faces`` are read.
- Hair: 24 meridians (azimuth every 15 deg), on each FOUR separate cards (no shared vertex) stacked radially at
  r = 0.094, 0.1005, 0.107, 0.1135 from the head centre — layers 6.5 mm apart, inside the spread radius SPREAD_M
  8.5 mm of each other, so the spread chains from the innermost card to the outermost. A card = 2 columns
  (azimuth +-1 deg) x rows at polar angle 4, 6, ..., 120 deg (59 rows): y = 1.6 + r cos(theta).
  Signed distance to the sphere d0 = r - R: -0.006 / 0.0005 / 0.007 / 0.0135.
- Hair top = 1.6 + 0.1135 cos 4 deg = 1.71322 -> blend from lo = 1.71322 - 0.119 = 1.59422 (w 0) to 1.62422 (w 1).
  On the outer card that is theta = acos((1.59422 - 1.6) / 0.1135) = 93.0 deg .. acos(0.02134) = 78.8 deg: the
  cards run 40 deg further down, through the band and below it, as Rosi's curtain does.

[1] The outermost card does not move at ANY height. Its d0 = 0.0135 >= CARD_CLEAR_M + LAYER_BAND_M = 0.010, so
    ``layer_push`` maps it onto itself (target = d0, displacement exactly 0); the smoothed push needs
    max(CARD_CLEAR_M - d, 0) = 0 on all its vertices in every iteration, and its smoothing averages over its own
    card only (a separate piece) -> 0; blend 0, the final clamp adds max(0.004 - 0.0135, 0) = 0. Expected max |disp|
    on the 24 outer cards = 0 (to 1e-9). The neck is >= 0.058 away from every card vertex (horizontal radius of the
    outer card at theta 120 deg is 0.1135 sin 120 = 0.098, the neck's 0.04), so only the sphere is near.
    Before the fix the spread carried the innermost card's push (~1 cm) out to it inside the band.
[2] No step across the band on any card. Step of a card = | |D_i| - |D_(i+1)| | / |P_i - P_(i+1)| between consecutive
    rows (|D| at the card's centre line). The blend itself contributes at most |L - S| / LAYER_BLEND_M, L / S the
    layer / smoothed push magnitude of a layer (both along the outward normal; T = CARD_CLEAR_M + LAYER_BAND_M):
      r 0.094 : L = 0.004 + 0.006 exp((-0.006 - 0.010) / 0.006) + 0.006 = 0.01042, S = 0.004 + 0.006 = 0.010
      r 0.1005: L = 0.004 + 0.006 exp((0.0005 - 0.010) / 0.006) - 0.0005 = 0.00473, S = 0.004 - 0.0005 = 0.0035
      r 0.107 : L = 0.004 + 0.006 exp((0.007 - 0.010) / 0.006) - 0.007 = 0.00064, S = 0 (outside the clearance)
      r 0.1135: L = S = 0
    -> at most 0.0012 / 0.03 = 0.041. On top of that every row carries the layer push's own noise (the voxel SDF:
    0.5 mm of d0 moves L by up to 0.5 mm), which the rows ABOVE the window (w = 1, the layer push alone, the same
    code before and after the fix) measure on this very fixture. So: in the window [lo - STEP_BELOW_M, lo +
    LAYER_BLEND_M + STEP_ABOVE_M] the largest step and the 95th percentile of the steps may exceed those of the rows
    above it (y > lo + LAYER_BLEND_M + STEP_ABOVE_M, below the pole rows y < 1.69 whose normals turn fastest) by at
    most STEP_SLACK 0.05 (> 0.041). Before the fix the outer card climbed from 0 above the band to 7-9 mm in it within
    three rows (~0.6 per row).
[3] Nothing is left inside the clearance: every hair vertex ends >= CARD_CLEAR_M - 0.001 from the sphere (the
    voxel SDF's slack), measured on the true sphere |p - c| - R.
[4] The proof against the old code: the module at commit d47f4d4f (before the fix) is loaded from git and run on
    the same fixture: [1] and [2] must fail there. Skipped (reported) when that module no longer imports against
    today's ``garment_fit``.
"""
import importlib.util
import math
import subprocess
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

OLD_COMMIT = "d47f4d4f"
FAILS = []
R, C = 0.1, np.array([0.0, 1.6, 0.0])
RADII = (0.094, 0.1005, 0.107, 0.1135)
THETAS = np.radians(np.arange(4, 121, 2))
AZIMUTHS = np.radians(np.arange(0, 360, 15))
HALF_DEG = math.radians(1.0)
# Window of [2] round the blend band (Rosi's leak reached 4 cm below it).
STEP_BELOW_M = 0.04
STEP_ABOVE_M = 0.01
STEP_SLACK = 0.05
POLE_ROWS_Y = 1.69


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
    F = [[0, 1 + j, 1 + (j + 1) % segs] for j in range(segs)]
    for i in range(bands - 2):
        a, b = 1 + i * segs, 1 + (i + 1) * segs
        for j in range(segs):
            k = (j + 1) % segs
            F += [[a + j, b + j, b + k], [a + j, b + k, a + k]]
    last, s = len(P) - 1, 1 + (bands - 2) * segs
    F += [[s + j, last, s + (j + 1) % segs] for j in range(segs)]
    return np.array(P) + c, np.array(F)


def cylinder(r, y0, y1, segs):
    P = [[r * math.sin(2 * math.pi * j / segs), y, r * math.cos(2 * math.pi * j / segs)]
         for y in (y0, y1) for j in range(segs)] + [[0.0, y0, 0.0], [0.0, y1, 0.0]]
    F = []
    for j in range(segs):
        k = (j + 1) % segs
        F += [[j, segs + j, segs + k], [j, segs + k, k], [2 * segs, k, j], [2 * segs + 1, segs + j, segs + k]]
    return np.array(P), np.array(F)


def body():
    Ps, Fs = uv_sphere(R, C, 61, 120)
    Pc, Fc = cylinder(0.04, 1.30, 1.55, 48)
    return types.SimpleNamespace(positions=np.vstack([Ps, Pc]), faces=np.vstack([Fs, Fc + len(Ps)]))


def hair():
    """``(P, F, cards)`` — ``cards`` = list of (radius, [row-major vertex indices, 2 per row])."""
    P, F, cards = [], [], []
    for r in RADII:
        for az in AZIMUTHS:
            idx = []
            for th in THETAS:
                for a in (az - HALF_DEG, az + HALF_DEG):
                    idx.append(len(P))
                    P.append(C + r * np.array([math.sin(th) * math.sin(a), math.cos(th), math.sin(th) * math.cos(a)]))
            for i in range(len(THETAS) - 1):
                a0, a1, b0, b1 = idx[2 * i], idx[2 * i + 1], idx[2 * i + 2], idx[2 * i + 3]
                F += [[a0, b0, b1], [a0, b1, a1]]
            cards.append((r, idx))
    return np.array(P), np.array(F, np.int64), cards


def run(gh, label):
    """The push of ``gh`` (a garment_hairdeck module) on the fixture -> ``(outer_max, window, above, min_clear)``;
    ``window`` / ``above`` = (max, p95) of the card steps in / above the window round the blend band."""
    P, F, cards = hair()
    out = gh._push(P, F, np.zeros((len(P), 2)), body())
    X = out["Qp"][out["inv"]]
    D = X - P
    outer = [i for r, idx in cards if r == RADII[-1] for i in idx]
    outer_max = float(np.linalg.norm(D[outer], axis=1).max())
    lo = float(P[:, 1].max()) - 0.119
    hi = lo + gh.LAYER_BLEND_M + STEP_ABOVE_M
    in_win, above = [], []
    for r, idx in cards:
        centre_m = np.linalg.norm((D[idx[0::2]] + D[idx[1::2]]) / 2, axis=1)
        centre_p = (P[idx[0::2]] + P[idx[1::2]]) / 2
        step = np.abs(np.diff(centre_m)) / np.linalg.norm(np.diff(centre_p, axis=0), axis=1)
        mid_y = (centre_p[1:, 1] + centre_p[:-1, 1]) / 2
        in_win += list(step[(mid_y > lo - STEP_BELOW_M) & (mid_y < hi)])
        above += list(step[(mid_y >= hi) & (mid_y < POLE_ROWS_Y)])
    window = (float(max(in_win)), float(np.percentile(in_win, 95)))
    above_s = (float(max(above)), float(np.percentile(above, 95)))
    clear = float((np.linalg.norm(X - C, axis=1) - R).min())
    print(f"  {label}: outer card max |disp| {outer_max * 1000:.3f} mm; steps in the window max/p95 "
          f"{window[0]:.3f}/{window[1]:.3f}, above it {above_s[0]:.3f}/{above_s[1]:.3f}; "
          f"min clearance {clear * 1000:.2f} mm")
    return outer_max, window, above_s, clear


def stepped(window, above) -> bool:
    return window[0] > above[0] + STEP_SLACK or window[1] > above[1] + STEP_SLACK


def load_old(tmp: Path):
    try:
        src = subprocess.run(["git", "-C", str(ROOT), "show", f"{OLD_COMMIT}:app/core/garment_hairdeck.py"],
                             check=True, capture_output=True, text=True).stdout
    except (OSError, subprocess.CalledProcessError) as e:
        return None, f"git show failed: {e}"
    path = tmp / "garment_hairdeck_old.py"
    path.write_text(src)
    spec = importlib.util.spec_from_file_location("garment_hairdeck_old", path)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as e:  # noqa: BLE001 — today's garment_fit may have dropped a name the old module imports
        return None, f"{type(e).__name__}: {e}"
    return mod, None


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="hairdeck-ring-") as tmp:
        from app.core import paths
        paths.init(Path(tmp) / "world")
        from app.core import garment_hairdeck as gh
        lo = 1.6 + RADII[-1] * math.cos(THETAS[0]) - 0.119
        print(f"blend band y {lo:.5f} .. {lo + gh.LAYER_BLEND_M:.5f}")
        outer, window, above, clear = run(gh, "current")
        check(outer <= 1e-9, f"[1] the outermost card (d0 13.5 mm) does not move: {outer * 1000:.4f} mm")
        check(not stepped(window, above), f"[2] no step across the blend band: window max/p95 {window[0]:.3f}/"
                                          f"{window[1]:.3f} <= above-band {above[0]:.3f}/{above[1]:.3f} + {STEP_SLACK}")
        check(clear >= gh.CARD_CLEAR_M - 0.001, f"[3] every vertex >= {gh.CARD_CLEAR_M - 0.001:.3f} m out: "
                                                f"{clear:.4f}")
        old, why = load_old(Path(tmp))
        if old is None:
            print(f"SKIP [4] the old module ({OLD_COMMIT}) does not load today: {why}")
        else:
            o_outer, o_window, o_above, _ = run(old, f"old {OLD_COMMIT}")
            check(o_outer > 1e-9 and stepped(o_window, o_above),
                  f"[4] the old code fails [1] and [2]: outer {o_outer * 1000:.2f} mm, window max/p95 "
                  f"{o_window[0]:.3f}/{o_window[1]:.3f}")
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
