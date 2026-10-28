#!/usr/bin/env node
/**
 * Task 46 fixture contract. Hand derivations are native/fixtures/embody/README.md:
 * frame step17/300, frame57 arrival, patch slide(7,10), party wall slide(-.3,.2),
 * accepted/refused correction distances4/13, offers at the listed probe points.
 * This verifies the authored data through production pure helpers; it does not
 * implement the future native fixture server or any prop-action behavior.
 */
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { embodyDispatch as m } from './embodyVectorDispatch.mjs';
import { near } from '../../shared/test-vectors/vectors.mjs';
const dir = new URL('../../native/fixtures/embody/', import.meta.url);
const read = file => JSON.parse(readFileSync(new URL(file, dir), 'utf8'));
let passed = 0;
const check = (label, actual, expected, eps = 1e-9) => {
  const result = near(expected, actual, eps);
  assert.ok(result.ok, `${label}: ${result.diff}`); passed++;
};
const map = read('worldmap.json'), scene = read('scene_loc-hall.json');
const [avatar, npc] = map.characters;
const height = read('heightfield.json');
check('height lattice shape', [height.rows, height.cols], [33,65]);
assert.ok(height.heights.length === height.rows && height.heights.every(r => r.length === height.cols));
for (let r=0;r<height.rows;r++) for (let c=0;c<height.cols;c++) {
  const x=height.origin_x+c, z=height.origin_z+r;
  assert.equal(height.heights[r][c], x>=10&&x<=14&&z>=-2&&z<=2 ? 1 : 0);
}
check('one metre rise blocked', m.slopeBlocks(1,1,map.max_step_height_m,map.max_slope_deg), true);
check('half metre lead blocked', m.slopeBlocks(.5,.5,.4,40), true);
check('drop permitted', m.slopeBlocks(-1,1,.4,40), false);
let point={...avatar.pos};
for(let n=1;n<=60;n++) {
  const dir=m.walkDir(['w'],0); point={x:point.x+dir.x*17/300,z:point.z+dir.z*17/300};
  if ([15,30,60].includes(n)) check(`walk frame ${n}`,point,{x:-3,z:({15:.15,30:-.7,60:-2.4})[n]});
}
point={...avatar.pos}; let frames=0;
while(!m.reachedGoal(point,{x:-3,z:-2.4})) {
  const dir=m.goalDir(point,{x:-3,z:-2.4});
  point={x:point.x+dir.x*17/300,z:point.z+dir.z*17/300}; frames++;
  assert.ok(frames<100,'finite click walk');
}
check('click arrives on frame57',[frames,point.z],[57,-2.23]);
const patch=read('terrain.json').areas[0].polygon;
check('patch authored rectangle',patch,[[8,8],[12,8],[12,12],[8,12]]);
check('terrain slide',m.slideBlocked({x:7,z:9},{x:9,z:10},{rects:[[8,8,12,12]],inclusive:true}),{x:7,z:10});
const walls=m.wallSegments(scene,0);
check('party wall slides',m.clampAgainstWalls({x:-.3,z:0},{x:.3,z:.2},walls,.25),{x:-.3,z:.2});
check('party door passes',m.clampAgainstWalls({x:-.3,z:2},{x:.3,z:2},walls,.25),{x:.3,z:2});
check('outside door passes',m.clampAgainstWalls({x:3,z:3},{x:3,z:5},walls,.25),{x:3,z:5});
check('two room plus upper storey',scene.rooms.map(r=>[r.room_id,r.level]),[['r-a',0],['r-b',0],['r-up',1]]);
const stops=scene.extras.filter(e=>e.kind==='elevator_pad').map(e=>({level:e.level,pos:{x:e.center[0],z:e.center[2]}}));
check('lift top faces',scene.extras.filter(e=>e.kind==='elevator_pad').map(e=>e.center[1]+e.size[1]/2),[.01,3.01]);
const rooms=scene.rooms.map(r=>({id:r.room_id,level:r.level,center:{x:0,z:0}}));
check('lift serves two storeys',m.elevatorAt({x:3,z:2},0,stops,rooms,1),{levels:[0,1],current:0,dist:1});
check('lift strict range',m.elevatorAt({x:5.5,z:2},0,stops,rooms,1),null);
check('sole destination',m.elevatorSoleOption({levels:[0,1],current:0}),1);
check('one stair flight',scene.stairs.length,1);
check('ten authored ascending treads',scene.extras.filter(e=>e.kind==='stair_tread')
  .map(e=>[e.center[0],e.center[1]+e.size[1]/2,e.size[0]]),
  [[.625,.3,.25],[.875,.6,.25],[1.125,.9,.25],[1.375,1.2,.25],[1.625,1.5,.25],
   [1.875,1.8,.25],[2.125,2.1,.25],[2.375,2.4,.25],[2.625,2.7,.25],[2.875,3,.25]]);
