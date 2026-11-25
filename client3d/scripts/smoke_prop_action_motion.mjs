#!/usr/bin/env node
/**
 * Derivation moved to native/tests/Derivations/prop_action_motion.md (E1, 2026-11-25).
 * Usage:  node client3d/scripts/smoke_prop_action_motion.mjs
 * Runs until E3 deletes the browser scene; the C# vector tests keep executing the cases.
 */
import assert from 'node:assert/strict';
import { loadVectors, resolveArgs, runVectors } from '../../shared/test-vectors/vectors.mjs';
import { motion, glyphs, THREE, propActionDispatch } from './propActionVectorDispatch.mjs';
const vectors = loadVectors('prop_action_motion');
// Reject unknown functions before any case executes, just like runVectors.
for (const c of vectors.cases) assert.equal(typeof propActionDispatch[c.fn], 'function', c.fn);
let passed = 0, failed = 0;
for (const c of vectors.cases) {
  let actual, error, threw = false;
  try { actual = await propActionDispatch[c.fn](...resolveArgs(c.args, vectors.fixtures)); }
  catch (e) { error = e; threw = true; }
  const result = runVectors({ ...vectors, cases: [c] }, {
    [c.fn]: () => { if (threw) throw error; return actual; },
  });
  passed += result.passed; failed += result.failed;
}
if (failed) process.exit(1);
const entry = {kind:'sit-down',started_s:5,access:{x:0,y:0,z:0,yaw:90},anchor:{x:1,y:.4,z:0,yaw:90}};
assert.equal(motion.entryIdentity(entry), motion.entryIdentity({...entry,elapsed_s:3}), 'elapsed polls never reschedule');
assert.notEqual(motion.entryIdentity(entry), motion.entryIdentity({...entry,started_s:6}), 'new authoritative origin schedules once');
const gate = motion.createManualPropGate();
let resolveCancel;
const deferred = new Promise(r => { resolveCancel = r; });
let cancelled = 0;
const pending = gate.cancel('run-1', 'journey-1', async () => { cancelled++; await deferred; });
assert.equal(gate.pending, true, 'position control blocked until real cancellation answer');
assert.equal(gate.withdrawn('journey-1'), false, 'failed/unanswered cancellation cannot tombstone');
resolveCancel(); await pending;
assert.equal(cancelled, 1);
assert.equal(gate.pending, false);
assert.equal(gate.withdrawn('journey-1'), true, 'old poll cannot revive cancelled route');
await assert.rejects(gate.cancel('run-2', 'journey-2', async () => { throw new Error('refused'); }));
assert.equal(gate.withdrawn('journey-2'), false, 'refusal retains server ownership');
const drain = motion.createPositionDrain();
const finishPosition = drain.begin();
let drained = false;
const draining = drain.wait().then(() => { drained = true; });
await Promise.resolve();
assert.equal(drained, false, 'preparation cannot acknowledge an in-flight position write');
const finishQueuedPosition = drain.begin();
finishPosition();
await Promise.resolve();
assert.equal(drained, false, 'queued final position report also drains before semantic HTTP');
finishQueuedPosition();
await draining;
assert.equal(drained, true);
const preparation = motion.createPropPreparationBarrier();
preparation.begin('mutation-a');
preparation.changed(); preparation.adoptFreshState();
assert.equal(preparation.pending, true, 'unrelated lifecycle polls cannot release mutation pause');
preparation.changed('mutation-other'); preparation.adoptFreshState();
assert.equal(preparation.pending, true, 'unrelated mutation cannot release another request pause');
preparation.changed('mutation-a');
assert.equal(preparation.pending, true, 'correlated invalidation still waits for authoritative state');
preparation.adoptFreshState();
assert.equal(preparation.pending, false, 'fresh state after correlated success/refusal releases pause');
preparation.begin('mutation-b'); preparation.begin('mutation-c');
preparation.changed('mutation-b'); preparation.adoptFreshState();
assert.equal(preparation.pending, true, 'concurrent mutation retains its own pause');
preparation.changed('mutation-c'); preparation.adoptFreshState();
assert.equal(preparation.pending, false);
preparation.begin('disconnected-hud', 0);
assert.equal(preparation.expire(9999), false, 'live preparation cannot expire before handshake lease');
preparation.adoptFreshState();
assert.equal(preparation.pending, true, 'lifecycle state alone cannot unlock a live preparation');
assert.equal(preparation.expire(10000), true, 'lost HUD completion becomes eligible at the exact lease');
assert.equal(preparation.pending, true, 'lease expiration still requires a new authoritative snapshot');
preparation.adoptFreshState();
assert.equal(preparation.pending, false, 'fresh state unlocks disconnected HUD without retries');
const furniture = new THREE.Group(), overlapping = new THREE.Group();
const geometry = new Map([['blocked', {roomId:'room', anchor:[0,0], slots:[new THREE.Vector3(1,0,2)],
  placementId:'chair-1', variantUid:'variant-1'}]]);
const blockedOffer = {id:'blocked', free:0, free_slots:[], prop_actions:[{enabled:false,reason:'claimed'}]};
const picks = glyphs.pickableProps([
  {role:'prop',roomId:'room',anchor:[0,0],placementId:'chair-1',variantUid:'variant-1',object:furniture},
  {role:'prop',roomId:'room',anchor:[0,0],placementId:'chair-2',variantUid:'variant-1',object:overlapping},
], geometry, [blockedOffer]);
assert.equal(picks.length, 1, 'blocked furniture is pickable even without free slots');
assert.equal(picks[0].object, furniture, 'same-anchor meshes cannot steal exact placement actions');
assert.deepEqual(picks[0].places, [{id:'blocked',free:[{x:1,z:2}]}]);
assert.equal(glyphs.pickableProps([{role:'prop',roomId:'room',anchor:[0,0],
  placementId:'chair-1',variantUid:'stale',object:furniture}], geometry, [blockedOffer]).length, 0,
  'stale variant cannot borrow another binding');
console.log(`prop action motion: ${passed} vectors + 27 inline assertions = ${passed + 27} checks, all ok`);

await import('./smoke_prop_action_storey.mjs');

await import('./smoke_prop_action_offers.mjs');

await import('../../scripts/smoke_prop_action_menu.mjs');

await import('./smoke_prop_action_recovery.mjs');

await import('./smoke_prop_action_playback.mjs');

await import('./smoke_prop_action_answer_bridge.mjs');
