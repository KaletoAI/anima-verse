
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
            <td>${testBadge(caps, m.name)}</td>
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

function testBadge(caps, modelName) {
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

    // Welches Modell wurde WIRKLICH getestet? (Substring-Matching kann fremde
    // Ergebnisse anzeigen.) testedBare = Name ohne Provider-Prefix.
    const testedFull = (suit && suit.model) ? suit.model : '';
    const testedBare = testedFull.indexOf('::') >= 0 ? testedFull.split('::').pop() : testedFull;
    const inherited = !!(testedBare && modelName && testedBare.toLowerCase() !== modelName.toLowerCase());

    let tooltip = 'Score: ' + score;
    if (testedFull) tooltip += '\nGetestet als: ' + testedFull
        + (inherited ? '  \u26a0 GEERBT — dieses Modell wurde NICHT selbst getestet' : '');
    if (verdict) tooltip += '\nVerdict tool: ' + (verdict.tool ? 'SUITABLE' : 'not suitable') +
        ' / helper: ' + (verdict.helper ? 'suitable' : 'not suitable');
    if (toolScore) tooltip += '\nTool: ' + toolScore;
    if (helperScore) tooltip += '\nHelper: ' + helperScore;
    const sp = caps.tested_speed || null;
    if (sp && (sp.tok_per_s || sp.avg_latency_s)) tooltip += '\nSpeed: '
        + (sp.tok_per_s ? sp.tok_per_s + ' tok/s' : '')
        + (sp.avg_latency_s ? ' · Ø ' + sp.avg_latency_s + 's/Call' : '');
    if (hall > 0) tooltip += '\n' + hall + ' mit Halluzination';
    if (bestFmt) tooltip += '\nBestes Format: ' + bestFmt;
    if (visionResp.red) tooltip += '\nVision red: ' + visionResp.red;
    if (visionResp.blue) tooltip += '\nVision blue: ' + visionResp.blue;
    if (date) tooltip += '\nGetestet: ' + date;
    if (suit && Array.isArray(suit.checks)) {
        tooltip += '\n———';
        suit.checks.forEach(function(c){
            const mark = c.ok ? '\u2713' : (c.hallucinated ? '!' : '\u2717');
            tooltip += '\n' + mark + ' ' + c.label + ' \u2014 ' + (c.detail || '');
        });
    }

    let html = '<span class="test-badge ' + cls + '" title="' + esc(tooltip) + '">' + esc(score)
        + (inherited ? ' *' : '');
    if (hall > 0) html += ' <span class="test-detail">(' + hall + ' warn)</span>';
    html += '</span>';
    if (inherited) html += '<span class="test-date" style="color:#d29922;" title="' + esc(testedFull) + '">\u21aa geerbt: ' + esc(testedBare) + '</span>';
    if (verdict) {
        const tcol = verdict.tool ? '#3fb950' : '#f85149';
        const tlab = verdict.tool ? 'TOOL \u2713' : 'TOOL \u2717';
        html += '<span class="test-date" style="color:' + tcol + ';">' + tlab + '</span>';
    }
    if (toolScore || helperScore) html += '<span class="test-date">T ' + esc(toolScore) + ' \u00b7 H ' + esc(helperScore) + '</span>';
    if (sp && sp.tok_per_s) html += '<span class="test-date">\u26a1 ' + esc(sp.tok_per_s) + ' tok/s</span>';
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
    return String(s).replace(/\\/g,'\\\\').replace(/'/g,"\\'");
}
function cssId(s) {
    return String(s).replace(/[^a-zA-Z0-9_-]/g, '_');
}

// ── Tool/Helper Suitability Test (asynchron, läuft im Hintergrund) ──
let suitPollTimer = null;
let suitCur = { provider: '', model: '' };
let suitModels = [];          // alle Modelle des gewählten Providers
let suitVision = new Set();   // davon Vision-Modelle
let suitLoadErr = '';         // Fehlertext beim Modell-Laden

let suitJobsTimer = null;

async function suitInit() {
    try {
        const r = await fetch('/admin/settings/providers-list');
        const d = await r.json();
        document.getElementById('suitProvider').innerHTML = '<option value="">Provider…</option>' +
            (d.providers || []).map(p => `<option value="${esc(p)}">${esc(p)}</option>`).join('');
    } catch (e) { /* ignore */ }
    suitCasesInfo();
    suitJobsRefresh();  // startet eigenen Poll-Loop
}

// Liste ALLER Test-Jobs (laufend/fertig) — parallele Taucher auf einen Blick.
async function suitJobsRefresh() {
    if (suitJobsTimer) { clearTimeout(suitJobsTimer); suitJobsTimer = null; }
    const el = document.getElementById('suitJobs');
    if (!el) return;
    let jobs = [];
    try {
        const r = await fetch('/admin/settings/llm-suitability-test/jobs');
        jobs = (await r.json()).jobs || [];
    } catch (e) { /* ignore */ }
    const running = jobs.filter(j => j.status === 'running');
    if (!jobs.length) { el.innerHTML = ''; }
    else {
        // laufende zuerst, dann der Rest
        jobs.sort((a, b) => (a.status === 'running' ? 0 : 1) - (b.status === 'running' ? 0 : 1));
        el.innerHTML = '<div class="info-text" style="margin-bottom:4px;">Test-Jobs ('
            + running.length + ' laufend):</div>'
            + jobs.map(j => {
                const v = j.verdict || {};
                let st, col;
                if (j.status === 'running') { st = (j.done || 0) + '/' + (j.total || '?'); col = '#58a6ff'; }
                else if (j.status === 'done') {
                    st = (j.score || '') + (v.tool ? ' · TOOL ✓' : ' · TOOL ✗'); col = v.tool ? '#3fb950' : '#d29922';
                } else if (j.status === 'error') { st = 'Fehler'; col = '#f85149'; }
                else { st = j.status || ''; col = '#8b949e'; }
                const dot = j.status === 'running' ? '⏳' : (j.status === 'error' ? '❌' : '✔');
                return '<div style="padding:2px 0; cursor:pointer; font-size:13px;" '
                    + 'onclick="suitSelectJob(\'' + escJs(j.model) + '\')" title="Anzeigen">'
                    + dot + ' <b>' + esc(j.model) + '</b> '
                    + '<span style="color:' + col + ';">' + esc(st) + '</span></div>';
            }).join('');
    }
    // Solange etwas laeuft: haeufig pollen; sonst gemaechlich (zeigt fertige an).
    suitJobsTimer = setTimeout(suitJobsRefresh, running.length ? 2000 : 8000);
}

// Job aus der Liste anklicken → in der Detailansicht zeigen.
function suitSelectJob(modelFull) {
    const idx = modelFull.indexOf('::');
    suitCur = idx >= 0
        ? { provider: modelFull.slice(0, idx), model: modelFull.slice(idx + 2) }
        : { provider: '', model: modelFull };
    suitPoll();
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
    suitModels = []; suitVision = new Set();
    if (!prov) { suitRenderModels(); return; }
    msel.innerHTML = '<option value="">Loading…</option>';
    try {
        const r = await fetch('/admin/settings/providers/' + encodeURIComponent(prov) + '/models');
        const d = await r.json();
        suitModels = d.models || [];
        suitVision = new Set(d.vision || []);
        suitLoadErr = (!suitModels.length && d.error) ? d.error : '';
    } catch (e) { suitModels = []; suitLoadErr = 'error'; }
    suitRenderModels();
}
// Modell-Select aus suitModels bauen, gefiltert nach dem Suchfeld.
function suitRenderModels() {
    const msel = document.getElementById('suitModel');
    const cnt = document.getElementById('suitModelCount');
    if (!msel) return;
    const q = (document.getElementById('suitSearch').value || '').trim().toLowerCase();
    const prev = msel.value;
    if (!suitModels.length) {
        msel.innerHTML = '<option value="">' + (suitLoadErr ? '(no models: ' + esc(suitLoadErr) + ')' : 'Model…') + '</option>';
        if (cnt) cnt.textContent = '';
        return;
    }
    const filtered = q ? suitModels.filter(m => m.toLowerCase().includes(q)) : suitModels;
    msel.innerHTML = '<option value="">Model…</option>' +
        filtered.map(m => `<option value="${esc(m)}"${m === prev ? ' selected' : ''}>${esc(m)}${suitVision.has(m) ? ' (vision)' : ''}</option>`).join('');
    if (cnt) cnt.textContent = q ? (filtered.length + '/' + suitModels.length) : (suitModels.length + ' models');
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
        suitJobsRefresh();  // neuen Job sofort in der Liste zeigen
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
        const s = job.summary || {}; const v = s.verdict || {}; const sp = s.speed || {};
        const speedTxt = (sp.tok_per_s ? ' · ⚡ ' + sp.tok_per_s + ' tok/s' : '')
            + (sp.avg_latency_s ? ' · Ø ' + sp.avg_latency_s + 's/Call' : '');
        const infraTxt = (s.infra || s.saved === false)
            ? ' <span style="color:#d29922;">⚠ NICHT gespeichert (Infrastruktur-Fehler — Provider nicht erreichbar)</span>'
            : '';
        status.innerHTML = 'Fertig ✔ — Tool: '
            + (v.tool ? '<span style="color:#3fb950;">SUITABLE</span>' : '<span style="color:#f85149;">not suitable</span>')
            + ' · Helper: ' + (v.helper ? '<span style="color:#3fb950;">suitable</span>' : '<span style="color:#f85149;">not suitable</span>')
            + ' · Score ' + esc(s.score || '') + ' (Tool ' + esc(s.tool || '') + ', Helper ' + esc(s.helper || '')
            + ', Halluz ' + (s.hallucinations || 0) + ')' + speedTxt + infraTxt;
    } else if (job.status === 'error') {
        status.innerHTML = '<span style="color:#f85149;">Fehler: ' + esc(job.error || '') + '</span>';
    } else {
        status.textContent = '';
    }
    prog.innerHTML = checks.map(c => {
        const icon = c.infra ? '🔌' : (c.ok ? '✅' : (c.hallucinated ? '⚠️' : '❌'));
        const color = c.infra ? '#8b949e' : (c.ok ? '#3fb950' : (c.hallucinated ? '#d29922' : '#f85149'));
        const spd = (c.duration_s ? ' <span style="opacity:.5;">' + c.duration_s + 's'
            + (c.tok_s ? ', ' + c.tok_s + ' tok/s' : '') + '</span>' : '');
        return '<div style="padding:2px 0; border-bottom:1px solid #21262d; font-size:13px;">'
            + '<span style="color:' + color + ';">' + icon + '</span> '
            + '<span style="opacity:.6;">[' + esc(c.category) + ']</span> '
            + '<b>' + esc(c.label) + '</b> <span style="opacity:.7;">— ' + esc(c.detail || '') + '</span>'
            + spd + '</div>';
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
