#!/usr/bin/env python3
"""Smoke: the pure numpy insole, topline and type analysis of a shoe mesh (app/core/footwear_insole.py;
plan docs/superpowers/plans/2026-11-10-footwear-rigid-shoes.md, Task 5; spec
docs/superpowers/specs/2026-11-10-footwear-rigid-shoes-design.md § 5.4).

Usage:  ./.venv/bin/python scripts/smoke_footwear_insole.py

No storage, no world DB, no hub, no server: numpy on synthetic meshes only. The shoe is the wedge pump of
scripts/_footwear_fixtures.py (Y up, x heel -> toe, z lateral, length L = 0.26, width 0.08): sole top
h(x) = 0.09 on [0, 0.05], linear to 0.01 at 0.15, 0.01 on [0.15, 0.26], bottom 0; zero-thickness side walls
at z = +-0.04 up to h(x) + 0.03 every 0.01; a vamp roof at h(x) + 0.03 over x in [0.18, 0.26].

Grid: STATIONS = 240 stations x_i = i * L / 239 (spacing 0.0010879); lateral columns
int(240 * 0.08 / 0.26) = 73 over z in [-0.04, 0.04]. AIR = 0.025 L = 0.0065, TOL = 0.035 L = 0.0091.

Expected, by hand:
[I6] vertical_hits on ONE triangle (x, z, height) = (0,0,0), (1,0,0), (0,1,1) — the plane height = z:
     ray (0.25, 0.25) -> barycentric (0.5, 0.25, 0.25) -> height 0.25, normal_up = 1/sqrt(2) = 0.70711
     (the normal (0, 1, -1)/sqrt 2, up for this winding); ray (0.75, 0.75): x + z = 1.5 > 1 -> no hit.
[I1] the pump. Frame: PCA axis +x, the rear 15 % (0.12 high) is taller than the front (0.04) -> heel at
     x = 0, origin (0, 0, 0), x_axis (1, 0, 0), z_axis = x x up = (0, 0, 1), length_raw 0.26 -> k = 0.26 /
     0.26 = 1. Candidates: the sole top (normal_up 1, on the slope 0.01/sqrt(0.01^2 + 0.008^2) = 0.781
     > 0.3) with 0.03 >= AIR of air under the roof or nothing above; the roof (nothing above). Seeded at
     station int(0.55 * 240) = 132 (x = 0.14360, lowest candidate = the sole top), tracked both ways (the
     slope changes by at most 0.8 * 0.00109 per station << TOL) -> the insole is the sole top in EVERY
     column -> insole_cover = 1.0, profile = h(x).
     heel_seat_h = profile(0.04 / k) = 0.09; insole_ball_h = profile(0.62 L = 0.1612) = 0.01;
     heel_rise = 0.08; pitch = atan2(profile(0.026) - profile(0.1612), 0.52 L = 0.1352)
     = atan2(0.08, 0.1352) = 30.61 deg (+-0.1); shank_slope (median station slope over [0.04, 0.1612]:
     the slope part [0.05, 0.15] is 0.10 of the 0.1212) = -atan(0.8) = -38.66 deg (+-0.1).
     contacts (ground = the sole bottom 0 everywhere): heel_tip = the ground cells within 0.05 L = 0.013 of
     the rearmost ground x (stations 0..11) -> (5.5 * 0.0010879, 0, 0) = (0.005983, 0, 0); ball = ground
     cells within 0.013 of 0.1612 (stations 137..160) -> x = 148.5 * 0.0010879 = 0.16155, (0.16155, 0, 0);
     toe_tip = the last footprint station (0.26, 0, 0). (+-1e-6)
[I2] topline(0.10) = h(0.10) + 0.03 = 0.05 + 0.03 = 0.08 (both walls; interpolated between stations, exact on
     the linear part); at station 0 the wall's vertical edge in the plane x = 0 -> 0.09 + 0.03 = 0.12;
     shaft_h_raw = max topline = 0.12; cavity_end_x: every roofed station has 0.03 >= 0.015 between insole
     and roof -> the last insole station, 0.26 (Task 9's insole arc runs to it).
[I3] vamp_cover = (0.26 - 0.18) / (0.26 - 0.1612) = 0.810 (stations: 74 of the 91 at x >= 0.1612 lie
     under the roof -> 0.8132; +-0.02); gates ok, no refusal.
[I4] the same wedge rotated 180 deg about Y ((x, y, z) -> (-x, y, -z)): PCA +x, the taller end is now at
     t = 0 -> x_axis (-1, 0, 0), z_axis (0, 0, -1), the frame coordinates are the original ones -> identical
     numbers (profile, topline, covers, nominal, contacts within 1e-9); the overlay points (mesh coords) are
     the original's times (-1, 1, -1).
[I5] the sandal (roof only over [0.24, 0.26]) -> vamp_cover 0.02 / 0.0988 = 0.202 (19/91 = 0.2088; +-0.02)
     < 0.6 -> gates not ok, refusal OPEN_REFUSED.
[I7] the pump plus a vertical fin at z = 0 over [0.24, 0.26] up to 0.15: the provisional heel is the TOE
     end (0.15 > 0.12) -> shoe_frame gives x_axis (-1, 0, 0). After tracking the insole at 0.10 L (toe,
     0.01) is lower than at 0.90 L (heel, 0.09) -> flipped: frame x_axis (1, 0, 0), frame.flipped True, and
     every number equals [I1] (the fin is vertical -> no ray hit; it sits at z = 0 -> no topline side).
[I8] analyse(static_glb(pump)) equals analyse_arrays(pump) within float32 (1e-5) and is JSON without NaN.
(Every float in insole.json is rounded to 7 decimals, so the station-count checks hold to 1e-6.)
[I9] constants: INSOLE_VERSION 5 (the cap inside the opening; 4 = the tube ring rules, 3 = the shaft block, 2 = the outsole footprint), DOWN_MAX -0.3, NOMINAL_LENGTH_M 0.26, STATIONS 240, AIR_SHARE 0.025, TOL_SHARE 0.035,
     INSOLE_GATES insole_cover min 0.80 / vamp_cover min 0.6 / opening_share min 0.5, BOOT_MARGIN_M 0.03,
     the refusal texts (boot, open, solid).
[I11] the closed solid wedge (sole alone: side faces only up to h(x), no roof): the top faces up with nothing
     above -> the insole everywhere, insole_cover 1.0; the topline per station is the top edge h(x) = the
     profile -> no station has walls AIR = 0.0065 above the insole -> opening_share 0.0 < 0.5 -> refused with
     SOLID_REFUSED (vamp_cover is 0.0 too, but the solid reason wins: never the sandal message). The pump
     and the sandal have walls 0.03 >= AIR above the insole at every profile station -> opening_share 1.0.
[I10] the pump with every up-facing triangle reversed (nothing faces up any more): no candidate anywhere ->
     no seed -> insole_cover 0.0 -> refused with INSOLE_REFUSED; the nominal numbers are None; no
     exception; JSON without NaN.
[I12] the OUTSOLE footprint (boots plan docs/superpowers/plans/2026-11-11-footwear-boots-mens.md Task 2, spec
     docs/superpowers/specs/2026-11-11-footwear-boots-mens-design.md § 5 F5, § 6.1; INSOLE_VERSION 2):
     wedge(shaft=0.16, flare=0.06) — the shaft walls over x in [0, 0.10] rise to 0.16 and two flare walls lean
     out from z = +-0.04 at y = 0.05 to z = +-0.06 at y = 0.16. The lateral grid now spans the flare: nzc =
     int(240 x 0.12 / 0.26) = 110 columns over [-0.06, 0.06], spacing 0.12 / 109 = 0.0011009; the sole holds the
     columns |z| < 0.04: j = 19 .. 90 -> 72 columns (the first beyond 0.04 is j = 18 at -0.04019); the flare the
     columns |z| in (0.04, 0.06]: 18 per side (j = 91 .. 108) plus the end column at exactly +-0.06, whose ray
     meets the flare's top edge (the point-in-triangle test is edge-inclusive: it counts) -> 19 per side.
     Stations over the flare: x_i = i x 0.26 / 239 <= 0.10 -> i = 0 .. 91 = 92 stations. A vertical ray over
     a flare column hits the leaning wall at 0.05 .. 0.16: the wall's outward normal is (0.11, -0.02) / 0.1118
     in (z, y) -> normal_up -0.179, above DOWN_MAX -0.3 (not an underside) and below UP_MIN 0.3 (no insole
     candidate), so those cells are footprint-with-a-hit, no outsole, no insole.
     On 4e3ce6f6 (the shipped rule, footprint = every column with a hit) insole_cover = 72 x 240 / (72 x 240
     + 2 x 19 x 92) = 17280 / 20776 = 0.8317 (measured 0.8317289; the continuous value is 1 - 0.004 / 0.0248 =
     0.8387) and the outline reaches |z| = 0.06 — a flared shaft pushes a perfectly closed shoe towards the
     0.80 refusal and widens the cut polygon to the flare.
     The version-2 rule: footprint_ground = the columns whose LOWEST hit faces down (normal_up <= DOWN_MAX)
     = the 72 sole columns at every station (the sole bottom, normal (0, -1, 0)); insole_cover = insole cells
     WITHIN it /
     its cells = 17280 / 17280 = 1.0 (+-1e-9); footprint_ground share = 17280 / 20776 = 0.831729 (+-1e-6);
     footprint_outline over the ground footprint -> every station's lateral extent is the sole's
     |z| <= 0.03908 (never the flare's 0.059): max |z| of the outline 0.03908 (+-1e-6, = gz[90]). The plain
     wedge() reads footprint_ground 1.0, the same cover, outline and gates as [I1]-[I3] (its every column's
     lowest hit is the sole bottom) — the [I1]-[I3] numbers above are unchanged by this task. (The spec's first
     wording, "within GROUND_SHARE L of the ground", was rejected on the real Business Heels: a pump's waist
     and toe spring hang above the ground — footwear_insole's module docstring has the numbers.)

The SHAFT block (boots plan Task 5, spec 2026-11-11 § 6.1; INSOLE_VERSION 3; the plan's cases [I8]-[I11] are
[I13]-[I16] here — those labels were taken). The wedge's heel seat (profile at HEEL_SEAT_M / k = 0.04) is
h(0.04) = 0.09; the throat (the first roofed station in the front half) is x = 0.18; the vamp roof's highest
point in front of it is h(0.18) + 0.03 = 0.04; a slab is 0.01 L = 0.0026; the slabs run from the mesh's top
down to max(vamp top, seat + 0.07 / k) — the height a shaft begins to be one.
[I13] collar + class: wedge(shaft=0.16): the topline behind the throat tops at 0.16 (the shaft walls) ->
     collar_h_raw = 0.16 - 0.09 = 0.07 (the pump-shaped wedge's insole stands at 0.09 at the heel; measured
     against the HEEL SEAT, never the station under the wall's top: at station 91, x = 0.099, the insole is
     0.0508 and a per-station difference would read 0.109 — the heel rise, not the shaft); collar_h_nominal =
     0.07 x 0.26 / 0.26 = 0.07 -> class none (<= 0.07, the boundary case on purpose; classified on the
     7-decimal value insole.json stores, 0.16 - 0.09 is 0.07000000000000001 in binary). wedge(shaft=0.26) ->
     0.17 -> ankle; wedge(shaft=0.45) -> 0.36 -> knee; wedge(shaft=0.60) -> 0.51 -> overknee, refused with
     OVERKNEE_REFUSED (gate overknee = collar_h_nominal <= 0.48). top_raw = the shaft height in each case
     (+- one slab, 0.0026): the top slab lies AT the mesh's top and its ring is the walls' top edges.
[I14] slabs of wedge(shaft=0.26) above the vamp: the slabs start at max(0.04, 0.09 + 0.07) = 0.16 and run to
     0.26 — every slab between y 0.12 and 0.26 has x in [0, 0.10] (+- 0.005: the shaft walls' extent), z in
     [-0.04, 0.04], closed True (cut points in all four quadrants about the ring's bbox centre) -> closed_share
     1.0. wedge(shaft=0.26, open_side=True): above 0.09 (the sole's end face) only the -z wall is cut -> every
     point at z = -0.04 = the centre -> no quadrant -> every shaft slab open -> closed_share 0.0, top_raw None
     -> refused SHAFT_OPEN_REFUSED. (The topline of the open-sided wedge is the LOWER side, the pump's
     h(x) + 0.03: its collar reads 0.03, class none — the slab ceiling is the mesh's top, not the topline,
     which is how the one-sided wall is seen at all.)
[I15] wedge(shaft=0.26, cap=True): the cap is 10 x 8 quads = 160 up-facing triangles at y = 0.26 over
     x in [0, 0.10] x z in [-0.04, 0.04]. strip_cap removes the faces whose centroid lies within the top 2 % of
     the shaft height, 0.26 - 0.02 x (0.26 - 0.04) = 0.2556 .. up, and whose normal's up component is
     >= cos 30 deg = 0.866: exactly the 160 cap triangles (the walls are vertical, everything else lies below);
     cap_removed == 160 in the analysis, 0 after stripping; the insole and topline numbers (profile, topline,
     nominal, contacts, covers, collar, top_raw, closed_share) are identical with and without the cap — the
     cap is a candidate hit 0.17 above the heel's insole, farther than TOL from the track, and its edges at
     z = +-0.03 / 0.04 sit at the walls' own top height.
[I16] the shaft block of the plain wedge() (no shaft): class none, collar_h_raw = 0.12 - 0.09 = 0.03 (the
     wall height), slabs == [] (the mesh tops at 0.12 < 0.16), closed_share None (not gated), cap_removed 0;
     SHAFT_GATES shaft_closed_share min 0.9 / overknee max 0.48; the refusal texts.
(On 2a54cb70 — INSOLE_VERSION 2 — insole.json has no ``shaft`` block, ``strip_cap`` does not exist and
wedge(shaft=0.60) passes its gates: [I13]-[I16] fail there on the missing key.)
[I17] a closed ring is a TUBE (INSOLE_VERSION 4, P2 Ruling 8c — on the real P2 material the four-quadrant test read
     the Work Shoes' tongue and the Leather Boots' pull tab as the shaft top): closed = four quadrants AND the
     largest angular gap between neighbouring cut points about the bbox centre < RING_GAP_MAX_DEG 90 AND both bbox
     ranges >= RING_EXTENT_MIN_SHARE 0.10 x L = 0.026. Every slab carries ``gap_deg``.
     (a) wedge(shaft=0.26, shaft_ends=True) — the tube closed by a back wall (x = 0) and a front wall (x = 0.10):
     about the centre (0.05, 0) the neighbouring cut points on the -z wall at x = 0.04 and 0.05 stand at
     atan2(-0.04, -0.01) = -104.04 deg and -90 deg -> gap_deg <= 14.04 on every slab in [0.16, 0.26] (the
     triangles' diagonals add points in between), closed, closed_share 1.0, top_raw 0.26.
     (b) wedge(shaft=0.26, shaft_ends=True, open_side=True) — the U whose open side is the LONG one (the -z wall
     and the two end walls remain): the end walls reach z = +0.04 on both sides of the centre, so all four
     quadrants hold a point (the version-3 test read it closed), but the opening between the back wall's top
     corner (0, 0.04) at atan2(0.04, -0.05) = 141.34 deg and the front wall's (0.10, 0.04) at 38.66 deg is one
     gap of 102.68 deg (+- 0.05) >= 90 -> every slab open, closed_share 0.0, top_raw None, refused
     SHAFT_OPEN_REFUSED.
     (c) wedge(shaft=0.26, tab=True) — a 0.02 x 0.02 pull-tab loop on the top ring from 0.26 to 0.29: the slabs
     run from the mesh top 0.29 down every 0.0026; the 12 slabs above 0.26 (0.29 .. 0.2614) cut the tab alone:
     four quadrants, gap_deg <= 45 (eight points round a square), but the extent 0.02 < 0.026 -> open; the first
     shaft slab 0.29 - 12 x 0.0026 = 0.2588 is closed -> top_raw 0.2588 (version 3 read the tab top 0.29),
     closed_share 1.0 (the tab slabs lie above top_raw and do not count), cap_removed 0 (the tab's walls are
     vertical), collar_h_raw 0.17 (the tab at |z| <= 0.01 is inside the topline's lateral filter), class ankle.
     (d) [I14]'s plain wedge(shaft=0.26) — two parallel walls without end walls — stays closed: its gap is the
     open short side, 2 x atan(0.04 / 0.05) = 77.32 deg < 90 (+- 0.05), extent 0.10 x 0.08.
(On 7b04e9f5 / 8efc6616 — INSOLE_VERSION 3 — (b) reads closed_share 1.0 and passes, (c) top_raw 0.29, and no slab
carries gap_deg: [I17] fails there.)
[I18] a cap face lies INSIDE the opening (INSOLE_VERSION 5, the P2 carry to Task 9: on the real P2 material the
     height-band rule stripped the collar RIM — 161 of 161 faces on the Work Shoes, 142 on the Leather Boots, the
     rounded top of the wall thickness). wedge(shaft=0.26, cap=True, rim=0.01): the capped shaft of [I15] plus a flat
     collar rim — up-facing quads at y = 0.26 from |z| = 0.04 out to 0.05 along both walls over x in [0, 0.10],
     10 x 2 quads = 40 triangles (1428 faces = [I15]'s 1388 + 40). The cap band's floor is 0.26 - 0.02 x (0.26 -
     0.04) = 0.2556; the plane there cuts the two walls at z = +-0.04 over x in [0, 0.10] (no end walls: the ring
     is the two parallel lines), its inner loop sorted by angle about (0.05, 0) is the rectangle [0, 0.10] x
     [-0.04, 0.04]. The disc's 160 centroids (x in (0, 0.10), |z| <= 0.035) lie inside it -> cap_removed 160;
     the rim's 40 centroids at |z| = 0.045 lie outside -> kept: strip_cap removes 160, 40 up-facing faces remain
     at the top (centroid y > 0.2556, up component >= cos 30), their centroids at |z| = 0.04 + 0.01 / 3 and
     0.04 + 0.02 / 3 (the two triangles of each rim quad: 0.043333 / 0.046667, +- 1e-9); top_raw 0.26
     (the top slab's in-plane rim edges widen the bbox to +-0.05, the ring stays closed), closed_share 1.0,
     collar_h_raw 0.17 and class ankle as [I15]; the plain cap of [I15] still reads exactly 160 (every disc
     centroid inside, nothing else up-facing in the band) and the cap-free [I14] / [I17] fixtures 0.
(On 162963ca / 863a2726 — INSOLE_VERSION 4 — the same fixture reads cap_removed 200 and strip_cap takes the rim
with the disc: [I18] fails there.)
"""
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

