#!/usr/bin/env node
/** NEU: residency.ts and SceneLibrary.forget absent on a241a8aa.
 * Canonical source for residency.json, op sequences [1]..[18].
 * Each op group yields one snapshot; expectations select state fields and exact
 * incremental up/down calls (mount/unmount decisions). No implicit flush occurs.
 * [1] up_down: gone->far->near mounts twice; near->far->gone unmounts twice.
 * [2] retarget_mid_await: near requested, gone before completion; one rollback,
 * no published resident and no retry. [3] flip_flop: gone then far invalidates
 * the first up; one rollback, one replacement up, final far/version 1.
 * [4] rebuild_during_shell: invalidate version 1, replace with version 2 at far.
 * [5], [9], [10] rebuild_at_near / settled_waits_rebuild / hasJob: initial
 * want queues a job synchronously; settled leaves near/version 1 with no job.
 * Rebuild downs near then far, awaits the new shell (gone, no live version,
 * hasJob=true, settled waiter unresolved), then ups far->near at version 2;
 * precisely one waiter resolves. No stale shell is kept.
 * [6], [7] drop_during_fetch / drop_during_mount: the driver's opaque awaited
 * up aborts once, ends gone with no live/timer. Real fetch/mount cleanup is
 * distinguished separately in the main-adapter integration cases below.
 * [8] rediscover_after_drop: aborted version 1 cleans up before version 2 up;
 * final far/version 2, one resident, one rollback, no retry.
 * [11] fetch_retry: failure leaves gone, hasJob=false and timer 5000 ms;
 * firing that timer without another want performs one new up and reaches far.
 * [12] queue_max: five far requests with ascending priorities, each gated;
 * exactly ids 0/1 enter first, max concurrent mounts=2, release yields 2/3/4
 * in order and five live residents, all jobs false.
 * [13] cancelled_retry_settled: failed up arms 5000 ms; want gone cancels it,
 * resolves both settled waiters, deletes the entry; rebuilding is then inert.
 * [14] sweep_forgotten: forget X before reply -> no cache/publication.
 * [15] sweep_forget_unstarted: while X awaits, forget Y; publish only X and
 * never fetch Y. [16] forget_then_request: forgotten X's old reply cannot
 * publish; fresh request publishes fresh once. [17] reverse reply order:
 * fresh first remains fresh after the old reply; same one publication.
 * [18] request_dedup: two requests share a promise and one fetch; both return
 * the same new signature, published exactly once.
 * Pins are renderer adapter state rather than driver state: the independent
 * current/travel owners and boot release assertions stay inline below.
 *
 * Hand oracles: gone->near needs two up steps; near->gone two down steps.
 * Invalidated steps roll back once, never publish ready. Five jobs on max=2
 * never exceed two mounts. Failed fetch retries at 5000 ms without retarget.
 * Rebuild tears down both stages and builds version 2, preserving near target;
 * settled waits for queued rebuild, hasJob includes queued and running work.
 * Drop invalidates fetch/mount, never retries; rediscovery waits for old cleanup.
 * Epoch snapshots reject forgotten replies in either order, and skip B when
 * forgotten while sweep waits for A. Duplicate requests share one promise.
 * Main adapter cases below run extracted production functions with stub I/O:
 * no_scene reaches ready without mounts; stale details never publish ready;
 * arrival_moves places on Y and opens Y before requesting its full tiers;
 * open_arrival_tiers/tick_during_promotion keep full until ready, height updates
 * still execute. Source guards cover the adapter wiring, not rendered pixels.
 */
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { build, transformSync } from 'esbuild';
import { loadVectors, near, resolveArgs } from '../../shared/test-vectors/vectors.mjs';
import { load, createResidencyDriver, createFocusQueue, flush, deferred,
  makeLibrary, residencyScenario } from './residencyVectorDispatch.mjs';
