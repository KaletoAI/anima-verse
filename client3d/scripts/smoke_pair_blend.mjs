#!/usr/bin/env node
/**
 * Derivation moved to native/tests/Derivations/pair_blend.md (E1, 2026-11-25).
 * Usage:  node client3d/scripts/smoke_pair_blend.mjs
 * Runs until E3 deletes the browser scene; the C# vector tests keep executing the cases.
 */
import { runPairVectors } from './pairVectorDispatch.mjs';
const {passed, failed} = await runPairVectors('pair_blend');
console.log(`pair_blend: ${passed} ok, ${failed} failed`);
process.exitCode = failed ? 1 : 0;
