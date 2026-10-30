#!/usr/bin/env node
/**
 * Driver hand derivation: J1 is adopted, absence arrives, J2 replaces J1.
 * Input reserves 5: origin 4 cannot acknowledge it, 5 can; J2 wins over 5.
 * Refusal 6 retries 5, while 4 cannot decide it. Null differs from NO_CANCEL.
 * Floor 8 excludes 7 forever, and accepts 8.
 * Integration oracle: report 7 in flight -> server drive sets floor 8.
 * Arrival cannot make answer 7 valid again (ok, throttled, 409, or network).
 * A cancel reserves 8 while 7 is in flight; only 7 is in the sent ring until
 * its answer settles. Replacement drops reserved 8 rather than cancelling J2.
 * Usage: node client3d/scripts/smoke_pos_echo.mjs
 * Hand derivation: sent [1,2,3] includes 2, not 9; another session or null
 * origin is foreign. Sending 1..65 to a 64-entry ring evicts only 1, leaving
 * 2..65 (64 numbers). A view switch must publish its revision before fetching;
 * every poll during the switch is discarded, including polls of the new view.
 * Token bytes 0..15 encode as 00,01,...,09,0a,...,0f: exactly 32 hex chars.
 * The HTTP crypto fixture exposes getRandomValues only, as on a LAN origin.
 */
