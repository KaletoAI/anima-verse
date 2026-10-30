/** Task 81: execute the production lifecycle closures together, without WebGL or a live server. */
import assert from 'node:assert/strict';
import { mainFunctions } from './mainFunction.mjs';
import { motion } from './propActionVectorDispatch.mjs';

for (const [status, offline] of [['cancelled', false], ['failed', true], ['withdrawn', false]]) {
  let finishState, maps = 0, states = 0, resets = 0;
  const preparation = motion.createPropPreparationBarrier();
  preparation.begin('request'); preparation.changed('request');
  const gate = motion.createManualPropGate();
  const run = { execution_id: 'run', status: 'approaching', reason: '' };
  const map = { characters: [{ name: 'avatar', travel: status === 'withdrawn' ? { journey_id: 'journey' } : null }] };
  const messages = [];
  const scope = await mainFunctions(['ownedPropRun', 'adoptPropState', 'reconcilePropWorld', 'endPropRun',
    'releaseLocalProp', 'refreshPropMotion', 'pollPropMotion', 'mutatePropAction'], {
    requestedPropRun: status === 'cancelled' ? null : run, trackedPropRun: status === 'cancelled' ? null : run, adoptedPropJourney: null,
    propMutationPending: false, cancelRoute() {},
    semanticState: { current: [], outgoing: [], recent_results: [] },
    releasedPropExecutions: new Set(), manualPropGate: gate,
    propStateEpoch: 1, propStateUncertain: true, propPreparation: preparation,
    propPollBusy: false, propPollUntil: performance.now() + 5000, manualPropRelease: false,
    lastMap: map, avatarName: 'avatar', ownedPropJourney: 'journey',
    avatarDrive: { kind: 'SERVER' }, avatarSeated: true, seatedKey: 'seat',
    preparedPropSeatExecution: 'old', preparedPropJourney: 'journey',
    avatarCancelled: null, ownSeatChangeAt: 0, answerFloor: 0, posSeq: 1, pendingReport: {},
    api: { getPropActionState: () => { states++; return new Promise(resolve => { finishState = resolve; }); } },
    pollCore: () => ({ refresh: async () => { maps++; scope.reconcilePropWorld(map); if (offline) throw Error('map offline'); } }),
    releaseSwitchedPropSeat() {}, syncPlaceGlyphs: async () => {},
    npcs: { clearPropEntry: () => { resets++; }, setServerDriven() {}, setPlayerPose() {}, setPlayerAnimation() {} },
    uiActions: { toast: message => { throw Error(message); } },
    console: { info: message => messages.push(message) },
  }, ['avatarDrive', 'avatarSeated', 'manualPropRelease', 'propStateUncertain', 'propPollUntil',
    'preparedPropSeatExecution', 'pendingReport']);
  const refreshing = status === 'cancelled' ? scope.mutatePropAction(async () => run) : scope.refreshPropMotion(true);
  await Promise.resolve();
  assert.equal(maps, 1, 'answer starts exactly one immediate map poll while private state is still pending');
  assert.equal(states, 1);
  finishState({ current: status === 'withdrawn' ? [run] : [], outgoing: [],
    recent_results: status === 'withdrawn' ? [] : [{ ...run, status, reason: 'execution_owner_error' }] });
  if (offline) await assert.rejects(refreshing, /map offline/);
  else await refreshing;
  if (status === 'withdrawn') {
    assert.equal(resets, 0, 'adopted route remains controlled until withdrawal');
    map.characters[0].travel = null;
    scope.reconcilePropWorld(map);
  }
  assert.equal(resets, 1, 'dead run releases once');
  assert.equal(scope.ownedPropRun(), undefined, 'old private ownership cannot keep the input gate closed');
  assert.equal(preparation.pending, false);
  assert.equal(gate.pending, false);
  const snapshot = scope.snapshot();
  assert.equal(snapshot.avatarDrive.kind, 'PLAYER');
  assert.equal(snapshot.avatarSeated, false);
  assert.equal(snapshot.propStateUncertain, false);
  assert.equal(snapshot.pendingReport, null);
  assert.equal(snapshot.preparedPropSeatExecution, undefined);
  assert.ok(messages.some(line => line.includes(`[prop] run ended without approach: status=${status === 'withdrawn' ? 'cancelled' : status} reason=`)));
  for (let i = 0; i < 120; i++) scope.pollPropMotion();
  assert.equal(maps, 1, 'no dead-run poll churn');
  assert.equal(states, 1, 'no dead-run state churn');
  scope.adoptPropState({ current: [run], outgoing: [], recent_results: [] });
  assert.equal(scope.ownedPropRun(), undefined, 'stale own run cannot revive ownership after release');
  assert.equal(resets, 1, 'old poll cannot repeat reset');
}
console.log('prop action recovery: PASS (immediate poll, cancelled/failed/withdrawn, input gates and idle polling)');

// A failed private read must still observe a parallel map rejection.
{
  const unhandled = [];
  const record = error => unhandled.push(error);
  process.on('unhandledRejection', record);
  try {
    const scope = await mainFunctions(['refreshPropMotion'], {
      propStateEpoch: 0,
      api: { getPropActionState: async () => { throw Error('state offline'); } },
      pollCore: () => ({ refresh: async () => { throw Error('map offline'); } }),
      console: { info() {} },
    });
    await assert.rejects(scope.refreshPropMotion(true), /state offline/);
    await new Promise(resolve => setImmediate(resolve));
    assert.deepEqual(unhandled, [], 'parallel map rejection is always observed');
  } finally { process.off('unhandledRejection', record); }
}
console.log('prop action recovery errors: PASS (parallel state/map rejection observed)');
