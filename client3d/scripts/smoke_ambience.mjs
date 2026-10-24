/** Hand oracles: sRGB tint numbers are left for the engine to convert.
 * tau=.5, dt=.5: .3+.7/e=.5575156. After 20*.25 seconds the
 * neutral error is .7*exp(-10)<.001. */
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {transformSync} from 'esbuild';
const code=transformSync(await readFile('client3d/src/scene/ambience.ts','utf8'),{loader:'ts',format:'esm'}).code;
const {ambienceTarget,stepAmbience}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
const neutral={daylight:1,tint:[1,1,1]};
assert.deepEqual(ambienceTarget(),neutral);
assert.deepEqual(ambienceTarget({daylight:.3,tint:'#ff0000'}),{daylight:.3,tint:[1,0,0]});
const target=ambienceTarget({daylight:.3,tint:'#ff0000'});
assert.ok(Math.abs(stepAmbience(neutral,target,.5).daylight-.5575156)<1e-4);
assert.equal(stepAmbience(neutral,target,0).daylight,1);
let cur=target;for(let i=0;i<20;i++)cur=stepAmbience(cur,neutral,.25);
assert.ok(Math.abs(cur.daylight-1)<.001);assert.ok(cur.tint.every(x=>Math.abs(x-1)<.001));
console.log('ambience: PASS (targets, exponential easing, return to neutral)');
// Exercise clock ticks through the real Engine methods without a WebGL renderer.
const {build}=await import('esbuild');
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
