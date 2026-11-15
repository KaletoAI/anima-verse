#!/usr/bin/env python3
"""The HairDeck scalp cap's front edge is a hairline, not a cut (Ruling A89, FIT_VERSION hair 17).

Usage: ./.venv/bin/python scripts/smoke_hairdeck_hairline_arc.py

No world, no server, no hub, no network: a throwaway storage dir (``paths.init`` first), every mesh is built here and
``garment_hairdeck.hairline_offset`` / ``hairline_shape`` / ``_scalp_cap`` / ``scalp_fill_cards`` / ``_face_roots``
are called directly. The fails-on-old proof reads ``app/core/garment_hairdeck.py`` of commit ``c7a1b1bfe`` (FIT hair
16) with ``git show``.

User report 2026-11-15: on Vallerie the cap's front edge is a straight horizontal line with a right-angle corner where
her side-swept fringe leaves it open; on her cheek the hair looks grown into the skin (the root ends of cards
HairDeck grew beside her eye).

Constants (garment_hairdeck): HAIRLINE_ARC_RISE_M R = 0.006, HAIRLINE_ARC_DEG a1 = 35, HAIRLINE_DROP_M D = 0.010,
HAIRLINE_TURN_ARC_M 0.06, HAIRLINE_RADIUS_BAND_M (0.002, 0.012], HAIRLINE_SIDE_FADE_DEG (85, 100), CAP_TUCK_M 0.003,
CAP_OFFSET_M 0.0015, CAP_EDGE_FADE_M 0.004, CAP_EDGE_SINK_M 0.001, FILL_LAND_JITTER_M 0.0025.

[1] ``hairline_offset`` by hand, shape {turn_deg 20}: az 0 -> 0; 17.5 -> R (1 - cos(pi/2)) / 2 = 0.003; 35 ->
    R (1 - cos pi) / 2 = 0.006; 45 -> u 0.5, s 0.5: 0.006 * 0.5 - 0.010 * 0.5 = -0.002; 55 and 70 -> -0.010;
    92.5 -> fade 1 - smoothstep(0.5) = 0.5: -0.005; 100 and 180 -> 0; the right side the same (-17.5 -> 0.003,
    -45 -> -0.002). (each +- 1e-12)
[2] ``hairline_shape`` on a sphere head (radius 0.1 at (0, 1.6, 0), 61 bands x 120 segments, all Head), floor 1.64:
    band = head points 2..12 mm under it, y in [1.628, 1.638) -> horizontal radius sqrt(0.01 - (y - 1.6)^2) in
    (0.0925, 0.0960] (the face centroids a hair inside): turn_deg = degrees(0.06 / r) in [35.7, 37.3].
[3] ``_scalp_cap`` with hair from 1.64 up (points on the sphere of radius 0.106, every 5 deg, every 5 mm): hairline
    1.64, no landmarks (no lift). Middle (|az| <= 3): the edge cut points lie on 1.643 and sink CAP_EDGE_SINK_M along
    a normal of y share 0.43: lowest 1.64257 (+- 0.0003), signed distance -0.001 (+- 1e-4: the cut points lie on
    chords, 0.03 mm in). Every cap vertex measured 4 mm or more over its edge (on the body) lies at +0.0015 (+- 2e-5:
    the offset runs along the mesh's vertex normal, not the sphere's). At the temple (az 34..36) the floor is up by
    R (5.95-6.0 mm): edge 1.649, sunk along a normal of y share 0.49 -> lowest 1.6485 (+- 0.0006), over the middle
    by >= 5 mm. Behind the turn (az 75..80: 35 + 36.5 = 71.5 < 75, fade from 85) the floor is 1.64 - 0.010 = 1.630:
    edge 1.633 - 0.001 * 0.33 -> lowest 1.6327 (+- 0.0006).
    c7a1b1bfe (hair 16): the edge is level, 1.643 + 0.0015 * 0.43 = 1.6436 at az 0 and at the temple alike -> FAILS
    "the temple over the middle by >= 5 mm".
[4] The floor curve's turn: sampled every 0.25 deg on the sphere at height 1.643 (r = 0.0907), as (arc length, y),
    resampled every 2 mm. In front of the side fade (|az| <= 80) the steepest bend is where the rise's S meets the
    turn's smoothstep: 6 (R + D) / L^2 with L = the turn's 36.5 deg at r 0.0907 = 0.0578 m: 28.7 /m, plus the S's
    R (pi / (a1 r))^2 / 2 = 9.6 /m -> at most 38.3 /m * 0.002 = 0.077 rad = 4.4 deg per 2 mm (< 4.5). Over the ear the
    fade's smoothstep (D over 15 deg = 0.0237 m: 6 D / 0.0237^2 = 106.6 /m) -> 12.2 deg per 2 mm (< 12.5 overall).
    The FIT 16 floor is level: the corner lay where the level edge met the side hair, 85 deg (the renders).
[5] ``_face_roots`` by hand, floor 1.64 everywhere, chin 1.45, FACE_ROOT_BACK_DEG 15: card A root (v 1) at az 50,
    y 1.55, tip (v 0) at az 130, y 1.65 -> rooted on the face, tip over the floor: flipped (its v -> 1 - v); card B
    the same root, tip at az 60, y 1.56 (under the floor, 10 deg farther back < 15) -> rooted on the face, kept;
    card C rooted at az 0, y 1.66 (over the floor) -> kept; card D the root of A, tip at az 130, y 1.50 (under the
    floor, 80 deg farther back) -> flipped. Report face_rooted 3, flipped 2; B's and C's UVs unchanged bit for bit.
[6] Fill landing (front band beyond z 0.05): with land_jitter 0 ``scalp_fill_cards`` equals the call without the
    keyword bit for bit; with
    FILL_LAND_JITTER_M every row centre lies at or above its floor - 0.0025 - 0.0005, and the landing rows (the
    lowest row of each landed card) spread over more than 1 mm.
"""
import importlib.util
import math
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

