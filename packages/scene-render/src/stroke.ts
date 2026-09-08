/**
 * stroke — how a DRAWN LINE is bent before it is widened, for both renderers.
 *
 * The map editor's line tool stores a RECIPE (`meta.stroke`: the clicked
 * points, a width, a style) and regenerates the area's polygon from it. The
 * 3D client never needed that line until the stroke grew things ALONG it
 * (`meta.stroke.along`, § A9): a lamp row has to follow the very centre line
 * the ribbon was built from, wavy bends included — so the decoration moved
 * here from `frontend/src/tabs/map/mapMath.ts` (2026-09-09, verbatim), and
 * `mapMath` re-exports it. `decorateStroke` is deterministic (the seed is the
 * clicked points), which is what lets two renderers agree on one line.
 *
 * The only import is `seededRandom` from `./scatter`, so
 * `scripts/smoke_stroke_styles.mjs` bundles this file with esbuild exactly as
 * it bundled mapMath before.
 */
import { seededRandom } from './scatter'

/** Two stroke points closer than this are the same click, not a segment. */
const STROKE_EPS = 1e-9

/** Metres are stored with 2 decimals (server side), so the line rounds too.
 *  The `+ 0` normalizes −0 to 0 — otherwise a mirrored side produces "-0",
 *  which `===` calls equal but JSON writes out as a different number. */
const round2 = (v: number): number => Math.round(v * 100) / 100 + 0

/** How a centre line is BENT before it is widened. `straight` is the line as
 *  clicked; the other two hang deflections off it, so a river bank or a forest
 *  edge stops looking like a ruler. */
export type StrokeStyle = 'straight' | 'jagged' | 'wavy'

/** The styles in the order the toolbar offers them — straight first, because
 *  that is what the tool did before and still does by default. */
export const STROKE_STYLES: readonly StrokeStyle[] = ['straight', 'jagged', 'wavy']

/** Is this one of the three? Anything else — a foreign `meta.stroke`, a client
 *  that knows a style this one does not — is read as the straight line the
 *  polygon was generated from, never guessed at. */
export function isStrokeStyle(value: unknown): value is StrokeStyle {
  return typeof value === 'string'
    && (STROKE_STYLES as readonly string[]).includes(value)
}

/** What a line's decoration is set to: the toolbar's setting for the next
 *  line, the stored recipe's for one that already exists. */
export interface StrokeDeco {
  style: StrokeStyle
  spacingM: number
  amplitudeM: number
}

/**
 * Points a DECORATED centre line may end up with.
 *
 * The budget is the server's polygon limit (`app/models/terrain.MAX_POINTS`),
 * counted where it is actually spent: a mitred ribbon is `2n` points wide
 * (`strokeToPolygon`), so 1024 centre points make a 2048-point outline and the
 * server takes `2·1024 + 2`. Cap the centre line at 2048 instead and every
 * dense line would generate a 4096-point polygon and be refused on save, which
 * is not a cap but a wall.
 *
 * 1024 is the number a KILOMETRE of `wavy` river needs: the curve is sampled
 * every 3 m at the widest (`WAVE_SAMPLE_MAX_M`), so 1000 m is 335 points, and
 * the budget still carries three of those before it has to coarsen. The old
 * 120 was a budget for four samples per wave — the very zigzag this sampling
 * replaces.
 *
 * It is a bound on the MITRED case, and deliberately only that: deflections
 * sharp enough to bevel add two points per join, and such a line overruns the
 * limit the way any hairpin chain already does — `MapTab.strokePolygon`
 * refuses it with the count in the message.
 */
export const MAX_DECORATED_POINTS = 1024

/** The smallest deflection, as a fraction of the amplitude. Deflections have
 *  random size (that is what keeps them from reading as a pattern), but one of
 *  nearly zero is a kink nobody drew — the field says how far the line swings,
 *  not how far its biggest swing goes. */
const DEFLECTION_MIN_FACTOR = 0.4

/** Deflection spacings per full wave of the `wavy` style: the sine's period is
 *  `4 · spacing`, which keeps ONE spacing field meaning the same thing in both
 *  styles — how far apart the deflections sit. */
const WAVE_SPACINGS_PER_PERIOD = 4

/** How finely `wavy` SAMPLES that sine: at least this many samples per
 *  deflection spacing, i.e. `4 · 3 = 12` per period. Below about a dozen a
 *  sine joined by straight segments stops reading as a curve and starts
 *  reading as a chain of corners — which is exactly what four samples per
 *  period (the rule until 2026-08-23) produced. */
