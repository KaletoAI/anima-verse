// ── LLM Routing (Advanced): the task-centric editor ─────────────────────
// plan-llm-routing-ui.md, Task 3. Loaded AFTER static/admin/settings.js, so
// every global of that file (CONFIG, SCHEMA, esc, toast, loadLlmCatalog,
// renderRequirementBadges, ensureModelCaps, …) is available at run time.
//
// The section is a PAGED schema section (config_schema.py → llm_routing.pages):
//   tasks    — one row per catalog task with its ordered LLM chain  (this file)
//   llms     — the per-LLM editor                                   (Task 4)
//   overview — what the server would route right now                (Task 4)
//
// The config model is unchanged: CONFIG.llm_routing is a list of LLM entries
// {name, enabled, preload_on_startup, provider, model, temperature, max_tokens,
//  chat_template, tasks: [{task, order}]}. This page only edits the `tasks`
// lists — a task's chain is its assignments across ALL entries, ordered.

// >>> harness-extract:routingModel
// Pure functions over CONFIG.llm_routing (a list of LLM entries, each with
// tasks: [{task, order}]). No DOM, no globals — scripts/check_routing_model.js
// runs this block on its own. Orders are per task: the chain of a task is its
// assignments across ALL entries sorted by order (ties by entry index), and
// every mutation renumbers that task's orders to 1..n by position.
function buildTaskChains(routing) {
    const chains = {};
    (routing || []).forEach((entry, idx) => {
        if (!entry || typeof entry !== 'object') return;
        for (const t of (entry.tasks || [])) {
            if (!t || !t.task) continue;
            (chains[t.task] = chains[t.task] || []).push({ entry: idx, order: Number(t.order) || 999 });
        }
    });
    for (const k in chains) chains[k].sort((a, b) => (a.order - b.order) || (a.entry - b.entry));
    return chains;
}
function renumberTask(routing, taskId) {
    const chain = buildTaskChains(routing)[taskId] || [];
    chain.forEach((row, i) => {
        const t = (routing[row.entry].tasks || []).find(x => x && x.task === taskId);
        if (t) t.order = i + 1;
    });
}
function assignTask(routing, taskId, entryIdx) {
    const entry = routing[entryIdx];
    if (!entry) return false;
    if (!Array.isArray(entry.tasks)) entry.tasks = [];
    if (entry.tasks.some(t => t && t.task === taskId)) return false;
    const chain = buildTaskChains(routing)[taskId] || [];
    const max = chain.reduce((m, r) => Math.max(m, r.order), 0);
    entry.tasks.push({ task: taskId, order: max + 1 });
    return true;
}
function unassignTask(routing, taskId, entryIdx) {
    const entry = routing[entryIdx];
    if (!entry || !Array.isArray(entry.tasks)) return false;
    const before = entry.tasks.length;
    entry.tasks = entry.tasks.filter(t => !(t && t.task === taskId));
    if (entry.tasks.length === before) return false;
    renumberTask(routing, taskId);
    return true;
}
function moveTask(routing, taskId, entryIdx, delta) {
    const chain = buildTaskChains(routing)[taskId] || [];
    const pos = chain.findIndex(r => r.entry === entryIdx);
    const target = pos + delta;
    if (pos < 0 || target < 0 || target >= chain.length) return false;
    const a = chain[pos], b = chain[target];
    const ta = routing[a.entry].tasks.find(t => t && t.task === taskId);
    const tb = routing[b.entry].tasks.find(t => t && t.task === taskId);
    // Give each a distinct provisional order in the swapped sequence, then renumber.
    ta.order = target + 1; tb.order = pos + 1;
    chain.forEach((r, i) => { if (i !== pos && i !== target) routing[r.entry].tasks.find(t => t && t.task === taskId).order = i + 1; });
    renumberTask(routing, taskId);
    return true;
}
function unknownAssignments(routing, knownIds) {
    const out = [];
    (routing || []).forEach((entry, idx) => {
        for (const t of ((entry && entry.tasks) || [])) {
            if (t && t.task && !knownIds.has(t.task)) out.push({ entry: idx, task: t.task });
        }
    });
    return out;
}
function entriesLosingLastAssignment(routing, entryIdx) {
    const chains = buildTaskChains(routing);
    const mine = ((routing[entryIdx] || {}).tasks || []).map(t => t && t.task).filter(Boolean);
    return mine.filter(tid => (chains[tid] || []).length === 1);
}
// <<< harness-extract:routingModel

