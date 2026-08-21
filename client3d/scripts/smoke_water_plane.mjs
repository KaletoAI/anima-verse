#!/usr/bin/env node
/**
 * Smoke check for the WATER MIRROR ("Ein Boden" E4, § G4) — the flat plane at
 * `water_level_effective`, the shore that comes out of the height data, the E1
 * carve invariant measured from the CLIENT side, and the wade/swim crossover.
 *
 * Usage:  node client3d/scripts/smoke_water_plane.mjs
 *         (transpiles `scene/waterPlaneMath.ts` and `game/walk.ts`; needs esbuild)
 *
 * The server halves are `scripts/smoke_height_bake.py` [1b] (the carve, on the
 * bake) and `scripts/smoke_heightfield.py`. This is the READING: the same
 * formula, the same numbers, in the renderer. Every expected value below is
 * derived BY HAND in this docstring (§ B5a) — nothing here is a recording of
 * current output.
 *
 * ===========================================================================
 * [1] THE PLANE'S HEIGHT COMES FROM THE PAYLOAD, and from nothing else
 * ===========================================================================
 * `waterLevelOf(meta)` reads `meta.water_level_effective` — the level the BAKE
 * really carved with (§ A16 addendum § 2), derived from the rim median where
 * the author left `water_level` on "auto". Three cases:
 *
 *     { water_level_effective: 3.25 }             -> 3.25   a lake at 3.25 m
 *     { water_level: 3.25 }                       -> null   AUTHORED, not baked
 *     { }                                         -> null   not water
 *
 * The second one is the load-bearing one: the authored field may be unset, and
 * a client that fell back to it would put a mirror at a height the ground was
 * never carved to. A missing effective level therefore means NO MESH, which is
 * the honest answer — better a lake that is not drawn than one that floats.
 *
 * `water_level_effective: 0` must still be a level (a sea at world zero), and
 * junk must be `null` and never `NaN`: one NaN in a mesh position and the whole
 * plane disappears from the frustum.
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
 * The bake carves, per point inside the polygon (§ A16 addendum § 2):
 *
 *     h = min( h_nat, level − depth_m · smoothstep( min(d_in / ramp_m, 1) ) )
 *
 * `d_in` is the distance to the OUTLINE, `min` and never an assignment. The
 * invariant the contract states: beyond the ramp, `h ≤ level − ε` with
 * `ε = min(depth_m, 0.25)`.
 *
 * THE COUNTER-PROBE IS THE POINT, and it is a proof and not a sample. Beyond
 * the ramp `smoothstep(1) = 1` exactly, so the second argument of the `min` is
 * the CONSTANT `level − depth_m` — whatever the natural ground does there. A
 * bump of +40 m in the middle of the lake therefore comes out at
 * `level − depth_m` all the same: a terrain texel above the mirror inside the
 * deep zone is not unlikely, it is arithmetically impossible. Sampling could
 * only ever have said "not in these 4 489 probes"; this says "never".
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
 * [4] THE WADE/SWIM CROSSOVER — `floatRootY`
 * ===========================================================================
 * `root = max(groundY + sink, waterLevel)`; the body reference is always
 * `root − sink`, so `body = max(groundY, waterLevel − sink)`. The two branches
 * meet where `groundY + sink = waterLevel`, i.e. at a DEPTH of exactly `sink`.
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
 * Note the last column: from the crossover on, the body stays at `L − sink`
 * however deep the bed goes. BEFORE E4 it was `groundY − sink`, i.e. 0.4 at a
 * 2 m depth — 2.6 m under the water line, which is the user's screenshot of a
 * swimmer half inside the grass plate of the bank.
 *
 * Out of the water (`waterLevel = null`) nothing changes: `root = groundY`, and
 * a bog with `move_sink_m = 0.2` still swallows ankles the way it always did.
 *
 * `groundWaterLevel` gates the mirror by SCOPE exactly as `groundSink` gates
 * the depth: a tiled hall standing in a painted lake is a floor, so `'built'`
 * answers `null` and the figure stands on it.
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

const [W, walk] = await loadPure('client3d/src/scene/waterPlaneMath.ts',
                                 'client3d/src/game/walk.ts');
const { WATER_EDGE_FADE_M, WATER_FOAM_ALPHA, WATER_FOAM_BAND_M,
  WATER_FOAM_STRENGTH, WATER_SHORE_BAND_M, waterAlpha, waterEdgeFade, waterFoam,
  waterLevelOf, waterShoreAlpha, waterShoreBody, waterShoreGlsl } = W;
const { floatRootY, groundWaterLevel } = walk;

// ── [1] the level comes from the payload ───────────────────────────────────
console.log('[1] the mirror height is the BAKED level, never the authored one');
checkEq('an area with a baked level', waterLevelOf({ water_level_effective: 3.25 }), 3.25);
checkEq('a sea at world zero is still a level',
  waterLevelOf({ water_level_effective: 0 }), 0);
checkEq('the AUTHORED field alone is no level — the bed was never carved to it',
  waterLevelOf({ water_level: 3.25 }), null);
checkEq('an area that is not water', waterLevelOf({}), null);
checkEq('no meta at all', waterLevelOf(undefined), null);
checkEq('junk is null and never NaN', waterLevelOf({ water_level_effective: 'deep' }), null);
checkEq('…nor is Infinity a height',
  waterLevelOf({ water_level_effective: Infinity }), null);

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
/** The bake's carve, written out INDEPENDENTLY here (§ A16 addendum § 2) —
 *  never imported, so the check is against the contract and not against a
 *  shared helper that could be wrong in both places at once. */
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

