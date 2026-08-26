#!/usr/bin/env node
/**
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
 */
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

// '../..' = the REPO root (this file lives in client3d/scripts/).
const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');
const SRC = join(ROOT, 'client3d/src/scene/travelPath.ts');

async function loadTravelPath() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'travelreckon-'));
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
  return a === b;
}

/** The old, wrong numbers of the generic catch-up branch — literals, so this
 *  check keeps stating the regression even if `npcs.ts` renames them. */
const WALK_SPEED = 3.4;
const RUN_FACTOR = 1.8;
const RUN_DISTANCE = 6;
/** `WORLDMAP_POLL_MS / 1000` (main.ts) — the window a rate is measured over. */
const POLL_S = 3;

async function main() {
  const { deadReckonRate, deadReckonStep } = await loadTravelPath();

  console.log('deadReckonRate — metres per real second between two polled points');
  check('(A) 6 m in one 3 s poll gap is 2 m/s',
    deadReckonRate([0, 0], 0, [6, 0], POLL_S), 2);
  check('(B) the 3-4-5 diagonal over 2.5 s',
    deadReckonRate([10, 10], 12, [13, 14], 14.5), 2);
  check('(C) the demo pace: 4.2 m in 3 s',
    deadReckonRate([0, 0], 0, [0, 4.2], POLL_S), 1.4);
  check('(D) no history at all — the first sighting',
    deadReckonRate(null, 0, [6, 0], POLL_S), null);
  check('(D) …and an undefined previous point is the same',
    deadReckonRate(undefined, 0, [6, 0], POLL_S), null);
  check('(D) no current point either', deadReckonRate([0, 0], 0, null, POLL_S), null);
  check('(E) a duplicate poll: no divide by zero',
    deadReckonRate([0, 0], 3, [6, 0], 3), null);
  check('(E) time running backwards is refused too',
    deadReckonRate([0, 0], 3, [6, 0], 2.5), null);
  check('(F) the figure stood still: an honest 0, not null',
    deadReckonRate([7, -2], 0, [7, -2], POLL_S), 0);
  check('(G) a NaN coordinate gives null, never a NaN rate',
    deadReckonRate([NaN, 0], 0, [6, 0], POLL_S), null);
  check('(G) …and so does a NaN stamp',
    deadReckonRate([0, 0], NaN, [6, 0], POLL_S), null);
  check('(G) …and an infinite one',
    deadReckonRate([0, 0], 0, [6, 0], Infinity), null);

  console.log('\ndeadReckonStep — one frame of that walk, in metres');
  check('(H) rate 2.0, terrain pace 0.7, dt 1/60',
    deadReckonStep(2, 0.7, 1 / 60, 100), 0.023333333333333334);
  check('(I) the same frame on plain ground',
    deadReckonStep(2, 1, 1 / 60, 100), 0.03333333333333333);
  check('(J) NO run boost, however far the goal is',
    deadReckonStep(2, 1, 1, 100), 2);
  check('(J) …and the old branch would have run this far',
    WALK_SPEED * RUN_FACTOR * 1, 6.12);
  check('(J) …exactly one poll gap is the threshold it used',
    2 * POLL_S, RUN_DISTANCE);
  check('(K) the cap is what is left to the polled point',
    deadReckonStep(2, 1, 1, 0.5), 0.5);
  check('(K) …and it holds under a slow pace as well',
    deadReckonStep(2, 0.7, 1, 0.5), 0.5);
  check('(L) nothing left to walk', deadReckonStep(2, 1, 1 / 60, 0), 0);
  check('(L) a negative rest', deadReckonStep(2, 1, 1 / 60, -3), 0);
  check('(L) a NaN rest', deadReckonStep(2, 1, 1 / 60, NaN), 0);
  check('(M) a pace of 0 is a broken lookup, not a stop',
    deadReckonStep(2, 0, 1, 100), 2);
  check('(M) …a negative one too', deadReckonStep(2, -0.5, 1, 100), 2);
  check('(M) …a NaN one too', deadReckonStep(2, NaN, 1, 100), 2);
  check('(M) …and a missing one', deadReckonStep(2, undefined, 1, 100), 2);
  check('(N) no rate yet: the caller falls back, this walks nothing',
    deadReckonStep(null, 1, 1, 100), 0);
  check('(N) a measured standstill walks nothing',
    deadReckonStep(0, 1, 1, 100), 0);
  check('(N) a negative rate is not a walk backwards',
    deadReckonStep(-2, 1, 1, 100), 0);
  check('(N) no time passed, no step', deadReckonStep(2, 1, 0, 100), 0);
  check('(N) a NaN rate', deadReckonStep(NaN, 1, 1, 100), 0);

  console.log('\n(O) three seconds of 60 fps frames after ONE measured poll gap');
  const rate = deadReckonRate([0, 0], 0, [6, 0], POLL_S);
  check('the measured rate', rate, 2);
  let walked = 0;
  let rest = 6;
  const dt = 1 / 60;
  for (let f = 0; f < 60; f += 1) {
    const s = deadReckonStep(rate, 1, dt, rest);
    walked += s;
    rest -= s;
  }
  check('after 1.0 s: 2 m walked, not the whole gap', walked, 2);
  check('…and 4 m of it still ahead', rest, 4);
  for (let f = 0; f < 120; f += 1) {
    const s = deadReckonStep(rate, 1, dt, rest);
    walked += s;
    rest -= s;
  }
  check('after 3.0 s: exactly the polled gap, arriving as the next poll lands',
    walked, 6);
  check('…and nothing left over', rest, 0);

  console.log(`\n${passed} ok, ${failed} failed`);
  process.exit(failed ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
