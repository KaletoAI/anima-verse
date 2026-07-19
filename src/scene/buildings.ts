import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { getLocationModel, getRoomModel } from '../api';

/** frühestens nach dieser Zeit erneut fragen (Generierung dauert Minuten) */
const RETRY_MS = 60_000;

/** Neutrale Environment-Map für Modelle mit echter Metal-Roughness-Textur
 *  (AV3D-14) — ohne sie rendern metallische Pixel schwarz. */
let modelEnv: THREE.Texture | null = null;
export function setModelEnvironment(tex: THREE.Texture) {
  modelEnv = tex;
}

/** Vergleichs-Kennung über alle darstellungsrelevanten Meta-Felder. */
function metaSig(meta: ModelMeta): string {
  return JSON.stringify([
    meta.url, meta.signature, meta.rotation, meta.offset_y,
    meta.height_m, meta.floors, meta.width_m,
  ]);
}

interface ModelMeta {
  url: string;
  rotation?: { x?: number; y?: number; z?: number };
  /** Höhen-Feinjustierung in Metern */
  offset_y?: number;
  /** Maßstabs-Anker (backend-note-scale-anchors.md): 0 = nicht deklariert */
  height_m?: number;
  floors?: number;
  width_m?: number;
  /** Änderungs-Kennung (Cache-Invalidierung ohne Reload) */
  signature?: string;
}

/**
 * Server-Modelle (Gebäude AV3D-9, Räume AV3D-2), lazy pro ID.
 *
 * 404 ist der Normalfall — die prozedurale Darstellung bleibt. Während im
 * Admin-Panel generiert wird, kann der Endpoint kurzzeitig auch Nicht-GLB-
 * Zwischenstände liefern (beobachtet: das Referenz-PNG mit 200) — der
 * GLTF-Parser lehnt das ab und wir versuchen es beim nächsten Poll erneut.
 */
export class ModelLibrary {
  private models = new Map<string, THREE.Group>();
  private pending = new Set<string>();
  private retryAt = new Map<string, number>();
  private metaSigs = new Map<string, string>();
  /** wird gerufen, sobald ein Modell bereit ist */
  onModelReady: ((id: string) => void) | null = null;

  constructor(
    private tag: string,
    private fetchMeta: (id: string) => Promise<ModelMeta | null>,
    private normalize: (scene: THREE.Group, meta: ModelMeta) => THREE.Group,
  ) {}

  /** Instanz des geladenen Modells (Klon; Geometrie/Material geteilt). */
  get(id: string): THREE.Group | null {
    const template = this.models.get(id);
    return template ? template.clone() : null;
  }

  /** Cache verwerfen (z.B. wenn sich rotation/offset_y im Meta geändert hat). */
  invalidate(id: string) {
    this.models.delete(id);
    this.retryAt.delete(id);
    this.metaSigs.delete(id);
  }

  /** Meta-Sweep: neu generierte Modelle UND Regler-Änderungen (rotation/
   *  offset_y/Anker) ohne Reload erkennen — das komplette Meta vergleichen,
   *  nicht nur die Datei-signature. */
  async sweepSignatures() {
    for (const [id, known] of [...this.metaSigs]) {
      try {
        const meta = await this.fetchMeta(id);
        if (meta && metaSig(meta) !== known) {
          console.info(`[${this.tag}] ${id}: Meta geändert — lade neu`);
          this.invalidate(id);
          this.request(id);
        }
      } catch { /* Server kurz weg -> nächster Sweep */ }
    }
  }

