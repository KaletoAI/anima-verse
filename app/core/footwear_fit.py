"""The CPU fit of a rigid shoe onto a wearer's body (plan
``docs/superpowers/plans/2026-11-10-footwear-rigid-shoes.md`` Task 9, spec
``docs/superpowers/specs/2026-11-10-footwear-rigid-shoes-design.md`` § 5.5 steps 1–8, § 5.7, § 6.1).

A pure numpy port of the spike's ``bl_assemble2.py`` v3 (``~/claude-out/shoe-spike/src``), without
Blender. Every length is in the body's bind space (metres, Y up); the shoe comes in its mesher
coordinates and is read in the frame of its ``insole.json`` (``footwear_insole``: ``x`` heel -> toe,
``height`` up, ``z`` = x × up, i.e. to the shoe's right).

1. **Foot on the MESH** (``measure_feet``, fit version 5 — the rule of the boots spec
   ``docs/superpowers/specs/2026-11-11-footwear-boots-mens-design.md`` § 13.1): the vertices weighted >
   ``FOOT_WEIGHT_MIN`` to a side's Foot + ToeBase **and below the Foot joint's height** — the auto-weighted
   shins of the generated male bodies carry Foot weight up the leg (spec § 5 F2: 87–157 vertices above the
   ankle, the rearmost "foot" vertex 8 cm behind the ankle on Kai), and a heel band anchored there held
   nothing. The foot axis ``forward`` = the horizontal direction Foot head -> ToeBase head (the ToeBase tail
   is not in a GLB; the spike's tail sat 7 cm beyond the toes anyway). Length = the extent along it.
   Down-facing = normal up component < ``PLANTAR_NORMAL_MAX``. **Each contact band is read against its OWN
   lowest point**, never against the body's floor: heel contact = the down-facing vertices of the rear
   ``HEEL_BAND_M`` within ``CONTACT_BAND_H_M`` of the lowest of them (mean, height = their lowest), ball
   contact the same among the down-facing vertices within ``BALL_BAND_M`` of the ToeBase head along the
   axis. (Round 1 took the plantar vertices within ``PLANTAR_BAND_M`` of the floor — spec § 5 F1: the
   generated male bodies stand on the forefoot in the bind pose, the heel's underside 3.9–5.3 cm up, and
   no shoe could be measured on them.) ``plantar`` — the arch-gap diagnostic only — = the down-facing
   vertices within ``PLANTAR_BAND_M`` of the lower of the two contacts. Toe height = the height range of
   the vertices within ``TOE_BAND_M`` of the toe tip; rest pitch = the slope heel contact -> ball contact
   along the axis — POSITIVE for a heel-up bind pose, and the extension of step 3 (chord minus rest
   pitch) and the lift of step 5 are then legally NEGATIVE: a flat insole dorsiflexes such a foot and the
   root descends (spec § 13.2; Kai −3.7° / −5.8 mm, Rosi −12.4° / −20.8 mm on the synthetic Oxford).
2. **Scale** (one per pair): k = (the longer foot + ``ALLOW_M``) / the insole arc from the heel end to
   the cavity end, where the cavity end is recomputed at the real scale: the last profile station whose
   insole-to-roof gap (``insole["cavity"]`` x k) holds the taller toes; an unroofed station counts as
   open (unlimited) in the rear ``OPEN_THROAT_SHARE`` of the length and as closed in front of it. The
   spike's fixed-point iteration (``SCALE_ITERATIONS``) from k = foot / arc(0.9 L).
3. **Extension per side** = the 2-point chord minus the rest pitch: the heel contact sits on the insole
   ``d_heel_m`` from the heel end, the ball on the insole at the chord distance from it; the Foot turns
   by that angle about its lateral axis (horizontal, ⟂ the foot axis) at the ankle, toe down. The ToeBase
   turns back so the toes lie on the forepart slope (the insole slope over ``FOREPART_SPAN_M`` in front of
   the ball): its net pitch is the slope, its own turn ``-(extension + slope)``. (The spike turned it by
   ``-(extension - slope)``, i.e. the toes DOWN by an up-going slope — a sign slip; 1.6 / 0.2 deg on the
   Stilettos.) THE BALL IS THE SKINNED BALL (fit version 2): the plantar ball band skinned with Foot and
   ToeBase in the stand pose (mean xz, lowest y), not the bind contact carried rigidly by Foot — the
   counter-turn moves it 4–5 mm on the real material and the shoe has to meet the ball the clips show. The
   ball depends on the pose and the pose on the chord to the ball, so the extension is a fixed point:
   start from the rigid solve (``heel_ball_m``, ``rest_pitch_deg``), then repeat — pose, skin the ball,
   chord of the posed heel-ball distance, correct the extension by chord minus the posed heel-over-ball
   pitch — until the correction is under ``BALL_SOLVE_TOL_RAD`` (``BALL_SOLVE_STEPS`` at most; three
   turns on the real material).
4. **Placement** (posed, before the root lift): yaw = the horizontal direction heel -> ball after the
   extension; the shoe's insole heel point on the posed heel contact; the left foot gets the source, the
   right foot its mirror (the shoe's lateral axis negated). Then the footprint midline goes onto the
   insole midline (the spike's v2: a line fitted to (foot slab middle - insole middle) over
   ``MIDLINE_SLABS`` slabs from the heel contact to ``MIDLINE_PAST_BALL_M`` past the ball, the shoe turned
   and shifted by it) and the shoe is widened by ONE width factor for the pair, ``min(width_cap,
   max(1, needed))`` with needed = foot width / insole width at the ball (each side's needed is recorded;
   what the cap leaves is ``slim_needed`` = the share of the ball width the forefoot slimming of Task 14
   must take off). No vertical rest step (the spike's 3rd-percentile plantar rest moved 1 mm).
5. **Root lift** = the largest per-side lift that puts that side's shoe ground on the floor; the gate
   ``lift_asymmetry_mm`` bounds the other side's float.
6. **Mirror**: the right shoe = the left's mirror image, winding flipped so its faces face out again;
   normals transform with the inverse transpose (still outward).
7. **Rigid bind**: weights Foot (1 - w) / ToeBase w, ``w`` = smoothstep over ±``BLEND_M`` around the ball
   along the shoe axis; the bind position is the inverse skinning of the posed placement (so in the bind
   pose the shoe is turned back by the extension, spec § 6.3). No leg bone gets weight.
8. **The cut** (fit version 3): a fit that passed its gates carries ``record["cut"]`` =
   ``footwear_cut.cut_description`` — the geometric description (no vertex indices) of what the shoe hides of
   the body, per side in the shoe's frame on the Foot / ToeBase bones. The fit step (``garment_footwear.fit``)
   applies it to the fit GLB's body and runs ``footwear_cut.cut_gates``; the assembly applies it per tier.

9. **The split at the wearer's ankle** (fit version 6; boots spec
   ``docs/superpowers/specs/2026-11-11-footwear-boots-mens-design.md`` § 6.2–6.4). Per side ``y_split`` =
   ``split_height`` — the Foot joint above the SHOE's ground in the shod stand (F6: 108–157 mm on the measured
   material). A shoe whose topline (``shaft_h_raw`` × k) stands more than ``SPLIT_MARGIN_M`` above it is a BOOT
   and is split; else it is rigid as above (the round-1 ``boot`` refusal is retired, its value is the diagnostic
   ``collar_above_ankle_mm``). Parts by the vertex's frame height: ``foot`` below ``y_split − SPLIT_BAND_M``,
   ``shaft`` above ``y_split + SPLIT_BAND_M``, the band between with ``s`` = smoothstep across it. Weights =
   (1 − s) × the foot part's Foot / ToeBase + s × ``garment_fit.clothing_weights`` restricted to the side's Leg
   and UpLeg (fit version 7, spec § 6.3's anti-double-bend rule, P2 Ruling 8a: the IDW over the body's own
   weights — Leg over the shin, UpLeg near the knee — WITHOUT the Foot column; a real body carries Foot share far up
   the shin (0.45 at +2 cm, 0.07 at +7 cm above the ankle on Kai) and the version-6 transfer copied it into the
   shaft, which then bent twice — once at the band, once with every Foot turn above it. The band's Foot share is
   the foot part's term alone, so it falls from 1 to exactly 0 across the band and no vertex above the band
   carries Foot or ToeBase); the dense (Foot, ToeBase, Leg, UpLeg) weights are the four skin slots. Bind position of the band and
   shaft = the EXACT inverse of the blended skin matrix (Leg / UpLeg stand in the bind pose), so the stand pose
   reproduces the fitted position; the foot part keeps the ball blend's blend of inverses (byte-identical to
   version 5). The spec's blend of inverses for the band was measured first: its residual 4 s(1−s) sin²(θ/2) r
   reaches 2.9 mm (p95) at the heel counter of the 24° pump boot fixture — above the 2 mm the spec allows —
   so the exact inverse replaced it. The weights are a fixed point of two turns (the bind points depend on the
   Foot share). Before the weights the band and shaft are pushed off the shin:
   ``garment_fit.body_sdf`` of the body skinned to the shod stand over the shaft's bounds, ``push_out`` with
   ``SHAFT_CLEAR_M``; the foot part is pinned. The two served parts are the index buffer split at ``y_split`` by
   face centroid; a band face's vertices appear in both with identical positions and weights, so the nodes
   never crack. Measures per side (``sides.<side>.shaft``, worst side under ``shaft`` and ``gates``):
   ``push_p95_m`` / ``push_max_m`` / ``inside_share``; ``seam_gap_p95_mm`` = p95 over the band vertices of
   |LBS(bind) in the stand − fitted position| — 0 up to rounding with the exact inverse (a guard on the bind
   construction; at a flex other than the stand there is no fitted reference, and the two nodes share their
   vertices, so a gap between them is 0 by construction too); ``seam_stretch_max`` = the largest area ratio (or
   its inverse) of a band face at ±``SEAM_FLEX_DEG`` about the fit's axis against the stand (a 25° flex over
   the 4-cm band at 6 cm radius
   moves the foot side 2.6 cm against the Leg side: the band compresses to about a third behind the ankle
   and stretches in front — by geometry, which is why this measure is recorded and not gating until P2
   calibrates it, ``SHAFT_GATING``); ``leg_follow_deg`` = the shaft top ring's best-fit turn under a
   ``FOLLOW_TURN_DEG`` Leg-only skin turn against that turn (the anti-double-bend check; UpLeg and Foot shares
   drag it). The ring (``follow_ring``, P2 Ruling 8b) is the shaft above ``y_split + SHAFT_RING_ABOVE_M``
   (``"top"``); when fewer than ``FOLLOW_RING_MIN`` vertices stand there (a low collar — the Work Shoes end 2.8 cm
   above the split) it is the upper half of the shaft part (``"upper_half"``, from the middle between the band's
   top and the shaft's highest vertex up); with no ring at all the measure is ``None`` — recorded as such, not
   gated (``check_gates`` optional, ``ok`` None in the record), never a green 0.0. ``foot_pose`` is unchanged —
   the extension, the toe counter, the root lift and the contacts are the foot part's.

Gates (``FIT_GATES``, every one refuses a fit since version 3): ``ball_placement_mm`` (the
posed SKINNED ball of step 3 vs the shoe's chord ball point under the heel-anchored placement, before the
midline step — the residual of the fixed point plus whatever the chord's elevation misses; the spike read
the ball rigid on Foot, 4–5 mm off on the real material), ``lift_asymmetry_mm``,
``slim_needed``, ``stand_floor_mm`` (the lowest shoe point in the shod stand vs the floor — a BIND-pose
number; floor contact under clips is the renderer's shared ground measure, ``packages/scene-render``
``clipGround.ts``); a split fit adds ``SHAFT_GATES`` (step 9), each ``gating`` per ``SHAFT_GATING``.

The record's ``insole`` block also carries ``wall_top_raw`` — the shoe's wall top per station (raw units; the
lower of the two sides' top edges, every point farther than ``WALL_SIDE_M`` from the midline counted) — which
``footwear_cut.cut_description`` turns into the cut's cap; insole.json keeps only the analysis' topline.

**Calibration of the step-1 rule (fit version 5, 2026-11-11) — REAL material, offline, no hub.** Measured with
this module on read-only copies of the base bodies (mm above the body's lowest vertex; L / R). Kira
``base20d5701a`` (the clone body the round-1 heels were accepted on; ankle 111 / 107 mm): ``measure_feet`` reads
foot length 241.8 / 255.7, ``ball_width_m`` 91.4 / 99.7, rest pitch 7.22° / 9.96° (the shipped round-1 rule,
ad341e95: 91.4 / 99.7 and 7.31° / 10.28°), the heel's underside 23.2 / 27.2 mm up, ``d_heel_m`` 20.6 / 30.0
(23.4 / 34.3). The WHOLE ``fit_pair`` of the Business Heels source (``item_68c4d249/df44e2fa4177``) on her,
new vs shipped: k 0.227580 both, extension 28.705° / 23.858° vs 28.860° / 23.783° (−0.16° / +0.07°), lift
46.08 / 47.01 mm vs 46.19 / 46.97 (−0.11 / +0.04 mm), root lift 47.01 vs 46.97 (+0.04 mm), ball placement
0.000 both, ``stand_floor`` 0.0 both, boot −52.8 vs −52.7; the fit's ``foot_w_ball_mm`` (the foot's width in the
shoe frame at the solved ball) 90.8 / 99.9 vs 93.0 / 101.0 — the tighter ball band (within ``CONTACT_BAND_H_M``
of its lowest vertex instead of everything under 3 cm) moves the solved ball 6 mm back on the left — so
``slim_needed`` 0.107 vs 0.151 (limit 0.18), every gate passing in both. Kira's heels therefore refit on the CPU
(``garment_refit``) to the same shoe within 0.2° / 0.2 mm; the width at the ball is 2.2 / 1.0 mm narrower, the
cut's slimming share smaller. Kai ``base634402e5`` (ankle 136 / 139 mm): foot length 291.3 / 292.7, ball
107.2 / 109.0, rest pitch 9.99° / 10.41°, heel 38.7 / 42.6 mm up — the shipped rule raised "no plantar heel or
ball vertices" on him (spec § 5 F1; his heel's underside is above ``PLANTAR_BAND_M``). Rosi ``baseed6cab12``
(no offline copy; spec § 5, measured there with the same rule): 245 / 246 mm, 14.3° / 18.1°, 53 mm up. The
synthetic numbers are in ``scripts/smoke_footwear_fit.py`` [F9]–[F12].
**P1 acceptance of the boots round (Task 4, 2026-11-11) — Kai in the Business Shoes, REAL chain on the clone.**
``item_6cc8e8ae`` (a cap-toe Derby, 220×256 item image) through the item chain: Iris upscale ×2, the Qwen side-view
empty edit (accepted at aspect 2.418, no leg, ``iou_below_topline`` 0.919 — after the empty gate was calibrated for a
men's shoe, ``footwear_gates``: aspect upper bound 2.4 → 2.6, ``LEG_EXCESS_SHARE`` 0.05 → 0.12; the first two
deliveries read 2.448 / 2.430 and a throat 0.052 / 0.050 L above the low counter), cut-out 979 px, one UniForge
mesh (95 788 → 59 082 tris, ``mesh_iou`` 0.919, component 1.0), insole v2 (cover 0.930, vamp 0.809, opening 0.956,
pitch 6.9°, heel seat 2.5 cm, rise 1.5 cm). The fit on ``base634402e5`` (0 hub jobs): k 0.3161 (shoe 32.3 cm long,
11.2 wide), width factor 1.030 (needed 0.990 / 1.030, slim 0 / 0), extension **−2.70° / −3.18°** (rest pitch 9.99 /
10.41°, chord 7.05 / 6.88°, forepart slope 7.4 / 8.5° → toe turn −4.66 / −5.27°), lift **−3.8 / −7.1 mm**, root lift
**−3.8 mm** — the sign the spec's F3 predicted (−5.8 on the synthetic Oxford), toe room 27.3 / 24.2 mm, every gate
green: ball 0.000 mm, lift asymmetry 3.3 mm, ``stand_floor`` 0.0, boot −54.7 mm, ``deep_outside`` 0.40 %,
``visible_poke`` 0, ``throat_ledge`` 0.0 mm, ``toe_conform`` 17.6 mm. ``check_footwear.mjs`` on the served shod base
model (idle / walk, ``--bare``): still sole 0 / 3.3 mm, idle lower sole −1 mm, walk stance −1.9 … +3.5 mm, strikes
+3.5 / +3.0, heel-off ≥ −1.9 — inside the round-1 bands (idle −3 … +3, walk −3 … +13). The same chain on the live
Kira body (``base20d5701a`` sha cca1685751b7, which stands heel-up 14.8° / 13.7° with the heel 46 mm up and on which
the round-1 rule raised) is the next calibration point; the clone body of round 1 is no longer the live one.
"""
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.core import glb_mesh
from app.core.footwear_gates import check_gates