// ── User-facing strings ────────────────────────────────────────────────
// Every string this page shows lives here, so a later i18n pass has one table
// to pick up (this admin page has no t() layer yet). English, like the rest of
// the admin UI.
const RT_TEXT = {
    title: 'LLM Routing', pageTasks: 'Tasks', pageLlms: 'LLMs', pageOverview: 'Overview',
    search: 'Search tasks…', catAll: 'all', thinking: 'thinking 🧠', onlyProblems: 'only problems',
    assignLlm: 'Assign LLM ▾', newLlm: '+ New LLM…', groupAssign: 'Assign LLM to all unassigned in this group ▾',
    noLlm: 'no LLM assigned', fallsBack: '→ falls back to', gateOff: 'feature off ({gate}) — no LLM required',
    entryDisabled: '(entry disabled)', providerMissing: 'provider "{name}" does not exist',
    notOnServer: '(not on server)', unknownTitle: 'Assignments to unknown tasks',
    unknownHint: 'These task ids are not in the catalog any more (removed or renamed). They have no effect — remove them.',
    active: 'active', preset: 'Runtime preset (not persistent):', presetNone: '— none (all tasks active) —',
    createAssign: 'Create & assign', cancel: 'Cancel', loadModels: 'Load Models', selectProvider: '— select provider —',
    selectModel: '— select —', needProviderModel: 'Provider and model are required',
    builtinEmbedding: 'built-in embedding — {model} (CPU, no LLM needed)', saveHint: 'Changes take effect after Save.',
    // Page furniture: headings, tooltips, counters.
    tasksIntro: 'One row per LLM task. A task runs on the FIRST enabled LLM of its chain; the '
              + 'others are fallbacks, in order. Tasks without an LLM are called out.',
    noMatch: 'No task matches the current filter.',
    allDisabled: 'every LLM of this chain is disabled',
    moveUp: 'Move up (earlier fallback)', moveDown: 'Move down (later fallback)',
    unassign: 'Remove this LLM from the task', remove: 'Remove',
    runtimeDisabled: 'runtime-disabled (preset)', tasksOff: 'tasks off',
    activeRuntime: 'Active: {n} tasks runtime-disabled',
    groupAssigned: '{n} task(s) assigned to {llm}', groupNone: 'Nothing to assign — no unassigned task in this group.',
    newLlmTitle: 'New LLM for this task', name: 'Name (optional)', temperature: 'Temperature',
    maxTokens: 'Max tokens (optional)', comingTask4: 'Coming in Task 4.',
    otherCategory: 'Other',
    suitabilityMoved: 'The Tool/Helper suitability test lives under Model Capabilities.',
    capabilitiesLink: 'Model Capabilities',
};

// Category order and colours — the Tasks page is grouped by category, big chat
// models on top, small helpers at the bottom. (Copied out of the old
// renderLlmTaskView, which Task 4 removes.)
const _CAT_ORDER = { chat: 0, tool: 1, helper: 2, image: 3, embedding: 4 };
const _CAT_COLORS = {
    chat:   { bg: '#1f3a5f', fg: '#79c0ff', border: '#30547a' },
    tool:   { bg: '#3a2f5f', fg: '#d2a8ff', border: '#54497a' },
    helper: { bg: '#1c3a2c', fg: '#7ee787', border: '#2d553f' },
    image:  { bg: '#5a3a1f', fg: '#ffaa66', border: '#7a543d' },
    embedding: { bg: '#3a1f4f', fg: '#c879ff', border: '#54387a' },
    '':     { bg: '#21262d', fg: '#8b949e', border: '#30363d' },
};

let RT_FILTER = { q: '', cat: '', thinking: false, problems: false };
let RT_NEW_FORM = null;   // taskId while the inline "New LLM" form is open, else null
let RT_CATALOG = null;    // last catalog seen by the renderer (for the click handlers)
// Last /admin/settings/llm-task-state response. Cached because the page
// re-renders on every keystroke in the filter box, and only applyTaskPreset()
// changes that state server-side — a direct renderLlmRoutingPage() call (the
// preset/active-toggle path in settings.js) refetches, rtRerender() reuses.
let RT_TASK_STATE = null;
let RT_KEEP_STATE = false;

