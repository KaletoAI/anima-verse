#!/usr/bin/env node
/**
 * Smoke check for the FAR-VIEW SHELL decision — where the shape of a location
 * comes from when the camera is outside it
 * (`client3d/src/scene/shellPlan.ts`), plus the wiring that carries that
 * decision into the mount (`client3d/src/scene/sceneRecipe.ts`, read as
 * source: § B5a says strings and numbers, never screenshots).
 *
 * Usage:  node client3d/scripts/smoke_far_shell.mjs
 *
 * `shellPlan.ts` is pure and import-free like `game/walk.ts`, so a plain
 * esbuild transpile loads it — no bundler, no three, no stand-ins. If someone
 * adds a runtime import the loader fails loudly, which is the intended alarm.
 *
 * ===========================================================================
 * WHY THIS EXISTS (user finding 2026-08-20)
 * ===========================================================================
 * The procedural building shell was struck on 2026-08-19 — a place must not
 * show a shape nobody authored. What was left was a place with NO shape: the
 * socle plate and a floating label, with the walls appearing only once the
 * player entered. But the walls are not missing at all: the scene recipe
 * delivers them as finished § B primitives, and they are the walls the place
 * really has. So a location without a server model wears its own primitives as
 * the far view.
 *
 * ---------------------------------------------------------------------------
 * (A) THE FOUR SOURCES, each derived by hand from the rule
 * ---------------------------------------------------------------------------
 * (A1) A MODEL WINS. A payload with a `role: 'building'` spec answers 'model'
 *      whatever else it says — even for an area location, even with a hundred
 *      plates — because what that model IS (shell / ground / detail area) is
 *      the SPEC's own `display` field and is decided where it is placed, not
 *      here. Two cases: a plain building with a model, and an area location
 *      with one.
 *
 * (A2) A BUILDING WITHOUT A MODEL FALLS TO THE RECIPE, and that is the whole
 *      finding: plates 12 / walls 30 -> 'recipe'. Walls alone are enough
 *      (0/30 -> 'recipe'): the shape of a place is its walls, and a payload
 *      may carry an outline without a storey plate. Plates alone likewise
 *      (12/0), which is a flat place — a courtyard reads as ground rather than
 *      as nothing.
 *
 * (A3) AN AREA LOCATION SHOWS ITS GROUND. A wood's "rooms" are zones like Road
 *      or Forest; walls around them would fence the wood in. Three ways to be
 *      one, each on its own and each with plates and walls present so the test
 *      cannot pass by accident:
 *        isBuilding false   -> 'ground'   (passable / template place)
 *        natureSite true    -> 'ground'   (named wood, lake, meadow, road)
 *        areaDetail true    -> 'ground'   (`scene.area_detail`, § B6 Nr. 10)
 *
 * (A4) NOTHING TO BUILD FROM. A building whose payload has neither plates nor
 *      walls -> 'none'. Junk counts (NaN, undefined) read as 0 and give the
 *      same answer rather than a shell of NaN primitives.
 *
 * (A5) `wantsRecipeShell` is exactly "the source is 'recipe'" — asserted
 *      against `farShellSource` over the whole table above, so the shorthand
 *      cannot drift away from the decision it abbreviates.
 *
 * ---------------------------------------------------------------------------
 * (B) THE WIRING, read out of `sceneRecipe.ts`
 * ---------------------------------------------------------------------------
 * Three lines the mount has to contain, none of which is arithmetic:
 *   B1 the shell is built from the PLATES AND WALLS just built, and only from
 *      storeys at or above ground — a basement is not part of a silhouette;
 *   B2 it is a `tile.shell` and rides the existing crossfade through
 *      `roofParts`/`roofMats` (what `applyTileFade` fades), with the corridor
 *      fade on its materials like every other shell;
 *   B3 the handover is the one that already existed: `applySceneBuilding`
 *      drops it when a real model arrives, and `unmountScene` drops it with
 *      the scene whose primitives it copies.
 * A fourth: the copies are invisible to the raycaster, so a click keeps
 * selecting what it selected before the shell existed.
 */
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');
const PLAN_SRC = join(ROOT, 'client3d/src/scene/shellPlan.ts');
const RECIPE_SRC = join(ROOT, 'client3d/src/scene/sceneRecipe.ts');

/** See the header: the module has no runtime import, so a transpile is all it
 *  takes. Should someone add one, this fails loudly. */
async function loadTs(src) {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'farshell-'));
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

