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
 * (1b) resolveClipName(names, needles) — WHICH clip stands in for a kind
 * ---------------------------------------------------------------------------
 * The alias layer of `Figure` (`CLIP_SYNONYMS`), as a rule: the needles rank,
 * and INSIDE one needle the exact name beats a name that merely contains it.
 * `''` when nothing stands in.
 *
 * The exact step is the fix of 2026-08-13: a clip kind is the whole file name
 * now, so `swim-idle` and `treading-water` are kinds of their own — and a
 * substring-only rule would hand a needle `swim` the clip `swim-idle` whenever
 * that one is listed first, i.e. a swimmer treading water on the spot.
 *
 *   ([swim-idle, swim], [swim])            -> swim        exact beats substring
 *                                                         though swim-idle is
 *                                                         listed first
 *   ([swim-idle], [swim])                  -> swim-idle   the substring step
 *                                                         still reaches (this
 *                                                         is `walk`→`walking`)
 *   ([walk, walking], [walk])              -> walk
 *   ([walking], [walk])                    -> walking
 *   ([laying, sleep], [lie, lay, sleep])   -> laying      needle 2 hits before
 *                                                         needle 3 is asked —
 *                                                         `sleep` was animated
 *                                                         on a bed
 *   ([sleep, lie-down], [lie, lay, sleep]) -> lie-down    the FIRST needle
 *                                                         already has a
 *                                                         substring hit
 *   ([" Idle ", walk], [idle])             -> idle        trimmed + lower-cased
 *   ([walk], [idle, stand])                -> ''          nothing stands in
 *   ([], [idle])                           -> ''
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
  const { missingClipKinds, animatablePool, resolveClipName } = await loadClipCoverage();

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

  console.log('resolveClipName — exact before substring');
  check('a needle takes its OWN clip, not the longer kind listed first',
    resolveClipName(['swim-idle', 'swim'], ['swim']), 'swim');
  check('...and the substring pass still reaches when there is no exact one',
    resolveClipName(['swim-idle'], ['swim']), 'swim-idle');
  check('walk beats walking', resolveClipName(['walk', 'walking'], ['walk']), 'walk');
  check('walking still stands in for walk',
    resolveClipName(['walking'], ['walk']), 'walking');
  check('the needle order ranks: `laying` before the exactly-named `sleep`',
    resolveClipName(['laying', 'sleep'], ['lie', 'lay', 'sleep']), 'laying');
  check('...and a substring hit on the FIRST needle ends it',
    resolveClipName(['sleep', 'lie-down'], ['lie', 'lay', 'sleep']), 'lie-down');
  check('names are trimmed and lower-cased',
    resolveClipName([' Idle ', 'walk'], ['idle']), 'idle');
  check('nothing stands in -> empty', resolveClipName(['walk'], ['idle', 'stand']), '');
  check('no clips at all -> empty', resolveClipName([], ['idle']), '');
  // RED COUNTER-PROBE: the substring-only rule this replaces. It must DISAGREE
  // on the swim case — otherwise the exact pass proves nothing.
  const substringOnly = (names, needles) => {
    for (const needle of needles) {
      const hit = names.find((n) => n.includes(needle));
      if (hit) return hit;
    }
    return '';
  };
  check('RED PROBE: substring-only would hand `swim` the swim-idle clip',
    substringOnly(['swim-idle', 'swim'], ['swim']), 'swim-idle');

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
