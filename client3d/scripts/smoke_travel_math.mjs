#!/usr/bin/env node
/**
 * Derivation moved to native/tests/Derivations/travel_math.md (E1, 2026-11-25).
 * Usage:  node client3d/scripts/smoke_travel_math.mjs
 * Runs until E3 deletes the browser scene; the C# vector tests keep executing the cases.
 */
import { readFile } from 'node:fs/promises';
import { loadVectors, runVectors } from '../../shared/test-vectors/vectors.mjs';
import { travelDispatch } from './travelVectorDispatch.mjs';

// Canonical consumer executes every shared travel case, including reckon/densify.
const { passed, failed } = runVectors(loadVectors('travel'), travelDispatch);
// Source/identity guards are intentionally not portable vector expectations.
const source = await readFile(new URL('../src/scene/travelPath.ts', import.meta.url), 'utf8');
const points = [[0, 0], [10, 0], [10, 20]];
const tail = travelDispatch.remainingPoints(points, 15);
tail[1][0] = 999;
const guards = [
  ['module has no imports', !/^\s*import\b/m.test(source)],
  ['the tail is COPIED out of the polyline', points[2][0] === 10],
  ['the bucket is five metres', travelDispatch.TRIM_BUCKET_M === 5],
];
for (const [label, ok] of guards) console.log(`  ${ok ? 'ok  ' : 'FAIL'} ${label}`);
const bad = guards.filter(([, ok]) => !ok).length;
console.log(`\n${passed + guards.length - bad} ok, ${failed + bad} failed`);
process.exit(failed + bad ? 1 : 0);
