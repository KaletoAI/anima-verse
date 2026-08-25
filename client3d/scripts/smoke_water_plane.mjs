#!/usr/bin/env node
/**
 * Smoke check for the WATER PROFILE and the SHORE ("Ein Boden" E4, § G4;
 * tilted by "Ein Wasser-Gesetz" W2) — the level of a painted water at a point,
 * the shore curves that come out of the height data, the E1 carve invariant
 * measured from the CLIENT side, and the wade/swim crossover against the LOCAL
 * level.
 *
 * Usage:  node client3d/scripts/smoke_water_plane.mjs
 *         (transpiles `scene/waterPlaneMath.ts` and `game/walk.ts`; needs esbuild)
 *
 * WHAT LEFT WITH WASSER v2 K-A E5. The water used to be a MESH of its own — a
 * ruled surface over the outline, cut at the axis knots, every vertex lifted
 * onto the profile, with a shore shader chained onto its material. The terrain
 * lifts and shades its own water pixels now (E3/E4), so the sections that
 * checked the mesh are gone with it: [4c]/[4d-flow]/[4e-flow]/[4f] (the
 * per-vertex flow — the server bakes the flow into the raster), [5]/[5b] (the
 * lift), [5c]/[5d] (the strip subdivision and the arrangement) and [2c] (the
 * shore GLSL). What stayed is what still has a reader: the profile itself, the
 * shore CURVES (`scene/waterShade.ts` shades the terrain with them,
 * `smoke_water_shade.mjs` checks that half), the carve invariant, and the
 * gameplay. [8] now also counts the deleted names as RED probes.
 *
 * The server halves are `scripts/smoke_height_bake.py` [8] (the profile and the
 * carve, on the bake) and `scripts/smoke_heightfield.py`. This is the READING:
 * the same formula, the same numbers, in the renderer. Every expected value
 * below is derived BY HAND in this docstring (§ B5a) — nothing here is a
 * recording of current output.
 *
 * ===========================================================================
 * [1] THE WATER IS A PROFILE, and it comes from the payload alone
 * ===========================================================================
 * `waterProfileOf(meta)` reads `meta.water_profile` — the numbers the bake
 * carved the bed against (W1 § 4, polyline since W4a). Reading it is the WHOLE
 * water test: only an area the server's one predicate called water carries one.
 * Its readers today are the gameplay (`floatRootY`, `typeAt`), the waterfall
 * detection and the look table — never a mesh.
 *
 *     { water_profile: {…nine + axis…} }  -> a profile      water
 *     { water_level_effective: 3.25 }     -> null           the MID level of a
 *                                                           profile is not one
 *     { water_level: 3.25 }               -> null           AUTHORED, not baked
 *     { }                                 -> null           not water
 *
 * The second one is new in W2 and load-bearing. `water_level_effective` is the
 * one plane a FLAT consumer draws, i.e. the mid level; a client that still read
 * it would put a river's water line 2.4 m over its bed at one end and 2.4 m
 * under it at the other (see [6] for that arithmetic, in full).
 *
 * A profile with one unreadable number is NO profile: one NaN in a vertex
 * position and the whole mesh leaves the frustum. `flow_dir_deg: null` is the
 * one exception — that is the shape of still water. THE `axis` IS CHECKED THE
 * SAME WAY (W4a) and it is the part that is actually evaluated: a list of at
 * least one `[x, z, s, level]` of finite numbers, or there is no water.
 *
 * ===========================================================================
 * [2] THE SHORE — how much of the bed is hidden, out of the DEPTH
 * ===========================================================================
 * `depth(x, z) = water level − h(x, z)`, both out of the SAME R32F pyramids the
 * terrain's vertices are placed by (the height one and, since K-A E1/E2, the
 * water one). The alpha ramps over the AREA's OWN opaque
 * depth (W4b) — ¾ of its bed depth, `waterOpaqueDepthM` — by `smoothstep`,
 * i.e. `t = depth/band` and `3t² − 2t³`. For the DEFAULT LAKE (`water_depth_m`
 * 2.0, band 1.5):
 *
 *     depth 0.15  -> t = 0.1  -> 3·0.01   − 2·0.001    = 0.028
 *     depth 0.30  -> t = 0.2  -> 3·0.04   − 2·0.008    = 0.104
 *     depth 0.375 -> t = 0.25 -> 3·0.0625 − 2·0.015625 = 0.15625
 *     depth 0.75  -> t = 0.5  -> 3·0.25   − 2·0.125    = 0.5
 *     depth 1.125 -> t = 0.75 -> 3·0.5625 − 2·0.421875 = 0.84375
 *     depth 1.5   -> t = 1                             = 1
 *     depth 4.0   -> clamped                           = 1
 *
 * …and for the SEEDED RIVER (`water_depth_m` 1.2, so ¾ = 0.9 — FLOORED to the
 * 1.0 m of `WATER_MIN_SEE_DEPTH_M`, the user's bed rule of 2026-08-25) the same
 * six fractions of THAT band:
 *
 *     depth 0.1   -> t = 0.1                           = 0.028
 *     depth 0.2   -> t = 0.2                           = 0.104
 *     depth 0.25  -> t = 0.25                          = 0.15625
 *     depth 0.5   -> t = 0.5                           = 0.5
 *     depth 0.75  -> t = 0.75                          = 0.84375
 *     depth 1.0   -> t = 1                             = 1
 *
 * THE FLOOR IS A RULE, NOT A TWEAK: `max(1 m, ¾ · depth)`. The bed of a water
 * has to stay readable down to at least a metre of depth, so every water
 * shallower than 4/3 m opens its band to that metre and a water shallower than
 * the metre — a 0.6 m pond — NEVER reaches full absorption at all
 * (`3·0.36 − 2·0.216` = 0.648, so 35.2 % of its bed still shows at its
 * deepest). Every water deeper than 4/3 m is untouched: the lake's 1.5 m stands.
 *
 * WHY ¾. The E1 carve reaches `water_depth_m` over a `shore_ramp_m` ramp by the
 * very same smoothstep, so ¾ of the depth is `smoothstep = 0.75`, i.e.
 * `3t² − 2t³ = 0.75`. Solving by hand: t = 0.67 gives 0.7450, t = 0.68 gives
 * 0.7581, so t ≈ 0.6736 — AT THE SAME FRACTION OF THE RAMP, whatever the depth
 * is. The default lake is therefore fully drawn `0.6736 · 3 = 2.02 m` inside its
 * outline, the seeded river `0.6736 · 1.0 = 0.674 m` inside its bank, i.e. over
 * 4.65 m of its 6 m width. Each fades in over the first two thirds of the ramp
 * the author drew and is fully drawn by the time its bed levels off.
 *
 * THE RED COUNTER-PROBE IS W4b ITSELF: with the OLD constant band of 1.5 m the
 * river's deepest water, 0.9 m, read `t = 0.6` -> `3·0.36 − 2·0.216 = 0.648` —
 * 65 % opaque in the MIDDLE of the river, which is the "am Rand zu durchsichtig"
 * finding, seen from the arithmetic. A shallow pond authored with
 * `water_depth_m = 0.6` still never reaches 1 against the LAKE's band
 * (`waterShoreAlpha(0.6, 1.5)` = 0.352) — but against its OWN band of 0.45 m it
 * does, which is what a pond with a visible bottom actually looks like.
 *
 * The FOAM is `1 − smoothstep(0, 0.6, depth)` — full at the rim, gone at
 * 0.6 m — and it whitens the outgoing light by `foam · 0.6`:
 *
 *     depth 0.0  foam 1        ramp 0
 *     depth 0.15 foam 0.84375  ramp 0.028
 *     depth 0.3  foam 0.5      ramp 0.104
 *     depth 0.45 foam 0.15625  ramp 0.216
 *     depth 0.6  foam 0        ramp 0.352
 *     depth 1.5  foam 0        ramp 1
 *
 * (`waterShoreAlpha(0.45)`: t = 0.3, 3·0.09 − 2·0.027 = 0.27 − 0.054 = 0.216.)
 * The 0.15 of alpha the foam used to hand back at the very rim was the MIRROR's
 * (a transparent sheet had to stay visible at its own edge); the terrain's
 * water is opaque ground, so it went with the mesh in K-A E5.
 *
 * ===========================================================================
 * [3] THE E1 INVARIANT, measured on THIS side — and its red counter-probe
 * ===========================================================================
 * The bake carves, per point inside the polygon (W1 § 3):
 *
 *     h = min( h_nat, level_at(x, z) − depth_m · smoothstep( min(d_in/ramp_m, 1) ) )
 *
 * `d_in` is the distance to the OUTLINE, `min` and never an assignment. The
 * invariant the contract states, PUNCTUALLY since W1: beyond the ramp,
 * `h ≤ level_at(x, z) − ε` with `ε = min(depth_m, 0.25)`.
 *
 * THE COUNTER-PROBE IS THE POINT, and it is a proof and not a sample. Beyond
 * the ramp `smoothstep(1) = 1` exactly, so the second argument of the `min` is
 * `level_at(x, z) − depth_m` — whatever the natural ground does there. A bump
 * of +40 m in the middle of the lake therefore comes out at that number all the
 * same: a terrain texel above the water inside the deep zone is not unlikely,
 * it is arithmetically impossible. Sampling could only ever have said "not in
 * these 4 489 probes"; this says "never".
 *
 * With the default lake at level 3.0, `depth_m = 2.0`, `ramp_m = 3.0`:
 *
 *     d_in 0.0  smoothstep(0)      = 0        -> min(h_nat, 3.0)
 *     d_in 0.75 smoothstep(0.25)   = 0.15625  -> min(h_nat, 2.6875)
 *     d_in 1.5  smoothstep(0.5)    = 0.5      -> min(h_nat, 2.0)
 *     d_in 2.25 smoothstep(0.75)   = 0.84375  -> min(h_nat, 1.3125)
 *     d_in 3.0  smoothstep(1)      = 1        -> min(h_nat, 1.0)
 *     d_in 40   clamped            = 1        -> min(h_nat, 1.0)
 *
 * ε = min(2.0, 0.25) = 0.25, and 3.0 − 1.0 = 2.0 ≥ 0.25 holds with 1.75 m to
 * spare. AT THE RIM (d_in = 0) the carve is `min(h_nat, level)`, which is the
 * water meeting the terrain — that IS the shoreline, and it is why the shore
 * curves all answer "not water" at `depth ≤ 0`.
 *
 * ===========================================================================
 * [4] THE FIXTURE RIVER — the profile arithmetic, hand-derived end to end
 * ===========================================================================
 * The SAME fixture the server smoke derives (`scripts/smoke_height_bake.py`
 * [8]); the numbers are re-derived here rather than imported, so the two halves
 * of one formula are checked against the contract and not against each other.
 *
 *   the shape        rectangle (20,−40) (80,−40) (80,−20) (20,−20)
 *   the landscape    NATURAL(x, z) = x/10, z-independent
 *   the kind         water_depth_m 1.0, shore_ramp_m 3.0
 *   the flow         flow_dir_deg 270
 *
 * THE DIRECTION. A bearing is spelled `dir = (sin θ, cos θ)` (§ A1.1), so
 * 270° is (sin 270°, cos 270°) = (−1, 0): the water flows toward −x, downhill.
 *
 * THE AXIS. The centroid is (50, −30), so
 *
 *     s(x, z) = (x − 50)·(−1) + (z + 30)·0 = 50 − x
 *
 * — z drops out entirely, which is why every check below can name one x. Over
 * the polygon s runs from −30 (at x = 80, the UPSTREAM extreme) to +30 (at
 * x = 20, the DOWNSTREAM one), so `s_min = −30`, `s_max = 30`, span 60.
 *
 * THE TWO ENDS come from the rim median of the outer THIRD of that span, which
 * the server smoke derives from 31 rim samples per end: `level_up = 7.4`,
 * `level_down = 2.6`. Those two numbers are the fixture's input here.
 *
 * THE PROFILE, written out:
 *
 *     t         = (s − s_min)/span = (50 − x + 30)/60 = (80 − x)/60
 *     level(x)  = 7.4 + (2.6 − 7.4)·(80 − x)/60
 *               = 7.4 − 0.08·(80 − x)
 *               = 0.08·x + 1.0
 *
 *     x = 20 -> 2.6     the downstream rim (t = 1, the clamp, EXACTLY level_down)
 *     x = 26 -> 3.08
 *     x = 35 -> 3.8
 *     x = 50 -> 5.0     the centroid — and the MID level of the profile
 *     x = 74 -> 6.92
 *     x = 80 -> 7.4     the upstream rim (t = 0, the clamp, EXACTLY level_up)
 *     x = 200 -> 7.4    past the upstream extreme: clamped
 *     x = −200 -> 2.6   past the downstream one: clamped
 *
 * THE NINE NUMBERS as the payload ships them:
 *
 *     level_up 7.4  level_down 2.6  flow_dir_deg 270
 *     axis_x 50  axis_z −30  dir_x −1  dir_z 0  s_min −30  s_max 30
 *
 * …AND THE AXIS BESIDE THEM (W4a), which is what is read: this straight river
 * is the polyline with TWO knots, the two extremes of the polygon ON the axis,
 * each carrying its own end level (`heightfield._straight_profile`):
 *
 *     axis = [ [80, −30, −30, 7.4], [20, −30, 30, 2.6] ]
 *
 * and the polyline rule REPRODUCES the three lines above, which is the whole
 * claim of "the old law is the two-knot case". By hand, for a point (x, z):
 * the segment runs (80, −30) -> (20, −30), so
 *
 *     u = ((x − 80)·(−60) + (z + 30)·0) / 60²  =  (80 − x)/60,  clamped
 *     s = −30 + 60·u = 50 − x                  — the W1 projection, verbatim
 *     level = 7.4 + (2.6 − 7.4)·(s + 30)/60 = 0.08·x + 1.0
 *
 * z drops out of BOTH readings for the same reason (the foot of the
 * perpendicular has the same `s` whatever z is), and at the two rims the clamp
 * answers the knot's own level bit-exactly rather than a lerp with t = 0 or 1.
 *
 * THE CARVE against that LOCAL level, depth 1.0 over a 3 m ramp — the bed is
 * `level(x) − 1.0` wherever the ramp is through, i.e. `0.08·x`:
 *
 *     (50,−30) d_in = 10 ≥ 3      -> 5.00 − 1.0            = 4.0
 *     (26,−30) d_in =  6          -> 3.08 − 1.0            = 2.08
 *     (74,−30) d_in =  6          -> 6.92 − 1.0            = 5.92
 *     (22,−30) d_in =  2, t = 2/3 -> smoothstep = (4/9)(3 − 4/3) = 20/27
 *                                 -> 2.76 − 20/27          = 2.0192592592592593
 *
 * ===========================================================================
 * [4d] THE HAIRPIN — a river follows its own LINE (W4a)
 * ===========================================================================
 * THE SAME FIXTURE the server smoke derives (`scripts/smoke_height_bake.py`
 * [8k]), re-derived here rather than imported. Three drawn points, flowed in
 * drawing order:
 *
 *     A = (150, 300)   B = (249, 280)   C = (201, 260)
 *
 * a hairpin: 99 m east and 20 m down-slope, then 48 m back west and 20 m down.
 *
 *     |AB| = √(99² + 20²) = √10201 = 101   -> s(B) = 101
 *     |BC| = √(48² + 20²) = √2704  = 52    -> s(C) = 153
 *
 * The landscape there is the plane `BOWL = (z − 200)/10`, and each knot's level
 * is the median of a cross section that is symmetric about the knot, i.e. the
 * knot's own height:
 *
 *     level(A) = 10      level(B) = 8      level(C) = 6
 *
 * so the axis the payload ships is
 *
 *     [[150, 300, 0, 10], [249, 280, 101, 8], [201, 260, 153, 6]]
 *
 * THE MIRROR AT A POINT, by the rule "nearest point on the polyline, then
 * linear between the two knots it falls between":
 *
 *   AT THE MIDDLE KNOT (249, 280) — it lies on both legs at distance 0. The
 *   loop keeps the FIRST one to reach it (`d2 < best_d2` is strict), so
 *   s = 101 and the level is knot B's own: 8.0. Not 8 because it is the mean of
 *   10 and 6 — that it also is here is a coincidence of this landscape; it is 8
 *   because the knot says 8.
 *
 *   HALFWAY ALONG LEG 1, (199.5, 290): it sits ON that leg, so
 *     u = ((49.5)·99 + (−10)·(−20)) / 10201 = (4900.5 + 200)/10201 = 0.5
 *     s = 50.5   ->  level = 10 + (8 − 10)·(50.5/101) = 9.0
 *   (leg 2 is far off: its clamped foot is (210.37, 263.91), 28.3 m away.)
 *
 *   HALFWAY ALONG LEG 2, (225, 270): it sits ON leg 2 (u = 0.5, distance 0)
 *   while leg 1's foot is (227.88, 284.27), 14.6 m away, so
 *     s = 101 + 26 = 127  ->  level = 8 + (6 − 8)·(26/52) = 7.0
 *
 *   UPSTREAM OF THE FIRST KNOT, (150, 400): leg 1 projects to u < 0 and clamps
 *   back to A (100 m away), leg 2's foot is 148.8 m away, so s = 0 and the
 *   clamp of `axisLevelAt` answers A's level 10.0 — not an extrapolation up the
 *   valley.
 *
 * THE RED COUNTER-PROBE is the STRAIGHT W1 axis of the same river, i.e. exactly
 * what the nine numbers beside the knots say. Its axis is the chord
 * A -> C = (51, −40), |chord|² = 51² + 40² = 4201, and the middle knot projects
 * onto it at
 *
 *     u = ((249−150)·51 + (280−300)·(−40)) / 4201 = (5049 + 800)/4201 = 1.392…
 *
 * i.e. PAST the downstream end, where the clamp answers `level_down` = 6.0. The
 * bend of a hairpin has no place on its own chord — that is the whole finding.
 *
 * ===========================================================================
 * [4e] THE CLIFF — knots where the GROUND bends, not where the author clicked
 * ===========================================================================
 * THE REPORTED BUG (2026-08-24) and the server's answer to it, W5b: a river
 * drawn with TWO clicks over a 3 m plateau edge used to get exactly two knots,
 * one per click, so its water line was ONE straight ramp between them. It ramped
 * down long BEFORE the edge (the water sank into a slot with its own banks
 * towering over it — "the water is almost gone") and was still too high long
 * AFTER it (a slab standing in the air over the low ground — "a mound of
 * water").
 *
 * THE SERVER NOW SAMPLES THE DRAWN LINE every 2 m before it measures the
 * levels, and simplifies the result back to the knots the level actually bends
 * at (`scripts/smoke_height_bake.py` [8l] derives the whole chain by hand). For
 * the fixture there — plateau 3.0 up to x = 41, 0.0 past it, river (0,0) to
 * (100,0) — the payload that reaches this side is
 *
 *     axis = [[0,0,0,3], [40,0,40,3], [42,0,42,0], [100,0,100,0]]
 *
 * and every number below follows from the rule this file already checks
 * ("nearest point on the polyline, then linear between the two knots"):
 *
 *     x = 21, 31, 40   ->  3.0    the plateau's own level, flat to the lip
 *     x = 41           ->  1.5    halfway between the two knots that straddle
 *                                 the edge: 3 + (0 − 3)·(41 − 40)/2
 *     x = 42, 51, 100  ->  0.0    the low ground's own level
 *
 * THE RED COUNTER-PROBE is the two-knot axis, i.e. exactly what the clicks
 * alone gave: `level = 3 − 0.03·x`, so
 *
 *     x = 31 -> 2.07   0.93 m UNDER the 3 m plateau it crosses
 *     x = 51 -> 1.47   1.47 m OVER a ground of 0
 *
 * Both are the symptom, in metres, on the client's own reader.
 *
 * ===========================================================================
 * [6] THE WADE/SWIM CROSSOVER, at the LOCAL level
 * ===========================================================================
 * `root = max(groundY + sink, waterLevel)`; the body reference is always
 * `root − sink`, so `body = max(groundY, waterLevel − sink)`. The two branches
 * meet where `groundY + sink = waterLevel`, i.e. at a DEPTH of exactly `sink`.
 * `floatRootY` is unchanged by W2 — what changed is what is fed into it.
 *
 * With the swim depth `sink = 0.6` and a water line at `L = 3.0`:
 *
 *     depth  groundY  root                       body
 *     0.0    3.0      max(3.6, 3.0) = 3.6        3.0    wading at the rim
 *     0.3    2.7      max(3.3, 3.0) = 3.3        2.7    wading, feet on the bed
 *     0.6    2.4      max(3.0, 3.0) = 3.0        2.4    THE CROSSOVER
 *     1.2    1.8      max(2.4, 3.0) = 3.0        2.4    swimming
 *     2.0    1.0      max(1.6, 3.0) = 3.0        2.4    swimming
 *
 * ON THE FIXTURE RIVER, where the bed is `0.08·x` and the local level is
 * `0.08·x + 1.0`, the DEPTH is 1.0 m at every metre of the river's length. So
 * with `sink = 0.6` the figure swims EVERYWHERE, and its body hangs 0.6 m under
 * whatever water line it is at:
 *
 *     x = 26   bed 2.08   level 3.08   root 3.08   body 2.48
 *     x = 74   bed 5.92   level 6.92   root 6.92   body 6.32
 *
 * THE RED COUNTER-PROBE — the flat mid level, which is what a pre-W2 client
 * read (`water_level_effective` = 5.0):
 *
 *     x = 26   root max(2.08 + 0.6, 5.0) = 5.0    1.92 m ABOVE the water it sees
 *     x = 74   root max(5.92 + 0.6, 5.0) = 6.52   feet on the bed: WADING,
 *                                                 in water 1.0 m deep
 *
 * and the crossover of the flat reading sits at ONE place instead of nowhere:
 * `5.0 − 0.08·x = 0.6` gives `x = 55`, so the swimmer would swim the lower half
 * of the river and walk the upper half of it. The local reading has no such
 * line, because the depth never changes.
 *
 * ===========================================================================
 * [7] THE SHORE ON A SLOPE — why the shore arithmetic needed no change
 * ===========================================================================
 * The depth is `level(x, z) − h(x, z)`, i.e. the LOCAL level minus the ground,
 * at every point — the profile for the gameplay, the raster the server baked
 * out of that very profile for the render. The shore therefore measures against
 * the local level for free, and on the fixture river it answers the same
 * absorption at every x:
 *
 *     depth 1.0 everywhere -> t = 1/1.5 = 2/3
 *                          -> 3·(4/9) − 2·(8/27) = 4/3 − 16/27 = 20/27
 *                          = 0.7407407407407407
 *
 * THE RED COUNTER-PROBE, again the flat plane at 5.0: its depth is
 * `5.0 − 0.08·x`, which reaches 0 at `x = 62.5` and is NEGATIVE above it. A
 * flat reading would therefore see no water at all over the river's upper
 * 17.5 m — the bed standing above its own level — while below x = 62.5 it would
 * hide the bed under up to 2.92 m of false depth (`waterShoreAlpha(2.92) = 1`,
 * fully absorbed) over ground 1 m under the real line.
 *
 * ===========================================================================
 * [9] THE RIPPLE SCROLLS DOWNSTREAM (W2 no. 2)
 * ===========================================================================
 * The wave normal map is sampled twice and both lookups drift. The drift
 * direction is built in the FLOW's frame: `wAx` downstream, `wAy = (−wAx.y,
 * wAx.x)` across it. With no flow (`vWaterFlow = (0, 0)` — a lake, an ice
 * sheet, or any surface that carries no attribute at all) the frame is the
 * world's own axes, and the two vectors come out as the constants that stood in
 * this shader before:
 *
 *     wAx = (1, 0), wAy = (0, 1)
 *     A =  wAx + wAy·0.6            = ( 1.0,  0.6)
 *     B = −(wAx·0.8 + wAy·1.3)      = (−0.8, −1.3)
 *
 * WITH a flow BOTH layers go downstream and only their CROSS component
 * opposes — a river whose second layer ran upstream would read as two rivers.
 * The cross factors are NOT the lake's, though (user finding 2026-08-23, "the
 * flow direction is not clearly recognisable"): 0.6 and 1.3 against along
 * components of 1.0 and 0.8 put the two sheets 31° and 58° off the flow, and a
 * layer travelling 58° off the stream is the diagonal shimmer the finding
 * names. Flowing water keeps the along components and shrinks the cross ones:
 *
 *     A = wAx + wAy·0.15 ,  B = wAx·0.8 − wAy·0.3
 *
 *     atan(0.15 / 1.0) =  8.5308…°      atan(0.3 / 0.8) = 20.5560…°
 *
 * — both plainly downstream, still of OPPOSITE SIGN and different magnitude,
 * so the two sheets go on beating against one another.
 *
 * The fixture river flows 270°, i.e. `dir = (−1, 0)`, so `wAx = (−1, 0)` and
 * `wAy = (−0, −1) = (0, −1)`:
 *
 *     A = (−1, 0) + (0, −0.15)  = (−1.0, −0.15)  · flow = +1.0   downstream
 *     B = (−0.8, 0) − (0, −0.3) = (−0.8,  0.30)  · flow = +0.8   downstream
 *
 * THE STILL LENGTHS ARE UNTOUCHED, and that is a rotation argument: `|A| =
 * √1.36` and `|B| = √2.33` whichever way a LAKE's frame points, so `uSpeed`
 * still means the metres per second it always meant. A river's layers are
 * shorter by construction — `|A| = √1.0225`, `|B| = √0.73` — and since A's
 * along component is exactly 1.0, `uFlowSpeed` IS the downstream metres per
 * second of the leading sheet, with B following at 0.8 of it. Two more
 * bearings, by the same arithmetic:
 *
 *     0°  dir (0, 1):   wAx = ( 0, 1), wAy = (−1, 0)
 *                       A = (−0.15, 1.0)  B = ( 0.3, 0.8)   both +z
 *     90° dir (1, 0):   wAx = ( 1, 0), wAy = ( 0, 1)
 *                       A = ( 1.0, 0.15)  B = ( 0.8, −0.3)  both +x
 *
 * ===========================================================================
 * [9c] TWO SPEEDS, A STRETCHED RIPPLE, AND A STREAK (finding 2026-08-23)
 * ===========================================================================
 * ONE SPEED COULD NOT SERVE BOTH. A lake counter-scrolls its layers, so they
 * cancel and 0.25 m/s reads slow; a river sends both downstream, where the
 * same 0.25 reads several times faster. That is why there are two dials — it
 * is no longer why the flowing one is the smaller: since 2026-08-25 the flow
 * default is 0.5 m/s, twice the lake's, by user decision. So `speed` stays the
 * still number and `flow_speed` (default 0.5 m/s, `uFlowSpeed`) is the flowing one;
 * the shader picks per pixel, `wSpeed = wStill ? uSpeed : uFlowSpeed · wLen`,
 * where the length is the AREA's own factor ([9e]) and 1 unless it says
 * otherwise.
 *
 * ANISOTROPY. The wave normal map is isotropic — circles, not streaks. The
 * stretch therefore happens in the LOOKUP: the sample coordinate is projected
 * into the flow frame and its ALONG component divided by 3, so a crest comes
 * out three times as long as it is wide. On the default `wave_m` 1.6 that is
 * 1.6 m across the stream against 4.8 m along it.
 *
 * AND THE SIGN, which is the other half of "the direction is not clearly
 * recognisable": adding `v·t` to a SAMPLE coordinate slides the picture the
 * OTHER way — `uv + vec2(t, 0)` is the classic LEFTWARD scroll — so the offset
 * that has stood here since the lake was written carried the crests AGAINST
 * `wDirA`, i.e. UPSTREAM on a river. Flowing water drifts by `wFlowSign = −1`;
 * still water keeps `+1`, because a lake has no reference direction (its two
 * sheets counter-scroll either way) and the requirement is that it looks
 * exactly as before, not that it agrees about a sign nobody can see on it.
 *
 * AND THE STRETCH IS FREE OF SPEED, because the squeeze `S` is LINEAR and is
 * applied to the WHOLE coordinate, drift included:
 *
 *     uv(p, t) = S( p/λ + dir·(σ·t·s/λ) ) = S( (p + dir·σ·s·t) / λ )
 *
 * so a feature at `p` at time `t` sits at `p − dir·σ·s·dt` at `t + dt`,
 * whatever S does — with `σ = −1` that is `p + dir·s·dt`, DOWNSTREAM, at
 * `s·|dir|` metres per second. Checked numerically below with λ = 1.6,
 * s = 0.08, t = 7, dt = 2.5, p = (12, −4): the two coordinates must come out
 * EQUAL, not merely close.
 *
 * THE STREAK LAYER is the same map read as a ribbon: `(world + wAx·t·s)/(2λ)`,
 * then squeezed by 8 along the flow. Its crests repeat every `2λ = 3.2 m`
 * ACROSS the stream and every `2λ·8 = 25.6 m` ALONG it — lines parallel to the
 * current, sliding downstream at the same `s`, so the direction reads even in
 * flat light where no highlight moves. Weight 0.35 against the two
 * full-strength sheets, and EXACTLY 0.0 when still, which is what keeps a lake
 * bit for bit the lake it was: `x + (…)·0.0 == x` for every finite `x`, and a
 * texture sample, being `2·[0,1] − 1`, is always finite.
 *
 * ===========================================================================
 * [9e] ONE AREA MAY RUN FASTER THAN ITS KIND (finding 2026-08-23 no. 2)
 * ===========================================================================
 * `flow_speed` is the KIND's dial, raised to 0.15 m/s in the same round ("the
 * river now moves too slowly") and to 0.5 m/s by user decision on 2026-08-25.
 * A single painted area may override it with
 * `meta.flow_speed_m_s`, and that override travels as the LENGTH of
 * `aWaterFlow`: the attribute has been a UNIT tangent since W4a, so the shader
 * reads `wSpeed = uFlowSpeed · wLen` and nothing already built changes by one
 * bit. The encoder is `waterFlowFactor` (`@anima/scene-render`), the ratio
 * `area m/s ÷ kind m/s`, on the fixture river whose tangent is exactly (−1, 0):
 *
 *     no override -> 1      -> 0.5 · 1      = 0.5 m/s    (the unit tangent)
 *     0.45 m/s    -> 0.9    -> 0.5 · 0.9    = 0.45 m/s
 *     0.03 m/s    -> 0.06   -> 0.5 · 0.06   = 0.03 m/s
 *     0 m/s       -> 1e-3   -> 0.5 · 1e-3   = 0.5 mm/s
 *
 * WHY THE LENGTH AND NOT A FLOAT OF ITS OWN: a geometry that carries no such
 * attribute reads its generic value, and for a float that is 0 — which would
 * multiply every water that never heard of the field down to a standstill. The
 * flow's generic value is (0, 0), which the shader already spells "still", so
 * the one encoding that needs no migration is the one that costs no attribute.
 *
 * AND WHY THE FLOOR: `wStill` is `wLen < 1e-4`, so a zero-length vector is a
 * LAKE — and a lake drifts at `uSpeed` = 0.25 m/s, which is not a standstill
 * either way (it used to be three times the river's dial, since 2026-08-25 it
 * is half of it), in a crossing pattern instead of streaks. An authored 0 m/s
 * is therefore floored to 1e-3, ten times the threshold: 0.5 mm/s, one 1.6 m
 * wavelength in 1.6/0.0005 = 3200 s, a river that stands still and stays a
 * river.
 * The direction survives all of it untouched — the shader divides by the very
 * length it multiplies by.
 */
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');

