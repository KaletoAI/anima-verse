/**
 * Derivation moved to native/tests/Derivations/clip_order.md (E1, 2026-11-25).
 * Usage:  node client3d/scripts/smoke_clip_order.mjs
 * Runs until E3 deletes the browser scene; the C# vector tests keep executing the cases.
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
