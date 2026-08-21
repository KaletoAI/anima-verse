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
 *      disagree about a point they share whatever their levels are ([8]).
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
 * `lodRange[i] = max(minLodDistance · 2^i, levelErrorM[i+1] · pixelScale /
 * MAX_PIXEL_ERROR)`, then made monotone.
 *
 * (j) WITHOUT an error list: 128 · 2^i -> [128, 256, 512, 1024, 2048, 4096].
 * (k) WITH the contract's own example errors (§ 4 of the E1 addendum:
 *     err = [0.5862, 0.85, 1.0, 1.1636, 3.3132] for levels 1…5) and a pixel
 *     scale of 2 000 px/m/m, the error term is err · 2000 / 2 = err · 1000:
 *       i=0: max(128,  586.2)  = 586.2
 *       i=1: max(256,  850)    = 850
 *       i=2: max(512,  1000)   = 1000
 *       i=3: max(1024, 1163.6) = 1163.6
 *       i=4: max(2048, 3313.2) = 3313.2
 *       i=5: max(4096, 0)      = 4096   (no level 6 to bound)
 *     Every ring is pushed OUT, i.e. the rugged world is drawn finer.
 * (l) THE MONOTONE GUARD: err = [0, 5, 0.1] at scale 200 gives
 *       i=0: max(128, 5·100)   = 500
 *       i=1: max(256, 0.1·100) = 10 -> raised to 500
 *       i=2: max(512, 0)       = 512
 *     A ring may never start before the one inside it, or a coarse node would
 *     be selected inside a fine ring and the ground would crack.
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
 * (n) 4 + 3 + 3 + 3 + 3 = 16 nodes, and none at level 5.
 * (o) THE MORPHS. For a selected node at level L the range is
 *     ranges[L] = 128·2^L = 2·size and the morph runs over
 *     [0.5·ranges[L], ranges[L]] = [size, 2·size]:
 *       the corner node (d = 0)        -> clamped to 0
 *       an axis node   (d = size)      -> (size − size)/size          = 0
 *       the diagonal   (d = size·√2)   -> (size√2 − size)/size = √2−1 = 0.414213562…
 *     The SAME number at every level, which is what "one halving of density
 *     per doubling of distance" means.
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
 *     the coarse lattice, read their λ at the point they start from rather than
 *     at the one they end on and so miss it by a hair: they land within 4 cm on
 *     this fixture, i.e. under 0.7 % of the 6 m the two mips are apart, and
 *     0.036 m at 128 m is 0.37 pixels (fov 45°, 1 080 px). It is a
 *     second-order term of the same λ and not a hole: a second λ evaluation
 *     after the snap would remove it and cost a fetch per vertex for a third
 *     of a pixel.
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
 * Neither says the picked set has no HOLE in it: selection also CULLS, against
 * the camera frustum, and a node wrongly culled is not a seam but a window to
 * the sky — the light blue of `engine.ts` (`0x9fc7e8`, background and fog are
 * the same colour), flashing on and off as the camera turns. That is what this
 * section measures, and it measures it over the WHOLE COMPASS, because a
 * culling mistake is by nature a mistake about one direction.
 *
 * THE INVARIANT. For a camera anywhere, the union of the SELECTED squares must
 * contain every ground point that is
 *   inside the view frustum ∩ inside the world frame ∩ nearer than the haze
 * (520 m, `engine.ts`). Not "roughly cover": every sample, every heading.
 *
 * WHY IT IS DECIDABLE AT ALL — the theorem the check is built on. Let the box
 * of every node contain the ground drawn over its square. A visible point p
 * lies in the box of the leaf that owns it and, since a child's square and its
 * heights are a subset of its parent's, in the box of EVERY ancestor of that
 * leaf. So no ancestor can fail the frustum test, the recursion walks all the
 * way down the chain that owns p, and somewhere on that chain a node is
 * selected. Coverage therefore fails if and ONLY if some node's box is too
 * small — which is why `nodeBounds` is written as a bound and not as a
 * measurement, and why it now lives outside the renderer where this file can
 * reach the shipped rule instead of a copy of it.
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
 *      4 373 188 sampled ground points. The selection is not the hole.
 * (z3) RED COUNTER-PROBE A — the hypothesis this check was written for: a box
 *      whose `min`/`max` are SWAPPED for nodes reaching into negative z (an
 *      inverted, empty box). Measured at 8 m / −15°: coverage fails at 306 of
 *      360 headings and loses 589 172 of 2 072 836 sampled points, i.e. 28 %
 *      of the visible ground. So the check WOULD see a sign error in the node
 *      box; it does not see one in the real rule.
 * (z4) RED COUNTER-PROBE B — the tile key by `Math.trunc` instead of
 *      `Math.floor`, i.e. the stats of the wrong tile everywhere west or north
 *      of the origin. Measured at 25 m / −25°: coverage fails over one broad
 *      band, headings 84°…202°. Also seen, also absent from the real rule.
 * (z5) STABILITY, the other half of a flicker: over 7 200 yaw steps of 0.05°
 *      the selected SET changes by at most a handful of nodes, and those are
 *      the ones entering or leaving at the edge of the screen. There is no
 *      node that toggles in the middle of the view from one frame to the next,
 *      so no hysteresis is owed.
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
export const RedFormat = 1022;
export const FloatType = 1015;
export const NearestFilter = 1003;
export const ClampToEdgeWrapping = 1001;
`;

/**
 * Transpile a module and import it, with `three` and `@anima/scene-render`
 * resolved to local files. The scene-render entry is `worldHeight.ts` itself:
 * that is the only thing `terrainLod.ts` takes from the package, and pointing
 * at the real barrel would drag three back in through the front door.
 */
async function loadLod() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'terrainlod-'));
  try {
    const ts = async (src, name) => {
      const code = await readFile(src, 'utf8');
      await writeFile(join(dir, `${name}.mjs`),
        esbuild.transformSync(code, { loader: 'ts', format: 'esm' }).code, 'utf8');
    };
    await writeFile(join(dir, 'three.mjs'), THREE_STUB, 'utf8');
    await ts(join(ROOT, 'packages/scene-render/src/worldHeight.ts'), 'worldHeight');
    const src = await readFile(join(ROOT, 'client3d/src/scene/terrainLod.ts'), 'utf8');
    const out = esbuild.transformSync(src, { loader: 'ts', format: 'esm' }).code
      .replace(/from\s*["']three["']/g, "from './three.mjs'")
      .replace(/from\s*["']@anima\/scene-render["']/g, "from './worldHeight.mjs'");
    await writeFile(join(dir, 'terrainLod.mjs'), out, 'utf8');
    return {
      lod: await import(`file://${join(dir, 'terrainLod.mjs')}`),
      height: await import(`file://${join(dir, 'worldHeight.mjs')}`),
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

