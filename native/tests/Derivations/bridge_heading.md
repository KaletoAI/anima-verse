# bridge_heading

- Origin: the browser scene's deleted `smoke_bridge_heading.mjs` @ 011cd048aa3cc2937186d7f35d2203af9491db8a
- Executed by: `native/tests/BridgeVectorTests.cs`
- Vectors: `shared/test-vectors/bridge_heading.json`

## Derivation

```text
/**
 * Smoke check for THE TURN OF A BRIDGE CLIP — the browser scene's `bridgeHeading.ts`
 * (the heading of the pelvis per frame), `bridgeTravel.turnAt` (its
 * interpolation) and the bake in `footLockMeasure.relockRootPaths` (the turn
 * moved out of the hips track), Task C2 of plan-bruecken-feinschliff.
 * § B5a: numbers, never screenshots. The whole chain on real rigs is
 * `smoke_bridge_root.mjs` [B12]–[B15].
 *
 * Usage:  node the browser scene's deleted smoke_bridge_heading.mjs
 *         (bundles the client modules itself; needs no clip files)
 *
 * Convention (clip frame, +Z forward, +X the figure's LEFT; yaw f means
 * forward (sin f, cos f), as in `bridgeTravel.toWorld` and three.js
 * `rotation.y`): L = leftUpLeg − rightUpLeg, heading = atan2(L.x, L.z) − π/2.
 *
 * [H1] Straight pelvis: left (10,100,0), right (−10,100,0) → L = (20,0,0),
 *      atan2(20, 0) − π/2 = 0.
 *      Turned 90° to the figure's RIGHT (forward now −X): left (0,100,10),
 *      right (0,100,−10) → L = (0,0,20), atan2(0, 20) − π/2 = −π/2.
 *      A two-frame take [straight, turned] → track [0, −π/2].
 * [H2] Unwrap: headings −170°, 175°, 160° (absolute) → relative track
 *      0, −15°, −30° (not +345°). A heading h is built as L = (cos h, 0,
 *      −sin h) · 20 (then atan2(cos h, −sin h) − π/2 = h), left = right + L.
 * [H3] A frame whose L vector is (0.1, 1, 0) (horizontal share
 *      0.1/|L| = 0.0995 < HEADING_MIN_HORIZONTAL 0.5) keeps the previous
 *      value: headings 0°, −20°, rolled, −40° → 0, −20°, −20°, −40°.
 *      A take that STARTS rolled takes the first valid value for its leading
 *      frames: rolled, rolled, 30°, 10° → relative to the first valid (30°):
 *      0, 0, 0, −20°.
 * [H5] turnAt: times [0,1,2], yaw [0, −0.5, −1.9] → t = 0.5 → −0.25
 *      (half way between 0 and −0.5), t = 5 → −1.9 (clamped), t = −1 → 0
 *      (clamped), NaN → 0 (the first key).
 *
 * THE SYNTHETIC SKELETON (template units = cm, unitsPerCm 1), the one of
 * `smoke_leg_pin.mjs`:
 *   rig (Group, identity)
 *   └ mixamorigHips            local (0, 108, 0)
 *     ├ mixamorig<Side>UpLeg   local (±10, 0, 0)     → world (±10, 108, 0)
 *     │ └ mixamorig<Side>Knee  local (0, −50, 15)    (a KNEE, not a `Leg`:
 *     │   │                     no leg chain, so the leg pin stays out and
 *     │   │                     only the turn is under test)
 *     │   └ mixamorig<Side>Foot local (0, −50, −15)  → world (±10, 8, 0)
 *     │     └ mixamorig<Side>ToeBase (0, −5, 12) └ mixamorig<Side>Toe_End (0, −3, 6)
 * THE CLIP, 30 keys f = 0 … 29 at 30 fps: the hips POSITION track holds
 * (0, 108, 0) (it gives the sample times), the hips QUATERNION turns about
 * +Y by α_f = −90° · f/29 (to the figure's right). The imported path is
 * preset to ZERO (`setClipRootPath`), so the clip counts as a travelling
 * bridge.
 *
 * [H6] The turn measured on it: the UpLegs sit at Ry(α)(±10, 0, 0) off the
 *      hips, so L = Ry(α)(20, 0, 0) = (20 cos α, 0, −20 sin α) and the
 *      heading is atan2(cos α, −sin α) − π/2 = α (α ∈ [−90°, 0]). Expected:
 *      `clipRootTurn(clip).yaw[f]` = −(π/2)·f/29 (±1e-5), its times the hips
 *      keys f/30, its pivot the hips' rest point in template-local
 *      coordinates (0, 108, 0) (±1e-6); the report's turnDeg = −90 (±1e-3).
 *      THE BAKE: the hips turned back about the vertical through the pivot
 *      by −α_f: world quaternion Ry(−α)·Ry(α) = identity on every key
 *      (|component − (0,0,0,1)| ≤ 1e-6, sign-aligned), position (0, 108, 0)
 *      unchanged (the pivot is on the hips' own vertical) (±1e-6).
 *      INVARIANCE (the rule `Figure` relies on): every bone's world position
 *      of the baked clip, turned by Ry(+ψ_f) about the pivot's vertical,
 *      equals the same bone of the SAME clip re-locked without the bake
 *      (`relockRootPaths(…, { turn: false })`) within 1e-3 cm on every key.
 *      A second call with `{ turn: false }` stores no turn.
 * [H7] A pelvis that never turns: the same rig and clip with α_f = 0 on
 *      every key → ψ ≡ 0 (below TURN_NONE_RAD 1e-6 everywhere): nothing to
 *      hand over — no turn stored, the hips tracks untouched (values
 *      identical), turnDeg 0, and the log line carries no turn part (like
 *      the pin part when it moved nothing).
 * [H4] Missing bones: the same rig with the UpLegs named `…Thigh` (no
 *      `LeftUpLeg`/`RightUpLeg`): no turn is stored (`clipRootTurn`
 *      undefined), the hips quaternion track is the one of the clip
 *      (values identical), the report's turnDeg is null with turnReason
 *      'no hip bones', and the log line says `turn: none (no hip bones)`.
 *      The figure then keeps its yaw — `Figure` reads no turn.
 */
```