  /** Modell nachladen, falls nicht vorhanden (drosselt sich selbst). */
  request(id: string) {
    if (this.models.has(id) || this.pending.has(id)) return;
    const at = this.retryAt.get(id);
    if (at !== undefined && performance.now() < at) return;
    this.pending.add(id);
    void (async () => {
      try {
        const meta = await this.fetchMeta(id);
        if (!meta) {
          this.retryAt.set(id, performance.now() + RETRY_MS);
          return;
        }
        const gltf = await new GLTFLoader().loadAsync(meta.url);
        // Generierte GLBs lassen metallicFactor oft unbelegt — der glTF-
        // Default ist 1.0 (voll metallisch), und ohne Environment-Map
        // rendert das fast schwarz. Gemeint ist kein Metall: neutralisieren.
        // Liefert das GLB dagegen eine echte Metal-Roughness-Textur
        // (AV3D-14), bleibt sie unangetastet — dann bekommt das Material
        // eine neutrale Environment-Map, damit Metall-Pixel reflektieren.
        gltf.scene.traverse((o) => {
          const mesh = o as THREE.Mesh;
          if (!mesh.isMesh) return;
          for (const m of Array.isArray(mesh.material) ? mesh.material : [mesh.material]) {
            const std = m as THREE.MeshStandardMaterial;
            if (!std.isMeshStandardMaterial) continue;
            if (std.metalnessMap) {
              if (modelEnv) {
                std.envMap = modelEnv;
                std.envMapIntensity = 0.7;
              }
            } else if (std.metalness > 0.5) {
              std.metalness = 0;
            }
          }
        });
        const model = this.normalize(gltf.scene, meta);
        model.userData.meta = {
          height_m: meta.height_m || 0, floors: meta.floors || 0,
          width_m: meta.width_m || 0, offset_y: meta.offset_y || 0,
          signature: meta.signature ?? '',
        };
        this.models.set(id, model);
        this.metaSigs.set(id, metaSig(meta));
        console.info(`[${this.tag}] ${id}: Modell vom Server`);
        this.onModelReady?.(id);
      } catch (e) {
        console.warn(`[${this.tag}] ${id}: Modell (noch) nicht ladbar — neuer Versuch folgt`, e);
        this.retryAt.set(id, performance.now() + RETRY_MS);
      } finally {
        this.pending.delete(id);
      }
    })();
  }
}

/** Flache Relief-Modelle: Bildseite nach oben drehen. Die Normalen der
 *  detaillierten Seite dominieren — zeigt die Mehrheit nach unten, ist das
 *  Relief verkehrt herum gelandet. */
function flipReliefFaceUp(scene: THREE.Group, size: THREE.Vector3) {
  if (size.y > Math.max(size.x, size.z) * 0.45) return;   // kein flaches Relief
  let sum = 0;
  const m = new THREE.Matrix3();
  const v = new THREE.Vector3();
  scene.updateMatrixWorld(true);
  scene.traverse((o) => {
    const mesh = o as THREE.Mesh;
    if (!mesh.isMesh) return;
    const normals = mesh.geometry.getAttribute('normal');
    if (!normals) return;
    m.getNormalMatrix(mesh.matrixWorld);
    const step = Math.max(1, Math.floor(normals.count / 1000));   // Stichprobe
    for (let i = 0; i < normals.count; i += step) {
      v.set(normals.getX(i), normals.getY(i), normals.getZ(i)).applyMatrix3(m);
      sum += v.y;
    }
  });
  if (sum < 0) {
    scene.rotateX(Math.PI);
    scene.updateMatrixWorld(true);
  }
}

/** Gebäude: nur den Meta-Rotations-Fix anwenden (Schritt 1 der Platzierungs-
 *  Kette aus backend-note-scale-anchors.md). Yaw, Skalierung und Gründung
 *  passieren pro Kachel in applyBuildingModel — die BBox muss dort NACH dem
 *  Karten-Yaw gemessen werden. */
