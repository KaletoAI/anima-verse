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
 *   (4) SOFT EDGE   a painted area fades out over the last 1.5 m of itself
 *                   along a noise-shifted line, so what lies under it comes
 *                   through instead of a drawn border. The distance to the
 *                   area's ring is a per-vertex attribute (`aEdgeDist`), and
 *                   only a material that HAS that attribute may compile the
 *                   branch — the base plate must not.
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
 * [9] THE SOFT EDGE — the band, the attribute, the two programs
 * ---------------------------------------------------------------------------
 * The band by hand, on `ngEdgeAlpha`: 0 at the ring, 0.15625 a quarter of the
 * way in, 0.5 at 0.75 m (the smoothstep of a half is a half, exactly), 0.84375
 * at three quarters, 1 from 1.5 m — and 1 from 2 m WHATEVER the noise does,
 * which is what "the core is opaque" means as a number. The noise moves the
 * edge by half a metre either way: at 0.75 m it reads 0.925926 with the noise
 * at 1 and 0.074074 with it at 0.
 * The distance itself: to a SEGMENT and not to its line, over a CLOSED ring
 * (the edge from the last corner back to the first is an edge).
 * THE REFINEMENT is checked on the case that makes it necessary — a flat
 * world's earcut triangles, whose every corner lies on the ring. Unrefined,
 * the interpolated distance is 0 across the whole face and the area would fade
 * away completely; refined, the middle of it is opaque and a point 0.75 m in
 * still reads 0.75. Reading it the way the GPU does (barycentric, in the
 * triangle the point falls in) is the point: corners are not the question.
 * The surface must not move (a tilted plane comes back exactly), the winding
 * must not flip (a flipped piece is a hole), and the whole thing must stay
 * cheap.
 * THE EDGE NAME is quantised, and that is what makes the marks conforming: the
 * grid clip hands the two owners of a shared edge the same intersection as two
 * different doubles (it interpolates from both ends), and a raw key would name
 * that edge twice and let its owners disagree about splitting it.
 * THE TWO PROGRAMS: the drape carries the `NG_EDGE_FADE` define, is
 * transparent and says so in its cache key; the base plate has none of the
 * three and therefore never compiles the branch that reads an attribute it
 * has not got. Both still WRITE depth — the coplanar `renderOrder` +
 * `polygonOffset` ladder of `ground.ts` rests on that — and the drapes' ladder
 * starts at a large NEGATIVE base, which is what keeps the transparent ground
 * behind every overlay that leaves its render order at the default 0.
 *
 * ---------------------------------------------------------------------------
 * [8] THE RED COUNTER-CHECKS — eight mutants, eight losses
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
 * (e) THE HALF TEXEL. `+ 0.5` drops out of the world -> UV mapping, which puts
 *     every support point on a texel CORNER and slides the whole shading half
 *     a support cell. This is the mutant the mapping was made a function for:
 *     while the line stood twice, one copy could lose it and every string
 *     check still found the other.
 * (f) THE BAND REFINEMENT gives up before its first pass. A coarse drape then
 *     reports "edge" in its middle, i.e. alpha 0 — the area vanishes where the
 *     truth is fully opaque.
 * (g) THE FRINGE ITSELF: the alpha line goes and the area ends on the drawn
 *     line of its polygon again, with everything else about the patch intact.
 * (h) AN UNPRINTABLE CONSTANT (1.505 m). The module must refuse to LOAD;
 *     without the assert `toFixed` would round it to 1.51 and the shader would
 *     spend a different number than the maths does.
 * (i) THE OLD RENDER-ORDER LADDER (1, 2, 3 …). Harmless while the drapes were
 *     opaque, fatal once they are not: in the transparent pass they would be
 *     drawn after every overlay that keeps the default order 0, and those write
 *     no depth — the opaque core of a painted area would paint over the
 *     selection ring under an NPC and punch a hole in the fog.
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
      + '  NG_EDGE_ATTRIBUTE, NG_EDGE_CACHE_KEY, NG_EDGE_DEFINE, ngLit,\n'
      + '  ngHeightTex, ngField, ngFieldSize, ngStrength }\n'
      + `  from '${NG_SRC}';\n`
      + `export { patchHole, HOLE_CACHE_KEY, AREA_RENDER_ORDER_BASE } from '${GROUND_SRC}';\n`
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

