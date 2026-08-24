#!/usr/bin/env node
/**
 * Smoke check for the CDLOD TERRAIN — `client3d/src/scene/terrainLod.ts`
 * (plan-ein-boden.md § G2, decision 5.3) and the analytic click march in
 * `packages/scene-render/src/worldHeight.ts`.
 *
 * Usage:  node client3d/scripts/smoke_terrain_lod.mjs
 *
 * Every number below is derived BY HAND in this docstring and never recorded
 * from the current output (§ B5a: numbers, not screenshots).
 *
 * WHY THIS FILE EXISTS. E2 replaced the one big drawn base plate with a
 * quadtree of instanced patches whose vertices fetch their height in the
 * VERTEX SHADER. Three things have to be true for that to be an improvement
 * rather than a third landscape:
 *
 *   1. what the GPU fetches has to be what `heightAt` answers — otherwise the
 *      figure stands on one surface and the server judges another (the very
 *      2.433 m the plate was measured at);
 *   2. the mip pyramid has to be the SAME height function on a coarser
 *      lattice, not a filtered picture of it — otherwise the server's exact
 *      `err[k]` bound stops bounding anything;
 *   3. the drawn surface has to be crack-free, which since 2026-08-21 means
 *      something stronger than "a node reaches morph 1 in time": the surface
 *      is a function of the WORLD POSITION alone, so two patches cannot
 *      disagree about a point they share whatever their levels are ([8]) —
 *      and since 2026-08-22 that has to hold for the vertices one side has and
 *      the other does not, which is what a T-junction is made of ([12]).
 *
 * ============================================================================
 * [1] THE CONSTANTS ARE DERIVED, not tasted
 * ============================================================================
 * `PATCH_N` = 32 cells, `MAX_LOD_LEVELS` = 6. At the server's fine step of
 * 2 m that makes the node grid steps 2, 4, 8, 16, 32, 64 m — the base lattice
 * plus EXACTLY the five levels `heightfield.MIP_LEVELS_M` declares an error
 * bound for. Leaf edge = 32 · 2 = 64 m, root edge = 64 · 2^5 = 2 048 m.
 * (a) the six steps                      -> [2, 4, 8, 16, 32, 64]
 * (b) levels 1..5 against MIP_LEVELS_M   -> [4, 8, 16, 32, 64], identical
 * (c) the patch has 33² = 1 089 vertices and 32² · 6 = 6 144 index entries.
 *
 * ============================================================================
 * [2] THE PYRAMID IS DECIMATION
 * ============================================================================
 * `buildPyramid(at, 0, 0, 2, 5, 5, 6)` — a 5 × 5 lattice at 2 m over [0, 8]².
 *   level 0: 5 × 5, step 2, rows 0…4
 *   level 1: floor(4/2)+1 = 3 × 3, step 4, rows 5…7
 *   level 2: floor(2/2)+1 = 2 × 2, step 8, rows 8…9
 *   level 3: floor(1/2)+1 = 1 < 2 -> the chain ends
 * so 3 levels, texture 5 wide and 5 + 3 + 2 = 10 tall, 50 texels.
 *
 * (d) THE DECIMATION IDENTITY, on an arbitrary field
 *     (h[j][i] = ((7i + 13j) mod 11) − 5): every support point of every coarse
 *     level reads exactly what level 0 reads at the same world point, because
 *     the coarse lattice is a SUBSET of the fine one. That is the whole
 *     licence for deriving mips on the client (§ G2).
 * (e) A LINEAR FIELD SURVIVES EVERY LEVEL: with h(x, z) = x/2 + z the coarse
 *     levels reproduce the plane between their points too, so (1, 1) reads
 *     1.5 and (7.5, 2.5) reads 6.25 on level 0, 1 AND 2.
 * (f) A SPIKE DOES NOT, and that is what `err` measures: 8 m on the support
 *     point (2, 2) — lattice index (1, 1), an ODD index — is gone from level 1
 *     entirely (its lattice takes indices 0, 2, 4), so level 0 reads 8 there
 *     and level 1 reads 0. The vertical error of drawing that tile one level
 *     up is those 8 m.
 *
 * ============================================================================
 * [3] THE GPU FORMULA IS THE CPU FORMULA
 * ============================================================================
 * The shader's `tlodGrid` is reimplemented HERE, from the arithmetic and not
 * from the string (a check that read the string could only prove the string
 * equals itself): clamp the grid fraction, `min(floor(f), n−2)` for the cell,
 * four `texelFetch`, the bilinear mix.
 *
 * THE FIXTURE HONOURS E1: one height function `H(x, z) = ((7x/2 + 13z/2)
 * mod 11) − 5` on the 2 m lattice, rastered TWICE — two loaded 16 m tiles
 * (9 × 9 points at 2 m, covering [0, 32] × [0, 16]) and a 4 m overview over
 * [−16, 48]². The two therefore carry the same number wherever they share a
 * support point, which since E1 is what the server guarantees (addendum § 1)
 * and what a fixture must not quietly break. The near pyramid is built by
 * sampling `heightAt` itself on the 2 m lattice of a window reaching 8 m past
 * the tiles.
 *
 * TWO tiles, not one, because the interesting seam is the INTERIOR one at
 * x = 16: both tiles carry that column, so `heightAt` is continuous across it
 * and the pyramid has to be too. The rim of the LOADED SET is a different
 * matter — there `heightAt` itself jumps, because a loaded tile answers alone
 * (§ A16.3); no renderer can smooth that, and in the client it sits at 560 m,
 * behind the haze.
 *
 * (g) INSIDE THE LOADED SET, across the interior seam, the pyramid's level 0
 *     and `heightAt` are the same bilinear over the same numbers: 1 769
 *     samples, all under the 1e-4 the contract asks for, and on this fixture
 *     exactly 0 — heights that are small halves survive `R32F` unchanged.
 *     What the 1e-4 is really for is measured beside it, on a field that is
 *     NOT a binary fraction: about 6e-6 m, the 24-bit mantissa at the scale a
 *     world is shaped in.
 * (h) IN THE MARGIN, past the loaded tiles, `heightAt` IS the overview — and
 *     the near pyramid, sampled from it on a lattice that subdivides the
 *     overview's own, reproduces it EXACTLY (bilinear interpolation
 *     reproduces a bilinear function on any sub-rectangle of its cell). That
 *     is why the shader may switch between the two pyramids on a rectangle
 *     instead of blending: where the switch happens, both answer the same
 *     number. The strip stops at z = −2, one cell short of the loaded set,
 *     which is what `NEAR_MARGIN_CELLS` = 2 buys in the real thing.
 * (i) RED COUNTER-PROBE: read the pyramid one level UP inside the tiles and
 *     the agreement is gone by more than a metre — the level-1 lattice drops
 *     every odd support point, and this field alternates on exactly that
 *     scale.
 *
 * ============================================================================
 * [4] THE LOD RANGES
 * ============================================================================
 * `lodRange[i] = max(minLodDistance · 2^i,
 *                    min(levelErrorM[i+1] · pixelScale / MAX_PIXEL_ERROR,
 *                        minLodDistance · 2^i · MAX_RANGE_WIDENING))`.
 *
 * THE CAP IS THE 2026-08-22 CHANGE: the error rule may push a level OUT BY ONE
 * STEP OF THE LADDER and no further. Uncapped it widened the live world's
 * innermost ring from 128 m to 1 538 m — the finest level over a 1.5 km disc,
 * 2 952 pieces of which 92 % stood behind the 520 m haze; [14] measures that
 * world and what the cap does to it.
 *
 * (j) WITHOUT an error list: 128 · 2^i -> [128, 256, 512, 1024, 2048, 4096].
 * (k) WITH the contract's own example errors (§ 4 of the E1 addendum:
 *     err = [0.5862, 0.85, 1.0, 1.1636, 3.3132] for levels 1…5) and a pixel
 *     scale of 2 000 px/m/m, the error term is err · 2000 / 2 = err · 1000 and
 *     the cap is twice the geometric ring:
 *       i=0: max(128,  min(586.2,  256))  = 256      <- held at the cap
 *       i=1: max(256,  min(850,    512))  = 512      <- held at the cap
 *       i=2: max(512,  min(1000,   1024)) = 1000
 *       i=3: max(1024, min(1163.6, 2048)) = 1163.6
 *       i=4: max(2048, min(3313.2, 4096)) = 3313.2
 *       i=5: max(4096, 0)                 = 4096   (no level 6 to bound)
 *     Every ring is still pushed OUT — the rugged world is drawn finer — but
 *     the two innermost, where the rule asked for 4.6× and 3.3× the geometric
 *     ring, get one doubling and stop there.
 * (l) THE MONOTONE GUARD IS NOW STRUCTURAL, which is a result and not a
 *     deletion. With the cap,
 *       g_i ≤ range[i] ≤ MAX_RANGE_WIDENING · g_i = g_(i+1) ≤ range[i+1],
 *     g_i = minLodDistance · 2^i: a ring can never start before the one inside
 *     it, whatever a hand-edited error list says. The fixture is the hostile
 *     shape — a huge error at level 1 beside a small one at level 2 — err =
 *     [0, 10, 3] at scale 200, i.e. an error term of err · 100:
 *       i=0: max(128, min(1000, 256)) = 256   <- held at the cap
 *       i=1: max(256, min(300,  512)) = 300   <- the rule really moves this one
 *       i=2: max(512, 0)              = 512
 *     RED: the SAME list without the cap is [1000, 300, 512] — level 1's ring
 *     starting 700 m inside level 0's, which is a coarse node selected in a
 *     fine ring and a cracked ground. That is the inversion the
 *     `if (r < out[i−1])` line had to repair after the fact and the cap now
 *     forbids outright; the line stays as the belt to that braces.
 * (m) A FLAT WORLD (minLodDistance 0) has no ranges at all — nothing splits,
 *     and the terrain is drawn from its roots.
 *
 * ============================================================================
 * [5] THE SELECTION
 * ============================================================================
 * Extent [0, 2048]², leaf 64 m, 6 levels, `minLodDistance` 128, flat bounds,
 * no frustum, no error term. THE CAMERA SITS ON THE WORLD CORNER (0, 0, 0),
 * so every distance is the box distance to a corner-anchored square and comes
 * out as a clean number.
 *
 * Ranges: [128, 256, 512, 1024, 2048, 4096].
 * The root (0, 0, 2048) is level 5 and d = 0 < ranges[4] = 2048 -> split. Each
 * split gives four children of half the size; the one AT THE CORNER always has
 * d = 0 and splits again, the two on the axes have d = size, and the diagonal
 * one has d = size·√2.
 *
 *   level 4 (size 1024): (0,0) splits · (1024,0) d=1024 · (0,1024) d=1024 ·
 *                        (1024,1024) d=1024√2
 *   level 3 (size  512): (0,0) splits · (512,0) d=512 · (0,512) d=512 ·
 *                        (512,512) d=512√2
 *   level 2 (size  256): (0,0) splits · (256,0) · (0,256) · (256,256)
 *   level 1 (size  128): (0,0) splits · (128,0) · (0,128) · (128,128)
 *   level 0 (size   64): (0,0) · (64,0) · (0,64) · (64,64) — all selected
 *
 * A node on the axis at level L has d = size = 64·2^L = ranges[L−1] exactly,
 * and `d < ranges[L−1]` is FALSE at equality, so it is selected rather than
 * split — the ring boundary belongs to the coarser level.
 *
 * (n) 4 + 3 + 3 + 3 + 3 = 16 nodes, and none at level 5. Every one of them
 *     draws the WHOLE patch (`cells` = 32): the out-of-range rule only emits a
 *     half-sized quadrant when a child has left its level's ring, and with the
 *     camera on the corner no child of a node that split has.
 * (o) THE MORPHS. A level-L node owns the ring [ranges[L−1], ranges[L]] =
 *     [size, 2·size] and its morph runs over the LAST HALF OF THAT RING,
 *     [1.5·size, 2·size] — Strugar's "last half", anchored in the ring and not
 *     at the origin (`lodLambda`, and see [12] for what the difference costs):
 *       the corner node (d = 0)        -> 0
 *       an axis node   (d = size)      -> the ring has only just begun    = 0
 *       the diagonal   (d = 1.414·size)-> still short of 1.5·size         = 0
 *     LEVEL 0 IS THE EXCEPTION, and it is not an exception to the rule but to
 *     the arithmetic: its ring starts at 0, so its ramp starts at 0.5·128 = 64
 *     = size and its diagonal node at d = size·√2 sits (√2 − 1) = 0.414213562…
 *     of the way through it.
 * (o2) THE RAMP ITSELF, on one node alone in the world. [0, 128]² at level 1
 *     owns [128, 256] and morphs over [192, 256]; a camera on the x axis at
 *     128 + d stands exactly d from its east face, so d = 192 -> 0,
 *     d = 224 -> 0.5, d = 256 -> 1.
 *
 * ============================================================================
 * [6] CRACK-FREENESS, measured
 * ============================================================================
 * A node at level L with morph 1 must describe exactly its PARENT's polyline:
 * every vertex snapped onto the parent lattice (index − index mod 2) and every
 * height taken from the parent's mip level. Then a neighbour that has just
 * stepped up to L+1 draws the same line, and there is no gap to skirt over.
 *
 * (p) All 33 vertices of a fully morphed level-1 node's north edge land on
 *     level-2 lattice points and carry the level-2 height — checked against
 *     the parent node's own morph-0 vertices, on a field with a spike in it so
 *     the two levels really disagree.
 * (q) RED COUNTER-PROBE: the same node at morph 0 does NOT — its odd vertices
 *     sit between the parent's points and carry the finer height, which is
 *     precisely the crack a skirt would have to hide.
 *
 * AND THE WORLD FRAME. A node is a power-of-two square and the frame is not,
 * so the outermost nodes reach past it; the shader clamps their vertices onto
 * it rather than letting the ground run on behind the backdrop ring
 * (`ground.BASE_MARGIN_M`). Checked twice over: nothing lands outside the
 * frame, and the clamp opens no crack — a node and its parent clamp against
 * the SAME rectangle, so the last vertex of a 256 m node at a 200 m frame is
 * 200 for both of them.
 *
 * ============================================================================
 * [8] THE MORPH BELONGS TO THE VERTEX — the seam fix of 2026-08-21
 * ============================================================================
 * [6] proves that a node AT MORPH 1 is its parent. It does not prove that a
 * node ever REACHES morph 1 while its neighbour still needs it to, and until
 * this round it did not: the morph was one number per patch, taken from the
 * patch's bounding-box distance. Two neighbours whose boxes straddle the morph
 * ramp then draw two different polylines along the edge they share — the
 * hairline of sky behind it was measured at 0.61 m, i.e. 6.2 px at 127 m.
 *
 * (w) λ, THE CONTINUOUS LOD COORDINATE (`lodLambda`), on the geometric ranges
 *     [128, 256, 512, 1024, 2048, 4096]. Each term is
 *     `clamp((d − range/2) / (range/2), 0, 1)`:
 *       d =   0 -> 0                                        = 0
 *       d =  64 -> (64−64)/64 = 0                            = 0
 *       d =  96 -> (96−64)/64 = 0.5, the rest 0               = 0.5
 *       d = 128 -> 1 + (128−128)/128 = 1                      = 1
 *       d = 192 -> 1 + (192−128)/128 = 0.5                    = 1.5
 *       d = 256 -> 1 + 1 + (256−256)/256                      = 2
 *       d = 400 -> 1 + 1 + (400−256)/256 = 0.5625             = 2.5625
 *     so λ(range[i]) = i + 1 and λ is the ring structure written as one
 *     monotone, continuous number.
 *
 * (x) TWO NEIGHBOURS, ONE POLYLINE. Camera on the world corner as in [5], so
 *     the level-0 node at (64, 0) and the level-1 node at (128, 0) share the
 *     edge x = 128, z ∈ [0, 64]. The fine node meets it with 33 vertices every
 *     2 m, the coarse one with every 4 m; the 17 points they have in common
 *     must agree to the last bit, in x, z AND y.
 *
 *     THE FIELD is a 6 m step every other 4 m of z: `h = 6` where
 *     `floor(z/4)` is odd, 0 where it is even. On the 2 m lattice that reads
 *     0, 0, 6, 6, 0, 0, … at z = 0, 2, 4, 6, 8, 10; the 4 m mip keeps 0, 6, 0,
 *     6 at z = 0, 4, 8, 12; and the 8 m mip is FLAT 0, since 8k/4 = 2k is even
 *     for every k. So the three levels really disagree, at the very points the
 *     two nodes have to meet on.
 *
 *     Worked at the vertex (128, 4), where the field is 6:
 *     d = √(128² + 6² + 4²) = 128.2029…, λ = 1 + (128.2029 − 128)/128 =
 *     1.001585… The fine node subtracts its level 0 -> t = 1.001585, k = 1,
 *     f = 0.001585: it snaps to every 2nd index — a 4 m lattice — and blends
 *     the 4 m mip towards the 8 m one. The coarse node subtracts its level 1
 *     -> t = 0.001585, k = 0, f = 0.001585: it snaps to every 1st index of its
 *     own 4 m grid — the SAME 4 m lattice — and blends the same two mips by
 *     the same f. The node's own level has cancelled out of every term, which
 *     is the whole argument.
 *
 *     THE 17 SHARED VERTICES therefore agree to the last bit — that is what
 *     closes the seam. The fine node's OTHER 16, the ones that collapse onto
 *     the coarse lattice, used to read their λ at the point they START from
 *     rather than at the one they end on, and missed it by up to 4 cm on this
 *     fixture. Since § A16.6 (2026-08-22) the morph is read at the BLOCK a
 *     vertex snaps into and not at the vertex, so those 16 land on the coarse
 *     polyline exactly: the whole fine edge lies ON the coarse one, 0 and not
 *     0.036 m. The derivation is in `lodVertex`; what it buys over the whole
 *     ground is [12].
 *
 * (y) RED COUNTER-PROBE: the same two nodes drawn as the renderer drew them
 *     before, with ONE morph per node. Both morphs are 0 here (the fine node's
 *     box is 64 m away, λ(64) = 0; the coarse one's is 128 m away,
 *     λ(128) − 1 = 0), so the fine node draws the 2 m mip and the coarse one
 *     the 4 m mip. At the fine node's vertex z = 2 the 2 m mip reads 0, while
 *     the coarse node's polyline runs straight from 0 at z = 0 to 6 at z = 4
 *     and is therefore at 3 — a THREE-METRE hole, in the ground, between two
 *     patches that touch.
 *
 * ============================================================================
 * [9] COVERAGE — the selected nodes tile every visible piece of ground
 * ============================================================================
 * [5] and [8] say which nodes are picked and that they meet without a crack.
 * Neither says the picked set has no HOLE in it, and a missing node is not a
 * seam but a window to the sky — the light blue of `engine.ts` (`0x9fc7e8`,
 * background and fog are the same colour), flashing on and off as the camera
 * turns. That is what this section measures, and it measures it over the WHOLE
 * COMPASS, because a hole of this kind is by nature about one direction.
 *
 * SINCE 2026-08-22 THE SELECTION CULLS NOTHING, so the invariant below holds by
 * construction and the section is a regression guard rather than a discovery.
 * What it still measures is the two things that DID lose ground, both kept as
 * red probes: the drawn list arriving one frame late (z3) and the frustum test
 * with a box the server's capped statistics do not cover (z4).
 *
 * THE INVARIANT. For a camera anywhere, the union of the SELECTED squares must
 * contain every ground point that is
 *   inside the view frustum ∩ inside the world frame ∩ nearer than the haze
 * (520 m, `engine.ts`). Not "roughly cover": every sample, every heading.
 *
 * WHY IT WAS DECIDABLE AT ALL WHILE THE CULL EXISTED — the theorem the check
 * was built on, and the one the red probes now break on purpose. Let the box of
 * every node contain the ground drawn over its square. A visible point p lies
 * in the box of the leaf that owns it and, since a child's square and its
 * heights are a subset of its parent's, in the box of EVERY ancestor of that
 * leaf. So no ancestor could fail the frustum test, the recursion walked all
 * the way down the chain that owns p, and somewhere on that chain a node was
 * selected. Coverage therefore failed if and ONLY if some node's box was too
 * small — and (z4) shows that the shipped `nodeBounds` really can be too small,
 * because `tile_stats` is capped and a tile with no statistic is folded in as
 * flat ground at zero whether it is flat or not.
 *
 * THE FIXTURE is the reported region: a 5 120 m world frame
 * [−2560, 2560]² — negative-heavy, so every `Math.floor` on a negative
 * coordinate really runs — 256 m tiles at a 2 m step, an honest `min`/`max`
 * per tile off that very lattice, and a camera at (−1550, −760), the spot the
 * finding was reported from. Three orbit settings (8 m / −15°, 25 m / −25°,
 * 60 m / −35°) and 360 headings each, on the § A1.8 compass: yaw 0 looks
 * south (+z), 90 east (+x), 180 north (−z), 270 west (−x).
 *
 * (z1) THE NEGATIVE TILE KEYS AND BOXES, by hand, because a truncation instead
 *      of a floor is the classic way a renderer loses the western half of a
 *      world:
 *        (−1550, −760) at 256 m -> floor(−6.0546875), floor(−2.96875)
 *                               -> tile (−7, −3), which spans
 *                                  x ∈ [−1792, −1536), z ∈ [−768, −512)
 *                                  — and truncation would say (−6, −2), the
 *                                  tile one step east AND one south.
 *        node (64, −128) of 64 m -> tx ∈ {0}, tz ∈ {−1}: exactly ONE tile, and
 *                                  neither (0, 0) nor (−1, −1) leaks in.
 *        node (−128, −128) of 256 m -> the four tiles around the origin.
 *        node (−256, −512) of 256 m -> tile (−1, −2) alone: the `− 1e-6`
 *                                  keeps the tile that STARTS on its east edge
 *                                  out.
 * (z2) THE SWEEP: 0 misses, at all 1 080 headings of the three settings, over
 *      4 373 188 sampled ground points, with at most 221 pieces in any one of
 *      them — well under the number the instance buffer is allocated against.
 *      (296 before `MAX_RANGE_WIDENING`: this world's error list asked for a
 *      1.5× wider innermost ring than the cap allows, so a quarter of the
 *      pieces were fine ones drawn past their geometric ring.)
 * (z3) RED COUNTER-PROBE A — THE DEFECT THAT WAS MEASURED. three.js uploads an
 *      `InstancedBufferGeometry`'s dirty attributes in `projectObject`
 *      (`WebGLObjects.update`, guarded by "Update once per frame"), and
 *      `projectObject` runs over the whole scene BEFORE the first
 *      `object.onBeforeRender`. The selection used to be written in that hook,
 *      so the ROWS the card read were the previous frame's while
 *      `geometry.instanceCount` — read at draw time — was this frame's. The
 *      probe draws exactly that: the previous heading's culled list, cut off at
 *      this heading's count.
 *
 *      HOW BIG THE DEFECT IS is a property of the RINGS, so it was re-measured
 *      when `MAX_RANGE_WIDENING` moved this world's innermost ring from 382 m
 *      back to 256 m: at 8 m / −15°, one degree of yaw per frame, 25 of 360
 *      headings lose ground over 13 122 sampled points — it was 40 headings and
 *      20 466 points on the uncapped rings, which drew a quarter more pieces and
 *      so had a quarter more of them to get wrong. The check therefore asks only
 *      that the defect is still there in force (a dozen headings, five figures
 *      of ground); the exact count belongs to the fixture, not to the law.
 *
 *      The SAME staleness against the shipped renderer loses nothing, because
 *      without a cull the selection is a function of the camera's POSITION and
 *      a changed heading does not change it.
 * (z4) RED COUNTER-PROBE B — THE CULL'S OWN BOX. `tile_stats` is capped
 *      server-side (`TILE_STATS_MAX`) and `nodeBounds` folds a zero into the
 *      box for every tile it holds no statistic for. Put the frustum test back
 *      with three quarters of the statistics missing and, at 25 m / −25°,
 *      132 of 360 headings lose ground, 14 498 sampled points. A cull is only
 *      as honest as the bound it culls against; this one could not be made
 *      honest without shipping every tile's statistic.
 * (z5) STABILITY, the other half of a flicker: over 7 200 yaw steps of 0.05°
 *      the selected SET changes by at most a handful of nodes — and those come
 *      from the orbit camera's EYE moving with the yaw, not from the heading:
 *      nothing in the selection reads a direction any more.
 *
 *      THE BOUND, DERIVED. The orbit eye stands `dist · cos(pitch)` from the
 *      point it looks at, so one 0.05° step carries it
 *      `dist · cos(pitch) · 0.05° in radians` — at 25 m / −25° that is
 *      25 · 0.9063 · 8.727e−4 = 0.0198 m, two centimetres. A piece changes only
 *      if its box distance crosses a ring boundary inside those two centimetres,
 *      and ONE crossing exchanges one piece for at most four: 5 entries of the
 *      set. Two crossings at once (siblings share a box distance over flat
 *      ground) make 10, three make 15, so the check asks for fewer than 16. The
 *      measurement is 5 at 8 m / −15° and 13 at 25 m / −25°, out of roughly 200
 *      pieces — three simultaneous events at the very worst step, never a
 *      redrawn frame. At 8 m / −15° the eye moves 6.7 mm per step and the worst
 *      is 5, i.e. a single crossing. (Both stayed under two events on the
 *      uncapped rings, whose boundaries lay at 382/554 m instead of on the
 *      doubling 256/512 m — where a whole row of same-level siblings, all of
 *      them a power of two from the camera, reaches the boundary together.)
 * (z6) THE SELECTION IS MIRROR-SYMMETRIC. A camera at (777, −333) and one at
 *      (−777, 333) over a symmetric frame select the same tree, node for node,
 *      through the point mirror (x, z) -> (−x − size, −z − size). Nothing in
 *      the quadtree, the ranges or λ knows a compass quadrant — λ reads a
 *      scalar distance, and the patch indices it snaps by are 0…32 whatever
 *      the node's own sign.
 * (z7) THE NEAR WINDOW, on its NEGATIVE side. The shader switches between the
 *      two pyramids on a RECTANGLE, which is only invisible where both answer
 *      the same number. [3](h) shows that south of a positive-coordinate tile;
 *      here it is shown on all four margin strips of the window around tile
 *      (−7, −3): window [−1920, −896] … [−1408, −384] (the tile grown by a
 *      128 m margin, `NEAR_MARGIN_CELLS` = 2 over a 64 m overview), where
 *      `heightAt` is the overview and the near pyramid, sampled from it at
 *      2 m, reproduces it exactly.
 *
 * ============================================================================
 * [13] A LEVEL WORLD IS DRAWN BY THE RINGS
 * ============================================================================
 * Until 2026-08-22 a world whose overview was level took `minLodDistance` 0:
 * every range 0, nothing ever split, the whole world drawn from its roots. The
 * isolation panel measured what that means on the "3D Test" world — a 7 km
 * frame, no height areas, the location at (−10, 10): SIXTEEN pieces of 2 048 m
 * for the entire world, of which the frustum kept three or four. At that
 * granularity every per-frame decision about a piece is a decision about a
 * square kilometre, which is how one wrong verdict became a hole in the sky.
 *
 * (qq) THE MODEL IS THAT WORLD, hand-derived before anything is asserted about
 *      the new rule: leaf 32 · 2 = 64 m, 6 levels, root 64 · 2^5 = 2 048 m,
 *      frame [−3500, 3500] covering roots −2…1 per axis = 4 × 4 = 16, every one
 *      of them 2 048 m. That is the panel's own "16".
 * (rr) THE SAME CAMERA WITH THE RINGS: 136 pieces, sized 64…2 048 m. Three
 *      digits, one draw call, and the near ground drawn at the 64 m leaf the
 *      server has data for instead of in 2 km lumps.
 * (ss) NO PIECE IS WIDER THAN ITS OWN DISTANCE, which is the ring structure as
 *      one number: `lodRange[i] = 128 · 2^i`, a whole node at level L is
 *      `64 · 2^L` wide and is emitted only once its box distance has reached
 *      `lodRange[L−1] = 64 · 2^L` — the same number. Level 0 is capped by the
 *      leaf instead. Inside the haze: 0 breaches now, 4 under the shortcut, the
 *      worst of them 32× wider than the ring allows.
 * (tt) …and the shaped compass world of [9] keeps the property, so it is the
 *      rule and not an accident of a level field.
 * (uu) THE CEILING. Nothing is culled, so the whole frame is selected every
 *      frame: 432 camera settings over the flat world (6 zoom steps × 72
 *      headings, the engine's own pitch law) reach at most 136 pieces, the
 *      compass world at most 221, against an instance buffer of `MAX_NODES` =
 *      4 096 that is allocated once and never replaced. The flat world has no
 *      error list at all, so `MAX_RANGE_WIDENING` cannot touch its 136; the
 *      compass world's 296 fell to 221 with it.
 *
 * ============================================================================
 * [14] THE CAP, AND THE CEILING THAT COARSENS RATHER THAN TRUNCATES
 * ============================================================================
 * [13](uu) sweeps two SMALL worlds with a gentle error list and finds a few
 * hundred pieces, which is what made `MAX_NODES` read like a guard against a
 * camera nobody has. The live world is neither small nor gentle: 16.6 × 14.4 km
 * (`world_bounds ± ground.BASE_MARGIN_M`) and a per-tile error bound of
 * 2…4.4 m at EVERY mip level, because the painted micro-relief (grass 1.0 m,
 * deep forest 1.5 m) is structure at the 2 m lattice itself — decimating it
 * once already costs its full amplitude, so `err[k]` barely grows with k
 * instead of halving with it.
 *
 * WHAT THE UNCAPPED RULE MADE OF THAT. `pixelScale` = 1 280 / (2 · tan 22.5°) =
 * 1 545.0967, so the error term is `err · 1545.0967 / 2 = err · 772.5483` and
 * level 0's is `1.9913 · 772.5483` = 1 538.4 m: the FINEST level drawn over a
 * disk of a kilometre and a half. 2 952 pieces at 1 280 px and 4 096 — the
 * ceiling — from 1 530 px up.
 *
 * WHAT THE CAP MAKES OF IT (`MAX_RANGE_WIDENING` = 2, 2026-08-22). Every error
 * term is measured against twice its own geometric ring:
 *   i=0: max( 128, min(1.9913 · 772.55 = 1538.4,  256)) =  256   <- at the cap
 *   i=1: max( 256, min(2.945  · 772.55 = 2275.2,  512)) =  512   <- at the cap
 *   i=2: max( 512, min(3.7229 · 772.55 = 2876.1, 1024)) = 1024   <- at the cap
 *   i=3: max(1024, min(3.5949 · 772.55 = 2777.2, 2048)) = 2048   <- at the cap
 *   i=4: max(2048, min(4.3741 · 772.55 = 3379.2, 4096)) = 3379.2 <- the rule
 *   i=5: max(4096, 0)                                   = 4096
 * — a clean doubling with ONE level moved, level 4, by 1.65 of its 2.0 allowance.
 * At a 2 160 px buffer the scale is 2 607.3506 and every error term is 1.69×
 * larger, so level 4 reaches its cap too and the ladder is
 * [256, 512, 1024, 2048, 4096, 4096]. The four inner rings are therefore THE
 * SAME at both viewports, which is the whole point: how far the finest ground
 * reaches must not be a function of the window's height.
 *
 * (vv) THE FIXTURE IS THAT WORLD, by its numbers and not by a fetch: the frame,
 *      the error list read off the server's own `heightfield.tile_stats`, and
 *      a flat box for every node (the live field spans 5.4 m, so a box is a
 *      rounding error against a ring of hundreds of metres). The ladder above is
 *      asserted at both viewports, and with it the ONE number the cap is for:
 *      1 538.4 m is what level 0 asked for and 256 m is what it gets.
 * (vv2) THE PIECE COUNT THAT FOLLOWS. At the reported camera the fixture selects
 *      372 pieces at 1 280 px and 390 at 2 160 px, `coarsenings` 0 both times —
 *      against 2 952 and the truncating 4 096 under the uncapped ladder. The
 *      18 extra pieces at 2 160 px are ALL at levels 4 and 5, where the ladder
 *      really did move (49/74 -> 70/71); levels 0…3 come back 67/58/59/65 at
 *      both, piece for piece, because their rings are pinned at the cap.
 *      A ROUGH CHECK ON THE ORDER, by hand: level L owns the annulus
 *      [128 · 2^(L−1), 128 · 2^L] and its pieces are 64 · 2^L wide, so
 *      π(4 − 1)(64 · 2^L)² / (64 · 2^L)² = 3π ≈ 9.4 whole pieces per level if
 *      the rings were circles and the quadtree could cut squares to fit; the
 *      out-of-range rule pays for the difference in half-sized quadrants (92 of
 *      the 372 here), and the roots outside the last ring for the rest.
 * (ww) THE RED PROBE — THE WORLD THAT REALLY OVERRAN THE BUFFER, put back by
 *      handing `LodSelectOpts.ranges` the UNCAPPED ladder (derived here from the
 *      same arithmetic, including the monotone repair the old code ran:
 *      [2596.0, 3839.3, 4853.5, 4853.5, 5702.4, 5702.4] at 2 160 px, where the
 *      raw level-3 term 4 686.6 falls below level 2's and is raised).
 *      `selectLodNodes` then returns exactly `MAX_NODES` = 4 096 pieces, and a
 *      256 m lattice over the frame finds ground no piece owns — the walk simply
 *      stopped. From a camera east and south of the origin — (3 000, 3 000),
 *      where the roots around it are ones the row-major walk reaches LATE —
 *      1 083 of 3 640 frame samples are uncovered and the nearest of them is
 *      240 m away, i.e. inside the 520 m haze and in plain view. The cap is not
 *      what makes this safe: it is one world's error list, and the ceiling has
 *      to hold for every world's.
 * (xx) THE GUARD: `selectLodFitted` on the same camera and the same uncapped
 *      rings halves them until the set fits — under the cap, and the 256 m
 *      lattice finds NO uncovered sample, on the frame and inside the haze
 *      alike. Halving is uniform, so the ranges stay monotone and
 *      `λ(range[i]) = i + 1` still holds exactly: the crack argument of [8]/[12]
 *      is untouched by the coarsening.
 * (yy) IT IS A NO-OP WHERE IT FITS: the live world under the SHIPPED (capped)
 *      rings, the flat world of [13] and the compass world of [9] all come back
 *      with `coarsenings` 0 and exactly the list `selectLodNodes` returns, so
 *      the guard costs nothing where nothing is wrong.
 *
 * ============================================================================
 * [7] THE ANALYTIC CLICK — `rayGroundHit`
 * ============================================================================
 * The ground under the pointer is solved against the FIELD, not raycast
 * against triangles that change with the camera.
 *
 * THE RAMP: one tile at 2 m over [0, 16]² carrying h(x, z) = x/2, so the field
 * range is 0…8.
 *
 * (r) STRAIGHT DOWN onto flat ground: from (4, 10, 4) along (0, −1, 0) over a
 *     tile of zeroes -> (4, 0, 4).
 * (s) DOWN THE RAMP: from (0, 10, 0) along (1, −1, 0). With t the arc length,
 *     x = t/√2 and y = 10 − t/√2; the ground under it is x/2 = t/(2√2). The
 *     ray meets it where
 *         10 − t/√2 = t/(2√2)  ->  10 = 3t/(2√2)  ->  t = 20√2/3 = 9.42809…
 *     i.e. at x = t/√2 = 20/3 = 6.6̄ and y = 10 − 20/3 = 10/3 = 3.3̄, where the
 *     ground is indeed x/2 = 3.3̄. The march walks in steps of one lattice cell
 *     of horizontal advance (2 m), so it brackets between x = 5 (f = +2.5) and
 *     x = 7 (f = −0.5) and bisects into that bracket.
 * (t) A MISS: the same origin along (0, +1, 0) — up, away from the world — and
 *     a ray running flat at y = 10 over a field whose highest point is 8.
 * (u) A RAY THAT STARTS BELOW THE GROUND hits at once, at its own origin:
 *     from (4, 1, 0) straight down, with the ramp at 2 m there.
 * (v) NO FIELD AT ALL is a miss, never a crash.
 *
 * ============================================================================
 * [10] THE SHADING NORMAL IS A FUNCTION OF THE GROUND — the shimmer fix
 * ============================================================================
 * [8] made the drawn SURFACE a function of the world position. The LIGHT on it
 * was not: the normal was built in the vertex shader as the central difference
 * of the vertex's own morph pair — spans `nodeStep·2^k` and twice that, blended
 * by `f = frac(λ)` — and λ is the vertex's distance to the CAMERA. So the
 * brightness of a fixed piece of ground moved when nothing but the camera did,
 * and with a low sun that is not a nuance: ground that falls past
 * `max(N·L, 0)` keeps only hemisphere sky (`0xdfeeff`) and fill (`0xdde8ff`)
 * and turns light blue. That is the whole-ground shimmer, and it is bound to
 * the sun's azimuth sector because the terminator is.
 *
 * THE NEW LAW, `terrainLodNormalGlsl` / `fragmentNormal`, per FRAGMENT:
 *
 *   n(x, z) = normalize( −(h(x+s, z) − h(x−s, z)), 2s, −(h(x, z+s) − h(x, z−s)) )
 *
 * with s = the base lattice step (2 m) and h the FINEST level, whatever the
 * ground under the pixel is drawn at. No node, no level, no morph, no camera.
 *
 * THE FIXTURE — a 1 m relief per axis on the 2 m lattice, with a period of 8 m,
 * so the coarse levels are provably blind to it. Per axis
 *   F(u) = 0 on [0, 2], (u−2)/2 on [2, 4], 1 on [4, 6], 1−(u−6)/2 on [6, 8],
 * repeated; on the 2 m lattice that reads 0, 0, 1, 1, 0, 0, 1, 1. The field is
 * H(x, z) = F(x) + F(z), which the bilinear reproduces exactly between the
 * lattice points (a separable sum of functions that are linear inside a cell).
 * The pyramid is 65 × 65 points at 2 m over [0, 128]², so
 *   level 1 keeps every 2nd point: F(0), F(4), F(8), F(12) = 0, 1, 0, 1 — a
 *          triangle wave of period 8, whose ±4 m central difference is
 *          IDENTICALLY ZERO (the two taps are one whole period apart);
 *   level 2 keeps every 4th point: F(0), F(8), F(16) = 0, 0, 0 — dead flat.
 * So on this fixture EVERY span above 2 m answers "straight up", and the old
 * law's blend runs from the true normal to the vertical.
 *
 * The probes are the 8 × 8 integer points of one period, placed at
 * (32 + i, 32 + j), i, j ∈ 0…7 — 32 is a multiple of 8, so the phase is the
 * one derived above, and the ±8 m taps stay far inside the window.
 *
 * (aa) THE FIXTURE ITSELF: the lattice column, the level shapes, and the two
 *      coarse levels being blind (period 8 and flat).
 * (bb) THE NORMAL AT A CREST FLANK. At (35, 35) — phase (3, 3) — the taps are
 *      h(37,35) − h(33,35) = F(5) − F(1) = 1 − 0 = 1, and the same in z. So
 *        n = normalize(−1, 4, −1) = (−1, 4, −1)/√18,
 *      i.e. (−0.235702260…, 0.942809041…, −0.235702260…) and a tilt from the
 *      vertical of acos(4/√18) = 19.4712206344°.
 * (cc) CAMERA INVARIANCE, measured rather than argued: every probe is asked for
 *      its normal from 200 cameras — 8 azimuths × 25 distances from 8 m to
 *      700 m, i.e. λ from 0 to λ(700) = 3 + (700−512)/512 = 3.3671875 (the
 *      first three terms have saturated), so the morph ramps of levels 0…3 are
 *      all crossed. The answer is bitwise the
 *      same 12 800 times over: the maximum deviation is 0, not 1e-9.
 * (dd) RED COUNTER-PROBE — the OLD law over the very same sweep, rebuilt here
 *      from its own arithmetic: L = ⌊λ⌋, f = λ − L, spans e1 = 2·2^L and
 *      e2 = 2·e1, each sampled at the mip level its span names, blended by f.
 *      At the nine probes with |h_x| = |h_z| = 1 it runs from (−1, 4, −1)/√18
 *      at f = 0 to straight up at f = 1, so the normal of one fixed piece of
 *      ground SWINGS by the full 19.4712206344° — the 16–17° class the live
 *      world was measured at — with the camera as the only thing that moved.
 * (ee) THE TERMINATOR, at the sun `engine.ts` really hangs at 18:00. There
 *      `sunAngle = π`, so the light sits at
 *        (cos π · 60, max(0.08, sin π) · 80, 25) = (−60, 6.4, 25),
 *      |·| = √(3600 + 40.96 + 625) = √4265.96 = 65.3142…, i.e. an ELEVATION of
 *      asin(6.4 / 65.3142) = 5.6233° and an azimuth atan2(25, −60) = 157.4°.
 *      With n ∝ (−h_x, 4, −h_z) the lit test is
 *        n · L ∝ 60·h_x − 25·h_z + 25.6 > 0.
 *      Over the 64 probes h_x runs −1, 0, 1, 1, 1, 0, −1, −1 (and h_z the same
 *      by symmetry), so
 *        h_x = −1 (3 columns): −34.4 − 25·h_z < 0 for every h_z ∈ {−1, 0, 1}
 *                              -> all 8 rows unlit -> 24 probes,
 *        h_x =  0 (2 columns): 25.6 − 25·h_z < 0 needs h_z > 1.024 -> none,
 *        h_x = +1 (3 columns): 85.6 − 25·h_z < 0 needs h_z > 3.424 -> none.
 *      So 24 of 64 probes stand in their own shadow — and they do so from
 *      EVERY camera, because the normal does not know about cameras: 0
 *      terminator crossings over the whole sweep. Under the OLD law the same
 *      24 are unlit at f = 0 and lit at f = 1 (a vertical normal at a sun 5.6°
 *      above the horizon is always lit), which is 24 crossings = 37.5 % of the
 *      ground flipping between sunlit and sky-blue as the camera moves.
 * (ff) NO FOOTPRINT BLEND was added, so there is nothing to make a function of
 *      the footprint: the shipped chunk names neither `cameraPosition` nor
 *      `iNode`, `uTlodRange` or `fwidth`, and the vertex chunk no longer
 *      computes a normal at all. The derivation for the fixed 2 m span is in
 *      `terrainLodNormalGlsl`.
 * (gg) THE COST, counted rather than guessed: the normal is 4 `tlodHeight`
 *      taps and each tap is a bilinear over 4 `texelFetch`, so 16 texel reads
 *      per GROUND FRAGMENT. The vertex shader gives 8 taps back (32 texels):
 *      `tlodCompute` is down from 11 `tlodHeight` calls to 3. The 16 texels of
 *      a fragment all lie in one 4 × 4 window of the R32F pyramid — 64 bytes,
 *      shared by every neighbouring pixel whose footprint is under the 2 m
 *      span, which at 45° / 1 080 px is every pixel nearer than 2.6 km.
 *
 * ============================================================================
 * [11] A SPLIT DOES NOT MOVE THE GROUND — the transition probe (2026-08-21)
 * ============================================================================
 * The isolation panel's toggle 10 ("LOD frozen") was reported to take the
 * whole-ground shimmer away, which would put the blame on the per-frame CHANGE
 * OF THE SELECTED NODE SET — split and merge. This section measures that claim
 * instead of arguing it, and the answer is no: what a split costs is a quarter
 * of a pixel.
 *
 * THE FIXTURE FIRST, because the obvious one proves nothing. The compass world
 * `CH` of [9] is three waves whose shortest period is 151 m: its 2 m lattice
 * and its 4 m decimation answer the same number to half a millimetre, so the
 * morph has nothing to carry and a transition probe run on it reports a pop of
 * 4e-3 m — a renderer with the morph deleted would pass. `TR` adds three short
 * waves (periods 8.2, 18 and 46 m) so that the levels genuinely disagree; (hh)
 * asserts that gap is over half a metre and that `CH` has none.
 *
 * (ii) THE SHARED VERTICES ARE EXACT. One parent (level 2, 256 m) and its SW
 *      child (level 1, 128 m), one camera: every vertex the two have in common
 *      lands on the same point at the same height — 0, not 1e-9. That is the
 *      whole of § A16.6's "the level cancels": t_child = λ − (L−1) = t_parent
 *      + 1, so k_child = k_parent + 1 and f is the SAME number, and the world
 *      snap pitch `nodeStep · 2^k` and the two mip spans `nodeStep · 2^k`,
 *      `· 2^(k+1)` come out identical in metres. Hypotheses "two distance
 *      metrics" and "the split threshold misses the morph end" die here: the
 *      metrics agree exactly, whatever the camera.
 * (jj) THE DIFFERENCE IS THE VERTICES THE CHILD ADDS. Its odd-index vertices
 *      are supposed to collapse onto their even twin wherever the child draws
 *      on a lattice coarser than its own (k = ⌊t⌋ ≥ 1) — that is what
 *      `mix(gi − gi mod m1, gi − gi mod m2, f)` does — but only if both use the
 *      SAME f. While f was each vertex's own λ they did not: a twin pair shares
 *      both `gi − gi mod m1` and `gi − gi mod m2`, so the entire separation was
 *      those two identical numbers blended with two different f,
 *
 *        offset = (gi mod m2 − gi mod m1) · Δt · nodeStep
 *
 *      measured 0.357060 m sideways and 0.086354 m in height. That is the
 *      vertex hanging beside the neighbour's edge — a T-junction, and on a
 *      flat-shaded, unfiltered, single-coloured ground still a sliver of sky.
 *      Since § A16.6 (2026-08-22) f is read at the BLOCK the vertex snaps into,
 *      which every member of the block shares, so the offset is 0 in both axes.
 *      The red probe here rebuilds the per-vertex reading and reproduces both
 *      old numbers to the digit.
 * (kk) AND A SPLIT NOW COSTS NOTHING AT ALL. 60 m of camera path heading
 *      east–north, 23 transitions, 14 161 ground points read from the OLD node
 *      set and the NEW one at the SAME camera: the worst difference is 3.4e-9 m,
 *      and those nanometres are the PROBE's barycentric division by the
 *      determinant of a triangle the morph has collapsed, not the ground (the
 *      derivation is at the check). It used to be 0.101 m (0.25 px of a
 *      45° / 1 080 px view) and the check asked for no more than a quarter of
 *      `MAX_PIXEL_ERROR`; the bound is now a micrometre, because the drawn
 *      surface is a function of the world point and its block and neither knows
 *      which piece drew it.
 * (ll) NO COMPASS DIRECTION, which was the other hypothesis (a corner bias in
 *      the box distance would make nodes east and north of the camera split
 *      earlier than their mirror images). The WORLD is mirrored through the
 *      origin — every tile (tx, tz) becomes (−tx−1, −tz−1), because tile tx
 *      spans [tx·T, (tx+1)·T) — and the opposite heading is walked: all 120
 *      frames answer the exactly mirrored tree. (z6) shows the same on a flat
 *      box; this shows it with the height boxes carrying real relief.
 *
 * WHAT THIS SECTION SAYS SINCE § A16.6: exchanging one piece for four moves the
 * ground by nothing measurable, and the one real residue (jj) is gone rather
 * than bounded. [12] is what pays for that.
 *
 * ============================================================================
 * [12] NO VERTEX HANGS BESIDE A NEIGHBOUR'S EDGE — the T-junction probe
 * ============================================================================
 * [8] and [11] measure single hand-picked pairs. This section measures the
 * WHOLE DRAWN GROUND: for every stretch of edge two rendered pieces share, every
 * vertex of each side must lie ON the other side's chain. A vertex that does not
 * is a T-junction — the ground has a hairline it cannot close — and on a
 * flat-shaded, unfiltered, single-coloured ground that hairline is still sky.
 * (The isolation panel measured exactly that: toggles 6, 7 and 18 together left
 * the light-blue shimmer standing, while toggle 10 took it away.)
 *
 * THE MEASURE IS A DISTANCE TO THE CHAIN, not a height read at a coordinate,
 * and that is not pedantry. The morph slides a vertex ALONG the shared edge as
 * well as across it, and under the old rule it slid two twins past each other:
 * the edge folded back on itself by 0.276 m. An evaluation at a coordinate then
 * reports 0.1 m of "gap" between two IDENTICAL chains, which is a measurement of
 * the probe and not of the ground.
 *
 * THE SWEEP is the `TR` world of [11] — the only fixture here whose 2 m lattice
 * and 4 m decimation really disagree — over 120 frames of the 60 m east–north
 * walk plus all 24 headings of a 15° compass at its start, 144 camera settings
 * and 3 346 436 edge vertices in all (it was 4 550 801 before
 * `MAX_RANGE_WIDENING` pulled this world's innermost ring back from 382 m to
 * 256 m and with it a quarter of the pieces).
 *
 * (mm) 0 vertices off the neighbour's chain by more than a micrometre, worst
 *      2.1e-13 m. That is float precision, not a small number.
 * (nn) RED — the old rule, rebuilt here from its own arithmetic (`redSelect`
 *      hands every child the finer level whether its own distance is still in
 *      the ring or not, `redLambda` anchors every ramp at the origin,
 *      `redVertex` reads the morph per vertex): 100 779 of 3 947 500 tests off,
 *      worst 0.1171 m. At 500 m that is 0.3 px of sky, and it moves to a
 *      different edge with every camera step, which is what a shimmer is.
 * (oo) NO PIECE IS DRAWN BEYOND ITS OWN RING. `morph` is λ at the piece's
 *      nearest point minus its level, and λ(range[i]) = i + 1 exactly
 *      (`lodLambda`), so `morph ≤ 1` IS the out-of-range rule. 0 offenders now;
 *      12 587 under the old rule, i.e. two pieces in five of what it drew.
 * (pp) AND IT IS CHEAPER. Same number of pieces per frame — a far child that
 *      used to be emitted at the finer level is now emitted as its parent's
 *      quadrant, one instance either way — but the quadrant carries the
 *      PARENT's spacing over the child's square, so it costs a quarter of the
 *      triangles: 335 275 per frame against 436 779, 77 %.
 */
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');

