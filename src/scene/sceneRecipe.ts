import * as THREE from 'three';
import { CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import {
  getLocationScene,
  type SceneModelSpec, type ScenePayload, type ScenePlate, type SceneWall,
} from '../api';
import { BASE_FIGURE_HEIGHT_M } from './figures';
import { loadGlb } from './propAssets';
import {
  preloadSurfaceTexture, sampleRoomWalkables, setLocationAnchor, surfaceFor,
  type Tile,
} from './tiles';

/**
 * Szenen-Rezept (schnittstellen-3d.md Teil B) — der Server rechnet, der
 * Client stellt dar.
 *
 * EIN Endpoint liefert die komplette Szene einer Location als fertige
 * Primitive (plates/walls/extras) und Platzierungs-Specs (models). Dieses
 * Modul besitzt daher genau ZWEI generische Routinen — `placeSpec` („Modell
 * platzieren", § B2) und die Primitiv-Builder („Primitiv bauen") — und keine
 * einzige eigene Geometrie-Entscheidung: keine Öffnungs-Aufteilung, keine
 * Spiegelung, keine Exit-Ableitung, keine Fahrstuhl-Maße, keine Konstanten
 * (0,07 / 0,14 / 0,12 / ±0,4 …) und keine Farben. Alles davon kommt aus dem
 * Payload; die einzige Geometrie-Zahl auf dieser Seite ist der 0,96-Rand des
 * `fit_box`-Fallbacks, den § B2 ausdrücklich hier verortet.
 *
 * Was hier bleibt, ist Sicht- und Interaktions-Zustand: `mountScene` füllt
 * die Tile-Felder der Innenansicht, damit LOD,
 * Crossfade, Etagen-Umschalter, Raum-Fokus, Wand-Culling, NPC-Platzierung und
 * Wegfindung unverändert weiterlaufen.
 *
 * 404 auf /scene = Legacy-Fall (kein Grundriss, kein Layout, kein Modell) —
 * dann rührt dieses Modul die Kachel nicht an.
 */

/** Der EINE Rand, den § B2 auf der Client-Seite lässt (fit_box-Fallback). */
const FIT_BOX_MARGIN = 0.96;
/** Verify-Toleranz in Welt-Metern (§ B5a). */
const VERIFY_EPS = 0.01;

const deg = (v: number | undefined) => ((v || 0) * Math.PI) / 180;

function std(opts: THREE.MeshStandardMaterialParameters): THREE.MeshStandardMaterial {
  return new THREE.MeshStandardMaterial({ roughness: 0.85, metalness: 0.02, ...opts });
}

/** '#rrggbb' → THREE.Color; unbrauchbar/fehlend → weiß (das Payload IST die
 *  Quelle, es gibt hier bewusst keine zweite Farbtabelle). */
function hex(c: string | undefined): THREE.Color {
  const v = parseInt((c || '').replace('#', ''), 16);
  return new THREE.Color(Number.isFinite(v) ? v : 0xffffff);
}

// ── Szenen-Bibliothek: Signatur-Polling wie beim Raum-Rezept ──────────────

/** Szene pro Location mit signature-Polling: request() holt einmalig (404 =
 *  nichts zu komponieren → null), sweep() fragt bekannte Locations erneut und
 *  meldet Änderungen über onScene. Die Signatur deckt map3d, ALLE Raum-Layouts,
 *  die Modell-Metas und die Prop-Sidecars ab — Polling genügt (§ B1). */
export class SceneLibrary {
  private cache = new Map<string, ScenePayload | null>();
  private pending = new Set<string>();
  onScene?: (locationId: string, scene: ScenePayload | null) => void;

  get(locationId: string): ScenePayload | null | undefined {
    return this.cache.get(locationId);
  }

  /** true = für diese Location gilt der Szenen-Pfad (Payload vorhanden). */
  has(locationId: string): boolean {
    return !!this.cache.get(locationId);
  }

  /** Szenen VOR dem ersten Kachelbau holen (kein onScene, kein Remount): so
   *  entsteht die Kachel gleich im richtigen Modus statt legacy gebaut und
   *  sofort wieder verworfen zu werden. Fehler bleiben ungecacht — der
   *  normale request/sweep-Zyklus holt sie nach. */
  async prime(locationIds: string[]): Promise<void> {
    await Promise.all(locationIds.map(async (id) => {
      if (this.cache.has(id)) return;
      try {
        this.cache.set(id, await getLocationScene(id));
      } catch { /* nächster Zyklus fragt neu */ }
    }));
    const n = [...this.cache.values()].filter(Boolean).length;
    console.info(`[scene] ${n}/${locationIds.length} Locations mit Szenen-Rezept`);
  }

  request(locationId: string): void {
    if (this.cache.has(locationId) || this.pending.has(locationId)) return;
    this.pending.add(locationId);
    getLocationScene(locationId)
      .then((scene) => {
        this.cache.set(locationId, scene);
        if (scene) {
          console.info(`[scene] ${locationId}: ${scene.plates.length} Platten, `
            + `${scene.walls.length} Wandsegmente, ${scene.extras.length} Extras, `
            + `${scene.models.length} Modelle (k=${scene.k}, storey=${scene.storey_m})`);
        }
        this.onScene?.(locationId, scene);
      })
      // Netzwerk/5xx: nicht als "keine Szene" cachen, nächster Zyklus fragt neu
      .catch((e) => console.warn(`[scene] ${locationId}: (noch) nicht ladbar — neuer Versuch folgt`, e))
      .finally(() => this.pending.delete(locationId));
  }

  async sweep(): Promise<void> {
    for (const [locationId, prev] of [...this.cache]) {
      try {
        const fresh = await getLocationScene(locationId);
        const changed = (prev?.signature ?? null) !== (fresh?.signature ?? null);
        this.cache.set(locationId, fresh);
        if (changed) this.onScene?.(locationId, fresh);
      } catch { /* Server kurz weg -> nächster Sweep */ }
    }
  }
}

// ── Verify (§ B5a): Arithmetik statt Screenshots ──────────────────────────

export interface VerifyRow {
  object: string;
  field: string;
  actual: number;
  target: number;
  delta: number;
}

export interface VerifyReport {
  location: string;
  checked: number;
  rows: VerifyRow[];
  /** Modell-Specs, die gar nicht platziert wurden (Mesh nicht ladbar). Eine
   *  übersprungene Spec ist ein FEHLENDES Objekt in der Szene und darf nicht
   *  als „geprüft und in Ordnung" durchgehen — sie zählt als Abweichung. */
  skipped: number;
  models: { placed: number; total: number };
  /** Beschnittene Dioramen (§ B1 clip_outline) mit ihrer Punktzahl. */
  clips: { object: string; punkte: number }[];
}

/** Verify-Modus aus: `?verify=1` in der URL oder `window.__verify3d = true`
 *  (zur Laufzeit umschaltbar; wirkt beim nächsten Mount). */
function verifyOn(): boolean {
  const w = window as unknown as { __verify3d?: boolean };
  if (w.__verify3d !== undefined) return !!w.__verify3d;
  try {
    return new URLSearchParams(location.search).get('verify') === '1';
  } catch {
    return false;
  }
}

/** Das Szenen-Rezept ist das SOLL: nach dem Aufbau wird jedes Objekt neu in
 *  Weltkoordinaten vermessen und gegen die Spec gedifft. Befunde reisen als
 *  ZAHLEN zwischen den Sessions (Objekt, Feld, Ist, Soll), nie als Bild. */
class Verifier {
  rows: VerifyRow[] = [];
  checked = 0;
  skipped = 0;
  placed = 0;
  total = 0;
  clips: { object: string; punkte: number }[] = [];
  constructor(readonly active: boolean) {}

  /** Eine Modell-Spec, die NICHT platziert wurde (Mesh nach allen Versuchen
   *  nicht ladbar, kein Platzhalter). Das ist ein fehlendes Objekt in der
   *  Szene — es wandert als Abweichungszeile in die Tabelle (`geladen` 0
   *  statt 1), damit eine Lücke nicht wie ein Erfolg aussieht. Wird
   *  unabhängig vom Verify-Modus gezählt und geloggt. */
  /** Beschnittenes Diorama vermerken (§ B1 clip_outline). Keine Abweichung,
   *  sondern eine Eigenschaft des Aufbaus — sie gehört trotzdem in die
   *  Ausgabe, sonst sieht man einem fehlenden Möbelstück nicht an, ob es
   *  weggeclippt oder gar nicht geladen wurde. */
  clipped(spec: SceneModelSpec, points: number): void {
    this.clips.push({ object: `${spec.role}:${spec.id}`, punkte: points });
  }

  skip(spec: SceneModelSpec): void {
    this.skipped += 1;
    console.warn(`[scene] ${spec.role}:${spec.id} übersprungen — Mesh nicht ladbar `
      + `(${spec.url || 'ohne URL'})`);
    if (!this.active) return;
    this.checked += 1;
    this.rows.push({ object: `${spec.role}:${spec.id}`, field: 'geladen',
                     actual: 0, target: 1, delta: -1 });
  }

  check(object: string, field: string, actual: number, target: number): void {
    if (!this.active) return;
    this.checked += 1;
    const delta = actual - target;
    if (Math.abs(delta) > VERIFY_EPS) {
      const r3 = (v: number) => Math.round(v * 1000) / 1000;
      this.rows.push({ object, field, actual: r3(actual), target: r3(target), delta: r3(delta) });
    }
  }

  /** Primitiv gegen seine Spec prüfen: Welt-BBox messen und die vom Payload
   *  vorgegebenen Kanten/Mitten diffen. `origin` = Weltposition des
   *  Kachelzentrums (die Spec rechnet um das Kachelzentrum). */
  primitive(mesh: THREE.Object3D, origin: THREE.Vector3, name: string,
            targets: { field: string; actual: (b: THREE.Box3) => number; target: number }[]): void {
    if (!this.active) return;
    mesh.updateWorldMatrix(true, true);   // Eltern MIT — sonst misst man eine kalte Matrix
    const box = new THREE.Box3().setFromObject(mesh);
    box.min.sub(origin);
    box.max.sub(origin);
    for (const t of targets) this.check(name, t.field, t.actual(box), t.target);
  }

  /** Platziertes Modell gegen seine Spec prüfen. `origin` = Weltposition des
   *  Kachelzentrums: die Spec rechnet um das Kachelzentrum, die Messung liegt
   *  in Weltkoordinaten. */
  placement(obj: THREE.Object3D, spec: SceneModelSpec, origin: THREE.Vector3): void {
    if (!this.active) return;
    obj.updateWorldMatrix(true, true);   // Eltern MIT — sonst misst man eine kalte Matrix
    const box = new THREE.Box3().setFromObject(obj);
    const size = box.getSize(new THREE.Vector3());
    const centre = box.getCenter(new THREE.Vector3());
    const name = `${spec.role}:${spec.id}`;
    this.check(name, 'bottom_y', box.min.y - origin.y, spec.bottom_y);
    this.check(name, 'anchor.x', centre.x - origin.x, spec.anchor[0]);
    this.check(name, 'anchor.z', centre.z - origin.z, spec.anchor[1]);
    // Ausdehnungs-Prüfungen gelten nur bei achsenparallelen Yaws — die
    // Welt-BBox eines diagonal gedrehten Meshes ist legitim größer als die
    // Zielbox.
    if (Math.abs(((spec.yaw_deg % 90) + 90) % 90) > 0.01) return;
    if (spec.scale_mode === 'real_size' && spec.max_m) {
      this.check(name, 'max_m', spec.measure_axes === 'xz'
        ? Math.max(size.x, size.z) : Math.max(size.x, size.y, size.z), spec.max_m);
    } else if (spec.scale_mode === 'tile_fit' && spec.box) {
      if (spec.box.xz) this.check(name, 'box.xz', Math.max(size.x, size.z), spec.box.xz);
      if (spec.box.y) this.check(name, 'box.y', size.y, spec.box.y);
    }
  }

  report(locationId: string): VerifyReport | null {
    if (!this.active) return null;
    const out: VerifyReport = {
      location: locationId, checked: this.checked, rows: this.rows,
      skipped: this.skipped, models: { placed: this.placed, total: this.total },
      clips: this.clips,
    };
    const modelInfo = `Modelle ${this.placed}/${this.total}`
      + (this.clips.length ? `, ${this.clips.length} beschnitten` : '');
    if (this.rows.length) {
      console.warn(`[verify] ${locationId}: ${this.rows.length} Abweichung(en) `
        + `bei ${this.checked} geprüften Zahlen (${modelInfo}, `
        + `${this.skipped} übersprungen), Toleranz ${VERIFY_EPS} m`);
      console.table(this.rows);
    } else {
      console.info(`[verify] ${locationId}: ${this.checked} Zahlen geprüft, `
        + `keine Abweichung > ${VERIFY_EPS} m (${modelInfo})`);
    }
    if (this.clips.length) console.table(this.clips);
    const w = window as unknown as { __sceneVerify?: Record<string, VerifyReport> };
    w.__sceneVerify = { ...(w.__sceneVerify ?? {}), [locationId]: out };
    return out;
  }
}

// ── DIE Platzierungs-Routine (§ B2) ───────────────────────────────────────

/**
 * Gebäude, Raum-Diorama und Prop unterscheiden sich nur in der SPEC, die der
 * Server schickt — nie im Code. Kette: fix_euler ('XYZ') auf die innere
 * Gruppe → messen → skalieren nach scale_mode → Yaw als ELTERN-Rotation (nie
 * in einen Euler kombinieren, ein x/z-Fix würde mitkippen) → Ergebnis-BBox
 * messen und Unterkante/XZ-Zentrum auf bottom_y/anchor setzen.
 *
 * Rückgabe: eine Hülle um `source`. Der Aufrufer hängt sie in eine Gruppe
 * OHNE eigene Transformation (die Erdung misst im Eltern-Koordinatensystem,
 * und die Spec-Zahlen gelten um das Kachelzentrum).
 */
export function placeSpec(source: THREE.Object3D, spec: SceneModelSpec): THREE.Group {
  const fix = new THREE.Group();
  fix.add(source);
  fix.rotation.set(deg(spec.fix_euler?.x), deg(spec.fix_euler?.y), deg(spec.fix_euler?.z));
  fix.updateMatrixWorld(true);
  const sFix = new THREE.Box3().setFromObject(fix).getSize(new THREE.Vector3());

  const yawG = new THREE.Group();
  yawG.add(fix);
  yawG.rotation.y = -deg(spec.yaw_deg);
  yawG.updateMatrixWorld(true);
  const sYaw = new THREE.Box3().setFromObject(yawG).getSize(new THREE.Vector3());

  const outer = new THREE.Group();
  outer.add(yawG);
  if (spec.scale_axes) {
    // Server-vermessenes Mesh: die Faktoren kommen fertig (§ B4).
    outer.scale.set(spec.scale_axes.xz, spec.scale_axes.y, spec.scale_axes.xz);
  } else if (spec.scale_mode === 'tile_fit') {
    // Gebäude füllen ihre Kachel je ACHSE, gemessen an der GEDREHTEN Box:
    // der Fußabdruck folgt dem Grundriss, die Höhe ihren deklarierten Metern.
    const kxz = (spec.box?.xz || 1) / (Math.max(sYaw.x, sYaw.z) || 1);
    const ky = spec.box?.y ? spec.box.y / (sYaw.y || 1) : kxz;
    outer.scale.set(kxz, ky, kxz);
  } else if (spec.scale_mode === 'real_size') {
    // EIN Maßstabsgesetz: reale Meter über der größten gemessenen Ausdehnung.
    // measure_axes 'xz' ignoriert die Höhe (Dioramen, § B2a).
    const maxExtent = (spec.measure_axes === 'xz'
      ? Math.max(sFix.x, sFix.z)
      : Math.max(sFix.x, sFix.y, sFix.z)) || 1;
    outer.scale.setScalar((spec.max_m || 1) / maxExtent);
  } else {
    // fit_box-Fallback: den UNROTIERTEN Fußabdruck in die Zielbox einpassen.
    outer.scale.setScalar(Math.min((spec.box?.w || 1) / (sFix.x || 1),
                                   (spec.box?.d || 1) / (sFix.z || 1)) * FIT_BOX_MARGIN);
  }
  outer.updateMatrixWorld(true);
  const bOut = new THREE.Box3().setFromObject(outer);
  const cOut = bOut.getCenter(new THREE.Vector3());
  outer.position.set(spec.anchor[0] - cOut.x,
                     spec.bottom_y - bOut.min.y,
                     spec.anchor[1] - cOut.z);
  return outer;
}

// ── Primitiv-Builder ─────────────────────────────────────────────────────

/** Kachelbare Surface-Textur eines Kinds im WELT-Maßstab (size_m × k).
 *  Box- und Extrude-UVs brauchen je Stück einen Klon mit eigener repeat.
 *  `use` steuert die Fallback-Kette von surfaceFor: Böden fallen auf das
 *  globale "floor"-Kind zurück, Wände nicht (sonst klebt Bodenbelag an der
 *  Wand). */
function tiledTexture(kind: string | undefined, use: 'floor' | 'wall', k: number,
                      repeat: (tileM: number) => [number, number]): THREE.Texture | null {
  const surf = kind ? surfaceFor(kind, use) : null;
  if (!surf) return null;
  const tex = surf.texture.clone();
  tex.needsUpdate = true;
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  const [rx, ry] = repeat(surf.sizeM * k);
  tex.repeat.set(rx, ry);
  return tex;
}

/** Bodenplatte aus einem fertigen Primitiv: `thickness > 0` = nach unten
 *  extrudierter Körper mit Oberkante auf `top_y`, `thickness 0` = reine
 *  Textur-Fläche ohne Körper (Outdoor-Räume, § A5). */
function buildPlate(plate: ScenePlate, k: number, style: ScenePayload['style']): THREE.Mesh {
  const solid = plate.thickness > 0;
  const upper = plate.opacity_role === 'upper';
  const shape = new THREE.Shape();
  plate.outline.forEach(([px, pz], i) => {
    // Extrudierte Platten gehen als (x, z) hinein und drehen +90° (die
    // Extrusion läuft dann nach unten); flache als (x, −z) mit −90°.
    const sy = solid ? pz : -pz;
    if (i === 0) shape.moveTo(px, sy);
    else shape.lineTo(px, sy);
  });
  shape.closePath();
  const opacity = upper ? (style.upper_floor_opacity ?? 1) : 1;
  const tex = tiledTexture(plate.texture_kind, 'floor', k, (tileM) => [1 / tileM, 1 / tileM]);
  const mat = std(tex
    ? { map: tex, transparent: upper, opacity, side: solid ? THREE.FrontSide : THREE.DoubleSide }
    : { color: hex(style.floor_color), transparent: upper, opacity, side: solid ? THREE.FrontSide : THREE.DoubleSide });
  const mesh = new THREE.Mesh(
    solid
      ? new THREE.ExtrudeGeometry(shape, { depth: plate.thickness, bevelEnabled: false })
      : new THREE.ShapeGeometry(shape),
    mat);
  mesh.rotation.x = solid ? Math.PI / 2 : -Math.PI / 2;
  mesh.position.y = plate.top_y;
  mesh.receiveShadow = true;
  mesh.castShadow = plate.level > 0 && solid;
  return mesh;
}

/** Wandsegment aus einem fertigen Primitiv: Türen/Passagen sind bereits
 *  Lücken, ein Fenster kommt als Brüstung + Sturz + eigener Glas-Eintrag —
 *  je eine Box, nichts wird hier geteilt. */
function buildWall(wall: SceneWall, k: number, style: ScenePayload['style'],
                   len: number): THREE.Mesh {
  const upper = wall.opacity_role === 'upper';
  let mat: THREE.MeshStandardMaterial;
  if (wall.glass) {
    mat = std({ color: hex(style.glass_color), transparent: true,
                opacity: style.glass_opacity ?? 0.25, roughness: 0.3 });
  } else {
    const tex = tiledTexture(wall.texture_kind, 'wall', k,
      (tileM) => [len / tileM, wall.height / tileM]);
    const opacity = upper ? (style.upper_wall_opacity ?? 1) : 1;
    mat = std(tex
      ? { map: tex, transparent: upper, opacity }
      : { color: hex(style.wall_color), transparent: upper, opacity });
  }
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(len, wall.height, wall.thickness), mat);
  const mx = (wall.from[0] + wall.to[0]) / 2;
  const mz = (wall.from[1] + wall.to[1]) / 2;
  mesh.position.set(mx, wall.base_y + wall.height / 2, mz);
  mesh.rotation.y = -Math.atan2(wall.to[1] - wall.from[1], wall.to[0] - wall.from[0]);
  mesh.castShadow = false;
  mesh.receiveShadow = false;
  return mesh;
}

