#!/usr/bin/env node
/** Task 56 authored fixture. Hand numbers: native/fixtures/propactions/README.md. */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { motion } from './propActionVectorDispatch.mjs';
import { near } from '../../shared/test-vectors/vectors.mjs';
const dir = new URL('../../native/fixtures/propactions/', import.meta.url);
const read = name => JSON.parse(readFileSync(new URL(name, dir), 'utf8'));
let checks = 0;
const check = (actual, expected, label) => {
  const result = near(expected, actual);
  assert.ok(result.ok, `${label}: ${result.diff}`); checks++;
};
const map = read('worldmap.json'), scene = read('scene_loc-props.json');
const answers = read('answers.json'), offers = read('offers.json'), actions = read('actions.json');
check([scene.rooms.length, scene.models.length, scene.markers.length], [1,1,1], 'one room and prop');
check(map.characters.map(c => [c.name,c.room_id,c.pos]), [
  ['fixture-avatar','r-props',{x:-3,z:-2}], ['fixture-npc','r-props',{x:4,z:2}],
], 'synthetic participants');
const prop = scene.models[0], marker = scene.markers[0];
const target = {location_id:'loc-props',room_id:'r-props',placement_id:'bench-56',variant_uid:'variant-56'};
check([prop.placement_id, prop.variant_uid, marker.placement_id, marker.variant_uid],
  ['bench-56','variant-56','bench-56','variant-56'], 'exact placement provenance');
check(actions.map(a => [a.id,a.ability,a.participants]),
  [['pose-56','pose',1],['pair-56','pair',2]], 'solo and pair definitions');
check(marker.action_bindings.map(b => [b.action_id,b.marker_id,b.variant_uid]),
  [['pose-56','seat56','variant-56'],['pair-56','seat56','variant-56']], 'both derived bindings');
for (const offer of offers) {
  check(offer.target,target,'offer exact target');
  check(offer.definition_revision,'revision-56','immutable revision');
}
check(offers.map(o => [o.action_id,o.enabled,o.required_partner]),
  [['pose-56',true,false],['pair-56',true,true]], 'honest partner requirement');
check(offers[1].available_targets,[{partner:'fixture-npc',enabled:true,reason:''}], 'exact offered partner');
check(marker.y_world-marker.root_offset,.129,'support .527 minus offset .398');
const approach = read('worldmap_approach.json');
const path = approach.characters[0].travel;
check(path.total_m,6,'three plus one plus two metre legs');
for (const [age,point] of [[0,[-3,-2]],[3,[0,-2]],[4,[0,-1]],[5,[1,-1]],[6,[2,-1]],[20,[2,-1]]])
  check(motion.localApproachPoint(path,age),point,`approach age ${age}`);
const entry = read('worldmap_entry.json').characters[0].prop_action_entry;
check([entry.access.x,entry.access.y,entry.access.z], [2,0,-1], 'floor access');
check([entry.anchor.x,entry.anchor.y,entry.anchor.z], [2,.129,0], 'body anchor distinct from access');
check(motion.entryPhase(entry,0),.5,'entry halfway');
check(motion.entrySupportLift(1,.5,.75,entry.access.y,entry.anchor.y,entry.root_offset),.0645,'measured support correction');
check(read('worldmap_active.json').characters[0].prop_action_entry,null,'entry clears on activation');
check(read('worldmap_active.json').characters[0].place,
  {id:'prop-bench-56-seat56',slot:0,x:2,z:0,facing:180,room_id:'r-props'},'authoritative held place');
const height = read('heightfield.json');
check(height.heights, [[0,0,0],[0,0,0],[0,0,0]], 'own flat heightfield');
check(read('worldmap_cancelled.json').characters[0].travel,null,'cancel clears journey');
const pair = read('worldmap_pair.json');
check(pair.characters[0].travel.journey_id,'journey-56-invite-avatar','own journey');
const local = pair.characters[1].local_approach;
check(Object.keys(local).sort(), ['journey_id','room_id','waypoints','progress_m','walked_m','remaining_m','paces_m_s_real','starts_in_s'].sort(), 'foreign motion has no consent or execution');
check([local.remaining_m,motion.localApproachPoint(local,2)], [5,[5,1]], 'NPC one plus three plus one metre route');
check(answers.format,'anima-prop-action-answers/1','answer format');
const bodyOf = step => Object.hasOwn(step,'body') ? step.body : read(step.body_file);
const scenario = name => answers.scenarios[name];
const rows = name => scenario(name).map(bodyOf);
for (const [name,steps] of Object.entries(answers.scenarios)) for (const step of steps) {
  assert.notEqual(Object.hasOwn(step,'body'),Object.hasOwn(step,'body_file'),name);
  assert.ok(['GET','POST'].includes(step.method) && step.path.startsWith('/play/'));
  if (step.method === 'GET') assert.equal(step.request,null);
  else {
    const fields = step.path.endsWith('/request') ? ['action_id','revision','target',...(step.request.partner ? ['partner'] : [])]
      : step.path.endsWith('/respond') ? ['execution_id','accept'] : ['execution_id'];
    assert.deepEqual(Object.keys(step.request).sort(),fields.sort(),name);
  }
  const body = bodyOf(step);
  if (step.path === '/play/prop-actions/state') {
    check(Object.keys(body).sort(),['incoming','outgoing','current','recent_results'].sort(),`${name} private state`);
    for (const row of Object.values(body).flat()) {
      check(row.target,target,`${name} lifecycle target`);
      assert.equal(row.can_respond, row.status === 'awaiting_consent' && row.partner === 'fixture-avatar');
      for (const key of ['execution_id','action_id','definition_revision','actor','partner','roles','phase','phase_label','label','reason','can_cancel'])
        assert.ok(Object.hasOwn(row,key),`${name}: ${key}`);
    }
  }
}
check(rows('solo')[0],offers,'offers route body');
check(rows('solo')[1],{execution_id:'execution-56-solo',status:'approaching',reason:''},'request returns lifecycle only');
check(rows('solo')[3],approach,'request followed by authoritative approach snapshot');
check(rows('solo')[7].current[0].phase,'active','pose activation uses Core active phase');
check(rows('pair-request')[0],{execution_id:'execution-56-outgoing',status:'awaiting_consent',reason:''},'outgoing invitation does not move');
check(rows('pair-request')[1].outgoing[0].can_respond,false,'initiator cannot consent');
check(rows('pair-accept')[0].incoming[0].can_respond,true,'only exact invitee can consent');
check(rows('pair-accept')[1],{execution_id:'execution-56-invite',status:'approaching',reason:''},'accepted invitation starts approach');
check(rows('pair-accept')[2].current[0].roles,
  {actor:'fixture-npc',partner:'fixture-avatar',clip:{a:'fixture-avatar',b:'fixture-npc'},
    access:{actor:'partner',partner:'actor'}},'semantic participants differ from physical clip/access roles');
check(rows('pair-decline')[1],{execution_id:'execution-56-invite',status:'cancelled',reason:'consent_declined'},'declined invitation');
check(rows('cancel')[0],{execution_id:'execution-56-solo',status:'cancelled',reason:'cancelled'},'explicit awaited cancellation');
check(rows('stale-revision')[0],{detail:{execution_id:'',status:'refused',reason:'stale_definition'}},'HTTP refusal envelope');
check(scenario('stale-revision')[0].status,409,'stale revision HTTP status');
console.log(`prop action fixture: all ok (${checks} checks)`);
