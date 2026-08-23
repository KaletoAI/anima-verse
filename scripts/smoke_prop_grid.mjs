#!/usr/bin/env node
/**
 * Smoke run for the PLACEMENT GRID of the world-props tool (§ A9a) — the two
 * pure helpers the map editor snaps and draws with,
 * `snapToGrid` and `gridLinesInView` in `frontend/src/tabs/map/mapMath.ts`.
 *
 * Usage:  node scripts/smoke_prop_grid.mjs
 *         (bundles the module with esbuild — a Vite dependency, already
 *          installed; no bundler config, no jsdom, no server)
 *
 * Same discipline as the other mjs smokes: every expected number is derived BY
 * HAND below and never recorded from the current output. What is deliberately
 * NOT covered is the React wiring (the toolbar picker, the localStorage
 * memory, the SVG lines) — that is a rendering question and this file could
 * only record it.
 *
 * ============================================================================
 * WHAT THE GRID IS FOR
 * ============================================================================
 * A world prop is set by hand at ONE point in world metres. By hand alone a
 * row of fence posts never lines up, so the props tool offers a raster: while
 * it is on, a placed or dragged prop lands on the nearest line and its yaw on
 * the nearest 15°. The angle is part of the SAME switch on purpose — a grid
 * that aligns the positions but leaves every post turned by 7° has aligned
 * nothing anybody can see.
 *
 * The raster is anchored at the WORLD ORIGIN, never at the first prop and
 * never at the view, so two props on the same step are on the same lines
 * wherever they stand and panning moves neither.
 *
 * The snap runs on the CLIENT, before the save call. The route keeps taking
 * free coordinates: the grid is how this editor builds, not a rule about what
 * the world may hold.
 *
 * ============================================================================
 * (A) snapToGrid — HALF-WAY ROUNDS AWAY FROM ZERO
 * ============================================================================
 * `Math.round` rounds half UP, which is not symmetric about the origin:
 * round(0.5) = 1 but round(-0.5) = -0. Applied to a raster that would put
 * +0.25 on +0.5 and -0.25 on 0 — the same distance from a line answered two
 * different ways, i.e. a grid that behaves differently west of the origin.
 * The helper therefore snaps |v| and puts the sign back:
 *
 *   step 1     3.4  -> |3.4|/1 = 3.4 -> round 3 -> 3
 *              3.6  -> 3.6 -> round 4 -> 4
 *              -3.4 -> 3.4 -> round 3 -> -3          (mirror of the first)
 *              3.5  -> round 4 (half away from zero) -> 4
 *              -3.5 -> -4                            (and NOT -3)
 *   step 0.5   -0.25 -> 0.25/0.5 = 0.5 -> round 1 -> -0.5
 *              0.25  -> 0.5
 *              0.74  -> 1.48 -> round 1 -> 0.5
 *              0.76  -> 1.52 -> round 2 -> 1
 *   step 2     -3    -> 3/2 = 1.5 -> round 2 -> -4
 *              301   -> 150.5 -> round 151 -> 302     (far from the origin,
 *                                                      still on the raster)
 *   step 0.1   3.34  -> 33.4 -> round 33 -> 3.3       (two decimals, the
 *              3.36  -> 33.6 -> round 34 -> 3.4        precision § A9a stores)
 *
 * The YAW uses the very same helper at step 15:
 *
 *   37    -> 37/15 = 2.4667 -> round 2 -> 30
 *   52.5  -> 3.5 -> round 4 (away from zero) -> 60
 *   7.4   -> 0.4933 -> round 0 -> 0
 *   -7.6  -> 0.5067 -> round 1 -> -15   (the caller normalises that to 345)
 *   352   -> 23.4667 -> round 23 -> 345
 *
 * Step 0 (or a negative, or NaN) means "no grid": the value is only trimmed to
 * centimetres, which is exactly what free placement did before the feature —
 * 3.456 -> 3.46, -0.254 -> -0.25.
 *
 * ============================================================================
 * (B) gridLinesInView — INCLUSIVE AT BOTH ENDS
 * ============================================================================
 * `View {cx, cz, pxPerM}` with a canvas of w x h px shows the world rectangle
 * [cx - w/2/pxPerM, cx + w/2/pxPerM] x [cz - h/2/pxPerM, cz + h/2/pxPerM]
 * (`visibleWorldRect`). The lines are every multiple of `step` inside it,
 * INCLUDING one lying exactly on the edge — it is visible, so it is drawn.
 *
 *   THE 10 m WINDOW: w = 200 px, pxPerM = 20  ->  200/20 = 10 m wide
 *   cx = 5 puts it at x [0, 10]; h = 200 and cz = 5 does the same for z.
 *
 *   step 2 m:  n from ceil(0/2) = 0 while n*2 <= 10  ->  0, 2, 4, 6, 8, 10
 *              = SIX lines per axis (not five — both ends count)
 *   step 5 m:  0, 5, 10                              = three
 *   step 1 m:  0..10                                 = eleven
 *   step 4 m:  0, 4, 8                               = three (12 > 10 falls
 *                                                     outside, no half line)
 *
 *   AN OFF-RASTER WINDOW: cx = 5.5 -> x [0.5, 10.5]
 *   step 2 m:  first n = ceil(0.5/2) = ceil(0.25) = 1  ->  2, 4, 6, 8, 10
 *              = five, and the first line is at 2 m, not at the window edge.
 *
 *   NEGATIVE GROUND: cx = -5 -> x [-10, 0], step 2 m
 *              first n = ceil(-10/2) = -5  ->  -10, -8, -6, -4, -2, 0
 *              = six, mirroring the first case exactly.
 *
 * ============================================================================
 * (C) THE 6 px FLOOR — a raster nobody can read is not drawn
 * ============================================================================
 * Lines closer together than a few pixels stop being a raster: they become a
 * moiré that hides the ground the props are being aligned against. So below
 * `GRID_MIN_SPACING_PX` = 6 px of on-screen spacing the drawing stops —
 * and ONLY the drawing; the snap goes on working, because the step the user
 * asked for is still the step they asked for.
 *
 *   spacing_px = step * pxPerM
 *   step 0.5 m at pxPerM 12  ->  6.0 px  = exactly the floor -> DRAWN
 *   step 0.5 m at pxPerM 11  ->  5.5 px  < the floor         -> nothing
 *   step 5   m at pxPerM 1   ->  5.0 px  < the floor         -> nothing
 *              (a 5 m grid vanishes too, once the world is zoomed far enough
 *               out — the floor is about PIXELS, not about the metre)
 *   step 5   m at pxPerM 1.2 ->  6.0 px                      -> DRAWN
 *
 * An unmeasured canvas (w or h = 0, the state before the first ResizeObserver
 * answer) and a grid that is off (step 0) draw nothing either.
 */
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const SRC = join(ROOT, 'frontend/src/tabs/map/mapMath.ts');

