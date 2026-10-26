#!/usr/bin/env node
/**
 * Smoke check for WATER AS A SHADING OF THE GROUND — `client3d/src/scene/
 * waterShade.ts` (Wasser v2, K-A E4; `recherche-wasser-v2.md` § 3.3, § 4 K-A).
 *
 * Usage:  node client3d/scripts/smoke_water_shade.mjs
 *
 * Every number below is derived BY HAND in this docstring and never recorded
 * from the current output (§ B5a: numbers, not screenshots).
 *
 * WHY THIS FILE EXISTS. Until E4 a water pixel was drawn by a SECOND, blended
 * surface, and how see-through it was came out of an alpha the blender applied.
 * Under K-A there is no second surface: the terrain fragment that has just
 * textured the bed mixes the water in itself. The curves that used to steer an
 * alpha now steer a colour, a roughness and a normal — the same curves, and
 * this file is what pins that they really are the same. If the water ever
 * changes shape, it must change HERE first.
 *
 * ============================================================================
 * [1] THE ABSORPTION IS THE OLD SHORE CURVE
 * ============================================================================
 * `waterAbsorb(d, band, edge)` = `waterShoreAlpha(d, band) · waterEdgeFade(d,
 * edge)`, i.e. `3t² − 2t³` with `t = d / band`, times the rim ramp. `band` is
 * `max(1 m, ¾ · bed)` (W4b plus the see-through FLOOR of 2026-08-25,
 * `waterOpaqueDepthM`): 1.5 m for the default lake (2.0 m), and 1.0 m for the
 * seeded river (1.2 m), whose bare ¾ would have been 0.9 m.
 *
 * With the rim ramp saturated (`edge` = its floor 0.05 m, so every depth from
 * 0.05 m on multiplies by 1), the lake:
 *
 *     d = 0.15  -> t = 0.1  -> 3(0.01)     − 2(0.001)     = 0.028
 *     d = 0.30  -> t = 0.2  -> 3(0.04)     − 2(0.008)     = 0.104
 *     d = 0.375 -> t = 0.25 -> 3(0.0625)   − 2(0.015625)  = 0.15625
 *     d = 0.75  -> t = 0.5  -> 3(0.25)     − 2(0.125)     = 0.5
 *     d = 1.125 -> t = 0.75 -> 3(0.5625)   − 2(0.421875)  = 0.84375
 *     d = 1.5   -> t = 1                                   = 1
 *     d = 2.0   -> clamped                                 = 1
 *
 * …and the river answers the SAME six numbers over its own floored band (0.1,
 * 0.2, 0.25, 0.5, 0.75, 1.0). The fraction is the law, the metres are the
 * water's — and under a metre the FLOOR is the law: the bed of a water has to
 * stay readable down to at least a metre of depth, so a 1.2 m river no longer
 * goes opaque at the 0.9 m a figure wades in, and a 0.6 m pond never goes
 * opaque at all (0.648 at its deepest, i.e. 35.2 % of its bed still showing).
 *
 * THE RIM RAMP, where it is not saturated. At d = 0.025 m and edge 0.05 m it is
 * 0.5, and the curve under it is `t = 0.025/1.5 = 1/60`:
 *     3t² − 2t³ = 3(1/3600) − 2(1/216000) = 8.333333e-4 − 9.259259e-6
 *               = 8.240741e-4
 *     × 0.5     = 4.120370e-4
 *
 * ============================================================================
 * [2] THE FOAM DOES NOT SCALE WITH THE WATER — BUT IT IS COVERED BY IT
 * ============================================================================
 * `waterFoamAt(d, opaque, edge)` = `foam(d) · cover(d) · rim`, with
 *
 *     foam(d)  = 1 − smoothstep(d / 0.6)          the band, W4b
 *     cover(d) = min(smoothstep(d / opaque) + foam(d)·0.15, 1)
 *
 * The BAND does not scale with the bed: half a metre of real water at a real
 * rim is the same half metre in a pond and in a lake, so `WATER_FOAM_BAND_M`
 * is 0.6 whatever the depth is —
 *
 *     d = 0.15 -> 1 − 0.15625 = 0.84375
 *     d = 0.3  -> 1 − 0.5     = 0.5
 *     d = 0.45 -> 1 − 0.84375 = 0.15625
 *     d = 0.6  -> 1 − 1       = 0
 *
 * — and the COVER is the mirror's own alpha, which K-A has to carry explicitly
 * because the ground it shades is opaque (finding 2026-08-24, "white edges and
 * corners at the waterline"). The mesh mirror whitened its light by
 * `foam · 0.6` and then blended the WHOLE fragment at
 * `clamp(shoreAlpha + foam·0.15, 0, 1) · rim`, so the white that ever reached
 * the screen was the product of all three. E4 kept two of them.
 *
 * On the lake fixture (opaque band 1.5 m), rim saturated:
 *
 *     d      foam      shoreAlpha   cover                     foam·cover
 *     0.15   0.84375   0.028        0.028 + 0.1265625         0.130412109375
 *                                   = 0.1545625
 *     0.3    0.5       0.104        0.104 + 0.075   = 0.179   0.0895
 *     0.45   0.15625   0.216        0.216 + 0.0234375         0.037412109375
 *                                   = 0.2394375
 *     0.6    0         —            —                         0
 *
 * times `WATER_FOAM_STRENGTH` = 0.6 that is 0.0782473 / 0.0537 / 0.0224473 of
 * the way to white. WITHOUT the cover the same three pixels are 0.50625 / 0.30
 * / 0.09375 — 6.47× / 5.59× / 4.18× as white, which is the reported white rim
 * and the white lattice corner where the raster's dilation ring ends. The RED
 * probes below are exactly those three broken numbers.
 *
 * AND IT IS THE FOAM THE RIM RAMP EXISTS FOR. `waterFoam(0)` is 1 — full white
 * — while a pixel one hair further out is bare ground, so without the ramp the
 * brightest line in the picture would step across a boundary whose sub-pixel
 * position moves with the camera. At d = 0.025 m, edge 0.05 m, lake band 1.5:
 *     foam:  t = 0.025/0.6 = 1/24
 *            3t² − 2t³ = 0.005208333333 − 0.000144675926 = 0.005063657407
 *            foam = 0.994936342593
 *     shore: t = 0.025/1.5 = 1/60
 *            3t² − 2t³ = 0.000833333333 − 0.000009259259 = 0.000824074074
 *     cover = 0.000824074074 + 0.994936342593·0.15 = 0.150064525463
 *     foam · cover = 0.149304650117 ,  × rim 0.5 = 0.074652325059
 *
 * ============================================================================
 * [3] THE TINT BLEND IS A MIX AND NOTHING ELSE
 * ============================================================================
 * `waterTintBlend(bed, tint, a)` = `bed + (tint − bed)·a`, per channel. With
 * bed (1, 0.5, 0), tint (0, 0.5, 1) and a = 0.25 that is (0.75, 0.5, 0.25).
 * At a = 0 it is the bed, exactly — which is the RED PROBE of the whole stage:
 * a fragment whose depth varying is 0 must come out as the ground it was.
 *
 * ============================================================================
 * [4] THE LOOK IS THE MIRROR'S LOOK
 * ============================================================================
 * `waterLookFrom(null, null)` has to answer what
 * `@anima/scene-render materials.applyWaterShader` would have fed its uniforms
 * for a kind that declares nothing:
 *     tint #3f7fb8 -> (63, 127, 184)/255 = (0.24705882, 0.49803922, 0.72156863)
 *     sky_mix 0.55 · wave_m 1.6 · speed 0.05 · flow_speed 0.5 (the shared
 *     `WATER_FLOW_SPEED_DEFAULT_M_S`, imported here rather than typed out)
 *     roughness 0.08 · metalness 0.15
 *     opaque depth = ¾ · 2.0 = 1.5
 *
 * …and for the library's `deep_water` (tint #002e57 = (0, 46, 87)/255, speed
 * 0.25) painted with a 1.2 m bed: opaque depth ¾ · 1.2 = 0.9.
 *
 * ============================================================================
 * [4b] THE FLOW IS THE FRAGMENT'S OWN TAP (Task 7, 2026-08-27)
 * ============================================================================
 * The downstream vector used to arrive as the varying `vTlodFlow`, sampled once
 * per VERTEX. The vertices of a terrain piece are `baseStep · 2^level` metres
 * apart — 2 m at level 0, 16 m at level 3, 64 m at level 5 — while a 6 m river
 * plus the bake's 4 m dilation on each bank is a band 14 m wide. From a 16 m
 * spacing on, all four corners of the cell a river pixel falls in can be dry,
 * the varying is EXACTLY (0, 0) and `twRipple` takes its STILL branch: a river
 * drawn as standing water while the raster under it carries 2 m/s. (The counts
 * per lattice alignment are hand-derived in `smoke_flow_lod.mjs`: 0/28 still at
 * level 2, 7/56 at level 3, 63/112 at level 4, 175/224 at level 5.)
 *
 * So the tap moved into the fragment, beside the sd and the kind row, and this
 * section pins the three statements that make that true of the SHIPPED source:
 * the sampler is declared in the fragment chunk, the ripple's `len` is taken
 * from `twFlowAt(p)` — the pixel's own XZ — and the word `vTlodFlow` does not
 * appear in the fragment at all. The still branch is decided on that tap and on
 * nothing else, which is the bit the WATER readout reports against.
 *
 * ============================================================================
 * [5] THE FLOW FRAME IS THE IDENTITY ON STILL WATER
 * ============================================================================
 * The mirror's shader had TWO spellings of every ripple coordinate — one for a
 * lake, one for a river. The terrain has one, `twFrame(v, ax, ay, aniso)`, and
 * the lake's is recovered by handing in the world's own axes and `aniso` 1:
 *     twFrame(v, (1,0), (0,1), 1) = (1,0)·(v·(1,0)/1) + (0,1)·(v·(0,1)) = v
 * The check re-implements the two lines and asserts the identity on arbitrary
 * vectors, and asserts that a flowing frame really squeezes the along
 * component by 3 and leaves the cross one alone.

 *
 * Shared-vector companion hand derivations (also retained at their original sites):
 * Companion: smoke_water_plane.mjs

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

 * Companion: smoke_waterfall.mjs

 * Smoke check for the WATERFALL ("Ein Wasser-Gesetz" W5) — which segment of a
 * river's own flow axis is a fall, where it stands, and how wide it is.
 *
 * Usage:  node client3d/scripts/smoke_waterfall.mjs
 *         (transpiles `packages/scene-render/src/waterfall.ts`; needs esbuild)
 *
 * The profile the axis belongs to is checked next door
 * (`client3d/scripts/smoke_water_plane.mjs`, the polyline of W4a); this is the
 * ONE question W5 adds to it. Every expected value below is derived BY
 * HAND in this docstring (§ B5a) — nothing here records current output.
 *
 * ===========================================================================
 * [1] THE RULE, and why it is two conditions
 * ===========================================================================
 * Per consecutive pair of knots `a -> b` of `meta.water_profile.axis` (in flow
 * order, levels already made non-increasing by the bake):
 *
 *     drop = a.level − b.level        metres of water level lost
 *     run  = b.s − a.s                metres of axis spent
 *     fall <=> drop > 1.0  AND  drop/run > 0.5
 *
 * BOTH, and both STRICTLY. Alone, each is wrong in a way the other repairs:
 *
 *   - the DROP alone calls a valley a waterfall — a river losing 4 m over 200 m
 *     of its length passes it and is a slope one walks down beside;
 *   - the SLOPE alone calls a stone in the stream one — 0.2 m over 0.3 m of run
 *     is a 1-in-1.5 step and the ground already draws it as the short ramp it
 *     is.
 *
 * 1.0 m is `swim_from_m`'s default (W4c): the least water this world already
 * treats as more than a step. 0.5 is 1-in-2, i.e. 26.6°, past where loose
 * material lies still at all — a bed that steep is scree and the water on it is
 * falling, not flowing.
 *
 * AT LEAST THREE KNOTS. A polygon river's axis is the two extremes of ONE
 * straight ramp (`heightfield._straight_profile`): its single segment is the
 * whole river, so a "fall" there would be a curtain across the entire length of
 * the water. A lake is one knot and has no segment at all.
 *
 * ===========================================================================
 * [2] THE PLAN'S FIXTURE — 10 / 9.8 / 4 / 3.9 over runs 20 / 3 / 20
 * ===========================================================================
 * Four knots, and the middle segment is the edge. Laid out so the fall does NOT
 * point the way the area does (see the red probe below): the first leg runs
 * 20 m east, the fall 3 m to the south-east, the last leg 20 m on:
 *
 *     A = (0, 0)        s = 0     level 10
 *     B = (20, 0)       s = 20    level 9.8      |AB| = 20            ✓
 *     C = (21.8, −2.4)  s = 23    level 4        |BC| = √(1.8²+2.4²)
 *                                                     = √9 = 3        ✓
 *     D = (33.8, −18.4) s = 43    level 3.9      |CD| = √(12²+16²)
 *                                                     = √400 = 20     ✓
 *
 * Segment by segment:
 *
 *     A->B  drop 0.2   run 20   0.2 > 1.0 ?  NO           -> no fall
 *     B->C  drop 5.8   run 3    5.8 > 1.0 ✓  5.8/3
 *                                            = 1.9333 > 0.5 ✓ -> FALL
 *     C->D  drop 0.1   run 20   0.1 > 1.0 ?  NO           -> no fall
 *
 * EXACTLY ONE FALL, and it is:
 *
 *     midpoint  ((20 + 21.8)/2, (0 + (−2.4))/2)  = (20.9, −1.2)
 *     direction (1.8, −2.4)/3                    = (0.6, −0.8)
 *     top / bottom                                = 9.8 / 4
 *     width     = the drawn ribbon's own `meta.stroke.width_m` = 6
 *
 * THE RED PROBE IS THE DIRECTION. The area-wide bearing of the nine numbers is
 * the CHORD A -> D = (33.8, −18.4), |chord| = √(33.8² + 18.4²) =
 * √(1142.44 + 338.56) = √1481 = 38.4837628, i.e. (0.8782925, −0.4781237).
 * Against the fall's own (0.6, −0.8):
 *
 *     cos = 0.6·0.8782925 + (−0.8)·(−0.4781237)
 *         = 0.5269755 + 0.3824990 = 0.9094745      -> 24.5672°
 *
 * A curtain hung on the AREA's bearing would stand a quarter-turn of a right
 * angle askew to the stream it is supposed to cross. The segment's own
 * direction is the whole reason the fall is read per segment.
 *
 * ===========================================================================
 * [3] THE FLAT RIVER — 10 down to 6 over 200 m
 * ===========================================================================
 *     A = (0, 0)    s = 0    level 10
 *     B = (100, 0)  s = 100  level 8
 *     C = (200, 0)  s = 200  level 6
 *
 *     A->B  drop 2.0  run 100  drop passes (2 > 1) but 2/100 = 0.02 > 0.5 ? NO
 *     B->C  the same
 *
 * NO FALL — and it is the DROP condition that lets it through and the SLOPE
 * that stops it, which is exactly why there are two.
 *
 * ===========================================================================
 * [4] THE TWO THRESHOLDS, from both sides
 * ===========================================================================
 * THE DROP, at run 1 m (slope 1.0, well past its own threshold, so only the
 * drop is under test):
 *
 *     10 -> 9      drop 1.0     1.0 > 1.0 ? NO (strict)      -> none
 *     10 -> 8.999  drop 1.001   1.001 > 1.0 ✓                -> ONE, top 10,
 *                                                               bottom 8.999
 *
 * THE SLOPE, at drop 2 m (twice its own threshold, so only the slope is under
 * test):
 *
 *     run 4.0   2/4   = 0.5      0.5 > 0.5 ? NO (strict)     -> none
 *     run 3.9   2/3.9 = 0.51282  > 0.5 ✓                     -> ONE, midpoint
 *                                                               x = 1.95
 *
 * Each fixture carries a third knot that is deliberately NOT a fall (a 1.0 m
 * and a 0.5 m step), so the axis has the three knots the rule needs and the
 * answer is about the segment under test alone.
 *
 * ===========================================================================
 * [5] THE POLYGON RIVER — steep and still no fall
 * ===========================================================================
 *     A = (0, 0)   s = 0   level 10
 *     B = (0, −3)  s = 3   level 4
 *
 *     drop 6.0  run 3  ->  6 > 1 ✓   6/3 = 2 > 0.5 ✓
 *
 * BOTH THRESHOLDS PASS AND THERE IS STILL NO FALL, because two knots are one
 * ramp and one ramp is the whole river. This is the red probe for the ≥ 3 rule:
 * without it, every steep polygon water in a world would grow a curtain across
 * its own length. (A lake — one knot — has no segment to test at all.)
 *
 * ===========================================================================
 * [6] TWO FALLS ON ONE RIVER, in flow order
 * ===========================================================================
 *     (0,0)  s 0   20      (2,0)  s 2   18     -> drop 2.0 / run 2 -> FALL
 *     (2,0)  s 2   18      (22,0) s 22  17.8   -> drop 0.2         -> no
 *     (22,0) s 22  17.8    (24,0) s 24  15     -> drop 2.8 / run 2 -> FALL
 *     (24,0) s 24  15      (44,0) s 44  14.8   -> drop 0.2         -> no
 *
 * Two falls, midpoints x = 1 and x = 23, tops 20 and 17.8. A staircase river is
 * a staircase, not one big fall.
 *
 * ===========================================================================
 * [7] THE WIDTH IS THE DRAWN RIBBON'S
 * ===========================================================================
 * `strokeWidthM(meta)` reads `meta.stroke.width_m`, which the server requires
 * of every stroke recipe (`models.terrain._sanitize_stroke`). No recipe, no
 * width — and no width, no fall: a curtain has to span the stream, and a stream
 * of unknown width has no curtain. In practice the two answers agree by
 * construction, because the axes with interior knots ARE the drawn ones.
 *
 * ===========================================================================
 * [9] THE CLIFF BETWEEN TWO CLICKS — where the falls actually come from (W5b)
 * ===========================================================================
 * Every axis above is hand-written, which is what a unit check of a pure
 * function should be. THIS one is the payload the server really ships for the
 * case the user reported (`scripts/smoke_height_bake.py` [8l], same numbers):
 * a river drawn with TWO clicks, (0,0) -> (100,0), 6 m wide, across a plateau
 * that ends at x = 41 with a 3 m step.
 *
 * Until W5b the knots were the CLICKS, so that river's axis was
 *
 *     [[0,0,0,3], [100,0,100,0]]
 *
 * — two knots, one ramp, 3 m of drop spread over 100 m of run. NO FALL, and
 * for three independent reasons: fewer than three knots, a slope of 0.03, and
 * nothing anywhere near the edge to read. The cliff was invisible in the data.
 *
 * Since W5b the server samples the drawn line every 2 m, measures a level per
 * sample and simplifies the result back to where the level BENDS:
 *
 *     [[0,0,0,3], [40,0,40,3], [42,0,42,0], [100,0,100,0]]
 *
 *     0->40   drop 0.0  run 40   -> no
 *     40->42  drop 3.0  run  2   3.0 > 1.0 ✓  3.0/2 = 1.5 > 0.5 ✓  -> FALL
 *     42->100 drop 0.0  run 58   -> no
 *
 * ONE FALL, midpoint (41, 0), direction (1, 0), top 3, bottom 0, width 6.
 *
 * AND THE SIMPLIFICATION IS WHY IT IS ONE. The sampler alone would have cut
 * the drop into as many segments as it took steps over the edge, and each
 * shortened segment carries a SHORTER DROP — the slope test survives that (it
 * is a ratio) but `WATERFALL_MIN_DROP_M` does not, and a stack of curtains is
 * not a waterfall. Because a genuinely straight fall deviates from its own
 * chord by nothing, the simplification hands this rule ONE segment per bend of
 * the level, which is exactly the unit a curtain is hung on.
 *
 * ===========================================================================
 * [10] A CLICK INSIDE THE CLIFF — the drop belongs to the RUN (2026-08-24)
 * ===========================================================================
 * The knots are the bends of the LEVEL plus the author's own clicks, and a
 * click is never dropped (it is a bend of the LINE). So an author who clicked
 * halfway down a cliff hands this rule TWO segments where the ground has one
 * drop — and asking each of them for a full metre made the waterfall vanish
 * exactly where somebody had clicked in it.
 *
 * The fix is in the grouping, not in the thresholds: maximal runs of
 * consecutive STEEP segments (slope > 0.5) are joined FIRST, and the 1 m
 * minimum is asked of the joined run once.
 *
 *   (a) THE SPLIT DROP — 3.0 / 2.1 / 1.2 at s = 0 / 1.5 / 3.0
 *
 *       seg 1  drop 0.9  run 1.5  slope 0.6 > 0.5 ✓  steep, 0.9 > 1.0 ? NO
 *       seg 2  drop 0.9  run 1.5  slope 0.6 > 0.5 ✓  steep, 0.9 > 1.0 ? NO
 *
 *       Per segment: NO fall at all — the bug. Merged: one run, knots 0..2,
 *       drop 3.0 − 1.2 = 1.8 > 1.0 ✓ over a run of 3.0 (slope 0.6, still past
 *       the slope threshold, as a mean of slopes past it must be). ONE fall,
 *       top 3.0, bottom 1.2, arc midpoint s = 1.5 → the middle knot (1.5, 0),
 *       chord (3, 0) → direction (1, 0).
 *
 *   (b) THREE STEPS — 3.0 / 2.1 / 1.2 / 0.3 at s = 0 / 1.5 / 3.0 / 4.5
 *
 *       All three segments steep (0.6 each), none past 1 m alone. Merged drop
 *       2.7 over 4.5. The arc midpoint is s = 2.25, which lies INSIDE the
 *       second segment: (2.25 − 1.5) / 1.5 = 0.5 of the way from (1.5, 0) to
 *       (3, 0) → x = 2.25.
 *
 *   (c) A BENT FALL — (0,0) s 0 level 3.0, (1.5,0) s 1.5 level 2.1,
 *       (1.5,−1.5) s 3.0 level 1.2
 *
 *       Both segments steep, merged drop 1.8. The CHORD is (1.5, −1.5), length
 *       √4.5 = 2.1213203, so the direction is (0.7071068, −0.7071068) — and
 *       the position is the ARC midpoint (1.5, 0), the elbow, NOT the chord's
 *       middle (0.75, −0.75), which lies in the dry corner beside the water.
 *
 *   (d) A POOL BETWEEN TWO STAIRCASES — 6.0 / 5.1 / 4.2 / 4.1 / 3.2 / 2.3 at
 *       s = 0 / 1.5 / 3 / 23 / 24.5 / 26
 *
 *       seg 3 loses 0.1 over 20 m (slope 0.005) and is NOT steep, so it ends
 *       the first run and opens nothing. TWO falls, not one:
 *         knots 0..2  drop 1.8  top 6.0  bottom 4.2  arc mid s 1.5  → x 1.5
 *         knots 3..5  drop 1.8  top 4.1  bottom 2.3  arc mid s 24.5 → x 24.5
 *       Merging across the pool would have hung one 3.7 m curtain over 26 m of
 *       river, which is the failure mode this direction has to avoid.
 *
 *   (e) A RUN OF ONE SEGMENT IS THE OLD RULE. Every fixture of [2], [4], [6]
 *       and [9] is a single steep segment between two flat ones and keeps the
 *       numbers it always had; the plan's fixture is re-asserted here.
 *
 * ===========================================================================
 * [8] THE 3D HALF, structurally
 * ===========================================================================
 * `client3d/src/scene/waterfall.ts` imports three and cannot be transpiled into
 * this process, so what is checked here is what makes it the ARRANGEMENT the
 * plan decided on, plus the two numbers it derives:
 *
 *     the mean speed of the falling water   √(g·h/2)
 *       h = 5.8  ->  √(9.81 · 5.8 / 2) = √28.449 = 5.3337604 m/s
 *       h = 2.0  ->  √(9.81 · 2.0 / 2) = √9.81   = 3.1320920 m/s
 *
 *     the lean, 0.3 m of downstream run per metre of fall — a jet leaving the
 *       lip at 1.5 m/s falls 5.8 m in √(2·5.8/9.81) = √1.1824679 = 1.0874129 s
 *       and travels 1.5 · 1.0874129 = 1.6311194 m while it does, i.e.
 *       1.6311194 / 5.8 = 0.2812275 of its own height.
 *
 * ===========================================================================
 * [9] THE CURTAIN MUST HANG IN FRONT OF ITS OWN WATERFALL (2026-08-24)
 * ===========================================================================
 * Under Wasser v2 K-A the mirror between lip and pool is not a mesh any more:
 * the terrain is lifted to `max(h, w_level)`, so the fall stands on the ground
 * as a steep, OPAQUE, wet face running the fall's own chord. On the plan's
 * fixture that face runs from knot B (20, 0) at y 9.8 to knot C (21.8, −2.4)
 * at y 4 — 3 m of ground for 5.8 m of drop.
 *
 * Write the run coordinate `r` of a point as its signed distance from the
 * fall's own point (20.9, −1.2) along `dir` = (0.6, −0.8), and the height as
 * `u = (y − 4) / 5.8` (0 at the pool, 1 at the lip). The FACE is then the
 * straight line
 *
 *     r_face(u) = (chord/2)·(1 − 2u) = 1.5·(1 − 2u)
 *
 * THE DEFECT. The curtain used to hang from the same midpoint over a run of
 * `WATERFALL_LEAN · h = 1.74 m`, i.e. `r_old(u) = 0.87·(1 − 2u)`. So
 *
 *     r_old − r_face = (0.87 − 1.5)·(1 − 2u) = −0.63·(1 − 2u)
 *
 * which is NEGATIVE — upstream, i.e. inside the hill — for every u below 0.5
 * and reaches −0.63 m at the pool. Exactly the lower HALF of the sheet stood
 * behind the water's own wall, and only the upper half was ever drawn: the
 * reported "the waterfall only has the waterfall texture at the top", and the
 * reason iso switch 22 ("water lift off") makes the whole curtain appear.
 *
 * THE FIX, and its numbers. The sheet is hung from the LIP and given the
 * face's own run plus the lean at its foot:
 *
 *     halfRun = chord/2 = 1.5      lean = 0.3 · 5.8 = 1.74
 *     top = (20.9, −1.2) − (0.6, −0.8)·1.5          = (20.0,   0.0)
 *     bot = (20.9, −1.2) + (0.6, −0.8)·(1.5 + 1.74) = (22.844, −3.792)
 *
 * The top corner IS knot B, the lip, to the metre. The foot sits
 * hypot(22.844 − 21.8, −3.792 + 2.4) = hypot(1.044, 1.392) = √3.0276 = 1.74 m
 * downstream of knot C, the face's foot — the lean, exactly. And in between
 *
 *     r_new(u) − r_face(u) = 1.74·(1 − u)
 *
 * so the sheet is in front of the face at every height, by 1.74 m at the pool,
 * 0.87 m halfway up, and 0 at the lip — where the curtain's own shader already
 * fades its last 6 % of v to nothing.
 *
 * THE TEXTURE WAS NEVER THE PROBLEM. The first suspicion was the wrap mode —
 * a fresh `THREE.CanvasTexture` clamps, and the curtain tiles its uv by
 * `width / 2.5` × `height / 2.5`, both well over 1. But the map is THE shared
 * one and `materials.makeWaveNormal` sets `wrapS = wrapT = RepeatWrapping` on
 * it before anybody sees it; the pin below is on that line.
 *
 * …and the arrangement: the curtain takes THE one wave normal map of the
 * process straight from `materials.surfaceWaveNormal` — the very texture the
 * terrain's own water pixels scroll (K-A E4), and no second one — rides the
 * shared surface clock (no per-frame work of its own), the foam is the shore's
 * own `WATER_FOAM_STRENGTH`, and no particle system was built. In `ground.ts`
 * the falls join `nextFalls` and their materials the area's disposal bag, which
 * is what makes them die with the areas they were derived from. Since K-A E5
 * they are the ONLY meshes a painted water still produces: the surface itself
 * is the terrain (`scene/waterShade.ts`).

 *
 * [20] Shared raster, curtain and normal-map cases:
 * A2x2 step2 water tile with levels[2,4;6,8], sd[0,2;4,6],
 * flowX[1,3;1,3],flowZ[2,2;4,4] averages at(1,1) to level5,sd3,
 * flow(2,3). Nearest kind at(1,0) rounds .5 upward to column1: river.
 * At(3,3) tile1,1 is absent: level dry(null),sd=-10000. Masked
 * bilinear at tx=tz=0 takes only h00=2; three NaN corners have zero
 * weight. At(.5,.5), a NaN corner has positive weight, so result is dry.
 * The sd gate at .25 of the .5 m band is smoothstep(.5)=.5.
 * Curtain centre(10,20), east dir(1,0), width4, top8,bottom3,chord6:
 * height5, halfW2, halfRun3, lean=.3*5=1.5, across(0,-1).
 * Lip=(7,20),foot=(14.5,20). Lip-left/right=(7,8,22)/(7,8,18),
 * foot-left/right=(14.5,3,22)/(14.5,3,18). South dir(0,1) makes
 * across(1,0), lip=(10,17),foot=(10,24.5): x8/12 at each edge.
 * Zero height returns null. Bottom coordinates also place the foam disc.
 * Wave texel(0,0), N256: sin(p+q)-sin(p-q)=2cos(p)sin(q), so
 * Dx=256*sum(a*cos(phase)*sin(2*pi*fx/256)). The four x terms are
 * 6.282554501866,-1.132920263547,-7.526496389831,-1.068951838872,
 * summing -3.445813990385. The y terms are12.561324627819,
 * .566630790374,-5.020184387859,1.602622839040, summing9.710393869374.
 * Normalize(-.02Dx,-.02Dy,1), length1.021012317880. RGBA before
 * rounding is(136.105993798125,103.248084588904,252.376064438465,255),
 * hence[136,103,252,255]. Integer frequencies repeat at(256,256).
 * A river axis (0,0,s0,y10) to(10,0,s10,y6), queried at(5,0),
 * projects to s5: y=10+(6-10)*.5=8.
 */
