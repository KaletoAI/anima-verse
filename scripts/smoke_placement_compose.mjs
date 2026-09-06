#!/usr/bin/env node
/**
 * Smoke run for the PARENT LINK `on` in the floor-plan editor — the two pure
 * helpers `composePlacements` and `toSupportFrame` in
 * `frontend/src/tabs/world/placementCompose.ts`.
 *
 * Usage:  node scripts/smoke_placement_compose.mjs
 *         (bundles the module with esbuild — a Vite dependency, already
 *          installed; no bundler config, no jsdom, no server)
 *
 * WHY IT EXISTS. The plan DRAWS and HIT-TESTS a child placement at its
 * composed spot while the placement itself stores a relative one. That is the
 * same arithmetic the server runs in `room_recipe.compose_on_chain`, written
 * twice because the editor may not ask the server on every pointer move — so
 * the two are checked against the SAME hand-derived numbers. The Python side
 * of them is `scripts/smoke_scene_recipe.py` [7j]; if a number here moves,
 * that row has to move with it or the plan is lying about where a piece lands.
 *
 * ============================================================================
 * THE CHILD FRAME (plan-furnish-v2.md § 4, decision E1)
 * ============================================================================
 * A placement carrying `on: "<id>"` stores
 *
 *   at  = [dx, dz]  metres from the SUPPORT's placement point, in the
 *                   support's UNTURNED frame (+x = its width axis,
 *                   +z = its depth axis),
 *   yaw = degrees RELATIVE to the support's heading,
 *
 * and composes with the support's finished pose. THE TURN IS THE RENDERER'S,
 * `R_y(+yaw)` — the same matrix `room_recipe.compose_prop_marker` applies to a
 * marker of the same support (§ B2 step 4, E4). A child stands on the
 * support's MESH, and the mesh turns with `rotation.y = +rad(yaw)`:
 *
 *   r = radians(yaw_support)
 *   x = x_support + dx·cos r + dz·sin r
 *   z = z_support − dx·sin r + dz·cos r
 *   yaw = (yaw_support + yaw_child) mod 360
 *
 * HAND DERIVATION — the [7j] fixture, a table at (3, 2) turned 90° and a
 * candle stored at [0.3, 0] on it (cos 90 = 0, sin 90 = 1):
 *
 *   x = 3.0 + 0.3·0 + 0.0·1 = 3.0
 *   z = 2.0 − 0.3·1 + 0.0·0 = 1.7        →  (3.0, 1.7), yaw 90
 *
 * i.e. 0.3 m along the table's WIDTH axis, which at yaw 90 points north.
 *
 * with the candle's own yaw 45 the heading is 90 + 45 = 135 and the spot is
 * unchanged — the child's yaw turns the candle, not its place.
 *
 * A CHAIN, tray at [0, 0] on the table and mug at [0.1, 0] on the tray:
 *
 *   tray  →  (3.0, 2.0), yaw 90, depth 1
 *   mug   →  x = 3.0 + 0.1·0 + 0.0·1 = 3.0
 *            z = 2.0 − 0.1·1 + 0.0·0 = 1.9,  yaw 90, depth 2
 *
 * ORDER DOES NOT MATTER. The same three entries listed child-first compose to
 * the same three poses: supports are resolved before their children.
 *
 * ============================================================================
 * A LINK THAT DOES NOT HOLD NEVER COSTS A PLACEMENT
 * ============================================================================
 *   unknown id      the piece keeps its stored `at`, the link is dropped
 *   self-reference  likewise
 *   circle          both pieces keep their spots, both lose the link
 *   depth > 3       the support IS valid, so the piece composes through it and
 *                   only loses the link — five pieces at [0.1, 0] on each
 *                   other, root at (1, 1) and every yaw 0 (the turn is the
 *                   identity), give x = 1.0 1.1 1.2 1.3 1.4 at z = 1.0, and
 *                   the fifth stands at 1.4 as a root of its own
 *
 * ============================================================================
 * toSupportFrame — THE INVERSE (dragging a child, "Place on top")
 * ============================================================================
 * The inverse is the TRANSPOSE of the turn above — and therefore the very
 * transform `RoomLayoutEditor.propsAtPoint` runs to hit-test a turned
 * footprint. Dropping the candle at the room point (3.0, 1.7) facing 135° onto
 * the same 90°-turned table has to give back what the forward step consumed:
 *
 *   dx_world = 0.0, dz_world = −0.3
 *   dx = 0.0·cos 90 − (−0.3)·sin 90 = 0.3
 *   dz = 0.0·sin 90 + (−0.3)·cos 90 = 0.0
 *   yaw = 135 − 90 = 45                  →  at [0.3, 0], yaw 45
 *
 * ============================================================================
 * THE VERTICAL CHAIN — composed `offset_y`
 * ============================================================================
 * The plan cannot know a prop's sink (`ground_offset_m`), so it composes the
 * server's `stack_on_support` with every sink taken as 0:
 *
 *   offset_y = offset_y_support + height_m_support + offset_y_child
 *
 * Table 0.75 m high, tray 0.05 m on it, mug on the tray:
 *
 *   table  base 0.00
 *   tray   base 0.00 + 0.75 + 0.00 = 0.75      (top = 0.75 + 0.05 = 0.80)
 *   mug    base 0.75 + 0.05 + 0.00 = 0.80
 *
 * and a 2 cm trim on the tray moves the tray to 0.77 and the mug to 0.82.
 * These are the same numbers `smoke_scene_recipe.py` [7j] derives for the
 * SERVER, which is the point: the plan may not disagree with the recipe about
 * which surface is the higher one.
 *
 * ============================================================================
 * pickSupport — WHICH PIECE CARRIES THE ONE BEING SET DOWN
 * ============================================================================
 * Candidates are the footprints covering the piece's anchor (the editor's own
 * hit test). Two rules, both hand-checked below:
 *
 *   (1) NEVER the piece's own subtree. A tray centred on a table covers the
 *       TABLE's anchor too, so it is one of the table's candidates — writing
 *       `table.on = tray` while `tray.on = table` closes a circle, and the
 *       circle rule would then cut it and drop both pieces to their raw `at`.
 *   (2) The TOPMOST surface wins, ties to the LATER placement — the server's
 *       rule, read off the COMPOSED base plus the prop's own height. Chain
 *       depth does not enter it: a 1.8 m floor lamp is a higher surface than
 *       a 0.01 m coaster lying on a 0.75 m table (top 0.76), whatever their
 *       depths say.
 *
 * ============================================================================
 * dependentIndices — WHAT A DELETE TAKES WITH IT
 * ============================================================================
 * A candle whose table is gone has no frame left to stand in, so removing a
 * support removes its subtree. Over the chain above: the mug alone is [2], the
 * tray takes the mug [1, 2], the table takes both [0, 1, 2] — and the answer
 * is by INDEX, so the same three entries in another order still name the same
 * three rows.
 */
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const SRC = join(ROOT, 'frontend/src/tabs/world/placementCompose.ts');

