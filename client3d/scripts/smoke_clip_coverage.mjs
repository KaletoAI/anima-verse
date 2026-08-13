#!/usr/bin/env node
/**
 * Smoke check for the pure clip-coverage rules of the 3D client —
 * `client3d/src/scene/clipCoverage.ts`.
 *
 * Usage:  node client3d/scripts/smoke_clip_coverage.mjs
 *
 * Same discipline as the other client smokes: every expectation below is
 * derived BY HAND from the rule as written down, never recorded from the
 * current output.
 *
 * ===========================================================================
 * WHY THIS FILE EXISTS
 * ===========================================================================
 * Acceptance round 2026-08-13: a character on water walked across the lake
 * instead of swimming. The rule chain (terrain `move_anim: swim` → payload →
 * gate → pace) was correct; the FIGURE was the fallback rig RobotExpressive,
 * whose skeleton is Blender-named (Hips, Abdomen, UpperArm.L, Shoulder.R, …)
 * while the shared clip library is Mixamo-named (mixamorig:Hips,
 * mixamorig:Spine, mixamorig:LeftArm, …). Normalised (prefix and colons
 * dropped, lower-cased) the two skeletons share exactly THREE bones — hips,
 * neck, head — measured from the joint lists of
 * `client3d/public/models/RobotExpressive.glb` against `Soldier.glb` and
 * `Xbot.glb`. Every library clip therefore kept at most 3 rotation tracks plus
 * one hip position track and died on the 8-track threshold in
 * `adaptExternalClips` — silently, because the caller only logged what it HAD
 * gained. `swim` was never bound and fell through `CLIP_FALLBACK` to `walk`.
 *
 * Retargeting cannot rescue that rig either: `retargetClips` pairs target and
 * donor bones by the very same normalised name and gives up below 8 pairs.
 * So the two rules checked here are the fix — name what is missing, and stop
 * handing a library-deaf rig to characters at random.
 *
 * ---------------------------------------------------------------------------
 * (1) missingClipKinds(offered, bound) — WHAT the rig cannot play
 * ---------------------------------------------------------------------------
 * offered minus bound, lower-cased, blanks dropped, de-duplicated, sorted.
 * "Bound" is one namespace: a clip embedded in the mesh counts exactly like an
 * adapted library clip — that is the per-kind merge (an embedded clip wins its
 * own kind, the library fills the gaps).
 *
 *   offered [walk, idle, swim], bound [walk, idle]      -> [swim]
 *   offered [Swim, " WALK "],   bound [swim]            -> [walk]
 *   offered [walk, swim],       bound [walk, swim]      -> []
 *   offered [swim, yoga, walk], bound []                -> [swim, walk, yoga]
 *   offered [walk],             bound [walk] (embedded) -> []
 *   offered ["", swim],         bound [""]              -> [swim]
 *   offered [swim, Swim],       bound []                -> [swim]
 *   offered [],                 bound [walk]            -> []
 *
 * ---------------------------------------------------------------------------
 * (2) animatablePool(pool) — WHICH rigs may stand in at random
 * ---------------------------------------------------------------------------
 * The rigs the library fits; all of them when none fits (a figure with three
 * embedded clips still beats no figure, e.g. an offline run with no library at
 * all). The input is never mutated.
 *
 *   [Soldier+, Xbot+, Robot−]  -> [Soldier, Xbot]     (Robot drops out)
 *   [Soldier−, Xbot−, Robot−]  -> all three           (pool never empties)
 *   [Soldier+, Xbot+]          -> both
 *   []                         -> []
 *   [Robot−]                   -> [Robot]
 */
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');
const SRC = join(ROOT, 'client3d/src/scene/clipCoverage.ts');

/** `clipCoverage.ts` has no import at all — not even a type-only one — so a
 *  plain esbuild transpile loads it here. If someone puts `three` into it,
 *  this loader fails loudly, which is the intended alarm: the module holds the
 *  bookkeeping, `figures.ts` holds the skeleton maths. */
async function loadClipCoverage() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'clipcov-'));
  try {
    const source = await readFile(SRC, 'utf8');
    const out = esbuild.transformSync(source, { loader: 'ts', format: 'esm' });
    const file = join(dir, 'clipCoverage.mjs');
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
  const { missingClipKinds, animatablePool } = await loadClipCoverage();

  console.log('missingClipKinds — the kinds a rig cannot play');
  check('library swim missing, own walk/idle bound',
    missingClipKinds(['walk', 'idle', 'swim'], ['walk', 'idle']), ['swim']);
  check('case and padding are not kinds of their own',
    missingClipKinds(['Swim', ' WALK '], ['swim']), ['walk']);
  check('everything bound -> nothing missing',
    missingClipKinds(['walk', 'swim'], ['walk', 'swim']), []);
  check('nothing bound (the Robot case) -> all, sorted',
    missingClipKinds(['swim', 'yoga', 'walk'], []), ['swim', 'walk', 'yoga']);
  check('embedded clip wins its kind -> kind is not missing',
    missingClipKinds(['walk'], ['walk']), []);
  check('nameless clips are no kinds',
    missingClipKinds(['', 'swim'], ['']), ['swim']);
  check('duplicates collapse',
    missingClipKinds(['swim', 'Swim'], []), ['swim']);
  check('empty library offers nothing to miss',
    missingClipKinds([], ['walk']), []);

  console.log('animatablePool — the rigs a character may be drawn from');
  const soldier = { name: 'Soldier', libraryFits: true };
  const xbot = { name: 'Xbot', libraryFits: true };
  const robot = { name: 'Robot', libraryFits: false };
  const deaf = [{ name: 'Soldier', libraryFits: false }, { name: 'Xbot', libraryFits: false }, robot];
  check('library-deaf rig drops out while fitting ones exist',
    animatablePool([soldier, xbot, robot]).map((m) => m.name), ['Soldier', 'Xbot']);
  check('no rig fits (offline, no library) -> pool stays whole',
    animatablePool(deaf).map((m) => m.name), ['Soldier', 'Xbot', 'Robot']);
  check('all fit -> all stay',
    animatablePool([soldier, xbot]).map((m) => m.name), ['Soldier', 'Xbot']);
  check('empty pool stays empty', animatablePool([]), []);
  check('single deaf rig is better than none',
    animatablePool([robot]).map((m) => m.name), ['Robot']);
  const input = [soldier, robot];
  animatablePool(input).pop();
  check('the input pool is not mutated', input.map((m) => m.name), ['Soldier', 'Robot']);

  console.log(`\n${passed} ok, ${failed} failed`);
  process.exit(failed ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