import { vectorCase, vectorArgs, vectorValue } from './e3VectorSupport.mjs';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');

/**
 * Transpile and import the three pure files this stage stands on.
 *
 * `waterShade.ts` takes the shore constants and curves from `waterPlaneMath.ts`
 * (no imports at all, pure arithmetic) and the flow-speed default from
 * `@anima/scene-render materials.ts` — which imports `three` only as a TYPE, so
 * esbuild erases it and the module loads with no stub and the REAL constants.
 */
async function load() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'watershade-'));
  try {
    const ts = async (src, name) => {
      const code = await readFile(src, 'utf8');
      await writeFile(join(dir, `${name}.mjs`),
        esbuild.transformSync(code, { loader: 'ts', format: 'esm' }).code
          .replace(/from\s*["']@anima\/scene-render["']/g, "from './materials.mjs'")
          .replace(/from\s*["']\.\/([A-Za-z]+)["']/g, "from './$1.mjs'"),
        'utf8');
    };
    await ts(join(ROOT, 'packages/scene-render/src/materials.ts'), 'materials');
    await ts(join(ROOT, 'client3d/src/scene/waterPlaneMath.ts'), 'waterPlaneMath');
    await ts(join(ROOT, 'client3d/src/scene/waterShade.ts'), 'waterShade');
    return {
      shade: await import(`file://${join(dir, 'waterShade.mjs')}`),
      plane: await import(`file://${join(dir, 'waterPlaneMath.mjs')}`),
      mat: await import(`file://${join(dir, 'materials.mjs')}`),
    };
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

function vector(label, fns) {
  const result = vectorCase("water", label, fns);
  passed += result.passed; failed += result.failed;
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
function checkAbove(label, actual, floor) {
  const ok = typeof actual === 'number' && actual > floor;
  if (ok) {
    passed += 1;
    console.log(`  ok   ${label} = ${actual} (> ${floor})`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}\n       expected > ${floor}\n       actual   ${actual}`);
  }
}
function checkBelow(label, actual, ceiling) {
  const ok = typeof actual === 'number' && actual < ceiling;
  if (ok) {
    passed += 1;
    console.log(`  ok   ${label} = ${actual} (< ${ceiling})`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}\n       expected < ${ceiling}\n       actual   ${actual}`);
  }
}
function checkNear(label, actual, expected, eps) {
  const ok = Array.isArray(actual) && actual.length === expected.length
    && actual.every((v, i) => Math.abs(v - expected[i]) <= eps);
  if (ok) {
    passed += 1;
    console.log(`  ok   ${label} = [${actual.map((v) => v.toFixed(8)).join(', ')}]`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}\n       expected ${JSON.stringify(expected)}`
      + `\n       actual   ${JSON.stringify(actual)}`);
  }
}

const { shade, plane, mat } = await load();
const { waterAbsorb, waterFoamAt, waterTintBlend, waterLookFrom, waterTintRgb,
  waterSurface, waterShadeNormal, waterShallowRamp, WATER_SHALLOW_SURFACE_MIN,
  packWaterLook, terrainWaterFragmentGlsl, waterGateGlsl, waterInside,
  waterSdGlsl, WATER_FOAM_MIN_COVER, WATER_SD_BAND_M,
  WATER_LOOK_DEFAULT, WATER_LOOK_TEXELS } = shade;
const { WATER_EDGE_FADE_M, WATER_FOAM_BAND_M, WATER_FOAM_STRENGTH,
  WATER_MIN_SEE_DEPTH_M, waterOpaqueDepthM } = plane;

// ── [1] the absorption ──────────────────────────────────────────────────────
console.log('[1] the absorption is the mirror\'s own shore curve (W4b)');
const EDGE = WATER_EDGE_FADE_M;          // 0.05 m — the floor, i.e. rim ramp 1
const LAKE = waterOpaqueDepthM(2.0);     // 1.5 m
// 1.0 m — ¾ of 1.2 is 0.9, and the see-through FLOOR of 2026-08-25 lifts it.
const RIVER = waterOpaqueDepthM(1.2);
vector("[1] water_shade: the lake's opaque depth is ¾ of its bed", { waterOpaqueDepthM: (...args) => waterOpaqueDepthM(...vectorArgs(args)) });
vector("[1] water_shade: …and the river's is the 1 m floor, not its own 0.9", { waterOpaqueDepthM: (...args) => waterOpaqueDepthM(...vectorArgs(args)) });
vector("[1] water_shade: lake, depth 0.15", { waterAbsorb: (...args) => waterAbsorb(...vectorArgs(args)) });
vector("[1] water_shade: lake, depth 0.30", { waterAbsorb: (...args) => waterAbsorb(...vectorArgs(args)) });
vector("[1] water_shade: lake, depth 0.375", { waterAbsorb: (...args) => waterAbsorb(...vectorArgs(args)) });
vector("[1] water_shade: lake, depth 0.75", { waterAbsorb: (...args) => waterAbsorb(...vectorArgs(args)) });
vector("[1] water_shade: lake, depth 1.125", { waterAbsorb: (...args) => waterAbsorb(...vectorArgs(args)) });
vector("[1] water_shade: lake, depth 1.5 — the bed is gone", { waterAbsorb: (...args) => waterAbsorb(...vectorArgs(args)) });
vector("[1] water_shade: lake, depth 2.0 — and stays gone", { waterAbsorb: (...args) => waterAbsorb(...vectorArgs(args)) });
vector("[1] water_shade: river, depth 0.1", { waterAbsorb: (...args) => waterAbsorb(...vectorArgs(args)) });
vector("[1] water_shade: river, depth 0.2", { waterAbsorb: (...args) => waterAbsorb(...vectorArgs(args)) });
vector("[1] water_shade: river, depth 0.25", { waterAbsorb: (...args) => waterAbsorb(...vectorArgs(args)) });
vector("[1] water_shade: river, depth 0.5", { waterAbsorb: (...args) => waterAbsorb(...vectorArgs(args)) });
vector("[1] water_shade: river, depth 0.75", { waterAbsorb: (...args) => waterAbsorb(...vectorArgs(args)) });
vector("[1] water_shade: river, depth 1.0 — the same six answers, over the floored band", { waterAbsorb: (...args) => waterAbsorb(...vectorArgs(args)) });
// THE FLOOR'S OWN RED PROBE: what the ¾ rule hid at the depth a figure wades
// in. 0.5 m over the bare 0.9 m band is t = 5/9 -> 3·(25/81) − 2·(125/729) =
// 0.58299040; over the floored 1.0 m band it is exactly a half.
vector("[1] water_shade: RED: at 0.5 m the ¾ band had hidden 0.58299 of the river bed", { waterAbsorb: (...args) => waterAbsorb(...vectorArgs(args)) });
vector("[1] water_shade: …and the floor leaves half of it readable", { waterAbsorb: (...args) => waterAbsorb(...vectorArgs(args)) });
check('…i.e. this much more bed shows at a wading depth',
  waterAbsorb(0.5, 0.9, EDGE) - waterAbsorb(0.5, RIVER, EDGE),
  0.0829903978052126, 1e-15);
// THE RIM RAMP under its floor.
vector("[1] water_shade: the rim ramp halves the curve at half a floor-pixel", { waterAbsorb: (...args) => waterAbsorb(...vectorArgs(args)) });
vector("[1] water_shade: …and a FAT pixel widens the ramp instead of the water", { waterAbsorb: (...args) => waterAbsorb(...vectorArgs(args)) });

// ── [2] the foam ────────────────────────────────────────────────────────────
console.log('\n[2] the foam is half a metre of real water — covered by the water');
check('the band is 0.6 m', WATER_FOAM_BAND_M, 0.6);
check('the cover floor is the mirror\'s own rim alpha', WATER_FOAM_MIN_COVER, 0.15);
vector("[2] water_shade: depth 0.15", { waterFoamAt: (...args) => waterFoamAt(...vectorArgs(args)) });
vector("[2] water_shade: depth 0.3", { waterFoamAt: (...args) => waterFoamAt(...vectorArgs(args)) });
vector("[2] water_shade: depth 0.45", { waterFoamAt: (...args) => waterFoamAt(...vectorArgs(args)) });
vector("[2] water_shade: depth 0.6 — gone", { waterFoamAt: (...args) => waterFoamAt(...vectorArgs(args)) });
vector("[2] water_shade: depth 1.0 — still gone", { waterFoamAt: (...args) => waterFoamAt(...vectorArgs(args)) });
vector("[2] water_shade: the rim ramp is what keeps the white line from stepping", { waterFoamAt: (...args) => waterFoamAt(...vectorArgs(args)) });
// RED: THE MEASURED DEFECT OF 2026-08-24 — the foam without the mirror's alpha.
// These are the three numbers the shipped code must NOT answer any more; each
// is the plain band times the rim ramp, i.e. up to 6.47× the white above.
check('RED: the uncovered band at 0.15 (the white rim that was reported)',
  waterFoamAt(0.15, LAKE, EDGE) === 0.84375 ? 1 : 0, 0);
check('RED: …at 0.3', waterFoamAt(0.3, LAKE, EDGE) === 0.5 ? 1 : 0, 0);
check('RED: …at 0.45', waterFoamAt(0.45, LAKE, EDGE) === 0.15625 ? 1 : 0, 0);
// The ratio IS one over the cover — the band cancels — so it is written that
// way: 1 / 0.1545625 = 6.46987464617…
check('RED: …and it was 6.47× as white at 0.15',
  0.84375 / waterFoamAt(0.15, LAKE, EDGE), 1 / 0.1545625, 1e-9);
// The BAND still does not follow the bed — only the COVER does, and it is the
// same factor the absorption already rides.
// The river's band is the floored 1.0 m, so at 0.3 m the shore curve stands at
// t = 0.3 -> 3(0.09) − 2(0.027) = 0.216, and the cover is 0.216 + 0.5·0.15.
vector("[2] water_shade: a SHALLOWER bed foams the same band, only better covered", { waterFoamAt: (...args) => waterFoamAt(...vectorArgs(args)) });

// ── [3] the blend, and the red probe ────────────────────────────────────────
console.log('\n[3] the blend — and what a DRY pixel must come out as');
checkNear('a quarter of the way to the tint',
  waterTintBlend([1, 0.5, 0], [0, 0.5, 1], 0.25), [0.75, 0.5, 0.25], 1e-12);
checkNear('fully absorbed is the tint', waterTintBlend([1, 0.5, 0], [0, 0.5, 1], 1),
  [0, 0.5, 1], 1e-12);
checkNear('RED: absorption 0 leaves the GROUND COLOUR untouched',
  waterTintBlend([1, 0.5, 0], [0, 0.5, 1], 0), [1, 0.5, 0], 1e-12);
vector("[3] water_shade: RED: a depth of 0 absorbs nothing", { waterAbsorb: (...args) => waterAbsorb(...vectorArgs(args)) });
vector("[3] water_shade: RED: …and foams nothing", { waterFoamAt: (...args) => waterFoamAt(...vectorArgs(args)) });
vector("[3] water_shade: RED: a NEGATIVE depth is not water either", { waterAbsorb: (...args) => waterAbsorb(...vectorArgs(args)) });
check('RED: nor is a NaN one', waterAbsorb(NaN, LAKE, EDGE), 0);
// That is the whole isolation switch 22: `uTlodNoWater` makes every lift a
// no-op, so `vTlodWet` is 0 and the three lines above are what the fragment
// computes — the plain ground look, without a second code path.

// ── [4] the look table ──────────────────────────────────────────────────────
console.log('\n[4] the look is the mirror\'s look, read by another program');
checkNear('the default tint is #3f7fb8', waterTintRgb(undefined),
  [63 / 255, 127 / 255, 184 / 255], 1e-12);
checkNear('…and an authored one is read', waterTintRgb('#002e57'),
  [0, 46 / 255, 87 / 255], 1e-12);
checkNear('…while a broken one falls back rather than throwing',
  waterTintRgb('not a colour'), [63 / 255, 127 / 255, 184 / 255], 1e-12);
const bare = waterLookFrom(null, null);
vector("[4] water_shade: a kind that declares nothing: sky_mix", { waterLookFromValue: (args, path) => vectorValue(waterLookFrom(...vectorArgs(args)), path) });
vector("[4] water_shade: …wave_m", { waterLookFromValue: (args, path) => vectorValue(waterLookFrom(...vectorArgs(args)), path) });
vector("[4] water_shade: …speed", { waterLookFromValue: (args, path) => vectorValue(waterLookFrom(...vectorArgs(args)), path) });
check('…flow_speed is the SHARED default', bare.flowSpeed,
  mat.WATER_FLOW_SPEED_DEFAULT_M_S);
check('…which is 0.5 m/s', mat.WATER_FLOW_SPEED_DEFAULT_M_S, 0.5);
vector("[4] water_shade: …roughness", { waterLookFromValue: (args, path) => vectorValue(waterLookFrom(...vectorArgs(args)), path) });
vector("[4] water_shade: …metalness", { waterLookFromValue: (args, path) => vectorValue(waterLookFrom(...vectorArgs(args)), path) });
vector("[4] water_shade: …and the default lake's opaque depth", { waterLookFromValue: (args, path) => vectorValue(waterLookFrom(...vectorArgs(args)), path) });
// The library's own `deep_water`, painted with a 1.2 m bed.
const deep = waterLookFrom({ class: 'water', tint: '#002e57', map_strength: 0.75,
  wave_m: 1.6, speed: 0.25, sky_mix: 0.55, roughness: 0.08 }, 1.2);
checkNear('deep_water\'s tint', deep.tint, [0, 46 / 255, 87 / 255], 1e-12);
vector("[4] water_shade: …its speed", { waterLookFromValue: (args, path) => vectorValue(waterLookFrom(...vectorArgs(args)), path) });
vector("[4] water_shade: …and its opaque depth follows the AREA's bed, floored at a metre", { waterLookFromValue: (args, path) => vectorValue(waterLookFrom(...vectorArgs(args)), path) });
vector("[4] water_shade: a wavelength below the floor is lifted to it", { waterLookFromValue: (args, path) => vectorValue(waterLookFrom(...vectorArgs(args)), path) });
// The packing — the layout `tlodWaterSurface` fetches its three texels from.
check('three RGBA texels per look', WATER_LOOK_TEXELS, 3);
const packed = packWaterLook([bare, deep]);
check('two looks are 2 · 3 · 4 floats', packed.length, 24);
checkNear('row 0, texel 0 — tint and sky_mix',
  [...packed.slice(0, 4)], [...bare.tint, 0.55], 1e-7);
// …the flow slot is the shared default (0.5 since 2026-08-25), the 0.15 one
// texel further on is metalness and did not move.
checkNear('row 0, texel 1 — wave, speed, flow, opaque depth',
  [...packed.slice(4, 8)], [1.6, 0.05, 0.5, 1.5], 1e-7);
// SINCE BAKE v10 the third slot is SPARE. It carried `is_water`, the flag the
// fragment used to pick the water half out of the id mask's layer pair — and
// with it the stand-in rows the table needed for every ground layer. The table
// is keyed by KIND now and every row is a real water, so there is nothing left
// to flag. See [10] for the conviction that killed the mask.
checkNear('row 0, texel 2 — roughness, metalness, two spare',
  [...packed.slice(8, 12)], [0.08, 0.15, 0, 0], 1e-7);
checkEq('RED: no row writes an is_water flag any more — the packer never sets '
  + 'the third slot', packWaterLook([bare, deep]).some((v, i) => i % 12 === 10 && v !== 0),
  false);
checkNear('row 1 is the SECOND water and no blend of the two',
  [...packed.slice(12, 16)], [...deep.tint, 0.55], 1e-7);
check('…with its own opaque depth', packed[19], 1.0, 1e-7);
vector("[4] water_shade: an EMPTY table is still one row, so no fetch is out of range", { packWaterLookValue: (args, path) => vectorValue(packWaterLook(...vectorArgs(args)), path) });
checkNear('…and that row is the library default',
  [...packWaterLook([]).slice(0, 3)], WATER_LOOK_DEFAULT.tint, 1e-7);

// ── [5] the flow frame ──────────────────────────────────────────────────────
console.log('\n[5] one ripple expression, two waters — the frame is the switch');
// The GLSL, re-implemented from the arithmetic and not from the string.
const dot2 = (a, b) => a[0] * b[0] + a[1] * b[1];
const twFrame = (v, ax, ay, aniso) => [
  ax[0] * (dot2(v, ax) / aniso) + ay[0] * dot2(v, ay),
  ax[1] * (dot2(v, ax) / aniso) + ay[1] * dot2(v, ay),
];
const STILL_AX = [1, 0];
const STILL_AY = [0, 1];
checkNear('STILL water: the frame is the identity',
  twFrame([3.7, -1.25], STILL_AX, STILL_AY, 1), [3.7, -1.25], 1e-12);
checkNear('…on any vector at all', twFrame([-0.5, 8], STILL_AX, STILL_AY, 1),
  [-0.5, 8], 1e-12);
// A river flowing toward +x: along = x, across = z, squeezed 3:1.
checkNear('FLOWING water: the along component is squeezed by 3',
  twFrame([3, 0], STILL_AX, STILL_AY, 3), [1, 0], 1e-12);
checkNear('…and the cross one is left alone',
  twFrame([0, 3], STILL_AX, STILL_AY, 3), [0, 3], 1e-12);
// A diagonal current, so the squeeze is not an axis accident: flow (1,1)/√2.
const AX = [Math.SQRT1_2, Math.SQRT1_2];
const AY = [-AX[1], AX[0]];
checkNear('…a diagonal current squeezes ALONG ITSELF',
  twFrame([3 * AX[0], 3 * AX[1]], AX, AY, 3), [AX[0], AX[1]], 1e-12);
checkNear('…and leaves its own cross direction whole',
  twFrame([3 * AY[0], 3 * AY[1]], AX, AY, 3), [3 * AY[0], 3 * AY[1]], 1e-12);

// ── [6] the GLSL says what the arithmetic above says ────────────────────────
console.log('\n[6] the fragment composes albedo -> normal -> light, once');
const glsl = terrainWaterFragmentGlsl();
checkEq('the easing is the TS smoothstep',
  glsl.includes('return c * c * ( 3.0 - 2.0 * c );'), true);
checkEq('the ABSORPTION writes the ALBEDO, so the lighting model shades water',
  glsl.includes('diffuseColor.rgb = mix( diffuseColor.rgb, look0.rgb, twA );'), true);
checkEq('…while the roughness and metalness ride the SURFACE share (H2)',
  glsl.includes('roughnessFactor = mix( roughnessFactor, look2.x, twS );')
  && glsl.includes('metalnessFactor = mix( metalnessFactor, look2.y, twS );'), true);
checkEq('RED: …and never the depth curve again (the land-coloured shallows)',
  glsl.includes('roughnessFactor = mix( roughnessFactor, look2.x, twA );')
  || glsl.includes('metalnessFactor = mix( metalnessFactor, look2.y, twA );'), false);
checkEq('RED: the tint never touches the finished light',
  /outgoingLight[^;]*look0/.test(glsl), false);
checkEq('the foam band is the shared constant',
  glsl.includes(`twSmooth( d / ${WATER_FOAM_BAND_M} )`), true);
checkEq('…and so is its strength',
  glsl.includes(`twFoam * ${WATER_FOAM_STRENGTH}`), true);
checkEq('the rim ramp is floored at the shared edge fade',
  glsl.includes(`max( fwidth( d ), ${WATER_EDGE_FADE_M} )`), true);
checkEq('…and BOTH water factors are multiplied by it',
  glsl.includes('twA = shore * rim;')
  && glsl.includes('* rim;\n'), true);
checkEq('the foam carries the COVER the mirror\'s alpha used to be',
  glsl.includes(
    `twFoam = rawFoam * min( shore + rawFoam * ${WATER_FOAM_MIN_COVER}, 1.0 ) * rim;`),
  true);
checkEq('RED: …and never the bare band again (the white rim of 2026-08-24)',
  glsl.includes(`twFoam = ( 1.0 - twSmooth( d / ${WATER_FOAM_BAND_M} ) ) * rim;`),
  false);
checkEq('the cover reuses the ABSORPTION\'s own shore curve, not a second one',
  glsl.includes('float shore = twSmooth( d / max( look1.w, 1e-3 ) );')
  && (glsl.match(/twSmooth\( d \/ max\( look1\.w/g) ?? []).length === 1, true);
checkEq('EVERYTHING keys on the depth varying, and nothing else',
  glsl.includes('float d = vTlodWet;') && glsl.includes('if ( d <= 0.0 ) return;'), true);
checkEq('RED: the fragment reads no height pyramid for its shoreline',
  glsl.includes('tlodHeight('), false);
// The ripple: three taps, all with EXPLICIT gradients (they sit under a branch
// that differs across a quad, where an implicit derivative is undefined).
check('three wave taps', glsl.split('textureGrad( uTlodWave').length - 1, 3);
checkEq('RED: and not one implicit fetch of the wave map',
  /texture\(\s*uTlodWave|texture2D\(\s*uTlodWave/.test(glsl), false);
checkEq('the derivatives are taken at UNIFORM control flow, before the branch',
  glsl.indexOf('vec2 gx = dFdx( vTlodXZ );') < glsl.indexOf('if ( d <= 0.0 ) return;'),
  true);
// The mirror's constants, carried over one by one.
checkEq('the still frame counter-scrolls (0.6 / 1.3) and the river does not (0.15 / 0.3)',
  glsl.includes('float crossA = still ? 0.6 : 0.15;')
  && glsl.includes('float crossB = still ? 1.3 : 0.3;'), true);
checkEq('the second sheet is 0.63 λ and 0.8 along',
  glsl.includes('float lamB = waveM * 0.63;') && glsl.includes('ax * 0.8'), true);
checkEq('the streak ribbon is 2 λ across and 8× that along, at weight 0.35',
  glsl.includes('float lamC = waveM * 2.0;')
  && glsl.includes('ax, ay, 8.0 )') && glsl.includes('still ? 0.0 : 0.35'), true);
checkEq('a river\'s crests run DOWNSTREAM (the sign is negative)',
  glsl.includes('float sgn = still ? 1.0 : -1.0;'), true);
// Sheets A/B are ISOTROPIC since 2026-08-25 (user finding, readout-measured:
// the 3:1 along-flow squeeze hid the downstream motion — a streak sliding
// along its own length shows nothing, so only the cross beat stayed visible
// and the river read as drifting SIDEWAYS). RED half: the old squeeze line
// must be gone; the direction-cue squeeze survives only in sheet C (8x).
checkEq('sheets A/B are isotropic — the squeeze line is gone',
  glsl.includes('float aniso = 1.0;')
  && !glsl.includes('float aniso = still ? 1.0 : 3.0;'), true);
checkEq('…sheet C keeps its 8x streak squeeze as the direction cue',
  glsl.includes('ax, ay, 8.0'), true);
checkEq('the area\'s speed factor is the LENGTH of the flow vector',
  glsl.includes('float sp = still ? speed : flowSpeed * len;'), true);
checkEq('…and a length below 1e-4 is a lake', glsl.includes('bool still = len < 1e-4;'),
  true);
// [4b] THE FLOW IS SAMPLED HERE, PER PIXEL — not handed in as a varying.
console.log('\n[4b] the flow is the fragment\'s own tap, at the pixel\'s XZ');
checkEq('the fragment declares the flow sampler itself',
  glsl.includes('uniform sampler2D uTlodFlow;')
  && glsl.includes('vec2 twFlowAt( vec2 p ) {'), true);
checkEq('…the ripple takes its vector from that tap at its own p',
  glsl.includes('vec2 flow = twFlowAt( p );')
  && glsl.includes('float len = length( flow );'), true);
checkEq('…and the STILL decision hangs on it and on nothing else',
  glsl.includes('bool still = len < 1e-4;')
  && glsl.includes('vec2 ax = still ? vec2( 1.0, 0.0 ) : flow / max( len, 1e-4 );'), true);
checkEq('RED: the varying vTlodFlow is gone from the fragment entirely',
  glsl.includes('vTlodFlow'), false);
checkEq('…and the lattice comes out of textureSize, like the sd\'s and the kind\'s',
  /vec2 twFlowAt[\s\S]*?\n}/.exec(glsl)[0].includes('textureSize( uTlodFlow, 0 )'), true);
checkEq('…with the window test, not a clamp, so no rim carries a stray current',
  /vec2 twFlowAt[\s\S]*?\n}/.exec(glsl)[0]
    .includes('if ( fx < 0.0 || fz < 0.0 || fx > cols - 1.0 || fz > rows - 1.0 ) return vec2( 0.0 );'),
  true);
check('…four texel fetches, the sd\'s count',
  (/vec2 twFlowAt[\s\S]*?\n}/.exec(glsl)[0].match(/texelFetch\(/g) ?? []).length, 4);
// WHICH ROW — the water raster's own kind, NEAREST, off the water lattice.
checkEq('the look row comes from the water raster and is clamped to the table',
  glsl.includes('int layer = clamp( twKindRow( vTlodXZ ), 0, rows - 1 );'), true);
checkEq('RED: …and never from the ground compositor\'s id mask again',
  /twIsWater|uTlodWaterMask/.test(glsl), false);
// The one place K-A gives GPU work back.
checkEq('a FULLY absorbed pixel does not read the bed\'s normal at all',
  /if \( twA >= 1\.0 \) \{\n\s*return normalize\( \( viewMatrix \* vec4\( twN/
    .test(glsl), true);
checkEq('…and a pixel with no water SURFACE over it reads only the bed\'s',
  glsl.includes('if ( twS <= 0.0 ) {'), true);

// ============================================================================
// [7] THE SHADING GATE — the water is shaded where it is PAINTED, and the field
//     that says so is the WATER's, not the ground compositor's (findings F-A/F-B)
// ============================================================================
// THE DEFECT THAT STARTED IT. The water raster is dilated: the server writes a
// level up to 4 m past the authored outline so that every point INSIDE a
// polygon reads four wet corners on the base lattice. The shading keyed on the
// lift alone, so every shore wore a band of centimetre-shallow water — a grey
// wash, and a white foam lace before the cover fix of the same day.
//
// THE FIRST GATE WAS THE WRONG FIELD (finding F-A, "the lake is only a sand
// surface"). It asked the ground compositor's id mask: which two KINDS meet
// under this pixel, and which side of them am I on. That mask names the topmost
// PAINTED kind, so a lake whose bed is painted — a sand shape inside the
// outline, which is what `bed_kind` describes and what a generated map draws —
// reads (sand, sand) over its whole interior. Neither half is water, the gate
// answered 0, and the lake was drawn as its own bed. Measured on that fixture
// (`app.core.terrain_layers`, lake + painted bed): the pair mid-lake is
// (1, 1) = (sand, sand).
//
// THE GATE NOW is the water raster's OWN signed distance — the same field, read
// by the same sampler, that the vertex stage gates its LIFT on. One question,
// one field, both stages: a pixel is shaded as water exactly where the ground
// under it was lifted onto the mirror.
//
// THE BAND IS ONE-SIDED AND A WORLD CONSTANT SINCE FINDING G1/G3 (2026-08-25).
// Two changes, one reason each:
//
//   * ONE-SIDED. It used to straddle the outline, `smoothstep(−b/2, +b/2, sd)`,
//     which claimed water a quarter-metre PAST the line the author drew and
//     called the line itself half water. The outer half was dead — outside the
//     outline the lift never fired, so the fragment left on `d <= 0` before the
//     gate was read — and the inner half is where a figure stood sunk (see [7b]).
//     `smoothstep(0, 0.5, sd)`: the outline IS the edge of the water.
//   * A WORLD CONSTANT. The old width was `max(pixelM, 0.5)`, and the pixel term
//     grows without bound with distance and with grazing angle — see [7c]. The
//     vertex stage has no pixel footprint either, and since G1 it reads this very
//     curve, so the band has to be a function of the world position alone.
//
// THE HAND TABLE, band 0.5 m, t = sd/0.5, w = t²(3 − 2t):
//   sd = −2     -> t clamps to 0 -> 0        (the ring, 2 m outside: GROUND)
//   sd = −0.25  -> t clamps to 0 -> 0        (the old band's outer half: GROUND)
//   sd =  0     -> t = 0     -> 0            (the authored waterline)
//   sd = +0.05  -> t = 0.1   -> 3(0.01)    − 2(0.001)    = 0.028
//   sd = +0.1   -> t = 0.2   -> 3(0.04)    − 2(0.008)    = 0.104
//   sd = +0.125 -> t = 0.25  -> 3(0.0625)  − 2(0.015625) = 0.15625
//   sd = +0.25  -> t = 0.5   -> 3(0.25)    − 2(0.125)    = 0.5
//   sd = +0.375 -> t = 0.75  -> 3(0.5625)  − 2(0.421875) = 0.84375
//   sd = +0.5   -> t = 1     -> 1            (half a metre in: FULL water)
console.log('\n[7] the shading gate: painted water, not lifted ground');
const inside = (sd) => waterInside(sd);
check('2 m out on the flooded ring the pixel is GROUND', inside(-2), 0);
check('…a quarter metre out — the old band\'s outer half — GROUND too',
  inside(-0.25), 0);
check('…on the authored waterline itself, still ground', inside(0), 0);
check('…5 cm in', inside(0.05), 0.028);
check('…10 cm in', inside(0.1), 0.104);
check('…an eighth of a metre in', inside(0.125), 0.15625);
check('…a quarter metre in, half and half', inside(0.25), 0.5);
check('…three eighths in, nearly water', inside(0.375), 0.84375);
check('half a metre inside the outline it is FULL water', inside(0.5), 1);
check('…and stays full however far in — a lake is unchanged', inside(20), 1);
// THE LAKE WITH A PAINTED BED, which is the whole of finding F-A. Mid-lake the
// distance is the lake's half-width; nothing about what is painted over it
// enters this function at all.
check('mid-lake, 20 m from its own outline: FULL water, bed or no bed',
  inside(20), 1);
// THE BAND NO LONGER DEPENDS ON ANYTHING BUT sd — one argument, no pixel.
checkEq('the gate takes the distance and nothing else', waterInside.length, 1);
check('the band is the fixed half metre', WATER_SD_BAND_M, 0.5);
// THE FALL FACE is inside the river's own outline — the steep wet wall between
// lip and plunge pool is water the author painted, not dilation — so it keeps
// the waterfall look whole.
check('the fall face, well inside the outline, is full water', inside(1.5), 1);
// RED: the ring pixel really did shade as water before the gate. The lift there
// is a few centimetres, and the absorption of a few centimetres is small but
// not zero — which is exactly what a grey wash is.
const RING_DEPTH = 0.05;
const ringAbsorb = waterAbsorb(RING_DEPTH, waterOpaqueDepthM(1.5),
                               WATER_EDGE_FADE_M);
checkAbove('RED: without the gate the ring pixel carries water absorption',
  ringAbsorb, 0);
check('…and with it, none at all', ringAbsorb * inside(-2), 0);
const ringFoam = waterFoamAt(RING_DEPTH, waterOpaqueDepthM(1.5), WATER_EDGE_FADE_M);
checkAbove('RED: …and foam', ringFoam, 0);
check('…which the gate takes with it', ringFoam * inside(-2), 0);
// The GLSL says the same line and the same band.
const gateGlsl = waterGateGlsl();
checkEq('the shader gate is ONE smoothstep and no cases at all',
  gateGlsl.includes('float twInside( float sd ) {')
  && gateGlsl.includes('return twSmooth( sd / 0.5 );'), true);
checkEq('…and it carries no pixel, no band variable and no fwidth at all',
  /pixelM|float band|fwidth/.test(gateGlsl), false);
checkEq('RED: the layer pair no longer decides anything about water',
  /aw\s*\?\s*w\s*:\s*1\.0\s*-\s*w/.test(glsl), false);
checkEq('the gate multiplies the RIM, so absorption AND foam ride it',
  glsl.includes('float rim = clamp( d / edge, 0.0, 1.0 ) * inside;')
  && glsl.includes('if ( rim <= 0.0 ) return;'), true);
checkEq('the distance is read from the WATER raster, at this pixel\'s position',
  glsl.includes('float inside = twInside( twSdAt( vTlodXZ ) );'), true);
checkEq('…by texel fetch and never by a filtered sampler',
  /texture(2D)?\(\s*uTlodWaterSd/.test(glsl), false);
checkEq('…and the pixel width comes from the world position, not from fwidth(sd)',
  /fwidth\(\s*sd/.test(glsl), false);
// RED: the compositor's own signed distance is GONE from this program — its
// window and its byte quantisation are not declared any more.
checkEq('RED: no uTlodWaterSdGeom, no uTlodWaterSdCode',
  glsl.includes('uTlodWaterSdGeom') || glsl.includes('uTlodWaterSdCode'), false);
// RED: the id mask is gone from this program ALTOGETHER (bake v10). It answered
// "which kind" out of the topmost PAINTED layer — see [10] for the numbers.
checkEq('RED: no uTlodWaterMask, no uTlodWaterMaskGeom, no pair fetch',
  /uTlodWaterMask|uvec2 pair/.test(glsl), false);
// THE SAMPLER IS ONE TEXT, included by both stages, so the lift and the shading
// cannot read the field two ways (`waterSdGlsl`).
const sdGlsl = waterSdGlsl();
checkEq('the sd sampler declares only its own texture',
  sdGlsl.includes('uniform sampler2D uTlodWaterSd;')
  && sdGlsl.includes('uniform vec4 uTlodWaterGeom') === false, true);
checkEq('…answers DRY where there is no water field at all',
  sdGlsl.includes('if ( uTlodWaterGeom.w <= 0.0 ) return TW_SD_DRY;'), true);
checkEq('…and DRY outside the window instead of clamping an edge texel outward',
  sdGlsl.includes('if ( fx < 0.0 || fz < 0.0 || fx > cols - 1.0 '
    + '|| fz > rows - 1.0 ) return TW_SD_DRY;'), true);
checkEq('…it is bilinear over four PLAIN texels — the sentinel is a number',
  sdGlsl.split('texelFetch(').length - 1, 4);
checkEq('…and the fragment includes that one text', glsl.includes(sdGlsl.trim()),
  true);
// THE GATE IS THE SECOND SHARED TEXT (finding G1) — the fragment declares it
// exactly once, and `terrainLod.terrainLodWaterGlsl` includes the same string.
checkEq('the fragment includes the gate text whole',
  glsl.includes(gateGlsl.trim()), true);
checkEq('…and declares twSmooth exactly once', glsl.split('float twSmooth(').length - 1,
  1);
// Isolation toggle 22 is untouched: it kills the LIFT, so `d` is 0 and the
// function returns before the gate is ever reached.
checkEq('toggle 22 still leaves before any of this',
  glsl.indexOf('if ( d <= 0.0 ) return;')
    < glsl.indexOf('float inside = twInside('), true);

// ============================================================================
// [7b] THE LIFT RIDES THE SAME CURVE — the figure no longer sinks (finding G1)
// ============================================================================
// THE DEFECT. The fragment faded the water LOOK in over the band; the vertex
// stage lifted BINARY, `sd >= 0` -> the whole lift. So between the outline and
// the band's far end the surface stood on the mirror while it was still shaded
// as ground, and a figure — which stands on the true terrain height `h`, never
// on the mirror — was drawn sunk by exactly that lift.
//
// THE NUMBER. Take a shore where the mirror stands 0.40 m over the bed at the
// probe (a "lifted spot": a river crossing a slope, a lake whose level is above
// its own rim). With the old gate the drawn surface at sd = +0.1 m stood
// h + 0.40 while the look was 0.784 ground; the figure at h was 40 cm under it.
// With the ramp the lift is 0.40 · twInside(0.1) = 0.40 · 0.104 = 0.0416 m —
// 4.2 cm, and the look there is 10.4 % water, i.e. the two now say the same
// thing about the same point. Hand table, LIFT = 0.40 m:
//
//   sd = −0.25 -> 0.40 · 0       = 0        (ring: ground, as before)
//   sd =  0    -> 0.40 · 0       = 0        (the waterline: ground)
//   sd = +0.05 -> 0.40 · 0.028   = 0.0112 m (1.1 cm)
//   sd = +0.1  -> 0.40 · 0.104   = 0.0416 m (4.2 cm)
//   sd = +0.25 -> 0.40 · 0.5     = 0.20 m
//   sd = +0.5  -> 0.40 · 1       = 0.40 m   (full mirror from here in)
//   sd = +1    -> 0.40 · 1       = 0.40 m
//
// The probe the finding asks for — "just inside the edge, the drawn surface
// within ~1 cm of h" — is sd = +0.05: 1.12 cm at a 40 cm lift, and under 1 cm
// for every lift under 0.357 m.
console.log('\n[7b] the LIFT rides the gate\'s own curve (G1)');
const LIFT = 0.40;
const liftAt = (sd) => LIFT * waterInside(sd);
check('the dilation ring is not lifted at all', liftAt(-0.25), 0);
check('…nor is the authored waterline itself', liftAt(0), 0);
check('5 cm in the ground has risen 1.12 cm', liftAt(0.05), 0.0112);
check('…10 cm in, 4.16 cm', liftAt(0.1), 0.0416);
check('…a quarter metre in, half the lift', liftAt(0.25), 0.2);
check('…half a metre in, the whole mirror', liftAt(0.5), 0.4);
check('…and it stays there', liftAt(1), 0.4);
// RED: the old binary gate really did stand the full lift under a ground look.
const oldLift = (sd) => (sd >= 0 ? LIFT : 0);
checkAbove('RED: the old gate lifted 5 cm inside the edge by the FULL',
  oldLift(0.05), 0.39);
checkAbove('RED: …while the look there was only this much water',
  1 - waterInside(0.05), 0.97);
check('the ramp closes that gap to under a centimetre', liftAt(0.05), 0.0112);
checkEq('…so drawn surface and shaded look never disagree by more than the '
  + 'lift itself times the curve', Math.abs(liftAt(0.05) - LIFT * 0.028) < 1e-12,
  true);
// THE MORPH PAIR STAYS CONSISTENT: `sd` is a function of the world point alone,
// so both taps are scaled by the SAME factor and the blend is unchanged in
// shape. Pinned as an identity over the pair (h1, w1) / (h2, w2).
const mix2 = (a, b, f) => a * (1 - f) + b * f;
const gatedPair = (sd, f) => mix2(mix2(2, 2 + LIFT * waterInside(sd), 1),
                                  mix2(3, 3 + LIFT * waterInside(sd), 1), f);
check('both taps carry the same factor, so the pair blends as one ramp',
  gatedPair(0.1, 0.5) - mix2(2, 3, 0.5), LIFT * 0.104);
// AND `vTlodWet` IS STILL >= 0 EVERYWHERE — the fragment's every branch keys on
// `> 0`, so a negative depth would paint water on dry ground. `l − h` is
// `max(0, w − h) · g` with `g` in [0, 1], and both factors are non-negative.
// (The shipped `terrainLod.liftedDepth` is pinned on the same probes in
// `smoke_terrain_lod.mjs` [w] — here the identity itself.)
let worstWet = 0;
for (let s = -1; s <= 2.0001; s += 0.001) {
  for (const w of [-3, 0, 0.4, 5]) {
    const d = w > 0 ? w * waterInside(s) : 0;
    if (d < worstWet) worstWet = d;
  }
}
check('the depth never goes negative over 3001 x 4 probes', worstWet, 0);

// ============================================================================
// [7c] THE BAND USED TO GROW WITH DISTANCE — the fat sand seam (finding G3.2)
// ============================================================================
// The old width was `max(pixelM, 0.5 m)` with `pixelM` = the ground footprint of
// one screen pixel, `max(|dFdx(vTlodXZ)|, |dFdy(vTlodXZ)|)`. For this client's
// camera (`scene/engine.ts`: PerspectiveCamera(45, …)) over a 900-row viewport
// one pixel subtends
//
//     α = (45° / 900) · π/180 = 0.05° = 8.726646e-4 rad
//
// and on the ground at slant distance D, seen at grazing angle θ, its longer
// footprint is `D · α / sin θ` — which is what the `max` of the two derivatives
// takes. The band was that number, floored at half a metre:
//
//     D = 50 m,  θ = 40°  ->  50·8.726646e-4/0.6427876 = 0.06788 m -> band 0.5
//     D = 150 m, θ = 40°  ->                              0.20364 m -> band 0.5
//     D = 400 m, θ = 40°  ->                              0.54305 m -> band 0.54305
//     D = 400 m, θ = 10°  ->  400·8.726646e-4/0.1736482 = 2.01019 m -> band 2.01019
//     D = 400 m, θ =  5°  ->  400·8.726646e-4/0.0871557 = 4.00508 m -> band 4.00508
//
// A band 4 m wide is 4 m of shore drawn as half-ground: the sand seam, and it is
// widest exactly where a shore is normally seen — far off and nearly edge-on.
// The fixed band is 0.5 m at every one of those five viewpoints.
console.log('\n[7c] the band no longer grows with the camera (G3.2)');
const PIX_RAD = (45 / 900) * Math.PI / 180;
const footprint = (d, degrees) =>
  d * PIX_RAD / Math.sin(degrees * Math.PI / 180);
const oldBand = (d, degrees) => Math.max(footprint(d, degrees), 0.5);
checkNear('one pixel on the ground at 50/150/400 m, 40° down',
  [footprint(50, 40), footprint(150, 40), footprint(400, 40)],
  [0.06788, 0.20364, 0.54305], 5e-5);
checkNear('…and at 400 m seen at 10° and 5°',
  [footprint(400, 10), footprint(400, 5)], [2.01019, 4.00508], 5e-5);
checkNear('RED: the OLD band at those five viewpoints',
  [oldBand(50, 40), oldBand(150, 40), oldBand(400, 40),
   oldBand(400, 10), oldBand(400, 5)],
  [0.5, 0.5, 0.54305, 2.01019, 4.00508], 5e-5);
checkAbove('RED: …so a distant, edge-on shore wore a band this many metres wide',
  oldBand(400, 5), 4);
checkNear('the shipped band is the same half metre at all five',
  [WATER_SD_BAND_M, WATER_SD_BAND_M, WATER_SD_BAND_M,
   WATER_SD_BAND_M, WATER_SD_BAND_M],
  [0.5, 0.5, 0.5, 0.5, 0.5], 0);
// G3.3 — WHAT THE SEAM IS MADE OF. At sd = +0.1 the pixel is 10.4 % water at
// most: `twA = shore · rim · inside`, and `inside` alone caps it at 0.104. The
// albedo is `mix(bed, tint, twA)`, so at least 89.6 % of the colour there is the
// BED the compositor painted — sand, if the author painted sand — and none of it
// is a residual water term. With the shore ramp taken into account it is far
// less still: a bed carved 1.0 m deep over a 3 m ramp stands 0.033 m under the
// mirror at that point (0.1/3 of the way in, times the 0.4 m lift used above is
// not the number here — the depth IS the lift), and `shore(0.0416, 0.75)` = 0.009.
const seamInside = waterInside(0.1);
vector("[7c] water_shade: at 10 cm inside the outline the water share is at most", { waterInside: (...args) => waterInside(...vectorArgs(args)) });
const seamA = waterAbsorb(LIFT * seamInside, waterOpaqueDepthM(1.0),
                          WATER_EDGE_FADE_M) * seamInside;
checkBelow('…and with the shore curve on top of it, under 1 % of the pixel',
  seamA, 0.01);
checkNear('so the seam colour is the bed, to better than a percent',
  waterTintBlend([0.76, 0.70, 0.50], [0.247, 0.498, 0.722], seamA),
  [0.76, 0.70, 0.50], 0.01);

// ============================================================================
// [8] THE FLOW SPEED, END TO END — what "auto" really is (finding G2)
// ============================================================================
// THE CHAIN, in the order the metres travel:
//
//   1. the KIND's dial      `material.flow_speed` m/s, default
//                           `WATER_FLOW_SPEED_DEFAULT_M_S` = 0.5 (0.08 -> 0.15
//                           on 2026-08-23, -> 0.5 by user decision 2026-08-25;
//                           the flowing default now sits ABOVE the still 0.25)
//   2. the AREA's override  `meta.flow_speed_m_s`, or none = "auto"
//   3. the server bakes a FACTOR into the flow vector's LENGTH:
//      `waterFlowFactor(area, kind)` = 1 for auto, else `area / kind`
//   4. the fragment reads that length back and multiplies:
//      `sp = still ? speed : flowSpeed * len`
//
// So the metres per second at the surface are `kind · factor`, which is the
// KIND's dial for auto and the AREA's number when one is authored:
//
//   auto,       kind 0.5   ->  factor 1        ->  sp = 0.5  · 1     = 0.5 m/s
//   1.0 m/s,    kind 0.5   ->  factor 2        ->  sp = 0.5  · 2     = 1.0 m/s
//   0.25 m/s,   kind 0.5   ->  factor 0.5      ->  sp = 0.5  · 0.5   = 0.25 m/s
//   1.0 m/s,    kind 0.15  ->  factor 6.6667   ->  sp = 0.15 · 6.667 = 1.0 m/s
//
// — i.e. an authored value is metres per second whatever the kind's dial is,
// exactly as the retired mirror's `uFlowSpeed · wLen` was. There is no zero
// anywhere in the chain: "auto shows no motion" is 0.5 m/s, not 0.
//
// AND HOW FAST A CREST REALLY TRAVELS. The drift is `dir · (t · sp · sgn / λ)`
// on a coordinate that is `p / λ`, so the pattern moves at `sp · |dir|` m/s
// along `dir`. The three sheets of flowing water:
//
//   A  dir = ax + 0.15·ay   |dir| = √1.0225 = 1.01118742   at  +8.53077°
//   B  dir = 0.8·ax − 0.3·ay |dir| = √0.73  = 0.85440037   at −20.55605°
//   C  dir = ax              |dir| = 1                     at   0°
//
// A and B are 29.08682° apart — deliberately (materials.ts: "still of opposite
// sign and of different magnitude, so the two sheets go on beating against each
// other"), and that beat is what a fast river shows as two drifts. The constants
// are the mirror's own accepted pair (0.15 / 0.3 flowing, 0.6 / 1.3 still) —
// cross-mix ratios of the two sheets, nothing to do with the flow DIAL that
// happens to have carried 0.15 until 2026-08-25.
console.log('\n[8] the flow speed, kind dial -> factor -> metres per second');
const { waterFlowFactor, WATER_FLOW_SPEED_DEFAULT_M_S } = mat;
check('the kind default is the shared 0.5 m/s', WATER_FLOW_SPEED_DEFAULT_M_S, 0.5);
vector("[8] water_shade: a kind that declares nothing carries it into the look", { waterLookFromValue: (args, path) => vectorValue(waterLookFrom(...vectorArgs(args)), path) });
vector("[8] water_shade: …and a kind that declares 0.15 carries that", { waterLookFromValue: (args, path) => vectorValue(waterLookFrom(...vectorArgs(args)), path) });
// AUTO — no override, factor exactly 1, so the surface runs at the kind's dial.
check('AUTO is factor 1', waterFlowFactor(undefined, 0.5), 1);
check('…and null is too', waterFlowFactor(null, 0.5), 1);
check('…so auto runs at the kind\'s own metres per second',
  waterLookFrom(null, null).flowSpeed * waterFlowFactor(undefined, 0.5), 0.5);
// AUTHORED — the factor is the ratio, so `flowSpeed · len` is the authored m/s.
check('1.0 m/s over a 0.5 dial is factor', waterFlowFactor(1, 0.5), 2, 1e-12);
check('…and the surface then runs at exactly 1 m/s',
  waterLookFrom(null, null).flowSpeed * waterFlowFactor(1, 0.5), 1, 1e-12);
check('0.25 m/s over the same dial', 0.5 * waterFlowFactor(0.25, 0.5), 0.25,
  1e-12);
check('1.0 m/s over the OLD 0.15 dial is still 1 m/s',
  0.15 * waterFlowFactor(1, 0.15), 1, 1e-12);
checkEq('RED: the shader does NOT ignore the look\'s flow_speed',
  glsl.includes('float sp = still ? speed : flowSpeed * len;')
  && glsl.includes('twN = twRipple( vTlodXZ, gx, gy, max( look1.x, 0.05 ), '
    + 'look1.y, look1.z );'), true);
// …and `look1.z` really is the flow speed: texel 1 of the packed row is
// (wave_m, speed, flow_speed, opaque_depth_m).
checkNear('the look table\'s texel 1 is (wave, speed, flow_speed, opaque)',
  [...packWaterLook([waterLookFrom({ class: 'water', wave_m: 2, speed: 0.25,
    flow_speed: 0.4 }, 1.2)]).slice(4, 8)], [2, 0.25, 0.4, 1.0], 1e-7);
// THE CROSS CONSTANTS are the mirror's accepted pair, per branch.
checkEq('flowing water keeps the SMALL cross factors (0.15 / 0.3)',
  glsl.includes('float crossA = still ? 0.6 : 0.15;')
  && glsl.includes('float crossB = still ? 1.3 : 0.3;'), true);
checkEq('…and both sheets are sent downstream, not counter-scrolled',
  glsl.includes('vec2 dirB = still ? -( ax * 0.8 + ay * crossB ) '
    + ': ax * 0.8 - ay * crossB;'), true);
// The three sheets' bearings and crest speeds, hand-derived above.
const deg = (v) => Math.atan2(v[1], v[0]) * 180 / Math.PI;
const dirA = [1, 0.15];
const dirB = [0.8, -0.3];
check('sheet A runs 8.53077° off the current', deg(dirA), 8.53076561, 1e-8);
check('…sheet B, 20.55605° the other way', deg(dirB), -20.55604522, 1e-8);
check('…so the two beat 29.08682° apart', deg(dirA) - deg(dirB), 29.08681083,
  1e-8);
check('sheet A\'s crests travel this multiple of sp', Math.hypot(...dirA),
  1.01118742, 1e-8);
check('…sheet B\'s', Math.hypot(...dirB), 0.85440037, 1e-8);
// At auto the surface runs at the 0.5 m/s default, so sheet A's crests make
// 0.5 · 1.01118742 = 0.50559371 m/s (they ran 0.15167811 m/s under the old 0.15).
check('at auto that is metres per second for sheet A',
  WATER_FLOW_SPEED_DEFAULT_M_S * Math.hypot(...dirA), 0.50559371, 1e-8);
check('…and at an authored 1 m/s', 1 * Math.hypot(...dirA), 1.01118742, 1e-8);

// ============================================================================
// [9] WHICH WAY THE PATTERN TRAVELS — the drift sign, DERIVED (finding H1)
// ============================================================================
// THE COMPLAINT, 2026-08-25: "Wasser fliesst nicht in Fliessrichtung". The flow
// FIELD is right — the bake's in-river tangent spread is <= 0.9 deg — and the
// surface still did not read as moving downstream. The mirror carried exactly
// this bug once (commit 09f2b29f): adding a drift to a SAMPLE coordinate
// slides the picture the OTHER way. So the sign is the first suspect, and it
// is settled here by algebra rather than by a screenshot.
//
// EACH SHEET'S SAMPLE COORDINATE is
//
//     uv(p, t) = F( p / lam + dir * ( t * sp * sgn / lam ) )
//
// with F the flow frame's squeeze (`twFrame`), a LINEAR and invertible map (it
// scales the along-flow axis by 1/aniso and leaves the cross one). A FIXED
// FEATURE of the wave map sits at a fixed uv0; the world point showing it
// follows from uv(p, t) = uv0:
//
//     F(p) / lam = uv0 - F(dir) * t * sp * sgn / lam
//     F(p)       = lam * uv0 - F(dir) * t * sp * sgn
//     d F(p)/dt  = -F(dir) * sp * sgn          (F is linear)
//     dp/dt      = -dir * sp * sgn             (apply F^-1)
//
// sgn = -1 therefore carries the crest along +dir (DOWNSTREAM) and sgn = +1
// along -dir (upstream). The shipped shader has `sgn = still ? 1.0 : -1.0`,
// i.e. the mirror's accepted convention, and it is CORRECT: H1's absent motion
// is not this sign but the depth coupling section [10] takes apart — over a
// shore there was no water normal left to carry a moving crest.
//
// THE SHARPEST FORM of the statement is an exact identity: a world point
// carried along with the crest must keep showing the same texel forever.
//
//     uv( p0 + dir * sp * t, t ) == uv( p0, 0 )   for every t
//
// Substituting, with sgn = -1:
//     F( (p0 + dir*sp*t)/lam + dir*(-t*sp/lam) ) = F( p0/lam ).  QED — exact,
// so the check below asserts it to 1e-12 and not to a tolerance.
//
// NUMBERS for a river running toward +x at sp = 0.5 m/s (the shipped auto
// default), lam = 1.6 m, aniso 3: after t = 2 s the crest that stood at the
// origin sits at dir * (sp * t) = dir * 1.0 m —
//
//     sheet A  dir = (1, 0.15)   -> (1.0,  0.15)  |d| = 1.01118742 m
//     sheet B  dir = (0.8, -0.3) -> (0.8, -0.30)  |d| = 0.85440037 m
//     sheet C  dir = (1, 0)      -> (1.0,  0.00)  |d| = 1.00000000 m
//
// — every one with a POSITIVE x component, i.e. downstream. With the sign
// flipped all three are negative: that is the red probe.
console.log('\n[9] the drift sign: the crests travel DOWNSTREAM (H1)');
const RIVER_AX = [1, 0];
const RIVER_AY = [-RIVER_AX[1], RIVER_AX[0]];   // = (0, 1), as the shader builds it
const SP = mat.WATER_FLOW_SPEED_DEFAULT_M_S;    // 0.5 m/s
const LAM_A = 1.6;
const LAM_B = 1.6 * 0.63;
const LAM_C = 1.6 * 2;
const ANISO = 3;
// The three sample coordinates, re-implemented from the arithmetic (as [5] is)
// and NOT read out of the GLSL string.
const uvSheet = (p, t, dir, lam, sgn, ax, ay, aniso) => twFrame(
  [p[0] / lam + dir[0] * (t * SP * sgn / lam),
    p[1] / lam + dir[1] * (t * SP * sgn / lam)], ax, ay, aniso);
const uvStreak = (p, t, sgn, ax, ay) => twFrame(
  [(p[0] + ax[0] * (t * SP * sgn)) / LAM_C,
    (p[1] + ax[1] * (t * SP * sgn)) / LAM_C], ax, ay, 8);
const DIR_A = [RIVER_AX[0] + RIVER_AY[0] * 0.15, RIVER_AX[1] + RIVER_AY[1] * 0.15];
const DIR_B = [RIVER_AX[0] * 0.8 - RIVER_AY[0] * 0.3,
  RIVER_AX[1] * 0.8 - RIVER_AY[1] * 0.3];
checkNear('sheet A\'s direction is ax + 0.15 ay', DIR_A, [1, 0.15], 1e-12);
checkNear('…sheet B\'s is 0.8 ax − 0.3 ay', DIR_B, [0.8, -0.3], 1e-12);
// THE IDENTITY, on an off-origin start point and at four times, per sheet.
const P0 = [7.25, -3.5];
const ride = (dir, t) => [P0[0] + dir[0] * SP * t, P0[1] + dir[1] * SP * t];
for (const t of [0.5, 2, 7.5, 60]) {
  checkNear(`sheet A: the point riding at dir·sp still shows uv0 at t = ${t}`,
    uvSheet(ride(DIR_A, t), t, DIR_A, LAM_A, -1, RIVER_AX, RIVER_AY, ANISO),
    uvSheet(P0, 0, DIR_A, LAM_A, -1, RIVER_AX, RIVER_AY, ANISO), 1e-12);
  checkNear(`…sheet B at t = ${t}`,
    uvSheet(ride(DIR_B, t), t, DIR_B, LAM_B, -1, RIVER_AX, RIVER_AY, ANISO),
    uvSheet(P0, 0, DIR_B, LAM_B, -1, RIVER_AX, RIVER_AY, ANISO), 1e-12);
  checkNear(`…and the streak ribbon at t = ${t}`,
    uvStreak(ride(RIVER_AX, t), t, -1, RIVER_AX, RIVER_AY),
    uvStreak(P0, 0, -1, RIVER_AX, RIVER_AY), 1e-12);
}
// A DIAGONAL CURRENT, so the answer is not an axis accident: flow (1,1)/√2.
const DAX = [Math.SQRT1_2, Math.SQRT1_2];
const DAY = [-DAX[1], DAX[0]];
const DDIR_A = [DAX[0] + DAY[0] * 0.15, DAX[1] + DAY[1] * 0.15];
checkNear('a DIAGONAL current: the same identity holds',
  uvSheet([P0[0] + DDIR_A[0] * SP * 3, P0[1] + DDIR_A[1] * SP * 3], 3,
    DDIR_A, LAM_A, -1, DAX, DAY, ANISO),
  uvSheet(P0, 0, DDIR_A, LAM_A, -1, DAX, DAY, ANISO), 1e-12);
// WHERE THE CREST IS after two seconds — dp/dt = −dir·sp·sgn, so p(t) − p0 is
// −dir·sp·t·sgn, which for sgn = −1 is +dir·1.0 m at t = 2 s.
const crestStep = (dir, t, sgn) => [-dir[0] * SP * t * sgn, -dir[1] * SP * t * sgn];
checkNear('after 2 s sheet A\'s crest has moved', crestStep(DIR_A, 2, -1),
  [1, 0.15], 1e-12);
checkNear('…sheet B\'s', crestStep(DIR_B, 2, -1), [0.8, -0.3], 1e-12);
checkNear('…and the ribbon\'s', crestStep(RIVER_AX, 2, -1), [1, 0], 1e-12);
checkAbove('all three carry a POSITIVE downstream component',
  Math.min(crestStep(DIR_A, 2, -1)[0], crestStep(DIR_B, 2, -1)[0],
    crestStep(RIVER_AX, 2, -1)[0]), 0);
check('sheet A\'s crest speed is sp·|dir|', SP * Math.hypot(...DIR_A),
  0.50559371, 1e-8);
// RED: the flipped sign — the bug the mirror had until 09f2b29f.
checkBelow('RED: with sgn = +1 sheet A\'s crest runs UPSTREAM',
  crestStep(DIR_A, 2, 1)[0], 0);
checkBelow('RED: …and so does sheet B\'s', crestStep(DIR_B, 2, 1)[0], 0);
checkBelow('RED: …and the ribbon\'s', crestStep(RIVER_AX, 2, 1)[0], 0);
checkEq('RED: …and the riding point no longer shows uv0',
  Math.abs(uvSheet(ride(DIR_A, 2), 2, DIR_A, LAM_A, 1, RIVER_AX, RIVER_AY,
    ANISO)[0]
    - uvSheet(P0, 0, DIR_A, LAM_A, 1, RIVER_AX, RIVER_AY, ANISO)[0]) > 0.1,
  true);
// STILL WATER keeps the +1 on purpose: a lake has no reference direction, and
// its two sheets are sent into OPPOSITE half-planes so no drift reads as one.
const STILL_DIR_A = [1, 0.6];
const STILL_DIR_B = [-0.8, -1.3];
checkBelow('a lake\'s two sheets point into opposite half-planes',
  STILL_DIR_A[0] * STILL_DIR_B[0] + STILL_DIR_A[1] * STILL_DIR_B[1], 0);
checkEq('…so the shader keeps the mirror\'s +1 for them',
  glsl.includes('float sgn = still ? 1.0 : -1.0;'), true);
// And the GLSL really spells the drift the derivation was made on.
checkEq('the drift is added to the SAMPLE coordinate, divided by each λ',
  glsl.includes('vec2 uvA = twFrame( p / lamA + dirA * ( uTlodTime * sp * sgn '
    + '/ lamA ), ax, ay, aniso );')
  && glsl.includes('vec2 uvB = twFrame( p / lamB + dirB * ( uTlodTime * sp * sgn '
    + '/ lamB ), ax, ay, aniso );'), true);
checkEq('…and the ribbon drifts along ax before its own division',
  glsl.includes('vec2 uvC = twFrame( ( p + ax * ( uTlodTime * sp * sgn ) ) '
    + '/ lamC, ax, ay, 8.0 );'), true);

// ============================================================================
// [10] SHALLOW WATER READS AS WATER — the two shares (finding H2)
// ============================================================================
// THE COMPLAINT, 2026-08-25: "warum kann es nicht halbtransparent sein?" —
// centimetre-deep water was drawn as land. It was, exactly: every water term
// rode ONE factor, the absorption `twA`, and the absorption is a DEPTH curve.
// At 5 cm over the default lake's 1.5 m opaque band it is 0.00325926, so the
// pixel got 99.7 % bed albedo (right, that IS see-through water) AND 0.3 % of
// its roughness, 0.3 % of its ripple and 0.3 % of its sky reflection (wrong:
// that is dry sand). The same coupling is why the correct downstream drift of
// section [9] was invisible over a shore.
//
// THE SPLIT. `twA` keeps the colour — `mix(bed, tint, twA)` IS the
// semi-transparent look. `twS`, the SURFACE share, carries the roughness, the
// metalness, the ripple tilt and the fresnel sky share.
//
// AND SINCE THE BED RULE OF 2026-08-25 IT CARRIES A SHALLOW RAMP (`waterShallow
// Ramp`): `twS = rim · inside · mix(0.35, 1, shore)`. H2 as first written gave
// those four terms their FULL say at every depth, and a full sky wash plus a
// full ripple tilt over a bed the absorption has barely touched is a surface the
// bed cannot be read through — the user's second report, "the bed is not visible
// down to a metre". The floor of 0.35 is what keeps H2's own answer: a film of
// water is still a surface, at a third of one, and never sand.
//
// THE HAND TABLE — default lake (bed 2.0 m, opaque band 1.5 m), rim ramp at its
// 0.05 m floor, well inside the outline so `inside` = 1. shore = t²(3 − 2t),
// ramp = 0.35 + 0.65·shore:
//
//   d = 0.025 m  rim 0.5  t = 1/60  shore = (1/3600)(3 − 1/30) = 89/108000
//                                         = 0.00082407
//                         ramp  = 0.35 + 0.65·0.00082407 = 0.35053565
//                         twS   = 0.5 · 0.35053565       = 0.17526782
//                         twA   = 89/108000 · 0.5        = 0.00041204
//   d = 0.05 m   rim 1    t = 1/30  shore = (1/900)(3 − 1/15) = 44/13500
//                                         = 0.00325926
//                         ramp  = twS = 0.35 + 0.00211852 = 0.35211852
//                         twA   = 0.00325926
//   d = 0.30 m   rim 1    t = 0.2   shore = 3(0.04) − 2(0.008) = 0.104
//                         ramp  = twS = 0.35 + 0.0676      = 0.4176
//                         twA   = 0.104
//   d = 1.50 m   rim 1    t = 1     shore = 1
//                         ramp  = twS = 1,  twA = 1
//
// WHAT EACH TERM BECOMES, over a sand bed (0.76, 0.70, 0.50), the library tint
// #3f7fb8 = (0.24705882, 0.49803922, 0.72156863), a ground roughness of 0.85,
// the water's 0.08, sky_mix 0.55 and a fresnel of 0.5 (a mid-angle look). Three
// rows now: what the picture does, what H2 alone did (surface at FULL), and
// what the coupling before H2 did (surface = absorption):
//
//                       d = 0.05 m        d = 0.30 m        d = 1.50 m
//   albedo (twA, kept) (0.75832822,      (0.70665412,      the tint,
//                       0.69934176,       0.67899608,       exactly
//                       0.50072216)       0.52304314)
//   roughness  NEW      0.57886874        0.52844800        0.08
//              H2       0.08              0.08              0.08
//              OLD      0.84749037        0.76992           0.08
//   sky share  NEW      0.09683259        0.11484000        0.275
//              H2       0.275             0.275             0.275
//              OLD      0.00089630        0.02860000        0.275
//
// The OLD row at 0.05 m is the red probe H2 named: a sky share of 0.0009 is no
// sky share, and a roughness of 0.847 out of a dry 0.85 is sand. The H2 row is
// the red probe of the NEW rule: a quarter of the pixel washed to sky colour
// over five centimetres of water is a surface the sand under it cannot be seen
// through — 2.84× the sky the picture now paints there.
console.log('\n[10] the two shares: colour by depth, surface by presence (H2)');
const LAKE_BED = 1.5;                    // the default lake's opaque band
/** The surface share of the default lake at one depth, rim ramp saturated and
 *  well inside the outline — the shape every check below reads. */
const surf = (d) => waterSurface(d, EDGE, 1, LAKE_BED);
check('the shallow ramp floor', WATER_SHALLOW_SURFACE_MIN, 0.35);
check('the surface share at 5 cm is a THIRD of one, not a whole one',
  surf(0.05), 0.35 + 0.65 * (44 / 13500), 1e-12);
check('…at 30 cm', surf(0.3), 0.35 + 0.65 * 0.104, 1e-12);
check('…and a whole one at the opaque depth', surf(1.5), 1);
check('…while the rim ramp itself still fades it in',
  surf(0.025), 0.5 * (0.35 + 0.65 * (89 / 108000)), 1e-12);
check('…and the shore gate still cuts the dilation ring',
  waterSurface(0.05, EDGE, waterInside(-2), LAKE_BED), 0);
vector("[10] water_shade: …and a dry pixel is no surface at all", { waterSurface: (...args) => waterSurface(...vectorArgs(args)) });
check('RED: H2 alone gave that 5 cm a WHOLE surface', 1, 1);
check('…i.e. this many times the sky wash the bed now shows through',
  1 / surf(0.05), 2.83995288, 1e-8);
// THE RAMP IS THE SHORE CURVE ITSELF — no second curve to keep in step.
check('the ramp is mix(0.35, 1, shore) and nothing else',
  waterShallowRamp(0.3, LAKE_BED),
  0.35 + 0.65 * waterAbsorb(0.3, LAKE_BED, EDGE), 1e-12);
vector("[10] water_shade: …so at the opaque depth it is 1 exactly", { waterShallowRamp: (...args) => waterShallowRamp(...vectorArgs(args)) });
check('…and a water shallower than the floor never gets there: a 0.6 m pond',
  waterShallowRamp(0.6, waterOpaqueDepthM(0.6)), 0.35 + 0.65 * 0.648, 1e-15);
vector("[10] water_shade: the ABSORPTION is unchanged — the colour still follows the depth", { waterAbsorb: (...args) => waterAbsorb(...vectorArgs(args)) });
vector("[10] water_shade: …at 30 cm", { waterAbsorb: (...args) => waterAbsorb(...vectorArgs(args)) });
vector("[10] water_shade: …and at the opaque depth", { waterAbsorb: (...args) => waterAbsorb(...vectorArgs(args)) });
vector("[10] water_shade: …and at a quarter of a floor-pixel it is the ramp times the curve", { waterAbsorb: (...args) => waterAbsorb(...vectorArgs(args)) });
// `twS >= twA` still holds, and that is arithmetic and not luck:
// `0.35 + 0.65·s >= s` for every s in 0…1, with equality only at s = 1.
checkAbove('the surface share is never below the absorption',
  Math.min(...[0.01, 0.05, 0.2, 0.75, 1.5, 3].map(
    (d) => surf(d) - waterAbsorb(d, LAKE_BED, EDGE))), -1e-15);
check('…and they meet exactly at the opaque depth',
  surf(1.5) - waterAbsorb(1.5, LAKE_BED, EDGE), 0);
// THE COLOUR — unchanged by H2, and it IS the semi-transparency asked for.
const SAND = [0.76, 0.70, 0.50];
const TINT = waterTintRgb(undefined);
checkNear('5 cm of water is 99.7 % sand',
  waterTintBlend(SAND, TINT, waterAbsorb(0.05, LAKE_BED, EDGE)),
  [0.75832822, 0.69934176, 0.50072216], 1e-7);
checkNear('…30 cm is a tenth of the way to the tint',
  waterTintBlend(SAND, TINT, waterAbsorb(0.3, LAKE_BED, EDGE)),
  [0.70665412, 0.67899608, 0.52304314], 1e-7);
checkNear('…and at the opaque depth the bed is gone',
  waterTintBlend(SAND, TINT, waterAbsorb(1.5, LAKE_BED, EDGE)), TINT, 1e-12);
// THE ROUGHNESS — the term that used to make shallow water dry sand.
const rough = (share) => 0.85 + (0.08 - 0.85) * share;
check('NEW: 5 cm of water is well smoother than sand, not a lake',
  rough(surf(0.05)), 0.57886874, 1e-8);
check('…and 30 cm smoother again', rough(surf(0.3)), 0.528448, 1e-12);
check('RED: H2 alone made that 5 cm as smooth as open water', rough(1), 0.08,
  1e-12);
check('RED: the OLD coupling left 5 cm at the roughness of dry ground',
  rough(waterAbsorb(0.05, LAKE_BED, EDGE)), 0.84749037, 1e-8);
check('RED: …and 30 cm barely better', rough(waterAbsorb(0.3, LAKE_BED, EDGE)),
  0.76992, 1e-12);
// THE SKY SHARE — the fresnel term, at a mid-angle fresnel of 0.5.
const skyShare = (fres, share) => Math.min(Math.max(fres * 0.55, 0), 1) * share;
check('NEW: 5 cm of water reflects a THIRD of the sky share',
  skyShare(0.5, surf(0.05)), 0.09683259, 1e-8);
check('…and a metre and a half reflects all of it',
  skyShare(0.5, surf(1.5)), 0.275, 1e-12);
check('RED: H2 alone washed that 5 cm with the FULL quarter',
  skyShare(0.5, 1), 0.275, 1e-12);
check('RED: the OLD coupling reflected all but nothing at 5 cm',
  skyShare(0.5, waterAbsorb(0.05, LAKE_BED, EDGE)), 0.00089630, 1e-8);
checkBelow('RED: …i.e. under a third of a percent of the sky',
  skyShare(0.5, waterAbsorb(0.05, LAKE_BED, EDGE)) / 0.275, 0.004);
check('RED: …and 2.9 % at 30 cm',
  skyShare(0.5, waterAbsorb(0.3, LAKE_BED, EDGE)), 0.0286, 1e-12);
// THE SHADING NORMAL — macro by depth, ripple tilt by presence.
const GROUND_N = [0.4472136, 0.89442719, 0];        // a bank tilted 26.5651°
const RIPPLE_N = [0.28734789, 0.95782629, 0];       // a crest tilted 16.6992°
const angleDeg = (a, b) => Math.acos(Math.min(1,
  a[0] * b[0] + a[1] * b[1] + a[2] * b[2])) * 180 / Math.PI;
const nShallow = waterShadeNormal(GROUND_N, RIPPLE_N,
  waterAbsorb(0.05, LAKE_BED, EDGE), surf(0.05));
checkNear('NEW: over 5 cm the ripple tilts the bank by its third',
  nShallow, [0.52790525, 0.84930327, 0], 1e-7);
check('…which is this many degrees off the bare bank',
  angleDeg(nShallow, GROUND_N), 5.298978, 1e-5);
const nH2 = waterShadeNormal(GROUND_N, RIPPLE_N,
  waterAbsorb(0.05, LAKE_BED, EDGE), 1);
checkNear('RED: H2 alone tilted it in FULL — the bank\'s own shape gone',
  nH2, [0.65197280, 0.75824235, 0], 1e-7);
check('…2.67× as far off the bank as the picture now goes',
  angleDeg(nH2, GROUND_N), 14.125457, 1e-5);
const nOld = (() => {
  const a = waterAbsorb(0.05, LAKE_BED, EDGE);
  const v = [GROUND_N[0] + (RIPPLE_N[0] - GROUND_N[0]) * a,
    GROUND_N[1] + (RIPPLE_N[1] - GROUND_N[1]) * a, 0];
  const l = Math.hypot(...v);
  return [v[0] / l, v[1] / l, v[2] / l];
})();
checkBelow('RED: the OLD mix(ground, ripple, twA) moved it by a thirtieth of a '
  + 'degree — no ripple, and nothing for the drift of [9] to move',
  angleDeg(nOld, GROUND_N), 0.04);
// (the two probe vectors are written to 8 places above, so the identity is
//  asserted to that many — the arithmetic itself is exact.)
checkNear('the deep-water answer is untouched: absorb 1 gives the ripple exactly',
  waterShadeNormal(GROUND_N, RIPPLE_N, 1, 1), RIPPLE_N, 1e-8);
checkNear('…and no surface at all gives the ground exactly',
  waterShadeNormal(GROUND_N, RIPPLE_N, 0, 0), GROUND_N, 1e-8);
checkNear('…a half-lit rim: macro half-flat, ripple half-strength',
  waterShadeNormal([0, 1, 0], RIPPLE_N, 0.5, 0.5),
  (() => {
    const v = [0.5 * RIPPLE_N[0], 1 + 0.5 * (RIPPLE_N[1] - 1), 0];
    const l = Math.hypot(...v);
    return [v[0] / l, v[1] / l, v[2] / l];
  })(), 1e-12);
// THE GLSL SAYS THE SAME SPLIT.
checkEq('the shader carries BOTH shares', glsl.includes('float twA;')
  && glsl.includes('float twS;'), true);
checkEq('…the surface share is the rim TIMES THE SHALLOW RAMP',
  glsl.includes('twS = rim * mix( 0.35, 1.0, shore );')
  && glsl.includes('twA = shore * rim;'), true);
checkEq('RED: …and it is no longer the bare rim, which is what hid the bed',
  glsl.includes('twS = rim;'), false);
checkEq('…the albedo keeps the depth curve',
  glsl.includes('diffuseColor.rgb = mix( diffuseColor.rgb, look0.rgb, twA );'),
  true);
checkEq('…the fresnel share of sky rides the SURFACE share',
  glsl.includes('clamp( fres * twSkyMix, 0.0, 1.0 ) * twS );'), true);
checkEq('RED: …and never the absorption again',
  glsl.includes('clamp( fres * twSkyMix, 0.0, 1.0 ) * twA );'), false);
checkEq('…the out stage leaves only where there is neither surface nor foam',
  glsl.includes('if ( twS <= 0.0 && twFoam <= 0.0 ) return;'), true);
checkEq('…the shading normal is macro-by-depth plus tilt-by-presence',
  glsl.includes('vec3 macro = mix( tlodNormalAt( vTlodXZ ), up, twA );')
  && glsl.includes('vec3 nw = normalize( macro + ( twN - up ) * twS );'), true);
checkEq('RED: …and not the old single blend',
  glsl.includes('normalize( mix( gn, wn, twA ) )'), false);
checkEq('the FOAM is untouched — it was never coupled wrongly',
  glsl.includes(
    `twFoam = rawFoam * min( shore + rawFoam * ${WATER_FOAM_MIN_COVER}, 1.0 ) * rim;`),
  true);


// ── [11] the conviction: which row a river through a forest picked ─────────
//
// THE USER'S EVIDENCE, 2026-08-25: "lake AND river show patches that look like
// forest floor, partly transparent and partly not; at the river the flow
// direction reads wrong; the rim transparency works in SOME lake spots."
//
// THE MECHANISM, and it is entirely in which ROW the fragment fetched. Until
// bake v10 the row came from the ground compositor's id mask — the PAIR
// (topmost painted layer, the one under it) — through
//
//     layer = twIsWater( a ) ? a : b;
//
// `scripts/smoke_height_bake.py` [12j] measures that pair on the very fixture
// the user describes: a river drawn into a forest area painted over it. At
// EVERY wet texel of the window the pair is (forest, forest) — layer 1 of that
// world's table, `water: false`. Neither half is water, so the pick fell
// through to `b`, a NON-water row, and every such row carried the world's
// PRIMARY water as a stand-in. The pixel therefore drew with a LAKE's numbers.
//
// THE TWO TABLES, spelled out. The world paints three kinds; the layer table is
// index 0 bare ground, then the painted kinds sorted by kind:
//
//     OLD, one row per LAYER:  0 bare -> stand-in (lake, is_water 0)
//                              1 g    -> stand-in (lake, is_water 0)
//                              2 lake -> the lake
//                              3 river-> the river
//     NEW, one row per KIND:   0 lake  1 river          (and nothing else)
//
// The bake names "river" at that texel, so the new pick is row 1, whatever the
// forest above it does.
console.log('\n[11] THE CONVICTION — the row a river under a forest picked (F-A II)');
// A deep, near-still lake and a shallow, fast river — two kinds a world really
// paints. `opaqueDepthM` is `max(1 m, ¾ · bed)`: 3.0 m and — the river's 0.9 m
// floored by the see-through rule of 2026-08-25 — 1.0 m.
const CONV_LAKE = waterLookFrom({ class: 'water', tint: '#002e57', wave_m: 2.0,
  speed: 0.05, flow_speed: 0, sky_mix: 0.55, roughness: 0.08 }, 4.0);
const CONV_RIVER = waterLookFrom({ class: 'water', tint: '#3f7fb8', wave_m: 1.2,
  speed: 0.05, flow_speed: 1.0, sky_mix: 0.55, roughness: 0.08 }, 1.2);
vector("[11] water_shade: the lake's opaque depth is ¾ of its 4 m bed", { waterLookFromValue: (args, path) => vectorValue(waterLookFrom(...vectorArgs(args)), path) });
vector("[11] water_shade: …and the river's is the floor over its 1.2 m one", { waterLookFromValue: (args, path) => vectorValue(waterLookFrom(...vectorArgs(args)), path) });
vector("[11] water_shade: …the lake does not flow", { waterLookFromValue: (args, path) => vectorValue(waterLookFrom(...vectorArgs(args)), path) });
vector("[11] water_shade: …and the river runs at 1 m/s", { waterLookFromValue: (args, path) => vectorValue(waterLookFrom(...vectorArgs(args)), path) });
// THE OLD PICK, reimplemented from the shader line it was: the stand-in rows
// are the primary water with the flag cleared, and the pair is (1, 1).
const OLD_ROWS = [CONV_LAKE, CONV_LAKE, CONV_LAKE, CONV_RIVER];
const OLD_IS_WATER = [false, false, true, true];
const oldPick = (a, b) => (OLD_IS_WATER[a] ? a : b);
const OLD_ROW = OLD_ROWS[oldPick(1, 1)];
// THE NEW PICK: the raster's own kind, straight into the per-kind table.
const NEW_ROWS = [CONV_LAKE, CONV_RIVER];
const NEW_ROW = NEW_ROWS[1];
check('RED: the old rule picked row 1 out of the pair (forest, forest)',
  oldPick(1, 1), 1);
check('RED: …which carried the LAKE\'s opaque depth on a river pixel',
  OLD_ROW.opaqueDepthM, 3.0);
check('the new rule reads the river\'s own', NEW_ROW.opaqueDepthM, 1.0);
checkNear('RED: …and the LAKE\'s tint', OLD_ROW.tint,
  [0, 46 / 255, 87 / 255], 1e-12);
checkNear('the new rule reads the river\'s', NEW_ROW.tint,
  [63 / 255, 127 / 255, 184 / 255], 1e-12);
// ── HOW MUCH OF THE FOREST FLOOR SHOWED THROUGH ───────────────────────────
// The absorption is `3t² − 2t³` with `t = d / opaque` (the rim ramp saturated,
// i.e. every depth from 0.05 m on). At 0.60 m of water — a river with a 1.2 m
// bed, half-filled:
//
//     NEW, opaque 1.0:  t = 0.6 -> 3(0.36) − 2(0.216) = 1.08 − 0.432 = 0.648
//     OLD, opaque 3.0:  t = 0.2 -> 3(0.04) − 2(0.008) = 0.12 − 0.016 = 0.104
//
// `diffuseColor = mix(bed, tint, absorb)`, so what is left of the BED is
// `1 − absorb`: 0.352 against 0.896. The forest floor under that river was
// drawn at 2.5454… × the share it should have had —
//
//     0.896 / 0.352 = 896 / 352 = 28 / 11 = 2.5454545454…
//
// — which is the "patches that look like forest floor" of the finding, and the
// "partly transparent, partly not" is the SAME pixel at another depth. (The
// ratio was 3.456 while the river's band was its bare ¾ of 0.9 m; the metre
// floor of the bed rule leaves more of the bed showing on BOTH sides of the
// comparison, and the row is still the whole defect.)
const CONV_D = 0.60;
check('NEW: at 0.6 m the river absorbs 0.648 of its bed',
  waterAbsorb(CONV_D, NEW_ROW.opaqueDepthM, EDGE), 0.648, 1e-12);
check('RED: with the lake\'s depth it absorbed 0.104',
  waterAbsorb(CONV_D, OLD_ROW.opaqueDepthM, EDGE), 0.104, 1e-12);
check('NEW: so 0.352 of the forest floor shows through',
  1 - waterAbsorb(CONV_D, NEW_ROW.opaqueDepthM, EDGE), 0.352, 1e-12);
check('RED: …where 0.896 of it did',
  1 - waterAbsorb(CONV_D, OLD_ROW.opaqueDepthM, EDGE), 0.896, 1e-12);
check('RED: …i.e. 28/11 as much forest as the water should have shown',
  (1 - waterAbsorb(CONV_D, OLD_ROW.opaqueDepthM, EDGE))
  / (1 - waterAbsorb(CONV_D, NEW_ROW.opaqueDepthM, EDGE)), 28 / 11, 1e-12);
// AND THE SAME MISS AT THE RIM, which is the other half of the evidence: the
// waterline of a lake reads right wherever the lake IS the topmost paint and
// wrong wherever it is not, on one and the same shore.
//     NEW, opaque 1.0: t = 0.225 -> 3(0.050625) − 2(0.011390625)
//                                 = 0.151875 − 0.02278125 = 0.12909375
//     OLD, opaque 3.0: t = 0.075 -> 3(0.005625) − 2(0.000421875)
//                                 = 0.016875 − 0.00084375 = 0.01603125
check('NEW: 0.225 m of river is an eighth absorbed',
  waterAbsorb(0.225, NEW_ROW.opaqueDepthM, EDGE), 0.12909375, 1e-12);
check('RED: with a 3 m opaque depth it was a sixtieth',
  waterAbsorb(0.225, OLD_ROW.opaqueDepthM, EDGE), 0.01603125, 1e-12);
// ── AND THE RIPPLE STOOD STILL ────────────────────────────────────────────
// `sp = still ? speed : flowSpeed * len` — the FRAME comes from the raster's
// flow vector and was always right, the SPEED comes from the row. A straight
// river's flow is the unit tangent (|flow| = 1, `heightfield` [12c]), so the
// crest travels at `flowSpeed · 1` metres per second downstream:
//
//     NEW: 1.0 m/s        OLD: the lake's 0 m/s — nothing moved at all.
//
// That is "die Fließrichtung stimmt nicht": the direction was never wrong, the
// pattern simply did not travel, and a surface that does not travel has no
// direction to read.
const CONV_LEN = 1.0;
check('NEW: the crest rides the river at 1 m/s', NEW_ROW.flowSpeed * CONV_LEN, 1.0);
check('RED: with the lake\'s dial it rode at nothing',
  OLD_ROW.flowSpeed * CONV_LEN, 0);
// A lake that DOES author a speed is the same defect with a softer number: the
// library default is 0.5 m/s, i.e. the river ran at half speed.
check('RED: …or at half speed where the primary water uses the shared default',
  WATER_LOOK_DEFAULT.flowSpeed * CONV_LEN / (NEW_ROW.flowSpeed * CONV_LEN), 0.5);
// THE WAVELENGTH WENT WITH IT — a river's 1.2 m ripple drawn at a lake's 2.0 m.
check('RED: and the ripple was a lake\'s 2.0 m wavelength', OLD_ROW.waveM, 2.0);
check('NEW: the river\'s own 1.2 m', NEW_ROW.waveM, 1.2);

console.log(`\n${passed + failed} checks, ${failed} failures`);
process.exit(failed ? 1 : 0);
