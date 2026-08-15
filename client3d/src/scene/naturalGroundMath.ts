/**
 * Pure arithmetic of the NATURAL GROUND — the numbers the shader patch of
 * `scene/naturalGround.ts` is built from, and the only half of it that can be
 * checked without a GPU.
 *
 * Everything here is a function of its arguments: no Three.js, no module
 * state, no DOM — the discipline of `scene/scatterLod.ts`, and what lets
 * `client3d/scripts/smoke_natural_ground.mjs` transpile this file and pin it
 * with hand-derived numbers. It must stay IMPORT-FREE.
 *
 * IT IS ALSO THE SINGLE SOURCE OF THE GLSL CONSTANTS. `naturalGround.ts`
 * prints its shader out of the very constants below, so a hand check on the
 * function and a string check on the composed shader measure ONE number — a
 * mutant that turns the AO around here turns it around in the shader too.
 * That is the whole reason the amplitudes do not live beside the GLSL that
 * spends them.
 *
 * WHAT THE GROUND GETS, in the order the fragment applies it:
 *  (1) ANTI-TILE — the ground texture sampled a second time at a much broader
 *      scale and shifted half a UV, blended by value noise. One texture, two
 *      scales: the eye stops finding the repeat because there is no single
 *      period left to find.
 *  (2) COLOUR PATCHES — a slow, large modulation of brightness and saturation
 *      (never of hue: a green meadow with blue patches is a bug, not weather).
 *      This is the ONE stage a single-coloured kind gets as well, and the
 *      reason it is separate from (1).
 *  (3) HEIGHT AO — a fragment lying lower than its surroundings darkens, one
 *      lying higher brightens a little. It reads the world's own heightfield,
 *      so a flat world is neutral by arithmetic and not by a switch.
 *  (4) SOFT EDGES — a painted area does not end on a drawn line but fades out
 *      over the last metre and a half of itself, along a noise-shifted edge,
 *      and what lies under it (the base plate, or the area below in the stack)
 *      comes through. Its half is the DISTANCE TO THE NEAREST RING EDGE, which
 *      is arithmetic on the polygon and therefore lives here.
 *
 * NO SLIDERS. These are numbers of the VIEW, like the corridor's
 * (`scene/occlusion.ts`) and the wind's — a world that ships a knob for the
 * blend weight of its ground texture has a knob nobody can judge.
 */

// ── (1) Anti-tile ───────────────────────────────────────────────────────────

/** Scale of the SECOND sample, as a factor on the first one's UV. 0.23 makes
 *  its features roughly 4.3 times as wide, which is far enough from 1 that the
 *  two periods share no visible common multiple — the point of the whole
 *  exercise. Anything nearer 1 beats against the base sample instead of
 *  breaking it up. */
export const NG_DETAIL_SCALE = 0.23;
/** …and shifted half a UV unit, so the two samples never show the same texel
 *  of the source image at the same place. Without the shift both samples agree
 *  exactly at the origin of every tile and the repeat survives the blend. */
export const NG_DETAIL_OFFSET = 0.5;
/** Wavelength of the noise that blends the two samples, in world metres. A
 *  patch of ground the size of a small clearing: short enough that a single
 *  screen shows several of them, long enough not to read as dirt. */
export const NG_MIX_M = 7;
/** How much of the broad sample the blend may reach — HALF, never all of it.
 *  The base sample is the ground the world was authored with; the second one
 *  breaks its rhythm and must not replace it. */
export const NG_MIX_MAX = 0.5;

/** The UV of the second sample. Trivial arithmetic, kept here because the two
 *  constants above are what a reader wants pinned by a number rather than by
 *  reading a shader string. */
export function ngDetailUv(u: number, v: number): [number, number] {
  return [u * NG_DETAIL_SCALE + NG_DETAIL_OFFSET,
          v * NG_DETAIL_SCALE + NG_DETAIL_OFFSET];
}

// ── (2) Colour patches ──────────────────────────────────────────────────────

