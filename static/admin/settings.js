
let CONFIG = {};
let CONFIG_REVISION = null;
let LORA_ENTRIES = [];
const RESETS = new Set();
let SCHEMA = {};
let OVERRIDES = new Set();
let SHIPPED = {};
let DIRTY = false;
let MUTATION_REVISION = 0;
let ONLY_OVERRIDES = false;
try { ONLY_OVERRIDES = localStorage.getItem('settings-only-overrides') === 'true'; } catch (e) { /* storage unavailable */ }
let PROVIDERS_CACHE = {};
let PROVIDERS_VISION = {};  // provName -> Set(vision model names)
// Runtime state of the media backends (name -> {available, cooldown_seconds,
// cooldown_reason, ...}) — merged into the backends table's Status column.
let MEDIA_STATUS = {};
let ACTIVE_SECTION = null;
// Page id inside a paged section (schema key `pages`), null for sections
// without paging. Kept across renderSection() rerenders so an edit on the
// "Blender" page does not throw the user back to "General".
let ACTIVE_PAGE = null;
// When the user expands an array item we keep its path here, so the state
// survives renderSection() rerenders (e.g. after an api_type change via
// triggers_rerender).
const OPEN_ITEMS = new Set();
// Master-detail: the currently selected item path per sub-array path.
const SELECTED_ITEM = {};
function toggleArrayItem(el, path) {
    const isOpen = el.parentElement.classList.toggle('open');
    if (isOpen) OPEN_ITEMS.add(path);
    else OPEN_ITEMS.delete(path);
}

// ── Init ──
async function init() {
    try {
        const [dataResp, schemaResp, originResp, shippedResp] = await Promise.all([
            fetch('/admin/settings/raw', { credentials: 'same-origin' }),
            fetch('/admin/settings/schema', { credentials: 'same-origin' }),
            fetch('/admin/settings/origin', { credentials: 'same-origin' }),
            fetch('/admin/settings/shipped-defaults', { credentials: 'same-origin' })
        ]);
        if (dataResp.status === 401 || dataResp.status === 403) {
            const ret = encodeURIComponent(window.location.pathname + window.location.hash);
            window.location.href = '/?return=' + ret;
            return;
        }
        for (const response of [dataResp, schemaResp, originResp, shippedResp]) {
            if (!response.ok) throw new Error('HTTP ' + response.status);
        }
        CONFIG = await dataResp.json();
        CONFIG_REVISION = dataResp.headers.get('X-Config-Revision');
        SCHEMA = await schemaResp.json();
        OVERRIDES = new Set((await originResp.json()).overrides || []);
        SHIPPED = await shippedResp.json();
        document.getElementById('only-overrides').checked = ONLY_OVERRIDES;
        await loadMediaStatus();
        buildNav();
        // Restore the section/page from the URL hash, else the first section.
        const fromHash = parseHash();
        if (fromHash) activateSection(fromHash.section, fromHash.page);
        else {
            const first = Object.keys(SCHEMA)[0];
            if (first) activateSection(first);
        }
        // Restart banner: after init, check whether anything is pending (e.g.
        // when another tab saved recently).
        loadRestartPending();
    } catch (e) {
        document.getElementById('content').innerHTML = '<div class="loading" style="color:#f85149;">Error loading config: ' + esc(e.message) + '</div>';
    }
}

function authHeaders() {
    // Cookie-based: the browser sends the session cookie itself. Only set Content-Type explicitly.
    return { 'Content-Type': 'application/json' };
}

// ── Navigation ──
// Nav/hash key of one entry: "<section>" or "<section>/<page>" for a paged
// section (schema key `pages`).
function navKey(key, pageId) {
    return pageId ? key + '/' + pageId : key;
}

