#!/usr/bin/env node
/**
 * Usage: node client3d/scripts/smoke_pos_echo.mjs
 * Hand derivation: sent [1,2,3] includes 2, not 9; another session or null
 * origin is foreign. Sending 1..65 to a 64-entry ring evicts only 1, leaving
 * 2..65 (64 numbers). A view switch must publish its revision before fetching;
 * every poll during the switch is discarded, including polls of the new view.
 * Token bytes 0..15 encode as 00,01,...,09,0a,...,0f: exactly 32 hex chars.
 * The HTTP crypto fixture exposes getRandomValues only, as on a LAN origin.
 */
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
console.log('Position echo: all checks passed');
