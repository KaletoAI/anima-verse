/**
 * WHERE AN NPC STANDS AFTER A BRIDGE CLIP (plan bruecken-feinschliff, Task C4).
 *
 * A bridge clip with root motion (getting up out of a chair or a bed) carries
 * the body off the seat, and when it ends the NPC's root takes that travel
 * over (`Figure.takeTravel`, rule 4). The server has already put the
 * character on the point the same clip sets it down
 * (`app/core/room_stand.py` `bridge_stand_point` = seat + the clip's travel,
 * then `pick_stand`), so the NPC's goal IS that stand point and the hand-over
 * moves the root only.
 *
 * Client and server measure the travel differently (the client per rig, with
 * the bridge's turn in the root; the server from the sidecar's `travel_m`
 * scaled by the height), so the body lands a few centimetres off the server's
 * point — and walking those centimetres after the clip has put the feet down
 * is the shuffle this rule removes: within `STAND_ADOPT_M` the NPC keeps the
 * spot it stands on, for as long as the server sends the same position.
 *
 * Pure, no three: the manager (`npcs.ts`) calls it at the hand-over and on
 * every poll; `client3d/scripts/smoke_stand_settle.mjs` checks it by hand.
 */

/** How far off the server's stand point a figure may stand and keep its spot,
 *  in metres — the raster step of the server's own stand search
 *  (`app/core/room_stand.py`: `STAND_GRID_M = 0.25`, the candidate grid of
 *  `pick_stand`). Closer than that the server could not have placed the
 *  figure any better, so the difference is the two travel measurements, not
 *  a decision to walk. */
export const STAND_ADOPT_M = 0.25;

/** Two server positions closer than this are the SAME position, in metres.
 *  The server writes centimetre-rounded points, so a real move is at least
 *  1 cm; below a millimetre it is float noise of the payload round trip. */
export const SAME_STAND_M = 0.001;

export interface StandXZ { x: number; z: number }

/** A kept spot: the server position it was taken against, and the figure's
 *  offset from it (X/Z; the height stays the server's). */
export interface StandSettle { server: StandXZ; offset: StandXZ }

/** The offset `figurePos − serverPos` the NPC keeps, or `null` when it walks
 *  to the server's point instead.
 *
 *  `lastServerPos` is the position the spot was taken against: at the
 *  hand-over that is `serverPos` itself, on a later poll the settle's own
 *  `server`. A server that moved (further than `SAME_STAND_M`) voids the spot
 *  — a new order, a journey — and so does a figure further than `tol` off
 *  the point (it walks there, as before). The bound is inclusive. */
export function settleOffset(figurePos: StandXZ, serverPos: StandXZ, lastServerPos: StandXZ,
                             tol = STAND_ADOPT_M): StandXZ | null {
  if (!(Math.hypot(serverPos.x - lastServerPos.x, serverPos.z - lastServerPos.z) <= SAME_STAND_M)) {
    return null;
  }
  const x = figurePos.x - serverPos.x;
  const z = figurePos.z - serverPos.z;
  return Math.hypot(x, z) <= tol ? { x, z } : null;
}
