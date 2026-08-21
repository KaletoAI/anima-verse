#!/usr/bin/env node
/**
 * Smoke check for the WATER MIRROR ("Ein Boden" E4, § G4; tilted by "Ein
 * Wasser-Gesetz" W2) — the ruled surface over a painted water, the shore that
 * comes out of the height data, the E1 carve invariant measured from the CLIENT
 * side, and the wade/swim crossover against the LOCAL level.
 *
 * Usage:  node client3d/scripts/smoke_water_plane.mjs
 *         (transpiles `scene/waterPlaneMath.ts` and `game/walk.ts`; needs esbuild)
 *
 * The server halves are `scripts/smoke_height_bake.py` [8] (the profile and the
 * carve, on the bake) and `scripts/smoke_heightfield.py`. This is the READING:
 * the same formula, the same numbers, in the renderer. Every expected value
 * below is derived BY HAND in this docstring (§ B5a) — nothing here is a
 * recording of current output.
 *
 * ===========================================================================
 * [1] THE MIRROR IS A PROFILE, and it comes from the payload alone
 * ===========================================================================
 * `waterProfileOf(meta)` reads `meta.water_profile` — the nine numbers the bake
 * carved the bed against (W1 § 4). Reading it is the WHOLE water test: only an
 * area the server's one predicate called water carries one.
 *
 *     { water_profile: {…nine…} }         -> a profile      water
 *     { water_level_effective: 3.25 }     -> null           the MID level of a
 *                                                           profile is not one
 *     { water_level: 3.25 }               -> null           AUTHORED, not baked
 *     { }                                 -> null           not water
 *
 * The second one is new in W2 and load-bearing. `water_level_effective` is the
 * one plane a FLAT consumer draws, i.e. the mid level; a client that still read
 * it would put a river's mirror 2.4 m over its bed at one end and 2.4 m under
 * it at the other (see [6] for that arithmetic, in full).
 *
 * A profile with one unreadable number is NO profile: one NaN in a vertex
 * position and the whole mesh leaves the frustum. `flow_dir_deg: null` is the
 * one exception — that is the shape of still water.
 *
 * ===========================================================================
 * [2] THE SHORE — alpha out of the DEPTH, hand-derived
 * ===========================================================================
 * `depth(x, z) = plane y − h(x, z)`, with h out of the SAME R32F pyramids the
 * terrain's vertices are placed by. The alpha ramps over `WATER_SHORE_BAND_M`
 * = 1.5 m of DEPTH, `smoothstep(0, 1.5, depth)`, i.e. `t = depth/1.5` and
 * `3t² − 2t³`:
 *
 *     depth 0.15  -> t = 0.1  -> 3·0.01   − 2·0.001    = 0.028
 *     depth 0.30  -> t = 0.2  -> 3·0.04   − 2·0.008    = 0.104
 *     depth 0.375 -> t = 0.25 -> 3·0.0625 − 2·0.015625 = 0.15625
 *     depth 0.75  -> t = 0.5  -> 3·0.25   − 2·0.125    = 0.5
 *     depth 1.125 -> t = 0.75 -> 3·0.5625 − 2·0.421875 = 0.84375
 *     depth 1.5   -> t = 1                             = 1
 *     depth 4.0   -> clamped                           = 1
 *
 * WHY 1.5 m. The E1 default lake carves `water_depth_m = 2.0` over a
 * `shore_ramp_m = 3.0` ramp, by the very same smoothstep. 1.5 m of depth is
 * therefore `smoothstep = 0.75`, i.e. `3t² − 2t³ = 0.75`. Solving by hand:
 * t = 0.67 gives 0.7450, t = 0.68 gives 0.7581, so t ≈ 0.6736 and the full
 * opacity is reached `0.6736 · 3 = 2.02 m` inside the outline — the water fades
 * in over the first two thirds of the shore ramp the author drew and is fully
 * drawn by the time the bed levels off. A shallow pond authored with
 * `water_depth_m = 0.6` never reaches 1 at all (`waterShoreAlpha(0.6)` =
 * 0.352), which is exactly what a shallow pond looks like.
 *
 * The FOAM is `1 − smoothstep(0, 0.6, depth)` — full at the rim, gone at
 * 0.6 m — and it does two things: it whitens the outgoing light by
 * `foam · 0.6` and it adds `foam · 0.15` back to the alpha, so the very
 * shoreline keeps a faint lace instead of fading to invisible:
 *
 *     depth 0.0  foam 1        alpha 0     + 0.15    = 0.15
 *     depth 0.15 foam 0.84375  alpha 0.028 + 0.1266  = 0.1546
 *     depth 0.3  foam 0.5      alpha 0.104 + 0.075   = 0.179
 *     depth 0.45 foam 0.15625  alpha 0.216 + 0.0234  = 0.2394
 *     depth 0.6  foam 0        alpha 0.352 + 0       = 0.352
 *     depth 1.5  foam 0        alpha 1     + 0       = 1
 *
 * (`waterShoreAlpha(0.45)`: t = 0.3, 3·0.09 − 2·0.027 = 0.27 − 0.054 = 0.216.)
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
 * same: a terrain texel above the mirror inside the deep zone is not unlikely,
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
 * plane meeting the terrain — that IS the shoreline, and it is why the shader
 * discards at `depth ≤ 0` rather than drawing a zero-alpha fragment there.
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
 * [5] THE SLOPED MESH — one y per vertex, and a lake still comes out flat
 * ===========================================================================
 * `liftToWaterProfile` writes `waterLevelAt(profile, x, z)` into the `y` of
 * every `(x, y, z)` triplet of the earcut. On the fixture rectangle's four
 * corners that is
 *
 *     (20, ?, −40) -> 2.6      (80, ?, −40) -> 7.4
 *     (80, ?, −20) -> 7.4      (20, ?, −20) -> 2.6
 *
 * — a plane of slope 0.08 in x and constant in z, spanning 4.8 m of height over
 * the river's 60 m of length.
 *
 * NO SUBDIVISION IS NEEDED, and that is arithmetic, not taste: the profile is
 * LINEAR in the plane wherever the clamp is not active, and the clamp is only
 * active OUTSIDE `[s_min, s_max]` — which are the polygon's own extremes, so no
 * interior point reaches it. A ruled surface through the outline therefore
 * reproduces the function exactly. Checked at the midpoint and the quarter
 * point of the long edge:
 *
 *     ½ of the way from 2.6 to 7.4 = 5.0     = level(50)   ✓
 *     ¼ of the way                  = 3.8     = level(35)   ✓
 *
 * A LAKE IS BIT-IDENTICAL TO THE FLAT PLANE OF BEFORE. A still profile has
 * `flow_dir_deg = null`, `s_min = s_max = 0` and both ends equal, so every
 * vertex gets literally `level_up` — the same float, by `Object.is`, at every
 * corner. And the world y is the same float the old arrangement produced:
 * the mesh sat at `position.y = level` over vertices at 0, and `level + 0` and
 * `0 + level` are one number.
 *
 * ===========================================================================
 * [6] THE WADE/SWIM CROSSOVER, at the LOCAL level
 * ===========================================================================
 * `root = max(groundY + sink, waterLevel)`; the body reference is always
 * `root − sink`, so `body = max(groundY, waterLevel − sink)`. The two branches
 * meet where `groundY + sink = waterLevel`, i.e. at a DEPTH of exactly `sink`.
 * `floatRootY` is unchanged by W2 — what changed is what is fed into it.
 *
 * With the swim depth `sink = 0.6` and a mirror at `L = 3.0`:
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
 * [7] THE SHORE ON A SLOPE — why the shader needed no change
 * ===========================================================================
 * `wsDepth = vWaterPlane.y − tlodHeight(vWaterPlane.xz)`. `vWaterPlane` is the
 * fragment's WORLD position, so its `y` is the interpolated ruled surface — and
 * the interpolation of a linear function over a triangle IS that function.
 * The shore therefore measures against the LOCAL level for free, and on the
 * fixture river it answers the same alpha at every x:
 *
 *     depth 1.0 everywhere -> t = 1/1.5 = 2/3
 *                          -> 3·(4/9) − 2·(8/27) = 4/3 − 16/27 = 20/27
 *                          = 0.7407407407407407
 *
 * THE RED COUNTER-PROBE, again the flat plane at 5.0: its depth is
 * `5.0 − 0.08·x`, which reaches 0 at `x = 62.5` and is NEGATIVE above it. The
 * shader discards at `depth ≤ 0`, so a flat mirror over this river would simply
 * stop existing over its upper 17.5 m — the bed poking through the plane —
 * while below x = 62.5 it would be drawn at up to 2.92 m of false depth
 * (`waterShoreAlpha(2.92) = 1`, opaque) over a bed 1 m under the real line.
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
 * opposes — a river whose second layer ran upstream would read as two rivers:
 *
 *     A = wAx + wAy·0.6 ,  B = wAx·0.8 − wAy·1.3
 *
 * The fixture river flows 270°, i.e. `dir = (−1, 0)`, so `wAx = (−1, 0)` and
 * `wAy = (−0, −1) = (0, −1)`:
 *
 *     A = (−1, 0) + (0, −0.6)  = (−1.0, −0.6)   · flow = +1.0   downstream
 *     B = (−0.8, 0) − (0, −1.3) = (−0.8,  1.3)   · flow = +0.8   downstream
 *
 * and their cross components are −0.6 against +1.3: opposite signs, so the two
 * sheets still cross each other, which is what makes the surface read as water
 * rather than as a moving photograph.
 *
 * THE SPEEDS ARE UNTOUCHED, and that is a rotation argument: `|A| = √1.36` and
 * `|B| = √2.33` whichever way the frame points, so `uSpeed` still means the
 * metres per second it meant for a lake. Two more bearings, by the same
 * arithmetic:
 *
 *     0°  dir (0, 1):   wAx = ( 0, 1), wAy = (−1, 0)
 *                       A = (−0.6, 1.0)   B = ( 1.3, 0.8)   both +z
 *     90° dir (1, 0):   wAx = ( 1, 0), wAy = ( 0, 1)
 *                       A = ( 1.0, 0.6)   B = ( 0.8, −1.3)  both +x
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

const [W, walk] = await loadPure('client3d/src/scene/waterPlaneMath.ts',
                                 'client3d/src/game/walk.ts');
const { WATER_EDGE_FADE_M, WATER_FOAM_ALPHA, WATER_FOAM_BAND_M,
  WATER_FOAM_STRENGTH, WATER_SHORE_BAND_M, liftToWaterProfile, waterAlpha,
  waterEdgeFade, waterFlowVector, waterFoam, waterLevelAt, waterProfileOf,
  waterShoreAlpha, waterShoreBody, waterShoreGlsl } = W;
const { floatRootY, groundWaterLevel } = walk;

// ── The fixture, as the payload ships it ───────────────────────────────────
/** The nine numbers of the fixture river (docstring [4]). */
const RIVER_META = { flow_dir_deg: 270, water_level_up: 7.4,
  water_level_down: 2.6, water_level_effective: 5.0,
  water_profile: { level_up: 7.4, level_down: 2.6, flow_dir_deg: 270.0,
    axis_x: 50.0, axis_z: -30.0, dir_x: -1.0, dir_z: 0.0,
    s_min: -30.0, s_max: 30.0 } };