const WAVE_SAMPLES_PER_SPACING = 3

/** …and never further apart than this, in metres, however wide the spacing is
 *  set. A 100 m spacing would otherwise sample its own curve every 33 m, and a
 *  33 m straight segment is a visible edge at any zoom the line is drawn at. */
const WAVE_SAMPLE_MAX_M = 3

/** How far to either side of a CLICKED CORNER the side normal is blended from
 *  the incoming segment's to the outgoing one's, as a fraction of the spacing.
 *  Without it the normal flips instantly at every corner and the deflections
 *  on the two sides of it point in different directions — a snap in the middle
 *  of a wave. Half a spacing is the widest window that cannot reach the next
 *  deflection. */
const CORNER_BLEND_SPACINGS = 0.5

/** Cosine ease over `[0, 1]`: 0 at 0, 1 at 1, and FLAT at both ends. Used for
 *  everything the decoration interpolates — the amplitude between two
 *  deflections and the side normal across a corner — because the flat ends are
 *  what make the joins kink-free: the value arrives at an anchor with slope 0
 *  from both sides, so the anchor itself is never a corner. */
const ease = (t: number): number => (1 - Math.cos(Math.PI * t)) / 2

/** The seed of one decoration — the clicked line itself, so the same stroke
 *  drawn twice gets the same spikes, and no two lines share a pattern. Fed to
 *  `seededRandom` (@anima/scene-render), the ONE PRNG of this repo. */
export function strokeSeed(points: Array<[number, number]>): string {
  let s = 'terrain:stroke'
  for (const p of points) s += `:${p?.[0]},${p?.[1]}`
  return s
}

/** A decorated centre line, plus what had to be given up to fit the budget. */
export interface DecoratedStroke {
  /** The line as `strokeToPolygon` should read it: the clicked points with the
   *  deflections woven in, in walking order. */
  points: Array<[number, number]>
  /** The spacing actually used — larger than the one asked for when the cap
   *  below thinned the deflections out. */
  spacingM: number
  /** `MAX_DECORATED_POINTS` raised the spacing. The toolbar says so; silently
   *  drawing something coarser than the field claims would be a lie. */
  capped: boolean
}

