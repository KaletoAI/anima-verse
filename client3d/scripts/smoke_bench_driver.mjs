/**
 * Usage: node client3d/scripts/smoke_bench_driver.mjs
 * Deterministic driver lifecycle check (no GPU/browser).
 * Hand values: 20 one-second intervals = 20 frames / 20 seconds = 1 fps.
 * CPU samples all 7 ms, calls all 11, triangles all 13. Anchor [100,5,200]
 * plus keyframe zero [0,24,40] puts the camera at [100,29,240], target
 * [100,6.5,200]. A stalled one-second frame must retain its full duration.
 */
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { Vector3, PerspectiveCamera } from 'three';
const built=await build({entryPoints:['client3d/src/bench/bench.ts'],bundle:true,write:false,format:'esm',platform:'node'});
const {initBench}=await import('data:text/javascript;base64,'+Buffer.from(built.outputFiles[0].text).toString('base64'));
globalThis.window={}; globalThis.location={search:'?scatter=0&water=0&goto=demo'};
globalThis.innerWidth=800; globalThis.innerHeight=600;
const elements=new Map();
globalThis.document={getElementById:id=>elements.get(id),createElement:()=>({style:{}}),body:{appendChild:el=>elements.set(el.id,el)}};
const engine={target:new Vector3(9,8,7),camera:new PerspectiveCamera(),dist:80,targetDist:80,yaw:1,targetYaw:1,renderer:{getPixelRatio:()=>1}};
let switches=0,restores=0;
initBench(engine,{output:result=>elements.set('bench',{textContent:JSON.stringify(result)}),anchor:()=>({pos:[100,5,200],locationId:'demo',heightSource:'fixture'}),switches:(scatter,water)=>{
 assert.equal(scatter,false); assert.equal(water,false); switches++; return ()=>restores++;
}});
assert.equal(engine.benchFrame,undefined); assert.equal(switches,0);
window.__bench.start(); window.__bench.start(); assert.equal(switches,1);
engine.benchFrame(0); engine.benchCamera();
assert.deepEqual(engine.camera.position.toArray(),[100,29,240]);
assert.deepEqual(engine.target.toArray(),[100,6.5,200]);
for(let i=0;i<3;i++){engine.benchFrame(1);engine.benchCamera();engine.benchRendered(1,7,11,13);}
assert.equal(window.__bench.last,null);
for(let i=0;i<20;i++){engine.benchFrame(1);engine.benchCamera();engine.benchRendered(1,7,11,13);}
const s=window.__bench.last;
assert.equal(s.frames,20);assert.equal(s.seconds,20);assert.equal(s.fps,1);
assert.equal(s.frameMsP95,1000);assert.equal(s.cpuMsMedian,7);
assert.equal(s.draws,11);assert.equal(s.triangles,13);assert.equal(s.gpuMs,null);
assert.equal(s.flags.scatter,false);assert.equal(s.flags.water,false);
assert.deepEqual(JSON.parse(elements.get('bench').textContent),s);
assert.equal(restores,1);assert.equal(window.__bench.running,false);
assert.equal(engine.benchFrame,undefined);assert.equal(engine.benchCamera,undefined);assert.equal(engine.benchRendered,undefined);
assert.deepEqual(engine.target.toArray(),[9,8,7]);assert.equal(engine.dist,80);
console.log('PASS smoke_bench_driver');
