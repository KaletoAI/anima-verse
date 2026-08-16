#!/usr/bin/env node
/**
 * Smoke check for the WATER TSL port (client3d/src/render/water.tsl.ts) — the
 * WebGPU counterpart of `applyWaterShader` in @anima/scene-render materials.ts.
 * § B5a style: names and numbers of the node tree, no screenshots. Runs without
 * a GPU: three/webgpu builds node materials in Node.js.
 *
 * Usage:  node client3d/scripts/smoke_water_tsl.mjs
 *
 * [1] parameter mapping equals the GLSL patch (defaults + clamps + explicit)
 * [2] ONE shared clock: waterTime follows surfaceTimeUniform via tickWaterTime,
 *     while the per-material uniforms are NOT shared between materials
 * [3] node tree wiring: colorNode/normalNode/roughnessNode set, >= 3 texture
 *     reads (two normal layers + mask), setupOutput overridden (fresnel-to-sky
 *     BEFORE fog — the place of `opaque_fragment`), sky reachable
 * [4] red checks: a matte spec is refused, wave_m below 0.05 clamps
 * [5] the factory switch (render/surface.ts): webgl -> the package material
 *     with its GLSL patch, webgpu -> the node material for water, and still
 *     the classic material for every other class
 *
 * The bundle re-exports the shared package THROUGH itself on purpose (same
 * rule as smoke_surface_patch.mjs [10]): the clock has to be measured on the
 * instance the port actually reads.
 */
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { DataTexture, RGBAFormat, UnsignedByteType } from 'three';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const SRC = join(ROOT, 'client3d/src/render/water.tsl.ts');
const SURFACE = join(ROOT, 'client3d/src/render/surface.ts');
let fails = 0;
const check = (ok, msg) => { console.log(`${ok ? 'ok  ' : 'FAIL'} ${msg}`); if (!ok) fails++; };
const near = (a, b, eps = 1e-6) => Math.abs(a - b) <= eps;

async function load(entry, name) {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(ROOT, 'client3d/scripts/.smoke-'));
  try {
    const built = await esbuild.build({
      stdin: { contents: entry, resolveDir: dir, loader: 'ts' },
      bundle: true, platform: 'node', format: 'esm', write: false,
      outfile: join(dir, name), external: ['three', 'three/*'],
    });
    const file = join(dir, name);
    await writeFile(file, built.outputFiles[0].text, 'utf8');
    return await import(`file://${file}`);
  } finally { await rm(dir, { recursive: true, force: true }); }
}

const m = await load(
  `export * from '${SRC}';\n`
  + "export { updateSurfaceMaterials, surfaceTimeUniform } from '@anima/scene-render';\n",
  'water.mjs');

const px = new DataTexture(new Uint8Array([128, 128, 255, 255]), 1, 1, RGBAFormat, UnsignedByteType);
const mk = (spec, opts = {}) => m.waterNodeMaterial(spec, { normalMap: px, ...opts });

console.log('\n[1] parameter mapping — the numbers of materials.ts applyWaterShader/surfaceMaterial');
{
  const mat = mk({ class: 'water' });
  const u = mat.waterUniforms;
  check(near(u.uWaveM.value, 1.6), 'wave_m default 1.6');
  check(near(u.uSpeed.value, 0.05), 'speed default 0.05');
  check(near(u.uSkyMix.value, 0.55), 'sky_mix default 0.55');
  check(near(u.uMapStrength.value, 0.75), 'map_strength default 0.75');
  check(u.uTint.value.getHexString() === '3f7fb8', 'tint default #3f7fb8');
  check(near(mat.roughness, 0.08) && near(mat.metalness, 0.15), 'roughness 0.08 / metalness 0.15');
  check(near(m.WATER_LAYER_B, 0.63), 'second layer 0.63× the wavelength');
  check(mat.normalMap === px && mat.normalScale.x === 1 && mat.normalScale.y === 1, 'wave normal map + scale (1,1)');
  const ice = mk({ class: 'ice', speed: 0, wave_m: 2.5, tint: '#a0c8ff', roughness: 0.2, metalness: 0.3,
                   sky_mix: 0.9, map_strength: 0.1 });
  const iu = ice.waterUniforms;
  check(near(iu.uSpeed.value, 0) && near(iu.uWaveM.value, 2.5) && near(iu.uSkyMix.value, 0.9)
        && near(iu.uMapStrength.value, 0.1) && iu.uTint.value.getHexString() === 'a0c8ff'
        && near(ice.roughness, 0.2) && near(ice.metalness, 0.3),
        'explicit spec values are taken as they are (ice = still water)');
  const tinted = mk({ class: 'water', tint: '#102030' });
  check(tinted.color.getHexString() === '102030', 'without a map the base colour is the tint');
  const withMap = mk({ class: 'water' }, { map: px, transparent: true, opacity: 0.4 });
  check(withMap.map === px && withMap.transparent === true && near(withMap.opacity, 0.4),
        'map / transparent / opacity are passed through');
}