/**
 * Bend a clicked centre line — the step BEFORE `strokeToPolygon`.
 *
 * A pure function of its arguments: the same line, style and numbers give the
 * same points, always, in every client. The randomness is seeded from the
 * clicked points themselves (`strokeSeed`), so redrawing the same line gives
 * the same river and dragging one of its points reshapes the whole pattern —
 * which is what dragging a point of a hand-drawn line looks like anyway.
 *
 * DEFLECTIONS sit at arc length `spacing/2`, `3·spacing/2`, … along the line,
 * each with a height drawn at random from `[0.4·amplitude, amplitude]`. They
 * are pushed sideways along the unit normal `(dz, −dx)` — side A of
 * `strokeToPolygon`, the same convention, so nothing here invents a second
 * idea of "sideways". What the two styles make of them:
 *
 *   jagged — one point PER DEFLECTION, on alternating sides: a triangle wave,
 *            the clicked points woven in between.
 *   wavy   — a CONTINUOUS CURVE, sampled far more finely than the deflections
 *            sit. The offset at arc length `d` is
 *
 *              offset(d) = A(d) · sin(phase + 2π·d / (4·spacing))
 *
 *            i.e. a sine of period `4·spacing` (`WAVE_SPACINGS_PER_PERIOD`)
 *            whose amplitude `A(d)` is the deflection heights, cosine-eased
 *            from one to the next and pinned to 0 at both clicked ends — never
 *            a fresh random number per sample, which would be noise and not a
 *            river. It is SAMPLED every `min(spacing/3, 3 m)` of arc length,
 *            so a period carries at least 12 points and reads as a curve.
 *
 * The phase is drawn FIRST and in both styles, so switching between them
 * leaves the heights alone and only changes the shape they are hung on.
 *
 * At a CLICKED CORNER the side normal does not snap from one segment's to the
 * next's. Over `±spacing/2` of arc length around the corner (`half`, clipped
 * to half of either adjoining segment so two corners can never fight over the
 * same stretch) it is the cosine-eased mix `normalize((1−b)·n1 + b·n2)`, which
 * at the corner itself — `b = 0.5` — is exactly `(n1+n2)/|n1+n2|`. A corner
 * therefore BENDS the decoration instead of flipping it inside out.
 *
 * The clicked points all survive for `jagged`, in order — the decoration is
 * woven between them. For `wavy` each of them is a SAMPLE like any other: it
 * keeps its arc position (so the corner is drawn where it was clicked) but is
 * offset like its neighbours, because a point dropped back onto the centre
 * line in the middle of a wave is the one kink the sampling exists to avoid.
 * The two ENDS are the exception in both styles: `A(d)` is 0 there, so they
 * stay exactly where they were clicked.
 *
 * Left unchanged, and returned as the very array it was given: the `straight`
 * style, a style this build does not know, a spacing or amplitude that is not
 * a positive number, a line with fewer than two distinct points or a
 * non-finite coordinate, and a line of zero length. A decoration that cannot
 * be computed is no decoration, never half of one.
 *
 * Verification cases (hand-derived, § B5a — arithmetic, not screenshots),
 * `A` = amplitude, `m_i` = the random height of the i-th deflection:
 *
 *   [(0,0),(100,0)], jagged, spacing 10, A 2: length 100, deflections at
 *     5, 15, …, 95 -> 10 of them, 12 points in all. Segment direction (1,0)
 *     has normal (0,−1), so side A is NEGATIVE z and the sides alternate from
 *     there:
 *     [(0,0),(5,−m0),(15,m1),(25,−m2),…,(95,m9),(100,0)] with 0.8 <= m_i <= 2
 *   the same line, WAVY: sampled every min(10/3, 3) = 3 m, so the arc
 *     positions are 0, 3, …, 99 (34 of them) plus the end 100 -> 35 points,
 *     and since the normal is (0,−1) the x of each point IS its arc position
 *     and the whole offset lands in z: z(d) = −A(d)·sin(phase + π·d/20).
 *     z(0) = z(100) = 0 (the ends are pinned), |z| <= 2 throughout, and the
 *     amplitude anchors are m_0 at 5, m_1 at 15, …, m_9 at 95.
 *     Smoothness, from |offset'| <= max|A'| + max|A|·2π/(4·spacing): the
 *     steepest cosine ease is the end ramp (height <= 2 over spacing/2 = 5 m,
 *     so <= (π/2)·2/5 = 0.6283) and the sine term is <= 2·π/20 = 0.3142,
 *     so |offset'| <= 3πA/(2·spacing) = 0.9425. Every sample-to-sample
 *     direction is therefore within atan(0.9425) = 43.30° of the line and the
 *     TURN at any sample is at most 86.60°; between the first and last anchor,
 *     where the ease spans 10 m and at most |A − 0.4A| = 1.2, the same sum is
 *     0.1885 + 0.3142 = 0.5027 -> 26.69°, turn at most 53.39°.
 *   [(0,0),(10,0),(10,10)], jagged, spacing 10, A 2: length 20, deflections at
 *     5 (on the first segment, normal (0,−1)) and 15 (on the second, direction
 *     (0,1), normal (1,0)) -> [(0,0),(5,−m0),(10,0),(10−m1,5),(10,10)]: the
 *     clicked corner (10,0) is still in there, between the two. The corner
 *     blend does NOT reach either deflection — the window is half-open and
 *     both sit exactly spacing/2 = 5 away from the corner — so this case is
 *     the same line it was before the blend existed.
 *   [(0,0),(7,0),(7,7)], jagged, spacing 10, A 2: length 14, ONE deflection at
 *     5, and now the blend does bite: half = min(5, 3.5, 3.5) = 3.5, the
 *     window around the corner at 7 is [3.5, 10.5], u = (5−7+3.5)/7
 *     = 0.214285…, b = ease(u) = 0.1090843, n1 = (0,−1), n2 = (1,0)
 *     -> mix (0.1090843,−0.8909157), length 0.8975691,
 *     normal (0.1215330,−0.9925874) -> (5 + 0.1215330·m0, −0.9925874·m0).
 *   [(0,0),(10,0),(10,10)], WAVY, spacing 10, A 2: samples at 0, 3, 6, 9, the
 *     clicked corner at 10, then 12, 15, 18 and the end 20 -> 9 points. At the
 *     corner b = ease(0.5) = 0.5, so the normal is normalize((0,−1)+(1,0))
 *     = (0.707107,−0.707107) and A(10) = (m_0+m_1)/2 (cosine ease, halfway
 *     between the anchors at 5 and 15).
 *   [(0,0),(1000,0)], jagged, spacing 2, A 2: 500 deflections would be 502
 *     points, which fits the 1024-point budget: 502 points, `capped` false.
 *   [(0,0),(1000,0)], WAVY, spacing 10, A 2: room is 1024 − 2 = 1022, so a
 *     sample every 1000/1022 = 0.98 m would still fit and the asked-for 3 m
 *     stands: arc positions 0, 3, …, 999 (334) plus the end -> 335 points,
 *     `capped` false. Under the old 120-point budget the same line had to be
 *     sampled every 8.47 m — 4.7 samples per period, the zigzag again.
 *   [(0,0),(100,0)], jagged, spacing 10, A 0 -> the input array itself, since
 *     a deflection of no height is no deflection.
 *   [(0,0),(100,0)], straight, spacing 10, A 2 -> the input array itself.
 */
