#!/usr/bin/env node
/**
 * Smoke check for the NATURAL GROUND — the three-stage shader patch that makes
 * the open world's ground stop looking like wallpaper, and the arithmetic that
 * steers it (§ B5a: strings and numbers, never screenshots).
 *
 * Usage:  node client3d/scripts/smoke_natural_ground.mjs
 *         (bundles the client's naturalGround + ground modules; needs three)
 *
 * ===========================================================================
 * WHAT IS UNDER TEST
 * ===========================================================================
 * `client3d/src/scene/naturalGround.ts` patches every OPEN-WORLD ground
 * material (the base plate and the painted area drapes of `scene/ground.ts`)
 * with three stages:
 *   (1) ANTI-TILE   the ground texture sampled a second time at 0.23× the
 *                   scale, shifted half a UV, blended by value noise over
 *                   world metres — one image, two periods, no visible repeat.
 *   (2) COLOUR      brightness and saturation modulated by ±8 % over a ~25 m
 *                   noise. Never hue. The ONE stage a single-coloured kind
 *                   gets as well, which is why it stands outside `USE_MAP`.
 *   (3) HEIGHT AO   four taps in a 3 m ring out of the world's own heightfield
 *                   against the fragment's own height: lower than its
 *                   surroundings darkens by up to 12 %, higher brightens by up
 *                   to 6 %.
 * The amplitudes live in `naturalGroundMath.ts` and the GLSL is PRINTED out of
 * them, so a hand check on the function and a string check on the composed
 * shader measure one number rather than two copies of it.
 *
 * Four things can silently break, and all four are checked here without a GPU:
 *  - the patch is the SECOND writer of `onBeforeCompile` on every ground
 *    material (`patchHole` is already in the slot). An ASSIGNMENT would throw
 *    the basement hole away — the rule this repo learned the hard way with the
 *    water shader (`smoke_surface_patch.mjs`), measured by the mutant of [8a].
 *  - WATER must not get it. A painted lake carries a full shader of its own
 *    (scrolling normals, sky fresnel, roughness mask); a second sample of its
 *    texture blended in and a relief shading on top would fight every part of
 *    it. Section [6] counts the anchors on a real water material.
 *  - a FLAT world must be EXACTLY neutral, not almost. The switch is the
 *    shared `uNgStrength` uniform at 0 plus the shader's own guard — the same
 *    shape the view corridor uses for an unembodied client.
 *  - the AO SIGN. Turned around, the ditches light up and the ridges go grey;
 *    it looks deliberate and it is the exact opposite of ground. Two mutants
 *    in [8b]/[8c], one on the pure function and one on the emitted GLSL.
 *
 * The patches are handed a STUB SHADER whose vertex/fragment strings carry the
 * real `#include` anchors of three's `meshphysical` shader, and the resulting
 * strings are read.
 *
 * THE ANCHORS (both `#include` LINES, because `onBeforeCompile` sees the shader
 * BEFORE three resolves its includes):
 *   vertex   `#include <project_vertex>`   the fragment's world position
 *   fragment `#include <map_fragment>`     where the texture lands in
 *                                          `diffuseColor` — everything the
 *                                          patch does modifies what is already
 *                                          there, so it goes AFTER it
 *
 * ---------------------------------------------------------------------------
 * [1] THE PATCH ALONE — every line, the four uniforms, the key
 * ---------------------------------------------------------------------------
 * The three stages in the composed fragment shader, the world position in the
 * vertex shader, the anti-tile stage inside `#ifdef USE_MAP` (a single-coloured
 * kind has no repeat to break) and the AO inside `if ( uNgStrength > 0.0 )`.
 * The key is the constant `natural-ground`: every number is either a GLSL
 * literal or a shared uniform, so all ground materials of a world compile to
 * ONE program.
 *
 * ---------------------------------------------------------------------------
 * [2] THE CHAIN — basement hole and natural ground on ONE material
 * ---------------------------------------------------------------------------
 * That is the real composition of `materialFor`. Every hole line AND every
 * natural-ground line must be in the composed shader, both uniform families
 * bound, and the key must be `ground-hole+natural-ground` — the two in the
 * order they were applied. Patching twice is still one patch (the WeakSet), or
 * the shader would declare `vNgWorld` and `ngNoise` twice and not compile.
 *
 * ---------------------------------------------------------------------------
 * [3] THE SHARED UNIFORMS — one upload reaches every ground material
 * ---------------------------------------------------------------------------
 * The `surfaceTimeUniform` pattern: two materials hand the SAME four objects
 * into their shaders, and one call to `setNaturalGroundField` shows up in both.
 * Without it a world with two hundred painted areas would hold two hundred
 * copies of the height texture.
 *
 * ---------------------------------------------------------------------------
 * [4] THE HEIGHT TEXTURE — what `setNaturalGroundField` uploads
 * ---------------------------------------------------------------------------
 * A 3×3 field of a single 4 m hill, and the four numbers the shader addresses
 * it with: R16F, linearly filtered, clamped at the edge, `uNgField` =
 * (origin_x, origin_z, step, 0), `uNgFieldSize` = (cols, rows). Half float
 * rather than full because WebGL2 filters R16F in core; the round trip of 4.0
 * and 22.5 must come back exact, which pins the packing.
 * NEUTRALITY, three ways, all of them the same promise: a world nobody has
 * shaped (every support point at the same height), a field that never arrived
 * (`null`), and a field too small to have an interior all answer strength 0 —
 * and the shader's guard then reads nothing at all.
 *
 * ---------------------------------------------------------------------------
 * [5] THE ARITHMETIC — `naturalGroundMath`, by hand
 * ---------------------------------------------------------------------------
 * With span 2 m, down 12 % and up 6 %:
 *   surroundings level with the fragment      ->  0        (flat is neutral)
 *   surroundings 1 m higher   -> t = 0.5      -> -0.06     (a shallow hollow)
 *   surroundings 2 m higher   -> t = 1        -> -0.12     (fully spent)
 *   surroundings 8 m higher   -> t clamped 1  -> -0.12     (a valley is not
 *                                                           four hollows)
 *   surroundings 1 m lower    -> t = -0.5     -> +0.03
 *   surroundings 2 m lower    -> t = -1       -> +0.06     (half the darkening)
 * The field UV is on TEXEL CENTRES: support point i lies at the centre of texel
 * i, so its coordinate is (i + 0.5)/cols. For a 21×21 field at origin (−100,
 * −100) and 10 m step: x = −100 -> 0.5/21, x = +100 -> 20.5/21, x = −105 -> 0
 * (the outer edge, still inside), x = −110 -> outside and therefore neutral.
 * Getting that half wrong shifts the whole shading by half a support cell.
 * The colour factors: noise 1 -> 1.08, noise 0 -> 0.92, noise 0.5 -> 1 exactly.
 * The second UV: (1, 1) -> (0.73, 0.73), (0, 0) -> (0.5, 0.5).
 *
 * ---------------------------------------------------------------------------
 * [6] WATER KEEPS ITS OWN SHADER — the anchor count
 * ---------------------------------------------------------------------------
 * A real water material out of `@anima/scene-render` `surfaceMaterial`, put
 * through the very decision `materialFor` makes (`isWaterClass`): the hole is
 * patched, the natural ground is NOT, and every water line survives. The same
 * decision on a matte material patches it. Counted on the composed shader,
 * because "we did not call it" is a claim about the code and "there is not one
 * `ngNoise` in the water's shader" is a claim about the picture.
 *
 * ---------------------------------------------------------------------------
 * [7] THE WIRING, pinned by reading the source
 * ---------------------------------------------------------------------------
 * A patch is worth nothing where nobody applies it. `materialFor` is a closure
 * over fetched payloads and cannot be called from here, so its three lines are
 * pinned against the source text: the hole first, the natural ground guarded
 * by the water class, the field handed over in `reloadHeight` and given back
 * in `dispose`. And nowhere else: the admin preview and the shared package must
 * not import any of this (view polish is not geometry, § B2).
 *
 * ---------------------------------------------------------------------------
 * [8] THE RED COUNTER-CHECKS — four mutants, four losses
 * ---------------------------------------------------------------------------
 * (a) ASSIGNMENT INSTEAD OF CHAIN. The bundle is rebuilt with the line that
 *     calls the previous callback deleted. Fed a material that already carries
 *     the basement hole, the mutant's shader contains NOT ONE hole line while
 *     every natural-ground line is still there — so the probe measures the loss
 *     of the chain, not a broken module.
 * (b) THE AO SIGN, in the pure function: `-down·t` becomes `+down·t`, and the
 *     hollow that the truth darkens comes out BRIGHTER.
 * (c) THE AO SIGN, in the emitted GLSL: both minus signs of the shade line are
 *     dropped. The mutant's shader loses the line the truth carries — which is
 *     what makes the string check in [1] a check on the sign rather than on the
 *     presence of a substring.
 * (d) THE FLAT WORLD. The neutrality test drops out of `setNaturalGroundField`,
 *     so a world nobody has shaped is shaded against its own zero — the mutant
 *     answers strength 1 for the very field the truth answers 0 for.
 */
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');
const NG_SRC = join(ROOT, 'client3d/src/scene/naturalGround.ts');
const MATH_SRC = join(ROOT, 'client3d/src/scene/naturalGroundMath.ts');
const GROUND_SRC = join(ROOT, 'client3d/src/scene/ground.ts');
const PREVIEW_SRC = join(ROOT, 'frontend/src/tabs/world/FloorPlanPreview.tsx');