/** Wavelength of the colour modulation, in world metres — a walk of half a
 *  minute crosses one patch. Deliberately far longer than the anti-tile noise:
 *  the two stages must not share a rhythm, or the ground would breathe. */
export const NG_TINT_M = 25;
/** How far brightness and saturation swing, as a share of the value they
 *  modulate. ±8 % is a ground that has weather; ±20 % is a ground somebody
 *  spilled something on. */
export const NG_TINT_AMP = 0.08;

/** The two factors of the colour stage for a pair of noise readings in 0..1.
 *
 *  Both are multipliers around 1: `brightness` scales the albedo, `saturation`
 *  is the mix weight AWAY from the fragment's own luminance (1 = untouched,
 *  >1 = more colourful). Neither touches hue, which is what keeps a meadow
 *  green in every patch of it. */
export function ngTintFactors(nBright: number, nSat: number
): { brightness: number; saturation: number } {
  return {
    brightness: 1 + NG_TINT_AMP * (nBright * 2 - 1),
    saturation: 1 + NG_TINT_AMP * (nSat * 2 - 1),
  };
}

// ── (3) Height AO ───────────────────────────────────────────────────────────

/** Radius of the ring the surroundings are read at, in world metres. Three
 *  metres is a step or four: near enough that a hollow a figure stands in is
 *  really measured, far enough that the tap does not simply read the
 *  fragment's own cell back. */
export const NG_AO_RING_M = 3;
/** The height difference at which the shading is fully spent, in metres. A
 *  two-metre dip is a hollow; anything deeper is a valley and gets no more
 *  than the hollow does. */
export const NG_AO_SPAN_M = 2;
/** How far down a fragment BELOW its surroundings goes, as a share of its
 *  albedo. */
export const NG_AO_DOWN = 0.12;
/** …and how far up one ABOVE them goes. Half the darkening on purpose: a rim
 *  catching light is a hint, a rim glowing is a bug. */
export const NG_AO_UP = 0.06;

/** Where the four taps sit, relative to the fragment, in world metres. Four
 *  and not eight: this is a shading hint, not an ambient-occlusion solver, and
 *  every tap is a texture fetch on every ground fragment on screen. */
export function ngAoTaps(ringM: number = NG_AO_RING_M): [number, number][] {
  return [[ringM, 0], [-ringM, 0], [0, ringM], [0, -ringM]];
}

/**
 * The AO term for one fragment: what its albedo is multiplied by, minus one.
 *
 * `ringMean` is the mean of the four taps, `own` the fragment's own height.
 * SIGN: the surroundings standing HIGHER than the fragment means the fragment
 * lies in a hollow, and a hollow is darker — so a positive difference gives a
 * NEGATIVE term. Turning that around lights the ditches and shades the ridges,
 * which is exactly the picture the stage exists to avoid.
 *
 * Flat ground answers 0 to the last bit, which is the neutrality promise: a
 * world nobody has shaped is not merely almost untouched.
 */
export function ngAoShade(ringMean: number, own: number): number {
  const t = Math.min(Math.max((ringMean - own) / NG_AO_SPAN_M, -1), 1);
  return t > 0 ? -NG_AO_DOWN * t : -NG_AO_UP * t;
}

/** The heightfield as the shader has to address it — the overview's own
 *  header, and nothing else. */
export interface NgFieldSpec {
  origin_x: number;
  origin_z: number;
  step_m: number;
  rows: number;
  cols: number;
}

/**
 * World point → texture coordinate of the height data texture.
 *
 * TEXEL CENTRES, not corners: support point `i` of the field lies at
 * `origin + i · step` and is the CENTRE of texel `i`, so its coordinate is
 * `(i + 0.5) / cols`. Getting that half wrong shifts the whole shading by half
 * a support cell — invisible in a screenshot, and a systematic lie about where
 * the hill is.
 *
 * `inside` is false beyond the field, where the stage has to be exactly
 * neutral: the world outside the raster is the flat border the server pins to
 * 0, and shading it against its own edge would draw a rim around the map.
 */
