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
 * `game/embody.ts` (mode, selection, talk target), `CharacterPlaque.tsx` (one
 * field — clearing the selection) and `Hud.tsx` (party state out of the
 * `/play/scene` poll — `movementLocked` + `partyLeader`, E3-T3).
 */
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
}

/** Actions the React side calls INTO the vanilla app; main.ts registers them. */
export interface HudGameActions {
  zoomTo?: (charName: string) => void;
  enterEmbodied?: () => void;
  exitEmbodied?: () => void;
}

/** React-side handlers the vanilla app calls (e.g. the F key opens the chat). */
export interface HudUiActions {
  openChat?: () => void;
  /** show a short message to the player (Hud.tsx wires the package toast) —
   *  the vanilla side renders no text of its own (E3-T3) */
  toast?: (msg: string) => void;
}

const state: HudGameState = {
  mode: 'overview', selected: null, talkTarget: null,
  movementLocked: false, partyLeader: '',
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
