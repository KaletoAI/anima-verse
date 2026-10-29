#!/usr/bin/env node
/**
 * Smoke check for the shared test-vector loader (shared/test-vectors/vectors.mjs) —
 * the comparison and loading rules of format `anima-test-vectors/1` as written in
 * shared/test-vectors/README.md. The cases are hand-written here on purpose: this checks
 * the loader, so it must not depend on a vector file the loader reads.
 *
 * Usage:  node shared/test-vectors/smoke_vectors_format.mjs
 *
 * Expectations (from the README rules):
 * [1] null only equals null (not 0, not undefined, not a missing key)
 * [2] -0 equals 0, both ways
 * [3] eps boundary at 1e-9: 1.0 vs 1.0 + 5e-10 equal, 1.0 vs 1.0 + 2e-9 not
 * [4] objects compare only the expectation's keys (extra actual keys ignored, missing ones fail)
 * [5] arrays must have the same length
 * [6] an actual NaN (or Infinity) fails against any number expectation
 * [7] a non-finite number (1e400 parses to Infinity), a NaN literal, a wrong format string or a
 *     case without label/fn/args/expect is a load error
 * [8] {"$fixture", "$with"} overrides top-level keys only and never mutates the fixture
 * [9] an fn missing from the dispatch table throws before any case runs
 * [10] {"$throws": true} passes only when the call throws
 */
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { loadVectors, loadVectorFile, near, parseVectors, resolveArgs, runVectors } from './vectors.mjs';

let fails = 0;
let oks = 0;
const check = (ok, msg) => {
  console.log(`  ${ok ? 'ok  ' : 'FAIL'} ${msg}`);
  if (ok) oks++; else fails++;
};
const throws = (f) => { try { f(); return false; } catch { return true; } };
const file = (cases, fixtures) => ({ format: 'anima-test-vectors/1', source: 'inline', fixtures, cases });

console.log('\n[1] null');
check(near(null, null).ok, 'null == null');
check(!near(null, 0).ok, 'null != 0');
check(!near(0, null).ok, '0 != null');
check(!near(null, undefined).ok, 'null != undefined');
check(!near({ a: null }, {}).ok, 'expected null key missing in actual fails');

console.log('\n[2] -0');
check(near(0, -0).ok && near(-0, 0).ok, '-0 == 0 both ways');

console.log('\n[3] eps boundary');
check(near(1.0, 1.0 + 5e-10, 1e-9).ok, '1.0 vs 1.0+5e-10 equal at eps 1e-9');
check(!near(1.0, 1.0 + 2e-9, 1e-9).ok, '1.0 vs 1.0+2e-9 not equal at eps 1e-9');
check(near(1.0, 1.0 + 5e-10).ok && !near(1.0, 1.0 + 2e-9).ok, 'default eps is 1e-9');

console.log('\n[4] objects');
check(near({ a: 1 }, { a: 1, b: 'extra' }).ok, 'extra actual keys ignored');
check(!near({ a: 1, b: 2 }, { a: 1 }).ok, 'missing expected key fails');
check(near({ p: { x: 1 } }, { p: { x: 1, y: 9 } }).ok, 'nested objects compare only expected keys');
check(!near({ a: 1 }, [1]).ok, 'array is not an object');

console.log('\n[5] arrays');
check(!near([1, 2], [1, 2, 3]).ok, 'longer actual fails');
check(!near([1, 2, 3], [1, 2]).ok, 'shorter actual fails');
check(near([0, [1, 2]], [-0, [1, 2]]).ok, 'nested arrays elementwise');

console.log('\n[6] NaN / Infinity in actual');
check(!near(0, NaN).ok, 'NaN != 0');
check(!near(1, NaN, 1e300).ok, 'NaN fails even with a huge eps');
check(!near({ v: 0 }, { v: NaN }).ok, 'NaN inside an object fails');
check(!near(1e308, Infinity, 1e300).ok, 'Infinity fails');
check(!near(null, NaN).ok, 'NaN != null');

