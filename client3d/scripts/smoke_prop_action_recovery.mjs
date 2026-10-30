/** B1 lifecycle closures: answers start playback; ordinary state confirms or releases. */
import assert from 'node:assert/strict';
import {mainFunctions} from './mainFunction.mjs';
import {motion} from './propActionVectorDispatch.mjs';
const plan={execution_id:'run',journey_id:'journey',waypoints:[[0,0],[2,0]],paces_m_s_real:[1],floor_y:0,room_id:'room',departure:null,
 access:{x:2,y:0,z:0,yaw:90},anchor:{x:2.5,y:.4,z:0,yaw:90,root_offset:0,place_id:'chair',slot:1},entry:null};
const state=current=>({current,outgoing:[],recent_results:[]});
function setup(){
 const calls=[], gate=motion.createManualPropGate(), preparation=motion.createPropPreparationBarrier();
 const deps={requestedPropRun:null,trackedPropRun:null,semanticState:state([]),releasedPropExecutions:new Set(),
  propMutationPending:false,propStateEpoch:0,propStateUncertain:false,manualPropRelease:false,
  propPreparation:preparation,manualPropGate:gate,avatarName:'avatar',avatarDrive:{kind:'SERVER'},avatarSeated:true,seatedKey:'old',
  ownSeatChangeAt:0,answerFloor:0,posSeq:2,pendingReport:{},avatarCancelled:null,
  cancelRoute(){calls.push('route cancelled')},walkIn:null,correction:null,
  npcs:{ownMotionJourney:()=>plan.journey_id,setServerDriven(){},playOwnMotion:(_name,plan,source)=>calls.push(['play',plan,source]),
   playOwnCancel:(_name,departure,done)=>{calls.push(['exit',departure]);deps.finishExit=done},
   clearOwnMotion(){calls.push('release')},clearPropEntry(){},setPlayerPose(){},setPlayerAnimation(){}},
  console:{info:line=>calls.push(line)},api:{getPropActionState:async()=>{calls.push('state read');return state([])}},
  uiActions:{toast:line=>calls.push(line)},propClickRevert:()=>calls.push('revert')};
 return {deps,calls,preparation,scope:null};
}
for(const source of ['request','respond','state']){
 const f=setup();f.scope=await mainFunctions(['ownedPropRun','receivePropAnswer','adoptPropState','endPropRun','releaseLocalProp','refreshPropMotion','pollPropMotion'],f.deps,['avatarDrive','manualPropRelease','pendingReport','avatarSeated']);
 const run={execution_id:'run',status:'approaching',reason:'',motion:plan};
 if(source==='state')f.scope.adoptPropState(state([run]));else f.scope.receivePropAnswer(run,source);
 assert.ok(f.calls.some(c=>Array.isArray(c)&&c[0]==='play'&&c[2]===source),'answer/state starts immediately');
 assert.ok(!f.calls.includes('state read'),'no private/world poll before answer playback');
 assert.equal(f.scope.snapshot().avatarDrive.kind,'PLAYER');assert.equal(f.scope.snapshot().pendingReport,null);
 for(let i=0;i<120;i++)f.scope.pollPropMotion();assert.ok(!f.calls.includes('state read'),'playback never starts burst polling');
 f.scope.adoptPropState({...state([]),recent_results:[{...run,status:'failed',reason:'geometry_changed'}]});
 assert.equal(f.calls.filter(c=>c==='release').length,1);assert.equal(f.scope.ownedPropRun(),undefined);
 assert.equal(f.scope.snapshot().manualPropRelease,true);
 f.scope.adoptPropState(state([run]));assert.equal(f.calls.filter(c=>Array.isArray(c)&&c[0]==='play').length,1,'stale released execution cannot restart');
}
for(const status of ['cancelled','failed','refused']){
 const f=setup();const scope=await mainFunctions(['ownedPropRun','receivePropAnswer','adoptPropState','endPropRun','releaseLocalProp'],f.deps);
 scope.receivePropAnswer({execution_id:'run',status:'approaching',motion:plan},'request');
 scope.receivePropAnswer({execution_id:'run',status,reason:'fixture'},'request');
 assert.equal(f.calls.filter(c=>c==='release').length,1);
}
{
 const f=setup();const scope=await mainFunctions(['ownedPropRun','receivePropAnswer','adoptPropState','endPropRun','releaseLocalProp'],f.deps);
 const run={execution_id:'run',status:'approaching',motion:plan};scope.receivePropAnswer(run,'request');
 scope.receivePropAnswer({execution_id:'run',status:'cancelled',motion:{seat:[2.5,0],stand:[2,0],exit_clip:'stand-up',exit_s:1}},'cancel');
 assert.equal(f.calls.filter(c=>c==='release').length,0,'cancel clip owns figure until it finishes');
 scope.adoptPropState({...state([]),recent_results:[{execution_id:'run',status:'cancelled'}]});
 assert.equal(f.calls.filter(c=>c==='release').length,0,'terminal private row cannot cut answer exit clip');
 f.deps.finishExit();assert.equal(f.calls.filter(c=>c==='release').length,1);
}
{
 const f=setup();const scope=await mainFunctions(['ownedPropRun','receivePropAnswer','adoptPropState','endPropRun','releaseLocalProp'],f.deps);
 scope.receivePropAnswer({execution_id:'run',status:'approaching',motion:plan},'request');
 scope.receivePropAnswer({execution_id:'run',status:'failed',reason:'HTTP 409'},'cancel');
 assert.equal(f.calls.filter(c=>c==='release').length,0,'failed cancel retains retriable own control');
 assert.equal(scope.ownedPropRun().execution_id,'run');
}
{
 const f=setup();const scope=await mainFunctions(['ownedPropRun','receivePropAnswer','adoptPropState','endPropRun','releaseLocalProp'],f.deps);
 scope.receivePropAnswer({execution_id:'run',status:'approaching',motion:plan},'request');
 scope.adoptPropState(state([{execution_id:'run',status:'active',motion:null}]));
 scope.adoptPropState({...state([]),recent_results:[{execution_id:'run',status:'completed',reason:'phases_completed'}]});
 assert.equal(f.calls.filter(c=>c==='release').length,1,'completed finite actions return player control');
}
console.log('prop action recovery: PASS (request/respond/state, release, stale execution, no burst, cancel exit ownership)');

