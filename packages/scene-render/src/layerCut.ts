/**
 * The LAYER CUT of the ground — the ONE reading of "which material is here",
 * for both renderers and for the rules that ask about it (plan-ein-boden.md
 * § G3, contract addendum "Ein Boden — E3").
 *
 * WHAT IT REPLACES. Until E3 a painted area was its own transparent mesh lying
 * a fraction of a millimetre over the terrain, kept apart from its neighbours by
 * a `renderOrder` ladder, a `polygonOffset` ladder and a hairline y ladder, and
 * blended into them by an alpha fringe. Three depth crutches and a sorting
 * problem for something that is not a stack at all: at any one point of the
 * ground exactly ONE material is on top. Here that is what is drawn — the
 * terrain is one surface, and the material is CUT into it per texel.
 *
 * THE SERVER BAKES TWO MASKS (`app/core/terrain_layers.py`) and this file is
 * how they are read:
 *
 *  - the **id mask**, one metre per texel, two bytes: the PAIR (A, B) of layer
 *    indices at the nearest boundary — A the layer painted on top there, B the
 *    one under it. Read with NEAREST.
 *  - the **sd mask**, half a metre per texel, one byte: the SIGNED distance in
 *    metres to that boundary, + on A's side, clamped to the band and quantised.
 *    Read LINEARLY.
 *
 * THE PAIR IS CANONICAL — both sides of a boundary carry the SAME (A, B), and
 * only the sign of the distance says which side a point is on. That is what
 * makes a NEAREST id and a LINEAR distance compose: the id may snap to either
 * side of the line without ever changing WHICH two materials are mixed, and
 * where exactly the cut runs comes out of the interpolated distance alone —
 * sub-texel sharp, at any zoom, with no geometry.
 *
 * WHY AN INTEGER TEXTURE FOR THE ID. `RG8UI` read through a `usampler2D` is a
 * layer index and not a number that was once one: integer textures cannot be
 * filtered at all, so NEAREST is enforced by the FORMAT rather than by a
 * sampler setting a driver may second-guess, and the value arrives as the exact
 * byte the server wrote. Two `R8` unorm textures would mean two samplers, two
 * `round(v · 255)` decodes and one more chance for a filtered texel to invent a
 * layer that is not there.
 *
 * `three` is not imported here — this is arithmetic and one GLSL string, which
 * is what lets the smoke transpile the file and run it on its own.
 */

// ── The payload ─────────────────────────────────────────────────────────────

/** One layer of the world's cut — an entry of the payload's `layers`. */
export interface TerrainLayer {
  index: number
  kind: string
  /** The surface-library id the kind wears ('' = no texture, use the colour). */
  surface: string
  /** How wide the transition from this layer to the one under it is, metres.
   *  0 is the HARD CUT (a room floor, a kerb). */
  edge_blend_m: number
  water: boolean
}

/** One baked tile of `GET /play/terrain-layers?keys=…`. A tile with no
 *  boundary in it carries `uniform` and no arrays at all. */
export interface TerrainLayerTile {
  origin_x: number
  origin_z: number
  uniform?: number
  id_size?: number
  sd_size?: number
  /** base64 of `id_size²` texels × 2 bytes (A, B), row-major from the origin. */
  id?: string
  /** base64 of `sd_size²` single bytes. */
  sd?: string
}

/** The coarse world-wide id mask — what the ground wears BEYOND the fine
 *  tiles. No signed distance rides with it: at this step every transition is
 *  narrower than a texel, so the honest answer out there is a hard cut. */
export interface TerrainLayerOverview {
  origin_x: number
  origin_z: number
  step_m: number
  cols: number
  rows: number
  id: string
}

/** The numbers a reader needs to decode the bytes — shipped with every
 *  answer, because a client that guessed them would decode a different
 *  landscape than the one that was baked. */
export interface TerrainLayerFormat {
  sig: string
  tile_m: number
  id_step_m: number
  sd_step_m: number
  sd_band_m: number
  sd_zero: number
  sd_codes_per_m: number
}

