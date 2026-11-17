#!/usr/bin/env python3
"""Smoke: OPEN footwear (A189) — sandals, slides, strap shoes: the kind in the insole analysis
(app/core/footwear_insole.py), the open fit (app/core/footwear_fit.py step 4c) and the cut that cuts nothing
(app/core/footwear_cut.py).

Usage:  ./.venv/bin/python scripts/smoke_a189_open_footwear.py

No storage, no world DB, no hub, no server: numpy on synthetic meshes only (the body solid of the strap push is
built in memory).

The fixtures. The wedge pump and the feet are those of scripts/_footwear_fixtures.py (length L = 0.26, 240 stations
x_i = i L / 239; feet: a box x in [-0.06, 0.19] (length 0.25), y in [0, 0.02], width 0.085; heel contact at x -0.04
-> d_heel 0.02; rest pitch 0). The SLIDE is built here: a flat sole slab x in [0, 0.26], z in [-0.05, 0.05], y in
[0, 0.01] (top face up, bottom face down, four sides) and a band over x in [0.12, 0.20]: two walls at z = +-0.05
from the sole top up to 0.01 + r and a roof at 0.01 + r facing up (r = the roof height above the insole).

Expected, by hand:
[O0] constants: OPEN_TOE_MAX 0.15, OPEN_HEEL_MAX 0.5, TOE_FROM_SHARE 0.85, HEEL_WALL_SHARE 0.25; OPEN_GATES of the
     insole: insole_cover min 0.80, strap_share min 0.08, insole_step max 0.035 (= TOL_SHARE); the fit's OPEN_GATES:
     strap_inside_share max 0.02, strap_push_max_mm max 30, sole_cover min 0.90, sole_sink_mm max 8;
     OPEN_ALLOW_M 0.014, OPEN_EDGE_M 0.005, STRAP_CLEAR_M 0.002, OPEN_HEIGHT_CAP 2.0. INSOLE_VERSION stays 8,
     FOOTWEAR_FIT_VERSION 18, CUT_VERSION 7: a closed shoe's analysis, fit and cut are what they were.
[O1] the wedge pump (roof over [0.18, 0.26]) stays CLOSED: toe zone x >= 0.85 L = 0.221 (stations 204..239) all
     under the roof -> toe_cover 1.0; heel zone x <= 0.25 L = 0.065: walls 0.03 >= AIR 0.0065 at every station ->
     heel_wall 1.0; vamp_cover 74/91 = 0.813 >= 0.6. Its gates keep vamp_cover and opening_share and carry no
     strap_share.
[O2] the wedge "sandal" (roof only over [0.24, 0.26]) is now OPEN by its vamp: toe zone stations 204..239 = 36,
     roofed x >= 0.24 -> stations 221..239 = 19 -> toe_cover 19/36 = 0.5278 (not toe-open); heel_wall 1.0;
     vamp_cover 19/91 = 0.2088 < 0.6 -> low_vamp -> kind "open". Open gates: insole_cover 1.0; strap_share 1.0 (the
     walls stand above the insole at every station); insole_step = the steepest station step of h(x) / L =
     0.8 x (L / 239) / L = 0.8 / 239 = 0.003347 <= 0.035 -> ok, no refusal; the gates carry no vamp_cover.
[O3] the solid wedge (no walls, no roof): toe_cover 0, heel_wall 0 -> open; strap_share 0 < 0.08 -> refused with
     STRAPLESS_REFUSED.
[O4] the slide (r = 0.03): toe zone without a roof -> toe_cover 0 (toe-open); heel zone without walls ->
     heel_wall 0 (heel-open); kind "open". The band's stations: x in [0.12, 0.20] -> i from ceil(0.12 / 0.26 x 239 =
     110.3) = 111 to floor(0.20 / 0.26 x 239 = 183.8) = 183 -> 73 stations -> strap_share 73/240 = 0.3042 (+- one
     station each end: 0.0084). Flat insole -> insole_step 0; insole_cover 1.0 -> gates ok. vamp_cover = the forefoot
     stations 149..239 (91) under the roof, 149..183 = 35 -> 0.3846 (+- 0.012), kept at the top level only.
[O5] a lid over part of the opening is scripts/smoke_footwear_source.py [W] (two boxes, the profile 0.03 in the pit
     and 0.13 on the lid): since A189 that mesh is "open" by its vamp (0.1165 < 0.6) and refused by insole_step
     0.10 / 0.25 = 0.4 > 0.035 with the same SOLID_REFUSED — checked there, unchanged.
[O6] the slide r = 0.03 on the feet. One scale: the foot lies on the whole insole (arc 0.26, flat), OPEN_ALLOW_M
     shorter: k = (0.25 + 0.014) / 0.26 = 1.0153846 -> length 0.264 m. The heel contact sits (d_heel 0.02 +
     OPEN_EDGE_M 0.005) / k from the insole's rear end -> the heel's back 5 mm in from it, the toes
     0.264 - 0.005 - 0.25 = 0.009 -> toe room 9 mm. Flat insole, rest pitch 0 -> extension 0, toe counter 0. The
     insole stands 0.01 k = 0.010154 above the shoe ground -> lift 0.010154 both sides, asymmetry 0. Width: the foot
     0.085 on a sole 0.10 k = 0.1015 -> needed 0.837 -> factor 1.0, and every plantar vertex over the sole ->
     sole_cover 1.0, no widening (widened 1.0). Height: the roof 0.03 k = 30.5 mm over a foot 20 + 2 mm ->
     needed 0.022 / (0.03 k) = 0.7222 -> factor 1.0. Straps: the walls stand at +-50.8 mm, the foot's
     sides at +-42.5 mm, the roof 10.5 mm over the foot -> nothing nearer than 2 mm -> push 0, inside 0. The foot's
     sole lies ON the insole -> sole_sink 0. Every gate passes. The record says shoe_kind "open"; its cut is
     {open: True} with both sides' frames; apply_cut returns the SAME primitive object and zero stats; cut_gates is
     ok with no gates. The shoe is bound on Foot / ToeBase only (two joint names per side).
[O7] the slide r = 0.012 (a band lower than the foot): needed = 0.022 / (0.012 k) = 1.8056 <= cap 2.0 -> height
     factor 1.8056 (+- 0.002): the roof (12.2 mm above the insole at k, beyond the 3 + 8 mm weighting band -> full
     weight) is raised to 0.012 k x 1.8056 = 22.0 mm above the insole = the foot's 20 mm + the 2 mm clearance
     (+- 1.5 mm: the push may add a voxel's rounding). Nothing is left inside the skin: strap_inside_share 0; gates
     pass.
[O8] the closed pump on the same feet (the control): its record has no shoe_kind, its gates no strap_* / sole_*
     keys, its cut no "open" key and apply_cut removes faces (> 0) — a closed shoe still hides the foot.
"""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import _footwear_fixtures as fx  # noqa: E402
from app.core import footwear_cut as fc  # noqa: E402
from app.core import footwear_fit as ff  # noqa: E402
from app.core import footwear_insole as fi  # noqa: E402
from app.core import glb_mesh  # noqa: E402

