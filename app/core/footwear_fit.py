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
   and shifted by it) and the shoe is widened by ONE width factor for the pair, ``min(cap,
   max(1, needed))`` with needed = foot width / insole width at the ball and cap = ``applied_width_cap`` (the
   Wardrobe's width cap; a shoe without a shaft at the default ``SHOE_WIDTH_CAP`` 1.65, fit version 13; each
   side's needed is recorded;
   what the cap leaves is ``slim_needed`` = the share of the ball width the forefoot slimming of Task 14
   must take off). No vertical rest step (the spike's 3rd-percentile plantar rest moved 1 mm). Step 4b (fit
   version 14): a shoe widened to the foot has its upper fitted to the foot's height (module docstring, "Shoe
   height").
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
   **The collar** (fit version 9, boots plan Task 9 fix 2): the shaft's top as every consumer reads it is the closed
   rim of the opening — the insole analysis' ``shaft.top_raw`` (its highest CLOSED slab ring: a pull tab, a loop or
   a tongue above the rim is no closed ring, INSOLE_VERSION 4), else, without a closed slab (a shaft too low for
   slabs), the topline ``shaft_h_raw`` that made it a boot. Per side ``split.collar_m`` = that height × k in the
   shoe frame (metres above the shoe ground — the cut frame of ``footwear_cut``) and ``split.collar_bind_m`` = its
   height in BIND space: the placement maps the frame's up onto the body's up (``P4``'s basis ``[d, UP, ±right]``,
   ``d`` horizontal), so a frame height h stands at ``Pf · (0, h, 0)`` everywhere, and above the band the bind
   position IS the posed one (Leg / UpLeg stand in the bind pose). ``footwear_cut.cut_gates`` reads ``shaft_poke``
   up to ``collar_m``; the hem (``garment_layers``) and ``scripts/check_footwear.mjs`` (the shaft node's extras
   ``collar_bind_m``, contract ``docs/schnittstellen-3d.md``) read ``collar_bind_m``. The shaft part's highest
   vertex is no longer read as its top: on the P2 Work Shoes it is the back pull tab, 2.9 cm above the collar,
   and every shin vertex between the two read as a poke (``footwear_cut`` module docstring).
10. **The knee edge** (fit version 10, boots plan Task 14, spec § 6.4 step 3). Per side of a split fit, after the push:
   ``shaft.shaft_top_m`` = the collar of step 9 in BIND space (the same value as ``collar_bind_m`` — never the shaft's
   highest vertex; above the band the bind position is the stand before the root lift, which raises knee and shaft
   alike), ``shaft.knee_m`` = the side's Leg joint (the knee) in bind space. A collar above ``knee − KNEE_MARGIN_M``
   is CLIPPED there: ``footwear_cut.plane_cut(…, keep="below")`` on the built shaft part — the horizontal plane in
   bind space, everything above removed, the crossing faces bisected ON the plane (exact secant root); the new ring
   lerps the shaft's own Leg / UpLeg weights, so it rides the Leg bone like the rest of the shaft (the spec's "plane
   in the Leg bone's frame": the plane is not turned with a bone because above the band nothing is). Recorded per
   side: ``clip_m`` (collar − plane, 0 without a clip), ``clip_y_m`` (the plane, None without one), ``clip`` (the
   cut's stats), ``knee_margin_m`` (knee − the collar after the clip, rounded to ``KNEE_MARGIN_ROUND`` decimals: a
   clipped collar sits on the plane and the float difference reads 0.04 ± 1e-17); ``split.collar_m`` /
   ``collar_bind_m`` are the collar AFTER the clip (the plane), so ``shaft_poke``, the hem and
   ``check_footwear.mjs`` read the served top. The follow ring (step 9) stops at the plane. Gates (``SHAFT_GATES``,
   worse side; the margin's worse side is the smaller): ``shaft_clip_m`` ≤ ``SHAFT_CLIP_MAX_M`` (more is another
   boot than the image) and ``knee_margin_m`` ≥ ``KNEE_MARGIN_M`` — a guard of the clip, true by construction for
   every collar it leaves (an ankle boot reads its whole margin, ~30 cm on the fixture). The record's ``shaft``
   summary carries the worse sides' ``clip_m`` / ``knee_margin_m``. Fixture numbers: ``scripts/smoke_footwear_split.py``
   [B8] / [B9]; the seated check (``seat_thigh_in_shaft`` ≤ 2 % per frame) is ``scripts/check_footwear.mjs``'s, not a
   fit gate.

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
**P4 acceptance (Task 15, 2026-11-11) — a knee-class boot on Kira, REFUSED on the shaft push (fit version 10).**
``item_knee_high_leather_boots`` (Flux item image 280×512, "black leather knee-high boots, flat heel, side view"):
Iris upscale, Qwen empty (aspect 0.846, ``iou_below_topline`` 0.951), one UniForge mesh (94 310 → 59 574 tris,
``mesh_iou`` 0.942), insole v5 (cover 0.910, vamp 0.863, opening 0.960, closed 1.0, ``overknee`` 0.254, class
``knee``, cap of 19 faces removed). The fit on ``base20d5701a`` (k 0.3083, shoe 27.1 cm; width factor 1.10 = the cap,
needed 1.186 / 1.098): collar ``collar_bind_m`` 0.3046 / 0.3051, knee 0.5038 / 0.5039 → ``knee_margin_m`` 0.199,
``shaft_clip_m`` 0 (the image drew a mid-calf shaft, 1.2 × the foot length: the clip is not exercised),
``shaft_leg_follow_deg`` 0.00 (ring ``top``, 7 508 / 7 402 vertices — the UpLeg share feared in T14 is nil 20 cm
under the knee), seam gap 0, slim 0.073, every foot gate green — REFUSED on ``shaft_push_p95_m`` **0.0215** / 0.0211
(gate 0.015) and ``shaft_push_max_m`` **0.0309** (gate 0.03). Where (offline, read-only copies): the band + 3 cm
(ankle) p95 21–22 mm and the upper shaft p95 20 mm alike; the opening (inner wall, walls ~10 mm thick) is 64 × 122 mm
(w × d) at the collar against a calf of 87 × 94 mm, and the calf's centre stands 34–42 mm in FRONT of the opening's
centre there — the shaft stands vertical (frame up = body up) while Kira's shin leans 16.3° forward in bind (Foot
joint 111 mm behind the knee). The same boot on Kai ``base634402e5`` (k 0.3800, width factor 1.046, collar 0.362):
push p95 0.0102, max 0.0344 — refused on the max alone. Not a follow / clip problem.

**Task 9 fix 4 (Ruling 15e: the body is cut away under the boot).** Step 9c: the collar PLANE (the widened rim's
best-fit plane, normal up; horizontal at the collar without a rim) and the OPENING (``footwear_cut.collar_opening``)
in the cut frame go into ``shaft.collar_plane`` / ``shaft.opening`` — the cut removes foot and lower leg under that
plane and conforms the leg's edge into the opening (``footwear_cut`` version 5). What the cut body cannot show stops
gating: ``shaft_push_p95_m`` / ``shaft_push_max_m`` / ``shaft_inside_share`` read the shaft vertices from
``COLLAR_BAND_M`` under the plane up (the visible collar band; the whole-shaft values stay as ``push_all_*`` /
``inside_all_share``). The push's body field is hole-filled slice by slice (``garment_fit.body_sdf``; since
fit-sdf-speed-drape Task 1 every body field is, along x, y and z — the shaft push needed the horizontal slices):
the clone's base bodies rebuilt 2026-11-12 (Kira ``base20d5701a``, Kai ``base634402e5``) are leg SHELLS whose
calf cavity the 3D fill and the seal read as outside, so the push left the shaft's side walls inside the leg
(pushed toward the cavity). Measured on copies (knee-high leather boots, width cap 1.10, turn + calf centring of
fix 3): Kira band push p95 26.6 / max 30.9 mm (whole shaft 21.6 / 31.1), Kai 36.6 / 42.7 mm — both REFUSED on the
push: the image's shaft is 64 mm wide at the collar against an 87-mm calf (a flattened single-view tube), the
spec's "too narrow for this calf". The Work Shoes on Kai read 16.2 / 23.4 mm (refused on p95 by 1.2 mm; on the
pre-rebuild Kai 13.5 / 20.9, accepted).