/**
 * ONE ZONE WATER of the world (§ A19 no. 5, "Ein Boden" E5a): a room whose
 * floor kind is a water surface carves its bed like a painted lake and wants
 * the same flat mirror over it.
 *
 * So it arrives in the very shape a painted lake carries its mirror in — the
 * outline in WORLD metres, the level in world y — and a renderer draws the pond
 * of a room with the machinery it draws a lake with, instead of inventing a
 * second water. A room the bake never saw (an unplaced location) is simply not
 * in the list; a guessed height would be the drape all over again.
 */
export interface TerrainLayerWater {
  location_id: string
  room_id: string
  kind: string
  polygon: [number, number][]
  water_level_effective: number
}

/** The INDEX answer of `GET /play/terrain-layers` (no `keys`). */
export interface TerrainLayerIndex extends TerrainLayerFormat {
  layers: TerrainLayer[]
  overview: TerrainLayerOverview
  tile_keys: string[]
  /** Every zone water of the world (E5a) — always present, empty in a world
   *  whose rooms have no water floor. */
  waters: TerrainLayerWater[]
}

/** The BATCH answer of `GET /play/terrain-layers?keys=…`. */
export interface TerrainLayerBatch extends TerrainLayerFormat {
  layers: TerrainLayer[]
  tiles: Record<string, TerrainLayerTile>
}

// ── The look of an edge ─────────────────────────────────────────────────────

/**
 * How far the noise pushes an edge in and out, in metres, and over what
 * wavelength.
 *
 * THE FRINGE IS NOT GONE, ONLY ITS MECHANISM. Until E3 a painted area faded out
 * over a fixed 1.5 m of alpha, wobbled by a value noise so the border read as a
 * fringe and not as an outline (`naturalGroundMath.NG_EDGE_NOISE_M` /
 * `NG_EDGE_WAVE_M`). The two numbers survive unchanged; what they act on is the
 * signed DISTANCE now, before the blend, so an organic border costs one add
 * instead of a transparent mesh.
 *
 * THE PUSH IS CAPPED BY HALF THE BLEND WIDTH, which is the whole reason a hard
 * cut stays hard: at `edge_blend_m = 0` the cap is 0 and the room floor ends on
 * the line the author drew, to the texel. At the default 1.5 m the cap is 0.75
 * and the full 0.5 m is spent — exactly today's look.
 */
export const LC_EDGE_NOISE_M = 0.5
export const LC_EDGE_WAVE_M = 2

/** Value noise in [0, 1) over world metres — the fract-sin hash of
 *  `naturalGround.ts`, written once so the GLSL and this file cannot drift.
 *  Deliberately NOT a texture: eight instructions, the same everywhere in the
 *  world, on every client, for ever. */
export function lcNoise(x: number, z: number): number {
  const hash = (px: number, pz: number): number => {
    const s = Math.sin(px * 12.9898 + pz * 78.233) * 43758.5453
    return s - Math.floor(s)
  }
  const ix = Math.floor(x)
  const iz = Math.floor(z)
  const fx = x - ix
  const fz = z - iz
  const wx = fx * fx * (3 - 2 * fx)
  const wz = fz * fz * (3 - 2 * fz)
  const a = hash(ix, iz)
  const b = hash(ix + 1, iz)
  const c = hash(ix, iz + 1)
  const d = hash(ix + 1, iz + 1)
  return (a * (1 - wx) + b * wx) * (1 - wz) + (c * (1 - wx) + d * wx) * wz
}

/** The signed distance a fragment really blends by: the baked one plus the
 *  noise push, capped at half the blend width. */
export function lcPushedSd(sd: number, blendM: number,
                           x: number, z: number): number {
  const cap = Math.min(LC_EDGE_NOISE_M, 0.5 * Math.max(blendM, 0))
  if (!(cap > 0)) return sd
  return sd + (lcNoise(x / LC_EDGE_WAVE_M + 5, z / LC_EDGE_WAVE_M + 23) * 2 - 1) * cap
}

