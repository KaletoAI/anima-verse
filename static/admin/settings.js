
let CONFIG = {};
let SCHEMA = {};
let USE_CASE_DEFAULTS = { use_cases: [], families: [], defaults: {} };
let PROVIDERS_CACHE = {};
let PROVIDERS_VISION = {};  // provName -> Set(vision model names)
let ACTIVE_SECTION = null;
// Wenn ein Array-Item per User-Klick aufgeklappt wurde, halten wir den
// Pfad hier fest. So bleibt der Zustand ueber renderSection()-Rerenders
// (z.B. nach api_type-Wechsel via triggers_rerender) erhalten.
const OPEN_ITEMS = new Set();
// Master-Detail: pro Sub-Array-Pfad der aktuell ausgewaehlte Item-Pfad.
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
        } catch (e) { /* defaults bleiben leer */ }
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
                  + 'onchange="setVal(\'' + p + '\', this.value)">' + esc(val) + '</textarea></div>';
        }
        html += '</div>';
    }
    return html;
}

// „Copy default": schreibt den eingebauten Use-Case-Default in das Feld, damit
// man ihn bearbeiten kann. uc/fam/fld bestimmen den Default, p ist der Setz-Pfad.
function copyUseCaseDefault(p, uc, fam, fld) {
    const D = USE_CASE_DEFAULTS || { defaults: {} };
    const def = (((D.defaults || {})[uc] || {})[fam] || {})[fld] || '';
    if (!def) return;
    setVal(p, def);
    renderSection(ACTIVE_SECTION);
}

// Repository: LoRA -> activation word. List of {lora, word, endpoint, source,
// missing}; the image-creation code automatically prepends the word to the
// prompt whenever the LoRA is used. Stored in image_generation.lora_triggers
// (per world). The discovery sync job fills it from every backend with a
// LoRA Query URL; every LoRA dropdown in the UI feeds from this library.
function renderLoraTriggersEditor(path) {
    const items = getVal(path) || [];
    let html = '<p class="hint" style="opacity:.7;margin-bottom:12px">'
             + 'Central LoRA library of the world — <b>every LoRA dropdown</b> (game admin + player UI) '
             + 'feeds from this list. One activation word per LoRA: whenever an image uses the LoRA, '
             + 'the word is automatically prepended to the prompt.</p>';
    html += '<p class="hint" style="opacity:.7;margin-bottom:12px">'
             + 'Backends with a <b>LoRA Query URL</b> are scanned automatically (hourly + on '
             + '<b>Discover now</b>): found LoRAs are added as <b>discovered</b>; entries whose LoRA '
             + 'vanished are removed (discovered, untouched) or flagged <b style="color:#f85149">missing</b> '
             + '(manual / edited) and excluded from the dropdowns. Backends without a listing '
             + '(CivitAI, Together): add entries manually.</p>';
    html += '<div style="margin-bottom:12px;display:flex;gap:8px">'
          + '<button class="btn btn-sm" onclick="addLoraTrigger(\'' + path + '\')">+ Add</button>'
          + '<button class="btn btn-sm" onclick="syncLoraLibrary()">⟳ Discover now</button></div>';
    if (!items.length) {
        html += '<div class="md-empty">No entries yet. "Discover now" scans the backends; "+ Add" creates a manual entry.</div>';
    }
    for (let i = 0; i < items.length; i++) {
        const it = items[i] || {};
        const ip = path + '[' + i + ']';
        html += '<div class="lora-row" style="display:flex;gap:8px;align-items:flex-start;margin-bottom:6px">';
        // Column 1: endpoint assignment (backend name) — empty = all backends.
        // Prevents a LoRA from being offered on the wrong backend (other model).
        html += '<select title="Endpoint (backend) — empty = all" style="flex:2;min-width:0;background:#0d1117;color:#c9d1d9;border:1px solid #30363d;border-radius:6px;padding:6px" onchange="ltTouch(\'' + ip + '\', \'endpoint\', this.value); setVal(\'' + ip + '.endpoint\', this.value)">';
        html += '<option value="">— All endpoints —</option>';
        for (const be of ((CONFIG.image_generation && CONFIG.image_generation.backends) || [])) {
            const bn = be.name || '';
            if (!bn) continue;
            html += '<option value="' + esc(bn) + '"' + (bn === (it.endpoint || '') ? ' selected' : '') + '>' + esc(bn) + '</option>';
        }
        html += '</select>';
        // Column 2: LoRA name. Custom dark search combobox instead of a native
        // <select> (whose option list renders OS-side white). Free text allowed.
        html += '<div class="lt-combo" style="flex:3;min-width:0">';
        html += '<input type="text" class="lt-lora-input" autocomplete="off" value="' + esc(it.lora || '') + '" '
              + 'placeholder="LoRA name — type to search or note freely" style="width:100%" '
              + 'oninput="ltFilter(this, \'' + ip + '\')" '
              + 'onfocus="ltFilter(this, \'' + ip + '\')" '
              + 'onkeydown="ltKey(event, this, \'' + ip + '\')" '
              + 'onblur="ltBlur(this)">';
        html += '<div class="lt-dd"></div>';
        html += '</div>';
        // Column 3: activation word.
        html += '<input type="text" value="' + esc(it.word || '') + '" placeholder="Activation word" '
              + 'style="flex:2;min-width:0" onchange="ltTouch(\'' + ip + '\', \'word\', this.value); setVal(\'' + ip + '.word\', this.value)">';
        // Column 4: origin + availability badges.
        const src = it.source === 'discovered' ? 'discovered' : 'manual';
        html += '<span style="flex:0 0 auto;display:flex;flex-direction:column;gap:2px;align-items:flex-start;padding-top:4px">';
        html += '<span class="badge" title="' + (src === 'discovered' ? 'Found by the backend scan' : 'Created/edited by hand') + '" '
              + 'style="font-size:10px;' + (src === 'discovered' ? 'background:#1f3a5f;color:#79c0ff;' : '') + '">' + src + '</span>';
        if (it.missing) {
            html += '<span class="badge" title="No longer exists on its backend — excluded from dropdowns" '
                  + 'style="font-size:10px;background:#5a1e1e;color:#f85149;">missing</span>';
        }
        html += '</span>';
        html += '<button class="btn btn-sm" title="Copy (e.g. for another endpoint)" onclick="copyLoraTrigger(\'' + path + '\', ' + i + ')">⧉</button>';
        html += '<button class="btn btn-sm btn-danger" title="Delete" onclick="removeItem(\'' + ip + '\')">✕</button>';
        html += '</div>';
    }
    return html;
}

