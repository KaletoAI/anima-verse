/**
 * Renderer backend switch (WebGPU MVP, plan-webgpu-mvp.md Task 1).
 *
 * The WebGL path is the DEFAULT and stays byte-identical to the boot before
 * this switch existed; `?webgpu=1` boots three's WebGPURenderer instead.
 * Everything renderer-specific of the boot lives here, so `engine.ts` keeps
 * ONE seam (`Engine.create`).
 *
 * Research notes (three 0.185.1, 2026-08-16):
 *  - `three` and `three/webgpu` share `three.core.js`; mixing the imports is
 *    safe (no second copy of the core classes in the bundle).
 *  - `WebGPURenderer` defaults to `alpha: true` (WebGL: false) — set false, the
 *    sky must stay the scene background. `render()` throws before `init()`.
 *  - The renderer silently falls back to its WebGL2 backend when
 *    `navigator.gpu` is missing; `renderer.isWebGPURenderer` is true in BOTH
 *    cases — only `renderer.backend.isWebGPUBackend` tells (after init).
 *  - `reversedDepthBuffer` would help the 0.2..800 m depth range a lot, but
 *    0.185 mirrors only `depthFunc` for it, NOT `polygonOffset`
 *    (WebGPUPipelineUtils.js:239-242) — the co-planar ground ladder
 *    (`AREA_POLYGON_OFFSET`) would push the wrong way. Deliberately OFF; a
 *    Phase-2 item together with a sign flip in the ladder.
 *  - GPU time needs `trackTimestamp: true` AND a `resolveTimestampsAsync()`
 *    per frame (Backend.js:597-616) — the bench does the resolving; here the
 *    value is only read.
 */
import * as THREE from 'three';
import { WebGPURenderer, PMREMGenerator as GPUPMREMGenerator } from 'three/webgpu';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';

export type RenderBackend = 'webgl' | 'webgpu';
export type AnyRenderer = THREE.WebGLRenderer | WebGPURenderer;
/** what actually runs — three falls back to its WebGL2 backend silently when
 *  `navigator.gpu` is missing; that case is reported, never hidden */
export type ActiveBackend = 'webgl' | 'webgpu' | 'webgl-fallback';

export interface RendererBoot {
  renderer: AnyRenderer;
  /** what was asked for */
  backend: RenderBackend;
  active: ActiveBackend;
  /** WebGPU compatibility mode (reduced limits on weaker devices), else false */
  compatibilityMode: boolean;
}

/** Pure: the backend a query string asks for. Only `webgpu=1` switches. */
export function requestedBackend(search: string): RenderBackend {
  return new URLSearchParams(search).get('webgpu') === '1' ? 'webgpu' : 'webgl';
}

/** The three renderer settings both paths share — the exact lines of the old
 *  constructor (`engine.ts`), in the same order. */
function applyCommon(r: AnyRenderer): void {
  r.shadowMap.enabled = true;
  r.shadowMap.type = THREE.PCFSoftShadowMap;
  r.outputColorSpace = THREE.SRGBColorSpace;
}

export async function createRenderer(backend: RenderBackend): Promise<RendererBoot> {
  if (backend === 'webgl') {
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    applyCommon(renderer);
    return { renderer, backend, active: 'webgl', compatibilityMode: false };
  }
  const renderer = new WebGPURenderer({
    antialias: true,
    alpha: false,
    powerPreference: 'high-performance',
    trackTimestamp: true,
  });
  await renderer.init();
  applyCommon(renderer);
  const be = renderer.backend as { isWebGPUBackend?: boolean; compatibilityMode?: boolean | null };
  const gpu = be.isWebGPUBackend === true;
  if (!gpu) {
    console.warn('[render] WebGPU requested but not available — three runs its WebGL2 backend');
  }
  return {
    renderer, backend,
    active: gpu ? 'webgpu' : 'webgl-fallback',
    compatibilityMode: gpu && be.compatibilityMode === true,
  };
}

/** Neutral IBL for server models with a real metal-roughness texture — the
 *  PMREM class of the renderer that runs (the WebGPU one is a different class
 *  and bakes asynchronously). */
export async function createModelEnv(boot: RendererBoot): Promise<THREE.Texture> {
  if (boot.backend === 'webgl') {
    return new THREE.PMREMGenerator(boot.renderer as THREE.WebGLRenderer)
      .fromScene(new RoomEnvironment(), 0.04).texture;
  }
  const gen = new GPUPMREMGenerator(boot.renderer as WebGPURenderer);
  const rt = await gen.fromSceneAsync(new RoomEnvironment(), 0.04);
  return rt.texture;
}

/** Draw calls of the last frame — the WebGPU Info counts render() calls under
 *  `calls` and the actual draws under `drawCalls`; WebGL only has `calls`. */
export function drawCallsOf(r: { info: { render: { calls: number; drawCalls?: number } } }): number {
  return r.info.render.drawCalls ?? r.info.render.calls;
}

/** GPU time of the last resolved frame in ms (WebGPU with timestamp queries
 *  and `resolveTimestampsAsync`), else null — never a misleading 0. */
export function gpuFrameMs(r: { info: { render: { timestamp?: number } } }): number | null {
  const ts = r.info.render.timestamp;
  return ts && ts > 0 ? ts : null;
}
