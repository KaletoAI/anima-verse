/** Hand oracle: native/fixtures/placement/avatar_rooms.json. Exercises the production poll closure:
 * identical XZ must snap 3 m upward, own echoes included; rides/inside same-storey lag stay untouched.
 * Usage: node client3d/scripts/smoke_avatar_rooms.mjs
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { build } from 'esbuild';
import { mainFunctions } from './mainFunction.mjs';
const f = JSON.parse(readFileSync(new URL('../../native/fixtures/placement/avatar_rooms.json', import.meta.url)));
const built = await build({ stdin: { contents: `export * from './client3d/src/game/npcPlacement'; export * as THREE from 'three';`, resolveDir: process.cwd(), loader: 'ts' }, bundle: true, platform: 'node', format: 'esm', write: false });
const m = await import(`data:text/javascript;base64,${Buffer.from(built.outputFiles[0].text).toString('base64')}`);
const tile = { center:f.center, yaw:f.yaw, roomCenters:new Map(Object.entries(f.rooms).map(([id,r])=>[id,r.center])),
  roomLevels:new Map(Object.entries(f.rooms).map(([id,r])=>[id,r.level])), roomFloors:new Map(Object.entries(f.rooms).map(([id,r])=>[id,{hull:r.hull}])) };
const guards = ['seat','pair','prop','unavailable','server','flight','walkIn','correction','stale'];
const scenarios = f.cases.map(c => ({c,guard:null})).concat(guards.map(guard => ({c:f.cases[0],guard})));
for (const {c,guard} of scenarios) for (const ready of [true,false]) {
  const shouldCorrect=c.correct && !guard;
  let isReady=ready;
  const lines=[];
  let placed, walked, held;
  const body = new m.THREE.Vector3(f.center.x,.01,f.center.z);
  const row = { name:'demo', location_id:'inn', room_id:c.room, pos:c.pos ?? {x:body.x,z:body.z}, pos_origin:c.echo ? {session:'own',seq:1} : null };
  const state={pendingSnap:null};
  const run = await mainFunctions(['reconcileAvatarPos','correctTo','releasePendingSnap'], {
    ...m, getGameState:()=>({mode:'embodied'}), avatarName:'demo', avatarDrive:{kind:guard === 'server' ? 'SERVER' : 'PLAYER'},
    npcs:{hasOwnMotion:()=>guard==='prop',propEntryUnavailable:()=>guard==='unavailable',inInteraction:()=>guard==='pair',positionOf:()=>body,
      snapPlayerTo:(_name,p)=>{placed=p;body.copy(p);},setPlayerTarget:(_name,p)=>{walked=p;}},
    pollIsStale:()=>guard==='stale', ownSeatChangeAt:0, ownCorrectionAt:0, ownRoomChangeAt:0, avatarBodyRoom:c.bodyRoom ?? 'lower', avatarCancelled:null, clearSnap(){state.pendingSnap=null;}, clearApproach(){},
    readinessDeps:{placeAt:()=> 'inn',isReady:()=>isReady},readinessState:state,avatarSeated:guard==='seat',pendingSnap:null,
    trySnap:()=>isReady,roomFloorY:()=>f.rooms[c.room].center.y,reportedPos:null,posDirty:false,
    posInFlight:guard==='flight',walkIn:guard==='walkIn' ? {} : null,verticalRide:c.ride ? {} : null,correction:guard==='correction' ? {} : null,
    isOwnEcho:()=>c.echo,sentSeqs:[1],posSession:'own',POS_SNAP_M:2,CORRECT_WALK_M:8,
    tileAt:()=>tile,roomStandY:(_t,room)=>f.rooms[room].center.y,
    residency:new Map([['inn',{tile}]]),holdSnap:(_d,_s,p)=>{held=p;state.pendingSnap=p;},cancelRoute(){},
    syncCounters:{posCorr:0},CORRECT_MS:3000,console:{debug:line=>lines.push(line)},
    engine:{flyTo(){},targetDist:7},groundY:()=>0,performance:{now:()=>100},
  }, ['pendingSnap','correction']);
  await run.reconcileAvatarPos({characters:[row]},100);
  if(shouldCorrect && !ready) {
    assert.equal(placed,undefined,c.label+' held until ready');
    assert.equal(held.id,'inn');
    assert.equal(held.roomCorrection.point.y,c.expected.y);
    isReady=true;
    // The real holdSnap owns readinessState.pendingSnap; main's accessor mirrors it.
    const release=await mainFunctions(['releasePendingSnap'], { ...m, pendingSnap:held,trySnap:()=>isReady,
      verticalRide:null,avatarSeated:false,posInFlight:false,avatarDrive:{kind:'PLAYER'},avatarName:'demo',
      npcs:{inInteraction:()=>false,hasOwnMotion:()=>false,snapPlayerTo:(_name,p)=>{placed=p;}},
      clearApproach(){},readinessDeps:{},readinessState:state,avatarBodyRoom:'lower',ownCorrectionAt:0,
      syncCounters:{posCorr:0},engine:{flyTo(){},targetDist:7},clearSnap(){},posDirty:false,groundY:()=>0,
      console:{debug:line=>lines.push(line)},performance:{now:()=>100},
    });
    release.releasePendingSnap();
  }
  if (shouldCorrect && ready) await run.reconcileAvatarPos({characters:[row]},101);
  assert.equal(!!placed,shouldCorrect,c.label);
  if(shouldCorrect && !ready) assert.equal(walked.y,.01,c.label+' hold keeps body');
  else assert.equal(walked,undefined,c.label);
  assert.equal(!!held,shouldCorrect && !ready,c.label);
  assert.equal(lines.length,shouldCorrect ? 1 : 0,c.label+' logs');
  if(shouldCorrect) for(const key of ['x','y','z']) assert(Math.abs(placed[key]-c.expected[key])<1e-7,c.label+' '+key);
}
console.log(`avatar room reconciliation: ${f.cases.length} shared fixture cases, ready/held paths and ${guards.length} movement guards passed`);
