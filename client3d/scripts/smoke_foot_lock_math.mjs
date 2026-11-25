#!/usr/bin/env node
/**
 * Derivation moved to native/tests/Derivations/foot_lock_math.md (E1, 2026-11-25).
 * Usage:  node client3d/scripts/smoke_foot_lock_math.mjs
 *         (needs esbuild; reads scripts/fixtures/root_motion_cases.json)
 * Runs until E3 deletes the browser scene; the C# vector tests keep executing the cases.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { loadVectors, resolveArgs } from '../../shared/test-vectors/vectors.mjs';
import { runBridgeVectors } from './bridgeVectorDispatch.mjs';
// Preserve the original Python/TS fixture contract while exposing ordinary JSON
// arguments to the native client. This checks hand data, never production output.
const legacy = JSON.parse(readFileSync(new URL('../../scripts/fixtures/root_motion_cases.json', import.meta.url), 'utf8'));
const vectors = loadVectors('foot_lock');
const wrapped = [];
for (const c of vectors.cases) {
  const args = resolveArgs(c.args, vectors.fixtures);
  if (c.fn === 'constant') assert.deepEqual(c.expect, legacy.constants[args[0]]);
  if (c.fn === 'footLockValue') wrapped.push({input:args[0], field:args[1], expect:c.expect});
}
assert.deepEqual(wrapped, legacy.cases.flatMap((c) => Object.entries(c.expect).map(([field, expect]) =>
  ({input:{tracks:c.tracks,rest:c.rest,fps:c.fps},field,expect}))));
console.log('  ok   legacy root_motion_cases wrapper agrees');
const result = await runBridgeVectors('foot_lock');
result.passed += 1;
console.log(`\n${result.passed} ok, ${result.failed} failed`);
process.exitCode = result.failed ? 1 : 0;