/** esbuild lives in the frontend workspace; a repo whose root install hoisted
 *  it resolves the bare name, one that did not still finds it there. */
async function esbuildModule() {
  try {
    return await import('esbuild');
  } catch {
    return await import(
      `file://${join(ROOT, 'frontend/node_modules/esbuild/lib/main.js')}`);
  }
}

async function loadBundled(src, prefix) {
  const esbuild = await esbuildModule();
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
/** Floating point: the composition runs through cos/sin, so the check is to
 *  the millimetre — never an exact match on a turned coordinate. */
function round(v) {
  if (Array.isArray(v)) return v.map(round);
  if (typeof v === 'number') return Math.round(v * 1000) / 1000 + 0;
  if (v && typeof v === 'object') {
    return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, round(x)]));
  }
  return v;
}
function check(label, actual, expected) {
  const ok = JSON.stringify(round(actual)) === JSON.stringify(round(expected));
  if (ok) {
    passed += 1;
    console.log(`  ok   ${label}`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}\n       expected ${JSON.stringify(round(expected))}`
      + `\n       actual   ${JSON.stringify(round(actual))}`);
  }
}

const { composePlacements, toSupportFrame, dependentIndices, pickSupport,
  withPropHeights, ON_MAX_DEPTH } =
  await loadBundled(SRC, 'placecompose-');

const TABLE = { id: 'tbl', at: [3.0, 2.0], yaw: 90, height_m: 0.75 };

console.log('\nA  the candle on the turned table');
let out = composePlacements([TABLE, { id: 'cnd', at: [0.3, 0.0], on: 'tbl' }]);
check('the table itself does not move', out[0],
  { at: [3, 2], yaw: 90, offset_y: 0, on: '', depth: 0 });
check('the candle lands at (3.0, 1.7), yaw 90, depth 1, base 0.75', out[1],
  { at: [3, 1.7], yaw: 90, offset_y: 0.75, on: 'tbl', depth: 1 });
out = composePlacements([TABLE, { id: 'cnd', at: [0.3, 0.0], yaw: 45, on: 'tbl' }]);
check('its own yaw 45 adds up to 135 and the spot stays', out[1],
  { at: [3, 1.7], yaw: 135, offset_y: 0.75, on: 'tbl', depth: 1 });
check('a placement on the floor composes to itself',
  composePlacements([{ id: 'x', at: [1.5, -2.25], yaw: 30, offset_y: 0.4 }])[0],
  { at: [1.5, -2.25], yaw: 30, offset_y: 0.4, on: '', depth: 0 });

console.log('\nB  a chain, in any order');
const CHAIN = [TABLE,
  { id: 'try', at: [0.0, 0.0], on: 'tbl', height_m: 0.05 },
  { id: 'mug', at: [0.1, 0.0], on: 'try', height_m: 0.12 }];
out = composePlacements(CHAIN);
check('the tray sits on the table point, base 0.75', out[1],
  { at: [3, 2], yaw: 90, offset_y: 0.75, on: 'tbl', depth: 1 });
check('the mug composes against the TRAY: (3.0, 1.9), base 0.80', out[2],
  { at: [3, 1.9], yaw: 90, offset_y: 0.8, on: 'try', depth: 2 });
const reversed = composePlacements([CHAIN[2], CHAIN[1], CHAIN[0]]);
check('listed child-first the mug lands in the same place', reversed[0],
  { at: [3, 1.9], yaw: 90, offset_y: 0.8, on: 'try', depth: 2 });
check('...and the answer stays in INPUT order', reversed[2],
  { at: [3, 2], yaw: 90, offset_y: 0, on: '', depth: 0 });

console.log('\nC  links that do not hold');
check('an unknown support: the piece keeps its spot',
  composePlacements([{ id: 'kid', at: [4, 4], on: 'ghost' }])[0],
  { at: [4, 4], yaw: 0, offset_y: 0, on: '', depth: 0 });
check('a self-reference: likewise',
  composePlacements([{ id: 'solo', at: [2, 2], on: 'solo' }])[0],
  { at: [2, 2], yaw: 0, offset_y: 0, on: '', depth: 0 });
check('a 2-cycle: both pieces keep their spots and lose the link',
  composePlacements([{ id: 'aaa', at: [2, 2], on: 'bbb' },
    { id: 'bbb', at: [3, 3], on: 'aaa' }]),
  [{ at: [2, 2], yaw: 0, offset_y: 0, on: '', depth: 0 },
    { at: [3, 3], yaw: 0, offset_y: 0, on: '', depth: 0 }]);
check('a piece hanging off a cut circle still follows it',
  composePlacements([{ id: 'aaa', at: [2, 2], on: 'bbb' },
    { id: 'bbb', at: [3, 3], on: 'aaa' },
    { id: 'kid', at: [0.5, 0], on: 'aaa' }])[2],
  { at: [2.5, 2], yaw: 0, offset_y: 0, on: 'aaa', depth: 1 });

console.log('\nD  the chain is three storeys deep, no more');
check('the limit is 3', ON_MAX_DEPTH, 3);
const deep = [{ id: 'p0', at: [1, 1] }];
for (let i = 1; i < 5; i += 1) deep.push({ id: `p${i}`, at: [0.1, 0], on: `p${i - 1}` });
out = composePlacements(deep);
check('x runs 1.0 1.1 1.2 1.3 1.4', out.map((p) => p.at[0]),
  [1, 1.1, 1.2, 1.3, 1.4]);
check('the first four keep their links', out.slice(0, 4).map((p) => p.on),
  ['', 'p0', 'p1', 'p2']);
check('the fifth is composed but linkless, a root of its own', out[4],
  { at: [1.4, 1], yaw: 0, offset_y: 0, on: '', depth: 0 });

console.log('\nE  toSupportFrame — the inverse');
const sup = composePlacements([TABLE])[0];
check('dropping the candle at (3.0, 1.7) facing 135 gives [0.3, 0] / 45',
  toSupportFrame([3.0, 1.7], 135, sup), { at: [0.3, 0], yaw: 45 });
check('the support point itself is the origin of the child frame',
  toSupportFrame([3.0, 2.0], 90, sup), { at: [0, 0], yaw: 0 });
check('and it undoes the forward step for an arbitrary pair',
  toSupportFrame(composePlacements([TABLE,
    { id: 'c', at: [-0.4, 0.25], yaw: 200, on: 'tbl' }])[1].at, 290, sup),
  { at: [-0.4, 0.25], yaw: 200 });

console.log('\nF  the vertical chain — composed offset_y');
out = composePlacements(CHAIN);
check('table 0, tray 0.75, mug 0.80', out.map((p) => p.offset_y),
  [0, 0.75, 0.8]);
check('a 2 cm trim on the tray lifts the mug with it',
  composePlacements([CHAIN[0], { ...CHAIN[1], offset_y: 0.02 }, CHAIN[2]])
    .map((p) => p.offset_y), [0, 0.77, 0.82]);
check('withPropHeights joins the library height onto a placement',
  withPropHeights([{ id: 'a', prop_id: 'table', at: [0, 0] }],
    { table: { height_m: 0.75 } })[0].height_m, 0.75);
check('...and an unknown prop weighs nothing',
  withPropHeights([{ id: 'a', prop_id: 'nope', at: [0, 0] }], {})[0].height_m, 0);

console.log('\nG  pickSupport — which piece carries the one being set down');
const chainC = composePlacements(CHAIN);
check('the mug on a table+tray stack takes the TRAY (top 0.80 > 0.75)',
  pickSupport(CHAIN, chainC, 2, [0, 1, 2]), 1);
// FINDING 1 (review round 2): the tray covers the TABLE's anchor as well, so
// it is one of the table's candidates — and it must never be picked.
check('setting the TABLE down cannot pick its own tray: null',
  pickSupport(CHAIN, chainC, 0, [0, 1, 2]), null);
check('...nor the mug two storeys up',
  pickSupport(CHAIN, chainC, 0, [0, 1, 2, 2]), null);
check('the tray may not stand on the mug it carries either',
  pickSupport(CHAIN, chainC, 1, [0, 1, 2]), 0);
check('nothing underneath at all: null',
  pickSupport(CHAIN, chainC, 2, [2]), null);
// FINDING 2: rank by the COMPOSED top. Two coasters at the SAME depth 1, one
// on the 0.75 m table (top 0.75 + 0.01 = 0.76), one on a 0.40 m stool
// (top 0.40 + 0.01 = 0.41) — the table's wins, and the stored `offset_y` of
// both is 0, so only the composed base can tell them apart.
const TWO = [
  { id: 'tbl', at: [0, 0], height_m: 0.75 },
  { id: 'stl', at: [0, 0], height_m: 0.4 },
  { id: 'c1', at: [0, 0], on: 'tbl', height_m: 0.01 },
  { id: 'c2', at: [0, 0], on: 'stl', height_m: 0.01 },
  { id: 'book', at: [0, 0], height_m: 0.03 }];
const twoC = composePlacements(TWO);
check('the two coasters sit at 0.75 and 0.40', [twoC[2].offset_y, twoC[3].offset_y],
  [0.75, 0.4]);
check('equal depth, different supports: the higher coaster wins',
  pickSupport(TWO, twoC, 4, [0, 1, 2, 3, 4]), 2);
// …and depth itself decides nothing: a 1.8 m floor lamp on the FLOOR beats a
// coaster lying on the table (top 1.80 > 0.76), though it is a depth-0 piece.
const LAMP = [...TWO, { id: 'lmp', at: [0, 0], height_m: 1.8 }];
check('a tall floor piece outranks a low one up a chain',
  pickSupport(LAMP, composePlacements(LAMP), 4, [0, 1, 2, 3, 4, 5]), 5);

console.log('\nH  dependentIndices — what goes with a support');
check('nothing stands on a lone piece', dependentIndices(CHAIN, 2), [2]);
check('the tray takes the mug with it', dependentIndices(CHAIN, 1), [1, 2]);
check('the table takes the whole chain', dependentIndices(CHAIN, 0), [0, 1, 2]);
check('order is by index, whatever the list order says',
  dependentIndices([CHAIN[2], CHAIN[1], CHAIN[0]], 2), [0, 1, 2]);

console.log(`\n${failed ? `FAILED (${failed})` : 'all checks passed'}`
  + `  —  ${passed} ok`);
process.exit(failed ? 1 : 0);
