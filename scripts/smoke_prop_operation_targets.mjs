/** Async UID continuation and paid-generation targets; no server.
 * Expected by hand: selected UID B moves from index 1 to 0 after deletion;
 * no allocator is involved in regeneration. Only append adds one slot;
 * 2 active at cap 2, or any running job, admits zero new slots.
 */
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
  const { resolveVariantAfterBarrier, propGenerationTarget, propGenerationAuthor,
    propGenerationSubject, resolvePropRepairAfterBarrier } = await import(`file://${file}`);
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
    .then(row => writes.push(row.index), error => assert.match(error.message, /removed/));
  assert.deepEqual(writes, []);
  assert.equal(await resolveVariantAfterBarrier('B', async () => false, async () => { throw new Error('must not read'); }), null);
  const row = (uid, index, tiers = ['full']) => ({ uid, index, active: true, tiers });
  assert.deepEqual(propGenerationTarget([row('A', 0), row('B', 1, [])], 3),
    { kind: 'append', index: 2, sourceUid: 'A', sourceIndex: 0 });
  assert.throws(() => propGenerationTarget([row('A', 0), row('B', 1)], 2), /limit/);
  assert.throws(() => propGenerationTarget([row('A', 0)], 2, [0]), /running/);
  const priced = [{ ...row('A', 0), target_faces_high: 12000 },
    { ...row('B', 1), primary: true, target_faces_high: 34000, target_faces_low: 4000 }];
  const copiedAuthor = propGenerationAuthor(priced, propGenerationTarget(priced, 3));
  assert.equal(copiedAuthor.uid, 'B');
  assert.equal(copiedAuthor.target_faces_high, 34000);
  const selected = { kind: 'existing', uid: 'A', index: 0 };
  assert.equal(propGenerationAuthor(priced, selected).uid, 'A');
  assert.equal(priced.length, 2, 'regeneration changes no variant records');
  assert.equal(propGenerationSubject({ name: 'Saved new name' }, { description: '' }), 'Saved new name');
  assert.equal(propGenerationSubject({ name: 'Saved new name' }, { description: 'Specific variant' }), 'Specific variant');
  const repair = { op_id: 'paid-legacy', original_variant: 1, original_name: 'Old bench',
    backend: 'saved-mesh-backend', tier: 'full', reason: 'identity required', created_at: '2026-10-27T10:00:00Z',
    status: 'waiting_provider', mesh_ready: false, collected: false, can_resume: true };
  let repairSnapshot = { variants: [row('A', 0), row('B', 1)], revision: 'before-save',
    generating_variants: [], repairs: [repair] };
  let releaseRepair;
  let repairReads = 0;
  const repairBarrier = new Promise(resolve => { releaseRepair = resolve; });
  const repairDecision = resolvePropRepairAfterBarrier('paid-legacy', 'B', () => repairBarrier,
    async () => { repairReads++; return repairSnapshot; });
  assert.equal(repairReads, 0);
  repairSnapshot = { ...repairSnapshot, variants: [row('B', 0)], revision: 'saved-current-revision' };
  releaseRepair(true);
  const confirmedRepair = await repairDecision;
  assert.equal(confirmedRepair.target.index, 0);
  assert.equal(confirmedRepair.repair.status, 'waiting_provider');
  assert.deepEqual(confirmedRepair.body, {
    resume_op_id: 'paid-legacy', variant_uid: 'B', base_revision: 'saved-current-revision',
  });
  assert.equal(repairReads, 1);
  assert.equal(await resolvePropRepairAfterBarrier('paid-legacy', 'B', async () => false,
    async () => { throw new Error('cancelled authoring must not read or resume'); }), null);
  await assert.rejects(resolvePropRepairAfterBarrier('paid-legacy', 'B', async () => true,
    async () => ({ ...repairSnapshot, variants: [row('C', 0)] })), /removed/);
  await assert.rejects(resolvePropRepairAfterBarrier('paid-legacy', 'B', async () => true,
    async () => ({ ...repairSnapshot, generating_variants: [0] })), /generating/);
  await assert.rejects(resolvePropRepairAfterBarrier('paid-legacy', 'B', async () => true,
    async () => ({ ...repairSnapshot, repairs: [] })), /no longer/);
  await assert.rejects(resolvePropRepairAfterBarrier('paid-legacy', 'B', async () => true,
    async () => ({ ...repairSnapshot, repairs: [{ ...repair, can_resume: false }] })), /No.*job/i);
  console.log('PASS: UID-safe async continuation, removed/cancelled targets, generation cap and saved subjects');
} finally { await rm(dir, { recursive: true, force: true }); }
