/**
 * Pure maths of the far backdrop (§ A17): WHERE the mountain silhouette has a
 * ridge and how high it stands there.
 *
 * Everything here is a function of its arguments: no Three.js, no module
 * state, no DOM, no clock — the same discipline as `scene/scatterLod.ts` and
 * `game/walk.ts`, and what lets `client3d/scripts/smoke_backdrop_math.mjs`
 * transpile this file on its own and check it against hand-derived numbers.
 * It must stay IMPORT-FREE. `scene/backdrop.ts` is the other half: it needs
 * `three` and turns the profile below into triangles, which is why the two are
 * separate files rather than one module with a pure head — an `import * as
 * THREE` at the top would put the whole file out of the smoke's reach.
 *
 * THE ANGLE IS THE CONTRACT'S FIGURE COMPASS (§ A1.8): 0 = south, 90 = east,
 * 180 = north, 270 = west, so a ground direction is `(x, z) = (sin a, cos a)`
 * with x growing east and z growing south. The server hands the arcs over
 * already resolved to degrees (`app/core/backdrop.py`) — this module never
 * translates a compass point, it only clips a ring to the ranges it is given.
 * An arc never wraps: `0 <= start < 360` and `start < end <= start + 360`, so
 * a range across north arrives as `[337.5, 382.5]` and is swept from start to
 * end. The full ring is the single arc `[0, 360]`.
 *
 * THE RIDGE IS A RING TABLE, NOT A STREAM ALONG THE ARC. Every layer draws
 * `segments` heights for the WHOLE circle first, and an arc then keeps the
 * nodes that fall inside it. That is what makes the picture stable while an
 * admin edits the setting: widening "N" to "N,NE" adds ridge to the east and
 * leaves every peak already standing exactly where it stood. Drawing along
 * the arc instead would reshuffle the whole range on every edit — the same
 * reasoning as the scatter sampler, where a footprint SUBTRACTS props instead
 * of moving them.
 *
 * WHAT IS NOT DECIDED HERE: the geometry, the colours and the two layers'
 * radii in the scene. The radius rule IS here (`layerRadiusM`) because it is
 * arithmetic the smoke has to be able to check; laying the vertices out is
 * `backdrop.ts`.
 */

/** Radius of the FRONT ridge, in metres, measured from the camera target the
 *  ring hangs on. 380 m sits in the middle of the engine's fog band
 *  (220 … 520 m), so the silhouette is hazed by the scene fog itself and no
 *  engine setting has to move for it. */
export const BACKDROP_DIST_M = 380;

/** How much farther out the BACK ridge stands (metres). The two rings at
 *  different radii are the whole parallax effect: panning the camera slides
 *  the near ridge across the far one. */
export const BACKDROP_LAYER_GAP_M = 60;

/** Extra height share of the back ridge. Farther away and yet TALLER on
 *  screen is what reads as "the range goes on behind" — a back layer at the
 *  same height would simply disappear behind the front one. */
export const BACKDROP_LAYER_HEIGHT_K = 0.25;

/** How many ridges are drawn. Two: one is a wall, three cost draw calls for a
 *  silhouette nobody can tell apart. */
export const BACKDROP_LAYERS = 2;

/** Ring resolution: nodes over the full 360°. 96 nodes = one ridge point
 *  every 3.75°, which at 380 m is a peak roughly every 25 m — coarse enough
 *  to stay low-poly (a full ring is ~2 × 96 quads) and fine enough that the
 *  silhouette does not read as a polygon. */
export const BACKDROP_SEGMENTS = 96;

/** Lowest peak, as a share of the authored height. A ridge whose peaks run
 *  from 0 to full height looks like teeth; 0.45 keeps a mountain range. */
export const RIDGE_MIN_SHARE = 0.45;

/** How far into an arc the ridge climbs out of the ground, in degrees. An arc
 *  that simply stopped would end in a vertical wall as tall as the range. */
export const RIDGE_TAPER_DEG = 12;

/** Height clamps, the client's own copy of the server's (§ A17). The server
 *  validates, and this re-clamps anyway: the payload is data from the network,
 *  and a NaN height would put every vertex of the ring at NaN — a silhouette
 *  that vanishes completely rather than one that is a bit too tall. */
export const BACKDROP_HEIGHT_MIN_M = 20;
export const BACKDROP_HEIGHT_MAX_M = 300;
export const BACKDROP_HEIGHT_DEFAULT_M = 120;

/** One sampled ridge point: a direction, how high the ridge stands there, and
 *  which of the two rings it belongs to. */
export interface RidgePoint {
  /** degrees on the figure compass; may exceed 360 inside a wrap-free arc */
  angleDeg: number;
  /** metres above y = 0; 0 at the two ends of an arc (the taper) */
  peakH: number;
  /** 0 = front ring, 1 = back ring */
  layer: number;
}

/**
 * Deterministic PRNG over a string seed: FNV-1a for the state, xorshift for
 * the stream. Copied — deliberately, not imported — from
 * `packages/scene-render/src/scatter.ts` (`seededRandom`), which is the repo's
 * one RNG body; this module has to stay import-free (see the header) and the
 * eight lines are cheaper than the coupling. Identical numbers for identical
 * seeds, so the copy can never drift into a different stream unnoticed: the
 * smoke pins the first draws of a known seed against the shared function.
 */
