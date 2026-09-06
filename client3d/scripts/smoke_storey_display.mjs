#!/usr/bin/env node
/**
 * Smoke check for WHAT A PIECE OF A DECLARED STOREY IS DRAWN AT —
 * `client3d/src/scene/storeyDisplay.ts`, plus the wiring that carries that
 * rule into the storey switch (`client3d/src/scene/tiles.ts`) and into the
 * mount (`client3d/src/scene/sceneRecipe.ts`), both read as SOURCE: § B5a says
 * strings and numbers, never screenshots, and `tiles.ts` cannot be loaded on
 * its own (it imports `three` and `@anima/scene-render`).
 *
 * Usage:  node client3d/scripts/smoke_storey_display.mjs
 *
 * `storeyDisplay.ts` is pure and import-free like `scene/shellPlan.ts`, so a
 * plain esbuild transpile loads it. If someone adds a runtime import the
 * loader fails loudly, which is the intended alarm.
 *
 * ===========================================================================
 * WHY THIS EXISTS (user finding 2026-09-06, "sometimes the floor is see-through")
 * ===========================================================================
 * Report: in a third-floor flat the KITCHEN floor is see-through from some
 * camera angles and solid from others — one looks through it onto the ground.
 *
 * The payload GHOSTS every storey above the lowest one (`_opacity_role`,
 * app/core/scene_recipe.py): the piece is marked `upper` and the renderer
 * builds it `transparent` at `style.upper_floor_opacity` = 0.4. That is the
 * FAR view's look. Inside, since 2026-07-31, exactly ONE storey is drawn and
 * the others are gone by `visible`, so `applyLevelDisplay` takes the ghosting
 * back off again — but it only ever did that for the storey's CONTOUR plate
 * (`levelSlabs`) and for the walls (`levelWallMats`). A ROOM's own floor plate
 * was registered in neither list and kept its 0.4.
 *
 * THE NUMBERS OF THE REPORTED PLACE, composed by `_plates()` with the real
 * layout of "Wohnung von Kira" (storey_height_m 3.1, rooms on level 3,
 * LEVEL_PLATE_TOP 0.08, ROOM_PLATE_TOP 0.10, ROOM_PLATE_THICKNESS 0.02):
 *
 *     (storey slab)  top_y 9.380  thickness 0.14  role upper   -> opacity 1  (restored)
 *     Kueche         top_y 9.400  thickness 0.02  role upper   -> opacity 0.4 (NOT restored)
 *
 * and the kitchen is the ONE room of that flat with no diorama mesh
 * (`selection.json`: `"room_451fb272": {}`), so its floor is that plate and
 * nothing else. Where a room plate has no storey plate under it — an
 * `always_visible` zone stays visible while the switch shows another storey,
 * and that storey's contour plate does not — the same 0.4 looks straight down
 * onto the terrain.
 *
 * ---------------------------------------------------------------------------
 * (A) THE RULE, derived by hand
 * ---------------------------------------------------------------------------
 * `storeyPieceOpacity(pieceLevel, shownLevel, ghost)`:
 *
 *  (A1) THE STOREY THAT IS SHOWN IS SOLID. It is alone in the picture, so
 *       there is nothing behind it the ghost could open up:  (3, 3, 0.4) = 1.
 *  (A2) EVERY OTHER STOREY KEEPS WHAT THE PAYLOAD COMPOSED:  (3, 0, 0.4) = 0.4.
 *       Not 1 and not 0 — the far view and an always-visible zone on a foreign
 *       storey are exactly the cases that need the composed value back.
 *  (A3) THE SWITCH GOES BOTH WAYS AND DOES NOT DRIFT. 3 shown -> 1, then 0
 *       shown -> 0.4, then 3 shown -> 1 again. The function reads the composed
 *       value, never the current one, so no number can be lost by switching.
 *  (A4) A `ground`-ROLE PIECE HAS NO GHOST (its composed opacity is 1), so it
 *       answers 1 on every storey:  (0, 0, 1) = 1 and (0, 3, 1) = 1.
 *  (A5) A ROOM PLATE AND THE STOREY SLAB OF THE SAME STOREY GET THE SAME
 *       NUMBER. The function is not told which family it is asked about —
 *       that is the whole point of the finding, where the two were treated
 *       differently:  (3, 3, 0.4) === (3, 3, 0.4) = 1.
 *  (A6) A BASEMENT IS A DECLARED STOREY LIKE ANY OTHER: (-1, -1, 0.4) = 1,
 *       (-1, 0, 0.4) = 0.4.
 *  (A7) `STOREY_SHOWN_OPACITY` is 1 — written down so "solid" cannot quietly
 *       become 0.95.
 *
 * ---------------------------------------------------------------------------
 * (B) THE WIRING (source strings)
 * ---------------------------------------------------------------------------
 * The rule is worth nothing unless the room plates actually reach it. Four
 * lines carry them there, and each one is a place the defect could come back:
 *
 *  (B1) `tiles.ts` imports the rule instead of writing `=== filter ? 1 : x`
 *       a fourth time.
 *  (B2) `applyLevelDisplay` walks `levelRoomPlateMats` through it.
 *  (B3) `mountScene` registers a room plate WITH the opacity the payload
 *       composed it with — the material's own value at build time.
 *  (B4) `unmountScene` clears the map, like `levelSlabs` and `levelWallMats`;
 *       a remount would otherwise write into materials that are gone.
 *  (B5) …and the composed value itself is still the style's ghost, i.e. this
 *       check is measuring the same ladder the finding is about.
 */
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');
const RULE_SRC = join(ROOT, 'client3d/src/scene/storeyDisplay.ts');
const TILES_SRC = join(ROOT, 'client3d/src/scene/tiles.ts');
const RECIPE_SRC = join(ROOT, 'client3d/src/scene/sceneRecipe.ts');

