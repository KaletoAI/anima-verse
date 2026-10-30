#!/usr/bin/env node
/** Manager lifecycle: a new id blends, polls/reseeks do not restart it, freeze does not stop it.
 * From (1,2,3), target at first tick (5,6,7): after .1 s weight .15625
 * gives (1.625,2.625,3.625), yaw .3125. At .2 s moving target (9,6,7)
 * gives (5,4,5), yaw 1. A .4 s blend ends exactly at the current target.
 */
import assert from 'node:assert/strict';
import {build} from 'esbuild';
import * as THREE from 'three';
const bundle=await build({entryPoints:['client3d/src/scene/npcs.ts'],bundle:true,write:false,platform:'node',format:'esm',loader:{'.css':'empty'},logLevel:'error'});
const {NpcManager}=await import(`data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].text).toString('base64')}`);
const saved=globalThis.performance;let now=1000;
globalThis.performance={now:()=>now};
try {
 let rootPoint={x:0,z:0};
 const mgr=new NpcManager({pairRootAt:()=>rootPoint},{syncCounters:{},errWindow:{t:[],e:[]}});
 mgr.setPlaceAt(()=>({slots:[{y:6}]}));
 const root=new THREE.Group();root.position.set(1,2,3);
 const figure={root:new THREE.Group(),playPair:()=>true,holdsTravel:false,update(){},
  faceTowards(dir,snap){assert.equal(snap,true);this.root.rotation.y=Math.atan2(dir.x,dir.z)},setYaw(yaw){this.root.rotation.y=yaw}};
 const npc={name:'avatar',root,figure,target:new THREE.Vector3(),waypoints:[],route:null,ride:null,interaction:null,
  label:{},labelName:{},labelActivity:{},travelLine:null,travelKey:''};
 mgr.npcs.set('avatar',npc);
 const state={stamp:1,interaction:{id:'one',kind:'handshake',role:'a',anchor:{x:5,z:7,yaw:2,place_id:'bench'},elapsed_s:0,rate:0,loop:true,clip_duration_s:2}};
 mgr.adoptInteraction(npc,state);
 assert.deepEqual(root.position.toArray(),[1,2,3]);
 now+=100;mgr.tickInteraction(npc,.1,true,true);
 assert.deepEqual(root.position.toArray(),[1.625,2.625,3.625],'new pair blends rendered position including seat height');
 assert.ok(Math.abs(figure.root.rotation.y-.3125)<1e-9);
 assert.equal(npc.interaction.clipT,0,'frozen clip stays at start while view blends');
 state.stamp++;state.interaction.anchor.x=9;state.interaction.rate=2;state.interaction.elapsed_s=20;
 mgr.adoptInteraction(npc,state);
 now+=100;mgr.tickInteraction(npc,0,true,false);
 assert.deepEqual(root.position.toArray(),[5,4,5],'same id reseek follows moving target without restarting blend');
 assert.equal(npc.interaction.clipT,10);
 assert.ok(Math.abs(figure.root.rotation.y-1)<1e-9);
 now+=200;mgr.tickInteraction(npc,0,true,false);
 assert.deepEqual(root.position.toArray(),[9,6,7]);
 state.stamp++;state.interaction.anchor.x=13;mgr.adoptInteraction(npc,state);
 mgr.tickInteraction(npc,0,true,false);assert.equal(root.position.x,13,'completed same id never blends again');
 state.interaction.id='two';mgr.adoptInteraction(npc,state);
 state.interaction.anchor.x=17;mgr.adoptInteraction(npc,state);
 now+=200;mgr.tickInteraction(npc,0,true,false);assert.equal(root.position.x,15,'new id captures rendered origin');
 state.interaction.role='b';mgr.adoptInteraction(npc,state);
 now+=100;mgr.tickInteraction(npc,0,true,false);assert.equal(root.position.x,16.375,'same id half change preserves the running blend');
 state.interaction=null;mgr.adoptInteraction(npc,state);assert.equal(npc.interaction,null);
 const partnerRoot=new THREE.Group();partnerRoot.position.set(root.position.x+3,root.position.y,root.position.z);
 mgr.npcs.set('partner',{root:partnerRoot});
 figure.root.rotation.y=0;
 mgr.pairFacing('avatar','begin','request','partner');
 assert.ok(Math.abs(figure.root.rotation.y-Math.PI/2)<1e-9,'invite faces rendered partner at once');
 mgr.pairFacing('avatar','keep','request','partner');
 mgr.pairFacing('avatar','rollback','old-request','partner');
 assert.ok(Math.abs(figure.root.rotation.y-Math.PI/2)<1e-9,'stale answer cannot undo newer preview');
 mgr.pairFacing('avatar','rollback','request','partner');assert.equal(figure.root.rotation.y,0);
 mgr.pairFacing('avatar','begin','steered','partner');mgr.faceTowards('avatar',0,-1,true);
 mgr.pairFacing('avatar','rollback','steered','partner');assert.ok(Math.abs(figure.root.rotation.y-Math.PI)<1e-9,'steering wins over late error');
 mgr.pairFacing('avatar','begin','bound','partner');
 state.interaction={id:'three',kind:'handshake',role:'a',anchor:{x:17,z:7,yaw:0},elapsed_s:0,rate:0};
 mgr.adoptInteraction(npc,state);mgr.pairFacing('avatar','rollback','bound','partner');
 assert.ok(Math.abs(figure.root.rotation.y-Math.PI/2)<1e-9,'pair start owns facing before delayed refusal');
 state.interaction=null;mgr.adoptInteraction(npc,state);
 figure.finishPropEntry=()=>true;
 const seat={x:root.position.x,y:root.position.y,z:root.position.z,yaw:0,place_id:'bench',slot:0,root_offset:0};
 mgr.playOwnMotion('avatar',{execution_id:'seated',journey_id:'',room_id:'room',waypoints:[[seat.x,seat.z]],
  paces_m_s_real:[],access:seat,anchor:seat,entry:null,departure:null},'request');
 mgr.pairFacing('avatar','begin','seated-turn','partner');
 mgr.tickOwnMotion(npc,true,now,0);
 assert.ok(Math.abs(figure.root.rotation.y-Math.PI/2)<1e-9,'held B1 seat keeps invite facing through its own tick');
 mgr.pairFacing('avatar','rollback','seated-turn','partner');assert.equal(figure.root.rotation.y,0);
 console.log('pair entry lifecycle and facing: ok');
} finally {globalThis.performance=saved}