FAILED = []


def check(label, got, expected):
    ok = got == expected
    print(f"  {'OK  ' if ok else 'FAIL'} {label}: {got!r}" + ("" if ok else f" (expected {expected!r})"))
    if not ok:
        FAILED.append(label)


def near(label, got, want, tol):
    ok = got is not None and math.isfinite(float(got)) and abs(float(got) - want) <= tol
    print(f"  {'OK  ' if ok else 'FAIL'} {label}: {got!r}" + ("" if ok else f" (expected {want} +- {tol})"))
    if not ok:
        FAILED.append(label)


def vec_near(label, got, want, tol):
    import numpy as np
    ok = got is not None and len(got) == len(want) and bool(np.all(np.abs(np.asarray(got, float)
                                                                         - np.asarray(want, float)) <= tol))
    print(f"  {'OK  ' if ok else 'FAIL'} {label}: {got!r}" + ("" if ok else f" (expected {want} +- {tol})"))
    if not ok:
        FAILED.append(label)


def arr(values):
    import numpy as np
    return np.array([np.nan if v is None else v for v in values], dtype=float)


def same_arrays(label, a, b, tol):
    import numpy as np
    a, b = arr(a), arr(b)
    ok = a.shape == b.shape and bool(np.all((np.isnan(a) & np.isnan(b)) | (np.abs(a - b) <= tol)))
    print(f"  {'OK  ' if ok else 'FAIL'} {label}" + ("" if ok else f": max diff {np.nanmax(np.abs(a - b))}"))
    if not ok:
        FAILED.append(label)


