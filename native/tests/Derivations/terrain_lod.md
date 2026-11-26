# terrain_lod

- Origin: the browser scene's deleted `smoke_terrain_lod.mjs` @ 011cd048aa3cc2937186d7f35d2203af9491db8a
- Executed by: `native/tests/TerrainLodVectorTests.cs`
- Vectors: `shared/test-vectors/terrain_lod.json`

## Derivation

```text
/**
 * Smoke check for the CDLOD TERRAIN — the browser scene's `terrainLod.ts`
 * (plan-ein-boden.md § G2, decision 5.3) and the analytic click march in
 * `packages/scene-render/src/worldHeight.ts`.
 *
 * Usage:  node the browser scene's deleted smoke_terrain_lod.mjs
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
 *
 * [20] Shared E3 extraction cases, derived independently:
 * Near windows union tile boxes, grow each side by max(16,2*overviewStep),
 * floor origins onto the step, then count floor(span/step)+1 support points.
 * A 256 m tile at step2 with margin16 gives origin(-16,-16), span288,
 * 145 points. Tile(-1,-1) starts -256-16=-272, same count. Overview40
 * makes margin80: origin -80, span416, 209 points. Tile4096 makes
 * (4096+32)/2+1=2065 points, capped to1025. Half span=1025*2/2=1025;
 * anchor(100,0) gives floor(-925/2)*2=-926 and floor(-1025/2)*2=-1026.
 * Keys(0,0),(16,0) span4352+32=4384:2193 columns,145 rows. When EITHER
 * axis caps, BOTH recenter: x=-1026, z=floor(-145/2)*2=-146.
 * No keys, no readable keys, or no positive step means no window.
 * Errors [1,4],[3,2] at steps4,8 take maxima3,4; level0 is0.
 * Bounds union known spans [-2,3],[-5,9] to[-5,9]; absent statistics
 * are skipped (the global [-20,20] is used only when none are known).
 * A single64 m leaf at the camera selects exactly (0,0,64,L0,cells32,
 * morph0), ranges[128], coarsenings0,capRelax0. No fit step is needed.
 * The plane h=x/2 on a3x3 step2 lattice is rows[0,1,2] three times;
 * decimation retains corners[0,2] twice. Packed width3, rows3+2=5:
 * [0,1,2,0,1,2,0,1,2,0,2,0,0,2,0], padding0. Levels have row0=0,3
 * and steps2,4. round(log2(step/2)) gives0,1,clamped1 at step64.
 * Vertex(1,1) of size64/cells32 starts(2,2); half morph snaps halfway
 * to(0,0), hence(1,1), flat y0. At camera(2,0,2), distance0 gives t0.
 * At camera(98,0,2), distance96 gives (96-64)/(128-64)=.5, same half
 * morph. No field gives normal(0,1,0). On h=x/2, at(2,2), span2:
 * hx=2,hz=0, vector(-2,4,0)/sqrt20=(-.4472135954999579,
 * .8944271909999159,0). A cap1 at tile0 of16 m creates a4x4 corner
 * grid from(-16,-16): central2x2 values1, perimeter6; min1. Thus
 * cap(8,8)=1, cap(100,100)=6, minimum over[0,16]^2=1.
 * No water/height gives no caps. Flat water10 over ground0 on a3x3
 * step2 grid lifts every support point. TileM4 includes endpoint tiles:
 * (0,0) has a complete3x3 block so cap1; tiles(1,0),(0,1),(1,1) only
 * have an endpoint row/column, so cap0. Iteration is z then x.
 * Lift h2,w6: inside(.5)=1 ->6; inside(.25)=.5 ->4; outside(-1)=0 ->2.
 *
 * [21] Review additions: nontrivial selection and height/mip morph.
 * A128 m square, leaf64, two levels, bounds y0, camera(0,0,0)
 * splits its root: child distances0,64,64,64sqrt2 are all<128.
 * Child order is(0,0),(64,0),(0,64),(64,64), each size64,L0,cells32.
 * Morphs are0,0,0,(64sqrt2-64)/64=sqrt2-1=.41421356237309515.
 * Camera(-128,0,0) is EXACTLY128 from the root: no split, size128,L1,
 * cells32,morph0. Camera(-96,0,0) splits the root, but alternates
 * leaf/parent-quadrant: near distances96 and sqrt(96^2+64^2) are<128,
 * far distances160 and sqrt(160^2+64^2) are>=128. Near morphs are
 * (96-64)/64=.5 and sqrt(3.25)-1=.8027756377319946; far pieces
 * retain parentL1,cells16,size64,morph0 (distances below192).
 * Budget case:64 m square,leaf1,two levels,camera(32,0,32),ranges
 * [200,400]. There are32^2=1024 roots. All split, making4096 leaves,
 * the exact ceiling. Halving to100 then50 still splits all four children
 * per root: even the farthest child is only32sqrt2=45.2548 m away.
 * Halving to25 leaves at least the corner root unsplit (distance>25),
 * so at most4093 pieces, strictly below4096: exactly3 coarsenings,
 * capRelax3,ranges[25,50]. No node count is inferred from a sampled run.
 * Nonflat fixture: a5x5 step2 grid, all zero except centre(4,4)=8.
 * Mip1 is3x3 step4 with centre8; mip2 is2x2 step8, all zero.
 * At gx=gz=2,t0, position(4,4) reads fine height8. At gx=gz=3,t1.5,
 * k1,f.5 snaps indices between2 and0 to1, hence position(2,2).
 * At(2,2), mip1 bilinear weight on its8 m peak is.5*.5=.25:
 * height2; mip2 height0. Pair interpolation gives(2+0)/2=1.
 * For lodVertex camera(4,232,4), the raw(6,6) vertex has height0
 * and distance sqrt(232^2+8), between224 and256. Its2-cell owner is
 * (4,4), height8, distance232-8=224, lambda=1+(224-192)/64=1.5.
 * Larger owner blocks land at(0,0), distance sqrt(232^2+32)<256,
 * so lambda<2 and cannot claim level2 or higher. Thus both index3
 * and its index2 twin use owner t1.5, position(2,2),height1.
 */
```

