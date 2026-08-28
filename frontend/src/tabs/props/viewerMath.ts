/**
 * viewerMath — the two pure rules the prop viewer's controls are made of.
 *
 * Both are DECISIONS, not rendering: when a hand-drawn ring is closed, and
 * when a freshly loaded model is a different enough object to be framed
 * again. They live outside the component because a pure function can be
 * checked by a node run, while a rule buried in a WebGL effect cannot.
 */

/** Squared pixel distance — the comparison never needs the root. */
const dist2 = (a: readonly [number, number], b: readonly [number, number]) =>
  (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2

/**
 * Does a click at `pt` CLOSE the ring `points`?
 *
 * The map's rule (`MapTab.addDraftPoint`): a ring closes by clicking its FIRST
 * vertex again, within `tolPx` PIXELS — measured on screen so it is equally
 * easy to hit however far the camera has been zoomed. Below three points there
 * is no area to close, so a click on the start point is an ordinary point
 * there, even at distance 0.
 */
export function closesOnFirstPoint(
  points: ReadonlyArray<readonly [number, number]>,
  pt: readonly [number, number],
  tolPx: number,
): boolean {
  if (points.length < 3) return false
  return dist2(points[0], pt) <= tolPx * tolPx
}

/**
 * Must a newly loaded model be FRAMED again, or does the camera stay?
 *
 * A model switch inside one viewer is usually the same object in another
 * version — a re-split frame, a picture variant, the far tier. Re-framing on
 * every one of them throws away the angle the admin was working at, which is
 * why the camera survives a switch by default. Only a real change of SIZE
 * re-frames: no previous model at all (nothing to keep), or a bounding-sphere
 * radius more than 25 % away from the previous one (a door swapped for a
 * poster) — at that point the old camera would show empty space or the inside
 * of the mesh.
 */
export function shouldRefit(prevRadius: number | null | undefined,
  nextRadius: number): boolean {
  if (prevRadius == null || !(prevRadius > 0) || !(nextRadius > 0)) return true
  return Math.abs(nextRadius - prevRadius) / prevRadius > 0.25
}