// Reads "#section" / "#section/page" / "#section::subarray" from the URL and
// returns it only when the section actually exists in the schema.
function parseHash() {
    const raw = decodeURIComponent((window.location.hash || '').replace(/^#/, ''));
    if (!raw) return null;
    const slash = raw.indexOf('/');
    const section = slash === -1 ? raw : raw.slice(0, slash);
    const page = slash === -1 ? null : raw.slice(slash + 1);
    const base = section.indexOf('::') !== -1 ? section.slice(0, section.indexOf('::')) : section;
    if (!SCHEMA[base] && section !== 'shipped_defaults') return null;
    return { section: section, page: page || null };
}

// Keeps the URL in sync WITHOUT adding a history entry (and without firing a
// hashchange), so a reload lands on the same section/page.
function syncHash(key, pageId) {
    const want = '#' + navKey(key, pageId);
    if (window.location.hash === want) return;
    try { history.replaceState(null, '', want); }
    catch (e) { window.location.hash = want; }
}

// Pages of a paged section, with every field/sub_array the pages forgot
// appended to the FIRST page — a newly added schema field is never invisible.
function resolvePages(sec) {
    const pages = (sec.pages || []).map(p => ({
        id: p.id,
        label: p.label || p.id,
        icon: p.icon || '',
        description: p.description || '',
        fields: (p.fields || []).slice(),
        sub_arrays: (p.sub_arrays || []).slice()
    }));
    if (!pages.length) return pages;
    const usedF = new Set(), usedA = new Set();
    for (const p of pages) {
        p.fields.forEach(f => usedF.add(f));
        p.sub_arrays.forEach(a => usedA.add(a));
    }
    for (const k of Object.keys(sec.fields || {})) if (!usedF.has(k)) pages[0].fields.push(k);
    for (const k of Object.keys(sec.sub_arrays || {})) if (!usedA.has(k)) pages[0].sub_arrays.push(k);
    return pages;
}

function isPaged(sec) {
    return !!(sec && Array.isArray(sec.pages) && sec.pages.length);
}

function buildNav() {
    const nav = document.getElementById('nav-links');
    nav.innerHTML = '';
    for (const [key, sec] of Object.entries(SCHEMA)) {
        if (ONLY_OVERRIDES && !sectionHasOverride(key)) continue;
        const a = document.createElement('a');
        a.href = '#' + key;
        // nav_sub keeps subordinate sections such as game_seasons indented.
        if (sec.nav_sub) {
            a.className = 'nav-sub';
            a.innerHTML = '<span class="nav-icon">›</span> ' + esc(sec.label);
        } else {
            a.innerHTML = '<span class="nav-icon">' + esc(sec.icon || '') + '</span> ' + esc(sec.label);
        }
        a.dataset.section = key;
        a.onclick = (e) => { e.preventDefault(); activateSection(key); };
        nav.appendChild(a);
        // Paged section: one indented entry per page (same look as nav_sub).
        // The parent entry opens the first page; the pages own the section's
        // sub_arrays too, so the generic sub-array entries below are skipped.
        if (isPaged(sec)) {
            for (const page of resolvePages(sec)) {
                if (ONLY_OVERRIDES && !pageHasOverride(key, sec, page)) continue;
                const pa = document.createElement('a');
                pa.className = 'nav-sub';
                pa.href = '#' + navKey(key, page.id);
                pa.innerHTML = '<span class="nav-icon">›</span> ' + esc(page.label);
                pa.dataset.section = navKey(key, page.id);
                pa.onclick = (e) => { e.preventDefault(); activateSection(key, page.id); };
                nav.appendChild(pa);
            }
            continue;
        }
        // Sub-arrays (e.g. backends) as indented sub-items — each gets its
        // own page (key "<sec>::<arr>").
        if (sec.sub_arrays) {
            for (const [arrKey, arrDef] of Object.entries(sec.sub_arrays)) {
                if (ONLY_OVERRIDES && originOf(key + '.' + arrKey) !== 'instance') continue;
                const subKey = key + '::' + arrKey;
                const sa = document.createElement('a');
                sa.className = 'nav-sub';
                sa.href = '#' + subKey;
                sa.innerHTML = '<span class="nav-icon">›</span> ' + esc(arrDef.label);
                sa.dataset.section = subKey;
                sa.onclick = (e) => { e.preventDefault(); activateSection(subKey); };
                nav.appendChild(sa);
            }
        }
    }
    const defaults = document.createElement('a');
    defaults.href = '#shipped_defaults';
    defaults.dataset.section = 'shipped_defaults';
    defaults.textContent = 'Shipped defaults';
    defaults.onclick = e => { e.preventDefault(); activateSection('shipped_defaults'); };
    nav.appendChild(defaults);
    nav.querySelectorAll('a').forEach(link => {
        link.classList.toggle('active', link.dataset.section === navKey(ACTIVE_SECTION, ACTIVE_PAGE));
    });
}

function activateSection(key, pageId) {
    const special = key === 'shipped_defaults' ||
        (key.includes('::') && SCHEMA[key.split('::')[0]]?.sub_arrays?.[key.split('::')[1]]);
    const sec = SCHEMA[key];
    if (!sec && !special) return;
    ACTIVE_SECTION = key;
    // Paged section: fall back to the first page (parent nav entry, or a hash
    // naming a page that no longer exists).
    if (sec && isPaged(sec)) {
        const pages = resolvePages(sec).filter(p => !ONLY_OVERRIDES || pageHasOverride(key, sec, p));
        const hit = pages.find(p => p.id === pageId);
        ACTIVE_PAGE = hit ? hit.id : (pages[0] ? pages[0].id : null);
    } else {
        ACTIVE_PAGE = null;
    }
    // Update nav — for a paged section the PAGE entry is the active one.
    document.querySelectorAll('.sidebar a').forEach(a => a.classList.remove('active'));
    const link = document.querySelector('.sidebar a[data-section="' + navKey(key, ACTIVE_PAGE) + '"]');
    if (link) link.classList.add('active');
    syncHash(key, ACTIVE_PAGE);
    // Show settings toolbar, restore content mode
    document.getElementById('settings-toolbar').style.display = 'flex';
    const content = document.getElementById('content');
    content.classList.remove('iframe-mode');
    // Render section
    renderSection(key, ACTIVE_PAGE);
}

function activateIframe(key, url, title) {
    ACTIVE_SECTION = key;
    ACTIVE_PAGE = null;
    // Update nav
    document.querySelectorAll('.sidebar a').forEach(a => a.classList.remove('active'));
    const link = document.querySelector('.sidebar a[data-section="' + key + '"]');
    if (link) link.classList.add('active');
    // Hide settings toolbar
    document.getElementById('settings-toolbar').style.display = 'none';
    // Load iframe
    const content = document.getElementById('content');
    content.classList.add('iframe-mode');
    content.innerHTML = '<iframe src="' + esc(safeUrl(url)) + '" title="' + esc(title) + '"></iframe>';
}

// ── Render Section ──
function renderLoraTriggersEditor() {
    const items = LORA_ENTRIES;
    let html = '<p class="hint" style="opacity:.7;margin-bottom:12px">'
             + 'Changes here are saved immediately.</p><p class="hint">Central LoRA library of the instance — <b>every LoRA dropdown</b> (game admin + player UI) '
             + 'feeds from this list, scoped to the selected backend. One entry per LoRA with the backends '
             + 'that have it; one activation word per LoRA: whenever an image uses the LoRA, '
             + 'the word is automatically prepended to the prompt.</p>';
    html += '<p class="hint" style="opacity:.7;margin-bottom:12px">'
             + 'Backends with a <b>LoRA Query URL</b> are scanned automatically (hourly + on '
             + '<b>Discover now</b>): found LoRAs are added as <b>discovered</b>; a backend whose LoRA '
             + 'vanished is dropped from the entry (discovered, untouched) or flagged '
             + '<b style="color:#f85149">missing</b> (manual / edited) — missing entries stay offered '
             + 'in the dialogs, marked "(missing)". Backends without a listing (CivitAI, Together): '
             + 'add entries manually; no backend assigned = offered on all backends.</p>';
    html += '<div style="margin-bottom:12px;display:flex;gap:8px">'
          + '<button class="btn btn-sm" onclick="addLoraTrigger()">+ Add</button>'
          + '<button class="btn btn-sm" onclick="syncLoraLibrary()">⟳ Discover now</button>'
          + '<button class="btn btn-sm btn-danger" onclick="clearDiscoveredLoras()">🗑 Delete discovered</button></div>';
    if (!items.length) {
        html += '<div class="md-empty">No entries yet. "Discover now" scans the backends; "+ Add" creates a manual entry.</div>';
    }
    for (let i = 0; i < items.length; i++) {
        const it = items[i] || {};
        const ip = String(i);
        const isManual = (it.source || 'manual') !== 'discovered';
        const backends = Array.isArray(it.backends) ? it.backends : [];
        const missingOn = Array.isArray(it.missing_on) ? it.missing_on : [];
        html += '<div class="lora-row" style="display:flex;gap:8px;align-items:flex-start;margin-bottom:6px">';
        // Column 1: LoRA name (free text; renaming a discovered entry makes
        // it a manual claim — ltRename also warns on duplicate names).
        html += '<input type="text" autocomplete="off" value="' + esc(it.lora || '') + '" '
              + 'placeholder="LoRA name (as the backend lists it)" style="flex:3;min-width:0" '
              + 'onchange="ltRename(\'' + sJs(ip) + '\', this)">';
        // Column 2: activation word.
        html += '<input type="text" value="' + esc(it.word || '') + '" placeholder="Activation word" '
              + 'style="flex:2;min-width:0" onchange="ltTouch(\'' + sJs(ip) + '\', \'word\', this.value)">';
        // Column 3: backend associations. Discovered entries: sync-owned,
        // read-only. Manual entries: editable chips; empty = all backends.
        html += '<div style="flex:3;min-width:0;display:flex;flex-wrap:wrap;gap:4px;align-items:center;padding-top:4px">';
        if (!backends.length) {
            html += '<span class="badge" style="font-size:10px;opacity:.7" '
                  + 'title="Offered on every backend (each backend\'s LoRA filter still applies)">all backends</span>';
        }
        for (const bn of backends) {
            const miss = missingOn.indexOf(bn) !== -1;
            html += '<span class="badge" style="font-size:10px;'
                  + (miss ? 'background:#5a1e1e;color:#f85149;text-decoration:line-through;'
                          : 'background:#1f3a5f;color:#79c0ff;')
                  + '" title="' + (miss ? 'The backend no longer lists this LoRA — still offered, marked (missing)'
                                        : 'This backend has the LoRA') + '">'
                  + esc(bn)
                  + (isManual ? ' <a style="cursor:pointer;text-decoration:none" title="Remove backend" '
                              + 'onclick="ltRemoveBackend(\'' + sJs(ip) + '\', \'' + sJs(bn) + '\')">✕</a>' : '')
                  + '</span>';
        }
        if (isManual) {
            let opts = '';
            for (const be of ((CONFIG.image_generation && CONFIG.image_generation.backends) || [])) {
                const bn = be.name || '';
                if (bn && backends.indexOf(bn) === -1) {
                    opts += '<option value="' + esc(bn) + '">' + esc(bn) + '</option>';
                }
            }
            if (opts) {
                html += '<select title="Assign a backend" style="font-size:10px;background:#0d1117;color:#c9d1d9;border:1px solid #30363d;border-radius:6px;padding:2px 4px" '
                      + 'onchange="ltAddBackend(\'' + sJs(ip) + '\', this.value)">'
                      + '<option value="">+ backend…</option>' + opts + '</select>';
            }
        }
        html += '</div>';
        // Column 4: origin badge.
        const src = isManual ? 'manual' : 'discovered';
        html += '<span style="flex:0 0 auto;padding-top:4px">'
              + '<span class="badge" title="' + (src === 'discovered' ? 'Found by the backend scan' : 'Created/edited by hand') + '" '
              + 'style="font-size:10px;' + (src === 'discovered' ? 'background:#1f3a5f;color:#79c0ff;' : '') + '">' + src + '</span>'
              + '</span>';
        html += '<button class="btn btn-sm btn-danger" title="Delete" onclick="ltDelete(\'' + sJs(ip) + '\')">✕</button>';
        html += '</div>';
    }
    return html;
}

// The library never participates in CONFIG or the settings save lifecycle.
async function loraRequest(suffix = '', method = 'GET', body) {
    const resp = await fetch('/admin/settings/lora-library' + suffix, {
        method, headers: authHeaders(),
        ...(body === undefined ? {} : {body: JSON.stringify(body)}),
    });
    const data = await resp.json();
    if (!resp.ok) {
        const detail = data && data.detail;
        throw new Error((detail && detail.message) || detail || ('HTTP ' + resp.status));
    }
    return data;
}

async function loadLoraLibrary() {
    try {
        LORA_ENTRIES = (await loraRequest()).entries;
        return true;
    } catch (e) {
        toast('LoRA library: ' + e.message, 'error');
        return false;
    }
}

async function loraAction(suffix, method, body) {
    try {
        const data = await loraRequest(suffix, method, body);
        if (data.entries) LORA_ENTRIES = data.entries;
        else if (data.entry) {
            const index = LORA_ENTRIES.findIndex(e => e.lora === body.lora);
            if (index === -1) LORA_ENTRIES.push(data.entry);
            else LORA_ENTRIES[index] = data.entry;
        } else if (data.deleted) {
            LORA_ENTRIES = LORA_ENTRIES.filter(e => e.lora !== body.lora);
        }
        renderSection(ACTIVE_SECTION, ACTIVE_PAGE, false);
        return data;
    } catch (e) {
        toast('LoRA library: ' + e.message, 'error');
        renderSection(ACTIVE_SECTION, ACTIVE_PAGE, false);
        return null;
    }
}

async function addLoraTrigger() {
    const name = await askText('LoRA name (as the backend lists it):', '');
    if (name === null || !name.trim()) return;
    await loraAction('/entry', 'POST', {lora: name.trim()});
}

function ltAddBackend(index, name) {
    if (!name) return;
    const e = LORA_ENTRIES[index];
    return loraAction('/entry', 'PATCH', {lora: e.lora, backends: [...new Set([...(e.backends || []), name])]});
}

function ltRemoveBackend(index, name) {
    const e = LORA_ENTRIES[index];
    return loraAction('/entry', 'PATCH', {lora: e.lora, backends: (e.backends || []).filter(b => b !== name)});
}

function ltRename(index, input) {
    return ltTouch(index, 'rename_to', input.value);
}

function ltTouch(index, field, value) {
    const e = LORA_ENTRIES[index];
    if ((field === 'rename_to' ? e.lora : e[field]) === value) return;
    return loraAction('/entry', 'PATCH', {lora: e.lora, [field]: value});
}

// Library edits are saved at once, so the destructive ones ask first.
async function ltDelete(index) {
    const name = LORA_ENTRIES[index].lora;
    if (!await askConfirm('Delete the LoRA entry "' + name + '"?', 'Delete')) return;
    return loraAction('/entry/delete', 'POST', {lora: name});
}

async function clearDiscoveredLoras() {
    if (!await askConfirm('Delete every discovered LoRA entry? Manual entries stay.', 'Delete')) return;
    const data = await loraAction('/clear-discovered', 'POST');
    if (data) toast('Removed ' + data.removed + ' discovered entries', 'success');
}

async function syncLoraLibrary() {
    const data = await loraAction('/sync', 'POST');
    if (data) toast('LoRA sync: ' + data.scanned.length + ' backend(s) scanned — '
        + data.added + ' added, ' + data.removed + ' removed, ' + data.missing + ' missing', 'success');
}

async function renderSection(key, pageId, reloadLibrary = true) {
    const hint = document.getElementById('providers-hint');
    if (hint) hint.hidden = (CONFIG.providers || []).length > 0;
    if (!key) return;
    if (key === 'shipped_defaults') {
        document.getElementById('content').innerHTML = '<div class="section active"><h1 class="section-title">Shipped defaults</h1><pre id="shipped-pre"></pre></div>';
        document.getElementById('shipped-pre').textContent = JSON.stringify(SHIPPED, null, 2);
        return;
    }
    if (ONLY_OVERRIDES && !sectionHasOverride(key)) {
        document.getElementById('content').innerHTML = '<div class="section active"><p>No overrides on this page.</p></div>';
        return;
    }
    // Compound key "<section>::<subArray>" opens its own sub-array page.
    if (key.indexOf('::') !== -1) {
        const [parent, arr] = key.split('::');
        if (reloadLibrary && SCHEMA[parent]?.sub_arrays?.[arr]?.lora_triggers_editor) {
            if (!await loadLoraLibrary() || ACTIVE_SECTION !== key) return;
        }
        renderSubArrayPage(key); return;
    }
    // Task-centric LLM routing editor — its own file (settings-routing.js),
    // loaded after this one, renders all three pages of the section.
    if (key === 'llm_routing') {
        await renderLlmRoutingPage(pageId === undefined || pageId === null
            ? (key === ACTIVE_SECTION ? ACTIVE_PAGE : null)
            : pageId);
        return;
    }
    // Decision models — its own file (settings-decision.js) renders the
    // Points and Shadow pages and adds the test panel to Endpoints.
    if (key === 'decision') {
        await renderDecisionPage(pageId === undefined || pageId === null
            ? (key === ACTIVE_SECTION ? ACTIVE_PAGE : null)
            : pageId);
        return;
    }
    // Image routing — its own file (settings-image-routing.js) renders the
    // two custom pages of the Media Generation section.
    if (key === 'image_generation') {
        const want = (pageId === undefined || pageId === null)
            ? (key === ACTIVE_SECTION ? ACTIVE_PAGE : null) : pageId;
        if (want === 'routing' || want === 'routing_overview') {
            await renderImageRoutingPage(want);
            return;
        }
    }
    const sec = SCHEMA[key];
    if (!sec) return;
    const loraPage = (pageId == null ? ACTIVE_PAGE : pageId);
    const page = isPaged(sec) && resolvePages(sec).find(p => p.id === loraPage);
    if (reloadLibrary && page && page.sub_arrays.some(k => sec.sub_arrays[k]?.lora_triggers_editor)) {
        if (!await loadLoraLibrary()) return;
        if (ACTIVE_SECTION !== key || ACTIVE_PAGE !== loraPage) return;
    }
    // Paged section: the many renderSection(ACTIVE_SECTION) rerenders (field
    // edits, array add/remove) pass no page — stay on the current one.
    if (isPaged(sec)) {
        const want = (pageId === undefined || pageId === null)
            ? (key === ACTIVE_SECTION ? ACTIVE_PAGE : null)
            : pageId;
        renderPagedSection(key, want);
        return;
    }
    // Let both null and undefined fall back to the default — otherwise
    // renderFields(null, ...) throws a TypeError at data[fKey].
    const cfgVal = CONFIG[key];
    const data = (cfgVal !== undefined && cfgVal !== null) ? cfgVal : (sec.is_array ? [] : {});
    const content = document.getElementById('content');

    let html = '<div class="section active">';
    html += '<h1 class="section-title">' + esc(sec.icon || '') + ' ' + esc(sec.label) + '</h1>';
    // Section-level description (what the whole section is for) — array
    // sections have no top-level fields to hang a note on.
    if (sec.description) html += '<div class="desc" style="margin-bottom:14px; white-space:pre-line;">' + sec.description + '</div>';

    // Top-level fields (skip for array sections — fields are rendered per item)
    if (sec.fields && !sec.is_array) {
        html += renderFields(sec.fields, data, key);
    }

    // Subsections
    if (sec.subsections) {
        for (const [subKey, sub] of Object.entries(sec.subsections)) {
            if (ONLY_OVERRIDES && originOf(key + '.' + subKey) !== 'instance') continue;
            const subData = data[subKey] || {};
            html += '<div class="subsection">';
            html += '<div class="subsection-title">' + esc(sub.label) + '</div>';
            html += renderFields(sub.fields, subData, key + '.' + subKey);
            html += '</div>';
        }
    }

    // Sub-arrays (backends, catalogs) are NOT rendered here — each has its
    // own nav sub-item (see buildNav /
    // renderSubArrayPage), so the main page does not get overloaded.

    // Array sections (providers)
    if (sec.is_array && (!ONLY_OVERRIDES || originOf(key) === 'instance')) {
        html += originBadge(key);
        html += '<div style="margin-bottom: 12px;">';
        html += '<button class="btn btn-sm" onclick="addArrayItem(\'' + sJs(key) + '\', \'array\')">+ Add ' + esc(sec.label) + '</button>';
        html += '</div>';
        html += renderArrayItems(sec, data || [], key);
    }

    html += '</div>';
    content.innerHTML = html;
    // Load the meta of image_preview fields (no <script> possible via innerHTML)
    populateImagePreviewMetas();
}

// Own page for a single sub-array (e.g. image_generation::backends).
function renderSubArrayPage(key) {
    const sep = key.indexOf('::');
    const parentKey = key.slice(0, sep);
    const arrKey = key.slice(sep + 2);
    const sec = SCHEMA[parentKey];
    const arrDef = sec && sec.sub_arrays ? sec.sub_arrays[arrKey] : null;
    const content = document.getElementById('content');
    if (!sec || !arrDef) { content.innerHTML = '<div class="section active"></div>'; return; }
    const parentData = (CONFIG[parentKey] && typeof CONFIG[parentKey] === 'object') ? CONFIG[parentKey] : {};

    let html = '<div class="section active">';
    html += '<h1 class="section-title">' + esc(sec.icon || '') + ' ' + esc(sec.label) + ' — ' + esc(arrDef.label) + '</h1>';
    html += renderSubArrayBody(arrDef, parentData, parentKey, arrKey);
    html += '</div>';
    content.innerHTML = html;
    populateImagePreviewMetas();
}

// Body of ONE sub-array (the editor dispatch), without any page chrome —
// shared by the standalone sub-array page and the paged sections.
function renderSubArrayBody(arrDef, parentData, parentKey, arrKey) {
    const path = parentKey + '.' + arrKey;
    const items = (parentData && parentData[arrKey]) || (arrDef.is_dict ? {} : []);
    if (ONLY_OVERRIDES && originOf(path) !== 'instance') return '';
    const heading = '<div class="list-origin">' + originBadge(path) + '</div>';
    if (arrDef.lora_triggers_editor) return renderLoraTriggersEditor();
    if (arrDef.master_detail) return heading + renderMasterDetail(arrDef, items, path);
    let html = '<div style="margin-bottom:12px;"><button class="btn btn-sm" onclick="addArrayItem(\'' + sJs(path) + '\', \'' + (arrDef.is_dict ? 'dict' : 'array') + '\')">+ Add</button></div>';
    if (arrDef.is_dict) html += renderDictItems(arrDef, items, path);
    else html += renderArrayItems(arrDef, items, path);
    return heading + html;
}

// One page of a paged section: only the fields and sub-arrays the page lists,
// in the listed order. The section itself is still saved as a whole.
function renderPagedSection(key, pageId) {
    const sec = SCHEMA[key];
    const pages = resolvePages(sec);
    const page = pages.find(p => p.id === pageId) || pages[0];
    ACTIVE_PAGE = page.id;
    const cfgVal = CONFIG[key];
    const data = (cfgVal !== undefined && cfgVal !== null && typeof cfgVal === 'object') ? cfgVal : {};

    let html = '<div class="section active">';
    html += '<h1 class="section-title">' + esc(sec.icon || '') + ' ' + esc(sec.label)
          + ' <span style="color:#8b949e;">›</span> '
          + (page.icon ? esc(page.icon) + ' ' : '') + esc(page.label) + '</h1>';
    if (page.description) {
        html += '<div class="desc" style="margin-bottom:14px; white-space:pre-line;">' + page.description + '</div>';
    }

    const subset = {};
    for (const fKey of page.fields) {
        if (sec.fields && sec.fields[fKey]) subset[fKey] = sec.fields[fKey];
    }
    const hasFields = Object.keys(subset).length > 0;
    if (hasFields) html += renderFields(subset, data, key);

    for (const arrKey of page.sub_arrays) {
        const arrDef = (sec.sub_arrays || {})[arrKey];
        if (!arrDef) continue;
        // Only label the block when it shares the page with something else —
        // a page holding just one sub-array already says so in its title.
        if (hasFields || page.sub_arrays.length > 1) {
            html += '<div class="subsection-title" style="margin-top:18px;">' + esc(arrDef.label || arrKey) + '</div>';
        }
        html += renderSubArrayBody(arrDef, data, key, arrKey);
    }

    html += '</div>';
    document.getElementById('content').innerHTML = html;
    populateImagePreviewMetas();
}

async function populateImagePreviewMetas() {
    const els = document.querySelectorAll('.image-preview-meta[data-meta-url]');
    for (const el of els) {
        const url = el.dataset.metaUrl;
        if (!url) continue;
        try {
            const r = await fetch(url);
            if (!r.ok) continue;
            const d = await r.json();
            if (d.has_frame && d.bbox && d.frame_size) {
                el.textContent = 'Frame ' + d.frame_size[0] + '×' + d.frame_size[1]
                    + ' — Window ' + d.bbox.w + '×' + d.bbox.h
                    + ' @ (' + d.bbox.x + ',' + d.bbox.y + ')'
                    + (d.generated_at ? ' — generated ' + d.generated_at : '');
            } else {
                el.textContent = 'Not generated yet.';
            }
        } catch (e) { /* ignore */ }
    }
}

// ── LLM routing: requirement badges & model mismatch ────────────────────
// All user-visible strings of this block are collected in ROUTING_TEXT /
// MISMATCH_TEXT so this file has one place to edit them — not as a staging
// area for a translation pass. /admin/settings is English-only by decision and
// gets no t() layer; its strings never belong in shared/languages/*.json
// (guard: scripts/smoke_i18n_orphans.py).
const ROUTING_TEXT = {
    profileTitle:     'Requirement profile of this task',
    requiredSuffix:   ' required',
    capsUnknown:      'capabilities unknown',
    capsUnknownTitle: 'No capability entry for this model — maintain it under /admin/models. No check possible, no warning.',
    catalogFailed:    'Could not load the LLM task list — the task pages and the '
                    + 'task chips stay empty. After a code update the server '
                    + 'needs a restart; if that is not it, your session may have expired.',
};

// Warning text per automatically checkable requirement. Only these two can be
// verified against the model-capability data; json / min_context and every soft
// criterion are displayed but never checked.
const MISMATCH_TEXT = {
    tools:  {
        label: 'model lacks tool calling',
        title: 'This task needs a model that reliably answers in the tool-call text format; the capability entry says this model does not.',
    },
    vision: {
        label: 'model lacks vision',
        title: 'This task sends images to the model; the capability entry says this model has no image input.',
    },
};

// Hard requirements are rendered as an icon (+ tooltip from the server-side
// requirement labels). Anything else in the profile falls through to the soft
// text badges. A requirement key without an icon and without a badge label is
// not rendered at all.
const HARD_REQUIREMENT_ICONS = {
    tools:       '🔧',
    vision:      '👁',
    json:        '{ }',
    min_context: '📏',
};

// >>> harness-extract:evaluateRoutingMatch
// Requirement key -> capability field delivered by
// /admin/settings/model-capabilities/lookup. The lookup itself (substring
// match, longest wins) happens server-side in app/core/model_capabilities.py.
const CHECKABLE_REQUIREMENTS = { tools: 'tools', vision: 'vision' };

// Compares a task's requirement profile against one model's capabilities.
//   requirements: the task profile (null for a task without one)
//   caps:         {tools: true|false|null, vision: ..., known: bool}
// Returns {missing: [requirementKey, ...], unknown: bool}.
// Warn ONLY on requirement === true AND capability === false. A null/absent
// capability or an unknown model yields `unknown` (grey hint), never a warning.
function evaluateRoutingMatch(requirements, caps) {
    const empty = { missing: [], unknown: false };
    if (!requirements || typeof requirements !== 'object') return empty;
    const needed = Object.keys(CHECKABLE_REQUIREMENTS)
        .filter(k => requirements[k] === true);
    if (!needed.length) return empty;
    if (!caps || caps.known !== true) return { missing: [], unknown: true };
    const missing = [];
    let unresolved = false;
    for (const k of needed) {
        const val = caps[CHECKABLE_REQUIREMENTS[k]];
        if (val === false) missing.push(k);
        else if (val !== true) unresolved = true;
    }
    return { missing: missing, unknown: unresolved && !missing.length };
}
// <<< harness-extract:evaluateRoutingMatch

// "Provider::Model" -> capability record. Filled by ensureModelCaps(); a failed
// lookup is cached as "unknown" so a re-render never loops on the same models.
const MODEL_CAPS_CACHE = {};

async function ensureModelCaps(keys) {
    const missing = [...new Set((keys || []).filter(
        k => k && MODEL_CAPS_CACHE[k] === undefined))];
    if (!missing.length) return false;
    let got = {};
    try {
        const resp = await fetch('/admin/settings/model-capabilities/lookup', {
            method: 'POST',
            headers: authHeaders(),
            body: JSON.stringify({ models: missing }),
        });
        if (resp.ok) got = (await resp.json()).models || {};
    } catch (e) { /* treated as unknown below */ }
    for (const k of missing) {
        MODEL_CAPS_CACHE[k] = got[k] || { tools: null, vision: null, known: false };
    }
    return true;
}

function capsKeyFor(provider, model) {
    return (provider || '') + '::' + (model || '');
}

// Compact context size for the badge: 16384 -> "16k".
function _fmtContextTokens(n) {
    const v = Number(n) || 0;
    return (v >= 1024 && v % 1024 === 0) ? (v / 1024) + 'k' : String(v);
}

// Renders the requirement profile generically: key ORDER and tooltips come from
// the server (requirement_labels), the short badge text from
// requirement_badge_labels. A value with no badge label renders nothing — that
// is how defaults (arch "any", the False flags) stay invisible. No task id and
// no per-task field list appears here, so a new task in the catalog renders
// correctly without a UI change.
function renderRequirementBadges(req, catalog) {
    if (!req || typeof req !== 'object') return '';
    const labels = (catalog && catalog.requirement_labels) || {};
    const badgeLabels = (catalog && catalog.requirement_badge_labels) || {};
    const classLabels = (catalog && catalog.model_class_labels) || {};
    let hard = '';
    const soft = [];
    for (const key of Object.keys(labels)) {
        const val = req[key];
        if (val === undefined || val === null || val === '') continue;
        const icon = HARD_REQUIREMENT_ICONS[key];
        if (icon) {
            if (val === false || val === 0) continue;   // not required by this task
            const isNum = typeof val === 'number';
            const title = labels[key] + (isNum ? ': ' + val : ROUTING_TEXT.requiredSuffix);
            hard += '<span class="req-hard" title="' + esc(title) + '">' + icon
                 + (isNum ? ' ' + esc(_fmtContextTokens(val)) : '') + '</span>';
            continue;
        }
        const text = (badgeLabels[key] || {})[String(val).toLowerCase()];
        if (!text) continue;   // default / no badge label -> not shown
        // model_class is the ONLY key with a long form. Applying the table to
        // every key would mis-explain values that exist in both tables (e.g.
        // hallucination_risk "medium" would read as the model-size text).
        const long = (key === 'model_class' ? (classLabels[String(val)] || val) : val);
        soft.push('<span class="req-soft" title="' + esc(labels[key] + ': ' + long) + '">'
                + esc(text) + '</span>');
    }
    if (!hard && !soft.length) return '';
    return '<div class="req-badges" title="' + esc(ROUTING_TEXT.profileTitle) + '">'
         + hard + soft.join('<span class="req-sep">·</span>') + '</div>';
}

// Warning / unknown chips for one task+model pair. Empty while the capabilities
// of that model have not been fetched yet (the caller awaits ensureModelCaps).
function renderMatchBadges(req, capsKey) {
    const caps = MODEL_CAPS_CACHE[capsKey];
    if (caps === undefined) return '';
    const res = evaluateRoutingMatch(req, caps);
    let html = '';
    for (const key of res.missing) {
        const txt = MISMATCH_TEXT[key];
        if (!txt) continue;
        html += '<span class="req-warn" title="' + esc(txt.title) + '">⚠ '
             + esc(txt.label) + '</span>';
    }
    if (res.unknown) {
        html += '<span class="req-unknown" title="' + esc(ROUTING_TEXT.capsUnknownTitle)
             + '">' + esc(ROUTING_TEXT.capsUnknown) + '</span>';
    }
    return html;
}

// Provider/model of an llm_routing entry changed. Only the Tasks page shows
// mismatch badges for a model, so only that page needs a re-render; on the
// LLMs page the tasks are read-only chips carrying no model information, and
// re-rendering there would collapse the accordion on every edit.
function onRoutingModelChanged(path) {
    if (!/^llm_routing\[\d+\]\.(model|provider)$/.test(path || '')) return;
    if (ACTIVE_SECTION === 'llm_routing' && ACTIVE_PAGE === 'tasks') renderLlmRoutingPage('tasks');
    // The entry may have joined another model's lane pool — no re-render,
    // only the lane fields and notes follow.
    if (ACTIVE_SECTION === 'llm_routing' && ACTIVE_PAGE === 'llms') {
        rtPoolMembershipChanged(path);
        rtProviderStateChanged(path);
    }
}

function toggleTaskPersistent(taskId, disable) {
    touchPath('llm_task_state.disabled_tasks');
    if (!CONFIG.llm_task_state) CONFIG.llm_task_state = { disabled_tasks: [] };
    const arr = CONFIG.llm_task_state.disabled_tasks || [];
    const idx = arr.indexOf(taskId);
    if (disable && idx < 0) arr.push(taskId);
    if (!disable && idx >= 0) arr.splice(idx, 1);
    CONFIG.llm_task_state.disabled_tasks = arr;
    toast('Change only takes effect after save', 'success');
    renderLlmRoutingPage('tasks');
}

async function applyTaskPreset(preset) {
    try {
        const resp = await fetch('/admin/settings/llm-task-state/runtime-preset', {
            method: 'POST',
            headers: authHeaders(),
            body: JSON.stringify({ preset: preset }),
        });
        const data = await resp.json();
        if (preset === 'none') {
            toast('Runtime preset cleared', 'success');
        } else {
            toast('Runtime preset "' + preset + '" active (' + (data.disabled || []).length + ' tasks off)', 'success');
        }
        await renderLlmRoutingPage('tasks');
    } catch (e) {
        toast('Preset error: ' + e.message, 'error');
    }
}

// ── Render Fields ──
function renderFields(fields, data, path, inItem = false) {
    let html = '';
    for (const [fKey, field] of Object.entries(fields)) {
        const f = field.min_by_api_type && field.min_by_api_type[data?.api_type] !== undefined
            ? {...field, min: field.min_by_api_type[data.api_type]} : field;
        if (!inItem && ONLY_OVERRIDES && originOf(path + '.' + fKey) !== 'instance') continue;
        // Schema-level visibility: a field with `applicable_for` is only shown
        // when `data.api_type` is in the list. While no api_type is set, the
        // type-specific fields stay hidden — the user picks the type first,
        // then the matching fields appear.
        if (Array.isArray(f.applicable_for) && f.applicable_for.length) {
            const cur = (data && data.api_type) || '';
            if (!cur || !f.applicable_for.includes(cur)) {
                continue;
            }
        }
        // Inverse of applicable_for: a field that applies to every type EXCEPT
        // a few (e.g. Width/Height/Image Family make no sense for a mesh
        // backend). Cheaper than listing every other api_type — and new types
        // keep inheriting the field by default.
        if (Array.isArray(f.not_applicable_for) && f.not_applicable_for.length) {
            const cur = (data && data.api_type) || '';
            if (cur && f.not_applicable_for.includes(cur)) {
                continue;
            }
        }
        // Sibling-value visibility: `visible_when: {field: value}` shows the
        // field only while every referenced sibling field holds the required
        // value (e.g. the inpaint-only mask fields behind Category=inpaint).
        // An ARRAY value means "one of these" (e.g. Category in
        // [txt2img, img2img]). The gating select needs `triggers_rerender`
        // so toggling it re-runs this filter immediately.
        if (f.visible_when && typeof f.visible_when === 'object') {
            let visible = true;
            for (const [depKey, depVal] of Object.entries(f.visible_when)) {
                const cur = (data && data[depKey] !== undefined && data[depKey] !== null)
                    ? data[depKey] : '';
                const ok = Array.isArray(depVal) ? depVal.includes(cur) : cur === depVal;
                if (!ok) { visible = false; break; }
            }
            if (!visible) continue;
        }
        if (f.type === 'group_header') {
            // Visual separator without data binding (groups the fields below)
            html += '<div class="subsection-title" style="margin-top:18px;">' + esc(f.label) + '</div>';
            continue;
        }
        if (f.type === 'note') {
            // Layout-only full-width note without data binding — e.g. the
            // size guide rendered below the Width/Height half-column pair.
            html += '<div class="field field-note"><label></label>'
                + '<div class="input-wrap"><div class="desc">' + (f.text || '') + '</div></div></div>';
            continue;
        }
        if (f.type === 'button') {
            // Action button — no data binding, calls an endpoint with a body
            // built from the named sibling fields.
            const btnId = 'btn-' + (path + '.' + fKey).replace(/\W+/g, '-');
            const bodyFrom = JSON.stringify(f.body_from || []);
            const confirmMsg = f.confirm ? sJs(f.confirm) : '';
            const previewUrl = f.preview_url ? sJs(f.preview_url) : '';
            html += '<div class="field">';
            html += '<label></label>';
            html += '<div class="input-wrap">';
            html += '<button type="button" id="' + btnId + '" class="btn btn-primary" '
                + 'onclick="runActionButton(\'' + sJs(f.endpoint) + '\', \'' + sJs(f.method || 'POST') + '\', '
                + '\'' + sJs(path) + '\', ' + esc(bodyFrom) + ', \'' + confirmMsg + '\', this, \'' + previewUrl + '\')">'
                + esc(f.label) + '</button>';
            if (f.description) html += '<div class="desc">' + f.description + '</div>';
            html += '</div></div>';
            continue;
        }
        if (f.type === 'image_preview') {
            // Live preview of an image endpoint (e.g. a generated frame)
            const imgId = 'img-' + (path + '.' + fKey).replace(/\W+/g, '-');
            const url = esc(f.url);
            const metaUrl = f.meta_url ? esc(f.meta_url) : '';
            html += '<div class="field">';
            html += '<label>' + esc(f.label) + '</label>';
            html += '<div class="input-wrap">';
            html += '<div id="' + imgId + '-wrap" class="image-preview-wrap" style="background:'
                + ' repeating-conic-gradient(#777 0% 25%, #555 0% 50%) 50% / 16px 16px;'
                + ' display:inline-block; padding:6px; border:1px solid #444; border-radius:6px; max-width:300px;">';
            html += '<img id="' + imgId + '" src="' + url + '?_=' + Date.now() + '" '
                + 'style="max-width:280px; max-height:380px; display:block;" '
                + 'onerror="this.style.display=\'none\'; this.nextElementSibling.style.display=\'block\';">';
            html += '<div style="display:none; color:#888; font-size:12px; padding:20px;">not generated yet</div>';
            html += '</div>';
            if (metaUrl) {
                // Store the meta URL as a data attribute — populateImagePreviewMetas()
                // runs after renderSection and fills every such element.
                html += '<div id="' + imgId + '-meta" class="desc image-preview-meta" '
                    + 'data-meta-url="' + metaUrl + '" '
                    + 'style="margin-top:6px; font-family:monospace; font-size:11px;"></div>';
            }
            if (f.description) html += '<div class="desc">' + f.description + '</div>';
            html += '</div></div>';
            continue;
        }
        if (f.type === 'task_order_list') {
            // Read-only chips (settings-routing.js) — assignment lives on the
            // Tasks page of the LLM Routing section.
            html += renderTaskChips(data[fKey] || [], path + '.' + fKey, f);
            continue;
        }
        const val = data[fKey] !== undefined ? data[fKey] : (f.default !== undefined ? f.default : '');
        const fullPath = path + '.' + fKey;
        const pill = f.requires_restart
            ? ' <span class="restart-pill" title="Changing this value requires a server restart">restart</span>'
            : '';
        // Fields irrelevant for embedding entries (tasks of the "embedding"
        // group), e.g. temperature/max_tokens — toggled by a post-pass.
        const embedAttr = f.hide_for_embedding ? ' data-embedhide-entry="' + esc(path) + '"' : '';
        // `half: true` fields occupy one grid column instead of both, so two
        // adjacent half fields (e.g. Width | Height) share one row.
        html += '<div class="field' + (f.half ? ' field-half' : '') + '"' + embedAttr + '>';
        html += '<label for="f-' + esc(fullPath) + '">' + esc(f.label) + pill + (!inItem ? originBadge(fullPath) : '') + '</label>';
        html += '<div class="input-wrap">';
        html += renderInput(f, val, fullPath);
        // Show the schema default next to the description so the effective
        // fallback is always visible — even when the stored value is empty.
        // Long text defaults (e.g. prompt templates) are skipped: they are
        // prefilled into the input anyway and would bloat the description.
        let desc = f.description || '';
        if (f.default !== undefined && f.default !== ''
            && (typeof f.default === 'string' || typeof f.default === 'number' || typeof f.default === 'boolean')
            && String(f.default).length <= 80) {
            const dv = typeof f.default === 'boolean' ? (f.default ? 'on' : 'off') : String(f.default);
            desc += (desc ? ' ' : '') + '<span class="desc-default">Default: ' + esc(dv) + '</span>';
        }
        if (desc) html += '<div class="desc">' + desc + '</div>';
        // `pool_shared`: one value for every llm_routing entry on the same
        // provider+model (settings-routing.js names who shares it).
        if (f.pool_shared) html += rtPoolNote(path);
        html += '</div></div>';
    }
    // Two-column grid: regular fields span both columns (unchanged look),
    // `half` fields take one column each so pairs share a row.
    return '<div class="fields-grid">' + html + '</div>';
}

// Default greyed in the empty field (like the use-case styles editor):
// placeholder attribute from f.placeholder, else from f.default. The server
// deliberately does NOT materialize defaults for these field types.
function _phAttr(f) {
    const ph = f.placeholder !== undefined && f.placeholder !== ''
        ? f.placeholder
        : (f.default !== undefined && f.default !== '' ? String(f.default) : '');
    return ph ? 'placeholder="' + esc(ph) + '" ' : '';
}

function renderInput(f, val, path) {
    const id = 'f-' + path;
    switch (f.type) {
        case 'bool':
            return '<input type="checkbox" id="' + esc(id) + '" ' + (val ? 'checked' : '') + ' onchange="setVal(\'' + sJs(path) + '\', this.checked)">';
        case 'int':
            return '<input type="number" id="' + esc(id) + '" value="' + esc(val) + '" '
                + (f.min !== undefined ? 'min="' + esc(f.min) + '" ' : '')
                + (f.max !== undefined ? 'max="' + esc(f.max) + '" ' : '')
                + _phAttr(f)
                + 'step="1" onchange="' + (f.pool_shared ? 'rtSetLanes' : 'setVal')
                + '(\'' + sJs(path) + '\', parseInt(this.value) || 0)">';
        case 'float':
            return '<input type="number" id="' + esc(id) + '" value="' + esc(val) + '" '
                + (f.min !== undefined ? 'min="' + esc(f.min) + '" ' : '')
                + (f.max !== undefined ? 'max="' + esc(f.max) + '" ' : '')
                + _phAttr(f)
                + 'step="' + esc(f.step || 0.1) + '" onchange="setVal(\'' + sJs(path) + '\', parseFloat(this.value) || 0)">';
        case 'select':
            let opts = (f.choices || []).map(c => '<option value="' + esc(c) + '"' + (c == val ? ' selected' : '') + '>' + esc(c) + '</option>').join('');
            const onChg = f.triggers_rerender
                ? "setVal('" + sJs(path) + "', this.value); renderSection(ACTIVE_SECTION)"
                : "setVal('" + sJs(path) + "', this.value)";
            return '<select id="' + esc(id) + '" onchange="' + onChg + '">' + opts + '</select>';
        case 'password':
            return '<div class="pw-wrap"><input type="password" id="' + esc(id) + '" value="' + esc(val) + '" onchange="setVal(\'' + sJs(path) + '\', this.value)">'
                + '<button class="pw-toggle" type="button" onclick="togglePw(this)">👁</button></div>';
        case 'text':
            return '<textarea id="' + esc(id) + '" ' + _phAttr(f)
                + 'onchange="setVal(\'' + sJs(path) + '\', this.value)">' + esc(val) + '</textarea>';
        case 'json_object':
            return '<textarea id="' + esc(id) + '" aria-label="' + esc(f.label) + '" '
                + 'oninput="validateJsonObjectField(\'' + sJs(path) + '\', this)">'
                + esc(JSON_OBJECT_DRAFTS.has(path) ? JSON_OBJECT_DRAFTS.get(path)
                    : (val && Object.keys(val).length ? JSON.stringify(val, null, 2) : '')) + '</textarea>'
                + '<button type="button" class="btn btn-sm" onclick="applyVeniceTemplate(\'' + sJs(path) + '\')">Venice template</button>'
                + '<div class="desc" role="alert" id="error-' + esc(path) + '">'
                + (INVALID_JSON_OBJECTS.has(path) ? 'Enter a valid JSON object.' : '') + '</div>';
        case 'provider_select':
            return renderProviderSelect(val, path);
        case 'model_select':
            return renderModelSelect(val, path);
        case 'imagegen_backend_select':
            return renderImagegenBackendSelect(val, path);
        case 'imagegen_model_select':
            return renderImagegenModelSelect(val, path);
        case 'imagegen_model':
            return renderImagegenModelCombo(val, path);
        default: // str / number
            return '<input type="text" id="' + esc(id) + '" value="' + esc(val) + '" '
                + _phAttr(f)
                + 'onchange="setVal(\'' + sJs(path) + '\', this.value)">';
    }
}

function renderProviderSelect(val, path) {
    const providers = CONFIG.providers || [];
    let opts = '<option value="">— Auto —</option>';
    for (const p of providers) {
        opts += '<option value="' + esc(p.name) + '"' + (p.name === val ? ' selected' : '') + '>' + esc(p.name) + ' (' + esc(p.type) + ')'
             + (p.enabled === false ? ' — disabled' : '') + '</option>';
    }
    return '<select id="f-' + esc(path) + '" onchange="setVal(\'' + sJs(path) + '\', this.value); refreshModelSelect(\'' + sJs(path) + '\'); onRoutingModelChanged(\'' + sJs(path) + '\')">' + opts + '</select>';
}

function renderModelSelect(val, path) {
    return ModelCombobox.render({id: 'f-' + path, value: val, ariaLabel: 'Model'})
        .replace('<input ', '<input data-model-path="' + esc(path) + '" ');
}

document.addEventListener('focusin', event => {
    const input = event.target;
    const path = input.dataset && input.dataset.modelPath;
    if (!path || input.modelCombobox) return;
    input.modelCombobox = ModelCombobox.attach(input.id, {
        loadModels: () => loadModels(path),
        onChange: value => { setVal(path, value); onRoutingModelChanged(path); }
    });
    input.modelCombobox.open();
});

function renderImagegenBackendSelect(val, path) {
    // ALL image backends (Together, CivitAI, LocalAI, ...)
    const backends = CONFIG.image_generation?.backends || [];
    let opts = '<option value="">— None —</option>';
    for (const be of backends) {
        const lbl = be.name + (be.api_type ? ' (' + be.api_type + ')' : '');
        opts += '<option value="' + esc(be.name) + '"' + (be.name === val ? ' selected' : '') + '>' + esc(lbl) + '</option>';
    }
    // onchange: setVal + refill the sibling model select if there is one
    return '<select id="f-' + esc(path) + '" onchange="setVal(\'' + sJs(path) + '\', this.value); refreshImagegenModelSelect(\'' + sJs(path) + '\')">' + opts + '</select>';
}

// Reload the sibling model select when the backend changes
function refreshImagegenModelSelect(backendPath) {
    const parts = backendPath.split('.');
    parts[parts.length - 1] = 'model';
    const modelPath = parts.join('.');
    const modelEl = document.getElementById('f-' + modelPath);
    if (!modelEl) return;
    const backendName = getVal(backendPath) || '';
    if (!backendName) {
        modelEl.innerHTML = '<option value="">— Select a backend first —</option>';
        return;
    }
    loadImagegenBackendModels(modelPath, backendName);
}

let IMAGEGEN_MODELS_CACHE = {};

async function loadImagegenBackendModels(path, backendName) {
    const sel = document.getElementById('f-' + path);
    if (!sel) return;
    const currentVal = sel.value || getVal(path) || '';
    if (!IMAGEGEN_MODELS_CACHE[backendName]) {
        sel.innerHTML = '<option>Loading...</option>';
        try {
            const resp = await fetch('/admin/settings/imagegen-backends/' + encodeURIComponent(backendName) + '/models',
                { credentials: 'same-origin' });
            const data = await resp.json();
            if (data.error) toast('Loading models failed: ' + data.error, 'error');
            const list = data.models || [];
            if (list.length > 0) IMAGEGEN_MODELS_CACHE[backendName] = list;
        } catch (e) {
            toast('Loading models failed: ' + e.message, 'error');
        }
    }
    const models = IMAGEGEN_MODELS_CACHE[backendName] || [];
    let opts = '<option value="">— Backend-Default —</option>';
    for (const m of models) {
        opts += '<option value="' + esc(m) + '"' + (m === currentVal ? ' selected' : '') + '>' + esc(m) + '</option>';
    }
    if (currentVal && !models.includes(currentVal)) {
        opts = '<option value="' + esc(currentVal) + '" selected>' + esc(currentVal) + ' (custom)</option>' + opts;
    }
    sel.innerHTML = opts;
}

function renderImagegenModelSelect(val, path) {
    // Read the backend from the sibling field
    const parts = path.split('.');
    parts[parts.length - 1] = 'backend';
    const backendPath = parts.join('.');
    const backendName = getVal(backendPath) || '';
    let html = '<select id="f-' + esc(path) + '" onchange="setVal(\'' + sJs(path) + '\', this.value)">';
    if (val) {
        html += '<option value="' + esc(val) + '" selected>' + esc(val) + '</option>';
    } else {
        html += '<option value="">— Backend-Default —</option>';
    }
    html += '</select>';
    html += ' <button class="btn btn-sm" onclick="loadImagegenBackendModels(\'' + sJs(path) + '\', \'' + sJs(backendName) + '\')">Load Models</button>';
    return html;
}

// Editable model combo for image backends: free text (CivitAI URN, manual
// typing) + datalist suggestions via "Load Models" (fetches /v1/models from the backend).
function renderImagegenModelCombo(val, path) {
    // base = the backend item (e.g. image_generation.backends.2); name/api_* are
    // read from the sibling fields at click time, so "enter URL ->
    // Load Models" works WITHOUT saving first.
    const parts = path.split('.');
    const base = parts.slice(0, -1).join('.');
    const dlId = 'dl-' + path.replace(/[^a-zA-Z0-9]/g, '-');
    let html = '<input type="text" list="' + dlId + '" id="f-' + esc(path) + '" value="' + esc(val) + '" placeholder="e.g. flux.2-klein-4b" onchange="setVal(\'' + sJs(path) + '\', this.value)">';
    html += '<datalist id="' + dlId + '"></datalist>';
    html += ' <button class="btn btn-sm" type="button" onclick="loadImagegenModelCombo(\'' + sJs(path) + '\', \'' + sJs(base) + '\')">Load Models</button>';
    return html;
}

async function loadImagegenModelCombo(path, base) {
    const name = getVal(base + '.name') || '';
    const apiType = getVal(base + '.api_type') || '';
    const apiUrl = getVal(base + '.api_url') || '';
    const apiKey = getVal(base + '.api_key') || '';
    const dlId = 'dl-' + path.replace(/[^a-zA-Z0-9]/g, '-');
    const dl = document.getElementById(dlId);
    if (!dl) return;
    if (!apiUrl) { toast('Enter the API URL first', 'error'); return; }
    try {
        const qs = new URLSearchParams({ api_type: apiType, api_url: apiUrl, api_key: apiKey }).toString();
        const resp = await fetch('/admin/settings/imagegen-backends/' + encodeURIComponent(name || '_new') + '/models?' + qs, { credentials: 'same-origin' });
        const data = await resp.json();
        if (data.error) { toast('Load Models: ' + data.error, 'error'); return; }
        const list = data.models || [];
        dl.innerHTML = list.map(m => '<option value="' + esc(m) + '"></option>').join('');
        toast(list.length ? (list.length + ' models loaded') : 'No models found', list.length ? 'success' : 'error');
    } catch (e) {
        toast('Load Models failed: ' + e.message, 'error');
    }
}

// ── Array/Dict Items ──
// _itemLabel: same logic as renderArrayItem — used for sorting.
// labelField may be a string OR an array. For an array the first non-empty
// value wins (e.g. ["name", "model"] -> name if set, else model).
function _itemLabel(item, labelField, fallback) {
    if (!item) return String(fallback || '');
    const fields = Array.isArray(labelField) ? labelField : [labelField];
    for (const f of fields) {
        const v = item[f];
        if (v !== undefined && v !== null && String(v).trim() !== '') return String(v);
    }
    return String(fallback || '');
}

function renderArrayItems(def, items, path) {
    let html = '<div id="arr-' + esc(path) + '">';
    // Keep the index (paths reference the real array index); order is
    // alphabetical when def.sort_alphabetically is set.
    const order = items.map((it, i) => ({ idx: i, label: _itemLabel(it, def.item_label_field, 'Item ' + i) }));
    if (def.sort_alphabetically) {
        order.sort((a, b) => a.label.localeCompare(b.label, undefined, { sensitivity: 'base' }));
    }
    for (const o of order) {
        html += renderArrayItem(def, items[o.idx], path + '[' + o.idx + ']', o.idx, def.item_label_field);
    }
    html += '</div>';
    return html;
}

function renderDictItems(def, items, path) {
    let html = '<div id="arr-' + esc(path) + '">';
    const entries = Object.entries(items).map(([k, item]) => ({ key: k, item, label: _itemLabel(item, def.item_label_field, k) }));
    if (def.sort_alphabetically) {
        entries.sort((a, b) => a.label.localeCompare(b.label, undefined, { sensitivity: 'base' }));
    }
    for (const e of entries) {
        html += renderArrayItem(def, e.item, path + '.' + e.key, e.key, def.item_label_field);
    }
    html += '</div>';
    return html;
}

// A section's `header_fields` (schema) render in the collapsed item header
// instead of the body. Only `enabled` is supported: the click toggle the LLM
// entries have on LLM Routing › LLMs (rtRenderEntryItem).
function _hasHeaderToggle(def) {
    return Array.isArray(def.header_fields) && def.header_fields.includes('enabled');
}

function renderArrayItem(def, item, path, index, labelField) {
    const label = _itemLabel(item, labelField, 'Item ' + index);
    const openClass = OPEN_ITEMS.has(path) ? ' open' : '';
    const headerToggle = _hasHeaderToggle(def);
    const on = item.enabled !== false;
    const toggleClass = headerToggle ? ' rt-entry ' + (on ? 'rt-on' : 'rt-off') : '';
    let html = '<div class="array-item' + toggleClass + openClass + '" id="item-' + esc(path) + '">';
    html += '<div class="array-item-header" onclick="toggleArrayItem(this, \'' + sJs(path) + '\')">';
    html += '<span class="chevron">▶</span> ';
    html += '<span class="title" style="margin-left:6px;">' + esc(label) + '</span>';
    if (headerToggle) {
        html += '<button class="rt-toggle" title="Click to enable/disable (settings stay)"'
             + ' onclick="event.stopPropagation(); toggleItemEnabled(\'' + sJs(path) + '\')">'
             + (on ? 'enabled' : 'disabled') + '</button>';
    } else if (item.enabled === false) {
        html += '<span class="badge">disabled</span>';
    }
    if (item.type) html += '<span class="badge">' + esc(item.type || item.api_type || '') + '</span>';
    html += '<button class="btn btn-sm" style="margin-left:8px;" title="Duplicate as a new entry" onclick="event.stopPropagation(); duplicateItem(\'' + sJs(path) + '\')">⧉</button>';
    html += '<button class="btn btn-sm btn-danger" style="margin-left:4px;" onclick="event.stopPropagation(); removeItem(\'' + sJs(path) + '\')">✕</button>';
    html += '</div>';
    html += '<div class="array-item-body">';
    let fields = def.fields;
    if (headerToggle) {
        fields = Object.assign({}, def.fields);
        for (const key of def.header_fields) delete fields[key];
    }
    html += renderFields(fields, item, path, true);
    html += '</div></div>';
    return html;
}

// Click on the header toggle: flips `enabled` in place — a re-render would
// collapse the accordion and lose the scroll position.
function toggleItemEnabled(path) {
    const item = getVal(path);
    if (!item || typeof item !== 'object') return;
    const on = item.enabled === false;
    setVal(path + '.enabled', on);
    const el = document.getElementById('item-' + path);
    if (el) {
        el.classList.toggle('rt-on', on);
        el.classList.toggle('rt-off', !on);
        const btn = el.querySelector('.rt-toggle');
        if (btn) btn.textContent = on ? 'enabled' : 'disabled';
    }
}

// ── Master-detail (table left, editor right) ──
// Returns the ordered entry list for array OR dict sub-arrays. Each entry
// carries its full path (image_generation.backends[0] or dict-keyed paths) —
// identical to the paths renderArrayItem/setVal use.
function _mdOrder(def, items, path) {
    let order;
    if (def.is_dict) {
        order = Object.entries(items || {}).map(([k, it]) => ({
            itemPath: path + '.' + k, item: it,
            label: _itemLabel(it, def.item_label_field, k),
        }));
    } else {
        order = (items || []).map((it, i) => ({
            itemPath: path + '[' + i + ']', item: it,
            label: _itemLabel(it, def.item_label_field, 'Item ' + i),
        }));
    }
    if (def.sort_alphabetically) {
        order.sort((a, b) => a.label.localeCompare(b.label, undefined, { sensitivity: 'base' }));
    }
    return order;
}

function renderMdCell(col, item) {
    const v = item ? item[col.field] : undefined;
    if (col.kind === 'status') {
        const on = v !== false;
        if (!on) return '<span class="md-status off">○ off</span>';
        // Merge the RUNTIME state (media-backend-status, keyed by name): a
        // backend flagged offline (error cooldown) or failing its probe shows
        // as offline here, with an action to lift the flag and probe again.
        // No entry (e.g. just added, pending restart) -> plain config state.
        const rt = item && item.name ? MEDIA_STATUS[item.name] : null;
        if (rt && (rt.cooldown_seconds > 0 || rt.available === false)) {
            const why = rt.cooldown_seconds > 0
                ? 'Flagged offline: ' + (rt.cooldown_reason || 'error') + ' — ' +
                  Math.ceil(rt.cooldown_seconds / 60) + ' min cooldown left'
                : 'Availability probe failed — backend unreachable';
            return '<span class="md-status offline" title="' + esc(why) + '">⏻ offline</span>' +
                   '<button class="md-online-btn" data-backend="' + esc(item.name) + '" ' +
                   'title="' + esc(why) + ' — clear the flag and probe again" ' +
                   'onclick="event.stopPropagation(); mediaBackendOnline(this.dataset.backend, this)">online</button>';
        }
        return '<span class="md-status on">● on</span>';
    }
    if (v === undefined || v === null || v === '') return '<span class="md-empty">—</span>';
    return esc(String(v));
}

// ── Media-backend runtime status (Status column + online action) ──
async function loadMediaStatus() {
    try {
        const resp = await fetch('/admin/settings/media-backend-status', { credentials: 'same-origin' });
        if (resp.ok) MEDIA_STATUS = (await resp.json()).backends || {};
    } catch (e) { /* no runtime info — the column falls back to the config state */ }
}

async function mediaBackendOnline(name, btn) {
    if (btn) { btn.disabled = true; btn.textContent = '…'; }
    try {
        const resp = await fetch('/admin/settings/media-backend-online', {
            method: 'POST', headers: authHeaders(), credentials: 'same-origin',
            body: JSON.stringify({ name: name })
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) throw new Error((data && data.detail) || ('HTTP ' + resp.status));
        toast(data.available
            ? name + ' is back online'
            : name + ' stays offline — the availability probe failed', data.available ? 'success' : 'error');
    } catch (e) {
        toast('Error: ' + e.message, 'error');
    }
    await loadMediaStatus();
    if (ACTIVE_SECTION) renderSection(ACTIVE_SECTION);
}

function renderMasterDetail(def, items, path) {
    const order = _mdOrder(def, items, path);
    // Validate the current selection — otherwise pick the first entry.
    let sel = SELECTED_ITEM[path];
    if (!order.some(o => o.itemPath === sel)) sel = order.length ? order[0].itemPath : null;
    SELECTED_ITEM[path] = sel;

    const cols = def.list_columns || [{ field: def.item_label_field || 'name', label: 'Name' }];

    let html = '<div class="md-grid">';
    // Left: table
    html += '<div class="md-list">';
    html += '<table class="md-table"><thead><tr>';
    for (const c of cols) html += '<th>' + esc(c.label) + '</th>';
    html += '</tr></thead><tbody>';
    for (const o of order) {
        const active = (o.itemPath === sel) ? ' active' : '';
        html += '<tr class="md-row' + active + '" onclick="selectMasterItem(\'' + sJs(path) + '\', \'' + sJs(o.itemPath) + '\')">';
        for (const c of cols) html += '<td>' + renderMdCell(c, o.item) + '</td>';
        html += '</tr>';
    }
    if (!order.length) {
        html += '<tr><td colspan="' + cols.length + '"><span class="md-empty">No entries</span></td></tr>';
    }
    html += '</tbody></table>';
    html += '<button class="btn btn-sm" style="margin-top:10px;" onclick="addArrayItem(\'' + sJs(path) + '\', \'' + (def.is_dict ? 'dict' : 'array') + '\')">+ Add</button>';
    html += '</div>';
    // Right: detail
    html += '<div class="md-detail" id="detail-' + esc(path) + '">';
    html += renderMasterDetailBody(def, items, path, sel);
    html += '</div>';
    html += '</div>';
    return html;
}

function renderMasterDetailBody(def, items, path, sel) {
    if (!sel) return '<div class="md-empty-detail">Select an entry on the left or create one.</div>';
    let item;
    if (def.is_dict) {
        item = (items || {})[sel.slice(path.length + 1)];
    } else {
        const m = sel.match(/\[(\d+)\]$/);
        item = m ? (items || [])[parseInt(m[1], 10)] : null;
    }
    if (!item) return '<div class="md-empty-detail">Select an entry on the left or create one.</div>';

    const label = _itemLabel(item, def.item_label_field, 'Entry');
    let html = '<div class="md-detail-head">';
    html += '<span class="md-detail-title">' + esc(label) + '</span>';
    html += '<span style="flex:1;"></span>';
    html += '<button class="btn btn-sm" title="Duplicate as a new entry" onclick="duplicateItem(\'' + sJs(sel) + '\')">⧉</button>';
    html += '<button class="btn btn-sm btn-danger" style="margin-left:4px;" title="Delete" onclick="removeItem(\'' + sJs(sel) + '\')">✕</button>';
    html += '</div>';
    html += renderFields(def.fields, item, sel, true);
    return html;
}

function selectMasterItem(path, itemPath) {
    SELECTED_ITEM[path] = itemPath;
    renderSection(ACTIVE_SECTION);
}

// ── Task/Order List (llm_routing.tasks) ──
// The catalog is one object: {tasks, requirement_labels,
// requirement_badge_labels, model_class_labels} — the label tables ride along
// once so the requirement badges can be rendered generically.
let LLM_CATALOG_CACHE = null;

const EMPTY_LLM_CATALOG = {
    tasks: [], requirement_labels: {}, requirement_badge_labels: {}, model_class_labels: {},
};

// Loads the task catalog. A failure must be LOUD: without it every task
// dropdown and the whole task view stay empty, which looks like an empty
// config instead of a broken fetch. The most likely cause is a server that
// still serves the pre-A0.3 list form (restart missing) — the response is
// therefore checked for shape, and there is deliberately NO fallback reader
// for the old list.
async function loadLlmCatalog(forceRefresh) {
    if (LLM_CATALOG_CACHE && !forceRefresh) return LLM_CATALOG_CACHE;
    let failure = '';
    try {
        // Cache-bust via query param so the browser does not serve from the HTTP
        // cache (e.g. after a server restart that added new sub-tasks).
        const resp = await fetch('/admin/settings/llm-tasks?_=' + Date.now(),
            { credentials: 'same-origin', cache: 'no-store' });
        if (!resp.ok) {
            failure = 'HTTP ' + resp.status;
        } else {
            const data = await resp.json();
            if (!data || typeof data !== 'object' || !Array.isArray(data.tasks)) {
                failure = 'unexpected response shape';
            } else {
                LLM_CATALOG_CACHE = data;
            }
        }
    } catch (e) {
        failure = e.message || String(e);
    }
    if (failure) {
        LLM_CATALOG_CACHE = EMPTY_LLM_CATALOG;
        toast(ROUTING_TEXT.catalogFailed + ' (' + failure + ')', 'error');
    }
    return LLM_CATALOG_CACHE;
}

// True when the routing entry serves at least one task of the "embedding" group
// (embedding models use no temperature/max_tokens).
function _entryIsEmbedding(data) {
    if (!data || !Array.isArray(data.tasks) || !data.tasks.length) return false;
    const cached = (LLM_CATALOG_CACHE || EMPTY_LLM_CATALOG).tasks || [];
    const embedIds = new Set(cached.filter(t => t.category === 'embedding').map(t => t.id));
    if (!embedIds.size) embedIds.add('pose_embedding');  // fallback until the catalog is loaded
    return data.tasks.some(it => it && embedIds.has(it.task));
}

// Hides temperature/max_tokens on embedding entries (post-pass, so it also
// toggles live when the task is added/removed).
function applyEmbedVisibility() {
    document.querySelectorAll('[data-embedhide-entry]').forEach(el => {
        const entryPath = el.getAttribute('data-embedhide-entry');
        const entry = getVal(entryPath);
        el.style.display = _entryIsEmbedding(entry) ? 'none' : '';
    });
}

// ── Data Access ──
// Origin compares parsed segments, including bracket and dotted indices.
function pathsOverlap(a, b) {
    const left = parsePath(a).map(String), right = parsePath(b).map(String);
    return left.slice(0, Math.min(left.length, right.length)).every((v, i) => v === right[i]);
}

function originOf(path) {
    return [...OVERRIDES].some(o => pathsOverlap(o, path)) ? 'instance' : 'default';
}

function shippedAt(path) {
    let cur = SHIPPED;
    for (const seg of parsePath(path)) {
        if (cur === null || typeof cur !== 'object' || !Object.prototype.hasOwnProperty.call(cur, seg)) return { has: false };
        cur = cur[seg];
    }
    return { has: true, value: JSON.parse(JSON.stringify(cur)) };
}

function originBadge(path) {
    const origin = originOf(path);
    let html = '<span class="origin origin-' + origin + '">' + (origin === 'instance' ? 'Instance' : 'Default (GitHub)') + '</span>';
    if (origin === 'instance') html += ' <button type="button" class="btn btn-xs" onclick="resetToDefault(\'' + sJs(path) + '\')">Reset to default</button>';
    return html;
}

function markDirty() {
    MUTATION_REVISION++;
    DIRTY = true;
    const btn = document.getElementById('btn-save');
    if (btn) btn.textContent = 'Save*';
}

// Called only by edits: an overlapping pending reset must not undo the edit.
function touchPath(path) {
    for (const reset of [...RESETS]) if (pathsOverlap(reset, path)) RESETS.delete(reset);
    markDirty();
}

function deleteVal(path) {
    const parts = parsePath(path);
    let obj = CONFIG;
    for (const seg of parts.slice(0, -1)) {
        if (obj === null || typeof obj !== 'object' || !(seg in obj)) return;
        obj = obj[seg];
    }
    if (obj && typeof obj === 'object') delete obj[parts[parts.length - 1]];
}

async function resetToDefault(path) {
    const shipped = shippedAt(path);
    if (shipped.has) setVal(path, shipped.value);
    else deleteVal(path);
    // Replaced routing entries must not inherit index-keyed JSON editor state.
    if (path === 'llm_routing' || path.startsWith('llm_routing[')) {
        const resetDepth = parsePath(path).length;
        const removed = draftPath => resetDepth <= parsePath(draftPath).length
            && pathsOverlap(path, draftPath);
        for (const draftPath of JSON_OBJECT_DRAFTS.keys()) {
            if (removed(draftPath)) JSON_OBJECT_DRAFTS.delete(draftPath);
        }
        for (const invalidPath of INVALID_JSON_OBJECTS) {
            if (removed(invalidPath)) INVALID_JSON_OBJECTS.delete(invalidPath);
        }
    }
    RESETS.add(path);
    for (const override of [...OVERRIDES]) {
        if (override === path || override.startsWith(path + '.')) OVERRIDES.delete(override);
    }
    markDirty();
    buildNav();
    await renderSection(ACTIVE_SECTION, ACTIVE_PAGE);
}

function sectionHasOverride(key) {
    if (key === 'llm_routing') return ['llm_routing', 'llm_task_state'].some(p => originOf(p) === 'instance');
    return originOf(key.replace('::', '.')) === 'instance';
}

function pageHasOverride(key, sec, page) {
    if (key === 'llm_routing' && page.id === 'tasks') return sectionHasOverride(key);
    if (sec.is_array) return originOf(key) === 'instance';
    if (key === 'image_generation' && ['routing', 'routing_overview'].includes(page.id)) return originOf(key + '.routing') === 'instance';
    if (key === 'decision' && page.id === 'points') return originOf('decision.points') === 'instance';
    if (key === 'decision' && page.id === 'shadow') return originOf('decision.points') === 'instance';
    return [...page.fields, ...page.sub_arrays].some(f => originOf(key + '.' + f) === 'instance');
}

async function setOnlyOverrides(value) {
    ONLY_OVERRIDES = value;
    try { localStorage.setItem('settings-only-overrides', String(value)); } catch (e) { /* storage unavailable */ }
    buildNav();
    if (ACTIVE_SECTION && !ACTIVE_SECTION.startsWith('_')) await renderSection(ACTIVE_SECTION, ACTIVE_PAGE);
}

const INVALID_JSON_OBJECTS = new Set();
const JSON_OBJECT_DRAFTS = new Map();

// Keep index-keyed editor state attached to entries when the routing array shifts.
function remapRoutingJsonDrafts(index, deleting) {
    const prefix = /^llm_routing\[(\d+)\]\.extra_params$/;
    const drafts = new Map();
    const invalid = new Set();
    for (const [path, value] of JSON_OBJECT_DRAFTS) {
        const match = prefix.exec(path);
        const oldIndex = match ? Number(match[1]) : -1;
        if (oldIndex < 0) {
            drafts.set(path, value);
        } else if (!(deleting && oldIndex === index)) {
            const next = oldIndex > index ? oldIndex + (deleting ? -1 : 1) : oldIndex;
            drafts.set(`llm_routing[${next}].extra_params`, value);
        }
    }
    for (const path of INVALID_JSON_OBJECTS) {
        const match = prefix.exec(path);
        const oldIndex = match ? Number(match[1]) : -1;
        if (oldIndex < 0) invalid.add(path);
        else if (!(deleting && oldIndex === index)) {
            const next = oldIndex > index ? oldIndex + (deleting ? -1 : 1) : oldIndex;
            invalid.add(`llm_routing[${next}].extra_params`);
        }
    }
    if (!deleting) {
        const source = `llm_routing[${index}].extra_params`;
        const clone = `llm_routing[${index + 1}].extra_params`;
        if (drafts.has(source)) drafts.set(clone, drafts.get(source));
        if (invalid.has(source)) invalid.add(clone);
    }
    JSON_OBJECT_DRAFTS.clear();
    INVALID_JSON_OBJECTS.clear();
    for (const [path, value] of drafts) JSON_OBJECT_DRAFTS.set(path, value);
    for (const path of invalid) INVALID_JSON_OBJECTS.add(path);
}

function validateJsonObjectField(path, input) {
    const error = document.getElementById('error-' + path);
    JSON_OBJECT_DRAFTS.set(path, input.value);
    try {
        const value = input.value.trim() ? JSON.parse(input.value) : {};
        if (!value || typeof value !== 'object' || Array.isArray(value)) {
            throw new Error('Enter a JSON object (not an array or scalar).');
        }
        const requireFinite = node => {
            if (typeof node === 'number' && !Number.isFinite(node))
                throw new Error('Numbers must be finite.');
            if (node && typeof node === 'object')
                for (const child of Object.values(node)) requireFinite(child);
        };
        requireFinite(value);
        INVALID_JSON_OBJECTS.delete(path);
        input.setCustomValidity('');
        if (error) error.textContent = '';
        setVal(path, value);
        return true;
    } catch (e) {
        INVALID_JSON_OBJECTS.add(path);
        input.setCustomValidity('Enter a valid JSON object.');
        if (error) error.textContent = e instanceof SyntaxError ? 'Invalid JSON: ' + e.message : e.message;
        return false;
    }
}

function applyVeniceTemplate(path) {
    const input = document.getElementById('f-' + path);
    if (!input) return;
    input.value = JSON.stringify({venice_parameters: {disable_thinking: true}}, null, 2);
    validateJsonObjectField(path, input);
}

function validateJsonObjectsBeforeSave() {
    document.querySelectorAll('textarea[id^="f-llm_routing["]').forEach(input => {
        if (input.id.endsWith('.extra_params')) validateJsonObjectField(input.id.slice(2), input);
    });
    if (!INVALID_JSON_OBJECTS.size) return true;
    const path = [...INVALID_JSON_OBJECTS][0];
    const input = document.getElementById('f-' + path);
    if (input) { input.focus(); input.reportValidity(); }
    toast('Fix invalid extra request parameters before saving.', 'error');
    return false;
}

function setVal(path, value) {
    touchPath(path);
    const parts = parsePath(path);
    let obj = CONFIG;
    for (let i = 0; i < parts.length - 1; i++) {
        const p = parts[i];
        if (obj[p] === undefined || obj[p] === null || typeof obj[p] !== 'object') {
            obj[p] = (typeof parts[i+1] === 'number') ? [] : {};
        }
        obj = obj[p];
    }
    obj[parts[parts.length - 1]] = value;
}

function getVal(path) {
    const parts = parsePath(path);
    let obj = CONFIG;
    for (const p of parts) {
        if (obj === undefined || obj === null) return undefined;
        obj = obj[p];
    }
    return obj;
}

function parsePath(path) {
    // "providers[0].name" => ["providers", 0, "name"]
    const result = [];
    for (const part of path.split('.')) {
        const m = part.match(/^([^\[]+)(?:\[(\d+)\])?$/);
        if (m) {
            result.push(m[1]);
            if (m[2] !== undefined) result.push(parseInt(m[2]));
        } else {
            result.push(part);
        }
    }
    return result;
}

// Walks `path` inside CONFIG, creating any missing levels. Intermediate levels
// are always created as {}; only the leaf takes the requested `leafType`
// ('array' or 'dict'). Returns the leaf container.
function _ensureContainer(path, leafType) {
    const parts = parsePath(path);
    let obj = CONFIG;
    for (let i = 0; i < parts.length; i++) {
        const p = parts[i];
        if (obj[p] === undefined) {
            obj[p] = (i === parts.length - 1)
                ? (leafType === 'dict' ? {} : [])
                : {};
        }
        obj = obj[p];
    }
    return obj;
}

// ── In-page dialogs ──
// A native confirm()/prompt() is a modal of the BROWSER: it cannot be styled,
// it cannot be translated and it blocks the main thread while it is up
// (CLAUDE.md, "Frontend"; scripts/smoke_no_native_dialogs.py). These two build
// the same question as an overlay of this page and resolve a Promise, so the
// call sites keep reading top to bottom.
function _askOverlay(build) {
    return new Promise(resolve => {
        const bg = document.createElement('div');
        bg.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.6);'
            + 'display:flex;align-items:center;justify-content:center;z-index:1000;';
        const box = document.createElement('div');
        box.style.cssText = 'background:#161b22;border:1px solid #30363d;'
            + 'border-radius:8px;padding:20px;width:420px;max-width:92vw;color:#e6edf3;';
        bg.appendChild(box);
        let done = false;
        const close = value => {
            if (done) return;
            done = true;
            document.removeEventListener('keydown', onKey);
            bg.remove();
            resolve(value);
        };
        const onKey = ev => {
            if (ev.key === 'Escape') { ev.preventDefault(); close(null); }
        };
        document.addEventListener('keydown', onKey);
        // A click on the backdrop itself (not inside the box) cancels.
        bg.addEventListener('mousedown', ev => { if (ev.target === bg) close(null); });
        build(box, close);
        document.body.appendChild(bg);
    });
}

function _askButtonRow(box, okLabel, okClass, onOk, onCancel) {
    const row = document.createElement('div');
    row.style.cssText = 'display:flex;gap:8px;justify-content:flex-end;margin-top:16px;';
    const cancel = document.createElement('button');
    cancel.className = 'btn';
    cancel.textContent = 'Cancel';
    cancel.onclick = onCancel;
    const ok = document.createElement('button');
    ok.className = 'btn ' + okClass;
    ok.textContent = okLabel;
    ok.onclick = onOk;
    row.appendChild(cancel);
    row.appendChild(ok);
    box.appendChild(row);
    return ok;
}

// Yes/no question. Resolves true only when the user confirms.
function askConfirm(message, okLabel) {
    return _askOverlay((box, close) => {
        const p = document.createElement('p');
        p.style.cssText = 'margin:0;font-size:14px;line-height:1.5;';
        p.textContent = message;
        box.appendChild(p);
        const ok = _askButtonRow(box, okLabel || 'OK', 'btn-danger',
            () => close(true), () => close(false));
        setTimeout(() => ok.focus(), 0);
    });
}

// One line of text. Resolves the string, or null when the user cancels.
function askText(message, defaultValue) {
    return _askOverlay((box, close) => {
        const label = document.createElement('label');
        label.style.cssText = 'display:block;font-size:13px;margin-bottom:8px;';
        label.textContent = message;
        box.appendChild(label);
        const input = document.createElement('input');
        input.type = 'text';
        input.value = defaultValue || '';
        input.style.cssText = 'width:100%;background:#0d1117;color:#c9d1d9;'
            + 'border:1px solid #30363d;border-radius:6px;padding:6px 10px;font-size:13px;';
        input.onkeydown = ev => {
            if (ev.key === 'Enter') { ev.preventDefault(); close(input.value); }
        };
        box.appendChild(input);
        _askButtonRow(box, 'OK', 'btn-primary',
            () => close(input.value), () => close(null));
        setTimeout(() => { input.focus(); input.select(); }, 0);
    });
}

// ── Actions ──
async function addArrayItem(path, type) {
    let obj;
    if (type === 'dict') {
        const id = await askText('New entry key:', '');
        if (!id) return;
        // Keep the key dot-free: the editor addresses fields via dot notation
        // and split('.') breaks on a dot INSIDE the key. The display name
        // keeps the original input.
        const key = id.replace(/[.\[\]]/g, ' ').replace(/\s+/g, ' ').trim();
        if (!key) { toast('Invalid key', 'error'); return; }
        obj = getVal(path) || {};
        if (obj[key] !== undefined) { toast('Entry already exists: ' + key, 'error'); return; }
        touchPath(path);
        obj = _ensureContainer(path, type);
        obj[key] = { name: id };
        // Select the new entry in the master-detail view (no-op for accordion).
        SELECTED_ITEM[path] = path + '.' + key;
    } else {
        touchPath(path);
        obj = _ensureContainer(path, type);
        if (path === 'llm_routing') {
            obj.push({ name: '', enabled: true, preload_on_startup: false, provider: '', model: '', temperature: 0.7, tasks: [] });
        } else if (path === 'content_marketplace.catalogs') {
            obj.push({ name: '', url: '', auth_token: '', enabled: true });
        } else {
            obj.push({ name: 'New', enabled: true });
        }
        SELECTED_ITEM[path] = path + '[' + (obj.length - 1) + ']';
    }
    renderSection(ACTIVE_SECTION);
}

async function removeItem(path) {
    if (!await askConfirm('Remove this item?', 'Remove')) return;
    touchPath(path);
    const parts = parsePath(path);
    let obj = CONFIG;
    for (let i = 0; i < parts.length - 1; i++) {
        obj = obj[parts[i]];
    }
    const last = parts[parts.length - 1];
    if (typeof last === 'number') {
        obj.splice(last, 1);
    } else {
        delete obj[last];
    }
    // Reset the master-detail selection — renderMasterDetail then falls back
    // to the first remaining entry.
    const arrPath = (typeof last === 'number')
        ? path.replace(/\[\d+\]$/, '')
        : path.replace(/\.[^.\[\]]+$/, '');
    if (arrPath === 'llm_routing') remapRoutingJsonDrafts(last, true);
    delete SELECTED_ITEM[arrPath];
    renderSection(ACTIVE_SECTION);
}

// Duplicates an array or dict entry (LLM routing, backends, ...). For dicts
// a new key is prompted; for arrays the clone is appended after the original.
// `name` fields get a "(copy)" suffix so the duplicate is distinguishable.
async function duplicateItem(path) {
    const parts = parsePath(path);
    let parent = CONFIG;
    for (let i = 0; i < parts.length - 1; i++) {
        parent = parent[parts[i]];
    }
    const last = parts[parts.length - 1];
    const original = (typeof last === 'number') ? parent[last] : parent[last];
    if (!original) { toast('Entry not found', 'error'); return; }
    // Deep clone — defaults must not be shared with the original.
    const copy = JSON.parse(JSON.stringify(original));
    if (copy && typeof copy === 'object' && 'name' in copy && copy.name) {
        copy.name = String(copy.name) + ' (copy)';
    }
    if (typeof last === 'number') {
        // Array: insert right behind the original
        touchPath(path);
        parent.splice(last + 1, 0, copy);
        const arrPath = path.replace(/\[\d+\]$/, '');
        if (arrPath === 'llm_routing') remapRoutingJsonDrafts(last, false);
        SELECTED_ITEM[arrPath] = arrPath + '[' + (last + 1) + ']';
    } else {
        // Dict: ask the user for a new key — keep it dot-free (the editor's
        // dot notation breaks otherwise, see addArrayItem).
        const rawKey = await askText('New key for the clone:', String(last) + '_copy');
        if (!rawKey) return;
        const newKey = rawKey.replace(/[.\[\]]/g, ' ').replace(/\s+/g, ' ').trim();
        if (!newKey) { toast('Invalid key', 'error'); return; }
        if (parent[newKey] !== undefined) { toast('Key already exists: ' + newKey, 'error'); return; }
        touchPath(parts.slice(0, -1).join('.') + '.' + newKey);
        parent[newKey] = copy;
        const arrPath = path.replace(/\.[^.\[\]]+$/, '');
        SELECTED_ITEM[arrPath] = arrPath + '.' + newKey;
    }
    renderSection(ACTIVE_SECTION);
}

async function providerModelNames(provider) {
    if (!provider) throw new Error('Select a provider first');
    if (PROVIDERS_CACHE[provider]?.length) return PROVIDERS_CACHE[provider];
    const resp = await fetch('/admin/settings/providers/' + encodeURIComponent(provider) + '/models', { credentials: 'same-origin' });
    const data = await resp.json();
    if (!resp.ok || data.error) throw new Error(data.error || 'Failed to load models');
    const names = data.models || [];
    if (names.length) {
        PROVIDERS_CACHE[provider] = names;
        PROVIDERS_VISION[provider] = new Set(data.vision || []);
    }
    return names;
}
async function loadModels(path) {
    return providerModelNames(getVal(path.replace(/\.model$/, '.provider')));
}
function refreshModelSelect(provPath) {
    const input = document.getElementById('f-' + provPath.replace(/\.provider$/, '.model'));
    if (input?.modelCombobox) input.modelCombobox.reload();
}

async function validateConfig() {
    const btn = document.getElementById('btn-validate');
    btn.disabled = true;
    btn.textContent = 'Validating...';
    try {
        const resp = await fetch('/admin/settings/validate', {
            method: 'POST',
            headers: authHeaders(),
            body: JSON.stringify(CONFIG)
        });
        const result = await resp.json();
        const issues = result.issues || [];
        const content = document.getElementById('content');

        let html = '<div class="validate-results ' + (result.errors > 0 ? 'has-errors' : 'all-ok') + '">';
        if (issues.length === 0) {
            html += '<h3>No issues found</h3>';
        } else {
            html += '<h3>' + esc(result.errors) + ' errors, ' + esc(result.warnings) + ' warnings</h3>';
            for (const issue of issues) {
                html += '<div class="validate-issue ' + esc(issue.level) + '">';
                html += '<span class="badge">' + (issue.level === 'error' ? 'ERROR' : 'WARN') + '</span>';
                html += '<span>' + esc(issue.message) + '</span>';
                html += '<span class="section-link" onclick="activateSection(\'' + sJs(issue.section) + '\')">' + esc(issue.section) + '</span>';
                html += '</div>';
            }
        }
        html += '</div>';

        // Show below current section or as standalone
        if (ACTIVE_SECTION && !ACTIVE_SECTION.startsWith('_')) {
            content.insertAdjacentHTML('afterbegin', html);
        } else {
            content.innerHTML = html;
        }
        if (result.errors > 0) toast(result.errors + ' errors found', 'error');
        else if (result.warnings > 0) toast(result.warnings + ' warnings', 'success');
        else toast('All OK!', 'success');
    } catch (e) {
        toast('Validation failed: ' + e.message, 'error');
    }
    btn.disabled = false;
    btn.textContent = 'Validate';
}

// Generic action-button handler — sends POST/DELETE/etc. to an endpoint with a
// body built from the named sibling fields. Used by schema type "button".
async function runActionButton(endpoint, method, path, bodyFrom, confirmMsg, btn, previewUrl) {
    if (confirmMsg && !await askConfirm(confirmMsg)) return;
    const body = {};
    // Read values from the DOM (freshest source — also when the user typed but
    // has not saved yet). Fallback to CONFIG, then to the f-input element's
    // value as a last resort for defaults.
    for (const fld of (bodyFrom || [])) {
        const sibling = path + '.' + fld;
        let v = undefined;
        // 1. Try the DOM input directly
        const el = document.getElementById('f-' + sibling);
        if (el && 'value' in el) {
            v = el.value;
        }
        // 2. Fallback: stored CONFIG value
        if (v === undefined || v === null || v === '') {
            v = getVal(sibling);
        }
        if (v !== undefined && v !== null && v !== '') body[fld] = v;
    }
    const origLabel = btn.textContent;
    btn.disabled = true;
    btn.textContent = '⏳ ' + origLabel;
    try {
        const opts = { method, headers: authHeaders(), credentials: 'same-origin' };
        if (method !== 'GET' && method !== 'DELETE') {
            opts.headers['Content-Type'] = 'application/json';
            opts.body = JSON.stringify(body);
        }
        const resp = await fetch(endpoint, opts);
        const data = await resp.json().catch(() => ({}));
        if (resp.ok) {
            const detail = data.bbox ? ` (bbox ${data.bbox.w}×${data.bbox.h})` : '';
            toast((data.status || 'OK') + detail, 'success');
            // Reload the preview image (cache bust via timestamp) and refresh its meta
            if (previewUrl) {
                document.querySelectorAll('img[src^="' + previewUrl + '"]').forEach(img => {
                    img.src = previewUrl + '?_=' + Date.now();
                    img.style.display = '';
                    if (img.nextElementSibling) img.nextElementSibling.style.display = 'none';
                });
                if (typeof populateImagePreviewMetas === 'function') {
                    populateImagePreviewMetas();
                }
            }
        } else {
            toast('Error: ' + (data.detail || data.error || resp.status), 'error');
        }
    } catch (e) {
        toast('Call failed: ' + e.message, 'error');
    }
    btn.disabled = false;
    btn.textContent = origLabel;
}

async function saveConfig() {
    if (!validateJsonObjectsBeforeSave()) return;
    const btn = document.getElementById('btn-save');
    btn.disabled = true;
    btn.textContent = 'Saving...';
    const submittedRevision = MUTATION_REVISION;
    const submittedResets = [...RESETS];
    try {
        // Snapshot the payload so confirmation resends exactly the same edits.
        const body = JSON.stringify({ values: CONFIG, resets: submittedResets, base_revision: CONFIG_REVISION });
        const send = payload => fetch('/admin/settings/save', {
            method: 'POST',
            headers: authHeaders(),
            body: payload
        });
        let resp = await send(body);
        let result = await resp.json();
        if (!resp.ok && result.detail && result.detail.code === 'would_drop') {
            const paths = result.detail.paths;
            const ok = await askConfirm('This save would remove: ' + paths.join(', ')
                + '. If this page is older than your last change, cancel and reload instead.', 'Remove');
            if (!ok) {
                toast('Save cancelled — nothing was changed.');
                return;
            }
            resp = await send(JSON.stringify({ ...JSON.parse(body), confirm_drop: paths }));
            result = await resp.json();
        }
        // The image routing Rules page keeps the outcome (a refused chain,
        // save warnings) on screen — a toast is gone after three seconds.
        if (typeof imageRoutingSaveResult === 'function') imageRoutingSaveResult(resp.ok, result);
        if (!resp.ok && result.detail && (result.detail.code === 'stale'
            || result.detail.code === 'revision_required')) {
            const paths = Array.isArray(result.detail.paths) ? result.detail.paths : [];
            const message = result.detail.code === 'revision_required'
                ? 'This page has no settings version. Reload it.'
                : 'Settings changed elsewhere since this page was loaded'
                    + (paths.length ? ': ' + paths.join(', ') : '')
                    + '. Reload to see them; your unsaved edits on this page are lost.';
            if (await askConfirm(message, 'Reload')) location.reload();
            else toast('Not saved — the page is out of date.', 'error');
            return;
        }
        if (resp.ok) {
            CONFIG_REVISION = result.revision;
            OVERRIDES = new Set(result.overrides || []);
            // A newer edit or reset must remain pending, including a reset
            // repeated for a submitted path. Conservatively retain all resets
            // when the configuration changed during the request.
            if (MUTATION_REVISION === submittedRevision) {
                for (const path of submittedResets) RESETS.delete(path);
                DIRTY = false;
            }
            const content = document.getElementById('content');
            const top = content.scrollTop;
            buildNav();
            await renderSection(ACTIVE_SECTION, ACTIVE_PAGE);
            content.scrollTop = top;
            // URL/key changes should apply immediately, without a page reload:
            // invalidate the provider and imagegen backend model caches.
            for (const k of Object.keys(PROVIDERS_CACHE)) delete PROVIDERS_CACHE[k];
            for (const k of Object.keys(IMAGEGEN_MODELS_CACHE)) delete IMAGEGEN_MODELS_CACHE[k];
            toast(result.message || 'Saved!', 'success');
            // After saving, check whether fields that need a restart changed.
            loadRestartPending();
        } else {
            toast('Error: ' + ((typeof result.detail === 'object' && result.detail !== null
                ? result.detail.message : result.detail) || result.message || resp.status), 'error');
        }
    } catch (e) {
        toast('Save failed: ' + e.message, 'error');
    }
    finally {
        btn.disabled = false;
        btn.textContent = DIRTY ? 'Save*' : 'Save';
    }
}

async function loadRestartPending() {
    try {
        const resp = await fetch('/admin/settings/restart-pending', { credentials: 'same-origin' });
        if (!resp.ok) return;
        const data = await resp.json();
        renderRestartBanner(data.pending || []);
    } catch (e) {
        // The banner is not critical — stay quiet on failure.
    }
}

function renderRestartBanner(pending) {
    const banner = document.getElementById('restart-banner');
    const slot = document.getElementById('restart-banner-fields');
    if (!banner || !slot) return;
    if (!pending || pending.length === 0) {
        banner.style.display = 'none';
        slot.innerHTML = '';
        return;
    }
    slot.innerHTML = pending.map(p => '<code>' + esc(p) + '</code>').join(' ');
    banner.style.display = 'block';
}

function togglePw(btn) {
    const input = btn.parentElement.querySelector('input');
    input.type = input.type === 'password' ? 'text' : 'password';
}

// ── Helpers ──
// A value that ends up INSIDE an inline handler's single-quoted JS literal,
// e.g. onclick="fn('…')": escape it for the JS string first, then for the
// double-quoted HTML attribute. Same shape as rtJs() in settings-routing.js.
// Config paths carry raw dict keys from config.json, so they need both steps.
function sJs(s) {
    return esc(String(s == null ? '' : s).replace(/\\/g, '\\\\').replace(/'/g, "\\'"));
}

// A URL from data before it goes into src=/href=: only a relative path or
// http(s) may pass. Anything else — javascript:, vbscript:, data: — is dropped.
function safeUrl(u) {
    const v = String(u == null ? '' : u).replace(/[\u0000-\u001F\u007F]/g, '').trim();
    if (!v || v.startsWith('//')) return '';
    if (/^https?:\/\//i.test(v)) return v;
    if (/^[a-z][a-z0-9+.\-]*:/i.test(v)) return '';
    return v;
}

function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function toast(msg, type) {
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.className = 'toast ' + type + ' show';
    setTimeout(() => t.classList.remove('show'), 3000);
}

// Start
init();
