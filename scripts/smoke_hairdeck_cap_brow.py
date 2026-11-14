#!/usr/bin/env python3
"""On a fringe the HairDeck scalp cap ends in the face at the natural hairline of the scalp, never lower (Ruling
A80, FIT_VERSION hair 15; Ruling A80b, hair 16).

Usage: ./.venv/bin/python scripts/smoke_hairdeck_cap_brow.py

No world, no server, no hub, no network: a throwaway storage dir (``paths.init`` first), every mesh is built here and
``garment_hairdeck._scalp_cap`` / ``fringe_floor`` / ``cap_floor`` / ``scalp_fill_cards`` are called directly. Two
older versions of ``app/core/garment_hairdeck.py`` are read with ``git show`` for the fails-on-old proofs:
``9312d5058`` (before A80: the cap at the fringe's tip) and ``cc032dbb8`` (A80, hair 15: the cap at the brow).

User reports 2026-11-15: Vallerie's brown cap ends in her face at the eyes (on a fringe the front hairline — the
lowest front hair vertex at or above the nasion — is the fringe's TIP, and the cap was cut at that one height all
round the head: 43.3 mm below her brow line). Hair 15 lifted it to the brow: a flat 4 cm slab of cap and fill over
the forehead (a visor). Ruling A80b: on a fringe the cap ends where the scalp's hairline is, ``hairline_target`` =
brow + 0.25 * (crown - brow) — where the auto tilt puts every hairline without a fringe, so the cap ends where a
fit without a fringe ends anyway. Below it the forehead is skin under the fringe's own cards.

Fixture (metres, +y up, the face looks along +z)
- Head = UV sphere radius 0.1 centred (0, 1.6, 0), 61 bands x 120 segments (azimuth step 3 deg), every vertex Head
  weight 1; body SDF = the exact sphere. Head box: x and z in +-0.099967 (ring 30 at polar 88.52 deg, sin 0.99967)
  -> centre (cx, cz) = (0, 0), width = depth = 0.19993; the front hairline strip is z > 0.04998, |x| < 0.02999.
- Hair = points on the sphere of radius 0.106 (6 mm over the head), azimuth every 5 deg, heights y = 1.57, 1.575, ..
  1.70 (+ the top point (0, 1.706, 0)): all round the head from 1.63 up; in front (|azimuth| <= 40 deg) a fringe
  from 1.57 up. At y 1.57 the fringe's ring radius is sqrt(0.106^2 - 0.03^2) = 0.101667: its point at azimuth 0 is
  (0, 1.57, 0.101667), in the front strip -> hairline = 1.57 (the floor, the nasion, is 1.55: 1.57 counts).
  Reference hair WITHOUT a fringe: the same points, in front only from 1.64 up -> its hairline is 1.64 (the strip's
  lowest point; the 1.63 / 1.635 rings in the strip are left out, those at |azimuth| >= 45 deg lie at |x| >= 0.07).
- Landmarks: brow 1.62, crown 1.70, nasion 1.55 -> natural hairline = 1.62 + 0.25 * (1.70 - 1.62) = 1.64.
- Azimuth of a point = atan2(x - cx, z - cz) in degrees; face sector = |azimuth| <= FACE_SECTOR_DEG 60; the fade to
  the plain hairline ends at 60 + FACE_SECTOR_FADE_DEG 25 = 85 deg.

[1] ``fringe_floor``: hairline 1.57 (<= brow 1.62) -> 1.64; 1.62 (at the brow, a fringe) -> 1.64; 1.63 (above) ->
    None; no landmarks -> None. ``cap_floor(1.57, 1.64, (0, 0))``: lift 0.07, floor = 1.57 + 0.07 * w,
    w = clip((85 - |az|) / 25, 0, 1): az 0 / -30 / 60 -> 1.64; az 72.5 -> w 0.5 -> 1.605; az 85 / 120 / 180 -> 1.57
    (each +- 1e-12). Without a face height (None) or with one at / below the hairline: 1.57 everywhere.
[2] 9312d5058: the cap is cut at y = 1.57 + CAP_TUCK_M 0.003 = 1.573 all round; the face triangles there have fringe
    hair within CAP_REACH_M 0.03, so the cut points lie on 1.573 and move CAP_OFFSET_M 0.0015 out along a normal
    whose y share is about (1.573 - 1.6) / 0.1 = -0.27 -> 0.4 mm lower: lowest cap point in the face sector 1.5726
    (+- 0.0006), below the natural hairline (and the brow) -> FAILS "lowest >= 1.64".
    cc032dbb8 (hair 15, cut at the brow + 0.003 = 1.623, normal y share +0.23 -> +0.35 mm): 1.6233 (+- 0.0006),
    16.7 mm below the natural hairline 1.64 — the visor -> FAILS "lowest >= 1.64" too.
[3] New: in the face sector the edge lies on 1.64 + 0.003 = 1.643; the cut points move 0.0015 out along a normal whose
    y share is about 0.43 -> +0.65 mm: the lowest cap point within 60 deg is 1.6436 (+- 0.0006) — at or above the
    natural hairline 1.64 and no higher than 1.645 (the cap reaches its edge: no gap under the fringe's roots).
    No helmet: the reference hair without a fringe (hairline 1.64 > brow: no lift) is cut at 1.643 everywhere — its
    lowest cap point within 55 deg is the same 1.6436 (+- 1e-6): the fringe fit's cap ends where it would without.
    Report: face_floor_y 1.64, face_edge_y 1.643, face_lift_m 0.07.
    Sides and back: the cap within |az| >= 88 deg is 9312d5058's vertex for vertex (+- 1e-12) — every triangle there
    has all three vertices at az >= 87 deg, w 0, the old level 1.573.
[4] No fringe (brow 1.56, below the hairline 1.57) and no landmarks: positions, faces and normals of the cap equal
    9312d5058's (+- 0): a fit whose hairline lies above the brow is rebuilt unchanged.
[5] Fill cards on the new cap with the floor ``cap_floor(1.57, 1.64)`` and the front band (z > 0.04998, less than
    0.003 + 0.012 above the floor): cards exist. A card lands on the floor at its row CENTRE (+- 0.5 mm: the landing
    step is cut where it crosses the floor and put back on the sphere, smoke_garment_hairdeck_fit [7]); its two
    vertices lie FILL_WIDTH_M / 2 = 6 mm to either side, horizontally on a meridian card: at 1.64 the rows' circle
    has radius sqrt(0.1025^2 - 0.04^2) = 0.09437, 6 mm = 3.64 deg of azimuth. So every row centre lies at or above
    its own floor - 0.0005, and every fill vertex within 60 - 3.64 = 56.3 deg (rounded down: 56) at or above
    1.64 - 0.0005. 9312d5058's fill there lands on 1.57.
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

BEFORE_A80 = "9312d5058"
A80_BROW = "cc032dbb8"
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


def hair_points(fringe):
    pts = [[0.0, 1.706, 0.0]]
    for k in range(27):
        y = 1.57 + 0.005 * k
        rho = math.sqrt(0.106 ** 2 - (y - 1.6) ** 2)
        for az in range(-180, 180, 5):
            front = abs(az) <= 40
            if (front and (fringe or y >= 1.64 - 1e-9)) or (not front and y >= 1.63 - 1e-9):
                a = math.radians(az)
                pts.append([rho * math.sin(a), y, rho * math.cos(a)])
    return np.array(pts)


def azimuth(X):
    return np.degrees(np.abs(np.arctan2(X[:, 0], X[:, 2])))


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


def lowest(V, az_max):
    return float(V[azimuth(V) <= az_max][:, 1].min())


def main():
    tmp = tempfile.mkdtemp(prefix="smoke_hairdeck_cap_brow_")
    from app.core import paths
    paths.init(tmp)
    from app.core import garment_hairdeck as gh
    old = old_module(tmp, BEFORE_A80)
    a80 = old_module(tmp, A80_BROW)

    P, F = uv_sphere(0.1, (0, 1.6, 0), 61, 120)
    body = SimpleNamespace(positions=P, faces=F)
    head_w = np.ones(len(P))
    sdf = SphereSDF((0, 1.6, 0), 0.1)
    hair = hair_points(fringe=True)
    ref = hair_points(fringe=False)
    lm = {"brow_y": 1.62, "crown_y": 1.70, "nasion_y": 1.55}
    box = gh._head_box(P, head_w > 0.5)
    print(f"       head box {box}")
    check(abs(box[0]) < 1e-9 and abs(box[1]) < 1e-9 and abs(box[2] - 0.19993) < 1e-5,
          "[0] head centre (0, 0), width 0.19993")

    print("[1] fringe_floor / cap_floor")
    for hl, want in ((1.57, 1.64), (1.62, 1.64), (1.63, None)):
        got = gh.fringe_floor(hl, lm)
        check((got is None and want is None) or (got is not None and want is not None and abs(got - want) < 1e-12),
              f"[1] fringe_floor({hl}) = {got} (want {want})")
    check(gh.fringe_floor(1.57, None) is None, "[1] fringe_floor without landmarks: None")
    fl = gh.cap_floor(1.57, 1.64, (0.0, 0.0))
    for az, want in ((0, 1.64), (-30, 1.64), (60, 1.64), (72.5, 1.605), (85, 1.57), (120, 1.57), (180, 1.57)):
        a = math.radians(az)
        got = float(fl(np.array([[0.1 * math.sin(a), 1.6, 0.1 * math.cos(a)]]))[0])
        check(abs(got - want) < 1e-12, f"[1] floor at az {az}: {got:.6f} (want {want})")
    pts = np.array([[0, 1.6, 0.1], [0.1, 1.6, 0], [0, 1.6, -0.1]])
    check(np.all(gh.cap_floor(1.57, None, (0, 0))(pts) == 1.57), "[1] no face height: 1.57 everywhere")
    check(np.all(gh.cap_floor(1.57, 1.56, (0, 0))(pts) == 1.57), "[1] face height below the hairline: 1.57")

    print(f"[2] old code ({BEFORE_A80}, {A80_BROW})")
    Vo, Fo, No, hl_o, _ = old._scalp_cap(body, head_w, hair, sdf, 1.55)
    low_o = lowest(Vo, 60.0)
    print(f"       {BEFORE_A80}: lowest face cap point {low_o:.5f} ({(low_o - 1.64) * 1000:+.1f} mm to the hairline)")
    check(abs(hl_o - 1.57) < 1e-9 and abs(low_o - 1.5726) <= 0.0006, f"[2] {BEFORE_A80}: {low_o:.5f} (want 1.5726)")
    check(not low_o >= 1.64, f"[2] fails on {BEFORE_A80}: the cap reaches into the face")
    V15 = a80._scalp_cap(body, head_w, hair, sdf, 1.55, 1.62)[0]
    low_15 = lowest(V15, 60.0)
    print(f"       {A80_BROW}: lowest face cap point {low_15:.5f} ({(low_15 - 1.64) * 1000:+.1f} mm to the hairline)")
    check(abs(low_15 - 1.6233) <= 0.0006, f"[2] {A80_BROW}: {low_15:.5f} (want 1.6233)")
    check(not low_15 >= 1.64, f"[2] fails on {A80_BROW}: the cap is a visor down to the brow")

    print("[3] new code")
    Vn, Fn, Nn, hl_n, info_n = gh._scalp_cap(body, head_w, hair, sdf, 1.55, lm)
    print(f"       {info_n}")
    check(abs(hl_n - 1.57) < 1e-9, f"[3] new hairline {hl_n} (unchanged)")
    low_n = lowest(Vn, 60.0)
    print(f"       new lowest face cap point {low_n:.5f} ({(low_n - 1.64) * 1000:+.1f} mm to the hairline)")
    check(low_n >= 1.64, f"[3] the cap's lowest face point {low_n:.5f} >= the natural hairline 1.64")
    check(abs(low_n - 1.6436) <= 0.0006 and low_n <= 1.645, f"[3] it reaches its edge: {low_n:.5f} (want 1.6436)")
    Vr = gh._scalp_cap(body, head_w, ref, sdf, 1.55, lm)
    check(abs(Vr[3] - 1.64) < 1e-9 and Vr[4].get("face_lift_m") == 0.0, f"[3] reference: hairline {Vr[3]}, no lift")
    low_r, low_n55 = lowest(Vr[0], 55.0), lowest(Vn, 55.0)
    check(abs(low_r - low_n55) <= 1e-6, f"[3] no helmet: fringe cap ends at {low_n55:.6f}, without a fringe {low_r:.6f}")
    check(info_n.get("face_floor_y") == 1.64 and info_n.get("face_edge_y") == 1.643
          and info_n.get("face_lift_m") == 0.07, f"[3] report face_floor_y 1.64, face_edge_y 1.643, lift 0.07")
    so, sn = Vo[azimuth(Vo) >= 88.0], Vn[azimuth(Vn) >= 88.0]
    so, sn = so[np.lexsort(so.T)], sn[np.lexsort(sn.T)]
    check(len(so) == len(sn) and len(so) > 0 and np.abs(so - sn).max() <= 1e-12,
          f"[3] sides/back (az >= 88): {BEFORE_A80}'s cap vertex for vertex ({len(so)} / {len(sn)})")

    print("[4] no fringe / no landmarks: unchanged")
    for marks, label in (({"brow_y": 1.56, "crown_y": 1.70}, "brow 1.56"), (None, "no landmarks")):
        V2, F2, N2, _, _ = gh._scalp_cap(body, head_w, hair, sdf, 1.55, marks)
        check(np.array_equal(V2, Vo) and np.array_equal(F2, Fo) and np.array_equal(N2, No),
              f"[4] {label}: the cap equals {BEFORE_A80}'s ({len(V2)} / {len(Vo)} vertices)")

    print("[5] fill cards")
    z_min = box[1] + gh.HAIRLINE_FRONT_DEPTH * box[3]
    crown = np.array([0.0, 1.7, 0.0])
    floor = gh.cap_floor(hl_n, gh.fringe_floor(hl_n, lm), (0.0, 0.0))
    Vf, Ff, Uf, Nf, cf, fi = gh.scalp_fill_cards(Vn, Fn, hair, sdf, crown, floor,
                                                 front=(z_min, gh.CAP_TUCK_M + gh.FILL_EDGE_BAND_M))
    print(f"       {fi}")
    face_f = Vf[azimuth(Vf) <= 56.0]
    check(fi["cards"] > 0 and len(face_f) > 0, f"[5] fill cards in the face: {fi['cards']} cards, {len(face_f)} vertices")
    low_f = float(face_f[:, 1].min()) if len(face_f) else float("nan")
    check(low_f >= 1.64 - 0.0005, f"[5] lowest fill vertex within 56 deg {low_f:.5f} >= 1.6395")
    centres = (Vf[0::2] + Vf[1::2]) / 2
    under = centres[:, 1] - floor(centres)
    check(float(under.min()) >= -0.0005, f"[5] every row centre at or above its floor - 0.5 mm ({under.min() * 1000:+.2f} mm)")
    Vfo = old.scalp_fill_cards(Vo, Fo, hair, sdf, crown, hl_o,
                               front=(z_min, hl_o + old.CAP_TUCK_M + old.FILL_EDGE_BAND_M))[0]
    low_fo = lowest(Vfo, 56.0)
    check(low_fo < 1.60, f"[5] {BEFORE_A80}: fill in the face lands on the fringe tip ({low_fo:.5f})")

    print("\nALL OK" if not FAILS else f"\n{len(FAILS)} FAILURE(S)")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
