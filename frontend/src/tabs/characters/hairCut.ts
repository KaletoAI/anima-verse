/**
 * hairCut — Ruling A71: the cut of HAAR hair cards, as the Hairstyles tab's Cut control previews it live.
 *
 * THE RULE is `app/core/hair_cut.py` (`cut_cards`, the fit). This file is its ONE port for the client;
 * `scripts/smoke_hair_cut_parity.py` holds the two together on synthetic cards with hand-derived cuts. Per card of
 * `R` rows of two rail vertices (left, right), root first, centreline = their mean, arc `a`, length `L`:
 *  1. `keep = min(L, CLAMP_P90 · p90(L of all cards), max_cm / 100, a(at))` — `a(at)` the arc where the centreline
 *     first drops below the landmark height (linear in its segment; 0 when the root lies below it) —, then at least
 *     `min(L, MIN_KEEP_M)`;
 *  2. the soft tip `E = min(ends_cm / 100 (Auto: ENDS_AUTO_M), ENDS_MAX_FRAC · keep)`;
 *  3. rows `0 … R−2` at arc `(keep − E)·r/(R − 2)`, the last at `keep`, each rail vertex interpolated along its rail;
 *  4. glTF `v = 1 − S_BODY·r/(R − 2)`, the last row `1 − S_END`.
 * The server cuts the float32 rails it stores (`garments.haar_cut_source`, the bytes this preview gets), in float64
 * — so does this port.
 */

export const CUT_VERSION = 1
export const S_BODY = 0.75
export const S_END = 0.95
export const ENDS_AUTO_M = 0.03
export const ENDS_MAX_FRAC = 0.25
export const CLAMP_P90 = 1.5
export const MIN_KEEP_M = 0.03

/** The landmarks "Ends at" offers, top down (`hair_cut.LANDMARKS`). */
export const CUT_LANDMARKS = ['chin', 'shoulder', 'shoulder_blades', 'mid_back', 'waist'] as const
export type CutLandmark = typeof CUT_LANDMARKS[number]

/** A hairstyle's `hair_cut` as stored (`hair_cut.normalise`): `{}` = automatic. */
export interface HairCut { max_cm?: number; at?: string; ends_cm?: number }

/** The uncut cards of the previewed fit (`GET …/garments/{item}/haar-cut-source`). */
export interface HaarCutSource {
  version: number
  cards: number
  rows: number
  /** base64 float32, card-major: row, left/right, xyz. */
  rails: string
  landmarks: Record<string, number>
  source_sha256: string
}

/** The Cut control's block of the HAAR panel (`garments.haar_cut_panel`). */
export interface HaarCutPanel {
  saved: HairCut
  built: HairCut | null
  landmarks: Record<string, number>
  source_url: string | null
  limits: { max_cm: [number, number]; ends_cm: [number, number] }
  auto_ends_cm: number
  at: string[]
}

/** The cut with only its set keys, rounded like the server (0.1 cm); `max_cm` and `at` exclude each other (`at`
 *  wins, as the control offers one of them). */
export function normaliseCut(cut: HairCut | null | undefined): HairCut {
  const out: HairCut = {}
  if (!cut) return out
  if (cut.at) out.at = cut.at
  else if (cut.max_cm != null && Number.isFinite(cut.max_cm)) out.max_cm = Math.round(cut.max_cm * 10) / 10
  if (cut.ends_cm != null && Number.isFinite(cut.ends_cm)) out.ends_cm = Math.round(cut.ends_cm * 10) / 10
  return out
}

/** Whether two cuts are the same setting. */
export function cutEqual(a: HairCut | null | undefined, b: HairCut | null | undefined): boolean {
  const x = normaliseCut(a), y = normaliseCut(b)
  return x.max_cm === y.max_cm && x.at === y.at && x.ends_cm === y.ends_cm
}

/** The body of `POST …/hair/cut` (with `item_id` added by the caller): the setting and nothing else — null =
 *  automatic for each key. Saving runs nothing; the fit reads due. */
