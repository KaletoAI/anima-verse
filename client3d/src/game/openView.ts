/**
 * The overview auto-close of the ONE open detail view (Stage 3,
 * plan-3d-lod-und-betreten.md): when the camera has left the open location,
 * main.ts' frame hook closes it. There is NO auto-reopen — opening is only
 * ever explicit. Pure, so the browser and the native client share the cases in
 * shared/test-vectors/overview_labels.json (derivations:
 * client3d/scripts/smoke_overview_labels.mjs).
 */

/** Camera farther out than this closes the open view (overview only). Must
 *  stay ABOVE the embodied EMBODY_MAX_DIST 34 with headroom, so the open view
 *  can never close under an embodied avatar — 60 leaves 26 m of it, and since
 *  finding B12 the wheel cannot even reach the 34. */
export const CLOSE_CAM_DIST = 60;
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
export const CLOSE_TARGET_FOOTPRINTS = 3;
export const CLOSE_TARGET_MIN_M = 12;

/** How far the camera target may stray from the open location's centre: max(12, 3 · footprint width). */
export function closeTargetDist(width: number): number {
  return Math.max(CLOSE_TARGET_MIN_M, width * CLOSE_TARGET_FOOTPRINTS);
}

/**
 * The overview auto-close: the camera is farther out than `CLOSE_CAM_DIST`, or
 * its target stands farther than `closeTargetDist(width)` from the open
 * location's centre, measured on the ground plane (x/z only). Both strictly
 * greater: exactly at a limit the view stays open.
 */
export function openViewShouldClose(camDist: number, targetX: number, targetZ: number,
                                    centreX: number, centreZ: number, width: number): boolean {
  const off = Math.hypot(targetX - centreX, targetZ - centreZ);
  return camDist > CLOSE_CAM_DIST || off > closeTargetDist(width);
}