export function decorateStroke(points: Array<[number, number]>,
  style: StrokeStyle, spacingM: number, amplitudeM: number,
  seed: string = strokeSeed(points)): DecoratedStroke {
  const plain: DecoratedStroke = { points, spacingM, capped: false }
  if (style !== 'jagged' && style !== 'wavy') return plain
  if (!Number.isFinite(spacingM) || spacingM <= 0) return plain
  if (!Number.isFinite(amplitudeM) || amplitudeM <= 0) return plain

  // 1. the line as the ribbon builder will read it: finite, no repeated click.
  const line: Array<[number, number]> = []
  for (const p of points) {
    if (!p || p.length < 2) return plain
    const [x, z] = p
    if (!Number.isFinite(x) || !Number.isFinite(z)) return plain
    const prev = line[line.length - 1]
    if (prev && Math.abs(prev[0] - x) < STROKE_EPS
      && Math.abs(prev[1] - z) < STROKE_EPS) continue
    line.push([x, z])
  }
  if (line.length < 2) return plain

  // 2. where each clicked point sits along the line, and how long it is.
  const cum = [0]
  for (let i = 1; i < line.length; i++) {
    cum.push(cum[i - 1] + Math.hypot(line[i][0] - line[i - 1][0],
      line[i][1] - line[i - 1][1]))
  }
  const total = cum[cum.length - 1]
  if (!(total > 0)) return plain

  // 3. the per-segment side-A normal (dz, −dx), unit length — the very
  //    convention `strokeToPolygon` offsets by.
  const nrm: Array<[number, number]> = []
  for (let i = 1; i < line.length; i++) {
    const len = cum[i] - cum[i - 1]
    nrm.push([(line[i][1] - line[i - 1][1]) / len,
      -(line[i][0] - line[i - 1][0]) / len])
  }

  // 4. the budget (see MAX_DECORATED_POINTS): the clicked points are already
  //    spent, the rest is what the decoration may take. Asking for more thins
  //    it out — the line still gets its style, at the density that fits, and
  //    `capped` says the field's number is not the one drawn.
  //    `jagged` spends one point per deflection, so its budget IS the spacing.
  //    `wavy` spends one per SAMPLE, so the sample step is what has to give;
  //    the spacing follows it up rather than the samples down, because fewer
  //    samples per period is the zigzag this style exists to avoid.
  const room = MAX_DECORATED_POINTS - line.length
  if (room <= 0) return { points: line, spacingM, capped: true }
  let spacing = spacingM
  let capped = false
  let step = 0
  if (style === 'wavy') {
    step = Math.min(spacing / WAVE_SAMPLES_PER_SPACING, WAVE_SAMPLE_MAX_M)
    if (step < total / room) {
      step = total / room
      spacing = Math.max(spacing, step * WAVE_SAMPLES_PER_SPACING)
      capped = true
    }
  } else if (spacing < total / room) {
    spacing = total / room
    capped = true
  }

  // 5. the deflections: where they sit and how high they are. The phase is
  //    drawn first and the heights in one run, so both styles read the same
  //    stream and switching between them keeps the heights.
  const rnd = seededRandom(seed)
  const phase = rnd() * Math.PI * 2
  const anchorD: number[] = []
  const anchorH: number[] = []
  for (let d = spacing / 2; d < total - STROKE_EPS; d += spacing) {
    anchorD.push(d)
    anchorH.push(amplitudeM
      * (DEFLECTION_MIN_FACTOR + (1 - DEFLECTION_MIN_FACTOR) * rnd()))
  }

  /** The unit side normal at arc length `d`, which sits on segment `seg`
   *  (1-based, as `cum` is indexed) — blended across a clicked corner instead
   *  of snapping at it. The window is clipped to half of either adjoining
   *  segment, so the windows of two corners never overlap and only one of the
   *  two corners bounding a segment can ever claim a sample. */
  const normalAt = (d: number, seg: number): [number, number] => {
    for (const c of [seg - 1, seg]) {
      if (c < 1 || c > line.length - 2) continue
      const dd = d - cum[c]
      const half = Math.min(spacing * CORNER_BLEND_SPACINGS,
        (cum[c] - cum[c - 1]) / 2, (cum[c + 1] - cum[c]) / 2)
      if (!(half > STROKE_EPS) || Math.abs(dd) >= half) continue
      const b = ease((dd + half) / (2 * half))
      const mx = (1 - b) * nrm[c - 1][0] + b * nrm[c][0]
      const mz = (1 - b) * nrm[c - 1][1] + b * nrm[c][1]
      const ml = Math.hypot(mx, mz)
      // A hairpin's two normals cancel; there is no "between" to blend to, so
      // the segment's own normal stands (the bevel handles the join anyway).
      if (ml > STROKE_EPS) return [mx / ml, mz / ml]
    }
    return nrm[seg - 1]
  }

  /** The offset's amplitude at arc length `d`: the deflection heights, cosine-
   *  eased into each other and pinned to 0 at both clicked ends, so the curve
   *  leaves and re-enters the line tangentially. `envI` walks forward with the
   *  samples — they are generated in increasing `d`. */
  const envD = [0, ...anchorD, total]
  const envH = [0, ...anchorH, 0]
  let envI = 0
  const envelope = (d: number): number => {
    while (envI + 2 < envD.length && envD[envI + 1] < d) envI++
    const span = envD[envI + 1] - envD[envI]
    if (!(span > 0)) return envH[envI + 1]
    const t = Math.min(1, Math.max(0, (d - envD[envI]) / span))
    return envH[envI] + (envH[envI + 1] - envH[envI]) * ease(t)
  }

  // 6. the arc positions to put a point at, in walking order, each tagged with
  //    the deflection it belongs to — or −1 for a clicked point, which is
  //    reproduced as clicked and not computed. `jagged` puts one point per
  //    deflection and weaves the clicked points in between; `wavy` samples the
  //    curve on a fixed step, with the clicked corners folded into the same
  //    sorted list so no arc position is visited twice.
  const ds: number[] = []
  const tag: number[] = []
  const CLICK = -1
  if (style === 'jagged') {
    let walk = 1
    for (let i = 0; i < anchorD.length; i++) {
      while (walk < line.length - 1 && cum[walk] <= anchorD[i]) {
        ds.push(cum[walk]); tag.push(CLICK); walk++
      }
      ds.push(anchorD[i]); tag.push(i)
    }
    while (walk < line.length - 1) { ds.push(cum[walk]); tag.push(CLICK); walk++ }
  } else {
    let walk = 1
    const push = (d: number) => {
      if (ds.length > 0 && d - ds[ds.length - 1] <= STROKE_EPS) return
      ds.push(d); tag.push(0)
    }
    for (let k = 0; k * step < total - STROKE_EPS; k++) {
      const d = k * step
      while (walk <= line.length - 2 && cum[walk] < d - STROKE_EPS) {
        push(cum[walk]); walk++
      }
      push(d)
    }
    while (walk <= line.length - 2) { push(cum[walk]); walk++ }
  }

  // 7. and turn them into points. The two clicked ENDS bracket the walk —
  //    `wavy` would place them there anyway (the envelope is 0 at both), and
  //    `jagged` has no deflection outside them to bend.
  const out: Array<[number, number]> = [line[0]]
  let seg = 1
  for (let k = 0; k < ds.length; k++) {
    const d = ds[k]
    while (seg < line.length - 1
      && (style === 'jagged' ? cum[seg] <= d : cum[seg] < d - STROKE_EPS)) seg++
    if (tag[k] === CLICK) { out.push(line[seg - 1]); continue }
    if (d <= STROKE_EPS) continue           // the start cap, already standing
    const [ax, az] = line[seg - 1]
    const [bx, bz] = line[seg]
    const f = (d - cum[seg - 1]) / (cum[seg] - cum[seg - 1])
    const [nx, nz] = normalAt(d, seg)
    const off = style === 'jagged'
      ? anchorH[tag[k]] * (tag[k] % 2 === 0 ? 1 : -1)
      : envelope(d) * Math.sin(phase
        + (2 * Math.PI * d) / (WAVE_SPACINGS_PER_PERIOD * spacing))
    out.push([round2(ax + f * (bx - ax) + off * nx),
      round2(az + f * (bz - az) + off * nz)])
  }
  out.push(line[line.length - 1])
  return { points: out, spacingM: spacing, capped }
}
