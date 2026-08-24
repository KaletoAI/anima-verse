/**
 * THE TERRAIN, drawn from the data it is defined by — CDLOD (plan-ein-boden.md
 * § G2, decision 5.3 "VOLL").
 *
 * WHAT IT REPLACES. Until E2 the open world's ground was ONE big drawn mesh:
 * `gridPlate` over the whole world frame, cut at whatever cell size kept it
 * under a 40 000-cell budget — 64 m in the live world — and every vertex
 * lifted out of the height field. Two things followed, both measured:
 *
 *  - the DRAWN surface stood up to 2.433 m (p95 1.584 m) away from the
 *    bilinear field the server judges walks by, because inside a 64 m cell a
 *    mesh is two triangles and the field is not;
 *  - the ground changed SHAPE as tiles arrived, since the same mesh was re-cut
 *    against a composite that had just gained a finer raster.
 *
 * Here the ground is a quadtree of ONE instanced 32 × 32 patch. Every vertex
 * fetches its height out of the very lattice `heightAt` reads (four
 * `texelFetch` and the bilinear mix of `@anima/scene-render` `bilinear`), so
 * the drawn surface and the rule's answer are the same function — assertable,
 * and asserted, to 1e-4 in `smoke_terrain_lod.mjs`. Detail is a MORPH between
 * two mip levels of that lattice, not a different landscape: every VERTEX
 * reads how coarse the ground is at its own distance (`lodLambda`) and blends
 * there, so nothing pops and nothing cracks (no skirts, no stitching).
 *
 * THE MORPH BELONGS TO THE VERTEX, NOT TO THE NODE (finding round 2026-08-21).
 * It used to be one number per patch, taken from the patch's bounding-box
 * distance: two neighbouring patches whose boxes straddled the morph ramp then
 * drew two different polylines along the edge they share — measured, on a
 * rolling 6 m relief, at 0.61 m between adjacent LEAF patches, i.e. a
 * 6.2-pixel hairline of sky at 127 m that reopened somewhere else every frame
 * the camera moved. See `lodLambda`.
 *
 * …BUT NOT TO THE VERTEX ALONE — TO THE BLOCK IT SNAPS INTO (finding round
 * 2026-08-22). Wherever λ has climbed past a piece's own level the piece is
 * drawing on a lattice coarser than its own and several of its vertices snap to
 * ONE point. They only really merge if they blend with the same f, and f was
 * each vertex's own λ: a twin pair therefore separated by
 * `(gi mod m2 − gi mod m1) · Δt · nodeStep` — 0.357 m sideways, 0.086 m up —
 * which leaves the added vertex hanging beside the coarser neighbour's edge.
 * That is a T-junction, and a T-junction on a flat-shaded, unfiltered,
 * single-coloured ground is still a sliver of sky: exactly what the isolation
 * panel measured, with toggles 6, 7 and 18 all on and the light-blue shimmer
 * standing, while toggle 10 took it away. Three things fix it and all three are
 * needed:
 *
 *  - `lodLambda` anchors each level's morph ramp INSIDE that level's own ring,
 *    so λ(range[i]) = i + 1 exactly even after the screen-space error rule has
 *    widened a range out of the doubling. Without it a coarse piece begins
 *    morphing before its own ring starts and stands 3.9 m off the fine piece
 *    beside it;
 *  - `lodVertex` / `tlodCompute` read the morph at the vertex's BLOCK, found by
 *    a descent over anchors every member of the block shares, so the added
 *    vertices land on their twin exactly instead of nearly;
 *  - `selectLodNodes` never renders a node at a level whose ring it lies
 *    outside — the parent draws those quadrants itself. That is Strugar's own
 *    rule; here it is what keeps the coarse blocks rare and the far ground
 *    cheap (23 % fewer triangles per frame) rather than what closes the seam.
 *
 * `smoke_terrain_lod.mjs` [12] measures the T-junctions over the whole drawn
 * ground: 0 (2.1e-13 m) now, 0.1171 m and 100 779 hanging vertices before.
 *
 * THE SHADING NORMAL BELONGS TO THE FRAGMENT, NOT TO THE VERTEX (finding round
 * 2026-08-21, second half). It used to be built in the VERTEX shader from
 * central differences over the vertex's own morph pair — spans of
 * `nodeStep·2^k` and twice that, blended by the same `f` — and every one of
 * those three numbers is a function of the CAMERA DISTANCE. So the normal of a
 * fixed piece of ground swung by up to 16–17° while nothing but the camera
 * moved, and with a low sun (18:00, elevation 5.6°) 8.6 % of the ground crossed
 * the `max(N·L, 0)` terminator from that alone: ground that lost its sun shows
 * hemisphere sky plus fill and turns light blue — the whole-ground shimmer that
 * was reported, bound to the sun's azimuth sector. `tlodNormalAt` takes the
 * normal per FRAGMENT from the interpolated world position at ONE fixed metre
 * span (`uTlodNormalSpan`, the base lattice step), so it is a pure function of
 * (x, z) and cannot know
 * where the camera is. See `terrainLodNormalGlsl`.
 *
 * THE PYRAMIDS ARE CLIENT-SIDE and are pure DECIMATION — every coarse level
 * takes every second support point of the one below it. That is exact rather
 * than an approximation because the server's height is one pure function
 * sampled on lattices that are subsets of each other (E1, addendum § 1/§ 4):
 * a decimated level IS the function on the coarser lattice, and the server's
 * own `err[k]` bound therefore describes what this renderer really draws.
 *
 * TWO PYRAMIDS, ONE FUNCTION. The near one covers the loaded fine tiles at the
 * server's fine step and is filled from `heightAt` itself, so it carries the
 * tile-first precedence. The far one is the overview. They are switched by
 * RECTANGLE, not blended — and that seam is invisible by construction, because
 * the near window is grown a margin PAST the loaded tiles, and out there
 * `heightAt` is the overview, so both pyramids answer the same number in the
 * strip where the branch flips.
 *
 * WHAT IS NOT HERE ANY MORE: PER-PIECE FRUSTUM CULLING, AND THE FLAT-WORLD
 * SHORTCUT (2026-08-22, the "ground plate vanishes for single frames" finding).
 * Three things had grown together into one defect:
 *
 *  - a world whose OVERVIEW was level took `minLodDistance` 0 and was drawn
 *    from its roots — 3 to 4 pieces of 2 048 m for the whole visible world;
 *  - each of those pieces was frustum-tested against its own box, so a single
 *    verdict decided a square kilometre of ground;
 *  - and the verdict reached the GPU one frame late. three.js uploads an
 *    `InstancedBufferGeometry`'s dirty attributes in `projectObject`
 *    (`WebGLObjects.update`, "Update once per frame"), which runs over the whole
 *    scene BEFORE the first `object.onBeforeRender` — and the selection was
 *    written in `onBeforeRender`. `geometry.instanceCount` is read at draw time
 *    and was this frame's; the ROWS were the previous frame's. While the camera
 *    turned, the card therefore drew the first n entries of a list selected for
 *    a different heading: pieces missing, pieces drawn twice, and the isolation
 *    panel's toggle 20 (culling off) making the whole thing go away because a
 *    list that never changes cannot be stale.
 *
 * So the cull is gone (every square inside the world frame is emitted, and the
 * one draw call carries a few hundred instances instead of a few dozen), the
 * shortcut is gone (`MIN_LOD_DISTANCE_M` applies to a level world too), the
 * instance buffer is allocated once at `MAX_NODES` and never replaced, and the
 * selection runs in the TICK before `renderer.render` (`TerrainLod.update`).
 *
 * WHAT IS NOT HERE: the material. The ground keeps the material
 * `scene/ground.ts` builds for the default kind, with the basement hole
 * (`patchHole`) and the natural-ground stages (`applyNaturalGround`) already
 * in its `onBeforeCompile` slot. This module CHAINS one more patch onto it —
 * the vertex displacement — and never assigns, the rule of every shader patch
 * in this client.
 *
 * TWO MATERIAL VARIANTS SINCE K-A E3, AND DRY GROUND PAYS NOTHING FOR THE WET
 * (`recherche-wasser-v2.md` § 4 K-A "Risiken", the binding risk rule). The
 * water mirror is no longer a mesh of its own: the terrain vertex is lifted to
 * `max(h, w_level)` wherever the water raster has a value. That branch is four
 * more `texelFetch` and a comparison per VERTEX, and the whole point of K-A is
 * that a water pixel gets CHEAPER — so the branch may not ride along on the
 * ground of a world without a drop of water in it. Hence:
 *
 *  - the owner hands in TWO materials (`setMaterial`), built by the same
 *    chain, and this module patches one of them with the lift and one without.
 *    The dry one keeps the exact program and the exact `customProgramCacheKey`
 *    it had before this stage, so three hands it the very same
 *    `WebGLProgram` — asserted in `smoke_terrain_lod.mjs` [16];
 *  - the selection is PARTITIONED per frame: a piece whose closed rectangle
 *    touches a tile of the water raster goes into the wet instance buffer, and
 *    everything else into the dry one (`nodeHasWater`). Two draw calls where
 *    there is water, one where there is not.
 *
 * WHY THE PARTITION CANNOT CRACK THE GROUND, which is the only thing it could
 * do wrong. A vertex can only lift where the water pyramid answers a level,
 * and the pyramid is filled from `rasterLevelAt` — which answers out of ONE
 * tile, the tile the point lies in (`tileKeyAt`). A tile the server shipped no
 * `water` key for has no wet texel anywhere in its window, borders included
 * (`HeightModel.water_raster` answers None only when EVERY point of the window
 * is dry). So: if a point lifts, its tile is in the raster; a shared vertex of
 * two neighbouring pieces lies in BOTH pieces' closed rectangles, hence its
 * tile touches both, hence BOTH pieces are wet-gated and run the lifting
 * program. Two pieces can therefore never disagree about a vertex they share.
 * That is why the gate scans the CLOSED rectangle — `floor((x + size) / tileM)`
 * with no epsilon, unlike `nodeBounds`.
 *
 * NO WATER SHADING YET. E3 lifts the geometry and nothing else: a lifted pixel
 * is painted as the ground it replaces, which is the "visibly flat intermediate
 * state" the research asks for — the SHAPE of the mirror is judgeable before
 * its look exists (E4). The old polygon mirrors keep rendering this stage and
 * will cover most of the flat patch; E5 deletes them.
 */
import * as THREE from 'three';
import { finestStep, heightAt, latticeSample } from '@anima/scene-render';
import type { WorldHeightField, WorldHeightTiles } from '@anima/scene-render';
import { rasterLevelAt, waterBilinear } from './waterRaster';
import type { WaterRaster } from './waterRaster';

/**
 * Cells per axis of the one patch — 32, and the number is derived rather than
 * tasted.
 *
 * The server's fine lattice is 2 m and its mip pyramid has exactly five levels
 * above it (`MIP_LEVELS_M = 4, 8, 16, 32, 64`). With 32 cells a leaf node is
 * 32 · 2 = 64 m and its vertices land on EVERY support point of the base
 * lattice — one vertex per datum, never a subdivision of ground that carries
 * no more detail — and the six node steps that follow (2, 4, 8, 16, 32, 64 m)
 * are the base plus precisely those five declared levels. So every level this
 * renderer draws has a server-declared error bound, and none of them
 * extrapolates.
 *
 * 64 would halve the instance count (4 225 vertices per patch instead of
 * 1 089) at the price of a leaf of 128 m: the LOD would then be chosen in
 * 128 m lumps, which over the 520 m the haze leaves visible is four rings
 * instead of eight — coarser culling and a visibly steppier morph front. The
 * draw call count is 1 either way, so the trade buys nothing that matters
 * here.
 */
export const PATCH_N = 32;

/** How many node levels the quadtree may hold — the base lattice plus the five
 *  declared mip levels (see `PATCH_N`). Level 0 is the finest. */
export const MAX_LOD_LEVELS = 6;

/**
 * `lodRange[0]` in metres: how close the camera must be for the FINEST level.
 *
 * `lodRange[i] = MIN_LOD_DISTANCE_M · 2^i`, i.e. 128, 256, 512, 1024, 2048 m.
 * The scene haze closes at 520 m (`engine.ts`), so everything a player can see
 * is drawn at levels 0–2 (2, 4 and 8 m between vertices) — and 560 m is
 * exactly how far the fine tiles are loaded (`heightTiles.ts`
 * `HEIGHT_TILE_RADIUS_M`), so the near pyramid covers every node that is drawn
 * finer than the overview can answer. Past the haze the levels are a picture.
 */
export const MIN_LOD_DISTANCE_M = 128;

/** Where in a level's own RING the morph towards the parent starts, as a
 *  fraction of it: `s_i = range[i−1] + MORPH_START · (range[i] − range[i−1])`.
 *  Strugar's CDLOD paper calls for "the last half" of the ring, and the ring is
 *  what it has to be measured in — anchoring the ramp at the origin instead
 *  (`MORPH_START · range[i]`) is the same number only while the ranges double
 *  exactly, and the screen-space error rule widens them out of the doubling all
 *  the time. See `lodLambda`. Below `s_i` the piece draws its own lattice
 *  unblended, which is what makes the morph=0 path assertable against
 *  `heightAt`. */
export const MORPH_START = 0.5;

/**
 * THE CONTINUOUS LOD COORDINATE — how coarse the ground is at a distance of
 * `d` metres, as a real number rather than a level index.
 *
 * λ = Σ_i clamp( (d − s_i) / (range[i] − s_i), 0, 1 ),
 *     s_i = range[i−1] + MORPH_START · (range[i] − range[i−1]),  range[−1] = 0
 *
 * Read it term by term: level i's morph runs from 0 at `s_i` to 1 at
 * `range[i]`, and `s_i` lies INSIDE level i's own ring `[range[i−1], range[i]]`
 * — the last half of it, which is what Strugar's paper calls for. So the ramps
 * cannot overlap: for a distance inside ring i every nearer term has finished
 * (1) and every farther term has not begun (0), and λ(d) = i + morph. That
 * gives λ(range[i]) = i + 1 and λ(0) = 0 EXACTLY, whatever `lodRanges` did to
 * the boundaries.
 *
 * THE RAMP IS ANCHORED IN THE RING AND NOT AT THE ORIGIN (2026-08-22). It used
 * to be `MORPH_START · range[i]`, which is the same number only while the ranges
 * double exactly — and the screen-space error rule (`MAX_PIXEL_ERROR`) still
 * widens them out of the doubling, cap (`MAX_RANGE_WIDENING`) or no cap. On the
 * ranges the smoke's own `TR` fixture produces, [256, 512, 652, 1024, 2160,
 * 4096]: level 3 owns the ring [652, 1024], so its ramp belongs in
 * [652 + 0.5 · 372, 1024] = [838, 1024] — while the origin anchor would have
 * started it at 0.5 · 1024 = 512 m, 140 m before its own ring even begins. Where
 * a level-2 neighbour had finished morphing onto the level-3 lattice, the
 * level-3 piece had therefore ALREADY left it: a step in the ground along the
 * edge they share, which `smoke_terrain_lod.mjs` [12](nn) measures as part of
 * its red probe. λ(range[i]) = i + 1 is not a nicety, it is the identity the
 * whole seam argument rests on.
 *
 * WHY IT EXISTS AT ALL — this is the crack fix of 2026-08-21. Until now the
 * morph was ONE number per node, taken from the node's bounding-box distance
 * and handed to every one of its 1 089 vertices. Two neighbouring patches of
 * the SAME level whose box distances straddle the morph ramp therefore drew two
 * different polylines along the edge they share: measured on a rolling 6 m
 * relief, adjacent leaf nodes at morph 0.00 and 0.96 stood 0.61 m apart, i.e. a
 * 6.2-pixel hairline of sky at 127 m (fov 45°, 1 080 px). It reopened every
 * frame the camera moved, which is exactly the light-blue shimmer that was
 * reported.
 *
 * Driving the morph from λ AT THE VERTEX removes it by construction: the drawn
 * surface becomes a function of the world position alone — `tlodCompute` reads
 * the same λ, snaps to the same absolute world lattice and mixes the same two
 * mip levels, whoever draws the point — so two patches CANNOT disagree about a
 * vertex they share, whatever their own levels and distances are. That is
 * Strugar's own rule (CDLOD computes `morphK` per vertex from the vertex's
 * distance); the per-node shortcut was the deviation.
 */
export function lodLambda(d: number, ranges: readonly number[]): number {
  let lam = 0;
  let prev = 0;
  for (const r of ranges) {
    if (!(r > 0)) continue;
    const start = prev + MORPH_START * (r - prev);
    prev = r;
    // A ring of zero width (two equal ranges — only a hand-edited error list
    // can produce one) owns no level and no morph: λ steps over it. Nothing is
    // ever emitted at such a level, so the step is a function of the distance
    // alone and every piece reads it the same way.
    if (!(r > start)) {
      lam += d >= r ? 1 : 0;
      continue;
    }
    const t = (d - start) / (r - start);
    lam += t <= 0 ? 0 : t >= 1 ? 1 : t;
  }
  return lam;
}

