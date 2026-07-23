import * as THREE from 'three';
import { getRoomRecipe, type ApiRoomRecipe } from '../api';
import { buildRoomShell } from './roomShell';
import { buildPropPlaceholder, loadPropModel, propInfo } from './propAssets';
import { placeProp } from './propPlace';
import {
  preloadSurfaceTexture, roomFigureScale, sampleRoomWalkables, storeyHeight,
  surfaceFor, type Tile,
} from './tiles';

// Eingerichtete Räume aus Einzel-Props (backend-note-room-recipe.md):
// Rezepte holen/pollen und den Szenengraphen (Hülle + Props + Marker) in die
// Raum-Gruppe bauen. Die Koexistenz-Weiche liegt in main.ts: Rezept MIT
// placements -> dieser Pfad, sonst Diorama (applyRoomModel) wie bisher.

const LW = 8;   // Kantenlänge des 8x8-Referenzquadrats (wie buildInterior)

/** Rezept pro Raum mit signature-Polling: request() holt einmalig (404 =
 *  kein Layout -> null), sweep() fragt bekannte Räume erneut und meldet
 *  Änderungen über onRecipe — signature bewegt sich bei Layout- UND
 *  Prop-Sidecar-Änderungen, GLBs selbst laufen über den HTTP-Cache (ETag). */
export class RecipeLibrary {
  private cache = new Map<string, ApiRoomRecipe | null>();
  private pending = new Set<string>();
  onRecipe?: (roomId: string, recipe: ApiRoomRecipe | null) => void;

  get(roomId: string): ApiRoomRecipe | null | undefined {
    return this.cache.get(roomId);
  }

  request(roomId: string): void {
    if (this.cache.has(roomId) || this.pending.has(roomId)) return;
    this.pending.add(roomId);
    getRoomRecipe(roomId)
      .then((r) => {
        this.cache.set(roomId, r);
        if (r?.placements?.length) console.info(`[recipe] ${roomId}: Rezept mit ${r.placements.length} Props`);
        this.onRecipe?.(roomId, r);
      })
      // Netzwerk/5xx: nicht als "kein Rezept" cachen, nächster Zyklus fragt neu
      .catch((e) => console.warn(`[recipe] ${roomId}: (noch) nicht ladbar — neuer Versuch folgt`, e))
      .finally(() => this.pending.delete(roomId));
  }

  async sweep(): Promise<void> {
    for (const [roomId, prev] of [...this.cache]) {
      try {
        const fresh = await getRoomRecipe(roomId);
        const changed = (prev?.signature ?? null) !== (fresh?.signature ?? null);
        this.cache.set(roomId, fresh);
        if (changed) this.onRecipe?.(roomId, fresh);
      } catch { /* Server kurz weg -> nächster Sweep */ }
    }
  }
}

const groupName = (roomId: string) => `recipe:${roomId}`;

/** Rezept-Aufbau eines Raums entfernen (Wechsel zurück zum Diorama oder
 *  Remount): Szene, Culling-Einträge und fertig komponierte Marker. */
export function unmountRoomRecipe(tile: Tile, roomId: string): void {
  const rg = tile.roomGroups.get(roomId);
  const prev = rg?.getObjectByName(groupName(roomId));
  if (!rg || !prev) return;
  const walls = new Set<THREE.Object3D>((prev.userData.cullWalls ?? []) as THREE.Mesh[]);
  tile.outlineWalls = tile.outlineWalls.filter((w) => !walls.has(w.mesh));
  rg.remove(prev);
  const slot = tile.roomSlots.get(roomId);
  if (slot && !slot.holder.children.length) slot.plate.visible = true;
  const markers = tile.roomMarkers.get(roomId);
  if (markers) {
    for (const [kind, entries] of markers) {
      const rest = entries.filter((e) => !e.fixed);
      if (rest.length) markers.set(kind, rest);
      else markers.delete(kind);
    }
  }
}

/** Szenengraph eines eingerichteten Raums bauen: Hülle aus dem outline-
 *  Polygon, Props nach der Real-Size-Regel, fertig komponierte Objekt-
 *  Marker, danach Begehbarkeit abtasten. Ersetzt einen früheren Aufbau
 *  (Remount bei signature-Wechsel). */