/** A still lake at 3.25 — the degenerate profile: no bearing, empty span. */
const LAKE_META = { water_level_effective: 3.25,
  water_profile: { level_up: 3.25, level_down: 3.25, flow_dir_deg: null,
    axis_x: 12.0, axis_z: -4.0, dir_x: 0.0, dir_z: 0.0,
    s_min: 0.0, s_max: 0.0 } };

// ── [1] the profile comes from the payload ─────────────────────────────────
console.log('[1] the mirror is a PROFILE, and only the payload names it');
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

// ── [2] the shore ──────────────────────────────────────────────────────────
console.log('\n[2] the shore ramp, out of the water DEPTH');
check('the band is the documented 1.5 m of depth', WATER_SHORE_BAND_M, 1.5);
check('the foam reaches 0.6 m', WATER_FOAM_BAND_M, 0.6);
check('the foam whitens by 0.6', WATER_FOAM_STRENGTH, 0.6);
check('the foam gives 0.15 of alpha back', WATER_FOAM_ALPHA, 0.15);
check('alpha at depth 0 — not water, the shader discards there',
  waterShoreAlpha(0), 0);
check('alpha at depth 0.15', waterShoreAlpha(0.15), 0.028);
check('alpha at depth 0.30', waterShoreAlpha(0.30), 0.104);
check('alpha at depth 0.375', waterShoreAlpha(0.375), 0.15625);
check('alpha at depth 0.45', waterShoreAlpha(0.45), 0.216);
check('alpha at depth 0.60', waterShoreAlpha(0.60), 0.352);
check('alpha at depth 0.75 — half, exactly, always', waterShoreAlpha(0.75), 0.5);
check('alpha at depth 1.125', waterShoreAlpha(1.125), 0.84375);
check('alpha at depth 1.5 — the band is through', waterShoreAlpha(1.5), 1);
check('alpha at depth 4.0 — clamped, a deep lake is not deeper drawn',
  waterShoreAlpha(4), 1);
