/**
 * Embodied mode: taking control of the avatar figure (plan-3d-game stage 3,
 * task 2).
 *
 * The mode is nothing but three camera facts plus one bus flag:
 * - `engine.follow` points at the avatar, so the camera chases it and the
 *   movement keys stop panning (task 3 hands them to the avatar),
 * - `engine.flyTo(avatar, EMBODY_DIST)` pulls the camera in,
 * - `engine.orbitOnDrag` hands the bare left drag to the view (B19).
 * There is NO tween of our own: the existing fly and the soft follow lerp of
 * the engine together are the ride, in both directions.
 *
 * Leaving happens TWO ways, both through `exitEmbodied`: the HUD chip and Esc.
 *
 * THE WHEEL IS NOT ONE OF THEM ANY MORE (finding B12). It used to be: zooming
 * out past a threshold simply dropped the mode, which read as the view sliding
 * seamlessly back into the overview and never told the player that giving up
 * control is a decision — one arrived in the map view without knowing what had
 * happened or how to get back. Zooming out now STOPS at `EMBODY_MAX_DIST`
 * (`engine.zoomCap`) and the cap reports itself, so the hint can point at the
 * chip that leaves. The distance is the same 34 m the exit used to trip at:
 * far enough to see the surroundings of the figure, and still inside the 60 m
 * at which an open detail view closes (`CLOSE_CAM_DIST` in main.ts), so an
 * open interior can never close under an embodied avatar.
 */
import type * as THREE from 'three';
import type { Engine } from '../scene/engine';
import { getGameState, setGameState } from '../hud/bus';

export const EMBODY_DIST = 7;    // camera distance right after entering
export const EMBODY_MAX_DIST = 34;  // the wheel stops here while embodied
const OVERVIEW_DIST = 70;        // distance the camera returns to (boot value)

export interface EmbodyDeps {
  engine: Engine;
  avatarPos: () => THREE.Vector3 | null;   // npcs.positionOf(avatarName)
}

/** Enter: fly in, hang the camera on the avatar and bind its zoom-out. No-op
 *  without a figure on the map (model still loading) or when already
 *  embodied. */
export function enterEmbodied(deps: EmbodyDeps): void {
  if (getGameState().mode === 'embodied') return;
  const pos = deps.avatarPos();
  if (!pos) return;
  // The cap goes up BEFORE the fly, and the fly is free of it on purpose: it
  // travels from the overview distance INWARDS, so nothing about it needs the
  // ceiling — and the very next wheel notch is already bound by it.
  deps.engine.zoomCap = EMBODY_MAX_DIST;
  // The mouse turns the view here (B19): with the camera on the figure a
  // pan-drag is undone by the chase in the next frame anyway, so the bare
  // button is free for the one thing one does want — looking around.
  deps.engine.orbitOnDrag = true;
  deps.engine.flyTo(pos, EMBODY_DIST);
  deps.engine.follow = deps.avatarPos;
  setGameState({ mode: 'embodied' });
}

/** Leave: drop the follow and the zoom cap, and pull back out where the avatar
 *  stands. */
export function exitEmbodied(deps: EmbodyDeps): void {
  const { engine } = deps;
  engine.follow = null;
  // Back to the overview controls: drag pans again, Shift+drag turns (B19).
  engine.orbitOnDrag = false;
  // Before the fly, or the camera would be pulled back to the cap it has just
  // been released from.
  engine.zoomCap = null;
  engine.flyTo(deps.avatarPos() ?? engine.target.clone(), OVERVIEW_DIST);
  setGameState({ mode: 'overview' });
}