const { buildingTier, interiorTier } = await load('client3d/src/scene/sceneView.ts');
function assertBefore(source, first, second) {
    const firstIndex = source.indexOf(first), secondIndex = source.indexOf(second);
    assert.ok(firstIndex >= 0, `missing first marker: ${first}`);
    assert.ok(secondIndex >= 0, `missing second marker: ${second}`);
    assert.ok(firstIndex < secondIndex, `${first} must precede ${second}`);
}
// Every scenario produces one snapshot per op group. The shared expectations
// compare only named state fields, but call arrays require exact order/length.
const vectors = loadVectors('residency');
const dispatch = { residencyScenario };
for (const c of vectors.cases) assert.equal(typeof dispatch[c.fn], 'function', `unknown fn ${c.fn}`);
for (const c of vectors.cases) {
    const actual = await dispatch[c.fn](...resolveArgs(c.args, vectors.fixtures));
    const result = near(c.expect, actual, c.eps);
    assert.ok(result.ok, `${c.label}: ${result.diff}`);
    console.log('PASS', c.label);
}
const main = await readFile('client3d/src/main.ts', 'utf8');
const ts = await import('typescript');
const ast = ts.createSourceFile('main.ts', main, ts.ScriptTarget.Latest, true);
function fn(name) { let found; function visit(n) { if (ts.isFunctionDeclaration(n) && n.name?.text === name)
    found = n.getText(ast); ts.forEachChild(n, visit); } visit(ast); assert.ok(found, `main function ${name} exists`); return found; }