FAILED = []


def check(name, got, want, tol=None):
    if tol is None:
        ok = got == want
    else:
        ok = got is not None and abs(got - want) <= tol
    print(f"  {'ok  ' if ok else 'FAIL'} {name}: {got!r}" + ("" if ok else f" (expected {want!r}"
                                                             + (f" ± {tol}" if tol is not None else "") + ")"))
    if not ok:
        FAILED.append(name)


def _quad(P, F, a, b, c, d, facing):
    """One quad a-b-c-d (two triangles) wound to face ``facing``."""
    a, b, c, d = (np.asarray(v, np.float64) for v in (a, b, c, d))
    base = len(P)
    P.extend([a, b, c, d])
    flip = np.dot(np.cross(b - a, c - a), np.asarray(facing, np.float64)) < 0
    for t in ((0, 1, 2), (0, 2, 3)):
        F.append(tuple(base + i for i in ((t[0], t[2], t[1]) if flip else t)))


def _box(P, F, x0, x1, y0, y1, z0, z1):
    _quad(P, F, (x0, y1, z0), (x1, y1, z0), (x1, y1, z1), (x0, y1, z1), (0, 1, 0))
    _quad(P, F, (x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1), (0, -1, 0))
    _quad(P, F, (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), (0, 0, -1))
    _quad(P, F, (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1), (0, 0, 1))
    _quad(P, F, (x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0), (-1, 0, 0))
    _quad(P, F, (x1, y0, z0), (x1, y0, z1), (x1, y1, z1), (x1, y1, z0), (1, 0, 0))


def slide(r=0.03):
    """The slide of the module docstring."""
    P, F = [], []
    _box(P, F, 0.0, 0.26, 0.0, 0.01, -0.05, 0.05)
    top = 0.01 + r
    for z, facing in ((-0.05, (0, 0, -1)), (0.05, (0, 0, 1))):
        _quad(P, F, (0.12, 0.01, z), (0.20, 0.01, z), (0.20, top, z), (0.12, top, z), facing)
    _quad(P, F, (0.12, top, -0.05), (0.20, top, -0.05), (0.20, top, 0.05), (0.12, top, 0.05), (0, 1, 0))
    return np.asarray(P), np.asarray(F, np.int64)