Shoe width (fit version 13, boots plan Ruling 15g). A shoe's width is the mesher's guess from one picture, so a shoe
WITHOUT a shaft (insole ``shaft.has_shaft`` False) may be widened to the wearer's foot: the width factor is the
needed one up to ``SHOE_WIDTH_CAP`` 1.65 instead of ``WIDTH_CAP`` 1.10, the forefoot slimming takes only what is left
over. A Wardrobe cap below 1.10 still caps; a boot keeps 1.10. The record carries ``scale.width_cap_applied``; the
delivered gates (cut deep_outside / visible_poke / throat / toe conform, the penetration of the delivered check)
decide. Measured on copies 2026-11-12 (clone base bodies Kai ``base634402e5``, Kira ``base20d5701a``): the Sneekers
on Kai needed 1.604 / 1.466 (was 1.10 + slim 0.314, refused) -> widened x1.604, slim 0, but the cut still refuses
(deep_outside 25.3 / 18.0 %, toe_conform 52.0 / 49.9 mm — the mesh's toe box is too LOW for Kai's toes, not too
narrow); the Black Stilettos on Kira needed 1.317 -> x1.317, slim 0, refused by lift asymmetry 10.46 mm (> 10, as at
1.10) and the cut (deep_outside 31.0 %, toe_conform 137 mm); the Business Heels on Kira widen from 1.10 + slim 0.022
to x1.124, slim 0, still accepted (visible_poke 0.0028 -> 0.0017).

Shoe height (fit version 14, boots plan Ruling 15h). The mesher guesses the upper's height as well: a shoe widened to
the foot (``applied_width_cap`` = ``SHOE_WIDTH_CAP``) has its upper scaled vertically about the insole surface
(``upper_height_map``, step 4b) — per roofed station (the toe box from the throat front on, the cut's ``vamp_inner``
range) the foot's top inside the insole's columns plus ``footwear_cut.TOE_CLEARANCE_M`` over the cavity, the worse
station of the worse side, capped at ``HEIGHT_CAP`` 1.5; ramped in from the heel seat to the throat front so the heel
counter keeps its height; the sole, the heel and the insole plane do not move (the lifts and the lift asymmetry read
the insole and the heel only — unchanged). The record's ``scale.height`` carries the map, ``cut_description`` takes
the vamp's inner surface and the topline through it (the wall top is measured on the fitted shoe). Measured on
copies 2026-11-12: the Sneekers on Kai need 3.66 / 3.48 (the mesher's vamp sits 25–29 mm over the insole, the
instep 90 mm) -> x1.5 with x1.604 wide: still REFUSED, deep_outside 29.5 / 28.8 % (the walls now count more of the
foot as should-be-enclosed; the pokes are lateral at mid-foot, 35–80 mm high), toe_conform 39.6 / 37.7 mm (was
52.0 / 49.9), delivered penetration 2.8 / 2.9 % (was 4.8 / 4.3); the Black Stilettos on Kira need 20.7 (a pointed
toe box) -> x1.5: still refused, lift asymmetry 10.46 mm unchanged, deep_outside 47.3 %, toe_conform 127 mm (was 137),
throat ledge 53.4 mm (was 39.5); the Business Heels on Kira need 1.51 / 1.53 -> x1.5, still accepted, toe_conform
10.8 -> 1.4 mm — the accepted pair's upper stands 50 % taller.

Since fit version 15 (boots plan Ruling 15i) the height fit changes no accepted look and stretches no open shoe:
``fit_pair`` only measures it (``scale.height_needed``, ``height_ready``) unless ``fit_height`` is set, and
``garment_footwear.fit_compute`` sets it only for a second attempt when the first one is refused — by the fit's
gates or the cut's — and the shoe is ready for it: a CLOSED toe box (``INSTEP_ROOF_SHARE`` of the instep stations
roofed at least ``CAVITY_MIN_M`` over the insole; a pump or a heel exposes the instep by design) widened to the
foot (``SHOE_WIDTH_CAP``, no Wardrobe cap, no shaft) that needs more than its own height. A second attempt that is
refused while the toe box needs more than ``HEIGHT_CAP`` names the mesh first (``too_flat_reason``): the shoe has
to be regenerated. Measured on copies 2026-11-12: the Business Heels on Kira (instep roof share 0) come out
byte-identical to fit version 13 again (x1.124 wide, no height, GLB sha256 269e8c6f…); the Sneekers on Kai (share 1)
stay refused, "Shoe mesh too flat for the foot: toe box 24 mm, instep needs ~89 mm — regenerate the shoe" ahead of
deep_outside 29.5 % and toe_conform 39.6 mm; the Black Stilettos on Kira (share 0.02) stay refused by the fit's lift
asymmetry 10.46 mm, no second attempt.

