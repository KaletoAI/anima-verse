# impostors

- Origin: the browser scene's deleted `smoke_impostors.mjs` @ 011cd048aa3cc2937186d7f35d2203af9491db8a
- Executed by: `native/tests/ImpostorVectorTests.cs`
- Vectors: `shared/test-vectors/impostors.json`

## Derivation

```text
/**
 * REGRESSION: Existing impostor math and render wiring retain their original baselines.
 * Smoke check for the FAR IMPOSTORS of the ground scatter — the render stage
 * that draws a wood beyond the cull line as billboards
 * (the browser scene's `scatterLod.ts`, the `IMPOSTOR_*` half; the GPU side is
 * the browser scene's `impostors.ts`).
 *
 * Usage:  node the browser scene's deleted smoke_impostors.mjs
 *
 * Same discipline as `smoke_scatter_math.mjs` and `smoke_occlusion.mjs`: every
 * expected number below is derived BY HAND in this header and never recorded
 * from the current output. `scatterLod.ts` has no import (see its header), so a
 * plain esbuild transpile is enough — no bundler, no three.
 *
 * SHARED VECTORS: impostors.json, including scatter_math's W seam.
 * [W1] the line starts at 0.25 just beyond either cull 120 or cull 60.
 * [W2] k=clamp(ceil(cull/64),1,32): culls 120/60/300/5/2000 yield
 * k=2/1/5/1/32. Reach=min(sqrt(2)*(k+1)*64,400), hence
 * 271.5290039756343 / 181.01933598375618 / 400 for culls 120/60/300.
 * [W3] at d=190 the share is 0.25*(1-70/(sqrt(2)*192-120)*0.75)
 * =0.163383 rounded to six decimals (eps 1e-6). Past the corner the share
 * stays 0.0625; at 401 the window is closed and the share is 0.
 * Cases use raw doubles with tolerances; mutant, wiring and relation checks
 * remain inline. No frame, quad or corner is recorded from the implementation.
 *
 * WHAT IS NOT CHECKED HERE, and it is a stated limit rather than an oversight:
 * the offscreen BAKE itself. It needs a GPU and a WebGL context; what a texture
 * looks like is a matter for the visual acceptance. What CAN be checked without
 * one is everything that decides geometry — the window, the thinning, the yaw
 * and the quad — and all of it lives in the import-free module for exactly that
 * reason. The wiring that connects the two is pinned against the source text in
 * section (F), the way `smoke_occlusion.mjs` pins its callers.
 *
 * ============================================================================
 * (A) THE WINDOW — where the meshes stop, the billboards start
 * ============================================================================
 * The mesh LOD hides an instance beyond `cullM` (120 m by default); the stage
 * runs from there to `IMPOSTOR_FAR_M` = 400 m. The window is OPEN at the near
 * end and CLOSED at the far one, which is exactly the complement of what
 * `instanceTier` draws — one line, two representations, never both:
 *
 *   119.9 m -> no billboard (the mesh has it)
 *   120.0 m -> no billboard (`instanceTier` hides only ABOVE cullM)
 *   120.1 m -> billboard
 *   400.0 m -> billboard, the very edge
 *   400.1 m -> nothing at all
 *
 * (A5) A CULL DISTANCE PUSHED PAST THE STAGE. The menu lets a player set the
 * cull out to 2000 m (`game/prefs.ts`). With cullM = 500 the window is
 * `(500, 400]` — empty, and it must come out empty rather than inverted: the
 * meshes then simply reach further than the stage that exists to replace them.
 *
 * ============================================================================
 * (B) THE THINNING — it CONTINUES the mesh line (2026-08-24)
 * ============================================================================
 * The stage starts at the share the meshes ended on, `SCATTER_MIN_SHARE` =
 * 0.25, and falls to `IMPOSTOR_TAIL_FACTOR` (a quarter) OF THAT over the reach
 * the sampled cell window really has (`impostorReachM`) — not over the 400 m
 * of `IMPOSTOR_FAR_M`, which no window ever fills:
 *
 *   cull 120 -> k = ceil(120/64) = 2 cells to each side
 *            -> the window's corner is √2 · (k+1) · 64 = 271.5290039756343 m
 *   share(d) = 0.25 · (1 − min((d − 120) / 151.5290039756343, 1) · 0.75)
 *
 *   120 m and nearer:  0 — outside the window there is no share at all
 *   120⁺ m:            0.25    — the mesh line's own last value, no step
 *   195.76450198781714 m:     0.15625 (the midpoint of the span, t = 0.5)
 *   271.5290039756343 m:     0.0625  (the corner, t = 1)
 *   400 m:             0.0625  — held at the floor past the corner
 *
 * The full derivation of the reach, the continuity of the two lines and the
 * red counter-check against the OLD rule (which restarted at 1) are section
 * (W) of `smoke_scatter_math.mjs`: they relate this line to `instanceShare`,
 * and that file has both halves of it.
 *
 * (B4) THE SETS NEST — and since the line stopped restarting they nest the
 * way a walk outward should. Both thinnings pick by `instanceHash(index)`, so
 * the billboards just outside the line are a SUBSET of the meshes just inside
 * it: at 119 m the mesh share is 1 − (74/75)·0.75 = 0.26, at 121 m the
 * billboard share is 0.25 · (1 − (1/151.5290039756343)·0.75) = 0.2487, and every
 * index under the smaller number is under the bigger one. Checked over 1000
 * indices: impostor-visible at 121 m implies mesh-visible at 119 m, without
 * exception. Crossing the line outward the wood now only ever gets THINNER —
 * the four-fold jump to a full share, and the ~1 % of instances that leave
 * along the way, are two different things: the first was a step, this is the
 * same continuous line the meshes were already on. Nothing moves either way.
 *
 * ============================================================================
 * (C) THE QUAD — a bake frame, and what it becomes in the world
 * ============================================================================
 * A prop model 4 m tall whose horizontal reach from its own origin is 1 m,
 * baked with the camera raised by 10° and 5 % of padding
 * (`IMPOSTOR_ELEV_RAD`, `IMPOSTOR_BAKE_PAD`):
 *
 *   halfW = 1.0 · 1.05                                  = 1.05
 *   halfH = ((4/2)·cos10° + 1.0·sin10°) · 1.05
 *         = (1.969615506… + 0.173648177…) · 1.05        = 2.250426867875914
 *   spanH = 2·halfH / 4                                 = 1.125213433937957
 *   aspect = halfW / halfH                              = 0.46657814790091456
 *
 * The depth term in `halfH` is not decoration: the image's up axis is
 * (0, cos e, −sin e), so a point at the box's rim contributes its DEPTH as
 * well, and without it the raised camera would cut the crown off.
 *
 * (C2) THE SAME PROP SCATTERED AT 8 m (the entry's `targetH` — the very number
 * the mesh is scaled to, which is what makes the swap a swap and not a jump in
 * size):
 *   h = 8 · 1.125213433937957 = 9.001707471503655
 *   w = h · 0.46657814790091456 = 4.2   — and 4.2 is derivable a second way,
 *       2·halfW · (8/4) = 2·1.05·2, which is the check that the two ratios
 *       really describe ONE frame.
 *   centreY = 8 · cos10° / 2 = 3.939231012048832
 *
 * (C3) THE FOOT IS ON THE GROUND. In the image the model's base sits
 * (height/2)·cos e below the image centre, so the quad centre has to stand
 * `targetH·cos e / 2` above the instance's ground point — which is exactly
 * `centreY`, i.e. the foot lands at y = 0 of the point the instance sits on.
 * The quad's BOTTOM EDGE lies below that, at 3.939231… − 4.500853… =
 * −0.5616227237029956: that is the transparent air the padding bought, and the
 * check that the padding is NOT what carries the foot.
 *
 * (C4) …and it must stay there when the padding changes. A frame with twice
 * the vertical span (a hypothetical fatter pad) gives twice the quad height
 * and the SAME `centreY` — the foot cannot move because somebody changed how
 * much air the bake keeps.
 *
 * (C5) A DEGENERATE MODEL (no height, no width, junk) gets NO frame: `null`,
 * and the caller then bakes nothing at all. A quad scaled by an infinity would
 * be a white flash across the map.
 *
 * ============================================================================
 * (D) THE BILLBOARD ITSELF — the four corners, by hand
 * ============================================================================
 * The quad of (C2) at the world origin, i.e. centre (0, 3.939231…, 0),
 * w = 4.2, h = 9.001707…
 *
 * (D1) CAMERA DUE +X, at (200, 60, 0). yaw = atan2(200−0, 0−0) = π/2, so the
 * quad's own +X axis (cos yaw, 0, −sin yaw)·(w/2) is (0, 0, −2.1): the quad
 * lies in the plane x = 0 and faces the camera. Corners, in the order
 * bottom-left, bottom-right, top-right, top-left:
 *   (0, −0.5616227237029956, +2.1)
 *   (0, −0.5616227237029956, −2.1)
 *   (0, +8.44008474780066,   −2.1)
 *   (0, +8.44008474780066,   +2.1)
 *
 * (D2) CAMERA ON THE DIAGONAL, at (100, 80, 100). yaw = atan2(100, 100) = π/4,
 * so w/2 · (cos45°, 0, −sin45°) = (1.48492424049175, 0, −1.48492424049175):
 * the corners move off the axes and the quad's own edge stands perpendicular
 * to the line of sight — checked as a dot product of 0 with the HORIZONTAL
 * camera direction.
 *
 * (D3) THE ONE PROPERTY THAT MUST NEVER BE LOST: it is a Y billboard. Every
 * corner keeps the y of its edge — the two bottom corners at −0.5616227…, the
 * two top ones at 8.4400847… — and those numbers do not move when the camera
 * climbs from y = 5 to y = 500. A tree stands upright whatever one looks at it
 * from.
 *
 * (D4) THE RED COUNTER-CHECK: A FULL BILLBOARD. Built here by hand, the way
 * one would if one "fixed" the quads to face the camera outright: view
 * direction v = normalize(cam − centre), right r = normalize(worldUp × v), up
 * u = v × r. With the camera at (200, 203.939231…, 0) — exactly 45° above the
 * quad's centre — u is (−cos45°, cos45°, 0), so
 *   the bottom edge rises to 3.939231… − 4.500853… · cos45° = 0.7566468143699092
 *   the top edge sinks to                                     7.121815209727755
 *   and the drawn height collapses from 9.0017… to 9.0017…·cos45° = 6.365168395357846
 * i.e. the tree hangs 0.76 m in the air and is a fifth shorter — the two
 * failures a Y billboard does not have, measured on the y component exactly as
 * the rule says to.
 *
 * ============================================================================
 * (E) THE RED COUNTER-CHECK OF THE WINDOW — one mutant, one double picture
 * ============================================================================
 * The module is transpiled a second time with the near end of the window
 * dropped (`distM > cfg.cullM` becomes `distM > 0`) — the mistake that would
 * draw a billboard AND a mesh for the same instance at 60 m, one inside the
 * other, and nobody would see anything wrong until the fill rate went. The
 * mutant says "billboard" at 60 m where the truth says nothing, and where
 * `instanceTier` is drawing a full mesh.
 *
 * ============================================================================
 * (G) WHAT A FAILED BAKE IS REMEMBERED AS
 * ============================================================================
 * The bake keeps a row of `null` for a prop it cannot bake, so the LOD tick
 * stops queueing the same hopeless job every second. That memory must be about
 * the MODEL and nothing else, and `impostorBakeVerdict` is where the four ways
 * an attempt can end are sorted:
 *
 *   baked       -> store    (there is a texture)
 *   unbakeable  -> refuse   (the file arrived, there is nothing to render)
 *   load-failed -> retry    (the file did not arrive — `leaseGlb` had already
 *                            tried three times, so this is a backend that went
 *                            away, not a broken prop)
 *   no-renderer -> retry    (the tick ran before `setImpostorRenderer`;
 *                            nothing was even attempted)
 *
 * (G2) THE RED COUNTER-CHECK is the bug this section exists for, and it is
 * exactly one character wide: a verdict that answers "refuse" to everything
 * that is not `baked` — the shape the code had — turns ONE dropped request into
 * a wood that stays bare for the whole session, and nothing on screen ever says
 * why. The mutant is transpiled and asked, and it refuses both transients.
 *
 * The bake itself is still un-smoke-able (it needs a GPU); what section (F)
 * pins instead is that this verdict is what the pass obeys — that a `retry`
 * leaves the cache untouched rather than writing a refusal into it.
 *
 * ============================================================================
 * (F) THE WIRING, pinned by reading the source
 * ============================================================================
 * None of this can be called from here — it lives inside closures over fetched
 * payloads and a WebGL context — so it is pinned against the source text:
 *  - `ground.ts` bins the far half BEFORE the entry-wide early-out, or a
 *    distant wood would be switched off whole before its billboards were ever
 *    considered;
 *  - it composes them from `prop.pos`, the array the meshes are binned from —
 *    that identity IS the promise that nothing jumps at the swap;
 *  - `impostors.ts` uses the app's renderer and creates none of its own;
 *  - a bake a billboard mesh is drawing with is CLAIMED, and the claim is
 *    given back with that mesh — the LRU may not free a texture out from under
 *    a live material, which would show a wood of black rectangles;
 *  - the impostor material is NOT patched with the camera corridor: the gate
 *    closes at 25 m and every billboard is beyond 120 m.
 */
```
