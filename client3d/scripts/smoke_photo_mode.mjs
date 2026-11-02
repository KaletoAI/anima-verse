#!/usr/bin/env node
/** Runs the real engine input/frame and photo-mode controller without WebGL.
 * Breaks caught: orbit state advancing in photo mode, key leakage, taking a
 * cleared-buffer screenshot, overlay/pin leakage, unbounded JPEGs, hand-off
 * before restoration, repeat uploads, typing stealing F2, and stuck errors.
 * Usage: node client3d/scripts/smoke_photo_mode.mjs
 */
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
import { mainFunction } from './mainFunction.mjs';
const built = await build({ stdin: { contents: `export { Engine } from './client3d/src/scene/engine.ts'; export { NpcManager } from './client3d/src/scene/npcs.ts'; export { FirstPersonZoom } from './client3d/src/scene/cameraFraming.ts'; export * from './client3d/src/game/photoMode.ts'; export * as THREE from 'three';`, resolveDir: process.cwd(), loader: 'ts' }, bundle: true, loader:{'.css':'empty'}, write: false, platform: 'node', format: 'esm' });
const bundleDir=await mkdtemp('/tmp/task94-photo-mode-');
let loaded;
try {
  const path=bundleDir+'/fixture.mjs'; await writeFile(path,built.outputFiles[0].text);
  loaded=await import(pathToFileURL(path).href);
} finally {await rm(bundleDir,{recursive:true,force:true});}
const { Engine, FirstPersonZoom, createPhotoMode, encodePhotoCanvas, NpcManager, THREE }=loaded;

