#!/usr/bin/env node
/**
 * Task 30: pure NPC walking vectors, derived BY HAND (never from output).
 * Source of npc_walk.json; world metres, seconds and radians throughout.
 *
 * [1] npcGoal retires each leading station at 3D distance < 1.5, then uses
 * the first remaining point or target. From (0,0,0), stations (1,0,0) and
 * (0,1,0) both retire (distance 1); (3,0,4) stays (sqrt(9+16)=5).
 * Delta ignores Y, so that goal has distance 5 and run distance 5+10=15.
 * A station at 1.5 stays: run distance 11.5. A station at (0,2,0) stays
 * (3D distance 2) but horizontal distance is zero: standing, run distance 10.
 * A custom stair radius 0.05 keeps a station at 0.1: run distance 10.1.
 * With no stations, target (10,2,0) gives delta (10,0,0), both distances 10.
 * Retiring the only station at 1 gives the same target with retired=1.
 * Distance exactly 0.05 is not moving (> is strict); target height 9 is ignored.
 *
 * [2] npcStepValue builds a plan with horizontal distance d and adds 10 only
 * while a waypoint remains. Run iff distance > 6, type walk_run, no reckoning.
 * Step = min(d, 3.4*dt*pace*(run ? 1.8 : 1))*paceLimit, only when d>0.05
 * and limit>0. At dt=.1, walk=.34, run=.612; six metres walks, seven runs,
 * a station two metres away runs (2+10=12). Types walk/swim/crawl and
 * reckoning all walk at .34. Pace .4 gives .34*.4=.136. For d=.1, dt=1,
 * limit=.5: min(.1,3.4)*.5=.05, proving cap BEFORE limit. Limit zero holds
 * even when running=true. d=.05 stands with step zero. A measured step .2
 * replaces nominal speed; with limit .5 it gives .1, without a run boost.
 *
 * [3] Neighbours are in a strict 3D sphere <4.5. Empty -> null. From origin,
 * (2,0,0), (0,2,2) are inside (2 and sqrt(8)); (4.5,0,0) is excluded at
 * equality, (0,5,0) by height. Centroid ((2+0)/2,(0+2)/2,(0+2)/2)=(1,1,1).
 *
 * [4] standingFacing: view yaw 0 yields (sin(0),0,cos(0))=(0,0,1),
 * ahead of marker (1,2,3). Without view the marker is copied, including Y=2.
 * Without either, position (1,2,3) toward neighbour (4,9,7) yields (3,0,4).
 * With none of the three requests it returns null (keep the current facing).
 * facingYaw ignores a vector when length squared <1e-6. (.0001,0,0)
 * has square 1e-8 -> null; (0,0,.001) has square 1e-6 -> atan2(0,.001)=0.
 * East atan2(1,0)=pi/2=1.5707963267948966; west is its negative.
 * Gate includes Y: (0,1,0) is accepted, atan2(0,0)=0.
 *
 * [5] Y = current+(target-current)*min(1,4*dt): (2,7,.1) gives
 * 2+5*.4=4; dt=.5 caps to 7; dt=0 leaves 2. Yaw uses 10*dt and wraps
 * delta to [-pi,pi], retaining BOTH endpoints. (0,1,.05) -> .5; dt=.2 ->1.
 * (3,-3,.05): delta=-6+2pi, half added to 3 gives pi=3.141592653589793.
 * (-3,3,.05) gives -pi. Exact +/-pi targets from zero give +/-pi/2.
 *
 * [6] liftStops reads source then destination, each falling back to level 0.
 * Fixture has level 0 at (2,0,1), level 2 at (2,6,1). 0->2 and missing
 * 1->2 both return those points in that order. 0->missing 3 returns level
 * zero twice (no deduplication). No stops returns []; with only level 2,
 * missing source 1 is skipped and destination (2,6,1) remains alone.
 *
 * Adapter npcStepValue(d, hasWaypoint, movement, reckoning, dt, pace, limit,
 * reckonedStep=null) constructs the plan as above and calls npcStep. liftStops
 * takes [level, point] pairs, converted to a Map. The existing prop_water.json
 * runs unchanged as a dependency, through exactly its source-smoke adapters.
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
