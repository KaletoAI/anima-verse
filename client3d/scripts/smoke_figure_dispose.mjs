#!/usr/bin/env node
/**
 * Smoke check for the GPU-RESOURCE LIFETIME of character models in the 3D
 * client (review finding UI-1): what `FigureLibrary` frees on an outfit
 * change, WHEN it frees it, and what it must never touch.
 *
 * Usage:  node client3d/scripts/smoke_figure_dispose.mjs
 *         (needs three + esbuild; no server, no world DB, no WebGL —
 *          three.js dispatches a 'dispose' event on geometries, materials and
 *          textures, and that event IS the measurement here)
 *
 * Hand-derived expectations
 * -------------------------
 * The models are built by hand, so the expected event counts are counted off
 * the fixture, not read from the code:
 *
 *   model "full"  = 2 meshes → 2 geometries
 *                   mesh 1: matA  (map = texAlbedo, normalMap = texNormal)
 *                   mesh 2: [matB (map = texAlbedo — the SAME texture), matC
 *                           (envMap = the engine's shared PMREM)]
 *                   → 3 materials, 2 own textures, 1 foreign texture
 *   model "low"   = 1 mesh → 1 geometry, 1 material (map = texLow)
 *   fallback      = 1 mesh → 1 geometry, 1 material (map = texFallback)
 *                   — a manifest model in `FigureLibrary.models`, shared
 *                     between characters through `assignments`
 *
 * [1] A changed signature retires the old models but frees NOTHING yet: while
 *     `onModelReady` runs, the figure on screen is still the clone of the old
 *     template (`npcs.rebuild` is what drops it), and a disposed buffer would
 *     simply be re-uploaded on the next frame. Expected inside the
 *     notification: 0 dispose events of any kind.
 *
 * [2] Right after the notification the old models are freed, each resource
 *     EXACTLY ONCE although `apiModels` and `tierCache['full']` are the same
 *     object and `texAlbedo` sits in two materials:
 *       geometries 2 + 1 = 3 events, materials 3 + 1 = 4 events,
 *       textures texAlbedo 1, texNormal 1, texLow 1.
 *     The shared PMREM (`envMap`) gets 0 — it belongs to the engine
 *     (`glbMaterials.setModelEnvironment`), not to a model.
 *
 * [3] The manifest fallback model is never touched: 0 events on its geometry,
 *     material and texture over the whole run.
 *
 * [4] `Figure.dispose()` frees what is PER FIGURE and nothing that is shared
 *     with the template: the skeleton's bone texture (1 event — every
 *     `SkeletonUtils.clone` gets its own `THREE.Skeleton`, and the renderer
 *     hangs the bone texture on it) and the mixer's bindings
 *     (`existingAction` → null afterwards). The template's own geometry,
 *     material and texture must still show 0 events, because every other
 *     clone of that model keeps rendering them.
 *
 * Counter-probe (RED): the pre-fix code path is `delete` without any dispose.
 * It is re-created here by dropping the same three map entries by hand and
 * checking that this frees nothing — the number this check would have read
 * before the fix.
 */
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');

globalThis.self = globalThis;
if (!globalThis.window) globalThis.window = globalThis;
if (!globalThis.document) {
  globalThis.document = {
    createElement: () => ({ style: {}, getContext: () => null, setAttribute() {} }),
  };
}

let failed = 0;
let passed = 0;
function check(label, ok, detail) {
  if (ok) { passed += 1; console.log(`  ok   ${label}${detail ? ` — ${detail}` : ''}`); }
  else { failed += 1; console.log(`  FAIL ${label}${detail ? ` — ${detail}` : ''}`); }
}
const eq = (label, actual, expected) =>
  check(label, actual === expected, `${actual} (expected ${expected})`);

