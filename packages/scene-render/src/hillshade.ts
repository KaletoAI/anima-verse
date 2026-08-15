/**
 * HILLSHADE — the world relief as a shading layer for 2D maps.
 *
 * The player map and the minimap draw the world from above, in colours that say
 * what the ground IS (meadow, water, road) and never how it LIES. A world with
 * hills therefore looks exactly like a flat one. This turns the same height
 * field the 3D client stands on (`worldHeight.ts`, § A16) into an RGBA overlay
 * that both 2D panels lay over their terrain colours: relief as light and
 * shadow, which is how every paper map has drawn it for a century.
 *
 * WHY THE MATH LIVES HERE and not in either panel: two panels drawing the same
 * landscape from the same field must draw the SAME light. The clip shader in
 * this package was written twice once, and the two copies had already drifted
 * when they were found. One routine, two callers — the callers only decide
 * WHERE the image lands on their canvas (their own map projection, their own
 * `drawImage` scaling), never what it says.
 *
 * IMPORT-FREE ON PURPOSE, like `worldHeight.ts`: no `three`, no DOM, no
 * `ImageData`. It answers a plain `Uint8ClampedArray` in RGBA order, and the
 * caller wraps it (`new ImageData(data, cols, rows)`) — which is also what lets
 * the smoke transpile this one file and run it on its own
 * (`client3d/scripts/smoke_hillshade.mjs`).
 *
 * ============================================================================
 * WHERE THE LIGHT STANDS — the one derivation this file rests on
 * ============================================================================
 * The world's axes are fixed by the contract (§ A1.8): **x runs EAST, z runs
 * SOUTH**, y is up. North is therefore −z and West is −x.
 *
 * `azimuthDeg` is the CARTOGRAPHIC azimuth, the one every hillshade is
 * specified in: measured FROM NORTH, CLOCKWISE over east — N = 0, E = 90,
 * S = 180, W = 270. That is NOT the figure compass of § A1.8 (0 = South,
 * 90 = East, 180 = North, 270 = West), which shares only the east; the two are
 * related by `A = (180 − facing) mod 360`, i.e. an offset AND a reversed sense.
 * Silently taking one for the other puts the light in the wrong quadrant and
 * every hill turns inside out, so the conversion is named here once and the
 * figure compass is not used below at all.
 *
 * The horizontal unit vector pointing TOWARDS the compass direction A is
 *
 *     d(A) = (sin A, −cos A)          in (x, z)
 *
 * which is checked on all four: A = 0 → (0, −1) = north ✓, A = 90 → (1, 0) =
 * east ✓, A = 180 → (0, 1) = south ✓, A = 270 → (−1, 0) = west ✓.
 *
 * The lamp STANDS in the direction the azimuth names ("light from the
 * north-west"), `altitudeDeg` above the horizon, so the vector from the ground
 * towards the light is
 *
 *     L = (cos alt · sin A,  sin alt,  −cos alt · cos A)
 *
 * and it is a unit vector by construction. The default 315° / 45° is the
 * cartographic standard, and it comes out as
 *
 *     L = (−½, √2⁄2, −½)  —  towards west and north, i.e. the north-west ✓
 *
 * ============================================================================
 * THE SURFACE NORMAL
 * ============================================================================
 * The ground is the surface y = h(x, z). Its tangents are (1, hx, 0) and
 * (0, hz, 1) with `hx = ∂h/∂x`, `hz = ∂h/∂z`; their cross product is
 * (hx, −1, hz), which points DOWN, so the upward normal is
 *
 *     N = (−hx, 1, −hz) / √(hx² + hz² + 1)
 *
 * The gradient is a CENTRAL DIFFERENCE over the neighbouring support points,
 * `(h[i+1] − h[i−1]) / (2·step)`, and one-sided at the borders,
 * `(h[i+1] − h[i]) / step` — the same shape in both cases, since the divisor is
 * simply the distance actually spanned. Central differences are what make the
 * shading symmetric: a one-sided gradient everywhere would shift every ridge
 * half a cell towards the sampling direction, and a hill would be lit off
 * centre.
 *
 * Note that the normal is per SUPPORT POINT, not per cell: the image carries
 * exactly the field's grid, and the consumer scales it with a smoothed
 * `drawImage`. Interpolating between point normals is precisely what that
 * smoothing does.
 *
 * ============================================================================
 * FROM LAMBERT TO PIXELS — and why the flat world stays untouched
 * ============================================================================
 * `lambert = max(N · L, 0)`: how much light the ground catches, zero once the
 * slope has turned away from the lamp (self-shadowed, which at 45° altitude
 * starts at a 45° slope facing away).
 *
 * LEVEL GROUND catches `N · L = sin alt` — call it the flat reference. The grey
 * is the RATIO to it, around neutral grey:
 *
 *     shade = min(½ · lambert / sin alt, 1)      →  grey = round(255 · shade)
 *
 * so level ground is exactly ½ → 128, ground catching twice the light of level
 * ground is white, ground in shadow is black. Nothing here is a tuned gain: the
 * only number is the neutral grey the overlay is centred on.
 *
 * THE ALPHA CARRIES THE SLOPE, and that is the requirement that shapes the
 * whole formula: a flat world must come out EXACTLY as it is drawn today.
 *
 *     alpha = maxAlpha · √(hx² + hz²) / √(hx² + hz² + 1)
 *
 * The fraction is the sine of the slope angle — equivalently the horizontal
 * length of the unit normal — so it is 0 on level ground, `maxAlpha` on a
 * vertical cliff, and monotone in between. A flat field therefore writes alpha
 * 0 into every pixel and changes not one colour underneath.
 *
 * AND THAT IS WHY THE GREY IS CENTRED rather than taken as `255 · lambert`
 * outright. Over gentle ground the shading signal `alpha · (grey − 128)` is
 * SECOND order in the slope (both factors vanish with it). Any grey that is off
 * neutral at zero slope — 255·sin 45° = 180, say — would add a term that is only
 * FIRST order, so every gentle hillside would brighten by the same amount
 * regardless of which way it faces, and the aspect, the whole point of a
 * hillshade, would drown under a haze. Centring removes that term instead of
 * damping it.
 *
 * `maxAlpha` stays low (0.35) for the same reason the panels want the layer at
 * all: the terrain colours have to stay readable through it.
 */
