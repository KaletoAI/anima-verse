#!/usr/bin/env node
/**
 * Derivation moved to native/tests/Derivations/scatter_math.md (E1, 2026-11-25).
 * Usage:  node client3d/scripts/smoke_scatter_math.mjs
 * Runs until E3 deletes the browser scene; the C# vector tests keep executing the cases.
 */
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { rowVectorDispatch } from './e4VectorDispatch.mjs';
import { loadVectors, runVectors } from '../../shared/test-vectors/vectors.mjs';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');
const SRC = join(ROOT, 'packages/scene-render/src/scatter.ts');
const AXIS_SRC = join(ROOT, 'packages/scene-render/src/scatterAxis.ts');
const OCCUPANCY_SRC = join(ROOT, 'packages/scene-render/src/occupancy.ts');
const MAPMATH_SRC = join(ROOT, 'frontend/src/tabs/map/mapMath.ts');
const LOD_SRC = join(ROOT, 'client3d/src/scene/scatterLod.ts');
const GROUND_SRC = join(ROOT, 'client3d/src/scene/ground.ts');
const PREFS_SRC = join(ROOT, 'hud/src/game/prefs.ts');

/** See the header: neither module has a runtime import, so a transpile is all
 *  it takes. Should someone add one, this fails loudly — that is the alarm.
 *
 *  `mutate` rewrites the SOURCE before the transpile — that is how sections
 *  (D) and (F8) get a wrong module to compare against, without a second copy
 *  of the maths lying around to rot. */
async function loadTs(src, mutate) {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'scattermath-'));
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

/** A module WITH imports — `scatterAxis.ts` pulls the ring primitives from
 *  `scatter.ts` — bundled by esbuild from the real source tree, so the import
 *  resolves against the very file section (C) loads. */
