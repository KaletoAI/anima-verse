/**
 * The ONE channel between the vanilla Three.js app and the React HUD island
 * (plan-3d-game stage 3, task 1).
 *
 * Two directions, both explicit:
 * - vanilla -> React: `setGameState` publishes a fresh immutable snapshot,
 *   React reads it with `useSyncExternalStore(subscribeGameState, getGameState)`.
 * - React -> vanilla: `gameActions` holds handlers `main.ts` registers (zoom,
 *   enter/exit embodied); `uiActions` holds React handlers the vanilla side
 *   calls (e.g. a key press opening the chat).
 *
 * Deliberately dependency-free: no React import here, so scene code may import
 * it without pulling the HUD bundle in. Game state has three writers, each
 * owning a disjoint set of fields: `main.ts` with its mode helper
 * `game/embody.ts` (mode, selection, talk target, elevator, stairs), `CharacterPlaque.tsx` (one
 * field — clearing the selection) and `Hud.tsx` (what the `/play/scene` poll
 * says: `movementLocked` + `partyLeader` (E3-T3), `groundRoomId` and the two
 * lock maps of task C2).
 */
import type { ElevatorState } from '../game/elevator';
import type { MinimapState } from '../game/minimap';
import type { PerfStats } from '../game/perfstats';
import type { Prefs, ScatterPrefs } from '../game/prefs';
import type { StairPrompt } from '../game/stairs';
import type { MapCharacter } from '../types';

export type GameMode = 'overview' | 'embodied';

export interface HudGameState {
  mode: GameMode;
  /** selected figure (worldmap snapshot, refreshed on every poll) or null */
  selected: { char: MapCharacter; isAvatar: boolean } | null;
  /** NPC currently in talk range (embodied mode), or null */
  talkTarget: string | null;
  /** avatar cannot move on its own (party follower) — HUD hint, server enforces */
  movementLocked: boolean;
  /** name of the party leader while `movementLocked` is set, else empty */
  partyLeader: string;
  /** Id of the ground room of the avatar's CURRENT location, from the
   *  `/play/scene` room list (`is_ground`) — empty while no payload has
   *  arrived. The ground is a room with an id but no geometry, so the room
   *  walk cannot find it by distance; it reads the id here instead of knowing
   *  the server's reserved constant. */
  groundRoomId: string;
  /** Rooms of the CURRENT location the server refuses this avatar, id -> its
   *  localized reason (`/play/scene → rooms[].enterable === false`, task C1).
   *  A key exists exactly for what is locked. The scene code binds it by id
   *  at render/interaction time — it is per avatar and per moment, so it never
   *  goes into a cached scene payload (§ 3 decision 2). */
  lockedRooms: Record<string, string>;
  /** The location `lockedRooms` was answered for. Room ids are NOT unique
   *  across locations — a clone inherits its template's rooms with their ids —
   *  so a lock may only ever be bound to the rooms of THIS location. Published
   *  together with the map, never derived from another poll, or the two could
   *  disagree for a moment and paint a lock onto a stranger's door. */
  lockedLoc: string;
  /** Neighbour LOCATIONS entering would be refused for, id -> reason (the
   *  `neighbors` block of the same poll). Only the places the server counts as
   *  neighbours of the avatar's own can appear here — which is exactly the
   *  range in which a locked way has to be visible before one walks to it. */
  lockedLocations: Record<string, string>;
  /** elevator the avatar is standing at (embodied mode), or null. The talk
   *  prompt WINS over it: with someone in range only that prompt shows, so one
   *  F press is never two offers at once. */
  elevator: ElevatorState | null;
  /** the storey choice is unfolded (F opens and closes it, Esc closes it) */
  elevatorOpen: boolean;
  /** flight of stairs the avatar is standing at (embodied mode), or null. Like
   *  the lift this is one storey change on foot, but there is nothing to
   *  choose: a flight leads exactly one storey up or down, so the offer IS the
   *  button. The ELEVATOR prompt wins over it — standing at both, the avatar
   *  gets the lift's storey choice and no stair button, so the bottom row
   *  never carries two offers at once. */
  stairs: StairPrompt | null;
  /** adjacent location the avatar could enter (standing near a boundary
   *  opening, or next to a location without authored openings) — the
   *  "Betreten" offer of Etappe 3. Talk and elevator prompts win over it. */
  enterOffer: { name: string } | null;
}

