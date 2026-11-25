#!/usr/bin/env node
/**
 * Derivation moved to native/tests/Derivations/clip_coverage.md (E1, 2026-11-25).
 * Usage:  node client3d/scripts/smoke_clip_coverage.mjs
 * Runs until E3 deletes the browser scene; the C# vector tests keep executing the cases.
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