Since fit version 16 (2026-11-12) the toe box is measured against the SLIMMED foot: ``footwear_cut`` presses the
hidden foot towards the insole down to the toe box (step 1b, never under ``FOOT_FLOOR_SHARES``), so ``height_needed``
is ``min(foot top, floor) + TOE_CLEARANCE_M`` over the cavity — slimming first, the height fit only for the rest.
Together with the insole's sole layers (``footwear_insole`` version 8; the numbers above were read on the hollow sole
plate, a 17-mm "cavity") the Sneekers on Kai's base need x1.12 and are ACCEPTED at the first attempt (width x1.0,
deep_outside 0, toe_conform 3.6 mm); on his outfit body ``obf6474c3b`` x1.438 at the second (deep_outside 1.9 %,
toe_conform 3.8 mm); on Kira x1.0 (toe_conform 6.7 mm). ``too_flat_reason`` names the mesh only when the mesh
disagrees with its own image (``footwear_gates.image_agreement``); otherwise the foot is too high for this shoe.
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
#:    the shaft's upper half when the top ring is empty (P2 Rulings 8a / 8b);
#: 8: the shaft push runs on WELDED positions (seam duplicates move as one vertex, the smoothing over the connected
#:    tube — an unwelded push tore the tube at its seams; Task 9 fix 1);
#: 9: the COLLAR per side (``split.collar_m`` / ``collar_bind_m``, step 9) — the shaft's top for ``shaft_poke``, the
#:    hem and ``check_footwear.mjs`` (a pull tab above the rim is no shaft top; Task 9 fix 2);
#: 10: the knee edge (step 10) — a knee-high shaft clipped at ``knee − KNEE_MARGIN_M``, the collar after the clip,
#:    the gates ``shaft_clip_m`` / ``knee_margin_m`` on every split fit (Task 14). A stored v9 boot fit differs (no
#:    knee gates in its record, a knee-high one unclipped); a shoe's output is unchanged and refits to the same bytes.
#: 11: the shaft turned onto the shin and centred on the calf at the width cap (Task 9 fix 3), the collar plane and
#:    opening for the boot body cut (step 9c, ``footwear_cut`` version 5), the push gates read in the collar band
#:    only, the push's body field hole-filled per slice (Task 9 fix 4, Ruling 15e);
#: 12: the shaft push recorded, not gating (``SHAFT_GATING``); the boot body cut's collar weights and the gate
#:    ``collar_flex_poke`` (``footwear_cut`` version 6) — a stored v11 boot fit's body and gates differ (Task 9 fix 5,
#:    Ruling 15f);
#: 13: a shoe without a shaft is widened to the foot up to ``SHOE_WIDTH_CAP`` (Ruling 15g);
#: 14: ... and its upper fitted to the foot's height up to ``HEIGHT_CAP`` (``upper_height_map``, Ruling 15h);
#: 15: ... only for a closed toe box and only when the fit without it is refused (``fit_pair(fit_height=)``, Ruling
#:    15i) — an accepted v13 shoe comes out as at v13, a v14 one fitted in height (an open pump) differs.
#: 16: the foot is slimmed vertically in the toe box before the upper is raised (``FOOT_FLOOR_SHARES``,
#:    ``footwear_cut`` version 7): ``height_needed`` reads the slimmed foot, the side records its toe tip
#:    (``toe_x_m``) for the cut, and a toe box the height fit cannot raise enough names the mesh only when the mesh
#:    disagrees with its image (``too_flat_reason``).
#: 17 (plan 2026-11-12 fit-sdf-speed-drape phase A): the body field is the three-axis slice-filled solid for every
#:    fit (Task 1; the footwear push had the y-slices only, ``fill_slices=True``), computed faster (Task 2) and
#:    cached per body on a body-anchored lattice (Task 5) — the shaft push moves by up to a voxel. One CPU refit.
#: 18 (Ruling A35): an outfit body's fit is DERIVED from the accepted base fit (``garment_footwear.derive_compute``:
#:    the shoe rides the shape's foot joints, raised by its sole, the base fit's cut applied there) instead of fitted
#:    fresh on the shape's own foot (Kai's ``obf6474c3b``: "Foot too high", 30 mm at the ball). A base fit refits to
#:    the same geometry (a new fsig); every outfit body's fit is derived again from it. One CPU refit.
FOOTWEAR_FIT_VERSION = 18
#: Toe room: the insole arc is the longer foot plus this (metres).
ALLOW_M = 0.005
#: Ruling A82: the per-piece footwear allowances the Wardrobe offers (percent; ``garment_footwear.ALLOWANCE_KEY``).
#: ``length``: the shoe one size longer — the uniform scale ``k`` is solved for the longer foot plus this share of its
#: length (``_scale``), and the heel contact sits that much further into the shoe, so ALL the added length is heel
#: room and the toe room stays ``ALLOW_M`` (the poke it exists for is the heel: Vallerie's Woman shoes, whose rounded
#: counter ends where her heel ends). The upper grows in height with ``k`` like a real size step; the WIDTH does not:
#: the width factor is solved at the scale without the length allowance and divided by the size ratio, so a length
#: step leaves the shoe's width in metres as it was. ``width``: the fitted width factor times (1 + share) — the shoe
#: that much wider than the fit made it (at the default cap a shoe without a shaft is as wide as the foot, so the share
#: is of the foot's ball width). 0 / 0 is byte-identical to fit version 18 (nothing becomes due).
#: A174: negative steps make the shoe tighter (narrower / shorter, the heel contact that much further back); the
#: fit's gates still refuse a shoe the foot pokes out of — a negative step is never clamped.
ALLOWANCE_STEPS: Tuple[int, ...] = (-10, -8, -6, -4, -2, 0, 2, 4, 6, 8, 10, 12, 15, 20)
#: Half-width of the Foot -> ToeBase smoothstep around the ball (metres).
BLEND_M = 0.015
#: The largest width factor a fit may apply (spec § 5.5), also the default cap — the cap of a boot (an item whose
#: insole has a shaft: its shaft must not grow past the look of the item) and the Wardrobe slider's maximum.
WIDTH_CAP = 1.10
#: A shoe WITHOUT a shaft (the insole's ``shaft.has_shaft`` False) at the default cap is widened to the wearer's
#: foot up to this (fit version 13, boots plan Ruling 15g): its width is the mesher's guess from one side view of
#: the item image, not a measured fact — a real shoe is as wide as the foot in it. The factor is the ball width of
#: the wider foot over the insole's (``width_needed``); the margin is the cut's own (``footwear_cut.CLEARANCE_M``: the
#: forefoot slimming takes the foot that far inside the widened walls). A width cap set in the Wardrobe (below
#: ``WIDTH_CAP``: the slider's maximum IS the default, ``garment_footwear.set_width_cap``) still caps the shoe — the
#: user keeps the item's look; a boot keeps ``WIDTH_CAP`` for the whole item, its shaft its own
#: ``SHAFT_WIDTH_CAP_*``. The applied cap is the record's ``scale.width_cap_applied``. Measured: module
#: docstring, "Shoe width".
SHOE_WIDTH_CAP = 1.65
#: The smallest per-fit width cap override.
WIDTH_CAP_MIN = 1.00
#: A shoe widened to the foot (``applied_width_cap`` = ``SHOE_WIDTH_CAP``) has its UPPER fitted to the foot's height
#: as well, up to this factor (fit version 14, boots plan Ruling 15h): the part above the insole is scaled vertically
#: about the insole surface (``upper_height_map``) so the toe box's inner roof stands the toe / instep height plus
#: ``footwear_cut.TOE_CLEARANCE_M`` above the insole; the sole and heel (the insole plane, heel rise and pitch) do not
#: move. The factor ramps in from the heel seat to the throat front (the heel counter keeps its height) and is the
#: needed one (``scale.height_needed``, the worse roofed station of the worse side) capped here. A boot and a shoe
#: under a Wardrobe width cap keep their height. The delivered gates decide. Since fit version 15 (Ruling 15i) only a
#: CLOSED toe box (``INSTEP_ROOF_SHARE``) takes it, and only on the second attempt of ``garment_footwear.fit_compute``
#: — when the fit without it was refused (an accepted look never changes). Measured: module docstring, "Shoe
#: height".
HEIGHT_CAP = 1.5
#: A closed toe box = a vamp roof over the instep: at least this share of the stations from ``INSTEP_FROM_SHARE`` of
#: the insole length to ``footwear_insole.BALL_SHARE`` carry a cavity (a roof above the insole in the middle columns)
#: of at least ``footwear_insole.CAVITY_MIN_M`` at the fit's scale. A pump or heel exposes the instep by design (no
#: roof there, or a lining a few millimetres over the insole — the Black Stilettos' 7–8 mm) and never gets the height
#: scale (Ruling 15i). Measured shares: Sneekers 1.00, Black Stilettos 0.02, Business Heels 0.00.
INSTEP_ROOF_SHARE = 0.8
#: Where the instep starts, as a share of the insole length (``INSTEP_ROOF_SHARE``).
INSTEP_FROM_SHARE = 0.45
#: The largest share of the ball width the forefoot slimming may take off (gate ``slim_needed``).
SLIM_MAX_SHARE = 0.18
#: The vertical forefoot slimming's floor (fit version 16, ``footwear_cut`` version 7): ``(u, share)`` — the
#: thinnest a foot may be pressed at ``u`` = the share of its own length from the toe tip, as a share of that length
#: (piecewise linear, the ends held). The foot inside a closed toe box is hidden, so the cut presses it towards the
#: insole down to the toe box's inner height minus ``footwear_cut.TOE_CLEARANCE_M`` — the lateral slimming's rule
#: turned vertical — but never thinner than a real foot: a generated mesh foot is 30–60 % too thick (measured on
#: copies 2026-11-12, foot top over the sole at u 0.10 / 0.20 / 0.36 / 0.45 / 0.55: Kai ``base634402e5`` 37 / 48 /
#: 71 / 79 / 102 mm at 291 mm long, his outfit body ``obf6474c3b`` 38 / 51 / 74 / 102 / 116 mm at 344 mm, Kira
#: ``base20d5701a`` 33 / 37 / 59 / 70 / 90 mm at 243 mm), a real one is not. Derivation, adult anthropometry of
#: a ~27-cm foot standing (foot top over the floor): the toes (u ≈ 0.10, hallux height) 20–25 mm, the ball (the
#: first metatarsal head, u ≈ 0.27–0.36) 40–45 mm, the instep at half the foot length (u ≈ 0.5–0.55, "instep
#: height") 65–70 mm, and the dorsum rises on to the ankle (u ≈ 0.70, the navicular / ankle front) at about 80 mm.
#: The floor is the LOW end of each range over the 270-mm length — 20 / 270 = 0.074, 40 / 270 = 0.148, 65 / 270 =
#: 0.241, 81 / 270 = 0.30 — and the toe tip's 11 mm (0.04, the nail's edge); a share of the foot's own length, so a
#: foot generated too long gets a proportionally higher floor (it is still a foot of that length). Between the
#: points the floor is linear; whatever the floor leaves above the toe box is the height fit's (``HEIGHT_CAP``).
FOOT_FLOOR_SHARES: Tuple[Tuple[float, float], ...] = ((0.0, 0.04), (0.10, 0.074), (0.36, 0.148), (0.55, 0.241),
                                                      (0.70, 0.30))