check('a shallow pond (0.6 m bed) never reaches full opacity',
  waterShoreAlpha(0.6), 0.352);
check('a bed ABOVE the mirror is not water', waterShoreAlpha(-0.5), 0);

console.log('\n[2b] the foam, and the alpha it hands back at the rim');
check('foam at depth 0', waterFoam(0), 1);
check('foam at depth 0.15', waterFoam(0.15), 0.84375);
check('foam at depth 0.3', waterFoam(0.3), 0.5);
check('foam at depth 0.45', waterFoam(0.45), 0.15625);
check('foam at depth 0.6 — gone', waterFoam(0.6), 0);
check('foam at depth 2 — long gone', waterFoam(2), 0);
check('total alpha at depth 0 — a lace, not nothing', waterAlpha(0), 0.15);
check('total alpha at depth 0.15', waterAlpha(0.15), 0.028 + 0.84375 * 0.15);
check('total alpha at depth 0.3', waterAlpha(0.3), 0.104 + 0.5 * 0.15);
check('total alpha at depth 0.45', waterAlpha(0.45), 0.216 + 0.15625 * 0.15);
check('total alpha at depth 0.6 — the foam is out, the ramp alone answers',
  waterAlpha(0.6), 0.352);
check('total alpha at depth 1.5 — clamped at one', waterAlpha(1.5), 1);

