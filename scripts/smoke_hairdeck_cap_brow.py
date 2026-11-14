#!/usr/bin/env python3
"""The HairDeck scalp cap never reaches below the brow line in the face (Ruling A80, FIT_VERSION hair 15).

Usage: ./.venv/bin/python scripts/smoke_hairdeck_cap_brow.py

No world, no server, no hub, no network: a throwaway storage dir (``paths.init`` first), every mesh is built here and
``garment_hairdeck._scalp_cap`` / ``cap_floor`` / ``scalp_fill_cards`` are called directly. The old code is read with
``git show 9312d5058:app/core/garment_hairdeck.py`` (the commit before the fix) for the fails-on-old proof.

User report 2026-11-15: Vallerie's brown cap ends in her face at the eyes. On a fringe the front hairline (the lowest
front hair vertex at or above the nasion) is the fringe's TIP, and the cap was cut at that one height all round the
head: her cap ended 43.3 mm below her brow line, 22.5 mm below her eye line.

Fixture (metres, +y up, the face looks along +z)
- Head = UV sphere radius 0.1 centred (0, 1.6, 0), 61 bands x 120 segments (azimuth step 3 deg), every vertex Head
  weight 1; body SDF = the exact sphere. Head box: x and z in +-0.099967 (ring 30 at polar 88.52 deg, sin 0.99967)
  -> centre (cx, cz) = (0, 0), width = depth = 0.19993; the front hairline strip is z > 0.04998, |x| < 0.02999.
- Hair = points on the sphere of radius 0.106 (6 mm over the head), azimuth every 5 deg, heights y = 1.57, 1.575, ..
  1.70 (+ the top point (0, 1.706, 0)): all round the head from 1.63 up; in front (|azimuth| <= 40 deg) a fringe
  from 1.57 up. At y 1.57 the fringe's ring radius is sqrt(0.106^2 - 0.03^2) = 0.101667: its point at azimuth 0 is
  (0, 1.57, 0.101667), in the front strip -> hairline = 1.57 (the floor, the nasion, is 1.55: 1.57 counts).
- Landmarks: brow 1.62 (above the hairline: a fringe), nasion 1.55.
- Azimuth of a point = atan2(x - cx, z - cz) in degrees; face sector = |azimuth| <= FACE_SECTOR_DEG 60; the fade to
  the plain hairline ends at 60 + FACE_SECTOR_FADE_DEG 25 = 85 deg.

[1] ``cap_floor(1.57, 1.62, (0, 0))``: lift = 1.62 - 1.57 = 0.05; floor = 1.57 + 0.05 * w,
    w = clip((85 - |az|) / 25, 0, 1): az 0 / -30 / 60 -> w 1 -> 1.62; az 72.5 -> w 0.5 -> 1.595; az 85 / 120 / 180
    -> w 0 -> 1.57 (each +- 1e-12). Without a brow (None) or with a brow at / below the hairline (1.56) the floor is
    1.57 everywhere.
[2] Old code (9312d5058): the cap is cut at y = hairline + CAP_TUCK_M = 1.573 all round. The face triangles at that
    height have fringe hair within CAP_REACH_M 0.03 (the fringe lies 6 mm over them), so the cap runs down to the cut:
    the cut points lie on the level 1.573 (on the chords, inside the sphere) and move CAP_OFFSET_M 0.0015 out along
    the normal, whose y share there is about (1.573 - 1.6) / 0.1 = -0.27 -> 0.4 mm lower: the cap's lowest point in
    the face sector is 1.5726 (+- 0.0006), 47.4 mm BELOW the brow 1.62 -> the check "lowest >= brow" FAILS on it.
    Its fill cards (floor 1.57, front band up to 1.57 + 0.003 + 0.012 = 1.585) land on 1.57: below the brow.
[3] New code: in the face sector the edge lies on 1.62 + 0.003 = 1.623 (every vertex of a triangle within 60 deg has
    w 1); the cut points lie on that level and move 0.0015 out along a normal whose y share is about
    (1.623 - 1.6) / 0.1 = +0.23 -> 0.35 mm higher: the lowest cap point within 60 deg is 1.6233 (+- 0.0006) — at or
    above the brow 1.62, and no higher than 1.6245 (the cap still reaches its edge: no gap under the fringe).
    Sides and back: the cap within |az| >= 88 deg is the old one vertex for vertex (+- 1e-12) — every triangle there
    has all three vertices at az >= 87 deg, w 0, the level 1.573 of the old code (a triangle spanning 84..87 deg has
    its cut points at az <= 87 deg).
[4] No fringe (brow 1.56, below the hairline 1.57) and no landmarks (brow None): positions, faces and normals of the
    cap equal the old code's (+- 0): a fit whose hairline lies above the brow is rebuilt unchanged.
[5] Fill cards on the new cap with the floor ``cap_floor`` and the front band (z > 0.04998, less than 0.003 + 0.012
    above the floor): cards exist. A card lands on the floor at its row CENTRE (the landing row is cut where its
    straight step crosses the floor and put back on the sphere: +- 0.5 mm, smoke_garment_hairdeck_fit [7]); its two
    vertices lie FILL_WIDTH_M / 2 = 6 mm to either side, horizontally on a meridian card: at the brow height the
    rows' circle has radius sqrt(0.1025^2 - 0.02^2) = 0.10053, 6 mm = 3.42 deg of azimuth. So every row centre lies at
    or above its own floor - 0.0005, and every fill vertex within 60 - 3.42 = 56.5 deg (its row centre within 59.92
    deg, w 1) at or above 1.62 - 0.0005. (A card centred in the fade, at 63 deg, lands on 1.62 - 0.05 * 3 / 25 =
    1.614, and its inner vertex lies at 59.6 deg: the fade, not the face.) Old: some fill vertex within 56.5 deg below
    1.60 (they land on 1.57).
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

BASE_COMMIT = "9312d5058"
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
            if y >= 1.63 - 1e-9 or abs(az) <= 40:
                a = math.radians(az)
                pts.append([rho * math.sin(a), y, rho * math.cos(a)])
    return np.array(pts)


def azimuth(X):
    return np.degrees(np.abs(np.arctan2(X[:, 0], X[:, 2])))


def old_module(tmp):
    src = subprocess.run(["git", "-C", str(ROOT), "show", f"{BASE_COMMIT}:app/core/garment_hairdeck.py"],
                         check=True, capture_output=True, text=True).stdout
    path = Path(tmp) / "old_garment_hairdeck.py"
    path.write_text(src)
    spec = importlib.util.spec_from_file_location("old_garment_hairdeck", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["old_garment_hairdeck"] = mod
    spec.loader.exec_module(mod)
    return mod


def main():
    tmp = tempfile.mkdtemp(prefix="smoke_hairdeck_cap_brow_")
    from app.core import paths
    paths.init(tmp)
    from app.core import garment_hairdeck as gh
    old = old_module(tmp)

    P, F = uv_sphere(0.1, (0, 1.6, 0), 61, 120)
    body = SimpleNamespace(positions=P, faces=F)
    head_w = np.ones(len(P))
    sdf = SphereSDF((0, 1.6, 0), 0.1)
    hair = hair_points()
    box = gh._head_box(P, head_w > 0.5)
    print(f"       head box {box}")
    check(abs(box[0]) < 1e-9 and abs(box[1]) < 1e-9 and abs(box[2] - 0.19993) < 1e-5, "[0] head centre (0, 0), width 0.19993")

    print("[1] cap_floor")
    fl = gh.cap_floor(1.57, 1.62, (0.0, 0.0))
    for az, want in ((0, 1.62), (-30, 1.62), (60, 1.62), (72.5, 1.595), (85, 1.57), (120, 1.57), (180, 1.57)):
        a = math.radians(az)
        got = float(fl(np.array([[0.1 * math.sin(a), 1.6, 0.1 * math.cos(a)]]))[0])
        check(abs(got - want) < 1e-12, f"[1] floor at az {az}: {got:.6f} (want {want})")
    pts = np.array([[0, 1.6, 0.1], [0.1, 1.6, 0], [0, 1.6, -0.1]])
    check(np.all(gh.cap_floor(1.57, None, (0, 0))(pts) == 1.57), "[1] no brow: 1.57 everywhere")
    check(np.all(gh.cap_floor(1.57, 1.56, (0, 0))(pts) == 1.57), "[1] brow 1.56 below the hairline: 1.57 everywhere")

    print("[2] old code (9312d5058)")
    Vo, Fo, No, hl_o, info_o = old._scalp_cap(body, head_w, hair, sdf, 1.55)
    check(abs(hl_o - 1.57) < 1e-9, f"[2] old hairline {hl_o}")
    face_o = Vo[azimuth(Vo) <= 60.0]
    low_o = float(face_o[:, 1].min())
    print(f"       old lowest cap point in the face sector {low_o:.5f} ({(low_o - 1.62) * 1000:+.1f} mm to the brow)")
    check(abs(low_o - 1.5726) <= 0.0006, f"[2] old lowest face point {low_o:.5f} (want 1.5726 +- 0.0006)")
    check(not low_o >= 1.62, "[2] fails on the old code: the old cap reaches below the brow in the face")

    print("[3] new code")
    Vn, Fn, Nn, hl_n, info_n = gh._scalp_cap(body, head_w, hair, sdf, 1.55, 1.62)
    print(f"       {info_n}")
    check(abs(hl_n - 1.57) < 1e-9, f"[3] new hairline {hl_n} (unchanged)")
    low_n = float(Vn[azimuth(Vn) <= 60.0][:, 1].min())
    print(f"       new lowest cap point in the face sector {low_n:.5f} ({(low_n - 1.62) * 1000:+.1f} mm to the brow)")
    check(low_n >= 1.62, f"[3] the cap's lowest face point {low_n:.5f} >= the brow 1.62")
    check(abs(low_n - 1.6233) <= 0.0006 and low_n <= 1.6245, f"[3] it reaches its edge: {low_n:.5f} (want 1.6233 +- 0.0006)")
    check(info_n.get("face_edge_y") == 1.623 and info_n.get("face_lift_m") == 0.05,
          f"[3] report face_edge_y 1.623, face_lift_m 0.05 ({info_n.get('face_edge_y')}, {info_n.get('face_lift_m')})")
    side_o = Vo[azimuth(Vo) >= 88.0]
    side_n = Vn[azimuth(Vn) >= 88.0]
    so, sn = side_o[np.lexsort(side_o.T)], side_n[np.lexsort(side_n.T)]
    check(len(so) == len(sn) and len(so) > 0 and np.abs(so - sn).max() <= 1e-12,
          f"[3] sides/back (az >= 88): the old cap vertex for vertex ({len(so)} / {len(sn)})")

    print("[4] no fringe / no landmarks: unchanged")
    for brow, label in ((1.56, "brow 1.56"), (None, "no brow")):
        V2, F2, N2, _, _ = gh._scalp_cap(body, head_w, hair, sdf, 1.55, brow)
        check(np.array_equal(V2, Vo) and np.array_equal(F2, Fo) and np.array_equal(N2, No),
              f"[4] {label}: the cap equals the old code's ({len(V2)} / {len(Vo)} vertices)")

    print("[5] fill cards")
    z_min = box[1] + gh.HAIRLINE_FRONT_DEPTH * box[3]
    crown = np.array([0.0, 1.7, 0.0])
    Vf, Ff, Uf, Nf, cf, fi = gh.scalp_fill_cards(Vn, Fn, hair, sdf, crown, gh.cap_floor(hl_n, 1.62, (0.0, 0.0)),
                                                 front=(z_min, gh.CAP_TUCK_M + gh.FILL_EDGE_BAND_M))
    print(f"       {fi}")
    face_f = Vf[azimuth(Vf) <= 56.5]
    check(fi["cards"] > 0 and len(face_f) > 0, f"[5] fill cards in the face: {fi['cards']} cards, {len(face_f)} face vertices")
    low_f = float(face_f[:, 1].min()) if len(face_f) else float("nan")
    check(low_f >= 1.62 - 0.0005, f"[5] lowest fill vertex within 56.5 deg {low_f:.5f} >= 1.6195")
    centres = (Vf[0::2] + Vf[1::2]) / 2
    under = centres[:, 1] - gh.cap_floor(hl_n, 1.62, (0.0, 0.0))(centres)
    check(float(under.min()) >= -0.0005, f"[5] every row centre at or above its floor - 0.5 mm ({under.min() * 1000:+.2f} mm)")
    Vfo, _, _, _, _, fio = old.scalp_fill_cards(Vo, Fo, hair, sdf, crown, hl_o,
                                                front=(z_min, hl_o + old.CAP_TUCK_M + old.FILL_EDGE_BAND_M))
    face_fo = Vfo[azimuth(Vfo) <= 56.5]
    low_fo = float(face_fo[:, 1].min()) if len(face_fo) else float("nan")
    check(low_fo < 1.60, f"[5] old: fill in the face lands below the brow ({low_fo:.5f})")

    print("\nALL OK" if not FAILS else f"\n{len(FAILS)} FAILURE(S)")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