#: Bumped when the fit changes what it produces (part of the footwear fsig and
#: ``garment_fit.FIT_VERSION["footwear"]``).
#: 5: the foot below the ankle, each contact band against its own lowest point (step 1);
#: 6: a boot is split at the wearer's ankle — rigid foot part, clothing-weighted shaft, four nodes (step 9);
#: 7: the shaft transfer without the Foot column (no Foot / ToeBase above the band) and the follow measure over
#:    the shaft's upper half when the top ring is empty (P2 Rulings 8a / 8b).
FOOTWEAR_FIT_VERSION = 7
#: Toe room: the insole arc is the longer foot plus this (metres).
ALLOW_M = 0.005
#: Half-width of the Foot -> ToeBase smoothstep around the ball (metres).
BLEND_M = 0.015
#: The largest width factor a fit may apply (spec § 5.5), also the default cap.
WIDTH_CAP = 1.10
#: The smallest per-fit width cap override.
WIDTH_CAP_MIN = 1.00
#: The largest share of the ball width the forefoot slimming may take off (gate ``slim_needed``).
SLIM_MAX_SHARE = 0.18

#: name -> (kind, limit) — ``footwear_gates.check_gates`` kinds.
FIT_GATES: Dict[str, Tuple[str, Any]] = {
    "ball_placement_mm": ("max", 3.0),
    "lift_asymmetry_mm": ("max", 10.0),
    "slim_needed": ("max", 0.18),
    "stand_floor_mm": ("range", (-3.0, 3.0)),
}
#: The split (boots spec 2026-11-11 § 6.2): band half-width about the ankle, the margin a topline must clear the
#: ankle by to be a boot (the round-1 ``boot`` refusal at 3 cm is retired; its value is the diagnostic
#: ``collar_above_ankle_mm``), the shaft's clearance from the shin (§ 6.4: the hair clearance).
SPLIT_BAND_M = 0.02
SPLIT_MARGIN_M = 0.01
SHAFT_CLEAR_M = 0.006
#: The top ring the anti-double-bend check reads: shaft vertices this far above the split (§ 6.3); below this
#: many vertices the ring is empty and the measure falls back to the shaft's upper half, then to ``None``.
SHAFT_RING_ABOVE_M = 0.06
FOLLOW_RING_MIN = 3
#: The ankle flex the seam measures are taken at, and the Leg turn of the follow check (degrees).
SEAM_FLEX_DEG = 25.0
FOLLOW_TURN_DEG = 20.0
#: The shaft gates of a SPLIT fit (spec § 9 start values); a shoe carries none of them. ``gating`` per gate
#: (``SHAFT_GATING``): the stretch measure is recorded, not gating, until P2 calibrates it on real boots — a 25°
#: flex over a 4-cm band at the heel counter's 6 cm radius compresses the band to about a third by geometry, so
#: the start value 1.5 would refuse every boot (module docstring, step 9).
SHAFT_GATES: Dict[str, Tuple[str, Any]] = {
    "shaft_push_p95_m": ("max", 0.015),
    "shaft_push_max_m": ("max", 0.030),
    "shaft_inside_share": ("max", 0.01),
    "seam_gap_p95_mm": ("max", 2.0),
    "seam_stretch_max": ("max", 1.5),
    "shaft_leg_follow_deg": ("max", 1.0),
}
#: P2 numbers (boots round, 2026-11-11, the clone): Work Shoes on Kai (``base634402e5``) ACCEPTED — split 14.6 cm,
#: collar 28 / 29 mm above the ankle, push p95 8.3 mm / max 17.6 mm, inside 0, seam gap 0, stretch 50 / 58 (recorded),
#: follow 0.0 deg but VACUOUS under version 6: the collar ends 2.8 cm above the split, the ring above
#: ``SHAFT_RING_ABOVE_M`` is empty (``ring_vertices`` 0); the same Leg-turn measure over the shaft's upper half read
#: 13.4–13.8 deg because the version-6 shaft carried the body's own Foot share there (0.47 at +2 cm, 0.21 at +4 cm,
#: 0.14 at +5 cm above the ankle — the clothing transfer copied the skin, whose Foot share is still 0.07 at +7 cm and
#: 0.05 at +8 cm). Leather Boots on Kira (``base20d5701a``) REFUSED under version 6: slim_needed 0.256 (width needed
#: ×1.48 / ×1.43, insole ball width 66 mm against the foot's 98 / 93 mm, toe room −19 / −22 mm), push p95 22.8 mm,
#: follow 5.9 / 7.2 deg (ring 205 / 106 vertices at +6 cm), stretch 39 / 20 (recorded). Version 7 (Rulings 8a / 8b,
#: offline on the same material): Kira's follow 0.0 on the +6 cm ring, Kai's 0.0 over the shaft's upper half
#: (``follow_ring`` "upper_half"), the width and push refusals unchanged — those are the mesh's (fix-1 report).
SHAFT_GATING: Dict[str, bool] = {
    "shaft_push_p95_m": True, "shaft_push_max_m": True, "shaft_inside_share": True,
    "seam_gap_p95_mm": True, "seam_stretch_max": False, "shaft_leg_follow_deg": True,
}
#: The gates whose value may be ``None`` (no ring to measure): not a refusal, the record says ``ok`` None.
FOLLOW_OPTIONAL = ("shaft_leg_follow_deg",)
GATE_LABELS = {
    "ball_placement_mm": "the posed ball contact vs the shoe's ball point, worse side",
    "lift_asymmetry_mm": "difference of the two sides' lifts",
    "slim_needed": "share of the ball width the forefoot slimming must take off, worse side",
    "stand_floor_mm": "lowest shoe point in the shod stand above the floor",
    "shaft_push_p95_m": "p95 push of the shaft and band off the shin, worse side",
    "shaft_push_max_m": "largest push of the shaft and band off the shin, worse side",
    "shaft_inside_share": "share of shaft and band vertices still inside the body after the push, worse side",
    "seam_gap_p95_mm": "p95 residual of the band's blended inverse skinning in the stand, worse side",
    "seam_stretch_max": "largest area ratio of a band face at +-25 deg ankle flex, worse side",
    "shaft_leg_follow_deg": "the shaft top ring's turn against a 20 deg Leg turn, worse side",
}