import { vectorChecks } from './embodyVectorDispatch.mjs';
import assert from 'node:assert/strict';
import { readFile, writeFile, mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { transformSync } from 'esbuild';
async function load(relative) {
  const dir = await mkdtemp(join(tmpdir(), 'pos-echo-'));
  try {
    const source = await readFile(new URL(relative, import.meta.url), 'utf8');
    const file = join(dir, 'module.mjs');
    await writeFile(file, transformSync(source, { loader:'ts', format:'esm' }).code);
    return await import(pathToFileURL(file).href);
  } finally { await rm(dir, { recursive:true, force:true }); }
}
function check(label, got, want) { assert.deepEqual(got,want,label); console.log('PASS',label); }
const vectorCase = vectorChecks(check, ["embody"]);

const m = await load('../src/game/posEcho.ts');
const A = 'sessAAAA01', B = 'sessBBBB02';
const ring = []; for (const s of [1, 2, 3]) m.pushSeq(ring, s);
check('echo own',        m.isOwnEcho(ring, A, { session: A, seq: 2 }), true);
check('not sent',        m.isOwnEcho(ring, A, { session: A, seq: 9 }), false);
check('other session',   m.isOwnEcho(ring, A, { session: B, seq: 2 }), false);
check('foreign write',   m.isOwnEcho(ring, A, null), false);
const big = []; for (let s = 1; s <= 65; s++) m.pushSeq(big, s);   // cap 64
check('evicted',         m.isOwnEcho(big, A, { session: A, seq: 1 }), false);
check('kept',            m.isOwnEcho(big, A, { session: A, seq: 2 }), true);
check('cap', big.length, 64);
const main = await readFile(new URL('../src/main.ts', import.meta.url), 'utf8');
const tokenStatement = main.match(/const posSession = .*;/)[0];
const httpCrypto = { getRandomValues(bytes) {
  assert.equal(bytes.length, 16);
  for (let i = 0; i < bytes.length; i++) bytes[i] = i;
  return bytes;
} };
const token = new Function('crypto', `${tokenStatement} return posSession;`)(httpCrypto);
check('HTTP session token', token, '000102030405060708090a0b0c0d0e0f');
check('session token format', /^[A-Za-z0-9_-]{8,64}$/.test(token), true);
const body = main.slice(main.indexOf('async function applyShowAll('), main.indexOf('gameActions.setShowAll'));
check('view revision before fetch', body.indexOf('viewRev += 1') < body.indexOf('api.getWorldMap('), true);
check('view flag before fetch', body.indexOf('showAll = on') < body.indexOf('api.getWorldMap('), true);
check('poll blocked during switch', /if \(p.viewRev !== viewRev \|\| viewSwitchBusy\) return;/.test(main), true);
const { avatarDriver: D, NO_CANCEL } = m;
const P = { kind: 'PLAYER' };
const pay = (hasRoute, journeyId, originOwnSeq = null) => ({ kind: 'payload', hasRoute, journeyId, originOwnSeq });
let r = D(P, pay(true, 'J1'), NO_CANCEL);                       check('adopt', r.state, { kind: 'SERVER', j: 'J1' });
r = D({ kind: 'SERVER', j: 'J1' }, pay(false, null), NO_CANCEL); check('arrive', r.state, P);
r = D({ kind: 'SERVER', j: 'J1' }, pay(true, 'J2'), NO_CANCEL);  check('replace', r.state, { kind: 'SERVER', j: 'J2' });
r = D({ kind: 'SERVER', j: 'J1' }, { kind: 'input', firstSeq: 5 }, NO_CANCEL);
check('cancel', r.state, { kind: 'CANCELLING', j: 'J1', s: 5 }); check('cancelled', r.cancelled, 'J1');
const C = { kind: 'CANCELLING', j: 'J1', s: 5 };
check('stale echo keeps', D(C, pay(true, 'J1', 4), 'J1').state, C);
check('ack',              D(C, pay(true, 'J1', 5), 'J1').state, P);
check('gone',             D(C, pay(false, null), 'J1').state, P);
check('replace wins over ack', D(C, pay(true, 'J2', 5), 'J1').state, { kind: 'SERVER', j: 'J2' });
const rr = D(C, { kind: 'refused', seq: 6 }, 'J1');            // retry after a throttled 5
check('refused', rr.state, { kind: 'SERVER', j: 'J1' }); check('refused clears', rr.cancelled, NO_CANCEL);
check('refused older ignored', D(C, { kind: 'refused', seq: 4 }, 'J1').state, C);
check('no re-adopt cancelled', D(P, pay(true, 'J1'), 'J1').state, P);
check('legacy_null', D(P, pay(true, null), NO_CANCEL).state, { kind: 'SERVER', j: null });   // Review focus 5
check('legacy same', D({ kind: 'SERVER', j: null }, pay(true, null), NO_CANCEL).state, { kind: 'SERVER', j: null });
check('input in PLAYER is no-op', D(P, { kind: 'input', firstSeq: 9 }, NO_CANCEL).state, P);
// A cancelled journey stays suppressed after acknowledgement (R5-17).
vectorCase("[33] " + ('suppress own'));
vectorCase("[33] " + ('suppress other'));
vectorCase("[33] " + ('server no supp.'));
vectorCase("[33] " + ('suppress legacy'));
vectorCase("[33] " + ('PLAYER suppresses remembered J'));
vectorCase("[33] " + ('PLAYER allows legacy null'));
// only answers the automaton still owns may correct the figure (round 2, finding 3)
vectorCase("[34] " + ('answer player'));
vectorCase("[34] " + ('answer server'));
vectorCase("[34] " + ('answer pre-cancel'));
vectorCase("[34] " + ('answer cancel'));
vectorCase("[34] " + ('answer after'));
// Round 4: answers to reports numbered before the last server drive stay outgrown
vectorCase("[34] " + ('answer below floor'));
vectorCase("[34] " + ('answer at floor'));
vectorCase("[34] " + ('cancel at floor'));
// Execute the actual report and adoption functions with controlled network completion.
const reportCode = main.slice(main.indexOf('  function applyDriver('), main.indexOf('  /**\n   * The reporting tick,'));
function productionFunction(name) {
  const start = main.indexOf(`  function ${name}(`);
  const end = main.indexOf('\n  }', start) + 4;
  return main.slice(start, end);
}
function reportFixture() {
  const sent = [], effects = [];
  class ApiError extends Error { status = 409; pos = { x: 0, z: 0 }; }
  const deps = {
    ...m, effects,
    ownedPropRun: () => null, propMutationPending: false, propStateUncertain: false,
    propPreparation: { pending: false }, manualPropRelease: false, lastMap: null,
    propPositionDrainActive: false, positionDrain: { begin: () => () => {} },
    manualPropGate: { pending: false, withdrawn: () => false }, pollIsStale: (asked, corrected) => asked < corrected,
    performance: { now: () => 100 }, THREE: { Vector3: class { constructor(x,y,z) { Object.assign(this,{x,y,z}); } } },
    groundY: () => 0, tileAt: () => null, roomFloorY: () => null, clearSnap() {}, cancelRoute() {},
    npcs: { propEntryUnavailable: () => false, hasOwnMotion: () => false, setServerDriven: (...args) => effects.push(['drive', ...args]), positionOf: () => ({x:3,z:0}) },
    api: { ApiError, isAuthError: () => false, postPos: (...args) => new Promise((resolve,reject) => sent.push({args,resolve,reject})) },
    adoptReport: () => effects.push('adopt'), rememberRefused: () => effects.push('refused'),
    getGameState: () => ({mode:'embodied'}),
    avatarWaitsForPlace: () => false,
    travellerState: c => ({char:c, pos:c.pos, route:{journeyId:c.travel.journey_id}}), uiActions: { toast: () => effects.push('toast') },
    console: { warn() {} }, AbortController, setTimeout, clearTimeout,
  };
  const code = `
    let avatarDrive = {kind:'PLAYER'}, avatarCancelled = NO_CANCEL, answerFloor = 0;
    let posSeq = 7, pendingReport = null, posInFlight = false, posDirty = false;
    let pendingSnap = null, reportedPos = null, lastReportAt = 0, ownCorrectionAt = 0;
    let avatarLocalPos = null, localPos = {x:3,z:0};
    let avatarSeated = false, ownSeatChangeAt = 0, verticalRide = null;
    const POS_SNAP_M = 0.1, CORRECT_WALK_M = 100, hiddenChars = new Set(), shownPlacement = new Map(), residency = new Map(), mapStamp = 0;
    let walkIn = null, correction = null, quietReason = '', quietUntil = 0;
    const readinessDeps = {placeAt: () => null}, readinessState = {}, avatarName = 'avatar', posSession = 'sessAAAA01';
    const sentSeqs = [], syncCounters = {pos409:0,posCorr:0}, POS_TIMEOUT_MS = 5000, REFUSAL_QUIET_MS = 10;
    npcs.positionOf = () => localPos;
    function correctTo(point) { effects.push('correct'); localPos = {...point}; posDirty = false; }
    ${reportCode}
    ${productionFunction('reconcileAvatarPos')}
    ${productionFunction('computeNpcPlacements')}
    return {applyDriver, enterServerDrive, reportPosWithSeq, reserveReport, reconcileAvatarPos, computeNpcPlacements,
      removeFigure: () => { localPos = null; },
      state: () => ({avatarDrive, answerFloor, pendingReport, sentSeqs, posDirty, reportedPos, syncCounters, posInFlight}),
      input: () => { const r = avatarDriver(avatarDrive, {kind:'input', firstSeq:posSeq+1}, avatarCancelled);
        avatarDrive=r.state; avatarCancelled=r.cancelled; return reserveReport(3,0); },
      holdSnap: () => { pendingSnap = {}; }};
  `;
  const api = new Function(...Object.keys(deps), transformSync(code,{loader:'ts'}).code)(...Object.values(deps));
  const payload = journey => ({characters:[{name:'avatar', pos:{x:3,z:0}, travel:journey === undefined ? null : {journey_id:journey,waypoints:[[0,0],[10,0]]}}]});
  return {api,sent,effects,payload,ApiError};
}
for (const answer of ['ok','throttled','409','network']) {
  const f = reportFixture();
  const old = f.api.reportPosWithSeq(0,0,7);
  f.api.applyDriver(f.payload('J1'), 1);
  check(`floor ${answer}`, f.api.state().answerFloor, 8);
  f.api.applyDriver(f.payload(), 101);
  f.effects.length = 0;
  if (answer === '409') f.sent[0].reject(new f.ApiError());
  else if (answer === 'network') f.sent[0].reject(new Error('offline'));
  else f.sent[0].resolve({ok:answer === 'ok'});
  await old;
  check(`obsolete ${answer} effects`, f.effects, []);
  check(`obsolete ${answer} dirty`, f.api.state().posDirty, false);
  check(`obsolete ${answer} counter`, f.api.state().syncCounters.pos409, 0);
}
{
  const f = reportFixture();
  const old = f.api.reportPosWithSeq(0,0,7);
  f.api.applyDriver(f.payload('J1'), 1);
  check('reserved cancel number', f.api.input(), 8);
  check('cancel state before send', f.api.state().avatarDrive, {kind:'CANCELLING',j:'J1',s:8});
  check('reserved number is not sent', f.api.state().sentSeqs, [7]);
  f.sent[0].resolve({ok:true}); await old;
  check('cancel sent after previous', f.sent.map(p => p.args[3]), [7,8]);
  f.sent[1].resolve({ok:true}); await Promise.resolve();
}
{
  const f = reportFixture();
  const old = f.api.reportPosWithSeq(0,0,7);
  f.api.applyDriver(f.payload('J1'), 1); f.api.input();
  f.api.applyDriver(f.payload('J2'), 2);
  f.sent[0].resolve({ok:true}); await old;
  check('replacement drops queued cancel', f.sent.length, 1);
  check('replacement owns avatar', f.api.state().avatarDrive, {kind:'SERVER',j:'J2'});
}
{
  const f = reportFixture(); f.api.holdSnap();
  await f.api.reportPosWithSeq(0,0,8);
  check('pending snap does not send', f.api.state().sentSeqs, []);
  check('pending snap remains dirty', f.api.state().posDirty, true);
}
// R5-17(a): settled S leaves no in-flight shield. A stale J point (30,0)
// must not replace local (3,0), increment zero corrections, or erase a retry.
for (const answer of ['ok', 'throttled']) {
  for (const origin of [null, {session:B, seq:8}, {session:A, seq:8}]) {
    const f = reportFixture();
    f.api.applyDriver(f.payload('J1'), 1); f.api.input();
    f.sent[0].resolve({ok:answer === 'ok'}); await Promise.resolve();
    check(`settled S ${answer}`, f.api.state().posInFlight, false);
    const poll = f.payload('J1');
    Object.assign(poll.characters[0], {pos:{x:30,z:0}, pos_origin:origin});
    f.api.applyDriver(poll, 101);
    check(`delayed J state ${answer} ${origin?.session}`, f.api.state().avatarDrive.kind,
      origin?.session === A ? 'PLAYER' : 'CANCELLING');
    f.effects.length = 0;
    f.api.reconcileAvatarPos(poll, 101);
    check(`delayed J effects ${answer} ${origin?.session}`, f.effects, []);
    check('delayed J posCorr', f.api.state().syncCounters.posCorr, 0);
    check('delayed J retry dirtiness', f.api.state().posDirty, answer === 'throttled');
  }
}
// R5-17(b): acknowledgement still carries J1. Overview uses the current
// local (3,0); a missing/rebuilt figure uses the remembered (3,0), never (30,0).
{
  const f = reportFixture();
  f.api.applyDriver(f.payload('J1'), 1); f.api.input();
  f.sent[0].resolve({ok:true}); await Promise.resolve();
  const ack = f.payload('J1');
  Object.assign(ack.characters[0], {pos:{x:30,z:0}, pos_origin:{session:A, seq:8}});
  f.api.applyDriver(ack, 101);
  check('ack with J enters PLAYER', f.api.state().avatarDrive, P);
  for (const view of ['overview', 'rebuild']) {
    if (view === 'rebuild') f.api.removeFigure();
    const [placement] = f.api.computeNpcPlacements(ack);
    check(`${view} suppresses J`, placement.char.travel, null);
    check(`${view} local fallback`, {x:placement.pos.x,z:placement.pos.z}, {x:3,z:0});
    check(`${view} no route`, placement.route, undefined);
  }
  const replacement = f.payload('J2');
  f.api.applyDriver(replacement, 102);
  check('J2 adopted after ack', f.api.state().avatarDrive, {kind:'SERVER',j:'J2'});
  check('J2 reaches renderer', f.api.computeNpcPlacements(replacement)[0].route, {journeyId:'J2'});
}
console.log('Position echo: all checks passed');