const events = new Map();
globalThis.window = { addEventListener(name, fn) { const a = events.get(name) ?? []; a.push(fn); events.set(name, a); } };
const emit = (name, data = {}) => { for (const fn of events.get(name) ?? []) fn({ preventDefault() {}, ...data }); };
const order = [];
const jpeg = new Blob(['jpeg'], { type: 'image/jpeg' });
const el = { width: 1600, height: 900, clientWidth: 1600, clientHeight: 900, addEventListener: window.addEventListener, setPointerCapture() {}, toBlob(fn, type, quality) { order.push('encode'); assert.equal(type, 'image/jpeg'); assert.equal(quality, .9); fn(jpeg); } };
const pin = new THREE.Object3D();
const hiddenPin = new THREE.Object3D(); hiddenPin.visible = false;
function fixture(firstPerson = false) {
  const zoom = new FirstPersonZoom();
  zoom.update(firstPerson ? 1 : 10, true, .1); zoom.update(firstPerson ? 1 : 10, true, .1);
  const camera = new THREE.PerspectiveCamera(45, 16/9, .2, 800);
  camera.position.set(8, 9, 10); camera.lookAt(1, 2, 3);
  camera.setViewOffset(1600, 900, -100, 50, 1600, 900);
  return Object.assign(Object.create(Engine.prototype), {
    camera, scene: new THREE.Scene(), renderer: { domElement: el, render() { order.push('render'); assert.equal(pin.visible, false); assert.equal(hiddenPin.visible, false); } },
    labelRenderer: { render() { order.push('labels'); } },
    target: new THREE.Vector3(1, 2, 3), dist: firstPerson ? 1 : 23, targetDist: firstPerson ? 1 : 24,
    yaw: .3, targetYaw: .4, pitchOffset: 12, nearPitchDeg: 8, zoomFloor: .8, zoomCap: 34,
    firstPersonZoom: zoom, keys: new Set(['w']), orbiting: false, follow: firstPerson ? () => new THREE.Vector3(1,2,3) : null,
    flyT: .2, flyFrom: new THREE.Vector3(), flyToPoint: new THREE.Vector3(9,8,7),
    viewDx: 100, viewDy: -50, viewApplied: {dx:100,dy:-50,w:1600,h:900}, obstruction: {x:1,y:2,w:3,h:4},
    clock: { getDelta: () => .05 }, frameHooks: [], sunAngle: 1, sun: { target: { position: new THREE.Vector3() }, position: new THREE.Vector3() },
    photoOverlays: () => [pin, hiddenPin],
  });
}
for (const mode of ['overview', 'follow', 'firstPerson']) {
  const firstPerson = mode === 'firstPerson';
  events.clear(); order.length = 0;
  const e = fixture(firstPerson);
  if (mode === 'follow') e.follow = () => new THREE.Vector3(1, 2, 3);
  const oldCamera = e.camera;
  const state = () => [e.target.toArray(), e.dist, e.targetDist, e.yaw, e.targetYaw, e.pitchOffset, e.flyT, e.viewDx, e.viewDy, e.follow, e.firstPersonZoom];
  const before = state();
  const zoomBefore = {...e.firstPersonZoom};
  e.bindInput(el);
  e.enterPhotoMode(); assert.equal(e.photoMode, true); assert.equal(e.firstPerson, false);
  assert.equal(e.keysDown().size, 0); assert.equal(e.camera.view?.enabled, false);
  e.flyTo(new THREE.Vector3(99, 98, 97), 100);
  assert.deepEqual(state(), before, 'late fly-to cannot replace saved play controls');
  emit('keydown', {key:'w'}); emit('keydown', {key:'q'}); emit('keydown', {key:'Shift'});
  assert.equal(e.keysDown().size, 0, 'photo keys must never reach avatar steering');
  emit('wheel', {deltaY:-10000}); assert.equal(e.photoSpeed, 20);
  emit('wheel', {deltaY:10000}); assert.equal(e.photoSpeed, .5);
  let picked = false; e.onPick = () => { picked = true; };
  emit('pointerdown', {button:0, pointerId:1, clientX:0,clientY:0});
  emit('pointermove', {clientX:10,clientY:20});
  emit('pointerup', {button:0,clientX:10,clientY:20}); assert.equal(picked, false);
  const pos = e.camera.position.clone(); e.frame();
  assert.ok(e.camera.position.distanceTo(pos) > 0, 'real dt moves free camera');
  assert.deepEqual(state(), before, 'normal camera arithmetic must be suspended');
  assert.equal(pin.visible, true); assert.equal(hiddenPin.visible, false);
  assert.ok(!order.includes('labels'));
  const shot = e.capturePhotoFrame(() => { order.push('view'); return {visible:[],camera:{pitch_deg:0,height_m:2,fov_deg:45}}; });
  e.frame(); const result = await shot;
  assert.equal(result.jpeg, jpeg); assert.ok(order.indexOf('encode') > order.lastIndexOf('render'));
  e.leavePhotoMode(); assert.equal(e.camera, oldCamera); assert.deepEqual(state(), before);
  assert.deepEqual({...e.firstPersonZoom}, zoomBefore);
  assert.equal(e.firstPerson, firstPerson); assert.equal(e.keysDown().size, 0);
  e.enterPhotoMode();
  emit('pointerdown', {button:0, pointerId:1, clientX:0, clientY:0});
  e.leavePhotoMode();
  emit('pointerup', {button:0, clientX:0, clientY:0});
  assert.equal(picked,false,'leaving mid-drag must not turn its release into a walk order');
}
// Real flight arithmetic: 4 m/s * .05 s = .2 m, Shift triples it.
events.clear();
const flight = fixture(); flight.camera.position.set(0,2,0); flight.camera.quaternion.identity();
flight.enterPhotoMode(); flight.bindInput(el);
emit('keydown',{key:'w'}); flight.frame();
assert.deepEqual(flight.camera.position.toArray(), [0,2,-.2]);
emit('keyup',{key:'w'}); emit('keydown',{key:'q'}); flight.frame();
assert.deepEqual(flight.camera.position.toArray(), [0,1.8,-.2]);
emit('keyup',{key:'q'}); emit('keydown',{key:'e'}); emit('keydown',{key:'Shift'}); flight.frame();
assert.ok(Math.abs(flight.camera.position.y - 2.4) < 1e-10);
flight.leavePhotoMode();
// Selection freezes the rendered view and disables look/flight, while frame hooks keep ticking.
flight.enterPhotoMode();flight.setPhotoSelecting(true);
const frozenPos=flight.camera.position.clone(), frozenRotation=flight.camera.quaternion.clone();
let worldTicks=0;flight.frameHooks.push(()=>worldTicks++);
const renders=order.filter(v=>v==='render').length;
emit('pointerdown',{button:0,pointerId:1,clientX:0,clientY:0});emit('pointermove',{clientX:120,clientY:60});
emit('keydown',{key:'w'});flight.frame();
assert.ok(flight.camera.position.equals(frozenPos));assert.ok(flight.camera.quaternion.equals(frozenRotation));
assert.equal(worldTicks,1);assert.equal(order.filter(v=>v==='render').length,renders);
flight.setPhotoSelecting(false);flight.frame();assert.ok(flight.camera.position.equals(frozenPos),'selection keys do not stick');
let latePick=0;flight.pickLocation=()=>null;flight.onPick=()=>latePick++;
flight.leavePhotoMode();emit('pointerup',{button:0,clientX:20,clientY:20});
assert.equal(latePick,0,'selection release after leaving cannot pick/walk');
// Interior view state and height sampling stay independent of flight position.
const floorTile={loc:{id:'place'},levelFilter:1,roomLevels:new Map([['room',1]]),roomCenters:new Map([['room',{y:3}]])};
const floor=await mainFunction('photoFloorY',{tileAt:()=>floorTile,groundY:()=>1,openLocationId:'place',
  worldToTile:(_,x,z)=>({x,z}),bakedFloorAt:(_t,_x,_z,keep)=>keep({roomId:'room'})?3:null,
  roomAt:()=>null,corridorAt:()=>null});