#: Foot vertices: Foot + ToeBase weight above this (and below the Foot joint's height).
FOOT_WEIGHT_MIN = 0.5
#: Down-facing vertices: normal up component below this.
PLANTAR_NORMAL_MAX = -0.4
#: A contact band's vertices: the down-facing vertices within this height (metres) of the band's lowest one.
CONTACT_BAND_H_M = 0.01
#: The arch diagnostic's plantar set: the down-facing vertices within this height (metres) of the lower contact.
PLANTAR_BAND_M = 0.03
#: Heel contact: the down-facing vertices this far in front of the heel back (metres).
HEEL_BAND_M = 0.045
#: Ball contact: the down-facing vertices within this of the ToeBase head along the foot axis (metres).
BALL_BAND_M = 0.012
#: Toe height: the vertices within this of the toe tip (metres).
TOE_BAND_M = 0.006
#: Fixed-point iterations of the scale against the cavity end.
SCALE_ITERATIONS = 20
#: The extension against the SKINNED ball (step 3): most turns of the fixed point, and the chord-minus-pitch
#: correction (radians) under which it has converged.
BALL_SOLVE_STEPS = 8
BALL_SOLVE_TOL_RAD = 1e-7
#: An unroofed station counts as the open throat in this rear share of the length, else as closed.
OPEN_THROAT_SHARE = 0.6
#: The forepart slope runs this far (metres) in front of the ball.
FOREPART_SPAN_M = 0.05
#: Midline fit: slabs between the heel contact and this far (metres) past the ball.
MIDLINE_SLABS = 11
MIDLINE_PAST_BALL_M = 0.04
#: Width at the ball: foot vertices within this (metres) of the ball along the shoe axis.
BALL_WIDTH_BAND_M = 0.01
#: Toe room: the foot's front-most vertex below this height (metres, shoe frame).
TOE_ROOM_HEIGHT_M = 0.05
#: Version of the ``foot_pose`` payload (spec § 6.1).
FOOT_POSE_VERSION = 1
#: Shoe points farther than this (metres) from the shoe's midline count as a side wall for the wall top the cut
#: and its gates read (the spike's 4 mm; ``record["insole"]["wall_top_raw"]``).
WALL_SIDE_M = 0.004

SIDES = ("left", "right")
_UP = np.array([0.0, 1.0, 0.0])


@dataclass
class FootMeasure:
    """One foot measured on the body mesh in the bind pose (``measure_feet``; points in bind space)."""
    side: str                    # "left" | "right"
    heel_back: np.ndarray        # the rearmost foot vertex along the foot axis
    toe_tip: np.ndarray          # the front-most foot vertex along the foot axis
    length_m: float              # heel back -> toe tip along the foot axis
    ball_width_m: float          # lateral extent of the foot vertices within BALL_WIDTH_BAND_M of the ball
    d_heel_m: float              # heel back -> heel contact along the foot axis
    heel_ball_m: float           # heel contact -> ball contact (3D distance)
    rest_pitch_deg: float        # slope heel contact -> ball contact along the axis (heel higher = positive)
    ankle: np.ndarray            # the Foot joint (head)
    ball_joint: np.ndarray       # the ToeBase joint (head)
    plantar: np.ndarray          # vertex ids of the plantar vertices (the arch diagnostic's set)
    vertex_ids: np.ndarray       # vertex ids of the foot (Foot + ToeBase weight > FOOT_WEIGHT_MIN, below the ankle)
    heel_contact: np.ndarray = field(default_factory=lambda: np.zeros(3))
    ball_contact: np.ndarray = field(default_factory=lambda: np.zeros(3))
    forward: np.ndarray = field(default_factory=lambda: np.array([1.0, 0.0, 0.0]))
    toe_height_m: float = 0.0
    foot_joint: str = ""         # the body's own joint names
    toe_joint: str = ""
    foot_index: int = -1         # skin indices
    toe_index: int = -1
    # vertex ids behind the two contacts: the down-facing heel band and ball band (``measure_feet``)
    heel_ids: np.ndarray = field(default_factory=lambda: np.zeros(0, np.int64))
    ball_ids: np.ndarray = field(default_factory=lambda: np.zeros(0, np.int64))


