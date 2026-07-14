import * as THREE from 'three';
import * as api from './api';
import { Engine } from './scene/engine';
import { FigureLibrary } from './scene/figures';
import { NpcManager, type NpcState } from './scene/npcs';
import { applyNightGlow, applyTileFade, buildTile, gridToWorld, CELL, type Tile } from './scene/tiles';
import { grassTexture, seededRandom } from './scene/textures';
import { createHud, InfoPanel, showLogin } from './ui';
import type { MapCharacter, WorldLocation, WorldMap } from './types';

const WORLDMAP_POLL_MS = 3000;
const ROOMS_POLL_MS = 4000;
const INTERIOR_CAM_DIST = 26; // näher als das -> Räume auflösen

const app = document.getElementById('app')!;

async function boot() {
  const status = await api.authStatus().catch(() => ({ authenticated: false as const }));
  if (status.authenticated && 'user' in status && status.user) {
    startApp(status.user.username);
    return;
  }
  showLogin(async (u, p) => {
    const user = await api.login(u, p);
    startApp(user.username);
  });
}

async function startApp(username: string) {
  const engine = new Engine(app);
  (window as unknown as { __engine: Engine }).__engine = engine;   // Debug-Hook (Tageszeit testen)
  const figures = new FigureLibrary();
  const [allLocs, firstMap] = await Promise.all([
    api.getLocations(),
    api.getWorldMap(),
    figures.load(),
  ]);
  const npcs = new NpcManager(figures);
  engine.scene.add(npcs.group);
  // Server-Modelle trudeln asynchron ein -> betroffenen NPC neu aufbauen
  figures.onModelReady = (charName) => {
    npcs.rebuild(charName);
    if (lastMap) npcs.update(computeNpcStates(lastMap));
  };
  const panel = new InfoPanel();

  const hud = createHud({
    username,
    avatar: firstMap.avatar,
    onLogout: async () => {
      await api.logout();
      location.reload();
    },
  });
  npcs.setAvatar(firstMap.avatar);

  // Worldmap ist autoritativ für Grid/Passable/Template; /world/locations liefert
  // Räume, Beschreibung, entry_room. Templates (Vorlagen für Klone) nicht rendern.
  const detailById = new Map(allLocs.map((l) => [l.id, l]));
  const templateIds = new Set(
    firstMap.locations.map((l) => l.template_location_id).filter(Boolean) as string[]
  );
  const placeable: WorldLocation[] = firstMap.locations
    .filter((l) => l.grid_x != null && l.grid_y != null && !templateIds.has(l.id))
    .map((l) => {
      const detail = detailById.get(l.id) ?? detailById.get(l.template_location_id || '');
      return {
        ...detail,
        ...l,
        rooms: detail?.rooms ?? [],
        description: detail?.description ?? '',
        entry_room: detail?.entry_room,
      } as WorldLocation;
    });

  // Boden + Kacheln
  const xs = placeable.map((l) => l.grid_x!), ys = placeable.map((l) => l.grid_y!);
  const center = gridToWorld((Math.min(...xs) + Math.max(...xs)) / 2, (Math.min(...ys) + Math.max(...ys)) / 2);
  const groundTex = grassTexture();
  groundTex.repeat.set(60, 60);
  const ground = new THREE.Mesh(
    new THREE.PlaneGeometry(600, 600),
    new THREE.MeshStandardMaterial({ map: groundTex, roughness: 1 })
  );
  ground.rotation.x = -Math.PI / 2;
  ground.position.copy(center);
  ground.receiveShadow = true;
  engine.scene.add(ground);

  const tiles = new Map<string, Tile>();
  for (const loc of placeable) {
    const tile = buildTile(loc);
    tiles.set(loc.id, tile);
    engine.scene.add(tile.group);
  }
  engine.setPickables([...tiles.values()].map((t) => t.group));
  engine.target.copy(center);
  engine.dist = engine.targetDist = 70;

  // --- Hover & Klick -------------------------------------------------------
  let hovered: Tile | null = null;
  engine.onHover = (id) => {
    const tile = id ? tiles.get(id) ?? null : null;
    if (tile === hovered) return;
    if (hovered) hovered.highlightRing.visible = false;
    hovered = tile;
    if (hovered) hovered.highlightRing.visible = true;
    document.body.style.cursor = hovered ? 'pointer' : 'default';
  };
  engine.onPick = (id) => {
    if (!id) {
      panel.hide();
      return;
    }
    const tile = tiles.get(id);
    if (!tile) return;
    const chars = (lastMap?.characters ?? []).filter((c) => c.location_id === id);
    panel.show(tile.loc, chars, lastMap?.events_by_location?.[id] ?? [], roomOf);
  };
  panel.onZoomTo = (id) => {
    const tile = tiles.get(id);
    if (tile) engine.flyTo(tile.center.clone(), 15);
  };

  // --- Event-Pins ----------------------------------------------------------
  const pins = new Map<string, THREE.Sprite>();
  function makePinTexture(emoji: string): THREE.CanvasTexture {
    const c = document.createElement('canvas');
    c.width = c.height = 96;
    const ctx = c.getContext('2d')!;
    ctx.font = '72px serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(emoji, 48, 54);
    const t = new THREE.CanvasTexture(c);
    t.colorSpace = THREE.SRGBColorSpace;
    return t;
  }
  function updatePins(map: WorldMap) {
    const wanted = new Map<string, string>();
    for (const [locId, evs] of Object.entries(map.events_by_location ?? {})) {
      if (!evs.length || !tiles.has(locId)) continue;
      wanted.set(locId, evs.some((e) => e.category === 'danger') ? '🔥' : '❗');
    }
    for (const [locId, pin] of pins) {
      if (!wanted.has(locId)) {
        engine.scene.remove(pin);
        pins.delete(locId);
      }
    }
    for (const [locId, emoji] of wanted) {
      if (pins.has(locId)) continue;
      const tile = tiles.get(locId)!;
      const pin = new THREE.Sprite(new THREE.SpriteMaterial({ map: makePinTexture(emoji), depthTest: false }));
      pin.scale.setScalar(3);
      pin.position.copy(tile.center).setY(tile.height + 3.5);
      engine.scene.add(pin);
      pins.set(locId, pin);
    }
  }

  // --- Polling: Worldmap + Raumbelegung -------------------------------------
  let lastMap: WorldMap | null = firstMap;
  const roomOf = new Map<string, string>(); // Charaktername -> Raum (ID oder Name)

  // AV3D-8: room_id kommt direkt mit der Worldmap; dazu die Clip-Set-Kette
  function takeRoomsFrom(map: WorldMap) {
    for (const c of map.characters) {
      if (c.room_id) roomOf.set(c.name, c.room_id);
      figures.setCharacterSets(c.name, c.animation_sets);
    }
  }

  async function pollWorldMap() {
    try {
      lastMap = await api.getWorldMap();
      hud.setOnline(true);
      takeRoomsFrom(lastMap);
      updatePins(lastMap);
    } catch {
      hud.setOnline(false);
    }
  }
  takeRoomsFrom(firstMap);
  updatePins(firstMap);
  setInterval(pollWorldMap, WORLDMAP_POLL_MS);

  // Fenster leuchten nachts
  engine.onDayNight = (night) => {
    for (const tile of tiles.values()) applyNightGlow(tile, night);
  };

  // Tageszeit der Welt -> Beleuchtung (alle 60 s nachführen)
  async function pollGameHour() {
    const h = await api.getGameHour();
    if (h != null) engine.setGameHour(h);
  }
  void pollGameHour();
  setInterval(pollGameHour, 60_000);

  // Fallback für Backends ohne room_id im Worldmap-Payload (Prä-AV3D-8)
  async function pollRooms() {
    const zoomed = [...tiles.values()].filter((t) => t.fadeTarget === 1 && t.loc.rooms.length);
    for (const tile of zoomed) {
      const charsHere = (lastMap?.characters ?? []).filter((c) => c.location_id === tile.loc.id);
      if (charsHere.every((c) => c.room_id)) continue;
      try {
        const chars = await api.getCharactersAtLocation(tile.loc.id);
        for (const c of chars) {
          if (c.room) roomOf.set(c.name, c.room);
        }
      } catch { /* Raum-Zuordnung ist optional */ }
    }
  }
  setInterval(pollRooms, ROOMS_POLL_MS);

  // --- NPC-Sollpositionen ----------------------------------------------------
  function slotOffset(tile: Tile, index: number, count: number): THREE.Vector3 {
    if (tile.isBuilding) {
      // vor dem Gebäude aufreihen (Südseite)
      const x = (index - (count - 1) / 2) * 2.3;
      return new THREE.Vector3(x, 0, CELL * 0.36);
    }
    const angle = (index / Math.max(count, 1)) * Math.PI * 2;
    return new THREE.Vector3(Math.cos(angle) * 2.6, 0, Math.sin(angle) * 2.6);
  }

  // Raum-Mitbewohner im kleinen Kreis anordnen statt aufeinander zu stehen
  function roomSlot(index: number, count: number, name: string): THREE.Vector3 {
    if (count <= 1) return new THREE.Vector3(0, 0, 0.2);
    const rnd = seededRandom('jitter:' + name);
    const angle = (index / count) * Math.PI * 2 + rnd() * 0.5;
    return new THREE.Vector3(Math.cos(angle) * 1.0, 0, Math.sin(angle) * 0.8);
  }

  function computeNpcStates(map: WorldMap): NpcState[] {
    const byLoc = new Map<string, MapCharacter[]>();
    for (const c of map.characters) {
      if (!tiles.has(c.location_id)) continue;
      (byLoc.get(c.location_id) ?? byLoc.set(c.location_id, []).get(c.location_id)!).push(c);
    }
    const states: NpcState[] = [];
    for (const [locId, chars] of byLoc) {
      const tile = tiles.get(locId)!;
      chars.sort((a, b) => a.name.localeCompare(b.name));
      const roomMates = new Map<string, string[]>();
      for (const c of chars) {
        const room = roomOf.get(c.name);
        if (room) (roomMates.get(room) ?? roomMates.set(room, []).get(room)!).push(c.name);
      }
      chars.forEach((c, i) => {
        let pos: THREE.Vector3;
        const room = roomOf.get(c.name);
        const roomCenter = room ? tile.roomCenters.get(room) : undefined;
        if (tile.fade > 0.5 && roomCenter && room) {
          const mates = roomMates.get(room)!;
          pos = roomCenter.clone().add(roomSlot(mates.indexOf(c.name), mates.length, c.name));
        } else {
          pos = tile.center.clone().add(slotOffset(tile, i, chars.length));
        }
        const targetTile = c.movement_target_id ? tiles.get(c.movement_target_id) : undefined;
        states.push({
          char: c,
          pos,
          travelTo: targetTile && c.movement_target_id !== locId ? targetTile.center.clone() : null,
        });
      });
    }
    return states;
  }

  setInterval(() => {
    if (lastMap) npcs.update(computeNpcStates(lastMap));
  }, 1000);
  npcs.update(computeNpcStates(firstMap));

  // --- Frame-Hook: LOD (Raumauflösung), NPC-Animation, Pin-Bobbing ----------
  let bob = 0;
  engine.addFrameHook((dt) => {
    for (const tile of tiles.values()) {
      if (tile.isBuilding && tile.interior) {
        const d = Math.hypot(engine.target.x - tile.center.x, engine.target.z - tile.center.z);
        tile.fadeTarget = engine.dist < INTERIOR_CAM_DIST && d < CELL * 0.75 ? 1 : 0;
        applyTileFade(tile, dt);
      }
    }
    npcs.tick(dt, engine.dist);
    bob += dt * 2.2;
    for (const pin of pins.values()) {
      pin.position.y += Math.sin(bob) * 0.008;
    }
  });
}

boot();
