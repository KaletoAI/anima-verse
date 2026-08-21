#!/usr/bin/env node
/**
 * Smoke check for the SHADER PATCHES on a ground material — the two writers of
 * the one `onBeforeCompile` slot (§ B5a: strings and numbers, no screenshots).
 *
 * Usage:  node client3d/scripts/smoke_surface_patch.mjs
 *         (transpiles the shared material module, bundles the client's ground
 *          module; needs three)
 *
 * ===========================================================================
 * WHY THIS FILE EXISTS
 * ===========================================================================
 * A painted water area never moved. The chain was right up to the last line:
 * `materialFor` (client3d/src/scene/ground.ts) builds the material through
 * `surfaceMaterial` (@anima/scene-render `materials.ts`), which for class
 * `water`/`ice` installs the ripple/tint/roughness/fresnel patch in
 * `mat.onBeforeCompile` and claims the cache key 'anima-water' — and the very
 * next line, `patchHole(mat)`, ASSIGNED its own callback into the same slot and
 * its own key over the same field. One slot, two writers, last one wins: the
 * water shader was built and thrown away one line later. Water therefore
 * rippled everywhere else (scene floors, tile plates, both admin previews) and
 * only the painted world areas lay dead still.
 *
 * The fix CHAINS: `patchHole` keeps the callback it finds, runs it first, and
 * combines the cache keys. This check is the proof, and it runs without a GPU:
 * the patches are handed a STUB SHADER whose vertex/fragment strings carry the
 * REAL `#include` anchors of three's `meshphysical` shader, and the resulting
 * strings are read.
 *
 * THE ANCHORS (all of them `#include` LINES, because `onBeforeCompile` sees the
 * shader BEFORE three resolves its includes — materials.ts:163-167 and the
 * hole patch in ground.ts):
 *   vertex    `#include <begin_vertex>`   water: world position + tile uv
 *             `#include <project_vertex>` hole:  world position of the fragment
 *   fragment  `#include <clipping_planes_fragment>` hole: the discard test
 *             `#include <map_fragment>`            water: tint mix
 *             `#include <roughnessmap_fragment>`   water: roughness mask
 *             `#include <normal_fragment_maps>`    water: the two scrolling
 *                                                  normal layers — REPLACED,
 *                                                  not appended to
 *             `#include <opaque_fragment>`         water: the sky fresnel
 * The stub lists them in three's own order (meshphysical.glsl.js: clipping,
 * map, roughnessmap, normal_fragment_maps, … opaque_fragment).
 *
 * ---------------------------------------------------------------------------
 * [1] A PAINTED WATER AREA — both patch families in ONE composed shader
 * ---------------------------------------------------------------------------
 * Built exactly as `materialFor` builds it: `surfaceMaterial(class water)` and
 * then `patchHole`. Hand expectations, each one a line the patches write:
 *   water   vertex   `varying vec2 vWaterWorld;` + the assignment after
 *                    `begin_vertex`
 *           fragment `wDriftA` (the drift of the ripple), the tint mix
 *                    `diffuseColor.rgb = mix( uTint`, the roughness mask
 *                    `roughnessFactor = mix( 0.85`, the fresnel `wFres`
 *           uniforms uTime, uSky, uWaveM, uSpeed, uSkyMix, uTint,
 *                    uMapStrength, uMask
 *           and `#include <normal_fragment_maps>` is GONE — that anchor is
 *           replaced, and a chain that ran the hole patch on the untouched
 *           shader would leave it standing.
 *   hole    vertex   `varying vec3 vHoleWorld;` + the assignment after
 *                    `project_vertex`
 *           fragment `uniform vec4 uHole;` and the `uHoleOn > 0.5 … discard`
 *                    test, and it stands BEFORE the clipping include (the
 *                    fragment is dropped before anything else is computed)
 *           uniforms uHole, uHoleOn
 *   key     'anima-water+ground-hole' — different from BOTH singles, so three
 *           compiles one program for rippling ground and one for matte ground
 *           instead of confusing the two.
 * `ice` is the same material with a still clock (materials.ts) and is checked
 * to chain identically — a frozen lake is a water surface that does not flow.
 *
 * ---------------------------------------------------------------------------
 * [2] A PAINTED MATTE AREA — only the hole patch, nothing else
 * ---------------------------------------------------------------------------
 * The default class writes no callback at all, so the chain must add nothing:
 * hole markers present, every water marker absent, `normal_fragment_maps`
 * still standing, and the key exactly 'ground-hole' — the string a meadow
 * carried before this change, unchanged.
 *
 * ---------------------------------------------------------------------------
 * [3] THE SHARED CLOCK — the ripple actually moves
 * ---------------------------------------------------------------------------
 * `uTime` is ONE object for every water surface (materials.ts), advanced once
 * per frame by `updateSurfaceMaterials` (client3d `engine.ts`). Two separate
 * painted areas must therefore hand the SAME uniform object into their shaders,
 * and a tick of 0.5 s must show up in both: value 0.5 after one call, 1.25
 * after a second of 0.75. Without this the chained patch would install a
 * ripple that never advances — animated in the source and still on screen.
 * `setSurfaceSky(0x000000)` likewise reaches the composed shader's `uSky`.
 *
 * ---------------------------------------------------------------------------
 * [4] EVERY OTHER CALLER IS UNTOUCHED
 * ---------------------------------------------------------------------------
 * The chain lives in `patchHole`, i.e. in the client's ground module alone.
 * A water material that never goes through it (scene floors, tile plates,
 * FloorPlanPreview, SurfaceMaterialPreview) keeps the key 'anima-water', its
 * water markers and NO hole markers — the admin previews cannot notice this
 * change at all.
 *
 * ---------------------------------------------------------------------------
 * [5] PATCHING TWICE IS STILL ONE PATCH
 * ---------------------------------------------------------------------------
 * The assignment was idempotent by accident; a chain is not. `patchHole` keeps
 * a set of the materials it has seen, so a second call changes nothing:
 * `varying vec3 vHoleWorld;` appears ONCE (twice would not compile) and the
 * key does not grow a second '+ground-hole'.
 *
 * ---------------------------------------------------------------------------
 * [6] THE RED COUNTER-CHECK — the pre-fix assignment, provably worse
 * ---------------------------------------------------------------------------
 * The module is bundled a SECOND time from a mutated source: the line that
 * calls the previous callback is deleted and the combined key falls back to
 * the plain one — that IS the code as it stood, expressed as a mutation. Fed
 * the same water material, the mutant's composed shader contains NOT ONE of
 * the water markers and answers 'ground-hole', while its hole markers are all
 * still there (so the probe measures the loss of the chain, not a broken
 * module). Every water marker is pinned from both sides: absent in the mutant,
 * present in the truth.
 *
 * ---------------------------------------------------------------------------
 * [7] THE COMPOSITION IN `materialFor`, pinned by reading the source
 * ---------------------------------------------------------------------------
 * `materialFor` builds inside a closure over a fetched payload and cannot be
 * called here, so the one thing this file assumes about it — `surfaceMaterial`
 * first, `patchHole` on the very material it returned — is pinned against the
 * source text. Without it the checks above would keep passing while the ground
 * quietly stopped patching at all.
 *
 * ===========================================================================
 * THE SECOND SUBJECT: THE WIND (terrain animations, task 2)
 * ===========================================================================
 * `applySway` bends what grows on a ground: a terrain kind names `meta.sway_m`
 * (§ A9) and every scatter material of an area of that kind gets a vertex
 * displacement at the very anchor the water patch uses. It is a THIRD writer
 * of the one slot, and it is held to the rule the hole patch had to learn.
 *
 * ---------------------------------------------------------------------------
 * [8] THE SWAY TERM ITSELF — at the real anchor, with the real formula
 * ---------------------------------------------------------------------------
 * Hand expectations, each one a line the patch writes into the VERTEX shader:
 *   `uniform float uTime;` + `uniform float uSwayRef;` (the clock is shared,
 *   the reference height is per material — a tuft and a tree must not split
 *   the compiled programs over their size)
 *   `pow( max( transformed.y, 0.0 ) / uSwayRef, 2.0 )` — quadratic in the
 *   height above the ground: the foot stands, the tip carries all of it
 *   `sin( uTime * 1.70 + swayPhase )` — the shared clock, one fixed frequency
 *   the phase out of `instanceMatrix[ 3 ].xz`, the instance's own position:
 *   no second attribute, and it survives every tier swap because the matrices
 *   are written once
 *   and the term stands AFTER `#include <begin_vertex>`, which is still there
 *   (appended, not replaced — `transformed` has to exist first).
 * The amplitude is a GLSL LITERAL, quantised to two decimals, and the cache
 * key carries it: 0.06 and 0.0649 are one program, 0.04 is another, 9 is the
 * clamp 0.50 — one program per authored value, never one per mesh. A kind
 * that says nothing (0) writes nothing at all and claims no key.
 *
 * ---------------------------------------------------------------------------
 * [8b] THE INSTANCE SCALE — `sway_m` is METRES, whatever an instance is scaled to
 * ---------------------------------------------------------------------------
 * § A9 promises that `sway_m` IS the maximum deflection of a blade's TIP. The
 * displacement is written into `transformed`, which is still in OBJECT
 * coordinates, so the instance matrix multiplies it afterwards — and since the
 * automatic undergrowth scales every tuft to its own height, that multiplier
 * is no longer 1 for everybody:
 *
 *   the layer's geometry stands (0.4 + 0.7)/2 = 0.55 m tall
 *   a 0.7 m blade is therefore scaled by 0.7 / 0.55 = 1.2727…
 *   with sway_m = 0.06 its tip moved 0.06 · 1.2727… = 0.0764 m
 *
 * — 27 % more than the number the catalog names, and a 0.4 m blade moved 27 %
 * less. So the instanced branch divides the direction by the instance's own
 * uniform scale, read off the length of the matrix's FIRST COLUMN:
 *
 *   `normalize( … ) / max( length( instanceMatrix[ 0 ].xyz ), 1e-6 )`
 *
 * The divisor is exactly 1 for every unscaled user — the authored scatter,
 * whose instances carry rotation and translation only — so nothing that waved
 * before this line existed moves differently now, which is why the displacement
 * line itself is byte-for-byte the one section [8] checks. The NON-instanced
 * branch has no divisor at all: there is one prop, and its own scale is the
 * mesh's own business.
 *
 * The red counter-check is the formula as it stood: the mutant drops the
 * divisor, and its shader then names no `instanceMatrix[ 0 ]` at all while
 * everything else about the bend is intact.
 *
 * ---------------------------------------------------------------------------
 * [9] THE CHAIN AGAIN — three writers, one slot
 * ---------------------------------------------------------------------------
 * The rule inherited from the hole patch: every further patch CHAINS. Water,
 * hole and sway on ONE material must all be present and the key must be
 * 'anima-water+ground-hole+ground-sway@0.06' — the three of them in the order
 * they were applied. Patching twice is still one patch (the WeakSet guard),
 * or the shader would declare `swayUp` twice and not compile.
 *
 * ---------------------------------------------------------------------------
 * [10] THE SHARED CLOCK, for the wind too
 * ---------------------------------------------------------------------------
 * The sway hangs on `surfaceTimeUniform` of @anima/scene-render — the very
 * object `updateSurfaceMaterials` advances once per frame (client3d
 * `engine.ts`). Two swaying areas therefore hand the SAME object into their
 * shaders and one tick moves both. Read through the GROUND BUNDLE's own
 * import, because the bundle carries its own instance of the shared module
 * (that is what `external: ['three']` leaves in); the water sections above
 * measure the separately transpiled copy, and comparing the two would only
 * measure the bundler.
 *
 * ---------------------------------------------------------------------------
 * [11] THE RED COUNTER-CHECKS — two mutants, two losses
 * ---------------------------------------------------------------------------
 * (a) THE PHASE HASH REMOVED. With the instance position out of the phase
 *     every blade of a field starts in the same place of the same wave — a
 *     meadow marching in lockstep, which no screenshot would ever be trusted
 *     to tell. The mutant replaces the hash by `0.0`: its composed shader then
 *     names neither `instanceMatrix` nor `fract( sin(`, while the truth names
 *     both. Pinned from both sides, so a renamed local cannot make it vacuous.
 * (b) ASSIGNMENT INSTEAD OF CHAIN, in `applySway` this time. The predecessor
 *     is dropped: a material that carried the hole patch loses every hole line
 *     while the sway lines stay — the probe measures the chain, not a broken
 *     module. This is the mutation the review of task 1 declared binding for
 *     every further patch on these materials.
 *
 * ===========================================================================
 * THE THIRD SUBJECT: WHICH SURFACE A GROUND WEARS (2026-08-16)
 * ===========================================================================
 *
 * ---------------------------------------------------------------------------
 * [13] THE FIELD, NEVER THE NAME — `surfaceOfType` and the chain around it
 * ---------------------------------------------------------------------------
 * The library used to be asked for an entry called exactly like the terrain
 * kind (`surfaceFor(area.kind, 'wall')`), so `grass` wore `grass` because of
 * the spelling. The server ships the assignment now (`types[].surface`,
 * § A1.5) and the name match is gone WITHOUT a fallback. `surfaceOfType` is
 * that reading, pure and exported, so it can be checked by value instead of
 * by regex:
 *   {kind:'grass', surface:'deep_forest'} -> 'deep_forest'   the field wins
 *   {surface:'  Deep_Forest '}            -> 'deep_forest'   id shape
 *   {kind:'grass'}                        -> ''              THE RED ONE
 *   {kind:'grass', surface:'   '}         -> ''
 *   undefined / null                      -> ''
 * The third line is the counter-check of the whole change: `grass` IS an id
 * the library holds, and a fallback to `kind` would answer 'grass' here.
 *
 * The rest of the chain lives in the closure and is pinned against the source
 * the way [7] pins the composition: `materialFor` resolves `surfaceOf(kind)`
 * first and asks the library about THAT id (texture and material class), the
 * fringe question does the same, the preload loads the named surfaces — and
 * NO library call in the module names a terrain kind any more, which is the
 * one assertion that catches a half-migrated caller.
 */
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');
const MATERIALS_SRC = join(ROOT, 'packages/scene-render/src/materials.ts');
const GROUND_SRC = join(ROOT, 'client3d/src/scene/ground.ts');