## Inline derivations

Comment blocks of the browser scene's deleted `smoke_terrain_lod.mjs` after its opening docstring that contain a mark a case label
cites, in file order; line numbers refer to the smoke at a56065e6f003.

Line 851 (cites [16]):

```text
/**
 * The one piece of DOM the water variant touches: the shared wave normal map
 * is drawn onto a 256² canvas (`@anima/scene-render materials.makeWaveNormal`)
 * the first time a water program is compiled, and [16] compiles one. The stub
 * takes the pixels and throws them away — what is checked here is the SHADER,
 * never the map.
 */
```

Line 1207 (cites [4]):

```text
// ── [4] the ranges ──────────────────────────────────────────────────────────
```

Line 1465 (cites [8]):

```text
// ── [8] the morph belongs to the vertex ─────────────────────────────────────
```

Line 2912 (cites [4], [8]):

```text
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
```

Line 2962 (cites [8]):

```text
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
```

Line 3056 (cites [16]):

```text
// AND THE UPLOAD IS WIRED: the three water uniforms are bound beside the height
// ones, by the same one function every patched material goes through — and
// since E3 the WATER VARIANT of the program is what reads them (section [16]).
```

Line 3071 (cites [16]):

```text
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
//       x = 12      2 m outside the outline: authored meadow standing 0.5 m
//                   OVER its own mirror — a bank, and nothing in the bake
//                   touches it (the shore guards are gone since v8, K-A E6,
//                   and while they existed this was the clamp's band):  1.5
//       x = 14      4 m outside: authored meadow lying UNDER the mirror,
//                   which is the normal legal case since v8 — the bake leaves
//                   it and the LIFT below is what covers it:            0.75
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
//                                              the authored ground already
//                                              stands 0.5 m over its mirror
//       x = 14   h = 0.75, w = 1.0    → 1.0   …and here it DOES, by 0.25 m
//       x = 15   h = mix(0.75, 3.0, ½) = 1.875, w = mix(1.0, null, ½) = dry
//                                     → 1.875 (a WEIGHTED dry corner is dry)
//       x = 16   h = 3.0, w = dry     → 3.0
//
//     THE RING RULE, and it is the point of the whole stage. A vertex in the
//     dilation ring lifts wherever the mirror stands over the ground, and
//     since v8 (K-A E6) the bake no longer holds that ground up: the bank
//     clamp and the 16 m relief fade are deleted, precisely because THIS is
//     the answer to land lying under the mirror beside its own water (failure
//     class F1, `recherche-wasser-v2.md` § 2) — K-A raises the land instead of
//     floating the water. The lift is bounded twice over: by `level − h` in
//     height and by the 4 m dilation in width, which is why x = 15 (a weighted
//     dry corner) is already dry again and the lake cannot creep into the
//     meadow past the ring.
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
```

