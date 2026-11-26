# bridge_root

- Origin: the browser scene's deleted `smoke_bridge_root.mjs` @ 011cd048aa3cc2937186d7f35d2203af9491db8a
- Executed by: `native/tests/BridgeVectorTests.cs`
- Vectors: `shared/test-vectors/bridge_travel.json`

## Derivation

```text
/**
 * Smoke check for BRIDGE CLIPS WITH ROOT MOTION — the browser scene's `bridgeTravel.ts`
 * and its consumer `figures.Figure` (§ B5a: numbers, never screenshots).
 *
 * Usage:  node smoke_bridge_root.mjs   (historical; the runner was deleted with the browser scene in E3)
 *         (bundles the client modules itself; part [B] needs the re-imported
 *          `get-up-chair` / `get-up-bed` in shared/models/clips — READ ONLY)
 *
 * ===========================================================================
 * WHY THIS FILE EXISTS
 * ===========================================================================
 * Every clip used to play "in place": `adaptExternalClips` throws the hips'
 * horizontal track away, so a figure standing up out of a chair kept its hips
 * over the seat while the legs pushed it forward — the feet slid ~0.4 m over
 * the floor. The importer can now bake a FOOT-LOCKED travel into the hips
 * track (`root_motion.mode = foot_lock`), and the client carries the figure
 * along that travel while the bridge plays, then hands the offset to whoever
 * owns the figure's position (`Figure.takeTravel`).
 *
 * ---------------------------------------------------------------------------
 * [A] pure arithmetic and the Figure's bookkeeping (no clip files needed)
 * ---------------------------------------------------------------------------
 * [1] travelAt: path times [0, 1, 2], xz [0,0, 0,0.2, 0,0.4] (metres):
 *       t=0 → (0,0); t=0.5 → (0,0.1) (half way between the keys 0 and 0.2);
 *       t=2 → (0,0.4); t=5 (past the end) → (0,0.4) (clamped);
 *       t=-1 → (0,0) (clamped). The offset is RELATIVE to frame 0: a path
 *       starting at (0.1, 0.1) with the same steps gives the same answers.
 * [2] toWorld((0, 0.4), yaw 0) → (0, 0.4); yaw π/2 → (0.4, 0) (x' = 0·0 +
 *       0.4·1, z' = −0·1 + 0.4·0); yaw π → (0, −0.4);
 *       toWorld((0.1, 0), π/2) → (0, −0.1) (x' = 0.1·0 + 0, z' = −0.1·1).
 *       (Compass facing f is three.js rotation.y = f: forward (sin f, cos f);
 *       the figure's left at facing 0 is +x, at facing 90° it is −z.)
 * [3] Figure with a root-motion bridge (accel 0), on a real rig with a
 *       SYNTHETIC library whose numbers are chosen so
 *       the travel is known by hand (on `Soldier.glb`, whose origin is at
 *       its feet — `Test3_mia` is centred on its hips): every clip holds the hips at 100 source
 *       units (so the standing reference `sourceRest` = 100), and the bridge
 *       moves the hips from (0, 100, 0) to (10, 100, 40). The client scales a
 *       hips length by k = H_t / 100 (H_t = the rig's rest hips height in
 *       template units) and the instance by s = 1.70 / rawHeight, so the
 *       travel in world metres is
 *           (10, 40) · k · s = (0.1, 0.4) · H,   H = H_t · s,
 *       H being the figure's rest hips height in world metres (read off the
 *       template here, not out of the Figure). Facing yaw = 0.6 rad. After
 *       the clip ends: holdsTravel true, takeTravel() = toWorld((0.1H, 0.4H),
 *       0.6) to 1e-4; the instance is back on its base XZ; a second
 *       takeTravel() returns null.
 *       [3b] Rule 5: a SECOND bridge started while the first travel is still
 *       held warns once and folds the held offset into the new one — the
 *       final takeTravel() is twice the single travel.
 * [4] The same clip as a RAMPING bridge (accel 1): no offset during or after
 *       (holdsTravel false, instance XZ on its base) — the figure walks off
 *       by itself.
 *       (The reference-rig hips height handed to `adaptExternalClips` is 100
 *       source units too — the synthetic "rig" the clips were authored on.)
 * [8] No reference rig served (`donorHipsY` undefined or NaN): the travel
 *       cannot be scaled, so there is none — the bridge plays in place, no
 *       hold, the instance never leaves its base and never turns NaN, and one
 *       console.warn covers the session (two adaptations, one line) — plus,
 *       separately, the one line saying the STANDING reference fell back to
 *       the idle clip (`standingHipsRef`, smoke_rig_stand_ref.mjs).
 * [5] Bridge ended, nobody took the travel yet, three more update() frames
 *       (with the next clip asked for, as `npcs.tick` does): instance x/z
 *       unchanged (no snap back to the seat).
 *
 * ---------------------------------------------------------------------------
 * [B] the whole chain on REAL rigs, measured at the CONSUMER
 * ---------------------------------------------------------------------------
 * `Test3_mia.glb` (server mesh pipeline), `Soldier.glb` (Mixamo fallback
 * rig) and the reference rig itself (life-size, its centimetres × 0.01), the
 * real neutral clips (`idle` gives the standing reference, the seat/bed clip
 * is the state the bridge leaves), the reference rig's rest pose for the
 * bind-relative transplant (`restCorrections`, exactly what `FigureLibrary`
 * does when `/assets/animation-rig` is served), the real
 * `adaptExternalClips`, and then — as `FigureLibrary.fitLibrary` does right
 * after it — `relockRootPaths(clips, template, 1 / (100 · scale))`, ONE call
 * per model over its library at the model's nominal scale (1.70 m ÷ mesh
 * height; 0.01 for the reference rig), which rebuilds the travel AND pins the
 * planted feet by leg IK (`legPin.ts`, `smoke_leg_pin.mjs`). A real `Figure` inside an owner group
 * plays the NPC root. What is measured is the WORLD position of the bones
 * `LeftFoot`/`LeftToeBase`/`RightFoot`/`RightToeBase` of the rendered
 * instance, frame by frame at 30 fps (the clips' own rate); figure frame i is
 * clip time (i+1)/30. The first 0.30 s are left out everywhere: the bridge
 * fades in over 0.25 s from the seat clip, those frames are a blend.
 *
 * WHICH POINT IS PLANTED, WHEN — the smoke's OWN contact detection on the
 * RENDERED rig (its own code here, not `footLock.ts`): "planted" is a
 * property of the rig the feet belong to. The importer's constants: a
 * point's ground is the 5th percentile of its heights (over the frames
 * after the fade), capped at its bind-pose rest height (the importer's rule
 * and the client's: no lift tolerance — with the rig's rest hips height as
 * the standing reference an adapted clip no longer stands lifted over the
 * rest, `smoke_foot_lock_measure.mjs` [C8]); rest heights come
 * from THAT rig's bind pose, each point over the lowest of the four points
 * and the toe ends. Weight = ramp(height − ground, 2, 5 cm) ×
 * ramp(|vertical speed|, 15, 30 cm/s) (central difference); a frame at
 * ≥ 0.999 is FULL. Drift = the largest horizontal distance a point moves
 * from where its run of FULL frames began. Each run is judged on its OWN
 * contacts: the leg pin lowers planted feet in the re-locked library, so its
 * heights are not those of the imported / offset-off runs (which share
 * theirs — the travel is XZ only).
 *
 * INFO only, the measurement [6] bounded before this plan: the importer's
 * classification (`_root_motion.contact_weights` re-run on the REFERENCE rig
 * with the RAW clip) inside the sidecar's `contact_s` windows. Cross-check:
 * on the reference rig that classification gives the sidecar's
 * `max_drift_cm` back (+0.05 cm). On another rig it transplants the
 * reference rig's contacts onto feet that are not planted there (Test3_mia
 * bed: 3.13 cm re-locked, although its own feet hold 2.27 cm).
 *
 * [6] foot_lock clips: planted-foot drift, own contacts, per clip, on ALL
 *       THREE rigs: <= 1.5 cm for get-up-chair AND get-up-bed — the
 *       importer's guarantee, now per rig. The bed turns ~90° while both
 *       feet are planted, which a translation-only path could not hold (it
 *       had 2.5 cm, the rule's residual 2.27 cm on Test3_mia); the leg pin
 *       holds each foot in place of the path, so the bed takes the chair's
 *       bound (Task C6).
 *       HISTORY (imported path only, sidecar spans, 2026-09-25): chair
 *       Test3_mia 2.20, Soldier 1.09, reference 0.30; bed 4.76, 2.95, 1.31 —
 *       bounded then by 2.5 / 5.0 cm.
 *       BEFORE Task C6 (path re-locked, NO leg pin; own contacts, re-locked /
 *       imported, cm) — the old get-up-chair (63e48659) and, in brackets, the
 *       re-import with both feet planted through the rise (B1/B2), which the
 *       path alone could no longer hold:
 *         chair  Test3_mia 1.41 / 2.20 [3.86 / 5.03]   Soldier 0.68 / 1.44 [1.59 / 4.89]
 *                reference 0.42 / 0.42 [1.04 / 1.04]
 *         bed    Test3_mia 2.27 / 2.83   Soldier 1.66 / 3.07   reference 1.43 / 1.43
 *       AFTER (the re-imported chair, leg pin on; re-locked + pinned /
 *       imported, cm):
 *         chair  Test3_mia 0.58 / 5.03   Soldier 1.02 / 4.89   reference 0.64 / 1.04
 *         bed    Test3_mia 0.70 / 2.83   Soldier 1.30 / 3.07   reference 1.11 / 1.43
 *       The re-lock's own report (`relockRootPaths`, its contacts on the
 *       probe clone, the bridge's fade-in included; drift rebuilt / imported
 *       before the pin, the largest horizontal hold / vertical lift of an
 *       ankle, the drift after it):
 *       Test3_mia chair 3.86 / 5.03, held 2.66 / lifted 2.08 → 0.45; bed
 *       2.27 / 3.00, 2.15 / 2.08 → 0.55; Soldier chair 1.63 / 4.91, 0.59 /
 *       1.63 → 1.03; bed 1.66 / 3.14, 1.41 / 2.08 → 1.00; the reference rig
 *       keeps its IMPORTED path for BOTH clips — chair imported 1.05 (rebuilt
 *       1.05), bed imported 1.43 (rebuilt 1.44): the rebuild gains less than
 *       `RELOCK_MIN_GAIN_CM` = 0.1 cm there — and is pinned on it: chair
 *       0.26 / 0.66 → 0.64, bed 1.81 / 2.08 → 0.44 (the bed is an import
 *       from before the importer's foot plant). The 2.08 is the most the
 *       lift can move: a foot h cm over its ground weighs (5 − h)/3 in the
 *       contact band and comes down by that × h, at most 2.5 · 2.5/3 =
 *       2.083 cm (h = 2.5). CHECKED:
 *       every report on the reference rig says used 'imported'; own contacts
 *       hold <= 1.5 cm for BOTH clips there (checked).
 *       COUNTER-PROBE in the same run, the IMPORTED path (no re-lock, no pin)
 *       measured the same way: never lower than the re-locked one (clip ×
 *       rig), and on Test3_mia / get-up-chair the re-lock gains >= 0.5 cm —
 *       Task 2 measured 2.20 → 1.23 cm (sidecar spans), a gain of 0.97; the
 *       path alone on the re-imported chair gains 5.03 → 3.86 = 1.17, with
 *       the pin 5.03 → 0.58 = 4.45; the checked floor of 0.5 cm stays well
 *       under all of them.
 *       RED COUNTER-PROBE: offset switched off (the library adapted WITHOUT
 *       the root-motion flag): chair >= 15 cm, bed >= 25 cm (measured, chair
 *       / bed: Test3_mia 35.9 / 32.2, Soldier 58.2 / 45.5, reference 70.0 /
 *       53.2 cm).
 *       RED COUNTER-PROBE of the scale (reference rig, sidecar spans): the
 *       idle-median scale overshoots the importer's own number by > 0.10 cm.
 * [7] End of bridge + takeTravel + owner root moved by it (re-locked
 *       library): the rendered foot positions of the last bridge frame and of
 *       the frame after the hand-over (no time advanced) differ by <= 1 cm.
 *       RED COUNTER-PROBE: takeTravel WITHOUT moving the owner jumps the feet
 *       by the whole travel (>= 30 cm for the chair).
 * [B9] LINEARITY PROOF, per clip × rig: the same figure drawn with
 *       baseScale × 1.15 (a 1.955 m body) on the path re-locked at the
 *       nominal scale; contacts judged at the nominal scale (heights ÷ 1.15 —
 *       the thresholds are written for it), drift in WORLD cm. Expected:
 *       drift(×1.15) = 1.15 × drift(×1) within 1 %. In the client the re-lock
 *       scale IS the figure's baseScale (`fitLibrary(…, model.scale)` and
 *       `Figure.baseScale = model.scale`), so no figure is ever drawn at
 *       another scale than its path was built for — what this check proves
 *       is that the path scales with the body (instance and travel both ×
 *       baseScale), not an extra tolerance on the [6] bounds. The leg pin
 *       bakes ROTATIONS, which do not care for the scale. Measured (chair /
 *       bed): Test3_mia 0.67 / 0.80 cm (= 1.15 × 0.58 / 0.70), Soldier
 *       1.17 / 1.49, reference 0.73 / 1.28.
 * [B10] INFO: distance of the handed-over end point from the server's stand
 *       point (`travel_m × height / ref_height_m`, turned by the same yaw;
 *       height 1.70 m, the reference rig = ratio 1), per rig, cm. Measured
 *       re-locked / imported: Test3_mia chair 9.6 / 5.2, bed 14.9 / 5.4;
 *       Soldier 2.0 / 1.4, 3.5 / 1.5; reference 0.0 / 0.0 (the pin moves
 *       feet, not the travel: the chair's numbers changed with its
 *       re-import, B2).
 * [B11] relockRootPaths per model (one call, both bridges, the leg pin
 *       included) <= 100 ms, printed (measured 4–5 ms before the pin,
 *       9.6–14.3 ms with it).
 * [B12]–[B15] THE TURN HANDED FROM THE HIPS TO THE ROOT (Task C2,
 *       `bridgeHeading.ts`, `Figure.turn`). `relockRootPaths` measures the
 *       pelvis heading ψ(t) of each bridge on each rig (LeftUpLeg→RightUpLeg),
 *       turns the hips tracks back by −ψ(t) about the hips' rest vertical and
 *       stores the turn; the Figure turns its root by +ψ(t) and keeps ψ_end.
 *       COUNTER-PROBE library in the same run: the same re-lock with
 *       `{ turn: false }` (the state before C2). Each run: owner at (3, 0, −2),
 *       facing YAW, the source clip for 1 s, the bridge, then the owner takes
 *       the travel over (`takeTravel`, as `npcs` does) and idle plays.
 * [B12] INVARIANCE: every bone's world position on every bridge frame from
 *       0.30 s on, WITH the hand-over, equals the counter-probe's within
 *       1 mm (max over bones × frames). The turn is only moved from the hips
 *       into the root, about the same vertical, so the two differ by float
 *       noise (measured ≤ 0.001 mm). The fade-in frames are left out, as
 *       everywhere in [B]: the clip being LEFT fades out under a root that
 *       already turns by ψ and is not turned back — the difference is ψ over
 *       the fade (chair 2.3–2.9 mm, printed as info). On the bed the working
 *       tree's lying clip on 2026-09-26 (a foreign modification of
 *       `laying.fbx`) stands with its hips 180° against get-up-bed's first
 *       frame (quaternion dot 0.0000; the committed file 0.95): that fade is a
 *       near-antipodal slerp whose direction a 1e-5 rad difference flips —
 *       up to 1.7 m in single fade frames, which says nothing about the turn.
 * [B12b] get-up-bed: a journey that starts early takes the travel at 1.6 s,
 *       mid-turn, the owner moves by it: no foot moves (<= 1 mm); the turn
 *       goes on, the end holds the pivot's swing again, and the second
 *       `takeTravel` moves no foot either (<= 1 mm); the root ends on
 *       base + ψ_end (1e-6).
 * [B13] NET TURN: get-up-bed ψ_end within −115° … −98° on all three rigs,
 *       get-up-chair |ψ_end| <= 8° (brief, measured by the analysis harness
 *       −104.8 / −108.9 / −109.3 and −4.5). Measured here (after the per-rig
 *       pin, which bends the legs below the UpLegs and so does not change ψ):
 *       bed Test3_mia −105.83°, Soldier −105.55°, reference −104.75°; chair
 *       −4.78°, −4.46°, −4.52°. The counter-probe stores no turn.
 * [B12c] get-up-bed played DIRECTLY (no holding bridge, so no root turn,
 *       its pose turned back by −ψ) warns once — played twice, one line —
 *       and none of the holding-bridge runs before it warned (Test3_mia).
 * [B14] NO SNAP INTO THE NEXT CLIP, predicted in the same run. The first
 *       idle frame after the hand-over (1/30 s) blends the bridge's last pose
 *       (clamped, weight 1 − W) with the idle's pose at clip time 1/30 s
 *       (weight W = (1/30)/0.25 = 0.1333, its fade-in), both in the root
 *       frame the hand-over left — the rotation ACTUALLY handed over, ψ_end.
 *       R_ψ = the largest horizontal distance of a foot point between those
 *       two poses in the root frame (the idle's pose read off a fresh figure of
 *       the rig by a mixer of its own; the instance on its base, as after
 *       `takeTravel`). To first order each foot moves W · its own distance.
 *       A single-joint arc is not a bound for an articulated pose: joint rotations can cancel at the
 *       endpoint and still move a foot during the blend. Task 86 baseline chair failures were 1.19/1.26/1.25 cm
 *       against invalid 0.63/0.79/0.63 cm bounds. The reference now independently blends each bone's local
 *       position/quaternion and evaluates FK on a fresh stationary rig; every foot must match within 0.1 mm.
 *       The endpoint chord and shortest lever remain diagnostic values. The no-turn bed counter-probe still
 *       requires >= 6 cm of foot movement and B15 independently checks the final heading.
 * [B15] THE ROOT KEEPS ψ_END: after 1 s of idle (the bridge long faded out)
 *       the pelvis heading in the WORLD equals base + ψ_end + h_idle within
 *       0.1°, h_idle = the idle's own pelvis heading against its root at that
 *       clip time, from a fresh figure playing idle alone. At 1 s both are the
 *       same idle frame, so this checks that the root still holds
 *       base + ψ_end — nothing eased it away — and the root yaw itself is
 *       base + ψ_end (1e-6). Measured h_idle: +6.01° (Test3_mia), +5.85°
 *       (Soldier), +6.43° (reference).
 *       INFO, the meaningful number: the pelvis heading's step at the SEAM
 *       (last bridge frame → first idle frame): 0.41° / 0.47° / 0.58° on the
 *       bed, 0.15° / 0.16° / 0.16° on the chair; without the hand-over 14.5°
 *       on the bed.
 *       RED COUNTER-PROBE (bed): without the hand-over the pelvis is >= 90°
 *       off (it swings back to base + h_idle: |ψ_end| ≈ 105°).
 * [B17] THE CHAIR'S END, BOTH FEET ON THE FLOOR: from t >= 3.5 s (40
 *       frames), per side the lowest of the foot's bones (Foot, ToeBase,
 *       Toe_End) over the rig's rest floor, MEDIAN over those frames — the
 *       measure Task B2 used, so the numbers compare; single frames reach
 *       further (printed as the range) — within ±1.0 cm on every rig. Task B2 measured it on the re-imported chair
 *       without the pin (right / left, cm): Test3_mia −0.53 / 0.82, Soldier
 *       1.30 / 1.15, reference 0.01 / 0.00 — Soldier's feet stood 1.2–1.3 cm
 *       up (old chair: right foot 3.84 there). With the pin: Test3_mia
 *       −0.93 / 0.33, Soldier −0.25 / −0.55, reference 0.01 / −0.16 (the
 *       pin brings a foot to the ground of its points, `groundHeights` —
 *       the low 5th percentile of the adapted clip itself, which on
 *       Test3_mia lies 1.01 cm under the rest floor for the right ball, in
 *       the same frame as the rest heights — the tightest case).
 *   info  The re-lock's own report per clip, the per-point numbers (FULL
 *       frames, runs, worst run and its span, drift re-locked / imported /
 *       off / × 1.15) and the final drift table.
 *
 * ---------------------------------------------------------------------------
 * [Y] NOTHING TURNS OR STEPS A FIGURE A BRIDGE HOLDS
 * ---------------------------------------------------------------------------
 * A bridge with `accel` 0 (getting up out of bed) owns the whole body: its
 * yaw as much as its place. [Y1]/[Y2] run in part [A] (the synthetic Soldier
 * bridge, 1 s, accel 0 — no clip files needed), [Y3] after part [B] (the
 * real clips).
 * [Y1] The figure faces yaw 0.6, the bridge opens, and on EVERY bridge frame
 *       `faceTowards(+x, snap)` (yaw atan2(1, 0) = π/2) and then
 *       `setYaw(1.0)` are asked for. `root.rotation.y` stays 0.6 ± 1e-6 for
 *       the whole bridge — the synthetic bridge holds every bone at rest, so
 *       its own turn (Task C2, `clipRootTurn`) is exactly 0 and the root has
 *       nothing to follow. Before C1 the snap turned the root to π/2 at
 *       once: |π/2 − 0.6| = 0.9708 rad.
 *       [Y1r] COUNTER-PROBE, same asks on a RAMPING bridge (accel 1): it
 *       keeps its turn — the figure is about to walk off — so rotation.y
 *       leaves 0.6 by more than 0.1 rad.
 * [Y2] After the bridge nobody asks again, the frames go on (the next clip
 *       asked for as `npcs.tick` does): the figure eases towards the LAST
 *       direction asked for, 1.0. After 2 s = 60 frames the rest is
 *       0.4 · (2/3)^60 ≈ 1e-11 rad, so |rotation.y − 1.0| < 0.05.
 * [Y3] The REAL `NpcManager.tick` (one injected NPC) over the real chain on
 *       Test3_mia (`adaptExternalClips` → `relockRootPaths` →
 *       `measureGroundOffsets` → `Figure`, the order of `fitLibrary`; clips idle, walk,
 *       the lying clip, get-up-bed; rule <lying clip> → * via get-up-bed,
 *       accel 0 — the lying clip is the one the live transition table names
 *       for get-up-bed if tracked, else the tracked `laying`, else [Y3] is
 *       skipped, `bridgeSources.mjs`). The NPC
 *       lies (`animation` = the lying clip, goal = its root), then the server
 *       stands it up: `animation` idle, goal 0.5 m away (< RUN_DISTANCE 6 m:
 *       walk). In the ONE tick that starts the bridge (checked: bridging
 *       after it) the root moves <= 1 mm in X/Z. Before this task the step
 *       read `paceLimit` before the clip was asked for: min(0.5, 3.4 m/s ·
 *       1/30 s) = 11.33 cm (C0 § 5.1).
 *       [Y3c] COUNTER-PROBE, same run: an NPC standing on idle (idle → walk
 *       has no rule) with the same goal steps the full 3.4/30 = 0.11333 m ±
 *       1e-4 in its first tick — the gate holds a bridge, nobody else.
 *       [Y3b] The NPC lies again, stands up with its goal ON its root (not
 *       moving — the standing branch) and a marker facing +x: rotation.y is
 *       the same ± 1e-6 on every bridge frame as that of a TWIN standing up
 *       the same way without a marker — since Task C2 the root turns by the
 *       bridge's own turn (get-up-bed, ~105°), which both share; the marker
 *       adds nothing. Before C1 it eased to the marker's π/2: 0.9708 rad off.
 *       [Y3d] After the bridge the gate opens: the first tick after it hands
 *       the bridge travel over (the ROOT moves by it, `applyBridgeTravel`;
 *       the goal stays, Task C4), and within the 1 s after THAT tick the root
 *       walks >= 5 cm. The goal does not become a kept spot
 *       (`settleAfterBridge`): in the figure's frame it lies 0.5 m ahead
 *       (0, 0.5), the travel sets the body down near (−0.485, −0.073) (the
 *       server's point of [Y3e]) — sqrt(0.485² + 0.573²) = 0.75 m apart, so
 *       even 0.25 m off that point the body is >= 0.50 m > STAND_ADOPT_M from
 *       the goal and walks (1 s of walking is up to 3.4 m).
 *       [Y3e] THE SERVER'S STAND POINT IS THE GOAL (Task C4): the NPC lies,
 *       stands up with its goal on `room_stand.bridge_stand_point` = seat +
 *       toWorld(travel_m · k, YAW), k = 1.70 / ref_height_m — get-up-bed:
 *       travel_m (−0.574, −0.086), ref 2.011 m → k = 0.84535, travel·k =
 *       (−0.48523, −0.07270), |.| = 0.49065 m from the seat. After the bridge
 *       and its hand-over: the root lands within STAND_ADOPT_M = 0.25 m (the
 *       `pick_stand` raster, app/core/room_stand.py STAND_GRID_M) of that
 *       point — client and server measure the same clip's travel, the client
 *       per rig with the turn in the root —, the goal IS the root (<= 1e-6)
 *       and the root does not move in the 1 s after (<= 1e-6). BEFORE C4 the
 *       hand-over moved the goal by the travel as well (≈ 0.36 m past the
 *       root, C0 § 5.2) and the NPC walked towards it: 34 cm in that second.
 *       [Y3f] A JOURNEY THAT STARTS WHILE THE NPC GETS UP (carried from the C1
 *       review): the NPC lies, stands up (goal = the stand point of [Y3e]),
 *       and JOURNEY_AT_F = 30 frames into the bridge a journey starts
 *       (route seat → stand point → 5 m ahead, progress at the stand point,
 *       1.4 m/s, `travelling`). For every remaining bridge frame the root
 *       X/Z moves <= 1 mm — the catch-up is gated by the bridge like the step
 *       without a route. BEFORE C4 the catch-up stepped WALK_SPEED/30 =
 *       11.33 cm per frame while the body was getting up: this per-frame
 *       check is the PROOF. Two SUPPORTING checks follow (both pass on the
 *       code before C4 as well, so they prove nothing about the gate; they
 *       pin the hand-over around it): the travel waits for the bridge's end
 *       (still held then), and within 1 s after the bridge it is handed over
 *       and the route pulls the root >= 5 cm.
 *
 * Task 31 additional bridge_travel.json cases: rootPathAt is absolute, so
 * moved path midpoint t=.5 is (.1, .1+(.3-.1)/2)=(.1,.2).
 * An empty absolute/relative path returns (0,0). NaN time selects frame 0;
 * subtracting that same origin in travelAt gives (0,0).
 */
```
