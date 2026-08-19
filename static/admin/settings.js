
let CONFIG = {};
let SCHEMA = {};
let USE_CASE_DEFAULTS = { use_cases: [], families: [], defaults: {} };
let PROVIDERS_CACHE = {};
let PROVIDERS_VISION = {};  // provName -> Set(vision model names)
// Runtime state of the media backends (name -> {available, cooldown_seconds,
// cooldown_reason, ...}) — merged into the backends table's Status column.
let MEDIA_STATUS = {};
let ACTIVE_SECTION = null;
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
        const [dataResp, schemaResp] = await Promise.all([
            fetch('/admin/settings/raw', { credentials: 'same-origin' }),
            fetch('/admin/settings/schema', { credentials: 'same-origin' })
        ]);
        if (dataResp.status === 401 || dataResp.status === 403) {
            const ret = encodeURIComponent(window.location.pathname + window.location.hash);
            window.location.href = '/?return=' + ret;
            return;
        }
        CONFIG = await dataResp.json();
        SCHEMA = await schemaResp.json();
        try {
            const ucResp = await fetch('/admin/settings/use-case-defaults', { credentials: 'same-origin' });
            if (ucResp.ok) USE_CASE_DEFAULTS = await ucResp.json();
        } catch (e) { /* defaults stay empty */ }
        await loadMediaStatus();
        buildNav();
        // Activate first section
        const first = Object.keys(SCHEMA)[0];
        if (first) activateSection(first);
        // Restart-Banner: nach Init pruefen, ob etwas pending ist (z.B. wenn
        // ein anderer Tab kuerzlich gespeichert hat).
        loadRestartPending();
    } catch (e) {
        document.getElementById('content').innerHTML = '<div class="loading" style="color:#f85149;">Error loading config: ' + e.message + '</div>';
    }
}

function authHeaders() {
    // Cookie-basiert: Browser sendet Session-Cookie automatisch. Nur Content-Type explizit setzen.
    return { 'Content-Type': 'application/json' };
}

// ── Navigation ──
function buildNav() {
    const nav = document.getElementById('nav-links');
    nav.innerHTML = '';
    for (const [key, sec] of Object.entries(SCHEMA)) {
        const a = document.createElement('a');
        a.href = '#' + key;
        // nav_sub: als eingerueckter Unterpunkt rendern (z.B. LLM Routing unter
        // der einfachen LLM-Models-Seite).
        if (sec.nav_sub) {
            a.className = 'nav-sub';
            a.innerHTML = '<span class="nav-icon">›</span> ' + sec.label;
        } else {
            a.innerHTML = '<span class="nav-icon">' + (sec.icon || '') + '</span> ' + sec.label;
        }
        a.dataset.section = key;
        a.onclick = (e) => { e.preventDefault(); activateSection(key); };
        nav.appendChild(a);
        // Sub-arrays (e.g. backends) as indented sub-items — each gets its
        // own page (key "<sec>::<arr>").
        if (sec.sub_arrays) {
            for (const [arrKey, arrDef] of Object.entries(sec.sub_arrays)) {
                const subKey = key + '::' + arrKey;
                const sa = document.createElement('a');
                sa.className = 'nav-sub';
                sa.href = '#' + subKey;
                sa.innerHTML = '<span class="nav-icon">›</span> ' + arrDef.label;
                sa.dataset.section = subKey;
                sa.onclick = (e) => { e.preventDefault(); activateSection(subKey); };
                nav.appendChild(sa);
            }
        }
    }
}

function activateSection(key) {
    ACTIVE_SECTION = key;
    // Update nav
    document.querySelectorAll('.sidebar a').forEach(a => a.classList.remove('active'));
    const link = document.querySelector('.sidebar a[data-section="' + key + '"]');
    if (link) link.classList.add('active');
    // Show settings toolbar, restore content mode
    document.getElementById('settings-toolbar').style.display = 'flex';
    const content = document.getElementById('content');
    content.classList.remove('iframe-mode');
    // Render section
    renderSection(key);
}

function activateIframe(key, url, title) {
    ACTIVE_SECTION = key;
    // Update nav
    document.querySelectorAll('.sidebar a').forEach(a => a.classList.remove('active'));
    const link = document.querySelector('.sidebar a[data-section="' + key + '"]');
    if (link) link.classList.add('active');
    // Hide settings toolbar
    document.getElementById('settings-toolbar').style.display = 'none';
    // Load iframe
    const content = document.getElementById('content');
    content.classList.add('iframe-mode');
    content.innerHTML = '<iframe src="' + url + '" title="' + esc(title) + '"></iframe>';
}

// World-Badge im Sidebar — auf jeder Seite + iframe-Children einsehbar.
fetch('/admin/world-name', { credentials: 'same-origin', cache: 'no-store' })
  .then(r => r.ok ? r.json() : null)
  .then(d => {
      const el = document.getElementById('world-name');
      if (el && d && d.world) el.textContent = d.world;
  })
  .catch(() => {});

// ── Render Section ──
// Master-Detail-Editor fuer image_generation.use_cases (links Use-Case-Liste,
// rechts Familien × Style/Negative/Instruction). Leeres Feld zeigt den
// eingebauten Default als grauen Placeholder.
function renderUseCasesMasterDetail(path) {
    const D = USE_CASE_DEFAULTS || { use_cases: [], families: [], defaults: {} };
    const ucs = D.use_cases || [];
    let sel = SELECTED_ITEM[path];
    if (ucs.indexOf(sel) === -1) sel = ucs.length ? ucs[0] : null;
    SELECTED_ITEM[path] = sel;
    let html = '<p class="hint" style="opacity:.7;margin-bottom:12px">'
          + 'Style / Negative / Instruction pro Use-Case × Familie. Leeres Feld = eingebauter Default (grau). '
          + 'Which family applies is determined by the <b>Image Family</b> of the backend.</p>';
    html += '<div class="md-grid"><div class="md-list"><table class="md-table"><thead><tr><th>Use-Case</th></tr></thead><tbody>';
    for (const uc of ucs) {
        const active = (uc === sel) ? ' active' : '';
        html += '<tr class="md-row' + active + '" onclick="selectMasterItem(\'' + path + '\', \'' + uc + '\')"><td>' + esc(uc) + '</td></tr>';
    }
    html += '</tbody></table></div>';
    html += '<div class="md-detail">' + renderUseCaseDetail(sel) + '</div></div>';
    return html;
}

function renderUseCaseDetail(uc) {
    if (!uc) return '<div class="md-empty-detail">Use-Case links auswaehlen.</div>';
    const D = USE_CASE_DEFAULTS || { families: [], defaults: {} };
    const FIELDS = [['prompt_style', 'Style'], ['prompt_negative', 'Negative'], ['prompt_instruction', 'Instruction']];
    let html = '<div class="md-detail-head"><span class="md-detail-title">' + esc(uc) + '</span></div>';
    // Opt-in LLM stage — per USE CASE, not per family: it rewrites whatever
    // the mechanical composer produced, in that family's voice.
    const llmPath = 'image_generation.use_cases.' + uc + '.llm_compose';
    html += '<div class="field" style="margin:0 0 14px 0">'
          + '<label style="font-size:.85em;display:flex;align-items:center;gap:6px">'
          + '<input type="checkbox" ' + (getVal(llmPath) ? 'checked' : '') + ' '
          + 'onchange="setVal(\'' + llmPath + '\', this.checked)"> Compose via LLM (opt-in)</label>'
          + '<div class="hint" style="opacity:.7;font-size:.78em;margin-top:2px">'
          + 'When enabled, an LLM rewrites the composed prompt into one coherent, '
          + 'positively-exhaustive English prompt. Shown editable in the render dialog.</div>'
          + '<div style="margin-top:6px;display:flex;align-items:center;gap:8px">'
          + '<button type="button" class="btn btn-sm" onclick="clearComposeCache(this)">Clear LLM compose cache</button>'
          + '<span class="hint" style="opacity:.7;font-size:.78em" id="compose-cache-size"></span></div></div>';
    loadComposeCacheSize();
    for (const fam of (D.families || [])) {
        html += '<div style="margin:4px 0 16px 0;padding-left:8px;border-left:2px solid var(--border,#30363d)">';
        html += '<div style="opacity:.6;font-size:.8em;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px">' + esc(fam) + '</div>';
        for (const fp of FIELDS) {
            const fld = fp[0], lbl = fp[1];
            const p = 'image_generation.use_cases.' + uc + '.styles.' + fam + '.' + fld;
            const val = getVal(p) || '';
            const def = (((D.defaults || {})[uc] || {})[fam] || {})[fld] || '';
            // „Copy default": fuellt das leere Feld mit dem eingebauten Default,
            // damit man ihn als Ausgangspunkt bearbeiten kann (sonst nur grauer
            // Placeholder). Nur anbieten, wenn ein Default existiert und das Feld
            // leer ist (kein versehentliches Ueberschreiben eigener Eingaben).
            const copyBtn = (def && !val)
                ? ' <button type="button" class="btn btn-sm" '
                  + 'style="margin-left:8px;font-size:.72em;padding:1px 6px;vertical-align:middle" '
                  + 'title="Copy the built-in default into this field to edit it" '
                  + 'onclick="copyUseCaseDefault(\'' + p + '\', \'' + uc + '\', \'' + fam + '\', \'' + fld + '\')">Copy default</button>'
                : '';
            html += '<div class="field" style="margin-bottom:8px"><label style="font-size:.8em;opacity:.8">' + esc(lbl) + copyBtn + '</label>';
            html += '<textarea rows="2" style="width:100%;font-family:inherit;resize:vertical" '
                  + 'placeholder="' + esc(def) + '" '
                  + 'onchange="setVal(\'' + p + '\', this.value)">' + esc(val) + '</textarea>';
            // The subject slot: the composer weaves the subject INTO the style
            // sentence where the placeholder sits (early tokens steer diffusion).
            if (fld === 'prompt_style') {
                html += '<div class="hint" style="opacity:.7;font-size:.78em;margin-top:2px">'
                      + 'Optional placeholder <code>{subject}</code> — replaced with the subject text; '
                      + 'without it the subject is appended.</div>';
            }
            html += '</div>';
        }
        html += '</div>';
    }
    return html;
}

