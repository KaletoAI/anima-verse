import { polygonDistance } from './polygon';

export type Ring = 'near' | 'far' | 'gone';
// 150 m ≈ 44 s at walking pace before a place must be ready;
// Anima Divide (12 places, 2026-10-16): median 5 / max 8 places near from any place centre.
export const NEAR_IN_M = 150;
export const NEAR_OUT_M = 180;
export const FAR_PAD_M = 40;
export const FAR_OUT_FACTOR = 1.2;
export function ringFor(dist: number, current: Ring, pinned: boolean, fogM: number): Ring {
  if (pinned || dist <= (current === 'near' ? NEAR_OUT_M : NEAR_IN_M)) return 'near';
  return dist <= (fogM + FAR_PAD_M) * (current === 'gone' ? 1 : FAR_OUT_FACTOR) ? 'far' : 'gone';
}
export interface FootprintLike {
  center: { x: number; z: number };
  yaw: number;
  boundary: [number, number][] | null;
  width: number;
}
/** Minimum footprint distance over avatar and camera focus; interior = zero. */
export function placeDistance(p: FootprintLike, points: { x: number; z: number }[]): number {
  const c = Math.cos(p.yaw), s = Math.sin(p.yaw);
  let best = Infinity;
  for (const point of points) {
    const dx = point.x - p.center.x, dz = point.z - p.center.z;
    const d = p.boundary ? polygonDistance(c * dx - s * dz, s * dx + c * dz, p.boundary)
      : Math.max(0, Math.hypot(dx, dz) - p.width * Math.SQRT1_2);
    best = Math.min(best, d);
  }
  return best;
}