/** Both files under test are import-free by design (their headers say so), so
 *  a transpile is all it takes. Should someone add a runtime import, this
 *  fails loudly instead of quietly testing something else. */
async function loadPure(...relPaths) {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'waterplane-'));
  try {
    const mods = [];
    for (const [i, rel] of relPaths.entries()) {
      const source = await readFile(join(ROOT, rel), 'utf8');
      const code = esbuild.transformSync(source, { loader: 'ts', format: 'esm' }).code;
      const file = join(dir, `m${i}.mjs`);
      await writeFile(file, code, 'utf8');
      mods.push(await import(`file://${file}`));
    }
    return mods;
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

let failed = 0;
let passed = 0;
function check(label, actual, expected, eps = 1e-9) {
  const ok = typeof actual === 'number' && Math.abs(actual - expected) <= eps;
  if (ok) {
    passed += 1;
    console.log(`  ok   ${label} = ${actual}`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}\n       expected ${expected}\n       actual   ${actual}`);
  }
}
function checkEq(label, actual, expected) {
  const a = JSON.stringify(actual);
  const b = JSON.stringify(expected);
  if (a === b) {
    passed += 1;
    console.log(`  ok   ${label} = ${a}`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}\n       expected ${b}\n       actual   ${a}`);
  }
}
/** A vector, component by component and with a tolerance — `Math.hypot` is not
 *  required to return the exact integer even where the triple is Pythagorean,
 *  so a normalised tangent is "close", never "the same string". */