BEFORE_A89 = "c7a1b1bfe"
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


def hair_points():
    pts = [[0.0, 1.706, 0.0]]
    for k in range(27):
        y = 1.57 + 0.005 * k
        rho = math.sqrt(0.106 ** 2 - (y - 1.6) ** 2)
        for az in range(-180, 180, 5):
            if y >= 1.64 - 1e-9:
                a = math.radians(az)
                pts.append([rho * math.sin(a), y, rho * math.cos(a)])
    return np.array(pts)


def at(az, y=1.6, r=0.1):
    a = math.radians(az)
    return np.array([[r * math.sin(a), y, r * math.cos(a)]])


def azimuth(X):
    return np.degrees(np.arctan2(X[:, 0], X[:, 2]))


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


def lowest(V, lo, hi):
    a = np.abs(azimuth(V))
    return float(V[(a >= lo) & (a <= hi)][:, 1].min())


def main():
    tmp = tempfile.mkdtemp(prefix="smoke_hairdeck_hairline_arc_")
    from app.core import paths
    paths.init(tmp)
    from app.core import garment_hairdeck as gh
    old = old_module(tmp, BEFORE_A89)

    print("[1] hairline_offset by hand")
    shape = {"turn_deg": 20.0}
    for az, want in ((0, 0.0), (17.5, 0.003), (35, 0.006), (45, -0.002), (55, -0.010), (70, -0.010),
                     (92.5, -0.005), (100, 0.0), (180, 0.0), (-17.5, 0.003), (-45, -0.002)):
        got = float(gh.hairline_offset(at(az), (0.0, 0.0), shape)[0])
        check(abs(got - want) < 1e-12, f"[1] az {az}: {got:+.7f} (want {want:+.7f})")

    P, F = uv_sphere(0.1, (0, 1.6, 0), 61, 120)
    head_v = np.ones(len(P), bool)
    flat = gh.cap_floor(1.64, None, (0.0, 0.0))
    print("[2] hairline_shape")
    plain = hair_points()
    sa = gh.hairline_shape(P, F, head_v, (0.0, 0.0), flat)
    print(f"       {sa}")
    check(35.7 <= sa["turn_deg"] <= 37.3 and 0.0925 - 1e-3 <= sa["radius_m"] <= 0.0960,
          f"[2] turn {sa['turn_deg']} deg in [35.7, 37.3], radius {sa['radius_m']}")

    print("[3] the cap")
    body = SimpleNamespace(positions=P, faces=F)
    sdf = SphereSDF((0, 1.6, 0), 0.1)
    V, Fc, N, hl, info = gh._scalp_cap(body, np.ones(len(P)), plain, sdf, 1.55, None)
    print(f"       hairline {hl}, shape {info.get('shape')}")
    check(abs(hl - 1.64) < 1e-9 and info.get("face_lift_m") == 0.0, f"[3] hairline {hl}, no lift")
    mid = lowest(V, 0.0, 3.0)
    check(abs(mid - 1.64257) <= 0.0003, f"[3] middle: lowest {mid:.5f} (want 1.64257)")
    d = sdf.sample(V)
    check(abs(float(d.min()) + 0.001) <= 1e-4, f"[3] the edge sinks under the skin: min sd {d.min() * 1000:+.4f} mm")
    floor = gh.cap_floor(1.64, None, (0.0, 0.0), 0.0, info["shape"])
    on_body = V - d[:, None] * sdf.grad(V)
    far = on_body[:, 1] - (floor(on_body) + gh.CAP_TUCK_M) >= gh.CAP_EDGE_FADE_M + 1e-9
    dev = float(np.abs(d[far] - 0.0015).max()) if far.any() else 1.0
    check(far.any() and dev <= 2e-5, f"[3] {int(far.sum())} vertices 4 mm or more over the edge at +1.5 mm "
          f"(+- {dev * 1e6:.1f} um)")
    tmp_ = lowest(V, 34.0, 36.0)
    check(abs(tmp_ - 1.6485) <= 0.0006 and tmp_ - mid >= 0.005,
          f"[3] temple (34..36): lowest {tmp_:.5f} (want 1.6485), over the middle by {(tmp_ - mid) * 1000:.1f} mm")
    side = lowest(V, 75.0, 80.0)
    check(abs(side - 1.6327) <= 0.0006, f"[3] behind the turn (75..80): lowest {side:.5f} (want 1.6327)")
    Vo = old._scalp_cap(body, np.ones(len(P)), plain, sdf, 1.55, None)[0]
    o_mid, o35 = lowest(Vo, 0.0, 3.0), lowest(Vo, 34.0, 36.0)
    print(f"       {BEFORE_A89}: middle {o_mid:.5f}, temple {o35:.5f}")
    check(not o35 - o_mid >= 0.005, f"[3] fails on {BEFORE_A89}: a level edge ({(o35 - o_mid) * 1000:+.2f} mm)")

    print("[4] the floor curve's turn")
    r = math.sqrt(0.01 - 0.043 ** 2)
    az = np.arange(-120.0, 120.0001, 0.25)
    pts = np.stack([r * np.sin(np.radians(az)), np.full(len(az), 1.643), r * np.cos(np.radians(az))], 1)
    y = floor(pts)
    s = np.radians(az) * r
    st = np.arange(s[0], s[-1], 0.002)
    yy = np.interp(st, s, y)
    ang = np.degrees(np.arctan2(np.diff(yy), np.diff(st)))
    turn = np.abs(np.diff(ang))
    mid_az = np.interp(st[1:-1], s, az)
    front_t = turn[np.abs(mid_az) <= 80.0]
    check(0.0 < front_t.max() < 4.5, f"[4] |az| <= 80: max turn {front_t.max():.2f} deg per 2 mm (< 4.5)")
    check(turn.max() < 12.5, f"[4] everywhere: max turn {turn.max():.2f} deg per 2 mm (< 12.5)")

    print("[5] _face_roots")
    U = np.zeros((16, 2))
    X = np.zeros((16, 3))
    card = np.repeat(np.arange(4), 4)
    ends = {0: ((50, 1.55), (130, 1.65)), 1: ((50, 1.55), (60, 1.56)), 2: ((0, 1.66), (20, 1.70)),
            3: ((50, 1.55), (130, 1.50))}
    for c, ((ra, ry), (ta, ty)) in ends.items():
        for k, (a_, y_, v) in enumerate(((ra, ry, 1.0), (ra, ry, 1.0), (ta, ty, 0.0), (ta, ty, 0.0))):
            X[4 * c + k] = at(a_, y_)[0] + [0.002 * (k % 2), 0, 0]
            U[4 * c + k] = (k % 2, v)
    U2, rep = gh._face_roots(U, X, card, gh.cap_floor(1.64, None, (0.0, 0.0)), (0.0, 0.0), 1.45)
    print(f"       {rep}")
    check(gh.FACE_ROOT_BACK_DEG == 15.0 and rep == {"face_rooted": 3, "flipped": 2},
          f"[5] report {rep} (want face_rooted 3, flipped 2)")
    for lo, name in ((0, "A"), (12, "D")):
        check(np.array_equal(U2[lo:lo + 4, 1], 1.0 - U[lo:lo + 4, 1]) and np.array_equal(U2[lo:lo + 4, 0], U[lo:lo + 4, 0]),
              f"[5] card {name} turned round")
    check(np.array_equal(U2[4:12], U[4:12]), "[5] cards B and C unchanged")

    print("[6] fill landing")
    crown = np.array([0.0, 1.7, 0.0])
    front = (0.05, gh.CAP_TUCK_M + gh.FILL_EDGE_BAND_M)
    a = gh.scalp_fill_cards(V, Fc, plain, sdf, crown, floor, front=front)
    b = gh.scalp_fill_cards(V, Fc, plain, sdf, crown, floor, front=front, land_jitter=0.0)
    check(all(np.array_equal(x, y) for x, y in zip(a[:5], b[:5])), "[6] land_jitter 0: bit for bit")
    Vf, Ff, Uf, Nf, cf, fi = gh.scalp_fill_cards(V, Fc, plain, sdf, crown, floor, front=front,
                                                 land_jitter=gh.FILL_LAND_JITTER_M)
    centres = (Vf[0::2] + Vf[1::2]) / 2
    under = centres[:, 1] - floor(centres)
    check(fi["cards"] > 0 and float(under.min()) >= -0.0025 - 0.0005,
          f"[6] {fi['cards']} cards; every row centre >= floor - 3 mm ({under.min() * 1000:+.2f} mm)")
    ccard = cf[0::2]
    lows = np.array([under[ccard == k].min() for k in np.unique(ccard)])
    landed = lows[lows < 0.0005]
    spread = float(landed.max() - landed.min()) if len(landed) else 0.0
    check(len(landed) > 1 and spread > 0.001, f"[6] {len(landed)} landed cards spread over {spread * 1000:.2f} mm")

    print("\nALL OK" if not FAILS else f"\n{len(FAILS)} FAILURE(S)")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
