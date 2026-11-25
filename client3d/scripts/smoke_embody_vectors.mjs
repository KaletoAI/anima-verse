#!/usr/bin/env node
/**
 * Derivation moved to native/tests/Derivations/embody_vectors.md (E1, 2026-11-25).
 * Usage: node client3d/scripts/smoke_embody_vectors.mjs
 * Runs until E3 deletes the browser scene; the C# vector tests keep executing the cases.
 */
import assert from 'node:assert/strict';
import { loadVectors, runVectors } from '../../shared/test-vectors/vectors.mjs';
import { embodyDispatch } from './embodyVectorDispatch.mjs';
let passed = 0, failed = 0;
for (const name of ['walk_control', 'collide', 'enter', 'embody', 'camera']) {
  const result = runVectors(loadVectors(name), embodyDispatch);
  passed += result.passed; failed += result.failed;
  console.log(`${name}: ${result.passed} passed, ${result.failed} failed`);
}
assert.equal(failed, 0, 'all E7 shared vectors');
console.log(`E7 vectors: ${passed} passed, ${failed} failed`);
