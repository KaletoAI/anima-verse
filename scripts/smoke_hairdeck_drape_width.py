#!/usr/bin/env python3
"""HairDeck fit (``app/core/garment_hairdeck.py``): the back curtain draped behind the nape instead of wrapped round
the neck (``drape_back``), and the per-character hair width (``narrow_sides``, profile ``hair_width_scale``).

Usage: ./.venv/bin/python scripts/smoke_hairdeck_drape_width.py

No world, no server, no hub: a throwaway storage dir (``paths.init`` first), every mesh is built in this file.

The defect (Rosi 2026-11-12, ~/claude-out/rosi-hair2): HairDeck's inner back cards hang straight down from the
occiput, through where the neck is (a head proxy has no neck). The push moved each vertex to its NEAREST surface;
for a vertex on a sheet through the middle of the neck that is the neck's side — the curtain wrapped round the neck
as a collar ("Kranz"). Since FIT_VERSION hair 8 the back cards are draped backward first.

Fixture (metres, +y up, +z front), a skinned stand-in body (``positions``, ``faces``, ``joints``, ``weights``,
``joint_names`` — what ``dense_weights`` / ``ear_line_height`` read):
- Head: UV sphere R 0.1 at (0, 1.6, 0), 61 bands x 120 segments, all Head-weighted -> chin 1.5, crown 1.7, ear line
  1.5 + 0.25 * 0.2 = 1.55 (``HAIR_EAR_LINE_FRACTION``), head box symmetric about z = 0 -> mid plane z 0.
- Neck: closed cylinder radius 0.05 about the y axis from 1.30 to 1.55, 48 segments x 51 rings (5 mm), Neck-weighted.
- Back curtain: 8 cards at x_c = +-0.01, +-0.02, +-0.03, +-0.04, each two columns x_c +- 0.002 at z = -0.002 (behind
  the mid plane -> back cards), rows y = 1.25 + 0.005 k, k = 0..46 (up to 1.48: below the ear line, inside the neck
  from 1.30 up, outside it below). A front card at x = 0, z = +0.03 (root in front of the mid plane).

[1] ``drape_back`` need of a curtain vertex (x, y, -0.002) in the neck band 1.32 .. 1.46 (away from the caps): the
    smallest backward step s with sqrt(x^2 + (0.002 + s)^2) >= 0.05 + CARD_CLEAR_M 0.004 = 0.054, i.e.
    s_exact(x) = sqrt(0.054^2 - x^2) - 0.002, rounded UP to a DRAPE_STEP_M multiple. Along a card every row needs
    the same, and the carry gives each vertex the largest need at or above it — the card's INNER column |x_c| -
    0.002: x_c 0.01 -> s_exact(0.008) = 0.051404 (-> 0.052), 0.02 -> s_exact(0.018) = 0.048912 (-> 0.050),
    0.03 -> s_exact(0.028) = 0.044174 (-> 0.046), 0.04 -> s_exact(0.038) = 0.036368 (-> 0.038). Expected shift
    of every band vertex in [s - 0.0012, s + DRAPE_STEP_M + 0.0012] of its card's s (1.2 mm: the voxel SDF's slack
    at 3.4 mm voxels). A curtain row below the neck (y < 1.30, outside the body) needs
    nothing but takes its card's shift (carried down the strand): equal to the band rows' max to 1e-9.
    The front card: shift 0.
[2] Ramp: ``drape_back`` with below_y 1.4025 (rows up to 1.40 count): the highest needing row 1.40 sets the card's
    shift S; row 1.415 lies 0.015 = DRAPE_RAMP_M / 2 above it -> 0.5 S (+-1e-9), row 1.43 (0.03 above) -> 0.
[3] The whole ``_push`` (drape, then the push): every curtain vertex of the band ends BEHIND the neck — its angle
    round the neck axis atan2(|x|, -z) at most the angle of the backward exit atan2(|x|, sqrt(0.054^2 - x^2))
    (x 0.008: 8.5 deg .. x 0.042: 51.0 deg) + 1.5 deg; and >= CARD_CLEAR_M - 0.0012 off the neck.
[4] The old code (commit 0a6a2f2a, before the drape) on the same fixture pushes every band vertex sideways:
    radially from the axis, the angle stays atan2(|x|, 0.002) >= atan2(0.008, 0.002) = 76.0 deg -> [3] fails:
    the median angle there >= 70 deg. Skipped (reported) when that module no longer imports today.
[5] ``narrow_sides`` with a flat head half width h = 0.08 (profile ys (1.0, 2.0), hs (0.08, 0.08)), mid plane 0:
    x 0.12 at width 0.5 -> 0.08 + 0.04 * 0.5 = 0.10; x -0.12 -> -0.10; x 0.05 (inside h) -> 0.05; x 0.09 -> 0.085;
    y and z unchanged; width 1 -> identical; width 1.5: x 0.12 -> 0.08 + 0.06 = 0.14. Order kept (monotone).
[6] Bounds: ``fit_hairdeck`` refuses width_scale 0.49 / 1.51 / nan before reading any file (ValueError naming
    width_scale); ``garment_hair.hair_placement`` carries ``width_scale`` only when set (a profile without
    ``hair_width_scale`` -> keys {forward_m, tilt_deg}: the fit fingerprint of an unset width stays as it was),
    "0.8" -> 0.8, 2.0 (out of 0.5..1.5) -> treated as unset.
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

OLD_COMMIT = "0a6a2f2a"
FAILS = []
R, C = 0.1, np.array([0.0, 1.6, 0.0])
NECK_R = 0.05
CLEAR_R = NECK_R + 0.004
SHEET_Z = -0.002
CARDS_X = (-0.04, -0.03, -0.02, -0.01, 0.01, 0.02, 0.03, 0.04)
ROWS_Y = 1.25 + 0.005 * np.arange(47)
BAND = (1.32, 1.46)
SDF_SLACK = 0.0012


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


def cylinder(r, y0, y1, segs, rings, cap_rings=10):
    """Closed cylinder: ``rings`` rings on the side and ``cap_rings`` concentric rings per cap — every triangle
    short, since the SDF voxelises 5 x 5 samples per triangle (a long fan triangle leaves holes in the solid)."""
    P, F = [], []

    def ring(rr, y):
        start = len(P)
        P.extend([rr * math.sin(2 * math.pi * j / segs), y, rr * math.cos(2 * math.pi * j / segs)] for j in range(segs))
        return start

    def strip(a, b, flip):
        for j in range(segs):
            k = (j + 1) % segs
            F.extend([[a + j, b + k, b + j], [a + j, a + k, b + k]] if flip else
                     [[a + j, b + j, b + k], [a + j, b + k, a + k]])

    side = [ring(r, y) for y in np.linspace(y0, y1, rings)]
    for a, b in zip(side, side[1:]):
        strip(a, b, False)
    for y, edge, flip in ((y0, side[0], True), (y1, side[-1], False)):
        prev = edge
        for rr in np.linspace(r, 0, cap_rings + 1)[1:-1]:
            cur = ring(rr, y)
            strip(prev, cur, flip)
            prev = cur
        centre = len(P)
        P.append([0.0, y, 0.0])
        for j in range(segs):
            k = (j + 1) % segs
            F.append([centre, prev + k, prev + j] if flip else [centre, prev + j, prev + k])
    return np.array(P), np.array(F)


def body():
    Ps, Fs = uv_sphere(R, C, 61, 120)
    Pc, Fc = cylinder(NECK_R, 1.30, 1.55, 48, 51)
    n_s, n_c = len(Ps), len(Pc)
    joints = np.zeros((n_s + n_c, 4), np.int64)
    joints[n_s:, 0] = 1
    weights = np.zeros((n_s + n_c, 4))
    weights[:, 0] = 1.0
    return types.SimpleNamespace(positions=np.vstack([Ps, Pc]), faces=np.vstack([Fs, Fc + n_s]), joints=joints,
                                 weights=weights, joint_names=["mixamorig:Head", "mixamorig:Neck"])


def hair():
    """``(P, F, curtain vertex ids, front vertex ids)``: one card per x (two columns), plus the front card."""
    P, F, curtain, front = [], [], [], []

    def card(xc, z, out):
        idx = []
        for y in ROWS_Y:
            for x in (xc - 0.002, xc + 0.002):
                idx.append(len(P))
                P.append([x, y, z])
        for i in range(len(ROWS_Y) - 1):
            a0, a1, b0, b1 = idx[2 * i], idx[2 * i + 1], idx[2 * i + 2], idx[2 * i + 3]
            F.extend([[a0, b0, b1], [a0, b1, a1]])
        out.extend(idx)

    for xc in CARDS_X:
        card(xc, SHEET_Z, curtain)
    card(0.0, 0.03, front)
    return np.array(P, np.float64), np.array(F, np.int64), np.array(curtain), np.array(front)


def s_exact(x):
    return math.sqrt(CLEAR_R ** 2 - x * x) + SHEET_Z


def angles(X):
    return np.degrees(np.arctan2(np.abs(X[:, 0]), -X[:, 2]))


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


def band_of(P, ids):
    return ids[(P[ids, 1] > BAND[0]) & (P[ids, 1] < BAND[1])]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="hairdeck-drape-") as tmp:
        from app.core import paths
        paths.init(Path(tmp) / "world")
        from app.core import garment_hairdeck as gh
        from app.core import garment_hair
        from app.core.garment_fit import body_sdf, ear_line_height, weld, VOX_M, SDF_MARGIN_M

        B = body()
        P, F, curtain, front = hair()
        frame = gh._drape_frame(B)
        check(abs(frame[0] - 1.55) < 1e-9 and abs(frame[1]) < 1e-9,
              f"fixture: ear line {frame[0]:.5f} (1.55), head mid plane z {frame[1]:.2e} (0)")
        check(abs(ear_line_height(B) - 1.55) < 1e-9, "fixture: ear_line_height 1.55")
        Pw, Fw, inv = weld(P, F, None)
        check(len(Pw) == len(P), f"the cards share no vertex: welded {len(Pw)} of {len(P)}")
        lo = Pw.min(0) - SDF_MARGIN_M
        lo[2] -= gh.DRAPE_MAX_M  # as ``_push`` crops it
        sdf = body_sdf(B.positions, B.faces, vox=VOX_M, bounds=(lo, Pw.max(0) + SDF_MARGIN_M))

        # [1] the drape per vertex
        # (welded order differs from P's: every per-vertex result is read back through ``inv``)
        disp, info = gh.drape_back(Pw, Fw, sdf, below_y=frame[0], back_z=frame[1])
        shift = -disp[inv, 2]
        check(not np.abs(disp[:, :2]).any(), "[1] the drape moves along z only")
        band = band_of(P, curtain)
        # a card takes its largest need (carried down): the inner column, |x_c| - 0.002
        card_x = np.repeat(np.array(CARDS_X), 2 * len(ROWS_Y))
        inner = {c: s_exact(abs(c) - 0.002) for c in CARDS_X}
        exact = np.array([inner[c] for c in card_x[np.searchsorted(curtain, band)]])
        dev = shift[band] - exact
        check(dev.min() >= -SDF_SLACK and dev.max() <= gh.DRAPE_STEP_M + SDF_SLACK,
              f"[1] band shift - s_exact in [{-SDF_SLACK}, {gh.DRAPE_STEP_M + SDF_SLACK}]: "
              f"{dev.min() * 1000:.2f} .. {dev.max() * 1000:.2f} mm (n {len(band)}; info {info})")
        for xc in (0.01, 0.02, 0.03, 0.04):
            col = band[np.abs(P[band, 0] - xc) < 0.0025]
            print(f"       card x {xc:.3f}: shift {shift[col].min() * 1000:.1f} .. {shift[col].max() * 1000:.1f} mm, "
                  f"inner column exact {inner[xc] * 1000:.2f} mm")
        carried = True
        for k in range(len(CARDS_X)):
            ids = curtain[k * 2 * len(ROWS_Y):(k + 1) * 2 * len(ROWS_Y)]
            below = ids[P[ids, 1] < 1.30 - 1e-6]
            carried &= bool(np.abs(shift[below] - shift[band_of(P, ids)].max()).max() <= 1e-9)
        check(carried, "[1] rows below the neck take their card's shift (carried down the strand)")
        check(np.abs(shift[front]).max() == 0.0, f"[1] the front card is not draped: {np.abs(shift[front]).max()}")

        # [2] the ramp above the highest needing row
        disp2, _ = gh.drape_back(Pw, Fw, sdf, below_y=1.4025, back_z=frame[1])
        s2 = -disp2[inv, 2]
        ok_ramp = True
        for k in range(len(CARDS_X)):
            ids = curtain[k * 2 * len(ROWS_Y):(k + 1) * 2 * len(ROWS_Y)]
            for sub in (ids[0::2], ids[1::2]):
                y = P[sub, 1]
                S = s2[sub][np.argmin(np.abs(y - 1.40))]
                ok_ramp &= abs(s2[sub][np.argmin(np.abs(y - 1.415))] - 0.5 * S) <= 1e-9
                ok_ramp &= s2[sub][np.argmin(np.abs(y - 1.43))] == 0.0
                ok_ramp &= S > 0.03
        check(ok_ramp, "[2] 0.015 above the highest needing row: half its shift; 0.03 above: none")

        # [3] the whole push
        def run(module, label):
            out = module._push(P, F, None, B)
            X = out["Qp"][out["inv"]]
            ids = band_of(P, curtain)
            ang = angles(X[ids])
            exit_ang = np.degrees(np.arctan2(np.abs(P[ids, 0]), np.sqrt(CLEAR_R ** 2 - P[ids, 0] ** 2)))
            clear = np.hypot(X[ids, 0], X[ids, 2]) - NECK_R
            print(f"  {label}: band angle round the neck p50 {np.median(ang):.1f} max {ang.max():.1f} deg "
                  f"(backward exit max {exit_ang.max():.1f}); min clearance {clear.min() * 1000:.2f} mm")
            return ang, exit_ang, clear

        ang, exit_ang, clear = run(gh, "current")
        check(bool((ang <= exit_ang + 1.5).all()), f"[3] every band vertex ends behind the neck: angle - exit max "
                                                   f"{(ang - exit_ang).max():.2f} deg <= 1.5")
        check(clear.min() >= 0.004 - SDF_SLACK, f"[3] clearance >= {0.004 - SDF_SLACK}: {clear.min():.4f}")

        # [4] the old code wraps the curtain round the neck
        old, why = load_old(Path(tmp))
        if old is None:
            print(f"SKIP [4] the old module ({OLD_COMMIT}) does not load today: {why}")
        else:
            o_ang, o_exit, _ = run(old, f"old {OLD_COMMIT}")
            check(float(np.median(o_ang)) >= 70.0 and not bool((o_ang <= o_exit + 1.5).all()),
                  f"[4] the old code fails [3]: band angle p50 {np.median(o_ang):.1f} deg (sideways, the collar)")

        # [5] narrow_sides
        prof = (np.array([1.0, 2.0]), np.array([0.08, 0.08]))
        Q = np.array([[0.12, 1.5, 0.01], [-0.12, 1.5, -0.02], [0.05, 1.5, 0.0], [0.09, 1.5, 0.0], [0.10, 1.5, 0.0]])
        N = gh.narrow_sides(Q, prof, 0.0, 0.5)
        check(np.allclose(N[:, 0], [0.10, -0.10, 0.05, 0.085, 0.09], atol=1e-12) and np.array_equal(N[:, 1:], Q[:, 1:]),
              f"[5] width 0.5: x {N[:, 0].round(5).tolist()} (0.10, -0.10, 0.05, 0.085, 0.09), y/z kept")
        check(np.array_equal(gh.narrow_sides(Q, prof, 0.0, 1.0), Q), "[5] width 1: identical")
        W = gh.narrow_sides(Q, prof, 0.0, 1.5)
        check(abs(W[0, 0] - 0.14) < 1e-12 and W[2, 0] == 0.05, f"[5] width 1.5: x 0.12 -> {W[0, 0]:.5f} (0.14)")
        xs = np.linspace(-0.2, 0.2, 81)
        Qs = np.column_stack([xs, np.full_like(xs, 1.5), np.zeros_like(xs)])
        check(bool((np.diff(gh.narrow_sides(Qs, prof, 0.0, 0.6)[:, 0]) > 0).all()), "[5] monotone: order kept")

        # [6] bounds and the fingerprint-neutral unset width
        for bad in (0.49, 1.51, float("nan")):
            try:
                gh.fit_hairdeck(b"", b"", b"", colour_target=None, width_scale=bad)
                check(False, f"[6] width_scale {bad} refused")
            except ValueError as e:
                check("width_scale" in str(e), f"[6] width_scale {bad} refused: {e}")
        check(set(garment_hair.hair_placement({})) == {"forward_m", "tilt_deg"},
              f"[6] unset width not in the placement: {garment_hair.hair_placement({})}")
        check(garment_hair.hair_placement({"hair_width_scale": "0.8"}).get("width_scale") == 0.8,
              "[6] hair_width_scale '0.8' -> 0.8")
        check("width_scale" not in garment_hair.hair_placement({"hair_width_scale": 2.0}),
              "[6] hair_width_scale 2.0 (beyond 1.5) counts as unset")
        try:
            garment_hair._placement_value("width_scale", 0.3)
            check(False, "[6] _placement_value refuses 0.3")
        except ValueError as e:
            check("0.5..1.5" in str(e), f"[6] _placement_value refuses 0.3: {e}")
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