def foot_floor_m(u: Any, length_m: float) -> np.ndarray:
    """The vertical slimming's floor (``FOOT_FLOOR_SHARES``) at ``u`` = shares of the foot length from the toe tip,
    in metres for a foot ``length_m`` long."""
    us = np.array([p[0] for p in FOOT_FLOOR_SHARES])
    shares = np.array([p[1] for p in FOOT_FLOOR_SHARES])
    return np.interp(np.asarray(u, np.float64), us, shares) * float(length_m)

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
#: The knee edge (step 10, spec § 6.4 step 3): the collar stays this far under the Leg joint — a shaft above it is
#: clipped at ``knee − KNEE_MARGIN_M``; more than ``SHAFT_CLIP_MAX_M`` clipped off is another boot than the image
#: (gate ``shaft_clip_m``). The margin is rounded to this many decimals (metres): a clipped collar sits ON the plane
#: and ``knee − (knee − 0.04)`` reads 0.04 ± 1e-17 in floats.
KNEE_MARGIN_M = 0.04
SHAFT_CLIP_MAX_M = 0.05
KNEE_MARGIN_ROUND = 9
#: The shaft onto the shin (step 9a, fit version 11): the shaft's axis is the line fitted through the middles of its
#: horizontal sections, slabs of ``SHAFT_AXIS_SLAB_M`` between the band's top and the collar, each with at least
#: ``SHAFT_AXIS_SLAB_MIN`` vertices; fewer than ``SHAFT_AXIS_SLABS`` slabs or a span under ``SHAFT_AXIS_MIN_M`` is no
#: axis (an ankle boot: no turn). The calf's section at the collar = the shin vertices within ``CALF_SECTION_M``.
SHAFT_AXIS_MIN_M = 0.05
SHAFT_AXIS_SLAB_M = 0.01
SHAFT_AXIS_SLAB_MIN = 8
SHAFT_AXIS_SLABS = 3
CALF_SECTION_M = 0.005
#: The shaft width factor (step 9b, spec § 17): per axis at most this — the spec names no cap of its own, so both are
#: its one width cap, § 5.5's 1.10 (Task 9 fix 3 measured what a larger across cap would take: module docstring); the
#: opening's inner radius on a side = the nearest shaft vertex to the axis within ``WIDEN_BIN_DEG`` of that side.
SHAFT_WIDTH_CAP_ACROSS = WIDTH_CAP
SHAFT_WIDTH_CAP_DEPTH = WIDTH_CAP
WIDEN_BIN_DEG = 15.0
#: The shaft push gates read the push of the shaft vertices within this far under the collar plane (and above it):
#: the body under the boot is cut away (``footwear_cut``, Ruling 15e), only the collar band still meets the leg.
COLLAR_BAND_M = 0.03
#: Shaft measures whose worse side is the SMALLER value.
WORST_IS_MIN = ("knee_margin_m",)
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
    "shaft_clip_m": ("max", SHAFT_CLIP_MAX_M),
    "knee_margin_m": ("min", KNEE_MARGIN_M),
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
#: **The push is recorded, not gating, since fit version 12 (Task 9 fix 5, Ruling 15f).** It measured the shaft
#: pushed off a leg that is no longer there: under a boot the body is cut away up to the collar (``footwear_cut``
#: version 5), so the push reads how far the item's shaft had to move, not anything the served model shows. On the
#: knee-high leather boots (clone copies, fit version 11) the collar band's push read Kira p95 26.6 / max 30.9 mm and
#: Kai 36.6 / 42.7 mm against 15 / 30 — refused — while the DELIVERED model (cut body + boot, ``check_footwear.mjs``)
#: had penetration 0 % in stand / idle / walk / sit, a rim gap of 1.9 / 3.8 mm (``collar_gap_min_mm``: the leg's cut
#: edge inside the opening), seam gap 0 and the seated thigh 0 % in the shaft; the sheet showed proper boots. What
#: gates a boot now is what can be seen: ``shaft_inside_share`` and the seam / follow / knee gates here,
#: ``shaft_poke`` (rim gap), ``collar_conform_m`` (rim step) and ``collar_flex_poke`` (the leg edge at ±25° ankle
#: flex) in ``footwear_cut.CUT_GATES``; ``check_footwear.mjs`` reads penetration and the seated thigh on the served
#: GLB. The push stays in the record and the Wardrobe as "Reported, not gated".
SHAFT_GATING: Dict[str, bool] = {
    "shaft_push_p95_m": False, "shaft_push_max_m": False, "shaft_inside_share": True,
    "seam_gap_p95_mm": True, "seam_stretch_max": False, "shaft_leg_follow_deg": True,
    "shaft_clip_m": True, "knee_margin_m": True,
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
    "shaft_clip_m": "height clipped off the shaft under the knee, worse side",
    "knee_margin_m": "the Leg joint (knee) above the collar after the clip, worse side",
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
             joints: Dict[str, np.ndarray], *, width_cap: Optional[float] = None,
             fit_height: bool = False, allowance: Optional[Dict[str, Any]] = None) -> FootwearFit:
    """Fit one shoe source (``shoe`` in its mesher coordinates, ``insole`` its analysis) to both feet of
    ``body`` (module docstring). A shoe that cannot be put on at all returns ``ok False`` with the reason
    and no parts; a fit that ran returns everything, ``ok`` = every gate of ``FIT_GATES`` (and, for a boot, the
    gating ``SHAFT_GATES``) passed (the cut gates are the fit step's, ``garment_footwear.fit``). ValueError
    for a body without the foot joints (a boot also needs the side's Leg and UpLeg). ``width_cap`` None = the
    default (``applied_width_cap``: a shoe without a shaft widens to the foot up to ``SHOE_WIDTH_CAP``, a boot to
    ``WIDTH_CAP``; recorded as ``scale.width_cap`` ``WIDTH_CAP``, the fingerprint's default); a number = the
    Wardrobe's cap, clamped to ``WIDTH_CAP_MIN`` .. ``WIDTH_CAP``, applied as it is. ``fit_height`` True fits the upper
    to the foot's height (step 4b) where ``scale.height_ready`` holds; False (the default) only measures it — the
    first attempt of ``garment_footwear.fit_compute``, byte-identical to fit version 13. ``allowance`` (Ruling A82):
    ``{"width": percent, "length": percent}`` of ``ALLOWANCE_STEPS`` (``ALLOWANCE_STEPS`` docstring); None / zeros =
    none."""
    applied = applied_width_cap(insole, width_cap)
    width_cap = WIDTH_CAP if width_cap is None else min(WIDTH_CAP, max(WIDTH_CAP_MIN, float(width_cap)))
    feet = measure_feet(body, joints)
    try:
        return _fit(insole, shoe, body, joints, feet, width_cap, applied, fit_height, allowance_shares(allowance))
    except _Refused as exc:
        reason = str(exc)
        return FootwearFit(ok=False, reasons=[reason], record={"version": FOOTWEAR_FIT_VERSION, "error": reason},
                           parts={}, foot_pose={})


def allowance_shares(allowance: Optional[Dict[str, Any]]) -> Tuple[float, float]:
    """``(width share, length share)`` of an allowance dict (percent -> share); a value outside ``ALLOWANCE_STEPS``
    is ValueError (``garment_footwear.validate_allowance`` checks it before it is stored)."""
    out = []
    for key in ("width", "length"):
        value = (allowance or {}).get(key, 0) or 0
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value not in ALLOWANCE_STEPS:
            raise ValueError(f"The {key} allowance must be one of {', '.join(str(v) for v in ALLOWANCE_STEPS)}")
        out.append(float(value) / 100.0)
    return out[0], out[1]


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


def _lean_deg(v: np.ndarray) -> float:
    """The angle (degrees) between the direction ``v`` and the body's up."""
    return math.degrees(math.acos(max(-1.0, min(1.0, float(_unit(v) @ _UP)))))


def _section_centre(X: np.ndarray) -> np.ndarray:
    """The horizontal (x, z) middle of a cross-section's extent — density-independent (a mesh denser on one wall
    pulls a vertex mean, not the middle of the extent)."""
    return 0.5 * (X[:, [0, 2]].min(0) + X[:, [0, 2]].max(0))


def _rodrigues(V: np.ndarray, axis: np.ndarray, angles: np.ndarray) -> np.ndarray:
    """Each row of ``V`` turned by its own angle (radians) about the unit ``axis`` (Rodrigues' formula)."""
    c, s = np.cos(angles)[:, None], np.sin(angles)[:, None]
    return V * c + np.cross(axis, V) * s + np.outer(V @ axis, axis) * (1.0 - c)


