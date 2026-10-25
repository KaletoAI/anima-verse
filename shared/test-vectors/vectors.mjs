/**
 * Loader, comparison and runner for the shared test vectors (format `anima-test-vectors/1`,
 * spec in shared/test-vectors/README.md). Plain ESM, Node built-ins only.
 *
 * The browser smokes import this; the native client's C# tests implement the same
 * semantics against the same JSON files. Change the semantics only together with the
 * README and the C# loader.
 */
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { inspect } from 'node:util';

export const FORMAT = 'anima-test-vectors/1';
export const DEFAULT_EPS = 1e-9;

const HERE = dirname(fileURLToPath(import.meta.url));

const isPlainObject = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
const show = (v) => inspect(v, { depth: 6, breakLength: Infinity });

/** Walk any parsed JSON value and throw on a non-finite number (JSON.parse turns 1e400 into Infinity). */
function assertFinite(value, where) {
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) throw new Error(`${where}: non-finite number ${value} is not allowed`);
  } else if (Array.isArray(value)) {
    value.forEach((v, i) => assertFinite(v, `${where}[${i}]`));
  } else if (isPlainObject(value)) {
    for (const [k, v] of Object.entries(value)) assertFinite(v, `${where}.${k}`);
  }
}

/** Validate a parsed vector file; returns it unchanged. `origin` names it in error messages. */
export function validateVectors(data, origin = '<vectors>') {
  const fail = (msg) => { throw new Error(`${origin}: ${msg}`); };
  if (!isPlainObject(data)) fail('top level must be an object');
  if (data.format !== FORMAT) fail(`format must be "${FORMAT}", got ${show(data.format)}`);
  if (typeof data.source !== 'string' || !data.source) fail('"source" must name the smoke holding the derivations');
  if (data.fixtures !== undefined && !isPlainObject(data.fixtures)) fail('"fixtures" must be an object');
  if (!Array.isArray(data.cases) || data.cases.length === 0) fail('"cases" must be a non-empty array');
  assertFinite(data, origin);
  const labels = new Set();
  data.cases.forEach((c, i) => {
    const at = `case #${i}`;
    if (!isPlainObject(c)) fail(`${at} must be an object`);
    if (typeof c.label !== 'string' || !c.label) fail(`${at} needs a non-empty "label"`);
    if (labels.has(c.label)) fail(`duplicate label "${c.label}"`);
    labels.add(c.label);
    if (typeof c.fn !== 'string' || !c.fn) fail(`"${c.label}" needs a non-empty "fn"`);
    if (!Array.isArray(c.args)) fail(`"${c.label}" needs an "args" array`);
    if (!('expect' in c)) fail(`"${c.label}" needs an "expect"`);
    if (c.eps !== undefined && (typeof c.eps !== 'number' || c.eps < 0)) fail(`"${c.label}": "eps" must be a number >= 0`);
    if (isPlainObject(c.expect) && '$throws' in c.expect
        && (c.expect.$throws !== true || Object.keys(c.expect).length !== 1)) {
      fail(`"${c.label}": a throw expectation is exactly {"$throws": true}`);
    }
    // Resolve once at load so a dangling $fixture is a load error, not a run-time one.
    try { resolveArgs(c.args, data.fixtures ?? {}); } catch (e) { fail(`"${c.label}": ${e.message}`); }
  });
  return data;
}

/** Parse + validate vector JSON text. */
export function parseVectors(text, origin = '<vectors>') {
  let data;
  try { data = JSON.parse(text); } catch (e) { throw new Error(`${origin}: not valid JSON (${e.message})`); }
  return validateVectors(data, origin);
}

/** Load a vector file by path. */
export function loadVectorFile(path) {
  return parseVectors(readFileSync(path, 'utf8'), path);
}

/** Load shared/test-vectors/<name>.json (name: lowercase letters, digits, underscores). */
export function loadVectors(name) {
  if (!/^[a-z0-9_]+$/.test(name)) throw new Error(`bad vector file name ${show(name)}`);
  return loadVectorFile(join(HERE, `${name}.json`));
}

/**
 * Replace every {"$fixture": NAME} (optionally with "$with": {...}) at any depth of `args`
 * by a deep copy of fixtures[NAME]; "$with" overrides top-level keys of an object fixture.
 */
