#!/usr/bin/env node
/**
 * Derivation moved to native/tests/Derivations/pair_storey.md (E1, 2026-11-25).
 * Usage:  node client3d/scripts/smoke_pair_storey.mjs
 *         (needs three and esbuild; no clips, no models, no server)
 * Runs until E3 deletes the browser scene; the C# vector tests keep executing the cases.
 */
import { runPairVectors } from './pairVectorDispatch.mjs';
const { passed, failed } = await runPairVectors('pair_height');
console.log(`\n${passed} ok, ${failed} failed`);
process.exitCode = failed ? 1 : 0;