export function ngFieldUv(x: number, z: number, field: NgFieldSpec
): { u: number; v: number; inside: boolean } {
  const u = ((x - field.origin_x) / field.step_m + 0.5) / field.cols;
  const v = ((z - field.origin_z) / field.step_m + 0.5) / field.rows;
  return { u, v, inside: u >= 0 && u <= 1 && v >= 0 && v <= 1 };
}

// ── (4) Soft area edges ─────────────────────────────────────────────────────

/** Width of the band an area fades out over, in world metres. A metre and a
 *  half is about one stride: wide enough that the eye reads a transition
 *  instead of a line, narrow enough that a three-metre path is still a path
 *  and not a smear. */
export const NG_EDGE_BAND_M = 1.5;
/** How far the noise pushes the edge in and out, in metres. Half a metre is
 *  what turns the polygon's straight run into a fringe; more than that and a
 *  painted shape stops being the shape the author drew. */
export const NG_EDGE_NOISE_M = 0.5;
/** Wavelength of that noise, in metres — the size of one tongue of the fringe.
 *  Two metres reads as ground finding its way; twenty would read as the
 *  polygon being wrong. */
export const NG_EDGE_WAVE_M = 2;
/**
 * From this distance inward the area is FULLY OPAQUE, whatever the noise does:
 * band plus the largest inward push the noise can spend. The core of an area
 * is never blended — that is the whole reason the band is narrow (there is no
 * new sorting problem if only a fringe is transparent), and this constant is
 * where "the core is opaque" is a number rather than a hope.
 */
export const NG_EDGE_OPAQUE_M = NG_EDGE_BAND_M + NG_EDGE_NOISE_M;

/** A world point on the ground plane, `[x, z]` in metres — structurally the
 *  `Point2` of `@anima/scene-render`, spelled out because this module must
 *  stay import-free (see the header). */
export type NgPoint2 = readonly [number, number];

/**
 * Distance from a point to a SEGMENT (not to its infinite line), in the plan.
 *
 * The projection parameter is clamped to `[0, 1]`, which is what makes a
 * corner of the ring measure as a corner: beyond the end of an edge the
 * nearest thing on it is its endpoint. A segment of length zero — two equal
 * ring corners survive `cleanRing` only as an artefact — answers the distance
 * to that point instead of dividing by zero.
 */
export function ngSegmentDistance(px: number, pz: number,
                                  ax: number, az: number,
                                  bx: number, bz: number): number {
  const dx = bx - ax;
  const dz = bz - az;
  const len2 = dx * dx + dz * dz;
  const t = len2 > 0
    ? Math.min(Math.max(((px - ax) * dx + (pz - az) * dz) / len2, 0), 1)
    : 0;
  const cx = px - (ax + t * dx);
  const cz = pz - (az + t * dz);
  return Math.sqrt(cx * cx + cz * cz);
}

/**
 * Distance from a point to the nearest edge of a CLOSED ring, unsigned.
 *
 * The ring is the area's own polygon (`buildAreaGeometry`'s `ring`, world
 * `[x, z]`, already cleaned) and it is read as closed: the edge from the last
 * corner back to the first is an edge like any other, or every area would
 * stay hard along the one edge nobody listed twice.
 *
 * UNSIGNED on purpose. Every vertex this is asked about lies inside the ring
 * or on it — it comes out of the triangulation of that very ring — so inside
 * and outside never have to be told apart, and a sign would only be a second
 * thing that can be wrong. A ring with fewer than two corners has no edge at
 * all and answers `Infinity`, which the band reads as "nothing near, stay
 * opaque".
 */
export function ngEdgeDistance(x: number, z: number,
                               ring: readonly NgPoint2[] | null | undefined): number {
  const n = ring?.length ?? 0;
  if (!ring || n < 2) return Infinity;
  let best = Infinity;
  for (let i = 0; i < n; i += 1) {
    const [ax, az] = ring[i];
    const [bx, bz] = ring[(i + 1) % n];
    const d = ngSegmentDistance(x, z, ax, az, bx, bz);
    if (d < best) best = d;
  }
  return best;
}