// „Copy default": schreibt den eingebauten Use-Case-Default in das Feld, damit
// man ihn bearbeiten kann. uc/fam/fld bestimmen den Default, p ist der Setz-Pfad.
async function loadComposeCacheSize() {
    const el = document.getElementById('compose-cache-size');
    if (!el) return;
    try {
        const r = await fetch('/world/compose-cache', { credentials: 'same-origin', cache: 'no-store' });
        const d = await r.json();
        el.textContent = (d.entries || 0) + ' cached prompts';
    } catch (e) { el.textContent = ''; }
}

async function clearComposeCache(btn) {
    // The cache keys on every input, so it never expires on its own — this
    // button is the only way to make "Compose with AI" start from scratch
    // for unchanged inputs (e.g. after a model swap).
    if (btn) btn.disabled = true;
    try {
        const r = await fetch('/world/compose-cache/clear', { method: 'POST', credentials: 'same-origin' });
        const d = await r.json();
        toast('LLM compose cache cleared (' + (d.cleared || 0) + ' entries)');
    } catch (e) {
        toast('Could not clear the compose cache', 'error');
    } finally {
        if (btn) btn.disabled = false;
        loadComposeCacheSize();
    }
}

function copyUseCaseDefault(p, uc, fam, fld) {
    const D = USE_CASE_DEFAULTS || { defaults: {} };
    const def = (((D.defaults || {})[uc] || {})[fam] || {})[fld] || '';
    if (!def) return;
    setVal(p, def);
    renderSection(ACTIVE_SECTION);
}

// Repository: LoRA -> activation word. ONE entry per unique LoRA — {lora,
// word, source, backends, missing_on}; the image-creation code automatically
// prepends the word to the prompt whenever the LoRA is used. Stored in
// image_generation.lora_triggers (per world). The discovery sync job
// consolidates every backend with a LoRA Query URL into this list; every
// LoRA dropdown in the UI feeds from this library, scoped to its backend.
function renderLoraTriggersEditor(path) {
    const items = getVal(path) || [];
    let html = '<p class="hint" style="opacity:.7;margin-bottom:12px">'
             + 'Central LoRA library of the world — <b>every LoRA dropdown</b> (game admin + player UI) '
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
          + '<button class="btn btn-sm" onclick="addLoraTrigger(\'' + path + '\')">+ Add</button>'
          + '<button class="btn btn-sm" onclick="syncLoraLibrary()">⟳ Discover now</button>'
          + '<button class="btn btn-sm btn-danger" onclick="clearDiscoveredLoras()">🗑 Delete discovered</button></div>';
    if (!items.length) {
        html += '<div class="md-empty">No entries yet. "Discover now" scans the backends; "+ Add" creates a manual entry.</div>';
    }
    for (let i = 0; i < items.length; i++) {
        const it = items[i] || {};
        const ip = path + '[' + i + ']';
        const isManual = (it.source || 'manual') !== 'discovered';
        const backends = Array.isArray(it.backends) ? it.backends : [];
        const missingOn = Array.isArray(it.missing_on) ? it.missing_on : [];
        html += '<div class="lora-row" style="display:flex;gap:8px;align-items:flex-start;margin-bottom:6px">';
        // Column 1: LoRA name (free text; renaming a discovered entry makes
        // it a manual claim — ltRename also warns on duplicate names).
        html += '<input type="text" autocomplete="off" value="' + esc(it.lora || '') + '" '
              + 'placeholder="LoRA name (as the backend lists it)" style="flex:3;min-width:0" '
              + 'onchange="ltRename(\'' + ip + '\', this)">';
        // Column 2: activation word.
        html += '<input type="text" value="' + esc(it.word || '') + '" placeholder="Activation word" '
              + 'style="flex:2;min-width:0" onchange="ltTouch(\'' + ip + '\', \'word\', this.value); setVal(\'' + ip + '.word\', this.value)">';
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
                              + 'onclick="ltRemoveBackend(\'' + ip + '\', \'' + esc(bn) + '\')">✕</a>' : '')
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
                      + 'onchange="ltAddBackend(\'' + ip + '\', this.value)">'
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
        html += '<button class="btn btn-sm btn-danger" title="Delete" onclick="removeItem(\'' + ip + '\')">✕</button>';
        html += '</div>';
    }
    return html;
}

function addLoraTrigger(path) {
    const arr = _ensureContainer(path, 'array');
    arr.push({ lora: '', word: '', source: 'manual', backends: [], missing_on: [] });
    renderSection(ACTIVE_SECTION);
}

// Assign/remove a backend on a manual entry's chip list. Removing a backend
// also clears its missing flag; an empty list means "all backends".
function ltAddBackend(ip, name) {
    if (!name) return;
    const e = getVal(ip) || {};
    if (!Array.isArray(e.backends)) e.backends = [];
    if (e.backends.indexOf(name) === -1) e.backends.push(name);
    renderSection(ACTIVE_SECTION);
}

function ltRemoveBackend(ip, name) {
    const e = getVal(ip) || {};
    e.backends = (e.backends || []).filter(function (b) { return b !== name; });
    e.missing_on = (e.missing_on || []).filter(function (b) { return b !== name; });
    renderSection(ACTIVE_SECTION);
}

// Rename handler for the LoRA name — flips discovered -> manual and warns on
// a duplicate name (entries are unique per LoRA; the sync and the dropdowns
// only honor the first occurrence).
function ltRename(ip, inp) {
    const v = inp.value;
    ltTouch(ip, 'lora', v);
    setVal(ip + '.lora', v);
    if (!v) return;
    const items = (CONFIG.image_generation && CONFIG.image_generation.lora_triggers) || [];
    let count = 0;
    for (const it of items) { if (it && (it.lora || '') === v) count++; }
    if (count > 1) toast('Duplicate LoRA name — only the first entry counts', 'error');
}

// Editing a discovered entry turns it into a manual claim: the sync job then
// flags it as missing instead of silently removing it when it vanishes.
// Only flips when the value actually changed (focus/no-op edits don't count).
function ltTouch(ip, field, newVal) {
    if ((getVal(ip + '.' + field) || '') === (newVal || '')) return;
    if (getVal(ip + '.source') === 'discovered') setVal(ip + '.source', 'manual');
}

// Remove all discovered entries server-side (manual ones stay) — reset
// helper to re-test the per-backend LoRA filter with a clean discovery run.
async function clearDiscoveredLoras() {
    try {
        const resp = await fetch('/admin/settings/lora-library/clear-discovered', {
            method: 'POST', headers: authHeaders(),
        });
        const d = await resp.json();
        if (!resp.ok) throw new Error((d && d.detail) || ('HTTP ' + resp.status));
        if (!CONFIG.image_generation) CONFIG.image_generation = {};
        CONFIG.image_generation.lora_triggers = d.lora_triggers || [];
        toast('Removed ' + (d.removed || 0) + ' discovered entr' + ((d.removed || 0) === 1 ? 'y' : 'ies'), 'success');
        renderSection(ACTIVE_SECTION);
    } catch (e) {
        toast('Delete discovered failed: ' + e.message, 'error');
    }
}

// Run the server-side discovery sync and refresh the editor in place. The
// server persists the result itself — CONFIG only mirrors it for rendering.
async function syncLoraLibrary() {
    try {
        const resp = await fetch('/admin/settings/lora-library/sync', {
            method: 'POST', headers: authHeaders(),
        });
        const d = await resp.json();
        if (!resp.ok) throw new Error((d && d.detail) || ('HTTP ' + resp.status));
        if (!CONFIG.image_generation) CONFIG.image_generation = {};
        CONFIG.image_generation.lora_triggers = d.lora_triggers || [];
        const scanned = (d.scanned || []).length;
        toast('LoRA sync: ' + scanned + ' backend(s) scanned — '
            + (d.added || 0) + ' added, ' + (d.removed || 0) + ' removed, '
            + (d.missing || 0) + ' missing', 'success');
        renderSection(ACTIVE_SECTION);
    } catch (e) {
        toast('LoRA sync failed: ' + e.message, 'error');
    }
}

function renderSection(key) {
    // Compound-Key "<section>::<subArray>" -> eigene Sub-Array-Seite.
    if (key.indexOf('::') !== -1) { renderSubArrayPage(key); return; }
    // Einfache, kategorie-basierte LLM-Seite (befuellt CONFIG.llm_routing).
    if (key === 'llm_simple') { renderLlmSimpleEditor(); return; }
    const sec = SCHEMA[key];
    // null und undefined beide auf Default fallen lassen — sonst wirft
    // renderFields(null, ...) bei data[fKey] einen TypeError.
    const cfgVal = CONFIG[key];
    const data = (cfgVal !== undefined && cfgVal !== null) ? cfgVal : (sec.is_array ? [] : {});
    const content = document.getElementById('content');

    let html = '<div class="section active">';
    html += '<h1 class="section-title">' + (sec.icon || '') + ' ' + sec.label + '</h1>';
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
            const subData = data[subKey] || {};
            html += '<div class="subsection">';
            html += '<div class="subsection-title">' + sub.label + '</div>';
            html += renderFields(sub.fields, subData, key + '.' + subKey);
            html += '</div>';
        }
    }

    // Sub-arrays (backends, catalogs) are NOT rendered here — each has its
    // own nav sub-item (see buildNav /
    // renderSubArrayPage), so the main page does not get overloaded.

    // Array sections (providers)
    if (sec.is_array) {
        if (key === 'llm_routing') {
            // Two columns: editor on the left, read-only task view on the right
            html += '<div style="display:grid; grid-template-columns: 1fr 1fr; gap:20px;">';
            html += '<div>';
            html += '<div style="margin-bottom: 12px;">';
            html += '<button class="btn btn-sm" onclick="addArrayItem(\'' + key + '\', \'array\')">+ Add LLM</button>';
            html += '</div>';
            html += renderArrayItems(sec, data || [], key);
            html += '</div>';
            html += '<div>';
            html += '<div class="subsection-title" style="margin-bottom:8px;">' + ROUTING_TEXT.perTaskView + '</div>';
            html += '<div id="llm-task-view"><div class="desc">Loading…</div></div>';
            html += '</div>';
            html += '</div>';
            // The tool/helper suitability test now lives under "Model Capabilities".
            html += '<div class="desc" style="margin-top:16px;">🧪 The Tool/Helper suitability test moved to <a href="/admin/models" target="_blank" style="color:#58a6ff;">Model Capabilities</a>.</div>';
            setTimeout(() => renderLlmTaskView(data || []), 0);
        } else {
            html += '<div style="margin-bottom: 12px;">';
            html += '<button class="btn btn-sm" onclick="addArrayItem(\'' + key + '\', \'array\')">+ Add ' + sec.label + '</button>';
            html += '</div>';
            html += renderArrayItems(sec, data || [], key);
        }
    }

    html += '</div>';
    content.innerHTML = html;
    // image_preview-Felder Meta nachladen (kein <script> via innerHTML moeglich)
    populateImagePreviewMetas();
}

