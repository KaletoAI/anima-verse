#!/usr/bin/env python3
"""Smoke: a flat shoe with a layered sole, the vertical forefoot slimming and the honest toe-box reason
(INSOLE_VERSION 8, footwear_fit version 16, footwear_cut version 7; the module docstrings' "Sole layers", step 1b
and ``too_flat_reason``). The live case: Kai's low-top sneakers ``item_3c60cf62`` were refused because the insole
analysis read the sole's hollow plate as the insole and flipped the shoe on a 1.1-mm difference.

Usage:  ./.venv/bin/python scripts/smoke_footwear_sole_layers.py

No storage, no world DB, no hub, no server: numpy on synthetic meshes. The "fails on the old code" proofs load
``footwear_insole.py`` and ``footwear_fit.py`` of commit c473a962 (``git show``) next to the current ones.

Meshes (mesher coordinates: Y up, x heel -> toe, z lateral), length L = 0.26, half width 0.04: full-footprint sheets
over x in [0, 0.26] x z in [-0.04, 0.04] (quads every 0.01 in x), zero-thickness side walls at z = +-0.04 from the
ground to the wall height, taller over x < 0.04 (the heel counter: the provisional frame's heel rule puts the heel
at x = 0), a vamp roof at the wall top over x in [0.16, 0.26] (facing up), a heel face at x = 0 and a toe face at
x = 0.26 (vertical: no ray hits them). Grid: 240 stations x_i = i L / 239, AIR = 0.025 L = 0.0065, TOL = 0.035 L.

[A] the flip needs a clear rise. Sheets: the ground (facing down) and the insole h(x) = 0.01 + 0.0016 x / L
    (facing up); walls 0.05, heel counter 0.06, roof at 0.05. The insole at 0.10 L = 0.01016, at 0.90 L = 0.01144:
    the toe end stands 0.00128 = 0.49 % L higher. FLIP_MIN_SHARE 1 % -> not flipped: the silhouette's heel stays,
    profile[24] = h(24 L / 239) = 0.01 + 0.0016 * 24 / 239 = 0.0101607, profile[215] = 0.0114393; every forefoot
    station (x >= 0.62 L = 0.1612) lies under the roof (from 0.16) -> vamp_cover 1.0, gates ok.
    c473a962 flipped on ANY rise (the insole at 0.10 L lower than at 0.90 L): the frame turns, the roof lies over
    the "heel", vamp_cover 0 -> refused "Open shoes and sandals are not supported yet" (the Kai base symptom).
[B] the open seed. Sheets: the ground 0 (down), a hollow sole plate's floor 0.005 (up), the footbed's underside
    0.022 (down), the footbed 0.025 (up); walls 0.065, heel counter 0.075, roof 0.065. Candidates (up-facing, at
    least AIR of air above or nothing): the plate's floor (0.017 to the underside) and the footbed (0.04 to the roof
    or nothing). The topline is the wall top 0.065 (0.075 at the heel): the footbed lies 0.04 >= AIR under it and its
    next hit, the roof at the topline, is >= topline - AIR -> OPEN; the plate's floor has the underside 0.022 <
    0.065 - 0.0065 above it -> closed. Every station has every column open -> the seed station nearest 0.55 * 240,
    the footbed in every column -> profile 0.025 at every station; the cavity under the roof (x >= 0.16, station
    200 at x 0.2176) 0.065 - 0.025 = 0.04, none at station 120 (x 0.1305, no roof).
    c473a962 seeded on the LOWEST candidate, the plate's floor: profile 0.005, "cavity" 0.022 - 0.005 = 0.017 at
    every station (the live sneakers' 17-20 mm toe box).
[C] MAX_HITS 48. B's sole with four thin sheets in it (down / up at 0.007 / 0.008, 0.010 / 0.011, 0.013 / 0.014,
    0.016 / 0.017): per column the hits are 0, 0.005, the 8 sheet faces, 0.022, 0.025 = 12, the roof the 13th. The
    plate's floor (0.002 to the first sheet) and the sheets' tops (0.002 / 0.005 to the next face) have less than
    AIR above: the footbed is the only candidate, in both versions. Now the roof is recorded: profile 0.025, cavity
    0.04 at station 200, vamp_cover 1.0, gates ok. c473a962 recorded 12 hits: the roof is dropped, no station has a
    roof -> vamp_cover 0, refused as an open shoe.
[D] the floor (``footwear_fit.FOOT_FLOOR_SHARES``, a share of the foot length at u = the share from the toe tip):
    for L 0.27 at u 0 / 0.10 / 0.36 / 0.55 / 0.70 / 0.9: 0.04 / 0.074 / 0.148 / 0.241 / 0.30 / 0.30 of 0.27 =
    0.0108 / 0.01998 / 0.03996 / 0.06507 / 0.081 / 0.081; at u 0.23 (between 0.10 and 0.36): 0.074 + 0.13 / 0.26 *
    0.074 = 0.111 -> 0.02997.
[E] ``footwear_cut._vslim_factors`` on a box foot: flat insole at 0, the toe box's inner surface 0.03, clearance
    0.002 -> room 0.028; toe tip x 0.25, foot length 0.25; foot vertices every 0.001 over x in [0.10, 0.25] at y 0
    and 0.05 (top t = 0.05 at every station). Stations every SLIM_WINDOW_M 0.003 from 0.10 (51, to 0.25); factor
    min(1, max(room, floor) / t), smoothed over +-0.005 (a station's window holds it and its two neighbours: the mean
    of a linear piece is its value at the station). The floor passes the room where 0.25 * share > 0.028, share >
    0.112, u > 0.10 + 0.038 / 0.074 * 0.26 = 0.2335, x < 0.25 - 0.2335 * 0.25 = 0.19162.
    x 0.235 (u 0.06, the floor 0.0157 under the room): 0.028 / 0.05 = 0.56;
    x 0.175 (u 0.30): floor 0.25 * (0.074 + 0.20 / 0.26 * 0.074) = 0.0327308 -> 0.654615;
    x 0.11 (u 0.56): floor 0.25 * (0.241 + 0.01 / 0.15 * 0.059) = 0.0612333 > t -> 1.
    vslim_share = 1 - 0.56 = 0.44; vslim_floor_stations = the stations at x < 0.19162: 0.100 .. 0.190 = 31.
[F] ``too_flat_reason`` (a record whose height_needed 2.0 / 1.9 passes HEIGHT_CAP 1.5, worst station roof 24.6 mm,
    need 53.4, foot 51.4 mm at u 0.3): the image agrees (or the insole has no comparison) -> "Foot too high for this
    shoe even after slimming (foot 51 mm, shoe 25 mm at the ball)"; u 0.1 -> "the toes", u 0.5 -> "the instep";
    the image disagrees -> "Shoe mesh too flat for the foot: toe box 25 mm, instep needs ~53 mm — regenerate the
    shoe"; height_needed 1.4 / 1.3 -> None. c473a962 named the mesh for the agreeing image too.
[G] ``footwear_gates.image_agreement``: B's mesh against its own side silhouette -> IoU 1.0, toe profile ratio 1.0,
    agrees. B with every point over the toe half (x >= 0.13) at half its height (the walls and the roof at 0.0325)
    against B's silhouette: both crop to 0.26 x 0.075; the toe half's top 0.0325 against 0.065 -> ratio 0.5 (+-0.03)
    < 0.80; IoU = the flat mesh's side area over B's: (0.13 * 0.065 + 0.04 * 0.01 + 0.13 * 0.0325) / (0.26 * 0.065 +
    0.04 * 0.01) = 0.013075 / 0.0173 = 0.7558 (+-0.02) < 0.85 -> disagrees.
[H] the chain (garment_footwear.fit_compute) on smoke_footwear_fit.py [F14] (e)'s closed clog S 1.0 with the foot
    raised to Ht 0.065: there, with the slimming off, x1.5 left toe_conform 0.028615 > 0.025 and the toe box was
    refused naming the mesh (and c473a962 refused it so). Slimmed, the worst station keeps the floor at its u (the
    record's toe_share): foot_mm = 1000 * 0.25 * share(u) (+-0.01) under the raw 65 mm, the roof 0.025 k = 25.590
    mm; the second attempt at x1.5 is ACCEPTED with toe_conform < 0.025 (and < 0.028615).
"""
import importlib.util
import subprocess
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402

