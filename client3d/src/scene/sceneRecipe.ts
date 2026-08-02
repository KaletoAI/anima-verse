import * as THREE from 'three';
import { CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import { applyClipOutline, applyCutouts, buildExtra, buildPlaceholder,
  buildPlate, buildWall, CLIP_MAX_POINTS, drapeGeometry, placeModelSpec, plateTargets,
  SpecVerifier, VERIFY_EPS, surfaceMaterial, wallLength, wallTargets } from '@anima/scene-render';
import type { PrimitiveTarget, VerifyRow } from '@anima/scene-render';
import {
  getLocationScene,
  type SceneExtra, type SceneModelSpec, type ScenePayload, type ScenePlate,
  type SceneWall,
} from '../api';
import { BASE_FIGURE_HEIGHT_M } from './figures';
import { loadGlb } from './propAssets';
import {
  preloadSurfaceTexture, sampleRoomWalkables, setLocationAnchor, surfaceFor,
  surfaceMaterialSpec,
  type Tile,
} from './tiles';

/**
 * Scene recipe (schnittstellen-3d.md part B) — the server computes, the
 * client renders.
 *
 * ONE endpoint delivers the complete scene of a location as finished
 * primitives (plates/walls/extras) and placement specs (models). This module
 * renders them and makes not a single geometry decision of its own: no
 * opening split, no mirroring, no exit derivation, no elevator dimensions, no
 * constants (0.07 / 0.14 / 0.12 / ±0.4 …) and no colours. All of that comes
 * from the payload.
 *
 * Since stage 2 the routine "place a model" (§ B2), the room clip (§ B1) and
 * — since the primitive builders moved (N) — plate, wall segment, extra box
 * and placeholder live in `@anima/scene-render`: the same arithmetic the
 * admin preview runs, down to the single uniform scale factor of § B2.
 *
 * What stays here is the MATERIAL of those primitives (the surface-texture
 * chain, the payload colour vocabulary) plus view and interaction state:
 * `mountScene` fills the tile fields of the interior view so that LOD,
 * crossfade, level switch, room focus, wall culling, NPC placement and
 * pathfinding keep running unchanged.
 *
 * 404 on /scene = the legacy case (no floor plan, no layout, no model) —
 * then this module leaves the tile alone.
 */

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

/** Eine Abweichungszeile — Definition im geteilten Paket, hier nur
 *  weitergereicht, damit die Konsumenten dieses Moduls sie weiter von hier
 *  beziehen können. */
export type { VerifyRow } from '@anima/scene-render';

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
  // Der Diff selbst liegt in @anima/scene-render — DIESELBE Rechnung, die die
  // Admin-Vorschau fährt. Hier drumherum bleibt der BERICHT: übersprungene
  // Specs, Modellzählung, Clip-Vermerke, console-Ausgabe und der Ablageort
  // window.__sceneVerify. Das ist Client-Sache und soll es bleiben.
  private readonly v: SpecVerifier;
  skipped = 0;
  placed = 0;
  total = 0;
  clips: { object: string; punkte: number }[] = [];
  constructor(readonly active: boolean) { this.v = new SpecVerifier(THREE, active); }

  get rows(): VerifyRow[] { return this.v.rows; }
  get checked(): number { return this.v.checked; }

  /** Beschnittenes Diorama vermerken (§ B1 clip_outline). Keine Abweichung,
   *  sondern eine Eigenschaft des Aufbaus — sie gehört trotzdem in die
   *  Ausgabe, sonst sieht man einem fehlenden Möbelstück nicht an, ob es
   *  weggeclippt oder gar nicht geladen wurde. */
  clipped(spec: SceneModelSpec, points: number): void {
    this.clips.push({ object: `${spec.role}:${spec.id}`, punkte: points });
  }

  /** Eine Modell-Spec, die NICHT platziert wurde (Mesh nach allen Versuchen
   *  nicht ladbar, kein Platzhalter). Das ist ein fehlendes Objekt in der
   *  Szene — es wandert als Abweichungszeile in die Tabelle (`geladen` 0
   *  statt 1), damit eine Lücke nicht wie ein Erfolg aussieht. Wird
   *  unabhängig vom Verify-Modus gezählt und geloggt. */
  skip(spec: SceneModelSpec): void {
    this.skipped += 1;
    console.warn(`[scene] ${spec.role}:${spec.id} übersprungen — Mesh nicht ladbar `
      + `(${spec.url || 'ohne URL'})`);
    this.v.check(`${spec.role}:${spec.id}`, 'geladen', 0, 1);
  }

  check(object: string, field: string, actual: number, target: number): void {
    this.v.check(object, field, actual, target);
  }

  /** Primitiv gegen seine Spec prüfen. `origin` = Weltposition des
   *  Kachelzentrums (die Spec rechnet um das Kachelzentrum). */
  primitive(mesh: THREE.Object3D, origin: THREE.Vector3, name: string,
            targets: PrimitiveTarget[]): void {
    this.v.primitive(mesh, origin, name, targets);
  }

  /** Platziertes Modell gegen seine Spec prüfen. */
  placement(obj: THREE.Object3D, spec: SceneModelSpec, origin: THREE.Vector3): void {
    this.v.placement(obj, spec, origin);
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

// ── Materials for the shared primitive builders ──────────────────────────
// The geometry of plate, wall, extra box and placeholder comes from
// @anima/scene-render; what belongs to this client is the LOOK. That is the
// side of the split that genuinely differs: the world-scale surface-texture
// chain and the payload's colour vocabulary — the admin preview paints the
// same primitives in its own preview colours.

/** Tileable surface texture of a kind in WORLD scale (size_m × k). Box and
 *  extrude UVs need a per-piece clone with its own repeat. `use` drives the
 *  fallback chain of surfaceFor: floors fall back to the global "floor" kind,
 *  walls deliberately do not (else floor covering sticks to the wall). */
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

/** Material of a floor plate: the tiled surface texture of its kind, else the
 *  payload's floor colour; upper storeys stay translucent. A body faces
 *  outward only, a bare surface both ways. */
function plateMaterial(plate: ScenePlate, k: number,
                       style: ScenePayload['style']): THREE.MeshStandardMaterial {
  const solid = plate.thickness > 0;
  const upper = plate.opacity_role === 'upper';
  const opacity = upper ? (style.upper_floor_opacity ?? 1) : 1;
  const side = solid ? THREE.FrontSide : THREE.DoubleSide;
  const tex = tiledTexture(plate.texture_kind, 'floor', k, (tileM) => [1 / tileM, 1 / tileM]);
  // Aussehen der ART kommt aus dem geteilten Paket — matt ist der Default und
  // exakt das bisherige Material.
  return surfaceMaterial(THREE, {
    material: surfaceMaterialSpec(plate.texture_kind),
    map: tex, color: hex(style.floor_color),
    transparent: upper, opacity, side,
  }) as THREE.MeshStandardMaterial;
}

/** Material of a wall segment: a glass band from the glass vocabulary, else
 *  the tiled wall texture or the wall colour. `len` tiles the texture across
 *  the segment's actual length. */
function wallMaterial(wall: SceneWall, k: number, style: ScenePayload['style'],
                      len: number): THREE.MeshStandardMaterial {
  if (wall.glass) {
    return std({ color: hex(style.glass_color), transparent: true,
                 opacity: style.glass_opacity ?? 0.25, roughness: 0.3 });
  }
  const upper = wall.opacity_role === 'upper';
  const opacity = upper ? (style.upper_wall_opacity ?? 1) : 1;
  const tex = tiledTexture(wall.texture_kind, 'wall', k,
    (tileM) => [len / tileM, wall.height / tileM]);
  return surfaceMaterial(THREE, {
    material: surfaceMaterialSpec(wall.texture_kind),
    map: tex, color: hex(style.wall_color), transparent: upper, opacity,
  }) as THREE.MeshStandardMaterial;
}

/** Material of an extra box: the part kind picks colour and opacity from the
 *  payload's style vocabulary — glass translucent, cabin semi-transparent,
 *  pad and shaft opaque. */
function extraMaterial(extra: SceneExtra,
                       style: ScenePayload['style']): THREE.MeshStandardMaterial {
  const glass = extra.kind.endsWith('_glass');
  const cabin = extra.kind === 'elevator_cabin';
  const color = glass ? style.glass_color
    : extra.kind === 'elevator_pad' ? style.elevator_pad_color
      : cabin ? style.elevator_cabin_color : style.elevator_frame_color;
  const opacity = glass ? (style.elevator_glass_opacity ?? style.glass_opacity ?? 0.22)
    : cabin ? (style.elevator_cabin_opacity ?? 1) : 1;
  return std({ color: hex(color), transparent: opacity < 1, opacity,
               roughness: glass ? 0.3 : 0.85 });
}

/** Material of the placeholder for a prop without a mesh: matte, half
 *  translucent grey — readable as a gap without dominating the scene. */
function placeholderMaterial(): THREE.MeshStandardMaterial {
  return std({ color: 0x9a9a9a, roughness: 0.9, transparent: true, opacity: 0.5 });
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
 * Modelle (Gebäudehülle, Raum-Dioramen, Props) laufen ALLE durch `placeModelSpec` (§ B2, geteiltes Paket);
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
  // Signal for the tile's view logic: a storey below ground exists, so the
  // tile's own ground plate has to get out of the way while the interior is
  // up (applyTileFade). The recipe itself needs nothing for this.
  tile.hasBasement = levels.some((lv) => lv < 0);

  // ── Geländerelief (§ B1 Nr. 14) ─────────────────────────────────────────
  // Das Höhenfeld gilt für die ganze Kachel: die Figuren-Standhöhe liest es
  // über `terrainLiftAt`, der Boden und die `relief`-Platten weiter unten
  // werden darüber drapiert. Objekthöhen NICHT — die kommen fertig gehoben.
  tile.terrain = scene.terrain;
  tile.terrainExtent = scene.extent_m;
  if (scene.terrain && tile.groundPlate) {
    // Die kachel-eigene Platte (kein Payload-Primitiv, sondern der Backstop
    // unter der Detailszene) wellt sich mit. Nur die GEOMETRIE wird getauscht:
    // Material, Höhe, Sichtbarkeit und der shell_area-Fade in applyTileFade
    // hängen am Mesh und bleiben damit unangetastet. Das ebene Original hebt
    // unmountScene wieder ein.
    const gp = tile.groundPlate;
    gp.updateMatrix();
    const draped = drapeGeometry(THREE, gp.geometry, scene.terrain,
                                 scene.extent_m, gp.matrix);
    if (!tile.flatGroundGeo) tile.flatGroundGeo = gp.geometry;
    else gp.geometry.dispose();
    gp.geometry = draped;
  }

  // Flächen-/Gelände-Location (Wald, See, Dorf): Räume sind ZONEN, keine
  // Zimmer — die Regel speist Raum-Labels, Panel UND die Platten unten.
  const areaLoc = tile.natureSite || !tile.isBuilding
    || (scene.models || []).some((m) => m.role === 'building'
        && (m.display === 'ground' || m.display === 'shell_area'));

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
    const mesh = buildPlate(THREE, plate, plateMaterial(plate, k, style));
    if (plate.relief && scene.terrain) {
      // Outdoor-Platte eines nicht-flachen Raums: unterteilen und über das
      // Gitter legen (§ B1 Nr. 14). Muss VOR der Begehbarkeits-Abtastung
      // passieren — die tastet den Boden per Strahl ab und soll den Hang
      // sehen, nicht die Ebene, von der er abgeleitet wurde.
      mesh.updateMatrix();
      const flat = mesh.geometry;
      mesh.geometry = drapeGeometry(THREE, flat, scene.terrain,
                                    scene.extent_m, mesh.matrix);
      flat.dispose();
    }
    // Zonen-Platte ohne erklärte Boden-Art auf einer Flächen-Location: NICHT
    // einfärben — die Palette-Farbe (das „Grün") gehört in Gebäude-Grundrisse,
    // hier IST das Terrain der Boden. Die Platte bleibt im Graphen (Raum-
    // Rechtecke, NPC-Mitten und die Begehbarkeits-Abtastung hängen an ihr),
    // nur ihr Material wird voll durchsichtig (User-Befund 2026-08-02).
    if (areaLoc && plate.room_id && outdoor.has(plate.room_id)
        && !plate.texture_kind) {
      const m = mesh.material as THREE.Material;
      m.transparent = true;
      m.opacity = 0;
      m.depthWrite = false;
    }
    // Shadow flags are view state and stay here: upper storeys cast, every
    // plate receives.
    mesh.receiveShadow = true;
    mesh.castShadow = plate.level > 0 && plate.thickness > 0;
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

  // ── Overlay-Zonen (Flächen-Locations) ───────────────────────────────────
  // Ein Outdoor-Raum außerhalb des Grundrisses wird nicht gebaut, er LIEGT auf
  // der Modelloberfläche. Es gibt also keine Platte, von der Rechteck, Mitte
  // und Höhe abzulesen wären — die kommen fertig aus dem Payload (der Server
  // rechnet). Damit stehen NPCs, Marker, Labels und Klick-Ziele dort, wo die
  // Zone liegt.
  for (const room of scene.rooms) {
    const ov = room.overlay;
    const id = room.room_id;
    if (!ov || !id) continue;
    tile.roomRects.set(id, { x: tile.center.x + ov.rect.x,
                             z: tile.center.z + ov.rect.z,
                             w: ov.rect.w, d: ov.rect.d });
    const centre = tile.center.clone().add(
      new THREE.Vector3(ov.centre[0], ov.y + 0.01, ov.centre[1]));
    tile.roomCenters.set(id, centre);
    const name = nameOf.get(id);
    if (name) tile.roomCenters.set(name, centre);
  }

  // ── Wände ───────────────────────────────────────────────────────────────
  // Bereits um jede Öffnung geteilt; das Glasband eines Fensters ist ein
  // eigener Eintrag. `outward_normal` kommt mit und speist das Culling.
  for (const wall of scene.walls) {
    const len = wallLength(wall);
    if (len < 1e-4) continue;
    const mesh = buildWall(THREE, wall, wallMaterial(wall, k, style, len));
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

  // ── Extras (elevator) ───────────────────────────────────────────────────
  // Typed boxes, centre + size, straight from the payload — one entry per
  // part. The pads double as the stops for the level routing.
  let elevatorXZ: THREE.Vector2 | null = null;
  for (const extra of scene.extras) {
    g.add(buildExtra(THREE, extra, extraMaterial(extra, style)));
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
    // y_world ist die FLÄCHE; wie tief die Wurzel darunter sitzt, sagt der
    // Server (root_offset). Der frühere eigene Sitz-Absatz des Clients galt
    // nur für Raum-Marker — Prop-Marker bekamen gar keinen, und die Autoren
    // rechneten ihn per Hand in den Marker hinein.
    const drop = marker.root_offset ?? 0;
    byKind.set(marker.animation, [...(byKind.get(marker.animation) ?? []), {
      p: tile.center.clone().add(new THREE.Vector3(
        marker.at_world[0], marker.y_world - drop, marker.at_world[1])),
      rotation: marker.facing,
      tilt: marker.tilt,
      roll: marker.roll,
      offsetY,
      drop,
      fixed,
    }]);
  }

  // ── Raum-Labels + Etagen-Umschalter (Sicht-Zustand, bleibt Client) ──────
  // Raum-Labels nur in GEBÄUDEN (`areaLoc` von oben): auf einer Flächen-
  // Location sind die Räume Zonen wie „Road"/„Forest", und ihre generischen
  // Namen über der Szene sind Rauschen (User-Vorgabe 2026-08-02).
  for (const [id, rg] of roomGroup) {
    if (areaLoc) break;  // Zonen statt Zimmer — keine Namen einblenden
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
    // The display state comes OUT of `tile.levelFilter`, not out of the click:
    // the storey is set from outside as well (the lift, the avatar changing
    // storey), and the switch then kept marking the old one and floating at its
    // height. The click handler takes the same path — one source.
    const refresh = () => {
      swAt(tile.levelFilter);
      el.querySelectorAll<HTMLButtonElement>('button').forEach(
        (b) => b.classList.toggle('active', b.dataset.level === String(tile.levelFilter)));
    };
    for (const lv of [...levels].sort((a, b) => a - b)) {
      const btn = document.createElement('button');
      btn.textContent = lv === 0 ? 'EG' : `${lv}.`;
      btn.dataset.level = String(lv);
      btn.addEventListener('click', (ev) => {
        ev.stopPropagation();
        tile.levelFilter = lv;
        refresh();
      });
      el.appendChild(btn);
    }
    refresh();
    tile.levelSwitch = refresh;
    g.add(sw);
  }

  // ── Modelle: ALLE durch placeModelSpec (§ B2, @anima/scene-render) ──────
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
      const ph = buildPlaceholder(THREE, spec.placeholder_dims, placeholderMaterial());
      ph.receiveShadow = true;
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
    // clone:false — der Client uebergibt das Objekt zur Uebernahme (die
    // Admin-Vorschau platziert dasselbe gecachte Objekt mehrfach und klont).
    // clip:false — wir clippen unten selbst, in WELT-Koordinaten um das
    // Kachelzentrum; die Spec traegt das Polygon relativ dazu.
    const placed = placeModelSpec(THREE, source, spec,
                                  { clone: false, clip: false });
    if (spec.role === 'building') {
      // Was das Modell IST, sagt die SPEC (`display`) — nicht ein Nebeneffekt.
      // Vorher wurde „Flächen-Location" aus `cutouts.length > 0` geraten; eine
      // Fläche ohne Grundriss (Mondscheinsee: kein outline, kein Indoor-Raum
      // außerhalb) hatte keine Löcher, galt als Gebäudehülle und blendete beim
      // Reinzoomen komplett weg (User-Befund 2026-07-28).
      applySceneBuilding(tile, placed, spec.display ?? 'shell');
      const cutouts = spec.cutouts || [];
      if (cutouts.length) {
        // Polygone kommen um das Kachelzentrum, der Shader misst in
        // Weltkoordinaten — dieselbe Umrechnung wie beim Raum-Clip.
        tile.cutouts?.dispose();
        tile.cutouts = applyCutouts(THREE, placed, cutouts.map(
          (poly) => poly.map(([cx, cz]) => [tile.center.x + cx,
                                            tile.center.z + cz] as [number, number])));
        // Sofort den aktuellen Sichtzustand anlegen: die Kachel kann bereits
        // in der Innenansicht stehen, wenn das Modell nachträglich eintrifft.
        tile.cutouts.setEnabled(tile.fade > 0.03);
      }
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
        applyClipOutline(THREE, placed, clip.slice(0, CLIP_MAX_POINTS).map(
          ([cx, cz]) => [tile.center.x + cx, tile.center.z + cz] as [number, number]));
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

  // ── Verify (§ B5a): primitives against the target ───────────────────────
  // Only now measure: the tile matrices are set, every object hangs in its
  // final place. WHICH numbers a plate or a wall has to match follows from
  // the payload and therefore comes from the shared package
  // (plateTargets/wallTargets) — the admin preview diffs the same fields.
  if (verify.active) {
    tile.group.updateMatrixWorld(true);
    for (const { mesh, plate } of builtPlates) {
      verify.primitive(mesh, tile.center,
        `plate:${plate.room_id || 'level'}@${plate.level}`, plateTargets(plate));
    }
    for (const { mesh, wall } of builtWalls) {
      verify.primitive(mesh, tile.center,
        `wall:${wall.room_id || 'contour'}@${wall.level}`, wallTargets(wall));
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
 *  die Räume frei). Ein `ground`-Modell bleibt stattdessen stehen.
 *
 *  Drei Modi, und die Spec sagt welcher (§ B6 Nr. 10): `shell` = Gebäude,
 *  `ground` = Fläche mit Löchern, `shell_area` = Fläche im Detail-Modus —
 *  fürs Ausblenden ist sie eine Hülle (Modell in roofParts/roofMats), ihre
 *  PLATZIERUNG bleibt die einer Fläche und wird hier so wenig angefasst wie
 *  bei den anderen beiden.
 *
 *  Hier wird an der Spec-Geometrie NICHTS mehr nachjustiert: die frühere
 *  Um-Verankerung samt Y-Morph zwischen Kachel- und Detail-Maßstab war eine
 *  reine Client-Erfindung und ließ dieselbe Location im Client bis zu 1,0 m
 *  anders hoch stehen als in der Admin-Vorschau (Kaxai Tower +0,97 m, Café
 *  −0,85 m). Seit die Spec nur noch EINEN Faktor liefert, gibt es auch nichts
 *  mehr zu blenden. */
function applySceneBuilding(tile: Tile, model: THREE.Group,
                            display: NonNullable<SceneModelSpec['display']> = 'shell'): void {
  if (tile.shell) {
    tile.group.remove(tile.shell);
    tile.shell = undefined;
  }
  tile.serverModel = model;
  // `area` = das Modell bleibt stehen und bekommt Löcher; das gilt NUR für
  // `ground`. Der Detail-Modus fadet und wird deshalb unten wie eine Hülle
  // behandelt — sein Kachelboden folgt dafür dem Fade (applyTileFade).
  const area = display === 'ground';
  tile.modelIsGround = area;
  tile.modelIsShellArea = display === 'shell_area';
  // Eine Flächen-Location BRINGT ihren Boden mit. Die kachel-eigene Platte
  // (10 × 10 m, undurchsichtig, y 0,04) steht in keinem Payload — sie ist
  // Client-Erfindung und schnitt das Modell auf ihrer Höhe ab: beim
  // Mondscheinsee lag alles unter +0,04 dahinter, also Seebecken und Strand
  // (Modell y −0,80 … +2,69). Für `display: ground` bleibt sie weg.
  if (tile.groundPlate) tile.groundPlate.visible = !area;
  // Als BACKSTOP der Detailszene muss die Platte UNTER die Payload-Platten:
  // die flachen Outdoor-Texturen (Straße, Waldboden) liegen auf Etage 0, und
  // bei y 0,04 verdeckte der Backstop genau sie — die Straße wurde erst ab
  // +0,1 m Raumhöhe sichtbar (User-Befund 2026-08-02). Das Relief hebt beide
  // mit denselben Gitterwerten, die Ordnung bleibt also überall erhalten.
  if (tile.groundPlate) {
    tile.groundPlate.position.y = tile.modelIsShellArea ? -0.01 : 0.04;
  }
  tile.shellMats = [];
  tile.roofMats = [];
  // Flächen-Location: das Modell IST die Location und bleibt sichtbar — es
  // wandert nicht in roofParts/roofMats, die der Crossfade wegblendet. Die
  // Cutouts übernehmen die Rolle des Aufdeckens (setEnabled am selben
  // fade-Zustand). Ohne Fade braucht es auch keine Material-Klone; die
  // Cutout-Routine klont ohnehin selbst.
  tile.roofParts = area ? [] : [model];
  tile.facadeMats = [];
  model.traverse((o) => {
    const mesh = o as THREE.Mesh;
    if (!mesh.isMesh) return;
    if (!area) {
      const clone = (m: THREE.Material) => {
        const c = m.clone();
        c.transparent = true;
        tile.roofMats.push(c as THREE.MeshStandardMaterial);
        return c;
      };
      mesh.material = Array.isArray(mesh.material)
        ? mesh.material.map(clone) : clone(mesh.material);
    }
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
  // Cutout-Material-Klone der vorigen Szene freigeben (Muster
  // disposeClipMaterials — die Texturen sind mit dem Cache geteilt).
  tile.cutouts?.dispose();
  tile.cutouts = undefined;
  tile.modelIsGround = false;
  tile.modelIsShellArea = false;
  tile.terrain = undefined;
  tile.terrainExtent = undefined;
  // Drapierte Kachelplatte zurückbauen: das ebene Original ist die Kachel,
  // nicht die Szene — eine Location ohne Relief muss nach dem Remount wieder
  // brettflach sein.
  if (tile.flatGroundGeo) {
    if (tile.groundPlate) {
      tile.groundPlate.geometry.dispose();
      tile.groundPlate.geometry = tile.flatGroundGeo;
    } else {
      tile.flatGroundGeo.dispose();
    }
    tile.flatGroundGeo = undefined;
  }
  if (tile.groundPlate) {
    tile.groundPlate.visible = true;
    tile.groundPlate.position.y = 0.04;
  }
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
  // The old scene's switch is gone with its DOM — its refresh function would
  // otherwise write to a widget that is no longer there.
  tile.levelSwitch = undefined;
}
