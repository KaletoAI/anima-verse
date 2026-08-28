"""Admin routes — model capabilities management."""
from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from typing import Any, Dict, List, Optional

from app.core.model_capabilities import (
    get_all_capabilities,
    get_model_capabilities,
    get_all_suitability,
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
    """JSON API: every available model plus its capabilities."""
    pm = get_provider_manager()
    all_caps = get_all_capabilities()
    suit_all = get_all_suitability()  # Key: "provider::model" (lowercased)

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
            if caps.get("vision") is None and m.get("vision"):
                caps["vision"] = True
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
                "has_custom_entry": has_custom,
                "has_result": has_result,
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

    return {
        "models": models,
        "unmatched_entries": unmatched,
        "all_capabilities": {k: v for k, v in all_caps.items() if not k.startswith("_")},
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
    <div id="suitBox" style="border:1px solid #30363d; border-radius:8px; padding:12px; margin-bottom:18px; background:#0d1117;">
        <h2 style="margin:0 0 6px;">🧪 Tool / Helper Suitability Test</h2>
        <p class="info-text" style="margin:0 0 8px;">Replays REAL logged prompts (logs/llm_calls.jsonl) against one model and validates with production-style parsers — real tool-call format, JSON schema, abstain (no over-eager tools), consistency repeats. <b>Runs in the background</b> — you can leave the page; the result is saved to the table below.</p>
        <div id="suitCases" class="info-text" style="margin-bottom:8px;">Loading test cases…</div>
        <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
            <select id="suitProvider" onchange="suitLoadModels()"><option value="">Provider…</option></select>
            <input type="text" id="suitSearch" placeholder="Modell suchen…" style="min-width:160px;" oninput="suitRenderModels()" />
            <select id="suitModel" style="min-width:240px;" onchange="suitOnModelChange()"><option value="">Model…</option></select>
            <span id="suitModelCount" class="info-text"></span>
            <button class="btn btn-primary" id="suitStartBtn" onclick="suitStart()">Start test</button>
            <span id="suitStatus" class="info-text"></span>
        </div>
        <div id="suitJobs" style="margin-top:10px;"></div>
        <div id="suitProgress" style="margin-top:10px;"></div>
    </div>

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

</div>

<script src="/static/admin/models.js"></script>
</body>
</html>'''
