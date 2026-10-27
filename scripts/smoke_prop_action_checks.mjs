/** Real configuration-check composition and request/snapshot ownership, without a backend or UI runner. */
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFile, writeFile, mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const ts = require('typescript');
const root = fileURLToPath(new URL('..', import.meta.url));
const dir = await mkdtemp(join(tmpdir(), 'prop-action-checks-'));
try {
  for (const name of ['propActionAuthoring', 'propActionChecks', 'pendingFields']) {
    const source = await readFile(join(root, 'frontend/src/tabs/props', name + '.ts'), 'utf8');
    await writeFile(join(dir, name + '.js'), ts.transpileModule(source, {
      compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
    }).outputText);
  }
  const { composePropConfigurationResult, samePropConfigurationSnapshot,
    isCurrentPropConfigurationRequest, resolveCheckIssue } = require(join(dir, 'propActionChecks.js'));
  const catalog = { status: 'ready', stats: ['energy'], conditions: [], groups: {},
    poses: [{ key: 'sitting', group: 'seat', solo: true, animation: 'sit' }],
    kinds: ['sit'], pairKinds: [] };
  const action = { id: 'rest', name: 'Rest', description: '', enabled: true,
    ability: 'pose', pose_key: '', participants: 1, presence: 'any',
    interrupt_on_presence_change: false, phases: [], requirements: [], effects: [] };
  const blank = { actions: [action], model_variants: [] };
  const accepted = { valid: true, placement: 'not_checked', issues: [] };
  const blocked = composePropConfigurationResult(blank, catalog, accepted);
  assert.equal(blocked.valid, false);
  const poseIssue = blocked.issues.find(issue => issue.path === 'actions.0.pose_key');
  assert.equal(poseIssue?.severity, 'error');
  assert.equal(poseIssue?.code, 'unsupported_pose_capability');
  assert.deepEqual(resolveCheckIssue(poseIssue, blank), { actionId: 'rest', field: 'pose_key' });
  assert.equal(blank.actions[0].pose_key, '');
  assert.deepEqual(accepted.issues, []);

  const document = { ...blank, actions: [{ ...action, pose_key: 'sitting' }] };
  assert.equal(composePropConfigurationResult(document, catalog, accepted).valid, true);
  const warning = { path: 'model_variants', code: 'no_variants', message: 'No variants', severity: 'warning' };
  const warned = composePropConfigurationResult(document, catalog, { ...accepted, issues: [warning] });
  assert.equal(warned.valid, true);
  assert.deepEqual(warned.issues, [warning]);
  const serverError = { path: 'model_variants.0.action_bindings', code: 'invalid_binding',
    message: 'Binding must be repaired', severity: 'error' };
  const invalid = composePropConfigurationResult(document, catalog, { ...accepted, issues: [serverError] });
  assert.equal(invalid.valid, false);
  assert.deepEqual(invalid.issues, [serverError]);
  assert.equal(composePropConfigurationResult(document, catalog, { ...accepted, valid: false }).valid, false);
  const duplicate = { ...poseIssue, message: 'Server pose diagnostic' };
  const deduplicated = composePropConfigurationResult(blank, catalog, { ...accepted, issues: [duplicate, serverError] });
  assert.equal(deduplicated.issues.filter(issue => issue.path === poseIssue.path && issue.code === poseIssue.code).length, 1);
  assert(deduplicated.issues.includes(duplicate));
  assert(deduplicated.issues.includes(serverError));
  const promoted = composePropConfigurationResult(blank, catalog, {
    ...accepted, issues: [{ ...duplicate, severity: 'warning' }],
  });
  assert.equal(promoted.valid, false);
  assert.equal(promoted.issues.find(issue => issue.path === poseIssue.path)?.severity, 'error');
  const unknown = { ...document, actions: [{ ...document.actions[0], pose_key: 'removed_pose' }] };
  assert.equal(composePropConfigurationResult(unknown, catalog, accepted).valid, false);
  assert.equal(unknown.actions[0].pose_key, 'removed_pose');
  assert.equal(composePropConfigurationResult(document, { ...catalog, status: 'loading' }, accepted).valid, false);
  const combined = { ...document, actions: [{ ...document.actions[0], ability: 'combined', phases: [
    { id: 'prepare', label: 'Prepare', duration_game_s: 120, pose_key: 'sitting' },
    { id: 'drink', label: 'Drink', duration_game_s: 180, pose_key: '' },
  ] }] };
  const phaseBlocked = composePropConfigurationResult(combined, catalog, accepted);
  assert.equal(phaseBlocked.valid, false);
  assert(phaseBlocked.issues.some(issue => issue.path === 'actions.0.phases.1.pose_key' && issue.severity === 'error'));

  const snapshot = { propId: 'chair', revision: 'r1', document, catalog, revisionReady: true };
  assert(samePropConfigurationSnapshot(snapshot, { ...snapshot }));
  const changes = [
    ['draft', { ...snapshot, document: blank }],
    ['prop', { ...snapshot, propId: 'other-chair' }],
    ['revision', { ...snapshot, revision: 'r2' }],
    ['catalog', { ...snapshot, catalog: { ...catalog, poses: [] } }],
    ['revision readiness', { ...snapshot, revisionReady: false }],
  ];
  const firstRequest = { snapshot, sequence: 1 };
  for (const [name, changed] of changes) {
    assert.equal(samePropConfigurationSnapshot(snapshot, changed), false, name);
    assert.equal(isCurrentPropConfigurationRequest(firstRequest,
      { snapshot: changed, sequence: 2 }), false, name);
  }
  const retried = { snapshot, sequence: 2 };
  assert.equal(isCurrentPropConfigurationRequest(firstRequest, retried), false);
  assert.equal(isCurrentPropConfigurationRequest(retried, retried), true);
  // Returning to the same document never restores an obsolete request's authority.
  const returned = { snapshot, sequence: 3 };
  assert.equal(isCurrentPropConfigurationRequest(firstRequest, returned), false);
  console.log('PASS: configuration blockers, retained diagnostics and exact-snapshot request ownership');
} finally { await rm(dir, { recursive: true, force: true }); }