/** See the header: the module has no runtime import, so a transpile is all it
 *  takes. Should someone add one, this fails loudly. */
async function loadTs(src) {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'storeydisp-'));
  try {
    const source = await readFile(src, 'utf8');
    const out = esbuild.transformSync(source, { loader: 'ts', format: 'esm' });
    const file = join(dir, 'module.mjs');
    await writeFile(file, out.code, 'utf8');
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

/** The style value the payload ghosts an upper FLOOR with
 *  (`app/core/scene_recipe.STYLE.upper_floor_opacity`). Written here by hand,
 *  not read from anywhere — if the server changes it, this check has to be
 *  looked at rather than silently follow. */
const GHOST_FLOOR = 0.4;

async function main() {
  const { storeyPieceOpacity, STOREY_SHOWN_OPACITY } = await loadTs(RULE_SRC);

  console.log('(A) the rule');
  check('A1 the storey the view shows is solid',
    storeyPieceOpacity(3, 3, GHOST_FLOOR), 1);
  check('A2 another storey keeps the composed ghost',
    storeyPieceOpacity(3, 0, GHOST_FLOOR), GHOST_FLOOR);
  check('A3 switching there, away and back does not drift',
    [storeyPieceOpacity(3, 3, GHOST_FLOOR), storeyPieceOpacity(3, 0, GHOST_FLOOR),
      storeyPieceOpacity(3, 3, GHOST_FLOOR)],
    [1, GHOST_FLOOR, 1]);
  check('A4 a ground-role piece has no ghost and is solid everywhere',
    [storeyPieceOpacity(0, 0, 1), storeyPieceOpacity(0, 3, 1)], [1, 1]);
  check('A5 room plate and storey slab of one storey get the same number',
    storeyPieceOpacity(3, 3, GHOST_FLOOR) === storeyPieceOpacity(3, 3, GHOST_FLOOR)
      && storeyPieceOpacity(3, 3, GHOST_FLOOR) === 1,
    true);
  check('A6 a basement is a declared storey like any other',
    [storeyPieceOpacity(-1, -1, GHOST_FLOOR), storeyPieceOpacity(-1, 0, GHOST_FLOOR)],
    [1, GHOST_FLOOR]);
  check('A7 "solid" is 1', STOREY_SHOWN_OPACITY, 1);

  const tiles = await readFile(TILES_SRC, 'utf8');
  const recipe = await readFile(RECIPE_SRC, 'utf8');

  console.log('\n(B) the wiring');
  check('B1 the storey switch imports the rule',
    tiles.includes("import { storeyPieceOpacity } from './storeyDisplay';"), true);
  check('B2 applyLevelDisplay walks the room plates through it',
    [tiles.includes('for (const [lv, plates] of tile.levelRoomPlateMats) {'),
      tiles.includes('p.mat.opacity = storeyPieceOpacity(lv, tile.levelFilter, p.ghost);')],
    [true, true]);
  check('B3 the mount registers a room plate with its COMPOSED opacity',
    recipe.includes('const entry = { mat: plateMat, ghost: plateMat.opacity };'), true);
  check('B3 …under its own storey',
    [recipe.includes('const forLevel = tile.levelRoomPlateMats.get(plate.level);'),
      recipe.includes('else tile.levelRoomPlateMats.set(plate.level, [entry]);')],
    [true, true]);
  check('B4 the unmount clears the map like the other level maps',
    recipe.includes('tile.levelRoomPlateMats.clear();'), true);
  check('B5 the composed value is still the payload style\'s ghost',
    [recipe.includes('const upper = plate.opacity_role === \'upper\';'),
      recipe.includes('const opacity = upper ? (style.upper_floor_opacity ?? 1) : 1;')],
    [true, true]);

  console.log(`\n${passed} ok, ${failed} failed`);
  process.exit(failed ? 1 : 0);
}

main().catch((e) => { console.error(e); process.exit(1); });
