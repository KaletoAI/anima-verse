/** Actual detached-HUD HTTP mutations deliver their answers through the bridge. */
import assert from 'node:assert/strict';
import {loadHudRealm} from './load_hud_realm.mjs';
const scene=loadHudRealm(),hud=loadHudRealm();
const [a,b]=scene.loopbackPair();
const previews=[];scene.gameActions.preparePropAction=async(_requestId,target)=>{previews.push(target)};
const stopHud=hud.connectHudSide(b),stopScene=scene.connectSceneSide(a);
const sceneApi=scene.load('packages/player-ui/src/propActions.ts'),hudApi=hud.load('packages/player-ui/src/propActions.ts');
const received=[];const off=sceneApi.onPropActionChanged((requestId,result,source)=>received.push({requestId,result,source}));
const savedFetch=globalThis.fetch;
try{
 const answer={execution_id:'run',status:'approaching',reason:'',motion:{journey_id:'own-plan',waypoints:[[0,0],[1,0]]}};
 globalThis.fetch=async()=>new Response(JSON.stringify(answer),{status:200});
 const target={location_id:'loc',room_id:'room',placement_id:'chair',variant_uid:'v'};
 await hudApi.requestPropAction('sit',target,'revision');
 assert.deepEqual(previews.at(-1),target,'detached preparation carries exact clicked target before HTTP');
 assert.deepEqual(received.at(-1).result,answer,'request answer motion reaches scene before another poll');assert.equal(received.at(-1).source,'request');
 await hudApi.respondPropAction('run',true);assert.equal(received.at(-1).source,'respond');
 const cancel={execution_id:'run',status:'cancelled',reason:'',motion:{seat:[1,0],stand:[0,0],exit_clip:'up',exit_s:1}};
 globalThis.fetch=async()=>new Response(JSON.stringify(cancel),{status:200});
 await hudApi.cancelPropAction('run');assert.deepEqual(received.at(-1).result,cancel);assert.equal(received.at(-1).source,'cancel');
 globalThis.fetch=async()=>new Response(JSON.stringify({detail:{reason:'claimed'}}),{status:409});
 await assert.rejects(hudApi.requestPropAction('sit',{},'revision'),/claimed/);
 assert.equal(received.at(-1).result.status,'failed','detached HUD HTTP refusal reaches scene release path');assert.equal(received.at(-1).source,'request');
 await assert.rejects(hudApi.cancelPropAction('run'),/claimed/);assert.equal(received.at(-1).result.execution_id,'run');assert.equal(received.at(-1).source,'cancel');
}finally{globalThis.fetch=savedFetch;off();stopScene();stopHud()}
console.log('prop action answer bridge: PASS (request/respond/cancel motion and HTTP409 failures cross detached HUD)');
