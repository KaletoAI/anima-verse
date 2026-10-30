/** B1 answer-driven playback: hand-derived real-time positions, independent of poll age. */
import assert from 'node:assert/strict';
import { motion } from './propActionVectorDispatch.mjs';
const plan = { execution_id:'run', journey_id:'journey', room_id:'room', floor_y:3,
  waypoints:[[0,0],[2,0],[2,3]], paces_m_s_real:[2,1], departure:null,
  access:{x:2,y:3,z:3,yaw:180}, anchor:{x:2.4,y:3.5,z:3,yaw:270,root_offset:.1,place_id:'bed',slot:1},
  entry:{mode:'bridge',kind:'lie',pose_key:'lying',duration_s:2},height_cm:170,role:null };
assert.equal(typeof motion.sampleMotion, 'function', 'B1 has a client-clock sampler');
assert.deepEqual(motion.sampleMotion(plan,.5), {phase:'walking',x:1,y:3,z:0,yaw:90});
assert.deepEqual(motion.sampleMotion(plan,2), {phase:'walking',x:2,y:3,z:1,yaw:0});
assert.deepEqual(motion.sampleMotion(plan,4), {phase:'entry',x:2,y:3,z:3,yaw:180});
assert.deepEqual(motion.sampleMotion(plan,6), {phase:'arrived',x:2.4,y:3.5,z:3,yaw:270});
assert.deepEqual(motion.sampleMotion({...plan,paces_m_s_real:null},500), {phase:'frozen',x:0,y:3,z:0,yaw:90});
const seated = {...plan,waypoints:[[-1,0],[0,0],[2,0],[2,3]],paces_m_s_real:[null,2,1],
 departure:{seat:[-1,0],stand:[0,0],exit_clip:'stand-up',exit_s:1}};
assert.deepEqual(motion.sampleMotion(seated,.5), {phase:'departure',x:-.5,y:3,z:0,yaw:90});
assert.deepEqual(motion.sampleMotion(seated,1.5), {phase:'walking',x:1,y:3,z:0,yaw:90});
assert.deepEqual(motion.sampleMotion({...seated,departure:{...seated.departure,exit_clip:''}},.5),
 {phase:'walking',x:1,y:3,z:0,yaw:90});
assert.deepEqual(motion.sampleMotion({...plan,entry:{mode:'direct',duration_s:50}},4),
 {phase:'arrived',x:2.4,y:3.5,z:3,yaw:270});
console.log('prop action playback: PASS (own clock, corners, frozen, departure, direct, exact anchor)');

// Production manager is exercised without WebGL; the figure boundary records exact clip calls.
import { build } from 'esbuild';
import { fileURLToPath } from 'node:url';
const bundle = await build({stdin:{contents:`export {NpcManager} from './client3d/src/scene/npcs'; export {Figure,setClipRootPath} from './client3d/src/scene/figures'; export * as THREE from 'three';`,
 resolveDir:fileURLToPath(new URL('../..',import.meta.url)),loader:'ts'},bundle:true,loader:{'.css':'empty'},write:false,platform:'node',format:'esm'});
