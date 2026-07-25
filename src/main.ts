import * as THREE from 'three';
import * as api from './api';
import { Engine } from './scene/engine';
import { activityToClipKind, FigureLibrary } from './scene/figures';
import { NpcManager, type NpcState } from './scene/npcs';
import { applyBuildingModel, applyLevelDisplay, applyNightGlow, applyRoomFocus, applyRoomModel, applyTileFade, applyTileOcclusion, applyWallCulling, buildTile, gridSurfaceKind, gridToWorld, roomFigureScale, setLocationAnchor, setSurfaceTextures, setTerrainGrid, storeyHeight, tileGroundY, CELL, type Tile } from './scene/tiles';
import { buildingLibrary, roomModelLibrary, setModelEnvironment } from './scene/buildings';
import { setPropLibrary, setPropLoadFocus } from './scene/propAssets';
import { mountRoomRecipe, RecipeLibrary, unmountRoomRecipe } from './scene/roomRecipe';
import { mountScene, sceneFigureScale, SceneLibrary } from './scene/sceneRecipe';
import { PathGrid } from './scene/pathfind';
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
  setModelEnvironment(engine.modelEnv);
  (window as unknown as { __engine: Engine }).__engine = engine;   // Debug-Hook (Tageszeit testen)
  (window as unknown as { __THREE: typeof THREE }).__THREE = THREE; // Debug-Hook (Szene vermessen)
  const figures = new FigureLibrary();
  const [allLocs, firstMap, surfaces, props] = await Promise.all([
    api.getLocations(),
    api.getWorldMap(),
    api.getSurfaceTextures(),
    api.getProps(),
    figures.load(),
  ]);
  setSurfaceTextures(surfaces);   // globale Terrain-Texturen (AV3D-13)
  setPropLibrary(props);          // Prop-Bibliothek (Maße + Orientierungs-Fix)
  setPropLoadFocus(engine.target);   // GLB-Queue: Props nahe der Kamera zuerst
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

  // Nachbarschafts-Grid der Oberflächen-Arten (für Zusammenstellungen
  // wie die Küste: Verlauf Richtung Wasser-Nachbarn)
  setTerrainGrid(placeable.map((l) => ({ gx: l.grid_x!, gy: l.grid_y!, kind: gridSurfaceKind(l) })));

  // Szenen-Rezept (Vertrag Teil B): der Server liefert die komplette Szene
  // einer Location als fertige Primitive + Platzierungs-Specs. Wo es eins
  // gibt, baut der Client NICHTS selbst mehr (kein Grundriss, keine
  // Öffnungs-Aufteilung, keine eigenen Konstanten/Farben) — 404 = Legacy-Fall,
  // dann bleibt der prozedurale Pfad unverändert.
  // Vor dem ersten Kachelbau holen, damit jede Kachel gleich im richtigen
  // Modus entsteht.
  const scenes = new SceneLibrary();
  await scenes.prime(placeable.map((l) => l.id));

  const tiles = new Map<string, Tile>();
  for (const loc of placeable) {
    const scene = scenes.get(loc.id);
    const tile = buildTile(loc, { sceneMode: !!scene });
    tiles.set(loc.id, tile);
    engine.scene.add(tile.group);
    if (scene) void mountScene(tile, scene);
  }
  engine.setPickables([...tiles.values()].map((t) => t.group));

  // Gebäude-/Kachel-Modelle vom Server (AV3D-9): lazy laden, prozedurale
  // Hülle ersetzen; solange 404/Generierung läuft, regelmäßig erneut fragen.
  // Klon-Kacheln (z.B. viele Wald-Kacheln einer Template-Location) teilen
  // sich ein Modell — der Schlüssel ist die Template-ID, jede Kachel bekommt
  // einen Klon mit geteilter Geometrie.
  const modelKeyOf = (loc: WorldLocation) => loc.template_location_id || loc.id;
  const buildings = buildingLibrary();
  const applyServerBuilding = (tile: Tile) => {
    // Szenen-Pfad: Hülle, Maßstab und Erdung stehen in der Spec — hier gibt es
    // keine zweite, lokal gerechnete Antwort auf die Gebäudegröße.
    if (scenes.has(tile.loc.id)) return;
    const model = buildings.get(modelKeyOf(tile.loc));
    if (!model) return;
    // v3-Maßstabs-Anker (backend-note-scale-anchors.md): explizites
    // plan_width_m, sonst Auto-Ableitung height_m x Mesh-Proportion.
    // Ändert sich der Anker, wird die Kachel mit den Anker-Maßen neu gebaut.
    const meta = model.userData.meta as { height_m?: number; floors?: number } | undefined;
    const planW = tile.loc.map3d?.plan_width_m
      || ((meta?.height_m || 0) * ((model.userData.aspectXZoverY as number) || 0));
    if (planW > 0) {
      const k = 8 / planW;
      const storeyWorld = meta?.height_m && meta?.floors
        ? (meta.height_m / meta.floors) * k
        : storeyHeight(tile.loc);
      if (setLocationAnchor(tile.loc.id, { k, storeyWorld })) {
        rebuildTile(tile, tile.loc);   // wendet das Modell wieder an
        return;
      }
    }
    applyBuildingModel(tile, model);
  };
  buildings.onModelReady = (key) => {
    // Multimap-Auflösung: ein Template-Modell landet auf allen Klon-Kacheln
    for (const tile of [...tiles.values()]) {
      if (modelKeyOf(tile.loc) === key) applyServerBuilding(tile);
    }
  };
  // Raum-Modelle (AV3D-2): nur Räume mit Layout haben einen Andockpunkt
  const roomModels = roomModelLibrary();
  const tileByRoom = new Map<string, Tile>();
  for (const tile of tiles.values()) {
    for (const r of tile.loc.rooms) if (r.layout) tileByRoom.set(r.id, tile);
  }
  // Raum-Rezepte (Raum-Props): die Hülle kommt immer aus dem Rezept (Wände/
  // Boden/Öffnungen), Props wenn placements da sind — und das DIORAMA
  // koexistiert (seit layout.model_at wird es wie ein Prop im Raum
  // platziert) und wird immer geladen. signature-Polling im 60-s-Zyklus.
  const recipes = new RecipeLibrary();
  /** Legacy-Ketten laufen nur für Locations OHNE Szenen-Rezept — sonst gäbe es
   *  die Geometrie zweimal, genau die Drift, die Teil B beseitigt. */
  const legacyRoom = (roomId: string): Tile | null => {
    const tile = tileByRoom.get(roomId);
    if (!tile || scenes.has(tile.loc.id)) return null;
    return tile;
  };
  recipes.onRecipe = (roomId, recipe) => {
    const tile = legacyRoom(roomId);
    if (!tile) return;
    if (recipe && recipe.outline.length >= 3) void mountRoomRecipe(tile, roomId, recipe);
    else unmountRoomRecipe(tile, roomId);
    roomModels.request(roomId);
    const model = roomModels.get(roomId);
    if (model) applyRoomModel(tile, roomId, model);
  };
  roomModels.onModelReady = (roomId) => {
    const tile = legacyRoom(roomId);
    const model = roomModels.get(roomId);
    if (tile && model) applyRoomModel(tile, roomId, model);
  };
  let firstSweep = true;
  const requestServerModels = () => {
    for (const tile of tiles.values()) {
      if (scenes.has(tile.loc.id)) continue;          // Szene liefert das Modell
      if (!tile.serverModel) buildings.request(modelKeyOf(tile.loc));
    }
    // Rezept zuerst (Weiche); Diorama-Anfragen stößt onRecipe an
    for (const [roomId, tile] of tileByRoom) {
      if (!scenes.has(tile.loc.id)) recipes.request(roomId);
    }
    // Szenen-Rezepte: neue Locations holen + Signaturen nachfassen (deckt
    // map3d, alle Raum-Layouts, Modell-Metas und Prop-Sidecars ab). Beim
    // ersten Durchlauf entfällt der Sweep — prime() hat gerade geholt.
    for (const locId of tiles.keys()) scenes.request(locId);
    if (!firstSweep) void scenes.sweep();
    firstSweep = false;
    // neu generierte Modelle/Rezepte ohne Reload erkennen (signature)
    void recipes.sweep();
    void buildings.sweepSignatures();
    void roomModels.sweepSignatures();
  };
  requestServerModels();
  setInterval(requestServerModels, 60_000);

  // Layout-Live-Refresh: Grundrisse/Marker/Meta-Justierungen aus dem Admin
  // erscheinen ohne Browser-Reload — Kachel wird bei Änderung neu gebaut
  const sigOf = (l: Partial<WorldLocation>) => JSON.stringify([
    l.map3d, l.entry_room,
    (l.rooms ?? []).map((r) => [r.id, r.name, r.layout]),
  ]);
  const locSig = new Map(placeable.map((l) => [l.id, sigOf(l)]));
  function rebuildTile(old: Tile, loc: WorldLocation) {
    engine.scene.remove(old.group);
    old.group.traverse((o) => {   // CSS2D-Label-Elemente aufräumen
      const el = (o as { isCSS2DObject?: boolean; element?: HTMLElement });
      if (el.isCSS2DObject && el.element) el.element.remove();
    });
    const scene = scenes.get(loc.id);
    const tile = buildTile(loc, { sceneMode: !!scene });
    tile.fade = old.fade;
    tile.fadeTarget = old.fadeTarget;
    tile.levelFilter = old.levelFilter;   // gewählte Etage über den Rebuild halten
    tiles.set(loc.id, tile);
    engine.scene.add(tile.group);
    for (const r of loc.rooms) if (r.layout) tileByRoom.set(r.id, tile);
    if (scene) {
      // Szenen-Pfad: die ganze Innenansicht plus Gebäudehülle kommt aus dem
      // Payload — keine der Legacy-Ketten anfassen.
      void mountScene(tile, scene);
    } else {
      const bm = buildings.get(modelKeyOf(loc));
      if (bm) applyBuildingModel(tile, bm);
      for (const r of loc.rooms) {
        if (!r.layout) continue;
        const recipe = recipes.get(r.id);
        if (recipe && recipe.outline.length >= 3) {
          void mountRoomRecipe(tile, r.id, recipe);   // frische Kachel: Rezept-Szene neu montieren
        }
        recipes.request(r.id);         // unbekannt: onRecipe montiert nach dem Laden
        roomModels.invalidate(r.id);   // rotation/model_at evtl. geändert
        roomModels.request(r.id);
      }
    }
    engine.setPickables([...tiles.values()].map((t) => t.group));
  }
  // Szenen-Signatur bewegt sich (Layout, map3d, Modell-Meta, Prop-Sidecar) →
  // Kachel im passenden Modus neu bauen. Wird eine Szene zu 404 (Layout
  // gelöscht), fällt dieselbe Kachel auf den Legacy-Pfad zurück.
  scenes.onScene = (locId) => {
    const tile = tiles.get(locId);
    if (tile) rebuildTile(tile, tile.loc);
  };
  async function pollLocations() {
    try {
      const fresh = await api.getLocations();
      const freshById = new Map(fresh.map((l) => [l.id, l]));
      for (const [id, tile] of tiles) {
        const detail = freshById.get(id) ?? freshById.get(tile.loc.template_location_id || '');
        if (!detail) continue;
        const sig = sigOf(detail);
        if (locSig.get(id) === sig) continue;
        locSig.set(id, sig);
        rebuildTile(tile, {
          ...tile.loc,
          rooms: detail.rooms ?? [],
          map3d: detail.map3d ?? tile.loc.map3d,
          entry_room: detail.entry_room ?? tile.loc.entry_room,
        });
      }
    } catch { /* Server kurz weg -> nächster Poll */ }
  }
  setInterval(pollLocations, 10_000);

  // Wegfindung: Gebäude blockieren, Straßen/Natur sind begehbar
  npcs.setPathGrid(new PathGrid(
    placeable.map((l) => ({
      x: l.grid_x!, y: l.grid_y!,
      passable: !!(l.passable || l.template_location_id),
    }))
  ));
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
  /** aktuell DARGESTELLTER Raum je Figur (null = Außenansicht) — erkennt
   *  Betreten/Verlassen/Wechsel für das Exit-Routing */
  const shownRoom = new Map<string, string | null>();

  // AV3D-8: room_id kommt direkt mit der Worldmap; dazu die Clip-Set-Kette
  function takeRoomsFrom(map: WorldMap) {
    for (const c of map.characters) {
      if (c.room_id) roomOf.set(c.name, c.room_id);
      figures.setCharacterSets(c.name, c.animation_sets);
      figures.setCharacterHeight(c.name, c.height_cm);
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

  // Outfit-/Modellwechsel: der Server kann pro Charakter ein anderes Modell
  // ausliefern (ein Modell je Outfit). Bis die Worldmap eine Signatur liefert,
  // fragen wir sie periodisch für die sichtbaren Charaktere nach.
  async function pollModelChanges() {
    const names = (lastMap?.characters ?? []).map((c) => c.name);
    for (const n of names) {
      // Kein Rebuild hier: die Figur behält ihr altes Modell, bis onModelReady
      // das neue meldet — sonst flackert sie während des Downloads.
      await figures.refreshIfChanged(n);
    }
  }
  setInterval(pollModelChanges, 20_000);

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
        let via: THREE.Vector3[] | undefined;
        let face: THREE.Vector3 | undefined;
        let scale = 1;
        const room = roomOf.get(c.name);
        const roomCenter = room ? tile.roomCenters.get(room) : undefined;
        // dauerhaft sichtbare Räume gelten in jeder Zoomstufe
        const inRoom = roomCenter && room && (tile.fade > 0.5 || tile.alwaysVisibleRooms.has(room))
          ? room : null;
        // Innenraum-Maßstab: bei Szenen-Locations aus dem Payload
        // (figures.base_height_m_world, § B1), sonst wie bisher aus dem Anker
        const roomScale = sceneFigureScale(tile.loc.id) ?? roomFigureScale(tile.loc);
        if (inRoom && roomCenter) {
          const mates = roomMates.get(inRoom)!;
          const idx = mates.indexOf(c.name);
          const spots = tile.roomSpots.get(inRoom);
          // Aktivitäts-Animation entscheidet die Stellfläche. Kuratierte
          // Marker (AV3D-11) schlagen die Heuristik aus der Modell-Abtastung.
          const kind = c.activity_animation || activityToClipKind(c.activity || '');
          const marked = tile.roomMarkers.get(inRoom)?.get(kind);
          const sit = tile.roomSitSpots.get(inRoom);
          const lieDown = tile.roomLieSpots.get(inRoom);
          const pool = kind === 'lie' ? (lieDown?.length ? lieDown : sit)
            : kind === 'sit' ? (sit?.length ? sit : lieDown) : undefined;
          if (marked?.length) {
            // kuratierter Marker: Position + eingestellte Blickrichtung
            const m = marked[idx % marked.length];
            pos = m.p.clone();
            if (m.rotation !== undefined) {
              const a = THREE.MathUtils.degToRad(m.rotation);
              face = new THREE.Vector3(Math.sin(a), 0, Math.cos(a));
            }
          } else if (pool?.length) {
            pos = pool[idx % pool.length].clone();
          } else if (spots?.length) {
            // abgetastete freie Stellfläche im Raum-Modell (nicht in Möbeln)
            pos = spots[idx % spots.length].clone();
          } else {
            pos = roomCenter.clone().add(
              roomSlot(idx, mates.length, c.name).multiplyScalar(roomScale)
            );
          }
          scale = roomScale;
        } else {
          pos = tile.center.clone().add(slotOffset(tile, i, chars.length));
          // Eingebackene Bodenhaut des Gebäude-Meshes: auf die Oberfläche
          // stellen statt bei y=0 darin zu versinken (Befund Kira).
          pos.setY(tileGroundY(tile, pos));
        }
        // Exit-Routing: bei Betreten/Verlassen/Wechsel des dargestellten
        // Raums über die Ausgänge laufen statt durch Wände; bei
        // Etagenwechseln zusätzlich über den Fahrstuhl (AV3D-12)
        const prevShown = shownRoom.get(c.name) ?? null;
        if (inRoom !== prevShown) {
          const exits: THREE.Vector3[] = [];
          const prevExit = prevShown ? tile.roomExits.get(prevShown) : undefined;
          if (prevExit) exits.push(prevExit.clone());                // alten Raum verlassen
          const levelOf = (r: string | null) => (r ? tile.roomLevels.get(r) ?? 0 : 0);
          const lf = levelOf(prevShown), lt = levelOf(inRoom);
          if (lf !== lt && tile.elevatorStops) {
            const a = tile.elevatorStops.get(lf) ?? tile.elevatorStops.get(0);
            const b = tile.elevatorStops.get(lt) ?? tile.elevatorStops.get(0);
            if (a) exits.push(a.clone());                            // Fahrstuhl einsteigen
            if (b) exits.push(b.clone());                            // Fahrt zur Ziel-Etage
          }
          const nextExit = inRoom ? tile.roomExits.get(inRoom) : undefined;
          if (nextExit) exits.push(nextExit.clone());                // neuen Raum betreten
          if (exits.length) via = exits;
          shownRoom.set(c.name, inRoom);
        }
        const targetTile = c.movement_target_id ? tiles.get(c.movement_target_id) : undefined;
        const travelTo = targetTile && c.movement_target_id !== locId ? targetTile.center.clone() : null;
        // Reisende schauen Richtung Ziel — sonst spielt die Lauf-Animation
        // im Stand in eine beliebige Richtung (Nachbarn/Süden)
        if (travelTo && !face) {
          face = travelTo.clone().sub(pos).setY(0);
        }
        // Etagen-Umschalter: Figuren auf nicht gewählten Etagen ausblenden
        const hidden = !!inRoom && tile.fade > 0.5
          && !tile.alwaysVisibleRooms.has(inRoom)
          && (tile.roomLevels.get(inRoom) ?? 0) !== tile.levelFilter;
        states.push({
          char: c,
          pos,
          scale,
          via,
          face,
          hidden,
          travelTo,
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
    let open: Tile | null = null;
    for (const tile of tiles.values()) {
      if (tile.isBuilding && tile.interior) {
        const d = Math.hypot(engine.target.x - tile.center.x, engine.target.z - tile.center.z);
        // mehrgeschossig: Innenansicht bis zu größerer Distanz halten, sonst
        // springt die Ansicht auf die Hülle, bevor man die Obergeschosse sieht
        tile.fadeTarget = engine.dist < INTERIOR_CAM_DIST + tile.interiorLift && d < CELL * 0.75 ? 1 : 0;
        applyTileFade(tile, dt);
        if (tile.fade > 0.03) {
          applyLevelDisplay(tile);
          if (tile.outlineWalls.length) {
            applyWallCulling(tile, engine.camera.position.x, engine.camera.position.z);
          }
        }
        if (tile.fadeTarget === 1 && tile.fade > 0.4) open = tile;
      }
    }

    // Verdecker Richtung Kamera: bei offener Innenansicht Nachbar-Kacheln
    // ausblenden, die zwischen Kamera und der Kachel liegen (XZ-Korridor)
    const cam = engine.camera.position;
    for (const tile of tiles.values()) {
      let hide = false;
      if (open && tile !== open && tile.height > 1.5) {
        const tx = open.center.x - cam.x, tz = open.center.z - cam.z;
        const nx = tile.center.x - cam.x, nz = tile.center.z - cam.z;
        const len2 = tx * tx + tz * tz;
        const t = len2 > 1e-6 ? (nx * tx + nz * tz) / len2 : 0;
        if (t > 0.05 && t < 0.92) {
          const px = cam.x + tx * t, pz = cam.z + tz * t;
          hide = Math.hypot(tile.center.x - px, tile.center.z - pz) < CELL * 1.05;
        }
      }
      applyTileOcclusion(tile, hide, dt);
    }

    // Raum-Fokus: füllt ein Raum ~80 % des Bildes (Kameradistanz < 1,5x
    // Raumgröße bei 45°-FOV), Nachbar-Räume der Kachel ausblenden
    for (const tile of tiles.values()) {
      if (!tile.roomGroups.size) continue;
      let focus: string | null = null;
      if (tile === open) {
        for (const [id, r] of tile.roomRects) {
          if (Math.abs(engine.target.x - r.x) < r.w / 2 && Math.abs(engine.target.z - r.z) < r.d / 2) {
            if (engine.dist < Math.max(r.w, r.d) * 1.5) focus = id;
            break;
          }
        }
      }
      applyRoomFocus(tile, focus);
    }
    npcs.tick(dt, engine.dist);
    bob += dt * 2.2;
    for (const pin of pins.values()) {
      pin.position.y += Math.sin(bob) * 0.008;
    }
  });
}

boot();
