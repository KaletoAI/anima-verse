/**
 * Derivation moved to native/tests/Derivations/ambience.md (E1, 2026-11-25).
 * Usage:  node client3d/scripts/smoke_ambience.mjs   (from the repo root)
 * Runs until E3 deletes the browser scene; the C# vector tests keep executing the cases.
 */
import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {loadVectors, runVectors} from '../../shared/test-vectors/vectors.mjs';
const pure=await build({stdin:{contents:"export * from './client3d/src/scene/ambience.ts'; export * from './client3d/src/game/roomAt.ts'; export { worldToLocalXZ } from './packages/scene-render/src/scatter.ts';",resolveDir:process.cwd(),loader:'ts'},bundle:true,platform:'node',format:'esm',write:false});
const {ambienceTarget,stepAmbience,nightFactorAt,roomRectOf,roomAtRects,corridorAtOutline,worldToLocalXZ}=await import('data:text/javascript;base64,'+Buffer.from(pure.outputFiles[0].text).toString('base64'));
const vectors=runVectors(loadVectors('ambience'),{
  ambienceTarget,stepAmbience,nightFactorAt,roomRectOf,roomAtRects,corridorAtOutline,
  stepAmbienceN:(cur,target,dt,n)=>{for(let i=0;i<n;i++)cur=stepAmbience(cur,target,dt);return cur;},
  worldToTile:(tile,x,z)=>worldToLocalXZ(tile.center.x,tile.center.z,tile.yaw,x,z),
});
assert.equal(vectors.failed,0,`${vectors.failed} ambience vector(s) failed`);
console.log(`ambience: PASS (${vectors.passed} vectors: targets, exponential easing, night clock, room under the focus)`);
// Exercise clock ticks through the real Engine methods without a WebGL renderer.
const bundled=await build({entryPoints:['client3d/src/scene/engine.ts'],bundle:true,platform:'node',format:'esm',write:false});
const {Engine}=await import('data:text/javascript;base64,'+Buffer.from(bundled.outputFiles[0].text).toString('base64'));
const THREE=await import('three');
function engine() {
  const e=Object.create(Engine.prototype);
  Object.assign(e,{scene:new THREE.Scene(),sun:new THREE.DirectionalLight(),
    hemi:new THREE.HemisphereLight(0xdfeeff,0x8a9a78),fill:new THREE.DirectionalLight(0xdde8ff),
    ambienceDaylight:1,ambienceTint:new THREE.Color('white')});
  e.scene.background=new THREE.Color();e.scene.fog=new THREE.Fog('white',1,10);
  return e;
}
const dim=engine(),base=engine();
dim.setGameHour(12);dim.applyAmbience(.3,new THREE.Color('#ffcf9a'));
for(const hour of [0,6,12,18]) {
  base.setGameHour(hour);dim.setGameHour(hour);
  for(const name of ['sun','hemi','fill']) {
    assert.ok(Math.abs(dim[name].intensity-base[name].intensity*.3)<1e-12);
    assert.ok(dim[name].color.equals(base[name].color.clone().multiply(new THREE.Color('#ffcf9a'))));
  }
  assert.ok(dim.scene.background.equals(base.scene.background));
  assert.ok(dim.scene.fog.color.equals(base.scene.fog.color));
}
dim.applyAmbience(1,new THREE.Color('white'));
assert.ok(dim.sun.color.equals(base.sun.color));assert.equal(dim.hemi.intensity,base.hemi.intensity);
console.log('ambience engine: PASS (clock preserves dimming/tint, neutral restores, sky background/fog unchanged)');