// Eigene Seite fuer ein einzelnes Sub-Array (z.B. image_generation::backends).
function renderSubArrayPage(key) {
    const sep = key.indexOf('::');
    const parentKey = key.slice(0, sep);
    const arrKey = key.slice(sep + 2);
    const sec = SCHEMA[parentKey];
    const arrDef = sec && sec.sub_arrays ? sec.sub_arrays[arrKey] : null;
    const content = document.getElementById('content');
    if (!sec || !arrDef) { content.innerHTML = '<div class="section active"></div>'; return; }
    const parentData = (CONFIG[parentKey] && typeof CONFIG[parentKey] === 'object') ? CONFIG[parentKey] : {};
    const path = parentKey + '.' + arrKey;
    const items = parentData[arrKey] || (arrDef.is_dict ? {} : []);

    let html = '<div class="section active">';
    html += '<h1 class="section-title">' + (sec.icon || '') + ' ' + sec.label + ' — ' + arrDef.label + '</h1>';
    if (arrDef.use_cases_editor) {
        html += renderUseCasesMasterDetail(path);
    } else if (arrDef.lora_triggers_editor) {
        html += renderLoraTriggersEditor(path);
    } else if (arrDef.master_detail) {
        html += renderMasterDetail(arrDef, items, path);
    } else {
        html += '<div style="margin-bottom:12px;"><button class="btn btn-sm" onclick="addArrayItem(\'' + path + '\', \'' + (arrDef.is_dict ? 'dict' : 'array') + '\')">+ Add</button></div>';
        if (arrDef.is_dict) html += renderDictItems(arrDef, items, path);
        else html += renderArrayItems(arrDef, items, path);
    }
    html += '</div>';
    content.innerHTML = html;
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
                    + (d.generated_at ? ' — generiert ' + d.generated_at : '');
            } else {
                el.textContent = 'Noch nicht generiert.';
            }
        } catch (e) { /* ignore */ }
    }
}

// ── Einfache, kategorie-basierte LLM-Seite ──────────────────────────────
// Eine Provider+Model-Auswahl pro Job-Typ; befuellt CONFIG.llm_routing
// (order=1) automatisch. Embedding kann "Internal (built-in)" sein → schreibt
// stattdessen CONFIG.embedding.
const LLM_SIMPLE_CATS = [
    {key:'chat',      label:'Chat & Roleplay',           desc:'The main model your characters chat and roleplay with. Pick your biggest / best writing model.'},
    {key:'tool',      label:'Tools & Decisions',         desc:'Structured decisions and tool-calling (intent, events, outfit generation). Needs a model that reliably follows instructions / returns clean JSON.'},
    {key:'helper',    label:'Helper (small jobs)',       desc:'Cheap background work: summaries, translation, image-prompt cleanup. A small / fast model is fine here.'},
    {key:'image',     label:'Vision (read images)',      desc:'Looks at generated images (recognition / analysis). Needs a vision-capable model.'},
    {key:'embedding', label:'Similarity (pose matching)',desc:'Turns text into vectors so similar poses reuse the same image. Can run built-in on CPU — no server needed.'},
];
const LLM_SIMPLE_TEMP = { chat:0.8, tool:0.1, helper:0.5, image:0.3, embedding:0 };
const LLM_SIMPLE_INTERNAL = '__internal__';
let LLM_SIMPLE_SEL = {};

async function renderLlmSimpleEditor() {
    const content = document.getElementById('content');
    content.innerHTML = '<div class="section active"><h1 class="section-title">🧭 LLM Models (Simple)</h1><div class="desc">Loading…</div></div>';
    const catalog = await loadLlmCatalog();
    llmSimpleDetect(catalog.tasks || []);

    let html = '<div class="section active">';
    html += '<h1 class="section-title">🧭 LLM Models (Simple)</h1>';
    html += '<div class="desc" style="margin-bottom:14px;">Pick one provider + model per job type. This fills the '
         + '<a href="#llm_routing" onclick="event.preventDefault(); activateSection(\'llm_routing\')" style="color:#58a6ff;">Advanced LLM Routing</a> '
         + 'automatically (as primary / order 1). Use the advanced page only for fallbacks and per-task tuning. Press <b>Save</b> when done.</div>';

    const providers = CONFIG.providers || [];
    for (const cat of LLM_SIMPLE_CATS) {
        const sel = LLM_SIMPLE_SEL[cat.key] || {};
        html += '<div class="subsection">';
        html += '<div class="subsection-title">' + esc(cat.label) + '</div>';
        html += '<div class="desc" style="margin-bottom:8px;">' + esc(cat.desc) + '</div>';
        html += '<div style="display:flex; gap:10px; flex-wrap:wrap; align-items:center;">';
        // Provider
        html += '<select id="llmsimple-prov-' + cat.key + '" onchange="llmSimpleSetProvider(\'' + cat.key + '\', this.value)">';
        html += '<option value="">— none —</option>';
        if (cat.key === 'embedding') {
            html += '<option value="' + LLM_SIMPLE_INTERNAL + '"' + (sel.provider === LLM_SIMPLE_INTERNAL ? ' selected' : '') + '>Internal (built-in — no setup)</option>';
        }
        for (const p of providers) {
            html += '<option value="' + esc(p.name) + '"' + (p.name === sel.provider ? ' selected' : '') + '>' + esc(p.name) + ' (' + esc(p.type) + ')</option>';
        }
        html += '</select>';
        // Model
        html += '<select id="llmsimple-model-' + cat.key + '" onchange="llmSimpleSetModel(\'' + cat.key + '\', this.value)" style="min-width:240px;">';
        html += '<option value="' + esc(sel.model || '') + '" selected>' + esc(sel.model || '— select —') + '</option>';
        html += '</select>';
        html += '<button class="btn btn-sm" onclick="llmSimpleLoadModels(\'' + cat.key + '\')">Load Models</button>';
        html += '</div>';
        html += '</div>';
    }
    html += '</div>';
    content.innerHTML = html;
    // Fill the model dropdowns initially (from cache / internal choices)
    for (const cat of LLM_SIMPLE_CATS) llmSimplePopulateModels(cat.key, false);
}

function llmSimpleDetect(tasks) {
    LLM_SIMPLE_SEL = {};
    const routing = CONFIG.llm_routing || [];
    const catOf = {};
    for (const t of (tasks || [])) catOf[t.id] = t.category;
    for (const cat of LLM_SIMPLE_CATS) {
        const tally = {};
        for (const e of routing) {
            if (e.enabled === false) continue;
            for (const t of (e.tasks || [])) {
                if ((t.order || 1) !== 1) continue;
                if (catOf[t.task] !== cat.key) continue;
                const k = (e.provider || '') + '\u0000' + (e.model || '');
                tally[k] = (tally[k] || 0) + 1;
            }
        }
        let best = null, bestN = 0;
        for (const k in tally) if (tally[k] > bestN) { bestN = tally[k]; best = k; }
        if (best) {
            const parts = best.split('\u0000');
            LLM_SIMPLE_SEL[cat.key] = { provider: parts[0], model: parts[1] };
        }
    }
    // Embedding: interne Config gewinnt ueber Routing-Detection
    const emb = CONFIG.embedding || {};
    if (emb.backend === 'internal') {
        LLM_SIMPLE_SEL.embedding = { provider: LLM_SIMPLE_INTERNAL, model: emb.internal_model || '' };
    }
}

function llmSimpleSetProvider(cat, val) {
    LLM_SIMPLE_SEL[cat] = { provider: val, model: '' };
    const m = document.getElementById('llmsimple-model-' + cat);
    if (m) m.innerHTML = '<option value="" selected>— select —</option>';
    llmSimplePopulateModels(cat, true);
    llmSimpleRebuild();
}

function llmSimpleSetModel(cat, val) {
    if (!LLM_SIMPLE_SEL[cat]) LLM_SIMPLE_SEL[cat] = {};
    LLM_SIMPLE_SEL[cat].model = val;
    llmSimpleRebuild();
}

function llmSimplePopulateModels(cat, autoload) {
    const sel = LLM_SIMPLE_SEL[cat] || {};
    const el = document.getElementById('llmsimple-model-' + cat);
    if (!el) return;
    const cur = sel.model || '';
    // Interne Embedding-Modelle: Choices aus dem Schema
    if (sel.provider === LLM_SIMPLE_INTERNAL) {
        const f = ((SCHEMA.embedding || {}).fields || {}).internal_model || {};
        const choices = f.choices || [];
        let opts = '<option value="">— select —</option>';
        for (const c of choices) opts += '<option value="' + esc(c) + '"' + (c === cur ? ' selected' : '') + '>' + esc(c) + '</option>';
        el.innerHTML = opts;
        if (!cur && choices.length) {
            LLM_SIMPLE_SEL[cat].model = choices[0];
            el.value = choices[0];
            llmSimpleRebuild();
        }
        return;
    }
    if (!sel.provider) { el.innerHTML = '<option value="">— select provider —</option>'; return; }
    const models = PROVIDERS_CACHE[sel.provider];
    if (models && models.length) {
        const vis = PROVIDERS_VISION[sel.provider] || new Set();
        let opts = '<option value="">— select —</option>';
        for (const m of models) opts += '<option value="' + esc(m) + '"' + (m === cur ? ' selected' : '') + '>' + esc(m) + (vis.has(m) ? ' (vision)' : '') + '</option>';
        el.innerHTML = opts;
        if (cur && !models.includes(cur)) {
            el.innerHTML = '<option value="' + esc(cur) + '" selected>' + esc(cur) + ' (not on server)</option>' + opts;
        }
    } else if (autoload) {
        llmSimpleLoadModels(cat);
    }
}