/**
 * A THREE.js stand-in, so a module that draws can still be checked as maths.
 *
 * `terrainLod.ts` allocates exactly two kinds of three object while it LOADS —
 * the neutral height texture and the level uniform array — and nothing else in
 * this file ever touches three. The stub therefore has to answer for those two
 * and no more; anything the module started using beyond them would fail here
 * loudly, which is the alarm this arrangement exists for.
 */
const THREE_STUB = `
export class DataTexture {
  constructor(data, w, h, format, type) {
    this.image = { data, width: w, height: h };
    this.format = format;
    this.type = type;
  }
  dispose() {}
}
export class Vector4 {
  constructor(x = 0, y = 0, z = 0, w = 0) { this.set(x, y, z, w); }
  set(x, y, z, w) { this.x = x; this.y = y; this.z = z; this.w = w; return this; }
}
export class CanvasTexture {
  constructor(image) { this.image = image; }
  dispose() {}
}
export const RedFormat = 1022;
export const FloatType = 1015;
export const NearestFilter = 1003;
export const ClampToEdgeWrapping = 1001;
`;

/**
 * The one piece of DOM the water variant touches: the shared wave normal map
 * is drawn onto a 256² canvas (`@anima/scene-render materials.makeWaveNormal`)
 * the first time a water program is compiled, and [16] compiles one. The stub
 * takes the pixels and throws them away — what is checked here is the SHADER,
 * never the map.
 */
if (typeof globalThis.document === 'undefined') {
  globalThis.document = {
    createElement: () => ({
      width: 0,
      height: 0,
      getContext: () => ({
        fillStyle: '',
        fillRect() {},
        putImageData() {},
        createImageData: (w, h) => ({ data: new Uint8ClampedArray(w * h * 4) }),
      }),
    }),
  };
}

