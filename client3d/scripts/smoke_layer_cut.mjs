#!/usr/bin/env node
/**
 * Smoke check for the LAYER CUT of the ground ("Ein Boden" E3, § G3) — the
 * arithmetic the terrain material composites its material with, and the proof
 * that the three ladders it replaces are really gone.
 *
 * Usage:  node client3d/scripts/smoke_layer_cut.mjs
 *         (transpiles `@anima/scene-render` `layerCut.ts`; needs esbuild)
 *
 * The server half is `scripts/smoke_terrain_layers.py` — the BAKE. This is the
 * READING: the same bytes, the same quantisation, the same blend, on the client
 * side. Every number below is derived by hand in this docstring (§ B5a).
 *
 * ===========================================================================
 * [1] THE CUT — `layerWeight(sd, blendM, fw)`
 * ===========================================================================
 * How much of layer A a fragment shows. Two cases.
 *
 * (a) A SOFT TRANSITION of width `b`, centred on the line:
 *     `smoothstep(−b/2, +b/2, sd)`, i.e. `t = clamp((sd + b/2)/b, 0, 1)` and
 *     `3t² − 2t³`. HALF THE WIDTH LIES ON EACH SIDE, so a "1.5 m blend" really
 *     is 1.5 m of ground and not three. At b = 1.5, by hand:
 *
 *         sd = −0.75  ->  t = 0     -> 0
 *         sd = −0.375 ->  t = 0.25  -> 3·0.0625 − 2·0.015625 = 0.15625
 *         sd =  0     ->  t = 0.5   -> 0.5             (exactly, always)
 *         sd = +0.375 ->  t = 0.75  -> 0.84375
 *         sd = +0.75  ->  t = 1     -> 1
 *         sd = ±20    ->  clamped   -> 1 / 0
 *
 *     The three middle numbers are the very ones the old alpha fringe was
 *     pinned on (`ngEdgeAlpha`, 0.15625 / 0.5 / 0.84375) — the LOOK is
 *     unchanged, only its mechanism is.
 *
 * (b) A HARD CUT, `b = 0`, ANALYTICALLY ANTI-ALIASED: `clamp(sd/fw + 0.5,
 *     0, 1)` where `fw` is one pixel measured in WORLD METRES —
 *     `max(length(dFdx(world)), length(dFdy(world)))`, never `fwidth(sd)`
 *     (finding round 2026-08-21, [5] below).
 *     That is a step ONE PIXEL wide wherever the camera stands. By hand with
 *     fw = 0.1 m (a pixel a decimetre across, i.e. standing on the ground):
 *
 *         sd = −0.05 -> 0      sd = −0.025 -> 0.25     sd = 0    -> 0.5
 *         sd = +0.025 -> 0.75  sd = +0.05  -> 1        sd = ±1   -> 1 / 0
 *
 *     and with fw = 4 m (a pixel four metres across, i.e. from far away) the
 *     same sd = 1 m reads 0.75 instead of 1 — the two grounds are AVERAGED at
 *     that distance rather than shimmering between them. A bare `step()` would
 *     stair-step along every diagonal; a fixed-width smoothstep would blur the
 *     near edge and still alias the far one.
 *
 * ===========================================================================
 * [2] THE NOISE PUSH — an organic border, and a hard cut that stays hard
 * ===========================================================================
 * `lcPushedSd` adds `(noise·2 − 1) · cap` to the distance, with
 * `cap = min(0.5, b/2)`:
 *
 *     b = 1.5 -> cap = min(0.5, 0.75) = 0.5   the full push, today's fringe
 *     b = 0.6 -> cap = min(0.5, 0.30) = 0.3   never more than half the blend
 *     b = 0   -> cap = 0                      THE HARD CUT DOES NOT MOVE
 *
 * The cap is what makes a room floor end on the metre it was drawn on while a
 * meadow finds its own way. The noise itself is the fract-sin value noise of
 * `naturalGround.ts`, unchanged, so the two look the same.
 *
 * ===========================================================================
 * [3] THE MASK, READ — a hand-built window, decoded texel by texel
 * ===========================================================================
 * One tile, 4 m across, at the world origin, with `id_step 1`, `sd_step 0.5`,
 * band 8, zero 128, 15.875 codes per metre — the server's own format numbers.
 * A single boundary at x = 2, layer 1 to the east (painted later, so A = 1) and
 * layer 0 to the west (B = 0). Every id texel therefore carries (1, 0); the
 * sd texel at centre `0.5m + 0.25` carries its signed distance to x = 2:
 *
 *     m = 0..3  centres 0.25 0.75 1.25 1.75  ->  −1.75 −1.25 −0.75 −0.25
 *     m = 4..7  centres 2.25 2.75 3.25 3.75  ->  +0.25 +0.75 +1.25 +1.75
 *
 * quantised as `round(sd·15.875) + 128`, i.e. codes 100, 108, 116, 124, 132,
 * 140, 148, 156. `layerPairAt` must read (1, 0) anywhere in the tile,
 * `layerSdAt` the value of the texel a point falls in, and `topLayerAt` — the
 * undergrowth gate — must answer 0 west of the line and 1 east of it.
 *
 * OUTSIDE THE WINDOW everything answers bare ground, which is what an unloaded
 * tile draws.
 *
 * ===========================================================================
 * [4b] TWO BOUNDARIES IN ONE NEIGHBOURHOOD — where the sign stops meaning
 * ===========================================================================
 * The sign of an sd texel says "on A's side of MY pair", so two texels signed
 * against two different pairs are two numbers on two scales. A hardware LINEAR
 * fetch reaches half a texel past the id texel and mixes exactly those — which
 * drew a strip of the kitchen's rubber a metre and a half inside the living
 * room of "Haus von Kai", along the whole medial axis of the west wall and the
 * kitchen line. The fixture below is that neighbourhood, decoded out of the
 * running world and moved to the origin: the filtered fetch answers +0.47 where
 * the reading of the fragment's OWN id texel answers −1.26.
 *
 * ===========================================================================
 * [4] A UNIFORM TILE, AND A MISSING ONE
 * ===========================================================================
 * A tile the bake answered `{"uniform": 2}` for fills its whole square with the
 * pair (2, 2) and keeps the neutral distance (code 255 = +8 m), which composites
 * to "layer 2, whole". A tile the batch never brought stays at the neutral fill,
 * i.e. bare ground — the same statement an unindexed tile makes.
 *
 * ===========================================================================
 * [5] THE GLSL — one string, and what has to be in it
 * ===========================================================================
 * Not read for its arithmetic (the smoke reimplements that above, so a check
 * that read the string could only prove the string equals itself), but for the
 * things a compiler would refuse or a driver would answer wrongly:
 *  - `usampler2D` + `texelFetch` for the id, because an INTEGER texture cannot
 *    be filtered at all — NEAREST is enforced by the format rather than by a
 *    sampler setting;
 *  - `sampler2DArray` for the surfaces, one slice per layer, sampled with an
 *    EXPLICIT gradient (`textureGrad`): every layer scales the world position
 *    by its own metres-per-tile, so the uv JUMPS at a boundary and an implicit
 *    derivative would ask for the coarsest mip — a blurred line along every
 *    edge in the world. The two masks are read with `texelFetch`, which asks
 *    for no derivative and no filter at all: the id because an integer texture
 *    cannot be filtered, the distance because the four texels the bake signed
 *    together are the only ones that may be mixed ([4b]);
 *  - `fwidth` OUTSIDE any branch that differs across a quad (a derivative taken
 *    in non-uniform control flow is undefined in GLSL ES);
 *  - the per-layer array sized by a compile-time constant.
 *
 * ===========================================================================
 * [6] THE RED COUNTER-PROBES — the ladders are GONE
 * ===========================================================================
 * The whole point of E3 is a deletion, and a deletion is the one thing a
 * positive check cannot measure. So the sources are read for the names of the
 * three crutches that used to hold the drape stack apart:
 * `AREA_RENDER_ORDER_BASE`, `AREA_POLYGON_OFFSET`, `AREA_OFFSET_MAX`,
 * `AREA_Y_STEP_M`, `AREA_Y_MAX_M`, plus the fringe machinery
 * (`ngRefineEdgeBand`, `NG_EDGE_BAND_M`, `aEdgeDist`) and the dead `gridPlate`.
 * None of them may appear as CODE anywhere in the client or the shared package.
 *
 * And the scene-graph builder must not stack: `rebuildAreas` may set no
 * `renderOrder`, no `polygonOffset` and — since E4 — no `position.y` at all.
 * The last one it had was `WATER_DRAPE_LIFT_M`, the two centimetres that kept
 * the water drape off its own bed; the drape is a MIRROR now
 * (`scene/waterPlane.ts`) which carries its height in its own vertices, and the
 * constant is checked to be gone from the code like the ladders are.
 *
 * ===========================================================================
 * [7b] WATER WEARS ITS BED, AND THE SERVER SAYS WHICH (W1 § 5)
 * ===========================================================================
 * A water layer is a full layer — the mask has to answer "here is water" for
 * the undergrowth gate and every point query — but what it PAINTS is the ground
 * underneath, because the mirror is a second surface drawn over it and painting
 * the lake twice made the two fight each other.
 *
 * WHO DECIDES THAT MOVED. Until W1 this client decided it: `setLayerTable`
 * substituted layer 0's image (`layer.water ? bare : layer`) for every water
 * row, which flattened an authored gravel bed back to the world's default kind
 * and was a renderer inventing ground. Now the server ships it — `surface` on a
 * water row IS the bed's, `bed_kind` names the kind it came from, and
 * `edge_blend_m` is the bed's too wherever a bed was authored. So the client's
 * whole job is to render the surface the table names, and the three checks
 * below are: the substitution is gone, the kind fallback asks the bed, and the
 * bed is part of the key that rebuilds the slice array.
 *
 * THE KEY IS A COUNTING ARGUMENT, not taste. The server keys a layer by
 * `(kind, edge_blend_m, bed_kind)`, so two ponds of one kind on two beds are
 * two rows with two images. A client whose `layerKey` left `bed_kind` out would
 * see one string for both worlds and keep yesterday's slice array standing.
 */
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');

