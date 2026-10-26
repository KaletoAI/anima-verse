#!/usr/bin/env node
/**
 * Smoke check for the PER-RIG FOOT LOCK of the 3D client
 * (`client3d/src/scene/footLockMeasure.ts`, `relockRootPaths`): a bridge
 * clip's imported root travel is rebuilt on each model's OWN skeleton, from
 * the foot bones of a probe clone — the same rule the importer ran on the
 * reference rig (`footLock.ts`, twin of `_root_motion.py`). Numbers only
 * (§ B5a); a SYNTHETIC skeleton, no clip files, no server.
 *
 * Usage:  node client3d/scripts/smoke_foot_lock_measure.mjs
 *         (needs esbuild and three from the workspace)
 *
 * ===========================================================================
 * THE SYNTHETIC RIG (k = template units per cm: 1 for [C1]–[C4]/[C6], 0.01
 * for [C5]; every length below is × k)
 * ===========================================================================
 *   rig (Group, identity)
 *   └ mixamorigHips        local (0, 100, 0)
 *     └ Legs               local (0, 0, 0)       ← the ONE animated bone
 *       ├ mixamorigLeftUpLeg   local ( 10, 0, 0)
 *       │ └ mixamorigLeftLeg   local (0, −46, 0)
 *       │   └ mixamorigLeftFoot    local (0, −46, 0)  → world ( 10, 8, 0)
 *       │     └ mixamorigLeftToeBase local (0, −5, 12) → world ( 10, 3, 12)
 *       │       └ mixamorigLeftToe_End local (0, −3, 6) → world ( 10, 0, 18)
 *       └ the same on the right with x = −10
 * Rest heights (bind pose, over the lowest of the four points AND the two
 * toe ends, which sit at 0): LeftFoot/RightFoot 8, LeftToeBase/RightToeBase 3.
 *
 * THE CLIP (the "Legs" variant the brief allows): 11 keys, f = 0 … 10 at
 * 30 fps (times f/30, duration 1/3 s). `mixamorigHips.position` stays at its
 * rest (0, 100, 0) — the hips are in place, as `adaptExternalClips` leaves
 * them — and `Legs.position` = (0, 0, −2f): both feet slide 2 cm a frame
 * BACKWARDS, which is exactly what a planted foot does in an in-place clip
 * while the body walks forward.
 *
 * Measured per frame (cm): LeftFoot (10, 8, −2f), LeftToeBase (10, 3, 12 − 2f),
 * the right side at x = −10. Heights are constant, so every point's ground is
 * min(5th percentile = its own height, rest height) = its own height →
 * height over ground 0 → band weight 1; vertical speed 0 → speed weight 1.
 * All four points weigh 1 in every frame: FULL contact throughout.
 * footLockPath: each step the four full points move dz = −2, dx = 0, so the
 * root moves by the opposite: path = (0, 2f) cm.
 *
 * [C1] The imported path is preset WRONG on purpose: z = 1·f (template
 *      units, = cm at k = 1). After relockRootPaths:
 *        stored path z = 2f (±1e-4), x = 0, times = the hips track's f/30;
 *        report used 'rig', driftCm 0 (±1e-3) — the world foot z is
 *        −2f + 2f = 0 over the whole run;
 *        importedDriftCm 10 (±1e-3) — with the preset path the world foot z
 *        is −2f + f = −f, a run from f = 0 to 10 drifts |−10 − 0| = 10;
 *        travel = the path's end (0, 20) cm.
 *      The same clip WITHOUT a hips position track is sampled uniformly at
 *      30 fps over its duration: round(1/3 · 30) + 1 = 11 frames at f/30 —
 *      the same path (0, 2f).
 *      The log sink is called exactly once, with
 *        "foot lock per rig — bridge-a 0.0 cm (imported 10.0)".
 * [C2] The template is untouched: every bone's local position and quaternion
 *      equal (exactly) their values before any of the calls below.
 * [C3] Legs.position = (0, 30, −2f): the feet hang 30 cm over their rest
 *      heights. ground = min(own height 38 resp. 33, rest 8 resp. 3) = rest,
 *      height over ground 30 ≥ 5 → weight 0 everywhere: no frame pair reaches
 *      FULL → used 'imported', reason 'no full contact', the stored path is
 *      still the preset z = 1·f; driftCm = importedDriftCm = 0 (no planted
 *      run exists); travel (0, 10) cm.
 * [C4] The rig without mixamorigLeftToeBase (and its toe end): one contact
 *      point is missing → used 'imported', reason 'no foot bones', the preset
 *      path stays, driftCm/importedDriftCm/travel finite (0, 0, (0, 10)).
 * [C5] The whole rig and clip scaled into METRES (k = 0.01), unitsPerCm
 *      0.01: the measured tracks in cm are those of [C1] (units / 0.01), so
 *      the path is (0, 2f) cm again and is stored back in template units:
 *      z = 0.02f (±1e-6 units = ±1e-4 cm); driftCm 0, importedDriftCm 10 for
 *      the preset z = 0.01f (= f cm).
 * [C6] A clip with no root path in the same call is not touched: one report
 *      only (for the [C1] clip), and it still has no path afterwards. A call
 *      with ONLY that clip returns [] and never calls the log sink.
 * [C7] NEVER WORSE THAN THE IMPORT (fix round 1): the preset path is already
 *      right, z = 2f. The rebuilt path is z = 2f too, so both drifts are 0
 *      (the imported one up to the Float32 rounding of its keys, ~6e-7) —
 *      the rebuild is not lower by more than RELOCK_MIN_GAIN_CM (0.1 cm),
 *      so the imported path is kept: used 'imported',
 *      reason 'imported holds better', the stored path is still the preset
 *      object, and the log line reads
 *        "foot lock per rig — bridge-g imported 0.0 cm (rig 0.0)".
 * [C8] NO LIFT TOLERANCE: the ground rule is the importer's
 *      (`_root_motion.ground_heights` with its default 0) — a point's ground
 *      is never above its bind-pose rest height. Since the rig's rest hips
 *      height is the standing reference of `adaptExternalClips`, an adapted
 *      clip no longer stands lifted over the rest, and the 3 cm tolerance
 *      that covered that lift is gone: `footLockMeasure` exports no
 *      GROUND_LIFT_TOL_CM any more.
 *      The rule on its own (`groundHeights`, a check of the RULE, not a
 *      regression proof — the relockRootPaths part below is the one that
 *      fails with the old tolerance): the four points held 2 cm over their
 *      rests for 11 frames — feet at 10, toes at 5 over rests 8 / 3 — have
 *      ground = min(own height, rest) = rest: 8 / 3, not 10 / 5.
 *      Through relockRootPaths (the discriminating proof): Legs.position = (0, 2.5, −2f) — the whole leg
 *      lifted 2.5 cm. Feet at 10.5 / toes at 5.5 over rests 8 / 3: ground =
 *      rest, height 2.5 → band ramp (5 − 2.5)/3 = 0.833 < FULL in every frame
 *      → used 'imported', reason 'no full contact', the stored path is still
 *      the preset object, driftCm = importedDriftCm = 0, travel (0, 10) cm
 *      (the preset z = f ends at 10).
 *      With the old tolerance (3 cm, 5cfc6c1f): ground = min(10.5, 8 + 3) =
 *      10.5 → height 0 → weight 1 → used 'rig', path z = 2f.
 */
import { runBridgeVectors } from './bridgeVectorDispatch.mjs';
const result = await runBridgeVectors('foot_lock_measure');
console.log(`\n${result.passed} ok, ${result.failed} failed`);
process.exitCode = result.failed ? 1 : 0;
