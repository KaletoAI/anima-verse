#!/usr/bin/env python3
"""Task 12 UI contract. Usage: .venv/bin/python scripts/smoke_suitability_ui.py

Suitability 1/2 are obsolete; 3 and later survive. Deletion must read disk
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
    suits = {"p::seen-images": {"tested_suitability": {"scorer_version": "suitability-5", "vision": {"rate": 1.0}}}}
    manager = SimpleNamespace(list_all_models=lambda: listed)
    with patch.object(admin_routes, "get_provider_manager", return_value=manager), patch.object(
            admin_routes, "get_all_suitability", return_value=suits), patch.object(
            admin_routes, "get_model_capabilities", side_effect=lambda name: {"vision": None, "tool_calling": None}), patch.object(
            admin_routes, "get_all_capabilities", return_value={}):
        rows = {m["name"]: m for m in admin_routes.model_capabilities_data()["models"]}
    assert rows["seen-images"]["capabilities"]["vision"] is True and rows["seen-images"]["reported"] == {"vision": "test"}
    assert rows["text-only"]["capabilities"]["vision"] is False
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
assert(el('suitStatus').innerHTML.includes('no - speed'));
assert(el('suitStatus').innerHTML.includes('measured under live play'));
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
el('suitProvider').value='P'; el('suitModel').value='M'; el('suitConcurrency').value='2';
ctx.suitPoll=()=>{}; ctx.suitJobsRefresh=()=>{};
ctx.fetch=async (url,options)=>{assert.strictEqual(JSON.parse(options.body).concurrency,2);return {ok:true,json:async()=>({job_id:'one'})};};
ctx.suitStart().then(()=>{assert(!el('suitStatus').textContent.startsWith('Error:')); console.log('Suitability UI JavaScript parses, string verdict renders, concurrency sent OK');});
"""], check=True)
