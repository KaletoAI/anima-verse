#!/usr/bin/env node
/**
 * Smoke check for the pure maths of the FAR BACKDROP (§ A17): the ridge
 * profile of `client3d/src/scene/backdropProfile.ts` — where the mountain
 * silhouette has a peak, how high it stands there, and how the two rings are
 * offset against each other.
 *
 * Usage:  node client3d/scripts/smoke_backdrop_math.mjs
 *
 * Same discipline as `smoke_scatter_math.mjs` and `scripts/smoke_scene_recipe.py`:
 * every expected number below is derived BY HAND in this header and NEVER
 * recorded from the current output. A check that only pins today's result
 * proves nothing.
 *
 * The module under test is IMPORT-FREE by design (its header says so), so a
 * plain esbuild transpile is enough — the same loader the scatter and relief
 * smokes use, no bundler and no stand-ins. That is also the reason the pure
 * half is its own file: `scene/backdrop.ts` needs `three` for its triangles
 * and could not be loaded here at all.
 *
 * ============================================================================
 * THE FORMULA, once
 * ============================================================================
 * Per layer L (0 = front, 1 = back) the ring carries `segments` nodes at the
 * angles i · 360/segments, and
 *
 *     h_i   = heightM · f(L) · ( 0.45 + 0.55 · r_i )     f(L) = 1 + 0.25·L
 *     R(L)  = 380 + 60 · L                               (metres)
 *
 * with r_i the i-th number of the layer's stream. An OPEN arc [s, e] emits
 *
 *     (s, 0) · every node angle strictly inside · (e, 0)
 *
 * and multiplies each inner node by the taper
 *
 *     ramp( min(a − s, e − a) / 12 ),  ramp(t) = 3t² − 2t³ clamped to [0,1]
 *
 * so the range climbs out of the ground at both ends instead of ending in a
 * wall. A FULL ring (span ≥ 360) has no ends, is not tapered, and repeats its
 * first node at +360 to close the strip.
 *
 * The hand cases feed `rnd` — the same device `scatterInstances.rng` uses —
 * because a seeded xorshift cannot be simulated on paper. ONE stream serves
 * both layers in order (front's `segments` numbers first).
 *
 * ============================================================================
 * (A) THE TWO LAYER OFFSETS — the parallax of the design decision
 * ============================================================================
 * (A1) R(0) = 380 + 60·0 = 380 m, R(1) = 380 + 60·1 = 440 m.
 * (A2) f(0) = 1, f(1) = 1 + 0.25 = 1.25.
 * (A3) With the SAME random number both rings differ by exactly that factor:
 *      r = 1, heightM = 100 -> front 100 · 1 · (0.45 + 0.55) = 100 m,
 *      back 100 · 1.25 · 1 = 125 m.
 *
 * ============================================================================
 * (B) THE FULL RING — [0, 360], segments 8 (step 45°), heightM 100, r ≡ 1
 * ============================================================================
 * Nodes: 0, 45, 90, …, 315 — eight of them, each at 100 m (front). No taper.
 * The ring closes with the first node again at 360, so the layer has 9 points
 * and 8 quads:
 *   front [ (0,100) (45,100) (90,100) (135,100) (180,100) (225,100)
 *           (270,100) (315,100) (360,100) ]
 *   back  the same angles at 125 m.
 * 18 points in total — the profile carries BOTH layers.
 *
 * ============================================================================
 * (C) ARC CLIPPING — "N" is [157.5, 202.5] (§ A17), segments 8, r ≡ 1
 * ============================================================================
 * ceil(157.5/45) = 4 and floor(202.5/45) = 4 (the ends are nudged off the
 * node grid by an epsilon), so exactly ONE node lies inside: 180°.
 *   at 180: min(180−157.5, 202.5−180) = 22.5° ≥ 12 -> ramp = 1 -> 100 m
 * -> front [ (157.5, 0) (180, 100) (202.5, 0) ], back the same at 125 m.
 * The ring is 45° of range in the north and nothing anywhere else, which is
 * the whole point of authoring an arc.
 *
 * ============================================================================
 * (D) AN ARC PAST 360 — [292.5, 427.5] ("SE,S,SW"), segments 8
 * ============================================================================
 * § A17 forbids a wrapped arc: a run across 0 arrives as end > 360. The node
 * indices are taken MODULO the ring, so the sweep continues into the same
 * table it started in.
 * Front stream r = [1, 0, 1, 1, 1, 1, 1, 0.5] gives the node heights
 *   i:      0    1   2    3    4    5    6    7
 *   a:      0   45  90  135  180  225  270  315
 *   h:    100   45 100  100  100  100  100  72.5      (0.45+0.55·0 = 0.45,
 *                                                      0.45+0.55·0.5 = 0.725)
 * ceil(292.5/45) = 7, floor(427.5/45) = 9 -> i = 7, 8, 9:
 *   i=7  a=315  node 7          -> 72.5   (d = min(22.5, 112.5) = 22.5 -> 1)
 *   i=8  a=360  node 8 mod 8 = 0 -> 100    (d = min(67.5, 67.5) -> 1)
 *   i=9  a=405  node 9 mod 8 = 1 -> 45     (d = min(112.5, 22.5) = 22.5 -> 1)
 * -> front [ (292.5,0) (315,72.5) (360,100) (405,45) (427.5,0) ].
 * The back layer is fed r ≡ 1 (its own eight numbers) -> 125 m at all three.
 *
 * ============================================================================
 * (E) THE TAPER — a narrow arc [0, 20], segments 72 (step 5°), r ≡ 1
 * ============================================================================
 * Nodes inside: 5, 10, 15. Node height 100 m, and with ramp(t) = 3t² − 2t³:
 *   a=5 :  d = min(5, 15) = 5,  t = 5/12
 *          ramp = 3·25/144 − 2·125/1728 = 900/1728 − 250/1728 = 650/1728
 *               = 325/864 = 0.376157407407…      -> 37.6157407407… m
 *   a=10:  d = min(10, 10) = 10, t = 10/12 = 5/6
 *          ramp = 3·25/36 − 2·125/216 = 450/216 − 250/216 = 200/216 = 25/27
 *               = 0.925925925926…                -> 92.5925925926… m
 *   a=15:  d = min(15, 5) = 5   -> the same 37.6157… m as a=5 (symmetric)
 * plus the two ends at 0. A ridge that comes out of the ground and goes back
 * into it.
 *
 * ============================================================================
 * (F) THE CLAMPS — the client re-clamps what the server already validated
 * ============================================================================
 * (F1) 5 m -> 20 m (the floor), 1000 m -> 300 m (the ceiling), 120 -> 120,
 *      NaN / undefined / a string -> the default 120.
 * (F2) Through the profile ("N", r ≡ 1): heightM 5 gives a 20 m front peak
 *      and a 20·1.25 = 25 m back peak; heightM 1000 gives 300 / 375 m.
 * (F3) THE LOWEST PEAK, r ≡ 0: 100 · (0.45 + 0) = 45 m front, and
 *      100 · 1.25 · 0.45 = 56.25 m back. No peak is ever lower than that —
 *      a ridge running down to 0 would look like teeth, not like a range.
 *
 * ============================================================================
 * (G) NOTHING TO DRAW / JUNK
 * ============================================================================
 * No arcs, an empty arc (start = end), a reversed one (end < start) and a
 * non-finite one all yield an EMPTY profile — never a ring "just in case".
 * `segments` is bounded into [8, 720]: 2 becomes 8 (a full ring of 9 points
 * per layer), NaN falls back to the default 96 (97 points per layer).
 *
 * ============================================================================
 * (H) THE COMPASS — § A1.8, the one figure compass of this contract
 * ============================================================================
 * direction(a) = (sin a, cos a) with x east and z south:
 *   0° -> ( 0,  1)  south     90° -> ( 1, 0)  east
 * 180° -> ( 0, −1)  north    270° -> (−1, 0)  west
 * and 45° -> (0.7071067811865476, 0.7071067811865476), south-east.
 *
 * ============================================================================
 * (I) DETERMINISM AND THE COPIED RNG
 * ============================================================================
 * The real path (no `rnd`) is a pure function of the seed: the same call twice
 * is the same list, a different seed is a different list, and the two layers
 * draw from their own streams — the back ridge is NOT the front one scaled by
 * 1.25. Every peak of a full ring stays inside [0.45·H·f, H·f] by the formula.
 * `backdropRandom` is a deliberate COPY of `seededRandom` in
 * `packages/scene-render/src/scatter.ts` (the module has to stay import-free);
 * the check loads BOTH and compares their streams, so the copy cannot drift
 * into different numbers unnoticed.
 *
 * ============================================================================
 * (J) THE RED COUNTER-CHECKS — mutants that must fail
 * ============================================================================
 * (J1) The layer HEIGHT offset removed (f(L) ≡ 1): the back ring answers 100 m
 *      in case (A3)/(B) where the real rule answers 125 — the two ridges would
 *      be one silhouette, and the back one would never be seen.
 * (J2) The layer RADIUS offset removed (R(L) ≡ 380): both rings stand at
 *      380 m, so there is no parallax left at all.
 * (J3) The modulo of the node lookup removed: case (D)'s 405° reads past the
 *      end of the table and gives NaN instead of 45 m — a wrap-free arc would
 *      tear a hole into the ring.
 * (J4) The compass mirrored (cos/sin swapped): 180° becomes (cos, sin) =
 *      (−1, 0), i.e. WEST — an arc authored as "N" would stand in the west.
 */
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');
const SRC = join(ROOT, 'client3d/src/scene/backdropProfile.ts');
const SCATTER_SRC = join(ROOT, 'packages/scene-render/src/scatter.ts');

