import * as THREE from 'three';
import { CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import { applyClipOutline, applyCutouts, buildExtra, buildPlaceholder,
  buildPlate, buildWall, CLIP_MAX_POINTS, disposeClipMaterials, drapeGeometry,
  pickModelVariant, placeModelSpec, plateTargets,
  SpecVerifier, VERIFY_EPS, surfaceMaterial, wallLength, wallTargets } from '@anima/scene-render';
import type { ModelTier, PrimitiveTarget, VerifyRow } from '@anima/scene-render';
import {
  getLocationScene,
  type SceneExtra, type SceneModelSpec, type ScenePayload, type ScenePlate,
  type SceneWall,
} from '../api';
import { roomDoor } from '../game/doors';
import { applyOcclusionFade } from './occlusion';
import { loadGlb } from './propAssets';
import { wantsRecipeShell } from './shellPlan';
import {
  applyPlateDepthBias, PLATE_Y_M, preloadSurfaceTexture, sampleRoomWalkables, surfaceFor,
  surfaceMaterialSpec, tileDirToWorld, tileToWorld,
  type PlacedSceneModel, type Tile,
} from './tiles';

/** Which resolution tier a mount loads, per model group. `building` = the
 *  far-view shell/area model, `interior` = everything else (dioramas, props).
 *  Pure VIEW STATE — main.ts decides (camera distance / open detail view),
 *  `pickVariant` resolves a missing tier to the best existing one. */
export interface SceneTiers { building: ModelTier; interior: ModelTier }

const tierOf = (spec: SceneModelSpec, tiers: SceneTiers): ModelTier =>
  (spec.role === 'building' ? tiers.building : tiers.interior);

/**
 * Scene recipe (schnittstellen-3d.md part B) — the server computes, the
 * client renders.
 *
 * ONE endpoint delivers the complete scene of a location as finished
 * primitives (plates/walls/extras) and placement specs (models). This module
 * renders them and makes not a single geometry decision of its own: no
 * opening split, no mirroring, no door measuring, no elevator dimensions, no
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
      + `(${pickModelVariant(spec) || 'ohne URL'})`);
    this.v.check(`${spec.role}:${spec.id}`, 'geladen', 0, 1);
  }

  check(object: string, field: string, actual: number, target: number): void {
    this.v.check(object, field, actual, target);
  }

  /** Primitiv gegen seine Spec prüfen. Bezugsrahmen = die KACHEL: ihr Zentrum
   *  als Ursprung und ihre Fußabdruck-Drehung als Rahmen-Yaw (§ A1.1) — die
   *  Spec-Zahlen sind kachel-lokal, die Messung ist es damit auch. */
  primitive(mesh: THREE.Object3D, tile: Tile, name: string,
            targets: PrimitiveTarget[]): void {
    this.v.primitive(mesh, tile.center, name, targets, tile.yaw);
  }

  /** Platziertes Modell gegen seine Spec prüfen. */
  placement(obj: THREE.Object3D, spec: SceneModelSpec, tile: Tile): void {
    this.v.placement(obj, spec, tile.center, tile.yaw);
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

/** Tileable surface texture of a kind, plus the world size of one tile. Every
 *  piece needs its OWN clone: the world scale ends up either on this texture's
 *  repeat (plates) or in the geometry's uvs (walls), and both are per piece.
 *  `use` drives the fallback chain of surfaceFor: floors fall back to the
 *  global "floor" kind, walls deliberately do not (else floor covering sticks
 *  to the wall).
 *
 *  The library's `size_m` IS the world tile size since E4: k = 1, so a metre in
 *  the room is a metre on the map and there is nothing left to convert. */
function tiledTexture(kind: string | undefined, use: 'floor' | 'wall'):
    { tex: THREE.Texture; tileM: number } | null {
  const surf = kind ? surfaceFor(kind, use) : null;
  if (!surf) return null;
  const tex = surf.texture.clone();
  tex.needsUpdate = true;
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  return { tex, tileM: surf.sizeM };
}

/** Material of a floor plate: the tiled surface texture of its kind, else the
 *  payload's floor colour; upper storeys stay translucent. A body faces
 *  outward only, a bare surface both ways. */
function plateMaterial(plate: ScenePlate,
                       style: ScenePayload['style']): THREE.MeshStandardMaterial {
  const solid = plate.thickness > 0;
  const upper = plate.opacity_role === 'upper';
  const opacity = upper ? (style.upper_floor_opacity ?? 1) : 1;
  const side = solid ? THREE.FrontSide : THREE.DoubleSide;
  // A plate's uvs ARE its outline in metres (Shape/Extrude geometry), so its
  // world scale is a plain repeat of one tile per tileM — unlike a wall box,
  // whose faces are each normalised to 0..1 and therefore carry the scale in
  // the uvs themselves.
  const surf = tiledTexture(plate.texture_kind, 'floor');
  if (surf) surf.tex.repeat.set(1 / surf.tileM, 1 / surf.tileM);
  const tex = surf?.tex ?? null;
  // Aussehen der ART kommt aus dem geteilten Paket — matt ist der Default und
  // exakt das bisherige Material.
  return surfaceMaterial(THREE, {
    material: surfaceMaterialSpec(plate.texture_kind),
    map: tex, color: hex(style.floor_color),
    transparent: upper, opacity, side,
  }) as THREE.MeshStandardMaterial;
}

/** Material of a wall segment: a glass band from the glass vocabulary, else
 *  the tiled wall texture or the wall colour.
 *
 *  Returns the tile size ALONGSIDE the material because the tiling of a wall
 *  lives in the box's uvs (buildWall/applyWorldScaleWallUVs), not on the
 *  texture: a repeat computed from the broad face and applied to all six faces
 *  crushed the texture on every jamb and reveal. `tileM` 0 = nothing to tile. */
function wallMaterial(wall: SceneWall, style: ScenePayload['style']):
    { mat: THREE.MeshStandardMaterial; tileM: number } {
  if (wall.glass) {
    return { mat: std({ color: hex(style.glass_color), transparent: true,
                        opacity: style.glass_opacity ?? 0.25, roughness: 0.3 }),
             tileM: 0 };
  }
  const upper = wall.opacity_role === 'upper';
  const opacity = upper ? (style.upper_wall_opacity ?? 1) : 1;
  const surf = tiledTexture(wall.texture_kind, 'wall');
  const mat = surfaceMaterial(THREE, {
    material: surfaceMaterialSpec(wall.texture_kind),
    map: surf?.tex ?? null, color: hex(style.wall_color),
    transparent: upper, opacity,
  }) as THREE.MeshStandardMaterial;
  return { mat, tileM: surf?.tileM ?? 0 };
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
/** Name of the far-view shell group (`buildFarShell`) — a place without a
 *  server model wears the recipe's own primitives instead of nothing. */
const FAR_SHELL_GROUP = 'far-shell';

// THE FIGURE SCALE IS GONE (E4 task 3). `figures.base_height_m_world` is the
// constant 1.70 since k = 1 (task 1), which divided by the figure library's own
// 1.70 is 1 — the room scale and the map scale are THE SAME SCALE now. Every
// consumer of the old factor went with it: the placement scale of `NpcState`,
// the scale lerps in `npcs.ts`, the interior pace factor in `walk.ts` and the
// scaled zoom-to in `main.ts`. A figure is 1.70 m × its `height_cm` factor,
// indoors and out (`figures.setCharacterHeight`).

/** k = 1 is the contract since E4. Complain once, then ignore the field — the
 *  client does not have a second scale to fall back to any more. */
let unitScaleWarned = false;
function assertUnitScale(k: number): void {
  if (k === 1 || unitScaleWarned) return;
  unitScaleWarned = true;
  console.warn(`[scene] payload k = ${k}, but the metre world is k = 1 since E4`
    + ' (§ B) — the value is ignored and the scene is drawn in real metres');
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
 * interiorLabels) — der ganze Sicht- und Interaktionscode
 * darüber (LOD, Crossfade, Fokus, Culling, NPCs) bleibt unberührt.
 *
 * Modelle (Gebäudehülle, Raum-Dioramen, Props) laufen ALLE durch `placeModelSpec` (§ B2, geteiltes Paket);
 * sie trudeln asynchron ein und werden nachgetragen.
 */
export async function mountScene(tile: Tile, scene: ScenePayload,
                                 tiers: SceneTiers = { building: 'full', interior: 'full' }
): Promise<VerifyReport | null> {
  const seq = (mountSeq.get(tile) ?? 0) + 1;
  mountSeq.set(tile, seq);
  // veraltet = diese Kachel wurde neu montiert ODER ganz aus der Szene genommen
  const stale = () => mountSeq.get(tile) !== seq || tile.group.parent === null;
  const locId = tile.loc.id;
  const verify = new Verifier(verifyOn());
  // k IS 1 since E4 (§ B, task 1) — the field stays in the payload for the
  // consumer contracts and this client no longer multiplies by it anywhere.
  // Said out loud ONCE per session rather than swallowed: a server that starts
  // sending something else would otherwise draw a silently wrong-sized world.
  assertUnitScale(scene.k);

  // Surface-Bilder FERTIG laden, bevor Platten/Wände sie klonen (Klone eines
  // noch ladenden Bildes bleiben leer).
  const kinds = new Set<string>(['floor']);
  for (const p of scene.plates) if (p.texture_kind) kinds.add(p.texture_kind);
  for (const w of scene.walls) if (w.texture_kind) kinds.add(w.texture_kind);
  await Promise.all([...kinds].map(preloadSurfaceTexture));
  if (stale()) return null;

  // Vorherigen Aufbau entfernen (Remount bei Signatur-Wechsel).
  unmountScene(tile);
  // Fresh placement ledger for the tier swap (Etappe 3): every model spec of
  // THIS mount registers below; an in-flight swap of the old mount finds its
  // record gone and drops its answer.
  const placements: PlacedSceneModel[] = [];
  tile.placedModels = placements;

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
  // Detail-Modus der LOCATION (v5.2 Nr. 10) — kommt als Payload-Flag und
  // gilt auch OHNE Location-Modell (der Wald hat bewusst keins mehr): der
  // Backstop rutscht UNTER die Etage-0-Platten, sonst begräbt er bei 0,04
  // genau die Zonen-Texturen, die er stützen soll (User-Befund 2026-08-02).
  // Ein vorhandenes Modell bestätigt das Flag nur (display shell_area).
  tile.modelIsShellArea = !!scene.area_detail;
  if (tile.groundPlate) {
    // −0,05 statt −0,01: 1 cm unter den Etage-0-Platten reichte dem
    // Tiefenpuffer aus der Distanz nicht (Z-Fighting-Wellen, User-Bild
    // 2026-08-03); zusätzlich drückt polygonOffset den Backstop im
    // Tiefenvergleich nach hinten, damit er auch bei drapierten,
    // parallelen Flächen NIE durch die Zonen-Platten sticht.
    //
    // The OTHER branch is the mirror image and is the plate's own bias
    // (`applyPlateDepthBias`): outside detail mode the plate lies ON the world
    // ground and must never be poked through by it, so it is pulled forward
    // instead of pushed back. Restoring it here rather than zeroing it is the
    // point — a mounted scene used to strip the bias off the very plate the
    // tile was built with.
    tile.groundPlate.position.y = tile.modelIsShellArea ? -0.05 : PLATE_Y_M;
    const gm = tile.groundPlate.material as THREE.MeshStandardMaterial;
    if (tile.modelIsShellArea) {
      gm.polygonOffset = true;
      gm.polygonOffsetFactor = 1;
      gm.polygonOffsetUnits = 2;
    } else {
      applyPlateDepthBias(gm);
    }
    gm.needsUpdate = true;
  }
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
  const areaLoc = tile.natureSite || !tile.isBuilding || !!scene.area_detail
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
  // The floors of the PREVIOUS mount are gone with it (a remount arrives after
  // `unmountScene`, but a tile built fresh never saw one) — the list below is
  // filled from this payload alone.
  tile.walkPlates = [];
  for (const plate of scene.plates) {
    const mesh = buildPlate(THREE, plate, plateMaterial(plate, style));
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
    // THE FLOOR THE FIGURES STAND ON (§ B1 addendum 2026-08-20): every plate
    // is one, level contour and room plate alike, and `tileWalkY` takes the
    // highest one under the point. It is registered here rather than derived
    // later because this is where the payload's outline and its `top_y` are
    // in one hand — and it is registered for an AREA location too: there the
    // model IS the ground and the walk rule never asks these, so the list
    // costs nothing and stays true if that ever changes.
    tile.walkPlates.push({ top: plate.top_y, outline: plate.outline });
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
    // `roomRects` stays TILE-LOCAL (it always was, minus the centre offset):
    // an axis-aligned rectangle only means something in the frame it was
    // measured in, and the tile may stand turned since E4. Its readers turn
    // their query point instead (`worldToTile`).
    tile.roomRects.set(id, { x: cx, z: cz, w, d });
    // Raum-Mitte: eine Instanz, unter ID UND Name — die Abtastung hebt ihr Y
    // später auf die gemessene Bodenhöhe (setY auf der geteilten Instanz).
    const centre = tileToWorld(tile, cx, cz, plate.top_y + 0.01);
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
    tile.roomRects.set(id, { x: ov.rect.x, z: ov.rect.z,
                             w: ov.rect.w, d: ov.rect.d });
    const centre = tileToWorld(tile, ov.centre[0], ov.centre[1], ov.y + 0.01);
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
    const { mat: wallMat, tileM } = wallMaterial(wall, style);
    const mesh = buildWall(THREE, wall, wallMat, tileM);
    parentFor(wall.room_id).add(mesh);
    builtWalls.push({ mesh, wall });
    if (!wall.glass) {
      const mid = tileToWorld(tile, (wall.from[0] + wall.to[0]) / 2,
                              (wall.from[1] + wall.to[1]) / 2);
      // The outward normal is a DIRECTION: it turns with the footprint but is
      // not shifted by its centre — the culling dots it against the camera
      // offset, so a normal left in the tile frame would cull the wrong walls
      // on a turned location.
      const n = tileDirToWorld(tile, wall.outward_normal[0], wall.outward_normal[1]);
      tile.outlineWalls.push({
        mesh, level: wall.level,
        mid: new THREE.Vector2(mid.x, mid.z),
        normal: new THREE.Vector2(n.x, n.z),
      });
      const mats = tile.levelWallMats.get(wall.level);
      const mat = mesh.material as THREE.MeshStandardMaterial;
      if (mats) mats.push(mat);
      else tile.levelWallMats.set(wall.level, [mat]);
    }
  }

  // ── Fernsicht-Hülle (finding 2026-08-20) ────────────────────────────────
  // A place without a server model showed a socle plate and a label from the
  // outside; its walls existed but only inside the crossfade. WHICH source a
  // far view has is decided in `shellPlan.ts` (pure, hand-checked in
  // `smoke_far_shell.mjs`), and 'recipe' means: stand the primitives just
  // built outside as well. Everything after this point (extras, doors,
  // markers, labels, models) is deliberately NOT part of it.
  if (wantsRecipeShell({
    isBuilding: tile.isBuilding,
    natureSite: !!tile.natureSite,
    areaDetail: !!scene.area_detail,
    // A ROOF-ONLY building model (§ B addendum 2026-08-20) is not an answer to
    // "does this place have a shape": it is a lid over the shape the recipe
    // primitives are. Counting it here would take the walls away and leave a
    // roof floating over a socle plate.
    hasBuildingModel: scene.models.some((m) => m.role === 'building' && !m.roof_only),
    plates: scene.plates.length,
    walls: scene.walls.length,
  })) buildFarShell(tile, builtPlates, builtWalls);

  // ── Extras (elevator) ───────────────────────────────────────────────────
  // Typed boxes, centre + size, straight from the payload — one entry per
  // part. The pads double as the stops for the level routing.
  let elevatorXZ: THREE.Vector2 | null = null;
  for (const extra of scene.extras) {
    g.add(buildExtra(THREE, extra, extraMaterial(extra, style)));
    elevatorXZ = elevatorXZ ?? new THREE.Vector2(extra.center[0], extra.center[2]);
    if (extra.kind === 'elevator_pad' && extra.level !== undefined) {
      tile.elevatorStops = tile.elevatorStops ?? new Map();
      tile.elevatorStops.set(extra.level, tileToWorld(tile,
        extra.center[0], extra.center[2],
        extra.center[1] + extra.size[1] / 2 + 0.01));
    }
  }

  // ── Türen & Marker: fertig in Weltkoordinaten ───────────────────────────
  // THE door of each room, for the floor sampling's reference ray: the one
  // leading outside, else the first the payload lists (`roomDoor`, the same
  // rule the walk uses). Read, never derived (plan-betreten-und-tueren.md
  // § 4.1) — and kept on the tile rather than looked up per call, because the
  // model-tier swap re-samples a room without having the payload at hand.
  // Asked in the TILE frame (origin 0/0, `doors.ts` default) and turned into
  // the world here: the payload is tile-local and the footprint may stand
  // rotated, so baking the centre in before the turn would misplace every door
  // of a turned location.
  const roomsWithDoor = new Set<string>();
  for (const doorway of scene.doorways) {
    for (const id of doorway.rooms ?? []) if (id) roomsWithDoor.add(id);
  }
  for (const id of roomsWithDoor) {
    const door = roomDoor(scene, id);
    if (door) {
      tile.roomDoors.set(id, tileToWorld(tile, door.mid.x, door.mid.z, door.baseY));
    }
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
      p: tileToWorld(tile, marker.at_world[0], marker.at_world[1],
                     marker.y_world - drop),
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
    // The label hangs INSIDE the tile group, so it wants the tile-local
    // rectangle — which is exactly what `roomRects` holds.
    label.position.set(rect ? rect.x : 0,
                       floorY + Math.min(1.5, scene.storey_m * 0.8),
                       rect ? rect.z : 0);
    rg.add(label);
    tile.interiorLabels.push(label);
  }
  // `interiorLift` stand hier bis Etappe 3: die Zoom-Zugabe des entfernten
  // Distanz-Aufklappens — die Detail-Ansicht öffnet jetzt ereignisgetrieben.
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
    // Tier (§ B1 variants): the caller says which tier this mount loads —
    // view state (camera distance / open detail view, Etappe 3 of
    // plan-3d-lod-und-betreten.md); a missing tier falls back to the best
    // existing one inside pickVariant. WELCHE Modell-Variante eines Props
    // (E2.3) gilt, steht in der Spec (`variant`) — `pickModelVariant` wählt
    // sie und danach die Stufe; ohne Varianten ist es dasselbe wie zuvor.
    const url = pickModelVariant(spec, tierOf(spec, tiers));
    if (url) {
      const raw = await loadGlb(url, tile.center);
      if (stale()) return;
      source = raw ? raw.clone(true) : null;
    }
    if (!source && spec.placeholder_dims) {
      // missing / has_model:false → Platzhalter in gelieferter Größe; die
      // Platzierung wird NIE verworfen (§ A2).
      const ph = buildPlaceholder(THREE, spec.placeholder_dims, placeholderMaterial());
      ph.receiveShadow = true;
      ph.position.set(spec.anchor[0], spec.bottom_y, spec.anchor[1]);
      // `+rad` since E4 — the same sign `placeModelSpec` turns a real mesh by
      // (§ A1.1). A placeholder that turned the other way would stand mirrored
      // against the mesh it stands in for.
      ph.rotation.y = deg(spec.yaw_deg);
      const parent = parentFor(spec.room_id);
      parent.add(ph);
      placements.push({ spec, url, object: ph, parent, placeholder: true });
      verify.placed += 1;
      // Auch der Platzhalter wird gegen seine Spec geprüft: er steht an
      // derselben Stelle und hat dieselbe Zielgröße wie das fehlende Mesh
      // (dims × k). Ohne diese Prüfung blieb ein Loch in der Abdeckung —
      // an 526cf40b waren das 2 Props / 8 Prüfungen, und die Verify-Summe
      // lag ohne Grund unter dem Soll.
      verify.placement(ph, spec, tile);
      return;
    }
    if (stale()) return;
    if (!source) {
      // Mesh nach allen Versuchen nicht ladbar UND kein Platzhalter geliefert:
      // hier fehlt ein Objekt in der Szene. Das wird GEZÄHLT (A3) — früher
      // verschwand die Platzierung stillschweigend und die Verify-Tabelle
      // meldete trotzdem „keine Abweichung". The ledger entry is still
      // written: a later tier swap may try the mesh again.
      placements.push({ spec, url, object: null, parent: parentFor(spec.room_id) });
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
      applyBuildingModel(tile, placed, spec);
      placements.push({ spec, url, object: placed });
    } else {
      const parent = parentFor(spec.room_id);
      parent.add(placed);
      placements.push({ spec, url, object: placed, parent });
      if (spec.role === 'room' && spec.walk_y_world !== undefined && spec.room_id) {
        walkY.set(spec.room_id, spec.walk_y_world);
      }
      const clipped = applyModelClip(tile, placed, spec);
      if (clipped) verify.clipped(spec, clipped);
    }
    verify.placement(placed, spec, tile);
  }));
  if (stale()) return null;

  // …and the second occasion for the far-view shell: a payload that DECLARED a
  // building model whose mesh never loaded (and brought no placeholder either).
  // The place would otherwise be exactly as shapeless as one with no model at
  // all — the finding again, only harder to see because the payload says the
  // shape exists. `hasBuildingModel` is false HERE on purpose: whatever the
  // payload declared, nothing of it stands.
  if (!tile.shell && !tile.serverModel && wantsRecipeShell({
    isBuilding: tile.isBuilding,
    natureSite: !!tile.natureSite,
    areaDetail: !!scene.area_detail,
    hasBuildingModel: false,
    plates: scene.plates.length,
    walls: scene.walls.length,
  })) buildFarShell(tile, builtPlates, builtWalls);

  // ── DIE DEKLARIERTEN BÖDEN dieser Szene (§ B6 Nr. 7) ────────────────────
  // Bis hier war `walk_y_world` eine reine Abtast-Vorgabe und endete in
  // diesem Block; die laufende Figur (`tileWalkY`) hat sie NIE gesehen. Genau
  // das war der Befund an der Mondhütte: der Regler bewegte die NPC-Spots und
  // die Raummitte, die Figur stand weiter auf dem Kachelboden. Die Ansage
  // gehört an die Kachel, nicht in diese Funktion.
  //
  // Die Hülle ist die des RAUMS aus dem Payload (§ B1), nicht die der Platte:
  // eine Ansage gilt für den Raum, auch wenn er gar keine Platte zeichnet.
  tile.declaredFloors = [];
  for (const room of scene.rooms) {
    const top = walkY.get(room.room_id);
    if (top === undefined) continue;
    tile.declaredFloors.push({ roomId: room.room_id, top, outline: room.outline });
  }

  // ── Begehbarkeit abtasten (Sicht-/Spiel-Logik, bleibt Client) ───────────
  // Über ALLES im Raum: Platte, Wände, Diorama, Props.
  for (const [id, rg] of roomGroup) {
    // walk_y (§ B6 Nr. 7): die deklarierte Standhöhe geht als Boden-SOLL in
    // die Abtastung — sie schlägt dort die Höhen-Heuristik, und damit stehen
    // auch die STEH-SPOTS (nicht nur Mitte/Exit) auf dem sichtbaren Boden.
    //
    // Ohne Diorama ist das SOLL die ROOM PLATE (decision 2026-08-20): sie ist
    // der Boden, den der Payload zeichnet und auf den er die Props des Raums
    // stellt — dieselbe Fläche, auf der `tileWalkY` die Figuren stehen lässt.
    // Vorher entschied hier die Höhen-Heuristik über die Strahl-Treffer, und
    // die fand in einem Raum ohne Diorama den Boden des Hüllen-Meshes: NPC-
    // Spots und Figuren standen auf zwei verschiedenen Böden.
    sampleRoomWalkables(tile, id, rg, walkY.get(id) ?? roomPlateTop.get(id));
  }

  // ── Verify (§ B5a): primitives against the target ───────────────────────
  // Only now measure: the tile matrices are set, every object hangs in its
  // final place. WHICH numbers a plate or a wall has to match follows from
  // the payload and therefore comes from the shared package
  // (plateTargets/wallTargets) — the admin preview diffs the same fields.
  if (verify.active) {
    tile.group.updateMatrixWorld(true);
    for (const { mesh, plate } of builtPlates) {
      verify.primitive(mesh, tile,
        `plate:${plate.room_id || 'level'}@${plate.level}`, plateTargets(plate));
    }
    for (const { mesh, wall } of builtWalls) {
      verify.primitive(mesh, tile,
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

/**
 * The FAR-VIEW SHELL of a location without a server model (user finding
 * 2026-08-20): the § B primitives it already has, standing outside instead of
 * only inside.
 *
 * The problem it answers: since the procedural hut was struck (2026-08-19) a
 * building with a room layout but no mesh was a socle plate and a label — its
 * walls existed, but they hang in `tile.interior`, which the crossfade only
 * uncovers once the player ENTERS. So the world was full of places you could
 * not see until you stood in them.
 *
 * WHAT IS COPIED, and nothing else: the LEVEL plates (the storey contours,
 * `plate.room_id` absent) and every non-glass wall — contour and room alike,
 * with their window and door gaps, because the payload delivers walls already
 * split around every opening (§ B1). No models, no props, no markers, no
 * labels, no room interiors: this is a SHAPE, not a second scene.
 *
 * THE GEOMETRY IS SHARED, ONLY THE MATERIAL IS A CLONE. `Mesh.clone()` keeps
 * the same `BufferGeometry` — the shell costs a draw call per primitive and no
 * vertex memory at all — while the material has to be its own, because the
 * crossfade drives its opacity and the corridor fade
 * (`applyOcclusionFade`) opens it up for an embodied avatar exactly as it does
 * a model shell or a tree.
 *
 * IT IS A `tile.shell` and takes the shell handover unchanged: the moment a
 * server model does arrive for this place, `applySceneBuilding` drops it
 * (`dropFarShell`) and takes over `roofParts`/`roofMats` itself.
 *
 * ROOFLESS, AND SAID OUT LOUD: the payload has no roof primitive family, so a
 * place seen from above is open. Inventing a lid would be the procedural hut
 * again, one storey higher.
 */
function buildFarShell(tile: Tile,
                       plates: { mesh: THREE.Mesh; plate: ScenePlate }[],
                       walls: { mesh: THREE.Mesh; wall: SceneWall }[]): void {
  const shell = new THREE.Group();
  shell.name = FAR_SHELL_GROUP;
  const mats: THREE.MeshStandardMaterial[] = [];
  const take = (src: THREE.Mesh) => {
    const copy = src.clone();
    const base = src.material as THREE.Material;
    const mat = base.clone() as THREE.MeshStandardMaterial;
    // The crossfade writes `opacity` on this material (`applyTileFade` →
    // roofMats), which an opaque material would ignore.
    mat.transparent = true;
    applyOcclusionFade(mat);
    copy.material = mat;
    copy.castShadow = true;
    copy.receiveShadow = false;
    // PICKING STAYS WITH THE SOCLE PLATE. A click on a place selected the tile
    // before this shell existed and must select exactly the same tile now —
    // so the copy is invisible to the raycaster (the pattern of
    // `buildBoundaryMarks`), and what a click does cannot depend on whether a
    // location happens to have a room layout.
    copy.raycast = () => {};
    mats.push(mat);
    shell.add(copy);
  };
  // The parents of the originals (the scene group, a room group) carry no
  // transform of their own, so a copy hung directly under the tile stands in
  // exactly the same place.
  // STOREYS AT OR ABOVE GROUND ONLY: a basement is not part of a silhouette,
  // and its walls would stand under the tile's own opaque socle plate.
  for (const { mesh, plate } of plates) {
    if (!plate.room_id && plate.level >= 0) take(mesh);
  }
  for (const { mesh, wall } of walls) if (!wall.glass && wall.level >= 0) take(mesh);
  if (!shell.children.length) return;
  shell.userData.shellMats = mats;
  tile.shell = shell;
  tile.roofParts.push(shell);
  tile.roofMats.push(...mats);
  tile.group.add(shell);
  // …and the label rises to the top of the real shape instead of floating at
  // the fixed reading height a place without a model was given (`buildTile`).
  // Same reading as the model branch: measured after the group hangs in the
  // world, so the tile's own transform is in it.
  shell.updateMatrixWorld(true);
  const box = new THREE.Box3().setFromObject(shell);
  if (box.max.y > box.min.y) {
    tile.height = box.max.y - box.min.y;
    tile.labelObj?.position.set(0, tile.height + 2.2, 0);
  }
}

/** Take the far-view shell down and free what it owns — its material clones.
 *  The GEOMETRIES belong to the interior primitives it was cloned from and are
 *  freed with them; disposing them here would empty the walls the player is
 *  standing in. */
function dropFarShell(tile: Tile): void {
  const shell = tile.shell;
  if (!shell) return;
  tile.group.remove(shell);
  const mats = (shell.userData.shellMats as THREE.Material[] | undefined) ?? [];
  tile.roofParts = tile.roofParts.filter((o) => o !== shell);
  tile.roofMats = tile.roofMats.filter((m) => !mats.includes(m));
  for (const m of mats) m.dispose();
  shell.clear();
  tile.shell = undefined;
}

/** Building spec applied in full — shell swap plus cutouts. Shared by the
 *  mount and the tier swap, so both paths stay one behaviour. What the model
 *  IS says the SPEC (`display`), never a side effect: "area location" used to
 *  be guessed from `cutouts.length > 0` and a plain area (Mondscheinsee, no
 *  outline) faded away like a shell (user finding 2026-07-28). */
function applyBuildingModel(tile: Tile, placed: THREE.Group,
                            spec: SceneModelSpec): void {
  applySceneBuilding(tile, placed, spec.display ?? 'shell', !!spec.roof_only);
  // Die deklarierte Standhöhe reist mit: `tileGroundY` misst den Dachschutz
  // daran, statt an einer festen 1,2-m-Marke (Befund B8, game/ground.ts).
  tile.modelWalkY = spec.walk_y_world;
  const cutouts = spec.cutouts || [];
  if (cutouts.length) {
    // Polygone kommen um das Kachelzentrum, der Shader misst in
    // Weltkoordinaten — dieselbe Umrechnung wie beim Raum-Clip.
    tile.cutouts?.dispose();
    tile.cutouts = applyCutouts(THREE, placed, cutouts.map(
      (poly) => poly.map(([cx, cz]) => {
        const w = tileToWorld(tile, cx, cz);
        return [w.x, w.z] as [number, number];
      })));
    // Sofort den aktuellen Sichtzustand anlegen: die Kachel kann bereits
    // in der Innenansicht stehen, wenn das Modell nachträglich eintrifft.
    tile.cutouts.setEnabled(tile.fade > 0.03);
  }
}

/** Room clipping (§ B1): ONLY the spec model is cut — figures and markers
 *  stay untouched, they deliberately stand at the edge too. The polygon comes
 *  around the tile centre, the shader measures in world coordinates. Returns
 *  the applied point count (0 = no clip). */
function applyModelClip(tile: Tile, placed: THREE.Object3D,
                        spec: SceneModelSpec): number {
  const clip = spec.clip_outline;
  if (!clip || clip.length < 3) return 0;
  applyClipOutline(THREE, placed, clip.slice(0, CLIP_MAX_POINTS).map(
    ([cx, cz]) => {
      const w = tileToWorld(tile, cx, cz);
      return [w.x, w.z] as [number, number];
    }));
  return Math.min(clip.length, CLIP_MAX_POINTS);
}

/**
 * Swap the mounted models of ONE group onto another resolution tier
 * (plan-3d-lod-und-betreten.md Etappe 3): `building` = the far-view model
 * (camera-distance driven), `interior` = dioramas + props (area locations
 * carry `low` while closed, `full` while open). WHICH tier is wanted is the
 * caller's view state; this routine only resolves URLs via `pickVariant` and
 * swaps in place.
 *
 * Swap rules: the standing mesh stays visible until the replacement finished
 * loading (no flash of nothing); a spec whose variants resolve to the SAME
 * URL (no low tier authored) is a no-op — zero special cases. Swapped-out
 * clones leave the graph and their CLONED materials are disposed (clip
 * shaders, shell/roof clones); geometries and base materials belong to the
 * loader cache and stay.
 */
export async function setSceneModelTier(tile: Tile, group: 'building' | 'interior',
                                        tier: ModelTier): Promise<void> {
  const placements = tile.placedModels;
  if (!placements) return;
  await Promise.all(placements.map(async (rec) => {
    if ((group === 'building') !== (rec.spec.role === 'building')) return;
    const url = pickModelVariant(rec.spec, tier);
    if (!url || url === rec.url) return;
    if (rec.wantUrl === url) return;            // same swap already in flight
    rec.wantUrl = url;
    const raw = await loadGlb(url, tile.center);
    // Superseded: a newer wish overwrote ours, or a remount replaced the
    // whole ledger — either way this answer belongs to nobody.
    if (rec.wantUrl !== url || tile.placedModels !== placements) return;
    rec.wantUrl = undefined;
    if (!raw) return;                            // keep what stands
    const placed = placeModelSpec(THREE, raw.clone(true), rec.spec,
                                  { clone: false, clip: false });
    const old = rec.object;
    if (rec.spec.role === 'building') {
      // applySceneBuilding clones the shell materials into roofMats — capture
      // the OLD clones before it resets the list, they are disposed below.
      const oldMats = [...tile.roofMats];
      applyBuildingModel(tile, placed, rec.spec);
      if (old) {
        tile.group.remove(old);
        // Only what the swap really replaced: with a roof-only model the far
        // shell stays standing and KEEPS its material clones in `roofMats`
        // (§ B addendum 2026-08-20) — disposing those would empty the walls
        // under the new roof.
        for (const m of oldMats) if (!tile.roofMats.includes(m)) m.dispose();
      }
    } else {
      applyModelClip(tile, placed, rec.spec);
      rec.parent?.add(placed);
      if (old) {
        old.parent?.remove(old);
        disposeClipMaterials(old);
        const mesh = old as THREE.Mesh;
        if (rec.placeholder && mesh.isMesh) {
          // The grey box owns its geometry and material (buildPlaceholder).
          mesh.geometry.dispose();
          (mesh.material as THREE.Material).dispose();
        }
      }
    }
    rec.object = placed;
    rec.url = url;
    rec.placeholder = false;
  }));
  if (tile.placedModels !== placements) return;
  // A swapped diorama changes the sampled floor and furniture — re-read the
  // affected rooms exactly the way the mount does, so figures keep standing
  // on what is actually visible.
  if (group === 'interior') {
    const roomsChanged = new Set<string>();
    for (const rec of placements) {
      if (rec.spec.role === 'room' && rec.spec.room_id) roomsChanged.add(rec.spec.room_id);
    }
    for (const id of roomsChanged) {
      const rg = tile.roomGroups.get(id);
      if (!rg) continue;
      const declared = placements.find((r) => r.spec.role === 'room'
        && r.spec.room_id === id
        && r.spec.walk_y_world !== undefined)?.spec.walk_y_world;
      // …and without a declaring diorama the ROOM PLATE is the floor, exactly
      // as in the mount above. The slot holder was placed on `plate.top_y` in
      // the same loop that built the plate, so this IS that number.
      //
      // `tile.declaredFloors` needs NO update here, and that is a property of
      // the swap and not an omission: a tier exchanges the URL inside the SAME
      // spec object (`rec.spec` is untouched above), and `walk_y` is a dial of
      // the SUBJECT, read off the default tier's sidecar for every tier
      // (`location_model3d.get_client_meta`). `declared` is therefore the same
      // number the mount already wrote. What DOES change is the mesh, which is
      // why the sampling below has to run again.
      sampleRoomWalkables(tile, id, rg,
                          declared ?? tile.roomSlots.get(id)?.holder.position.y);
    }
  }
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
                            display: NonNullable<SceneModelSpec['display']> = 'shell',
                            roofOnly = false): void {
  // The handover: whatever stood in for the model — the far-view shell built
  // from the recipe's own primitives — goes when the real one arrives.
  //
  // EXCEPT for a ROOF (§ B addendum 2026-08-20, docs/llm-blender-models.md):
  // a `roof_only` model is a lid over the very walls the shell is, so there is
  // nothing to hand over. The shell stays, the roof joins it, and both fade
  // together on the way in — which is why the two lists below are APPENDED to
  // instead of reset in that case.
  if (!roofOnly) dropFarShell(tile);
  tile.serverModel = model;
  // `area` = das Modell bleibt stehen und bekommt Löcher; das gilt NUR für
  // `ground`. Der Detail-Modus fadet und wird deshalb unten wie eine Hülle
  // behandelt — sein Kachelboden folgt dafür dem Fade (applyTileFade).
  const area = display === 'ground';
  tile.modelIsGround = area;
  // Nur SETZEN, nie löschen — das Payload-Flag `scene.area_detail` hat die
  // Kachel schon markiert, wenn die Location auch ohne Modell im
  // Detail-Modus ist.
  if (display === 'shell_area') tile.modelIsShellArea = true;
  // Eine Flächen-Location BRINGT ihren Boden mit. Die kachel-eigene Platte
  // (10 × 10 m, undurchsichtig, y 0,04) steht in keinem Payload — sie ist
  // Client-Erfindung und schnitt das Modell auf ihrer Höhe ab: beim
  // Mondscheinsee lag alles unter +0,04 dahinter, also Seebecken und Strand
  // (Modell y −0,80 … +2,69). Für `display: ground` bleibt sie weg.
  if (tile.groundPlate) tile.groundPlate.visible = !area;
  // Die Backstop-Höhe (−0,01 im Detail-Modus) setzt mountScene zentral —
  // hier würde sie nur dupliziert.
  tile.shellMats = [];
  // A kept far shell brought its own material clones into `roofMats`; they
  // stay in the fade, the roof's clones are added to them below.
  tile.roofMats = roofOnly ? [...tile.roofMats] : [];
  const keptParts = roofOnly ? tile.roofParts : [];
  // An AREA location: the model IS the location and stays visible — it does not
  // go into roofParts/roofMats, which the crossfade takes away. The cutouts do
  // the revealing instead (`setEnabled` on the same fade state). Without a fade
  // there is no need for material clones either; the cutout routine clones on
  // its own account anyway — which is why the corridor fade below reaches only
  // the shell branch.
  tile.roofParts = area ? [] : [...keptParts, model];
  tile.facadeMats = [];
  model.traverse((o) => {
    const mesh = o as THREE.Mesh;
    if (!mesh.isMesh) return;
    if (!area) {
      const clone = (m: THREE.Material) => {
        const c = m.clone();
        c.transparent = true;
        // The shell of a location is in the way of an embodied avatar exactly
        // like a tree is, so it takes part in the corridor fade
        // (`scene/occlusion.ts`). Patched on the CLONE this line just made —
        // the loaded model's own material belongs to `loadGlb`'s cache and to
        // every other tile that shows the same building. An `area` model takes
        // no clone and no patch: it IS the location's ground, which the fade
        // deliberately leaves whole.
        applyOcclusionFade(c);
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
  // A roof measured ALONE is 2 m tall and would pull the label down into the
  // walls it sits on — the readable height of the place is shell plus roof.
  if (roofOnly && tile.shell) box.expandByObject(tile.shell);
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
  // The far-view shell is a copy of THIS scene's primitives, so it dies with
  // it — its geometries are the ones just taken out of the graph.
  dropFarShell(tile);
  // Cutout-Material-Klone der vorigen Szene freigeben (Muster
  // disposeClipMaterials — die Texturen sind mit dem Cache geteilt).
  tile.cutouts?.dispose();
  // Placement ledger of the old mount: gone with the scene — an in-flight
  // tier swap compares against this list and drops its answer.
  tile.placedModels = undefined;
  tile.cutouts = undefined;
  tile.modelIsGround = false;
  tile.modelIsShellArea = false;
  tile.modelWalkY = undefined;
  // The floors of this scene leave with it: until the next mount the tile has
  // its plate and the world under it, exactly as a place without a recipe.
  tile.walkPlates = [];
  tile.declaredFloors = [];
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
    tile.groundPlate.position.y = PLATE_Y_M;
    // Und die eigene Tiefen-Vorspannung der Platte zurueck: der Detail-Modus
    // hat sie auf den Backstop-Wert (+1/+2) gedreht, und ohne diese Zeile
    // bliebe die Kachel nach dem Aushaengen hinter ihrem eigenen Gelaende.
    applyPlateDepthBias(tile.groundPlate.material as THREE.MeshStandardMaterial);
    (tile.groundPlate.material as THREE.MeshStandardMaterial).needsUpdate = true;
  }
  for (const [, rg] of tile.roomGroups) rg.parent?.remove(rg);
  for (const label of tile.interiorLabels) label.element?.remove();
  tile.interior = null;
  tile.interiorLabels = [];
  tile.roomGroups.clear();
  tile.roomCenters.clear();
  tile.roomDoors.clear();
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