/**
 * How many pixels of vertical error a level may show — the screen-space budget
 * the server's own bound is spent against.
 *
 * The distance rule alone knows nothing about the ground: on a world of
 * gentle meadows 128 m per level is generous, and on one full of cliffs the
 * same 128 m is a visible staircase. The server ships the exact bound per mip
 * level (`stats.err[k]`, § G2), so a level may only be used from
 * `err · pixelScale / MAX_PIXEL_ERROR` metres away, and the LOD ranges are
 * pushed out until that holds — by at most one doubling, see
 * `MAX_RANGE_WIDENING` for what an uncapped push cost.
 *
 * IT WIDENS THE RANGES, IT DOES NOT SPLIT SINGLE NODES, and that is a
 * correctness matter rather than a taste. CDLOD is crack-free because two
 * neighbouring nodes are at most one level apart AND the finer one has morphed
 * fully onto the coarser one's lattice by the time the coarser is chosen —
 * which holds only while both nodes measure against the SAME ranges. A
 * per-node error test would give a rugged node a finer level than its smooth
 * neighbour at the same distance, with no morph between them: a seam as tall
 * as the error it was meant to remove. So the error is taken per LEVEL, over
 * everything loaded, and moves the ring boundaries for the whole world at
 * once.
 */
export const MAX_PIXEL_ERROR = 2;

/**
 * How far the error rule may WIDEN a ring beyond its geometric size, as a
 * factor — 2 means "one doubling", i.e. the rule may push a level out by one
 * step of the ladder and no further.
 *
 * Measured on the live big world (2026-08-22): the mip errors grow by only
 * 2.2× over five levels (micro-relief painted ON the 2 m lattice costs its
 * full amplitude once decimated), so uncapped the rule widened the innermost
 * ring from 128 m to 1538 m and the finest pieces covered a 1.5 km disc —
 * 2952 pieces, 91.8 % of them behind the 520 m haze, scaling with draw-buffer
 * height until MAX_NODES was hit at 1530 px. Capped at one doubling the same
 * camera draws 372 pieces at 1280 px and 390 at 2160 px, and the ladder is
 * 256/512/1024/2048/3379/4096 m: the four inner rings sit AT the cap at both
 * viewports and are therefore resolution-independent — level for level the same
 * 67/58/59/65 pieces — while the rule keeps its job of shifting a level by one
 * step, which here it spends on level 4 (2048 → 3379 m). A jump from level 5 to
 * level 1 removed only 54 % of that error for 15× the pieces.
 */
export const MAX_RANGE_WIDENING = 2;

/** The base lattice step to fall back on when the payload names none, metres —
 *  the server's own `TILE_STEP_M`. It is only ever reached by a world with no
 *  relief at all, where the leaf size decides nothing but how many quads the
 *  flat ground is drawn as. */
const FALLBACK_BASE_STEP_M = 2;

/**
 * Ceiling on selected nodes per frame — AND the instance buffer's capacity,
 * allocated once and never re-allocated (`createTerrainLod`).
 *
 * A guard, not a working limit: with no frustum culling left (2026-08-22) the
 * whole world frame is selected every frame and the working case is a few
 * hundred pieces — `smoke_terrain_lod.mjs` [13] sweeps the full compass over
 * three worlds and reports the maximum it reaches. Without a ceiling a
 * pathological camera (inside the ground, at the origin of a 100 km world)
 * would walk the whole quadtree.
 *
 * REACHING IT IS NO LONGER A TRUNCATION (2026-08-22, second finding). While the
 * error rule was uncapped the live 16.6 km world reached it at a 1 530 px
 * viewport, and what the depth-first walk had not got to yet was ground nobody
 * drew — 30 % of the frame at 2 160 px, the nearest missing square 240 m from
 * the camera. `MAX_RANGE_WIDENING` takes that particular world back to a few
 * hundred pieces, but the cap is a statement about how far a level may be
 * pushed and the ceiling has to hold for any error list at all. So every
 * selection goes through `selectLodFitted`, which COARSENS the rings until the
 * set fits instead of dropping its tail; the early return inside
 * `selectLodNodes` is what tells it the cap was reached.
 * `smoke_terrain_lod.mjs` [14] drives it by handing the UNCAPPED ladder in as
 * `LodSelectOpts.ranges` — the world that really overran the buffer.
 */
export const MAX_NODES = 4096;

/** Texels per axis the near pyramid may have. 1025 at a 2 m step is 2 048 m,
 *  nearly twice the 1 120 m the tile radius can span — the cap is a memory
 *  guard for a world with a different tile size, never the working case.
 *  1025² floats plus the mip chain is 5.6 MB. */
const NEAR_MAX_TEXELS = 1025;

/** How far past the loaded tiles the near window reaches, in metres. It has to
 *  be at least one OVERVIEW cell so the rectangle the shader switches on lies
 *  in ground where near and far answer the same number — see the file header.
 *  Two overview cells, floor 16 m, is that with room to spare. */
const NEAR_MARGIN_CELLS = 2;
const NEAR_MARGIN_MIN_M = 16;

// ── The pyramid ────────────────────────────────────────────────────────────

/** One level of a height pyramid: its lattice and where its rows sit in the
 *  packed texture. The ORIGIN is the pyramid's — decimation keeps it. */
export interface PyramidLevel {
  cols: number;
  rows: number;
  step: number;
  /** First row of this level inside the packed data, in texels. */
  row0: number;
}

/**
 * A height pyramid, packed for ONE texture.
 *
 * The levels are stacked vertically in a single `Float32Array` of `texW ×
 * texH`, because GLSL ES 3.00 forbids indexing an array of SAMPLERS with a
 * value that is not a constant expression — while indexing an array of `vec4`
 * with the per-instance level is perfectly legal. So the level is a lookup in
 * a uniform array and the sampler never changes.
 */
export interface HeightPyramid {
  originX: number;
  originZ: number;
  /** Metres between support points of level 0. */
  step: number;
  levels: PyramidLevel[];
  data: Float32Array;
  texW: number;
  texH: number;
}

/**
 * Build a pyramid by sampling `at` on the base lattice and DECIMATING upwards.
 *
 * `levelCount` is a wish: a level with fewer than two support points per axis
 * carries no surface and ends the chain.
 *
 * DECIMATION, NOT AVERAGING, and that is the contract of § G2: the coarse
 * lattice is a SUBSET of the fine one, so taking every second point IS the
 * height function on the coarse lattice — the very grid the server computed
 * `err[k]` against. An averaging (box) filter would produce a surface no
 * lattice of the model describes and the error bound would stop being a bound.
 */
export function buildPyramid(at: (x: number, z: number) => number,
                             originX: number, originZ: number, step: number,
                             cols: number, rows: number,
                             levelCount: number): HeightPyramid {
  const levels: PyramidLevel[] = [];
  let c = Math.max(2, Math.floor(cols));
  let r = Math.max(2, Math.floor(rows));
  let s = step;
  let height = 0;
  for (let k = 0; k < levelCount; k += 1) {
    levels.push({ cols: c, rows: r, step: s, row0: height });
    height += r;
    const nc = Math.floor((c - 1) / 2) + 1;
    const nr = Math.floor((r - 1) / 2) + 1;
    if (nc < 2 || nr < 2) break;
    c = nc;
    r = nr;
    s *= 2;
  }
  const texW = levels[0].cols;
  const data = new Float32Array(texW * height);
  const base = levels[0];
  for (let j = 0; j < base.rows; j += 1) {
    const z = originZ + j * step;
    const row = j * texW;
    for (let i = 0; i < base.cols; i += 1) {
      data[row + i] = at(originX + i * step, z);
    }
  }
  for (let k = 1; k < levels.length; k += 1) {
    const lv = levels[k];
    const prev = levels[k - 1];
    for (let j = 0; j < lv.rows; j += 1) {
      const src = (prev.row0 + j * 2) * texW;
      const dst = (lv.row0 + j) * texW;
      for (let i = 0; i < lv.cols; i += 1) data[dst + i] = data[src + i * 2];
    }
  }
  return { originX, originZ, step, levels, data, texW, texH: height };
}

/**
 * The height a pyramid answers at (x, z) on level `k` — the CPU MIRROR of the
 * shader's `tlodGrid`, arithmetic for arithmetic.
 *
 * It runs through `latticeSample`, the same function `sampleWorldHeight` runs
 * through, so the only thing that could differ between CPU and GPU is the
 * fetch — and the smoke reimplements that fetch on its own to keep the check
 * independent of this very line.
 */
export function pyramidHeight(pyr: HeightPyramid | null, x: number, z: number,
                              k: number): number {
  if (!pyr) return 0;
  const lv = pyr.levels[Math.max(0, Math.min(k, pyr.levels.length - 1))];
  if (!lv) return 0;
  return latticeSample(
    (i, j) => pyr.data[(lv.row0 + j) * pyr.texW + i] ?? 0,
    lv.cols, lv.rows, pyr.originX, pyr.originZ, lv.step, x, z);
}

/**
 * The WATER pyramid — the same construction as the height one, and the same
 * decimation (Wasser v2, K-A E2).
 *
 * IT IS `buildPyramid`, deliberately and without a rule of its own. Two things
 * had to be decided and both come out the same way as for the heights:
 *
 * **THE DECIMATION IS A SUBSET, not an average.** The mirror is PIECEWISE
 * LINEAR — `water_level_at` interpolates linearly between two knots along the
 * axis — so taking every second support point IS the mirror on the coarse
 * lattice, exactly as decimating a height field is the height function on it.
 * A box filter would produce a surface no profile describes, and would smear
 * the shore: at a rim texel it would mix the level with its dilated neighbour
 * and move the mirror by a fraction of the ring, i.e. invent water. `min` was
 * the other candidate (it would guarantee "never above the ground next door")
 * and is wrong for the same reason — it is a different surface, and under K-A
 * the ground is lifted to `max(h, level)`, so nothing needs the mirror to be
 * pessimistic.
 *
 * **A COARSE TEXEL IS WATER EXACTLY WHEN ITS OWN BASE TEXEL IS.** The mask
 * decimates WITH the level because it IS the level: NaN is the sentinel, and a
 * NaN copied by the decimation is the same statement one level up. Any other
 * rule ("water if ANY of the four base texels is water", "…if all four are")
 * would be a second book about where the water is, kept beside the first one
 * and free to disagree with it.
 *
 * THE PRICE, stated: the dilation ring is two texels wide on level 0, one on
 * level 1 and gone above it, while a bilinear read needs sqrt(2) TEXELS at
 * every level. So the server's guarantee — every point inside a water polygon
 * reads four wet corners — holds on the BASE lattice and is not claimed above
 * it. That is a deliberate server-side choice (`WATER_RASTER_DILATION_STEPS`):
 * covering level 5 would mean painting the mirror 92 m into the land. What a
 * coarse level gets wrong at a shore is a fringe the fragment MASK covers
 * (K-A E4), never a hole in the ground — the ground is the height pyramid's.
 */
export function buildWaterPyramid(at: (x: number, z: number) => number,
                                  originX: number, originZ: number,
                                  step: number, cols: number, rows: number,
                                  levelCount: number): HeightPyramid {
  return buildPyramid(at, originX, originZ, step, cols, rows, levelCount);
}

/**
 * `wlevelAt` — the water level a pyramid answers at (x, z) on level `k`, NaN
 * where there is none. The CPU twin of the GLSL of the same name that K-A E3
 * will put beside `tlodHeight`.
 *
 * It does NOT go through `latticeSample`: that one mixes all four corners
 * unconditionally, and here a corner with weight 0 must not be read at all —
 * see `waterRaster.waterBilinear` for the finding (a sample on a lattice line
 * would otherwise be dragged to NaN by a dry texel that contributes nothing,
 * eroding the dilation ring along a grid of lines through every water). The
 * cell arithmetic above it is the same three lines, clamp for clamp, so the
 * water and the height of one point are read out of the same cell.
 */
export function wlevelAt(pyr: HeightPyramid | null, x: number, z: number,
                         k: number): number {
  if (!pyr) return NaN;
  const lv = pyr.levels[Math.max(0, Math.min(k, pyr.levels.length - 1))];
  if (!lv || lv.cols < 2 || lv.rows < 2 || !(lv.step > 0)) return NaN;
  const frac = (v: number, n: number): [number, number] => {
    const c = v < 0 ? 0 : v > n - 1 ? n - 1 : v;
    const i = Math.min(Math.floor(c), n - 2);
    return [i, c - i];
  };
  const [i, tx] = frac((x - pyr.originX) / lv.step, lv.cols);
  const [j, tz] = frac((z - pyr.originZ) / lv.step, lv.rows);
  const at = (a: number, b: number): number => {
    const v = pyr.data[(lv.row0 + b) * pyr.texW + a];
    return typeof v === 'number' ? v : NaN;
  };
  return waterBilinear(at(i, j), at(i + 1, j), at(i, j + 1), at(i + 1, j + 1),
                       tx, tz);
}

/** Which level of the pyramid draws a node whose vertices are `stepM` apart —
 *  `round(log2(stepM / baseStep))`, clamped into the chain. The same three
 *  lines run in the shader (`tlodLevel`). */
export function pyramidLevelFor(pyr: HeightPyramid | null, stepM: number): number {
  if (!pyr || !(pyr.step > 0)) return 0;
  const k = Math.round(Math.log2(Math.max(stepM / pyr.step, 1)));
  return Math.max(0, Math.min(k, pyr.levels.length - 1));
}

// ── The quadtree ───────────────────────────────────────────────────────────

/**
 * One selected piece of terrain: its south-west corner and edge length in world
 * metres, the level it draws at, and how many patch cells per axis that costs.
 *
 * `cells` is `PATCH_N` for a WHOLE node and `PATCH_N / 2` for a parent QUADRANT
 * — the out-of-range rule of `selectLodNodes` emits those, and they carry the
 * parent's vertex spacing over a child-sized square. The vertex spacing is
 * therefore always `size / cells = baseStep · 2^level`, and the level alone
 * says how dense the piece is drawn.
 *
 * `morph` is the morph coordinate at the piece's NEAREST point,
 * `max(lodLambda(d_min) − level, 0)`: 0 = its own lattice, 1 = exactly the
 * parent's. For every piece but a root it stays in [0, 1] since the
 * out-of-range rule of `selectLodNodes` (2026-08-22) — a piece is never emitted
 * at a level whose ring it lies outside. It is a DIAGNOSTIC and the input of
 * the arithmetic twin `morphedVertex`; the renderer hands the shader the LEVEL
 * and lets every vertex read its own λ (see `lodLambda`), because one number
 * per node is what cracked the ground before.
 */
export interface LodNode {
  x: number;
  z: number;
  size: number;
  level: number;
  cells: number;
  morph: number;
}

/** What `selectLodNodes` has to be told. Everything is plain numbers and
 *  callbacks so the selection can be derived by hand in a smoke without a
 *  camera, a renderer or a world. */
export interface LodSelectOpts {
  /** The world rectangle the terrain covers. */
  x0: number;
  z0: number;
  x1: number;
  z1: number;
  /** Edge length of a LEAF node (level 0), metres. */
  leafM: number;
  /** How many levels the tree may have (leaf included). */
  levels: number;
  /** `lodRange[0]`, metres. 0 switches the distance rule off entirely and
   *  selects nothing but roots. The renderer never passes it — the rings apply
   *  to every world, a level one included (see `createTerrainLod`); it is kept
   *  because it is what makes `lodRanges` a total function and the smoke
   *  derives the degenerate case from it. */
  minLodDistance: number;
  /** Where the camera is. */
  camX: number;
  camY: number;
  camZ: number;
  /** The vertical box of a node — `{ min, max }` in metres. */
  boundsOf: (x: number, z: number, size: number) => { min: number; max: number };
  /** The largest vertical error in metres that DRAWING AT LEVEL i costs,
   *  anywhere in the loaded world (`levelErrorM[i]`, from the server's
   *  `stats.err`). Missing or 0 switches the error rule off for that level. */
  levelErrorM?: readonly number[];
  /** Pixels per metre of vertical error at one metre of distance —
   *  `viewportHeightPx / (2 · tan(fovY/2))`. 0 switches the error rule off. */
  pixelScale?: number;
  /**
   * The ring boundaries to select against, metres — normally left out, and
   * then `lodRanges` is asked for them.
   *
   * IT EXISTS SO THE SELECTION AND THE SHADER CANNOT DESCRIBE TWO WORLDS.
   * `selectLodFitted` may COARSEN the rings to stay under `MAX_NODES`, and the
   * per-vertex morph reads its own λ out of `uTlodRange`: if the renderer
   * uploaded the honest ranges while the selection had used coarsened ones,
   * every piece would morph against a ring it was not chosen for — the exact
   * disagreement `lodLambda` exists to rule out. So the fitted ranges are
   * handed BACK to the caller and handed IN here, one array for both.
   */
  ranges?: readonly number[];
}

