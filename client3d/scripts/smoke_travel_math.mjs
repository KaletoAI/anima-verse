#!/usr/bin/env node
/**
 * Smoke check for the pure journey maths of the 3D client
 * (plan-freie-weltkarte-e4-3d-client.md, task 4) —
 * `client3d/src/scene/travelPath.ts`.
 *
 * Usage:  node client3d/scripts/smoke_travel_math.mjs
 *
 * Same discipline as `client3d/scripts/smoke_ground_math.mjs` and
 * `client3d/scripts/smoke_walk_math.mjs`: every expected number below is derived BY
 * HAND from the contract (§ A11 of docs/schnittstellen-3d.md), written out in
 * this header, and NEVER recorded from the current output. A check that only
 * pins today's result proves nothing.
 *
 * `travelPath.ts` has NO import at all — not even a type-only one — so a plain
 * esbuild transpile is enough to load it here. If someone ever puts a runtime
 * import into it, this loader fails loudly, which is the intended alarm: the
 * module is the shared arc-length truth of `main.ts` (route build) and
 * `npcs.ts` (per-frame extrapolation) and must stay checkable without a
 * bundler, a DOM or three.
 *
 * ===========================================================================
 * THE CONTRACT (§ A11), in one formula
 * ===========================================================================
 * A journey is a polyline of world points in METRES, `waypoints`, plus ONE
 * number: `progress_m`, the distance already walked ALONG that polyline. The
 * position is
 *
 *     d = progress_m
 *     for i = 0 … n-2:
 *         L = |w[i+1] - w[i]|
 *         if d <= L:  pos = lerp(w[i], w[i+1], d / L);  done
 *         d -= L
 *     else:           pos = w[n-1]
 *
 * There is deliberately NO segment index in the payload — it would be a second
 * truth beside `progress_m`. Everything below checks exactly this walk, the
 * capped extrapolation between polls, and the snap threshold that reconciles
 * the local extrapolation with a fresh server number.
 *
 * --- The polylines used, and their hand-measured lengths --------------------
 *
 * (P) THE PLAN'S CASE — an L in the XZ plane:  [[0,0], [10,0], [10,20]]
 *       segment 0: (0,0) -> (10,0)    length sqrt(10^2 + 0^2)  = 10
 *       segment 1: (10,0) -> (10,20)  length sqrt(0^2 + 20^2)  = 20
 *       total = 10 + 20 = 30 m
 *
 * (Q) A DIAGONAL, so nothing can pass by only ever moving on an axis:
 *     [[0,0], [3,4]]
 *       segment 0: length sqrt(9 + 16) = sqrt(25) = 5      (the 3-4-5 triangle)
 *       total = 5 m
 *
 * (R) A CORNER with a diagonal leg:  [[0,0], [3,4], [-3,4]]
 *       segment 0: sqrt(9 + 16)          = 5
 *       segment 1: |(-3,4) - (3,4)|      = 6
 *       total = 11 m
 *
 * (D) A DUPLICATE point (the server rounds waypoints to 2 decimals, so two
 *     consecutive ones can collapse):  [[0,0], [0,0], [10,0]]
 *       segment 0: length 0     <- must NOT produce a 0/0 lerp
 *       segment 1: length 10
 *       total = 10 m
 *
 * (S) A SINGLE point (§ A11: "the formula copes with a degenerate one-point
 *     line — a journey without a way"):  [[7,-2]]   total = 0 m
 *
 * --- pointAtDistance on (P) -------------------------------------------------
 *   d = 0    ->  first segment, d <= 10, t = 0/10 = 0
 *                lerp((0,0),(10,0),0)          = (0, 0)
 *   d = 5    ->  d <= 10, t = 5/10 = 0.5
 *                lerp((0,0),(10,0),0.5)        = (5, 0)          <- plan case
 *   d = 10   ->  d <= 10, t = 1
 *                lerp((0,0),(10,0),1)          = (10, 0)         <- the node
 *   d = 15   ->  15 > 10, so d := 15 - 10 = 5; segment 1, L = 20, 5 <= 20,
 *                t = 5/20 = 0.25
 *                lerp((10,0),(10,20),0.25)     = (10, 0 + 0.25*20) = (10, 5)
 *                                                                 <- plan case
 *   d = 22.5 ->  d := 12.5; t = 12.5/20 = 0.625 -> (10, 12.5)
 *   d = 30   ->  d := 20; t = 20/20 = 1         -> (10, 20)       <- the end
 *   d = 42   ->  past the end: the loop leaves and the LAST point stands
 *                                              -> (10, 20)
 *   d = -3   ->  before the start, clamped     -> (0, 0)
 *
 * --- pointAtDistance on (Q), the diagonal -----------------------------------
 *   d = 2.5  ->  t = 2.5/5 = 0.5
 *                lerp((0,0),(3,4),0.5) = (1.5, 2)
 *   d = 1    ->  t = 0.2 -> (0.6, 0.8)      (the unit vector is (0.6, 0.8))
 *
 * --- pointAtDistance on (R), across the corner ------------------------------
 *   d = 5    ->  exactly the corner                       -> (3, 4)
 *   d = 8    ->  d := 8 - 5 = 3 on segment 1 (direction (-1, 0), L = 6),
 *                t = 3/6 = 0.5 -> lerp((3,4),(-3,4),0.5)  -> (0, 4)
 *   d = 11   ->  the end                                   -> (-3, 4)
 *
 * --- pointAtDistance on (D), the duplicate ----------------------------------
 *   d = 0    ->  segment 0 has L = 0. `d <= L` would be TRUE with d = 0 and
 *                the lerp would be 0/0 = NaN, so a zero-length segment is
 *                skipped instead: segment 1, t = 0 -> (0, 0)
 *   d = 4    ->  segment 0 skipped (nothing subtracted), segment 1 t = 0.4
 *                                                        -> (4, 0)
 *
 * --- pointAtDistance on (S) and on nothing ----------------------------------
 *   (S), any d  ->  the one point                          -> (7, -2)
 *   []          ->  no line at all                         -> null
 *
 * --- clampProgress ----------------------------------------------------------
 * `progress_m` from the payload is trusted but not blindly: it is pinned into
 * [0, total], so no NaN can ever reach the walk (a NaN position silently
 * removes the figure from the picture). NaN is the ONE value with no place on
 * the line and becomes 0; an infinity is merely an over-run and clamps like
 * any other number.
 *   clampProgress(5, 30)        = 5
 *   clampProgress(-4, 30)       = 0
 *   clampProgress(41, 30)       = 30
 *   clampProgress(NaN, 30)      = 0
 *   clampProgress(Infinity, 30) = 30     (an over-run, not a nonsense value)
 *   clampProgress(5, 0)         = 0      (degenerate line: nothing to walk)
 *
 * --- advanceProgress: the capped extrapolation ------------------------------
 * Between two worldmap polls the client moves the figure itself:
 *     progress' = clamp(clamp(progress) + rate * dt, 0, total)
 * — the incoming value is pinned onto the line FIRST, so a negative
 * `progress_m` starts the frame at the beginning and walks from there, rather
 * than spending its first metres crawling back to zero.
 * `rate` is METRES PER REAL SECOND — `pace_m_s_real ?? speed_m_s_real` — and
 * `null` means "do not extrapolate" (frozen world, arrived, degenerate
 * segment). The clamp at `total` is the binding cap of the plan: the figure
 * never walks past the end of its own polyline while it waits for the server
 * to book the arrival.
 *   advanceProgress(5,    2,    1,   30) = 5 + 2      = 7
 *   advanceProgress(5,    1.4,  0.5, 30) = 5 + 0.7    = 5.7
 *   advanceProgress(28,   4,    1,   30) = 32 -> capped        = 30   <- plan
 *   advanceProgress(28.4, 3.4,  0.5, 30) = 28.4 + 1.7 = 30.1 -> capped = 30
 *   advanceProgress(30,   2,    1,   30) = 32 -> capped        = 30
 *   advanceProgress(5,    null, 1,   30) = 5           (frozen: no movement)
 *   advanceProgress(5,    0,    1,   30) = 5           (rate 0 is no rate)
 *   advanceProgress(5,    -2,   1,   30) = 5           (a negative rate is junk)
 *   advanceProgress(5,    2,    0,   30) = 5           (no time passed)
 *   advanceProgress(-5,   1,    1,   30) = clamp(-5) = 0, then 0 + 1*1 = 1
 *
 * And the two composed, which is what the frame loop actually does — the plan
 * case: standing at 28 m on (P) with 4 m/s for one second lands ON the end
 * point, not past it:
 *   pointAtDistance(P, advanceProgress(28, 4, 1, 30))
 *     = pointAtDistance(P, 30) = (10, 20)
 *
 * --- catchUpStep: how far the FIGURE moves towards that point ---------------
 * The rendered figure does not jump onto the interpolated point, it walks
 * there, so a poll correction stays a walk:
 *     step = min(distance, max(walkSpeed, rate) * dt)
 * `npcs.ts` hands in its own `WALK_SPEED` (3.4 m/s), which is why the constant
 * appears as a literal here rather than as an import — the module is pure and
 * knows nothing about the figure library.
 *
 * The `max` is the point of it. A fixed 3.4 m/s is a BRAKE, not a smoother:
 * `pace_m_s_real` already carries the game time factor (§ A11), so with the
 * demo pace of 1.4 m/s a factor above 3.4 / 1.4 = 2.43 makes the interpolated
 * point outrun the figure — it would lag behind its own journey for the whole
 * trip and then teleport when the travel block vanishes.
 *   catchUpStep(10, null, 1,   3.4) = min(10, max(3.4, 0)*1)   = 3.4
 *       (frozen world: the figure may still walk off a correction)
 *   catchUpStep(10, 2,    1,   3.4) = min(10, max(3.4, 2)*1)   = 3.4
 *       (a SLOW journey does not slow the correction below a walk)
 *   catchUpStep(10, 5.6,  1,   3.4) = min(10, max(3.4, 5.6)*1) = 5.6
 *       (1.4 m/s at time factor 4 — the case the fix exists for)
 *   catchUpStep(10, 5.6,  0.5, 3.4) = min(10, 5.6*0.5)         = 2.8
 *   catchUpStep(1,  5.6,  1,   3.4) = min(1, 5.6)              = 1
 *       (never past the point it is correcting towards)
 *   catchUpStep(10, -5,   1,   3.4) = a junk rate is no rate    = 3.4
 *   catchUpStep(0,  5.6,  1,   3.4) = nothing to correct        = 0
 *   catchUpStep(10, 5.6,  0,   3.4) = no time passed            = 0
 *
 * --- shouldSnap: reconciling with a fresh server number ---------------------
 * The local extrapolation drifts (segment changes between polls, a paused
 * tab, a rate that changed with the terrain). When a genuinely NEW payload
 * arrives, the client adopts the server's `progress_m` only if the two are
 * further apart than TRAVEL_SNAP_M — otherwise the local number keeps running
 * and poll jitter does not make the figure stutter. The threshold is ABSOLUTE
 * METRES since E4 (v1 compared 0.5 CELLS, a unit that no longer exists).
 *   TRAVEL_SNAP_M = 2
 *   shouldSnap(10, 8)     -> |2|   > 2 ? no   -> false  (exactly on it: keep)
 *   shouldSnap(10, 7.9)   -> |2.1| > 2 ? yes  -> true
 *   shouldSnap(10, 12.5)  -> |2.5| > 2 ? yes  -> true   (local ran AHEAD)
 *   shouldSnap(0, 0)      -> 0                -> false
 *   shouldSnap(3, 2.5)    -> 0.5              -> false
 */
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');
const SRC = join(ROOT, 'client3d/src/scene/travelPath.ts');

