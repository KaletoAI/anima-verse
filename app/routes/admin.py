"""Admin Routes — Model Capabilities Verwaltung"""
from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from typing import Any, Dict, List, Optional

from app.core.model_capabilities import (
    get_all_capabilities,
    get_model_capabilities,
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

    # Alle Modelle von allen Providern sammeln
    models: List[Dict[str, Any]] = []
    seen_names = set()

    provider_models = pm.list_all_models()
    for prov_name, prov_data in provider_models.items():
        for m in prov_data.get("models", []):
            name = m.get("name", "")
            if not name:
                continue
            caps = get_model_capabilities(f"{prov_name}::{name}")
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
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #0d1117; color: #c9d1d9; }

.toolbar {
    position: sticky; top: 0; z-index: 100;
    background: #161b22; border-bottom: 1px solid #30363d;
    padding: 10px 16px; display: flex; gap: 10px; align-items: center; flex-wrap: wrap;
}
.toolbar input {
    background: #0d1117; color: #c9d1d9; border: 1px solid #30363d;
    padding: 6px 10px; border-radius: 6px; font-size: 13px; min-width: 220px;
}
.toolbar select {
    background: #0d1117; color: #c9d1d9; border: 1px solid #30363d;
    padding: 6px 10px; border-radius: 6px; font-size: 13px; min-width: 140px;
}
.toolbar .count { color: #8b949e; font-size: 13px; margin-left: auto; }
.toolbar button, .btn {
    background: #21262d; color: #c9d1d9; border: 1px solid #30363d;
    padding: 6px 12px; border-radius: 6px; cursor: pointer; font-size: 13px;
}
.toolbar button:hover, .btn:hover { background: #30363d; }
.btn-primary { background: #238636; border-color: #2ea043; }
.btn-primary:hover { background: #2ea043; }
.btn-danger { background: #da3633; border-color: #f85149; }
.btn-danger:hover { background: #f85149; }

.content { padding: 16px; }
h2 { font-size: 16px; margin: 16px 0 8px 0; color: #8b949e; }
h2:first-child { margin-top: 0; }

table {
    width: 100%; border-collapse: collapse; font-size: 13px;
}
th, td {
    padding: 8px 10px; text-align: left; border-bottom: 1px solid #21262d;
}
th {
    background: #161b22; color: #8b949e; font-size: 11px;
    text-transform: uppercase; letter-spacing: 0.5px; position: sticky; top: 42px;
}
th.sortable {
    cursor: pointer; user-select: none;
}
th.sortable:hover {
    color: #c9d1d9;
}
th .sort-arrow {
    display: inline-block; margin-left: 4px; font-size: 10px; color: #58a6ff;
}
tr:hover { background: #161b22; }

.cap-yes { color: #3fb950; font-weight: 600; }
.cap-no { color: #f85149; font-weight: 600; }
.cap-unknown { color: #8b949e; font-style: italic; }
.row-documented { }
.row-unknown { opacity: 0.6; }

.notes-input {
    background: #0d1117; color: #c9d1d9; border: 1px solid #30363d;
    padding: 4px 6px; border-radius: 4px; font-size: 12px; width: 100%; min-width: 200px;
}
.notes-input:focus { border-color: #58a6ff; outline: none; }

.cap-toggle {
    cursor: pointer; padding: 2px 8px; border-radius: 4px;
    display: inline-block; min-width: 40px; text-align: center;
    border: 1px solid transparent; user-select: none;
}
.cap-toggle:hover { border-color: #30363d; background: #21262d; }

.save-indicator {
    display: inline-block; color: #3fb950; font-size: 11px;
    margin-left: 6px; opacity: 0; transition: opacity 0.3s;
}
.save-indicator.show { opacity: 1; }

.badge-provider {
    display: inline-block; padding: 1px 6px; border-radius: 10px;
    font-size: 11px; background: #1f6feb33; color: #58a6ff;
}
.badge-size {
    color: #8b949e; font-size: 11px;
}

.add-pattern-row {
    padding: 12px 0;
}
.add-pattern-row input {
    background: #0d1117; color: #c9d1d9; border: 1px solid #30363d;
    padding: 6px 10px; border-radius: 6px; font-size: 13px; width: 250px;
}

.info-text { color: #8b949e; font-size: 12px; margin-bottom: 12px; }

.instruction-row td { padding: 4px 10px 12px 10px; border-bottom: 1px solid #30363d; }
.instruction-row { display: none; }
.instruction-row.open { display: table-row; }
.instruction-textarea {
    background: #0d1117; color: #c9d1d9; border: 1px solid #30363d;
    padding: 6px 8px; border-radius: 4px; font-size: 12px; font-family: monospace;
    width: 100%; min-height: 80px; resize: vertical;
}
.instruction-textarea:focus { border-color: #58a6ff; outline: none; }
.btn-instr {
    background: none; border: none; color: #8b949e; cursor: pointer;
    font-size: 14px; padding: 2px 4px; line-height: 1;
}
.btn-instr:hover { color: #58a6ff; }
.btn-instr.has-instruction { color: #d29922; }
.btn-insert-default {
    background: #21262d; color: #8b949e; border: 1px solid #30363d;
    padding: 2px 8px; border-radius: 4px; font-size: 11px; cursor: pointer;
}
.btn-insert-default:hover { color: #58a6ff; border-color: #58a6ff; }

.test-badge {
    display: inline-block; padding: 1px 6px; border-radius: 4px;
    font-size: 11px; font-weight: 600; white-space: nowrap;
}
.test-badge.ok { background: #23863633; color: #3fb950; }
.test-badge.warn { background: #d2992233; color: #d29922; }
.test-badge.fail { background: #da363333; color: #f85149; }
.test-badge.none { color: #8b949e; font-weight: normal; }
.test-date { color: #484f58; font-size: 10px; display: block; margin-top: 1px; }
.test-detail { color: #8b949e; font-size: 10px; cursor: help; }
</style>
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
            <select id="suitModel" style="min-width:240px;" onchange="suitOnModelChange()"><option value="">Model…</option></select>
            <button class="btn btn-primary" id="suitStartBtn" onclick="suitStart()">Test starten</button>
            <span id="suitStatus" class="info-text"></span>
        </div>
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

<script>
let allModels = [];
let unmatchedEntries = [];
let defaultToolInstruction = '';
let sortField = '';
let sortDir = 0; // 0=none, 1=asc, -1=desc

function insertDefault(btn) {
    const td = btn.closest('td');
    const ta = td ? td.querySelector('.instruction-textarea') : null;
    if (ta && defaultToolInstruction) {
        ta.value = defaultToolInstruction;
        ta.dispatchEvent(new Event('change'));
    }
}

async function loadData() {
    const resp = await fetch('/admin/models/data');
    const data = await resp.json();
    allModels = data.models || [];
    unmatchedEntries = data.unmatched_entries || [];
    defaultToolInstruction = data.default_tool_instruction || '';

    // Provider-Filter befuellen
    const providers = [...new Set(allModels.map(m => m.provider))].sort();
    const provSel = document.getElementById('filterProvider');
    provSel.innerHTML = '<option value="">Alle Provider</option>';
    providers.forEach(p => { provSel.add(new Option(p, p)); });

    renderAll();
}

function filterTable() {
    renderAll();
}

function sortBy(field) {
    if (sortField === field) {
        // Gleiche Spalte: asc -> desc -> kein Sort
        if (sortDir === 1) sortDir = -1;
        else if (sortDir === -1) { sortDir = 0; sortField = ''; }
        else sortDir = 1;
    } else {
        sortField = field;
        sortDir = 1;
    }
    updateSortArrows();
    renderAll();
}

function updateSortArrows() {
    document.querySelectorAll('.sort-arrow').forEach(el => el.textContent = '');
    if (sortField && sortDir !== 0) {
        const arrow = document.getElementById('arrow-' + sortField);
        if (arrow) arrow.textContent = sortDir === 1 ? ' ▲' : ' ▼';
    }
}

function getSortValue(m, field) {
    if (field === 'tool_calling' || field === 'vision') {
        const v = (m.capabilities || {})[field];
        if (v === true) return 2;
        if (v === false) return 1;
        return 0; // null/unknown
    }
    if (field === 'tested_score') {
        const s = (m.capabilities || {}).tested_score || '';
        const parts = s.split('/');
        return parts.length === 2 ? parseInt(parts[0]) || 0 : -1;
    }
    if (field === 'notes_de') return ((m.capabilities || {}).notes_de || '').toLowerCase();
    if (field === 'size_gb') return m.size_gb || 0;
    return (m[field] || '').toLowerCase();
}

function renderAll() {
    const search = document.getElementById('searchInput').value.toLowerCase();
    const provFilter = document.getElementById('filterProvider').value;
    const statusFilter = document.getElementById('filterStatus').value;

    // Modelle filtern
    let filtered = allModels.slice();
    if (search) filtered = filtered.filter(m => m.name.toLowerCase().includes(search) || m.provider.toLowerCase().includes(search));
    if (provFilter) filtered = filtered.filter(m => m.provider === provFilter);
    if (statusFilter === 'documented') filtered = filtered.filter(m => m.has_custom_entry);
    if (statusFilter === 'unknown') filtered = filtered.filter(m => !m.has_custom_entry);

    // Sortieren
    if (sortField && sortDir !== 0) {
        filtered.sort((a, b) => {
            const va = getSortValue(a, sortField);
            const vb = getSortValue(b, sortField);
            let cmp = 0;
            if (typeof va === 'number' && typeof vb === 'number') cmp = va - vb;
            else if (typeof va === 'string' && typeof vb === 'string') cmp = va.localeCompare(vb);
            else cmp = String(va).localeCompare(String(vb));
            return cmp * sortDir;
        });
    }

    renderModels(filtered);
    renderUnmatched(unmatchedEntries);
    document.getElementById('countLabel').textContent = filtered.length + ' / ' + allModels.length + ' Modelle';
}

function renderModels(models) {
    const body = document.getElementById('modelsBody');
    body.innerHTML = '';
    models.forEach(m => {
        const row = document.createElement('tr');
        row.className = m.has_custom_entry ? 'row-documented' : 'row-unknown';
        const caps = m.capabilities || {};
        const sizeStr = m.size_gb ? m.size_gb + ' GB' : '';
        const paramStr = m.parameter_size ? ' (' + esc(m.parameter_size) + ')' : '';
        const hasInstr = caps.tool_instruction ? ' has-instruction' : '';
        const instrId = 'instr-' + cssId(m.name);

        row.innerHTML = `
            <td><span class="badge-provider">${esc(m.provider)}</span></td>
            <td><strong>${esc(m.name)}</strong></td>
            <td><span class="badge-size">${sizeStr}${paramStr}</span></td>
            <td>${capToggle(m.name, 'tool_calling', caps.tool_calling)}</td>
            <td>${capToggle(m.name, 'vision', caps.vision)}</td>
            <td>${testBadge(caps)}</td>
            <td><input class="notes-input" data-model="${esc(m.name)}" value="${esc(caps.notes_de || '')}"
                onchange="saveRow(this)" onblur="saveRow(this)" /></td>
            <td>
                <button class="btn-instr${hasInstr}" title="Tool Instruction" onclick="toggleInstruction('${instrId}')">&#9881;</button>
                <span class="save-indicator" id="save-${cssId(m.name)}">saved</span>
            </td>
        `;
        body.appendChild(row);

        // Aufklappbare Detail-Zeile fuer tool_instruction
        const detailRow = document.createElement('tr');
        detailRow.className = 'instruction-row';
        detailRow.id = instrId;
        detailRow.innerHTML = `
            <td colspan="8">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
                    <label style="font-size:11px;color:#8b949e;">Tool Instruction (leer = Default):</label>
                    <button class="btn-insert-default" onclick="insertDefault(this)" title="Default-Text einfuegen">Default einfuegen</button>
                </div>
                <textarea class="instruction-textarea" data-model="${esc(m.name)}"
                    onchange="saveRow(this)" onblur="saveRow(this)"
                    placeholder="Custom tool instruction fuer dieses Modell...">${esc(caps.tool_instruction || '')}</textarea>
            </td>
        `;
        body.appendChild(detailRow);
    });
}

function toggleInstruction(instrId) {
    const row = document.getElementById(instrId);
    if (row) row.classList.toggle('open');
}

function renderUnmatched(entries) {
    const show = entries.length > 0;
    document.getElementById('unmatchedHeader').style.display = show ? '' : 'none';
    document.getElementById('unmatchedInfo').style.display = show ? '' : 'none';
    document.getElementById('unmatchedTable').style.display = show ? '' : 'none';

    const body = document.getElementById('unmatchedBody');
    body.innerHTML = '';
    entries.forEach(e => {
        const caps = e.capabilities || {};
        const hasInstr = caps.tool_instruction ? ' has-instruction' : '';
        const instrId = 'instr-' + cssId(e.pattern);
        const row = document.createElement('tr');
        row.innerHTML = `
            <td><strong>${esc(e.pattern)}</strong></td>
            <td>${capToggle(e.pattern, 'tool_calling', caps.tool_calling)}</td>
            <td>${capToggle(e.pattern, 'vision', caps.vision)}</td>
            <td><input class="notes-input" data-model="${esc(e.pattern)}" value="${esc(caps.notes_de || '')}"
                onchange="saveRow(this)" onblur="saveRow(this)" /></td>
            <td>
                <button class="btn-instr${hasInstr}" title="Tool Instruction" onclick="toggleInstruction('${instrId}')">&#9881;</button>
                <span class="save-indicator" id="save-${cssId(e.pattern)}">saved</span>
                <button class="btn btn-danger" style="font-size:11px;padding:2px 8px;margin-left:4px;" onclick="deletePattern('${escJs(e.pattern)}')">X</button>
            </td>
        `;
        body.appendChild(row);

        const detailRow = document.createElement('tr');
        detailRow.className = 'instruction-row';
        detailRow.id = instrId;
        detailRow.innerHTML = `
            <td colspan="5">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
                    <label style="font-size:11px;color:#8b949e;">Tool Instruction (leer = Default):</label>
                    <button class="btn-insert-default" onclick="insertDefault(this)" title="Default-Text einfuegen">Default einfuegen</button>
                </div>
                <textarea class="instruction-textarea" data-model="${esc(e.pattern)}"
                    onchange="saveRow(this)" onblur="saveRow(this)"
                    placeholder="Custom tool instruction fuer dieses Modell...">${esc(caps.tool_instruction || '')}</textarea>
            </td>
        `;
        body.appendChild(detailRow);
    });
}

function testBadge(caps) {
    const score = caps.tested_score;
    if (!score) return '<span class="test-badge none">-</span>';

    const parts = score.split('/');
    const ok = parseInt(parts[0]) || 0;
    const total = parseInt(parts[1]) || 0;
    const hall = caps.tested_hallucinations || 0;
    const date = caps.tested_date || '';
    const visionResp = caps.tested_vision_responses || {};
    const bestFmt = caps.tested_best_format || '';
    const toolScore = caps.tested_tool_score || '';
    const helperScore = caps.tested_helper_score || '';
    const suit = caps.tested_suitability || null;
    const verdict = caps.tested_verdict || null;

    let cls = 'ok';
    if (ok === 0) cls = 'fail';
    else if (hall > 0) cls = 'warn';
    // Verdict dominiert: ein Modell, das den strengen Tool-Test nicht besteht,
    // wird NICHT gruen markiert, auch wenn der Rohscore hoch ist.
    if (verdict && verdict.tool === false) cls = (hall > 0 ? 'fail' : 'warn');

    let tooltip = 'Score: ' + score;
    if (verdict) tooltip += '\\nVerdict tool: ' + (verdict.tool ? 'SUITABLE' : 'not suitable') +
        ' / helper: ' + (verdict.helper ? 'suitable' : 'not suitable');
    if (toolScore) tooltip += '\\nTool: ' + toolScore;
    if (helperScore) tooltip += '\\nHelper: ' + helperScore;
    if (hall > 0) tooltip += '\\n' + hall + ' mit Halluzination';
    if (bestFmt) tooltip += '\\nBestes Format: ' + bestFmt;
    if (visionResp.red) tooltip += '\\nVision red: ' + visionResp.red;
    if (visionResp.blue) tooltip += '\\nVision blue: ' + visionResp.blue;
    if (date) tooltip += '\\nGetestet: ' + date;
    if (suit && Array.isArray(suit.checks)) {
        tooltip += '\\n———';
        suit.checks.forEach(function(c){
            const mark = c.ok ? '\\u2713' : (c.hallucinated ? '!' : '\\u2717');
            tooltip += '\\n' + mark + ' ' + c.label + ' \\u2014 ' + (c.detail || '');
        });
    }

    let html = '<span class="test-badge ' + cls + '" title="' + esc(tooltip) + '">' + esc(score);
    if (hall > 0) html += ' <span class="test-detail">(' + hall + ' warn)</span>';
    html += '</span>';
    if (verdict) {
        const tcol = verdict.tool ? '#3fb950' : '#f85149';
        const tlab = verdict.tool ? 'TOOL \\u2713' : 'TOOL \\u2717';
        html += '<span class="test-date" style="color:' + tcol + ';">' + tlab + '</span>';
    }
    if (toolScore || helperScore) html += '<span class="test-date">T ' + esc(toolScore) + ' \\u00b7 H ' + esc(helperScore) + '</span>';
    if (date) html += '<span class="test-date">' + esc(date) + '</span>';
    return html;
}

function capToggle(modelName, field, value) {
    let cls, label;
    if (value === true) { cls = 'cap-yes'; label = 'Ja'; }
    else if (value === false) { cls = 'cap-no'; label = 'Nein'; }
    else { cls = 'cap-unknown'; label = '?'; }
    return `<span class="cap-toggle ${cls}" data-model="${esc(modelName)}" data-field="${field}" data-value="${value}" onclick="toggleCap(this)">${label}</span>`;
}

function toggleCap(el) {
    const current = el.getAttribute('data-value');
    let next;
    if (current === 'true') next = false;
    else if (current === 'false') next = null;
    else next = true;

    el.setAttribute('data-value', String(next));
    if (next === true) { el.className = 'cap-toggle cap-yes'; el.textContent = 'Ja'; }
    else if (next === false) { el.className = 'cap-toggle cap-no'; el.textContent = 'Nein'; }
    else { el.className = 'cap-toggle cap-unknown'; el.textContent = '?'; }

    saveFromElement(el);
}

function saveRow(inputEl) {
    saveFromElement(inputEl);
}

async function saveFromElement(el) {
    // Modellname aus Element oder Zeile
    const modelName = el.getAttribute('data-model') || el.closest('tr').querySelector('[data-model]').getAttribute('data-model');

    // Alle Elemente fuer dieses Modell suchen (Hauptzeile + Detail-Zeile)
    const allEls = document.querySelectorAll('[data-model="' + CSS.escape(modelName) + '"]');
    let tool_calling = null, vision = null, notes_de = '', tool_instruction = '';

    allEls.forEach(e => {
        if (e.classList.contains('cap-toggle')) {
            const val = e.getAttribute('data-value');
            const parsed = val === 'true' ? true : val === 'false' ? false : null;
            if (e.getAttribute('data-field') === 'tool_calling') tool_calling = parsed;
            if (e.getAttribute('data-field') === 'vision') vision = parsed;
        }
        if (e.classList.contains('notes-input')) notes_de = e.value;
        if (e.classList.contains('instruction-textarea')) tool_instruction = e.value;
    });

    const resp = await fetch('/admin/models/capabilities', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pattern: modelName, tool_calling, vision, notes_de, tool_instruction }),
    });

    if (resp.ok) {
        const indicator = document.getElementById('save-' + cssId(modelName));
        if (indicator) {
            indicator.classList.add('show');
            setTimeout(() => indicator.classList.remove('show'), 1500);
        }
        // Update lokalen State
        const m = allModels.find(x => x.name === modelName);
        if (m) {
            m.has_custom_entry = true;
            m.capabilities = { tool_calling, vision, notes_de, tool_instruction };
        }
        // Zahnrad-Button gelb markieren wenn Instruktion gesetzt
        const instrId = 'instr-' + cssId(modelName);
        const instrRow = document.getElementById(instrId);
        if (instrRow) {
            const btn = instrRow.previousElementSibling?.querySelector('.btn-instr');
            if (btn) btn.classList.toggle('has-instruction', !!tool_instruction);
        }
    }
}

async function addPattern() {
    const input = document.getElementById('newPattern');
    const pattern = input.value.trim();
    if (!pattern) return;

    await fetch('/admin/models/capabilities', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pattern, tool_calling: null, vision: null, notes_de: '' }),
    });
    input.value = '';
    loadData();
}

async function deletePattern(pattern) {
    if (!confirm('Really delete pattern "' + pattern + '"?')) return;
    await fetch('/admin/models/capabilities', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pattern }),
    });
    loadData();
}

function esc(s) {
    if (s == null) return '';
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function escJs(s) {
    return String(s).replace(/\\\\/g,'\\\\\\\\').replace(/'/g,"\\\\'");
}
function cssId(s) {
    return String(s).replace(/[^a-zA-Z0-9_-]/g, '_');
}

// ── Tool/Helper Suitability Test (asynchron, läuft im Hintergrund) ──
let suitPollTimer = null;
let suitCur = { provider: '', model: '' };

async function suitInit() {
    try {
        const r = await fetch('/admin/settings/providers-list');
        const d = await r.json();
        document.getElementById('suitProvider').innerHTML = '<option value="">Provider…</option>' +
            (d.providers || []).map(p => `<option value="${esc(p)}">${esc(p)}</option>`).join('');
    } catch (e) { /* ignore */ }
    suitCasesInfo();
}
async function suitCasesInfo() {
    const el = document.getElementById('suitCases');
    if (!el) return;
    try {
        const r = await fetch('/admin/settings/llm-suitability-cases');
        const i = await r.json();
        const bt = i.by_task || {};
        const parts = Object.keys(bt).map(k => k + ':' + bt[k]);
        el.innerHTML = (i.total || 0) + ' frozen test cases from log'
            + (parts.length ? ' (' + esc(parts.join(', ')) + ')' : '')
            + (i.built_at ? ' · built ' + esc(i.built_at) : '')
            + ' <button class="btn" style="margin-left:6px;" onclick="suitRebuild()">Rebuild from log</button>';
    } catch (e) { el.textContent = 'Could not load test cases'; }
}
async function suitRebuild() {
    const el = document.getElementById('suitCases');
    if (el) el.textContent = 'Rebuilding from log…';
    try { await fetch('/admin/settings/llm-suitability-cases/rebuild', { method: 'POST' }); } catch (e) { /* ignore */ }
    suitCasesInfo();
}
async function suitLoadModels() {
    const prov = document.getElementById('suitProvider').value;
    const msel = document.getElementById('suitModel');
    if (!prov) { msel.innerHTML = '<option value="">Model…</option>'; return; }
    msel.innerHTML = '<option value="">Loading…</option>';
    try {
        const r = await fetch('/admin/settings/providers/' + encodeURIComponent(prov) + '/models');
        const d = await r.json();
        const models = d.models || [];
        const vis = new Set(d.vision || []);
        msel.innerHTML = models.length
            ? '<option value="">Model…</option>' + models.map(m => `<option value="${esc(m)}">${esc(m)}${vis.has(m) ? ' (vision)' : ''}</option>`).join('')
            : '<option value="">(no models' + (d.error ? ': ' + esc(d.error) : '') + ')</option>';
    } catch (e) { msel.innerHTML = '<option value="">(error)</option>'; }
}
function suitOnModelChange() {
    suitCur = { provider: document.getElementById('suitProvider').value,
                model: document.getElementById('suitModel').value };
    if (suitPollTimer) { clearTimeout(suitPollTimer); suitPollTimer = null; }
    document.getElementById('suitProgress').innerHTML = '';
    document.getElementById('suitStatus').textContent = '';
    if (suitCur.model) suitPoll();  // bereits laufenden/fertigen Job anzeigen
}
async function suitStart() {
    const provider = document.getElementById('suitProvider').value;
    const model = document.getElementById('suitModel').value;
    const status = document.getElementById('suitStatus');
    if (!model) { status.textContent = 'Bitte ein Modell wählen'; return; }
    document.getElementById('suitStartBtn').disabled = true;
    status.textContent = 'Starte…';
    document.getElementById('suitProgress').innerHTML = '';
    suitCur = { provider, model };
    try {
        await fetch('/admin/settings/llm-suitability-test/start', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ provider, model }),
        });
        suitPoll();
    } catch (e) {
        status.textContent = 'Fehler: ' + e.message;
        document.getElementById('suitStartBtn').disabled = false;
    }
}
function suitRenderJob(job) {
    const status = document.getElementById('suitStatus');
    const prog = document.getElementById('suitProgress');
    const checks = job.checks || [];
    if (job.status === 'running') {
        document.getElementById('suitStartBtn').disabled = true;
        status.textContent = 'Läuft… (' + (job.done || 0) + '/' + (job.total || '?') + ')';
    } else if (job.status === 'done') {
        const s = job.summary || {}; const v = s.verdict || {};
        status.innerHTML = 'Fertig ✔ — Tool: '
            + (v.tool ? '<span style="color:#3fb950;">SUITABLE</span>' : '<span style="color:#f85149;">not suitable</span>')
            + ' · Helper: ' + (v.helper ? '<span style="color:#3fb950;">suitable</span>' : '<span style="color:#f85149;">not suitable</span>')
            + ' · Score ' + esc(s.score || '') + ' (Tool ' + esc(s.tool || '') + ', Helper ' + esc(s.helper || '')
            + ', Halluz ' + (s.hallucinations || 0) + ')';
    } else if (job.status === 'error') {
        status.innerHTML = '<span style="color:#f85149;">Fehler: ' + esc(job.error || '') + '</span>';
    } else {
        status.textContent = '';
    }
    prog.innerHTML = checks.map(c => {
        const icon = c.ok ? '✅' : (c.hallucinated ? '⚠️' : '❌');
        const color = c.ok ? '#3fb950' : (c.hallucinated ? '#d29922' : '#f85149');
        return '<div style="padding:2px 0; border-bottom:1px solid #21262d; font-size:13px;">'
            + '<span style="color:' + color + ';">' + icon + '</span> '
            + '<span style="opacity:.6;">[' + esc(c.category) + ']</span> '
            + '<b>' + esc(c.label) + '</b> <span style="opacity:.7;">— ' + esc(c.detail || '') + '</span></div>';
    }).join('');
}
async function suitPoll() {
    if (suitPollTimer) { clearTimeout(suitPollTimer); suitPollTimer = null; }
    if (!suitCur.model) return;
    try {
        const q = 'provider=' + encodeURIComponent(suitCur.provider) + '&model=' + encodeURIComponent(suitCur.model);
        const r = await fetch('/admin/settings/llm-suitability-test/status?' + q);
        const job = await r.json();
        suitRenderJob(job);
        if (job.status === 'running') {
            suitPollTimer = setTimeout(suitPoll, 1500);
        } else {
            document.getElementById('suitStartBtn').disabled = false;
            if (job.status === 'done') loadData();  // Tabelle/Badge aktualisieren
        }
    } catch (e) {
        suitPollTimer = setTimeout(suitPoll, 2500);
    }
}

loadData();
suitInit();
</script>
</body>
</html>'''