async function llmSimpleLoadModels(cat) {
    const sel = LLM_SIMPLE_SEL[cat] || {};
    if (sel.provider === LLM_SIMPLE_INTERNAL) { llmSimplePopulateModels(cat, false); return; }
    if (!sel.provider) { toast('Select a provider first', 'error'); return; }
    const el = document.getElementById('llmsimple-model-' + cat);
    if (el) el.innerHTML = '<option>Loading…</option>';
    if (!PROVIDERS_CACHE[sel.provider] || !PROVIDERS_CACHE[sel.provider].length) {
        try {
            const resp = await fetch('/admin/settings/providers/' + encodeURIComponent(sel.provider) + '/models', { credentials: 'same-origin' });
            const data = await resp.json();
            if (data.error) toast('Error: ' + data.error, 'error');
            const list = data.models || [];
            if (list.length) {
                PROVIDERS_CACHE[sel.provider] = list;
                PROVIDERS_VISION[sel.provider] = new Set(data.vision || []);
            }
        } catch (e) { toast('Failed to load models: ' + e.message, 'error'); }
    }
    llmSimplePopulateModels(cat, false);
}

// Writes CONFIG.llm_routing (order=1) + CONFIG.embedding from LLM_SIMPLE_SEL.
function llmSimpleRebuild() {
    const tasks = (LLM_CATALOG_CACHE || EMPTY_LLM_CATALOG).tasks || [];
    const byCat = {};
    for (const t of tasks) (byCat[t.category] = byCat[t.category] || []).push(t.id);
    // Take a copy, then drop every order==1 assignment (fallbacks stay)
    let routing = (CONFIG.llm_routing || []).map(e => Object.assign({}, e, { tasks: (e.tasks || []).slice() }));
    for (const e of routing) e.tasks = (e.tasks || []).filter(t => (t.order || 1) !== 1);
    for (const cat of LLM_SIMPLE_CATS) {
        const sel = LLM_SIMPLE_SEL[cat.key] || {};
        if (cat.key === 'embedding' && sel.provider === LLM_SIMPLE_INTERNAL) continue;
        if (!sel.provider || !sel.model) continue;
        const ids = byCat[cat.key] || [];
        if (!ids.length) continue;
        let entry = routing.find(e => e.provider === sel.provider && e.model === sel.model);
        if (!entry) {
            entry = { provider: sel.provider, model: sel.model, enabled: true, temperature: LLM_SIMPLE_TEMP[cat.key], tasks: [] };
            routing.push(entry);
        }
        if (!entry.tasks) entry.tasks = [];
        for (const id of ids) entry.tasks.push({ task: id, order: 1 });
    }
    // Remove entries that ran empty (unless they only exist for preloading)
    routing = routing.filter(e => (e.tasks && e.tasks.length) || e.preload_on_startup);
    CONFIG.llm_routing = routing;
    // Embedding config
    if (!CONFIG.embedding) CONFIG.embedding = {};
    const e = LLM_SIMPLE_SEL.embedding || {};
    if (e.provider === LLM_SIMPLE_INTERNAL) {
        CONFIG.embedding.backend = 'internal';
        if (e.model) CONFIG.embedding.internal_model = e.model;
    } else if (e.provider && e.model) {
        CONFIG.embedding.backend = 'external';
    } else {
        CONFIG.embedding.backend = 'auto';
    }
}

// ── LLM routing: requirement badges & model mismatch ────────────────────
// All user-visible strings of this block are collected in ROUTING_TEXT /
// MISMATCH_TEXT so a later i18n layer can pick them up in one pass — this page
// has no t() yet, so they are plain English literals for now.
const ROUTING_TEXT = {
    profileTitle:     'Requirement profile of this task',
    requiredSuffix:   ' required',
    capsUnknown:      'capabilities unknown',
    capsUnknownTitle: 'No capability entry for this model — maintain it under /admin/models. No check possible, no warning.',
    perTaskView:      'Per-task view',
    orderApplied:     'Order set for all tasks',
    catalogFailed:    'Could not load the LLM task list — task dropdowns and the '
                    + 'per-task view stay empty. After a code update the server '
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

// Compact variant for the narrow editable task rows: ONLY a real warning, and
// only as an icon whose tooltip carries the full text. No chip text and no
// "capabilities unknown" hint — that row is a flex-row of select + number +
// delete button and has no space for either.
function renderMatchIcon(req, capsKey) {
    const caps = MODEL_CAPS_CACHE[capsKey];
    if (caps === undefined) return '';
    const res = evaluateRoutingMatch(req, caps);
    let html = '';
    for (const key of res.missing) {
        const txt = MISMATCH_TEXT[key];
        if (!txt) continue;
        html += '<span class="req-warn-icon" title="' + esc(txt.label + ' — ' + txt.title)
             + '">⚠</span>';
    }
    return html;
}

// Fills the mismatch slots of the editable task rows of one llm_routing entry
// with the compact warning icon. Runs as a post-pass because
// renderTaskOrderRow() is synchronous.
async function updateTaskRowMatchBadges(path) {
    const slots = document.querySelectorAll('[data-taskmatch^="' + path + '|"]');
    if (!slots.length) return;
    const catalog = await loadLlmCatalog();
    const reqById = {};
    for (const t of (catalog.tasks || [])) reqById[t.id] = t.requirements || null;
    const entry = getVal(path.replace(/\.tasks$/, '')) || {};
    const items = getVal(path) || [];
    const key = capsKeyFor(entry.provider, entry.model);
    if (entry.model) await ensureModelCaps([key]);
    slots.forEach(el => {
        const idx = parseInt((el.getAttribute('data-taskmatch') || '').split('|')[1], 10);
        const item = items[idx] || {};
        el.innerHTML = entry.model ? renderMatchIcon(reqById[item.task], key) : '';
    });
}

// Task select of an editable routing row changed.
function onTaskRowTaskChanged(path, index, value) {
    setVal(path + '[' + index + '].task', value);
    updateTaskRowMatchBadges(path);
    applyEmbedVisibility();
    if (ACTIVE_SECTION === 'llm_routing') renderLlmTaskView(CONFIG.llm_routing || []);
}

// Model/provider of an llm_routing entry changed -> re-check its task rows and
// the per-task overview. Every other model field on the page is ignored.
function onRoutingModelChanged(path) {
    const m = /^(llm_routing\[\d+\])\.(model|provider)$/.exec(path || '');
    if (!m) return;
    updateTaskRowMatchBadges(m[1] + '.tasks');
    if (ACTIVE_SECTION === 'llm_routing') renderLlmTaskView(CONFIG.llm_routing || []);
}

async function renderLlmTaskView(entries) {
    const catalog = await loadLlmCatalog();
    const tasks = catalog.tasks || [];
    const view = document.getElementById('llm-task-view');
    if (!view) return;

    // Load state from the server (runtime + persistent + presets)
    let state = { disabled: [], runtime_disabled: [], presets: {} };
    try {
        const r = await fetch('/admin/settings/llm-task-state', { credentials: 'same-origin' });
        if (r.ok) state = await r.json();
    } catch (e) {}

    // Persistently disabled from CONFIG (the UI source for the toggles)
    const persistentDisabled = new Set(
        ((CONFIG.llm_task_state || {}).disabled_tasks || [])
    );
    const runtimeDisabled = new Set(state.runtime_disabled || []);

    // task_id -> [{order, provider, model, llmDisabled}]
    const byTask = {};
    for (const entry of (entries || [])) {
        if (!entry || typeof entry !== 'object') continue;
        const prov = entry.provider || '';
        const mod = entry.model || '';
        const llmDisabled = entry.enabled === false;
        for (const t of (entry.tasks || [])) {
            if (!t || !t.task) continue;
            (byTask[t.task] = byTask[t.task] || []).push({
                order: t.order || 999,
                provider: prov,
                model: mod,
                llmDisabled: llmDisabled,
            });
        }
    }
    for (const k in byTask) byTask[k].sort((a, b) => a.order - b.order);

    // Capabilities of every assigned model — one batched lookup before the
    // markup is built, so the mismatch chips are there on the first paint.
    const capsKeys = [];
    for (const k in byTask) {
        for (const r of byTask[k]) if (r.model) capsKeys.push(capsKeyFor(r.provider, r.model));
    }
    await ensureModelCaps(capsKeys);

    let html = '';
    // Preset selector (runtime, not persistent — only for this server session)
    html += '<div style="margin-bottom:10px; padding:8px 10px; background:#161b22; border:1px solid #30363d; border-radius:6px;">';
    html += '<div style="font-size:12px; color:#8b949e; margin-bottom:6px;">Runtime preset (not persistent):</div>';
    html += '<select id="llm-task-preset" onchange="applyTaskPreset(this.value)" style="background:#0d1117; color:#c9d1d9; border:1px solid #30363d; padding:6px; border-radius:4px; width:100%;">';
    html += '<option value="none">— none (all tasks active) —</option>';
    for (const p of Object.keys(state.presets || {})) {
        html += '<option value="' + esc(p) + '">' + esc(p) + ' — ' + (state.presets[p] || []).length + ' tasks off</option>';
    }
    html += '</select>';
    if (runtimeDisabled.size) {
        html += '<div style="font-size:11px; color:#d29922; margin-top:4px;">Active: ' + runtimeDisabled.size + ' tasks runtime-disabled</div>';
    }
    html += '</div>';

    // Sorted by category (chat → tool → helper → image), then by label. Bigger
    // models (chat) end up on top, small helpers at the bottom — which matches
    // the reading expectation "who needs what".
    const _CAT_ORDER = { chat: 0, tool: 1, helper: 2, image: 3, embedding: 4 };
    // Per-category colors for border + badge:
    //   chat:   blue   — large models
    //   tool:   violet — structured output
    //   helper: green  — small/cheap models
    //   image:  orange — vision / image IO
    const _CAT_COLORS = {
        chat:   { bg: '#1f3a5f', fg: '#79c0ff', border: '#30547a' },
        tool:   { bg: '#3a2f5f', fg: '#d2a8ff', border: '#54497a' },
        helper: { bg: '#1c3a2c', fg: '#7ee787', border: '#2d553f' },
        image:  { bg: '#5a3a1f', fg: '#ffaa66', border: '#7a543d' },
        embedding: { bg: '#3a1f4f', fg: '#c879ff', border: '#54387a' },
        '':     { bg: '#21262d', fg: '#8b949e', border: '#30363d' },
    };
    const sortedTasks = [...tasks].sort((a, b) => {
        const ao = _CAT_ORDER[a.category] ?? 99;
        const bo = _CAT_ORDER[b.category] ?? 99;
        if (ao !== bo) return ao - bo;
        return (a.label || '').localeCompare(b.label || '');
    });

    let _lastCat = null;
    for (const t of sortedTasks) {
        // Category header whenever the category changes
        if (t.category !== _lastCat) {
            _lastCat = t.category;
            const cc = _CAT_COLORS[t.category] || _CAT_COLORS[''];
            html += '<div style="margin:14px 0 6px 0; padding:4px 10px; '
                 + 'background:' + cc.bg + '; color:' + cc.fg + '; '
                 + 'border-left:3px solid ' + cc.fg + '; border-radius:3px; '
                 + 'font-size:11px; font-weight:600; letter-spacing:0.3px; '
                 + 'text-transform:uppercase;">'
                 + esc(t.category_label || 'Other') + '</div>';
        }

        const rows = byTask[t.id] || [];
        const isEmpty = rows.length === 0;
        const isPersistDisabled = persistentDisabled.has(t.id);
        const isRuntimeDisabled = runtimeDisabled.has(t.id);
        const disabledStyle = (isPersistDisabled || isRuntimeDisabled) ? 'opacity:0.5;' : '';
        const cc = _CAT_COLORS[t.category] || _CAT_COLORS[''];
        html += '<div style="margin-bottom:6px; padding:8px 10px; background:#0d1117; '
             + 'border:1px solid #30363d; border-left:3px solid ' + cc.fg + '; '
             + 'border-radius:6px; ' + disabledStyle + '">';
        html += '<div style="display:flex; justify-content:space-between; align-items:center;">';
        let catBadge = '';
        if (t.category_label) {
            catBadge = ' <span style="font-size:10px; color:' + cc.fg
                 + '; font-weight:400; background:' + cc.bg
                 + '; padding:1px 6px; border-radius:8px; margin-left:4px;">'
                 + esc(t.category_label) + '</span>';
        }
        html += '<div style="font-size:12px; color:#58a6ff; font-weight:600;">' + esc(t.label) + catBadge + ' <span style="color:#6e7681; font-weight:400;">— ' + esc(t.id) + '</span></div>';
        html += '<label style="display:inline-flex; align-items:center; gap:4px; font-size:11px; color:#8b949e; cursor:pointer;">';
        html += '<input type="checkbox" ' + (isPersistDisabled ? '' : 'checked') + ' onchange="toggleTaskPersistent(\'' + t.id + '\', !this.checked)"> active';
        html += '</label>';
        html += '</div>';
        // Requirement profile of the task (nothing for a task without one).
        html += renderRequirementBadges(t.requirements, catalog);
        if (isRuntimeDisabled) {
            html += '<div style="font-size:11px; color:#d29922;">runtime-disabled (preset)</div>';
        }
        if (isEmpty) {
            // pose_embedding runs over CONFIG.embedding (built-in fastembed/ONNX or an
            // external /v1/embeddings provider), NOT over llm_routing. With the
            // internal/auto backend "no LLM assigned" would be misleading -> show the
            // real status instead.
            const _emb = CONFIG.embedding || {};
            const _embBackend = (_emb.backend || 'auto');
            if (t.id === 'pose_embedding' && _embBackend !== 'external') {
                const _m = _emb.internal_model || 'bge-small-en';
                const _lbl = _embBackend === 'auto' ? 'built-in (auto)' : 'built-in';
                html += '<div class="desc" style="color:#3fb950;">' + _lbl + ' embedding — ' + esc(_m) + ' (CPU, no LLM needed)</div>';
            } else {
                html += '<div class="desc" style="color:#d29922;">no LLM assigned</div>';
            }
        } else {
            html += '<div style="margin-top:4px;">';
            for (const r of rows) {
                const rowStyle = r.llmDisabled
                    ? 'font-size:12px; color:#6e7681; display:flex; gap:8px; text-decoration:line-through;'
                    : 'font-size:12px; color:#c9d1d9; display:flex; gap:8px;';
                html += '<div style="' + rowStyle + '">';
                html += '<span style="color:#6e7681; min-width:22px;">' + r.order + '.</span>';
                html += '<span>' + esc(r.provider) + ' / ' + esc(r.model) + '</span>';
                if (r.llmDisabled) {
                    html += '<span style="color:#d29922; text-decoration:none;">(LLM disabled)</span>';
                }
                // Mismatch per provider/model entry of this task row.
                if (r.model) html += renderMatchBadges(t.requirements, capsKeyFor(r.provider, r.model));
                html += '</div>';
            }
            html += '</div>';
        }
        html += '</div>';
    }
    view.innerHTML = html;
}

function toggleTaskPersistent(taskId, disable) {
    if (!CONFIG.llm_task_state) CONFIG.llm_task_state = { disabled_tasks: [] };
    const arr = CONFIG.llm_task_state.disabled_tasks || [];
    const idx = arr.indexOf(taskId);
    if (disable && idx < 0) arr.push(taskId);
    if (!disable && idx >= 0) arr.splice(idx, 1);
    CONFIG.llm_task_state.disabled_tasks = arr;
    toast('Change only takes effect after save', 'success');
    renderLlmTaskView(CONFIG.llm_routing || []);
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
        renderLlmTaskView(CONFIG.llm_routing || []);
    } catch (e) {
        toast('Preset error: ' + e.message, 'error');
    }
}

