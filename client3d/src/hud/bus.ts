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
 * it without pulling the HUD bundle in. Only `main.ts` writes game state; the
 * plaque writes exactly one field (clearing the selection).
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
}

const state: HudGameState = {
  mode: 'overview', selected: null, talkTarget: null, movementLocked: false,
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