function compile(names, deps, tail = '') { deps = { restoreStorey() {}, buildingTier, interiorTier, ...deps }; return new Function(...Object.keys(deps), transformSync(names.map(fn).join('\n') + '\n' + tail + '\nreturn {' + names.join(',') + '};', { loader: 'ts' }).code)(...Object.values(deps)); }
for (const name of ['no_scene', 'retarget_far_near', 'open_arrival_tiers', 'tick_during_promotion']) {
    const residency = new Map(), promoting = new Set(), buildingTierByLoc = new Map(), interiorTierByLoc = new Map();
    const log = [];
    const gate = deferred();
    let alive = true;
    const tile = { loc: { id: 'X' }, group: {}, height: 4, center: {}, width: 40, placedModels: [] };
    const place = { loc: { id: 'X' }, height: 4 };
    const scene = name === 'no_scene' ? null : {area_detail: true};
    const deps = { driver: { target: () => 'gone' }, residency, promoting, buildingTierByLoc, interiorTierByLoc, scenes: { get: () => scene, request: async () => scene }, engine: { scene: { add() { }, remove() { } }, setPickables() { }, camera: { position: {distanceTo: () => 0} } }, buildTile: () => tile, shareTileHeight() { }, mountShell: async () => { log.push('shell'); }, mountDetail: async (t, s, tier) => { log.push(['detail', tier]); if (name === 'retarget_far_near') {
            await gate.promise;
        } return true; }, setSceneModelTier: async (t, kind, tier) => { log.push([kind, tier]); if (name === 'tick_during_promotion' && kind === 'building')
            await gate.promise; }, openLocationId: 'X', BUILDING_TIER_NEAR: 45, BUILDING_TIER_FAR: 60, buildBoundaryMarks() { }, buildDoorMarks() { log.push('doors'); }, unmountDetail() { log.push('rollback'); }, unmountShell() { }, freeTile() { }, rebuildPlaceGlyphs() { }, places: new Map([['X', place]]), console };
    const { upResident, wantedBuildingTier, wantedInteriorTier } = compile(['upResident', 'nearBuildingTier', 'nearInteriorTier', 'wantedBuildingTier', 'wantedInteriorTier'], deps);
    assert.equal(await upResident('X', place, 'gone', () => alive), 'ok');
    assert.equal(residency.get('X').ring, 'far');
    assert.equal(wantedBuildingTier(tile), 'low');
    assert.equal(wantedInteriorTier('X', scene), 'low');
    const p = upResident('X', place, 'far', () => alive);
    await flush();
    if (name === 'retarget_far_near') {
        alive = false;
        gate.resolve();
        assert.equal(await p, 'aborted');
        assert.equal(residency.get('X').ready, false);
        assert.ok(log.includes('rollback'));
        assert.ok(!log.includes('doors'));
    }
    else {
        if (name === 'tick_during_promotion') {
            assert.equal(promoting.has('X'), true);
            assert.equal(residency.get('X').ready, false);
            const body = fn('tickModelTiers');
            assertBefore(body, 'reliftScene(', 'promoting.has(');
            assertBefore(body, 'promoting.has(', 'const b =');
            gate.resolve();
        }
        assert.equal(await p, 'ok');
        assert.equal(residency.get('X').ready, true);
        if (scene) {
            assert.ok(log.some(x => Array.isArray(x) && x[0] === 'building' && x[1] === 'full'));
            assert.ok(log.some(x => Array.isArray(x) && x[0] === 'interior' && x[1] === 'full'));
            assert.equal(buildingTierByLoc.get('X'), 'full');
            assert.equal(interiorTierByLoc.get('X'), 'full');
        }
        else
            assert.ok(!log.includes('shell'));
    }
    assert.equal(promoting.size, 0);
    console.log('PASS', name);
}
{
    const gates = { X: deferred(), Y: deferred() }, wants = [], placed = [], pins = new Map(), state = {};
    const map = { characters: [{ name: 'avatar', location_id: 'X' }] };
    const residency = new Map(['X', 'Y'].map(id => [id, { tile: { loc: { id }, roomGroups: new Map() } }]));
    const deps = { state, residency, firstMap: map, avatarName: 'avatar', places: new Map([['X', {}], ['Y', {}]]), driver: { want: (id) => { assert.equal(state.open(), id, 'open before want'); wants.push(id); }, settled: id => gates[id].promise }, setPinOwner: (owner, id) => { pins.set(owner, id); }, distanceOf: () => 0, followAvatarStorey: t => placed.push(t.loc.id) };
    const api = compile(['awaitArrivalMount', 'placeAvatarOnArrival'], deps, `let lastMap = firstMap; let bootPin = ''; let openLocationId = null; state.open = () => openLocationId; const refreshOpenBadge = () => {}; const roomOf = new Map(); const openable = () => true; const npcs = {update(){}}; const computeNpcStates = () => {}; const applyTileFade = () => {}; const applyLevelDisplay = () => {}; const applyRoomVisibility = () => {};`);
    const p = api.placeAvatarOnArrival();
    await flush();
    map.characters[0].location_id = 'Y';
    gates.X.resolve();
    await flush();
    assert.deepEqual(wants, ['X', 'Y']);
    assert.equal(pins.get('boot'), 'Y');
    assert.deepEqual(placed, []);
    gates.Y.resolve();
    await p;
    assert.deepEqual(placed, ['Y']);
    assert.equal(state.open(), 'Y');
    const placement = fn('placeAvatarOnArrival');
    assertBefore(placement, 'await awaitArrivalMount()', 'residency.get(locId)');
    console.log('PASS arrival_moves');
}
// The promoting guard must skip only tier selection: execute a real LOD tick
// while the full building swap is pending, with a new ground revision.
{
    const residency = new Map(), promoting = new Set(), buildingTierByLoc = new Map(), interiorTierByLoc = new Map(), log = [];
    const gate = deferred(), tile = { loc: { id: 'X' }, group: {}, height: 4, placedModels: [] }, place = { loc: { id: 'X' }, height: 4 };
    const deps = { driver: { target: () => 'gone' }, residency, promoting, buildingTierByLoc, interiorTierByLoc, scenes: { get: () => ({}), request: async () => ({}) }, engine: { scene: { add() { } }, setPickables() { }, camera: { position: {} }, target: { x: 0, z: 0 } }, buildTile: () => tile, shareTileHeight() { }, mountShell: async () => { }, mountDetail: async () => true, setSceneModelTier: async (t, kind, tier) => { log.push([kind, tier]); if (kind === 'building' && tier === 'full')
            await gate.promise; }, nearInteriorTier: () => 'full', nearBuildingTier: () => 'full', wantedBuildingTier: () => 'low', wantedInteriorTier: () => 'low', buildBoundaryMarks() { }, buildDoorMarks() { }, unmountDetail() { }, freeTile() { }, places: new Map([['X', place]]), console, terrainGround: { heightRevision: () => 1, setHeightAnchor() { } }, redatumPlace: () => log.push('place-height'), redatumTile: () => { log.push('tile-height'); return 2; }, reliftScene: () => { log.push('relift'); return false; }, npcs: { tickFigureTiers() { } }, FIGURE_TIER_NEAR: 1, FIGURE_TIER_FAR: 2, runScatterLod() { }, worldPropsLayer: { tick() { }, redrape() { } }, getGameState: () => ({ mode: 'overview' }), firstMap: { avatar: 'avatar' } };
    const api = compile(['upResident', 'tickModelTiers'], deps, 'let groundDrapedRev = 0; let seatedKey = "";');
    await api.upResident('X', place, 'gone', () => true);
    const p = api.upResident('X', place, 'far', () => true);
    await flush();
    api.tickModelTiers();
    assert.ok(log.includes('place-height'));
    assert.ok(log.includes('tile-height'));
    assert.ok(log.includes('relift'));
    assert.ok(!log.some(x => Array.isArray(x) && x[1] === 'low'));
    assert.equal(residency.get('X').ready, false);
    gate.resolve();
    await p;
    assert.equal(residency.get('X').ready, true);
    assert.equal(buildingTierByLoc.get('X'), 'full');
    assert.equal(interiorTierByLoc.get('X'), 'full');
    console.log('PASS tick_during_promotion with height revision');
}
// Owners are independent even when they refer to one location.
{
    const pins = new Map();
    const { setPinOwner } = compile(['setPinOwner'], { pins });
    setPinOwner('current', 'X');
    setPinOwner('travel', 'X');
    setPinOwner('boot', 'Y');
    setPinOwner('boot', null);
    assert.deepEqual([...pins.get('X')], ['current', 'travel']);
    setPinOwner('current', 'Y');
    assert.deepEqual([...pins.get('X')], ['travel']);
    console.log('PASS pin owners');
}
// Real adapter rollback distinguishes an in-flight fetch from a mounted shell.
for (const stage of ['fetch', 'mount']) {
    const gate = deferred(), residency = new Map(), freed = [], forgotten = [];
    let alive = true, mounts = 0;
    const place = { loc: { id: 'X' } }, tile = { loc: { id: 'X' }, group: {} };
    const deps = { driver: { target: () => 'gone' }, residency, scenes: { get: () => stage === 'fetch' ? undefined : {}, request: () => gate.promise, forget: id => forgotten.push(id) }, buildTile: () => tile, shareTileHeight() { }, engine: { scene: { add() { } }, setPickables() { } }, mountShell: async () => { mounts++; await gate.promise; }, freeTile: t => freed.push(t), buildingTierByLoc: new Map(), interiorTierByLoc: new Map(), buildBoundaryMarks() { }, console };
    const { upResident } = compile(['upResident'], deps);
    const p = upResident('X', place, 'gone', () => alive);
    await flush();
    assert.equal(residency.size, stage === 'fetch' ? 0 : 1);
    alive = false;
    gate.resolve({});
    assert.equal(await p, 'aborted');
    assert.equal(residency.size, 0);
    assert.equal(mounts, stage === 'fetch' ? 0 : 1);
    assert.equal(freed.length, stage === 'fetch' ? 0 : 1);
    assert.deepEqual(forgotten, ['X']);
    console.log('PASS drop_during_' + stage + ' adapter cleanup');
}
// Prime captures epochs before its queue starts as well as before publication.
{
    const gate = deferred(), events = [];
    const C = makeLibrary(() => gate.promise), lib = new C();
    lib.onScene = id => events.push(id);
    const p = lib.prime(['X']);
    await flush();
    lib.forget('X');
    gate.resolve({ signature: 'old' });
    await p;
    assert.equal(lib.has('X'), false);
    assert.deepEqual(events, []);
    console.log('PASS prime_forgotten');
}
// NEU: a target/rebuild can arrive after run() finishes but before push()
// resolves. Hand oracle: the queued successor still reaches near/version 2.
for (const change of ['target', 'rebuild', 'drop', 'rediscover']) {
  const calls = [], live = new Map();
  let driver, first = true;
  const queue = {push: async job => {
    await job.run();
    if (first) {
      first = false;
      if (change === 'target') driver.want('X', 1, 'near', () => 0);
      if (change === 'rebuild') driver.rebuild('X', 2);
      if (change === 'drop') driver.drop('X');
      if (change === 'rediscover') { driver.drop('X'); driver.want('X', 2, 'near', () => 0); }
    }
    return 'done';
  }};
  driver = createResidencyDriver({up:async(id,p,from)=>{calls.push([p,from]);live.set(id,p);return 'ok';},down(id,p,from){calls.push(['down',p,from]);if(from === 'far') live.delete(id);}},queue,{setTimeout(){throw Error('no retry expected');},clearTimeout(){}});
  driver.want('X', 1, 'far', () => 0);
  await flush();
  assert.equal(driver.ring('X'), ['target', 'rediscover'].includes(change) ? 'near' : change === 'drop' ? 'gone' : 'far');
  if (change === 'rebuild') assert.deepEqual(calls, [[1,'gone'],['down',1,'far'],[2,'gone']]);
  // NEU hand oracle: old teardown precedes both new ups, leaving one new resident.
  if (change === 'rediscover') {
    assert.deepEqual(calls, [[1,'gone'],['down',1,'far'],[2,'gone'],[2,'far']]);
    assert.deepEqual([...live], [['X',2]]);
  }
  assert.equal(driver.hasJob('X'), false);
  await driver.settled('X');
  console.log('PASS queue completion '+change);
}

