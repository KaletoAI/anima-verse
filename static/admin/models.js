
let allModels = [];
let unmatchedEntries = [];
let defaultToolInstruction = '';
let suitEntries = [];
let suitGroupTasks = {};
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
    suitGroupTasks = data.suitability_group_tasks || {};
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
    if (field === 'speed') {
        // Untested models sort after every measured one.
        const t = ((m.capabilities || {}).tested_suitability || {}).projected_turn_s;
        return t == null ? Number.MAX_VALUE : Number(t);
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
        const sizeStr = [m.size_gb ? m.size_gb + ' GB' : '', m.parameter_size, m.quantization]
            .filter(Boolean).map(esc).join(' · ');
        const reported = m.reported || {};
        const hasInstr = caps.tool_instruction ? ' has-instruction' : '';
        const instrId = 'instr-' + cssId(m.name);

        row.innerHTML = `
            <td><span class="badge-provider">${esc(m.provider)}</span>${m.listed === false ? ' <span class="info-text" title="The provider is disabled or not reachable right now; this row comes from the saved test result.">not loaded</span>' : ''}</td>
            <td><strong>${esc(m.name)}</strong></td>
            <td><span class="badge-size">${sizeStr}</span></td>
            <td>${capToggle(m.name, 'tool_calling', caps.tool_calling, reported.tool_calling)}</td>
            <td>${capToggle(m.name, 'vision', caps.vision, reported.vision)}</td>
            <td>${testBadge(caps, m.name)}</td>
            <td>${speedCell(caps)}</td>
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
            <td colspan="9">
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

function suitCutoffStats(result) {
    const checks = result.checks || [];
    const count = check => check.truncated_runs ?? (check.run_checks || []).filter(r => r.truncated).length;
    return {
        total: result.total_runs ?? checks.reduce((n, c) => n + (c.run_checks || c.runs || []).length, 0),
        cut: result.truncated_runs ?? checks.reduce((n, c) => n + count(c), 0),
        failed: result.failed_by_truncation ?? checks.filter(c => {
            const failing = (c.run_checks || []).filter(r => r.ok === false);
            return c.ok === false && failing.length && failing.every(r => r.truncated);
        }).map(c => c.id),
    };
}
function suitThinkingText(result) {
    return result.thinking_runs > 0 && (result.settings || {}).thinking === false
        ? 'The model produced reasoning although thinking was off (median '
            + (result.reasoning_tokens_median ?? 'unknown') + ' reasoning tokens).' : '';
}
function suitWarning(result, settings) {
    const stats = suitCutoffStats(result);
    if (!stats.cut) return '';
    return '<div class="suit-warn">⚠ ' + stats.cut + ' of ' + stats.total
        + ' answers were cut off at the token limit (Max tokens ' + esc((settings || {}).max_tokens ?? 'unknown')
        + ').<div>Failed only because of this: ' + esc(stats.failed.join(', ') || 'none')
        + '</div>' + (suitThinkingText(result) ? '<div>' + esc(suitThinkingText(result)) + '</div>' : '') + '</div>';
}
function suitDiagnosticBadges(result) {
    const stats = suitCutoffStats(result);
    const tooltip = stats.cut + ' of ' + stats.total + ' answers hit the token limit (finish_reason=length). Cases that failed only because of this: '
        + stats.failed.length + '. Usually thinking that was not switched off or a too small Max tokens - the score then says little about the model.';
    return (stats.cut ? ' <span class="test-badge amber" title="' + esc(tooltip) + '">✂ ' + stats.cut + '/' + stats.total + ' cut off</span>' : '')
        + (suitThinkingText(result) ? ' <span class="test-badge amber" title="' + esc(suitThinkingText(result)) + '">🧠 thinks (' + result.thinking_runs + ' runs)</span>' : '');
}

function testBadge(caps) {
    const result = caps.tested_suitability;
    if (!suitCurrent(result)) return '<span class="test-badge none">-</span>';
    const verdict = caps.tested_verdict || result.verdict || '';
    const vision = result.vision || {};
    const speed = result.speed || {};
    const visionText = vision.rate == null ? 'not tested' : Math.round(vision.rate * 100) + '%';
    const tooltip = 'Tools ' + (result.tool || '-') + ' · Helpers ' + (result.helper || '-')
        + ' · Vision ' + visionText + '\n'
        + ['tools', 'helpers', 'vision'].map(g => g + ' median ' + ((speed[g] || {}).median_latency_s ?? '-') + ' s').join(' · ')
        + '\n' + suitSettingsText(result.settings) + (result.settings ? '\n' + JSON.stringify(result.settings) : '') + '\n' + (caps.tested_date || '') + ' · ' + result.scorer_version + ' · click for details';
    const key = result.model || '';
    return '<span class="test-badge ' + (verdict === 'yes' ? 'ok' : 'fail') + '" style="cursor:pointer;"'
        + ' title="' + esc(tooltip) + '"'
        + (key ? ' onclick="suitShowSaved(\'' + escJs(key) + '\')"' : '') + '>'
        + esc((caps.tested_score || result.score || '') + ' · ' + verdict) + '</span>' + suitDiagnosticBadges(result);
}

// Speed of the last current test: projected seconds per thought turn, big,
// red when the verdict failed on speed; the median per group below it.
function speedCell(caps) {
    const result = caps.tested_suitability;
    if (!suitCurrent(result) || result.projected_turn_s == null) return '<span class="test-badge none">-</span>';
    const slow = result.speed_ok === false
        || (result.speed_ok == null && String(result.verdict || '').includes('speed'));
    const limit = result.max_turn_seconds == null ? '' : ' (limit ' + result.max_turn_seconds + ' s)';
    const speed = result.speed || {};
    const groups = ['tools', 'helpers', 'vision']
        .filter(g => (speed[g] || {}).median_latency_s != null)
        .map(g => g + ' ' + speed[g].median_latency_s + ' s');
    return '<span class="speed-turn ' + (slow ? 'slow' : 'fast') + '" title="Projected non-RP time per thought turn' + esc(limit) + '">'
        + esc(Number(result.projected_turn_s).toFixed(1)) + ' s/turn</span>'
        + (groups.length ? '<div class="speed-groups">' + esc(groups.join(' · ')) + '</div>' : '');
}

// Open a saved result (model table badge) in the test detail view.
function suitShowSaved(model) {
    suitSelectJob('saved:' + model);
    const target = document.getElementById('suitDetail');
    if (target) target.scrollIntoView({behavior: 'smooth', block: 'start'});
}

function suitCurrent(result) {
    const match = /^suitability-(\d+)$/.exec(result && result.scorer_version || '');
    return !!match && Number(match[1]) >= 5;
}

// reported = where an unstored value comes from ('provider' = its model
// list, 'test' = the last test answered images): shown dimmed with a
// tooltip; a click stores it for real.
function capToggle(modelName, field, value, reported = '') {
    let cls, label;
    if (value === true) { cls = 'cap-yes'; label = 'Yes'; }
    else if (value === false) { cls = 'cap-no'; label = 'No'; }
    else { cls = 'cap-unknown'; label = '?'; }
    const source = reported ? ' cap-reported" title="' + (reported === 'test' ? 'From the last test' : 'Reported by the provider')
        + ' — click to store a value' : '';
    return `<span class="cap-toggle ${cls}${source}" data-model="${esc(modelName)}" data-field="${field}" data-value="${esc(reported ? capPredecessor(value) : value)}" onclick="toggleCap(this)">${label}</span>`;
}

// The cycle is Yes -> No -> ? -> Yes; a reported value carries its
// predecessor so that the first click stores exactly what is shown.
function capPredecessor(value) {
    return value === true ? 'null' : value === false ? 'true' : 'false';
}

function toggleCap(el) {
    const current = el.getAttribute('data-value');
    let next;
    if (current === 'true') next = false;
    else if (current === 'false') next = null;
    else next = true;

    el.setAttribute('data-value', String(next));
    el.removeAttribute('title');
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
let suitCombobox = null;
let suitJobsTimer = null;
let suitQueuePreference = null;

async function suitInit() {
    document.getElementById('suitModelPicker').innerHTML = ModelCombobox.render({id: 'suitModel'});
    suitCombobox = ModelCombobox.attach('suitModel', {loadModels: suitFetchModels, onChange: () => {}});
    try { suitQueuePreference = localStorage.getItem('suit-queue-open'); } catch (e) { /* Storage may be unavailable. */ }
    const queue = document.getElementById('suitQueueBox');
    if (suitQueuePreference !== null) queue.open = suitQueuePreference === 'true';
    queue.addEventListener('toggle', () => {
        // Programmatic default changes do not create a persistent preference.
        if (queue.open === suitQueueDefaultOpen && suitQueuePreference === null) return;
        suitQueuePreference = String(queue.open);
        try { localStorage.setItem('suit-queue-open', suitQueuePreference); } catch (e) { /* Storage may be unavailable. */ }
    });
    try {
        const r = await fetch('/admin/settings/providers-list');
        const d = await r.json();
        document.getElementById('suitProvider').innerHTML = '<option value="">Provider…</option>' +
            (d.providers || []).map(p => `<option value="${esc(p)}">${esc(p)}${(d.disabled || []).includes(p) ? ' (disabled in game)' : ''}</option>`).join('');
    } catch (e) { /* ignore */ }
    suitCasesInfo();
    suitJobsRefresh();  // starts its own polling loop
}

let suitQueueDefaultOpen = false;
function suitQueueGroups(jobs) {
    const groups = new Map();
    jobs.forEach(job => {
        const provider = job.provider || job.model.split('::')[0];
        if (!groups.has(provider)) groups.set(provider, []);
        groups.get(provider).push(job);
    });
    return groups;
}
function suitQueueSummary(jobs) {
    if (!jobs.length) return 'Queue empty';
    return Array.from(suitQueueGroups(jobs), ([provider, group]) => {
        const running = group.filter(j => j.status === 'running').length;
        const waiting = group.filter(j => j.status === 'queued').length;
        return provider + ': ' + ([running ? running + ' running' : '', waiting ? waiting + ' waiting' : ''].filter(Boolean).join(', ') || 'idle');
    }).join(' · ');
}
function suitSettingsText(settings) {
    if (!settings) return 'Settings not recorded (older test)';
    const temps = settings.temperature || {};
    return 'Temperatures: tools ' + (temps.tools ?? '—') + ' / helpers ' + (temps.helpers ?? '—')
        + ' / vision ' + (temps.vision ?? '—') + ' · Max tokens: ' + (settings.max_tokens ?? '—')
        + ' · Thinking: ' + (settings.thinking ? 'on' : 'off');
}
async function suitJobsRefresh() {
    if (suitJobsTimer) { clearTimeout(suitJobsTimer); suitJobsTimer = null; }
    let jobs;
    try {
        const response = await fetch('/admin/settings/llm-suitability-test/jobs');
        if (!response.ok) throw new Error('HTTP ' + response.status);
        jobs = (await response.json()).jobs || [];
        document.getElementById('suitQueueSummary').textContent = suitQueueSummary(jobs);
        const queue = document.getElementById('suitQueueBox');
        suitQueueDefaultOpen = jobs.some(j => ['queued', 'running'].includes(j.status));
        if (suitQueuePreference === null) queue.open = suitQueueDefaultOpen;
        document.getElementById('suitQueue').innerHTML = Array.from(suitQueueGroups(jobs), ([provider, group]) =>
            '<h3>' + esc(provider) + '</h3>' + group.map(j =>
                '<div class="suit-job"><button type="button" class="btn" onclick="suitSelectJob(\'' + escJs(j.job_id) + '\')">'
                + esc(j.model) + '</button> · ' + esc(j.status) + ' · ' + esc(j.done || 0) + '/' + esc(j.total || '?')
                + (j.status === 'queued' ? ' · position ' + esc(j.position) : '')
                + '<div class="info-text">' + esc(suitSettingsText(j.settings)) + '</div>'
                + (['queued', 'running'].includes(j.status) ? '<button type="button" class="btn" onclick="suitCancel(\''
                    + escJs(j.job_id) + '\',this)">Cancel</button>' : '') + '</div>').join('')).join('');
    } catch (error) {
        document.getElementById('suitQueueSummary').textContent = 'Could not load queue';
    }
    suitJobsTimer = setTimeout(suitJobsRefresh, 2000);
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
        const groups = i.by_group || {};
        const parts = ['tools', 'helpers', 'vision'].filter(g => groups[g]).map(g => groups[g] + ' ' + g);
        el.textContent = (i.total || 0) + ' test cases' + (parts.length ? ': ' + parts.join(', ') : '');
    } catch (e) { el.textContent = 'Could not load test cases'; }
}
async function suitFetchModels() {
    const provider = document.getElementById('suitProvider').value;
    if (!provider) return [];
    const response = await fetch('/admin/settings/providers/' + encodeURIComponent(provider) + '/models');
    if (!response.ok) throw new Error('HTTP ' + response.status);
    const data = await response.json();
    if (data.error && !(data.models || []).length) throw new Error(data.error);
    return data.models || [];
}
function suitLoadModels() {
    document.getElementById('suitModel').value = '';
    return suitCombobox.reload();
}
function suitRenderEntries() {
    const select = document.getElementById('suitPrefill');
    if (!select) return;
    const previous = select.value;
    select.innerHTML = '<option value="">Choose an entry…</option>' + suitEntries.map(e =>
        '<option value="' + esc(e.index) + '">' + esc(e.name + ' · ' + e.provider + '::' + e.model) + '</option>').join('');
    select.value = previous;
}
function suitPrefillTemperatures(chosen, entries, tasks, current) {
    const result = {...current};
    const serves = (entry, group) => (tasks[group] || []).some(task => (entry.tasks || []).some(assignment => assignment.task === task));
    ['tools', 'helpers', 'vision'].forEach(group => {
        const matching = entries.find(e => e.enabled !== false && e.provider === chosen.provider
            && e.model === chosen.model && serves(e, group));
        const source = matching || (serves(chosen, group) ? chosen : null);
        if (source && typeof source.temperature === 'number') result[group] = source.temperature;
    });
    return result;
}
function suitPrefill() {
    const chosen = suitEntries.find(e => String(e.index) === document.getElementById('suitPrefill').value);
    if (!chosen) return;
    const providerSelect = document.getElementById('suitProvider');
    providerSelect.value = chosen.provider;
    if (providerSelect.value !== chosen.provider) {
        document.getElementById('suitStatus').textContent =
            'Provider ' + chosen.provider + ' no longer exists — values copied, pick another provider.';
    }
    document.getElementById('suitModel').value = chosen.model;
    suitCombobox.reload();
    const ids = {tools: 'suitTempTools', helpers: 'suitTempHelpers', vision: 'suitTempVision'};
    const current = Object.fromEntries(Object.entries(ids).map(([group, id]) => [group, Number(document.getElementById(id).value)]));
    const temps = suitPrefillTemperatures(chosen, suitEntries, suitGroupTasks, current);
    Object.entries(ids).forEach(([group, id]) => { document.getElementById(id).value = temps[group]; });
    document.getElementById('suitPenalty').value = chosen.repetition_penalty ?? '';
    document.getElementById('suitMaxTokens').value = chosen.max_tokens ?? 900;
    document.getElementById('suitChatTemplate').value = chosen.chat_template || '';
    document.getElementById('suitThinking').value = chosen.thinking ? 'on' : 'off';
    document.getElementById('suitExtraParams').value = JSON.stringify(chosen.extra_params || {}, null, 2);
    suitValidateExtraParams();
    // Selection is a one-time copy and is never sent with a test request.
    document.getElementById('suitPrefill').value = '';
}
function suitFinite(value) {
    if (typeof value === 'number') return Number.isFinite(value);
    if (Array.isArray(value)) return value.every(suitFinite);
    if (value && typeof value === 'object') return Object.values(value).every(suitFinite);
    return true;
}
function suitVeniceTemplate() {
    document.getElementById('suitExtraParams').value =
        JSON.stringify({venice_parameters: {disable_thinking: true}}, null, 2);
    suitValidateExtraParams();
}
function suitValidateExtraParams() {
    const input = document.getElementById('suitExtraParams');
    const error = document.getElementById('suitExtraError');
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
    const concurrency = Number(document.getElementById('suitConcurrency').value);
    if (!Number.isInteger(concurrency) || concurrency < 1) {
        status.textContent = 'Parallel requests must be a positive integer'; return;
    }
    const extraParams = suitValidateExtraParams();
    if (extraParams === null) { status.textContent = 'Fix extra params before starting.'; return; }
    const penalty = document.getElementById('suitPenalty').value;
    const settings = {
        temperature: {tools: Number(document.getElementById('suitTempTools').value),
            helpers: Number(document.getElementById('suitTempHelpers').value),
            vision: Number(document.getElementById('suitTempVision').value)},
        repetition_penalty: penalty === '' ? null : Number(penalty),
        max_tokens: Number(document.getElementById('suitMaxTokens').value),
        chat_template: document.getElementById('suitChatTemplate').value,
        thinking: document.getElementById('suitThinking').value === 'on', extra_params: extraParams,
    };
    document.getElementById('suitStartBtn').disabled = true;
    status.textContent = 'Starting…';
    document.getElementById('suitProgress').innerHTML = '';
    suitCur = { provider, model };
    try {
        const r = await fetch('/admin/settings/llm-suitability-test/start', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({provider, model, settings, concurrency}),
        });
        if (!r.ok) {
            const data = await r.json().catch(() => ({}));
            throw new Error(typeof data.detail === 'string' ? data.detail : 'HTTP ' + r.status);
        }
        suitCur = await r.json();
        status.textContent = 'Test queued';
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
    const status = document.getElementById('suitDetailStatus');
    document.getElementById('suitDetail').hidden = false;
    const settings = job.settings || (job.summary || {}).settings;
    document.getElementById('suitSettings').innerHTML = '<p>' + esc(suitSettingsText(settings)) + '</p>'
        + (settings ? '<pre>' + esc(JSON.stringify(settings, null, 2)) + '</pre>' : '');
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
            + suitWarning({...summary, settings}, settings)
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
        status.textContent = 'Running ' + (job.model || '')
            + ' (' + (job.done || 0) + '/' + (job.total || '?') + ')';
    } else if (job.status === 'queued') {
        status.textContent = 'Queued · position ' + job.position;
    } else {
        status.textContent = job.status === 'error' ? 'Error: ' + (job.error || '') : job.status;
    }
    prog.innerHTML = checks.map(check => {
        const prompt = check.prompt || {};
        const runs = check.runs || [];
        const cut = check.truncated_runs ?? (check.run_checks || []).filter(r => r.truncated).length;
        return '<div class="suit-case"><b>' + esc(check.ok === false ? 'Failed' : check.ok ? 'Passed' : 'Excluded')
            + (cut ? ' · cut off ' + cut + '/' + (check.run_checks || runs).length : '')
            + ' · ' + esc(check.group || '') + ' · ' + esc(check.task || check.label || check.id || '') + '</b>'
            + '<div>' + esc(check.detail || '') + '</div>'
            + (check.ok === false ? '<details><summary>Prompt (system + user)</summary><h4>System</h4><pre>'
                + esc(prompt.system || 'Prompt unavailable') + '</pre><h4>User</h4><pre>' + esc(prompt.user || '')
                + '</pre></details><details open><summary>Model answer(s)</summary>'
                + (runs.length ? runs.map((run, index) => '<h4>Run ' + (index + 1) + '</h4><pre>'
                    + esc(run.content || run.error || (run.finish_reason === 'length' ? '' : '(empty answer)'))
                    + esc(run.finish_reason === 'length' ? (run.content ? '\n' : '') + '(cut off at the token limit'
                        + ((run.usage || {}).reasoning_tokens != null ? ' - ' + run.usage.reasoning_tokens + ' reasoning tokens' : '') + ')'
                        : (run.usage || {}).reasoning_tokens > 0 ? ' (' + run.usage.reasoning_tokens + ' reasoning tokens)' : '') + '</pre>').join('') : '<p>Raw answer unavailable.</p>')
                + '</details>' : '') + '</div>';
    }).join('');
}
async function suitPoll() {
    if (suitPollTimer) { clearTimeout(suitPollTimer); suitPollTimer = null; }
    if (!suitCur.job_id) return;
    const selectedJob = suitCur.job_id;
    try {
        const q = 'job_id=' + encodeURIComponent(selectedJob);
        const r = await fetch('/admin/settings/llm-suitability-test/status?' + q);
        if (selectedJob !== suitCur.job_id) return;
        if (r.status === 404) {  // No saved result for this model yet.
            document.getElementById('suitDetailStatus').textContent = 'Result no longer available';
            document.getElementById('suitProgress').innerHTML = '';
            return;
        }
        if (!r.ok) throw new Error('HTTP ' + r.status);
        const job = await r.json();
        if (selectedJob !== suitCur.job_id) return;
        suitRenderJob(job);
        if (job.status === 'running' || job.status === 'queued') {
            suitPollTimer = setTimeout(suitPoll, 1500);
        } else {
            document.getElementById('suitStartBtn').disabled = false;
            if (job.status === 'done') loadData();  // Refresh table and badges.
        }
    } catch (e) {
        if (selectedJob === suitCur.job_id) suitPollTimer = setTimeout(suitPoll, 2500);
    }
}

loadData();
suitInit();