export function backdropRandom(seed: string): () => number {
  let h = 2166136261;
  for (let i = 0; i < seed.length; i += 1) {
    h ^= seed.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return () => {
    h = Math.imul(h ^ (h >>> 15), 2246822519);
    h = Math.imul(h ^ (h >>> 13), 3266489917);
    return ((h ^= h >>> 16) >>> 0) / 4294967296;
  };
}

/** Radius of a layer's ring in metres: front 380, back 440. */
export function layerRadiusM(layer: number): number {
  return BACKDROP_DIST_M + BACKDROP_LAYER_GAP_M * layer;
}

/**
 * Ground direction of a compass angle as `[x, z]` (§ A1.8): 0 = south →
 * `(0, 1)`, 90 = east → `(1, 0)`, 180 = north → `(0, −1)`, 270 = west →
 * `(−1, 0)`. The ONE place the client turns a backdrop angle into world axes —
 * `backdrop.ts` builds every vertex through it, so the ring cannot be mounted
 * against a second reading of the compass.
 */
export function ridgeDirection(angleDeg: number): [number, number] {
  const a = (angleDeg * Math.PI) / 180;
  return [Math.sin(a), Math.cos(a)];
}

/** Height factor of a layer: front 1, back 1.25. */
export function layerHeightFactor(layer: number): number {
  return 1 + BACKDROP_LAYER_HEIGHT_K * layer;
}

/** The authored height, made usable: junk becomes the default, everything
 *  else is clamped into [20; 300] m. */
export function clampBackdropHeightM(heightM: unknown): number {
  const h = typeof heightM === 'number' && Number.isFinite(heightM)
    ? heightM : BACKDROP_HEIGHT_DEFAULT_M;
  return Math.min(BACKDROP_HEIGHT_MAX_M, Math.max(BACKDROP_HEIGHT_MIN_M, h));
}

/** Classic Hermite ramp `3t² − 2t³` on an already normalised t. */
function smoothRamp(t: number): number {
  const x = t <= 0 ? 0 : t >= 1 ? 1 : t;
  return x * x * (3 - 2 * x);
}

/**
 * The ridge of ONE backdrop setting, both layers, ready to be turned into
 * triangle strips.
 *
 * Per layer:
 *   1. draw `segments` node heights for the whole circle,
 *        h_i = heightM · layerHeightFactor(layer)
 *              · (RIDGE_MIN_SHARE + (1 − RIDGE_MIN_SHARE) · r_i)
 *   2. for every arc, emit its START, then every ring node strictly inside
 *      it, then its END. Node angles are `i · 360/segments` and are looked up
 *      MODULO `segments`, so an arc running past 360 (`[292.5, 427.5]`) keeps
 *      sweeping into the same ring it started in.
 *   3. the two ends stand at peakH 0 and every inner node is multiplied by
 *      the taper `smoothRamp(min(a − start, end − a) / RIDGE_TAPER_DEG)`, so
 *      the range rises out of the ground instead of ending in a wall. A FULL
 *      ring (span ≥ 360) has no ends and is not tapered; it closes by
 *      emitting the first node again at +360.
 *
 * `rnd` exists for the smoke, exactly as `scatterInstances.rng` does: the
 * seeded stream cannot be simulated on paper, so the hand-derived cases feed a
 * fixed list of numbers. When it is given, BOTH layers draw from that one
 * stream in order (front first); the real path gives each layer its own seeded
 * stream so the two ridges are not the same shape scaled by 1.25.
 */
export function ridgeProfile(
  seed: number,
  arcs: ReadonlyArray<readonly [number, number]>,
  heightM: number,
  segments: number = BACKDROP_SEGMENTS,
  rnd?: () => number,
): RidgePoint[] {
  const h0 = clampBackdropHeightM(heightM);
  // A ring needs at least a triangle's worth of nodes, and beyond a few
  // hundred the silhouette gains nothing but vertices.
  const n = Number.isFinite(segments)
    ? Math.min(720, Math.max(8, Math.round(segments))) : BACKDROP_SEGMENTS;
  const step = 360 / n;
  const seedInt = Number.isFinite(seed) ? Math.trunc(seed) : 1;

  const out: RidgePoint[] = [];
  for (let layer = 0; layer < BACKDROP_LAYERS; layer += 1) {
    const draw = rnd ?? backdropRandom(`backdrop-${seedInt}-l${layer}`);
    const top = h0 * layerHeightFactor(layer);
    const nodes = new Array<number>(n);
    for (let i = 0; i < n; i += 1) {
      nodes[i] = top * (RIDGE_MIN_SHARE + (1 - RIDGE_MIN_SHARE) * draw());
    }

    for (const arc of arcs ?? []) {
      const start = arc?.[0];
      const end = arc?.[1];
      if (!Number.isFinite(start) || !Number.isFinite(end)) continue;
      const span = end - start;
      if (span <= 0) continue;
      const wrap = (i: number) => ((i % n) + n) % n;

      if (span >= 360 - 1e-9) {
        // A FULL ring: every node once, in ring order from the first node at
        // or after `start`, plus the first one again at +360 — without that
        // closing sample the strip leaves a gap one segment wide.
        const i0 = Math.ceil(start / step - 1e-9);
        for (let k = 0; k <= n; k += 1) {
          out.push({ angleDeg: (i0 + k) * step, peakH: nodes[wrap(i0 + k)], layer });
        }
        continue;
      }

      // An OPEN arc: its two ends, and the ring nodes strictly inside it. The
      // bounds are nudged by an epsilon so a node sitting exactly ON an end is
      // not emitted twice — the end sample owns that angle, and at peakH 0.
      out.push({ angleDeg: start, peakH: 0, layer });
      const first = Math.ceil((start + 1e-9) / step);
      const last = Math.floor((end - 1e-9) / step);
      for (let i = first; i <= last; i += 1) {
        const a = i * step;
        const dEnd = Math.min(a - start, end - a);
        out.push({
          angleDeg: a,
          peakH: nodes[wrap(i)] * smoothRamp(dEnd / RIDGE_TAPER_DEG),
          layer,
        });
      }
      out.push({ angleDeg: end, peakH: 0, layer });
    }
  }
  return out;
}