def _shaft_widen(P: np.ndarray, yf: np.ndarray, s_band: np.ndarray, turn: Dict[str, Any], *, y_lo: float,
                 y_hi: float, lateral: np.ndarray, calf: np.ndarray) -> Dict[str, Any]:
    """Step 9b (fit version 11, spec § 17's shaft width factor): the turned shaft's cross-section scaled about its axis
    — ONE factor across (``lateral``, the shoe's z ⟂ the axis) and one along the depth — to the calf plus
    ``SHAFT_CLEAR_M`` where the opening is narrower, each ``min(cap, max(1, needed))``, blended in across the band
    like the turn. ``needed`` per axis = the largest over the shaft's slabs (frame heights [``y_lo``, ``y_hi``], as the
    axis) and the axis' two sides of (the calf's reach from the axis + clearance) / the opening's inner radius there
    (the nearest shaft vertex to the axis within ±``WIDEN_BIN_DEG`` of that side). Returns the positions and the
    record (``needed`` and ``factor`` per axis) and the collar ring's lowest / highest point after the widening."""
    a = _unit(turn["leg_axis"])
    lv = _unit(lateral - (lateral @ a) * a)
    dv = np.cross(a, lv)
    c_top = turn["pivot"] + turn["t"]

    def local(X: np.ndarray) -> np.ndarray:
        Q = X - c_top
        return np.stack([Q @ lv, Q @ dv, Q @ a], axis=1)

    Lc = local(calf)
    need = {"across": [], "depth": []}
    half = math.radians(WIDEN_BIN_DEG)
    for lo in np.arange(y_lo, y_hi - 1e-12, SHAFT_AXIS_SLAB_M):
        sel = (yf >= lo) & (yf < lo + SHAFT_AXIS_SLAB_M) & (s_band >= 1.0)
        if int(sel.sum()) < SHAFT_AXIS_SLAB_MIN:
            continue
        Ls = local(P[sel])
        ua = float(np.median(Ls[:, 2]))
        sec = Lc[np.abs(Lc[:, 2] - ua) <= CALF_SECTION_M]
        if len(sec) < SHAFT_AXIS_SLAB_MIN:
            continue
        r = np.hypot(Ls[:, 0], Ls[:, 1])
        th = np.arctan2(Ls[:, 1], Ls[:, 0])
        for name, col, dirs in (("across", 0, (0.0, math.pi)), ("depth", 1, (0.5 * math.pi, -0.5 * math.pi))):
            for sign, ang in zip((1.0, -1.0), dirs):
                inb = np.abs(np.angle(np.exp(1j * (th - ang)))) <= half
                if not inb.any():
                    continue
                reach = float(np.max(sign * sec[:, col]))
                r_in = max(float(r[inb].min()), 1e-6)
                need[name].append((reach + SHAFT_CLEAR_M) / r_in)

    needed = {name: (max(v) if v else None) for name, v in need.items()}
    caps = {"across": SHAFT_WIDTH_CAP_ACROSS, "depth": SHAFT_WIDTH_CAP_DEPTH}
    factor = {name: (1.0 if v is None else min(caps[name], max(1.0, v))) for name, v in needed.items()}
    out = P.copy()
    rows, s = turn["rows"], turn["s"]
    if factor["across"] != 1.0 or factor["depth"] != 1.0:
        C = turn["pivot"] + s[:, None] * turn["t"]
        Q = P[rows] - C
        ul, ud = Q @ lv, Q @ dv
        out[rows] = (P[rows] + np.outer(ul * s * (factor["across"] - 1.0), lv)
                     + np.outer(ud * s * (factor["depth"] - 1.0), dv))
    # the collar ring widened with the shaft (above the band, s = 1): its lowest and highest point
    rim = turn["rim"]
    if len(rim):
        Q = rim - c_top
        rim = rim + np.outer((Q @ lv) * (factor["across"] - 1.0), lv) + np.outer((Q @ dv) * (factor["depth"] - 1.0), dv)
    return {"P": out, "needed": needed, "factor": factor, "cap": caps, "rim": rim,
            "collar_lo": float(rim[:, 1].min()) if len(rim) else None,
            "collar_hi": float(rim[:, 1].max()) if len(rim) else None}


def _shaft_turn(Pw: np.ndarray, yf: np.ndarray, s_band: np.ndarray, *, y_lo: float, y_hi: float, frame0: float,
                y_pivot: float, leg_dir: np.ndarray, calf: np.ndarray, faces: np.ndarray,
                collar_f: float) -> Optional[Dict[str, Any]]:
    """Step 9a (fit version 11): the shaft onto the shin (module docstring). ``Pw`` = the placed shoe (posed, before
    the root lift), ``yf`` its frame heights, ``s_band`` the band's smoothstep; the axis is read over the frame
    heights [``y_lo``, ``y_hi``] (the band's top to the collar), ``frame0`` = the bind height of frame height 0,
    ``y_pivot`` the frame height of the pivot (the split), ``leg_dir`` the Leg bone's direction (ankle -> knee) in the
    stand, ``calf`` the side's shin vertices in the stand, ``faces`` the side's faces, ``collar_f`` the collar's frame
    height. None when the shaft is too short for an axis (fewer than ``SHAFT_AXIS_SLABS`` slabs over at least
    ``SHAFT_AXIS_MIN_M``) — the shaft then stays as placed (an ankle boot: the foot part's placement decides).
    Else ``{"P": the turned positions, "rows" / "s": the moving vertices and their blend, "axis" / "angle": the
    full turn, "pivot", "t": the horizontal shift, "leg_axis", "rim": the collar ring turned and shifted, …}``."""
    if y_hi - y_lo < SHAFT_AXIS_MIN_M:
        return None
    edges = np.arange(y_lo, y_hi + 1e-12, SHAFT_AXIS_SLAB_M)
    ys, cs = [], []
    for a, b in zip(edges[:-1], edges[1:]):
        sel = (yf >= a) & (yf < b) & (s_band >= 1.0)
        if int(sel.sum()) < SHAFT_AXIS_SLAB_MIN:
            continue
        ys.append(frame0 + 0.5 * (a + b))
        cs.append(_section_centre(Pw[sel]))
    if len(ys) < SHAFT_AXIS_SLABS:
        return None
    Y, C = np.asarray(ys), np.asarray(cs)
    bx, ax = np.polyfit(Y, C[:, 0], 1)
    bz, az = np.polyfit(Y, C[:, 1], 1)
    axis_s = _unit(np.array([bx, 1.0, bz]))
    axis_l = _unit(leg_dir)
    yp = frame0 + y_pivot
    pivot = np.array([ax + bx * yp, yp, az + bz * yp])
    cross = np.cross(axis_s, axis_l)
    sn = float(np.linalg.norm(cross))
    angle = math.atan2(sn, float(axis_s @ axis_l))
    rot_axis = cross / sn if sn > 1e-12 else np.array([1.0, 0.0, 0.0])
    R = _rotation(rot_axis, angle)
    # the collar ring: where the frame plane at the collar cuts the shaft's edges (exact lerp) and the vertices ON it
    # (a rim row at the collar's very height), turned in full
    E = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    da, db = yf[E[:, 0]] - collar_f, yf[E[:, 1]] - collar_f
    cut = (da * db < 0.0) & (s_band[E[:, 0]] >= 1.0) & (s_band[E[:, 1]] >= 1.0)
    u = (da[cut] / (da[cut] - db[cut]))[:, None]
    on = np.unique(faces[np.isin(faces, np.nonzero((np.abs(yf - collar_f) <= 1e-9) & (s_band >= 1.0))[0])])
    on = on[np.abs(yf[on] - collar_f) <= 1e-9]
    rim = np.concatenate([Pw[E[cut, 0]] + u * (Pw[E[cut, 1]] - Pw[E[cut, 0]]), Pw[on]])
    rim_t = (rim - pivot) @ R.T + pivot
    # the shift: the turned shaft's axis onto the calf's section centre at the collar (horizontal only)
    yc = float(rim_t[:, 1].mean()) if len(rim_t) else frame0 + collar_f
    sec = calf[np.abs(calf[:, 1] - yc) <= CALF_SECTION_M]
    t = np.zeros(3)
    calf_c = None
    if len(sec) >= SHAFT_AXIS_SLAB_MIN:
        calf_c = _section_centre(sec)
        on_axis = pivot + axis_l * ((yc - yp) / float(axis_l[1]))
        t[[0, 2]] = calf_c - on_axis[[0, 2]]
    # the blend: the band's smoothstep turns and shifts by s (the foot part, s = 0, stays put; above the band s = 1)
    out = Pw.copy()
    mv = np.nonzero(s_band > 0.0)[0]
    s = s_band[mv]
    out[mv] = _rodrigues(Pw[mv] - pivot, rot_axis, s * angle) + pivot + s[:, None] * t
    rim_t = rim_t + t
    return {"P": out, "rows": mv, "s": s, "axis": rot_axis, "angle": angle, "pivot": pivot, "t": t, "leg_axis": axis_l,
            "turn_deg": math.degrees(angle),
            "shaft_lean_deg": _lean_deg(axis_s), "leg_lean_deg": _lean_deg(axis_l),
            "shift_m": float(np.linalg.norm(t)), "calf_centre": calf_c, "slabs": len(ys), "rim": rim_t}


