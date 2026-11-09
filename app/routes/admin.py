"""Admin routes — model capabilities management."""
from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from typing import Any, Dict, List, Optional

from app.core.model_capabilities import (
    get_all_capabilities,
    get_model_capabilities,
    get_all_suitability,
    get_all_rp_results,
    prefill_from_provider,
    save_model_capability,
    delete_model_capability)
from app.core.model_capabilities_migration import has_capability_info
from app.core.provider_manager import get_provider_manager
from app.core.auth_dependency import require_admin

router = APIRouter(prefix="/admin", tags=["admin"],
                   dependencies=[Depends(require_admin)])


class CapabilityUpdate(BaseModel):
    pattern: str
    tool_calling: Optional[bool] = None
    vision: Optional[bool] = None
    uncensored: Optional[bool] = None
    notes_de: str = ""
    tool_instruction: str = ""


class CapabilityDelete(BaseModel):
    pattern: str


@router.get("", include_in_schema=False)
@router.get("/", include_in_schema=False)
def admin_root():
    """Redirect /admin to /admin/settings."""
    return RedirectResponse(url="/admin/settings", status_code=302)


@router.get("/models", response_class=HTMLResponse)
def model_capabilities_page():
    """Admin page for model capabilities."""
    return HTMLResponse(content=_build_models_html())


@router.get("/models/data")
def model_capabilities_data() -> Dict[str, Any]:
    """JSON API: every available model plus its capabilities and routing labels."""
    from app.core import config
    from app.core.llm_refusal import refusal_counts
    refusal_models = refusal_counts()["models"]
    pm = get_provider_manager()
    all_caps = get_all_capabilities()
    suit_all = get_all_suitability()  # Key: "provider::model" (lowercased)
    rp_all = get_all_rp_results()  # same key, a table of its own
    routing = config.get("llm_routing", [])
    routing_entries = [
        {"index": index, "provider": entry["provider"], "model": entry["model"],
         "name": str(entry.get("name") or f"Entry #{index + 1}"),
         **{key: entry.get(key) for key in ("enabled", "tasks", "temperature",
             "repetition_penalty", "max_tokens", "chat_template", "thinking", "thinking_budget", "extra_params")}}
        for index, entry in enumerate(routing if isinstance(routing, list) else [])
        if isinstance(entry, dict)
        and isinstance(entry.get("provider"), str) and isinstance(entry.get("model"), str)
    ]

    # Collect every model from every provider
    models: List[Dict[str, Any]] = []
    seen_names = set()

    provider_models = pm.list_all_models()
    for prov_name, prov_data in provider_models.items():
        for m in prov_data.get("models", []):
            name = m.get("name", "")
            if not name:
                continue
            # COPY the caps (otherwise we mutate the cache). Intrinsic ones come
            # from the substring match, the test result is hardware-exact
            # (provider::model), and the vision flag is pre-filled from what the
            # provider itself reports.
            caps = dict(get_model_capabilities(f"{prov_name}::{name}"))
            sd = suit_all.get(f"{prov_name}::{name}".lower())
            # "Has a result" is decided BEFORE the provider's own vision claim is
            # merged in — that claim is self-reported metadata, not something
            # anybody tested or documented here. Otherwise every vision model
            # would look documented and the short list would be pointless.
            rp = rp_all.get(f"{prov_name}::{name}".lower())
            has_result = (has_capability_info(caps) or caps.get("uncensored") is not None
                          or bool(sd) or bool(rp))
            # A vision answer in the last test beats the provider's claim
            # (DX10-02 lists qwen3.5-9b-heretic-v2-nvfp4 as text-only, yet it
            # answers images); a stored Yes/No beats both.
            vision_result = ((sd or {}).get("tested_suitability") or {}).get("vision")
            vision_rate = vision_result.get("rate") if isinstance(vision_result, dict) else None
            tested_vision = caps.get("vision") is None and bool(vision_rate)
            if tested_vision:
                caps["vision"] = True
            reported = {field: "provider" for field in prefill_from_provider(caps, m)}
            if tested_vision:
                reported["vision"] = "test"
            if sd:
                caps.update(sd)
            default_caps = all_caps.get("_default", {})
            has_custom = caps != default_caps

            models.append({
                "provider": prov_name,
                "name": name,
                "size_gb": m.get("size_gb", 0),
                "parameter_size": m.get("parameter_size", ""),
                "family": m.get("family", ""),
                "quantization": m.get("quantization", ""),
                "capabilities": caps,
                "reported": reported,
                "has_custom_entry": has_custom,
                "has_result": has_result,
                "listed": True,
                "rp_result": _rp_row(rp),
            })
            seen_names.add(name.lower())

    # A saved test result whose provider is disabled or offline is not in the
    # live lists above, yet it is a result — list it from the saved record.
    listed_keys = {f"{m['provider']}::{m['name']}".lower() for m in models}
    for key, sd in [*suit_all.items(), *((k, None) for k in rp_all if k not in suit_all)]:
        if key in listed_keys:
            continue
        rp = rp_all.get(key)
        full = str(((sd or {}).get("tested_suitability") or {}).get("model") or (rp or {}).get("model") or key)
        prov_name, _, name = full.partition("::")
        if not name:
            continue
        caps = dict(get_model_capabilities(full))
        vision_result = ((sd or {}).get("tested_suitability") or {}).get("vision")
        vision_rate = vision_result.get("rate") if isinstance(vision_result, dict) else None
        reported = {}
        if caps.get("vision") is None and vision_rate:
            caps["vision"] = True
            reported["vision"] = "test"
        caps.update(sd or {})
        models.append({
            "provider": prov_name, "name": name, "size_gb": 0, "parameter_size": "",
            "family": "", "quantization": "", "capabilities": caps, "reported": reported,
            "has_custom_entry": True, "has_result": True, "listed": False,
            "rp_result": _rp_row(rp),
        })
        seen_names.add(name.lower())

    # Sort by provider, then name
    models.sort(key=lambda x: (x["provider"], x["name"]))

    # Pattern entries with no model behind them
    unmatched: List[Dict[str, Any]] = []
    for pattern, caps in all_caps.items():
        if pattern.startswith("_"):
            continue
        # Does any model match this pattern?
        matched = any(pattern.lower() in name for name in seen_names)
        if not matched:
            unmatched.append({"pattern": pattern, "capabilities": caps})
    unmatched.sort(key=lambda x: x["pattern"])

    for row in models:
        row["refusals_48h"] = refusal_models.get(row["name"].lower(), {"count": 0, "recent": []})
    for row in unmatched:
        row["refusals_48h"] = refusal_models.get(row["pattern"].lower(), {"count": 0, "recent": []})

    # Fetch the default tool instruction
    try:
        from app.core.tool_formats import _DEFAULT_TOOL_INSTRUCTION
        default_instruction = _DEFAULT_TOOL_INSTRUCTION
    except Exception:
        default_instruction = ""

    from app.core.model_suitability import runnable_cases
    cases = runnable_cases()
    group_tasks = {group: sorted({case.get("task") for case in cases
                                 if case.get("group") == group and case.get("task")})
                   for group in ("tools", "helpers", "vision")}
    return {
        "models": models,
        "unmatched_entries": unmatched,
        "all_capabilities": {k: v for k, v in all_caps.items() if not k.startswith("_")},
        "routing_entries": routing_entries,
        "suitability_group_tasks": group_tasks,
        "default_tool_instruction": default_instruction,
    }


