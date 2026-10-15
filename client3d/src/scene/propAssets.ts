import * as THREE from 'three';
import { createFocusQueue } from '../game/focusQueue';
import { createGLTFLoader } from './gltfLoader';
import { neutralizeGltfMaterials } from './glbMaterials';
import { createLeasePool, type Lease, type LeasePool } from './glbLeases';

// Shared GLB queue for buildings, room dioramas and props. Returns RAW meshes:
// orientation, scale and position belong to the placement spec and the single
// place() routine (sceneRecipe.ts, contract § B2).
// Prop dimensions and orientation arrive with the spec (`dims` -> `max_m`,
// `fix_euler`); the client no longer needs a separate /assets/props library.
const loader = createGLTFLoader();


// Large, numerous GLBs would saturate browser connections if loaded together.
// Limit downloads and re-evaluate distance to the live camera target whenever
// a slot becomes free, so the currently viewed tile is served first.
const MAX_PARALLEL = 3;
const glbQueue = createFocusQueue({ max: MAX_PARALLEL });
let loadFocus: THREE.Vector3 | null = null;
/** Keep the live camera target reference: the engine mutates it in place.
 *  Without a focus, jobs retain insertion order. */
export function setPropLoadFocus(target: THREE.Vector3) {
  loadFocus = target;
}

/** Attempts before giving up on a model. The server is stable under parallel
 *  load (Fable, 2026-07-26: 120 concurrent GETs returned 200; 30 conditional
 *  GETs returned 304, without rate limiting). Transient backend restarts must
 *  not make a model disappear for the whole session. */
const LOAD_ATTEMPTS = 3;
const RETRY_BASE_MS = 800;
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Idle templates retain CPU data for quick returns, bounded to 256 MiB. */
export const GLB_LRU_BUDGET_BYTES = 256 * 1024 * 1024;
export type GlbLease = Lease<THREE.Group>;

function resources(root: THREE.Object3D) {
  const geos = new Set<THREE.BufferGeometry>();
  const mats = new Set<THREE.Material>();
  const texs = new Set<THREE.Texture>();
  root.traverse((o) => {
    const mesh = o as THREE.Mesh;
    if (mesh.geometry) geos.add(mesh.geometry);
    for (const mat of ([] as (THREE.Material | undefined)[]).concat(mesh.material ?? [])) {
      if (!mat) continue;
      mats.add(mat);
      for (const [key, value] of Object.entries(mat)) {
        if (key !== 'envMap' && (value as THREE.Texture | null)?.isTexture) texs.add(value as THREE.Texture);
      }
    }
  });
  return { geos, mats, texs };
}

/** Release GPU allocations by identity; retain arrays and image sources. */
export function disposeGpu(root: THREE.Object3D): void {
  const { geos, mats, texs } = resources(root);
  geos.forEach(g => g.dispose()); mats.forEach(m => m.dispose()); texs.forEach(t => t.dispose());
}

/** Final CPU eviction closes each bitmap source once. Environment maps are shared. */
export function dropCpu(root: THREE.Object3D): void {
  const sources = new Set([...resources(root).texs].map(t => t.source));
  for (const source of sources) {
    if (typeof ImageBitmap !== 'undefined' && source.data instanceof ImageBitmap) source.data.close();
  }
}

/** Estimate unique backing buffers plus RGBA images with their mip chains. */
export function templateBytes(root: THREE.Object3D): number {
  const { geos, texs } = resources(root);
  const buffers = new Set<ArrayBufferLike>();
  const add = (attr: THREE.BufferAttribute | THREE.InterleavedBufferAttribute) => {
    buffers.add(('data' in attr ? attr.data.array : attr.array).buffer);
  };
  for (const geo of geos) {
    Object.values(geo.attributes).forEach(add);
    if (geo.index) add(geo.index);
    for (const attrs of Object.values(geo.morphAttributes)) attrs?.forEach(add);
  }
  let bytes = [...buffers].reduce((sum, buffer) => sum + buffer.byteLength, 0);
  const sources = new Set([...texs].map(t => t.source));
  for (const source of sources) {
    const image = source.data as { width?: number; height?: number } | null;
    if (image?.width && image?.height) bytes += image.width * image.height * 4 * 4 / 3;
  }
  return bytes;
}

// Priority belongs to the request that starts the shared load.
const loadNear = new Map<string, { near?: THREE.Vector3; pending: number }>();
const pool = createLeasePool<THREE.Group>({
  disposeGpu, dropCpu, bytes: templateBytes, budgetBytes: GLB_LRU_BUDGET_BYTES,
  load(url, signal) {
    const near = loadNear.get(url)?.near;
    return new Promise<THREE.Group | null>((resolve) => {
      const cancel = () => { glbQueue.cancel(url); };
      signal.addEventListener('abort', cancel, { once: true });
      void glbQueue.push({
        key: url,
        distance: () => near && loadFocus ? near.distanceToSquared(loadFocus) : Infinity,
        run: async () => {
          for (let attempt = 1; attempt <= LOAD_ATTEMPTS; attempt++) {
            try {
              const gltf = await loader.loadAsync(url);
              neutralizeGltfMaterials(gltf.scene);
              resolve(gltf.scene); return;
            } catch (error) {
              if (attempt === LOAD_ATTEMPTS) {
                console.warn(`[glb] ${url}: could not load after ${LOAD_ATTEMPTS} attempts`, error);
                resolve(null); return;
              }
              await sleep(RETRY_BASE_MS * 2 ** (attempt - 1));
            }
          }
        },
      }).then((result) => {
        if (result === 'cancelled') resolve(null);
      }).finally(() => { signal.removeEventListener('abort', cancel); });
      if (signal.aborted) cancel();
    });
  },
});

export function leaseGlb(url: string, near?: THREE.Vector3, signal?: AbortSignal): Promise<GlbLease | null> {
  const priority = loadNear.get(url) ?? { near, pending: 0 };
  loadNear.set(url, priority);
  priority.pending++;
  // Retain priority across a cancelled load that restarts for a new waiter.
  return pool.lease(url, signal).finally(() => {
    if (--priority.pending === 0) loadNear.delete(url);
  });
}
export function glbLeaseStats(): ReturnType<LeasePool<THREE.Group>['stats']> {
  return pool.stats();
}
