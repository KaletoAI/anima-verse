import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import type { ApiProp } from '../api';
import { propModelUrl } from '../api';

// Prop-Assets (Raum-Rezept, Abschnitt 2b/2c): Bibliotheks-Cache, GLB-Loading,
// Platzhalter. KEIN Orientierungs-Fix, NICHT skalieren, NICHT positionieren —
// die Platzierungskette baut die Integration und erwartet hier rohe Meshes.

const library = new Map<string, ApiProp>();

/** Bibliothek setzen (einmalig beim Start aus getProps()). */
export function setPropLibrary(list: ApiProp[]): void {
  library.clear();
  for (const p of list) if (p?.id) library.set(p.id, p);
}

export function propInfo(id: string): ApiProp | undefined {
  return library.get(id);
}

const loader = new GLTFLoader();
const loadCache = new Map<string, Promise<THREE.Group | null>>();

/** GLB laden (Promise-Cache pro id; parallele Aufrufe teilen den Load).
 *  Rückgabe: die ROHE Szene des glTF, unverändert. 404/Fehler → null,
 *  fehlgeschlagene Loads nicht dauerhaft als null cachen (Retry möglich).
 *  Browser-HTTP-Cache + ETag erledigen die Revalidierung. */
export async function loadPropModel(id: string): Promise<THREE.Group | null> {
  const cached = loadCache.get(id);
  if (cached) return cached;
  const pending = (async () => {
    try {
      const gltf = await loader.loadAsync(propModelUrl(id));
      return gltf.scene;
    } catch {
      // 404/Fehler nicht dauerhaft festhalten -> Eintrag löschen, Retry möglich
      loadCache.delete(id);
      return null;
    }
  })();
  loadCache.set(id, pending);
  return pending;
}

/** Platzhalter für missing / has_model:false — Box in Realgröße dims × k,
 *  halbtransparent neutral-grau, Ursprung = ZENTRUM DER UNTERKANTE
 *  (die Integration setzt ihn direkt auf den Platzierungspunkt). */
export function buildPropPlaceholder(
  dims: { width_m: number; depth_m: number; height_m: number },
  k: number
): THREE.Object3D {
  const w = Math.max(dims.width_m * k, 0.01);
  const h = Math.max(dims.height_m * k, 0.01);
  const d = Math.max(dims.depth_m * k, 0.01);
  const geo = new THREE.BoxGeometry(w, h, d);
  geo.translate(0, h / 2, 0);   // Ursprung an das Zentrum der Unterkante legen
  const mesh = new THREE.Mesh(
    geo,
    new THREE.MeshStandardMaterial({
      color: 0x9a9a9a, roughness: 0.9, metalness: 0.0,
      transparent: true, opacity: 0.5,
    })
  );
  mesh.castShadow = false;
  mesh.receiveShadow = true;
  return mesh;
}
