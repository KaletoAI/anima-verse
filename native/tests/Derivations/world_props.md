# world_props

- Origin: the browser scene's deleted `smoke_world_props.mjs` @ 011cd048aa3cc2937186d7f35d2203af9491db8a
- Executed by: `native/tests/WorldPropVectorTests.cs`
- Vectors: `shared/test-vectors/world_props.json`

## Derivation

```text
/**
 * REGRESSION: Existing LOD, placement and ghost arithmetic keep their original baselines.
 * Smoke: the AUTHORED props of the world plane (§ A9a) on the client side.
 *
 * Usage: direct node call, self-bundling via esbuild:
 *     node the browser scene's deleted smoke_world_props.mjs
 *
 * Three questions, all of them arithmetic, all expectations derived BY HAND
 * from the contract below (§ B5a — never recorded from a run):
 *
 * ── 1. The LOD distances ──────────────────────────────────────────────────
 * A world prop is a LANDMARK, not one of a thousand tufts, so it keeps its
 * meshes `WORLD_PROP_LOD_SCALE` = 3 times as far as the scatter. The scatter
 * defaults are 35 / 45 / 120 m (`scene/scatterLod.ts`), hence
 *
 *     near = 3·35  = 105 m
 *     far  = 3·45  = 135 m
 *     cull = 3·120 = 360 m
 *
 * and `instanceTier` (the SAME hysteresis function the scatter uses) then has
 * to answer, for a prop last drawn as full (tier 0):
 *
 *     100 m  <  105  -> 0 (full)
 *     120 m  in the 105…135 band, exclusive at both ends -> keeps 0
 *     140 m  >  135  -> 1 (low)
 *     400 m  >  360  -> 2 (not drawn)
 *
 * and coming back from hidden (tier 2), the un-hide edge is
 * `SCATTER_UNHIDE_FACTOR` = 0.92 of the cull distance = 0.92·360 = 331.2 m:
 *
 *     340 m  >  331.2 -> stays 2
 *     300 m  <  331.2 -> re-enters, and 300 > 135, so tier 1
 *
 * ── 2. The placement spec ─────────────────────────────────────────────────
 * `worldPropSceneSpec` turns ONE payload row plus a ground height into the
 * § B2 spec `place()` reads. The row states `x`/`z`/`offset_y`; the BOTTOM is
 * the caller's — the server never sends one. `worldPropBottom` is that sum,
 * and it has three summands with three owners (§ A9a, ground offset
 * 2026-08-20): the relief, THIS placement's `offset_y`, and the PROP's own
 * `ground_offset_m`. On a ground of 2.5 m with `offset_y` 0.5:
 *
 *     no ground_offset_m        -> 3.00
 *     ground_offset_m = -0.20   -> 2.80   (a trunk without a root ball)
 *     +0.35 and no placement trim -> 2.85
 *
 * An absent key is 0 — the server ships it only when it differs.
 *
 * E4 SHARED VECTORS: world_props.json contains sections 1/2/2a.
 * worldPropTier(d,prev,base) adapts only the composition
 * instanceTier(d,prev,worldPropLodCfg(base)); all base tables are explicit.
 * Finite bottom values compare at 1e-9 instead of pre-rounding. The variant
 * fixture carries variant 1 and its two maps unchanged into the scene spec.
 * Object-key absence, mount/ghost and lease lifecycle checks stay inline.
 * Vectors load before bundling so their path is rooted at shared/test-vectors.
 *
 * ── 3. The mount itself, measured ─────────────────────────────────────────
 * `placeModelSpec` is the shared routine; here it is fed a hand-built box so
 * the resulting world bounding box can be predicted exactly.
 *
 *   Source A: a 1 x 1 x 1 box centred on the origin, `max_m` = 3, `xyz`.
 *     measured extent = max(1,1,1) = 1  ->  scale = 3/1 = 3
 *     scaled box: 3 x 3 x 3, still centred on the origin
 *     anchor = [10, -4], ground 2.5 m, offset_y 0.5  ->  bottom_y = 3.0
 *     position.y = bottom_y - box.min.y = 3.0 - (-1.5) = 4.5
 *     world box: x 8.5…11.5,  y 3.0…6.0,  z -5.5…-2.5
 *
 *   Source B: a 2 x 1 x 1 box, `max_m` = 3, yaw 90°.
 *     measured extent = max(2,1,1) = 2  ->  scale = 3/2 = 1.5
 *     scaled box: 3 x 1.5 x 1.5 (long along local x)
 *     three.js Ry(+90°) maps  x = lz,  z = -lx  (§ A1.1, place.ts)
 *       -> the 3 m length lands on the Z axis, the 1.5 m on X
 *     world box size: x 1.5,  y 1.5,  z 3.0
 *
 *   Yaw is measured AFTER the fix but the scale is measured BEFORE it, which
 *   is exactly why a turned prop must not change size — checked as the last
 *   assertion.
 */
```
