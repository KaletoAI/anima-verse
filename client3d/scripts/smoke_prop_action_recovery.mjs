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
  endedOwnPropExecutions:new Set(),playedCancelMotions:new Set(),
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
 const f=setup();f.scope=await mainFunctions(['ownedPropRun','receivePropAnswer','adoptPropState','endPropRun','releaseLocalProp','resyncPropState','refreshPropMotion','refreshPropMotion','pollPropMotion'],f.deps,['avatarDrive','manualPropRelease','pendingReport','avatarSeated']);
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
 const f=setup();const scope=await mainFunctions(['ownedPropRun','receivePropAnswer','adoptPropState','endPropRun','releaseLocalProp','resyncPropState','refreshPropMotion'],f.deps);
 scope.receivePropAnswer({execution_id:'run',status:'approaching',motion:plan},'request');
 scope.receivePropAnswer({execution_id:'run',status,reason:'fixture'},'request');
 assert.equal(f.calls.filter(c=>c==='release').length,1);
}
{
 const f=setup();const scope=await mainFunctions(['ownedPropRun','receivePropAnswer','adoptPropState','endPropRun','releaseLocalProp','resyncPropState','refreshPropMotion'],f.deps);
 const run={execution_id:'run',status:'approaching',motion:plan};scope.receivePropAnswer(run,'request');
 scope.receivePropAnswer({execution_id:'run',status:'cancelled',motion:{seat:[2.5,0],stand:[2,0],exit_clip:'stand-up',exit_s:1}},'cancel');
 assert.equal(f.calls.filter(c=>c==='release').length,0,'cancel clip owns figure until it finishes');
 scope.adoptPropState({...state([]),recent_results:[{execution_id:'run',status:'cancelled'}]});
 assert.equal(f.calls.filter(c=>c==='release').length,0,'terminal private row cannot cut answer exit clip');
 f.deps.finishExit();assert.equal(f.calls.filter(c=>c==='release').length,1);
}
{
 const f=setup();const scope=await mainFunctions(['ownedPropRun','receivePropAnswer','adoptPropState','endPropRun','releaseLocalProp','resyncPropState','refreshPropMotion'],f.deps);
 scope.receivePropAnswer({execution_id:'run',status:'approaching',motion:plan},'request');
 scope.receivePropAnswer({execution_id:'run',status:'failed',reason:'HTTP 409'},'cancel');
 assert.equal(f.calls.filter(c=>c==='release').length,0,'failed cancel retains retriable own control');
 assert.equal(scope.ownedPropRun().execution_id,'run');
}
{
 const f=setup();const scope=await mainFunctions(['ownedPropRun','receivePropAnswer','adoptPropState','endPropRun','releaseLocalProp','resyncPropState','refreshPropMotion'],f.deps);
 scope.receivePropAnswer({execution_id:'run',status:'approaching',motion:plan},'request');
 scope.adoptPropState(state([{execution_id:'run',status:'active',motion:null}]));
 scope.adoptPropState({...state([]),recent_results:[{execution_id:'run',status:'completed',reason:'phases_completed'}]});
 assert.equal(f.calls.filter(c=>c==='release').length,1,'completed finite actions return player control');
}
// A terminal state and HUD answer compete for one departure, in either order.
for(const hudFirst of [false,true]) for(const status of ['completed','cancelled','failed']){
 const f=setup();const scope=await mainFunctions(['ownedPropRun','receivePropAnswer','adoptPropState','endPropRun','releaseLocalProp','resyncPropState','refreshPropMotion'],f.deps);
 scope.receivePropAnswer({execution_id:'run',status:'approaching',motion:plan},'request');
 scope.adoptPropState(state([{execution_id:'run',status:'active',motion:null}]));
 const answer={execution_id:'run',status:'completed',motion:{seat:[2.5,0],stand:[2,0],exit_clip:'stand-up',exit_s:1}};
 if(hudFirst) scope.receivePropAnswer(answer,'cancel');
 const terminal={...state([]),recent_results:[{...answer,status}]};
 scope.adoptPropState(terminal);
 scope.receivePropAnswer(answer,'cancel');scope.adoptPropState(terminal);
 assert.equal(f.calls.filter(c=>Array.isArray(c)&&c[0]==='exit').length,1,'terminal/HUD departure plays once');
 assert.equal(f.calls.filter(c=>c==='release').length,0,'departure retains figure');
 f.deps.finishExit();assert.equal(f.calls.filter(c=>c==='release').length,1);
}
{
 const f=setup();const scope=await mainFunctions(['ownedPropRun','receivePropAnswer','adoptPropState','endPropRun','releaseLocalProp','resyncPropState','refreshPropMotion'],f.deps);
 scope.receivePropAnswer({execution_id:'run',status:'approaching',motion:plan},'request');
 scope.adoptPropState({...state([]),recent_results:[{execution_id:'run',status:'completed',motion:null}]});
 const answer={execution_id:'run',status:'completed',motion:{seat:[2.5,0],stand:[2,0],exit_clip:'stand-up',exit_s:1}};
 scope.receivePropAnswer(answer,'cancel');scope.receivePropAnswer(answer,'cancel');
 assert.equal(f.calls.filter(c=>Array.isArray(c)&&c[0]==='exit').length,1,'late HUD after motionless end still departs once');
}
console.log('prop action terminal departure races: PASS');
// Another action on the same piece switches IN PLACE (prop_action_engine): the
// state shows the tracked run completed and a NEW own run current — the answer
// was "active" without a motion, or (via state) the partner said yes. Not a
// hand-back (fails on 97cc89a8: "handed back"): the played plan is let go once,
// the server keeps the figure, no position report is pending; the NEW run's own
// end hands back as before.
for(const via of ['answer','state']){
 const f=setup();const scope=await mainFunctions(['ownedPropRun','receivePropAnswer','adoptPropState','endPropRun','releaseLocalProp','resyncPropState','refreshPropMotion'],f.deps,['manualPropRelease','pendingReport']);
 const driven=[];f.deps.npcs.setServerDriven=(_name,on)=>driven.push(on);
 scope.receivePropAnswer({execution_id:'run',status:'approaching',motion:plan},'request');
 scope.adoptPropState(state([{execution_id:'run',status:'active',motion:null}]));
 if(via==='answer')scope.receivePropAnswer({execution_id:'next',status:'active',reason:'',motion:null},'request');
 scope.adoptPropState({...state([{execution_id:'next',status:'active',motion:null}]),recent_results:[{execution_id:'run',status:'completed',reason:'ended'}]});
 assert.ok(!f.calls.includes('[prop] motion ended: handed back'),`${via}: a switch is no hand-back`);
 assert.equal(scope.ownedPropRun()?.execution_id,'next',`${via}: the new run is the own run`);
 assert.equal(f.calls.filter(c=>c==='release').length,1,`${via}: the old plan is let go once`);
 assert.equal(driven.at(-1),true,`${via}: the server keeps the figure`);
 assert.equal(scope.snapshot().pendingReport,null);assert.equal(scope.snapshot().manualPropRelease,false);
 scope.adoptPropState({...state([]),recent_results:[{execution_id:'next',status:'completed',reason:'ended'}]});
 assert.ok(f.calls.includes('[prop] motion ended: handed back'),`${via}: the new run's end hands back`);
 assert.equal(driven.at(-1),false);
}
// A verdict about anything but the own run leaves that run alone: the server
// keeps the current action on a refusal (prop_action_engine.request_with_creation,
// "Refusals that need no route keep the current action"), a declined invitation
// is the inviter's run, a withdrawn one never was ours. The client asks /state.
const RECOVERY_NAMES=['ownedPropRun','receivePropAnswer','adoptPropState','endPropRun','releaseLocalProp','resyncPropState','refreshPropMotion'];
for(const [answer,source,label] of [
 [{execution_id:'',status:'failed',reason:'HTTP 409 claimed'},'request','refused new request'],
 [{execution_id:'invite',status:'cancelled',reason:'consent_declined'},'respond','declined invitation'],
 [{execution_id:'outgoing',status:'cancelled',reason:'cancelled',motion:{seat:[2.5,0],stand:[2,0],exit_clip:'stand-up',exit_s:1}},'cancel','withdrawn invitation'],
]){
 const f=setup();const scope=await mainFunctions(RECOVERY_NAMES,f.deps);
 scope.receivePropAnswer({execution_id:'run',status:'approaching',motion:plan},'request');
 f.deps.api.getPropActionState=async()=>{f.calls.push('state read');return state([{execution_id:'run',status:'active',motion:null}])};
 scope.receivePropAnswer(answer,source);
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(f.calls.filter(c=>c==='release').length,0,`${label} keeps the own run`);
 assert.ok(!f.calls.some(c=>Array.isArray(c)&&c[0]==='exit'),`${label} plays no stand-up`);
 assert.ok(f.calls.includes('state read'),`${label} re-reads /state`);
 assert.equal(scope.ownedPropRun()?.execution_id,'run',`${label} leaves the run owned`);
}
{
 // A request that replaced the own run and then failed: /state shows it ended.
 const f=setup();const scope=await mainFunctions(RECOVERY_NAMES,f.deps);
 scope.receivePropAnswer({execution_id:'run',status:'approaching',motion:plan},'request');
 f.deps.api.getPropActionState=async()=>({...state([]),recent_results:[{execution_id:'run',status:'completed',reason:'ended'}]});
 scope.receivePropAnswer({execution_id:'',status:'failed',reason:'HTTP 409 no_route'},'request');
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(f.calls.filter(c=>c==='release').length,1,'a run the server ended is released after the read');
}
// partner_consent "react": the run is the avatar's own from the start, on
// either side. The partner's resist ends it on the server — the initiator sees
// it end in /state, the partner in its own cancel answer — and the figure is
// released exactly once, however often the ended row is read again.
{
 const f=setup();const scope=await mainFunctions(RECOVERY_NAMES,f.deps);
 scope.receivePropAnswer({execution_id:'run',status:'approaching',motion:plan},'request');
 scope.adoptPropState(state([{execution_id:'run',status:'approaching',reason:'',motion:plan}]));
 const resisted={...state([]),recent_results:[{execution_id:'run',status:'cancelled',reason:'partner_resisted'}]};
 scope.adoptPropState(resisted);scope.adoptPropState(resisted);
 assert.equal(f.calls.filter(c=>c==='release').length,1,'initiator: resisted run released once');
 assert.equal(scope.ownedPropRun(),undefined,'initiator: no run left owned');
}
{
 const f=setup();const scope=await mainFunctions(RECOVERY_NAMES,f.deps);
 scope.adoptPropState(state([{execution_id:'run',status:'approaching',reason:'',motion:plan}]));
 assert.equal(scope.ownedPropRun()?.execution_id,'run','partner: the react run is owned at once');
 scope.receivePropAnswer({execution_id:'run',status:'cancelled',reason:'partner_resisted'},'cancel');
 scope.adoptPropState({...state([]),recent_results:[{execution_id:'run',status:'cancelled',reason:'partner_resisted'}]});
 assert.equal(f.calls.filter(c=>c==='release').length,1,'partner: pushed-away run released once');
 assert.equal(scope.ownedPropRun(),undefined,'partner: no run left owned');
}
console.log('prop action recovery: PASS (request/respond/state, release, stale execution, no burst, cancel exit ownership, foreign verdicts keep the own run, partner_resisted releases once)');