/**
 * THE CUT, as one number: how much of layer A a fragment shows.
 *
 * `sd` is the signed distance in metres (+ inside A), `blendM` the layer's own
 * transition width and `fw` the size of one PIXEL in world metres
 * (`max(length(dFdx(world)), length(dFdy(world)))` in the shader).
 *
 * Two cases, and the second is why this is not a plain `smoothstep`:
 *
 *  - `blendM > 0` — a soft transition of exactly that width, centred on the
 *    line: `smoothstep(−b/2, +b/2, sd)`. Half the width lies on each side, so a
 *    "1.5 m blend" really is 1.5 m of ground and not 3.
 *  - `blendM = 0` — the HARD cut, ANALYTICALLY ANTI-ALIASED:
 *    `clamp(sd / fw + 0.5, 0, 1)`. That is a step one pixel wide, wherever the
 *    camera stands: near the ground a pixel is centimetres and the edge is
 *    razor sharp, far away a pixel is metres and the same expression averages
 *    the two materials instead of shimmering. A bare `step()` would stair-step
 *    along every diagonal; a fixed-width smoothstep would blur the near edge
 *    and still alias the far one.
 *
 * `fw` IS THE PIXEL MEASURED IN WORLD METRES, and it is measured on the world
 * position — never as `fwidth(sd)` (finding round 2026-08-21). A distance field
 * has a gradient of one, so the two are the same number wherever the field is
 * smooth; where it is not — across a texel whose neighbour names a different
 * boundary, or at the rim of the loaded mask window — `fwidth` of the SAMPLED
 * distance explodes, the "one pixel" becomes metres, and the cut turns into a
 * 50/50 average of two grounds for that one quad. That is a patch of the wrong
 * material that appears and disappears as the camera turns, which is exactly
 * what it looked like. The world position is continuous by construction.
 */
export function layerWeight(sd: number, blendM: number, fw: number): number {
  const clamp01 = (v: number): number => (v < 0 ? 0 : v > 1 ? 1 : v)
  if (blendM > 0) {
    const t = clamp01((sd + blendM * 0.5) / blendM)
    return t * t * (3 - 2 * t)
  }
  return clamp01(sd / Math.max(fw, 1e-6) + 0.5)
}

// ── The window ──────────────────────────────────────────────────────────────

/**
 * The loaded masks as ONE rectangle, ready to become two textures.
 *
 * The tiles are packed into a single lattice rather than sampled per tile, for
 * the same reason `terrainLod.buildNear` packs the height tiles: a fragment
 * shader that had to find its tile first would branch per pixel over a set that
 * changes as the player walks. A tile the batch did not bring is left at the
 * neutral fill — pair (0, 0), distance +band — which reads as bare ground, the
 * very thing an unindexed tile IS.
 */
export interface LayerMaskWindow {
  /** South-west corner of the window in world metres. */
  originX: number
  originZ: number
  /** Metres per texel of each mask. */
  idStep: number
  sdStep: number
  /** Texels per axis of each mask. */
  idSize: number
  sdSize: number
  /** `idSize² × 2` bytes, (A, B) per texel, row-major. */
  id: Uint8Array
  /** `sdSize²` bytes, the quantised signed distance. */
  sd: Uint8Array
  /** How the `sd` bytes decode: `(code − zero) / codesPerM` metres. */
  sdZero: number
  sdCodesPerM: number
  sdBandM: number
}

/** One quantised distance byte as metres. */
export function decodeSd(code: number, zero: number, codesPerM: number): number {
  return (code - zero) / (codesPerM || 1)
}

/**
 * Pack a batch of baked tiles into ONE window over the tiles it holds.
 *
 * `keys` are `"tx,tz"`, the height tiles' own form. The window is the bounding
 * box of those tiles, snapped to the tile lattice — which is already a multiple
 * of both mask steps, so no tile ever lands on a fractional texel and the
 * packing is a straight block copy.
 *
 * A `uniform` tile is filled with its own layer on both halves of the pair and
 * with the maximum positive distance, which is exactly what "far inside one
 * ground" means; a tile that is missing entirely stays bare ground.
 */