/** Actions the React side calls INTO the vanilla app; main.ts registers them. */
export interface HudGameActions {
  zoomTo?: (charName: string) => void;
  /** show a line as a speech bubble over that figure's head (stage 6). The
   *  HUD owns the transcript poll, the scene owns the figures — so this is
   *  the only way the two meet. Unknown names are dropped by the scene. */
  sayBubble?: (charName: string, text: string) => void;
  enterEmbodied?: () => void;
  /** take control of the avatar from anywhere: fly to its place, open that
   *  location's detail view and enter the embodied mode. The figure-less way
   *  in — a character inside a closed room is not drawn, the avatar included,
   *  so there is nothing to click on for the plaque. */
  takeControl?: () => void;
  exitEmbodied?: () => void;
  /** ride to that storey: enter its room on the server, then walk the figure
   *  to the holding point of the target storey */
  rideElevator?: (level: number) => void;
  /** take the flight the avatar is standing at: enter the room the far landing
   *  lies in on the server, then walk the figure up (or down) it. No argument
   *  — the offer already names the one destination. */
  rideStairs?: () => void;
  /** perform the offered location entry (the real server step + walk-in) */
  enterLocation?: () => void;
  /** sign out and return to the title screen — the game menu's "Back to
   *  title" (E4-T4). main.ts owns the flow (logout + reload), so the menu
   *  does not become a second shutdown path. */
  backToTitle?: () => void;
  /** the administrator flipped "show all locations" in the game menu. The
   *  switch changes which VIEW the client fetches, and main.ts applies it to
   *  the running world — the places of the other view are added and removed in
   *  place, so there is no reload and nothing is lost. */
  setShowAll?: (on: boolean) => void;
  /** the player changed an audio setting in the menu (E4-T4). The VOLUMES are
   *  already applied to the engine when this runs — this is for the switches
   *  (musicOn/ambientOn/ttsOn), which say what should play at all and are the
   *  business of the music/ambience/speech drivers (stage 4, tasks 5 + 6).
   *  Only CHANGES arrive here; the state at startup is read with `loadPrefs`. */
  applyAudioPrefs?: (prefs: Prefs) => void;
  /** the player changed a scatter detail distance in the menu (per-object
   *  scatter LOD, 2026-08-15). `main.ts` hands it to the ground, which re-bins
   *  the props at once instead of waiting for the next LOD tick. Only CHANGES
   *  arrive here; the state at startup the ground reads for itself, the same
   *  way the audio drivers read `loadPrefs`. */
  applyScatterPrefs?: (prefs: ScatterPrefs) => void;
}

/** React-side handlers the vanilla app calls (e.g. the F key opens the chat). */
export interface HudUiActions {
  openChat?: () => void;
  /** show a short message to the player (Hud.tsx wires the package toast) —
   *  the vanilla side renders no text of its own (E3-T3). ``translate`` marks
   *  an ENGLISH source string that still needs the HUD's i18n (a finding of
   *  the scene composer, § 4.3); a server text is already localized and goes
   *  out as it is. */
  toast?: (msg: string, translate?: boolean) => void;
  /** M opens and closes the game menu (E4-T4) */
  toggleMenu?: () => void;
  /** Esc: close the menu IF it is open, and say whether it was — the caller
   *  hands the key on to the mode exit when it was not. */
  closeMenu?: () => boolean;
}

const state: HudGameState = {
  mode: 'overview', selected: null, talkTarget: null,
  movementLocked: false, partyLeader: '', groundRoomId: '',
  lockedRooms: {}, lockedLocations: {}, lockedLoc: '',
  elevator: null, elevatorOpen: false, stairs: null, enterOffer: null,
};
const listeners = new Set<() => void>();
let snapshot: HudGameState = { ...state };

export const gameActions: HudGameActions = {};
export const uiActions: HudUiActions = {};

export function setGameState(patch: Partial<HudGameState>): void {
  Object.assign(state, patch);
  snapshot = { ...state };
  for (const fn of listeners) fn();
}
/** For React's useSyncExternalStore: stable snapshot per change. */
export function getGameState(): HudGameState { return snapshot; }
export function subscribeGameState(fn: () => void): () => void {
  listeners.add(fn);
  return () => { listeners.delete(fn); };
}

// --- Performance readout (Etappe 5, plan-3d-lod-und-betreten.md) ------------
//
// A SECOND store next to the game state, with its own listener set, because
// this one ticks several times a second: publishing it through `setGameState`
// would re-render the chat, the plaque and the rail along with it — the
// display would cost more than what it measures.
//
// The switch travels the other way (React -> vanilla) and is a plain flag
// rather than an action: `main.ts` asks before it measures, so a hidden
// overlay costs nothing at all, not even the traversal.

let perf: PerfStats | null = null;
const perfListeners = new Set<() => void>();
let perfOn = false;

/** main.ts publishes a fresh readout (null = nothing measured right now). */
export function setPerfStats(next: PerfStats | null): void {
  perf = next;
  for (const fn of perfListeners) fn();
}
export function getPerfStats(): PerfStats | null { return perf; }
export function subscribePerfStats(fn: () => void): () => void {
  perfListeners.add(fn);
  return () => { perfListeners.delete(fn); };
}

/** The HUD switches the readout on and off; switching it off also clears the
 *  last numbers, so re-opening never shows a frozen picture from minutes ago. */
export function setPerfEnabled(on: boolean): void {
  perfOn = on;
  if (!on) setPerfStats(null);
}
/** Asked by main.ts before it measures — see the note above. */
export function perfEnabled(): boolean { return perfOn; }

// --- Minimap (Etappe 5, task 3) ---------------------------------------------
//
// A THIRD store, for the same reason the perf readout got the second one: this
// slice is republished up to four times a second while one walks, and pushing
// it through `setGameState` would re-render the chat, the plaque and the whole
// rail with every step. Here it re-renders one canvas and nothing else.
//
// `main.ts` is the only writer and it publishes only on a real CHANGE (the
// avatar's metre position, the quantised yaw, the painted ground or the world
// frame) — so a subscriber can treat every notification as "redraw", and
// standing still costs nothing at all.

const emptyMinimap: MinimapState = {
  areas: [], relief: null, locations: [], avatar: null, yaw: 0, bounds: null,
};
let minimap: MinimapState = emptyMinimap;
const minimapListeners = new Set<() => void>();

/** main.ts publishes a fresh slice. Pass `null` for "nothing to show" (the
 *  overview mode), which is the initial state as well. */
export function setMinimap(next: MinimapState | null): void {
  minimap = next ?? emptyMinimap;
  for (const fn of minimapListeners) fn();
}
export function getMinimap(): MinimapState { return minimap; }
export function subscribeMinimap(fn: () => void): () => void {
  minimapListeners.add(fn);
  return () => { minimapListeners.delete(fn); };
}
