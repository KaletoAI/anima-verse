#!/usr/bin/env node
/**
 * Derivation moved to native/tests/Derivations/backdrop_math.md (E1, 2026-11-25).
 * Usage:  node client3d/scripts/smoke_backdrop_math.mjs
 * Runs until E3 deletes the browser scene; the C# vector tests keep executing the cases.
 */
import { vectorCase, vectorArgs, vectorValue } from './e3VectorSupport.mjs';
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

function vector(label, fns) {
  const result = vectorCase("backdrop", label, fns);
  passed += result.passed; failed += result.failed;
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
  vector("[0] backdrop_math: A1 the front ring stands at 380 m", { layerRadiusM: (...args) => layerRadiusM(...vectorArgs(args)) });
  vector("[0] backdrop_math: A1 the back ring 60 m farther out", { layerRadiusM: (...args) => layerRadiusM(...vectorArgs(args)) });
  check('A1 …and that IS the design constant', BACKDROP_DIST_M + BACKDROP_LAYER_GAP_M, 440);
  vector("[0] backdrop_math: A2 the front ring keeps its height", { layerHeightFactor: (...args) => layerHeightFactor(...vectorArgs(args)) });
  vector("[0] backdrop_math: A2 the back ring is 25 % taller", { layerHeightFactor: (...args) => layerHeightFactor(...vectorArgs(args)) });
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
  vector("[0] backdrop_math: F1 5 m is lifted to the floor", { clampBackdropHeightM: (...args) => clampBackdropHeightM(...vectorArgs(args)) });
  vector("[0] backdrop_math: F1 1000 m is cut to the ceiling", { clampBackdropHeightM: (...args) => clampBackdropHeightM(...vectorArgs(args)) });
  vector("[0] backdrop_math: F1 120 m passes through", { clampBackdropHeightM: (...args) => clampBackdropHeightM(...vectorArgs(args)) });
  check('F1 NaN is no height', clampBackdropHeightM(NaN), 120);
  check('F1 nothing is no height', clampBackdropHeightM(undefined), 120);
  vector("[0] backdrop_math: F1 a string is no height", { clampBackdropHeightM: (...args) => clampBackdropHeightM(...vectorArgs(args)) });
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