// ── Raum-Clipping (§ B1 `clip_outline`) ──────────────────────────────────

/** Obergrenze des Vertrags; das Uniform-Array trägt einen Punkt mehr, weil
 *  das Polygon geschlossen hochgeladen wird (letzter Punkt = erster). */
const CLIP_MAX_POINTS = 32;

/**
 * Ein Diorama auf seinen Raum beschneiden: Fragmente außerhalb des
 * gelieferten Polygons werden verworfen.
 *
 * Warum Fragment-Discard und nicht `clippingPlanes`: der Grundriss ist ein
 * beliebiges Polygon, keine Handvoll Halbräume — Ebenen bräuchten pro Kante
 * eine und würden bei konkaven Umrissen falsch schneiden. Der Paritätstest
 * (Punkt-im-Polygon) ist dagegen exakt und kostet einen kurzen Loop.
 *
 * Die Schnittkanten bleiben OFFEN (das Mesh wird nicht verschlossen) —
 * deshalb DoubleSide, damit man von außen nicht durch die Rückseite ins
 * Nichts schaut. Bekannt und laut Auftrag akzeptiert.
 *
 * Materialien werden vorher GEKLONT: `loadGlb` cacht die rohe Szene, und
 * `clone(true)` teilt die Materialien — ohne Klon würde derselbe Patch auch
 * bei jeder anderen Verwendung desselben GLB zuschlagen.
 */