/** Section [8e]'s mutant, and the reason the mapping stands in a function at
 *  all: the HALF TEXEL drops out of the world -> UV line. Support point i then
 *  addresses the corner of texel i instead of its centre and the whole shading
 *  slides half a support cell — a lie no screenshot shows. */
function dropTheHalfTexel(text) {
  const line = '( ( p - uNgField.xy ) / uNgField.z + 0.5 ) / uNgFieldSize';
  if (!text.includes(line)) throw new Error('the field mapping is no longer where the probe looks');
  return text.replace(line, '( ( p - uNgField.xy ) / uNgField.z ) / uNgFieldSize');
}

/** Section [8f]'s mutant: the band refinement gives up before its first pass,
 *  so a drape keeps the triangles it came in with. */
function refineNothing(source) {
  const line = 'export const NG_EDGE_PASSES = 8;';
  if (!source.includes(line)) throw new Error('the pass budget is no longer where the probe looks');
  return source.replace(line, 'export const NG_EDGE_PASSES = 0;');
}

/** Section [8g]'s mutant: the alpha line goes, and with it the whole fringe —
 *  the area ends on the drawn line of its polygon again. */
function dropTheFringe(text) {
  const line = 'diffuseColor.a *= smoothstep( 0.0, ';
  if (!text.includes(line)) throw new Error('the fringe line is no longer where the probe looks');
  return text.replace(line, 'diffuseColor.rgb *= vec3( 1.0 ); // ');
}

/** Section [8h]'s mutant: a constant that two decimals cannot print. The
 *  module must refuse to LOAD; without the assert `toFixed` would round it and
 *  the shader would fade over 1.51 m while the maths says 1.505. */
function unprintableConstant(text) {
  const line = 'NG_EDGE_BAND_M = 1.5;';
  if (!text.includes(line)) throw new Error('the band width is no longer where the probe looks');
  return text.replace(line, 'NG_EDGE_BAND_M = 1.505;');
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
  // THE WORLD -> FIELD MAPPING, in ONE function and with the half texel in it.
  // Both readers go through this; a second copy of the line is a second chance
  // to lose the `+ 0.5` and shift the whole shading by half a support cell,
  // which is what the mutant of [8e] measures.
  ['frag', 'vec2 ngFieldUvOf( vec2 p ) {'],
  ['frag', 'return ( ( p - uNgField.xy ) / uNgField.z + 0.5 ) / uNgFieldSize;'],
  ['frag', 'return texture2D( uNgHeight, ngFieldUvOf( p ) ).r;'],
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
  // (3) the taps of the 3 m ring, the span, and THE SIGN. The taps themselves
  //     are checked against `ngAoTaps()` in [1] instead of being copied here.
  ['frag', 'if ( uNgStrength > 0.0 ) {'],
  ['frag', 'float ngOwn = ngHeightAt( vNgWorld );'],
  ['frag', 'float ngT = clamp( ( ngAround - ngOwn ) / 2.00, -1.0, 1.0 );'],
  ['frag', 'float ngShade = ngT > 0.0 ? -0.12 * ngT : -0.06 * ngT;'],
  ['frag', 'vec2 ngUv = ngFieldUvOf( vNgWorld );'],
  ['frag', 'diffuseColor.rgb *= 1.0 + ngShade * uNgStrength * ngIn;'],
  ['frag', 'diffuseColor.rgb = clamp( diffuseColor.rgb, 0.0, 1.0 );'],
  // (4) the soft edge. The lines are PRINTED on every ground material and the
  //     `NG_EDGE_FADE` define decides who compiles them — see [9].
  ['vert', 'attribute float aEdgeDist;'],
  ['vert', 'varying float vNgEdge;'],
  ['vert', 'vNgEdge = aEdgeDist;'],
  ['frag', 'varying float vNgEdge;'],
  ['frag', 'float ngEdgePush = ( ngNoise( vNgWorld / 2.00 + vec2( 5.0, 23.0 ) ) * 2.0 - 1.0 ) * 0.50;'],
  ['frag', 'diffuseColor.a *= smoothstep( 0.0, 1.50, vNgEdge + ngEdgePush );'],
];
const NG_UNIFORMS = ['uNgHeight', 'uNgField', 'uNgFieldSize', 'uNgStrength'];
/** The drapes' place in the transparent pass, as `ground.ts` writes it — one
 *  regular expression for the truth in [9] and for the mutant in [8i], so the
 *  two sides cannot drift. */
