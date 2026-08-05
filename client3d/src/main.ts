import * as THREE from 'three';
import * as api from './api';
import { initDebug3d } from './debug3d';
import { Engine, isTypingTarget, MIN_DIST } from './scene/engine';
import { checkExit, enterEmbodied, exitEmbodied, type EmbodyDeps } from './game/embody';
import { activityToClipKind, FigureLibrary } from './scene/figures';
import { NpcManager, WALK_SPEED, type NpcState } from './scene/npcs';
import { cellOf, clampToCell, keepAhead, splitDiagonal, stepDirection, walkDir, walkSpeedScale, type Cell } from './game/walk';
import { planRoute, type ClickRoute } from './game/clickmove';
import { talkTargetNear, type TalkCandidate } from './game/proximity';
import { idleRoomWalk, nearestRoomSwitch, type RoomWalkRoom, type RoomWalkState } from './game/roomwalk';
import { elevatorAt, elevatorTargetRoom, type ElevatorStop } from './game/elevator';
import { bodyRadius, clampAgainstWalls, wallSegments, type Segment } from './game/collide';
import { doorMarkers, type DoorMarker } from './game/doors';
import { getAudio } from './game/audio';
import {
  newFpsMeter, pushFrame, tierCounts, visibleVertices,
  type TierCounts, type TierSample,
} from './game/perfstats';
import { loadPrefs, PREFS_KEY } from './game/prefs';
import { fogQuadRects, SHOW_ALL_KEY, unknownCells } from './game/fog';
import type { MinimapCell } from './game/minimap';
import {
  ambientTerrainFor, emptyManifest, newTerrainSwitch, nightForMusic, pickAmbient,
  pickMusic, terrainSwitch, type AudioManifest,
} from './game/soundtrack';
import { applyLevelDisplay, applyNightGlow, applyRoomVisibility, applyTileFade, applyTileOcclusion, applyWallCulling, buildTile, gridSurfaceKind, gridToWorld, roomFigureScale, setSurfaceTextures, setTerrainGrid, terrainLiftAt, tileGroundY, CELL, type Tile } from './scene/tiles';
import { setModelEnvironment } from './scene/glbMaterials';
import { setPropLoadFocus } from './scene/propAssets';
import { mountScene, sceneFigureScale, SceneLibrary, setSceneModelTier } from './scene/sceneRecipe';
import {
  entryOfferNear, mayLeaveAcross, EXIT_EDGE_OF,
  type Edge, type EntryTile,
} from './game/enterLocation';
import { PathGrid } from './scene/pathfind';
import { grassTexture, seededRandom } from './scene/textures';
import { bootStatus, createHud, InfoPanel, OpenViewBadge } from './ui';
import { reportBootStage, setBootNote } from './game/boot';
import { mountHud, mountTitle } from './hud/mount';
import { gameActions, getGameState, perfEnabled, setGameState, setMinimap, setPerfStats, subscribeGameState, uiActions } from './hud/bus';
import type { ModelTier, ScenePayload } from './api';
import type { MapCharacter, WorldLocation, WorldMap } from './types';

const WORLDMAP_POLL_MS = 3000;
const ROOMS_POLL_MS = 4000;
/** How often the soundtrack driver reconsiders what should be playing (E4-T5).
 *  Every input of that decision moves on its own schedule (the night factor
 *  with the game-hour poll, the terrain with every step), and recomputing the
 *  whole answer is a handful of string comparisons — no need to be clever. */
const SOUNDTRACK_TICK_MS = 1000;

// --- The ONE open detail view (Etappe 3, plan-3d-lod-und-betreten.md) --------
// `openLocationId` (in startApp) is the singleton the whole view keys off:
// exactly ONE location shows its interior, and the crossfade (applyTileFade)
// is the TRANSITION, driven by open/close events — never by camera distance.
// The former INTERIOR_CAM_DIST 26 + "target within 0.75 cells" auto-open is
// gone; opening is explicit ("Hineinsehen"/"Betreten") or avatar-driven.
/** Camera farther out than this closes the open view (overview only). Must
 *  stay ABOVE the embodied EXIT_DIST 34 with headroom, so the open view can
 *  never close under an embodied avatar — 60 leaves 26 m of it. */
const CLOSE_CAM_DIST = 60;
/** Camera target panned this far off the open tile closes it too — the tile
 *  has left the view. Three cells is generous next to the old 0.75-cell
 *  auto-open gate: looking around inside stays free of surprises. */
const CLOSE_TARGET_DIST = CELL * 3;
/** "Hineinsehen" flies in to this distance — the old panel fly-to, kept. */
const OPEN_FLY_DIST = 15;
/** Far-view building models: hysteresis of the camera-distance tier choice
 *  (Nr. 5). Nearer than NEAR → `full`, farther than FAR → `low`; the 15 m
 *  band between them keeps a camera hovering at the line from thrashing
 *  swaps. Boot overview distance is 70 (> FAR), so the map starts light. */
const BUILDING_TIER_NEAR = 45;
const BUILDING_TIER_FAR = 60;
/** Tier re-evaluation cadence — second-scale like the talk target: a swap
 *  loads a GLB anyway, per-frame checks would buy nothing. */
const LOD_TICK_MS = 1000;
/** How often the performance readout is refreshed (Etappe 5). Three to four
 *  updates a second: fast enough that a stutter shows up while it is felt,
 *  slow enough that the digits stay readable instead of blurring. */
const PERF_UI_MS = 300;
/** How often the minimap slice is reconsidered (Etappe 5, task 3). Four times
 *  a second: the picture only changes when the avatar crosses a cell boundary
 *  or the camera turns, both of which are slower than that — and a slice
 *  published per frame would re-render React sixty times a second for a dot
 *  that has not moved. Nothing is published unless something changed. */
const MINIMAP_MS = 250;
/** How far past an opening the "Betreten" walk-in aims, in world metres —
 *  just inside the cell, so the figure visibly crosses the boundary. */
const OPENING_WALK_IN_M = 1.5;

// --- Doorway markers (E3 acceptance: "you cannot see the doors") ------------
//
// A door is a GAP in the wall segments (§ B1) — the server emits no door
// geometry, and a hole between two wall pieces does not read as a way through.
// So the game layer lays a flat threshold into each gap. This is an OVERLAY,
// exactly like the event pins and the selection ring: nothing here touches the
// recipe, the diorama or any shared render code, and `game/doors.ts` (pure
// maths, hand-checked in scripts/smoke_walk_math.mjs) says WHERE the gaps are.
//
// One unit quad and one material for every marker of every tile: a threshold
// differs only in position, direction and size, so per-marker geometry would
// buy nothing. Pre-rotated into the XZ plane, so a marker only needs the
// heading (`rotation.y`) — with `rotation.x` also set, the two Euler angles
// would compose and the quad would stand up.
const DOOR_MARK_GEO = new THREE.PlaneGeometry(1, 1).rotateX(-Math.PI / 2);
/** The gold of the UI (`--gold` of the HUD), at the opacity of a hint. */
const DOOR_MARK_MAT = new THREE.MeshBasicMaterial({
  color: 0xf2d98c, transparent: true, opacity: 0.35, depthWrite: false,
});
/** Depth of the threshold ACROSS the wall, as a share of the doorway's width —
 *  never thinner than the wall it fills, or it would vanish inside it. */
const DOOR_MARK_DEPTH = 0.3;

/**
 * "Zoom to" a figure, for a figure drawn at scale 1. With the camera's 45°
 * vertical FOV the visible height is 2·d·tan(22.5°) ≈ 0.828·d, so 4.5 m frames
 * 3.7 m of world and a 1.70 m character covers ~46% of the picture: full
 * height with air above and below. The distance is multiplied by the scale the
 * figure is actually DRAWN at, so an indoor figure (scale ~0.3, ~0.5 m tall)
 * gets the same framing at ~1.35 m instead of staring at it from 12 m away.
 */
const ZOOM_TO_BASE_DIST = 4.5;
/** Upper clamp for the scaled zoom-to: a giant figure must not push the camera
 *  past the old fixed distance, and 12 < EXIT_DIST (34) keeps a zoom-to from
 *  ever tripping the embodied-mode exit. */
const ZOOM_TO_MAX_DIST = 12;

const app = document.getElementById('app')!;

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/**
 * Where a boot request reports that it is still waiting for the server. There
 * are two of them and they are NOT the same surface: before the title screen
 * exists there is only the bare status line of `ui.bootStatus`, afterwards the
 * message belongs on the title screen itself (`game/boot.ts`), which is on top
 * of everything at that point.
 */
interface WaitSink {
  /** the server did not answer; the next attempt runs in `seconds` */
  waiting(seconds: number): void;
  /** it answered — take the message away */
  clear(): void;
}

/**
 * Repeat a start request until the server answers.
 *
 * The backend restart (start.sh) only hits port 8000; the Vite proxy answers
 * with 500 meanwhile, so exactly the boot queries fail. The client used to die
 * of that for good: `startApp` threw, nobody caught it, the page stayed empty
 * and never recovered by itself — a reload during the restart looked like a
 * crash. Now the boot waits with a visible status and catches itself as soon
 * as the server is back.
 */
async function retryBoot<T>(what: string, fn: () => Promise<T>,
                            sink: WaitSink): Promise<T> {
  for (let attempt = 0; ; attempt++) {
    try {
      const out = await fn();
      sink.clear();
      return out;
    } catch (e) {
      const wait = Math.min(15_000, 1000 * 2 ** Math.min(attempt, 4));
      console.warn(`[boot] ${what} failed (attempt ${attempt + 1}) — `
        + `retrying in ${wait / 1000} s`, e);
      sink.waiting(Math.round(wait / 1000));
      await sleep(wait);
    }
  }
}

/** The wait sink of the title screen — used for everything `startApp` fetches,
 *  because from then on the title screen IS the loading screen. */
const titleSink: WaitSink = {
  waiting: (seconds) => setBootNote({ kind: 'retry', seconds }),
  clear: () => setBootNote(null),
};

async function boot() {
  // `bootStatus` survives for exactly ONE job: the reachability check below
  // runs BEFORE any React exists — the title screen cannot be mounted before
  // we know whether it has to ask for a login — and a server that is down at
  // that moment must still say so instead of leaving a black page. Everything
  // after this point reports through the title screen (`titleSink`).
  const status = bootStatus();
  // Keep reachability and authentication apart: an unreachable server is NOT
  // "not signed in" — otherwise the client shows a login form whose submit is
  // bound to fail.
  const auth = await retryBoot('auth status', () => api.authStatus(), {
    waiting: (seconds) => status.set(
      `The server is not answering — trying again in ${seconds} s…`),
    clear: () => status.remove(),
  });

  const start = (username: string, role: string) => {
    void startApp(username, role).catch((e) => {
      console.error('[boot] start failed', e);
      setBootNote({ kind: 'failed' });
    });
  };

  // The title screen replaces the old vanilla login overlay AND the loading
  // gap behind it: it stays up while `startApp` builds the world underneath
  // and fades once `game/boot.ts` has all four stages.
  mountTitle({
    needsLogin: !(auth.authenticated && auth.user),
    // The login click is the guaranteed user gesture — the one moment a
    // browser lets an AudioContext start. Nothing plays here; audio output is
    // merely no longer blocked afterwards.
    onLogin: async (u, p) => {
      void getAudio().unlock();
      const user = await api.login(u, p);
      start(user.username, user.role);
    },
    // Same gesture for the session that is already signed in. This case used
    // to have no click at all: the old boot went straight into `startApp` and
    // the audio context stayed suspended for the whole session.
    onEnter: () => {
      void getAudio().unlock();
      start(auth.user!.username, auth.user!.role);
    },
  });
}

