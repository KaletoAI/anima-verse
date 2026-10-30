#!/usr/bin/env node
/** Request boundary: preview precedes HTTP, asked keeps it, errors/declined roll back, decline never turns. */
import assert from 'node:assert/strict';
import {build} from 'esbuild';
const built=await build({entryPoints:['packages/player-ui/src/pairInteractions.ts'],bundle:true,write:false,platform:'node',format:'esm'});
const pair=await import(`data:text/javascript;base64,${Buffer.from(built.outputFiles[0].text).toString('base64')}`);
const trace=[];
const off=pair.setPairFacing((phase,id,partner)=>trace.push({phase,id,partner}));
const savedFetch=globalThis.fetch;let release;
try {
 globalThis.fetch=(path,init)=>{
  trace.push({path,body:JSON.parse(init.body)});
  return new Promise(resolve=>{release=(status,body)=>resolve(new Response(JSON.stringify(body),{status,headers:{'content-type':'application/json'}}))});
 };
 const waiting=pair.invitePair('Partner','hug');
 assert.equal(trace[0].phase,'begin');assert.equal(trace[0].partner,'Partner');
 assert.equal(trace[1].path,'/play/interact');assert.deepEqual(trace[1].body,{partner:'Partner',pose:'hug'});
 release(200,{status:'asked'});await waiting;
 assert.equal(trace.at(-1).phase,'keep');
 for(const status of [400,404,409]) {
  const request=pair.invitePair('Partner','hug');release(status,{detail:'refused'});
  await assert.rejects(request);assert.equal(trace.at(-1).phase,'rollback');
 }
 const accepted=pair.respondPair('invite',true,'Inviter');
 assert.equal(trace.at(-2).partner,'Inviter');assert.equal(trace.at(-2).phase,'begin');
 assert.deepEqual(trace.at(-1).body,{invite_id:'invite',accept:true});
 release(200,{status:'declined'});await accepted;assert.equal(trace.at(-1).phase,'rollback');
 trace.length=0;const declined=pair.respondPair('invite',false,'Inviter');
 assert.equal(trace.length,1);assert.equal(trace[0].path,'/play/interact/respond');release(200,{status:'declined'});await declined;
 assert.equal(trace.length,1,'explicit decline never turns');
 globalThis.fetch=async()=>{throw new Error('network')};
 await assert.rejects(pair.invitePair('Partner','hug'));assert.equal(trace.at(-1).phase,'rollback');
 console.log('pair invite/respond boundary: ok');
} finally {off();globalThis.fetch=savedFetch}