function applyRoomClip(model: THREE.Object3D, outlineWorld: THREE.Vector2[]): void {
  const poly: THREE.Vector2[] = [];
  for (let i = 0; i <= CLIP_MAX_POINTS; i++) {
    poly.push(outlineWorld[Math.min(i, outlineWorld.length - 1)].clone());
  }
  // geschlossen hochladen: Kante i = poly[i] -> poly[i+1]; der Loop im Shader
  // darf damit mit konstantem i+1 indizieren (GLSL-ES-Regel für Uniform-Arrays)
  poly[outlineWorld.length] = outlineWorld[0].clone();
  const count = outlineWorld.length;

  model.traverse((o) => {
    const mesh = o as THREE.Mesh;
    if (!mesh.isMesh) return;
    const patch = (src: THREE.Material): THREE.Material => {
      const m = src.clone();
      m.side = THREE.DoubleSide;
      m.onBeforeCompile = (shader) => {
        shader.uniforms.uClipPoly = { value: poly };
        shader.uniforms.uClipCount = { value: count };
        shader.vertexShader = `varying vec3 vClipWorld;\n${shader.vertexShader}`
          .replace('#include <project_vertex>',
            'vClipWorld = (modelMatrix * vec4(transformed, 1.0)).xyz;\n'
            + '#include <project_vertex>');
        shader.fragmentShader = `uniform vec2 uClipPoly[${CLIP_MAX_POINTS + 1}];\n`
          + 'uniform int uClipCount;\n'
          + 'varying vec3 vClipWorld;\n'
          + shader.fragmentShader.replace('#include <clipping_planes_fragment>',
            `#include <clipping_planes_fragment>
            {
              bool insidePoly = false;
              for (int i = 0; i < ${CLIP_MAX_POINTS}; i++) {
                if (i >= uClipCount) break;
                vec2 a = uClipPoly[i];
                vec2 b = uClipPoly[i + 1];
                if (((a.y > vClipWorld.z) != (b.y > vClipWorld.z))
                    && (vClipWorld.x < (b.x - a.x) * (vClipWorld.z - a.y)
                                       / (b.y - a.y) + a.x)) {
                  insidePoly = !insidePoly;
                }
              }
              if (!insidePoly) discard;
            }`);
      };
      // sonst greift three auf das Programm des ungepatchten Materials zurück
      m.customProgramCacheKey = () => `roomclip:${count}`;
      m.needsUpdate = true;
      return m;
    };
    mesh.material = Array.isArray(mesh.material)
      ? mesh.material.map(patch) : patch(mesh.material);
  });
}