export function packLayerWindow(tiles: Map<string, TerrainLayerTile>,
                                fmt: TerrainLayerFormat): LayerMaskWindow | null {
  if (!tiles.size || !(fmt.tile_m > 0)) return null
  let tx0 = Infinity
  let tz0 = Infinity
  let tx1 = -Infinity
  let tz1 = -Infinity
  for (const key of tiles.keys()) {
    const [tx, tz] = key.split(',').map(Number)
    if (!Number.isFinite(tx) || !Number.isFinite(tz)) continue
    tx0 = Math.min(tx0, tx)
    tz0 = Math.min(tz0, tz)
    tx1 = Math.max(tx1, tx)
    tz1 = Math.max(tz1, tz)
  }
  if (!Number.isFinite(tx0)) return null
  const idPer = Math.round(fmt.tile_m / fmt.id_step_m)
  const sdPer = Math.round(fmt.tile_m / fmt.sd_step_m)
  // THE WINDOW IS SQUARE. The shader addresses both masks with ONE size, and a
  // rectangle would cost two more uniforms and a second branch for a saving of
  // a few hundred kilobytes on a window that is nearly square anyway (the want
  // set is a disc around the player). The larger axis wins; the surplus stays
  // at the neutral fill, which reads as bare ground.
  const span = Math.max(tx1 - tx0 + 1, tz1 - tz0 + 1)
  const idN = idPer * span
  const sdN = sdPer * span
  const id = new Uint8Array(idN * idN * 2)
  const sd = new Uint8Array(sdN * sdN)
  sd.fill(255)
  for (const [key, tile] of tiles) {
    const [tx, tz] = key.split(',').map(Number)
    if (!Number.isFinite(tx) || !Number.isFinite(tz)) continue
    const ix0 = (tx - tx0) * idPer
    const iz0 = (tz - tz0) * idPer
    const sx0 = (tx - tx0) * sdPer
    const sz0 = (tz - tz0) * sdPer
    if (tile.uniform !== undefined && tile.uniform !== null) {
      const layer = tile.uniform & 255
      for (let j = 0; j < idPer; j += 1) {
        let dst = ((iz0 + j) * idN + ix0) * 2
        for (let i = 0; i < idPer; i += 1) {
          id[dst] = layer
          id[dst + 1] = layer
          dst += 2
        }
      }
      continue
    }
    const idBytes = base64Bytes(tile.id)
    const sdBytes = base64Bytes(tile.sd)
    if (idBytes) {
      for (let j = 0; j < idPer; j += 1) {
        const src = j * idPer * 2
        id.set(idBytes.subarray(src, src + idPer * 2), ((iz0 + j) * idN + ix0) * 2)
      }
    }
    if (sdBytes) {
      for (let j = 0; j < sdPer; j += 1) {
        const src = j * sdPer
        sd.set(sdBytes.subarray(src, src + sdPer), (sz0 + j) * sdN + sx0)
      }
    }
  }
  return {
    originX: tx0 * fmt.tile_m,
    originZ: tz0 * fmt.tile_m,
    idStep: fmt.id_step_m,
    sdStep: fmt.sd_step_m,
    idSize: idN,
    sdSize: sdN,
    id,
    sd,
    sdZero: fmt.sd_zero,
    sdCodesPerM: fmt.sd_codes_per_m,
    sdBandM: fmt.sd_band_m,
  }
}

/** base64 -> bytes, in whichever runtime this is loaded (browser or node). */
function base64Bytes(b64: string | undefined): Uint8Array | null {
  if (!b64) return null
  const g = globalThis as unknown as {
    atob?: (s: string) => string
    Buffer?: { from(s: string, enc: string): Uint8Array }
  }
  if (typeof g.atob === 'function') {
    const bin = g.atob(b64)
    const out = new Uint8Array(bin.length)
    for (let i = 0; i < bin.length; i += 1) out[i] = bin.charCodeAt(i)
    return out
  }
  if (g.Buffer) return new Uint8Array(g.Buffer.from(b64, 'base64'))
  return null
}

// ── The CPU twin of the shader's lookup ─────────────────────────────────────

/** Texel index of a world coordinate on a mask lattice — `floor((p − o)/step)`,
 *  clamped into the window. The shader's NEAREST fetch lands on exactly this
 *  texel, which is what makes the two readings one. */
