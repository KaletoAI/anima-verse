"""Admin routes — model capabilities management."""
from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from typing import Any, Dict, List, Optional

from app.core.model_capabilities import (
    get_all_capabilities,
    get_model_capabilities,
    get_all_suitability,
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
    pm = get_provider_manager()
    all_caps = get_all_capabilities()
    suit_all = get_all_suitability()  # Key: "provider::model" (lowercased)
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
            has_result = has_capability_info(caps) or bool(sd)
            # A vision answer in the last test beats the provider's claim
            # (DX10-02 lists qwen3.5-9b-heretic-v2-nvfp4 as text-only, yet it
            # answers images); a stored Yes/No beats both.
            vision_rate = (((sd or {}).get("tested_suitability") or {}).get("vision") or {}).get("rate")
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
            })
            seen_names.add(name.lower())

    # A saved test result whose provider is disabled or offline is not in the
    # live lists above, yet it is a result — list it from the saved record.
    listed_keys = {f"{m['provider']}::{m['name']}".lower() for m in models}
    for key, sd in suit_all.items():
        if key in listed_keys:
            continue
        full = str(((sd or {}).get("tested_suitability") or {}).get("model") or key)
        prov_name, _, name = full.partition("::")
        if not name:
            continue
        caps = dict(get_model_capabilities(full))
        vision_rate = (((sd.get("tested_suitability") or {}).get("vision")) or {}).get("rate")
        reported = {}
        if caps.get("vision") is None and vision_rate:
            caps["vision"] = True
            reported["vision"] = "test"
        caps.update(sd)
        models.append({
            "provider": prov_name, "name": name, "size_gb": 0, "parameter_size": "",
            "family": "", "quantization": "", "capabilities": caps, "reported": reported,
            "has_custom_entry": True, "has_result": True, "listed": False,
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
                <label>Thinking<select id="suitThinkingTools" onchange="suitThinkingChanged('Tools')"><option value="off">Off</option><option value="on">On</option></select></label>
                <label>Budget<input id="suitBudgetTools" type="number" min="1" max="32000" step="1" placeholder="unlimited" disabled></label>
            </div>
            <div class="suit-group-row"><strong>Helpers</strong>
                <label>Temperature<input id="suitTempHelpers" type="number" min="0" max="2" step="0.1" value="0.5"></label>
                <label>Thinking<select id="suitThinkingHelpers" onchange="suitThinkingChanged('Helpers')"><option value="off">Off</option><option value="on">On</option></select></label>
                <label>Budget<input id="suitBudgetHelpers" type="number" min="1" max="32000" step="1" placeholder="unlimited" disabled></label>
            </div>
            <div class="suit-group-row"><strong>Vision</strong>
                <label>Temperature<input id="suitTempVision" type="number" min="0" max="2" step="0.1" value="0.3"></label>
                <label>Thinking<select id="suitThinkingVision" onchange="suitThinkingChanged('Vision')"><option value="off">Off</option><option value="on">On</option></select></label>
                <label>Budget<input id="suitBudgetVision" type="number" min="1" max="32000" step="1" placeholder="unlimited" disabled></label>
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
    <details class="models-box" id="suitQueueBox">
        <summary>Queue — <span id="suitQueueSummary">Queue empty</span><span id="suitInterruptedNotice" class="suit-interrupted-notice" hidden></span></summary>
        <div id="suitQueue"></div>
    </details>
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

<script src="/static/admin/model-combobox.js"></script>
<script src="/static/admin/models.js"></script>
</body>
</html>'''