// NEU A-T5: readiness.ts absent on a241a8aa. Hand oracles: hold only
// unready footprints; release owners independently; entry waits twice for
// far then near, once after drop, always releases its entry pin once.
const { holdFor, trySnap, holdSnap, clearSnap, enterWhenReady } = await load('client3d/src/game/readiness.ts');
{
    const pins = new Map(), state = { approachPin: null, pendingSnap: null };
    let ready = false, point = 'A';
    const deps = { placeAt: () => point, isReady: () => ready,
        pin(id, owner) { const s = pins.get(id) ?? new Set(); s.add(owner); pins.set(id, s); },
        release(id, owner) { pins.get(id)?.delete(owner); if (!pins.get(id)?.size)
            pins.delete(id); } };
    assert.equal(holdFor(deps, state, 1, 2), true);
    console.log('PASS walk_hold');
    holdSnap(deps, state, { id: 'A', x: 1, z: 2 });
    assert.equal(trySnap(deps, state.pendingSnap), false);
    ready = true;
    assert.equal(trySnap(deps, state.pendingSnap), true);
    console.log('PASS teleport_hold');
    assert.equal(holdFor(deps, state, 1, 2), false);
    assert.deepEqual([...pins.get('A')], ['teleport']);
    console.log('PASS approach_released_ready / owners_independent');
    ready = false;
    holdFor(deps, state, 1, 2);
    point = 'B';
    holdFor(deps, state, 3, 4);
    assert.deepEqual([...pins.get('A')], ['teleport']);
    assert.ok(pins.get('B').has('approach'));
    console.log('PASS approach_moved');
    holdSnap(deps, state, { id: 'B', x: 3, z: 4 });
    assert.equal(pins.has('A'), false);
    assert.equal(state.pendingSnap.id, 'B');
    ready = true;
    const executed = [];
    if (trySnap(deps, state.pendingSnap)) executed.push(state.pendingSnap.id);
    assert.deepEqual(executed, ['B']);
    console.log('PASS snap_replaced');
    point = null;
    assert.equal(holdFor(deps, state, 0, 0), false);
    clearSnap(deps, state);
    assert.equal(pins.size, 0);
}
// A teleport ends the old approach even if A never becomes ready and
// the avatar never supplies another walk input. Other owners survive.
{
    const pins = new Map(), state = { approachPin: null, pendingSnap: null };
    const deps = { placeAt: () => 'A', isReady: () => false,
        pin(id, owner) { const owners = pins.get(id) ?? new Set(); owners.add(owner); pins.set(id, owners); },
        release(id, owner) { pins.get(id)?.delete(owner); if (!pins.get(id)?.size) pins.delete(id); } };
    holdFor(deps, state, 1, 2);
    deps.pin('A', 'current');
    deps.pin('B', 'teleport');
    holdSnap(deps, state, { id: 'B', x: 100, z: 0 });
    assert.equal(state.approachPin, null);
    assert.deepEqual([...pins.get('A')], ['current']);
    assert.deepEqual([...pins.get('B')], ['teleport']);
    assert.equal(trySnap(deps, state.pendingSnap), false);
    assert.equal(pins.get('A').has('approach'), false);
    console.log('PASS teleport_ends_approach while stopped / owners_independent');
}
for (const name of ['entry_settled_far', 'entry_same_offer', 'entry_offer_gone', 'entry_dropped', 'entry_no_progress']) {
    let waits = 0, released = 0, requested = false, ready = false, offer = { key: 'A#door' };
    const result = await enterWhenReady({ requestNear() { requested = true; }, release(id, owner) { assert.equal(owner, 'entry'); released++; },
        sleep: () => new Promise(() => {}),
        async settled() {
            assert.ok(requested);
            waits++;
            if (name === 'entry_same_offer')
                offer = { key: 'A#door' };
            if (name === 'entry_offer_gone')
                offer = null;
            ready = name !== 'entry_settled_far' || waits === 2;
            if (name === 'entry_no_progress')
                ready = false;
        },
        isReady: () => ready, stillValid: key => offer?.key === key, exists: () => name !== 'entry_dropped', canProgress: () => name !== 'entry_no_progress' }, 'A', 'A#door');
    assert.equal(result, ['entry_settled_far', 'entry_same_offer'].includes(name));
    assert.equal(waits, name === 'entry_settled_far' ? 2 : 1);
    assert.equal(released, 1);
    console.log('PASS', name, '/ entry_pin_released');
}
// Source guards ensure the pure rules precede movement in real renderer paths.
{
    assertBefore(fn('correctTo'), 'clearApproach(', 'npcs.positionOf(');
    const snapTick = main.slice(main.indexOf('if (pendingSnap && trySnap('));
    assertBefore(snapTick, 'clearApproach(', 'npcs.snapPlayerTo(');
    const body = fn('reconcileAvatarPos');
    assertBefore(body, 'pollIsStale(', 'clearSnap(');
    assertBefore(body, 'clearSnap(', 'isOwnEcho(');
    assertBefore(body, 'holdSnap(', 'correctTo(me.pos)');
    const entry = fn('enterOfferedLocation'), guard = entry.indexOf('if (!(await enterWhenReady(');
    assert.ok(guard >= 0);
    assertBefore(entry.slice(guard), 'return;', 'setPlayerTarget(');
    assertBefore(entry.slice(guard), 'return;', 'walkIn =');
    assert.match(fn('tickPosReport'), /\{\s*if \(pendingSnap\) return;/);
    const walk = main.slice(main.indexOf('({ x, z } = slideBlocked'));
    assertBefore(walk, 'holdFor(', 'walkGoal.set(');
    const seat = fn('reconcileAvatarPlace');
    assertBefore(seat, 'avatarSeated = true', "?.ring !== 'near'");
    assertBefore(seat, "?.ring !== 'near'", 'roomMarkers');
    console.log('PASS main readiness path guards');
}
for (const name of ['snap_superseded_free', 'snap_superseded_ready', 'snap_superseded_here']) {
    const pins = new Set(['A']), state = { pendingSnap: { id: 'A', x: 100, z: 0 } }, corrected = [];
    const point = name.endsWith('here') ? { x: 0, z: 0 } : { x: 20, z: 0 };
    const deps = { isReady: () => true, placeAt: () => name.endsWith('free') ? null : 'B', pin() { }, release(id) { pins.delete(id); } };
    const api = compile(['reconcileAvatarPos'], { getGameState: () => ({ mode: 'embodied' }), pollIsStale: () => false, ownSeatChangeAt: 0,
        isOwnEcho: () => false, sentSeqs: [], posSession: 'sessAAAA01', ownCorrectionAt: 0,
        syncCounters: { posCorr: 0, pos409: 0, travBack: 0, travFwd: 0, travErrMaxM: 0, arrive: 0, place: 0 },
        avatarDrive: { kind: 'PLAYER' }, avatarSeated: false, posInFlight: false, walkIn: null, verticalRide: null, correction: null, npcs: { propEntryUnavailable: () => false, positionOf: () => ({ x: 0, z: 0 }) },
        avatarName: 'avatar', reportedPos: null, POS_SNAP_M: 1, CORRECT_WALK_M: 8, clearSnap: () => clearSnap(deps, state),
        holdSnap, readinessDeps: deps, readinessState: state, correctTo: p => corrected.push(p), THREE: { Vector3: class {
            } }, groundY: () => 0, engine: { flyTo() { } } }, 'let pendingSnap=readinessState.pendingSnap;');
    api.reconcileAvatarPos({ characters: [{ name: 'avatar', pos: point }] }, 1);
    assert.equal(state.pendingSnap, null);
    assert.equal(pins.size, 0);
    assert.equal(corrected.length, name.endsWith('here') ? 0 : 1);
    console.log('PASS', name);
}

// A stopped walker still releases an approach pin on the next ring tick.
{
    const state = { approachPin: 'A' }, released = [];
    const { tickStreamRings } = compile(['tickStreamRings'], {
        readinessState: state,
        readinessDeps: { isReady: () => true, release: (...args) => released.push(args) },
        places: new Map(), syncStreamPins() {},
    });
    tickStreamRings();
    assert.equal(state.approachPin, null);
    assert.deepEqual(released, [['A', 'approach']]);
    console.log('PASS approach_released_ready while stopped');
}

// NEU review: payload-only X holds a teleport until a ready record exists.
{
    const places = new Map(), map = { locations: [{ id: 'X' }] };
    const { placeAt } = compile(['placeAt'], { places, lastMap: map, firstMap: map,
        footprintCentre: () => ({ x: 100, z: 0 }), footprintBoundary: () => [[-5,-5],[5,-5],[5,5],[-5,5]],
        footprintYaw: () => 0, polygonArea: () => 100,
        tileContains: (p, x, z) => Math.abs(x - p.center.x) <= 5 && Math.abs(z - p.center.z) <= 5 });
    const state = { approachPin: null, pendingSnap: null }, pins = [], corrected = [];
    let ready = false;
    const deps = { placeAt, isReady: id => places.has(id) && ready, pin: (...p) => pins.push(p), release() {} };
    const id = placeAt(100, 0);
    assert.equal(id, 'X');
    if (id && !deps.isReady(id)) holdSnap(deps, state, { id, x: 100, z: 0 });
    else corrected.push('incorrect early correction');
    assert.deepEqual(corrected, []);
    assert.deepEqual(pins, [['X', 'teleport']]);
    assert.equal(trySnap(deps, state.pendingSnap), false);
    places.set('X', { loc: { id: 'X' }, center: { x: 100, z: 0 }, area: 100 });
    assert.equal(trySnap(deps, state.pendingSnap), false);
    ready = true;
    assert.equal(trySnap(deps, state.pendingSnap), true);
    console.log('PASS payload_only_teleport NEU');
}
// NEU review: a failed load never settles; cancellation after two timed rounds releases once.
{
    let sleeps = 0, released = 0;
    const result = await Promise.race([enterWhenReady({ requestNear() {}, release() { released++; },
        settled: () => new Promise(() => {}), sleep: async ms => { assert.equal(ms, 1000); sleeps++; },
        exists: () => true, stillValid: () => sleeps < 2, isReady: () => false, canProgress: () => true,
    }, 'X', 'offer'), new Promise(resolve => setTimeout(() => resolve('stuck'), 100))]);
    assert.equal(result, false);
    assert.equal(sleeps, 2);
    assert.equal(released, 1);
    console.log('PASS entry_cancelled_unsettled NEU');
}
{
    const apply = fn('applyWorldMap');
    assertBefore(apply, 'rebuildMovedTiles(map)', 'reconcileAvatarPlace(');
    assertBefore(apply, 'ensurePlace(loc)', 'reconcileAvatarPos(');
    const placement = fn('computeNpcPlacements');
    assertBefore(placement, 'avatarWaitsForPlace(', 'travellerState(');
    assert.match(placement, /hidden: true/);
    const start = main.indexOf('} else if (openLocationId) {');
    assert.ok(start >= 0);
    const end = main.indexOf('let open: Tile', start);
    assert.ok(end >= 0);
    assert.ok(start < end);
    const frame = main.slice(start, end);
    assert.match(frame, /places.get\(openLocationId\)/);
    assert.doesNotMatch(frame, /residency.get/);
    assert.match(fn('downResident'), /storeyByPlace.set\(id, resident.tile.levelFilter\)/);
    assertBefore(fn('upResident'), 'restoreStorey(tile)', 'resident.ready = true');
    console.log('PASS review integration guards NEU');
}
const { avatarWaitsForPlace } = await load('client3d/src/game/readiness.ts');
for (const resident of [undefined, { ring: 'far', ready: true }, { ring: 'near', ready: false }, { ring: 'near', ready: true }]) {
    assert.equal(avatarWaitsForPlace(true, 'X', resident), resident?.ring !== 'near' || resident?.ready !== true);
    assert.equal(avatarWaitsForPlace(false, 'X', resident), false);
    assert.equal(avatarWaitsForPlace(true, '', resident), false);
}
console.log('PASS avatar_arrival_readiness NEU');

// NEU review: readiness is revoked synchronously, even while rebuild work is queued.
{
    const resident = { ready: true }, residency = new Map([['X', resident]]);
    const { rebuildTile } = compile(['rebuildTile'], { places: new Map(), residency,
        engine: { scene: { add() {} } }, buildPlace: loc => ({ loc, anchor: {} }),
        driver: { hasJob: () => false, rebuild() { assert.equal(resident.ready, false); } } });
    rebuildTile(undefined, { id: 'X' });
    console.log('PASS queued_rebuild_revokes_ready NEU');
}

// Every control entry must respect the same arrival hold as hidden placement.
{
    const action = name => {
        const start = main.indexOf(`gameActions.${name} = () => {`);
        assert.ok(start >= 0);
        const end = main.indexOf('\n  };', start);
        assert.ok(end >= 0);
        assert.ok(start < end);
        return main.slice(start, end);
    };
    const entry = action('enterEmbodied');
    assertBefore(entry, 'avatarWaitsForPlace(', 'enterEmbodied(embody)');
    assertBefore(entry, "toastQuiet('Loading this place…')", 'enterEmbodied(embody)');
    assert.match(entry, /pendingArrivalTakeControl = true/);
    assert.match(entry, /pendingArrivalTakeControl = false/);
    const control = action('takeControl');
    assert.doesNotMatch(control, /avatarWaitsForPlace\(/);
    assert.match(control, /gameActions\.enterEmbodied\?\.\(\)/);
    const retryStart = main.indexOf('if (bootDone && pendingArrivalTakeControl) {');
    assert.ok(retryStart >= 0);
    const retryEnd = main.indexOf('\n    }', retryStart);
    assert.ok(retryEnd >= 0);
    assert.ok(retryStart < retryEnd);
    const retry = main.slice(retryStart, retryEnd);
    assertBefore(retry, "getGameState().mode === 'overview'", 'gameActions.enterEmbodied?.()');
    assert.doesNotMatch(retry, /gameActions\.takeControl/);
    assertBefore(retry, 'pendingArrivalTakeControl', 'gameActions.enterEmbodied?.()');
    assert.doesNotMatch(retry, /pendingArrivalTakeControl = false/);
    const escapeStart = main.indexOf("if (e.key !== 'Escape'");
    assert.ok(escapeStart >= 0);
    const escapeEnd = main.indexOf('\n  }, true);', escapeStart);
    assert.ok(escapeEnd >= 0);
    assert.ok(escapeStart < escapeEnd);
    const escape = main.slice(escapeStart, escapeEnd);
    assertBefore(escape, 'cancelPendingControl(', "getGameState().mode === 'embodied'");
    const plaque = await readFile('client3d/src/hud/CharacterPlaque.tsx', 'utf8');
    assert.match(plaque, /gameActions\.enterEmbodied\?\.\(\)/);
    const keyStart = main.indexOf("if (e.key.toLowerCase() !== 'f'");
    assert.ok(keyStart >= 0);
    const keyEnd = main.indexOf('\n  });', keyStart);
    assert.ok(keyEnd >= 0);
    assert.ok(keyStart < keyEnd);
    const key = main.slice(keyStart, keyEnd);
    assert.match(key, /gameActions\.enterEmbodied\?\.\(\)/);
    for (const source of [plaque, key]) {
        assert.doesNotMatch(source, /setGameState\s*\(\s*\{[^}]*\bmode\s*:/);
        assert.doesNotMatch(source, /(?<!\.)\benterEmbodied\s*\(/);
    }
    // Only the gated action may invoke the mode setter in embody.ts.
    assert.equal((main.match(/\benterEmbodied\(embody\)/g) ?? []).length, 1);
    assert.doesNotMatch(main, /setGameState\s*\(\s*\{\s*mode\s*:\s*['"]embodied['"]/);
    console.log('PASS enter_embodied_arrival_guard');
}

// Cancellation also stops the model-readiness retry and clears its loading note.
{
    const notes = [];
    compile(['cancelPendingControl'], { setBootNote: note => notes.push(note), assert }, `
        let pendingArrivalTakeControl = true, pendingTakeControl = true;
        cancelPendingControl();
        assert.equal(pendingArrivalTakeControl, false);
        assert.equal(pendingTakeControl, false);
        cancelPendingControl();
    `);
    assert.deepEqual(notes, [null, null]);
    console.log('PASS cancel_pending_control');
}
