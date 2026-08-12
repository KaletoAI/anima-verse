/**
 * scatter — how scattered props are PLACED and how they STAND, for both
 * renderers.
 *
 * The 3D client plants them on the world map; the map editor draws the very
 * same points as a top-down preview. That only stays true if the maths lives
 * in ONE place, so it lives here.
 *
 * NO IMPORT AT ALL, not even a type one. Everything in this file is arithmetic
 * on numbers and number pairs, and that is what lets
 * `client3d/scripts/smoke_scatter_math.mjs` load it through the plain esbuild
 * transpile the other pure smokes use — no bundler, no stand-ins. If someone
 * ever adds a runtime import, that loader fails loudly, which is the intended
 * alarm.
 */

/** How a loaded prop mesh has to be transformed to STAND on the ground. */
export interface PropGroundFit {
  /** uniform scale factor; 1 when no target height was asked for */
  scale: number
  /** metres to add to y AFTER scaling, so the lowest point sits at 0 */
  offsetY: number
}

/**
 * Put a prop ON the ground instead of THROUGH it (finding B16).
 *
 * A GLB carries whatever origin its author chose — for a tree that is
 * typically the middle of the trunk, so half of it stood below y = 0 while the
 * placeholder cone next to it (built at base = 0) stood correctly. The fix is
 * pure arithmetic on the mesh's bounding box in its own frame:
 *
 *   scale   = targetH / (maxY − minY)   when a target height is asked for
 *   offsetY = −minY · scale             the lowest point after scaling
 *
 * so the bounding box afterwards runs from y = 0 to y = targetH. Worked
 * example, the one from the finding: a 2 m tree modelled around its centre has
 * minY = −1, maxY = +1. Without a target height that is scale 1, offsetY +1 —
 * the metre it used to sink. With `height_m = 4` it is scale 2 (a 4 m tree)
 * and offsetY +2, because after scaling the lowest point is at −2.
 *
 * A degenerate box (a flat plane, a single point) has no height to scale, so
 * the scale stays 1 and only the lift applies — a flat prop lies on the
 * ground rather than vanishing into an infinite scale.
 */
export function propGroundFit(minY: number, maxY: number,
                              targetH?: number | null): PropGroundFit {
  const lo = Number(minY)
  const hi = Number(maxY)
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return { scale: 1, offsetY: 0 }
  const height = hi - lo
  const target = Number(targetH)
  const scale = Number.isFinite(target) && target > 0 && height > 1e-6
    ? target / height
    : 1
  return { scale, offsetY: -lo * scale }
}
