#!/usr/bin/env node
/**
 * Smoke: the ONE relief sampler of `@anima/scene-render`
 * (`packages/scene-render/src/terrain.ts` `sampleTerrain`) reads the lattice
 * the payload actually delivers — contract § B1 Nr. 14 with the v6 Nr. 2
 * addendum `terrain.origin`.
 *
 * Usage:  node client3d/scripts/smoke_terrain_origin.mjs
 *
 * Every expected number below is derived BY HAND in this header from the
 * contract's formula and never recorded from the current output (§ B5a:
 * numbers, never screenshots).
 *
 * --- THE RULE ---------------------------------------------------------------
 * With n = grid.length − 1 cells per axis and span = step · n:
 *
 *     u = clamp01((x − origin[0]) / span) · n
 *     v = clamp01((z − origin[1]) / span) · n
 *     i = min(floor(u), n − 1),  tx = u − i     (j / tz likewise)
 *     h = (1−tz)·[(1−tx)·g[j][i] + tx·g[j][i+1]]
 *       +    tz ·[(1−tx)·g[j+1][i] + tx·g[j+1][i+1]]
 *
 * `origin` is the MIN CORNER of the lattice in payload metres. Before v6 the
 * lattice was a square around the PIN, so the sampler read
 * `u = x / extent + 0.5`; that formula stays as the fallback for a payload
 * without an origin, and § A1.1 guarantees the two agree whenever the boundary
 * IS centred on its pin — which section [3] proves as a number, not as a claim.
 *
 * ============================================================================
 * [1] THE OFF-CENTRE LATTICE — the case the field was added for
 * ============================================================================
 * A plot drawn far to the east of its pin: boundary bbox 40 … 80 m in x,
 * −20 … 20 m in z, so extent_m = 40 and the terrain frame is the 40 m square
 * over that box, i.e. origin = (40, −20), step = 40 / 2 = 20 for a 2-cell
 * demo grid (n = 2, 3 × 3 support points, span = 40):
 *
 *     grid = [[0, 0, 0],
 *             [0, 6, 0],
 *             [0, 0, 0]]
 *
 * (rim 0 as the composer pins it, one 6 m spike in the middle).
 *
 *   (a) the lattice CENTRE is the world point (60, 0):
 *       u = (60 − 40)/40 · 2 = 1.0  -> i = min(1, 1) = 1, tx = 0
 *       v = ( 0 + 20)/40 · 2 = 1.0  -> j = 1, tz = 0
 *       h = g[1][1] = 6
 *   (b) halfway from the centre to the east rim, world (70, 0):
 *       u = (70 − 40)/40 · 2 = 1.5  -> i = 1, tx = 0.5
 *       v = 1.0                     -> j = 1, tz = 0
 *       h = 0.5·g[1][1] + 0.5·g[1][2] = 0.5·6 + 0.5·0 = 3
 *   (c) quarter cell in BOTH axes, world (65, 5):
 *       u = (65 − 40)/40 · 2 = 1.25 -> i = 1, tx = 0.25
 *       v = ( 5 + 20)/40 · 2 = 1.25 -> j = 1, tz = 0.25
 *       h = (1−0.25)·[(1−0.25)·6 + 0.25·0] + 0.25·[(1−0.25)·0 + 0.25·0]
 *         = 0.75 · 4.5 = 3.375
 *   (d) the PIN (0, 0) lies far west of this lattice: u clamps to 0, v to
 *       (0+20)/40·2 = 1.0 -> h = g[1][0] = 0. The pin is OUTSIDE the plot and
 *       reads the rim, which is the whole point — the old formula would have
 *       read the centre spike there (see [2]).
 *   (e) 100 m east, past the rim: u clamps to 1 -> i = 1, tx = 1 -> g[1][2] = 0.
 *
 * ============================================================================
 * [2] THE OLD FORMULA IS THE BUG — the same payload without an origin
 * ============================================================================
 * Drop `origin` from [1]'s payload and the fallback `u = x/span + 0.5` runs:
 *   world (60, 0): u = 60/40 + 0.5 = 2.0 -> clamps to 1 -> i = 1, tx = 1 -> 0
 *   world ( 0, 0): u = 0.5, v = 0.5 -> i = j = 1, tx = tz = 0 -> g[1][1] = 6
 * i.e. the spike sits at the pin instead of at the plot's centre, 60 m away.
 * The two rows below are the numeric statement of that drift; they are what
 * the `origin` field removes.
 *
 * ============================================================================
 * [3] A PIN-CENTRED PLOT: origin CHANGES NOTHING
 * ============================================================================
 * boundary bbox −20 … 20 in both axes -> origin = (−20, −20), same step/grid.
 *   world (0, 0):   u = (0+20)/40·2 = 1.0, v = 1.0            -> 6
 *   old formula:    u = 0/40 + 0.5 = 0.5, ·2 = 1.0, v likewise -> 6
 *   world (10, 0):  u = (10+20)/40·2 = 1.5 -> i 1, tx 0.5      -> 3
 *   old formula:    u = (10/40 + 0.5)·2 = 1.5                  -> 3
 * Identical, as v6 Nr. 2 promises for a boundary drawn around its pin.
 *
 * ============================================================================
 * [4] DEGENERATE PAYLOADS
 * ============================================================================
 * No terrain, a grid of fewer than two rows, and a step of 0 with extent 0 all
 * answer 0 — a missing height field is flat ground, never a crash.
 * A step of 0 WITH an extent falls back on the extent as the span (the pre-v6
 * reading), so an old payload keeps working.
 */
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');