const AREA_ORDER_RE = /mesh\.renderOrder = AREA_RENDER_ORDER_BASE \+ index \+ 1;/;
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
/** …and six, where the hand value is a smoothstep of thirds (0.925926). */
const q6 = (v) => Math.round(v * 1e6) / 1e6;

/** A plane over the ground, for the check that the band refinement does not
 *  move the surface: any tilt will do as long as it is not flat. */
const tiltY = (x, z) => 3 + 0.1 * x + 0.2 * z;

/**
 * Read a refined drape the way the GPU does: find the triangle a point falls
 * in and interpolate its vertex values barycentrically.
 *
 * That is the whole question the `aEdgeDist` attribute has to answer — not
 * "what is at the corners" but "what does the fragment between them get" —
 * and it is why the coarse-drape case in [9] is a check and not a hope.
 */
function sampleTri(band, x, z) {
  for (let t = 0; t + 8 < band.pos.length; t += 9) {
    const ax = band.pos[t]; const az = band.pos[t + 2];
    const bx = band.pos[t + 3]; const bz = band.pos[t + 5];
    const cx = band.pos[t + 6]; const cz = band.pos[t + 8];
    const det = (bz - cz) * (ax - cx) + (cx - bx) * (az - cz);
    if (Math.abs(det) < 1e-12) continue;
    const l1 = ((bz - cz) * (x - cx) + (cx - bx) * (z - cz)) / det;
    const l2 = ((cz - az) * (x - cx) + (ax - cx) * (z - cz)) / det;
    const l3 = 1 - l1 - l2;
    if (l1 < -1e-9 || l2 < -1e-9 || l3 < -1e-9) continue;
    const i = t / 3;
    return { d: l1 * band.dist[i] + l2 * band.dist[i + 1] + l3 * band.dist[i + 2],
             y: l1 * band.pos[t + 1] + l2 * band.pos[t + 4] + l3 * band.pos[t + 7] };
  }
  return null;
}
const sampleBand = (band, x, z) => sampleTri(band, x, z)?.d ?? NaN;
const sampleBandY = (band, x, z) => sampleTri(band, x, z)?.y ?? NaN;

/** Do all pieces of a refined drape run the same way round? A piece wound
 *  against its parent faces down and is culled away — a hole in the ground. */
function windings(band) {
  const signs = new Set();
  for (let t = 0; t + 8 < band.pos.length; t += 9) {
    const cross = (band.pos[t + 3] - band.pos[t]) * (band.pos[t + 8] - band.pos[t + 2])
      - (band.pos[t + 5] - band.pos[t + 2]) * (band.pos[t + 6] - band.pos[t]);
    if (Math.abs(cross) > 1e-9) signs.add(Math.sign(cross));
  }
  return signs.size === 1 ? 'all one way' : `${signs.size} windings`;
}

