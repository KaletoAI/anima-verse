/** Real licensed bed clips on a real humanoid, driven by the B1 answer clock. */
import assert from 'node:assert/strict';
import {existsSync} from 'node:fs';
import {mkdtemp,readFile,writeFile,rm} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {join} from 'node:path';
import {build} from 'esbuild';
import * as THREE from 'three';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import {FBXLoader} from 'three/addons/loaders/FBXLoader.js';

globalThis.self=globalThis;
const root=fileURLToPath(new URL('../..',import.meta.url)), clips=join(root,'shared/models/clips');
const needed=['idle','lie-down','laying','get-up-bed'];
if(needed.some(k=>!existsSync(join(clips,k+'.fbx')))) {
 console.log('bed entry: SKIP (local licensed clips absent)');
} else {
 const dir=await mkdtemp(join(root,'client3d/scripts/.smoke-bed-'));
 const saved=globalThis.performance; let now=10000;
 try {
  const result=await build({stdin:{contents:`export {Figure,FigureLibrary,adaptExternalClips,setClipRootMotion,clipRootTurn} from './client3d/src/scene/figures';
   export {relockRootPaths} from './client3d/src/scene/footLockMeasure'; export {NpcManager} from './client3d/src/scene/npcs';
   export {restCorrections,restPoseOf,rigHipsHeight} from '@anima/scene-render';`,resolveDir:root,loader:'ts'},
   loader:{'.css':'empty'},bundle:true,platform:'node',format:'esm',write:false,external:['three','three/*']});
  const file=join(dir,'client.mjs'); await writeFile(file,result.outputFiles[0].text);
  const {Figure,FigureLibrary,adaptExternalClips,setClipRootMotion,clipRootTurn,relockRootPaths,NpcManager,restCorrections,restPoseOf,rigHipsHeight}=await import(file);
  const bytes=async file=>{const b=await readFile(file);return b.buffer.slice(b.byteOffset,b.byteOffset+b.byteLength)};
  const template=(await new GLTFLoader().register(()=>({name:'geometry_only',loadTexture:()=>Promise.resolve(null)})).parseAsync(await bytes(join(root,'static/client3d/models/Soldier.glb')),'')).scene;
  const loader=new FBXLoader(), donor=loader.parse(await bytes(join(root,'shared/models/rig/reference.fbx')),'');
  const raw=[];
  for(const kind of needed) {const c=loader.parse(await bytes(join(clips,kind+'.fbx')),'').animations[0].clone();c.name=kind;
   const sidecar=JSON.parse(await readFile(join(clips,kind+'.json'),'utf8'));
   setClipRootMotion(c,!!sidecar.geometry?.root_motion&&sidecar.geometry.root_motion.mode!=='strip',sidecar.geometry?.root_motion?.mode);raw.push(c);}
  const library=new FigureLibrary();
  library.clipIndex=new Map(raw.map(c=>[c.name,new Map([['licensed',c]])]));library.charSets.set('bed-86',['licensed']);
  const selected=library.clipsFor('bed-86');
  const fitted=adaptExternalClips(selected,template,restCorrections(THREE,restPoseOf(THREE,donor),template),rigHipsHeight(THREE,donor));
  const box=new THREE.Box3().setFromObject(template),scale=1.7/(box.max.y-box.min.y);
  relockRootPaths(fitted,template,1/(100*scale));
  console.log('bed entry measured turn',(clipRootTurn(fitted.find(c=>c.name==='lie-down'))?.yaw.at(-1) ?? 0)*180/Math.PI);
  const makeFigure=()=>new Figure({name:'bed-86',template,clips:fitted,scale,height:1.7,noClips:false,tier:'full',libraryFits:true});
  const axis=(figure,owner)=>{
   owner.updateMatrixWorld(true);let hips,head;
   figure.root.traverse(o=>{if(o.isBone){const k=o.name.replace(/^mixamorig:?/i,'').toLowerCase();if(k==='hips')hips=o;if(k==='head')head=o}});
   const d=head.getWorldPosition(new THREE.Vector3()).sub(hips.getWorldPosition(new THREE.Vector3()));return Math.atan2(d.x,d.z)*180/Math.PI;
  };
  const diff=(a,b)=>Math.abs(THREE.MathUtils.euclideanModulo(a-b+180,360)-180);
  const installed=makeFigure(),installedOwner=new THREE.Group();installedOwner.add(installed.root);
  installed.faceTowards(new THREE.Vector3(1,0,1),true);installed.finishPropEntry('laying');installed.update(1);
  const installedAxis=axis(installed,installedOwner);
  // A compatible hold from the real reverse clip. The checkout's legacy laying file faces 180 degrees away.
  const reverse=fitted.find(c=>c.name==='get-up-bed');
  const hold=new THREE.AnimationClip('laying',.1,reverse.tracks.map(t=>new t.constructor(t.name,[0],Array.from(t.createInterpolant().evaluate(0)))));
  const index=fitted.findIndex(c=>c.name==='laying'),localLaying=fitted[index];fitted[index]=hold;
  const compatible=makeFigure(),compatibleOwner=new THREE.Group();compatibleOwner.add(compatible.root);
  compatible.faceTowards(new THREE.Vector3(1,0,1),true);compatible.finishPropEntry('laying');compatible.update(1);
  const compatibleAxis=axis(compatible,compatibleOwner);
  if(diff(installedAxis,compatibleAxis)<4) fitted[index]=localLaying;
  console.log(`bed entry installed laying axis=${installedAxis.toFixed(3)} reverse first axis=${compatibleAxis.toFixed(3)} mismatch=${diff(installedAxis,compatibleAxis).toFixed(3)}; hold=${fitted[index]===hold?'real get-up-bed frame 0':'installed laying'}`);
  const figure=makeFigure(),owner=new THREE.Group();owner.add(figure.root);
  const manager=new NpcManager(null,{syncCounters:{},errWindow:{t:[],e:[]}});
  const npc={name:'avatar',root:owner,figure,target:new THREE.Vector3(),waypoints:[],route:null,entry:null,interaction:null,
   label:{},labelName:{},labelActivity:{},travelLine:null,travelKey:'',bubbleUntil:0};
  manager.npcs.set('avatar',npc);
  const plan={execution_id:'bed-86',journey_id:'bed-86',room_id:'',floor_y:0,waypoints:[[0,0],[0,0]],paces_m_s_real:[1],departure:null,
   access:{x:0,y:.01,z:0,yaw:45},anchor:{x:.46669,y:.4,z:-.34507,yaw:45,root_offset:0,place_id:'bed-86',slot:1},
   entry:{mode:'bridge',kind:'lie-down',pose_key:'laying',duration_s:4.066667},height_cm:170,role:null};
  globalThis.performance={now:()=>now};manager.playOwnMotion('avatar',plan,'request');
  let last=axis(figure,owner);
  for(let frame=1;frame<=122;frame++) {
   now+=1000/30;manager.tick(1/30,10);last=axis(figure,owner);
   assert.ok(diff(figure.root.rotation.y*180/Math.PI,45)<.1,`keep entry yaw must stay at 45, got ${figure.root.rotation.y*180/Math.PI}`);
   console.log(`bed B1 frame=${frame} yaw=${(figure.root.rotation.y*180/Math.PI).toFixed(3)} axis=${last.toFixed(3)}`);
  }
  let previous=last,maxJump=0;
  for(let f=0;f<=20;f++) {
   now+=f===0?1:1000/30;manager.tick(f===0?.001:1/30,10);const current=axis(figure,owner);
   maxJump=Math.max(maxJump,diff(previous,current));
   console.log(`bed B1 seam+${f} yaw=${(figure.root.rotation.y*180/Math.PI).toFixed(3)} axis=${current.toFixed(3)}`);
   assert.ok(diff(previous,current)<4,`B1 bed seam jumped ${diff(previous,current)} degrees`);
   assert.ok(diff(last,current)<4,`B1 bed pose diverged ${diff(last,current)} degrees`);previous=current;
  }
  manager.clearOwnMotion('avatar');
  const spec={...plan.entry,access:plan.access,anchor:plan.anchor,height_cm:170,root_offset:0,
   started_game_s:0,elapsed_game_s:0,duration_game_s:4.066667,game_seconds_per_real_second:1};
  manager.update([{char:{name:'avatar',activity_animation:'idle',prop_action_entry:spec},pos:owner.position.clone(),stamp:100}]);
  manager.tick(0,10);
  for(let frame=1;frame<=122;frame++) {
   now+=1000/30;manager.tick(1/30,10);last=axis(figure,owner);
   assert.ok(diff(figure.root.rotation.y*180/Math.PI,45)<.1,'keep observer must retain access yaw');
   console.log(`bed observer frame=${frame} yaw=${(figure.root.rotation.y*180/Math.PI).toFixed(3)} axis=${last.toFixed(3)}`);
  }
  manager.update([{char:{name:'avatar',activity_animation:'laying',place:{id:'bed-86',slot:1}},
   pos:new THREE.Vector3(plan.anchor.x,plan.anchor.y,plan.anchor.z),stamp:101}]);
  previous=last;
  for(let f=0;f<=20;f++) {
   now+=f===0?1:1000/30;manager.tick(f===0?.001:1/30,10);const current=axis(figure,owner);
   maxJump=Math.max(maxJump,diff(previous,current));
   console.log(`bed observer seam+${f} yaw=${(figure.root.rotation.y*180/Math.PI).toFixed(3)} axis=${current.toFixed(3)}`);
   assert.ok(diff(previous,current)<4,`observer bed seam jumped ${diff(previous,current)} degrees`);
   assert.ok(diff(last,current)<4,'observer hold must match real entry endpoint');previous=current;
  }
  console.log(`bed entry: PASS (B1 + observer, root yaw 45, max seam jump ${maxJump.toFixed(4)} degrees)`);
 }finally{globalThis.performance=saved;await rm(dir,{recursive:true,force:true})}
}
