/**
 * Embodied mode: taking control of the avatar figure (plan-3d-game stage 3,
 * task 2).
 *
 * The mode is nothing but two camera facts plus one bus flag:
 * - `engine.follow` points at the avatar, so the camera chases it and the
 *   movement keys stop panning (task 3 hands them to the avatar),
 * - `engine.flyTo(avatar, EMBODY_DIST)` pulls the camera in.
 * There is NO tween of our own: the existing fly and the soft follow lerp of
 * the engine together are the ride, in both directions.
 *
 * Leaving happens three ways, all through `exitEmbodied`: the HUD button, Esc
 * (bound in main.ts) and simply zooming out past `EXIT_DIST` — the mode is a
 * zoom level as much as a state, so the wheel must not be able to leave the
 * player half in it.
 */
import type * as THREE from 'three';
import type { Engine } from '../scene/engine';
import { getGameState, setGameState } from '../hud/bus';

export const EMBODY_DIST = 7;    // camera distance right after entering
export const EXIT_DIST = 34;     // zooming farther out than this leaves the mode
const OVERVIEW_DIST = 70;        // distance the camera returns to (boot value)

export interface EmbodyDeps {
  engine: Engine;
  avatarPos: () => THREE.Vector3 | null;   // npcs.positionOf(avatarName)
}

/**
 * The zoom-out exit is ARMED only once the camera has actually arrived inside
 * `EXIT_DIST`. Entering starts at overview distance (~70), which is already
 * past the threshold — an unarmed check would leave the mode in the very first
 * frame of the ride. Module state, because the signature of `checkExit` is the
 * frame hook's and there is exactly one camera per page.
 */
let exitArmed = false;

/** Enter: fly in and hang the camera on the avatar. No-op without a figure on
 *  the map (model still loading) or when already embodied. */
export function enterEmbodied(deps: EmbodyDeps): void {
  if (getGameState().mode === 'embodied') return;
  const pos = deps.avatarPos();
  if (!pos) return;
  exitArmed = false;
  deps.engine.flyTo(pos, EMBODY_DIST);
  deps.engine.follow = deps.avatarPos;
  setGameState({ mode: 'embodied' });
}

/** Leave: drop the follow and pull back out where the avatar stands. */
export function exitEmbodied(deps: EmbodyDeps): void {
  const { engine } = deps;
  engine.follow = null;
  exitArmed = false;
  engine.flyTo(deps.avatarPos() ?? engine.target.clone(), OVERVIEW_DIST);
  setGameState({ mode: 'overview' });
}

/** Per-frame: leaves the mode when the camera is zoomed out past EXIT_DIST.
 *  Call from a frame hook — it checks the mode itself. */
export function checkExit(deps: EmbodyDeps): void {
  if (getGameState().mode !== 'embodied') return;
  const { dist, targetDist } = deps.engine;
  if (!exitArmed) {
    if (dist < EXIT_DIST) exitArmed = true;
    // Zoomed back out DURING the ride: the wanted distance is the user's
    // intent (the fly sets it to EMBODY_DIST), so this can only be the wheel —
    // the ride is cancelled and the mode goes with it. Without this the camera
    // could stay outside EXIT_DIST forever and never arm.
    else if (targetDist > EXIT_DIST) exitEmbodied(deps);
    return;
  }
  if (dist > EXIT_DIST) exitEmbodied(deps);
}