assert.equal(floor(2,5,2),3,'height uses displayed upstairs floor');
assert.equal(floor(2,2,2),1,'floor above camera is not below it');
const followStorey=await mainFunction('followAvatarStorey',{engine:{photoMode:true}});
followStorey(floorTile,'other'); assert.equal(floorTile.levelFilter,1);
const cleared=[];
const photoHover=await mainFunction('photoOwnsHover',{engine:{photoMode:true,onHover:()=>cleared.push('tile')},
  clearPropHover:()=>cleared.push('prop'),clearVerticalHover:()=>cleared.push('stairs'),hoverSeq:2},['hoverSeq']);
assert.equal(photoHover(),true);assert.deepEqual(cleared,['prop','stairs','tile']);assert.equal(photoHover.snapshot().hoverSeq,-1);
// Actual manager tick holds the avatar but still dispatches the other NPC.
const manager = new NpcManager(null, {syncCounters:{},errWindow:{t:[],e:[]}});
const held = {name:'avatar', root:new THREE.Group(), target:new THREE.Vector3(10,0,0), bubbleUntil:0,
  figure:{setFirstPerson(){}, update(dt){assert.equal(dt,0);}, firstPersonEye(out){return out.set(0,1.6,0);}}, label:{}};
const other = {...held, name:'other',root:new THREE.Group()};
manager.npcs.set('avatar',held); manager.npcs.set('other',other);
manager.photoHeldName='avatar'; const dispatched=[];
manager.tickOwnMotion = npc => {dispatched.push(npc.name); return true;};
manager.tick(.1,20);
assert.deepEqual(held.root.position.toArray(),[0,0,0]); assert.deepEqual(dispatched,['other']);
manager.npcs.set('unloaded',{...held,name:'unloaded',figure:null});
other.root.visible=false;
assert.deepEqual(manager.photoSubjects(),[{name:'avatar',head:[0,1.6,0]}]);
other.root.visible=true; const hiddenParent=new THREE.Group();hiddenParent.visible=false;hiddenParent.add(other.root);
assert.equal(manager.photoSubjects().length,1,'hidden storey ancestors stay out of PhotoView');
// Downscale in the render task, never defer the draw of a WebGL canvas.
let output;
const big = { width: 4096, height: 2160 };
const scaled = await encodePhotoCanvas(big, () => output = { width:0,height:0, getContext: () => ({drawImage(source,x,y,w,h) { assert.equal(source,big); assert.deepEqual([x,y,w,h],[0,0,2048,1080]); }}), toBlob(fn,type,q) { assert.equal(type,'image/jpeg'); assert.equal(q,.9); fn(jpeg); } });
assert.equal(scaled,jpeg); assert.deepEqual([output.width,output.height],[2048,1080]);
await assert.rejects(encodePhotoCanvas({width:10,height:10,toBlob(fn){fn(null);}}), /capture/i);
// Crop at native resolution before downscale; never stretch a small selection.
for (const [rect,dimensions] of [[{x:700,y:100,width:800,height:400},[800,400]],
  [{x:700,y:100,width:3000,height:1500},[2048,1024]]]) {
  let drawn;
  const source={width:4096,height:2160};
  const result=await encodePhotoCanvas(source,()=>output={width:0,height:0,
    getContext:()=>({drawImage(...args){drawn=args;}}),toBlob(fn){fn(jpeg);}},rect);
  assert.equal(result,jpeg);assert.deepEqual([output.width,output.height],dimensions);
  assert.deepEqual(drawn,[source,rect.x,rect.y,rect.width,rect.height,0,0,...dimensions]);
}
// Real main steering hook returns before any position report or route movement.
const steering = await mainFunction('engine.addFrameHook:manualInput', { engine:{photoMode:true} });
steering(.05);
// Controller selection is exposed in the hint model; the React island owns pointer input.
let active=false,hudHidden=false,uploads=0,errors=0,hints=[],resolveCapture,rejectCapture,freeze;
const view={visible:[{name:'left',screen_x:0,screen_y:.5,depth_m:10}],camera:{pitch_deg:0,height_m:2,fov_deg:90}};
let uploadedView;
const engine={get photoMode(){return active;},photoSpeed:4,selecting:false,
  enterPhotoMode(){active=true;},leavePhotoMode(){active=false;},
  setPhotoSelecting(value){this.selecting=value;},
  capturePhotoFrame(getView,select){freeze=select;return new Promise((r,j)=>{resolveCapture=r;rejectCapture=j;});}};
