#!/usr/bin/env node
/**
 * Derivation moved to native/tests/Derivations/foot_lock_measure.md (E1, 2026-11-25).
 * Usage:  node client3d/scripts/smoke_foot_lock_measure.mjs
 *         (needs esbuild and three from the workspace)
 * Runs until E3 deletes the browser scene; the C# vector tests keep executing the cases.
 */
import { runBridgeVectors } from './bridgeVectorDispatch.mjs';
const result = await runBridgeVectors('foot_lock_measure');
console.log(`\n${result.passed} ok, ${result.failed} failed`);
process.exitCode = result.failed ? 1 : 0;
