// Shared visibility horizon for scene fog, minimap and height-tile prefetch.
export const FOG_NEAR_M = 220;
export const FOG_FAR_M = 520;

/** Three's linear fog uses view-space depth, with a smoothstep transition. */
export function fogFactor(depth: number): number {
  if (depth <= FOG_NEAR_M) return 0;
  if (depth >= FOG_FAR_M) return 1;
  const t = (depth - FOG_NEAR_M) / (FOG_FAR_M - FOG_NEAR_M);
  return t * t * (3 - 2 * t);
}
