
const PAGE_SIZE = 50;
let currentOffset = 0;
let totalEntries = 0;
// trace_id -> number of calls this trace has in the WHOLE log (server-side
// count over all lines, unfiltered). Needed for the "N of M calls" header
// when a filter or the page boundary hides part of a trace.
let traceTotals = {};

async function loadData() {
    const task = document.getElementById('taskFilter').value;
    const provider = document.getElementById('providerFilter').value;
    const model = document.getElementById('modelFilter').value;
    const character = document.getElementById('characterFilter').value;
    const search = document.getElementById('searchInput').value;
    const errorsOnly = document.getElementById('errorsOnly').checked;

    const params = new URLSearchParams({
        limit: PAGE_SIZE, offset: currentOffset,
        task, provider, model, character, search,
        errors_only: errorsOnly
    });

    const resp = await fetch('/logs/llm/data?' + params);
    const data = await resp.json();
    totalEntries = data.total;
    traceTotals = data.trace_totals || {};

    // Fill the filter dropdowns (only on the first load)
    const taskSel = document.getElementById('taskFilter');
    if (taskSel.options.length <= 1) {
        data.tasks.forEach(t => {
            if (t) { const o = new Option(t, t); taskSel.add(o); }
        });
    }
    const modelSel = document.getElementById('modelFilter');
    if (modelSel.options.length <= 1) {
        data.models.forEach(m => {
            if (m) { const o = new Option(m, m); modelSel.add(o); }
        });
    }
    const charSel = document.getElementById('characterFilter');
    if (charSel.options.length <= 1) {
        (data.characters || []).forEach(c => {
            if (c) { const o = new Option(c, c); charSel.add(o); }
        });
    }
    const provSel = document.getElementById('providerFilter');
    if (provSel.options.length <= 1) {
        (data.providers || []).forEach(p => {
            if (p) { const o = new Option(p, p); provSel.add(o); }
        });
    }

    renderEntries(data.entries, search);
    updatePager();
}

function renderEntries(entries, searchTerm) {
    const container = document.getElementById('entries');
    container.innerHTML = '';
    // Null-guard: with a freshly reloaded JS but a not-yet-restarted server the
    // toolbar has no groupTraces checkbox — group by default instead of throwing.
    const gtEl = document.getElementById('groupTraces');
    const grouping = !gtEl || gtEl.checked;

    // Blocks in page order (newest first) — each is either a single entry or a
    // trace group. Sorted by anchor time afterwards.
    const blocks = [];
    const groups = new Map();

    entries.forEach((e, idx) => {
        const globalIdx = currentOffset + idx;
        const entryEl = buildEntry(e, globalIdx, searchTerm);
        const tid = grouping ? (e.trace_id || '') : '';
        if (!tid) {
            // No trace id (old data, unrooted job) or grouping switched off:
            // renders exactly like before, as a single.
            blocks.push({ el: entryEl, anchor: e.starttime || '' });
            return;
        }
        let g = groups.get(tid);
        if (!g) {
            g = createTraceGroup(tid);
            groups.set(tid, g);
            blocks.push(g);
        }
        g.members.push(e);
        g.body.appendChild(entryEl);
    });

    // Fills the header and sets group.anchor = starttime of the FIRST call.
    groups.forEach((g, tid) => renderTraceHeader(g, tid));

    // Sorting stays by starttime, descending — but a group sorts at the
    // position of its FIRST call (the action's trigger), not of its last one.
    // The sort is stable, so equal timestamps keep the server's order.
    blocks.sort((a, b) => (a.anchor < b.anchor ? 1 : a.anchor > b.anchor ? -1 : 0));
    blocks.forEach(b => container.appendChild(b.el));

    document.getElementById('countLabel').textContent = totalEntries + ' entries';
}

/** Empty group shell; the header is filled once all members are known. */
function createTraceGroup(traceId) {
    const root = document.createElement('div');
    root.className = 'trace-group';
    root.dataset.traceId = traceId;
    const head = document.createElement('div');
    head.className = 'trace-header';
    head.onclick = () => toggleTrace(head);
    const body = document.createElement('div');
    body.className = 'trace-body open';
    root.appendChild(head);
    root.appendChild(body);
    return { el: root, head, body, members: [], anchor: '' };
}