/**
 * How opaque the ground is at a point: `smoothstep(0, BAND, edgeDist + push)`.
 *
 * `noise01` is one reading of the shader's own value noise in `0..1`; 0.5 is
 * the neutral middle and pushes the edge nowhere. The curve is GLSL's own
 * `smoothstep` (`3t² − 2t³` over the clamped `t`), because the fragment
 * spends exactly that one — this function and the shader line it is checked
 * against must be the same arithmetic, not merely a similar shape.
 *
 * 0 at the ring, 1 from `NG_EDGE_BAND_M` inward, and exactly 0.5 half way:
 * the hand values `smoke_natural_ground.mjs` pins.
 */
export function ngEdgeAlpha(edgeDist: number, noise01 = 0.5): number {
  const push = (noise01 * 2 - 1) * NG_EDGE_NOISE_M;
  const t = Math.min(Math.max((edgeDist + push) / NG_EDGE_BAND_M, 0), 1);
  return t * t * (3 - 2 * t);
}

// ── The band's geometry: refining a drape until the distance interpolates ───

/** Longest edge that is still worth splitting, in metres. Under half a metre
 *  the triangle is finer than the noise that shifts the edge, and no picture
 *  gets better. */
export const NG_EDGE_MIN_M = 0.5;
/** How far the linear interpolation of the distance may miss the truth at an
 *  edge's midpoint before that edge is split, in metres. A quarter metre is a
 *  sixth of the band and a half of what the noise pushes anyway. */
export const NG_EDGE_TOL_M = 0.25;
/** How often the whole drape may be refined. Six halvings take a 32 m cell —
 *  the coarsest the overview grid ever gets — below the half-metre floor, and
 *  the two passes on top of that are for the cascade: a piece can be marked
 *  because its NEIGHBOUR needed splitting, one pass later than itself. */
export const NG_EDGE_PASSES = 8;
/** …and the hard stop, in triangles per area, for a ring that defeats the
 *  criterion (a hairline spiral, a self-intersecting polygon). Reaching it
 *  costs a harder edge on one area, never a frozen frame. */
export const NG_EDGE_MAX_TRIS = 20000;

/** One vertex of a drape while it is being refined: the plan position, the
 *  height it was already lifted to, its UV, and its distance to the ring. */
interface NgVert { x: number; y: number; z: number; u: number; v: number; d: number }

/** The refined drape: triangle soup, plus the per-vertex distance that becomes
 *  the `aEdgeDist` attribute. `uv` is `null` exactly when the input had none. */
export interface NgBandMesh {
  pos: number[];
  uv: number[] | null;
  dist: number[];
}

/**
 * The midpoint of an edge, with the TRUE distance measured there — never the
 * interpolated one, since measuring it is the entire point of the split.
 *
 * Everything else is interpolated linearly, and that is what keeps the
 * refinement free of consequences: the vertices arrive already lifted onto the
 * relief, so a midpoint's height is the height of the triangle's own plane and
 * the refined drape describes the SAME surface as the coarse one. Sampling the
 * heightfield here instead would lift the midpoints onto the field and make
 * the drape wander off the plate it has to lie on.
 */
function ngMidVert(a: NgVert, b: NgVert, ring: readonly NgPoint2[]): NgVert {
  const x = (a.x + b.x) / 2;
  const z = (a.z + b.z) / 2;
  return { x, y: (a.y + b.y) / 2, z, u: (a.u + b.u) / 2, v: (a.v + b.v) / 2,
           d: ngEdgeDistance(x, z, ring) };
}

/** Is this edge long enough to be worth a vertex? Under the floor the triangle
 *  is already finer than the noise that shifts the fringe. */
function ngLongEnough(a: NgVert, b: NgVert): boolean {
  const dx = b.x - a.x;
  const dz = b.z - a.z;
  return dx * dx + dz * dz > NG_EDGE_MIN_M * NG_EDGE_MIN_M;
}

