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
 * `game/embody.ts` (mode, selection, talk target, elevator), `CharacterPlaque.tsx` (one
 * field — clearing the selection) and `Hud.tsx` (party state out of the
 * `/play/scene` poll — `movementLocked` + `partyLeader`, E3-T3).
 */
import type { ElevatorState } from '../game/elevator';
import type { PerfStats } from '../game/perfstats';
import type { Prefs } from '../game/prefs';
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
  /** elevator the avatar is standing at (embodied mode), or null. The talk
   *  prompt WINS over it: with someone in range only that prompt shows, so one
   *  F press is never two offers at once. */
  elevator: ElevatorState | null;
  /** the storey choice is unfolded (F opens and closes it, Esc closes it) */
  elevatorOpen: boolean;
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
  exitEmbodied?: () => void;
  /** ride to that storey: enter its room on the server, then walk the figure
   *  to the holding point of the target storey */
  rideElevator?: (level: number) => void;
  /** perform the offered location entry (the real server step + walk-in) */
  enterLocation?: () => void;
  /** sign out and return to the title screen — the game menu's "Back to
   *  title" (E4-T4). main.ts owns the flow (logout + reload), so the menu
   *  does not become a second shutdown path. */
  backToTitle?: () => void;
  /** the player changed an audio setting in the menu (E4-T4). The VOLUMES are
   *  already applied to the engine when this runs — this is for the switches
   *  (musicOn/ambientOn/ttsOn), which say what should play at all and are the
   *  business of the music/ambience/speech drivers (stage 4, tasks 5 + 6).
   *  Only CHANGES arrive here; the state at startup is read with `loadPrefs`. */
  applyAudioPrefs?: (prefs: Prefs) => void;
}

/** React-side handlers the vanilla app calls (e.g. the F key opens the chat). */
export interface HudUiActions {
  openChat?: () => void;
  /** show a short message to the player (Hud.tsx wires the package toast) —
   *  the vanilla side renders no text of its own (E3-T3) */
  toast?: (msg: string) => void;
  /** M opens and closes the game menu (E4-T4) */
  toggleMenu?: () => void;
  /** Esc: close the menu IF it is open, and say whether it was — the caller
   *  hands the key on to the mode exit when it was not. */
  closeMenu?: () => boolean;
}

const state: HudGameState = {
  mode: 'overview', selected: null, talkTarget: null,
  movementLocked: false, partyLeader: '',
  elevator: null, elevatorOpen: false, enterOffer: null,
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