// ── The canvas the shared module draws its wave normal map on ──────────────
// Section [6] builds a REAL water material, and `@anima/scene-render`
// generates its wave normal map procedurally (no asset, no download) — that is
// the only DOM it touches. A buffer of zeros is enough: nothing here reads a
// pixel, the checks read STRINGS. Copied from `smoke_surface_patch.mjs`, which
// is where that generator is the subject.
globalThis.document = {
  createElement() {
    return {
      width: 0,
      height: 0,
      getContext() {
        return {
          fillStyle: '',
          fillRect() {},
          createImageData(w, h) { return { data: new Uint8ClampedArray(w * h * 4) }; },
          putImageData() {},
        };
      },
    };
  },
};

/**
 * Bundle the client's natural-ground module TOGETHER with the ground module
 * and the shared surface materials, and import the three as one.
 *
 * One bundle on purpose: the chain of section [2] needs the very `patchHole`
 * that runs in the app and section [6] the very `surfaceMaterial` a painted
 * lake is built from. `external: ['three']` keeps node's own three the only one
 * in play (the trick of `smoke_surface_patch.mjs`); `ground.ts` reaches the DOM
 * and the network only inside functions, so it loads here.
 *
 * `mutate` rewrites the BUILT text before the import — that is how sections
 * [8a], [8c] and [8d] get their mutants without a second copy of the patch
 * lying around to rot.
 */