import type { WorldHeightField } from './worldHeight'

/** Where the lamp stands and how hard it paints. Every field is optional; the
 *  defaults are the cartographic standard, and no consumer overrides them
 *  today (the layer is always on, without a control — it is pure appearance). */
export interface HillshadeOpts {
  /** Cartographic azimuth in degrees: from north, clockwise. Default 315
   *  (north-west), the convention printed maps have used for a century —
   *  lighting from anywhere south makes hills read as hollows to most eyes. */
  azimuthDeg?: number
  /** Height of the lamp over the horizon in degrees. Default 45. Clamped into
   *  `[MIN_ALTITUDE_DEG, 90]`: at or below the horizon the flat reference
   *  `sin alt` collapses to zero and every slope saturates to black or white,
   *  which is no longer a shading of anything. */
  altitudeDeg?: number
  /** Opacity of the steepest slope, 0…1. Default 0.35 — enough to read the
   *  relief, little enough to keep the terrain colours underneath. */
  maxAlpha?: number
}

/** The finished overlay: `cols · rows` pixels in RGBA order, one per support
 *  point of the field, row `j` being the field's row `j` (so row 0 is the
 *  NORTHERNMOST line, smallest z). The consumer owns the projection — where
 *  this rectangle lands on its canvas comes from `origin_x`/`origin_z`/`step_m`
 *  and its own map transform, never from a second one invented here. */
export interface HillshadeImage {
  cols: number
  rows: number
  data: Uint8ClampedArray
}

const DEFAULT_AZIMUTH_DEG = 315
const DEFAULT_ALTITUDE_DEG = 45
const DEFAULT_MAX_ALPHA = 0.35
/** The lowest lamp that still shades: `sin alt` divides the grey, and below a
 *  degree the reference is so small that every visible slope clips to white. */