export function buildingLibrary(): ModelLibrary {
  return new ModelLibrary('buildings', getLocationModel, (scene, meta) => {
    // Rotations-Fix aus dem Meta (Admin-Regler) hat Vorrang vor Heuristiken
    const r = meta.rotation;
    const explicit = !!r && ((r.x ?? 0) !== 0 || (r.y ?? 0) !== 0 || (r.z ?? 0) !== 0);
    if (explicit) {
      scene.rotation.set(
        THREE.MathUtils.degToRad(r!.x ?? 0),
        THREE.MathUtils.degToRad(r!.y ?? 0),
        THREE.MathUtils.degToRad(r!.z ?? 0)
      );
    }
    scene.updateMatrixWorld(true);
    const size = new THREE.Box3().setFromObject(scene).getSize(new THREE.Vector3());
    // KEIN Auto-Aufrichten mehr: Gebäude kommen als Y-up-GLB aus der
    // Pipeline; die alte Z-up-Heuristik kippte normale flach-tiefe Häuser
    // hochkant (Grenzfall Haus von Kai). Ausnahmen korrigiert der Admin
    // über meta.rotation.
    if (!explicit) flipReliefFaceUp(scene, size);
    // Mesh-Proportion nach Rotations-Fix (für die plan_width_m-Auto-Ableitung)
    const aspectXZoverY = Math.max(size.x, size.z) / Math.max(size.y, 1e-3);
    scene.traverse((o) => {
      if ((o as THREE.Mesh).isMesh) {
        o.castShadow = true;
        o.receiveShadow = false;
      }
    });
    const root = new THREE.Group();
    root.add(scene);
    root.userData.aspectXZoverY = aspectXZoverY;
    return root;
  });
}

/** Räume: Kette aus backend-note-scale-anchors.md (Raum-Rezept) —
 *  Schritt 1 hier: an der ROHEN BBox normalisieren (größte XZ-Seite = 1,
 *  XZ zentriert, Unterkante y = 0 — nie dem Pivot trauen, die Trellis-
 *  Meshes haben ihren Ursprung in der Box-MITTE). Der Fußabdruck fürs
 *  Fit stammt ebenfalls von der UNROTIERTEN Box. Danach Meta-Rotations-
 *  Fix als innere Gruppe; Fit, Layout-Yaw und die Neu-Erdung der
 *  rotierten Box passieren am Tile (applyRoomModel). */
export function roomModelLibrary(): ModelLibrary {
  return new ModelLibrary('rooms', getRoomModel, (scene, meta) => {
    const r = meta.rotation;
    const explicit = !!r && ((r.x ?? 0) !== 0 || (r.y ?? 0) !== 0 || (r.z ?? 0) !== 0);
    if (!explicit) {
      // Ohne Sidecar-Fix ersetzen Heuristiken den Meta-Fix und gehören
      // deshalb VOR die Roh-Messung: hochkant stehende Reliefs
      // (Bild-Generierung) flach legen, Bildseite nach oben.
      scene.updateMatrixWorld(true);
      let size = new THREE.Box3().setFromObject(scene).getSize(new THREE.Vector3());
      if (size.y > size.z * 1.8) {
        scene.rotation.x = -Math.PI / 2;
        scene.updateMatrixWorld(true);
        size = new THREE.Box3().setFromObject(scene).getSize(new THREE.Vector3());
      }
      flipReliefFaceUp(scene, size);
    }
    scene.updateMatrixWorld(true);
    const size = new THREE.Box3().setFromObject(scene).getSize(new THREE.Vector3());
    const s = 1 / Math.max(size.x, size.z, 1e-3);
    scene.scale.multiplyScalar(s);
    scene.updateMatrixWorld(true);
    const box = new THREE.Box3().setFromObject(scene);
    const c = box.getCenter(new THREE.Vector3());
    scene.position.x -= c.x;
    scene.position.z -= c.z;
    scene.position.y -= box.min.y;
    scene.traverse((o) => {
      if ((o as THREE.Mesh).isMesh) {
        o.castShadow = false;                    // Innenraum wirft keine Karten-Schatten
        o.receiveShadow = false;
      }
    });
    // Meta-Rotations-Fix als eigene innere Gruppe ÜBER der Normalisierung
    const metaG = new THREE.Group();
    metaG.add(scene);
    if (explicit) {
      metaG.rotation.set(
        THREE.MathUtils.degToRad(r!.x ?? 0),
        THREE.MathUtils.degToRad(r!.y ?? 0),
        THREE.MathUtils.degToRad(r!.z ?? 0)
      );
    }
    const root = new THREE.Group();
    root.add(metaG);
    root.userData.footprint = { x: size.x * s, z: size.z * s };
    root.userData.height = size.y * s;
    root.userData.offsetY = meta.offset_y ?? 0;
    return root;
  });
}