// ── Render Fields ──
function renderFields(fields, data, path) {
    let html = '';
    for (const [fKey, f] of Object.entries(fields)) {
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
            html += '<div class="subsection-title" style="margin-top:18px;">' + f.label + '</div>';
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
            // Action-Button — kein Daten-Binding, ruft Endpoint mit
            // body aus angegebenen Geschwister-Feldern auf.
            const btnId = 'btn-' + (path + '.' + fKey).replace(/\W+/g, '-');
            const bodyFrom = JSON.stringify(f.body_from || []);
            const confirmMsg = f.confirm ? esc(f.confirm) : '';
            const previewUrl = f.preview_url ? esc(f.preview_url) : '';
            html += '<div class="field">';
            html += '<label></label>';
            html += '<div class="input-wrap">';
            html += '<button type="button" id="' + btnId + '" class="btn btn-primary" '
                + 'onclick="runActionButton(\'' + esc(f.endpoint) + '\', \'' + (f.method || 'POST') + '\', '
                + '\'' + path + '\', ' + bodyFrom.replace(/"/g, '&quot;') + ', \'' + confirmMsg + '\', this, \'' + previewUrl + '\')">'
                + esc(f.label) + '</button>';
            if (f.description) html += '<div class="desc">' + f.description + '</div>';
            html += '</div></div>';
            continue;
        }
        if (f.type === 'image_preview') {
            // Live-Preview eines Bild-Endpoints (z.B. generiertes Frame)
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
            html += '<div style="display:none; color:#888; font-size:12px; padding:20px;">noch nicht generiert</div>';
            html += '</div>';
            if (metaUrl) {
                // Meta-URL als data-attribute hinterlegen — populateImagePreviewMetas()
                // wird nach renderSection aufgerufen und befuellt alle solche Elemente.
                html += '<div id="' + imgId + '-meta" class="desc image-preview-meta" '
                    + 'data-meta-url="' + metaUrl + '" '
                    + 'style="margin-top:6px; font-family:monospace; font-size:11px;"></div>';
            }
            if (f.description) html += '<div class="desc">' + f.description + '</div>';
            html += '</div></div>';
            continue;
        }
        if (f.type === 'task_order_list') {
            html += renderTaskOrderList(data[fKey] || [], path + '.' + fKey, f);
            continue;
        }
        const val = data[fKey] !== undefined ? data[fKey] : (f.default !== undefined ? f.default : '');
        const fullPath = path + '.' + fKey;
        const pill = f.requires_restart
            ? ' <span class="restart-pill" title="Changing this value requires a server restart">restart</span>'
            : '';
        // Fields irrelevant for embedding entries (tasks of the "embedding"
        // group), e.g. temperature/max_tokens — toggled by a post-pass.
        const embedAttr = f.hide_for_embedding ? ' data-embedhide-entry="' + path + '"' : '';
        // `half: true` fields occupy one grid column instead of both, so two
        // adjacent half fields (e.g. Width | Height) share one row.
        html += '<div class="field' + (f.half ? ' field-half' : '') + '"' + embedAttr + '>';
        html += '<label for="f-' + fullPath + '">' + f.label + pill + '</label>';
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
            return '<input type="checkbox" id="' + id + '" ' + (val ? 'checked' : '') + ' onchange="setVal(\'' + path + '\', this.checked)">';
        case 'int':
            return '<input type="number" id="' + id + '" value="' + esc(val) + '" '
                + (f.min !== undefined ? 'min="' + f.min + '" ' : '')
                + (f.max !== undefined ? 'max="' + f.max + '" ' : '')
                + _phAttr(f)
                + 'step="1" onchange="setVal(\'' + path + '\', parseInt(this.value) || 0)">';
        case 'float':
            return '<input type="number" id="' + id + '" value="' + esc(val) + '" '
                + (f.min !== undefined ? 'min="' + f.min + '" ' : '')
                + (f.max !== undefined ? 'max="' + f.max + '" ' : '')
                + _phAttr(f)
                + 'step="' + (f.step || 0.1) + '" onchange="setVal(\'' + path + '\', parseFloat(this.value) || 0)">';
        case 'select':
            let opts = (f.choices || []).map(c => '<option value="' + esc(c) + '"' + (c == val ? ' selected' : '') + '>' + esc(c) + '</option>').join('');
            const onChg = f.triggers_rerender
                ? "setVal('" + path + "', this.value); renderSection(ACTIVE_SECTION)"
                : "setVal('" + path + "', this.value)";
            return '<select id="' + id + '" onchange="' + onChg + '">' + opts + '</select>';
        case 'password':
            return '<div class="pw-wrap"><input type="password" id="' + id + '" value="' + esc(val) + '" onchange="setVal(\'' + path + '\', this.value)">'
                + '<button class="pw-toggle" type="button" onclick="togglePw(this)">👁</button></div>';
        case 'text':
            return '<textarea id="' + id + '" ' + _phAttr(f)
                + 'onchange="setVal(\'' + path + '\', this.value)">' + esc(val) + '</textarea>';
        case 'provider_select':
            return renderProviderSelect(val, path);
        case 'model_select':
            return renderModelSelect(val, path);
        case 'imagegen_select':
            return renderImagegenSelect(val, path);
        case 'imagegen_backend_select':
            return renderImagegenBackendSelect(val, path);
        case 'imagegen_model_select':
            return renderImagegenModelSelect(val, path);
        case 'imagegen_model':
            return renderImagegenModelCombo(val, path);
        case 'imagegen_target_select':
            return renderImagegenTargetSelect(val, path);
        default: // str / number
            return '<input type="text" id="' + id + '" value="' + esc(val) + '" '
                + _phAttr(f)
                + 'onchange="setVal(\'' + path + '\', this.value)">';
    }
}

