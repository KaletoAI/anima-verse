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
[I9] constants: INSOLE_VERSION 1, NOMINAL_LENGTH_M 0.26, STATIONS 240, AIR_SHARE 0.025, TOL_SHARE 0.035,
     INSOLE_GATES insole_cover min 0.80 / vamp_cover min 0.6, BOOT_MARGIN_M 0.03, the two refusal texts.
[I10] the pump with every up-facing triangle reversed (nothing faces up any more): no candidate anywhere ->
     no seed -> insole_cover 0.0 -> refused with INSOLE_REFUSED; the nominal numbers are None; no
     exception; JSON without NaN.
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
                        fi.BOOT_MARGIN_M),
          (1, 0.26, 240, 0.025, 0.035, 0.03))
    check("INSOLE_GATES", {k: v[:2] for k, v in fi.INSOLE_GATES.items()},
          {"insole_cover": ("min", 0.80), "vamp_cover": ("min", 0.6)})
    check("refusal texts", (fi.BOOT_REFUSED, fi.OPEN_REFUSED),
          ("Boots are not supported yet", "Open shoes and sandals are not supported yet"))

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
    check("version", pump["version"], 1)

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

    if FAILED:
        print(f"\n{len(FAILED)} check(s) failed: {FAILED}")
        sys.exit(1)
    print("\nALL PASS")


if __name__ == "__main__":
    main()
