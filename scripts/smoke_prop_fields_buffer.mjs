/** Behavioral prop draft regression. Run: node scripts/smoke_prop_fields_buffer.mjs */
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFile, mkdtemp, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const ts = require('typescript');
const dir = await mkdtemp(join(tmpdir(), 'prop-fields-'));
try {
  const source = await readFile(new URL('../frontend/src/tabs/props/pendingFields.ts', import.meta.url), 'utf8');
  const out = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 } });
  const file = join(dir, 'pendingFields.mjs');
  await writeFile(file, out.outputText);
  const { emptyFields, queueFields, variantTarget, GENERAL_TARGET, toBulkFieldBody,
    applyVariantDraft, dropDeletedVariant, pendingFieldCount, draftValue,
    fieldConflicts, dropPendingField } = await import(`file://${file}`);
  let draft = emptyFields();
  draft = queueFields(draft, variantTarget('uid-b'), { description: 'mine' });
  draft = queueFields(draft, variantTarget('uid-b'), { dims: { height_m: 4 }, action_bindings: [] });
  draft = queueFields(draft, GENERAL_TARGET, { actions: [], name: 'Bench' });
  assert.equal(pendingFieldCount(draft), 5);
  assert.equal(draftValue(draft, variantTarget('uid-b'), 'description', 'server'), 'mine');
  const row = (uid, index) => ({ uid, index, dims: { width_m: 2, depth_m: 2, height_m: 2 },
    dims_estimated: true, description: 'server', ground_offset_m: 0, markers: [], seasons: [] });
  const shown = applyVariantDraft([row('uid-b', 0), row('uid-c', 1)], draft);
  assert.equal(shown[0].description, 'mine');
  assert.equal(shown[0].dims.height_m, 4);
  assert.equal(shown[0].dims.width_m, 2);
  assert.equal(shown[1].description, 'server');
  draft = dropDeletedVariant(draft, 'uid-a');
  assert.deepEqual(toBulkFieldBody(draft, 'revision-1'), {
    base_revision: 'revision-1', actions: [], general: { name: 'Bench' },
    variants: { 'uid-b': { description: 'mine', dims: { height_m: 4 }, action_bindings: [] } },
  });
  draft = dropDeletedVariant(draft, 'uid-b');
  assert.equal(applyVariantDraft([row('uid-new', 0)], draft)[0].description, 'server');
  assert.deepEqual(toBulkFieldBody(emptyFields(), 'revision-2'), { base_revision: 'revision-2' });
  const base = new Map([
    [GENERAL_TARGET, { mount: { value: '', suggested: false }, name: 'Bench', actions: [] }],
    [variantTarget('uid-b'), { dims: row('uid-b', 0).dims, description: 'server', markers: [] }],
  ]);
  const filesOnly = new Map(base);
  draft = queueFields(emptyFields(), GENERAL_TARGET, { mount: 'wall' });
  draft = queueFields(draft, variantTarget('uid-b'), { description: 'mine', markers: [] });
  assert.deepEqual(fieldConflicts(draft, base, filesOnly), []);
  const classified = new Map(filesOnly);
  classified.set(GENERAL_TARGET, { ...base.get(GENERAL_TARGET), mount: { value: 'floor', suggested: true } });
  assert.deepEqual(fieldConflicts(draft, base, classified).map(({ target, field }) => [target, field]),
    [[GENERAL_TARGET, 'mount']]);
  assert.equal(draftValue(draft, GENERAL_TARGET, 'mount', ''), 'wall');
  const changedVariant = new Map(classified);
  changedVariant.set(variantTarget('uid-b'), { ...base.get(variantTarget('uid-b')), description: 'theirs' });
  assert.deepEqual(fieldConflicts(draft, base, changedVariant).map(({ field }) => field), ['mount', 'description']);
  const reordered = new Map([...base].reverse());
  assert.deepEqual(fieldConflicts(draft, base, reordered), []);
  const removed = new Map(base);
  removed.delete(variantTarget('uid-b'));
  assert.deepEqual(fieldConflicts(draft, base, removed).map(({ field, missing }) => [field, missing]),
    [['description', true], ['markers', true]]);
  draft = dropPendingField(draft, variantTarget('uid-b'), 'description');
  assert.deepEqual(toBulkFieldBody(draft, 'new-revision').variants, { 'uid-b': { markers: [] } });
  assert.equal(draftValue(draft, GENERAL_TARGET, 'mount', ''), 'wall');
  draft = dropPendingField(draft, variantTarget('uid-b'), 'markers');
  assert.equal(draft.has(variantTarget('uid-b')), false);
  const resized = new Map(base);
  resized.set(variantTarget('uid-b'), { ...base.get(variantTarget('uid-b')), dims: { width_m: 3, height_m: 3, depth_m: 3 } });
  const descriptionOnly = queueFields(emptyFields(), variantTarget('uid-b'), { description: 'mine' });
  assert.deepEqual(fieldConflicts(descriptionOnly, base, resized), []);
  const actionDraft = queueFields(emptyFields(), GENERAL_TARGET, { actions: [{ id: 'local' }] });
  const remoteActions = new Map(base);
  remoteActions.set(GENERAL_TARGET, { ...base.get(GENERAL_TARGET), actions: [{ id: 'remote' }] });
  assert.deepEqual(fieldConflicts(actionDraft, base, remoteActions).map(({ field, local, server }) => ({ field, local, server })),
    [{ field: 'actions', local: [{ id: 'local' }], server: [{ id: 'remote' }] }]);
  assert.deepEqual(toBulkFieldBody(actionDraft, 'accepted-revision').actions, [{ id: 'local' }]);
  console.log('PASS: merged fields, actions/bindings, stable UUIDs, disjoint rebase and explicit overlap resolution');
} finally { await rm(dir, { recursive: true, force: true }); }
