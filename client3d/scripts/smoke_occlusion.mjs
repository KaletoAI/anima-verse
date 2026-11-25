#!/usr/bin/env node
/**
 * Derivation moved to native/tests/Derivations/occlusion.md (E1, 2026-11-25).
 * Usage:  node client3d/scripts/smoke_occlusion.mjs
 *         (bundles the client's occlusion + ground modules; needs three)
 * Runs until E3 deletes the browser scene; the C# vector tests keep executing the cases.
 */
import { loadVectors, runVectors } from '../../shared/test-vectors/vectors.mjs';
import { mkdtemp, rm, writeFile, readFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');
const OCC_SRC = join(ROOT, 'client3d/src/scene/occlusion.ts');
const GROUND_SRC = join(ROOT, 'client3d/src/scene/ground.ts');

/**
 * Bundle the client's occlusion module TOGETHER with the ground module and
 * import the pair. One bundle on purpose: the double chain of section [2] needs
 * the very `applySway` that runs in the app, and `external: ['three']` keeps
 * node's own three the only one in play (same trick as
 * `smoke_surface_patch.mjs`). `ground.ts` reaches the DOM and the network only
 * inside functions, so it loads here.
 *
 * `mutate` rewrites the BUILT text before the import — that is how section [5]
 * gets its two mutants without a second copy of the patch lying around to rot.
 */
async function loadClient(mutate) {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(ROOT, 'client3d/scripts/.smoke-'));
  try {
    const entry = "export { applyOcclusionFade, occlusionUniforms, updateOcclusion,\n"
      + "  occA, occB, occRadius, occStrength, OCC_CACHE_KEY, OCC_RADIUS_M }\n"
      + `  from '${OCC_SRC}';\n`
      + `export { applySway } from '${GROUND_SRC}';\n`
      + `export { applyCutouts } from '${join(ROOT, 'packages/scene-render/src/cutouts.ts')}';\n`;
    const built = await esbuild.build({
      stdin: { contents: entry, resolveDir: dir, loader: 'ts' },
      bundle: true, platform: 'node', format: 'esm', write: false,
      outfile: join(dir, 'occlusion.mjs'), external: ['three', 'three/*'],
    });
    const text = built.outputFiles[0].text;
    const source = mutate ? mutate(text) : text;
    const file = join(dir, 'occlusion.mjs');
    await writeFile(file, source, 'utf8');
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

/** Section [5a]'s mutant: `applyOcclusionFade` ASSIGNS instead of chaining, so
 *  the predecessor patch in the slot is never called. Anchored on the
 *  corridor's own first uniform — there are several chained patches in this
 *  bundle and a bare `prev.call(…)` would hit whichever esbuild printed
 *  first. */
function assignInsteadOfChain(text) {
  const chained = /prev\.call\(mat, shader, renderer\);(\s*)shader\.uniforms\.uOccA =/;
  if (!chained.test(text)) throw new Error('the corridor patch no longer chains here');
  return text.replace(chained, 'shader.uniforms.uOccA =');
}

/** Section [5b]'s mutant: the embodiment gate drops out of the arithmetic, so
 *  an overview client would get a real corridor cut through its map. */
function ignoreEmbodied(text) {
  const gate = 'if (!embodied || !avatar) {';
  if (!text.includes(gate)) throw new Error('the embodiment gate is no longer where the probe looks');
  return text.replace(gate, 'if (!avatar) {');
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
      '\t#include <opaque_fragment>',
      '}',
    ].join('\n'),
  };
}

/** The lines the corridor patch writes — one list, used for "present" in [1]
 *  and [2] and for "absent" nowhere yet, so the two sides cannot drift. */