export function resolveArgs(args, fixtures = {}) {
  const walk = (v) => {
    if (Array.isArray(v)) return v.map(walk);
    if (!isPlainObject(v)) return v;
    if ('$fixture' in v) {
      const extra = Object.keys(v).filter((k) => k !== '$fixture' && k !== '$with');
      if (extra.length) throw new Error(`fixture reference has stray keys ${extra.join(', ')}`);
      const name = v.$fixture;
      if (typeof name !== 'string' || !Object.hasOwn(fixtures, name)) throw new Error(`unknown fixture ${show(name)}`);
      const base = structuredClone(fixtures[name]);
      if (!('$with' in v)) return base;
      if (!isPlainObject(v.$with)) throw new Error(`"$with" of fixture "${name}" must be an object`);
      if (!isPlainObject(base)) throw new Error(`"$with" needs an object fixture, "${name}" is not one`);
      return { ...base, ...structuredClone(v.$with) };
    }
    return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, walk(x)]));
  };
  return walk(args);
}

/**
 * Compare an actual value against an expectation.
 * Numbers within eps (actual NaN/Infinity never match), null only equals null, -0 == 0,
 * arrays elementwise with equal length, objects only on the expectation's keys.
 * Returns {ok, diff}; diff is '' when ok.
 */
export function near(expect, actual, eps = DEFAULT_EPS, path = '') {
  const at = path || '<value>';
  const bad = (why) => ({ ok: false, diff: `${at}: ${why}` });
  if (expect === null) return actual === null ? { ok: true, diff: '' } : bad(`expected null, got ${show(actual)}`);
  if (typeof expect === 'number') {
    if (typeof actual !== 'number' || !Number.isFinite(actual)) return bad(`expected ${expect}, got ${show(actual)}`);
    const d = Math.abs(expect - actual);
    return d <= eps ? { ok: true, diff: '' } : bad(`expected ${expect}, got ${actual} (|diff| ${d} > eps ${eps})`);
  }
  if (typeof expect === 'string' || typeof expect === 'boolean') {
    return actual === expect ? { ok: true, diff: '' } : bad(`expected ${show(expect)}, got ${show(actual)}`);
  }
  if (Array.isArray(expect)) {
    if (!Array.isArray(actual)) return bad(`expected an array, got ${show(actual)}`);
    if (actual.length !== expect.length) return bad(`expected length ${expect.length}, got ${actual.length}`);
    for (let i = 0; i < expect.length; i++) {
      const r = near(expect[i], actual[i], eps, `${path}[${i}]`);
      if (!r.ok) return r;
    }
    return { ok: true, diff: '' };
  }
  if (isPlainObject(expect)) {
    if (!isPlainObject(actual)) return bad(`expected an object, got ${show(actual)}`);
    for (const k of Object.keys(expect)) {
      const r = near(expect[k], Object.hasOwn(actual, k) ? actual[k] : undefined, eps, `${path}.${k}`);
      if (!r.ok) return r;
    }
    return { ok: true, diff: '' };
  }
  return bad(`unsupported expectation ${show(expect)}`);
}

const isThrows = (expect) => isPlainObject(expect) && expect.$throws === true;

/**
 * Run every case of a loaded vector file against `fns` (fn name -> function).
 * Throws before running anything when a case names a fn missing from `fns`.
 * Prints "  ok   <label>" / "  FAIL <label>" (+ expected/actual/diff) through opts.log.
 */
export function runVectors(file, fns, opts = {}) {
  const log = opts.log ?? ((line) => console.log(line));
  for (const c of file.cases) {
    if (typeof fns[c.fn] !== 'function') {
      throw new Error(`vector case "${c.label}" calls fn "${c.fn}", which is not in the dispatch table`);
    }
  }
  let passed = 0;
  let failed = 0;
  for (const c of file.cases) {
    const eps = c.eps ?? DEFAULT_EPS;
    let actual;
    let threw = null;
    try { actual = fns[c.fn](...resolveArgs(c.args, file.fixtures ?? {})); } catch (e) { threw = e; }
    let ok;
    let diff;
    if (isThrows(c.expect)) {
      ok = threw !== null;
      diff = ok ? '' : `expected a throw, returned ${show(actual)}`;
    } else if (threw !== null) {
      ok = false;
      diff = `threw ${threw?.message ?? show(threw)}`;
    } else {
      ({ ok, diff } = near(c.expect, actual, eps));
    }
    if (ok) {
      passed++;
      log(`  ok   ${c.label}`);
    } else {
      failed++;
      log(`  FAIL ${c.label}`);
      log(`       expected: ${show(c.expect)}`);
      log(`       actual:   ${threw !== null ? `<threw ${threw?.message ?? show(threw)}>` : show(actual)}`);
      log(`       ${diff}`);
    }
  }
  return { passed, failed };
}
