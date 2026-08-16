#!/usr/bin/env node
/**
 * Smoke check for the renderer-backend switch (client3d/src/render/backend.ts).
 *
 * Usage:  node client3d/scripts/smoke_render_backend.mjs
 *         (bundles the module with esbuild, three stays external; no GPU, no DOM)
 *
 * [1] `requestedBackend` is a pure function of the query string — ONLY
 *     `webgpu=1` switches, everything else is the WebGL default.
 * [2] three/webgpu and three/tsl are importable in Node and expose the
 *     symbols the port relies on (629 exports in three 0.185.1).
 * [3] `drawCallsOf` prefers the WebGPU counter (`info.render.drawCalls`) and
 *     falls back to the WebGL one (`info.render.calls`) — under WebGPU `calls`
 *     counts render() invocations, not draws.
 * [4] `gpuFrameMs` reports null while no timestamp was resolved (never 0).
 */
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const SRC = join(ROOT, 'client3d/src/render/backend.ts');
let fails = 0;
const check = (ok, msg) => { console.log(`${ok ? 'ok  ' : 'FAIL'} ${msg}`); if (!ok) fails++; };

async function load() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(ROOT, 'client3d/scripts/.smoke-'));
  try {
    const built = await esbuild.build({
      stdin: { contents: `export * from '${SRC}';`, resolveDir: dir, loader: 'ts' },
      bundle: true, platform: 'node', format: 'esm', write: false,
      outfile: join(dir, 'backend.mjs'), external: ['three', 'three/*'],
    });
    const file = join(dir, 'backend.mjs');
    await writeFile(file, built.outputFiles[0].text, 'utf8');
    return await import(`file://${file}`);
  } finally { await rm(dir, { recursive: true, force: true }); }
}

const m = await load();

// [1]
check(m.requestedBackend('') === 'webgl', '[1] empty query -> webgl');
check(m.requestedBackend('?foo=1') === 'webgl', '[1] unrelated query -> webgl');
check(m.requestedBackend('?webgpu=1') === 'webgpu', '[1] ?webgpu=1 -> webgpu');
check(m.requestedBackend('?debug3d=1&webgpu=1') === 'webgpu', '[1] combined -> webgpu');
check(m.requestedBackend('?webgpu=0') === 'webgl', '[1] ?webgpu=0 -> webgl (red check)');
check(m.requestedBackend('?webgpu') === 'webgl', '[1] bare ?webgpu -> webgl (red check)');

// [2]
const gpu = await import('three/webgpu');
check(typeof gpu.WebGPURenderer === 'function', '[2] WebGPURenderer exported');
check(typeof gpu.MeshStandardNodeMaterial === 'function', '[2] MeshStandardNodeMaterial exported');
check(typeof gpu.PMREMGenerator === 'function', '[2] webgpu PMREMGenerator exported');
const tsl = await import('three/tsl');
for (const n of ['uniform', 'time', 'texture', 'uv', 'positionWorld', 'normalMap',
                 'materialColor', 'materialRoughness', 'positionViewDirection',
                 'transformedNormalView', 'renderGroup', 'Fn', 'mix', 'pow', 'dot', 'clamp']) {
  check(n in tsl, `[2] three/tsl exports ${n}`);
}

// [3]
check(m.drawCallsOf({ info: { render: { calls: 1, drawCalls: 42 } } }) === 42, '[3] drawCallsOf webgpu counter');
check(m.drawCallsOf({ info: { render: { calls: 7 } } }) === 7, '[3] drawCallsOf webgl fallback');

// [4]
check(m.gpuFrameMs({ info: { render: { calls: 1, timestamp: 0 } } }) === null, '[4] gpuFrameMs null when unresolved');
check(m.gpuFrameMs({ info: { render: { calls: 1 } } }) === null, '[4] gpuFrameMs null without the field (WebGL)');
check(m.gpuFrameMs({ info: { render: { calls: 1, timestamp: 2.5 } } }) === 2.5, '[4] gpuFrameMs passes a resolved value');

console.log(fails ? `\n${fails} FAILED` : '\nall ok');
process.exit(fails ? 1 : 0);
