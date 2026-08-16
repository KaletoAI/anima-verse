/**
 * Surface-material factory with the renderer switch (plan-webgpu-mvp.md
 * Task 5). ONE call site shape for the four places that build ground, tile
 * plate and scene-recipe surfaces:
 *
 *   webgl          -> `surfaceMaterial` of @anima/scene-render, unchanged —
 *                     the byte-identical default path (GLSL water patch).
 *   webgpu /
 *   webgl-fallback -> water/ice: the TSL `WaterNodeMaterial`
 *                     (`render/water.tsl.ts`); every other class: the package
 *                     material as before — three converts classic materials
 *                     itself, and its material uniforms keep referencing the
 *                     ORIGINAL object at update time (MaterialReferenceNode.
 *                     updateReference), so later opacity/colour changes of the
 *                     callers still land. (The WebGL2 fallback of the WebGPU
 *                     renderer is the node path too — no `onBeforeCompile`
 *                     there either.)
 *
 * The backend is module state set once at boot (`main.ts`, right after
 * `Engine.create`) — the same shape as `setImpostorRenderer` and
 * `setModelEnvironment`: the call sites sit deep in the scene builders and
 * have no engine at hand.
 *
 * `makeWaveNormal` below is a MIRROR of the package's private routine
 * (materials.ts `makeWaveNormal`, same layers, same numbers): the package is
 * out of bounds for this branch. Phase 2 exports it from the package and this
 * copy goes away — see the report's port list.
 */
import type * as THREE from 'three';
import { surfaceMaterial, type SurfaceMaterialOptions,
         type SurfaceMaterialSpec } from '@anima/scene-render';
import type { ActiveBackend } from './backend';
import { waterNodeMaterial } from './water.tsl';

type ThreeNs = typeof import('three');

let active: ActiveBackend = 'webgl';

/** Set once at boot — which renderer the surfaces are built for. */
export function setSurfaceBackend(backend: ActiveBackend): void {
  active = backend;
}

export function surfaceBackend(): ActiveBackend {
  return active;
}

function isRippled(spec: SurfaceMaterialSpec | null | undefined): spec is SurfaceMaterialSpec {
  return spec?.class === 'water' || spec?.class === 'ice';
}

/** The material of ONE surface for the active renderer (see file header). */
export function surfaceMaterialFor(T: ThreeNs, opts: SurfaceMaterialOptions): THREE.Material {
  if (active === 'webgl' || !isRippled(opts.material)) {
    return surfaceMaterial(T, opts);
  }
  const spec = opts.material;
  return waterNodeMaterial(spec, {
    map: opts.map ?? null,
    color: opts.color !== undefined ? toColor(T, opts.color) : undefined,
    mask: opts.mask ?? null,
    transparent: opts.transparent,
    opacity: opts.opacity,
    side: opts.side as THREE.Side | undefined,
    normalMap: waveNormalTexture(T),
  });
}

function toColor(T: ThreeNs, c: SurfaceMaterialOptions['color']): THREE.Color | undefined {
  if (c === undefined || c === null) return undefined;
  if (typeof c === 'number' || typeof c === 'string') return new T.Color(c);
  return new T.Color(c.r, c.g, c.b);
}

// ── Wave normal map (mirror of materials.ts makeWaveNormal) ─────────────────
// Procedural, seamless, deterministic: a sum of sine layers with INTEGER
// frequencies tiles by construction. No asset, no download.
let waveNormal: THREE.Texture | null = null;

/** The ONE wave normal texture of the client (lazy, shared by all water). */
export function waveNormalTexture(T: ThreeNs): THREE.Texture {
  if (!waveNormal) waveNormal = makeWaveNormal(T);
  return waveNormal;
}

function makeWaveNormal(T: ThreeNs): THREE.Texture {
  const N = 256;
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = N;
  const ctx = canvas.getContext('2d')!;
  const img = ctx.createImageData(N, N);
  // fx, fy integer -> the height is periodic on the unit square.
  const layers: [number, number, number, number][] = [
    // fx, fy, amplitude, phase
    [1, 2, 1.0, 0.0],
    [2, -1, 0.7, 1.7],
    [3, 2, 0.4, 3.1],
    [-2, 3, 0.3, 5.0],
  ];
  const h = (u: number, v: number) => {
    let s = 0;
    for (const [fx, fy, a, ph] of layers) {
      s += a * Math.sin(2 * Math.PI * (fx * u + fy * v) + ph);
    }
    return s;
  };
  const d = 1 / N;
  for (let y = 0; y < N; y++) {
    for (let x = 0; x < N; x++) {
      const u = x / N;
      const v = y / N;
      // Central differences -> gradient -> normal (tangent space, +z up).
      const dx = (h(u + d, v) - h(u - d, v)) / (2 * d);
      const dy = (h(u, v + d) - h(u, v - d)) / (2 * d);
      const sc = 0.02;
      let nx = -dx * sc;
      let ny = -dy * sc;
      const nz = 1;
      const len = Math.hypot(nx, ny, nz) || 1;
      nx /= len;
      ny /= len;
      const i = (y * N + x) * 4;
      img.data[i] = Math.round((nx * 0.5 + 0.5) * 255);
      img.data[i + 1] = Math.round((ny * 0.5 + 0.5) * 255);
      img.data[i + 2] = Math.round((nz / len * 0.5 + 0.5) * 255);
      img.data[i + 3] = 255;
    }
  }
  ctx.putImageData(img, 0, 0);
  const tex = new T.CanvasTexture(canvas);
  tex.wrapS = tex.wrapT = T.RepeatWrapping;
  tex.needsUpdate = true;
  return tex;
}
