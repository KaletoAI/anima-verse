import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { neutralizeGltfMaterials } from './glbMaterials';

// GLB-Ladewarteschlange für alle Modelle der Szene (Gebäude, Raum-Dioramen,
// Props). Liefert ROHE Meshes: kein Orientierungs-Fix, keine Skalierung,
// keine Position — all das steht in der Platzierungs-Spec und läuft durch
// die eine place()-Routine (sceneRecipe.ts, Vertrag § B2).
//
// Eine Prop-BIBLIOTHEK gibt es hier nicht mehr: Maße und Orientierungs-Fix
// eines Props kommen mit seiner Spec (`dims` → `max_m`, `fix_euler`), der
// Client muss /assets/props nicht mehr kennen.

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

/** Wiederholungen je Modell, bevor es als „nicht ladbar" gilt.
 *  Der Server ist unter paralleler Last nachweislich stabil (Fable
 *  2026-07-26: 120 gleichzeitige GETs → 120 × 200, 30 Conditional-GETs
 *  → 30 × 304, kein Rate-Limit); 5xx entsteht dort praktisch nur während
 *  eines Backend-Neustarts. Genau dieser Fall war die Lücke: ein einzelner
 *  Fehlschlag ließ das Modell für die ganze Sitzung verschwinden. */
const LOAD_ATTEMPTS = 3;
const RETRY_BASE_MS = 800;
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** GLB per URL laden (Promise-Cache pro URL; parallele Aufrufe teilen den
 *  Load). `near` = Weltposition des Verwenders (Kachelzentrum) für die
 *  Priorisierung. Rückgabe: die ROHE Szene des glTF, unverändert — kein
 *  Orientierungs-Fix, keine Skalierung, keine Position. Genau das braucht
 *  die place()-Routine des Szenen-Rezepts (§ B2): sie wendet fix_euler aus
 *  der Spec selbst an und misst danach.
 *
 *  Fehlschläge werden mit Backoff wiederholt (der Slot bleibt dabei belegt —
 *  gewollt: reißt das Backend gerade weg, soll die Queue warten statt zu
 *  hämmern). Erst danach null, und der Cache-Eintrag wird verworfen, damit
 *  ein späterer Aufruf erneut versuchen darf. Browser-HTTP-Cache + ETag
 *  erledigen die Revalidierung. */
export function loadGlb(url: string, near?: THREE.Vector3): Promise<THREE.Group | null> {
  const cached = loadCache.get(url);
  if (cached) return cached;
  const pending = new Promise<THREE.Group | null>((resolve) => {
    queue.push({
      at: near,
      start: () => {
        void (async () => {
          try {
            for (let attempt = 1; attempt <= LOAD_ATTEMPTS; attempt++) {
              try {
                const gltf = await loader.loadAsync(url);
                // gleiche Material-Behandlung wie Gebäude-/Raum-GLBs (Metalness/Env)
                neutralizeGltfMaterials(gltf.scene);
                if (attempt > 1) console.info(`[glb] ${url}: geladen im Versuch ${attempt}`);
                resolve(gltf.scene);
                return;
              } catch (e) {
                if (attempt === LOAD_ATTEMPTS) {
                  console.warn(`[glb] ${url}: nach ${LOAD_ATTEMPTS} Versuchen nicht ladbar`, e);
                  loadCache.delete(url);
                  resolve(null);
                  return;
                }
                await sleep(RETRY_BASE_MS * 2 ** (attempt - 1));
              }
            }
          } finally {
            active--;
            pump();
          }
        })();
      },
    });
    pump();
  });
  loadCache.set(url, pending);
  return pending;
}