function renderProviderSelect(val, path) {
    const providers = CONFIG.providers || [];
    let opts = '<option value="">— Auto —</option>';
    for (const p of providers) {
        opts += '<option value="' + esc(p.name) + '"' + (p.name === val ? ' selected' : '') + '>' + esc(p.name) + ' (' + p.type + ')</option>';
    }
    return '<select id="f-' + path + '" onchange="setVal(\'' + path + '\', this.value); refreshModelSelect(\'' + path + '\'); onRoutingModelChanged(\'' + path + '\')">' + opts + '</select>';
}

function renderModelSelect(val, path) {
    // The provider is read from the sibling field at click time (not baked in at
    // render time) — otherwise the button would still point at the old provider
    // after a provider switch and fetch the wrong model list.
    let select = '<select id="f-' + path + '" onchange="setVal(\'' + path + '\', this.value); onRoutingModelChanged(\'' + path + '\')">';
    select += '<option value="' + esc(val) + '" selected>' + esc(val || '— select —') + '</option>';
    select += '</select>';
    select += ' <button class="btn btn-sm" onclick="loadModels(\'' + path + '\')">Load Models</button>';
    return select;
}

function renderImagegenSelect(val, path) {
    // Default MATCH: combobox with backend-name glob suggestions + free text
    // (values are bare backend globs). Resolved via resolve_imagegen_target ->
    // match_backend (by availability). A legacy "backend:" prefix is tolerated.
    const backends = CONFIG.image_generation?.backends || [];
    const sugg = new Set();
    for (const be of backends) {
        if (be.enabled === false) continue;  // do not suggest disabled backends
        sugg.add(be.name);
    }
    let opts = '';
    for (const s of sugg) opts += '<option value="' + esc(s) + '">';
    return '<input type="text" id="f-' + path + '" list="dl-' + path + '" value="' + esc(val || '') + '" placeholder="e.g. LocalAI-Flux" onchange="setVal(\'' + path + '\', this.value)"><datalist id="dl-' + path + '">' + opts + '</datalist>';
}

function renderImagegenBackendSelect(val, path) {
    // ALL image backends (Together, CivitAI, LocalAI, ...)
    const backends = CONFIG.image_generation?.backends || [];
    let opts = '<option value="">— None —</option>';
    for (const be of backends) {
        const lbl = be.name + (be.api_type ? ' (' + be.api_type + ')' : '');
        opts += '<option value="' + esc(be.name) + '"' + (be.name === val ? ' selected' : '') + '>' + esc(lbl) + '</option>';
    }
    // onchange: setVal + Geschwister-Modell-Select neu fuellen falls vorhanden
    return '<select id="f-' + path + '" onchange="setVal(\'' + path + '\', this.value); refreshImagegenModelSelect(\'' + path + '\')">' + opts + '</select>';
}

