import { DIM_KEYS, DIM_MAX_M, DIM_MIN_M, orientedDims, variantRedistribute,
  type DimKey } from './dims'
import type { PropDims } from './propTypes'

/** Ratio source is the oriented mesh box, or this variant's declared aspect. */
export function dimRatios(dims: PropDims, bbox: [number, number, number] | null,
  rotation?: { x?: number; y?: number; z?: number }): Record<DimKey, number> {
  if (bbox) {
    const [w, h, d] = orientedDims(bbox, rotation)
    return { width_m: w, depth_m: d, height_m: h }
  }
  return { width_m: dims.width_m, depth_m: dims.depth_m, height_m: dims.height_m }
}

/** Existing resize law: one edge drives the uniformly scaled, rounded trio. */
export function dimsPatch(stored: PropDims, key: DimKey, raw: string,
  ratios: Record<DimKey, number>): PropDims | null {
  const n = parseFloat(raw)
  if (!Number.isFinite(n) || n <= 0) return null
  const next = variantRedistribute(key, n, ratios) ?? {
    ...stored,
    [key]: Math.round(Math.min(Math.max(n, DIM_MIN_M), DIM_MAX_M) * 1000) / 1000,
  }
  if (DIM_KEYS.every((k) => next[k] === stored[k])) return null
  return next as PropDims
}

/** Transient arithmetic context, not another draft: pendingFields owns dims. */
export interface DimensionGesture {
  uid: string
  key: DimKey
  ratios: Record<DimKey, number>
}

/** Freeze the aspect before the first keystroke; clamp/round results must never
 * become the next keystroke's ratio source. Invalid text still pins the field. */
export function editDimensionGesture(previous: DimensionGesture | null,
  uid: string, stored: PropDims, key: DimKey, raw: string,
  bbox: [number, number, number] | null,
  rotation?: { x?: number; y?: number; z?: number }): {
    gesture: DimensionGesture; dims: PropDims
  } {
  const gesture = previous?.uid === uid && previous.key === key ? previous
    : { uid, key, ratios: dimRatios(stored, bbox, rotation) }
  return { gesture, dims: dimsPatch(stored, key, raw, gesture.ratios) || stored }
}