Line 3422 (cites [16], [17]):

```text
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
```

Line 3827 (cites [19]):

```text
// ============================================================================
// [19] THE CAP AS A FIELD — continuous, an upper bound inside, none outside
// ============================================================================
// The cap enters λ (`tlodMorphAt`), and the whole crack-freeness of this
// renderer is that the drawn surface is a function of the WORLD POINT alone. A
// per-tile step function is such a function but a discontinuous one, and a
// discontinuous λ stops the fine side's extra vertices collapsing onto the
// coarse side's edge — a T-junction at every tile border. So the caps are
// sampled at the tile CORNERS, each corner taking the MINIMUM of the four tiles
// that meet there, and mixed bilinearly.
//
// THE FIXTURE is one row of 64 m tiles, tx = 0…31 at tz = 0, all capped at 1.
// Corner b sits between tiles (tz0 − 2 + b) and (tz0 − 1 + b), so with tz0 = 0
// the grid runs z = −64, 0, 64, 128 — four rows — and its outer two touch no
// wet tile and read LOD_CAP_NONE = 6.
// (e) the corner values are 6, 1, 1, 6 and the field between them is the ramp.
// (f) INSIDE a wet tile the field never exceeds that tile's own cap, which is
//     what makes the cap a promise: every corner of the tile is a minimum over
//     four tiles including this one.
// (g) OUTSIDE the grid it is LOD_CAP_NONE, so a world with a pond in one corner
//     pays nothing anywhere else — and a world with no water has NO GRID AT
//     ALL: `buildLodCapGrid` answers null and no texture is ever allocated.
```

Line 3882 (cites [19], [20]):

```text
// ============================================================================
// [20] THE SELECTION SPLITS TO THE CAP — and the budget takes it back
// ============================================================================
// The same [5] world — extent [0, 2048]², leaf 64 m, six levels,
// `minLodDistance` 128 — with the camera in the MIDDLE (1024, 200, 1024) so the
// tile row along the south edge is far enough to be drawn coarse, and the cap
// row of [19] under it.
// (h) a node is never emitted above the cap of the square it covers;
// (i) the price is 36 extra pieces, and every one of them stands over the
//     water's own tile row — the cost lands on the water, which is the whole
//     decision;
// (j) RELAXING THE CAP PAST `LOD_CAP_NONE` REPRODUCES THE OLD SELECTION
//     EXACTLY, piece for piece. That is one statement doing two jobs: the
//     budget ladder of `selectLodFitted` (eight halvings, +8 on the cap) ends
//     at the picture this renderer drew before F1 — the river breaks up again,
//     which is a loss and never a crash — and the isolation panel's toggle 22
//     ("Water lift off") is the same addition, which is why it needs no switch
//     of its own.
```

Line 3940 (cites [21]):

```text
// ============================================================================
// [21] THE CAP DOES NOT CRACK THE GROUND — shared vertices, bit for bit
// ============================================================================
// THE FINDING THAT MADE THE CAP NECESSARY, first. The drawn surface is a
// function of λ and the world point: a vertex snaps onto the world lattice of
// `baseStep · 2^⌊λ⌋` and reads the mip pair (⌊λ⌋, ⌊λ⌋+1), and the piece's own
// level cancels out of both (`morphedVertex`). So SPLITTING A NODE DOWN CHANGES
// NOTHING: the vertices it adds collapse onto the ones the coarse piece already
// had. (kk) measures that on the rugged fixture — which is why the cap had to
// go into λ and not into the node level.
//
// And because it goes into λ, the same probe is what proves it safe: two pieces
// of DIFFERENT levels must still answer the same point and the same height at a
// vertex they share, with the cap on, and on the cap grid's own corner line
// where the field's derivative jumps.
```
