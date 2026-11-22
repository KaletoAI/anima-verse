/**
 * THE CHANNEL READOUT: how far an entering part goes into a channel and how much it stretches the channel's width,
 * per (receiving figure, channel, entering figure) and frame. ONE pure function for both renderers — the admin's
 * Poses preview prints it, client3d publishes it as live values (`FigureRuntime.channelReadouts`). Values are raw per
 * frame (nothing smoothed); a consumer may smooth.
 *
 * Inputs: the channel as the receiving figure binds it this frame (`ChannelNow`: O, u, D, R — R is the REST radius,
 * the declared one scaled with the figure, never the radius an engaging part grew it to, Ruling A161), the entering
 * chain's links as world segments a → b with the radius r the opening widens the surface to (`channelOpening.ts`:
 * the link's surface radius × girth × the engagement weight w — at w = 1 the part's own surface radius), and the
 * depth scale k its guidance applied (`depthScale`, blended by w; 1 = none). s(P) = (P − O)·u (`channelCoords`).
 *
 * - `insertionM` = how far the part's surface front reaches along u past the opening plane:
 *   max over the links of (max(s(a), s(b)) + r), clamped to ≥ 0 (a link's capsule front is its deeper end plus r).
 * - `insertionOfDepth` = insertionM / D (1 = the part's front at the bottom; above 1 = past it).
 * - `insertionOfLength` = the share of the chain's CURRENT length (Σ |b − a|, after any compression) that lies at
 *   s ≥ 0: per link the fraction of the segment with s ≥ 0 (linear in s), weighted by its length.
 * - `compressK` = k as applied (1 = none).
 * - `stretchM` = how much wider than its rest radius the channel is held open over the inserted part:
 *   max over the links that reach s ≥ 0 of max(0, r − R); `stretchAtM` = the s where that maximum starts (the
 *   shallowest inside point of the first link with the largest excess, max(0, min(s(a), s(b)))), 0 without a stretch.
 *   `stretchOpeningM` = the same excess over the links that cross the opening plane (min s ≤ 0 ≤ max s) — the
 *   stretch AT the opening; 0 when no link crosses it (the part is all in front of it or all inside).
 *   `stretchDiameterM` = 2 · stretchM, `stretchRatio` = stretchM / R.
 * - `partRadiusM` = the largest r over the links that reach s ≥ 0 (the same links as the stretch), 0 when none — the
 *   part's own width inside, so a part thinner than R ("not filled") is measurable too.
 *   The opening itself holds the wall at r + `OPENING_MARGIN_M` from the part's axis; the readout measures the part's
 *   surface against R, without that skin margin.
 *
 * Null without segments.
 */
import type { Vec3 } from './collision'

export interface ChannelReadoutValues {
  /** The channel's depth D and rest radius R this frame (metres). */
  depthM: number
  restRadiusM: number
  insertionM: number
  insertionOfDepth: number
  insertionOfLength: number
  compressK: number
  stretchM: number
  stretchDiameterM: number
  stretchRatio: number
  stretchAtM: number
  stretchOpeningM: number
  partRadiusM: number
}

/** One readout with its owners: `receiver` holds the channel, `entering` is the figure whose chain is in it, `w` the
 *  engagement weight. */
export interface ChannelReadout extends ChannelReadoutValues {
  receiver: string
  channel: string
  entering: string
  w: number
}

/** The readout of one entering chain in `ch` (module docstring). Null without segments. */
export function channelReadout(ch: { o: Vec3; u: Vec3; depth: number; r: number },
  segments: readonly { a: Vec3; b: Vec3; r: number }[], k = 1): ChannelReadoutValues | null {
  if (!segments.length) return null
  const sOf = (p: Vec3) => (p[0] - ch.o[0]) * ch.u[0] + (p[1] - ch.o[1]) * ch.u[1] + (p[2] - ch.o[2]) * ch.u[2]
  const R = ch.r
  let front = 0, total = 0, inside = 0
  let stretch = 0, stretchAt = 0, opening = 0, partR = 0
  for (const seg of segments) {
    const sa = sOf(seg.a), sb = sOf(seg.b)
    const lo = Math.min(sa, sb), hi = Math.max(sa, sb)
    const r = Math.max(0, seg.r)
    front = Math.max(front, hi + r)
    const length = Math.hypot(seg.b[0] - seg.a[0], seg.b[1] - seg.a[1], seg.b[2] - seg.a[2])
    total += length
    if (hi >= 0) {
      inside += lo >= 0 ? length : hi - lo > 1e-12 ? length * hi / (hi - lo) : length
      partR = Math.max(partR, r)
      const excess = Math.max(0, r - R)
      if (excess > stretch) { stretch = excess; stretchAt = Math.max(0, lo) }
      if (lo <= 0) opening = Math.max(opening, excess)
    }
  }
  const insertion = Math.max(0, front)
  return {
    depthM: ch.depth, restRadiusM: R,
    insertionM: insertion,
    insertionOfDepth: ch.depth > 0 ? insertion / ch.depth : 0,
    insertionOfLength: total > 0 ? inside / total : 0,
    compressK: k,
    stretchM: stretch, stretchDiameterM: 2 * stretch, stretchRatio: R > 0 ? stretch / R : 0,
    stretchAtM: stretchAt, stretchOpeningM: opening, partRadiusM: partR,
  }
}

/** The key of a readout: `"<receiver>|<channel>|<entering>"` (a channel id may hold a colon, never a bar). */
export function channelReadoutKey(r: { receiver: string; channel: string; entering: string }): string {
  return `${r.receiver}|${r.channel}|${r.entering}`
}

/** The maxima of readouts over a span (one clip loop): per key the largest insertion, insertion share of D and of
 *  the part, stretch (and its ratio) and the SMALLEST k. `fold` adds one frame's readouts. */
export interface ChannelReadoutMax { insertionM: number; insertionOfDepth: number; insertionOfLength: number
  stretchM: number; stretchRatio: number; compressK: number }
export function foldReadoutMax(into: Map<string, ChannelReadoutMax>, readouts: readonly ChannelReadout[]): void {
  for (const r of readouts) {
    const key = channelReadoutKey(r)
    const m = into.get(key)
    if (!m) {
      into.set(key, { insertionM: r.insertionM, insertionOfDepth: r.insertionOfDepth,
        insertionOfLength: r.insertionOfLength, stretchM: r.stretchM, stretchRatio: r.stretchRatio, compressK: r.compressK })
      continue
    }
    m.insertionM = Math.max(m.insertionM, r.insertionM)
    m.insertionOfDepth = Math.max(m.insertionOfDepth, r.insertionOfDepth)
    m.insertionOfLength = Math.max(m.insertionOfLength, r.insertionOfLength)
    m.stretchM = Math.max(m.stretchM, r.stretchM)
    m.stretchRatio = Math.max(m.stretchRatio, r.stretchRatio)
    m.compressK = Math.min(m.compressK, r.compressK)
  }
}
