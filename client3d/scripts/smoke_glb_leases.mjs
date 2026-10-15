#!/usr/bin/env node
/**
 * NEU (red on a241a8aa: glbLeases.ts and leaseGlb are absent).
 * Hand-derived oracles: two_leases/last_release: refs 2 -> 1 -> 0, so GPU
 * disposal only at zero, once despite repeated release. from_lru: one load.
 * budget: 60 + 60 > 100, evict A, retain B's 60 bytes. fail: no retained row.
 * tier_swap: 1 -> 2 -> 1 never disposes. abort_loading: running load completes
 * at refs 0 into LRU. two_waiters_one_abort: refs 2 -> 1, no load abort.
 * last_waiter_abort: refs 1 -> 0 aborts controller. reacquire_before_cancel:
 * cancelled null with refs 1 requires load 2. abort_after_delivery: refs stays 1.
 * abort_vs_resolve: either null/0 or lease/1, never lease/0. cancel_queued:
 * cancelled queue push settles null, held/loading/LRU all zero.
 * shared_geometry: two clones share one geometry, one dispose event.
 * bytes_interleaved: shared 1200-byte attribute buffer + 400-byte index = 1600.
 * bitmap_close: two textures share one Source, hence one close, only at CPU drop.
 * Scatter consumer tests live HERE: scatter_double_load retains one lease per
 * URL despite two requests; scatter_meshless/scatter_throw retain zero leases.
 * REGRESSION: none; existing consumer lifetime baselines stay in their smokes.
 */
import assert from 'node:assert/strict';
import { readFile, writeFile, mkdtemp, rm } from 'node:fs/promises';
import { resolve, join } from 'node:path';
import { transformSync, build } from 'esbuild';
import * as THREE from 'three';
const root = resolve(import.meta.dirname, '../..');
const pure = async (path) => import('data:text/javascript;base64,' + Buffer.from(transformSync(await readFile(join(root, path), 'utf8'), { loader: 'ts', format: 'esm' }).code).toString('base64'));
assert.ok(await readFile(join(root, 'client3d/src/scene/glbLeases.ts'), 'utf8'), 'NEU: lease pool module must exist');
const { createLeasePool } = await pure('client3d/src/scene/glbLeases.ts');
const flush = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };
function fixture(load, budgetBytes = 100) {
  const gpu = [], cpu = []; let loads = 0;
  const pool = createLeasePool({ load: (...args) => { loads++; return load(...args); }, disposeGpu: t => gpu.push(t.id), dropCpu: t => cpu.push(t.id), bytes: t => t.bytes, budgetBytes });
  return { pool, gpu, cpu, get loads() { return loads; } };
}
const template = id => ({ id, geo: { id }, bytes: 60 });
async function test(name, run) { await run(); console.log(`NEU ${name}: PASS`); }
await test('two_leases / last_release / from_lru / tier_swap', async () => {
  const f = fixture(async url => template(url));
  const a = await f.pool.lease('A'), b = await f.pool.lease('A');
  assert.equal(f.loads, 1); assert.equal(f.pool.stats().held, 2);
  a.release(); assert.deepEqual(f.gpu, []);
  b.release(); b.release(); assert.deepEqual(f.gpu, ['A']);
  const c = await f.pool.lease('A'); assert.equal(f.loads, 1);
  const d = await f.pool.lease('A'); c.release(); assert.deepEqual(f.gpu, ['A']); d.release();
});
await test('budget / fail', async () => {
  const f = fixture(async url => url === 'bad' ? null : template(url));
  (await f.pool.lease('A')).release(); (await f.pool.lease('B')).release();
  assert.deepEqual(f.cpu, ['A']); assert.equal(f.pool.stats().lruBytes, 60);
  assert.equal(await f.pool.lease('bad'), null); assert.equal(await f.pool.lease('bad'), null);
  assert.equal(f.loads, 4); assert.equal(f.pool.stats().held, 0); assert.equal(f.pool.stats().loading, 0);
});
await test('two_waiters_one_abort / last_waiter_abort / abort_loading', async () => {
  const wait = deferred(); let signal;
  const f = fixture((_url, s) => { signal = s; return wait.promise; });
  const x = new AbortController(), y = new AbortController();
  const a = f.pool.lease('A', x.signal), b = f.pool.lease('A', y.signal);
  assert.equal(f.pool.stats().held, 2); x.abort(); assert.equal(await a, null);
  assert.equal(f.pool.stats().held, 1); assert.equal(signal.aborted, false);
  y.abort(); assert.equal(await b, null); assert.equal(signal.aborted, true);
  wait.resolve(template('A')); await flush();
  assert.equal(f.pool.stats().held, 0); assert.equal(f.pool.stats().lruCount, 1);
});
await test('reacquire_before_cancel', async () => {
  const wait = deferred(); const f = fixture((_url, s) => f.loads === 1 ? wait.promise : Promise.resolve(template('A')));
  const c = new AbortController(); const a = f.pool.lease('A', c.signal); c.abort();
  const b = f.pool.lease('A'); wait.resolve(null);
  assert.equal(await a, null); const lease = await b; assert.ok(lease); assert.equal(f.loads, 2); lease.release();
});
await test('abort_after_delivery / abort_vs_resolve', async () => {
  const f = fixture(async () => template('A')); const c = new AbortController();
  const a = await f.pool.lease('A', c.signal); c.abort(); assert.equal(f.pool.stats().held, 1); assert.deepEqual(f.gpu, []); a.release();
  const wait = deferred(), g = fixture(() => wait.promise), d = new AbortController();
  const pending = g.pool.lease('A', d.signal); wait.resolve(template('A')); queueMicrotask(() => d.abort());
  const result = await pending; await flush(); assert.equal(g.pool.stats().held, result ? 1 : 0); result?.release();
});
const dir = await mkdtemp(join(root, 'client3d/scripts/.leases-'));
try {
  const out = await build({ stdin: { contents: `export * from './client3d/src/scene/propAssets';`, resolveDir: root, loader: 'ts' }, bundle: true, format: 'esm', platform: 'node', external: ['three'], write: false, plugins: [{ name: 'loader', setup(b) { b.onLoad({ filter: /gltfLoader\.ts$/ }, () => ({ contents: 'export const createGLTFLoader = () => ({loadAsync: (...args) => globalThis.__leaseLoad(...args)});', loader: 'ts' })); } }] });
  const path = join(dir, 'assets.mjs'); await writeFile(path, out.outputFiles[0].text); const assets = await import(path);
  await test('cancel_queued (real propAssets queue adapter)', async () => {
    const waits = [deferred(), deferred(), deferred()]; let calls = 0;
    globalThis.__leaseLoad = () => waits[calls++].promise;
    const pending = [assets.leaseGlb('busy0'), assets.leaseGlb('busy1'), assets.leaseGlb('busy2')]; await flush();
    const c = new AbortController(); const cancelled = assets.leaseGlb('queued', undefined, c.signal); c.abort();
    assert.equal(await cancelled, null); await flush(); assert.equal(calls, 3);
    waits.forEach(w => w.resolve({ scene: new THREE.Group() })); (await Promise.all(pending)).forEach(l => l.release()); await flush();
    assert.equal(assets.glbLeaseStats().held, 0); assert.equal(assets.glbLeaseStats().loading, 0);
    assert.equal(assets.glbLeaseStats().lruCount, 3);
  });
  await test('shared_geometry / bytes_interleaved / bitmap_close', async () => {
    const geo = new THREE.BufferGeometry(); const buffer = new THREE.InterleavedBuffer(new Float32Array(300), 6);
    geo.setAttribute('position', new THREE.InterleavedBufferAttribute(buffer, 3, 0)); geo.setAttribute('normal', new THREE.InterleavedBufferAttribute(buffer, 3, 3)); geo.setIndex(new THREE.BufferAttribute(new Uint16Array(200), 1));
    const mat = new THREE.MeshStandardMaterial(); const group = new THREE.Group(); group.add(new THREE.Mesh(geo, mat)); group.add(group.children[0].clone(true));
    let count = 0; geo.addEventListener('dispose', () => count++); assets.disposeGpu(group); assert.equal(count, 1); assert.equal(assets.templateBytes(group), 1600);
    let closes = 0; globalThis.ImageBitmap = class { width = 3; height = 2; close() { closes++; } };
    const tex = new THREE.Texture(new ImageBitmap()), other = tex.clone(); mat.map = tex; mat.normalMap = other;
    const env = new THREE.Texture(new ImageBitmap()); mat.envMap = env;
    assert.equal(assets.templateBytes(group), 1600 + 3 * 2 * 4 * 4 / 3);
    assets.disposeGpu(group); assert.equal(closes, 0); assets.dropCpu(group); assert.equal(closes, 1);
  });
} finally { await rm(dir, { recursive: true, force: true }); }