/** Platzhalter für ein Prop ohne Mesh: Box in den gelieferten Maßen (schon
 *  Welt-Meter), Ursprung im Zentrum der Unterkante. */
function buildPlaceholder(dims: { w: number; d: number; h: number }): THREE.Mesh {
  const geo = new THREE.BoxGeometry(Math.max(dims.w, 0.01), Math.max(dims.h, 0.01),
                                    Math.max(dims.d, 0.01));
  geo.translate(0, Math.max(dims.h, 0.01) / 2, 0);
  const mesh = new THREE.Mesh(geo, std({
    color: 0x9a9a9a, roughness: 0.9, transparent: true, opacity: 0.5,
  }));
  mesh.receiveShadow = true;
  return mesh;
}

// ── Mount ────────────────────────────────────────────────────────────────

const SCENE_GROUP = 'scene';

/** Figuren-Vorgaben der zuletzt montierten Szene je Location (§ B1 `figures`). */
const sceneFigureInfo = new Map<string, { scale: number; clearance: number }>();

/**
 * Figuren-Maßstab einer Szenen-Location: `base_height_m_world` geteilt durch
 * die Basishöhe der Figurenbibliothek — der Faktor, mit dem eine Figur in
 * REALEN Metern zur Weltgröße wird. Kommt aus dem Payload und nicht aus einer
 * eigenen k-Rechnung, weil der Server im Legacy-Mode bewusst anders rechnet
 * (1,7 × storey/3 statt × k). null = keine Szene für diese Location.
 */