const frozenCanvas={width:1600,height:900,getContext:()=>({drawImage(){}}),toBlob(fn){fn(jpeg);}};
globalThis.document={createElement:()=>frozenCanvas};
const controller=createPhotoMode({engine,view:()=>view,
  hideHud:()=>{hudHidden=true;return()=>{hudHidden=false;};},hint:s=>hints.push(s),
  upload:async(blob,v)=>{assert.equal(active,false);assert.equal(hudHidden,false);assert.equal(blob,jpeg);uploads++;uploadedView=v;},error:()=>errors++});
const key=(key,extra={})=>({key,preventDefault(){},stopImmediatePropagation(){},...extra});
const settle=()=>new Promise(r=>setImmediate(r));
async function frozen(){try {const frame=await freeze(frozenCanvas,view);resolveCapture(frame);} catch(e) {rejectCapture(e);} await settle();}
assert.equal(controller.keydown(key('F2',{target:{closest:()=>true}}),false),false);
assert.equal(controller.keydown(key('F2'),true),false);
controller.keydown(key('F2'),false);controller.keydown(key('F2',{repeat:true}),false);assert.equal(active,true);
controller.keydown(key(' '),false);assert.equal(engine.selecting,true,'Space starts selection');
const selecting=frozen();await settle();assert.equal(uploads,0,'freezing never uploads');
assert.equal(typeof hints.at(-1).capturing,'object');
hints.at(-1).capturing.choose({x:0,y:0,width:800,height:900});await selecting;
assert.equal(uploads,1);assert.equal(uploadedView.visible[0].screen_x,0);
controller.keydown(key('F2'),false);controller.keydown(key(' '),false);
const second=frozen();await settle();controller.keydown(key(' '),false);await second;
assert.equal(uploads,2);assert.deepEqual(uploadedView,view,'second Space selects full frame');
controller.keydown(key('F2'),false);controller.keydown(key(' '),false);
const cancelledCapture=frozen();await settle();controller.keydown(key('Escape'),false);await cancelledCapture;
assert.equal(active,true,'Escape selection returns to flying');assert.equal(engine.selecting,false);
controller.keydown(key('Escape'),false);assert.equal(active,false);assert.equal(hudHidden,false);assert.equal(errors,0);
// Small drags and clicks count as whole frame in original device pixels.
const {photoSelectionRect,photoShotRect}=loaded;
assert.deepEqual(photoSelectionRect({x:100,y:50},{x:500,y:250},{left:100,top:50,width:800,height:450},1600,900),{x:0,y:0,width:800,height:400});
assert.deepEqual(photoSelectionRect({x:500,y:250},{x:-20,y:-20},{left:100,top:50,width:800,height:450},1600,900),{x:0,y:0,width:800,height:400});
assert.deepEqual(photoShotRect({x:40,y:40,width:63,height:500},1600,900),{x:0,y:0,width:1600,height:900});
assert.deepEqual(photoShotRect({x:0,y:0,width:64,height:64},1600,900),{x:0,y:0,width:64,height:64});
const ring=new THREE.Object3D(), line=new THREE.Object3D();
manager.walkTargetRing=ring; held.travelLine=line;
assert.deepEqual(manager.photoOverlays(),[ring,line]);
// Leaving before the render resolves must ignore a late frame without uploading.
controller.keydown(key('F2'),false);controller.keydown(key(' '),false);
controller.keydown(key('F2'),false);assert.equal(active,true,'F2 selection returns to flying');
resolveCapture({jpeg,view});await settle();assert.equal(uploads,2);assert.equal(errors,0);
controller.keydown(key('Escape'),false);
// Restore and report capture/encoding/upload errors; repeated Space cannot duplicate a handoff.
for (const failure of ['capture','encode','upload']) {
  let failedHints=[],failedError=0,failedUpload=0;
  const failedEngine={...engine,get photoMode(){return active;},
    capturePhotoFrame:async(getView,select)=>{
      if(failure==='capture')throw Error('capture');
      return select(frozenCanvas,view);
    }};
  const originalToBlob=frozenCanvas.toBlob;
  if(failure==='encode')frozenCanvas.toBlob=fn=>fn(null);
  const failed=createPhotoMode({engine:failedEngine,view:()=>view,hideHud:()=>()=>{},hint:s=>failedHints.push(s),
    upload:async()=>{failedUpload++;if(failure==='upload')throw Error('403');},error:()=>failedError++});
  failed.keydown(key('F2'),false);failed.keydown(key(' '),false);await settle();
  if(failure!=='capture') {failed.keydown(key(' '),false);failed.keydown(key(' ',{repeat:true}),false);await settle();}
  assert.equal(active,false);assert.equal(failedError,1);assert.equal(failedUpload,failure==='upload'?1:0);
  frozenCanvas.toBlob=originalToBlob;
}
console.log('PASS photo mode: restoration, input isolation, capture ordering, selection, device pixels, click, small drag and cancellation');
