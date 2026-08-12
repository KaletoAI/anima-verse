#!/usr/bin/env node
/**
 * Smoke check for the pure scatter maths shared by the 3D client and the map
 * editor — `packages/scene-render/src/scatter.ts`.
 *
 * Usage:  node client3d/scripts/smoke_scatter_math.mjs
 *
 * Same discipline as `smoke_ground_math.mjs` and `scripts/smoke_scene_recipe.py`:
 * every expected number below is derived BY HAND in this header and NEVER
 * recorded from the current output. A check that only pins today's result
 * proves nothing.
 *
 * `scatter.ts` has NO import at all (see its header), so a plain esbuild
 * transpile is enough — no bundler, no stand-ins.
 *
 * ============================================================================
 * (A) propGroundFit — a prop STANDS on the ground (finding B16)
 * ============================================================================
 * A GLB carries whatever origin its author chose; the placeholder cone it
 * replaces is built with its base at y = 0. The fit is arithmetic on the
 * mesh's bounding box:
 *
 *     scale   = targetH / (maxY - minY)      when a target height is asked for
 *     offsetY = -minY * scale
 *
 * so afterwards the box runs from y = 0 to y = targetH.
 *
 * (A1) THE REPORTED CASE. A 2 m tree modelled around its centre:
 *      minY = -1, maxY = +1, no target height.
 *      scale = 1 (nothing asked), offsetY = -(-1) * 1 = +1.
 *      -> the tree rises by exactly the 1 m it used to stand too deep, and
 *         its base sits at 0. Before the fix the offset was 0 and half the
 *         2 m tree was underground — which is the finding, word for word.
 *
 * (A2) THE SAME TREE with height_m = 4:
 *      height = 1 - (-1) = 2, scale = 4/2 = 2,
 *      offsetY = -(-1) * 2 = +2.
 *      -> after scaling the lowest point is at -2, the lift puts it at 0 and
 *         the top at -2 + 2*2 = ... in box terms: min 0, max 4. A 4 m tree.
 *
 * (A3) AN AUTHOR WHO ALREADY PUT THE BASE AT 0: minY = 0, maxY = 3.
 *      scale = 1, offsetY = -0 = 0 -> nothing moves. The fix must not
 *      "correct" a prop that was right.
 *
 * (A4) A PROP HANGING ABOVE ITS ORIGIN: minY = 0.5, maxY = 2.5.
 *      scale = 1, offsetY = -0.5 -> it comes DOWN onto the ground. The rule
 *      is "lowest point at 0", not "lift everything".
 *      With height_m = 1: height = 2, scale = 0.5,
 *      offsetY = -0.5 * 0.5 = -0.25 -> box from 0 to 1.
 *
 * (A5) A FLAT PROP (a decal plane): minY = maxY = 0.7.
 *      height = 0, so no scale is possible however tall the target — scale
 *      stays 1 and offsetY = -0.7 lays it on the ground. An infinite scale
 *      would make it vanish.
 *      Checked with height_m = 3 as well: still scale 1, offsetY -0.7.
 *
 * (A6) JUNK BOX (a geometry with no vertices gives NaN bounds): scale 1,
 *      offsetY 0 — the prop stands where the file put it rather than at NaN,
 *      which would remove every instance from the screen at once.
 *
 * (A7) A target height that is not a height (0, negative, NaN, null) is not a
 *      request: scale stays 1, only the grounding lift applies. Derived from
 *      minY = -1, maxY = 1 -> offsetY = +1 in every one of those cases.
 *
 * ============================================================================
 * (B) pointInFootprint — the exclusion of finding B18
 * ============================================================================
 * A footprint is a SQUARE of edge `plan_width_m` centred on `pos_x/pos_z` and
 * turned by `yaw_deg` (§ A1.1). The test turns the point into the square's own
 * frame (a rotation by -yaw) and compares against half the edge.
 *
 * (B1) AXIS-ALIGNED, centre (10, 10), edge 4 -> the square runs 8..12 on both
 *      axes.
 *        (10, 10)   centre                      -> inside
 *        (11.9, 8.1) just inside the corner      -> inside
 *        (12.1, 10) 0.1 m past the east edge     -> outside
 *        (10, 7.9)  0.1 m short of the north edge-> outside
 *        (12, 12)   exactly the corner           -> inside (<= half)
 *
 * (B2) TURNED BY 45 deg, centre (0, 0), edge 2 (half 1). The square's corners
 *      now point along the axes at distance sqrt(2) = 1.41421356..., and the
 *      EDGE midpoints sit at distance 1 along the diagonals.
 *        (1.3, 0)      -> inside  (a corner direction; 1.3 < 1.414)
 *        (1.5, 0)      -> outside (past the corner)
 *        (0.8, 0.8)    -> local (via -45 deg): x = 0.8*cos45 + 0.8*sin45
 *                        ... careful, the mapping is
 *                        lx = dx*cos - dz*sin, lz = dx*sin + dz*cos
 *                        with cos = sin = 0.70710678 for yaw 45:
 *                        lx = 0.8*0.7071 - 0.8*0.7071 = 0
 *                        lz = 0.8*0.7071 + 0.8*0.7071 = 1.13137
 *                        |lz| = 1.131 > 1 -> OUTSIDE. The point lies past the
 *                        edge midpoint on the diagonal, which is exactly what
 *                        a turned square does that an axis-aligned box test
 *                        would get wrong.
 *        (0.7, 0.7)    -> lz = 0.98995 <= 1 -> inside.
 *
 * (B3) NOT A SQUARE AT ALL — never blocks anything:
 *        unplaced (pos_x null), edge 0, edge negative, edge missing, NaN
 *        centre. All false, for the centre point itself.
 *
 * ============================================================================
 * (C) scatterInstances — the sampler, with a HAND-FED random stream
 * ============================================================================
 * The seeded PRNG cannot be simulated on paper, so the checks feed a fixed
 * list of numbers through `rng` and derive the points from the formula:
 *
 *     wanted = min(round(areaM2 / 100 * density), maxPoints)
 *     x   = minX + r * (maxX - minX)
 *     z   = minZ + r * (maxZ - minZ)      (the NEXT number)
 *     yaw = r * 2*pi                       (the NEXT one, ALWAYS drawn)
 *     reject when outside the ring or inside a footprint
 *
 * THREE numbers per candidate, drawn before the test even when the candidate
 * is thrown away. That is the point of (C2): every candidate keeps its place
 * in the stream, so a footprint SUBTRACTS the props it covers instead of
 * shifting everything behind it.
 *
 * THE SQUARE: (0,0) (20,0) (20,20) (0,20). Bounds 0..20 on both axes,
 * area 400 m2. With density 25 per 100 m2: wanted = round(400/100 * 25) = 100
 * — too many to write out, so the cases below cap with `maxPoints`.
 *
 * (C1) density 0.5 -> round(4 * 0.5) = 2 wanted. `triesPerPoint` 1 bounds the
 *      loop at 2 candidates, so the stream below is the WHOLE run — with the
 *      default budget the sampler would keep asking for a replacement after
 *      any rejection, which is right in the world and unreadable on paper.
 *      Stream:
 *        0.10, 0.20, 0.50   -> x = 0 + 0.10*20 = 2,  z = 0.20*20 = 4,
 *                              yaw = 0.50 * 2pi = pi, inside the square
 *        0.75, 0.25, 0.00   -> x = 15, z = 5, yaw = 0, inside
 *      -> [ {2, 4, pi}, {15, 5, 0} ]. Six numbers for two points.
 *
 * (C2) THE SAME STREAM with a footprint over the FIRST point: a location at
 *      (2, 4), yaw 0, edge 2 covers 1..3 by 3..5. The first candidate is
 *      inside it and is dropped — but it still cost its three numbers, so the
 *      second candidate is the very same 0.75/0.25/0.00 it was in (C1).
 *      Result: [ {15, 5, 0} ] — (C1) MINUS the covered point, nothing else
 *      moved (same `triesPerPoint` 1, so the two runs are the same two
 *      candidates). That is the whole promise of finding B18: a building clears the
 *      ground it stands on and does not rearrange the wood around it.
 *
 * (C3) A MISS OUTSIDE THE RING. Ring = the LOWER-LEFT TRIANGLE of that square,
 *      (0,0) (20,0) (0,20): area 200 m2, same 0..20 bounding box. With
 *      density 1 -> round(200/100 * 1) = 2 wanted.
 *      Stream 0.90, 0.90, 0.00 -> (18, 18): x + z = 36 > 20, OUTSIDE the
 *        triangle, rejected; the yaw number is spent all the same.
 *      Then 0.10, 0.10, 0.00 -> (2, 2) inside, yaw 0.
 *      Then 0.25, 0.25, 0.50 -> (5, 5) inside, yaw pi.
 *      -> [ {2, 2, 0}, {5, 5, pi} ].
 *
 * (C4) THE TRY BUDGET. Same triangle, wanted 2, `triesPerPoint` 1 -> 2 tries
 *      in total. A stream that misses twice (0.9/0.9 and 0.95/0.95, three
 *      numbers each) gives an EMPTY list instead of looping forever.
 *
 * (C5) NOTHING TO SCATTER: density 0, a negative density, an area of 0, a
 *      two-point "ring" and a density so low that `round` gives 0
 *      (400 m2 at 0.1 per 100 m2 -> round(0.4) = 0) all yield [].
 *
 * (C6) maxPoints CAPS the count: 400 m2 at density 25 wants 100, capped to 3.
 *      Fed with a stream of 9 numbers (three points), it returns exactly 3.
 *
 * (C7) DETERMINISM of the real path (a property, not a recorded value): the
 *      same seed gives an identical list twice, and `scatterSeed` differs per
 *      index, so entry 0 and entry 1 of one area do not stand in the same
 *      spots.
 */
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');
const SRC = join(ROOT, 'packages/scene-render/src/scatter.ts');

