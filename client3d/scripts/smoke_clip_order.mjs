/** [1] Hand calculation: w1, w2, i1, h1 arrive i1, h1, w2, w1.
 * List order chooses w1 for walk/A, with loop=true. Losing w1 chooses w2
 * with loop=false. Pair roots and root-motion survive. A second a-half
 * replaces its root, but its first clip wins; the b-half stays independent.
 * Missing results leave gaps.
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
  const { commitInListOrder } = await import(`file://${file}`);
  const { passed, failed } = runVectors(loadVectors('clip_commit'), {
    commitInListOrderValue: (sources, results, path) => {
      const out = commitInListOrder(sources, results, {
        setFlags: (c, s) => { c.flags = { loop: s.loop, rootMotion: !!s.rootMotion }; },
        isPair: k => /__[ab]$/.test(k), pairRoot: c => 'root:' + c.id,
        rename: (c, name) => ({ ...c, name }),
      });
      if (path[0] === 'hasKind') return out.index.has(path[1]);
      return path.reduce((value, key) => value instanceof Map ? value.get(key) : value[key], out);
    },
  });
  console.log(`smoke_clip_order: ${passed} ok, ${failed} failed`);
  if (failed) process.exitCode = 1;
} finally { await rm(dir, { recursive: true, force: true }); }