function checkVec(label, actual, expected, eps = 1e-12) {
  const ok = Array.isArray(actual) && actual.length === expected.length
    && actual.every((v, i) => Math.abs(v - expected[i]) <= eps);
  if (ok) {
    passed += 1;
    console.log(`  ok   ${label} = ${JSON.stringify(actual)}`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}\n       expected ${JSON.stringify(expected)}\n       actual   ${JSON.stringify(actual)}`);
  }
}
/** Bit equality, for the claims that say "the same float" and not "close". */
function checkIs(label, actual, expected) {
  if (Object.is(actual, expected)) {
    passed += 1;
    console.log(`  ok   ${label} = ${actual}`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}\n       expected exactly ${expected}\n       actual          ${actual}`);
  }
}

const [W, walk, mats] = await loadPure('client3d/src/scene/waterPlaneMath.ts',
                                       'client3d/src/game/walk.ts',
                                       'packages/scene-render/src/materials.ts');
const { WATER_EDGE_FADE_M, WATER_FOAM_BAND_M, WATER_FOAM_STRENGTH,
  WATER_MIN_SEE_DEPTH_M,
  waterEdgeFade, waterFoam, waterLevelAt, waterOpaqueDepthM,
  waterProfileOf, waterShoreAlpha } = W;
const { floatRootY, groundWaterLevel } = walk;
// The shared package's own half of the flow encoding — the factor the length of
// the flow vector carries, which the SERVER bakes into the water raster since
// K-A E1. `materials.ts` imports nothing but types, so it loads the same way.
const { waterFlowFactor, WATER_FLOW_FACTOR_MIN,
  WATER_FLOW_SPEED_DEFAULT_M_S } = mats;

