"""Admin Routes — Model Capabilities Verwaltung"""
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
    """Admin-Seite fuer Model Capabilities."""
    return HTMLResponse(content=_build_models_html())


@router.get("/models/data")
def model_capabilities_data() -> Dict[str, Any]:
    """JSON-API: Alle verfuegbaren Modelle + Capabilities."""
    pm = get_provider_manager()
    all_caps = get_all_capabilities()
    suit_all = get_all_suitability()  # Key: "provider::model" (lowercased)

    # Alle Modelle von allen Providern sammeln
    models: List[Dict[str, Any]] = []
    seen_names = set()

    provider_models = pm.list_all_models()
    for prov_name, prov_data in provider_models.items():
        for m in prov_data.get("models", []):
            name = m.get("name", "")
            if not name:
                continue
            # Caps KOPIEREN (sonst Cache-Mutation). Intrinsisch per Substring,
            # Vision-Flag vorbelegen, Test-Ergebnis HW-genau (provider::model).
            caps = dict(get_model_capabilities(f"{prov_name}::{name}"))
            if caps.get("vision") is None and m.get("vision"):
                caps["vision"] = True
            sd = suit_all.get(f"{prov_name}::{name}".lower())
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
            })
            seen_names.add(name.lower())

    # Sortieren: Provider, dann Name
    models.sort(key=lambda x: (x["provider"], x["name"]))

    # Pattern-Eintraege ohne zugeordnetes Modell
    unmatched: List[Dict[str, Any]] = []
    for pattern, caps in all_caps.items():
        if pattern.startswith("_"):
            continue
        # Pruefen ob irgendein Modell dieses Pattern matched
        matched = any(pattern.lower() in name for name in seen_names)
        if not matched:
            unmatched.append({"pattern": pattern, "capabilities": caps})
    unmatched.sort(key=lambda x: x["pattern"])

    # Default Tool Instruction holen
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
    """Speichert/aktualisiert Capabilities fuer ein Pattern.

    Merged mit bestehenden Feldern (z.B. tested_* vom Test-Script).
    """
    existing = get_model_capabilities(body.pattern)
    # tested_* Felder aus bestehendem Eintrag uebernehmen
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
    """Loescht einen Capability-Eintrag."""
    deleted = delete_model_capability(body.pattern)
    return {"status": "success" if deleted else "not_found", "pattern": body.pattern}


def _build_models_html() -> str:
    return '''<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Model Capabilities</title>
<link rel="stylesheet" href="/static/admin/models.css">
</head>
<body>

<div class="toolbar">
    <strong style="color:#58a6ff;">Model Capabilities</strong>
    <input type="text" id="searchInput" placeholder="Modell suchen..." oninput="filterTable()" />
    <select id="filterProvider" onchange="filterTable()"><option value="">Alle Provider</option></select>
    <select id="filterStatus" onchange="filterTable()">
        <option value="">Alle</option>
        <option value="documented">Dokumentiert</option>
        <option value="unknown">Unbekannt</option>
    </select>
    <button onclick="loadData()">Neu laden</button>
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
            <button class="btn btn-primary" id="suitStartBtn" onclick="suitStart()">Test starten</button>
            <span id="suitStatus" class="info-text"></span>
        </div>
        <div id="suitJobs" style="margin-top:10px;"></div>
        <div id="suitProgress" style="margin-top:10px;"></div>
    </div>

    <h2>Verfuegbare Modelle</h2>
    <p class="info-text">Click Tool/Vision to toggle the value. Edit notes directly — saved automatically.</p>
    <table>
        <thead>
            <tr>
                <th class="sortable" data-sort="provider" onclick="sortBy('provider')">Provider<span class="sort-arrow" id="arrow-provider"></span></th>
                <th class="sortable" data-sort="name" onclick="sortBy('name')">Modell<span class="sort-arrow" id="arrow-name"></span></th>
                <th class="sortable" data-sort="size_gb" onclick="sortBy('size_gb')">Groesse<span class="sort-arrow" id="arrow-size_gb"></span></th>
                <th class="sortable" data-sort="tool_calling" onclick="sortBy('tool_calling')">Tool-Calling<span class="sort-arrow" id="arrow-tool_calling"></span></th>
                <th class="sortable" data-sort="vision" onclick="sortBy('vision')">Vision<span class="sort-arrow" id="arrow-vision"></span></th>
                <th class="sortable" data-sort="tested_score" onclick="sortBy('tested_score')">Test<span class="sort-arrow" id="arrow-tested_score"></span></th>
                <th class="sortable" data-sort="notes_de" onclick="sortBy('notes_de')">Notizen<span class="sort-arrow" id="arrow-notes_de"></span></th>
                <th></th>
            </tr>
        </thead>
        <tbody id="modelsBody"></tbody>
    </table>

    <h2 id="unmatchedHeader" style="display:none;">Pattern-Eintraege (kein aktives Modell)</h2>
    <p id="unmatchedInfo" class="info-text" style="display:none;">Diese Eintraege matchen kein aktuell verfuegbares Modell — koennen aber als Substring-Pattern fuer zukuenftige Modelle relevant sein.</p>
    <table id="unmatchedTable" style="display:none;">
        <thead>
            <tr>
                <th>Pattern</th>
                <th>Tool-Calling</th>
                <th>Vision</th>
                <th>Notizen</th>
                <th></th>
            </tr>
        </thead>
        <tbody id="unmatchedBody"></tbody>
    </table>

    <div class="add-pattern-row" style="margin-top:16px;">
        <h2>Neues Pattern hinzufuegen</h2>
        <div style="display:flex; gap:8px; align-items:center; margin-top:8px;">
            <input type="text" id="newPattern" placeholder="z.B. gemma, llava, gpt-4o" />
            <button class="btn btn-primary" onclick="addPattern()">Hinzufuegen</button>
        </div>
    </div>

</div>

<script src="/static/admin/models.js"></script>
</body>
</html>'''
