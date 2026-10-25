/**
 * Smoke check for the prop light pool — client3d/src/scene/lightPool.ts.
 *
 * Usage:  node client3d/scripts/smoke_light_pool.mjs   (from the repo root)
 *
 * Hand derivations (cases in shared/test-vectors/light_pool.json, shared with
 * the native client's C# tests). JSON wrappers: `visibleRooms` is a LIST (the
 * function takes a Set); `lightPoolSize()` returns LIGHT_POOL_SIZE.
 *
 * [P] pickLights(sources, focus, n, night, visibleRooms, previous): a source
 *     is a candidate when (when ≠ night or night > .3), its room is shown (or
 *     it has none) and its 3D distance to the focus is ≤ range_m + 30; the
 *     candidates sort nearest first, the first n win; a previous slot whose id
 *     still wins keeps it, the other winners fill the empty slots in distance
 *     order; trailing empty slots are dropped.
 *     P1 distances 1..7 → 1..6. P2 previous [2, 1], both win → [2, 1].
 *     P3 night gate strictly > .3: night .3 → []. P4 night .5 → [1].
 *     P5 room r1 while only r2 is shown → []. P6 50 > 10 + 30 → [].
 *     P7 40 = 10 + 30 → in. P8 (0, 30, 0) with range 0 → 30 ≤ 30 in,
 *     (0, 30.5, 0) out. P9 winners [1, 2, 3], previous ['', '3'] → slot 1
 *     keeps 3, the free [1, 2] fill slots 0 and 2 → [1, 3, 2].
 *     P10 b at 1 m, a at 2 m, six slots → [b, a] (four trailing '' dropped).
 *     P11 winners [1, 3], previous [1, 2, 3] → 2 lost its slot → [1, '', 3].
 * [F] flickerFactor(kind, t, phase) = 1 + a·(sin t0 + sin(√2·t0))/2 with
 *     t0 = t·hz·2π + phase; candle hz 8, a .08; fire hz 4, a .25; none a 0.
 *     F1 none → 1. F2 candle t 0 phase 0 → 1. F3 candle t 1/32: t0 = π/2,
 *     sin(π√2/2) = 0.7956932015674809 → 1 + .08·1.7956932015674809/2 =
 *     1.0718277280626993. F4 fire, t 0, phase π/2 → 1 + .25·1.79569…/2 =
 *     1.2244616501959351. F5 fire, phase π: sin π ≈ 1.2e-16,
 *     sin(π√2) = −0.9639025328498773 → 1 − .25·0.96390…/2 = 0.8795121833937654.
 *     Bounds over 1000 samples: candle .92..1.08, fire .75..1.25 (checked inline).
 * [G] nightLightGain(when, night): a night lamp = smoothstep(night, .3, .6),
 *     t = (night − .3)/.3, t²(3 − 2t); every other lamp 1. G4 night .375 →
 *     t .25 → .0625·2.5 = .15625; G5 .45 → t .5 → .25·2 = .5; ≤ .3 → 0, ≥ .6 → 1.
 * [H] haloVisible(roomShown, when, night) = roomShown ∧ (when ≠ night ∨ night > .3).
 * [C] fireColourMix(t, phase) = max(0, (1 − flickerFactor('fire', t, phase))/.25)·.1:
 *     C1 phase π → (1 − 0.8795121833937654)/.25·.1 = 0.04819512664249386;
 *     C2 phase π/2 → the factor 1.224… > 1 → 0.
 * [S] stepLightSlot({id, gain}, wanted, dt): the wanted id → gain + dt/.4
 *     (max 1); another id → gain − dt/.4 (min 0), and only AT 0 the slot takes
 *     the wanted id. S1 .5 + .25 = .75; S2 .5 + .5 → 1; S3 .5 − .25 = .25;
 *     S4 .25 − .25 = 0 → id b; S5 '' at 0 → b at 0; S6 .4 − .5 → 0 → ''.
 * [W] lightPositionInFrame(frame, anchor, bottom, light): (anchor x, bottom,
 *     anchor z) through the column-major frame, then + (offset x, height,
 *     offset z) in world metres. W1 frame = position (10, 5, 20), rotation y
 *     +90° (x → −z, z → x): (2, 7, 4) → (4, 7, −2) + (10, 5, 20) =
 *     (14, 12, 18), + (1, 3, 2) = (15, 15, 20). W2 identity: (0, 1, 0) +
 *     (.5, 2, −.5). W3 scale 2 + (1, 0, 0): (1, 1, 1) → (3, 2, 2), + (0, 1, 0)
 *     = (3, 3, 2) — the offset is not scaled.
 * [K] LIGHT_POOL_SIZE = 6.
 *
 * The rest runs inline: the LightPool class with real three objects (fixed
 * count, registry, halos and their ownership); no browser/GL required.
 */
import assert from 'node:assert/strict';
import { build } from 'esbuild';
const result = await build({entryPoints:['client3d/src/scene/lightPool.ts'], bundle:true,platform:'node',format:'esm',write:false,external:['three']});
const {pickLights,flickerFactor,LightPool,placementLightPosition,nightLightGain,haloVisible,fireColourMix,stepLightSlot,lightPositionInFrame,LIGHT_POOL_SIZE} = await import('data:text/javascript;base64,'+Buffer.from(result.outputFiles[0].text.replaceAll('from "three"',`from "${import.meta.resolve('three')}"`)).toString('base64'));
const {loadVectors,runVectors}=await import('../../shared/test-vectors/vectors.mjs');
const vectors=runVectors(loadVectors('light_pool'),{
  pickLights:(src,focus,n,night,rooms,prev)=>pickLights(src,focus,n,night,new Set(rooms),prev),
  flickerFactor,nightLightGain,haloVisible,fireColourMix,stepLightSlot,lightPositionInFrame,
  lightPoolSize:()=>LIGHT_POOL_SIZE,
});
assert.equal(vectors.failed,0,`${vectors.failed} light_pool vector(s) failed`);
const focus={x:0,y:0,z:0}, rooms=new Set(['r2']);
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
console.log(`light pool: PASS (${vectors.passed} vectors; registry, fixed count, world anchor)`);
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
