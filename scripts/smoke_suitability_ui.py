#!/usr/bin/env python3
"""Task 12 UI contract. Usage: .venv/bin/python scripts/smoke_suitability_ui.py

Suitability 1/2 are obsolete; 3 and later survive. Deletion must read disk
under the write lock, preserve capabilities and current history, and remove
obsolete raw answers. Node exercises actual rendering and start serialization.
"""
import json
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
ctx.suitRenderJob({status:'done',summary:{scorer_version:'suitability-5',verdict:'no - tools',checks:[{ok:false,group:'tools',task:'thought',prompt:{system:'<system>',user:'user text'},runs:[{content:'<answer>'}]}]}});
assert(el('suitProgress').innerHTML.includes('&lt;system&gt;'));
assert(el('suitProgress').innerHTML.includes('&lt;answer&gt;'));
assert(el('suitProgress').innerHTML.includes('<details>'));
el('suitProvider').value='P'; el('suitModel').value='M'; el('suitConcurrency').value='2';
ctx.suitPoll=()=>{}; ctx.suitJobsRefresh=()=>{};
ctx.fetch=async (url,options)=>{assert.strictEqual(JSON.parse(options.body).concurrency,2);return {ok:true,json:async()=>({job_id:'one'})};};
ctx.suitStart().then(()=>{assert(!el('suitStatus').textContent.startsWith('Error:')); console.log('Suitability UI JavaScript parses, string verdict renders, concurrency sent OK');});
"""], check=True)
