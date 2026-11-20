/** [1] Hand calculation: w1, w2, i1, h1 arrive i1, h1, w2, w1.
 * List order chooses w1 for walk/A, with loop=true. Losing w1 chooses w2
 * with loop=false. Pair roots and root-motion survive. The pair roots are
 * taken from the committed index (`pairRootsOf`), keyed by kind AND set: a
 * second handshake__a file in the same (neutral) set loses its slot AND its
 * root (h1 stays, not h2); the b-half stays independent. Missing results
 * leave gaps.
 * [2] Sets (2026-11-20 fix, client3d/scripts/smoke_pair_root_sets.mjs [A]):
 * hug__a in set "female" (f1), in "male" (m1), in "male" again (m2, loses:
 * first wins), hug__b in "" (n1), walk in "" (w1). Roots: hug__a/female =
 * root:f1, hug__a/male = root:m1. `pairRootFor` along a set chain (the
 * character's sets, then ""): [male, ""] → root:m1, [female, ""] → root:f1,
 * [elf, ""] → none (null: no neutral hug__a), hug__b with [male, ""] →
 * root:n1 (the neutral file).
 * [3] A solo kind (walk) has no pair-root entry.
 */
import { loadVectors, runVectors } from '../../shared/test-vectors/vectors.mjs';
import { readFile, writeFile, mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { transformSync } from 'esbuild';
const dir = await mkdtemp(join(tmpdir(), 'clip-order-'));
try {
  const source = await readFile(new URL('../src/game/clipCommit.ts', import.meta.url), 'utf8');
  const file = join(dir, 'clipCommit.mjs');
  await writeFile(file, transformSync(source, { loader: 'ts', format: 'esm' }).code);
  const { commitInListOrder, pairRootsOf, pairRootFor } = await import(`file://${file}`);
  const isPair = k => /__[ab]$/.test(k);
  const commit = (sources, results) => {
    const { index } = commitInListOrder(sources, results, {
      setFlags: (c, s) => { c.flags = { loop: s.loop, rootMotion: !!s.rootMotion }; },
      isPair, pairRoot: c => 'root:' + c.id,
      rename: (c, name) => ({ ...c, name }),
    });
    return { index, pairRoots: pairRootsOf(index, isPair, c => 'root:' + c.id) };
  };
  const { passed, failed } = runVectors(loadVectors('clip_commit'), {
    commitInListOrderValue: (sources, results, path) => {
      const out = commit(sources, results);
      if (path[0] === 'hasKind') return out.index.has(path[1]);
      if (path[0] === 'hasPairRoot') return out.pairRoots.has(path[1]);
      return path.reduce((value, key) => value instanceof Map ? value.get(key) : value[key], out);
    },
    pairRootForValue: (sources, results, kind, chain) => pairRootFor(commit(sources, results).pairRoots, kind, chain) ?? null,
  });
  console.log(`smoke_clip_order: ${passed} ok, ${failed} failed`);
  if (failed) process.exitCode = 1;
} finally { await rm(dir, { recursive: true, force: true }); }