console.log('\n[7] load errors');
const tmp = await mkdtemp(join(tmpdir(), 'vectors-format-'));
try {
  const good = '{"format":"anima-test-vectors/1","source":"x","cases":[{"label":"a","fn":"f","args":[],"expect":1}]}';
  const write = async (name, text) => { const p = join(tmp, name); await writeFile(p, text, 'utf8'); return p; };
  const pGood = await write('good.json', good);
  check(!throws(() => loadVectorFile(pGood)), 'a well-formed file loads');
  check(throws(() => loadVectorFile(join(tmp, 'absent.json'))), 'absent file throws');
  const pInf = await write('inf.json', good.replace('"expect":1', '"expect":1e400'));
  check(throws(() => loadVectorFile(pInf)), '1e400 (parses to Infinity) is a load error');
  const pInfArg = await write('infarg.json', good.replace('"args":[]', '"args":[-1e400]'));
  check(throws(() => loadVectorFile(pInfArg)), 'non-finite number in args is a load error');
  const pNaN = await write('nan.json', good.replace('"expect":1', '"expect":NaN'));
  check(throws(() => loadVectorFile(pNaN)), 'NaN literal is a load error');
  const pFmt = await write('fmt.json', good.replace('anima-test-vectors/1', 'anima-test-vectors/2'));
  check(throws(() => loadVectorFile(pFmt)), 'wrong format string is a load error');
  for (const key of ['label', 'fn', 'args', 'expect']) {
    const c = { label: 'a', fn: 'f', args: [], expect: 1 };
    delete c[key];
    check(throws(() => parseVectors(JSON.stringify(file([c])))), `case without "${key}" is a load error`);
  }
  check(!throws(() => parseVectors(JSON.stringify(file([{ label: 'a', fn: 'f', args: [], expect: null }])))),
    'expect: null is a valid expectation');
  check(throws(() => parseVectors(JSON.stringify(file([{ label: 'a', fn: 'f', args: [{ $fixture: 'NOPE' }], expect: 1 }])))),
    'unknown fixture is a load error');
  check(throws(() => parseVectors(JSON.stringify(file([
    { label: 'a', fn: 'f', args: [], expect: 1 }, { label: 'a', fn: 'f', args: [], expect: 2 }])))),
    'duplicate label is a load error');
} finally { await rm(tmp, { recursive: true, force: true }); }

console.log('\n[8] $fixture / $with');
const fixtures = { P: { a: 1, b: { c: 2 } }, L: [1, 2] };
const r = resolveArgs([{ $fixture: 'P', $with: { b: { d: 3 }, e: 4 } }, 7], fixtures);
check(r[0].a === 1 && r[0].e === 4, '$with adds/keeps top-level keys');
check(near({ b: { d: 3 } }, r[0]).ok && !('c' in r[0].b), '$with replaces a nested object whole (shallow)');
check(r[1] === 7, 'plain args pass through');
check(fixtures.P.b.c === 2 && !('e' in fixtures.P), 'fixture itself is not mutated');
const plain = resolveArgs([{ $fixture: 'L' }], fixtures);
plain[0].push(99);
check(fixtures.L.length === 2, 'resolved fixture is a copy');
check(near([[[1, 2]]], resolveArgs([[{ $fixture: 'L' }]], fixtures)).ok, 'fixture nested inside an array arg resolves');
check(throws(() => resolveArgs([{ $fixture: 'L', $with: { a: 1 } }], fixtures)), '$with on an array fixture throws');

console.log('\n[9] unknown fn');
const lines = [];
const quiet = { log: (l) => lines.push(l) };
let ran = false;
check(throws(() => runVectors(file([
  { label: 'known', fn: 'f', args: [], expect: 1 },
  { label: 'unknown', fn: 'g', args: [], expect: 1 }]), { f: () => { ran = true; return 1; } }, quiet)),
'fn missing from the table throws');
check(!ran, '... before any case ran');