/** Transpile one import-free TypeScript module and load it. `mutate` builds
 *  the red counter-checks; a mutation that changes nothing is an error, not a
 *  quietly passing test. */
async function loadTs(src, mutate) {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'backdrop-'));
  try {
    const original = await readFile(src, 'utf8');
    const source = mutate ? mutate(original) : original;
    if (mutate && source === original) {
      throw new Error('the mutant changed nothing — the counter-check would be vacuous');
    }
    const out = esbuild.transformSync(source, { loader: 'ts', format: 'esm' });
    const file = join(dir, 'module.mjs');
    await writeFile(file, out.code, 'utf8');
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

let failed = 0;
let passed = 0;
function check(label, actual, expected, eps = 1e-9) {
  const ok = typeof actual === 'number' && Math.abs(actual - expected) <= eps;
  if (ok) {
    passed += 1;
    console.log(`  ok   ${label} = ${actual}`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}\n       expected ${expected}\n       actual   ${actual}`);
  }
}
function checkEq(label, actual, expected) {
  const a = JSON.stringify(actual);
  const b = JSON.stringify(expected);
  if (a === b) {
    passed += 1;
    console.log(`  ok   ${label} = ${a}`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}\n       expected ${b}\n       actual   ${a}`);
  }
}
function checkNotEq(label, actual, forbidden) {
  const a = JSON.stringify(actual);
  const b = JSON.stringify(forbidden);
  if (a !== b) {
    passed += 1;
    console.log(`  ok   ${label} (is ${a}, not ${b})`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}\n       must NOT be ${b}`);
  }
}

/** A stream of fixed numbers, as the hand cases feed it. Runs dry loudly: a
 *  case that draws more numbers than it wrote down is a case nobody derived. */
function stream(...values) {
  let i = 0;
  return () => {
    if (i >= values.length) throw new Error(`the hand stream ran dry after ${values.length}`);
    return values[i++];
  };
}
/** `n` copies of one number — the "every peak the same" cases. */
function flat(value, n) {
  return stream(...new Array(n).fill(value));
}
/** The [angle, height] pairs of one layer, rounded to 1e-9 so a
 *  0.30000000000000004 never reads as a failure of the maths. */
function layerPairs(profile, layer) {
  return profile.filter((p) => p.layer === layer)
    .map((p) => [round(p.angleDeg), round(p.peakH)]);
}
function round(v) {
  return Number.isFinite(v) ? Math.round(v * 1e9) / 1e9 : v;
}

async function main() {
  const {
    ridgeProfile, ridgeDirection, layerRadiusM, layerHeightFactor,
    clampBackdropHeightM, backdropRandom,
    BACKDROP_DIST_M, BACKDROP_LAYER_GAP_M, BACKDROP_LAYER_HEIGHT_K,
    BACKDROP_SEGMENTS, RIDGE_MIN_SHARE, RIDGE_TAPER_DEG,
  } = await loadTs(SRC);

  console.log('(A) the two layer offsets');
  check('A1 the front ring stands at 380 m', layerRadiusM(0), 380);
  check('A1 the back ring 60 m farther out', layerRadiusM(1), 440);
  check('A1 …and that IS the design constant', BACKDROP_DIST_M + BACKDROP_LAYER_GAP_M, 440);
  check('A2 the front ring keeps its height', layerHeightFactor(0), 1);
  check('A2 the back ring is 25 % taller', layerHeightFactor(1), 1.25);
  check('A2 …which is the declared share', 1 + BACKDROP_LAYER_HEIGHT_K, 1.25);

  console.log('\n(B) the full ring — [0,360], segments 8, height 100, r = 1');
  const ring = ridgeProfile(1, [[0, 360]], 100, 8, flat(1, 16));
  checkEq('B the front ring closes at 360, every peak 100 m',
    layerPairs(ring, 0),
    [[0, 100], [45, 100], [90, 100], [135, 100], [180, 100],
      [225, 100], [270, 100], [315, 100], [360, 100]]);
  checkEq('B the back ring, same angles at 125 m',
    layerPairs(ring, 1),
    [[0, 125], [45, 125], [90, 125], [135, 125], [180, 125],
      [225, 125], [270, 125], [315, 125], [360, 125]]);
  check('A3/B both layers are in ONE profile', ring.length, 18);

  console.log('\n(C) arc clipping — "N" = [157.5, 202.5]');
  const north = ridgeProfile(1, [[157.5, 202.5]], 100, 8, flat(1, 16));
  checkEq('C one node inside, both ends on the ground',
    layerPairs(north, 0), [[157.5, 0], [180, 100], [202.5, 0]]);
  checkEq('C …and the back ridge above it', layerPairs(north, 1),
    [[157.5, 0], [180, 125], [202.5, 0]]);

  console.log('\n(D) an arc past 360 — [292.5, 427.5], the wrap-free convention');
  const wrapArc = ridgeProfile(1, [[292.5, 427.5]], 100, 8,
    stream(1, 0, 1, 1, 1, 1, 1, 0.5, ...new Array(8).fill(1)));
  checkEq('D the sweep continues into node 0 and node 1',
    layerPairs(wrapArc, 0),
    [[292.5, 0], [315, 72.5], [360, 100], [405, 45], [427.5, 0]]);
  checkEq('D the back ridge over the same three nodes',
    layerPairs(wrapArc, 1),
    [[292.5, 0], [315, 125], [360, 125], [405, 125], [427.5, 0]]);

  console.log('\n(E) the taper — [0, 20] with 5° nodes');
  const narrow = ridgeProfile(1, [[0, 20]], 100, 72, flat(1, 144));
  const TAPER_5 = round((325 / 864) * 100);
  const TAPER_10 = round((25 / 27) * 100);
  checkEq('E the ridge climbs out of the ground and back into it',
    layerPairs(narrow, 0),
    [[0, 0], [5, TAPER_5], [10, TAPER_10], [15, TAPER_5], [20, 0]]);
  check('E …and 12° is the ramp it uses', RIDGE_TAPER_DEG, 12);

  console.log('\n(F) the clamps');
  check('F1 5 m is lifted to the floor', clampBackdropHeightM(5), 20);
  check('F1 1000 m is cut to the ceiling', clampBackdropHeightM(1000), 300);
  check('F1 120 m passes through', clampBackdropHeightM(120), 120);
  check('F1 NaN is no height', clampBackdropHeightM(NaN), 120);
  check('F1 nothing is no height', clampBackdropHeightM(undefined), 120);
  check('F1 a string is no height', clampBackdropHeightM('200'), 120);
  const low = ridgeProfile(1, [[157.5, 202.5]], 5, 8, flat(1, 16));
  check('F2 a 5 m setting draws the 20 m floor', layerPairs(low, 0)[1][1], 20);
  check('F2 …with the back ridge at 25 m', layerPairs(low, 1)[1][1], 25);
  const high = ridgeProfile(1, [[157.5, 202.5]], 1000, 8, flat(1, 16));
  check('F2 a 1000 m setting draws the 300 m ceiling',
    layerPairs(high, 0)[1][1], 300);
  check('F2 …with the back ridge at 375 m', layerPairs(high, 1)[1][1], 375);
  const lowest = ridgeProfile(1, [[157.5, 202.5]], 100, 8, flat(0, 16));
  check('F3 the lowest peak is 45 % of the height',
    layerPairs(lowest, 0)[1][1], 45);
  check('F3 …the back one 56.25 m', layerPairs(lowest, 1)[1][1], 56.25);
  check('F3 …which is the declared share', RIDGE_MIN_SHARE, 0.45);

  console.log('\n(G) nothing to draw / junk');
  checkEq('G no arcs, no ring', ridgeProfile(1, [], 100, 8, flat(1, 16)), []);
  checkEq('G an empty arc draws nothing',
    ridgeProfile(1, [[10, 10]], 100, 8, flat(1, 16)), []);
  checkEq('G a reversed arc draws nothing',
    ridgeProfile(1, [[90, 10]], 100, 8, flat(1, 16)), []);
  checkEq('G a non-finite arc draws nothing',
    ridgeProfile(1, [[NaN, 20]], 100, 8, flat(1, 16)), []);
  checkEq('G no arc list at all draws nothing',
    ridgeProfile(1, null, 100, 8, flat(1, 16)), []);
  check('G segments 2 is lifted to 8 (9 points per ring)',
    ridgeProfile(1, [[0, 360]], 100, 2, flat(1, 16)).filter((p) => !p.layer).length, 9);
  check('G segments NaN falls back to the default 96',
    ridgeProfile(1, [[0, 360]], 100, NaN).filter((p) => !p.layer).length,
    BACKDROP_SEGMENTS + 1);

  console.log('\n(H) the compass of § A1.8');
  checkEq('H 0° is south', ridgeDirection(0).map(round), [0, 1]);
  checkEq('H 90° is east', ridgeDirection(90).map(round), [1, 0]);
  checkEq('H 180° is north', ridgeDirection(180).map(round), [0, -1]);
  checkEq('H 270° is west', ridgeDirection(270).map(round), [-1, 0]);
  checkEq('H 45° is south-east', ridgeDirection(45).map(round),
    [round(Math.SQRT1_2), round(Math.SQRT1_2)]);

  console.log('\n(I) determinism and the copied RNG');
  const seeded = () => ridgeProfile(7, [[0, 360]], 100, 16);
  checkEq('I the same seed is the same ridge, twice',
    JSON.stringify(seeded()) === JSON.stringify(seeded()), true);
  const real = seeded();
  const front = real.filter((p) => p.layer === 0);
  const back = real.filter((p) => p.layer === 1);
  /** The first four peaks of a ridge — enough to tell two ridges apart, short
   *  enough to read in the log. */
  const head = (list) => list.slice(0, 4).map((p) => round(p.peakH));
  checkNotEq('I a different seed is a different ridge',
    head(ridgeProfile(8, [[0, 360]], 100, 16)), head(front));
  checkNotEq('I the back ridge is not the front one scaled by 1.25',
    head(back), head(front).map((h) => round(h * 1.25)));
  check('I every front peak is inside [45, 100] m',
    front.filter((p) => p.peakH >= 45 - 1e-9 && p.peakH <= 100 + 1e-9).length,
    front.length);
  check('I every back peak is inside [56.25, 125] m',
    back.filter((p) => p.peakH >= 56.25 - 1e-9 && p.peakH <= 125 + 1e-9).length,
    back.length);
  const { seededRandom } = await loadTs(SCATTER_SRC);
  for (const seed of ['backdrop-1-l0', 'backdrop-42-l1']) {
    const mine = backdropRandom(seed);
    const theirs = seededRandom(seed);
    checkEq(`I the copy draws what scatter.ts draws ("${seed}")`,
      [mine(), mine(), mine(), mine(), mine()],
      [theirs(), theirs(), theirs(), theirs(), theirs()]);
  }

  console.log('\n(J) the red counter-checks');
  const flatLayers = await loadTs(SRC, (s) =>
    s.replace('return 1 + BACKDROP_LAYER_HEIGHT_K * layer;', 'return 1;'));
  check('J1 the "one height" mutant puts the back ridge at 100 m',
    layerPairs(flatLayers.ridgeProfile(1, [[0, 360]], 100, 8, flat(1, 16)), 1)[0][1], 100);
  checkNotEq('J1 …which is NOT what the real rule builds there',
    layerPairs(ring, 1)[0][1], 100);
  const oneRadius = await loadTs(SRC, (s) =>
    s.replace('return BACKDROP_DIST_M + BACKDROP_LAYER_GAP_M * layer;',
      'return BACKDROP_DIST_M;'));
  check('J2 the "one radius" mutant stands both rings at 380 m',
    oneRadius.layerRadiusM(1), 380);
  checkNotEq('J2 …which is NOT the real back radius', layerRadiusM(1), 380);
  const noWrap = await loadTs(SRC, (s) =>
    s.replace('const wrap = (i: number) => ((i % n) + n) % n;',
      'const wrap = (i: number) => i;'));
  const torn = layerPairs(noWrap.ridgeProfile(1, [[292.5, 427.5]], 100, 8,
    stream(1, 0, 1, 1, 1, 1, 1, 0.5, ...new Array(8).fill(1))), 0);
  checkEq('J3 the "no wrap" mutant reads past the ring at 405°',
    Number.isFinite(torn[3][1]), false);
  check('J3 …where the real ring answers node 1', layerPairs(wrapArc, 0)[3][1], 45);
  const mirrored = await loadTs(SRC, (s) =>
    s.replace('return [Math.sin(a), Math.cos(a)];', 'return [Math.cos(a), Math.sin(a)];'));
  checkEq('J4 the mirrored compass points 180° west',
    mirrored.ridgeDirection(180).map(round), [-1, 0]);
  checkNotEq('J4 …which is NOT where the real compass points north',
    ridgeDirection(180).map(round), [-1, 0]);

  console.log(`\n${passed} ok, ${failed} failed`);
  process.exit(failed ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