export async function mountRoomRecipe(tile: Tile, roomId: string, recipe: ApiRoomRecipe): Promise<void> {
  const rg = tile.roomGroups.get(roomId);
  const slot = tile.roomSlots.get(roomId);
  if (!rg || !slot) {
    console.warn(`[recipe] ${roomId}: kein Raum-Slot auf der Kachel — Mount übersprungen`);
    return;
  }

  const k = roomFigureScale(tile.loc);
  const storey = storeyHeight(tile.loc);
  const level = recipe.level ?? 0;
  const floorY = level * storey;
  // Props/Marker stehen AUF der Bodenplatte der Hülle (Oberkante +0.10)
  const floorTop = floorY + 0.11;

  // Surface-Bilder fertig laden, BEVOR die Hülle sie klont (Klone eines noch
  // ladenden Bildes blieben leer); "floor" ist der globale Boden-Fallback
  await Promise.all([
    preloadSurfaceTexture(recipe.surfaces?.floor),
    preloadSurfaceTexture('floor'),
    preloadSurfaceTexture(recipe.surfaces?.wall),
  ]);

  unmountRoomRecipe(tile, roomId);
  // Datenlage entscheidet: ein evtl. schon montiertes Diorama weicht dem
  // Rezept (zurück geht es über die Weiche in main.ts, das Modell bleibt
  // im Cache der roomModelLibrary)
  slot.holder.clear();
  const shell = buildRoomShell(recipe, { k, storey, floorY, surface: surfaceFor });
  const g = shell.group;
  g.name = groupName(roomId);
  g.userData.cullWalls = shell.walls.map((w) => w.mesh);
  rg.add(g);
  slot.plate.visible = false;   // Platte nur als Platzhalter ohne Aufbau

  // Hüllen-Wände ins Blickrichtungs-Culling (wie die Grundriss-Wände)
  for (const w of shell.walls) {
    tile.outlineWalls.push({
      mesh: w.mesh, level,
      mid: new THREE.Vector2(tile.center.x + w.mid.x, tile.center.z + w.mid.y),
      normal: w.normal,
    });
  }

  // Objekt-Marker: fertig komponiert, NICHT selbst rechnen — Welt =
  // Platzierungspunkt + offset_m x k, Höhe = Etagenboden + height_m x k,
  // facing im Welt-Kompass (0=S/90=E/...), wie Raum-Marker. Synchron VOR dem
  // Prop-Laden, damit ein veralteter Mount nach einem Remount keine alten
  // Marker mehr nachträgt.
  const placements = recipe.placements ?? [];
  const propMarkers = recipe.prop_markers ?? [];
  if (propMarkers.length) {
    let byKind = tile.roomMarkers.get(roomId);
    if (!byKind) {
      byKind = new Map();
      tile.roomMarkers.set(roomId, byKind);
      const room = tile.loc.rooms.find((r) => r.id === roomId);
      if (room) tile.roomMarkers.set(room.name, byKind);
    }
    for (const m of propMarkers) {
      const p = placements[m.placement];
      if (!p || !m.animation) continue;
      const world = tile.center.clone().add(new THREE.Vector3(
        p.at[0] * LW - LW / 2 + m.offset_m[0] * k,
        floorTop + m.height_m * k,
        p.at[1] * LW - LW / 2 + m.offset_m[1] * k,
      ));
      const entry = { p: world, rotation: m.facing, offsetY: 0, fixed: true };
      (byKind.get(m.animation) ?? byKind.set(m.animation, []).get(m.animation)!).push(entry);
    }
  }

  // Props platzieren — Real-Size-Regel (propPlace.ts, verifiziert gegen 2d).
  // missing / has_model:false -> Platzhalter in dims-Größe, Platzierung nie
  // verwerfen; das GLB kommt über /assets/props/{id}/model (ETag).
  await Promise.all(placements.map(async (p) => {
    const lx = p.at[0] * LW - LW / 2;
    const lz = p.at[1] * LW - LW / 2;
    const info = propInfo(p.prop_id);
    const dims = p.dims
      ?? (info ? { width_m: info.width_m, depth_m: info.depth_m, height_m: info.height_m } : undefined);
    if (!dims) return;
    let obj: THREE.Object3D | null = null;
    if (!p.missing && p.has_model !== false) {
      const raw = await loadPropModel(p.prop_id);
      if (raw) {
        obj = placeProp(raw.clone(true), {
          fix: info?.rotation, dims, k, yaw: p.yaw ?? 0,
          offsetY: p.offset_y ?? 0, at: { x: lx, z: lz }, floorY: floorTop,
        });
      }
    }
    if (!obj) {
      obj = buildPropPlaceholder(dims, k);
      obj.position.set(lx, floorTop + (p.offset_y ?? 0) * k, lz);
      obj.rotation.y = -THREE.MathUtils.degToRad(p.yaw ?? 0);
    }
    g.add(obj);
  }));

  // Rezept könnte während der Ladezeit ersetzt worden sein (Remount/Tile-
  // Rebuild): dann hängt g nicht mehr in der Szene -> nichts abtasten
  if (g.parent !== rg || rg.getObjectByName(groupName(roomId)) !== g) {
    console.info(`[recipe] ${roomId}: Mount verworfen (Remount/Rebuild während des Ladens)`);
    return;
  }
  console.info(`[recipe] ${roomId}: montiert — ${placements.length} Props, ${shell.walls.length} Wandsegmente`);
  sampleRoomWalkables(tile, roomId, g);
}
