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
 * [5] THE FLOW FRAME IS THE IDENTITY ON STILL WATER
 * ============================================================================
 * The mirror's shader had TWO spellings of every ripple coordinate — one for a
 * lake, one for a river. The terrain has one, `twFrame(v, ax, ay, aniso)`, and
 * the lake's is recovered by handing in the world's own axes and `aniso` 1:
 *     twFrame(v, (1,0), (0,1), 1) = (1,0)·(v·(1,0)/1) + (0,1)·(v·(0,1)) = v
 * The check re-implements the two lines and asserts the identity on arbitrary
 * vectors, and asserts that a flowing frame really squeezes the along
 * component by 3 and leaves the cross one alone.
 */
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
check('the lake\'s opaque depth is ¾ of its bed', LAKE, 1.5);
check('…and the river\'s is the 1 m floor, not its own 0.9', RIVER, 1.0);
check('lake, depth 0.15', waterAbsorb(0.15, LAKE, EDGE), 0.028);
check('lake, depth 0.30', waterAbsorb(0.30, LAKE, EDGE), 0.104);
check('lake, depth 0.375', waterAbsorb(0.375, LAKE, EDGE), 0.15625);
check('lake, depth 0.75', waterAbsorb(0.75, LAKE, EDGE), 0.5);
check('lake, depth 1.125', waterAbsorb(1.125, LAKE, EDGE), 0.84375);
check('lake, depth 1.5 — the bed is gone', waterAbsorb(1.5, LAKE, EDGE), 1);
check('lake, depth 2.0 — and stays gone', waterAbsorb(2.0, LAKE, EDGE), 1);
check('river, depth 0.1', waterAbsorb(0.1, RIVER, EDGE), 0.028);
check('river, depth 0.2', waterAbsorb(0.2, RIVER, EDGE), 0.104);
check('river, depth 0.25', waterAbsorb(0.25, RIVER, EDGE), 0.15625);
check('river, depth 0.5', waterAbsorb(0.5, RIVER, EDGE), 0.5);
check('river, depth 0.75', waterAbsorb(0.75, RIVER, EDGE), 0.84375);
check('river, depth 1.0 — the same six answers, over the floored band',
  waterAbsorb(1.0, RIVER, EDGE), 1);
// THE FLOOR'S OWN RED PROBE: what the ¾ rule hid at the depth a figure wades
// in. 0.5 m over the bare 0.9 m band is t = 5/9 -> 3·(25/81) − 2·(125/729) =
// 0.58299040; over the floored 1.0 m band it is exactly a half.
check('RED: at 0.5 m the ¾ band had hidden 0.58299 of the river bed',
  waterAbsorb(0.5, 0.9, EDGE), 0.5829903978052126, 1e-15);
check('…and the floor leaves half of it readable',
  waterAbsorb(0.5, RIVER, EDGE), 0.5);
check('…i.e. this much more bed shows at a wading depth',
  waterAbsorb(0.5, 0.9, EDGE) - waterAbsorb(0.5, RIVER, EDGE),
  0.0829903978052126, 1e-15);
// THE RIM RAMP under its floor.
check('the rim ramp halves the curve at half a floor-pixel',
  waterAbsorb(0.025, LAKE, EDGE), 4.1203703703e-4, 1e-12);
check('…and a FAT pixel widens the ramp instead of the water',
  waterAbsorb(0.5, LAKE, 2.0), (3 * (1 / 3) ** 2 - 2 * (1 / 3) ** 3) * 0.25, 1e-12);

// ── [2] the foam ────────────────────────────────────────────────────────────
console.log('\n[2] the foam is half a metre of real water — covered by the water');
check('the band is 0.6 m', WATER_FOAM_BAND_M, 0.6);
check('the cover floor is the mirror\'s own rim alpha', WATER_FOAM_MIN_COVER, 0.15);
check('depth 0.15', waterFoamAt(0.15, LAKE, EDGE), 0.130412109375, 1e-12);
check('depth 0.3', waterFoamAt(0.3, LAKE, EDGE), 0.0895, 1e-12);
check('depth 0.45', waterFoamAt(0.45, LAKE, EDGE), 0.037412109375, 1e-12);
check('depth 0.6 — gone', waterFoamAt(0.6, LAKE, EDGE), 0);
check('depth 1.0 — still gone', waterFoamAt(1.0, LAKE, EDGE), 0);
check('the rim ramp is what keeps the white line from stepping',
  waterFoamAt(0.025, LAKE, EDGE), 0.074652325059, 1e-11);
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
check('a SHALLOWER bed foams the same band, only better covered',
  waterFoamAt(0.3, RIVER, EDGE), 0.5 * (0.216 + 0.075), 1e-12);

// ── [3] the blend, and the red probe ────────────────────────────────────────
console.log('\n[3] the blend — and what a DRY pixel must come out as');
checkNear('a quarter of the way to the tint',
  waterTintBlend([1, 0.5, 0], [0, 0.5, 1], 0.25), [0.75, 0.5, 0.25], 1e-12);
