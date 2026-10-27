/** Real authoring boundaries: executable presets, independent identity and illegal effect timing. */
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFile, writeFile, mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const ts = require('typescript');
const root = fileURLToPath(new URL('..', import.meta.url));
const dir = await mkdtemp(join(tmpdir(), 'prop-action-authoring-'));
try {
  for (const name of ['propActionAuthoring', 'propActionChecks', 'pendingFields']) {
    const source = await readFile(join(root, 'frontend/src/tabs/props', name + '.ts'), 'utf8');
    await writeFile(join(dir, name + '.js'), ts.transpileModule(source, {
      compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
    }).outputText);
  }
  const { createActionPreset, copyAction, actionEditorIssues, effectTimings, presentations } = require(join(dir, 'propActionAuthoring.js'));
  const { propActionCheckDocument, resolveCheckIssue } = require(join(dir, 'propActionChecks.js'));
  const { emptyFields, queueFields, applyVariantDraft } = require(join(dir, 'pendingFields.js'));
  const catalog = { status: 'ready', stats: ['energy'], conditions: [{ name: 'alert', label: 'Alert' }],
    poses: [{ key: 'sitting', group: 'seat', solo: true, animation: 'sit' },
      { key: 'lying', group: 'lie', solo: true, animation: 'lie' },
      { key: 'embracing', group: 'seat', solo: false, animation: 'embrace' },
      { key: 'fake_pair', group: 'seat', solo: false, animation: 'missing_pair' }],
    kinds: ['sit', 'lie'], pairKinds: ['embrace'] };
  assert.deepEqual(presentations(catalog, 'pair').map(p => p.key), ['embracing']);
  const coffee = createActionPreset('coffee', catalog);
  assert.equal(coffee.ability, 'combined');
  assert.equal(coffee.phases.length, 2);
  assert.equal(new Set(coffee.phases.map(p => p.id)).size, 2);
  assert(coffee.phases.every(p => p.duration_game_s > 0 && p.pose_key === 'sitting'));
  coffee.effects.push({ id: 'effect', type: 'stat_delta', target: 'actor', when: 'success', stat: 'energy', amount: 15 });
  coffee.requirements.push({ id: 'requirement', type: 'condition', target: 'actor', condition_id: 'alert', present: false });
  const copied = copyAction(coffee);
  assert.notEqual(copied.id, coffee.id);
  assert.notEqual(copied.effects[0].id, coffee.effects[0].id);
  assert.notEqual(copied.requirements[0].id, coffee.requirements[0].id);
  assert.notEqual(copied.phases[0].id, coffee.phases[0].id);
  copied.effects[0].amount = 99;
  assert.equal(coffee.effects[0].amount, 15);
  assert.deepEqual(actionEditorIssues([coffee], catalog), []);
  coffee.effects[0].stat = 'unknown';
  assert(actionEditorIssues([coffee], catalog).some(i => i.path === 'actions.0.effects.0.stat'));
  assert.equal(coffee.effects[0].stat, 'unknown');
  const relax = createActionPreset('sit', catalog);
  relax.effects = [{ id: 'reward', type: 'stat_delta', target: 'actor', when: 'success', stat: 'energy', amount: 5 }];
  assert(!effectTimings(relax, 'stat_delta').includes('success'));
  assert(actionEditorIssues([relax], catalog).some(i => i.code === 'unsupported_combination'));
  const sleep = createActionPreset('sleep', catalog);
  assert.equal(sleep.ability, 'sleep');
  assert(!effectTimings(sleep, 'stat_delta').includes('active'));
  const pair = createActionPreset('pair', catalog);
  assert.equal(pair.participants, 2);
  assert.equal(pair.pose_key, 'embracing');
  const savedVariants = [
    { uid: 'B', index: 4, stem: 'b', active: true, seasons: [], dims: { width_m: 2, depth_m: 3, height_m: 4 }, markers: [], action_bindings: [] },
    { uid: 'A', index: 0, stem: 'a', active: false, seasons: [], dims: { width_m: 1, depth_m: 1, height_m: 1 }, markers: [], action_bindings: [] },
  ];
  let draft = queueFields(emptyFields(), 'general', { name: 'Unsaved name', tags: 'a, b', mount: { value: 'floor', suggested: false }, actions: [coffee] });
  draft = queueFields(draft, 'v:A', { dims: { width_m: 9 }, action_bindings: [{ action_id: coffee.id, variant_uid: 'A', supported: false, marker_ids: [], access_points: {}, validation: 'repair_required' }] });
  const prop = { name: 'Saved', category: 'test', tags: [], actions: [] };
  const document = propActionCheckDocument(prop, applyVariantDraft(savedVariants, draft), draft);
  assert.equal(document.name, 'Unsaved name');
  assert.equal(document.mount, 'floor');
  assert.deepEqual(document.tags, ['a', 'b']);
  assert.deepEqual(document.model_variants.map(v => v.uid), ['B', 'A']);
  assert.equal(document.model_variants[1].width_m, 9);
  assert.equal(document.model_variants[1].depth_m, 1);
  assert(!('dims' in document.model_variants[1]));
  assert.equal(document.actions[0].effects[0].stat, 'unknown');
  assert.equal(savedVariants[1].dims.width_m, 1);
  assert.deepEqual(resolveCheckIssue({ path: 'model_variants.1.action_bindings.0.access_points.actor.x' }, document),
    { variantUid: 'A', actionId: coffee.id, field: 'action_bindings.0.access_points.actor.x' });
  console.log('PASS: executable presets, immutable copy, unknown-ref repair and semantic timing');
} finally { await rm(dir, { recursive: true, force: true }); }