def applied_width_cap(insole: Dict[str, Any], width_cap: Optional[float] = None) -> float:
    """The width factor's cap for ``insole``'s item: a Wardrobe cap (a number) clamped to ``WIDTH_CAP_MIN`` ..
    ``WIDTH_CAP``; without one (None, the default) ``SHOE_WIDTH_CAP`` for a shoe without a shaft, ``WIDTH_CAP``
    for a boot (``SHOE_WIDTH_CAP`` docstring). An insole without ``shaft.has_shaft`` (before INSOLE_VERSION 6)
    counts as a shaft: the old cap."""
    if width_cap is not None:
        return min(WIDTH_CAP, max(WIDTH_CAP_MIN, float(width_cap)))
    shaft = insole.get("shaft") if isinstance(insole.get("shaft"), dict) else {}
    return SHOE_WIDTH_CAP if shaft.get("has_shaft", True) is False else WIDTH_CAP


#: ``too_flat_reason``: the station names by the share of the foot length from the toe tip (upper bounds).
STATION_NAMES: Tuple[Tuple[float, str], ...] = ((0.15, "the toes"), (0.40, "the ball"), (1.01, "the instep"))


def _station_name(u: Optional[float]) -> str:
    if u is None:
        return "the toe box"
    return next((name for bound, name in STATION_NAMES if float(u) < bound), "the instep")


def too_flat_reason(record: Dict[str, Any]) -> Optional[str]:
    """The Wardrobe's reason for a closed shoe whose toe box the height fit cannot raise enough even for the slimmed
    foot (``height_ready`` and ``height_needed`` above ``HEIGHT_CAP``; the worse side's worst station); None
    otherwise. Only a mesh that disagrees with its own image (``record.insole.image.agrees`` False —
    ``footwear_gates.image_agreement``: the mesher flattened what the picture shows) names the mesh: "Shoe mesh too
    flat for the foot: toe box 27 mm, instep needs ~90 mm — regenerate the shoe". A mesh that matches its image is the
    shoe the image shows, and regenerating it gives the same toe box: "Foot too high for this shoe even after
    slimming (foot 51 mm, shoe 30 mm at the ball)" — the slimmed foot over the insole against the toe box's inner
    height there (fit version 16). An insole without the comparison (before INSOLE_VERSION 8) reads as agreeing."""
    scale = record.get("scale") or {}
    needed = [v for v in (scale.get("height_needed") or {}).values() if v is not None]
    if not scale.get("height_ready") or not needed or max(needed) <= HEIGHT_CAP:
        return None
    worst = [v for v in (scale.get("height_worst") or {}).values() if v]
    if not worst:
        return None
    w = max(worst, key=lambda v: v["need_mm"] / max(v["roof_mm"], 1e-9))
    image = (record.get("insole") or {}).get("image") or {}
    if image.get("agrees") is False:
        return (f"Shoe mesh too flat for the foot: toe box {w['roof_mm']:.0f} mm, instep needs ~{w['need_mm']:.0f} mm "
                f"— regenerate the shoe")
    foot = w.get("foot_mm", w["need_mm"])
    return (f"Foot too high for this shoe even after slimming (foot {foot:.0f} mm, shoe {w['roof_mm']:.0f} mm at "
            f"{_station_name(w.get('toe_share'))})")


def upper_scale(x: np.ndarray, height: Optional[Dict[str, Any]]) -> np.ndarray:
    """The upper's vertical factor at the shoe-frame stations ``x`` (raw units) for the record's ``scale.height``:
    1 up to ``x_from_raw`` (the heel seat), ``factor`` from ``x_full_raw`` (the throat front) on, smoothstep between;
    all 1 for None (``HEIGHT_CAP`` docstring)."""
    x = np.asarray(x, np.float64)
    if not height or float(height.get("factor", 1.0)) == 1.0:
        return np.ones_like(x)
    x0, x1 = float(height["x_from_raw"]), float(height["x_full_raw"])
    u = (x - x0) / max(x1 - x0, 1e-9)
    return 1.0 + (float(height["factor"]) - 1.0) * _smoothstep(u)


def upper_height_map(Q: np.ndarray, insole: Dict[str, Any], height: Optional[Dict[str, Any]],
                     normals: Optional[np.ndarray] = None) -> Tuple[np.ndarray, Optional[np.ndarray]]:
    """``(Q', normals')``: shoe-frame points ``Q`` (raw units, ``(x, height, z)``) with the upper fitted in height —
    a point above the insole surface ``b(x)`` (the insole profile, flat beyond its ends) goes to ``b + (y − b)·s(x)``
    (``upper_scale``), one on or below it stays (the sole, the heel). ``normals`` (frame directions, optional) go
    through the map's inverse transpose and are renormalised. The identity (copies) for a factor of 1 / None."""
    Q = np.asarray(Q, np.float64)
    if not height or float(height.get("factor", 1.0)) == 1.0:
        return Q.copy(), None if normals is None else np.asarray(normals, np.float64).copy()
    ins = _Insole(insole)
    x, y = Q[:, 0], Q[:, 1]
    b = ins.z(x)
    sx = upper_scale(x, height)
    above = y > b
    out = Q.copy()
    out[:, 1] = np.where(above, b + (y - b) * sx, y)
    if normals is None:
        return out, None
    # the Jacobian above the insole: dy'/dy = s, dy'/dx = (1 - s) b'(x) + (y - b) s'(x)
    eps = 1e-5
    db = (ins.z(x + eps) - ins.z(x - eps)) / (2.0 * eps)
    ds = (upper_scale(x + eps, height) - upper_scale(x - eps, height)) / (2.0 * eps)
    a = np.where(above, (1.0 - sx) * db + (y - b) * ds, 0.0)
    s_ = np.where(above, sx, 1.0)
    n = np.asarray(normals, np.float64).copy()
    nx = n[:, 0] - n[:, 1] * a / s_
    ny = n[:, 1] / s_
    n[:, 0], n[:, 1] = nx, ny
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    return out, n / np.where(ln > 0, ln, 1.0)


