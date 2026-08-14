#!/usr/bin/env node
/**
 * Smoke check for the height-tile LOADING POLICY —
 * `client3d/src/scene/heightTiles.ts` (§ A16.3).
 *
 * Usage:  node client3d/scripts/smoke_height_tiles.mjs
 *
 * Every number below is counted BY HAND from the tile raster, never recorded
 * from the current output. The question the file answers is "which indexed
 * tiles lie within 560 m of the anchor", and a want set that quietly loses the
 * rim of the radius is a ring of flat ground around the player that only shows
 * up as a step where the fine raster ends.
 *
 * ============================================================================
 * THE RASTER: tiles of 256 m, keys `"tx,tz"`, tile (tx, tz) covering
 * [tx·256, (tx+1)·256] × [tz·256, (tz+1)·256]. The test is box-to-point:
 * `dx` = how far the anchor is from the tile's x range (0 while inside it),
 * `dz` likewise, and the tile counts when dx² + dz² ≤ radius².
 * ============================================================================
 *
 * [1] THE ANCHOR AT THE ORIGIN, radius 560 (560² = 313 600)
 *
 *     Candidate columns for x = 0: tx runs floor(−560/256) = −3 … floor(560/256)
 *     = 2, and their distances are
 *         tx = −3 -> [−768, −512] -> dx = 512      512² = 262 144
 *         tx = −2 -> [−512, −256] -> dx = 256      256² =  65 536
 *         tx = −1 -> [−256,    0] -> dx =   0
 *         tx =  0 -> [   0,  256] -> dx =   0
 *         tx =  1 -> [ 256,  512] -> dx = 256
 *         tx =  2 -> [ 512,  768] -> dx = 512
 *     and the same six for z. Which pairs fit under 313 600:
 *         (0, 0)      0                  yes   2 × 2 = 4 tiles
 *         (0, 256)    65 536             yes   2 × 2 = 4   (and mirrored: 4)
 *         (256, 256)  131 072            yes   2 × 2 = 4
 *         (0, 512)    262 144            yes   2 × 2 = 4   (and mirrored: 4)
 *         (256, 512)  327 680            NO
 *         (512, 512)  524 288            NO
 *     -> 4 + 4 + 4 + 4 + 4 + 4 = 24 tiles.
 *
 *     NEAREST FIRST, ties by key: the four tiles the anchor stands in or on
 *     touch it (d = 0) and come first, in key order
 *     "-1,-1", "-1,0", "0,-1", "0,0"; the last one out is a d² = 262 144 tile.
 *
 * [2] RED COUNTER-PROBE — THE RIM IS THE PART THAT MATTERS. At radius 500
 *     (250 000) the 512-columns fall out: 262 144 > 250 000. That drops the
 *     (512, 0) group and the (0, 512) one, 8 tiles, leaving 16 — and "2,0",
 *     the tile due east across the last seam, is gone with them. A radius
 *     picked one tile too small looks exactly like this: everything near the
 *     player is fine and the world ends 500 m out, inside the fog's 520 m.
 *
 * [3] CROSSING A TILE BORDER CHANGES THE SET. The anchor at (300, 0) stands in
 *     tile (1, 0), one border east of the origin. Its columns:
 *         tx = −2 -> [−512, −256] -> dx = 556      309 136
 *         tx = −1 -> [−256,    0] -> dx = 300       90 000
 *         tx =  0 -> [   0,  256] -> dx =  44        1 936
 *         tx =  1 -> [ 256,  512] -> dx =   0
 *         tx =  2 -> [ 512,  768] -> dx = 212       44 944
 *         tx =  3 -> [ 768, 1024] -> dx = 468      219 024
 *     against the rows dz ∈ {512, 256, 0, 0, 256, 512} of z = 0 (tz = −3 … 2).
 *     Per column, how many of the six rows fit under 313 600:
 *         tx = −2: dz = 0 only            -> 2
 *         tx = −1: dz = 0, 256            -> 4      (90 000 + 262 144 > cap)
 *         tx =  0: all three              -> 6
 *         tx =  1: all three              -> 6
 *         tx =  2: all three              -> 6      (44 944 + 262 144 = 307 088)
 *         tx =  3: dz = 0, 256            -> 4      (219 024 + 262 144 > cap)
 *     -> 28 tiles, "3,0" now in and "-3,0" now out. THAT is why a border
 *     crossing has to recompute: the far half of the set is a different half.
 *
 * [4] THE INDEX CUTS THE SET. The want set is intersected with the tiles the
 *     world says it has a ground in, so an index of two keys can never produce
 *     more than those two — and never a request for a tile the server would
 *     answer with nothing.
 *
 * [5] BATCHES OF 64, in order. 130 keys are 64 + 64 + 2, and the first batch
 *     holds the nearest tiles because `wantedTiles` sorted them that way.
 *
 * [6] DEGENERATE INPUTS answer with nothing rather than with a guess: no tile
 *     size, an empty index, a non-finite anchor. Radius 0 is not degenerate —
 *     it is the anchor's own tile, and nothing else.
 */
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');

/**
 * Bundle the module under test into ONE file inside the repo and import it.
 * Inside on purpose: `heightTiles.ts` imports `tileKeyAt` from
 * `@anima/scene-render` (there is ONE key mapping and this file does not own
 * it), which resolves through the workspace's `node_modules` — and the package
 * takes `three` as a parameter everywhere, so nothing of it survives into the
 * bundle.
 */