/**
 * Is any part of this run of vertices near enough to the ring to care?
 *
 * THE BAND GATE, and it is asked of the CORNERS, never of the sample point.
 * What the fragment ends up with is the interpolation between the corners, so
 * a triangle reaching from the ring (0) to deep inside (30 m) draws the whole
 * band somewhere across itself — even though every midpoint of it reads metres.
 * Gating on the sampled reading instead was the bug that let a coarse polygon
 * keep a band twice too wide: the error was found, and then ignored because the
 * place it was measured at happened to be far out.
 *
 * The other direction is the cheap one, and it is exact: with EVERY corner past
 * the opaque distance the interpolation is past it everywhere between them, and
 * the face is opaque whatever the truth does.
 */
function ngNearBand(...dists: number[]): boolean {
  return Math.min(...dists) <= NG_EDGE_OPAQUE_M;
}

/** Does a reading miss badly enough to be worth a triangle? `truth` is the
 *  measured distance at a point, `lin` what the interpolation reports there. */
function ngMisses(truth: number, lin: number): boolean {
  return Math.abs(truth - lin) > NG_EDGE_TOL_M;
}

/**
 * Must this edge be split, and if so, at which vertex?
 *
 * THE CRITERION IS THE INTERPOLATION ERROR, not the length: the fragment gets
 * `aEdgeDist` interpolated linearly across the triangle, and along a straight
 * stretch of ring the true distance IS linear — a 30 m triangle sitting on one
 * ring edge is exact and must not be touched. What is not linear is a triangle
 * that spans a corner or, worse, one whose corners all sit on the ring while
 * its middle is far from it (the chord of a coarse triangulation): there the
 * interpolation reads zero across the whole face and the area would fade out
 * completely. So the midpoint is measured and compared with the average.
 */
function ngSplitEdge(a: NgVert, b: NgVert, ring: readonly NgPoint2[]): NgVert | null {
  if (!ngLongEnough(a, b) || !ngNearBand(a.d, b.d)) return null;
  const mid = ngMidVert(a, b, ring);
  return ngMisses(mid.d, (a.d + b.d) / 2) ? mid : null;
}

/**
 * …and the same question for the INSIDE of a triangle, asked at its centroid.
 *
 * The three edges can each be exact while the face between them is not: where
 * the ring turns, the distance is the MINIMUM of two straight-edge readings,
 * and a minimum of two linear functions is not linear. The corner of an
 * L-shaped area is the everyday case — every edge of the triangle covering it
 * interpolates perfectly and the middle of it is a metre out, which is most of
 * the band.
 */
function ngSplitInside(t: readonly NgVert[], ring: readonly NgPoint2[]): boolean {
  if (!ngNearBand(t[0].d, t[1].d, t[2].d)) return false;
  const x = (t[0].x + t[1].x + t[2].x) / 3;
  const z = (t[0].z + t[1].z + t[2].z) / 3;
  return ngMisses(ngEdgeDistance(x, z, ring), (t[0].d + t[1].d + t[2].d) / 3);
}

/** How finely an edge's endpoints are told apart when they are named, in
 *  metres: a tenth of a millimetre. Two vertices nearer than that are the same
 *  vertex for every purpose this module has — the band is measured in
 *  decimetres — while a real neighbour is centimetres away at the very least. */
export const NG_EDGE_KEY_M = 1e-4;