def _rp_row(record: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """What the model table shows of an RP result (the report loads the rest)."""
    if not record:
        return None
    return {key: record.get(key) for key in ("model", "date", "overall", "verdict", "caps", "length",
                                             "speed", "replies", "rejudged")} | {
        "dimensions": {name: {"score": d.get("score"), "n": d.get("n")}
                       for name, d in (record.get("dimensions") or {}).items()},
        "judge": {k: (record.get("judge") or {}).get(k) for k in ("provider", "model")}
                 | {"calibrated": bool(((record.get("judge") or {}).get("calibration") or {}).get("ok"))},
        "settings": {k: (record.get("settings") or {}).get(k)
                     for k in ("temperature", "top_p", "repetition_penalty", "max_tokens", "thinking_budget")},
    }


@router.post("/models/capabilities")
def update_model_capability(body: CapabilityUpdate) -> Dict[str, Any]:
    """Saves/updates the capabilities for a pattern.

    Merges with the existing fields (e.g. tested_* from the test script).
    """
    existing = get_model_capabilities(body.pattern)
    # Carry the tested_* fields over from the existing entry
    caps = {k: v for k, v in existing.items() if k.startswith("tested_")}
    caps["tool_calling"] = body.tool_calling
    caps["vision"] = body.vision
    caps["uncensored"] = body.uncensored
    caps["notes_de"] = body.notes_de
    if body.tool_instruction:
        caps["tool_instruction"] = body.tool_instruction
    save_model_capability(body.pattern, caps)
    return {"status": "success", "pattern": body.pattern, "capabilities": caps}


@router.delete("/models/capabilities")
def remove_model_capability(body: CapabilityDelete) -> Dict[str, Any]:
    """Deletes a capability entry."""
    deleted = delete_model_capability(body.pattern)
    return {"status": "success" if deleted else "not_found", "pattern": body.pattern}


def _build_models_html() -> str:
    return '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Model Capabilities</title>
<link rel="stylesheet" href="/static/admin/models.css">
</head>
<body>

<div class="toolbar">
    <strong style="color:#58a6ff;">Model Capabilities</strong>
    <input type="text" id="searchInput" placeholder="Search model..." oninput="filterTable()" />
    <select id="filterProvider" onchange="filterTable()"><option value="">All providers</option></select>
    <select id="filterStatus" onchange="filterTable()">
        <option value="results" selected>With result</option>
        <option value="">All models</option>
        <option value="unknown">Without result</option>
    </select>
    <button onclick="loadData()">Reload</button>
    <span class="count" id="countLabel"></span>
</div>

<div class="content">
    <nav class="models-tabs" role="tablist" aria-label="Model tests">
        <button type="button" role="tab" id="tabBtnTools" aria-controls="tabTools" aria-selected="true" onclick="modelsTab('tools')">Tools &amp; Helpers</button>
        <button type="button" role="tab" id="tabBtnRp" aria-controls="tabRp" aria-selected="false" onclick="modelsTab('rp')">Roleplay</button>
    </nav>
    <details class="models-box" id="suitQueueBox">
        <summary>Queue — <span id="suitQueueSummary">Queue empty</span><span id="suitInterruptedNotice" class="suit-interrupted-notice" hidden></span></summary>
        <div id="suitQueue"></div>
    </details>
    <div id="tabRp" class="tab-panel" role="tabpanel" aria-labelledby="tabBtnRp" hidden>
    <section class="models-box rp-setup" id="rpBox">
        <h2>Roleplay test</h2>
        <p class="info-text">Plays the game's real chat prompt (1:1, in person) with a small demo cast and checks what went wrong in play before:
        repetition loops, flat prose, a character that drops its personality, logic slips (absent people, night, things in hand, facts from the history)
        and discipline (tool syntax, leaked reasoning, speaking for the player, length). Code measures what code can measure; a separate judge model
        answers yes/no questions per case and must first pass calibration anchors. Results are kept apart from the tool test.</p>
        <div id="rpCases" class="rp-chips">Loading test cases…</div>
        <div class="rp-grid">
            <fieldset class="rp-card"><legend>Model under test</legend>
                <label>Provider<select id="rpProvider" onchange="rpLoadModels()"><option value="">Provider…</option></select></label>
                <label>Model<span id="rpModelPicker"></span></label>
                <label>Prefill from LLM entry<select id="rpPrefill" onchange="rpPrefill()"><option value="">Choose an entry…</option></select></label>
            </fieldset>
            <fieldset class="rp-card"><legend>Sampling</legend>
                <label>Temperature<input id="rpTemp" type="number" min="0" max="2" step="0.05" value="0.8"></label>
                <label>Top P<input id="rpTopP" type="number" min="0.01" max="1" step="0.01" placeholder="not sent"></label>
                <label>Repetition penalty<input id="rpPenalty" type="number" min="0" max="1.5" step="0.01" placeholder="not sent"></label>
                <label>Max tokens<input id="rpMaxTokens" type="number" min="0" max="200000" step="1" value="700"></label>
                <label>Thinking budget<select id="rpThinking"><option value="0">Off</option><option value="300">300</option><option value="600">600</option><option value="900">900</option><option value="1200">1200</option><option value="1500">1500</option><option value="2000">2000</option><option value="3000">3000</option></select></label>
            </fieldset>
            <fieldset class="rp-card"><legend>Judge</legend>
                <label>Provider<select id="rpJudgeProvider" onchange="rpLoadJudgeModels()"><option value="">Provider…</option></select></label>
                <label>Model<span id="rpJudgeModelPicker"></span></label>
                <p class="info-text">A strong instruction model, never the model under test. Runs at temperature 0 without thinking.</p>
            </fieldset>
            <fieldset class="rp-card"><legend>Advanced</legend>
                <label>Chat template<textarea id="rpChatTemplate" rows="1" placeholder="Provider default (Jinja, only if the model has none)"></textarea></label>
                <label>Extra params (JSON)<textarea id="rpExtraParams" rows="2" oninput="rpValidateExtra()">{}</textarea></label>
                <span id="rpExtraError" role="alert"></span>
                <label>Parallel requests<input id="rpConcurrency" type="number" min="1" step="1" value="3"></label>
            </fieldset>
        </div>
        <div class="suit-actions"><button class="btn btn-primary" id="rpStartBtn" onclick="rpStart()">Start roleplay test</button>
        <span id="rpStatus" role="status"></span></div>
    </section>
    <section class="models-box" id="rpResults">
        <div id="rpReport" class="rp-report" hidden></div>
        <h2>Roleplay results</h2>
        <p class="info-text">Click a row for the full report. Scores are 0–100; a model is suited at an overall score of 70 with every dimension at 55 or more.</p>
        <table class="rp-table">
            <thead><tr>
                <th class="sortable" onclick="rpSort('provider')">Provider<span class="sort-arrow" id="rpArrow-provider"></span></th>
                <th class="sortable" onclick="rpSort('name')">Model<span class="sort-arrow" id="rpArrow-name"></span></th>
                <th class="sortable" onclick="rpSort('overall')">Overall<span class="sort-arrow" id="rpArrow-overall"></span></th>
                <th class="sortable" onclick="rpSort('repetition')">Repetition<span class="sort-arrow" id="rpArrow-repetition"></span></th>
                <th class="sortable" onclick="rpSort('prose')">Prose<span class="sort-arrow" id="rpArrow-prose"></span></th>
                <th class="sortable" onclick="rpSort('character')">Character<span class="sort-arrow" id="rpArrow-character"></span></th>
                <th class="sortable" onclick="rpSort('logic')">Logic<span class="sort-arrow" id="rpArrow-logic"></span></th>
                <th class="sortable" onclick="rpSort('discipline')">Discipline<span class="sort-arrow" id="rpArrow-discipline"></span></th>
                <th class="sortable" onclick="rpSort('words')" title="Median words per reply">Words<span class="sort-arrow" id="rpArrow-words"></span></th>
                <th class="sortable" onclick="rpSort('latency')" title="Median seconds per reply">Latency<span class="sort-arrow" id="rpArrow-latency"></span></th>
                <th>Judge</th>
                <th>Settings</th>
                <th class="sortable" onclick="rpSort('date')">Date<span class="sort-arrow" id="rpArrow-date"></span></th>
            </tr></thead>
            <tbody id="rpBody"></tbody>
        </table>
    </section>
    </div>
    <div id="tabTools" class="tab-panel" role="tabpanel" aria-labelledby="tabBtnTools">
    <section class="models-box" id="suitBox">
        <h2>Test setup</h2>
        <p class="info-text">Tests tools, helpers, vision and speed with curated and reviewed game prompts. Tests run in the background, FIFO per provider; different providers run in parallel.</p>
        <div id="suitCases" class="info-text">Loading test cases…</div>
        <div class="suit-fields">
            <label>Provider<select id="suitProvider" onchange="suitLoadModels()"><option value="">Provider…</option></select></label>
            <label>Model<span id="suitModelPicker"></span></label>
            <label>Prefill from LLM entry<select id="suitPrefill" onchange="suitPrefill()"><option value="">Choose an entry…</option></select></label>
            <div class="suit-group-row"><strong>Tools</strong>
                <label>Temperature<input id="suitTempTools" type="number" min="0" max="2" step="0.1" value="0.1"></label>
                <label>Thinking up to<select id="suitThinkingMaxTools"><option value="0">Off</option><option value="300">300</option><option value="600">600</option><option value="900">900</option><option value="1200">1200</option><option value="1500">1500</option><option value="1800">1800</option><option value="2100">2100</option><option value="2400">2400</option><option value="2700">2700</option><option value="3000">3000</option></select></label>
            </div>
            <div class="suit-group-row"><strong>Helpers</strong>
                <label>Temperature<input id="suitTempHelpers" type="number" min="0" max="2" step="0.1" value="0.5"></label>
                <label>Thinking up to<select id="suitThinkingMaxHelpers"><option value="0">Off</option><option value="300">300</option><option value="600">600</option><option value="900">900</option><option value="1200">1200</option><option value="1500">1500</option><option value="1800">1800</option><option value="2100">2100</option><option value="2400">2400</option><option value="2700">2700</option><option value="3000">3000</option></select></label>
            </div>
            <div class="suit-group-row"><strong>Vision</strong>
                <label>Temperature<input id="suitTempVision" type="number" min="0" max="2" step="0.1" value="0.3"></label>
                <label>Thinking up to<select id="suitThinkingMaxVision"><option value="0">Off</option><option value="300">300</option><option value="600">600</option><option value="900">900</option><option value="1200">1200</option><option value="1500">1500</option><option value="1800">1800</option><option value="2100">2100</option><option value="2400">2400</option><option value="2700">2700</option><option value="3000">3000</option></select></label>
            </div>
            <label>Repetition penalty<input id="suitPenalty" type="number" min="0" max="1.5" step="0.01" placeholder="not sent"></label>
            <label>Max tokens<input id="suitMaxTokens" type="number" min="0" max="200000" step="1" value="900"></label>
            <label>Chat template<textarea id="suitChatTemplate" rows="1" placeholder="Provider default (Jinja, only if the model has none)"></textarea></label>
            <label>Parallel requests<input id="suitConcurrency" type="number" min="1" step="1" value="3"></label>
        </div>
        <label for="suitExtraParams">Extra params (JSON)</label>
        <textarea id="suitExtraParams" aria-label="Extra params (JSON object)" oninput="suitValidateExtraParams()">{}</textarea>
        <button class="btn" type="button" onclick="suitVeniceTemplate()">Venice template</button>
        <span id="suitExtraError" role="alert"></span>
        <div class="suit-actions"><button class="btn btn-primary" id="suitStartBtn" onclick="suitStart()">Start test</button>
        <span id="suitStatus" role="status"></span></div>
    </section>
    <section class="models-box" id="suitResults">
    <h2>Results</h2>
    <div id="suitDetail" hidden>
        <div id="suitDetailStatus" role="status"></div>
        <div id="suitSettings"></div>
        <div id="suitProgress"></div>
    </div>
    <button type="button" class="btn" onclick="suitDeleteOld(this)">Delete old test results</button>

    <h2>Available models</h2>
    <p class="info-text">Click Tool/Vision to toggle the value. Edit notes directly — saved automatically.
    By default only models with a result are listed: a suitability test, or a capability someone filled in.
    Switch the filter to "All models" to document a newly discovered one.</p>
    <table>
        <thead>
            <tr>
                <th class="sortable" data-sort="provider" onclick="sortBy('provider')">Provider<span class="sort-arrow" id="arrow-provider"></span></th>
                <th class="sortable" data-sort="name" onclick="sortBy('name')">Model<span class="sort-arrow" id="arrow-name"></span></th>
                <th class="sortable" data-sort="size_gb" onclick="sortBy('size_gb')">Size<span class="sort-arrow" id="arrow-size_gb"></span></th>
                <th class="sortable" data-sort="tool_calling" onclick="sortBy('tool_calling')">Tool-Calling<span class="sort-arrow" id="arrow-tool_calling"></span></th>
                <th class="sortable" data-sort="vision" onclick="sortBy('vision')">Vision<span class="sort-arrow" id="arrow-vision"></span></th>
                <th class="sortable" data-sort="uncensored" onclick="sortBy('uncensored')">Uncensored<span class="sort-arrow" id="arrow-uncensored"></span></th>
                <th class="sortable" data-sort="tested_score" onclick="sortBy('tested_score')">Test<span class="sort-arrow" id="arrow-tested_score"></span></th>
                <th class="sortable" data-sort="speed" onclick="sortBy('speed')" title="Projected non-RP time per thought turn, from the last test">Speed<span class="sort-arrow" id="arrow-speed"></span></th>
                <th class="sortable" data-sort="notes_de" onclick="sortBy('notes_de')">Notes<span class="sort-arrow" id="arrow-notes_de"></span></th>
                <th></th>
            </tr>
        </thead>
        <tbody id="modelsBody"></tbody>
    </table>

    <h2 id="unmatchedHeader" style="display:none;">Pattern entries (no active model)</h2>
    <p id="unmatchedInfo" class="info-text" style="display:none;">These entries match no currently available model, but may still apply as a substring pattern to a future one.</p>
    <table id="unmatchedTable" style="display:none;">
        <thead>
            <tr>
                <th>Pattern</th>
                <th>Tool calling</th>
                <th>Vision</th>
                <th>Uncensored</th>
                <th>Notes</th>
                <th></th>
            </tr>
        </thead>
        <tbody id="unmatchedBody"></tbody>
    </table>

    <div class="add-pattern-row" style="margin-top:16px;">
        <h2>Add new pattern</h2>
        <div style="display:flex; gap:8px; align-items:center; margin-top:8px;">
            <input type="text" id="newPattern" placeholder="e.g. gemma, llava, gpt-4o" />
            <button class="btn btn-primary" onclick="addPattern()">Add</button>
        </div>
    </div>

    </section>
    </div>
</div>

<script src="/static/admin/model-combobox.js"></script>
<script src="/static/admin/models.js"></script>
<script src="/static/admin/models-rp.js"></script>
<div id="suitApplyDialog" class="suit-apply-dialog" role="dialog" aria-modal="true" aria-label="Apply to game" hidden></div>
</body>
</html>'''