def interp(res, key, x):
    import numpy as np
    xs, ys = np.asarray(res["stations"], float), arr(res[key])
    ok = ~np.isnan(ys)
    return float(np.interp(x, xs[ok], ys[ok]))


def numbers(res):
    """The scalar outputs two analyses of the same shoe must agree on."""
    nom = res["nominal"]
    out = {"length_raw": res["length_raw"], "insole_cover": res["insole_cover"], "vamp_cover": res["vamp_cover"],
           "cavity_end_x": res["cavity_end_x"], "shaft_h_raw": res["shaft_h_raw"]}
    out.update({f"nominal.{k}": v for k, v in nom.items()})
    for name, p in (res.get("contacts") or {}).items():
        for axis, v in zip("xyz", p or []):
            out[f"contacts.{name}.{axis}"] = v
    return out


def same_numbers(label, a, b, tol):
    na, nb = numbers(a), numbers(b)
    bad = [k for k in na if (na[k] is None) != (nb.get(k) is None)
           or (na[k] is not None and abs(na[k] - nb[k]) > tol)]
    ok = not bad and set(na) == set(nb)
    print(f"  {'OK  ' if ok else 'FAIL'} {label}" + ("" if ok else f": {[(k, na[k], nb.get(k)) for k in bad]}"))
    if not ok:
        FAILED.append(label)