/**
 * The LOD ring boundaries in metres, `lodRange[i]` per level.
 *
 * Two terms, and the larger wins per level:
 *  - the geometric one, `minLodDistance · 2^i` — one halving of the vertex
 *    density per doubling of the distance, which is what keeps the number of
 *    vertices per pixel constant;
 *  - the ERROR one, `levelErrorM[i+1] · pixelScale / MAX_PIXEL_ERROR` — the
 *    nearest distance at which level i+1 stays inside its pixel budget. It
 *    lands on `lodRange[i]` because that is the boundary level i+1 begins at,
 *    and it is CAPPED at `MAX_RANGE_WIDENING` times the geometric ring.
 *
 * THE CAP MAKES THE LADDER MONOTONE BY CONSTRUCTION (2026-08-22), and the line
 * that repaired it afterwards is kept as the belt to that braces:
 *   `g_i ≤ range[i] ≤ MAX_RANGE_WIDENING · g_i = g_(i+1) ≤ range[i+1]`
 * with `g_i = minLodDistance · 2^i`, whatever the error list says. Before the
 * cap the error term could invert the ladder — a big `err[1]` beside a small
 * `err[2]` really did produce a ring starting inside the one before it, which
 * selects a coarse node inside a fine ring and cracks the ground.
 * `smoke_terrain_lod.mjs` [4](l) derives both, the capped ladder and the
 * inversion the uncapped one still shows.
 *
 * `minLodDistance` 0 answers "every range is 0", i.e. nothing is ever split and
 * the terrain is drawn from its roots. NOTHING PASSES IT ANY MORE (2026-08-22):
 * it used to be what a world with no relief got, and a world drawn in 2 048 m
 * lumps is one whose every per-frame decision is a decision about a square
 * kilometre. The rings apply to every world now; the degenerate case survives
 * as the boundary the smoke derives the ring arithmetic against.
 */
export function lodRanges(minLodDistance: number, levels: number,
                          levelErrorM?: readonly number[],
                          pixelScale?: number): number[] {
  const out: number[] = [];
  const scale = pixelScale && pixelScale > 0 ? pixelScale : 0;
  for (let i = 0; i < levels; i += 1) {
    let r = minLodDistance * (1 << i);
    const err = levelErrorM?.[i + 1] ?? 0;
    if (minLodDistance > 0 && scale > 0 && err > 0) {
      // The error term, capped at MAX_RANGE_WIDENING times the geometric ring:
      // the rule may shift a level by one step, never buy fine detail for
      // ground the haze has already replaced.
      r = Math.max(r, Math.min((err * scale) / MAX_PIXEL_ERROR,
                               r * MAX_RANGE_WIDENING));
    }
    if (i > 0 && r < out[i - 1]) r = out[i - 1];
    out.push(r);
  }
  return out;
}

/** What `nodeBounds` needs of one tile's statistics — the height span, and
 *  nothing else. Structural on purpose, so the check can hand in plain
 *  objects. */
export interface NodeStatSpan {
  min: number;
  max: number;
}

/** What the level-error rule needs of one tile's statistics: one exact
 *  vertical error bound per entry of the server's `mip_levels_m`. Structural
 *  like `NodeStatSpan`, and for the same reason. */
export interface LevelErrorStat {
  err?: readonly number[];
}

/**
 * The worst vertical error per NODE LEVEL, in metres — the pure rule behind
 * `TerrainLod.setField`/`refreshStats`.
 *
 * Level L draws its vertices `baseStepM · 2^L` apart, which for L ≥ 1 is one
 * of the server's declared `mipLevelsM`; level 0 is the base lattice and has
 * no error at all. The maximum is taken over EVERY tile a statistic is known
 * for, because `lodRanges` turns it into world-wide ring distances — a
 * per-node maximum would give two neighbours different rings and crack the
 * ground along the seam.
 *
 * THAT IS WHY THE STATISTICS HAVE TO BE COMPLETE. `GET /play/heightfield`
 * ships at most `TILE_STATS_MAX` = 64 of them; over a maximum, a missing tile
 * is not a small error but no error at all, so a world of 200 tiles reported
 * the roughness of its first 64 and the rings came out too wide — distant
 * ground drawn at a level whose real error is several times the pixel budget.
 * `scene/ground.ts` fetches the remainder (`GET /play/heightfield/stats`) and
 * calls `refreshStats`.
 *
 * AND THE LIFTED MIRROR STAYS INSIDE IT (Wasser v2, K-A E3). The drawn surface
 * of the water variant is `y_k = max(h_k, w_k)` per level, and for any four
 * numbers `|max(a,b) − max(c,d)| ≤ max(|a−c|, |b−d|)`, so the lifted level-k
 * error is bounded by `max(err_h[k], err_w[k])` — the height's own bound and
 * the MIRROR's decimation error, whichever is larger. The mirror's is the
 * smaller of the two wherever the two are comparable, and the reason is the
 * carve: `h = min(h, level_at − depth·smoothstep(…))` writes the mirror's own
 * variation INTO the bed and then adds the shore ramp on top of it, so under a
 * water the coarse lattice loses at least as much of the bed as it loses of
 * the mirror. A LIFTED MIRROR IS FLATTER THAN THE BED IT COVERS, which is why
 * the statistics are left as the server bakes them (height-only) rather than
 * re-derived over a second field.
 *
 * WHERE THAT ARGUMENT IS NOT A PROOF, stated: the ramp could in principle
 * cancel a mirror step over one coarse cell, and then `err_w[k]` would exceed
 * `err_h[k]`. The consequence is bounded and benign — `lodRanges` would put a
 * ring boundary slightly nearer than the mirror deserves, i.e. a far mirror
 * drawn one level too coarse. It cannot crack anything (see `MAX_PIXEL_ERROR`:
 * the rule moves rings for the whole world, never single nodes).
 *
 * EXTRACTED FROM THE RENDERER so the check measures the shipped rule rather
 * than a copy of it — the reason `nodeBounds` stands up here too.
 */
export function levelErrorsFrom(
  stats: ReadonlyMap<string, LevelErrorStat> | null | undefined,
  mipLevelsM: readonly number[] | null | undefined,
  baseStepM: number, levels: number): number[] {
  const out = new Array<number>(Math.max(0, levels)).fill(0);
  if (!stats?.size || !mipLevelsM?.length || !(baseStepM > 0)) return out;
  for (let level = 1; level < out.length; level += 1) {
    const k = mipLevelsM.indexOf(baseStepM * (1 << level));
    if (k < 0) continue;
    let err = 0;
    for (const s of stats.values()) {
      const v = s.err?.[k];
      if (typeof v === 'number' && v > err) err = v;
    }
    out[level] = err;
  }
  return out;
}

/** How many tiles a node's box may be unioned over before the whole field's
 *  range is taken instead. A root node of 2 048 m over 256 m tiles covers
 *  exactly 64, so the shortcut never fires for a node the quadtree really has
 *  — it is the guard for a world whose `tile_m` is small. */
const STAT_TILE_SCAN_MAX = 64;

/**
 * The vertical box of a node, from the tile statistics where there are any —
 * `{ min, max }` in metres.
 *
 * A node covering several tiles takes the UNION; a node the statistics say
 * nothing about takes the whole field's range, which culls nothing and is
 * never wrong.
 *
 * WHAT IT IS FOR, since the frustum cull was deleted (2026-08-22): the LOD
 * DISTANCE and nothing else. `selectLodNodes` measures to the node's box, so a
 * node high on a cliff must not be treated as if its ground lay at zero — the
 * box is what makes "distance to the node" mean the distance to the ground the
 * node draws. It used to be the box the frustum test culled against as well,
 * and being a hair too small was fatal there; being a hair too small here costs
 * a slightly wrong level at the far end of a ring and nothing more.
 *
 * It IS a bound either way, twice over — a tile's `min`/`max` are read off its
 * own 2 m raster, the drawn surface inside that tile is the bilinear of the
 * very same numbers (and every coarser mip is a SUBSET of them,
 * `buildPyramid`), so no vertex can leave the span.
 *
 * THE WATER LIFT IS NOT REBUILT INTO IT (Wasser v2, K-A E3), and the argument
 * is worth writing down rather than re-deriving. A tile's `min`/`max` are read
 * off `heights` alone — the server says so explicitly (§ "Signatur und
 * Statistik": the mirror does not move `h`) — so a node whose ground is lifted
 * to `max(h, w)` can stand ABOVE its own box, by at most the water's depth
 * there (inside a lake the carve puts every `h` under the mirror, so the whole
 * tile can be one bed and its `max` a metre or two below the level). What that
 * costs is stated in the paragraph above and nothing more: the box is the LOD
 * DISTANCE and the distance alone since the frustum cull was deleted, so a box
 * a metre too low means a node measured a metre too far away — against ring
 * boundaries of 128 m and up, a level that is occasionally one ring late at the
 * outer edge of its ring. It cannot open a seam: the morph argument does not
 * mention the box at all, and `lodRanges` moves the rings for the WHOLE world
 * at once, so two neighbours always measure against the same ladder.
 *
 * EXTRACTED FROM THE RENDERER (2026-08-21) so the checks measure the shipped
 * rule rather than a copy of it.
 */
export function nodeBounds(stats: ReadonlyMap<string, NodeStatSpan> | null | undefined,
                           tileM: number,
                           globalRange: NodeStatSpan,
                           x: number, z: number, size: number): NodeStatSpan {
  if (!stats?.size || !(tileM > 0)) return globalRange;
  let min = Infinity;
  let max = -Infinity;
  // `Math.floor` and never `Math.trunc`: the world reaches west and north of
  // the origin, and truncation would file every node at x < 0 or z < 0 under
  // the tile one step east/south of the one it really covers.
  const tx0 = Math.floor(x / tileM);
  const tx1 = Math.floor((x + size - 1e-6) / tileM);
  const tz0 = Math.floor(z / tileM);
  const tz1 = Math.floor((z + size - 1e-6) / tileM);
  const covered = (tx1 - tx0 + 1) * (tz1 - tz0 + 1);
  if (covered > STAT_TILE_SCAN_MAX) return globalRange;
  let seen = 0;
  for (let tz = tz0; tz <= tz1; tz += 1) {
    for (let tx = tx0; tx <= tx1; tx += 1) {
      const s = stats.get(`${tx},${tz}`);
      if (!s) continue;
      seen += 1;
      if (s.min < min) min = s.min;
      if (s.max > max) max = s.max;
    }
  }
  // A node that reaches past the indexed tiles reaches over flat ground
  // (an unindexed tile IS the flat world), so 0 belongs in its box.
  if (!seen) return globalRange;
  if (seen < covered) { min = Math.min(min, 0); max = Math.max(max, 0); }
  return { min, max };
}

/**
 * How many tiles a node's CLOSED rectangle may be probed over before the water
 * gate answers "wet" without looking.
 *
 * A root node is 2 048 m (`PATCH_N · baseStep · 2^5` at the live 2 m step) and
 * the live world's `tile_m` is 256 m, so the largest node this quadtree emits
 * spans 9 × 9 = 81 tiles once the closed rectangle is counted — the cap is that
 * number, so the shortcut never fires for a node the tree really has. For a
 * world with smaller tiles it fires on the biggest nodes and puts them on the
 * lifting program without a scan, which is the SAFE direction: over-marking a
 * piece costs it four `texelFetch` per vertex and draws the identical ground,
 * while under-marking one is the only thing that could crack the seam.
 */
const WATER_TILE_SCAN_MAX = 81;

/**
 * DOES THIS PIECE OF TERRAIN NEED THE LIFTING PROGRAM? — the gate of the
 * second material variant (Wasser v2, K-A E3).
 *
 * `tiles` is the key set of the WATER raster, i.e. exactly the tiles the
 * server shipped a `water` field for (`HeightModel.water_raster` answers None
 * for a window without a single wet or dilated point, and `scene/ground.ts`
 * files nothing under that key then). So "this tile is in the set" is the
 * cheapest complete statement of "somewhere in this tile a vertex could lift",
 * and it costs a `Set.has` per tile a piece touches — a leaf touches one or
 * two.
 *
 * THE RECTANGLE IS CLOSED: `floor((x + size) / tileM)` and NOT the `− 1e-6` of
 * `nodeBounds`. A node's last row of vertices sits exactly ON `x + size`, and
 * `tileKeyAt` files that coordinate under the NEXT tile — so the water a
 * vertex there could read lives in a tile the epsilon would have dropped. With
 * the closed rectangle a vertex shared by two pieces is covered by both, which
 * is the whole crack-freeness argument of the partition (file header).
 *
 * IT IS A PURE RULE and exported for the same reason `nodeBounds` is: the
 * check measures the shipped gate rather than a copy of it.
 */
export function nodeHasWater(tiles: ReadonlySet<string> | null | undefined,
                             tileM: number,
                             x: number, z: number, size: number): boolean {
  if (!tiles?.size || !(tileM > 0)) return false;
  // `Math.floor` and never `Math.trunc`, for the reason `nodeBounds` gives:
  // the world reaches west and north of the origin.
  const tx0 = Math.floor(x / tileM);
  const tx1 = Math.floor((x + size) / tileM);
  const tz0 = Math.floor(z / tileM);
  const tz1 = Math.floor((z + size) / tileM);
  if ((tx1 - tx0 + 1) * (tz1 - tz0 + 1) > WATER_TILE_SCAN_MAX) return true;
  for (let tz = tz0; tz <= tz1; tz += 1) {
    for (let tx = tx0; tx <= tx1; tx += 1) {
      if (tiles.has(`${tx},${tz}`)) return true;
    }
  }
  return false;
}

/** Distance from a point to an axis-aligned box, metres — 0 inside it. */
function boxDistance(px: number, py: number, pz: number,
                     x0: number, y0: number, z0: number,
                     x1: number, y1: number, z1: number): number {
  const dx = Math.max(x0 - px, 0, px - x1);
  const dy = Math.max(y0 - py, 0, py - y1);
  const dz = Math.max(z0 - pz, 0, pz - z1);
  return Math.sqrt(dx * dx + dy * dy + dz * dz);
}

/**
 * Which pieces of terrain are drawn, at which level, morphed how far.
 *
 * THE RULE, top down from the roots (Strugar CDLOD):
 *
 *   `lodRange[i] = max( minLodDistance · 2^i,
 *                       min( levelErrorM[i+1] · pixelScale / MAX_PIXEL_ERROR,
 *                            minLodDistance · 2^i · MAX_RANGE_WIDENING ) )`;
 *   a node at level L is SPLIT when the camera is nearer than `lodRange[L−1]`
 *   — i.e. level L owns the ring `[lodRange[L−1], lodRange[L])`;
 *   otherwise it is SELECTED, and `morph` records `lodLambda(d) − L` at its
 *   nearest point (a diagnostic — the shader morphs per VERTEX, `lodLambda`).
 *
 * THE OUT-OF-RANGE RULE, and it is the T-junction fix of 2026-08-22. A node is
 * NEVER drawn at a level whose ring it does not lie in. When a node at level
 * L+1 splits because SOME child needs level L, the children that do not — the
 * far ones, whose own box distance has already reached `lodRange[L]` — are not
 * emitted at level L. The PARENT draws those quadrants itself, at level L+1, as
 * a piece of `size / 2` with `PATCH_N / 2` cells: the parent's vertex spacing
 * over the child's square.
 *
 * WHAT THAT BUYS, and what it does not. Every emitted piece then satisfies
 * `lodRange[L−1] ≤ d < lodRange[L]` at its NEAREST point, so its own `morph` is
 * in [0, 1] — measured over a 144-camera sweep, 0 pieces outside their ring
 * against 12 587 under the old rule, two pieces in five of what it drew. And a
 * far child that used to be drawn at the finer level is now drawn as its
 * parent's quadrant: the same ONE instance either way, but at the parent's
 * spacing, so it costs a quarter of the triangles (335 275 per frame against
 * 436 779, [12](pp)).
 *
 * IT DOES NOT, on its own, close the T-junctions. A piece is as wide as its own
 * ring here (`size = range[L] / 2` and the ring is `[range[L]/2, range[L]]`), so
 * its OUTER strip still reaches into the next ring however it was selected, and
 * there λ − L is above 1 whatever selection did. What closes the seam is that
 * the morph is read at the vertex's block (`lodVertex`) and that λ's ramps sit
 * inside their own rings (`lodLambda`); this rule keeps those coarse blocks rare
 * and the far ground cheap. See the file header for the three together.
 *
 * THE ERROR TERM IS INSIDE THE RANGE, not a second test beside it — see
 * `MAX_PIXEL_ERROR` for why a per-node error test cracks the ground.
 * `levelErrorM[i+1]` is what level i+1 would cost, so it is `lodRange[i]` — the
 * boundary at which level i+1 is allowed to start — that has to move.
 *
 * DISTANCE IS 3D and measured to the node's BOX, not to its centre: a node
 * 512 m wide whose near edge is under the camera must not be treated as
 * 256 m away, and a camera high over a valley must not pull the valley floor
 * to the finest level because it is directly below.
 *
 * THERE IS NO FRUSTUM TEST HERE, AND THAT IS THE 2026-08-22 DECISION. Every
 * square inside the world frame is emitted, whatever the camera looks at. The
 * per-piece cull it replaces was measured to drop ground that was on screen:
 * with the OLD flat-world shortcut the whole visible world was 3–4 pieces of
 * 2 048 m, so one rejected piece was a square kilometre of sky — and because
 * three.js uploads an `InstancedBufferGeometry`'s attributes in `projectObject`
 * BEFORE it calls the mesh's `onBeforeRender` (three 0.185.1, `WebGLObjects.
 * update` "Update once per frame"), the GPU drew the PREVIOUS frame's node list
 * under the CURRENT frame's `instanceCount`. A list that changes every frame
 * (which is what culling makes it) therefore drew a set that had never been
 * selected for any camera. Both halves are gone: the list is written before the
 * render (`TerrainLod.update`) and it no longer depends on the heading at all,
 * so a stale upload cannot even arise. What the cull saved is a few hundred
 * instances of ONE draw call; what it cost was the ground.
 */
