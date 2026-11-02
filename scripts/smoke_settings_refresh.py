"""Usage: ./.venv/bin/python scripts/smoke_settings_refresh.py

Hand expectations for static/admin/settings.js refreshIfChangedElsewhere():
- same revision r1 on return: CONFIG stays, nothing re-rendered, no toast;
- revision r2 and no edits: CONFIG becomes the fetched {b:2}, revision r2,
  overrides from /origin, one re-render, one success toast;
- revision r3 with an unsaved edit (DIRTY): CONFIG and revision unchanged,
  no re-render, one error toast naming "another page";
- an edit made while /origin loads: the fetched config is NOT taken;
- a failing fetch leaves the page as it was.
Node vm with a stubbed DOM; no server.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
subprocess.run(["node", "-e", r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const listeners={};
const content={scrollTop:5};
const ctx={console,setTimeout:()=>0,clearTimeout:()=>{},
  document:{getElementById:()=>content,addEventListener:(t,f)=>{listeners[t]=f;},visibilityState:'visible'},
  window:{addEventListener:(t,f)=>{listeners['w'+t]=f;},location:{hash:''}},history:{}};
vm.createContext(ctx);
const src=fs.readFileSync('static/admin/settings.js','utf8').replace(/\ninit\(\);\n$/,'\n');
vm.runInContext(src,ctx);
let renders=0,toasts=[];
// Top-level functions of the script are properties of ctx; stub them there.
ctx.buildNav=()=>{};ctx.renderSection=async()=>{renders++;};ctx.toast=(m,t)=>toasts.push([m,t]);
const state=()=>JSON.parse(vm.runInContext('JSON.stringify({config:CONFIG,revision:CONFIG_REVISION,overrides:[...OVERRIDES]})',ctx));
let raw,originHook=null;
ctx.fetch=async url=>{
  if(url.includes('/raw')){ if(raw.fail) throw new Error('down'); return {ok:true,headers:{get:()=>raw.rev},json:async()=>raw.data}; }
  if(originHook) originHook();
  return {ok:true,json:async()=>({overrides:['llm_routing']})};
};
(async()=>{
  vm.runInContext("CONFIG={a:1};CONFIG_REVISION='r1';",ctx);
  assert(listeners.visibilitychange && listeners.wfocus);
  raw={rev:'r1',data:{x:1}};await ctx.refreshIfChangedElsewhere();
  assert.deepStrictEqual(state().config,{a:1});assert.strictEqual(renders,0);assert.strictEqual(toasts.length,0);
  raw={rev:'r2',data:{b:2}};await ctx.refreshIfChangedElsewhere();
  const s=state();assert.deepStrictEqual(s.config,{b:2});assert.strictEqual(s.revision,'r2');assert.deepStrictEqual(s.overrides,['llm_routing']);
  assert.strictEqual(renders,1);assert.strictEqual(toasts.length,1);assert.strictEqual(toasts[0][1],'success');assert.strictEqual(content.scrollTop,5);
  vm.runInContext('DIRTY=true;',ctx);
  raw={rev:'r3',data:{c:3}};await ctx.refreshIfChangedElsewhere();
  assert.deepStrictEqual(state().config,{b:2});assert.strictEqual(state().revision,'r2');assert.strictEqual(renders,1);
  assert.strictEqual(toasts[1][1],'error');assert(toasts[1][0].includes('another page'));
  vm.runInContext('DIRTY=false;',ctx);
  originHook=()=>vm.runInContext('MUTATION_REVISION++;',ctx);
  raw={rev:'r4',data:{d:4}};await ctx.refreshIfChangedElsewhere();
  assert.deepStrictEqual(state().config,{b:2});assert.strictEqual(renders,1);
  originHook=null;
  raw={fail:true};await ctx.refreshIfChangedElsewhere();
  assert.deepStrictEqual(state().config,{b:2});
  console.log('Settings refresh: same revision, clean take-over, dirty refusal, mid-load edit and failure OK');
})().catch(e=>{console.error(e);process.exit(1);});
"""], cwd=ROOT, check=True)