const {NpcManager,THREE,Figure,setClipRootPath} = await import(`data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].text).toString('base64')}`);
const savedPerformance=globalThis.performance; let now=10000;
globalThis.performance={now:()=>now};
try {
 const manager=new NpcManager(null,{syncCounters:{},errWindow:{t:[],e:[]}});
 const calls=[]; const root=new THREE.Group();
 const figure={root:new THREE.Group(),finishPropEntry:clip=>calls.push(['finish',clip]),faceTowards(){},setYaw(){},setLean(){},
  playPropEntry:(...args)=>{calls.push(['entry',...args]);return true},playPair:()=>true,
  update:dt=>calls.push(['update',dt]),setFirstPerson(){},resetSecondaryMotion(){}};
 const npc={name:'avatar',root,figure,target:new THREE.Vector3(),waypoints:[],route:null,entry:null,interaction:null,
 label:{},labelName:{},labelActivity:{},travelLine:null,travelKey:'',bubbleUntil:0};
 manager.npcs.set('avatar',npc);manager.setRoomStandAt(()=>3.01);
 assert.equal(typeof manager.playOwnMotion,'function','manager accepts answer motion');
 manager.playOwnMotion('avatar',plan,'request');
 now+=500; manager.tick(.5,10);
 assert.ok(calls.some(c=>c[0]==='update'&&c[1]===.5),'locomotion advances actual frame time');
 assert.equal(root.position.x,1,'answer moves before a world poll'); assert.equal(root.position.y,3.01);
 manager.update([{char:{name:'avatar',activity_animation:'standing',prop_action_entry:{kind:'WRONG'}},pos:new THREE.Vector3(99,0,99)}]);
 assert.equal(root.position.x,1,'worldmap cannot change playing avatar');
 now+=3500;manager.tick(0,10);assert.ok(calls.some(c=>c[0]==='entry'&&c[1]==='lie'),'entry starts at access without a poll');
 now+=2000;manager.tick(0,10);assert.equal(root.position.x,2.4);assert.equal(root.position.y,3.5);
 manager.update([{char:{name:'avatar',place:{id:'bed',slot:1},activity_animation:'lying'},pos:new THREE.Vector3(80,0,80)}]);
 assert.equal(root.position.x,2.4,'anchor hold cannot adopt marker slot');
 manager.playOwnMotion('avatar',plan,'state');now+=500;manager.tick(0,10);
 assert.equal(root.position.x,2.4,'repeated same state cannot restart the completed plan');
 manager.playOwnMotion('avatar',{...plan,paces_m_s_real:null},'state');manager.tick(.1,10);
 assert.equal(root.position.x,2.4,'post-arrival freeze cannot rewind the client to route start');
 const replacement=[];npc.figure={...figure,finishPropEntry:clip=>replacement.push(clip)};manager.tick(.1,10);
 assert.deepEqual(replacement,['lying'],'model replacement adopts confirmed hold clip at same anchor');assert.equal(root.position.x,2.4);
 let handedBack=0; manager.playOwnCancel('avatar',{seat:[2.4,3],stand:[2.4,2],exit_clip:'',exit_s:0},()=>handedBack++);
 assert.equal(root.position.z,2,'clipless cancel stands immediately');assert.equal(handedBack,1);
 // Freeze and unfreeze update the same plan without changing the rendered route point.
 manager.playOwnMotion('avatar',{...plan,execution_id:'frozen',journey_id:'frozen',paces_m_s_real:null},'request');
 now+=20000;manager.tick(.1,10);assert.equal(root.position.x,0);
 manager.playOwnMotion('avatar',{...plan,execution_id:'frozen',journey_id:'frozen'},'state');
 now+=500;manager.tick(.5,10);assert.equal(root.position.x,1,'resume begins at frozen point, not elapsed wall time');
 manager.playOwnMotion('avatar',{...plan,execution_id:'frozen',journey_id:'frozen',paces_m_s_real:null},'state');
 now+=20000;manager.tick(.1,10);assert.equal(root.position.x,1,'mid-route freeze retains progress');
 manager.playOwnMotion('avatar',{...plan,execution_id:'frozen',journey_id:'frozen',paces_m_s_real:[1,1]},'state');
 now+=500;manager.tick(.5,10);assert.equal(root.position.x,1.5,'new pace continues from current point');
 manager.playOwnMotion('avatar',{...plan,execution_id:'entry-freeze',journey_id:'entry-freeze'},'request');
 now+=4500;manager.tick(.1,10);
 const entryBeforeFreeze=calls.filter(c=>c[0]==='entry'&&c[1]==='lie').at(-1)[2];
 manager.playOwnMotion('avatar',{...plan,execution_id:'entry-freeze',journey_id:'entry-freeze',paces_m_s_real:null},'state');
 now+=20000;manager.tick(.1,10);
 assert.equal(calls.filter(c=>c[0]==='entry'&&c[1]==='lie').at(-1)[2],entryBeforeFreeze,'freeze holds current measured entry frame');
 manager.playOwnMotion('avatar',{...plan,execution_id:'entry-freeze',journey_id:'entry-freeze'},'state');
 now+=500;manager.tick(.5,10);
 assert.equal(calls.filter(c=>c[0]==='entry'&&c[1]==='lie').at(-1)[2],entryBeforeFreeze+.25,'entry resumes remaining real duration');
 // Each pair half uses its authoritative role and subsequently adopts server phase timing.
 for(const role of ['a','b']){
  const pairCalls=[],faces=[];manager.figures={pairRootAt:()=>({x:.4,z:0})};
  npc.figure={...figure,faceTowards:dir=>faces.push(dir.clone()),playPair:(...args)=>{pairCalls.push(args);return true}};
  const paired={...plan,execution_id:`pair-${role}`,journey_id:`pair-${role}`,paces_m_s_real:[null,null],role,
   entry:{mode:'direct',kind:'',pose_key:'kiss',duration_s:0}};
  manager.playOwnMotion('avatar',paired,'request');
  manager.update([{char:{name:'avatar',place:{id:'bed',slot:1},activity_animation:`kiss__${role}`},pos:new THREE.Vector3(99,0,99),
   stamp:10,interaction:{id:`pair-${role}`,kind:'kiss',role,anchor:{x:2.4,z:3.4,yaw:Math.PI/2,place_id:'bed'},elapsed_s:.5,rate:1,loop:true,clip_duration_s:2}}]);
  manager.tick(.25,10);
  now+=400;manager.tick(0,10); // Task 84: pair yaw reaches the anchor after its real-time entry blend.
  assert.equal(pairCalls.at(-1)[0],`kiss__${role}`);assert.equal(root.position.x,2.4);
  assert.equal(root.position.z,3);assert.equal(root.position.y,3.5,'pair uses server body anchor Y');
  assert.ok(Math.abs(faces.at(-1).x-1)<1e-8&&Math.abs(faces.at(-1).z)<1e-8,'pair uses authoritative shared interaction yaw');
 }
 manager.playOwnMotion('avatar',{...plan,execution_id:'release',journey_id:'release'},'request');
 now+=4500;manager.tick(.1,10);npc.figure.takeTravel=()=>({x:.25,z:.1});
 const atAccess=root.position.clone();manager.clearOwnMotion('avatar');
 assert.equal(root.position.x,atAccess.x+.25,'failure bakes measured entry travel before releasing');
 assert.equal(root.position.z,atAccess.z+.1);
 // A measured departure keeps the old seat heading and hands its root travel to the stand once.
 const rig=new THREE.Group(),hips=new THREE.Bone();hips.name='Hips';rig.add(hips);
 const exit=new THREE.AnimationClip('up',.5,[new THREE.VectorKeyframeTrack('Hips.position',[0,.5],[0,.5,0,0,1,0])]);
 setClipRootPath(exit,{times:new Float32Array([0,.5]),xz:new Float32Array([0,0,0,-.5])});
 const realFigure=new Figure({name:'departure-b1',template:rig,scale:1,height:1.7,
  clips:[exit,...['idle','walk','sitting'].map(kind=>new THREE.AnimationClip(kind,1,[]))],tier:'full',noClips:false,libraryFits:true});
 npc.figure=realFigure;root.add(realFigure.root);root.position.set(2,.129,0);realFigure.faceTowards(new THREE.Vector3(0,0,1),true);
 const revert=manager.previewPropFacing('avatar',4,0);assert.equal(realFigure.root.rotation.y,Math.PI/2);
 revert();assert.equal(realFigure.root.rotation.y,0,'refusal reverts immediate click facing');
 manager.previewPropFacing('avatar',4,0);
 const leaving={...plan,execution_id:'leaving',journey_id:'leaving',floor_y:0,
  waypoints:[[2,0],[2,-.5],[4,-.5]],paces_m_s_real:[null,1],departure:{seat:[2,0],stand:[2,-.5],exit_clip:'up',exit_s:.5},
  access:{x:4,y:0,z:-.5,yaw:90},anchor:{...plan.anchor,x:4,y:.129,z:-.5}};
 manager.playOwnMotion('avatar',leaving,'request');now+=250;manager.tick(.25,10);
 root.updateMatrixWorld(true);const beforeStand=realFigure.root.children[0].getWorldPosition(new THREE.Vector3());
 assert.ok(Math.abs(beforeStand.z+.25)<1e-5,'exit follows measured root path in original seat heading');
 now+=250;manager.tick(.25,10);root.updateMatrixWorld(true);
 assert.equal(root.position.z,-.5,'exit ends at exact server stand');
 const afterStand=realFigure.root.children[0].getWorldPosition(new THREE.Vector3());
 assert.ok(Math.abs(afterStand.z+.5)<1e-5,'stand handoff never counts exit travel twice');
 now+=500;manager.tick(.5,10);assert.equal(root.position.x,2.5,'walk starts immediately after measured departure');
 root.position.set(2,.129,0);realFigure.finishPropEntry('sitting');realFigure.faceTowards(new THREE.Vector3(0,0,1),true);
 let exitDone=0;manager.playOwnCancel('avatar',{seat:[2,0],stand:[2,-.5],exit_clip:'up',exit_s:.5},()=>exitDone++);
 now+=250;manager.tick(.25,10);assert.equal(exitDone,0,'cancel owns the complete exit clip');
 now+=250;manager.tick(.25,10);assert.equal(exitDone,1);assert.equal(root.position.z,-.5);
 assert.equal(manager.hasOwnMotion('avatar'),false,'cancel returns control without a poll');
 // Observer local_approach still plays the measured departure while its server lead holds the walk.
 root.position.set(2,.129,0);realFigure.finishPropEntry('sitting');realFigure.faceTowards(new THREE.Vector3(0,0,1),true);
 manager.update([{char:{name:'avatar',activity_animation:'up',travel:{journey_id:'observer-exit'}},pos:root.position.clone(),
  route:{points:[[2,0],[2,-.5],[4,-.5]],totalM:2.5,paces:[null,1],serverM:0,ageAtParsedS:0,
   parsedAt:now,journeyId:'observer-exit',stamp:20,exact:true,floorY:.01,startsInS:.75,departureClip:'up'}}]);
 manager.tick(.1,10);assert.equal(realFigure.currentClip,'up','observer departure retains its exit clip');
 now+=300;manager.tick(.3,10);assert.equal(root.position.x,2,'observer does not walk before its public countdown');
 console.log('prop action playback manager: PASS (immediate answer, poll suppression, anchor hold, dedupe, cancel)');
}finally{globalThis.performance=savedPerformance}
