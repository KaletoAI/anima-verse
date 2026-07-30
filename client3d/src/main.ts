import * as THREE from 'three';
import * as api from './api';
import { Engine, isTypingTarget } from './scene/engine';
import { checkExit, enterEmbodied, exitEmbodied, type EmbodyDeps } from './game/embody';
import { activityToClipKind, FigureLibrary } from './scene/figures';
import { NpcManager, type NpcState } from './scene/npcs';
import { applyLevelDisplay, applyNightGlow, applyRoomVisibility, applyTileFade, applyTileOcclusion, applyWallCulling, buildTile, gridSurfaceKind, gridToWorld, roomFigureScale, setSurfaceTextures, setTerrainGrid, tileGroundY, CELL, type Tile } from './scene/tiles';
import { setModelEnvironment } from './scene/glbMaterials';
import { setPropLoadFocus } from './scene/propAssets';
import { mountScene, sceneFigureScale, SceneLibrary } from './scene/sceneRecipe';
import { PathGrid } from './scene/pathfind';
import { grassTexture, seededRandom } from './scene/textures';
import { bootStatus, createHud, InfoPanel, showLogin } from './ui';
import { mountHud } from './hud/mount';
import { gameActions, getGameState, setGameState, subscribeGameState } from './hud/bus';
import type { MapCharacter, WorldLocation, WorldMap } from './types';

const WORLDMAP_POLL_MS = 3000;
const ROOMS_POLL_MS = 4000;
const INTERIOR_CAM_DIST = 26; // näher als das -> Räume auflösen

const app = document.getElementById('app')!;

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/**
 * Start-Anfragen so lange wiederholen, bis der Server antwortet.
 *
 * Der Backend-Neustart (start.sh) trifft nur Port 8000; der Vite-Proxy
 * antwortet währenddessen mit 500, also schlagen genau die Boot-Abfragen
 * fehl. Vorher starb der Client daran endgültig: `startApp` warf, niemand
 * fing es, die Seite blieb leer und kam von selbst nie wieder — ein Reload
 * während des Neustarts sah aus wie ein Absturz. Jetzt wartet der Boot mit
 * sichtbarem Status und fängt sich, sobald der Server wieder da ist.
 */
async function retryBoot<T>(what: string, fn: () => Promise<T>,
                            status: ReturnType<typeof bootStatus>): Promise<T> {
  for (let attempt = 0; ; attempt++) {
    try {
      const out = await fn();
      status.remove();
      return out;
    } catch (e) {
      const wait = Math.min(15_000, 1000 * 2 ** Math.min(attempt, 4));
      console.warn(`[boot] ${what} fehlgeschlagen (Versuch ${attempt + 1}) — `
        + `neuer Versuch in ${wait / 1000} s`, e);
      status.set(`Server nicht erreichbar (${what}) — neuer Versuch in `
        + `${Math.round(wait / 1000)} s …`);
      await sleep(wait);
    }
  }
}

async function boot() {
  const status = bootStatus();
  // Erreichbarkeit und Anmeldung trennen: ein nicht erreichbarer Server ist
  // KEIN "nicht angemeldet" — sonst zeigt der Client eine Login-Maske, deren
  // Absenden zwangsläufig scheitert.
  const auth = await retryBoot('Anmeldestatus', () => api.authStatus(), status);
  if (auth.authenticated && auth.user) {
    void startApp(auth.user.username).catch((e) => {
      console.error('[boot] Start fehlgeschlagen', e);
      status.set('Start fehlgeschlagen — bitte Seite neu laden.');
    });
    return;
  }
  showLogin(async (u, p) => {
    const user = await api.login(u, p);
    await startApp(user.username);
  });
}