// ── The fixture, as the payload ships it ───────────────────────────────────
/** The nine numbers of the fixture river and its TWO-KNOT axis (docstring [4]).
 *  `water_depth_effective` is the bake's own bed depth for this area (W4b). */
const RIVER_META = { flow_dir_deg: 270, water_level_up: 7.4,
  water_level_down: 2.6, water_level_effective: 5.0,
  water_depth_effective: 1.0,
  water_profile: { level_up: 7.4, level_down: 2.6, flow_dir_deg: 270.0,
    axis_x: 50.0, axis_z: -30.0, dir_x: -1.0, dir_z: 0.0,
    s_min: -30.0, s_max: 30.0,
    axis: [[80.0, -30.0, -30.0, 7.4], [20.0, -30.0, 30.0, 2.6]] } };
/** A still lake at 3.25 — the degenerate profile: no bearing, empty span, and
 *  ONE knot, which is what makes the polyline rule answer one number. */
const LAKE_META = { water_level_effective: 3.25, water_depth_effective: 2.0,
  water_profile: { level_up: 3.25, level_down: 3.25, flow_dir_deg: null,
    axis_x: 12.0, axis_z: -4.0, dir_x: 0.0, dir_z: 0.0,
    s_min: 0.0, s_max: 0.0, axis: [[12.0, -4.0, 0.0, 3.25]] } };
/** The HAIRPIN of docstring [4d] — the same fixture as `smoke_height_bake.py`
 *  [8k], three knots, drawn with the line tool and flowed forward. */
const HAIRPIN_META = { water_depth_effective: 1.2,
  water_profile: { level_up: 10.0, level_down: 6.0, flow_dir_deg: 180.0
      - (Math.atan(51.0 / 40.0) * 180) / Math.PI,
    axis_x: 150.0, axis_z: 300.0, dir_x: 51.0 / Math.sqrt(4201),
    dir_z: -40.0 / Math.sqrt(4201), s_min: 0.0, s_max: Math.sqrt(4201),
    axis: [[150.0, 300.0, 0.0, 10.0], [249.0, 280.0, 101.0, 8.0],
      [201.0, 260.0, 153.0, 6.0]] } };
/** The CLIFF of docstring [4e] — the same payload `scripts/smoke_height_bake.py`
 *  [8l] derives on the server: TWO clicks over a 3 m step, and FOUR knots,
 *  because since W5b the line is sampled every 2 m and simplified back to where
 *  the level actually bends. Depth 1.0, the seeded river's bed. */
const CLIFF_META = { water_depth_effective: 1.0,
  stroke: { points: [[0, 0], [100, 0]], width_m: 6 },
  water_profile: { level_up: 3.0, level_down: 0.0, flow_dir_deg: 90.0,
    axis_x: 0.0, axis_z: 0.0, dir_x: 1.0, dir_z: 0.0,
    s_min: 0.0, s_max: 100.0,
    axis: [[0.0, 0.0, 0.0, 3.0], [40.0, 0.0, 40.0, 3.0],
      [42.0, 0.0, 42.0, 0.0], [100.0, 0.0, 100.0, 0.0]] } };

// ── [1] the profile comes from the payload ─────────────────────────────────
console.log('[1] the water is a PROFILE, and only the payload names it');
const RIVER = waterProfileOf(RIVER_META);
const LAKE = waterProfileOf(LAKE_META);
checkEq('the nine numbers arrive verbatim', RIVER, RIVER_META.water_profile);
checkEq('a still lake is a profile too, with an empty span', LAKE,
  LAKE_META.water_profile);
checkEq('the MID level alone is no profile — that is the flat client\'s number',
  waterProfileOf({ water_level_effective: 3.25 }), null);
checkEq('the AUTHORED level alone is none either',
  waterProfileOf({ water_level: 3.25 }), null);
checkEq('an area that is not water', waterProfileOf({}), null);
checkEq('no meta at all', waterProfileOf(undefined), null);
checkEq('a profile with one unreadable number is NO profile',
  waterProfileOf({ water_profile: { ...LAKE_META.water_profile,
    level_down: 'deep' } }), null);
checkEq('…and Infinity is not a height either',
  waterProfileOf({ water_profile: { ...LAKE_META.water_profile,
    axis_x: Infinity } }), null);
checkEq('a MISSING number is missing, not zero',
  waterProfileOf({ water_profile: { level_up: 1, level_down: 1 } }), null);
checkEq('junk in the slot is not a profile',
  waterProfileOf({ water_profile: 'yes' }), null);
check('a sea at world zero is still a profile',
  waterProfileOf({ water_profile: { ...LAKE_META.water_profile, level_up: 0,
    level_down: 0 } })?.level_up, 0);

console.log('\n[1b] the AXIS is checked like every other number (W4a)');
checkEq('the hairpin arrives with three knots, verbatim',
  waterProfileOf(HAIRPIN_META).axis, HAIRPIN_META.water_profile.axis);
checkEq('no axis at all is no water — it is what the level is read from',
  waterProfileOf({ water_profile: { ...LAKE_META.water_profile,
    axis: undefined } }), null);
checkEq('an EMPTY axis names no place either',
  waterProfileOf({ water_profile: { ...LAKE_META.water_profile, axis: [] } }),
  null);
checkEq('a knot short of a number is a broken axis',
  waterProfileOf({ water_profile: { ...LAKE_META.water_profile,
    axis: [[12, -4, 0]] } }), null);
checkEq('…and so is one carrying a NaN',
  waterProfileOf({ water_profile: { ...LAKE_META.water_profile,
    axis: [[12, -4, 0, 3.25], [20, -4, 8, NaN]] } }), null);
checkEq('junk in the axis slot is not an axis',
  waterProfileOf({ water_profile: { ...LAKE_META.water_profile,
    axis: 'downhill' } }), null);

// ── [2] the shore ──────────────────────────────────────────────────────────
console.log('\n[2] the shore ramp, out of the water DEPTH');
/** The default lake's band — what an area without a shipped depth falls back
 *  to, and the number every table below is derived against. */
const LAKE_BAND = waterOpaqueDepthM(2.0);
check('the band of the DEFAULT lake is ¾ of its 2.0 m bed', LAKE_BAND, 1.5);
check('the foam reaches 0.6 m', WATER_FOAM_BAND_M, 0.6);
check('the foam whitens by 0.6', WATER_FOAM_STRENGTH, 0.6);
check('alpha at depth 0 — not water, the pixel stays the dry ground it is',
  waterShoreAlpha(0, LAKE_BAND), 0);
check('alpha at depth 0.15', waterShoreAlpha(0.15, LAKE_BAND), 0.028);
check('alpha at depth 0.30', waterShoreAlpha(0.30, LAKE_BAND), 0.104);
check('alpha at depth 0.375', waterShoreAlpha(0.375, LAKE_BAND), 0.15625);
check('alpha at depth 0.45', waterShoreAlpha(0.45, LAKE_BAND), 0.216);
check('alpha at depth 0.60', waterShoreAlpha(0.60, LAKE_BAND), 0.352);
check('alpha at depth 0.75 — half, exactly, always',
  waterShoreAlpha(0.75, LAKE_BAND), 0.5);
check('alpha at depth 1.125', waterShoreAlpha(1.125, LAKE_BAND), 0.84375);
check('alpha at depth 1.5 — the band is through',
  waterShoreAlpha(1.5, LAKE_BAND), 1);
check('alpha at depth 4.0 — clamped, a deep lake is not deeper drawn',
  waterShoreAlpha(4, LAKE_BAND), 1);
check('a shallow pond (0.6 m bed) never reaches full opacity against the '
  + 'LAKE\'s band', waterShoreAlpha(0.6, LAKE_BAND), 0.352);
check('a bed ABOVE the water line is not water',
  waterShoreAlpha(-0.5, LAKE_BAND),
  0);

console.log('\n[2a] W4b: the band is the AREA\'s own ¾, not one constant');
/** The seeded river kind: 1.2 m of bed, so 0.9 m of it are opaque. */
const RIVER_BAND = waterOpaqueDepthM(1.2);
check('a 1.2 m river is fully drawn at 1.0 m — ¾ is 0.9, the FLOOR wins',
  RIVER_BAND, 1.0);
check('a 0.6 m pond at the same floor, not at its own 0.45 m',
  waterOpaqueDepthM(0.6), 1.0);
check('4/3 m is the break-even — ¾ of it IS the floor',
  waterOpaqueDepthM(4 / 3), 1.0, 1e-15);
check('…and a hair deeper the fraction takes over again',
  waterOpaqueDepthM(1.4), 1.05, 1e-15);
check('the floor itself', WATER_MIN_SEE_DEPTH_M, 1.0);
check('the deepest lake the bake allows (20 m) at 15 m',
  waterOpaqueDepthM(20), 15);
check('a payload without the field falls back to the default lake',
  waterOpaqueDepthM(undefined), 1.5);