/** Header line: kind, character(s), time of the first call, call count and
 *  summed duration. Members hidden by a filter or by the page boundary show
 *  up as "N of M calls" — M comes from the server-side count over the whole log.
 *  Also sets ``g.anchor`` = starttime of the first call, which is where the
 *  whole group sorts in the list. */
function renderTraceHeader(g, traceId) {
    const members = g.members;
    // The page is newest first — read the members chronologically so the
    // character that started the trace is named first, and so an entry
    // without trace_kind does not degrade the header to "trace".
    const chrono = members.slice().reverse();
    const kindMember = chrono.find(m => m.trace_kind);
    const kind = (kindMember && kindMember.trace_kind) || 'trace';
    const services = [...new Set(chrono.map(m => m.service).filter(Boolean))];
    let svcTxt = services.slice(0, 2).join(', ');
    if (services.length > 2) svcTxt += ' +' + (services.length - 2);
    const times = members.map(m => m.starttime || '').filter(Boolean).sort();
    const firstTime = times[0] || '';
    g.anchor = firstTime;
    const total = Math.max(Number(traceTotals[traceId]) || 0, members.length);
    const countTxt = total > members.length
        ? members.length + ' of ' + total + ' calls'
        : members.length + (members.length === 1 ? ' call' : ' calls');
    const sumDur = members.reduce((acc, m) => acc + (Number(m.duration_s) || 0), 0);
    const errCount = members.filter(m => m.error).length;
    if (errCount) g.el.classList.add('trace-error');

    const svcBadge = svcTxt ? `<span class="badge badge-character">${escapeHtml(svcTxt)}</span>` : '';
    const errBadge = errCount
        ? `<span class="badge" style="background:#b62324;color:#fff;">${errCount} ERROR${errCount === 1 ? '' : 'S'}</span>` : '';
    g.head.innerHTML = `
        <span class="trace-arrow open">&#9654;</span>
        <span class="badge badge-trace-kind">&#9889; ${escapeHtml(kind)}</span>
        ${svcBadge}
        <span class="badge badge-time">${escapeHtml(firstTime)}</span>
        <span class="badge badge-count">${countTxt}</span>
        <span class="badge badge-duration">&Sigma; ${sumDur.toFixed(1)}s</span>
        ${errBadge}
        <span class="badge badge-trace-id" title="Show only this trace">${escapeHtml(traceId)}</span>
    `;
    const idBadge = g.head.querySelector('.badge-trace-id');
    if (idBadge) idBadge.onclick = (ev) => { ev.stopPropagation(); isolateTrace(traceId); };
}

/** Search for the trace id — the full-text search on the server matches
 *  exactly the calls of this trace. The other filters are cleared, otherwise
 *  a character/task filter would keep hiding members of that very trace. */
function isolateTrace(traceId) {
    document.getElementById('searchInput').value = traceId;
    document.getElementById('taskFilter').value = '';
    document.getElementById('providerFilter').value = '';
    document.getElementById('modelFilter').value = '';
    document.getElementById('characterFilter').value = '';
    document.getElementById('errorsOnly').checked = false;
    currentOffset = 0;
    loadData();
}

function toggleTrace(head) {
    const arrow = head.querySelector('.trace-arrow');
    const body = head.nextElementSibling;
    if (arrow) arrow.classList.toggle('open');
    body.classList.toggle('open');
}

/** Expands a group (used by the deeplink so the affected trace is open). */
function expandTrace(root) {
    const body = root.querySelector('.trace-body');
    const arrow = root.querySelector('.trace-arrow');
    if (body) body.classList.add('open');
    if (arrow) arrow.classList.add('open');
}

