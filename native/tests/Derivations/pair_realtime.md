# pair_realtime

- Origin: `client3d/scripts/smoke_pair_realtime.mjs` @ 011cd048aa3cc2937186d7f35d2203af9491db8a
- Executed by: `native/tests/PairVectorTests.cs`
- Vectors: `shared/test-vectors/pair_clip_phase.json`

## Derivation

```text
/**
 * Smoke check for the PAIR-CLIP PHASE — `client3d/src/game/pairClip.ts`, the
 * one place that turns the server's clip clock (§ A8a) into the time the
 * mixer of `scene/figures.ts` `playPair()` is seeked to.
 *
 * Usage: timeout 300 node client3d/scripts/smoke_pair_realtime.mjs
 *        (needs three and esbuild; expectations live in pair_clip_phase.json.)
 *
 * Every number below is derived BY HAND in this docstring from the rule of
 * plan-animationen-echtzeit-stehplatz.md E1/T1 and the pair-scene tempo,
 * never recorded from the current output (§ B5a: numbers, not screenshots).
 * The tempo cases themselves live in smoke_pair_clip_tempo.mjs.
 *
 * THE RULE (E1 + tempo). Every animation runs in REAL time, whatever the
 * game-speed factor is, at the scene's tempo. The server keeps one clip clock
 * per scene and sends `clip_s` — CLIP seconds since the clip began, every
 * second already at the tempo it ran at — and `tempo` (clip seconds per real
 * second, 0.2..1). The client carries its own copy:
 *
 *     clipT = local + (frozen ? 0 : dt · tempo), then snapped to clip_s when a
 *             poll is more than PAIR_SNAP_S off (adopted when there is no local)
 *     phase = loop ? clipT mod clip_duration_s : min(clipT, clip_duration_s)
 *
 * The game-speed factor is no part of it (`rate` only says "frozen" at 0).
 *
 * ============================================================================
 * [1] ADOPTION TAKES clip_s AS IT IS
 * ============================================================================
 * Clip `handshake` as a CYCLE of 0.533 s, a poll with clip_s 3.0 and no local
 * clock: clipT = 3 — at tempo 1 and at tempo 0.5 alike (clip_s is already
 * clip seconds; nothing divides it). 3 s of a 0.533 s cycle is the sixth pass:
 *   5 x 0.533 = 2.665;  3 - 2.665 = 0.335  -> phase 0.335 s.
 *
 * ============================================================================
 * [2] A FROZEN WORLD does not advance the local clock
 * ============================================================================
 * Local clock 0.4, a frame of 0.1 s, frozen: clipT stays 0.4 -> phase 0.4.
 * Adopting a NEW interaction in a frozen world takes the server's clock (it
 * stopped there too): clip_s 1.2 -> clipT 1.2, phase 1.2 - 2 x 0.533 = 0.134.
 *
 * ============================================================================
 * [3] A ONE-SHOT CLIP HOLDS ITS LAST FRAME
 * ============================================================================
 * `handshake` as a one-shot of 2.533 s: clip_s 10 -> clipT 10, phase
 * min(10, 2.533) = 2.533 (clamped). Below the end nothing is clamped: 2.0 ->
 * 2.0; exactly at the end 2.533 -> 2.533. The same clock in a LOOPING clip of
 * that length wraps instead: 10 - 3 x 2.533 = 10 - 7.599 = 2.401.
 *
 * ============================================================================
 * [4] A POLL SNAPS ONLY A GENUINE DRIFT (PAIR_SNAP_S = 0.3 clip s)
 * ============================================================================
 * Between polls the client counts frames itself, so a poll that merely
 * confirms what the client already has must not re-seek the action — that is
 * what made the figure stutter once a second. Local clock 3.0 s, no frame:
 *
 *   clip_s 3.25 -> drift 0.25 <= 0.3 -> keep 3.0 -> phase 3.0 - 2.665 = 0.335
 *   clip_s 3.50 -> drift 0.50 >  0.3 -> take 3.5 -> 6 x 0.533 = 3.198;
 *                                        3.5 - 3.198 = 0.302
 *   clip_s 3.50, snapS 0.5 -> drift 0.5 is NOT more than 0.5 -> keep 3.0
 *                          (the threshold is "more than", tested on numbers
 *                           that are exact in binary so the boundary is real)
 *   frozen, clip_s 3.25 -> the same rule: keep 3.0
 *
 * Adoption — no local clock — always takes the server's value whatever the
 * drift: clip_s 49.5 -> 49.5.
 *
 * ============================================================================
 * [5] THE FRAME ADVANCE (how `scene/npcs.ts` composes it)
 * ============================================================================
 * Per frame the caller hands the REAL frame time as `dt` and no server value.
 * Three frames of 1/60 s on top of clipT 3.0:
 *   tempo 1:   3.0 + 3/60       = 3.05  -> phase 3.05  - 2.665 = 0.385
 *   tempo 0.5: 3.0 + 3/60 x 0.5 = 3.025 -> phase 3.025 - 2.665 = 0.36
 *   frozen:    3.0 (nothing added)      -> phase 0.335
 *
 * ============================================================================
 * [6] DEGENERATE INPUTS never produce NaN
 * ============================================================================
 * A clip length of 0 (a listing without `clip_duration_s`) has no cycle to
 * wrap in: the phase is the clock itself, clip_s 3 -> 3.0 (loop or not). A
 * negative local clock cannot happen but must not seek backwards either:
 * clamped to 0.
 *
 * WHAT THIS FILE DOES NOT COVER: `playPair` applies the same wrap/clamp once
 * more against the ACTION's own duration (the loaded clip may be a frame
 * longer than the sidecar says) and drives `action.timeScale = frozen ? 0 : 1`
 * plus the three.js loop mode. That needs a mixer and a rig; the numbers it
 * works with are the ones pinned here.
 */
```