function addLoraTrigger(path) {
    const arr = _ensureContainer(path, 'array');
    arr.push({ lora: '', word: '', endpoint: '', source: 'manual', missing: false });
    renderSection(ACTIVE_SECTION);
}

// Duplicates a LoRA entry (same LoRA + word) right below — then just switch
// the endpoint to use the same LoRA for another backend. The copy is a manual
// claim (the scan verifies it against the new endpoint).
function copyLoraTrigger(path, i) {
    const arr = _ensureContainer(path, 'array');
    const src = arr[i] || {};
    arr.splice(i + 1, 0, { lora: src.lora || '', word: src.word || '', endpoint: src.endpoint || '', source: 'manual', missing: false });
    renderSection(ACTIVE_SECTION);
}

// Editing a discovered entry turns it into a manual claim: the sync job then
// flags it as missing instead of silently removing it when it vanishes.
// Only flips when the value actually changed (focus/no-op edits don't count).
function ltTouch(ip, field, newVal) {
    if ((getVal(ip + '.' + field) || '') === (newVal || '')) return;
    if (getVal(ip + '.source') === 'discovered') setVal(ip + '.source', 'manual');
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

// Suggestion list for the LoRA search combobox. There is no server-side LoRA
// scan anymore — suggestions are the LoRA names already entered in the list
// (useful when reusing the same LoRA for another endpoint).
function ltSuggestions() {
    const items = (CONFIG.image_generation && CONFIG.image_generation.lora_triggers) || [];
    const seen = {};
    const out = [];
    for (const it of items) {
        const n = (it && it.lora) ? String(it.lora) : '';
        if (n && !seen[n]) { seen[n] = true; out.push(n); }
    }
    return out;
}

// Fill the dropdown below the input, filtered by the typed text.
function ltFilter(inp, ip) {
    ltTouch(ip, 'lora', inp.value);   // renaming a discovered entry → manual
    setVal(ip + '.lora', inp.value);  // apply free text immediately
    const dd = inp.nextElementSibling;
    if (!dd) return;
    const q = (inp.value || '').toLowerCase();
    const all = ltSuggestions();
    const opts = q ? all.filter(function (m) { return m.toLowerCase().indexOf(q) !== -1; }) : all;
    if (!all.length) {
        dd.innerHTML = '<div class="lt-dd-empty">No suggestions — type the LoRA name manually</div>';
        dd.style.display = 'block';
        return;
    }
    if (!opts.length) {
        dd.innerHTML = '<div class="lt-dd-empty">Kein Treffer — Eingabe wird als Freitext gespeichert</div>';
        dd.style.display = 'block';
        return;
    }
    let h = '';
    for (let i = 0; i < opts.length && i < 80; i++) {
        h += '<div class="lt-opt" data-v="' + esc(opts[i]) + '" '
           + 'onmousedown="ltPick(this, \'' + ip + '\')">' + esc(opts[i]) + '</div>';
    }
    dd.innerHTML = h;
    dd.style.display = 'block';
}

// Mouse selection (onmousedown fires before onblur, so no race).
function ltPick(el, ip) {
    const v = el.getAttribute('data-v');
    const dd = el.parentElement;
    const inp = dd.previousElementSibling;
    inp.value = v;
    ltTouch(ip, 'lora', v);
    setVal(ip + '.lora', v);
    dd.style.display = 'none';
}

// Tastatur: Pfeil hoch/runter markiert, Enter uebernimmt, Esc schliesst.
function ltKey(ev, inp, ip) {
    const dd = inp.nextElementSibling;
    if (!dd || dd.style.display === 'none') return;
    const opts = dd.querySelectorAll('.lt-opt');
    if (!opts.length) return;
    let idx = -1;
    for (let i = 0; i < opts.length; i++) { if (opts[i].classList.contains('active')) { idx = i; break; } }
    if (ev.key === 'ArrowDown') { ev.preventDefault(); idx = Math.min(idx + 1, opts.length - 1); }
    else if (ev.key === 'ArrowUp') { ev.preventDefault(); idx = Math.max(idx - 1, 0); }
    else if (ev.key === 'Enter') {
        if (idx >= 0) { ev.preventDefault(); ltPick(opts[idx], ip); }
        return;
    } else if (ev.key === 'Escape') { dd.style.display = 'none'; return; }
    else { return; }
    for (let i = 0; i < opts.length; i++) opts[i].classList.toggle('active', i === idx);
    opts[idx].scrollIntoView({ block: 'nearest' });
}

function ltBlur(inp) {
    // Verzoegert schliessen, damit ein Klick auf eine Option noch ankommt.
    setTimeout(function () { const dd = inp.nextElementSibling; if (dd) dd.style.display = 'none'; }, 150);
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
    // renderSubArrayPage), damit die Hauptseite nicht ueberladen ist.

    // Array sections (providers)
    if (sec.is_array) {
        if (key === 'llm_routing') {
            // Zweispaltig: links Editor, rechts Task-View (read-only)
            html += '<div style="display:grid; grid-template-columns: 1fr 1fr; gap:20px;">';
            html += '<div>';
            html += '<div style="margin-bottom: 12px;">';
            html += '<button class="btn btn-sm" onclick="addArrayItem(\'' + key + '\', \'array\')">+ Add LLM</button>';
            html += '</div>';
            html += renderArrayItems(sec, data || [], key);
            html += '</div>';
            html += '<div>';
            html += '<div class="subsection-title" style="margin-bottom:8px;">Sichtweise pro Task</div>';
            html += '<div id="llm-task-view"><div class="desc">Loading…</div></div>';
            html += '</div>';
            html += '</div>';
            // Der Tool-/Helper-Eignungstest lebt jetzt unter "Model Capabilities".
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
    const tasks = await loadLlmTasks();
    llmSimpleDetect(tasks);

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
    // Model-Dropdowns initial fuellen (aus Cache / interne Choices)
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

// Schreibt CONFIG.llm_routing (order=1) + CONFIG.embedding aus LLM_SIMPLE_SEL.
function llmSimpleRebuild() {
    const tasks = LLM_TASKS_CACHE || [];
    const byCat = {};
    for (const t of tasks) (byCat[t.category] = byCat[t.category] || []).push(t.id);
    // Kopie ziehen, dann alle order==1-Zuordnungen entfernen (Fallbacks bleiben)
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
    // Leer gewordene Eintraege entfernen (ausser sie sind nur zum Preload da)
    routing = routing.filter(e => (e.tasks && e.tasks.length) || e.preload_on_startup);
    CONFIG.llm_routing = routing;
    // Embedding-Config
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

async function renderLlmTaskView(entries) {
    const tasks = await loadLlmTasks();
    const view = document.getElementById('llm-task-view');
    if (!view) return;

    // State vom Server laden (runtime + persistent + presets)
    let state = { disabled: [], runtime_disabled: [], presets: {} };
    try {
        const r = await fetch('/admin/settings/llm-task-state', { credentials: 'same-origin' });
        if (r.ok) state = await r.json();
    } catch (e) {}

    // Persistent disabled aus CONFIG (UI-Quelle fuer Toggles)
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

    let html = '';
    // Preset-Selector (runtime, nicht persistent — gilt nur fuer diese Server-Session)
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

    // Sortierung nach Category (chat → tool → helper → image), innerhalb
    // dann nach Label. So sind groessere Modelle (chat) oben, kleine
    // Helfer unten — entspricht der Lese-Erwartung "wer braucht was".
    const _CAT_ORDER = { chat: 0, tool: 1, helper: 2, image: 3, embedding: 4 };
    // Per-Category Farben fuer Border + Badge:
    //   chat:   blau    — grosse Modelle
    //   tool:   violett — strukturierte Outputs
    //   helper: gruen   — kleine/billige Modelle
    //   image:  orange  — Vision / Bild-IO
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
        // Category-Header bei Wechsel
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
        if (isRuntimeDisabled) {
            html += '<div style="font-size:11px; color:#d29922;">runtime-disabled (preset)</div>';
        }
        if (isEmpty) {
            // pose_embedding laeuft ueber CONFIG.embedding (eingebautes fastembed/ONNX
            // oder externer /v1/embeddings-Provider), NICHT ueber llm_routing. Bei
            // internem/auto-Backend ist "no LLM assigned" irrefuehrend -> echten Status zeigen.
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
        // Sibling-value visibility: `visible_when: {field: value}` shows the
        // field only while every referenced sibling field holds the required
        // value (e.g. the inpaint-only mask fields behind Category=inpaint).
        // The gating select needs `triggers_rerender` so toggling it re-runs
        // this filter immediately.
        if (f.visible_when && typeof f.visible_when === 'object') {
            let visible = true;
            for (const [depKey, depVal] of Object.entries(f.visible_when)) {
                const cur = (data && data[depKey] !== undefined && data[depKey] !== null)
                    ? data[depKey] : '';
                if (cur !== depVal) { visible = false; break; }
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
        let desc = f.description || '';
        if (f.default !== undefined && f.default !== ''
            && (typeof f.default === 'string' || typeof f.default === 'number' || typeof f.default === 'boolean')) {
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

function renderInput(f, val, path) {
    const id = 'f-' + path;
    switch (f.type) {
        case 'bool':
            return '<input type="checkbox" id="' + id + '" ' + (val ? 'checked' : '') + ' onchange="setVal(\'' + path + '\', this.checked)">';
        case 'int':
            return '<input type="number" id="' + id + '" value="' + esc(val) + '" '
                + (f.min !== undefined ? 'min="' + f.min + '" ' : '')
                + (f.max !== undefined ? 'max="' + f.max + '" ' : '')
                + 'step="1" onchange="setVal(\'' + path + '\', parseInt(this.value) || 0)">';
        case 'float':
            return '<input type="number" id="' + id + '" value="' + esc(val) + '" '
                + (f.min !== undefined ? 'min="' + f.min + '" ' : '')
                + (f.max !== undefined ? 'max="' + f.max + '" ' : '')
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
            return '<textarea id="' + id + '" onchange="setVal(\'' + path + '\', this.value)">' + esc(val) + '</textarea>';
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
        default: // str
            return '<input type="text" id="' + id + '" value="' + esc(val) + '" '
                + (f.placeholder ? 'placeholder="' + esc(f.placeholder) + '" ' : '')
                + 'onchange="setVal(\'' + path + '\', this.value)">';
    }
}

function renderProviderSelect(val, path) {
    const providers = CONFIG.providers || [];
    let opts = '<option value="">— Auto —</option>';
    for (const p of providers) {
        opts += '<option value="' + esc(p.name) + '"' + (p.name === val ? ' selected' : '') + '>' + esc(p.name) + ' (' + p.type + ')</option>';
    }
    return '<select id="f-' + path + '" onchange="setVal(\'' + path + '\', this.value); refreshModelSelect(\'' + path + '\')">' + opts + '</select>';
}

function renderModelSelect(val, path) {
    // Provider wird zur Klick-Zeit aus dem Geschwister-Feld gelesen (nicht zur
    // Render-Zeit eingebrannt), sonst zeigt der Button nach einem Provider-
    // Wechsel weiter auf den alten Provider und holt die falsche Modell-Liste.
    let select = '<select id="f-' + path + '" onchange="setVal(\'' + path + '\', this.value)">';
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
// Value format: "backend:<name>" (as served by /settings/imagegen-targets)
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
        return '<span class="md-status ' + (on ? 'on' : 'off') + '">' + (on ? '● on' : '○ off') + '</span>';
    }
    if (v === undefined || v === null || v === '') return '<span class="md-empty">—</span>';
    return esc(String(v));
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
let LLM_TASKS_CACHE = null;

async function loadLlmTasks(forceRefresh) {
    if (LLM_TASKS_CACHE && !forceRefresh) return LLM_TASKS_CACHE;
    try {
        // cache-bust per Query-Param damit Browser nicht aus dem HTTP-Cache
        // serviert (z.B. nach Server-Neustart mit neuen Sub-Tasks).
        const resp = await fetch('/admin/settings/llm-tasks?_=' + Date.now(),
            { credentials: 'same-origin', cache: 'no-store' });
        LLM_TASKS_CACHE = await resp.json();
    } catch (e) {
        LLM_TASKS_CACHE = [];
    }
    return LLM_TASKS_CACHE;
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
    html += '<select data-taskrow="' + path + '-' + i + '" style="flex:3;" onchange="setVal(\'' + path + '[' + i + '].task\', this.value)">';
    html += '<option value="' + esc(task) + '" selected>' + esc(task || '— select —') + '</option>';
    html += '</select>';
    html += '<input type="number" value="' + order + '" min="1" step="1" style="max-width:70px;" title="Order" onchange="setVal(\'' + path + '[' + i + '].order\', parseInt(this.value) || 1)">';
    html += '<button class="btn btn-sm btn-danger" onclick="removeTaskOrderRow(\'' + path + '\', ' + i + ')">✕</button>';
    html += '</div>';
    return html;
}

async function populateTaskSelects(path) {
    const tasks = await loadLlmTasks();
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
}

// True, wenn der Routing-Eintrag mindestens einen Task der Gruppe "embedding"
// bedient (Embedding-Modelle nutzen kein temperature/max_tokens).
function _entryIsEmbedding(data) {
    if (!data || !Array.isArray(data.tasks) || !data.tasks.length) return false;
    const cache = LLM_TASKS_CACHE || [];
    const embedIds = new Set(cache.filter(t => t.category === 'embedding').map(t => t.id));
    if (!embedIds.size) embedIds.add('pose_embedding');  // Fallback bis Cache geladen
    return data.tasks.some(it => it && embedIds.has(it.task));
}

// Blendet temperature/max_tokens bei Embedding-Eintraegen aus (Post-Pass, damit
// es auch live beim Hinzufuegen/Entfernen des Tasks toggelt).
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
    const tasks = await loadLlmTasks();
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
    const tasks = await loadLlmTasks();
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
    toast('Order=' + order + ' fuer alle ' + obj.length + ' Tasks gesetzt', 'success');
}

function rerenderTaskOrderList(path) {
    // Re-render nur den Tasks-Container statt die ganze Section — damit
    // das umgebende Array-Item offen bleibt.
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
    // Sichtweise rechts mit aktualisieren wenn wir im llm_routing-Tab sind
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
