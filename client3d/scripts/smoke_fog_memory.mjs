#!/usr/bin/env node
/**
 * Smoke check for the VEIL'S MEMORY — the client half of the Fog-Gedächtnis
 * (2026-08-16, finding B14 option 2). Pure set-and-rectangle maths out of
 * `client3d/src/game/fog.ts`: which quads survive once the cells the avatar has
 * already stood in are spared, on top of the known footprints.
 *
 * Usage:  node client3d/scripts/smoke_fog_memory.mjs
 *
 * Its own file rather than another section of `smoke_walk_math.mjs`: that one
 * is about where a FIGURE may go, this one about what the OVERVIEW covers, and
 * the memory has a server twin (`scripts/smoke_exploration.py`) whose cases
 * these mirror one for one.
 *
 * Same discipline as the neighbours: every expected number below is derived BY
 * HAND in this header and never recorded from the current output.
 *
 * ============================================================================
 * THE ONE NUMBER
 * ============================================================================
 * `EXPLORED_CELL_M` is 64 m and MUST equal `FOG_TILE_M` — that identity is what
 * lets a spared cell REPLACE a tile instead of having to be cut out of one. The
 * server says the same number in `app/core/exploration.EXPLORED_CELL_M`; if the
 * two ever drift, section (A) here fails and so does `[0]` over there.
 *
 * `exploredCellOf` is a FLOOR division, so the raster is continuous across the
 * origin: −0.1 m is cell −1, not cell 0.
 *
 * ============================================================================
 * THE WORLD ALL THE RECTANGLE CASES USE
 * ============================================================================
 * bounds 0…128 on both axes, margin 0, no footprints, no height query — so the
 * sweep produces ONE band (z 0…128) with ONE run (x 0…128), 128 × 128 m, and
 * the relief tiling (no query = tile unconditionally) cuts it into
 * ceil(128/64) = 2 × 2 = FOUR 64 m quads at (0,0), (0,64), (64,0), (64,64).
 * That is the baseline every case below is measured against.
 *
 * (B) ONE CELL REMEMBERED, `{"0,0"}`. The run spans cells cx 0…1 and cz 0…1
 *     (its far edge 128 is asked at 128 − ε, which is still cell 1), and one of
 *     those four is explored — so the run is cut on the cell raster and the
 *     explored cell produces nothing:
 *        (0,1) -> x 0,  z 64, 64 × 64
 *        (1,0) -> x 64, z 0,  64 × 64
 *        (1,1) -> x 64, z 64, 64 × 64
 *     THREE quads, in cx-major then cz order.
 *
 * (C) RED COUNTER-CHECK — a cell that is not under the run changes nothing.
 *     `{"5,5"}` covers 320…384 m, far outside the world: the run touches no
 *     explored cell, so it never reaches the raster cut and the FOUR baseline
 *     quads stand. Without this case (B) would also pass for an implementation
 *     that dropped quads at random. The empty set is the same statement and is
 *     checked beside it.
 *
 * (D) A CLIPPED CELL. bounds 0…96 × 0…64: the run is 96 × 64, spanning cells
 *     cx 0…1 (96 − ε is cell 1) and cz 0…0. With `{"0,0"}` spared, only (1,0)
 *     is left, and it is CLIPPED to the run: x 64…96, z 0…64 -> ONE quad
 *     64/0/32 × 64. A quad of a full 64 m width here would mean the veil
 *     reaches 32 m past the world frame.
 *
 * (E) THE NEGATIVE SIDE. bounds −128…0 × −64…0: cells cx −2…−1 (0 − ε is cell
 *     −1) and cz −1…−1. With `{"-1,-1"}` spared, only (−2,−1) is left:
 *     x −128…−64, z −64…0 -> ONE quad −128/−64/64 × 64. This is the case a
 *     truncating cell index would get wrong.
 *
 * (F) THE MEMORY BEATS THE FLAT-GROUND SHORTCUT. With a height query that
 *     answers 0 (level ground) the baseline run is NOT tiled at all — it stays
 *     ONE 128 × 128 quad. Add `{"0,0"}` and it must still be cut into the three
 *     quads of (B): ground one has walked is spared however flat it is.
 *
 * (G) RED COUNTER-CHECK for (F) — level ground with the memory somewhere ELSE
 *     (`{"5,5"}`) keeps its single 128 × 128 quad. That is the quad census the
 *     flat case exists for (module header: 744 instead of 3659 at n = 100), and
 *     it must survive the memory being switched on.
 *
 * (H) FOOTPRINT AND MEMORY TOGETHER. bounds 0…192 × 0…64 with one location at
 *     (96, 32), edge 64, yaw 0 — its box is x 64…128, z 0…64 and spans the only
 *     band, leaving two runs: x 0…64 and x 128…192, each 64 × 64 and therefore
 *     one quad each. Sparing `{"0,0"}` removes the FIRST run entirely (its only
 *     cell is that one) and leaves the second untouched (cell (2,0)):
 *     ONE quad 128/0/64 × 64.
 */
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

// '../..' = the REPO root (this file lives in client3d/scripts/) — the same
// anchor smoke_walk_math.mjs uses.
const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');
const SRC_DIR = join(ROOT, 'client3d/src/game');

