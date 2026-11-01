#!/usr/bin/env python3
"""Task 12 UI contract. Usage: .venv/bin/python scripts/smoke_suitability_ui.py

Suitability 1–4 are obsolete; 5 and later survive.
Hand-derived UI expectations: entries for thought/extraction/image_analysis on one
model at 0.1/0.5/0.3 copy those three temperatures, regardless of the chosen entry.
Without a vision assignment its prior 0.7 stays. One running and one queued A job
plus one running B job produce "A: 1 running, 1 waiting · B: 1 running".
The detail panel and badge contain the explicit settings; POST contains settings
and concurrency only, with no routing reference. Deletion must read disk
under the write lock, preserve capabilities and current history, and remove
obsolete raw answers. Node exercises actual rendering and start serialization.
"""
import json
from types import SimpleNamespace
import subprocess
import tempfile
import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths

with tempfile.TemporaryDirectory() as directory:
    paths.init(directory)
    from app.core import model_capabilities as caps
    from app.routes import admin_settings as routes
    target = Path(directory) / "caps.json"
    outputs = Path(directory) / "outputs.json"
    old = {"tested_suitability": {"scorer_version": "suitability-4"}}
    new = {"tested_suitability": {"scorer_version": "suitability-5"}}
    data = {"models": {"demo": {"vision": True}}, "suitability": {"old": old, "new": new},
            "suitability_history": {"old": [old], "new": [old, new]}}
    with patch.object(caps, "_caps_path", return_value=target), patch.object(caps, "_outputs_path", return_value=outputs):
        target.write_text(json.dumps(data))
        outputs.write_text(json.dumps({"outputs": {"old": {}, "new": {"scorer_version": "suitability-5"}},
                                       "history": {"new": [{"scorer_version": "suitability-4"}, {"scorer_version": "suitability-5"}]}}))
        caps.invalidate_cache()
        assert set(caps.get_all_suitability()) == {"new"}
        # A fresh disk entry must survive even after the read cache was filled.
        data["suitability"]["fresh"] = new
        target.write_text(json.dumps(data))
        routes.llm_suitability_delete_old(user=None)
        saved = json.loads(target.read_text())
        assert set(saved["suitability"]) == {"new", "fresh"}
        assert saved["models"] == data["models"]
        assert saved["suitability_history"] == {"new": [new]}
        raw = json.loads(outputs.read_text())
        assert set(raw["outputs"]) == {"new"}
        assert raw["history"] == {"new": [{"scorer_version": "suitability-5"}]}
        with patch("app.core.model_suitability.load_cases", return_value={"cases": []}):
            caps.save_raw_outputs("new", {"scorer_version": "suitability-5", "cases": {}})
            caps.save_suitability("new", new)
            record = caps.get_all_suitability()["new"]
            first_id = record["tested_suitability"]["diagnostic_run_id"]
            assert first_id == caps.get_suitability_outputs("new")["run_id"]
            caps.save_raw_outputs("new", {"scorer_version": "suitability-5", "cases": {}})
            assert first_id != caps.get_suitability_outputs("new")["run_id"]
            assert first_id == caps.get_suitability_outputs("new", first_id)["run_id"]
        caps.invalidate_cache()
    summary = {"scorer_version": "suitability-5", "fixture_version": "original", "diagnostic_run_id": "first",
               "checks": [{"id": "failure", "ok": False}]}
    fixture = {"fixture_version": "changed", "cases": [{"id": "failure", "system": "wrong prompt", "user": "wrong"}]}
    raw = {"run_id": "second", "cases": {"failure": [{"content": "wrong answer"}]},
           "prompts": {"failure": {"system": "wrong prompt", "user": "wrong"}}}
    with patch.object(caps, "get_all_suitability", return_value={"new": {"tested_suitability": summary}}), patch.object(
            caps, "get_suitability_outputs", return_value=raw), patch(
            "app.core.model_suitability.load_cases", return_value=fixture):
        status = routes.llm_suitability_test_status("saved:new", user=None)
        check = status["summary"]["checks"][0]
        assert check["runs"] == [] and not check["prompt"]["system"]
        raw["run_id"] = "first"
        raw["prompts"]["failure"] = {"system": "actual system", "user": "actual user"}
        status = routes.llm_suitability_test_status("saved:new", user=None)
        assert status["summary"]["checks"][0]["prompt"]["system"] == "actual system"
    # Running detail must retain this job's own prompts and answers.
    live_check = {"id": "failure", "ok": False, "prompt": {"system": "live system", "user": "live user"},
                  "runs": [{"content": "live answer"}]}
    with patch("app.core.model_suitability.get_job", return_value={
            "model": "P::M", "status": "running", "checks": [live_check]}), patch.object(
            caps, "get_suitability_outputs", return_value={}), patch(
            "app.core.model_suitability.load_cases", return_value=fixture):
        status = routes.llm_suitability_test_status("live", user=None)
        assert status["checks"][0]["prompt"]["system"] == "live system"
        assert status["checks"][0]["runs"][0]["content"] == "live answer"
    # The queue lists waiting/running jobs and those ended within ten minutes;
    # saved results are no queue rows (they open from the model table).
    jobs = [{"job_id": j, "position": 0, "model": "m", "status": st, "finished_ago_s": ago,
             "summary": {"scorer_version": "suitability-5"} if st == "done" else {}}
            for j, st, ago in (("run", "running", None), ("wait", "queued", None),
                               ("fresh", "done", 599.0), ("stale", "done", 601.0),
                               ("err", "error", 30.0))]
    with patch("app.core.model_suitability.list_jobs", return_value=jobs), patch.object(
            caps, "get_all_suitability", return_value={"P::m": {"tested_suitability": summary}}):
        listed = [j["job_id"] for j in routes.llm_suitability_test_jobs(user=None)["jobs"]]
    assert listed == ["run", "wait", "fresh", "err"], listed
    # Model table: what a llama-swap /models entry reports, name-derived
    # parameter size, and the fill order stored > last test > provider.
    from app.core.provider import _reported_capabilities, _parameter_size_from_name
    swap = {"id": "gemma-4-26b-a4b-it-q6-k", "capabilities": {"function_calling": True, "vision": True},
            "meta": {"llamaswap": {"quantization": "q6-k"}}}
    assert _reported_capabilities(swap) == {"vision": True, "tool_calling": True, "quantization": "q6-k"}
    text_only = {"id": "granite-switch-4.1-8b-bf16", "architecture": {"input_modalities": ["text"]}}
    assert _reported_capabilities(text_only) == {"vision": False, "tool_calling": None, "quantization": ""}
    assert _reported_capabilities({"id": "x", "supported_parameters": ["tools"]})["tool_calling"] is True
    assert _reported_capabilities({"id": "gpt-4o"}) == {"vision": None, "tool_calling": None, "quantization": ""}
    for name, size in (("gemma-4-26b-a4b-it", "26B-A4B"), ("granite-switch-4.1-8b-bf16", "8B"),
                       ("together/Qwen/Qwen3.5-9B", "9B"), ("lfm3-1.7b-bf16", "1.7B"), ("gpt-4o", "")):
        assert _parameter_size_from_name(name) == size, (name, _parameter_size_from_name(name))
    stored_no = {"vision": False, "tool_calling": None}
    assert caps.prefill_from_provider(stored_no, {"vision": True, "tool_calling": True}) == ["tool_calling"]
    assert stored_no == {"vision": False, "tool_calling": True}
    from app.routes import admin as admin_routes
    listed = {"P": {"models": [
        {"name": "seen-images", "vision": False, "tool_calling": None},
        {"name": "text-only", "vision": False, "tool_calling": True}]}}
    suits = {"p::seen-images": {"tested_suitability": {"scorer_version": "suitability-5", "vision": {"rate": 1.0}}},
             # A disabled/offline provider lists no models; its saved result still gets a row.
             "off::tested-elsewhere": {"tested_score": "9/16", "tested_suitability": {
                 "scorer_version": "suitability-5", "model": "Off::tested-elsewhere", "vision": {"rate": 0.0}}}}
    manager = SimpleNamespace(list_all_models=lambda: listed)
    with patch.object(admin_routes, "get_provider_manager", return_value=manager), patch.object(
            admin_routes, "get_all_suitability", return_value=suits), patch.object(
            admin_routes, "get_model_capabilities", side_effect=lambda name: {"vision": None, "tool_calling": None}), patch.object(
            admin_routes, "get_all_capabilities", return_value={}):
        rows = {m["name"]: m for m in admin_routes.model_capabilities_data()["models"]}
    assert rows["seen-images"]["capabilities"]["vision"] is True and rows["seen-images"]["reported"] == {"vision": "test"}
    assert rows["text-only"]["capabilities"]["vision"] is False
    assert rows["seen-images"]["listed"] is True
    off = rows["tested-elsewhere"]
    assert (off["provider"], off["listed"], off["has_result"], off["capabilities"]["tested_score"]) == \
        ("Off", False, True, "9/16"), off
    assert rows["text-only"]["reported"] == {"vision": "provider", "tool_calling": "provider"}