export function selectLodNodes(o: LodSelectOpts): LodNode[] {
  const out: LodNode[] = [];
  const levels = Math.max(1, Math.min(Math.floor(o.levels), MAX_LOD_LEVELS));
  const leaf = o.leafM;
  if (!(leaf > 0) || !(o.x1 > o.x0) || !(o.z1 > o.z0)) return out;
  const top = levels - 1;
  const ranges = o.ranges
    ?? lodRanges(o.minLodDistance, levels, o.levelErrorM, o.pixelScale);

  /** A square's box distance, or `null` when it is off the world frame — the
   *  ONE reason a square is dropped since 2026-08-22. Computed ONCE per square
   *  and handed on, so a child is never measured twice: the quadrant rule needs
   *  the child's distance in the parent's loop and the child's own recursion
   *  needs the same number. */
  const probe = (x: number, z: number, size: number): number | null => {
    if (x >= o.x1 || z >= o.z1 || x + size <= o.x0 || z + size <= o.z0) return null;
    const b = o.boundsOf(x, z, size);
    return boxDistance(o.camX, o.camY, o.camZ,
                       x, b.min, z, x + size, b.max, z + size);
  };

  const emit = (x: number, z: number, size: number, level: number,
                cells: number, d: number): void => {
    // The morph at the piece's NEAREST point. For every piece but a root it is
    // in [0, 1] by construction — `lodRange[level−1] ≤ d < lodRange[level]`
    // holds after the out-of-range rule, and λ(lodRange[i]) = i + 1 exactly
    // (`lodLambda`). A root has no coarser level to be pushed up to and simply
    // keeps counting past 1 out there. `smoke_terrain_lod.mjs` [12] asserts it.
    out.push({ x, z, size, level, cells,
               morph: Math.max(lodLambda(d, ranges) - level, 0) });
  };

  const visit = (x: number, z: number, level: number, d: number): void => {
    if (out.length >= MAX_NODES) return;
    const size = leaf * (1 << level);
    const inner = level > 0 ? ranges[level - 1] : 0;
    if (inner > 0 && d < inner) {
      const half = size / 2;
      for (let q = 0; q < 4; q += 1) {
        const cx = x + ((q & 1) ? half : 0);
        const cz = z + ((q & 2) ? half : 0);
        const cd = probe(cx, cz, half);
        if (cd === null) continue;
        // THE OUT-OF-RANGE RULE: a child past `lodRange[level − 1]` is not a
        // level-(level − 1) node. Its quadrant is drawn by THIS node instead.
        if (cd < inner) visit(cx, cz, level - 1, cd);
        else emit(cx, cz, half, level, PATCH_N / 2, cd);
        if (out.length >= MAX_NODES) return;
      }
      return;
    }
    emit(x, z, size, level, PATCH_N, d);
  };

  const rootSize = leaf * (1 << top);
  const rx0 = Math.floor(o.x0 / rootSize);
  const rx1 = Math.floor((o.x1 - 1e-6) / rootSize);
  const rz0 = Math.floor(o.z0 / rootSize);
  const rz1 = Math.floor((o.z1 - 1e-6) / rootSize);
  for (let rz = rz0; rz <= rz1; rz += 1) {
    for (let rx = rx0; rx <= rx1; rx += 1) {
      const d = probe(rx * rootSize, rz * rootSize, rootSize);
      if (d !== null) visit(rx * rootSize, rz * rootSize, top, d);
    }
  }
  return out;
}

/** What `selectLodFitted` answers: the pieces, the rings they were chosen
 *  against, and how many times those rings had to be halved to fit. */
export interface LodSelection {
  nodes: LodNode[];
  /** The rings the selection really used — what the shader must morph against
   *  (`LodSelectOpts.ranges`). */
  ranges: number[];
  /** 0 = the honest rings fitted. n > 0 = they were halved n times. */
  coarsenings: number;
}

/**
 * How often the rings may be halved before the attempt is given up. Each step
 * quarters the area of the finest ring, so eight of them divide it by 65 536 —
 * far past the point where every ring has collapsed and the tree is drawn from
 * its roots, which is the coarsest picture there is.
 */
const MAX_FIT_STEPS = 8;

/** Whether the coarsening has already been reported this session — the log is
 *  a one-shot, since the condition holds for every frame while it holds at
 *  all and a per-frame warning would be a stream. */
let fitWarned = false;

/**
 * THE SELECTION, GUARANTEED TO FIT — `selectLodNodes` with the ceiling turned
 * from a silent truncation into a deliberate coarsening.
 *
 * WHY IT EXISTS (finding 2026-08-22). `MAX_NODES` was described as a guard
 * against a pathological camera, and the sweeps of `smoke_terrain_lod.mjs`
 * [13] reported a few hundred pieces — but both were measured on SMALL worlds
 * with a gentle error list. Measured on the live 16.6 × 14.4 km world, whose
 * per-tile error bound is 2…4.4 m at every mip level (the painted micro-relief
 * is structure AT the 2 m lattice, so decimating it once already costs its full
 * amplitude), the UNCAPPED screen-space rule widened `lodRange[0]` from 128 m to
 * `1.9913 · pixelScale / 2` — 1 538 m at a 1 280 px viewport, 2 596 m at
 * 2 160 px — and the FINEST level was drawn over a disk of that radius: 2 952
 * pieces at 1 280 px, and 4 096 — the ceiling — from 1 530 px up. Past it the
 * depth-first walk simply stopped, and what it had not reached yet was ground
 * that was never emitted: at a 2 160 px viewport 1 083 of 3 640 frame samples,
 * with the nearest missing square 240 m from the camera and well inside the
 * haze. That is the hole-in-the-sky class the frustum cull was deleted for.
 *
 * `MAX_RANGE_WIDENING` has since taken THAT world's ladder back to a clean
 * doubling (256/512/1024/2048/3379/4096 at 1 280 px, 372 pieces), so the live
 * world no longer comes near the ceiling. The guard stays and is still proven:
 * the cap bounds how far a level may be pushed, not how much ground a frame
 * holds, and a world with more levels of relief than this one would reach the
 * buffer's end the same way. [14] drives it with the uncapped ladder handed in
 * as `ranges`.
 *
 * WHAT IT DOES INSTEAD. The rings are HALVED, all of them at once, until the
 * selection fits — the same ring structure, moved in. Uniformly and not level
 * by level, because a selection is only crack-free while every node measures
 * against the same monotone ranges (`MAX_PIXEL_ERROR`): halving keeps the
 * ladder monotone and keeps `λ(range[i]) = i + 1` exact, so the morph argument
 * survives it untouched. Each step quarters the area of the finest ring, so the
 * dominant term falls by 4 per step and one or two steps are the whole story.
 *
 * IT COARSENS, IT NEVER DROPS. Every root is still visited and every quadrant
 * still emitted, so the frame stays covered whatever the rings do — the picture
 * gets blockier, not holed. That is the trade: the cap is a memory limit of the
 * instance buffer and the ONE thing it must not cost is ground.
 */
export function selectLodFitted(o: LodSelectOpts): LodSelection {
  const levels = Math.max(1, Math.min(Math.floor(o.levels), MAX_LOD_LEVELS));
  let ranges = o.ranges
    ? [...o.ranges]
    : lodRanges(o.minLodDistance, levels, o.levelErrorM, o.pixelScale);
  let nodes = selectLodNodes({ ...o, ranges });
  let step = 0;
  while (nodes.length >= MAX_NODES && step < MAX_FIT_STEPS) {
    step += 1;
    ranges = ranges.map((r) => r / 2);
    nodes = selectLodNodes({ ...o, ranges });
  }
  if (step > 0 && !fitWarned) {
    fitWarned = true;
    // Not a debug line: it names a world whose ground is being drawn coarser
    // than its own data, which is worth knowing when a picture looks blocky.
    console.warn(`[terrain] the LOD rings were halved ${step}x to stay under `
      + `${MAX_NODES} pieces — ${nodes.length} selected, rings now `
      + `${ranges.map((r) => Math.round(r)).join('/')} m`);
  }
  return { nodes, ranges, coarsenings: step };
}

// ── The GLSL twin ──────────────────────────────────────────────────────────

/**
 * The height fetch itself, as GLSL — uniforms and lookup, NOTHING that only a
 * vertex shader may say.
 *
 * WHAT MAKES IT THE SAME NUMBER AS `heightAt`: `tlodGrid` is `latticeSample`
 * written out — the same clamp, the same `min(floor(f), n−2)`, the same
 * `bilinear` — with `texelFetch` for the array read. `texelFetch` and not
 * `texture()`: R32F is not filterable in core WebGL2 (that needs
 * `OES_texture_float_linear`), and a driver that DID filter it would round the
 * weights in its own way, which is exactly the "nearly the same" this whole
 * stage exists to end.
 *
 * IT IS SPLIT OFF FROM `terrainLodGlsl` FOR THE WATER (E4). The mirror plane
 * of `scene/waterPlane.ts` needs the very same height, but in its FRAGMENT
 * shader — the depth of the lake under a pixel is `plane y − h(x, z)` — and a
 * fragment shader may not declare `attribute vec4 iNode`. So the sampler is
 * one chunk that both stages include and the vertex-only half (`iNode`,
 * `tlodCompute`) hangs off it. Copying the four `texelFetch` into the water
 * shader would have been the second implementation of the one height, which is
 * the thing this whole stage exists to prevent.
 *
 * The smoke does not read this string. It reimplements the arithmetic
 * independently and checks it against `heightAt` on hand-derived fixtures — a
 * check that read the string could only prove the string equals itself.
 */
export function terrainLodSampleGlsl(): string {
  return `
uniform sampler2D uTlodNear;
uniform sampler2D uTlodFar;
uniform vec4 uTlodNearGeom;
uniform vec4 uTlodFarGeom;
uniform vec4 uTlodNearLevel[ ${MAX_LOD_LEVELS} ];
uniform vec4 uTlodFarLevel[ ${MAX_LOD_LEVELS} ];
uniform vec4 uTlodNearRect;
uniform vec4 uTlodExtent;

float tlodGrid( sampler2D tex, vec2 origin, vec4 lv, vec2 p ) {
  float cols = lv.x;
  float rows = lv.y;
  float step = lv.z;
  if ( cols < 2.0 || rows < 2.0 || step <= 0.0 ) return 0.0;
  float fx = clamp( ( p.x - origin.x ) / step, 0.0, cols - 1.0 );
  float fz = clamp( ( p.y - origin.y ) / step, 0.0, rows - 1.0 );
  float fi = min( floor( fx ), cols - 2.0 );
  float fj = min( floor( fz ), rows - 2.0 );
  float tx = fx - fi;
  float tz = fz - fj;
  int i = int( fi );
  int j = int( fj + lv.w );
  float h00 = texelFetch( tex, ivec2( i, j ), 0 ).r;
  float h10 = texelFetch( tex, ivec2( i + 1, j ), 0 ).r;
  float h01 = texelFetch( tex, ivec2( i, j + 1 ), 0 ).r;
  float h11 = texelFetch( tex, ivec2( i + 1, j + 1 ), 0 ).r;
  float north = h00 * ( 1.0 - tx ) + h10 * tx;
  float south = h01 * ( 1.0 - tx ) + h11 * tx;
  return north * ( 1.0 - tz ) + south * tz;
}

int tlodLevel( float baseStep, float count, float nodeStep ) {
  if ( baseStep <= 0.0 ) return 0;
  float k = floor( log2( max( nodeStep / baseStep, 1.0 ) ) + 0.5 );
  return int( clamp( k, 0.0, count - 1.0 ) );
}

float tlodHeight( vec2 p, float nodeStep ) {
  if ( uTlodNearGeom.w > 0.0
       && p.x >= uTlodNearRect.x && p.x <= uTlodNearRect.z
       && p.y >= uTlodNearRect.y && p.y <= uTlodNearRect.w ) {
    int k = tlodLevel( uTlodNearGeom.z, uTlodNearGeom.w, nodeStep );
    return tlodGrid( uTlodNear, uTlodNearGeom.xy, uTlodNearLevel[ k ], p );
  }
  int k = tlodLevel( uTlodFarGeom.z, uTlodFarGeom.w, nodeStep );
  return tlodGrid( uTlodFar, uTlodFarGeom.xy, uTlodFarLevel[ k ], p );
}
`;
}

/**
 * THE WATER SAMPLER AND THE LIFT, as GLSL — the second material variant's
 * whole cost, and it exists in no other program (Wasser v2, K-A E3).
 *
 * It rides on `terrainLodSampleGlsl()` and borrows two things from it:
 * `tlodLevel`, so the mirror is read at exactly the mip the height is read at,
 * and `uTlodNearRect`, so it is read in exactly the window the height comes
 * out of the NEAR pyramid in.
 *
 * ── THE MIP IS THE HEIGHT'S MIP, AND THAT IS THE WHOLE MORPH ARGUMENT ───────
 * The water pyramid is built over the NEAR pyramid's own geometry — same
 * origin, same base step, same base extent (`createTerrainLod.buildWater`) —
 * so `tlodLevel(uTlodWaterGeom.z, …, nodeStep)` and
 * `tlodLevel(uTlodNearGeom.z, …, nodeStep)` are the same integer for the same
 * `nodeStep`. `tlodCompute` then calls the lift ONCE PER TAP of the height's
 * morph pair, with that tap's own footprint:
 *
 *     y = mix( max( h(p, s·2^k),   w(p, s·2^k)   ),
 *              max( h(p, s·2^(k+1)), w(p, s·2^(k+1)) ),  f )
 *
 * Read what that is NOT: it is not `max(mix(h₁,h₂,f), mix(w₁,w₂,f))`. The
 * difference shows at a shore where the coarse level has already lost the
 * mirror (the dilation ring halves per level, `buildWaterPyramid`): mixing the
 * two mirrors first would answer "dry" for the whole pair the moment the
 * coarse one is dry, so the shoreline would JUMP as f crosses 0 — the mirror
 * swimming against the ground between LOD levels, which is the one thing this
 * shape has to rule out. Taking the max per LEVEL and morphing the two lifted
 * surfaces is continuous in f by construction, and it also gives
 * `y ≥ mix(h₁, h₂, f)` for free: each term dominates its own height, so the
 * lifted ground can never sink below the bed it was drawn from.
 *
 * λ IS NEVER LIFTED, deliberately. `tlodMorphAt` keeps measuring its distance
 * against the unlifted `tlodHeight(p, 0.0)`, so the morph coordinate is the
 * same number in BOTH variants — a dry piece and a wet piece beside it read
 * the same λ at the vertex they share, snap to the same point and pick the
 * same mip pair. A lifted λ would have made the two programs disagree about
 * WHERE the shared vertex is, which is a crack that no gate could close.
 *
 * ── THE DRY TEST IS `>` AND NEVER `max()` ───────────────────────────────────
 * The dry sentinel is the wire's `null`, carried as NaN through
 * `waterRaster.ts` into the Float32Array the texture is made of. IEEE says
 * every comparison against a NaN is false, so `( w > h ) ? w : h` falls
 * through to the ground for a dry texel — while `max(h, w)` is free to return
 * either operand for a NaN and GLSL does not say which. Where this chunk has
 * to PRODUCE a dry answer itself (no pyramid, outside the near window) it
 * returns `TLOD_DRY`, a number every compiler agrees about that fails the same
 * comparison for every world height there is.
 *
 * The masked mix is `waterRaster.waterBilinear`, line for line: a corner with
 * weight 0 is NOT READ. Plain floating point would carry its NaN through
 * `NaN · 0 = NaN`, and since the pyramid is filled AT the lattice points that
 * would erode the dilation ring by a full texel along a grid of lines through
 * every water — the finding is spelled out in `waterRaster.ts`.
 *
 * NO FAR TWIN. Outside `uTlodNearRect` the HEIGHT comes from the overview
 * pyramid, and the overview carries no water at all (§ A16.5). Reading a level
 * there would put the two halves of the max on two different lattices, so the
 * answer out there is dry — which is also what "no water known here" has to
 * draw.
 */
