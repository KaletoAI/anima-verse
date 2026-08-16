import * as THREE from 'three';
import * as api from './api';
import { initDebug3d } from './debug3d';
import { Engine, isTypingTarget, MIN_DIST } from './scene/engine';
import { drawCallsOf, requestedBackend } from './render/backend';
import { setSurfaceBackend } from './render/surface';
import { initBench } from './render/bench';
import { enterEmbodied, exitEmbodied, type EmbodyDeps } from './game/embody';
import { activityToClipKind, FigureLibrary } from './scene/figures';
import { NpcManager, WALK_SPEED, type NpcState } from './scene/npcs';
import {
  groundScope, slideBlocked, slopeBlocks, terrainBlocks, terrainPace, walkDir,
  type GroundScope,
} from './game/walk';
import { groundLift, type ScenePatch } from './game/ground';
import {
  goalDir, planClickWalk, reachedGoal, walkStalled, STALL_FRAMES,
} from './game/clickmove';
import { talkTargetNear, type TalkCandidate } from './game/proximity';
import { idleRoomWalk, nearestRoomSwitch, type RoomWalkRoom, type RoomWalkState } from './game/roomwalk';
import { elevatorAt, elevatorTargetRoom, type ElevatorStop } from './game/elevator';
import { bodyRadius, clampAgainstWalls, wallSegments, type Segment } from './game/collide';
import { doorMarkers, doorwayBetween, roomDoor, type DoorMarker } from './game/doors';
import { doorwayLock, isLocked, lockReason, unlockedRooms, NO_LOCKS } from './game/locks';
import { getAudio } from './game/audio';
import {
  newFpsMeter, pushFrame, tierCounts, visibleVertices,
  type TierCounts, type TierSample,
} from './game/perfstats';
import { loadPrefs, loadScatterPrefs, PREFS_KEY, scatterLodCfgOf,
  SCATTER_PREFS_KEY } from './game/prefs';
import { fogRects, SHOW_ALL_KEY } from './game/fog';
import type { ExploredCells } from './game/fog';
import { createFogClouds } from './game/fogClouds';
import { hillshadeImage, MAP_RELIEF_Z_FACTOR } from '@anima/scene-render';
import type { MinimapArea, MinimapDot, MinimapRelief } from './game/minimap';
import {
  footprintSignature, locationsSignature, minimapAnchor, minimapFollowStepM,
  minimapRadius, terrainColor, MINIMAP_SIZE_PX,
} from './game/minimap';
import {
  ambientTerrainFor, emptyManifest, newTerrainSwitch, nightForMusic, pickAmbient,
  pickMusic, terrainSwitch, type AudioManifest,
} from './game/soundtrack';
import { applyLevelDisplay, applyNightGlow, applyRoomVisibility, applyTileFade, applyTileOcclusion, applyWallCulling, buildTile, footprintCentre, setSurfaceTextures, terrainLiftAt, tileDirToWorld, tileGroundY, tileToWorld, worldToTile, type Tile } from './scene/tiles';
import { setModelEnvironment } from './scene/glbMaterials';
import { setImpostorRenderer } from './scene/impostors';
import { updateOcclusion } from './scene/occlusion';
import { setPropLoadFocus } from './scene/propAssets';
import { mountScene, SceneLibrary, setSceneModelTier, unmountScene } from './scene/sceneRecipe';
import { anchorRawOpenings, entryOfferNear, freeBoundaryOf, inwardOf, type EntryTile, type LocalOpening } from './game/enterLocation';
import { figureTransition, placementOf, type ShownPlacement } from './game/placement';
import { seededRandom } from './scene/textures';
import { bootStatus, createHud, InfoPanel, OpenViewBadge } from './ui';
import { reportBootStage, setBootNote } from './game/boot';
import { mountHud, mountTitle } from './hud/mount';
import { gameActions, getGameState, perfEnabled, setGameState, setMinimap, setPerfStats, subscribeGameState, uiActions } from './hud/bus';
import type { ModelTier, ScenePayload } from './api';
import { BASE_MARGIN_M, createGround } from './scene/ground';
import { createBackdrop } from './scene/backdrop';
import { clampProgress, pointAtDistance, polylineLength, type MetrePoint } from './scene/travelPath';
import type { MapCharacter, MapTravel, WorldBounds, WorldLocation, WorldMap } from './types';

// --- THE CELL WORLD IS GONE (E4, tasks 2–6) ---------------------------------
//
// Nothing in this file reads a grid key any more, and the `v1()` cast that
// kept the last of them compiling is deleted with the fog (task 6): the tile
// loop and the camera frame went in task 3, the journey bridge in task 4
// (travellers are interpolated along the metre polyline of § A11), the step
// machine in task 5 (free walking over `POST /play/pos`) and the veil in task
// 6 (`world_bounds` minus the known footprints, `game/fog.ts`). The payload
// types have carried metres only since task 2 — `pos_x`/`pos_z`/`yaw_deg`/
// `world_bounds` — so a grid read would not even type-check today.
const WORLDMAP_POLL_MS = 3000;
const ROOMS_POLL_MS = 4000;
/** How long the boot waits for the ground (terrain + relief) before framing
 *  the camera anyway. Long enough for a local request and far too short to
 *  strand the player behind a backend that is restarting. */
const GROUND_BOOT_WAIT_MS = 2500;
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
 *  stay ABOVE the embodied EMBODY_MAX_DIST 34 with headroom, so the open view
 *  can never close under an embodied avatar — 60 leaves 26 m of it, and since
 *  finding B12 the wheel cannot even reach the 34. */
const CLOSE_CAM_DIST = 60;
/** Camera target panned this far off the open tile closes it too — the tile
 *  has left the view.
 *
 *  ABSOLUTE METRES since E4, and measured against the OPEN LOCATION'S OWN
 *  footprint: `3 × plan_width_m`, which on the grid world's 10 m cell is
 *  exactly the 30 m this used to be. It has to follow the footprint, not a
 *  fixed number — panning three metres off a 1 m shrine is leaving it, panning
 *  thirty metres off a 200 m forest is still standing in the middle of it.
 *  Floored, so a location with a tiny anchor cannot close itself on the first
 *  nudge of the mouse. */
const CLOSE_TARGET_FOOTPRINTS = 3;
const CLOSE_TARGET_MIN_M = 12;
const closeTargetDist = (tile: Tile) =>
  Math.max(CLOSE_TARGET_MIN_M, tile.width * CLOSE_TARGET_FOOTPRINTS);

/** Radius around the NEIGHBOUR's centre inside which it counts as standing
 *  between the camera and the open location, as a factor on its own
 *  `plan_width_m`: 1.05 × the FULL edge, not the half — deliberately generous,
 *  and exactly what `CELL * 1.05` was (a radius of one whole cell and a bit
 *  around a cell centre). It is written against the neighbour's own size now,
 *  so a 40 m hall is no longer judged by a 10 m yardstick.
 *  OBSERVATION for task 7: on a very large footprint (a 200 m forest) this
 *  radius is 210 m, so such a location fades away as an "occluder" from far
 *  off. Sizing an area location by its half-width — or by the distance to its
 *  EDGE rather than its centre — is the fix; it needs its own look at the
 *  shell/ground display rules and does not belong in this task. */
const OCCLUDER_RADIUS_FACTOR = 1.05;
/** "Hineinsehen" flies in to this distance — the old panel fly-to, kept. */
const OPEN_FLY_DIST = 15;
/** Far-view building models: hysteresis of the camera-distance tier choice
 *  (Nr. 5). Nearer than NEAR → `full`, farther than FAR → `low`; the 15 m
 *  band between them keeps a camera hovering at the line from thrashing
 *  swaps. Boot overview distance is 70 (> FAR), so the map starts light. */
const BUILDING_TIER_NEAR = 45;
const BUILDING_TIER_FAR = 60;
/** Character figures: same hysteresis idea, tighter band — a 1.70 m figure
 *  carries its detail only up close, and the swap re-downloads a mesh, so the
 *  10 m band keeps a strolling camera from flapping at the line. */
const FIGURE_TIER_NEAR = 25;
const FIGURE_TIER_FAR = 35;
/** Tier re-evaluation cadence — second-scale like the talk target: a swap
 *  loads a GLB anyway, per-frame checks would buy nothing. */
const LOD_TICK_MS = 1000;
/** How often the performance readout is refreshed (Etappe 5). Three to four
 *  updates a second: fast enough that a stutter shows up while it is felt,
 *  slow enough that the digits stay readable instead of blurring. */
const PERF_UI_MS = 300;
/** How often the minimap slice is reconsidered (Etappe 5, task 3). Four times
 *  a second: the picture only changes when the avatar has walked its follow
 *  step or the camera turns, both of which are slower than that — and a slice
 *  published per frame would re-render React sixty times a second for a window
 *  that has not moved. Nothing is published unless something changed. */
const MINIMAP_MS = 250;
/**
 * How far past an opening the "Betreten" walk-in aims, in world metres — far
 * enough inside that the figure visibly crosses the boundary, and WELL under
 * the server's crossing tolerance of 1.5 m (`_POS_OPENING_TOLERANCE_M`).
 *
 * That headroom is the whole point (review finding, E4 task 5). The goal is
 * measured along the opening's inward normal, but the figure arrives on the
 * line it walked in on — an oblique approach ends up offset SIDEWAYS as well,
 * and the two add up as a hypotenuse: at a depth of 1.5 m the crossing point
 * was already 1.68 m from the opening on a plausible approach, which the
 * server refuses with `no_opening` although the offer was perfectly correct.
 * At 0.5 m the same offset leaves ~1.4 m of budget for the sideways part —
 * more than a body width, and more than the walk-in's own arrival threshold.
 */
const OPENING_WALK_IN_M = 0.5;
/** Fallbacks for the two walk limits (§ A15 Nr. 8) when the worldmap payload
 *  carries none — the same numbers `app/core/relief.py` defaults to, so a
 *  client talking to an older server judges the ground the way that server
 *  does. */
const DEFAULT_MAX_STEP_M = 0.4;
const DEFAULT_MAX_SLOPE_DEG = 40;

// --- Doorway markers (E3 acceptance: "you cannot see the doors") ------------
//
// A door is a GAP in the wall segments (§ B1) — the server emits no door
// geometry, and a hole between two wall pieces does not read as a way through.
// So the game layer lays a flat threshold into each gap. This is an OVERLAY,
// exactly like the event pins and the selection ring: nothing here touches the
// recipe, the diorama or any shared render code, and `game/doors.ts` (pure
// maths, hand-checked in client3d/scripts/smoke_walk_math.mjs) says WHERE the gaps are.
//
// One unit quad for every marker of every tile: a threshold differs only in
// position, direction and size, so per-marker geometry would buy nothing.
// Pre-rotated into the XZ plane, so a marker only needs the heading
// (`rotation.y`) — with `rotation.x` also set, the two Euler angles would
// compose and the quad would stand up.
const DOOR_MARK_GEO = new THREE.PlaneGeometry(1, 1).rotateX(-Math.PI / 2);
/** The gold of the UI (`--gold` of the HUD), at the opacity of a hint. */
const DOOR_MARK_MAT = new THREE.MeshBasicMaterial({
  color: 0xf2d98c, transparent: true, opacity: 0.35, depthWrite: false,
});
/** The same threshold, LOCKED (task C2): iron red instead of gold, and denser,
 *  so a barred way reads as a closed door at a glance and not as a dimmer
 *  invitation. Which one a marker wears is pure VIEW state — the server says
 *  WHAT is locked (`/play/scene`), the client says how it looks. */
const DOOR_MARK_LOCKED_MAT = new THREE.MeshBasicMaterial({
  color: 0x9b3b2f, transparent: true, opacity: 0.6, depthWrite: false,
});
/** The two looks of a threshold, CLONED per tile. The door marks of a tile
 *  hang in `tile.group`, and the occlusion fade walks that group and writes
 *  `opacity` into every material it meets (`applyTileOcclusion`) — with the two
 *  singletons up there, one fading tile would dim the thresholds of the whole
 *  map. The pair rides on the marker group; the lock look swaps between the two
 *  by identity, so it has to be the tile's own pair. */
type DoorMarkMats = { open: THREE.Material; locked: THREE.Material };
/** Depth of the threshold ACROSS the wall, as a share of the doorway's width —
 *  never thinner than the wall it fills, or it would vanish inside it. */
const DOOR_MARK_DEPTH = 0.3;
/** How far the threshold quad lies ABOVE the floor the payload names
 *  (`doorways[].base_y`), so it cannot sink into it. Centimetres, not a share
 *  of anything: a storey is three real metres since E4 (k = 1), so two
 *  centimetres are two centimetres. */
const DOOR_MARK_LIFT = 0.02;

/**
 * "Zoom to" a figure. With the camera's 45° vertical FOV the visible height is
 * 2·d·tan(22.5°) ≈ 0.828·d, so 4.5 m frames 3.7 m of world and a 1.70 m
 * character covers ~46 % of the picture: full height with air above and below.
 *
 * ONE distance since E4 (task 3): the multiplication by the scale the figure
 * was DRAWN at is gone with the second scale itself — a figure is 1.70 m in a
 * room as well as on the map (k = 1), so the same distance frames it wherever
 * it stands.
 */
const ZOOM_TO_BASE_DIST = 4.5;
/** Upper clamp of the zoom-to. It no longer has a scale to run away with, but
 *  the clamp stays as the guarantee it always was: 12 < EMBODY_MAX_DIST (34)
 *  keeps a zoom-to inside what the embodied mode may show. */
const ZOOM_TO_MAX_DIST = 12;

// --- Framing the world (§ A12, E4 task 3) -----------------------------------
//
// The map camera is an orbit camera with a 45° VERTICAL field of view
// (`engine.ts`), so a sphere of radius R fits the picture at
//
//     d = R / sin(22.5°) = 2.6131 · R
//
// and the fit below is exactly that, over the bounding sphere of
// `world_bounds` — the simplest framing that can be checked by hand, and the
// one the plan asks for. It is deliberately GENEROUS: the camera looks down at
// an angle, so the ground it actually covers is wider than the sphere test
// assumes, and the horizontal field is wider still on a landscape window.
/** Half the vertical field of view of the map camera, in radians. */
const CAMERA_HALF_FOV = (22.5 * Math.PI) / 180;
/** Air around the bounds, as a factor on the fitted radius. 15 % keeps the
 *  outermost footprint off the edge of the picture. */
const CAMERA_FIT_MARGIN = 1.15;
/** The engine's own MAX_DIST (not exported) — a world larger than this simply
 *  starts as far out as the camera can go. The lower end is `MIN_DIST`, which
 *  the engine DOES export. */
const CAMERA_FIT_MAX = 150;
/** Fit distance for a world with nothing placed: the old boot default, so an
 *  empty world looks exactly as it always did. */
const CAMERA_FIT_EMPTY = 70;

/** Centre of `world_bounds`, or the world origin when nothing is placed — on
 *  the GROUND there (§ A16). The camera looks at a point of the world, and in
 *  a world whose middle is a hilltop the y = 0 plane is somewhere inside the
 *  hill: the view would start looking at the inside of the mountain. `groundY`
 *  is the sampler; a world without a relief answers 0 as it always did. */
function worldCentre(b: WorldBounds | null | undefined,
                     groundY: (x: number, z: number) => number): THREE.Vector3 {
  const x = b ? (b.min_x + b.max_x) / 2 : 0;
  const z = b ? (b.min_z + b.max_z) / 2 : 0;
  return new THREE.Vector3(x, groundY(x, z), z);
}

/** Camera distance at which `world_bounds` fits the picture, clamped to what
 *  the camera can actually be set to: the engine snaps anything below
 *  `MIN_DIST` on its first update anyway, and handing it a smaller number
 *  would mean the boot distance and the camera's distance disagree from frame
 *  one — a tiny world (a single 4 m location) is exactly that case. */
function fitDistance(b: WorldBounds | null | undefined): number {
  if (!b) return CAMERA_FIT_EMPTY;
  const r = Math.hypot(b.max_x - b.min_x, b.max_z - b.min_z) / 2;
  if (!Number.isFinite(r) || r <= 0) return CAMERA_FIT_EMPTY;
  return THREE.MathUtils.clamp(
    (r * CAMERA_FIT_MARGIN) / Math.sin(CAMERA_HALF_FOV),
    MIN_DIST, CAMERA_FIT_MAX);
}

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
      // An expired session is NOT the restarting backend this loop is for, and
      // it is not a defect either: `api.json()` has already fired
      // `auth:required` and the title screen's login form is coming up. The
      // BACKOFF stays — the same request has to run again once the player is
      // back in, and this loop is what runs it — but the console line does
      // not, or a boot spent at the login form would fill the log with
      // warnings about a state the player is being asked about on screen.
      if (!api.isAuthError(e)) {
        console.warn(`[boot] ${what} failed (attempt ${attempt + 1}) — `
          + `retrying in ${wait / 1000} s`, e);
      }
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

/**
 * Marker that survives exactly ONE reload, for the ONE case that still needs
 * one: a re-login as a DIFFERENT player (see `installReloginGate`). The world
 * that stands belongs to the old session, so the page is loaded again — and
 * then the title screen's "Enter world" gate would be a door the player has
 * just walked through. With the marker set, boot goes straight in.
 *
 * It is NOT used anywhere else. The admin's view switch applies live
 * (`applyShowAll`), and a logout must land on the title screen, so
 * `backToTitle` deliberately leaves the marker alone.
 */
const RESUME_KEY = 'av3d.resume';

/**
 * Stand in for the title screen's button as the audio gesture.
 *
 * A browser only lets an `AudioContext` start from a real user gesture, and a
 * resumed page has no button to click. So the next click or key press — the
 * first one, whatever it is — unlocks the engine. Capture phase so nothing can
 * swallow it, one-shot, and `unlock()` is idempotent anyway; until it happens
 * the soundtrack tick simply keeps waiting for `running` (see below).
 */
function unlockAudioOnFirstGesture(): void {
  const once = () => {
    window.removeEventListener('pointerdown', once, true);
    window.removeEventListener('keydown', once, true);
    void getAudio().unlock();
  };
  window.addEventListener('pointerdown', once, true);
  window.addEventListener('keydown', once, true);
}

/**
 * The session died while the world was running — bring the login form back
 * instead of leaving the player in front of a map that quietly stops moving.
 *
 * `auth:required` is fired by BOTH api layers on a 401 (client3d's `api.ts`
 * and the shared `@anima/player-ui`), so this one listener covers the scene
 * polls and the HUD's own calls alike. Deduped: a burst of failing polls is
 * one lost session, not a stack of overlays.
 *
 * A SUCCESSFUL RE-LOGIN RESUMES IN PLACE. There is nothing to rebuild — the
 * world stands, the polls simply start succeeding again with the fresh cookie,
 * and the title screen fades itself out because the boot state is long at
 * 100 %. The one exception is a re-login under ANOTHER name: avatar, role and
 * the whole known-places view were built for the session that is gone, so that
 * case reloads (with the resume marker, so it does not land on the gate).
 */