const MIN_ALTITUDE_DEG = 1
const DEG = Math.PI / 180

/** An option value, or the default when it is missing or not a number. */
function opt(value: number | undefined, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

/** A support point of a possibly ragged field. A missing or non-finite entry
 *  reads as 0 — the same reading `sampleWorldHeight` gives it, and the only one
 *  that keeps a single bad number from poisoning a whole neighbourhood of
 *  gradients (NaN would spread over three pixels per axis). */
function heightAt(heights: number[][], j: number, i: number): number {
  const v = heights[j]?.[i]
  return typeof v === 'number' && Number.isFinite(v) ? v : 0
}

/**
 * The relief of `field` as an RGBA shading layer — one pixel per support point.
 *
 * `null` for anything that carries no relief: no field, fewer than 2 × 2
 * support points (a single row or column has no gradient across it), or a
 * non-positive step. That is the empty world as the endpoint sends it, and the
 * consumers draw nothing at all then — not a transparent rectangle, nothing.
 *
 * The SHAPE COMES FROM THE ARRAY, never from the payload's `rows`/`cols`, for
 * the same reason `sampleWorldHeight` reads it that way: a field whose counts
 * disagree with its data is read as the data it actually carries.
 */
export function hillshadeImage(field: WorldHeightField | null | undefined,
                               opts?: HillshadeOpts): HillshadeImage | null {
  const heights = field?.heights
  if (!heights || heights.length < 2) return null
  const rows = heights.length
  const cols = heights[0]?.length || 0
  if (cols < 2) return null
  const step = field?.step_m ?? 0
  if (!(step > 0)) return null

  const azimuth = opt(opts?.azimuthDeg, DEFAULT_AZIMUTH_DEG) * DEG
  const altitudeDeg = Math.min(90, Math.max(MIN_ALTITUDE_DEG,
    opt(opts?.altitudeDeg, DEFAULT_ALTITUDE_DEG)))
  const altitude = altitudeDeg * DEG
  const maxAlpha = Math.min(1, Math.max(0, opt(opts?.maxAlpha, DEFAULT_MAX_ALPHA)))

  // The lamp, in world axes — the derivation in the header, written out.
  const cosAlt = Math.cos(altitude)
  const lx = cosAlt * Math.sin(azimuth)
  const ly = Math.sin(altitude)
  const lz = -cosAlt * Math.cos(azimuth)
  // What level ground catches: N = (0, 1, 0), so N · L is the lamp's height.
  // `altitudeDeg` is clamped above the horizon, so this is never 0.
  const flat = ly

  const data = new Uint8ClampedArray(cols * rows * 4)
  for (let j = 0; j < rows; j += 1) {
    // The neighbours of the row, and the distance they really span: two steps
    // inside the field, one at the northern and southern border.
    const jN = j > 0 ? j - 1 : j
    const jS = j < rows - 1 ? j + 1 : j
    const spanZ = (jS - jN) * step
    for (let i = 0; i < cols; i += 1) {
      const iW = i > 0 ? i - 1 : i
      const iE = i < cols - 1 ? i + 1 : i
      const spanX = (iE - iW) * step
      const hx = (heightAt(heights, j, iE) - heightAt(heights, j, iW)) / spanX
      const hz = (heightAt(heights, jS, i) - heightAt(heights, jN, i)) / spanZ

      const grad = Math.sqrt(hx * hx + hz * hz)
      const len = Math.sqrt(grad * grad + 1)
      // N = (−hx, 1, −hz)/len, dotted with the lamp.
      const lambert = (-hx * lx + ly - hz * lz) / len
      const lit = lambert > 0 ? lambert : 0
      const shade = Math.min(1, 0.5 * lit / flat)

      const grey = Math.round(255 * shade)
      // sin of the slope angle: the horizontal length of the unit normal.
      const alpha = Math.round(255 * maxAlpha * (grad / len))
      const p = (j * cols + i) * 4
      data[p] = grey
      data[p + 1] = grey
      data[p + 2] = grey
      data[p + 3] = alpha
    }
  }
  return { cols, rows, data }
}