print("Suitability UI old-result filtering, deletion and exact diagnostic identity OK")
subprocess.run(["node", "--check", "static/admin/models.js"], check=True)
source = Path("static/admin/models.js").read_text()
subprocess.run(["node", "-e", r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const elements = new Map();
const el = id => { if (!elements.has(id)) elements.set(id, {value:'', innerHTML:'', textContent:'', checked:false}); return elements.get(id); };
const ctx = {document:{getElementById:el}, setTimeout:()=>0, clearTimeout:()=>{}, console};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync('static/admin/models.js','utf8').replace(/loadData\(\);\s*suitInit\(\);\s*$/, ''), ctx);
ctx.suitRenderJob({status:'done', summary:{scorer_version:'suitability-5', verdict:'no - speed', tool:'9/10',helper:'8/10',vision:{rate:1},speed:{tools:{median_latency_s:2,tok_s:30}},projected_turn_s:25,live_play:true,checks:[]}});
assert(el('suitDetailStatus').innerHTML.includes('no - speed'));
assert(el('suitDetailStatus').innerHTML.includes('measured under live play'));
assert(ctx.testBadge({tested_score:'1/1',tested_verdict:'yes',tested_suitability:{scorer_version:'suitability-5'}}).includes('yes'));
assert(ctx.testBadge({tested_score:'1/1',tested_suitability:{scorer_version:'suitability-4'}}).includes('none'));
const rich = ctx.testBadge({tested_score:'13/16',tested_verdict:'no - tools',tested_suitability:{scorer_version:'suitability-5',
    model:'Evo::gemma',tool:'9/11',helper:'2/3',vision:{rate:1},projected_turn_s:18.7,speed:{tools:{median_latency_s:3.8}}}});
assert(rich.includes('13/16 · no - tools'), rich);
const fast = ctx.speedCell({tested_suitability:{scorer_version:'suitability-5',verdict:'no - tools',projected_turn_s:18.74,
    speed:{tools:{median_latency_s:3.8},helpers:{median_latency_s:6.97}}}});
assert(fast.includes('speed-turn fast') && fast.includes('18.7 s/turn') && fast.includes('tools 3.8 s · helpers 6.97 s'), fast);
assert(ctx.speedCell({tested_suitability:{scorer_version:'suitability-5',verdict:'no - speed',projected_turn_s:107}}).includes('speed-turn slow'));
const both = ctx.speedCell({tested_suitability:{scorer_version:'suitability-5',verdict:'no - tools',speed_ok:false,max_turn_seconds:20,projected_turn_s:31}});
assert(both.includes('speed-turn slow') && both.includes('limit 20 s'), both);
assert(ctx.speedCell({tested_suitability:{scorer_version:'suitability-4',projected_turn_s:5}}).includes('none'));
assert.strictEqual(ctx.getSortValue({capabilities:{}}, 'speed'), Number.MAX_VALUE);
const shown = ctx.capToggle('m', 'vision', false, 'provider');
assert(shown.includes('cap-reported') && shown.includes('Reported by the provider') && shown.includes('data-value="true"'), shown);
assert(ctx.capToggle('m', 'vision', true, 'test').includes('From the last test'));
assert(!ctx.capToggle('m', 'vision', true).includes('cap-reported'));
assert(rich.includes('Tools 9/11 · Helpers 2/3 · Vision 100%'), rich);
assert(rich.includes("suitShowSaved('Evo::gemma')"), rich);
ctx.suitRenderJob({status:'done',summary:{scorer_version:'suitability-5',verdict:'no - tools',checks:[{ok:false,group:'tools',task:'thought',prompt:{system:'<system>',user:'user text'},runs:[{content:'<answer>'}]}]}});
assert(el('suitProgress').innerHTML.includes('&lt;system&gt;'));
assert(el('suitProgress').innerHTML.includes('&lt;answer&gt;'));
assert(el('suitProgress').innerHTML.includes('<details>'));
// Hand expectation: three stored run checks, all truncated, give 3/3 even without summary counts.
const cutoff = {scorer_version:'suitability-5',settings:{thinking:false,max_tokens:900},thinking_runs:3,reasoning_tokens_median:216,
    checks:[{id:'facts_only',ok:false,run_checks:[{ok:false,truncated:true},{ok:false,truncated:true},{ok:false,truncated:true}],
    runs:[{content:'',finish_reason:'length',usage:{reasoning_tokens:216}}]}]};
assert(ctx.testBadge({tested_suitability:cutoff}).includes('3/3 cut off'));
assert(ctx.testBadge({tested_suitability:cutoff}).includes('thinks (3 runs)'));
ctx.suitRenderJob({status:'done',summary:cutoff});
assert(el('suitDetailStatus').innerHTML.includes('suit-warn'));
assert(el('suitDetailStatus').innerHTML.includes('3 of 3 answers were cut off'));
assert(el('suitProgress').innerHTML.includes('cut off 3/3'));
assert(el('suitProgress').innerHTML.includes('cut off at the token limit - 216 reasoning tokens'));
// One capped run among two runs shows 1/2; reported median 40 sits beside speed.
ctx.suitRenderJob({status:'done',summary:{scorer_version:'suitability-5',speed:{tools:{reasoning_tokens_median:40}},checks:[
    {ok:false,group:'tools',budget_hits:1,run_checks:[{},{}],runs:[{content:'answer',budget_hit:true},{content:'other'}]}]}});
assert(el('suitProgress').innerHTML.includes('budget hit 1/2'));
assert(el('suitProgress').innerHTML.includes('(thinking capped at the budget, answer continued)'));
assert(el('suitDetailStatus').innerHTML.includes('reasoning median 40 tokens'));
assert(ctx.suitSettingsText({thinking:false}).includes('Thinking: off'));
const entries = [
    {index:0,provider:'P',model:'M',temperature:0.1,tasks:[{task:'thought',order:0}]},
    {index:1,provider:'P',model:'M',temperature:0.5,tasks:[{task:'extraction',order:0}]},
    {index:2,provider:'P',model:'M',temperature:0.3,tasks:[{task:'image_analysis',order:0}]},
    {index:3,provider:'P',model:'M',temperature:0.9,enabled:false,tasks:[{task:'image_analysis'}]},
];
const tasks = {tools:['thought'],helpers:['extraction'],vision:['image_analysis']};
const copied = ctx.suitPrefillTemperatures(entries[1],entries,tasks,{tools:1,helpers:1,vision:0.7});
assert.strictEqual(JSON.stringify(copied), JSON.stringify({tools:0.1,helpers:0.5,vision:0.3}));
const partial = ctx.suitPrefillTemperatures(entries[1],[entries[0],entries[1],entries[3]],tasks,{tools:1,helpers:1,vision:0.7});
assert.strictEqual(partial.vision,0.7);
// No enabled match: the chosen entry still supplies its own served group.
const fallback = ctx.suitPrefillTemperatures(entries[3],[entries[3]],tasks,{tools:0.1,helpers:0.5,vision:0.7});
assert.strictEqual(fallback.vision,0.9);
ctx.prefillEntries = entries;
vm.runInContext('suitEntries = prefillEntries; suitGroupTasks = {tools:["thought"], helpers:["extraction"], vision:["image_analysis"]}; suitCombobox = {reload:()=>{}};',ctx);
entries[1].repetition_penalty=1.03;entries[1].max_tokens=1200;entries[1].chat_template='<template>';
entries[1].thinking='on';entries[1].thinking_budget=200;entries[1].extra_params={nested:{test:true}};
el('suitPrefill').value='1';ctx.suitPrefill();
assert.strictEqual(el('suitProvider').value,'P');assert.strictEqual(el('suitModel').value,'M');
assert.strictEqual(el('suitTempTools').value,0.1);assert.strictEqual(el('suitTempHelpers').value,0.5);assert.strictEqual(el('suitTempVision').value,0.3);
assert.strictEqual(el('suitPenalty').value,1.03);assert.strictEqual(el('suitMaxTokens').value,1200);
assert.strictEqual(el('suitChatTemplate').value,'<template>');for (const group of ['Tools','Helpers','Vision']) { assert.strictEqual(el('suitThinking'+group).value,'on'); assert.strictEqual(el('suitBudget'+group).value,200); assert.strictEqual(el('suitBudget'+group).disabled,false); }
assert.strictEqual(JSON.parse(el('suitExtraParams').value).nested.test,true);
assert.strictEqual(el('suitPrefill').value,'');
entries[1].max_tokens=2000;assert.strictEqual(el('suitMaxTokens').value,1200);
for (const mode of ['off','task']) {
    entries[1].thinking=mode;el('suitPrefill').value='1';ctx.suitPrefill();
    for (const group of ['Tools','Helpers','Vision']) {
        assert.strictEqual(el('suitThinking'+group).value,'off');
        assert.strictEqual(el('suitBudget'+group).disabled,true);
    }
}
el('suitThinkingTools').value='on';ctx.suitThinkingChanged('Tools');
assert.strictEqual(el('suitBudgetTools').disabled,false);

assert.strictEqual(ctx.suitQueueSummary([{model:'A::one',status:'running'},{model:'A::two',status:'queued'},{model:'B::one',status:'running'}]),'A: 1 running, 1 waiting · B: 1 running');
assert.strictEqual(ctx.suitQueueSummary([]),'Queue empty');
assert.strictEqual(ctx.suitQueueSummary([{model:'A::one',status:'done'}]),'A: idle');
const settings = {temperature:{tools:0.1,helpers:0.5,vision:0.3},max_tokens:900,thinking:false,repetition_penalty:1.03,chat_template:'<template>',extra_params:{foo:'<bar>'}};
ctx.suitRenderJob({status:'running',model:'P::M',settings,checks:[]});
assert.strictEqual(el('suitDetail').hidden,false);
assert(el('suitSettings').innerHTML.includes('Max tokens: 900'));
assert(el('suitSettings').innerHTML.includes('&lt;template&gt;'));
assert(el('suitSettings').innerHTML.includes('&lt;bar&gt;'));
const settingsBadge = ctx.testBadge({tested_suitability:{scorer_version:'suitability-5',settings}});
assert(settingsBadge.includes('Temperatures: tools 0.1'));
assert(settingsBadge.includes('repetition_penalty') && settingsBadge.includes('&lt;template&gt;'));
el('suitProvider').value='P'; el('suitModel').value='M'; el('suitConcurrency').value='2';
el('suitTempTools').value='0.1';el('suitTempHelpers').value='0.5';el('suitTempVision').value='0.3';
el('suitMaxTokens').value='900';for (const group of ['Tools','Helpers','Vision']) { el('suitThinking'+group).value='off'; el('suitBudget'+group).value=''; }el('suitExtraParams').value='{}';
ctx.suitPoll=()=>{}; ctx.suitJobsRefresh=()=>{};
ctx.fetch=async (url,options)=>{const body=JSON.parse(options.body);assert.strictEqual(body.concurrency,2);assert.strictEqual(JSON.stringify(body.settings.temperature),JSON.stringify({tools:0.1,helpers:0.5,vision:0.3}));assert.strictEqual(JSON.stringify(body.settings.thinking),JSON.stringify({tools:false,helpers:false,vision:false}));assert.strictEqual(JSON.stringify(body.settings.thinking_budget),JSON.stringify({tools:null,helpers:null,vision:null}));assert.strictEqual(Object.keys(body).sort().join(','),'concurrency,model,provider,settings');return {ok:true,json:async()=>({job_id:'one'})};};
assert.strictEqual(ctx.suitSettingsText({thinking:{tools:true,helpers:false,vision:false},thinking_budget:{tools:200}}).includes('Thinking: tools on (budget 200), helpers off, vision off'),true);
assert.strictEqual(ctx.suitThinkingText({thinking_runs:3,thinking_leak_runs:0,settings:{thinking:{tools:true}}}), '');
assert(ctx.suitThinkingText({thinking_runs:3,thinking_leak_runs:1,settings:{thinking:{tools:true}}}).includes('although thinking was off'));
ctx.suitStart().then(()=>{assert(!el('suitStatus').textContent.startsWith('Error:')); console.log('Suitability UI prefill, queue summary, settings detail, escaping and explicit POST OK');});
"""], check=True)

subprocess.run(["node", "-e", r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const elements=new Map();
const el=id=>{if(!elements.has(id))elements.set(id,{innerHTML:'',textContent:''});return elements.get(id);};
const ctx={document:{getElementById:el},setTimeout:()=>0,clearTimeout:()=>{},console};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync('static/admin/models.js','utf8').replace(/loadData\(\);\s*suitInit\(\);\s*$/, ''),ctx);
const settings={max_tokens:900};
// Hand-derived: one interrupted job is visible in the collapsed header;
// Discard first arms an inline question, and recovery sends POST then refreshes.
const queueRefresh = ctx.suitJobsRefresh;
const interrupted = [{job_id:'saved',model:'P::<M>',provider:'P',status:'interrupted',settings}];
ctx.fetch=async()=>({ok:true,json:async()=>({jobs:interrupted})});
(async()=>{
    await queueRefresh();
    assert.strictEqual(el('suitQueueBox').open,false);
    assert.strictEqual(el('suitInterruptedNotice').hidden,false);
    assert(el('suitInterruptedNotice').innerHTML.includes('1 tests were interrupted by a server restart'));
    assert(el('suitInterruptedNotice').innerHTML.includes('Resume'));
    assert(el('suitInterruptedNotice').innerHTML.includes('Discard'));
    assert(!el('suitInterruptedNotice').innerHTML.includes('Discard interrupted tests?'));
    assert(el('suitQueue').innerHTML.includes('Interrupted'));
    assert(el('suitQueue').innerHTML.includes('&lt;M&gt;'));
    assert(el('suitQueue').innerHTML.includes('Max tokens: 900'));
    assert(el('suitQueue').innerHTML.includes('suitCancel'));
    vm.runInContext('suitDiscardArmed=true',ctx);
    ctx.suitInterruptedNotice(interrupted);
    assert(el('suitInterruptedNotice').innerHTML.includes('Discard interrupted tests?'));
    for (const action of ['resume','discard-interrupted']) {
        let refreshed=false;
        ctx.suitJobsRefresh=async()=>{refreshed=true;};
        ctx.fetch=async(url,options)=>{
            assert.strictEqual(url,'/admin/settings/llm-suitability-test/'+action);
            assert.strictEqual(options.method,'POST');return {ok:true};
        };
        await ctx.suitInterruptedAction(action);
        assert(refreshed);
    }
    ctx.suitInterruptedNotice([]);
    assert.strictEqual(el('suitInterruptedNotice').hidden,true);
    console.log('Suitability interrupted header, rows, inline confirmation and recovery POST OK');
})().catch(error=>{console.error(error);process.exitCode=1;});

"""], check=True)
