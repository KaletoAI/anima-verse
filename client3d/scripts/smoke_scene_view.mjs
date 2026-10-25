#!/usr/bin/env node
/**
 * Pure scene/interior view oracles, shared with the native client.
 * Usage: node client3d/scripts/smoke_scene_view.mjs
 *
 * Hand derivations for scene_view.json:
 * [O] Opening requires an interior AND building/ground/shell-area. Interior
 *     detection is OR over plates, floor_plan, walls, extras, markers and any
 *     non-building model. No room means outdoor, otherwise membership in either
 *     always-visible or outdoor rooms decides.
 * [T] Low enters full strictly below 45; full leaves strictly above 60.
 *     Equality retains state. Area detail stays low only while closed.
 * [W] Wall dot (camera-mid)·normal <= 0 AND equal storey. Camera x=-1/0/1
 *     against normal (1,0) yields -1/0/1: visible/visible/culled.
 * [F] Fade uses f+(target-f)(1-exp(-4dt)); dt=ln(2)/4=.17328679513998632
 *     halves the remaining distance: 0->1 gives .5, .5->1 gives .75,
 *     1->0 gives .5. Zero dt gives no change. roof=max(0,1-1.4f),
 *     shell=1-.88f: at f=0:1/1; .5:.3/.56; 1:0/.12.
 *     roof visible f<.95, shadow f<.4, interior f>.03, labels f>.5;
 *     the boundary cases .03/.4/.5/.95 pin the strict comparisons.
 * [R] A room is visible iff always-visible OR (level??0)==shown. Shown
 *     storey piece opacity=1, otherwise its composed ghost (.4/.45/1).
 * [S] Model wins; no building, nature or area detail gives ground; otherwise
 *     positive plate+wall count gives recipe, no pieces gives none. Recipe
 *     pieces: non-room plate or non-glass wall at level>=0; leaves count.
 * [M] Door quad scale=(width,1,max(.3width,thickness)), yaw=atan2(-az,ax),
 *     y=base+.02: width2/thickness.8 =>(2,1,.8), base3=>3.02; +z along
 *     gives -pi/2. Boundary width2 => depth .6, width.5 => floor .3,
 *     inward +x => pi/2, ground4=>4.05.
 * [N] Camera(0,0), target(100,0): neighbour x determines t=x/100;
 *     .05 and .92 are excluded, .05001 and .91999 are included. Width2
 *     yields perpendicular limit 2.1, strict: z2.099 is in, z2.1 is out.
 *     Height must exceed 1.5; same tile and zero-length corridor never hide.
 * [B] Bounds [-2,-3,2,3], width10: camera offset(3,4) has unit(.6,.8)
 *     so only maxima grow by(6,8) =>[-2,-3,8,11]. Opposite camera grows
 *     minima =>[-8,-11,2,3]. At centre the 0/1 fallback adds nothing.
 * [X] Positive yaw rotates (lx,lz) to (lx cos+lz sin,-lx sin+lz cos).
 *     Frame centre(10,4,-5), yaw pi/2: local(2,3), ly1 =>(13,5,-7),
 *     direction(2,3)=>(3,-2). Rectangle local x[-2,2],z[-1,1] becomes
 *     world x[9,11],z[-7,-3]. At yaw0 local(2,3)=>(12,4,-2).
 * [D] Explicit style overrides terrain, which overrides name; area names may
 *     guess forest/road, else grass; built names guess tower/cafe/house else
 *     generic. Thus forest terrain beats Cafe, explicit house beats water.
 * [G] Rings: enter near <=150, leave >180; enter far <=520+40=560,
 *     leave >560*1.2=672; a pin overrides all distances. Square centred
 *     (200,0), half-side60: west edge140, origin distance140. No boundary:
 *     100-40sqrt(1/2)=71.7157287525381; two probes min(300,120)=120.
 *     A point at the rotated square centre remains inside (distance0).
 */
import { build } from 'esbuild';
import { loadVectors, runVectors } from '../../shared/test-vectors/vectors.mjs';
const built = await build({ entryPoints: ['client3d/src/scene/sceneView.ts'], bundle: true,
  platform: 'node', format: 'esm', write: false });
const view = await import(`data:text/javascript;base64,${Buffer.from(built.outputFiles[0].text).toString('base64')}`);
const { passed, failed } = runVectors(loadVectors('scene_view'), view);
console.log(`${passed} ok, ${failed} failed`);
process.exitCode = failed ? 1 : 0;
