#!/usr/bin/env node
/**
 * Smoke check for THE AUTOMATIC UNDERGROWTH — the layer nobody authored, as it
 * stands after the camera-local rebuild (plan-undergrowth-rettung.md,
 * 2026-08-16). Two modules, one subject: the numbers in
 * `client3d/src/scene/scatterLod.ts` (`UNDERGROWTH_*`) and everything that is
 * not a plain number in `client3d/src/scene/undergrowth.ts` — the cell raster,
 * the blade texture, the crossed quads and the field that grows them.
 *
 * Usage:  node client3d/scripts/smoke_undergrowth.mjs
 *
 * WHERE THESE CASES COME FROM. Sections (E) and part of (C) are the old
 * section (K) of `smoke_scatter_math.mjs`, moved here whole: the layer is no
 * longer a variant of the authored scatter (it has its own raster, its own
 * seed shape and its own look), so its checks no longer belong in the file
 * about where a PROP stands. `smoke_scatter_math.mjs` went from 239 to 180
 * checks in that move, and the cases that did NOT come along are the ones the
 * rebuild deleted: the per-AREA count rule (`undergrowthCount`), its 20 000
 * ceiling and the "capped" report (`undergrowthCapped`) — the area is not the
 * unit any more, so there is no per-area number to check.
 *
 * Same discipline as `smoke_scatter_math.mjs` and `smoke_height_tiles.mjs`:
 * every expected number below is derived BY HAND in this header and NEVER
 * recorded from the current output.
 *
 * TWO LOADERS, for two kinds of module. `scatterLod.ts` has no import at all,
 * so a plain esbuild transpile is enough. `undergrowth.ts` imports three and
 * the shared sampler, so it is BUNDLED with `external: ['three']` and pulled
 * in against node's own three — the trick `smoke_occlusion.mjs` uses, and what
 * lets section (F)/(G) build REAL materials and REAL instanced meshes instead
 * of asserting against a copy of the code.
 *
 * ============================================================================
 * (A) THE CELL RASTER — `wantedUndergrowthCells`, the `heightTiles` pattern
 * ============================================================================
 * The world is cut into an ORIGIN-ANCHORED raster of `UNDERGROWTH_CELL_M`
 * (64 m) and the cells within `UNDERGROWTH_CELL_RADIUS_M` (128 m) of the
 * anchor are held. The test is SQUARE-to-point: `dx` is the distance from the
 * anchor to the cell's box, 0 on the axes where the anchor is inside it.
 *
 * (A1) THE ANCHOR IN THE MIDDLE OF ITS CELL, (32, 32) — cell (0, 0).
 *      first = floor((32 − 128)/64) = floor(−1.5) = −2
 *      last  = floor((32 + 128)/64) = floor(2.5)  = 2      -> 5 columns
 *      dx per column (−2 … 2):  96, 32, 0, 32, 96
 *        cx = −2: the box runs −128 … −64, so dx = 32 − (−64) = 96
 *        cx = −1: −64 … 0,     dx = 32 − 0 = 32
 *        cx =  0: 0 … 64,      the anchor is inside, dx = 0
 *      and the same five by symmetry on z. Accepted when dx² + dz² ≤ 128²
 *      = 16384:
 *        96² + 96² = 18432  > 16384  -> the FOUR corners fall out
 *        96² + 32² = 10240  ≤        -> in
 *        96² + 0   =  9216  ≤        -> in
 *      -> 25 − 4 = 21 cells, and the first of them is the anchor's own
 *         ("0,0", distance 0).
 *
 * (A2) THE ANCHOR ON A CELL CORNER, (0, 0). Now the raster is asymmetric
 *      about the anchor, which is exactly the case a centre-to-point test
 *      would get wrong:
 *      first = floor(−2) = −2, last = floor(2) = 2
 *      dx per column (−2 … 2): 64, 0, 0, 64, 128
 *        cx = −1 (−64 … 0) and cx = 0 (0 … 64) both TOUCH the anchor -> 0
 *        cx =  2 (128 … 192) is a full 128 m away — the very edge
 *      accepted:
 *        dx = 64: dz ∈ {64, 0, 0, 64} in (8192 / 4096 ≤ 16384), dz = 128 out
 *                 -> 4 rows each, twice           =  8
 *        dx =  0: every dz, 128 included (0 + 16384 = 16384, EQUAL -> in)
 *                 -> 5 rows each, twice           = 10
 *        dx = 128: only dz = 0 (16384 + 0), i.e. cz ∈ {−1, 0}
 *                                                 =  2
 *      -> 20 cells. Four of them are at distance 0 ("−1,−1", "−1,0", "0,−1",
 *         "0,0"), so the tie-break by key decides the first: "−1,−1".
 *
 * (A3) THE BORDER CROSSING, which is the whole point of the want set. Walking
 *      from (32, 32) to (96, 32) is one cell to the east, and since both are
 *      cell CENTRES the set is (A1) shifted by one column: still 21 cells, and
 *      the difference is
 *        dropped: the whole cx = −2 column of (A1), which is |cx| = 2 and
 *                 therefore only cz ∈ {−1, 0, 1}          -> 3
 *                 plus (−1, ±2), which in the shifted set ARE corners  -> 2
 *                                                          -> 5
 *        added:   the mirror image of that                 -> 5
 *
 * (A3b) AND THE SET MOVES WITHIN A CELL TOO, because the radius is measured
 *      from the POINT and not from the cell — the very reason
 *      `heightTiles.ts` re-asks on every poll instead of only on a crossing,
 *      and the reason the field does. From (63, 32), still in cell (0, 0):
 *        first = floor((63 − 128)/64) = −2, last = floor(191/64) = 2
 *        dx per column (−2 … 2): 127, 63, 0, 1, 65
 *        dz is (A1)'s:            96, 32, 0, 32, 96
 *        cx = −2: 127² = 16129, so dz² ≤ 255 -> only dz = 0          -> 1
 *        every other column clears 128 for all five rows             -> 20
 *      -> 21 cells again, but NOT the same 21: (−2, ±1) have dropped out and
 *         (2, ±2) have come in. Two out, two in.
 *
 * (A4) JUNK IN, NOTHING OUT: a NaN anchor, an infinite one and a negative
 *      radius all answer with no cells rather than with a loop over the world.
 *      A radius of 0 is the anchor's own cell and nothing else.
 *
 * ============================================================================
 * (B) THE SEED — one per (area, cell)
 * ============================================================================
 * `undergrowthCellSeed(id, cx, cz)` = `terrain:undergrowth:<id>:<cx>,<cz>`.
 * Two things hang on that string and each has its own counter-check.
 *
 * (B1) THE NAMESPACE keeps the layer out of the authored scatter's stream
 *      (`terrain:scatter:<id>:<index>`): two different strings are two
 *      different FNV-1a states, so the tufts cannot stand on the props.
 *
 * (B2) THE CELL keeps neighbours apart. Sampled with the real seed, cell
 *      (0, 0) and cell (1, 0) give point lists whose offsets INSIDE the cell
 *      differ; asked for the same cell twice, they are identical to the last
 *      bit — that is what "walking back gives the same tufts" means.
 *
 * (B3) THE RED COUNTER-CHECK, by mutating the source: the seed drops the cell
 *      and becomes `terrain:undergrowth:<id>`. Every cell then draws the same
 *      sequence of random numbers, and since each maps them onto its own box
 *      the mutant's two neighbouring cells are the SAME tuft pattern stamped
 *      out 64 m apart — measured as "the in-cell offsets are equal to the last
 *      decimal", which the real seed is asserted NOT to be.
 *
 * ============================================================================
 * (C) HOW MANY — the density, per CELL and no longer per shape
 * ============================================================================
 * (C1) THE BASE DENSITY IS 0.40/m2 (0.15 before the rebuild). The catalog
 *      value is a SHARE of it, so the density handed to the sampler is
 *        per 100 m2 = 0.40 · 100 · min(value, 1) = 40 · value
 *      forest 0.6 -> 24 · grass 0.3 -> 12 · full 1.0 -> 40.
 *
 * (C2) ONE FULL CELL is 64 · 64 = 4096 m2, so
 *        count = round(4096/100 · 40 · value) = round(1638.4 · value)
 *        0.6 -> round(983.04)  =  983      the number the design names
 *        0.3 -> round(491.52)  =  492
 *        1.0 -> round(1638.4)  = 1638
 *      and the sampler really places 983 of them in a cell that lies wholly
 *      inside the shape — the count rule and `scatterInstances` must not drift
 *      apart in the last bit of a float.
 *
 * (C3) THE CEILING IS 8000 PER CELL AND CANNOT BE REACHED. The catalog value
 *      is clamped to 1, so the densest legal ground asks for 1638 — a fifth of
 *      it. That is the difference to the old per-area ceiling, which ordinary
 *      worlds hit and were silently thinned by: 1 km2 at 0.6 wanted 90 000
 *      tufts, got 20 000, i.e. 0.02/m2. Pinned as "the cap is above what full
 *      density asks", not as a number the code can produce.
 *
 * (C4) "NOT GIVEN" AND THE CLAMP, because the value crosses a JSON boundary:
 *        0 / −1 / NaN / 'thick' / null / undefined -> density 0, count 0
 *        5 -> clamped to 1 -> 1638, not 8192
 *
 * ============================================================================
 * (D) THE BLADE TEXTURE — a pure pixel function
 * ============================================================================
 * 64 × 64 RGBA, ROW 0 AT THE BOTTOM (a `DataTexture` is uploaded unflipped and
 * the quad's v = 0 is its foot). Seven blades, blade `i`:
 *   rootX  = (i + 0.5)/7 · 64      -> 4.571, 13.714, 22.857, 32, 41.143,
 *                                     50.286, 59.429
 *   height = [0.55, 0.725, 0.90][i mod 3] · 64 -> 35.2, 46.4, 57.6 in turn
 *   bend   = ±0.12 · 64 = ±7.68, + for even i
 *   x(t)   = rootX + bend · t²,  halfW(t) = 2.88 · (1 − t),  t = py/height
 *   cov    = clamp(halfW − |px − x| + 0.5, 0, 1),  px = c + 0.5, py = r + 0.5
 *   grey   = round(255 · (0.7 + 0.3 · py/64))     written EVERYWHERE
 *
 * (D1) THE SHAPE OF THE ARRAY: 64 · 64 · 4 = 16384 bytes, `Uint8ClampedArray`.
 *
 * (D2) A BLADE IS OPAQUE DOWN THE MIDDLE. Blade 3 has rootX = 3.5/7 · 64 = 32
 *      exactly, bend −7.68, height 35.2. In row 0 (py = 0.5):
 *        t = 0.5/35.2 = 0.01420455,  x = 32 − 7.68 · t² = 31.99845
 *        halfW = 2.88 · (1 − t) = 2.83909
 *        c = 31 -> px 31.5, |dx| = 0.49845, cov = 2.83909 − 0.49845 + 0.5
 *                  = 2.84 -> clamped to 1 -> alpha 255
 *        c = 32 -> px 32.5, |dx| = 0.50155 -> likewise 255
 *
 * (D3) …AND TRANSPARENT BETWEEN BLADES. Blades 3 and 4 sit at 32 and 41.143,
 *      so c = 36 (px 36.5) is 4.50 from the one and 4.64 from the other, both
 *      well past halfW + 0.5 = 3.34 -> alpha 0.
 *
 * (D4) THE EDGE IS ANTIALIASED, which is what the alpha cut of 0.35 is set
 *      against. Still blade 3, row 0, c = 29 -> px 29.5, |dx| = 2.49845:
 *        cov = 2.83909 − 2.49845 + 0.5 = 0.84064 -> alpha = round(214.36)
 *        = 214.  No other blade reaches that column (blade 2 stands at
 *        22.858 with halfW 2.855, i.e. 6.64 away).
 *
 * (D5) THE TIP IS NARROWER THAN THE FOOT, and it is measurable exactly. The
 *      summed coverage of ONE ROW is the summed WIDTH of the blades crossing
 *      it: a unit box filter reproduces the area of a ramp of unit slope
 *      exactly, whatever the phase (true while halfW ≥ 0.5, which holds in
 *      both rows below).
 *        row 0  (py = 0.5): every blade crosses it, 2·halfW = 5.76 · (1 −
 *          0.5/h) with h = 35.2 (three blades), 46.4 (two), 57.6 (two):
 *          3 · 5.678182 + 2 · 5.697931 + 2 · 5.708 = 39.8464
 *        row 46 (py = 46.5): 35.2 is long gone and 46.4 ends at py = 46.4, so
 *          only the two 57.6 blades are left:
 *          t = 46.5/57.6 = 0.807292, 2·halfW = 5.76 · 0.192708 = 1.11 each
 *          -> 2.22
 *      Both to a tolerance that only covers the 8-bit rounding of the alpha
 *      channel (±0.5/255 per texel).
 *
 * (D6) THE TOP TENTH IS EMPTY, on purpose: the tallest blade stops at 0.90 of
 *      the edge (57.6), so every row with py > 57.6 — that is r ≥ 58 — is
 *      alpha 0 from end to end. A silhouette touching the border would be cut
 *      off by the clamp instead of ending in a tip.
 *
 * (D7) THE GREY IS THE ROW'S OWN and is written into every texel, transparent
 *      ones included — a black transparent texel bleeds a dark rim into every
 *      mip level.
 *        row 0  -> round(255 · (0.7 + 0.3 · 0.5/64))  = round(179.098) = 179
 *        row 63 -> round(255 · (0.7 + 0.3 · 63.5/64)) = round(254.402) = 254
 *      and R = G = B in both.
 *
 * (D8) HOW MUCH INK THE FOOT CARRIES, exactly. Over the ten lowest rows the
 *      row rule of (D5) applies to every blade (halfW is near its maximum and
 *      the leaning tips have not yet reached each other — at py = 9.5 the
 *      largest lean is 7.68 · 0.27² = 0.56 texels against a spacing of 9.14,
 *      so no two blades overlap and "max" and "sum" are the same picture):
 *        Σ_{r=0}^{9} 5.76 · (1 − (r + 0.5)/h) = 5.76 · [10 − 50/h]
 *        h = 35.2 -> 49.418 (three blades)
 *        h = 46.4 -> 51.393 (two)
 *        h = 57.6 -> 52.600 (two)
 *        -> 3·49.418 + 2·51.393 + 2·52.600 = 356.24
 *      The WHOLE texture is deliberately not pinned to a number: above the
 *      foot the blades lean across each other (±7.68 texels at the tip against
 *      a spacing of 9.14), and a texel takes the strongest blade rather than
 *      the sum, so the total is a little under the 2.88 · Σh = 903 the widths
 *      alone would give. What IS derivable is a BOUND, and it is the one worth
 *      having: the ink is at most 903 texels and an antialiased edge adds at
 *      most one partly covered texel per side per row, i.e. 2 · (3·35 + 2·46 +
 *      2·58) = 626 — so at most 1529 of the 4096 texels carry any alpha at all
 *      and at least 2567 are pure hole. A tuft is mostly hole, which is what
 *      an alpha cut is for.
 *
 * (D9) THE RED COUNTER-CHECK: the alpha is written as a flat 255. The picture
 *      is then a solid square — 4096 texels of ink and not one transparent
 *      texel — so a material with `alphaTest` would draw two solid crossed
 *      boards. That the REAL function leaves thousands of texels fully
 *      transparent is the counter-assertion.
 *
 * ============================================================================
 * (E) THE LOD LADDER — moved here from section (K) of smoke_scatter_math
 * ============================================================================
 * (E1) HOW TALL, out of the instance's own yaw (0.4 … 0.7 m):
 *        h(yaw) = 0.4 + 0.3 · frac(yaw / 2π)
 *        yaw 0 -> 0.4 · π -> 0.55 (the geometry's own height) · 1.5π -> 0.625
 *        2π -> 0.4 (one full turn is the same blade) · NaN / 'x' -> 0.4, never
 *        a NaN scale (which removes the instance instead of shrinking it)
 *
 * (E2) HOW FAR — its own ladder, half the props':
 *        share(d) = 1 up to 30 m, then 1 − (d − 30)/(60 − 30), 0 past 60 m
 *        0 -> 1 · 30 -> 1 · 37.5 -> 0.75 · 45 -> 0.5 · 52.5 -> 0.25 ·
 *        60 -> 0 · 60.001 -> 0 · NaN -> 0
 *      THE FLOOR IS 0 AND THE PROPS' IS 0.25, the one place the two ladders
 *      disagree on purpose: at 45 m the scatter still draws everything while
 *      the carpet is halved, at 60 m the scatter is at 0.85 while the carpet
 *      is gone. Asserted side by side, so a copy of the props' constants
 *      cannot pass.
 *
 * (E3) WHICH tufts survive — properties, never a table:
 *        - inside 30 m all 1000 are drawn;
 *        - at 60 m none is (share exactly 0), which is what makes the missing
 *          hysteresis right: nothing can pop at the cull line;
 *        - STABLE: the set at 45 m built twice is the same set;
 *        - MONOTONE: the set at 52.5 m is a SUBSET of the one at 37.5 m;
 *        - the COUNT is the share within 5 % of 1000 · share;
 *        - tuft 0 (hash 0) is drawn as long as anything is: 59.9 m yes,
 *          60 m no.
 *
 * ============================================================================
 * (F) THE LOOK — crossed quads with an alpha cut, built for real
 * ============================================================================
 * (F1) THE GEOMETRY of one tuft at the reference height 0.55 m: TWO quads,
 *      eight vertices, twelve indices, base at y = 0 (B16) and
 *      0.55 · 1.0 = 0.55 m wide.
 *        quad A lies in the xz-plane's +Z face: x = ±0.275, z = 0
 *        quad B is A turned by 80° about +Y, so its own +X axis is
 *          (cos 80°, 0, −sin 80°) = (0.173648, 0, −0.984808)
 *          -> its first vertex is (−0.275 · 0.173648, 0, +0.275 · 0.984808)
 *             = (−0.0477533, 0, 0.2708221)
 *        NOT 90°: two quads at a right angle look the same from four
 *        directions and a field of them shows the pattern.
 *
 * (F2) THE MATERIAL is alpha-CUT and not transparent: `alphaTest` 0.35,
 *      `transparent` false, `side` DoubleSide, `castShadow` off on the mesh.
 *      That is what keeps a cell of a thousand tufts in the opaque pass — one
 *      draw call, no sorting.
 *
 * (F3) THE TINT is the kind's own colour times 0.75 (the authored tuft's
 *      logic), because the texture is greyscale: #6a994e -> (0.4·0.75,
 *      0.6·0.75, 0.306·0.75) in linear-ish terms — asserted through three's
 *      own `Color` so the colour space of the comparison is three's, not ours.
 *
 * (F4) THE CHAIN IS ABSOLUTE. `applySway` first, `applyOcclusionFade` after
 *      it, both CHAINED into `onBeforeCompile` — so the combined program cache
 *      key of a material on a kind that blows at 0.06 m reads
 *      `ground-sway@0.06+occlusion-corridor`. An assignment by either would
 *      throw the other away and the key would be one of the two alone.
 *
 * (F5) THE RED COUNTER-CHECK: `alphaTest` drops out of the material. three
 *      then reports 0, i.e. every texel of the quad is drawn and the tuft is
 *      two solid boards — the picture (D9) describes from the texture side.
 *
 * ============================================================================
 * (G) THE FIELD, END TO END — cells appear, are binned, and disappear
 * ============================================================================
 * Built with a flat ground (`heightAt` = 0), one painted shape covering
 * everything at value 0.6 and no footprints.
 *
 * (G1) NOTHING IS BUILT BEFORE THERE IS AN ANCHOR: `setAreas` alone leaves the
 *      group empty. The window follows the play, and before the first tick
 *      there is no play to follow.
 *
 * (G2) THE ANCHOR BUILDS THE WANT SET: after `setAnchor(32, 32)` the group
 *      holds one mesh per cell of (A1) — 21 — and each of them has room for
 *      exactly the 983 instances of (C2), because the shape covers the whole
 *      cell.
 *
 * (G3) NOTHING IS DRAWN UNTIL IT IS BINNED: every mesh is `visible === false`
 *      with `count === 0` until the first `tick`. A buffer filled for one
 *      camera must not be shown at the count of another.
 *
 * (G4) WHAT THE TICK DRAWS, as an area integral. The layer is thinned from
 *      30 m and gone at 60 m, so the drawn instances of a camera standing on
 *      flat ground at the anchor are
 *        0.24/m2 · ∫₀^60 share(r) · 2πr dr
 *        = 0.24 · [ π·30² + 2π·(r² − r³/90) from 30 to 60 ]
 *        = 0.24 · [ 2827.43 + 2π·(1200 − 600) ]
 *        = 0.24 · [ 2827.43 + 3769.91 ] = 0.24 · 6597.34 = 1583
 *      to within a few per cent — the hash is a hash, not a quota. And EVERY
 *      drawn instance is within 60 m of the camera, which is the property the
 *      integral is only a consequence of.
 *
 * (G5) THE WINDOW MOVES WITH THE ANCHOR: `setAnchor(96, 32)` is one cell east
 *      and leaves 21 meshes standing, five of which are new (A3); the step to
 *      (63, 32) inside the same cell exchanges two of them (A3b) and leaves
 *      the other nineteen as the very same objects — not merely the same
 *      count, so a rebuild disguised as a no-op cannot pass.
 *
 * (G6) `dispose` empties the group.
 *
 * (G7) A BORDER DOES NOT THICKEN THE CARPET. Paint a second shape with no
 *      undergrowth of its own over the eastern half of the world and the wood
 *      keeps only its western half — about 983/2 ≈ 492 tufts per full cell,
 *      NOT 983 squeezed into half the ground.
 *
 *      That is what `triesPerPoint: 1` buys and why the cell case needs it.
 *      The shared sampler re-rolls a rejected candidate up to twelve times,
 *      because a RING fills only part of its bounding box and a shape sampled
 *      without re-rolls would come out thinner than its density. A CELL is its
 *      own bounding box, so nothing is ever rejected for missing the ring —
 *      and the rejections that are left (a building's footprint, ground
 *      painted over this shape) are exactly the ones that have to SUBTRACT.
 *      Asserted from both sides: the same cell sampled the sampler's default
 *      way tops itself back up to the full 983.
 */
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import * as THREE from 'three';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');
const LOD_SRC = join(ROOT, 'client3d/src/scene/scatterLod.ts');
const UG_SRC = join(ROOT, 'client3d/src/scene/undergrowth.ts');
const GROUND_SRC = join(ROOT, 'client3d/src/scene/ground.ts');