import {mainFunction} from './mainFunction.mjs';
for(const name of ['applyDriver','reconcileAvatarPlace','reconcileAvatarPos']){
 const scope=await mainFunction(name,{avatarName:'avatar',manualPropRelease:false,
  getGameState:()=>({mode:'embodied'}),pollIsStale:()=>false,ownCorrectionAt:0,ownSeatChangeAt:0,
  manualPropGate:{pending:false},npcs:{hasOwnMotion:()=>true},avatarDrive:{kind:'PLAYER'}});
 scope({characters:[{name:'avatar',place:{id:'WRONG',slot:99},pos:{x:99,z:99}}]},0);
}
console.log('prop action reconciliation: PASS (playing own motion blocks driver, seat and position adoption)');

{
 const f=setup();const scope=await mainFunctions(['ownedPropRun','receivePropAnswer','adoptPropState','endPropRun','releaseLocalProp','resyncPropState','refreshPropMotion'],f.deps,['propClickRevert']);
 scope.receivePropAnswer({execution_id:'invite',status:'awaiting_consent',motion:null},'request');
 assert.equal(scope.snapshot().propClickRevert,null,'accepted invitation drops only stale revert callback');
 scope.receivePropAnswer({execution_id:'invite',status:'cancelled',motion:null},'cancel');
 assert.equal(scope.snapshot().propClickRevert,null,'withdrawal allows a fresh target preview');
}

