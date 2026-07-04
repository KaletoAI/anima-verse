
const PAGE_SIZE = 50;
let currentOffset = 0;
let totalEntries = 0;

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

    // Filter-Dropdowns befuellen (nur beim ersten Mal)
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

    entries.forEach((e, idx) => {
        const globalIdx = currentOffset + idx;
        const entryNum = totalEntries - globalIdx;
        const tokens = e.tokens || {};
        const duration = e.duration_s ? e.duration_s.toFixed(1) + 's' : '';
        const tokenStr = (tokens.input || 0) + '/' + (tokens.output || 0);

        const div = document.createElement('div');
        div.className = 'entry';
        const charBadge = e.service ? `<span class="badge badge-character">${escapeHtml(e.service)}</span>` : '';
        const provBadge = e.provider ? `<span class="badge badge-provider">${escapeHtml(e.provider)}</span>` : '';
        const role = e.llm_role || '';
        const roleCls = role === 'Tool-LLM' ? 'badge-role-tool' : role === 'Chat-LLM' ? 'badge-role-chat' : 'badge-role';
        const roleBadge = (role && role !== e.task) ? `<span class="badge ${roleCls}">${escapeHtml(role)}</span>` : '';
        // Template-Basename: bevorzugt e.template (zeigt welche .md-Datei
        // gerendert wurde — erleichtert Fehlersuche). Bei aelteren Eintraegen
        // ohne template-Feld faellt es auf e.task zurueck.
        const tplName = e.template || e.task || '?';
        const tplTitle = e.template ? 'Template: ' + e.template : 'Task: ' + (e.task || '?');
        const errBadge = e.error ? `<span class="badge" style="background:#b62324;color:#fff;" title="${escapeHtml(e.error)}">ERROR</span>` : '';
        if (e.error) div.classList.add('entry-error');
        div.innerHTML = `
            <div class="entry-header" onclick="toggleEntry(this)">
                <span class="badge badge-number">#${entryNum}</span>
                <span class="badge badge-time">${e.starttime || ''}</span>
                <span class="badge badge-task" title="${escapeHtml(tplTitle)}">${escapeHtml(tplName)}</span>
                ${roleBadge}
                ${charBadge}
                ${provBadge}
                <span class="badge badge-model">${e.model || '?'}</span>
                <span class="badge badge-tokens">${tokenStr} tok</span>
                <span class="badge badge-duration">${duration}</span>
                ${errBadge}
            </div>
            <div class="entry-body" id="body-${globalIdx}">
                ${buildSections(e, searchTerm)}
            </div>
        `;
        container.appendChild(div);
    });

    document.getElementById('countLabel').textContent = totalEntries + ' Eintraege';
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
    if (e.response) {
        html += buildSection('Response', formatText(e.response, searchTerm), false);
    }
    // Meta-Daten
    const meta = {
        task: e.task, template: e.template || '', llm_role: e.llm_role || '',
        model: e.model, service: e.service,
        user_id: e.user_id,
        starttime: e.starttime, endtime: e.endtime,
        duration_s: e.duration_s,
        tokens: e.tokens
    };
    html += buildSection('Meta', '<pre>' + escapeHtml(JSON.stringify(meta, null, 2)) + '</pre>', false);

    return html;
}

function buildSection(title, content, startOpen) {
    const openCls = startOpen ? ' open' : '';
    return `
        <div class="section">
            <div class="section-header" onclick="toggleSection(this)">
                <span class="arrow${openCls}">&#9654;</span> ${title}
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
        const role = (m && m.role) || 'unknown';
        const content = (m && m.content) || '';
        const cls = 'role-' + role.replace(/[^a-z0-9]/gi, '');
        return `<div class="msg-turn ${cls}">
            <div class="msg-role">${escapeHtml(role)}</div>
            ${formatText(content, searchTerm)}
        </div>`;
    }).join('');
}

function escapeHtml(s) {
    if (!s) return '';
    return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
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

// Enter-Taste in Suchfeld
document.getElementById('searchInput').addEventListener('keydown', e => {
    if (e.key === 'Enter') doSearch();
});

// Filter-Aenderungen
document.getElementById('taskFilter').addEventListener('change', () => { currentOffset = 0; loadData(); });
document.getElementById('modelFilter').addEventListener('change', () => { currentOffset = 0; loadData(); });
document.getElementById('characterFilter').addEventListener('change', () => { currentOffset = 0; loadData(); });
document.getElementById('providerFilter').addEventListener('change', () => { currentOffset = 0; loadData(); });
document.getElementById('errorsOnly').addEventListener('change', () => { currentOffset = 0; loadData(); });

// URL-Params -> Filter-Felder uebernehmen, damit Deep-Links (z.B. vom
// Agent-Loop-Admin: /logs/llm?character=X&search=YYYY-MM-DD HH:MM)
// die Liste vorgefiltert anzeigen UND den ersten passenden Eintrag
// automatisch aufklappen.
(function applyUrlParams() {
    try {
        const params = new URLSearchParams(window.location.search);
        const ch = params.get('character') || '';
        const tk = params.get('task') || '';
        const md = params.get('model') || '';
        const sr = params.get('search') || '';
        if (sr) document.getElementById('searchInput').value = sr;
        // Character/Task/Model-Selects werden erst nach loadData mit Optionen
        // befuellt — wir setzen den Wert nach dem ersten Render via Watch.
        window.__pendingPreselect = { ch, tk, md, search: sr };
    } catch (_) {}
})();

// Hook: nach jedem Render pruefen ob noch ein Pending-Preselect zu
// applizieren ist + den ersten Match auto-expand.
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
            // Pruefen ob Wert in Options vorhanden ist — sonst Option anlegen
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
        // Ersten Eintrag auto-expand (wenn nach Filterung sichtbar)
        const firstEntry = document.querySelector('.entries .entry .entry-header');
        if (firstEntry) {
            firstEntry.click();
            firstEntry.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    }
};

// Initial laden
loadData();
