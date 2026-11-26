# rig_stand_ref

- Origin: the browser scene's deleted `smoke_rig_stand_ref.mjs` @ 011cd048aa3cc2937186d7f35d2203af9491db8a
- Executed by: `native/tests/ClipLibraryVectorTests.cs`
- Vectors: `shared/test-vectors/hips_tracks.json`

## Derivation

```text
/**
 * Smoke check for the STANDING REFERENCE of the clip library —
 * `standingHipsRef` / `rigHipsHeight` of `@anima/scene-render` and their
 * consumer the browser scene's `figures.adaptExternalClips` (§ B5a: numbers,
 * never screenshots).
 *
 * Usage:  node the browser scene's deleted smoke_rig_stand_ref.mjs
 *         (bundles the client modules itself; reads shared/models/rig/reference.fbx
 *          and the clips `idle` / `get-up-chair` in shared/models/clips — READ ONLY)
 *
 * ===========================================================================
 * WHY THIS FILE EXISTS
 * ===========================================================================
 * A clip's hips track is in the units of the rig it was retargeted onto: every
 * import drives its take onto `shared/models/rig/reference.fbx`. The client
 * rescales that track so a hips height equal to the STANDING reference lands
 * on the target rig's own rest hips. That reference used to be the idle
 * clip's hips median (110.179 units) — but the idle stance has slightly bent
 * knees, while the reference rig's REST hips (113.032) is the straight-legged
 * stance the take was measured against. Mapping 110.179 onto the rest lifted
 * every figure by 113.032 / 110.179 − 1 = 2.59 % of its hips height, ~2.85 cm
 * on the reference rig (hips 113.032 cm × 0.0259 = 2.93 cm of hips lift; the
 * feet follow with the legs' own bend, measured +2.87 cm). With the rig rest
 * as the reference the reference rig reproduces its raw take exactly.
 *
 * ---------------------------------------------------------------------------
 * Expected numbers, derived by hand
 * ---------------------------------------------------------------------------
 * [R1] standingHipsRef(113.032, 110.179) → {ref 113.032, source 'rig'}
 *      (a served rig with a finite, positive rest hips height wins).
 * [R2] standingHipsRef(undefined, 110.179) → {ref 110.179, source 'idle'};
 *      standingHipsRef(0, 110.179) and (NaN, 110.179) → 'idle' as well
 *      (0 and NaN are not a height).
 * [R3] standingHipsRef(undefined, null) → {ref null, source 'none'};
 *      clipHipsDrop(0.98013, 65.961, null) = 0 (no NaN).
 * [R4] clipHipsDrop(0.98013, 65.961, 113.032) = 0.98013·(1 − 65.961/113.032)
 *      65.961 / 113.032 = 0.58356 → 1 − 0.58356 = 0.41644
 *      = 0.98013 · 0.41644 = 0.40816 (±1e-5)
 * [R5] rigHipsHeight on shared/models/rig/reference.fbx = 113.032 (±0.01) —
 *      the number the analysis measured; a synthetic rig with hips at y=90 → 90;
 *      a rig without a hips bone → undefined.
 * [R6] REFERENCE RIG (instance scale 0.01, its centimetres → metres), idle
 *      clip through adaptExternalClips with the rig served (donorHipsY =
 *      113.032): lowest foot/toe bone over the bind floor (the lowest of the
 *      same bones in the bind pose), median over the clip, in cm:
 *      |value| ≤ 0.3 cm (raw take: +0.01 — the clip IS on this rig, the
 *      rescale factor is 113.032 / 113.032 = 1, nothing is lifted).
 *      Counter-probe in the same run with donorHipsY omitted (idle fallback):
 *      ≥ 2.5 cm (measured +2.87; hand: the hips rise 2.59 % of 113.032 cm =
 *      2.93 cm, the straightening legs keep the feet within a few mm of that).
 *      The fallback says so in ONE console.warn per session.
 * [R7] get-up-chair, last 0.5 s (the figure is standing again), reference
 *      rig, rig served: LEFT foot lowest bone (LeftFoot / LeftToeBase /
 *      LeftToe_End) over the bind floor, median over the window:
 *      |value| ≤ 0.5 cm (measured −0.18 with the rig reference).
 * [R8] hipsTrackMedian takes absolute y from hips position tracks only,
 * sorts ascending and chooses floor(n/2): y=[-3,1,2,4] -> [1,2,3,4]
 * -> 3 (upper middle, not average); no track -> null. Other properties and
 * other bones do not contribute. Multiple matching tracks share one sample list.
 * [R9] mapHipsTrack: ref=100, world hips=2 -> k=.02. Rest=[1,2,3].
 * y=100,50,-150 -> bounce=0,-1,1 -> local [1,2,3],[1,1,3],[1,3,3].
 * Raw xz=(10,20),(20,40),(0,10), relative to frame zero, times=0,1,2:
 * path=(0,0),(.2,.4),(-.2,-.2). A median of 200 exceeds 1.5*100,
 * so scaleFix=.5: y=200,100,-300 gives the same bounce, xz is halved.
 * At median=150 the strict threshold keeps scaleFix=1.
 * Without a served rig or without root motion, rootPath=null.
 * Parent inverse with linear diagonal (2,3,4), translation (7,8,9):
 * apply(0,-1,0)=(7,5,9), subtract translation -> (0,-3,0),
 * add rest -> (1,-1,3); zero bounce still maps to rest (1,2,3).
 * For parent inverse Rz(90), world (0,-1,0) becomes (1,0,0),
 * so adding rest gives (2,2,3), independent of its translation.
 */
```