export function terrainLodWaterGlsl(): string {
  return `
uniform sampler2D uTlodWater;
uniform vec4 uTlodWaterGeom;
uniform vec4 uTlodWaterLevel[ ${MAX_LOD_LEVELS} ];
uniform float uTlodNoWater;

const float TLOD_DRY = -1e30;

float tlodWaterGrid( vec4 lv, vec2 p ) {
  float cols = lv.x;
  float rows = lv.y;
  float step = lv.z;
  if ( cols < 2.0 || rows < 2.0 || step <= 0.0 ) return TLOD_DRY;
  float fx = clamp( ( p.x - uTlodWaterGeom.x ) / step, 0.0, cols - 1.0 );
  float fz = clamp( ( p.y - uTlodWaterGeom.y ) / step, 0.0, rows - 1.0 );
  float fi = min( floor( fx ), cols - 2.0 );
  float fj = min( floor( fz ), rows - 2.0 );
  float tx = fx - fi;
  float tz = fz - fj;
  int i = int( fi );
  int j = int( fj + lv.w );
  float w00 = ( 1.0 - tx ) * ( 1.0 - tz );
  float w10 = tx * ( 1.0 - tz );
  float w01 = ( 1.0 - tx ) * tz;
  float w11 = tx * tz;
  float sum = 0.0;
  if ( w00 != 0.0 ) sum += texelFetch( uTlodWater, ivec2( i, j ), 0 ).r * w00;
  if ( w10 != 0.0 ) sum += texelFetch( uTlodWater, ivec2( i + 1, j ), 0 ).r * w10;
  if ( w01 != 0.0 ) sum += texelFetch( uTlodWater, ivec2( i, j + 1 ), 0 ).r * w01;
  if ( w11 != 0.0 ) sum += texelFetch( uTlodWater, ivec2( i + 1, j + 1 ), 0 ).r * w11;
  return sum;
}

float tlodWaterAt( vec2 p, float nodeStep ) {
  if ( uTlodWaterGeom.w <= 0.0
       || p.x < uTlodNearRect.x || p.x > uTlodNearRect.z
       || p.y < uTlodNearRect.y || p.y > uTlodNearRect.w ) return TLOD_DRY;
  int k = tlodLevel( uTlodWaterGeom.z, uTlodWaterGeom.w, nodeStep );
  return tlodWaterGrid( uTlodWaterLevel[ k ], p );
}

// THE LIFT of ONE tap of the morph pair. The isolation panel's toggle 21 takes
// it out as a UNIFORM and not as a define, so the frame after the click is
// drawn by the very same program and what is left is exactly the dry variant's
// answer — the pattern of toggles 6 and 9.
float tlodLift( float h, vec2 p, float nodeStep ) {
  if ( uTlodNoWater > 0.5 ) return h;
  float w = tlodWaterAt( p, nodeStep );
  return ( w > h ) ? w : h;
}
`;
}

/**
 * The VERTEX side: the patch attribute and the whole of `tlodCompute`, on top
 * of the sampler chunk above.
 *
 * `iNode` is (south-west x, south-west z, edge length, LEVEL) — the level and
 * NOT a morph, since 2026-08-21. Every vertex reads its own λ out of
 * `uTlodRange` (`lodLambda`), so the drawn surface is a function of the world
 * position alone and two patches cannot disagree about a vertex they share. The
 * old per-node morph is what opened 6-pixel hairlines of sky between
 * neighbouring leaf patches; the derivation is in `lodLambda`.
 *
 * THE LEVEL SAYS HOW DENSE, THE SIZE SAYS HOW BIG (§ A16.6, 2026-08-22). The
 * vertex spacing is `uTlodBaseStep · 2^level` and NOT `size / PATCH_N`, because
 * a selected piece is no longer always a whole node: the out-of-range rule of
 * `selectLodNodes` also emits parent QUADRANTS — a child-sized square carrying
 * the parent's spacing, i.e. `PATCH_N / 2` cells per axis. `cells` falls out of
 * the two numbers, and the patch indices past it are clamped onto the last row
 * and column, which is the same collapse-to-degenerate the world frame uses
 * below: a vertex each, no fragments, no seam. There is nothing to justify
 * beyond that — the alternative, four sub-draws with a quadrant bitmask, needs
 * one draw call per quadrant (this renderer has exactly ONE) or a per-vertex
 * mask test that cannot be made degenerate for a DIAGONAL mask, where a cell at
 * the patch centre survives as a stray sliver.
 *
 * WHY IT IS EXACT. Let a vertex of a piece at level L sit at the world point p,
 * with spacing e = baseStep·2^L, and let t = λ(p) − L, k = ⌊t⌋, f = t − k. It
 * snaps to grid multiples of 2^k blended towards 2^(k+1), i.e. onto the WORLD
 * lattice of step e·2^k = baseStep·2^(L+k) = baseStep·2^⌊λ⌋ — a number that no
 * longer mentions L. Its two height taps are `e·2^k` and `·2^(k+1)`, the mip
 * pair (⌊λ⌋, ⌊λ⌋+1), blended by f = λ − ⌊λ⌋. Every one of those depends on λ
 * and p alone, so a neighbour at ANY level answers the same number at the same
 * point. The piece's origin is a multiple of 16·baseStep·2^L, hence of
 * baseStep·2^⌊λ⌋ for every ⌊λ⌋ this renderer reaches, so the two also snap onto
 * the same ABSOLUTE lattice and not merely onto one of the same pitch.
 *
 * TWICE, AND THE SECOND TIME AT THE OWNER. k ≥ 1 means the piece is drawing on
 * a lattice coarser than its own and several of its vertices snap to one point.
 * Reading λ per VERTEX made those twins miss each other by
 * `(gi mod m2 − gi mod m1)·Δt·nodeStep` — 0.357 m — and one of them then hung
 * beside the coarser neighbour's edge as a T-junction. So the morph is read at
 * the vertex's OWNER, `gi − gi mod 2^k`, which every vertex of the block shares;
 * `tlodMorphAt` is called once to find k and once at that owner. The owner is a
 * point of the same world lattice for the neighbour too, so the exactness above
 * survives it. Derivation and numbers: `lodVertex`.
 *
 * λ is fed the FINEST height (`tlodHeight(p, 0.0)`) rather than the piece's own
 * level, for the last part of the same argument: a level-dependent distance
 * would make λ level-dependent again, and with it the surface.
 *
 * `water` = the SECOND VARIANT (K-A E3): every height tap of the morph pair
 * goes through `tlodLift`, so the vertex lands on `max(h, w_level)` where the
 * water raster has a value. `terrainLodGlsl(false)` declares no water uniform,
 * calls no water function and fetches no water texel — its four `texelFetch`
 * and its `mix` of two `tlodHeight` are the same statements as before the
 * stage, so the dry ground compiles to the program it always did.
 */
export function terrainLodGlsl(water = false): string {
  /** ONE tap of the morph pair, lifted or not. The dry spelling is left
   *  exactly as it was so the dry program is unchanged. */
  const tap = (m: string): string => (water
    ? `tlodLift( tlodHeight( p, nodeStep * ${m} ), p, nodeStep * ${m} )`
    : `tlodHeight( p, nodeStep * ${m} )`);
  return `${terrainLodSampleGlsl()}${water ? terrainLodWaterGlsl() : ''}
uniform float uTlodRange[ ${MAX_LOD_LEVELS} ];
uniform float uTlodNoMorph;
uniform float uTlodBaseStep;
uniform vec4 uTlodFreeze;
attribute vec4 iNode;
varying vec2 vTlodXZ;

vec3 tlodWorld;

float tlodLambda( float d ) {
  float lam = 0.0;
  float prev = 0.0;
  for ( int i = 0; i < ${MAX_LOD_LEVELS}; i ++ ) {
    float r = uTlodRange[ i ];
    if ( r > 0.0 ) {
      float s = prev + ${MORPH_START} * ( r - prev );
      prev = r;
      lam += ( r > s ) ? clamp( ( d - s ) / ( r - s ), 0.0, 1.0 ) : step( r, d );
    }
  }
  return lam;
}

// The morph coordinate at one lattice point of this piece: λ there, minus the
// piece's own level. nodeStep and eye are passed in so the two calls in
// tlodCompute cannot drift apart.
float tlodMorphAt( vec2 gi, float nodeStep, vec3 eye ) {
  // CLAMPED TO THE WORLD FRAME. A quadtree node is a power-of-two square and
  // the frame is not, so the outermost nodes reach past it; without this the
  // ground would run on behind the backdrop ring that is supposed to close the
  // view (ground.BASE_MARGIN_M). Clamping collapses the vertices outside onto
  // the border instead of clipping triangles, and because every node clamps
  // against the SAME rectangle the ground stays whole along it.
  vec2 p = clamp( iNode.xy + gi * nodeStep, uTlodExtent.xy, uTlodExtent.zw );
  // The distance is taken to the FINEST ground under the point — one number per
  // world point, so every piece that owns this point reads the same λ.
  float d = distance( vec3( p.x, tlodHeight( p, 0.0 ), p.y ), eye );
  return max( tlodLambda( d ) - iNode.w, 0.0 );
}

void tlodCompute() {
  float nodeStep = uTlodBaseStep * exp2( iNode.w );
  // How many of the patch's cells this piece uses: PATCH_N for a whole node,
  // PATCH_N / 2 for a parent quadrant. The rest collapse onto the last row and
  // column and cost a vertex each and no fragments.
  float cells = floor( iNode.z / nodeStep + 0.5 );
  vec2 gi = min( position.xz * ${PATCH_N}.0, vec2( cells ) );
  // The isolation panel's toggle 10 freezes the camera the MORPH is measured
  // from, so the frozen node set is drawn by the very rule that selected it —
  // see TerrainLod.setFrozen.
  vec3 eye = mix( cameraPosition, uTlodFreeze.xyz, uTlodFreeze.w );
  // WHERE THE MORPH IS READ. Where λ has climbed past this piece's level the
  // piece draws on a coarser lattice and several of its vertices snap to the
  // same point. They are only truly redundant if they carry the SAME k and f,
  // so both are read at the block they belong to and never at the vertex: the
  // coarsest block level j whose own anchor still reports λ >= level + j wins.
  // Every vertex of that block shares every anchor from the top down to it, so
  // every vertex of it reaches the same answer — and the neighbour one level up
  // reaches it too, one step later in the same descent. See lodVertex.
  float k = 0.0;
  float t = tlodMorphAt( gi, nodeStep, eye );
  for ( int j = ${MAX_LOD_LEVELS - 1}; j >= 1; j -- ) {
    float m = exp2( float( j ) );
    float tj = tlodMorphAt( gi - mod( gi, m ), nodeStep, eye );
    if ( floor( tj ) >= float( j ) ) { k = float( j ); t = tj; break; }
  }
  // The isolation panel's toggle 9 multiplies the morph out entirely: k = f = 0
  // puts every vertex on its own lattice (gm = gi).
  float nm = 1.0 - uTlodNoMorph;
  k *= nm;
  float f = clamp( t - k, 0.0, 1.0 ) * nm;
  float m1 = exp2( k );
  float m2 = m1 * 2.0;
  // The morph snaps every vertex onto the coarser of the two lattices λ names
  // (every 2^(k+1)-th index) and blends there from the finer one.
  vec2 gm = mix( gi - mod( gi, m1 ), gi - mod( gi, m2 ), f );
  vec2 p = clamp( iNode.xy + gm * nodeStep, uTlodExtent.xy, uTlodExtent.zw );
  // THE MAX PER LEVEL, THE MORPH OVER THE PAIR (K-A E3, water variant only):
  // each tap is lifted at its OWN footprint before the two are blended, so the
  // mirror morphs in step with the ground it sits in. See terrainLodWaterGlsl.
  float h = mix( ${tap('m1')}, ${tap('m2')}, f );
  tlodWorld = vec3( p.x, h, p.y );
  // The one thing the fragment stage needs of this: WHERE the point is. The
  // shading normal is taken there, from this position alone (tlodNormalAt) —
  // the vertex used to blend the normal out of its own morph pair, and every
  // number in that pair is a function of the camera distance.
  vTlodXZ = p;
}
`;
}

/**
 * THE SHADING NORMAL, as the GLSL that rides on `terrainLodSampleGlsl()` — the
 * FRAGMENT half, and the whole of the fix of 2026-08-21.
 *
 * n(x, z) = normalize( −(h(x+s, z) − h(x−s, z)), 2s, −(h(x, z+s) − h(x, z−s)) )
 *
 * with s = `uTlodNormalSpan` metres and h the FINEST level of the pyramids
 * (`tlodHeight(q, 0.0)`, the very surface `heightAt` answers and the server
 * judges walks by). Read what it does NOT contain: no node step, no LOD level,
 * no morph fraction, no camera. The normal of a piece of ground is a pure
 * function of that ground, so the camera cannot change it — which is the
 * property, not a side effect. The vertex-side predecessor differenced the
 * vertex's morph pair (`nodeStep·2^k` and twice it, blended by `f = frac(λ)`,
 * λ the vertex's distance to the CAMERA) and swung by 16–17° on levels 0/1 from
 * camera motion alone.
 *
 * WHY s IS THE BASE LATTICE STEP (2 m in the live world, `setField`). The height
 * field IS bilinear over that lattice, so it carries no detail below it:
 *  - a SHORTER span reads the bilinear derivative inside one cell — constant
 *    across the cell and discontinuous at every cell edge, i.e. a 2 m facet
 *    grid drawn over the whole world;
 *  - the span s = one lattice step is the central difference AT a lattice
 *    point, the mean of the two adjacent cell slopes, and is continuous in
 *    (x, z) everywhere;
 *  - a LONGER span (4 m, 8 m) smooths away relief the geometry still draws at
 *    2 m, so a hill would be shaded flatter than its own silhouette.
 *
 * NO FOOTPRINT BLEND, deliberately, and the arithmetic says why. One pixel of
 * the 45° / 1 080 px view spans 2·tan(22.5°)/1080 = 7.667e-4 rad; at distance d
 * that is d·7.667e-4 m across the view and, at the flattest camera pitch this
 * client uses (18°), d·7.667e-4/sin 18° = d·2.481e-3 m along it. Nyquist for a
 * field whose finest structure is 2 m wants a footprint ≤ 1 m, i.e. d ≤ 403 m —
 * and the scene fog (220…520 m, `engine.ts`) has already replaced
 * (403−220)/300 = 61 % of the ground colour with sky there, 100 % at 520 m. So
 * the ground can only alias where it is at most 39 % visible and fading. A
 * footprint-driven span would buy that back at the price of a normal that
 * changes with the camera again — the exact class of defect this replaces — and
 * would have to be a function of `fwidth` alone to be admissible at all.
 */
export function terrainLodNormalGlsl(): string {
  return `
uniform float uTlodNormalSpan;
uniform float uTlodFlatNormal;
varying vec2 vTlodXZ;

vec3 tlodNormalAt( vec2 p ) {
  // The isolation panel's toggle 6: the ground is shaded as if it were level,
  // which tells a SHADING shimmer from a geometric one.
  if ( uTlodFlatNormal > 0.5 ) return vec3( 0.0, 1.0, 0.0 );
  float s = max( uTlodNormalSpan, 1e-3 );
  float hx = tlodHeight( vec2( p.x + s, p.y ), 0.0 ) - tlodHeight( vec2( p.x - s, p.y ), 0.0 );
  float hz = tlodHeight( vec2( p.x, p.y + s ), 0.0 ) - tlodHeight( vec2( p.x, p.y - s ), 0.0 );
  return normalize( vec3( -hx, 2.0 * s, -hz ) );
}
`;
}

/**
 * The TypeScript twin of `tlodCompute`'s height — what the GPU really answers
 * for a point on a node.
 *
 * Used by the smoke to assert `|h_gpu − h_cpu| < 1e-4` on the morph-0 path,
 * and by nothing at runtime: the runtime asks `heightAt`, which is the point
 * of the whole exercise.
 */
export function gpuHeightAt(near: HeightPyramid | null, nearRect: readonly number[] | null,
                            far: HeightPyramid | null,
                            x: number, z: number, nodeStep: number): number {
  if (near && nearRect && x >= nearRect[0] && x <= nearRect[2]
      && z >= nearRect[1] && z <= nearRect[3]) {
    return pyramidHeight(near, x, z, pyramidLevelFor(near, nodeStep));
  }
  return pyramidHeight(far, x, z, pyramidLevelFor(far, nodeStep));
}

/**
 * The TypeScript twin of `tlodWaterAt` — the water level the GPU really reads
 * at a point, NaN where there is none (Wasser v2, K-A E3).
 *
 * `nearRect` is the HEIGHT window and that is not an oversight: the water
 * pyramid is built over the near pyramid's own geometry, so the rectangle is
 * the same one, and gating on it is what makes "the height came from the near
 * pyramid" and "the mirror is known here" the same statement. Outside it the
 * height is the overview's and the overview carries no water.
 */
export function gpuWaterAt(water: HeightPyramid | null,
                           nearRect: readonly number[] | null,
                           x: number, z: number, nodeStep: number): number {
  if (!water || !nearRect) return NaN;
  if (x < nearRect[0] || x > nearRect[2] || z < nearRect[1] || z > nearRect[3]) return NaN;
  return wlevelAt(water, x, z, pyramidLevelFor(water, nodeStep));
}

