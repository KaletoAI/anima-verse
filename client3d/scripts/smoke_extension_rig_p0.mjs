/** P0 transport regression: content revision reloads and live motion storage.
 * Usage: node client3d/scripts/smoke_extension_rig_p0.mjs
 * Hand-derived expectations: same signature and revision => zero reloads;
 * changed motion alone => zero reloads, existing Figure sees the new payload;
 * changed revision alone or changed signature alone => exactly one reload.
 * URLs are opaque server inputs: low tier selects lowUrl verbatim, including its
 * revision query; missing lowUrl falls back to url, and full tier uses url.
 * Thus one low build requests exactly the supplied low URL, not a client-built
 * ?tier=low&rev= URL: only the server knows the low asset path/cache identity.
 */
import assert from 'node:assert/strict';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import * as THREE from 'three';
import { build } from 'esbuild';

const root = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');
globalThis.self = globalThis;
globalThis.window = globalThis;
globalThis.document = { createElement: () => ({ style: {}, getContext: () => null, setAttribute() {} }) };
const dir = await mkdtemp(join(root, 'client3d/scripts/.smoke-'));
try {
  const result = await build({
    stdin: { contents: `export { FigureLibrary, Figure } from '${root}/client3d/src/scene/figures';`,
             resolveDir: dir, loader: 'ts' },
    bundle: true, platform: 'node', format: 'esm', write: false,
    external: ['three', 'three/*'],
  });
  const file = join(dir, 'client.mjs');
  await writeFile(file, result.outputFiles[0].text);
  const { FigureLibrary, Figure } = await import(`file://${file}`);
  const lib = new FigureLibrary();
  let reloads = 0;
  lib.fetchCharacterModel = () => { reloads += 1; };
  const state = { payload: { rev: 'motion-a', groups: {} } };
  const model = { name: 'demo', template: new THREE.Group(), clips: [], scale: 1,
                  height: 1.7, assignOnly: true, noClips: true, tier: 'full',
                  libraryFits: false, motion: state };
  const figure = new Figure(model);
  lib.apiModels.set('demo', model);
  lib.apiSignature.set('demo', 'signature-a');
  lib.apiRevision.set('demo', 'revision-a');
  lib.motionState.set('demo', state);
  assert.equal(await lib.refreshIfChanged('demo', 'signature-a', 'revision-a'), false);
  assert.equal(reloads, 0);
  const motion = { rev: 'motion-b', groups: {example: {
    bones: ['ExampleBone'], freq_hz: 2.2, zeta: .15, gravity: .35, gravity_scale: 1,
    gain: 1, axis_gain: [.5, 1, .15], flatten: 0, spill: 0,
    max_deg: 25, sag_max_deg: 25, squash: [.6, 1.4], rest_deg: 0, rest_max_deg: 90,
  }} };
  assert.equal(await lib.refreshIfChanged('demo', 'signature-a', 'revision-a', motion), false);
  assert.equal(figure.motion, motion);
  assert.deepEqual(figure.motion.groups.example.axis_gain, [.5, 1, .15]);
  assert.equal(reloads, 0);
  assert.equal(await lib.refreshIfChanged('demo', 'signature-a', 'revision-b', motion), true);
  assert.equal(reloads, 1);
  lib.apiSignature.set('demo', 'signature-a');
  lib.apiRevision.set('demo', 'revision-b');
  assert.equal(await lib.refreshIfChanged('demo', 'signature-b', 'revision-b', motion), true);
  assert.equal(reloads, 2);
  let requestedUrl;
  lib.loadFile = async (url) => {
    requestedUrl = url;
    return { scene: new THREE.Group(), animations: [] };
  };
  const info = { url: '/characters/demo/model3d/file', format: 'glb', rig: 'mixamo',
                 lowUrl: '/assets/demo-low.glb?v=server-revision-b',
                 modelRev: 'revision-b', motion };
  await lib.buildModel('demo', info, 'low');
  assert.equal(requestedUrl, info.lowUrl);
  await lib.buildModel('demo', info, 'full');
  assert.equal(requestedUrl, info.url);
  const { lowUrl, ...withoutLow } = info;
  await lib.buildModel('demo', withoutLow, 'low');
  assert.equal(requestedUrl, info.url);
  figure.dispose();
  console.log('PASS extension rig P0 client: revision reload and independent motion storage');
} finally {
  await rm(dir, { recursive: true, force: true });
}