check('…and so does junk in it', waterOpaqueDepthM('deep'), 1.5);
check('…and a depth of zero, which is no water at all',
  waterOpaqueDepthM(0), 1.5);
check('a numeric STRING is a number — the payload is JSON either way',
  waterOpaqueDepthM('1.2'), 1.0);
// The same six fractions of the band as the lake's table above — the law is
// the fraction (with the metre floor under it), the metres are the area's.
check('river alpha at depth 0.1', waterShoreAlpha(0.1, RIVER_BAND), 0.028);
check('river alpha at depth 0.2', waterShoreAlpha(0.2, RIVER_BAND), 0.104);
check('river alpha at depth 0.25', waterShoreAlpha(0.25, RIVER_BAND),
  0.15625);
check('river alpha at depth 0.5 — half, exactly',
  waterShoreAlpha(0.5, RIVER_BAND), 0.5);
check('river alpha at depth 0.75', waterShoreAlpha(0.75, RIVER_BAND),
  0.84375);
check('river alpha at depth 1.0 — the band is through',
  waterShoreAlpha(1.0, RIVER_BAND), 1);
check('river alpha at its full 1.2 m — clamped',
  waterShoreAlpha(1.2, RIVER_BAND), 1);
check('RED: the OLD constant band drew that same deepest water at only',
  waterShoreAlpha(0.9, 1.5), 0.648);
check('…which is the "see-through in the middle of the river" finding, in one '
  + 'number: the river gains this much opacity',
  waterShoreAlpha(0.9, RIVER_BAND) - waterShoreAlpha(0.9, 1.5), 0.324,
  1e-15);
// THE FLOOR'S OWN RED PROBE (the bed rule, 2026-08-25). Under the bare ¾ rule
// the river went opaque at 0.9 m, i.e. its bed was gone at the depth a wading
// figure stands waist-deep in; with the floor 0.5 m of it still shows half the
// bed. The two numbers at 0.5 m of depth:
check('RED: at half a metre the ¾ rule had already hidden 0.58299 of the bed',
  waterShoreAlpha(0.5, 0.9), 0.5829903978052126, 1e-15);
check('…and the floored band hides exactly half of it',
  waterShoreAlpha(0.5, RIVER_BAND), 0.5);
check('a 0.6 m pond NEVER reaches full absorption — its own deepest point',
  waterShoreAlpha(0.6, waterOpaqueDepthM(0.6)), 0.648, 1e-15);
check('…i.e. this much of its bed is readable everywhere in it',
  1 - waterShoreAlpha(0.6, waterOpaqueDepthM(0.6)), 0.352, 1e-15);

console.log('\n[2b] the foam band');
check('foam at depth 0', waterFoam(0), 1);
check('foam at depth 0.15', waterFoam(0.15), 0.84375);
check('foam at depth 0.3', waterFoam(0.3), 0.5);
check('foam at depth 0.45', waterFoam(0.45), 0.15625);
check('foam at depth 0.6 — gone', waterFoam(0.6), 0);
check('foam at depth 2 — long gone', waterFoam(2), 0);
// The FOAM does not scale with the band (W4b): half a metre of broken water is
// half a metre of broken water, in a pond and in a lake — while the ramp under
// it is the area's own.
check('the river\'s rim carries the same foam as the lake\'s',
  waterFoam(0), 1);
check('…and at 0.3 m the foam is the same half-gone lace over both',
  waterFoam(0.3), 0.5);
// 0.3 m over the river's 1.0 m band is t = 0.3 -> 3·0.09 − 2·0.027 = 0.216,
// against the lake's t = 0.2 -> 0.104.
check('…while the ramp under it is already further along on the river',
  waterShoreAlpha(0.3, RIVER_BAND), 0.216, 1e-15);
check('…which is this much more of the bed hidden than over the lake',
  waterShoreAlpha(0.3, RIVER_BAND) - waterShoreAlpha(0.3, LAKE_BAND),
  0.112, 1e-15);

// ── [2d] the rim is faded, not merely discarded ────────────────────────────
// The foam is FULL at depth 0 and whitens the light by 0.6 there, so without a
// ramp the waterline would step from that white lace to dry ground across a
// boundary with no width — and a boundary with no width crawls sub-pixel as the
// camera moves. The fade is the one factor that reaches 0 exactly there. The
// GLSL that spends it is the terrain's (`smoke_water_shade.mjs` [3]).
console.log('\n[2d] the rim fades to the waterline instead of stepping to it');
check('the fade floor is 5 cm of depth', WATER_EDGE_FADE_M, 0.05);
check('RED: without it the rim carried the foam\'s full whitening',
  waterFoam(0) * WATER_FOAM_STRENGTH, 0.6);
check('…with it the rim carries nothing at all',
  waterFoam(0) * WATER_FOAM_STRENGTH * waterEdgeFade(0, 0.05), 0);
check('half a pixel in, half the fade', waterEdgeFade(0.025, 0.05), 0.5);
check('one pixel in, the fade is done', waterEdgeFade(0.05, 0.05), 1);
check('a pixel narrower than the floor still spends the floor',
  waterEdgeFade(0.025, 0.001), 0.5);
check('a metre-wide pixel far away spends the metre',
  waterEdgeFade(0.5, 1), 0.5);

// ── [3] the E1 invariant, and the red counter-probe ────────────────────────
console.log('\n[3] the E1 carve invariant, re-derived on the client side');
/** The bake's carve, written out INDEPENDENTLY here (W1 § 3) — never imported,
 *  so the check is against the contract and not against a shared helper that
 *  could be wrong in both places at once. */
function carve(hNat, dIn, level, depthM, rampM) {
  const t = rampM > 0 ? Math.min(dIn / rampM, 1) : 1;
  const s = t * t * (3 - 2 * t);
  return Math.min(hNat, level - depthM * s);
}
const LEVEL = 3.0;
const DEPTH_M = 2.0;
const RAMP_M = 3.0;
const EPS = Math.min(DEPTH_M, 0.25);
check('ε = min(water_depth_m, 0.25)', EPS, 0.25);
// A natural ground that RISES towards the middle of the lake — the worst case
// the invariant has to survive, and the one a sampled check would be lucky to
// hit.
const hNatAt = (dIn) => 2.5 + dIn * 0.8;
for (const [dIn, cap] of [[0, 3.0], [0.75, 2.6875], [1.5, 2.0],
  [2.25, 1.3125], [3.0, 1.0], [40, 1.0]]) {
  check(`carve at d_in ${dIn} m caps the ground at`,
    carve(1e6, dIn, LEVEL, DEPTH_M, RAMP_M), cap);
}
for (const dIn of [3.0, 3.5, 5, 12, 40, 400]) {
  const h = carve(hNatAt(dIn), dIn, LEVEL, DEPTH_M, RAMP_M);
  check(`beyond the ramp (d_in ${dIn} m): plane − h ≥ ε`,
    LEVEL - h >= EPS ? 1 : 0, 1);
  check(`…and it is the constant level − depth_m, whatever the ground did`,
    h, LEVEL - DEPTH_M);
}
check('at the rim the plane MEETS the terrain — that is the shoreline',
  carve(LEVEL, 0, LEVEL, DEPTH_M, RAMP_M), LEVEL);
check('…and a bank already below the water is left where it is (min, never =)',
  carve(1.2, 0, LEVEL, DEPTH_M, RAMP_M), 1.2);

console.log('\n[3b] the RED counter-probe — a bump above the water is impossible');
// Not "we did not find one in N samples": beyond the ramp the smoothstep is
// exactly 1, so the second argument of the min is a CONSTANT below the level.
for (const bump of [3.5, 10, 40, 1e9]) {
  check(`a natural +${bump} m bump inside the deep zone still comes out at`,
    carve(bump, 10, LEVEL, DEPTH_M, RAMP_M), LEVEL - DEPTH_M);
}
check('a basin (shore_ramp_m = 0) is a STEP and carves full depth at the rim',
  carve(1e6, 0, LEVEL, DEPTH_M, 0), LEVEL - DEPTH_M);
// The shallow-pond case: ε follows the authored depth, so the invariant is not
// silently loosened by a pond that never gets 25 cm deep.
check('a 0.2 m pond: ε = 0.2, and the carve still clears it',
  LEVEL - carve(1e6, 5, LEVEL, 0.2, RAMP_M) >= Math.min(0.2, 0.25) ? 1 : 0, 1);

// ── [4] the fixture river's profile ────────────────────────────────────────
console.log('\n[4] the fixture river: level(x) = 0.08·x + 1.0, hand-derived');
const level = (x, z = -30) => waterLevelAt(RIVER, x, z);
for (const x of [20, 26, 35, 50, 74, 80]) {
  check(`level(${x}) = ${0.08 * x + 1.0}`, level(x), 0.08 * x + 1.0, 1e-12);
}
checkIs('the downstream rim is EXACTLY level_down (the clamp, not the ramp)',
  level(20), 2.6);
checkIs('…and the upstream rim EXACTLY level_up', level(80), 7.4);
check('past the upstream extreme it CLAMPS', level(200), 7.4);
check('…and past the downstream one too', level(-200), 2.6);
check('the axis is the x axis here, so z does not enter at all',
  level(35, -21) - level(35, -39), 0);
check('the MID level is the level at the centroid', level(50),
  RIVER_META.water_level_effective);
check('…and it is the mean of the two ends', (7.4 + 2.6) / 2, level(50), 1e-12);
console.log('\n[4b] a still lake: the same arithmetic, one answer everywhere');
for (const [x, z] of [[0, 0], [12, -4], [-300, 900], [1e6, -1e6]]) {
  checkIs(`level(${x}, ${z}) is the lake's one float`, waterLevelAt(LAKE, x, z),
    3.25);
}
// A degenerate span must not divide by zero even with a bearing set — the
// server ships s_min == s_max == 0 for still water and the guard is the same.
checkIs('an empty span with a bearing set still answers level_up, never NaN',
  waterLevelAt({ ...RIVER, s_min: 0, s_max: 0 }, 999, 999), 7.4);
// ── [4d] the hairpin: a river follows its own line ─────────────────────────
console.log('\n[4d] the HAIRPIN — the axis is a polyline (W4a)');
const U = waterProfileOf(HAIRPIN_META);
const uLevel = (x, z) => waterLevelAt(U, x, z);
checkIs('AT the middle knot the level is that knot\'s own', uLevel(249, 280),
  8.0);
check('halfway along the first leg, the mean of its two knots',
  uLevel(199.5, 290), 9.0, 1e-12);
check('…and halfway along the second', uLevel(225, 270), 7.0, 1e-12);
checkIs('upstream of the first knot the polyline CLAMPS', uLevel(150, 400),
  10.0);
checkIs('…and downstream of the last one too', uLevel(201, 160), 6.0);
checkIs('on the first knot itself', uLevel(150, 300), 10.0);
checkIs('…and on the last', uLevel(201, 260), 6.0);
// THE RED COUNTER-PROBE: the same river as the ONE tilted plane the nine
// numbers describe — its chord is A -> C, and the middle knot projects PAST the
// downstream end of it.
const STRAIGHT = { ...U, axis: [[150, 300, 0, 10],
  [201, 260, Math.sqrt(4201), 6]] };