function texelOf(p: number, origin: number, step: number, size: number): number {
  const i = Math.floor((p - origin) / step)
  return i < 0 ? 0 : i >= size ? size - 1 : i
}

/**
 * The (A, B) pair at a world point — the CPU twin of the shader's id fetch.
 *
 * Outside the window the answer is bare ground on both halves, which is what an
 * unloaded tile shows.
 */
export function layerPairAt(win: LayerMaskWindow | null,
                            x: number, z: number): [number, number] {
  if (!win) return [0, 0]
  const i = texelOf(x, win.originX, win.idStep, win.idSize)
  const j = texelOf(z, win.originZ, win.idStep, win.idSize)
  const k = (j * win.idSize + i) * 2
  return [win.id[k] ?? 0, win.id[k + 1] ?? 0]
}

/** The signed distance at a world point, in metres — NEAREST, the twin of the
 *  shader's LINEAR fetch at a texel centre. The smoke reads it here and the
 *  shader interpolates between two of them; a reader that needs the
 *  interpolated value asks the shader, not this. */
export function layerSdAt(win: LayerMaskWindow | null,
                          x: number, z: number): number {
  if (!win) return 0
  const i = texelOf(x, win.originX, win.sdStep, win.sdSize)
  const j = texelOf(z, win.originZ, win.sdStep, win.sdSize)
  return decodeSd(win.sd[j * win.sdSize + i] ?? 255, win.sdZero, win.sdCodesPerM)
}

/**
 * WHICH LAYER IS ON TOP at a world point — the gate everything non-graphical
 * asks (user decision 5.2: the undergrowth of a ground grows only where that
 * ground really is the topmost one).
 *
 * It is the SAME reading the picture makes, and that is the point of asking the
 * mask instead of walking the polygons a second time: an area painted over a
 * wood hides the wood in the picture and must hide its undergrowth too, and two
 * implementations of "topmost" are two answers waiting to differ. The rule is
 * the sign of the distance — positive means the fragment is on A's side, which
 * is the layer painted on top.
 *
 * A point outside the window answers bare ground (0), which is what an unloaded
 * tile draws.
 */
export function topLayerAt(win: LayerMaskWindow | null,
                           x: number, z: number): number {
  if (!win) return 0
  const [a, b] = layerPairAt(win, x, z)
  if (a === b) return a
  return layerSdAt(win, x, z) >= 0 ? a : b
}

// ── The GLSL ────────────────────────────────────────────────────────────────

/**
 * The compositor, as GLSL — ONE surface, two layers, one cut.
 *
 * `maxLayers` sizes the uniform array of per-layer numbers; it is a compile-time
 * constant because GLSL ES 3.00 wants one, and the client passes the size of the
 * world's own table (rounded up) so a small world compiles a small program.
 *
 * The chain, per fragment:
 *
 *  1. the window test — inside the loaded tiles the FINE masks answer, outside
 *     them the coarse overview does, with a distance of "far inside" so its
 *     edges are hard. One branch, no per-pixel tile search.
 *  2. the pair and the distance; the noise push (`lcPushedSd`) on the distance
 *     alone, so an organic border costs one add and no transparency.
 *  3. `lcWeight` — the cut, `smoothstep` of the layer's own width or the
 *     `fwidth`-anti-aliased step at width 0.
 *  4. two samples per layer out of ONE `sampler2DArray` — the narrow one and
 *     the wide, shifted one the anti-tile blend needs — composited by the same
 *     weight, so the broken-up repeat survives the cut instead of being applied
 *     to a colour that is already a mixture of two grounds.
 *
 * The smoke does not read this string. It reimplements the arithmetic
 * independently (`layerWeight`, `lcPushedSd`) and checks it on hand-derived
 * fixtures — a check that read the string could only prove the string equals
 * itself.
 */
/** The anti-tile numbers as GLSL literals — the very ones the drapes spent
 *  (`naturalGroundMath.NG_DETAIL_SCALE` / `NG_DETAIL_OFFSET` / `NG_MIX_M` /
 *  `NG_MIX_MAX`) and the edge noise above. They are strings because this module
 *  has no dependency on the client, and they are the ONLY spelling of these
 *  four numbers: the numeric twins that used to sit beside them
 *  (`LC_DETAIL_SCALE` / `LC_DETAIL_OFFSET` / `LC_MIX_M` / `LC_MIX_MAX`) never
 *  had a reader and were deleted in E6 — a second spelling nobody reads is a
 *  drift waiting to happen. */
