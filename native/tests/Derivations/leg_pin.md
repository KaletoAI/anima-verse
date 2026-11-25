# leg_pin

- Origin: `client3d/scripts/smoke_leg_pin.mjs` @ 011cd048aa3cc2937186d7f35d2203af9491db8a
- Executed by: `native/tests/BridgeVectorTests.cs`
- Vectors: `shared/test-vectors/leg_pin.json`

## Derivation

```text
/**
 * Smoke check for the PER-RIG LEG PIN of the 3D client
 * (`client3d/src/scene/legPin.ts` with `twoBoneIk` of `@anima/scene-render`,
 * used by `footLockMeasure.relockRootPaths`):
 * a bridge clip's planted feet are nailed to their spot on each model's OWN
 * skeleton by a two-bone leg IK, baked into the adapted clip — the client's
 * counterpart of the importer's foot plant (`app/blender/scripts/_foot_plant.py`,
 * `cmu_clip._plant_feet` / `_pin_feet`). Numbers only (§ B5a); a SYNTHETIC
 * skeleton, no clip files, no server.
 *
 * Usage:  node client3d/scripts/smoke_leg_pin.mjs
 *         (needs esbuild and three from the workspace)
 *
 * ===========================================================================
 * THE PURE MATHS — the importer's parity cases (scripts/smoke_foot_plant_math.py)
 * ===========================================================================
 * [P2] twoBoneIk, a REACHABLE pull-down, verbatim: hip H (0,100,0), knee
 *      K (0,50,15), ankle A (0,0,0), target T (0,−2,0), pole = K.
 *      l1 = |H−K| = √(50² + 15²) = √2725 = 52.2015 = l2 = |K−A|;
 *      d = |H−T| = 102 < l1 + l2 = 104.4031. Equal segments → the new knee
 *      sits above the midpoint of H–T: y = 100 − d/2 = 49, off the line by
 *      √(l1² − (d/2)²) = √(2725 − 2601) = √124 = 11.1355, on the pole's side
 *      (+z) → knee (0, 49, 11.1355). Applying upper to K−H about H and
 *      lower·upper to A−K about the new knee: the ankle reaches (0,−2,0),
 *      the knee stays in the plane x = 0, both lengths stay 52.2015 (±1e-6).
 * [P3] out of reach: K (0,50,5), target (0,−5,0): hip→target 105 >
 *      2·√2525 = 100.4988 → stretched along hip→target: ankle at
 *      (0, 100 − 100.4988, 0) = (0, −0.4988, 0), knee at (0, 49.7506, 0)
 *      (±1e-6) — and every number finite (no NaN).
 * [P1] pinRuns, the run rule and fade, 30 fps (F = round(0.1·30) = 3):
 *      weights [1]*9 + [0]*14: the run [0, 8] = 9 frames = 0.3 s ≥ 0.2 s,
 *      it starts at the take's first frame → no fade-in, fade-out
 *      min(1, (8 − f + 1)/4) → [1, 1, 1, 1, 1, 1, 0.75, 0.5, 0.25] + [0]*14.
 *      [P1b] a run inside the take fades on both sides: [0]*4 + [1]*7 +
 *      [0]*4, run [4, 10] = 0.233 s → (f − 3)/4 rising, (11 − f)/4 falling →
 *      [0, 0, 0, 0, 0.25, 0.5, 0.75, 1, 0.75, 0.5, 0.25, 0, 0, 0, 0].
 *      [P1c] too short: [0]*3 + [1]*5 + [0]*3 (5 frames = 0.167 s < 0.2) →
 *      all 0. [P1d] the ramps do not count as full: [0.9]*20 → all 0.
 *      [P1e] a run touching the LAST frame keeps its end: [0]*4 + [1]*8 →
 *      [0]*4 + [0.25, 0.5, 0.75] + [1]*5.
 * [P8] soleDown, the twin of `_foot_plant.sole_down`, verbatim: a foot pins
 *      only while its ankle stands above its ball by at least
 *      SOLE_MIN_FRACTION = 0.5 of the rest rise. Rest rise 4 → threshold 2:
 *        upright            ankle 5.0, ball 0.0 → rise  5.0 ≥ 2 → true
 *        lying on its side  ankle 1.0, ball 0.6 → rise  0.4 < 2 → false
 *        kneeling, instep   ankle 4.5, ball 3.0 → rise  1.5 < 2 → false
 *        on the back, heel  ankle 4.0, ball 12  → rise −8.0 < 2 → false
 *      A rest rise ≤ 0 (−1) gives threshold 0: upright true, heel-down false.
 *
 * ===========================================================================
 * THE SYNTHETIC SKELETON (template units = cm, unitsPerCm 1)
 * ===========================================================================
 *   rig (Group, identity)
 *   └ mixamorigHips            local (0, 108, 0)   (held there: the hips are fixed)
 *     ├ mixamorigLeftUpLeg     local (10, 0, 0)     → world (10, 108, 0)   hip
 *     │ └ mixamorigLeftLeg     local (0, −50, 15)   → world (10, 58, 15)   knee
 *     │   └ mixamorigLeftFoot  local (0, −50, −15)  → world (10, 8, 0)     ankle
 *     │     └ mixamorigLeftToeBase local (0, −5, 12) → world (10, 3, 12)
 *     │       └ mixamorigLeftToe_End local (0, −3, 6) → world (10, 0, 18)
 *     └ the same on the right with x = −10 (never animated)
 * Both segments are √2725 = 52.2015 long, the hip→ankle line 100 < 104.40:
 * a bent knee, so the IK has its own bending plane (x = ±10).
 * Rest heights over the toe ends: ankle 8, ball 3.
 *
 * THE CLIP, 30 keys f = 0 … 29 at 30 fps: the hips POSITION track holds
 * (0, 108, 0) (it gives the sample times); `mixamorigLeftUpLeg.quaternion`
 * turns the whole left leg about X by θ_f and `mixamorigLeftFoot.quaternion`
 * turns the foot back by −θ_f, so the left foot stays LEVEL (world rotation
 * identity, its ball always (0, −5, 12) off the ankle). Turning (0, −100, 0)
 * about X by θ gives (0, −100 cos θ, −100 sin θ), so with
 *   f = 0 … 14:  sin θ_f = (2f − 10)/100  → ankle z = 10 − 2f: the foot
 *                SLIDES 2 cm a frame backwards while standing (its height
 *                108 − 100 cos θ_f stays within 8 … 9.63 cm);
 *   f = 15 … 29: θ = −60° → ankle (10, 58, 86.6): the foot is up.
 * The right ankle stands still at (−10, 8, 0) the whole clip, while
 * `mixamorigRightFoot.quaternion` turns the right foot about Y (its yaw) by
 * φ_f = −5° + 10°·f/29: a planted foot that pivots, as the actors' feet do
 * while they rise.
 * The imported root path is preset to ZERO.
 *
 * CONTACTS (`footLock.contactWeights`, the client's rule): left ankle ground
 * = min(5th percentile = 2nd lowest of 30 = 8.02 (f = 4, 6), rest 8) = 8;
 * heights ≤ 9.63 → over ground < 2 → band 1; vertical speed on 0 … 13 ≤
 * (9.633 − 8.985)·15 = 9.7 cm/s < 15 → 1; frame 14's central difference
 * reaches the lifted frame 15 → 0; frames 15 … 29 are 48 cm up → 0. The left
 * ball stands 5 cm under its ankle (ground min(3.02, rest 3) = 3, the same
 * heights over it) → the same weights. Right ankle and ball: constant heights
 * 8 and 3 (a yaw does not lift) → 1 everywhere.
 * DOWN (pinRuns of the sampled contacts): left run [0, 13] (14 frames =
 * 0.47 s) from the take's first frame → no fade-in, fade-out F = 3:
 * (13 − f + 1)/4 → [1]*11 + [0.75, 0.5, 0.25] + [0]*16. The LIFT = the least
 * of ankle − 8 and ball − 3 = the ankle's own height over 8 (equal), so the
 * lowered left heights are 8 + (1 − down_f)·(h_f − 8): 8 on f 0 … 10, then
 * 8.1807, 8.4924, 8.9662 on f 11 … 13 (h = 8.7226, 8.9848, 9.2883), f 14
 * unlowered 9.6333. Right: lift 0.
 * HOLD (pinRuns of the contacts of the LOWERED foot): frame 13's vertical
 * speed is now (9.6333 − 8.4924)·15 = 17.114 cm/s → weight (30 − 17.114)/15
 * = 0.8591 (frame 12: (8.9662 − 8.1807)·15 = 11.78 → 1) → the same run,
 * its fade-out × that weight:
 *   left hold  = [1]*11 + [0.75, 0.5, 0.25 · 0.8591 = 0.2148] + [0]*16,
 *   right hold = [1]*30 (a run over the whole take: no fade at all).
 * THE HELD POINT per run: ankle + s·(ball − ankle), s = the ball's share of
 * the two points' contact weights over the run's full frames = 1/(1 + 1) =
 * 0.5 on both feet — the middle of a flat foot.
 *
 * [L1] After relockRootPaths, with u_f = the left ankle's WORLD XZ before the
 *      pin (the probe's in-place position + the stored path, whatever path
 *      the re-lock chose) and A = mean of u_f over the full-hold frames (the
 *      left foot is level, its held middle point sits a constant (0, 6) off
 *      the ankle, so holding it holds the ankle):
 *        left ankle world XZ on f = 0 … 10 equals A (≤ 1 mm) — the foot is
 *        nailed; on the fade frames 11 … 13 it is A + (1 − w_f)(u_f − A)
 *        (w = 0.75, 0.5, 0.2148; ≤ 1 mm) — the importer's blend
 *        `old + w·(anchor − path − old)`;
 *        the left Foot's WORLD rotation is unchanged on every frame
 *        (|Δ| ≤ 1e-6 per component, sign-aligned) — the toes stay flat;
 *        frames 14 … 29 of the left leg are UNCHANGED: ankle and knee world
 *        position (≤ 1e-6) and the three local quaternions (≤ 1e-6);
 *        the LIFT: frame 5 (θ = 0) — ankle 8 over ground 8 → lift 0 → its
 *        height stays 8 (±1e-3); frame 0 (sin θ = −0.1, cos θ = 0.994987) —
 *        ankle 108 − 99.4987 = 8.5013, lift 0.5013, down 1 → 8 (±1e-3);
 *        the report says pinnedCm (horizontal) > 0 (finite), liftCm
 *        (vertical) ≥ 0.5013 − 1e-3 (frame 0 came down by that), no
 *        pinReason, and driftCm (re-measured AFTER the pin) is below
 *        importedDriftCm.
 * [L5] THE PIVOTING RIGHT FOOT: its ball is v = (0, 12) off the ankle in XZ,
 *      turned by φ. Held at the middle point, ankle = M − v(φ)/2 and ball =
 *      M + v(φ)/2 with M fixed (≤ 1 mm), so each moves |v(φ_f) − v(φ_0)|/2 =
 *      6 · 2 sin(|φ_f − φ_0|/2) from where the run began — at most (f = 29,
 *      10°) 12 · sin 5° = 1.0459 cm for BOTH points (±1e-3). Holding the ankle
 *      (the importer's anchor) would leave the ankle at 0 and swing the ball
 *      by the whole 2 · 1.0459 = 2.0917 cm.
 * [L2] The template is untouched: every bone's local position and quaternion
 *      equal (exactly) their values before the call.
 * [L3] The same rig with the left KNEE bone renamed (`mixamorigLeftKnee` — no
 *      `LeftLeg`): the contact points are all there, so the path is still
 *      rebuilt, but there is no leg chain to bend: pinReason 'no leg bones',
 *      pinnedCm 0, liftCm 0, and no quaternion track of the clip changed (the
 *      values identical, no track added).
 * [L4] RED COUNTER-PROBE, same run: the left ankle's world XZ over f = 0 … 10
 *      WITHOUT the pin (u_f) moves ≥ 9.5 cm — the path alone cannot hold a
 *      foot that slides against the other one: each step moves the root by
 *      the mean slide of the fully planted points — left ankle and ball −2
 *      each, right ankle 0, right ball at most 12 · (10°/29 in rad) = 0.072 —
 *      so at most (2 + 2 + 0.072)/4 = 1.018 cm a frame, and the left ankle's
 *      world z still moves ≥ (2 − 1.018)·10 = 9.82 cm over f = 0 … 10.
 * [L6] THE SOLE-DOWN GATE on the rig: a second clip on the same rig, the left
 *      leg at rest, the right foot ROLLING ONTO ITS SIDE inside a planted
 *      stretch — `mixamorigRightFoot.quaternion` about Z (the foot's long
 *      axis) by α_f and its local position (0, −50 + r_f, −15):
 *        f      ≤10  11    12    13…16  17    18    ≥19
 *        α       0   45°   75°   90°    75°   45°    0
 *        r       0   0.25  0.5   1      0.5   0.25   0
 *      The ball (0, −5, 12) turned about Z stands 5 cos α under the ankle.
 *      Contacts: the right ankle at 8 + r over its ground min(2nd lowest 8,
 *      rest 8) = 8 → ≤ 1 cm → band 1; its vertical speed at most
 *      (1 − 0.25)·15 = 11.25 cm/s (f 12, 17) → 1: planted on EVERY frame.
 *      Sole-down: rest rise 8 − 3 = 5 → threshold 2.5; ankle − ball = 5 cos α
 *      = 5, 3.54 (45°) pass; 1.29 (75°), 0 (90°) fail → false on f 12 … 17.
 *      DOWN = pinRuns([1]*12 + [0]*6 + [1]*12): [0, 11] (fade-out 0.75, 0.5,
 *      0.25 on f 9 … 11) and [18, 29] (fade-in 0.25, 0.5, 0.75 on f 18 … 20).
 *      The LIFT = min(ankle − 8, ball − its ground 3) = r where the ankle is
 *      the lower of the two over its ground (ball 4.71 at f 11, 7.21 at f 12,
 *      9 on f 13 … 16): positive — without the gate the foot would come down
 *      on the rolled frames, one run over the whole take at weight 1:
 *      f 13 … 16 at 8. With it:
 *        f 13 … 16: the ankle stays at 9 (±1e-4) — not moved at all;
 *        f 11: lowered by down 0.25 × lift 0.25 = 0.0625 → 8.1875 (±1e-4);
 *        f 5: 8 (lift 0, ±1e-4).
 *
 * [P9] Task 31 additional leg_pin.json cases: shortest rotation from +X to +Y
 * is +90 degrees around +Z, quaternion (w,x,y,z)=(sqrt(1/2),0,0,sqrt(1/2)).
 * Applying that quaternion to (1,0,0) gives (cos 90,sin 90,0)=(0,1,0).
 */
```