def _fit(insole: Dict[str, Any], shoe: glb_mesh.GarmentMesh, body: glb_mesh.BodyMesh,
         joints: Dict[str, np.ndarray], feet: Dict[str, FootMeasure], width_cap: float,
         cap_applied: float, fit_height: bool = False,
         allow: Tuple[float, float] = (0.0, 0.0)) -> FootwearFit:
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
    # Ruling A82 (``ALLOWANCE_STEPS``): the length allowance is heel room — the scale of the longer foot, the heel
    # contact that much further in; ``size`` = the scale ratio the width factor is divided by
    width_share, length_share = allow
    heel_room = foot_len * length_share
    k0 = k
    if heel_room != 0.0:  # A174: a negative length step is a shorter shoe (less heel room)
        k, x_end = _scale(ins, foot_len + heel_room, toe_h)
    size = k / k0

    def insole_cols(x: float) -> Tuple[int, np.ndarray]:
        i = int(np.argmin(np.abs(gx - x)))
        return i, np.nonzero(~np.isnan(imap[i]))[0]

    sides: Dict[str, Dict[str, Any]] = {}
    work: Dict[str, Dict[str, Any]] = {}
    for side, fm in feet.items():
        # 3. extension: the 2-point chord minus the rest pitch; the ToeBase back onto the forepart slope
        xh = ins.x0 + (fm.d_heel_m + heel_room) / k
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
    width_factor = min(cap_applied, max(1.0, max(needed.values()) * size))
    if width_share or heel_room:
        width_factor = width_factor * (1.0 + width_share) / size
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

    # 4b. the upper's height (fit version 14, ``HEIGHT_CAP``): per roofed station (the toe box, as the cut's) the
    # foot's top inside the insole's columns against the inner roof (insole profile + cavity) plus the clearance
    from app.core.footwear_cut import TOE_CLEARANCE_M
    roofed = ~np.isnan(ins.cav) & (gx > 0.5 * float(np.nanmax(gx)))
    height_needed: Dict[str, Optional[float]] = {}
    height_worst: Dict[str, Optional[Dict[str, float]]] = {}
    half = 0.5 * float(gx[1] - gx[0]) if len(gx) > 1 else 0.0
    for side, w in work.items():
        Cf = _apply(np.linalg.inv(w["Pf"]), w["Xf"])
        # the foot's toe tip in the shoe frame: the vertical slimming's floor is read from it (fit version 16)
        w["toe_x_raw"] = float(Cf[:, 0].max())
        worst = None
        height_worst[side] = None
        for i in np.nonzero(roofed)[0]:
            _, jj = insole_cols(float(gx[i]))
            if len(jj) < 2 or ins.cav[i] <= 0.0:
                continue
            sel = (np.abs(Cf[:, 0] - gx[i]) <= half) & (Cf[:, 2] >= gz[jj.min()]) & (Cf[:, 2] <= gz[jj.max()])
            if not sel.any():
                continue
            base = float(ins.z(gx[i]))
            # the foot as the cut leaves it: slimmed vertically down to the toe box, never under the floor — what
            # is left over the roof is what the upper must be raised by (FOOT_FLOOR_SHARES)
            top = float(Cf[sel, 1].max()) - base
            u = (w["toe_x_raw"] - float(gx[i])) * k / w["fm"].length_m
            floor_raw = float(foot_floor_m(u, w["fm"].length_m)) / k
            foot = min(top, floor_raw)
            need = foot + TOE_CLEARANCE_M / k
            ratio = need / float(ins.cav[i])
            if worst is None or ratio > worst:
                worst = ratio
                height_worst[side] = {"x_share": float(gx[i]) / float(np.nanmax(gx)), "toe_share": u,
                                      "roof_mm": float(ins.cav[i]) * k * 1000.0, "need_mm": need * k * 1000.0,
                                      "foot_mm": foot * k * 1000.0, "foot_raw_mm": top * k * 1000.0}
        height_needed[side] = worst
    # a closed toe box (Ruling 15i): a roof of at least CAVITY_MIN_M over the instep stations
    from app.core.footwear_insole import CAVITY_MIN_M
    span = ins.ok & (gx >= INSTEP_FROM_SHARE * ins.length) & (gx < BALL_SHARE * ins.length)
    roof_ok = np.where(np.isnan(ins.cav), False, ins.cav * k >= CAVITY_MIN_M)
    instep_roof = float(roof_ok[span].mean()) if span.any() else 0.0
    wanted = [v for v in height_needed.values() if v is not None]
    height_ready = bool(cap_applied >= SHOE_WIDTH_CAP - 1e-9 and roofed.any() and instep_roof >= INSTEP_ROOF_SHARE
                        and wanted and max(wanted) > 1.0)
    height_factor = min(HEIGHT_CAP, max(wanted)) if fit_height and height_ready else 1.0
    height: Optional[Dict[str, Any]] = None
    if height_factor > 1.0:
        height = {"factor": height_factor, "cap": HEIGHT_CAP, "x_from_raw": ins.x0 + HEEL_SEAT_M / k,
                  "x_full_raw": float(gx[roofed].min())}
        Q = upper_height_map(Q, insole, height)[0]

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
    # the collar (step 9, fit version 9): the highest closed slab ring of the analysis, else the topline
    collar_raw = (insole.get("shaft") or {}).get("top_raw")
    if collar_raw is None:
        collar_raw = shaft_raw
    shaft_metrics: Dict[str, List[float]] = {name: [] for name in SHAFT_GATES}
    any_split = False
    for side, w in work.items():
        fm = w["fm"]
        M = w["Pf"] @ FrameM                      # mesh coordinates -> posed body
        # the upper fitted in height (4b) lives in Q; without it the direct map (the same bytes as before)
        Pw = _apply(w["Pf"], Q) if height is not None else _apply(M, S_pos)
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
        turn: Optional[Dict[str, Any]] = None
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
            from app.core.garment_fit import SDF_MARGIN_M, VOX_M, body_sdf, push_out, weld
            mats = {fm.foot_index: w["Bf"], fm.toe_index: w["Bt"]}
            Pposed = _skin(P, body, np.arange(len(P)), mats)
            frame0 = float(w["Pf"][1, 3])              # bind height of the shoe ground (frame height 0)
            knee = np.asarray(joints[f"{side}leg"], np.float64)[:3, 3]
            # 9a. the shaft onto the shin (fit version 11): turned onto the Leg bone about the band's centre and
            # shifted onto the calf's section at the collar, both blended in across the band
            shin_w = _joint_weight(body, li) + (_joint_weight(body, ui) if ui is not None else 0.0)
            turn = _shaft_turn(Pw, yf, s_band, y_lo=y_split + SPLIT_BAND_M, y_hi=float(collar_raw) * k,
                               frame0=frame0, y_pivot=y_split, leg_dir=knee - fm.ankle,
                               calf=Pposed[shin_w > 0.5], faces=side_idx, collar_f=float(collar_raw) * k)
            widen = None
            if turn is not None:
                Pw = turn["P"]
                # 9b. the shaft width factor where the opening is still narrower than the calf (spec § 17)
                widen = _shaft_widen(Pw, yf, s_band, turn, y_lo=y_split + SPLIT_BAND_M, y_hi=float(collar_raw) * k,
                                     lateral=w["Pf"][:3, 2], calf=Pposed[shin_w > 0.5])
                Pw = widen["P"]
            rows = np.nonzero(moving)[0]
            lo = Pw[rows].min(0) - SDF_MARGIN_M
            hi = Pw[rows].max(0) + SDF_MARGIN_M
            sdf = body_sdf(Pposed, body.faces, vox=VOX_M, bounds=(lo, hi))
            local = np.full(n_v, -1, np.int64)
            local[rows] = np.arange(len(rows))
            fsel = side_idx[np.all(moving[side_idx], axis=1)]
            # WELDED (fit version 8, Task 9 fix 1 — as ``garment_fit_layers.layer_over``): seam duplicates (a UV
            # seam, the fixtures' unshared quads) move as ONE vertex and the displacement smoothing runs over the
            # connected tube; unwelded, every patch was smoothed on its own and the push tore the tube open at
            # its seams (the flood fill of ``footwear_cut.cut_gates`` then entered the shaft: shaft_poke 0.58 on
            # an accepted fixture fit).
            Pwld, Fwld, inv = weld(Pw[rows], local[fsel])
            Qw, dispw = push_out(Pwld, Fwld, sdf, clear=SHAFT_CLEAR_M)
            Qp, disp = Qw[inv], dispw[inv]
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
            # 10. the knee edge (fit version 10): the collar in bind space against the Leg joint; above
            # knee - KNEE_MARGIN_M the shaft is clipped there (the cut itself runs on the built shaft part below)
            # a turned shaft's rim tilts with the shin: its highest point is the top the knee clip reads, its lowest
            # the collar a horizontal plane still closes (step 9a); an unturned rim is level, both are the collar
            knee_y = float(knee[1])
            top_bind = frame0 + float(collar_raw) * k
            rim_lo = top_bind
            if widen is not None and widen["collar_hi"] is not None:
                top_bind, rim_lo = widen["collar_hi"], widen["collar_lo"]
            clip_y = knee_y - KNEE_MARGIN_M
            clip_m = max(0.0, top_bind - clip_y)
            collar_bind = min(rim_lo, clip_y) if clip_m > 0.0 else rim_lo
            shaft_rec.update({"shaft_top_m": top_bind, "knee_m": knee_y, "clip_m": clip_m,
                              "clip_y_m": clip_y if clip_m > 0.0 else None,
                              "knee_margin_m": round(knee_y - min(top_bind, clip_y), KNEE_MARGIN_ROUND),
                              "turn": None if turn is None else {
                                  "turn_deg": turn["turn_deg"], "shaft_lean_deg": turn["shaft_lean_deg"],
                                  "leg_lean_deg": turn["leg_lean_deg"], "shift_m": turn["shift_m"],
                                  "slabs": turn["slabs"], "calf_section": turn["calf_centre"] is not None,
                                  "rim_lo_m": widen["collar_lo"], "rim_hi_m": widen["collar_hi"]},
                              "widen": None if widen is None else {"needed": widen["needed"], "factor": widen["factor"],
                                                                   "cap": widen["cap"]}})
            # 9c. the collar plane and the opening (fit version 11, Ruling 15e): what the body cut removes under and
            # conforms into (``footwear_cut``), in the cut frame — the shoe frame at the fitted size, where every
            # stand position X sits at ``diag(k, k, k wf) Pf^-1 X`` (a rigid map: the width factor cancels)
            from app.core.footwear_cut import collar_height, collar_opening
            T0 = np.diag([k, k, k * width_factor, 1.0]) @ np.linalg.inv(w["Pf"])
            rim_pts = widen["rim"] if widen is not None else np.zeros((0, 3))
            if len(rim_pts) >= 3:
                c0 = rim_pts.mean(0)
                nrm = np.linalg.svd(rim_pts - c0)[2][-1]
                nrm = nrm if nrm[1] > 0 else -nrm
            else:
                c0, nrm = _apply(w["Pf"], np.array([0.0, float(collar_raw), 0.0])), _UP.copy()
            plane = {"point": _apply(T0, c0), "normal": _unit(T0[:3, :3] @ nrm),
                     "clip_m": (clip_y - frame0) if clip_m > 0.0 else None}
            Xc = _apply(T0, Pw)
            hc = collar_height(Xc, plane)
            opening = collar_opening(Xc, hc, plane)
            # the push measures read the collar band only: under it the body is cut away (Ruling 15e)
            band = hc[rows] >= -COLLAR_BAND_M
            dn_band, in_band_c = dn[band], inside[band]
            shaft_rec.update({"collar_plane": plane, "opening": opening,
                              "push_all_p95_m": shaft_rec["push_p95_m"], "push_all_max_m": shaft_rec["push_max_m"],
                              "inside_all_share": shaft_rec["inside_share"],
                              "push_p95_m": float(np.percentile(dn_band, 95)) if len(dn_band) else 0.0,
                              "push_max_m": float(dn_band.max()) if len(dn_band) else 0.0,
                              "inside_share": float(in_band_c.mean()) if len(in_band_c) else 0.0,
                              "collar_band_vertices": int(band.sum())})
        bind = (W4[:, 0:1] * _apply(Bfi, Pw) + W4[:, 1:2] * _apply(Bti, Pw) + (W4[:, 2:3] + W4[:, 3:4]) * Pw)
        if is_boot:
            bind[rows] = blended_bind(Pw[rows], W4[rows])        # the band and shaft: exact (above)
        normals = None
        if shoe.normals is not None:
            n = np.asarray(shoe.normals, np.float64) @ np.linalg.inv(M[:3, :3])    # inverse transpose
            if height is not None:                          # through the frame, the height map (4b), the placement
                nf = np.asarray(shoe.normals, np.float64) @ np.linalg.inv(FrameM[:3, :3])
                n = upper_height_map(_apply(FrameM, S_pos), insole, height, nf)[1] @ np.linalg.inv(w["Pf"][:3, :3])
            if is_boot and turn is not None:                # the band and shaft turned with the positions (9a)
                n[turn["rows"]] = _rodrigues(n[turn["rows"]], turn["axis"], turn["s"] * turn["angle"])
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
            # else no measure (None — never a vacuous 0.0; Ruling 8b); a clipped shaft is measured up to the clip
            # (what is served — the clipped-off top no longer exists)
            served = ((yf <= clip_y - frame0 + 1e-9 if turn is None else turn["P"][:, 1] <= clip_y + 1e-9)
                      if clip_m > 0.0 else np.ones(n_v, bool))
            ring = (yf > y_split + SHAFT_RING_ABOVE_M) & served
            follow_ring: Optional[str] = "top"
            if int(ring.sum()) < FOLLOW_RING_MIN:
                shaft_v = (yf > y_split + SPLIT_BAND_M) & served
                follow_ring = None
                if shaft_v.any():
                    ring = (yf >= 0.5 * (float(yf[shaft_v].max()) + y_split + SPLIT_BAND_M)) & served
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
                              ("seam_stretch_max", "seam_stretch_max"), ("leg_follow_deg", "shaft_leg_follow_deg"),
                              ("clip_m", "shaft_clip_m"), ("knee_margin_m", "knee_margin_m")):
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
            if is_boot and shaft_rec["clip_m"] > 0.0:
                # 10. the knee clip: everything of the shaft part above the plane goes, the crossing faces are
                # bisected ON it (``footwear_cut.plane_cut``, exact secant root); above the band the bind position
                # IS the stand (Leg / UpLeg stand in the bind pose), and the clipped ring keeps the shaft's Leg /
                # UpLeg weights — it rides the Leg bone like the rest of the shaft
                from app.core.footwear_cut import plane_cut
                from app.core.garment_layers import _mesh_prim, _prim_mesh
                cut_prim, cut_stats = plane_cut(_mesh_prim(side_parts["shaft"]), y_m=clip_y, keep="below")
                side_parts["shaft"] = _prim_mesh(cut_prim, side_parts["shaft"])
                shaft_rec["clip"] = dict(cut_stats)
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
            "foot_len_m": fm.length_m, "toe_x_m": w["toe_x_raw"] * k, "foot_w_ball_mm": w["fw_ball"] * 1000.0,
            "insole_w_ball_mm": w["iw_ball"] * 1000.0, "toe_room_mm": w["toe_room_mm"], "contacts": recs,
            "split": {"is_boot": is_boot, "y_m": y_split, "band_m": SPLIT_BAND_M, "margin_m": SPLIT_MARGIN_M,
                      "topline_m": topline_m, "collar_above_ankle_mm": collar_above,
                      # the collar AFTER the knee clip (step 10): a clipped shaft's top is the clip plane
                      # (a turned shaft's collar is its rim's lowest point after the clip, step 9a)
                      "collar_m": (None if not is_boot else collar_bind - frame0 if turn is not None
                                   else float(collar_raw) * k if not shaft_rec["clip_m"]
                                   else shaft_rec["clip_y_m"] - frame0),
                      "collar_bind_m": (None if not is_boot else collar_bind if turn is not None
                                        else float(_apply(w["Pf"], np.array([0.0, float(collar_raw), 0.0]))[1])
                                        if not shaft_rec["clip_m"] else shaft_rec["clip_y_m"])},
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
        # the worse side: the largest value, except the knee margin (the smaller one)
        metrics.update({name: ((min if name in WORST_IS_MIN else max)(values) if values else None)
                        for name, values in shaft_metrics.items()})
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
            "width_needed": needed, "width_cap": width_cap, "width_cap_applied": cap_applied, "slim_needed": slim,
            "height_factor": height_factor, "height_needed": height_needed, "height": height,
            "height_ready": height_ready, "instep_roof_share": instep_roof, "height_worst": height_worst,
            "insole_arc_m": ins.arc_at(x_end) * k, "foot_len_m": foot_len, "toe_h_m": toe_h,
            **({"allowance": {"width_pct": round(width_share * 100.0, 6), "length_pct": round(length_share * 100.0, 6),
                              "heel_room_m": heel_room, "size": size}} if width_share or heel_room else {}),
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
            # the mesh against its own image (``footwear_gates.image_agreement``, insole step): ``too_flat_reason``
            "image": insole.get("image"),
        },
        "split": {"is_boot": any_split, "band_m": SPLIT_BAND_M, "margin_m": SPLIT_MARGIN_M},
        "shaft": {
            "class": shaft_in.get("class"), "cap_removed": shaft_in.get("cap_removed"),
            "closed_share": shaft_in.get("closed_share"), "top_m": topline_m,
            **{key: (((min if name in WORST_IS_MIN else max)(shaft_metrics[name])) if shaft_metrics[name] else None)
               for key, name in (
                ("push_p95_m", "shaft_push_p95_m"), ("push_max_m", "shaft_push_max_m"),
                ("inside_share", "shaft_inside_share"), ("seam_gap_p95_mm", "seam_gap_p95_mm"),
                ("seam_stretch_max", "seam_stretch_max"), ("leg_follow_deg", "shaft_leg_follow_deg"),
                ("clip_m", "shaft_clip_m"), ("knee_margin_m", "knee_margin_m"))},
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