async function startApp(username: string, role: string) {
  // --- Fog of war (Etappe 5): the ONE switch that decides which view is
  // fetched. Only an administrator may see the unfiltered map — a stored `1`
  // in anybody else's browser is ignored here (the server would answer 403,
  // and a client that asked would break its own boot for a setting it is not
  // allowed to have). It is read once: the menu applies a change by reloading.
  const isAdmin = role === 'admin';
  const showAll = isAdmin && localStorage.getItem(SHOW_ALL_KEY) === '1';
  const engine = new Engine(app);
  setModelEnvironment(engine.modelEnv);
  (window as unknown as { __engine: Engine }).__engine = engine;   // Debug-Hook (Tageszeit testen)
  (window as unknown as { __THREE: typeof THREE }).__THREE = THREE; // Debug-Hook (Szene vermessen)
  const figures = new FigureLibrary();
  // figures.load() wirft nie (Manifest/Clips fangen selbst) und darf NICHT
  // wiederholt werden — ein zweiter Lauf würde die Modelle doppelt einhängen.
  const figuresReady = figures.load();
  const [allLocs, firstMap, surfaces] = await retryBoot('world data', () => Promise.all([
    api.getLocations(),
    api.getWorldMap(showAll),
    api.getSurfaceTextures(),
  ]), titleSink);
  reportBootStage('world');
  await figuresReady;
  reportBootStage('figures');
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

  // Logging out reloads, and that is the whole way back to the title: the
  // reload runs `boot()` again, `authStatus` now says "not signed in" and the
  // title screen comes up with its login form. Tearing the engine, the pollers
  // and the three roots down by hand to reach the same state would be a second
  // shutdown path with nothing to gain. ONE flow, two doors: the top bar's
  // logout and the game menu's "Back to title" (E4-T4).
  // The reload runs in a `finally`: a logout that fails (the server is down —
  // exactly the moment one wants back to the title screen) must not swallow
  // the way back and leave the button looking dead. A cookie that survives is
  // no loss either, the reload lands on the title screen with the session it
  // still has.
  const backToTitle = async () => {
    try {
      await api.logout();
    } finally {
      location.reload();
    }
  };
  gameActions.backToTitle = () => void backToTitle();
  const hud = createHud({ username, avatar: firstMap.avatar, onLogout: backToTitle });
  mountHud({ username, avatar: firstMap.avatar, role });   // React HUD island (E2-T5)
  npcs.setAvatar(firstMap.avatar);

  // Worldmap ist autoritativ für Grid/Passable/Template; /world/locations liefert
  // Räume, Beschreibung, entry_room. Templates (Vorlagen für Klone) nicht rendern.
  const detailById = new Map(allLocs.map((l) => [l.id, l]));
  /**
   * The placeable locations of a worldmap snapshot. ONE function, because
   * since the fog of war (Etappe 5) locations arrive not only at boot: a place
   * the avatar discovers appears in a later poll and has to become a tile the
   * very same way — same template filter, same merge of map entry and detail.
   */
  function placeableOf(map: WorldMap, details: Map<string, WorldLocation>): WorldLocation[] {
    const templateIds = new Set(
      map.locations.map((l) => l.template_location_id).filter(Boolean) as string[]
    );
    return map.locations
      .filter((l) => l.grid_x != null && l.grid_y != null && !templateIds.has(l.id))
      .map((l) => {
        const detail = details.get(l.id) ?? details.get(l.template_location_id || '');
        return {
          ...detail,
          ...l,
          rooms: detail?.rooms ?? [],
          description: detail?.description ?? '',
          entry_room: detail?.entry_room,
        } as WorldLocation;
      });
  }
  /** Every location that HAS a tile. Grows while the fog lifts
   *  (`revealLocations` below) — the derived structures are rebuilt from this
   *  one list. */
  const placeable: WorldLocation[] = placeableOf(firstMap, detailById);

  // Boden + Kacheln
  //
  // The frame comes from `grid_bounds` (§ A12) and NOT from the delivered
  // locations: those are only what the avatar knows, so a map centred on them
  // would jump sideways with every place discovered. The bounds are computed
  // over ALL placed locations and stay still. Fallback (no location placed at
  // all, `null`): the old min/max over what we have.
  const xs = placeable.map((l) => l.grid_x!), ys = placeable.map((l) => l.grid_y!);
  const center = firstMap.grid_bounds
    ? gridToWorld((firstMap.grid_bounds.min_x + firstMap.grid_bounds.max_x) / 2,
      (firstMap.grid_bounds.min_y + firstMap.grid_bounds.max_y) / 2)
    : gridToWorld((Math.min(...xs) + Math.max(...xs)) / 2, (Math.min(...ys) + Math.max(...ys)) / 2);
  const groundTex = grassTexture();
  groundTex.repeat.set(60, 60);
  const ground = new THREE.Mesh(
    new THREE.PlaneGeometry(600, 600),
    new THREE.MeshStandardMaterial({ map: groundTex, roughness: 1 })
  );
  ground.rotation.x = -Math.PI / 2;
  ground.position.copy(center);
  // DEUTLICH unter alles Kachel-Eigene (Platten 0,04, Detail-Backstop −0,05,
  // Relief-Senken): diese Welt-Grasebene lag bei y 0 KOPLANAR mit den
  // Etage-0-Zonenplatten der Detailszenen und gewann das Z-Fighting in
  // organischen Flecken — die „grünen Stellen", die jede Platten-Korrektur
  // überlebten (Raster-Raycast 2026-08-03: Treffer „Mesh<Scene", Canvas-
  // Gras). Jede Location zeigt ihren eigenen Terrain-Boden; das Gras hier
  // ist nur noch der Untergrund ZWISCHEN den Kacheln (User-Vorgabe: die
  // grüne Fallback-Fläche gehört nirgendwohin, wo Terrain konfiguriert ist).
  ground.position.y = -0.5;
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
  /** The known cells for the minimap (Etappe 5, task 3), out of the SAME list
   *  and the SAME surface-kind function the tiles are built from — so the map
   *  in the corner can never show a colour the world does not have. Rebuilt
   *  only when the set of known locations changes, which is what lets the
   *  4 Hz publisher below hand the very same array out again. */
  let minimapCells: MinimapCell[] = [];
  /** Counts every rebuild of the cells above. The publisher compares it
   *  instead of the array's contents: the list is a few hundred entries at
   *  most, but comparing it four times a second for a picture that changes
   *  once an hour would be work for nothing. */
  let minimapCellsRev = 0;
  /** The minimap cells out of the SAME kind list the tiles are built from —
   *  taking the terrain from anywhere else is how the two pictures drift. */
  function setMinimapCells(kinds: { gx: number; gy: number; kind: string }[]) {
    minimapCells = kinds.map((k) => ({ x: k.gx, y: k.gy, terrain: k.kind }));
    minimapCellsRev += 1;
  }
  /** Publish the surface-kind neighbourhood of every known location. Called at
   *  boot and again whenever a discovered place joins the map — a new cell is
   *  a new neighbour for the coast blends around it. */
  const publishTerrainGrid = () => {
    const kinds = placeable.map(
      (l) => ({ gx: l.grid_x!, gy: l.grid_y!, kind: gridSurfaceKind(l) }));
    setTerrainGrid(kinds);
    setMinimapCells(kinds);
  };
  publishTerrainGrid();

  // Szenen-Rezept (Vertrag Teil B): der Server liefert die komplette Szene
  // einer Location als fertige Primitive + Platzierungs-Specs. Wo es eins
  // gibt, baut der Client NICHTS selbst mehr (kein Grundriss, keine
  // Öffnungs-Aufteilung, keine eigenen Konstanten/Farben) — 404 = Legacy-Fall,
  // dann bleibt der prozedurale Pfad unverändert.
  // Vor dem ersten Kachelbau holen, damit jede Kachel gleich im richtigen
  // Modus entsteht.
  const scenes = new SceneLibrary();
  await scenes.prime(placeable.map((l) => l.id));
  reportBootStage('scenes');

  const tiles = new Map<string, Tile>();
  // Numeric on-screen probe for remote diagnosis — inert without ?debug3d=1.
  initDebug3d(engine, tiles);

  // --- The open detail view: ONE explicit singleton (Etappe 3) --------------
  // Every downstream consumer (interior visibility, labels, roof fade, door
  // thresholds, NPC room figures, ground hole, neighbour occlusion, elevator
  // prompt, figure scale) keeps reading `tile.fade`/`fadeTarget` — only the
  // fade TARGET now comes from here instead of from camera geometry.
  let openLocationId: string | null = null;
  /** A tile with something to reveal: a mounted interior on a building or a
   *  detail-mode area location — the same condition the fade loop gates on. */
  const openable = (tile: Tile) =>
    !!tile.interior && (tile.isBuilding || !!tile.modelIsShellArea);
  const badge = new OpenViewBadge();
  /** The floating close control shows exactly while a view is open in the
   *  OVERVIEW. Embodied it stays hidden: there the avatar's location owns the
   *  state and an explicit close would be reopened the very next frame. */
  function refreshOpenBadge() {
    const tile = openLocationId ? tiles.get(openLocationId) : null;
    if (tile && getGameState().mode !== 'embodied') badge.show(tile.loc.name);
    else badge.hide();
  }
  function openLocation(id: string) {
    if (openLocationId === id) return;
    const tile = tiles.get(id);
    if (!tile || !openable(tile)) return;
    // Opening one location closes the current one — the crossfade of both
    // runs in the frame hook off their diverged fade targets.
    openLocationId = id;
    refreshOpenBadge();
  }
  function closeOpenLocation() {
    if (openLocationId === null) return;
    openLocationId = null;
    refreshOpenBadge();
  }
  badge.onClose = () => closeOpenLocation();
  subscribeGameState(refreshOpenBadge);

  // --- Resolution tiers (Etappe 3, Nr. 4 + 5) -------------------------------
  // WHICH tier a model group shows is pure view state and decided HERE; the
  // resolution to a URL (missing tier → best existing) is pickVariant's, and
  // the in-place swap is setSceneModelTier's. Two drivers:
  //  - `building` (far-view models): camera distance with hysteresis,
  //  - `interior` (dioramas + props): area-detail locations carry `low`
  //    while closed and `full` while open; building interiors stay `full`
  //    (they are invisible while closed — nothing to save).
  const buildingTierByLoc = new Map<string, ModelTier>();
  const interiorTierByLoc = new Map<string, ModelTier>();
  function wantedBuildingTier(tile: Tile): ModelTier {
    const d = engine.camera.position.distanceTo(tile.center);
    const cur = buildingTierByLoc.get(tile.loc.id) ?? 'low';
    if (cur === 'low' && d < BUILDING_TIER_NEAR) return 'full';
    if (cur === 'full' && d > BUILDING_TIER_FAR) return 'low';
    return cur;
  }
  function wantedInteriorTier(locId: string, scene: ScenePayload | null | undefined): ModelTier {
    return scene?.area_detail && openLocationId !== locId ? 'low' : 'full';
  }
  function tickModelTiers() {
    for (const tile of tiles.values()) {
      if (!tile.placedModels) continue;   // no mounted scene, nothing to swap
      const b = wantedBuildingTier(tile);
      if (buildingTierByLoc.get(tile.loc.id) !== b) {
        buildingTierByLoc.set(tile.loc.id, b);
        void setSceneModelTier(tile, 'building', b);
      }
      const i = wantedInteriorTier(tile.loc.id, scenes.get(tile.loc.id));
      if (interiorTierByLoc.get(tile.loc.id) !== i) {
        interiorTierByLoc.set(tile.loc.id, i);
        void setSceneModelTier(tile, 'interior', i);
      }
    }
  }
  // --- Performance readout (Etappe 5, plan-3d-lod-und-betreten.md) ---------
  //
  // Three sources, three cadences, and the split is the whole point:
  //  - FPS is sampled EVERY frame (a rate averaged from anything slower is
  //    not a frame rate), but that is one array push — `game/perfstats.ts`.
  //  - The vertex sum and the tier split need a walk over the scene graph and
  //    the placement ledgers. Those run on the SAME ~1 Hz tick as the tier
  //    choice: a traversal per frame would distort the very figure it
  //    measures.
  //  - `renderer.info` is free to read and is picked up by the publisher.
  // Nothing is measured at all while the readout is off (`perfEnabled`) —
  // a display nobody looks at may not cost a frame.
  let fpsMeter = newFpsMeter();
  let fpsNow = 0;
  engine.addFrameHook((dt) => {
    if (perfEnabled()) { fpsNow = pushFrame(fpsMeter, dt); return; }
    // Switched off: throw the window away once, so switching it on again
    // starts measuring now instead of showing a second from another minute.
    if (fpsMeter.samples.length) { fpsMeter = newFpsMeter(); fpsNow = 0; }
  });
  /** Last heavy measurement, refreshed on the LOD tick. */
  let perfHeavy = { vertices: 0, tiers: { full: 0, low: 0 } as TierCounts };
  function measurePerfHeavy() {
    const placed: TierSample[] = [];
    for (const tile of tiles.values()) {
      for (const rec of tile.placedModels ?? []) {
        placed.push({ variants: rec.spec.variants, url: rec.url });
      }
    }
    perfHeavy = { vertices: visibleVertices(engine.scene), tiers: tierCounts(placed) };
  }
  // The publisher is faster than the measurement on purpose: the tier numbers
  // may stand for a second (they change about that often), but an FPS reading
  // that only moved once a second would feel broken while the picture stutters.
  setInterval(() => {
    if (!perfEnabled()) return;
    const info = engine.renderer.info;
    setPerfStats({
      fps: fpsNow,
      // Read outside the frame hook, so these are the counters of the frame
      // that was last rendered — which is exactly what should be displayed.
      triangles: info.render.triangles,
      calls: info.render.calls,
      vertices: perfHeavy.vertices,
      geometries: info.memory.geometries,
      textures: info.memory.textures,
      tiers: perfHeavy.tiers,
    });
  }, PERF_UI_MS);

  setInterval(() => {
    tickModelTiers();
    if (perfEnabled()) measurePerfHeavy();
  }, LOD_TICK_MS);

  /** Threshold quads per location, one child group per storey. They live in
   *  `engine.scene` and not in `tile.group` on purpose: a rebuild throws the
   *  tile group away wholesale, and an overlay that is rebuilt from the SAME
   *  payload wants its own bookkeeping — the same reason the event pins and the
   *  wall-segment cache keep theirs. */
  const doorMarks = new Map<string, THREE.Group>();

  function dropDoorMarks(locId: string) {
    const old = doorMarks.get(locId);
    if (!old) return;
    engine.scene.remove(old);
    doorMarks.delete(locId);
  }

  /**
   * Height the threshold lies at. `baseY` is the foot of the WALL the gap sits
   * in and always exists; a room's own floor may be higher, because it is a
   * sampled diorama plate and not the wall's base (`sampleRoomWalkables` lifts
   * `roomCenters` onto it, the same number the avatar walks at). The higher of
   * the two is the floor one would actually step on, so the quad cannot sink
   * into it. The lift on top scales with the scene: at Willowbrook's k = 0.21 a
   * whole storey is 0.63 m, and a fixed centimetre offset there is a step.
   */
  function doorMarkY(tile: Tile, m: DoorMarker, k: number): number {
    let y = m.baseY;
    for (const id of m.roomIds) {
      const c = tile.roomCenters.get(id);
      if (c && c.y > y) y = c.y;
    }
    return y + 0.02 * Math.max(k, 0.35);
  }

  /** (Re)build the thresholds of one tile from its payload. Called after every
   *  mount — the mount is what fills `roomCenters` with the sampled floor the
   *  markers are laid on. */
  function buildDoorMarks(tile: Tile, scene: ScenePayload) {
    dropDoorMarks(tile.loc.id);
    if (!tile.isBuilding) return;
    // The payload is TILE-LOCAL (world metres around the tile centre) while the
    // scene is absolute — the C1 lesson of the collision round, where segments
    // sat 45 m from the figure. `doorMarkers` bakes the centre in for us.
    const origin = { x: tile.center.x, z: tile.center.z };
    const root = new THREE.Group();
    root.visible = false;
    for (const { level } of scene.levels) {
      const marks = doorMarkers(scene, level, origin);
      if (!marks.length) continue;
      // Wall thickness of this storey — the floor is the same for every wall of
      // a recipe, so the first one answers for all of them.
      const thickness = scene.walls.find((w) => w.level === level)?.thickness ?? 0;
      const storey = new THREE.Group();
      storey.userData.level = level;
      for (const m of marks) {
        const mesh = new THREE.Mesh(DOOR_MARK_GEO, DOOR_MARK_MAT);
        mesh.scale.set(m.width, 1, Math.max(m.width * DOOR_MARK_DEPTH, thickness));
        // World +x turned onto the wall direction: a rotation by φ about Y maps
        // (1,0,0) to (cos φ, 0, -sin φ), so φ = atan2(-along.z, along.x).
        mesh.rotation.y = Math.atan2(-m.along.z, m.along.x);
        mesh.position.set(m.mid.x, doorMarkY(tile, m, scene.k), m.mid.z);
        // Late, so the quad is not swallowed by the fading walls it lies
        // between, and unpickable — the selection-ring lesson: an overlay that
        // catches the ray steals the click that was meant for the tile.
        mesh.renderOrder = 3;
        mesh.raycast = () => {};
        storey.add(mesh);
      }
      root.add(storey);
    }
    if (!root.children.length) return;
    engine.scene.add(root);
    doorMarks.set(tile.loc.id, root);
  }

  /** Mount a payload and lay its thresholds afterwards. `finally` and not
   *  `then`: the markers come from the payload alone, so a mount that fell over
   *  (a model that would not load) still gets its doors — and the rejection
   *  stays unhandled exactly as it was before. The mount loads the tiers the
   *  view wants RIGHT NOW (and pins the tier maps to them, so the 1 Hz tick
   *  issues no redundant swap straight after). */
  function mountWithDoors(tile: Tile, scene: ScenePayload) {
    const building = wantedBuildingTier(tile);
    const interior = wantedInteriorTier(tile.loc.id, scene);
    buildingTierByLoc.set(tile.loc.id, building);
    interiorTierByLoc.set(tile.loc.id, interior);
    void mountScene(tile, scene, { building, interior }).finally(() => {
      if (tiles.get(tile.loc.id) === tile) buildDoorMarks(tile, scene);
    });
  }

  /** Build a location's tile and hang it in the scene. Boot walks every
   *  placeable location through here, the reveal path (Etappe 5) the newly
   *  discovered ones — the pickables are refreshed by the CALLER, once per
   *  batch. */
  function addTile(loc: WorldLocation) {
    const tile = buildTile(loc);
    tiles.set(loc.id, tile);
    engine.scene.add(tile.group);
    const scene = scenes.get(loc.id);
    if (scene) mountWithDoors(tile, scene);
  }
  for (const loc of placeable) addTile(loc);
  engine.setPickables([...tiles.values()].map((t) => t.group));

  // --- The veil over what the avatar does not know (Etappe 5) --------------
  //
  // The server decides WHAT is known (§ A12) and sends only that; here the
  // rest of the frame is covered. WHICH cells that are is pure maths in
  // `game/fog.ts` (hand-checked in scripts/smoke_walk_math.mjs) — this is only
  // the mesh side: one quad per row run, all of them in ONE group that is
  // thrown away and built again whenever the set of known locations moves.
  // Rebuilding wholesale is what keeps it honest: there is no incremental
  // state that could end up showing a veil over a place one already stands in.
  //
  // It is an OVERLAY like the door thresholds: unlit (a veil that took the
  // sun would read as a surface), never written into the depth buffer, and
  // unpickable — a click belongs to the world underneath.
  const FOG_MAT = new THREE.MeshBasicMaterial({
    color: 0x080b12, transparent: true, opacity: 0.82, depthWrite: false,
  });
  /** A hand's breadth above the world's grass plane: unknown cells carry no
   *  tile, so that plane is the only thing under the veil. */
  const FOG_Y = ground.position.y + 0.05;
  const fogGroup = new THREE.Group();
  engine.scene.add(fogGroup);
  /** The frame and the switch of the CURRENT payload — both move only with a
   *  poll, and `fogged: false` (the admin's unfiltered view) means there is no
   *  veil at all. */
  let fogBounds = firstMap.grid_bounds;
  let fogged = firstMap.fogged;
  /** What the veil currently standing was built from. The poll runs every
   *  three seconds and nearly always finds the same three inputs — rebuilding
   *  regardless would throw away and re-allocate a dozen geometries per poll
   *  for a picture that does not change. `null` until the first build: every
   *  string is a possible key, so the sentinel must not be one. */
  let fogKey: string | null = null;
  function rebuildFog() {
    const frame = fogBounds
      ? `${fogBounds.min_x},${fogBounds.min_y},${fogBounds.max_x},${fogBounds.max_y}` : '';
    const key = `${fogged}|${frame}|${[...tiles.keys()].sort().join(' ')}`;
    if (key === fogKey) return;
    fogKey = key;
    for (const child of fogGroup.children) {
      (child as THREE.Mesh).geometry.dispose();
    }
    fogGroup.clear();
    if (!fogged) return;
    const known = [...tiles.values()].map((t) => ({ x: t.loc.grid_x!, y: t.loc.grid_y! }));
    for (const r of fogQuadRects(unknownCells(fogBounds, known))) {
      const quad = new THREE.Mesh(
        new THREE.PlaneGeometry(r.w * CELL, r.h * CELL).rotateX(-Math.PI / 2), FOG_MAT);
      // A rectangle covers the cells x … x+w-1, and a cell's centre is its grid
      // position: the middle therefore sits half a cell run further along.
      quad.position.set((r.x + (r.w - 1) / 2) * CELL, FOG_Y, (r.y + (r.h - 1) / 2) * CELL);
      quad.renderOrder = 1;   // under the thresholds (3) and the pins
      quad.raycast = () => {};
      fogGroup.add(quad);
    }
  }
  rebuildFog();
  // Last stage: the map stands and can be clicked. The title screen fades on
  // this one — the scene models behind the tiles keep streaming in afterwards
  // (`mountWithDoors` is deliberately not awaited), and holding the screen
  // until the last GLB is decoded would mean staring at a bar over a world
  // that is already finished enough to look at.
  reportBootStage('tiles');

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
    l.map3d, l.entry_room, l.terrain || '', l.surface_kind || '',
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
    // The thresholds go with it, unconditionally: a scene that turned 404
    // (layout deleted) is never mounted again, so nothing else would clear
    // them and they would hang in the air over a procedural tile.
    dropDoorMarks(loc.id);
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
    if (scene) mountWithDoors(tile, scene);
    engine.setPickables([...tiles.values()].map((t) => t.group));
  }
  // Szenen-Signatur bewegt sich (Layout, map3d, Modell-Meta, Prop-Sidecar) →
  // Kachel neu bauen. Wird eine Szene zu 404 (Layout gelöscht), bleibt genau
  // die prozedurale Kachel übrig — es gibt dann nichts mehr aufzuklappen.
  /** Blocking wall lines per location and storey, for the avatar's collision
   *  (game/collide.ts). Built from the payload, so it is cached per
   *  `(location, storey)` and thrown away in exactly ONE place: `onScene`
   *  below, the only moment a payload is replaced (a moved scene signature),
   *  and the same moment the tile is rebuilt from it. Nothing else can change
   *  a wall — the walls are the server's. */
  const wallCache = new Map<string, Map<number, Segment[]>>();

  scenes.onScene = (locId) => {
    wallCache.delete(locId);
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
        // The neighbourhood grid is built from `surface_kind`, the tile style
        // from `terrain` — a change in EITHER has to repaint.
        if ((detail.terrain || '') !== (tile.loc.terrain || '')
            || (detail.surface_kind || '') !== (tile.loc.surface_kind || '')) {
          terrainChanged = true;
        }
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
          surface_kind: detail.surface_kind ?? tile.loc.surface_kind,
        }]);
      }
      if (terrainChanged) {
        const nextLoc = new Map(dirty.map(([tl, loc]) => [tl.loc.id, loc]));
        const kinds = [...tiles.values()].map((tl) => {
          const loc = nextLoc.get(tl.loc.id) ?? tl.loc;
          return { gx: loc.grid_x!, gy: loc.grid_y!, kind: gridSurfaceKind(loc) };
        });
        setTerrainGrid(kinds);
        // The minimap follows the same repaint: a terrain edited in the admin
        // must change the colour in the corner, not only the ground.
        setMinimapCells(kinds);
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
  //
  // The grid is IMMUTABLE by design (it caches its answers, see pathfind.ts),
  // so a map that grew gets a NEW one — the reason this binding is a `let`:
  // a discovered location adds a cell, and every user of the grid has to be
  // looking at the same one.
  let pathGrid = publishPathGrid();
  function publishPathGrid(): PathGrid {
    const grid = new PathGrid(
      placeable.map((l) => ({
        x: l.grid_x!, y: l.grid_y!,
        passable: !!(l.passable || l.template_location_id),
      }))
    );
    npcs.setPathGrid(grid);
    // Debug-Hooks: laufendes Grid + Klasse, um Wegfindung zu vermessen
    (window as unknown as { __pathGrid: PathGrid }).__pathGrid = grid;
    (window as unknown as { __PathGrid: typeof PathGrid }).__PathGrid = PathGrid;
    return grid;
  }
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
    panel.show(tile.loc, chars, lastMap?.events_by_location?.[id] ?? [], roomOf,
      { openable: openable(tile), open: openLocationId === id });
  };
  panel.onZoomTo = (id) => {
    const tile = tiles.get(id);
    if (tile) engine.flyTo(tile.center.clone(), OPEN_FLY_DIST);
  };
  // "Hineinsehen" (Etappe 3): the old fly-to stays part of it — fly in AND
  // open the detail view. Pure view state, no server call.
  panel.onLookInside = (id) => {
    const tile = tiles.get(id);
    if (!tile) return;
    engine.flyTo(tile.center.clone(), OPEN_FLY_DIST);
    openLocation(id);
  };
  panel.onCloseView = () => closeOpenLocation();

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
  gameActions.sayBubble = (name, text) => npcs.say(name, text);
  gameActions.zoomTo = (name) => {
    // While a follow target is set (embodied mode) the camera belongs to the
    // followed figure: a fly-to would be dragged back by the chase every
    // frame and only make the view judder. The button stays visible — it is
    // simply without effect until the player leaves the mode.
    if (engine.follow) return;
    const p = npcs.positionOf(name);
    if (!p) return;
    // The drawn scale, not a nominal one: indoors a metre is `scale` human
    // metres, so both the distance and the aim point have to follow it.
    const scale = npcs.scaleOf(name) ?? 1;
    // Aim at the middle of the body, not at the feet — `positionOf` returns the
    // root, i.e. ground level, and from this close the figure would run out of
    // the top of the frame. Half of a 1.70 m character is 0.85 m.
    p.y += 0.85 * scale;
    engine.flyTo(p, THREE.MathUtils.clamp(ZOOM_TO_BASE_DIST * scale, MIN_DIST, ZOOM_TO_MAX_DIST));
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
  //
  // OVERLAYS OWN ESCAPE: an open lightbox (`.lb-overlay`), a portalled modal
  // (`.ga-modal-backdrop`, e.g. the gift/gallery pickers) or the gallery's own
  // detail view (`.player-gallery-overlay`) closes on Esc itself,
  // and one key press must not do both — close the picture AND throw the player
  // out of the mode. Listening in the CAPTURE phase is what makes the check
  // reliable: the overlay's own window listener runs in the bubble phase, and
  // React may already have unmounted the node by the time a second bubble
  // listener sees the event.
  window.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape' || isTypingTarget(e)) return;
    if (document.querySelector(
      '.lb-overlay, .ga-modal-backdrop, .player-gallery-overlay')) return;
    // The storey choice comes FIRST: it is part of the HUD's bottom stack and
    // not a document.body overlay, so the guard above cannot see it — and Esc
    // must close the choice one has just opened, not throw the player out of
    // the mode with it.
    if (getGameState().elevatorOpen) {
      setGameState({ elevatorOpen: false });
      return;
    }
    // Then the game menu (E4-T4), for the same reason and one step later: it
    // is a panel of the HUD, so the overlay guard above cannot see it, and it
    // is opened DELIBERATELY — a key that closed the menu and left the mode in
    // one press would answer a question nobody asked. `closeMenu` says whether
    // there was anything to close, so the key falls through when there was not.
    if (uiActions.closeMenu?.()) return;
    if (getGameState().mode === 'embodied') exitEmbodied(embody);
  }, true);

  // M is the menu key — the game menu opens and closes with it, in both modes.
  // Guarded like Esc and F: inside a form field it types an m. Modifier
  // combinations belong to the browser (Ctrl+M, Cmd+M are window commands).
  window.addEventListener('keydown', (e) => {
    if (e.key.toLowerCase() !== 'm' || isTypingTarget(e)) return;
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    uiActions.toggleMenu?.();
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
  /** Figures the placement pass left INVISIBLE (a storey that is not shown, a
   *  room whose interior is closed). Rewritten by every `computeNpcStates`
   *  run; read by the talk target, because nobody can be addressed through a
   *  wall one cannot even see. */
  const hiddenChars = new Set<string>();

  // AV3D-8: room_id kommt direkt mit der Worldmap; dazu die Clip-Set-Kette
  function takeRoomsFrom(map: WorldMap) {
    for (const c of map.characters) {
      // An empty room_id is the location's GROUND, not a missing answer — it
      // must overwrite whatever room this character was in before, or the
      // client keeps believing it stands in a room of the PREVIOUS location.
      roomOf.set(c.name, c.room_id ?? '');
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
    let map: WorldMap;
    try {
      map = await api.getWorldMap(showAll);
      lastMap = map;
      mapStamp += 1;
      hud.setOnline(true);
      takeRoomsFrom(map);
      updatePins(map);
      refreshSelection(map);
      reconcileAvatarCell(map);   // server moved the avatar? (E3-T3)
    } catch {
      hud.setOnline(false);
      return;
    }
    // The fog of war (Etappe 5) moves WHILE one plays: a place the avatar has
    // just discovered is simply in the payload from one poll to the next. The
    // frame and the switch travel with it — the frame is computed unfiltered
    // and does not move, but a world can gain a location at any time.
    fogBounds = map.grid_bounds;
    fogged = map.fogged;
    rebuildFog();   // a no-op unless the frame, the switch or the known set moved
    // The trigger asks the SAME question the reveal answers — `placeableOf`,
    // not a hand-written filter next to it. A cheaper test that forgot the
    // template rule would fire on every single poll in a world whose template
    // location is itself placed, and each shot would refetch all of
    // /world/locations to build nothing.
    if (placeableOf(map, detailById).some((l) => !tiles.has(l.id))) {
      // Deliberately not awaited: the reveal fetches and mounts, and the poll
      // must not be held up by it (it guards itself against a second run).
      void revealLocations(map);
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

  // Windows glow at night — and the soundtrack changes with the same factor.
  /** Installed further down by the soundtrack driver (E4-T5), which needs the
   *  avatar and the cell lookup; null until then, so an early day/night change
   *  simply lights the windows. */
  let updateSoundtrack: (() => void) | null = null;
  engine.onDayNight = (night) => {
    for (const tile of tiles.values()) applyNightGlow(tile, night);
    updateSoundtrack?.();
  };

  // Time of day of the world -> lighting (kept up to date every 60 s)
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
    hiddenChars.clear();
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
            // Relief (§ B1 Nr. 14): die Raum-Mitte ist EINE Höhe, der Boden
            // unter der versetzten Figur ist es nicht. Als DIFFERENZ zur
            // Mitte angesetzt, damit es egal bleibt, ob die Mitte selbst
            // schon auf dem abgetasteten Hang liegt — sonst zählte die
            // Hebung doppelt. Marker- und Spot-Positionen bleiben außen vor:
            // die kommen gehoben vom Server bzw. vom Strahl auf die bereits
            // drapierte Platte.
            const rise = terrainLiftAt(tile, pos.x, pos.z)
              - terrainLiftAt(tile, roomCenter.x, roomCenter.z);
            if (rise) pos.setY(pos.y + rise);
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
        const wrongStorey = !!inRoom && tile.fade > 0.5
          && !tile.alwaysVisibleRooms.has(inRoom)
          && (tile.roomLevels.get(inRoom) ?? 0) !== tile.levelFilter;
        // A character the server has in a ROOM of this tile belongs inside it.
        // With the interior closed there is nothing to draw it in, and the
        // `else` branch above lines it up in FRONT of the building — the whole
        // tavern standing on the doorstep, which is the acceptance finding.
        // So it simply is not drawn until the interior opens; then the room
        // placement and the exit routing take over unchanged (`inRoom` flips,
        // `shownRoom` sees the transition and walks the figure in through the
        // door). Untouched: characters without a room, always-visible rooms,
        // travellers (they returned above) and THE AVATAR — the last one by
        // name, not via `playerDriven`: that flag is only set inside the
        // embodied mode, so in the overview this rule hid the player's own
        // figure, and with it the only way back in (`characterAt` raycasts
        // visible roots only, so the plaque and its "take control" were
        // unreachable). The storey filter below still applies to it.
        const roomIsClosed = !inRoom && !!room && !!roomCenter
          && c.name !== map.avatar;
        const hidden = wrongStorey || roomIsClosed;
        if (hidden) hiddenChars.add(c.name);
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
    updateElevator();   // standing at the lift is a second-scale event too
    updateEnterOffer(); // …and so is standing at a location entry (Etappe 3)
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
   *  and nature carry). It says where a route may travel THROUGH — it is NOT
   *  what makes a cell enterable. */
  const passableCells = new Set(placeable
    .filter((l) => l.passable || l.template_location_id)
    .map((l) => `${l.grid_x},${l.grid_y}`));
  /** Which location sits on a cell. Also the enterable-check: the server's step
   *  (`world_ops.move_avatar_step`) has NO passability check — it gates on the
   *  entry room and the block rules and otherwise moves the avatar into the
   *  neighbouring location, so a plot or a building can be walked into and the
   *  client must let the server decide. A cell with no location stays a wall;
   *  there the server would answer 404. */
  const locIdAtCell = new Map(placeable.map((l) => [`${l.grid_x},${l.grid_y}`, l.id]));
  function tileAtCell(c: Cell): Tile | null {
    const id = locIdAtCell.get(`${c.gx},${c.gy}`);
    return id ? tiles.get(id) ?? null : null;
  }

  // --- Minimap slice (Etappe 5, task 3) --------------------------------------
  //
  // The HUD draws the map, this publishes what it draws — and it publishes ONLY
  // ON A CHANGE. The signature below is the whole rule: the cell revision, the
  // avatar's cell and the camera yaw in whole degrees. Everything smaller than
  // that (a step across a cell, a fraction of a degree of orbit) would redraw a
  // 160-pixel canvas and re-render React for a picture nobody could tell apart.
  //
  // The avatar's CELL comes from `cellOf` — the very function the step machine
  // above asks, so the dot stands on the cell the server is being told about
  // and never on a neighbouring one. Leaving the mode publishes the empty slice
  // once: the minimap belongs to the embodied view, and a map left standing
  // with a dot from minutes ago would be worse than none.
  let minimapSig = '';
  setInterval(() => {
    if (getGameState().mode !== 'embodied') {
      if (minimapSig === '') return;
      minimapSig = '';
      setMinimap(null);
      return;
    }
    const pos = npcs.positionOf(avatarName);
    const cell = pos ? cellOf(pos.x, pos.z, CELL) : null;
    // Whole degrees: the compass needle turns in 45° steps (Q/E) plus the free
    // orbit, and a degree is finer than the needle can show anyway.
    const yawDeg = Math.round(engine.yaw * 180 / Math.PI);
    const frame = fogBounds
      ? `${fogBounds.min_x},${fogBounds.min_y},${fogBounds.max_x},${fogBounds.max_y}` : '';
    const sig = `${minimapCellsRev}|${cell ? `${cell.gx},${cell.gy}` : ''}|${yawDeg}|${frame}`;
    if (sig === minimapSig) return;
    minimapSig = sig;
    setMinimap({
      cells: minimapCells,
      avatar: cell ? { x: cell.gx, y: cell.gy } : null,
      // The published yaw is the QUANTISED one, so the drawn wedge and the
      // signature can never disagree about where the avatar looks.
      yaw: yawDeg * Math.PI / 180,
      bounds: fogBounds,
    });
  }, MINIMAP_MS);

  /**
   * A place the avatar has just discovered joins the map (Etappe 5).
   *
   * The fog lifts DURING play — the server starts delivering a location the
   * moment it becomes known — so this walks a newcomer through everything the
   * boot path does for a location, in the same order and out of the same
   * functions: the surface neighbourhood first (the coast blends of the tiles
   * around it read from it), then the tile itself, then the structures that
   * answer questions about cells (pathfinding, passability, which location is
   * where) and finally the veil, which is one cell smaller now.
   *
   * The rooms come from a FRESH `/world/locations`: the boot snapshot was
   * taken while this place was still fogged, and a location created after boot
   * would not be in it at all. That endpoint is unfiltered, one call covers
   * however many appeared at once, and a failed call simply leaves the work to
   * the next poll — `tiles` is what says "already built", so nothing is done
   * twice.
   *
   * ONE DIRECTION ONLY. In play a place once known stays known, so nothing has
   * to be taken away again. The only thing that can shrink the map is the
   * administrator's "show all" switch, and that one is applied by reloading
   * the view (see the game menu) rather than by unbuilding half a world.
   */
  let revealBusy = false;
  async function revealLocations(map: WorldMap): Promise<void> {
    // One reveal at a time: the run awaits twice, and two overlapping runs
    // would both pass the `tiles.has` filter and mount the same location
    // twice. Whatever a skipped run would have found is found by the next
    // poll — three seconds later, and the payload says it again.
    if (revealBusy) return;
    revealBusy = true;
    try {
      await revealBatch(map);
    } finally {
      revealBusy = false;
    }
  }
  async function revealBatch(map: WorldMap): Promise<void> {
    let details: Map<string, WorldLocation>;
    try {
      details = new Map((await api.getLocations()).map((l) => [l.id, l]));
    } catch {
      return;   // server briefly away — the next poll tries again
    }
    for (const [id, loc] of details) detailById.set(id, loc);
    const fresh = placeableOf(map, details).filter((l) => !tiles.has(l.id));
    if (!fresh.length) return;
    placeable.push(...fresh);
    publishTerrainGrid();
    // Neighbours FIRST, and only then the newcomers: a tile bakes its coast
    // blend from the grid at build time (the ordering finding of 2026-07-29),
    // so the four neighbours of a new cell have to be rebuilt against the
    // grid that already knows about it.
    const revealedCells = new Set(fresh.map((l) => `${l.grid_x},${l.grid_y}`));
    for (const tile of [...tiles.values()]) {
      const near = [[1, 0], [-1, 0], [0, 1], [0, -1]] as const;
      if (near.some(([dx, dy]) => revealedCells.has(`${tile.loc.grid_x! + dx},${tile.loc.grid_y! + dy}`))) {
        rebuildTile(tile, tile.loc);
      }
    }
    // The scene recipes before the tiles, exactly as at boot: a tile built
    // without its payload would stand as the procedural shell and only swap
    // once the sweep noticed it.
    await scenes.prime(fresh.map((l) => l.id));
    for (const loc of fresh) {
      addTile(loc);
      // Seeded from the SAME source the boot path seeds from, template
      // fallback included: a revealed clone has no detail entry of its own,
      // and a signature taken from the merged location would differ from the
      // first poll's and rebuild the fresh tile for nothing.
      locSig.set(loc.id, sigOf(
        details.get(loc.id) ?? details.get(loc.template_location_id || '') ?? loc));
      const cell = `${loc.grid_x},${loc.grid_y}`;
      if (loc.passable || loc.template_location_id) passableCells.add(cell);
      locIdAtCell.set(cell, loc.id);
    }
    engine.setPickables([...tiles.values()].map((t) => t.group));
    pathGrid = publishPathGrid();
    rebuildFog();
  }

  // --- Soundtrack: music by daylight, ambience by ground (E4-T5) ------------
  //
  // WHAT plays is decided in `game/soundtrack.ts` (pure, hand-checked in
  // scripts/smoke_walk_math.mjs); what is left here is the wiring — where the
  // numbers come from and when they are looked at. ONE tick recomputes the
  // whole answer, because every input moves on its own schedule (the night
  // factor with the game-hour poll, the terrain with every step, the switches
  // with a click in the menu) and a full recompute can never end up in a state
  // that no input would produce. Repeating it is free: an identical playlist
  // is a no-op in the engine.
  //
  // NOTHING SOUNDS BEFORE THE CONTEXT RUNS. It is created suspended and only
  // the title screen's click resumes it (`getAudio().unlock()` in `boot`); a
  // source started into a suspended context would not play but would still
  // consume its place in the schedule. So the tick waits for `running` — which
  // is at the same time the retry for the case where the resume lands a moment
  // after the world is built.
  const audio = getAudio();
  // The drivers read the stored settings themselves — this one runs before the
  // React island that owns the menu even mounts (E4-T4).
  const startPrefs = loadPrefs(localStorage.getItem(PREFS_KEY));
  let musicOn = startPrefs.musicOn;
  let ambientOn = startPrefs.ambientOn;
  let audioManifest: AudioManifest = emptyManifest();
  let musicNight = false;
  let ambience = newTerrainSwitch();
  /** Crossfade of the day/night change. Longer than the playlist's own seam:
   *  this one is a change of mood, not the next track. */
  const MUSIC_CROSSFADE_S = 4;

  function tickSoundtrack() {
    if (!audio.running) return;
    musicNight = nightForMusic(musicNight, engine.nightFactor);
    audio.playMusic(musicOn ? pickMusic(audioManifest, musicNight) : [],
      { crossfadeS: MUSIC_CROSSFADE_S });
    const mode = getGameState().mode;
    // Embodied the avatar's own cell decides, in the overview the cell the
    // camera looks at; the terrain is read off the tile standing there, so a
    // tile rebuilt with a different terrain takes effect without a cache.
    const pos = mode === 'embodied' ? npcs.positionOf(avatarName) : null;
    const here = ambientTerrainFor(
      mode,
      pos ? cellOf(pos.x, pos.z, CELL) : null,
      cellOf(engine.target.x, engine.target.z, CELL),
      (c) => tileAtCell(c)?.loc.terrain ?? '',
    );
    ambience = terrainSwitch(ambience, here, performance.now());
    audio.playAmbient(ambientOn ? pickAmbient(audioManifest, ambience.applied) : []);
  }
  updateSoundtrack = tickSoundtrack;
  setInterval(tickSoundtrack, SOUNDTRACK_TICK_MS);
  // ONE fetch per session: the folder is user data that does not change while
  // the game runs, and `getAudioManifest` never throws — a server without the
  // route or a failed request is the empty manifest, i.e. silence until the
  // next reload.
  void api.getAudioManifest().then((m) => {
    audioManifest = m;
    tickSoundtrack();
  });

  // The switches of the game menu (E4-T4). This fires on EVERY change there,
  // which means dozens of times a second while a volume slider is dragged — so
  // it compares the two fields it owns and returns. The volumes are already on
  // the engine by the time this runs; they are none of this driver's business.
  gameActions.applyAudioPrefs = (p) => {
    if (p.musicOn === musicOn && p.ambientOn === ambientOn) return;
    musicOn = p.musicOn;
    ambientOn = p.ambientOn;
    tickSoundtrack();
  };

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
  /** Companion flag of the room walk (E3-T6), declared here because the two
   *  INTERLOCK: a cell step and a room change are both "where the avatar is",
   *  and the entry-room gate judges a step by the room the avatar is in. Let
   *  them overlap and the NETWORK order decides whether the step through the
   *  door gets through. So neither starts while the other runs — at a cell
   *  boundary that is the same clamp a step in flight already causes. The T6
   *  section further down owns the writes. */
  let roomRequestInFlight = false;
  /** How long a lift ride may take before the figure is handed back even
   *  without arriving. A safety net only: the figure can be held up (a model
   *  reload throws its group away mid-ride), and a ride that never ends would
   *  leave the player unable to steer at all. */
  const ELEVATOR_RIDE_MS = 4000;
  /** Distance that counts as "arrived at the holding point" — in XZ AND in
   *  height, so the vertical part of the ride has to be over as well. */
  const ELEVATOR_ARRIVE = 0.2;
  /** The running lift ride, declared here for the same reason as the flag
   *  above: it INTERLOCKS with the walking hook. While it is set the hook does
   *  not steer at all — the goal belongs to the lift, and one steering frame
   *  would overwrite it, walking the figure out of the shaft while its height
   *  still blends to the other storey (through the ceiling) into a room nobody
   *  chose, which the room walk then pays for with a second
   *  `/play/enter-room`. The elevator section further down owns the writes. */
  let elevatorRide: { goal: THREE.Vector3; until: number } | null = null;
  /** Deadline of a doorway walk (E3 acceptance, "walking on the roof"). Same
   *  safety net as the ride's, and generous for the same reason: the pace the
   *  figure keeps during it is whatever it walked in with. */
  const DOOR_WALK_MS = 4000;
  /** Distance that counts as "arrived at the door" — XZ only. Unlike the lift
   *  there is no vertical ride to wait for: the goal already carries the room
   *  floor and `tick()` blends the height while the figure walks. */
  const DOOR_ARRIVE = 0.3;
  /** The running doorway walk, and it owns the figure exactly as the ride
   *  does: a granted step into a building puts the avatar in that building's
   *  entry room (the server says so in its answer), and the figure has to
   *  arrive there through the door instead of walking on across the shell.
   *  One steering frame would overwrite the goal, so the hook keeps its hands
   *  off until the figure stands at the door point. Written below in
   *  `enterThroughDoor`. */
  let doorWalk: { goal: THREE.Vector3; until: number } | null = null;
  /** Cell our own step aims at (or came back to after a refusal) — the
   *  authority check must not read it as foreign movement. It is consumed by
   *  the FIRST worldmap poll after the request ended (see
   *  `reconcileAvatarCell`), not by a timer. */
  let expectedCell: Cell | null = null;
  /** Until when a `not_at_entry_room` 403 counts as a race and is answered by
   *  running the entry-room chain instead of by a toast. Bounds it to one
   *  automatic attempt per memory window — a second refusal in a row is a real
   *  disagreement with the server and belongs on screen. */
  let entryRetryUntil = 0;
  /** cell key -> `performance.now()` stamp until which a refused crossing stays
   *  refused. The monotonic clock, never the wall clock: this is a DURATION,
   *  and the same choice the room walk (T6) makes for its own cooldowns. */
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
      const moved = await api.avatarStep(direction, abort.signal);
      // The boundary is open now: the figure walks over it in the next frames
      // WITHOUT another request. No snap — the server is already there and the
      // worldmap confirms it within a poll.
      edge.granted = true;
      // A step into another location lands the avatar in that location's ENTRY
      // room, and the answer says which one that is. Taking it is not a local
      // anticipation — it is the server's own word, three seconds before the
      // poll repeats it. Without it the room walk below is blind for a whole
      // poll and adopts the nearest room centre out of nothing, which walks
      // the avatar straight out of the entry room it was just placed in; the
      // step back out then earns a `not_at_entry_room` 403.
      // An empty room_id is the location's GROUND, not a missing answer — it
      // must overwrite roomOf unconditionally, or the avatar keeps the room
      // of the location it just left. `enterThroughDoor` stays gated on an
      // actual room, since there is no door onto the ground to walk through.
      roomOf.set(avatarName, moved.room_id ?? '');
      if (moved.room_id) {
        enterThroughDoor(to, moved.room_id);
      }
    } catch (e) {
      const err = e instanceof api.ApiError ? e : null;
      rejectedUntil.set(`${to.gx},${to.gy}`, performance.now() + REJECT_MEMORY_MS);
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
      // The entry-room gate is walked by the client now (`entryRoomToEnter`),
      // so this 403 is a RACE, not something the player did: the poll moved
      // the avatar's room between the check and the request. A toast asking
      // them to walk to a room the client walks to by itself is noise — the
      // chain is simply run once and the edge is not blocked for it. Once,
      // though: a second refusal inside the memory window IS worth telling
      // them about instead of looping silently.
      // The chain has to REALLY start for that, though: with no room to walk
      // to (the client already believes it is in the entry room, or that room
      // is on cooldown) clearing the edge only bought a second request and a
      // toast one refusal later. Then the refusal counts as an ordinary one
      // and goes out as it stands.
      const race = err?.reason === 'not_at_entry_room'
        && performance.now() > entryRetryUntil
        ? entryRoomToEnter(tileAtCell(from), EXIT_EDGE_OF[direction]) : null;
      if (race) {
        entryRetryUntil = performance.now() + REJECT_MEMORY_MS;
        rejectedUntil.delete(`${to.gx},${to.gy}`);
        void enterEntryRoom(race);
      }
      // 403 = a rule refused it and the server wrote the reason for the
      // player. 404 = there is simply no location that way, which the edge
      // already shows — no toast for that.
      else if (err?.status === 403) uiActions.toast?.(err.message);
      else if (abort.signal.aborted) console.warn('[walk] step request timed out');
      else if (!err) console.warn('[walk] step request failed', e);
    } finally {
      clearTimeout(deadline);
      stepInFlight = false;
    }
  }

  /**
   * Walk into a building through its DOOR (E3 acceptance, "Zur Rosinante").
   *
   * A granted step into another location puts the avatar in that location's
   * entry room — the server's answer names it. The figure, though, is standing
   * on the cell boundary and would keep walking straight ahead: over the
   * building's shell, past every wall, into a room from the wrong side. The
   * entry room's exit point is where the door is (`tile.roomExits`, the same
   * point the NPC exit routing walks through, `computeNpcStates`), so the
   * figure is sent there and the walking hook keeps its hands off until it
   * arrives — the ownership the lift ride already needs, for the same reason.
   *
   * A tile without a layout for that room (no scene, an outdoor location)
   * keeps the old behaviour: nothing to enter through, nothing to own.
   */
  function enterThroughDoor(cell: Cell, roomId: string) {
    const tile = tileAtCell(cell);
    // Only where there is an interior to enter — the same condition the view
    // opens one on. Walking onto passable ground (a street, a park with
    // zones) must not take the steering away for a second: there the avatar
    // is simply outdoors, wherever the player walks.
    if (!tile?.isBuilding || !tile.interior) return;
    // Centre as the fallback: an entry room without a derived exit (an outdoor
    // room, an overlay zone) still has a place the avatar belongs at.
    const point = tile.roomExits.get(roomId) ?? tile.roomCenters.get(roomId);
    if (!point) return;
    npcs.setPlayerTarget(avatarName, point.clone());
    doorWalk = { goal: point.clone(), until: performance.now() + DOOR_WALK_MS };
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
    // Overview mode is untouched: there a click stays a tile pick. A running
    // lift ride or doorway walk owns the figure, so no new order is planned
    // during those either — a route planned from the old position would walk
    // the figure back out of the door it just came through.
    if (state.mode !== 'embodied' || state.movementLocked
      || elevatorRide || doorWalk) return false;
    const pos = npcs.positionOf(avatarName);
    if (!pos) return false;
    // The click is read against the plane the FIGURE stands on, not against
    // y = 0 (parked review finding, E3): on an upper storey or a raised floor
    // the ray otherwise runs past the floor down to the map's ground, and at a
    // flat camera angle the goal lands metres behind the pointer. The height is
    // the drawn one, so it is right for every storey without a second source.
    const hit = engine.groundPointAt(x, y, pos.y);
    if (!hit) return false;
    const planned = planRoute(
      { x: pos.x, z: pos.z }, { x: hit.x, z: hit.z },
      (gx, gy) => passableCells.has(`${gx},${gy}`),
      (gx, gy) => locIdAtCell.has(`${gx},${gy}`),
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
    // Marker height from the same source the walking uses: the room floor
    // where the avatar's room reaches, the ground skin everywhere else.
    const goalCell = cellOf(planned.goal.x, planned.goal.z, CELL);
    npcs.setWalkTarget(new THREE.Vector3(planned.goal.x,
      roomFloorY(tileAtCell(goalCell)) ?? groundY(planned.goal.x, planned.goal.z),
      planned.goal.z));
    return true;
  };

  // The player drives the avatar for exactly as long as the mode is on. Hung
  // off the BUS, not off the enter/exit calls: zooming out leaves the mode
  // from inside embody.ts, and the figure has to be handed back then too.
  subscribeGameState(() => {
    const embodied = getGameState().mode === 'embodied';
    npcs.setPlayerDriven(embodied ? avatarName : null);
    // The storey following is edge-triggered, and its memory must not outlive
    // the mode: while the player is in the overview the in-world switch is the
    // only authority, so a storey picked there would face a memory that
    // already holds the avatar's — the edge would not fire on re-entry and the
    // view would stay on the wrong floor, which IS the finding.
    if (!embodied) followedStorey.clear();
  });

  const walkGoal = new THREE.Vector3();
  engine.addFrameHook((dt) => {
    const state = getGameState();
    if (state.mode !== 'embodied') {
      cancelRoute();                      // leaving the mode drops the route
      // …and with it the whole step machine: a pending permission or an
      // expected cell from the last walk must not survive into the next
      // embodied session, where it would belong to a cell nobody stands on.
      askedEdge = null;
      expectedCell = null;
      elevatorRide = null;   // ditto for a ride nobody is in any more
      doorWalk = null;       // …and for a doorway nobody is walking through
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
    // A running lift ride owns the figure: its goal is the holding point of
    // the target storey, and steering would overwrite it in the very next
    // frame. The ride is short, so the keys and click orders are ignored for
    // its duration instead of cancelling it half-way — a ride abandoned in
    // mid-air would leave the figure between two storeys. It ends when the
    // figure stands at the point (XZ and height), or on the safety deadline.
    if (elevatorRide) {
      const arrived = Math.hypot(elevatorRide.goal.x - pos.x, elevatorRide.goal.z - pos.z)
          < ELEVATOR_ARRIVE
        && Math.abs(elevatorRide.goal.y - pos.y) < ELEVATOR_ARRIVE;
      if (!arrived && performance.now() <= elevatorRide.until) return;
      elevatorRide = null;
    }
    // A doorway walk owns the figure the same way: the step was granted, the
    // avatar is in the building's entry room, and the figure walks to that
    // room's door point. Steering during it is what put the avatar on the
    // shell — the very finding this exists for. XZ only, the height is the
    // room floor and `tick()` blends it on the way.
    if (doorWalk) {
      const arrived = Math.hypot(doorWalk.goal.x - pos.x, doorWalk.goal.z - pos.z)
        < DOOR_ARRIVE;
      if (!arrived && performance.now() <= doorWalk.until) return;
      doorWalk = null;
    }
    // Pace of the SIZE the figure is drawn at (E3 fix): indoors it stands at
    // the room scale, where a world metre is not a figure metre — unscaled,
    // 3.4 m/s next to a figure a third the size reads as eleven metres a
    // second, which is the "far too fast in rooms" of the acceptance round.
    // The factor goes to BOTH halves of the pace, the goal below and the
    // catch-up in `tick()`; see `setPlayerSpeed` for why the goal alone cannot
    // carry it. `MIN_LEAD` deliberately does not scale — it is not a distance
    // in figure metres but the floor that keeps tick()'s 0.05 world-unit "is
    // moving" test true.
    const speedScale = walkSpeedScale(npcs.scaleOf(avatarName));
    npcs.setPlayerSpeed(speedScale);
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
    const lead = Math.min(Math.max(WALK_SPEED * speedScale * dt, MIN_LEAD), reach);
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
        // What bars a crossing is the LOCATION, not the terrain: every known
        // neighbour is worth a step request, and the server answers whether it
        // is allowed (403 + toast). Only a cell no location covers is a wall
        // the client may decide about on its own.
        const barred = !step || !locIdAtCell.has(key)
          || (rejectedUntil.get(key) ?? 0) > performance.now();
        // Room the avatar has to be in before it may leave this location
        // OVER THIS EDGE (E3 acceptance "the village cannot be left"), null
        // when it already is, the location has no gate, or an authored
        // pass-through opens this very edge from the room it stands in.
        const gateRoom = step
          ? entryRoomToEnter(tileAtCell(here), EXIT_EDGE_OF[step]) : null;
        // `roomRequestInFlight` clamps exactly like a step in flight (E3-T6):
        // a room change and a cell step must not overlap, or the entry-room
        // gate judges this step against a room that is still moving.
        if (barred || stepInFlight || roomRequestInFlight) {
          // A route that runs into a barred edge is void — the plan was made
          // against the map, so this is a refusal the plan did not know about.
          // A step merely in flight is NOT that: there the figure just waits
          // at the boundary for its turn.
          if (barred) cancelRoute();
          ({ x, z } = clampToCell(x, z, here, CELL));
        } else if (gateRoom) {
          // The entry-room gate is 2D logic — in 3D the client walks it. The
          // avatar stands in a room that is not the one this location is left
          // through, so the room change goes FIRST, through the one
          // room-request machine (`enterRoomOnFoot` sets the interlock flag in
          // the same frame). The figure waits at the boundary meanwhile,
          // exactly as it waits for a step: one request, no hail, and the step
          // follows in the frame after the answer.
          void enterEntryRoom(gateRoom);
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
    // Walls have the LAST word (E3 acceptance: "the avatar walks through
    // walls"). After the cell logic and after `keepAhead`, because a goal that
    // is perfectly legal for its cell may still lie in the next room — and a
    // wall must outrank the anti-vibration rule, not the other way round. The
    // clamp slides along the wall exactly as the cell clamp slides along a
    // boundary, so nothing here has to stop the figure dead.
    const walls = avatarWalls(tileAtCell(here));
    if (walls) ({ x, z } = clampAgainstWalls(pos, { x, z }, walls.segments, walls.radius));
    walkGoal.set(x, roomFloorY(tileAtCell(here)) ?? groundY(x, z), z);
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

  // --- Changing rooms on foot (E3-T6) ---------------------------------------
  // Inside an open interior the avatar's room is no longer a click on a room
  // chip — walking into a room moves it, and the chat context follows. The
  // rule itself is pure (`game/roomwalk.ts`, numbers in
  // scripts/smoke_walk_math.mjs); everything here looks up its arguments and
  // fires the ONE request it asks for.
  //
  // This is also where the avatar's position, room and scale finally become
  // ONE pair (findings of T3/T5). All three are derived from where the figure
  // is DRAWN: the tile under its feet, the room of that tile it is closest to,
  // and the scale that tile draws its figures at.
  const ROOM_HOLD_SECONDS = 1.5;
  /** How long a refused room stays refused. Without it a player standing on
   *  the wrong side of a block rule would fire a fresh request every 1.5 s. */
  const ROOM_REJECT_MS = 4000;
  /** How long a fired switch waits for the worldmap to confirm it (poll: 3 s).
   *  After that the request counts as lost — a confirmation that never arrives
   *  would otherwise bar that room for the rest of the session. */
  const ROOM_CONFIRM_MS = 10_000;
  /** Deadline for one room request. Same reason as `STEP_TIMEOUT_MS`: only ONE
   *  may be in flight and it interlocks with the walking steps, so a request
   *  that never answers (proxy hiccup, server restart) would bar every room
   *  change AND every cell boundary for the rest of the session. */
  const ROOM_TIMEOUT_MS = 10_000;
  let roomWalk: RoomWalkState = idleRoomWalk();
  /** Room the server was asked for, until `roomOf` confirms it. NOT a local
   *  anticipation of the room — the payload alone decides where the avatar is;
   *  this only stops the hysteresis from asking again while the answer is
   *  still on its way. */
  let requestedRoom: string | null = null;
  let requestedAt = 0;
  /** room id -> time until which a refused switch stays refused */
  const roomRejectedUntil = new Map<string, number>();

  /** The avatar's room as the SERVER sees it, resolved to a room ID: `roomOf`
   *  carries the worldmap's `room_id`, but the pre-AV3D-8 fallback poll writes
   *  a room NAME into the same map — and `/play/enter-room` takes ids only. */
  function avatarRoomId(tile: Tile): string | null {
    const raw = roomOf.get(avatarName);
    if (!raw) return null;
    return tile.loc.rooms.find((r) => r.id === raw || r.name === raw)?.id ?? null;
  }

  /** Rooms of an interior, reduced to id/storey/centre — the shared input of
   *  the room walk and of the elevator. Keyed by ID on purpose: `roomCenters`
   *  holds every centre TWICE (under id and under name, one shared instance),
   *  and one room must not stand for two candidates. No centre = no layout to
   *  walk into. */
  function interiorRooms(tile: Tile): RoomWalkRoom[] {
    const rooms: RoomWalkRoom[] = [];
    for (const r of tile.loc.rooms) {
      const c = tile.roomCenters.get(r.id);
      if (c) {
        rooms.push({ id: r.id, level: tile.roomLevels.get(r.id) ?? 0,
                     center: { x: c.x, z: c.z } });
      }
    }
    return rooms;
  }

  /** Whether a point lies inside a room's floor rectangle (world XZ) — the
   *  same rectangles the focus mode uses, taken from the mounted scene. A room
   *  the tile has no rectangle for (no plate, no overlay) contains nothing. */
  function insideRoomRect(tile: Tile, roomId: string,
                          pos: { x: number; z: number }): boolean {
    const r = tile.roomRects.get(roomId);
    if (!r) return false;
    return Math.abs(pos.x - r.x) <= r.w / 2 && Math.abs(pos.z - r.z) <= r.d / 2;
  }

  /**
   * Height the avatar WALKS at INSIDE A BUILDING: the floor of the room it is
   * in, on every storey, taken from the same source the NPC placement uses
   * (`roomCenters`, lifted onto the sampled floor by `sampleRoomWalkables`).
   * Null — the ground skin answers — everywhere else, and that is three cases:
   * a passable tile (street, park), a tile whose rooms the avatar is not in,
   * and an ALWAYS-VISIBLE outdoor zone. The last one is not a room with a
   * floor but a piece of ground: the payload gives it ONE height (its
   * `overlay.y`), while the skin samples the model under the figure's feet and
   * follows the slope. Taking the zone's single height there would float the
   * figure downhill and sink it uphill — a village square is 0.63 m of world
   * height across a 3 m rise of the plan at Willowbrook's scale.
   *
   * The ground skin (`tileGroundY`) is NOT an alternative inside a room, and
   * the "Zur Rosinante" finding of the acceptance round is why: it raycasts
   * the building/area MESH from above and takes the first hit below 1.2 m,
   * which is a world metre and therefore an assumption about scale. Willowbrook
   * runs at k = 0.21 (extent_m 10.5 over a 50 m plan), so a whole storey is
   * 0.63 m and every ROOF of the village fits inside that window: the ray hit
   * the tavern's roof at ~0.6..0.9 instead of its floor plate at 0.037 and the
   * avatar walked over the houses. Reading the floor off the room removes the
   * guess entirely — the number comes from the payload the room is built from.
   */
  function roomFloorY(tile: Tile | null): number | null {
    if (!tile?.isBuilding) return null;
    const room = avatarRoomId(tile);
    if (!room || tile.alwaysVisibleRooms.has(room)) return null;
    return tile.roomCenters.get(room)?.y ?? null;
  }

  /**
   * The walls the AVATAR currently bumps into, or null when nothing should
   * block. Three conditions, and each one is a real case:
   *
   *  - a building whose interior is DRAWN (`interior.visible`, set by
   *    `applyTileFade` from the camera distance). With the shell closed there
   *    is nothing on screen to bump into and the figure is walking the tile
   *    from outside — invisible walls there would be the worse bug.
   *  - a scene payload. A legacy procedural tile has no wall vocabulary at
   *    all; there is nothing to derive segments from and it stays as it was.
   *  - a KNOWN storey for the avatar: the one its room is on. Not
   *    `levelFilter` as a fallback — that is the storey the CAMERA shows, and
   *    clamping a figure against the walls of a floor it is not on is worse
   *    than not clamping at all. No room resolved (a poll in flight, a stale
   *    id) means no collision for those few frames.
   *  - at least one segment on that storey.
   *
   * Guided movements are NOT affected — the walking hook returns early for a
   * lift ride and for a doorway walk, both of which aim at a point the route
   * was chosen for (the door, the holding point) and would only be fought by
   * a clamp.
   */
  function avatarWalls(tile: Tile | null
  ): { segments: Segment[]; radius: number } | null {
    if (!tile?.isBuilding || !tile.interior?.visible) return null;
    const scene = scenes.get(tile.loc.id);
    if (!scene) return null;
    const room = avatarRoomId(tile);
    const level = room ? tile.roomLevels.get(room) : undefined;
    if (level === undefined) return null;
    let byLevel = wallCache.get(tile.loc.id);
    if (!byLevel) {
      byLevel = new Map();
      wallCache.set(tile.loc.id, byLevel);
    }
    let segments = byLevel.get(level);
    if (!segments) {
      // The payload is TILE-LOCAL (world metres around the tile centre), the
      // figure position is absolute — so the centre is baked in here, exactly
      // as `mountScene` bakes it into room centres, exits, markers and the
      // wall mids of the culling. Without it the segments of a building on
      // grid (4,2) sit 45 m from the figure and nothing ever blocks.
      segments = wallSegments(scene, level,
        { x: tile.center.x, z: tile.center.z });
      byLevel.set(level, segments);
    }
    // The radius comes from the SCENE's `k`, the same number the doorways are
    // measured in: walls and body then shrink together and a 0.6 m gap in a
    // village drawn at k = 0.21 is still a 0.6 m gap for the figure.
    return segments.length ? { segments, radius: bodyRadius(scene.k) } : null;
  }

  /** @param announce show the server's reason to the player when it wrote one
   *                  (the ride does, the room walk stays silent).
   *  @returns true when the server accepted the room. */
  async function enterRoomOnFoot(roomId: string, announce = false): Promise<boolean> {
    roomRequestInFlight = true;
    requestedRoom = roomId;
    requestedAt = performance.now();
    const abort = new AbortController();
    const deadline = setTimeout(() => abort.abort(), ROOM_TIMEOUT_MS);
    try {
      await api.enterRoom(roomId, abort.signal);
      return true;
    } catch (e) {
      // Silent, exactly like the HUD's room chips: a rule refused it, the room
      // is stale, or the deadline ran out — the next poll shows what actually
      // holds. What the failure DOES buy is the block below, so a player
      // standing in the same spot cannot hammer the endpoint. An aborted
      // request lands here too and gets the ordinary 4-second block.
      roomRejectedUntil.set(roomId, performance.now() + ROOM_REJECT_MS);
      requestedRoom = null;
      // A room change the player ASKED for (the lift) must not fail mutely.
      // Only the server's own player text goes out — a `reason` marks it as
      // written for the player; a technical detail string ("room not in
      // current location") or a bare status stays in the console, and no text
      // is invented here (the vanilla side renders none).
      const err = e instanceof api.ApiError ? e : null;
      if (announce && err?.reason) uiActions.toast?.(err.message);
      else if (announce) console.warn('[elevator] enter-room refused', e);
      return false;
    } finally {
      clearTimeout(deadline);
      roomRequestInFlight = false;   // guaranteed, or the interlock never opens
    }
  }

  /**
   * The room the avatar has to be in before it may leave this location over
   * `exitEdge` — its ENTRY room — or null when there is nothing to do (E3
   * acceptance: "the village cannot be left, you have to walk to the square
   * first").
   *
   * The gate itself is the server's (`world_ops.move_avatar_step` refuses a
   * step out of any other room, 403 `not_at_entry_room`). In the 2D UI the
   * player clicks the room chip themselves; walking a figure through a world
   * has no such moment, so the client walks the rule instead of reporting it.
   * The server stays untouched and keeps deciding — this only takes the step
   * the player would otherwise have to guess at.
   *
   * The rule is per EDGE, which is why it needs one: an authored pass-through
   * lets one out of its own linked room (the ground, when it links to none)
   * over its own edge, so a detour through the entry room would be a detour
   * the server never asked for — and one a rule locking that room could make
   * impossible.
   */
  function entryRoomToEnter(tile: Tile | null, exitEdge: Edge): string | null {
    if (!tile) return null;
    const entry = (tile.loc.entry_room || '').trim();
    if (!entry) return null;                       // location without a gate
    const room = avatarRoomId(tile);
    // No room resolved at all (outdoors, a payload still on its way): nothing
    // to correct, and the server decides exactly as before.
    if (!room || room === entry) return null;
    // The server's own rule first: standing at an opening of this edge is a
    // way out on its own.
    const openings = (scenes.get(tile.loc.id)?.boundary_openings ?? [])
      .map((o) => ({ edge: o.edge, room_id: o.room_id }));
    if (mayLeaveAcross(exitEdge, room, entry, openings,
      getGameState().groundRoomId)) return null;
    if (!tile.loc.rooms.some((r) => r.id === entry)) return null;
    // A refused entry room is not walked around in circles: let the ordinary
    // step go out and let the server say why, in its own words.
    if ((roomRejectedUntil.get(entry) ?? 0) > performance.now()) return null;
    return entry;
  }

  /** Enter the entry room so the next step out may pass. The ONE room-request
   *  machine, and the server's answer is adopted the same way the step answer
   *  is: it IS the avatar's room now, three seconds before the poll repeats
   *  it — without that the gate would fire again in the very next frame. */
  async function enterEntryRoom(roomId: string): Promise<boolean> {
    if (!await enterRoomOnFoot(roomId)) return false;
    roomOf.set(avatarName, roomId);
    roomWalk = idleRoomWalk();   // fresh hysteresis: no instant switch back
    return true;
  }

  /** Storey the displayed one was last pulled to per tile — the memory that
   *  makes the following EDGE-triggered (see below). */
  const followedStorey = new Map<string, number>();

  /**
   * The displayed storey follows the avatar (E3 acceptance). Every way the
   * avatar changes storey now moves the view with it: entering a building, a
   * room change the poll brings in, the room walk — the lift was the only one
   * that did it, and everywhere else the player ended up standing on a floor
   * the view was not showing.
   *
   * Edge-triggered on purpose: the storey is applied when the AVATAR'S changes,
   * not every frame. A player who picks a storey on the in-world switch to look
   * around keeps that view for as long as the avatar stays where it is —
   * pulling it back per frame would make the switch useless while embodied.
   * In the overview the caller never runs at all, so there the switch is the
   * only authority, unchanged.
   */
  function followAvatarStorey(tile: Tile | null, room: string | null) {
    if (!tile || !room) return;
    const level = tile.roomLevels.get(room) ?? 0;
    if (followedStorey.get(tile.loc.id) === level) return;
    followedStorey.set(tile.loc.id, level);
    if (tile.levelFilter === level) return;
    tile.levelFilter = level;
    tile.levelSwitch?.();   // the in-world widget marks and floats at it too
  }

  // `performance.now()` throughout, never the wall clock: these are DURATIONS,
  // and a clock correction must not make a hold fire instantly or never.
  engine.addFrameHook(() => {
    const state = getGameState();
    if (state.mode !== 'embodied') { roomWalk = idleRoomWalk(); return; }
    const pos = npcs.positionOf(avatarName);
    // No figure on the map (a model reload throws the group away and rebuilds
    // it): the clock is RESET, not carried over. A candidate whose `sinceMs`
    // lies before the gap would fire in the very first frame after the figure
    // returns — the hold guarantee gone.
    if (!pos) { roomWalk = idleRoomWalk(); return; }
    // The tile the figure STANDS on, not the one the worldmap names — while
    // walking, the two differ for up to one poll.
    const tile = tileAtCell(cellOf(pos.x, pos.z, CELL));
    const current = tile ? avatarRoomId(tile) : null;
    if (requestedRoom
      && (current === requestedRoom
        || performance.now() - requestedAt > ROOM_CONFIRM_MS)) {
      requestedRoom = null;
    }
    followAvatarStorey(tile, current);
    // Scale (T5 finding): `update()` skips every placement field for the
    // player-driven figure, so its scale used to stay frozen at whatever it
    // was at takeover — a map-sized avatar inside a room, or a room-sized one
    // back out on the map. Same rule as `computeNpcStates`, only fed from the
    // drawn position instead of the placement pass.
    let scale = 1;
    if (tile && current && tile.roomCenters.has(current)
      && (tile.fade > 0.5 || tile.alwaysVisibleRooms.has(current))) {
      scale = sceneFigureScale(tile.loc.id) ?? roomFigureScale(tile.loc);
    }
    npcs.setPlayerScale(avatarName, scale);

    // The switch runs only while the interior of the avatar's OWN tile is
    // open — the same condition the room placement uses; from the outside
    // there is nothing to walk between. A party follower is carried by its
    // leader and the server refuses the call anyway.
    //
    // T5 (backend-status-3d.md, "Raumwechsel greift nur in Gebäuden"): on an
    // AREA location that is not the whole story. Its rooms are outdoor zones,
    // drawn at every zoom level, and its cell is passable — the avatar walks
    // in from the map instead of being placed inside. Tying the switch to the
    // interior alone meant the room there never changed on foot, which left
    // the prompt scoped to a room the player cannot reach.
    const interiorUp = !!tile && tile.fadeTarget === 1;
    if (!tile || !(interiorUp || tile.modelIsShellArea) || state.movementLocked) {
      roomWalk = idleRoomWalk();
      return;
    }
    // `roomOf` names a room, but this tile does not have it: the avatar
    // changed location and the truth (step answer, poll) is still on its way.
    // Adopting the nearest room centre out of nothing is exactly how a figure
    // that has just entered a building drifts out of its entry room again —
    // and cannot leave afterwards. An avatar with NO room at all (outdoors, a
    // location without rooms) is a different case and keeps the old behaviour.
    if (!current && roomOf.get(avatarName)) {
      roomWalk = idleRoomWalk();
      return;
    }
    // With the interior still closed (an area location seen from farther out)
    // only the ALWAYS-VISIBLE rooms are on screen: switching into a hidden
    // indoor room there would move the avatar somewhere the player cannot see.
    const rooms = interiorRooms(tile).filter(
      (r) => interiorUp || tile.alwaysVisibleRooms.has(r.id));
    // The ground is a TARGET, not a gap (plan-grundflaeche.md § 8, stage 2).
    // The rooms of a place do not cover it, so whoever steps out of a room
    // stands outside every rectangle — and that used to mean "no candidate",
    // which left the avatar in the room it had left, for the server, the
    // prompt and the chat window alike. The ground is the one room with an id
    // and no geometry: it cannot be found by distance, it is what remains
    // when no rectangle holds the figure. Its id comes from the scene payload
    // (`is_ground`) over the bus — the reserved constant stays the server's.
    //
    // Whether a rectangle holds the figure decides which room it is in; among
    // several (overlapping outdoor zones) the nearest centre still wins, and
    // the hold below is unchanged, so the boundary between "in" and "out"
    // flickers no more than the boundary between two rooms does.
    //
    // Only where there ARE rooms: a tile whose scene has not arrived (no
    // rectangles, no centres) proposes nothing at all, exactly as before —
    // adopting a room out of nothing is what the guard above prevents.
    const ground = getGameState().groundRoomId;
    const inside = rooms.filter((r) => insideRoomRect(tile, r.id, pos));
    const candidates = inside.length ? inside
      : (rooms.length && ground
        ? [{ id: ground, level: 0, center: { x: pos.x, z: pos.z } }]
        : rooms);
    // The storey is the FIGURE'S OWN, never the displayed one: `levelFilter`
    // is the in-world storey BUTTON, pure view state. Glancing at the first
    // floor from the hall must not post the avatar up there, and a room set by
    // the HUD chip must not be pulled back down because the view shows the
    // ground floor. Without a room yet, the displayed storey is the only
    // answer there is. The ground has no plate, so `roomLevels` does not know
    // it — it is the ground storey by definition.
    const ownLevel = current
      ? tile.roomLevels.get(current) ?? (current === ground ? 0 : undefined)
      : undefined;
    const level = ownLevel ?? tile.levelFilter;
    const before = roomWalk;
    const out = nearestRoomSwitch(current, { x: pos.x, z: pos.z }, candidates,
      level, before, performance.now(), ROOM_HOLD_SECONDS);
    const next = out.next;
    if (!next || next === current) { roomWalk = out.state; return; }
    // A due switch that cannot leave keeps the OLD clock instead of the
    // re-armed one, so it goes out the moment the line is free and does not
    // cost a second full hold. `stepInFlight` is the interlock: a cell step
    // and a room change must not overlap (the entry-room gate judges the step
    // by the room the avatar is in), so whichever started first finishes.
    const gated = roomRequestInFlight || stepInFlight || next === requestedRoom
      || (roomRejectedUntil.get(next) ?? 0) > performance.now();
    roomWalk = gated ? before : out.state;
    if (gated) return;
    void enterRoomOnFoot(next);
  });

  // --- Riding the elevator (E3, floors on foot) -----------------------------
  // Stage 3 left storey changes out and the 3D HUD has no room chips, so upper
  // floors were unreachable while embodied. The building already carries the
  // holding points the NPC storey routing rides (`tile.elevatorStops`,
  // AV3D-12) — what was missing is the player's way in. The rule is pure
  // (`game/elevator.ts`, numbers in scripts/smoke_walk_math.mjs); everything
  // here looks up its arguments and rides the ONE room-request machine of the
  // room walk above.
  function elevatorStopsOf(tile: Tile): ElevatorStop[] {
    if (!tile.elevatorStops) return [];
    return [...tile.elevatorStops].map(([level, p]) => ({ level, pos: { x: p.x, z: p.z } }));
  }

  /** Same 1 Hz tick as the talk target, and for the same reason: walking up to
   *  the lift is a second-scale event, not a per-frame one. */
  function updateElevator() {
    const state = getGameState();
    const clear = () => {
      if (state.elevator || state.elevatorOpen) {
        setGameState({ elevator: null, elevatorOpen: false });
      }
    };
    // A party follower is carried by its leader and the server refuses the
    // room change anyway — no offer it could not honour.
    if (state.mode !== 'embodied' || state.movementLocked) return clear();
    // Somebody walked into talk range: that prompt owns the bottom row and the
    // F key, so an open storey choice is no longer visible — and an invisible
    // choice must not keep Esc from leaving the mode.
    if (state.talkTarget && state.elevatorOpen) setGameState({ elevatorOpen: false });
    const pos = npcs.positionOf(avatarName);
    if (!pos) return clear();
    // Only inside the OPEN interior of the tile the figure stands on, exactly
    // as the room walk judges it: from the outside there is no lift to use.
    const tile = tileAtCell(cellOf(pos.x, pos.z, CELL));
    if (!tile || tile.fadeTarget !== 1 || !tile.elevatorStops) return clear();
    const room = avatarRoomId(tile);
    if (!room) return clear();
    const found = elevatorAt({ x: pos.x, z: pos.z }, tile.roomLevels.get(room) ?? 0,
      elevatorStopsOf(tile), interiorRooms(tile), npcs.scaleOf(avatarName) ?? 1);
    if (!found) return clear();
    // Unchanged offer: no bus write, or React re-renders the chip every second
    // for nothing.
    const now = state.elevator;
    if (now && now.current === found.current
      && now.levels.length === found.levels.length
      && now.levels.every((lv, i) => lv === found.levels[i])) return;
    setGameState({ elevator: found });
  }
  // Leaving the mode drops the offer in the same tick the mode changes,
  // instead of leaving it standing for up to a second.
  subscribeGameState(() => {
    if (getGameState().mode !== 'embodied') updateElevator();
  });

  gameActions.rideElevator = (level) => { void rideElevator(level); };

  /**
   * The ride: the server moves the avatar into the room of the target storey,
   * then the figure walks to that storey's holding point — the stop's world
   * point carries the storey height, and `tick()` blends the height towards
   * its goal, which is the same vertical ride the NPC storey routing takes.
   */
  async function rideElevator(level: number) {
    const state = getGameState();
    if (state.mode !== 'embodied' || !state.elevator || state.movementLocked) return;
    setGameState({ elevatorOpen: false });   // the press closes the choice, always
    const pos = npcs.positionOf(avatarName);
    if (!pos) return;
    const tile = tileAtCell(cellOf(pos.x, pos.z, CELL));
    const stop = tile?.elevatorStops?.get(level);
    if (!tile || !stop) return;
    const target = elevatorTargetRoom(level, elevatorStopsOf(tile), interiorRooms(tile));
    if (!target) return;
    // The ONE room-request machine of the room walk — a ride while a cell step
    // or another room change is in flight would let the network order decide
    // where the avatar ends up (the entry-room gate judges a step by the room
    // the avatar is in). No second enter-room path, and the SAME cooldown: a
    // room the server just refused stays refused for the ride as well, or
    // every press would run into the same 403.
    if (roomRequestInFlight || stepInFlight
      || (roomRejectedUntil.get(target) ?? 0) > performance.now()) return;
    // A click order would fight the ride from the next frame on — and it was
    // made for the storey the player is leaving.
    cancelRoute();
    if (!await enterRoomOnFoot(target, true)) return;
    // The server accepted the room, so that IS the avatar's room now — the
    // same word the step answer gives (`moved.room_id`), up to three seconds
    // before the poll repeats it. Without it the room walk would judge the
    // ride against the storey just left and ask the avatar back down.
    roomOf.set(avatarName, target);
    npcs.setPlayerTarget(avatarName, stop.clone());
    // From here the lift owns the figure until it stands at that point.
    elevatorRide = { goal: stop.clone(), until: performance.now() + ELEVATOR_RIDE_MS };
    // The view follows the ride. `levelFilter` is the in-world storey button,
    // pure view state — the same switch a click on it would throw, widget
    // marking included.
    tile.levelFilter = level;
    tile.levelSwitch?.();
    roomWalk = idleRoomWalk();   // fresh hysteresis: no instant switch back
    setGameState({ elevator: { levels: state.elevator.levels, current: level } });
  }

  // --- Entering an adjacent location (Etappe 3, "Betreten") -----------------
  // The offer is view logic, the ENTRY is the server's: pressing F runs the
  // very same `/world/avatar/step` flow the walking hook uses — entry-room
  // chain, one step machine, one interlock set — and then walks the figure
  // in. The rule of WHEN the offer stands is pure (`game/enterLocation.ts`,
  // numbers in scripts/smoke_walk_math.mjs): within ENTER_RADIUS of an
  // authored boundary opening (§ B1 Nr. 13) ON THE EDGE THE STEP CROSSES, of
  // a 4-adjacent location — a location without such an opening offers no
  // entry (2026-08-04), exactly as the server refuses that step.
  /** the standing offer, resolved to the cell the step must aim at */
  let enterOffer: { locId: string; cell: Cell } | null = null;

  function updateEnterOffer() {
    const state = getGameState();
    const clear = () => {
      enterOffer = null;
      if (state.enterOffer) setGameState({ enterOffer: null });
    };
    if (state.mode !== 'embodied' || state.movementLocked) return clear();
    const pos = npcs.positionOf(avatarName);
    if (!pos) return clear();
    const here = cellOf(pos.x, pos.z, CELL);
    const myLoc = locIdAtCell.get(`${here.gx},${here.gy}`);
    const candidates: EntryTile[] = [];
    for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]] as const) {
      const t = tileAtCell({ gx: here.gx + dx, gy: here.gy + dy });
      // Only locations with a detail view to enter — walking onto plain
      // passable ground is ordinary walking and needs no offer.
      if (!t || t.loc.id === myLoc || !openable(t)) continue;
      // Openings come TILE-LOCAL from the payload (world metres around the
      // tile centre, § B1 Nr. 13) — the centre is added here exactly as the
      // exits and markers get it added in mountScene. The EDGE rides along:
      // only the one the step crosses is a way in, and the rule filters on
      // it (the payload's letter is already the world edge, rotation
      // applied).
      const openings = (scenes.get(t.loc.id)?.boundary_openings ?? []).map((o) => ({
        x: t.center.x + o.at_world[0],
        z: t.center.z + o.at_world[1],
        edge: o.edge,
      }));
      candidates.push({
        locId: t.loc.id,
        cell: { gx: t.loc.grid_x!, gy: t.loc.grid_y! },
        openings,
      });
    }
    const offer = entryOfferNear({ x: pos.x, z: pos.z }, here, candidates);
    if (!offer) return clear();
    enterOffer = { locId: offer.locId, cell: offer.cell };
    const name = tiles.get(offer.locId)?.loc.name ?? '';
    if (state.enterOffer?.name !== name) setGameState({ enterOffer: { name } });
  }
  // Leaving the mode drops the offer in the same tick, like talk and lift.
  subscribeGameState(() => {
    if (getGameState().mode !== 'embodied') updateEnterOffer();
  });

  gameActions.enterLocation = () => { void enterOfferedLocation(); };

  /** Perform the offered entry: the entry-room chain of the location one is
   *  LEAVING first (the same 2D gate the walking hook walks), then the one
   *  step request, then the walk-in — through the door for buildings
   *  (requestStep already routes that via the answered room), towards the
   *  nearest opening for an area location (it has no door point). */
  async function enterOfferedLocation() {
    const offer = enterOffer;
    const state = getGameState();
    if (!offer || state.mode !== 'embodied' || state.movementLocked) return;
    // The one step/room machine: nothing may overlap a running request or a
    // guided movement — the same interlocks the walking hook honours.
    if (stepInFlight || roomRequestInFlight || elevatorRide || doorWalk) return;
    const pos = npcs.positionOf(avatarName);
    if (!pos) return;
    const here = cellOf(pos.x, pos.z, CELL);
    const step = stepDirection(here, offer.cell);
    if (!step) return;   // offer went stale — the avatar changed cells
    if ((rejectedUntil.get(`${offer.cell.gx},${offer.cell.gy}`) ?? 0) > performance.now()) return;
    cancelRoute();
    const gateRoom = entryRoomToEnter(tileAtCell(here), EXIT_EDGE_OF[step]);
    if (gateRoom && !await enterEntryRoom(gateRoom)) return;
    const edge = { from: here, to: offer.cell, granted: false };
    askedEdge = edge;
    await requestStep(step, here, offer.cell, edge);
    if (!edge.granted) return;
    // Granted, but the figure still stands short of the boundary — unlike a
    // WASD step, where it is already walking. Without a walk-in the figure
    // would linger on the old cell and the authority check would snap it to
    // the tile centre two polls later. Buildings got their door walk from
    // requestStep; everything else aims at the nearest opening, one step
    // inward (`inward` is the payload's unit normal), or the cell centre.
    if (!doorWalk) {
      const target = tiles.get(offer.locId);
      if (!target) return;
      let goal: { x: number; z: number } | null = null;
      let best = Infinity;
      for (const o of scenes.get(offer.locId)?.boundary_openings ?? []) {
        const ox = target.center.x + o.at_world[0] + o.inward[0] * OPENING_WALK_IN_M;
        const oz = target.center.z + o.at_world[1] + o.inward[1] * OPENING_WALK_IN_M;
        const d = Math.hypot(ox - pos.x, oz - pos.z);
        if (d < best) { best = d; goal = { x: ox, z: oz }; }
      }
      goal = goal ?? { x: target.center.x, z: target.center.z };
      const g = new THREE.Vector3(goal.x, groundY(goal.x, goal.z), goal.z);
      npcs.setPlayerTarget(avatarName, g);
      doorWalk = { goal: g.clone(), until: performance.now() + DOOR_WALK_MS };
    }
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
  // For the AVATAR it is still the server's view: its figure is player-driven,
  // so `npcs.update` ignores every placement field for it, yet its `shownRoom`
  // entry keeps being written from `roomOf` (the worldmap's `room_id`) in
  // `computeNpcStates`. Since T6 that is no longer a second source pulling the
  // other way: the room-walk hook DERIVES the server room from the drawn
  // position (nearest room centre of the tile under the figure's feet) and
  // asks the server for it, so `roomOf` follows where the player walked within
  // a poll. Room and position agree again — what remains is the poll's delay,
  // not a disagreement.
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
      // Nobody one cannot see is addressable: since the acceptance round a
      // character in a room whose interior is closed is not drawn at all, and
      // it stands where the placement pass parked it. Without this the prompt
      // would offer a conversation with an invisible figure.
      if (hiddenChars.has(c.name)) continue;
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

  // F is the ONE action key: talk to whoever is in range, use the lift one is
  // standing at, and — as the keyboard counterpart of the plaque's "Take
  // control" — enter the mode when the avatar is selected in the overview.
  // That is also the PRIORITY, and the HUD shows only the offer that wins:
  // a character in range beats the lift, so one press is never two offers.
  // Guarded like Esc: while the focus sits in the chat composer, F types an f.
  // Modifier combinations belong to the browser (Ctrl+F is the page search).
  window.addEventListener('keydown', (e) => {
    if (e.key.toLowerCase() !== 'f' || isTypingTarget(e)) return;
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    const state = getGameState();
    if (state.talkTarget) {
      uiActions.openChat?.();
      return;
    }
    if (state.elevator) {
      // Pressing again closes the storey choice — the same key, both ways.
      setGameState({ elevatorOpen: !state.elevatorOpen });
      return;
    }
    // Entering an adjacent location (Etappe 3) — last in the F priority,
    // exactly the order the HUD shows the offers in.
    if (state.enterOffer) {
      gameActions.enterLocation?.();
      return;
    }
    if (state.mode === 'overview' && state.selected?.isAvatar) gameActions.enterEmbodied?.();
  });

  // --- Frame-Hook: Detail-Ansicht (Singleton), NPC-Animation, Pin-Bobbing ---
  let bob = 0;
  engine.addFrameHook((dt) => {
    // Who owns the open view this frame (Etappe 3):
    //  - EMBODIED, the avatar's own location IS it — auto-open on entering
    //    (embody start included), auto-close on stepping out. The camera
    //    cannot close it: the mode exits at EXIT_DIST 34 < CLOSE_CAM_DIST 60.
    //  - OVERVIEW, the explicit choice stands until the explicit close or an
    //    auto-close: camera beyond CLOSE_CAM_DIST, or the tile panned out of
    //    view. There is NO auto-REopen — opening is only ever explicit.
    // Closing is always the crossfade below, never a hard cut.
    if (getGameState().mode === 'embodied') {
      const pos = npcs.positionOf(avatarName);
      if (pos) {
        const t = tileAtCell(cellOf(pos.x, pos.z, CELL));
        if (t && openable(t)) openLocation(t.loc.id);
        else closeOpenLocation();
      }
    } else if (openLocationId) {
      const t = tiles.get(openLocationId);
      const off = t
        ? Math.hypot(engine.target.x - t.center.x, engine.target.z - t.center.z)
        : Infinity;
      if (!t || engine.dist > CLOSE_CAM_DIST || off > CLOSE_TARGET_DIST) {
        closeOpenLocation();
      }
    }

    let open: Tile | null = null;
    let basementOpen: Tile | null = null;
    for (const tile of tiles.values()) {
      // A detail-scene area location (`display: 'shell_area'`, § B6 Nr. 10)
      // fades like a building although its cell is PASSABLE — `isBuilding` is
      // false there by definition, so gating on it alone kept the interior of
      // exactly those locations shut, the one place the fade is supposed to
      // reveal something.
      if (tile.interior && (tile.isBuilding || tile.modelIsShellArea)) {
        // The fade TARGET comes from the singleton — never from camera
        // geometry (Etappe 3). A tile that just lost the state keeps fading
        // out here over the same crossfade the opening one fades in on.
        tile.fadeTarget = tile.loc.id === openLocationId ? 1 : 0;
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
        // The hole/occlusion pass below always assumed "one open tile" — it
        // is now BOUND to the singleton explicitly (fade still gates, so the
        // neighbours only vanish once there is something to see).
        if (tile.loc.id === openLocationId && tile.fade > 0.4) open = tile;
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

    // Doorway thresholds: a hint for the room view, nothing for the map. Shown
    // only where the interior actually resolved — the same 0.5 the room
    // resolution uses, so a marker never floats over a closed shell — and only
    // on the storey the tile displays, exactly like its walls and slabs. Built
    // once per tile, so a frame only flips visibility.
    for (const [locId, root] of doorMarks) {
      const tile = tiles.get(locId);
      const on = !!tile && tile.fade > 0.5;
      root.visible = on;
      if (!tile || !on) continue;
      for (const storey of root.children) {
        storey.visible = storey.userData.level === tile.levelFilter;
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