export function cutPostBody(cut: HairCut | null | undefined): { max_cm: number | null; at: string | null
  ends_cm: number | null } {
  const c = normaliseCut(cut)
  return { max_cm: c.max_cm ?? null, at: c.at ?? null, ends_cm: c.ends_cm ?? null }
}

/** numpy's linear percentile 90. */
export function percentile90(values: ArrayLike<number>): number {
  const x = Array.from(values).sort((p, q) => p - q)
  if (!x.length) return 0
  const h = 0.9 * (x.length - 1)
  const lo = Math.floor(h)
  const hi = Math.min(lo + 1, x.length - 1)
  return x[lo] + (h - lo) * (x[hi] - x[lo])
}

/** The base64 rails as float32. */
export function decodeRails(b64: string): Float32Array {
  const bin = atob(b64)
  const bytes = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
  return new Float32Array(bytes.buffer, 0, Math.floor(bytes.length / 4))
}

export interface CutResult {
  /** cards · rows · 2 · 3, the cut rails. */
  positions: Float64Array
  /** cards · rows, glTF v of each row. */
  v: Float64Array
  keep: Float64Array
  clamp: number
  clamped: number
  shortened: number
}

/** `hair_cut.cut_cards` on `rails` (cards · rows · 2 · 3). */
export function cutCards(rails: ArrayLike<number>, cards: number, rows: number, cut: HairCut | null | undefined,
  heights: Record<string, number> | null | undefined): CutResult {
  const R = rows
  if (!(R >= 3) || rails.length !== cards * R * 6) throw new Error(`cutCards: ${rails.length} values for ${cards} × ${R}`)
  const c = normaliseCut(cut)
  const C = new Float64Array(cards * R * 3)
  const A = new Float64Array(cards * R)
  const L = new Float64Array(cards)
  for (let k = 0; k < cards; k++) {
    for (let r = 0; r < R; r++) {
      const b = (k * R + r) * 6
      for (let d = 0; d < 3; d++) C[(k * R + r) * 3 + d] = 0.5 * (Number(rails[b + d]) + Number(rails[b + 3 + d]))
      if (r > 0) {
        const p = (k * R + r) * 3, q = p - 3
        const dx = C[p] - C[q], dy = C[p + 1] - C[q + 1], dz = C[p + 2] - C[q + 2]
        A[k * R + r] = A[k * R + r - 1] + Math.sqrt(dx * dx + dy * dy + dz * dz)
      }
    }
    L[k] = A[k * R + R - 1]
  }
  const clamp = CLAMP_P90 * percentile90(L)
  const user = c.max_cm != null ? c.max_cm / 100 : Infinity
  const yAt = c.at != null && heights && Number.isFinite(heights[c.at]) ? heights[c.at] : null
  const ends = c.ends_cm != null ? c.ends_cm / 100 : ENDS_AUTO_M
  const positions = new Float64Array(cards * R * 6)
  const v = new Float64Array(cards * R)
  const keep = new Float64Array(cards)
  let clamped = 0, shortened = 0
  const body = R - 2
  for (let k = 0; k < cards; k++) {
    const length = L[k]
    let at = Infinity
    if (yAt !== null) {
      if (C[k * R * 3 + 1] < yAt) at = 0
      else {
        for (let i = 1; i < R; i++) {
          const yi = C[(k * R + i) * 3 + 1]
          if (yi < yAt) {
            const yp = C[(k * R + i - 1) * 3 + 1]
            const dy = yp - yi
            const t = dy > 0 ? (yp - yAt) / dy : 0
            at = A[k * R + i - 1] + t * (A[k * R + i] - A[k * R + i - 1])
            break
          }
        }
      }
    }
    let kk = Math.min(length, clamp, user, at)
    if (clamp < length && clamp <= Math.min(user, at)) clamped++
    kk = Math.max(kk, Math.min(length, MIN_KEEP_M))
    if (kk < length) shortened++
    const e = Math.min(ends, ENDS_MAX_FRAC * kk)
    for (let r = 0; r < R; r++) {
      const t = r <= body ? (kk - e) * r / body : kk
      let i = 0
      while (i < R - 2 && A[k * R + i + 1] < t) i++
      const span = A[k * R + i + 1] - A[k * R + i]
      let f = span > 0 ? (t - A[k * R + i]) / span : 0
      f = Math.min(Math.max(f, 0), 1)
      const a0 = (k * R + i) * 6, a1 = a0 + 6, o = (k * R + r) * 6
      for (let j = 0; j < 6; j++) {
        const p0 = Number(rails[a0 + j])
        positions[o + j] = p0 + f * (Number(rails[a1 + j]) - p0)
      }
      v[k * R + r] = 1 - (r <= body ? S_BODY * r / body : S_END)
    }
    keep[k] = kk
  }
  return { positions, v, keep, clamp, clamped, shortened }
}

