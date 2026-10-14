import * as THREE from 'three';
import { createFocusQueue } from '../game/focusQueue';
import { createGLTFLoader } from './gltfLoader';
import { neutralizeGltfMaterials } from './glbMaterials';

// Shared GLB queue for buildings, room dioramas and props. Returns RAW meshes:
// orientation, scale and position belong to the placement spec and the single
// place() routine (sceneRecipe.ts, contract § B2).
// Prop dimensions and orientation arrive with the spec (`dims` -> `max_m`,
// `fix_euler`); the client no longer needs a separate /assets/props library.
const loader = createGLTFLoader();
const loadCache = new Map<string, Promise<THREE.Group | null>>();

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

/** Load a raw glTF scene, sharing concurrent calls through a per-URL promise
 *  cache. `near` is the caller's world position (tile centre) for priority.
 *  place() applies the spec's fix_euler and measures the raw scene itself.
 *  Retry backoff keeps the slot occupied to avoid hammering a restarting
 *  backend. Final failure removes the cache entry so later calls can retry;
 *  the browser HTTP cache and ETag handle revalidation. */
export function loadGlb(url: string, near?: THREE.Vector3): Promise<THREE.Group | null> {
  const cached = loadCache.get(url);
  if (cached) return cached;
  const job = { at: near };
  const pending = new Promise<THREE.Group | null>((resolve) => {
    void glbQueue.push({
      key: url,
      distance: () => (job.at && loadFocus) ? job.at.distanceToSquared(loadFocus) : Infinity,
      run: async () => {
        for (let attempt = 1; attempt <= LOAD_ATTEMPTS; attempt++) {
          try {
            const gltf = await loader.loadAsync(url);
            // Match the material treatment of building and room GLBs.
            neutralizeGltfMaterials(gltf.scene);
            if (attempt > 1) console.info(`[glb] ${url}: loaded on attempt ${attempt}`);
            resolve(gltf.scene);
            return;
          } catch (e) {
            if (attempt === LOAD_ATTEMPTS) {
              console.warn(`[glb] ${url}: could not load after ${LOAD_ATTEMPTS} attempts`, e);
              loadCache.delete(url);
              resolve(null);
              return;
            }
            await sleep(RETRY_BASE_MS * 2 ** (attempt - 1));
          }
        }
      },
    });
  });
  loadCache.set(url, pending);
  return pending;
}