async function loadClient(mutate) {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(ROOT, 'client3d/scripts/.smoke-'));
  try {
    const entry = 'export { applyNaturalGround, setNaturalGroundField, NG_CACHE_KEY,\n'
      + '  ngHeightTex, ngField, ngFieldSize, ngStrength }\n'
      + `  from '${NG_SRC}';\n`
      + `export { patchHole, HOLE_CACHE_KEY } from '${GROUND_SRC}';\n`
      + `export { isWaterClass } from '${MATH_SRC}';\n`
      + "export { surfaceMaterial } from '@anima/scene-render';\n";
    const built = await esbuild.build({
      stdin: { contents: entry, resolveDir: dir, loader: 'ts' },
      bundle: true, platform: 'node', format: 'esm', write: false,
      outfile: join(dir, 'naturalGround.mjs'), external: ['three', 'three/*'],
    });
    const text = built.outputFiles[0].text;
    const source = mutate ? mutate(text) : text;
    if (mutate && source === text) {
      throw new Error('the mutant changed nothing — the counter-check would be vacuous');
    }
    const file = join(dir, 'naturalGround.mjs');
    await writeFile(file, source, 'utf8');
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

/** The math module has no runtime import (see its header), so a plain
 *  transpile loads it — the rule of `smoke_scatter_math.mjs`. Should someone
 *  add one, this fails loudly, and that is the alarm. */
async function loadMath(mutate) {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'naturalground-'));
  try {
    const original = await readFile(MATH_SRC, 'utf8');
    const source = mutate ? mutate(original) : original;
    if (mutate && source === original) {
      throw new Error('the mutant changed nothing — the counter-check would be vacuous');
    }
    const out = esbuild.transformSync(source, { loader: 'ts', format: 'esm' });
    const file = join(dir, 'module.mjs');
    await writeFile(file, out.code, 'utf8');
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

/** Section [8a]'s mutant: `applyNaturalGround` ASSIGNS instead of chaining, so
 *  the predecessor in the slot is never called. Anchored on this patch's own
 *  first uniform — there are several chained patches in this bundle and a bare
 *  `prev.call(…)` would hit whichever esbuild printed first. */
function assignInsteadOfChain(text) {
  const chained = /prev\.call\(mat, shader, renderer\);(\s*)shader\.uniforms\.uNgHeight =/;
  if (!chained.test(text)) throw new Error('the natural-ground patch no longer chains here');
  return text.replace(chained, 'shader.uniforms.uNgHeight =');
}

/** Section [8b]'s mutant, on the MATHS: the hollow is lit instead of shaded. */
function flipShadeSign(source) {
  const line = 'return t > 0 ? -NG_AO_DOWN * t : -NG_AO_UP * t;';
  if (!source.includes(line)) throw new Error('the AO shade is no longer where the probe looks');
  return source.replace(line, 'return t > 0 ? NG_AO_DOWN * t : NG_AO_UP * t;');
}

/** Section [8c]'s mutant, on the emitted GLSL: the same flip, one layer down.
 *  It has to survive esbuild's printing of the template literal, so both
 *  halves are replaced by their own text rather than by a line match. */
function flipShadeSignGlsl(text) {
  const down = 'ngShade = ngT > 0.0 ? -';
  const up = ' * ngT : -';
  if (!text.includes(down) || !text.includes(up)) {
    throw new Error('the emitted shade line is no longer where the probe looks');
  }
  return text.replace(down, 'ngShade = ngT > 0.0 ? ').replace(up, ' * ngT : ');
}

/** Section [8d]'s mutant: the flat-world test drops out, so a world nobody has
 *  shaped uploads a texture of zeroes and shades itself against it. */
function shadeTheFlatWorld(text) {
  const test = 'if (!(max > min)) {';
  if (!text.includes(test)) throw new Error('the flat-world test is no longer where the probe looks');
  return text.replace(test, 'if (false) {');
}

/** The stub shader: three's own anchor lines, in three's own order, and
 *  nothing else. What the patches do to these strings is the whole subject. */
function stubShader() {
  return {
    uniforms: {},
    vertexShader: [
      'void main() {',
      '\t#include <begin_vertex>',
      '\t#include <project_vertex>',
      '}',
    ].join('\n'),
    fragmentShader: [
      'void main() {',
      '\t#include <clipping_planes_fragment>',
      '\t#include <map_fragment>',
      '\t#include <normal_fragment_maps>',
      '\t#include <roughnessmap_fragment>',
      '\t#include <opaque_fragment>',
      '}',
    ].join('\n'),
  };
}

/** The lines the natural-ground patch writes — ONE list, used for "present" in
 *  [1]/[2] and for "absent" in [6], so the two sides cannot drift. Every entry
 *  is a decision somebody could undo by accident. */
const NG_MARKS = [
  ['vert', 'varying vec2 vNgWorld;'],
  ['vert', 'vNgWorld = ( modelMatrix * vec4( transformed, 1.0 ) ).xz;'],
  ['frag', 'uniform sampler2D uNgHeight;'],
  ['frag', 'uniform float uNgStrength;'],
  ['frag', 'varying vec2 vNgWorld;'],
  // the value noise, over WORLD metres and out of a hash — no second image
  ['frag', 'return fract( sin( dot( p, vec2( 12.9898, 78.233 ) ) ) * 43758.5453 );'],
  // (1) the second sample: 0.23x the scale, half a UV across, blended at most
  //     half way — the base sample stays the ground the world was authored with
  ['frag', '#ifdef USE_MAP'],
  ['frag', 'float ngMix = ngNoise( vNgWorld / 7.00 ) * 0.50;'],
  ['frag', 'vec4 ngWide = texture2D( map, vMapUv * 0.23 + 0.50 );'],
  ['frag', 'diffuseColor.rgb = mix( diffuseColor.rgb, ngWide.rgb * diffuse, ngMix );'],
  // (2) brightness and saturation, +-8 % over 25 m, and never hue
  ['frag', 'float ngTint = ngNoise( vNgWorld / 25.00 ) * 2.0 - 1.0;'],
  ['frag', 'float ngSat = ngNoise( vNgWorld / 25.00 + vec2( 37.0, 11.0 ) ) * 2.0 - 1.0;'],
  ['frag', 'diffuseColor.rgb *= 1.0 + 0.08 * ngTint;'],
  ['frag', 'float ngLum = dot( diffuseColor.rgb, vec3( 0.2126, 0.7152, 0.0722 ) );'],
  ['frag', 'diffuseColor.rgb = mix( vec3( ngLum ), diffuseColor.rgb, 1.0 + 0.08 * ngSat );'],
  // (3) the four taps of the 3 m ring, the span, and THE SIGN
  ['frag', 'if ( uNgStrength > 0.0 ) {'],
  ['frag', 'vec2 ngRing = vec2( 3.00 );'],
  ['frag', 'float ngOwn = ngHeightAt( vNgWorld );'],
  ['frag', 'float ngAround = 0.25 * ( ngHeightAt( vNgWorld + vec2( ngRing.x, 0.0 ) )'],
  ['frag', 'float ngT = clamp( ( ngAround - ngOwn ) / 2.00, -1.0, 1.0 );'],
  ['frag', 'float ngShade = ngT > 0.0 ? -0.12 * ngT : -0.06 * ngT;'],
  ['frag', 'diffuseColor.rgb *= 1.0 + ngShade * uNgStrength * ngIn;'],
  ['frag', 'diffuseColor.rgb = clamp( diffuseColor.rgb, 0.0, 1.0 );'],
];
const NG_UNIFORMS = ['uNgHeight', 'uNgField', 'uNgFieldSize', 'uNgStrength'];
/** What `patchHole` writes — the predecessor the chain has to keep (the lines
 *  are the subject of `smoke_surface_patch.mjs`, here they are the witness). */
const HOLE_MARKS = [
  ['vert', 'varying vec3 vHoleWorld;'],
  ['frag', 'uniform vec4 uHole;'],
  ['frag', 'if ( uHoleOn > 0.5 &&'],
];
const HOLE_UNIFORMS = ['uHole', 'uHoleOn'];
/** …and what the WATER shader writes, which section [6] must find untouched. */
const WATER_MARKS = [
  ['vert', 'varying vec2 vWaterWorld;'],
  ['frag', 'uniform float uSkyMix;'],
  ['frag', 'float wMask = texture2D( uMask, vWaterUv ).r;'],
];

let failed = 0;
let passed = 0;
function check(label, actual, expected) {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  if (ok) {
    passed += 1;
    console.log(`  ok   ${label}`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}\n       expected ${JSON.stringify(expected)}`
      + `\n       actual   ${JSON.stringify(actual)}`);
  }
}

function marksIn(shader, marks) {
  return marks.filter(([where, text]) => (where === 'vert'
    ? shader.vertexShader : shader.fragmentShader).includes(text))
    .map(([, text]) => text);
}
const allOf = (marks) => marks.map(([, text]) => text);
/** Shading terms to four decimals — these are shares of an albedo, and
 *  comparing raw doubles would only measure the division by the span. */
const q = (v) => Math.round(v * 10000) / 10000;

async function main() {
  const THREE = await import('three');
  const { applyNaturalGround, setNaturalGroundField, NG_CACHE_KEY,
    ngHeightTex, ngField, ngFieldSize, ngStrength,
    patchHole, HOLE_CACHE_KEY, isWaterClass, surfaceMaterial } = await loadClient();
  const M = await loadMath();

  /** One material through the patch(es), with its composed shader. */
  function patched(before = null, mat = new THREE.MeshStandardMaterial({ color: 0x6a994e })) {
    if (before) before(mat);
    applyNaturalGround(mat);
    const shader = stubShader();
    mat.onBeforeCompile(shader, null);
    return { mat, shader };
  }

  console.log('\n[1] the patch alone — every line, the uniforms, the key');
  const meadow = patched();
  check('every natural-ground line is written', marksIn(meadow.shader, NG_MARKS),
    allOf(NG_MARKS));
  check('…the four uniforms are bound',
    NG_UNIFORMS.filter((u) => meadow.shader.uniforms[u] !== undefined), NG_UNIFORMS);
  check('the vertex anchor is APPENDED to, not replaced',
    meadow.shader.vertexShader.includes('#include <project_vertex>'), true);
  check('…and the world position stands after it',
    meadow.shader.vertexShader.indexOf('#include <project_vertex>')
      < meadow.shader.vertexShader.indexOf('vNgWorld ='), true);
  check('the colour work stands after the map chunk (it modifies what is there)',
    meadow.shader.fragmentShader.indexOf('#include <map_fragment>')
      < meadow.shader.fragmentShader.indexOf('float ngTint ='), true);
  check('the second sample is guarded by USE_MAP (a plain colour has no repeat)',
    meadow.shader.fragmentShader.indexOf('#ifdef USE_MAP')
      < meadow.shader.fragmentShader.indexOf('vec4 ngWide ='), true);
  check('…while the colour patches stand OUTSIDE that guard',
    meadow.shader.fragmentShader.indexOf('#endif')
      < meadow.shader.fragmentShader.indexOf('float ngTint ='), true);
  check('the AO stands inside the strength guard (0 reads nothing)',
    meadow.shader.fragmentShader.indexOf('if ( uNgStrength > 0.0 ) {')
      < meadow.shader.fragmentShader.indexOf('float ngOwn ='), true);
  check('…and the field is never sampled outside it',
    meadow.shader.fragmentShader.split('ngHeightAt( vNgWorld').length - 1, 5);
  check('nothing of the colour work lands in the vertex shader',
    meadow.shader.vertexShader.includes('diffuseColor'), false);
  check('the cache key is the patch\'s own', meadow.mat.customProgramCacheKey(),
    NG_CACHE_KEY);
  check('…which is the constant, not a value of the frame',
    NG_CACHE_KEY, 'natural-ground');
  const second = patched();
  check('a second material answers the SAME key (one program for all of them)',
    second.mat.customProgramCacheKey(), meadow.mat.customProgramCacheKey());

  console.log('\n[2] the chain — basement hole and natural ground on one material');
  const drape = patched((m) => patchHole(m));
  check('the hole lines survive the natural-ground patch',
    marksIn(drape.shader, HOLE_MARKS), allOf(HOLE_MARKS));
  check('…and every natural-ground line is there as well',
    marksIn(drape.shader, NG_MARKS), allOf(NG_MARKS));
  check('the hole uniforms are bound',
    HOLE_UNIFORMS.filter((u) => drape.shader.uniforms[u] !== undefined), HOLE_UNIFORMS);
  check('…and the natural-ground uniforms too',
    NG_UNIFORMS.filter((u) => drape.shader.uniforms[u] !== undefined), NG_UNIFORMS);
  check('the key is both, in the order they were applied',
    drape.mat.customProgramCacheKey(), `${HOLE_CACHE_KEY}+${NG_CACHE_KEY}`);
  check('…which is neither of the two singles',
    [HOLE_CACHE_KEY, NG_CACHE_KEY].includes(drape.mat.customProgramCacheKey()), false);
  applyNaturalGround(drape.mat);
  const twice = stubShader();
  drape.mat.onBeforeCompile(twice, null);
  check('patching twice is still one patch',
    twice.vertexShader.split('varying vec2 vNgWorld;').length - 1, 1);
  check('…and the noise is declared exactly once',
    twice.fragmentShader.split('float ngNoise(').length - 1, 1);
  check('…and the key did not grow a second stage',
    drape.mat.customProgramCacheKey(), `${HOLE_CACHE_KEY}+${NG_CACHE_KEY}`);

  console.log('\n[3] the shared uniforms — one upload reaches every ground material');
  check('two materials share ONE height texture',
    meadow.shader.uniforms.uNgHeight === drape.shader.uniforms.uNgHeight, true);
  check('…one field frame', meadow.shader.uniforms.uNgField === drape.shader.uniforms.uNgField, true);
  check('…one field size',
    meadow.shader.uniforms.uNgFieldSize === drape.shader.uniforms.uNgFieldSize, true);
  check('…and one strength',
    meadow.shader.uniforms.uNgStrength === drape.shader.uniforms.uNgStrength, true);
  check('…and they are the module\'s own objects',
    [meadow.shader.uniforms.uNgHeight === ngHeightTex,
      meadow.shader.uniforms.uNgField === ngField,
      meadow.shader.uniforms.uNgFieldSize === ngFieldSize,
      meadow.shader.uniforms.uNgStrength === ngStrength], [true, true, true, true]);

  console.log('\n[4] the height texture — what setNaturalGroundField uploads');
  // One 4 m hill on a 3x3 raster at a 10 m step, plus a 22.5 m peak: two values
  // that are exact in half float, which is what the round trip below pins.
  const hill = {
    origin_x: -10, origin_z: -10, step_m: 10, rows: 3, cols: 3,
    heights: [[0, 0, 0], [0, 4, 22.5], [0, 0, 0]],
  };
  setNaturalGroundField(hill);
  check('the stage is live', ngStrength.value, 1);
  check('the field frame is origin and step',
    [ngField.value.x, ngField.value.y, ngField.value.z], [-10, -10, 10]);
  check('…and the size is columns then rows',
    [ngFieldSize.value.x, ngFieldSize.value.y], [3, 3]);
  check('the texture is one texel per support point',
    [ngHeightTex.value.image.width, ngHeightTex.value.image.height], [3, 3]);
  check('…as a single red channel of half floats',
    [ngHeightTex.value.format, ngHeightTex.value.type],
    [THREE.RedFormat, THREE.HalfFloatType]);
  check('…filtered LINEARLY, because the field is defined bilinear',
    [ngHeightTex.value.minFilter, ngHeightTex.value.magFilter],
    [THREE.LinearFilter, THREE.LinearFilter]);
  check('…clamped at the edge, because outside the raster the world is flat',
    [ngHeightTex.value.wrapS, ngHeightTex.value.wrapT],
    [THREE.ClampToEdgeWrapping, THREE.ClampToEdgeWrapping]);
  check('…with no mipmaps and byte-tight rows (an odd column count would smear)',
    [ngHeightTex.value.generateMipmaps, ngHeightTex.value.unpackAlignment], [false, 1]);
  const back = [...ngHeightTex.value.image.data].map((h) => THREE.DataUtils.fromHalfFloat(h));
  check('the heights come back row by row, exact',
    back, [0, 0, 0, 0, 4, 22.5, 0, 0, 0]);
  check('…and every ground material sees the new texture at once',
    [meadow.shader.uniforms.uNgHeight.value === ngHeightTex.value,
      drape.shader.uniforms.uNgStrength.value], [true, 1]);

  const flat = { ...hill, heights: [[0, 0, 0], [0, 0, 0], [0, 0, 0]] };
  setNaturalGroundField(flat);
  check('a world nobody has shaped is EXACTLY neutral', ngStrength.value, 0);
  setNaturalGroundField({ ...hill, heights: [[3, 3, 3], [3, 3, 3], [3, 3, 3]] });
  check('…and so is one lifted whole (it is the RANGE that matters, not the height)',
    ngStrength.value, 0);
  setNaturalGroundField(hill);
  check('a shaped world switches back on', ngStrength.value, 1);
  setNaturalGroundField({ ...hill, rows: 1, cols: 1, heights: [[4]] });
  check('a field too small to have an interior is neutral', ngStrength.value, 0);
  setNaturalGroundField(hill);
  setNaturalGroundField(null);
  check('…and so is a relief that never arrived', ngStrength.value, 0);
  check('…which points the sampler at the one neutral texel, never at nothing',
    [ngHeightTex.value.image.width, ngHeightTex.value.image.height], [1, 1]);
  check('…and resets the frame, so no stale origin survives the teardown',
    [ngField.value.x, ngField.value.z, ngFieldSize.value.x], [0, 1, 1]);

  console.log('\n[5] the arithmetic — naturalGroundMath, by hand');
  check('flat ground shades nothing', q(M.ngAoShade(0, 0)), 0);
  check('surroundings 1 m higher: a shallow hollow', q(M.ngAoShade(1, 0)), -0.06);
  check('surroundings 2 m higher: fully spent', q(M.ngAoShade(2, 0)), -0.12);
  check('…and 8 m higher is not four hollows', q(M.ngAoShade(8, 0)), -0.12);
  check('surroundings 1 m lower: half the brightening', q(M.ngAoShade(-1, 0)), 0.03);
  check('surroundings 2 m lower: fully spent, and HALF the darkening',
    [q(M.ngAoShade(-2, 0)), q(M.ngAoShade(-8, 0))], [0.06, 0.06]);
  check('…which is the amplitude pair 12 % down, 6 % up',
    [M.NG_AO_DOWN, M.NG_AO_UP], [0.12, 0.06]);
  check('it is the DIFFERENCE that counts, not the altitude',
    [q(M.ngAoShade(102, 100)), q(M.ngAoShade(2, 0))], [-0.12, -0.12]);
  check('the ring is four taps at three metres', M.ngAoTaps(),
    [[3, 0], [-3, 0], [0, 3], [0, -3]]);
  const grid = { origin_x: -100, origin_z: -100, step_m: 10, rows: 21, cols: 21 };
  const at = (x, z) => {
    const uv = M.ngFieldUv(x, z, grid);
    return [q(uv.u), q(uv.v), uv.inside];
  };
  check('the first support point sits on the FIRST TEXEL CENTRE',
    at(-100, -100), [q(0.5 / 21), q(0.5 / 21), true]);
  check('…and the last on the last', at(100, 100), [q(20.5 / 21), q(20.5 / 21), true]);
  check('half a cell beyond the first point is the texture\'s own edge',
    at(-105, -105), [0, 0, true]);
  check('…and a whole cell beyond it is outside, where the stage is neutral',
    at(-110, -110), [q(-1 / 42), q(-1 / 42), false]);
  check('the colour factors swing +-8 % around 1',
    [M.ngTintFactors(1, 1).brightness, M.ngTintFactors(0, 0).saturation], [1.08, 0.92]);
  check('…and the middle of the noise leaves the ground exactly as it was',
    [M.ngTintFactors(0.5, 0.5).brightness, M.ngTintFactors(0.5, 0.5).saturation], [1, 1]);
  check('the second sample is 0.23x the scale, half a UV across',
    [M.ngDetailUv(1, 1), M.ngDetailUv(0, 0)], [[0.73, 0.73], [0.5, 0.5]]);
  check('water and ice carry their own shader', [isWaterClass('water'), isWaterClass('ice')],
    [true, true]);
  check('…and nothing else does',
    ['matte', 'gloss', 'glow', '', null, undefined].map(isWaterClass),
    [false, false, false, false, false, false]);

  console.log('\n[6] water keeps its own shader — the anchor count');
  /** `materialFor`'s decision, reproduced: hole always, natural ground only
   *  where the class does not bring a shader of its own. */
  function groundMaterial(spec) {
    const mat = surfaceMaterial(THREE, { material: spec, color: 0x3f7fb8 });
    patchHole(mat);
    if (!isWaterClass(spec?.class)) applyNaturalGround(mat);
    const shader = stubShader();
    mat.onBeforeCompile(shader, null);
    return { mat, shader };
  }
  const lake = groundMaterial({ class: 'water', tint: '#3f7fb8' });
  check('a painted lake gets NOT ONE natural-ground line',
    marksIn(lake.shader, NG_MARKS), []);
  check('…nor one of its uniforms',
    NG_UNIFORMS.filter((u) => lake.shader.uniforms[u] !== undefined), []);
  check('…while every water line is there', marksIn(lake.shader, WATER_MARKS),
    allOf(WATER_MARKS));
  check('…and the hole still cuts through it (a cellar under a lake)',
    marksIn(lake.shader, HOLE_MARKS), allOf(HOLE_MARKS));
  check('…which the key says: water, hole, and no third stage',
    lake.mat.customProgramCacheKey(), `anima-water+${HOLE_CACHE_KEY}`);
  const ice = groundMaterial({ class: 'ice', tint: '#cfe8f5' });
  check('ice is water that stands still, and is spared just the same',
    marksIn(ice.shader, NG_MARKS), []);
  const meadowSpec = groundMaterial({ class: 'matte' });
  check('the very same decision patches a matte ground',
    marksIn(meadowSpec.shader, NG_MARKS), allOf(NG_MARKS));
  check('…and one with no declaration at all', marksIn(groundMaterial(null).shader, NG_MARKS),
    allOf(NG_MARKS));

  console.log('\n[7] the wiring, pinned by reading the source');
  const groundSrc = await readFile(GROUND_SRC, 'utf8');
  check('materialFor patches the hole first',
    /patchHole\(mat\);\n(\s*\/\/[^\n]*\n)*\s*if \(!isWaterClass\(spec\?\.class\)\) applyNaturalGround\(mat\);/
      .test(groundSrc), true);
  check('…and that is the only place it is applied',
    groundSrc.split('applyNaturalGround(').length - 1, 1);
  check('the overview reaches the shader when height_sig moves',
    /heightRev \+= 1;[\s\S]{0,600}?setNaturalGroundField\(payload\);/.test(groundSrc), true);
  check('…and is handed back on teardown',
    /dispose\(\) \{[\s\S]{0,600}?setNaturalGroundField\(null\);/.test(groundSrc), true);
  check('…twice in the file and nowhere else',
    groundSrc.split('setNaturalGroundField(').length - 1, 2);
  const preview = await readFile(PREVIEW_SRC, 'utf8');
  check('the admin preview stays untouched (view polish is not geometry)',
    preview.includes('naturalGround'), false);
  const shared = await readFile(join(ROOT, 'packages/scene-render/src/materials.ts'), 'utf8');
  check('…and the shared package knows nothing of it either',
    shared.includes('naturalGround'), false);

  console.log('\n[8] the RED counter-checks — the chain, the sign, the flat world');
  const red = await loadClient(assignInsteadOfChain);
  const redMat = new THREE.MeshStandardMaterial({ color: 0x6a994e });
  red.patchHole(redMat);
  red.applyNaturalGround(redMat);
  const redShader = stubShader();
  redMat.onBeforeCompile(redShader, null);
  check('the assignment mutant loses EVERY hole line',
    marksIn(redShader, HOLE_MARKS), []);
  check('…and the hole uniforms with them',
    HOLE_UNIFORMS.filter((u) => redShader.uniforms[u] !== undefined), []);
  check('…while its own three stages are fully intact (the probe measures the chain)',
    marksIn(redShader, NG_MARKS), allOf(NG_MARKS));
  check('the truth, from the other side, KEEPS the hole',
    marksIn(drape.shader, HOLE_MARKS).length, HOLE_MARKS.length);

  const lit = await loadMath(flipShadeSign);
  check('with the sign turned around the hollow comes out BRIGHTER',
    [q(lit.ngAoShade(2, 0)), q(lit.ngAoShade(-2, 0))], [0.12, -0.06]);
  check('…while the truth darkens it, for the very same ground',
    [q(M.ngAoShade(2, 0)), q(M.ngAoShade(-2, 0))], [-0.12, 0.06]);

  const litGlsl = await loadClient(flipShadeSignGlsl);
  const litMat = new THREE.MeshStandardMaterial({ color: 0x6a994e });
  litGlsl.applyNaturalGround(litMat);
  const litShader = stubShader();
  litMat.onBeforeCompile(litShader, null);
  check('the same flip in the emitted GLSL loses the shade line the truth writes',
    litShader.fragmentShader.includes('float ngShade = ngT > 0.0 ? -0.12 * ngT : -0.06 * ngT;'),
    false);
  check('…and writes the lit one instead',
    litShader.fragmentShader.includes('float ngShade = ngT > 0.0 ? 0.12 * ngT : 0.06 * ngT;'),
    true);
  check('…while everything around it is untouched (the probe measures the sign)',
    marksIn(litShader, NG_MARKS).length, NG_MARKS.length - 1);

  const shaded = await loadClient(shadeTheFlatWorld);
  shaded.setNaturalGroundField(flat);
  check('without the flat-world test a level world WOULD be shaded',
    shaded.ngStrength.value, 1);
  setNaturalGroundField(flat);
  check('…while the truth answers 0 for the very same field', ngStrength.value, 0);

  console.log(`\n${passed} ok, ${failed} failed`);
  process.exit(failed ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