// Geschwister-Modell-Select neu laden wenn Backend gewechselt wird
function refreshImagegenModelSelect(backendPath) {
    const parts = backendPath.split('.');
    parts[parts.length - 1] = 'model';
    const modelPath = parts.join('.');
    const modelEl = document.getElementById('f-' + modelPath);
    if (!modelEl) return;
    const backendName = getVal(backendPath) || '';
    if (!backendName) {
        modelEl.innerHTML = '<option value="">— Backend zuerst waehlen —</option>';
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

// Backend selection for imagegen_target_select fields.
// Value format: the bare backend name (as served by /settings/imagegen-targets)
let IMAGEGEN_TARGETS_CACHE = null;

async function loadImagegenTargets() {
    if (IMAGEGEN_TARGETS_CACHE) return IMAGEGEN_TARGETS_CACHE;
    try {
        const r = await fetch('/admin/settings/imagegen-targets', { credentials: 'same-origin' });
        const d = await r.json();
        IMAGEGEN_TARGETS_CACHE = d.targets || [];
    } catch {
        IMAGEGEN_TARGETS_CACHE = [];
    }
    return IMAGEGEN_TARGETS_CACHE;
}

function renderImagegenTargetSelect(val, path) {
    // Initial mit aktuellem Wert rendern; Liste wird async nachgeladen
    let html = '<select id="f-' + path + '" onchange="setVal(\'' + path + '\', this.value)">';
    if (val) html += '<option value="' + esc(val) + '" selected>' + esc(val) + '</option>';
    html += '<option value="">— Auto (Cloud bevorzugt) —</option>';
    html += '</select>';
    // Async populate
    setTimeout(async () => {
        const targets = await loadImagegenTargets();
        const sel = document.getElementById('f-' + path);
        if (!sel) return;
        let opts = '<option value="">— Auto (Cloud bevorzugt) —</option>';
        for (const t of targets) {
            const dis = t.available ? '' : ' disabled';
            const tag = t.available ? '' : ' (offline)';
            const sl = t.value === val ? ' selected' : '';
            opts += '<option value="' + esc(t.value) + '"' + sl + dis + '>' + esc(t.label + tag) + '</option>';
        }
        sel.innerHTML = opts;
    }, 0);
    return html;
}

function renderImagegenModelSelect(val, path) {
    // Backend aus Geschwister-Feld lesen
    const parts = path.split('.');
    parts[parts.length - 1] = 'backend';
    const backendPath = parts.join('.');
    const backendName = getVal(backendPath) || '';
    let html = '<select id="f-' + path + '" onchange="setVal(\'' + path + '\', this.value)">';
    if (val) {
        html += '<option value="' + esc(val) + '" selected>' + esc(val) + '</option>';
    } else {
        html += '<option value="">— Backend-Default —</option>';
    }
    html += '</select>';
    html += ' <button class="btn btn-sm" onclick="loadImagegenBackendModels(\'' + path + '\', \'' + esc(backendName) + '\')">Load Models</button>';
    return html;
}

// Editierbares Modell-Combo fuer Image-Backends: Freitext (CivitAI-URN, manuelles
// Tippen) + Datalist-Vorschlaege ueber "Load Models" (holt /v1/models vom Backend).
function renderImagegenModelCombo(val, path) {
    // base = das Backend-Item (z.B. image_generation.backends.2); name/api_* werden
    // zur Klick-Zeit aus den Geschwister-Feldern gelesen, damit "URL eintragen ->
    // Load Models" auch OHNE vorheriges Speichern funktioniert.
    const parts = path.split('.');
    const base = parts.slice(0, -1).join('.');
    const dlId = 'dl-' + path.replace(/[^a-zA-Z0-9]/g, '-');
    let html = '<input type="text" list="' + dlId + '" id="f-' + path + '" value="' + esc(val) + '" placeholder="z.B. flux.2-klein-4b" onchange="setVal(\'' + path + '\', this.value)">';
    html += '<datalist id="' + dlId + '"></datalist>';
    html += ' <button class="btn btn-sm" type="button" onclick="loadImagegenModelCombo(\'' + path + '\', \'' + base + '\')">Load Models</button>';
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
    if (!apiUrl) { toast('Bitte zuerst die API URL eintragen', 'error'); return; }
    try {
        const qs = new URLSearchParams({ api_type: apiType, api_url: apiUrl, api_key: apiKey }).toString();
        const resp = await fetch('/admin/settings/imagegen-backends/' + encodeURIComponent(name || '_new') + '/models?' + qs, { credentials: 'same-origin' });
        const data = await resp.json();
        if (data.error) { toast('Load Models: ' + data.error, 'error'); return; }
        const list = data.models || [];
        dl.innerHTML = list.map(m => '<option value="' + esc(m) + '"></option>').join('');
        toast(list.length ? (list.length + ' Modelle geladen') : 'Keine Modelle gefunden', list.length ? 'success' : 'error');
    } catch (e) {
        toast('Load Models fehlgeschlagen: ' + e.message, 'error');
    }
}

// ── Array/Dict Items ──
// _itemLabel: gleiche Logik wie in renderArrayItem — fuer Sortierung.
// labelField darf ein String ODER ein Array sein. Bei Array gewinnt der erste
// nicht-leere Wert (z.B. ["name", "model"] -> name wenn gesetzt, sonst model).
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
    let html = '<div id="arr-' + path + '">';
    // Index erhalten (Pfade referenzieren echten Array-Index), Reihenfolge
    // alphabetisch wenn def.sort_alphabetically gesetzt ist.
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
    let html = '<div id="arr-' + path + '">';
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

function renderArrayItem(def, item, path, index, labelField) {
    const label = _itemLabel(item, labelField, 'Item ' + index);
    const openClass = OPEN_ITEMS.has(path) ? ' open' : '';
    let html = '<div class="array-item' + openClass + '" id="item-' + path + '">';
    html += '<div class="array-item-header" onclick="toggleArrayItem(this, \'' + path + '\')">';
    html += '<span class="chevron">▶</span> ';
    html += '<span class="title" style="margin-left:6px;">' + esc(label) + '</span>';
    if (item.enabled === false) html += '<span class="badge">deaktiviert</span>';
    if (item.type) html += '<span class="badge">' + esc(item.type || item.api_type || '') + '</span>';
    html += '<button class="btn btn-sm" style="margin-left:8px;" title="Als neuen Eintrag duplizieren" onclick="event.stopPropagation(); duplicateItem(\'' + path + '\')">⧉</button>';
    html += '<button class="btn btn-sm btn-danger" style="margin-left:4px;" onclick="event.stopPropagation(); removeItem(\'' + path + '\')">✕</button>';
    html += '</div>';
    html += '<div class="array-item-body">';
    html += renderFields(def.fields, item, path);
    html += '</div></div>';
    return html;
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
    // Aktuelle Auswahl validieren — sonst ersten Eintrag waehlen.
    let sel = SELECTED_ITEM[path];
    if (!order.some(o => o.itemPath === sel)) sel = order.length ? order[0].itemPath : null;
    SELECTED_ITEM[path] = sel;

    const cols = def.list_columns || [{ field: def.item_label_field || 'name', label: 'Name' }];

    let html = '<div class="md-grid">';
    // Links: Tabelle
    html += '<div class="md-list">';
    html += '<table class="md-table"><thead><tr>';
    for (const c of cols) html += '<th>' + esc(c.label) + '</th>';
    html += '</tr></thead><tbody>';
    for (const o of order) {
        const active = (o.itemPath === sel) ? ' active' : '';
        html += '<tr class="md-row' + active + '" onclick="selectMasterItem(\'' + path + '\', \'' + o.itemPath + '\')">';
        for (const c of cols) html += '<td>' + renderMdCell(c, o.item) + '</td>';
        html += '</tr>';
    }
    if (!order.length) {
        html += '<tr><td colspan="' + cols.length + '"><span class="md-empty">Keine Eintraege</span></td></tr>';
    }
    html += '</tbody></table>';
    html += '<button class="btn btn-sm" style="margin-top:10px;" onclick="addArrayItem(\'' + path + '\', \'' + (def.is_dict ? 'dict' : 'array') + '\')">+ Add</button>';
    html += '</div>';
    // Rechts: Detail
    html += '<div class="md-detail" id="detail-' + path + '">';
    html += renderMasterDetailBody(def, items, path, sel);
    html += '</div>';
    html += '</div>';
    return html;
}

function renderMasterDetailBody(def, items, path, sel) {
    if (!sel) return '<div class="md-empty-detail">Eintrag links auswaehlen oder neu anlegen.</div>';
    let item;
    if (def.is_dict) {
        item = (items || {})[sel.slice(path.length + 1)];
    } else {
        const m = sel.match(/\[(\d+)\]$/);
        item = m ? (items || [])[parseInt(m[1], 10)] : null;
    }
    if (!item) return '<div class="md-empty-detail">Eintrag links auswaehlen oder neu anlegen.</div>';

    const label = _itemLabel(item, def.item_label_field, 'Eintrag');
    let html = '<div class="md-detail-head">';
    html += '<span class="md-detail-title">' + esc(label) + '</span>';
    html += '<span style="flex:1;"></span>';
    html += '<button class="btn btn-sm" title="Als neuen Eintrag duplizieren" onclick="duplicateItem(\'' + sel + '\')">⧉</button>';
    html += '<button class="btn btn-sm btn-danger" style="margin-left:4px;" title="Loeschen" onclick="removeItem(\'' + sel + '\')">✕</button>';
    html += '</div>';
    html += renderFields(def.fields, item, sel);
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

function renderTaskOrderList(items, path, f) {
    // items: [{task: 'chat_stream', order: 1}, ...]
    let html = '<div class="field"><label>' + f.label + '</label><div class="input-wrap">';
    if (f.description) html += '<div class="desc" style="margin-bottom:6px;">' + f.description + '</div>';
    html += '<div id="tasks-' + path + '">';
    for (let i = 0; i < items.length; i++) {
        html += renderTaskOrderRow(items[i] || {}, path, i);
    }
    html += '</div>';
    html += '<div style="margin-top:6px; display:flex; flex-wrap:wrap; gap:4px;">';
    html += '<button class="btn btn-sm" onclick="addTaskOrderRow(\'' + path + '\')">+ Task</button>';
    html += '<button class="btn btn-sm" title="Add all Image-Input tasks not yet assigned" onclick="addTaskGroup(\'' + path + '\', \'image\')">+ All Image</button>';
    html += '<button class="btn btn-sm" title="Add all Tool tasks not yet assigned" onclick="addTaskGroup(\'' + path + '\', \'tool\')">+ All Tools</button>';
    html += '<button class="btn btn-sm" title="Add all Large Chat Model tasks not yet assigned" onclick="addTaskGroup(\'' + path + '\', \'chat\')">+ All Chat</button>';
    html += '<button class="btn btn-sm" title="Add all Small Helper tasks not yet assigned" onclick="addTaskGroup(\'' + path + '\', \'helper\')">+ All Helper</button>';
    html += '<button class="btn btn-sm" title="Add all Embedding tasks not yet assigned" onclick="addTaskGroup(\'' + path + '\', \'embedding\')">+ All Embedding</button>';
    html += '<button class="btn btn-sm" title="Add all Tool/Helper tasks that run WITHOUT thinking" onclick="addTaskGroupByThinking(\'' + path + '\', false)">+ All No-Thinking</button>';
    html += '<button class="btn btn-sm" title="Add all Tool/Helper tasks that should run WITH thinking (🧠)" onclick="addTaskGroupByThinking(\'' + path + '\', true)">+ All Thinking 🧠</button>';
    html += '</div>';
    // Bulk-Action: alle Task-Orders dieses LLMs auf einen Wert setzen
    html += '<div style="margin-top:6px; display:flex; align-items:center; gap:6px;">';
    html += '<span style="font-size:12px; color:#8b949e;">Set order for all tasks:</span>';
    html += '<input type="number" id="bulk-order-input-' + path + '" min="1" step="1" placeholder="1" style="max-width:70px;">';
    html += '<button class="btn btn-sm" onclick="setAllTaskOrders(\'' + path + '\')">Apply</button>';
    html += '</div>';
    html += '</div></div>';
    // Async: Dropdowns fuellen nachdem DOM da ist
    setTimeout(() => populateTaskSelects(path), 0);
    return html;
}

function renderTaskOrderRow(item, path, i) {
    const task = item.task || '';
    const order = (item.order !== undefined ? item.order : 1);
    let html = '<div class="flex-row" id="taskrow-' + path + '-' + i + '">';
    html += '<select data-taskrow="' + path + '-' + i + '" style="flex:3;" onchange="onTaskRowTaskChanged(\'' + path + '\', ' + i + ', this.value)">';
    html += '<option value="' + esc(task) + '" selected>' + esc(task || '— select —') + '</option>';
    html += '</select>';
    html += '<input type="number" value="' + order + '" min="1" step="1" style="max-width:70px;" title="Order" onchange="setVal(\'' + path + '[' + i + '].order\', parseInt(this.value) || 1)">';
    // Slot for the mismatch chip — filled by updateTaskRowMatchBadges().
    html += '<span class="task-match-slot" data-taskmatch="' + path + '|' + i + '"></span>';
    html += '<button class="btn btn-sm btn-danger" onclick="removeTaskOrderRow(\'' + path + '\', ' + i + ')">✕</button>';
    html += '</div>';
    return html;
}

async function populateTaskSelects(path) {
    const tasks = (await loadLlmCatalog()).tasks || [];
    // Group tasks by category for guidance — show grouped <optgroup>s in the dropdown.
    const order = ['image', 'tool', 'chat', 'helper', 'embedding', ''];
    const grouped = {};
    for (const t of tasks) {
        const cat = t.category || '';
        (grouped[cat] = grouped[cat] || []).push(t);
    }
    const selects = document.querySelectorAll('select[data-taskrow^="' + path + '-"]');
    selects.forEach(sel => {
        const current = sel.value;
        let opts = '<option value="">— select —</option>';
        for (const cat of order) {
            const list = grouped[cat];
            if (!list || !list.length) continue;
            const groupLabel = list[0].category_label || 'Other';
            opts += '<optgroup label="' + esc(groupLabel) + '">';
            for (const t of list) {
                opts += '<option value="' + esc(t.id) + '"' + (t.id === current ? ' selected' : '') + '>'
                     + esc(t.label) + (t.thinking ? ' 🧠' : '') + ' — ' + esc(t.id) + '</option>';
            }
            opts += '</optgroup>';
        }
        sel.innerHTML = opts;
    });
    applyEmbedVisibility();
    updateTaskRowMatchBadges(path);
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

function addTaskOrderRow(path) {
    const obj = _ensureContainer(path, 'array');
    // order=1 is the default primary slot. Increase only when this LLM is meant
    // as a fallback for a task another LLM already serves at order=1.
    obj.push({ task: '', order: 1 });
    rerenderTaskOrderList(path);
}

async function addTaskGroup(path, category) {
    const tasks = (await loadLlmCatalog()).tasks || [];
    const obj = _ensureContainer(path, 'array');
    const existing = new Set((obj || []).map(it => it && it.task).filter(Boolean));
    let added = 0;
    for (const t of tasks) {
        if (t.category !== category) continue;
        if (existing.has(t.id)) continue;
        obj.push({ task: t.id, order: 1 });
        added++;
    }
    rerenderTaskOrderList(path);
    if (added) toast('Added ' + added + ' task' + (added === 1 ? '' : 's'), 'success');
    else toast('All tasks of this group are already assigned', 'success');
}

// Bulk-add tool/helper tasks by their thinking-group (gateway thinking vs
// no-thinking alias). wantThinking=true → only tasks flagged thinking; false →
// the rest of tool/helper. Chat/image/embedding tasks are never included here.
async function addTaskGroupByThinking(path, wantThinking) {
    const tasks = (await loadLlmCatalog()).tasks || [];
    const obj = _ensureContainer(path, 'array');
    const existing = new Set((obj || []).map(it => it && it.task).filter(Boolean));
    let added = 0;
    for (const t of tasks) {
        if (t.category !== 'tool' && t.category !== 'helper') continue;
        if (!!t.thinking !== !!wantThinking) continue;
        if (existing.has(t.id)) continue;
        obj.push({ task: t.id, order: 1 });
        added++;
    }
    rerenderTaskOrderList(path);
    if (added) toast('Added ' + added + ' task' + (added === 1 ? '' : 's'), 'success');
    else toast('All tasks of this group are already assigned', 'success');
}

function removeTaskOrderRow(path, index) {
    const parts = parsePath(path);
    let obj = CONFIG;
    for (const p of parts) obj = obj[p];
    obj.splice(index, 1);
    rerenderTaskOrderList(path);
}

function setAllTaskOrders(path) {
    const inputEl = document.getElementById('bulk-order-input-' + path);
    if (!inputEl) return;
    const order = parseInt(inputEl.value, 10);
    if (!order || order < 1) {
        toast('Please enter an order value >= 1', 'error');
        return;
    }
    const parts = parsePath(path);
    let obj = CONFIG;
    for (const p of parts) obj = obj && obj[p];
    if (!Array.isArray(obj) || !obj.length) {
        toast('No tasks assigned', 'error');
        return;
    }
    for (const it of obj) {
        if (it && typeof it === 'object') it.order = order;
    }
    rerenderTaskOrderList(path);
    toast(ROUTING_TEXT.orderApplied + ': order=' + order + ' (' + obj.length + ')', 'success');
}

function rerenderTaskOrderList(path) {
    // Re-render only the tasks container instead of the whole section, so the
    // surrounding array item stays open.
    const parts = parsePath(path);
    let obj = CONFIG;
    for (const p of parts) obj = obj && obj[p];
    const items = Array.isArray(obj) ? obj : [];
    const wrap = document.getElementById('tasks-' + path);
    if (!wrap) { renderSection(ACTIVE_SECTION); return; }
    let html = '';
    for (let i = 0; i < items.length; i++) {
        html += renderTaskOrderRow(items[i] || {}, path, i);
    }
    wrap.innerHTML = html;
    populateTaskSelects(path);
    // Also refresh the per-task view on the right while we are in the llm_routing tab
    if (ACTIVE_SECTION === 'llm_routing') {
        renderLlmTaskView(CONFIG.llm_routing || []);
    }
}

// ── Data Access ──
function setVal(path, value) {
    const parts = parsePath(path);
    let obj = CONFIG;
    for (let i = 0; i < parts.length - 1; i++) {
        const p = parts[i];
        if (obj[p] === undefined) {
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

function setLoraVal(path, index, field, value) {
    const parts = parsePath(path);
    let obj = CONFIG;
    for (const p of parts) {
        if (obj[p] === undefined) obj[p] = [];
        obj = obj[p];
    }
    while (obj.length <= index) obj.push({ file: '', strength: 1 });
    obj[index][field] = value;
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

// ── Actions ──
function addArrayItem(path, type) {
    const obj = _ensureContainer(path, type);
    if (type === 'dict') {
        const id = prompt('New entry key:');
        if (!id) return;
        // Keep the key dot-free: the editor addresses fields via dot notation
        // and split('.') breaks on a dot INSIDE the key. The display name
        // keeps the original input.
        const key = id.replace(/[.\[\]]/g, ' ').replace(/\s+/g, ' ').trim();
        if (!key) { toast('Invalid key', 'error'); return; }
        if (obj[key] !== undefined) { toast('Entry already exists: ' + key, 'error'); return; }
        obj[key] = { name: id };
        // Select the new entry in the master-detail view (no-op for accordion).
        SELECTED_ITEM[path] = path + '.' + key;
    } else {
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

function removeItem(path) {
    if (!confirm('Remove this item?')) return;
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
    // Auswahl im Master-Detail zuruecksetzen — renderMasterDetail faellt dann
    // auf den ersten verbliebenen Eintrag zurueck.
    const arrPath = (typeof last === 'number')
        ? path.replace(/\[\d+\]$/, '')
        : path.replace(/\.[^.\[\]]+$/, '');
    delete SELECTED_ITEM[arrPath];
    renderSection(ACTIVE_SECTION);
}

// Duplicates an array or dict entry (LLM routing, backends, ...). For dicts
// a new key is prompted; for arrays the clone is appended after the original.
// `name` fields get a "(Kopie)" suffix so the duplicate is distinguishable.
function duplicateItem(path) {
    const parts = parsePath(path);
    let parent = CONFIG;
    for (let i = 0; i < parts.length - 1; i++) {
        parent = parent[parts[i]];
    }
    const last = parts[parts.length - 1];
    const original = (typeof last === 'number') ? parent[last] : parent[last];
    if (!original) { toast('Eintrag nicht gefunden', 'error'); return; }
    // Deep clone — Defaults sollen nicht mit dem Original geteilt werden.
    const copy = JSON.parse(JSON.stringify(original));
    if (copy && typeof copy === 'object' && 'name' in copy && copy.name) {
        copy.name = String(copy.name) + ' (Kopie)';
    }
    if (typeof last === 'number') {
        // Array: direkt hinter Original einfuegen
        parent.splice(last + 1, 0, copy);
        const arrPath = path.replace(/\[\d+\]$/, '');
        SELECTED_ITEM[arrPath] = arrPath + '[' + (last + 1) + ']';
    } else {
        // Dict: neuen Key vom User abfragen — punktfrei halten (Dot-Notation
        // im Editor zerbricht sonst, s. addArrayItem).
        const rawKey = prompt('Neuer Schluessel fuer den Klon:', String(last) + '_copy');
        if (!rawKey) return;
        const newKey = rawKey.replace(/[.\[\]]/g, ' ').replace(/\s+/g, ' ').trim();
        if (!newKey) { toast('Ungueltiger Schluessel', 'error'); return; }
        if (parent[newKey] !== undefined) { toast('Schluessel existiert bereits: ' + newKey, 'error'); return; }
        parent[newKey] = copy;
        const arrPath = path.replace(/\.[^.\[\]]+$/, '');
        SELECTED_ITEM[arrPath] = arrPath + '.' + newKey;
    }
    renderSection(ACTIVE_SECTION);
}

function removeSubItem(path, index) {
    const parts = parsePath(path);
    let obj = CONFIG;
    for (const p of parts) obj = obj[p];
    obj.splice(index, 1);
    renderSection(ACTIVE_SECTION);
}

async function loadModels(path, provName) {
    if (!provName) {
        // Try to detect from sibling
        const parts = path.split('.');
        parts[parts.length - 1] = 'provider';
        provName = getVal(parts.join('.'));
    }
    if (!provName) { toast('Select a provider first', 'error'); return; }

    const sel = document.getElementById('f-' + path);
    if (!sel) return;
    const currentVal = sel.value;

    // Cache: leere Listen NICHT cachen (sonst blockt eine fehlgeschlagene
    // Abfrage alle Retry-Versuche bis zum Page-Reload).
    if (!PROVIDERS_CACHE[provName] || PROVIDERS_CACHE[provName].length === 0) {
        sel.innerHTML = '<option>Loading...</option>';
        try {
            const resp = await fetch('/admin/settings/providers/' + encodeURIComponent(provName) + '/models', { credentials: 'same-origin' });
            const data = await resp.json();
            if (data.error) { toast('Error: ' + data.error, 'error'); }
            const list = data.models || [];
            if (list.length > 0) {
                PROVIDERS_CACHE[provName] = list;
                PROVIDERS_VISION[provName] = new Set(data.vision || []);
            } else {
                delete PROVIDERS_CACHE[provName];
            }
        } catch (e) {
            toast('Failed to load models: ' + e.message, 'error');
            delete PROVIDERS_CACHE[provName];
        }
    }

    const models = PROVIDERS_CACHE[provName];
    const vis = PROVIDERS_VISION[provName] || new Set();
    let opts = '<option value="">— select —</option>';
    for (const m of models) {
        opts += '<option value="' + esc(m) + '"' + (m === currentVal ? ' selected' : '') + '>' + esc(m) + (vis.has(m) ? ' (vision)' : '') + '</option>';
    }
    sel.innerHTML = opts;
    if (currentVal && !models.includes(currentVal)) {
        sel.innerHTML = '<option value="' + esc(currentVal) + '" selected>' + esc(currentVal) + ' (not on server)</option>' + opts;
    }
}

function refreshModelSelect(provPath) {
    // When provider changes, clear model cache
    const parts = provPath.split('.');
    parts[parts.length - 1] = 'model';
    const modelPath = parts.join('.');
    const provName = getVal(provPath);
    if (provName) loadModels(modelPath, provName);
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
            html += '<h3>' + result.errors + ' errors, ' + result.warnings + ' warnings</h3>';
            for (const issue of issues) {
                html += '<div class="validate-issue ' + issue.level + '">';
                html += '<span class="badge">' + (issue.level === 'error' ? 'ERROR' : 'WARN') + '</span>';
                html += '<span>' + esc(issue.message) + '</span>';
                html += '<span class="section-link" onclick="activateSection(\'' + issue.section + '\')">' + issue.section + '</span>';
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
        else if (result.warnings > 0) toast(result.warnings + ' Warnungen', 'success');
        else toast('Alles OK!', 'success');
    } catch (e) {
        toast('Validation failed: ' + e.message, 'error');
    }
    btn.disabled = false;
    btn.textContent = 'Validate';
}

// Generischer Action-Button-Handler — schickt POST/DELETE/etc an einen Endpoint
// mit Body aus angegebenen Geschwister-Feldern. Genutzt von schema-Type "button".
async function runActionButton(endpoint, method, path, bodyFrom, confirmMsg, btn, previewUrl) {
    if (confirmMsg && !confirm(confirmMsg)) return;
    const body = {};
    // Werte aus DOM lesen (frischste Quelle — auch wenn User getippt aber
    // noch nicht gespeichert hat). Fallback auf CONFIG, dann auf
    // f-input-element.value als letzten Strohhalm fuer Defaults.
    for (const fld of (bodyFrom || [])) {
        const sibling = path + '.' + fld;
        let v = undefined;
        // 1. Versuche das DOM-Input direkt
        const el = document.getElementById('f-' + sibling);
        if (el && 'value' in el) {
            v = el.value;
        }
        // 2. Fallback: gespeicherter CONFIG-Wert
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
            // Preview-Bild neu laden (Cache-Bust via Timestamp) und Meta refreshen
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
    const btn = document.getElementById('btn-save');
    btn.disabled = true;
    btn.textContent = 'Saving...';
    try {
        const resp = await fetch('/admin/settings/save', {
            method: 'POST',
            headers: authHeaders(),
            body: JSON.stringify(CONFIG)
        });
        const result = await resp.json();
        if (resp.ok) {
            // URL/key changes should apply immediately, without a page reload:
            // invalidate the provider and imagegen backend model caches.
            for (const k of Object.keys(PROVIDERS_CACHE)) delete PROVIDERS_CACHE[k];
            for (const k of Object.keys(IMAGEGEN_MODELS_CACHE)) delete IMAGEGEN_MODELS_CACHE[k];
            toast(result.message || 'Saved!', 'success');
            // Nach Save pruefen, ob restart-pflichtige Felder veraendert wurden.
            loadRestartPending();
        } else {
            toast('Error: ' + (result.detail || result.message), 'error');
        }
    } catch (e) {
        toast('Save failed: ' + e.message, 'error');
    }
    btn.disabled = false;
    btn.textContent = 'Save';
}

async function loadRestartPending() {
    try {
        const resp = await fetch('/admin/settings/restart-pending', { credentials: 'same-origin' });
        if (!resp.ok) return;
        const data = await resp.json();
        renderRestartBanner(data.pending || []);
    } catch (e) {
        // Banner-Anzeige ist nicht kritisch — bei Fehler nicht stoeren.
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
function esc(s) {
    if (s === null || s === undefined) return '';
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function toast(msg, type) {
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.className = 'toast ' + type + ' show';
    setTimeout(() => t.classList.remove('show'), 3000);
}

// Start
init();
