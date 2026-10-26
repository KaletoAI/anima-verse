/** Pure hips position mapping; all lengths remain in target template units. */
export interface HipsTrackOptions {
  sourceRest: number
  median: number
  hipsPosScale: number
  /** Column-major inverse world matrix of the hips parent. */
  parentInverse: ArrayLike<number>
  rest: readonly number[]
  rootMotion: boolean
  rigKnown: boolean
}

/** Vertical bounce and optional horizontal travel, using the same scale healing.
 * The caller has established sourceRest > 1e-6 (a usable standing reference).
 */
export function mapHipsTrack(raw: ArrayLike<number>, times: ArrayLike<number>,
                             options: HipsTrackOptions): {
  values: Float32Array
  rootPath: { times: Float32Array; xz: Float32Array } | null
} {
  const { sourceRest, median, hipsPosScale, parentInverse: m, rest } = options
  const k = hipsPosScale / sourceRest
  const scaleFix = sourceRest > 1e-6 && median > sourceRest * 1.5 ? sourceRest / median : 1
  const values = new Float32Array(raw.length)
  for (let i = 0; i < raw.length; i += 3) {
    const bounce = (Math.abs(raw[i + 1]) * scaleFix - sourceRest) * k
    // Match Vector3.applyMatrix4, then subtract the matrix translation.
    const w = 1 / (m[3] * 0 + m[7] * bounce + m[11] * 0 + m[15])
    values[i] = (m[0] * 0 + m[4] * bounce + m[8] * 0 + m[12]) * w - m[12] + rest[0]
    values[i + 1] = (m[1] * 0 + m[5] * bounce + m[9] * 0 + m[13]) * w - m[13] + rest[1]
    values[i + 2] = (m[2] * 0 + m[6] * bounce + m[10] * 0 + m[14]) * w - m[14] + rest[2]
  }
  let rootPath: { times: Float32Array; xz: Float32Array } | null = null
  if (options.rootMotion && options.rigKnown) {
    const xz = new Float32Array(times.length * 2)
    const x0 = raw[0] * scaleFix
    const z0 = raw[2] * scaleFix
    for (let i = 0; i < times.length; i++) {
      xz[i * 2] = (raw[i * 3] * scaleFix - x0) * k
      xz[i * 2 + 1] = (raw[i * 3 + 2] * scaleFix - z0) * k
    }
    rootPath = { times: Float32Array.from(times), xz }
  }
  return { values, rootPath }
}