/** Builds one log entry — unchanged rendering, whether single or group member. */
function buildEntry(e, globalIdx, searchTerm) {
    const entryNum = totalEntries - globalIdx;
    const tokens = e.tokens || {};
    const duration = e.duration_s ? (Number(e.duration_s) || 0).toFixed(1) + 's' : '';
    const tokenStr = (Number(tokens.input) || 0) + '/' + (Number(tokens.output) || 0);
    // Prompt tokens the backend served from its prefix cache. The field only
    // exists when the backend reported it — absent is "not reported", not 0.
    const cacheBadge = (typeof tokens.cached === 'number')
        ? `<span class="badge badge-cache" title="Prompt tokens served from the backend's prompt cache">cache ${tokens.cached}${tokens.input ? ' (' + Math.round(tokens.cached / tokens.input * 100) + '%)' : ''}</span>`
        : '';

    const div = document.createElement('div');
    div.className = 'entry';
    const charBadge = e.service ? `<span class="badge badge-character">${escapeHtml(e.service)}</span>` : '';
    const provBadge = e.provider ? `<span class="badge badge-provider">${escapeHtml(e.provider)}</span>` : '';
    const role = e.llm_role || '';
    const roleCls = role === 'Tool-LLM' ? 'badge-role-tool' : role === 'Chat-LLM' ? 'badge-role-chat' : 'badge-role';
    const roleBadge = (role && role !== e.task) ? `<span class="badge ${roleCls}">${escapeHtml(role)}</span>` : '';
    // Template basename: prefers e.template (shows which .md file was
    // rendered — makes debugging easier). Older entries without a template
    // field fall back to e.task.
    const tplName = e.template || e.task || '?';
    const tplTitle = e.template ? 'Template: ' + e.template : 'Task: ' + (e.task || '?');
    const errBadge = e.error ? `<span class="badge" style="background:#b62324;color:#fff;" title="${escapeHtml(e.error)}">ERROR</span>` : '';
    if (e.error) div.classList.add('entry-error');
    div.innerHTML = `
        <div class="entry-header" onclick="toggleEntry(this)">
            <span class="badge badge-number">#${entryNum}</span>
            <span class="badge badge-time">${escapeHtml(e.starttime || '')}</span>
            <span class="badge badge-task" title="${escapeHtml(tplTitle)}">${escapeHtml(tplName)}</span>
            ${roleBadge}
            ${charBadge}
            ${provBadge}
            <span class="badge badge-model">${escapeHtml(e.model || '?')}</span>
            <span class="badge badge-tokens">${tokenStr} tok</span>
            ${cacheBadge}
            <span class="badge badge-duration">${duration}</span>
            ${errBadge}
        </div>
        <div class="entry-body" id="body-${globalIdx}">
            ${buildSections(e, searchTerm)}
        </div>
    `;
    const body = div.querySelector('.entry-body');
    const initializeReplay = mountReplay(body, e, globalIdx, searchTerm);
    div.querySelector('.entry-header').addEventListener('click', () => {
        if (body.classList.contains('open')) initializeReplay();
    });
    return div;
}

function buildSections(e, searchTerm) {
    const prompt = e.prompt || {};
    let html = '';

    if (e.error) {
        html += buildSection('⚠ Error', '<pre style="color:#ff7b72;">' + escapeHtml(e.error) + '</pre>', true);
    }
    if (prompt.system) {
        html += buildSection('System Prompt', formatText(prompt.system, searchTerm), true);
    }
    if (Array.isArray(prompt.messages) && prompt.messages.length) {
        const title = `Conversation History (${prompt.messages.length} turns)`;
        html += buildSection(title, formatMessages(prompt.messages, searchTerm), false);
    }
    if (prompt.user) {
        html += buildSection('User / Input', formatText(prompt.user, searchTerm), !prompt.system);
    }
    html += buildSection('Responses', buildResponseCards(e, searchTerm), true);
    // Metadata
    const meta = {
        task: e.task, template: e.template || '', llm_role: e.llm_role || '',
        label: e.label || '',
        provider: e.provider, model: e.model, service: e.service,
        user_id: e.user_id,
        trace_id: e.trace_id || '', trace_kind: e.trace_kind || '',
        // Only a call that moved to another model carries it (lane overflow).
        ...(e.overflow_from ? { overflow_from: e.overflow_from } : {}),
        starttime: e.starttime, endtime: e.endtime,
        duration_s: e.duration_s, sampler: e.sampler,
        tokens: e.tokens, finish_reason: e.finish_reason
    };
    html += buildSection('Meta', '<pre>' + escapeHtml(JSON.stringify(meta, null, 2)) + '</pre>', false);

    return html;
}