/**
 * The name of an edge, the same from both triangles that own it.
 *
 * This is what keeps the refinement CRACK-FREE. A triangle that splits because
 * of its own inside would otherwise leave its neighbour with a straight edge
 * against a split one — no gap in the surface (the midpoint lies on the line),
 * but a step in the alpha along it, which reads as a hairline seam through the
 * fringe. Marking EDGES rather than triangles means both owners see the same
 * decision.
 *
 * THE COORDINATES ARE QUANTISED FIRST, and that is not tidiness. The vertices
 * a shared edge is made of are NOT bit-identical from both sides: the grid clip
 * (`subdivideOnGrid`) walks the two triangles in opposite directions and
 * interpolates the very same intersection as `a + (b − a)·t` on one side and as
 * `b + (a − b)·(1 − t)` on the other, which are the same real number and two
 * different doubles. A raw key would then name one edge twice, and exactly
 * those two triangles would disagree about splitting it — the seam this
 * function exists to prevent. Rounding to `NG_EDGE_KEY_M` folds the last bits
 * away, and the same rounding orders the pair so the name is direction-blind.
 *
 * Exported so the smoke can pin that behaviour on hand-built endpoints.
 */
export function ngEdgeKey(a: { x: number; z: number },
                          b: { x: number; z: number }): string {
  const ax = Math.round(a.x / NG_EDGE_KEY_M);
  const az = Math.round(a.z / NG_EDGE_KEY_M);
  const bx = Math.round(b.x / NG_EDGE_KEY_M);
  const bz = Math.round(b.z / NG_EDGE_KEY_M);
  return (ax < bx || (ax === bx && az <= bz))
    ? `${ax},${az}|${bx},${bz}`
    : `${bx},${bz}|${ax},${az}`;
}

/**
 * One triangle split at the marked edges — the three standard templates, and
 * every piece wound the way its parent was (a flipped piece would be culled
 * away and leave a hole in the ground).
 *
 * `mid[i]` belongs to the edge from vertex `i` to vertex `i + 1`.
 */
function ngSplitTriangle(t: readonly NgVert[], mid: readonly (NgVert | null)[],
                         out: NgVert[][]): void {
  const [a, b, c] = t;
  const [ab, bc, ca] = mid;
  if (ab && bc && ca) {                       // all three: four pieces
    out.push([a, ab, ca], [ab, b, bc], [ca, bc, c], [ab, bc, ca]);
    return;
  }
  if (ab && bc) { out.push([c, a, ab], [c, ab, bc], [ab, b, bc]); return; }
  if (bc && ca) { out.push([a, b, bc], [a, bc, ca], [ca, bc, c]); return; }
  if (ca && ab) { out.push([b, c, ca], [b, ca, ab], [a, ab, ca]); return; }
  if (ab) { out.push([a, ab, c], [ab, b, c]); return; }
  if (bc) { out.push([b, bc, a], [bc, c, a]); return; }
  if (ca) { out.push([c, ca, b], [ca, a, b]); return; }
  out.push([a, b, c]);
}

/**
 * Give a drape the distance-to-edge attribute it needs for the soft band, and
 * refine it wherever that distance cannot be interpolated.
 *
 * The input is the drape as it goes to the GPU today: a NON-INDEXED triangle
 * soup in world metres (`pos`), with UVs that are world metres as well, cut on
 * the relief grid and already lifted onto it. The output is the same surface
 * with more triangles in the fringe and one distance per vertex.
 *
 * WHY THE REFINEMENT EXISTS AT ALL. A painted area is triangulated by earcut:
 * on a flat world it is a handful of huge triangles whose corners ALL lie on
 * the ring, so every one of them carries distance 0 at every corner — a
 * linearly interpolated attribute would report "edge" over the whole face and
 * the area would disappear. On a relieved world the grid cut bounds the damage
 * to one cell, which is up to 32 m of it. Neither is a picture anybody wants,
 * and neither can be fixed in the shader: the fragment does not know the ring.
 *
 * The cost is paid where the fringe is. Deep inside an area nothing is split
 * (the gate), and along a straight run of ring nothing is split either (the
 * distance is exactly linear there) — the extra triangles follow the corners
 * and the chords, which is a length, not an area.
 */