/** See the header: the module has no runtime import, so a transpile is all it
 *  takes. Should someone add one, this fails loudly — that is the alarm. */
async function loadScatter() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'scattermath-'));
  try {
    const source = await readFile(SRC, 'utf8');
    const out = esbuild.transformSync(source, { loader: 'ts', format: 'esm' });
    const file = join(dir, 'scatter.mjs');
    await writeFile(file, out.code, 'utf8');
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

let failed = 0;
let passed = 0;
function check(label, actual, expected, eps = 1e-9) {
  const ok = compare(actual, expected, eps);
  if (ok) {
    passed += 1;
    console.log(`  ok   ${label}`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}\n       expected ${JSON.stringify(expected)}`
      + `\n       actual   ${JSON.stringify(actual)}`);
  }
}
function compare(a, b, eps) {
  if (a === null || b === null) return a === b;
  if (typeof b === 'number') return typeof a === 'number' && Math.abs(a - b) <= eps;
  if (Array.isArray(b)) {
    return Array.isArray(a) && a.length === b.length
      && b.every((v, i) => compare(a[i], v, eps));
  }
  if (typeof b === 'object') {
    const keys = Object.keys(b);
    if (typeof a !== 'object' || a === null) return false;
    if (Object.keys(a).length !== keys.length) return false;
    return keys.every((k) => compare(a[k], b[k], eps));
  }
  return a === b;
}

/** A random stream from a fixed list — see section (C). Running past its end
 *  is a broken expectation, not a wrap-around, so it throws. */
function stream(values) {
  let i = 0;
  return () => {
    if (i >= values.length) throw new Error('scatter drew more numbers than the case feeds');
    const v = values[i];
    i += 1;
    return v;
  };
}

async function main() {
  const {
    propGroundFit, pointInFootprint, pointInRing, scatterInstances, scatterSeed,
  } = await loadScatter();

  const TAU = Math.PI * 2;
  const SQUARE = [[0, 0], [20, 0], [20, 20], [0, 20]];
  const TRIANGLE = [[0, 0], [20, 0], [0, 20]];

  console.log('\n(A) propGroundFit — the prop stands on the ground (B16)');
  check('A1 a 2 m tree around its centre rises by exactly 1 m',
    propGroundFit(-1, 1, null), { scale: 1, offsetY: 1 });
  check('A2 …and with height_m 4 it doubles and lifts by 2',
    propGroundFit(-1, 1, 4), { scale: 2, offsetY: 2 });
  check('A3 a prop already based at 0 is not "corrected"',
    propGroundFit(0, 3, null), { scale: 1, offsetY: 0 });
  check('A4 a prop hanging above its origin comes DOWN',
    propGroundFit(0.5, 2.5, null), { scale: 1, offsetY: -0.5 });
  check('A4 …and scales to a 1 m target from there',
    propGroundFit(0.5, 2.5, 1), { scale: 0.5, offsetY: -0.25 });
  check('A5 a flat prop lies on the ground instead of scaling to infinity',
    propGroundFit(0.7, 0.7, null), { scale: 1, offsetY: -0.7 });
  check('A5 …even when a target height is asked for',
    propGroundFit(0.7, 0.7, 3), { scale: 1, offsetY: -0.7 });
  check('A6 a NaN box leaves the prop where the file put it',
    propGroundFit(NaN, NaN, 2), { scale: 1, offsetY: 0 });
  for (const bad of [0, -2, NaN, null, undefined, 'tall']) {
    check(`A7 target height ${JSON.stringify(bad)} is no request — lift only`,
      propGroundFit(-1, 1, bad), { scale: 1, offsetY: 1 });
  }

  console.log('\n(B) pointInFootprint — footprints stay clear (B18)');
  const fp = { pos_x: 10, pos_z: 10, yaw_deg: 0, plan_width_m: 4 };
  check('B1 the centre is inside', pointInFootprint(fp, 10, 10), true);
  check('B1 just inside the corner', pointInFootprint(fp, 11.9, 8.1), true);
  check('B1 0.1 m past the east edge', pointInFootprint(fp, 12.1, 10), false);
  check('B1 0.1 m short of the north edge', pointInFootprint(fp, 10, 7.9), false);
  check('B1 exactly the corner counts as inside',
    pointInFootprint(fp, 12, 12), true);
  const turned = { pos_x: 0, pos_z: 0, yaw_deg: 45, plan_width_m: 2 };
  check('B2 1.3 m along a corner direction is inside a 45 deg square',
    pointInFootprint(turned, 1.3, 0), true);
  check('B2 1.5 m is past that corner', pointInFootprint(turned, 1.5, 0), false);
  check('B2 (0.8, 0.8) is past the edge midpoint on the diagonal',
    pointInFootprint(turned, 0.8, 0.8), false);
  check('B2 (0.7, 0.7) is still inside', pointInFootprint(turned, 0.7, 0.7), true);
  check('B3 an unplaced location blocks nothing',
    pointInFootprint({ pos_x: null, pos_z: null, yaw_deg: 0, plan_width_m: 4 }, 0, 0), false);
  check('B3 a zero edge blocks nothing',
    pointInFootprint({ pos_x: 0, pos_z: 0, yaw_deg: 0, plan_width_m: 0 }, 0, 0), false);
  check('B3 a negative edge blocks nothing',
    pointInFootprint({ pos_x: 0, pos_z: 0, yaw_deg: 0, plan_width_m: -5 }, 0, 0), false);
  check('B3 a missing edge blocks nothing',
    pointInFootprint({ pos_x: 0, pos_z: 0 }, 0, 0), false);
  check('B3 a NaN centre blocks nothing',
    pointInFootprint({ pos_x: NaN, pos_z: 0, yaw_deg: 0, plan_width_m: 4 }, 0, 0), false);

  console.log('\n  pointInRing — the even-odd rule both sides share');
  check('the centre of the square is inside', pointInRing(10, 10, SQUARE), true);
  check('a point outside it is not', pointInRing(25, 10, SQUARE), false);
  check('(18, 18) is outside the lower-left triangle',
    pointInRing(18, 18, TRIANGLE), false);
  check('…and (2, 2) is inside it', pointInRing(2, 2, TRIANGLE), true);

  console.log('\n(C) scatterInstances — the sampler');
  check('C1 two points out of six hand-fed numbers',
    scatterInstances({
      ring: SQUARE, areaM2: 400, densityPer100m2: 0.5, seed: 's',
      triesPerPoint: 1,
      rng: stream([0.10, 0.20, 0.50, 0.75, 0.25, 0.00]),
    }),
    [{ x: 2, z: 4, yaw: Math.PI }, { x: 15, z: 5, yaw: 0 }]);
  check('C2 a footprint SUBTRACTS the covered point — the rest is (C1) verbatim',
    scatterInstances({
      ring: SQUARE, areaM2: 400, densityPer100m2: 0.5, seed: 's',
      footprints: [{ pos_x: 2, pos_z: 4, yaw_deg: 0, plan_width_m: 2 }],
      triesPerPoint: 1,
      rng: stream([0.10, 0.20, 0.50, 0.75, 0.25, 0.00]),
    }),
    [{ x: 15, z: 5, yaw: 0 }]);
  check('C3 a candidate outside the ring costs its three numbers all the same',
    scatterInstances({
      ring: TRIANGLE, areaM2: 200, densityPer100m2: 1, seed: 's',
      rng: stream([0.90, 0.90, 0.00, 0.10, 0.10, 0.00, 0.25, 0.25, 0.50]),
    }),
    [{ x: 2, z: 2, yaw: 0 }, { x: 5, z: 5, yaw: Math.PI }]);
  check('C4 the try budget ends the loop instead of hanging',
    scatterInstances({
      ring: TRIANGLE, areaM2: 200, densityPer100m2: 1, seed: 's',
      triesPerPoint: 1,
      rng: stream([0.90, 0.90, 0.00, 0.95, 0.95, 0.00]),
    }), []);
  check('C5 density 0 scatters nothing',
    scatterInstances({ ring: SQUARE, areaM2: 400, densityPer100m2: 0, seed: 's' }), []);
  check('C5 a negative density scatters nothing',
    scatterInstances({ ring: SQUARE, areaM2: 400, densityPer100m2: -3, seed: 's' }), []);
  check('C5 an area of 0 scatters nothing',
    scatterInstances({ ring: SQUARE, areaM2: 0, densityPer100m2: 5, seed: 's' }), []);
  check('C5 a two-point ring scatters nothing',
    scatterInstances({ ring: [[0, 0], [1, 1]], areaM2: 400, densityPer100m2: 5, seed: 's' }), []);
  check('C5 a density that rounds to zero scatters nothing',
    scatterInstances({ ring: SQUARE, areaM2: 400, densityPer100m2: 0.1, seed: 's' }), []);
  check('C6 maxPoints caps the count at 3',
    scatterInstances({
      ring: SQUARE, areaM2: 400, densityPer100m2: 25, seed: 's', maxPoints: 3,
      rng: stream([0.1, 0.1, 0, 0.2, 0.2, 0.25, 0.3, 0.3, 0.5]),
    }),
    [{ x: 2, z: 2, yaw: 0 }, { x: 4, z: 4, yaw: TAU * 0.25 },
     { x: 6, z: 6, yaw: Math.PI }]);

  console.log('\n  C7 determinism of the seeded path (a property, not a record)');
  const opts = { ring: SQUARE, areaM2: 400, densityPer100m2: 2 };
  const a1 = scatterInstances({ ...opts, seed: scatterSeed('ta_1', 0) });
  const a2 = scatterInstances({ ...opts, seed: scatterSeed('ta_1', 0) });
  const b1 = scatterInstances({ ...opts, seed: scatterSeed('ta_1', 1) });
  check('the same seed gives the identical list', a1, a2);
  check('…and it is not empty', a1.length, 8);
  check('a second entry of the same area stands elsewhere',
    JSON.stringify(a1) !== JSON.stringify(b1), true);
  check('the seed is area- and index-stable',
    scatterSeed('ta_1', 2), 'terrain:scatter:ta_1:2');

  console.log(`\n${passed} ok, ${failed} failed`);
  process.exit(failed ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
