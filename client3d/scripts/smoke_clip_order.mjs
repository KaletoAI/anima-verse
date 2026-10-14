/** Hand calculation: w1, w2, i1, h1 arrive i1, h1, w2, w1.
 * List order chooses w1 for walk/A, with loop=true. Losing w1 chooses w2
 * with loop=false. Pair roots and root-motion survive. A second a-half
 * replaces its root, but its first clip wins; the b-half stays independent.
 * Missing results leave gaps.
 */
import assert from 'node:assert/strict';
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
  const sources = [
    { kind: 'walk', set: 'A', url: 'w1', loop: true },
    { kind: 'walk', set: 'A', url: 'w2', loop: false },
    { kind: 'idle', set: 'B', url: 'i1' },
    { kind: 'handshake__a', set: '', url: 'h1', rootMotion: true },
  ];
  const ops = {
    setFlags: (c, s) => { c.flags = { loop: s.loop, rootMotion: !!s.rootMotion }; },
    isPair: k => /__[ab]$/.test(k), pairRoot: c => 'root:' + c.id,
    rename: (c, name) => ({ ...c, name }),
  };
  const results = [];
  for (const i of [2, 3, 1, 0]) results[i] = { clip: { id: sources[i].url } };
  let out = commitInListOrder(sources, results, ops);
  assert.equal(out.index.get('walk').get('A').id, 'w1');
  assert.equal(out.index.get('walk').get('A').flags.loop, true);
  assert.equal(out.index.get('idle').get('B').name, 'idle');
  assert.equal(out.pairRoots.get('handshake__a'), 'root:h1');
  assert.equal(out.index.get('handshake__a').get('').flags.rootMotion, true);
  out = commitInListOrder(sources, [{ clip: null }, ...results.slice(1)], ops);
  assert.equal(out.index.get('walk').get('A').id, 'w2');
  assert.equal(out.index.get('walk').get('A').flags.loop, false);
  out = commitInListOrder([...sources,
    { kind: 'handshake__a', set: '', url: 'h2' },
    { kind: 'handshake__b', set: '', url: 'h3' },
    { kind: 'missing', set: '', url: 'gone' },
  ], [...results, { clip: { id: 'h2' } }, { clip: { id: 'h3' } }], ops);
  assert.equal(out.index.get('handshake__a').get('').id, 'h1');
  assert.equal(out.pairRoots.get('handshake__a'), 'root:h2');
  assert.equal(out.pairRoots.get('handshake__b'), 'root:h3');
  assert.equal(out.index.has('missing'), false);
  console.log('smoke_clip_order: OK');
} finally { await rm(dir, { recursive: true, force: true }); }
