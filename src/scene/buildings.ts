import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { getLocationModel } from '../api';
import { CELL } from './tiles';

/** frühestens nach dieser Zeit erneut fragen (Generierung dauert Minuten) */
const RETRY_MS = 60_000;

/**
 * Gebäude-Modelle vom Server (AV3D-9), lazy pro Location.
 *
 * 404 ist der Normalfall — das prozedurale Gebäude bleibt stehen. Während im
 * Admin-Panel generiert wird, kann der Endpoint kurzzeitig auch Nicht-GLB-
 * Zwischenstände liefern (beobachtet: das Referenz-PNG mit 200) — der
 * GLTF-Parser lehnt das ab und wir versuchen es beim nächsten Poll erneut.
 */
export class BuildingLibrary {
  private models = new Map<string, THREE.Group>();
  private pending = new Set<string>();
  private retryAt = new Map<string, number>();
  /** wird gerufen, sobald ein Gebäude-Modell bereit ist */
  onModelReady: ((locationId: string) => void) | null = null;

  /** Instanz des geladenen Modells (Klon; Geometrie/Material geteilt). */
  get(locationId: string): THREE.Group | null {
    const template = this.models.get(locationId);
    return template ? template.clone() : null;
  }

  /** Modell nachladen, falls nicht vorhanden (drosselt sich selbst). */
  request(locationId: string) {
    if (this.models.has(locationId) || this.pending.has(locationId)) return;
    const at = this.retryAt.get(locationId);
    if (at !== undefined && performance.now() < at) return;
    this.pending.add(locationId);
    void (async () => {
      try {
        const meta = await getLocationModel(locationId);
        if (!meta) {
          this.retryAt.set(locationId, performance.now() + RETRY_MS);
          return;
        }
        const gltf = await new GLTFLoader().loadAsync(meta.url);
        const model = this.normalize(gltf.scene);
        this.models.set(locationId, model);
        console.info(`[buildings] ${locationId}: Gebäude-Modell vom Server (${(model.userData.height as number).toFixed(1)} m hoch)`);
        this.onModelReady?.(locationId);
      } catch (e) {
        console.warn(`[buildings] ${locationId}: Modell (noch) nicht ladbar — neuer Versuch folgt`, e);
        this.retryAt.set(locationId, performance.now() + RETRY_MS);
      } finally {
        this.pending.delete(locationId);
      }
    })();
  }

  /** Aufrichten, auf die Kachel skalieren, XZ zentrieren, Unterkante auf y=0. */
  private normalize(scene: THREE.Group): THREE.Group {
    scene.updateMatrixWorld(true);
    let box = new THREE.Box3().setFromObject(scene);
    let size = box.getSize(new THREE.Vector3());
    // Z-up-Export aufrichten — aber nur, wenn dabei keine "Papierwand"
    // entsteht: flache Relief-Modelle (dünn in Y) sind flach gemeint und
    // würden aufgerichtet als dünne schiefe Wand auf der Kachel stehen.
    if (size.z > size.y * 1.8 && size.y > Math.max(size.x, size.z) * 0.2) {
      scene.rotation.x = -Math.PI / 2;
      scene.updateMatrixWorld(true);
      box = new THREE.Box3().setFromObject(scene);
      size = box.getSize(new THREE.Vector3());
    }
    const s = (CELL * 0.92) / Math.max(size.x, size.z, 1e-3);
    scene.scale.setScalar(s);
    scene.updateMatrixWorld(true);
    box = new THREE.Box3().setFromObject(scene);
    const c = box.getCenter(new THREE.Vector3());
    scene.position.x -= c.x;
    scene.position.z -= c.z;
    scene.position.y -= box.min.y - 0.06;        // knapp über der Sockel-Platte
    scene.traverse((o) => {
      if ((o as THREE.Mesh).isMesh) {
        o.castShadow = true;
        o.receiveShadow = false;
      }
    });
    const root = new THREE.Group();
    root.add(scene);
    root.userData.height = box.max.y - box.min.y;
    return root;
  }
}