async function loadTravelPath() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'travelmath-'));
  try {
    const source = await readFile(SRC, 'utf8');
    const out = esbuild.transformSync(source, { loader: 'ts', format: 'esm' });
    const file = join(dir, 'travelPath.mjs');
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
  return a === b;
}

// The polylines of the header, once, so every check reads against the same
// geometry the derivation above is written for.
const P = [[0, 0], [10, 0], [10, 20]];
const Q = [[0, 0], [3, 4]];
const R = [[0, 0], [3, 4], [-3, 4]];
const D = [[0, 0], [0, 0], [10, 0]];
const S = [[7, -2]];

async function main() {
  const { polylineLength, pointAtDistance, clampProgress, advanceProgress,
          catchUpStep, shouldSnap, TRAVEL_SNAP_M } = await loadTravelPath();
  // What `npcs.ts` hands in as its walking pace; kept as a literal because
  // this module is pure and must not import the figure code.
  const WALK = 3.4;

  console.log('polylineLength — the sum of the segment lengths, in metres');
  check('(P) 10 + 20', polylineLength(P), 30);
  check('(Q) the 3-4-5 diagonal', polylineLength(Q), 5);
  check('(R) 5 + 6', polylineLength(R), 11);
  check('(D) a duplicate point adds nothing', polylineLength(D), 10);
  check('(S) one point is no way at all', polylineLength(S), 0);
  check('no points either', polylineLength([]), 0);
  check('a missing polyline is 0, not a throw', polylineLength(null), 0);

  console.log('\npointAtDistance on (P) — the § A11 walk');
  check('d = 0 is the start', pointAtDistance(P, 0), [0, 0]);
  check('d = 5 is halfway along the first leg', pointAtDistance(P, 5), [5, 0]);
  check('d = 10 lands exactly on the corner', pointAtDistance(P, 10), [10, 0]);
  check('d = 15 is a quarter up the second leg', pointAtDistance(P, 15), [10, 5]);
  check('d = 22.5 is five eighths up it', pointAtDistance(P, 22.5), [10, 12.5]);
  check('d = 30 is the end', pointAtDistance(P, 30), [10, 20]);
  check('d = 42 cannot go past the end', pointAtDistance(P, 42), [10, 20]);
  check('d = -3 cannot go before the start', pointAtDistance(P, -3), [0, 0]);
  check('a NaN distance is treated as 0, never as a NaN point',
    pointAtDistance(P, NaN), [0, 0]);

  console.log('\npointAtDistance on the other shapes');
  check('(Q) halfway down the diagonal', pointAtDistance(Q, 2.5), [1.5, 2]);
  check('(Q) one metre along it', pointAtDistance(Q, 1), [0.6, 0.8]);
  check('(R) exactly on the corner', pointAtDistance(R, 5), [3, 4]);
  check('(R) three metres past it', pointAtDistance(R, 8), [0, 4]);
  check('(R) the far end', pointAtDistance(R, 11), [-3, 4]);
  check('(D) a zero-length segment does not make a NaN',
    pointAtDistance(D, 0), [0, 0]);
  check('(D) …and does not eat any distance either',
    pointAtDistance(D, 4), [4, 0]);
  check('(S) a one-point line is that point', pointAtDistance(S, 0), [7, -2]);
  check('(S) …at any distance', pointAtDistance(S, 99), [7, -2]);
  check('an empty polyline has no point', pointAtDistance([], 3), null);
  check('and neither has a missing one', pointAtDistance(null, 3), null);

  console.log('\nclampProgress — nothing outside the line, and never a NaN');
  check('inside stays put', clampProgress(5, 30), 5);
  check('below zero is the start', clampProgress(-4, 30), 0);
  check('past the end is the end', clampProgress(41, 30), 30);
  check('NaN is the start', clampProgress(NaN, 30), 0);
  check('Infinity is the end', clampProgress(Infinity, 30), 30);
  check('a zero-length line has only 0', clampProgress(5, 0), 0);

  console.log('\nadvanceProgress — extrapolation, capped at the polyline end');
  check('two metres a second for one second', advanceProgress(5, 2, 1, 30), 7);
  check('1.4 m/s for half a second', advanceProgress(5, 1.4, 0.5, 30), 5.7);
  check('the cap holds at the end', advanceProgress(28, 4, 1, 30), 30);
  check('…and it holds on a fraction too', advanceProgress(28.4, 3.4, 0.5, 30), 30);
  check('standing on the end stays on the end', advanceProgress(30, 2, 1, 30), 30);
  check('a frozen world does not extrapolate', advanceProgress(5, null, 1, 30), 5);
  check('rate 0 is no rate', advanceProgress(5, 0, 1, 30), 5);
  check('a negative rate is junk, not a walk backwards',
    advanceProgress(5, -2, 1, 30), 5);
  check('no time passed, no metres walked', advanceProgress(5, 2, 0, 30), 5);
  check('a NaN rate moves nothing', advanceProgress(5, NaN, 1, 30), 5);
  check('a NaN dt moves nothing', advanceProgress(5, 2, NaN, 30), 5);
  check('below zero starts at the start and walks from there',
    advanceProgress(-5, 1, 1, 30), 1);

  console.log('\nthe two composed — one frame of the loop on (P)');
  check('28 m + 4 m/s * 1 s lands ON the end, not past it',
    pointAtDistance(P, advanceProgress(28, 4, 1, 30)), [10, 20]);
  check('5 m + 2 m/s * 2.5 s is 10 m: the corner',
    pointAtDistance(P, advanceProgress(5, 2, 2.5, 30)), [10, 0]);
  check('a frozen journey stays where it is',
    pointAtDistance(P, advanceProgress(15, null, 1, 30)), [10, 5]);

  console.log('\ncatchUpStep — the walk towards the interpolated point');
  check('a frozen journey still walks its correction off',
    catchUpStep(10, null, 1, WALK), 3.4);
  check('a journey slower than a walk does not slow the correction',
    catchUpStep(10, 2, 1, WALK), 3.4);
  check('1.4 m/s at time factor 4: the journey pace wins',
    catchUpStep(10, 5.6, 1, WALK), 5.6);
  check('…and it scales with dt like everything else',
    catchUpStep(10, 5.6, 0.5, WALK), 2.8);
  check('never past the point it corrects towards',
    catchUpStep(1, 5.6, 1, WALK), 1);
  check('a negative rate is junk, the walk stands',
    catchUpStep(10, -5, 1, WALK), 3.4);
  check('nothing to correct, no step', catchUpStep(0, 5.6, 1, WALK), 0);
  check('no time passed, no step', catchUpStep(10, 5.6, 0, WALK), 0);
  check('a NaN distance moves nothing', catchUpStep(NaN, 5.6, 1, WALK), 0);
  // The regression this exists for, stated as the inequality it is: at the
  // demo pace of 1.4 m/s the figure keeps up until the time factor pushes the
  // journey past a walk, and from there the step must FOLLOW the journey.
  check('below factor 3.4/1.4 the walk is still the bound',
    catchUpStep(10, 1.4 * 2, 1, WALK), 3.4);
  check('above it the journey pace is', catchUpStep(10, 1.4 * 3, 1, WALK), 4.2);

  console.log('\nshouldSnap — adopt the server number only past 2 metres');
  check('the threshold is two metres', TRAVEL_SNAP_M, 2);
  check('exactly two metres apart: keep the local value', shouldSnap(10, 8), false);
  check('2.1 m apart: snap', shouldSnap(10, 7.9), true);
  check('the local value ran ahead by 2.5 m: snap', shouldSnap(10, 12.5), true);
  check('no difference at all', shouldSnap(0, 0), false);
  check('half a metre of poll jitter is not a snap', shouldSnap(3, 2.5), false);

  console.log(`\n${passed} ok, ${failed} failed`);
  process.exit(failed ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
