
let allModels = [];
let unmatchedEntries = [];
let defaultToolInstruction = '';
let suitEntries = [];         // public routing labels and indices, never entry settings
let suitRoutingRevision = '';
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
    suitEntries = data.routing_entries || [];
    suitRoutingRevision = data.routing_revision || '';
    suitRenderEntries();

    // Populate the provider filter.
    const providers = [...new Set(allModels.map(m => m.provider))].sort();
    const provSel = document.getElementById('filterProvider');
    provSel.innerHTML = '<option value="">All providers</option>';
    providers.forEach(p => { provSel.add(new Option(p, p)); });

    renderAll();
}

function filterTable() {
    renderAll();
}

function sortBy(field) {
    if (sortField === field) {
        // Same column: ascending -> descending -> unsorted.
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

    // Filter the models. Default: only the ones we actually know something
    // about — a suitability test or a capability somebody filled in. Without
    // this the table lists every model every provider offers.
    let filtered = allModels.slice();
    if (search) filtered = filtered.filter(m => m.name.toLowerCase().includes(search) || m.provider.toLowerCase().includes(search));
    if (provFilter) filtered = filtered.filter(m => m.provider === provFilter);
    if (statusFilter === 'results') filtered = filtered.filter(m => m.has_result);
    if (statusFilter === 'unknown') filtered = filtered.filter(m => !m.has_result);

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
    const withResult = allModels.filter(m => m.has_result).length;
    document.getElementById('countLabel').textContent =
        filtered.length + ' / ' + allModels.length + ' models · ' + withResult + ' with result';
}

function renderModels(models) {
    const body = document.getElementById('modelsBody');
    body.innerHTML = '';
    models.forEach(m => {
        const row = document.createElement('tr');
        row.className = m.has_result ? 'row-documented' : 'row-unknown';
        const caps = m.capabilities || {};
        const sizeStr = m.size_gb ? esc(m.size_gb) + ' GB' : '';
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

        // Collapsible detail row for tool_instruction
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
                    placeholder="Custom tool instruction for this model...">${esc(caps.tool_instruction || '')}</textarea>
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
                <button class="btn btn-danger" style="font-size:11px;padding:2px 8px;margin-left:4px;" onclick="armDeletePattern(this, '${escJs(e.pattern)}')">X</button>
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
                    placeholder="Custom tool instruction for this model...">${esc(caps.tool_instruction || '')}</textarea>
            </td>
        `;
        body.appendChild(detailRow);
    });
}

function testBadge(caps) {
    const result = caps.tested_suitability;
    if (!suitCurrent(result)) return '<span class="test-badge none">-</span>';
    const verdict = caps.tested_verdict || result.verdict || '';
    return '<span class="test-badge ' + (verdict === 'yes' ? 'ok' : 'fail')
        + '" title="' + esc(result.scorer_version) + '">' + esc(verdict) + '</span>';
}

function suitCurrent(result) {
    const match = /^suitability-(\d+)$/.exec(result && result.scorer_version || '');
    return !!match && Number(match[1]) >= 5;
}

function capToggle(modelName, field, value) {
    let cls, label;
    if (value === true) { cls = 'cap-yes'; label = 'Yes'; }
    else if (value === false) { cls = 'cap-no'; label = 'No'; }
    else { cls = 'cap-unknown'; label = '?'; }
    return `<span class="cap-toggle ${cls}" data-model="${esc(modelName)}" data-field="${field}" data-value="${esc(value)}" onclick="toggleCap(this)">${label}</span>`;
}

function toggleCap(el) {
    const current = el.getAttribute('data-value');
    let next;
    if (current === 'true') next = false;
    else if (current === 'false') next = null;
    else next = true;

    el.setAttribute('data-value', String(next));
    if (next === true) { el.className = 'cap-toggle cap-yes'; el.textContent = 'Yes'; }
    else if (next === false) { el.className = 'cap-toggle cap-no'; el.textContent = 'No'; }
    else { el.className = 'cap-toggle cap-unknown'; el.textContent = '?'; }

    saveFromElement(el);
}

function saveRow(inputEl) {
    saveFromElement(inputEl);
}

async function saveFromElement(el) {
    // Model name from the element or its row.
    const modelName = el.getAttribute('data-model') || el.closest('tr').querySelector('[data-model]').getAttribute('data-model');

    // Find every element for this model (main row + detail row)
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
        // Update local state.
        const m = allModels.find(x => x.name === modelName);
        if (m) {
            m.has_custom_entry = true;
            m.capabilities = { tool_calling, vision, notes_de, tool_instruction };
        }
        // Highlight the instruction button when an instruction is set.
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

// Inline confirmation instead of a browser confirm(): the X turns into
// "Delete <pattern>? [Delete] [Cancel]" inside the row it belongs to
// (CLAUDE.md, "Frontend"; scripts/smoke_no_native_dialogs.py).
// Built as DOM nodes with real listeners, not as an HTML string: the pattern
// is arbitrary user text and never has to cross an attribute grammar this way.
function armDeletePattern(btn, pattern) {
    const strip = document.createElement('span');
    const question = document.createElement('span');
    question.style.cssText = 'font-size:11px;color:#c9d1d9;margin-left:4px;';
    question.textContent = 'Delete ' + pattern + '?';
    const yes = _smallButton('Delete', 'btn btn-danger');
    yes.onclick = () => deletePattern(pattern);
    const no = _smallButton('Cancel', 'btn');
    no.onclick = () => cancelDeletePattern(no, pattern);
    strip.appendChild(question);
    strip.appendChild(yes);
    strip.appendChild(no);
    btn.replaceWith(strip);
}

// Puts the row's X button back, without refetching the whole table.
function cancelDeletePattern(btn, pattern) {
    const strip = btn.parentElement;
    const x = _smallButton('X', 'btn btn-danger');
    x.onclick = () => armDeletePattern(x, pattern);
    strip.replaceWith(x);
}

function _smallButton(label, cls) {
    const b = document.createElement('button');
    b.className = cls;
    b.style.cssText = 'font-size:11px;padding:2px 8px;margin-left:4px;';
    b.textContent = label;
    return b;
}

// Only reachable from the armed strip above, so the question has been answered.
async function deletePattern(pattern) {
    await fetch('/admin/models/capabilities', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pattern }),
    });
    loadData();
}

function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
// A value that ends up INSIDE an inline onclick="fn('…')" crosses two
// grammars: escape it for the single-quoted JS literal first, then for the
// double-quoted HTML attribute. Same shape as rtJs() in settings-routing.js.
function escJs(s) {
    return esc(String(s == null ? '' : s).replace(/\\/g,'\\\\').replace(/'/g,"\\'"));
}
function cssId(s) {
    return String(s).replace(/[^a-zA-Z0-9_-]/g, '_');
}

// ── Tool/Helper Suitability Test (runs in the background) ──
let suitPollTimer = null;
let suitCur = { provider: '', model: '' };
let suitModels = [];          // every model of the selected provider
let suitEntryModel = '';      // key for retaining selection on data refresh only
let suitVision = new Set();   // of those, the vision-capable ones
let suitLoadErr = '';         // error text from loading the model list

let suitJobsTimer = null;

async function suitInit() {
    const start = document.getElementById('suitStartBtn');
    start.insertAdjacentHTML('beforebegin', '<label for="suitConcurrency">Concurrency</label> '
        + '<input type="number" id="suitConcurrency" min="1" max="3" step="1" value="3"> ');
    document.getElementById('suitJobs').id = 'suitQueue';
    document.getElementById('suitQueue').insertAdjacentHTML('beforebegin',
        '<button type="button" class="btn" onclick="suitDeleteOld(this)">Delete old test results</button>');
    document.querySelector('#suitBox h2').textContent = 'Single helper model suitability test';
    document.querySelector('#suitBox p').textContent = 'Tests tools, helpers, vision and speed using logged and curated structural cases. Tests run in a FIFO queue, one model at a time, with up to three requests inside a test. Results are saved; the queue survives page reloads.';

    try {
        const r = await fetch('/admin/settings/providers-list');
        const d = await r.json();
        document.getElementById('suitProvider').innerHTML = '<option value="">Provider…</option>' +
            (d.providers || []).map(p => `<option value="${esc(p)}">${esc(p)}</option>`).join('');
    } catch (e) { /* ignore */ }
    suitCasesInfo();
    suitJobsRefresh();  // starts its own polling loop
}

// List ALL test jobs (running and completed).
async function suitJobsRefresh() {
    if (suitJobsTimer) { clearTimeout(suitJobsTimer); suitJobsTimer = null; }
    const el = document.getElementById('suitQueue');
    if (!el) return;
    let jobs = [];
    try {
        const r = await fetch('/admin/settings/llm-suitability-test/jobs');
        jobs = (await r.json()).jobs || [];
    } catch (e) { /* ignore */ }
    const running = jobs.filter(j => j.status === 'running');
    if (!jobs.length) { el.innerHTML = ''; }
    else {
        el.innerHTML = '<div class="info-text" style="margin-bottom:4px;">Test jobs ('
            + running.length + ' running):</div>'
            + jobs.map(j => {
                const v = j.verdict || '';
                let st, col;
                if (j.status === 'running') { st = (j.done || 0) + '/' + (j.total || '?'); col = '#58a6ff'; }
                else if (j.status === 'queued') { st = 'Queued · position ' + j.position; col = '#8b949e'; }
                else if (j.status === 'done') {
                    st = (j.score || '') + ' · ' + v; col = v === 'yes' ? '#3fb950' : '#d29922';
                } else if (j.status === 'error') { st = 'Error'; col = '#f85149'; }
                else { st = j.status || ''; col = '#8b949e'; }
                const dot = j.status === 'running' ? '⏳' : (j.status === 'error' ? '❌' : '✔');
                return '<div style="padding:2px 0; cursor:pointer; font-size:13px;" '
                    + 'onclick="suitSelectJob(\'' + escJs(j.job_id) + '\')" title="Show details">'
                    + esc(j.position || 0) + ' · ' + dot + ' <b>' + esc(j.model) + '</b> '
                    + (j.entry_name ? '<span class="info-text">(' + esc(j.entry_name) + ')</span> ' : '')
                     + '<span style="color:' + col + ';">' + esc(j.status) + ' · ' + esc(st) + '</span>'
                    + (['queued', 'running'].includes(j.status) ? ' <button type="button" class="btn" onclick="event.stopPropagation();suitCancel(\'' + escJs(j.job_id) + '\',this)">Cancel</button>' : '') + '</div>';
            }).join('');
    }
    if (!suitCur.job_id && running.length) suitSelectJob(running[0].job_id);
    // Refresh active queues often, and completed results less often.
    suitJobsTimer = setTimeout(suitJobsRefresh, jobs.some(j => ['queued', 'running'].includes(j.status)) ? 2000 : 8000);
}

// Show a selected job in the detail view.
function suitSelectJob(jobId) {
    suitCur = { job_id: jobId };
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
        el.innerHTML = esc(i.total || 0) + ' frozen log + synthetic test cases'
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
    msel.value = '';
    suitRenderEntries();
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
// Build the model dropdown from suitModels, filtered by search.
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
    if (!filtered.includes(prev)) suitRenderEntries();
}
function suitRenderEntries() {
    const select = document.getElementById('suitEntry');
    if (!select) return;
    const provider = document.getElementById('suitProvider').value;
    const model = document.getElementById('suitModel').value;
    const key = provider + '::' + model;
    const previous = suitEntryModel === key ? select.value : '';
    const entries = model ? suitEntries.filter(e => e.provider === provider && e.model === model) : [];
    select.replaceChildren();
    if (!model) select.add(new Option('Select a model…', ''));
    else if (!entries.length) select.add(new Option('No saved LLM entry (temporary parameters optional)', ''));
    else {
        select.add(new Option(entries.length > 1 ? 'Select an LLM entry…' : 'LLM entry…', ''));
        entries.forEach(e => select.add(new Option(e.name + ' (#' + (e.index + 1) + ')', String(e.index))));
        select.value = entries.some(e => String(e.index) === previous) ? previous
            : (entries.length === 1 ? String(entries[0].index) : '');
    }
    suitEntryModel = key;
}
function suitFinite(value) {
    if (typeof value === 'number') return Number.isFinite(value);
    if (Array.isArray(value)) return value.every(suitFinite);
    if (value && typeof value === 'object') return Object.values(value).every(suitFinite);
    return true;
}
async function suitOnModelChange() {
    suitCur = { provider: document.getElementById('suitProvider').value,
                model: document.getElementById('suitModel').value };
    suitRenderEntries();
    if (suitPollTimer) { clearTimeout(suitPollTimer); suitPollTimer = null; }
    document.getElementById('suitProgress').innerHTML = '';
    document.getElementById('suitStatus').textContent = '';
    if (suitCur.model) {
        const full = suitCur.provider ? suitCur.provider + '::' + suitCur.model : suitCur.model;
        try {
            const response = await fetch('/admin/settings/llm-suitability-test/jobs');
            const jobs = ((await response.json()).jobs || []).filter(j => j.model.toLowerCase() === full.toLowerCase());
            const job = jobs.find(j => j.status === 'running' || j.status === 'queued') || jobs[jobs.length - 1];
            const current = suitCur.provider ? suitCur.provider + '::' + suitCur.model : suitCur.model;
            if (job && current === full) { suitCur = job; suitPoll(); }
        } catch (e) { /* The jobs list will retry on its next refresh. */ }
    }
}
function suitOverrideChanged() {
    document.getElementById('suitOverrideFields').hidden = !document.getElementById('suitOverride').checked;
    suitValidateExtraParams();
}
function suitVeniceTemplate() {
    document.getElementById('suitExtraParams').value =
        JSON.stringify({venice_parameters: {disable_thinking: true}}, null, 2);
    document.getElementById('suitOverride').checked = true;
    suitOverrideChanged();
}
function suitValidateExtraParams() {
    const input = document.getElementById('suitExtraParams');
    const error = document.getElementById('suitExtraError');
    if (!document.getElementById('suitOverride').checked) {
        error.textContent = '';
        return null;
    }
    try {
        const value = input.value.trim() ? JSON.parse(input.value) : {};
        if (!value || typeof value !== 'object' || Array.isArray(value))
            throw new Error('Enter a JSON object (not an array or scalar).');
        if (!suitFinite(value))
            throw new Error('Request parameters must contain only finite numbers.');
        error.textContent = '';
        return value;
    } catch (e) {
        error.textContent = e instanceof SyntaxError ? 'Invalid JSON: ' + e.message : e.message;
        return null;
    }
}
async function suitStart() {
    const provider = document.getElementById('suitProvider').value;
    const model = document.getElementById('suitModel').value;
    const status = document.getElementById('suitStatus');
    if (!model) { status.textContent = 'Please pick a model'; return; }
    const entry = document.getElementById('suitEntry');
    const matches = suitEntries.filter(e => e.provider === provider && e.model === model);
    if (matches.length && !matches.some(e => String(e.index) === entry.value)) {
        status.textContent = 'Please select an LLM entry';
        return;
    }
    const concurrency = Number(document.getElementById('suitConcurrency').value);
    if (!Number.isInteger(concurrency) || concurrency < 1 || concurrency > 3) {
        status.textContent = 'Concurrency must be an integer from 1 to 3';
        return;
    }
    const override = document.getElementById('suitOverride').checked;
    const extraParams = suitValidateExtraParams();
    if (override && extraParams === null) { status.textContent = 'Fix temporary request parameters before starting.'; return; }
    document.getElementById('suitStartBtn').disabled = true;
    status.textContent = 'Starting…';
    document.getElementById('suitProgress').innerHTML = '';
    suitCur = { provider, model };
    try {
        const r = await fetch('/admin/settings/llm-suitability-test/start', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ provider, model, concurrency,
                ...(matches.length ? {
                    entry_index: Number(entry.value),
                    routing_revision: suitRoutingRevision,
                } : {}),
                ...(override ? {extra_params: extraParams} : {}) }),
        });
        if (!r.ok) {
            const data = await r.json().catch(() => ({}));
            throw new Error(typeof data.detail === 'string' ? data.detail : 'HTTP ' + r.status);
        }
        suitCur = await r.json();
        suitPoll();
        suitJobsRefresh();
    } catch (e) {
        status.textContent = 'Error: ' + e.message;
        document.getElementById('suitStartBtn').disabled = false;
    }
}
async function suitCancel(jobId, button) {
    button.disabled = true;
    try {
        const response = await fetch('/admin/settings/llm-suitability-test/cancel', {
            method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({job_id: jobId}),
        });
        if (!response.ok) throw new Error('HTTP ' + response.status);
        document.getElementById('suitStatus').textContent = 'Cancellation requested';
        suitJobsRefresh();
    } catch (error) {
        document.getElementById('suitStatus').textContent = 'Cancel failed: ' + error.message;
        button.disabled = false;
    }
}

async function suitDeleteOld(button) {
    button.disabled = true;
    try {
        const response = await fetch('/admin/settings/llm-suitability-test/delete-old', {method: 'POST'});
        if (!response.ok) throw new Error('HTTP ' + response.status);
        const result = await response.json();
        document.getElementById('suitStatus').textContent = 'Deleted old test results: ' + result.deleted;
        await loadData();
        suitJobsRefresh();
    } catch (error) {
        document.getElementById('suitStatus').textContent = 'Delete failed: ' + error.message;
    } finally { button.disabled = false; }
}

function suitRenderJob(job) {
    const status = document.getElementById('suitStatus');
    const prog = document.getElementById('suitProgress');
    // Starting another model is allowed while the current job waits or runs.
    document.getElementById('suitStartBtn').disabled = false;
    const summary = job.summary || {};
    let checks = summary.checks || job.checks || [];
    if (job.status === 'done') {
        if (!suitCurrent(summary)) { status.textContent = ''; prog.innerHTML = ''; return; }
        const speed = summary.speed || {};
        const vision = summary.vision || {};
        const limit = job.max_turn_seconds == null ? 20 : job.max_turn_seconds;
        const number = value => value == null ? 'not tested' : String(value);
        status.innerHTML = '<b>' + esc(job.model || summary.model || '') + '</b> · Finished'
            + '<div>Tools: ' + esc(summary.tool || 'not tested')
            + ' · Helpers: ' + esc(summary.helper || 'not tested')
            + ' · Vision: ' + esc(vision.verdict === 'not_tested' || vision.rate == null ? 'not tested' : (vision.rate * 100).toFixed(1) + '%') + '</div>'
            + '<div>Concurrency: ' + esc(number(summary.concurrency))
            + (summary.live_play ? ' · measured under live play' : '') + '</div>'
            + '<div>' + ['tools', 'helpers', 'vision'].map(group => {
                const measured = speed[group] || {};
                return esc(group) + ': median ' + esc(number(measured.median_latency_s)) + ' s · '
                    + esc(number(measured.tok_s)) + ' tok/s';
            }).join(' | ') + '</div>'
            + '<div>Projected non-RP time per thought turn: ' + esc(number(summary.projected_turn_s))
            + ' s / maximum ' + esc(limit) + ' s</div>'
            + '<div>Suitable as the single helper model: <b>' + esc(summary.verdict || 'not tested') + '</b></div>'
            + (summary.saved === false || summary.infra ? '<div>Quality result not saved; inspect diagnostics.</div>' : '')
            + (summary.curated_only ? '<div>Curated cases only; no logged cases.</div>' : '');
        checks = checks.filter(check => check.ok === false);
        if (!checks.length) { prog.innerHTML = '<div>No failing cases.</div>'; return; }
    } else if (job.status === 'running') {
        status.textContent = 'Running ' + (job.model || '') + ' · ' + (job.entry_name || '')
            + ' (' + (job.done || 0) + '/' + (job.total || '?') + ')';
    } else if (job.status === 'queued') {
        status.textContent = 'Queued · position ' + job.position;
    } else {
        status.textContent = job.status === 'error' ? 'Error: ' + (job.error || '') : job.status;
    }
    prog.innerHTML = checks.map(check => {
        const prompt = check.prompt || {};
        const runs = check.runs || [];
        return '<div class="suit-case"><b>' + esc(check.ok === false ? 'Failed' : check.ok ? 'Passed' : 'Excluded')
            + ' · ' + esc(check.group || '') + ' · ' + esc(check.task || check.label || check.id || '') + '</b>'
            + '<div>' + esc(check.detail || '') + '</div>'
            + (check.ok === false ? '<details><summary>Prompt (system + user)</summary><h4>System</h4><pre>'
                + esc(prompt.system || 'Prompt unavailable') + '</pre><h4>User</h4><pre>' + esc(prompt.user || '')
                + '</pre></details><details open><summary>Model answer(s)</summary>'
                + (runs.length ? runs.map((run, index) => '<h4>Run ' + (index + 1) + '</h4><pre>'
                    + esc(run.content || run.error || '(empty answer)') + '</pre>').join('') : '<p>Raw answer unavailable.</p>')
                + '</details>' : '') + '</div>';
    }).join('');
}
async function suitPoll() {
    if (suitPollTimer) { clearTimeout(suitPollTimer); suitPollTimer = null; }
    if (!suitCur.job_id) return;
    try {
        const q = 'job_id=' + encodeURIComponent(suitCur.job_id);
        const r = await fetch('/admin/settings/llm-suitability-test/status?' + q);
        const job = await r.json();
        suitRenderJob(job);
        if (job.status === 'running' || job.status === 'queued') {
            suitPollTimer = setTimeout(suitPoll, 1500);
        } else {
            document.getElementById('suitStartBtn').disabled = false;
            if (job.status === 'done') loadData();  // Refresh table and badges.
        }
    } catch (e) {
        suitPollTimer = setTimeout(suitPoll, 2500);
    }
}

loadData();
suitInit();
