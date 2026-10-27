/** Real change/change/blur resize arithmetic and before-blur author conflicts. */
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFile, writeFile, mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const ts = require('typescript');
const root = fileURLToPath(new URL('..', import.meta.url));
const dir = await mkdtemp(join(tmpdir(), 'prop-dimension-gesture-'));
try {
  for (const name of ['dims', 'dimensionGesture', 'pendingFields']) {
    const source = await readFile(join(root, 'frontend/src/tabs/props', name + '.ts'), 'utf8');
    const out = ts.transpileModule(source, {
      compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
    });
    await writeFile(join(dir, name + '.js'), out.outputText);
  }
  const { editDimensionGesture, dimsPatch, dimRatios } = require(join(dir, 'dimensionGesture.js'));
  const { emptyFields, queueFields, variantTarget, fieldConflicts, toBulkFieldBody } = require(join(dir, 'pendingFields.js'));
  const original = { width_m: 20, depth_m: 0.01, height_m: 20 };
  const target = variantTarget('meshless-B');
  const base = new Map([[target, { dims: original }]]);
  const remote = new Map([[target, { dims: { width_m: 8, depth_m: 0.004, height_m: 8 } }]]);
  let draft = emptyFields();
  let edit = editDimensionGesture(null, 'meshless-B', original, 'width_m', '', null);
  assert.equal(edit.dims, original);
  draft = queueFields(draft, target, { dims: edit.dims });
  assert.deepEqual(fieldConflicts(draft, base, remote).map(({ field }) => field), ['dims']);
  edit = editDimensionGesture(edit.gesture, 'meshless-B', edit.dims, 'width_m', '1', null);
  assert.deepEqual(edit.dims, { width_m: 1, depth_m: 0.001, height_m: 1 });
  draft = queueFields(draft, target, { dims: edit.dims });
  assert.deepEqual(fieldConflicts(draft, base, remote).map(({ field }) => field), ['dims']);
  edit = editDimensionGesture(edit.gesture, 'meshless-B', edit.dims, 'width_m', '10', null);
  const expected = { width_m: 10, depth_m: 0.005, height_m: 10 };
  assert.deepEqual(edit.dims, expected);
  assert.deepEqual(edit.dims, dimsPatch(original, 'width_m', '10', dimRatios(original, null)));
  const blur = editDimensionGesture(edit.gesture, 'meshless-B', edit.dims, 'width_m', '10', null);
  assert.deepEqual(blur.dims, expected);
  draft = queueFields(draft, target, { dims: blur.dims });
  assert.deepEqual(toBulkFieldBody(draft, 'initial-revision').variants['meshless-B'].dims, expected);
  // A late mesh measurement must not change an already active gesture's aspect.
  assert.deepEqual(editDimensionGesture(edit.gesture, 'meshless-B', edit.dims,
    'width_m', '10', [1, 1, 1]).dims, expected);
  const other = { width_m: 4, depth_m: 2, height_m: 1 };
  assert.deepEqual(editDimensionGesture(edit.gesture, 'other-UID', other,
    'width_m', '2', null).dims, { width_m: 2, depth_m: 1, height_m: 0.5 });
  console.log('PASS: multi-keystroke equals one-step resize; blur, UID reset and before-blur conflict retention');
} finally { await rm(dir, { recursive: true, force: true }); }