async function loadBundled(src) {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'scattermath-'));
  try {
    const file = join(dir, 'module.mjs');
    await esbuild.build({
      entryPoints: [src], outfile: file, bundle: true, format: 'esm',
      platform: 'neutral', logLevel: 'silent', absWorkingDir: ROOT,
    });
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

/** The renderers' own band rule — `strokeToPolygon` out of the map editor's
 *  `mapMath.ts`, bundled through a stdin entry because the module is a
 *  frontend file with imports of its own. Section (R8) needs the ring a road
 *  really has, and restating the miter rule here would be the second copy
 *  this repo keeps deleting. */
async function loadStrokeToPolygon() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'scattermath-'));
  try {
    const file = join(dir, 'mapMath.mjs');
    await esbuild.build({
      stdin: {
        contents: `export { strokeToPolygon } from ${JSON.stringify(MAPMATH_SRC)};\n`,
        resolveDir: ROOT, sourcefile: 'smoke-entry.mjs', loader: 'js',
      },
      outfile: file, bundle: true, format: 'esm',
      platform: 'neutral', logLevel: 'silent', absWorkingDir: ROOT,
    });
    return (await import(`file://${file}`)).strokeToPolygon;
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

/** Section (D)'s mutant: the yaw is drawn only for an ACCEPTED candidate, so a
 *  rejected one costs two numbers instead of three and shifts everything
 *  behind it. See the header for the derivation. */
function yawOnAcceptance(source) {
  return source
    .replace('    const turn = rnd()\n', '')
    .replace('    const yaw = scatterYaw(turn, opts.yawMode, opts.yawDeg, '
      + 'axisAt ? axisAt(x, z) : 0)\n', '')
    .replace(
      'out.push(mixing\n'
      + '      ? { x, z, yaw, variant: pinned >= 0 ? pinned'
      + ' : scatterVariantIndex(opts.seed, index, variants) }\n'
      + '      : { x, z, yaw })',
      'out.push({ x, z, yaw: rnd() * Math.PI * 2 })');
}

/** Section (N3)'s mutant: the variant is counted over the SURVIVORS instead of
 *  over the candidates, so a rejection shifts the whole rest of the cell into
 *  other meshes — the wood behind a newly painted shape changes species.
 *  See the header for the derivation. */
function variantFromSurvivorIndex(source) {
  return source.replace(
    'scatterVariantIndex(opts.seed, index, variants)',
    'scatterVariantIndex(opts.seed, out.length, variants)');
}

/** Section (G5)'s mutant: the prop's library height is never consulted and
 *  every scattered prop is the flat fallback — the state before finding 12,
 *  where an 8.5 m tree stood at avatar height. */
function ignorePropHeight(source) {
  return source.replace(
    '  if (Number(propH) > 0) return Number(propH);\n', '');
}

/** Section (H7)'s mutant: the prop's factor is ignored and the ground's
 *  amplitude is handed back as it came — the state of the code before the
 *  factor existed, where every prop of a waving area waves. */
function ignoreSwayFactor(source) {
  return source.replace(
    '  return Math.round(base * clamped * 100) / 100;\n',
    '  return Math.round(base * 100) / 100;\n');
}

/** Section (H8)'s mutant: the ground offset is dropped and the sampled height
 *  is handed back as it came — the state of the code before the field existed,
 *  where a sunk fir stands on the grass in a painted wood while the same fir
 *  is buried correctly in every room. */
function ignoreGroundOffset(source) {
  return source.replace(
    '  if (typeof offsetM !== \'number\' || !Number.isFinite(offsetM)) return 0;\n'
    + '  return Math.min(Math.max(offsetM, -SCATTER_GROUND_OFFSET_LIMIT_M),\n'
    + '    SCATTER_GROUND_OFFSET_LIMIT_M);\n',
    '  return 0;\n');
}

/** Section (I5)'s third mutant: the textbook `fract(sin(i*12.9898)*43758.5453)`
 *  in place of the murmur3 finaliser — the mix that WAS tried first, and the
 *  one the 0.25 row of (I4) rejected. */
function sinInsteadOfMurmur(source) {
  return source.replace(
    '  let h = Math.imul(index | 0, 2654435761) >>> 0;\n'
    + '  h = Math.imul(h ^ (h >>> 15), 2246822507);\n'
    + '  h = Math.imul(h ^ (h >>> 13), 3266489909);\n'
    + '  h ^= h >>> 16;\n'
    + '  return (h >>> 0) / 4294967296;\n',
    '  const v = Math.sin(index * 12.9898) * 43758.5453;\n'
    + '  return v - Math.floor(v);\n');
}

/** Section (I5)'s first mutant: the per-instance band is gone, so an instance
 *  in the 35…45 m band no longer keeps the tier it has — the very thrash the
 *  band exists to prevent, now once per prop instead of once per area. */
function dropInstanceBand(source) {
  return source.replace(
    '  if (distM < cfg.nearM) return 0;\n'
    + '  if (distM > cfg.farM) return 1;\n'
    + '  return held;\n',
    '  return distM > cfg.farM ? 1 : 0;\n');
}

/** Section (I5)'s second mutant: the index hash is replaced by chance. Each
 *  tick draws a NEW set of survivors, which is the flickering wood the stable
 *  hash exists to prevent. */
function randomInsteadOfHash(source) {
  return source.replace(
    '  let h = Math.imul(index | 0, 2654435761) >>> 0;\n'
    + '  h = Math.imul(h ^ (h >>> 15), 2246822507);\n'
    + '  h = Math.imul(h ^ (h >>> 13), 3266489909);\n'
    + '  h ^= h >>> 16;\n'
    + '  return (h >>> 0) / 4294967296;\n',
    '  return Math.random();\n');
}

/** Section (S8)'s mutant: the spacing grid looks ONLY in the candidate's own
 *  bucket instead of in the 3x3 block around it, so two props on either side
 *  of a bucket border never see each other — the spacing would hold nowhere
 *  except by luck. See the header for the derivation. */
function ownBucketOnly(source) {
  return source.replace(
    '      for (let dz = -1; dz <= 1 && !crowded; dz += 1) {\n'
    + '        for (let dx = -1; dx <= 1 && !crowded; dx += 1) {\n',
    '      for (let dz = 0; dz <= 0 && !crowded; dz += 1) {\n'
    + '        for (let dx = 0; dx <= 0 && !crowded; dx += 1) {\n');
}

/** Section (P4)'s mutant: a placed prop's box is built AXIS-ALIGNED — the turn
 *  the author gave the prop is dropped, so the box clears ground the prop
 *  never covers on two corners and grows props inside it on the other two.
 *  See the header for the derivation. */
function axisAlignedPropBox(source) {
  return source.replace(
    '  const cos = Math.cos(yawRad)\n  const sin = Math.sin(yawRad)\n',
    '  const cos = 1\n  const sin = 0\n');
}

/** Section (V5)'s mutant: the view cone is cut exactly at the frustum edge.
 *  The LOD pass runs at most ten times a second, so a camera that turns
 *  between two passes would show a bare wedge along the edge of the picture
 *  until the next one. */
function noConeMargin(source) {
  return source.replace('(30 * Math.PI) / 180', '0');
}

/** Section (V6)'s mutant: the 40 m near keep is deleted, so the horizontal
 *  cone alone decides for every instance. Under a steep look-down the XZ
 *  forward direction points far past the ground the player is looking at, and
 *  the wood at their feet is culled. */
function noConeNearKeep(source) {
  return source.replace(
    '  if (!(d2 > SCATTER_CONE_NEAR_M * SCATTER_CONE_NEAR_M)) return true;\n',
    '');
}

/** Section (W4)'s mutant: the impostor thinning as it stood until 2026-08-24 —
 *  restarting at a full 1 where the meshes had just thinned to a quarter, and
 *  calibrated to `IMPOSTOR_FAR_M` instead of to the reach of the cell window.
 *  It is the behaviour the acceptance round reported as a visible density jump
 *  at the 120 m line. */
function impostorShareRestartsFull(source) {
  return source.replace(
    '  const span = impostorReachM(cfg.cullM) - cfg.cullM;\n'
    + '  // A window whose corner does not clear the cull line has no span to thin\n'
    + '  // over (only reachable from a hand-built cfg): the whole of it is the floor.\n'
    + '  if (!(span > 0)) return SCATTER_MIN_SHARE * IMPOSTOR_TAIL_FACTOR;\n'
    + '  const t = Math.min((distM - cfg.cullM) / span, 1);\n'
    + '  return SCATTER_MIN_SHARE * (1 - t * (1 - IMPOSTOR_TAIL_FACTOR));\n',
    '  const span = IMPOSTOR_FAR_M - cfg.cullM;\n'
    + '  if (!(span > 0)) return 0;\n'
    + '  const t = (distM - cfg.cullM) / span;\n'
    + '  return 1 - t * (1 - IMPOSTOR_TAIL_FACTOR);\n');
}

/** Section (M6)'s mutant: the clearance is thrown away and the old "is its
 *  CENTRE inside?" decides again — the state the user reported as scatter
 *  overhanging into locations. */
function centreInsteadOfClearance(source) {
  return source.replace(
    '  if (!(clear > 0)) return pointInFootprint(fp, x, z)\n'
    + '  return footprintDistance(fp, x, z) < clear\n',
    '  return pointInFootprint(fp, x, z)\n');
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
/** The other half of a red counter-check: the value the MUTANT produces,
 *  asserted absent. A mutant that agrees means the case pins nothing. */
function checkNot(label, actual, forbidden, eps = 1e-9) {
  const ok = !compare(actual, forbidden, eps);
  if (ok) {
    passed += 1;
    console.log(`  ok   ${label}`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}\n       this is the value the correct sampler gives`
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
    scatterYaw, reshuffleEpoch, seededRandom,
    scatterWantedCount, scatterCellAt, scatterCellInstances, scatterCellRing,
    scatterCellSeed, scatterCellSpan, scatterCellsInBox, wantedScatterCells,
    scatterSeedHash, scatterVariantIndex,
    propBoxFootprint, propBoxFootprints,
    footprintBlocks, footprintDistance, scatterClearM,
    SCATTER_CELL_M, SCATTER_CLEAR_HEIGHT_RATIO, SCATTER_MAX_PER_CELL,
  } = await loadTs(SRC);

  const TAU = Math.PI * 2;
  const SQUARE = [[0, 0], [20, 0], [20, 20], [0, 20]];
  // The occluder ring OCC_LEFT of (C8) — the rest of (C8..C11) runs from the
  // JSON, which spells its rings out the same way.
  const OCC_LEFT = [[0, 0], [10, 0], [10, 10], [0, 10]];
  /** The server's concave L-shape in LOCAL metres — the fixture of
   *  `scripts/smoke_world_polygon.py` and `smoke_polygon_containment.mjs`. */
  const L_LOCAL = [[0, 0], [4, 0], [4, 2], [2, 2], [2, 4], [0, 4]];
  /** Local -> world (§ A1.1) — the turn the CALLER does before the sampler
   *  ever sees a footprint (`ground.ts → worldFootprints`). Spelled out here,
   *  never imported: the world literals of section (B) are hand-derived from
   *  this formula, and a shared helper would be checking itself. */
  const localToWorld = (lx, lz, cx, cz, yawDeg) => {
    const r = (yawDeg * Math.PI) / 180;
    const c = Math.cos(r);
    const s = Math.sin(r);
    // rounded to nanometres: cos(90 deg) is 6.1e-17 in binary floats, not 0,
    // and a corner at 100.0000000000000002 reads worse than it is.
    return [Math.round((cx + lx * c + lz * s) * 1e9) / 1e9,
      Math.round((cz - lx * s + lz * c) * 1e9) / 1e9];
  };
  const L_WORLD = L_LOCAL.map(([lx, lz]) => localToWorld(lx, lz, 100, 50, 90));
  /** (C2)/(D): the outline that covers the first candidate of the (C1) stream
   *  — 1..3 by 3..5 in world metres, and (2, 4) is its centre. */
  const FP_OVER_FIRST = { points: [[1, 3], [3, 3], [3, 5], [1, 5]] };
  // The (C1) stream — the (D) mutant below reads it; the (C12) meadow around
  // the L-shaped place is the JSON fixture L_MEADOW (derivation in the header).
  const C1_STREAM = [0.10, 0.20, 0.50, 0.75, 0.25, 0.00];
  /** The client's `SCATTER_MODEL_HEIGHT_M` (metres), written out by hand and
   *  pinned against the client source in section (E). */
  const DEFAULT_TARGET_H = 2.0;

  // ---- the shared vectors: every hand-derived case of a C#-ported function
  // (see "SHARED VECTORS" in the header). A sampler's `rng` list becomes the
  // throwing `stream()`; everything else is called as the JSON spells it.
  const lod = await loadTs(LOD_SRC);
  const rowFns = rowVectorDispatch(
    await loadTs(SRC), await loadBundled(AXIS_SRC), await loadBundled(OCCUPANCY_SRC),
    await loadBundled(join(ROOT, 'packages/scene-render/src/stroke.ts')));
  for (const name of ['scatter_rows', 'impostors']) {
    const file = loadVectors(name);
    // Impostor seam vectors also belong to this smoke's original section W.
    const selected = name === 'impostors'
      ? { ...file, cases: file.cases.filter((c) => c.label.startsWith('[W')) } : file;
    const result = runVectors(selected, name === 'impostors' ? lod : rowFns);
    passed += result.passed; failed += result.failed;
  }
  const fed = (fn) => (opts) => fn(Array.isArray(opts?.rng)
    ? { ...opts, rng: stream(opts.rng) } : opts);
  console.log('\n(vectors) shared/test-vectors/scatter.json');
  const vectors = runVectors(loadVectors('scatter'), {
    propGroundFit, pointInRing, pointInFootprint, footprintDistance, footprintBlocks,
    scatterClearM, propBoxFootprint, scatterWantedCount,
    scatterInstances: fed(scatterInstances), scatterCellInstances: fed(scatterCellInstances),
    scatterSeed, scatterCellSeed, reshuffleEpoch, scatterSeedHash, scatterVariantIndex,
    scatterYaw, scatterCellAt, scatterCellRing, scatterCellSpan,
    wantedScatterCells, seedEpochSuffix: (await loadTs(SRC)).seedEpochSuffix,
    scatterOccupyR: (await loadTs(SRC)).scatterOccupyR, instanceHash: lod.instanceHash,
    scatterTargetH: lod.scatterTargetH, scatterSway: lod.scatterSway,
    scatterGroundOffset: lod.scatterGroundOffset, instanceTier: lod.instanceTier,
    instanceShare: lod.instanceShare, instanceVisible: lod.instanceVisible,
    horizontalFovRad: lod.horizontalFovRad, viewCone: lod.viewCone, inViewCone: lod.inViewCone,
  });
  passed += vectors.passed;
  failed += vectors.failed;

  console.log('\n(A) propGroundFit — the inline rest (non-finite / non-number input)');
  check('A6 a NaN box leaves the prop where the file put it',
    propGroundFit(NaN, NaN, 2), { scale: 1, offsetY: 0 });
  for (const bad of [NaN, 'tall']) {
    check(`A7 target height ${JSON.stringify(bad)} is no request — lift only`,
      propGroundFit(-1, 1, bad), { scale: 1, offsetY: 1 });
  }

  console.log('\n(B) pointInFootprint — the DRAWN outline stays clear (B18, v6)');
  // The caller's job, done here by hand so the expectations below are literals
  // and not the output of a helper: local -> world at pin (100, 50), yaw 90.
  check('B the pin transform puts local (4,0) at world (100,46)',
    L_WORLD[1], [100, 46]);
  check('B …and the whole outline is the hand-derived one', L_WORLD, [
    [100, 50], [100, 46], [102, 46], [102, 48], [104, 48], [104, 50],
  ]);
  // B1..B5 run from the JSON (HUT there is this hand-derived L_WORLD); inline
  // stay the two non-finite inputs.
  const HUT = { points: L_WORLD };
  check('B4 a junk coordinate poisons the whole outline',
    pointInFootprint({ points: [[100, 50], [100, NaN], [102, 46], [102, 48]] },
      101, 47), false);
  check('B4 a NaN query point is refused', pointInFootprint(HUT, NaN, 49), false);

  console.log('\n(M) the CLEARANCE — a prop stops OVERHANGING a location');
  const SQ_FP = { points: [[0, 0], [10, 0], [10, 10], [0, 10]] };
  // M1..M5 run from the JSON, except what JSON cannot carry. Infinity survives no JSON round trip, so the four are asserted as the
  // predicate they stand for: nothing can ever be that close.
  check('M1 a degenerate outline is unreachable',
    [footprintDistance({ points: [[0, 0], [10, 0]] }, 5, 5),
      footprintDistance({}, 5, 5),
      footprintDistance({ points: [[0, 0], [10, NaN], [10, 10]] }, 5, 5),
      footprintDistance(SQ_FP, NaN, 5)].map((d) => d === Infinity),
    [true, true, true, true]);
  check('M1 …and therefore blocks nothing, at any clearance',
    footprintBlocks({ points: [[0, 0], [10, NaN], [10, 10]] }, 5, 5, 1e6),
    false);
  check('M2 without a clearance it is the plain containment test again — clearM NaN',
    footprintBlocks(SQ_FP, 10.4, 5, NaN), false);
  const CLEAR_SAMPLE = {
    ring: SQUARE, areaM2: 400, densityPer100m2: 0.5, seed: 's',
    footprints: [{ points: [[10, 0], [20, 0], [20, 10], [10, 10]] }],
    triesPerPoint: 1,
  };
  const CLEAR_STREAM = [0.48, 0.25, 0.00, 0.43, 0.25, 0.50];
  check('M5 a junk extent falls back to the estimate — extent NaN',
    scatterClearM(8, NaN), 4);
  check('M5 …and a junk height is no clearance at all — height NaN',
    scatterClearM(NaN), 0);
  check('M5 the estimate ratio is a half', SCATTER_CLEAR_HEIGHT_RATIO, 0.5);
  const centreMutant = await loadTs(SRC, centreInsteadOfClearance);
  checkNot('M6 the "centre inside" mutant does NOT reproduce the M4 answer',
    centreMutant.scatterInstances({
      ...CLEAR_SAMPLE, clearM: 1, rng: stream(CLEAR_STREAM),
    }),
    [{ x: 8.6, z: 5, yaw: Math.PI }]);
  check('M6 …it keeps the overhanging 0.4 m prop, which IS the defect',
    centreMutant.scatterInstances({
      ...CLEAR_SAMPLE, clearM: 1, rng: stream(CLEAR_STREAM),
    }),
    [{ x: 9.6, z: 5, yaw: 0 }, { x: 8.6, z: 5, yaw: Math.PI }]);

  // pointInRing and C1..C6, C8..C12 run from the JSON.
  console.log('\n(C) scatterInstances — the sampler');
  console.log('\n  C7 determinism of the seeded path (a property, not a record)');
  const opts = { ring: SQUARE, areaM2: 400, densityPer100m2: 2 };
  const a1 = scatterInstances({ ...opts, seed: scatterSeed('ta_1', 0) });
  const a2 = scatterInstances({ ...opts, seed: scatterSeed('ta_1', 0) });
  const b1 = scatterInstances({ ...opts, seed: scatterSeed('ta_1', 1) });
  check('the same seed gives the identical list', a1, a2);
  check('…and it is not empty', a1.length, 8);
  check('a second entry of the same area stands elsewhere',
    JSON.stringify(a1) !== JSON.stringify(b1), true);

  console.log('\n  C13 TWO AREAS OF ONE KIND — the count is the AREA\'s, '
    + 'never the kind\'s');
  const BIG = [[0, 0], [100, 0], [100, 100], [0, 100]];      // 10 000 m2
  const SMALL = [[200, 0], [230, 0], [230, 30], [200, 30]];  //    900 m2
  const big = scatterInstances({
    ring: BIG, areaM2: 10000, densityPer100m2: 3, seed: scatterSeed('ta_big', 0),
  });
  const small = scatterInstances({
    ring: SMALL, areaM2: 900, densityPer100m2: 3, seed: scatterSeed('ta_small', 0),
  });
  check('C13 both areas are planted, 300 and 27 props',
    [big.length, small.length], [300, 27]);
  check('C13 …at the SAME density per 100 m2 — 3 and 3',
    [big.length / (10000 / 100), small.length / (900 / 100)], [3, 3]);
  check('C13 …so the second area is not a copy of the first',
    JSON.stringify(scatterInstances({
      ring: BIG, areaM2: 10000, densityPer100m2: 3,
      seed: scatterSeed('ta_small', 0),
    })) !== JSON.stringify(big), true);
  // (C14) A LOWER CEILING IS A PREFIX, not a second sample — what lets the map
  // editor thin its preview to a budget and still draw props the world plants.
  const thinned = scatterInstances({
    ring: BIG, areaM2: 10000, densityPer100m2: 3, seed: scatterSeed('ta_big', 0),
    maxPoints: 25,
  });
  check('C14 maxPoints 25 gives the first 25 of the very same 300',
    thinned, big.slice(0, 25));

  console.log('\n(K) the CELL raster — the density of the GROUND, not of the shape');
  // (K1) the per-cell counts, straight off 4096/100 = 40.96
  const CELL_M2 = SCATTER_CELL_M * SCATTER_CELL_M;
  check('K0 a cell is 64 m, i.e. 4 096 m2', [SCATTER_CELL_M, CELL_M2], [64, 4096]);
  // K1's per-cell counts and the d = 200 cap run from the JSON; the 97.66 is
  // arithmetic on the constants.
  check('K1 the guard is 4 000 per cell, i.e. 97.66 props per 100 m2',
    Math.round((SCATTER_MAX_PER_CELL / (CELL_M2 / 100)) * 100) / 100, 97.66);
  // (K2) the two forests — cell-aligned squares, 100 times apart in size
  const F_BIG = [[0, 0], [1280, 0], [1280, 1280], [0, 1280]];
  const F_SMALL = [[2048, 0], [2176, 0], [2176, 128], [2048, 128]];
  const cellCount = (ring, id, cells) => cells.reduce((sum, [cx, cz]) => sum
    + scatterCellInstances({
      ring, cx, cz, densityPer100m2: 3, seed: scatterCellSeed(id, 0, cx, cz),
    }).length, 0);
  const bigCells = [];
  for (let cz = 0; cz < 20; cz += 1) for (let cx = 0; cx < 20; cx += 1) bigCells.push([cx, cz]);
  const smallCells = [[32, 0], [33, 0], [32, 1], [33, 1]];
  const bigN = cellCount(F_BIG, 'ta_big', bigCells);
  const smallN = cellCount(F_SMALL, 'ta_small', smallCells);
  check('K2 one cell wholly inside either wood carries its 123 props',
    [scatterCellInstances({
      ring: F_BIG, cx: 5, cz: 7, densityPer100m2: 3,
      seed: scatterCellSeed('ta_big', 0, 5, 7),
    }).length,
    scatterCellInstances({
      ring: F_SMALL, cx: 32, cz: 1, densityPer100m2: 3,
      seed: scatterCellSeed('ta_small', 0, 32, 1),
    }).length],
    [123, 123]);
  check('K2 400 cells of the big wood and 4 of the small: 49 200 and 492 props',
    [bigN, smallN], [49200, 492]);
  const density = (n, m2) => Math.round((n / (m2 / 100)) * 100000) / 100000;
  check('K2 …which is the SAME density per 100 m2 on both — 3.00293',
    [density(bigN, 1638400), density(smallN, 16384)], [3.00293, 3.00293]);
  // (K3) the red counter-probe: the whole-area sampler on the same two woods
  const oldBig = scatterInstances({
    ring: F_BIG, areaM2: 1638400, densityPer100m2: 3, seed: scatterSeed('ta_big', 0),
  }).length;
  const oldSmall = scatterInstances({
    ring: F_SMALL, areaM2: 16384, densityPer100m2: 3, seed: scatterSeed('ta_small', 0),
  }).length;
  check('K3 the OLD whole-area path really did cap the big wood at 2 000',
    [oldBig, oldSmall], [2000, 492]);
  check('K3 …i.e. 0.12207 against 3.00293 per 100 m2 — a factor of 24.6',
    [density(oldBig, 1638400), density(oldSmall, 16384),
      Math.round((density(oldSmall, 16384) / density(oldBig, 1638400)) * 10) / 10],
    [0.12207, 3.00293, 24.6]);
  checkNot('K3 …and the cell rule does NOT reproduce that pair',
    [density(bigN, 1638400), density(smallN, 16384)],
    [density(oldBig, 1638400), density(oldSmall, 16384)]);
  check('K3 …because the cell rule puts the two woods at ONE density, ratio 1',
    density(bigN, 1638400) / density(smallN, 16384), 1);
  // (K4) the seed string runs from the JSON
  const cellA = scatterCellInstances({
    ring: F_BIG, cx: 3, cz: 4, densityPer100m2: 3,
    seed: scatterCellSeed('ta_big', 0, 3, 4),
  });
  const cellB = scatterCellInstances({
    ring: F_BIG, cx: 4, cz: 4, densityPer100m2: 3,
    seed: scatterCellSeed('ta_big', 0, 4, 4),
  });
  check('K4 the same cell asked twice gives the identical props', cellA,
    scatterCellInstances({
      ring: F_BIG, cx: 3, cz: 4, densityPer100m2: 3,
      seed: scatterCellSeed('ta_big', 0, 3, 4),
    }));
  check('K4 …and the neighbour cell is not that pattern shifted by 64 m',
    cellA.map((p) => [p.x + SCATTER_CELL_M, p.z, p.yaw]).slice(0, 3)
      .some((p, i) => Math.abs(p[0] - cellB[i].x) < 1e-9
        && Math.abs(p[1] - cellB[i].z) < 1e-9), false);
  // (K5) runs from the JSON. (K6) the window — the spans, cell indices and
  // the cell ring run from the JSON too.
  check('K6 …i.e. 25 / 9 / 121 cells in the window',
    [wantedScatterCells(0, 0, 120).length, wantedScatterCells(0, 0, 60).length,
      wantedScatterCells(0, 0, 300).length], [25, 9, 121]);
  check('K6 …and every span reaches at least as far as its cull distance',
    [120, 60, 300].map((c) => scatterCellSpan(c) * SCATTER_CELL_M >= c),
    [true, true, true]);
  check('K6 at the origin the window runs from (-2,-2)',
    wantedScatterCells(0, 0, 120)[0], [-2, -2]);
  check('K6 at (100, 30) the anchor cell is (1, 0), so it runs from (-1,-2)',
    wantedScatterCells(100, 30, 120)[0], [-1, -2]);
  check('K6 a step inside the same cell does not move the window',
    wantedScatterCells(100, 30, 120), wantedScatterCells(120, 60, 120));
  check('K6 …crossing the border does', wantedScatterCells(130, 30, 120)[0],
    [0, -2]);
  check('K6 a world box asks for every cell it meets, row-major',
    scatterCellsInBox(0, 0, 70, 10), [[0, 0], [1, 0]]);
  check('K6 …and a box bigger than the guard asks for none',
    scatterCellsInBox(0, 0, 1e6, 1e6).length, 0);
  // (K7) what the reporting world costs
  const BIG_ROWS = [1, 0.1, 10, 10, 1, 1, 20];
  const SMALL_ROWS = [1, 10, 1, 10, 20, 1];
  const perCell = (rows) => rows.reduce((sum, d) =>
    sum + scatterWantedCount(CELL_M2, d, SCATTER_MAX_PER_CELL), 0);
  check('K7 the reporting world\'s two woods want 1 766 and 1 762 props per cell',
    [perCell(BIG_ROWS), perCell(SMALL_ROWS)], [1766, 1762]);
  check('K7 …i.e. 43.115 and 43.018 per 100 m2 — the authored 43.1 and 43.0',
    [Math.round((perCell(BIG_ROWS) / 40.96) * 1000) / 1000,
      Math.round((perCell(SMALL_ROWS) / 40.96) * 1000) / 1000],
    [43.115, 43.018]);
  check('K7 …44 150 and 44 050 instances held over a 25-cell window',
    [25 * perCell(BIG_ROWS), 25 * perCell(SMALL_ROWS)], [44150, 44050]);
  check('K7 …19 505 and 19 461 inside the 120 m cull circle (was 46 and 645)',
    [Math.round(((Math.PI * 120 * 120) / 100) * (perCell(BIG_ROWS) / 40.96)),
      Math.round(((Math.PI * 120 * 120) / 100) * (perCell(SMALL_ROWS) / 40.96))],
    [19505, 19461]);

  console.log('\n(N) the VARIANT MIX — a wood of 14 000 trees is not one tree');
  // (N1) the hash. An INDEPENDENT FNV-1a, written out here and never imported:
  // the point of the section is that the module's hash is this arithmetic, and
  // a shared helper would be checking itself (same discipline as `localToWorld`
  // above).
  const fnv1a = (seed) => {
    let h = 2166136261;
    for (let i = 0; i < seed.length; i += 1) {
      h = Math.imul(h ^ seed.charCodeAt(i), 16777619);
    }
    return h >>> 0;
  };
  // N1's three hashes and N2's index walks run from the JSON.
  check('N1 …and 3 289 118 412 mod 3 = 0 — the offset of the (N3) fixture',
    scatterSeedHash('A') % 3, 0);
  check('N1 …the module agrees with an independently written FNV-1a',
    ['', 'A', 'terrain:scatter:ta_1:0:-2,3', 'terrain:scatter:ta_big:7:31,-4']
      .map(scatterSeedHash),
    ['', 'A', 'terrain:scatter:ta_1:0:-2,3', 'terrain:scatter:ta_big:7:31,-4']
      .map(fnv1a));
  check('N1 the hash is UNSIGNED — a negative one would be a negative variant',
    ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'].map(scatterSeedHash)
      .every((h) => h >= 0 && h < 2 ** 32 && Number.isInteger(h)), true);
  // (N2) the formula — the junk the JSON cannot carry
  check('N2 …and neither has n = 0, a negative n or junk — NaN n, NaN candidate',
    [scatterVariantIndex('A', 3, NaN), scatterVariantIndex('A', NaN, 3)], [0, 0]);
  check('N2 …and the answer is always a usable index',
    [1, 2, 3, 4].every((n) => [0, 1, 2, 3, 4, 5, 6, 7].every((i) => {
      const v = scatterVariantIndex(`terrain:scatter:ta_${i}:0:${i},${n}`, i, n);
      return Number.isInteger(v) && v >= 0 && v < n;
    })), true);
  // (N3) the candidate, not the survivor
  const MIX = {
    ring: SQUARE, areaM2: 400, densityPer100m2: 1.25, seed: 'A',
    triesPerPoint: 1, variantCount: 3,
  };
  const MIX_STREAM = [0.10, 0.20, 0.00, 0.25, 0.25, 0.25, 0.50, 0.50, 0.50,
    0.75, 0.30, 0.00, 0.40, 0.80, 0.00];
  /** The ring painted OVER the middle of (N3) — it covers c2 and nothing else. */
  const OCC_MIDDLE = [[8, 8], [12, 8], [12, 12], [8, 12]];
  // N3's three value checks run from the JSON; the runs are kept here for the
  // mutant, bucket and pinned-variant checks below.
  const mixed = scatterInstances({ ...MIX, rng: stream(MIX_STREAM) });
  const subtracted = scatterInstances({
    ...MIX, occluders: [OCC_MIDDLE], rng: stream(MIX_STREAM),
  });
  const survivorMutant = await loadTs(SRC, variantFromSurvivorIndex);
  checkNot('N3 the mutant "count the survivors" does NOT reproduce that',
    survivorMutant.scatterInstances({
      ...MIX, occluders: [OCC_MIDDLE], rng: stream(MIX_STREAM),
    }).map((p) => p.variant), [0, 1, 0, 1]);
  check('N3 …it re-species the wood behind the new shape: 0, 1, 2, 0',
    survivorMutant.scatterInstances({
      ...MIX, occluders: [OCC_MIDDLE], rng: stream(MIX_STREAM),
    }).map((p) => p.variant), [0, 1, 2, 0]);
  check('N3 …and it agrees where nothing was subtracted, which is why it hides',
    survivorMutant.scatterInstances({ ...MIX, rng: stream(MIX_STREAM) })
      .map((p) => p.variant), mixed.map((p) => p.variant));
  // DETERMINISM: the production stream, twice, through the cell sampler.
  const CELL_MIX = {
    ring: [[0, 0], [64, 0], [64, 64], [0, 64]], cx: 0, cz: 0,
    densityPer100m2: 0.2, seed: scatterCellSeed('ta_mix', 0, 0, 0),
    variantCount: 3,
  };
  check('N3 the same cell answers the same mix twice — no load order in it',
    scatterCellInstances(CELL_MIX).map((p) => p.variant),
    scatterCellInstances(CELL_MIX).map((p) => p.variant));
  check('N3 …and it is the formula on the CELL seed, not on anything else',
    scatterCellInstances(CELL_MIX).map((p) => p.variant),
    scatterCellInstances(CELL_MIX).map((_p, i) =>
      scatterVariantIndex(scatterCellSeed('ta_mix', 0, 0, 0), i, 3)));
  // Each cell enters the ring at ITS OWN offset. Not "every neighbour differs"
  // — a hash is allowed to agree with its neighbour, and two of three cells
  // sharing an offset is the arithmetic working, not failing. What must not
  // happen is ONE offset for the whole wood, which would stamp the same mix
  // out every 64 m.
  const cellOffsets = [];
  for (let cz = 0; cz < 4; cz += 1) {
    for (let cx = 0; cx < 4; cx += 1) {
      cellOffsets.push(
        scatterVariantIndex(scatterCellSeed('ta_mix', 0, cx, cz), 0, 3));
    }
  }
  check('N3 …and the 16 cells of a wood do not all enter the ring together',
    new Set(cellOffsets).size, 3);
  // (N4) the regression proof: one variant is the world as it was
  const PLAIN = { ...MIX, variantCount: undefined };
  const plain = scatterInstances({ ...PLAIN, rng: stream(MIX_STREAM) });
  check('N4 without a variant count the instances carry three keys, as ever',
    plain.map((p) => Object.keys(p).sort()),
    plain.map(() => ['x', 'yaw', 'z']));
  for (const n of [undefined, 0, 1]) {
    check(`N4 variantCount ${String(n)} is byte for byte the old answer`,
      scatterInstances({ ...MIX, variantCount: n, rng: stream(MIX_STREAM) }),
      plain);
  }
  check('N4 …and the cell sampler passes that through untouched',
    scatterCellInstances({ ...CELL_MIX, variantCount: 1 }),
    scatterCellInstances({ ...CELL_MIX, variantCount: undefined }));
  check('N4 a mixed cell places the SAME props in the SAME places as a plain one',
    scatterCellInstances(CELL_MIX).map((p) => [p.x, p.z, p.yaw]),
    scatterCellInstances({ ...CELL_MIX, variantCount: 1 })
      .map((p) => [p.x, p.z, p.yaw]));
  // (N5) the meshes — the split `ground.ts buildScatter` builds them from
  const bucketsOf = (points, n) => {
    const buckets = Array.from({ length: n }, () => []);
    for (const p of points) (buckets[p.variant ?? 0] ?? buckets[0]).push(p);
    return buckets;
  };
  check('N5 the (N3) cell fills three buckets 2 / 2 / 1 — three meshes',
    bucketsOf(mixed, 3).map((b) => b.length), [2, 2, 1]);
  check('N5 …with the occluder it is 2 / 2 / 0, so variant 2 gets NO mesh',
    bucketsOf(subtracted, 3).map((b) => b.length), [2, 2, 0]);
  check('N5 …and a split never loses a prop',
    [bucketsOf(mixed, 3).reduce((s, b) => s + b.length, 0),
      bucketsOf(subtracted, 3).reduce((s, b) => s + b.length, 0)],
    [mixed.length, subtracted.length]);
  check('N5 one variant is one bucket — the entry the row always had',
    bucketsOf(plain, 1).map((b) => b.length), [plain.length]);
  // …and that this is really what the client does, pinned by its source (E).
  const mixSrc = await readFile(GROUND_SRC, 'utf8');
  // Since the along rows (2026-09-09) the sampling is the row's own
  // `sample(variantCount, clearM)`; the count still comes from the kinds.
  check('N5 buildScatter tells the sampler how many variants there are',
    mixSrc.includes('sample(kinds.length, clearM)')
      && mixSrc.includes('variantCount,\n'), true);
  check('N5 …buckets the points by the sampler\'s answer, never by a count',
    mixSrc.includes('(buckets[p.variant ?? 0] ?? buckets[0]).push(p)'), true);
  check('N5 …and builds one entry per (row, variant)',
    mixSrc.includes('kinds.forEach((kind, variantPos) => {')
    && mixSrc.includes('const points = buckets[variantPos];'), true);
  check('N5 …skipping a variant nothing picked, so it costs no download',
    /const points = buckets\[variantPos\];[\s\S]{0,400}?if \(!points\.length\) return;/
      .test(mixSrc), true);
  check('N5 the client never CALLS the formula itself — the sampler decides',
    /scatterVariantIndex\(/.test(mixSrc), false);
  check('N5 the payload list it reads is `model_variants` (§ A9)',
    mixSrc.includes('const list = entry.model_variants;'), true);

  // (N6) the pinned variant — the formula's answer replaced, nothing else.
  // Pinned 1 / 9 / -1 and the cell-sampler pair run from the JSON.
  const pinnedRun = (variant) => scatterInstances({ ...MIX, variant, rng: stream(MIX_STREAM) });
  check('N6 NaN is no pin: the formula of (N3), 0 1 2 0 1',
    pinnedRun(NaN).map((p) => p.variant), [0, 1, 2, 0, 1]);
  check('N6 one variant carries no variant key even when pinned',
    scatterInstances({ ...MIX, variantCount: 1, variant: 1, rng: stream(MIX_STREAM) })
      .map((p) => Object.keys(p)), Array(5).fill(['x', 'z', 'yaw']));

  console.log('\n(S) the MINIMUM SPACING — a row\'s own props keep their distance');
  // The 10 x 10 fixture of the header: 5 wanted, one try each, 15 numbers.
  const SPACE_RING = [[0, 0], [10, 0], [10, 10], [0, 10]];
  const SPACE_SAMPLE = {
    ring: SPACE_RING, areaM2: 100, densityPer100m2: 5, seed: 'A',
    triesPerPoint: 1,
  };
  const SPACE_STREAM = [0.10, 0.10, 0.00, 0.30, 0.30, 0.00, 0.50, 0.10, 0.50,
    0.80, 0.40, 0.25, 0.10, 0.50, 0.00];
  const SPACE_ALL = [
    { x: 1, z: 1, yaw: 0 }, { x: 3, z: 3, yaw: 0 },
    { x: 5, z: 1, yaw: Math.PI }, { x: 8, z: 4, yaw: TAU * 0.25 },
    { x: 1, z: 5, yaw: 0 },
  ];
  // S1 (spacing absent / 0 / -1 / null), S2, S4, S5, S7 and S8's true answer
  // run from the JSON; inline stay NaN and the non-number 'far'.
  for (const none of [NaN, 'far']) {
    check(`S1 minSpacingM ${String(none)} is no constraint — the same five`,
      scatterInstances({
        ...SPACE_SAMPLE, minSpacingM: none, rng: stream(SPACE_STREAM),
      }),
      SPACE_ALL);
  }
  // …and on the SEEDED path, where there is no hand-fed stream to keep in
  // step: a world that never touches the field is sampled as it always was.
  const SEEDED = {
    ring: [[0, 0], [100, 0], [100, 100], [0, 100]], areaM2: 10000,
    densityPer100m2: 0.5, seed: scatterSeed('ta_space', 0),
  };
  const seededPlain = scatterInstances(SEEDED);
  check('S1 …and the seeded path is untouched by the option existing',
    [scatterInstances({ ...SEEDED, minSpacingM: 0 }),
      scatterInstances({ ...SEEDED, minSpacingM: undefined })],
    [seededPlain, seededPlain]);
  // (S3) the entry ends thinner than the density asked for, and the run is
  // still the five candidates the budget allows — `stream` throws on a sixth.
  check('S3 four of the five wanted, and no extra try to fill the count',
    scatterInstances({
      ...SPACE_SAMPLE, minSpacingM: 4, rng: stream(SPACE_STREAM),
    }).length,
    4);
  // (S6) the prefix property, with the spacing switched on
  const spacedFull = scatterInstances({ ...SEEDED, minSpacingM: 4 });
  const spacedHead = scatterInstances({ ...SEEDED, minSpacingM: 4, maxPoints: 10 });
  check('S6 a spaced run still plants something to be a prefix OF',
    [spacedFull.length > 10, spacedHead.length], [true, 10]);
  check('S6 …and maxPoints 10 is the first 10 of the very same list',
    spacedHead, spacedFull.slice(0, 10));
  // (S8) the red counter-check: two props 0.2 m apart across a bucket border
  const BUCKET_SAMPLE = {
    ring: SPACE_RING, areaM2: 100, densityPer100m2: 2, seed: 'A',
    triesPerPoint: 1, minSpacingM: 4,
  };
  const BUCKET_STREAM = [0.39, 0.10, 0.00, 0.41, 0.10, 0.00];
  const bucketMutant = await loadTs(SRC, ownBucketOnly);
  const bucketMutantOut = bucketMutant.scatterInstances({
    ...BUCKET_SAMPLE, rng: stream(BUCKET_STREAM),
  });
  checkNot('S8 the "own bucket only" mutant does NOT reproduce that answer',
    bucketMutantOut, [{ x: 3.9, z: 1, yaw: 0 }]);
  check('S8 …it keeps both, 0.2 m apart at an authored 4 m — the defect',
    bucketMutantOut,
    [{ x: 3.9, z: 1, yaw: 0 }, { x: 4.1, z: 1, yaw: 0 }]);

  console.log('\n(P) the placed props\' boxes — scatter does not grow in a bench');
  /** The fixture of the whole section: a 4 x 2 m prop at (5,5), turned 30°.
   *  `half_w`/`half_d` arrive from the server with its margin already in. */
  const PROP_BOX = { id: 'wp_1', x: 5, z: 5, yaw_deg: 30, half_w: 2, half_d: 1 };
  /** The four corners, hand-derived in the header from § A1.1. */
  const PROP_BOX_CORNERS = [
    [2.7679491924311228, 5.133974596215561],
    [6.232050807568877, 3.1339745962155614],
    [7.232050807568877, 4.866025403784439],
    [3.7679491924311228, 6.866025403784439],
  ];
  // (P1) the corners run from the JSON; the block helper has no C# port
  check('P1 …and a whole block comes back as footprints',
    propBoxFootprints([PROP_BOX]), [{ points: PROP_BOX_CORNERS }]);
  // (P2) a box that encloses nothing is no box
  check('P2 a non-finite centre likewise',
    propBoxFootprint({ ...PROP_BOX, x: NaN }), null);
  check('P2 …and the block drops them instead of passing empty outlines',
    propBoxFootprints([{ ...PROP_BOX, half_w: 0 }, PROP_BOX, null]),
    [{ points: PROP_BOX_CORNERS }]);
  check('P2 nothing at all is an empty list', propBoxFootprints(undefined), []);
  // (P3) which of the seven candidates die — see the header for each one
  const BOX_RING = [[0, 0], [10, 0], [10, 10], [0, 10]];
  const BOX_SAMPLE = {
    ring: BOX_RING, areaM2: 100, densityPer100m2: 7, seed: 'p3',
    triesPerPoint: 1,
  };
  const BOX_STREAM = [
    0.5, 0.5, 0, 0.6, 0.5, 0, 0.5, 0.6, 0, 0.32, 0.42, 0,
    0.71, 0.48, 0, 0.1, 0.1, 0, 0.9, 0.9, 0,
  ];
  const BOX_TRUE = [{ x: 3.2, z: 4.2, yaw: 0 }, { x: 1, z: 1, yaw: 0 },
    { x: 9, z: 9, yaw: 0 }];
  // P3's value runs from the JSON (the footprint there is P1's corner list).
  check('P3 …and with no box at all every one of the seven stands',
    scatterInstances({ ...BOX_SAMPLE, rng: stream(BOX_STREAM) }).length, 7);
  // (P4) the red counter-check: the axis-aligned box swaps two of them
  const boxMutant = await loadTs(SRC, axisAlignedPropBox);
  const boxMutantOut = boxMutant.scatterInstances({
    ...BOX_SAMPLE, footprints: boxMutant.propBoxFootprints([PROP_BOX]),
    rng: stream(BOX_STREAM),
  });
  checkNot('P4 the axis-aligned mutant does NOT reproduce that answer',
    boxMutantOut, BOX_TRUE);
  check('P4 …it kills (3.2, 4.2), keeps (7.1, 4.8) and grazes past (5, 6)',
    boxMutantOut,
    [{ x: 5, z: 6, yaw: 0 }, { x: 7.1, z: 4.8, yaw: 0 },
      { x: 1, z: 1, yaw: 0 }, { x: 9, z: 9, yaw: 0 }]);
  // (P5) and (P6) run from the JSON: the location alone, the location plus the
  // enclosed box (both against the hand-derived [(1,1), (9,9)]), and the box
  // under the seeds 'ta_own:0' and 'ta_other:3' (against BOX_TRUE).

  console.log('\n(D) the RED counter-check — a mutant that fails these cases');
  const RED = {
    ring: SQUARE, areaM2: 400, densityPer100m2: 0.5, seed: 's',
    occluders: [OCC_LEFT], triesPerPoint: 2,
  };
  const RED_STREAM = [0.10, 0.20, 0.50, 0.75, 0.25, 0.00, 0.60, 0.80, 0.25];
  const RED_TRUE = [{ x: 15, z: 5, yaw: 0 }, { x: 12, z: 16, yaw: TAU * 0.25 }];
  // The true sampler's answer runs from the JSON; the mutant is compared here.
  const mutant = await loadTs(SRC, yawOnAcceptance);
  const redMutant = mutant.scatterInstances({ ...RED, rng: stream(RED_STREAM) });
  checkNot('D the mutant "yaw only on acceptance" does NOT reproduce that list',
    redMutant, RED_TRUE);
  check('D …its first instance is the hand-derived shifted one',
    redMutant[0], { x: 10, z: 15, yaw: TAU * 0.25 });
  checkNot('D …and it breaks the footprint subtraction (C2) too',
    mutant.scatterInstances({
      ring: SQUARE, areaM2: 400, densityPer100m2: 0.5, seed: 's',
      footprints: [FP_OVER_FIRST],
      triesPerPoint: 1, rng: stream(C1_STREAM),
    }),
    [{ x: 15, z: 5, yaw: 0 }]);

  console.log('\n(E) the client\'s scatter constants — pinned by reading the source');
  const groundSrc = await readFile(GROUND_SRC, 'utf8');
  for (const [name, want] of [
    ['TUFT_HEIGHT_M', 0.8],
    ['TUFT_RADIUS_M', 0.22],
  ]) {
    const m = new RegExp(`const ${name} = (-?[0-9.]+);`).exec(groundSrc);
    check(`E ground.ts ${name} is ${want} m`, m ? Number(m[1]) : null, want);
  }
  // …and the wiring of section (M) on the client side, which is not maths and
  // can only be read: the clearance goes INTO the sampler, and it is derived
  // from the measured spread of the entry's own meshes at its planted height.
  check('E ground.ts hands the clearance to the cell sampler',
    groundSrc.includes('          clearM,\n'), true);
  check('E …derived from the measured spread, or estimated from the height',
    groundSrc.includes(
      'const clearM = scatterClearM(h, spread === null ? null : spread * h);'),
    true);
  check('E …and the measurement is filed where the mesh is grounded',
    groundSrc.includes('noteSpread(url, geometry);'), true);
  // (P6)'s wiring half, on the same source: ONE footprint list, built from the
  // location outlines AND the placed props' boxes, handed to every area.
  check('P6 ground.ts turns the payload boxes into footprints',
    groundSrc.includes('propFootprints = propBoxFootprints(payload.prop_boxes);'),
    true);
  check('P6 …joins them with the location outlines into the ONE list',
    groundSrc.includes('footprints = locFootprints.concat(propFootprints);'),
    true);
  check('P6 …and the drawn location outlines are the other half',
    groundSrc.includes('locFootprints = worldFootprints(locations);'), true);

  // The constants of the LOD, which section (I) derives its expectations from.
  // Loaded here because (G) and (H) below read the same module.
  const {
    SCATTER_TIER_NEAR, SCATTER_TIER_FAR, SCATTER_CULL_FAR, SCATTER_MIN_SHARE,
    SCATTER_MODEL_HEIGHT_M, scatterTargetH,
    SCATTER_SWAY_FACTOR_DEFAULT, scatterSway,
  } = await loadTs(LOD_SRC);
  console.log('\n(F) the display LOD — the four numbers everything is derived from');
  check('F NEAR is 35 m', SCATTER_TIER_NEAR, 35);
  check('F FAR is 45 m', SCATTER_TIER_FAR, 45);
  check('F CULL is 120 m', SCATTER_CULL_FAR, 120);
  check('F the smallest share is a quarter', SCATTER_MIN_SHARE, 0.25);

  console.log('\n(G) how tall a scattered prop is — the prop\'s own height (finding 12, Task 9)');
  // The fallback of (A8) and step 2 of the rule are the same number.
  check('G the flat fallback is 2 m', SCATTER_MODEL_HEIGHT_M, DEFAULT_TARGET_H);
  // (G1), (G2) and (G3) for 0 / -1 / null run from the JSON; NaN stays here.
  check('G3 a prop height of NaN is no answer', scatterTargetH(NaN), 2);
  // (G4) one argument — the row has no height of its own any more
  check('G4 scatterTargetH takes ONE argument', scatterTargetH.length, 1);
  check('G4 a stale row height in the old first slot is read AS the prop height',
    scatterTargetH(4, 8.5), 4);
  // (G5) the red counter-check
  const ignoring = await loadTs(LOD_SRC, ignorePropHeight);
  check('G5 the "always the fallback" mutant answers 2 m for a prop of 8.5 m',
    ignoring.scatterTargetH(8.5), 2);
  checkNot('G5 …which is NOT what the real rule answers', scatterTargetH(8.5), 2);

  console.log('\n(H) the wind factor — kind × prop, the one effective amplitude');
  check('H an absent factor means the FULL amount', SCATTER_SWAY_FACTOR_DEFAULT, 1);
  // (H1)..(H5) run from the JSON; (H3) for NaN and a string stays here.
  for (const [bad, name] of [[NaN, 'NaN'], ['x', 'a string']]) {
    check(`H3 ${name} reads as the full amount, not as nothing`,
      scatterSway(0.06, bad), 0.06);
  }
  // (H6) THE one place — asserted on ground.ts, like (E)
  const swayCalls = groundSrc.match(/scatterSway\(sway, entry\.sway_factor\)/g);
  check('H6 ground.ts multiplies in exactly ONE place',
    swayCalls ? swayCalls.length : 0, 1);
  check('H6 …and that product is what the ScatterProp carries',
    groundSrc.includes('sway: entrySway,'), true);
  check('H6 …the tuft bends by it too, not by the area\'s raw amplitude',
    groundSrc.includes('applySway(mat, entrySway, h);'), true);
  check('H6 no caller passes the unfactored amplitude any more',
    groundSrc.includes('applySway(mat, sway,'), false);
  // (H7) the red counter-check
  const noFactor = await loadTs(LOD_SRC, ignoreSwayFactor);
  check('H7 the "ignore the factor" mutant bends the boulder by 0.06 m',
    noFactor.scatterSway(0.06, 0), 0.06);
  checkNot('H7 …which is NOT what the real product answers',
    scatterSway(0.06, 0), 0.06);

  console.log('\n(H8) the ground offset — how deep a scattered prop stands');
  // The second fact the payload puts on a scatter entry from the PROP's
  // record (§ A9, 2026-08-20). The instances of a painted scatter are seated
  // client-side, so the seat is `heightAt(x, z) + this` — a fir at −0.2 sinks
  // 20 cm into the ground in a wood exactly as it does in a room.
  const { SCATTER_GROUND_OFFSET_LIMIT_M, scatterGroundOffset }
    = await loadTs(LOD_SRC);
  check('H8 the limit is the server\'s own ±5 m', SCATTER_GROUND_OFFSET_LIMIT_M, 5);
  // The stated sink / lift, undefined, null and the ±99 clamp run from the
  // JSON. An absent key is the NORMAL case here (the server ships it only when
  // it differs), so it has to read as "on the ground" and not as anything else.
  for (const [bad, name] of [[NaN, 'NaN'], ['x', 'a string']]) {
    check(`H8 ${name} means "on the ground"`, scatterGroundOffset(bad), 0);
  }
  // The seat itself, hand-derived: ground 12.5 m under the instance, entry at
  // −0.2 → 12.3; the same instance on an entry without the key stays at 12.5.
  check('H8 an instance at ground 12.5 with −0.2 is seated at 12.3',
    12.5 + scatterGroundOffset(-0.2), 12.3);
  check('H8 …and without the key at 12.5 exactly',
    12.5 + scatterGroundOffset(undefined), 12.5);
  // (H8a) THE one place — asserted on ground.ts, like (E)/(H6).
  const sinkCalls = groundSrc.match(
    /scatterGroundOffset\(entry\.ground_offset_m\)/g);
  check('H8a ground.ts reads the offset in exactly ONE place',
    sinkCalls ? sinkCalls.length : 0, 1);
  check('H8a …and every instance is seated with it',
    groundSrc.includes('const y = heightAt(p.x, p.z) + entrySink;'), true);
  check('H8a no seat uses the bare sample any more',
    groundSrc.includes('const y = heightAt(p.x, p.z);'), false);
  // (H8b) the red counter-check
  const noSink = await loadTs(LOD_SRC, ignoreGroundOffset);
  check('H8b the "ignore the offset" mutant seats the fir at 12.5',
    12.5 + noSink.scatterGroundOffset(-0.2), 12.5);
  checkNot('H8b …which is NOT where the real rule seats it',
    12.5 + scatterGroundOffset(-0.2), 12.5);

  console.log('\n(I) the LOD per instance — band, cull edge, stable thinning');
  const {
    SCATTER_LOD_DEFAULTS, SCATTER_UNHIDE_FACTOR,
    instanceTier, instanceShare, instanceVisible,
  } = await loadTs(LOD_SRC);
  const DEF = SCATTER_LOD_DEFAULTS;
  // A configuration that shares no number with the module's, so a function
  // reading the constants instead of its argument cannot pass (I1)/(I2).
  const CFG2 = { nearM: 10, farM: 20, cullM: 60 };
  /** Which of the first `n` instances are drawn at that distance. */
  const drawn = (visible, d, cfg, n = 1000) => {
    const out = [];
    for (let i = 0; i < n; i += 1) if (visible(i, d, cfg)) out.push(i);
    return out;
  };
  /** How often the class CHANGES along a walk — the number the hysteresis is
   *  there to keep down, and what a buffer refill costs. */
  const swaps = (tier, prev, dists, cfg) => {
    let cur = prev;
    let n = 0;
    for (const d of dists) {
      const next = tier(d, cur, cfg);
      if (next !== cur) n += 1;
      cur = next;
    }
    return n;
  };

  check('I the defaults are the constants of (F)',
    [DEF.nearM, DEF.farM, DEF.cullM], [35, 45, 120]);
  check('I an instance re-appears at 0.92 of the cull distance',
    SCATTER_UNHIDE_FACTOR, 0.92);

  // (I1) and (I2) run from the JSON, except the NaN distance and the walk.
  check('I2 a NaN distance hides, whatever stood there',
    [instanceTier(NaN, 0, DEF), instanceTier(NaN, 1, DEF), instanceTier(NaN, 2, DEF)],
    [2, 2, 2]);
  check('I2 drifting across the cull edge costs ONE change, not six',
    swaps(instanceTier, 1, [119.9, 120.1, 119.9, 120.1, 119.9, 120.1], DEF), 1);

  // (I3) the share at the instance's own distance runs from the JSON, but NaN
  check('I3 share of a NaN distance is 0', instanceShare(NaN, DEF), 0);

  // (I4) which instances survive — properties, never a table of hashes
  check('I4 inside the far distance every instance is drawn',
    drawn(instanceVisible, 45, DEF).length, 1000);
  check('I4 past the cull distance none is',
    drawn(instanceVisible, 120.001, DEF).length, 0);
  check('I4 the set at 82.5 m is the SAME set when asked again',
    drawn(instanceVisible, 82.5, DEF), drawn(instanceVisible, 82.5, DEF));
  const near60 = new Set(drawn(instanceVisible, 60, DEF));
  const far105 = drawn(instanceVisible, 105, DEF);
  check('I4 what is drawn at 105 m is still drawn at 60 m (nothing pops away)',
    far105.filter((i) => !near60.has(i)).length, 0);
  for (const [d, cfg, share, label] of [
    [60, DEF, 0.85, 'DEF at 60 m'], [82.5, DEF, 0.625, 'DEF at 82.5 m'],
    [105, DEF, 0.4, 'DEF at 105 m'],
    // THE ROW THAT CHOSE THE HASH — the cull edge, where the share is at its
    // smallest and the tolerance at its tightest (0.9 sigma). The mix in use
    // draws 258 of the ideal 250; the textbook sin-hash draws 215 and fails
    // here alone. See (I4) in the header for the whole derivation.
    [120, DEF, 0.25, 'DEF at 120 m'],
    [40, CFG2, 0.625, 'CFG2 at 40 m'],
  ]) {
    const n = drawn(instanceVisible, d, cfg).length;
    check(`I4 ${label} draws ${1000 * share} of 1000, within 5 % (got ${n})`,
      Math.abs(n - 1000 * share) <= 0.05 * 1000 * share, true);
  }
  // 'I4 instance 0 survives as long as anything of the entry does' runs from the JSON.

  // (I5) the red counter-checks
  const noInstanceBand = await loadTs(LOD_SRC, dropInstanceBand);
  check('I5 the "no band" mutant answers full at 44.9 m for a low instance',
    noInstanceBand.instanceTier(44.9, 1, DEF), 0);
  checkNot('I5 …which is NOT what the real rule answers there',
    instanceTier(44.9, 1, DEF), 0);
  const FLUTTER = [44.9, 45.1, 44.9, 45.1, 44.9, 45.1];
  check('I5 …and it swaps mesh 6 times over a walk across 45 m',
    swaps(noInstanceBand.instanceTier, 1, FLUTTER, DEF), 6);
  check('I5 …where the real rule swaps none',
    swaps(instanceTier, 1, FLUTTER, DEF), 0);
  const rolledHash = await loadTs(LOD_SRC, randomInsteadOfHash);
  const rolledA = new Set(drawn(rolledHash.instanceVisible, 82.5, DEF));
  const rolledB = drawn(rolledHash.instanceVisible, 82.5, DEF);
  const churn = rolledB.filter((i) => !rolledA.has(i)).length;
  check(`I5 the "random" mutant reshuffles the set between two ticks (${churn})`,
    churn > 100, true);
  // …and the mix that was tried FIRST, pinned from both sides: at the cull
  // edge it draws 215 where 250 are wanted, 35 counts outside the +-12.5 the
  // real mix holds — while at 0.4 it would still have passed (380 against a
  // 20-count line). One row apart, one hash chosen.
  const sinHash = await loadTs(LOD_SRC, sinInsteadOfMurmur);
  const sinAt120 = drawn(sinHash.instanceVisible, 120, DEF).length;
  check('I5 the textbook sin-hash draws 215 of 1000 at the cull edge',
    sinAt120, 215);
  check('I5 …which is outside the band the real mix keeps',
    Math.abs(sinAt120 - 250) > 12.5, true);
  check('I5 …while at share 0.4 it would have passed unnoticed',
    Math.abs(drawn(sinHash.instanceVisible, 105, DEF).length - 400) <= 20, true);

  console.log('\n(V) the view cone — what is behind the player is not binned');
  const {
    SCATTER_CONE_MARGIN_RAD, SCATTER_CONE_NEAR_M,
    horizontalFovRad, viewCone, inViewCone,
  } = await loadTs(LOD_SRC);
  const DEG = Math.PI / 180;
  /** The closed form of the header — cos(atan(u) + 30°) without an atan. */
  const coneCos = (u) => (Math.sqrt(3) - u) / (2 * Math.sqrt(1 + u * u));
  /** The 90° fixture: half-fov 45°, cone half-angle 75°. */
  const COS75 = coneCos(1);
  /** A point 100 m out, θ degrees off the +Z axis (positive θ towards +X). */
  const at100 = (thetaDeg) => [100 * Math.sin(thetaDeg * DEG),
    100 * Math.cos(thetaDeg * DEG)];
  /** The test on the 90° fixture, looking down +Z. */
  const seen = (dx, dz, cosHalf = COS75) => inViewCone(dx, dz, 0, 1, cosHalf);

  check('V the margin is 30 degrees', SCATTER_CONE_MARGIN_RAD, Math.PI / 6);
  check('V the near keep is 40 m', SCATTER_CONE_NEAR_M, 40);

  // (V1) the horizontal fov — the three values run from the JSON (the narrow
  // fov there is the header's 53.13010235415598 deg, 2*atan 2 its
  // 2.214297435588181 rad); the degree reading and the junk stay here.
  check('V1 …which is 126.86989764584402 deg',
    horizontalFovRad(90, 2) / DEG, 126.86989764584402, 1e-9);
  for (const [fov, aspect, label] of [
    [0, 1, 'a fov of 0'], [180, 1, 'a fov of 180'], [-45, 1, 'a negative fov'],
    [NaN, 1, 'a NaN fov'], [45, 0, 'an aspect of 0'],
    [45, -2, 'a negative aspect'], [45, NaN, 'a NaN aspect'],
    [45, Infinity, 'an infinite aspect'],
  ]) {
    check(`V1 ${label} is NaN, not a guess`,
      Number.isNaN(horizontalFovRad(fov, aspect)), true);
  }

  // (V2) the cone of one pass — the normalised forwards, cos 75 deg
  // (0.25881904510252074 in the JSON), the degenerate and the 320 deg cones run
  // from the JSON; what needs the smoke's own closed form stays here.
  check('V2 the closed form IS cos 75 deg',
    COS75, (Math.sqrt(6) - Math.sqrt(2)) / 4);
  // the client's own camera: fov 45 on 16:9, tan 22.5 deg = sqrt(2) - 1
  const U_CLIENT = (16 * (Math.SQRT2 - 1)) / 9;
  const clientCone = viewCone(0, 1, horizontalFovRad(45, 16 / 9));
  check('V2 the client camera (45 deg, 16:9) matches the closed form',
    clientCone.cosHalf, coneCos(U_CLIENT));
  check('V2 …and its half-angle lies between 66 and 67 deg',
    [Math.cos(66 * DEG) >= clientCone.cosHalf,
      Math.cos(67 * DEG) >= clientCone.cosHalf],
    [true, false]);
  for (const hfov of [NaN, Infinity]) {
    check(`V2 an hfov of ${hfov} accepts everything`,
      viewCone(0, 1, hfov).cosHalf, -1);
  }
  check('V2 …where cos(190 deg) would have rejected a direction 175 deg off',
    Math.cos(175 * DEG) >= Math.cos(190 * DEG), false);

  // (V3) the 40 m near keep runs from the JSON, but the NaN offsets
  check('V3 a NaN offset is kept, not silently dropped',
    [seen(NaN, 0), seen(0, NaN)], [true, true]);

  // (V4) the angle, both sides of the line and both sides of the axis. Dead
  // ahead (0, 100) and the exact >= pair run from the JSON; the points the
  // `at100` helper computes stay here.
  check('V4 74.9 deg off is in, either way',
    [seen(...at100(74.9)), seen(...at100(-74.9))], [true, true]);
  check('V4 75.1 deg off is out, either way',
    [seen(...at100(75.1)), seen(...at100(-75.1))], [false, false]);
  check('V4 dead behind at 100 m is out', seen(...at100(180)), false);

  // (V5) the margin, against a mutant that cuts at the frustum edge
  const tightCone = await loadTs(LOD_SRC, noConeMargin);
  const tightCos = tightCone.viewCone(0, 1, Math.PI / 2).cosHalf;
  check('V5 the "no margin" mutant cuts at cos 45 deg', tightCos, Math.SQRT1_2);
  check('V5 …and drops a tree 50 deg off the axis',
    tightCone.inViewCone(...at100(50), 0, 1, tightCos), false);
  checkNot('V5 …which is NOT what the real cone answers there',
    seen(...at100(50)), false);

  // (V6) the near keep, against a mutant with the line deleted
  const noKeep = await loadTs(LOD_SRC, noConeNearKeep);
  check('V6 the "no near keep" mutant culls a tuft 5 m behind the camera',
    noKeep.inViewCone(0, -5, 0, 1, COS75), false);
  checkNot('V6 …which is NOT what the real rule answers there',
    seen(0, -5), false);
  check('V6 …and beyond 40 m the two agree again',
    [noKeep.inViewCone(0, -50, 0, 1, COS75), seen(0, -50),
      noKeep.inViewCone(...at100(10), 0, 1, COS75), seen(...at100(10))],
    [false, false, true, true]);

  console.log('\n(W) the seam at the cull line — the billboards continue the '
    + 'mesh thinning');
  const {
    IMPOSTOR_FAR_M, IMPOSTOR_TAIL_FACTOR, IMPOSTOR_WINDOW_CELL_M,
    IMPOSTOR_WINDOW_SPAN_MAX, impostorReachM, impostorShare, impostorVisible,
    impostorWindowSpan, SCATTER_MIN_SHARE: MIN_SHARE,
  } = await loadTs(LOD_SRC);
  // The window constants this file mirrors are the SAMPLER's — pinned against
  // the package, the way (J1) pins the prefs' stored defaults. `scatterLod.ts`
  // may not import them (it has to stay transpile-alone), so this is what keeps
  // the two copies from drifting.
  check('W the mirrored cell edge IS the sampler\'s',
    IMPOSTOR_WINDOW_CELL_M, SCATTER_CELL_M);
  check('W …and the span ceiling is floor(sqrt(4096)/2)',
    IMPOSTOR_WINDOW_SPAN_MAX, Math.floor(Math.sqrt(4096) / 2));
  check('W …so the mirrored span is the sampler\'s for every cull distance',
    [120, 60, 300, 5, 2000].map(impostorWindowSpan),
    [120, 60, 300, 5, 2000].map(scatterCellSpan));

  // (W1) continuity — the two lines meet at the cull distance
  const JUST_PAST = 120.000001;
  // 'W1 the mesh line ends at a quarter' runs from the JSON.
  check('W1 …which is SCATTER_MIN_SHARE itself', MIN_SHARE, 0.25);

  // (W2) the real reach of the cell window

  check('W2 the guaranteed and the axis reach of that window are 128 and 192',
    [2 * 64, 3 * 64], [128, 192]);

  // (W3) the line itself
  const REACH = Math.SQRT2 * 3 * 64;
  check('W3 the tail keeps a quarter of the start', IMPOSTOR_TAIL_FACTOR, 0.25);

  /** The combined line of both stages, sampled every half metre out to 400 m. */
  const walk = (share) => {
    const out = [];
    for (let d = 0; d <= 400.0001; d += 0.5) {
      out.push(d <= DEF.cullM ? instanceShare(d, DEF) : share(d, DEF));
    }
    return out;
  };
  const rises = (line) => line.some((v, i) => i > 0 && v > line[i - 1] + 1e-12);
  const combined = walk(impostorShare);
  check('W3 the walk is 801 samples', combined.length, 801);
  check('W3 …and it never rises — one non-increasing line, no seam',
    rises(combined), false);

  // (W4) the red counter-check: the old rule, restored by mutation
  const oldLine = await loadTs(LOD_SRC, impostorShareRestartsFull);
  check('W4 the old rule restarts at a full 1 just past the cull line',
    oldLine.impostorShare(JUST_PAST, DEF), 1, 1e-6);
  checkNot('W4 …which is NOT what the rule now answers there',
    impostorShare(JUST_PAST, DEF), 1, 1e-6);
  check('W4 the old rule at 190 m -> 1 - (70/280)*0.75 = 0.8125',
    oldLine.impostorShare(190, DEF), 0.8125);
  check('W4 …where the real line is at a sixth of that plus a hair',
    Math.round(impostorShare(190, DEF) * 1e6) / 1e6, 0.163383);
  const oldCombined = [];
  for (let d = 0; d <= 400.0001; d += 0.5) {
    oldCombined.push(d <= DEF.cullM
      ? instanceShare(d, DEF) : oldLine.impostorShare(d, DEF));
  }
  check('W4 …and its combined walk RISES at the seam', rises(oldCombined), true);
  // The counts follow the shares, over the very same indices and the very same
  // hash: 1000 * 0.163383 = 163 against 1000 * 0.8125 = 813 at 190 m. The band
  // is three binomial sigmas (sqrt(1000*p*(1-p)) = 11.7 and 12.3) — what is
  // pinned is that THIS mix lands inside it, as in (I4).
  let now = 0;
  let then = 0;
  for (let i = 0; i < 1000; i += 1) {
    if (impostorVisible(i, 190, DEF)) now += 1;
    if (oldLine.impostorVisible(i, 190, DEF)) then += 1;
  }
  check('W4 about 163 of 1000 billboards are drawn at 190 m',
    now > 128 && now < 198, true);
  check('W4 …where the old rule drew about 813 of them',
    then > 776 && then < 850, true);

  console.log('\n(J) the detail distances as a local setting — prefs.ts');
  const {
    SCATTER_PREFS_KEY, SCATTER_PREF_MIN_M, SCATTER_PREF_MAX_M,
    DEFAULT_SCATTER_PREFS, loadScatterPrefs, saveScatterPrefs, scatterLodCfgOf,
  } = await loadTs(PREFS_SRC);
  const PREF_DEFAULTS = {
    scatterNearM: 35, scatterFarM: 45, scatterCullM: 120,
  };

  // (J1) the same three numbers on both sides, and a key of its own
  check('J1 the stored defaults are 35 / 45 / 120', DEFAULT_SCATTER_PREFS,
    PREF_DEFAULTS);
  check('J1 …which is exactly SCATTER_LOD_DEFAULTS',
    scatterLodCfgOf(DEFAULT_SCATTER_PREFS), DEF);
  check('J1 the store key is its own, not the audio one',
    SCATTER_PREFS_KEY, 'av3d.view.scatter.v1');
  check('J1 a distance runs 5 .. 2000 m',
    [SCATTER_PREF_MIN_M, SCATTER_PREF_MAX_M], [5, 2000]);

  // (J2) reading whatever the store holds
  check('J2 nothing stored yet -> defaults', loadScatterPrefs(null), PREF_DEFAULTS);
  check('J2 unparsable text -> defaults',
    loadScatterPrefs('not json at all'), PREF_DEFAULTS);
  check('J2 JSON null -> defaults', loadScatterPrefs('null'), PREF_DEFAULTS);
  check('J2 an array is not a prefs object',
    loadScatterPrefs('[35,45,120]'), PREF_DEFAULTS);
  check('J2 an empty object -> defaults', loadScatterPrefs('{}'), PREF_DEFAULTS);
  check('J2 a numeric string is not a number',
    loadScatterPrefs('{"scatterFarM":"50"}'), PREF_DEFAULTS);
  check('J2 null is not a number either',
    loadScatterPrefs('{"scatterFarM":null}'), PREF_DEFAULTS);
  check('J2 3 m clamps up to the 5 m floor',
    loadScatterPrefs('{"scatterNearM":3}'), { ...PREF_DEFAULTS, scatterNearM: 5 });
  check('J2 5000 m clamps down to the 2000 m ceiling',
    loadScatterPrefs('{"scatterCullM":5000}'),
    { ...PREF_DEFAULTS, scatterCullM: 2000 });
  check('J2 a stored triple that does not climb falls back COMPLETELY',
    loadScatterPrefs('{"scatterNearM":100}'), PREF_DEFAULTS);
  check('J2 a stored triple that climbs is taken as it stands',
    loadScatterPrefs('{"scatterNearM":20,"scatterFarM":40,"scatterCullM":300}'),
    { scatterNearM: 20, scatterFarM: 40, scatterCullM: 300 });
  const typed = { scatterNearM: 12, scatterFarM: 24, scatterCullM: 90 };
  check('J2 the round trip returns what was stored',
    loadScatterPrefs(saveScatterPrefs(typed)), typed);

  // (J3) and the rename of (J4) run from shared/test-vectors/overview_hud.json
  // in smoke_walk_math.mjs; the cfg {nearM 20, farM 40, cullM 300} that
  // rename yields drives the tier and share cases of (J4) in scatter.json.

  // (Q) THE TURN
  console.log('\n(Q) the turn — scatterYaw, aligned to an axis');
  // Q1..Q3 run from the JSON (an absent angle there is null, which reads as
  // undefined does); the NaN angle stays here.
  check('Q2 aligned without an angle is the axis alone — NaN',
    scatterYaw(0.7, 'aligned', NaN, Math.PI / 2), Math.PI / 2);

  // Q4 without a mode and without axisAt run from the JSON; axisAt is a function.

  const cellYaws = scatterCellInstances({
    ring: SQUARE, cx: 0, cz: 0, densityPer100m2: 1,
    seed: scatterCellSeed('area', 0, 0, 0), yawMode: 'aligned', yawDeg: 45,
    axisAt: () => Math.PI / 4,
  }).map((p) => p.yaw);
  check('Q5 the cell sampler places something on the square', cellYaws.length > 0, true);

  const sided = scatterCellInstances({
    ring: SQUARE, cx: 0, cz: 0, densityPer100m2: 1,
    seed: scatterCellSeed('area', 0, 0, 0), yawMode: 'aligned', yawDeg: 0,
    axisAt: (x) => (x > 10 ? 1 : 0),
  });
  check('Q5 axisAt is asked about the survivor\'s own position',
    sided.every((p) => p.yaw === (p.x > 10 ? 1 : 0)), true);
  let axisCalls = 0;
  const asked = scatterInstances({
    ...MIX, occluders: [OCC_MIDDLE], rng: stream(MIX_STREAM),
    yawMode: 'aligned', yawDeg: 0, axisAt: () => { axisCalls += 1; return 0; },
  });
  check('Q5 …and only for survivors: the (N3) occluder run asks 4 times, not 5',
    [asked.length, axisCalls], [4, 4]);

  // (R) THE SURFACE AXIS
  console.log('\n(R) the surface axis — ringEdgeAxis / lineAxis');
  const {
    ringEdgeAxis, lineAxis, areaAxis, ringSelectedEdges, ribbonSelectedEdges,
    polylabel, ringStations, scatterEdgeInstances, scatterCenterInstance,
  } = await loadBundled(AXIS_SRC);
  const strokeToPolygon = await loadStrokeToPolygon();
  const RECT = [[0, 0], [10, 0], [10, 4], [0, 4]];
  const RECT_CW = [[0, 0], [0, 4], [10, 4], [10, 0]];

  const AXIS_PTS = [[5, 0.5], [9.5, 2], [5, 3.5], [0.5, 2]];
  check('R3 axis + 90° faces INTO the rectangle at every one of the four',
    AXIS_PTS.every(([x, z]) => {
      const a = ringEdgeAxis(RECT, x, z) + Math.PI / 2;
      return pointInRing(x + Math.sin(a) * 0.1, z + Math.cos(a) * 0.1, RECT);
    }), true);
  check('R3 …and the opposite winding reads the same four',
    AXIS_PTS.map(([x, z]) => ringEdgeAxis(RECT_CW, x, z)),
    AXIS_PTS.map(([x, z]) => ringEdgeAxis(RECT, x, z)), 1e-12);

  const CORNER = [[0, 0], [10, 0], [10, 10]];

  // (R6) the edge selection
  const L_SHAPE = [[0, 0], [10, 0], [10, 4], [4, 4], [4, 10], [0, 10]];

  // (R7) the axis over the selected edges

  check('R7 the tie at the centre under [0, 2] goes to edge 0: 3π/2',
    ringEdgeAxis(RECT, 5, 2, [0, 2]), 3 * Math.PI / 2, 1e-12);
  check('R7 absent edges are today\'s answer at the four points and the tie',
    [...AXIS_PTS, [5, 2]].map(([x, z]) => ringEdgeAxis(RECT, x, z)),
    [3 * Math.PI / 2, Math.PI, Math.PI / 2, 0, 3 * Math.PI / 2], 1e-12);

  // (R8) the road sides of a ribbon
  const ROAD = strokeToPolygon([[0, 0], [100, 0]], 6);
  check('R8 the straight road at width 6 is the band (0,−3) (100,−3) (100,3) (0,3)',
    ROAD, [[0, -3], [100, -3], [100, 3], [0, 3]]);
  check('R8 absent, "all" and an unknown word are every edge of the band',
    [ribbonSelectedEdges(ROAD), ribbonSelectedEdges(ROAD, 'all'),
      ribbonSelectedEdges(ROAD, 'sideways')],
    [[0, 1, 2, 3], [0, 1, 2, 3], [0, 1, 2, 3]]);

  const BEND = strokeToPolygon([[0, 0], [50, 0], [50, 50]], 6);
  check('R8 the bend miters to (0,−3) (53,−3) (53,50) (47,50) (47,3) (0,3)',
    BEND, [[0, -3], [53, -3], [53, 50], [47, 50], [47, 3], [0, 3]]);

  const BEND_R = strokeToPolygon([[0, 0], [50, 0], [50, -50]], 6);
  check('R8 the mirrored bend: (0,−3) (47,−3) (47,−50) (53,−50) (53,3) (0,3)',
    BEND_R, [[0, -3], [47, -3], [47, -50], [53, -50], [53, 3], [0, 3]]);

  // (T) THE POLE OF INACCESSIBILITY
  console.log('\n(T) the pole of inaccessibility — polylabel');
  /** The smoke's OWN distance to the ring's edges — the derivation's ruler,
   *  never the module's. */
  const edgeDistance = (ring, x, z) => {
    let best = Infinity;
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i, i += 1) {
      const [ax, az] = ring[j];
      const [bx, bz] = ring[i];
      const dx = bx - ax;
      const dz = bz - az;
      const t = Math.min(1, Math.max(0, ((x - ax) * dx + (z - az) * dz) / (dx * dx + dz * dz)));
      best = Math.min(best, Math.hypot(x - (ax + t * dx), z - (az + t * dz)));
    }
    return best;
  };
  const poleRect = polylabel(RECT);

  check('T1 …with d in [1.5, 2] — 2 is the most any point can have',
    poleRect.d >= 1.5 && poleRect.d <= 2 + 1e-9, true);
  check('T1 …and d is the ring distance of the answered point',
    poleRect.d, edgeDistance(RECT, poleRect.x, poleRect.z), 1e-9);
  const poleL = polylabel(L_SHAPE);
  check('T2 the L-shape: the pole lies in the ring', pointInRing(poleL.x, poleL.z, L_SHAPE), true);
  check('T2 …with d >= 1.9', poleL.d >= 1.9, true);
  check('T2 …and d is the ring distance of the answered point',
    poleL.d, edgeDistance(L_SHAPE, poleL.x, poleL.z), 1e-9);
  check('T2 the centroid (4.5, 3.875) is only 0.125 m from the inner edge',
    edgeDistance(L_SHAPE, 4.5, 3.875), 0.125, 1e-9);
  check('T2 …and the pole beats it by more than the precision',
    poleL.d >= edgeDistance(L_SHAPE, 4.5, 3.875) - 0.5, true);
  check('T2 a finer precision only gets closer to 2', polylabel(L_SHAPE, 0.05).d >= 1.95, true);

  // (U) STATIONS ALONG THE RING
  console.log('\n(U) stations along the ring — ringStations');
  const U_OPTS = { spacingM: 7, offsetM: 1 };
  const u1 = ringStations(RECT, U_OPTS);

  check('U1 …all four in the ring', u1.every((s) => pointInRing(s.x, s.z, RECT)), true);

  check('U2 startM past the spacing clamps to it: three stations',
    ringStations(RECT, { ...U_OPTS, startM: 100 }).map((s) => [s.x, s.z, s.ordinal]),
    [[7, 1, 0], [10, 3, 1], [3, 3, 2]], 1e-9);

  // (U4) the spacing jitter — its own stream, one draw per candidate

  check('U4 the real stream is seededRandom(seed + \':jitter\')',
    ringStations(RECT, { ...U_OPTS, jitterM: 2, seed: 'r' }),
    ringStations(RECT, { ...U_OPTS, jitterM: 2, jitterRng: seededRandom('r:jitter') }));
  checkNot('U4 …and it is not the yaw stream of the seed',
    ringStations(RECT, { ...U_OPTS, jitterM: 2, seed: 'r' }).map((s) => s.x),
    ringStations(RECT, { ...U_OPTS, jitterM: 2, jitterRng: seededRandom('r') }).map((s) => s.x));
  // (U5) the sides

  check('U5 …and so is an absent word', ringStations(RECT, { ...U_OPTS, sides: undefined }), u1);

  // (U6) the chain runs — `edges`, the road sides of (R8)
  const ROAD_OPTS = { spacingM: 25, offsetM: 1 };
  const road = (ring, sides) => ringStations(ring, {
    ...ROAD_OPTS, edges: ribbonSelectedEdges(ring, sides),
  }).map((s) => [s.x, s.z, s.axis, s.ordinal]);

  check('U6 no station stands on a road end',
    road(ROAD, 'opposite').every(([x]) => x > 0 && x < 100), true);
  const SPLIT = strokeToPolygon([[0, 0], [40, 0], [100, 0]], 6);
  check('U6 the road clicked at x = 40 is the six-point band',
    SPLIT, [[0, -3], [40, -3], [100, -3], [100, 3], [40, 3], [0, 3]]);

  check('U6 …which a run per edge would not: 52.5 and 77.5 on the second edge',
    ringStations(SPLIT, { ...ROAD_OPTS, edges: [1] }).map((s) => s.x),
    [52.5, 77.5], 1e-12);
  const rim = ringStations(ROAD, ROAD_OPTS);
  check('U6 the whole rim: side A, then side B from 6.5 m in — 93.5, not 87.5',
    rim.map((s) => [s.x, s.z, s.ordinal]),
    [[12.5, -2, 0], [37.5, -2, 1], [62.5, -2, 2], [87.5, -2, 3],
      [93.5, 2, 4], [68.5, 2, 5], [43.5, 2, 6], [18.5, 2, 7]], 1e-12);
  check('U6 …and an `edges` list of every edge is that walk byte for byte',
    ringStations(ROAD, { ...ROAD_OPTS, edges: ribbonSelectedEdges(ROAD, 'all') }), rim);

  check('U6 an index no edge carries is skipped, an empty list places nothing',
    [ringStations(ROAD, { ...ROAD_OPTS, edges: [0, 99] }).length,
      ringStations(ROAD, { ...ROAD_OPTS, edges: [] }).length], [4, 0]);

  // (V) THE OCCUPANCY GRID
  console.log('\n(V) the occupancy grid — OccupancyGrid and the fifth verdict');
  const { cellOccupancy } = await loadBundled(OCCUPANCY_SRC);
  // (V6) the routing adapter of a pass — see the header
  const v6Grids = new Map();
  const v6 = cellOccupancy(v6Grids);
  v6.grid.add(10, 10, 1);
  check('V6 a station in cell (0,0) is filed in grid "0,0" and in no other',
    [[...v6Grids.keys()], v6Grids.get('0,0').blocks(10, 10, 0.1)], [['0,0'], true]);
  check('V6 blocks asks the cell of the QUERIED point: (10.5, 10) is (0,0), 0.5 < 2, blocked',
    v6.grid.blocks(10.5, 10, 1), true);
  check('V6 …(70, 10) is cell (1,0), nobody there, and no grid is made for asking',
    [v6.grid.blocks(70, 10, 1), v6Grids.has('1,0')], [false, false]);
  v6.grid.add(63.5, 10, 1);
  check('V6 (64.2, 10) is 0.7 m from it but over the border: its own cell answers',
    [v6.grid.blocks(64.2, 10, 1), v6.grid.blocks(63.6, 10, 1)], [false, true]);
  check('V6 gridOf hands the very grid the adapter filed into, and makes one on demand',
    [v6.gridOf(0, 0) === v6Grids.get('0,0'), v6Grids.has('1,0'),
      v6.gridOf(1, 0) === v6Grids.get('1,0'), v6Grids.size], [true, false, true, 2]);
  // (V7) the routing adapter passes tags through to its cell grid.
  v6.grid.add(30, 30, 1, 'a');
  check('V7 the routing adapter passes the tag through on add and blocks',
    [v6.grid.blocks(30.5, 30, 1, 'a'), v6.grid.blocks(30.5, 30, 1, 'b'),
      v6Grids.get('0,0').blocks(30.5, 30, 1, 'a')], [false, true, false]);

  // (W) THE EPOCH
  console.log('\n(W) the epoch — reshuffleEpoch and the seed suffix');
  // W1's three epochs and W2's seeds run from the JSON; `undefined` as a
  // RESULT and a NaN epoch cannot be written there.
  check('W1 no interval, 0, negative or a junk clock is undefined',
    [reshuffleEpoch(3600), reshuffleEpoch(3600, 0), reshuffleEpoch(3600, -5),
      reshuffleEpoch(NaN, 60)], [undefined, undefined, undefined, undefined]);
  check('W2 an undefined or NaN epoch adds nothing — NaN',
    [scatterCellSeed('a', 1, 2, 3, NaN), scatterSeed('a', 1, NaN)],
    ['terrain:scatter:a:1:2,3', 'terrain:scatter:a:1']);

  // (X) THE EDGE AND CENTRE SAMPLERS
  console.log('\n(X) the edge and centre samplers');
  const EDGE = { spacingM: 7, offsetM: 1, seed: 'x', yawMode: 'aligned', yawDeg: 0 };

  const X_BLOCK = { points: [[3, 0.5], [4, 0.5], [4, 1.5], [3, 1.5]] };
  const x2 = scatterEdgeInstances(RECT, {
    ...EDGE, variantCount: 3, footprints: [X_BLOCK], clearM: 0.2,
  });

  check('X2 …the unblocked run carries 0..3 of the same formula',
    scatterEdgeInstances(RECT, { ...EDGE, variantCount: 3 }).map((p) => p.variant),
    [0, 1, 2, 3].map((k) => scatterVariantIndex('x', k, 3)));

  // (X9) the pinned variant on the rim — see (N6)
  const x9 = (variant) => scatterEdgeInstances(RECT, {
    ...EDGE, variantCount: 3, footprints: [X_BLOCK], clearM: 0.2, variant,
  });
  check('X9 a pinned variant keeps the (X2) survivors and their yaws',
    x9(2).map((p) => [p.x, p.z, p.yaw]), x2.map((p) => [p.x, p.z, p.yaw]), 1e-12);

  const x3Ref = seededRandom('x');
  check('X3 no mode: one seeded draw per station, positions unmoved',
    scatterEdgeInstances(RECT, { spacingM: 7, offsetM: 1, seed: 'x' })
      .map((p) => [p.x, p.z, p.yaw]),
    [[3.5, 1], [9, 0.5], [6.5, 3], [1, 3.5]].map(([x, z]) => [x, z, x3Ref() * TAU]), 1e-9);

  const rimRow = [[3.5, 0], [10, 0.5], [6.5, 4], [0, 3.5]];

  check('X8 …and so does an absent offset',
    scatterEdgeInstances(RECT, { spacingM: 7, seed: 'x' }).map((p) => [p.x, p.z]), rimRow, 1e-9);

  // (X10) the sides

  check('X10 …carrying the variants of ordinals 0 and 1',
    scatterEdgeInstances(RECT, { ...EDGE, sides: 'opposite', variantCount: 3 }).map((p) => p.variant),
    [0, 1].map((k) => scatterVariantIndex('x', k, 3)));

  // (X11) the road sides — `edges` through the sampler

  const CENTRE = { seed: 'x', yawMode: 'aligned', yawDeg: 0, variantCount: 3, variant: 2 };

  check('X5 no pin: the formula with ordinal 0',
    scatterCenterInstance(RECT, { ...CENTRE, variant: undefined })[0]?.variant,
    scatterVariantIndex('x', 0, 3));
  check('X5 one variant carries no variant key',
    Object.keys(scatterCenterInstance(RECT, { ...CENTRE, variantCount: 1 })[0] ?? {}),
    ['x', 'z', 'yaw']);
  const askedAt = [];
  check('X6 axisAt wins over the ring',
    scatterCenterInstance(RECT, {
      ...CENTRE, axisAt: (x, z) => { askedAt.push([x, z]); return 1; },
    })[0]?.yaw, 1, 1e-12);
  check('X6 …and was asked at the pole', askedAt, [[5, 2]], 0.5);
  check('X6 no mode: the seeded draw',
    scatterCenterInstance(RECT, { seed: 'x' })[0]?.yaw, seededRandom('x')() * TAU, 1e-12);

  console.log(`\n${passed} ok, ${failed} failed`);
  process.exit(failed ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