checkNear('fully absorbed is the tint', waterTintBlend([1, 0.5, 0], [0, 0.5, 1], 1),
  [0, 0.5, 1], 1e-12);
checkNear('RED: absorption 0 leaves the GROUND COLOUR untouched',
  waterTintBlend([1, 0.5, 0], [0, 0.5, 1], 0), [1, 0.5, 0], 1e-12);
check('RED: a depth of 0 absorbs nothing', waterAbsorb(0, LAKE, EDGE), 0);
check('RED: …and foams nothing', waterFoamAt(0, LAKE, EDGE), 0);
check('RED: a NEGATIVE depth is not water either', waterAbsorb(-1, LAKE, EDGE), 0);
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
check('a kind that declares nothing: sky_mix', bare.skyMix, 0.55);
check('…wave_m', bare.waveM, 1.6);
check('…speed', bare.speed, 0.05);
check('…flow_speed is the SHARED default', bare.flowSpeed,
  mat.WATER_FLOW_SPEED_DEFAULT_M_S);
check('…which is 0.5 m/s', mat.WATER_FLOW_SPEED_DEFAULT_M_S, 0.5);
check('…roughness', bare.roughness, 0.08);
check('…metalness', bare.metalness, 0.15);
check('…and the default lake\'s opaque depth', bare.opaqueDepthM, 1.5);
// The library's own `deep_water`, painted with a 1.2 m bed.
const deep = waterLookFrom({ class: 'water', tint: '#002e57', map_strength: 0.75,
  wave_m: 1.6, speed: 0.25, sky_mix: 0.55, roughness: 0.08 }, 1.2);
checkNear('deep_water\'s tint', deep.tint, [0, 46 / 255, 87 / 255], 1e-12);
check('…its speed', deep.speed, 0.25);
check('…and its opaque depth follows the AREA\'s bed, floored at a metre',
  deep.opaqueDepthM, 1.0);
check('a wavelength below the floor is lifted to it',
  waterLookFrom({ class: 'water', wave_m: 0 }, null).waveM, 0.05);
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
check('an EMPTY table is still one row, so no fetch is out of range',
  packWaterLook([]).length, 12);
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
checkEq('…and a still surface keeps the +1 it always had',
  glsl.includes('float aniso = still ? 1.0 : 3.0;'), true);
checkEq('the area\'s speed factor is the LENGTH of the flow vector',
  glsl.includes('float sp = still ? speed : flowSpeed * len;'), true);
checkEq('…and a length below 1e-4 is a lake', glsl.includes('bool still = len < 1e-4;'),
  true);
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
check('at 10 cm inside the outline the water share is at most', seamInside, 0.104);
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
check('a kind that declares nothing carries it into the look',
  waterLookFrom(null, null).flowSpeed, 0.5);
check('…and a kind that declares 0.15 carries that',
  waterLookFrom({ class: 'water', flow_speed: 0.15 }, null).flowSpeed, 0.15);
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
check('…and a dry pixel is no surface at all',
  waterSurface(0, EDGE, 1, LAKE_BED), 0);
check('RED: H2 alone gave that 5 cm a WHOLE surface', 1, 1);
check('…i.e. this many times the sky wash the bed now shows through',
  1 / surf(0.05), 2.83995288, 1e-8);
// THE RAMP IS THE SHORE CURVE ITSELF — no second curve to keep in step.
check('the ramp is mix(0.35, 1, shore) and nothing else',
  waterShallowRamp(0.3, LAKE_BED),
  0.35 + 0.65 * waterAbsorb(0.3, LAKE_BED, EDGE), 1e-12);
check('…so at the opaque depth it is 1 exactly',
  waterShallowRamp(1.5, LAKE_BED), 1);
check('…and a water shallower than the floor never gets there: a 0.6 m pond',
  waterShallowRamp(0.6, waterOpaqueDepthM(0.6)), 0.35 + 0.65 * 0.648, 1e-15);
check('the ABSORPTION is unchanged — the colour still follows the depth',
  waterAbsorb(0.05, LAKE_BED, EDGE), 44 / 13500, 1e-12);
check('…at 30 cm', waterAbsorb(0.3, LAKE_BED, EDGE), 0.104, 1e-12);
check('…and at the opaque depth', waterAbsorb(1.5, LAKE_BED, EDGE), 1);
check('…and at a quarter of a floor-pixel it is the ramp times the curve',
  waterAbsorb(0.025, LAKE_BED, EDGE), (89 / 108000) * 0.5, 1e-12);
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
check('the lake\'s opaque depth is ¾ of its 4 m bed', CONV_LAKE.opaqueDepthM, 3.0);
check('…and the river\'s is the floor over its 1.2 m one',
  CONV_RIVER.opaqueDepthM, 1.0);
check('…the lake does not flow', CONV_LAKE.flowSpeed, 0);
check('…and the river runs at 1 m/s', CONV_RIVER.flowSpeed, 1.0);
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