const LC_DETAIL_SCALE_GLSL = '0.23'
const LC_DETAIL_OFFSET_GLSL = '0.50'
const LC_MIX_M_GLSL = '7.00'
const LC_MIX_MAX_GLSL = '0.50'
const LC_EDGE_NOISE_GLSL = '0.50'
const LC_EDGE_WAVE_GLSL = '2.00'

export function terrainLayerGlsl(maxLayers: number): string {
  const n = Math.max(1, Math.floor(maxLayers))
  return `
uniform highp usampler2D uLcNearId;
uniform sampler2D uLcNearSd;
uniform highp usampler2D uLcFarId;
uniform sampler2DArray uLcSurf;
uniform vec4 uLcNear;        // originX, originZ, idStep, idSize
uniform vec4 uLcNearSdGeom;  // originX, originZ, sdStep, sdSize
uniform vec4 uLcFar;         // originX, originZ, step, 0
uniform vec2 uLcFarSize;     // cols, rows
uniform vec2 uLcSdCode;      // zero, codes per metre
uniform float uLcBandM;
uniform vec4 uLcLayer[ ${n} ];   // edge_blend_m, metres per texture tile, 0, 0
varying vec2 vLcWorld;

float lcHash( vec2 p ) {
  return fract( sin( dot( p, vec2( 12.9898, 78.233 ) ) ) * 43758.5453 );
}
float lcNoise( vec2 p ) {
  vec2 i = floor( p );
  vec2 f = fract( p );
  vec2 w = f * f * ( 3.0 - 2.0 * f );
  return mix( mix( lcHash( i ), lcHash( i + vec2( 1.0, 0.0 ) ), w.x ),
              mix( lcHash( i + vec2( 0.0, 1.0 ) ), lcHash( i + vec2( 1.0, 1.0 ) ), w.x ),
              w.y );
}

/** The cut: how much of layer A this fragment shows. See \`layerWeight\`.
 *
 *  \`pixelM\` IS THE PIXEL IN WORLD METRES, handed in from the world position's
 *  own derivatives — NOT \`fwidth( sd )\`. A distance field has a gradient of
 *  one, so where the field is smooth the two are the same number; where it is
 *  not — a texel whose neighbour names a different boundary, the rim of the
 *  loaded window — the derivative of the SAMPLED distance explodes and the hard
 *  cut collapses to a 50/50 average of two grounds for that quad. That is a
 *  patch of the wrong material that comes and goes as the camera turns.
 *
 *  BOTH BRANCHES ARE STILL EVALUATED: \`blendM\` comes out of a uniform array
 *  indexed by the LAYER, which differs across a quad on every boundary, so the
 *  width is read unconditionally and the branch picks a finished number.
 *  The \`max\` inside the smoothstep only keeps its two edges apart when the
 *  width is 0; that result is discarded. */
float lcWeight( float sd, float blendM, float pixelM ) {
  float b = max( blendM, 1e-4 );
  float soft = smoothstep( -0.5 * b, 0.5 * b, sd );
  float hard = clamp( sd / max( pixelM, 1e-6 ) + 0.5, 0.0, 1.0 );
  return blendM > 0.0 ? soft : hard;
}

/** One layer's albedo at a world point — the narrow sample and the wide,
 *  shifted one of the anti-tile blend, in one call so the compositor spends
 *  exactly two array fetches per layer.
 *
 *  textureGrad, NOT texture: every layer scales the world position by its OWN
 *  metres-per-tile, so the uv JUMPS at a ground boundary — and an implicit
 *  derivative of a jumping uv is a gigantic gradient, i.e. the coarsest mip,
 *  i.e. a blurred line along every edge in the world. The gradient is therefore
 *  taken from the WORLD position (which is continuous, always) and divided by
 *  this layer's own scale. */
vec3 lcSurface( int layer, vec2 p, vec2 dpdx, vec2 dpdy, float wide ) {
  float sizeM = max( uLcLayer[ layer ].y, 0.01 );
  vec2 gx = dpdx / sizeM;
  vec2 gy = dpdy / sizeM;
  vec3 narrow = textureGrad( uLcSurf, vec3( p / sizeM, float( layer ) ), gx, gy ).rgb;
  vec3 broad = textureGrad( uLcSurf,
    vec3( p / sizeM * ${LC_DETAIL_SCALE_GLSL} + ${LC_DETAIL_OFFSET_GLSL}, float( layer ) ),
    gx * ${LC_DETAIL_SCALE_GLSL}, gy * ${LC_DETAIL_SCALE_GLSL} ).rgb;
  return mix( narrow, broad, wide );
}

void lcCompose( inout vec4 albedo ) {
  vec2 p = vLcWorld;
  // The two derivatives, taken ONCE and at uniform control flow — everything
  // below branches, and a derivative inside a branch that differs across a quad
  // is undefined in GLSL ES.
  vec2 dpdx = dFdx( p );
  vec2 dpdy = dFdy( p );
  uvec2 pair;
  float sd = uLcBandM;
  float nearN = uLcNear.w;
  vec2 nearIdx = ( p - uLcNear.xy ) / uLcNear.z;
  if ( nearN > 0.5 && nearIdx.x >= 0.0 && nearIdx.y >= 0.0
       && nearIdx.x < nearN && nearIdx.y < nearN ) {
    pair = texelFetch( uLcNearId, ivec2( nearIdx ), 0 ).rg;
    vec2 sdUv = ( ( p - uLcNearSdGeom.xy ) / uLcNearSdGeom.z ) / uLcNearSdGeom.w;
    // textureLod( …, 0 ) rather than texture(): the mask has no mip chain, and
    // an implicit lookup would ask for a derivative inside this very branch.
    sd = ( textureLod( uLcNearSd, sdUv, 0.0 ).r * 255.0 - uLcSdCode.x ) / uLcSdCode.y;
  } else if ( uLcFarSize.x > 1.5 ) {
    vec2 farIdx = floor( ( p - uLcFar.xy ) / uLcFar.z );
    farIdx = clamp( farIdx, vec2( 0.0 ), uLcFarSize - 1.0 );
    pair = texelFetch( uLcFarId, ivec2( farIdx ), 0 ).rg;
  } else {
    pair = uvec2( 0u, 0u );
  }
  int a = int( pair.r );
  int b = int( pair.g );
  float blendM = uLcLayer[ a ].x;
  // The organic border: the noise pushes the LINE, not the alpha, and the push
  // is capped at half the width so a hard cut stays on the metre it was drawn.
  float cap = min( ${LC_EDGE_NOISE_GLSL}, 0.5 * max( blendM, 0.0 ) );
  float sdN = sd + ( lcNoise( p / ${LC_EDGE_WAVE_GLSL} + vec2( 5.0, 23.0 ) ) * 2.0 - 1.0 ) * cap;
  // ONE PIXEL, IN METRES OF GROUND — the anti-aliasing width of a hard cut,
  // measured on the continuous world position instead of on the sampled
  // distance (see \`lcWeight\`).
  float pixelM = max( length( dpdx ), length( dpdy ) );
  float w = lcWeight( sdN, blendM, pixelM );
  float wide = lcNoise( p / ${LC_MIX_M_GLSL} ) * ${LC_MIX_MAX_GLSL};
  vec3 col = a == b
    ? lcSurface( a, p, dpdx, dpdy, wide )
    : mix( lcSurface( b, p, dpdx, dpdy, wide ),
           lcSurface( a, p, dpdx, dpdy, wide ), w );
  albedo.rgb = col * albedo.rgb;
}
`
}

/** The vertex-side head: the world position the compositor reads. Written at
 *  `project_vertex`, i.e. AFTER the CDLOD displacement has put the vertex where
 *  it really is — measuring before it would paint the ground where it used to
 *  be. */
export function terrainLayerVertexGlsl(): string {
  return 'varying vec2 vLcWorld;\n'
}
