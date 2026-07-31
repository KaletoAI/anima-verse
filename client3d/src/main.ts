import * as THREE from 'three';
import * as api from './api';
import { Engine, isTypingTarget } from './scene/engine';
import { checkExit, enterEmbodied, exitEmbodied, type EmbodyDeps } from './game/embody';
import { activityToClipKind, FigureLibrary } from './scene/figures';
import { NpcManager, WALK_SPEED, type NpcState } from './scene/npcs';
import { cellOf, clampToCell, keepAhead, splitDiagonal, stepDirection, walkDir, type Cell } from './game/walk';
import { planRoute, type ClickRoute } from './game/clickmove';
import { talkTargetNear, type TalkCandidate } from './game/proximity';
import { applyLevelDisplay, applyNightGlow, applyRoomVisibility, applyTileFade, applyTileOcclusion, applyWallCulling, buildTile, gridSurfaceKind, gridToWorld, roomFigureScale, setSurfaceTextures, setTerrainGrid, tileGroundY, CELL, type Tile } from './scene/tiles';
import { setModelEnvironment } from './scene/glbMaterials';
import { setPropLoadFocus } from './scene/propAssets';
import { mountScene, sceneFigureScale, SceneLibrary } from './scene/sceneRecipe';
import { PathGrid } from './scene/pathfind';
import { grassTexture, seededRandom } from './scene/textures';
import { bootStatus, createHud, InfoPanel, showLogin } from './ui';
import { mountHud } from './hud/mount';
import { gameActions, getGameState, setGameState, subscribeGameState, uiActions } from './hud/bus';
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
    // While a follow target is set (embodied mode) the camera belongs to the
    // followed figure: a fly-to would be dragged back by the chase every
    // frame and only make the view judder. The button stays visible — it is
    // simply without effect until the player leaves the mode.
    if (engine.follow) return;
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
    // `firstMap` on purpose: the deps object is built before `lastMap` exists,
    // and the avatar of a session does not change under us.
    avatarPos: () => npcs.positionOf(firstMap.avatar),
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
      reconcileAvatarCell(lastMap);   // server moved the avatar? (E3-T3)
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
    // Talk target (E3-T5): the same 1 Hz tick, and deliberately not a frame
    // hook — walking up to someone is a second-scale event, and `shownRoom`
    // is only rewritten here anyway. See the section further down.
    updateTalkTarget();
  }, 1000);
  npcs.update(computeNpcStates(firstMap));

  // --- Walking on foot (E3-T3) ----------------------------------------------
  // Two facts carry this: while the mode is on, the avatar's position is OURS
  // (npcs.setPlayerDriven — update() stops placing it), and every CELL BOUNDARY
  // belongs to the server (`/world/avatar/step`). Inside a cell the client walks
  // freely, at a boundary it either asks or slides along the edge. All the
  // geometry is in game/walk.ts and checked numerically by
  // scripts/smoke_walk_math.mjs; nothing here recomputes it.
  const avatarName = firstMap.avatar;   // one avatar per session (as everywhere else)
  /** Same passability rule the pathfinder is built with (buildings block, road
   *  and nature carry). A cell that is not on the map at all is not steppable
   *  either — the server would answer 404. */
  const passableCells = new Set(placeable
    .filter((l) => l.passable || l.template_location_id)
    .map((l) => `${l.grid_x},${l.grid_y}`));
  const locIdAtCell = new Map(placeable.map((l) => [`${l.grid_x},${l.grid_y}`, l.id]));
  function tileAtCell(c: Cell): Tile | null {
    const id = locIdAtCell.get(`${c.gx},${c.gy}`);
    return id ? tiles.get(id) ?? null : null;
  }

  /** `tick()` only counts a figure as moving from 0.05 units away, and at a
   *  high frame rate ONE step is shorter than that — the avatar would stand
   *  still without a walk animation. So the goal is set a short lead ahead;
   *  0.15 m reaches a boundary at most ~40 ms early. */
  const MIN_LEAD = 0.15;
  /** How long a refused edge is remembered. Without it a held key would fire a
   *  request per frame against a block rule and bury the player in toasts. */
  const REJECT_MEMORY_MS = 4000;
  /** Deadline for one step request. Only ONE may be in flight, so a request
   *  that never answers (proxy hiccup, server restart mid-step) would bar
   *  every cell boundary until the page is reloaded — the figure would still
   *  walk inside its cell and look merely "stuck", which is the worst kind of
   *  broken. After the deadline the step counts as failed. */
  const STEP_TIMEOUT_MS = 10_000;

  /** At most ONE step request in flight: a second one could overtake the first
   *  and the server would end up two cells away from the figure. While it runs,
   *  the figure clamps at the next boundary instead of crossing again. */
  let stepInFlight = false;
  /** Cell our own step aims at (or came back to after a refusal) — the
   *  authority check must not read it as foreign movement. It is consumed by
   *  the FIRST worldmap poll after the request ended (see
   *  `reconcileAvatarCell`), not by a timer. */
  let expectedCell: Cell | null = null;
  /** cell key -> time until which a refused crossing stays refused */
  const rejectedUntil = new Map<string, number>();
  /**
   * The ONE cell boundary the server has been asked about. It exists because
   * the request leaves before the figure reaches the line: the goal runs
   * MIN_LEAD ahead, so the figure still stands ~0.09 m short when the request
   * goes out. Without this memory the frames until the answer clamp the figure
   * in place, the answer arrives while it is STILL in the old cell, and the
   * very next frame asks again — three requests per edge, latency or not. The
   * server counts each of them from its own cell and ends up two cells ahead
   * of the figure: 403s for edges nobody walked at, then a snap-back.
   *
   * `granted` is what the answer buys: from then on the figure walks over that
   * boundary without asking again. The permission belongs to the cell it was
   * asked from and is dropped as soon as the figure stands somewhere else.
   */
  let askedEdge: { from: Cell; to: Cell; granted: boolean } | null = null;

  async function requestStep(direction: api.StepDirection, from: Cell, to: Cell,
    edge: { granted: boolean }) {
    stepInFlight = true;
    expectedCell = to;
    const abort = new AbortController();
    const deadline = setTimeout(() => abort.abort(), STEP_TIMEOUT_MS);
    try {
      await api.avatarStep(direction, abort.signal);
      // The boundary is open now: the figure walks over it in the next frames
      // WITHOUT another request. No snap — the server is already there and the
      // worldmap confirms it within a poll.
      edge.granted = true;
    } catch (e) {
      const err = e instanceof api.ApiError ? e : null;
      rejectedUntil.set(`${to.gx},${to.gy}`, Date.now() + REJECT_MEMORY_MS);
      expectedCell = from;
      if (askedEdge === edge) askedEdge = null;
      // The crossing did NOT happen, so the figure must not be standing past
      // the line: a hard put-back, not a walk-back — otherwise the local cell
      // stays the new one and the very next frame walks on into it.
      const p = npcs.positionOf(avatarName);
      if (p) {
        const back = clampToCell(p.x, p.z, from, CELL);
        npcs.snapPlayerTo(avatarName, new THREE.Vector3(back.x, p.y, back.z));
      }
      // A click route was planned across this edge — it is void now, whatever
      // the reason. Walking on would only collect the same refusal again.
      cancelRoute();
      // 403 = a rule refused it and the server wrote the reason for the
      // player. 404 = there is simply no location that way, which the edge
      // already shows — no toast for that.
      if (err?.status === 403) uiActions.toast?.(err.message);
      else if (abort.signal.aborted) console.warn('[walk] step request timed out');
      else if (!err) console.warn('[walk] step request failed', e);
    } finally {
      clearTimeout(deadline);
      stepInFlight = false;
    }
  }

  // --- Click to walk (E3-T4) ------------------------------------------------
  // A ground click plans a route ONCE (game/clickmove.ts); walking it is the
  // same frame hook, the same cell boundaries and the same step requests as
  // WASD — the route only replaces the direction the hook steers in.
  /** Reached-a-waypoint threshold. Must stay above the 0.05 that `tick()`
   *  needs to count a figure as moving, otherwise the last centimetres would
   *  never be walked and the route would never finish. */
  const ROUTE_ARRIVE = 0.2;
  let route: ClickRoute | null = null;
  let routeAt = 0;                      // index of the waypoint being steered at

  function cancelRoute() {
    if (!route) return;
    route = null;
    npcs.setWalkTarget(null);
  }

  /** Point the hook currently steers at: cell centres for the waypoints in
   *  between, the exact planned goal for the last one. */
  function routeGoal(): { x: number; z: number } | null {
    if (!route || routeAt >= route.cells.length) return null;
    if (routeAt === route.cells.length - 1) return route.goal;
    const c = route.cells[routeAt];
    return { x: c.gx * CELL, z: c.gy * CELL };
  }

  /** Ground height at a world point, so marker and walk goal sit on the tile
   *  instead of on the y=0 plane. */
  const groundProbe = new THREE.Vector3();
  function groundY(x: number, z: number): number {
    const tile = tileAtCell(cellOf(x, z, CELL));
    if (!tile) return 0;
    groundProbe.set(x, 0, z);
    return tileGroundY(tile, groundProbe);
  }

  engine.onGroundClick = (x, y) => {
    const state = getGameState();
    // Overview mode is untouched: there a click stays a tile pick.
    if (state.mode !== 'embodied' || state.movementLocked) return false;
    const pos = npcs.positionOf(avatarName);
    const hit = engine.groundPointAt(x, y);
    if (!pos || !hit) return false;
    const planned = planRoute(
      { x: pos.x, z: pos.z }, { x: hit.x, z: hit.z },
      (gx, gy) => passableCells.has(`${gx},${gy}`),
      (a, b) => {
        const pts = pathGrid.findPath(a.gx, a.gy, b.gx, b.gy);
        if (!pts.length) return null;
        return pts.map((p) => {
          const c = PathGrid.cellOf(p);
          return { gx: c.x, gy: c.y };
        });
      },
      CELL,
    );
    // Nothing walkable under the pointer (a building with no way to it, the
    // map edge): let the click fall through to the tile's info panel.
    if (!planned) return false;
    route = planned;
    routeAt = 0;
    npcs.setWalkTarget(new THREE.Vector3(planned.goal.x,
      groundY(planned.goal.x, planned.goal.z), planned.goal.z));
    return true;
  };

  // The player drives the avatar for exactly as long as the mode is on. Hung
  // off the BUS, not off the enter/exit calls: zooming out leaves the mode
  // from inside embody.ts, and the figure has to be handed back then too.
  subscribeGameState(() => {
    npcs.setPlayerDriven(getGameState().mode === 'embodied' ? avatarName : null);
  });

  const walkGoal = new THREE.Vector3();
  engine.addFrameHook((dt) => {
    const state = getGameState();
    if (state.mode !== 'embodied') {
      cancelRoute();                      // leaving the mode drops the route
      return;
    }
    // Party follower: the leader carries the avatar along; the server refuses
    // every step anyway, so the keys stay dead instead of collecting 403s.
    if (state.movementLocked) {
      cancelRoute();
      return;
    }
    const pos = npcs.positionOf(avatarName);
    if (!pos) return;                     // no figure on the map (yet) — nothing to steer
    const keyDir = walkDir(engine.keysDown(), engine.yaw);
    // The keys always win: touching WASD is the player taking over from the
    // click order, not fighting it.
    if (keyDir) cancelRoute();
    let dir = keyDir;
    // How far the goal may be pushed ahead this frame. Unlimited for the keys
    // (the direction just carries on), capped at the remaining distance while
    // a route runs, so the figure stops ON the waypoint instead of past it.
    let reach = Infinity;
    while (!dir && route) {
      const wp = routeGoal();
      if (!wp) { cancelRoute(); break; }   // last waypoint reached: done
      const dx = wp.x - pos.x;
      const dz = wp.z - pos.z;
      const dist = Math.hypot(dx, dz);
      if (dist < ROUTE_ARRIVE) { routeAt += 1; continue; }
      dir = { x: dx / dist, z: dz / dist };
      reach = dist;
    }
    if (!dir) return;
    const here = cellOf(pos.x, pos.z, CELL);
    // A permission belongs to the cell it was asked from; standing anywhere
    // else means it has been used (or the figure was moved away from it).
    if (askedEdge && (askedEdge.from.gx !== here.gx || askedEdge.from.gy !== here.gy)) {
      askedEdge = null;
    }
    const lead = Math.min(Math.max(WALK_SPEED * dt, MIN_LEAD), reach);
    let x = pos.x + dir.x * lead;
    let z = pos.z + dir.z * lead;
    let next = cellOf(x, z, CELL);
    // Corner: a goal that crosses BOTH axes has no compass step. Split it into
    // the single-axis step it really is instead of reading it as blocked —
    // otherwise an exact 45° heading (the camera's default) sticks to the
    // corner for good.
    if (next.gx !== here.gx && next.gy !== here.gy) {
      ({ x, z } = splitDiagonal(x, z, here, CELL));
      next = cellOf(x, z, CELL);
    }
    if (next.gx !== here.gx || next.gy !== here.gy) {
      const step = stepDirection(here, next);
      const key = `${next.gx},${next.gy}`;
      if (askedEdge && askedEdge.to.gx === next.gx && askedEdge.to.gy === next.gy) {
        // Exactly this boundary is already asked for: wait for the answer,
        // then walk over it. Never a second request for the same edge.
        if (!askedEdge.granted) ({ x, z } = clampToCell(x, z, here, CELL));
      } else {
        const barred = !step || !passableCells.has(key)
          || (rejectedUntil.get(key) ?? 0) > Date.now();
        if (barred || stepInFlight) {
          // A route that runs into a barred edge is void — the plan was made
          // against the map, so this is a refusal the plan did not know about.
          // A step merely in flight is NOT that: there the figure just waits
          // at the boundary for its turn.
          if (barred) cancelRoute();
          ({ x, z } = clampToCell(x, z, here, CELL));
        } else {
          askedEdge = { from: here, to: next, granted: false };
          void requestStep(step, here, next, askedEdge);
          // Behind the line until the answer comes: asking AND walking on in
          // the same frame is what used to trigger the repeat requests.
          ({ x, z } = clampToCell(x, z, here, CELL));
        }
      }
    }
    // The clamp pulls the goal to the inset edge, which can be BEHIND the
    // figure — `tick()` would walk backwards and turn the figure around every
    // frame. On a blocked axis the goal is the position itself (stand still),
    // the free axis keeps sliding along the edge.
    ({ x, z } = keepAhead({ x, z }, pos, dir));
    walkGoal.set(x, groundY(x, z), z);
    npcs.setPlayerTarget(avatarName, walkGoal);
  });

  /** Authority check: while the player steers, the SERVER can still move the
   *  avatar (teleport, party pull, admin). Such a move is a jump — the figure
   *  goes to the server's tile and the camera follows. It must NOT fire for
   *  our own steps, which are briefly out of sync in both directions: the
   *  request has returned but this payload predates it (server = old cell,
   *  expected = local), or the payload is already ahead of the walking figure
   *  (server = expected, local = old cell).
   *
   *  That excuse is worth exactly ONE poll: the payload of the first poll
   *  after the request ended may still have been in flight while the step was
   *  answered, the next one cannot be. So `expectedCell` is consumed here
   *  instead of expiring on a timer — a 15-second window used to blind the
   *  check against real foreign movement for five polls in a row. */
  function reconcileAvatarCell(map: WorldMap) {
    if (getGameState().mode !== 'embodied') return;
    if (stepInFlight) return;
    const pos = npcs.positionOf(avatarName);
    if (!pos) return;
    const me = map.characters.find((c) => c.name === avatarName);
    const tile = me ? tiles.get(me.location_id) ?? null : null;
    if (!tile || tile.loc.grid_x == null || tile.loc.grid_y == null) return;
    const server: Cell = { gx: tile.loc.grid_x, gy: tile.loc.grid_y };
    const local = cellOf(pos.x, pos.z, CELL);
    if (server.gx === local.gx && server.gy === local.gy) {
      expectedCell = null;                 // in sync, nothing outstanding
      return;
    }
    if (expectedCell
      && ((expectedCell.gx === local.gx && expectedCell.gy === local.gy)
        || (expectedCell.gx === server.gx && expectedCell.gy === server.gy))) {
      expectedCell = null;               // one poll of grace, then it counts
      return;
    }
    const p = tile.center.clone();
    p.setY(tileGroundY(tile, p));
    npcs.snapPlayerTo(avatarName, p);
    engine.flyTo(p, engine.targetDist);
    expectedCell = null;
    askedEdge = null;                    // that permission was for another cell
    // The figure was moved from under the route — the plan started somewhere
    // else and would now walk back through cells it never chose.
    cancelRoute();
  }

  // --- Talking by proximity (E3-T5) -----------------------------------------
  // Walking up to someone is the whole interaction: the bus carries the name,
  // the HUD shows the prompt and F opens the chat. The rule itself is pure
  // (`game/proximity.ts`, checked in scripts/smoke_walk_math.mjs); everything
  // here is the lookup of its arguments.
  //
  // Rooms come from `shownRoom`, NOT from `roomOf` — but only for the NPCs is
  // that "the room the view DRAWS". For them the two genuinely differ: a room
  // resolves only above the fade threshold, so `shownRoom` is null while the
  // interior is closed, and the prompt cannot fire through a wall one is
  // looking at.
  //
  // For the AVATAR it is the server's view. Its figure is player-driven, so
  // `npcs.update` ignores every placement field for it, yet its `shownRoom`
  // entry is still written from `roomOf` (the worldmap's `room_id`) in
  // `computeNpcStates`. Position (drawn by us) and room (told by the server)
  // therefore come from two different sources, and the known consequence is:
  // standing inside a building with the interior open (avatar room = "hall")
  // next to a character the server assigns no room to (room = null) never
  // yields a prompt, however close the two are drawn. Accepted until T6 brings
  // walking between rooms — which is where that pairing gets sorted out.
  function updateTalkTarget() {
    const state = getGameState();
    const clear = () => { if (state.talkTarget) setGameState({ talkTarget: null }); };
    // Only the embodied mode addresses anybody — in the overview there is no
    // "standing next to", the camera is free of the figure.
    if (state.mode !== 'embodied' || !lastMap) return clear();
    const me = npcs.positionOf(avatarName);
    if (!me) return clear();
    // The avatar's cell is LIVE (the player drives it), while its
    // `location_id` on the worldmap is up to one poll behind — reading the
    // location off the position means the prompt appears when the player has
    // arrived, not three seconds later. Only if that cell carries no location
    // at all does the map's answer stand in.
    const here = cellOf(me.x, me.z, CELL);
    const myLoc = locIdAtCell.get(`${here.gx},${here.gy}`)
      ?? lastMap.characters.find((c) => c.name === avatarName)?.location_id;
    if (!myLoc) return clear();
    const candidates: TalkCandidate[] = [];
    for (const c of lastMap.characters) {
      if (c.name === avatarName) continue;
      const p = npcs.positionOf(c.name);
      const scale = npcs.scaleOf(c.name);
      if (!p || scale === null) continue;   // not (yet) a figure in the scene
      candidates.push({
        name: c.name,
        pos: { x: p.x, z: p.z },
        locId: c.location_id,
        room: shownRoom.get(c.name) ?? null,
        scale,
      });
    }
    const target = talkTargetNear(
      { name: avatarName, pos: { x: me.x, z: me.z }, locId: myLoc,
        room: shownRoom.get(avatarName) ?? null },
      candidates,
    );
    if (target !== state.talkTarget) setGameState({ talkTarget: target });
  }
  // Leaving the mode drops the prompt in the same tick the mode changes,
  // instead of leaving it standing for up to a second.
  subscribeGameState(() => {
    if (getGameState().mode !== 'embodied') updateTalkTarget();
  });

  // F is the ONE action key: talk to whoever is in range, and — as the
  // keyboard counterpart of the plaque's "Take control" — enter the mode when
  // the avatar is selected in the overview. Guarded like Esc: while the focus
  // sits in the chat composer, F types an f. Modifier combinations belong to
  // the browser (Ctrl+F is the page search).
  window.addEventListener('keydown', (e) => {
    if (e.key.toLowerCase() !== 'f' || isTypingTarget(e)) return;
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    const state = getGameState();
    if (state.talkTarget) {
      uiActions.openChat?.();
      return;
    }
    if (state.mode === 'overview' && state.selected?.isAvatar) gameActions.enterEmbodied?.();
  });

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
