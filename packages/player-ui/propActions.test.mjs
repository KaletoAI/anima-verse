// Run from the repository root: node packages/player-ui/propActions.test.mjs
// Catches lost exact targets/revisions, implicit consent, stale mutation views,
// hidden blocked partners, and swallowed authoritative refusal reasons.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
const require = createRequire(new URL('../../client3d/package.json', import.meta.url));
const ts = require('typescript');
const compile = source => ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText;
const dataUrl = source => 'data:text/javascript;base64,' + Buffer.from(source).toString('base64');
const apiUrl = dataUrl(compile(readFileSync(new URL('./src/api.ts', import.meta.url), 'utf8')));
const source = compile(readFileSync(new URL('./src/propActions.ts', import.meta.url), 'utf8'));
const actions = await import(dataUrl(source.replace(/from ['"]\.\/api['"]/, `from '${apiUrl}'`)));
globalThis.window = new EventTarget();
if (!globalThis.CustomEvent) globalThis.CustomEvent = class extends Event { constructor(type, options) { super(type); this.detail = options?.detail; } };
const target = { location_id: 'house', room_id: 'lounge', placement_id: 'sofa-2', variant_uid: 'green' };
const offer = { action_id: 'rest', definition_revision: 'rev-7', placement_id: 'sofa-2', variant_uid: 'green', target, label: 'Rest', description: '', enabled: true, reason: '', required_partner: true, available_targets: [{ partner: 'Kira', enabled: false, reason: 'slot_occupied' }, { partner: 'Mira', enabled: true, reason: '' }], effects: [] };
assert.deepEqual(actions.propActionChoices(offer), [
  { partner: 'Kira', enabled: false, reason: 'slot_occupied' },
  { partner: 'Mira', enabled: true, reason: '' },
]);
assert.deepEqual(actions.propActionChoices({ ...offer, enabled: false, reason: 'partner_required', available_targets: [] }), [{ enabled: false, reason: 'partner_required' }]);
assert.deepEqual(actions.propActionChoices({ ...offer, required_partner: false, enabled: false, reason: 'no_path' }), [{ enabled: false, reason: 'no_path' }]);
let changes = 0;
const finishIds = [];
const off = actions.onPropActionChanged(requestId => { changes++; finishIds.push(requestId); });
const requests = [];
const response = { execution_id: 'run-8', status: 'awaiting_consent', reason: '' };
globalThis.fetch = async (path, init) => {
  requests.push({ path, body: init?.body ? JSON.parse(init.body) : null });
  return new Response(JSON.stringify(path.endsWith('/state') ? { incoming: [], outgoing: [], current: [], recent_results: [] } : path === '/play/prop-actions' ? [offer] : response), { status: 200, headers: { 'Content-Type': 'application/json' } });
};
assert.deepEqual(await actions.getPropActions(), [offer]);
assert.deepEqual(await actions.getPropActionState(), { incoming: [], outgoing: [], current: [], recent_results: [] });
assert.equal(changes, 0);
let releasePreparation, preparedId;
const offPreparation = actions.setPropActionPreparation(requestId => {
  preparedId = requestId;
  return new Promise(resolve => { releasePreparation = resolve; });
});
const heldRequest = actions.requestPropAction('rest', target, 'rev-7', 'Mira');
await Promise.resolve();
assert.equal(requests.length, 2, 'semantic HTTP must await position-writer drain');
releasePreparation();
assert.deepEqual(await heldRequest, response);
offPreparation();
assert.deepEqual(requests.at(-1), { path: '/play/prop-actions/request', body: { action_id: 'rest', target, revision: 'rev-7', partner: 'Mira' } });
assert.equal(requests.filter(r => r.path.endsWith('/respond')).length, 0, 'request must never accept on behalf of a partner');
assert.equal(changes, 1, 'successful request invalidates before returning');
assert.equal(finishIds[0], preparedId, 'mutation completion carries exact preparation correlation');
await actions.respondPropAction('run-8', false);
assert.deepEqual(requests.at(-1), { path: '/play/prop-actions/respond', body: { execution_id: 'run-8', accept: false } });
await actions.cancelPropAction('run-8');
assert.deepEqual(requests.at(-1), { path: '/play/prop-actions/cancel', body: { execution_id: 'run-8' } });
assert.equal(changes, 3);
await actions.requestPropAction('rest', target, 'rev-7');
assert.deepEqual(requests.at(-1).body, { action_id: 'rest', target, revision: 'rev-7' });
globalThis.fetch = async () => new Response(JSON.stringify({ detail: { execution_id: '', status: 'refused', reason: 'definition_changed' } }), { status: 409 });
await assert.rejects(actions.requestPropAction('rest', target, 'old'), /definition_changed/);
assert.equal(changes, 5, 'refusal invalidates and releases the host barrier without adopting a place');
const beforeFailedPreparation = requests.length;
let failedPreparationId;
const offFailedPreparation = actions.setPropActionPreparation(async requestId => {
  failedPreparationId = requestId;
  throw new Error('position writer failed');
});
await assert.rejects(actions.cancelPropAction('run-8'), /position writer failed/);
assert.equal(requests.length, beforeFailedPreparation, 'failed preflight never issues mutation HTTP');
assert.equal(changes, 6, 'failed preflight still releases host via invalidation');
assert.equal(finishIds[5], failedPreparationId, 'preparation failure releases its own exact correlation');
offFailedPreparation();
let staleCalled = false;
const staleOff = actions.setPropActionPreparation(async () => { staleCalled = true; });
let replacementCalled = false;
const replacementOff = actions.setPropActionPreparation(async () => { replacementCalled = true; });
staleOff();
await assert.rejects(actions.respondPropAction('run-8', true), /definition_changed/);
assert.equal(staleCalled, false, 'old preparation must not revive after host replacement');
assert.equal(replacementCalled, true, 'stale unsubscribe cannot detach replacement host');
replacementOff();
assert.equal(changes, 7);
assert.equal(new Set(finishIds).size, 7, 'distinct mutations must never share barrier identities');
off();
const pollIds = [];
const offPoll = actions.onPropActionChanged(requestId => pollIds.push(requestId));
actions.notifyPropActionChanged();
assert.deepEqual(pollIds, [undefined], 'lifecycle invalidation cannot complete a prepared mutation');
offPoll();
assert.equal(changes, 7);
console.log('PASS semantic prop-action API, exact consent and blocked choices');