/**
 * `fog.ts` is TypeScript and imports nothing at all (that is the point of the
 * "PURE" in its header), so a plain esbuild transpile is enough — no bundler,
 * no `three`, no DOM. The loader of `smoke_walk_math.mjs`, cut down to the one
 * module this file is about.
 */
async function loadFog() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'fogmemory-'));
  try {
    const source = await readFile(join(SRC_DIR, 'fog.ts'), 'utf8');
    const out = esbuild.transformSync(source, { loader: 'ts', format: 'esm' });
    await writeFile(join(dir, 'fog.mjs'), out.code, 'utf8');
    return await import(`file://${join(dir, 'fog.mjs')}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

let failed = 0;
let passed = 0;
function check(label, actual, expected) {
  const a = JSON.stringify(actual);
  const e = JSON.stringify(expected);
  if (a === e) {
    passed += 1;
    console.log(`  ok   ${label}`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}\n       expected ${e}\n       actual   ${a}`);
  }
}

/** A rectangle list in a form one can read in a failure message. */
const shape = (rects) => rects.map((r) => `${r.x}/${r.z} ${r.w}x${r.d}`);

async function main() {
  const fog = await loadFog();
  const { EXPLORED_CELL_M, FOG_TILE_M, exploredCellKey, exploredCellOf,
          fogRects } = fog;

  console.log('\n(A) the one number, and the identity it rests on');
  check('EXPLORED_CELL_M', EXPLORED_CELL_M, 64);
  check('…is the veil tile (a spared cell REPLACES a tile)',
    EXPLORED_CELL_M === FOG_TILE_M, true);
  check('cell of 0 m', exploredCellOf(0), 0);
  check('cell of 63.9 m', exploredCellOf(63.9), 0);
  check('cell of 64 m (the border belongs to the cell after it)',
    exploredCellOf(64), 1);
  check('cell of 100 m', exploredCellOf(100), 1);
  check('cell of −0.1 m (floor, not truncation)', exploredCellOf(-0.1), -1);
  check('cell of −64 m', exploredCellOf(-64), -1);
  check('cell of −65 m', exploredCellOf(-65), -2);
  check('key form', exploredCellKey(1, -2), '1,-2');

  const WORLD = { min_x: 0, min_z: 0, max_x: 128, max_z: 128 };
  const FLAT = () => 0;   // a level world: the run is not tiled

  console.log('\n(A2) the baseline — four 64 m quads, no memory in play');
  const base = fogRects(WORLD, [], 0);
  check('four quads', shape(base),
    ['0/0 64x64', '0/64 64x64', '64/0 64x64', '64/64 64x64']);

  console.log('\n(B) one cell remembered — three quads left');
  check('quads', shape(fogRects(WORLD, [], 0, undefined, new Set(['0,0']))),
    ['0/64 64x64', '64/0 64x64', '64/64 64x64']);

  console.log('\n(C) RED — a cell nowhere near the run leaves every quad');
  check('memory at (5,5)',
    shape(fogRects(WORLD, [], 0, undefined, new Set(['5,5']))), shape(base));
  check('an empty memory', shape(fogRects(WORLD, [], 0, undefined, new Set())),
    shape(base));
  check('no memory argument at all', shape(fogRects(WORLD, [], 0)),
    shape(base));

  console.log('\n(D) the surviving cell is CLIPPED to its run');
  check('96 × 64 world, (0,0) spared',
    shape(fogRects({ min_x: 0, min_z: 0, max_x: 96, max_z: 64 }, [], 0,
      undefined, new Set(['0,0']))), ['64/0 32x64']);

  console.log('\n(E) the negative side');
  check('−128…0 × −64…0, (−1,−1) spared',
    shape(fogRects({ min_x: -128, min_z: -64, max_x: 0, max_z: 0 }, [], 0,
      undefined, new Set(['-1,-1']))), ['-128/-64 64x64']);

  console.log('\n(F) the memory beats the flat-ground shortcut');
  check('level ground without a memory is ONE quad',
    shape(fogRects(WORLD, [], 0, FLAT)), ['0/0 128x128']);
  check('…and with (0,0) spared it is the three of (B)',
    shape(fogRects(WORLD, [], 0, FLAT, new Set(['0,0']))),
    ['0/64 64x64', '64/0 64x64', '64/64 64x64']);

  console.log('\n(G) RED — a memory elsewhere must not cost the flat world its'
    + ' single quad');
  check('level ground, memory at (5,5)',
    shape(fogRects(WORLD, [], 0, FLAT, new Set(['5,5']))), ['0/0 128x128']);

  console.log('\n(H) a footprint and the memory in one run');
  const WIDE = { min_x: 0, min_z: 0, max_x: 192, max_z: 64 };
  const HUT = [{ x: 96, z: 32, width: 64, yaw: 0 }];
  check('the hut alone leaves two runs', shape(fogRects(WIDE, HUT, 0)),
    ['0/0 64x64', '128/0 64x64']);
  check('…and sparing (0,0) leaves the far one',
    shape(fogRects(WIDE, HUT, 0, undefined, new Set(['0,0']))),
    ['128/0 64x64']);

  console.log(`\n${passed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
}

main().catch((e) => {
  console.error(`\nsmoke_fog_memory: ${e?.message || e}`);
  process.exit(1);
});