// ── [4] the wade/swim crossover ────────────────────────────────────────────
console.log('\n[4] the figure floats on the LEVEL, not in the bed');
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

console.log('\n[4b] out of the water nothing changed');
check('no mirror: the root is the ground, as it always was',
  floatRootY(7.25, null, SINK), 7.25);
check('…and the body still sinks into a bog by its own depth',
  floatRootY(7.25, null, 0.2) - 0.2, 7.05);
check('a NaN level is no level', floatRootY(7.25, NaN, SINK), 7.25);
check('a junk sink is no sink', floatRootY(7.25, LEVEL, NaN), Math.max(7.25, LEVEL));
check('a negative sink is no sink either', floatRootY(2.0, LEVEL, -1), LEVEL);

console.log('\n[4c] how far the mirror\'s word reaches (the twin of groundSink)');
checkEq('wilderness: the lake counts', groundWaterLevel(LEVEL, 'wilderness'), LEVEL);
checkEq('an OPEN place: it counts there too — the terrace of a house',
  groundWaterLevel(LEVEL, 'open'), LEVEL);
checkEq('a BUILT place: a tiled hall in a lake is a floor',
  groundWaterLevel(LEVEL, 'built'), null);
checkEq('no lake, no level', groundWaterLevel(null, 'open'), null);

console.log('\n[5] the zone water under a point — the swimmer\'s half (§ A19 no. 5)');
// zoneWaterAt(waters, x, z, inside): a room whose floor is water ranks ABOVE
// painted areas, and among overlapping zones the LAST one wins — the same
// last-wins reading the layer mask uses. The ring test is INJECTED (the module
// stays import-free); this even-odd twin is the textbook crossing rule.
const inside = (x, z, ring) => {
  let hit = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, zi] = ring[i];
    const [xj, zj] = ring[j];
    if ((zi > z) !== (zj > z) && x < (xj - xi) * (z - zi) / (zj - zi) + xi) hit = !hit;
  }
  return hit;
};
const POND = { kind: 'water', polygon: [[0, 0], [10, 0], [10, 10], [0, 10]],
  water_level_effective: 2.0 };
const POOL = { kind: 'pool_tile', polygon: [[4, 4], [8, 4], [8, 8], [4, 8]],
  water_level_effective: 3.5 };
check('a point in the pond carries the pond\'s mirror',
  W.zoneWaterAt([POND, POOL], 2, 2, inside)?.level ?? null, 2.0);
check('overlap: the LAST zone wins, like the mask',
  W.zoneWaterAt([POND, POOL], 5, 5, inside)?.level ?? null, 3.5);
checkEq('outside every zone the answer is null',
  W.zoneWaterAt([POND, POOL], 20, 20, inside), null);
checkEq('a zone the bake never carved (null level) is skipped, never 0',
  W.zoneWaterAt([{ kind: 'water', polygon: POND.polygon,
    water_level_effective: null }], 2, 2, inside), null);
// The end of the chain: over the pond's 0.0 bed the figure floats at the
// mirror — root = max(0.0 + 0.35, 2.0) = 2.0 (the E4 law, now fed by a ZONE).
check('…and the swimmer floats at the zone mirror',
  walk.floatRootY(0.0, W.zoneWaterAt([POND], 2, 2, inside).level, SINK), 2.0);

console.log(`\n${passed} ok, ${failed} failed`);
process.exit(failed ? 1 : 0);