/** `terrain.ts` is type-import only by design, so a transpile is all it takes.
 *  Should someone add a runtime import, this fails loudly — that is the alarm,
 *  not a nuisance. */
async function loadPure(rel) {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'terrain-'));
  try {
    const source = await readFile(join(ROOT, rel), 'utf8');
    const code = esbuild.transformSync(source, { loader: 'ts', format: 'esm' }).code;
    const file = join(dir, 'terrain.mjs');
    await writeFile(file, code, 'utf8');
    return await import(`file://${file}`);
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

const { sampleTerrain } = await loadPure('packages/scene-render/src/terrain.ts');

const GRID = [[0, 0, 0], [0, 6, 0], [0, 0, 0]];
/** The plot drawn 40 … 80 m east of its pin: extent 40, 2 cells of 20 m. */
const OFFSET = { step: 20, grid: GRID, amplitude_m: 6, origin: [40, -20] };
/** The very same field without the v6 addendum. */
const LEGACY = { step: 20, grid: GRID, amplitude_m: 6 };
/** The plot drawn around its own pin. */
const CENTRED = { step: 20, grid: GRID, amplitude_m: 6, origin: [-20, -20] };

console.log('[1] the off-centre lattice is read at its own origin');
check('centre of the plot (60, 0)', sampleTerrain(OFFSET, 60, 0, 40), 6);
check('half a cell east (70, 0)', sampleTerrain(OFFSET, 70, 0, 40), 3);
check('quarter cell on both axes (65, 5)', sampleTerrain(OFFSET, 65, 5, 40), 3.375);
check('the pin (0, 0) is outside — rim', sampleTerrain(OFFSET, 0, 0, 40), 0);
check('past the east rim (100, 0)', sampleTerrain(OFFSET, 100, 0, 40), 0);

console.log('[2] without an origin the old pin-centred formula runs — the drift');
check('legacy at the plot centre (60, 0)', sampleTerrain(LEGACY, 60, 0, 40), 0);
check('legacy at the pin (0, 0)', sampleTerrain(LEGACY, 0, 0, 40), 6);

console.log('[3] a pin-centred plot: origin and legacy agree');
check('origin at the pin (0, 0)', sampleTerrain(CENTRED, 0, 0, 40), 6);
check('legacy at the pin (0, 0)', sampleTerrain(LEGACY, 0, 0, 40), 6);
check('origin 10 m east', sampleTerrain(CENTRED, 10, 0, 40), 3);
check('legacy 10 m east', sampleTerrain(LEGACY, 10, 0, 40), 3);

console.log('[4] degenerate payloads are flat ground, never a throw');
check('no terrain', sampleTerrain(null, 0, 0, 40), 0);
check('one-row grid', sampleTerrain({ step: 20, grid: [[0]], amplitude_m: 0 }, 0, 0, 40), 0);
check('no step and no extent',
  sampleTerrain({ step: 0, grid: GRID, amplitude_m: 6 }, 0, 0, 0), 0);
check('no step, extent carries the span',
  sampleTerrain({ step: 0, grid: GRID, amplitude_m: 6 }, 0, 0, 40), 6);

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
