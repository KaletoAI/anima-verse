
const PAGE_SIZE = 50;
let currentOffset = 0;
let totalEntries = 0;

async function loadData() {
    const character = document.getElementById('characterFilter').value;
    const backend = document.getElementById('backendFilter').value;
    const model = document.getElementById('modelFilter').value;
    const search = document.getElementById('searchInput').value;
    const errorsOnly = document.getElementById('errorsOnly').checked;

    const params = new URLSearchParams({
        limit: PAGE_SIZE, offset: currentOffset,
        character, backend, model, search,
        errors_only: errorsOnly
    });

    const resp = await fetch('/logs/image-prompts/data?' + params);
    const data = await resp.json();
    totalEntries = data.total;

    const charSel = document.getElementById('characterFilter');
    if (charSel.options.length <= 1) {
        (data.characters || []).forEach(c => {
            if (c) { const o = new Option(c, c); charSel.add(o); }
        });
    }
    const backSel = document.getElementById('backendFilter');
    if (backSel.options.length <= 1) {
        (data.backends || []).forEach(b => {
            if (b) { const o = new Option(b, b); backSel.add(o); }
        });
    }
    const modelSel = document.getElementById('modelFilter');
    if (modelSel.options.length <= 1) {
        (data.models || []).forEach(m => {
            if (m) { const o = new Option(m, m); modelSel.add(o); }
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
        const backendName = (e.backend || {}).name || '?';
        const promptPreview = (e.original_prompt || '').substring(0, 80);
        const charBadge = e.service ? `<span class="badge badge-character">${esc(e.service)}</span>` : '';
        const modelBadge = e.model ? `<span class="badge badge-model">${esc(e.model)}</span>` : '';
        const seedBadge = e.seed ? `<span class="badge badge-seed">seed:${e.seed}</span>` : '';
        const enhanceBadge = e.auto_enhance ? '<span class="badge badge-enhance">enhanced</span>' : '';
        const loraList = (e.loras || []).filter(l => l.name && l.name !== 'None');
        const loraBadge = loraList.length > 0 ? `<span class="badge badge-lora">LoRA: ${esc(loraList.map(l => l.name).join(', '))}</span>` : '';

        const errBadge = e.error ? `<span class="badge" style="background:#b62324;color:#fff;" title="${esc(e.error)}">ERROR</span>` : '';

        const div = document.createElement('div');
        div.className = e.error ? 'entry entry-error' : 'entry';
        div.innerHTML = `
            <div class="entry-header" onclick="toggleEntry(this)">
                <span class="badge badge-number">#${entryNum}</span>
                <span class="badge badge-time">${e.starttime || ''}</span>
                ${charBadge}
                <span class="badge badge-backend">${esc(backendName)}</span>
                ${modelBadge}
                ${seedBadge}
                ${enhanceBadge}
                ${loraBadge}
                ${errBadge}
                <span class="badge badge-prompt">${esc(promptPreview)}</span>
            </div>
            <div class="entry-body" id="body-${globalIdx}">
                ${buildSections(e, searchTerm)}
            </div>
        `;
        container.appendChild(div);
    });

    document.getElementById('countLabel').textContent = totalEntries + ' Eintraege';
}

function buildSections(e, st) {
    let html = '';
    if (e.error) {
        html += buildSection('⚠ Error', '<pre style="color:#ff7b72;">' + esc(e.error) + '</pre>', true);
    }
    if (e.original_prompt) {
        html += buildSection('Original Prompt', fmtText(e.original_prompt, st), true);
    }
    if (e.final_prompt && e.final_prompt !== e.original_prompt) {
        html += buildSection('Final Prompt', fmtText(e.final_prompt, st), false);
    }
    if (e.negative_prompt) {
        html += buildSection('Negative Prompt', fmtText(e.negative_prompt, st), false);
    }
    if (e.pose_prompt) {
        html += buildSection('Pose Prompt', fmtText(e.pose_prompt, st), false);
    }
    if (e.expression_prompt) {
        html += buildSection('Expression Prompt', fmtText(e.expression_prompt, st), false);
    }
    const loras = (e.loras || []).filter(l => l.name && l.name !== 'None');
    if (loras.length > 0) {
        const loraText = loras.map(l => l.name + ' (strength: ' + l.strength + ')').join('\n');
        html += buildSection('LoRAs (' + loras.length + ')', fmtText(loraText, st), false);
    }
    const apps = e.appearances || [];
    if (apps.length > 0) {
        const appText = apps.map(a => a.name + ': ' + a.appearance).join('\n');
        html += buildSection('Appearances (' + apps.length + ')', fmtText(appText, st), false);
    }
    const refs = e.reference_images || {};
    const refKeys = Object.keys(refs).filter(k => refs[k]);
    if (refKeys.length > 0) {
        const refText = refKeys.map(k => k + ': ' + refs[k]).join('\n');
        html += buildSection('Reference Images (' + refKeys.length + ')', fmtText(refText, st), false);
    }
    const ctx = e.context || {};
    if (Object.keys(ctx).length > 0) {
        html += buildSection('Context', '<pre>' + esc(JSON.stringify(ctx, null, 2)) + '</pre>', false);
    }
    // Meta
    const meta = {
        service: e.service, user_id: e.user_id,
        backend: e.backend, model: e.model, seed: e.seed || 0,
        loras: e.loras || [],
        agent_mentioned: e.agent_mentioned, auto_enhance: e.auto_enhance,
        starttime: e.starttime, endtime: e.endtime,
    };
    html += buildSection('Meta', '<pre>' + esc(JSON.stringify(meta, null, 2)) + '</pre>', false);
    return html;
}

function buildSection(title, content, startOpen) {
    const openCls = startOpen ? ' open' : '';
    return `<div class="section">
        <div class="section-header" onclick="toggleSection(this)">
            <span class="arrow${openCls}">&#9654;</span> ${title}
        </div>
        <div class="section-content${openCls}">${content}</div>
    </div>`;
}

function fmtText(text, searchTerm) {
    let s = esc(text);
    if (searchTerm) {
        const regex = new RegExp('(' + escRx(esc(searchTerm)) + ')', 'gi');
        s = s.replace(regex, '<span class="highlight">$1</span>');
    }
    return '<pre>' + s + '</pre>';
}

function esc(s) {
    if (!s) return '';
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
function escRx(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }

function toggleEntry(header) { header.nextElementSibling.classList.toggle('open'); }
function toggleSection(header) {
    header.querySelector('.arrow').classList.toggle('open');
    header.nextElementSibling.classList.toggle('open');
}

function doSearch() { currentOffset = 0; loadData(); }
function resetFilters() {
    document.getElementById('characterFilter').value = '';
    document.getElementById('backendFilter').value = '';
    document.getElementById('modelFilter').value = '';
    document.getElementById('searchInput').value = '';
    document.getElementById('errorsOnly').checked = false;
    currentOffset = 0; loadData();
}
function prevPage() { currentOffset = Math.max(0, currentOffset - PAGE_SIZE); loadData(); window.scrollTo(0,0); }
function nextPage() {
    if (currentOffset + PAGE_SIZE < totalEntries) { currentOffset += PAGE_SIZE; loadData(); window.scrollTo(0,0); }
}
function updatePager() {
    const from = totalEntries === 0 ? 0 : currentOffset + 1;
    const to = Math.min(currentOffset + PAGE_SIZE, totalEntries);
    document.getElementById('pageLabel').textContent = from + '-' + to + ' / ' + totalEntries;
    document.getElementById('prevBtn').disabled = currentOffset === 0;
    document.getElementById('nextBtn').disabled = currentOffset + PAGE_SIZE >= totalEntries;
}

document.getElementById('searchInput').addEventListener('keydown', e => { if (e.key === 'Enter') doSearch(); });
document.getElementById('characterFilter').addEventListener('change', () => { currentOffset = 0; loadData(); });
document.getElementById('backendFilter').addEventListener('change', () => { currentOffset = 0; loadData(); });
document.getElementById('modelFilter').addEventListener('change', () => { currentOffset = 0; loadData(); });
document.getElementById('errorsOnly').addEventListener('change', () => { currentOffset = 0; loadData(); });

loadData();
