#!/usr/bin/env node
/**
 * Smoke check for the FOOT-LOCK maths of the 3D client
 * (`client3d/src/scene/footLock.ts`) — the TypeScript twin of the importer's
 * `app/blender/scripts/_root_motion.py`. Pure numbers (§ B5a), no three, no
 * clips, no server.
 *
 * Usage:  node client3d/scripts/smoke_foot_lock_math.mjs
 *         (needs esbuild; reads scripts/fixtures/root_motion_cases.json)
 *
 * Hand-derived expectations
 * -------------------------
 * The expectations are NOT derived here a second time: they live in the
 * shared fixture `scripts/fixtures/root_motion_cases.json`, which holds the
 * cases [2], [4], [5], [6], [10] and [11] of `scripts/smoke_root_motion_math.py`
 * with the paths and drifts derived by hand in that smoke's docstring (each
 * case names its origin in `"from"`). The Python smoke checks the same file in
 * its section [F], so one file is the contract both copies answer to.
 *
 *   [C] constants: BAND_LO_CM 2, BAND_HI_CM 5, VY_LO_CM_S 15, VY_HI_CM_S 30,
 *       GROUND_PCT 0.05, MIN_WEIGHT 1e-3, FULL 0.999 and CONTACT_POINTS
 *       (LeftFoot, LeftToeBase, RightFoot, RightToeBase) equal the fixture's.
 *
 *   [F] every fixture case through groundHeights → contactWeights →
 *       footLockPath: the path within 1e-6 of the fixture's, and
 *       maxPlantedDrift with the case's own path (`drift_path`) and with an
 *       all-zero path (`drift_zero_path`, the strip file) where given.
 *       Example, case [2]: one foot at its rest height 8 sliding back 2 cm a
 *       frame → path z = 2f, drift 0 with that path, 20 with a zero path.
 *
 *   [D] degenerate inputs, from the Python smoke's [1]/[7]:
 *       ramp(NaN, 2, 5) = 0; ramp(3.5, 2, 5) = (5 − 3.5)/3 = 0.5;
 *       footLockPath({}, {}) = [] (empty tracks → empty path).
 *
 * [F] The wrapper guard compares the constants, inputs and hand expectations
 * against the legacy file verbatim; it never derives an oracle from output.
 * Canonical derivations copied from the Python twin for foot_lock.json:
 * Frame of every case: clip frame, Y up, +Z forward, +X the figure's left, cm,
 * 30 fps. The tracks are what the importer sees AFTER stripping the travel
 * (``strip``): the hips stay at the origin, so a foot that is planted in the
 * world slides BACKWARDS in these numbers by exactly the travel.
 *
 * [1] ramp(v, lo=2, hi=5): 1 at or below lo, 0 at or above hi, linear between.
 *       ramp(1)=1, ramp(2)=1, ramp(3.5)=0.5, ramp(5)=0, ramp(6)=0, ramp(nan)=0.
 * [2] One planted point, sliding back 2 cm per frame (the chair case):
 *       LeftFoot y=8 (its rest height), x=0, z=-2f for f=0..10; rest 8.
 *       ground = min(p5(8…)=8, rest 8) = 8 → height weight 1; vy = 0 → weight 1.
 *       Δ(f→f+1) = −(−2) = +2 → path z = 2f, travel (0, 20).
 *       World track z + path = 0 for every frame → drift 0.
 *       With a zero path (the strip file) the drift is |−20 − 0| = 20.
 * [3] Point in the air the whole take: y=30, rest 8 → ground = min(30, 8) = 8,
 *       y − ground = 22 ≥ 5 → weight 0 → path all zero, travel (0, 0).
 *       (Without the rest guard the 5th percentile would call 30 cm "ground".)
 * [4] Air, then planted: f=0..4 y=30, f=5..10 y=8, z=-2f throughout, rest 8.
 *       Height weight: f≤4 → 0, f≥5 → 1.
 *       vy (central difference, one-sided at the ends, ×30 fps):
 *         f=4: (8−30)/2·30 = −330 → 0;  f=5: (8−30)/2·30 = −330 → 0;
 *         f=6: (8−8)/2·30 = 0 → 1.
 *       Pair weight min(w[f], w[f+1]): only f≥6 is 1.
 *       path z: f=0..6 → 0, f=7 → 2, f=8 → 4, f=9 → 6, f=10 → 8; travel (0, 8).
 *       contact_spans at full weight (w ≥ 0.999): [[6/30, 10/30]] = [[0.2, 0.333]].
 * [5] Two points: A planted (y=8, z=-2f), B in the air (y=30, z=+5f), rest 8.
 *       Only A carries weight → Δ = +2 per frame, path z = 2f (B is ignored).
 * [6] Two planted points that disagree: A z=-2f, B z=-4f, both y=8, rest 8.
 *       Δ = −(1·(−2) + 1·(−4)) / 2 = +3 per frame → path z = 3f, travel (0, 30).
 * [7] Degenerate: one frame → path [(0,0)], travel (0,0); a NaN position gets
 *       weight 0; a point name missing from the tracks is simply absent.
 * [8] rotate_travel((0, 40), yaw 90, 0, 0) → (40, 0)
 *       (x' = x cos a + z sin a, z' = −x sin a + z cos a — cmu_clip/clip_orient's
 *       yaw); (10, 0) at yaw 90 → (0, −10); (0, 40) at yaw 180 → (0, −40);
 *       (0, 40) at tilt 90: Rx(90) turns (0, 0, 40) into (0, −40, 0), so the
 *       horizontal part is (0, 0) within 1e-9.
 * [9] ONE vocabulary: the Blender side keeps its own copy of the modes
 *       (bpy scripts do not import the app package), so ``_root_motion.MODES``
 *       must equal ``animation_clips.ROOT_MOTION_MODES`` — the tuple the routes
 *       validate against — element for element, order included:
 *       ("strip", "keep", "foot_lock").
 *       (Importing animation_clips reads no storage: it only resolves clip
 *       directories when a function is called.)
 * [10] DOMINANT CONTACT — a fully planted point outranks a half-planted one.
 *       A planted: y=8 (rest 8), z=-2f → weight 1.
 *       B hovers: y=11.5, rest 8 → ground = min(11.5, 8) = 8, height 3.5 →
 *       ramp(3.5, 2, 5) = 0.5; vy = 0 → weight 0.5; it slides z=-6f.
 *       Old rule (plain weighted mean): Δ = −(1·(−2) + 0.5·(−6)) / 1.5 = +10/3
 *       per frame — the half-planted B drags the planted A by 4/3 cm a frame,
 *       13.33 cm over the take, although A is the only VERIFIED contact.
 *       New rule: while any point is in full contact (pair weight ≥ FULL), only
 *       full-contact points steer → Δ = +2, path z = 2f, travel (0, 20), drift
 *       of A = 0. (Real case: get-up-bed, a shuffling left foot at 2 cm height,
 *       weight 0.83–0.97, dragged the planted right foot by 2.02 cm.)
 * [11] NO full contact anywhere → the partial weights still steer, as before.
 *       A: y=11.5 (rest 8) → height 3.5 → weight 0.5, z=-2f;
 *       B: y=12.25 (rest 8) → height 4.25 → ramp = (5−4.25)/3 = 0.25, z=-5f.
 *       Δ = −(0.5·(−2) + 0.25·(−5)) / 0.75 = 2.25/0.75 = +3 → path z = 3f,
 *       travel (0, 30).
 *       [6] stays as derived: both points there are FULL, so the mean of the
 *       full points is the old mean (path z = 3f).
 * [F] SHARED FIXTURE — ``scripts/fixtures/root_motion_cases.json`` is the
 *       parity contract with the TypeScript twin (``client3d/src/scene/footLock.ts``,
 *       checked by ``client3d/scripts/smoke_foot_lock_math.mjs``). It holds the
 *       cases [2], [4], [5], [6], [10] and [11] above — the same inputs, the
 *       paths and drifts derived here by hand (each case names its origin in
 *       ``"from"``) — plus the constants. This section checks the constants
 *       equal ``_root_motion.*`` and runs every case through ground → weights →
 *       path, path and drift within 1e-6. Case [10]'s drift runs over BOTH
 *       points: B weighs 0.5 in every frame, never FULL, so it adds no run and
 *       the drift is A's 0.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { loadVectors, resolveArgs } from '../../shared/test-vectors/vectors.mjs';
import { runBridgeVectors } from './bridgeVectorDispatch.mjs';
// Preserve the original Python/TS fixture contract while exposing ordinary JSON
// arguments to the native client. This checks hand data, never production output.
const legacy = JSON.parse(readFileSync(new URL('../../scripts/fixtures/root_motion_cases.json', import.meta.url), 'utf8'));
const vectors = loadVectors('foot_lock');
const wrapped = [];
for (const c of vectors.cases) {
  const args = resolveArgs(c.args, vectors.fixtures);
  if (c.fn === 'constant') assert.deepEqual(c.expect, legacy.constants[args[0]]);
  if (c.fn === 'footLockValue') wrapped.push({input:args[0], field:args[1], expect:c.expect});
}
assert.deepEqual(wrapped, legacy.cases.flatMap((c) => Object.entries(c.expect).map(([field, expect]) =>
  ({input:{tracks:c.tracks,rest:c.rest,fps:c.fps},field,expect}))));
console.log('  ok   legacy root_motion_cases wrapper agrees');
const result = await runBridgeVectors('foot_lock');
result.passed += 1;
console.log(`\n${result.passed} ok, ${result.failed} failed`);
process.exitCode = result.failed ? 1 : 0;