export function sceneFigureScale(locationId: string): number | null {
  return sceneFigureInfo.get(locationId)?.scale ?? null;
}

/** Laufende Mount-Nummer PRO KACHEL: ein während des GLB-Ladens ersetzter
 *  Mount darf nichts mehr nachtragen. Pro Kachel, nicht global — beim Start
 *  montieren alle Szenen-Locations gleichzeitig, ein globaler Zähler würde
 *  jeden Mount außer dem letzten für veraltet erklären. */
const mountSeq = new WeakMap<Tile, number>();

/**
 * Die komplette Innenansicht einer Location aus dem Payload bauen.
 *
 * Füllt die Tile-Felder der Innenansicht
 * (roomGroups/-Centers/-Exits/-Levels/-Rects/-Slots/-Markers, outlineWalls,
 * levelSlabs, levelWallMats, elevatorStops, alwaysVisibleRooms, interior,
 * interiorLabels, interiorLift) — der ganze Sicht- und Interaktionscode
 * darüber (LOD, Crossfade, Fokus, Culling, NPCs) bleibt unberührt.
 *
 * Modelle (Gebäudehülle, Raum-Dioramen, Props) laufen ALLE durch `placeSpec`;
 * sie trudeln asynchron ein und werden nachgetragen.
 */
export async function mountScene(tile: Tile, scene: ScenePayload): Promise<VerifyReport | null> {
  const seq = (mountSeq.get(tile) ?? 0) + 1;
  mountSeq.set(tile, seq);
  // veraltet = diese Kachel wurde neu montiert ODER ganz aus der Szene genommen
  const stale = () => mountSeq.get(tile) !== seq || tile.group.parent === null;
  const locId = tile.loc.id;
  const k = scene.k;
  const verify = new Verifier(verifyOn());

  // Maßstabs-Anker der Location auf die Payload-Skalare setzen: alles, was im
  // Client mit k/Etagenhöhe rechnet (Figuren-Maßstab, Sitzhöhen-Heuristik,
  // Textur-Kachelung), zieht damit aus derselben Quelle wie die Primitive.
  setLocationAnchor(locId, { k, storeyWorld: scene.storey_m });
  sceneFigureInfo.set(locId, {
    scale: scene.figures.base_height_m_world / BASE_FIGURE_HEIGHT_M,
    clearance: scene.figures.stand_clearance,
  });

  // Surface-Bilder FERTIG laden, bevor Platten/Wände sie klonen (Klone eines
  // noch ladenden Bildes bleiben leer).
  const kinds = new Set<string>(['floor']);
  for (const p of scene.plates) if (p.texture_kind) kinds.add(p.texture_kind);
  for (const w of scene.walls) if (w.texture_kind) kinds.add(w.texture_kind);
  await Promise.all([...kinds].map(preloadSurfaceTexture));
  if (stale()) return null;

  // Vorherigen Aufbau entfernen (Remount bei Signatur-Wechsel).
  unmountScene(tile);

  const g = new THREE.Group();
  g.name = SCENE_GROUP;
  g.visible = false;                      // der Crossfade deckt sie auf
  // NUR eine Szene mit INNEN-Inhalt ist eine Innenansicht: eine Location,
  // deren Payload allein aus dem Gebäudemodell besteht (Mondscheinsee —
  // Modell, aber keine Räume/Platten/Wände), darf beim Reinzoomen NICHT
  // ausgeblendet werden; es gäbe nichts aufzudecken.
  const hasInterior = scene.plates.length > 0 || scene.walls.length > 0
    || scene.extras.length > 0 || scene.markers.length > 0
    || scene.models.some((m) => m.role !== 'building');
  tile.interior = hasInterior ? g : null;
  tile.group.add(g);

  const style = scene.style;
  const floorYof = new Map(scene.levels.map((l) => [l.level, l.floor_y]));
  const levels = scene.levels.map((l) => l.level);

  // ── Räume: Gruppen, Etagen, Outdoor-Flags ───────────────────────────────
  // Outdoor-Räume (§ A5) hängen direkt an der Kachel und sind damit in jeder
  // Zoomstufe sichtbar; Innenräume hängen an der Innenansicht.
  const outdoor = new Set(scene.outdoor_rooms);
  const roomGroup = new Map<string, THREE.Group>();
  const roomLevel = new Map<string, number>();
  const nameOf = new Map<string, string>();
  for (const room of scene.rooms) {
    const id = room.room_id;
    if (!id) continue;
    const rg = new THREE.Group();
    rg.name = `room:${id}`;
    if (outdoor.has(id) || room.always_visible) {
      tile.group.add(rg);
      tile.alwaysVisibleRooms.add(id);
      outdoor.add(id);
    } else {
      g.add(rg);
    }
    roomGroup.set(id, rg);
    roomLevel.set(id, room.level);
    tile.roomGroups.set(id, rg);
    tile.roomLevels.set(id, room.level);
    const name = tile.loc.rooms.find((r) => r.id === id)?.name;
    if (name) {
      nameOf.set(id, name);
      tile.roomLevels.set(name, room.level);
      if (outdoor.has(id)) tile.alwaysVisibleRooms.add(name);
    }
    if (outdoor.has(id)) {
      tile.roomOutdoor.add(id);
      if (name) tile.roomOutdoor.add(name);
    }
  }
  /** Zielgruppe eines Primitivs: der Raum (Fokus-Modus blendet ihn komplett
   *  aus) oder die Innenansicht für alles Gebäudeweite. */
  const parentFor = (roomId: string | undefined) =>
    (roomId && roomGroup.get(roomId)) || g;

  // ── Platten ─────────────────────────────────────────────────────────────
  // Raum-Platten liefern zugleich Rechteck, Mitte und Auflagehöhe des Raums:
  // roomRects (Label-Position), roomCenters (NPC-Standort) und der Slot für
  // die Begehbarkeits-Abtastung entstehen aus ihrer Umschließenden.
  const roomPlateTop = new Map<string, number>();
  /** Gebaute Primitive für den Verify-Durchgang — vermessen wird erst, wenn
   *  die Kachel-Matrizen stehen (sonst misst man Zwischenzustände). */
  const builtPlates: { mesh: THREE.Mesh; plate: ScenePlate }[] = [];
  const builtWalls: { mesh: THREE.Mesh; wall: SceneWall }[] = [];
  for (const plate of scene.plates) {
    const mesh = buildPlate(plate, k, style);
    parentFor(plate.room_id).add(mesh);
    builtPlates.push({ mesh, plate });
    if (!plate.room_id) {
      // Kontur-Platte der Etage — Grundlage des Etagen-Umschalters
      tile.levelSlabs.set(plate.level, mesh);
      continue;
    }
    const id = plate.room_id;
    let minX = Infinity, maxX = -Infinity, minZ = Infinity, maxZ = -Infinity;
    for (const [px, pz] of plate.outline) {
      minX = Math.min(minX, px); maxX = Math.max(maxX, px);
      minZ = Math.min(minZ, pz); maxZ = Math.max(maxZ, pz);
    }
    const cx = (minX + maxX) / 2, cz = (minZ + maxZ) / 2;
    const w = Math.max(maxX - minX, 0.5), d = Math.max(maxZ - minZ, 0.5);
    roomPlateTop.set(id, plate.top_y);
    tile.roomRects.set(id, { x: tile.center.x + cx, z: tile.center.z + cz, w, d });
    // Raum-Mitte: eine Instanz, unter ID UND Name — die Abtastung hebt ihr Y
    // später auf die gemessene Bodenhöhe (setY auf der geteilten Instanz).
    const centre = tile.center.clone().add(new THREE.Vector3(cx, plate.top_y + 0.01, cz));
    tile.roomCenters.set(id, centre);
    const name = nameOf.get(id);
    if (name) tile.roomCenters.set(name, centre);
    // Bezugsrahmen für sampleRoomWalkables: Halter auf der Raum-Mitte in
    // Auflagehöhe, Maße = Umschließende der Platte.
    const holder = new THREE.Group();
    holder.position.set(cx, plate.top_y, cz);
    parentFor(id).add(holder);
    tile.roomSlots.set(id, { holder, w, d });
  }

  // ── Wände ───────────────────────────────────────────────────────────────
  // Bereits um jede Öffnung geteilt; das Glasband eines Fensters ist ein
  // eigener Eintrag. `outward_normal` kommt mit und speist das Culling.
  for (const wall of scene.walls) {
    const len = Math.hypot(wall.to[0] - wall.from[0], wall.to[1] - wall.from[1]);
    if (len < 1e-4) continue;
    const mesh = buildWall(wall, k, style, len);
    parentFor(wall.room_id).add(mesh);
    builtWalls.push({ mesh, wall });
    if (!wall.glass) {
      tile.outlineWalls.push({
        mesh, level: wall.level,
        mid: new THREE.Vector2(tile.center.x + (wall.from[0] + wall.to[0]) / 2,
                               tile.center.z + (wall.from[1] + wall.to[1]) / 2),
        normal: new THREE.Vector2(wall.outward_normal[0], wall.outward_normal[1]),
      });
      const mats = tile.levelWallMats.get(wall.level);
      const mat = mesh.material as THREE.MeshStandardMaterial;
      if (mats) mats.push(mat);
      else tile.levelWallMats.set(wall.level, [mat]);
    }
  }

  // ── Extras (Fahrstuhl) ──────────────────────────────────────────────────
  // Typisierte Boxen, Zentrum + Größe, direkt aus dem Payload. Die Pads
  // liefern zugleich die Haltepunkte fürs Etagen-Routing.
  let elevatorXZ: THREE.Vector2 | null = null;
  for (const extra of scene.extras) {
    const glass = extra.kind.endsWith('_glass');
    const cabin = extra.kind === 'elevator_cabin';
    const color = glass ? style.glass_color
      : extra.kind === 'elevator_pad' ? style.elevator_pad_color
        : cabin ? style.elevator_cabin_color : style.elevator_frame_color;
    const opacity = glass ? (style.elevator_glass_opacity ?? style.glass_opacity ?? 0.22)
      : cabin ? (style.elevator_cabin_opacity ?? 1) : 1;
    const mesh = new THREE.Mesh(
      new THREE.BoxGeometry(extra.size[0], extra.size[1], extra.size[2]),
      std({ color: hex(color), transparent: opacity < 1, opacity, roughness: glass ? 0.3 : 0.85 }));
    mesh.position.set(extra.center[0], extra.center[1], extra.center[2]);
    mesh.receiveShadow = false;
    g.add(mesh);
    elevatorXZ = elevatorXZ ?? new THREE.Vector2(extra.center[0], extra.center[2]);
    if (extra.kind === 'elevator_pad' && extra.level !== undefined) {
      tile.elevatorStops = tile.elevatorStops ?? new Map();
      tile.elevatorStops.set(extra.level, tile.center.clone().add(new THREE.Vector3(
        extra.center[0], extra.center[1] + extra.size[1] / 2 + 0.01, extra.center[2])));
    }
  }

  // ── Ausgänge & Marker: fertig in Weltkoordinaten ────────────────────────
  for (const exit of scene.exits) {
    const id = exit.room_id;
    if (!id) continue;
    const y = (roomPlateTop.get(id) ?? floorYof.get(roomLevel.get(id) ?? 0) ?? 0) + 0.01;
    const world = tile.center.clone().add(new THREE.Vector3(exit.at_world[0], y, exit.at_world[1]));
    tile.roomExits.set(id, world);
    const name = nameOf.get(id);
    if (name) tile.roomExits.set(name, world);
  }
  for (const marker of scene.markers) {
    const id = marker.room_id;
    if (!id || !marker.animation) continue;
    let byKind = tile.roomMarkers.get(id);
    if (!byKind) {
      byKind = new Map();
      tile.roomMarkers.set(id, byKind);
      const name = nameOf.get(id);
      if (name) tile.roomMarkers.set(name, byKind);
    }
    // Prop-Marker sind FERTIG komponiert (fixed: die Abtastung lässt ihre Höhe
    // in Ruhe). Raum-Marker bleiben laut § A4 additiv zur ABGETASTETEN
    // Auflagehöhe — ihr offset_y steckt im gelieferten y_world über dem
    // Etagenboden und wird dafür zurückgerechnet.
    const fixed = marker.source === 'prop';
    const floorY = floorYof.get(roomLevel.get(id) ?? 0) ?? 0;
    const offsetY = fixed ? 0 : marker.y_world - floorY;
    byKind.set(marker.animation, [...(byKind.get(marker.animation) ?? []), {
      p: tile.center.clone().add(new THREE.Vector3(
        marker.at_world[0], marker.y_world, marker.at_world[1])),
      rotation: marker.facing,
      offsetY,
      fixed,
    }]);
  }

  // ── Raum-Labels + Etagen-Umschalter (Sicht-Zustand, bleibt Client) ──────
  for (const [id, rg] of roomGroup) {
    const name = nameOf.get(id);
    if (!name) continue;
    const rect = tile.roomRects.get(id);
    const el = document.createElement('div');
    el.className = 'room-label';
    el.textContent = name;
    const label = new CSS2DObject(el);
    const floorY = floorYof.get(roomLevel.get(id) ?? 0) ?? 0;
    label.position.set(rect ? rect.x - tile.center.x : 0,
                       floorY + Math.min(1.5, scene.storey_m * 0.8),
                       rect ? rect.z - tile.center.z : 0);
    rg.add(label);
    tile.interiorLabels.push(label);
  }
  const maxLevel = levels.length ? Math.max(...levels) : 0;
  tile.interiorLift = Math.max(0, maxLevel) * scene.storey_m * 1.5;
  if (levels.length > 1) {
    const el = document.createElement('div');
    el.className = 'level-switch';
    const sw = new CSS2DObject(el);
    const swAt = (lv: number) => {
      sw.position.set(elevatorXZ?.x ?? 2.2,
                      (floorYof.get(lv) ?? lv * scene.storey_m) + scene.storey_m * (2 / 3),
                      elevatorXZ?.y ?? 0);
    };
    for (const lv of [...levels].sort((a, b) => a - b)) {
      const btn = document.createElement('button');
      btn.textContent = lv === 0 ? 'EG' : `${lv}.`;
      if (lv === tile.levelFilter) btn.classList.add('active');
      btn.addEventListener('click', (ev) => {
        ev.stopPropagation();
        tile.levelFilter = lv;
        swAt(lv);
        el.querySelectorAll('button').forEach((b) => b.classList.toggle('active', b === btn));
      });
      el.appendChild(btn);
    }
    swAt(tile.levelFilter);
    g.add(sw);
  }

  // ── Modelle: ALLE durch placeSpec (§ B2) ────────────────────────────────
  // Gebäudehülle, Raum-Dioramen und Props sind derselbe Code — nur die Spec
  // unterscheidet sie. Das Diorama koexistiert seit § A4 (2026-07-25) immer
  // mit den Props des Raums; es ist einfach ein weiteres Modell im Raum.
  const walkY = new Map<string, number>();
  verify.total = scene.models.length;
  await Promise.all(scene.models.map(async (spec) => {
    let source: THREE.Object3D | null = null;
    if (spec.url) {
      const raw = await loadGlb(spec.url, tile.center);
      if (stale()) return;
      source = raw ? raw.clone(true) : null;
    }
    if (!source && spec.placeholder_dims) {
      // missing / has_model:false → Platzhalter in gelieferter Größe; die
      // Platzierung wird NIE verworfen (§ A2).
      const ph = buildPlaceholder(spec.placeholder_dims);
      ph.position.set(spec.anchor[0], spec.bottom_y, spec.anchor[1]);
      ph.rotation.y = -deg(spec.yaw_deg);
      parentFor(spec.room_id).add(ph);
      verify.placed += 1;
      // Auch der Platzhalter wird gegen seine Spec geprüft: er steht an
      // derselben Stelle und hat dieselbe Zielgröße wie das fehlende Mesh
      // (dims × k). Ohne diese Prüfung blieb ein Loch in der Abdeckung —
      // an 526cf40b waren das 2 Props / 8 Prüfungen, und die Verify-Summe
      // lag ohne Grund unter dem Soll.
      verify.placement(ph, spec, tile.center);
      return;
    }
    if (stale()) return;
    if (!source) {
      // Mesh nach allen Versuchen nicht ladbar UND kein Platzhalter geliefert:
      // hier fehlt ein Objekt in der Szene. Das wird GEZÄHLT (A3) — früher
      // verschwand die Platzierung stillschweigend und die Verify-Tabelle
      // meldete trotzdem „keine Abweichung".
      verify.skip(spec);
      return;
    }
    verify.placed += 1;
    const placed = placeSpec(source, spec);
    if (spec.role === 'building') {
      applySceneBuilding(tile, placed);
    } else {
      parentFor(spec.room_id).add(placed);
      if (spec.role === 'room' && spec.walk_y_world !== undefined && spec.room_id) {
        walkY.set(spec.room_id, spec.walk_y_world);
      }
      // Raum-Clipping (§ B1): NUR das Spec-Modell wird beschnitten — Figuren
      // und Marker bleiben unberührt, die stehen bewusst auch am Rand.
      // Polygon kommt um das Kachelzentrum, der Shader misst in Weltkoordinaten.
      const clip = spec.clip_outline;
      if (clip && clip.length >= 3) {
        applyRoomClip(placed, clip.slice(0, CLIP_MAX_POINTS).map(
          ([cx, cz]) => new THREE.Vector2(tile.center.x + cx, tile.center.z + cz)));
        verify.clipped(spec, Math.min(clip.length, CLIP_MAX_POINTS));
      }
    }
    verify.placement(placed, spec, tile.center);
  }));
  if (stale()) return null;

  // ── Begehbarkeit abtasten (Sicht-/Spiel-Logik, bleibt Client) ───────────
  // Über ALLES im Raum: Platte, Wände, Diorama, Props.
  for (const [id, rg] of roomGroup) {
    // walk_y (§ B6 Nr. 7): die deklarierte Standhöhe geht als Boden-SOLL in
    // die Abtastung — sie schlägt dort die Höhen-Heuristik, und damit stehen
    // auch die STEH-SPOTS (nicht nur Mitte/Exit) auf dem sichtbaren Boden.
    // Ohne walk_y wie gehabt: dominante Lage + Tür-Referenz.
    sampleRoomWalkables(tile, id, rg, walkY.get(id));
  }

  // ── Verify (§ B5a): Primitive gegen das Soll ────────────────────────────
  // Erst jetzt vermessen: die Kachel-Matrizen stehen, jedes Objekt hängt an
  // seinem endgültigen Platz. Platten prüfen Oberkante (und Unterkante bei
  // Körpern), Wände Fuß-/Oberkante und Mitte.
  if (verify.active) {
    tile.group.updateMatrixWorld(true);
    for (const { mesh, plate } of builtPlates) {
      const name = `plate:${plate.room_id || 'level'}@${plate.level}`;
      const targets = [{ field: 'top_y', actual: (b: THREE.Box3) => b.max.y, target: plate.top_y }];
      if (plate.thickness > 0) {
        targets.push({ field: 'bottom_y', actual: (b: THREE.Box3) => b.min.y,
                       target: plate.top_y - plate.thickness });
      }
      verify.primitive(mesh, tile.center, name, targets);
    }
    for (const { mesh, wall } of builtWalls) {
      verify.primitive(mesh, tile.center, `wall:${wall.room_id || 'contour'}@${wall.level}`, [
        { field: 'base_y', actual: (b) => b.min.y, target: wall.base_y },
        { field: 'top_y', actual: (b) => b.max.y, target: wall.base_y + wall.height },
        { field: 'centre.x', actual: (b) => (b.min.x + b.max.x) / 2,
          target: (wall.from[0] + wall.to[0]) / 2 },
        { field: 'centre.z', actual: (b) => (b.min.z + b.max.z) / 2,
          target: (wall.from[1] + wall.to[1]) / 2 },
      ]);
    }
  }

  // Modelle als platziert/gesamt loggen — eine Lücke ist damit auch ohne
  // Verify-Modus im Log sichtbar (A3).
  console.info(`[scene] ${locId}: montiert — ${scene.plates.length} Platten, `
    + `${scene.walls.length} Wandsegmente, `
    + `${verify.placed}/${scene.models.length} Modelle, `
    + `${scene.markers.length} Marker, Etagen ${levels.join('/')}`
    + (verify.skipped ? ` — ${verify.skipped} Modell(e) NICHT ladbar` : ''));
  return verify.report(locId);
}