const { lod, height } = await loadLod();
const { PATCH_N, MAX_LOD_LEVELS, MIN_LOD_DISTANCE_M, MORPH_START, MAX_PIXEL_ERROR,
  buildPyramid, pyramidHeight, pyramidLevelFor, lodRanges, selectLodNodes,
  morphedVertex, lodLambda, lodVertex, nodeBounds, terrainLodGlsl } = lod;
const { heightAt, rayGroundHit, sampleWorldHeight } = height;

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
console.log('\n[4] the LOD ranges — geometry, widened by the server\'s error bound');
checkEq('(j) without an error list', lodRanges(128, 6),
  [128, 256, 512, 1024, 2048, 4096]);
const ERR = [0, 0.5862, 0.85, 1.0, 1.1636, 3.3132];
checkEq('(k) with the contract\'s own example errors at 2 000 px/m/m',
  lodRanges(128, 6, ERR, 2000).map((v) => Math.round(v * 1e4) / 1e4),
  [586.2, 850, 1000, 1163.6, 3313.2, 4096]);
checkEq('(l) the monotone guard', lodRanges(128, 3, [0, 5, 0.1], 200), [500, 500, 512]);
checkEq('(m) a flat world has no ranges', lodRanges(0, 6, ERR, 2000), [0, 0, 0, 0, 0, 0]);

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
const MORPH_DIAG = Math.SQRT2 - 1;
for (const level of [0, 1, 2, 3, 4]) {
  const size = 64 * (1 << level);
  const corner = picked.find((n) => n.level === level && n.x === 0 && n.z === 0);
  const axis = picked.find((n) => n.level === level && n.x === size && n.z === 0);
  const diag = picked.find((n) => n.level === level && n.x === size && n.z === size);
  if (level === 0) check(`(o) level 0, the corner node (d = 0)`, corner.morph, 0);
  check(`(o) level ${level}, the axis node (d = size)`, axis.morph, 0);
  check(`…the diagonal one (d = size·√2)`, diag.morph, MORPH_DIAG, 1e-12);
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
const childFull = { x: 0, z: 0, size: 256, level: 1, morph: 1 };
const childOwn = { x: 0, z: 0, size: 256, level: 1, morph: 0 };
const parent = { x: 0, z: 0, size: 512, level: 2, morph: 0 };
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
check('(w) λ(192)', lodLambda(192, RANGES), 1.5);
check('(w) λ(256)', lodLambda(256, RANGES), 2);
check('(w) λ(400)', lodLambda(400, RANGES), 2.5625);
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
checkBelow('…and the whole fine edge stays within 4 cm of the coarse one',
  seamWorst, 0.04);
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
function coverageAt(boundsFn, atX, atZ, yawDeg, pitchDeg, dist) {
  const { fwd, eye } = eyeFor(atX, atZ, yawDeg, pitchDeg, dist);
  const ps = frustumPlanes(eye, fwd);
  const picked = selectLodNodes({
    x0: CX0, z0: CZ0, x1: CX1, z1: CZ1,
    leafM: LEAF_M, levels: MAX_LOD_LEVELS, minLodDistance: MIN_LOD_DISTANCE_M,
    camX: eye[0], camY: eye[1], camZ: eye[2],
    boundsOf: boundsFn, levelErrorM: CERR, pixelScale: camPixelScale,
    inView: (x, z, s, mnY, mxY) => boxSeen(ps, x, mnY, z, x + s, mxY, z + s),
  });
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
function sweepCompass(boundsFn, atX, atZ, pitchDeg, dist) {
  let miss = 0;
  let tested = 0;
  const bad = [];
  for (let yaw = 0; yaw < 360; yaw += 1) {
    const r = coverageAt(boundsFn, atX, atZ, yaw, pitchDeg, dist);
    miss += r.miss;
    tested += r.tested;
    if (r.miss) bad.push(yaw);
  }
  const ranges = [];
  for (const y of bad) {
    const last = ranges[ranges.length - 1];
    if (last && y === last[1] + 1) last[1] = y;
    else ranges.push([y, y]);
  }
  return { miss, tested, headings: bad.length,
           ranges: ranges.map((r) => (r[0] === r[1] ? `${r[0]}` : `${r[0]}-${r[1]}`)).join(', ') };
}
const REPORTED_X = -1550;
const REPORTED_Z = -760;
const ORBITS = [[8, -15], [25, -25], [60, -35]];
const honest = (x, z, size) => nodeBounds(cStats, TILE_M, cGlobal, x, z, size);
let sweptSamples = 0;
for (const [dist, pitch] of ORBITS) {
  const r = sweepCompass(honest, REPORTED_X, REPORTED_Z, pitch, dist);
  sweptSamples += r.tested;
  check(`(z2) 360 headings at ${dist} m / ${pitch}°: visible ground with no node`
    + ` (of ${r.tested} samples)`, r.miss, 0);
  check('…failing headings', r.headings, 0);
}
checkAbove('(z2) ground points sampled over the whole compass', sweptSamples, 2.5e6);
// (z3) RED A — the very hypothesis: a sign mix-up in the box for negative z.
const redSwapZ = (x, z, size) => {
  const b = honest(x, z, size);
  return z < 0 ? { min: b.max, max: b.min } : b;
};
const redA = sweepCompass(redSwapZ, REPORTED_X, REPORTED_Z, -15, 8);
checkAbove('(z3) RED A: an inverted box for z < 0 loses ground at headings',
  redA.headings, 200);
checkAbove('…and loses this many sampled points', redA.miss, 5e5);
console.log(`       (RED A fails at headings ${redA.ranges})`);
// (z4) RED B — the tile key by truncation instead of floor.
const redTrunc = (x, z, size) => {
  const tx0 = Math.trunc(x / TILE_M);
  const tx1 = Math.trunc((x + size - 1e-6) / TILE_M);
  const tz0 = Math.trunc(z / TILE_M);
  const tz1 = Math.trunc((z + size - 1e-6) / TILE_M);
  const covered = (tx1 - tx0 + 1) * (tz1 - tz0 + 1);
  if (covered > 64) return cGlobal;
  let min = Infinity;
  let max = -Infinity;
  let seen = 0;
  for (let tz = tz0; tz <= tz1; tz += 1) {
    for (let tx = tx0; tx <= tx1; tx += 1) {
      const s = cStats.get(`${tx},${tz}`);
      if (!s) continue;
      seen += 1;
      min = Math.min(min, s.min);
      max = Math.max(max, s.max);
    }
  }
  if (!seen) return cGlobal;
  if (seen < covered) { min = Math.min(min, 0); max = Math.max(max, 0); }
  return { min, max };
};
const redB = sweepCompass(redTrunc, REPORTED_X, REPORTED_Z, -25, 25);
checkAbove('(z4) RED B: the tile key by trunc loses ground at headings',
  redB.headings, 50);
console.log(`       (RED B fails at headings ${redB.ranges})`);

// (z5) stability — the other half of a flicker
for (const [dist, pitch] of [[8, -15], [25, -25]]) {
  let worst = 0;
  let prev = null;
  for (let yaw = 0; yaw < 360; yaw += 0.05) {
    const { fwd, eye } = eyeFor(REPORTED_X, REPORTED_Z, yaw, pitch, dist);
    const ps = frustumPlanes(eye, fwd);
    const picked = selectLodNodes({
      x0: CX0, z0: CZ0, x1: CX1, z1: CZ1,
      leafM: LEAF_M, levels: MAX_LOD_LEVELS, minLodDistance: MIN_LOD_DISTANCE_M,
      camX: eye[0], camY: eye[1], camZ: eye[2],
      boundsOf: honest, levelErrorM: CERR, pixelScale: camPixelScale,
      inView: (x, z, s, mnY, mxY) => boxSeen(ps, x, mnY, z, x + s, mxY, z + s),
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
  checkBelow(`(z5) worst node churn per 0.05° of yaw at ${dist} m / ${pitch}°`,
    worst, 8);
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

console.log(`\n${passed + failed} checks, ${failed} failures`);
process.exit(failed ? 1 : 0);