OLD = "c473a962"
L, HW = 0.26, 0.04
FAILS = []


def check(label, got, want, tol=None):
    if tol is None:
        ok = got == want
    else:
        ok = got is not None and abs(float(got) - float(want)) <= tol
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f" (expected {want!r})"))
    if not ok:
        FAILS.append(label)


def old_module(rel: str, name: str, tmp: Path):
    src = subprocess.run(["git", "-C", str(ROOT), "show", f"{OLD}:{rel}"], capture_output=True, check=True).stdout
    path = tmp / f"{name}.py"
    path.write_bytes(src)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def build(layers, wall, heel_wall, roof_y, half_toe=False):
    """The meshes of the docstring; ``layers`` = (y or y(x), +1 up / -1 down) sheets; ``half_toe`` puts every point
    at x >= 0.13 at half its height ([G])."""
    P, F = [], []

    def tri(a, b, c, up):
        a, b, c = (np.asarray(v, np.float64) for v in (a, b, c))
        if np.dot(np.cross(b - a, c - a), up) < 0:
            b, c = c, b
        n = len(P)
        P.extend([a, b, c])
        F.append((n, n + 1, n + 2))

    def quad(p00, p10, p11, p01, up):
        tri(p00, p10, p11, up)
        tri(p00, p11, p01, up)

    xs = [round(0.01 * i, 10) for i in range(27)]
    for x0, x1 in zip(xs[:-1], xs[1:]):
        for y, s in layers:
            y0, y1 = (y(x0), y(x1)) if callable(y) else (y, y)
            quad((x0, y0, -HW), (x1, y1, -HW), (x1, y1, HW), (x0, y0, HW), (0, s, 0))
        wh = heel_wall if x0 < 0.04 - 1e-9 else wall
        for z, f in ((HW, 1), (-HW, -1)):
            quad((x0, 0, z), (x1, 0, z), (x1, wh, z), (x0, wh, z), (0, 0, f))
        if x0 >= 0.16 - 1e-9:
            quad((x0, roof_y, -HW), (x1, roof_y, -HW), (x1, roof_y, HW), (x0, roof_y, HW), (0, 1, 0))
    quad((0, 0, -HW), (0, heel_wall, -HW), (0, heel_wall, HW), (0, 0, HW), (-1, 0, 0))
    quad((L, 0, -HW), (L, wall, -HW), (L, wall, HW), (L, 0, HW), (1, 0, 0))
    P = np.asarray(P, np.float64)
    if half_toe:
        P[P[:, 0] >= 0.13 - 1e-9, 1] *= 0.5
    return P, np.asarray(F, np.int64)