/** Gebäudehülle aus der Szene einwechseln: ersetzt die prozedurale Hülle und
 *  verhält sich fürs Reinzoomen wie ein Dach (blendet aus, gibt den Blick auf
 *  die Räume frei). Anders als der Legacy-Pfad blendet hier NICHTS zwischen
 *  zwei Y-Maßstäben um — die Spec ist die eine Antwort auf die Größe. */
function applySceneBuilding(tile: Tile, model: THREE.Group): void {
  if (tile.shell) {
    tile.group.remove(tile.shell);
    tile.shell = undefined;
  }
  if (tile.decor) tile.decor.visible = false;
  tile.serverModel = model;
  // Kachel-/Detail-Crossfade (Anker-Note "zwei Sichten"): die tile_fit-Spec
  // liefert die DETAIL-Skalierung (Y = height_m × k); die Kartenansicht
  // zeigt weiter uniform (Y = k_xz), applyTileFade blendet beim Zoomen —
  // der Umbau hatte das verloren (Befund Kira: Bodenhaut am Eingang stand
  // im Café ×1,24 höher als in der Kachel-Ansicht). Damit der Boden beim
  // Blenden nicht wandert, wird der Inhalt auf lokale Unterkante 0
  // umgeankert (Welt-Geometrie bleibt exakt gleich — Verify unberührt).
  model.updateMatrixWorld(true);
  const bb = new THREE.Box3().setFromObject(model);
  const inner = model.children[0];
  if (inner && model.scale.y > 1e-6) {
    const localBottom = (bb.min.y - model.position.y) / model.scale.y;
    inner.position.y -= localBottom;
    model.position.y = bb.min.y;
  }
  model.userData.scaleBase = model.scale.x;
  model.userData.scaleYDetail = model.scale.y;
  tile.shellMats = [];
  tile.roofMats = [];
  tile.roofParts = [model];
  tile.facadeMats = [];
  model.traverse((o) => {
    const mesh = o as THREE.Mesh;
    if (!mesh.isMesh) return;
    const clone = (m: THREE.Material) => {
      const c = m.clone();
      c.transparent = true;
      tile.roofMats.push(c as THREE.MeshStandardMaterial);
      return c;
    };
    mesh.material = Array.isArray(mesh.material)
      ? mesh.material.map(clone) : clone(mesh.material);
    mesh.castShadow = true;
    mesh.receiveShadow = false;
  });
  tile.group.add(model);
  model.updateMatrixWorld(true);
  const box = new THREE.Box3().setFromObject(model);
  tile.height = box.max.y - box.min.y;
  tile.labelObj?.position.set(0, tile.height + 2.2, 0);
}

