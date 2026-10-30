#!/usr/bin/env node
/**
 * Hand derivations for prop_action_motion.json (metres, seconds, compass degrees).
 * No expected value is sampled from production. Run:
 *   node client3d/scripts/smoke_prop_action_motion.mjs
 *
 * [1] Original ten routes: (0,0)->(2,0)->(2,3)->(5,3) has segment lengths
 * 2,3,3. Unit pace at ages 1,2,3,6 gives (1,0),(2,0),(2,1),(3,3).
 * Paces 2,1,3 consume 1+3 seconds to corner two; another .5*3 gives (3.5,3).
 * Null paces hold (0,0). Delay 2 at age 1 holds; age 5 leaves 3 seconds ->
 * (2,1). Trimmed (2,1)->(2,3)->(5,3) takes 2+1 seconds -> (3,3).
 * Age 100 exceeds length 8 -> exact endpoint (5,3).
 * [2] Entry fraction = clamp((elapsed + max(age,0)*max(rate,0))/duration,0,1).
 * Original (elapsed,duration,rate,age) values: (2,4,1,0),(1,4,1,1),
 * (1,8,2,1.5),(1,4,0,50),(3,4,1,20),(2,4,1,0) give
 * .5,.5,.5,.25,1,.5. Multiply measured clip durations 2,2,4,2,2,2 ->
 * 1,1,2,.5,2,1 seconds. Heights 200/140/100 cm do not scale this clock.
 * [3] Original support cases: support = anchor + root_offset;
 * correction = support - root_offset - access = anchor - access.
 * Stool .527-.398 = .129; hips 1->.5 at 1,.75,.5 give factors 0,.5,1,
 * hence lifts 0,.0645,.129. Bed .49-.002=.488; hips 1->.2 at .6 gives
 * .5*.488=.244. Upper storey 3.527-.398-3=.129 -> half .0645.
 * Hips .4 overshoots .5 -> clamp to .129. Flat hips cannot realize .129
 * (null/unsupported); .398-.398=0 needs no correction (0/supported).
 * [4] Additional routes: progress 3 skips the 2 m leg, then 1 m initial +
 * 1 m timed -> (2,2). Progress exactly 2 plus 1 s on next leg -> (2,1).
 * Progress 4 on a 2 m route clamps (2,0). Negative progress/age clamp 0;
 * negative delay clamps 0, so age 1 -> (1,0). Zero-length first leg still
 * consumes a pace index: .5 s at second pace 2 -> (1,0). Null/negative pace
 * holds progress 1 -> (1,0). Missing second pace holds at (2,0). Empty
 * route -> (0,0), singleton (4,5) -> itself. Diagonal length sqrt(3²+4²)=5;
 * 1.25 s * 2 = 2.5 m, halfway -> (1.5,2). Initial progress 1 leaves 1 m
 * at pace 2 (.5 s); from age 1.5 the remaining 1 s gives (2,1).
 * [5] Negative age/rate hold 1/4=.25; elapsed -2 clamps to 0;
 * (1+1.5*2)/4=1 exactly at the end.
 * [6] Ascending hips 0->2 at 1: .5*.4=.2. Hips 1.2 before descent
 * clamps 0. Access 1, anchor .5 -> -.5 correction, half -> -.25.
 * Span .0000005 < 1e-6 is flat: .129 lift unsupported; correction
 * .0000005 < 1e-6 with flat span returns 0 (the measured-support tolerance).
 * Span exactly .000001 is measured: 0->.000001 at .0000005 gives
 * .5*.2=.1 lift. Flat hips with correction exactly .000001 cannot count
 * as zero correction and return null (both tolerance checks are strict <).
 * [7] Identity joins kind|start|access x,y,z,yaw|anchor x,y,z,yaw.
 * Base is sit-down|5|0,0,0,90|1,0.4,0,90. Elapsed poll changes nothing;
 * changing start to 6, access Y to 3, anchor X to 2 or kind to lie-down
 * changes only that token. These are public clip origins, not execution IDs.
 * [8] Two meshes at (0,0) share room/variant, only chair-1 matches entry
 * placement chair-1/variant-1. Blocked semantic offers still expose slot
 * (1,0,2) as XZ (1,2); free=0 does not hide the reason. Stale variant,
 * wrong room, null mounted object or moved anchor each yields no pick.
 * [9] Gate starts with no withdrawn journeys. Cancel blocks immediately,
 * calls HTTP once and withdraws only after resolution. Reject releases pending
 * with no withdrawal; retry can succeed. Concurrent callers share the SAME
 * promise and only the first journey is withdrawn. Null/empty journeys never
 * enter the withdrawn set. Traces list pending, call count and probe booleans
 * after each operation; settle also records resolved/rejected.
 * [10] Begin retains pause until matching changed AND subsequent adopt.
 * Missing/other correlation cannot release it; completing one of two leaves
 * the other. Begin at 100 expires at 100+10000=10100, not 10099. Expire
 * marks complete once, stays pending, repeats false, then adopt releases.
 * [11] Drain waits for every actual position promise: finishing first of two
 * leaves both waiters false; finishing the queued final write resolves both.
 * Idle wait resolves on the next microtask; a later write blocks a new waiter.
 * [12] Choices preserve Core verdicts. Solo yields one enabled/reason row
 * without a partner; blocked solo keeps claimed. Pair returns the authored
 * fixture-npc busy / fixture-other enabled rows in that order, without picking
 * either. An empty pair list yields one disabled partner_required row.
 *
 * [14] A .75 s departure at age 0 or .5 must hold even with reported progress
 * ahead. At age .75 the step may advance .1 m; age 1 permits late catch-up
 * (6 m / .6 s = 10 m/s). A lead of exactly .25 m needs no catch-up.
 *
 * [15] A .3 s lead holds until age .3 exactly. The seat stand leg is
 * sqrt((2-2)^2+(-.5-0)^2)=.5 m; a .3/.4 diagonal is also .5 m.
 * After this defined release, .1 s at 1 m/s advances .5 -> .6 m.
 *
 * Adapters call production exports and normalize Three/Promise results only.
 * Async traces resolve before passing their actual result through runVectors;
 * the common loader, fixture resolver, comparator and failure accounting apply.
 * The original 27 inline lifecycle/pick assertions below remain as regressions.
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
const entry = {kind:'sit-down',started_game_s:5,access:{x:0,y:0,z:0,yaw:90},anchor:{x:1,y:.4,z:0,yaw:90}};
assert.equal(motion.entryIdentity(entry), motion.entryIdentity({...entry,elapsed_game_s:3}), 'elapsed polls never reschedule');
assert.notEqual(motion.entryIdentity(entry), motion.entryIdentity({...entry,started_game_s:6}), 'new authoritative origin schedules once');
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

await import('./smoke_prop_action_menu.mjs');

await import('./smoke_prop_action_recovery.mjs');
