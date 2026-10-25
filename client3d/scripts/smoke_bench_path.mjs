/**
 * Usage: node client3d/scripts/smoke_bench_path.mjs
 * Hand calculations: d=26+14*cos(yaw), pos=[d*sin(yaw),.6*d,d*cos(yaw)].
 * At yaw=pi/8, sin=.3826834324, cos=.9238795325, d=38.934313455;
 * rounded pos=[14.9,23.361,35.971]. At yaw=9*pi/8, d=13.065686545;
 * rounded pos=[-5,7.839,-12.071]. Thus from the rounded keyframes:
 * t=.625 is halfway between [0,24,40] and [14.9,23.361,35.971]:
 * [7.45,23.6805,37.9855]. t=10.625 is halfway between [0,7.2,-12]
 * and [-5,7.839,-12.071]:
 * [-2.5,7.5195,-12.0355]. Target is always [0,1.5,0].
 * These checks reject nearest-neighbour and cosine interpolation.
 */
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { build } from 'esbuild';
const built = await build({entryPoints:['client3d/src/bench/benchPath.ts'],bundle:true,write:false,format:'esm',platform:'node'});
const {loadPath,samplePath} = await import('data:text/javascript;base64,'+Buffer.from(built.outputFiles[0].text).toString('base64'));
const raw = JSON.parse(await readFile('shared/bench/camera_path_v1.json','utf8'));
const path = loadPath(raw);
const near = (a,b) => a.forEach((v,i)=>assert.ok(Math.abs(v-b[i])<1e-8, `${v} != ${b[i]}`));
assert.equal(path.keyframes.length,17);
assert.equal(path.duration,20); assert.equal(path.warmup,3);
near(samplePath(path,.625).pos,[7.45,23.6805,37.9855]);
near(samplePath(path,10.625).pos,[-2.5,7.5195,-12.0355]);
near(samplePath(path,10.625).target,[0,1.5,0]);
assert.deepEqual(samplePath(path,-1),{pos:path.keyframes[0].pos,target:path.keyframes[0].target});
assert.deepEqual(samplePath(path,21),{pos:path.keyframes[16].pos,target:path.keyframes[16].target});
for (const mutate of [p=>p.version=2,p=>p.space='world',p=>p.duration=0,p=>p.warmup=-1,p=>p.keyframes[0].t=1,p=>p.keyframes[1].t=0,p=>p.keyframes[16].t=19,p=>p.keyframes[1].pos=[0,NaN,0],p=>p.keyframes=[]]) {
 const p=structuredClone(raw); mutate(p); assert.throws(()=>loadPath(p));
}
console.log('PASS smoke_bench_path');