async function startApp(username: string) {
  const engine = new Engine(app);
  setModelEnvironment(engine.modelEnv);
  (window as unknown as { __engine: Engine }).__engine = engine;   // Debug-Hook (Tageszeit testen)
  (window as unknown as { __THREE: typeof THREE }).__THREE = THREE; // Debug-Hook (Szene vermessen)
  const figures = new FigureLibrary();
  // figures.load() wirft nie (Manifest/Clips fangen selbst) und darf NICHT
  // wiederholt werden — ein zweiter Lauf würde die Modelle doppelt einhängen.
  const figuresReady = figures.load();
  const status = bootStatus();
  const [allLocs, firstMap, surfaces] = await retryBoot('Weltdaten', () => Promise.all([
    api.getLocations(),
    api.getWorldMap(),
    api.getSurfaceTextures(),
  ]), status);
  await figuresReady;
  setSurfaceTextures(surfaces);   // globale Terrain-Texturen (AV3D-13)
  setPropLoadFocus(engine.target);   // GLB-Queue: Modelle nahe der Kamera zuerst
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
  mountHud({ username, avatar: firstMap.avatar });   // React HUD island (E2-T5)
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

  // Basement view: the global ground plane sits at height 0 across the whole
  // map, so a storey below ground would stay hidden even after the tile's own
  // plate ghosts (applyTileFade). While the interior view of a tile with a
  // basement is up, a rectangular hole the size of that tile's cell is
  // discarded out of this plane — same shader technique as the room clip
  // (@anima/scene-render clip.ts), just inverted: inside the rect goes away.
  // Uniforms are shared objects, so the frame hook can steer them per frame
  // without recompiling.
  const groundHole = { value: new THREE.Vector4(0, 0, 0, 0) }; // minX, minZ, maxX, maxZ
  const groundHoleOn = { value: 0 };
  const groundMat = ground.material as THREE.MeshStandardMaterial;
  groundMat.onBeforeCompile = (shader) => {
    shader.uniforms.uHole = groundHole;
    shader.uniforms.uHoleOn = groundHoleOn;
    shader.vertexShader = `varying vec3 vHoleWorld;\n${shader.vertexShader}`
      .replace('#include <project_vertex>',
        '#include <project_vertex>\n\tvHoleWorld = ( modelMatrix * vec4( transformed, 1.0 ) ).xyz;');
    const head = 'uniform vec4 uHole;\nuniform float uHoleOn;\nvarying vec3 vHoleWorld;\n';
    const test = `
  if ( uHoleOn > 0.5 &&
       vHoleWorld.x > uHole.x && vHoleWorld.x < uHole.z &&
       vHoleWorld.z > uHole.y && vHoleWorld.z < uHole.w ) discard;
`;
    const body = head + shader.fragmentShader;
    shader.fragmentShader = body.includes('#include <clipping_planes_fragment>')
      ? body.replace('#include <clipping_planes_fragment>', `${test}\n#include <clipping_planes_fragment>`)
      : body.replace('void main() {', `void main() {\n${test}`);
  };
  groundMat.customProgramCacheKey = () => 'ground-hole';

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
    const tile = buildTile(loc);
    tiles.set(loc.id, tile);
    engine.scene.add(tile.group);
    const scene = scenes.get(loc.id);
    if (scene) void mountScene(tile, scene);
  }
  engine.setPickables([...tiles.values()].map((t) => t.group));

  let firstSweep = true;
  const requestServerModels = () => {
    // Szenen-Rezepte: neue Locations holen + Signaturen nachfassen. EINE
    // Signatur deckt map3d, alle Raum-Layouts, die Modell-Metas und die
    // Prop-Sidecars ab (§ B1) — mehr gibt es nicht zu pollen. Beim ersten
    // Durchlauf entfällt der Sweep, prime() hat gerade geholt.
    for (const locId of tiles.keys()) scenes.request(locId);
    if (!firstSweep) void scenes.sweep();
    firstSweep = false;
  };
  requestServerModels();
  setInterval(requestServerModels, 60_000);

  // Layout-Live-Refresh: Grundrisse/Marker/Meta-Justierungen/Terrain aus dem
  // Admin erscheinen ohne Browser-Reload — Kachel wird bei Änderung neu gebaut
  const sigOf = (l: Partial<WorldLocation>) => JSON.stringify([
    l.map3d, l.entry_room, l.terrain || '',
    (l.rooms ?? []).map((r) => [r.id, r.name, r.layout]),
  ]);
  // Signaturen aus DERSELBEN Quelle wie der Poll (/world/locations): die
  // Worldmap reichert map3d um abgeleitete floors an — mit der gemergten
  // Boot-Variante als Startwert wich die Signatur beim ersten Poll ab und
  // jede Kachel mit Raum-Layouts wurde einmal grundlos neu gebaut.
  const locSig = new Map(placeable.map((l) => {
    const detail = detailById.get(l.id) ?? detailById.get(l.template_location_id || '');
    return [l.id, sigOf(detail ?? l)];
  }));
  function rebuildTile(old: Tile, loc: WorldLocation) {
    engine.scene.remove(old.group);
    old.group.traverse((o) => {   // CSS2D-Label-Elemente aufräumen
      const el = (o as { isCSS2DObject?: boolean; element?: HTMLElement });
      if (el.isCSS2DObject && el.element) el.element.remove();
    });
    const tile = buildTile(loc);
    tile.fade = old.fade;
    tile.fadeTarget = old.fadeTarget;
    tile.levelFilter = old.levelFilter;   // gewählte Etage über den Rebuild halten
    tiles.set(loc.id, tile);
    engine.scene.add(tile.group);
    const scene = scenes.get(loc.id);
    if (scene) void mountScene(tile, scene);
    engine.setPickables([...tiles.values()].map((t) => t.group));
  }
  // Szenen-Signatur bewegt sich (Layout, map3d, Modell-Meta, Prop-Sidecar) →
  // Kachel neu bauen. Wird eine Szene zu 404 (Layout gelöscht), bleibt genau
  // die prozedurale Kachel übrig — es gibt dann nichts mehr aufzuklappen.
  scenes.onScene = (locId) => {
    const tile = tiles.get(locId);
    if (tile) rebuildTile(tile, tile.loc);
  };
  async function pollLocations() {
    try {
      const fresh = await api.getLocations();
      const freshById = new Map(fresh.map((l) => [l.id, l]));
      // Erst sammeln, dann bauen: eine Terrain-Änderung muss VOR dem Neubau
      // ins Nachbarschafts-Grid, sonst backt die eigene Kachel noch mit dem
      // alten Grid (Reihenfolge war der Kern des Küsten-Befunds 2026-07-29).
      const dirty: [Tile, WorldLocation][] = [];
      let terrainChanged = false;
      for (const [id, tile] of tiles) {
        const detail = freshById.get(id) ?? freshById.get(tile.loc.template_location_id || '');
        if (!detail) continue;
        const sig = sigOf(detail);
        if (locSig.get(id) === sig) continue;
        locSig.set(id, sig);
        if ((detail.terrain || '') !== (tile.loc.terrain || '')) terrainChanged = true;
        // map3d aus dem Detail, aber ohne die abgeleiteten floors zu
        // verlieren: die trägt nur die Worldmap-Variante (Kachel vom Boot) —
        // sonst schrumpfte die prozedurale Hülle beim ersten echten Rebuild.
        const m3 = detail.map3d ?? tile.loc.map3d;
        const floors = detail.map3d?.floors ?? tile.loc.map3d?.floors;
        dirty.push([tile, {
          ...tile.loc,
          rooms: detail.rooms ?? [],
          map3d: m3 && floors !== undefined ? { ...m3, floors } : m3,
          entry_room: detail.entry_room ?? tile.loc.entry_room,
          terrain: detail.terrain ?? tile.loc.terrain,
        }]);
      }
      if (terrainChanged) {
        const nextLoc = new Map(dirty.map(([tl, loc]) => [tl.loc.id, loc]));
        setTerrainGrid([...tiles.values()].map((tl) => {
          const loc = nextLoc.get(tl.loc.id) ?? tl.loc;
          return { gx: loc.grid_x!, gy: loc.grid_y!, kind: gridSurfaceKind(loc) };
        }));
        // Die 4-Nachbarn jeder Terrain-Änderung mit neu bauen: deren
        // Zusammenstellungen (Küste) beziehen ihre Wasserrichtung aus dem
        // Grid — gemaltes Wasser muss die Küste daneben umbacken.
        const byCell = new Map([...tiles.values()].map((tl) => [`${tl.loc.grid_x},${tl.loc.grid_y}`, tl]));
        for (const [tl, loc] of [...dirty]) {
          if ((loc.terrain || '') === (tl.loc.terrain || '')) continue;
          for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]] as const) {
            const nb = byCell.get(`${tl.loc.grid_x! + dx},${tl.loc.grid_y! + dy}`);
            if (nb && !nextLoc.has(nb.loc.id)) {
              nextLoc.set(nb.loc.id, nb.loc);
              dirty.push([nb, nb.loc]);
            }
          }
        }
      }
      for (const [tile, loc] of dirty) rebuildTile(tile, loc);
    } catch { /* Server kurz weg -> nächster Poll */ }
  }
  setInterval(pollLocations, 10_000);

  // Wegfindung: Gebäude blockieren, Straßen/Natur sind begehbar
  const pathGrid = new PathGrid(
    placeable.map((l) => ({
      x: l.grid_x!, y: l.grid_y!,
      passable: !!(l.passable || l.template_location_id),
    }))
  );
  npcs.setPathGrid(pathGrid);
  // Debug-Hooks: laufendes Grid + Klasse, um Wegfindung zu vermessen
  (window as unknown as { __pathGrid: PathGrid }).__pathGrid = pathGrid;
  (window as unknown as { __PathGrid: typeof PathGrid }).__PathGrid = PathGrid;
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

  // --- Figure selection (E3-T1) --------------------------------------------
  // Figure picking runs before the tile pick: a hit figure gets the ring and
  // the plaque (React reads the bus), a miss clears the selection and lets the
  // click fall through to the tile's info panel.
  engine.pickFigure = (x, y) => {
    const name = npcs.characterAt(engine.raycasterAt(x, y));
    npcs.setSelected(name);
    if (!name) {
      setGameState({ selected: null });
      return false;
    }
    const char = lastMap?.characters.find((c) => c.name === name) ?? null;
    setGameState({ selected: char ? { char, isAvatar: name === lastMap!.avatar } : null });
    return true;
  };
  gameActions.zoomTo = (name) => {
    const p = npcs.positionOf(name);
    if (p) engine.flyTo(p, 12);
  };
  // The marker follows the BUS, not the click: closing the plaque happens on
  // the React side without a gameAction, and the ring has to go with it.
  subscribeGameState(() => {
    npcs.setSelected(getGameState().selected?.char.name ?? null);
  });

  // --- Embodied mode (E3-T2) -----------------------------------------------
  // Everything the mode needs is the avatar's live position: enter/leave are
  // camera moves, the frame hook only watches the zoom threshold.
  const embody: EmbodyDeps = {
    engine,
    avatarPos: () => npcs.positionOf((lastMap ?? firstMap).avatar),
  };
  gameActions.enterEmbodied = () => enterEmbodied(embody);
  gameActions.exitEmbodied = () => exitEmbodied(embody);
  engine.addFrameHook(() => checkExit(embody));
  // Esc leaves the mode — THE one binding for it. Guarded like the engine's own
  // keys: while the focus sits in a form field Esc belongs to that field (the
  // chat clears/blurs with it), not to the camera.
  window.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape' || isTypingTarget(e)) return;
    if (getGameState().mode === 'embodied') exitEmbodied(embody);
  });

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
  /** counts successful worldmap polls — travel seg/frac reconciliation in the
   *  NpcManager only runs against a genuinely NEW payload (npcs.update is
   *  called at 1 Hz off the cached map, the poll refreshes every 3 s) */
  let mapStamp = 1;
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

  /** Keep the plaque on the fresh worldmap snapshot (activity, mood, travel
   *  target change while it is open). A character that vanished from the map
   *  drops the selection including its marker. */
  function refreshSelection(map: WorldMap) {
    const sel = getGameState().selected;
    if (!sel) return;
    const char = map.characters.find((c) => c.name === sel.char.name) ?? null;
    if (!char) {
      npcs.setSelected(null);
      setGameState({ selected: null });
      return;
    }
    setGameState({ selected: { char, isAvatar: char.name === map.avatar } });
  }

  async function pollWorldMap() {
    try {
      lastMap = await api.getWorldMap();
      mapStamp += 1;
      hud.setOnline(true);
      takeRoomsFrom(lastMap);
      updatePins(lastMap);
      refreshSelection(lastMap);
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
        // Server-authoritative journey (contract § A11: the server computes, we
        // render): position = lerp along the path cells at seg/frac — NEVER the
        // tile centre of location_id, which lags at ticker cadence. The
        // NpcManager keeps extrapolating between polls via cellSecondsReal.
        const tr = c.travel;
        if (tr && tr.path.length >= 2) {
          const points = tr.path.map((id) => {
            const t = tiles.get(id);
            if (t) return t.center.clone().setY(tileGroundY(t, t.center));
            return null;
          });
          if (points.every((p): p is THREE.Vector3 => !!p)) {
            const seg = THREE.MathUtils.clamp(tr.seg, 0, points.length - 2);
            const pos = points[seg].clone().lerp(points[seg + 1], tr.frac);
            const last = points[points.length - 1];
            states.push({
              char: c,
              pos,
              scale: 1,
              route: { points, seg, frac: tr.frac,
                       cellSecondsReal: tr.cell_seconds_real, stamp: mapStamp },
              travelTo: last.clone(),
            });
            shownRoom.set(c.name, null);
            return;   // forEach callback — travellers skip room placement
          }
        }
        let pos: THREE.Vector3;
        let via: THREE.Vector3[] | undefined;
        let face: THREE.Vector3 | undefined;
        let lean: { tilt: number; roll: number } | undefined;
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
            // kuratierter Marker: Position, Blickrichtung UND Neigung
            const m = marked[idx % marked.length];
            pos = m.p.clone();
            if (m.rotation !== undefined) {
              const a = THREE.MathUtils.degToRad(m.rotation);
              face = new THREE.Vector3(Math.sin(a), 0, Math.cos(a));
            }
            if (m.tilt || m.roll) lean = { tilt: m.tilt || 0, roll: m.roll || 0 };
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
          lean,
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
    let basementOpen: Tile | null = null;
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
          // Same condition as the ground-plate ghost in applyTileFade: while
          // a basement scene's interior is up, the global ground opens too.
          if (tile.hasBasement) basementOpen = tile;
        }
        if (tile.fadeTarget === 1 && tile.fade > 0.4) open = tile;
      }
    }
    groundHoleOn.value = basementOpen ? 1 : 0;
    if (basementOpen) {
      let minX = basementOpen.center.x - CELL / 2;
      let minZ = basementOpen.center.z - CELL / 2;
      let maxX = basementOpen.center.x + CELL / 2;
      let maxZ = basementOpen.center.z + CELL / 2;
      // A tile-sized hole is enough to look straight down, but not to look
      // INTO the pit: from an angle its near rim stands between camera and
      // basement. So while a storey BELOW ground is actually displayed, the
      // hole grows towards the viewer — up to double the extent, smoothly
      // with the camera angle, recomputed per frame (that is what the
      // uniforms are for). Only for level < 0: at level 0 and above the
      // enlarged hole would tear open the map around the tile for nothing.
      if (basementOpen.levelFilter < 0) {
        const dx = engine.camera.position.x - basementOpen.center.x;
        const dz = engine.camera.position.z - basementOpen.center.z;
        const len = Math.hypot(dx, dz) || 1;
        const ux = dx / len;
        const uz = dz / len;
        // Only the edge FACING the camera moves — the far one stays put, so
        // the pit does not grow away from the viewer.
        if (ux > 0) maxX += CELL * ux; else minX += CELL * ux;
        if (uz > 0) maxZ += CELL * uz; else minZ += CELL * uz;
      }
      groundHole.value.set(minX, minZ, maxX, maxZ);
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

    // Raum-Sichtbarkeit: allein die gewählte Etage entscheidet. Der frühere
    // „Raum-Fokus" (Nachbarräume ausblenden, sobald einer das Bild füllt)
    // ist gestrichen — er hing am wandernden Kamera-Zielpunkt und ließ
    // Räume samt Diorama und Props winkelabhängig verschwinden.
    for (const tile of tiles.values()) {
      if (tile.roomGroups.size) applyRoomVisibility(tile);
    }
    npcs.tick(dt, engine.dist);
    bob += dt * 2.2;
    for (const pin of pins.values()) {
      pin.position.y += Math.sin(bob) * 0.008;
    }
  });
}

boot();