checkIs('RED: the straight W1 axis answers the DOWNSTREAM level at the bend',
  waterLevelAt(STRAIGHT, 249, 280), 6.0);
check('…i.e. the bend projects onto it at u = 1.392, past its own end',
  (99 * 51 + -20 * -40) / 4201, 1.3923, 1e-4);
check('…and the hairpin reading is 2.0 m higher there',
  uLevel(249, 280) - waterLevelAt(STRAIGHT, 249, 280), 2.0, 1e-12);
// ── [4e] the cliff: the axis has knots where the GROUND bends (W5b) ────────
console.log('\n[4e] the CLIFF — the level follows the step, not the chord');
const CLIFF = waterProfileOf(CLIFF_META);
const cLevel = (x, z = 0) => waterLevelAt(CLIFF, x, z);
checkIs('upstream, 10 m before the lip, the water is the plateau\'s 3.0',
  cLevel(31), 3.0);
checkIs('…and 20 m before it as well — no ramp starts early', cLevel(21), 3.0);
checkIs('at the last knot before the lip it is still 3.0', cLevel(40), 3.0);
check('at the lip itself, halfway between the two knots', cLevel(41), 1.5,
  1e-12);
checkIs('two metres past it the water is the low ground\'s 0.0', cLevel(42),
  0.0);
checkIs('…and 10 m past the lip, still 0.0', cLevel(51), 0.0);
checkIs('…and at the mouth', cLevel(100), 0.0);
// THE RED COUNTER-PROBE: the two-knot axis the clicked-points-only rule shipped
// for the very same two clicks — `level = 3 − 0.03·x` all the way down.
const RAMP = { ...CLIFF, axis: [[0, 0, 0, 3], [100, 0, 100, 0]] };
check('RED: the two-knot ramp reads 2.07 ten metres BEFORE the lip',
  waterLevelAt(RAMP, 31, 0), 2.07, 1e-12);
check('…i.e. 0.93 m below the 3 m plateau it is crossing — the water sinks '
  + 'into a slot long before the edge',
  3 - waterLevelAt(RAMP, 31, 0), 0.93, 1e-12);
check('RED: …and 1.47 ten metres AFTER it', waterLevelAt(RAMP, 51, 0), 1.47,
  1e-12);
check('…i.e. 1.47 m of water standing on ground that is at 0 — the mound',
  waterLevelAt(RAMP, 51, 0) - 0, 1.47, 1e-12);
// The shore reads the DEPTH under the pixel, so the same two probes decide how
// opaque the surface is (docstring [2], `waterOpaqueDepthM` = ¾ of the bed
// depth). Upstream the bed is 1.0 m under a level of 3.0, i.e. the full depth.
check('the opaque depth of this river is the 1 m floor, not ¾ of its 1.0 m bed',
  waterOpaqueDepthM(CLIFF_META.water_depth_effective), 1.0, 1e-12);
check('upstream the water is its full 1.0 m deep, i.e. fully opaque',
  waterShoreAlpha(3.0 - 2.0,
    waterOpaqueDepthM(CLIFF_META.water_depth_effective)), 1, 1e-12);
// ── [6] the wade/swim crossover ────────────────────────────────────────────
console.log('\n[6] the figure floats on the LEVEL, not in the bed');
const SINK = 0.6;
const bodyY = (depth) => {
  const groundY = LEVEL - depth;
  return floatRootY(groundY, LEVEL, SINK) - SINK;
};
const rootY = (depth) => floatRootY(LEVEL - depth, LEVEL, SINK);
for (const [depth, root, bodyRef] of [
  [0.0, 3.6, 3.0],
  [0.3, 3.3, 2.7],
  [0.6, 3.0, 2.4],
  [1.2, 3.0, 2.4],
  [2.0, 3.0, 2.4],
  [8.0, 3.0, 2.4],
]) {
  check(`depth ${depth} m: root`, rootY(depth), root);
  check(`depth ${depth} m: body reference`, bodyY(depth), bodyRef);
}
check('THE CROSSOVER is at depth == sink, where the two branches agree',
  rootY(SINK), LEVEL);
check('…and the body is continuous across it (0.599 vs 0.601 m of depth)',
  Math.abs(bodyY(0.601) - bodyY(0.599)) < 3e-3 ? 1 : 0, 1);
check('before E4 a 2 m bed put the body 2.6 m under the water line',
  (LEVEL - 2.0) - SINK, 0.4);
check('…now it is 0.6 m under it, at any depth', LEVEL - bodyY(2.0), SINK);

console.log('\n[6b] on the RIVER the swimmer floats at his own metre');
/** The carved bed of the fixture beyond the shore ramp: level(x) − 1.0. */
const bed = (x) => level(x) - 1.0;
for (const [x, bedY, lvl, root, ref] of [
  [26, 2.08, 3.08, 3.08, 2.48],
  [50, 4.00, 5.00, 5.00, 4.40],
  [74, 5.92, 6.92, 6.92, 6.32],
]) {
  check(`x = ${x}: the bed`, bed(x), bedY, 1e-12);
  check(`x = ${x}: the local level`, level(x), lvl, 1e-12);
  check(`x = ${x}: the root rides the local water line`,
    floatRootY(bed(x), level(x), SINK), root, 1e-12);
  check(`x = ${x}: the body hangs 0.6 m under it`,
    floatRootY(bed(x), level(x), SINK) - SINK, ref, 1e-12);
}
check('the DEPTH is 1.0 m at every metre of the river, so he swims everywhere',
  Math.max(...[20, 35, 50, 65, 80].map((x) => Math.abs(level(x) - bed(x) - 1))),
  0, 1e-12);

console.log('\n[6c] the RED counter-probe — the flat MID level, which W2 ends');
const MID = RIVER_META.water_level_effective;
check('downstream (x = 26) a flat client floats him at', floatRootY(bed(26), MID, SINK),
  5.0, 1e-12);
check('…which is this far ABOVE the water line he can see',
  floatRootY(bed(26), MID, SINK) - level(26), 1.92, 1e-12);
check('upstream (x = 74) it puts his feet on the bed instead',
  floatRootY(bed(74), MID, SINK) - SINK, bed(74), 1e-12);
check('…i.e. WADING in water this deep', level(74) - bed(74), 1.0, 1e-12);
// The flat reading's crossover: 5.0 − 0.08·x = 0.6  ->  x = 55.
check('and its crossover sits at ONE x — he swims below it and walks above it',
  (MID - 0.6) / 0.08, 55, 1e-12);
check('…while the local reading has none: the depth never changes',
  (level(55) - bed(55)) - (level(20) - bed(20)), 0, 1e-12);

console.log('\n[6d] out of the water nothing changed');
check('no water: the root is the ground, as it always was',
  floatRootY(7.25, null, SINK), 7.25);
check('…and the body still sinks into a bog by its own depth',
  floatRootY(7.25, null, 0.2) - 0.2, 7.05);
check('a NaN level is no level', floatRootY(7.25, NaN, SINK), 7.25);
check('a junk sink is no sink', floatRootY(7.25, LEVEL, NaN), Math.max(7.25, LEVEL));
check('a negative sink is no sink either', floatRootY(2.0, LEVEL, -1), LEVEL);

console.log('\n[6e] how far the water\'s word reaches (the twin of groundSink)');
checkEq('wilderness: the lake counts', groundWaterLevel(LEVEL, 'wilderness'), LEVEL);
checkEq('an OPEN place: it counts there too — the terrace of a house',
  groundWaterLevel(LEVEL, 'open'), LEVEL);
checkEq('a BUILT place: a tiled hall in a lake is a floor',
  groundWaterLevel(LEVEL, 'built'), null);
checkEq('no lake, no level', groundWaterLevel(null, 'open'), null);

// ── [7] the shore on a slope ───────────────────────────────────────────────
console.log('\n[7] the shore measures the LOCAL level, and needed no change');
// The depth is `level(x, z) − h(x, z)` at every point — the LOCAL level, from
// the profile (gameplay) or from the raster the server baked out of it
// (render). The fixture river's own band: 1.0 m of bed -> ¾ is 0.75 m, floored
// to the 1.0 m of `WATER_MIN_SEE_DEPTH_M`, so its constant 1.0 m of depth is
// OPAQUE at exactly its deepest point — under the old lake band it was 20/27.
const FIX_BAND = waterOpaqueDepthM(RIVER_META.water_depth_effective);
check('the fixture river is 1.0 m deep, and the floor draws it fully at 1.0 m',
  FIX_BAND, 1.0);
check('the alpha over the river is 1 at every x — it is deeper than its band',
  Math.min(...[20, 26, 50, 74, 80].map(
    (x) => waterShoreAlpha(level(x) - bed(x), FIX_BAND))),
  1);
check('RED: against the LAKE\'s band the same water was 20/27 opaque',
  waterShoreAlpha(1.0, LAKE_BAND), 0.7407407407407407, 1e-15);
check('…the same number at every x, which is why the finding was not local',
  Math.max(...[20, 26, 50, 74, 80].map(
    (x) => Math.abs(waterShoreAlpha(level(x) - bed(x), LAKE_BAND) - 20 / 27))),
  0, 1e-12);
console.log('\n[7b] the RED counter-probe — the flat plane over the same river');
check('a flat plane at 5.0 has NEGATIVE depth upstream of x = 62.5',
  MID - bed(74), -0.92, 1e-12);
check('…so no water is drawn there at all — the bed stands above the level',
  waterShoreAlpha(MID - bed(74), FIX_BAND), 0);
check('the waterline of the flat plane lies at x =', (MID - 0) / 0.08, 62.5, 1e-12);
check('…and downstream it would be fully opaque over a false 2.92 m of depth',
  waterShoreAlpha(MID - bed(26), FIX_BAND), 1);

// ── [8] the RED counter-probes: the zone water is GONE ─────────────────────
console.log('\n[8] the RED counter-probes — the second water source is deleted');
const SOURCES = ['client3d/src/scene/waterPlaneMath.ts',
  'client3d/src/scene/ground.ts', 'client3d/src/scene/waterShade.ts',
  'client3d/src/scene/layerGround.ts', 'client3d/src/scene/sceneRecipe.ts',
  'packages/scene-render/src/layerCut.ts',
  'packages/scene-render/src/index.ts'];
const texts = new Map();
for (const rel of SOURCES) texts.set(rel, await readFile(join(ROOT, rel), 'utf8'));
/** Where a name still appears as CODE. A mention in a comment is the history
 *  the deletion is owed; a line that is not a comment is the mechanism alive. */
