#!/usr/bin/env node
/**
 * Derivation moved to scripts/smoke_group_role_points.py (E1, 2026-11-25).
 * Usage: timeout 300 node client3d/scripts/smoke_group_role_points.mjs
 * Runs until E3 deletes the browser scene; the C# vector tests keep executing the cases.
 */
import { runPairVectors } from './pairVectorDispatch.mjs';

const result = await runPairVectors('group_role_points');
console.log(`group_role_points: ${result.passed} ok, ${result.failed} failed`);
process.exitCode = result.failed ? 1 : 0;
