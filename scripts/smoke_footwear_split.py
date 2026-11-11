#!/usr/bin/env python3
"""Smoke: the split of a boot at the wearer's ankle (app/core/footwear_fit.py step 9, fit version 6; boots plan
docs/superpowers/plans/2026-11-11-footwear-boots-mens.md Task 6, spec
docs/superpowers/specs/2026-11-11-footwear-boots-mens-design.md § 6.2–6.4, § 9).

Usage:  ./.venv/bin/python scripts/smoke_footwear_split.py

No storage, no world DB, no hub, no server: numpy on the synthetic fixtures of scripts/_footwear_fixtures.py.
Body = ``foot_body_glb(leg_cell=0.01)``: the round-1 box feet (Foot at (0, 0.08, +-0.10), the sole on y = 0, the
heel contact at x = -0.04) with the leg column x in [-0.03, 0.03], z in zc +- 0.03, y in [0.10, 0.45], Leg 1.0,
tessellated in 1-cm cells (the voxel body field of the push needs a surface the sampler closes; the round-1
column of six quads leaks). Boot = ``flat_boot(shaft=0.16)``: the closed flat clog (insole 0.01 raw over
[0.01, 0.26], walls 0.035 / 0.04, roof 0.04) whose walls over x in [0, 0.10] rise to 0.16 in 1-cm rows, closed
by a back wall at x = 0 and a front wall at x = 0.10 — a tube on the clog.

The clog's fit on this foot is smoke_footwear_fit.py [F11] / smoke_footwear_fit_step.py [P1]: k = (0.25 + 0.005)
/ (0.26 - 0.0108787) = 1.023599, extension 0 (flat insole, flat foot), width factor 1.0380 (0.085 / 0.08 k),
lift +0.010236 = the insole height (the shoe ground sits one insole under the heel contact at y = 0).
Heights below are FRAME heights: metres above the shoe's ground = raw x k = body y + lift.

Expected, by hand:
[B1] split_height = (Foot joint 0.08 - floor 0) + lift 0.010236 = y_split 0.090236; band (0.070236, 0.110236);
     the boot's topline 0.16 k = 0.163776 > y_split + SPLIT_MARGIN_M 0.01 = 0.100236 -> a boot, split: parts
     foot + shaft per side, record split.is_boot, sides.<side>.split {y_m 0.090236, topline_m 0.163776,
     collar_above_ankle_mm 73.54} and diagnostics.<side>.collar_above_ankle_mm 73.54 (+-0.1). The clog alone:
     topline 0.05 k = 0.05118 -> collar -39.06 mm -> a shoe, parts["left"] has no "shaft", no shaft gates.
     Faces go to the part of their centroid: the foot part holds every face with centroid under y_split, the
     shaft part the rest; both parts together have the boot's 3348 faces (Task 6 fixture count); a band
     vertex appears in both parts with the same bind position and weights.
[B2] weights (the 8 nearest body vertices of a wall point BESIDE the shin, body x in [-0.03, 0.03], at body
     y >= 0.0717 are shin vertices — the dense leg's bottom edge 2.8 cm up at the row 0.08 vs the foot top
     5.2 cm down — Leg 1.0, so the clothing transfer's share is Leg 1 and the band's Foot + ToeBase is exactly
     1 - s; s = smoothstep((yf - 0.070236) / 0.04)): a shaft-wall vertex of raw row 0.05 (yf 0.05118) or 0.06
     -> Foot + ToeBase = 1 (+-1e-9); the top row 0.16 (yf 0.163776) -> Leg >= 0.95 (it is 1.0), Foot + ToeBase
     <= 0.05; the band rows beside the shin: raw 0.08 -> yf 0.081888, u 0.2913, s 0.20514 -> Foot + ToeBase
     0.79486; raw 0.09 -> yf 0.092124, u 0.5472, s 0.57059 -> 0.42941; raw 0.10 -> yf 0.102360, u 0.8031,
     s 0.89896 -> 0.10104 (+-2e-4 each: k is known to 1e-5). Behind the shin (the shaft runs to body x -0.0711)
     the foot top competes with the leg in the IDW at the row 0.08 and Foot rises to 0.87 — the body's own
     weights near the ankle — so the whole ring reads within [1 - s, 1]. (The plan's "Foot in [0.45, 0.60] at
     the band's middle 0.0902" has no vertex: the rows are 1 cm apart and the nearest, 0.092124, reads 0.429 —
     the exact 1 - s.) Anti-goal:
     no vertex above 0.110236 carries Foot + ToeBase > 0.05 (the row 0.11 at yf 0.112596 already has s = 1).
     No vertex carries a joint outside [Foot, ToeBase, Leg]; the parts' joint_names are those three (the
     fixture body has no UpLeg; a rig-contract body adds it as the fourth slot).
[B3] push: the leg column's half-width 0.03 against the shaft's inner half-width 0.04 k x 1.0380 = 0.042504
     -> gap 12.5 mm > SHAFT_CLEAR_M 6 mm -> push_max_m < 0.0002, inside_share 0. ``foot_body_glb(leg_half_w=
     0.045, leg_cell=0.01)``: the shin stands 2.5 mm INSIDE each side wall -> needed 0.045 + 0.006 - 0.042504
     = 0.0085 laterally for the rows inside the shin's height (body y >= 0.10: raw rows 0.11 .. 0.16, more than
     half of the moving vertices) -> push_p95_m >= 0.0085; push_max_m in [0.0085, 0.0120]: the row 0.11 sits
     2.4 mm above the box leg's bottom face and the field's gradient there points down, so a vertex at that
     edge can be pushed past the bottom face as well as the side, hypot(8.5, 8.4) = 12.0 mm at most (a real
     shin has no bottom face; the smoothing passes mix the two) — measured 10.8 / p95 9.3 mm; inside_share 0;
     every foot-part vertex (s = 0) unmoved: identical bind positions to the 0.03 fit (+-1e-12). (The plan's
     0.0102 took the inner half-width as 0.04 k = 0.0408 without the width factor, which widens the shaft
     too — it is one mesh.)
[B4] seams: seam_gap_p95_mm = p95 over the band vertices of |LBS(bind) in the stand - fitted position| = 0
     (+-1e-6) for the flat boot (theta 0) AND for the round-1 wedge pump with the shaft 0.26 on the same foot
     (theta 24.29 deg, k 0.8853, y_split 0.13614, split): the band's bind is the EXACT inverse of the blended
     skin matrix. (The spec's blend of inverses was measured first on that pump boot: its residual
     4 s(1-s) sin^2(theta/2) r — s(1-s) <= 0.25, r up to the heel counter's 0.065 m behind the ankle — read
     2.85 mm at p95, above the 2 mm gate; the exact inverse makes it 0.) seam_stretch_max at +-25 deg about the
     fit's axis: the flat boot's back wall stands at raw x = 0 -> body x = -0.04 - 0.030418 k = -0.0711, r =
     0.0711 from the ankle; a 25 deg plantarflexion lifts its Foot-weighted rows by 2 r sin 12.5 deg = 0.0308
     against the Leg-weighted rows: the 4-cm band compresses to 0.0092 (ratio 0.23 overall, the middle 1-cm
     row with smoothstep slope 1.5 x 0.0102 / 0.04 = 0.384 of the travel = 11.8 mm > 10 mm collapses) -> the
     largest per-face ratio (or its inverse) is >= 4 — far above the spec's start value 1.5 by geometry, which
     is why it is recorded (gates.seam_stretch_max.gating False, ok False) and does not refuse; the fit is
     accepted. shaft_leg_follow_deg <= 1 for the flat boot: the top ring (yf > y_split + 0.06 = 0.150236:
     rows 0.15, 0.16) is Leg 1.0 -> a 20 deg Leg-only turn turns it 20 deg -> 0 (the plan's bound asin(0.05
     sin 20 deg) = 0.98 deg for Leg >= 0.95).
[B5] the four nodes without a world: the parts grafted on the fixture body GLB with
     garment_footwear.node_name -> nodes garment_footwear_<item>_{left,right} + …_shaft, extras.garment.part
     "foot" / "shaft", the shaft nodes' material doubleSided True (graft's material_overrides), the foot nodes'
     False (the source material says so); glb_mesh.garment_arrays(prefix) raises on the foot name (two
     matches), exact=True returns it. foot_pose of the boot fit == foot_pose of the clog fit on the same foot
     (bones, root_lift_m, contacts: the split changes no pose; the boot's foot part IS the clog).
[B6] FOOTWEAR_FIT_VERSION 6; FIT_GATES has no "boot"; SHAFT_GATES = push p95 0.015 / max 0.030 / inside 0.01 /
     seam gap 2 mm / stretch 1.5 / follow 1 deg, SHAFT_GATING seam_stretch_max False and the rest True;
     SPLIT_BAND_M 0.02, SPLIT_MARGIN_M 0.01, SHAFT_CLEAR_M 0.006; the record's gates carry the six shaft
     entries for the boot and none for the clog.
(On 2a54cb70 — fit version 5 — FootwearFit has ``shoes`` and no ``parts``, FIT_GATES has ``boot`` and the flat
boot is refused BOOT_REFUSED: its topline stands 73.5 - 30 = 43.5 mm above the ankle + margin.)
[B7] fit version 7 (P2 Rulings 8a / 8b): the shaft transfer takes Leg and UpLeg only, and the follow measure has a
     ring or is None. Body A = ``foot_body_glb(shin_foot_weight=0.3, leg_cell=0.01)``: the leg column carries
     Foot 0.3 / Leg 0.7 like a real body's shin (Kai: Foot 0.45 at +2 cm, 0.07 at +7 cm above the ankle); the foot
     boxes are unchanged (the shin's 0.3 is under FOOT_WEIGHT_MIN), so k, lift and y_split are [B1]'s. The flat
     boot (shaft 0.16) on it: no vertex above the band (yf > 0.110236) carries Foot + ToeBase (max 0, gate 0.05;
     version 6 copied the shin's 0.3 into the whole shaft); the band rows beside the shin read exactly 1 - s
     (0.79486 / 0.42941 / 0.10104 as in [B2]; version 6 read 1 - 0.7 s = 0.856 / 0.601 / 0.371); the top row
     0.16 is Leg 1.0; the top ring (rows 0.15 / 0.16, follow_ring "top") turns 20 deg under the 20 deg Leg turn
     -> leg_follow_deg 0 (+-1e-6), gate ok (version 6: Leg 0.7 on the ring -> the blend 0.7 e^{i 20 deg} + 0.3
     has the argument atan2(0.7 sin 20, 0.7 cos 20 + 0.3) = 14.03 deg -> follow 5.97 deg > 1, refused). The fit
     is accepted; the parts' joints stay [Foot, ToeBase, Leg].
     Body B = the default body with ``flat_boot(shaft=0.13)``: topline 0.13 k = 0.133068 -> collar +42.83 mm ->
     split, but nothing stands above y_split + 0.06 = 0.150236 -> the ring is the shaft part's upper half: the
     shaft part is yf > 0.110236 (rows 0.11 / 0.12 / 0.13 at 0.112596 / 0.122832 / 0.133068), its middle
     (0.133068 + 0.110236) / 2 = 0.121652 -> rows 0.12 and 0.13, follow_ring "upper_half", ring_vertices > 0,
     Leg 1.0 -> follow 0, gate ok and gating. ``flat_boot(shaft=0.105)``: topline 0.107478 -> collar +17.24 mm
     -> split, yet its top row lies UNDER the band's top 0.110236 -> no shaft part vertex -> follow_ring None,
     leg_follow_deg None, ring_vertices 0, gates.shaft_leg_follow_deg {value None, ok None, gating True} and the
     fit is still accepted (FOLLOW_OPTIONAL: no measure is not a refusal). FOOTWEAR_FIT_VERSION 7,
     FOLLOW_RING_MIN 3.
(On 7b04e9f5 / 8efc6616 — fit version 6 — Body A's shaft carries Foot 0.3 above the band and its ring follows the
Leg turn by 14 deg, not 20: [B7] fails on both numbers; the 0.13 boot's record has no ``follow_ring`` and its
follow is a vacuous 0.0 over an empty ring.)
"""
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402

