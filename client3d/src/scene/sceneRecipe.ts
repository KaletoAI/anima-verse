import * as THREE from 'three';
import { CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import { applyClipOutline, applyCutouts, applyDepthCut, applySlotMaterials,
  buildExtra,
  buildPlaceholder,
  buildPlate, buildWall, CLIP_MAX_POINTS, disposeClipMaterials,
  disposeCutMaterials, disposeSlotMaterials, leafPivot,
  pickModelVariant, placeModelSpec, plateTargets,
  SpecVerifier, storeyGroundLift, storeyGroundRelift, VERIFY_EPS,
  surfaceMaterial, surfaceScale, wallLength, wallTargets } from '@anima/scene-render';
import type { FixEuler, LeafBox, ModelTier, PrimitiveTarget,
  VerifyRow } from '@anima/scene-render';
import {
  getLocationScene,
  type SceneExtra, type SceneModelSpec, type ScenePayload, type ScenePlate,
  type SceneWall,
} from '../api';
import { roomDoor } from '../game/doors';
import { markerLiftPoint } from '../game/placement';
import { applyOcclusionFade } from './occlusion';
import { loadGlb } from './propAssets';
import { wantsRecipeShell } from './shellPlan';
import {
  deriveRoomSpots, preloadSurfaceTexture, surfaceFor,
  surfaceMaterialSpec, tileDirToWorld, tileToWorld, worldGroundSampler,
  worldWaterSampler,
  type PlacedSceneModel, type RoomFloor, type StairWorldLink, type SwingingDoor,
  type Tile,
} from './tiles';
import { SubmergedGhost } from './submergedGhost';
import { ghostCutY, ghostWaterLevel } from '../game/walk';
import { waterInside } from './waterShade';

/** Which resolution tier a mount loads, per model group. `building` = the
 *  far-view shell/area model, `interior` = everything else (dioramas, props).
 *  Pure VIEW STATE — main.ts decides (camera distance / open detail view),
 *  `pickVariant` resolves a missing tier to the best existing one. */
export interface SceneTiers { building: ModelTier; interior: ModelTier }

const tierOf = (spec: SceneModelSpec, tiers: SceneTiers): ModelTier =>
  (spec.role === 'building' ? tiers.building : tiers.interior);

/**
 * PUT ONE PLACEMENT ON THE GROUND UNDER ITS OWN ANCHOR (§ A16.9) — the
 * client's half of the one law in `@anima/scene-render/storeyGround`, and the
 * single move that both MOUNTING and RE-DRAPING are.
 *
 * All this side does is put the arguments in the right frame: the spec's
 * anchor is TILE-LOCAL, the height field is WORLD, so the anchor is turned by
 * the footprint yaw first (`tileToWorld`, § A1.1); and the datum the payload
 * was composed against is the tile's own centre, i.e. the ground under the
 * anchor pin. A building/ground model is excluded by the rule itself — it IS
 * the plot rather than something standing on it.
 *
 * The record carries the lift it stands on; this moves the object by the
 * DIFFERENCE to the lift the height field says now and writes the new value
 * back. A fresh mount hands in a record with `lift: 0` and an object sitting on
 * its composed `bottom_y`, so the first call IS the mount — which is what makes
 * a scene mounted before its fine height tiles arrived end up, after the
 * re-lift, at the very number a scene mounted after them lands on.
 *
 * Returns the lift now applied (the verify row and the room's declared floor
 * both read it, and neither may derive it a second time).
 */
function reliftPlacement(tile: Tile, rec: PlacedSceneModel): number {
  if (rec.spec.role === 'building') return 0;
  const w = tileToWorld(tile, rec.spec.anchor[0], rec.spec.anchor[1], 0);
  const step = storeyGroundRelift(rec.lift, rec.spec.level, w.x, w.z,
                                  tile.center.y, worldGroundSampler());
  if (rec.object && step.delta) rec.object.position.y += step.delta;
  rec.lift = step.lift;
  // THE BAKED LATTICE COMES ALONG (v6): it describes where the model stands,
  // so the one funnel that moves the model moves it too — mount, re-drape and
  // tier swap alike. The entry is found ONCE by spec identity and then held on
  // the record, so a redrape does not search again.
  //
  // AND IT IS WRITTEN WHETHER OR NOT THE MESH LOADED (Minor 6). The lift is a
  // property of the PLACEMENT, not of the object: the payload states where the
  // lattice stands, and § A16.9 moves it onto the ground under its own anchor
  // whether three managed to draw a mesh there or not. Gating the write on
  // `rec.object` left a failed-to-load diorama's lattice on lift 0 while every
  // figure in it walked on the lifted ground — the walking height and the
  // (missing) mesh disagreeing by the relief under the anchor. Only the
  // OBJECT MOVE stays conditional: there is nothing to move.
  if (rec.spec.surface) {
    if (!rec.surface) rec.surface = tile.surfaces.find((e) => e.spec === rec.spec);
    if (rec.surface) rec.surface.lift = step.lift;
  }
  return step.lift;
}

/**
 * THE BOX OF A PLACEMENT'S FIX GROUP — the mesh under its EXACT orientation
 * fix, in MODEL UNITS, before the placement yaw and the `max_m` scale. That is
 * precisely the box `heightgrid.py` writes as `box_min`/`box_max`, so the two
 * are comparable number for number (the `surface_box` verify row, fix wave B).
 *
 * `placeModelSpec` builds outer → yawG → fitG → fix and hangs the source under
 * `fix`; measuring in `fitG`'s frame therefore strips the yaw and the outer
 * scale while keeping the fix. `Box3.setFromObject` cannot do that — it always
 * measures in WORLD space, and un-turning a finished AABB grows it — so the
 * union is built here from the same per-geometry boxes three itself unions,
 * each carried into `fitG`'s frame.
 *
 * `place()` then re-seats the group on its own centre (`fix.position`) AFTER
 * measuring, so that translation is taken back out: what is left is the box
 * the bake describes, seated where the bake seated it.
 *
 * `null` when the placement carries no mesh geometry at all (a placeholder,
 * an empty group) — there is nothing to compare then.
 */
function fixGroupBox(placed: THREE.Object3D): THREE.Box3 | null {
  const fitG = placed.children[0]?.children[0];
  const fix = fitG?.children[0];
  if (!fitG || !fix) return null;
  fitG.updateMatrixWorld(true);
  const inv = new THREE.Matrix4().copy(fitG.matrixWorld).invert();
  const local = new THREE.Matrix4();
  const one = new THREE.Box3();
  const box = new THREE.Box3();
  fix.traverse((o) => {
    const geo = (o as THREE.Mesh).geometry as THREE.BufferGeometry | undefined;
    if (!geo) return;
    if (!geo.boundingBox) geo.computeBoundingBox();
    if (!geo.boundingBox) return;
    local.multiplyMatrices(inv, o.matrixWorld);
    box.union(one.copy(geo.boundingBox).applyMatrix4(local));
  });
  if (box.isEmpty()) return null;
  return box.translate(fix.position.clone().negate());
}

/**
 * IS THIS PLACEMENT STANDING IN WATER — the gate of its underwater ghost
 * (`scene/submergedGhost.ts`, user decision 2026-08-25).
 *
 * The occasion is the same defect the figures had: since Wasser v2 K-A the
 * water surface IS the opaque terrain, so a crate on a lake bed, a jetty post
 * or a fish prop is cut clean off at the waterline and mostly simply gone. The
 * fix is the FIGURES' fix, one module for both — a tinted `GreaterDepth`
 * redraw below the line.
 *
 * TWO NUMBERS, and both are already computed elsewhere:
 *  - the BASE. `bottom_y` is where `place()` seats the object's lowest point,
 *    and `lift` is what § A16.9 then moved it by; both are TILE-LOCAL, so
 *    `tileToWorld` turns the anchor by the footprint yaw and adds the datum.
 *    That is the very y the object is standing at, not a second measurement of
 *    its bounding box.
 *  - the WATER. `worldWaterSampler()` is the raster the terrain draws its own
 *    surface from (K-A E2/E3), so the line the ghost cuts at is the line the
 *    player sees. `NaN` where nothing knows of water, which the gate reads as
 *    dry. It is asked the SAME question the terrain asks — level AND
 *    `waterInside(sd)`, exactly the pair of `terrainLod.liftedHeight` — because
 *    the level is dilated 4 m past the authored outline and a gate reading it
 *    alone ghosts a diorama standing on the bank (user finding 2026-08-27).
 *
 * IT IS CALLED AT PLACEMENT TIME, NOT PER FRAME. A prop does not move; what
 * moves under it is the height field and the water raster, and those arrive on
 * exactly the beats that already re-seat a placement — the mount, `reliftScene`
 * on the height revision, and the tier swap. Per-frame gating would be one
 * raster read per prop per frame for an answer that changes twice a session.
 *
 * A BUILDING/GROUND MODEL IS NOT GATED, for the same reason § A16.9 does not
 * lift it: it IS the plot rather than something standing on it, so "the water
 * over its base" is not a question about it, and a ghost spanning a whole
 * footprint would be a blue slab under the lake.
 */
function refreshPlacementGhost(tile: Tile, rec: PlacedSceneModel): void {
  if (rec.spec.role === 'building' || !rec.object) return;
  const water = worldWaterSampler();
  if (!water) return;
  const w = tileToWorld(tile, rec.spec.anchor[0], rec.spec.anchor[1],
                        rec.spec.bottom_y + rec.lift);
  const ww = water(w.x, w.z);
  const level = ghostCutY(w.y, ghostWaterLevel(ww.level, waterInside(ww.sd)));
  if (!rec.ghost) {
    // Nothing is built for a dry placement — no object, no meshes, no
    // registration. That is the red probe of the smoke.
    if (level === null) return;
    rec.ghost = new SubmergedGhost(rec.object);
  }
  rec.ghost.set(level);
}

/** Give a placement's ghost up — wherever its OBJECT goes (an unmount, a tier
 *  swap). The materials are the ghost's own and its registration is what
 *  isolation toggle 22 walks. */
function dropPlacementGhost(rec: PlacedSceneModel): void {
  rec.ghost?.dispose();
  rec.ghost = undefined;
}

/**
 * THE HEIGHT FIELD MOVED — put this tile's whole mounted scene back on it
 * (user finding 2026-08-21, the sinking Mondscheinhütte).
 *
 * The occasion: `ground.heightRevision()` counts up when the overview arrives
 * and again when each batch of 2 m tiles lands. A scene mounts as soon as its
 * payload is there, which on a fresh page load is BEFORE the tiles under it —
 * so every storey-0 placement was lifted onto whatever coarse answer the
 * sampler had at that instant and kept it. The world props already re-ask
 * (`worldProps.redrape`, § A9a); this is the same beat for the scene.
 *
 * WHAT MOVES, and it is everything the mount lifted:
 *  - every non-building placement (dioramas, props, placeholders), by the
 *    difference, through the same `reliftPlacement` the mount runs;
 *  - the FIXED markers (prop seat marks), which are composed finished and are
 *    therefore the only ones that carry a lift of their own;
 *  - the DECLARED floors a diorama states (`walk_y_world + lift`) — in
 *    `roomFloors` and in `tile.declaredFloors`, written absolutely so no
 *    correction can apply twice;
 *  - and then every room's stands, centre, seats and ROOM markers, which
 *    `deriveRoomSpots` re-derives from the sampler as it stands now.
 *
 * Nothing else in the scene is touched: plates, walls and the building/ground
 * model are not lifted by this law in the first place (§ A16.9).
 *
 * `datumDelta` IS THE FRAME'S OWN MOVE (user finding 2026-08-24, the floating
 * "Haus von Kai"): `redatumTile` ran right before this and put the tile back on
 * the ground under its pin. Everything hanging in the group came along for that
 * ride, so the re-lift below simply takes it back off again — but the scene
 * composed three things in WORLD coordinates that the group does not parent,
 * and those are carried here: the room doors, the elevator stops, the stair
 * landings and the `fixed` prop markers. A moved datum also re-derives every room, because a
 * room whose floor is DECLARED measures from that very datum.
 *
 * RETURNS whether anything in this scene actually moved. The caller needs it
 * for the one thing in the world that does NOT read its height back every
 * poll: the STEERED avatar, which is snapped onto its seat once and then held
 * there (`main.reconcileAvatarPlace`, gated by `seatedKey`). An NPC re-reads
 * `slotFor` on every worldmap poll and follows a re-lifted seat by itself; the
 * player's own figure would keep the height the seat had when it sat down.
 */
export function reliftScene(tile: Tile, datumDelta = 0): boolean {
  const placements = tile.placedModels;
  if (!placements) return false;
  if (datumDelta) {
    for (const p of tile.roomDoors.values()) p.y += datumDelta;
    for (const p of tile.elevatorStops?.values() ?? []) p.y += datumDelta;
    for (const s of tile.stairs ?? []) { s.foot.pos.y += datumDelta; s.head.pos.y += datumDelta; }
    const carried = new Set<object>();
    for (const byId of tile.roomMarkers.values()) {
      if (carried.has(byId)) continue;   // one map hangs under id AND name
      carried.add(byId);
      for (const e of byId.values()) {
        if (e.fixed) for (const s of e.slots) s.y += datumDelta;
      }
    }
  }
  const walkY = new Map<string, number>();
  let moved = datumDelta !== 0;
  for (const rec of placements) {
    const before = rec.lift;
    const lift = reliftPlacement(tile, rec);
    if (lift !== before) moved = true;
    // …and the WATER over the seat this placement now has. Same beat, same
    // reason: the height tiles and the water raster arrive together (they ride
    // in one tile payload), so the height revision that re-lifts an object is
    // also the moment its waterline first becomes knowable.
    refreshPlacementGhost(tile, rec);
    if (rec.spec.role === 'room' && rec.spec.walk_y_world !== undefined
        && rec.spec.room_id) {
      walkY.set(rec.spec.room_id, rec.spec.walk_y_world + lift);
    }
  }
  // A prop marker is finished the moment it is composed and is never
  // re-derived — so it is moved here, once, by its own difference. The same
  // marker object hangs under BOTH the room id and the room name
  // (`mountScene`), hence the identity set: a second pass over it would move
  // it twice.
  // The lift is ONE number per place, measured at the place's OWN LIFT POINT
  // (`liftAt` — for a prop marker its placement's anchor, the point the mesh
  // itself is lifted at), and applied to every slot alike. It used to be
  // measured at slot 0, which on a bench of capacity > 1 is neither the
  // marker's point nor the prop's anchor: mount and re-lift then answered two
  // different heights for the same seat (finding 2026-08-28).
  // A moved SEAT is reported separately from `moved` and deliberately does not
  // feed it: `moved` gates `deriveRoomSpots` below, and a prop marker is the
  // one thing that law never touches. Both are in the return value.
  let seatsMoved = false;
  const seen = new Set<object>();
  for (const byId of tile.roomMarkers.values()) {
    if (seen.has(byId)) continue;
    seen.add(byId);
    for (const e of byId.values()) {
      if (!e.fixed || !e.slots.length) continue;
      const step = storeyGroundRelift(e.lift, e.level, e.liftAt.x, e.liftAt.z,
                                      tile.center.y, worldGroundSampler());
      if (step.delta) {
        for (const s of e.slots) s.y += step.delta;
        seatsMoved = true;
      }
      e.lift = step.lift;
    }
  }
  for (const floor of tile.declaredFloors) {
    const top = walkY.get(floor.roomId);
    if (top !== undefined) floor.top = top;
  }
  for (const [id, floor] of tile.roomFloors) {
    const declared = walkY.get(id);
    if (declared !== undefined) floor.declared = declared;
    // A room whose floor is DECLARED and whose placements did not move has
    // nothing to re-derive: its stands, its centre and its seats are all
    // measured against that one number, and none of them asks the terrain.
    // A room whose floor IS the terrain always does — its stands are sampled
    // point by point, and the point of this call is that those points moved.
    if (moved || floor.declared === undefined) {
      deriveRoomSpots(tile, id, roomProps(placements, id));
    }
  }
  return moved || seatsMoved;
}

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

  /** Platziertes Modell gegen seine Spec prüfen. `groundLift` ist die
   *  Etage-0-Geländehebung dieser Platzierung (§ A16.9, `reliftPlacement`) —
   *  ohne sie läse jede auf einem Hang stehende Platzierung als Abweichung. */
  placement(obj: THREE.Object3D, spec: SceneModelSpec, tile: Tile,
            groundLift = 0): void {
    this.v.placement(obj, spec, tile.center, tile.yaw, groundLift);
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

/** Colour of a door leaf when the payload carries no `style.door_color` —
 *  the server's own constant (`scene_recipe.STYLE`), repeated here ONLY as the
 *  fallback for a payload composed before the field existed. */
const DOOR_COLOR_FALLBACK = '#4a3a2e';

/** Colour of a staircase (`stair_step`, `stair_pad`) when the payload carries
 *  no `style.stair_color` — the server's own constant (`scene_recipe.STYLE`),
 *  repeated here ONLY as the fallback for a payload composed before the field
 *  existed. Without it a staircase would wear the elevator's grey and the two
 *  vertical connections would look like the same thing. */
const STAIR_COLOR_FALLBACK = '#8a7a66';

/** Material of a wall segment: a PANE from its own vocabulary — a window's
 *  translucent glass or a door's opaque dark leaf — else the tiled wall
 *  texture or the wall colour.
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
  // The DOOR LEAF: opaque, dark, matte — the one thing that makes an exterior
  // door read as a door rather than as a hole into the dark.
  if (wall.leaf) {
    return { mat: std({ color: hex(style.door_color ?? DOOR_COLOR_FALLBACK),
                        roughness: 0.75 }),
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
  const stair = extra.kind === 'stair_step' || extra.kind === 'stair_pad';
  const color = glass ? style.glass_color
    : stair ? (style.stair_color ?? STAIR_COLOR_FALLBACK)
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

/** Running mount number PER TILE: a mount replaced while its GLBs were still
 *  loading must not add anything afterwards. Per tile, not global — at startup
 *  every scene location mounts at once, and a global counter would declare
 *  every mount but the last one stale. */
const mountSeq = new WeakMap<Tile, number>();

/** The node name Blender gives the door leaf it cut out (spec § 6). */
const LEAF_NODE = 'leaf';

const LEAF_PIVOT = 'leaf_pivot';

/**
 * Hang the placed model's `leaf` node in a pivot group on its hinge edge
 * (spec-picture-props.md § 6) and return that group with its axis — or
 * `undefined` when the model has no such node, in which case the whole
 * group swings as before.
 *
 * WHERE THE PIVOT SITS is the shared package's business (`leafPivot`,
 * ruling R13): `leaf_bbox` is the node's box in raw model metres and
 * `fix_euler` the orientation fix `place()` put on the model; the rule is
 * stated in the FIXED frame (min.x, min.y, centre z — the edge `place()`
 * seats) and mapped back into raw coordinates, axis included — nothing is
 * measured here (§ B5a). The pivot is inserted between the leaf and its
 * parent, BELOW the fix and INSIDE the scaled model root, so the raw
 * coordinates are the right ones: fix and fit scale sit on ancestors and act
 * on pivot and leaf alike. The leaf keeps its world position (its own
 * position is re-expressed in the pivot's frame), so hanging it changes
 * nothing until the pivot turns.
 *
 * Looked up on the CLONE `place()` returned, never on the shared source —
 * a door two rooms share must not have its leaf re-parented twice; and a
 * leaf that already hangs in a pivot is re-seated, never wrapped again.
 */
function hangLeafPivot(group: THREE.Object3D, bbox: LeafBox,
                       fix: FixEuler | undefined,
): { node: THREE.Object3D; axis: THREE.Vector3 } | undefined {
  let leaf: THREE.Object3D | undefined;
  group.traverse((o) => { if (!leaf && o.name === LEAF_NODE) leaf = o; });
  if (!leaf || !leaf.parent) return undefined;
  const spec = leafPivot(bbox, fix);
  const axis = new THREE.Vector3(spec.axis[0], spec.axis[1], spec.axis[2]);
  let pivot: THREE.Object3D;
  if (leaf.parent.name === LEAF_PIVOT) {
    // Already wrapped (a second registration of the same clone): put the
    // leaf back where it was and seat the existing pivot anew.
    pivot = leaf.parent;
    leaf.position.add(pivot.position);
    pivot.rotation.set(0, 0, 0);
  } else {
    pivot = new THREE.Group();
    pivot.name = LEAF_PIVOT;
    leaf.parent.add(pivot);
    pivot.add(leaf);                     // `add` takes it off the parent
  }
  pivot.position.set(spec.point[0], spec.point[1], spec.point[2]);
  leaf.position.sub(pivot.position);
  pivot.updateMatrixWorld(true);
  return { node: pivot, axis };
}

/**
 * Remember a placed DOOR PROP so the frame loop can swing it (v5).
 *
 * Everything it needs is READ, never derived: the sign out of `door.swing`,
 * the threshold's centre and the rooms it joins out of the `doorways[]` entry
 * `door.opening` points at, and the base yaw off the node that will turn —
 * the leaf pivot when the model has a `leaf` node and the payload a
 * `leaf_bbox` (spec § 6), else the group `placeModelSpec` just returned. A
 * spec whose index points nowhere registers nothing — the prop still stands,
 * it simply never opens.
 */
function registerDoorProp(list: SwingingDoor[], scene: ScenePayload,
                          spec: SceneModelSpec, group: THREE.Object3D): void {
  const door = spec.door;
  if (!door) return;
  const way = (scene.doorways ?? [])[door.opening];
  if (!way || !Array.isArray(way.at_world)) return;
  const hinge = door.hinge === 'right' ? 'right' : 'left';
  const leafBbox = door.leaf_bbox;
  const fixEuler = spec.fix_euler;
  const hung = leafBbox ? hangLeafPivot(group, leafBbox, fixEuler) : undefined;
  list.push({
    group,
    // Only ±1 ever reaches the object: a garbled or missing field would end up
    // as `rotation.y = NaN` and take the whole door out of the picture, and a
    // door that opens the wrong way is a far smaller lie than one that
    // vanishes. The payload's own value is `1 | -1`.
    swing: door.swing === -1 ? -1 : 1,
    at: { x: way.at_world[0], z: way.at_world[1] },
    level: Number(way.level) || 0,
    rooms: (way.rooms ?? []).filter((r): r is string => typeof r === 'string' && !!r),
    baseYaw: group.rotation.y,
    angle: 0,
    swingNode: hung?.node,
    swingAxis: hung?.axis,
    leafBbox,
    fixEuler,
    hinge,
  });
}

/** How THIS client turns a slot's payload URL into a texture (§ B2 v5). It
 *  stays here rather than in the shared package: the loading
 *  policy is the app's (the preview loads on its own terms), while "sRGB, not
 *  flipped, onto `map`" is the same everywhere and lives in
 *  `applySlotMaterials`. Deliberately NOT cached by URL — a texture belongs to
 *  the placement that disposes it. */
const slotTexture = (url: string, onError?: () => void) =>
  new THREE.TextureLoader().load(url, undefined, undefined, onError);

/** Fill the texture slots of one placed group and REMEMBER the clones on its
 *  record, so the tier swap and the unmount can free them. The record is the
 *  only thing that knows they exist. */
function fillSlots(rec: PlacedSceneModel, placed: THREE.Object3D): void {
  rec.slotMats = applySlotMaterials(THREE, placed, rec.spec.slots, slotTexture);
}

/** A tier swap has replaced a door prop's mesh: the swing list points at the
 *  GROUP, so it has to follow, or that door would freeze at whatever angle the
 *  group taken out of the graph stood at. The angle carries over — it says
 *  where the door STANDS, and the fresh group is placed shut. The LEAF PIVOT
 *  is hung again on the fresh mesh (spec § 6): the `leaf` node lives in the
 *  file that was just swapped, and a distance tier without one falls back
 *  to swinging the whole group. */
function retargetDoorProp(tile: Tile, old: THREE.Object3D,
                          next: THREE.Object3D): void {
  for (const door of tile.doorProps ?? []) {
    if (door.group !== old) continue;
    door.group = next;
    const hung = door.leafBbox
      ? hangLeafPivot(next, door.leafBbox, door.fixEuler) : undefined;
    door.swingNode = hung?.node;
    door.swingAxis = hung?.axis;
    door.baseYaw = next.rotation.y;
    if (door.swingNode && door.swingAxis) {
      door.swingNode.setRotationFromAxisAngle(door.swingAxis, door.angle);
    } else {
      next.rotation.y = door.baseYaw + door.angle;
    }
  }
}

/** The PLACED PROPS of one room — what the sit/lie derivation measures its
 *  bounding boxes on (`deriveRoomSpots`). A prop whose mesh never loaded and
 *  that got no placeholder either has no object and therefore no surface; the
 *  room diorama is deliberately not in the list, it is the room's SHELL and its
 *  box would be the whole room. */
function roomProps(placements: readonly PlacedSceneModel[], roomId: string
): THREE.Object3D[] {
  const out: THREE.Object3D[] = [];
  for (const rec of placements) {
    if (rec.spec.role !== 'prop' || rec.spec.room_id !== roomId) continue;
    if (rec.object) out.push(rec.object);
  }
  return out;
}

/**
 * Die komplette Innenansicht einer Location aus dem Payload bauen.
 *
 * Füllt die Tile-Felder der Innenansicht
 * (roomGroups/-Centers/-Exits/-Levels/-Rects/-Slots/-Markers, outlineWalls,
 * levelSlabs, levelWallMats, elevatorStops, stairs, alwaysVisibleRooms, interior,
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
  // The DOOR PROPS of this mount (v5) — filled below as the model specs land,
  // read by the frame loop that swings them, and dropped with the scene by
  // `unmountScene`. Pure view state: nothing in here is ever persisted.
  const doorProps: SwingingDoor[] = [];
  tile.doorProps = doorProps;

  const g = new THREE.Group();
  g.name = SCENE_GROUP;
  g.visible = false;                      // the crossfade uncovers it
  // NUR eine Szene mit INNEN-Inhalt ist eine Innenansicht: eine Location,
  // deren Payload allein aus dem Gebäudemodell besteht (Mondscheinsee —
  // Modell, aber keine Räume/Platten/Wände), darf beim Reinzoomen NICHT
  // ausgeblendet werden; es gäbe nichts aufzudecken.
  // …and since E5a a storey-0 room is DATA rather than a plate, so the floor
  // plan counts here exactly as its plates used to: a location made of nothing
  // but open zones still has an inside to uncover.
  const hasInterior = scene.plates.length > 0 || scene.floor_plan.length > 0
    || scene.walls.length > 0
    || scene.extras.length > 0 || scene.markers.length > 0
    || scene.models.some((m) => m.role !== 'building');
  tile.interior = hasInterior ? g : null;
  tile.group.add(g);

  const style = scene.style;
  const floorYof = new Map(scene.levels.map((l) => [l.level, l.floor_y]));
  const levels = scene.levels.map((l) => l.level);
  // Signal for the camera rule that opens a basement view (main.ts): this
  // scene has a storey below ground. The ground itself opens only while the
  // storey switch shows a level below 0 — this flag says there is one to show.
  // The recipe itself needs nothing for this.
  tile.hasBasement = levels.some((lv) => lv < 0);

  // THE SCENE'S OWN RELIEF IS GONE ("Ein Boden" E5a, decision 1): there is no
  // `terrain` block in the payload any more and nothing is draped over one.
  // Local relief is authored through the map's HEIGHT AREAS, and the one ground
  // under a location is the world field (§ A16).
  //
  // Detail-Modus der LOCATION (v5.2 Nr. 10) — kommt als Payload-Flag und
  // gilt auch OHNE Location-Modell (der Wald hat bewusst keins mehr): der
  // Backstop rutscht UNTER die Etage-0-Platten, sonst begräbt er bei 0,04
  // genau die Zonen-Texturen, die er stützen soll (User-Befund 2026-08-02).
  // Ein vorhandenes Modell bestätigt das Flag nur (display shell_area).
  tile.modelIsShellArea = !!scene.area_detail;
  // THE BACKSTOP IS GONE ("Ein Boden" E3, plan § 3.1). A mounted scene used to
  // shove the tile's own ground plate under its storey-0 surfaces (−0.05, or
  // −0.13 under a natural location), pushed it back in the depth test and
  // re-draped its geometry over `scene.terrain` — three mechanisms whose only
  // job was to keep a SECOND ground from poking through the first. The tile
  // carries no plate any more, so nothing here places, biases or drapes one:
  // what the scene does not cover, the world terrain shows.

  // Area/terrain location (forest, lake, village): rooms are ZONES, not
  // rooms — the rule feeds the room labels, the panel AND the plates below.
  const areaLoc = tile.natureSite || !tile.isBuilding || !!scene.area_detail
    || (scene.models || []).some((m) => m.role === 'building'
        && (m.display === 'ground' || m.display === 'shell_area'));

  // ── Rooms: groups, storeys, outdoor flags ───────────────────────────────
  // Outdoor rooms (§ A5) hang straight off the tile and are therefore visible
  // at every zoom level; interior rooms hang off the interior view.
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

  // ── Plates: THE DECLARED STOREYS ONLY (E5a) ─────────────────────────────
  // Storey 0 draws none any more — its height is the terrain and its material
  // is the layer bake — so what is built here is upper floors and basements.
  // A room plate of such a storey is still where that room's floor is, which is
  // why its `top_y` travels into `roomFloors` below.
  const roomPlateTop = new Map<string, number>();
  /** Gebaute Primitive für den Verify-Durchgang — vermessen wird erst, wenn
   *  die Kachel-Matrizen stehen (sonst misst man Zwischenzustände). */
  const builtPlates: { mesh: THREE.Mesh; plate: ScenePlate }[] = [];
  const builtWalls: { mesh: THREE.Mesh; wall: SceneWall }[] = [];
  // The floors of the PREVIOUS mount are gone with it (a remount arrives after
  // `unmountScene`, but a tile built fresh never saw one) — the list below is
  // filled from this payload alone.
  tile.walkPlates = [];
  // The BAKED SURFACES (v6): collected synchronously from the payload, before
  // any model has loaded — the figure stands right when the scene arrives.
  // `lift` starts at 0 and is written by `reliftPlacement` once the placement
  // is on its ground; an entry whose mesh never loads keeps 0, which is the
  // composed height the payload itself states.
  tile.surfaces = scene.models
    .filter((m) => m.surface)
    .map((m) => ({ id: `${m.role}:${m.id}:${m.room_id ?? ''}`, spec: m, surface: m.surface!,
                   lift: 0, level: m.level, roomId: m.room_id ?? '' }));
  for (const plate of scene.plates) {
    const mesh = buildPlate(THREE, plate, plateMaterial(plate, style));
    // THE FLOOR THE FIGURES STAND ON (§ B1 addendum 2026-08-20): every plate is
    // one, and `tileWalkY` takes the highest one under the point that is still
    // below the storey ceiling. Since E5a that list is a list of STOREYS.
    // The OPENINGS travel with it (addendum "Treppen v2"): where a flight
    // cuts a stairwell into this floor, the walk rule must not answer inside
    // the ring the mesh above has just been built without.
    tile.walkPlates.push({ top: plate.top_y, outline: plate.outline,
                           holes: plate.holes });
    // Shadow flags are view state and stay here: upper storeys cast, every
    // plate receives.
    mesh.receiveShadow = true;
    mesh.castShadow = plate.level > 0 && plate.thickness > 0;
    parentFor(plate.room_id).add(mesh);
    builtPlates.push({ mesh, plate });
    if (!plate.room_id) {
      // The storey's outline plate — the basis of the storey switch
      tile.levelSlabs.set(plate.level, mesh);
      continue;
    }
    roomPlateTop.set(plate.room_id, plate.top_y);
  }

  // ── THE FLOORS OF THE ROOMS, as data (§ A19 no. 3, E5b) ─────────────────
  // One entry per room the payload gives a hull, and it is the ONLY frame the
  // room's centre, its stands, its label rectangle and its NPC huddle come out
  // of — the 6 x 6 raycast raster that used to find them is deleted.
  //
  // TWO SOURCES, one per kind of storey, and neither is a fallback for the
  // other: storey 0 comes from `floor_plan`, which is what E5a put in the
  // place of its plates; a DECLARED storey comes from its room block's own
  // `outline`, which is the polygon its plate is drawn from.
  //
  // A DECLARATION is a payload field and there are three of them:
  //  - a storey plate (`roomPlateTop`) — an upper floor or a basement;
  //  - an OVERLAY zone (§ B, `room.overlay.y`) — a zone that lies ON an area
  //    model's surface and never had a plate to read a height off;
  //  - a diorama's `walk_y_world`, which arrives with the models further down
  //    and is written into these same entries there (it outranks both).
  // Where none of the three speaks, the floor is the terrain.
  //
  // AND NO ROOM PAINTS WATER (W1 § 6). An entry may carry `map_water`, the
  // derived reference "this room's hull lies in that painted water area". It is
  // read for nothing here on purpose: the room keeps its semantics (its centre,
  // its spots, its huddle, all out of `polygon_world` below) and the MAP draws
  // the ground and the mirror (`scene/ground.ts`). Storey 0 has drawn no floor
  // surface of its own since E5a, so there is no surface to suppress — and the
  // room's old water fields, which this loop never read either, are gone.
  const overlayOf = new Map(scene.rooms.map((r) => [r.room_id, r.overlay]));
  for (const floor of scene.floor_plan) {
    const id = floor.room_id;
    if (!id || floor.polygon_world.length < 3) continue;
    const declared = overlayOf.get(id)?.y;
    const entry: RoomFloor = { hull: floor.polygon_world };
    if (declared !== undefined) entry.declared = declared;
    tile.roomFloors.set(id, entry);
  }
  for (const room of scene.rooms) {
    const id = room.room_id;
    if (!id || room.level === 0 || (room.outline?.length ?? 0) < 3) continue;
    const declared = roomPlateTop.get(id) ?? room.overlay?.y;
    const entry: RoomFloor = { hull: room.outline };
    if (declared !== undefined) entry.declared = declared;
    tile.roomFloors.set(id, entry);
  }

  // ── Walls ───────────────────────────────────────────────────────────────
  // Already split around every opening; the PANE in a hole is its own entry —
  // a window's glass band, a door's leaf. `outward_normal` comes with it and
  // feeds the culling.
  for (const wall of scene.walls) {
    const len = wallLength(wall);
    if (len < 1e-4) continue;
    const { mat: wallMat, tileM } = wallMaterial(wall, style);
    const mesh = buildWall(THREE, wall, wallMat, tileM);
    // A leaf whose hole a DOOR PROP fills is not drawn INSIDE (v5) — the prop
    // in `models[]` IS the door there, and both of them in one hole is one
    // door too many. It is still BUILT and still hung in, invisible, for two
    // reasons: the FAR SHELL copies from `builtWalls` below, and from outside
    // a place without a server model has to show its doors — which is exactly
    // what the leaf was added for, while a model is deliberately not part of
    // that shell; and a piece the § B5a verify measures has to hang in the
    // graph, or it would be measured without the tile's own transform.
    // The wall entry itself stays in the payload on purpose as well: the
    // Blender exterior render builds its facade out of `walls`.
    if (wall.door_prop) mesh.visible = false;
    parentFor(wall.room_id).add(mesh);
    builtWalls.push({ mesh, wall });
    // A PANE never joins the facade culling — glass since it existed, the
    // door LEAF for the same reason (2026-08-25): the culling list is what a
    // FACADE is made of, and a pane fills a hole instead of enclosing a room.
    // Its own normal must not decide what the camera may see, and it keeps
    // the storey filter off itself too (`applyWallCulling`).
    if (!wall.glass && !wall.leaf) {
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

  // ── Extras (elevator, stairs) ───────────────────────────────────────────
  // Typed boxes, centre + size, straight from the payload — one entry per
  // part. The ELEVATOR's pads double as the stops of its level routing (one
  // per storey); a staircase is read from `scene.stairs` below, not measured
  // back out of its boxes.
  let elevatorXZ: THREE.Vector2 | null = null;
  for (const extra of scene.extras) {
    g.add(buildExtra(THREE, extra, extraMaterial(extra, style)));
    // Only the ELEVATOR anchors the storey switch (finding 2026-08-25): the
    // first extra of a scene with stairs but no lift is a step, and the widget
    // would hang on it.
    if (extra.kind.startsWith('elevator_')) {
      elevatorXZ = elevatorXZ ?? new THREE.Vector2(extra.center[0], extra.center[2]);
    }
    if (extra.kind !== 'elevator_pad' || extra.level === undefined) continue;
    // THE TOP FACE OF THE PAD, and nothing added to it (addendum "Treppen
    // v2"): since the pads clear the floor by `PROP_CLEARANCE` on the server,
    // that face IS the height one stands at. The client's own extra
    // centimetre was the second half of a clearance that now exists once, and
    // it left a figure hovering two centimetres over every landing.
    const stopY = extra.center[1] + extra.size[1] / 2;
    tile.elevatorStops = tile.elevatorStops ?? new Map();
    tile.elevatorStops.set(extra.level, tileToWorld(tile,
      extra.center[0], extra.center[2], stopY));
  }
  // ── Staircases, from the payload's own block (§ B1 `stairs`) ────────────
  // The flight AS DATA: the two landings finished (the server states where one
  // stands, this only turns the point into the world frame), plus the run it
  // covers — the axis a guided climb follows and the floor it eats. Nothing
  // here derives a staircase from the `stair_step`/`stair_pad` boxes any more,
  // and no pair can be half missing: a block always carries both ends.
  const stairs: StairWorldLink[] = scene.stairs.map((s) => {
    const foot = tileToWorld(tile, s.foot[0], s.foot[2], s.foot[1]);
    const head = tileToWorld(tile, s.head[0], s.head[2], s.head[1]);
    const at = tileToWorld(tile, s.at[0], s.at[1]);
    // The climb direction in WORLD xz, read off the payload's own points
    // instead of turning `dir_deg` through the tile yaw: `head` lies on the
    // flight's axis past its end, so head − at IS that direction, and the
    // server's degree table stays where it belongs.
    const dir = new THREE.Vector2(head.x - at.x, head.z - at.z).normalize();
    return {
      foot: { level: s.from_level, pos: foot },
      head: { level: s.to_level, pos: head },
      at: new THREE.Vector2(at.x, at.z),
      dir,
      runM: s.run_m,
      widthM: s.width_m,
      steps: s.steps,
      footprint: s.footprint.map(([x, z]) => {
        const p = tileToWorld(tile, x, z);
        return [p.x, p.z] as [number, number];
      }),
    };
  });
  if (stairs.length) tile.stairs = stairs;

  // ── Doors & places: finished in world coordinates ───────────────────────
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
  // PLACES (plan-posen-plaetze.md § 4): one entry per marker ID, its slot
  // points finished in world metres. Nothing here matches a clip kind — who
  // sits on which slot is the server's word in the worldmap row, and
  // `main.ts` only looks the seat up by id.
  for (const marker of scene.markers) {
    const id = marker.room_id;
    if (!id || !marker.id) continue;
    let byId = tile.roomMarkers.get(id);
    if (!byId) {
      byId = new Map();
      tile.roomMarkers.set(id, byId);
      const name = nameOf.get(id);
      if (name) tile.roomMarkers.set(name, byId);
    }
    // Prop markers are FINISHED as composed (fixed: the floor sampling leaves
    // their height alone). Room markers stay additive to the SAMPLED seat
    // height per § A4 — their offset_y is inside the delivered y_world over
    // the storey floor and is derived back for that.
    const fixed = marker.source === 'prop';
    const level = roomLevel.get(id) ?? 0;
    const floorY = floorYof.get(level) ?? 0;
    const offsetY = fixed ? 0 : marker.y_world - floorY;
    // THE STOREY-0 TERRAIN LIFT of this marker (§ A16.9). It matters for the
    // `fixed` ones: a prop marker is composed from its prop's bounding box and
    // stays exactly as composed, so if the prop rises onto its shore and the
    // seat mark does not, the sitter is left in the air where the chair used
    // to be. A ROOM marker is re-derived from the room's own floor a few lines
    // further down (`deriveRoomSpots`), which already samples the terrain per
    // point — there this term is simply overwritten, never counted twice.
    //
    // AND IT IS SAMPLED AT THE PROP'S ANCHOR, not at the marker's own point
    // (user finding 2026-08-28, the sitter ~40 cm too low on the "Stone
    // bench"): `reliftPlacement` puts the MESH on the ground under
    // `spec.anchor`, so a seat lifted anywhere else differs from its bench by
    // the relief between the two points. `markerLiftPoint` is that choice,
    // pure and hand-derived (`client3d/scripts/smoke_place_lift.mjs`).
    const liftPoint = markerLiftPoint(
      { x: marker.at_world[0], z: marker.at_world[1] },
      marker.anchor ? { x: marker.anchor[0], z: marker.anchor[1] } : null);
    const at = tileToWorld(tile, liftPoint.x, liftPoint.z, 0);
    const markerLift = storeyGroundLift(level, at.x, at.z, tile.center.y,
                                        worldGroundSampler());
    // y_world is the SURFACE; how deep the root sits below it is the server's
    // word (root_offset, composed from the place type's `root_drop`). The
    // client's former own seat drop applied to room markers only — prop
    // markers got none, and the authors folded it into the marker by hand.
    const drop = marker.root_offset ?? 0;
    byId.set(marker.id, {
      roomId: id,
      group: marker.group,
      // Every slot the server composed, turned into the world like the
      // anchor: the payload is tile-local and the footprint may stand rotated.
      slots: marker.slots.map(([x, z]) =>
        tileToWorld(tile, x, z, marker.y_world - drop + markerLift)),
      rotation: marker.facing,
      tilt: marker.tilt,
      roll: marker.roll,
      offsetY,
      drop,
      fixed,
      // …and whether the furniture under this place is part of the room's
      // DIORAMA (plan-diorama-hover.md). The server says so per marker; the
      // client only carries it, because it decides the place's target: the
      // diorama mesh instead of a ring.
      diorama: marker.diorama === true,
      // …and the two numbers the RE-LIFT needs when the height field moves
      // (`reliftScene`): which storey this marker belongs to, and how much of
      // the terrain is already in the slot heights — and WHERE it was
      // sampled, so the re-lift asks the field at the very same point.
      level,
      lift: markerLift,
      liftAt: { x: at.x, z: at.z },
      anchor: marker.anchor,
    });
  }

  // ── Room labels + storey switch (view state, stays in the client) ───────
  // Room labels only in BUILDINGS (`areaLoc` from above): on an area
  // location the rooms are zones like "Road"/"Forest", and their generic
  // names over the scene are noise (user directive 2026-08-02).
  for (const [id, rg] of roomGroup) {
    if (areaLoc) break;  // zones instead of rooms — show no names
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
  // `interiorLift` stood here until stage 3: the zoom bonus of the removed
  // distance-based unfolding — the detail view now opens on an event.
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
    // THE ONE PLACE this tile's terrain enters a placement (§ A16.9), and it
    // is the SAME call the re-lift makes: the object is built on its composed
    // `bottom_y`, its record starts at `lift: 0`, and `reliftPlacement` moves
    // it onto the ground under its own anchor. Read ONCE per spec so mesh,
    // placeholder, the room's declared floor and the verify row can never
    // disagree about it.
    let lift = 0;
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
      const rec: PlacedSceneModel = { spec, url, object: ph, parent,
                                      placeholder: true, lift: 0 };
      placements.push(rec);
      lift = reliftPlacement(tile, rec);
      // A stand-in for a CUT prop is cut too (§ B2 addendum 2026-08-23) —
      // otherwise the missing half of the table reappears the moment its mesh
      // fails to load. The plane is world space and needs the mounted object.
      applyDepthCut(THREE, ph, spec.cut_plane);
      verify.placed += 1;
      // Auch der Platzhalter wird gegen seine Spec geprüft: er steht an
      // derselben Stelle und hat dieselbe Zielgröße wie das fehlende Mesh
      // (dims × k). Ohne diese Prüfung blieb ein Loch in der Abdeckung —
      // an 526cf40b waren das 2 Props / 8 Prüfungen, und die Verify-Summe
      // lag ohne Grund unter dem Soll.
      verify.placement(ph, spec, tile, lift);
      return;
    }
    if (stale()) return;
    if (!source) {
      // Mesh nach allen Versuchen nicht ladbar UND kein Platzhalter geliefert:
      // hier fehlt ein Objekt in der Szene. Das wird GEZÄHLT (A3) — früher
      // verschwand die Platzierung stillschweigend und die Verify-Tabelle
      // meldete trotzdem „keine Abweichung". The ledger entry is still
      // written: a later tier swap may try the mesh again.
      placements.push({ spec, url, object: null,
                        parent: parentFor(spec.room_id), lift: 0 });
      verify.skip(spec);
      return;
    }
    verify.placed += 1;
    // clone:false — the client hands the object over for good (the admin
    // preview places the same cached object several times and clones it).
    // clip:false — we clip below ourselves, in WORLD coordinates around the
    // tile centre; the spec carries the polygon relative to it.
    const placed = placeModelSpec(THREE, source, spec,
                                  { clone: false, clip: false });
    if (spec.surface && spec.measure !== 'fit') {
      // The one place a loader divergence Blender↔three would show: the
      // spec's scale (max_m over the BAKED snapped extent) against the scale
      // place() derived from the mesh it actually loaded. A `fit` spec is out
      // — it is fitted to an opening instead of scaled to `max_m`, so neither
      // side of this comparison is the factor it applied.
      verify.check(`${spec.role}:${spec.id}`, 'surface_scale', placed.scale.x,
                   surfaceScale(spec.surface, spec));
      // …AND THE BOX ITSELF (fix wave B). `surface_scale` compares ONE number
      // derived from `extent_snapped`, so it stays green whenever the two
      // sides agree about the largest side — a mesh whose Blender box and
      // three box differ in the OTHER axes, or in where its underside sits,
      // passes it while every lattice reading is off by that difference. This
      // row measures the exact box `place()` seated the model on against the
      // one the bake wrote, in model units, and reports the worst of the four
      // numbers (three sizes + the bottom edge).
      const box = fixGroupBox(placed);
      if (box) {
        const size = box.getSize(new THREE.Vector3());
        const [bx0, by0, bz0] = spec.surface.box_min;
        const [bx1, by1, bz1] = spec.surface.box_max;
        const dev = Math.max(Math.abs(size.x - (bx1 - bx0)),
                             Math.abs(size.y - (by1 - by0)),
                             Math.abs(size.z - (bz1 - bz0)),
                             Math.abs(box.min.y - by0));
        verify.check(`${spec.role}:${spec.id}`, 'surface_box', dev, 0);
      }
    }
    if (spec.role === 'building') {
      applyBuildingModel(tile, placed, spec);
      placements.push({ spec, url, object: placed, lift: 0 });
    } else {
      const parent = parentFor(spec.room_id);
      parent.add(placed);
      const rec: PlacedSceneModel = { spec, url, object: placed, parent, lift: 0 };
      placements.push(rec);
      // THE TEXTURE SLOTS of this placement (§ B2 v5) — FIRST of the material
      // passes: the cut, the clip and the ghost below all clone what they
      // traverse, so a picture written here rides into their clones instead of
      // having to be written again after each of them.
      fillSlots(rec, placed);
      // A DOOR PROP joins the swing list (v5). `placed`'s origin IS the hinge
      // (`measure: "fit"`, § B2), so the entry needs nothing but the group and
      // the threshold it belongs to — no geometry is computed here.
      registerDoorProp(doorProps, scene, spec, placed);
      // The DEPTH CUT of a placed prop (§ B2 addendum 2026-08-23): the server
      // states the plane, this hangs it on the material clones. It runs after
      // `parent.add`, because `Material.clippingPlanes` is world space and the
      // payload's metres only become world metres through the tile group.
      applyDepthCut(THREE, placed, spec.cut_plane);
      // The storey-0 terrain lift (§ A16.9). It rides on the placed group's y
      // AFTER `place()` has seated the mesh on `bottom_y`, so every step of
      // § B2 keeps working on the composed numbers and only the finished
      // object moves onto the ground under its own anchor.
      lift = reliftPlacement(tile, rec);
      if (spec.role === 'room' && spec.walk_y_world !== undefined && spec.room_id) {
        // A diorama's declared floor moves WITH its mesh — otherwise the
        // figures of that room would keep standing on the height the payload
        // composed while the hut they belong to sits on the hillside (the
        // Mondhütte finding, one relief further on).
        walkY.set(spec.room_id, spec.walk_y_world + lift);
      }
      const clipped = applyModelClip(tile, placed, spec);
      if (clipped) verify.clipped(spec, clipped);
    }
    verify.placement(placed, spec, tile, lift);
  }));
  if (stale()) return null;

  // THE UNDERWATER GHOSTS of this mount, once the whole ledger stands (user
  // decision 2026-08-25). One pass instead of a call inside each of the three
  // placement branches above: the gate needs nothing but the record, and a
  // placeholder box standing in a lake has to be redrawn exactly like the mesh
  // it stands in for.
  for (const rec of placements) refreshPlacementGhost(tile, rec);

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

  // ── THE DECLARED FLOORS of this scene (§ B6 no. 7) ──────────────────────
  // Until here `walk_y_world` was a pure sampling hint and ended inside this
  // block; the walking figure (`tileWalkY`) NEVER saw it. That was exactly the
  // finding at the moon hut: the slider moved the NPC spots and the room
  // centre, the figure kept standing on the tile ground. The declaration
  // belongs on the tile, not in this function.
  //
  // The hull is the ROOM's from the payload (§ B1), not the plate's: a
  // declaration holds for the room even when it draws no plate at all.
  tile.declaredFloors = [];
  for (const room of scene.rooms) {
    const top = walkY.get(room.room_id);
    if (top === undefined) continue;
    tile.declaredFloors.push({ roomId: room.room_id, top, outline: room.outline });
  }

  // ── The stands of every room, from DATA (§ A19 no. 3, E5b) ──────────────
  // A diorama's `walk_y_world` is the strongest declaration there is (§ B6
  // no. 7) and outranks the storey plate / overlay height already written into
  // the entry; it is folded in HERE because the models arrive asynchronously.
  for (const [id, floor] of tile.roomFloors) {
    const declared = walkY.get(id);
    if (declared !== undefined) floor.declared = declared;
    deriveRoomSpots(tile, id, roomProps(placements, id));
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
 * split around every opening (§ B1). The DOOR LEAVES ride along (2026-08-25):
 * they are opaque wall-like pieces, and a far view that shows the doors is
 * exactly what the leaf was added for. No models, no props, no markers, no
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
    // THE SHELL SHOWS EVERYTHING IT TAKES. `Mesh.clone()` copies `visible`,
    // and one source is deliberately invisible inside: the leaf of a door
    // whose hole a prop fills (v5). The prop is not part of a shell, so
    // without this line that place would read as an empty hole from outside —
    // the very thing the leaf exists to prevent.
    copy.visible = true;
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
 *
 * `onSwapped` is called ONCE per tier swap with the records that really
 * changed their mesh — a PARAMETER and not a module-level hook, so this
 * routine keeps knowing nothing about its callers. It exists because
 * everything a VIEW holds on the old object dies with the swap: the seat
 * targets point at a mesh that has left the graph, and the shader patches a
 * view installed on its materials are gone with the clones
 * (`scene/spotHighlight.ts`).
 *
 * ONCE, at the very END, and both halves of that matter: a room of twelve
 * props would otherwise call the view back twelve times for one swap, and the
 * seats of a swapped diorama are re-derived onto the new mesh's floor in the
 * block below this loop — a callback fired earlier would rebuild the targets
 * from slot heights that are about to move. A remount (`placedModels`
 * replaced) returns without the call: that path rebuilds everything anyway.
 */
export async function setSceneModelTier(tile: Tile, group: 'building' | 'interior',
                                        tier: ModelTier,
                                        onSwapped?: (recs: PlacedSceneModel[]) => void
                                       ): Promise<void> {
  const swapped: PlacedSceneModel[] = [];
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
      // Same storey-0 terrain lift the mount applies (§ A16.9) — through the
      // SAME function, from the same `lift: 0` baseline: the fresh mesh sits on
      // its composed `bottom_y`, so a tier swap that happens after a height
      // tile arrived lands on the height that is now known instead of the one
      // that was.
      // The ghost belongs to the MESH that is going away, so it goes with it —
      // and the new one is gated below, on the same seat the re-lift just gave
      // this record.
      dropPlacementGhost(rec);
      rec.object = placed;
      rec.lift = 0;
      // The texture slots belong to the PLACEMENT, not to the mesh that fills
      // it — same as the clip and the cut below, and for the same reason. The
      // old clones (and their textures) go with the old group further down.
      const oldSlotMats = rec.slotMats;
      fillSlots(rec, placed);
      reliftPlacement(tile, rec);
      applyModelClip(tile, placed, rec.spec);
      rec.parent?.add(placed);
      // …and the cut survives the tier swap, for the same reason the clip
      // does: it belongs to the PLACEMENT, not to the mesh that fills it.
      applyDepthCut(THREE, placed, rec.spec.cut_plane);
      // …and so does the underwater ghost. LAST, after the clip and the cut,
      // exactly as in the mount: those two rewrite the materials of everything
      // they traverse, and the ghost's own material is not theirs to touch.
      refreshPlacementGhost(tile, rec);
      // The swing list of a DOOR PROP follows its mesh (v5): the entry points
      // at the GROUP, and the tier swap has just built a new one. The angle
      // survives the swap — it says where the door stands, which is not a
      // property of the mesh that fills it.
      if (old) retargetDoorProp(tile, old, placed);
      disposeSlotMaterials(oldSlotMats);
      if (old) {
        old.parent?.remove(old);
        disposeClipMaterials(old);
        disposeCutMaterials(old);
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
    swapped.push(rec);
  }));
  if (tile.placedModels !== placements) return;
  // A swapped mesh changes the furniture boxes — re-derive the
  // affected rooms exactly the way the mount does, so figures keep standing
  // on what is actually visible.
  if (group === 'interior') {
    const roomsChanged = new Set<string>();
    for (const rec of placements) {
      if (rec.spec.role === 'room' && rec.spec.room_id) roomsChanged.add(rec.spec.room_id);
    }
    for (const id of roomsChanged) {
      if (!tile.roomGroups.has(id)) continue;
      const declaring = placements.find((r) => r.spec.role === 'room'
        && r.spec.room_id === id
        && r.spec.walk_y_world !== undefined);
      // The declared floor carries the SAME storey-0 terrain lift its mesh
      // does (§ A16.9) — read OFF THE RECORD, which is the lift that mesh is
      // actually standing on after the swap re-lifted it. Deriving it again
      // here would be a second reading of a field that moves.
      const declared = declaring
        ? (declaring.spec.walk_y_world as number) + declaring.lift
        : undefined;
      // …and without a declaring diorama the ROOM PLATE is the floor, exactly
      // as in the mount above. The slot holder was placed on `plate.top_y` in
      // the same loop that built the plate, so this IS that number.
      //
      // `tile.declaredFloors` needs NO update here, and that is a property of
      // the swap and not an omission: a tier exchanges the URL inside the SAME
      // spec object (`rec.spec` is untouched above), and `walk_y` is a dial of
      // the SUBJECT, read off the default tier's sidecar for every tier
      // (`location_model3d.get_client_meta`). `declared` is therefore the same
      // number the mount already wrote.
      //
      // WHAT DOES CHANGE IS THE FURNITURE: a swapped mesh has its own bounding
      // box, and the sit/lie targets are read off it (`deriveRoomSpots`). The
      // FLOOR of the room is data and is unaffected by the swap — which is why
      // the entry is left exactly as the mount wrote it.
      if (declared !== undefined) {
        const floor = tile.roomFloors.get(id);
        if (floor) floor.declared = declared;
      }
      deriveRoomSpots(tile, id, roomProps(placements, id));
    }
  }
  // LAST, and once: the seats above have found the swapped mesh's floor, so
  // whatever the caller derives from them now sees their final heights.
  if (swapped.length) onSwapped?.(swapped);
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
  // An area model used to have to hide the tile's own plate here — a client
  // invention that cut the model off at its own 4 cm (Mondscheinsee: lake bed
  // and beach, model y −0.80 … +2.69, all of it behind the plate). There is no
  // plate to hide since "Ein Boden" E3.
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
  // Found by NAME, not through tile.interior — a building-only scene (no
  // interior content) hangs in the graph as a group without being `interior`.
  const prev = tile.group.children.find((c) => c.name === SCENE_GROUP)
    ?? tile.interior;
  if (prev && prev.name === SCENE_GROUP) tile.group.remove(prev);
  // The far-view shell is a copy of THIS scene's primitives, so it dies with
  // it — its geometries are the ones just taken out of the graph.
  dropFarShell(tile);
  // Free the previous scene's cutout material clones (the disposeClipMaterials
  // pattern — their textures are shared with the cache).
  tile.cutouts?.dispose();
  // The underwater ghosts of this scene die with it: their materials are their
  // own, and their registration is what isolation toggle 22 walks — a ghost
  // left registered would keep a whole unmounted scene alive for the switch's
  // sake.
  // …and so do the TEXTURE SLOTS (§ B2 v5): each placement owns its material
  // clones AND the picture loaded into them — nothing else in the graph
  // references either, so leaving them would leak one texture per filled slot
  // per mount.
  for (const rec of tile.placedModels ?? []) {
    dropPlacementGhost(rec);
    disposeSlotMaterials(rec.slotMats);
    rec.slotMats = undefined;
  }
  // Placement ledger of the old mount: gone with the scene — an in-flight
  // tier swap compares against this list and drops its answer.
  tile.placedModels = undefined;
  // The swing list points at groups that just left the graph — it dies with
  // them, and the next mount builds its own (v5). Nothing to dispose: the
  // groups are the placements above, and the angle was view state.
  tile.doorProps = undefined;
  tile.cutouts = undefined;
  tile.modelIsGround = false;
  tile.modelIsShellArea = false;
  tile.modelWalkY = undefined;
  // The floors of this scene leave with it: until the next mount the tile has
  // the world terrain under it, exactly as a place without a recipe.
  //
  // NOTHING TO RESTORE HERE ANY MORE ("Ein Boden" E3): the unmount used to put
  // the tile's own plate back — flat geometry, y 0.04, its own depth bias,
  // visible again — because the mount had draped, lowered, biased and hidden
  // it. No plate, no restore.
  tile.walkPlates = [];
  tile.declaredFloors = [];
  tile.surfaces = [];
  for (const [, rg] of tile.roomGroups) rg.parent?.remove(rg);
  for (const label of tile.interiorLabels) label.element?.remove();
  tile.interior = null;
  tile.interiorLabels = [];
  tile.roomGroups.clear();
  tile.roomCenters.clear();
  tile.roomDoors.clear();
  tile.roomFloors.clear();
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
  tile.stairs = undefined;
  // The old scene's switch is gone with its DOM — its refresh function would
  // otherwise write to a widget that is no longer there.
  tile.levelSwitch = undefined;
}