function liveMentions(name) {
  const out = [];
  for (const [rel, text] of texts) {
    for (const raw of text.split('\n')) {
      const line = raw.trim();
      if (line.startsWith('//') || line.startsWith('*') || line.startsWith('/*')
        || line.startsWith('*/')) continue;
      if (line.includes(name)) out.push(`${rel}: ${line}`);
    }
  }
  return out;
}
for (const dead of ['zoneWaterAt', 'zoneWaterMirrors', 'zoneWaters',
  'ZoneMirror', 'TerrainLayerWater', 'index.waters',
  // …and the flat reading itself: the client stopped having a use for the mid
  // level the moment its water learned to tilt.
  'waterLevelOf', 'water_level_effective',
  // …AND THE MIRROR MESH ITSELF (Wasser v2 K-A E5). The water surface is the
  // terrain, so every piece of the second surface is gone: the builder, the
  // shader chunk, the two attributes, the strip cut, the lift, and the
  // per-vertex flow the server now bakes into the raster.
  'buildWaterPlane', 'patchWaterShore', 'addMirror', 'earcutStrips',
  'waterShoreGlsl', 'waterShoreBody', 'aWaterOpaque', 'vWaterOpaque',
  'subdivideRibbonByAxis', 'liftToWaterProfile', 'waterFlowAt',
  'WATER_STRIP_MAX', 'WATER_SHORE_BAND_M', 'WATER_FOAM_ALPHA', 'waterAlpha']) {
  checkEq(`\`${dead}\` is gone from the code`, liveMentions(dead), []);
}
// …and `SceneFloor` no longer declares the field at all: the payload stopped
// carrying it with the room water it described, and W3 removed the one reader
// (the admin floor-plan preview) that still named it.
const sceneTypes = await readFile(
  join(ROOT, 'packages/scene-render/src/types.ts'), 'utf8');
checkEq('RED: SceneFloor declares no room water height any more',
  (sceneTypes.match(/^\s*water_level_effective\?: number$/gm) ?? []).length, 0);
check('the room\'s water is a REFERENCE now, not a height',
  /map_water\?: \{ area_id: string; kind: string \}/.test(sceneTypes) ? 1 : 0, 1);
checkEq('…and the module exports neither of the two zone functions',
  [W.zoneWaterAt, W.zoneWaterMirrors, W.waterLevelOf].map((f) => typeof f),
  ['undefined', 'undefined', 'undefined']);
// The BED substitution died with it (W1 § 5): the client renders the surface
// the table names, water or not.
const lg = texts.get('client3d/src/scene/layerGround.ts');
check('RED: the compositor substitutes no bare-ground image for water any more',
  /layer\.water \? bare : layer/.test(lg) ? 1 : 0, 0);
check('…and asks the BED kind where a row names one',
  /const kind = layer\.bed_kind \|\| layer\.kind;/.test(lg) ? 1 : 0, 1);
// And what still asks the profile in the ground builder: the falls, and the
// point query. One condition, and it is the profile.
const gr = texts.get('client3d/src/scene/ground.ts');
check('the water test is the PROFILE alone',
  /const profile = waterProfileOf\(area\.meta\);/.test(gr) ? 1 : 0, 1);
check('…and typeAt reads the level AT THE POINT',
  /level = profile \? waterLevelAt\(profile, x, z\) : null;/.test(gr) ? 1 : 0, 1);
check('…while the falls are the only meshes it still builds',
  /nextFalls\.push\(\.\.\.buildWaterfall\(fall, nextOwned\)\);/.test(gr)
    ? 1 : 0, 1);

// ── [9] the ripple scrolls downstream ──────────────────────────────────────
// See the docstring section [9] for the derivation of every vector below.
//
// WHOSE SHADER THIS IS. `@anima/scene-render materials.applyWaterShader` — the
// rippled surface the room floors of `scene/sceneRecipe.ts` and the admin
// previews are drawn with. The 3D MAP's own water is the terrain's fragment
// since Wasser v2 K-A E4 and is checked in `smoke_water_shade.mjs` [5]; the two
// carry the same arithmetic on purpose, which is why both are pinned by hand.
//
// THE FLOW VECTOR IS TYPED OUT HERE, not read from a helper: the mesh that used
// to hand it over per vertex is gone with K-A E5, and the fixture river's axis
// runs (80,−30) -> (20,−30), i.e. exactly toward −x (docstring [4]).
const RIVER_FLOW = [-1, 0];
console.log('\n[9] the ripple scroll direction follows the flow');
/** The shader's frame arithmetic, written out INDEPENDENTLY (the GLSL is
 *  checked structurally below). `flow` is `vWaterFlow`; (0, 0) is still. */
function waterFrame([fx, fz]) {
  const len = Math.hypot(fx, fz);
  const still = len < 1e-4;
  const ax = still ? [1, 0] : [fx / Math.max(len, 1e-4), fz / Math.max(len, 1e-4)];
  return { still, ax, ay: [-ax[1], ax[0]] };
}
function rippleDirs(flow) {
  const { still, ax, ay } = waterFrame(flow);
  // The cross factors shrink on a current (finding 2026-08-23) — the along
  // ones do not. Still water keeps 0.6 / 1.3, constant for constant.
  const cA = still ? 0.6 : 0.15;
  const cB = still ? 1.3 : 0.3;
  const a = [ax[0] + ay[0] * cA, ax[1] + ay[1] * cA];
  const b = still
    ? [-(ax[0] * 0.8 + ay[0] * cB), -(ax[1] * 0.8 + ay[1] * cB)]
    : [ax[0] * 0.8 - ay[0] * cB, ax[1] * 0.8 - ay[1] * cB];
  return [a, b];
}
const STILL = rippleDirs([0, 0]);
checkEq('still water: layer A is the constant that stood here before',
  STILL[0], [1, 0.6]);
checkEq('…and layer B is its counter-scrolling one', STILL[1], [-0.8, -1.3]);
const DOWN = rippleDirs(RIVER_FLOW);
checkEq('the fixture river (270°, toward −x): layer A', DOWN[0], [-1, -0.15]);
checkEq('…and layer B', DOWN[1], [-0.8, 0.3]);
check('BOTH layers travel downstream — A along the flow',
  DOWN[0][0] * -1 + DOWN[0][1] * 0, 1, 1e-12);
check('…and B along it too (this is what a river reads as)',
  DOWN[1][0] * -1 + DOWN[1][1] * 0, 0.8, 1e-12);
check('…while their CROSS components oppose, so the two still beat',
  Math.sign(DOWN[0][1]) * Math.sign(DOWN[1][1]), -1);
// …and both now run CLOSE to the flow: 58° off it was the diagonal shimmer
// the finding names, 20° is a stream.
check('layer A is 8.5308…° off the flow', Math.atan2(0.15, 1) * 180 / Math.PI,
  8.530765609948139, 1e-12);
check('…and layer B 20.5560…°, the widest of the two',
  Math.atan2(0.3, 0.8) * 180 / Math.PI, 20.556045219583664, 1e-12);
// A LAKE's lengths are untouched — the frame is a rotation, and a rotation
// keeps lengths, so uSpeed means exactly the metres per second it always did.
check('a lake still drifts at √1.36', Math.hypot(...STILL[0]),
  Math.sqrt(1.36), 1e-15);
check('…and √2.33', Math.hypot(...STILL[1]), Math.sqrt(2.33), 1e-15);
// A RIVER's are shorter by construction, and A's ALONG component is exactly
// 1.0 — which is what makes uFlowSpeed the downstream m/s of the leading sheet.
check('a river layer A is √1.0225 long', Math.hypot(...DOWN[0]),
  Math.sqrt(1.0225), 1e-15);
check('…and layer B √0.73', Math.hypot(...DOWN[1]), Math.sqrt(0.73), 1e-15);
for (const [deg, flow, a, b] of [
  [0, [0, 1], [-0.15, 1], [0.3, 0.8]],
  [90, [1, 0], [1, 0.15], [0.8, -0.3]],
  [270, [-1, 0], [-1, -0.15], [-0.8, 0.3]],
]) {
  const [da, db] = rippleDirs(flow);
  checkEq(`${deg}° -> A`, da.map((v) => Math.round(v * 1e12) / 1e12), a);
  checkEq(`${deg}° -> B`, db.map((v) => Math.round(v * 1e12) / 1e12), b);
}

// ── [9c] two speeds, the stretched ripple, the streak ──────────────────────
// See the docstring section [9c]. The numbers here are the shader's, written
// out a second time from the derivation, not read out of it.
console.log('\n[9c] two speeds, a ripple stretched along the flow, a streak');
const LAMBDA = 1.6;          // wave_m default
const S_STILL = 0.25;        // speed default        (lake)
const S_FLOW = 0.5;          // flow_speed default   (river, 0.5 since 2026-08-25)
check('a lake drifts at its own dial', S_STILL, 0.25);
check('…a current at the raised one, now twice the lake\'s', S_FLOW, 0.5);
// A's along component is exactly 1.0, so flow_speed IS the downstream m/s.
check('…and layer A of that current makes exactly that downstream',
  (DOWN[0][0] * -1 + DOWN[0][1] * 0) * S_FLOW, 0.5, 1e-15);
check('…layer B trails it at 0.8 of that',
  (DOWN[1][0] * -1 + DOWN[1][1] * 0) * S_FLOW, 0.4, 1e-15);
/** The squeeze: project into the flow frame, divide the ALONG part by `k`. */
function squash(frame, [x, z], k) {
  const { ax, ay } = frame;
  const al = (x * ax[0] + z * ax[1]) / k;
  const cr = x * ay[0] + z * ay[1];
  return [ax[0] * al + ay[0] * cr, ax[1] * al + ay[1] * cr];
}
const STILL_FRAME = waterFrame([0, 0]);
const FLOW_FRAME = waterFrame(RIVER_FLOW);
checkEq('still water squeezes by 1 in the world frame, i.e. not at all',
  squash(STILL_FRAME, [12, -4], 1), [12, -4]);
// The ripple is 3× as long as it is wide: on wave_m 1.6 that is 1.6 m across
// the stream against 4.8 m along it (a texture period is 1 in uv).
check('a crest is 1.6 m across the stream', LAMBDA, 1.6);
check('…and 4.8 m along it', LAMBDA * 3, 4.8, 1e-15);
// SPEED SURVIVES THE STRETCH because the squeeze is linear and takes the whole
// coordinate, drift included: uv(p, t) == uv(p − dir·s·dt, t + dt), EXACTLY.
const P = [12, -4];
const T0 = 7;
const DT = 2.5;
const SIGMA = -1;             // wFlowSign on a current; a lake keeps +1
function uvA(p, t) {
  const [dx, dz] = DOWN[0];
  const drift = t * S_FLOW * SIGMA / LAMBDA;
  return squash(FLOW_FRAME, [p[0] / LAMBDA + dx * drift, p[1] / LAMBDA + dz * drift], 3);
}
// Where the crest that sat at P at T0 has got to at T0 + DT: p − dir·σ·s·dt,
// which with σ = −1 is p + dir·s·dt — DOWNSTREAM, at flow_speed·|A| m/s.
const moved = [P[0] - DOWN[0][0] * SIGMA * S_FLOW * DT,
               P[1] - DOWN[0][1] * SIGMA * S_FLOW * DT];
