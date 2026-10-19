#!/usr/bin/env node
/**
 * Task 3 hand calculations, in metres and real seconds:
 * L lengths 30,40 at 1,.5: from 28, 2 s reaches 30, 2 s adds 1 => 31.
 * From 69, 10 s clamps to 70. Null first segment crosses 30 instantly,
 * then 2 s adds 1 => 31. Null list keeps 12. Zero-length middle costs 0:
 * from 29, 1 s reaches 30, 2 s adds 1 => 31.
 * Timeless after budget: 30 s reaches 30; null second segment still crosses
 * instantly => 60. From 30 at dt=0 also => 60; timed dt=0 keeps 10.
 * Age: (300+(500-200)/2+40)/1000=.49; net clamped at 0 gives .34.
 * Even 10 advances to 10.1. Ahead: max(0,.1-1.5*(1-exp(-.1)))=0,
 * so 11.5 stays. Cross: pred=30.05,target'=30.6, k=1-exp(-.2),
 * 29.9+.15+.55*k=30.1496980858. Freeze: 19+1*(1-exp(-.1))=
 * 19.0951626; ahead 21 stays. long_dt: target'=min(99+5,100)=100,
 * pred=min(98+5,100)=100, err=0 => clamp(98+2,0,100)=100.
 * Threshold max(6,2*rate): 1.4/null => 6, 4 => 8. At 31 rate=.5.
 * Adoption gaps 5,7,-10,7 at limits 6,6,6,8 => none,fwd,back,none.
 * After pause: shown 60,target 52 => -8; abs(-8)>6 => back to 52.
 * Deque (0,.8),(10000,.3),(29000,.2): at 29500 none expired => .8;
 * at 30500 t<=500 expires => .3. Empty => 0. Sample (999,.9) at 30000
 * is 29.001 s old (keep .9); at 31000 is 30.001 s old (expire => 0).
 *
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
 * --- trimBucket / remainingPoints: the line BEHIND the walker (E5 task 2) ---
 * The drawn journey used to be the whole polyline, start to goal, for the
 * whole trip — so a traveller halfway to the next village dragged a dashed
 * line back to the village it had left. The line is now trimmed at the
 * walker's own foot point, and to keep that from rebuilding a buffer every
 * frame the trim advances in BUCKETS of TRIM_BUCKET_M = 5 m; the bucket is
 * part of the drawn line's key in `npcs.ts`.
 *   trimBucket(0)    = floor(0/5)   = 0     (the untrimmed whole line)
 *   trimBucket(4.99) = floor(0.998) = 0
 *   trimBucket(5)    = 1
 *   trimBucket(7)    = floor(1.4)   = 1                          <- plan case
 *   trimBucket(9.99) = 1                    (still the same geometry)
 *   trimBucket(10)   = 2
 *   trimBucket(-3)   = 0   and   trimBucket(NaN) = 0   (nothing said = untrimmed)
 *
 * remainingPoints = pointAtDistance(points, d) followed by every waypoint
 * BEHIND that point. On (P) = [[0,0],[10,0],[10,20]], total 30:
 *   d = 0    -> foot (0,0) on segment 0, tail = points[1..]
 *               -> [(0,0), (10,0), (10,20)]            the whole line
 *   d = 7    -> foot (7,0) (t = 0.7 on segment 0), tail = points[1..]
 *               -> [(7,0), (10,0), (10,20)]            <- plan case, bucket 1
 *   d = 10   -> the foot IS the corner (t = 1). It must NOT appear twice, so
 *               the tail starts BEHIND it: points[2..]
 *               -> [(10,0), (10,20)]
 *   d = 15   -> segment 1, t = 5/20 = 0.25 -> foot (10,5), tail = points[2..]
 *               -> [(10,5), (10,20)]
 *   d = 30   -> foot (10,20) = the end, tail empty -> [(10,20)]
 *               ONE point: `npcs.ts` draws from two up, so an arrived
 *               traveller draws no line at all — which is right, there is
 *               nothing ahead of it any more.
 *   d = 42   -> clamped to 30, same single point
 *   d = -3   -> clamped to 0, the whole line
 * On (D) = [[0,0],[0,0],[10,0]], the collapsed pair:
 *   d = 4    -> segment 0 has L = 0 and is skipped (no 0/0 lerp), so the foot
 *               is found on segment 1 at t = 0.4 -> (4,0), tail = points[2..]
 *               -> [(4,0), (10,0)]   — the duplicate start is trimmed away
 *               with everything else behind the walker
 * On (S) = [[7,-2]] any d -> [(7,-2)]; on [] -> [].
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
  if (b && typeof b === 'object') {
    return a && typeof a === 'object'
      && Object.keys(a).length === Object.keys(b).length
      && Object.keys(b).every((key) => compare(a[key], b[key], eps));
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
  const t = await loadTravelPath();
  {
    const L = [[0,0],[30,0],[70,0]], P = [1.0, 0.5];
    check('adv cross',      t.advanceAlongPaces(L, P, 28, 4), 31.0);
    check('adv clamp',      t.advanceAlongPaces(L, P, 69, 10), 70.0);
    check('adv null seg',   t.advanceAlongPaces(L, [null, 0.5], 0, 2), 31.0);
    check('adv paces null', t.advanceAlongPaces(L, null, 12, 5), 12);
    check('adv zero-length seg', t.advanceAlongPaces([[0,0],[30,0],[30,0],[70,0]], [1, 1, 0.5], 29, 3), 31.0);
    // timeless segments are crossed even when the time budget is exactly used up (plan review 8):
    const T = [[0,0],[30,0],[60,0]];
    check('adv timeless after budget', t.advanceAlongPaces(T, [1, null], 0, 30), 60);
    check('adv timeless at dt 0',      t.advanceAlongPaces(T, [1, null], 30, 0), 60);
    check('adv dt 0 timed',            t.advanceAlongPaces(T, [1, 1], 10, 0), 10);
    check('age',       t.ageAtReceiptS({clock_age_ms: 300, build_ms: 200}, {polledAt: 0, headersAt: 500, parsedAt: 540}), 0.49);
    check('age net 0', t.ageAtReceiptS({clock_age_ms: 300, build_ms: 200}, {polledAt: 0, headersAt: 150, parsedAt: 190}), 0.34);
    const S = [[0,0],[100,0]];
    check('even',  t.stepShown(S, [1.0], 10.0, 10.0, 0.1), 10.1);
    check('ahead', t.stepShown(S, [1.0], 11.5, 10.0, 0.1), 11.5);          // gap afterwards 1.4
    check('cross', t.stepShown(L, P, 29.9, 30.5, 0.2), 30.149698, 1e-6);
    check('freeze catch-up', t.stepShown(S, null, 19, 20, 0.1), 19.0951626, 1e-6);
    check('freeze ahead',    t.stepShown(S, null, 21, 20, 0.1), 21);
    check('long_dt', t.stepShown(S, [1.0], 98, 99, 5), 100);              // Review focus 3
    check('snap 1.4', t.hardSnapM(1.4), 6); check('snap 4', t.hardSnapM(4), 8); check('snap null', t.hardSnapM(null), 6);
    check('rateAt seg2', t.rateAt(L, P, 31), 0.5);
    // adoption on a NEW payload (plan review 10): the snap decision itself
    check('adopt none', t.adoptTarget(40, 45, 1.4), { shownM: 40, snap: 'none' });   // |5| <= 6
    check('adopt fwd',  t.adoptTarget(40, 47, 1.4), { shownM: 47, snap: 'fwd' });    // 7 > 6
    check('adopt back', t.adoptTarget(50, 40, 1.4), { shownM: 40, snap: 'back' });   // |-10| > 6
    check('adopt fast', t.adoptTarget(40, 47, 4),   { shownM: 40, snap: 'none' });   // 7 <= 8
    // Review focus 3 (pause/tab switch): a stale payload 5 s behind a figure that ran on
    check('adopt after pause', t.adoptTarget(60, 52, 1.4), { shownM: 52, snap: 'back' });
    // the 30-s maximum is over the LAST 30 s, not a fixed window (plan review 10)
    const w = t.createErrWindow();
    t.pushErr(w, 0, 0.8); t.pushErr(w, 10_000, 0.3); t.pushErr(w, 29_000, 0.2);
    check('err max inside', t.maxErr(w, 29_500), 0.8);
    check('err max slid',   t.maxErr(w, 30_500), 0.3);    // the 0.8 at t=0 is older than 30 s
    check('err max empty',  t.maxErr(t.createErrWindow(), 0), 0);
    const w2 = t.createErrWindow(); t.pushErr(w2, 999, 0.9);
    check('err max keeps 29.001 s', t.maxErr(w2, 30_000), 0.9);   // plan review R2-3
    check('err max expires',        t.maxErr(w2, 31_000), 0);
    }
  const { polylineLength, pointAtDistance, clampProgress,
          catchUpStep,
          trimBucket, remainingPoints, TRIM_BUCKET_M } = t;
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

  console.log('\ntrimBucket — the five metres a redrawn travel line costs');
  check('the bucket is five metres', TRIM_BUCKET_M, 5);
  check('nothing walked yet', trimBucket(0), 0);
  check('just short of the first bucket', trimBucket(4.99), 0);
  check('exactly on it', trimBucket(5), 1);
  check('seven metres in', trimBucket(7), 1);
  check('...and still at 9.99', trimBucket(9.99), 1);
  check('ten metres is the next', trimBucket(10), 2);
  check('a negative progress trims nothing', trimBucket(-3), 0);
  check('...and neither does a NaN one', trimBucket(NaN), 0);

  console.log('\nremainingPoints — the line ahead of the walker, nothing behind');
  check('nothing walked: the whole line', remainingPoints(P, 0),
    [[0, 0], [10, 0], [10, 20]]);
  check('7 m in: the foot point, then the rest', remainingPoints(P, 7),
    [[7, 0], [10, 0], [10, 20]]);
  check('exactly on the corner: it is NOT repeated', remainingPoints(P, 10),
    [[10, 0], [10, 20]]);
  check('a quarter up the second leg', remainingPoints(P, 15), [[10, 5], [10, 20]]);
  check('arrived: one point, so `npcs.ts` draws no line', remainingPoints(P, 30),
    [[10, 20]]);
  check('past the end clamps to the same', remainingPoints(P, 42), [[10, 20]]);
  check('before the start clamps to the whole line', remainingPoints(P, -3),
    [[0, 0], [10, 0], [10, 20]]);
  check('the collapsed pair is skipped, not lerped', remainingPoints(D, 4),
    [[4, 0], [10, 0]]);
  check('a one-point journey stays one point', remainingPoints(S, 3), [[7, -2]]);
  check('no line at all', remainingPoints([], 5), []);
  check('...and none for a missing one', remainingPoints(null, 5), []);
  // The trim must not alias the payload: `npcs.ts` builds Vector3s from these
  // and the route keeps running on its own points.
  const kept = remainingPoints(P, 15);
  kept[1][0] = 999;
  check('the tail is COPIED out of the polyline', P[2][0], 10);

  console.log(`\n${passed} ok, ${failed} failed`);
  process.exit(failed ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