// A value that ends up INSIDE an inline onclick="fn('…')": escaped for the
// single-quoted JS literal first, then for the HTML attribute. Task ids and
// categories come from the catalog, but an unknown task id comes straight out
// of the saved config — that one is genuinely user-supplied.
function rtJs(s) {
    return esc(String(s === undefined || s === null ? '' : s).replace(/\\/g, '\\\\').replace(/'/g, "\\'"));
}

// "{k}" placeholders — the strings above stay one readable sentence each.
function rtFmt(tpl, vars) {
    return String(tpl).replace(/\{(\w+)\}/g, (m, k) => (vars && vars[k] !== undefined ? String(vars[k]) : m));
}

// How one LLM entry is named everywhere on this page (chain rows, dropdowns).
function rtEntryLabel(entry, idx) {
    const e = entry || {};
    return (e.name || e.model || ('#' + (idx + 1))) + ' · ' + (e.provider || '?');
}

function rtRouting() {
    if (!Array.isArray(CONFIG.llm_routing)) CONFIG.llm_routing = [];
    return CONFIG.llm_routing;
}

// ── Page dispatch ──────────────────────────────────────────────────────
async function renderLlmRoutingPage(pageId) {
    const content = document.getElementById('content');
    if (RT_KEEP_STATE) RT_KEEP_STATE = false; else RT_TASK_STATE = null;
    const page = pageId || 'tasks';
    if (page === 'llms') return renderLlmRoutingLlmsPage(content);       // Task 4
    if (page === 'overview') return renderLlmRoutingOverviewPage(content); // Task 4
    return renderLlmRoutingTasksPage(content);
}

function renderLlmRoutingLlmsPage(content) {
    content.innerHTML = '<div class="section active"><h1 class="section-title">🔧 ' + esc(RT_TEXT.title)
        + ' — ' + esc(RT_TEXT.pageLlms) + '</h1><div class="desc">' + esc(RT_TEXT.comingTask4) + '</div></div>';
}

function renderLlmRoutingOverviewPage(content) {
    content.innerHTML = '<div class="section active"><h1 class="section-title">🔧 ' + esc(RT_TEXT.title)
        + ' — ' + esc(RT_TEXT.pageOverview) + '</h1><div class="desc">' + esc(RT_TEXT.comingTask4) + '</div></div>';
}

// Re-render the Tasks page in place. Scroll position and (for the search box)
// focus + caret survive, so typing into the filter does not fight the re-render.
async function rtRerender(msg) {
    const content = document.getElementById('content');
    const top = content ? content.scrollTop : 0;
    RT_KEEP_STATE = true;
    const act = document.activeElement;
    const focusId = act && act.id ? act.id : null;
    const caret = (act && typeof act.selectionStart === 'number') ? act.selectionStart : null;
    await renderLlmRoutingPage('tasks');
    if (content) content.scrollTop = top;
    if (focusId) {
        const el = document.getElementById(focusId);
        if (el) {
            el.focus();
            if (caret !== null && typeof el.setSelectionRange === 'function') {
                try { el.setSelectionRange(caret, caret); } catch (e) { /* not a text input */ }
            }
        }
    }
    if (msg) toast(msg, 'success');
}

// ── Tasks page ─────────────────────────────────────────────────────────
async function renderLlmRoutingTasksPage(content) {
    const catalog = await loadLlmCatalog();
    RT_CATALOG = catalog;
    const tasks = catalog.tasks || [];
    const routing = rtRouting();

    // Runtime/persistent task state (same endpoint the old per-task view used).
    if (RT_TASK_STATE === null) {
        RT_TASK_STATE = { disabled: [], runtime_disabled: [], presets: {} };
        try {
            const r = await fetch('/admin/settings/llm-task-state', { credentials: 'same-origin' });
            if (r.ok) RT_TASK_STATE = await r.json();
        } catch (e) { /* the page works without it; the toggles still edit CONFIG */ }
    }
    const state = RT_TASK_STATE;
    const persistentDisabled = new Set(((CONFIG.llm_task_state || {}).disabled_tasks || []));
    const runtimeDisabled = new Set(state.runtime_disabled || []);

    const chains = buildTaskChains(routing);
    const providerNames = new Set((CONFIG.providers || []).map(p => p && p.name).filter(Boolean));

    // One batched capability lookup for every model in any chain, BEFORE the
    // markup is built — otherwise the mismatch badges appear only on re-render.
    const capsKeys = [];
    for (const k in chains) {
        for (const row of chains[k]) {
            const e = routing[row.entry] || {};
            if (e.model) capsKeys.push(capsKeyFor(e.provider, e.model));
        }
    }
    await ensureModelCaps(capsKeys);

    // Per task: its chain rows plus everything the problem filter needs.
    const emb = CONFIG.embedding || {};
    const embBackend = emb.backend || 'auto';
    const info = {};
    for (const t of tasks) {
        const rows = (chains[t.id] || []).map(r => {
            const e = routing[r.entry] || {};
            const capsKey = e.model ? capsKeyFor(e.provider, e.model) : '';
            const match = capsKey ? evaluateRoutingMatch(t.requirements, MODEL_CAPS_CACHE[capsKey]) : { missing: [], unknown: false };
            // Only judge the model when the provider's model list is actually
            // loaded — an unloaded provider says nothing about its models.
            const known = PROVIDERS_CACHE[e.provider];
            return {
                entry: r.entry, order: r.order, cfg: e, capsKey: capsKey,
                off: e.enabled === false,
                providerMissing: !!(e.provider && !providerNames.has(e.provider)) || !e.provider,
                notOnServer: !!(known && known.length && e.model && !known.includes(e.model)),
                mismatch: (match.missing || []).length > 0,
            };
        });
        // "built-in embedding" is not a missing LLM: pose_embedding runs over
        // CONFIG.embedding (fastembed/ONNX on CPU) unless the backend is external.
        const builtinEmbedding = (t.id === 'pose_embedding' && embBackend !== 'external');
        const emptyProblem = !rows.length && !t.gated_off && !builtinEmbedding;
        const problem = emptyProblem
            || rows.some(r => r.providerMissing)
            || rows.some(r => r.mismatch)
            || (rows.length > 0 && rows.every(r => r.off));
        info[t.id] = { rows: rows, problem: problem, builtinEmbedding: builtinEmbedding };
    }

    // ── Filters ──
    const q = (RT_FILTER.q || '').trim().toLowerCase();
    const visible = tasks.filter(t => {
        if (RT_FILTER.cat && t.category !== RT_FILTER.cat) return false;
        if (RT_FILTER.thinking && !t.thinking) return false;
        if (RT_FILTER.problems && !info[t.id].problem) return false;
        if (q && !((t.label || '').toLowerCase().includes(q) || (t.id || '').toLowerCase().includes(q))) return false;
        return true;
    });
    visible.sort((a, b) => {
        const ao = _CAT_ORDER[a.category] ?? 99, bo = _CAT_ORDER[b.category] ?? 99;
        if (ao !== bo) return ao - bo;
        return (a.label || '').localeCompare(b.label || '');
    });

    const problemCount = tasks.filter(t => info[t.id].problem).length;
    const catsPresent = [];
    for (const t of tasks) if (!catsPresent.some(c => c.key === t.category)) {
        catsPresent.push({ key: t.category, label: t.category_label || RT_TEXT.otherCategory });
    }
    catsPresent.sort((a, b) => (_CAT_ORDER[a.key] ?? 99) - (_CAT_ORDER[b.key] ?? 99));

    let html = '<div class="section active">';
    html += '<h1 class="section-title">🔧 ' + esc(RT_TEXT.title) + ' — ' + esc(RT_TEXT.pageTasks) + '</h1>';
    html += '<div class="desc" style="margin-bottom:12px;">' + esc(RT_TEXT.tasksIntro) + '</div>';

    // Toolbar: search, category chips, thinking, only problems
    html += '<div class="rt-toolbar">';
    html += '<input type="text" id="rt-search" placeholder="' + esc(RT_TEXT.search) + '" value="' + esc(RT_FILTER.q) + '" '
         + 'oninput="rtSetFilter(\'q\', this.value)" style="min-width:200px;">';
    html += '<span class="rt-chip' + (RT_FILTER.cat ? '' : ' on') + '" onclick="rtSetFilter(\'cat\', \'\')">' + esc(RT_TEXT.catAll) + '</span>';
    for (const c of catsPresent) {
        const cc = _CAT_COLORS[c.key] || _CAT_COLORS[''];
        const on = RT_FILTER.cat === c.key;
        html += '<span class="rt-chip' + (on ? ' on' : '') + '" style="color:' + cc.fg + ';'
             + (on ? ' background:' + cc.bg + '; border-color:' + cc.fg + ';' : '') + '" '
             + 'onclick="rtSetFilter(\'cat\', \'' + rtJs(c.key) + '\')">' + esc(c.label) + '</span>';
    }
    html += '<span class="rt-chip' + (RT_FILTER.thinking ? ' on' : '') + '" onclick="rtSetFilter(\'thinking\', null)">' + esc(RT_TEXT.thinking) + '</span>';
    html += '<span class="rt-chip' + (RT_FILTER.problems ? ' on' : '') + '" onclick="rtSetFilter(\'problems\', null)">⚠ '
         + esc(RT_TEXT.onlyProblems) + ' (' + problemCount + ')</span>';
    html += '</div>';

    // Runtime preset (server-side, not persistent) — unchanged behaviour.
    html += '<div style="margin:10px 0; padding:8px 10px; background:#161b22; border:1px solid #30363d; border-radius:6px;">';
    html += '<div style="font-size:12px; color:#8b949e; margin-bottom:6px;">' + esc(RT_TEXT.preset) + '</div>';
    html += '<select id="rt-preset" onchange="applyTaskPreset(this.value)" style="background:#0d1117; color:#c9d1d9; border:1px solid #30363d; padding:6px; border-radius:4px; width:100%;">';
    html += '<option value="none">' + esc(RT_TEXT.presetNone) + '</option>';
    for (const p of Object.keys(state.presets || {})) {
        html += '<option value="' + esc(p) + '">' + esc(p) + ' — ' + (state.presets[p] || []).length + ' ' + esc(RT_TEXT.tasksOff) + '</option>';
    }
    html += '</select>';
    if (runtimeDisabled.size) {
        html += '<div class="rt-warn" style="font-size:11px; margin-top:4px;">' + esc(rtFmt(RT_TEXT.activeRuntime, { n: runtimeDisabled.size })) + '</div>';
    }
    html += '</div>';

    // Assignments to task ids the catalog does not know any more.
    const knownIds = new Set(tasks.map(t => t.id));
    const unknown = unknownAssignments(routing, knownIds);
    if (unknown.length) {
        html += '<div class="rt-card problem" style="margin-bottom:12px;">';
        html += '<div style="font-size:12px; font-weight:600; color:#d29922;">⚠ ' + esc(RT_TEXT.unknownTitle) + '</div>';
        html += '<div class="desc">' + esc(RT_TEXT.unknownHint) + '</div>';
        for (const u of unknown) {
            html += '<div class="rt-chain-row">';
            html += '<span class="rt-err">' + esc(u.task) + '</span>';
            html += '<span class="rt-muted">' + esc(rtEntryLabel(routing[u.entry], u.entry)) + '</span>';
            html += '<span style="margin-left:auto;"><button class="btn btn-sm" title="' + esc(RT_TEXT.remove) + '" '
                 + 'onclick="rtRemoveUnknown(' + u.entry + ', \'' + rtJs(u.task) + '\')">✕</button></span>';
            html += '</div>';
        }
        html += '</div>';
    }

    if (!visible.length) {
        html += '<div class="desc">' + esc(RT_TEXT.noMatch) + '</div>';
    }

    const labelById = {};
    for (const t of tasks) labelById[t.id] = t.label || t.id;

    let lastCat = null;
    for (const t of visible) {
        if (t.category !== lastCat) {
            lastCat = t.category;
            const cc = _CAT_COLORS[t.category] || _CAT_COLORS[''];
            html += '<div style="margin:16px 0 6px 0; display:flex; align-items:center; gap:8px; flex-wrap:wrap;">';
            html += '<div style="padding:4px 10px; background:' + cc.bg + '; color:' + cc.fg + '; '
                 + 'border-left:3px solid ' + cc.fg + '; border-radius:3px; font-size:11px; font-weight:600; '
                 + 'letter-spacing:0.3px; text-transform:uppercase;">'
                 + esc(t.category_label || RT_TEXT.otherCategory) + '</div>';
            html += rtEntrySelect('rtGroupAssign(\'' + rtJs(t.category) + '\', this.value)', RT_TEXT.groupAssign, false);
            html += '</div>';
        }

        const nfo = info[t.id];
        const cc = _CAT_COLORS[t.category] || _CAT_COLORS[''];
        const persistOff = persistentDisabled.has(t.id);
        const runtimeOff = runtimeDisabled.has(t.id);
        // The category colour rides on an inline style; a problem card keeps the
        // warning colour from .rt-card.problem, so it must NOT be overridden here.
        const style = (nfo.problem ? '' : 'border-left-color:' + cc.fg + ';')
                    + ((persistOff || runtimeOff) ? ' opacity:0.55;' : '');
        html += '<div class="rt-card' + (nfo.problem ? ' problem' : '') + '" style="' + style + '">';

        html += '<div style="display:flex; justify-content:space-between; align-items:center; gap:8px;">';
        html += '<div style="font-size:12px; color:#58a6ff; font-weight:600;">' + esc(t.label);
        if (t.category_label) {
            html += ' <span style="font-size:10px; color:' + cc.fg + '; font-weight:400; background:' + cc.bg
                 + '; padding:1px 6px; border-radius:8px; margin-left:4px;">' + esc(t.category_label) + '</span>';
        }
        if (t.thinking) html += ' <span title="runs with thinking">🧠</span>';
        html += ' <span class="rt-muted" style="font-weight:400;">— ' + esc(t.id) + '</span>';
        html += '</div>';
        html += '<label style="display:inline-flex; align-items:center; gap:4px; font-size:11px; color:#8b949e; cursor:pointer; white-space:nowrap;">';
        html += '<input type="checkbox" ' + (persistOff ? '' : 'checked') + ' onchange="toggleTaskPersistent(\'' + rtJs(t.id) + '\', !this.checked)"> '
             + esc(RT_TEXT.active) + '</label>';
        html += '</div>';

        html += renderRequirementBadges(t.requirements, catalog);
        if (runtimeOff) html += '<div class="rt-warn" style="font-size:11px;">' + esc(RT_TEXT.runtimeDisabled) + '</div>';
        if (t.gated_off) {
            html += '<div class="desc rt-muted">' + esc(rtFmt(RT_TEXT.gateOff, { gate: t.gate || '' })) + '</div>';
        }

        if (!nfo.rows.length) {
            if (nfo.builtinEmbedding) {
                html += '<div class="desc rt-ok">' + esc(rtFmt(RT_TEXT.builtinEmbedding,
                    { model: emb.internal_model || 'bge-small-en' })) + '</div>';
            } else if (!t.gated_off) {
                let line = '<div class="desc rt-warn">' + esc(RT_TEXT.noLlm);
                if (t.fallback) {
                    line += ' <span class="rt-muted">' + esc(RT_TEXT.fallsBack) + ' '
                         + esc(labelById[t.fallback] || t.fallback) + '</span>';
                }
                html += line + '</div>';
            }
        } else {
            html += '<div style="margin-top:4px;">';
            nfo.rows.forEach((r, i) => {
                html += '<div class="rt-chain-row' + (r.off ? ' off' : '') + '">';
                html += '<span class="rt-muted" style="min-width:20px;">' + r.order + '.</span>';
                html += '<span>' + esc(rtEntryLabel(r.cfg, r.entry)) + '</span>';
                if (r.off) html += '<span class="rt-warn" style="text-decoration:none;">' + esc(RT_TEXT.entryDisabled) + '</span>';
                if (r.providerMissing) {
                    html += '<span class="rt-err" style="text-decoration:none;">'
                         + esc(rtFmt(RT_TEXT.providerMissing, { name: r.cfg.provider || '?' })) + '</span>';
                }
                if (r.notOnServer) html += '<span class="rt-muted">' + esc(RT_TEXT.notOnServer) + '</span>';
                if (r.capsKey) html += renderMatchBadges(t.requirements, r.capsKey);
                html += '<span style="margin-left:auto; display:inline-flex; gap:4px;">';
                html += '<button class="btn btn-sm" title="' + esc(RT_TEXT.moveUp) + '"' + (i === 0 ? ' disabled' : '')
                     + ' onclick="rtMove(\'' + rtJs(t.id) + '\', ' + r.entry + ', -1)">↑</button>';
                html += '<button class="btn btn-sm" title="' + esc(RT_TEXT.moveDown) + '"' + (i === nfo.rows.length - 1 ? ' disabled' : '')
                     + ' onclick="rtMove(\'' + rtJs(t.id) + '\', ' + r.entry + ', 1)">↓</button>';
                html += '<button class="btn btn-sm" title="' + esc(RT_TEXT.unassign) + '"'
                     + ' onclick="rtUnassign(\'' + rtJs(t.id) + '\', ' + r.entry + ')">✕</button>';
                html += '</span>';
                html += '</div>';
            });
            if (nfo.rows.every(r => r.off)) {
                html += '<div class="desc rt-warn">' + esc(RT_TEXT.allDisabled) + '</div>';
            }
            html += '</div>';
        }

        // Assign row: pick an existing LLM or open the inline "new LLM" form.
        html += '<div style="margin-top:6px; display:flex; gap:6px; flex-wrap:wrap; align-items:center;">';
        html += rtEntrySelect('rtAssign(\'' + rtJs(t.id) + '\', this.value)', RT_TEXT.assignLlm, true,
            new Set(nfo.rows.map(r => r.entry)));
        html += '</div>';
        if (RT_NEW_FORM === t.id) html += rtNewLlmForm(t);
        html += '</div>';
    }

    // Where the capability data behind the mismatch badges is maintained.
    html += '<div class="desc" style="margin-top:16px;">🧪 ' + esc(RT_TEXT.suitabilityMoved)
         + ' <a href="/admin/models" target="_blank" style="color:#58a6ff;">' + esc(RT_TEXT.capabilitiesLink) + '</a></div>';

    html += '</div>';
    content.innerHTML = html;
}

// One <select> over CONFIG.llm_routing. `withNew` adds the "+ New LLM…" option
// (the per-task assign dropdown); the group dropdown only assigns existing ones.
// `excludeIdx` (a Set of entry indices) hides entries that are already in the
// chain of this task — picking one could only be a no-op.
function rtEntrySelect(onchangeJs, placeholder, withNew, excludeIdx) {
    const routing = rtRouting();
    let html = '<select onchange="' + onchangeJs + '" style="background:#0d1117; color:#c9d1d9; border:1px solid #30363d; padding:4px 6px; border-radius:4px; font-size:12px;">';
    html += '<option value="">' + esc(placeholder) + '</option>';
    routing.forEach((e, i) => {
        if (excludeIdx && excludeIdx.has(i)) return;
        html += '<option value="' + i + '">' + esc(rtEntryLabel(e, i)) + (e && e.enabled === false ? ' ' + esc(RT_TEXT.entryDisabled) : '') + '</option>';
    });
    if (withNew) html += '<option value="__new__">' + esc(RT_TEXT.newLlm) + '</option>';
    html += '</select>';
    return html;
}

// Inline form for a brand-new LLM entry that is assigned to `task` right away.
function rtNewLlmForm(task) {
    const providers = CONFIG.providers || [];
    const temp = LLM_SIMPLE_TEMP[task.category];
    let html = '<div class="rt-newform">';
    html += '<div style="grid-column:1 / -1; font-size:12px; color:#8b949e; font-weight:600;">' + esc(RT_TEXT.newLlmTitle) + '</div>';
    html += '<label style="font-size:11px; color:#8b949e;">' + esc(RT_TEXT.name) + '</label>';
    html += '<input type="text" id="rt-new-name">';
    html += '<label style="font-size:11px; color:#8b949e;">Provider</label>';
    html += '<select id="rt-new-provider" onchange="rtLoadModelsFor(\'rt-new-model\', this.value)">';
    html += '<option value="">' + esc(RT_TEXT.selectProvider) + '</option>';
    for (const p of providers) html += '<option value="' + esc(p.name) + '">' + esc(p.name) + ' (' + esc(p.type || '') + ')</option>';
    html += '</select>';
    html += '<label style="font-size:11px; color:#8b949e;">Model</label>';
    html += '<div style="display:flex; gap:6px;"><select id="rt-new-model" style="flex:1;"><option value="">' + esc(RT_TEXT.selectModel) + '</option></select>';
    html += '<button class="btn btn-sm" onclick="rtLoadModelsFor(\'rt-new-model\', (document.getElementById(\'rt-new-provider\')||{}).value)">'
         + esc(RT_TEXT.loadModels) + '</button></div>';
    html += '<label style="font-size:11px; color:#8b949e;">' + esc(RT_TEXT.temperature) + '</label>';
    html += '<input type="number" step="0.05" id="rt-new-temp" value="' + (temp === undefined ? 0.5 : temp) + '">';
    html += '<label style="font-size:11px; color:#8b949e;">' + esc(RT_TEXT.maxTokens) + '</label>';
    html += '<input type="number" id="rt-new-maxtok">';
    html += '<div style="grid-column:1 / -1; display:flex; gap:6px;">';
    html += '<button class="btn btn-sm" onclick="rtNewLlmCreate(\'' + rtJs(task.id) + '\')">' + esc(RT_TEXT.createAssign) + '</button>';
    html += '<button class="btn btn-sm" onclick="rtNewLlmCancel()">' + esc(RT_TEXT.cancel) + '</button>';
    html += '</div>';
    html += '</div>';
    return html;
}

// ── Click handlers (called from the inline onclick/onchange above) ──────
function rtSetFilter(kind, value) {
    if (kind === 'q') RT_FILTER.q = value || '';
    else if (kind === 'cat') RT_FILTER.cat = value || '';
    else if (kind === 'thinking') RT_FILTER.thinking = !RT_FILTER.thinking;
    else if (kind === 'problems') RT_FILTER.problems = !RT_FILTER.problems;
    rtRerender();   // no toast: a filter changes nothing that needs saving
}

function rtAssign(taskId, entryIdxOrNew) {
    if (entryIdxOrNew === '' || entryIdxOrNew === null || entryIdxOrNew === undefined) return;
    if (entryIdxOrNew === '__new__') { rtNewLlmOpen(taskId); return; }
    const idx = parseInt(entryIdxOrNew, 10);
    if (isNaN(idx)) return;
    const changed = assignTask(rtRouting(), taskId, idx);
    RT_NEW_FORM = null;
    rtRerender(changed ? RT_TEXT.saveHint : '');
}

function rtUnassign(taskId, entryIdx) {
    const changed = unassignTask(rtRouting(), taskId, entryIdx);
    rtRerender(changed ? RT_TEXT.saveHint : '');
}

function rtMove(taskId, entryIdx, delta) {
    if (!moveTask(rtRouting(), taskId, entryIdx, delta)) return;
    rtRerender(RT_TEXT.saveHint);
}

// Assigns one LLM to every task of a category that has no chain yet (gated-off
// tasks are skipped — they need no LLM).
function rtGroupAssign(category, entryIdx) {
    if (entryIdx === '' || entryIdx === null || entryIdx === undefined) return;
    const idx = parseInt(entryIdx, 10);
    if (isNaN(idx)) return;
    const routing = rtRouting();
    const catalog = RT_CATALOG || { tasks: [] };
    const chains = buildTaskChains(routing);
    let n = 0;
    for (const t of (catalog.tasks || [])) {
        if (t.category !== category) continue;
        if (t.gated_off) continue;
        if ((chains[t.id] || []).length) continue;
        if (assignTask(routing, t.id, idx)) n++;
    }
    if (!n) { rtRerender(); toast(RT_TEXT.groupNone, 'error'); return; }
    rtRerender(rtFmt(RT_TEXT.groupAssigned, { n: n, llm: rtEntryLabel(routing[idx], idx) }) + ' — ' + RT_TEXT.saveHint);
}

function rtNewLlmOpen(taskId) {
    RT_NEW_FORM = taskId;
    rtRerender();
}

function rtNewLlmCancel() {
    RT_NEW_FORM = null;
    rtRerender();
}

function rtNewLlmCreate(taskId) {
    const name = (document.getElementById('rt-new-name') || {}).value || '';
    const provider = (document.getElementById('rt-new-provider') || {}).value || '';
    const model = (document.getElementById('rt-new-model') || {}).value || '';
    const tempRaw = (document.getElementById('rt-new-temp') || {}).value;
    const maxRaw = (document.getElementById('rt-new-maxtok') || {}).value;
    if (!provider || !model) { toast(RT_TEXT.needProviderModel, 'error'); return; }
    // Unparsable numbers fall back instead of writing NaN into the config:
    // the temperature to the category default, max_tokens to "not set".
    const task = ((RT_CATALOG || {}).tasks || []).find(x => x && x.id === taskId);
    const defTemp = LLM_SIMPLE_TEMP[task ? task.category : ''];
    const temp = parseFloat(tempRaw);
    const maxTok = parseInt(maxRaw, 10);
    const entry = {
        name: name.trim(),
        enabled: true,
        preload_on_startup: false,
        provider: provider,
        model: model,
        temperature: isNaN(temp) ? (defTemp === undefined ? 0.5 : defTemp) : temp,
        tasks: [],
    };
    if (!isNaN(maxTok)) entry.max_tokens = maxTok;
    const routing = rtRouting();
    routing.push(entry);
    assignTask(routing, taskId, routing.length - 1);
    RT_NEW_FORM = null;
    rtRerender(RT_TEXT.saveHint);
}

function rtRemoveUnknown(entryIdx, taskId) {
    const changed = unassignTask(rtRouting(), taskId, entryIdx);
    rtRerender(changed ? RT_TEXT.saveHint : '');
}

// Fills a model <select> for one provider — same endpoint and the same
// PROVIDERS_CACHE / PROVIDERS_VISION fill as llmSimpleLoadModels() uses.
async function rtLoadModelsFor(selectId, provider) {
    const el = document.getElementById(selectId);
    if (!el) return;
    const cur = el.value || '';
    if (!provider) { el.innerHTML = '<option value="">' + esc(RT_TEXT.selectProvider) + '</option>'; return; }
    if (!PROVIDERS_CACHE[provider] || !PROVIDERS_CACHE[provider].length) {
        el.innerHTML = '<option>Loading…</option>';
        try {
            const resp = await fetch('/admin/settings/providers/' + encodeURIComponent(provider) + '/models', { credentials: 'same-origin' });
            const data = await resp.json();
            if (data.error) toast('Error: ' + data.error, 'error');
            const list = data.models || [];
            if (list.length) {
                PROVIDERS_CACHE[provider] = list;
                PROVIDERS_VISION[provider] = new Set(data.vision || []);
            }
        } catch (e) { toast('Failed to load models: ' + e.message, 'error'); }
    }
    const models = PROVIDERS_CACHE[provider] || [];
    const vis = PROVIDERS_VISION[provider] || new Set();
    let opts = '<option value="">' + esc(RT_TEXT.selectModel) + '</option>';
    for (const m of models) opts += '<option value="' + esc(m) + '">' + esc(m) + (vis.has(m) ? ' (vision)' : '') + '</option>';
    // A model the user already picked that the server does not list stays
    // selectable — the list may be stale, and dropping it would silently
    // change the choice.
    if (cur && !models.includes(cur)) {
        opts = '<option value="' + esc(cur) + '" selected>' + esc(cur) + ' ' + esc(RT_TEXT.notOnServer) + '</option>' + opts;
    }
    el.innerHTML = opts;
}