function buildResponseCard(entry, title, searchTerm) {
    const meta = {
        provider: entry.provider, model: entry.model, sampler: entry.sampler,
        starttime: entry.starttime, endtime: entry.endtime, duration_s: entry.duration_s,
        tokens: entry.tokens, finish_reason: entry.finish_reason, error: entry.error || null
    };
    const tokens = entry.tokens || {};
    const summary = [
        entry.starttime || '',
        entry.duration_s != null ? Number(entry.duration_s).toFixed(2) + 's' : '',
        `${tokens.input ?? '?'} input / ${tokens.output ?? '?'} output tokens`,
        ...Object.entries(entry.sampler || {}).map(([key, value]) => key + ': ' + value),
        tokens.max != null ? 'Max output: ' + (tokens.max || 'provider default') : '',
        entry.finish_reason ? 'Finish: ' + entry.finish_reason : ''
    ].filter(Boolean).join('\n');
    return `<article class="response-card">
        <h3>${escapeHtml(title)}</h3>
        <div class="response-model" title="${escapeHtml((entry.provider || '') + ' / ' + (entry.model || ''))}">${escapeHtml(entry.provider || '?')} / ${escapeHtml(entry.model || '?')}</div>
        <pre class="response-summary">${escapeHtml(summary)}</pre>
        <details class="response-metadata"><summary>Full metadata</summary>
            <pre class="response-meta">${escapeHtml(JSON.stringify(meta, null, 2))}</pre>
        </details>
        ${entry.error ? '<pre class="response-error">' + escapeHtml(entry.error) + '</pre>' : ''}
        ${entry.response != null && entry.response !== '' ? formatText(entry.response, searchTerm) : '<p class="replay-hint">No response text was returned.</p>'}
    </article>`;
}

function buildResponseCards(entry, searchTerm) {
    return '<div class="response-grid">' + buildResponseCard(entry, 'Original response', searchTerm)
        + (entry.comparisons || []).map((comparison, index) =>
            buildResponseCard(comparison, 'Replay ' + (index + 1), searchTerm)).join('') + '</div>';
}

async function replayFetch(url, options) {
    const response = await fetch(url, options);
    const data = await response.json();
    if (!response.ok || data.error) {
        const detail = data.detail || data.error || ('HTTP ' + response.status);
        throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    }
    return data;
}

