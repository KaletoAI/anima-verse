#!/usr/bin/env node
/**
 * Canonical derivations for travel.json (metres, real seconds, monotonic ms).
 * [1] advanceAlongPaces; [2] ageAtReceiptS; [3] stepShown; [4] rates/thresholds;
 * [5] adoptTarget; [6] errWindowMax. Their hand calculations follow.
 * [7] lengths; [8] points; [9] clamps; [10] catch-up; [11] buckets;
 * [12] remaining points are derived in the named sections below.
 * [13] deadReckonRate and [14] deadReckonStep: merged reckon header below.
 * [15] densifyPolyline: merged relief [6] header below (full points, not
 * only lengths/projections). Missing input yields []; a duplicate-only line
 * has total zero and keeps both copies of (2,3). Thirds are 10/3 and 20/3 on each 10 m leg;
 * the capped 100 m route has endpoints and every multiple of 10 m.
 * [9] Additional clamps: -Infinity is before zero; undefined and a string
 * are non-numbers, so all three become zero.
 *
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
 *
 * --- Merged source: smoke_travel_reckon.mjs ([13], [14]) -------------------

 * Smoke check for the DEAD RECKONING of a fogged traveller (plan-npc-leben-bugs,
 * task 3) — `deadReckonRate` and `deadReckonStep` in
 * `client3d/src/scene/travelPath.ts`.
 *
 * Usage:  node client3d/scripts/smoke_travel_reckon.mjs
 *
 * Same discipline as `client3d/scripts/smoke_travel_math.mjs` and
 * `smoke_walk_math.mjs`: every expected number below is derived BY HAND from
 * the rule, written out in this header, and NEVER recorded from the current
 * output. A check that only pins today's result proves nothing.
 *
 * `travelPath.ts` has NO import at all — not even a type-only one — so a plain
 * esbuild transpile loads it here without a bundler, a DOM or three.
 *
 * ===========================================================================
 * WHY THE CLIENT MEASURES INSTEAD OF ASKING
 * ===========================================================================
 * Under fog the worldmap deliberately thins a FOREIGN traveller's row down to
 * its `pos` (decision `77dbdb61`): `waypoints`, `progress_m`, `total_m`,
 * `speed_m_s_real` and `pace_m_s_real` are all null, because neither the goal
 * nor the speed of someone else's journey is the avatar's to know. That
 * decision stands, so the client may not ask for the missing numbers — it can
 * only DERIVE the one it needs from what it already sees.
 *
 * What it sees is a fresh `pos` every worldmap poll (`WORLDMAP_POLL_MS` =
 * 3000 ms, `main.ts`). Two consecutive polled points and the real time between
 * them are a speed:
 *
 *     rate [m/s] = |cur - prev| / (t_cur - t_prev)
 *
 * and the figure walks at that rate — scaled by the pace of the ground it
 * stands on (`walk.terrainPace`, the same helper the avatar uses) and capped
 * by what is still left to the polled point, so it can never overshoot the
 * only position the server actually vouched for.
 *
 * WHAT THIS REPLACES, and why the old numbers were wrong:
 *   the generic catch-up branch of `npcs.ts` walked such a figure at
 *   `WALK_SPEED (3.4) * dt * pace (1) * (dist > RUN_DISTANCE (6) ? 1.8 : 1)`
 *   — up to 6.12 m/s. A wanderer's real pace is `game.travel_speed_m_s`
 *   (default 1.4 m/s) times the terrain factor, so at ~2 m/s a 3.0 s poll gap
 *   is 6.0 m — EXACTLY the run threshold. The figure therefore sprinted the
 *   whole gap in about one second and stood for two: sprint, pause, sprint.
 *
 * ===========================================================================
 * deadReckonRate(prev, prevAtS, cur, atS) -> m/s | null
 * ===========================================================================
 * `prevAtS`/`atS` are REAL seconds (the caller hands in `performance.now()`
 * over 1000, taken when the payload stamp changed — `npcs.update()` runs at
 * 1 Hz off the CACHED map, so the same poll is seen three times and only the
 * stamp says which sighting is a new one).
 *
 * (A) THE PLAN'S CASE — polls 3.0 s apart, the figure 6.0 m further on:
 *       prev = (0,0) at t = 0, cur = (6,0) at t = 3
 *       gap  = sqrt(6^2 + 0^2) = 6
 *       rate = 6 / 3 = 2 m/s
 * (B) A DIAGONAL, so nothing passes by only ever moving on an axis:
 *       prev = (10,10) at t = 12.0, cur = (13,14) at t = 14.5
 *       gap  = sqrt(3^2 + 4^2) = 5      (the 3-4-5 triangle)
 *       rate = 5 / 2.5 = 2 m/s
 * (C) A SLOW ground — the same 3.0 s, but only 4.2 m of it:
 *       rate = 4.2 / 3 = 1.4 m/s        (the demo's `travel_speed_m_s`)
 * (D) NO HISTORY (the first sighting of a traveller): prev is null
 *       -> null, and null is what the caller falls back on.
 * (E) A DUPLICATE POLL — the same instant twice, which is what a repeated
 *     payload would look like if the stamp guard ever failed:
 *       t_cur - t_prev = 0  -> null, NEVER 6/0 = Infinity. The caller keeps
 *       the rate it already had, so the figure walks on at the last measure.
 *     Time running BACKWARDS (a clock reset) is the same answer.
 * (F) A FIGURE THAT DID NOT MOVE between two polls:
 *       gap 0 over 3.0 s -> rate 0, a HONEST measure and not null: the figure
 *       stands until the next poll says otherwise.
 * (G) NONSENSE IN, null OUT: a NaN coordinate or a NaN stamp gives null
 *     rather than a NaN rate — one NaN in the step and the figure is gone
 *     from the picture without a word.
 *
 * ===========================================================================
 * deadReckonStep(rate, pace, dt, remainingM) -> metres
 * ===========================================================================
 *     step = min(remainingM, rate * pace * dt)
 *
 * THERE IS NO RUN FACTOR IN IT — that is the whole point. The old branch
 * multiplied by 1.8 as soon as the goal was further than 6 m away, and 6 m is
 * exactly one poll gap.
 *
 * (H) THE PLAN'S FRAME — rate 2.0 m/s, terrain pace 0.7, dt = 1/60 s, with
 *     more than a step still to go:
 *       2.0 * 0.7 = 1.4 m/s
 *       1.4 / 60  = 0.023333333333333334 m
 * (I) THE SAME FRAME ON PLAIN GROUND (pace 1): 2.0 / 60 = 0.03333333333333333
 * (J) NO BOOST: the goal 100 m away — sixteen times `RUN_DISTANCE` — over a
 *     full second still walks `2.0 * 1 * 1 = 2.0` m and not `3.4 * 1.8 = 6.12`.
 * (K) THE CAP IS THE REMAINING DISTANCE: rate 2.0, pace 1, dt 1 s, 0.5 m left
 *       -> 0.5, never past the point the server vouched for.
 * (L) NOTHING LEFT (0 m, a negative rest, a NaN rest) -> 0.
 * (M) A PACE THAT IS NOT A PACE (0, negative, NaN, missing) counts as 1 — the
 *     ground rule already clamps a real pace at `walk.MIN_PACE` = 0.25, so
 *     anything outside is a broken lookup and must not stop the figure dead.
 * (N) NO RATE (null — the first sighting), a zero or negative rate, dt 0:
 *       -> 0. The caller's fallback for "no rate yet" is the plain walk
 *       WITHOUT the boost, and that lives in `npcs.ts`, not here.
 *
 * ===========================================================================
 * (O) THREE SECONDS OF FRAMES — the regression, stated as a walk
 * ===========================================================================
 * The measured rate of case (A) is 2.0 m/s and the polled point is 6.0 m
 * ahead. Walking 60 fps frames at pace 1:
 *   - after 60 frames (1.0 s) the figure has covered 60 * (2/60) = 2.0 m and
 *     is NOT standing at the goal — the old 6.12 m/s would have been there
 *     after 0.98 s;
 *   - after 180 frames (3.0 s) it has covered exactly 6.0 m: it arrives as the
 *     next poll lands, which is what "no pause" means.
 * Floating point adds up over 180 additions, so the sum is compared at 1e-9.

 *
 * --- Merged source: smoke_relief_math.mjs [6] ([15]) ----------------------
 * [6] `densifyPolyline` — a drawn line that follows the ground
 * ============================================================================
 * (a) The journey above with spacing 4: the single 8 m segment is cut into
 *     ceil(8/4) = 2 pieces -> 3 points (-4, 0), (0, 0), (4, 0), and their
 *     heights are 0, 5, 0 — the line goes OVER the peak instead of through it.
 * (b) Spacing 2 -> 4 pieces -> 5 points at x = -4, -2, 0, 2, 4.
 * (c) CORNERS SURVIVE. (0,0) -> (10,0) -> (10,10) at spacing 4: each 10 m leg
 *     becomes ceil(10/4) = 3 pieces, so the inserted points sit at 10/3 and
 *     20/3 along it and both original corners are still in the list:
 *     1 + 3 + 3 = 7 points, the 4th of them the corner (10, 0).
 * (d) THE CAP DECIDES FIRST. (0,0) -> (100,0) with spacing 1 but at most 11
 *     points: the spacing is stretched to 100/(11-1) = 10, giving 11 points
 *     ten metres apart.
 * (e) A line of fewer than two points, and a spacing of 0, are handed back
 *     unchanged.

 */
import { readFile } from 'node:fs/promises';
import { loadVectors, runVectors } from '../../shared/test-vectors/vectors.mjs';
import { travelDispatch } from './travelVectorDispatch.mjs';

// Canonical consumer executes every shared travel case, including reckon/densify.
const { passed, failed } = runVectors(loadVectors('travel'), travelDispatch);
// Source/identity guards are intentionally not portable vector expectations.
const source = await readFile(new URL('../src/scene/travelPath.ts', import.meta.url), 'utf8');
const points = [[0, 0], [10, 0], [10, 20]];
const tail = travelDispatch.remainingPoints(points, 15);
tail[1][0] = 999;
const guards = [
  ['module has no imports', !/^\s*import\b/m.test(source)],
  ['the tail is COPIED out of the polyline', points[2][0] === 10],
  ['the bucket is five metres', travelDispatch.TRIM_BUCKET_M === 5],
];
for (const [label, ok] of guards) console.log(`  ${ok ? 'ok  ' : 'FAIL'} ${label}`);
const bad = guards.filter(([, ok]) => !ok).length;
console.log(`\n${passed + guards.length - bad} ok, ${failed + bad} failed`);
process.exit(failed + bad ? 1 : 0);