// The GLSL twin: the smoke does not read the string for its numbers (that
// would only prove the string equals itself), but the two things that make it
// a SHADER rather than a comment are structural and are read.
console.log('\n[2c] the GLSL says the same thing, structurally');
const glsl = waterShoreGlsl();
const body = waterShoreBody();
check('the fragment reads the plane\'s own world y as the level',
  /vWaterPlane\.y - tlodHeight\( vWaterPlane\.xz, 0\.0 \)/.test(body) ? 1 : 0, 1);
check('…asking the FINEST mip (nodeStep 0 clamps to level 0)',
  /tlodHeight\( vWaterPlane\.xz, 0\.0 \)/.test(body) ? 1 : 0, 1);
check('the rim is discarded, not drawn at zero alpha',
  /if \( wsDepth <= 0\.0 \) discard;/.test(body) ? 1 : 0, 1);
check('the alpha is MULTIPLIED into diffuseColor.a, never assigned',
  /diffuseColor\.a \*=/.test(body) ? 1 : 0, 1);
check('the easing is the same smoothstep the arithmetic above uses',
  /return c \* c \* \( 3\.0 - 2\.0 \* c \);/.test(glsl) ? 1 : 0, 1);
check('no screen-space depth texture is sampled anywhere',
  /depthTexture|tDepth|viewZ/.test(glsl + body) ? 1 : 0, 0);
// W2: the shore was NOT touched, and that is the finding — it never knew the
// level as a number, so a level that varies over the mesh reaches it for free.
check('RED: no level uniform crept into the shore for the slope',
  /uWaterLevel|uLevel|uMirror/.test(glsl + body) ? 1 : 0, 0);