/** Mount once per entry; load provider/model choices only when it is expanded. */
function mountReplay(body, entry, index, searchTerm) {
    const panel = document.createElement('section');
    panel.className = 'replay-panel';
    const prefix = 'replay-' + index;
    if (!entry.replay_available) {
        panel.innerHTML = '<h3>Replay with another model</h3><p class="replay-hint">'
            + escapeHtml(entry.replay_unavailable_reason || 'This log entry does not contain a replayable request.') + '</p>';
        body.appendChild(panel);
        return () => {};
    }
    const sampler = entry.sampler || {};
    panel.innerHTML = `
        <h3>Replay with another model</h3>
        <p class="replay-hint" id="${prefix}-help">The request is unchanged, including its system prompt, user input and full logged history. Only the provider, model and sampling parameters change. Blank optional values use the provider default; 0 output tokens means no client limit.</p>
        <form class="replay-form" aria-describedby="${prefix}-help">
            <fieldset class="replay-fields">
                <label for="${prefix}-provider">Provider
                    <select id="${prefix}-provider" name="provider" required disabled><option value="">Loading providers…</option></select>
                </label>
                <label class="replay-model-field" for="${prefix}-model">Model
                    <input id="${prefix}-model" name="model" list="${prefix}-models" required placeholder="Select or type a model" autocomplete="off">
                    <datalist id="${prefix}-models"></datalist>
                </label>
                <label for="${prefix}-temperature">Temperature
                    <input id="${prefix}-temperature" name="temperature" type="number" min="0" step="any" required>
                </label>
                <label for="${prefix}-max-tokens">Max output tokens
                    <input id="${prefix}-max-tokens" name="max_tokens" type="number" min="0" step="1" required>
                </label>
                <label for="${prefix}-top-p">Top p (optional)
                    <input id="${prefix}-top-p" name="top_p" type="number" min="0" max="1" step="any" placeholder="Provider default">
                </label>
                <label for="${prefix}-frequency">Frequency penalty (optional)
                    <input id="${prefix}-frequency" name="frequency_penalty" type="number" step="any" placeholder="Provider default">
                </label>
            </fieldset>
            <div class="replay-actions">
                <button class="replay-run" type="submit" disabled>Run replay</button>
                <button class="replay-load" type="button">Reload providers / models</button>
            </div>
            <p class="replay-model-status replay-hint" role="status" aria-live="polite"></p>
            <p class="replay-status" role="status" aria-live="polite"></p>
        </form>`;
    body.appendChild(panel);
    const form = panel.querySelector('form');
    const fields = form.querySelector('fieldset');
    const provider = form.elements.namedItem('provider');
    const model = form.elements.namedItem('model');
    const modelList = panel.querySelector('datalist');
    const run = panel.querySelector('.replay-run');
    const reload = panel.querySelector('.replay-load');
    const status = panel.querySelector('.replay-status');
    const modelStatus = panel.querySelector('.replay-model-status');
    form.elements.namedItem('temperature').value = sampler.temperature ?? 0.7;
    form.elements.namedItem('max_tokens').value = (entry.tokens || {}).max ?? 0;
    form.elements.namedItem('top_p').value = sampler.top_p ?? '';
    form.elements.namedItem('frequency_penalty').value = sampler.frequency_penalty ?? '';
    model.value = entry.model || '';
    let initialized = false;
    let pending = false;
    let modelGeneration = 0;
    let providersLoading = false;

    function setStatus(element, message, error = false) {
        element.setAttribute('role', error ? 'alert' : 'status');
        element.classList.toggle('replay-error', error);
        element.textContent = message;
    }

    async function loadModels() {
        const generation = ++modelGeneration;
        const selected = provider.value;
        modelList.replaceChildren();
        if (!selected) {
            setStatus(modelStatus, '');
            return;
        }
        setStatus(modelStatus, 'Loading models for ' + selected + '… You can also type a model name.');
        try {
            const data = await replayFetch('/admin/settings/providers/' + encodeURIComponent(selected) + '/models');
            if (generation !== modelGeneration) return;
            (data.models || []).forEach(name => modelList.appendChild(new Option(name, name)));
            setStatus(modelStatus, (data.models || []).length
                ? 'Model suggestions loaded. You can also type a custom model name.'
                : 'No model suggestions were returned. Type a model name to continue.');
        } catch (error) {
            if (generation !== modelGeneration) return;
            setStatus(modelStatus, 'Could not load models: ' + error.message + '. Type a model name or reload the list.', true);
        }
    }

    async function loadProviders() {
        if (providersLoading || pending) return;
        providersLoading = true;
        reload.disabled = true;
        run.disabled = true;
        try {
            const data = await replayFetch('/admin/settings/providers-list');
            const selected = provider.value || entry.provider;
            provider.replaceChildren(new Option('Select a provider', ''));
            (data.providers || []).forEach(name => provider.add(new Option(name, name)));
            provider.disabled = false;
            if ([...provider.options].some(option => option.value === selected)) provider.value = selected;
            setStatus(status, data.providers && data.providers.length ? '' : 'No providers are configured.', !(data.providers || []).length);
            if (provider.value) await loadModels();
        } catch (error) {
            setStatus(status, 'Could not load providers: ' + error.message + '. Use Reload providers / models to retry.', true);
        } finally {
            providersLoading = false;
            reload.disabled = false;
            run.disabled = pending || !provider.value;
        }
    }

    provider.addEventListener('change', () => {
        model.value = provider.value === entry.provider ? (entry.model || '') : '';
        run.disabled = pending || !provider.value;
        loadModels();
    });
    reload.addEventListener('click', loadProviders);
    form.addEventListener('submit', async event => {
        event.preventDefault();
        if (pending || providersLoading || !form.reportValidity()) return;
        const nullableNumber = name => {
            const value = form.elements.namedItem(name).value;
            return value === '' ? null : Number(value);
        };
        const payload = {
            entry_id: entry.entry_id, provider: provider.value, model: model.value.trim(),
            temperature: Number(form.elements.namedItem('temperature').value),
            max_tokens: Number(form.elements.namedItem('max_tokens').value),
            top_p: nullableNumber('top_p'), frequency_penalty: nullableNumber('frequency_penalty')
        };
        if (!payload.model) {
            setStatus(status, 'Enter a model name.', true);
            model.focus();
            return;
        }
        pending = true;
        fields.disabled = true;
        run.disabled = true;
        reload.disabled = true;
        form.setAttribute('aria-busy', 'true');
        setStatus(status, 'Replay queued or running. Waiting for the provider response…');
        try {
            const data = await replayFetch('/logs/llm/replay', {
                method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
            });
            entry.comparisons = entry.comparisons || [];
            entry.comparisons.push(data.comparison);
            const grid = body.querySelector('.response-grid');
            grid.insertAdjacentHTML('beforeend', buildResponseCard(data.comparison, 'Replay ' + entry.comparisons.length, searchTerm));
            grid.parentElement.classList.add('open');
            grid.parentElement.previousElementSibling.querySelector('.arrow').classList.add('open');
            setStatus(status, data.comparison.error ? 'Replay finished with a provider error. The result was saved alongside the original response.' : 'Replay saved. Compare the responses above.', !!data.comparison.error);
        } catch (error) {
            setStatus(status, 'Replay failed: ' + error.message + '. Adjust the selection or parameters and run it again.', true);
        } finally {
            pending = false;
            fields.disabled = false;
            run.disabled = !provider.value;
            reload.disabled = false;
            form.removeAttribute('aria-busy');
        }
    });
    return () => {
        if (initialized) return;
        initialized = true;
        loadProviders();
    };
}