/**
 * ONE TAP LIFTED — the arithmetic of the shader's `tlodLift`, and the reason
 * it is a function rather than a call to `Math.max`.
 *
 * `Math.max(h, NaN)` is NaN; the whole dry half of the world would come back
 * as a hole. `w > h ? w : h` answers `h` for every dry sentinel, which is what
 * the GLSL `( w > h ) ? w : h` does for the same reason — see
 * `terrainLodWaterGlsl`.
 */
export function liftedHeight(h: number, w: number): number {
  return w > h ? w : h;
}

/**
 * The TypeScript twin of `tlodNormalAt` — the SHADING normal the fragment
 * shader really computes at a world point, as a unit vector.
 *
 * Note what the signature cannot express: there is no camera, no node, no
 * level and no morph in it. That is the property the whole change exists for,
 * and the smoke asserts it by handing this function the same (x, z) from every
 * camera it can think of ([10]).
 */
export function fragmentNormal(near: HeightPyramid | null,
                               nearRect: readonly number[] | null,
                               far: HeightPyramid | null,
                               x: number, z: number, spanM: number
): { x: number; y: number; z: number } {
  const s = Math.max(spanM, 1e-3);
  // The FINEST level of the pyramids, `tlodHeight(q, 0.0)` — the surface
  // `heightAt` answers, whatever the ground under this pixel is drawn at.
  const h = (px: number, pz: number): number =>
    gpuHeightAt(near, nearRect, far, px, pz, 0);
  const hx = h(x + s, z) - h(x - s, z);
  const hz = h(x, z + s) - h(x, z - s);
  const len = Math.hypot(hx, 2 * s, hz);
  return { x: -hx / len, y: (2 * s) / len, z: -hz / len };
}

/**
 * What a vertex of a piece really lands on AT A GIVEN morph coordinate —
 * position and height, the second half of `tlodCompute` as arithmetic.
 *
 * `gx`/`gz` are the vertex's integer indices inside the patch (0 … `PATCH_N`);
 * indices past the piece's own `cells` collapse onto its last row and column,
 * exactly as the shader's `min(gi, cells)` does. `extent` is the world frame the
 * shader clamps against, `null` for "no frame"; `t` is the morph coordinate
 * λ − level (`node.morph` by default, the value at the piece's nearest point).
 *
 * `water` is the water pyramid of the SECOND material variant (K-A E3), `null`
 * for the dry one — and `null` is what every caller before that stage passes,
 * so the answer is unchanged for them: `gpuWaterAt` returns NaN and
 * `liftedHeight` falls through to the height. With a pyramid the two taps of
 * the morph pair are lifted SEPARATELY, each at its own footprint, and blended
 * afterwards; the argument for that order is in `terrainLodWaterGlsl`.
 *
 * `t` MAY RUN PAST 1, and that is the property the whole seam argument rests
 * on. With k = ⌊t⌋ and f = t − k the vertex snaps to every 2^k-th index and
 * blends to every 2^(k+1)-th, i.e. onto the WORLD lattice of step
 * `baseStep · 2^(level + k)` = `baseStep · 2^⌊λ⌋` — a number that no longer
 * mentions the piece's own level. So a piece at level L and its coarser
 * neighbour at L+1 place a shared vertex at the same point, at the same height,
 * from the same two mip levels: the level CANCELS. Clamping t to [0, 1] would
 * break exactly that (measured: 3.9 m of step along a shared edge) — see
 * `lodVertex` for the second half, which is what makes the vertices the finer
 * piece ADDS collapse exactly.
 */
export function morphedVertex(node: LodNode, gx: number, gz: number,
                              near: HeightPyramid | null,
                              nearRect: readonly number[] | null,
                              far: HeightPyramid | null,
                              extent: readonly number[] | null = null,
                              t: number = node.morph,
                              water: HeightPyramid | null = null
): { x: number; z: number; y: number } {
  const nodeStep = node.size / node.cells;
  const k = Math.min(Math.floor(Math.max(t, 0)), MAX_LOD_LEVELS - 1);
  const f = Math.max(t, 0) - k;
  const m1 = 2 ** k;
  const m2 = m1 * 2;
  const snap = (g: number): number => {
    const gc = Math.min(g, node.cells);
    return (gc - (gc % m1)) * (1 - f) + (gc - (gc % m2)) * f;
  };
  let x = node.x + snap(gx) * nodeStep;
  let z = node.z + snap(gz) * nodeStep;
  if (extent) {
    x = Math.min(Math.max(x, extent[0]), extent[2]);
    z = Math.min(Math.max(z, extent[1]), extent[3]);
  }
  const own = liftedHeight(gpuHeightAt(near, nearRect, far, x, z, nodeStep * m1),
                           gpuWaterAt(water, nearRect, x, z, nodeStep * m1));
  const parent = liftedHeight(gpuHeightAt(near, nearRect, far, x, z, nodeStep * m2),
                              gpuWaterAt(water, nearRect, x, z, nodeStep * m2));
  return { x, z, y: own * (1 - f) + parent * f };
}

/** Where the camera stands, for the per-vertex λ — the three numbers
 *  `tlodCompute` reads out of `cameraPosition`. */
export interface LodCamera {
  x: number;
  y: number;
  z: number;
}

/**
 * The WHOLE of `tlodCompute` as arithmetic: the morph coordinate a vertex reads
 * and the point it lands on. This is what the smoke asserts two neighbouring
 * pieces agree on — `morphedVertex` alone cannot say it, because the agreement
 * lives in the λ that both of them compute for the same world point.
 *
 * THE MORPH IS READ AT THE VERTEX'S OWNER, NOT AT THE VERTEX (the T-junction fix
 * of 2026-08-22). Where λ has climbed past the piece's own level — the outer
 * strip of a piece, the part that borders the coarser ring — k = ⌊t⌋ is ≥ 1 and
 * the piece is drawing at a lattice coarser than its own: several of its
 * vertices then snap to the SAME point and are meant to be redundant. They are
 * redundant only if they blend with the same f, and f used to be each vertex's
 * own. Two such twins therefore separated by
 * `(gi mod m2 − gi mod m1) · Δt · nodeStep` — 0.357 m sideways and 0.086 m in
 * height on the live world — which leaves one of them hanging beside the
 * neighbour's edge: a T-junction, and a sliver of sky at every camera step.
 *
 * So the vertex first asks λ where it is (`t0`), takes k from that, and then
 * asks λ again at its OWNER — the vertex it snaps onto, index
 * `gi − gi mod 2^k`. Every vertex of one owner-block reads the owner's λ, so
 * they carry the same k and f and land on exactly the same point: the extra
 * vertices become degenerate rather than nearly-degenerate. The owner is a
 * lattice point of the same world lattice for the coarser neighbour too
 * (`morphedVertex`: the level cancels), so the two pieces still agree exactly.
 * One more `heightAt` tap per vertex is the whole price.
 */
export function lodVertex(node: LodNode, gx: number, gz: number,
                          near: HeightPyramid | null,
                          nearRect: readonly number[] | null,
                          far: HeightPyramid | null,
                          extent: readonly number[] | null,
                          cam: LodCamera, ranges: readonly number[],
                          water: HeightPyramid | null = null
): { x: number; z: number; y: number; t: number } {
  const nodeStep = node.size / node.cells;
  /** The morph coordinate at the lattice point (ix, iz) of this piece. */
  const tAt = (ix: number, iz: number): number => {
    let x = node.x + ix * nodeStep;
    let z = node.z + iz * nodeStep;
    if (extent) {
      x = Math.min(Math.max(x, extent[0]), extent[2]);
      z = Math.min(Math.max(z, extent[1]), extent[3]);
    }
    // THE UNLIFTED GROUND, even in the water variant (K-A E3): λ has to be the
    // same number in both programs or a dry piece and the wet piece beside it
    // would place the vertex they share at two different points — a crack no
    // gate can close. See `terrainLodWaterGlsl`.
    const y = gpuHeightAt(near, nearRect, far, x, z, 0);
    const d = Math.hypot(x - cam.x, y - cam.y, z - cam.z);
    return Math.max(lodLambda(d, ranges) - node.level, 0);
  };
  const gi = Math.min(gx, node.cells);
  const gj = Math.min(gz, node.cells);
  let k = 0;
  let t = tAt(gi, gj);
  for (let j = MAX_LOD_LEVELS - 1; j >= 1; j -= 1) {
    const m = 2 ** j;
    const tj = tAt(gi - (gi % m), gj - (gj % m));
    if (Math.floor(tj) >= j) { k = j; t = tj; break; }
  }
  return { ...morphedVertex(node, gx, gz, near, nearRect, far, extent,
                            k + Math.min(Math.max(t - k, 0), 1), water), t };
}

// ── The renderer ───────────────────────────────────────────────────────────

/** Materials that already carry the CDLOD displacement. Same guard as
 *  `patchHole` and `applyNaturalGround`: the patch CHAINS, so applying it
 *  twice would declare `tlodWorld` a second time and the shader would not
 *  compile. */
const lodPatched = new WeakSet<THREE.Material>();

/** The cache key this patch contributes, exported so the smoke can pin the
 *  combined key without carrying a copy of the string. */
export const TERRAIN_LOD_CACHE_KEY = 'terrain-lod';

/** What the WATER VARIANT appends to it (K-A E3). It is an ADDITION and the
 *  dry key is left untouched, so the dry ground's combined key — and with it
 *  three's program cache entry — is the same string it was before the stage. */
export const TERRAIN_LOD_WATER_CACHE_KEY = 'water';

/** The one texel of nothing every empty state falls back to — a driver handed
 *  an unbound sampler is a warning at best and a black ground at worst. Built
 *  once and never freed, the `neutralFallback` pattern of `naturalGround.ts`. */
function makeNeutral(): THREE.DataTexture {
  const tex = new THREE.DataTexture(new Float32Array(1), 1, 1,
                                    THREE.RedFormat, THREE.FloatType);
  tex.minFilter = THREE.NearestFilter;
  tex.magFilter = THREE.NearestFilter;
  tex.unpackAlignment = 1;
  tex.needsUpdate = true;
  return tex;
}
const neutralTex = makeNeutral();

function makeLevelArray(): THREE.Vector4[] {
  const out: THREE.Vector4[] = [];
  for (let i = 0; i < MAX_LOD_LEVELS; i += 1) out.push(new THREE.Vector4(0, 0, 0, 0));
  return out;
}

/** The shared uniform objects — ONE per value for every patched material, the
 *  pattern of `naturalGround.ts`. Swapping a pyramid is therefore one
 *  assignment and nothing recompiles. */
const uNear: { value: THREE.Texture } = { value: neutralTex };
const uFar: { value: THREE.Texture } = { value: neutralTex };
const uNearGeom = { value: new THREE.Vector4(0, 0, 1, 0) };
const uFarGeom = { value: new THREE.Vector4(0, 0, 1, 0) };
const uNearLevel = { value: makeLevelArray() };
const uFarLevel = { value: makeLevelArray() };
const uNearRect = { value: new THREE.Vector4(0, 0, -1, -1) };
const uExtent = { value: new THREE.Vector4(-1e6, -1e6, 1e6, 1e6) };
/**
 * THE WATER PYRAMID, uploaded and bound but NOT YET READ (Wasser v2, K-A E2).
 *
 * Same three objects the height pyramids carry — the packed R32F texture, the
 * `(originX, originZ, step, levelCount)` geometry and the per-level lattice
 * array — so K-A E3 only has to write the GLSL that reads them. There is no
 * FAR twin and there will not be one: the overview grid carries no water at
 * all (§ A16.5), so a point outside the near window is "no water known here",
 * which is what a renderer must draw rather than invent.
 *
 * A shader that does not declare these uniforms simply never looks them up —
 * three.js resolves uniforms by location and skips what the program has none
 * for — so binding them now costs a property assignment and no recompile.
 */
const uWater: { value: THREE.Texture } = { value: neutralTex };
const uWaterGeom = { value: new THREE.Vector4(0, 0, 1, 0) };
const uWaterLevel = { value: makeLevelArray() };
/** The LOD ring boundaries in metres, the input of the per-vertex λ
 *  (`lodLambda`). VERTEX-ONLY: the water mirror reads the height pyramids from
 *  its fragment shader but has no vertices to morph, so this one is bound in
 *  `patchTerrainLod` rather than in `bindTerrainLodUniforms`. */
const uRange = { value: new Array<number>(MAX_LOD_LEVELS).fill(0) };
/** The base lattice step in metres, set in `setField`. VERTEX-ONLY: it is what
 *  turns a piece's LEVEL into its vertex spacing (`terrainLodGlsl`), which is
 *  what lets a parent quadrant carry the parent's spacing over a child-sized
 *  square. */
const uBaseStep = { value: FALLBACK_BASE_STEP_M };
/** The frozen camera for the morph — xyz the eye, w = 1 while the isolation
 *  panel's toggle 10 holds the selection still. See `TerrainLod.setFrozen`. */
const uFreeze = { value: new THREE.Vector4(0, 0, 0, 0) };
/** The metre span of the shading normal's central difference — the base
 *  lattice step, set in `setField`. FRAGMENT-ONLY and therefore bound in
 *  `patchTerrainLod` beside `uTlodRange`; see `terrainLodNormalGlsl` for why it
 *  is one fixed number and not a function of the LOD. */
const uNormalSpan = { value: FALLBACK_BASE_STEP_M };
/**
 * THE TWO ISOLATION SWITCHES (`debug3d.ts`, toggles 6 and 9) — uniforms and
 * never defines, so flipping one costs no recompile and the very next frame is
 * drawn by the same program. Both are 0 in every normal run and the shader
 * spends one comparison each on them.
 *
 * `uFlatNormal` = 1 makes `tlodNormalAt` answer straight up, which separates a
 * shading defect from a geometry one; `uNoMorph` = 1 forces the per-vertex
 * morph factor to 0, which separates the geomorph from everything else (and
 * opens the LOD cracks the morph exists to close — that is the reading, not a
 * side effect).
 */
const uFlatNormal = { value: 0 };
const uNoMorph = { value: 0 };
/**
 * …AND THE THIRD (toggle 21, K-A E3). `uNoWater` = 1 makes `tlodLift` hand its
 * height straight back, so the water variant draws exactly what the dry one
 * would — the lift can be bisected against everything else in the frame
 * without a recompile and without changing which pieces are drawn by which
 * program. Only the water variant's program declares it.
 */
const uNoWater = { value: 0 };

/** Flip the three switches above. Only the ISOLATION panel calls this. */
export function setTerrainLodDebug(o: { flatNormal?: boolean; noMorph?: boolean;
                                        noWater?: boolean }): void {
  if (o.flatNormal !== undefined) uFlatNormal.value = o.flatNormal ? 1 : 0;
  if (o.noMorph !== undefined) uNoMorph.value = o.noMorph ? 1 : 0;
  if (o.noWater !== undefined) uNoWater.value = o.noWater ? 1 : 0;
}

/**
 * Hang the shared height uniforms — and, since K-A E2, the water ones — into a
 * shader that includes `terrainLodSampleGlsl()`.
 *
 * Exported for the water mirror (E4, `scene/waterPlane.ts`): it reads the same
 * pyramids from its FRAGMENT shader and must read them through the same
 * objects, or a pyramid swap would reach the terrain and leave the lake
 * measuring its depth against yesterday's ground.
 *
 * The three `uTlodWater*` entries are bound and kept current but read by NO
 * shader yet — K-A E2 ships the field and the upload, E3 writes the GLSL that
 * lifts a vertex onto it. An unread uniform has no location and is skipped.
 */
export function bindTerrainLodUniforms(uniforms: Record<string, unknown>): void {
  uniforms.uTlodNear = uNear;
  uniforms.uTlodFar = uFar;
  uniforms.uTlodNearGeom = uNearGeom;
  uniforms.uTlodFarGeom = uFarGeom;
  uniforms.uTlodNearLevel = uNearLevel;
  uniforms.uTlodFarLevel = uFarLevel;
  uniforms.uTlodNearRect = uNearRect;
  uniforms.uTlodExtent = uExtent;
  uniforms.uTlodWater = uWater;
  uniforms.uTlodWaterGeom = uWaterGeom;
  uniforms.uTlodWaterLevel = uWaterLevel;
}