// manualPropRelease hides the avatar's server place/interaction after a local
// release. It ends once a read started after the release (worldmap AND private
// state) shows no live own run; a stale worldmap or a live run keeps it.
for(const [label,mapPolledAt,current,expected] of [
 ['fresh read without a live run clears it',20,[],false],
 ['stale worldmap keeps it',5,[],true],
 ['live own run keeps it',20,[{execution_id:'run',status:'active'}],true],
]){
 const map={characters:[{name:'avatar',location_id:'house',room_id:'room'}]};
 const scope=await mainFunctions(['syncPlaceGlyphs'],{
  avatarName:'avatar',lastMap:map,offersGeneration:0,offersAppliedGeneration:0,propStateEpoch:0,propOffersRoomKey:JSON.stringify(['house','room']),
  ownSeatChangeAt:10,mapPolledAt,manualPropRelease:true,placeOffers:[],placeOffersRoom:'',semanticOffers:[],propStateUncertain:false,
  api:{invalidatePropActionOffers(){},getPropActionState:async()=>({current,outgoing:[],recent_results:[]}),getPlaces:async()=>({places:[],room_id:'room'}),
   getPropActions:async()=>[],isAuthError:()=>false},
  setGameState(){},getGameState:()=>({}),propPreparation:{adoptFreshState(){}},pollIsStale:(at,changed)=>at<changed,
  performance:{now:()=>15},logPropOffers(){},adoptPropState(){},rebuildPlaceGlyphs(){},figures:{state:'loading'},
  uiActions:{toast:message=>{throw new Error(message)}},
 },['manualPropRelease']);
 await scope.syncPlaceGlyphs(map);
 assert.equal(scope.snapshot().manualPropRelease,expected,label);
}
console.log('prop action release gate: PASS (manualPropRelease ends on a fresh read without a live own run)');