def strict_json(res) -> bool:
    try:
        json.dumps(res, allow_nan=False)
        return True
    except ValueError:
        return False


def main():
    import numpy as np
    from _footwear_fixtures import wedge
    from app.core import footwear_insole as fi
    from app.core import glb_mesh

    print("[I9] constants")
    check("constants", (fi.INSOLE_VERSION, fi.NOMINAL_LENGTH_M, fi.STATIONS, fi.AIR_SHARE, fi.TOL_SHARE,
                        fi.BOOT_MARGIN_M, fi.DOWN_MAX),
          (5, 0.26, 240, 0.025, 0.035, 0.03, -0.3))
    check("ring constants", (fi.RING_GAP_MAX_DEG, fi.RING_EXTENT_MIN_SHARE), (90.0, 0.10))
    check("INSOLE_GATES", {k: v[:2] for k, v in fi.INSOLE_GATES.items()},
          {"insole_cover": ("min", 0.80), "vamp_cover": ("min", 0.6), "opening_share": ("min", 0.5)})
    check("refusal texts", (fi.BOOT_REFUSED, fi.OPEN_REFUSED, fi.SOLID_REFUSED),
          ("Boots are not supported yet", "Open shoes and sandals are not supported yet",
           "Solid mesh: no shoe opening found"))

    print("[I6] vertical_hits on one triangle")
    tri_p = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 1.0]])   # frame (x, height, z)
    hits = fi.vertical_hits(tri_p, np.array([[0, 1, 2]]), np.array([0.25, 0.75]), np.array([0.25, 0.75]))
    check("shape", hits.shape, (2, 2, 12, 2))
    near("(0.25, 0.25) height", hits[0, 0, 0, 0], 0.25, 1e-12)
    near("(0.25, 0.25) |normal_up|", abs(hits[0, 0, 0, 1]), 1 / math.sqrt(2), 1e-12)
    check("(0.25, 0.25) one hit", int(np.sum(~np.isnan(hits[0, 0, :, 0]))), 1)
    check("(0.75, 0.75) no hit", bool(np.all(np.isnan(hits[1, 1]))), True)

    P, F = wedge()
    pump = fi.analyse_arrays(P, F)
    L = 0.26

    print("[I1] pump frame + nominal")
    fr = pump["frame"]
    vec_near("origin", fr["origin"], [0, 0, 0], 1e-9)
    vec_near("x_axis", fr["x_axis"], [1, 0, 0], 1e-9)
    vec_near("z_axis", fr["z_axis"], [0, 0, 1], 1e-9)
    check("not flipped", fr["flipped"], False)
    near("length_raw", pump["length_raw"], 0.26, 1e-9)
    check("grid", (len(pump["stations"]), len(pump["lateral"])), (240, 73))
    nom = pump["nominal"]
    near("k", nom["k"], 1.0, 1e-9)
    near("heel_seat_h_m", nom["heel_seat_h_m"], 0.09, 1e-6)
    near("insole_ball_h_m", nom["insole_ball_h_m"], 0.01, 1e-6)
    near("heel_rise_m", nom["heel_rise_m"], 0.08, 1e-6)
    near("pitch_deg", nom["pitch_deg"], math.degrees(math.atan2(0.08, 0.1352)), 0.1)
    near("pitch_deg = 30.61", nom["pitch_deg"], 30.61, 0.1)
    near("shank_slope_deg", nom["shank_slope_deg"], -math.degrees(math.atan(0.8)), 0.1)
    near("insole_cover", pump["insole_cover"], 1.0, 1e-9)
    near("profile(0.10)", interp(pump, "profile", 0.10), 0.05, 1e-6)
    dx = L / 239
    vec_near("contacts.heel_tip", pump["contacts"]["heel_tip"], [5.5 * dx, 0, 0], 1e-6)
    vec_near("contacts.ball", pump["contacts"]["ball"], [148.5 * dx, 0, 0], 1e-6)
    vec_near("contacts.toe_tip", pump["contacts"]["toe_tip"], [0.26, 0, 0], 1e-6)

    print("[I2] topline")
    near("topline(0.10)", interp(pump, "topline", 0.10), 0.08, 1e-6)
    near("topline station 0", pump["topline"][0], 0.12, 1e-6)
    near("shaft_h_raw", pump["shaft_h_raw"], 0.12, 1e-6)
    near("cavity_end_x", pump["cavity_end_x"], 0.26, 1e-6)

    print("[I3] vamp cover")
    near("vamp_cover", pump["vamp_cover"], 0.810, 0.02)
    near("vamp_cover (station count 74/91)", pump["vamp_cover"], 74 / 91, 1e-6)
    check("gates", (pump["gates"]["ok"], pump["gates"]["reasons"], pump["gates"].get("refusal")), (True, [], None))
    check("version", pump["version"], 5)
    near("pump footprint_ground", pump["footprint_ground"], 1.0, 1e-9)

    print("[I4] rotated 180 deg about Y")
    Pr, Fr = wedge(rotate_180=True)
    rot = fi.analyse_arrays(Pr, Fr)
    vec_near("rot x_axis", rot["frame"]["x_axis"], [-1, 0, 0], 1e-9)
    vec_near("rot z_axis", rot["frame"]["z_axis"], [0, 0, -1], 1e-9)
    same_numbers("rot numbers", rot, pump, 1e-9)
    for key in ("profile", "topline"):
        same_arrays(f"rot {key}", rot[key], pump[key], 1e-9)
    for key in ("insole", "topline"):
        a, b = np.asarray(rot["overlay"][key], float), np.asarray(pump["overlay"][key], float)
        ok = a.shape == b.shape and a.size > 0 and bool(np.all(np.abs(a - b * [-1, 1, -1]) <= 1e-9))
        check(f"rot overlay {key} = original * (-1, 1, -1)", ok, True)

    print("[I5] sandal")
    Ps, Fs = wedge(roof_from=0.24)
    sandal = fi.analyse_arrays(Ps, Fs)
    near("sandal vamp_cover", sandal["vamp_cover"], 0.202, 0.02)
    near("sandal vamp_cover (19/91)", sandal["vamp_cover"], 19 / 91, 1e-6)
    check("sandal refused", (sandal["gates"]["ok"], sandal["gates"].get("refusal")), (False, fi.OPEN_REFUSED))
    near("sandal insole_cover", sandal["insole_cover"], 1.0, 1e-9)

    print("[I7] fin: provisional heel wrong, flipped after tracking")
    Pf, Ff = wedge(fin=True)
    provisional = fi.shoe_frame(Pf, Ff)
    vec_near("provisional x_axis", provisional.x_axis.tolist(), [-1, 0, 0], 1e-9)
    fin = fi.analyse_arrays(Pf, Ff)
    vec_near("fin x_axis", fin["frame"]["x_axis"], [1, 0, 0], 1e-9)
    vec_near("fin origin", fin["frame"]["origin"], [0, 0, 0], 1e-9)
    check("fin flipped", fin["frame"]["flipped"], True)
    same_numbers("fin numbers", fin, pump, 1e-9)
    same_arrays("fin topline", fin["topline"], pump["topline"], 1e-9)

    print("[I11] closed solid wedge")
    Pc, Fc = wedge(solid=True)
    solid = fi.analyse_arrays(Pc, Fc)
    near("solid insole_cover", solid["insole_cover"], 1.0, 1e-9)
    near("solid opening_share", solid["opening_share"], 0.0, 1e-9)
    near("solid vamp_cover", solid["vamp_cover"], 0.0, 1e-9)
    check("solid refused", (solid["gates"]["ok"], solid["gates"].get("refusal")), (False, fi.SOLID_REFUSED))
    near("pump opening_share", pump["opening_share"], 1.0, 1e-9)
    near("sandal opening_share", sandal["opening_share"], 1.0, 1e-9)

    print("[I8] analyse(GLB bytes)")
    glb = glb_mesh.static_glb(P, F, np.zeros((len(P), 2)))
    from_glb = fi.analyse(glb)
    same_numbers("glb numbers", from_glb, pump, 1e-5)
    check("glb JSON strict", strict_json(from_glb), True)
    check("glb gates ok", from_glb["gates"]["ok"], True)

    print("[I10] nothing faces up")
    n_up = np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]])[:, 1]
    inside_out = fi.analyse_arrays(P, np.where((n_up > 0)[:, None], F[:, ::-1], F))
    check("inside-out cover", inside_out["insole_cover"], 0.0)
    check("inside-out refused", (inside_out["gates"]["ok"], inside_out["gates"].get("refusal")),
          (False, fi.INSOLE_REFUSED))
    check("inside-out nominal None", (inside_out["nominal"]["heel_seat_h_m"], inside_out["nominal"]["pitch_deg"]),
          (None, None))
    check("inside-out JSON strict", strict_json(inside_out), True)

    print("[I12] the outsole footprint under a flared shaft")
    Pz, Fz = wedge(shaft=0.16, flare=0.06)
    flared = fi.analyse_arrays(Pz, Fz)
    check("flare grid", (len(flared["stations"]), len(flared["lateral"])), (240, 110))
    near("flare insole_cover (insole over the OUTSOLE)", flared["insole_cover"], 1.0, 1e-9)
    near("flare footprint_ground share", flared["footprint_ground"], 17280 / 20776, 1e-6)
    oz = np.abs(np.asarray(flared["footprint_outline"], float)[:, 1])
    near("flare outline max |z| = the sole's edge column", float(oz.max()), 0.0390826, 1e-6)
    check("flare gates ok", (flared["gates"]["ok"], flared["gates"].get("refusal")), (True, None))
    near("flare shaft_h_raw", flared["shaft_h_raw"], 0.16, 1e-6)
    near("flare profile(0.10)", interp(flared, "profile", 0.10), 0.05, 1e-6)
    check("flare JSON strict", strict_json(flared), True)

    print("[I13] collar height and class")
    for shaft, collar, cls in ((0.16, 0.07, "none"), (0.26, 0.17, "ankle"), (0.45, 0.36, "knee"),
                               (0.60, 0.51, "overknee")):
        res = fi.analyse_arrays(*wedge(shaft=shaft))
        sh = res["shaft"]
        near(f"shaft {shaft} collar_h_raw", sh["collar_h_raw"], collar, 1e-6)
        near(f"shaft {shaft} collar_h_nominal", sh["collar_h_nominal"], collar, 1e-6)
        check(f"shaft {shaft} class", sh["class"], cls)
        near(f"shaft {shaft} top_raw", sh["top_raw"], shaft, 0.0026)
        check(f"shaft {shaft} refusal", (res["gates"]["ok"], res["gates"].get("refusal")),
              (cls != "overknee", fi.OVERKNEE_REFUSED if cls == "overknee" else None))
        check(f"shaft {shaft} JSON strict", strict_json(res), True)
    near("shaft 0.60 overknee metric", fi.analyse_arrays(*wedge(shaft=0.60))["gates"]["overknee"], 0.51, 1e-6)

    print("[I14] tube slabs and the closed share")
    boot = fi.analyse_arrays(*wedge(shaft=0.26))
    slabs = [s for s in boot["shaft"]["slabs"] if 0.12 <= s["y"] <= 0.26 + 1e-9]
    check("boot has slabs above 0.12", len(slabs) >= 2, True)
    check("boot slabs closed", all(s["closed"] for s in slabs), True)
    check("boot slabs x in [0, 0.10]", all(abs(s["x_min"]) <= 0.005 and abs(s["x_max"] - 0.10) <= 0.005
                                           for s in slabs), True)
    check("boot slabs z in [-0.04, 0.04]", all(abs(s["z_min"] + 0.04) <= 1e-6 and abs(s["z_max"] - 0.04) <= 1e-6
                                               for s in slabs), True)
    near("boot closed_share", boot["shaft"]["closed_share"], 1.0, 1e-9)
    near("boot slab step 0.0026", slabs[0]["y"] - slabs[1]["y"], 0.0026, 1e-9)
    near("boot top slab at the mesh top", boot["shaft"]["slabs"][0]["y"], 0.26, 1e-9)
    hole = fi.analyse_arrays(*wedge(shaft=0.26, open_side=True))
    check("open side: every slab open", (len(hole["shaft"]["slabs"]) >= 2,
                                         all(not s["closed"] for s in hole["shaft"]["slabs"])), (True, True))
    near("open side closed_share", hole["shaft"]["closed_share"], 0.0, 1e-9)
    check("open side top_raw None", hole["shaft"]["top_raw"], None)
    check("open side refused", (hole["gates"]["ok"], hole["gates"].get("refusal")), (False, fi.SHAFT_OPEN_REFUSED))
    check("open side class none (the topline is the lower side)", hole["shaft"]["class"], "none")
    check("open side JSON strict", strict_json(hole), True)

    print("[I15] cap detection and removal")
    Pcap, Fcap = wedge(shaft=0.26, cap=True)
    Pb, Fb = wedge(shaft=0.26)
    check("cap fixture: 160 more faces", len(Fcap) - len(Fb), 160)
    capped = fi.analyse_arrays(Pcap, Fcap)
    check("capped cap_removed", capped["shaft"]["cap_removed"], 160)
    check("uncapped cap_removed", boot["shaft"]["cap_removed"], 0)
    P2, F2, removed = fi.strip_cap(Pcap, Fcap, capped)
    check("strip_cap removed", removed, 160)
    check("strip_cap faces", len(F2), len(Fcap) - 160)
    n_up = np.cross(P2[F2[:, 1]] - P2[F2[:, 0]], P2[F2[:, 2]] - P2[F2[:, 0]])
    n_up = n_up[:, 1] / np.linalg.norm(n_up, axis=1)
    cy = P2[F2].mean(1)[:, 1]
    check("strip_cap: nothing up-facing left at the top", int(((cy > 0.2556) & (n_up >= 0.866)).sum()), 0)
    check("strip_cap keeps the walls' top edges", bool(np.isclose(P2[np.unique(F2), 1].max(), 0.26)), True)
    stripped = fi.analyse_arrays(P2, F2)
    check("stripped cap_removed 0", stripped["shaft"]["cap_removed"], 0)
    same_numbers("capped numbers = uncapped", capped, boot, 1e-9)
    same_numbers("stripped numbers = uncapped", stripped, boot, 1e-9)
    for key in ("profile", "topline"):
        same_arrays(f"capped {key}", capped[key], boot[key], 1e-9)
    for key in ("collar_h_raw", "top_raw", "closed_share"):
        near(f"capped shaft.{key}", capped["shaft"][key], boot["shaft"][key], 1e-9)
    check("capped class ankle", capped["shaft"]["class"], "ankle")
    check("capped gates ok", (capped["gates"]["ok"], capped["gates"].get("refusal")), (True, None))
    P3, F3, removed3 = fi.strip_cap(Pb, Fb, boot)
    check("strip_cap on a cap-free boot: nothing", (removed3, len(F3) == len(Fb)), (0, True))

    print("[I16] the plain pump's shaft block")
    sh = pump["shaft"]
    check("pump class", sh["class"], "none")
    near("pump collar_h_raw", sh["collar_h_raw"], 0.03, 1e-6)
    check("pump slabs", sh["slabs"], [])
    check("pump closed_share None", sh["closed_share"], None)
    check("pump top_raw None", sh["top_raw"], None)
    check("pump cap_removed", sh["cap_removed"], 0)
    check("pump gates carry the shaft metrics", (pump["gates"]["shaft_closed_share"], pump["gates"]["overknee"]),
          (None, 0.03))
    check("SHAFT_GATES", {k: v[:2] for k, v in fi.SHAFT_GATES.items()},
          {"shaft_closed_share": ("min", 0.9), "overknee": ("max", 0.48)})
    check("shaft refusal texts", (fi.OVERKNEE_REFUSED, fi.SHAFT_OPEN_REFUSED),
          ("Over-knee boots are not supported yet", "The boot shaft is not closed"))
    check("class table", fi.SHAFT_CLASS_M, {"none": 0.07, "ankle": 0.22, "knee": 0.48})

    print("[I17] a closed ring is a tube: angular gap and extent")
    tube = fi.analyse_arrays(*wedge(shaft=0.26, shaft_ends=True))
    tube_slabs = [s for s in tube["shaft"]["slabs"] if 0.16 - 1e-9 <= s["y"] <= 0.26 + 1e-9]
    check("(a) tube slabs", len(tube_slabs) >= 2, True)
    check("(a) tube slabs closed, gap <= 14.04", all(s["closed"] and s["gap_deg"] <= 14.04 + 0.01 for s in tube_slabs), True)
    near("(a) tube closed_share", tube["shaft"]["closed_share"], 1.0, 1e-9)
    near("(a) tube top_raw", tube["shaft"]["top_raw"], 0.26, 1e-9)
    check("(a) tube gates ok", (tube["gates"]["ok"], tube["gates"].get("refusal")), (True, None))
    u = fi.analyse_arrays(*wedge(shaft=0.26, shaft_ends=True, open_side=True))
    u_slabs = [s for s in u["shaft"]["slabs"] if 0.16 - 1e-9 <= s["y"] <= 0.26 + 1e-9]
    check("(b) U slabs", len(u_slabs) >= 2, True)
    check("(b) U: four quadrants but one gap of 102.68 deg", all(not s["closed"] and abs(s["gap_deg"] - 102.68) <= 0.05
                                                                for s in u_slabs), True)
    # the one-sided U yaws the PCA frame by 2.2 deg: the extents are the tube's to 5 mm, not to the micron
    check("(b) U: x / z extent of the tube", all(abs(s["x_min"]) <= 0.005 and abs(s["x_max"] - 0.10) <= 0.005
                                                   and abs(s["z_max"] - s["z_min"] - 0.08) <= 0.005
                                                   for s in u_slabs), True)
    near("(b) U closed_share", u["shaft"]["closed_share"], 0.0, 1e-9)
    check("(b) U top_raw None", u["shaft"]["top_raw"], None)
    check("(b) U refused", (u["gates"]["ok"], u["gates"].get("refusal")), (False, fi.SHAFT_OPEN_REFUSED))
    tabbed = fi.analyse_arrays(*wedge(shaft=0.26, tab=True))
    tab_slabs = [s for s in tabbed["shaft"]["slabs"] if s["y"] > 0.26 + 1e-9]
    check("(c) 12 tab slabs above 0.26", len(tab_slabs), 12)
    near("(c) top slab at the tab top", tabbed["shaft"]["slabs"][0]["y"], 0.29, 1e-9)
    check("(c) tab slabs: closed by gap, open by extent", all(not s["closed"] and s["gap_deg"] <= 45.0 + 0.01
                                                             and abs(s["x_max"] - s["x_min"] - 0.02) <= 1e-6
                                                             and abs(s["z_max"] - s["z_min"] - 0.02) <= 1e-6
                                                             for s in tab_slabs), True)
    near("(c) top_raw = the first shaft slab 0.2588", tabbed["shaft"]["top_raw"], 0.29 - 12 * 0.0026, 1e-9)
    near("(c) closed_share", tabbed["shaft"]["closed_share"], 1.0, 1e-9)
    check("(c) cap_removed 0", tabbed["shaft"]["cap_removed"], 0)
    near("(c) collar_h_raw", tabbed["shaft"]["collar_h_raw"], 0.17, 1e-6)
    check("(c) class ankle, gates ok", (tabbed["shaft"]["class"], tabbed["gates"]["ok"]), ("ankle", True))
    check("(c) JSON strict", strict_json(tabbed), True)
    check("(d) [I14] plain walls: gap 77.32 deg, closed", all(s["closed"] and abs(s["gap_deg"] - 77.32) <= 0.05
                                                             for s in slabs), True)

    print("[I18] a cap face lies inside the opening: the collar rim stays")
    Prim_, Frim = wedge(shaft=0.26, cap=True, rim=0.01)
    check("rim fixture: 40 more faces than the capped shaft", len(Frim) - len(Fcap), 40)
    rimmed = fi.analyse_arrays(Prim_, Frim)
    check("rim cap_removed 160 (the disc only)", rimmed["shaft"]["cap_removed"], 160)
    P4, F4, removed4 = fi.strip_cap(Prim_, Frim, rimmed)
    check("rim strip_cap removed 160", (removed4, len(F4)), (160, len(Frim) - 160))
    n4 = np.cross(P4[F4[:, 1]] - P4[F4[:, 0]], P4[F4[:, 2]] - P4[F4[:, 0]])
    n4 = n4[:, 1] / np.linalg.norm(n4, axis=1)
    c4 = P4[F4].mean(1)
    top_up = (c4[:, 1] > 0.2556) & (n4 >= 0.866)
    check("rim: 40 up-facing faces remain at the top", int(top_up.sum()), 40)
    rz = np.sort(np.unique(np.round(np.abs(c4[top_up, 2]), 9)))
    check("rim: the remaining top faces' centroids at |z| 0.043333 / 0.046667", rz.tolist(), [0.043333333, 0.046666667])
    check("rim top_raw 0.26, closed 1.0, class ankle", (rimmed["shaft"]["top_raw"], rimmed["shaft"]["closed_share"],
                                                        rimmed["shaft"]["class"]), (0.26, 1.0, "ankle"))
    near("rim collar_h_raw", rimmed["shaft"]["collar_h_raw"], 0.17, 1e-6)
    check("rim gates ok", (rimmed["gates"]["ok"], rimmed["gates"].get("refusal")), (True, None))
    check("the plain cap still reads 160", capped["shaft"]["cap_removed"], 160)
    check("CAP_RING_BINS 120", fi.CAP_RING_BINS, 120)

    if FAILED:
        print(f"\n{len(FAILED)} check(s) failed: {FAILED}")
        sys.exit(1)
    print("\nALL PASS")


if __name__ == "__main__":
    main()
