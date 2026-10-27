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
  function deferred() {
    let resolve, reject;
    const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
    return { promise, resolve, reject };
  }
  function checks(initial) {
    let current = { snapshot: initial, sequence: 0 };
    let result = null, error = null, pending = null;
    return {
      change(next) {
        if (!samePropConfigurationSnapshot(current.snapshot, next)) {
          current = { snapshot: next, sequence: current.sequence + 1 };
        }
      },
      async validate(response) {
        const checked = { snapshot: current.snapshot, sequence: current.sequence + 1 };
        current = checked; pending = checked; error = null;
        try {
          const server = await response;
          if (isCurrentPropConfigurationRequest(checked, current)) {
            result = { snapshot: checked.snapshot,
              value: composePropConfigurationResult(checked.snapshot.document, checked.snapshot.catalog, server) };
          }
        } catch (failure) {
          if (isCurrentPropConfigurationRequest(checked, current)) error = { snapshot: checked.snapshot, value: failure };
        } finally {
          if (isCurrentPropConfigurationRequest(checked, current)) pending = null;
        }
      },
      get result() { return result && samePropConfigurationSnapshot(result.snapshot, current.snapshot) ? result.value : null; },
      get stale() { return !!result && !samePropConfigurationSnapshot(result.snapshot, current.snapshot); },
      get error() { return error && samePropConfigurationSnapshot(error.snapshot, current.snapshot) ? error.value : null; },
      get pending() { return !!pending && isCurrentPropConfigurationRequest(pending, current); },
    };
  }
  for (const [name, changed] of changes) {
    assert.equal(samePropConfigurationSnapshot(snapshot, changed), false, name);
    const state = checks(snapshot);
    await state.validate(Promise.resolve(accepted));
    assert.equal(state.result.valid, true, name);
    const delayed = deferred();
    const old = state.validate(delayed.promise);
    state.change(changed);
    assert.equal(state.result, null, name);
    assert.equal(state.stale, true, name);
    assert.equal(state.pending, false, name);
    delayed.resolve(accepted);
    await old;
    assert.equal(state.result, null, name);
    assert.equal(state.stale, true, name);

    const failed = deferred();
    const failingState = checks(snapshot);
    const oldFailure = failingState.validate(failed.promise);
    failingState.change(changed);
    const newer = deferred();
    const newRequest = failingState.validate(newer.promise);
    failed.reject(new Error('Obsolete response'));
    await oldFailure;
    assert.equal(failingState.error, null, name);
    assert.equal(failingState.pending, true, name);
    newer.resolve(accepted);
    await newRequest;
    assert.equal(failingState.pending, false, name);
  }
  for (const rejectOlder of [false, true]) {
    const state = checks(snapshot);
    const older = deferred(), newer = deferred();
    const oldRequest = state.validate(older.promise);
    const newRequest = state.validate(newer.promise);
    newer.resolve({ ...accepted, valid: false, issues: [serverError] });
    await newRequest;
    if (rejectOlder) older.reject(new Error('Older error'));
    else older.resolve(accepted);
    await oldRequest;
    assert.equal(state.result.valid, false);
    assert.deepEqual(state.result.issues, [serverError]);
    assert.equal(state.error, null);
    assert.equal(state.pending, false);
  }
  const currentFailure = checks(snapshot);
  await currentFailure.validate(Promise.reject(new Error('Current failure')));
  assert.equal(currentFailure.error.message, 'Current failure');
  currentFailure.change(changes[0][1]);
  assert.equal(currentFailure.error, null);
  const returned = checks(snapshot), interrupted = deferred();
  const interruptedRequest = returned.validate(interrupted.promise);
  returned.change(changes[1][1]);
  returned.change(snapshot);
  interrupted.resolve(accepted);
  await interruptedRequest;
  assert.equal(returned.result, null);
  console.log('PASS: configuration blockers, retained diagnostics and exact-snapshot request ownership');
} finally { await rm(dir, { recursive: true, force: true }); }