// Execute the actual nested consumer without constructing the terrain or a GPU.
const ground = await readFile(join(root, 'client3d/src/scene/ground.ts'), 'utf8');
const mountSource = ground.slice(ground.indexOf('  function mountUrl('), ground.indexOf('\n  /**\n   * Hang a loaded geometry'));
const disposeSource = ground.slice(ground.indexOf('  function disposeProps('), ground.indexOf('\n  function ', ground.indexOf('  function disposeProps(') + 10));
await test('scatter_meshless / scatter_throw / scatter_double_load', async () => {
  for (const mode of ['meshless', 'throw', 'double']) {
    let held = 0, released = 0;
    const obj = new THREE.Group(); if (mode !== 'meshless') obj.add(new THREE.Mesh(new THREE.BoxGeometry(), new THREE.MeshStandardMaterial()));
    const leaseGlb = async () => { held++; return { template: obj, release() { held--; released++; } }; };
    const source = transformSync(mountSource + '\nreturn mountUrl;', { loader: 'ts' }).code;
    const mount = new Function('leaseGlb', 'groundedGeometry', 'noteSpread', 'applySway', 'applyOcclusionFade', 'place', source)(leaseGlb,
      () => { if (mode === 'throw') throw new Error('measurement failed'); return new THREE.BoxGeometry(); }, () => {}, () => {}, () => {}, () => {});
    const prop = { owned: new Map(), mats: new Map(), leases: new Map(), targetH: 1, wantLow: '', wantHigh: '', shownLow: '', shownHigh: '' };
    mount(prop, 'A', false); if (mode === 'double') mount(prop, 'A', true); await flush();
    assert.equal(held, mode === 'double' ? 1 : 0, mode);
    if (mode === 'double') {
      assert.equal(released, 1); assert.equal(prop.mats.size, 1);
      // The actual teardown must release after disposing the material clones.
      let materialGone = false; prop.mats.get('A').addEventListener('dispose', () => { materialGone = true; });
      const lease = prop.leases.get('A'), release = lease.release; lease.release = () => { assert.equal(materialGone, true); release(); };
      prop.low = new THREE.InstancedMesh(new THREE.BoxGeometry(), new THREE.MeshBasicMaterial(), 1);
      const disposeCode = transformSync(disposeSource + '\nreturn disposeProps;', { loader: 'ts' }).code;
      new Function('group', 'releaseImpostor', disposeCode)(new THREE.Group(), () => {})([prop]);
      assert.equal(held, 0);
    }
  }
});