async function loadClient() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(ROOT, 'client3d/scripts/.smoke-'));
  try {
    const src = join(ROOT, 'client3d/src/scene');
    const entry = `export { FigureLibrary, Figure } from '${src}/figures';`;
    const built = await esbuild.build({
      stdin: { contents: entry, resolveDir: dir, loader: 'ts' },
      bundle: true, platform: 'node', format: 'esm', write: false,
      outfile: join(dir, 'client.mjs'), external: ['three', 'three/*'],
    });
    const file = join(dir, 'client.mjs');
    await writeFile(file, built.outputFiles[0].text, 'utf8');
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

const THREE = await import('three');

/** Count 'dispose' events per resource — that is three's own signal that a
 *  geometry/material/texture was handed back. */
const counts = new Map();
function watch(res, name) {
  counts.set(name, 0);
  res.addEventListener('dispose', () => counts.set(name, counts.get(name) + 1));
  return res;
}
const hits = (name) => counts.get(name) ?? -1;
const totalHits = () => [...counts.values()].reduce((a, b) => a + b, 0);

function texture(name) {
  return watch(new THREE.DataTexture(new Uint8Array([255, 255, 255, 255]), 1, 1), name);
}

/** A model fixture: plain meshes, no rig — `buildModel` is not involved here,
 *  the objects stand in for what a loaded GLB leaves behind. */
function plainModel(tag, opts = {}) {
  const template = new THREE.Group();
  const geo1 = watch(new THREE.BoxGeometry(1, 1, 1), `${tag}.geo1`);
  const mat1 = watch(new THREE.MeshStandardMaterial(), `${tag}.mat1`);
  mat1.map = opts.albedo ?? texture(`${tag}.texAlbedo`);
  template.add(new THREE.Mesh(geo1, mat1));
  if (opts.second) {
    const geo2 = watch(new THREE.BoxGeometry(1, 1, 1), `${tag}.geo2`);
    const mat2 = watch(new THREE.MeshStandardMaterial(), `${tag}.mat2`);
    mat2.map = mat1.map;                       // the SAME texture in two slots
    const mat3 = watch(new THREE.MeshStandardMaterial(), `${tag}.mat3`);
    mat3.envMap = opts.env;                    // the engine's shared PMREM
    mat1.normalMap = texture(`${tag}.texNormal`);
    template.add(new THREE.Mesh(geo2, [mat2, mat3]));
  }
  return {
    name: tag, template, clips: [], scale: 1, height: 1.7,
    assignOnly: true, noClips: false, tier: opts.tier ?? 'full', libraryFits: false,
  };
}

/** A rigged fixture for the Figure half: one bone, one skinned mesh. */
function riggedModel(tag) {
  const template = new THREE.Group();
  const bone = new THREE.Bone();
  bone.name = 'Hips';
  const geo = watch(new THREE.BoxGeometry(1, 1, 1), `${tag}.geo`);
  const count = geo.attributes.position.count;
  geo.setAttribute('skinIndex', new THREE.Uint16BufferAttribute(new Uint16Array(count * 4), 4));
  geo.setAttribute('skinWeight', new THREE.Float32BufferAttribute(
    Float32Array.from({ length: count * 4 }, (_, i) => (i % 4 === 0 ? 1 : 0)), 4));
  const mat = watch(new THREE.MeshStandardMaterial(), `${tag}.mat`);
  mat.map = texture(`${tag}.tex`);
  const mesh = new THREE.SkinnedMesh(geo, mat);
  mesh.add(bone);
  mesh.bind(new THREE.Skeleton([bone]));
  template.add(mesh);
  const track = new THREE.QuaternionKeyframeTrack('Hips.quaternion', [0, 1],
    [0, 0, 0, 1, 0, 0, 0, 1]);
  const clip = new THREE.AnimationClip('idle', 1, [track]);
  return {
    name: tag, template, clips: [clip], scale: 1, height: 1.7,
    assignOnly: true, noClips: false, tier: 'full', libraryFits: false,
  };
}

const tick = () => new Promise((r) => setTimeout(r, 0));
async function settle(predicate, tries = 200) {
  for (let i = 0; i < tries && !predicate(); i += 1) await tick();
  return predicate();
}

async function main() {
  const { FigureLibrary, Figure } = await loadClient();

  // ── the swap path ────────────────────────────────────────────────────────
  const sharedEnv = texture('shared.env');          // the engine's PMREM
  const full = plainModel('full', { second: true, env: sharedEnv });
  const low = plainModel('low', { tier: 'low' });
  const fallback = plainModel('fallback');

  const lib = new FigureLibrary();
  lib.models.push(fallback);                        // manifest model
  lib.apiModels.set('Demo', full);                  // SAME object as tier full
  lib.apiSignature.set('Demo', 'sig-a');
  lib.tierCache.set('Demo', new Map([['full', full], ['low', low]]));
  lib.loadFile = async () => ({ scene: plainModel('new').template, animations: [] });

  globalThis.fetch = async () => ({
    ok: true, status: 200,
    json: async () => ({ model: { url: '/demo.glb', signature: 'sig-b', format: 'glb', rig: 'mixamo' } }),
  });

  let atNotify = null;
  lib.onModelReady = () => { atNotify = totalHits(); };

  console.log('[1] the old model is retired, not freed, while the figure still shows it');
  const changed = await lib.refreshIfChanged('Demo');
  check('refreshIfChanged reports the change', changed === true, String(changed));
  eq('retired models parked (full and low, deduplicated)', lib.retired.get('Demo')?.length ?? 0, 2);
  await settle(() => atNotify !== null);
  eq('nothing disposed while onModelReady runs', atNotify, 0);

  console.log('\n[2] once the replacement is live, every resource is freed exactly once');
  await settle(() => lib.retired.size === 0);
  eq('the new model is installed', lib.apiSignature.get('Demo'), 'sig-b');
  eq('full.geo1', hits('full.geo1'), 1);
  eq('full.geo2', hits('full.geo2'), 1);
  eq('low.geo1', hits('low.geo1'), 1);
  eq('full.mat1', hits('full.mat1'), 1);
  eq('full.mat2', hits('full.mat2'), 1);
  eq('full.mat3', hits('full.mat3'), 1);
  eq('low.mat1', hits('low.mat1'), 1);
  eq('full.texAlbedo (in two materials → still one)', hits('full.texAlbedo'), 1);
  eq('full.texNormal (a slot no hand-written list would have)', hits('full.texNormal'), 1);
  eq('low.texAlbedo', hits('low.texAlbedo'), 1);
  eq('the shared PMREM envMap is NOT freed', hits('shared.env'), 0);

  console.log('\n[3] the manifest fallback model is never touched');
  eq('fallback.geo1', hits('fallback.geo1'), 0);
  eq('fallback.mat1', hits('fallback.mat1'), 0);
  eq('fallback.texAlbedo', hits('fallback.texAlbedo'), 0);

  console.log('\n[4] Figure.dispose frees the per-figure state only');
  const rig = riggedModel('rig');
  const figure = new Figure(rig);
  let skeleton = null;
  figure.root.traverse((o) => { if (o.isSkinnedMesh) skeleton = o.skeleton; });
  check('the clone has its own skeleton', !!skeleton && skeleton !== rig.template.children[0].skeleton);
  // What the renderer does on the first draw — done by hand, because there is
  // no WebGL context here.
  skeleton.boneTexture = texture('rig.boneTexture');
  const clip = rig.clips[0];
  const mixer = figure.mixer;
  check('the idle action is bound', !!mixer.existingAction(clip));
  figure.dispose();
  eq('the bone texture is freed', hits('rig.boneTexture'), 1);
  check('and unhooked from the skeleton', skeleton.boneTexture === null, String(skeleton.boneTexture));
  check('the mixer forgot the root', mixer.existingAction(clip) === null,
    String(mixer.existingAction(clip)));
  eq('the template geometry stays (other clones render it)', hits('rig.geo'), 0);
  eq('the template material stays', hits('rig.mat'), 0);
  eq('the template texture stays', hits('rig.tex'), 0);

  console.log('\n[5] RED counter-probe: the pre-fix path (delete without dispose)');
  const red = plainModel('red');
  const redLib = new FigureLibrary();
  redLib.apiModels.set('Red', red);
  redLib.apiSignature.set('Red', 'sig-a');
  redLib.tierCache.set('Red', new Map([['full', red]]));
  redLib.apiModels.delete('Red');
  redLib.apiSignature.delete('Red');
  redLib.tierCache.delete('Red');
  eq('dropping the map entries alone frees nothing (geometry)', hits('red.geo1'), 0);
  eq('… nor the material', hits('red.mat1'), 0);
  eq('… nor the texture', hits('red.texAlbedo'), 0);

  console.log(`\n${failed ? 'FAILED' : 'PASSED'}: ${passed} ok, ${failed} failed`);
  process.exit(failed ? 1 : 0);
}

await main();
