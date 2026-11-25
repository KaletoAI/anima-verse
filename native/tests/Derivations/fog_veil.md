# fog_veil

- Origin: `client3d/scripts/smoke_fog_veil.mjs` @ 011cd048aa3cc2937186d7f35d2203af9491db8a
- Executed by: `native/tests/FogVeilVectorTests.cs`
- Vectors: `shared/test-vectors/fog_veil.json`

## Derivation

```text
/**
 * Smoke check for the EXPLORATION VEIL — the haze over ground the avatar has
 * never walked (`plan-fog-schleier-v2.md`, § A12).
 *
 * Usage:  node client3d/scripts/smoke_fog_veil.mjs
 *         (transpiles `scene/fogVeilMath.ts`; bundles `scene/fogVeil.ts`,
 *          needs three)
 *
 * Same discipline as `smoke_natural_ground.mjs` and `smoke_scene_recipe.py`:
 * EVERY expected number below is derived BY HAND in this header, from the
 * definition, and never recorded from an implementation run (§ B5a — numbers,
 * never screenshots). A check that only pins today's output proves nothing.
 *
 * ============================================================================
 * THE SUBJECT
 * ============================================================================
 * `scene/fogVeilMath.ts` is the arithmetic: which 64 m cell a metre lies in,
 * where that cell lands in the data texture, how soft its edge is and how much
 * haze a camera height is worth. `scene/fogVeil.ts` is how those numbers reach
 * the GPU: one data texture, seven uniforms, one shader patch on the ground
 * material.
 *
 * Four things can break silently, and all four are checked here without a GPU:
 *  - the RASTER drifting away from the server's. The cells arrive as `"cx,cz"`
 *    keys out of `GET /play/explored` and are the server's own
 *    `EXPLORED_CELL_M` = 64 m, anchored at the world origin. A client that
 *    rounded instead of flooring would veil the wrong half of the world across
 *    the origin — section [1] is the twin of `app/core/exploration.cell_of`.
 *  - the TEXEL MAPPING slipping by half a cell. Texel centres have to sit on
 *    CELL centres, or the soft edge lands inside a cell instead of on its
 *    boundary (sections [4]/[5]).
 *  - the patch ASSIGNING instead of chaining `onBeforeCompile` — the mistake
 *    this repo learned the hard way with the water shader; the mutant of [9d]
 *    measures it.
 *  - the HEIGHT RAMP losing an end: a veil that never quite reaches 0 fogs the
 *    embodied mode (section [6] pins both ends exactly, not "almost").
 *
 * ============================================================================
 * [1] fogCellOf — floor division, the server's twin
 * ============================================================================
 * `cx = floor(x / 64)`; cell (cx, cz) covers [cx·64, (cx+1)·64).
 *      0     -> 0            (the cell starts at its own left edge)
 *     63.999 -> 0
 *     64     -> 1
 *    100     -> 1            (100/64 = 1.5625)
 *    900     -> 14           (900/64 = 14.0625 — the cell of the smoke world
 *                             `scripts/smoke_fog_worldmap.py` [8] measures in)
 *    950     -> 14           (950/64 = 14.84375)
 *     -1     -> -1           (-0.015625 floors to -1, NOT to 0: that is what
 *                             makes the raster continuous across the origin
 *                             instead of doubling the width of the cell that
 *                             straddles it)
 *    -64     -> -1
 *    -65     -> -2           (-1.015625)
 *
 * ============================================================================
 * [2] fogParseCell — two integers, or nothing
 * ============================================================================
 *   "0,0"     -> [0, 0]
 *   "-1,2"    -> [-1, 2]
 *   "14,1"    -> [14, 1]
 *   "3.5,1"   -> null      (Number() would take it and veil a place between
 *                           two cells)
 *   "+3,1"    -> null
 *   " 3,1"    -> null      (whole-string match, no trimming: the server never
 *                           writes a space, so a space is a payload this
 *                           client does not understand)
 *   "3,1,2"   -> null
 *   "3"       -> null
 *   "a,b"     -> null
 *   ""        -> null
 *
 * ============================================================================
 * [3] fogGrid — the bounding box, grown by ONE cell on every side
 * ============================================================================
 * The ring of zeros is what the clamp-to-edge sampler needs: without it an
 * explored cell at the border of the box would smear its 1 over everything
 * outside the box.
 *   ["0,0"]           -> cx0 -1, cz0 -1, cols 3, rows 3
 *                        (1 cell + 1 on each side = 3, both axes)
 *   ["0,0", "2,1"]    -> x: 0…2 = 3 cells + 2 = 5, cx0 = -1
 *                        z: 0…1 = 2 cells + 2 = 4, cz0 = -1
 *   ["-3,-3"]         -> cx0 -4, cz0 -4, cols 3, rows 3
 *   ["0,0", "nope"]   -> as ["0,0"]: an unreadable key is SKIPPED, never
 *                        guessed at — one NaN would stretch the grid over the
 *                        whole world
 *   []                -> null   (no box; the caller answers with the neutral
 *                                one-texel texture, i.e. a world nobody has
 *                                walked)
 *   ["nope"]          -> null
 *
 * ============================================================================
 * [4] fogTexUv — texel CENTRES sit on CELL CENTRES
 * ============================================================================
 * Grid of ["0,0"]: cx0 = cz0 = -1, cols = rows = 3. Texel i covers
 * [i/3, (i+1)/3] and its centre is (i+0.5)/3.
 *   world (32, 32)   = centre of cell (0,0)   -> u = (0.5+1)/3 = 0.5
 *                                                 = centre of texel 1 ✓
 *   world (-32, -32) = centre of cell (-1,-1) -> u = (-0.5+1)/3 = 1/6
 *                                                 = centre of texel 0 ✓
 *   world (96, 96)   = centre of cell (1,1)   -> u = (1.5+1)/3 = 5/6
 *                                                 = centre of texel 2 ✓
 *   world (0, 0)     = CORNER of cell (0,0)   -> u = 1/3 = the left EDGE of
 *                                                 texel 1
 * There is no half-texel term anywhere in the mapping: the half texel is
 * already the cell's own half.
 *
 * ============================================================================
 * [5] THE SOFT EDGE IS THE LINEAR FILTER — 32 m, half a cell
 * ============================================================================
 * Sampled bilinearly, the value between the centre of an explored cell (1) and
 * the centre of its unexplored neighbour (0) falls linearly over the 64 m
 * between them. Hand-derived along z = 32 (the row of centres) on the grid of
 * ["0,0"], whose only 1 is texel (1,1):
 *
 *     x =   0 m (boundary cell −1|0)  -> 0.5
 *     x =  16 m                       -> 0.75
 *     x =  32 m (cell 0 centre)       -> 1
 *     x =  48 m                       -> 0.75
 *     x =  64 m (boundary cell 0|1)   -> 0.5
 *     x =  80 m                       -> 0.25
 *     x =  96 m (cell 1 centre)       -> 0
 *     x = 128 m (cell 2 centre)       -> 0
 *
 * Read the ramp as the veil sees it: the haze is (1 − value), so it is half
 * strength exactly ON the cell boundary and reaches full strength one cell
 * centre later — i.e. it blends over FOG_BLEND_M = 32 m into each of the two
 * cells. No blur pass, no second texture, no geometry.
 *
 * The sampler used here is a REIMPLEMENTATION of GL_LINEAR + CLAMP_TO_EDGE
 * (texel coordinate `u·cols − 0.5`, mix by the fraction), not a call into the
 * module: the point is that the module's UV mapping lands where a GPU would
 * read it, and asking the module both questions would prove nothing.
 *
 * ============================================================================
 * [6] fogHeightAlpha — the ramp, both ends EXACT
 * ============================================================================
 * smoothstep between FOG_CLEAR_H_M = 20 and FOG_FULL_H_M = 45 (span 25):
 * `t = clamp((h−20)/25, 0, 1)`, `s = t²(3−2t)`.
 *     h =  0    -> t = 0     -> 0            (below the clear height: EXACTLY
 *     h = 20    -> t = 0     -> 0             0, so an embodied player pays
 *                                             nothing at all)
 *     h = 26.25 -> t = 0.25  -> 0.15625      (0.0625·2.5)
 *     h = 32.5  -> t = 0.5   -> 0.5          (0.25·2)
 *     h = 38.75 -> t = 0.75  -> 0.84375      (0.5625·1.5)
 *     h = 45    -> t = 1     -> 1
 *     h = 200   -> t = 1     -> 1
 * and it is monotone in between (checked over 0…60 in 0.25 m steps).
 *
 * WHERE THE TWO ENDS COME FROM — the engine's own zoom tiers, so the veil has
 * no scale of its own. `Engine.update` puts the camera at
 * `dist · sin(pitch)` above its target, with
 * `pitch = lerp(18°, 62°, sqrt((dist − 0.8) / 149.2))`:
 *
 *   dist 34 m = EMBODY_MAX_DIST, the embodied zoom wall
 *     zoomK = 33.2/149.2 = 0.22252, sqrt = 0.47172,
 *     pitch = 18 + 44·0.47172 = 38.756°, sin = 0.62607
 *     -> height 21.29 m.  FOG_CLEAR_H_M = 20 <= 21.29, so everything the
 *        embodied mode can reach is veil-free.
 *   dist 60 m = CLOSE_CAM_DIST, where the open detail view closes
 *     zoomK = 59.2/149.2 = 0.39678, sqrt = 0.62991,
 *     pitch = 18 + 44·0.62991 = 45.716°, sin = 0.71606
 *     -> height 42.96 m.  FOG_FULL_H_M = 45 >= 42.96, so full haze is an
 *        overview state and nothing else.
 *
 * ============================================================================
 * [7] fogVeilAlpha — the product, and what it clamps
 * ============================================================================
 * `FOG_ALPHA_MAX · (1 − explored) · fogHeightAlpha(h)`, with FOG_ALPHA_MAX
 * = 0.72 ("haze, not black" — at 0.72 the land keeps its silhouette).
 *     (h 32.5, e 0)   -> 0.72 · 1   · 0.5 = 0.36
 *     (h 32.5, e 0.5) -> 0.72 · 0.5 · 0.5 = 0.18
 *     (h 32.5, e 1)   -> 0
 *     (h 45,   e 0)   -> 0.72
 *     (h 45,   e 0.5) -> 0.36
 *     (h 10,   e 0)   -> 0            (below the clear height, whatever the
 *                                      ground remembers)
 *     (h 45,   e 2)   -> 0            (a value above 1 is clamped, not
 *                                      subtracted)
 *     (h 45,   e −1)  -> 0.72         (…and below 0 likewise)
 *
 * ============================================================================
 * [8] THE CELLS TEXTURE — what `setFogVeilCells` really uploads
 * ============================================================================
 * `setFogVeilCells(["0,0"])` on the grid of [3]: a 3×3 byte grid, and the ONLY
 * 255 is the texel of cell (0,0) at index `j·cols + i` = `1·3 + 1` = 4:
 *     [0, 0, 0,
 *      0, 255, 0,
 *      0, 0, 0]
 * The geometry uniform says where it lies: (cx0, cz0, cols, rows) =
 * (−1, −1, 3, 3). An empty set uploads the shared NEUTRAL texel (one zero,
 * geometry (0,0,1,1)) — with clamp-to-edge the whole world then samples that
 * zero, which is exactly "nobody has walked anywhere yet".
 *
 * ============================================================================
 * [9] THE PATCH — uniforms, chain, key, anchors, neutrality
 * ============================================================================
 * (a) all seven uniforms bound, the varying declared once, the body inserted
 *     BEFORE `#include <opaque_fragment>` (the anchor the water's sky fresnel
 *     uses: the LIT colour, after every albedo stage);
 * (b) the cache key composes — `ground-hole+fog-veil`, and `fog-veil` alone on
 *     a material without a key of its own;
 * (c) a three version WITHOUT the anchors leaves the shader untouched as a
 *     WHOLE (matte beats broken: a fragment side alone would read a varying
 *     nobody wrote);
 * (d) RED: a mutant that ASSIGNS `onBeforeCompile` instead of chaining loses
 *     the predecessor's uniform. Without this the whole section would pass on
 *     a patch that silently deletes the basement hole;
 * (e) the crossfade: after a new set `uFogMix` is 0, `tickFogVeil(0.3)` with
 *     FOG_FADE_S = 0.6 puts it at 0.5, a second one at 1 — and only THEN do
 *     both samplers point at the same texture (the old one has to stay alive
 *     while it is still being shown);
 * (f) neutrality: below the clear height, with the veil switched off
 *     (isolation toggle 20) or in the admin's unfiltered view, `uFogAlpha` is
 *     EXACTLY 0 and the shader reads no texture at all.
 *
 * ============================================================================
 * [10] THE WIRING — the veil is on the open world's ground
 * ============================================================================
 * A string check on `scene/ground.ts`: `applyFogVeil` is imported and applied
 * at THE ground material site — the CDLOD terrain's own material, which since
 * Wasser v2 K-A E5 is the only one this file builds (the water mirror was the
 * second, and the water is the terrain itself now). It is the very list
 * `applyNaturalGround` is on. Props, scatter and location tiles are
 * deliberately NOT on it (plan § 4).
 *
 * THE WATER-CLASS EXCEPTION WENT WITH THE MIRROR. It existed because a painted
 * lake got a rippled material of its own here and the veil would have fought
 * that shader for the `opaque_fragment` anchor; the terrain's one material is
 * never a water material, so the check below is that no such branch is left.
 *
 * [20] Shared texture and constant cases: cell0 in a3x3 padded
 * grid starts at cx0=cz0=-1. World32 is its centre: texel coordinate
 * (32/64-(-1))/3=1.5/3=.5 on both axes. Index(0,0) is1*3+1=4.
 * Constants pin the server64 m cell, one padding cell,32 m half-cell
 * blend,20/45 m height ends,.72 maximum alpha,.6 s fade and2048 cap
 * (the contracts derived in sections1/3/5/6/7 and the header above).
 */
```

## Inline derivations

Comment blocks of `client3d/scripts/smoke_fog_veil.mjs` after its opening docstring that contain a mark a case label
cites, in file order; line numbers refer to the smoke at a56065e6f003.

Line 382 (cites [1]):

```text
// ── [1] fogCellOf ───────────────────────────────────────────────────────────
```

Line 396 (cites [2]):

```text
// ── [2] fogParseCell ────────────────────────────────────────────────────────
```

Line 410 (cites [3]):

```text
// ── [3] fogGrid ─────────────────────────────────────────────────────────────
```

Line 464 (cites [6]):

```text
// ── [6] fogHeightAlpha ──────────────────────────────────────────────────────
```

Line 487 (cites [6]):

```text
  // The two ends against the engine's own zoom tiers — see the header of [6].
```

Line 499 (cites [7]):

```text
// ── [7] fogVeilAlpha ────────────────────────────────────────────────────────
```
