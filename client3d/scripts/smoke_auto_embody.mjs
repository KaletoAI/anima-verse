/** Task 85: session-start automation drives the existing take-control action exactly once. */
import assert from 'node:assert/strict';
import { mainFunctions } from './mainFunction.mjs';
async function fixture(overrides = {}) {
  let control = 0, logs = 0;
  const map = { avatar: 'Kai', characters: [{ name: 'Kai' }] };
  const deps = {
    autoControlHandled: false, arrivalReady: false, bootDone: true, firstMap: map, lastMap: map,
    showAll: false, location: { search: '' }, npcs: { positionOf: () => ({ x: 1, z: 2 }) },
    getGameState: () => ({ mode: 'overview' }), gameActions: { takeControl: () => { control++; } },
    console: { info: () => { logs++; } }, pendingTakeControl: false, pendingArrivalTakeControl: false, setBootNote() {}, ...overrides,
  };
  const scope = await mainFunctions(['tryAutoTakeControl', 'cancelPendingControl'], deps, ['autoControlHandled']);
  const attempt = Object.assign(scope.tryAutoTakeControl, { snapshot: scope.snapshot });
  return { attempt, cancel: scope.cancelPendingControl, calls: () => control, logs: () => logs };
}
let f = await fixture(); f.attempt(); assert.equal(f.calls(), 0, 'wait for boot arrival');
f = await fixture({ arrivalReady: true }); f.attempt(); f.attempt();
assert.equal(f.calls(), 1); assert.equal(f.logs(), 1);
f.attempt(); assert.equal(f.calls(), 1, 'Esc/overview does not repeat the automation');
for (const overrides of [
  { showAll: true }, { location: { search: '?goto=house' } },
  { firstMap: { avatar: '' }, lastMap: { avatar: '', characters: [] } },
  { getGameState: () => ({ mode: 'embodied' }) }, { bootDone: false },
]) {
  f = await fixture({ arrivalReady: true, ...overrides }); f.attempt();
  assert.equal(f.calls(), 0, JSON.stringify(overrides));
}
f = await fixture({ arrivalReady: true, npcs: { positionOf: () => null } }); f.attempt();
assert.equal(f.calls(), 0); assert.equal(f.attempt.snapshot().autoControlHandled, false, 'wait for late avatar');
f = await fixture({ arrivalReady: true }); f.attempt(); assert.equal(f.calls(), 1, 'fresh resume session re-enters control');

let placed = false;
f = await fixture({ arrivalReady: true, npcs: { positionOf: () => placed ? { x: 1, z: 2 } : null } });
f.attempt(); f.cancel(false); // Poll temporarily omits the avatar; it is not an explicit overview choice.
placed = true; f.attempt();
assert.equal(f.calls(), 1, 'transient missing-avatar poll must not consume automatic control');
f = await fixture({ arrivalReady: true }); f.cancel(); f.attempt();
assert.equal(f.calls(), 0, 'explicit cancellation consumes automatic control');
console.log('automatic embody: PASS (arrival, once/session, resume, late avatar, goto/admin/no-avatar)');
