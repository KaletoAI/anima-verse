#!/usr/bin/env node
/**
 * Derivation moved to native/tests/Derivations/pair_realtime.md (E1, 2026-11-25).
 * Usage: timeout 300 node client3d/scripts/smoke_pair_realtime.mjs
 *        (needs three and esbuild; expectations live in pair_clip_phase.json.)
 * Runs until E3 deletes the browser scene; the C# vector tests keep executing the cases.
 */
import { runPairVectors } from './pairVectorDispatch.mjs';
const { passed, failed } = await runPairVectors('pair_clip_phase');
console.log(`\n${passed} ok, ${failed} failed`);
process.exitCode = failed ? 1 : 0;