console.log('\n[2] one clock');
{
  m.surfaceTimeUniform.value = 0;
  m.updateSurfaceMaterials(0.5);
  check(near(m.tickWaterTime(), 0.5) && near(m.waterTime.value, 0.5), 'waterTime follows surfaceTimeUniform');
  m.updateSurfaceMaterials(0.25);
  check(near(m.tickWaterTime(), 0.75), 'and keeps following');
  const a = mk({ class: 'water' }), b = mk({ class: 'water' });
  check(a.waterUniforms.uWaveM !== b.waterUniforms.uWaveM, 'per-material uniforms are NOT shared');
  check(typeof m.setWaterSky === 'function', 'setWaterSky exists (day/night tint of the fresnel)');
}

console.log('\n[3] node tree wiring');
{
  const mat = mk({ class: 'water' }, { map: px, mask: px });
  check(mat.isNodeMaterial === true && m.isWaterNodeMaterial(mat), 'a node material of the water class');
  check(!!mat.colorNode && !!mat.normalNode && !!mat.roughnessNode, 'color/normal/roughness nodes set');
  let textures = 0;
  const seen = new Set();
  for (const slot of [mat.colorNode, mat.normalNode, mat.roughnessNode]) {
    const raw = slot.node ?? slot;
    raw.traverse((n) => { if (n.isTextureNode && !seen.has(n)) { seen.add(n); textures++; } });
  }
  check(textures >= 3, `>= 3 distinct texture reads in the tree (got ${textures})`);
  const base = Object.getPrototypeOf(Object.getPrototypeOf(mat));
  check(typeof mat.setupOutput === 'function' && mat.setupOutput !== base.setupOutput,
        'setupOutput overridden (fresnel-to-sky before fog)');
  const key = mat.normalNode.node?.getCacheKey?.() ?? mat.normalNode.getCacheKey?.();
  check(typeof key === 'number' || typeof key === 'string', 'the tree is inspectable (cache key)');
}

console.log('\n[4] red checks');
{
  let threw = false;
  try { mk({ class: 'matte' }); } catch { threw = true; }
  check(threw, 'a matte spec is refused');
  threw = false;
  try { mk({ class: 'glow' }); } catch { threw = true; }
  check(threw, 'a glow spec is refused');
  check(near(mk({ class: 'water', wave_m: 0.001 }).waterUniforms.uWaveM.value, 0.05), 'wave_m clamps to 0.05');
}

console.log('\n[5] the factory switch (render/surface.ts)');
{
  // `surfaceMaterial` draws its wave normal map on a 2D canvas — a stub is
  // enough, CanvasTexture only reads width/height.
  const stubCanvas = () => ({
    width: 1, height: 1,
    getContext: () => ({
      fillStyle: '', fillRect() {},
      createImageData: (w, h) => ({ data: new Uint8ClampedArray(w * h * 4) }),
      putImageData() {},
    }),
  });
  globalThis.document = { createElement: () => stubCanvas() };
  const s = await load(`export * from '${SURFACE}';\n`, 'surface.mjs');
  const THREE = await import('three');
  s.setSurfaceBackend('webgl');
  const gl = s.surfaceMaterialFor(THREE, { material: { class: 'water' } });
  check(gl.isNodeMaterial !== true && gl.customProgramCacheKey?.() === 'anima-water',
        'webgl -> the package material with the GLSL patch');
  s.setSurfaceBackend('webgpu');
  const gpu = s.surfaceMaterialFor(THREE, { material: { class: 'water', wave_m: 3 } });
  check(m.isWaterNodeMaterial(gpu) || gpu.isWaterNodeMaterial === true, 'webgpu -> the water node material');
  check(near(gpu.waterUniforms.uWaveM.value, 3), 'the spec reaches the node material');
  const matte = s.surfaceMaterialFor(THREE, { material: { class: 'matte' } });
  check(matte.isMeshStandardMaterial === true && matte.isNodeMaterial !== true,
        'webgpu -> other classes stay the classic material (three converts them)');
  const fb = (s.setSurfaceBackend('webgl-fallback'), s.surfaceMaterialFor(THREE, { material: { class: 'ice' } }));
  check(fb.isWaterNodeMaterial === true, 'webgl-fallback of the WebGPU renderer is the node path too');
  check(s.waveNormalTexture() === s.waveNormalTexture(), 'ONE wave normal texture');
}

console.log(fails ? `\n${fails} FAILED` : '\nall ok');
process.exit(fails ? 1 : 0);