#: The refusal text of the pinned old commit (A189 reworded the constant: open shoes are supported now).
OLD_OPEN_REFUSED = "Open shoes and sandals are not supported yet"


def main() -> int:
    from app.core import footwear_cut as fc
    from app.core import footwear_fit as ff
    from app.core import footwear_gates as fg
    from app.core import footwear_insole as fi
    tmp = Path(tempfile.mkdtemp(prefix="smoke_sole_layers_"))
    oi = old_module("app/core/footwear_insole.py", "old_footwear_insole", tmp)
    of = old_module("app/core/footwear_fit.py", "old_footwear_fit", tmp)

    print("[A] the flip needs a clear rise")
    PA, FA = build([(0.0, -1), (lambda x: 0.01 + 0.0016 * x / L, 1)], 0.05, 0.06, 0.05)
    a = fi.analyse_arrays(PA, FA)
    check("FLIP_MIN_SHARE / INSOLE_VERSION / MAX_HITS", (fi.FLIP_MIN_SHARE, fi.INSOLE_VERSION, fi.MAX_HITS), (0.01, 8, 48))
    check("A not flipped", a["frame"]["flipped"], False)
    check("A profile[24]", a["profile"][24], 0.01 + 0.0016 * 24 / 239, 1e-6)
    check("A profile[215]", a["profile"][215], 0.01 + 0.0016 * 215 / 239, 1e-6)
    check("A vamp_cover", a["vamp_cover"], 1.0, 1e-6)
    check("A gates", (a["gates"]["ok"], a["gates"].get("refusal")), (True, None))
    ao = oi.analyse_arrays(PA, FA)
    check(f"A on {OLD}: flipped, refused as open", (ao["frame"]["flipped"], ao["vamp_cover"], ao["gates"].get("refusal")),
          (True, 0.0, OLD_OPEN_REFUSED))

    print("[B] the open seed")
    sole = [(0.0, -1), (0.005, 1), (0.022, -1), (0.025, 1)]
    PB, FB = build(sole, 0.065, 0.075, 0.065)
    b = fi.analyse_arrays(PB, FB)
    prof = [v for v in b["profile"] if v is not None]
    check("B profile at every station", (len(prof), round(min(prof), 6), round(max(prof), 6)), (240, 0.025, 0.025))
    check("B cavity[200]", b["cavity"][200], 0.04, 1e-6)
    check("B cavity[120]", b["cavity"][120], None)
    check("B not flipped, gates", (b["frame"]["flipped"], b["gates"]["ok"]), (False, True))
    bo = oi.analyse_arrays(PB, FB)
    check(f"B on {OLD}: the plate's floor", (round(bo["profile"][132], 6), round(bo["cavity"][200], 6)), (0.005, 0.017))

    print("[C] MAX_HITS 48")
    sheets = [(y, s) for a0 in (0.007, 0.010, 0.013, 0.016) for y, s in ((a0, -1), (round(a0 + 0.001, 6), 1))]
    PC, FC = build(sole[:2] + sheets + sole[2:], 0.065, 0.075, 0.065)
    c = fi.analyse_arrays(PC, FC)
    check("C profile[132], cavity[200]", (round(c["profile"][132], 6), round(c["cavity"][200], 6)), (0.025, 0.04))
    check("C vamp_cover, gates", (c["vamp_cover"], c["gates"]["ok"]), (1.0, True))
    co = oi.analyse_arrays(PC, FC)
    check(f"C on {OLD}: the roof dropped", (co["cavity"][200], co["vamp_cover"], co["gates"].get("refusal")),
          (None, 0.0, OLD_OPEN_REFUSED))

    print("[D] the floor")
    got = [round(float(v), 6) for v in ff.foot_floor_m([0.0, 0.10, 0.36, 0.55, 0.70, 0.9, 0.23], 0.27)]
    check("D floor at L 0.27", got, [0.0108, 0.01998, 0.03996, 0.06507, 0.081, 0.081, 0.02997])

    print("[E] the vertical slimming's factor")
    side = types.SimpleNamespace(insole=lambda x: np.zeros_like(np.asarray(x, np.float64)),
                                 inner=lambda x: np.full_like(np.asarray(x, np.float64), 0.03),
                                 toe_clearance=0.002, toe_x=0.25, foot_len=0.25)
    xs = np.round(np.arange(0.10, 0.2505, 0.001), 6)
    C = np.array([[x, y, 0.0] for x in xs for y in (0.0, 0.05)])
    probe = np.array([[0.235, 0.05, 0.0], [0.175, 0.05, 0.0], [0.11, 0.05, 0.0]])
    C = np.vstack([C, probe])
    allv = np.ones(len(C), bool)
    f_v, info = fc._vslim_factors(side, C, allv, allv)
    check("E x 0.235", f_v[-3], 0.56, 1e-6)
    check("E x 0.175", f_v[-2], 0.654615, 1e-5)
    check("E x 0.11", f_v[-1], 1.0, 1e-9)
    check("E vslim_share", info["vslim_share"], 0.44, 1e-6)
    check("E vslim_floor_stations", info["vslim_floor_stations"], 31)

    print("[F] the toe box's reason")

    def record(u, agrees, needed=2.0):
        rec = {"scale": {"height_ready": True, "height_needed": {"left": needed, "right": round(needed - 0.1, 6)},
                         "height_worst": {"left": {"x_share": 0.7, "toe_share": u, "roof_mm": 24.6, "need_mm": 53.4,
                                                   "foot_mm": 51.4, "foot_raw_mm": 70.0}, "right": None}},
               "insole": {}}
        if agrees is not None:
            rec["insole"]["image"] = {"agrees": agrees}
        return rec
    high = "Foot too high for this shoe even after slimming (foot 51 mm, shoe 25 mm at {})"
    flat = "Shoe mesh too flat for the foot: toe box 25 mm, instep needs ~53 mm — regenerate the shoe"
    check("F agrees, u 0.3", ff.too_flat_reason(record(0.3, True)), high.format("the ball"))
    check("F no comparison, u 0.1", ff.too_flat_reason(record(0.1, None)), high.format("the toes"))
    check("F agrees, u 0.5", ff.too_flat_reason(record(0.5, True)), high.format("the instep"))
    check("F disagrees", ff.too_flat_reason(record(0.3, False)), flat)
    check("F under the cap", ff.too_flat_reason(record(0.3, True, needed=1.4)), None)
    check(f"F on {OLD}: the mesh named for an agreeing image", of.too_flat_reason(record(0.3, True)), flat)

    print("[G] the mesh against its image")
    sil = fg.side_silhouette(PB, FB, size=512)
    g1 = fg.image_agreement(PB, FB, sil)
    check("G own silhouette", (round(g1["mesh_iou"], 3), round(g1["toe_profile_ratio"], 3), g1["agrees"]),
          (1.0, 1.0, True))
    PF, FF = build(sole, 0.065, 0.075, 0.065, half_toe=True)
    g2 = fg.image_agreement(PF, FF, sil)
    check("G flattened toe: ratio", g2["toe_profile_ratio"], 0.5, 0.03)
    check("G flattened toe: IoU", g2["mesh_iou"], 0.013075 / 0.0173, 0.02)
    check("G flattened toe: disagrees", g2["agrees"], False)

    print("[H] the chain: [F14] (e)'s closed clog, slimmed")
    import _footwear_fixtures as fx
    from app.core import garment_footwear, glb_mesh
    real_body = fx.foot_body

    def tall(*args, **kw):
        Pt, Ft, Jt, Wt, Nt = real_body(*args, **kw)
        Pt = np.array(Pt, np.float64)
        Pt[(np.abs(Pt[:, 1] - fx.FOOT_H) < 1e-9) & (Pt[:, 0] <= 0.15 + 1e-9), 1] = 0.065
        return Pt, Ft, Jt, Wt, Nt
    fx.foot_body = tall
    try:
        body = fx.foot_body_glb()
    finally:
        fx.foot_body = real_body
    Pq, Fq = fx.clog()
    Pl, Fl = [tuple(v) for v in Pq], [tuple(f) for f in Fq]

    def quad(a0, b0, c0, d0):
        n = len(Pl)
        Pl.extend([a0, b0, c0, d0])
        Fl.extend([(n, n + 2, n + 1), (n, n + 3, n + 2)])
    xq = [round(0.1 + 0.0025 * i, 10) for i in range(34)]
    for x0, x1 in zip(xq[:-1], xq[1:]):
        quad((x0, 0.035, -0.04), (x1, 0.035, -0.04), (x1, 0.035, 0.04), (x0, 0.035, 0.04))
    quad((0.1825, 0.035, -0.04), (0.1825, 0.04, -0.04), (0.1825, 0.04, 0.04), (0.1825, 0.035, 0.04))
    P10, F10 = np.asarray(Pl, np.float64), np.asarray(Fl, np.int64)
    ins = fi.analyse_arrays(P10, F10)
    prep = glb_mesh.static_glb(P10, F10, np.zeros((len(P10), 2)))
    with tempfile.TemporaryDirectory() as td:
        out = garment_footwear.fit_compute(prep, ins, body, None, "footwear", "item_h", "h", td + "/fit.glb")
    sc = out["record"]["scale"]
    w = (sc.get("height_worst") or {}).get("left") or {}
    u = w.get("toe_share")
    check("H accepted at x1.5", (out["ok"], sc.get("height_factor")), (True, 1.5))
    check("H foot_mm = the floor at u", w.get("foot_mm"), 1000 * float(ff.foot_floor_m(u or 0.0, 0.25)), 0.01)
    check("H foot_raw_mm", w.get("foot_raw_mm"), 65.0, 0.01)
    check("H roof_mm", w.get("roof_mm"), 25.590, 0.01)
    conform = ((out["record"].get("gates") or {}).get("toe_conform_m") or {}).get("value")
    check("H toe_conform < 0.025", conform is not None and conform < 0.025 and conform < 0.028615, True)

    print("ALL PASS" if not FAILS else f"FAILED: {', '.join(FAILS)}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
