/**
 * Embodied mode: taking control of the avatar figure (plan-3d-game stage 3,
 * task 2).
 *
 * The mode is nothing but a handful of camera facts plus one bus flag:
 * - `engine.follow` points at the avatar's EYES, so the camera chases it and
 *   the movement keys stop panning (task 3 hands them to the avatar),
 * - `engine.flyTo(eyes, EMBODY_DIST)` pulls the camera in,
 * - `engine.zoomFloor`/`engine.nearPitchDeg` make the close view a look over
 *   the avatar's shoulder rather than down at its feet (see below),
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
 *
 * ZOOMING IN aims at the EYES, not at the figure's root (2026-09-02). The
 * camera used to follow `positionOf`, which is the root — and a root sits at
 * the feet, so the centre of the picture was the ankles at every distance and
 * the head left the frame below ~3 m: the closer one zoomed, the more of the
 * shot was the ground the avatar stands on. Three numbers together make the
 * close view a look at what the avatar looks at, and all three live in
 * `scene/cameraFraming.ts` with their derivations:
 * - the aim point is `npcs.eyeOf` (0.94 · height, 1.60 m on a 1.70 m figure),
 * - `EMBODY_MIN_DIST` (2 m) keeps the camera out of the head,
 * - `EMBODY_NEAR_PITCH_DEG` (8° instead of 18°) flattens the near end, which
 *   is what puts the horizon inside the frame ahead of the avatar.
 * At the floor that is a camera 2.04 m up and 1.95 m behind the head, looking
 * 12.8° down: head in the centre, horizon 12.8° above it, half-frame 22.5°.
 */
import type * as THREE from 'three';
import type { Engine } from '../scene/engine';
import {
  EMBODY_MIN_DIST, EMBODY_NEAR_PITCH_DEG, OVERVIEW_NEAR_PITCH_DEG,
} from '../scene/cameraFraming';
import { getGameState, setGameState } from '../hud/bus';

export const EMBODY_DIST = 7;    // camera distance right after entering
export const EMBODY_MAX_DIST = 34;  // the wheel stops here while embodied
const OVERVIEW_DIST = 70;        // distance the camera returns to (boot value)

export interface EmbodyDeps {
  engine: Engine;
  avatarPos: () => THREE.Vector3 | null;   // npcs.positionOf(avatarName)
  /** npcs.eyeOf(avatarName) — the point the camera AIMS at while embodied.
   *  Kept apart from `avatarPos` because the two are different questions:
   *  where the avatar stands (the fly-out on leaving wants the ground) and
   *  where it looks from. */
  avatarEye: () => THREE.Vector3 | null;
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
  // …and so does the floor, before the fly it now binds as well.
  deps.engine.zoomFloor = EMBODY_MIN_DIST;
  deps.engine.nearPitchDeg = EMBODY_NEAR_PITCH_DEG;
  // The mouse turns the view here (B19): with the camera on the figure a
  // pan-drag is undone by the chase in the next frame anyway, so the bare
  // button is free for the one thing one does want — looking around.
  deps.engine.orbitOnDrag = true;
  deps.engine.flyTo(deps.avatarEye() ?? pos, EMBODY_DIST);
  deps.engine.follow = deps.avatarEye;
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
  engine.zoomFloor = null;
  engine.nearPitchDeg = OVERVIEW_NEAR_PITCH_DEG;
  engine.flyTo(deps.avatarPos() ?? engine.target.clone(), OVERVIEW_DIST);
  setGameState({ mode: 'overview' });
}