/** Bundled and imported — `mapMath` pulls in the workspace package
 *  `@anima/scene-render`, which esbuild resolves and inlines. */
async function loadBundled(src, prefix) {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), prefix));
  try {
    const file = join(dir, 'module.mjs');
    await esbuild.build({
      entryPoints: [src], outfile: file, bundle: true, format: 'esm',
      platform: 'neutral', logLevel: 'silent', absWorkingDir: ROOT,
    });
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

let failed = 0;
let passed = 0;
function check(label, actual, expected) {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  if (ok) {
    passed += 1;
    console.log(`  ok   ${label}`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}\n       expected ${JSON.stringify(expected)}`
      + `\n       actual   ${JSON.stringify(actual)}`);
  }
}

const { snapToGrid, gridLinesInView, GRID_MIN_SPACING_PX, PROP_YAW_STEP_DEG } =
  await loadBundled(SRC, 'propgrid-');

console.log('\nA1  snapToGrid — the metre raster');
check('3.4 at step 1', snapToGrid(3.4, 1), 3);
check('3.6 at step 1', snapToGrid(3.6, 1), 4);
check('-3.4 at step 1', snapToGrid(-3.4, 1), -3);
check('3.5 at step 1 rounds away from zero', snapToGrid(3.5, 1), 4);
check('-3.5 likewise, and NOT -3', snapToGrid(-3.5, 1), -4);
check('-0.25 at step 0.5', snapToGrid(-0.25, 0.5), -0.5);
check('+0.25 at step 0.5 is its mirror', snapToGrid(0.25, 0.5), 0.5);
check('0.74 at step 0.5', snapToGrid(0.74, 0.5), 0.5);
check('0.76 at step 0.5', snapToGrid(0.76, 0.5), 1);
check('-3 at step 2', snapToGrid(-3, 2), -4);
check('301 at step 2 — far from the origin, still on the raster',
  snapToGrid(301, 2), 302);
check('3.34 at step 0.1', snapToGrid(3.34, 0.1), 3.3);
check('3.36 at step 0.1', snapToGrid(3.36, 0.1), 3.4);
check('a point already on a line does not move', snapToGrid(8, 2), 8);
check('the origin stays the origin (and is not -0)',
  Object.is(snapToGrid(-0.4, 2), 0), true);

console.log('\nA2  snapToGrid — the angle raster, the SAME helper');
check('the yaw step is 15°', PROP_YAW_STEP_DEG, 15);
check('37° snaps to 30°', snapToGrid(37, PROP_YAW_STEP_DEG), 30);
check('52.5° snaps to 60°, half away from zero',
  snapToGrid(52.5, PROP_YAW_STEP_DEG), 60);
check('7.4° snaps to 0°', snapToGrid(7.4, PROP_YAW_STEP_DEG), 0);
check('-7.6° snaps to -15° (the caller normalises to 345)',
  snapToGrid(-7.6, PROP_YAW_STEP_DEG), -15);
check('352° snaps to 345°', snapToGrid(352, PROP_YAW_STEP_DEG), 345);
check('a quarter turn is already on the raster',
  snapToGrid(90, PROP_YAW_STEP_DEG), 90);

console.log('\nA3  step 0 means NO grid — centimetres, as before the feature');
check('3.456 keeps its centimetres', snapToGrid(3.456, 0), 3.46);
check('-0.254 likewise', snapToGrid(-0.254, 0), -0.25);
check('a negative step is no grid either', snapToGrid(3.456, -1), 3.46);
check('NaN in, 0 out — never a NaN coordinate', snapToGrid(NaN, 1), 0);

// The 10 m window of (B): 200 px at 20 px/m, centred so it runs x [0, 10].
const W = 200;
const H = 200;
const VIEW = { cx: 5, cz: 5, pxPerM: 20 };

console.log('\nB   gridLinesInView — a 10 m window, both ends inclusive');
check('step 2 m gives six lines per axis',
  gridLinesInView(VIEW, W, H, 2),
  { xs: [0, 2, 4, 6, 8, 10], zs: [0, 2, 4, 6, 8, 10] });
check('step 5 m gives three',
  gridLinesInView(VIEW, W, H, 5).xs, [0, 5, 10]);
check('step 1 m gives eleven',
  gridLinesInView(VIEW, W, H, 1).xs.length, 11);
check('step 4 m stops before the edge — no half line',
  gridLinesInView(VIEW, W, H, 4).xs, [0, 4, 8]);
check('an off-raster window starts at the first line INSIDE it',
  gridLinesInView({ cx: 5.5, cz: 5.5, pxPerM: 20 }, W, H, 2).xs,
  [2, 4, 6, 8, 10]);
check('negative ground mirrors the first case',
  gridLinesInView({ cx: -5, cz: -5, pxPerM: 20 }, W, H, 2).xs,
  [-10, -8, -6, -4, -2, 0]);

console.log('\nC   the 6 px floor — the drawing stops, the snap does not');
check('the floor is 6 px', GRID_MIN_SPACING_PX, 6);
check('0.5 m at 12 px/m = exactly 6 px, drawn',
  gridLinesInView({ cx: 5, cz: 5, pxPerM: 12 }, W, H, 0.5).xs.length > 0, true);
check('0.5 m at 11 px/m = 5.5 px, nothing drawn',
  gridLinesInView({ cx: 5, cz: 5, pxPerM: 11 }, W, H, 0.5),
  { xs: [], zs: [] });
check('even a 5 m grid vanishes at 1 px/m (5 px)',
  gridLinesInView({ cx: 5, cz: 5, pxPerM: 1 }, W, H, 5), { xs: [], zs: [] });
check('…and comes back at 1.2 px/m (6 px)',
  gridLinesInView({ cx: 5, cz: 5, pxPerM: 1.2 }, W, H, 5).xs.length > 0, true);
check('the grid switched off draws nothing',
  gridLinesInView(VIEW, W, H, 0), { xs: [], zs: [] });
check('an unmeasured canvas draws nothing',
  gridLinesInView(VIEW, 0, 0, 2), { xs: [], zs: [] });
// The snap is a different question from the drawing: the step the user asked
// for still bites at a zoom where no line is painted.
check('the snap at 1 px/m still uses the 5 m step', snapToGrid(12.4, 5), 10);

console.log(`\n${failed ? `FAILED (${failed})` : 'all checks passed'}`
  + `  —  ${passed} ok`);
process.exit(failed ? 1 : 0);
