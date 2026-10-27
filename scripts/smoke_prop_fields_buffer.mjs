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
    applyVariantDraft, dropDeletedVariant, pendingFieldCount, draftValue } = await import(`file://${file}`);
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
  console.log('PASS: merged fields, actions/bindings, revision and stable UID drafts');
} finally { await rm(dir, { recursive: true, force: true }); }