import _footwear_fixtures as fx  # noqa: E402

FAILS = []


def check(cond, label):
    print(("ok   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


def near(a, b, tol) -> bool:
    return a is not None and abs(float(a) - float(b)) <= tol


def smoothstep(u: float) -> float:
    u = min(1.0, max(0.0, u))
    return u * u * (3.0 - 2.0 * u)


def main() -> int:
    from app.core import footwear_fit as ff
    from app.core import footwear_insole, garment_footwear, glb_mesh

    # [B6]
    check(ff.FOOTWEAR_FIT_VERSION == 7 and "boot" not in ff.FIT_GATES and ff.SPLIT_BAND_M == 0.02
          and ff.SPLIT_MARGIN_M == 0.01 and ff.SHAFT_CLEAR_M == 0.006 and ff.FOLLOW_RING_MIN == 3
          and ff.FOLLOW_OPTIONAL == ("shaft_leg_follow_deg",), "[B6] version 7, no boot gate, split constants")
    check(ff.SHAFT_GATES == {"shaft_push_p95_m": ("max", 0.015), "shaft_push_max_m": ("max", 0.030),
                             "shaft_inside_share": ("max", 0.01), "seam_gap_p95_mm": ("max", 2.0),
                             "seam_stretch_max": ("max", 1.5), "shaft_leg_follow_deg": ("max", 1.0)}
          and ff.SHAFT_GATING == {"shaft_push_p95_m": True, "shaft_push_max_m": True, "shaft_inside_share": True,
                                  "seam_gap_p95_mm": True, "seam_stretch_max": False, "shaft_leg_follow_deg": True},
          "[B6] SHAFT_GATES + SHAFT_GATING")

    glb = fx.foot_body_glb(leg_cell=0.01)
    body = glb_mesh.body_arrays(glb)
    joints = glb_mesh.joint_bind_matrices(glb)
    Pb, Fb = fx.flat_boot(shaft=0.16)
    insole_b = footwear_insole.analyse_arrays(Pb, Fb)
    check(insole_b["gates"]["ok"] and insole_b["shaft"]["class"] == "ankle", "[B1] the flat boot's insole passes, class ankle")
    boot = ff.fit_pair(insole_b, fx.shoe_garment(Pb, Fb), body, joints)
    rec = boot.record
    k = rec["scale"]["k_m_per_unit"]
    lift = rec["sides"]["left"]["lift_m"]
    check(boot.ok and boot.reasons == [], f"[B1] the boot fit is accepted: ok {boot.ok}, reasons {boot.reasons}")
    check(near(k, 1.023599, 2e-5) and near(lift, 0.010236, 1e-5) and near(rec["scale"]["width_factor"], 1.0380, 2e-3),
          f"[B1] k {k:.6f}, lift {lift:.6f}, width factor {rec['scale']['width_factor']:.4f}")
    Pc, Fc = fx.clog()
    clog = ff.fit_pair(footwear_insole.analyse_arrays(Pc, Fc), fx.shoe_garment(Pc, Fc), body, joints)

    # [B1]
    fm = ff.measure_feet(body, joints)["left"]
    y_split = ff.split_height(fm, lift, float(body.positions[:, 1].min()))
    sp = rec["sides"]["left"]["split"]
    check(near(y_split, 0.090236, 1e-5) and near(sp["y_m"], y_split, 1e-7) and sp["is_boot"] is True
          and near(sp["topline_m"], 0.163776, 2e-5) and near(sp["collar_above_ankle_mm"], 73.54, 0.1)
          and near(rec["diagnostics"]["left"]["collar_above_ankle_mm"], 73.54, 0.1)
          and rec["split"] == {"is_boot": True, "band_m": 0.02, "margin_m": 0.01},
          f"[B1] y_split {sp['y_m']}, topline {sp['topline_m']}, collar {sp['collar_above_ankle_mm']} mm -> boot")
    check(all(sorted(boot.parts[s]) == ["foot", "shaft"] for s in ("left", "right")), "[B1] parts foot + shaft per side")
    cs = clog.record["sides"]["left"]["split"]
    check(clog.ok and cs["is_boot"] is False and near(cs["collar_above_ankle_mm"], -39.06, 0.1)
          and sorted(clog.parts["left"]) == ["foot"] and clog.record["split"]["is_boot"] is False
          and not any(g in clog.record["gates"] for g in ff.SHAFT_GATES),
          f"[B1] the clog: collar {cs['collar_above_ankle_mm']} mm -> a shoe, foot part only, no shaft gates")
    foot, shaft = boot.parts["left"]["foot"], boot.parts["left"]["shaft"]
    check(len(foot.indices) + len(shaft.indices) == len(Fb) == 3348
          and rec["sides"]["left"]["parts"] == {"foot": len(foot.indices), "shaft": len(shaft.indices)},
          f"[B1] faces: foot {len(foot.indices)} + shaft {len(shaft.indices)} = {len(Fb)}")
    yf_foot = foot.positions[foot.indices].mean(1)[:, 1] + lift
    yf_shaft = shaft.positions[shaft.indices].mean(1)[:, 1] + lift
    check(bool(np.all(yf_foot < y_split + 1e-9)) and bool(np.all(yf_shaft >= y_split - 1e-9)),
          "[B1] every foot face's centroid under y_split, every shaft face's at or above it")
    # shared band vertices: same position -> same weights in both parts
    from scipy.spatial import cKDTree
    d, j = cKDTree(foot.positions).query(shaft.positions)
    shared = d < 1e-12
    check(shared.sum() > 0 and np.allclose(shaft.weights[shared], foot.weights[j[shared]], atol=1e-12)
          and np.array_equal(shaft.joints[shared], foot.joints[j[shared]]),
          f"[B1] {int(shared.sum())} shared vertices carry identical weights in both parts")

    # [B2]
    allP = np.concatenate([foot.positions, shaft.positions])
    allW = np.concatenate([foot.weights, shaft.weights])
    allJ = np.concatenate([foot.joints, shaft.joints])
    names = foot.joint_names
    check(names == ["LeftFoot", "LeftToeBase", "LeftLeg"] and shaft.joint_names == names
          and set(np.unique(allJ[allW > 0]).tolist()) <= {0, 1, 2}, f"[B2] joints {names}, weight only on them")
    yf = allP[:, 1] + lift
    wall = np.abs(allP[:, 2] + 0.10) > 0.035
    ft = allW[:, 0] + allW[:, 1]

    def row(raw: float, beside: bool = False):
        sel = wall & (np.abs(yf - raw * k) < 2e-4) & (allP[:, 0] < 0.032)
        if beside:
            sel &= (allP[:, 0] >= -0.03) & (allP[:, 0] <= 0.03)
        return ft[sel], allW[sel, 2]
    for raw in (0.05, 0.06):
        f_, _l = row(raw)
        check(len(f_) > 0 and np.all(np.abs(f_ - 1.0) <= 1e-9), f"[B2] raw row {raw}: Foot + ToeBase = 1 ({len(f_)} vertices)")
    f_, l_ = row(0.16)
    check(len(f_) > 0 and l_.min() >= 0.95 and f_.max() <= 0.05, f"[B2] top row 0.16: Leg {l_.min():.4f}, Foot+Toe {f_.max():.4f}")
    for raw in (0.08, 0.09, 0.10):
        s = smoothstep((raw * 1.023599 - 0.070236) / 0.04)
        f_, _l = row(raw, beside=True)
        check(len(f_) > 0 and np.all(np.abs(f_ - (1.0 - s)) <= 2e-4),
              f"[B2] band row {raw} beside the shin: Foot + ToeBase {f_.min():.5f}..{f_.max():.5f} = 1 - s = {1 - s:.5f}")
        f_all, _l = row(raw)
        check(len(f_all) > len(f_) and f_all.min() >= 1.0 - s - 2e-4 and f_all.max() <= 1.0 + 1e-9,
              f"[B2] band row {raw} whole ring: Foot + ToeBase in [1 - s, 1] ({f_all.min():.5f}..{f_all.max():.5f})")
    above = yf > y_split + 0.02 + 1e-9
    check(above.any() and ft[above].max() <= 0.05, f"[B2] anti-goal: max Foot + ToeBase above the band {ft[above].max():.4f}")

    # [B3]
    sh = rec["sides"]["left"]["shaft"]
    check(sh["push_max_m"] < 0.0002 and sh["inside_share"] == 0.0,
          f"[B3] shin 0.03 vs wall 0.0425: push {sh['push_max_m']} m, inside {sh['inside_share']}")
    glb_w = fx.foot_body_glb(leg_half_w=0.045, leg_cell=0.01)
    wide = ff.fit_pair(insole_b, fx.shoe_garment(Pb, Fb), glb_mesh.body_arrays(glb_w), glb_mesh.joint_bind_matrices(glb_w))
    shw = wide.record["sides"]["left"]["shaft"]
    need = 0.045 + 0.006 - 0.04 * k * wide.record["scale"]["width_factor"]
    check(near(need, 0.0085, 1e-4) and 0.0085 <= shw["push_max_m"] <= 0.0120 and 0.0085 <= shw["push_p95_m"] <= 0.0120
          and shw["inside_share"] == 0.0 and wide.ok,
          f"[B3] shin 0.045: needed {need:.4f}, push max {shw['push_max_m']:.4f} / p95 {shw['push_p95_m']:.4f}, "
          f"inside {shw['inside_share']}, ok {wide.ok}")
    pin = (foot.positions[:, 1] + lift) < y_split - 0.02 - 1e-9
    wf_ = wide.parts["left"]["foot"]
    check(len(wf_.positions) == len(foot.positions) and np.allclose(wf_.positions[pin], foot.positions[pin], atol=1e-12),
          f"[B3] {int(pin.sum())} foot-part vertices unmoved by the push")
    gw = wide.record["gates"]
    check(all(gw[g]["ok"] and gw[g]["gating"] for g in ("shaft_push_p95_m", "shaft_push_max_m", "shaft_inside_share")),
          "[B3] the push gates pass and gate")

    # [B4]
    check(near(sh["seam_gap_p95_mm"], 0.0, 1e-6), f"[B4] flat boot seam gap {sh['seam_gap_p95_mm']} mm")
    Pw_, Fw_ = fx.wedge(shaft=0.26)
    pump = ff.fit_pair(footwear_insole.analyse_arrays(Pw_, Fw_), fx.shoe_garment(Pw_, Fw_), body, joints)
    ps = pump.record["sides"]["left"]
    check(ps["split"]["is_boot"] is True and near(ps["extension"]["deg"], 24.29, 0.05)
          and near(ps["split"]["y_m"], 0.13614, 5e-4) and near(ps["shaft"]["seam_gap_p95_mm"], 0.0, 1e-3),
          f"[B4] pump boot: theta {ps['extension']['deg']:.2f}, y_split {ps['split']['y_m']}, "
          f"seam gap {ps['shaft']['seam_gap_p95_mm']} mm (exact inverse)")
    g = rec["gates"]
    check(sh["seam_stretch_max"] >= 4.0 and math.isfinite(sh["seam_stretch_max"])
          and g["seam_stretch_max"]["ok"] is False and g["seam_stretch_max"]["gating"] is False and boot.ok,
          f"[B4] flat boot stretch at +-25 deg {sh['seam_stretch_max']:.1f} (recorded, not gating; fit ok {boot.ok})")
    check(sh["leg_follow_deg"] <= 1.0 and g["shaft_leg_follow_deg"]["ok"] and g["shaft_leg_follow_deg"]["gating"]
          and sh["ring_vertices"] > 0, f"[B4] leg follow {sh['leg_follow_deg']} deg over {sh['ring_vertices']} ring vertices")
    check(g["seam_gap_p95_mm"]["ok"] and g["seam_gap_p95_mm"]["gating"], "[B4] seam gap gates and passes")
    check(sorted(k_ for k_ in g if k_ in ff.SHAFT_GATES) == sorted(ff.SHAFT_GATES), "[B6] the record carries the six shaft gates")

    # [B5]
    item = "demo_boot"
    blob = glb
    for side in ("left", "right"):
        for part, mesh in boot.parts[side].items():
            blob = glb_mesh.graft(blob, mesh, name=garment_footwear.node_name(item, side, part),
                                  extras={"kind": "footwear", "item_id": item, "fsig": "f", "side": side, "part": part},
                                  material_overrides={"doubleSided": True} if part == "shaft" else None)
    gltf = json.loads(blob[20:20 + int.from_bytes(blob[12:16], "little")].decode("utf-8"))
    nodes = {n["name"]: n for n in gltf["nodes"] if str(n.get("name", "")).startswith(f"garment_footwear_{item}")}
    want = {f"garment_footwear_{item}_left", f"garment_footwear_{item}_right",
            f"garment_footwear_{item}_left_shaft", f"garment_footwear_{item}_right_shaft"}
    check(set(nodes) == want, f"[B5] four nodes {sorted(nodes)}")
    parts_of = {n: nodes[n]["extras"]["garment"]["part"] for n in nodes}
    check(parts_of == {f"garment_footwear_{item}_left": "foot", f"garment_footwear_{item}_right": "foot",
                       f"garment_footwear_{item}_left_shaft": "shaft", f"garment_footwear_{item}_right_shaft": "shaft"},
          f"[B5] extras.part {parts_of}")

    def double_sided(name: str) -> bool:
        prim = gltf["meshes"][nodes[name]["mesh"]]["primitives"][0]
        return bool(gltf["materials"][prim["material"]].get("doubleSided", False))
    check(double_sided(f"garment_footwear_{item}_left_shaft") and double_sided(f"garment_footwear_{item}_right_shaft")
          and not double_sided(f"garment_footwear_{item}_left") and not double_sided(f"garment_footwear_{item}_right"),
          "[B5] shaft nodes doubleSided, foot nodes not")
    try:
        glb_mesh.garment_arrays(blob, node_prefix=f"garment_footwear_{item}_left")
        check(False, "[B5] garment_arrays(prefix) raises on the foot name")
    except ValueError:
        check(True, "[B5] garment_arrays(prefix) raises on the foot name")
    back = glb_mesh.garment_arrays(blob, node_prefix=f"garment_footwear_{item}_left", exact=True)
    check(len(back.indices) == len(foot.indices) and len(back.joint_names) >= 3
          and not back.material.get("doubleSided", False), "[B5] garment_arrays(exact=True) returns the foot node")
    fp_boot = {k_: v for k_, v in boot.foot_pose.items()}
    fp_clog = {k_: v for k_, v in clog.foot_pose.items()}
    check(fp_boot == fp_clog, "[B5] foot_pose of the boot == the clog's (the split changes no pose)")

    # [B7] Body A: a shin with its own Foot share
    check(sh.get("follow_ring") == "top", f"[B7] the 0.16 boot's follow ring is the top ring ({sh.get('follow_ring')})")
    glb_a = fx.foot_body_glb(shin_foot_weight=0.3, leg_cell=0.01)
    body_a = glb_mesh.body_arrays(glb_a)
    fit_a = ff.fit_pair(insole_b, fx.shoe_garment(Pb, Fb), body_a, glb_mesh.joint_bind_matrices(glb_a))
    ra = fit_a.record
    check(fit_a.ok and near(ra["scale"]["k_m_per_unit"], k, 1e-9) and near(ra["sides"]["left"]["split"]["y_m"], y_split, 1e-7),
          f"[B7] body A: accepted {fit_a.ok} {fit_a.reasons}, k and y_split as [B1]")
    fa, sa = fit_a.parts["left"]["foot"], fit_a.parts["left"]["shaft"]
    Pa = np.concatenate([fa.positions, sa.positions])
    Wa = np.concatenate([fa.weights, sa.weights])
    check(fa.joint_names == ["LeftFoot", "LeftToeBase", "LeftLeg"], f"[B7] body A joints {fa.joint_names}")
    yfa = Pa[:, 1] + lift
    fta = Wa[:, 0] + Wa[:, 1]
    above_a = yfa > y_split + 0.02 + 1e-9
    check(above_a.any() and fta[above_a].max() <= 1e-9,
          f"[B7] body A: max Foot + ToeBase above the band {fta[above_a].max():.4f} (version 6: 0.3)")
    wall_a = np.abs(Pa[:, 2] + 0.10) > 0.035
    for raw in (0.08, 0.09, 0.10):
        s = smoothstep((raw * 1.023599 - 0.070236) / 0.04)
        sel = wall_a & (np.abs(yfa - raw * k) < 2e-4) & (Pa[:, 0] >= -0.03) & (Pa[:, 0] <= 0.03)
        check(sel.any() and np.all(np.abs(fta[sel] - (1.0 - s)) <= 2e-4),
              f"[B7] body A band row {raw} beside the shin: Foot + ToeBase {fta[sel].min():.5f}..{fta[sel].max():.5f} "
              f"= 1 - s = {1 - s:.5f} (version 6: {1 - 0.7 * s:.3f})")
    top_a = wall_a & (np.abs(yfa - 0.16 * k) < 2e-4) & (Pa[:, 0] < 0.032)
    check(top_a.any() and Wa[top_a, 2].min() >= 1.0 - 1e-9, f"[B7] body A top row: Leg {Wa[top_a, 2].min():.6f}")
    sha = ra["sides"]["left"]["shaft"]
    ga = ra["gates"]["shaft_leg_follow_deg"]
    check(sha["follow_ring"] == "top" and sha["ring_vertices"] > 0 and near(sha["leg_follow_deg"], 0.0, 1e-6)
          and ga["ok"] is True and ga["gating"] is True,
          f"[B7] body A follow {sha['leg_follow_deg']} deg over {sha['ring_vertices']} top-ring vertices (version 6: 5.97)")
    # [B7] Body B: a low collar -> the shaft's upper half; a collar inside the band -> no measure
    Pl, Fl = fx.flat_boot(shaft=0.13)
    low = ff.fit_pair(footwear_insole.analyse_arrays(Pl, Fl), fx.shoe_garment(Pl, Fl), body, joints)
    ls = low.record["sides"]["left"]
    gl = low.record["gates"]["shaft_leg_follow_deg"]
    check(low.ok and ls["split"]["is_boot"] is True and near(ls["split"]["collar_above_ankle_mm"], 42.83, 0.1),
          f"[B7] 0.13 boot: ok {low.ok}, collar {ls['split']['collar_above_ankle_mm']} mm -> split")
    check(ls["shaft"]["follow_ring"] == "upper_half" and ls["shaft"]["ring_vertices"] > 0
          and near(ls["shaft"]["leg_follow_deg"], 0.0, 1e-6) and gl["ok"] is True and gl["gating"] is True,
          f"[B7] 0.13 boot: follow {ls['shaft']['leg_follow_deg']} over the shaft's upper half "
          f"({ls['shaft']['follow_ring']}, {ls['shaft']['ring_vertices']} vertices)")
    Pn, Fn = fx.flat_boot(shaft=0.105)
    none_ = ff.fit_pair(footwear_insole.analyse_arrays(Pn, Fn), fx.shoe_garment(Pn, Fn), body, joints)
    ns = none_.record["sides"]["left"]
    gn = none_.record["gates"]["shaft_leg_follow_deg"]
    check(none_.ok and ns["split"]["is_boot"] is True and near(ns["split"]["collar_above_ankle_mm"], 17.24, 0.1),
          f"[B7] 0.105 boot: ok {none_.ok} {none_.reasons}, collar {ns['split']['collar_above_ankle_mm']} mm -> split")
    check(ns["shaft"]["follow_ring"] is None and ns["shaft"]["leg_follow_deg"] is None and ns["shaft"]["ring_vertices"] == 0
          and gn["value"] is None and gn["ok"] is None and gn["gating"] is True
          and none_.record["shaft"]["leg_follow_deg"] is None,
          f"[B7] 0.105 boot: no ring -> follow None, ok None ({ns['shaft']['follow_ring']}, {gn})")

    print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL PASS")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