const OCC_MARKS = [
  ['vert', 'varying vec3 vOccWorld;'],
  ['vert', 'vOccWorld = ( modelMatrix * instanceMatrix * vec4( transformed, 1.0 ) ).xyz;'],
  ['vert', 'vOccWorld = ( modelMatrix * vec4( transformed, 1.0 ) ).xyz;'],
  ['frag', 'uniform vec3 uOccA;'],
  ['frag', 'uniform float uOccStrength;'],
  ['frag', 'if ( uOccStrength > 0.0 ) {'],
  // point-to-SEGMENT, not point-to-line: the clamp is the whole difference
  ['frag', 'float occT = clamp( dot( vOccWorld - uOccA, occAB ) / occLen2, 0.0, 1.0 );'],
  ['frag', 'float occDist = distance( vOccWorld, uOccA + occAB * occT );'],
  // the soft rim over the radius, and the ordered 4x4 Bayer threshold
  ['frag', 'smoothstep( uOccRadius * 0.5, uOccRadius, occDist )'],
  ['frag', 'float occThreshold = ( abs( occY0 - occX0 ) * 8.0 + occY0 * 4.0'],
  ['frag', 'if ( occHide > occThreshold ) discard;'],
];
const OCC_UNIFORMS = ['uOccA', 'uOccB', 'uOccRadius', 'uOccStrength'];
/** What `applySway` writes, at the amplitude used below — the predecessor the
 *  chain has to keep (copied from `smoke_surface_patch.mjs` section [8], which
 *  is where these lines are the subject). */
