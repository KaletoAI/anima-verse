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
    const entry = `export { patchHole, HOLE_CACHE_KEY } from '${GROUND_SRC}';\n`;
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
 *  the counter-check vacuous. */
function assignInsteadOfChain(text) {
  let out = text.replace('prev.call(mat, shader, renderer);\n', '');
  if (out === text) throw new Error('the mutant did not drop the chained call');
  const keyed = out.replace('prevKey ? ', 'false ? ');
  if (keyed === out) throw new Error('the mutant did not drop the combined key');
  out = keyed;
  return out;
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
  const { patchHole, HOLE_CACHE_KEY } = await loadGround();

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

  console.log(`\n${passed} ok, ${failed} failed`);
  process.exit(failed ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