/** `scatterLod.ts` has no import at all (see its header), so a transpile is
 *  all it takes. */
async function loadLod() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'undergrowth-'));
  try {
    const source = await readFile(LOD_SRC, 'utf8');
    const out = esbuild.transformSync(source, { loader: 'ts', format: 'esm' });
    const file = join(dir, 'module.mjs');
    await writeFile(file, out.code, 'utf8');
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

/**
 * Bundle `undergrowth.ts` together with the wind patch it is handed and the
 * shared sampler it draws from, and import the lot. `external: ['three']`
 * keeps node's own three the only one in play, which is what lets sections
 * (F) and (G) inspect REAL materials and REAL instanced meshes.
 *
 * `mutate` rewrites the BUILT text before the import — that is how (B3), (D9)
 * and (F5) get a wrong module to compare against without a second copy of the
 * code lying around to rot.
 */
async function loadField(mutate) {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(ROOT, 'client3d/scripts/.smoke-ug-'));
  try {
    const entry = `export * from '${UG_SRC}';\n`
      + `export { applySway } from '${GROUND_SRC}';\n`
      + "export { scatterInstances, scatterSeed } from '@anima/scene-render';\n";
    const built = await esbuild.build({
      stdin: { contents: entry, resolveDir: dir, loader: 'ts' },
      bundle: true, platform: 'node', format: 'esm', write: false,
      outfile: join(dir, 'undergrowth.mjs'), external: ['three', 'three/*'],
    });
    const text = built.outputFiles[0].text;
    const source = mutate ? mutate(text) : text;
    const file = join(dir, 'undergrowth.mjs');
    await writeFile(file, source, 'utf8');
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

/** Section (B3)'s mutant: the seed forgets the CELL, so every cell of an area
 *  draws the same sequence of random numbers — one tuft pattern stamped out
 *  across the world every 64 m. */
function seedWithoutCell(text) {
  const anchor = /return `terrain:undergrowth:\$\{areaId\}:\$\{cx\},\$\{cz\}`;/;
  if (!anchor.test(text)) throw new Error('the cell seed is no longer where the probe looks');
  return text.replace(anchor, 'return `terrain:undergrowth:${areaId}`;');
}

/** Section (D9)'s mutant: every texel is opaque, so the blades stop being a
 *  silhouette and the alpha cut has nothing left to cut. */
function opaqueTexture(text) {
  const anchor = 'out[o + 3] = Math.round(255 * cov);';
  if (!text.includes(anchor)) throw new Error('the alpha write is no longer where the probe looks');
  return text.replace(anchor, 'out[o + 3] = 255;');
}

/** Section (F5)'s mutant: the material loses its alpha cut and draws every
 *  texel of both quads — two solid boards per tuft. */
function noAlphaTest(text) {
  const anchor = 'alphaTest: UNDERGROWTH_ALPHA_TEST,';
  if (!text.includes(anchor)) throw new Error('the alpha cut is no longer where the probe looks');
  return text.replace(anchor, '');
}

let failed = 0;
let passed = 0;
function check(label, actual, expected, eps = 1e-9) {
  const ok = compare(actual, expected, eps);
  if (ok) {
    passed += 1;
    console.log(`  ok   ${label}`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}`);
    console.log(`       expected ${JSON.stringify(expected)}`);
    console.log(`       actual   ${JSON.stringify(actual)}`);
  }
}

function checkNot(label, actual, forbidden, eps = 1e-9) {
  const same = compare(actual, forbidden, eps);
  if (!same) {
    passed += 1;
    console.log(`  ok   ${label}`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}`);
    console.log(`       must NOT equal ${JSON.stringify(forbidden)}`);
  }
}

function compare(a, b, eps) {
  if (Array.isArray(a) && Array.isArray(b)) {
    return a.length === b.length && a.every((v, i) => compare(v, b[i], eps));
  }
  if (typeof a === 'number' && typeof b === 'number') {
    return Number.isNaN(a) ? Number.isNaN(b) : Math.abs(a - b) <= eps;
  }
  if (a && b && typeof a === 'object' && typeof b === 'object') {
    const ka = Object.keys(a);
    const kb = Object.keys(b);
    return ka.length === kb.length && ka.every((k) => compare(a[k], b[k], eps));
  }
  return a === b;
}

/** The in-cell offsets of a sampled point list — what makes "these two cells
 *  are the same pattern" a measurement rather than an impression. */
function offsets(points, cx, cz, cellM) {
  return points.map((p) => [p.x - cx * cellM, p.z - cz * cellM]);
}

async function main() {
  const lod = await loadLod();
  const field = await loadField();
  const {
    UNDERGROWTH_CELL_M, UNDERGROWTH_CELL_RADIUS_M, UNDERGROWTH_CULL_M,
    UNDERGROWTH_DENSITY_PER_M2, UNDERGROWTH_FADE_M, UNDERGROWTH_H_MAX,
    UNDERGROWTH_H_MIN, UNDERGROWTH_MAX_PER_CELL, UNDERGROWTH_MIN_SHARE,
    SCATTER_MIN_SHARE, instanceShare, SCATTER_LOD_DEFAULTS,
    undergrowthCellCount, undergrowthDensityPer100m2, undergrowthHeight,
    undergrowthShare, undergrowthVisible,
  } = lod;
  const {
    createUndergrowthField, scatterInstances, scatterSeed,
    undergrowthCellKey, undergrowthCellSeed,
    undergrowthGeometry, undergrowthMaterial, undergrowthTexture,
    undergrowthTexturePixels, wantedUndergrowthCells, applySway,
    UNDERGROWTH_ALPHA_TEST, UNDERGROWTH_H_REF_M, UNDERGROWTH_TEX_SIZE,
    UNDERGROWTH_BLADES,
  } = field;
  const TAU = Math.PI * 2;

  console.log('(A) the cell raster — which cells the layer holds');
  check('A the raster is 64 m, the window 128 m',
    [UNDERGROWTH_CELL_M, UNDERGROWTH_CELL_RADIUS_M], [64, 128]);
  check('A the key is "cx,cz"', undergrowthCellKey(-2, 3), '-2,3');
  // A cell owns its LOWER edge (`Math.floor`), which a radius of 0 shows
  // directly: it answers with the anchor's own cell and nothing else.
  check('A a point is in the cell that starts at its own floor',
    [wantedUndergrowthCells(0, 0, 0), wantedUndergrowthCells(63.9, 64, 0),
      wantedUndergrowthCells(-0.1, -64, 0)],
    [['0,0'], ['0,1'], ['-1,-1']]);

  // (A1) the anchor in the middle of its cell
  const midCell = wantedUndergrowthCells(32, 32);
  check('A1 an anchor at a cell centre holds 21 cells — 25 less four corners',
    midCell.length, 21);
  check('A1 …and the nearest is its own', midCell[0], '0,0');
  check('A1 …the four corners are exactly the ones missing',
    ['-2,-2', '-2,2', '2,-2', '2,2'].filter((k) => midCell.includes(k)), []);
  check('A1 …while their neighbours along the axes are in',
    ['-2,-1', '-2,0', '2,1', '0,2'].every((k) => midCell.includes(k)), true);

  // (A2) the anchor on a corner — the asymmetric case
  const cornerCell = wantedUndergrowthCells(0, 0);
  check('A2 an anchor ON a cell corner holds 20', cornerCell.length, 20);
  check('A2 …and the tie between the four cells it touches goes by key',
    cornerCell[0], '-1,-1');
  check('A2 …the cell whose near edge is exactly 128 m away is still in',
    cornerCell.includes('2,0'), true);
  check('A2 …but its neighbour one row up is out',
    cornerCell.includes('2,1'), false);

  // (A3) the crossing
  const eastCell = wantedUndergrowthCells(96, 32);
  const dropped = midCell.filter((k) => !eastCell.includes(k));
  const added = eastCell.filter((k) => !midCell.includes(k));
  check('A3 one cell east is still 21 cells', eastCell.length, 21);
  check('A3 …five of them are new and five are gone',
    [dropped.length, added.length], [5, 5]);
  const nudged = wantedUndergrowthCells(63, 32);
  check('A3b a step INSIDE the cell still moves the window — it is the POINT '
    + 'the radius is measured from', nudged.length, 21);
  check('A3b …two out, two in',
    [midCell.filter((k) => !nudged.includes(k)).sort(),
      nudged.filter((k) => !midCell.includes(k)).sort()],
    [['-2,-1', '-2,1'], ['2,-2', '2,2']]);

  // (A4) junk
  for (const [x, z, name] of [[NaN, 0, 'a NaN anchor'],
    [0, Infinity, 'an infinite anchor']]) {
    check(`A4 ${name} holds no cells`, wantedUndergrowthCells(x, z), []);
  }
  check('A4 a negative radius holds no cells',
    wantedUndergrowthCells(32, 32, -1), []);
  check('A4 a radius of 0 is the anchor\'s own cell and nothing else',
    wantedUndergrowthCells(32, 32, 0), ['0,0']);

  console.log('\n(B) the seed — one per (area, cell)');
  check('B1 the seed names the area AND the cell',
    undergrowthCellSeed('ta_1', -2, 3), 'terrain:undergrowth:ta_1:-2,3');
  check('B1 …and is not the authored scatter\'s',
    undergrowthCellSeed('ta_1', 0, 0) !== scatterSeed('ta_1', 0), true);

  // (B2) the cell keeps neighbours apart — measured on the in-cell offsets
  const CELL = UNDERGROWTH_CELL_M;
  const cellRing = (cx, cz) => [
    [cx * CELL, cz * CELL], [(cx + 1) * CELL, cz * CELL],
    [(cx + 1) * CELL, (cz + 1) * CELL], [cx * CELL, (cz + 1) * CELL],
  ];
  const sampleCell = (cx, cz, seed) => scatterInstances({
    ring: cellRing(cx, cz),
    areaM2: CELL * CELL,
    densityPer100m2: undergrowthDensityPer100m2(0.6),
    seed,
    maxPoints: UNDERGROWTH_MAX_PER_CELL,
  });
  const cell00 = sampleCell(0, 0, undergrowthCellSeed('ta_1', 0, 0));
  const cell10 = sampleCell(1, 0, undergrowthCellSeed('ta_1', 1, 0));
  check('B2 the same cell asked twice is the same tufts',
    sampleCell(0, 0, undergrowthCellSeed('ta_1', 0, 0)).slice(0, 5),
    cell00.slice(0, 5));
  checkNot('B2 …while the cell next door is a different pattern',
    offsets(cell10, 1, 0, CELL).slice(0, 5),
    offsets(cell00, 0, 0, CELL).slice(0, 5));

  // (B3) the red counter-check
  const noCell = await loadField(seedWithoutCell);
  const stamped00 = sampleCell(0, 0, noCell.undergrowthCellSeed('ta_1', 0, 0));
  const stamped10 = sampleCell(1, 0, noCell.undergrowthCellSeed('ta_1', 1, 0));
  check('B3 the "seed without the cell" mutant stamps ONE pattern everywhere',
    offsets(stamped10, 1, 0, CELL).slice(0, 5),
    offsets(stamped00, 0, 0, CELL).slice(0, 5));
  check('B3 …which the real seed measurably is not',
    compare(offsets(cell10, 1, 0, CELL).slice(0, 5),
      offsets(cell00, 0, 0, CELL).slice(0, 5), 1e-9), false);

  console.log('\n(C) how many — the density, per cell');
  check('C1 the base density is 0.40 tufts per square metre',
    UNDERGROWTH_DENSITY_PER_M2, 0.40);
  check('C1 the share becomes 40 * value per 100 m2',
    [undergrowthDensityPer100m2(0.6), undergrowthDensityPer100m2(0.3),
      undergrowthDensityPer100m2(1)], [24, 12, 40]);
  check('C2 a full cell of the seeded forest carries 983 tufts',
    undergrowthCellCount(0.6), 983);
  check('C2 …of the seeded grass 492, at full value 1638',
    [undergrowthCellCount(0.3), undergrowthCellCount(1)], [492, 1638]);
  check('C2 …and the sampler really places 983 of them',
    cell00.length, 983);
  check('C3 the ceiling is 8000 per cell', UNDERGROWTH_MAX_PER_CELL, 8000);
  check('C3 …which full density does not come near',
    undergrowthCellCount(1) < UNDERGROWTH_MAX_PER_CELL, true);
  for (const [bad, name] of [[0, '0'], [-1, '-1'], [NaN, 'NaN'],
    ['thick', 'a string'], [null, 'null'], [undefined, 'undefined']]) {
    check(`C4 a value of ${name} grows nothing`,
      [undergrowthCellCount(bad), undergrowthDensityPer100m2(bad)], [0, 0]);
  }
  check('C4 a hand-edited 5 is clamped to full density, not multiplied',
    undergrowthCellCount(5), 1638);

  console.log('\n(D) the blade texture — a pure pixel function');
  const N = UNDERGROWTH_TEX_SIZE;
  const tex = undergrowthTexturePixels(N);
  const at = (r, c) => (r * N + c) * 4;
  check('D1 the texture is 64 x 64 and seven blades wide',
    [N, UNDERGROWTH_BLADES], [64, 7]);
  check('D1 …and comes back as RGBA bytes',
    [tex.length, tex instanceof Uint8ClampedArray], [64 * 64 * 4, true]);
  check('D2 a blade is opaque down its middle',
    [tex[at(0, 31) + 3], tex[at(0, 32) + 3]], [255, 255]);
  check('D3 …and there is nothing at all between two blades',
    tex[at(0, 36) + 3], 0);
  check('D4 the blade edge is antialiased, not a hard step',
    tex[at(0, 29) + 3], 214);
  const rowInk = (r) => {
    let sum = 0;
    for (let c = 0; c < N; c += 1) sum += tex[at(r, c) + 3] / 255;
    return sum;
  };
  check('D5 the foot row carries 39.85 texels of ink', rowInk(0), 39.8464, 0.15);
  check('D5 …and the row at 46.5 only 2.22 — the taper, measured',
    rowInk(46), 2.22, 0.05);
  let topInk = 0;
  for (let r = 58; r < N; r += 1) topInk += rowInk(r);
  check('D6 the top tenth of the texture is empty', topInk, 0);
  check('D7 the grey is the row\'s own, and greyscale',
    [tex[at(0, 0)], tex[at(0, 0) + 1], tex[at(0, 0) + 2], tex[at(63, 0)]],
    [179, 179, 179, 254]);
  let footInk = 0;
  for (let r = 0; r < 10; r += 1) footInk += rowInk(r);
  check('D8 the ten lowest rows carry exactly 356.24 texels of ink',
    footInk, 356.24, 0.5);
  let ink = 0;
  let clear = 0;
  for (let r = 0; r < N; r += 1) {
    for (let c = 0; c < N; c += 1) {
      const a = tex[at(r, c) + 3];
      ink += a / 255;
      if (a === 0) clear += 1;
    }
  }
  check('D8 the whole texture stays under the 903 texels the widths allow',
    ink < 903.2, true);
  check('D8 …so at least 2567 of its 4096 texels are pure hole',
    clear >= 2567, true);

  // (D9) the red counter-check
  const solid = await loadField(opaqueTexture);
  const solidTex = solid.undergrowthTexturePixels(N);
  let solidClear = 0;
  let solidInk = 0;
  for (let i = 3; i < solidTex.length; i += 4) {
    solidInk += solidTex[i] / 255;
    if (solidTex[i] === 0) solidClear += 1;
  }
  check('D9 the "always opaque" mutant is a solid square, not a tuft',
    [solidInk, solidClear], [64 * 64, 0]);
  check('D9 …which is measurably not what the real function draws',
    [ink < solidInk / 4, clear > 2567], [true, true]);

  console.log('\n(E) the LOD ladder — its own numbers, beside the props\'');
  check('E the layer is drawn to 60 m and thinned from 30 m',
    [UNDERGROWTH_FADE_M, UNDERGROWTH_CULL_M], [30, 60]);
  check('E …and it fades to NOTHING, where the props keep a quarter',
    [UNDERGROWTH_MIN_SHARE, SCATTER_MIN_SHARE], [0, 0.25]);
  check('E a tuft is knee-high, 0.4 .. 0.7 m',
    [UNDERGROWTH_H_MIN, UNDERGROWTH_H_MAX], [0.4, 0.7]);
  check('E1 yaw 0 is the shortest blade', undergrowthHeight(0), 0.4);
  check('E1 yaw pi is the middle — the geometry\'s own height',
    undergrowthHeight(Math.PI), 0.55);
  check('E1 yaw 1.5pi', undergrowthHeight(1.5 * Math.PI), 0.625);
  check('E1 a full turn is the same blade again', undergrowthHeight(TAU), 0.4);
  for (const [bad, name] of [[NaN, 'NaN'], ['x', 'a string'],
    [undefined, 'undefined']]) {
    check(`E1 a yaw of ${name} is the shortest blade, never a NaN scale`,
      undergrowthHeight(bad), 0.4);
  }
  check('E2 share at 0 m is 1', undergrowthShare(0), 1);
  check('E2 …at 30 m still 1', undergrowthShare(30), 1);
  check('E2 …at 37.5 m 0.75', undergrowthShare(37.5), 0.75);
  check('E2 …at 45 m half the carpet', undergrowthShare(45), 0.5);
  check('E2 …at 52.5 m a quarter', undergrowthShare(52.5), 0.25);
  check('E2 …and at 60 m nothing at all', undergrowthShare(60), 0);
  check('E2 past the cull distance nothing', undergrowthShare(60.001), 0);
  check('E2 a NaN distance draws nothing', undergrowthShare(NaN), 0);
  check('E2 at 45 m the props draw everything while the carpet is halved',
    [instanceShare(45, SCATTER_LOD_DEFAULTS), undergrowthShare(45)], [1, 0.5]);
  check('E2 …and at 60 m they are at 0.85 while it is gone',
    [instanceShare(60, SCATTER_LOD_DEFAULTS), undergrowthShare(60)], [0.85, 0]);
  const grown = (d, n = 1000) => {
    const out = [];
    for (let i = 0; i < n; i += 1) if (undergrowthVisible(i, d)) out.push(i);
    return out;
  };
  check('E3 inside 30 m every tuft is drawn', grown(30).length, 1000);
  check('E3 at the cull distance none is — nothing can pop there',
    grown(60).length, 0);
  check('E3 the set at 45 m is the SAME set when asked again',
    grown(45), grown(45));
  const near375 = new Set(grown(37.5));
  check('E3 what is drawn at 52.5 m is still drawn at 37.5 m',
    grown(52.5).filter((i) => !near375.has(i)).length, 0);
  for (const [d, share] of [[37.5, 0.75], [45, 0.5], [52.5, 0.25]]) {
    const n = grown(d).length;
    check(`E3 ${d} m draws ${1000 * share} of 1000, within 5 % (got ${n})`,
      Math.abs(n - 1000 * share) <= 0.05 * 1000 * share, true);
  }
  check('E3 tuft 0 survives as long as anything of the layer does',
    [undergrowthVisible(0, 59.9), undergrowthVisible(0, 60)], [true, false]);

  console.log('\n(F) the look — crossed quads with an alpha cut');
  check('F the geometry stands at the middle of the height span',
    UNDERGROWTH_H_REF_M, 0.55);
  const geo = undergrowthGeometry(UNDERGROWTH_H_REF_M);
  const gp = geo.getAttribute('position');
  check('F1 two quads: eight vertices, twelve indices',
    [gp.count, geo.getIndex().count], [8, 12]);
  check('F1 quad A spans +-0.275 m at z = 0',
    [gp.getX(0), gp.getY(0), gp.getZ(0), gp.getX(1)],
    [-0.275, 0, 0, 0.275], 1e-6);
  check('F1 …and quad B is it turned by 80 degrees, not 90',
    [gp.getX(4), gp.getY(4), gp.getZ(4)],
    [-0.0477533, 0, 0.2708221], 1e-6);
  geo.computeBoundingBox();
  check('F1 the tuft STANDS on the ground (B16): y runs 0 .. 0.55',
    [geo.boundingBox.min.y, geo.boundingBox.max.y], [0, 0.55], 1e-6);

  const dataTex = undergrowthTexture();
  check('F the one shared texture is a 64 x 64 DataTexture',
    [dataTex.image.width, dataTex.image.height], [64, 64]);
  const mat = undergrowthMaterial(dataTex, '#6a994e', 0.06, applySway);
  check('F2 the material CUTS its alpha at 0.35',
    [mat.alphaTest, UNDERGROWTH_ALPHA_TEST], [0.35, 0.35]);
  check('F2 …and is NOT transparent — it stays in the opaque pass',
    mat.transparent, false);
  check('F2 …and both faces of a quad are drawn',
    mat.side, THREE.DoubleSide);
  check('F2 …through the blade texture', mat.map === dataTex, true);
  const want = new THREE.Color('#6a994e').multiplyScalar(0.75);
  check('F3 the tint is the kind\'s colour times 0.75',
    [mat.color.r, mat.color.g, mat.color.b], [want.r, want.g, want.b], 1e-9);
  check('F4 wind and camera corridor are BOTH on it, in that order',
    mat.customProgramCacheKey(), 'ground-sway@0.06+occlusion-corridor');

  // (F5) the red counter-check
  const cut = await loadField(noAlphaTest);
  const cutMat = cut.undergrowthMaterial(cut.undergrowthTexture(), '#6a994e',
                                         0.06, cut.applySway);
  check('F5 the "no alpha cut" mutant draws every texel of both quads',
    cutMat.alphaTest, 0);
  checkNot('F5 …which the real material does not', mat.alphaTest, 0);

  console.log('\n(G) the field, end to end');
  const BIG = 2000;
  const area = {
    id: 'ta_wood',
    kind: 'forest',
    ring: [[-BIG, -BIG], [BIG, -BIG], [BIG, BIG], [-BIG, BIG]],
    bounds: [-BIG, -BIG, BIG, BIG],
    value: 0.6,
    color: '#6a994e',
    swayM: 0.06,
  };
  const grown3d = createUndergrowthField({ heightAt: () => 0, applySway });
  grown3d.setAreas([area], []);
  check('G1 nothing is built before there is an anchor',
    grown3d.group.children.length, 0);
  grown3d.setAnchor(32, 32);
  check('G2 the anchor builds one mesh per wanted cell',
    grown3d.group.children.length, midCell.length);
  check('G2 …each with room for the cell\'s own 983 tufts',
    grown3d.group.children.map((m) => m.instanceMatrix.count),
    midCell.map(() => 983));
  check('G3 and nothing is DRAWN until the first tick',
    grown3d.group.children.some((m) => m.visible || m.count > 0), false);
  check('G3 …nor does any of it cast a shadow',
    grown3d.group.children.every((m) => m.castShadow === false), true);

  const cam = new THREE.Vector3(32, 0, 32);
  grown3d.tick(cam);
  let drawn = 0;
  let farthest = 0;
  const m4 = new THREE.Matrix4();
  const at3 = new THREE.Vector3();
  for (const mesh of grown3d.group.children) {
    drawn += mesh.count;
    for (let i = 0; i < mesh.count; i += 1) {
      m4.fromArray(mesh.instanceMatrix.array, i * 16);
      at3.setFromMatrixPosition(m4);
      const d = at3.distanceTo(cam);
      if (d > farthest) farthest = d;
    }
  }
  check('G4 the tick draws the 1583 tufts the thinning integral asks for',
    Math.abs(drawn - 1583) <= 0.08 * 1583, true);
  check(`G4 …and not one of them past the cull distance (${farthest.toFixed(1)} m)`,
    farthest <= UNDERGROWTH_CULL_M, true);

  const before = grown3d.group.children.slice();
  grown3d.setAnchor(63, 32);
  const nudgedMeshes = grown3d.group.children.slice();
  check('G5 a step inside the cell exchanges the two cells of (A3b)…',
    [nudgedMeshes.length,
      before.filter((m) => !nudgedMeshes.includes(m)).length],
    [21, 2]);
  check('G5 …and leaves the other nineteen as the very same meshes',
    before.filter((m) => nudgedMeshes.includes(m)).length, 19);
  grown3d.setAnchor(96, 32);
  check('G5 a border crossing moves the window, and it stays 21 cells',
    grown3d.group.children.length, eastCell.length);
  check('G5 …five of the meshes standing at the cell centre really went',
    before.filter((m) => !grown3d.group.children.includes(m)).length, 5);
  grown3d.dispose();
  check('G6 dispose empties the group', grown3d.group.children.length, 0);

  // (G7) the border, and the re-roll that must not happen there
  const path = {
    id: 'ta_path',
    kind: 'path',
    ring: [[0, -BIG], [BIG, -BIG], [BIG, BIG], [0, BIG]],
    bounds: [0, -BIG, BIG, BIG],
    value: 0,
    color: '#a0a0a0',
    swayM: 0,
  };
  const halved = createUndergrowthField({ heightAt: () => 0, applySway });
  halved.setAreas([area, path], []);
  halved.setAnchor(-32, 32);
  // The anchor's own cell (-1, 0) runs x −64 … 0, so it lies wholly west of
  // the path and keeps everything — and it is built FIRST, the want set being
  // nearest-first.
  check('G7 a cell wholly west of the border still carries its 983',
    halved.group.children[0].instanceMatrix.count, 983);
  // The want set at (−32, 32) is (A1) shifted one column west, so the columns
  // east of the border (cx = 0 and 1) grow nothing at all: 21 cells less
  // cx = 0 (five rows) and cx = 1 (three, being a |cx| = 2 column) -> 13.
  check('G7 …and the thirteen cells west of it are the only ones with a layer',
    halved.group.children.length, 13);
  const straddling = scatterInstances({
    ring: cellRing(-1, 0),
    areaM2: CELL * CELL,
    densityPer100m2: undergrowthDensityPer100m2(0.6),
    seed: undergrowthCellSeed('ta_wood', -1, 0),
    occluders: [[[-32, -BIG], [BIG, -BIG], [BIG, BIG], [-32, BIG]]],
    maxPoints: UNDERGROWTH_MAX_PER_CELL,
    triesPerPoint: 1,
  });
  check('G7 half the cell covered keeps about half the tufts, not all of them',
    Math.abs(straddling.length - 492) <= 0.1 * 492, true);
  const topped = scatterInstances({
    ring: cellRing(-1, 0),
    areaM2: CELL * CELL,
    densityPer100m2: undergrowthDensityPer100m2(0.6),
    seed: undergrowthCellSeed('ta_wood', -1, 0),
    occluders: [[[-32, -BIG], [BIG, -BIG], [BIG, BIG], [-32, BIG]]],
    maxPoints: UNDERGROWTH_MAX_PER_CELL,
  });
  check('G7 …while the sampler\'s DEFAULT re-roll tops it back up to 983 — '
    + 'double density against the border', topped.length, 983);
  halved.dispose();

  console.log('\n(H) the wiring, pinned by reading the source');
  const ugSrc = await readFile(UG_SRC, 'utf8');
  const groundSrc = await readFile(GROUND_SRC, 'utf8');
  check('H the layer samples every cell under its own (area, cell) seed',
    ugSrc.includes('seed: undergrowthCellSeed(area.id, cx, cz),'), true);
  check('H …and hands the sampler its own per-cell ceiling',
    ugSrc.includes('maxPoints: UNDERGROWTH_MAX_PER_CELL,'), true);
  check('H the chain is wind first, camera corridor after it',
    /applySway\(mat, swayM, UNDERGROWTH_H_REF_M\);\s*applyOcclusionFade\(mat\);/
      .test(ugSrc), true);
  check('H ground.ts no longer builds the layer itself',
    /buildUndergrowth|UNDERGROWTH_MAX_PER_AREA/.test(groundSrc), false);
  check('H …it hands over the shapes on every rebuild',
    groundSrc.includes('undergrowth.setAreas(undergrowthAreas, footprints);'),
    true);
  check('H …the height tiles\' own anchor',
    groundSrc.includes('undergrowth.setAnchor(x, z);'), true);
  check('H …and the LOD beat',
    groundSrc.includes('undergrowth.tick(cameraPos);'), true);
  // The authored tuft cones are untouched by this round, and the one place
  // that still patches a material of its own in ground.ts is theirs.
  const fadeCalls = groundSrc.match(/applyOcclusionFade\(mat\);/g);
  check('H the authored tuft keeps its own patched material, and only it',
    fadeCalls ? fadeCalls.length : 0, 1);
  const seedCalls = groundSrc.match(/scatterSeed\(/g);
  check('H …and scatterSeed is still used exactly once, for the authored rows',
    seedCalls ? seedCalls.length : 0, 1);

  console.log(`\n${passed} ok, ${failed} failed`);
  process.exit(failed ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