console.log('\n[10] $throws');
const boom = () => { throw new Error('boom'); };
const t1 = runVectors(file([{ label: 't', fn: 'boom', args: [], expect: { $throws: true } }]), { boom }, quiet);
check(t1.passed === 1 && t1.failed === 0, 'throwing call passes a $throws case');
const t2 = runVectors(file([{ label: 't', fn: 'ok', args: [], expect: { $throws: true } }]), { ok: () => 1 }, quiet);
check(t2.passed === 0 && t2.failed === 1, 'returning call fails a $throws case');
const t3 = runVectors(file([{ label: 't', fn: 'boom', args: [], expect: 1 }]), { boom }, quiet);
check(t3.passed === 0 && t3.failed === 1, 'unexpected throw fails a value case');
const t4 = runVectors(file([{ label: 't', fn: 'nan', args: [], expect: 0 }]), { nan: () => NaN }, quiet);
check(t4.failed === 1, 'runVectors fails a NaN result');
check(throws(() => parseVectors(JSON.stringify(file([{ label: 't', fn: 'f', args: [], expect: { $throws: false } }])))),
  '{"$throws": false} is a load error');
const t5 = runVectors(file([{ label: 'e', fn: 'f', args: [[1, 2], 3], expect: 6, eps: 0 }]),
  { f: (xs, k) => xs.length * k }, quiet);
check(t5.passed === 1, 'args are spread into the call; eps 0 allowed');

console.log('\n[12] exact string sentinels in arguments only');
const sentinels = ['$NaN', '$Infinity', '$-Infinity', '$undefined'];
const decoded = resolveArgs(sentinels);
check(Number.isNaN(decoded[0]), '$NaN decodes to NaN');
check(decoded[1] === Infinity, '$Infinity decodes to positive Infinity');
check(decoded[2] === -Infinity, '$-Infinity decodes to negative Infinity');
check(decoded[3] === undefined && decoded.length === 4, '$undefined preserves an undefined array slot');
check(near(['x$NaN', '$Inf', '$Infinity suffix', ' $undefined'],
  resolveArgs(['x$NaN', '$Inf', '$Infinity suffix', ' $undefined'])).ok, 'non-exact strings stay strings');
const sf = parseVectors(JSON.stringify(file([
  {label: 'sentinels', fn: 'inspect', args: [{nested: sentinels},
    {$fixture: 'P', $with: {v: '$undefined'}}], expect: '$NaN'},
], {P: {v: 1, nested: ['$Infinity']}})));
const sa = resolveArgs(sf.cases[0].args, sf.fixtures);
check(Number.isNaN(sa[0].nested[0]) && sa[0].nested[3] === undefined, 'nested arguments decode');
check(sa[1].nested[0] === Infinity && Object.hasOwn(sa[1], 'v') && sa[1].v === undefined,
  'fixture copies and shallow overrides decode without losing undefined keys');
check(sf.fixtures.P.nested[0] === '$Infinity' && sf.fixtures.P.v === 1, 'raw fixtures are unchanged');
check(sf.cases[0].expect === '$NaN', 'expectations stay literal strings');
check(runVectors(sf, {inspect: (a, b) => Number.isNaN(a.nested[0]) && b.v === undefined ? '$NaN' : 'bad'},
  {log() {}}).passed === 1, 'runner receives decoded arguments');

console.log('\n[11] E4 files obey the shared format');
for (const name of ['scatter', 'scatter_rows', 'impostors', 'undergrowth', 'world_props']) {
  const vectors = loadVectors(name);
  check(vectors.cases.length > 0, `${name}: nonempty, validated labels, fixtures and finite numbers`);
}

console.log('\n[13] E6 files obey the shared format');
for (const name of ['travel', 'residency']) {
  const vectors = loadVectors(name);
  check(vectors.cases.length > 0 && vectors.cases.every(c => /^\[\d+\]/.test(c.label)),
    `${name}: validated numbered cases, fixtures and finite JSON numbers`);
  if (name === 'residency') check(vectors.cases.length === 18 && vectors.cases.every(c =>
    c.args[1].length === c.expect.length), '18 residency scenarios have one expected snapshot per step');
}

console.log('\n[14] E7 files obey the shared format');
for (const name of ['walk_control', 'collide', 'enter', 'embody', 'camera', 'prop_action_motion']) {
  const vectors = loadVectors(name);
  check(vectors.cases.every(c => /^\[\d+[a-z]?\]/.test(c.label)),
    `${name}: numbered cases, unique labels, resolved fixtures and finite JSON`);
}

console.log(fails ? `\n${fails} FAILED, ${oks} ok` : `\nall ok (${oks})`);
process.exit(fails ? 1 : 0);
