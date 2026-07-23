import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import type { ApiProp } from '../api';
import { propModelUrl } from '../api';
import { neutralizeGltfMaterials } from './buildings';

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

// Lade-Warteschlange: Prop-GLBs sind groß (bis ~25 MB) und zahlreich — alles
// gleichzeitig anzufordern verstopft die Browser-Verbindungen und lässt die
// gerade betrachtete Kachel genauso lange warten wie die entfernteste.
// Deshalb wenige parallele Downloads; der nächste Job ist immer der mit der
// kleinsten Distanz zum Kamera-Ziel (Fokus wird beim Slot-Freiwerden neu
// bewertet — zoomt der User woandershin, ordnet sich der Rest automatisch um).
const MAX_PARALLEL = 3;
let loadFocus: THREE.Vector3 | null = null;
/** Live-Referenz auf das Kamera-Ziel setzen (die Engine mutiert den Vektor
 *  in place, der Fokus bleibt damit von selbst aktuell). Ohne Fokus: FIFO. */
export function setPropLoadFocus(target: THREE.Vector3) {
  loadFocus = target;
}

const queue: { at?: THREE.Vector3; start: () => void }[] = [];
let active = 0;
function pump() {
  while (active < MAX_PARALLEL && queue.length) {
    const f = loadFocus;
    let idx = 0;
    if (f) {
      let best = Infinity;
      queue.forEach((j, i) => {
        const d = j.at ? j.at.distanceToSquared(f) : Infinity;
        if (d < best) { best = d; idx = i; }
      });
    }
    const [job] = queue.splice(idx, 1);
    active++;
    job.start();
  }
}

/** GLB laden (Promise-Cache pro id; parallele Aufrufe teilen den Load).
 *  `near` = Weltposition des Verwenders (Kachelzentrum) für die
 *  Priorisierung. Rückgabe: die ROHE Szene des glTF, unverändert.
 *  404/Fehler → null, fehlgeschlagene Loads nicht dauerhaft als null cachen
 *  (Retry möglich). Browser-HTTP-Cache + ETag erledigen die Revalidierung. */
export function loadPropModel(id: string, near?: THREE.Vector3): Promise<THREE.Group | null> {
  const cached = loadCache.get(id);
  if (cached) return cached;
  const pending = new Promise<THREE.Group | null>((resolve) => {
    queue.push({
      at: near,
      start: () => {
        loader.loadAsync(propModelUrl(id))
          .then((gltf) => {
            // gleiche Material-Behandlung wie Gebäude-/Raum-GLBs (Metalness/Env)
            neutralizeGltfMaterials(gltf.scene);
            resolve(gltf.scene);
          })
          .catch(() => {
            // 404/Fehler nicht dauerhaft festhalten -> Retry möglich
            loadCache.delete(id);
            resolve(null);
          })
          .finally(() => {
            active--;
            pump();
          });
      },
    });
    pump();
  });
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
