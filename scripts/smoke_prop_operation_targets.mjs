/** Async UID continuation and paid-generation target regressions; no server. */
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFile, mkdtemp, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const ts = require('typescript');
const dir = await mkdtemp(join(tmpdir(), 'prop-operations-'));
try {
  const source = await readFile(new URL('../frontend/src/tabs/props/propOperations.ts', import.meta.url), 'utf8');
  const out = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 } });
  const file = join(dir, 'operations.mjs');
  await writeFile(file, out.outputText);
  const { resolveVariantAfterBarrier, propGenerationTarget, propGenerationSubject } = await import(`file://${file}`);
  let variants = [{ uid: 'A', index: 0 }, { uid: 'B', index: 1 }, { uid: 'C', index: 2 }];
  let release;
  const barrier = new Promise(resolve => { release = resolve; });
  let reads = 0;
  const target = resolveVariantAfterBarrier('B', () => barrier, async () => { reads++; return variants; });
  assert.equal(reads, 0);
  variants = [{ uid: 'B', index: 0 }, { uid: 'C', index: 1 }];
  release(true);
  assert.equal((await target).index, 0);
  assert.equal(reads, 1);
  const writes = [];
  await resolveVariantAfterBarrier('B', async () => true, async () => [{ uid: 'C', index: 0 }])
    .then(row => writes.push(row.index), error => assert.match(error.message, /entfernt/));
  assert.deepEqual(writes, []);
  assert.equal(await resolveVariantAfterBarrier('B', async () => false, async () => { throw new Error('must not read'); }), null);
  const row = (uid, index, tiers = ['full']) => ({ uid, index, active: true, tiers });
  assert.deepEqual(propGenerationTarget([row('A', 0), row('B', 1, [])], 2),
    { kind: 'existing', uid: 'B', index: 1, replaces: false });
  assert.deepEqual(propGenerationTarget([row('A', 0)], 2), { kind: 'append' });
  assert.deepEqual(propGenerationTarget([row('A', 0), row('B', 1)], 2),
    { kind: 'existing', uid: 'B', index: 1, replaces: true });
  assert.equal(propGenerationSubject({ name: 'Saved new name' }, { description: '' }), 'Saved new name');
  assert.equal(propGenerationSubject({ name: 'Saved new name' }, { description: 'Specific variant' }), 'Specific variant');
  console.log('PASS: UID-safe async continuation, removed/cancelled targets, generation cap and saved subjects');
} finally { await rm(dir, { recursive: true, force: true }); }
