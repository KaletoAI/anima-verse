#!/usr/bin/env node
/**
 * Derivation moved to native/tests/Derivations/figure_normalisation.md (E1, 2026-11-25).
 * Usage: timeout 300 node client3d/scripts/smoke_figure_normalisation.mjs
 * Runs until E3 deletes the browser scene; the C# vector tests keep executing the cases.
 */
import { runPairVectors } from './pairVectorDispatch.mjs';
const { passed, failed } = await runPairVectors('figure_normalisation');
console.log(`\n${passed} ok, ${failed} failed`);
process.exitCode = failed ? 1 : 0;
