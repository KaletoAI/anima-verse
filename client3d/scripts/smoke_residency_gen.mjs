#!/usr/bin/env node
/** NEU: residency.ts and SceneLibrary.forget absent on a241a8aa.
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
async function load(path) { const r = await build({ entryPoints: [path], bundle: true, write: false, format: 'esm', platform: 'node' }); return import(`data:text/javascript;base64,${Buffer.from(r.outputFiles[0].text).toString('base64')}`); }
const { createResidencyDriver } = await load('client3d/src/game/residency.ts');
const { createFocusQueue } = await load('client3d/src/game/focusQueue.ts');
const flush = async () => { for (let i = 0; i < 100; i++)
    await Promise.resolve(); };
const deferred = () => { let resolve; const promise = new Promise(r => resolve = r); return { promise, resolve }; };
function assertBefore(source, first, second) {
    const firstIndex = source.indexOf(first), secondIndex = source.indexOf(second);
    assert.ok(firstIndex >= 0, `missing first marker: ${first}`);
    assert.ok(secondIndex >= 0, `missing second marker: ${second}`);
    assert.ok(firstIndex < secondIndex, `${first} must precede ${second}`);
}
function fixture() {
    const calls = [], live = new Map(), wait = [], timers = [];
    let active = 0, max = 0, rollback = 0, fail = false;
    const driver = createResidencyDriver({ up: async (id, p, from, alive) => { calls.push(['up', id, p, from]); active++; max = Math.max(max, active); const gate = wait.shift(); if (gate)
            await gate.promise; active--; if (!alive()) {
            rollback++;
            return 'aborted';
        } if (fail) {
            fail = false;
            return 'failed';
        } live.set(id, p); return 'ok'; }, down: (id, p, from) => { calls.push(['down', id, p, from]); if (from === 'far')
            live.delete(id); } }, createFocusQueue({ max: 2 }), { setTimeout(fn, ms) { const t = { fn, ms }; timers.push(t); return t; }, clearTimeout(t) { const i = timers.indexOf(t); if (i >= 0)
            timers.splice(i, 1); } });
    return { driver, calls, live, wait, timers, get max() { return max; }, get rollback() { return rollback; }, fail() { fail = true; } };
}
for (const name of ['up_down', 'retarget_mid_await', 'flip_flop', 'rebuild_during_shell', 'rebuild_at_near', 'drop_during_fetch', 'drop_during_mount', 'rediscover_after_drop', 'settled_waits_rebuild', 'hasJob', 'fetch_retry']) {
    const f = fixture(), d = f.driver;
    if (name === 'up_down') {
        d.want('X', 1, 'near', () => 0);
        await d.settled('X');
        assert.equal(d.ring('X'), 'near');
        assert.equal(f.calls.length, 2);
        d.want('X', 1, 'gone', () => 0);
        await d.settled('X');
        assert.equal(f.calls.length, 4);
    }
    else if (['rebuild_at_near', 'settled_waits_rebuild', 'hasJob'].includes(name)) {
        d.want('X', 1, 'near', () => 0);
        assert.equal(d.hasJob('X'), true);
        await d.settled('X');
        assert.equal(d.hasJob('X'), false);
        d.rebuild('X', 2);
        assert.equal(d.hasJob('X'), true);
        let done = false;
        const gate = deferred();
        f.wait.push(gate);
        const settled = d.settled('X').then(() => done = true);
        await flush();
        assert.equal(done, false);
        gate.resolve();
        await settled;
        assert.equal(f.live.get('X'), 2);
        assert.equal(d.ring('X'), 'near');
        assert.deepEqual(f.calls.slice(2).map(c => [c[0], c[2], c[3]]), [['down', 1, 'near'], ['down', 1, 'far'], ['up', 2, 'gone'], ['up', 2, 'far']]);
    }
    else if (name === 'fetch_retry') {
        f.fail();
        d.want('X', 1, 'far', () => 0);
        await flush();
        assert.equal(d.ring('X'), 'gone');
        assert.equal(d.hasJob('X'), false);
        assert.equal(f.timers[0].ms, 5000);
        f.timers.shift().fn();
        await d.settled('X');
        assert.equal(d.ring('X'), 'far');
    }
    else {
        const gate = deferred();
        f.wait.push(gate);
        d.want('X', 1, name === 'retarget_mid_await' ? 'near' : 'far', () => 0);
        await flush();
        if (name === 'flip_flop') {
            d.want('X', 1, 'gone', () => 0);
            d.want('X', 1, 'far', () => 0);
        }
        else if (name === 'rebuild_during_shell')
            d.rebuild('X', 2);
        else if (name === 'rediscover_after_drop') {
            d.drop('X');
            d.want('X', 2, 'far', () => 0);
        }
        else if (name === 'retarget_mid_await')
            d.want('X', 1, 'gone', () => 0);
        else
            d.drop('X');
        gate.resolve();
        await flush();
        await d.settled('X');
        assert.equal(f.rollback, 1);
        assert.equal(d.ring('X'), ['flip_flop', 'rebuild_during_shell', 'rediscover_after_drop'].includes(name) ? 'far' : 'gone');
        assert.equal(f.live.size, d.ring('X') === 'far' ? 1 : 0);
        assert.equal(f.timers.length, 0);
        if (name === 'rediscover_after_drop' || name === 'rebuild_during_shell')
            assert.equal(f.live.get('X'), 2);
    }
    console.log('PASS', name);
}
{
    const f = fixture(), gates = Array.from({ length: 5 }, deferred);
    for (let i = 0; i < 5; i++) {
        f.wait.push(gates[i]);
        f.driver.want(String(i), 1, 'far', () => i);
    }
    await flush();
    assert.equal(f.max, 2);
    assert.equal(f.calls.length, 2);
    for (const gate of gates)
        gate.resolve();
    await Promise.all(Array.from({ length: 5 }, (_, i) => f.driver.settled(String(i))));
    assert.equal(f.max, 2);
    assert.equal(f.live.size, 5);
    console.log('PASS queue_max');
}
// NEU hand oracle (G1b): cancelling a failed gone->far retry satisfies gone.
// Both waiters resolve; no timer/up remains; rebuild is inert after deletion.
{
    const f = fixture(), d = f.driver;
    f.fail();
    d.want('X', 1, 'far', () => 0);
    await flush();
    assert.equal(f.timers.length, 1);
    let resolved = 0;
    const waiters = [d.settled('X'), d.settled('X')].map(p => p.then(() => resolved++));
    d.want('X', 1, 'gone', () => 0);
    await flush();
    assert.equal(resolved, 2, 'cancelled retry releases every settled waiter');
    await Promise.all(waiters);
    assert.equal(f.timers.length, 0);
    assert.equal(d.ring('X'), 'gone');
    assert.equal(d.hasJob('X'), false);
    d.rebuild('X', 2);
    assert.equal(d.hasJob('X'), false, 'gone entry was deleted');
    await flush();
    assert.deepEqual(f.calls, [['up', 'X', 1, 'gone']]);
    assert.equal(f.live.size, 0);
    console.log('PASS cancelled_retry_settled NEU');
}
// Extract the real library, avoiding unrelated renderer imports.
const recipe = await readFile('client3d/src/scene/sceneRecipe.ts', 'utf8');
const librarySource = recipe.slice(recipe.indexOf('export class SceneLibrary'), recipe.indexOf('// ── Verify'));
const makeLibrary = (fetch) => new Function('getLocationScene', 'createFocusQueue', transformSync(librarySource.replace('export class', 'class') + '\nreturn SceneLibrary;', { loader: 'ts', format: 'cjs' }).code)(fetch, createFocusQueue);
for (const name of ['sweep_forgotten', 'sweep_forget_unstarted', 'forget_then_request', 'forget_then_request_reverse', 'request_dedup']) {
    const pending = [], events = [];
    const C = makeLibrary(id => { const gate = deferred(); pending.push({ id, ...gate }); return gate.promise; });
    const lib = new C();
    lib.onScene = (id) => events.push(id);
    if (name === 'request_dedup') {
        const a = lib.request('X'), b = lib.request('X');
        assert.equal(a, b);
        assert.equal(pending.length, 1);
        const scene = { signature: 'new' };
        pending[0].resolve(scene);
        assert.equal(await a, scene);
        assert.equal(await b, scene);
    }
    else {
        const sweep = lib.sweep(name === 'sweep_forget_unstarted' ? ['X', 'Y'] : ['X']);
        await flush();
        lib.forget(name === 'sweep_forget_unstarted' ? 'Y' : 'X');
        let newer;
        if (name.startsWith('forget_then_request'))
            newer = lib.request('X');
        const old = { signature: 'old' }, fresh = { signature: 'fresh' };
        if (name.endsWith('reverse')) {
            pending[1].resolve(fresh);
            await newer;
        }
        pending[0].resolve(old);
        await sweep;
        if (newer) {
            pending[1].resolve(fresh);
            assert.equal(await newer, fresh);
            assert.equal(lib.get('X'), fresh);
        }
        else if (name === 'sweep_forget_unstarted') {
            assert.equal(pending.length, 1);
            assert.equal(lib.has('Y'), false);
            assert.deepEqual(events, ['X']);
        }
        else {
            assert.equal(lib.has('X'), false);
            assert.deepEqual(events, []);
        }
    }
    console.log('PASS', name);
}
const main = await readFile('client3d/src/main.ts', 'utf8');
const ts = await import('typescript');
const ast = ts.createSourceFile('main.ts', main, ts.ScriptTarget.Latest, true);
function fn(name) { let found; function visit(n) { if (ts.isFunctionDeclaration(n) && n.name?.text === name)
    found = n.getText(ast); ts.forEachChild(n, visit); } visit(ast); assert.ok(found, `main function ${name} exists`); return found; }
function compile(names, deps, tail = '') { deps = { restoreStorey() {}, ...deps }; return new Function(...Object.keys(deps), transformSync(names.map(fn).join('\n') + '\n' + tail + '\nreturn {' + names.join(',') + '};', { loader: 'ts' }).code)(...Object.values(deps)); }
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
    assertBefore(body, 'clearSnap(', 'if (reportedPos');
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
        avatarSeated: false, posInFlight: false, walkIn: null, verticalRide: null, correction: null, npcs: { positionOf: () => ({ x: 0, z: 0 }) },
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