// ── The canvas the shared module draws its wave normal map on ──────────────
// `materials.ts` generates its textures procedurally (no asset, no download),
// and that is the only DOM it touches. A 256 x 256 buffer of zeros is enough:
// nothing here reads a pixel, the patches under test read STRINGS.
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

/** `materials.ts` has no runtime import (only `import type`), so a plain
 *  transpile loads it — the same rule as `smoke_scatter_math.mjs`. Should
 *  someone add a real import, this fails loudly, and that is the alarm. */
async function loadMaterials() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'surfacepatch-'));
  try {
    const out = esbuild.transformSync(await readFile(MATERIALS_SRC, 'utf8'),
      { loader: 'ts', format: 'esm' });
    const file = join(dir, 'materials.mjs');
    await writeFile(file, out.code, 'utf8');
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

/**
 * Bundle the client's ground module and import it. Inside the repo on purpose:
 * node resolves `three` upwards from the file, so bundle and script share ONE
 * three — `external` keeps it out of the bundle for exactly that reason
 * (`smoke_clip_ground.mjs` does the same). `ground.ts` reaches the DOM and the
 * network only inside functions, so it loads here.
 *
 * `mutate` rewrites the BUILT text before the import — that is how section [6]
 * gets the pre-fix module to compare against, without a second copy of the
 * patch lying around to rot.
 */
async function loadGround(mutate) {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(ROOT, 'client3d/scripts/.smoke-'));
  try {
    // The shared module is re-exported THROUGH the bundle on purpose: the
    // bundle carries its own instance of it, and the sway's clock has to be
    // measured on the instance the sway actually writes (section [10]).
    const entry = `export { patchHole, HOLE_CACHE_KEY, applySway, swayCacheKey, surfaceOfType } from '${GROUND_SRC}';\n`
      + "export { updateSurfaceMaterials, surfaceTimeUniform } from '@anima/scene-render';\n";
    const built = await esbuild.build({
      stdin: { contents: entry, resolveDir: dir, loader: 'ts' },
      bundle: true, platform: 'node', format: 'esm', write: false,
      outfile: join(dir, 'ground.mjs'), external: ['three', 'three/*'],
    });
    const text = built.outputFiles[0].text;
    const source = mutate ? mutate(text) : text;
    const file = join(dir, 'ground.mjs');
    await writeFile(file, source, 'utf8');
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

/** Section [6]'s mutant: `patchHole` as it stood — it ASSIGNS instead of
 *  chaining (the previous callback is never called) and claims the bare key.
 *  Both edits are asserted to bite; a mutation that changed nothing would make
 *  the counter-check vacuous.
 *
 *  ANCHORED on the line that follows, because there are two chained patches in
 *  this module now and a bare `prev.call(…)` would hit whichever esbuild
 *  printed first. */
function assignInsteadOfChain(text) {
  const chained = /prev\.call\(mat, shader, renderer\);(\s*)shader\.uniforms\.uHole =/;
  if (!chained.test(text)) throw new Error('the hole patch no longer chains here');
  let out = text.replace(chained, 'shader.uniforms.uHole =');
  const keyed = out.replace('prevKey ? ', 'false ? ');
  if (keyed === out) throw new Error('the mutant did not drop the combined key');
  out = keyed;
  return out;
}

/** Section [11a]'s mutant: the phase hash gone, so every instance rides the
 *  same wave at the same moment. */
function phaseInSync(text) {
  const hash = /fract\( sin\( dot\( instanceMatrix\[ 3 \]\.xz[^\n]*/;
  if (!hash.test(text)) throw new Error('the phase hash is no longer where the probe looks');
  return text.replace(hash, '0.0;');
}

/** Section [8b]'s mutant: the amplitude is no longer divided by the instance's
 *  own scale — the formula as it stood, under which a tuft scaled to 1.27 of
 *  its geometry deflected 1.27 · sway_m. */
function swayIgnoresInstanceScale(text) {
  const divisor = ' / max( length( instanceMatrix[ 0 ].xyz ), 1e-6 )';
  if (!text.includes(divisor)) {
    throw new Error('the sway no longer divides by the instance scale');
  }
  return text.split(divisor).join('');
}

/** Section [11b]'s mutant: `applySway` ASSIGNS instead of chaining — same
 *  anchoring trick, this time on the sway's own first uniform. */
function swayAssignInsteadOfChain(text) {
  const chained = /prev\.call\(mat, shader, renderer\);(\s*)shader\.uniforms\.uTime =/;
  if (!chained.test(text)) throw new Error('the sway patch no longer chains here');
  return text.replace(chained, 'shader.uniforms.uTime =');
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
      '\t#include <roughnessmap_fragment>',
      '\t#include <normal_fragment_maps>',
      '\t#include <opaque_fragment>',
      '}',
    ].join('\n'),
  };
}

/** The lines each patch family writes — one list, used for "present" in [1]
 *  and for "absent" in [2] and [6], so the two sides can never drift apart. */
const WATER_MARKS = [
  ['vert', 'varying vec2 vWaterWorld;'],
  ['vert', 'vWaterWorld = ( modelMatrix * vec4( transformed, 1.0 ) ).xz;'],
  ['frag', 'uniform float uTime;'],
  ['frag', 'float wDriftA = uTime * uSpeed / uWaveM;'],
  ['frag', 'diffuseColor.rgb = mix( uTint'],
  ['frag', 'roughnessFactor = mix( 0.85'],
  ['frag', 'float wFres = pow('],
];
const HOLE_MARKS = [
  ['vert', 'varying vec3 vHoleWorld;'],
  ['vert', 'vHoleWorld = ( modelMatrix * vec4( transformed, 1.0 ) ).xyz;'],
  ['frag', 'uniform vec4 uHole;'],
  ['frag', 'uHoleOn > 0.5'],
  ['frag', 'discard;'],
];
const WATER_UNIFORMS = ['uTime', 'uSky', 'uWaveM', 'uSpeed', 'uSkyMix', 'uTint',
  'uMapStrength', 'uMask'];
const HOLE_UNIFORMS = ['uHole', 'uHoleOn'];
/** What the sway writes — all of it in the VERTEX shader, where `transformed`
 *  lives. The amplitude is a literal, so the list is a function of it. */
const swayMarks = (amp) => [
  ['vert', 'uniform float uTime;'],
  ['vert', 'uniform float uSwayRef;'],
  ['vert', 'float swayUp = pow( max( transformed.y, 0.0 ) / uSwayRef, 2.0 );'],
  ['vert', `transformed.xz += ${amp} * swayUp * sin( uTime * 1.70 + swayPhase ) * swayDir.xz;`],
];
const SWAY_MARKS = swayMarks('0.06');
/** The phase, checked on its own: section [11a] takes exactly this away. */
const PHASE_MARKS = [
  ['vert', 'instanceMatrix[ 3 ].xz'],
  ['vert', 'fract( sin( dot('],
];
const SWAY_UNIFORMS = ['uTime', 'uSwayRef'];

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

async function main() {
  const THREE = await import('three');
  const { surfaceMaterial, updateSurfaceMaterials, setSurfaceSky } = await loadMaterials();
  const { patchHole, HOLE_CACHE_KEY, applySway, swayCacheKey, surfaceOfType,
    updateSurfaceMaterials: tickSurfaces, surfaceTimeUniform } = await loadGround();

  /** One painted area's material, built the way `materialFor` builds it. */
  function groundMaterial(spec, patch = patchHole) {
    const mat = surfaceMaterial(THREE, { material: spec, color: 0x336699 });
    patch(mat);
    const shader = stubShader();
    mat.onBeforeCompile(shader, null);
    return { mat, shader };
  }

  console.log('\n[1] a painted WATER area — both patch families in one shader');
  const water = groundMaterial({ class: 'water', tint: '#3f7fb8' });
  check('every water line survives the hole patch',
    marksIn(water.shader, WATER_MARKS), allOf(WATER_MARKS));
  check('…and every hole line is there as well',
    marksIn(water.shader, HOLE_MARKS), allOf(HOLE_MARKS));
  check('the water uniforms are bound',
    WATER_UNIFORMS.filter((u) => water.shader.uniforms[u] !== undefined), WATER_UNIFORMS);
  check('…and the hole uniforms too',
    HOLE_UNIFORMS.filter((u) => water.shader.uniforms[u] !== undefined), HOLE_UNIFORMS);
  check('the normal-map anchor is REPLACED, not appended to',
    water.shader.fragmentShader.includes('#include <normal_fragment_maps>'), false);
  check('the discard stands before the clipping include',
    water.shader.fragmentShader.indexOf('uHoleOn > 0.5')
      < water.shader.fragmentShader.indexOf('#include <clipping_planes_fragment>'), true);
  check('the cache key is the COMBINED one',
    water.mat.customProgramCacheKey(), `anima-water+${HOLE_CACHE_KEY}`);
  check('…which is neither of the two singles',
    ['anima-water', HOLE_CACHE_KEY].includes(water.mat.customProgramCacheKey()), false);
  check('…and it is stable across calls',
    water.mat.customProgramCacheKey(), water.mat.customProgramCacheKey());
  const ice = groundMaterial({ class: 'ice', tint: '#cfe6ff' });
  check('a frozen lake chains exactly the same way',
    marksIn(ice.shader, WATER_MARKS).length + marksIn(ice.shader, HOLE_MARKS).length,
    WATER_MARKS.length + HOLE_MARKS.length);
  check('…with the same combined key',
    ice.mat.customProgramCacheKey(), `anima-water+${HOLE_CACHE_KEY}`);

  console.log('\n[2] a painted MATTE area — only the hole patch');
  const meadow = groundMaterial(null);
  check('no water line is written', marksIn(meadow.shader, WATER_MARKS), []);
  check('the hole lines are all there',
    marksIn(meadow.shader, HOLE_MARKS), allOf(HOLE_MARKS));
  check('no water uniform is bound',
    WATER_UNIFORMS.filter((u) => meadow.shader.uniforms[u] !== undefined), []);
  check('the normal-map anchor stands untouched',
    meadow.shader.fragmentShader.includes('#include <normal_fragment_maps>'), true);
  check('the key is the plain one a meadow always had',
    meadow.mat.customProgramCacheKey(), HOLE_CACHE_KEY);
  const gloss = groundMaterial({ class: 'gloss' });
  check('a glossy kind is no water either — plain key',
    gloss.mat.customProgramCacheKey(), HOLE_CACHE_KEY);
  check('…and writes no water line', marksIn(gloss.shader, WATER_MARKS), []);

  console.log('\n[3] the shared clock — the ripple really advances');
  const lake = groundMaterial({ class: 'water' });
  check('two painted areas share ONE time uniform',
    water.shader.uniforms.uTime === lake.shader.uniforms.uTime, true);
  updateSurfaceMaterials(0.5);
  check('a 0.5 s frame moves the clock in the composed shader',
    lake.shader.uniforms.uTime.value, 0.5);
  updateSurfaceMaterials(0.75);
  check('…and the next frame adds to it', water.shader.uniforms.uTime.value, 1.25);
  setSurfaceSky(0x000000);
  check('the night sky reaches the painted water',
    lake.shader.uniforms.uSky.value, { r: 0, g: 0, b: 0 });

  console.log('\n[4] every other surfaceMaterial caller is untouched');
  const scene = groundMaterial({ class: 'water' }, () => {});
  check('a floor that never meets patchHole keeps the water key',
    scene.mat.customProgramCacheKey(), 'anima-water');
  check('…keeps its water lines',
    marksIn(scene.shader, WATER_MARKS), allOf(WATER_MARKS));
  check('…and carries no hole at all', marksIn(scene.shader, HOLE_MARKS), []);
  check('…nor a hole uniform',
    HOLE_UNIFORMS.filter((u) => scene.shader.uniforms[u] !== undefined), []);

  console.log('\n[5] patching twice is still one patch');
  const twice = surfaceMaterial(THREE, { material: { class: 'water' }, color: 0x336699 });
  patchHole(twice);
  patchHole(twice);
  const twiceShader = stubShader();
  twice.onBeforeCompile(twiceShader, null);
  check('the hole varying is declared exactly once',
    twiceShader.vertexShader.split('varying vec3 vHoleWorld;').length - 1, 1);
  check('the key did not grow a second hole',
    twice.customProgramCacheKey(), `anima-water+${HOLE_CACHE_KEY}`);

  console.log('\n[6] the RED counter-check — the pre-fix assignment');
  const old = await loadGround(assignInsteadOfChain);
  const redMat = surfaceMaterial(THREE, { material: { class: 'water', tint: '#3f7fb8' } });
  old.patchHole(redMat);
  const redShader = stubShader();
  redMat.onBeforeCompile(redShader, null);
  check('the assignment mutant loses EVERY water line',
    marksIn(redShader, WATER_MARKS), []);
  check('…and every water uniform with them',
    WATER_UNIFORMS.filter((u) => redShader.uniforms[u] !== undefined), []);
  check('…it answers the bare hole key', redMat.customProgramCacheKey(), HOLE_CACHE_KEY);
  check('…while its hole patch is fully intact (the probe measures the chain)',
    marksIn(redShader, HOLE_MARKS), allOf(HOLE_MARKS));
  // The other side of the same coin: what the mutant lost, the truth has.
  check('the chained patch does NOT answer the bare hole key',
    water.mat.customProgramCacheKey() === HOLE_CACHE_KEY, false);
  check('…and does NOT lose the water lines',
    marksIn(water.shader, WATER_MARKS).length, WATER_MARKS.length);

  console.log('\n[7] the composition in materialFor, pinned by reading the source');
  const groundSrc = await readFile(GROUND_SRC, 'utf8');
  check('materialFor builds through surfaceMaterial…',
    /const mat = surfaceMaterial\(THREE, \{ material: spec,/.test(groundSrc), true);
  check('…and hands that very material to patchHole',
    /\n\s*patchHole\(mat\);\n/.test(groundSrc), true);

  // ── THE WIND ─────────────────────────────────────────────────────────────
  /** One scatter material of a swaying kind: a plain standard material, the
   *  way a tuft and a cloned prop material both arrive at `applySway`. */
  function swayMaterial(swayM, refH, patch = applySway) {
    const mat = new THREE.MeshStandardMaterial({ color: 0x6a994e });
    patch(mat, swayM, refH);
    const shader = stubShader();
    mat.onBeforeCompile(shader, null);
    return { mat, shader };
  }

  console.log('\n[8] the sway term — at the real anchor, with the real formula');
  const grass = swayMaterial(0.06, 0.8);
  check('every sway line is written', marksIn(grass.shader, SWAY_MARKS),
    allOf(SWAY_MARKS));
  check('…the phase comes out of the instance position',
    marksIn(grass.shader, PHASE_MARKS), allOf(PHASE_MARKS));
  check('…the clock and the reference height are bound',
    SWAY_UNIFORMS.filter((u) => grass.shader.uniforms[u] !== undefined),
    SWAY_UNIFORMS);
  check('…the reference height is the prop\'s own',
    grass.shader.uniforms.uSwayRef.value, 0.8);
  check('the anchor is APPENDED to, not replaced',
    grass.shader.vertexShader.includes('#include <begin_vertex>'), true);
  check('…and the bend stands after it (transformed exists first)',
    grass.shader.vertexShader.indexOf('#include <begin_vertex>')
      < grass.shader.vertexShader.indexOf('float swayUp ='), true);
  check('nothing of it lands in the fragment shader',
    grass.shader.fragmentShader.includes('swayUp'), false);
  check('the key carries the amplitude', grass.mat.customProgramCacheKey(),
    'ground-sway@0.06');
  check('…which is what swayCacheKey says', swayCacheKey(0.06),
    grass.mat.customProgramCacheKey());
  const rounded = swayMaterial(0.0649, 1.2);
  check('two decimals: 0.0649 is the SAME program as 0.06',
    rounded.mat.customProgramCacheKey(), grass.mat.customProgramCacheKey());
  check('…and writes the same literal', marksIn(rounded.shader, SWAY_MARKS),
    allOf(SWAY_MARKS));
  check('…while its own reference height still differs',
    rounded.shader.uniforms.uSwayRef.value, 1.2);
  const wood = swayMaterial(0.04, 8);
  check('a gentler kind is its own program',
    wood.mat.customProgramCacheKey(), 'ground-sway@0.04');
  check('…with its own literal in the shader',
    marksIn(wood.shader, swayMarks('0.04')), allOf(swayMarks('0.04')));
  const shorn = swayMaterial(9, 0.8);
  check('a deflection that would shear the meadow is clamped',
    shorn.mat.customProgramCacheKey(), 'ground-sway@0.50');
  const stillMat = new THREE.MeshStandardMaterial({ color: 0x6a994e });
  applySway(stillMat, 0, 0.8);
  const stillShader = stubShader();
  stillMat.onBeforeCompile(stillShader, null);
  check('a kind that says nothing writes nothing',
    marksIn(stillShader, SWAY_MARKS), []);
  check('…and claims no cache key of its own',
    Object.prototype.hasOwnProperty.call(stillMat, 'customProgramCacheKey'), false);

  console.log('\n[8b] the instance scale — sway_m stays metres however tall the blade');
  const SCALED = 'normalize( ( vec4( 0.8, 0.0, 0.6, 0.0 ) * instanceMatrix ).xyz )'
    + ' / max( length( instanceMatrix[ 0 ].xyz ), 1e-6 )';
  check('the instanced branch divides by the instance\'s own scale',
    grass.shader.vertexShader.includes(SCALED), true);
  check('…while the lone prop has no divisor',
    grass.shader.vertexShader.includes('vec3 swayDir = vec3( 0.8, 0.0, 0.6 );'), true);
  check('…and the displacement line itself is untouched (the unscaled user is 1)',
    marksIn(grass.shader, SWAY_MARKS), allOf(SWAY_MARKS));
  const unscaled = await loadGround(swayIgnoresInstanceScale);
  const undergrown = new THREE.MeshStandardMaterial({ color: 0x6a994e });
  unscaled.applySway(undergrown, 0.06, 0.55);
  const undergrownShader = stubShader();
  undergrown.onBeforeCompile(undergrownShader, null);
  check('the "no divisor" mutant lets the instance scale eat the metres',
    undergrownShader.vertexShader.includes('instanceMatrix[ 0 ]'), false);
  check('…while its bend is otherwise intact (the probe measures the divisor)',
    marksIn(undergrownShader, SWAY_MARKS), allOf(SWAY_MARKS));

  console.log('\n[9] the chain again — water, hole and wind in one shader');
  const all = surfaceMaterial(THREE, { material: { class: 'water' }, color: 0x336699 });
  patchHole(all);
  applySway(all, 0.06, 0.8);
  const allShader = stubShader();
  all.onBeforeCompile(allShader, null);
  check('the water lines survive two more patches',
    marksIn(allShader, WATER_MARKS), allOf(WATER_MARKS));
  check('…the hole lines survive the sway',
    marksIn(allShader, HOLE_MARKS), allOf(HOLE_MARKS));
  check('…and the sway lines are there too',
    marksIn(allShader, SWAY_MARKS), allOf(SWAY_MARKS));
  check('the key is all three, in the order they were applied',
    all.customProgramCacheKey(), `anima-water+${HOLE_CACHE_KEY}+ground-sway@0.06`);
  applySway(all, 0.06, 0.8);
  const twiceSway = stubShader();
  all.onBeforeCompile(twiceSway, null);
  check('patching the sway twice is still one patch',
    twiceSway.vertexShader.split('float swayUp =').length - 1, 1);
  check('…and the key did not grow a second wind',
    all.customProgramCacheKey(), `anima-water+${HOLE_CACHE_KEY}+ground-sway@0.06`);

  console.log('\n[10] the shared clock — the wind really advances');
  check('two swaying areas share ONE time uniform',
    grass.shader.uniforms.uTime === wood.shader.uniforms.uTime, true);
  check('…and it is the module\'s own surface clock',
    grass.shader.uniforms.uTime === surfaceTimeUniform, true);
  const before = surfaceTimeUniform.value;
  tickSurfaces(0.5);
  check('a 0.5 s frame moves the clock in the composed shader',
    Math.round((wood.shader.uniforms.uTime.value - before) * 1000) / 1000, 0.5);
  tickSurfaces(0.75);
  check('…and the next frame adds to it',
    Math.round((grass.shader.uniforms.uTime.value - before) * 1000) / 1000, 1.25);

  console.log('\n[11] the RED counter-checks — the phase, and the chain again');
  const synced = await loadGround(phaseInSync);
  const syncMat = new THREE.MeshStandardMaterial({ color: 0x6a994e });
  synced.applySway(syncMat, 0.06, 0.8);
  const syncShader = stubShader();
  syncMat.onBeforeCompile(syncShader, null);
  check('without the hash no instance knows where it stands',
    marksIn(syncShader, PHASE_MARKS), []);
  check('…while the bend itself is untouched (the probe measures the phase)',
    marksIn(syncShader, SWAY_MARKS), allOf(SWAY_MARKS));
  check('the truth, from the other side, DOES spread the phase',
    marksIn(grass.shader, PHASE_MARKS).length, PHASE_MARKS.length);

  const flat = await loadGround(swayAssignInsteadOfChain);
  const redSway = new THREE.MeshStandardMaterial({ color: 0x6a994e });
  flat.patchHole(redSway);
  flat.applySway(redSway, 0.06, 0.8);
  const redSwayShader = stubShader();
  redSway.onBeforeCompile(redSwayShader, null);
  check('the assignment mutant loses the patch it found',
    marksIn(redSwayShader, HOLE_MARKS), []);
  check('…and its own hole uniforms with it',
    HOLE_UNIFORMS.filter((u) => redSwayShader.uniforms[u] !== undefined), []);
  check('…while its sway is fully intact (the probe measures the chain)',
    marksIn(redSwayShader, SWAY_MARKS), allOf(SWAY_MARKS));
  // The other side of the same coin: a chained sway keeps what it found.
  const kept = new THREE.MeshStandardMaterial({ color: 0x6a994e });
  patchHole(kept);
  applySway(kept, 0.06, 0.8);
  const keptShader = stubShader();
  kept.onBeforeCompile(keptShader, null);
  check('the chained sway keeps the hole patch',
    marksIn(keptShader, HOLE_MARKS), allOf(HOLE_MARKS));
  check('…and combines the keys instead of claiming the slot',
    kept.customProgramCacheKey(), `${HOLE_CACHE_KEY}+ground-sway@0.06`);

  console.log('\n[12] the wiring in buildScatter/mountUrl, pinned by the source');
  check('the sway hangs on the AREA\'s kind, asked once per area',
    /const sway = swayFor\(area\.kind\);/.test(groundSrc), true);
  // The tuft is patched with the ENTRY's amplitude (`entrySway`), not the
  // area's: the kind says how hard it blows, the prop's `sway_factor` how much
  // it takes part, and the product is what a stone with factor 0 arrives at.
  check('…the tuft material of every entry is patched',
    /applySway\(mat, entrySway, h\);/.test(groundSrc), true);
  // The clone used to be the WIND's doing (a still prop was patched by nobody
  // and could share the cache). Since the camera corridor patches every scatter
  // material (`scene/occlusion.ts`), the shared cache material can no longer be
  // handed out at all — the reason changed, the requirement for the wind did
  // not: patching the cached material would set every scene that ever placed
  // this prop waving.
  check('…a swaying prop draws through a CLONE of the cached GLB material',
    /const material = prop\.mats\.get\(url\) \?\? \(mesh\.material as THREE\.Material\)\.clone\(\);/
      .test(groundSrc), true);
  // ONE mount path for BOTH meshes of an entry since the per-instance LOD:
  // the full and the cheap mesh come through `mountUrl`, so both bend.
  check('…and the patch is applied where a tier is MOUNTED (mountUrl)',
    /applySway\(material, prop\.sway, prop\.targetH\);/.test(groundSrc), true);

  console.log('\n[13] which surface a kind wears — the field, never the name');
  check('a type that names a material answers it',
    surfaceOfType({ kind: 'grass', surface: 'deep_forest' }), 'deep_forest');
  check('…trimmed and lowercased like every id over the wire',
    surfaceOfType({ kind: 'grass', surface: '  Deep_Forest ' }), 'deep_forest');
  // THE RED COUNTER-CHECK of this whole change: a type whose kind IS a library
  // id and that names no material must come out empty. Under the old rule it
  // wore the same-named texture; a fallback to `kind` would show up right here.
  check('a type that names none answers NOTHING, even when its kind is an id',
    surfaceOfType({ kind: 'grass', name: 'Grass' }), '');
  check('…and so does an empty assignment',
    surfaceOfType({ kind: 'grass', surface: '   ' }), '');
  check('a kind the catalog does not know at all answers nothing',
    surfaceOfType(undefined), '');
  check('…and neither does a null entry', surfaceOfType(null), '');
  // The chain in `materialFor` reads the SURFACE, so both library questions —
  // the texture and the material class — are asked about the named entry and
  // not about the terrain kind. Pinned against the source, like [7].
  check('materialFor resolves the kind to its surface first',
    /const surface = surfaceOf\(kind\);/.test(groundSrc), true);
  check('…asks the library for THAT id (texture)',
    /const lib = surfaceFor\(surface, 'wall'\);/.test(groundSrc), true);
  check('…and for THAT id (material class)',
    /surfaceMaterialSpec\(surface\);/.test(groundSrc), true);
  // RED, since "Ein Wasser-Gesetz" W1/W2: the library is no longer asked
  // WHETHER a painted area is water. The class says what water LOOKS like
  // (ripple or matte) and was a second book about what water IS beside the
  // server's one predicate; the mirror is built on `meta.water_profile` alone,
  // so this question does not exist any more.
  check('the mirror asks the PROFILE, never the material class',
    /const profile = waterProfileOf\(area\.meta\);/.test(groundSrc), true);
  check('…and no library question decides water any more',
    /isWaterClass\(surfaceMaterialSpec\(surfaceOf\(area\.kind\)\)\?\.class\)/
      .test(groundSrc), false);
  check('the preload loads the named SURFACES, not the kinds',
    /preloadSurfaceTexture\(s\)/.test(groundSrc), true);
  // …and nowhere in this module does a terrain kind still reach the library.
  check('no library question is asked about a terrain kind any more',
    /surfaceFor\(kind,|surfaceMaterialSpec\(kind\)|surfaceMaterialSpec\(area\.kind\)|preloadSurfaceTexture\(k\)/
      .test(groundSrc), false);

  console.log(`\n${passed} ok, ${failed} failed`);
  process.exit(failed ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