// ── [2d] the rim is faded, not merely discarded ────────────────────────────
// `waterAlpha(0)` is 0.15 BY DESIGN — the foam gives it back so the last hand's
// width of water can be seen. The discard then cut that 0.15 off at a boundary
// with no width, and a step with no width crawls sub-pixel as the camera moves.
// The fade is the one factor that reaches 0 exactly where the discard begins.
console.log('\n[2d] the rim fades to the discard instead of stepping to it');
check('the fade floor is 5 cm of depth', WATER_EDGE_FADE_M, 0.05);
check('RED: without it the rim was drawn at', waterAlpha(0), 0.15);
check('…with it the rim is drawn at', waterAlpha(0) * waterEdgeFade(0, 0.05), 0);
check('half a pixel in, half the fade', waterEdgeFade(0.025, 0.05), 0.5);
check('one pixel in, the fade is done', waterEdgeFade(0.05, 0.05), 1);
check('a pixel narrower than the floor still spends the floor',
  waterEdgeFade(0.025, 0.001), 0.5);
check('a metre-wide pixel far away spends the metre',
  waterEdgeFade(0.5, 1), 0.5);
check('the shader multiplies the fade in',
  /\* clamp\( wsDepth \/ wsEdge, 0\.0, 1\.0 \)/.test(body) ? 1 : 0, 1);
check('…and takes its derivative BEFORE the discard',
  body.indexOf('fwidth( wsDepth )')
    < body.indexOf('if ( wsDepth <= 0.0 ) discard;') ? 1 : 0, 1);

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
check('…and a bank already below the mirror is left where it is (min, never =)',
  carve(1.2, 0, LEVEL, DEPTH_M, RAMP_M), 1.2);

console.log('\n[3b] the RED counter-probe — a bump above the mirror is impossible');
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
console.log('\n[4c] the flow vector the ripple scrolls along');
checkEq('270° flows toward −x — dir = (sin θ, cos θ)', waterFlowVector(RIVER),
  [-1, 0]);
checkEq('a lake has no flow, and (0, 0) is what the shader reads as "still"',
  waterFlowVector(LAKE), [0, 0]);
checkEq('no profile at all is still water too', waterFlowVector(null), [0, 0]);
checkEq('a non-unit direction is normalised, never trusted',
  waterFlowVector({ ...RIVER, dir_x: 0, dir_z: 4 }), [0, 1]);
checkEq('a bearing with a zero direction cannot scroll anywhere',
  waterFlowVector({ ...RIVER, dir_x: 0, dir_z: 0 }), [0, 0]);

// ── [5] the sloped mesh ────────────────────────────────────────────────────
console.log('\n[5] the mirror mesh is a RULED surface — one y per vertex');
/** The earcut as three.js hands it over: (x, y, z) triplets with a meaningless
 *  y (whatever `rotateX(-π/2)` left of a zero — never exactly 0, which is why
 *  the lift WRITES it instead of adding to it). */
const CORNERS = [20, 6.1e-15, -40, 80, 6.1e-15, -40, 80, 6.1e-15, -20,
  20, 6.1e-15, -20];
const riverMesh = Float64Array.from(CORNERS);
liftToWaterProfile(riverMesh, RIVER);
checkEq('the four corners span 2.6 … 7.4',
  [riverMesh[1], riverMesh[4], riverMesh[7], riverMesh[10]],
  [2.6, 7.4, 7.4, 2.6]);
check('…i.e. 4.8 m of fall over the river\'s 60 m', riverMesh[4] - riverMesh[1],
  4.8, 1e-12);
check('the x of every vertex is untouched',
  riverMesh[0] + riverMesh[3] + riverMesh[6] + riverMesh[9], 200);
check('…and the z too',
  riverMesh[2] + riverMesh[5] + riverMesh[8] + riverMesh[11], -120);
// LINEARITY: no subdivision is needed because the ruled surface IS the
// function between the outline's vertices.
check('half way along the edge, the ruling agrees with the profile',
  (riverMesh[1] + riverMesh[4]) / 2, level(50), 1e-12);
