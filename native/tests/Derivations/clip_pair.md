# clip_pair

- Origin: the browser scene's deleted `smoke_clip_pair.mjs` @ 011cd048aa3cc2937186d7f35d2203af9491db8a
- Executed by: `native/tests/PairVectorTests.cs`
- Vectors: `shared/test-vectors/pair_clip_geometry.json`

## Derivation

```text
/**
 * Smoke check for PAIR CLIPS at the consumer (§ B5a: numbers, no screenshots):
 * the two halves of a converted pair clip loaded with three's own
 * FBXLoader, the root path the client extracts from them, and the anchor
 * transformation the server and the client agree on (§ A8a).
 *
 * Usage:  node smoke_clip_pair.mjs   (historical; the runner was deleted with the browser scene in E3)
 *         (needs three, esbuild and the converted clips in shared/models/clips:
 *          greeting-handshake__a.fbx / __b.fbx / greeting-handshake.json — the
 *          animation studio's handshake, anims/greeting-handshake.py)
 *
 * Hand-derived expectations
 * -------------------------
 * The converter (`app/blender/scripts/cmu_clip.py`, `run_takes`) writes both
 * halves in ONE frame: origin at the XZ midpoint of the two roots at the
 * anchor frame, +X pointing from A to B. The sidecar states that frame's
 * numbers. The studio handshake stands still: hips 0.72 m apart along their
 * facing with a stagger of −0.14 m (each 7 cm to its own left), so the roots
 * are hypot(0.72, 0.14) = 0.7335 m apart — `root_distance_m` 0.734 at
 * `anchor_s` 1.5, A at (−d/2, 0) and B at (+d/2, 0) (3 decimals). So:
 *
 *   [1] naming/role: `parse` of the two file names yields the halves, the
 *       client indexes them as `greeting-handshake__a` / `__b`
 *       (`isPairClipName` true; `idle` false; a group continues the role
 *       letters, so `x__c` is a role file too, while `x__f` — no role letter
 *       a..e — is not; an ALT half of a role, `x__b~wave` / `x__c~arm-down`
 *       (G6), is a role file, while `x__b~` (no name), `x~wave` (no role)
 *       and `x__f~wave` are not).
 *
 *   [2] the root path of each half, read from the raw hips position track in
 *       Mixamo centimetres → metres: at `anchor_s` A sits at x = −d/2 = −0.367 and
 *       B at x = +d/2 (±0.02 m — the sidecar rounds, and the client
 *       interpolates between 30 fps keys), both at z = 0 (±0.02); the two
 *       roots `root_distance_m` = 0.734 = hypot(0.72, 0.14) apart (±0.03).
 *       The studio clip has no walk-up: at t = 0 the roots are already
 *       where they are at the anchor (±0.02), the sidecar's start positions.
 *
 *   [3] the anchor transformation, the SAME formula on both sides
 *       (`interaction_engine._rotate` ↔ `npcs.tickInteraction`):
 *       x' = ax + x·cos(yaw) + z·sin(yaw), z' = az − x·sin(yaw) + z·cos(yaw).
 *       With the server's yaw for a partner standing in +Z of the actor
 *       (yaw = −π/2, see `scripts/smoke_interaction.py` [2]) and the anchor
 *       at (10, 22), A's root at the anchor moment lands at (10, 22 − d/2)
 *       and B's at (10, 22 + d/2): A stands south, B north, d = `root_distance_m` apart,
 *       the line between them along +Z exactly as the server placed them.
 *
 *   [4] `rootPathAt` clamps: before the first key it answers the first key,
 *       after the last the last, and between two keys it interpolates
 *       linearly (hand case: keys at t = 0 → x 0 and t = 1 → x 2 give x = 1
 *       at t = 0.5); z 0 -> 4 gives z = 2 at the same midpoint.
 *
 * Shared synthetic cases (same production functions, no files):
 * [2] Hips keys (-36.7,100,0), (36.7,120,40) cm at 0,1 s
 *     give XZ (-0.367,0),(0.367,0.4) m by /100; Y is ignored.
 *     First matching hips position wins; Spine alone gives the default
 *     time [0], XZ [0,0]. Unprefixed hIpS keys (100,200,-300),
 *     (200,400,-100) at 0,2 give XZ (1,-3),(2,-1).
 * [3] d/2 = 0.734/2 = 0.367; yaw -pi/2 has c=0,s=-1:
 *     A (-0.367,0) -> (10,21.633), B (0.367,0) -> (10,22.367).
 *     Unit +X at origin -> (0,1). Yaw 0: root (2,3), anchor
 *     (10,22) -> (12,25). Yaw +pi/2: c=0,s=1 -> (13,20).
 *
 *   [5] the time base: the clip's duration equals the sidecar's
 *       `duration_s` (±1 frame = 0.034 s) — the server sends that number as
 *       `clip_duration_s`, the client wraps or clamps the phase with it
 *       (the interaction itself has no clock end, § A8a).
 *
 *   [6] TRACK SHAPE — the Mixamo library's: rotation tracks plus ONE
 *       position track (the hips), no scale tracks. Checked on the converted
 *       pair halves and `dance`. And the consequence, measured the way the ADMIN
 *       PREVIEW applies a clip (every track but the hips position, straight
 *       onto a metre-scaled GLB, `Model3DViewer.tsx`): on `Test3_mia.glb`
 *       the posed skeleton's body length (longest extent of the joint cloud
 *       — the admin pivot may turn it onto any axis) stays within 0.7 … 1.3
 *       of its bind length and the diagonal under 2.6 m; the library's own
 *       `idle.fbx` is run first as the reference of the harness. The
 *       2026-08-21 finding was the opposite — per-bone translation/scale
 *       tracks in centimetres left "a stick figure of the mesh" (measured on
 *       the character model of the finding: 151 m joint extent against 1.4 m
 *       with the fixed export); the RED counter-probe below re-creates it by
 *       adding one such track (100x the bone's rest offset) and watches the
 *       body length run away (> 2×).
 */
```