/**
 * Give a ground material the CDLOD vertex displacement and its shading normal.
 *
 * FOUR ANCHORS, and each one is deliberate:
 *  - `uv_vertex` computes the world position FIRST (everything below needs it)
 *    and then overwrites `vMapUv` with the world metres, because a patch's UV
 *    is its position in the world and not a fraction of a node — one UV unit
 *    is one metre, exactly as the painted-area drapes have it;
 *  - `beginnormal_vertex` pins the vertex normal to straight up. It is no
 *    longer the shading normal (that is a fragment matter since 2026-08-21,
 *    `terrainLodNormalGlsl`), but `vNormal` must still be a defined vector:
 *    the patch geometry carries no `normal` attribute at all, so without this
 *    three would interpolate whatever constant the driver hands an unbound
 *    attribute and any consumer of it (a shadow normal bias, a tangent frame)
 *    would read a NaN;
 *  - `begin_vertex` puts the world position into `transformed`, which is what
 *    every chunk after it (and the hole and natural-ground patches) reads;
 *  - `normal_fragment_begin`, in the FRAGMENT shader, replaces the interpolated
 *    normal with the one sampled at this pixel's own world position. `normal`
 *    is three's VIEW-space vector there, so the world normal goes through
 *    `viewMatrix` (the mesh sits at the origin with an identity matrix, so
 *    object space is world space and no model matrix is owed).
 *    `nonPerturbedNormal` is set with it — that is the copy the clearcoat and
 *    iridescence paths read, and leaving the two disagreeing would be a bug
 *    waiting for the first ground kind that switches one of them on.
 *
 * The mesh sits at the origin with an identity matrix, so object space IS
 * world space — the same arrangement the old base plate had, and what lets one
 * sampled height serve the ground, the areas and the figures without a
 * transform in between.
 *
 * `water` PICKS THE SECOND VARIANT (K-A E3): the water sampler is declared,
 * every height tap goes through `tlodLift`, `uTlodNoWater` is bound and the
 * cache key gains `+water`. Called with `false` — which is how the dry ground
 * is patched — this function is what it was before the stage, down to the
 * cache key, so three keeps handing the dry material the program it already
 * has.
 */
export function patchTerrainLod(mat: THREE.Material, water = false): void {
  if (lodPatched.has(mat)) return;
  lodPatched.add(mat);
  const prev = mat.onBeforeCompile;
  const prevKey = Object.prototype.hasOwnProperty.call(mat, 'customProgramCacheKey')
    ? String(mat.customProgramCacheKey())
    : '';
  mat.onBeforeCompile = (shader, renderer) => {
    prev.call(mat, shader, renderer);
    bindTerrainLodUniforms(shader.uniforms as unknown as Record<string, unknown>);
    (shader.uniforms as unknown as Record<string, unknown>).uTlodRange = uRange;
    (shader.uniforms as unknown as Record<string, unknown>).uTlodBaseStep = uBaseStep;
    (shader.uniforms as unknown as Record<string, unknown>).uTlodFreeze = uFreeze;
    (shader.uniforms as unknown as Record<string, unknown>).uTlodNormalSpan = uNormalSpan;
    (shader.uniforms as unknown as Record<string, unknown>).uTlodNoMorph = uNoMorph;
    (shader.uniforms as unknown as Record<string, unknown>).uTlodFlatNormal = uFlatNormal;
    if (water) {
      (shader.uniforms as unknown as Record<string, unknown>).uTlodNoWater = uNoWater;
    }
    if (!shader.vertexShader.includes('#include <begin_vertex>')) return;
    shader.vertexShader = terrainLodGlsl(water) + shader.vertexShader
      .replace('#include <uv_vertex>', `\ttlodCompute();
#include <uv_vertex>
\t#ifdef USE_MAP
\t\tvMapUv = ( mapTransform * vec3( tlodWorld.xz, 1.0 ) ).xy;
\t#endif`)
      .replace('#include <beginnormal_vertex>',
        '#include <beginnormal_vertex>\n\tobjectNormal = vec3( 0.0, 1.0, 0.0 );')
      .replace('#include <begin_vertex>',
        '#include <begin_vertex>\n\ttransformed = tlodWorld;');
    if (!shader.fragmentShader.includes('#include <normal_fragment_begin>')) return;
    shader.fragmentShader = terrainLodSampleGlsl() + terrainLodNormalGlsl()
      + shader.fragmentShader.replace('#include <normal_fragment_begin>',
        `#include <normal_fragment_begin>
\tnormal = normalize( ( viewMatrix * vec4( tlodNormalAt( vTlodXZ ), 0.0 ) ).xyz );
\tnonPerturbedNormal = normal;`);
  };
  const own = water
    ? `${TERRAIN_LOD_CACHE_KEY}+${TERRAIN_LOD_WATER_CACHE_KEY}`
    : TERRAIN_LOD_CACHE_KEY;
  mat.customProgramCacheKey = () => (prevKey ? `${prevKey}+${own}` : own);
}

/** The one patch geometry — `PATCH_N`² cells in [0, 1]², every cell split from
 *  its minimum corner to its maximum one (the split `gridMesh` uses, so the
 *  triangulation of the ground reads the same everywhere). */
function patchGeometry(): { pos: Float32Array; uv: Float32Array; index: Uint16Array } {
  const n = PATCH_N;
  const side = n + 1;
  const pos = new Float32Array(side * side * 3);
  const uv = new Float32Array(side * side * 2);
  for (let j = 0; j < side; j += 1) {
    for (let i = 0; i < side; i += 1) {
      const v = j * side + i;
      pos[v * 3] = i / n;
      pos[v * 3 + 1] = 0;
      pos[v * 3 + 2] = j / n;
      uv[v * 2] = i / n;
      uv[v * 2 + 1] = j / n;
    }
  }
  const index = new Uint16Array(n * n * 6);
  let k = 0;
  for (let j = 0; j < n; j += 1) {
    for (let i = 0; i < n; i += 1) {
      const a = j * side + i;
      index[k] = a; index[k + 1] = a + side; index[k + 2] = a + side + 1;
      index[k + 3] = a; index[k + 4] = a + side + 1; index[k + 5] = a + 1;
      k += 6;
    }
  }
  return { pos, uv, index };
}

/** A packed pyramid as an R32F data texture, read by `texelFetch` alone —
 *  hence NEAREST and no mipmaps: the filtering is done by hand in the shader,
 *  which is what makes it the same arithmetic as the CPU's. */
function pyramidTexture(pyr: HeightPyramid): THREE.DataTexture {
  const tex = new THREE.DataTexture(pyr.data, pyr.texW, pyr.texH,
                                    THREE.RedFormat, THREE.FloatType);
  tex.minFilter = THREE.NearestFilter;
  tex.magFilter = THREE.NearestFilter;
  tex.wrapS = THREE.ClampToEdgeWrapping;
  tex.wrapT = THREE.ClampToEdgeWrapping;
  tex.generateMipmaps = false;
  tex.unpackAlignment = 1;
  tex.needsUpdate = true;
  return tex;
}

/** What the terrain renderer offers its owner (`scene/ground.ts`). */
export interface TerrainLod {
  /**
   * The mesh, to be hung into the ground group once.
   *
   * SINCE K-A E3 IT CARRIES THE WET MESH AS ITS CHILD. The water variant is a
   * second program and therefore a second draw call, and a second draw call is
   * a second `THREE.Mesh` — there is no way to give two instances of one mesh
   * two programs. It is hung UNDER this one rather than beside it so the
   * owner's `group.add` / `group.remove` and the isolation panel's
   * `visible = false` keep meaning "the terrain", whole. Both sit at the
   * origin with an identity matrix, so nothing is transformed by the nesting.
   */
  readonly mesh: THREE.Mesh;
  /**
   * SELECT THE FRAME'S PIECES AND WRITE THEM INTO THE INSTANCE BUFFER — called
   * once per frame from the tick, BEFORE `renderer.render`.
   *
   * IT MAY NOT RUN FROM `onBeforeRender`, and that is measured rather than
   * tasted (2026-08-22). three.js uploads a geometry's dirty attributes in
   * `projectObject` — `WebGLObjects.update`, guarded by "Update once per frame"
   * — and `projectObject` runs over the whole scene BEFORE the first
   * `object.onBeforeRender`. A selection written in `onBeforeRender` therefore
   * reaches the GPU one frame late, while `geometry.instanceCount` (read at
   * draw time) is this frame's number: the card draws the first `n` rows of the
   * PREVIOUS frame's list. Written here, the buffer is dirty before
   * `projectObject` sees it and the drawn set is the selected set.
   *
   * `viewportPx` is the drawing buffer's height in pixels — the screen-space
   * error rule needs it and this module has no canvas.
   */
  update(camera: THREE.Camera, viewportPx: number): void;
  /** Take over the relief. `baseStepM` is the server's FINE step
   *  (`tile_step_m`), which fixes the leaf size for good — a lattice that
   *  changed size when a tile arrived would re-anchor the whole quadtree.
   *
   *  `water` is the second field of the same tiles (Wasser v2, K-A E2). It
   *  rides in HERE and not in a call of its own because it is built over the
   *  SAME near window: two entry points would be two chances for the two
   *  pyramids to describe different rectangles, and the shader reads them at
   *  one world position. */
  setField(relief: WorldHeightTiles | null, baseStepM: number,
           anchorX: number, anchorZ: number,
           water?: WaterRaster | null): void;
  /** The relief's STATISTICS grew without its heights changing — re-derive the
   *  per-level errors and nothing else.
   *
   *  The narrow half of `setField`: the tile statistics arrive after the
   *  overview does (`GET /play/heightfield` caps them at 64,
   *  `GET /play/heightfield/stats` delivers the rest), and only `levelErrorM`
   *  is cached off them. `nodeBounds` reads the very same map per call and is
   *  current the moment a statistic lands; the pyramids are built from HEIGHTS
   *  and would be rebuilt for nothing. */
  refreshStats(): void;
  /** The world rectangle to cover, `[minX, minZ, maxX, maxZ]`. */
  setExtent(rect: readonly [number, number, number, number]): void;
  /**
   * The ground material — built by the owner (kind, textures, hole patch,
   * natural-ground stages) and patched here.
   *
   * TWO OF THEM SINCE K-A E3, and they must come out of the SAME builder: `dry`
   * is patched exactly as before, `water` gains the `max(h, w_level)` lift.
   * Anything the owner does to one it has to do to the other, or a piece of
   * ground would change its look at the shore for no reason — which is why the
   * owner builds them in one function and this takes both at once rather than
   * offering a second entry point that could be forgotten.
   */
  setMaterial(dry: THREE.Material, water: THREE.Material): void;
  /** Both ground materials, dry first — what a diagnostic that wants to act on
   *  "the terrain's material" (the isolation panel's wireframe) has to reach.
   *  Empty until `setMaterial`. */
  materials(): THREE.Material[];
  /** How many pieces the last selection drew, for the performance readout —
   *  BOTH variants, since the split is a partition of one selection. */
  nodeCount(): number;
  /** How many of those pieces carry water and are therefore drawn by the
   *  lifting program (K-A E3). 0 in a world without a drop, which is the case
   *  the risk rule is about — the second draw call is then skipped entirely. */
  waterNodeCount(): number;
  /** DIAGNOSTIC: the instance cap three.js draws against
   *  (`geometry._maxInstanceCount`) and the attribute's capacity. Both are
   *  `MAX_NODES` and stay there — the buffer is allocated once and never
   *  replaced, and the cap is set by hand because three freezes it at the first
   *  bind of a plain Mesh over an InstancedBufferGeometry and never raises it
   *  again (three issues #19595, #26363, #32099). `cap < nodeCount()` would
   *  mean the renderer silently drops the tail of the selection every frame.
   *
   *  THE TIGHTER OF THE TWO GEOMETRIES since K-A E3 — both are allocated at
   *  `MAX_NODES` and the split is a PARTITION of one selection, so either one
   *  alone already holds every piece there can be; reporting the minimum means
   *  a readout that would notice if that ever stopped being true. */
  instanceCap(): { cap: number; capacity: number };
  /** How many NON-DEGENERATE triangles those pieces draw — `Σ cells² · 2`. The
   *  patch always submits `PATCH_N² · 2` per instance; the ones past a piece's
   *  own `cells` collapse onto its last row and column and rasterize nothing,
   *  so this is the number that says what the ground really costs. */
  triangleCount(): number;
  /**
   * STOP RE-SELECTING (`debug3d.ts`, toggle 10). While frozen the per-frame
   * quadtree selection is skipped and the instance buffer of the frame the
   * switch was flipped keeps being drawn, however the camera moves.
   *
   * IT FREEZES THE DRAWING RULE, NOT ONLY THE LIST (2026-08-22). The morph is a
   * function of each vertex's distance to the camera, so a frozen node set drawn
   * against a LIVE camera is not the frozen frame: the pieces keep morphing, and
   * once the camera has moved the invariant that makes them meet — a piece's
   * coarser neighbour lies entirely beyond `lodRange[L]` — no longer holds, so
   * the toggle would open the very cracks it is meant to rule out. The frozen
   * eye is therefore handed to the shader as well (`uTlodFreeze`), and what the
   * toggle shows is exactly the geometry of the frame it was flipped on, seen
   * from a moving viewpoint. A picture that still shimmers under it cannot blame
   * the terrain geometry at all.
   */
  setFrozen(on: boolean): void;
  dispose(): void;
}

/**
 * Build the terrain renderer. One mesh, one draw call, no state of its own
 * beyond the two pyramids and the instance buffer.
 *
 * THE SELECTION RUNS PER FRAME, from the tick (`TerrainLod.update`, called by
 * `scene/ground.ts` `tickTerrain` out of `main.ts`'s frame hook). Per frame and
 * not on the 1 Hz LOD beat because the morph is a function of the camera's
 * distance: a slower beat would step the ground in visible jumps while the
 * camera flies, the very popping CDLOD exists to remove. A selection is a few
 * hundred box distances and costs less than one of the draws it saves. From the
 * TICK and not from the mesh's `onBeforeRender` because three uploads the
 * instance attribute before it calls that hook — see `TerrainLod.update`.
 */
