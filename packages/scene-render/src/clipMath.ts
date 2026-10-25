/** CPU twin of the fragment parity test, including its half-open boundary rule. */
export type ClipPoint = [number, number]
export const CLIP_POINT_LIMIT = 64
export const CUTOUT_POLYGON_LIMIT = 16
export function clipOutlinePoints(outline: ClipPoint[] | null | undefined): ClipPoint[] {
  return (outline || []).slice(0, CLIP_POINT_LIMIT)
}
export function cutoutPolygons(outlines: ClipPoint[][] | null | undefined): ClipPoint[][] {
  return (outlines || []).map(clipOutlinePoints).filter(p => p.length >= 3)
    .slice(0, CUTOUT_POLYGON_LIMIT)
}
export function clipPointInside(point: ClipPoint, outline: ClipPoint[]): boolean {
  let inside = false
  let prev = outline[outline.length - 1]
  for (const cur of outline) {
    if ((cur[1] > point[1]) !== (prev[1] > point[1]) &&
        point[0] < (prev[0] - cur[0]) * (point[1] - cur[1]) /
          (prev[1] - cur[1]) + cur[0]) inside = !inside
    prev = cur
  }
  return inside
}
export function clipKeepsPoint(point: ClipPoint, outline: ClipPoint[]): boolean {
  const points = clipOutlinePoints(outline)
  return points.length < 3 || clipPointInside(point, points)
}
export function cutoutPadding(declared: unknown, maxWorldScale: number): number {
  return typeof declared === 'number' && Number.isFinite(declared) && declared > 0
    ? declared * maxWorldScale : 0
}
export function cutoutDiscardsPoint(point: ClipPoint, outlines: ClipPoint[][],
                                    padding = 0, enabled = true): boolean {
  if (!enabled) return false
  for (const poly of cutoutPolygons(outlines)) {
    if (clipPointInside(point, poly)) return true
    if (!(padding > 0)) continue
    let prev = poly[poly.length - 1]
    for (const cur of poly) {
      const dx = cur[0] - prev[0], dz = cur[1] - prev[1]
      const t = Math.max(0, Math.min(1, ((point[0] - prev[0]) * dx +
        (point[1] - prev[1]) * dz) / Math.max(dx * dx + dz * dz, 1e-8)))
      const x = point[0] - (prev[0] + t * dx), z = point[1] - (prev[1] + t * dz)
      if (x * x + z * z <= padding * padding) return true
      prev = cur
    }
  }
  return false
}
