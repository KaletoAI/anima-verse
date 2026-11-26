# bridge_lift

- Origin: the browser scene's deleted `smoke_bridge_lift.mjs` @ 011cd048aa3cc2937186d7f35d2203af9491db8a
- Executed by: `native/tests/BridgeVectorTests.cs`
- Vectors: `shared/test-vectors/bridge_lift.json`

## Derivation

```text
/**
 * Smoke check for THE HEIGHT OF A HOLDING BRIDGE — the browser scene's `bridgeLift.ts`,
 * its measurement in `footLockMeasure.relockRootPaths` and its consumers
 * `figures.Figure` (`beginBridgeLift`, `holdsHeight`) and `npcs.NpcManager.tick`
 * (§ B5a: numbers, never screenshots). Task C5 of plan-bruecken-feinschliff.
 *
 * Usage:  node smoke_bridge_lift.mjs   (historical; the runner was deleted with the browser scene in E3)
 *         (bundles the client modules itself; part [V] reads the clips
 *          idle, walk, get-up-bed, get-up-chair, the pair half greeting-handshake__a
 *          and the two clips the bridges leave from shared/models/clips —
 *          READ ONLY)
 *
 * WHICH CLIPS ARE LEFT (`bridgeSources.mjs`): the lying clip is the first
 * `from` the live transition table (`shared/config/clip_transitions.json`,
 * read at run time) names for get-up-bed whose .fbx exists AND is tracked by
 * git; otherwise the tracked `laying`. The sitting clip likewise for
 * get-up-chair, fallback `recovering`. No tracked clip → the bed or
 * chair part is SKIPPED with a message. The run prints which it used.
 *
 * ===========================================================================
 * WHY THIS FILE EXISTS
 * ===========================================================================
 * Task C0 measured an NPC getting out of bed: the server's stand point is the
 * FLOOR (+ WALK_CLEARANCE_M = 0.01), it arrives in the same poll as the
 * standing clip, and `npcs.tick` eased the root down to it with 4·dt from the
 * first bridge frame on — the lying body sank up to 35 cm (bed 0.46 m) / 46 cm
 * (0.60 m) into the mattress, the feet ended 31–43 cm UNDER the floor and the
 * figure hopped 36 cm up when the next clip faded in. The avatar kept its
 * root on the bed: feet 13.5 / 27.5 cm over the floor at the end, and without
 * input afterwards the idle feet hung 49 / 63 cm beside the bed for good.
 * Re-measured on this tree before the fix (Test3_mia / Soldier / reference
 * rig, lowest foot bone over y = 0, last bridge frame): NPC −32.0 / −37.0 /
 * −45.0 cm (both beds); avatar bed 0.46 +12.5 / +7.5 / −0.6, bed 0.60
 * +26.5 / +21.5 / +13.4; avatar without input, 0.5 s after: +47.0 / +47.3 /
 * +45.6 (bed 0.46).
 *
 * THE RULE NOW: during a holding bridge the owner keeps the root in X/Z only;
 * it puts the root ONCE, at the bridge start, onto the new floor and hands the
 * difference to the figure as `startLift`. The figure draws the body at
 * `root + startLift` (on the bed) until `LIFT_RAMP_S` before the feet's first
 * full contact, then smoothsteps onto `endLift` — measured per rig so that the
 * lowest foot point of the clip's LAST frame stands on the rig's REST floor.
 *
 * THE FLOOR every check below measures against is the plane the figure stands
 * on: its root goal, floor 0 + WALK_CLEARANCE_M = 0.01 m (the NPC's stand
 * point, `main.ts` server stand point; the avatar's `groundAvatarGoal` /
 * walking goal, `roomFloorY`). A foot "on the floor" is a foot BONE point
 * (Foot, ToeBase, Toe_End of both sides — the points of the rest floor) at
 * that plane plus the rig's own rest height of it over the bind soles, r:
 * Test3_mia 0.33 cm, Soldier 1.34 cm, the reference rig 0 (its bind box IS
 * its bones) — measured on the rigs (lowest foot bone over the bind box
 * floor at the nominal scale).
 *
 * ---------------------------------------------------------------------------
 * [L] liftAt — pure, by hand (smoothstep s(x) = x²(3 − 2x))
 * ---------------------------------------------------------------------------
 * [L1] startLift 0.46, endLift 0.358, firstContactS 2.4 → ramp from
 *      2.4 − 0.6 = 1.8 s: t=0 → 0.46; t=1.8 → 0.46; t=2.1 (x = 0.5,
 *      s = 0.25·2 = 0.5) → 0.46 − 0.102·0.5 = 0.409; t=2.4 → 0.358;
 *      t=4 → 0.358.
 * [L2] firstContactS 0.03 (a chair whose feet stand from the start): the ramp
 *      never ends before the bridge's start crossfade BRIDGE_FADE_IN_S = 0.25
 *      → window [max(0, 0.25 − 0.6) = 0, max(0.03, 0.25) = 0.25]:
 *      t=0 → startLift (0.042); t=0.125 (x = 0.5, s = 0.5) → 0.021;
 *      t=0.0625 (x = 0.25, s = 0.0625·2.5 = 0.15625) → 0.042 − 0.042·0.15625
 *      = 0.0354375; t=0.25 → endLift (0.0); t=0.03 (x = 0.12, s = 0.0144·2.76
 *      = 0.039744) → 0.042·(1 − 0.039744) = 0.040330752 — NOT endLift any
 *      more (before: a drop of the whole 4.2 cm within 0.03 s).
 *      liftRamp(0.03) = {0, 0.25}; liftRamp(2.4) = {1.8, 2.4};
 *      liftRamp(0.4) = {0, 0.4}.
 * [L3] startLift == endLift (0.2) → 0.2 for t = 0, 1.9, 2.1, 2.4, 9.
 * [L4] non-finite t / endLift / firstContactS → startLift (0.46); a NaN
 *      startLift counts as 0 — never NaN.
 * [L5] fadeCarry(0.1, e): e=0 → 0.1; e=0.3 (x = 0.5) → 0.05; e=0.15
 *      (x = 0.25, s = 0.15625) → 0.084375; e=0.6 → 0; e=2 → 0; NaN → 0.
 *
 * ---------------------------------------------------------------------------
 * [V] the whole chain on REAL rigs, measured at the CONSUMER
 * ---------------------------------------------------------------------------
 * Test3_mia.glb, Soldier.glb (1.70 m, nominal scale 1.70 / mesh height) and the
 * reference rig (its centimetres × 0.01, 2.011 m); the real clips through
 * `adaptExternalClips` → `relockRootPaths` (which now also measures the
 * lift) → `measureGroundOffsets` → `Figure`, the order of `fitLibrary`.
 * Rules: <lying clip> → * via get-up-bed, <sitting clip> → * via
 * get-up-chair, both accel 0 (they hold). 30 fps (the clips' own rate).
 *
 * The bed: lying place at S = 0.46 and 0.60 m, `lie` root_drop 0.001 · H
 * (pose_catalog groups; H = 1.70, the reference rig 2.011) → root at S −
 * 0.0017 (S − 0.0020). Yaw 0.7 (heights do not depend on it).
 * The chair: seat S = 0.45 m, `seat` root_drop 0.234 · H → root at
 * 0.45 − 0.3978 = 0.0522 m (reference rig 0.45 − 0.4706 = −0.0206 m), so the
 * chair's startLift = root − 0.01 = 0.0422 m (−0.0306 m).
 *
 * NPC = the REAL `NpcManager.tick` with one injected NPC (the pattern of
 * smoke_bridge_root [Y3]): it lies/sits on its slot (goal = its root), then
 * the server stands it up — `animation` idle and goal = the server's stand
 * point (slot + the clip's travel_m × H / ref_height_m turned by the yaw,
 * y = 0.01), delivered once a second through the real `update()` (which
 * since Task C4 keeps the spot the bridge left the figure on when it is
 * within 0.25 m of that point).
 * AVATAR = the same manager with the figure player-driven: seated by
 * `snapPlayerTo`, then the release `main.ts` does now — clip cleared (key:
 * walk while held) and `groundAvatarGoal` (goal = seat X/Z at the floor
 * height 0.01) — and per frame the steering hook's part that matters here:
 * `takePlayerTravel`, and with the key held, once `paceLimitFor(walk)` lets
 * go, a walking goal 0.3 m ahead at y = 0.01.
 *
 * [V1] NPC, bed: from the first bridge frame while the clip time is before
 *      the ramp (`liftRamp(firstContactS).from`), the lowest trunk bone (hips,
 *      spines, neck, head, shoulders) − S >= min(0, the same measure while it
 *      still LAY) − 5 cm. The body is drawn where it lay (root + startLift =
 *      the old root), so the lift adds nothing; what is left is the 0.25 s
 *      crossfade from the lying clip into the first pose of get-up-bed
 *      (sleeping-side: −4.3 cm on Test3_mia, C0's avatar column, where the
 *      root never left the bed). A lying clip whose own pose already reaches
 *      under S (the tracked `laying` on Test3_mia: −10.3 cm, the clip and the
 *      `lie` root_drop, not the bridge — INFO line) is judged from there.
 *      Before: −35.8 / −46.9 cm (Test3_mia, sleeping-side, S = 0.46 / 0.60).
 * [V2] last bridge frame: lowest foot − floor within ±1.5 cm, both S, three
 *      rigs, NPC and avatar (key held / no input). By construction the lift is
 *      `endLift` there, which puts the lowest foot point of the clip's last
 *      frame on the rest floor, r over the root plane: 0.33 / 1.34 / 0 cm
 *      (the last bridge frame is up to one frame before the clip's end).
 *      COUNTER-PROBE in the same run, the lift removed from the clip (and the
 *      avatar's goal not written, as before): NPC <= −25 cm (today −32 / −37 /
 *      −45 over y = 0).
 * [V3] from the last bridge frame through 0.5 s after it, no 36 cm hop: the
 *      fade-out lift (lift × the bridge's weight) carries the body across the
 *      crossfade into the next clip.
 *      [V3a] into IDLE (the avatar without input, and since Task C4 the NPC
 *      that keeps the spot its bridge left it on — within STAND_ADOPT_M
 *      = 0.25 m of the server's stand point): lowest foot − floor
 *      within −2 … +3 cm — idle's own foot lift over the root is +1.5
 *      (Test3_mia) / +1.8 (Soldier) / +0.2 cm (reference; the A1 measure).
 *      The NPC SETTLES on every rig, and that is checked, not only observed:
 *      its hand-over lands 14.58 (Test3_mia) / 3.80 (Soldier) / 0.01 cm
 *      (reference) off the stand point (measured), all under STAND_ADOPT_M
 *      = 25 cm — a broken settle fails there instead of quietly moving the
 *      NPC to the [V3b] bounds.
 *      [V3b] into WALK (the NPC walking on to its stand point from further
 *      off, the avatar with the key held): upper bound +3 cm as above; the lower bound is
 *      NOT −2 cm. A crossfade between two stances blends the leg joints'
 *      rotations, and a blended leg reaches further down than the average of
 *      the two (the vertical reach goes with the cosine of the joint angles,
 *      which is concave): every plain idle → walk crossfade on flat ground,
 *      no bridge and no lift involved, dips the lowest foot under the root
 *      plane — measured in this run per rig as the reference (INFO; at the
 *      time of writing Test3_mia −3.67, Soldier −2.45, reference −3.38 cm).
 *      The hand-over into walk may dip no deeper than that plain crossfade
 *      minus the [V2] tolerance, 1.5 cm — DERIVED, not measured: the blended
 *      foot height is the weighted mix of the two poses' foot heights plus
 *      the blend's own concave term. The plain crossfade starts from idle's
 *      feet; the hand-over starts from the bridge's last frame, whose feet
 *      [V2] puts within ±1.5 cm of the floor. The concave term is the same
 *      kind of dip, so the hand-over's mix differs from the control's by at
 *      most the weight × that start offset, i.e. at most 1.5 cm. Before: the
 *      feet rose from −32 to +2.6 cm in eight frames (NPC) — the hop.
 * [V4] avatar, no input after the bridge: 1 s after its end the root stands
 *      on the floor plane (±1 cm; it was put there at the bridge start and
 *      nothing lifts it — before: 45.5 / 59.5 cm) and the lowest idle foot is
 *      within ±2 cm of it (the idle lift above; before +47 / +61 cm).
 * [V5] get-up-chair, seat 0.45, NPC and avatar without input: last bridge
 *      frame lowest foot − floor within ±1.5 cm (same construction as [V2]);
 *      and no frame of the bridge moves the drawn root (owner y + lift) by
 *      more than the smoothstep's steepest frame (+0.1 mm): the drawn root is
 *      continuous at the bridge start (root + startLift = the old root) and
 *      then follows start + Δ·s(x), Δ = endLift − startLift, x over the ramp
 *      of length D = liftRamp(fc).to − liftRamp(fc).from. s'(x) = 6x(1 − x)
 *      peaks at 1.5, so no frame of dt = 1/30 s moves it more than
 *      1.5 · |Δ| / D · dt (mean value theorem). For a chair whose feet stand
 *      from the first frame D = 0.25 s (the fade-in floor): Soldier |Δ| =
 *      4.22 + 0.34 = 4.56 cm → 1.5·4.56/0.25/30 = 0.912 cm (before this
 *      floor: the whole 4.56 cm in one frame). The same bound is checked on
 *      every bed run ([V5b], D = 0.6 s).
 * [V6] THE FLOOR ARRIVES LATE (C0 § 6), NPC, bed 0.46, three rigs: the bridge
 *      opens while the goal is still the SEAT (the poll carried the standing
 *      clip but still the seat's point), so it opens with startLift 0; 0.5 s
 *      later the server's stand point arrives at the floor. The owner puts the
 *      root on it and hands the difference over (`shiftBridgeLift`); 0.5 s is
 *      before every rig's ramp (firstContactS − 0.6 >= 1.26 s, INFO; the
 *      first contact is read off the clip AFTER the leg pin since the final
 *      review — before that the earliest ramp was 1.4 s), so the
 *      carry is 0 and the run from there on is the normal one: [V2] holds
 *      (last bridge frame, lowest foot − floor within ±1.5 cm) and no frame
 *      moves the drawn root more than the [V5] bound of the normal bed run
 *      (the same Δ and D).
 * [P] A PAIR CLIP TAKES THE FIGURE MID-BRIDGE (final review, finding 1), NPC,
 *     bed 0.46, three rigs: PAIR_AT_S = 0.8 s into get-up-bed the server hands
 *     the NPC the interaction `greeting-handshake`, role a (anchor on the ground, no
 *     place → `tickInteraction` puts the root on the anchor's floor, y = 0).
 *     `playPair` fades the bridge out over 0.25 s; three.js then disables the
 *     action (weight 0), so its time stands still and "finished" never comes.
 *     BEFORE: `playPair` left the bridge as the transition, so `bridging`,
 *     `holdsHeight` and the frozen lift stayed until the wall-clock deadline
 *     (clip length 4.067 + 0.5 s after the start): the clip time froze once
 *     the fade was over, at 0.8 + 8 frames = 1.067 s, before every rig's ramp
 *     (>= 1.26 s, [V6]), so the lift stayed startLift = S − 0.001·H − 0.01 =
 *     0.46 − 0.0017 − 0.01 = 0.4483 m (reference: 0.46 − 0.0020 − 0.01 =
 *     0.4480 m) and the handshaking figure floated 44.8 cm over the anchor.
 *     NOW `playPair` releases the bridge before the takeover (`releaseBridge`,
 *     the one end of every bridge):
 *     [P1] on the takeover frame `bridging`, `holdsHeight`, `holdsFacing` are
 *          false and `paceLimit` is 1 (before: bridging true, holdsHeight
 *          true, pace 0). INFO: the lift on that frame is already startLift ×
 *          the bridge's weight after one frame of the fade, (1 − (1/30)/0.25)
 *          = 0.8667 → 0.4483 · 0.8667 = 38.85 cm (reference 38.83 cm).
 *     [P2] PAIR_CHECK_S = 0.3 s after the takeover (the 0.25 s fade is over,
 *          weight 0): the lift is exactly 0, so the body is the pair clip's
 *          pose on the anchor's floor and nothing else — its lowest foot
 *          equals that of a CONTROL figure that stood (idle, no bridge) and
 *          got the same interaction, at the same phase, within 1 mm. The
 *          brief asked for "feet within ±2 cm of the anchor floor"; that
 *          absolute bound does not hold for the clip itself — the control's
 *          lowest foot at phase 0.3 s may sit over its root (INFO; the CMU
 *          handshake stepped in, 4.30 / 4.69 / 3.80 cm) — so the floor is measured THROUGH
 *          the control, which stands on it. Before (figures.ts of 819f1571): 49.13 / 49.52 / 48.60 cm
 *          (= control + 44.8 cm).
 *     [P4] the interaction ends PAIR_END_S = 0.5 s after the takeover (well
 *          before the old deadline): two frames later the figure plays what
 *          `tick` asks for (walk to its stand point, then idle), not the pair
 *          half — `play` is not blocked. Before: the pair half on every frame.
 * INFO: per rig the measured endLift (world cm) and firstContactS.
 */
```