check('…and a quarter of the way too',
  riverMesh[1] + (riverMesh[4] - riverMesh[1]) * 0.25, level(35), 1e-12);
check('…and seven eighths of the way',
  riverMesh[1] + (riverMesh[4] - riverMesh[1]) * 0.875, level(72.5), 1e-12);

console.log('\n[5b] a lake comes out FLAT, and bit-identically so');
const lakeMesh = Float64Array.from([0, 6.1e-15, 0, 40, 6.1e-15, 0,
  40, 6.1e-15, 40, 0, 6.1e-15, 40]);
liftToWaterProfile(lakeMesh, LAKE);
for (let i = 1; i < lakeMesh.length; i += 3) {
  checkIs(`vertex ${(i - 1) / 3} sits on the lake's one float`, lakeMesh[i],
    3.25);
}
checkIs('the OLD arrangement gave the same world y: level + 0 …', 3.25 + 0, 3.25);
checkIs('…and 0 + level are one number', 0 + 3.25, 3.25);
// A degenerate span must not divide by zero even with a bearing set — the
// server ships s_min == s_max == 0 for still water and the guard is the same.
checkIs('an empty span with a bearing set still answers level_up, never NaN',
  waterLevelAt({ ...RIVER, s_min: 0, s_max: 0 }, 999, 999), 7.4);