@dataclass
class FootwearFit:
    """``fit_pair``'s result: ``ok`` = every gate passed; ``record`` = spec § 5.7 without ``accepted`` and the
    parents (``cut`` only when ``ok``); ``parts[side]`` = ``{"foot": GarmentMesh, "shaft": GarmentMesh}`` in bind
    space — ``"shaft"`` only for a split fit (a boot; boots spec 2026-11-11 § 6.2), the two parts share the band's
    vertices with identical positions and weights; ``foot_pose`` = spec § 6.1 without ``source``."""
    ok: bool
    reasons: List[str]
    record: Dict[str, Any]
    parts: Dict[str, Dict[str, glb_mesh.GarmentMesh]]
    foot_pose: Dict[str, Any]


class _Refused(Exception):
    """A shoe that cannot be put on this foot at all (no toe room, foot longer than the insole)."""


# --- small geometry ---------------------------------------------------------------------------------------------------

def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    if n <= 1e-12:
        raise ValueError("degenerate direction")
    return np.asarray(v, np.float64) / n


def _rotation(axis: np.ndarray, angle: float) -> np.ndarray:
    """3x3 rotation by ``angle`` (radians, right hand) about the unit ``axis``."""
    x, y, z = axis
    c, s = math.cos(angle), math.sin(angle)
    C = 1.0 - c
    return np.array([[c + x * x * C, x * y * C - z * s, x * z * C + y * s],
                     [y * x * C + z * s, c + y * y * C, y * z * C - x * s],
                     [z * x * C - y * s, z * y * C + x * s, c + z * z * C]])


def _about(pivot: np.ndarray, axis: np.ndarray, angle: float) -> np.ndarray:
    """4x4 rotation about the line through ``pivot`` along ``axis``."""
    R = _rotation(axis, angle)
    M = np.eye(4)
    M[:3, :3] = R
    M[:3, 3] = pivot - R @ pivot
    return M


def _translation(t) -> np.ndarray:
    M = np.eye(4)
    M[:3, 3] = t
    return M


def _apply(M: np.ndarray, X: np.ndarray) -> np.ndarray:
    X = np.asarray(X, np.float64)
    return X @ M[:3, :3].T + M[:3, 3]


def _smoothstep(u: np.ndarray) -> np.ndarray:
    u = np.clip(u, 0.0, 1.0)
    return u * u * (3.0 - 2.0 * u)


def _vertex_normals(P: np.ndarray, F: np.ndarray) -> np.ndarray:
    """Area-weighted vertex normals (zero for an unused vertex)."""
    fn = np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]])
    N = np.zeros_like(P)
    for k in range(3):
        np.add.at(N, F[:, k], fn)
    n = np.linalg.norm(N, axis=1, keepdims=True)
    return N / np.where(n > 0, n, 1.0)


def _joint_weight(body: glb_mesh.BodyMesh, index: int) -> np.ndarray:
    return np.where(body.joints == index, body.weights, 0.0).sum(axis=1)


def _r(v: Any, nd: int = 7) -> Any:
    """JSON-safe: floats rounded, NaN/inf -> None, arrays -> lists."""
    if isinstance(v, dict):
        return {k: _r(x, nd) for k, x in v.items()}
    if isinstance(v, np.ndarray):
        return _r(v.tolist(), nd)
    if isinstance(v, (list, tuple)):
        return [_r(x, nd) for x in v]
    if isinstance(v, (bool, np.bool_)):
        return bool(v)
    if isinstance(v, (float, np.floating)):
        f = float(v)
        return round(f, nd) if math.isfinite(f) else None
    if isinstance(v, np.integer):
        return int(v)
    return v


# --- step 1: the feet -------------------------------------------------------------------------------------------------

def _skin_index(body: glb_mesh.BodyMesh, key: str) -> int:
    from app.core.rig_contract import norm_bone_name
    for i, name in enumerate(body.joint_names):
        if norm_bone_name(name) == key:
            return i
    raise ValueError(f"The body has no joint '{key}'")


def _contact_band(P: np.ndarray, band: np.ndarray) -> np.ndarray:
    """The contact vertices of a down-facing band: those within ``CONTACT_BAND_H_M`` of the band's lowest one
    (module docstring, step 1). Empty for an empty band."""
    if not len(band):
        return band
    return band[P[band, 1] < float(P[band, 1].min()) + CONTACT_BAND_H_M]


def measure_feet(body: glb_mesh.BodyMesh, joints: Dict[str, np.ndarray]) -> Dict[str, FootMeasure]:
    """Both feet measured on the MESH (module docstring, step 1); ``joints`` = ``glb_mesh.joint_bind_matrices``.
    ValueError when a side lacks its Foot / ToeBase joint or its heel / ball contact vertices."""
    P = np.asarray(body.positions, np.float64)
    F = np.asarray(body.faces, np.int64)
    N = _vertex_normals(P, F)
    out: Dict[str, FootMeasure] = {}
    for side in SIDES:
        cap = side.capitalize()
        fkey, tkey = f"{side}foot", f"{side}toebase"
        if fkey not in joints or tkey not in joints:
            raise ValueError(f"The body has no {cap}Foot / {cap}ToeBase joint")
        fi, ti = _skin_index(body, fkey), _skin_index(body, tkey)
        a = np.asarray(joints[fkey], np.float64)[:3, 3]
        b = np.asarray(joints[tkey], np.float64)[:3, 3]
        fwd = _unit(np.array([b[0] - a[0], 0.0, b[2] - a[2]]))
        lat = np.cross(fwd, _UP)
        wf = _joint_weight(body, fi) + _joint_weight(body, ti)
        # the foot = Foot/ToeBase-weighted AND below the ankle: the auto-weighted shins carry Foot weight
        idx = np.nonzero((wf > FOOT_WEIGHT_MIN) & (P[:, 1] < a[1]))[0]
        if len(idx) < 8:
            raise ValueError(f"The {side} foot has no skinned vertices below the ankle")
        sc = (P[idx] - a) @ fwd
        smin, smax = float(sc.min()), float(sc.max())
        down = idx[N[idx, 1] < PLANTAR_NORMAL_MAX]
        ds = (P[down] - a) @ fwd
        bs = float((b - a) @ fwd)
        # each contact band against its OWN lowest point (a heel-up bind pose stands the heel off the floor)
        hsel = _contact_band(P, down[ds < smin + HEEL_BAND_M])
        bsel = _contact_band(P, down[np.abs(ds - bs) < BALL_BAND_M])
        if not len(hsel) or not len(bsel):
            raise ValueError(f"The {side} foot has no down-facing heel or ball vertices")
        H = P[hsel].mean(0)
        H[1] = P[hsel, 1].min()
        B = P[bsel].mean(0)
        B[1] = P[bsel, 1].min()
        plantar = down[P[down, 1] < min(float(H[1]), float(B[1])) + PLANTAR_BAND_M]
        tsel = idx[sc > smax - TOE_BAND_M]
        near_ball = idx[np.abs(sc - bs) < BALL_WIDTH_BAND_M]
        lw = (P[near_ball] - a) @ lat
        out[side] = FootMeasure(
            side=side, heel_back=P[idx[int(np.argmin(sc))]].copy(), toe_tip=P[idx[int(np.argmax(sc))]].copy(),
            length_m=smax - smin, ball_width_m=float(lw.max() - lw.min()) if len(lw) else 0.0,
            d_heel_m=float((H - a) @ fwd - smin), heel_ball_m=float(np.linalg.norm(B - H)),
            rest_pitch_deg=math.degrees(math.atan2(H[1] - B[1], float((B - H) @ fwd))),
            ankle=a, ball_joint=b, plantar=plantar, vertex_ids=idx, heel_contact=H, ball_contact=B,
            forward=fwd, toe_height_m=float(np.ptp(P[tsel, 1])), foot_joint=body.joint_names[fi],
            toe_joint=body.joint_names[ti], foot_index=fi, toe_index=ti, heel_ids=hsel, ball_ids=bsel)
    return out


# --- the insole at real scale -----------------------------------------------------------------------------------------

def _floats(values: Any) -> np.ndarray:
    return np.array([np.nan if v is None else float(v) for v in values], np.float64)