const SWAY_MARKS = [
  ['vert', 'uniform float uSwayRef;'],
  ['vert', 'float swayUp = pow( max( transformed.y, 0.0 ) / uSwayRef, 2.0 );'],
  ['vert', 'transformed.xz += 0.06 * swayUp * sin( uTime * 1.70 + swayPhase ) * swayDir.xz;'],
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
/** Metres to the millimetre — the corridor is a view effect, and comparing
 *  raw doubles would only measure the square root. */
const mm = (v) => Math.round(v * 1000) / 1000;

function occlusionThreshold(x, y) {
  x = Math.floor(x) % 4; y = Math.floor(y) % 4;
  return (Math.abs(y % 2 - x % 2) * 8 + y % 2 * 4
    + Math.abs(Math.floor(y / 2) - Math.floor(x / 2)) * 2 + Math.floor(y / 2)) / 16;
}

async function main() {
  const THREE = await import('three');
  const { applyOcclusionFade, occlusionUniforms, updateOcclusion,
    occA, occB, occRadius, occStrength, OCC_CACHE_KEY, OCC_RADIUS_M,
    applySway, applyCutouts } = await loadClient();

  /** One material through the patch, with its composed shader. */
  function patched(patch = applyOcclusionFade, before = null) {
    const mat = new THREE.MeshStandardMaterial({ color: 0x6a994e });
    if (before) before(mat);
    patch(mat);
    const shader = stubShader();
    mat.onBeforeCompile(shader, null);
    return { mat, shader };
  }

  console.log('\n[1] the corridor patch alone — both replacements after the chain');
  const bush = patched();
  check('every corridor line is written', marksIn(bush.shader, OCC_MARKS),
    allOf(OCC_MARKS));
  check('…the four uniforms are bound',
    OCC_UNIFORMS.filter((u) => bush.shader.uniforms[u] !== undefined), OCC_UNIFORMS);
  check('the vertex anchor is APPENDED to, not replaced',
    bush.shader.vertexShader.includes('#include <project_vertex>'), true);
  check('…and the world position stands after it',
    bush.shader.vertexShader.indexOf('#include <project_vertex>')
      < bush.shader.vertexShader.indexOf('vOccWorld ='), true);
  check('the discard stands before the clipping include',
    bush.shader.fragmentShader.indexOf('discard;')
      < bush.shader.fragmentShader.indexOf('#include <clipping_planes_fragment>'), true);
  check('…and inside the strength guard (0 discards nothing)',
    bush.shader.fragmentShader.indexOf('if ( uOccStrength > 0.0 ) {')
      < bush.shader.fragmentShader.indexOf('discard;'), true);
  check('nothing of the test lands in the vertex shader',
    bush.shader.vertexShader.includes('discard'), false);
  check('the cache key is the corridor\'s own', bush.mat.customProgramCacheKey(),
    OCC_CACHE_KEY);
  check('…which is the constant, not a value of the frame',
    OCC_CACHE_KEY, 'occlusion-corridor');
  check('…and it is stable across calls', bush.mat.customProgramCacheKey(),
    bush.mat.customProgramCacheKey());
  const second = patched();
  check('a second material answers the SAME key (one program for all of them)',
    second.mat.customProgramCacheKey(), bush.mat.customProgramCacheKey());

  console.log('\n[2] the double chain — wind and corridor on one material');
  const grass = patched(applyOcclusionFade, (m) => applySway(m, 0.06, 0.8));
  check('the sway lines survive the corridor patch',
    marksIn(grass.shader, SWAY_MARKS), allOf(SWAY_MARKS));
  check('…and every corridor line is there as well',
    marksIn(grass.shader, OCC_MARKS), allOf(OCC_MARKS));
  check('the sway uniforms are bound',
    SWAY_UNIFORMS.filter((u) => grass.shader.uniforms[u] !== undefined), SWAY_UNIFORMS);
  check('…and the corridor uniforms too',
    OCC_UNIFORMS.filter((u) => grass.shader.uniforms[u] !== undefined), OCC_UNIFORMS);
  check('the key is both, in the order they were applied',
    grass.mat.customProgramCacheKey(), `ground-sway@0.06+${OCC_CACHE_KEY}`);
  check('…which is neither of the two singles',
    ['ground-sway@0.06', OCC_CACHE_KEY].includes(grass.mat.customProgramCacheKey()), false);
  applyOcclusionFade(grass.mat);
  const twice = stubShader();
  grass.mat.onBeforeCompile(twice, null);
  check('patching twice is still one patch',
    twice.vertexShader.split('varying vec3 vOccWorld;').length - 1, 1);
  check('…and the key did not grow a second corridor',
    grass.mat.customProgramCacheKey(), `ground-sway@0.06+${OCC_CACHE_KEY}`);

  console.log('\n[3] the shared uniforms — one write per frame reaches everything');
  check('two materials share ONE corridor start',
    bush.shader.uniforms.uOccA === grass.shader.uniforms.uOccA, true);
  check('…one corridor end', bush.shader.uniforms.uOccB === grass.shader.uniforms.uOccB, true);
  check('…one radius', bush.shader.uniforms.uOccRadius === grass.shader.uniforms.uOccRadius, true);
  check('…and one strength',
    bush.shader.uniforms.uOccStrength === grass.shader.uniforms.uOccStrength, true);
  check('…and they are the module\'s own objects',
    [bush.shader.uniforms.uOccA === occA, bush.shader.uniforms.uOccB === occB,
      bush.shader.uniforms.uOccRadius === occRadius,
      bush.shader.uniforms.uOccStrength === occStrength], [true, true, true, true]);
  updateOcclusion({ x: 0, y: 1.2, z: 10 }, { x: 0, y: 0, z: 0 }, true);
  check('one frame\'s write reaches the composed shader',
    [mm(bush.shader.uniforms.uOccA.value.z), mm(bush.shader.uniforms.uOccB.value.z),
      mm(bush.shader.uniforms.uOccStrength.value)], [9.5, 0, 1]);
  check('…and the second material sees the very same numbers',
    [mm(grass.shader.uniforms.uOccA.value.z), mm(grass.shader.uniforms.uOccStrength.value)],
    [9.5, 1]);
  updateOcclusion({ x: 0, y: 1.2, z: 10 }, { x: 0, y: 0, z: 0 }, false);
  check('leaving the mode neutralises both at once',
    [bush.shader.uniforms.uOccStrength.value, grass.shader.uniforms.uOccStrength.value],
    [0, 0]);

  console.log('\n[3b] cutout clones and the tile corridor gate');
  const sourceMat = new THREE.MeshStandardMaterial();
  const model = new THREE.Group();
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(), sourceMat);
  model.add(mesh);
  const cut = applyCutouts(THREE, model, [[[0, 0], [4, 0], [4, 4], [0, 4]]]);
  const cutKey = mesh.material.customProgramCacheKey();
  const tileGate = { value: 1 };
  applyOcclusionFade(mesh.material, tileGate);
  const composed = stubShader();
  mesh.material.onBeforeCompile(composed, null);
  check('patches the cutout clone, preserving the leased source', mesh.material !== sourceMat, true);
  check('cutout discard survives', composed.fragmentShader.includes('if ( cutHit ) discard;'), true);
  check('corridor discard survives', marksIn(composed, OCC_MARKS), allOf(OCC_MARKS));
  check('gate is wired by identity', composed.uniforms.uOccGate === tileGate, true);
  check('gate declared in every shader', bush.shader.fragmentShader.includes('uniform float uOccGate;'), true);
  check('gate multiplies strength', composed.fragmentShader.includes('uOccStrength * uOccGate *'), true);
  check('both cache keys survive', mesh.material.customProgramCacheKey(), `${cutKey}+${OCC_CACHE_KEY}`);
  check('default gate is shared', bush.shader.uniforms.uOccGate === grass.shader.uniforms.uOccGate, true);
  check('default gate is one', bush.shader.uniforms.uOccGate?.value, 1);
  check('gate does not change shader text', composed.fragmentShader.slice(0, composed.fragmentShader.indexOf('#define CUT_POLYS')),
    bush.shader.fragmentShader.slice(0, bush.shader.fragmentShader.indexOf('void main()')));
  cut.setEnabled(true);
  tileGate.value = 0;
  check('gate changes live without recompiling', composed.uniforms.uOccGate?.value, 0);
  check('gate changes preserve cache key', mesh.material.customProgramCacheKey(), `${cutKey}+${OCC_CACHE_KEY}`);
  cut.dispose();
  sourceMat.dispose();
  mesh.geometry.dispose();

  const recipe = await readFile(join(ROOT, 'client3d/src/scene/sceneRecipe.ts'), 'utf8');
  const tiles = await readFile(join(ROOT, 'client3d/src/scene/tiles.ts'), 'utf8');
  const building = recipe.slice(recipe.indexOf('function applyBuildingModel('), recipe.indexOf('/** Room clipping'));
  check('only plan hulls excluding ground get the gated patch after cutouts',
    /if \(spec\.plan_hull && spec\.display !== 'ground'\)/.test(building)
      && building.indexOf('applyOcclusionFade(') > building.indexOf('tile.cutouts = applyCutouts('), true);
  check('patch only proven cutout clones', building.includes('__cutoutClone'), true);
  const calls = (recipe + tiles).match(/setTileCutoutsEnabled\(tile,/g) || [];
  check('at least both known toggle sites use the helper', calls.length >= 2, true);
  check('only helper calls cutout setEnabled', ((recipe + tiles).match(/cutouts\??\.setEnabled\(/g) || []).length, 1);
  check('helper keeps gate inverse to cutouts', /cutoutOccGate\.value = on \? 0 : 1/.test(tiles), true);

  console.log('\n[4,6,7] shared corridor arithmetic and shader probes, by hand');
  const vectors = runVectors(loadVectors('occlusion'), {
    occlusionUniforms,
    occlusionHide: (st, p, gate) => {
      const ab = st.b.map((v, i) => v - st.a[i]);
      const dot = (a, b) => a.reduce((sum, v, i) => sum + v * b[i], 0);
      const t = Math.min(1, Math.max(0, dot(p.map((v, i) => v - st.a[i]), ab) / Math.max(dot(ab, ab), 1e-6)));
      const d = Math.hypot(...p.map((v, i) => v - st.a[i] - ab[i] * t));
      const rim = Math.min(1, Math.max(0, (d - st.radius * .5) / (st.radius * .5)));
      return st.strength * gate * (1 - rim * rim * (3 - 2 * rim));
    },
    occlusionThreshold,
    occlusionDiscard: (hide, x, y) => hide > occlusionThreshold(x, y),
  });
  passed += vectors.passed;
  failed += vectors.failed;
  const feet = { x: 0, y: 0, z: 0 };
  check('radius is the hand-derived 1.5 m constant', OCC_RADIUS_M, 1.5);

  console.log('\n[5] the RED counter-checks — the chain, and the neutrality');
  const flat = await loadClient(assignInsteadOfChain);
  const redMat = new THREE.MeshStandardMaterial({ color: 0x6a994e });
  flat.applySway(redMat, 0.06, 0.8);
  flat.applyOcclusionFade(redMat);
  const redShader = stubShader();
  redMat.onBeforeCompile(redShader, null);
  check('the assignment mutant loses EVERY sway line',
    marksIn(redShader, SWAY_MARKS), []);
  check('…and the sway uniforms with them',
    SWAY_UNIFORMS.filter((u) => redShader.uniforms[u] !== undefined), []);
  check('…while its own corridor is fully intact (the probe measures the chain)',
    marksIn(redShader, OCC_MARKS), allOf(OCC_MARKS));
  check('the truth, from the other side, KEEPS the wind',
    marksIn(grass.shader, SWAY_MARKS).length, SWAY_MARKS.length);

  const loud = await loadClient(ignoreEmbodied);
  check('without the embodiment gate an overview client WOULD be cut open',
    mm(loud.occlusionUniforms({ x: 0, y: 1.2, z: 5 }, feet, false).strength), 1);
  check('…while the truth answers 0 for the very same frame',
    mm(occlusionUniforms({ x: 0, y: 1.2, z: 5 }, feet, false).strength), 0);

  console.log(`\n${passed} ok, ${failed} failed`);
  process.exit(failed ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