let reloginOpen = false;
function installReloginGate(username: string): void {
  window.addEventListener('auth:required', () => {
    if (reloginOpen) return;
    reloginOpen = true;
    mountTitle({
      needsLogin: true,
      onLogin: async (u, p) => {
        void getAudio().unlock();
        const user = await api.login(u, p);
        reloginOpen = false;
        if (user.username !== username) {
          sessionStorage.setItem(RESUME_KEY, '1');
          location.reload();
        }
      },
      // Not reachable with `needsLogin` — the screen shows the form, not the
      // button. Kept honest anyway: whoever gets past the gate leaves it open
      // for the next lost session.
      onEnter: () => { reloginOpen = false; },
    });
  });
}

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
    installReloginGate(username);
    void startApp(username, role).catch((e) => {
      console.error('[boot] start failed', e);
      setBootNote({ kind: 'failed' });
    });
  };

  // Coming back from the one reload that is not a fresh start (see
  // RESUME_KEY): the player is signed in and has just clicked their way
  // through a login form — asking them to click "Enter world" as well would be
  // a door in front of a door. The gesture the button would have been is
  // caught from the first click or key press instead.
  if (auth.authenticated && auth.user && sessionStorage.getItem(RESUME_KEY) === '1') {
    sessionStorage.removeItem(RESUME_KEY);
    unlockAudioOnFirstGesture();
    start(auth.user.username, auth.user.role);
    return;
  }

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
  // allowed to have). The stored value is the STARTING view; the menu switches
  // it while the world runs (`applyShowAll`), which is why it is a `let`.
  const isAdmin = role === 'admin';
  let showAll = isAdmin && localStorage.getItem(SHOW_ALL_KEY) === '1';
  const engine = await Engine.create(app, requestedBackend(location.search));
  console.info('[render] backend:', engine.active);
  setSurfaceBackend(engine.active);
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
  // The far scatter billboards are baked with the app's OWN renderer — one
  // WebGL context, and the offscreen passes borrow it between frames
  // (`scene/impostors.ts`). A second renderer would mean a second context and
  // a second copy of every texture the props already uploaded.
  setImpostorRenderer(engine.renderer);
  initBench(engine);   // ?bench=auto / window.__bench — inert without it (render/bench.ts)
  const npcs = new NpcManager(figures);
  // The figures walk on the world's relief (§ A16): the manager re-derives a
  // traveller's point every frame, so it gets the sampler rather than a height
  // per poll. `terrainGround` is created a few lines down — the arrow reads it
  // when a figure is placed, which is long after that.
  //
  // ONE SAMPLER FOR EVERY FIGURE (finding 4, 2026-08-13): `groundY` is the
  // hoisted function below, which asks the TILE inside a footprint and the world
  // field outside it. The world field alone was the height rule of a traveller
  // only, so a walker crossing a footprint border changed rule and jumped —
  // and inside a place it ignored the plate it was walking on.
  npcs.setGroundHeight((x, z) => groundY(x, z),
                       () => terrainGround.heightRevision());
  // …and they move the way the ground under them says (finding 3): the same
  // lookup for every figure, avatar included, out of the ONE terrain payload
  // — together with how far that rule reaches at the point (§ A1.5), which is
  // why the footprints and rooms are asked here and not in the manager.
  npcs.setTerrainMove((x, z) => {
    const type = terrainGround.typeAt(x, z);
    return { anim: type.move_anim, idle: type.idle_anim,
      sink: { move: type.move_sink_m, idle: type.idle_sink_m },
      scope: groundScopeAt(x, z) };
  });
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
    // PLACED = it has a point (§ A1.1). That one test replaces both v1 filters:
    // the grid keys are gone, and a template stands on no map at all — the
    // server leaves its `pos_x`/`pos_z` null, which is exactly what "not
    // placeable" means. The worldmap row no longer carries a template id
    // either (§ A1.9), so nothing is looked up through one any more.
    return map.locations
      .filter((l) => !!footprintCentre(l))
      .map((l) => {
        const detail = details.get(l.id);
        return {
          ...detail,
          ...l,
          rooms: detail?.rooms ?? [],
          description: detail?.description ?? '',
          entry_room: detail?.entry_room,
          // The footprint anchor comes from the worldmap row (the server
          // hoists it out of `map3d`); the detail record's own `map3d` is the
          // fallback for a location the map row states nothing about.
          plan_width_m: l.plan_width_m ?? detail?.map3d?.plan_width_m ?? null,
        } as WorldLocation;
      });
  }
  /** Every location that HAS a tile. Grows while the fog lifts
   *  (`revealLocations` below) — the derived structures are rebuilt from this
   *  one list. */
  const placeable: WorldLocation[] = placeableOf(firstMap, detailById);

  // --- The camera frame (§ A12) ---------------------------------------------
  //
  // The frame comes from `world_bounds` and NOT from the delivered locations:
  // those are only what the avatar knows, so a map framed on them would jump
  // sideways with every place discovered. The bounds are computed over ALL
  // placed locations, in metres, and stay still.
  //
  // `null` (nothing placed at all) is the world ORIGIN at the default
  // distance — the grid world's fallback was a min/max over the placed cells,
  // and with the metre payload `Math.min()` of nothing gave `Infinity` and the
  // camera target became NaN: a world one could not see at all.
  //
  // The centre itself is taken further down, AFTER the ground has been synced:
  // its height comes from the relief (§ A16), and asking before the field has
  // arrived would frame the world on the flat plane under its hills.

  // --- The ground of the metre world (E4 task 2) -----------------------------
  //
  // One base plane over `world_bounds` in the default kind's look, plus the
  // painted areas of `/play/terrain` on top of it. Terrain is never fogged, so
  // it is fetched ONCE and again only when a poll reports a different
  // `terrain_sig` — `sync` decides that itself.
  //
  // The grid world's global GRASS PLANE is gone with the tile loop (task 3):
  // one 600 x 600 m square of canvas grass under everything, which the painted
  // ground replaces in full. Its one other job travels with it — see the
  // basement hole below.
  const terrainGround = createGround();
  engine.scene.add(terrainGround.group);
  // THE DETAIL DISTANCES OF THE SCATTER, read here for the same reason the
  // audio drivers read their own settings (E4-T4): this runs long before the
  // React island that owns the menu mounts, and a ground built at the module's
  // defaults would draw one picture and then jump to the player's on the first
  // menu change. Every later change comes through `applyScatterPrefs` below.
  terrainGround.setScatterLod(scatterLodCfgOf(
    loadScatterPrefs(localStorage.getItem(SCATTER_PREFS_KEY))));
  gameActions.applyScatterPrefs = (p) => {
    terrainGround.setScatterLod(scatterLodCfgOf(p));
  };

  // --- The far backdrop (§ A17) ---------------------------------------------
  //
  // The plate ends at `world_bounds` + 60 m and behind it there is nothing.
  // The backdrop is the mountain silhouette that closes the view there — pure
  // scenery, no collision and no nav, authored per world in the settings and
  // riding along on the worldmap poll. It hangs off the CAMERA TARGET at a
  // fixed 380 m, which is why the frame hook below carries it: the ring is the
  // same picture whether the world is 200 m or 16 km across.
  //
  // Only its POSITION is written — never its rotation. The ridge is built in
  // world directions (§ A1.8), so a group that merely translates keeps north
  // in the north while the player walks, which is the whole point of a
  // horizon. It is deliberately NOT fogged over (`fogGroup` covers the plate
  // only): a silhouette on the horizon gives nothing away.
  const backdrop = createBackdrop();
  engine.scene.add(backdrop.group);
  engine.addFrameHook(() => {
    backdrop.group.position.set(engine.target.x, 0, engine.target.z);
  });

  /** The map payload's own METRE data, kept for the pieces that already speak
   *  metres (the terrain frame, the minimap) while the tile loop waits for
   *  task 3. Both move with every poll. */
  let worldBounds = firstMap.world_bounds;
  let mapLocations = firstMap.locations;
  /** `locationsSignature(mapLocations)`, recomputed with every payload TAKEN
   *  and never in the publish tick — see the minimap slice below. */
  let mapLocSig = locationsSignature(firstMap.locations);
  /** The one way `mapLocations` changes: the derived signature must never lag
   *  behind the list it describes. */
  function takeMapLocations(list: typeof firstMap.locations): void {
    mapLocations = list;
    mapLocSig = locationsSignature(list);
  }
  // THE FIRST SYNC IS AWAITED, with a deadline (E8 task 3): the world's
  // RELIEF comes with it, and the camera below is framed on the centre of the
  // world — which is a point on the ground, not on the y = 0 plane. Waiting
  // for it is a single request on a boot that already awaits half a dozen;
  // waiting for it FOREVER is what the race guards against, because a backend
  // restarting under the boot must not leave the player at a black screen.
  // Whatever arrives late simply drapes the ground a moment later.
  await Promise.race([
    // …and a ground that could not be built must not black out the boot: the
    // sync swallows a failed FETCH itself, but a rebuild that throws (a broken
    // texture, a driver refusing a buffer) would reject into this race.
    terrainGround.sync(firstMap.terrain_sig, worldBounds, mapLocations,
                       firstMap.height_sig ?? '')
      .catch((e) => { console.warn('[ground] first sync failed', e); return false; }),
    sleep(GROUND_BOOT_WAIT_MS),
  ]);
  /** Where the map camera looks at boot — see the frame note above. */
  const center = worldCentre(firstMap.world_bounds,
                             (x, z) => terrainGround.heightAt(x, z));

  // Basement view: the world's ground covers height 0 everywhere, so a storey
  // below ground would stay hidden even after the tile's own plate ghosts
  // (applyTileFade). While the interior view of a tile with a basement is up, a
  // rectangle the size of that tile's FOOTPRINT is discarded out of the ground
  // — the same shader technique as the room clip (@anima/scene-render clip.ts),
  // just inverted: inside the rect goes away. The frame hook steers it per
  // frame (`terrainGround.setHole`); the patch itself moved into `ground.ts`
  // with the plane it belongs to, because the metre world's ground is a base
  // plane PLUS the painted areas and every one of them would roof the cellar.

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
    // Distance to the FOOTPRINT, not to its centre (E4 task 3): footprints
    // have sizes now, and a camera standing on the edge of a 200 m forest is
    // 100 m from its centre — measured that way the one location filling the
    // whole picture would be the one drawn at the low tier. Subtracting the
    // bounding sphere of the square (half its diagonal, `w · 0.7071`) is the
    // same rule the ground scatter uses. The hysteresis is UNTOUCHED: the
    // 45/60 band of the landed LOD strand keeps deciding, it is only fed a
    // distance that means the same thing for every location.
    const d = engine.camera.position.distanceTo(tile.center)
      - tile.width * Math.SQRT1_2;
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
    // Same tick, third driver: character figures by camera distance.
    npcs.tickFigureTiers(engine.camera.position, FIGURE_TIER_NEAR, FIGURE_TIER_FAR);
    // …and fourth: the prop scatter of the painted ground. It used to be a
    // plain on/off switch at the buildings' far distance; it now has a tier
    // swap, an instance budget and a cull line of its own, all of them read
    // from the area's distance in `scene/scatterLod.ts`. The numbers live
    // there and not here because that is the module the hysteresis and the
    // budget are TESTED in — a threshold that decides a swap belongs next to
    // the function that swaps on it. This tick stays the driver.
    terrainGround.tickScatterLod(engine.camera.position);
    // …and fifth, on the same beat: WHERE the fine height tiles are needed
    // (§ A16.3). Embodied that is the ground the avatar stands on, in the
    // overview the point the camera looks at — the same pair `tickSoundtrack`
    // reads for the ambience, and both are computed by the engine anyway, so
    // nothing is rayed for this. The ground itself decides what to do with it:
    // a tick that finds the anchor in the tile it left it in does nothing at
    // all, and a border crossing starts one batch fetch in the background.
    const held = getGameState().mode === 'embodied'
      ? npcs.positionOf(firstMap.avatar) : null;
    terrainGround.setHeightAnchor(held ? held.x : engine.target.x,
                                  held ? held.z : engine.target.z);
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
    // The ground scatter counts too — it is the same question ("how much of
    // what is on screen is still the expensive mesh?"), and a wood of full-tier
    // trees is exactly the load this readout exists to make visible.
    placed.push(...terrainGround.scatterTiers());
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
      calls: drawCallsOf(engine.renderer),
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

  /** Threshold quads per location, one child group per storey. The group hangs
   *  in `tile.group` — TILE-LOCAL, exactly like the walls the gaps were cut
   *  from: the payload states `base_y` in tile metres, and a tile stands on its
   *  own plateau (`footprintCentre`), so anything anchored in world metres
   *  drifts by the plateau height the moment the ground is not flat. The MAP
   *  keeps its own bookkeeping all the same — the group is rebuilt from the
   *  same payload as the tile but on its own occasion (`mountWithDoors`), and
   *  the lock look is repainted by id. */
  const doorMarks = new Map<string, THREE.Group>();
  /** Thresholds at the AUTHORED BOUNDARY OPENINGS of a location, one group per
   *  tile (task C2). They exist only to be shown LOCKED: an open way in needs
   *  no marker (walking through it is the offer), a barred one has to be
   *  visible from the cell next door. Unlike the door marks these stay in
   *  `engine.scene`: they lie on the WORLD ground at the edge of the cell
   *  (`groundY`), which is the neighbour's height and not the tile's plateau. */
  const boundaryMarks = new Map<string, THREE.Group>();
  /** What the locked look was last painted for: the published lock map, the
   *  location it was answered for and the avatar's room. Starts as "nothing",
   *  so the first frame paints once. The LOCATION belongs in here — walking
   *  from one clone into another can leave both the map and the room id
   *  unchanged (clones share their template's room ids), and without it the
   *  place left behind would keep the red doors. */
  let lockPainted: { locks: Record<string, string> | null; loc: string; room: string } = {
    locks: null, loc: '', room: '',
  };

  /** Both threshold overlays of a tile — they are built together and a tile
   *  that goes away takes both with it. Unhooked from whatever they hang in:
   *  the door marks ride in `tile.group`, the boundary marks in `engine.scene`
   *  (they lie on the WORLD ground of the neighbouring cell). */
  function dropDoorMarks(locId: string) {
    for (const map of [doorMarks, boundaryMarks]) {
      const old = map.get(locId);
      if (!old) continue;
      old.parent?.remove(old);
      // The tile's own material pair goes with it — unhooked before the tile is
      // freed, so nothing else ever disposes it (`dropTile`).
      const mats = old.userData.mats as DoorMarkMats | undefined;
      mats?.open.dispose();
      mats?.locked.dispose();
      map.delete(locId);
    }
  }

  /** A doorway as a waypoint for a walking figure: its centre, on the floor the
   *  payload names there (`base_y`, the standing height of the rooms the gap
   *  joins — the server resolves it, § B doorways). `m.mid` is TILE-LOCAL like
   *  every payload vector, so the walk gets it turned into the world, `base_y`
   *  with it: a tile stands on its plateau and a scene metre is not a world
   *  metre. */
  function doorStop(tile: Tile, m: DoorMarker): THREE.Vector3 {
    return tileToWorld(tile, m.mid.x, m.mid.z, m.baseY);
  }

  /** (Re)build the thresholds of one tile from its payload. Called after every
   *  mount, which is also what puts the tile's scene group in place. */
  function buildDoorMarks(tile: Tile, scene: ScenePayload) {
    dropDoorMarks(tile.loc.id);
    if (!tile.isBuilding) return;
    // Everything below stays in the TILE frame — the group hangs in
    // `tile.group`, which carries the footprint's position, its plateau height
    // and its yaw, exactly as it does for the walls. Nothing is turned into the
    // world here and NOTHING is recomputed: `base_y` is the standing height the
    // server resolved (§ B doorways), and the client that used to lift it
    // against its own sampled room floors was mixing tile metres with world
    // metres — the floating thresholds of 2026-08-16.
    const root = new THREE.Group();
    root.visible = false;
    const mats: DoorMarkMats = { open: DOOR_MARK_MAT.clone(),
                                 locked: DOOR_MARK_LOCKED_MAT.clone() };
    root.userData.mats = mats;
    for (const { level } of scene.levels) {
      const marks = doorMarkers(scene, level);
      if (!marks.length) continue;
      // Wall thickness of this storey — the floor is the same for every wall of
      // a recipe, so the first one answers for all of them.
      const thickness = scene.walls.find((w) => w.level === level)?.thickness ?? 0;
      const storey = new THREE.Group();
      storey.userData.level = level;
      for (const m of marks) {
        const mesh = new THREE.Mesh(DOOR_MARK_GEO, mats.open);
        // The rooms ride along so the lock look can be bound LATER, by id: the
        // verdict is per avatar and arrives with its own poll, while this
        // geometry comes from the shared, signature-cached recipe. Nothing
        // about a lock is stored in the payload (§ 3 decision 2).
        mesh.userData.rooms = m.roomIds;
        mesh.scale.set(m.width, 1, Math.max(m.width * DOOR_MARK_DEPTH, thickness));
        // Local +x turned onto the wall direction: a rotation by φ about Y maps
        // (1,0,0) to (cos φ, 0, -sin φ), so φ = atan2(-along.z, along.x). Both
        // the direction and the point stay TILE-LOCAL — the tile's own turn is
        // applied to the whole group, once.
        mesh.rotation.y = Math.atan2(-m.along.z, m.along.x);
        mesh.position.set(m.mid.x, m.baseY + DOOR_MARK_LIFT, m.mid.z);
        // Late, so the quad is not swallowed by the fading walls it lies
        // between, and unpickable — the selection-ring lesson: an overlay that
        // catches the ray steals the click that was meant for the tile.
        mesh.renderOrder = 3;
        mesh.raycast = () => {};
        storey.add(mesh);
      }
      root.add(storey);
    }
    if (!root.children.length) {
      mats.open.dispose();
      mats.locked.dispose();
      return;
    }
    tile.group.add(root);
    doorMarks.set(tile.loc.id, root);
    // Fresh markers wear the open look; the next frame paints the locks (see
    // the frame hook). Repainting HERE would run during boot, where the
    // avatar's name and room are not in scope yet.
    lockPainted = { locks: null, loc: '', room: '' };
  }

  /**
   * The look of a locked threshold (task C2, § 3 decision 2: "a ban is
   * visible"). The material is the ONLY thing that changes — geometry,
   * position and visibility stay exactly what the recipe made them.
   *
   * A doorway wears the locked look when a room BEHIND it is barred for this
   * avatar (`game/locks.ts`, hand-checked in client3d/scripts/smoke_walk_math.mjs); the
   * room the avatar is standing in is left out of that judgement, or every door
   * of a room one may not re-enter would read as a cage.
   *
   * ONLY the avatar's own location is painted locked. The lock state is per
   * avatar and answered for exactly one place (`lockedLoc`, published with the
   * map), and room ids do NOT identify a room across the map: a clone inherits
   * its template's rooms WITH their ids, so binding by id alone would paint the
   * same doorway red in every other clone of that template — a lie about
   * places the avatar is not in. Every other tile is painted open.
   */
  function applyDoorLocks(locId: string) {
    const root = doorMarks.get(locId);
    if (!root) return;
    const tile = tiles.get(locId);
    const state = getGameState();
    const locks = locId === state.lockedLoc ? state.lockedRooms : NO_LOCKS;
    const here = tile ? avatarRoomId(tile) ?? '' : '';
    // The tile's OWN pair (see `DoorMarkMats`) — the two module singletons are
    // the templates, never what a mesh wears.
    const mats = root.userData.mats as DoorMarkMats | undefined;
    if (!mats) return;
    for (const storey of root.children) {
      for (const mesh of storey.children) {
        const rooms = (mesh.userData.rooms as string[] | undefined) ?? [];
        // `null` = open; a locked room WITHOUT a sentence is still locked.
        const locked = doorwayLock(rooms, locks, here) !== null;
        (mesh as THREE.Mesh).material = locked ? mats.locked : mats.open;
      }
    }
  }

  /**
   * Thresholds at the authored boundary openings of one location — built for
   * every tile, SHOWN only while the server refuses this avatar the step into
   * it (the per-frame loop below reads `lockedLocations`).
   *
   * An open way in draws nothing: walking through it is the offer, and a
   * marker on every edge of every neighbour would litter the map. A locked one
   * has to be visible from the cell next door, which is the whole point of
   * "before you walk there".
   */
  function buildBoundaryMarks(tile: Tile, scene: ScenePayload) {
    const openings = scene.boundary_openings ?? [];
    if (!openings.length) return;
    const root = new THREE.Group();
    root.visible = false;
    for (const o of openings) {
      const width = Number(o.width_m);
      if (!Number.isFinite(width) || width <= 0) continue;
      // Payload coordinates are TILE-LOCAL (metres around the tile centre,
      // the SCENE rotation applied) — the footprint transform is applied here,
      // exactly as the entry offer and the walk-in apply it.
      const at = tileToWorld(tile, o.at_world[0], o.at_world[1]);
      const x = at.x;
      const z = at.z;
      const inward = tileDirToWorld(tile, o.inward[0], o.inward[1]);
      const mesh = new THREE.Mesh(DOOR_MARK_GEO, DOOR_MARK_LOCKED_MAT);
      mesh.scale.set(width, 1, Math.max(width * DOOR_MARK_DEPTH, 0.3));
      // The threshold runs ALONG the edge, i.e. across the inward normal:
      // rotating (1,0,0) by φ about Y gives (cos φ, 0, -sin φ), and the
      // direction perpendicular to `inward` is (inward.z, -inward.x).
      mesh.rotation.y = Math.atan2(inward.x, inward.z);
      mesh.position.set(x, groundY(x, z) + 0.05, z);
      mesh.renderOrder = 3;
      mesh.raycast = () => {};
      root.add(mesh);
    }
    if (!root.children.length) return;
    engine.scene.add(root);
    boundaryMarks.set(tile.loc.id, root);
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
      if (tiles.get(tile.loc.id) !== tile) return;
      buildDoorMarks(tile, scene);
      buildBoundaryMarks(tile, scene);
    });
  }

  /** Build a location's tile and hang it in the scene. Boot walks every
   *  placeable location through here, the reveal path (Etappe 5) the newly
   *  discovered ones — the pickables are refreshed by the CALLER, once per
   *  batch. */
  function addTile(loc: WorldLocation) {
    // Placed or not built at all (§ A1.1). `placeableOf` already filters on
    // this, so the guard is the second lock on the one door through which a
    // location without a point could reach the scene — and it SAYS so instead
    // of quietly stacking such a place on the world origin.
    if (!footprintCentre(loc)) {
      console.warn(`[map] ${loc.name || loc.id} has no position (pos_x/pos_z)`
        + ' — no tile drawn');
      return;
    }
    const tile = buildTile(loc);
    tiles.set(loc.id, tile);
    engine.scene.add(tile.group);
    const scene = scenes.get(loc.id);
    if (scene) mountWithDoors(tile, scene);
  }
  for (const loc of placeable) addTile(loc);
  engine.setPickables([...tiles.values()].map((t) => t.group));

  // --- The veil over what the avatar does not know (E4 task 6) -------------
  //
  // The server decides WHAT is known (§ A12) and sends only that; here the
  // rest of the world is covered. WHICH part of the plane that is, is pure
  // maths in `game/fog.ts` (hand-checked in client3d/scripts/smoke_walk_math.mjs) —
  // the world frame grown by the ground's own margin, minus the footprints of
  // the tiles standing. This is only the mesh side: one quad per rectangle,
  // all of them in ONE group that is thrown away and built again whenever the
  // set of known locations moves. Rebuilding wholesale is what keeps it
  // honest: there is no incremental state that could end up showing a veil
  // over a place one already stands in.
  //
  // It is an OVERLAY like the door thresholds: unlit (a veil that took the
  // sun would read as a surface), never written into the depth buffer, and
  // unpickable — a click belongs to the world underneath.
  //
  // WHAT it looks like is `game/fogClouds.ts`: an overcast cloud layer, opaque
  // inside and torn at the rim. The first version was a flat dark quad and
  // read as an empty box (user finding); the material, the texture and the
  // overhang that makes the soft border all live in that module, so this file
  // keeps doing nothing but placing rectangles.
  const clouds = createFogClouds();
  /** A hand's breadth above the world's ground: an unknown place carries no
   *  tile, so the painted ground is the only thing under the veil.
   *
   *  ABOVE THE HIGHEST GROUND IN ITS OWN RECTANGLE since E8 (§ A16): one quad
   *  is flat and the ground under it is not, so a veil hung on the average
   *  height stands in every hill it covers — the mountain comes through the
   *  cloud and shows exactly the topography the fog is there to withhold. */
  const FOG_CLEARANCE_M = 0.05;
  const fogGroup = new THREE.Group();
  engine.scene.add(fogGroup);
  /** The switch of the CURRENT payload: `fogged: false` (the admin's
   *  unfiltered view) means there is no veil at all. The FRAME is
   *  `worldBounds` above — one field for the ground, the minimap and the fog,
   *  because all three cover the same world. */
  let fogged = firstMap.fogged;
  /**
   * The two WALK LIMITS of the world (§ A12): how high a step the figure
   * takes and how steep a slope it climbs. They are SERVER settings — the
   * height gate of `POST /play/pos` judges every reported point with exactly
   * these two numbers (§ A15 Nr. 8) — and they ride along on the worldmap
   * poll, so an admin who changes them reaches a running client within one
   * poll instead of at the next reload. An older server sends neither, and
   * then the built-in defaults are the very ones `app/core/relief.py` falls
   * back to.
   */
  let maxStepHeightM = DEFAULT_MAX_STEP_M;
  let maxSlopeDeg = DEFAULT_MAX_SLOPE_DEG;

  function takeWalkLimits(map: WorldMap): void {
    maxStepHeightM = map.max_step_height_m ?? DEFAULT_MAX_STEP_M;
    maxSlopeDeg = map.max_slope_deg ?? DEFAULT_MAX_SLOPE_DEG;
  }
  takeWalkLimits(firstMap);
  /** The backdrop rides in the SAME payload as the walk limits and for the
   *  same reasons (§ A17): it is a world setting and this poll runs anyway, so
   *  an admin who switches the range on reaches a running client within one
   *  poll. A MISSING block is the ring being off — that is also what an older
   *  server sends, and the two are one state here. `sync` compares the payload
   *  with what stands and rebuilds only on a real change, so nine polls out of
   *  ten cost a string comparison. */
  function takeBackdrop(map: WorldMap): void {
    backdrop.sync(map.backdrop ?? null);
  }
  takeBackdrop(firstMap);
  /** What the veil currently standing was built from. The poll runs every
   *  three seconds and nearly always finds the same inputs — rebuilding
   *  regardless would throw away and re-allocate a dozen geometries per poll
   *  for a picture that does not change. `null` until the first build: every
   *  string is a possible key, so the sentinel must not be one. */
  let fogKey: string | null = null;
  /** The avatar's EXPLORATION MEMORY (§ A12, 2026-08-16): the 64 m cells it has
   *  already stood in, which the veil spares in addition to the footprints. The
   *  server owns it (`app/core/exploration.py`); this is only what arrived
   *  last. Empty until the first fetch answers, and empty forever without an
   *  avatar — both are "the veil as it was before the memory existed". */
  let exploredCells: ExploredCells = new Set<string>();
  /** The signature the current `exploredCells` came with, PREFIXED WITH THE
   *  AVATAR it belongs to. `null` until the first fetch, so that even a server
   *  answering `""` (no avatar) is fetched exactly once instead of never.
   *
   *  The prefix is what makes a TAKEOVER safe: the memory is per character, and
   *  two characters that happen to have walked the same number of cells would
   *  otherwise share a signature and the client would go on showing the
   *  previous one's map. */
  let exploredSig: string | null = null;
  /** Guards against a second fetch while one is in flight — the poll runs every
   *  three seconds and the payload can be hundreds of kilobytes. */
  let exploredPending = false;
  /**
   * Refetch the memory when its signature moved, and rebuild the veil once it
   * is in. The `terrainGround.sync` bargain exactly: the sig rides on the poll,
   * the payload has its own endpoint and is fetched a few times per session.
   *
   * A FAILURE IS SWALLOWED on purpose (a `debug` line, no toast, no offline
   * flag): a veil that still covers ground one has walked is last week's
   * picture and nothing worse, and the signature is deliberately NOT taken
   * over, so the next poll simply tries again.
   */
  function syncExplored(map: WorldMap): void {
    const who = map.avatar ?? '';
    const sig = `${who}|${map.explored_sig ?? ''}`;
    if (sig === exploredSig || exploredPending) return;
    exploredPending = true;
    void api.fetchExplored().then((payload) => {
      // The payload's OWN signature, not the poll's: between the poll and this
      // answer the avatar may have walked into another cell, and taking the
      // poll's would leave the client one refetch short of the truth forever.
      exploredSig = `${who}|${payload.sig}`;
      exploredCells = new Set(payload.cells);
      rebuildFog();
    }).catch((e) => {
      console.debug('explored memory fetch failed', e);
    }).finally(() => {
      exploredPending = false;
    });
  }
  /** The known footprints, as the veil is cut around them: the tile's OWN
   *  centre, edge and rotation — what is DRAWN, so the hole and the tile in it
   *  can never disagree (a location with no `plan_width_m` is drawn at the
   *  fallback edge and its hole is that size too). */
  const fogFootprints = () => [...tiles.values()].map(
    (t) => ({ x: t.center.x, z: t.center.z, width: t.width, yaw: t.yaw }));
  function rebuildFog() {
    const frame = worldBounds
      ? `${worldBounds.min_x},${worldBounds.min_z},${worldBounds.max_x},${worldBounds.max_z}` : '';
    // Read ONCE: the key and the geometry have to describe the same instant,
    // and walking the tiles twice per poll for the same answer is work for
    // nothing.
    const holeList = fogFootprints();
    // The key carries the FOOTPRINTS, not just the location ids: a place
    // resized or turned in the admin keeps its id, and a veil keyed on ids
    // alone would go on covering the metres the tile has just grown into
    // until some other location appeared. Centimetres are enough — nothing
    // finer is visible under a cloud edge that is metres wide.
    const holes = holeList
      .map((f) => `${f.x.toFixed(2)},${f.z.toFixed(2)},${f.width.toFixed(2)},${f.yaw.toFixed(3)}`)
      .sort().join(' ');
    // The RELIEF is part of the key: the veil's height comes from the field,
    // and the field arrives well after the first fog was built (its own fetch
    // on its own signature). Without this the clouds would keep the flat
    // world's height until some location happened to move.
    // The MEMORY is part of the key for the same reason the relief is: it
    // arrives on its own fetch, well after the first veil was built. Its SIZE
    // is enough of a key — the set only ever grows (the server never deletes a
    // cell, § A12), so a different count is a different set, and hashing tens
    // of thousands of keys on every poll to learn that would be the one
    // expensive thing in this function.
    const key = `${fogged}|${frame}|${holes}|${terrainGround.heightRevision()}`
      + `|${exploredCells.size}`;
    if (key === fogKey) return;
    fogKey = key;
    for (const child of fogGroup.children) {
      (child as THREE.Mesh).geometry.dispose();
    }
    fogGroup.clear();
    if (!fogged) return;
    // The ground's own relief decides which rectangles are TILED (E8 task 5):
    // a veil over level ground stays one quad however wide it is, and only
    // where the field moves is it cut into `FOG_TILE_M` pieces. Handing the
    // query in keeps `game/fog.ts` importless, exactly like the footprints.
    for (const r of fogRects(worldBounds, holeList, BASE_MARGIN_M,
                             (x0, z0, x1, z1) =>
                               terrainGround.heightRangeIn(x0, z0, x1, z1),
                             exploredCells)) {
      // The geometry comes out LARGER than the rectangle — the cloud edge
      // needs room to fade, and neighbouring rectangles overlap into each
      // other so no seam opens between them (see `fogClouds.ts`). The centre
      // is unaffected: the overhang is symmetric.
      const quad = new THREE.Mesh(clouds.quadGeometry(r.w, r.d), clouds.material);
      // `x`/`z` is the rectangle's MINIMUM corner, the quad hangs on its
      // middle — half its extents further along, in plain metres. Its HEIGHT
      // is the highest ground inside that very rectangle plus the clearance:
      // per rectangle, because the veil is many quads over one landscape and a
      // single world-wide height would float the whole cover over the plain.
      const fogY = terrainGround.maxHeightIn(r.x, r.z, r.x + r.w, r.z + r.d)
        + FOG_CLEARANCE_M;
      quad.position.set(r.x + r.w / 2, fogY, r.z + r.d / 2);
      quad.renderOrder = 1;   // under the thresholds (3) and the pins
      quad.raycast = () => {};
      fogGroup.add(quad);
    }
  }
  rebuildFog();
  // The memory the veil is cut around, on its first fetch — deliberately not
  // awaited: the map must stand now, and the walked ground clears one fetch
  // later (the same deal `terrainGround.sync` gets for the relief).
  syncExplored(firstMap);
  // THE VEIL IS AN OVERVIEW DEVICE (finding B14, the user's option 1).
  //
  // `fogRects` subtracts the footprints of the KNOWN places from the world
  // frame and nothing else — there is no memory of ground one has walked. That
  // is a map legend, and it is wrong under a figure's feet: between two places
  // the world stays covered forever (a dark wood with no location in it never
  // clears, however far one walks), and the cover lies as an opaque surface
  // 5 cm above the ground, made for a camera 70 m up. In control, with 7 m of
  // camera distance, one walks INTO it at a grazing angle.
  //
  // Leaving it out in control leaks nothing: an unknown place is not in the
  // payload at all, there is no tile for it, so what shows underneath is the
  // painted terrain the server always delivers — which § A12 keeps unfogged on
  // purpose, "so the map stays a landscape in the fog instead of an empty
  // plane". The overview keeps its veil, and switching back brings it straight
  // back.
  //
  // Option 2 — a fog with a MEMORY, walked ground permanently free and
  // persisted like `known_locations` — LANDED on 2026-08-16 and stands beside
  // option 1 rather than replacing it: the overview keeps its veil, and that
  // veil now spares the 64 m cells the avatar has already been in on top of the
  // known footprints (`exploredCells` above, § A12). Close up there is still no
  // veil at all, for the reasons in the paragraph before this one.
  //
  // The cover drifts and takes the time of day. Both are one uniform each, so
  // this rides in the engine's frame loop rather than bringing a timer: with
  // no fog standing there is nothing to advance at all.
  engine.addFrameHook((dt) => {
    fogGroup.visible = getGameState().mode !== 'embodied';
    if (fogGroup.visible && fogGroup.children.length) {
      clouds.advance(dt, engine.nightFactor);
    }
  });
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
  /** The GEOMETRY each tile stands on (`footprintSignature`) — centre,
   *  rotation and footprint edge, taken from the WORLDMAP row, which is the
   *  authority for all four (`placeableOf` merges it over the detail record).
   *  A second signature beside `locSig` on purpose: that one watches `map3d`
   *  and the room layouts and comes from `/world/locations` every ten
   *  seconds, while these four numbers are not in `map3d` at all and arrive
   *  with every worldmap poll. Finding B13 is what happens without it — a
   *  location moved in the world editor kept its tile at the old metre while
   *  the server judged walking and entering against the new footprint. */
  const geomSig = new Map(firstMap.locations.map((l) => [l.id, footprintSignature(l)]));
  /** Take the geometry of a payload as the state the tiles were built from —
   *  called wherever tiles are MOUNTED (boot above, `revealBatch` below), so
   *  the next poll compares against the payload the tile really came from and
   *  not against a merged record whose `plan_width_m` fallback would look like
   *  a move. Rows without a tile are stored too: they cost a string and save
   *  the reveal path a lookup. */
  const noteGeometry = (rows: typeof firstMap.locations) => {
    for (const row of rows) geomSig.set(row.id, footprintSignature(row));
  };
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
   *  (game/collide.ts). The payload is TILE-LOCAL, so the cached segments are
   *  world lines derived from the tile's centre AND its turn — which means it
   *  is invalidated wherever the tile is rebuilt, not only where its payload
   *  changes: `onScene` (a moved scene signature), `dropTile` (the place is
   *  gone) and `rebuildMovedTiles` (the place was moved or turned in the
   *  editor — finding B13's other half: the tile followed, the walls did not,
   *  and the avatar went on clamping against the old building's outline). */
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
      // Collect first, build after. The neighbourhood grid this used to feed
      // (and the coast blends baked from it) is gone with the cell — the
      // ground between the places is the painted terrain of `/play/terrain`
      // now, and a changed `terrain`/`surface_kind` simply repaints the one
      // tile it belongs to, through the ordinary signature rebuild.
      const dirty: [Tile, WorldLocation][] = [];
      for (const [id, tile] of tiles) {
        const detail = freshById.get(id) ?? freshById.get(tile.loc.template_location_id || '');
        if (!detail) continue;
        const sig = sigOf(detail);
        if (locSig.get(id) === sig) continue;
        locSig.set(id, sig);
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
      for (const [tile, loc] of dirty) rebuildTile(tile, loc);
    } catch { /* Server kurz weg -> nächster Poll */ }
  }
  setInterval(pollLocations, 10_000);

  // The cell PATHFINDER lived here (`publishPathGrid` + `scene/pathfind.ts`):
  // an A* over the grid so NPCs walked around buildings instead of through
  // them. Both are DELETED with E4 task 5. It was built from `grid_x`/`grid_y`,
  // which the server stopped sending in E3 — every cell it planned over was
  // `undefined` — and E4 walks the free plane: the avatar takes the straight
  // line and slides (`game/walk.slideBlocked`), NPCs follow the server's own
  // metre polyline (§ A11). A pathfinder over the free plane is E5+ work
  // ("Client-A* fürs Klick-Laufen: nach Bedarf"), and it would have to be one
  // the server's position gate can follow — not this one.
  engine.target.copy(center);
  engine.dist = engine.targetDist = fitDistance(firstMap.world_bounds);

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
  /** Fly-in distance of the panel buttons: never FARTHER than where the camera
   *  already stands. `flyTo` sets the distance unconditionally, so a fixed
   *  OPEN_FLY_DIST pushed a camera that was already closer back out — "look
   *  inside" would zoom OUT. */
  const flyInDist = () => Math.min(engine.targetDist, OPEN_FLY_DIST);
  panel.onZoomTo = (id) => {
    const tile = tiles.get(id);
    if (tile) engine.flyTo(tile.center.clone(), flyInDist());
  };
  // "Hineinsehen" (Etappe 3): the old fly-to stays part of it — fly in AND
  // open the detail view. Pure view state, no server call.
  panel.onLookInside = (id) => {
    const tile = tiles.get(id);
    if (!tile) return;
    engine.flyTo(tile.center.clone(), flyInDist());
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
    // ONE scale (E4): a figure is 1.70 m indoors and out, so the framing is
    // the same wherever it stands — the drawn-scale factor this used to carry
    // was the interior compression, and there is none any more.
    // Aim at the middle of the body, not at the feet — `positionOf` returns the
    // root, i.e. ground level, and from this close the figure would run out of
    // the top of the frame. Half of a 1.70 m character is 0.85 m.
    p.y += 0.85;
    engine.flyTo(p, THREE.MathUtils.clamp(ZOOM_TO_BASE_DIST, MIN_DIST, ZOOM_TO_MAX_DIST));
  };
  // The marker follows the BUS, not the click: closing the plaque happens on
  // the React side without a gameAction, and the ring has to go with it.
  subscribeGameState(() => {
    npcs.setSelected(getGameState().selected?.char.name ?? null);
  });

  // --- Embodied mode (E3-T2) -----------------------------------------------
  // Everything the mode needs is the avatar's live position: enter/leave are
  // camera moves, and since finding B12 the wheel is bound instead of being a
  // third, silent way out (`engine.zoomCap`, set by the mode itself).
  const embody: EmbodyDeps = {
    engine,
    // `firstMap` on purpose: the deps object is built before `lastMap` exists,
    // and the avatar of a session does not change under us.
    avatarPos: () => npcs.positionOf(firstMap.avatar),
  };
  /** Has the player been told, THIS time in the mode, what the zoom wall is?
   *  One sentence per session in control: the wall itself is the answer from
   *  then on, and a toast on every notch of the wheel would be noise. */
  let zoomCapHinted = false;
  engine.onZoomCapped = () => {
    if (zoomCapHinted || getGameState().mode !== 'embodied') return;
    zoomCapHinted = true;
    uiActions.toast?.('That is as far out as you can look while in control — '
      + 'press Esc to leave control.', true);
  };
  gameActions.enterEmbodied = () => { zoomCapHinted = false; enterEmbodied(embody); };
  gameActions.exitEmbodied = () => exitEmbodied(embody);
  // "Take control" from the HUD's Self panel: the way back into the avatar that
  // does NOT need a clickable figure. Since a character in a closed room is not
  // drawn at all (see `computeNpcStates`) — the avatar included — the plaque
  // route can be unreachable, so the HUD offers the same step off the panel one
  // always has. Three moves, in the order the player would make them by hand:
  // fly to the avatar's place, open its detail view (the very path the info
  // panel's "look inside" takes) and hand the figure over. Entering is the
  // registered action, not a second call of `enterEmbodied`, so there stays ONE
  // way into the mode — the camera ride, the storey following and the takeover
  // all come with it.
  gameActions.takeControl = () => {
    const me = lastMap?.characters.find((c) => c.name === lastMap!.avatar);
    const tile = me ? tiles.get(me.location_id) : undefined;
    // WILDERNESS IS A PLACE (E4 task 5). An avatar without a tile used to be
    // refused here — in the grid world it meant "no cell, nothing to fly to".
    // On the metre plane a location is not required to stand somewhere: an
    // avatar in the open, or one the travel ticker has on the road, has a
    // POINT and that point is a perfectly good anchor to embody at. Taking
    // over a traveller also ENDS its journey, and it does so through the
    // ordinary channel — the first position report the walking hook sends
    // (free walking overrides travel, `POST /play/pos`).
    const at = me?.pos ?? (tile ? { x: tile.center.x, z: tile.center.z } : null);
    // Only now is there really nothing: no tile AND no point (an unplaced
    // location, a fogged place the map has not built). Say so instead of
    // doing half of it.
    if (!at) {
      uiActions.toast?.('Your avatar is not on the map yet.', true);
      return;
    }
    engine.flyTo(new THREE.Vector3(at.x, groundY(at.x, at.z), at.z), flyInDist());
    // The detail view belongs to a LOCATION — out in the open there is none
    // to open, and the camera ride above is the whole of the arrival.
    if (tile) openLocation(tile.loc.id);
    gameActions.enterEmbodied?.();
    // No figure on the map yet (the model is still loading): entering is a
    // no-op then, and the view has already flown in — the same message says
    // what happened, and pressing again once the figure is there works.
    if (getGameState().mode !== 'embodied') {
      uiActions.toast?.('Your avatar is not on the map yet.', true);
    }
  };
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
  /** Counts the changes of the VIEW (`applyShowAll`). A poll that started
   *  under the old view is dropped when it comes back under the new one — the
   *  two payloads describe different worlds. */
  let viewRev = 0;
  const roomOf = new Map<string, string>(); // Charaktername -> Raum (ID oder Name)
  /** How each figure was placed LAST TIME: the room it was drawn in (null = on
   *  the ground) and whether its location's interior was revealed then. Both
   *  halves are needed to tell a real room change from a mere visibility
   *  change — see `game/placement.figureTransition` (finding B5). */
  const shownPlacement = new Map<string, ShownPlacement>();
  /** The drawn room of a figure — `null` while it stands outside, and also
   *  while nothing has been drawn for it yet. */
  const shownRoomOf = (name: string): string | null =>
    shownPlacement.get(name)?.room ?? null;
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

  /**
   * Rebuild every tile whose FOOTPRINT has moved (finding B13).
   *
   * A location can be dragged to another metre, turned or resized in the world
   * editor while clients are running, and nothing noticed: the layout poll
   * (`pollLocations`) keys on `map3d` + the room layouts, and none of the four
   * geometry numbers lives there — they are columns of the location row
   * (§ A1.1). The tile therefore kept standing where it was built, which is a
   * disagreement with the server about where the walls of a place are: the
   * walker judges "may I walk here" against the OLD footprint
   * (`blockedFor`/`freeBoundary`), the entry offer computes its opening points
   * around the OLD centre, and `POST /play/pos` answers `no_opening` for a
   * step the client thought was open ground — from every side, at every
   * corner, until the browser was reloaded.
   *
   * ONLY the geometry is taken over. Everything else on `tile.loc` is the more
   * recent merge (`pollLocations` writes rooms, `map3d`, `entry_room`,
   * `terrain` into it from a fresher `/world/locations` than the boot
   * snapshot `detailById` still holds), and re-merging the payload here would
   * throw those away.
   */
  function rebuildMovedTiles(map: WorldMap): void {
    for (const row of map.locations) {
      const tile = tiles.get(row.id);
      if (!tile) continue;
      const sig = footprintSignature(row);
      const before = geomSig.get(row.id);
      geomSig.set(row.id, sig);
      // Unknown = a tile nothing has recorded geometry for. It cannot happen
      // (every mounting path calls `noteGeometry`), and if it ever does, the
      // honest answer is to adopt the signature rather than to rebuild a tile
      // against a state nobody compared it with.
      if (before === undefined || before === sig) continue;
      // The cached wall lines were computed against the OLD centre and turn —
      // see `wallCache`. They go with the tile, or the avatar keeps colliding
      // with the outline of a building that has moved away underneath it.
      wallCache.delete(row.id);
      rebuildTile(tile, {
        ...tile.loc,
        pos_x: row.pos_x,
        pos_z: row.pos_z,
        yaw_deg: row.yaw_deg,
        plan_width_m: row.plan_width_m,
      });
    }
  }

  async function pollWorldMap() {
    let map: WorldMap;
    const rev = viewRev;
    try {
      map = await api.getWorldMap(showAll);
      // The view was switched while this was in flight (the admin's "show all"):
      // this payload belongs to the OTHER view and would re-reveal tiles the
      // switch has just taken away. The switch published its own snapshot.
      if (rev !== viewRev) return;
      lastMap = map;
      mapStamp += 1;
      hud.setOnline(true);
      takeRoomsFrom(map);
      updatePins(map);
      refreshSelection(map);
      reconcileAvatarPos(map);    // server moved the avatar? (E4-T5)
      announceSceneProblems(map); // what the composer found wrong (§ 4.3)
    } catch (e) {
      // An expired session is not an unreachable server: the dot stays as it
      // was and the `auth:required` listener (boot) brings the login form up.
      // Painting it red here is what made a lost login look like a dead
      // backend.
      if (!api.isAuthError(e)) hud.setOnline(false);
      return;
    }
    // The metre side of the payload: the world frame, the places as the
    // minimap knows them, and the terrain signature that decides whether the
    // ground has to be refetched (E4 task 2). `sync` is a no-op on an
    // unchanged signature — terrain is never fogged and never polled.
    worldBounds = map.world_bounds;
    takeMapLocations(map.locations);
    // The locations travel WITH it: their footprints are what the scatter
    // keeps clear (finding B18), and a place that moved is a rebuild trigger
    // of its own — `terrain_sig` does not move when a location does.
    void terrainGround.sync(map.terrain_sig, worldBounds, mapLocations,
                            map.height_sig ?? '');
    takeWalkLimits(map);
    takeBackdrop(map);
    rebuildMovedTiles(map);
    // The fog of war (Etappe 5) moves WHILE one plays: a place the avatar has
    // just discovered is simply in the payload from one poll to the next. The
    // switch travels with it, and the frame is the one just taken over — the
    // bounds are computed unfiltered and do not move while one discovers, but
    // a world can gain a location anywhere at any time.
    fogged = map.fogged;
    // The MEMORY grows while one walks — the server marks every accepted point
    // (§ A12), so `explored_sig` moves and the cells are refetched. Before
    // `rebuildFog`, so a poll that changes nothing else still costs only the
    // signature comparison.
    syncExplored(map);
    rebuildFog();   // a no-op unless the frame, the switch or a footprint moved
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
    // The far range takes the time of day from the SAME hook (§ A17): its
    // material is unlit, so without this it would keep its daylight rock
    // colour and glow over a dark world. The engine has just set the sky it is
    // mixed towards, so reading the background here is reading the current
    // sky, not last hour's.
    backdrop.setDayNight(night, engine.scene.background as THREE.Color);
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
  /** Where a character stands on a tile, in TILE-LOCAL metres — the caller
   *  turns it into the world with the footprint (`tileToWorld`). The row in
   *  front of a building scales with the footprint (0.36 of the edge, which is
   *  the old 3.6 m on a 10 m location); the ring around an open place stays an
   *  absolute 2.6 m, because it is a huddle of people and not a property line. */
  function slotOffset(tile: Tile, index: number, count: number): { x: number; z: number } {
    if (tile.isBuilding) {
      // vor dem Gebäude aufreihen (Südseite)
      return { x: (index - (count - 1) / 2) * 2.3, z: tile.width * 0.36 };
    }
    const angle = (index / Math.max(count, 1)) * Math.PI * 2;
    return { x: Math.cos(angle) * 2.6, z: Math.sin(angle) * 2.6 };
  }

  // Raum-Mitbewohner im kleinen Kreis anordnen statt aufeinander zu stehen
  function roomSlot(index: number, count: number, name: string): THREE.Vector3 {
    if (count <= 1) return new THREE.Vector3(0, 0, 0.2);
    const rnd = seededRandom('jitter:' + name);
    const angle = (index / count) * Math.PI * 2 + rnd() * 0.5;
    return new THREE.Vector3(Math.cos(angle) * 1.0, 0, Math.sin(angle) * 0.8);
  }

  /**
   * Render state of a character on a JOURNEY (contract § A11), or null when it
   * is not travelling — then the location placement below takes over.
   *
   * With `waypoints` the position is the point `progress_m` metres along the
   * metre polyline; the route travels into the NpcManager, which keeps walking
   * it between polls at `pace_m_s_real ?? speed_m_s_real` (the SEGMENT pace
   * first: the terrain speed factor sits in it, the nominal journey speed
   * knows nothing about the ground).
   *
   * WITHOUT them — the fog nulls `waypoints` for every traveller but the
   * avatar (§ A12) — there is no route at all: the figure stands at its `pos`,
   * no line is drawn and nothing is extrapolated. That is the point of the
   * rule: the route ends at the target's door and would be a metre-exact map
   * marker for a place the avatar may not know.
   */
  function travellerState(c: MapCharacter, stamp: number): NpcState | null {
    const tr: MapTravel | null = c.travel ?? null;
    if (!tr) return null;
    const wp = tr.waypoints;
    // The fog thins route AND distance out together (§ A12); a route without
    // a `progress_m` is therefore a fogged row, not a walkable line.
    if (wp && wp.length >= 2 && tr.progress_m !== null) {
      const points = wp.map((p) => [p[0], p[1]] as MetrePoint);
      const totalM = polylineLength(points);
      const progressM = clampProgress(tr.progress_m, totalM);
      const at = pointAtDistance(points, progressM)!;
      return {
        char: c,
        // THE WORLD RELIEF, not a tile's baked ground skin: a journey runs
        // over the open terrain between the locations, where the heightfield
        // is the only surface there is (`ground_y` discipline, § A16). The
        // figure keeps sampling it while it walks the polyline between polls —
        // that half lives in `npcs.ts`, on the same sampler.
        pos: new THREE.Vector3(at[0], terrainGround.heightAt(at[0], at[1]), at[1]),
        route: { points, totalM, progressM,
                 rateMS: tr.pace_m_s_real ?? tr.speed_m_s_real, stamp },
      };
    }
    // Fogged route, or a degenerate one-point line (a journey without a way):
    // the payload's own point is the whole answer.
    if (c.pos) {
      return { char: c,
               pos: new THREE.Vector3(c.pos.x,
                                      terrainGround.heightAt(c.pos.x, c.pos.z),
                                      c.pos.z) };
    }
    return null;
  }

  function computeNpcStates(map: WorldMap): NpcState[] {
    const byLoc = new Map<string, MapCharacter[]>();
    hiddenChars.clear();
    const states: NpcState[] = [];
    for (const c of map.characters) {
      // Travellers FIRST, and outside the grouping by location: on its way a
      // character stands in the WILDERNESS (`location_id: ""`, § A11), which
      // is no tile — grouping by location would drop it off the map for the
      // whole journey.
      const travelling = travellerState(c, mapStamp);
      if (travelling) {
        states.push(travelling);
        shownPlacement.set(c.name, { room: null, interiorShown: false });
        continue;
      }
      // WILDERNESS IS A PLACE (finding B2). Standing outside every footprint
      // is legal since E1, and a character there has no tile to be grouped
      // under — the old `continue` dropped it from the list and `npcs.update`
      // removed its figure, the player's own included. `pos` is the whole
      // answer then, on the open ground plane like a traveller's.
      const placement = placementOf(tiles.has(c.location_id), c.pos);
      if (placement.kind === 'free') {
        // Straight out of a ROOM into the open is a snap, not a walk: the
        // straight line from a room spot to a point outside the building runs
        // through its walls, and there is no door route to the wilderness.
        // Coming from the open ground the figure keeps walking as before.
        const wasInRoom = shownPlacement.get(c.name)?.room ?? null;
        states.push({
          char: c,
          // On the open ground plane like a traveller's — which since § A16 is
          // the world's relief, sampled at the character's own point.
          pos: new THREE.Vector3(placement.pos.x,
                                 terrainGround.heightAt(placement.pos.x, placement.pos.z),
                                 placement.pos.z),
          snap: wasInRoom !== null,
        });
        shownPlacement.set(c.name, { room: null, interiorShown: false });
        continue;
      }
      if (placement.kind === 'offmap') continue;
      (byLoc.get(c.location_id) ?? byLoc.set(c.location_id, []).get(c.location_id)!).push(c);
    }
    for (const [locId, chars] of byLoc) {
      const tile = tiles.get(locId)!;
      chars.sort((a, b) => a.name.localeCompare(b.name));
      const roomMates = new Map<string, string[]>();
      for (const c of chars) {
        const room = roomOf.get(c.name);
        if (room) (roomMates.get(room) ?? roomMates.set(room, []).get(room)!).push(c.name);
      }
      chars.forEach((c, i) => {
        // Travellers never get here — `travellerState` took them out of the
        // grouping above, route and all (contract § A11: the server computes,
        // we render).
        let pos: THREE.Vector3;
        let via: THREE.Vector3[] | undefined;
        let face: THREE.Vector3 | undefined;
        let lean: { tilt: number; roll: number } | undefined;
        const room = roomOf.get(c.name);
        const roomCenter = room ? tile.roomCenters.get(room) : undefined;
        // Is the inside of this location REVEALED for this character right
        // now? Permanently visible rooms count at every zoom level. This is a
        // pure VIEW state — it says nothing about where the character is, only
        // about whether the client can draw it there (finding B5).
        const interiorShown = tile.fade > 0.5
          || (!!room && tile.alwaysVisibleRooms.has(room));
        const inRoom = roomCenter && room && interiorShown ? room : null;
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
              // `facing` is TILE-LOCAL like every other payload angle, and a
              // gaze is a DIRECTION: it turns with the footprint but is not
              // shifted by its centre. The position two lines up went through
              // `tileToWorld`; without the same turn here a curated figure on
              // a rotated location sits in the right chair looking off by the
              // location's yaw. The counter-sense of `facing` itself
              // (scene_recipe.py `_marker_facing`) is untouched — this changes
              // the FRAME, not the convention.
              const a = THREE.MathUtils.degToRad(m.rotation);
              const dir = tileDirToWorld(tile, Math.sin(a), Math.cos(a));
              face = new THREE.Vector3(dir.x, 0, dir.z);
            }
            if (m.tilt || m.roll) lean = { tilt: m.tilt || 0, roll: m.roll || 0 };
          } else if (pool?.length) {
            pos = pool[idx % pool.length].clone();
          } else if (spots?.length) {
            // abgetastete freie Stellfläche im Raum-Modell (nicht in Möbeln)
            pos = spots[idx % spots.length].clone();
          } else {
            // No room scale on the offset any anymore: a metre in the room IS a
            // metre on the map (k = 1), so the huddle radius is the metre
            // count `roomSlot` states.
            pos = roomCenter.clone().add(roomSlot(idx, mates.length, c.name));
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
        } else {
          const slot = slotOffset(tile, i, chars.length);
          pos = tileToWorld(tile, slot.x, slot.z);
          // Eingebackene Bodenhaut des Gebäude-Meshes: auf die Oberfläche
          // stellen statt bei y=0 darin zu versinken (Befund Kira).
          pos.setY(tileGroundY(tile, pos));
        }
        // Door routing: a real room change walks through the DOOR, not through
        // a wall. Which door is a payload question, not a heuristic
        // (plan-betreten-und-tueren.md § 4.1): two rooms that share a wall have
        // ONE doorway naming both, and that is the whole route. Otherwise the
        // figure leaves through its room's own door and enters through the
        // other's — which is also the case for room ↔ ground, where the ground
        // has no doorway of its own and the room's OUTSIDE door is the way. A
        // storey change adds the lift (AV3D-12); rooms joined by a doorway are
        // on one storey by construction, so only the two-door route can need it.
        //
        // A VISIBILITY change is not a room change (finding B5): opening or
        // closing the detail view moves nobody, it only decides whether the
        // client can draw a character in the room it has been standing in all
        // along. Routed like a room change it walked the figure in from the
        // outdoor huddle spot through the front door. `figureTransition` keeps
        // the two apart; a snap places the figure without a walk.
        const prevShown = shownPlacement.get(c.name);
        const nextShown: ShownPlacement = { room: inRoom, interiorShown };
        const transition = figureTransition(prevShown, nextShown);
        if (transition !== 'stay') shownPlacement.set(c.name, nextShown);
        if (transition === 'route') {
          const scene = scenes.get(tile.loc.id);
          // Asked in the TILE frame (no origin): `doorStop` turns the marker
          // into the world with the footprint transform. Handing the centre in
          // here as well would apply the offset TWICE — and on a turned
          // location it would also turn an already-absolute point, which is
          // how a doorway ends up on the far side of the map.
          // `route` implies a previous placement (`figureTransition`), so the
          // room it was drawn in is the start of the walk.
          const prevRoom = prevShown?.room ?? null;
          const from = roomIdOf(tile, prevRoom);
          const to = roomIdOf(tile, inRoom);
          const levelOf = (r: string | null) => (r ? tile.roomLevels.get(r) ?? 0 : 0);
          const lf = levelOf(prevRoom), lt = levelOf(inRoom);
          const stops: THREE.Vector3[] = [];
          const shared = from && to ? doorwayBetween(scene, from, to) : null;
          if (shared) {
            stops.push(doorStop(tile, shared));
          } else {
            const leave = from ? roomDoor(scene, from) : null;
            if (leave) stops.push(doorStop(tile, leave));            // alten Raum verlassen
            if (lf !== lt && tile.elevatorStops) {
              const a = tile.elevatorStops.get(lf) ?? tile.elevatorStops.get(0);
              const b = tile.elevatorStops.get(lt) ?? tile.elevatorStops.get(0);
              if (a) stops.push(a.clone());                          // Fahrstuhl einsteigen
              if (b) stops.push(b.clone());                          // Fahrt zur Ziel-Etage
            }
            const enter = to ? roomDoor(scene, to) : null;
            if (enter) stops.push(doorStop(tile, enter));            // neuen Raum betreten
          }
          if (stops.length) via = stops;
        }
        // A destination without a running journey (the target survived, the
        // journey did not): no line — that belongs to the ROUTE now — but the
        // figure still looks the way it means to go, or its standing animation
        // points at a random neighbour.
        const targetTile = c.movement_target_id ? tiles.get(c.movement_target_id) : undefined;
        if (targetTile && c.movement_target_id !== locId && !face) {
          face = targetTile.center.clone().sub(pos).setY(0);
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
        // placement takes over unchanged (`inRoom` flips and the figure is
        // SNAPPED onto its room spot — the interior opening is a visibility
        // change, not a walk). Untouched: characters without a room,
        // always-visible rooms and travellers (they returned above).
        // THE AVATAR IS NOT AN EXCEPTION: it used to be exempt so it stayed
        // clickable (`characterAt` raycasts visible roots only, and the plaque
        // was the only way back into the mode) — which drew the player's own
        // figure standing outside the building it is in. The way back is the
        // Self panel's "Take control" now (`gameActions.takeControl`), which
        // needs no figure to click on, so the exemption is gone.
        const roomIsClosed = !inRoom && !!room && !!roomCenter;
        const hidden = wrongStorey || roomIsClosed;
        if (hidden) hiddenChars.add(c.name);
        states.push({
          char: c,
          pos,
          via,
          face,
          lean,
          hidden,
          // A visibility change places the figure, it does not walk it
          // (finding B5) — and the very first placement of a figure has
          // nowhere to walk from either.
          snap: transition === 'snap',
        });
      });
    }
    return states;
  }

  setInterval(() => {
    if (lastMap) npcs.update(computeNpcStates(lastMap));
    // Talk target (E3-T5): the same 1 Hz tick, and deliberately not a frame
    // hook — walking up to someone is a second-scale event, and
    // `shownPlacement` is only rewritten here anyway. See the section further
    // down.
    updateTalkTarget();
    updateElevator();   // standing at the lift is a second-scale event too
    updateEnterOffer(); // …and so is standing at a location entry (Etappe 3)
  }, 1000);
  npcs.update(computeNpcStates(firstMap));

  // --- Walking on foot (E3-T3; FREE on the metre plane since E4 task 5) -----
  // Two facts carry this: while the mode is on, the avatar's position is OURS
  // (npcs.setPlayerDriven — update() stops placing it), and the server is not
  // asked for permission any more but TOLD where the figure stands
  // (`POST /play/pos`). What stops the figure is geometry, not a round trip:
  // impassable terrain and foreign footprints outdoors, walls inside an open
  // interior. The maths is in game/walk.ts + game/clickmove.ts and checked
  // numerically by client3d/scripts/smoke_walk_math.mjs; nothing here recomputes it.
  const avatarName = firstMap.avatar;   // one avatar per session (as everywhere else)

  /**
   * The location whose footprint covers a world point — the client's mirror of
   * `app/core/world_geometry.location_at_point`, and the successor of the
   * cell lookup that used to answer this.
   *
   * The SMALLEST matching footprint wins: overlaps are legal (a hut on a
   * village square) and the smallest one is the most specific answer, exactly
   * as the server resolves it. `worldToTile` turns the point into the tile's
   * own frame first, so a rotated footprint is tested as the square it is.
   */
  function tileAt(x: number, z: number): Tile | null {
    let best: Tile | null = null;
    for (const tile of tiles.values()) {
      const half = tile.width / 2;
      const p = worldToTile(tile, x, z);
      if (Math.abs(p.x) > half || Math.abs(p.z) > half) continue;
      if (!best || tile.width < best.width) best = tile;
    }
    return best;
  }

  /**
   * The SMALLEST room rectangle of a tile that covers a world point, or null.
   *
   * The same "most specific wins" the footprints follow (`tileAt`): a hut
   * room drawn inside a village zone is the more precise answer. `roomRects`
   * is TILE-LOCAL, so the point is turned into that frame ONCE — the reason
   * this is not a loop over `insideRoomRect`.
   */
  function roomAt(tile: Tile, x: number, z: number): string | null {
    const p = worldToTile(tile, x, z);
    let best: string | null = null;
    let bestArea = Infinity;
    for (const [id, r] of tile.roomRects) {
      if (Math.abs(p.x - r.x) > r.w / 2 || Math.abs(p.z - r.z) > r.d / 2) continue;
      const area = r.w * r.d;
      if (area < bestArea) { best = id; bestArea = area; }
    }
    return best;
  }

  /**
   * HOW FAR THE TERRAIN RULE REACHES at a world point (§ A1.5) — the client's
   * lookup half of `game/walk.groundScope`, which is where the rule lives.
   *
   * Three sources, all of them payload: the footprint the point falls in
   * (`tileAt`), whether that place is open ground (`tile.isArea`, the twin of
   * `world_geometry.is_area_location`) and — most specific — the room
   * rectangle over the point plus its outdoor flag (`alwaysVisibleRooms`,
   * § A5). A tile whose scene is not mounted yet has no rectangles, so the
   * footprint answers alone; that is the same answer the server's router
   * gives, which never sees rooms either.
   */
  function groundScopeAt(x: number, z: number): GroundScope {
    const tile = tileAt(x, z);
    if (!tile) return groundScope(null, null);
    const room = roomAt(tile, x, z);
    return groundScope(tile.isArea,
                       room === null ? null : tile.alwaysVisibleRooms.has(room));
  }

  /**
   * Points the SERVER refused, with the time they stop counting
   * (`performance.now()`, a duration clock). The metre successor of the grid
   * world's `rejectedUntil` cell memory, and it exists for the same reason:
   * without it a player leaning into a border the client cannot predict
   * (`leave_blocked` — the entry-room rule is the server's) would walk into
   * the same refusal three times a second for as long as the key is held.
   * A refused point becomes a small blocked disc, so the figure slides along
   * that border like any other and the channel stays quiet.
   *
   * Bounded to a handful of entries: they expire, and a longer list would
   * make the walk trace a wall out of every attempt the player ever made.
   */
  const refusedPoints: { x: number; z: number; until: number }[] = [];
  /**
   * Radius of such a disc, in metres — margin around the point the server
   * would not have.
   *
   * It MUST stay below one report step, or the self-trap skip below swallows
   * every disc a walking figure could ever produce (E7 task 2 review): the
   * figure walks `WALK_SPEED` = 3.4 m/s (`scene/npcs.ts`) and reports every
   * `POS_REPORT_MS` = 330 ms, so between the refused point and where the
   * figure stands when the answer arrives lie at most
   *
   *     3.4 m/s × 0.33 s = 1.12 m
   *
   * and usually less. At the old 1.2 m every refusal was inside its own
   * skip radius and no disc was ever remembered while walking — the memory
   * was inert exactly where it is needed. 0.8 m sits below that step (and far
   * below the ~2 m of a delayed or dropped report), so discs exist again,
   * while the skip stays the belt for the cases it was built for: a report
   * gap, a standing figure, or a server correction that puts the figure right
   * onto the refused point.
   */
  const REFUSED_RADIUS_M = 0.8;
  const REFUSED_MEMORY_MS = 4000;
  const REFUSED_MAX = 8;

  /**
   * Remember a refused point — UNLESS the disc would swallow the figure.
   *
   * `home` is where the figure will stand once this refusal is settled: the
   * point the server vouched for when it sent one, else the figure's own
   * position (nothing moves it then). A disc drawn around a point that close
   * CONTAINS that position, and `blockedFor` then answers "blocked" for every
   * direction at once — the figure cannot walk anywhere for the four seconds
   * the memory lasts, in the open as much as at a border. That is the
   * total-block class E7 task 1 took out of the footprint gate, and it is the
   * same bug here.
   *
   * Derived by hand (REFUSED_RADIUS_M = 0.8, `blockedFor` blocks at a distance
   * STRICTLY below it), figure at (10, 10):
   *   refusal (10.5, 10)   → d = 0.5  ≤ 0.8  → NO disc. With one, the figure
   *                          at d = 0.5 < 0.8 would be inside it.
   *   refusal (10.8, 10)   → d = 0.8  ≤ 0.8  → no disc either. The figure
   *                          would sit exactly ON the rim, which `blockedFor`
   *                          lets pass (`<`), so this one is skipped out of
   *                          caution, not out of necessity.
   *   refusal (10.9, 10)   → d = 0.9  > 0.8  → disc. The figure is 0.1 m
   *                          outside it and keeps every direction but the one
   *                          leading in.
   *   refusal (11.12, 10)  → d = 1.12 > 0.8  → disc. THE ordinary case: one
   *                          report step at walking pace (see the radius
   *                          above), and the reason the radius is 0.8 and not
   *                          1.2 — at 1.2 this very case was skipped and the
   *                          memory never held anything.
   *   refusal (14, 14)     → d = 5.66 > 0.8  → disc, far away and harmless.
   * A refusal without any known figure position (`home` null — no avatar
   * model yet) is remembered: there is nothing it could trap.
   */
  function rememberRefused(x: number, z: number,
                           home: { x: number; z: number } | null): void {
    if (home && Math.hypot(x - home.x, z - home.z) <= REFUSED_RADIUS_M) return;
    refusedPoints.push({ x, z, until: performance.now() + REFUSED_MEMORY_MS });
    if (refusedPoints.length > REFUSED_MAX) refusedPoints.shift();
  }

  /**
   * Is that point off limits for the walking avatar (E4 task 5)?
   *
   * THREE blockers, and none of them invents a rule — each mirrors something
   * the server would refuse on the position report:
   *
   *  - IMPASSABLE TERRAIN (`terrainGround.passableAt`, the client's copy of
   *    `terrain_query.passability_at` on the same payload) — water, cliffs,
   *    whatever the world's catalog marks as such — but ONLY OUT IN THE
   *    WILDERNESS. Inside a placed footprint the FOOTPRINT WINS (server
   *    decision 2026-08-13, `POST /play/pos` derives the location first and
   *    checks the ground only for `location_id == ""`): a place is put ON the
   *    world and does not inherit the ground painted under it, so a hall on a
   *    rock plateau is a place one can stand in. Without the mirror the
   *    figure would refuse to walk where the server accepts every report —
   *    the two views disagreeing, which is the one thing this pair must not
   *    do. It costs nothing extra: `tileAt` is read anyway one line down, and
   *    the footprint rule below is untouched by it — entry stays the gate of
   *    a place, the terrain rule never was;
   *  - a FOREIGN FOOTPRINT WITH AUTHORED OPENINGS: the server lets one into
   *    such a place only within 1.5 m of one of them
   *    (`_POS_OPENING_TOLERANCE_M`), so walking into the middle of it would
   *    earn a `no_opening` refusal and a snap back on every attempt. Entering
   *    is the explicit offer at the opening (`updateEnterOffer`), and the
   *    walk-in it starts bypasses this check by owning the figure. A location
   *    that draws NO opening has a free boundary on both sides (`freeBoundary`
   *    — the server's own rule since the task-5 review) and is walked into
   *    like open ground. Since task 6 a location with no SCENE at all (404:
   *    no plan, no layout, no model) is judged by its AUTHORED openings
   *    (`map3d.boundary_openings`, which is where the server reads them too):
   *    without any it is that same open ground — a painted meadow used to be
   *    a wall to the walker — and with one it stays closed, because an author
   *    may draw a gate long before the place has a layout;
   *  - a point the server JUST refused (see above).
   *
   * `mine` is the footprint the avatar stands in, passed in because the
   * answer depends on it: the avatar's OWN location never blocks — inside it
   * the walls take over, and standing in a place must never be a state one
   * cannot walk in.
   *
   * `from` is the point the step STARTS at, and it is optional because only
   * one caller has one: the height gate (E8 task 1) judges a DIFFERENCE, so
   * without an origin there is nothing to compare. The walk loop passes the
   * figure's current point; a click target — which is metres away and not a
   * step at all — deliberately does not, or a hill between here and there
   * would refuse a goal the figure could perfectly well walk around to.
   */
  function blockedFor(mine: Tile | null, x: number, z: number,
                      from?: { x: number; z: number }): boolean {
    const at = tileAt(x, z);
    if (terrainBlocks(terrainGround.passableAt(x, z), at !== null)) return true;
    if (at && at !== mine && !freeBoundary(at)) return true;
    if (from && slopeBlockedBetween(from, x, z)) return true;
    const now = performance.now();
    for (const r of refusedPoints) {
      if (r.until > now && Math.hypot(r.x - x, r.z - z) < REFUSED_RADIUS_M) return true;
    }
    return false;
  }

  /**
   * Height of the ground at a WORLD point — the client's mirror of the
   * server's `relief.ground_lift_at`.
   *
   * TWO SOURCES, ADDED (E8 task 4, the rule itself is `game/ground.groundLift`
   * and hand-checked in `client3d/scripts/smoke_world_height.mjs`):
   *
   *  - the WORLD relief under everything — `terrainGround.fieldHeightAt`, the
   *    BILINEAR reading of the heightfield. Bilinear and not the drawn surface
   *    (`heightAt`) on purpose: this function exists to predict what the
   *    server will say, and the server reads the field, not our triangles.
   *    Until task 4 this term was missing and the mirror knew scene relief
   *    only — the rubber band on every world hill steeper than `max_slope_deg`.
   *  - the SCENE relief of the innermost enclosing tile that HAS a field
   *    (`terrainLiftAt`, the payload's own grid — never `tileGroundY`, whose
   *    model skin is client-only and would refuse steps the server accepts).
   *    A place without a field of its own does not flatten the ground it
   *    stands on (finding F3).
   */
  function reliefLiftAt(x: number, z: number): number {
    const patches: ScenePatch[] = [];
    for (const tile of tiles.values()) {
      if (!tile.terrain) continue;
      const half = tile.width / 2;
      const p = worldToTile(tile, x, z);
      if (Math.abs(p.x) > half || Math.abs(p.z) > half) continue;
      patches.push({ width: tile.width, lift: terrainLiftAt(tile, x, z) });
    }
    return groundLift(terrainGround.fieldHeightAt(x, z), patches);
  }

  /**
   * Does the HEIGHT between two points stop the figure (§ A15 Nr. 8)?
   *
   * The rule is `walk.slopeBlocks` and the limits are the world's
   * (`maxStepHeightM` / `maxSlopeDeg`, off the worldmap payload) — this only
   * looks the two heights up and applies the OPENING EXEMPTION: an authored
   * opening is where a place is entered, and a place sitting on its own
   * plateau has a step at exactly that spot. Refusing it would lock every
   * such location behind its own door, so any point within the server's
   * crossing tolerance of an opening — at either end of the step, because a
   * crossing has one foot on each side — is exempt, the same way
   * `POST /play/pos` exempts it.
   */
  const OPENING_TOLERANCE_M = 1.5;

  function slopeBlockedBetween(from: { x: number; z: number },
                               x: number, z: number): boolean {
    const dh = reliefLiftAt(x, z) - reliefLiftAt(from.x, from.z);
    if (!dh) return false;
    if (!slopeBlocks(dh, Math.hypot(x - from.x, z - from.z),
                     maxStepHeightM, maxSlopeDeg)) return false;
    const there = tileAt(x, z);
    const here = tileAt(from.x, from.z);
    for (const t of here && here !== there ? [there, here] : [there]) {
      if (!t) continue;
      for (const o of openingsOf(t)) {
        const w = tileToWorld(t, o.at.x, o.at.z);
        if (Math.hypot(w.x - x, w.z - z) <= OPENING_TOLERANCE_M
            || Math.hypot(w.x - from.x, w.z - from.z) <= OPENING_TOLERANCE_M) {
          return false;
        }
      }
    }
    return true;
  }

  /**
   * Does that location let anyone in anywhere (the server's free-boundary
   * rule)? The rule itself is `enterLocation.freeBoundaryOf`, hand-checked in
   * `client3d/scripts/smoke_enter_math.mjs`; this is the lookup of its two
   * inputs.
   *
   * The authored openings come off the TILE's own location record, not out of
   * a second dictionary: `placeableOf` merges the `/world/locations` detail
   * and the worldmap row into it, and both carry the sanitised `map3d`. It is
   * therefore the same list the server judges the crossing with, for exactly
   * the locations that have a tile — and the caller always holds one.
   */
  function freeBoundary(tile: Tile): boolean {
    const authored = tile.loc.map3d?.boundary_openings ?? [];
    return freeBoundaryOf(scenes.get(tile.loc.id), authored.length);
  }

  /**
   * The boundary openings of a location, TILE-LOCAL and with their inward
   * normal — from whichever of the client's TWO sources can answer.
   *
   * 1. THE SCENE PAYLOAD, whenever there is one: the server has already
   *    applied `tile_rotation` and anchored every opening in metres around the
   *    tile centre (`at_world`, `inward`, § B1 Nr. 13). A payload that lists
   *    none is a location with a free boundary — nothing to offer, one simply
   *    walks in.
   * 2. THE RAW `map3d.boundary_openings`, when the scene endpoint answered 404
   *    (no outline, no room layout, no building model — a painted place whose
   *    author drew a gate before there was anything to draw it into). The
   *    server reads exactly this list, so the client anchors it with the
   *    server's own formula (`enterLocation.anchorRawOpenings`, hand-checked
   *    against `boundary_entry.opening_world_points` in
   *    `client3d/scripts/smoke_enter_math.mjs`). WITHOUT `plan_width_m` there
   *    is no edge length and therefore no point — the place stays closed
   *    rather than offering a metre nobody authored.
   *
   * A payload still IN FLIGHT answers nothing at all: the conservative side,
   * the same one `freeBoundaryOf` takes.
   */
  function openingsOf(tile: Tile): (LocalOpening & { inward: { x: number; z: number } })[] {
    const scene = scenes.get(tile.loc.id);
    if (scene === undefined) return [];
    if (scene !== null) {
      return (scene.boundary_openings ?? []).map((o) => ({
        edge: o.edge,
        at: { x: o.at_world[0], z: o.at_world[1] },
        inward: { x: o.inward[0], z: o.inward[1] },
      }));
    }
    const m3 = tile.loc.map3d;
    const width = tile.loc.plan_width_m ?? m3?.plan_width_m ?? 0;
    return anchorRawOpenings(m3?.boundary_openings, width, m3?.tile_rotation ?? 0)
      .map((o) => ({ ...o, inward: inwardOf(o.edge) }));
  }

  /** `blockedFor` from where the avatar stands right now. */
  function blockedForAvatar(x: number, z: number): boolean {
    const p = npcs.positionOf(avatarName);
    return blockedFor(p ? tileAt(p.x, p.z) : null, x, z);
  }

  // --- Minimap slice (Etappe 5 task 3; metre world since E4 task 2) ----------
  //
  // The HUD draws the map, this publishes what it draws — and it publishes ONLY
  // ON A CHANGE. The signature below is the whole rule: the ground revision,
  // the known places with their POINTS (`mapLocSig`, computed when the payload
  // is taken — the count alone missed a location that MOVED, and the dot then
  // sat at the old metre until an unrelated input happened to move the
  // signature), the WINDOW ANCHOR the map is centred on and the camera yaw in
  // whole degrees. Everything smaller than that (a step of a few
  // centimetres, a fraction of a degree of orbit) would redraw a 160-pixel
  // canvas and re-render React for a picture nobody could tell apart.
  //
  // The anchor, not the raw position: since the map is a sight-radius WINDOW
  // that travels with the figure, every published metre would move the whole
  // picture — so `minimapAnchor` re-centres it in steps of
  // `MINIMAP_FOLLOW_STEP_PX` (0.6 px, i.e. 3.9 m at the full sight radius) and
  // hands the same object back in between. The avatar dot is drawn on the
  // anchor as well, so it sits in the middle of the window by construction and
  // can never disagree with the ground around it.
  //
  // Leaving the mode publishes the empty slice once: the minimap belongs to
  // the embodied view, and a map left standing with a dot from minutes ago
  // would be worse than none.
  let minimapSig = '';
  // The shaded relief, kept across publishes and rebuilt only when the ground
  // module has taken over a new field. The signature below carries the height
  // revision for exactly that reason: without it a world whose relief arrived
  // after the first publish would stay flat on the map until an unrelated
  // input moved the signature — the lesson `mapLocSig` already taught.
  let reliefRev = -1;
  let relief: MinimapRelief | null = null;
  /** Centre of the sight window, moved half a pixel at a time — see above. */
  let mapAnchor: MinimapDot | null = null;
  setInterval(() => {
    if (getGameState().mode !== 'embodied') {
      if (minimapSig === '') return;
      minimapSig = '';
      mapAnchor = null;
      setMinimap(null);
      return;
    }
    // The step follows the WINDOW, so it is derived from the same
    // `minimapRadius(worldBounds)` the drawing side frames with — a small world
    // has a narrower window and must therefore re-anchor sooner, or the picture
    // would jump by several pixels at a time.
    mapAnchor = minimapAnchor(mapAnchor, npcs.positionOf(avatarName),
      minimapFollowStepM(minimapRadius(worldBounds), MINIMAP_SIZE_PX));
    // Whole degrees: the compass needle turns in 45° steps (Q/E) plus the free
    // orbit, and a degree is finer than the needle can show anyway.
    const yawDeg = Math.round(engine.yaw * 180 / Math.PI);
    const frame = worldBounds
      ? `${worldBounds.min_x},${worldBounds.min_z},${worldBounds.max_x},${worldBounds.max_z}` : '';
    const spot = mapAnchor ? `${mapAnchor.x},${mapAnchor.z}` : '';
    const heightRev = terrainGround.heightRevision();
    const sig = `${terrainGround.revision()}|${heightRev}|${mapLocSig}`
      + `|${spot}|${yawDeg}|${frame}`;
    if (sig === minimapSig) return;
    minimapSig = sig;
    // ONE hillshade per field, never per publish: the shading walks every
    // support point of the world (up to 120 000, § A16) and this tick runs
    // four times a second. The 2D player map shades the same overview with the
    // same call and the same exaggeration — the light over a landscape is not
    // a thing two pictures of it may decide separately.
    if (reliefRev !== heightRev) {
      reliefRev = heightRev;
      const field = terrainGround.heightField();
      const image = hillshadeImage(field, { zFactor: MAP_RELIEF_Z_FACTOR });
      relief = image && field
        ? { image, origin_x: field.origin_x, origin_z: field.origin_z,
            step_m: field.step_m }
        : null;
    }
    // The colours come from the world's OWN terrain catalog, never from a
    // table in the client — a kind an admin invented this morning is on the
    // map this afternoon.
    const terrain = terrainGround.payload();
    const colors = new Map((terrain?.types ?? [])
      .map((t) => [t.kind.toLowerCase(), t.color] as const));
    const areas: MinimapArea[] = (terrain?.areas ?? []).map((a) => ({
      polygon: a.polygon,
      color: terrainColor(a.kind, colors),
    }));
    const dots: MinimapDot[] = mapLocations
      .filter((l) => l.pos_x != null && l.pos_z != null)
      .map((l) => ({ x: l.pos_x as number, z: l.pos_z as number }));
    setMinimap({
      areas,
      relief,
      locations: dots,
      avatar: mapAnchor,
      // The published yaw is the QUANTISED one, so the drawn wedge and the
      // signature can never disagree about where the avatar looks.
      yaw: yawDeg * Math.PI / 180,
      bounds: worldBounds,
    });
  }, MINIMAP_MS);

  /**
   * A place the avatar has just discovered joins the map (Etappe 5).
   *
   * The fog lifts DURING play — the server starts delivering a location the
   * moment it becomes known — so this walks a newcomer through everything the
   * boot path does for a location, in the same order and out of the same
   * functions. On the metre world that is FOUR steps and no more: the scene
   * recipe, the tile, the pickables, the veil (which now has one footprint
   * cut out of it). What went away with the grid: the surface NEIGHBOURHOOD
   * (a tile baked its coast blend from the four cells around it, so a newcomer
   * forced its neighbours to be rebuilt — footprints have no neighbours,
   * § A1.1), the pathfinding grid and the passability map (task 5: the server
   * judges the reported point, the client walks freely) and the fog's own
   * cell bookkeeping (task 6: the veil is recomputed from the footprints
   * standing, so there is nothing to keep in step).
   *
   * The rooms come from a FRESH `/world/locations`: the boot snapshot was
   * taken while this place was still fogged, and a location created after boot
   * would not be in it at all. That endpoint is unfiltered, one call covers
   * however many appeared at once, and a failed call simply leaves the work to
   * the next poll — `tiles` is what says "already built", so nothing is done
   * twice.
   *
   * ONE DIRECTION ONLY, and that is the whole of it: in play a place once
   * known stays known. The only thing that can take places away again is the
   * administrator's "show all" switch — `applyShowAll` below owns that
   * direction and calls this one for the places the other view adds.
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
    // The same guard the poll carries (`viewRev`), and for the same reason: a
    // reveal that is in flight when the administrator switches "show all" OFF
    // would mount exactly the tiles `dropVanished` has just taken away. Read
    // once at entry and checked after EVERY await — both halves of this run
    // (the locations, then their scene payloads) describe the OLD view once
    // the counter has moved, and the switch publishes its own snapshot.
    const rev = viewRev;
    let details: Map<string, WorldLocation>;
    try {
      details = new Map((await api.getLocations()).map((l) => [l.id, l]));
    } catch {
      return;   // server briefly away — the next poll tries again
    }
    if (rev !== viewRev) return;
    for (const [id, loc] of details) detailById.set(id, loc);
    const fresh = placeableOf(map, details).filter((l) => !tiles.has(l.id));
    if (!fresh.length) return;
    placeable.push(...fresh);
    // The scene recipes before the tiles, exactly as at boot: a tile built
    // without its payload would stand as the procedural shell and only swap
    // once the sweep noticed it.
    await scenes.prime(fresh.map((l) => l.id));
    if (rev !== viewRev) return;
    for (const loc of fresh) {
      addTile(loc);
      // Seeded from the SAME source the boot path seeds from, template
      // fallback included: a revealed clone has no detail entry of its own,
      // and a signature taken from the merged location would differ from the
      // first poll's and rebuild the fresh tile for nothing.
      locSig.set(loc.id, sigOf(
        details.get(loc.id) ?? details.get(loc.template_location_id || '') ?? loc));
    }
    // The geometry of the payload these tiles were just built from (B13) —
    // without it the next poll would read every fresh tile as "moved".
    noteGeometry(map.locations);
    engine.setPickables([...tiles.values()].map((t) => t.group));
    rebuildFog();
  }

  /**
   * Give a tile back. The mirror image of `addTile`, and the only place that
   * takes one down for good — a rebuild (`rebuildTile`) replaces a tile with a
   * fresh one and must NOT come through here.
   *
   * WHAT IS FREED AND WHAT IS NOT. `unmountScene` is the scene side's own
   * teardown (its group, the clip material clones, the room groups and their
   * labels); what stays behind afterwards is what `buildTile` itself made —
   * ring, ground plate, procedural shell — and those geometries and materials
   * belong to this tile alone, so they are disposed. Two things are left
   * deliberately: everything hanging off a placed server MODEL (geometries and
   * base materials belong to the loader cache, see setSceneModelTier — freeing
   * them would poison every later mount of the same URL) and every TEXTURE
   * (the surface library is shared between tiles; a material's dispose does
   * not touch its maps).
   */
  function dropTile(id: string): void {
    const tile = tiles.get(id);
    if (!tile) return;
    if (openLocationId === id) closeOpenLocation();
    if (hovered === tile) {
      // Including the cursor: `onHover` bails out early when the id it gets is
      // the one it already knows, so a pointer left on a vanished tile would
      // keep the hand shape over empty ground.
      hovered = null;
      document.body.style.cursor = 'default';
    }
    tiles.delete(id);
    dropDoorMarks(id);
    wallCache.delete(id);
    locSig.delete(id);
    buildingTierByLoc.delete(id);
    interiorTierByLoc.delete(id);
    engine.scene.remove(tile.group);
    // Captured BEFORE the unmount, which clears the ledger: these subtrees are
    // the loader cache's and are only unhooked, never disposed.
    const cached = new Set<THREE.Object3D>();
    for (const rec of tile.placedModels ?? []) if (rec.object) cached.add(rec.object);
    unmountScene(tile);
    const free = (o: THREE.Object3D) => {
      if (cached.has(o)) return;
      // CSS2D labels live in the DOM — the renderer does not take them down.
      const label = o as { isCSS2DObject?: boolean; element?: HTMLElement };
      if (label.isCSS2DObject && label.element) label.element.remove();
      const mesh = o as THREE.Mesh;
      if (mesh.isMesh) {
        mesh.geometry.dispose();
        for (const m of (Array.isArray(mesh.material) ? mesh.material : [mesh.material])) {
          m?.dispose();
        }
      }
      for (const child of [...o.children]) free(child);
    };
    free(tile.group);
  }

  /**
   * Take down every tile the given payload no longer carries, and republish
   * everything derived from the set of tiles. Returns whether anything went.
   *
   * The avatar's own location is never dropped, whatever the payload says: it
   * is where the player stands, and a cell pulled out from under the figure
   * would leave the walk machine (passability, collision, the enter offer)
   * without ground to stand on.
   */
  function dropVanished(map: WorldMap): boolean {
    const keep = new Set(placeableOf(map, detailById).map((l) => l.id));
    const here = map.characters.find((c) => c.name === map.avatar)?.location_id;
    if (here) keep.add(here);
    const gone = [...tiles.keys()].filter((id) => !keep.has(id));
    if (!gone.length) return false;
    for (const id of gone) dropTile(id);
    for (let i = placeable.length - 1; i >= 0; i -= 1) {
      if (!keep.has(placeable[i].id)) placeable.splice(i, 1);
    }
    // The panel may be showing one of the places that just went; it carries no
    // location of its own to compare, and a view switch is a fine moment to
    // close it either way.
    panel.hide();
    engine.setPickables([...tiles.values()].map((t) => t.group));
    rebuildFog();
    return true;
  }

  /**
   * The administrator's "show all locations" switch, applied LIVE (game menu).
   *
   * It changes which VIEW is fetched (`/play/worldmap?all=1`, § A12), and the
   * world is reconciled against the new payload in place: what the other view
   * adds goes through the reveal path of Etappe 5, what it takes away through
   * `dropVanished`. No reload — the switch is a view, not a new session.
   *
   * The flag moves BEFORE anything is built, and `viewRev` invalidates the
   * poll that was in flight while it moved: a stale payload of the previous
   * view would immediately reveal the tiles this switch has just removed.
   */
  let viewSwitchBusy = false;
  async function applyShowAll(on: boolean): Promise<void> {
    if (!isAdmin || on === showAll || viewSwitchBusy) return;
    viewSwitchBusy = true;
    try {
      const map = await api.getWorldMap(on);
      showAll = on;
      viewRev += 1;
      lastMap = map;
      mapStamp += 1;
      // The frame comes over with the switch: `world_bounds` is unfiltered and
      // therefore the same in both views, but this payload is what the veil
      // (and the ground, and the minimap) is rebuilt from below, and reading
      // one field from the new view and another from the old one is how two
      // pictures of the same world start to disagree. That the two views agree
      // on the frame still holds since B7 gave `world_bounds` the painted
      // areas as well (`c1447a9`) — the bounds are computed over everything
      // placed, unfiltered by what this avatar knows, and the fog does not
      // shrink a meadow.
      worldBounds = map.world_bounds;
      takeMapLocations(map.locations);
      // …and the GROUND is synced right here instead of being left to the next
      // poll: `terrain_sig` travels in this payload too, and until E5 the
      // switch published a new frame that only the base plane of the OLD sync
      // knew about — up to three seconds in which the plate and the painted
      // areas stood in the frame of the view one had just left.
      void terrainGround.sync(map.terrain_sig, worldBounds, mapLocations,
                              map.height_sig ?? '');
      takeWalkLimits(map);
      takeBackdrop(map);
      fogged = map.fogged;
      dropVanished(map);
      takeRoomsFrom(map);
      updatePins(map);
      refreshSelection(map);
      // Adds the places the other view knows and republishes what it touched;
      // a run with nothing fresh returns without doing anything.
      await revealLocations(map);
    } catch (e) {
      console.warn('[view] show-all switch failed', e);
      uiActions.toast?.('The view could not be switched.', true);
    } finally {
      viewSwitchBusy = false;
    }
  }
  gameActions.setShowAll = (on) => { void applyShowAll(on); };

  // --- Soundtrack: music by daylight, ambience by ground (E4-T5) ------------
  //
  // WHAT plays is decided in `game/soundtrack.ts` (pure, hand-checked in
  // client3d/scripts/smoke_walk_math.mjs); what is left here is the wiring — where the
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
    // Embodied the ground the avatar stands on decides, in the overview the
    // point the camera looks at; the terrain is read off the footprint
    // standing there, so a tile rebuilt with a different terrain takes effect
    // without a cache.
    const pos = mode === 'embodied' ? npcs.positionOf(avatarName) : null;
    const here = ambientTerrainFor(
      mode,
      pos ? { x: pos.x, z: pos.z } : null,
      { x: engine.target.x, z: engine.target.z },
      (at) => tileAt(at.x, at.z)?.loc.terrain ?? '',
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

  /** `tick()` only counts a figure as moving from `MOVE_EPS_M` = 0.05 m away,
   *  and at a high frame rate ONE step is shorter than that — the avatar would
   *  stand still without a walk animation. So the goal is set a short lead
   *  ahead; 0.15 m is under a twentieth of a second of walking, and three
   *  times the threshold, which is what keeps the figure moving on the
   *  slowest ground as well (the pace scales the STEP, never this — see the
   *  walking hook). */
  const MIN_LEAD = 0.15;
  /** Companion flag of the room walk (E3-T6), declared here because the two
   *  used to INTERLOCK with the cell step. The step is gone (E4 task 5), so
   *  what is left is the room walk's own guard: only ONE `/play/enter-room`
   *  may be in flight. The T6 section further down owns the writes. */
  let roomRequestInFlight = false;
  /** How long a lift ride may take before the figure is handed back even
   *  without arriving. A safety net only: the figure can be held up (a model
   *  reload throws its group away mid-ride), and a ride that never ends would
   *  leave the player unable to steer at all. */
  const ELEVATOR_RIDE_MS = 4000;
  /** Distance that counts as "arrived at the holding point" — in XZ AND in
   *  height, so the vertical part of the ride has to be over as well. */
  const ELEVATOR_ARRIVE = 0.2;
  /** The running lift ride. It INTERLOCKS with the walking hook: while it is
   *  set the hook does not steer at all — the goal belongs to the lift, and
   *  one steering frame would overwrite it, walking the figure out of the
   *  shaft while its height still blends to the other storey (through the
   *  ceiling) into a room nobody chose, which the room walk then pays for with
   *  a second `/play/enter-room`. The elevator section owns the writes. */
  let elevatorRide: { goal: THREE.Vector3; until: number } | null = null;
  /** Deadline of a walk-in (E3 acceptance, "walking on the roof"). Same
   *  safety net as the ride's, and generous for the same reason: the pace the
   *  figure keeps during it is whatever it walked in with. */
  const WALK_IN_MS = 4000;
  /** Distance that counts as "arrived" — XZ only. Unlike the lift there is no
   *  vertical ride to wait for: the goal already carries the ground height and
   *  `tick()` blends it while the figure walks. */
  const WALK_IN_ARRIVE = 0.3;
  /** The running walk-in, and it owns the figure exactly as the ride does: an
   *  accepted entry offer walks the figure THROUGH the opening it was made at,
   *  and the pos report that crosses the boundary is the one taken on the way.
   *  One steering frame would overwrite the goal — and, worse, could steer the
   *  figure into the footprint anywhere BUT the opening, which the server
   *  refuses (`no_opening`). Written below in `enterOfferedLocation`. */
  let walkIn: { goal: THREE.Vector3; until: number } | null = null;

  // --- Position reporting (E4 task 5) ---------------------------------------
  //
  // THE MOVEMENT CHANNEL, and there is only this one. The grid world asked the
  // server for permission at every cell boundary; the metre world has no
  // boundaries to ask about, so the client walks the figure and REPORTS where
  // it stands (`POST /play/pos`). The server judges the point — step
  // plausibility, terrain, and the full entry/exit gate when the point derives
  // another location — and answers with what it stored.
  //
  // Refusals are not exceptions here, they are how the player learns that a
  // place is locked: the answer carries the LAST VALID point, the figure is
  // pulled back onto it and the server's sentence goes into a toast.

  /** How often a MOVING avatar reports, in milliseconds. The server accepts
   *  about four a second and drops the rest silently, so this stays under that
   *  ceiling: three a second is roughly one report per metre walked. */
  const POS_REPORT_MS = 330;
  /** Deadline for one report. Only ONE may be in flight (a second could
   *  overtake the first and the server would judge the steps out of order), so
   *  a request that never answers would silence the channel for the rest of
   *  the session. */
  const POS_TIMEOUT_MS = 8000;
  /** How far the local figure may stand from the server's point before the
   *  correction is a snap rather than a walk (metres). Below it the figure
   *  glides there at walking pace, which hides the jitter of a poll; above it
   *  it is a teleport or a refusal, and pretending otherwise would walk the
   *  figure through walls. */
  const POS_SNAP_M = 2;
  /** How long the SAME refusal stays quiet after it was shown once. A player
   *  leaning into a locked border would otherwise collect three toasts a
   *  second saying the same thing. */
  const REFUSAL_QUIET_MS = 4000;

  let posInFlight = false;
  /** When the last report went out (`performance.now()`, a DURATION clock). */
  let lastReportAt = 0;
  /** The point the last report carried, so a standing figure reports once and
   *  then stops talking: `null` = nothing reported yet this session. */
  let reportedPos: { x: number; z: number } | null = null;
  /** True while the figure moved since the last report — the flag that turns
   *  the "one final report on stop" into a single call instead of a stream. */
  let posDirty = false;
  /** Reason of the last refusal and until when it stays quiet. */
  let quietReason = '';
  let quietUntil = 0;
  /** The location/room the SERVER last confirmed for the avatar through a
   *  report. Adopted immediately, exactly as the step answer used to be: it is
   *  the server's own word, up to three seconds before the poll repeats it,
   *  and without it the room walk would spend a whole poll judging the avatar
   *  against the place it just left. */
  function adoptReport(res: { location_id?: string; room_id?: string }): void {
    // An empty room_id is the location's GROUND, not a missing answer — it
    // must overwrite `roomOf` unconditionally, or the avatar keeps the room of
    // the location it just left.
    roomOf.set(avatarName, res.room_id ?? '');
  }

  /** How far a correction may be walked instead of jumped (metres). Beyond it
   *  the server did not correct the figure, it MOVED it — a teleport, a party
   *  pull, an admin drag — and walking there would take half a minute. */
  const CORRECT_WALK_M = 8;
  /** Safety deadline of a walking correction: at WALK_SPEED the 8 m above take
   *  2.4 s, and a figure held up by a model reload must not keep the keys. */
  const CORRECT_MS = 3000;
  /** Distance that counts as "corrected" (metres). */
  const CORRECT_ARRIVE = 0.2;
  /** The running correction. It owns the figure exactly as a walk-in does —
   *  without that the very next steering frame would overwrite the goal and
   *  the figure would never arrive at the point the server insists on. */
  let correction: { goal: THREE.Vector3; until: number } | null = null;

  /**
   * Put the figure where the server says it is.
   *
   * Near points are WALKED (at WALK_SPEED, the figure keeps its footing and
   * its facing — a refusal at a border is a metre or so, and jerking the
   * figure for that would read as a stutter); a far one is a hard put-back,
   * because it is not a correction at all but a move the player did not make.
   */
  function correctTo(point: { x: number; z: number }): void {
    const pos = npcs.positionOf(avatarName);
    if (!pos) return;
    const target = new THREE.Vector3(point.x, groundY(point.x, point.z), point.z);
    if (Math.hypot(point.x - pos.x, point.z - pos.z) > CORRECT_WALK_M) {
      npcs.snapPlayerTo(avatarName, target);
      correction = null;
    } else {
      npcs.setPlayerTarget(avatarName, target);
      correction = { goal: target.clone(), until: performance.now() + CORRECT_MS };
    }
    // Whatever the figure was walking towards was planned from a position the
    // server does not share — the plan is void. A WALK-IN too: it aimed
    // through an opening the server has just refused to let us through, and
    // leaving it running would fight the correction until its own deadline.
    cancelRoute();
    walkIn = null;
    reportedPos = { x: point.x, z: point.z };
    posDirty = false;
  }

  /** Send ONE report. Never throws: every refusal is either a correction plus
   *  a toast, or (the throttle) nothing at all. */
  async function reportPos(x: number, z: number): Promise<void> {
    posInFlight = true;
    lastReportAt = performance.now();
    const abort = new AbortController();
    const deadline = setTimeout(() => abort.abort(), POS_TIMEOUT_MS);
    try {
      const res = await api.postPos(x, z, abort.signal);
      // Throttled: the server took none of it and said so. Not an error, not
      // a correction — but the point IS still unreported, so the dirty flag
      // has to go back up. `tickPosReport` cleared it when it sent this call,
      // and a figure that stops right afterwards would never move again — no
      // further `markMoved`, no further report, and the server would keep a
      // stale stop point that only the poll's echo check papers over.
      if (!res.ok) { posDirty = true; return; }
      reportedPos = { x, z };
      adoptReport(res);
    } catch (e) {
      // AN EXPIRED SESSION IS NOT A WALKING PROBLEM. `json()` fires
      // `auth:required` before it throws, so the relogin flow is already
      // running and the login form is on its way up; logging it here would
      // print one line per report — several a second while the figure walks —
      // for a state the player is being asked about anyway. The point stays
      // UNREPORTED (`posDirty`), so the first report after the relogin carries
      // it, exactly like the network hiccup below.
      if (api.isAuthError(e)) { posDirty = true; return; }
      const err = e instanceof api.ApiError ? e : null;
      if (!err) {
        // A dropped request is a network hiccup, not a verdict: the figure
        // stays where it is and the next report tries again — which it can
        // only do while the point counts as unreported, so the flag goes back
        // up here too (same swallowed-stop-report trap as the throttle above).
        if (!abort.signal.aborted) console.warn('[walk] position report failed', e);
        posDirty = true;
        return;
      }
      // The server refused the point. Its answer carries the last one it
      // vouched for, and that is where the figure belongs — and the refused
      // point itself becomes a blocked disc, so the next frames slide along
      // that border instead of running into the same refusal. The slide is
      // unaffected by the disc's SIZE: a frame step is 3.4 m/s × ~16 ms ≈
      // 0.06 m, so even the 0.8 m disc is a dozen steps wide and nothing
      // tunnels through it — `slideBlocked` keeps the component along the
      // border exactly as it does for a building.
      // Where the figure ENDS UP decides whether the disc may be drawn at
      // all: the server's own point when it sent one (`correctTo` puts the
      // figure there), otherwise the place the figure is standing.
      rememberRefused(x, z, err.pos ?? npcs.positionOf(avatarName) ?? null);
      if (err.pos) correctTo(err.pos);
      const now = performance.now();
      if (err.message && (err.reason !== quietReason || now > quietUntil)) {
        quietReason = err.reason;
        quietUntil = now + REFUSAL_QUIET_MS;
        uiActions.toast?.(err.message);
      }
    } finally {
      clearTimeout(deadline);
      posInFlight = false;
    }
  }

  /**
   * The reporting tick, called from the walking hook every frame.
   *
   * Two rules, and between them they cover both halves of the contract
   * ("~3/s while moving plus one final on stop"):
   *  - while the figure MOVES, a report every `POS_REPORT_MS`;
   *  - when it stops, ONE more report with the point it stopped at — that is
   *    what `posDirty` is for: it is set by the movement and cleared by the
   *    report, so a standing figure sends nothing at all.
   */
  function tickPosReport(pos: { x: number; z: number }): void {
    if (posInFlight) return;
    if (!posDirty) return;
    if (performance.now() - lastReportAt < POS_REPORT_MS) return;
    void reportPos(Math.round(pos.x * 100) / 100, Math.round(pos.z * 100) / 100);
    posDirty = false;
  }

  /** The figure moved: remember it for the next report. Called with the point
   *  the frame ended at, so a stopped figure's LAST position is reported too. */
  function markMoved(pos: { x: number; z: number }): void {
    if (reportedPos
      && Math.abs(reportedPos.x - pos.x) < 0.01
      && Math.abs(reportedPos.z - pos.z) < 0.01) return;
    posDirty = true;
  }

  // --- Click to walk (E3-T4; free metres since E4 task 5) -------------------
  // A ground click plans ONE thing: the point to walk at (game/clickmove.ts).
  // Walking it is the same frame hook with the same collision as WASD — the
  // goal only replaces the direction the keys would give. NO CLIENT A* in E4
  // (plan task 5): the figure takes the straight line and slides along what it
  // meets; a goal behind a building is not reached and the walk gives up
  // (`STALL_FRAMES`), which is honest about what a route planner would be.
  /** The point the click order steers at, or null when none is running. */
  let route: { x: number; z: number } | null = null;
  /** Frames in a row in which the walk got nowhere — see `walkStalled`. */
  let routeStalled = 0;

  function cancelRoute() {
    if (!route) return;
    route = null;
    routeStalled = 0;
    npcs.setWalkTarget(null);
  }

  /**
   * Ground height at a world point — THE height every consumer here asks for.
   *
   * Two sources, in this order: inside a footprint the location's own model
   * answers (`tileGroundY` rays it, so a raised shore or a bridge is honoured),
   * and outside every footprint the WORLD RELIEF does (§ A16, the sampled
   * heightfield). Until E8 the second half was the flat `GROUND_Y`, and that
   * one constant is what kept markers, walk goals, the camera and the
   * corrections on the y = 0 plane; with the fallback moved, all seven callers
   * of this function stand on the terrain without a line of their own.
   *
   * The two are no longer two RULES, only two lookups (finding 4, 2026-08-13):
   * `tileGroundY` itself answers the higher of the tile and the world under it,
   * so the height does not change its mind at a footprint border. Since then
   * this is also the sampler the NPC manager walks its travellers on
   * (`setGroundHeight` above), which is what closed the jump.
   */
  const groundProbe = new THREE.Vector3();
  function groundY(x: number, z: number): number {
    const tile = tileAt(x, z);
    if (!tile) return terrainGround.heightAt(x, z);
    groundProbe.set(x, 0, z);
    return tileGroundY(tile, groundProbe);
  }

  engine.onGroundClick = (x, y) => {
    const state = getGameState();
    // Overview mode is untouched: there a click stays a tile pick. A running
    // lift ride or walk-in owns the figure, so no new order is planned during
    // those either — a goal planned from the old position would walk the
    // figure back out of the opening it just came through.
    if (state.mode !== 'embodied' || state.movementLocked
      || elevatorRide || walkIn) return false;
    const pos = npcs.positionOf(avatarName);
    if (!pos) return false;
    // OUT IN THE OPEN the click is read against the DRAPED GROUND itself
    // (E8 task 3): a horizontal plane through the figure's feet meets a slope
    // metres away from the pointer — at 40° and a flat camera angle 7-14 m,
    // which is a walk order to somewhere the player did not click.
    //
    // INSIDE A FOOTPRINT the plane stays (parked review finding, E3): on an
    // upper storey or a raised floor the world's ground is the wrong surface
    // entirely — the ray would run past the floor down to the map. Same split
    // as `groundY()`, and for the same reason.
    const standingOn = tileAt(pos.x, pos.z);
    const hit = (standingOn ? null : terrainGround.groundPointAt(engine.raycasterAt(x, y)))
      ?? engine.groundPointAt(x, y, pos.y);
    if (!hit) return false;
    const goal = planClickWalk({ x: pos.x, z: pos.z }, { x: hit.x, z: hit.z },
      (bx, bz) => blockedForAvatar(bx, bz));
    // Nothing walkable under the pointer (a building, water, the point one
    // already stands on): let the click fall through to the tile's info panel.
    if (!goal) return false;
    route = goal;
    routeStalled = 0;
    // Marker height from the same source the walking uses: the room floor
    // where the avatar's room reaches, the ground skin everywhere else.
    npcs.setWalkTarget(new THREE.Vector3(goal.x,
      roomFloorY(tileAt(goal.x, goal.z)) ?? groundY(goal.x, goal.z), goal.z));
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

  // --- The view corridor camera -> avatar (`scene/occlusion.ts`) ------------
  //
  // ONE evaluation per frame, ONE write of the shared uniforms — the pattern of
  // the surface clock (`updateSurfaceMaterials` in `scene/engine.ts`): however
  // many materials carry the patch, they all read these four objects, so a wood
  // costs the same as a single bush. Both ends are known here and nowhere else:
  // the camera is the engine's, the avatar's chest is the figure's position
  // plus the constant in the module.
  //
  // Not embodied (or no figure on the map yet) means strength 0, and the
  // shader's own guard then discards nothing at all — an overview client draws
  // exactly the picture it drew before this existed.
  engine.addFrameHook(() => {
    const embodied = getGameState().mode === 'embodied';
    updateOcclusion(engine.camera.position,
                    embodied ? npcs.positionOf(avatarName) : null, embodied);
  });

  const walkGoal = new THREE.Vector3();
  engine.addFrameHook((dt) => {
    const state = getGameState();
    if (state.mode !== 'embodied') {
      cancelRoute();                      // leaving the mode drops the route
      elevatorRide = null;   // ditto for a ride nobody is in any more
      walkIn = null;         // …and for a walk-in nobody is walking
      correction = null;     // …and for a correction of a figure nobody steers
      return;
    }
    // Party follower: the leader carries the avatar along; the server refuses
    // every report anyway (403 `party_follower`), so the keys stay dead
    // instead of collecting toasts.
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
    // A walk-in owns the figure the same way: the offer was accepted and the
    // figure walks THROUGH the boundary opening, which is what makes the next
    // position report a legal crossing. Steering during it could put the
    // figure into the footprint anywhere but at the opening — the very point
    // the server refuses. XZ only, the height is the ground and `tick()`
    // blends it on the way. The reports keep running during it: the crossing
    // IS one of them.
    if (walkIn) {
      const arrived = Math.hypot(walkIn.goal.x - pos.x, walkIn.goal.z - pos.z)
        < WALK_IN_ARRIVE;
      markMoved({ x: pos.x, z: pos.z });
      tickPosReport({ x: pos.x, z: pos.z });
      if (!arrived && performance.now() <= walkIn.until) return;
      walkIn = null;
    }
    // A correction owns the figure the same way, and for the same reason: the
    // server insists on a point, and one steering frame would pull the figure
    // off it again. Nothing is REPORTED while it runs — the point is the
    // server's own word, and telling it back would be an echo.
    if (correction) {
      const arrived = Math.hypot(correction.goal.x - pos.x, correction.goal.z - pos.z)
        < CORRECT_ARRIVE;
      if (!arrived && performance.now() <= correction.until) return;
      correction = null;
    }
    // ONE pace (E4): `WALK_SPEED` is 3.4 metres a second and a metre is a
    // metre, indoors and out. The interior factor that used to sit here (and
    // in `tick()`'s catch-up) existed only because a room drew its figures
    // small — with k = 1 there is nothing left to compensate.
    const keyDir = walkDir(engine.keysDown(), engine.yaw);
    // The keys always win: touching WASD is the player taking over from the
    // click order, not fighting it.
    if (keyDir) cancelRoute();
    let dir = keyDir;
    // How far the goal may be pushed ahead this frame. Unlimited for the keys
    // (the direction just carries on), capped at the remaining distance while
    // a click order runs, so the figure stops ON the goal instead of past it.
    let reach = Infinity;
    if (!dir && route) {
      if (reachedGoal({ x: pos.x, z: pos.z }, route)) {
        cancelRoute();
      } else {
        const to = goalDir({ x: pos.x, z: pos.z }, route);
        if (!to) cancelRoute();
        else { dir = { x: to.x, z: to.z }; reach = to.dist; }
      }
    }
    if (!dir) {
      // Standing still is when the FINAL report of a walk goes out — the
      // server's last word about where the avatar is must be where it really
      // stopped, not where it happened to be a third of a second earlier.
      tickPosReport({ x: pos.x, z: pos.z });
      return;
    }
    const from = { x: pos.x, z: pos.z };
    // The footprint the figure stands in — looked up ONCE per frame and handed
    // to both the blocker and the wall/floor lookups below.
    const here = tileAt(pos.x, pos.z);
    // THE GROUND SETS THE PACE (finding 3 of the E8 acceptance): the factor of
    // the terrain the figure stands on RIGHT NOW, as far as that rule reaches
    // here (`groundScopeAt` — a village on a lake is waded through, the hall
    // beside it is not).
    //
    // IT SCALES THE STEP, NOT THE LEAD (round 2, 2026-08-13). The goal is set
    // a lead ahead of the CURRENT position every frame, and `npcs.tick` walks
    // the figure toward it at `WALK_SPEED * dt * pace`; the lead only has to
    // clear `MOVE_EPS_M`, below which the manager calls the figure standing.
    // Multiplying the LEAD by the pace put it at 0.0375 m on a 0.25 ground —
    // under that threshold, so the figure froze in an idle clip instead of
    // swimming slowly. The clamp against the goal distance comes last, so the
    // figure still stops ON its click target instead of overshooting it.
    const pace = terrainPace(terrainGround.typeAt(pos.x, pos.z).speed_factor,
                             groundScopeAt(pos.x, pos.z));
    const lead = Math.min(Math.max(WALK_SPEED * dt, MIN_LEAD), reach);
    let { x, z } = { x: pos.x + dir.x * lead, z: pos.z + dir.z * lead };
    // OUTDOORS the world itself stops the figure: impassable terrain — out in
    // the WILDERNESS only, a footprint replaces the ground under it
    // (`terrainBlocks`, decision 2026-08-13) — and the footprints of locations
    // the avatar is not in. Both slide (the movement keeps the component that
    // runs ALONG the boundary), so walking into a wall of water follows the
    // shore instead of nailing the figure to it.
    // This is what the cell clamps used to be — and unlike them it is not a
    // permission but geometry, which is why it needs no server round trip.
    ({ x, z } = slideBlocked(from, { x, z },
                            (bx, bz) => blockedFor(here, bx, bz, from)));
    // Walls have the LAST word (E3 acceptance: "the avatar walks through
    // walls"), and they apply INSIDE an open interior, where the outdoor
    // blockers say nothing: a room is inside the avatar's own footprint.
    const walls = avatarWalls(here);
    if (walls) ({ x, z } = clampAgainstWalls(pos, { x, z }, walls.segments, walls.radius));
    // A click order that gets nowhere for a while has run into something the
    // straight line cannot get round — drop it instead of pressing the figure
    // against the obstacle for good.
    if (route) {
      routeStalled = walkStalled(from, { x, z }) ? routeStalled + 1 : 0;
      if (routeStalled >= STALL_FRAMES) cancelRoute();
    }
    walkGoal.set(x, roomFloorY(here) ?? groundY(x, z), z);
    npcs.setPlayerTarget(avatarName, walkGoal, pace);
    // The report is about where the figure IS, not where it is being sent:
    // `setPlayerTarget` only moves the goal, `tick()` walks the figure there.
    // Reporting the goal would put the server up to one lead ahead of the
    // picture — and at a boundary that is the difference between a legal
    // point and a refused one.
    markMoved({ x: pos.x, z: pos.z });
    tickPosReport({ x: pos.x, z: pos.z });
  });

  /** Findings the SERVER made about a location (plan-betreten-und-tueren.md
   *  § 4.3, today: a building whose hull has no door leading outside — the
   *  automatic door in the south wall is gone, so a sealed building says so
   *  instead of quietly getting one). Display only: the message is the
   *  server's, nothing here re-derives the rule or repairs anything.
   *
   *  Every VISIBLE location ships its own findings, so only the one the avatar
   *  stands in is worth the player's attention; each is shown once. */
  const announcedProblems = new Set<string>();
  function announceSceneProblems(map: WorldMap) {
    const locId = map.characters.find((c) => c.name === avatarName)?.location_id;
    if (!locId) return;
    for (const problem of scenes.get(locId)?.problems ?? []) {
      const key = `${locId}|${problem.kind}|${problem.room_id ?? ''}`;
      if (announcedProblems.has(key)) continue;
      announcedProblems.add(key);
      console.warn(`[scene] ${locId}: ${problem.kind} — ${problem.message}`);
      uiActions.toast?.(problem.message, true);
    }
  }

  /**
   * Authority check: while the player steers, the SERVER can still move the
   * avatar (teleport, party pull, admin, a travel arrival). Since E4 task 5
   * that is a comparison of POINTS, not of cells — the payload carries the
   * avatar's metre position (§ A12) and so does the local figure.
   *
   * It must not fight our own reports, and it cannot: an accepted report IS
   * the server's position, so the two agree by construction, and a REFUSED one
   * has already put the figure back on the point this check would compare it
   * with. What is left is genuine foreign movement — and the poll's word about
   * it is up to three seconds old, which is why the threshold is metres and
   * not centimetres.
   *
   * Under `POS_SNAP_M` the difference is the ordinary lag between a walking
   * figure and the last report, and correcting it would tug the figure
   * backwards every poll. Above it the figure GLIDES to the server's point
   * when the distance is still walkable and is put back hard when it is not
   * (`correctTo`) — a teleport is a jump, not a sprint across the map.
   */
  function reconcileAvatarPos(map: WorldMap) {
    if (getGameState().mode !== 'embodied') return;
    // A report in flight would be compared against a payload that predates it.
    if (posInFlight || walkIn || elevatorRide || correction) return;
    const pos = npcs.positionOf(avatarName);
    if (!pos) return;
    const me = map.characters.find((c) => c.name === avatarName);
    // No point in the payload = the server has no position for the avatar at
    // all (an unplaced location). Nothing to reconcile against.
    if (!me?.pos) return;
    // OUR OWN last report is not foreign movement. The payload is up to a
    // poll old and the report before it took a round trip, so on a remote
    // client (a documented deployment: `ANIMA_API=http://<host>:8000`) the
    // figure has walked on by report-lag + poll-lag by the time this sees it
    // — from ~260 ms of latency that alone exceeds POS_SNAP_M and the figure
    // would be tugged backwards on every single poll. So the comparison is
    // against what WE last told the server: if the payload says that point,
    // it is our own echo and there is nothing to reconcile. This is the
    // metric successor of the grid world's `expectedCell` grace.
    if (reportedPos
      && Math.hypot(me.pos.x - reportedPos.x, me.pos.z - reportedPos.z) < 0.05) {
      return;
    }
    const d = Math.hypot(me.pos.x - pos.x, me.pos.z - pos.z);
    if (d <= POS_SNAP_M) return;
    // `correctTo` moves the figure — walking the last few metres, jumping a
    // real teleport. The camera follows only in the second case: a jump across
    // the map must not leave the view behind, while a two-metre correction
    // would fly the camera for nothing.
    correctTo(me.pos);
    if (d > CORRECT_WALK_M) {
      const p = new THREE.Vector3(me.pos.x, groundY(me.pos.x, me.pos.z), me.pos.z);
      engine.flyTo(p, engine.targetDist);
    }
  }

  // --- Changing rooms on foot (E3-T6) ---------------------------------------
  // Inside an open interior the avatar's room is no longer a click on a room
  // chip — walking into a room moves it, and the chat context follows. The
  // rule itself is pure (`game/roomwalk.ts`, numbers in
  // client3d/scripts/smoke_walk_math.mjs); everything here looks up its arguments and
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
  /** Deadline for one room request. Only ONE may be in flight, so a request
   *  that never answers (proxy hiccup, server restart) would bar every room
   *  change for the rest of the session. */
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

  /** A room reference from `roomOf` as a room ID: it carries the worldmap's
   *  `room_id`, but the pre-AV3D-8 fallback poll writes a room NAME into the
   *  same map — and ids are what `/play/enter-room` takes and what every
   *  payload block (`doorways[].rooms`) speaks in. */
  function roomIdOf(tile: Tile, raw: string | null | undefined): string | null {
    if (!raw) return null;
    return tile.loc.rooms.find((r) => r.id === raw || r.name === raw)?.id ?? null;
  }

  /** The avatar's room as the SERVER sees it, resolved to a room ID. */
  function avatarRoomId(tile: Tile): string | null {
    return roomIdOf(tile, roomOf.get(avatarName));
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

  /** Whether a point lies inside a room's floor rectangle — the same
   *  rectangles the labels use, taken from the mounted scene. A room the tile
   *  has no rectangle for (no plate, no overlay) contains nothing.
   *
   *  `roomRects` is TILE-LOCAL (an axis-aligned rectangle only means anything
   *  in the frame it was measured in), so the WORLD point is turned into that
   *  frame instead of the rectangle being turned into the world — a turned
   *  rectangle is not a rectangle. */
  function insideRoomRect(tile: Tile, roomId: string,
                          pos: { x: number; z: number }): boolean {
    const r = tile.roomRects.get(roomId);
    if (!r) return false;
    const p = worldToTile(tile, pos.x, pos.z);
    return Math.abs(p.x - r.x) <= r.w / 2 && Math.abs(p.z - r.z) <= r.d / 2;
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
   * figure downhill and sink it uphill.
   *
   * The ground skin (`tileGroundY`) is NOT an alternative inside a room, and
   * the "Zur Rosinante" finding of the acceptance round is why: it raycasts
   * the building/area MESH from above and takes the first hit below 1.2 m,
   * which is a world metre and therefore an assumption about scale. In the
   * SHRUNK-SCENE ERA (before E4; k = 1 since, § A1.8) Willowbrook ran at
   * k = 0.21 — extent_m 10.5 over a 50 m plan — so a whole storey WAS 0.63 m
   * and every ROOF of the village fitted inside that 1.2 m window: the ray hit
   * the tavern's roof at ~0.6..0.9 instead of its floor plate at 0.037 and the
   * avatar walked over the houses. The metre world has taken that particular
   * trap away, but not the guess itself — reading the floor off the room
   * removes it entirely, the number comes from the payload the room is built
   * from.
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
      // The payload is TILE-LOCAL, the figure position is absolute — so the
      // footprint transform is applied here, exactly as `mountScene` applies
      // it to room centres, doorways, markers and the wall mids of the
      // culling. Without it the segments of a building 45 m away sit 45 m from
      // the figure and nothing ever blocks.
      //
      // `wallSegments` is asked in the TILE frame (no origin) and its ends are
      // turned afterwards: since E4 the footprint may stand rotated, and a
      // segment is a line, so both ends have to go through the same turn — an
      // origin baked in before it would place the walls of a turned location
      // in the wrong direction.
      segments = wallSegments(scene, level).map((sg) => {
        const a = tileToWorld(tile, sg.ax, sg.az);
        const b = tileToWorld(tile, sg.bx, sg.bz);
        return { ax: a.x, az: a.z, bx: b.x, bz: b.z };
      });
      byLevel.set(level, segments);
    }
    // The radius comes from the SCENE's `k` — which is the constant 1 since E4
    // (`assertUnitScale` says so out loud if it ever is not), so this is the
    // plain 0.25 m body half-width in world metres. The factor stays until the
    // walk rewrite of task 5 takes `bodyRadius` apart with its smoke.
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

  // `entryRoomToEnter` + `enterEntryRoom` lived here: the client walked the
  // avatar into the location's ENTRY ROOM before it took the step out, because
  // the grid step refused any other room with a 403 `not_at_entry_room`. Both
  // are GONE with the step (E4 task 5). Leaving is judged by the server on the
  // position report now (`boundary_entry.may_leave` with the room the avatar
  // stands in) and refused with `leave_blocked` — the figure is put back on
  // the last valid point and the server's sentence goes into a toast. Walking
  // to the entry room is the player's move again, which is what it is in the
  // 2D UI as well; anticipating it would mean a second gate beside the one
  // that decides.

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
    const tile = tileAt(pos.x, pos.z);
    const current = tile ? avatarRoomId(tile) : null;
    if (requestedRoom
      && (current === requestedRoom
        || performance.now() - requestedAt > ROOM_CONFIRM_MS)) {
      requestedRoom = null;
    }
    followAvatarStorey(tile, current);
    // The player-driven figure's SCALE used to be pulled to the room scale
    // here (and back out again on leaving), because a world metre inside a
    // room was a fraction of a human metre. Gone with k = 1 (E4): the figure
    // stands at scale 1 wherever it is, so there is nothing to follow.

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
    // A room the server refuses this avatar is no candidate at all (task C2):
    // walking across its threshold must not post the avatar into a room
    // `/play/enter-room` would turn away — the figure would be asked to move
    // and bounce back on the next poll. The room the avatar is ALREADY in
    // survives the filter (`unlockedRooms`), or standing still inside it would
    // make the nearest other room the best candidate.
    const rooms = unlockedRooms(interiorRooms(tile).filter(
      (r) => interiorUp || tile.alwaysVisibleRooms.has(r.id)),
    state.lockedRooms, current ?? '');
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
    // …and a LOCKED ground is no fallback either: it is a room like every
    // other one, so a rule on it bars the step out onto it just the same.
    const groundId = getGameState().groundRoomId;
    const ground = (groundId === current || !isLocked(state.lockedRooms, groundId))
      ? groundId : '';
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
    // cost a second full hold. The cell step it also used to wait for is gone
    // (E4 task 5): a position report changes no room, so the two cannot race.
    const gated = roomRequestInFlight || next === requestedRoom
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
  // (`game/elevator.ts`, numbers in client3d/scripts/smoke_walk_math.mjs); everything
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
    const tile = tileAt(pos.x, pos.z);
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
    const tile = tileAt(pos.x, pos.z);
    const stop = tile?.elevatorStops?.get(level);
    if (!tile || !stop) return;
    const target = elevatorTargetRoom(level, elevatorStopsOf(tile), interiorRooms(tile));
    if (!target) return;
    // The ONE room-request machine of the room walk — a ride while another
    // room change is in flight would let the network order decide which room
    // the avatar ends up in. No second enter-room path, and the SAME cooldown:
    // a room the server just refused stays refused for the ride as well, or
    // every press would run into the same 403.
    if (roomRequestInFlight
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

  // --- Entering a location (Etappe 3, "Betreten"; metres since E4 task 5) ---
  // The offer is view logic, the ENTRY is the server's — and since free
  // walking it is not a step but the next POSITION REPORT: pressing F walks
  // the figure THROUGH the authored opening, and the report taken on the way
  // in is what the server judges (opening tolerance, `accessible_when`,
  // access rules). No silent auto-entry: the explicit offer stays, exactly as
  // the old UX had it, because entering a place is a decision.
  //
  // The rule of WHEN the offer stands is pure (`game/enterLocation.ts`,
  // numbers in client3d/scripts/smoke_enter_math.mjs): within ENTER_RADIUS of
  // an authored boundary opening (§ B1 Nr. 13) of a location one is not in —
  // a location without such an opening offers no entry (2026-08-04), exactly
  // as the server refuses the crossing. The 4-adjacency and the edge filter
  // are GONE with the cells: on a free plane there is no crossed edge, only
  // the distance to the opening, which is what the server measures too.
  //
  // A LOCKED location makes no offer (task C2, § 3 decision 2: the hint does
  // not appear in the first place), but it is not forgotten either: the offer
  // is kept with the server's reason, so pressing F says why instead of doing
  // nothing at all. An open neighbour always wins over a locked one.
  /** the standing offer, with the opening WORLD POINT the figure is walked to
   *  when it is accepted. `locked` = the server's own refusal sentence, empty
   *  for a real offer. */
  let enterOffer: {
    locId: string; point: { x: number; z: number }; locked: string;
  } | null = null;

  function updateEnterOffer() {
    const state = getGameState();
    const clear = () => {
      enterOffer = null;
      if (state.enterOffer) setGameState({ enterOffer: null });
    };
    if (state.mode !== 'embodied' || state.movementLocked) return clear();
    const pos = npcs.positionOf(avatarName);
    if (!pos) return clear();
    const myLoc = tileAt(pos.x, pos.z)?.loc.id ?? '';
    const candidates: EntryTile[] = [];
    for (const t of tiles.values()) {
      // WHO IS WORTH AN OFFER. A location with a detail view to enter always
      // is — and since E5 so is one the walker CANNOT get into by walking:
      // a place with authored openings is not a free boundary, so its
      // footprint is a wall everywhere but at its gates, and without an offer
      // there is no way in at all. That is the whole 404 case (`openingsOf`
      // Nr. 2): no scene means no interior, so `openable` was false and the
      // painted place with a gate on it could be neither opened nor entered.
      // Skipped is only what is BOTH: nothing to open and free to walk into —
      // there the offer would just duplicate ordinary walking.
      if (!openable(t) && freeBoundary(t)) continue;
      candidates.push({
        locId: t.loc.id,
        footprint: { x: t.center.x, z: t.center.z, yaw: t.yaw },
        // Openings come TILE-LOCAL (metres around the tile centre, § B1
        // Nr. 13, `tile_rotation` already applied); `openingWorldPoints`
        // turns them with the tile's own yaw, the § A1.1 mapping `tileToWorld`
        // uses for every other payload point.
        openings: openingsOf(t),
        // The verdict of the neighbour poll, bound by ID at this moment — it
        // is per avatar and never travels in the cached payload above.
        locked: isLocked(state.lockedLocations, t.loc.id),
      });
    }
    const offer = entryOfferNear({ x: pos.x, z: pos.z }, myLoc, candidates);
    if (!offer) return clear();
    const locked = lockReason(state.lockedLocations, offer.locId);
    enterOffer = { locId: offer.locId, point: offer.point, locked };
    // Locked: no "Press F to enter" at all — the barred threshold is what the
    // player sees, and the key answers with the server's sentence.
    if (locked) {
      if (state.enterOffer) setGameState({ enterOffer: null });
      return;
    }
    const name = tiles.get(offer.locId)?.loc.name ?? '';
    if (state.enterOffer?.name !== name) setGameState({ enterOffer: { name } });
  }
  // Leaving the mode drops the offer in the same tick, like talk and lift.
  subscribeGameState(() => {
    if (getGameState().mode !== 'embodied') updateEnterOffer();
  });

  gameActions.enterLocation = () => { void enterOfferedLocation(); };

  /** Perform the offered entry: walk the figure THROUGH the opening the offer
   *  was made at. There is nothing to ask for — the crossing happens when the
   *  position report taken on the way in derives the new location, and the
   *  server's gate decides then (a refusal snaps the figure back and says
   *  why, like any other refused report).
   *
   *  The goal is the opening's world point plus one step INWARD (`inward` is
   *  the payload's unit normal): far enough inside the footprint to be a real
   *  entry, close enough to the opening to stay well within the server's
   *  crossing tolerance of 1.5 m.
   *
   *  A locked place is answered instead of entered: the server's own sentence,
   *  passed through untranslated (it is localized already), so the key is never
   *  silent at a barred gate. */
  async function enterOfferedLocation() {
    const offer = enterOffer;
    const state = getGameState();
    if (!offer || state.mode !== 'embodied' || state.movementLocked) return;
    if (offer.locked) {
      uiActions.toast?.(offer.locked);
      return;
    }
    // Nothing may overlap a guided movement or a room request — the same
    // interlocks the walking hook honours.
    if (roomRequestInFlight || elevatorRide || walkIn) return;
    const pos = npcs.positionOf(avatarName);
    if (!pos) return;
    const target = tiles.get(offer.locId);
    if (!target) return;
    cancelRoute();
    // The inward normal of the opening the OFFER names — the nearest one is
    // what `entryOfferNear` already picked, so this looks up its normal
    // instead of choosing a second time.
    let goal = { x: offer.point.x, z: offer.point.z };
    let best = Infinity;
    // The SAME list the offer was made from (`openingsOf`) — the raw-anchored
    // one included, or a 404 place would be offered and then walked to its own
    // opening point without the step inward that makes the crossing.
    for (const o of openingsOf(target)) {
      const at = tileToWorld(target, o.at.x, o.at.z);
      const d = Math.hypot(at.x - offer.point.x, at.z - offer.point.z);
      if (d >= best) continue;
      best = d;
      const inward = tileDirToWorld(target, o.inward.x, o.inward.z);
      goal = { x: at.x + inward.x * OPENING_WALK_IN_M,
               z: at.z + inward.z * OPENING_WALK_IN_M };
    }
    const g = new THREE.Vector3(goal.x, groundY(goal.x, goal.z), goal.z);
    npcs.setPlayerTarget(avatarName, g);
    // From here the walk-in owns the figure: no steering, and the reports
    // keep running — one of them IS the crossing.
    walkIn = { goal: g.clone(), until: performance.now() + WALK_IN_MS };
  }

  // --- Talking by proximity (E3-T5) -----------------------------------------
  // Walking up to someone is the whole interaction: the bus carries the name,
  // the HUD shows the prompt and F opens the chat. The rule itself is pure
  // (`game/proximity.ts`, checked in client3d/scripts/smoke_walk_math.mjs); everything
  // here is the lookup of its arguments.
  //
  // Rooms come from `shownPlacement`, NOT from `roomOf` — but only for the
  // NPCs is that "the room the view DRAWS". For them the two genuinely differ:
  // a room resolves only above the fade threshold, so the drawn room is null
  // while the interior is closed, and the prompt cannot fire through a wall one
  // is looking at.
  //
  // For the AVATAR it is still the server's view: its figure is player-driven,
  // so `npcs.update` ignores every placement field for it, yet its placement
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
    // The avatar's POINT is LIVE (the player drives it), while its
    // `location_id` on the worldmap is up to one poll behind — reading the
    // location off the position means the prompt appears when the player has
    // arrived, not three seconds later. Only if no footprint covers that
    // point does the map's answer stand in.
    const myLoc = tileAt(me.x, me.z)?.loc.id
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
        room: shownRoomOf(c.name),
        scale,
      });
    }
    const target = talkTargetNear(
      { name: avatarName, pos: { x: me.x, z: me.z }, locId: myLoc,
        room: shownRoomOf(avatarName) },
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
    // exactly the order the HUD shows the offers in. A LOCKED neighbour shows
    // no prompt (task C2) and is still answered here: the key explains itself
    // with the server's refusal rather than staying silent.
    if (state.enterOffer || enterOffer) {
      gameActions.enterLocation?.();
      return;
    }
    if (state.mode === 'overview' && state.selected?.isAvatar) gameActions.enterEmbodied?.();
  });

  /**
   * Put every tile back on its plateau after the relief changed (E8 task 4).
   *
   * `footprintCentre` reads the world ground at the location's centre, so the
   * height a tile stands on is decided when the tile is BUILT — and the field
   * arrives asynchronously and changes again whenever somebody paints a hill
   * or moves a place. A tile built before its ground was known would stand on
   * the flat world for good.
   *
   * A full rebuild rather than moving the group: the scene mount anchors room
   * centres and marker heights as WORLD points via `tileToWorld`, so a group
   * that quietly slid up would leave them behind at the old height. (The
   * doorway thresholds ride IN the group since the floating-threshold finding
   * and would follow on their own — the sampled room floors do not.)
   * Rebuilding is the path a MOVED location already takes
   * (`rebuildMovedTiles`) and costs the same; it happens on an authoring edit,
   * never per frame — the revision counter is compared, not the field.
   */
  let builtHeightRev = -1;
  function relevelTiles(): void {
    const rev = terrainGround.heightRevision();
    if (rev === builtHeightRev) return;
    builtHeightRev = rev;
    for (const tile of [...tiles.values()]) {
      const centre = footprintCentre(tile.loc);
      if (!centre || Math.abs(centre.y - tile.center.y) < 1e-3) continue;
      wallCache.delete(tile.loc.id);
      rebuildTile(tile, tile.loc);
    }
  }

  // --- Frame-Hook: Detail-Ansicht (Singleton), NPC-Animation, Pin-Bobbing ---
  let bob = 0;
  engine.addFrameHook((dt) => {
    relevelTiles();
    // Who owns the open view this frame (Etappe 3):
    //  - EMBODIED, the avatar's own location IS it — auto-open on entering
    //    (embody start included), auto-close on stepping out. The camera
    //    cannot close it: the wheel stops at EMBODY_MAX_DIST 34, which is
    //    inside CLOSE_CAM_DIST 60 (finding B12).
    //  - OVERVIEW, the explicit choice stands until the explicit close or an
    //    auto-close: camera beyond CLOSE_CAM_DIST, or the tile panned out of
    //    view. There is NO auto-REopen — opening is only ever explicit.
    // Closing is always the crossfade below, never a hard cut.
    if (getGameState().mode === 'embodied') {
      const pos = npcs.positionOf(avatarName);
      if (pos) {
        const t = tileAt(pos.x, pos.z);
        if (t && openable(t)) openLocation(t.loc.id);
        else closeOpenLocation();
      }
    } else if (openLocationId) {
      const t = tiles.get(openLocationId);
      const off = t
        ? Math.hypot(engine.target.x - t.center.x, engine.target.z - t.center.z)
        : Infinity;
      if (!t || engine.dist > CLOSE_CAM_DIST || off > closeTargetDist(t)) {
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
    if (!basementOpen) {
      terrainGround.setHole(null);
    } else {
      // The hole is the FOOTPRINT of the open location, as an axis-aligned
      // rectangle: a square of edge w turned by yaw spans
      // `w/2 · (|cos yaw| + |sin yaw|)` on each axis, which is exactly w/2 at
      // yaw 0 and grows to w·0.707 at 45°. The ground is cut, not the tile, so
      // the rectangle has to be stated in world axes.
      const half = (basementOpen.width / 2)
        * (Math.abs(Math.cos(basementOpen.yaw)) + Math.abs(Math.sin(basementOpen.yaw)));
      let minX = basementOpen.center.x - half;
      let minZ = basementOpen.center.z - half;
      let maxX = basementOpen.center.x + half;
      let maxZ = basementOpen.center.z + half;
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
        // the pit does not grow away from the viewer. It grows by one whole
        // footprint at most, the same "up to double the extent" as before.
        const grow = basementOpen.width;
        if (ux > 0) maxX += grow * ux; else minX += grow * ux;
        if (uz > 0) maxZ += grow * uz; else minZ += grow * uz;
      }
      terrainGround.setHole([minX, minZ, maxX, maxZ]);
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
          hide = Math.hypot(tile.center.x - px, tile.center.z - pz)
            < tile.width * OCCLUDER_RADIUS_FACTOR;
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

    // The LOCKED look of a threshold is bound here, not at build time: it
    // follows the avatar's `/play/scene` poll — its lock map, the location that
    // answer belongs to — and the room the avatar stands in, all of which
    // change long after a tile was built (task C2). Repainted only when one of
    // the three actually changed; Hud.tsx publishes a new map object only on a
    // real change, so identity is the whole comparison for the map.
    const lockState = getGameState();
    const roomNow = roomOf.get(avatarName) ?? '';
    if (lockState.lockedRooms !== lockPainted.locks
      || lockState.lockedLoc !== lockPainted.loc
      || roomNow !== lockPainted.room) {
      lockPainted = { locks: lockState.lockedRooms, loc: lockState.lockedLoc, room: roomNow };
      // Every tile, not just the avatar's: `applyDoorLocks` paints a foreign
      // location OPEN, and the place just left has to lose its red doors.
      for (const locId of doorMarks.keys()) applyDoorLocks(locId);
    }
    // Boundary thresholds exist ONLY to show a barred way in: a location the
    // server refuses this avatar the step into shows them, every other one
    // shows nothing. `lockedLocations` holds at most the four cells around the
    // avatar, so this is the neighbour one is walking towards.
    for (const [locId, root] of boundaryMarks) {
      root.visible = isLocked(lockState.lockedLocations, locId);
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

  // --- Arriving IN the avatar (finding B15) ---------------------------------
  // "Enter world" ends where the player actually is, not on the overview. The
  // camera used to stop at `fitDistance(world_bounds)` — the whole map from
  // above — and every session began with the same two manual steps: find your
  // own figure, take control. That is the arrival, so the world does it.
  //
  // It is `takeControl` and nothing else: the ONE way into the mode (fly in,
  // open the detail view of the place one is in, hand the figure over), so
  // this shares every rule with the HUD button, the zoom wall included.
  //
  // Two conditions, both of them "there is nobody to be":
  //  - no avatar at all (`avatar` is "" for a session that controls nobody) —
  //    then the overview IS the view, exactly as before;
  //  - an avatar whose figure is not on the map yet (unplaced location, a
  //    model still loading). `takeControl` would say so in a toast, which is
  //    right when a player pressed the button and wrong as a greeting, so the
  //    boot asks first and stays on the overview in silence.
  // Last in `startApp` on purpose: everything it touches (figures, tiles, the
  // registered action) stands by now.
  if (firstMap.avatar && npcs.positionOf(firstMap.avatar)) {
    gameActions.takeControl?.();
  }
}

boot();