class _Insole:
    """The profile of ``insole.json`` as a function of x (raw frame units)."""

    def __init__(self, insole: Dict[str, Any]):
        self.gx = _floats(insole["stations"])
        self.gz = _floats(insole["lateral"])
        self.prof = _floats(insole["profile"])
        self.cav = _floats(insole.get("cavity") or [None] * len(self.gx))
        ok = ~np.isnan(self.prof)
        if ok.sum() < 2:
            raise ValueError("The insole has no profile")
        self.ok = ok
        self.px, self.pz = self.gx[ok], self.prof[ok]
        self.x0, self.x1 = float(self.px.min()), float(self.px.max())
        self.arc = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(self.px), np.diff(self.pz)))])
        self.length = float(insole["length_raw"])

    def z(self, x):
        return np.interp(x, self.px, self.pz)

    def arc_at(self, x: float) -> float:
        return float(np.interp(x, self.px, self.arc))

    def chord_to(self, xh: float, d: float, k: float) -> float:
        """The first x >= xh whose insole point lies ``d`` metres from the insole point at ``xh`` (linear
        between dense samples); _Refused when the insole ends first."""
        xs = np.linspace(xh, self.x1, 8000)
        dd = np.hypot((xs - xh) * k, (self.z(xs) - self.z(xh)) * k)
        hit = np.nonzero(dd >= d)[0]
        if not len(hit) or hit[0] == 0:
            raise _Refused("The foot is longer than the shoe's insole")
        i = int(hit[0])
        f = (d - dd[i - 1]) / (dd[i] - dd[i - 1])
        return float(xs[i - 1] + f * (xs[i] - xs[i - 1]))


def _scale(ins: _Insole, foot_len: float, toe_h: float) -> Tuple[float, float]:
    """``(k, x_end)``: the spike's fixed point k = (foot + ALLOW) / arc(cavity end at k)."""
    k = foot_len / ins.arc_at(0.9 * ins.length)
    x_end = ins.x1
    for _ in range(SCALE_ITERATIONS):
        room = np.where(np.isnan(ins.cav), np.where(ins.gx > OPEN_THROAT_SHARE * ins.gx.max(), 0.0, np.inf),
                        ins.cav) * k
        xs_ok = ins.gx[(room >= toe_h) & ins.ok]
        if not len(xs_ok):
            raise _Refused("The toe box is lower than the toes everywhere")
        x_end = float(xs_ok.max())
        k = (foot_len + ALLOW_M) / ins.arc_at(x_end)
    return k, x_end


# --- the fit ----------------------------------------------------------------------------------------------------------

def _frame_matrix(insole: Dict[str, Any]) -> np.ndarray:
    """4x4 mesh coordinates -> shoe frame ``(x, height, z)``."""
    from app.core.footwear_insole import frame_of
    fr = frame_of(insole)
    basis = np.stack([fr.x_axis, fr.up, fr.z_axis])
    M = np.eye(4)
    M[:3, :3] = basis
    M[:3, 3] = -basis @ fr.origin
    return M


def _pose(fm: FootMeasure, theta: float, slope: float) -> Tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    """``(Bf, Bt, axis, toe_turn)``: the stand-pose skin matrices of Foot and ToeBase (bind -> posed, before
    the root lift) for an extension ``theta`` and a forepart slope ``slope`` (radians); ``axis`` = up x
    forward (a positive turn about it takes the toes down)."""
    axis = _unit(np.cross(_UP, fm.forward))
    Bf = _about(fm.ankle, axis, theta)
    toe_turn = -(theta + slope)
    Bt = _about(_apply(Bf, fm.ball_joint), axis, toe_turn) @ Bf
    return Bf, Bt, axis, toe_turn


def _skin(P: np.ndarray, body: glb_mesh.BodyMesh, ids: np.ndarray, mats: Dict[int, np.ndarray]) -> np.ndarray:
    """Linear blend skinning of the vertices ``ids`` with ``mats`` (skin index -> 4x4; others identity)."""
    X = P[ids]
    out = X.copy()
    for j, M in mats.items():
        w = _joint_weight(body, j)[ids][:, None]
        out += w * (_apply(M, X) - X)
    return out


def _local_axis(J: np.ndarray, axis_w: np.ndarray) -> np.ndarray:
    return _unit(np.linalg.solve(np.asarray(J, np.float64)[:3, :3], axis_w))


def fit_pair(insole: Dict[str, Any], shoe: glb_mesh.GarmentMesh, body: glb_mesh.BodyMesh,
             joints: Dict[str, np.ndarray], *, width_cap: float = WIDTH_CAP) -> FootwearFit:
    """Fit one shoe source (``shoe`` in its mesher coordinates, ``insole`` its analysis) to both feet of
    ``body`` (module docstring). A shoe that cannot be put on at all returns ``ok False`` with the reason
    and no parts; a fit that ran returns everything, ``ok`` = every gate of ``FIT_GATES`` (and, for a boot, the
    gating ``SHAFT_GATES``) passed (the cut gates are the fit step's, ``garment_footwear.fit``). ValueError
    for a body without the foot joints (a boot also needs the side's Leg and UpLeg)."""
    width_cap = min(WIDTH_CAP, max(WIDTH_CAP_MIN, float(width_cap)))
    feet = measure_feet(body, joints)
    try:
        return _fit(insole, shoe, body, joints, feet, width_cap)
    except _Refused as exc:
        reason = str(exc)
        return FootwearFit(ok=False, reasons=[reason], record={"version": FOOTWEAR_FIT_VERSION, "error": reason},
                           parts={}, foot_pose={})


def split_height(fm: FootMeasure, lift_m: float, floor: float) -> float:
    """The wearer's ankle (the Foot joint) above the SHOE's ground in the shod stand (boots spec § 6.2): the
    joint's height above the body's floor plus the side's lift (the shoe ground sits ``lift_m`` under the floor
    before the root lift — a heeled shoe stands the ankle higher, a flat insole raises it by its own thickness)."""
    return float(fm.ankle[1]) - float(floor) + float(lift_m)


def _part_mesh(faces: np.ndarray, positions: np.ndarray, normals: Any, uvs: np.ndarray, joints: np.ndarray,
               weights: np.ndarray, joint_names: List[str], colors: Any, shoe: glb_mesh.GarmentMesh,
               material: Dict[str, Any]) -> glb_mesh.GarmentMesh:
    """One served part: the vertices ``faces`` use, re-indexed (a band vertex appears in both parts)."""
    used, inverse = np.unique(faces.reshape(-1), return_inverse=True)
    return glb_mesh.GarmentMesh(
        positions=positions[used].copy(), normals=None if normals is None else normals[used].copy(),
        uvs=uvs[used].copy(), indices=inverse.reshape(-1, 3).astype(np.int64), joints=joints[used].copy(),
        weights=weights[used].copy(), joint_names=list(joint_names), image=shoe.image, mime=shoe.mime,
        material=dict(material), colors=None if colors is None else colors[used].copy())


def _tri_area(P: np.ndarray, F: np.ndarray) -> np.ndarray:
    return 0.5 * np.linalg.norm(np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]]), axis=1)


def _rotation_angle_deg(R: np.ndarray) -> float:
    return math.degrees(math.acos(max(-1.0, min(1.0, (float(np.trace(R)) - 1.0) / 2.0))))