export function ngRefineEdgeBand(pos: readonly number[], uv: readonly number[] | null,
                                 ring: readonly NgPoint2[] | null | undefined): NgBandMesh {
  // The ring as the distance can use it: junk corners out, everything else in
  // the order it was drawn. `[]` means "no ring" and leaves every distance at
  // Infinity, i.e. an opaque drape with the hard edge of before.
  const edges: NgPoint2[] = (ring ?? []).filter((p): p is NgPoint2 => Array.isArray(p)
    && Number.isFinite(p[0]) && Number.isFinite(p[1]));
  let tris: NgVert[][] = [];
  for (let t = 0, k = 0; t + 8 < pos.length; t += 9, k += 6) {
    tris.push([0, 1, 2].map((n) => {
      const x = pos[t + n * 3];
      const z = pos[t + n * 3 + 2];
      return { x, y: pos[t + n * 3 + 1], z,
               u: uv ? uv[k + n * 2] : 0, v: uv ? uv[k + n * 2 + 1] : 0,
               d: ngEdgeDistance(x, z, edges) };
    }));
  }
  for (let pass = 0; pass < NG_EDGE_PASSES && tris.length < NG_EDGE_MAX_TRIS; pass += 1) {
    // WHICH EDGES GET A VERTEX — decided for the whole drape before a single
    // triangle is cut, so that both owners of an edge cut it alike (see
    // `ngEdgeKey`). An edge earns its vertex either on its own account or
    // because a triangle it belongs to misses in the middle.
    const marks = new Map<string, NgVert | null>();
    for (const tri of tris) {
      for (let i = 0; i < 3; i += 1) {
        const a = tri[i];
        const b = tri[(i + 1) % 3];
        const key = ngEdgeKey(a, b);
        if (!marks.has(key)) marks.set(key, ngSplitEdge(a, b, edges));
      }
    }
    for (const tri of tris) {
      if (!ngSplitInside(tri, edges)) continue;
      for (let i = 0; i < 3; i += 1) {
        const a = tri[i];
        const b = tri[(i + 1) % 3];
        const key = ngEdgeKey(a, b);
        if (!marks.get(key) && ngLongEnough(a, b)) marks.set(key, ngMidVert(a, b, edges));
      }
    }
    const next: NgVert[][] = [];
    let split = false;
    for (const tri of tris) {
      const mid = [marks.get(ngEdgeKey(tri[0], tri[1])) ?? null,
                   marks.get(ngEdgeKey(tri[1], tri[2])) ?? null,
                   marks.get(ngEdgeKey(tri[2], tri[0])) ?? null];
      if (!mid[0] && !mid[1] && !mid[2]) { next.push(tri); continue; }
      split = true;
      ngSplitTriangle(tri, mid, next);
    }
    tris = next;
    if (!split) break;
  }
  const outPos: number[] = [];
  const outUv: number[] = [];
  const outDist: number[] = [];
  for (const tri of tris) {
    for (const p of tri) {
      outPos.push(p.x, p.y, p.z);
      outUv.push(p.u, p.v);
      // A ring that has no edges leaves the distance at Infinity, and an
      // Infinity in a vertex buffer is a black ground on some drivers: the
      // opaque distance says the same thing in a number the GPU can add to.
      outDist.push(Number.isFinite(p.d) ? p.d : NG_EDGE_OPAQUE_M);
    }
  }
  return { pos: outPos, uv: uv ? outUv : null, dist: outDist };
}

// ── Who is left out ─────────────────────────────────────────────────────────

/**
 * Does this surface class carry its own shader already?
 *
 * Water and ice are ONE surface in `@anima/scene-render/materials.ts` (ice is
 * water that stands still), and that surface is a full shader of its own:
 * scrolling normal maps, a sky fresnel, a roughness mask. Blending a second
 * sample of a water texture into it and then shading it by the ground's relief
 * would fight every one of those — the ripples are the surface, not the
 * texture under them.
 *
 * The predicate is here rather than beside the patch so the smoke can ask it
 * directly instead of reading a regular expression out of `ground.ts`.
 */
export function isWaterClass(cls: string | null | undefined): boolean {
  const c = (cls || '').toLowerCase();
  return c === 'water' || c === 'ice';
}