export function createTerrainLod(): TerrainLod {
  const patch = patchGeometry();
  // ONE patch, TWO geometries — the attributes are SHARED objects and not
  // copies, so the vertex data, the UVs and the index live once on the card
  // (three's `WebGLAttributes` caches per BufferAttribute). Only `iNode`
  // differs, because that is the list of pieces each program draws.
  const patchPos = new THREE.Float32BufferAttribute(patch.pos, 3);
  const patchUv = new THREE.Float32BufferAttribute(patch.uv, 2);
  const patchIndex = new THREE.BufferAttribute(patch.index, 1);

  /**
   * One instanced patch geometry and its node list.
   *
   * THE INSTANCE BUFFER IS ALLOCATED ONCE, AT THE CEILING, AND NEVER REPLACED
   * (2026-08-22). three.js freezes `geometry._maxInstanceCount` at the FIRST
   * bind of a plain Mesh over an InstancedBufferGeometry
   * (`WebGLBindingStates.setupVertexAttributes`, guarded by `=== undefined`)
   * and never raises it again, so a buffer that grew later kept drawing
   * against the capacity it happened to have when the first frame was
   * submitted — the tail of every larger selection silently missing. Setting
   * the cap by hand to the ceiling the selection is clamped to (`MAX_NODES`)
   * makes the two one number. 4 096 instances × 4 floats is 64 kB, held for
   * the session; the water variant's second buffer is another 64 kB and is
   * allocated at the same ceiling because the split is a PARTITION — a world
   * that is all water puts every piece into it.
   */
  function makePatchGeo(): { geo: THREE.InstancedBufferGeometry;
                             attr: THREE.InstancedBufferAttribute } {
    const g = new THREE.InstancedBufferGeometry();
    g.setAttribute('position', patchPos);
    g.setAttribute('uv', patchUv);
    g.setIndex(patchIndex);
    // The bounding sphere is never used for culling (the mesh is not culled as
    // a whole — its nodes are), but three computes one on demand and would do
    // it from the UNDISPLACED patch, i.e. a sphere of radius 1 at the origin. A
    // world-sized one is the honest answer for geometry that is placed in the
    // vertex shader.
    g.boundingSphere = new THREE.Sphere(new THREE.Vector3(), 1e6);
    const a = new THREE.InstancedBufferAttribute(new Float32Array(MAX_NODES * 4), 4);
    a.setUsage(THREE.DynamicDrawUsage);
    g.setAttribute('iNode', a);
    g.instanceCount = 0;
    (g as unknown as { _maxInstanceCount: number })._maxInstanceCount = MAX_NODES;
    return { geo: g, attr: a };
  }

  const dryGeo = makePatchGeo();
  const wetGeo = makePatchGeo();
  const geo = dryGeo.geo;
  const nodeAttr = dryGeo.attr;
  const waterGeo = wetGeo.geo;
  const waterAttr = wetGeo.attr;

  /** The placeholder until the owner hands the real ground material in — it
   *  draws nothing, so a client whose terrain payload has not arrived shows an
   *  empty world rather than a magenta one. */
  const placeholder = new THREE.MeshBasicMaterial({ visible: false });
  const mesh: THREE.Mesh<THREE.BufferGeometry, THREE.Material> = new THREE.Mesh(geo, placeholder);
  mesh.frustumCulled = false;
  mesh.receiveShadow = true;
  mesh.renderOrder = 0;
  mesh.matrixAutoUpdate = false;
  // THE WET HALF, as a CHILD of the dry one (K-A E3). Same origin, same
  // identity matrix, same flags — the nesting is a lifetime and visibility
  // arrangement and never a transform. See `TerrainLod.mesh`.
  const waterMesh: THREE.Mesh<THREE.BufferGeometry, THREE.Material>
    = new THREE.Mesh(waterGeo, placeholder);
  waterMesh.frustumCulled = false;
  waterMesh.receiveShadow = true;
  waterMesh.renderOrder = 0;
  waterMesh.matrixAutoUpdate = false;
  mesh.add(waterMesh);

  let relief: WorldHeightTiles | null = null;
  let baseStep = 0;
  let nearPyr: HeightPyramid | null = null;
  let farPyr: HeightPyramid | null = null;
  let waterPyr: HeightPyramid | null = null;
  let nearTex: THREE.DataTexture | null = null;
  let farTex: THREE.DataTexture | null = null;
  let waterTex: THREE.DataTexture | null = null;
  let nearRect: [number, number, number, number] | null = null;
  let extent: [number, number, number, number] = [-100, -100, 100, 100];
  let leafM = 0;
  let nodes = 0;
  let waterNodes = 0;
  let triangles = 0;
  /**
   * WHICH TILES CARRY WATER — the gate of the second material variant, taken
   * as a SNAPSHOT in `setField` beside the pyramid it belongs to.
   *
   * A snapshot and not the live `WaterRaster`, although holding the reference
   * would be one word less: the water PYRAMID is rebuilt in `setField` and
   * nowhere else, so a gate that walked ahead of it would mark pieces wet that
   * the pyramid still says nothing about (harmless, they draw the same ground)
   * or — the other way round, when a tile is dropped — leave a piece whose
   * pyramid still holds water on the dry program, which is the one direction
   * that cracks. One Set of a few hundred short strings per field change buys
   * "the gate and the pyramid are the same raster" outright.
   */
  let waterTileKeys: Set<string> | null = null;
  let waterTileM = 0;
  /** The height span of everything held — the fallback box of a node the tile
   *  statistics say nothing about. */
  let globalRange = { min: 0, max: 0 };

  function setLevels(target: THREE.Vector4[], pyr: HeightPyramid | null): void {
    for (let i = 0; i < MAX_LOD_LEVELS; i += 1) {
      const lv = pyr?.levels[i];
      if (lv) target[i].set(lv.cols, lv.rows, lv.step, lv.row0);
      else target[i].set(0, 0, 0, 0);
    }
  }

  /** The overview as its own pyramid — the far half of the field. */
  function buildFar(ov: WorldHeightField | null): HeightPyramid | null {
    const rows = ov?.heights?.length ?? 0;
    const cols = ov?.heights?.[0]?.length ?? 0;
    if (!ov || rows < 2 || cols < 2 || !(ov.step_m > 0)) return null;
    const at = (x: number, z: number): number => {
      const fx = Math.round((x - ov.origin_x) / ov.step_m);
      const fz = Math.round((z - ov.origin_z) / ov.step_m);
      const v = ov.heights[fz]?.[fx];
      return typeof v === 'number' && Number.isFinite(v) ? v : 0;
    };
    return buildPyramid(at, ov.origin_x, ov.origin_z, ov.step_m, cols, rows,
                        MAX_LOD_LEVELS);
  }

  /**
   * The near window — the loaded tiles at the fine step, filled from
   * `heightAt` itself.
   *
   * Filling it through the sampler rather than copying tile rows is what makes
   * the branch in the shader honest: inside the window the texture IS
   * `heightAt`, tile-first precedence and all, and in the margin strip past
   * the loaded tiles it is the overview — the same number the far pyramid
   * carries there, which is why switching between the two at the rectangle's
   * edge is not a seam.
   */
  function buildNear(c: WorldHeightTiles, step: number,
                     anchorX: number, anchorZ: number): HeightPyramid | null {
    if (!c.tiles?.size || !(step > 0) || !(c.tileM > 0)) return null;
    let x0 = Infinity;
    let z0 = Infinity;
    let x1 = -Infinity;
    let z1 = -Infinity;
    for (const key of c.tiles.keys()) {
      const [tx, tz] = key.split(',').map(Number);
      if (!Number.isFinite(tx) || !Number.isFinite(tz)) continue;
      x0 = Math.min(x0, tx * c.tileM);
      z0 = Math.min(z0, tz * c.tileM);
      x1 = Math.max(x1, (tx + 1) * c.tileM);
      z1 = Math.max(z1, (tz + 1) * c.tileM);
    }
    if (!Number.isFinite(x0)) return null;
    const ovStep = c.overview?.step_m ?? step;
    const margin = Math.max(NEAR_MARGIN_MIN_M, NEAR_MARGIN_CELLS * ovStep);
    x0 -= margin; z0 -= margin; x1 += margin; z1 += margin;
    // Snapped onto the fine lattice, which is anchored at the world origin —
    // the tile origins are multiples of `tileM` and `tileM` is a multiple of
    // the step, so the window's lattice IS the tiles' lattice.
    x0 = Math.floor(x0 / step) * step;
    z0 = Math.floor(z0 / step) * step;
    let cols = Math.floor((x1 - x0) / step) + 1;
    let rows = Math.floor((z1 - z0) / step) + 1;
    if (cols > NEAR_MAX_TEXELS || rows > NEAR_MAX_TEXELS) {
      // The cap bites only for a tile size this client has never seen. Centre
      // what is left on the anchor so the player at least stands in it.
      const halfX = Math.min(cols, NEAR_MAX_TEXELS) * step / 2;
      const halfZ = Math.min(rows, NEAR_MAX_TEXELS) * step / 2;
      x0 = Math.floor((anchorX - halfX) / step) * step;
      z0 = Math.floor((anchorZ - halfZ) / step) * step;
      cols = Math.min(cols, NEAR_MAX_TEXELS);
      rows = Math.min(rows, NEAR_MAX_TEXELS);
    }
    if (cols < 2 || rows < 2) return null;
    const pyr = buildPyramid((x, z) => heightAt(c, x, z), x0, z0, step,
                             cols, rows, MAX_LOD_LEVELS);
    nearRect = [x0, z0, x0 + (cols - 1) * step, z0 + (rows - 1) * step];
    return pyr;
  }

  /**
   * The WATER window — the same rectangle, the same lattice, filled from
   * `rasterLevelAt` (K-A E2).
   *
   * It is built over `nearPyr`'s own geometry rather than over the tiles' own
   * boxes, and that is the whole point: the shader reads a height and a water
   * level at ONE world position, so the two textures have to be the same
   * lattice or the mask would sit a fraction of a texel beside the ground it
   * masks. Where the raster has no tile the sampler answers NaN, which is the
   * dry sentinel all the way through to the texture.
   */
  function buildWater(raster: WaterRaster | null): HeightPyramid | null {
    const base = nearPyr?.levels[0];
    if (!nearPyr || !base || !raster?.tiles?.size) return null;
    return buildWaterPyramid((x, z) => rasterLevelAt(raster, x, z),
                             nearPyr.originX, nearPyr.originZ, nearPyr.step,
                             base.cols, base.rows, MAX_LOD_LEVELS);
  }

  function uploadPyramids(): void {
    nearTex?.dispose();
    farTex?.dispose();
    waterTex?.dispose();
    nearTex = nearPyr ? pyramidTexture(nearPyr) : null;
    farTex = farPyr ? pyramidTexture(farPyr) : null;
    waterTex = waterPyr ? pyramidTexture(waterPyr) : null;
    uNear.value = nearTex ?? neutralTex;
    uFar.value = farTex ?? neutralTex;
    uWater.value = waterTex ?? neutralTex;
    uWaterGeom.value.set(waterPyr?.originX ?? 0, waterPyr?.originZ ?? 0,
                         waterPyr?.step ?? 1, waterPyr?.levels.length ?? 0);
    setLevels(uWaterLevel.value, waterPyr);
    uNearGeom.value.set(nearPyr?.originX ?? 0, nearPyr?.originZ ?? 0,
                        nearPyr?.step ?? 1, nearPyr?.levels.length ?? 0);
    uFarGeom.value.set(farPyr?.originX ?? 0, farPyr?.originZ ?? 0,
                       farPyr?.step ?? 1, farPyr?.levels.length ?? 0);
    setLevels(uNearLevel.value, nearPyr);
    setLevels(uFarLevel.value, farPyr);
    if (nearPyr && nearRect) uNearRect.value.set(...nearRect);
    else uNearRect.value.set(0, 0, -1, -1);
  }

  /** The vertical box of a node — `nodeBounds` on what this renderer holds.
   *  The rule itself is up there, exported, so the coverage check of § B5a
   *  measures the shipped one. */
  function boundsOf(x: number, z: number, size: number): { min: number; max: number } {
    return nodeBounds(relief?.stats, relief?.tileM ?? 0, globalRange, x, z, size);
  }

  /** The worst vertical error per NODE LEVEL of the relief that stands —
   *  recomputed whenever the field changes or its statistics grow, never per
   *  frame. The rule itself is `levelErrorsFrom`, up there and exported. */
  function computeLevelError(): number[] {
    return levelErrorsFrom(relief?.stats, relief?.mipLevelsM,
                           baseStep, MAX_LOD_LEVELS);
  }
  let levelErrorM: number[] = new Array<number>(MAX_LOD_LEVELS).fill(0);

  /**
   * Re-select the nodes for a camera and hand them to the instance buffer.
   *
   * A WORLD WITH NO RELIEF STILL GETS A GROUND, and since 2026-08-22 it gets
   * the SAME ground every other world gets: the rings apply, a level world is
   * drawn by the same 64 m leaves near the camera and the same coarse pieces
   * far away. The shortcut that used to answer "no relief → no ranges → roots
   * only" made the whole visible world 3–4 pieces of 2 048 m — a granularity at
   * which every per-frame decision about a piece is a decision about a square
   * kilometre, which is how one wrong verdict became a hole in the sky. It also
   * lied about the relief: a "flat" world is only flat in the OVERVIEW, and the
   * painted kinds' micro-relief (`app/core/heightfield.py`) rides in with the
   * fine tiles, where the very same shortcut had already decided there was
   * nothing to spend triangles on.
   */
  function update(camera: THREE.Camera, viewportPx: number): void {
    if (!leafM) {
      geo.instanceCount = 0;
      waterGeo.instanceCount = 0;
      nodes = 0;
      waterNodes = 0;
      triangles = 0;
      return;
    }
    camera.updateMatrixWorld();
    const cam = camera.position;
    const persp = camera as THREE.PerspectiveCamera;
    const fov = persp.isPerspectiveCamera ? persp.fov : 0;
    // Pixels per metre of vertical error at one metre — the projection's own
    // scale. Without a canvas height the error rule simply does not fire.
    const pixelScale = fov > 0 && viewportPx > 0
      ? viewportPx / (2 * Math.tan((fov * Math.PI) / 360))
      : 0;
    // The pieces AND the rings they were chosen against — `selectLodFitted`
    // may halve the rings to stay under `MAX_NODES`, and the shader has to
    // morph against the rings the selection really used or every piece would
    // measure its λ on a ladder it was not picked from.
    const sel = selectLodFitted({
      x0: extent[0], z0: extent[1], x1: extent[2], z1: extent[3],
      leafM,
      levels: MAX_LOD_LEVELS,
      minLodDistance: MIN_LOD_DISTANCE_M,
      camX: cam.x, camY: cam.y, camZ: cam.z,
      boundsOf,
      levelErrorM,
      pixelScale,
    });
    const picked = sel.nodes;
    for (let i = 0; i < MAX_LOD_LEVELS; i += 1) uRange.value[i] = sel.ranges[i] ?? 0;
    const arr = nodeAttr.array as Float32Array;
    const warr = waterAttr.array as Float32Array;
    triangles = 0;
    // THE PARTITION (K-A E3). One selection, two lists: a piece whose closed
    // rectangle touches a tile of the water raster is drawn by the lifting
    // program, everything else by the program the dry world has always used.
    // The two counts sum to the selection, so neither buffer can overrun.
    let dry = 0;
    let wet = 0;
    for (let i = 0; i < picked.length; i += 1) {
      const n = picked[i];
      const carries = nodeHasWater(waterTileKeys, waterTileM, n.x, n.z, n.size);
      const dst = carries ? warr : arr;
      const at = (carries ? wet++ : dry++) * 4;
      dst[at] = n.x;
      dst[at + 1] = n.z;
      dst[at + 2] = n.size;
      // THE LEVEL, not the morph: every vertex reads its own λ and subtracts
      // this (`lodLambda`, `tlodCompute`). One morph per node is what stood two
      // neighbouring patches 0.61 m apart along the edge they share. The level
      // also FIXES THE VERTEX SPACING (`uTlodBaseStep · 2^level`), which is how
      // a parent quadrant draws a child-sized square at the parent's density —
      // `cells` is `size / spacing` and needs no attribute of its own.
      dst[at + 3] = n.level;
      triangles += n.cells * n.cells * 2;
    }
    nodeAttr.needsUpdate = true;
    waterAttr.needsUpdate = true;
    geo.instanceCount = dry;
    waterGeo.instanceCount = wet;
    nodes = picked.length;
    waterNodes = wet;
  }

  /** The isolation panel's LOD freeze — see `TerrainLod.setFrozen`. */
  let frozen = false;

  return {
    mesh,
    update(camera, viewportPx) {
      // Shadow passes never reach here any more (the tick calls this once, with
      // the scene camera), but a caller handing in the light's orthographic one
      // would select a ground for a viewpoint nobody draws from.
      if (!(camera as THREE.PerspectiveCamera).isPerspectiveCamera) return;
      if (frozen) return;
      update(camera, viewportPx);
      // The eye the morph would be measured from if the next frame froze. Kept
      // current so `setFrozen(true)` needs no camera of its own.
      uFreeze.value.set(camera.position.x, camera.position.y, camera.position.z,
                        uFreeze.value.w);
    },
    setField(next, baseStepM, anchorX, anchorZ, water) {
      relief = next;
      baseStep = baseStepM > 0 ? baseStepM : finestStep(next) || FALLBACK_BASE_STEP_M;
      leafM = PATCH_N * baseStep;
      // The shading normal differences over ONE base lattice step, whatever the
      // ground under a pixel is drawn at (`terrainLodNormalGlsl`).
      uNormalSpan.value = baseStep;
      // …and the vertex spacing of a piece is that step doubled per level
      // (`terrainLodGlsl`). Two uniforms for one number on purpose: the normal
      // span is a shading decision that may yet move, the base step is the
      // lattice itself.
      uBaseStep.value = baseStep;
      farPyr = buildFar(next?.overview ?? null);
      nearRect = null;
      nearPyr = next ? buildNear(next, baseStep, anchorX, anchorZ) : null;
      let min = 0;
      let max = 0;
      for (const pyr of [nearPyr, farPyr]) {
        const base = pyr?.levels[0];
        if (!pyr || !base) continue;
        for (let j = 0; j < base.rows; j += 1) {
          const row = j * pyr.texW;
          for (let i = 0; i < base.cols; i += 1) {
            const v = pyr.data[row + i];
            if (v < min) min = v;
            if (v > max) max = v;
          }
        }
      }
      globalRange = { min, max };
      levelErrorM = computeLevelError();
      // AFTER the near pyramid, because it is built over the near pyramid's own
      // window — and never over the far one, which has no water in it.
      waterPyr = buildWater(water ?? null);
      // …and the GATE is snapshotted from the same raster in the same breath
      // (K-A E3). A pyramid without tiles behind it can lift nothing, so the
      // gate is emptied with it and every piece goes back to the dry program.
      waterTileM = waterPyr ? (water?.tileM ?? 0) : 0;
      waterTileKeys = waterPyr && water?.tiles?.size
        ? new Set(water.tiles.keys()) : null;
      uploadPyramids();
    },
    refreshStats() {
      levelErrorM = computeLevelError();
    },
    setExtent(rect) {
      extent = [rect[0], rect[1], rect[2], rect[3]];
      uExtent.value.set(rect[0], rect[1], rect[2], rect[3]);
    },
    setMaterial(dryMat, waterMat) {
      patchTerrainLod(dryMat);
      patchTerrainLod(waterMat, true);
      mesh.material = dryMat;
      waterMesh.material = waterMat;
    },
    materials: () => (mesh.material === placeholder
      ? [] : [mesh.material, waterMesh.material]),
    nodeCount: () => nodes,
    waterNodeCount: () => waterNodes,
    instanceCap: () => {
      const capOf = (g: THREE.InstancedBufferGeometry): number =>
        (g as unknown as { _maxInstanceCount?: number })._maxInstanceCount ?? -1;
      const capacityOf = (g: THREE.InstancedBufferGeometry): number =>
        (g.getAttribute('iNode') as THREE.InstancedBufferAttribute | undefined)?.count ?? 0;
      return {
        cap: Math.min(capOf(geo), capOf(waterGeo)),
        capacity: Math.min(capacityOf(geo), capacityOf(waterGeo)),
      };
    },
    triangleCount: () => triangles,
    setFrozen(on) {
      frozen = on;
      uFreeze.value.w = on ? 1 : 0;
    },
    dispose() {
      geo.dispose();
      waterGeo.dispose();
      placeholder.dispose();
      nearTex?.dispose();
      farTex?.dispose();
      waterTex?.dispose();
      nearTex = null;
      farTex = null;
      waterTex = null;
      // The pyramids are module-shared uniforms and outlive this closure, so
      // they are handed back explicitly — the rule `setNaturalGroundField(null)`
      // follows for the same reason.
      uNear.value = neutralTex;
      uFar.value = neutralTex;
      uWater.value = neutralTex;
      uNearRect.value.set(0, 0, -1, -1);
    },
  };
}
