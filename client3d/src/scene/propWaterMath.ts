/** Import-free twin of model_water.water_region_at. Boundaries belong to rings. */
type Ring = readonly (readonly [number, number])[];
export interface WaterRegion {
  outline: Ring;
  holes?: readonly Ring[];
  y: number;
  bed_y: number;
  swim_from_m: number;
}
export interface WaterHit { y: number; bed_y: number; swim_from_m: number }

function pointInRing(x: number, z: number, ring: Ring): boolean {
  let inside = false;
  for (let i = 0; i < ring.length; i++) {
    const [ax, az] = ring[i];
    const [bx, bz] = ring[(i + ring.length - 1) % ring.length];
    const cross = (x - ax) * (bz - az) - (z - az) * (bx - ax);
    if (Math.abs(cross) < 1e-9 && x >= Math.min(ax, bx) - 1e-9
        && x <= Math.max(ax, bx) + 1e-9 && z >= Math.min(az, bz) - 1e-9
        && z <= Math.max(az, bz) + 1e-9) return true;
    if ((az > z) !== (bz > z) && x < (bx - ax) * (z - az) / (bz - az) + ax) inside = !inside;
  }
  return inside;
}

export function pointInRegion(region: Pick<WaterRegion, 'outline' | 'holes'>,
                              x: number, z: number): boolean {
  return pointInRing(x, z, region.outline)
    && !(region.holes ?? []).some((hole) => pointInRing(x, z, hole));
}

/** Callers select the storey, as they do for the baked surfaces. */
export function waterRegionAt<S extends { water?: { regions: readonly WaterRegion[] } }>(
  specs: Iterable<S>, x: number, z: number, liftOf: (spec: S) => number = () => 0,
): WaterHit | null {
  let best: WaterHit | null = null;
  for (const spec of specs) {
    for (const region of spec.water?.regions ?? []) {
      if (!pointInRegion(region, x, z)) continue;
      const lift = liftOf(spec);
      const y = region.y + lift;
      if (!best || y > best.y) best = { y, bed_y: region.bed_y + lift,
        swim_from_m: region.swim_from_m };
    }
  }
  return best;
}
