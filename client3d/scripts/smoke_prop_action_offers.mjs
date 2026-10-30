/** Task 78: actual offer reconciliation reads actions after authoritative lifecycle state. */
import assert from 'node:assert/strict';
import { mainFunction } from './mainFunction.mjs';
const me = { name: 'avatar', location_id: 'loc', room_id: 'room' };
const map = { characters: [me] };
let refreshWorld = 0;
let status = 'approaching', reason = 'approaching', actionReads = 0, finishActions;
const blocked = [{ action_id: 'sit', enabled: false, reason: 'approaching' }];
const enabled = [{ action_id: 'sit', enabled: true, reason: '' }];
const deps = {
  propOffersRoomKey: null, offersGeneration: 0, offersAppliedGeneration: 0, propStateEpoch: 0, ownSeatChangeAt: 0,
  avatarName: 'avatar', lastMap: map, semanticOffers: blocked,
  semanticState: { current: [{ execution_id: 'run', status: 'approaching' }] },
  placeOffers: [], placeOffersRoom: 'room', manualPropRelease: false, propStateUncertain: false,
  propPreparation: { adoptFreshState() {} }, pollIsStale: () => false,
  api: {
    invalidatePropActionOffers() {},
    getPlaces: async () => ({ places: [], room_id: 'room' }),
    getPropActions: async () => {
      actionReads++;
      const rows = reason ? [{ ...blocked[0], reason }] : enabled;
      if (finishActions) await new Promise(resolve => { finishActions.resolve = resolve; });
      return rows;
    },
    getPropActionState: async () => {
      reason = status === 'active' ? 'seated' : '';
      return { current: status ? [{ execution_id: 'run', status }] : [] };
    },
    isAuthError: () => false,
  },
  rebuildPlaceGlyphs() {}, getGameState: () => ({}), setGameState() {},
  figures: { state: 'loading' }, npcs: {}, uiActions: { toast: m => { throw Error(m); } },
  releaseSwitchedPropSeat() {}, logPropOffers() {}, adoptPropState() {},
};
const sync = await mainFunction('syncPlaceGlyphs', deps, ['semanticOffers']);
status = 'active';
await sync(map);
assert.equal(sync.snapshot().semanticOffers[0].reason, 'seated', 'arrival offers follow new private state');
status = ''; finishActions = {};
const refreshing = sync(map);
await new Promise(resolve => setImmediate(resolve));
assert.equal(sync.snapshot().semanticOffers[0].reason, 'seated', 'in-flight refresh keeps previous rows');
finishActions.resolve(); await refreshing;
assert.equal(sync.snapshot().semanticOffers[0].enabled, true, 'polled completion restores availability');
assert.equal(actionReads, 2);
finishActions = null;
const refreshMotion = await mainFunction('refreshPropMotion', {
  adoptPropState() {}, releaseSwitchedPropSeat() {}, propStateEpoch: 0, api: deps.api, semanticState: {}, propStateUncertain: false,
  ownedPropRun: () => null, propPreparation: deps.propPreparation,
  pollCore: () => ({ refresh: async () => { refreshWorld++; } }), lastMap: map, syncPlaceGlyphs: sync,
});
const release = await mainFunction('releaseOwnedProp', {
  trackedPropRun: null, requestedPropRun: null, adoptedPropJourney: null, releaseLocalProp() {},
  ownedPropRun: () => ({ execution_id: 'run' }), manualPropGate: {
    pending: false, cancel: async (_run, _journey, cancel) => { await cancel(); },
  },
  avatarName: 'avatar', lastMap: map, ownedPropJourney: 'journey',
  api: { cancelPropAction: async () => ({ status: 'cancelled' }) }, releasedPropExecutions: new Set(),
  manualPropRelease: false, ownSeatChangeAt: 0, avatarCancelled: null, avatarDrive: {},
  npcs: { setServerDriven() {}, clearPropEntry() {}, setPlayerPose() {}, setPlayerAnimation() {} },
  avatarSeated: true, seatedKey: '', refreshPropMotion: refreshMotion, uiActions: deps.uiActions,
});
await release();
assert.equal(actionReads, 2, 'cancel answer uses its own motion without another offers poll');
assert.equal(refreshWorld, 0, 'cancel does not need a separate worldmap poll');
assert.equal(sync.snapshot().semanticOffers[0].enabled, true);
console.log('prop action offers: PASS (arrival, completion, in-flight rows retained, answer-driven release)');

// Request diagnostics begin after the production position preparation has drained.
const events = [], diagnostic = {};
const prepare = await mainFunction('preparePropAction', {
  preparedPropSeatExecution: undefined, preparedPropJourney: undefined, avatarName: 'avatar', lastMap: map,
  propPreparation: { begin() {} }, propStateUncertain: false, propStateEpoch: 0,
  cancelRoute() {}, npcs: { positionOf: () => ({ x: 1, z: 2 }), setPlayerTarget() {} },
  avatarDrive: { kind: 'PLAYER' }, ownedPropRun: () => null, pendingReport: null,
  propPositionDrainActive: false, propPositionDrainFailed: false, avatarSeated: false, posDirty: true,
  reserveReport: () => events.push('flush'), flushPendingReport() {},
  positionDrain: { wait: async () => { events.push('drained'); } }, propRequestDiagnostic: diagnostic,
  console: { info: line => events.push(line.includes('request sent') ? 'sent' : 'position') },
});
let operation;
const pick = await mainFunction('gameActions.pickPropAction', {
  gameActions: { closePlaceMenu() {} }, propRequestDiagnostic: diagnostic, propMutationPending:false, placeEntries:undefined,
  mutatePropAction: work => { operation = work(); },
  api: { requestPropAction: async () => { await prepare('fixture'); events.push('http'); return { status: 'approaching' }; } },
  console: { info: () => events.push('answered') },
});
pick('sit', { placement_id: 'bench' }, 'revision'); await operation;
assert.deepEqual(events, ['flush', 'drained', 'position', 'sent', 'http', 'answered']);
console.log('prop action diagnostics: PASS (pre-flush, request sent, HTTP, answer ordering)');
