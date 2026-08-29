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
 * (1c) animFamily(kind) — the family of an animation kind
 * ---------------------------------------------------------------------------
 * Everything before the FIRST `-`, trimmed and lower-cased; an empty kind is
 * the idle family. The inner `_` is NOT a separator (the server's parser cuts
 * only a trailing `_<number>` take suffix), and a LEADING `-` separates
 * nothing — there is no motion in front of it, so the kind stays whole.
 *
 *   walk            -> walk        walk-cmu       -> walk
 *   run-fast        -> run         "  RUN  "      -> run
 *   swim-idle       -> swim        treading-water -> treading
 *   sit_a           -> sit_a       -cmu           -> -cmu
 *   ''              -> idle        undefined      -> idle
 *
 * WHY: the pose catalog renamed walking's kind `walk` → `walk-cmu` on
 * 2026-08-24. Every literal `'walk'` in the client stopped matching — the
 * procedural gait of a clip-less rig froze, the clip fallback dropped to idle
 * and room markers authored `walk` matched nothing. The family is the grouping
 * that survives a rename: the hyphen separates the motion from the SOURCE of
 * the take.
 *
 * ---------------------------------------------------------------------------
 * (1d) matchAnimKind(available, kind) — the exact kind, else a relative
 * ---------------------------------------------------------------------------
 * Exact wins; then the FAMILY BASE among the relatives; then the first listed
 * relative; `''` when nothing is of the sort. The entry comes back AS PASSED
 * IN, so the caller can look it up in its own map. It matches BOTH ways: a
 * wanted kind finds an older relative, and an older wanted kind finds a
 * renamed one.
 *
 * Only the FUNCTION is checked here. The room-marker call site in `main.ts`
 * that this once served is gone (places strand, task 13: the keyword
 * heuristic was removed), so nothing below greps `main.ts` for it any more —
 * `figures.ts` is the remaining consumer, and it is the one checked.
 *
 *   ([walk, idle], walk-cmu)                 -> walk        rename, rig side
 *   ([walk-cmu, idle], walk)                 -> walk-cmu    the other direction
 *   ([walk, walk-cmu], walk-cmu)             -> walk-cmu    exact beats the
 *                                                           relative listed first
 *   ([walk-mixamo, walk], walk-cmu)          -> walk        the family BASE
 *                                                           beats another take
 *   ([walk-mixamo, walk-cmu], walk)          -> walk-mixamo no base -> first
 *   ([" Walk "], walk-cmu)                   -> " Walk "    returned unchanged
 *   ([run, run-fast], run-fast)              -> run-fast
 *   ([idle-loop], idle)                      -> idle-loop
 *   ([idle, sit], walk-cmu)                  -> ''
 *   ([], walk) / ([walk], '')                -> ''
 *
 * ---------------------------------------------------------------------------
 * (1e) clipKindChain(kind) / resolveClipKind(kind, bound) — WHICH clip plays
 * ---------------------------------------------------------------------------
 * The chain is kind → its `CLIP_FALLBACK` stand-in → its FAMILY'S stand-in →
 * idle, blanks and duplicates dropped. The family of the kind is no step of
 * its own because every step is matched with `matchAnimKind`, which already
 * takes a relative once the exact kind is missing — that is what keeps the two
 * directions symmetric.
 *
 *   walk-cmu       -> [walk-cmu, idle]
 *   walk           -> [walk, idle]
 *   run            -> [run, walk, idle]              (fallback run -> walk)
 *   run-fast       -> [run-fast, walk, idle]         (via the FAMILY entry)
 *   swim-idle      -> [swim-idle, swim, walk, idle]  (own entry, then swim's)
 *   treading-water -> [treading-water, idle]         (own entry IS idle)
 *   lie            -> [lie, sit, idle]
 *   idle / ''      -> [idle]
 *
 * `resolveClipKind` walks that chain against the kinds a rig has bound:
 *
 *   (walk-cmu, [walk, idle])            -> walk       THE FINDING: the rig
 *                                                     keeps its old walk take
 *   (walk-cmu, [walk, walk-cmu, idle])  -> walk-cmu   exact stays preferred
 *   (walk, [walk-cmu, idle])            -> walk-cmu   and the other way round
 *   (walk-cmu, [idle])                  -> idle
 *   (walk-cmu, [sit])                   -> ''         nothing of the sort
 *   (run-fast, [run, walk, idle])       -> run        the run take, not walk
 *   (run-fast, [walk, idle])            -> walk       run's stand-in
 *   (run-fast, [walk-cmu, idle])        -> walk-cmu   stand-in via family
 *   (run, [walk, idle])                 -> walk
 *   (swim, [walk, idle])                -> walk       unchanged from before
 *   (swim-idle, [swim, walk])           -> swim       unchanged from before
 *   (treading-water, [walk, idle])      -> idle       the treader STANDS, it
 *                                                     does not walk on water
 *   (idle, [idle, walk])                -> idle       idle untouched
 *   (idle, [walk])                      -> ''         caller plays what it has
 *
 * ---------------------------------------------------------------------------
 * (1f) proceduralGait(kind) — what a CLIP-LESS rig has to fake
 * ---------------------------------------------------------------------------
 * `run` / `walk` by family, `null` for stand-and-breathe. A rig without clips
 * cannot fall back to anything, so a missed gait is a figure sliding across
 * the map stock still — precisely what `walk-cmu` did to it.
 *
 *   walk -> walk   walk-cmu -> walk   run -> run   run-fast -> run
 *   RUN  -> run    idle -> null       sit -> null  swim -> null
 *   ''   -> null   null -> null       walking -> null (a family of its own)
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
  const {
    missingClipKinds, animatablePool, resolveClipName,
    animFamily, matchAnimKind, clipKindChain, resolveClipKind, proceduralGait,
    CLIP_FALLBACK,
  } = await loadClipCoverage();

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

  console.log('animFamily — the family of a kind (first token before the `-`)');
  check('walk is its own family', animFamily('walk'), 'walk');
  check('THE RENAME: walk-cmu is a walk', animFamily('walk-cmu'), 'walk');
  check('run-fast is a run', animFamily('run-fast'), 'run');
  check('trimmed and lower-cased', animFamily('  RUN  '), 'run');
  check('swim-idle belongs to swim', animFamily('swim-idle'), 'swim');
  check('treading-water is its own thing', animFamily('treading-water'), 'treading');
  check('the inner underscore is no separator', animFamily('sit_a'), 'sit_a');
  check('an empty kind is idle', animFamily(''), 'idle');
  check('...and so is a missing one', animFamily(undefined), 'idle');
  check('a leading dash separates nothing', animFamily('-cmu'), '-cmu');

  console.log('matchAnimKind — exact, else the family, both ways');
  check('THE FINDING: a rig on walk serves a wanted walk-cmu',
    matchAnimKind(['walk', 'idle'], 'walk-cmu'), 'walk');
  check('...and a marker on walk-cmu serves a wanted walk',
    matchAnimKind(['walk-cmu', 'idle'], 'walk'), 'walk-cmu');
  check('the exact kind beats the relative listed first',
    matchAnimKind(['walk', 'walk-cmu'], 'walk-cmu'), 'walk-cmu');
  check('among relatives the family BASE wins',
    matchAnimKind(['walk-mixamo', 'walk'], 'walk-cmu'), 'walk');
  check('...and without a base the first listed one',
    matchAnimKind(['walk-mixamo', 'walk-cmu'], 'walk'), 'walk-mixamo');
  check('the entry comes back exactly as passed in',
    matchAnimKind([' Walk '], 'walk-cmu'), ' Walk ');
  check('run-fast takes itself', matchAnimKind(['run', 'run-fast'], 'run-fast'), 'run-fast');
  check('idle-loop stands in for idle', matchAnimKind(['idle-loop'], 'idle'), 'idle-loop');
  check('another family is no match', matchAnimKind(['idle', 'sit'], 'walk-cmu'), '');
  check('nothing available -> empty', matchAnimKind([], 'walk'), '');
  check('no kind wanted -> empty', matchAnimKind(['walk'], ''), '');
  // RED COUNTER-PROBE: the exact-only lookup this replaces — the rig with the
  // old walk take finds NOTHING for walk-cmu, which is the reported bug.
  const exactOnly = (available, kind) => available.find((n) => n === kind) ?? '';
  check('RED PROBE: exact-only lookup misses walk-cmu on a walk rig',
    exactOnly(['walk', 'idle'], 'walk-cmu'), '');

  console.log('clipKindChain — kind, its stand-in, its family\'s, idle');
  check('a renamed kind needs no stand-in of its own',
    clipKindChain('walk-cmu'), ['walk-cmu', 'idle']);
  check('walk likewise', clipKindChain('walk'), ['walk', 'idle']);
  check('run falls to walk', clipKindChain('run'), ['run', 'walk', 'idle']);
  check('run-fast reaches walk through the FAMILY entry',
    clipKindChain('run-fast'), ['run-fast', 'walk', 'idle']);
  check('swim-idle: own entry, then swim\'s',
    clipKindChain('swim-idle'), ['swim-idle', 'swim', 'walk', 'idle']);
  check('the treader stands rather than walks',
    clipKindChain('treading-water'), ['treading-water', 'idle']);
  check('lie sits down', clipKindChain('lie'), ['lie', 'sit', 'idle']);
  check('idle is the floor itself', clipKindChain('idle'), ['idle']);
  check('an empty kind is idle', clipKindChain(''), ['idle']);

  console.log('resolveClipKind — which kind a rig actually plays');
  check('THE FINDING: walk-cmu plays the rig\'s old walk take',
    resolveClipKind('walk-cmu', ['walk', 'idle']), 'walk');
  check('...and the exact take stays preferred where it exists',
    resolveClipKind('walk-cmu', ['walk', 'walk-cmu', 'idle']), 'walk-cmu');
  check('...and a wanted walk finds the walk-cmu take',
    resolveClipKind('walk', ['walk-cmu', 'idle']), 'walk-cmu');
  check('no gait at all -> idle', resolveClipKind('walk-cmu', ['idle']), 'idle');
  check('nothing of the sort -> empty', resolveClipKind('walk-cmu', ['sit']), '');
  check('run-fast takes the run take before the walk one',
    resolveClipKind('run-fast', ['run', 'walk', 'idle']), 'run');
  check('...and walks when there is no run take',
    resolveClipKind('run-fast', ['walk', 'idle']), 'walk');
  check('...even when the walk take carries the new name',
    resolveClipKind('run-fast', ['walk-cmu', 'idle']), 'walk-cmu');
  check('run -> walk, unchanged', resolveClipKind('run', ['walk', 'idle']), 'walk');
  check('swim -> walk, unchanged', resolveClipKind('swim', ['walk', 'idle']), 'walk');
  check('swim-idle -> swim, unchanged',
    resolveClipKind('swim-idle', ['swim', 'walk']), 'swim');
  check('treading-water stands, it does not walk on water',
    resolveClipKind('treading-water', ['walk', 'idle']), 'idle');
  check('idle is untouched', resolveClipKind('idle', ['idle', 'walk']), 'idle');
  check('...and a rig without any idle answers nothing',
    resolveClipKind('idle', ['walk']), '');
  // RED COUNTER-PROBE: the resolution before the family step — exact kind,
  // explicit stand-in, idle. It drops the walker to idle, statue-still.
  const preFix = (kind, bound) => {
    const fallback = CLIP_FALLBACK[kind];
    return [kind, fallback, 'idle'].find((k) => k && bound.includes(k)) ?? '';
  };
  check('RED PROBE: the pre-family chain drops walk-cmu to idle',
    preFix('walk-cmu', ['walk', 'idle']), 'idle');

  console.log('proceduralGait — the gait a clip-less rig fakes');
  check('walk', proceduralGait('walk'), 'walk');
  check('THE GATE FIRES for walk-cmu (the static-rig finding)',
    proceduralGait('walk-cmu'), 'walk');
  check('run', proceduralGait('run'), 'run');
  check('run-fast is still a run', proceduralGait('run-fast'), 'run');
  check('case does not matter', proceduralGait('RUN'), 'run');
  check('idle stands', proceduralGait('idle'), null);
  check('sit stands', proceduralGait('sit'), null);
  check('swim stands (no gait for a stroke)', proceduralGait('swim'), null);
  check('no kind stands', proceduralGait(''), null);
  check('null stands', proceduralGait(null), null);
  check('`walking` is a family of its own, as it always was',
    proceduralGait('walking'), null);
  // RED COUNTER-PROBE: the literal gate this replaces.
  const literalGate = (k) => (k === 'walk' || k === 'run' ? k : null);
  check('RED PROBE: the literal gate misses walk-cmu', literalGate('walk-cmu'), null);

  console.log('the rules are WIRED at their consumers');
  const figures = await readFile(join(ROOT, 'client3d/src/scene/figures.ts'), 'utf8');
  check('figures.play resolves through resolveClipKind',
    /resolveClipKind\(kind,/.test(figures), true);
  check('the procedural gait gate asks proceduralGait',
    /proceduralGait\(this\.currentKind\)/.test(figures), true);
  check('...and no literal kind comparison is left in figures.ts',
    !/currentKind === '(walk|run)'/.test(figures), true);

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
