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
 * ¾ of the water's own bed depth (W4b, `waterOpaqueDepthM`): 1.5 m for the
 * default lake (2.0 m), 0.9 m for the seeded river (1.2 m).
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
 * …and the river answers the SAME six numbers at 0.6 times the depth (0.09,
 * 0.18, 0.225, 0.45, 0.675, 0.9), which is the whole of W4b: the fraction is
 * the law, the metres are the water's.
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
 *     sky_mix 0.55 · wave_m 1.6 · speed 0.05 · flow_speed 0.15 (the shared
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
  packWaterLook, terrainWaterFragmentGlsl, WATER_FOAM_MIN_COVER,
  WATER_LOOK_DEFAULT, WATER_LOOK_TEXELS } = shade;
const { WATER_EDGE_FADE_M, WATER_FOAM_BAND_M, WATER_FOAM_STRENGTH,
  waterOpaqueDepthM } = plane;

// ── [1] the absorption ──────────────────────────────────────────────────────
console.log('[1] the absorption is the mirror\'s own shore curve (W4b)');
const EDGE = WATER_EDGE_FADE_M;          // 0.05 m — the floor, i.e. rim ramp 1
const LAKE = waterOpaqueDepthM(2.0);     // 1.5 m
const RIVER = waterOpaqueDepthM(1.2);    // 0.9 m
check('the lake\'s opaque depth is ¾ of its bed', LAKE, 1.5);
check('…and the river\'s', RIVER, 0.9);
check('lake, depth 0.15', waterAbsorb(0.15, LAKE, EDGE), 0.028);
check('lake, depth 0.30', waterAbsorb(0.30, LAKE, EDGE), 0.104);
check('lake, depth 0.375', waterAbsorb(0.375, LAKE, EDGE), 0.15625);
check('lake, depth 0.75', waterAbsorb(0.75, LAKE, EDGE), 0.5);
check('lake, depth 1.125', waterAbsorb(1.125, LAKE, EDGE), 0.84375);
check('lake, depth 1.5 — the bed is gone', waterAbsorb(1.5, LAKE, EDGE), 1);
check('lake, depth 2.0 — and stays gone', waterAbsorb(2.0, LAKE, EDGE), 1);
check('river, depth 0.09', waterAbsorb(0.09, RIVER, EDGE), 0.028);
check('river, depth 0.18', waterAbsorb(0.18, RIVER, EDGE), 0.104);
check('river, depth 0.225', waterAbsorb(0.225, RIVER, EDGE), 0.15625);
check('river, depth 0.45', waterAbsorb(0.45, RIVER, EDGE), 0.5);
check('river, depth 0.675', waterAbsorb(0.675, RIVER, EDGE), 0.84375);
check('river, depth 0.9 — the same six answers, 0.6 as deep',
  waterAbsorb(0.9, RIVER, EDGE), 1);
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
// The river's band is 0.9 m, so at 0.3 m the shore curve stands at
// t = 1/3 -> 3/9 − 2/27 = 7/27, and the cover is 7/27 + 0.5·0.15.
check('a SHALLOWER bed foams the same band, only better covered',
  waterFoamAt(0.3, RIVER, EDGE), 0.5 * (7 / 27 + 0.075), 1e-12);

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
check('…which is 0.15 m/s', mat.WATER_FLOW_SPEED_DEFAULT_M_S, 0.15);
check('…roughness', bare.roughness, 0.08);
check('…metalness', bare.metalness, 0.15);
check('…and the default lake\'s opaque depth', bare.opaqueDepthM, 1.5);
// The library's own `deep_water`, painted with a 1.2 m bed.
const deep = waterLookFrom({ class: 'water', tint: '#002e57', map_strength: 0.75,
  wave_m: 1.6, speed: 0.25, sky_mix: 0.55, roughness: 0.08 }, 1.2);
checkNear('deep_water\'s tint', deep.tint, [0, 46 / 255, 87 / 255], 1e-12);
check('…its speed', deep.speed, 0.25);
check('…and its opaque depth follows the AREA\'s bed', deep.opaqueDepthM, 0.9);
check('a wavelength below the floor is lifted to it',
  waterLookFrom({ class: 'water', wave_m: 0 }, null).waveM, 0.05);
// The packing — the layout `tlodWaterSurface` fetches its three texels from.
check('three RGBA texels per look', WATER_LOOK_TEXELS, 3);
const packed = packWaterLook([bare, deep]);
check('two looks are 2 · 3 · 4 floats', packed.length, 24);
checkNear('row 0, texel 0 — tint and sky_mix',
  [...packed.slice(0, 4)], [...bare.tint, 0.55], 1e-7);
checkNear('row 0, texel 1 — wave, speed, flow, opaque depth',
  [...packed.slice(4, 8)], [1.6, 0.05, 0.15, 1.5], 1e-7);
checkNear('row 0, texel 2 — roughness, metalness, the water flag, one spare',
  [...packed.slice(8, 12)], [0.08, 0.15, 1, 0], 1e-7);
checkNear('…and a STAND-IN row says it is not water',
  [...packWaterLook([{ ...bare, isWater: false }]).slice(8, 12)],
  [0.08, 0.15, 0, 0], 1e-7);
checkNear('row 1 is the SECOND water and no blend of the two',
  [...packed.slice(12, 16)], [...deep.tint, 0.55], 1e-7);
check('…with its own opaque depth', packed[19], 0.9, 1e-7);
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
checkEq('…and the roughness and metalness ride the same factor',
  glsl.includes('roughnessFactor = mix( roughnessFactor, look2.x, twA );')
  && glsl.includes('metalnessFactor = mix( metalnessFactor, look2.y, twA );'), true);
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
// The mask names a PAIR and not a layer, and the pixel is known to be water.
checkEq('the water half of the mask\'s pair is picked by the is_water flag',
  glsl.includes('texelFetch( uTlodWaterLook, ivec2( 2, a ), 0 ).z > 0.5 ? a : b;'), true);
checkEq('RED: and the signed distance is never read — it cannot say more',
  /uLcNearSd|lcSdAt|uTlodWaterSd/.test(glsl), false);
// The one place K-A gives GPU work back.
checkEq('a FULLY absorbed pixel does not read the bed\'s normal at all',
  /if \( twA >= 1\.0 \) return wn;/.test(glsl), true);
checkEq('…and a dry one reads only the bed\'s',
  glsl.includes('if ( twA <= 0.0 ) {'), true);

console.log(`\n${passed + failed} checks, ${failed} failures`);
process.exit(failed ? 1 : 0);
