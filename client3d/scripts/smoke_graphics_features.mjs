/** Task 110: hand-derived scene counts, no GL/DOM/server.
 * Six pool lamps + sun/hemi/fill = 9 lights; off = 3; restored = 9.
 * One mirror render callback per enabled frame, zero while disabled.
 * Two waterfall meshes + one prop sheet disappear; the water surface stays.
 * Fog = one scene fog, backdrop = one group; off = zero, on = one each.
 * New sheets and tier visibility writes must also honour the current switch.
 */
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import * as T from 'three';
const result = await build({ stdin: { contents: `
 export { applyFogVeil, setFogVeilCameraHeight } from './client3d/src/scene/fogVeil';
 export { SubmergedGhost } from './client3d/src/scene/submergedGhost';
 export { loadGraphicsPrefs } from './client3d/src/game/prefs';
 export { GraphicsFeatures } from './client3d/src/scene/graphicsFeatures';
 export { LightPool } from './client3d/src/scene/lightPool';
 export { attachMirror, disposeMirror } from './packages/scene-render/src/mirrorSurface';
 export { buildPropWater } from './packages/scene-render/src/propWater';
 export { gateWaterExtra, waterExtrasUniform } from './packages/scene-render/src/waterExtras';
 export { buildWaterfall } from './client3d/src/scene/waterfall';
 export { DEFAULT_GRAPHICS_PREFS } from './client3d/src/game/prefs';
`, resolveDir: process.cwd(), loader: 'ts' }, bundle:true, platform:'node', format:'esm', write:false, external:['three'] });
const dir = await mkdtemp(join(tmpdir(), 'graphics-features-'));
const modulePath = join(dir, 'features.mjs');
await writeFile(modulePath, result.outputFiles[0].text.replaceAll('from "three"', `from "${import.meta.resolve('three')}"`));
const P = await import(modulePath);
await rm(dir, { recursive: true });
// Canvas provides pixel storage only; all scene objects and render hooks are real.
globalThis.document = { createElement: () => ({ getContext: () => ({
 createImageData:(w,h)=>({data:new Uint8ClampedArray(w*h*4)}), putImageData(){}, fillRect(){},
 createRadialGradient:()=>({addColorStop(){}}),
}) }) };
const scene = new T.Scene();
scene.background = new T.Color(0x123456);
scene.fog = new T.Fog(0x123456, 220, 520);
const pool = new P.LightPool(scene);
scene.add(new T.DirectionalLight(), new T.HemisphereLight(), new T.DirectionalLight());
const backdrop = new T.Group(); scene.add(backdrop);
const controller = new P.GraphicsFeatures(scene, pool, backdrop);
const prefs = P.DEFAULT_GRAPHICS_PREFS;
const groundMaterial = new T.MeshStandardMaterial();
P.applyFogVeil(groundMaterial);
const shader = { uniforms:{}, vertexShader:'', fragmentShader:'' };
groundMaterial.onBeforeCompile(shader, null);
P.setFogVeilCameraHeight(45);
const ghostRoot = new T.Group();
ghostRoot.add(new T.Mesh(new T.BoxGeometry(), new T.MeshStandardMaterial()));
scene.add(ghostRoot);
const ghost = new P.SubmergedGhost(ghostRoot); ghost.set(1);
assert.ok(ghost.count > 0);
const lights = () => { let n=0; scene.traverse(o => { if(o.isLight) n++; }); return n; };
const surface = new T.Mesh(new T.PlaneGeometry(), new T.MeshStandardMaterial()); scene.add(surface);
const sheets = () => P.buildPropWater(T, {regions:[{outline:[[0,0],[1,0],[1,1],[0,1]], y:1, tint:'#337799', opacity:0.5}]}, 0);
const sheet = sheets()[0]; scene.add(sheet);
const falls = P.buildWaterfall({x:0,z:0,topY:3,bottomY:0,width:2,dirX:0,dirZ:1,chordM:1}, []);
assert.equal(falls.length,2); scene.add(...falls);
const pane = new T.Mesh(new T.PlaneGeometry(2,2),new T.MeshStandardMaterial()); scene.add(pane);
const material = P.attachMirror(T,pane,pane.material,null,'mirror',{textureSize:16,maxPerFrame:2});
assert.ok(material);
const camera = new T.PerspectiveCamera(60,1,0.1,100); camera.position.z=3;
scene.updateMatrixWorld(true); camera.updateMatrixWorld(true);
let calls=0;
const renderer = {info:{render:{frame:1}}, xr:{enabled:false}, shadowMap:{autoUpdate:true},
 getRenderTarget:()=>null, getViewport:v=>v.set(0,0,16,16), setRenderTarget(){},
 state:{buffers:{depth:{setMask(){}}},viewport(){}}, render(){calls++;}};
const draw = () => {renderer.info.render.frame++; pane.onBeforeRender(renderer,scene,camera,pane.geometry,material,null);};
// Simulate stored startup values: all-off must land before the first draw.
controller.apply(P.loadGraphicsPrefs('{"waterMirrors":false,"lampLights":false,"fogHorizon":false}'));
assert.equal(lights(),3); assert.equal(scene.fog,null); assert.equal(backdrop.visible,false);
assert.equal(shader.uniforms.uFogAlpha.value,0);
draw(); assert.equal(calls,0);
controller.apply(prefs); draw(); assert.equal(calls,1); assert.equal(lights(),9);
for (const key of ['waterMirrors','lampLights','fogHorizon']) {
 controller.apply({...prefs,[key]:false});
 if(key==='waterMirrors') {
  draw(); assert.equal(calls,1); assert.equal(P.waterExtrasUniform.value,0);
  assert.equal(ghost.visible,false); assert.equal(ghost.parts.filter(o=>o.visible).length,0);
  assert.equal([sheet,...falls].filter(o=>o.visible).length,0); assert.equal(surface.visible,true);
  const late=sheets()[0]; late.visible=true; assert.equal(late.visible,false);
  // Streaming changes this tier while disabled: enabling must retain the new hidden tier.
  sheet.visible=false;
  controller.apply(prefs); assert.equal(sheet.visible,false); sheet.visible=true;
  assert.equal(late.visible,true); draw(); assert.equal(calls,2);
 } else if(key==='lampLights') {
  assert.equal(lights(),3);
  const handle = pool.register({color:'#ffffff',intensity:1,range_m:4,flicker:'none',when:'always',glow_m:1,offset_m:[0,0],height_m:1}, {x:0,y:0,z:0});
  const halo=scene.children.find(o=>o.isSprite); assert.equal(halo.visible,false);
  let updates=0; const old=pool.sources;
  pool.sources={values(){updates++; return old.values();}};
  pool.update(1,{x:0,y:0,z:0},1,new Set()); assert.equal(updates,0);
  pool.sources=old;
  controller.apply(prefs); pool.update(.4,{x:0,y:0,z:0},1,new Set());
  assert.equal(halo.visible,true); handle.remove();
 } else {
  assert.equal(scene.fog,null); assert.equal(backdrop.visible,false);
  assert.equal(shader.uniforms.uFogAlpha.value,0);
 }
 controller.apply(prefs);
 assert.equal(ghost.visible,true);
 assert.ok(shader.uniforms.uFogAlpha.value > 0);
 assert.equal(lights(),9); assert.ok(scene.fog); assert.equal(backdrop.visible,true);
 assert.equal([sheet,...falls].filter(o=>o.visible).length,3);
}
ghost.dispose();
P.disposeMirror(material);
console.log('graphics features: lights 9→3→9; mirror renders 1→1→2; extras 3→0→3; fog/backdrop 1→0→1; late sheets/tier gates pass');
