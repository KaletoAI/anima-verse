#!/usr/bin/env node
/**
 * Derivation moved to native/tests/Derivations/height_tiles.md (E1, 2026-11-25).
 * Usage:  node client3d/scripts/smoke_height_tiles.mjs
 * Runs until E3 deletes the browser scene; the C# vector tests keep executing the cases.
 */
import { vectorCase, vectorArgs, vectorValue } from './e3VectorSupport.mjs';
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

function vector(label, fns) {
  const result = vectorCase("height_tiles", label, fns);
  passed += result.passed; failed += result.failed;
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
vector("[1] height_tiles: tiles within 560 m of (0, 0)", { wantedTilesValue: (args, path) => vectorValue(wantedTiles(...vectorArgs(args)), path) });
check('the four tiles touching the anchor come first',
  atOrigin.slice(0, 4).join(' '), '-1,-1 -1,0 0,-1 0,0');
check('the tile due east across one seam is in', atOrigin.includes('2,0'), true);
check('the diagonal at (256, 512) is out', atOrigin.includes('1,2'), false);
check('...and so is the far diagonal', atOrigin.includes('2,2'), false);
check('the last one out is a rim tile', atOrigin[atOrigin.length - 1], '2,0');

console.log('[2] RED COUNTER-PROBE: one tile less radius loses the rim');
const tooSmall = wantedTiles(FULL, TILE_M, 0, 0, 500);
vector("[2] height_tiles: at 500 m the rim columns fall out", { wantedTilesValue: (args, path) => vectorValue(wantedTiles(...vectorArgs(args)), path) });
check('...and "2,0" with them', tooSmall.includes('2,0'), false);
check('the ring that is lost', atOrigin.length - tooSmall.length, 8);

console.log('[3] crossing a tile border changes the set');
const eastward = wantedTiles(FULL, TILE_M, 300, 0, 560);
vector("[3] height_tiles: tiles within 560 m of (300, 0)", { wantedTilesValue: (args, path) => vectorValue(wantedTiles(...vectorArgs(args)), path) });
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
vector("[4] height_tiles: an index that knows nothing here", { wantedTilesValue: (args, path) => vectorValue(wantedTiles(...vectorArgs(args)), path) });

console.log('[5] batches of 64, nearest first');
const many = [];
for (let i = 0; i < 130; i += 1) many.push(`k${i}`);
const batches = tileBatches(many);
vector("[5] height_tiles: 130 keys are three requests", { tileBatchesValue: (args, path) => vectorValue(tileBatches(...vectorArgs(args)), path) });
vector("[5] height_tiles: the first is full", { tileBatchesValue: (args, path) => vectorValue(tileBatches(...vectorArgs(args)), path) });
vector("[5] height_tiles: the second too", { tileBatchesValue: (args, path) => vectorValue(tileBatches(...vectorArgs(args)), path) });
vector("[5] height_tiles: the tail is the rest", { tileBatchesValue: (args, path) => vectorValue(tileBatches(...vectorArgs(args)), path) });
vector("[5] height_tiles: and the order survives", { tileBatchesValue: (args, path) => vectorValue(tileBatches(...vectorArgs(args)), path) });
vector("[5] height_tiles: ...through the split", { tileBatchesValue: (args, path) => vectorValue(tileBatches(...vectorArgs(args)), path) });
check('one batch is enough for a full want set',
  tileBatches(atOrigin).length, 1);
vector("[5] height_tiles: nothing wanted is no request", { tileBatchesValue: (args, path) => vectorValue(tileBatches(...vectorArgs(args)), path) });
vector("[5] height_tiles: a nonsense batch size still terminates", { tileBatchesValue: (args, path) => vectorValue(tileBatches(...vectorArgs(args)), path) });

console.log('[6] degenerate inputs answer with nothing');
vector("[6] height_tiles: no tile size", { wantedTilesValue: (args, path) => vectorValue(wantedTiles(...vectorArgs(args)), path) });
vector("[6] height_tiles: a negative tile size", { wantedTilesValue: (args, path) => vectorValue(wantedTiles(...vectorArgs(args)), path) });
vector("[6] height_tiles: an empty index", { wantedTilesValue: (args, path) => vectorValue(wantedTiles(...vectorArgs(args)), path) });
check('a NaN anchor', wantedTiles(FULL, TILE_M, NaN, 0, 560).length, 0);
check('an infinite radius', wantedTiles(FULL, TILE_M, 0, 0, Infinity).length, 0);
check('radius 0 is the anchor\'s own tile and nothing else',
  wantedTiles(FULL, TILE_M, 300, 300, 0).join(' '), '1,1');

console.log(`\n${passed + failed} checks, ${failed} failures`);
process.exit(failed ? 1 : 0);
