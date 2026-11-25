#!/usr/bin/env node
/**
 * Derivation moved to native/tests/Derivations/npc_walk.md (E1, 2026-11-25).
 * Usage:  node client3d/scripts/smoke_npc_walk.mjs
 * Runs until E3 deletes the browser scene; the C# vector tests keep executing the cases.
 */
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { loadVectors, runVectors } from '../../shared/test-vectors/vectors.mjs';

const built = await build({
  stdin: { contents: `export * from './client3d/src/game/npcWalk.ts';
    export * from './client3d/src/game/walk.ts';
    export * from './client3d/src/scene/propWaterMath.ts';`,
    resolveDir: process.cwd(), loader: 'ts' },
  bundle: true, platform: 'node', format: 'esm', write: false, logLevel: 'error',
});
const m = await import(`data:text/javascript;base64,${Buffer.from(built.outputFiles[0].text).toString('base64')}`);
const result = runVectors(loadVectors('npc_walk'), {
  ...m,
  npcStepValue: (d, waypoint, movement, reckoning, dt, pace, limit, measured = null) =>
    m.npcStep({ goal: {x:d,y:0,z:0}, retired:0, delta:{x:d,y:0,z:0},
      distToGoal:d, dist:d+(waypoint ? 10 : 0), moving:d>0.05 },
      movement, reckoning, dt, pace, limit, measured),
  liftStops: (stops, from, to) => m.liftStops(new Map(stops), from, to),
});
console.log(`npc_walk: ${result.passed} ok, ${result.failed} failed`);

// Purity: deep-frozen goals and stations must be accepted without mutation.
const pos = Object.freeze({x:0,y:0,z:0});
const target = Object.freeze({x:10,y:2,z:0});
const stations = Object.freeze([Object.freeze({x:1,y:0,z:0})]);
m.npcGoal(pos, target, stations);
m.neighbourFacing(pos, stations);
assert.equal(stations.length, 1);
console.log('npc_walk purity: 1 ok');

const water = runVectors(loadVectors('prop_water'), {
  ...m,
  waterRegionAt: (specs, x, z, lift = 0) => m.waterRegionAt(specs, x, z, () => lift),
});
console.log(`prop_water dependency: ${water.passed} ok, ${water.failed} failed`);
process.exitCode = result.failed || water.failed ? 1 : 0;