async function main() {
  const { farShellSource, wantsRecipeShell } = await loadTs(PLAN_SRC);

  /** A plain built place with a room layout and no model — the case of the
   *  finding. Every row below is this one with exactly one field moved. */
  const HOUSE = {
    isBuilding: true, natureSite: false, areaDetail: false,
    hasBuildingModel: false, plates: 12, walls: 30,
  };

  console.log('(A) the four sources of a far view');
  check('A1 a building WITH a model: the model is the far view',
    farShellSource({ ...HOUSE, hasBuildingModel: true }), 'model');
  check('A1 …and it wins over an area location too',
    farShellSource({ ...HOUSE, hasBuildingModel: true, areaDetail: true,
      natureSite: true }),
    'model');
  check('A2 a building WITHOUT one falls to the recipe primitives',
    farShellSource(HOUSE), 'recipe');
  check('A2 …walls alone are a shape', farShellSource({ ...HOUSE, plates: 0 }),
    'recipe');
  check('A2 …and plates alone are one', farShellSource({ ...HOUSE, walls: 0 }),
    'recipe');
  check('A3 a passable/template place shows its ground',
    farShellSource({ ...HOUSE, isBuilding: false }), 'ground');
  check('A3 …a named nature site does too',
    farShellSource({ ...HOUSE, natureSite: true }), 'ground');
  check('A3 …and so does a composed area detail scene',
    farShellSource({ ...HOUSE, areaDetail: true }), 'ground');
  check('A4 a building with no primitives has nothing to show',
    farShellSource({ ...HOUSE, plates: 0, walls: 0 }), 'none');
  check('A4 …and junk counts read as none, never as a shell of NaN',
    [farShellSource({ ...HOUSE, plates: NaN, walls: NaN }),
      farShellSource({ ...HOUSE, plates: undefined, walls: undefined })],
    ['none', 'none']);
  const TABLE = [
    HOUSE,
    { ...HOUSE, hasBuildingModel: true },
    { ...HOUSE, isBuilding: false },
    { ...HOUSE, natureSite: true },
    { ...HOUSE, areaDetail: true },
    { ...HOUSE, plates: 0, walls: 0 },
    { ...HOUSE, plates: 0 },
  ];
  check('A5 wantsRecipeShell is exactly "the source is recipe"',
    TABLE.map(wantsRecipeShell),
    TABLE.map((f) => farShellSource(f) === 'recipe'));

  console.log('\n(B) the wiring in sceneRecipe.ts');
  const recipe = await readFile(RECIPE_SRC, 'utf8');
  check('B1 the mount asks the plan and builds from the primitives it has',
    recipe.includes('})) buildFarShell(tile, builtPlates, builtWalls);'), true);
  check('B1 …taking the LEVEL plates of storeys at or above ground',
    recipe.includes('if (!plate.room_id && plate.level >= 0) take(mesh);'), true);
  check('B1 …and the non-glass walls of those storeys',
    recipe.includes('if (!wall.glass && wall.level >= 0) take(mesh);'), true);
  check('B2 it is a tile.shell', recipe.includes('tile.shell = shell;'), true);
  check('B2 …and rides the existing crossfade',
    [recipe.includes('tile.roofParts.push(shell);'),
      recipe.includes('tile.roofMats.push(...mats);')],
    [true, true]);
  check('B2 …with the corridor fade on its own material clone',
    recipe.includes('    applyOcclusionFade(mat);\n    copy.material = mat;'),
    true);
  check('B3 a real model takes over from it',
    recipe.includes('  dropFarShell(tile);\n  tile.serverModel = model;'), true);
  check('B3 …and it dies with the scene it copies',
    recipe.includes('if (prev && prev.name === SCENE_GROUP) tile.group.remove(prev);\n'
      + '  // The far-view shell is a copy of THIS scene\'s primitives, so it dies with\n'
      + '  // it — its geometries are the ones just taken out of the graph.\n'
      + '  dropFarShell(tile);'),
    true);
  // Scoped to the teardown itself: `geometry.dispose()` is legitimate
  // elsewhere in this file (the drape swaps a plate's geometry), it is only
  // forbidden HERE — the shell shares its geometries with the walls the player
  // is about to stand in.
  const drop = recipe.slice(recipe.indexOf('function dropFarShell'));
  const dropBody = drop.slice(0, drop.indexOf('\n}\n') + 2);
  check('B3 …freeing the material clones and NOT the shared geometries',
    [dropBody.includes('for (const m of mats) m.dispose();'),
      dropBody.includes('geometry.dispose()'),
      dropBody.length > 0 && dropBody.length < 900],
    [true, false, true]);
  check('B4 the copies are invisible to the raycaster',
    recipe.includes('copy.raycast = () => {};'), true);
  // The second occasion: a payload that DECLARED a model whose mesh never
  // loaded is as shapeless as one with no model, so the shell is built after
  // the placements settle — guarded so it can never build twice.
  check('B5 a declared model that never landed falls back to the shell',
    recipe.includes('if (!tile.shell && !tile.serverModel && wantsRecipeShell({'),
    true);
  check('B5 …and the mount asks the plan exactly twice',
    recipe.split('wantsRecipeShell({').length - 1, 2);

  console.log(`\n${passed} ok, ${failed} failed`);
  process.exit(failed ? 1 : 0);
}

main().catch((e) => { console.error(e); process.exit(1); });