/** `layerCut.ts` is import-free by design (its header says so), so a transpile
 *  is all it takes. Should someone add a runtime import, this fails loudly. */
async function loadPure(rel) {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'layercut-'));
  try {
    const source = await readFile(join(ROOT, rel), 'utf8');
    const code = esbuild.transformSync(source, { loader: 'ts', format: 'esm' }).code;
    const file = join(dir, 'layerCut.mjs');
    await writeFile(file, code, 'utf8');
    return await import(`file://${file}`);
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

const L = await loadPure('packages/scene-render/src/layerCut.ts');
const { decodeSd, layerPairAt, layerSdAt, layerSdBlockAt, layerWeight,
  lcPushedSd, packLayerWindow, terrainLayerGlsl, topLayerAt } = L;

// --- [1] the cut ------------------------------------------------------------
console.log('[1] layerWeight — the soft blend and the anti-aliased hard cut');
check('b = 1.5, half a width out: nothing of A', layerWeight(-0.75, 1.5, 0.1), 0);
check('…a quarter of the way in, on the smoothstep curve',
  layerWeight(-0.375, 1.5, 0.1), 0.15625);
check('…ON the line it is exactly half, whatever the width',
  layerWeight(0, 1.5, 0.1), 0.5);
check('…and at width 8 it is still exactly half', layerWeight(0, 8, 0.1), 0.5);
check('…three quarters of the way', layerWeight(0.375, 1.5, 0.1), 0.84375);
check('…half a width in: all of A', layerWeight(0.75, 1.5, 0.1), 1);
checkEq('…and past it, clamped',
  [layerWeight(20, 1.5, 0.1), layerWeight(-20, 1.5, 0.1)], [1, 0]);
console.log('  — the hard cut (b = 0) is one PIXEL wide, wherever the camera is');
check('standing on it (a pixel is 0.1 m): 2.5 cm out', layerWeight(-0.025, 0, 0.1), 0.25);
check('…on the line', layerWeight(0, 0, 0.1), 0.5);
check('…2.5 cm in', layerWeight(0.025, 0, 0.1), 0.75);
check('…and 5 cm in it is whole', layerWeight(0.05, 0, 0.1), 1);
check('far away (a pixel is 4 m): a whole metre in is only three quarters',
  layerWeight(1, 0, 4), 0.75);
check('…which is the AVERAGE the far edge needs instead of a shimmer',
  layerWeight(0, 0, 4), 0.5);
check('a hard cut with no derivative at all still answers, and answers hard',
  layerWeight(1, 0, 0), 1);

// --- [2] the noise push -----------------------------------------------------
console.log('\n[2] lcPushedSd — an organic border, and a hard cut that stays hard');
check('a hard cut does not move, whatever the noise says',
  lcPushedSd(0.3, 0, 12.34, 56.78) - 0.3, 0);
const pushed = lcPushedSd(0, 1.5, 12.34, 56.78);
check('…while a 1.5 m blend is pushed by at most half a metre',
  Math.abs(pushed) <= 0.5 + 1e-12 ? 1 : 0, 1);
check('…and really is pushed (the border is not the polygon)',
  Math.abs(pushed) > 1e-6 ? 1 : 0, 1);
// The cap is min(NOISE, b/2), so a NARROW blend gets a proportionally smaller
// push: at b = 0.6 the cap is 0.3, and the same world point must move less.
const wide = Math.abs(lcPushedSd(0, 1.5, 12.34, 56.78));
const narrow = Math.abs(lcPushedSd(0, 0.6, 12.34, 56.78));
check('a narrow blend is pushed by less, in the ratio of the caps',
  narrow / wide, 0.3 / 0.5, 1e-12);
check('…and never by more than half the blend',
  narrow <= 0.3 + 1e-12 ? 1 : 0, 1);
check('the noise is deterministic — the same point, the same push',
  lcPushedSd(0, 1.5, 12.34, 56.78), pushed);

// --- [3] the mask, read -----------------------------------------------------
console.log('\n[3] the mask — a hand-built window, decoded texel by texel');
const FMT = {
  sig: 'hand', tile_m: 4, id_step_m: 1, sd_step_m: 0.5,
  sd_band_m: 8, sd_zero: 128, sd_codes_per_m: 127 / 8,
};
/** The tile of the docstring: a boundary at x = 2, layer 1 east, layer 0 west,
 *  the pair (1, 0) everywhere. */
function handTile() {
  const idN = 4;
  const sdN = 8;
  const id = new Uint8Array(idN * idN * 2);
  for (let k = 0; k < idN * idN; k += 1) {
    id[k * 2] = 1;
    id[k * 2 + 1] = 0;
  }
  const sd = new Uint8Array(sdN * sdN);
  for (let j = 0; j < sdN; j += 1) {
    for (let i = 0; i < sdN; i += 1) {
      const x = i * 0.5 + 0.25;
      sd[j * sdN + i] = Math.round((x - 2) * (127 / 8)) + 128;
    }
  }
  const b64 = (bytes) => Buffer.from(bytes).toString('base64');
  return { origin_x: 0, origin_z: 0, id_size: idN, sd_size: sdN,
           id: b64(id), sd: b64(sd) };
}
const win = packLayerWindow(new Map([['0,0', handTile()]]), FMT);
checkEq('the window is the tile, at its own origin and steps',
  [win.originX, win.originZ, win.idStep, win.sdStep, win.idSize, win.sdSize],
  [0, 0, 1, 0.5, 4, 8]);
checkEq('the quantisation travels with it, out of the payload',
  [win.sdZero, win.sdCodesPerM, win.sdBandM], [128, 127 / 8, 8]);
checkEq('the codes are the eight the hand derivation names',
  [...win.sd.slice(0, 8)], [100, 108, 116, 124, 132, 140, 148, 156]);
checkEq('the pair is the SAME on both sides of the line',
  [layerPairAt(win, 1.5, 2), layerPairAt(win, 2.5, 2)], [[1, 0], [1, 0]]);
check('…and the distance is what turns over', layerSdAt(win, 1.75, 2),
  decodeSd(124, 128, 127 / 8), 1e-12);
check('…on the other side', layerSdAt(win, 2.25, 2),
  decodeSd(132, 128, 127 / 8), 1e-12);
check('the decode is the server\'s own arithmetic',
  decodeSd(124, 128, 127 / 8), -4 / (127 / 8), 1e-12);
console.log('  — and the gate the undergrowth reads (decision 5.2)');
checkEq('west of the line the ground is layer 0, east of it layer 1',
  [topLayerAt(win, 0.25, 2), topLayerAt(win, 1.75, 2),
   topLayerAt(win, 2.25, 2), topLayerAt(win, 3.75, 2)], [0, 0, 1, 1]);
checkEq('outside the window, and without one, everything is bare ground',
  [topLayerAt(win, -50, 0), topLayerAt(null, 1, 1), layerPairAt(null, 0, 0)],
  [0, 0, [0, 0]]);

// --- [4] a uniform tile, and a missing one ----------------------------------
console.log('\n[4] a uniform tile, and a missing one');
const two = packLayerWindow(new Map([
  ['0,0', { origin_x: 0, origin_z: 0, uniform: 2 }],
  ['1,0', handTile()],
]), FMT);
checkEq('a uniform tile fills its whole square with (2, 2)',
  [layerPairAt(two, 0.5, 0.5), layerPairAt(two, 3.5, 3.5)], [[2, 2], [2, 2]]);
check('…at the neutral distance, which composites to "layer 2, whole"',
  layerSdAt(two, 2, 2), 8, 1e-12);
check('…so the gate reads it as layer 2', topLayerAt(two, 2, 2), 2);
checkEq('…and the tile beside it keeps its own pair',
  layerPairAt(two, 5.5, 2), [1, 0]);
// The window is SQUARE by the larger axis: two tiles across, one down, so the
// second row of tiles is surplus and stays at the neutral fill — bare ground.
checkEq('the surplus of the square window is bare ground',
  [layerPairAt(two, 2, 6), topLayerAt(two, 2, 6)], [[0, 0], 0]);
checkEq('an empty batch has no window at all',
  packLayerWindow(new Map(), FMT), null);

// --- [4b] TWO BOUNDARIES IN ONE NEIGHBOURHOOD -------------------------------
// The RED probe of the second finding round (2026-08-21). The numbers are the
// ones decoded out of the running world, living room of "Haus von Kai", around
// world (−1553.0, −759.9) — only moved to the origin:
//
//   id (x 1..2, z 1..2) = (2, 1)  the kitchen line: rubber over the floor
//   id (x 0..1, z 1..2) = (1, 0)  the west wall:    floor over the meadow
//   id (      z 0..1  ) = (1, 1)  collapsed — a metre deep inside the floor
//
//   sd, x centres      0.25    0.75    1.25    1.75
//     z 1.75 / 1.25   +1.26   +1.26   −1.26   −1.26   (signed vs the kitchen
//     z 0.75 / 0.25   +1.26   +1.26   +1.76   −1.76    line / vs own sites)
//
// A HARDWARE LINEAR FETCH at (1.05, 1.05) mixes the four texels around it —
// two of which belong to the id texels next door and carry the sign of ANOTHER
// boundary — and lands at +0.47: positive, i.e. "on the rubber's side", one and
// a half metres inside the living room. That was the patch under the chairs.
// Reconstructed from the four texels of the fragment's OWN id texel, all signed
// against (2, 1), the answer is −1.26 and the floor stays wood.
console.log('\n[4b] two boundaries in one neighbourhood — the sign is per PAIR');
function cornerTile() {
  const idN = 4;
  const sdN = 8;
  const id = new Uint8Array(idN * idN * 2);
  for (let j = 0; j < idN; j += 1) {
    for (let i = 0; i < idN; i += 1) {
      const k = (j * idN + i) * 2;
      const deep = j < 1;                    // z 0..1 — collapsed
      id[k] = deep ? 1 : (i === 0 ? 1 : i === 1 ? 2 : 1);
      id[k + 1] = deep ? 1 : (i === 0 ? 0 : i === 1 ? 1 : 1);
    }
  }
  const sd = new Uint8Array(sdN * sdN);
  sd.fill(156);                                // +1.76 m, far inside
  const row = (j, codes) => codes.forEach((c, i) => { sd[j * sdN + i] = c; });
  row(0, [148, 148, 156, 100]);                // +1.26 +1.26 +1.76 −1.76
  row(1, [148, 148, 156, 100]);
  row(2, [148, 148, 108, 108]);                // +1.26 +1.26 −1.26 −1.26
  row(3, [148, 148, 108, 108]);
  const b64 = (bytes) => Buffer.from(bytes).toString('base64');
  return { origin_x: 0, origin_z: 0, id_size: idN, sd_size: sdN,
           id: b64(id), sd: b64(sd) };
}
const corner = packLayerWindow(new Map([['0,0', cornerTile()]]), FMT);
const q = (code) => decodeSd(code, 128, 127 / 8);
checkEq('the fragment stands in the kitchen line\'s id texel',
  layerPairAt(corner, 1.05, 1.05), [2, 1]);
/** What a hardware LINEAR fetch would have answered: the four texels around the
 *  point, across the id texel's rim, which is exactly the reading this replaces. */
function filteredSd(win, x, z) {
  const cx = (x - win.originX) / win.sdStep - 0.5;
  const cz = (z - win.originZ) / win.sdStep - 0.5;
  const i0 = Math.floor(cx);
  const j0 = Math.floor(cz);
  const fx = cx - i0;
  const fz = cz - j0;
  const at = (i, j) => decodeSd(win.sd[j * win.sdSize + i], win.sdZero, win.sdCodesPerM);
  return (at(i0, j0) * (1 - fx) + at(i0 + 1, j0) * fx) * (1 - fz)
       + (at(i0, j0 + 1) * (1 - fx) + at(i0 + 1, j0 + 1) * fx) * fz;
}
check('red: the filtered fetch crosses zero where no boundary is',
  filteredSd(corner, 1.05, 1.05),
  (q(148) * 0.4 + q(156) * 0.6) * 0.4 + (q(148) * 0.4 + q(108) * 0.6) * 0.6, 1e-12);
check('…which is POSITIVE, i.e. the wrong side of the pair',
  filteredSd(corner, 1.05, 1.05) > 0 ? 1 : 0, 1);
check('the block reading takes only the four signed against (2, 1)',
  layerSdBlockAt(corner, 1.05, 1.05), q(108), 1e-12);
check('…so the gate keeps the floor it stands on', topLayerAt(corner, 1.05, 1.05), 1);
console.log('  — and the block EXTRAPOLATES, so a straight edge stays sub-texel sharp');
// One boundary, one pair: the four texels of an id texel sample the same plane,
// so the reconstruction is that plane — at the texel centres, between them, and
// a quarter metre past them out to the id texel's rim.
check('at the first texel centre it IS the texel', layerSdBlockAt(win, 1.25, 2),
  q(116), 1e-12);
check('…halfway between the two, exactly halfway', layerSdBlockAt(win, 1.5, 2),
  (q(116) + q(124)) / 2, 1e-12);
check('…and extrapolated to the rim of the metre, still on the plane',
  layerSdBlockAt(win, 1.0, 2), q(116) - (q(124) - q(116)) / 2, 1e-12);
checkEq('the cut of the hand tile still lands on x = 2',
  [1.99, 2.01].map((x) => (layerSdBlockAt(win, x, 2) >= 0 ? 1 : 0)), [0, 1]);

// --- [5] the GLSL -----------------------------------------------------------
console.log('\n[5] the GLSL says what a compiler and a driver need');
const glsl = terrainLayerGlsl(64);
const has = (needle) => (glsl.includes(needle) ? 1 : 0);
check('the id is an INTEGER sampler — NEAREST enforced by the format',
  has('uniform highp usampler2D uLcNearId'), 1);
check('…and read with texelFetch, never with a filtered lookup',
  has('texelFetch( uLcNearId'), 1);
check('the coarse world mask is the same kind of sampler',
  has('uniform highp usampler2D uLcFarId'), 1);
check('the distance is fetched by TEXEL — the shader interpolates, not the sampler',
  has('uniform sampler2D uLcNearSd') * has('texelFetch( uLcNearSd'), 1);
check('red: no filtered lookup of the distance anywhere',
  /texture(Lod)?\( uLcNearSd/.test(glsl) ? 1 : 0, 0);
check('…and the four it interpolates are the OWN id texel\'s',
  /vec2 t0 = idIdx \* ratio;[\s\S]*vec2 t1 = t0 \+ \( ratio - 1\.0 \);/.test(glsl)
    ? 1 : 0, 1);
check('the surfaces are one array, one slice per layer',
  has('uniform sampler2DArray uLcSurf'), 1);
check('the per-layer numbers are an array sized by the caller\'s constant',
  has('uniform vec4 uLcLayer[ 64 ];'), 1);
check('…and a smaller world compiles a smaller one',
  terrainLayerGlsl(8).includes('uniform vec4 uLcLayer[ 8 ];') ? 1 : 0, 1);
// THE ANTI-ALIASING WIDTH. `fwidth( sd )` was the pixel size in metres only
// while the sampled distance field is smooth. It is not smooth at a texel whose
// neighbour names a different boundary, nor at the rim of the loaded window —
// there the derivative explodes, the hard cut collapses to a 50/50 average of
// two grounds for that quad, and the patch of wrong material comes and goes as
// the camera turns (finding 3 of 2026-08-21). A distance field's gradient is
// one, so the honest number is the pixel measured on the WORLD position, which
// is continuous by construction.
const weightFn = glsl.slice(glsl.indexOf('float lcWeight('),
                            glsl.indexOf('vec3 lcSurface('));
check('the hard cut is one pixel of WORLD, handed in',
  /float lcWeight\( float sd, float blendM, float pixelM \)[\s\S]*clamp\( sd \/ max\( pixelM, 1e-6 \)/
    .test(weightFn) ? 1 : 0, 1);
check('red: the derivative of the SAMPLED distance is gone',
  weightFn.includes('fwidth(') ? 1 : 0, 0);
check('…and the pixel is measured on the world position, before any branch',
  /float pixelM = max\( length\( dpdx \), length\( dpdy \) \);\n\s*float w = lcWeight\( sdN, blendM, pixelM \);/
    .test(glsl) ? 1 : 0, 1);
check('…and there is no `if` in the whole function',
  weightFn.includes('if (') ? 1 : 0, 0);
check('the blend is centred on the line — half the width on each side',
  has('smoothstep( -0.5 * b, 0.5 * b, sd )'), 1);
check('the composed albedo is a mix of exactly TWO layers',
  /mix\( lcSurface\( b, p, dpdx, dpdy, wide \),\s*\n\s*lcSurface\( a, p, dpdx, dpdy, wide \), w \)/
    .test(glsl) ? 1 : 0, 1);
// THE MIP LEVEL. Every layer scales the world position by its OWN
// metres-per-tile, so the uv JUMPS at a boundary — an implicit derivative of a
// jumping uv is the coarsest mip, i.e. a blurred line along every edge in the
// world. The gradient comes from the world position instead, taken once, at
// uniform control flow, before any branch.
check('the surface array is sampled with an EXPLICIT gradient',
  has('textureGrad( uLcSurf'), 1);
check('…never with an implicit one',
  /[^d]texture\( uLcSurf/.test(glsl) ? 1 : 0, 0);
check('…and the two derivatives are taken before the branch',
  /vec2 dpdx = dFdx\( p \);\n\s*vec2 dpdy = dFdy\( p \);\n\s*uvec2 pair;/.test(glsl)
    ? 1 : 0, 1);
check('the mask itself is read at level 0 — it has no mip chain to ask for',
  has('texelFetch( uLcNearSd, clamp( t, ivec2( 0 ), ivec2( last ) ), 0 )'), 1);

// --- [6] the RED counter-probes: the ladders are GONE ------------------------
console.log('\n[6] the RED counter-probes — the three ladders are gone');
const SOURCES = [
  'client3d/src/scene/ground.ts',
  'client3d/src/scene/naturalGround.ts',
  'client3d/src/scene/naturalGroundMath.ts',
  'client3d/src/scene/undergrowth.ts',
  'client3d/src/scene/terrainLod.ts',
  'client3d/src/scene/layerGround.ts',
  'packages/scene-render/src/groundAreas.ts',
  'packages/scene-render/src/index.ts',
];
const texts = new Map();
for (const rel of SOURCES) texts.set(rel, await readFile(join(ROOT, rel), 'utf8'));

/** Where a name still appears as CODE — a mention inside a comment is history
 *  and is welcome; a line that is not a comment is the mechanism still living. */
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
for (const dead of ['AREA_RENDER_ORDER_BASE', 'AREA_POLYGON_OFFSET',
  'AREA_OFFSET_MAX', 'AREA_Y_STEP_M', 'AREA_Y_MAX_M', 'ngRefineEdgeBand',
  'NG_EDGE_BAND_M', 'NG_EDGE_ATTRIBUTE', 'aEdgeDist', 'gridPlate',
  // …and with E4 the last lift of them all, plus the drape machinery that
  // only ever served it: the cut on the height lattice and the per-area cell
  // budget that sized it.
  'WATER_DRAPE_LIFT_M', 'drapeArea', 'areaCellM',
  // …and with E5b the drape machinery itself, plus the scene relief it was
  // built for: the package files `gridMesh.ts` and `terrain.ts` are deleted
  // (§ A19 no. 6), so not one of these names may be imported any more.
  'subdivideOnGrid', 'gridStepFor', 'GRID_MAX_CELLS',
  'sampleTerrain', 'drapeGeometry', 'TERRAIN_CELLS']) {
  checkEq(`\`${dead}\` is gone from the code`, liveMentions(dead), []);
}

const groundSrc = texts.get('client3d/src/scene/ground.ts');
const build = groundSrc
  .slice(groundSrc.indexOf('async function rebuildAreas('),
         groundSrc.indexOf('function footprintSig('))
  // Comments may still NAME the ladders — that is the history the deletion is
  // owed. What must be gone is the code.
  .split('\n').filter((l) => !l.trim().startsWith('//')).join('\n');
check('the area builder sets no renderOrder at all',
  build.includes('renderOrder') ? 1 : 0, 0);
check('…and no polygonOffset',
  build.includes('polygonOffset') ? 1 : 0, 0);
const lifts = build.match(/\.position\.y = [^\n;]+;/g) ?? [];
checkEq('…and no height at all any more: the mirror stands at its own level',
  lifts, []);
check('only WATER still gets a mesh at all — and the PROFILE is what says so',
  /const profile = waterProfileOf\(area\.meta\);/.test(build) ? 1 : 0, 1);
// ONE MIRROR BUILDER, and since W1 exactly ONE feeder: the painted areas. The
// room water that used to feed it a second time is deleted with its bake stage
// (W1 § 6), which is what makes "one water source" a countable claim.
check('the mirror builder exists exactly once',
  (build.match(/const addMirror = \(/g) ?? []).length, 1);
check('…the painted area feeds it',
  /addMirror\(built\.geometry, area\.kind, profile\);/.test(build) ? 1 : 0, 1);
check('RED: and nothing else does — the zone-water loop is gone',
  /zoneWater/.test(build) ? 1 : 0, 0);
check('…with exactly one buildWaterPlane call in the whole builder',
  (build.match(/buildWaterPlane\(/g) ?? []).length, 1);

console.log('\n[7] the wiring, pinned by reading the source');
check('the terrain material carries no map — or the anti-tile would blend the '
  + 'DEFAULT kind over every forest',
  /surfaceMaterial\(THREE, \{ material: null, map: null,\n\s*color: 0xffffff \}\);/
    .test(groundSrc) ? 1 : 0, 1);
// THE ORDER IS THE POINT. Every ground patch inserts its body directly after
// `#include <map_fragment>`, so the one applied LAST runs FIRST — which is why
// the compositor is applied after the natural stages: it writes the albedo, they
// work on what it wrote (plan § G3, "the LAST chain link").
check('the compositor is applied AFTER applyNaturalGround, so it runs BEFORE it',
  /applyNaturalGround\(mat\);[\s\S]{0,600}?applyTerrainLayers\(mat\);/.test(groundSrc)
    ? 1 : 0, 1);
check('the undergrowth is handed the mask reading, not a second polygon walk',
  /createUndergrowthField\(\{\n\s*heightAt, applySway, topLayerAt: topLayerIndexAt \}\)/
    .test(groundSrc) ? 1 : 0, 1);
const ugSrc = texts.get('client3d/src/scene/undergrowth.ts');
check('…and really gates on it, beside the ring and not instead of it',
  /pointInRing\(p\.x, p\.z, area\.ring\)\s*\n\s*&& opts\.topLayerAt\(p\.x, p\.z\) === area\.layer/
    .test(ugSrc) ? 1 : 0, 1);
check('the masks are fetched on the terrain signature, with the areas',
  /await reloadLayers\(loadedSig\);/.test(groundSrc) ? 1 : 0, 1);
check('…and their window follows the height tiles\' own want set',
  /wantedTiles\(layerIndexKeys, tileM, anchorX, anchorZ,\n\s*HEIGHT_TILE_RADIUS_M\)/
    .test(groundSrc) ? 1 : 0, 1);

console.log('\n[7b] a water layer wears its BED — and the server says which');
const layerSrc = texts.get('client3d/src/scene/layerGround.ts');
check('RED: the bare-ground substitution is gone from the compositor',
  /layer\.water \? bare : layer/.test(layerSrc) ? 1 : 0, 0);
check('…and with it the `bare` binding it needed',
  /const bare = layers\[0\];/.test(layerSrc) ? 1 : 0, 0);
check('the slice is drawn from the row\'s OWN surface, water or not',
  /const lib = surfaceFor\(layer\.surface, 'wall'\);/.test(layerSrc) ? 1 : 0, 1);
check('…and the colour fallback and the tile size ask the BED kind',
  /const kind = layer\.bed_kind \|\| layer\.kind;/.test(layerSrc) ? 1 : 0, 1);
check('the flat colour really uses it',
  /colorOf\(kind\) \|\| '#888888'/.test(layerSrc) ? 1 : 0, 1);
check('…and so does the metres-per-tile',
  /sizeOf \? sizeOf\(kind\) : \(lib\?\.sizeM \?\? 3\)/.test(layerSrc) ? 1 : 0, 1);
// Two beds must be two keys, or the slice array is never rebuilt for the
// second world (see the docstring's counting argument).
check('the layer key carries the bed, so two beds are two states',
  /\$\{l\.edge_blend_m\}:\$\{l\.water \? 1 : 0\}:\$\{l\.bed_kind \?\? ''\}/
    .test(groundSrc) ? 1 : 0, 1);
// …and the payload type says the field exists, on water rows only.
const cutSrc = await readFile(
  join(ROOT, 'packages/scene-render/src/layerCut.ts'), 'utf8');
check('`bed_kind` is an optional field of the layer row',
  /bed_kind\?: string/.test(cutSrc) ? 1 : 0, 1);
check('RED: and the index has no `waters` list left to draw from',
  /waters: TerrainLayerWater\[\]/.test(cutSrc) ? 1 : 0, 0);

console.log(`\n${passed} ok, ${failed} failed`);
process.exit(failed ? 1 : 0);