/**
 * Transpile a module and import it, with `three` and `@anima/scene-render`
 * resolved to local files.
 *
 * The package entry is a two-line BARREL over the two files `terrainLod.ts`
 * really takes something from — `worldHeight.ts` (the lattice sampler) and,
 * since K-A E4, `materials.ts` (the shared wave map, the shared sky and the
 * shared clock). Both are three-free at RUNTIME: materials.ts imports three
 * only as a TYPE, which esbuild erases, so no stub is needed and the constants
 * the water look falls back to are the REAL ones. Pointing at the real barrel
 * instead would drag three back in through the front door.
 *
 * `waterRaster.ts`, `waterPlaneMath.ts` and `waterShade.ts` come along as local
 * siblings: all three are pure arithmetic over the wire shape and over the
 * shore curves, so they load under exactly the same rules.
 *
 * `layerGround.ts` is STUBBED and not transpiled. `terrainLod.ts` takes exactly
 * one function from it (the borrowed id-mask uniforms, K-A E4) and that file
 * pulls in three, the texture library and the DOM — a wiring line, checked by
 * `npm run build -w client3d` and by nothing that could be derived by hand.
 */
async function loadLod() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'terrainlod-'));
  try {
    const ts = async (src, name) => {
      const code = await readFile(src, 'utf8');
      await writeFile(join(dir, `${name}.mjs`),
        esbuild.transformSync(code, { loader: 'ts', format: 'esm' }).code
          .replace(/from\s*["']@anima\/scene-render["']/g, "from './sceneRender.mjs'")
          .replace(/from\s*["']\.\/([A-Za-z]+)["']/g, "from './$1.mjs'"),
        'utf8');
    };
    await writeFile(join(dir, 'three.mjs'), THREE_STUB, 'utf8');
    await writeFile(join(dir, 'sceneRender.mjs'),
      "export * from './worldHeight.mjs';\nexport * from './materials.mjs';\n", 'utf8');
    await writeFile(join(dir, 'layerGround.mjs'),
      'export function bindLayerIdUniforms(u, idName, geomName) {\n'
      + '  u[idName] = { value: null };\n  u[geomName] = { value: null };\n}\n', 'utf8');
    await ts(join(ROOT, 'packages/scene-render/src/worldHeight.ts'), 'worldHeight');
    await ts(join(ROOT, 'packages/scene-render/src/materials.ts'), 'materials');
    await ts(join(ROOT, 'client3d/src/scene/waterRaster.ts'), 'waterRaster');
    await ts(join(ROOT, 'client3d/src/scene/waterPlaneMath.ts'), 'waterPlaneMath');
    await ts(join(ROOT, 'client3d/src/scene/waterShade.ts'), 'waterShade');
    const src = await readFile(join(ROOT, 'client3d/src/scene/terrainLod.ts'), 'utf8');
    const out = esbuild.transformSync(src, { loader: 'ts', format: 'esm' }).code
      .replace(/from\s*["']three["']/g, "from './three.mjs'")
      .replace(/from\s*["']\.\/(waterRaster|waterShade|layerGround)["']/g,
               "from './$1.mjs'")
      .replace(/from\s*["']@anima\/scene-render["']/g, "from './sceneRender.mjs'");
    await writeFile(join(dir, 'terrainLod.mjs'), out, 'utf8');
    return {
      lod: await import(`file://${join(dir, 'terrainLod.mjs')}`),
      height: await import(`file://${join(dir, 'worldHeight.mjs')}`),
      water: await import(`file://${join(dir, 'waterRaster.mjs')}`),
      shade: await import(`file://${join(dir, 'waterShade.mjs')}`),
    };
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

let failed = 0;
let passed = 0;
function check(label, actual, expected, eps = 1e-9) {
  const ok = typeof actual === 'number' && Math.abs(actual - expected) <= eps;
  if (ok) {
    passed += 1;
    console.log(`  ok   ${label} = ${actual}`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}\n       expected ${expected}\n       actual   ${actual}`);
  }
}
function checkBelow(label, actual, ceiling) {
  const ok = typeof actual === 'number' && actual >= 0 && actual < ceiling;
  if (ok) {
    passed += 1;
    console.log(`  ok   ${label} = ${actual} (< ${ceiling})`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}\n       expected < ${ceiling}\n       actual   ${actual}`);
  }
}
function checkAbove(label, actual, floor) {
  const ok = typeof actual === 'number' && actual > floor;
  if (ok) {
    passed += 1;
    console.log(`  ok   ${label} = ${actual} (> ${floor})`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}\n       expected > ${floor}\n       actual   ${actual}`);
  }
}
function checkEq(label, actual, expected) {
  const a = JSON.stringify(actual);
  const b = JSON.stringify(expected);
  if (a === b) {
    passed += 1;
    console.log(`  ok   ${label} = ${a}`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}\n       expected ${b}\n       actual   ${a}`);
  }
}

const { lod, height, water, shade } = await loadLod();
const { PATCH_N, MAX_LOD_LEVELS, MIN_LOD_DISTANCE_M, MAX_NODES, MORPH_START, MAX_PIXEL_ERROR,
  MAX_RANGE_WIDENING,
  buildPyramid, pyramidHeight, pyramidLevelFor, lodRanges, selectLodNodes,
  morphedVertex, lodLambda, lodVertex, nodeBounds, terrainLodGlsl, selectLodFitted,
  levelErrorsFrom,
  terrainLodNormalGlsl, fragmentNormal, gpuHeightAt,
  buildWaterPyramid, wlevelAt, bindTerrainLodUniforms,
  terrainLodWaterGlsl, nodeHasWater, liftedHeight, liftedDepth, gpuWaterAt,
  patchTerrainLod,
  TERRAIN_LOD_CACHE_KEY, TERRAIN_LOD_WATER_CACHE_KEY } = lod;
const { heightAt, rayGroundHit, sampleWorldHeight } = height;
const { emptyWaterRaster, rasterLevelAt, waterTileFrom } = water;

// ── [1] the constants ───────────────────────────────────────────────────────
console.log('[1] the constants are derived from the server\'s own pyramid');
const BASE = 2;
check('cells per patch axis', PATCH_N, 32);
check('levels', MAX_LOD_LEVELS, 6);
check('lodRange[0]', MIN_LOD_DISTANCE_M, 128);
check('the morph starts at half a range', MORPH_START, 0.5);
check('the pixel budget', MAX_PIXEL_ERROR, 2);
const stepsPerLevel = [];
for (let i = 0; i < MAX_LOD_LEVELS; i += 1) stepsPerLevel.push(BASE * (1 << i));
checkEq('(a) the node grid steps at a 2 m base', stepsPerLevel, [2, 4, 8, 16, 32, 64]);
// The server's own list, read out of the Python so the two cannot drift.
const heightfieldPy = await readFile(join(ROOT, 'app/core/heightfield.py'), 'utf8');
const mipLine = /MIP_LEVELS_M = \(([^)]*)\)/.exec(heightfieldPy);
const serverMips = mipLine[1].split(',').map((s) => Number(s.trim())).filter((n) => n > 0);
checkEq('(b) levels 1..5 ARE the server\'s MIP_LEVELS_M', stepsPerLevel.slice(1), serverMips);
check('the leaf node edge', PATCH_N * BASE, 64);
check('the root node edge', PATCH_N * BASE * (1 << (MAX_LOD_LEVELS - 1)), 2048);
check('(c) vertices per patch', (PATCH_N + 1) ** 2, 1089);
check('…index entries', PATCH_N * PATCH_N * 6, 6144);
// The shader fetches, it does not filter: R32F is not filterable in core
// WebGL2, and a driver that DID filter it would round the weights its own way.
const glsl = terrainLodGlsl();
check('the shader fetches texels', glsl.split('texelFetch(').length - 1, 4);
checkEq('…and never asks a sampler to filter', glsl.includes('texture2D('), false);
checkEq('…nor the GLSL3 spelling of it', /\btexture\s*\(/.test(glsl), false);

// ── [2] the pyramid ─────────────────────────────────────────────────────────
console.log('\n[2] the pyramid is decimation — the SAME function, coarser');
const ARB = (x, z) => (((7 * (x / 2) + 13 * (z / 2)) % 11) - 5);
const arb = buildPyramid(ARB, 0, 0, 2, 5, 5, MAX_LOD_LEVELS);
check('levels', arb.levels.length, 3);
check('texture width', arb.texW, 5);
check('texture height', arb.texH, 10);
checkEq('the level shapes', arb.levels.map((l) => [l.cols, l.rows, l.step, l.row0]),
  [[5, 5, 2, 0], [3, 3, 4, 5], [2, 2, 8, 8]]);
check('texels held', arb.data.length, 50);
// (d) every coarse support point reads what level 0 reads there
let worst = 0;
for (let k = 1; k < arb.levels.length; k += 1) {
  const lv = arb.levels[k];
  for (let j = 0; j < lv.rows; j += 1) {
    for (let i = 0; i < lv.cols; i += 1) {
      const x = i * lv.step;
      const z = j * lv.step;
      worst = Math.max(worst, Math.abs(pyramidHeight(arb, x, z, k)
        - pyramidHeight(arb, x, z, 0)));
    }
  }
}
check('(d) coarse support points == fine support points', worst, 0);
// (e) a linear field survives every level, between the points as well
const lin = buildPyramid((x, z) => x / 2 + z, 0, 0, 2, 5, 5, MAX_LOD_LEVELS);
for (const [x, z, want] of [[1, 1, 1.5], [7.5, 2.5, 6.25], [3, 5, 6.5]]) {
  for (let k = 0; k < lin.levels.length; k += 1) {
    check(`(e) the plane at (${x}, ${z}), level ${k}`, pyramidHeight(lin, x, z, k),
      want, 1e-6);
  }
}
// (f) a spike on an ODD lattice index is gone one level up — that IS the error
const spike = buildPyramid((x, z) => (x === 2 && z === 2 ? 8 : 0), 0, 0, 2, 5, 5,
                           MAX_LOD_LEVELS);
check('(f) level 0 has the spike', pyramidHeight(spike, 2, 2, 0), 8);
check('…level 1 does not', pyramidHeight(spike, 2, 2, 1), 0);
check('…so drawing that tile one level up costs', pyramidHeight(spike, 2, 2, 0)
  - pyramidHeight(spike, 2, 2, 1), 8);
checkEq('the level for a node step, base 2', [2, 4, 8, 16, 32, 64]
  .map((s) => pyramidLevelFor(arb, s)), [0, 1, 2, 2, 2, 2]);

// ── [3] the GPU formula ─────────────────────────────────────────────────────
console.log('\n[3] the shader formula IS the sampler — reimplemented, not read');
/** `tlodGrid` of the vertex shader, written out from the arithmetic. */
function glslGrid(pyr, k, x, z) {
  const lv = pyr.levels[k];
  const { cols, rows, step, row0 } = lv;
  if (cols < 2 || rows < 2 || step <= 0) return 0;
  const fx = Math.min(Math.max((x - pyr.originX) / step, 0), cols - 1);
  const fz = Math.min(Math.max((z - pyr.originZ) / step, 0), rows - 1);
  const fi = Math.min(Math.floor(fx), cols - 2);
  const fj = Math.min(Math.floor(fz), rows - 2);
  const tx = fx - fi;
  const tz = fz - fj;
  const at = (i, j) => pyr.data[(j + row0) * pyr.texW + i];
  const north = at(fi, fj) * (1 - tx) + at(fi + 1, fj) * tx;
  const south = at(fi, fj + 1) * (1 - tx) + at(fi + 1, fj + 1) * tx;
  return north * (1 - tz) + south * tz;
}
/**
 * ONE height function, two rasters — which is what E1 made true of the server
 * (addendum § 1) and what the fixture has to honour, or it would be testing a
 * world that cannot exist. `H` is defined on the 2 m lattice; the tiles take
 * every point of it, the overview every second one, so the two carry the SAME
 * number wherever they share a support point.
 */
const H = (x, z) => ((((7 * (x / 2) + 13 * (z / 2)) % 11) + 11) % 11) - 5;
const TILE_N = 9;                 // 9 points at 2 m = one 16 m tile
function tileOf(tx) {
  return {
    origin_x: tx * 16, origin_z: 0, step_m: 2, rows: TILE_N, cols: TILE_N,
    heights: Array.from({ length: TILE_N }, (_, j) =>
      Array.from({ length: TILE_N }, (_, i) => H(tx * 16 + 2 * i, 2 * j))),
  };
}
const OV_N = 17;                  // 17 points at 4 m over [-16, 48]
const OVERVIEW = {
  origin_x: -16, origin_z: -16, step_m: 4, rows: OV_N, cols: OV_N,
  heights: Array.from({ length: OV_N }, (_, j) =>
    Array.from({ length: OV_N }, (_, i) => H(-16 + 4 * i, -16 + 4 * j))),
};
// TWO loaded tiles, so the fixture has an INTERIOR seam. The rim of the loaded
// set is a real discontinuity in `heightAt` itself (a tile answers alone,
// § A16.3) and no renderer can smooth it; in the client it sits at 560 m,
// behind the haze. The interior seam is the one that must be invisible.
const COMPOSITE = {
  tileM: 16, overview: OVERVIEW,
  tiles: new Map([['0,0', tileOf(0)], ['1,0', tileOf(1)]]),
};
check('the two tiles share the column at x = 16',
  heightAt(COMPOSITE, 16, 6) - H(16, 6), 0);
// The near window: the loaded tiles grown by 8 m, on the 2 m lattice.
const NEAR_X0 = -8;
const NEAR_Z0 = -8;
const NEAR_COLS = 25;   // -8 … 40 at 2 m
const NEAR_ROWS = 17;   // -8 … 24
const near = buildPyramid((x, z) => heightAt(COMPOSITE, x, z),
                          NEAR_X0, NEAR_Z0, 2, NEAR_COLS, NEAR_ROWS, MAX_LOD_LEVELS);
check('the near window reaches', NEAR_X0 + (NEAR_COLS - 1) * 2, 40);
// (g) inside the loaded set, ACROSS the interior seam at x = 16
let gpuWorst = 0;
let samples = 0;
for (let z = 0; z <= 14; z += 0.5) {
  for (let x = 0; x <= 30; x += 0.5) {
    gpuWorst = Math.max(gpuWorst,
      Math.abs(glslGrid(near, 0, x, z) - heightAt(COMPOSITE, x, z)));
    samples += 1;
  }
}
check('samples taken', samples, 61 * 29);
check('(g) |h_gpu - h_cpu| stays under 1e-4', gpuWorst < 1e-4 ? 0 : gpuWorst, 0);
check('…and on THIS fixture it is exactly 0 (small halves survive R32F)',
  gpuWorst, 0);
// What the 1e-4 of the contract is really for: a height that is not a binary
// fraction loses about 6e-6 m to the 24-bit mantissa at the scale a world is
// shaped in. Sampled here so the bound is a measured number and not a hope.
const ROUGH = buildPyramid((x, z) => 0.1 * x + 0.03 * z, 0, 0, 2, 9, 9, 1);
let f32Worst = 0;
for (let z = 0; z <= 16; z += 0.5) {
  for (let x = 0; x <= 16; x += 0.5) {
    f32Worst = Math.max(f32Worst, Math.abs(glslGrid(ROUGH, 0, x, z) - (0.1 * x + 0.03 * z)));
  }
}
check('R32F rounding on a non-representable field is under 1e-5',
  f32Worst > 0 && f32Worst < 1e-5 ? 1 : 0, 1);
checkEq('a few of them by name', [[0, 0], [1, 1], [7, 3], [15.5, 9.5], [16, 6], [17, 7]]
  .map(([x, z]) => Math.abs(glslGrid(near, 0, x, z) - heightAt(COMPOSITE, x, z)) < 1e-4),
  [true, true, true, true, true, true]);
// (h) the margin, where the switch between the pyramids happens
const far = buildPyramid((x, z) => sampleWorldHeight(OVERVIEW, x, z),
                         OVERVIEW.origin_x, OVERVIEW.origin_z, 4, OV_N, OV_N,
                         MAX_LOD_LEVELS);
// The strip runs to z = −2 and no further: the 2 m cell [−2, 0] has its south
// row ON the loaded set, so it is the rim cell itself. That is why the near
// window is grown by TWO overview cells (`NEAR_MARGIN_CELLS`) — the rectangle
// the shader switches on must lie strictly outside the rim.
let rimWorst = 0;
for (let z = -8; z <= -2; z += 0.5) {
  for (let x = -8; x <= 40; x += 0.5) {
    rimWorst = Math.max(rimWorst, Math.abs(glslGrid(near, 0, x, z) - glslGrid(far, 0, x, z)));
  }
}
check('(h) near == far in the margin strip', rimWorst < 1e-4 ? 0 : rimWorst, 0);
check('…and there too it is exact, not merely close', rimWorst, 0);
// (i) the red counter-probe: one level up is a different surface
let mipWorst = 0;
for (let z = 0; z <= 14; z += 0.5) {
  for (let x = 0; x <= 30; x += 0.5) {
    mipWorst = Math.max(mipWorst,
      Math.abs(glslGrid(near, 1, x, z) - heightAt(COMPOSITE, x, z)));
  }
}
check('(i) RED: level 1 is NOT the sampler, and misses by more than a metre',
  mipWorst > 1 ? 1 : 0, 1);

// ── [4] the ranges ──────────────────────────────────────────────────────────
console.log('\n[4] the LOD ranges — geometry, widened by the error bound, capped at one doubling');
checkEq('(j) without an error list', lodRanges(128, 6),
  [128, 256, 512, 1024, 2048, 4096]);
const ERR = [0, 0.5862, 0.85, 1.0, 1.1636, 3.3132];
check('the error rule may widen a ring by one doubling', MAX_RANGE_WIDENING, 2);
checkEq('(k) with the contract\'s own example errors at 2 000 px/m/m',
  lodRanges(128, 6, ERR, 2000).map((v) => Math.round(v * 1e4) / 1e4),
  [256, 512, 1000, 1163.6, 3313.2, 4096]);
// …and the two the cap holds are exactly the two the rule asked too much for:
// 586.2 / 128 = 4.6 doublings' worth and 850 / 256 = 3.3.
checkEq('…the levels the cap held, and what they had asked for',
  [0, 1].map((i) => [Math.round((ERR[i + 1] * 2000) / MAX_PIXEL_ERROR * 10) / 10,
                     128 * (1 << i) * MAX_RANGE_WIDENING]),
  [[586.2, 256], [850, 512]]);
/**
 * (l) THE LADDER IS MONOTONE BY CONSTRUCTION UNDER THE CAP — derived in the
 * docstring, measured here on the shape that used to invert it: a huge error at
 * level 1 beside a small one at level 2. The error term is err · 200 / 2 =
 * err · 100, so [1000, 300] against geometric rings of [128, 256] and caps of
 * [256, 512].
 */
const HOSTILE = [0, 10, 3];
checkEq('(l) the hostile error list, capped', lodRanges(128, 3, HOSTILE, 200),
  [256, 300, 512]);
/**
 * THE LADDER AS IT WAS BEFORE THE CAP, written out from its own arithmetic
 * rather than by calling the shipped function — `MAX_RANGE_WIDENING` cannot be
 * turned off from outside, and a red probe that asked the shipped code to
 * misbehave would prove nothing anyway.
 *
 * `monotone` is the repair line the old `lodRanges` ran afterwards: off here in
 * (l), where the point is that the raw terms really do invert, and ON in [14],
 * which reproduces the world that overran `MAX_NODES` and therefore needs the
 * old function's answer to the digit.
 */
const uncappedLadder = (min, levels, err, scale, monotone = false) => {
  const out = [];
  for (let i = 0; i < levels; i += 1) {
    let r = min * (1 << i);
    const e = err?.[i + 1] ?? 0;
    if (min > 0 && scale > 0 && e > 0) r = Math.max(r, (e * scale) / MAX_PIXEL_ERROR);
    if (monotone && i > 0 && r < out[i - 1]) r = out[i - 1];
    out.push(r);
  }
  return out;
};
// RED: level 1's ring starts INSIDE level 0's as soon as the cap is gone.
const hostileRaw = uncappedLadder(128, 3, HOSTILE, 200);
checkEq('…RED: uncapped, the same list inverts the ladder', hostileRaw,
  [1000, 300, 512]);
check('…RED: by this many metres, level 1 starting inside level 0',
  hostileRaw[0] - hostileRaw[1], 700);
// …and the capped ladder cannot: range[i] ≤ 2·g_i = g_(i+1) ≤ range[i+1].
const capMono = (err, scale) => {
  const r = lodRanges(128, 6, err, scale);
  return r.every((v, i) => (i === 0 || v >= r[i - 1])
    && v <= 128 * (1 << i) * MAX_RANGE_WIDENING + 1e-9);
};
checkEq('…while every capped ladder is monotone and inside one doubling',
  [capMono(ERR, 2000), capMono(HOSTILE, 200), capMono([0, 9, 9, 9, 9, 9], 5000)],
  [true, true, true]);
checkEq('(m) a flat world has no ranges', lodRanges(0, 6, ERR, 2000), [0, 0, 0, 0, 0, 0]);

/**
 * (m2) THE ERROR LIST IS TAKEN OVER *ALL* TILES — `levelErrorsFrom`, and what
 *     an incomplete `tile_stats` costs.
 *
 * `GET /play/heightfield` ships at most `TILE_STATS_MAX` = 64 tile statistics
 * and says so through `tile_stats_complete`; the rest is fetched from
 * `GET /play/heightfield/stats`. The rule below takes a MAXIMUM per level, so
 * a missing tile is not a small contribution but no contribution at all: the
 * ladder above is then built from the roughness of the first 64 tiles alone.
 *
 * THE FIXTURE — 100 tiles keyed `"i,0"`, i = 0…99, in the server's own order
 * (`sorted(tile_index())` is by tx, then tz), each with the five mip errors
 *     err(i) = [ i/128, 2i/128, 3i/128, 4i/128, 5i/128 ]  metres
 * — dyadic, so every number here is exact in binary. The roughest tiles are
 * the LAST ones, which is the case that matters: the cap keeps the first 64.
 *
 * The node level L draws its vertices `2 · 2^L` m apart, so L = 1…5 are the
 * server's `mip_levels_m` [4, 8, 16, 32, 64] and L = 0 is the base lattice
 * with no error at all. Hence, per level, the maximum of column k over the
 * tiles held:
 *     all 100 tiles   -> i = 99: [0, 99/128, 198/128, 297/128, 396/128, 495/128]
 *                              = [0, 0.7734375, 1.546875, 2.3203125,
 *                                 3.09375, 3.8671875]
 *     first 64 only   -> i = 63: [0, 63/128, 126/128, 189/128, 252/128, 315/128]
 *                              = [0, 0.4921875, 0.984375, 1.4765625,
 *                                 1.96875, 2.4609375]
 * — 99/63 = 1.5714… times too small on EVERY level.
 *
 * WHAT THAT COSTS, through `lodRanges(128, 6, err, 500)`. The error term is
 * `err · 500 / MAX_PIXEL_ERROR` = `err · 250`, the geometric ring is
 * `128 · 2^i`, and the widening is capped at twice that:
 *     complete: 250 · [0.7734375, 1.546875, 2.3203125, 3.09375, 3.8671875]
 *             = [193.359375, 386.71875, 580.078125, 773.4375, 966.796875]
 *       i = 0: max(128,  min(193.359375, 256))  = 193.359375
 *       i = 1: max(256,  min(386.71875,  512))  = 386.71875
 *       i = 2: max(512,  min(580.078125, 1024)) = 580.078125
 *       i = 3: max(1024, min(773.4375,   2048)) = 1024      (geometry wins)
 *       i = 4: max(2048, min(966.796875, 4096)) = 2048      (geometry wins)
 *       i = 5: no err[6]                        = 4096
 *     capped:   250 · [0.4921875, 0.984375, 1.4765625, 1.96875, 2.4609375]
 *             = [123.046875, 246.09375, 369.140625, 492.1875, 615.234375]
 *       every one of them is BELOW its geometric ring, so the ladder collapses
 *       to the purely geometric [128, 256, 512, 1024, 2048, 4096].
 *
 * That is the defect in one number: with two thirds of the statistics missing
 * the finest ring reaches 128 m instead of 193.359375 m — the ground between
 * them is drawn one level coarser than the two-pixel budget allows, and
 * nothing in the picture says so.
 */
const statsFor = (n, from = 0) => {
  const m = new Map();
  for (let i = from; i < n; i += 1) {
    m.set(`${i},0`, { err: [1, 2, 3, 4, 5].map((f) => (i * f) / 128) });
  }
  return m;
};
const MIPS = [4, 8, 16, 32, 64];
const allStats = statsFor(100);
const cappedStats = statsFor(64);
check('(m2) the fixture has one statistic per tile', allStats.size, 100);
checkEq('…the level errors over ALL 100 tiles',
  levelErrorsFrom(allStats, MIPS, BASE, MAX_LOD_LEVELS),
  [0, 0.7734375, 1.546875, 2.3203125, 3.09375, 3.8671875]);
checkEq('…RED: over the first 64 alone, too small on every level',
  levelErrorsFrom(cappedStats, MIPS, BASE, MAX_LOD_LEVELS),
  [0, 0.4921875, 0.984375, 1.4765625, 1.96875, 2.4609375]);
checkEq('…and the ladder the complete list buys',
  lodRanges(128, MAX_LOD_LEVELS,
            levelErrorsFrom(allStats, MIPS, BASE, MAX_LOD_LEVELS), 500),
  [193.359375, 386.71875, 580.078125, 1024, 2048, 4096]);
checkEq('…RED: the capped list falls back to the purely geometric rings',
  lodRanges(128, MAX_LOD_LEVELS,
            levelErrorsFrom(cappedStats, MIPS, BASE, MAX_LOD_LEVELS), 500),
  [128, 256, 512, 1024, 2048, 4096]);
// The order the statistics arrive in cannot matter — it is a maximum. The
// 36 tiles the cap dropped are merged in the other way round and answer the
// same list, which is what `fillMissingStats` does per batch.
const merged = new Map([...statsFor(100, 64), ...cappedStats]);
checkEq('…merging the missing 36 in afterwards restores it, order-free',
  levelErrorsFrom(merged, MIPS, BASE, MAX_LOD_LEVELS),
  [0, 0.7734375, 1.546875, 2.3203125, 3.09375, 3.8671875]);
// The degenerate inputs of the rule: no statistics at all, and a base step
// whose doublings (6, 12, 24, 48, 96 m) are no declared mip level.
checkEq('…no statistics at all -> no error anywhere',
  levelErrorsFrom(new Map(), MIPS, BASE, MAX_LOD_LEVELS), [0, 0, 0, 0, 0, 0]);
checkEq('…a base step the server declares no level for -> the same',
  levelErrorsFrom(allStats, MIPS, 3, MAX_LOD_LEVELS), [0, 0, 0, 0, 0, 0]);

// ── [5] the selection ───────────────────────────────────────────────────────
console.log('\n[5] the quadtree — camera on the world corner');
const FLAT_BOUNDS = () => ({ min: 0, max: 0 });
const picked = selectLodNodes({
  x0: 0, z0: 0, x1: 2048, z1: 2048,
  leafM: 64, levels: 6, minLodDistance: 128,
  camX: 0, camY: 0, camZ: 0,
  boundsOf: FLAT_BOUNDS,
});
check('(n) nodes selected', picked.length, 16);
const perLevel = [0, 0, 0, 0, 0, 0];
for (const n of picked) perLevel[n.level] += 1;
checkEq('…per level', perLevel, [4, 3, 3, 3, 3, 0]);
const key = (n) => `${n.level}:${n.x},${n.z}`;
checkEq('the level-0 nodes', picked.filter((n) => n.level === 0).map(key).sort(),
  ['0:0,0', '0:0,64', '0:64,0', '0:64,64']);
checkEq('the level-4 nodes', picked.filter((n) => n.level === 4).map(key).sort(),
  ['4:0,1024', '4:1024,0', '4:1024,1024']);
checkEq('…and every one of them draws the whole patch',
  picked.every((n) => n.cells === PATCH_N), true);
for (const level of [0, 1, 2, 3, 4]) {
  const size = 64 * (1 << level);
  const corner = picked.find((n) => n.level === level && n.x === 0 && n.z === 0);
  const axis = picked.find((n) => n.level === level && n.x === size && n.z === 0);
  const diag = picked.find((n) => n.level === level && n.x === size && n.z === size);
  if (level === 0) check(`(o) level 0, the corner node (d = 0)`, corner.morph, 0);
  check(`(o) level ${level}, the axis node (d = size)`, axis.morph, 0);
  // The ramp of level L runs over the LAST HALF OF ITS OWN RING. Level 0's ring
  // starts at 0, so its ramp begins at 0.5·range[0] = size and the diagonal node
  // at d = size·√2 is (√2 − 1) of the way through it. Every level above has its
  // ring start at range[L−1] = size, so its ramp begins at 1.5·size — past the
  // 1.414·size the diagonal stands at, and the node has not begun to morph.
  check(`…the diagonal one (d = size·√2 = 1.414·size)`, diag.morph,
    level === 0 ? Math.SQRT2 - 1 : 0, 1e-12);
}
// (o2) AND THE RAMP ITSELF, on one node with nothing else in the world. The
// node [0, 128]² at level 1 owns the ring [128, 256] and its morph runs over
// the LAST HALF of that ring, [192, 256]. A camera on the x axis at 128 + d is
// exactly d from its east face:
//   d = 192 -> the ramp has not started        -> 0
//   d = 224 -> (224 − 192) / 64                -> 0.5
//   d = 256 -> the ring ends                   -> 1
for (const [camX, want] of [[320, 0], [352, 0.5], [384, 1]]) {
  const one = selectLodNodes({
    x0: 0, z0: 0, x1: 128, z1: 128, leafM: 64, levels: 2, minLodDistance: 128,
    camX, camY: 0, camZ: 0, boundsOf: FLAT_BOUNDS,
  });
  check(`(o2) the level-1 ramp at d = ${camX - 128} m`, one[0].morph, want, 1e-12);
}
// The ring boundary belongs to the COARSER level: at exactly `ranges[L-1]` the
// node is selected, not split. One metre nearer and it splits.
// The node is [0, 128]², so a camera at x = 256 is 128 m from its east face —
// exactly lodRange[0]. (A camera AT 128 would be touching the box and read 0.)
const onRing = selectLodNodes({
  x0: 0, z0: 0, x1: 128, z1: 128, leafM: 64, levels: 2, minLodDistance: 128,
  camX: 256, camY: 0, camZ: 0, boundsOf: FLAT_BOUNDS,
});
checkEq('a node at exactly lodRange[0] stays whole', onRing.map(key), ['1:0,0']);
check('…and it has not begun to morph', onRing[0].morph, 0);
const inside = selectLodNodes({
  x0: 0, z0: 0, x1: 128, z1: 128, leafM: 64, levels: 2, minLodDistance: 128,
  camX: 255.9, camY: 0, camZ: 0, boundsOf: FLAT_BOUNDS,
});
check('…and a decimetre nearer it splits into four', inside.length, 4);

// ── [6] crack-freeness ──────────────────────────────────────────────────────
console.log('\n[6] a fully morphed node IS its parent — no skirt, no crack');
// A field with a spike on every odd lattice point of level 1, so the two
// levels genuinely disagree between the parent's support points.
const CRACK = buildPyramid((x, z) => (((x / 8) % 2 === 1) ? 6 : 0),
                           0, 0, 8, 33, 33, MAX_LOD_LEVELS);
const RECT = null;
const childFull = { x: 0, z: 0, size: 256, level: 1, cells: PATCH_N, morph: 1 };
const childOwn = { x: 0, z: 0, size: 256, level: 1, cells: PATCH_N, morph: 0 };
const parent = { x: 0, z: 0, size: 512, level: 2, cells: PATCH_N, morph: 0 };
let edgeWorst = 0;
let ownWorst = 0;
for (let g = 0; g <= PATCH_N; g += 1) {
  const a = morphedVertex(childFull, g, 0, null, RECT, CRACK);
  // The parent's vertex at the SAME world x — the child's fully morphed
  // vertices land on even indices of its own grid, i.e. on the parent's every
  // other point, which is the parent's vertex g/2 rounded down.
  const b = morphedVertex(parent, Math.floor(g / 2), 0, null, RECT, CRACK);
  edgeWorst = Math.max(edgeWorst, Math.abs(a.x - b.x), Math.abs(a.y - b.y));
  const c = morphedVertex(childOwn, g, 0, null, RECT, CRACK);
  ownWorst = Math.max(ownWorst, Math.abs(c.y - b.y));
}
check('(p) the morphed edge lands exactly on the parent\'s', edgeWorst, 0);
check('(q) RED: unmorphed, the same edge stands off it by', ownWorst, 6);
// THE WORLD FRAME. A quadtree node is a power-of-two square and the frame is
// not, so the outermost nodes reach past it and the shader clamps their
// vertices onto it. Two things have to hold: nothing is drawn outside, and the
// clamp does not open a crack — a node and its parent clamp against the SAME
// rectangle, so they still meet.
const EXTENT = [0, 0, 200, 200];
let outside = 0;
let frameWorst = 0;
for (let g = 0; g <= PATCH_N; g += 1) {
  const a = morphedVertex(childFull, g, 0, null, RECT, CRACK, EXTENT);
  const b = morphedVertex(parent, Math.floor(g / 2), 0, null, RECT, CRACK, EXTENT);
  if (a.x < EXTENT[0] - 1e-9 || a.x > EXTENT[2] + 1e-9) outside += 1;
  frameWorst = Math.max(frameWorst, Math.abs(a.x - b.x), Math.abs(a.y - b.y));
}
check('no vertex is drawn outside the world frame', outside, 0);
check('…and the clamp opens no crack against the parent', frameWorst, 0);
check('the last vertex of a 256 m node sits on the 200 m frame',
  morphedVertex(childFull, PATCH_N, 0, null, RECT, CRACK, EXTENT).x, 200);

// ── [8] the morph belongs to the vertex ─────────────────────────────────────
console.log('\n[8] two neighbours describe ONE polyline — the morph is per vertex');
const RANGES = lodRanges(128, 6);
check('(w) λ(0)', lodLambda(0, RANGES), 0);
check('(w) λ(64)', lodLambda(64, RANGES), 0);
check('(w) λ(96)', lodLambda(96, RANGES), 0.5);
check('(w) λ(128) = one whole level', lodLambda(128, RANGES), 1);
check('(w) λ(192) — level 1\'s ramp only STARTS here', lodLambda(192, RANGES), 1);
check('(w) λ(224)', lodLambda(224, RANGES), 1.5);
check('(w) λ(256)', lodLambda(256, RANGES), 2);
check('(w) λ(400)', lodLambda(400, RANGES), 2.125);
check('(w) λ(512)', lodLambda(512, RANGES), 3);
// A 6 m step every other 4 m of z — see the docstring: the 2 m, 4 m and 8 m
// mips all read it differently, at the very points the two nodes meet on.
const SEAM = buildPyramid((x, z) => ((Math.floor(z / 4) % 2 === 1) ? 6 : 0),
                          0, 0, 2, 129, 129, MAX_LOD_LEVELS);
check('the 2 m mip reads the step at z = 4', pyramidHeight(SEAM, 128, 4, 0), 6);
check('…the 4 m mip too', pyramidHeight(SEAM, 128, 4, 1), 6);
check('…and the 8 m mip is flat there', pyramidHeight(SEAM, 128, 4, 2), 0);
const SEAM_CAM = { x: 0, y: 0, z: 0 };
const seamNodes = selectLodNodes({
  x0: 0, z0: 0, x1: 2048, z1: 2048,
  leafM: 64, levels: 6, minLodDistance: 128,
  camX: SEAM_CAM.x, camY: SEAM_CAM.y, camZ: SEAM_CAM.z,
  // An HONEST box: the field really reaches 6 m, and the guarantee "a vertex is
  // never nearer than its node's box" is what puts λ ≥ level on every vertex.
  boundsOf: () => ({ min: 0, max: 6 }),
});
const fine = seamNodes.find((n) => n.level === 0 && n.x === 64 && n.z === 0);
const coarse = seamNodes.find((n) => n.level === 1 && n.x === 128 && n.z === 0);
check('the fine node is a leaf at (64, 0)', fine ? fine.size : -1, 64);
check('…its neighbour at (128, 0) is one level up', coarse ? coarse.size : -1, 128);
check('both stand at morph 0 under the old per-node rule', fine.morph + coarse.morph, 0);
/** The height of a node's WEST edge polyline at world z — the line a neighbour
 *  really has to meet, not merely its vertices. */
function edgeYAt(node, vertexFn, z) {
  let prev = vertexFn(node, 0, 0);
  for (let j = 1; j <= PATCH_N; j += 1) {
    const cur = vertexFn(node, 0, j);
    if (cur.z > prev.z && z >= prev.z - 1e-9 && z <= cur.z + 1e-9) {
      const f = (z - prev.z) / (cur.z - prev.z);
      return prev.y * (1 - f) + cur.y * f;
    }
    prev = cur;
  }
  return null;
}
const newFine = (n, gx, gz) => lodVertex(n, gx, gz, SEAM, null, SEAM, null,
                                         SEAM_CAM, RANGES);
const oldFine = (n, gx, gz) => morphedVertex(n, gx, gz, SEAM, null, SEAM);
let sharedWorst = 0;
let seamWorst = 0;
let seamRed = 0;
for (let g = 0; g <= PATCH_N; g += 1) {
  const a = newFine(fine, PATCH_N, g);
  const onB = edgeYAt(coarse, (n, gx, gz) => newFine(n, gx, gz), a.z);
  if (onB !== null) seamWorst = Math.max(seamWorst, Math.abs(a.y - onB));
  if (g % 2 === 0) {
    // The vertices the two really SHARE: the fine node's every second one is
    // the coarse node's own. Same raw point, same finest height, same λ.
    const b = newFine(coarse, 0, g / 2);
    sharedWorst = Math.max(sharedWorst, Math.abs(a.x - b.x), Math.abs(a.z - b.z),
                           Math.abs(a.y - b.y));
  }
  const ra = oldFine(fine, PATCH_N, g);
  const onRb = edgeYAt(coarse, (n, gx, gz) => oldFine(n, gx, gz), ra.z);
  if (onRb !== null) seamRed = Math.max(seamRed, Math.abs(ra.y - onRb));
}
check('(x) every vertex the two SHARE agrees exactly', sharedWorst, 0, 1e-12);
check('…and the whole fine edge lies ON the coarse one', seamWorst, 0, 1e-9);
check('(y) RED: with one morph per node the same edge stood off by',
  seamRed, 3, 1e-12);

// ── [9] coverage over the whole compass ─────────────────────────────────────
console.log('\n[9] the selected nodes tile every visible piece of ground');

// (z1) the negative side of the tile lattice, by hand
const TILE_M = 256;
const bx = (x, size) => [Math.floor(x / TILE_M), Math.floor((x + size - 1e-6) / TILE_M)];
checkEq('(z1) the reported spot (-1550, -760) is tile (-7, -3)',
  [Math.floor(-1550 / TILE_M), Math.floor(-760 / TILE_M)], [-7, -3]);
checkEq('…and that tile spans x [-1792, -1536), z [-768, -512)',
  [-7 * TILE_M, -6 * TILE_M, -3 * TILE_M, -2 * TILE_M], [-1792, -1536, -768, -512]);
checkEq('…while Math.trunc would name the tile east AND south of it',
  [Math.trunc(-1550 / TILE_M), Math.trunc(-760 / TILE_M)], [-6, -2]);
checkEq('a 64 m node at (64, -128) covers tile (0, -1) alone',
  [bx(64, 64), bx(-128, 64)], [[0, 0], [-1, -1]]);
checkEq('a 256 m node at (-128, -128) covers the four tiles around the origin',
  [bx(-128, 256), bx(-128, 256)], [[-1, 0], [-1, 0]]);
checkEq('a 256 m node at (-256, -512) stops at its own tile',
  [bx(-256, 256), bx(-512, 256)], [[-1, -1], [-2, -2]]);

// The compass world — see the docstring. Negative-heavy on purpose.
const CX0 = -2560;
const CZ0 = -2560;
const CX1 = 2560;
const CZ1 = 2560;
const LEAF_M = PATCH_N * BASE;                  // 64
/** A rolling relief with two hills, deliberately NOT symmetric in x and z, so
 *  a direction-blind bug cannot hide behind a symmetric field. */
const CH = (x, z) => 9 * Math.sin(x / 197) * Math.cos(z / 151)
  + 14 * Math.exp(-(((x + 900) ** 2 + (z + 200) ** 2) / (2 * 320 ** 2)))
  + 22 * Math.exp(-(((x - 400) ** 2 + (z + 1400) ** 2) / (2 * 260 ** 2)));
/** Honest per-tile statistics: the extremes of the tile's OWN 2 m lattice,
 *  which is what the server ships and what the drawn surface stays inside. */
const cStats = new Map();
let gMin = 0;
let gMax = 0;
for (let tz = CZ0 / TILE_M; tz < CZ1 / TILE_M; tz += 1) {
  for (let tx = CX0 / TILE_M; tx < CX1 / TILE_M; tx += 1) {
    let mn = Infinity;
    let mx = -Infinity;
    for (let j = 0; j <= TILE_M / BASE; j += 1) {
      for (let i = 0; i <= TILE_M / BASE; i += 1) {
        const v = CH(tx * TILE_M + i * BASE, tz * TILE_M + j * BASE);
        if (v < mn) mn = v;
        if (v > mx) mx = v;
      }
    }
    cStats.set(`${tx},${tz}`, { min: mn, max: mx });
    gMin = Math.min(gMin, mn);
    gMax = Math.max(gMax, mx);
  }
}
const cGlobal = { min: gMin, max: gMax };
check('the compass world holds tiles', cStats.size, 20 * 20);

// The frustum, written out — three's own `setFromProjectionMatrix` (Gribb &
// Hartmann: the rows of the view-projection added to and subtracted from the
// w row) and its `intersectsBox` (the box corner FARTHEST along each plane
// normal). Reimplemented here for the same reason `tlodGrid` is: a check that
// imported the renderer's matrices could only prove them equal to themselves.
const FOV_DEG = 45;
const ASPECT = 16 / 9;
const NEAR_M = 0.2;
const FAR_M = 800;
const HAZE_M = 520;
const PIXELS = 1080;
const camPixelScale = PIXELS / (2 * Math.tan((FOV_DEG * Math.PI) / 360));
/** The server's own example error bounds (§ 4 of the E1 addendum), so the
 *  ranges the sweep runs against are the widened ones a real world produces. */
const CERR = [0, 0.5862, 0.85, 1.0, 1.1636, 3.3132];
const dot3 = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross3 = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
                          a[0] * b[1] - a[1] * b[0]];
const unit = (a) => { const l = Math.hypot(a[0], a[1], a[2]); return [a[0] / l, a[1] / l, a[2] / l]; };
function mul4(a, b) {
  const o = new Array(16).fill(0);
  for (let r = 0; r < 4; r += 1) {
    for (let c = 0; c < 4; c += 1) {
      let s = 0;
      for (let k = 0; k < 4; k += 1) s += a[r * 4 + k] * b[k * 4 + c];
      o[r * 4 + c] = s;
    }
  }
  return o;
}
function frustumPlanes(eye, fwd) {
  const zA = [-fwd[0], -fwd[1], -fwd[2]];
  const xA = unit(cross3([0, 1, 0], zA));
  const yA = cross3(zA, xA);
  const view = [xA[0], xA[1], xA[2], -dot3(xA, eye),
                yA[0], yA[1], yA[2], -dot3(yA, eye),
                zA[0], zA[1], zA[2], -dot3(zA, eye),
                0, 0, 0, 1];
  const f = 1 / Math.tan((FOV_DEG * Math.PI) / 360);
  const proj = [f / ASPECT, 0, 0, 0,
                0, f, 0, 0,
                0, 0, (FAR_M + NEAR_M) / (NEAR_M - FAR_M), (2 * FAR_M * NEAR_M) / (NEAR_M - FAR_M),
                0, 0, -1, 0];
  const m = mul4(proj, view);
  const row = (r) => [m[r * 4], m[r * 4 + 1], m[r * 4 + 2], m[r * 4 + 3]];
  const [m0, m1, m2, m3] = [row(0), row(1), row(2), row(3)];
  const add = (a, b, s) => [a[0] + s * b[0], a[1] + s * b[1], a[2] + s * b[2], a[3] + s * b[3]];
  return [add(m3, m0, 1), add(m3, m0, -1), add(m3, m1, 1), add(m3, m1, -1),
          add(m3, m2, 1), add(m3, m2, -1)]
    .map((p) => { const l = Math.hypot(p[0], p[1], p[2]);
                  return [p[0] / l, p[1] / l, p[2] / l, p[3] / l]; });
}
const boxSeen = (ps, x0, y0, z0, x1, y1, z1) => ps.every((p) =>
  p[0] * (p[0] > 0 ? x1 : x0) + p[1] * (p[1] > 0 ? y1 : y0)
  + p[2] * (p[2] > 0 ? z1 : z0) + p[3] >= 0);
const pointSeen = (ps, x, y, z) => ps.every((p) => p[0] * x + p[1] * y + p[2] * z + p[3] >= 0);

/** Where the eye stands for a heading: the orbit camera sits `dist` behind and
 *  above the point it looks at, exactly the arrangement `engine.ts` builds. */
function eyeFor(atX, atZ, yawDeg, pitchDeg, dist) {
  const a = (yawDeg * Math.PI) / 180;
  const pr = (pitchDeg * Math.PI) / 180;
  const fwd = [Math.sin(a) * Math.cos(pr), Math.sin(pr), Math.cos(a) * Math.cos(pr)];
  const ty = CH(atX, atZ) + 1.6;
  return { fwd, eye: [atX - fwd[0] * dist, ty - fwd[1] * dist, atZ - fwd[2] * dist] };
}
/**
 * One heading: select, then walk a polar fan of ground points and count the
 * VISIBLE ones no selected square owns.
 *
 * The fan is ±40° about the view axis (the horizontal half-angle of a 45°/16:9
 * frustum is atan(tan 22.5° · 16/9) = 36.4°, so it reaches past both edges)
 * and its rings grow geometrically, which puts samples where the nodes are
 * small as well as where they are large.
 */
function coverageAt(boundsFn, atX, atZ, yawDeg, pitchDeg, dist, drawn = null) {
  const { fwd, eye } = eyeFor(atX, atZ, yawDeg, pitchDeg, dist);
  const ps = frustumPlanes(eye, fwd);
  const select = (e) => selectLodNodes({
    x0: CX0, z0: CZ0, x1: CX1, z1: CZ1,
    leafM: LEAF_M, levels: MAX_LOD_LEVELS, minLodDistance: MIN_LOD_DISTANCE_M,
    camX: e[0], camY: e[1], camZ: e[2],
    boundsOf: boundsFn, levelErrorM: CERR, pixelScale: camPixelScale,
  });
  // The SHIPPED renderer draws the whole selection — there is no frustum test
  // in it since 2026-08-22. `drawn` is how a RED probe puts one back, or hands
  // the frame a list that was selected for a different camera.
  const picked = drawn ? drawn({ eye, fwd, ps, select, boundsFn }) : select(eye);
  const a = (yawDeg * Math.PI) / 180;
  const flat = Math.cos((pitchDeg * Math.PI) / 180);
  let miss = 0;
  let tested = 0;
  for (let r = 4; r <= HAZE_M; r *= 1.06) {
    for (let da = -40; da <= 40; da += 1) {
      const b = a + (da * Math.PI) / 180;
      const px = eye[0] + Math.sin(b) * r * flat;
      const pz = eye[2] + Math.cos(b) * r * flat;
      if (px < CX0 || px > CX1 || pz < CZ0 || pz > CZ1) continue;
      const py = CH(px, pz);
      if (!pointSeen(ps, px, py, pz)) continue;
      tested += 1;
      let owned = false;
      for (const n of picked) {
        if (px >= n.x && px <= n.x + n.size && pz >= n.z && pz <= n.z + n.size) {
          owned = true;
          break;
        }
      }
      if (!owned) miss += 1;
    }
  }
  return { miss, tested, nodes: picked.length };
}
/** The whole compass for one orbit setting: total misses, total samples, and
 *  the headings that failed, as ranges. */
function sweepCompass(boundsFn, atX, atZ, pitchDeg, dist, drawn = null) {
  let miss = 0;
  let tested = 0;
  let maxNodes = 0;
  const bad = [];
  for (let yaw = 0; yaw < 360; yaw += 1) {
    const r = coverageAt(boundsFn, atX, atZ, yaw, pitchDeg, dist, drawn);
    miss += r.miss;
    tested += r.tested;
    if (r.nodes > maxNodes) maxNodes = r.nodes;
    if (r.miss) bad.push(yaw);
  }
  const ranges = [];
  for (const y of bad) {
    const last = ranges[ranges.length - 1];
    if (last && y === last[1] + 1) last[1] = y;
    else ranges.push([y, y]);
  }
  return { miss, tested, headings: bad.length, maxNodes,
           ranges: ranges.map((r) => (r[0] === r[1] ? `${r[0]}` : `${r[0]}-${r[1]}`)).join(', ') };
}
const REPORTED_X = -1550;
const REPORTED_Z = -760;
const ORBITS = [[8, -15], [25, -25], [60, -35]];
const honest = (x, z, size) => nodeBounds(cStats, TILE_M, cGlobal, x, z, size);
let sweptSamples = 0;
let maxSweepNodes = 0;
for (const [dist, pitch] of ORBITS) {
  const r = sweepCompass(honest, REPORTED_X, REPORTED_Z, pitch, dist);
  sweptSamples += r.tested;
  maxSweepNodes = Math.max(maxSweepNodes, r.maxNodes);
  check(`(z2) 360 headings at ${dist} m / ${pitch}°: visible ground with no node`
    + ` (of ${r.tested} samples)`, r.miss, 0);
  check('…failing headings', r.headings, 0);
}
checkAbove('(z2) ground points sampled over the whole compass', sweptSamples, 2.5e6);
checkBelow('…and the largest selection any of those frames drew', maxSweepNodes, MAX_NODES);
console.log(`       (at most ${maxSweepNodes} pieces per frame, cap ${MAX_NODES})`);

// (z3) RED A — THE ONE-FRAME-LATE INSTANCE BUFFER, the defect that was measured
// on 2026-08-22. three.js uploads an InstancedBufferGeometry's dirty attributes
// in `projectObject` (`WebGLObjects.update`, "Update once per frame"), which
// runs over the whole scene BEFORE the first `object.onBeforeRender`. The
// selection used to be written in that hook, so the rows the card read were the
// PREVIOUS frame's while `instanceCount` was this frame's. Here the frame is
// drawn with the list selected one degree of yaw earlier — and because the old
// code also culled per piece, that list was a different set every frame.
const cullAll = (list, planes, boundsFn) => list.filter((n) => {
  const b = boundsFn(n.x, n.z, n.size);
  return boxSeen(planes, n.x, b.min, n.z, n.x + n.size, b.max, n.z + n.size);
});
const oneFrameLate = (deg, pitchDeg, dist) => ({ eye, fwd, ps, select, boundsFn }) => {
  const yawNow = (Math.atan2(fwd[0], fwd[2]) * 180) / Math.PI;
  const prev = eyeFor(REPORTED_X, REPORTED_Z, yawNow - deg, pitchDeg, dist);
  // What the card really had: the ROWS of the previous frame (selected and
  // culled against the previous camera), cut off at THIS frame's instance
  // count. Both halves are the shipped code of 2026-08-21 — the write in
  // `onBeforeRender`, the count read at draw time.
  const rows = cullAll(select(prev.eye), frustumPlanes(prev.eye, prev.fwd), boundsFn);
  const count = cullAll(select(eye), ps, boundsFn).length;
  return rows.slice(0, count);
};
const redLate = sweepCompass(honest, REPORTED_X, REPORTED_Z, -15, 8,
                             oneFrameLate(1, -15, 8));
// The floor is a dozen headings and five figures of ground, not the exact count:
// how many headings the staleness bites at is a property of the fixture's rings
// (25 under the capped ladder, 40 under the uncapped one — see the docstring).
checkAbove('(z3) RED A: the previous frame\'s rows under this frame\'s count'
  + ' lose ground at headings', redLate.headings, 12);
checkAbove('…and lose this many sampled points', redLate.miss, 1e4);
console.log(`       (RED A fails at headings ${redLate.ranges})`);
// …and the same staleness against the SHIPPED renderer, which culls nothing:
// the selection then depends on the camera POSITION alone, so a heading that is
// one frame old changes nothing at all and the count matches the rows.
const lateNoCull = (deg, pitchDeg, dist) => ({ fwd, select }) => {
  const yawNow = (Math.atan2(fwd[0], fwd[2]) * 180) / Math.PI;
  return select(eyeFor(REPORTED_X, REPORTED_Z, yawNow - deg, pitchDeg, dist).eye);
};
const lateNow = sweepCompass(honest, REPORTED_X, REPORTED_Z, -15, 8,
                             lateNoCull(1, -15, 8));
check('…while without the cull the very same staleness loses nothing',
  lateNow.miss, 0);

// (z4) RED B — THE CULL'S OWN BOX, where the server's per-tile statistics do not
// reach. `tile_stats` is capped (`TILE_STATS_MAX`), and `nodeBounds` folds a
// ZERO into the box for every tile it has no statistic for — the flat world an
// unindexed tile stands for. A tile that exists and carries hills but whose
// statistic was capped away therefore gets a box that does not contain its own
// ground, and the frustum test rejects it while it is on screen. That is the
// second reason the per-piece cull is gone rather than repaired.
const capped = new Map();
let kept = 0;
for (const [key, v] of cStats) {
  // Every fourth tile keeps its statistic — a cap that bites, in the pattern a
  // server-side cap really produces (the first N of an ordered scan).
  if (kept % 4 === 0) capped.set(key, v);
  kept += 1;
}
const cappedBounds = (x, z, size) => nodeBounds(capped, TILE_M, { min: 0, max: 0 },
                                                x, z, size);
const cullWithBox = ({ eye, ps, select }) => select(eye)
  .filter((n) => {
    const b = cappedBounds(n.x, n.z, n.size);
    return boxSeen(ps, n.x, b.min, n.z, n.x + n.size, b.max, n.z + n.size);
  });
const redBox = sweepCompass(honest, REPORTED_X, REPORTED_Z, -25, 25, cullWithBox);
checkAbove('(z4) RED B: the cull with a box the capped statistics do not cover'
  + ' loses ground at headings', redBox.headings, 20);
checkAbove('…and loses this many sampled points', redBox.miss, 1e3);
console.log(`       (RED B fails at headings ${redBox.ranges})`);

// (z5) stability — the other half of a flicker
for (const [dist, pitch] of [[8, -15], [25, -25]]) {
  let worst = 0;
  let prev = null;
  for (let yaw = 0; yaw < 360; yaw += 0.05) {
    const { eye } = eyeFor(REPORTED_X, REPORTED_Z, yaw, pitch, dist);
    const picked = selectLodNodes({
      x0: CX0, z0: CZ0, x1: CX1, z1: CZ1,
      leafM: LEAF_M, levels: MAX_LOD_LEVELS, minLodDistance: MIN_LOD_DISTANCE_M,
      camX: eye[0], camY: eye[1], camZ: eye[2],
      boundsOf: honest, levelErrorM: CERR, pixelScale: camPixelScale,
    });
    const set = new Set(picked.map((n) => `${n.level}:${n.x},${n.z}`));
    if (prev) {
      let diff = 0;
      for (const k of set) if (!prev.has(k)) diff += 1;
      for (const k of prev) if (!set.has(k)) diff += 1;
      if (diff > worst) worst = diff;
    }
    prev = set;
  }
  // Three simultaneous split/merge events, 5 entries each — the derivation of
  // the two centimetres the eye moves per step is in the docstring.
  checkBelow(`(z5) worst node churn per 0.05° of yaw at ${dist} m / ${pitch}°`,
    worst, 16);
}

// (z6) the selection knows no quadrant
const MIRROR_EXTENT = [-2048, -2048, 2048, 2048];
const flatBounds = () => ({ min: 0, max: 6 });
function selectAt(cx, cz) {
  return selectLodNodes({
    x0: MIRROR_EXTENT[0], z0: MIRROR_EXTENT[1], x1: MIRROR_EXTENT[2], z1: MIRROR_EXTENT[3],
    leafM: LEAF_M, levels: MAX_LOD_LEVELS, minLodDistance: MIN_LOD_DISTANCE_M,
    camX: cx, camY: 12, camZ: cz, boundsOf: flatBounds,
  });
}
const eastNorth = selectAt(777, -333);
const westSouth = selectAt(-777, 333);
checkAbove('(z6) the mirrored selections have nodes', eastNorth.length, 20);
const mirrored = eastNorth.map((n) => `${n.level}:${-n.x - n.size},${-n.z - n.size}`).sort().join('|');
checkEq('…and are the same tree through (x, z) -> (-x - size, -z - size)',
  mirrored === westSouth.map((n) => `${n.level}:${n.x},${n.z}`).sort().join('|'), true);

// (z7) the near window on its negative side — the pyramid switch is invisible
// on all four margin strips, not only the one [3](h) walks.
const NEG_TILE_N = 129;                 // 129 points at 2 m = one 256 m tile
const NEG_TILE = {
  origin_x: -1792, origin_z: -768, step_m: BASE, rows: NEG_TILE_N, cols: NEG_TILE_N,
  heights: Array.from({ length: NEG_TILE_N }, (_, j) =>
    Array.from({ length: NEG_TILE_N }, (_, i) => CH(-1792 + BASE * i, -768 + BASE * j))),
};
const NEG_OV_N = 81;                    // 81 points at 64 m over [-2560, 2560]
const NEG_OVERVIEW = {
  origin_x: CX0, origin_z: CZ0, step_m: 64, rows: NEG_OV_N, cols: NEG_OV_N,
  heights: Array.from({ length: NEG_OV_N }, (_, j) =>
    Array.from({ length: NEG_OV_N }, (_, i) => CH(CX0 + 64 * i, CZ0 + 64 * j))),
};
const NEG_COMPOSITE = { tileM: TILE_M, overview: NEG_OVERVIEW,
                        tiles: new Map([['-7,-3', NEG_TILE]]) };
check('the loaded tile really answers inside itself',
  heightAt(NEG_COMPOSITE, -1700, -700) - sampleWorldHeight(NEG_TILE, -1700, -700), 0);
// The window: the tile grown by max(16, 2 · 64) = 128 m, on the 2 m lattice.
const NEG_X0 = -1792 - 128;
const NEG_Z0 = -768 - 128;
const NEG_COLS = Math.floor((-1536 + 128 - NEG_X0) / BASE) + 1;
const NEG_ROWS = Math.floor((-512 + 128 - NEG_Z0) / BASE) + 1;
checkEq('the near window around tile (-7, -3)',
  [NEG_X0, NEG_Z0, NEG_COLS, NEG_ROWS], [-1920, -896, 257, 257]);
checkEq('…so its rectangle is',
  [NEG_X0, NEG_Z0, NEG_X0 + (NEG_COLS - 1) * BASE, NEG_Z0 + (NEG_ROWS - 1) * BASE],
  [-1920, -896, -1408, -384]);
const negNear = buildPyramid((x, z) => heightAt(NEG_COMPOSITE, x, z),
                             NEG_X0, NEG_Z0, BASE, NEG_COLS, NEG_ROWS, MAX_LOD_LEVELS);
const negFar = buildPyramid((x, z) => sampleWorldHeight(NEG_OVERVIEW, x, z),
                            CX0, CZ0, 64, NEG_OV_N, NEG_OV_N, MAX_LOD_LEVELS);
const STRIPS = [
  ['west', [-1920, -1794], [-896, -384]],
  ['east', [-1534, -1408], [-896, -384]],
  ['north', [-1920, -1408], [-896, -770]],
  ['south', [-1920, -1408], [-510, -384]],
];
for (const [name, [sx0, sx1], [sz0, sz1]] of STRIPS) {
  let worstStrip = 0;
  let n = 0;
  for (let z = sz0; z <= sz1; z += 2) {
    for (let x = sx0; x <= sx1; x += 2) {
      worstStrip = Math.max(worstStrip,
        Math.abs(pyramidHeight(negNear, x, z, 0) - pyramidHeight(negFar, x, z, 0)));
      n += 1;
    }
  }
  check(`(z7) near == far in the ${name} margin strip (${n} samples)`, worstStrip, 0, 1e-4);
}

// ── [7] the analytic click ──────────────────────────────────────────────────
console.log('\n[7] the click is solved against the field, not raycast');
const zeros = (n) => Array.from({ length: n }, () => new Array(n).fill(0));
const FLAT = {
  tileM: 16, overview: null,
  tiles: new Map([['0,0', { origin_x: 0, origin_z: 0, step_m: 2, rows: 9, cols: 9,
    heights: zeros(9) }]]),
};
const down = rayGroundHit(FLAT, 4, 10, 4, 0, -1, 0, { minY: 0, maxY: 0 });
check('(r) straight down onto flat ground: x', down.x, 4, 1e-9);
check('…y', down.y, 0, 1e-9);
check('…z', down.z, 4, 1e-9);
const RAMP = {
  tileM: 16, overview: null,
  tiles: new Map([['0,0', { origin_x: 0, origin_z: 0, step_m: 2, rows: 9, cols: 9,
    heights: Array.from({ length: 9 }, () =>
      Array.from({ length: 9 }, (_, i) => (i * 2) / 2)) }]]),
};
check('the ramp reads x/2 at (7, 0)', heightAt(RAMP, 7, 0), 3.5);
const slope = rayGroundHit(RAMP, 0, 10, 0, 1, -1, 0, { minY: 0, maxY: 8 });
check('(s) down the ramp: x', slope.x, 20 / 3, 1e-6);
check('…y', slope.y, 10 / 3, 1e-6);
check('…and the hit really lies ON the ground',
  slope.y - heightAt(RAMP, slope.x, slope.z), 0, 1e-6);
checkEq('(t) a ray into the sky misses',
  rayGroundHit(RAMP, 0, 10, 0, 0, 1, 0, { minY: 0, maxY: 8 }), null);
checkEq('…and one running flat above the whole world too',
  rayGroundHit(RAMP, 0, 10, 0, 1, 0, 0, { minY: 0, maxY: 8 }), null);
const under = rayGroundHit(RAMP, 4, 1, 0, 0, -1, 0, { minY: 0, maxY: 8 });
check('(u) a ray starting under the ground hits at its own origin, y', under.y, 1, 1e-9);
check('…at x', under.x, 4, 1e-9);
checkEq('(v) no field at all is a miss',
  rayGroundHit(null, 0, 10, 0, 0, -1, 0, { minY: 0, maxY: 0 }), null);

// ── [10] the shading normal ─────────────────────────────────────────────────
console.log('\n[10] the shading normal is a function of the ground, not of the camera');
/** One axis of the fixture: period 8, 1 m tall, flat over the two lattice
 *  points on each side of its crest — see the docstring. */
const rung = (u) => {
  const i = Math.round(u / 2);
  return ((i % 4) + 4) % 4 >= 2 ? 1 : 0;
};
const RELIEF = (x, z) => rung(x) + rung(z);
const relPyr = buildPyramid(RELIEF, 0, 0, 2, 65, 65, MAX_LOD_LEVELS);
const relRect = [0, 0, 128, 128];
const SPAN = 2;
// (aa) the fixture is what the derivation says it is
checkEq('(aa) the lattice column reads 0,0,1,1,0,0,1,1',
  [0, 1, 2, 3, 4, 5, 6, 7].map((i) => rung(i * 2)), [0, 0, 1, 1, 0, 0, 1, 1]);
checkEq('…the level steps', relPyr.levels.map((l) => l.step), [2, 4, 8, 16, 32, 64]);
check('…level 1 is a triangle wave of period 8: h(36) − h(28)',
  pyramidHeight(relPyr, 36, 32, 1) - pyramidHeight(relPyr, 28, 32, 1), 0, 0);
let flatL2 = 0;
for (let x = 24; x <= 48; x += 1) flatL2 = Math.max(flatL2,
  Math.abs(pyramidHeight(relPyr, x, 32, 2) - pyramidHeight(relPyr, 24, 32, 2)));
check('…and level 2 is dead flat', flatL2, 0, 0);
// (bb) the normal at the crest flank, by hand
const nCrest = fragmentNormal(relPyr, relRect, null, 35, 35, SPAN);
const S18 = Math.sqrt(18);
check('(bb) n.x at (35, 35)', nCrest.x, -1 / S18, 1e-12);
check('…n.y', nCrest.y, 4 / S18, 1e-12);
check('…n.z', nCrest.z, -1 / S18, 1e-12);
const degOff = (n) => (Math.acos(Math.min(Math.max(n.y, -1), 1)) * 180) / Math.PI;
check('…the tilt from the vertical, degrees', degOff(nCrest), 19.4712206344, 1e-9);

/** The 200 cameras: 8 azimuths × 25 distances from 8 m to 1 000 m, as offsets
 *  from the ground point. Only their DISTANCE can reach the old law, so the
 *  sweep is written as one. */
const CAMS = [];
for (let a = 0; a < 8; a += 1) {
  for (let k = 0; k < 25; k += 1) {
    const d = 8 * (1000 / 8) ** (k / 24);
    const phi = (a * Math.PI) / 4;
    const pitch = 0.3 + 0.05 * a;
    CAMS.push([Math.cos(phi) * Math.cos(pitch) * d, Math.sin(pitch) * d,
               Math.sin(phi) * Math.cos(pitch) * d]);
  }
}
const NRANGES = lodRanges(MIN_LOD_DISTANCE_M, MAX_LOD_LEVELS);
check('the sweep crosses the morph ramps of levels 0…3, λ(1000)',
  lodLambda(1000, NRANGES), 3 + (1000 - 768) / 256, 1e-12);

/** THE OLD LAW, rebuilt from its own arithmetic: the vertex's morph pair,
 *  differenced at each span on the mip level that span names, blended by
 *  `f = λ − ⌊λ⌋`. `d` is the vertex's distance to the CAMERA — the whole
 *  defect in one argument. */
function oldNormal(x, z, d) {
  const lam = lodLambda(d, NRANGES);
  const level = Math.max(0, Math.min(Math.floor(lam), MAX_LOD_LEVELS - 1));
  const t = lam - level;
  const k = Math.min(Math.floor(t), MAX_LOD_LEVELS - 1);
  const f = t - k;
  const e1 = SPAN * 2 ** level * 2 ** k;
  const e2 = e1 * 2;
  const at = (px, pz, e) => gpuHeightAt(relPyr, relRect, null, px, pz, e);
  const one = (e) => {
    const hx = at(x + e, z, e) - at(x - e, z, e);
    const hz = at(x, z + e, e) - at(x, z - e, e);
    const len = Math.hypot(hx, 2 * e, hz);
    return [-hx / len, (2 * e) / len, -hz / len];
  };
  const [ax, ay, az] = one(e1);
  const [bx, by, bz] = one(e2);
  const mx = ax + (bx - ax) * f;
  const my = ay + (by - ay) * f;
  const mz = az + (bz - az) * f;
  const len = Math.hypot(mx, my, mz);
  return { x: mx / len, y: my / len, z: mz / len };
}

// The sun of `engine.ts` at 18:00 — the numbers, not a stand-in.
const SUN = [Math.cos(Math.PI) * 60, Math.max(0.08, Math.sin(Math.PI)) * 80, 25];
const SUN_LEN = Math.hypot(...SUN);
check('the 18:00 sun stands at |(−60, 6.4, 25)|', SUN_LEN, Math.sqrt(4265.96), 1e-9);
check('…which is an elevation of', (Math.asin(SUN[1] / SUN_LEN) * 180) / Math.PI,
  5.6233, 1e-3);
const dotSun = (n) => (n.x * SUN[0] + n.y * SUN[1] + n.z * SUN[2]) / SUN_LEN;

let worstNew = 0;
let swingOld = 0;
let crossNew = 0;
let crossOld = 0;
let unlitNew = 0;
for (let j = 0; j < 8; j += 1) {
  for (let i = 0; i < 8; i += 1) {
    const px = 32 + i;
    const pz = 32 + j;
    const ref = fragmentNormal(relPyr, relRect, null, px, pz, SPAN);
    let litNewSeen = false;
    let darkNewSeen = false;
    let litOldSeen = false;
    let darkOldSeen = false;
    let minOldY = 1;
    let maxOldY = -1;
    for (const [ox, oy, oz] of CAMS) {
      const d = Math.hypot(ox, oy, oz);
      // (cc) the same ground point, asked from every camera in the sweep
      const n = fragmentNormal(relPyr, relRect, null, px, pz, SPAN);
      worstNew = Math.max(worstNew, Math.abs(n.x - ref.x), Math.abs(n.y - ref.y),
                          Math.abs(n.z - ref.z));
      if (dotSun(n) > 0) litNewSeen = true; else darkNewSeen = true;
      // (dd) and the same point under the old law, from the same camera
      const o = oldNormal(px, pz, d);
      minOldY = Math.min(minOldY, o.y);
      maxOldY = Math.max(maxOldY, o.y);
      if (dotSun(o) > 0) litOldSeen = true; else darkOldSeen = true;
    }
    swingOld = Math.max(swingOld,
      Math.abs(degOff({ y: minOldY }) - degOff({ y: maxOldY })));
    if (litNewSeen && darkNewSeen) crossNew += 1;
    if (litOldSeen && darkOldSeen) crossOld += 1;
    if (dotSun(ref) <= 0) unlitNew += 1;
  }
}
check(`(cc) the normal over ${CAMS.length} cameras × 64 probes — worst deviation`,
  worstNew, 0, 0);
check('(dd) RED: the old law swings, degrees', swingOld, 19.4712206344, 1e-9);
checkAbove('…which is the 16° class the live world was measured at', swingOld, 16);
check('(ee) probes standing in their own shadow at a 5.62° sun', unlitNew, 24);
check('…terminator crossings over the whole sweep, NEW law', crossNew, 0, 0);
check('…RED: the same count under the OLD law', crossOld, 24);
check('…i.e. this share of the ground flipped with the camera, %',
  (crossOld / 64) * 100, 37.5, 1e-9);

// (ff) the shipped chunks, read as strings — the same kind of pin as [1]
const nglsl = terrainLodNormalGlsl();
checkEq('(ff) the fragment normal names no camera', /cameraPosition/.test(nglsl), false);
checkEq('…no node attribute', /iNode/.test(nglsl), false);
checkEq('…no LOD range', /uTlodRange/.test(nglsl), false);
checkEq('…and no pixel footprint (none was needed)', /fwidth|dFdx|dFdy/.test(nglsl), false);
checkEq('…while the vertex chunk computes no normal any more',
  /tlodNormal\b/.test(glsl), false);
// (gg) the cost, counted
check('(gg) height taps of the fragment normal', nglsl.split('tlodHeight(').length - 1, 4);
check('…texel reads per ground fragment, 4 taps × the bilinear\'s 4',
  (nglsl.split('tlodHeight(').length - 1) * 4, 16);
// The VERTEX cost, after the T-junction fix of 2026-08-22. `tlodCompute` taps
// the height twice for the blend and asks `tlodMorphAt` — one tap each — once
// for the vertex itself and once per step of the block descent, which runs at
// most MAX_LOD_LEVELS − 1 = 5 times. Worst case 2 + 1 + 5 = 8 taps per vertex,
// still fewer than the 11 the shader carried before the shading normal moved to
// the fragment stage.
const compute = glsl.slice(glsl.indexOf('void tlodCompute'));
check('…height taps in tlodCompute itself', compute.split('tlodHeight(').length - 1, 2);
check('…and morph reads, one before the descent and one inside it',
  compute.split('tlodMorphAt(').length - 1, 2);
check('…one tap each, so the worst case per vertex is',
  2 + 1 + (MAX_LOD_LEVELS - 1), 8);
checkBelow('…which is still under what the vertex stage cost before', 8, 11);

// ── [11] the transition probe ───────────────────────────────────────────────
console.log('\n[11] a split does not move the ground — the transition probe');

/**
 * A relief with structure AT the 2 m lattice.
 *
 * The compass world `CH` of [9] is three smooth waves whose shortest period is
 * 151 m, so its 2 m lattice and its 4 m decimation answer almost the same
 * number and the morph has nothing to carry — (hh) measures that, and it is
 * why this section brings its own field instead of borrowing that one: a
 * transition probe run on `CH` reports a pop of 4e-3 m and would pass on a
 * renderer with no morph at all.
 */
const TR = (x, z) => 9 * Math.sin(x / 197) * Math.cos(z / 151)
  + 0.9 * Math.sin(x / 1.3) * Math.cos(z / 1.1)
  + 0.6 * Math.sin(x / 2.9 + z / 3.7)
  + 1.4 * Math.sin(x / 7.3) * Math.sin(z / 6.1);
const TR_X0 = -2048;
const TR_Z0 = -1280;
const TR_N = 513;                             // 1 024 m at 2 m
const trPyr = buildPyramid(TR, TR_X0, TR_Z0, BASE, TR_N, TR_N, MAX_LOD_LEVELS);
const TR_RECT = [TR_X0, TR_Z0, TR_X0 + (TR_N - 1) * BASE, TR_Z0 + (TR_N - 1) * BASE];
const TR_EXT = [-2560, -2560, 2560, 2560];
let mipGap = 0;
let chGap = 0;
for (let z = -1000; z <= -900; z += 2) {
  for (let x = -1700; x <= -1600; x += 2) {
    mipGap = Math.max(mipGap, Math.abs(pyramidHeight(trPyr, x, z, 0)
      - pyramidHeight(trPyr, x, z, 1)));
    chGap = Math.max(chGap, Math.abs(CH(x, z) - (CH(x - 2, z) + CH(x + 2, z)) / 2));
  }
}
checkAbove('(hh) the fixture: the 2 m and the 4 m mip really disagree, metres',
  mipGap, 0.5);
checkBelow('…RED: the compass world of [9] does not, so it cannot probe a morph',
  chGap, 0.01);

// Honest per-tile boxes over the stretch the path can see; everything else
// falls back to a range that contains the whole field, which culls nothing.
const trStats = new Map();
for (let tz = -6; tz <= -1; tz += 1) {
  for (let tx = -9; tx <= -4; tx += 1) {
    let mn = Infinity;
    let mx = -Infinity;
    for (let j = 0; j <= TILE_M / BASE; j += 1) {
      for (let i = 0; i <= TILE_M / BASE; i += 1) {
        const v = TR(tx * TILE_M + i * BASE, tz * TILE_M + j * BASE);
        if (v < mn) mn = v;
        if (v > mx) mx = v;
      }
    }
    trStats.set(`${tx},${tz}`, { min: mn, max: mx });
  }
}
// The amplitudes sum to 9 + 0.9 + 0.6 + 1.4 = 11.9, so ±12 contains the field
// everywhere — a bound, which is all `nodeBounds` may ever be.
const TR_GLOBAL = { min: -12, max: 12 };
const trBounds = (x, z, size) => nodeBounds(trStats, TILE_M, TR_GLOBAL, x, z, size);
/**
 * THE RINGS THIS SECTION AND [12] MEASURE AGAINST, derived by hand from the
 * error list `CERR` and the 1 080 px pixel scale
 * 1080 / (2 · tan 22.5°) = 1080 / 0.8284271 = 1303.6753, so the error term is
 * `err · 1303.6753 / 2 = err · 651.8377` and the cap is twice the geometric
 * ring:
 *   i=0: max(128,  min(0.5862 · 651.84 =  382.1, 256))  =  256   <- at the cap
 *   i=1: max(256,  min(0.85   · 651.84 =  554.1, 512))  =  512   <- at the cap
 *   i=2: max(512,  min(1.0    · 651.84 =  651.8, 1024)) =  651.8 <- the rule
 *   i=3: max(1024, min(1.1636 · 651.84 =  758.5, 2048)) = 1024
 *   i=4: max(2048, min(3.3132 · 651.84 = 2159.7, 4096)) = 2159.7 <- the rule
 *   i=5: max(4096, 0)                                   = 4096
 * Two rings still stand OUT of the doubling (652 and 2160), which is what makes
 * this fixture a fair test of `lodLambda`'s ring-anchored ramp: level 3 owns
 * [652, 1024] and must not begin morphing at 0.5 · 1024 = 512.
 */
const TR_RANGES = lodRanges(MIN_LOD_DISTANCE_M, MAX_LOD_LEVELS, CERR, camPixelScale);
checkEq('the rings this section measures against',
  TR_RANGES.map((r) => Math.round(r * 10) / 10), [256, 512, 651.8, 1024, 2159.7, 4096]);
checkEq('…two of them still out of the doubling, the rest held at the cap',
  TR_RANGES.map((r, i) => Math.round((r / (MIN_LOD_DISTANCE_M * (1 << i))) * 100) / 100),
  [2, 2, 1.27, 1, 1.05, 1]);

function trSelect(cam) {
  return selectLodNodes({
    x0: TR_EXT[0], z0: TR_EXT[1], x1: TR_EXT[2], z1: TR_EXT[3],
    leafM: LEAF_M, levels: MAX_LOD_LEVELS, minLodDistance: MIN_LOD_DISTANCE_M,
    camX: cam.x, camY: cam.y, camZ: cam.z,
    boundsOf: trBounds, levelErrorM: CERR, pixelScale: camPixelScale,
  });
}
/** One vertex of a node — the whole of `tlodCompute`, position and height. */
function trVertex(node, gx, gz, cam) {
  return lodVertex(node, gx, gz, trPyr, TR_RECT, trPyr, TR_EXT, cam, TR_RANGES);
}
/**
 * THE OLD λ, rebuilt from its own arithmetic: every level's ramp anchored at
 * the ORIGIN (`MORPH_START · range[i]`) instead of inside the level's own ring.
 * The two agree while the ranges double exactly and part company as soon as the
 * screen-space error rule widens one — which is why [12] uses it as a red probe.
 */
function redLambda(d, ranges) {
  let lam = 0;
  for (const r of ranges) {
    if (!(r > 0)) continue;
    const t = (d - MORPH_START * r) / ((1 - MORPH_START) * r);
    lam += t <= 0 ? 0 : t >= 1 ? 1 : t;
  }
  return lam;
}
/**
 * THE OLD `tlodCompute`, rebuilt: the morph coordinate read at the VERTEX
 * itself rather than at the block it snaps into, and the old λ. `morphedVertex`
 * is the shipped one — it takes t as an argument, so what this reimplements is
 * precisely the half that changed.
 */
function redVertex(node, gx, gz, pyr, rect, ext, cam, ranges) {
  const step = node.size / node.cells;
  let x0 = node.x + Math.min(gx, node.cells) * step;
  let z0 = node.z + Math.min(gz, node.cells) * step;
  if (ext) {
    x0 = Math.min(Math.max(x0, ext[0]), ext[2]);
    z0 = Math.min(Math.max(z0, ext[1]), ext[3]);
  }
  const y0 = gpuHeightAt(pyr, rect, pyr, x0, z0, 0);
  const d = Math.hypot(x0 - cam.x, y0 - cam.y, z0 - cam.z);
  const t = Math.max(0, ranges === null ? 0 : redLambda(d, ranges) - node.level);
  return { ...morphedVertex(node, gx, gz, pyr, rect, pyr, ext, t), t };
}

// (ii)/(jj) ONE parent, ONE child, ONE camera — where exactly do they differ?
// The two are built by hand: after the out-of-range rule of § A16.6 a rendered
// parent and a rendered child of it cannot both occur, and what is asked here is
// the VERTEX ARITHMETIC, which has to hold for any pair of levels that meet.
const trCam = { x: -1669.6, y: TR(-1669.6, -630.4) + 12, z: -630.4 };
const trParent = { x: -1280, z: -1152, size: 256, level: 2, cells: PATCH_N, morph: 0 };
const trChild = { x: -1280, z: -1152, size: 128, level: 1, cells: PATCH_N, morph: 0 };
let sharedWorstV = 0;
let oddOffset = 0;
let oddHeight = 0;
let redOffset = 0;
let redHeight = 0;
let deepest = 0;
for (let gz = 0; gz <= PATCH_N; gz += 1) {
  for (let gx = 0; gx <= PATCH_N; gx += 1) {
    const c = trVertex(trChild, gx, gz, trCam);
    deepest = Math.max(deepest, Math.floor(c.t));
    if (gx % 2 === 0 && gz % 2 === 0) {
      const p = trVertex(trParent, gx / 2, gz / 2, trCam);
      sharedWorstV = Math.max(sharedWorstV, Math.abs(c.x - p.x), Math.abs(c.z - p.z),
                              Math.abs(c.y - p.y));
      continue;
    }
    // The vertices the child ADDS are supposed to COLLAPSE onto their even twin
    // wherever the child is drawing on a lattice coarser than its own (k ≥ 1) —
    // that is what `mix(gi − gi mod m1, gi − gi mod m2, f)` does, and it does it
    // only if both use the SAME f.
    const e = trVertex(trChild, gx - (gx % 2), gz - (gz % 2), trCam);
    if (Math.floor(c.t) >= 1) {
      oddOffset = Math.max(oddOffset, Math.hypot(c.x - e.x, c.z - e.z));
      oddHeight = Math.max(oddHeight, Math.abs(c.y - e.y));
    }
    const rc = redVertex(trChild, gx, gz, trPyr, TR_RECT, TR_EXT, trCam, TR_RANGES);
    const re = redVertex(trChild, gx - (gx % 2), gz - (gz % 2), trPyr, TR_RECT,
                         TR_EXT, trCam, TR_RANGES);
    if (Math.floor(rc.t) >= 1) {
      redOffset = Math.max(redOffset, Math.hypot(rc.x - re.x, rc.z - re.z));
      redHeight = Math.max(redHeight, Math.abs(rc.y - re.y));
    }
  }
}
check('(ii) every vertex the parent and the child SHARE agrees', sharedWorstV, 0, 0);
checkAbove('…and the child really is drawing coarser than its own level here, k',
  deepest, 0);
// (jj) THE VERTICES THE CHILD ADDS. Reading the morph at the vertex's BLOCK
// instead of at the vertex (§ A16.6, `lodVertex`) makes every one of them land
// exactly on the twin it is meant to disappear into.
check('(jj) a vertex the child adds misses its own twin by, metres', oddOffset, 0, 0);
check('…and stands off the parent\'s surface by, metres', oddHeight, 0, 0);
checkAbove('…RED: with the morph read per VERTEX it missed by, metres',
  redOffset, 0.3);
checkAbove('…and hung this far off the parent\'s surface, metres', redHeight, 0.05);

// (kk) THE SWEEP: the surface before and after every transition, same camera.
/** The drawn mesh of one node — `tlodCompute` at all 1 089 vertices. */
function trMesh(node, cam) {
  const V = [];
  for (let gz = 0; gz <= PATCH_N; gz += 1) {
    const row = [];
    for (let gx = 0; gx <= PATCH_N; gx += 1) row.push(trVertex(node, gx, gz, cam));
    V.push(row);
  }
  return V;
}
function triY(a, b, c, x, z) {
  const den = (b.z - c.z) * (a.x - c.x) + (c.x - b.x) * (a.z - c.z);
  if (Math.abs(den) < 1e-12) return null;
  const l1 = ((b.z - c.z) * (x - c.x) + (c.x - b.x) * (z - c.z)) / den;
  const l2 = ((c.z - a.z) * (x - c.x) + (a.x - c.x) * (z - c.z)) / den;
  const l3 = 1 - l1 - l2;
  if (l1 < -1e-9 || l2 < -1e-9 || l3 < -1e-9) return null;
  return l1 * a.y + l2 * b.y + l3 * c.y;
}
/** The height a node's TRIANGLES answer at (x, z) — the surface, not the
 *  vertices. The morph slides a vertex up to `m2` cells towards the node's own
 *  corner, so the cell holding the point is looked for in a window that wide. */
function meshY(node, V, x, z) {
  const step = node.size / PATCH_N;
  const gi = Math.floor((x - node.x) / step);
  const gj = Math.floor((z - node.z) / step);
  for (let dj = -16; dj <= 16; dj += 1) {
    for (let di = -16; di <= 16; di += 1) {
      const i = gi + di;
      const j = gj + dj;
      if (i < 0 || j < 0 || i >= PATCH_N || j >= PATCH_N) continue;
      const t1 = triY(V[j][i], V[j + 1][i], V[j + 1][i + 1], x, z);
      if (t1 !== null) return t1;
      const t2 = triY(V[j][i], V[j + 1][i + 1], V[j][i + 1], x, z);
      if (t2 !== null) return t2;
    }
  }
  return null;
}
function trSurface(nodes, cam) {
  const cache = new Map();
  return (x, z) => {
    for (let i = 0; i < nodes.length; i += 1) {
      const n = nodes[i];
      if (x < n.x || x > n.x + n.size || z < n.z || z > n.z + n.size) continue;
      let V = cache.get(i);
      if (!V) { V = trMesh(n, cam); cache.set(i, V); }
      const y = meshY(n, V, x, z);
      if (y !== null) return y;
    }
    return null;
  };
}
const nkey = (n) => `${n.level}:${n.x},${n.z}`;
/** One walk: every frame where the node set changes, the OLD set's surface and
 *  the NEW set's surface are read at the same points from the same camera. The
 *  pop is reported in PIXELS as well as in metres, because a metre at 700 m is
 *  not the same defect as a metre at 30 m. */
function sweepTransitions(yawDeg, stepM, steps) {
  const ang = (yawDeg * Math.PI) / 180;
  const dx = Math.sin(ang);
  const dz = Math.cos(ang);
  let prevSet = null;
  let prevNodes = null;
  let transitions = 0;
  let worstM = 0;
  let worstPx = 0;
  let sumPx = 0;
  let samples = 0;
  for (let s = 0; s < steps; s += 1) {
    const cx = -1700 + dx * stepM * s;
    const cz = -600 + dz * stepM * s;
    const cam = { x: cx, y: TR(cx, cz) + 12, z: cz };
    const nodes = trSelect(cam);
    const set = new Set(nodes.map(nkey));
    if (prevSet) {
      const appeared = nodes.filter((n) => !prevSet.has(nkey(n)));
      if (appeared.length) {
        transitions += 1;
        const oldS = trSurface(prevNodes, cam);
        const newS = trSurface(nodes, cam);
        for (const n of appeared) {
          const q = n.size / 16;
          for (let j = 0; j <= 16; j += 1) {
            for (let i = 0; i <= 16; i += 1) {
              const x = n.x + i * q + 0.137;
              const z = n.z + j * q + 0.211;
              const oy = oldS(x, z);
              const ny = newS(x, z);
              if (oy === null || ny === null) continue;
              const d = Math.abs(ny - oy);
              const dist = Math.hypot(x - cam.x, cam.y - ny, z - cam.z);
              const px = (d * camPixelScale) / dist;
              worstM = Math.max(worstM, d);
              worstPx = Math.max(worstPx, px);
              sumPx += px;
              samples += 1;
            }
          }
        }
      }
    }
    prevSet = set;
    prevNodes = nodes;
  }
  return { transitions, worstM, worstPx, meanPx: sumPx / Math.max(samples, 1), samples };
}
// Heading 135° is east–north, the sector the shimmer was reported in.
const swept = sweepTransitions(135, 0.5, 120);
checkAbove('(kk) transitions over 60 m heading east–north', swept.transitions, 5);
checkAbove('…ground points compared across them', swept.samples, 1e4);
console.log(`       (worst pop ${swept.worstM.toFixed(4)} m, `
  + `mean ${swept.meanPx.toExponential(2)} px)`);
/**
 * THE BOUND, re-derived after § A16.6 (2026-08-22). It used to be a fraction of
 * `MAX_PIXEL_ERROR`: a split cost 0.101 m, a quarter of a pixel, and the check
 * asked for no more than that. It now costs NOTHING, and the reason is
 * structural rather than lucky — the drawn surface is a function of the world
 * point and the block it lies in, and neither of those knows which piece drew
 * it, so exchanging one piece for four cannot move the ground at all.
 *
 * SO THE BOUND IS THE PROBE'S OWN ARITHMETIC, and it is worth writing down what
 * that is, because it is not the double epsilon. `meshY` reads the surface by
 * BARYCENTRIC interpolation, dividing by the triangle's determinant `den`, and
 * a morphed patch is full of triangles the morph has collapsed: three vertices
 * on one line, `den` a rounding residue of products of world coordinates around
 * 1.7e3 m, i.e. (1.7e3)² · 2.2e−16 ≈ 6e−10 — just past the 1e−12 the probe
 * rejects a triangle at. Such a sliver returns weights whose noise is amplified
 * by the same tiny divisor, so the floor of the METHOD is nanometres and moves
 * with the fixture's rings, while the floor of the LAW is the 2.2e−13 that [12]
 * measures on vertices, where no division happens. The threshold is therefore
 * the micrometre [12](mm) calls "on the chain" — six orders under the 0.101 m
 * the old rule cost, and nine under the ground's own relief.
 */
check('…the worst of them, metres', swept.worstM, 0, 1e-6);
// 1 µm at the 10 m the nearest sample can stand from the eye is
// 1e-6 · 1303.7 / 10 = 1.3e-4 px, so a thousandth of a pixel is the matching
// ceiling on the other axis.
check('…and in PIXELS of a 45° / 1 080 px view', swept.worstPx, 0, 1e-3);

// (ll) NO COMPASS DIRECTION. Hypothesis (B) was a corner bias in the box
// distance — nodes east and north of the camera splitting earlier than their
// mirror images. Mirror the WORLD through the origin (every tile (tx, tz)
// becomes (−tx−1, −tz−1), because tile tx spans [tx·T, (tx+1)·T)) and walk the
// opposite heading: the selection must answer the mirrored tree at every step.
const mirStats = new Map();
for (const [k, v] of trStats) {
  const [tx, tz] = k.split(',').map(Number);
  mirStats.set(`${-tx - 1},${-tz - 1}`, v);
}
const mirBounds = (x, z, size) => nodeBounds(mirStats, TILE_M, TR_GLOBAL, x, z, size);
let mirrorWorst = 0;
let mirrorFrames = 0;
for (let s = 0; s < 120; s += 1) {
  const cx = -1700 + Math.sin((135 * Math.PI) / 180) * 0.5 * s;
  const cz = -600 + Math.cos((135 * Math.PI) / 180) * 0.5 * s;
  const cy = TR(cx, cz) + 12;
  const here = selectLodNodes({
    x0: TR_EXT[0], z0: TR_EXT[1], x1: TR_EXT[2], z1: TR_EXT[3],
    leafM: LEAF_M, levels: MAX_LOD_LEVELS, minLodDistance: MIN_LOD_DISTANCE_M,
    camX: cx, camY: cy, camZ: cz, boundsOf: trBounds,
    levelErrorM: CERR, pixelScale: camPixelScale,
  });
  const there = selectLodNodes({
    x0: TR_EXT[0], z0: TR_EXT[1], x1: TR_EXT[2], z1: TR_EXT[3],
    leafM: LEAF_M, levels: MAX_LOD_LEVELS, minLodDistance: MIN_LOD_DISTANCE_M,
    camX: -cx, camY: cy, camZ: -cz, boundsOf: mirBounds,
    levelErrorM: CERR, pixelScale: camPixelScale,
  });
  const a = here.map((n) => `${n.level}:${-n.x - n.size},${-n.z - n.size}`).sort().join('|');
  const b = there.map(nkey).sort().join('|');
  if (a !== b) mirrorWorst += 1;
  mirrorFrames += 1;
}
check('(ll) frames whose mirror image is a different tree', mirrorWorst, 0);
checkAbove('…frames walked east–north and its mirror', mirrorFrames, 100);

// ── [12] the T-junction probe ───────────────────────────────────────────────
console.log('\n[12] no vertex hangs beside a neighbour\'s edge — the T-junction probe');

/** Distance from a point to an axis-aligned box, the shipped `boxDistance`
 *  rewritten for the red selection below. */
function redBoxDist(px, py, pz, x0, y0, z0, x1, y1, z1) {
  const dx = Math.max(x0 - px, 0, px - x1);
  const dy = Math.max(y0 - py, 0, py - y1);
  const dz = Math.max(z0 - pz, 0, pz - z1);
  return Math.sqrt(dx * dx + dy * dy + dz * dz);
}
/**
 * THE OLD SELECTION, rebuilt: split on the node's own distance and hand every
 * one of the four children the finer level, whether that child's own distance
 * is still inside the ring or not. `cells` is `PATCH_N` for all of them, since
 * a parent quadrant is exactly what this rule cannot express.
 */
function redSelect(o) {
  const out = [];
  const top = o.levels - 1;
  const ranges = lodRanges(o.minLodDistance, o.levels, o.levelErrorM, o.pixelScale);
  const visit = (x, z, level) => {
    const size = o.leafM * (1 << level);
    if (x >= o.x1 || z >= o.z1 || x + size <= o.x0 || z + size <= o.z0) return;
    const b = o.boundsOf(x, z, size);
    const d = redBoxDist(o.camX, o.camY, o.camZ,
                         x, b.min, z, x + size, b.max, z + size);
    if (level > 0 && ranges[level - 1] > 0 && d < ranges[level - 1]) {
      const half = size / 2;
      visit(x, z, level - 1);
      visit(x + half, z, level - 1);
      visit(x, z + half, level - 1);
      visit(x + half, z + half, level - 1);
      return;
    }
    out.push({ x, z, size, level, cells: PATCH_N,
               morph: Math.max(0, redLambda(d, ranges) - level) });
  };
  const rootSize = o.leafM * (1 << top);
  for (let rz = Math.floor(o.z0 / rootSize); rz <= Math.floor((o.z1 - 1e-6) / rootSize); rz += 1) {
    for (let rx = Math.floor(o.x0 / rootSize); rx <= Math.floor((o.x1 - 1e-6) / rootSize); rx += 1) {
      visit(rx * rootSize, rz * rootSize, top);
    }
  }
  return out;
}

/**
 * The four DRAWN edges of a piece, each as a chain of (along-axis, height)
 * points. The morph slides a vertex along the edge as well as across it, so the
 * chain is not a graph over the axis and the comparison below has to be a
 * distance to the chain rather than an evaluation at a coordinate — that is not
 * pedantry: measured with an evaluation, two IDENTICAL chains report 0.1 m
 * wherever the old rule folded one back on itself.
 */
function edgesOf(node, vertexFn, cam) {
  const c = node.cells;
  const line = (fn) => {
    const pts = [];
    for (let g = 0; g <= c; g += 1) pts.push(fn(g));
    return pts;
  };
  return {
    west: line((g) => { const v = vertexFn(node, 0, g, cam); return { a: v.z, y: v.y }; }),
    east: line((g) => { const v = vertexFn(node, c, g, cam); return { a: v.z, y: v.y }; }),
    north: line((g) => { const v = vertexFn(node, g, 0, cam); return { a: v.x, y: v.y }; }),
    south: line((g) => { const v = vertexFn(node, g, c, cam); return { a: v.x, y: v.y }; }),
  };
}
/** Distance from a point to a polygonal chain, in the (along, height) plane. */
function distToChain(pts, a, y) {
  let best = Infinity;
  for (let i = 0; i + 1 < pts.length; i += 1) {
    const dx = pts[i + 1].a - pts[i].a;
    const dy = pts[i + 1].y - pts[i].y;
    const len2 = dx * dx + dy * dy;
    let u = len2 > 0 ? ((a - pts[i].a) * dx + (y - pts[i].y) * dy) / len2 : 0;
    u = u < 0 ? 0 : u > 1 ? 1 : u;
    const d = Math.hypot(pts[i].a + u * dx - a, pts[i].y + u * dy - y);
    if (d < best) best = d;
  }
  return best;
}
/**
 * One camera: select, then walk every pair of pieces that share a stretch of
 * edge and ask how far each side's vertices stand off the other side's chain.
 * `triangles` counts the NON-DEGENERATE ones, `beyond` the pieces whose own
 * nearest point has already left their level's ring.
 */
function tjunctionAt(cam, selectFn, vertexFn, acc) {
  const nodes = selectFn(cam);
  const E = nodes.map((n) => edgesOf(n, vertexFn, cam));
  for (const n of nodes) {
    acc.triangles += n.cells * n.cells * 2;
    if (n.level < MAX_LOD_LEVELS - 1 && n.morph > 1 + 1e-12) acc.beyond += 1;
    if (n.morph < 0) acc.negative += 1;
  }
  for (let i = 0; i < nodes.length; i += 1) {
    for (let j = 0; j < nodes.length; j += 1) {
      if (i === j) continue;
      const A = nodes[i];
      const B = nodes[j];
      let pair = null;
      if (Math.abs(A.x + A.size - B.x) < 1e-9) {
        const lo = Math.max(A.z, B.z);
        const hi = Math.min(A.z + A.size, B.z + B.size);
        if (hi - lo > 1e-9) pair = [E[i].east, E[j].west, lo, hi];
      } else if (Math.abs(A.z + A.size - B.z) < 1e-9) {
        const lo = Math.max(A.x, B.x);
        const hi = Math.min(A.x + A.size, B.x + B.size);
        if (hi - lo > 1e-9) pair = [E[i].south, E[j].north, lo, hi];
      }
      if (!pair) continue;
      const [pa, pb, lo, hi] = pair;
      for (const [from, onto] of [[pa, pb], [pb, pa]]) {
        for (const p of from) {
          if (p.a < lo - 1e-9 || p.a > hi + 1e-9) continue;
          const d = distToChain(onto, p.a, p.y);
          if (d > acc.worst) acc.worst = d;
          if (d > 1e-6) acc.bad += 1;
          acc.tested += 1;
        }
      }
    }
  }
  acc.nodes += nodes.length;
  acc.frames += 1;
}
/** The whole sweep: the 60 m NE walk of (kk) plus all 24 headings of a
 *  15°-compass at its start, which is where the finding was reported. */
function tjunctionSweep(selectFn, vertexFn) {
  const acc = { worst: 0, bad: 0, tested: 0, nodes: 0, frames: 0,
                triangles: 0, beyond: 0, negative: 0 };
  for (let s = 0; s < 120; s += 1) {
    const cx = -1700 + Math.sin((135 * Math.PI) / 180) * 0.5 * s;
    const cz = -600 + Math.cos((135 * Math.PI) / 180) * 0.5 * s;
    tjunctionAt({ x: cx, y: TR(cx, cz) + 12, z: cz }, selectFn, vertexFn, acc);
  }
  for (let h = 0; h < 24; h += 1) {
    const a = (h * 15 * Math.PI) / 180;
    const cx = -1700 + Math.sin(a) * 30;
    const cz = -600 + Math.cos(a) * 30;
    tjunctionAt({ x: cx, y: TR(cx, cz) + 12, z: cz }, selectFn, vertexFn, acc);
  }
  return acc;
}
const redTrSelect = (cam) => redSelect({
  x0: TR_EXT[0], z0: TR_EXT[1], x1: TR_EXT[2], z1: TR_EXT[3],
  leafM: LEAF_M, levels: MAX_LOD_LEVELS, minLodDistance: MIN_LOD_DISTANCE_M,
  camX: cam.x, camY: cam.y, camZ: cam.z,
  boundsOf: trBounds, levelErrorM: CERR, pixelScale: camPixelScale,
});
const now = tjunctionSweep(trSelect, (n, gx, gz, cam) => trVertex(n, gx, gz, cam));
const before = tjunctionSweep(redTrSelect,
  (n, gx, gz, cam) => redVertex(n, gx, gz, trPyr, TR_RECT, TR_EXT, cam, TR_RANGES));
checkAbove('(mm) camera settings walked (120 m of path + 24 headings)', now.frames, 140);
checkAbove('…edge vertices measured against the neighbour\'s chain', now.tested, 3e6);
check('(mm) vertices standing off the neighbour\'s edge by more than 1 µm',
  now.bad, 0);
check('…and the worst of them, metres', now.worst, 0, 1e-9);
console.log(`       (worst ${now.worst.toExponential(2)} m over ${now.tested} tests)`);
checkAbove('(nn) RED: the old rule leaves this many hanging vertices',
  before.bad, 1e4);
checkAbove('…and the worst of them stands off by, metres', before.worst, 0.05);
console.log(`       (RED worst ${before.worst.toFixed(4)} m, `
  + `${before.bad} of ${before.tested} tests)`);
// (oo) THE OUT-OF-RANGE RULE ITSELF: `morph` is λ at the piece's nearest point
// minus its level, so `morph ≤ 1` says the piece lies inside its own ring.
check('(oo) pieces drawn at a level whose ring they have left', now.beyond, 0);
check('…and none with a negative morph either', now.negative, 0);
checkAbove('…RED: under the old rule this many were', before.beyond, 1e3);
// (pp) WHAT IT COSTS. The out-of-range quadrants draw a child-sized square at
// the parent's spacing — a quarter of the triangles the old rule spent on the
// same ground — so the far half of the ground gets cheaper, not dearer.
const triNow = Math.round(now.triangles / now.frames);
const triRed = Math.round(before.triangles / before.frames);
console.log(`       (${Math.round(now.nodes / now.frames)} pieces / `
  + `${triNow} triangles per frame, was `
  + `${Math.round(before.nodes / before.frames)} / ${triRed})`);
checkBelow('(pp) real triangles per frame, as a share of the old rule\'s',
  triNow / triRed, 1);

// ── [13] the flat world gets the rings too ──────────────────────────────────
console.log('\n[13] a level world is drawn by the rings, not by its roots');

/**
 * THE 3D-TEST WORLD, as the readout described it: a world frame of about 7 km,
 * no height areas, the location at (-10, 10). Its overview is level, so the
 * shortcut that was deleted on 2026-08-22 gave it `minLodDistance` 0 — every
 * range 0, nothing ever split, the whole world drawn from its roots.
 *
 * THE CALIBRATION IS HAND-DERIVED AND MATCHES THE PANEL. A leaf is
 * `PATCH_N · baseStep` = 32 · 2 = 64 m and the tree has 6 levels, so a root is
 * 64 · 2^5 = 2 048 m. The frame [-3500, 3500] reaches roots
 * floor(-3500/2048) = -2 up to floor(3499.999/2048) = 1, i.e. 4 per axis and
 * 16 in all — which is exactly the "16" the isolation panel read with the
 * frustum test switched off, and the 3 to 4 it read with it on were those of
 * the 16 that a 800 m / 45° frustum kept.
 */
const FLAT_EXT = [-3500, -3500, 3500, 3500];
const FLAT_AT = [-10, 10];
const flatLevel = () => ({ min: 0, max: 0 });
const flatSelect = (eye, minLod) => selectLodNodes({
  x0: FLAT_EXT[0], z0: FLAT_EXT[1], x1: FLAT_EXT[2], z1: FLAT_EXT[3],
  leafM: LEAF_M, levels: MAX_LOD_LEVELS, minLodDistance: minLod,
  camX: eye[0], camY: eye[1], camZ: eye[2],
  boundsOf: flatLevel, pixelScale: camPixelScale,
});
// The engine's own camera law (`scene/engine.ts`): pitch 18° at MIN_DIST 0.8 m,
// 62° at MAX_DIST 150 m, the eye `dist` behind and above the point it looks at.
const flatEye = (yawDeg, dist) => {
  const zoomK = Math.min(Math.max((dist - 0.8) / (150 - 0.8), 0), 1);
  const pitch = 18 + (62 - 18) * Math.sqrt(zoomK);
  const a = (yawDeg * Math.PI) / 180;
  const pr = (pitch * Math.PI) / 180;
  const fwd = [Math.sin(a) * Math.cos(pr), -Math.sin(pr), Math.cos(a) * Math.cos(pr)];
  return [FLAT_AT[0] - fwd[0] * dist, -fwd[1] * dist, FLAT_AT[1] - fwd[2] * dist];
};
const flatCam = flatEye(45, 12);
// (qq) the model IS the world the panel measured — before anything is asserted
// about the new rule.
const wasRoots = flatSelect(flatCam, 0);
check('(qq) the deleted shortcut drew the 7 km world as this many pieces',
  wasRoots.length, 16);
checkEq('…every one of them a 2 048 m root',
  [...new Set(wasRoots.map((n) => n.size))], [64 * 2 ** (MAX_LOD_LEVELS - 1)]);
// (rr) …and what the rings make of the same camera.
const nowRings = flatSelect(flatCam, MIN_LOD_DISTANCE_M);
checkAbove('(rr) the same camera with the rings, pieces', nowRings.length, 100);
checkBelow('…and still a three-digit count', nowRings.length, 1000);
console.log(`       (${wasRoots.length} pieces of 2048 m -> ${nowRings.length} pieces, `
  + `${[...new Set(nowRings.map((n) => n.size))].sort((a, b) => a - b).join('/')} m)`);
/**
 * (ss) NO PIECE IS WIDER THAN ITS OWN DISTANCE, and that is the ring structure
 * written as one number. `lodRange[i] = 128 · 2^i` and a leaf is 64 m, so a
 * whole node at level L has `size = 64 · 2^L` and is only emitted once its box
 * distance has reached `lodRange[L-1] = 128 · 2^(L-1) = 64 · 2^L` — the same
 * number. A level-0 leaf has no inner ring and is capped by the leaf size
 * instead. Under the deleted shortcut a piece 2 048 m wide stood at distance 0,
 * i.e. 32 leaves wide where the rule allows one.
 */
const ringBreaches = (picked, eye) => {
  let bad = 0;
  let worst = 0;
  for (const n of picked) {
    const d = Math.hypot(Math.max(n.x - eye[0], 0, eye[0] - (n.x + n.size)),
                         eye[1],
                         Math.max(n.z - eye[2], 0, eye[2] - (n.z + n.size)));
    if (d > HAZE_M) continue;
    const allowed = Math.max(LEAF_M, d);
    if (n.size > allowed + 1e-9) { bad += 1; worst = Math.max(worst, n.size / allowed); }
  }
  return { bad, worst };
};
check('(ss) pieces inside the haze wider than their own distance', 
  ringBreaches(nowRings, flatCam).bad, 0);
checkAbove('…RED: under the deleted shortcut, this many were',
  ringBreaches(wasRoots, flatCam).bad, 3);
console.log(`       (RED: the worst stood ${ringBreaches(wasRoots, flatCam).worst.toFixed(0)}x `
  + 'wider than the ring allows)');
// (tt) …and the SHAPED worlds keep the property, so it is the rule and not an
// accident of a level field.
for (const [name, picked, eye] of [
  ['the compass world', selectLodNodes({
    x0: CX0, z0: CZ0, x1: CX1, z1: CZ1,
    leafM: LEAF_M, levels: MAX_LOD_LEVELS, minLodDistance: MIN_LOD_DISTANCE_M,
    camX: REPORTED_X, camY: CH(REPORTED_X, REPORTED_Z) + 14, camZ: REPORTED_Z,
    boundsOf: honest, levelErrorM: CERR, pixelScale: camPixelScale,
  }), [REPORTED_X, CH(REPORTED_X, REPORTED_Z) + 14, REPORTED_Z]],
]) {
  check(`(tt) ${name}: pieces inside the haze wider than their distance`,
    ringBreaches(picked, eye).bad, 0);
}
// (uu) THE CEILING. Nothing is culled any more, so the whole frame is selected
// every frame — the number the instance buffer is allocated for has to hold it
// over every camera, not over the lucky one.
let flatMax = 0;
let flatFrames = 0;
for (const dist of [0.8, 3, 12, 40, 90, 150]) {
  for (let yaw = 0; yaw < 360; yaw += 5) {
    flatMax = Math.max(flatMax, flatSelect(flatEye(yaw, dist), MIN_LOD_DISTANCE_M).length);
    flatFrames += 1;
  }
}
checkAbove('(uu) camera settings swept over the flat 7 km world', flatFrames, 400);
checkBelow('…and the largest selection any of them produced', flatMax, MAX_NODES);
console.log(`       (flat world at most ${flatMax} pieces, compass world at most `
  + `${maxSweepNodes}, buffer ${MAX_NODES})`);

// ── [14] the ceiling coarsens, it does not truncate ─────────────────────────
console.log('\n[14] the widening is capped at one doubling, and the ceiling coarsens '
  + 'instead of dropping the tail');

/**
 * THE LIVE WORLD, by its numbers. `world_bounds` comes from
 * `core/world_ops.py` (every placed location's outline and every painted
 * polygon), the ground plate grows it by `ground.BASE_MARGIN_M` = 60 m, and
 * the error list is the per-level MAXIMUM of `heightfield.tile_stats` over the
 * tiles the client really holds — the 64-tile world-wide `index_stats_payload`
 * block plus the 25 tiles inside the 560 m load radius. Baked off a COPY of
 * `worlds/Anima Divide/world.db` through `heightfield.rasterize_tile` /
 * `tile_stats`, i.e. the server's own arithmetic and not a fetch.
 *
 * The boxes are FLAT here on purpose: that world's whole relief spans 5.4 m
 * (-2.0 … 3.4), which against a 1 538 m ring is a rounding error — so the
 * count below is a property of the RINGS and cannot be blamed on a hill.
 */
const LIVE_BOUNDS = { min_x: -7907.36, min_z: -6505.66, max_x: 8544.28, max_z: 7726.95 };
const LIVE_MARGIN_M = 60;                       // ground.BASE_MARGIN_M
const LIVE_EXT = [LIVE_BOUNDS.min_x - LIVE_MARGIN_M, LIVE_BOUNDS.min_z - LIVE_MARGIN_M,
                  LIVE_BOUNDS.max_x + LIVE_MARGIN_M, LIVE_BOUNDS.max_z + LIVE_MARGIN_M];
const LIVE_ERR = [0, 1.9913, 2.945, 3.7229, 3.5949, 4.3741];
const liveFlat = () => ({ min: 0, max: 0 });
/** `ranges` is how the red probes put the UNCAPPED ladder back: the shipped
 *  `lodRanges` can no longer produce it, and `LodSelectOpts.ranges` is the one
 *  door the selection has for rings it did not compute itself. */
const liveOpts = (eye, px, ranges) => ({
  x0: LIVE_EXT[0], z0: LIVE_EXT[1], x1: LIVE_EXT[2], z1: LIVE_EXT[3],
  leafM: LEAF_M, levels: MAX_LOD_LEVELS, minLodDistance: MIN_LOD_DISTANCE_M,
  camX: eye[0], camY: eye[1], camZ: eye[2], boundsOf: liveFlat,
  levelErrorM: LIVE_ERR, pixelScale: px / (2 * Math.tan((FOV_DEG * Math.PI) / 360)),
  ...(ranges ? { ranges } : {}),
});
/** The engine's camera law again, about an arbitrary point of the live frame. */
const liveEye = (yawDeg, dist, tx, tz) => {
  const zoomK = Math.min(Math.max((dist - 0.8) / (150 - 0.8), 0), 1);
  const pitch = (18 + (62 - 18) * Math.sqrt(zoomK)) * Math.PI / 180;
  const a = (yawDeg * Math.PI) / 180;
  return [tx + Math.sin(a) * Math.cos(pitch) * dist, Math.sin(pitch) * dist,
          tz + Math.cos(a) * Math.cos(pitch) * dist];
};
/**
 * Ground the selection does not own — a 256 m lattice over the WHOLE frame,
 * because the shipped rule culls nothing and therefore owes every square of
 * it. The haze half is reported apart: an uncovered sample nearer than 520 m
 * is not a coarser picture, it is sky.
 */
function uncovered(picked, eye) {
  let miss = 0;
  let tested = 0;
  let nearMiss = 0;
  let nearTested = 0;
  let nearest = Infinity;
  for (let z = LIVE_EXT[1] + 64; z < LIVE_EXT[3]; z += 256) {
    for (let x = LIVE_EXT[0] + 64; x < LIVE_EXT[2]; x += 256) {
      tested += 1;
      let owned = false;
      for (const n of picked) {
        if (x >= n.x && x <= n.x + n.size && z >= n.z && z <= n.z + n.size) {
          owned = true;
          break;
        }
      }
      const d = Math.hypot(x - eye[0], z - eye[2]);
      if (d <= HAZE_M) {
        nearTested += 1;
        if (!owned) { nearMiss += 1; nearest = Math.min(nearest, d); }
      }
      if (!owned) miss += 1;
    }
  }
  return { miss, tested, nearMiss, nearTested, nearest };
}

// (vv) THE CAPPED LADDER, at both viewports — the derivation is in the
// docstring, and the number the cap exists to refuse is asserted beside it.
const livePx = (px) => px / (2 * Math.tan((FOV_DEG * Math.PI) / 360));
const liveCam = liveEye(45, 12, REPORTED_X, REPORTED_Z);
const liveRanges = lodRanges(MIN_LOD_DISTANCE_M, MAX_LOD_LEVELS, LIVE_ERR, livePx(1280));
const liveRanges2160 = lodRanges(MIN_LOD_DISTANCE_M, MAX_LOD_LEVELS, LIVE_ERR,
                                 livePx(2160));
check('the pixel scale of a 1 280 px buffer at 45°', livePx(1280), 1545.0967, 1e-4);
check('(vv) what level 0 asked for, metres',
  Math.round(((LIVE_ERR[1] * livePx(1280)) / MAX_PIXEL_ERROR) * 10) / 10, 1538.4);
check('…and what the cap gives it', liveRanges[0], MIN_LOD_DISTANCE_M * MAX_RANGE_WIDENING);
checkEq('(vv) the capped ladder at 1 280 px',
  liveRanges.map((r) => Math.round(r * 10) / 10), [256, 512, 1024, 2048, 3379.2, 4096]);
checkEq('…and at 2 160 px, where level 4 reaches its cap too',
  liveRanges2160.map((r) => Math.round(r * 10) / 10), [256, 512, 1024, 2048, 4096, 4096]);
checkEq('…so the four inner rings do not depend on the buffer height at all',
  liveRanges.slice(0, 4), liveRanges2160.slice(0, 4));
checkEq('…and no ring stands more than one doubling out of the ladder',
  liveRanges.every((r, i) => r <= MIN_LOD_DISTANCE_M * (1 << i) * MAX_RANGE_WIDENING + 1e-9)
  && liveRanges2160.every((r, i) =>
    r <= MIN_LOD_DISTANCE_M * (1 << i) * MAX_RANGE_WIDENING + 1e-9), true);
// RED: the uncapped ladder is a different world — a 1 538 m innermost ring.
const liveUncapped = uncappedLadder(MIN_LOD_DISTANCE_M, MAX_LOD_LEVELS, LIVE_ERR,
                                    livePx(1280), true);
check('…RED: uncapped, lodRange[0] was, metres',
  Math.round(liveUncapped[0] * 10) / 10, 1538.4);
checkAbove('…RED: which is this many times the geometric 128 m',
  Math.round(liveUncapped[0] / MIN_LOD_DISTANCE_M), 11);

// (vv2) the pieces that follow from the capped ladder.
const live1280 = selectLodFitted(liveOpts(liveCam, 1280));
const live2160 = selectLodFitted(liveOpts(liveCam, 2160));
const perLv = (sel) => {
  const c = [0, 0, 0, 0, 0, 0];
  for (const n of sel.nodes) c[n.level] += 1;
  return c;
};
check('(vv2) pieces at the reported camera, 1 280 px', live1280.nodes.length, 372);
check('…and at 2 160 px', live2160.nodes.length, 390);
check('…the rings did not have to be coarsened for either',
  live1280.coarsenings + live2160.coarsenings, 0);
checkEq('…and levels 0…3 are the same count at both, ring for ring',
  perLv(live1280).slice(0, 4), perLv(live2160).slice(0, 4));
checkEq('…the whole per-level split at 1 280 px', perLv(live1280),
  [67, 58, 59, 65, 49, 74]);
checkEq('…and at 2 160 px, where only levels 4 and 5 move',
  perLv(live2160), [67, 58, 59, 65, 70, 71]);
check('…half-sized quadrants among the 372',
  live1280.nodes.filter((n) => n.cells === PATCH_N / 2).length, 92);
// RED: what the SAME camera drew before the cap — the uncapped rings handed in.
const liveRed1280 = selectLodNodes(liveOpts(liveCam, 1280, liveUncapped));
check('…RED: the uncapped ladder drew this many pieces there', liveRed1280.length, 2952);
check('…RED: of which finest-level (64 m) ones',
  liveRed1280.filter((n) => n.level === 0).length, 1914);

// (ww) RED — the uncapped world at a 2 160 px drawing buffer, WITHOUT the guard.
// The rings are handed in rather than asked for: `MAX_RANGE_WIDENING` is not a
// switch, and a probe that made the shipped function misbehave would measure the
// probe. The ceiling itself is a property of the SELECTION and has to stay
// proven for any ring ladder, capped or not.
const redRanges = uncappedLadder(MIN_LOD_DISTANCE_M, MAX_LOD_LEVELS, LIVE_ERR,
                                 livePx(2160), true);
checkEq('(ww) the uncapped ladder the red probe selects against',
  redRanges.map((r) => Math.round(r * 10) / 10),
  [2596, 3839.3, 4853.5, 4853.5, 5702.4, 5702.4]);
check('…where the raw level-3 term fell below level 2\'s and was raised',
  Math.round(((LIVE_ERR[4] * livePx(2160)) / MAX_PIXEL_ERROR) * 10) / 10, 4686.6);
const redCam = liveEye(45, 12, 3000, 3000);
const redRaw = selectLodNodes(liveOpts(redCam, 2160, redRanges));
const redCover = uncovered(redRaw, redCam);
check('(ww) RED: selectLodNodes alone stops at exactly the ceiling',
  redRaw.length, MAX_NODES);
checkAbove('…RED: frame samples it left with no ground at all',
  redCover.miss, 1000);
check(`…RED: of ${redCover.nearTested} samples inside the haze, uncovered`,
  redCover.nearMiss, 6);
checkBelow('…RED: and the nearest of those stood this far from the camera, m',
  Math.round(redCover.nearest), HAZE_M);

// (xx) the guard on the very same camera and the very same rings.
const redFit = selectLodFitted(liveOpts(redCam, 2160, redRanges));
checkBelow('(xx) selectLodFitted stays under the ceiling', redFit.nodes.length, MAX_NODES);
check('…by halving the rings this many times', redFit.coarsenings, 1);
const fitCover = uncovered(redFit.nodes, redCam);
check(`…and of the ${fitCover.tested} frame samples, uncovered`, fitCover.miss, 0);
check('…inside the haze, uncovered', fitCover.nearMiss, 0);
/**
 * HALVING IS A PURE RESCALING OF λ, which is what makes it safe for the seam.
 * `lodLambda` anchors each ramp inside its own ring — `s_i = range[i−1] +
 * MORPH_START · (range[i] − range[i−1])` — so halving every range halves every
 * `s_i` with it and `(d − s/2)/((r − s)/2) = (2d − s)/(r − s)`: the coarsened
 * λ at d is the honest λ at 2d, EXACTLY. Nothing about the morph's shape
 * changes, only how far out it happens, so the arguments of [8] and [12] carry
 * over unchanged. (The identity λ(range[i]) = i + 1 is NOT asserted here: this
 * world's error list collapses two rings to zero width — range[2] = range[3]
 * and range[4] = range[5] — and `lodLambda` steps over such a ring by design,
 * so λ skips a level there. Nothing is ever emitted at a zero-width level.)
 */
checkEq('…the coarsened rings are still monotone',
  redFit.ranges.every((r, i) => i === 0 || r >= redFit.ranges[i - 1]), true);
checkEq('…and are exactly the rings it started from, halved',
  redFit.ranges.every((r, i) => Math.abs(r - redRanges[i] / 2) < 1e-9), true);
let lamOff = 0;
for (let d = 0; d <= 4000; d += 7) {
  const a = lodLambda(d, redFit.ranges);
  const b = lodLambda(2 * d, redRanges);
  lamOff = Math.max(lamOff, Math.abs(a - b));
}
check('…so the coarsened λ(d) IS the honest λ(2d), worst deviation', lamOff, 0, 1e-12);
console.log(`       (${redRaw.length} truncated pieces, ${redCover.miss}/${redCover.tested} `
  + `frame samples with no ground -> ${redFit.nodes.length} coarsened pieces, 0 uncovered)`);

// (yy) …and it is a no-op wherever the honest rings already fit — the live
// world under the SHIPPED (capped) rings first, which is the case that used to
// need the guard and no longer does.
check('(yy) the live world, capped rings: coarsenings', live1280.coarsenings, 0);
check('…and the very list selectLodNodes returns',
  live1280.nodes.length, selectLodNodes(liveOpts(liveCam, 1280)).length);
const flatFit = selectLodFitted({
  x0: FLAT_EXT[0], z0: FLAT_EXT[1], x1: FLAT_EXT[2], z1: FLAT_EXT[3],
  leafM: LEAF_M, levels: MAX_LOD_LEVELS, minLodDistance: MIN_LOD_DISTANCE_M,
  camX: flatCam[0], camY: flatCam[1], camZ: flatCam[2],
  boundsOf: flatLevel, pixelScale: camPixelScale,
});
check('(yy) the level world: coarsenings', flatFit.coarsenings, 0);
check('…and its list too', flatFit.nodes.length, nowRings.length);
const compassOpts = {
  x0: CX0, z0: CZ0, x1: CX1, z1: CZ1,
  leafM: LEAF_M, levels: MAX_LOD_LEVELS, minLodDistance: MIN_LOD_DISTANCE_M,
  camX: REPORTED_X, camY: CH(REPORTED_X, REPORTED_Z) + 14, camZ: REPORTED_Z,
  boundsOf: honest, levelErrorM: CERR, pixelScale: camPixelScale,
};
const compassFit = selectLodFitted(compassOpts);
check('…the compass world: coarsenings', compassFit.coarsenings, 0);
check('…and its list too', compassFit.nodes.length, selectLodNodes(compassOpts).length);

// ── [15] THE WATER PYRAMID (Wasser v2, K-A E2) ──────────────────────────────
//
// The second field of the tiles gets a pyramid of its own, beside the height
// ones and over the SAME near window. This section pins the two decisions of
// that pyramid — the decimation rule and what happens to the dry sentinel —
// and the CPU twin `wlevelAt` the shader of K-A E3 will mirror.
//
// THE FIXTURE, a ramp with a dry tail, so every number is readable at a glance:
// one tile, origin (0,0), step 2, 9 x 9 support points at x, z in {0…16}, and
//
//     level[j][i] = i        for i <= 7      (i.e. the mirror is x/2)
//     level[j][8] = null                     (x = 16 carries no water)
//
// A LINEAR mirror is not a convenience here, it is the case the rule is chosen
// for: `water_level_at` interpolates LINEARLY between two knots, so a coarse
// lattice that is a SUBSET of the fine one carries the same surface — and that
// is exactly what the checks below measure.
console.log('\n[15] the water pyramid — decimation, the sentinel, and wlevelAt');
const WROW = [0, 1, 2, 3, 4, 5, 6, 7, null];
const WRASTER = emptyWaterRaster();
WRASTER.tileM = 256;
WRASTER.tiles.set('0,0', waterTileFrom(0, 0, 2, {
  level: Array.from({ length: 9 }, () => WROW.slice()),
}));
const WPYR = buildWaterPyramid((x, z) => rasterLevelAt(WRASTER, x, z),
  0, 0, 2, 9, 9, MAX_LOD_LEVELS);
// The chain: 9 -> 5 -> 3 -> 2 -> (1, too small to carry a surface), so FOUR
// levels at steps 2, 4, 8, 16 — the same `floor((n−1)/2)+1` the height pyramid
// walks, because it IS `buildPyramid`.
check('the chain ends where a level has under two points per axis',
  WPYR.levels.length, 4);
check('level 0 is the raster itself', WPYR.levels[0].step, 2);
check('…level 1 is twice as coarse', WPYR.levels[1].step, 4);
check('…level 3 is eight times', WPYR.levels[3].step, 16);
check('level 1 has 5 points per axis', WPYR.levels[1].cols, 5);
check('…level 2 has 3', WPYR.levels[2].cols, 3);
check('…level 3 has 2', WPYR.levels[3].cols, 2);
// DECIMATION IS A SUBSET. Level 1 keeps the base points 0, 2, 4, 6, 8, so its
// row is [0, 2, 4, 6, NaN] — every value is a base value, none is an average.
const wrow = (k) => {
  const lv = WPYR.levels[k];
  return Array.from({ length: lv.cols },
    (_, i) => WPYR.data[lv.row0 * WPYR.texW + i]);
};
check('level 1 keeps every SECOND base value, at index 1', wrow(1)[1], 2);
check('…at index 2', wrow(1)[2], 4);
check('…at index 3', wrow(1)[3], 6);
check('level 2 keeps every fourth', wrow(2)[1], 4);
// RED COUNTER-PROBE: a MEAN (box) filter would answer 6.5 at that same level-1
// texel — the average of the base pair (6, 7) — a mirror no profile describes
// and half a metre of invented water at the shore.
check('RED: a box filter would have put 6.5 there', (6 + 7) / 2, 6.5);
checkEq('…and the pyramid does not carry it', wrow(1)[3] === 6.5, false);
// THE SUBSET IS EXACT FOR A LINEAR MIRROR, which is the justification: level 1
// and level 2 answer the SAME number as level 0 between the support points.
check('level 0 at (6, 0)', wlevelAt(WPYR, 6, 0, 0), 3);
check('…level 1 answers the same', wlevelAt(WPYR, 6, 0, 1), 3);
check('…and level 2 as well', wlevelAt(WPYR, 6, 0, 2), 3);
check('…between two base points too, at (7, 0)', wlevelAt(WPYR, 7, 0, 0), 3.5);
// THE SENTINEL DECIMATES WITH THE LEVEL: a coarse texel is water exactly when
// its own base texel is. Base index 8 is dry, so level 1's index 4 is, and so
// on up the chain — one number, one book about where the water is.
checkEq('the dry base point is NaN', Number.isNaN(wrow(0)[8]), true);
checkEq('…and so is the level-1 texel that IS it', Number.isNaN(wrow(1)[4]), true);
checkEq('…and the level-2 one', Number.isNaN(wrow(2)[2]), true);
checkEq('a read on the dry point answers NaN',
  Number.isNaN(wlevelAt(WPYR, 16, 0, 0)), true);
checkEq('…on every level', Number.isNaN(wlevelAt(WPYR, 16, 0, 1)), true);
// THE MASKED MIX, at the pyramid this time. (14, 0) is the OUTERMOST written
// point; its eastern neighbour is dry and carries weight 0 there. Plain
// bilinear would answer NaN and the ring would lose its outer texel — which is
// the erosion finding of `waterRaster.waterBilinear`.
check('the outermost written point keeps its value', wlevelAt(WPYR, 14, 0, 0), 7);
checkEq('RED: the same mix without the mask is NaN',
  Number.isNaN(7 * 1 + NaN * 0), true);
checkEq('…and a WEIGHTED dry corner still answers NaN',
  Number.isNaN(wlevelAt(WPYR, 15, 0, 0)), true);
// THE PRICE, stated as the number it is: the ring loses half its texels per
// level, because the decimation keeps every second one. The outermost WRITTEN
// support point walks inward 14 -> 12 -> 8 -> 0 as the level coarsens, which is
// why the server's dilation guarantee (`WATER_RASTER_DILATION_STEPS`) is
// claimed for the BASE lattice and deliberately not above it.
const lastWritten = (k) => {
  const lv = WPYR.levels[k];
  let last = -1;
  for (let i = 0; i < lv.cols; i += 1) {
    if (!Number.isNaN(wrow(k)[i])) last = i * lv.step;
  }
  return last;
};
check('the outermost written x at level 0', lastWritten(0), 14);
check('…at level 1', lastWritten(1), 12);
check('…at level 2', lastWritten(2), 8);
check('…at level 3', lastWritten(3), 0);
// AND THE UPLOAD IS WIRED: the three water uniforms are bound beside the height
// ones, by the same one function every patched material goes through — and
// since E3 the WATER VARIANT of the program is what reads them (section [16]).
const bound = {};
bindTerrainLodUniforms(bound);
checkEq('the water TEXTURE is bound', bound.uTlodWater !== undefined, true);
checkEq('…its geometry', bound.uTlodWaterGeom !== undefined, true);
checkEq('…and its per-level lattice', bound.uTlodWaterLevel !== undefined, true);
checkEq('…and the height ones are still there',
  bound.uTlodNear !== undefined && bound.uTlodFar !== undefined, true);
// NO FAR TWIN, and there will not be one: the overview grid carries no water at
// all (§ A16.5), so a point outside the near window is "no water known here"
// rather than a mirror invented from a coarse raster.
checkEq('there is no far water pyramid', bound.uTlodWaterFar === undefined, true);

// ── [16] THE VERTEX LIFT (Wasser v2, K-A E3) ────────────────────────────────
//
// THE FIXTURE — one shore, hand-built from the shape the server's bake really
// leaves behind, on one 9 x 9 window at the 2 m base step (x = 0 … 16, and
// everything is constant in z so the row IS the world).
//
// The authored water is a lake whose OUTLINE runs at x = 10, level 1.0 (one
// knot, so the mirror is 1.0 everywhere), depth 2.0 m, shore ramp 4.0 m.
//
// EVERY NUMBER BELOW IS EXACT IN BINARY32, on purpose: the pyramids are
// Float32Arrays, so a fixture built out of tenths would be checked against
// values the arithmetic never produces (1.4 comes back as 1.3999999762) and
// the tolerances would hide the very drift they are there to catch.
//
//   THE MIRROR ROW, i.e. what `HeightModel.water_raster` writes. The raster is
//   dilated `WATER_RASTER_DILATION_STEPS` = 2 steps = 4 m past the outline
//   (`heightfield.py`), so it is written out to x = 14 and x = 16 is the dry
//   sentinel:
//
//       x     0    2    4    6    8   10   12   14   16
//       w   1.0  1.0  1.0  1.0  1.0  1.0  1.0  1.0  null
//
//   THE GROUND ROW, `h_final`, one number per bake stage:
//
//       x = 0 … 6   the CARVE at full depth:  level − depth = 1 − 2 = −1
//       x = 8       the shore ramp on its way up out of the bed:       0.0
//       x = 10      the outline, where the ramp has reached the mirror: 1.0
//       x = 12      the BANK CLAMP band, 2 m outside the outline. The rule
//                   (`HeightModel._bank_clamp`) is
//                       floor  = level + WATER_BANK_LIP_M = 1.0 + 0.1 = 1.1
//                       target = floor + (h − floor) · (d / shore_ramp)
//                   and for a natural bank of 1.5 at d = 2, ramp 4:
//                       target = 1.1 + (1.5 − 1.1) · 0.5 = 1.3
//                       h      = max(1.5, 1.3) = 1.5          → 1.5
//       x = 14      4 m outside, i.e. d = ramp, where the clamp's minimum has
//                   faded to `h` itself ("the band closes without a seam by
//                   construction", `_bank_clamp`) — so untouched meadow, and
//                   this stretch of it lies under the mirror:           0.75
//       x = 16      dry land:                                          3.0
//
//       x     0    2    4    6    8   10   12   14   16
//       h  −1.0 −1.0 −1.0 −1.0  0.0  1.0  1.5 0.75  3.0
//
// THE TWO PYRAMIDS DECIMATE AS SUBSETS (section [15]), so level 1 keeps the
// base points 0, 4, 8, 12, 16:
//
//       level 1   x:    0     4     8    12    16
//                 w:  1.0   1.0   1.0   1.0   null
//                 h: −1.0  −1.0   0.0   1.5   3.0
//
// (a) THE LIFT ITSELF: y = max(h, w), with the DRY SENTINEL falling through to
//     the ground. Derived from the rows above:
//
//       x = 4    h = −1.0, w = 1.0    → 1.0   (the bed lifts by 2 m)
//       x = 9    h = mix(0.0, 1.0, ½) = 0.5, w = 1.0 → 1.0
//       x = 10   h = 1.0, w = 1.0     → 1.0   (AT THE OUTLINE THE TWO HALVES
//                                              OF THE MAX MEET: the ramp has
//                                              arrived, so it does not matter
//                                              which branch wins)
//       x = 12   h = 1.5, w = 1.0     → 1.5   THE RING PROBE — the dilation
//                                              ring HAS a level here and the
//                                              terrain does NOT lift, because
//                                              the bank clamp put the ground
//                                              0.5 m over its own mirror
//       x = 14   h = 0.75, w = 1.0    → 1.0   …and here it DOES, by 0.25 m
//       x = 15   h = mix(0.75, 3.0, ½) = 1.875, w = mix(1.0, null, ½) = dry
//                                     → 1.875 (a WEIGHTED dry corner is dry)
//       x = 16   h = 3.0, w = dry     → 3.0
//
//     THE RING RULE, and it is not the one-liner it looks like. "A vertex in
//     the dilation ring lifts only where the mirror stands over the ground,
//     which the bank clamp rules out" is true AT THE OUTLINE and only there:
//     the clamp's minimum FADES linearly to the untouched ground over
//     `shore_ramp_m` and is exactly `h` again at `d = ramp`, while the ring is
//     a fixed `WATER_RASTER_DILATION_M` = 4 m whatever the ramp is. Solve the
//     clamp for the general case: a vertex at distance `d` outside the outline
//     is guaranteed not to lift iff
//         d / ramp  ≤  LIP / (LIP + level − h_natural)
//     — so for a bank 0.75 m under the mirror (LIP 0.1) that is the innermost
//     0.1/0.35 = 28.6 % of the band, and x = 14 (d = ramp, the outer edge) is
//     never covered for any ramp at all. With the DEFAULT 3 m ramp the ring is
//     a metre wider than the clamp band on top of that, so its outermost metre
//     has no clamp behind it whatsoever.
//     THIS IS NOT A DEFECT AND MUST NOT BE "FIXED" HERE: land lying
//     under the mirror beside its own water IS failure class F1
//     (`recherche-wasser-v2.md` § 2), and K-A answers it by raising the land
//     instead of floating the water. The lift is bounded twice over — by
//     `level − h` in height and by the 4 m dilation in width — and it is
//     exactly why the plan puts the bank clamp and the 16 m relief fade up for
//     removal in E6.
//
// (b) THE MIP IS THE HEIGHT'S MIP, AND THE MAX IS TAKEN PER LEVEL. At x = 14
//     the level-1 lattice has already lost the ring (its next support point,
//     x = 16, is the dry sentinel), so:
//
//       level 0:  h = 0.75,                    w = 1.0  → max = 1.0
//       level 1:  h = mix(1.5, 3.0, ½) = 2.25, w = dry  → max = 2.25
//
//     The shipped shape blends those two: y(f) = mix(1.0, 2.25, f), continuous,
//     y(0) = 1.0, y(0.001) = 1.00125. The OTHER order — blend the mirrors
//     first, then take one max — answers max(mix(0.75, 2.25, f),
//     maskedMix(1.0, dry, f)), and `maskedMix(1.0, dry, f)` is 1.0 at f = 0 and
//     dry for every f > 0, so it drops to 0.75 + 1.5·f the instant f leaves 0
//     (0.7515 at f = 0.001): a step of
//         1.0 − 0.75 = 0.25 m
//     in the drawn ground, AT the morph front, i.e. a shoreline that swims
//     against its own bed as the camera moves. That is the number this section
//     pins, and the reason for the order.
//
// (c) THE GATE. `nodeHasWater` decides which pieces get the lifting program.
//     Over a world of 256 m tiles with water in tile "1,0" alone:
//       - a 64 m piece at x = 0 touches tile 0 only              → dry
//       - a 64 m piece at x = 256 touches tile 1                 → wet
//       - a 64 m piece at x = 192 REACHES x = 256, and the vertex it puts
//         there is filed under tile 1 by `tileKeyAt`             → wet
//     The third is the whole crack argument: the closed rectangle
//     (`floor((x + size) / tileM)`, no epsilon) is what makes a vertex shared
//     by two pieces belong to BOTH of their tile spans, so both pieces run the
//     same program and cannot disagree about where it sits. The RED probe
//     below re-derives the same span with `nodeBounds`' `− 1e-6` and shows it
//     answering "one tile" for the piece at 192 — the crack the epsilon opens.
console.log('\n[16] the vertex lift — max(h, w_level), and who pays for it');

const SHORE_H = [-1, -1, -1, -1, 0, 1, 1.5, 0.75, 3];
const SHORE_W = [1, 1, 1, 1, 1, 1, 1, 1, null];
const shoreH = (x) => SHORE_H[Math.max(0, Math.min(8, Math.round(x / 2)))];
const shoreNear = buildPyramid((x) => shoreH(x), 0, 0, 2, 9, 9, MAX_LOD_LEVELS);
const shoreRaster = emptyWaterRaster();
shoreRaster.tileM = 256;
shoreRaster.tiles.set('0,0', waterTileFrom(0, 0, 2, {
  level: Array.from({ length: 9 }, () => SHORE_W.slice()),
}));
const shoreWater = buildWaterPyramid((x, z) => rasterLevelAt(shoreRaster, x, z),
  0, 0, 2, 9, 9, MAX_LOD_LEVELS);
const SHORE_RECT = [0, 0, 16, 16];
/** The drawn height of ONE tap: the two shipped twins composed exactly as
 *  `tlodCompute` composes them for one member of the morph pair. */
const liftAt = (x, nodeStep) => liftedHeight(
  gpuHeightAt(shoreNear, SHORE_RECT, null, x, 0, nodeStep),
  gpuWaterAt(shoreWater, SHORE_RECT, x, 0, nodeStep));
const wrow16 = (pyr, k, n) => {
  const lv = pyr.levels[k];
  return Array.from({ length: n }, (_, i) => pyr.data[lv.row0 * pyr.texW + i]);
};

// The fixture is what the docstring says it is, before anything is read off it.
checkEq('(a) the level-1 mirror keeps every second base value',
  wrow16(shoreWater, 1, 5).map((v) => (Number.isNaN(v) ? 'dry' : v)),
  [1, 1, 1, 1, 'dry']);
checkEq('…and the level-1 ground does too', wrow16(shoreNear, 1, 5),
  [-1, -1, 0, 1.5, 3]);

// (a) the lift, probe by probe
check('the bed at x = 4 (−1) lifts onto its mirror', liftAt(4, 2), 1);
check('…and so does the shore ramp at x = 9 (0.5)', liftAt(9, 2), 1);
check('AT THE OUTLINE x = 10 the two halves meet — 1.0 either way',
  liftAt(10, 2), 1);
check('THE RING PROBE x = 12: the level is there, the bank is over it',
  liftAt(12, 2), 1.5);
checkEq('…so what is drawn is the GROUND and not the mirror',
  liftAt(12, 2) === shoreH(12), true);
check('THE OUTER RING x = 14, where the clamp has faded: it DOES lift',
  liftAt(14, 2), 1);
check('…by exactly level − h', liftAt(14, 2) - shoreH(14), 0.25);
check('a WEIGHTED dry corner is dry — x = 15 draws the ground', liftAt(15, 2), 1.875);
check('…and so does the dry probe x = 16', liftAt(16, 2), 3);
// RED: `Math.max` is not the rule, and this is why `liftedHeight` exists.
checkEq('RED: Math.max(h, NaN) would answer NaN at the dry probe',
  Number.isNaN(Math.max(3, gpuWaterAt(shoreWater, SHORE_RECT, 16, 0, 2))), true);
check('…while the shipped rule answers the ground', liftedHeight(3, NaN), 3);
// The near rectangle is the gate: outside it the height is the OVERVIEW's and
// the overview carries no water, so the mirror is not known there either.
checkEq('past the near window there is no mirror to read',
  Number.isNaN(gpuWaterAt(shoreWater, SHORE_RECT, 20, 0, 2)), true);
checkEq('…and no pyramid at all is dry as well',
  Number.isNaN(gpuWaterAt(null, SHORE_RECT, 4, 0, 2)), true);

// (b) the morph reads BOTH taps at their own footprint
check('at x = 14 the level-0 tap lifts to the mirror', liftAt(14, 2), 1);
check('…while the level-1 tap has lost the ring and stays ground',
  liftAt(14, 4), 2.25);
const blend16 = (f) => liftAt(14, 2) * (1 - f) + liftAt(14, 4) * f;
check('the shipped order is continuous at f = 0', blend16(0), 1);
check('…and one thousandth in it has moved one thousandth of the way',
  blend16(0.001), 1.00125, 1e-12);
// RED COUNTER-PROBE: mirrors blended first, then one max. A masked mix of a wet
// and a dry corner is dry for every weight above 0, so the lift vanishes the
// moment f leaves 0.
const wrongOrder = (f) => {
  const h = gpuHeightAt(shoreNear, SHORE_RECT, null, 14, 0, 2) * (1 - f)
    + gpuHeightAt(shoreNear, SHORE_RECT, null, 14, 0, 4) * f;
  const w = f === 0 ? gpuWaterAt(shoreWater, SHORE_RECT, 14, 0, 2) : NaN;
  return liftedHeight(h, w);
};
check('RED: the wrong order stands at 1.0 while f is exactly 0', wrongOrder(0), 1);
check('…and drops to the bed one thousandth later', wrongOrder(0.001), 0.7515, 1e-12);
check('…a step in the drawn ground of', wrongOrder(0) - wrongOrder(0.001),
  0.2485, 1e-12);

// …and the SHIPPED vertex function does it, not just the arithmetic above.
const SHORE_NODE = { x: 0, z: 0, size: 64, level: 0, cells: 32, morph: 0 };
check('morphedVertex at x = 14, morph 0, lifts to the mirror',
  morphedVertex(SHORE_NODE, 7, 0, shoreNear, SHORE_RECT, null, null, 0,
    shoreWater).y, 1);
check('…and without a water pyramid it is the bed, unchanged',
  morphedVertex(SHORE_NODE, 7, 0, shoreNear, SHORE_RECT, null, null, 0,
    null).y, 0.75);
// x = 12 is a support point of levels 0, 1 AND 2, so the decimation gives every
// tap the same lifted height and the morph moves NOTHING — the mirror cannot
// swim at a point every lattice agrees on.
for (const t of [0, 0.5, 1]) {
  check(`…and at x = 12 the morph t = ${t} draws the same 1.5`,
    morphedVertex(SHORE_NODE, 6, 0, shoreNear, SHORE_RECT, null, null, t,
      shoreWater).y, 1.5);
}

// (c) the gate
console.log('\n…and the gate: which pieces get the lifting program at all');
const WET_TILES = new Set(['1,0']);
checkEq('a piece west of the water is dry',
  nodeHasWater(WET_TILES, 256, 0, 0, 64), false);
checkEq('…a piece inside the wet tile is wet',
  nodeHasWater(WET_TILES, 256, 256, 0, 64), true);
checkEq('THE SEAM: a piece whose EAST EDGE is the tile border is wet too',
  nodeHasWater(WET_TILES, 256, 192, 0, 64), true);
// RED: the same span with `nodeBounds`' epsilon drops the tile the shared
// vertex reads its water out of — the piece at 192 would run the dry program
// while its neighbour at 256 lifts, and the edge they share would tear.
const epsSpan = (x, size, tileM) =>
  Math.floor((x + size - 1e-6) / tileM) - Math.floor(x / tileM) + 1;
check('RED: with the −1e-6 span that piece covers only', epsSpan(192, 64, 256), 1);
check('…while the closed rectangle covers',
  Math.floor((192 + 64) / 256) - Math.floor(192 / 256) + 1, 2);
checkEq('…and the tile the epsilon keeps holds no water',
  WET_TILES.has('0,0'), false);
checkEq('an empty raster leaves every piece on the dry program',
  nodeHasWater(new Set(), 256, 0, 0, 64), false);
checkEq('…and so does a raster with no tile size',
  nodeHasWater(WET_TILES, 0, 0, 0, 64), false);
// The scan cap: a 2 048 m root over 256 m tiles spans 9 x 9 = 81 closed, which
// is the cap itself, so the real quadtree is always scanned. Smaller tiles blow
// past it and the answer is the SAFE one — wet, i.e. it pays four texelFetch
// per vertex and draws the identical ground.
check('a root over 256 m tiles spans exactly the cap', (2048 / 256 + 1) ** 2, 81);
checkEq('…and is really scanned: no water near it, no lifting program',
  nodeHasWater(WET_TILES, 256, -4096, 0, 2048), false);
check('…while over 128 m tiles the same root spans', (2048 / 128 + 1) ** 2, 289);
checkEq('…which is past the cap, so it is marked wet without looking',
  nodeHasWater(new Set(['99,99']), 128, -4096, 0, 2048), true);

// ── [17] THE SECOND MATERIAL VARIANT — and what the dry one pays ────────────
//
// THE BINDING RISK RULE of `recherche-wasser-v2.md` § 4 K-A: the water branch
// exists only for nodes that carry water, so dry ground must keep the program
// it had before this stage — the same GLSL statements and, since three caches
// programs by `customProgramCacheKey`, literally the same `WebGLProgram`.
//
// String pins, hand-derived from what the lift has to be:
//   - the dry variant declares NO uTlodWater*, calls NO tlodLift, and keeps
//     its four texelFetch (the height's bilinear corners);
//   - the water variant has EIGHT — four for the ground, four for the mirror;
//   - the lift is `( w > h ) ? w : h` and NOT `max( h, w )`: the dry sentinel
//     is a NaN out of the texture, IEEE says every comparison against it is
//     false so `>` falls through to the ground, while GLSL leaves it open
//     which operand `max` returns for a NaN;
//   - each tap passes the SAME `nodeStep * m1` (and `* m2`) to the height and
//     to the lift. That one repeated expression IS the "same footprint, same
//     mip" property of section [16](b), written where it cannot drift.
console.log('\n[17] the water variant, and the dry program that is untouched');
const dryGlsl = terrainLodGlsl();
const wetGlsl = terrainLodGlsl(true);
checkEq('the dry variant knows no water uniform', dryGlsl.includes('uTlodWater'), false);
checkEq('…nor the lift', dryGlsl.includes('tlodLift'), false);
check('…and still fetches exactly the height\'s four texels',
  dryGlsl.split('texelFetch(').length - 1, 4);
checkEq('…its height line is the one it always had',
  dryGlsl.includes(
    'float h = mix( tlodHeight( p, nodeStep * m1 ), tlodHeight( p, nodeStep * m2 ), f );'),
  true);
checkEq('the water variant declares the sampler',
  wetGlsl.includes('uniform sampler2D uTlodWater;'), true);
checkEq('…and the isolation uniform',
  wetGlsl.includes('uniform float uTlodNoWater;'), true);
check('…and fetches twelve texels: four ground, four mirror, four flow',
  wetGlsl.split('texelFetch(').length - 1, 12);
checkEq('THE LIFT IS A COMPARISON', wetGlsl.includes('return ( w > h ) ? w : h;'), true);
checkEq('RED: and never max(), which GLSL does not pin down for a NaN',
  /max\(\s*h,\s*w\s*\)/.test(wetGlsl), false);
checkEq('EACH TAP IS LIFTED AT ITS OWN FOOTPRINT — the m1 half',
  wetGlsl.includes('float l1 = tlodLift( h1, p, nodeStep * m1 );'), true);
checkEq('…and the m2 half',
  wetGlsl.includes('float l2 = tlodLift( h2, p, nodeStep * m2 );'), true);
checkEq('…so the max is taken per LEVEL and one mix wraps both',
  wetGlsl.includes('float h = mix( l1, l2, f );'), true);
// ── K-A E4: the DEPTH the fragment shades from is a varying, not a lookup ──
// The drawn surface is mix(l1, l2, f) and the drawn bed is mix(h1, h2, f), so
// their difference is mix(l1 − h1, l2 − h2, f): exact for the triangle that is
// really drawn, ≥ 0 term by term, and 0 wherever nothing was lifted. That is
// what buys the fragment its shoreline WITHOUT the mirror's four texelFetch
// per pixel.
checkEq('THE LIFTED DEPTH RIDES ALONG as a varying',
  wetGlsl.includes('vTlodWet = mix( l1 - h1, l2 - h2, f );'), true);
checkEq('…declared in the water variant', wetGlsl.includes('varying float vTlodWet;'), true);
checkEq('…and in NO dry program', dryGlsl.includes('vTlodWet'), false);
checkEq('the flow rides along too', wetGlsl.includes('vTlodFlow = uTlodNoWater > 0.5'), true);
checkEq('…on the water lattice\'s LEVEL 0 and no pyramid',
  /vec2 tlodFlowAt[\s\S]*?\n}/.exec(wetGlsl)[0].includes('uTlodWaterLevel[ 0 ]'), true);
checkEq('…and never in the dry one', dryGlsl.includes('tlodFlowAt'), false);
// The TS twin of `l - h`, and the identity that makes it one statement.
check('liftedDepth: a mirror 1.2 m over the bed', liftedDepth(3, 4.2), 1.2);
check('…a mirror UNDER the bed is dry', liftedDepth(5, 4.2), 0);
check('…and the dry sentinel is dry', liftedDepth(5, NaN), 0);
checkEq('RED: depth 0 is exactly where the lift did nothing',
  [liftedHeight(5, NaN) - 5, liftedDepth(5, NaN),
   liftedHeight(3, 4.2) - 3 - liftedDepth(3, 4.2)], [0, 0, 0]);
// The masked mix, in GLSL this time: four corners, four weight guards.
check('the mirror\'s bilinear guards every one of its four corners',
  terrainLodWaterGlsl().split('!= 0.0').length - 1, 4);
checkEq('…and it is read in the NEAR window alone, where the height is',
  terrainLodWaterGlsl().includes('p.x < uTlodNearRect.x'), true);
// λ IS NEVER LIFTED: both variants measure the morph distance against the
// unlifted ground, so a dry piece and the wet piece beside it place the vertex
// they share at the same point.
checkEq('the morph distance is the UNLIFTED ground, in both variants',
  dryGlsl.includes('tlodHeight( p, 0.0 )') && wetGlsl.includes('tlodHeight( p, 0.0 )'),
  true);
checkEq('RED: nothing lifts inside tlodMorphAt',
  /float tlodMorphAt[\s\S]*?\n}/.exec(wetGlsl)[0].includes('tlodLift'), false);

// The cache key, on a stand-in material: the dry one is the string it was, the
// water one appends and never replaces.
const fakeMat = (prevKey) => {
  const m = { onBeforeCompile: () => {} };
  if (prevKey) m.customProgramCacheKey = () => prevKey;
  return m;
};
const dryMat = fakeMat('');
patchTerrainLod(dryMat);
const wetMat = fakeMat('');
patchTerrainLod(wetMat, true);
checkEq('the dry cache key', dryMat.customProgramCacheKey(), TERRAIN_LOD_CACHE_KEY);
checkEq('…is the string it always was', TERRAIN_LOD_CACHE_KEY, 'terrain-lod');
checkEq('the water cache key appends', wetMat.customProgramCacheKey(),
  `${TERRAIN_LOD_CACHE_KEY}+${TERRAIN_LOD_WATER_CACHE_KEY}`);
const chainedDry = fakeMat('ground+layers');
patchTerrainLod(chainedDry);
const chainedWet = fakeMat('ground+layers');
patchTerrainLod(chainedWet, true);
checkEq('…and both still chain onto what the owner built',
  [chainedDry.customProgramCacheKey(), chainedWet.customProgramCacheKey()],
  ['ground+layers+terrain-lod', 'ground+layers+terrain-lod+water']);
// …and the uniform that only the water variant may carry.
const compile = (mat) => {
  const shader = {
    uniforms: {},
    vertexShader: '#include <uv_vertex>\n#include <beginnormal_vertex>\n'
      + '#include <begin_vertex>',
    // The four chunks the two variants insert at, in three's own order.
    fragmentShader: '#include <metalnessmap_fragment>\n'
      + '#include <normal_fragment_begin>\n#include <opaque_fragment>',
  };
  mat.onBeforeCompile(shader, null);
  return shader;
};
const dryShader = compile(dryMat);
const wetShader = compile(wetMat);
checkEq('the dry program is handed no uTlodNoWater',
  dryShader.uniforms.uTlodNoWater === undefined, true);
checkEq('…the water program is', wetShader.uniforms.uTlodNoWater !== undefined, true);
checkEq('…both get the water TEXTURE bound (an unread uniform has no location)',
  dryShader.uniforms.uTlodWater !== undefined
  && wetShader.uniforms.uTlodWater !== undefined, true);
checkEq('the dry vertex shader carries no lift',
  dryShader.vertexShader.includes('tlodLift'), false);
checkEq('…the water one does', wetShader.vertexShader.includes('tlodLift'), true);

// ── [18] K-A E4: THE WATER SHADING IS THE WATER PROGRAM'S ALONE ─────────────
// The dry fragment must be, statement for statement, what it was before the
// stage — one replacement at `normal_fragment_begin` and nothing else. The
// arithmetic the shading itself runs on is checked, against hand tables, in
// `client3d/scripts/smoke_water_shade.mjs`; what belongs HERE is only that the
// two programs stay two programs.
console.log('\n[18] the water shading lives in the water program only (K-A E4)');
checkEq('THE DRY FRAGMENT IS THE ONE IT ALWAYS WAS',
  dryShader.fragmentShader.includes(`#include <normal_fragment_begin>
\tnormal = normalize( ( viewMatrix * vec4( tlodNormalAt( vTlodXZ ), 0.0 ) ).xyz );
\tnonPerturbedNormal = normal;`), true);
checkEq('…and gains nothing at metalnessmap or opaque_fragment',
  /#include <metalnessmap_fragment>\n#include <normal/.test(dryShader.fragmentShader)
  && /nonPerturbedNormal = normal;\n#include <opaque_fragment>/
    .test(dryShader.fragmentShader), true);
checkEq('RED: no water word reaches the dry fragment',
  /tlodWater|vTlodWet|uTlodWave|twA/.test(dryShader.fragmentShader), false);
// …and the water one composes in exactly three places, in shader order.
const wetFrag = wetShader.fragmentShader;
checkEq('the ALBEDO stage sits after the metalness chunk',
  wetFrag.includes('#include <metalnessmap_fragment>\n'
    + '\ttlodWaterSurface( diffuseColor, roughnessFactor, metalnessFactor );'), true);
checkEq('…the NORMAL stage replaces the dry expression',
  wetFrag.includes('\tnormal = tlodWaterNormal();'), true);
checkEq('…and the LIGHT stage runs before opaque_fragment',
  wetFrag.includes('\ttlodWaterOut( outgoingLight, normal, vViewPosition );\n'
    + '#include <opaque_fragment>'), true);
check('the composition order is albedo -> normal -> light',
  [wetFrag.indexOf('tlodWaterSurface( diffuseColor'),
   wetFrag.indexOf('normal = tlodWaterNormal();'),
   wetFrag.indexOf('tlodWaterOut( outgoingLight')]
    .every((v, i, a) => v > 0 && (i === 0 || v > a[i - 1])) ? 1 : 0, 1);
checkEq('the water program is handed the look table, the wave map and the mask',
  ['uTlodWaterLook', 'uTlodWave', 'uTlodFlow', 'uTlodTime', 'uTlodSky',
   'uTlodWaterMask', 'uTlodWaterMaskGeom']
    .every((k) => wetShader.uniforms[k] !== undefined), true);
checkEq('RED: and the dry program is handed none of them',
  ['uTlodWaterLook', 'uTlodWave', 'uTlodFlow', 'uTlodWaterMask']
    .some((k) => dryShader.uniforms[k] !== undefined), false);
// The absorption a fragment reads is the mirror's own shore curve — the twin
// is checked against hand tables in `smoke_water_shade.mjs`; here only that
// BOTH sides spell the same easing.
checkEq('the GLSL easing is the TS easing',
  shade.terrainWaterFragmentGlsl()
    .includes('return c * c * ( 3.0 - 2.0 * c );'), true);

console.log(`\n${passed + failed} checks, ${failed} failures`);
process.exit(failed ? 1 : 0);