/** Szenen-Aufbau einer Kachel entfernen (Remount bei Signatur-Wechsel).
 *  Räumt auch die Felder, die mountScene gefüllt hat — die Kachel selbst
 *  (Sockel, prozedurale Hülle, Label, Ring) bleibt stehen. */
export function unmountScene(tile: Tile): void {
  // Über den NAMEN suchen, nicht über tile.interior — eine Nur-Gebäude-Szene
  // (kein Innen-Inhalt) hängt als Gruppe im Graphen, ohne interior zu sein.
  const prev = tile.group.children.find((c) => c.name === SCENE_GROUP)
    ?? tile.interior;
  if (prev && prev.name === SCENE_GROUP) tile.group.remove(prev);
  for (const [, rg] of tile.roomGroups) rg.parent?.remove(rg);
  for (const label of tile.interiorLabels) label.element?.remove();
  tile.interior = null;
  tile.interiorLabels = [];
  tile.roomGroups.clear();
  tile.roomCenters.clear();
  tile.roomExits.clear();
  tile.roomSlots.clear();
  tile.roomSpots.clear();
  tile.roomSitSpots.clear();
  tile.roomLieSpots.clear();
  tile.roomMarkers.clear();
  tile.roomRects.clear();
  tile.roomLevels.clear();
  tile.roomOutdoor.clear();
  tile.alwaysVisibleRooms.clear();
  tile.outlineWalls = [];
  tile.levelSlabs.clear();
  tile.levelWallMats.clear();
  tile.elevatorStops = undefined;
}