async function main() {
  const THREE = await import('three');
  const { applyNaturalGround, setNaturalGroundField, NG_CACHE_KEY,
    NG_EDGE_ATTRIBUTE, NG_EDGE_CACHE_KEY, NG_EDGE_DEFINE, ngLit,
    ngHeightTex, ngField, ngFieldSize, ngStrength,
    patchHole, HOLE_CACHE_KEY, AREA_RENDER_ORDER_BASE,
    isWaterClass, surfaceMaterial } = await loadClient();
  const M = await loadMath();

  /** One material through the patch(es), with its composed shader. */
  function patched(before = null, mat = new THREE.MeshStandardMaterial({ color: 0x6a994e }),
                   edgeFade = false) {
    if (before) before(mat);
    applyNaturalGround(mat, edgeFade);
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
  // THE MAPPING, ONCE. Two readers need the world -> texture coordinate (the
  // height itself and the "is the fragment over the raster at all" test), and
  // the half texel in it is the difference between shading the hill and
  // shading half a support cell beside it. One function, one occurrence of the
  // arithmetic — counted, so a second copy cannot creep back in.
  check('the world -> field mapping is written exactly ONCE',
    meadow.shader.fragmentShader.split('- uNgField.xy').length - 1, 1);
  check('…and both readers go through that one function',
    meadow.shader.fragmentShader.split('ngFieldUvOf(').length - 1, 3);
  // THE RING, out of `ngAoTaps` and not out of a shader somebody typed: the
  // tap offsets, how many there are, and the divisor of their mean.
  const tapLines = M.ngAoTaps()
    .map(([dx, dz]) => `ngHeightAt( vNgWorld + vec2( ${dx.toFixed(2)}, ${dz.toFixed(2)} ) )`);
  check('every tap of ngAoTaps() is read, at its own offset',
    tapLines.filter((l) => meadow.shader.fragmentShader.includes(l)).length,
    M.ngAoTaps().length);
  check('…the mean divides by the LENGTH of that list, not by a typed 0.25',
    meadow.shader.fragmentShader.includes(`float ngAround = ( 1.0 / ${M.ngAoTaps().length}.0 ) * (`),
    true);
  check('…and the field is read once per tap plus once for the fragment itself',
    meadow.shader.fragmentShader.split('ngHeightAt( vNgWorld').length - 1,
    M.ngAoTaps().length + 1);
  check('nothing of the colour work lands in the vertex shader',
    meadow.shader.vertexShader.includes('diffuseColor'), false);
  check('the cache key is the patch\'s own', meadow.mat.customProgramCacheKey(),
    NG_CACHE_KEY);
  check('…which is the constant, not a value of the frame',
    NG_CACHE_KEY, 'natural-ground');
  const second = patched();
  check('a second material answers the SAME key (one program for all of them)',
    second.mat.customProgramCacheKey(), meadow.mat.customProgramCacheKey());
  // THE PRINTER, and why it may print two decimals. `toFixed` rounds silently:
  // a constant of 0.125 would reach the maths as 0.125 and the GPU as 0.13, and
  // "one number" would quietly be two. So the printer refuses what it cannot
  // print, at LOAD time — the mutant of [8h] is the other half of this.
  check('the GLSL printer gives back exactly what it was handed',
    [ngLit(0.5), ngLit(3), ngLit(-3), ngLit(0.08)], ['0.50', '3.00', '-3.00', '0.08']);
  check('…and refuses a number two decimals would round',
    (() => { try { ngLit(0.125); return 'printed'; } catch { return 'refused'; } })(), 'refused');
  const ngSrc = await readFile(NG_SRC, 'utf8');
  const imported = [...new Set((/import \{([\s\S]*?)\} from '\.\/naturalGroundMath'/
    .exec(ngSrc)?.[1] ?? '').match(/NG_[A-Z0-9_]+/g) ?? [])].sort();
  const swept = [...new Set((/const NG_PRINTED_AMOUNTS = \[([\s\S]*?)\];/
    .exec(ngSrc)?.[1] ?? '').match(/NG_[A-Z0-9_]+/g) ?? [])].sort();
  check('every amount the module imports is checked at load, and none is missing',
    swept, imported);
  check('…and there is more than a handful of them (the probe reads something)',
    imported.length > 8, true);

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
    /patchHole\(mat\);\n(\s*\/\/[^\n]*\n)*\s*if \(!isWaterClass\(spec\?\.class\)\) applyNaturalGround\(mat, edgeFade\);/
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
  // WHO GETS THE FRINGE: the painted-area drapes, and the base plate does not.
  // ONE decision, out of the class the material is built from, reaching the
  // geometry and the material alike — so a lake is spared the refinement and
  // the attribute as well as the branch.
  check('the drape is built from its own ring and asks for the fringe',
    /const softEdge = !isWaterClass\(surfaceMaterialSpec\(area\.kind\)\?\.class\);[\s\S]{0,300}?drapeArea\(built\.geometry, softEdge \? built\.ring : null\),\n\s*materialFor\(area\.kind, 1, nextOwned, softEdge\)/
      .test(groundSrc), true);
  check('…and a kind without a fringe gets neither refinement nor attribute',
    /const band = ring \? ngRefineEdgeBand\(cutPos, cutUv, ring\) : null;/.test(groundSrc)
      && /if \(band\) \{\n\s*geo\.setAttribute\(NG_EDGE_ATTRIBUTE/.test(groundSrc), true);
  check('…while the base plate takes the material without one',
    /materialFor\(kind, Math\.min\(w, d\), baseOwned\)/.test(groundSrc), true);
  check('the drape writes the distance attribute the shader reads',
    /geo\.setAttribute\(NG_EDGE_ATTRIBUTE, new THREE\.Float32BufferAttribute\(band\.dist, 1\)\)/
      .test(groundSrc), true);
  check('…out of the refinement, and after the lift (same surface, more triangles)',
    /liftToField\(cutPos\);[\s\S]{0,200}?const band = ring \? ngRefineEdgeBand\(cutPos, cutUv, ring\) : null;/
      .test(groundSrc), true);

  console.log('\n[9] the soft edge — the band, the attribute, the two programs');
  check('at the ring the ground is gone, and half way through the band it is half there',
    [M.ngEdgeAlpha(0), M.ngEdgeAlpha(0.75), M.ngEdgeAlpha(1.5)], [0, 0.5, 1]);
  check('…a quarter and three quarters of the way, on the smoothstep curve',
    [M.ngEdgeAlpha(0.375), M.ngEdgeAlpha(1.125)], [0.15625, 0.84375]);
  check('…and the CORE is opaque, whatever the noise does to the edge',
    [M.ngEdgeAlpha(M.NG_EDGE_OPAQUE_M, 0), M.ngEdgeAlpha(20, 0), M.ngEdgeAlpha(20, 1)],
    [1, 1, 1]);
  check('the noise moves the edge, and measurably',
    [q6(M.ngEdgeAlpha(0.75, 1)), q6(M.ngEdgeAlpha(0.75, 0))], [0.925926, 0.074074]);
  check('…by half a metre either way, which is what the opaque distance adds up from',
    [M.NG_EDGE_BAND_M, M.NG_EDGE_NOISE_M, M.NG_EDGE_OPAQUE_M], [1.5, 0.5, 2]);
  check('a distance is to the SEGMENT, not to its line (a corner measures as a corner)',
    [M.ngSegmentDistance(0, 0, 1, -1, 1, 1), q6(M.ngSegmentDistance(0, 0, 1, 1, 2, 2)),
      M.ngSegmentDistance(3, 4, 0, 0, 0, 0)],
    [1, q6(Math.SQRT2), 5]);
  const square = [[0, 0], [10, 0], [10, 10], [0, 10]];
  check('the ring is CLOSED — the edge from the last corner back to the first counts',
    [M.ngEdgeDistance(5, 5, square), M.ngEdgeDistance(1, 5, square),
      M.ngEdgeDistance(5, 0.75, square), M.ngEdgeDistance(0, 3, square),
      M.ngEdgeDistance(9.5, 9.5, square)], [5, 1, 0.75, 0, 0.5]);
  check('…and a ring with no edge at all is infinitely far from everywhere',
    [M.ngEdgeDistance(1, 1, []), M.ngEdgeDistance(1, 1, null)], [Infinity, Infinity]);

  // THE REFINEMENT, on the case that makes it necessary: a flat world's earcut
  // triangles have EVERY corner on the ring, so an unrefined drape reads
  // distance 0 across its whole face — the area would fade away completely.
  const coarse = [0, 0, 0, 10, 0, 0, 10, 0, 10,
                  0, 0, 0, 10, 0, 10, 0, 0, 10];
  const band = M.ngRefineEdgeBand(coarse, null, square);
  check('the coarse drape comes in with every corner on the ring',
    [0, 1, 2, 3, 4, 5].map((n) => M.ngEdgeDistance(coarse[n * 3], coarse[n * 3 + 2], square)),
    [0, 0, 0, 0, 0, 0]);
  check('…and comes out with one distance per vertex',
    band.dist.length, band.pos.length / 3);
  check('the middle of the area is OPAQUE after the refinement',
    sampleBand(band, 5, 5) >= M.NG_EDGE_OPAQUE_M, true);
  check('…and the fringe of it still is the fringe, to the centimetre',
    [q(sampleBand(band, 0.75, 5)), q(sampleBand(band, 5, 0.75)),
      q(sampleBand(band, 9.25, 5))], [0.75, 0.75, 0.75]);
  check('nothing moved: the refined mesh stays inside the ring it was cut from',
    [Math.min(...band.pos.filter((_, i) => i % 3 === 0)),
      Math.max(...band.pos.filter((_, i) => i % 3 === 0))], [0, 10]);
  // The height is INTERPOLATED, never resampled: the drape arrives lifted onto
  // the relief, and a midpoint lifted a second time would leave the plate.
  const tilted = coarse.map((v, i) => (i % 3 === 1 ? tiltY(coarse[i - 1], coarse[i + 1]) : v));
  const lifted = M.ngRefineEdgeBand(tilted, null, square);
  check('the refinement describes the very same surface (the plane is preserved)',
    [q(sampleBandY(lifted, 5, 5)), q(sampleBandY(lifted, 2.5, 7.5))],
    [q(tiltY(5, 5)), q(tiltY(2.5, 7.5))]);
  check('…and every piece keeps its parent\'s winding (a flipped one would be culled)',
    windings(band), 'all one way');
  // THE EDGE NAME, which is what makes the refinement seam-free. The two
  // triangles that share an edge do NOT hold bit-identical endpoints: the grid
  // clip interpolates the same intersection from both directions, `a + (b−a)·t`
  // against `b + (a−b)·(1−t)`, which is one real number and two doubles. A raw
  // key would name that edge twice and let its owners disagree about splitting
  // it — precisely the alpha seam the marks exist to prevent.
  const { ngEdgeKey } = M;
  const vert = (x, z) => ({ x, y: 0, z, u: 0, v: 0, d: 0 });
  const lerpFwd = (a, b, t) => a + (b - a) * t;
  const lerpBack = (a, b, t) => b + (a - b) * (1 - t);
  const cut = [0.1, 0.3, 0.7].map((t) => [lerpFwd(-7.3, 12.9, t), lerpBack(-7.3, 12.9, t)]);
  check('the two directions of one clip really are different doubles',
    cut.some(([f, b]) => f !== b), true);
  check('…and still name the same edge',
    cut.map(([f, b]) => ngEdgeKey(vert(f, 3), vert(9, 4))
      === ngEdgeKey(vert(b, 3), vert(9, 4))), [true, true, true]);
  check('…as does the same edge read backwards',
    ngEdgeKey(vert(1, 2), vert(3, 4)), ngEdgeKey(vert(3, 4), vert(1, 2)));
  const oneUlpAbove5 = 5 + Number.EPSILON * 4;   // the ulp at 5 is 4·EPSILON
  check('one ULP away is a different double…', oneUlpAbove5 === 5, false);
  check('…and still the same vertex',
    ngEdgeKey(vert(oneUlpAbove5, 2), vert(9, 9)), ngEdgeKey(vert(5, 2), vert(9, 9)));
  check('…while a real neighbour a millimetre away is NOT',
    ngEdgeKey(vert(5.001, 2), vert(9, 9)) === ngEdgeKey(vert(5, 2), vert(9, 9)), false);
  check('the UVs are carried along when there are any',
    M.ngRefineEdgeBand(coarse, coarse.filter((_, i) => i % 3 !== 1), square).uv.length,
    (band.pos.length / 3) * 2);
  check('…and stay null when there were none', band.uv, null);
  check('a triangle deep inside a huge area is not touched at all',
    M.ngRefineEdgeBand([100, 0, 100, 200, 0, 100, 200, 0, 200], null,
      [[0, 0], [1000, 0], [1000, 1000], [0, 1000]]).pos.length / 9, 1);
  check('…and the whole of a small area is worth only a few hundred triangles',
    band.pos.length / 9 < 400, true);

  // THE TWO PROGRAMS. The plate has no `aEdgeDist` attribute, so it must not
  // compile a line that reads one — an unbound attribute reads as 0 on most
  // drivers, which would fade the plate out along its whole rim. The lines are
  // printed on both; the DEFINE is what separates them.
  const plate = patched();
  const drapeEdge = patched(null, new THREE.MeshStandardMaterial({ color: 0x6a994e }), true);
  check('the drape defines the fringe on', drapeEdge.mat.defines?.[NG_EDGE_DEFINE], '');
  check('…and the base plate does not', plate.mat.defines?.[NG_EDGE_DEFINE], undefined);
  check('…which is the only difference in their defines',
    Object.keys(drapeEdge.mat.defines ?? {}).filter((k) => !(k in (plate.mat.defines ?? {}))),
    [NG_EDGE_DEFINE]);
  check('the drape blends, the plate stays opaque',
    [drapeEdge.mat.transparent, plate.mat.transparent], [true, false]);
  check('…and the drape still WRITES depth (the coplanar ladder rests on it)',
    [drapeEdge.mat.depthWrite, plate.mat.depthWrite], [true, true]);
  check('the fringe is a program of its own, and says so in the key',
    [plate.mat.customProgramCacheKey(), drapeEdge.mat.customProgramCacheKey()],
    [NG_CACHE_KEY, `${NG_CACHE_KEY}+${NG_EDGE_CACHE_KEY}`]);
  check('…and chained after the hole it is all three, in order',
    patched((m) => patchHole(m), new THREE.MeshStandardMaterial({}), true)
      .mat.customProgramCacheKey(),
    `${HOLE_CACHE_KEY}+${NG_CACHE_KEY}+${NG_EDGE_CACHE_KEY}`);
  check('every line that reads the attribute stands inside the define',
    [...drapeEdge.shader.vertexShader.matchAll(/#ifdef NG_EDGE_FADE([\s\S]*?)#endif/g)]
      .map((m) => m[1]).join('').includes(NG_EDGE_ATTRIBUTE), true);
  check('…and the attribute is named nowhere else in the vertex shader',
    drapeEdge.shader.vertexShader.split(NG_EDGE_ATTRIBUTE).length - 1, 2);
  check('…nor anywhere in the fragment shader (it travels as a varying)',
    drapeEdge.shader.fragmentShader.includes(NG_EDGE_ATTRIBUTE), false);
  // WHERE THE TRANSPARENT GROUND SITS IN THE PASS. Turning the drapes
  // transparent moved them out of the opaque pass, where they were drawn
  // before everything, into the one three sorts by `renderOrder` — and every
  // overlay that leaves its order at the default 0 (fog clouds, selection
  // rings, path lines, door marks) writes no depth, so a drape drawn after
  // them paints its opaque core straight over them.
  check('the drape ladder starts far in FRONT of the default overlays',
    [AREA_RENDER_ORDER_BASE < 0, AREA_RENDER_ORDER_BASE + 1 + 200 < 0], [true, true]);
  check('…and keeps the stacking order among the areas themselves',
    [1, 2, 3].map((i) => AREA_RENDER_ORDER_BASE + i),
    [AREA_RENDER_ORDER_BASE + 1, AREA_RENDER_ORDER_BASE + 2, AREA_RENDER_ORDER_BASE + 3]);
  check('…which is the ladder ground.ts really builds',
    AREA_ORDER_RE.test(groundSrc), true);
  check('the base plate stays where it was (it is opaque; the pass ignores it)',
    /mesh\.renderOrder = 0;/.test(groundSrc), true);
  check('the alpha is the LAST thing the stage does, after the colour clamp',
    drapeEdge.shader.fragmentShader.indexOf('diffuseColor.rgb = clamp(')
      < drapeEdge.shader.fragmentShader.indexOf('diffuseColor.a *='), true);
  check('…and the colour work never touches alpha',
    drapeEdge.shader.fragmentShader.split('diffuseColor.a').length - 1, 1);

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

  const shifted = await loadClient(dropTheHalfTexel);
  const shiftedMat = new THREE.MeshStandardMaterial({});
  shifted.applyNaturalGround(shiftedMat);
  const shiftedShader = stubShader();
  shiftedMat.onBeforeCompile(shiftedShader, null);
  check('without the half texel the mapping is not the one the maths describes',
    marksIn(shiftedShader, NG_MARKS).length, NG_MARKS.length - 1);
  check('…and it is exactly the mapping line that is missing',
    shiftedShader.fragmentShader
      .includes('return ( ( p - uNgField.xy ) / uNgField.z + 0.5 ) / uNgFieldSize;'), false);
  check('…while the truth writes it, once, for both readers',
    [meadow.shader.fragmentShader.split('+ 0.5 ) / uNgFieldSize').length - 1,
      meadow.shader.fragmentShader.split('ngFieldUvOf(').length - 1], [1, 3]);

  const coarseOnly = await loadMath(refineNothing);
  check('without the refinement the middle of a coarse area reads EDGE and fades away',
    [sampleBand(coarseOnly.ngRefineEdgeBand(coarse, null, square), 5, 5),
      coarseOnly.ngEdgeAlpha(0)], [0, 0]);
  check('…while the truth carries the ground through, opaque',
    [sampleBand(band, 5, 5) >= M.NG_EDGE_OPAQUE_M, M.ngEdgeAlpha(sampleBand(band, 5, 5))],
    [true, 1]);

  const hard = await loadClient(dropTheFringe);
  const hardMat = new THREE.MeshStandardMaterial({});
  hard.applyNaturalGround(hardMat, true);
  const hardShader = stubShader();
  hardMat.onBeforeCompile(hardShader, null);
  check('without the alpha line the area ends on a drawn line again',
    hardShader.fragmentShader.includes('diffuseColor.a'), false);
  check('…while everything else about it is untouched (the probe measures the fringe)',
    marksIn(hardShader, NG_MARKS).length, NG_MARKS.length - 1);

  // [8i] THE OLD LADDER. Before the fringe the drapes were opaque and the
  // opaque pass drew them before every overlay in the world; transparent, the
  // natural 1, 2, 3 puts them AFTER everything that leaves its render order at
  // 0 — and those overlays write no depth, so the drape's opaque core paints
  // over them. The mutant is the line as it read then.
  const oldLadder = groundSrc.replace(
    'mesh.renderOrder = AREA_RENDER_ORDER_BASE + index + 1;',
    'mesh.renderOrder = index + 1;');
  check('the old ladder is really a different line', oldLadder === groundSrc, false);
  check('…and it would put the painted ground OVER the default-0 overlays',
    [AREA_ORDER_RE.test(oldLadder), /mesh\.renderOrder = index \+ 1;/.test(oldLadder)],
    [false, true]);
  check('…while the truth starts the ladder in front of them',
    [AREA_ORDER_RE.test(groundSrc), AREA_RENDER_ORDER_BASE + 1 < 0], [true, true]);

  let printed = 'loaded';
  try {
    await loadClient(unprintableConstant);
  } catch (e) {
    printed = /does not survive two decimals/.test(String(e?.message ?? e))
      ? 'refused at load' : `threw something else: ${e}`;
  }
  check('a constant two decimals cannot print stops the module at LOAD',
    printed, 'refused at load');

  console.log(`\n${passed} ok, ${failed} failed`);
  process.exit(failed ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