check('an odd tail of numbers is left alone rather than half-written',
  (() => { const a = [1, 9, 2, 5]; liftToWaterProfile(a, LAKE); return a[3]; })(),
  5);

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
  check(`x = ${x}: the root rides the local mirror`,
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
check('no mirror: the root is the ground, as it always was',
  floatRootY(7.25, null, SINK), 7.25);
check('…and the body still sinks into a bog by its own depth',
  floatRootY(7.25, null, 0.2) - 0.2, 7.05);
check('a NaN level is no level', floatRootY(7.25, NaN, SINK), 7.25);
check('a junk sink is no sink', floatRootY(7.25, LEVEL, NaN), Math.max(7.25, LEVEL));
check('a negative sink is no sink either', floatRootY(2.0, LEVEL, -1), LEVEL);

console.log('\n[6e] how far the mirror\'s word reaches (the twin of groundSink)');
checkEq('wilderness: the lake counts', groundWaterLevel(LEVEL, 'wilderness'), LEVEL);
checkEq('an OPEN place: it counts there too — the terrace of a house',
  groundWaterLevel(LEVEL, 'open'), LEVEL);
checkEq('a BUILT place: a tiled hall in a lake is a floor',
  groundWaterLevel(LEVEL, 'built'), null);
checkEq('no lake, no level', groundWaterLevel(null, 'open'), null);

// ── [7] the shore on a slope ───────────────────────────────────────────────
console.log('\n[7] the shore measures the LOCAL level, and needed no change');
// `vWaterPlane.y` is the interpolated ruled surface, i.e. the profile itself.
check('the alpha over the river is 20/27 at every x',
  Math.max(...[20, 26, 50, 74, 80].map(
    (x) => Math.abs(waterShoreAlpha(level(x) - bed(x)) - 20 / 27))),
  0, 1e-12);
check('…which is', waterShoreAlpha(1.0), 0.7407407407407407, 1e-15);
console.log('\n[7b] the RED counter-probe — the flat plane over the same river');
check('a flat mirror at 5.0 has NEGATIVE depth upstream of x = 62.5',
  MID - bed(74), -0.92, 1e-12);
check('…so the shader discards it: nothing is drawn there at all',
  waterShoreAlpha(MID - bed(74)), 0);
check('the waterline of the flat plane lies at x =', (MID - 0) / 0.08, 62.5, 1e-12);
check('…and downstream it is drawn fully opaque over a false 2.92 m of depth',
  waterShoreAlpha(MID - bed(26)), 1);

// ── [8] the RED counter-probes: the zone water is GONE ─────────────────────
console.log('\n[8] the RED counter-probes — the second water source is deleted');
const SOURCES = ['client3d/src/scene/waterPlaneMath.ts',
  'client3d/src/scene/waterPlane.ts', 'client3d/src/scene/ground.ts',
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
  // level the moment its mirror learned to tilt.
  'waterLevelOf', 'water_level_effective']) {
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
// And the mirror builder: one condition, and it is the profile.
const gr = texts.get('client3d/src/scene/ground.ts');
check('the mirror is built on the PROFILE alone',
  /const profile = waterProfileOf\(area\.meta\);/.test(gr) ? 1 : 0, 1);
check('…and typeAt reads the level AT THE POINT',
  /level = profile \? waterLevelAt\(profile, x, z\) : null;/.test(gr) ? 1 : 0, 1);

// ── [9] the ripple scrolls downstream ──────────────────────────────────────
// See the docstring section [9] for the derivation of every vector below.
console.log('\n[9] the ripple scroll direction follows the flow');
/** The shader's frame arithmetic, written out INDEPENDENTLY (the GLSL is
 *  checked structurally below). `flow` is `vWaterFlow`; (0, 0) is still. */
function rippleDirs([fx, fz]) {
  const len = Math.hypot(fx, fz);
  const still = len < 1e-4;
  const ax = still ? [1, 0] : [fx / Math.max(len, 1e-4), fz / Math.max(len, 1e-4)];
  const ay = [-ax[1], ax[0]];
  const a = [ax[0] + ay[0] * 0.6, ax[1] + ay[1] * 0.6];
  const b = still
    ? [-(ax[0] * 0.8 + ay[0] * 1.3), -(ax[1] * 0.8 + ay[1] * 1.3)]
    : [ax[0] * 0.8 - ay[0] * 1.3, ax[1] * 0.8 - ay[1] * 1.3];
  return [a, b];
}
const STILL = rippleDirs([0, 0]);
checkEq('still water: layer A is the constant that stood here before',
  STILL[0], [1, 0.6]);
checkEq('…and layer B is its counter-scrolling one', STILL[1], [-0.8, -1.3]);
const DOWN = rippleDirs(waterFlowVector(RIVER));   // 270° -> (−1, 0)
checkEq('the fixture river (270°, toward −x): layer A', DOWN[0], [-1, -0.6]);
checkEq('…and layer B', DOWN[1], [-0.8, 1.3]);
check('BOTH layers travel downstream — A along the flow',
  DOWN[0][0] * -1 + DOWN[0][1] * 0, 1, 1e-12);
check('…and B along it too (this is what a river reads as)',
  DOWN[1][0] * -1 + DOWN[1][1] * 0, 0.8, 1e-12);
check('…while their CROSS components oppose, so the two still beat',
  Math.sign(DOWN[0][1]) * Math.sign(DOWN[1][1]), -1);
// The SPEEDS are untouched, so uSpeed still means the metres per second it
// meant for a lake: the frame is a rotation, and a rotation keeps lengths.
check('layer A drifts at the same rate as on a lake',
  Math.hypot(...DOWN[0]) - Math.hypot(...STILL[0]), 0, 1e-12);
check('…and so does layer B', Math.hypot(...DOWN[1]) - Math.hypot(...STILL[1]),
  0, 1e-12);
check('…which are √1.36 and √2.33', Math.hypot(...STILL[0]), Math.sqrt(1.36), 1e-15);
for (const [deg, flow, a, b] of [
  [0, [0, 1], [-0.6, 1], [1.3, 0.8]],
  [90, [1, 0], [1, 0.6], [0.8, -1.3]],
  [270, [-1, 0], [-1, -0.6], [-0.8, 1.3]],
]) {
  const [da, db] = rippleDirs(flow);
  checkEq(`${deg}° -> A`, da.map((v) => Math.round(v * 1e12) / 1e12), a);
  checkEq(`${deg}° -> B`, db.map((v) => Math.round(v * 1e12) / 1e12), b);
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
  /vec2 wUvA = vWaterWorld \/ uWaveM \+ wDirA \* wDriftA;/.test(matSrc) ? 1 : 0, 1);
check('RED: no normalize of a possibly-zero vector anywhere in the patch',
  /normalize\( vWaterFlow \)/.test(matSrc) ? 1 : 0, 0);

console.log(`\n${passed} ok, ${failed} failed`);
process.exit(failed ? 1 : 0);
