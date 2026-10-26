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
 * instead of swimming. The rule chain (terrain `movement: swim` → payload →
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
 * (1g) FIXED MOVEMENT POSES (design §5.3)
 * The server delivers played/public kinds for each fixed pose. With walking
 * mob1-walk/walk and standing mob1-stand-relaxed-idle-v2/idle, the ordered
 * chain is [mob1-walk, walk, mob1-stand-relaxed-idle-v2, idle]: no explicit
 * fallback for either walk kind or the mob1 family, then the two standing
 * kinds, with the trailing duplicate idle removed. Thus a free rig walks.
 * For crawl-rest the explicit fallback idle is second. Procedural rigs use
 * the walking/running pose, then family. No locomotion role mapping remains.
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
import { loadVectors, runVectors } from '../../shared/test-vectors/vectors.mjs';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');
const SRC = join(ROOT, 'client3d/src/scene/clipCoverage.ts');
const WALK_SRC = join(ROOT, 'client3d/src/game/walk.ts');

/** `clipCoverage.ts` imports exactly ONE module — `game/walk.ts`, for the
 *  movement pose mapping (1g) — and that one is import-free itself, so a plain
 *  esbuild transpile of the pair loads them here; only the file extension has
 *  to be fixed up for Node's ESM loader, as in `smoke_walk_math.mjs`. No
 *  bundler, and above all no `three`: that the import list stays this short is
 *  checked below, and anything else makes this loader fail loudly — the module
 *  holds the bookkeeping, `figures.ts` holds the skeleton maths.
 *
 *  `setMovementPoses` comes back alongside, from the SAME instance of
 *  `walk.mjs` the coverage module reads (Node caches by URL), so the checks
 *  can put the admin's mapping in force. */
async function loadClipCoverage() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'clipcov-'));
  try {
    const walkSource = await readFile(WALK_SRC, 'utf8');
    const walkOut = esbuild.transformSync(walkSource, { loader: 'ts', format: 'esm' });
    const walkFile = join(dir, 'walk.mjs');
    await writeFile(walkFile, walkOut.code, 'utf8');
    const source = await readFile(SRC, 'utf8');
    const out = esbuild.transformSync(source, { loader: 'ts', format: 'esm' });
    const file = join(dir, 'clipCoverage.mjs');
    await writeFile(file, out.code.replace(/(from\s*["'])\.\.\/game\/walk(["'])/g,
      '$1./walk.mjs$2'), 'utf8');
    const coverage = await import(`file://${file}`);
    const walk = await import(`file://${walkFile}`);
    return { ...coverage, setMovementPoses: walk.setMovementPoses, movementPoseOf: walk.movementPoseOf };
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
    movementPoseOf, setMovementPoses, CLIP_FALLBACK,
  } = await loadClipCoverage();

  const vectors = runVectors(loadVectors('clip_coverage'), {
    missingClipKinds, resolveClipName, matchAnimKind, clipKindChain,
    resolveClipKind, proceduralGait,
    // JSON null represents the original omitted/undefined family argument.
    animFamily: kind => animFamily(kind ?? undefined),
    animatablePool: pool => animatablePool(pool).map(m => m.name),
  });
  passed += vectors.passed; failed += vectors.failed;
  console.log('missingClipKinds — the kinds a rig cannot play');

  console.log('resolveClipName — exact before substring');

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

  console.log('matchAnimKind — exact, else the family, both ways');

  // RED COUNTER-PROBE: the exact-only lookup this replaces — the rig with the
  // old walk take finds NOTHING for walk-cmu, which is the reported bug.
  const exactOnly = (available, kind) => available.find((n) => n === kind) ?? '';
  check('RED PROBE: exact-only lookup misses walk-cmu on a walk rig',
    exactOnly(['walk', 'idle'], 'walk-cmu'), '');

  console.log('clipKindChain — kind, its stand-in, its family\'s, idle');

  console.log('resolveClipKind — which kind a rig actually plays');

  // RED COUNTER-PROBE: the resolution before the family step — exact kind,
  // explicit stand-in, idle. It drops the walker to idle, statue-still.
  const preFix = (kind, bound) => {
    const fallback = CLIP_FALLBACK[kind];
    return [kind, fallback, 'idle'].find((k) => k && bound.includes(k)) ?? '';
  };
  check('RED PROBE: the pre-family chain drops walk-cmu to idle',
    preFix('walk-cmu', ['walk', 'idle']), 'idle');

  console.log('proceduralGait — the gait a clip-less rig fakes');

  // RED COUNTER-PROBE: the literal gate this replaces.
  const literalGate = (k) => (k === 'walk' || k === 'run' ? k : null);
  check('RED PROBE: the literal gate misses walk-cmu', literalGate('walk-cmu'), null);

  // Spec §5.3: want, public pose, stand-ins, standing pose, idle.
  console.log('movement pose public fallback (1g)');
  setMovementPoses({walking: {kind: 'mob1-walk', public_kind: 'walk'},
    running: {kind: 'mob1-jog', public_kind: 'run'},
    standing: {kind: 'mob1-stand-relaxed-idle-v2', public_kind: 'idle'}});

  check('crawl rest starts with idle', clipKindChain('crawl-rest').slice(0, 2), ['crawl-rest', 'idle']);

  setMovementPoses({crawling: {kind: 'missing-crawl', public_kind: 'crawl'},
    crawling_rest: {kind: 'missing-rest', public_kind: 'crawl-rest'}});

  setMovementPoses({});

  console.log('the rules are WIRED at their consumers');
  const coverageSrc = await readFile(SRC, 'utf8');
  const imports = [...coverageSrc.matchAll(/^import[^;]*?from\s*['"]([^'"]+)['"]/gm)]
    .map((m) => m[1]);
  check('clipCoverage.ts imports the movement pose mapping and NOTHING else',
    [...new Set(imports)], ['../game/walk']);
  const walkSrc = await readFile(WALK_SRC, 'utf8');
  check('...and walk.ts stays import-free, so there is no cycle',
    /^import\s/m.test(walkSrc), false);
  const figures = await readFile(join(ROOT, 'client3d/src/scene/figures.ts'), 'utf8');
  check('figure loader takes server movement poses', /setMovementPoses\(library\.movement_poses\)/.test(figures), true);
  check('figure loader takes clip-keyed transitions', /setClipTransitions\(library\.transition_clips\)/.test(figures), true);
  check('figures.play resolves through resolveClipKind',
    /resolveClipKind\(kind,/.test(figures), true);
  check('the procedural gait gate asks proceduralGait',
    /proceduralGait\(this\.currentKind\)/.test(figures), true);
  check('...and no literal kind comparison is left in figures.ts',
    !/currentKind === '(walk|run)'/.test(figures), true);

  console.log('animatablePool — the rigs a character may be drawn from');
  const soldier = { name: 'Soldier', libraryFits: true };
  const robot = { name: 'Robot', libraryFits: false };

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
