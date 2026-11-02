export type Segment = { url: string; startS: number; endS: number }
export type Root = { x: number; z: number; yaw: number }

export function segmentAt(segments: Segment[], t: number): { index: number; localS: number } | null {
  if (t < 0 || !Number.isFinite(t)) return null
  for (let index = 0; index < segments.length; index++) {
    const s = segments[index]
    const duration = Math.max(0, s.endS - s.startS)
    if (t < duration || (index === segments.length - 1 && t <= duration + 1e-9)) {
      return { index, localS: s.startS + Math.min(t, duration) }
    }
    t -= duration
  }
  return null
}

/** Includes the identity start and the final endpoint; yaw is in radians. */
export function chainRoots(ends: Root[]): Root[] {
  const roots: Root[] = [{ x: 0, z: 0, yaw: 0 }]
  for (const end of ends) {
    const p = roots[roots.length - 1]
    roots.push({ x: p.x + end.x * Math.cos(p.yaw) + end.z * Math.sin(p.yaw),
      z: p.z - end.x * Math.sin(p.yaw) + end.z * Math.cos(p.yaw), yaw: p.yaw + end.yaw })
  }
  return roots
}

/** The context around a conditioning pose; loops wrap, one-shots clamp. */
export function clipWindow(url: string, time: number, duration: number, loop: boolean, before: boolean): Segment[] {
  if (!(duration > 0)) return []
  const at = Math.min(duration, Math.max(0, time))
  if (!loop) return [{ url, startS: before ? Math.max(0, at - 1.5) : at,
    endS: before ? at : Math.min(duration, at + 1.5) }].filter((s) => s.endS > s.startS)
  let remaining = 1.5
  let cursor = before ? ((at - 1.5) % duration + duration) % duration : at % duration
  const out: Segment[] = []
  while (remaining > 1e-9) {
    const span = Math.min(remaining, duration - cursor)
    out.push({ url, startS: cursor, endS: cursor + span })
    remaining -= span; cursor = 0
  }
  return out
}