checkEq('the stretched crest still travels at flow_speed·|A| m/s',
  uvA(moved, T0 + DT).map((v) => Math.round(v * 1e12) / 1e12),
  uvA(P, T0).map((v) => Math.round(v * 1e12) / 1e12));
// …and DOWNSTREAM, not against the current: the fixture river runs toward −x,
// so the crest must have moved toward −x too. `+ dir·drift` alone would have
// walked it the other way — the ripple ran upstream before this round.
check('…and it travelled DOWNSTREAM (toward −x on the fixture river)',
  Math.sign(moved[0] - P[0]), -1);
check('…by exactly |A|·flow_speed·dt metres',
  Math.hypot(moved[0] - P[0], moved[1] - P[1]),
  Math.hypot(...DOWN[0]) * S_FLOW * DT, 1e-15);
check('RED: the old sign would have carried it upstream',
  Math.sign(P[0] - DOWN[0][0] * S_FLOW * DT - P[0]), 1);
// The STREAK: the same map as a ribbon, 2λ across the stream, 8× that along.
check('the streak repeats every 3.2 m across the stream', LAMBDA * 2, 3.2, 1e-15);
check('…and every 25.6 m along it', LAMBDA * 2 * 8, 25.6, 1e-15);
check('…at weight 0.35 when flowing', 0.35, 0.35);
// And exactly 0 when still — which is why a lake is bit for bit unchanged.
for (const sample of [-1, -0.5, 0, 0.25, 1]) {
  check(`RED: streak·0 leaves a lake normal alone (${sample})`,
    sample + sample * 0.0, sample, 0);
}

console.log('\n[9b] …and the GLSL is that arithmetic, structurally');
const matSrc = await readFile(
  join(ROOT, 'packages/scene-render/src/materials.ts'), 'utf8');
check('the flow is a per-vertex ATTRIBUTE, so ONE material serves every area',
  /attribute vec2 aWaterFlow;/.test(matSrc) ? 1 : 0, 1);
check('…handed to the fragment as a varying',
  /vWaterFlow = aWaterFlow;/.test(matSrc) ? 1 : 0, 1);
check('RED: and it is NOT a uniform — that would be one material per lake',
  /uniform vec2 uWaterFlow|uniforms\.uWaterFlow/.test(matSrc) ? 1 : 0, 0);
check('the frame is built from the flow, with the still case named',
  /vec2 wAx = wStill \? vec2\( 1\.0, 0\.0 \) : vWaterFlow \/ max\( wLen, 1e-4 \);/
    .test(matSrc) ? 1 : 0, 1);
check('…and the cross axis is its perpendicular',
  /vec2 wAy = vec2\( -wAx\.y, wAx\.x \);/.test(matSrc) ? 1 : 0, 1);
check('both layers are offset ALONG that frame',
  /vec2 wRawA = vWaterWorld \/ uWaveM \+ wDirA \* wDriftA;/.test(matSrc) ? 1 : 0, 1);
check('RED: no normalize of a possibly-zero vector anywhere in the patch',
  /normalize\( vWaterFlow \)/.test(matSrc) ? 1 : 0, 0);

console.log('\n[9d] …and so are the two speeds, the stretch and the streak');
check('the drift picks between the still and the flowing dial',
  /float wSpeed = wStill \? uSpeed : uFlowSpeed \* wLen;/.test(matSrc) ? 1 : 0, 1);
check('…and both layers drift by it', (matSrc.match(
  /float wDrift[AB] = uTime \* wSpeed \* wFlowSign \/ /g) || []).length, 2);
check('the drift SIGN is +1 still, −1 flowing (the ripple ran upstream)',
  /float wFlowSign = wStill \? 1\.0 : -1\.0;/.test(matSrc) ? 1 : 0, 1);
check('…and the streak rides the same sign',
  /wAx \* \( uTime \* wSpeed \* wFlowSign \)/.test(matSrc) ? 1 : 0, 1);
check('flow_speed reaches the shader as its own uniform',
  /shader\.uniforms\.uFlowSpeed = uFlowSpeed\b/.test(matSrc) ? 1 : 0, 1);
check('…declared in the fragment source',
  /uniform float uFlowSpeed;/.test(matSrc) ? 1 : 0, 1);
check('…and defaulted to the kind default, by name not by copy',
  /uFlowSpeed = \{ value: spec\.flow_speed \?\? WATER_FLOW_SPEED_DEFAULT_M_S \}/
    .test(matSrc) ? 1 : 0, 1);
check('…which is 0.5 m/s since the user decision of 2026-08-25',
  /export const WATER_FLOW_SPEED_DEFAULT_M_S = 0\.5/.test(matSrc) ? 1 : 0, 1);
// STILL WATER IS UNCHANGED, and these are the constants that say so: every new
// branch is a ternary whose still side carries the old number.
check('the cross factors keep 0.6 / 1.3 when still',
  /float wCrossA = wStill \? 0\.6 : 0\.15;/.test(matSrc)
  && /float wCrossB = wStill \? 1\.3 : 0\.3;/.test(matSrc) ? 1 : 0, 1);
check('…the anisotropy is 3 and skipped entirely when still',
  /float wAniso = 3\.0;/.test(matSrc)
  && /vec2 wUvA = wStill \? wRawA/.test(matSrc) ? 1 : 0, 1);
check('…and the streak weighs 0 when still, 0.35 on a current',
  /float wStreak = wStill \? 0\.0 : 0\.35;/.test(matSrc) ? 1 : 0, 1);
check('the stretch divides the ALONG component only',
  /wAx \* \( dot\( wRawA, wAx \) \/ wAniso \) \+ wAy \* dot\( wRawA, wAy \)/
    .test(matSrc) ? 1 : 0, 1);
check('the streak is the SAME map, no new texture',
  (matSrc.match(/texture2D\( normalMap, wUv[ABC] \)/g) || []).length, 3);
check('…read as a ribbon 8× longer than wide, sliding downstream',
  /vec2 wUvC = wAx \* \( dot\( wRawC, wAx \) \/ 8\.0 \) \+ wAy \* dot\( wRawC, wAy \);/
    .test(matSrc) ? 1 : 0, 1);
check('RED: the streak tap is unconditional (derivatives need it)',
  /if[^\n]*wStill[^\n]*\{[^}]*texture2D/.test(matSrc) ? 1 : 0, 0);

// ── [9e] the AREA's own speed rides on the LENGTH of the flow ──────────────
// See the docstring section [9e]. `aWaterFlow` has been a UNIT tangent since
// W4a, so its length was 1.0 on every flowing water ever built; an area that
// authors `meta.flow_speed_m_s` scales it by the ratio of its own metres per
// second to its KIND's dial, and the fragment multiplies `uFlowSpeed` by that
// length. Hand-derived on the fixture river, whose tangent at (50, −30) is
// exactly (−1, 0):
//   no override           -> length 1        -> 0.5 · 1     = 0.5 m/s
//   0.45 m/s over 0.5     -> length 0.9      -> 0.5 · 0.9   = 0.45 m/s
//   0.03 m/s over 0.5     -> length 0.06     -> 0.5 · 0.06  = 0.03 m/s
//   0 m/s over 0.5        -> length 1e-3     -> 0.5 · 1e-3  = 0.5 mm/s
// (the ratios all shrank when the dial rose to 0.5: an area now has to author
//  MORE than half a metre per second before it stretches the unit tangent.)
console.log('\n[9e] the flow vector carries the AREA\'s speed as its length');
const TANGENT = RIVER_FLOW;
checkVec('the fixture river\'s tangent is the unit vector it always was',
  TANGENT, [-1, 0]);
/** The encoding itself: a UNIT tangent scaled by the area's factor. It was the
 *  mirror's `aWaterFlow` attribute until K-A E5 and is the server's baked flow
 *  raster now (`heightfield.water_flow_factor`) — the same two floats, read by
 *  the same expression `uFlowSpeed · length`. */
const encode = ([x, z], factor) => [x * factor, z * factor];
for (const [areaSpeed, factor] of [[undefined, 1], [0.45, 0.9], [0.03, 0.06],
  [0.5, 1]]) {
  const f = waterFlowFactor(areaSpeed, WATER_FLOW_SPEED_DEFAULT_M_S);
  check(`${areaSpeed ?? 'no'} m/s over the kind's 0.5 is a factor of`,
    f, factor, 1e-12);
  const a = encode(TANGENT, f);
  check('…so the attribute comes out that long',
    Math.hypot(a[0], a[1]), factor, 1e-12);
  // AND POINTING WHERE IT DID: the shader divides by that same length, so the
  // frame is untouched — the ripple direction may not move by a millimetre.
  checkVec('…and still points downstream, unchanged',
    [a[0] / Math.hypot(a[0], a[1]), a[1] / Math.hypot(a[0], a[1])],
    TANGENT, 1e-12);
  check('…and uFlowSpeed · length is the authored m/s again',
    WATER_FLOW_SPEED_DEFAULT_M_S * Math.hypot(a[0], a[1]),
    areaSpeed === undefined ? WATER_FLOW_SPEED_DEFAULT_M_S : areaSpeed, 1e-12);
}
// THE ONE THING THE LENGTH MAY NOT DO: fall to zero. `wStill` is `wLen < 1e-4`,
// and a still surface drifts at uSpeed (0.25 m/s) — FASTER than the standstill
// an author asking for 0 m/s wants, and in a lake's crossing pattern instead of
// the river's streaks. The factor is floored at 1e-3, ten times that threshold.
const stopped = encode(TANGENT,
  waterFlowFactor(0, WATER_FLOW_SPEED_DEFAULT_M_S));
check('a river dialled to 0 m/s keeps a length above the still threshold',
  Math.hypot(stopped[0], stopped[1]), WATER_FLOW_FACTOR_MIN, 1e-15);
check('…which is ten times the shader\'s own 1e-4',
  Math.hypot(stopped[0], stopped[1]) / 1e-4, 10, 1e-9);
check('RED: an unfloored 0 would have been shorter than the threshold',
  0 < 1e-4 ? 1 : 0, 1);
check('…and it still moves, at 0.5 mm/s',
  WATER_FLOW_SPEED_DEFAULT_M_S * Math.hypot(stopped[0], stopped[1]),
  0.0005, 1e-12);
// STILL WATER IS UNTOUCHED BY ALL OF IT: a lake's flow is exactly (0, 0) and
// 0 × anything is 0, so it stays the exact pair the shader reads as "still"
// whatever an author dialled.
for (const f of [1, 3, 0.2, WATER_FLOW_FACTOR_MIN]) {
  checkEq(`…and a lake stays (0, 0) at factor ${f}`, encode([0, 0], f),
    [0, 0]);
}
check('RED: and no second attribute was ever added for the speed',
  /aWaterSpeed|aFlowSpeed/.test(matSrc) ? 1 : 0, 0);

console.log(`\n${passed} ok, ${failed} failed`);
process.exit(failed ? 1 : 0);