function buildSection(title, content, startOpen) {
    const openCls = startOpen ? ' open' : '';
    return `
        <div class="section">
            <div class="section-header" onclick="toggleSection(this)">
                <span class="arrow${openCls}">&#9654;</span> ${escapeHtml(title)}
            </div>
            <div class="section-content${openCls}">${content}</div>
        </div>
    `;
}

function formatText(text, searchTerm) {
    let escaped = escapeHtml(text);
    if (searchTerm) {
        const regex = new RegExp('(' + escapeRegex(escapeHtml(searchTerm)) + ')', 'gi');
        escaped = escaped.replace(regex, '<span class="highlight">$1</span>');
    }
    return '<pre>' + escaped + '</pre>';
}

function formatMessages(messages, searchTerm) {
    return messages.map(m => {
        const role = String((m && m.role) || 'unknown');
        const content = (m && m.content) || '';
        const cls = 'role-' + role.replace(/[^a-z0-9]/gi, '');
        return `<div class="msg-turn ${cls}">
            <div class="msg-role">${escapeHtml(role)}</div>
            ${formatText(content, searchTerm)}
        </div>`;
    }).join('');
}

function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function escapeRegex(s) {
    return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function toggleEntry(header) {
    const body = header.nextElementSibling;
    body.classList.toggle('open');
}

function toggleSection(header) {
    const arrow = header.querySelector('.arrow');
    const content = header.nextElementSibling;
    arrow.classList.toggle('open');
    content.classList.toggle('open');
}

function doSearch() {
    currentOffset = 0;
    loadData();
}

function resetFilters() {
    document.getElementById('taskFilter').value = '';
    document.getElementById('providerFilter').value = '';
    document.getElementById('modelFilter').value = '';
    document.getElementById('characterFilter').value = '';
    document.getElementById('searchInput').value = '';
    document.getElementById('errorsOnly').checked = false;
    const gtEl = document.getElementById('groupTraces');
    if (gtEl) gtEl.checked = true;
    currentOffset = 0;
    loadData();
}

function prevPage() {
    currentOffset = Math.max(0, currentOffset - PAGE_SIZE);
    loadData();
    window.scrollTo(0, 0);
}

function nextPage() {
    if (currentOffset + PAGE_SIZE < totalEntries) {
        currentOffset += PAGE_SIZE;
        loadData();
        window.scrollTo(0, 0);
    }
}

function updatePager() {
    const from = totalEntries === 0 ? 0 : currentOffset + 1;
    const to = Math.min(currentOffset + PAGE_SIZE, totalEntries);
    document.getElementById('pageLabel').textContent = from + '-' + to + ' / ' + totalEntries;
    document.getElementById('prevBtn').disabled = currentOffset === 0;
    document.getElementById('nextBtn').disabled = currentOffset + PAGE_SIZE >= totalEntries;
}

// Enter key in the search field
document.getElementById('searchInput').addEventListener('keydown', e => {
    if (e.key === 'Enter') doSearch();
});

// Filter changes
document.getElementById('taskFilter').addEventListener('change', () => { currentOffset = 0; loadData(); });
document.getElementById('modelFilter').addEventListener('change', () => { currentOffset = 0; loadData(); });
document.getElementById('characterFilter').addEventListener('change', () => { currentOffset = 0; loadData(); });
document.getElementById('providerFilter').addEventListener('change', () => { currentOffset = 0; loadData(); });
document.getElementById('errorsOnly').addEventListener('change', () => { currentOffset = 0; loadData(); });
// Grouping is a pure view switch — same page, only rendered differently.
// Guarded like the read sites: the checkbox is missing until the server, which
// renders the toolbar, has been restarted. Without the guard this top-level
// call would throw and abort the whole script (including the initial load).
const _groupTracesEl = document.getElementById('groupTraces');
if (_groupTracesEl) _groupTracesEl.addEventListener('change', () => loadData());

// Take URL params into the filter fields so deeplinks (e.g. from the
// agent-loop admin: /logs/llm?character=X&search=YYYY-MM-DD HH:MM) show the
// list pre-filtered AND expand the first matching entry — including the
// trace group it belongs to.
(function applyUrlParams() {
    try {
        const params = new URLSearchParams(window.location.search);
        const ch = params.get('character') || '';
        const tk = params.get('task') || '';
        const md = params.get('model') || '';
        const sr = params.get('search') || '';
        if (sr) document.getElementById('searchInput').value = sr;
        // The character/task/model selects only get their options after
        // loadData — the value is applied after the first render.
        window.__pendingPreselect = { ch, tk, md, search: sr };
    } catch (_) {}
})();

// Hook: after each render, check whether a pending preselect still has to be
// applied + auto-expand the first match.
const _origLoadData = loadData;
loadData = async function() {
    await _origLoadData.apply(this, arguments);
    const pre = window.__pendingPreselect;
    if (pre) {
        let needsReload = false;
        const setIf = (id, val) => {
            if (!val) return false;
            const el = document.getElementById(id);
            if (!el) return false;
            // Check whether the value exists in the options — add it otherwise
            let exists = false;
            for (const o of el.options) { if (o.value === val) { exists = true; break; } }
            if (!exists) el.add(new Option(val, val));
            if (el.value !== val) { el.value = val; return true; }
            return false;
        };
        needsReload |= setIf('characterFilter', pre.ch);
        needsReload |= setIf('taskFilter', pre.tk);
        needsReload |= setIf('modelFilter', pre.md);
        if (needsReload) {
            window.__pendingPreselect = null;
            currentOffset = 0;
            await _origLoadData();
        } else {
            window.__pendingPreselect = null;
        }
        // Auto-expand the first entry (if visible after filtering). Inside a
        // trace group the group is opened first, so the entry is really shown.
        const firstEntry = document.querySelector('.entries .entry');
        if (firstEntry) {
            const group = firstEntry.closest('.trace-group');
            if (group) expandTrace(group);
            const header = firstEntry.querySelector('.entry-header');
            if (header) header.click();
            (group || firstEntry).scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    }
};

// Initial load
loadData();