async function loadHeightTiles() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(ROOT, 'client3d/scripts/.smoke-'));
  try {
    const entry = "export { wantedTiles, tileBatches, HEIGHT_TILE_RADIUS_M,"
      + " HEIGHT_TILE_BATCH_MAX, HEIGHT_TILE_CACHE_MAX }"
      + ` from '${join(ROOT, 'client3d/src/scene/heightTiles')}';`;
    const built = await esbuild.build({
      stdin: { contents: entry, resolveDir: dir, loader: 'ts' },
      bundle: true, platform: 'node', format: 'esm', write: false,
      outfile: join(dir, 'heightTiles.mjs'), external: ['three', 'three/*'],
    });
    const file = join(dir, 'heightTiles.mjs');
    await writeFile(file, built.outputFiles[0].text, 'utf8');
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

let failed = 0;
let passed = 0;
function check(label, actual, expected) {
  const ok = actual === expected;
  if (ok) {
    passed += 1;
    console.log(`  ok   ${label} = ${actual}`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}\n       expected ${expected}\n       actual   ${actual}`);
  }
}

const {
  wantedTiles, tileBatches, HEIGHT_TILE_RADIUS_M, HEIGHT_TILE_BATCH_MAX,
  HEIGHT_TILE_CACHE_MAX,
} = await loadHeightTiles();

const TILE_M = 256;
/** Everything from tile (−8, −8) to (8, 8) exists — a world with ground
 *  everywhere, so only the radius decides. */
const FULL = new Set();
for (let tz = -8; tz <= 8; tz += 1) {
  for (let tx = -8; tx <= 8; tx += 1) FULL.add(`${tx},${tz}`);
}

console.log('[0] the constants the policy is written in');
check('the load radius clears the fog end of 520 m', HEIGHT_TILE_RADIUS_M, 560);
check('the batch cap is the server\'s', HEIGHT_TILE_BATCH_MAX, 64);
check('the LRU cap', HEIGHT_TILE_CACHE_MAX, 96);

console.log('[1] the anchor at the origin — 24 tiles, counted by hand');
const atOrigin = wantedTiles(FULL, TILE_M, 0, 0, 560);
check('tiles within 560 m of (0, 0)', atOrigin.length, 24);
check('the four tiles touching the anchor come first',
  atOrigin.slice(0, 4).join(' '), '-1,-1 -1,0 0,-1 0,0');
check('the tile due east across one seam is in', atOrigin.includes('2,0'), true);
check('the diagonal at (256, 512) is out', atOrigin.includes('1,2'), false);
check('...and so is the far diagonal', atOrigin.includes('2,2'), false);
check('the last one out is a rim tile', atOrigin[atOrigin.length - 1], '2,0');

console.log('[2] RED COUNTER-PROBE: one tile less radius loses the rim');
const tooSmall = wantedTiles(FULL, TILE_M, 0, 0, 500);
check('at 500 m the rim columns fall out', tooSmall.length, 16);
check('...and "2,0" with them', tooSmall.includes('2,0'), false);
check('the ring that is lost', atOrigin.length - tooSmall.length, 8);

console.log('[3] crossing a tile border changes the set');
const eastward = wantedTiles(FULL, TILE_M, 300, 0, 560);
check('tiles within 560 m of (300, 0)', eastward.length, 28);
check('a tile appears in the east', eastward.includes('3,0'), true);
check('...and one drops off in the west', eastward.includes('-3,0'), false);
check('the west tile WAS in the origin set', atOrigin.includes('-3,0'), true);
check('the two tiles the anchor now touches come first',
  eastward.slice(0, 2).join(' '), '1,-1 1,0');
check('the same anchor answers the same set twice',
  wantedTiles(FULL, TILE_M, 300, 0, 560).join(' ') === eastward.join(' '), true);

console.log('[4] the index cuts the set');
const SPARSE = new Set(['0,0', '5,5']);
check('only what the world has a ground in',
  wantedTiles(SPARSE, TILE_M, 0, 0, 560).join(' '), '0,0');
check('an index that knows nothing here', wantedTiles(
  new Set(['9,9']), TILE_M, 0, 0, 560).length, 0);

console.log('[5] batches of 64, nearest first');
const many = [];
for (let i = 0; i < 130; i += 1) many.push(`k${i}`);
const batches = tileBatches(many);
check('130 keys are three requests', batches.length, 3);
check('the first is full', batches[0].length, 64);
check('the second too', batches[1].length, 64);
check('the tail is the rest', batches[2].length, 2);
check('and the order survives', batches[0][0], 'k0');
check('...through the split', batches[2][1], 'k129');
check('one batch is enough for a full want set',
  tileBatches(atOrigin).length, 1);
check('nothing wanted is no request', tileBatches([]).length, 0);
check('a nonsense batch size still terminates', tileBatches(['a', 'b'], 0).length, 2);

console.log('[6] degenerate inputs answer with nothing');
check('no tile size', wantedTiles(FULL, 0, 0, 0, 560).length, 0);
check('a negative tile size', wantedTiles(FULL, -256, 0, 0, 560).length, 0);
check('an empty index', wantedTiles(new Set(), TILE_M, 0, 0, 560).length, 0);
check('a NaN anchor', wantedTiles(FULL, TILE_M, NaN, 0, 560).length, 0);
check('an infinite radius', wantedTiles(FULL, TILE_M, 0, 0, Infinity).length, 0);
check('radius 0 is the anchor\'s own tile and nothing else',
  wantedTiles(FULL, TILE_M, 300, 300, 0).join(' '), '1,1');

console.log(`\n${passed + failed} checks, ${failed} failures`);
process.exit(failed ? 1 : 0);