/** The vertex override of the preview (`Model3DViewer` `meshAdjust.cut`): the first `cards · rows · 2` vertices of
 *  the hair primitive get these positions and uv.y — the HAAR layout (`hair_strands.haar_layout`): card k is
 *  vertices `[2R k, 2R (k + 1))`, row-major, left then right. */
export function cutOverride(source: HaarCutSource, rails: Float32Array, cut: HairCut | null | undefined):
  { positions: Float32Array; v: Float32Array; keep: Float64Array } {
  const res = cutCards(rails, source.cards, source.rows, cut, source.landmarks)
  const v = new Float32Array(source.cards * source.rows * 2)
  for (let i = 0; i < source.cards * source.rows; i++) { v[2 * i] = res.v[i]; v[2 * i + 1] = res.v[i] }
  return { positions: Float32Array.from(res.positions), v, keep: res.keep }
}

const RULER_COLOUR = '#c9d1d9'

/** The reference the Cut preview draws beside the hair (checklist: a measure needs a reference): for "Ends at" a
 *  level line behind the hair at the landmark's height; for a max length a scale with a tick every 5 cm (longer every
 *  10), hanging from the cards' median root height beside them — the length runs along each strand, so a strand
 *  that falls straight ends at the scale's foot. Empty for an automatic cut. */
export function cutRuler(source: HaarCutSource, rails: Float32Array, cut: HairCut | null | undefined):
  Array<{ points: [number, number, number][]; color: string }> {
  const c = normaliseCut(cut)
  const R = source.rows
  let minX = Infinity, maxX = -Infinity, minZ = Infinity
  const rootY: number[] = []
  for (let k = 0; k < source.cards; k++) {
    for (let r = 0; r < R; r++) {
      for (let s = 0; s < 2; s++) {
        const o = ((k * R + r) * 2 + s) * 3
        minX = Math.min(minX, rails[o]); maxX = Math.max(maxX, rails[o]); minZ = Math.min(minZ, rails[o + 2])
      }
    }
    const o = k * R * 6
    rootY.push(0.5 * (rails[o + 1] + rails[o + 4]))
  }
  if (!rootY.length) return []
  const z = minZ - 0.02
  if (c.at) {
    const y = source.landmarks?.[c.at]
    if (y == null) return []
    return [{ points: [[minX - 0.04, y, z], [maxX + 0.04, y, z]], color: RULER_COLOUR }]
  }
  if (c.max_cm == null) return []
  rootY.sort((p, q) => p - q)
  const y0 = rootY[Math.floor(rootY.length / 2)]
  const x = maxX + 0.04
  const lines: Array<{ points: [number, number, number][]; color: string }> = [
    { points: [[x, y0, z], [x, y0 - c.max_cm / 100, z]], color: RULER_COLOUR }]
  for (let cm = 0; cm <= c.max_cm + 1e-6; cm += 5) {
    const len = cm % 10 === 0 ? 0.02 : 0.01
    lines.push({ points: [[x, y0 - cm / 100, z], [x - len, y0 - cm / 100, z]], color: RULER_COLOUR })
  }
  const foot = y0 - c.max_cm / 100
  lines.push({ points: [[x - 0.03, foot, z], [x + 0.01, foot, z]], color: '#f0883e' })
  return lines
}