check('stair endpoints',[scene.stairs[0].foot,scene.stairs[0].head],[[0,.01,-2],[3.5,3.01,-2]]);
check('talk at initial point',m.talkTargetNear({name:avatar.name,pos:avatar.pos,locId:'loc-hall',room:'r-a'},[{name:npc.name,pos:npc.pos,locId:'loc-hall',room:'r-a',scale:1}]),{name:'fixture-npc',dist:2});
const locations=map.locations.map(l=>({locId:l.id,footprint:{x:l.pos_x,z:l.pos_z,yaw:0},boundary:l.boundary,openings:l.openings,locked:l.id==='loc-locked'}));
check('hall entry',m.entryOfferNear({x:3,z:6},'',locations),{locId:'loc-hall',point:{x:3,z:4},dist:2,inward:{x:0,z:-1}});
check('free rim entry',m.entryOfferNear({x:30,z:0},'',locations),{locId:'loc-free',point:{x:28,z:0},edge:null,dist:2,inward:{x:-1,z:0}});
check('locked entry still offered',m.entryOfferNear({x:40,z:6},'',locations),{locId:'loc-locked',point:{x:40,z:4},dist:2});
const marker=scene.markers[0], free=[{id:marker.id,free:marker.slots.map(([x,z])=>({x,z}))}];
check('room marker source and slots',[marker.source,marker.capacity,marker.diorama],['room',2,true]);
check('diorama pick boundary',m.pickablePlaceFor({x:-3.3,z:.6},free,.6),'room-seat');
check('diorama pick outside',m.pickablePlaceFor({x:-3.3,z:.7},free,.6),null);
check('seat root height',marker.y_world-marker.root_offset,.05);
assert.ok(scene.models.some(model=>model.role==='room'&&model.room_id===marker.room_id));
const urls=read('urls.json');
for(const file of Object.values(urls)) assert.ok(existsSync(file.startsWith('repo:')
  ? new URL(file.slice(5),new URL('../../',import.meta.url)) : new URL(file,dir)),file);
const answers=read('pos_answers.json');
check('answer format',answers.format,'anima-pos-answers/1');
const endpoints=new Set();
for(const steps of Object.values(answers.scenarios)) for(const s of steps) {
  endpoints.add(`${s.method} ${s.path}`);
  assert.ok(Number.isInteger(s.status)&&s.status>=200&&s.status<500);
  if(s.path==='/play/pos') check('pos wire fields',Object.keys(s.request).sort(),['seq','session','t_ms','x','z']);
}
check('exact endpoint scope',[...endpoints].sort(),['GET /play/places','POST /play/enter-room','POST /play/pos','POST /play/self/activity']);
const places=answers.scenarios['take-room-pose'][0].body.places[0];
check('room poses',places.poses.map(p=>p.key),['sitting','reading']);
check('two free slots',places.free_slots,[0,1]);
for(const [scenario,distance] of [['refusal-walk',4],['refusal-snap',13]]) {
  const answer=answers.scenarios[scenario][0];
  check(scenario,Math.hypot(answer.request.x-answer.body.pos.x,answer.request.z-answer.body.pos.z),distance);
}
console.log(`Embodiment fixture: ${passed} passed`);