def _fit(insole: Dict[str, Any], shoe: glb_mesh.GarmentMesh, body: glb_mesh.BodyMesh,
         joints: Dict[str, np.ndarray], feet: Dict[str, FootMeasure], width_cap: float) -> FootwearFit:
    from app.core.footwear_insole import BALL_SHARE, HEEL_SEAT_M, PITCH_HEEL_SHARE, insole_map, topline_stations
    ins = _Insole(insole)
    P = np.asarray(body.positions, np.float64)
    floor = float(P[:, 1].min())
    FrameM = _frame_matrix(insole)
    S_pos = np.asarray(shoe.positions, np.float64)
    S_idx = np.asarray(shoe.indices, np.int64)
    Q = _apply(FrameM, S_pos)                        # the shoe in its frame (raw units)
    imap = insole_map(S_pos, S_idx, insole)
    gx, gz = ins.gx, ins.gz

    # 2. one scale for the pair
    foot_len = max(f.length_m for f in feet.values())
    toe_h = max(f.toe_height_m for f in feet.values())
    k, x_end = _scale(ins, foot_len, toe_h)

    def insole_cols(x: float) -> Tuple[int, np.ndarray]:
        i = int(np.argmin(np.abs(gx - x)))
        return i, np.nonzero(~np.isnan(imap[i]))[0]

    sides: Dict[str, Dict[str, Any]] = {}
    work: Dict[str, Dict[str, Any]] = {}
    for side, fm in feet.items():
        # 3. extension: the 2-point chord minus the rest pitch; the ToeBase back onto the forepart slope
        xh = ins.x0 + fm.d_heel_m / k
        # The ball the shoe is placed on is the ball AS SKINNED (Foot and ToeBase): the ToeBase
        # counter-turn moves the plantar ball vertices off the Foot-rigid point — 4–5 mm on the real
        # material — and the shoe has to meet the ball the clips show. That ball depends on the pose,
        # the pose on the chord to that ball: a fixed point, started from the rigid solve (the chord of
        # the bind heel–ball distance minus the rest pitch) and converged in a few turns
        # (|correction| < BALL_SOLVE_TOL_RAD, at most BALL_SOLVE_STEPS).
        xb = ins.chord_to(xh, fm.heel_ball_m, k)
        chord = math.atan2(float(ins.z(xh) - ins.z(xb)) * k, (xb - xh) * k)
        theta = chord - math.radians(fm.rest_pitch_deg)
        for _ in range(BALL_SOLVE_STEPS):
            x_fore = min(xb + FOREPART_SPAN_M / k, x_end)
            slope = (math.atan2(float(ins.z(x_fore) - ins.z(xb)) * k, (x_fore - xb) * k) if x_fore > xb else 0.0)
            Bf, Bt, axis, toe_turn = _pose(fm, theta, slope)
            H1 = _apply(Bf, fm.heel_contact)
            mats = {fm.foot_index: Bf, fm.toe_index: Bt}
            Bs = _skin(P, body, fm.ball_ids, mats)
            B1 = Bs.mean(0)
            B1[1] = Bs[:, 1].min()
            xb = ins.chord_to(xh, float(np.linalg.norm(B1 - H1)), k)
            chord = math.atan2(float(ins.z(xh) - ins.z(xb)) * k, (xb - xh) * k)
            pitch = math.atan2(float(H1[1] - B1[1]), float(np.hypot(B1[0] - H1[0], B1[2] - H1[2])))
            if abs(chord - pitch) < BALL_SOLVE_TOL_RAD:
                break
            theta += chord - pitch

        # 4. placement: yaw heel -> ball, the insole heel point on the posed heel contact; right = mirror
        d = _unit(np.array([B1[0] - H1[0], 0.0, B1[2] - H1[2]]))
        mirror = side == "right"
        right = np.cross(d, _UP)
        S = np.stack([d, _UP, -right if mirror else right], axis=1) * k
        P4 = np.eye(4)
        P4[:3, :3] = S
        P4[:3, 3] = H1 - S @ np.array([xh, float(ins.z(xh)), 0.0])
        ball_err = float(np.linalg.norm(_apply(P4, np.array([xb, float(ins.z(xb)), 0.0])) - B1))

        # the midline: foot slab middle - insole middle along the shoe, a line fitted to it
        Xf = _skin(P, body, fm.vertex_ids, mats)
        C = _apply(np.linalg.inv(P4), Xf)
        edges = np.linspace(xh, xb + MIDLINE_PAST_BALL_M / k, MIDLINE_SLABS + 1)
        dm, xm = [], []
        for xa, xc_ in zip(edges[:-1], edges[1:]):
            q = C[(C[:, 0] >= xa) & (C[:, 0] < xc_)]
            _, jj = insole_cols(0.5 * (xa + xc_))
            if len(q) < 5 or len(jj) < 3:
                continue
            dm.append(0.5 * (q[:, 2].min() + q[:, 2].max()) - 0.5 * (gz[jj.min()] + gz[jj.max()]))
            xm.append(0.5 * (xa + xc_))
        if len(xm) >= 2:
            sl, off = (float(v) for v in np.polyfit(np.array(xm), np.array(dm), 1))
        else:
            sl, off = 0.0, float(dm[0]) if dm else 0.0
        xc = float(np.mean(xm)) if xm else xh
        qb = C[np.abs(C[:, 0] - xb) < BALL_WIDTH_BAND_M / k]
        _, jb = insole_cols(xb)
        if not len(qb) or len(jb) < 2:
            raise _Refused("No foot or insole width at the ball")
        fw_ball = float(np.ptp(qb[:, 2])) * k
        iw_ball = float(gz[jb.max()] - gz[jb.min()]) * k
        work[side] = dict(fm=fm, xh=xh, xb=xb, chord=chord, theta=theta, slope=slope, Bf=Bf, Bt=Bt, axis=axis,
                          toe_turn=toe_turn, H1=H1, B1=B1, P4=P4, ball_err=ball_err, sl=sl, off=off, xc=xc,
                          fw_ball=fw_ball, iw_ball=iw_ball, Xf=Xf, mirror=mirror)

    # one width factor for the pair
    needed = {s: w["fw_ball"] / w["iw_ball"] for s, w in work.items()}
    width_factor = min(width_cap, max(1.0, max(needed.values())))
    slim = {s: max(0.0, 1.0 - w["iw_ball"] * width_factor / w["fw_ball"]) for s, w in work.items()}

    for side, w in work.items():
        fm = w["fm"]
        a = math.atan(w["sl"])
        c, s_ = math.cos(a), math.sin(a)
        R4 = np.eye(4)
        R4[:3, :3] = [[c, 0.0, -s_], [0.0, 1.0, 0.0], [s_, 0.0, c]]
        D4 = np.diag([1.0, 1.0, width_factor, 1.0])
        A = _translation([w["xc"], 0.0, w["off"] + w["sl"] * w["xc"]]) @ R4 @ _translation([-w["xc"], 0.0, 0.0]) @ D4
        Pf = w["P4"] @ A                          # shoe frame -> posed body (before the root lift)
        w["Pf"] = Pf
        w["lift"] = floor - float(Pf[1, 3])       # the shoe ground (frame height 0) onto the floor
        Cf = _apply(np.linalg.inv(Pf), w["Xf"])
        Bc = _apply(np.linalg.inv(Pf), w["B1"])
        w["xb_final"] = float(Bc[0])
        w["ball_gap_mm"] = (float(Bc[1]) - float(ins.z(Bc[0]))) * k * 1000.0
        low = Cf[Cf[:, 1] < TOE_ROOM_HEIGHT_M / k]
        w["toe_room_mm"] = (float(Q[:, 0].max()) - float(low[:, 0].max())) * k * 1000.0 if len(low) else None
        # arch gap: the plantar vertices against the insole map
        pl = _apply(np.linalg.inv(Pf), _skin(P, body, fm.plantar, {fm.foot_index: w["Bf"], fm.toe_index: w["Bt"]}))
        ix = np.rint((pl[:, 0] - gx[0]) / (gx[1] - gx[0])).astype(np.int64)
        iz = np.rint((pl[:, 2] - gz[0]) / (gz[1] - gz[0])).astype(np.int64)
        inside = (ix >= 0) & (ix < len(gx)) & (iz >= 0) & (iz < len(gz))
        zi = np.full(len(pl), np.nan)
        zi[inside] = imap[ix[inside], iz[inside]]
        gap = np.abs(pl[:, 1] - zi)[~np.isnan(zi)] * k * 1000.0
        w["arch_gap"] = (float(np.percentile(gap, 50)), float(np.percentile(gap, 95))) if len(gap) else (None, None)

    # 5. the root lift
    root_lift = max(w["lift"] for w in work.values())
    lifts = {s: w["lift"] for s, w in work.items()}

    # 6./7. mirror + rigid bind; contacts; the stand checks; 9. the split (boots spec § 6.2–6.4)
    parts: Dict[str, Dict[str, glb_mesh.GarmentMesh]] = {}
    bones: Dict[str, Dict[str, Any]] = {}
    contacts_pose: Dict[str, List[Dict[str, Any]]] = {}
    lowest: List[float] = []
    shaft_raw = insole.get("shaft_h_raw")
    topline_m = None if shaft_raw is None else float(shaft_raw) * k
    shaft_metrics: Dict[str, List[float]] = {name: [] for name in SHAFT_GATES}
    any_split = False
    for side, w in work.items():
        fm = w["fm"]
        M = w["Pf"] @ FrameM                      # mesh coordinates -> posed body
        Pw = _apply(M, S_pos)
        lowest.append(float(Pw[:, 1].min()) + root_lift - floor)
        wt = _smoothstep((Q[:, 0] - (w["xb_final"] - BLEND_M / k)) / (2.0 * BLEND_M / k))
        Bfi, Bti = np.linalg.inv(w["Bf"]), np.linalg.inv(w["Bt"])
        n_v = len(S_pos)
        side_idx = S_idx[:, [0, 2, 1]].copy() if w["mirror"] else S_idx.copy()

        # 9. the split at the wearer's ankle: heights in the shoe frame (metres above the shoe ground)
        y_split = split_height(fm, w["lift"], floor)
        yf = Q[:, 1] * k
        is_boot = topline_m is not None and topline_m > y_split + SPLIT_MARGIN_M
        collar_above = None if topline_m is None else (topline_m - y_split) * 1000.0
        s_band = _smoothstep((yf - (y_split - SPLIT_BAND_M)) / (2.0 * SPLIT_BAND_M)) if is_boot else np.zeros(n_v)
        in_band = (s_band > 0.0) & (s_band < 1.0)
        moving = s_band > 0.0                     # band + shaft: clothing-weighted, pushed off the shin
        # dense weights over [Foot, ToeBase, Leg, UpLeg]; a shoe keeps the two foot columns only
        W4 = np.zeros((n_v, 4))
        W4[:, 0], W4[:, 1] = 1.0 - wt, wt
        shaft_rec: Dict[str, Any] = {}
        if is_boot:
            any_split = True
            li = _skin_index(body, f"{side}leg")
            try:
                ui: Optional[int] = _skin_index(body, f"{side}upleg")
            except ValueError:
                ui = None                     # a rig-contract body has it; the synthetic feet of the smokes do not
            # the shaft transfer's columns: Leg and UpLeg only (spec § 6.3 anti-double-bend) — the band's Foot
            # share is the foot part's (1 - s) term, nothing above the band carries Foot or ToeBase
            column_of = {li: 2, **({ui: 3} if ui is not None else {})}
            columns = [li] + ([ui] if ui is not None else [])

            def shaft_weights(points: np.ndarray) -> np.ndarray:
                from app.core.garment_fit import clothing_weights
                J, Wc = clothing_weights(points, body, skirt=False, columns=columns)
                out = np.zeros((len(points), 4))
                for slot in range(4):
                    for j_body, col in column_of.items():
                        sel = J[:, slot] == j_body
                        out[sel, col] += Wc[sel, slot]
                return out / np.maximum(out.sum(1, keepdims=True), 1e-12)

            def blended_bind(X: np.ndarray, Wd: np.ndarray) -> np.ndarray:
                # the EXACT inverse of the blended skin matrix M = wF Bf + wT Bt + (wL + wU) I (Leg and UpLeg
                # stand in the bind pose): LBS of the result reproduces the fitted stand position exactly. The
                # ball blend's blend of inverses leaves a residual of 4 s(1-s) sin^2(theta/2) r at the band — 2.9 mm
                # at the heel counter of a 24 deg pump boot (scripts/smoke_footwear_split.py [B4]).
                Mb = (Wd[:, 0, None, None] * w["Bf"][None] + Wd[:, 1, None, None] * w["Bt"][None]
                      + (Wd[:, 2] + Wd[:, 3])[:, None, None] * np.eye(4)[None])
                Xh = np.concatenate([X, np.ones((len(X), 1))], axis=1)
                return np.linalg.solve(Mb, Xh[:, :, None])[:, :3, 0]

            # the push: the body skinned to the shod stand, its field over the shaft's bounds; only the band and
            # shaft move, the foot part is pinned (anti-goal: a shoe deformed by anything)
            from app.core.garment_fit import SDF_MARGIN_M, VOX_M, body_sdf, push_out
            mats = {fm.foot_index: w["Bf"], fm.toe_index: w["Bt"]}
            Pposed = _skin(P, body, np.arange(len(P)), mats)
            rows = np.nonzero(moving)[0]
            lo = Pw[rows].min(0) - SDF_MARGIN_M
            hi = Pw[rows].max(0) + SDF_MARGIN_M
            sdf = body_sdf(Pposed, body.faces, vox=VOX_M, bounds=(lo, hi))
            local = np.full(n_v, -1, np.int64)
            local[rows] = np.arange(len(rows))
            fsel = side_idx[np.all(moving[side_idx], axis=1)]
            Qp, disp = push_out(Pw[rows], local[fsel], sdf, clear=SHAFT_CLEAR_M)
            Pw = Pw.copy()
            Pw[rows] = Qp
            dn = np.linalg.norm(disp, axis=1)
            inside = sdf.sample(Qp) < 0.0
            # weights: the shaft's clothing transfer on the bind points — a fixed point of two turns (the bind
            # points depend on the weights through the Foot share near the ankle)
            Ws = shaft_weights(Pw[rows])
            Wd = W4.copy()
            Wd[rows] = (1.0 - s_band[rows])[:, None] * W4[rows] + s_band[rows][:, None] * Ws
            bind_1 = blended_bind(Pw[rows], Wd[rows])
            Ws = shaft_weights(bind_1)
            W4[rows] = (1.0 - s_band[rows])[:, None] * W4[rows] + s_band[rows][:, None] * Ws
            shaft_rec = {"push_p95_m": float(np.percentile(dn, 95)) if len(dn) else 0.0,
                         "push_max_m": float(dn.max()) if len(dn) else 0.0,
                         "inside_share": float(inside.mean()) if len(inside) else 0.0}
        bind = (W4[:, 0:1] * _apply(Bfi, Pw) + W4[:, 1:2] * _apply(Bti, Pw) + (W4[:, 2:3] + W4[:, 3:4]) * Pw)
        if is_boot:
            bind[rows] = blended_bind(Pw[rows], W4[rows])        # the band and shaft: exact (above)
        normals = None
        if shoe.normals is not None:
            n = np.asarray(shoe.normals, np.float64) @ np.linalg.inv(M[:3, :3])    # inverse transpose
            n = (W4[:, 0:1] * (n @ Bfi[:3, :3].T) + W4[:, 1:2] * (n @ Bti[:3, :3].T) + (W4[:, 2:3] + W4[:, 3:4]) * n)
            ln = np.linalg.norm(n, axis=1, keepdims=True)
            normals = n / np.where(ln > 0, ln, 1.0)
        Jf = np.asarray(joints[f"{side}foot"], np.float64)
        Jt = np.asarray(joints[f"{side}toebase"], np.float64)
        if is_boot:
            joint_names = [fm.foot_joint, fm.toe_joint, body.joint_names[li]] + (
                [body.joint_names[ui]] if ui is not None else [])
            jj = np.tile(np.array([0, 1, 2, 3 if ui is not None else 0], np.int64), (n_v, 1))
            jw = W4
            # the seam measures (spec § 6.3, § 9): the band's blended-inverse residual in the stand; the band
            # faces' area ratio at +-SEAM_FLEX_DEG about the fit's axis; the top ring against a Leg turn
            def posed(theta: float) -> np.ndarray:
                Bf2, Bt2, _axis, _tt = _pose(fm, theta, w["slope"])
                return (W4[:, 0:1] * _apply(Bf2, bind) + W4[:, 1:2] * _apply(Bt2, bind)
                        + (W4[:, 2:3] + W4[:, 3:4]) * bind)
            stand = posed(w["theta"])
            gap = np.linalg.norm(stand[in_band] - Pw[in_band], axis=1) * 1000.0
            band_faces = side_idx[np.any(in_band[side_idx], axis=1)]
            a0 = _tri_area(stand, band_faces)
            stretch = 1.0
            for theta in (w["theta"] + math.radians(SEAM_FLEX_DEG), w["theta"] - math.radians(SEAM_FLEX_DEG)):
                a1 = _tri_area(posed(theta), band_faces)
                okf = a0 > 1e-14
                if okf.any():
                    r = a1[okf] / a0[okf]
                    stretch = max(stretch, float(np.max(np.maximum(r, 1.0 / np.maximum(r, 1e-12)))))
            # the follow ring: the shaft above y_split + SHAFT_RING_ABOVE_M, else the shaft part's upper half,
            # else no measure (None — never a vacuous 0.0; Ruling 8b)
            ring = yf > y_split + SHAFT_RING_ABOVE_M
            follow_ring: Optional[str] = "top"
            if int(ring.sum()) < FOLLOW_RING_MIN:
                shaft_v = yf > y_split + SPLIT_BAND_M
                follow_ring = None
                if shaft_v.any():
                    ring = yf >= 0.5 * (float(yf[shaft_v].max()) + y_split + SPLIT_BAND_M)
                    follow_ring = "upper_half"
            follow: Optional[float] = None
            if follow_ring is not None and int(ring.sum()) >= FOLLOW_RING_MIN:
                from app.core.garment_fit import similarity
                Jl = np.asarray(joints[f"{side}leg"], np.float64)[:3, 3]
                Bl = _about(Jl, w["axis"], math.radians(FOLLOW_TURN_DEG))
                turned = W4[ring, 2:3] * _apply(Bl, bind[ring]) + (1.0 - W4[ring, 2:3]) * bind[ring]
                _s, R, _a, _b = similarity(bind[ring], turned)
                follow = abs(FOLLOW_TURN_DEG - _rotation_angle_deg(R))
            else:
                follow_ring = None
            shaft_rec.update({"seam_gap_p95_mm": float(np.percentile(gap, 95)) if len(gap) else 0.0,
                              "seam_stretch_max": stretch, "leg_follow_deg": follow, "follow_ring": follow_ring,
                              "band_vertices": int(in_band.sum()),
                              "ring_vertices": int(ring.sum()) if follow_ring is not None else 0})
            for key, name in (("push_p95_m", "shaft_push_p95_m"), ("push_max_m", "shaft_push_max_m"),
                              ("inside_share", "shaft_inside_share"), ("seam_gap_p95_mm", "seam_gap_p95_mm"),
                              ("seam_stretch_max", "seam_stretch_max"), ("leg_follow_deg", "shaft_leg_follow_deg")):
                if shaft_rec[key] is not None:
                    shaft_metrics[name].append(float(shaft_rec[key]))
            centroid_y = yf[side_idx].mean(1)
            foot_faces = side_idx[centroid_y < y_split]
            shaft_faces = side_idx[centroid_y >= y_split]
        else:
            joint_names = [fm.foot_joint, fm.toe_joint]
            jj = np.zeros((n_v, 4), np.int64)
            jj[:, 1] = 1
            jw = np.zeros((n_v, 4))
            jw[:, 0], jw[:, 1] = W4[:, 0], W4[:, 1]
            foot_faces, shaft_faces = side_idx, np.zeros((0, 3), np.int64)
        uvs = np.asarray(shoe.uvs, np.float64)
        colors = None if shoe.colors is None else np.asarray(shoe.colors, np.float64)
        material = dict(shoe.material or {})
        side_parts = {"foot": _part_mesh(foot_faces, bind, normals, uvs, jj, jw, joint_names, colors, shoe, material)}
        if len(shaft_faces):
            side_parts["shaft"] = _part_mesh(shaft_faces, bind, normals, uvs, jj, jw, joint_names, colors, shoe,
                                             {**material, "doubleSided": True})
        parts[side] = side_parts
        ax_f, ax_t = _local_axis(Jf, w["axis"]), _local_axis(Jt, w["axis"])
        bones[fm.foot_joint] = {"axis": ax_f, "deg": math.degrees(w["theta"])}
        bones[fm.toe_joint] = {"axis": ax_t, "deg": math.degrees(w["toe_turn"])}
        # contacts on the shoe sole: heel on Foot, ball and toe on ToeBase
        recs, pose = [], []
        for role, key, bone, J, Binv in (("heel", "heel_tip", fm.foot_joint, Jf, Bfi),
                                         ("ball", "ball", fm.toe_joint, Jt, Bti),
                                         ("toe", "toe_tip", fm.toe_joint, Jt, Bti)):
            pt = (insole.get("contacts") or {}).get(key)
            if pt is None:
                continue
            pos = _apply(Binv, _apply(w["Pf"], np.asarray(pt, np.float64)))
            recs.append({"bone": bone, "pos_local": _apply(np.linalg.inv(J), pos), "role": role})
            pose.append({"bone": bone, "pos": pos, "role": role})
        contacts_pose[side] = pose
        placement_bind = np.linalg.inv(Jf) @ Bfi @ M
        w["collar_above"] = collar_above
        sides[side] = {
            "mirror": w["mirror"], "placement_bind": placement_bind, "blend_m": BLEND_M,
            "extension": {"axis_local": ax_f, "deg": math.degrees(w["theta"])},
            "toe_counter": {"axis_local": ax_t, "deg": math.degrees(w["toe_turn"])},
            "forepart_slope_deg": math.degrees(w["slope"]), "lift_m": w["lift"],
            "foot_len_m": fm.length_m, "foot_w_ball_mm": w["fw_ball"] * 1000.0,
            "insole_w_ball_mm": w["iw_ball"] * 1000.0, "toe_room_mm": w["toe_room_mm"], "contacts": recs,
            "split": {"is_boot": is_boot, "y_m": y_split, "band_m": SPLIT_BAND_M, "margin_m": SPLIT_MARGIN_M,
                      "topline_m": topline_m, "collar_above_ankle_mm": collar_above},
            "parts": {name: int(len(mesh.indices)) for name, mesh in side_parts.items()},
            **({"shaft": shaft_rec} if is_boot else {}),
        }

    ball_mm = max(w["ball_err"] for w in work.values()) * 1000.0
    metrics: Dict[str, Any] = {
        "ball_placement_mm": ball_mm,
        "lift_asymmetry_mm": abs(lifts["left"] - lifts["right"]) * 1000.0,
        "slim_needed": max(slim.values()),
        "stand_floor_mm": min(lowest) * 1000.0,
    }
    table = {name: (kind, limit, GATE_LABELS[name]) for name, (kind, limit) in FIT_GATES.items()}
    if any_split:
        metrics.update({name: max(values) if values else None for name, values in shaft_metrics.items()})
        table.update({name: (kind, limit, GATE_LABELS[name]) for name, (kind, limit) in SHAFT_GATES.items()
                      if SHAFT_GATING[name]})
    # the follow measure is None without a ring (Ruling 8b): recorded, not a refusal, ``ok`` None
    ok, reasons = check_gates(metrics, table, optional=FOLLOW_OPTIONAL)
    gates: Dict[str, Any] = {}
    for name, value in metrics.items():
        kind, limit = (FIT_GATES.get(name) or SHAFT_GATES[name])
        passed = (None if value is None and name in FOLLOW_OPTIONAL
                  else check_gates({name: value}, {name: (kind, limit, GATE_LABELS[name])})[0])
        gates[name] = {"value": value, "limit": list(limit) if isinstance(limit, tuple) else limit,
                       "ok": passed, "gating": bool(SHAFT_GATING.get(name, True))}

    seat = float(ins.z(ins.x0 + HEEL_SEAT_M / k))
    ball_h = float(ins.z(BALL_SHARE * ins.length))
    heel_h = float(ins.z(PITCH_HEEL_SHARE * ins.length))
    used = Q[np.unique(S_idx)]
    # the wall top per station (raw units, None where absent), for the cut (footwear_cut.cut_description;
    # insole.json keeps only the analysis' topline and the cut must be derivable from the record): the lower
    # of the two sides' top edges, every point farther than WALL_SIDE_M from the midline counted — the spike's
    # wall top, not the analysis' topline whose 75 % lateral filter reads a leaning heel counter 2 cm low
    wall_top = topline_stations(Q, S_idx, gx, side_share=0.0, min_abs=WALL_SIDE_M / k)[0]
    wall_top_raw = [None if math.isnan(v) else float(v) for v in wall_top]
    shaft_in = insole.get("shaft") or {}
    record = {
        "version": FOOTWEAR_FIT_VERSION,
        "scale": {
            "k_m_per_unit": k, "length_m": float(np.ptp(used[:, 0])) * k, "width_m": float(np.ptp(used[:, 2])) * k,
            "height_m": float(np.ptp(used[:, 1])) * k, "width_factor": width_factor,
            "width_needed": needed, "width_cap": width_cap, "slim_needed": slim,
            "insole_arc_m": ins.arc_at(x_end) * k, "foot_len_m": foot_len, "toe_h_m": toe_h,
        },
        "sides": sides,
        "root_lift_m": root_lift,
        "insole": {
            "pitch_deg": math.degrees(math.atan2(heel_h - ball_h, (BALL_SHARE - PITCH_HEEL_SHARE) * ins.length)),
            "heel_seat_h_m": seat * k, "heel_rise_m": (seat - ball_h) * k, "insole_ball_h_m": ball_h * k,
            "insole_cover": insole.get("insole_cover"), "cavity_end_x_m": x_end * k,
            "shaft_h_m": topline_m,
            "open_share": None if insole.get("vamp_cover") is None else 1.0 - float(insole["vamp_cover"]),
            "wall_top_raw": wall_top_raw,
        },
        "split": {"is_boot": any_split, "band_m": SPLIT_BAND_M, "margin_m": SPLIT_MARGIN_M},
        "shaft": {
            "class": shaft_in.get("class"), "cap_removed": shaft_in.get("cap_removed"),
            "closed_share": shaft_in.get("closed_share"), "top_m": topline_m,
            "clip_m": None, "knee_margin_m": None,
            **{key: (max(shaft_metrics[name]) if shaft_metrics[name] else None) for key, name in (
                ("push_p95_m", "shaft_push_p95_m"), ("push_max_m", "shaft_push_max_m"),
                ("inside_share", "shaft_inside_share"), ("seam_gap_p95_mm", "seam_gap_p95_mm"),
                ("seam_stretch_max", "seam_stretch_max"), ("leg_follow_deg", "shaft_leg_follow_deg"))},
        },
        "gates": gates,
        "diagnostics": {s: {
            "chord_pitch_deg": math.degrees(w["chord"]), "rest_pitch_deg": w["fm"].rest_pitch_deg,
            "ball_placement_mm": w["ball_err"] * 1000.0, "ball_gap_mm": w["ball_gap_mm"],
            "lateral_off_mm": w["off"] * k * 1000.0,
            "lateral_yaw_deg": math.degrees(math.atan(w["sl"])),
            "arch_gap_p50_mm": w["arch_gap"][0], "arch_gap_p95_mm": w["arch_gap"][1],
            "ball_x_m": w["xb_final"] * k, "heel_x_m": w["xh"] * k,
            "foot_vertices": int(len(w["fm"].vertex_ids)), "plantar_vertices": int(len(w["fm"].plantar)),
            "collar_above_ankle_mm": w["collar_above"],
        } for s, w in work.items()},
    }
    foot_pose = {"version": FOOT_POSE_VERSION, "bones": bones, "root_lift_m": root_lift,
                 "contacts": contacts_pose}
    result = FootwearFit(ok=ok, reasons=reasons, record=_r(record), parts=parts, foot_pose=_r(foot_pose))
    if ok:
        # 8. the cut: derived from the record and the bound shoes of this fit (footwear_cut imports this module,
        # hence the local import); a refused fit carries none — nothing applies it
        from app.core.footwear_cut import cut_description
        result.record["cut"] = cut_description(result, insole)
    return result
