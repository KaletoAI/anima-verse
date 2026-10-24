/** Hand oracles: distances 1..7 select 1..6; cutoff 10+30=40;
 * night gate strictly >.3; retained B,A preserve slots. Noise amplitudes
 * bound candle .92..1.08 and fire .75..1.25. No browser/GL required. */
import assert from 'node:assert/strict';
import { build } from 'esbuild';
const result = await build({entryPoints:['client3d/src/scene/lightPool.ts'], bundle:true,platform:'node',format:'esm',write:false,external:['three']});
const {pickLights,flickerFactor,LightPool,placementLightPosition} = await import('data:text/javascript;base64,'+Buffer.from(result.outputFiles[0].text.replaceAll('from "three"',`from "${import.meta.resolve('three')}"`)).toString('base64'));
const sources=Array.from({length:7},(_,i)=>({id:String(i+1),pos:{x:i+1,y:0,z:0},range_m:10,when:'always'}));
const focus={x:0,y:0,z:0}, rooms=new Set(['r2']);
assert.deepEqual(pickLights(sources,focus,6,1,rooms,[]),['1','2','3','4','5','6']);
assert.deepEqual(pickLights(sources,focus,2,1,rooms,['2','1']),['2','1']);
const one={...sources[0],when:'night'};
assert.deepEqual(pickLights([one],focus,6,.3,rooms,[]),[]);
assert.deepEqual(pickLights([one],focus,6,.5,rooms,[]),['1']);
assert.deepEqual(pickLights([{...one,when:'always',room_id:'r1'}],focus,6,1,rooms,[]),[]);
assert.deepEqual(pickLights([{...sources[0],pos:{x:50,y:0,z:0}}],focus,6,1,rooms,[]),[]);
for(let i=0;i<1000;i++) for(const [kind,lo,hi] of [['none',1,1],['candle',.92,1.08],['fire',.75,1.25]]) {const f=flickerFactor(kind,i/37,.7);assert.ok(f>=lo&&f<=hi);}
const THREE=await import('three');
const scene=new THREE.Scene(),pool=new LightPool(scene);
const light={color:'#ffb35c',intensity:2,range_m:4,flicker:'none',when:'always',glow_m:0,offset_m:[1,2],height_m:3};
const handle=pool.register(light,focus);
pool.update(.4,focus,1,rooms);pool.update(.4,focus,1,rooms);
assert.equal(scene.children.filter(x=>x.isPointLight).length,6);
assert.ok(scene.children.some(x=>x.isPointLight&&x.intensity>0));
handle.remove();pool.update(.4,focus,1,rooms);pool.update(.4,focus,1,rooms);
assert.ok(scene.children.every(x=>!x.isPointLight||x.intensity===0));
const parent=new THREE.Group();parent.position.set(10,5,20);parent.rotation.y=Math.PI/2;
const pos=placementLightPosition(parent,[2,4],7,light);
assert.ok(pos.distanceTo(new THREE.Vector3(15,15,20))<1e-9);
console.log('light pool: PASS (selection, sticky slots, flicker, registry, fixed count, world anchor)');
// Canvas supplies pixels only; selection, sprites, materials and cleanup are real.
globalThis.document={createElement:()=>({getContext:()=>({createRadialGradient:()=>({addColorStop(){}}),fillRect(){}})})};
const glowA=pool.register({...light,glow_m:.2},focus);
const glowB=pool.register({...light,glow_m:.2},focus,'hidden');
const sprites=scene.children.filter(x=>x.isSprite);
assert.equal(sprites.length,2);assert.equal(sprites[0].material.map,sprites[1].material.map);
assert.equal(sprites[0].scale.x,.4);
let disposed=0,textureDisposed=0;
sprites[0].material.addEventListener('dispose',()=>disposed++);
sprites[0].material.map.addEventListener('dispose',()=>textureDisposed++);
pool.update(.2,focus,1,rooms);
assert.equal(sprites[1].visible,false);
glowA.move({x:2,y:3,z:4});assert.deepEqual(sprites[0].position.toArray(),[2,3,4]);
glowA.remove();glowA.remove();glowB.remove();
assert.equal(disposed,1);assert.equal(textureDisposed,0);
assert.equal(scene.children.filter(x=>x.isSprite).length,0);
assert.equal(scene.children.filter(x=>x.isPointLight&&x.visible).length,6);
console.log('halos: PASS (shared texture, visibility, movement, material-only disposal)');
let ledgerRegistered=0,ledgerReleased=0;
const ledgerHalo=pool.register({...light,glow_m:.1},focus,undefined,sprite=>{
  ledgerRegistered++;
  return ()=>{ledgerReleased++;sprite.material.dispose();};
});
assert.equal(ledgerRegistered,1);
ledgerHalo.remove();ledgerHalo.remove();assert.equal(ledgerReleased,1);
console.log('halo ownership hook: PASS (mount registers and releases exactly once)');