def fit_of(P, F, insole):
    glb = fx.foot_body_glb()
    body, joints = glb_mesh.body_arrays(glb), glb_mesh.joint_bind_matrices(glb)
    shoe = glb_mesh.GarmentMesh(positions=P, normals=None, uvs=np.zeros((len(P), 2)), indices=F,
                                joints=np.zeros((len(P), 4), np.int64), weights=np.zeros((len(P), 4)), joint_names=[])
    return ff.fit_pair(insole, shoe, body, joints), glb_mesh.body_primitive_arrays(glb), joints


def main() -> int:
    print("[O0] constants")
    check("kind limits", (fi.OPEN_TOE_MAX, fi.OPEN_HEEL_MAX, fi.TOE_FROM_SHARE, fi.HEEL_WALL_SHARE),
          (0.15, 0.5, 0.85, 0.25))
    check("insole OPEN_GATES", {k: v[:2] for k, v in fi.OPEN_GATES.items()},
          {"insole_cover": ("min", 0.80), "strap_share": ("min", 0.08), "insole_step": ("max", 0.035)})
    check("fit OPEN_GATES", ff.OPEN_GATES, {"strap_inside_share": ("max", 0.02), "strap_push_max_mm": ("max", 30.0),
                                           "sole_cover": ("min", 0.90), "sole_sink_mm": ("max", 8.0)})
    check("open fit constants", (ff.OPEN_ALLOW_M, ff.OPEN_EDGE_M, ff.STRAP_CLEAR_M, ff.OPEN_HEIGHT_CAP),
          (0.014, 0.005, 0.002, 2.0))
    check("versions unchanged", (fi.INSOLE_VERSION, ff.FOOTWEAR_FIT_VERSION, fc.CUT_VERSION), (8, 18, 7))

    print("[O1] the pump stays closed")
    pump = fi.analyse_arrays(*fx.wedge())
    check("pump kind", pump["kind"], "closed")
    check("pump toe_cover", pump["open"]["toe_cover"], 1.0, 1e-6)
    check("pump heel_wall", pump["open"]["heel_wall"], 1.0, 1e-6)
    check("pump gates keys", sorted(k for k in pump["gates"] if k not in ("ok", "reasons", "refusal")),
          ["insole_cover", "opening_share", "overknee", "shaft_closed_share", "vamp_cover"])

    print("[O2] the wedge sandal is open by its vamp")
    sandal = fi.analyse_arrays(*fx.wedge(roof_from=0.24))
    check("sandal kind", sandal["kind"], "open")
    check("sandal toe_cover 19/36", sandal["open"]["toe_cover"], 19 / 36, 1e-6)
    check("sandal heel_wall", sandal["open"]["heel_wall"], 1.0, 1e-6)
    check("sandal flags", (sandal["open"]["toe_open"], sandal["open"]["heel_open"], sandal["open"]["low_vamp"]),
          (False, False, True))
    check("sandal vamp_cover 19/91 (top level)", sandal["vamp_cover"], 19 / 91, 1e-6)
    check("sandal strap_share", sandal["gates"]["strap_share"], 1.0, 1e-6)
    check("sandal insole_step 0.8/239", sandal["gates"]["insole_step"], 0.8 / 239, 2e-6)
    check("sandal accepted", (sandal["gates"]["ok"], sandal["gates"]["refusal"]), (True, None))
    check("sandal gates carry no vamp_cover", "vamp_cover" in sandal["gates"], False)

    print("[O3] the solid wedge")
    solid = fi.analyse_arrays(*fx.wedge(solid=True))
    check("solid kind", solid["kind"], "open")
    check("solid strap_share", solid["gates"]["strap_share"], 0.0, 1e-9)
    check("solid refused", (solid["gates"]["ok"], solid["gates"]["refusal"]), (False, fi.STRAPLESS_REFUSED))

    print("[O4] the slide")
    Ps, Fs = slide()
    ins = fi.analyse_arrays(Ps, Fs)
    check("slide kind", ins["kind"], "open")
    check("slide toe_cover / heel_wall", (ins["open"]["toe_cover"], ins["open"]["heel_wall"]), (0.0, 0.0))
    check("slide flags", (ins["open"]["toe_open"], ins["open"]["heel_open"]), (True, True))
    check("slide strap_share 73/240", ins["gates"]["strap_share"], 73 / 240, 2 / 240 + 1e-9)
    check("slide insole_step", ins["gates"]["insole_step"], 0.0, 1e-9)
    check("slide insole_cover", ins["gates"]["insole_cover"], 1.0, 1e-9)
    check("slide vamp_cover 35/91", ins["vamp_cover"], 35 / 91, 0.012)
    check("slide accepted", (ins["gates"]["ok"], ins["gates"]["refusal"]), (True, None))
    check("slide not flipped", ins["frame"]["flipped"], False)

    print("[O6] the slide on the feet")
    res, prims, joints = fit_of(Ps, Fs, ins)
    rec = res.record
    k = (0.25 + 0.014) / 0.26
    check("fit ok", (res.ok, res.reasons), (True, []))
    check("shoe_kind", rec.get("shoe_kind"), "open")
    check("k", rec["scale"]["k_m_per_unit"], k, 1e-6)
    check("length_m", rec["scale"]["length_m"], 0.264, 1e-6)
    check("width factor / widened / height factor",
          (rec["scale"]["width_factor"], rec["scale"]["open"]["widened"], rec["scale"]["open"]["height_factor"]),
          (1.0, 1.0, 1.0))
    check("height needed", rec["scale"]["open"]["height_needed"]["left"], 0.022 / (0.03 * k), 2e-3)
    for side in ("left", "right"):
        s = rec["sides"][side]
        check(f"{side} extension deg", s["extension"]["deg"], 0.0, 1e-4)
        check(f"{side} lift", s["lift_m"], 0.01 * k, 1e-6)
        check(f"{side} toe room mm", s["toe_room_mm"], 9.0, 1e-3)
        check(f"{side} heel x (m from the insole's rear end)", rec["diagnostics"][side]["heel_x_m"], 0.025, 1e-6)
        o = s["open"]
        check(f"{side} strap push / inside", (o["strap_push_max_mm"], o["strap_inside_share"]), (0.0, 0.0))
        check(f"{side} sole_cover", o["sole_cover"], 1.0, 1e-9)
        check(f"{side} sole_sink_mm", o["sole_sink_mm"], 0.0, 1e-3)
        check(f"{side} joint names", len(res.parts[side]["foot"].joint_names), 2)
    g = rec["gates"]
    check("open gates in the record", sorted(n for n in g if n in ff.OPEN_GATES), sorted(ff.OPEN_GATES))
    check("every gate ok", all(v["ok"] for v in g.values()), True)
    cut = rec["cut"]
    check("cut open, both sides", (cut.get("open"), sorted(cut["sides"])), (True, ["left", "right"]))
    check("cut side keys", all({"frame", "foot_joint", "toe_joint"} <= set(d) for d in cut["sides"].values()), True)
    same, stats = fc.apply_cut(prims[0], cut, joints)
    check("apply_cut returns the same primitive", same is prims[0], True)
    check("apply_cut stats", (stats["removed_faces"], stats["bisected_faces"], stats["new_vertices"]), (0, 0, 0))
    cg = fc.cut_gates(prims[0], res.parts, cut, joints=joints, body_before=prims[0])
    check("cut_gates", (cg["ok"], cg["gates"], cg["marks"]), (True, {}, None))

    print("[O7] a band lower than the foot")
    Pl, Fl = slide(r=0.012)
    low = fi.analyse_arrays(Pl, Fl)
    res7, _prims, _joints = fit_of(Pl, Fl, low)
    r7 = res7.record
    check("fit ok", (res7.ok, res7.reasons), (True, []))
    check("height factor", r7["scale"]["open"]["height_factor"], 0.022 / (0.012 * k), 2e-3)
    check("strap inside", max(s["open"]["strap_inside_share"] for s in r7["sides"].values()), 0.0)
    # the roof in bind space (extension 0: the stand is the bind + nothing): its height above the foot's top 0.02
    roof_y = max(float(np.asarray(res7.parts[s]["foot"].positions)[:, 1].max()) for s in ("left", "right"))
    check("roof above the insole = the foot's sole plane y 0 (m)", roof_y, 0.022, 1.5e-3)

    print("[O8] the closed pump on the same feet")
    Pp, Fp = fx.wedge()
    res8, prims8, joints8 = fit_of(Pp, Fp, pump)
    r8 = res8.record
    check("no shoe_kind", "shoe_kind" in r8, False)
    check("no open gates", [n for n in r8["gates"] if n in ff.OPEN_GATES], [])
    check("no open scale block", "open" in r8["scale"], False)
    if res8.ok:
        check("cut not open", fc.is_open(r8["cut"]), False)
        _p, st8 = fc.apply_cut(prims8[0], r8["cut"], joints8)
        check("the closed cut removes foot faces", st8["removed_faces"] > 0, True)
    else:
        check("pump fit ok", res8.reasons, [])

    print("FAILED: " + ", ".join(FAILED) if FAILED else "ALL OK")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