import {mainFunction} from './mainFunction.mjs';
for(const name of ['applyDriver','reconcileAvatarPlace','reconcileAvatarPos']){
 const scope=await mainFunction(name,{avatarName:'avatar',manualPropRelease:false,
  getGameState:()=>({mode:'embodied'}),pollIsStale:()=>false,ownCorrectionAt:0,ownSeatChangeAt:0,
  manualPropGate:{pending:false},npcs:{hasOwnMotion:()=>true},avatarDrive:{kind:'PLAYER'}});
 scope({characters:[{name:'avatar',place:{id:'WRONG',slot:99},pos:{x:99,z:99}}]},0);
}
console.log('prop action reconciliation: PASS (playing own motion blocks driver, seat and position adoption)');

{
 const f=setup();const scope=await mainFunctions(['ownedPropRun','receivePropAnswer','adoptPropState','endPropRun','releaseLocalProp'],f.deps,['propClickRevert']);
 scope.receivePropAnswer({execution_id:'invite',status:'awaiting_consent',motion:null},'request');
 assert.equal(scope.snapshot().propClickRevert,null,'accepted invitation drops only stale revert callback');
 scope.receivePropAnswer({execution_id:'invite',status:'cancelled',motion:null},'cancel');
 assert.equal(scope.snapshot().propClickRevert,null,'withdrawal allows a fresh target preview');
}
