// ── Media Generation › Routing: ONE backend chain per render occasion ──
// development_instructions/plan-image-routing.md § 6. Loaded AFTER
// static/admin/settings.js and uses its globals at run time (CONFIG, SCHEMA,
// ACTIVE_PAGE, esc, sJs, toast, authHeaders) — deliberately no escaper of its
// own (scripts/smoke_admin_escape.mjs: one escaper per file).
//
// Two pages of the paged section `image_generation` (config_schema.py):
//   routing           Rules — one card per occasion with its ordered chain
//   routing_overview  Overview — GET /admin/settings/image-routing/effective
// Config model: CONFIG.image_generation.routing = {occasion: [glob, ...]};
// the order in the list is the position (1..n). Saved with the Save button;
// saveConfig() hands every outcome to imageRoutingSaveResult() so a refused
// chain stays visible on the Rules page. Loading the page never rewrites a
// stored chain — a malformed or unknown one is shown with a remove button.

// >>> harness-extract:imageRoutingModel
// Pure functions over the routing object {occasion: [spec]} and plain
// catalog/backend rows. No DOM, no globals — scripts/check_image_routing_model.js
// runs this block on its own. The kind rule mirrors
// app/imagegen/occasions.py::backend_fits; the glob rule mirrors fnmatch.
function irNormSpec(spec) {
    let s = String(spec === undefined || spec === null ? '' : spec).trim();
    if (/^workflow:/i.test(s)) s = s.slice(9).trim();
    if (/^backend:/i.test(s)) s = s.slice(8).trim();
    return s;
}

function irChain(routing, occ) {
    const c = routing && Array.isArray(routing[occ]) ? routing[occ] : [];
    return c.filter(s => typeof s === 'string');
}

function _irHas(chain, spec, exceptIdx) {
    const k = spec.toLowerCase();
    return chain.some((s, i) => i !== exceptIdx && irNormSpec(s).toLowerCase() === k);
}

function irAdd(routing, occ, spec) {
    const s = irNormSpec(spec);
    if (!s) return false;
    const chain = irChain(routing, occ);
    if (_irHas(chain, s, -1)) return false;
    chain.push(s);
    routing[occ] = chain;
    return true;
}

function irRemove(routing, occ, idx) {
    const chain = irChain(routing, occ);
    if (idx < 0 || idx >= chain.length) return false;
    chain.splice(idx, 1);
    if (chain.length) routing[occ] = chain; else delete routing[occ];
    return true;
}

function irMove(routing, occ, idx, delta) {
    const chain = irChain(routing, occ);
    const j = idx + delta;
    if (idx < 0 || idx >= chain.length || j < 0 || j >= chain.length) return false;
    const t = chain[idx]; chain[idx] = chain[j]; chain[j] = t;
    routing[occ] = chain;
    return true;
}

function irSet(routing, occ, idx, spec) {
    const chain = irChain(routing, occ);
    if (idx < 0 || idx >= chain.length) return false;
    const s = irNormSpec(spec);
    if (!s) return irRemove(routing, occ, idx);
    if (_irHas(chain, s, idx)) return false;
    chain[idx] = s;
    routing[occ] = chain;
    return true;
}

// Python's fnmatch.translate, case-insensitive (the server lowers both
// sides): '*' any run, '?' one char, '[...]' a class where a leading '!'
// negates, a leading '^' is literal, a ']' right after '[' / '[!' is a
// member, and an unclosed '[' is literal. A class JS cannot compile
// (a reversed range like [z-a]) never matches — fnmatch drops such ranges.
function irGlobToRegex(pattern) {
    const p = String(pattern || '');
    let re = '';
    for (let i = 0; i < p.length; i++) {
        const c = p[i];
        if (c === '*') re += '.*';
        else if (c === '?') re += '.';
        else if (c === '[') {
            let j = i + 1;
            if (p[j] === '!') j++;
            if (p[j] === ']') j++;
            const k = p.indexOf(']', j);
            if (k < 0) { re += '\\['; continue; }
            let body = p.slice(i + 1, k);
            const neg = body.startsWith('!');
            if (neg) body = body.slice(1);
            re += '[' + (neg ? '^' : '') + body.replace(/[\\\]\[^]/g, '\\$&') + ']';
            i = k;
        } else {
            re += c.replace(/[.*+?^${}()|[\]\\\/]/g, '\\$&');
        }
    }
    try {
        return new RegExp('^' + re + '$', 'is');
    } catch (e) {
        return /(?!)/;
    }
}

function irMatches(pattern, backends) {
    const s = irNormSpec(pattern);
    if (!s) return [];
    const re = irGlobToRegex(s);
    return (backends || []).filter(b => b && re.test(String(b.name || ''))).map(b => b.name);
}

function irFits(occ, b) {
    if (!occ || !b) return false;
    if ((b.media || 'image') !== occ.media) return false;
    const cat = String(b.category || '').toLowerCase();
    if (occ.media === 'mesh') {
        if (cat === 'mesh2mesh') return false;
        return (String(b.rig || 'mixamo').toLowerCase() || 'mixamo') === occ.rig;
    }
    if (cat === 'inpaint') return false;
    if (occ.needs_ref_slot && (Number(b.ref_slot_count) || 0) < 1) return false;
    return true;
}

function irVerdict(occ, spec, backends) {
    const names = new Set(irMatches(spec, backends));
    if (!names.size) return 'no_match';
    return (backends || []).some(b => names.has(b.name) && irFits(occ, b)) ? 'ok' : 'wrong_kind';
}

// A chain the page can edit: a list of strings. Anything else (a string, an
// object, a list with a non-string member) is shown as stored, never rewritten.
function irWellFormed(chain) {
    return Array.isArray(chain) && chain.every(s => typeof s === 'string');
}

// Read-only survey of the STORED routing. It never mutates: loading the page
// must not turn an untouched chain into an edited one — the save refuses an
// EDITED invalid chain (HTTP 400) but only warns about an unchanged one.
//   root_ok    false when the routing is not a plain object (absent = {})
//   unknown    keys that are not catalog occasions, in key order
//   malformed  catalog occasions whose chain is not a list of strings
function irSurvey(routing, knownIds) {
    const out = { root_ok: true, unknown: [], malformed: [] };
    if (routing === undefined || routing === null) return out;
    if (typeof routing !== 'object' || Array.isArray(routing)) { out.root_ok = false; return out; }
    for (const occ of Object.keys(routing)) {
        if (!knownIds.has(occ)) out.unknown.push(occ);
        else if (!irWellFormed(routing[occ])) out.malformed.push(occ);
    }
    return out;
}

// {index: note} for the entries of a stored chain the server skips:
// 'empty' (blank after trim + prefix strip) or 'duplicate' (the same pattern
// as an earlier entry, case-insensitive). Shown, never removed on load.
function irEntryNotes(chain) {
    const notes = {}, seen = new Set();
    (Array.isArray(chain) ? chain : []).forEach((raw, i) => {
        const k = irNormSpec(raw).toLowerCase();
        if (!k) notes[i] = 'empty';
        else if (seen.has(k)) notes[i] = 'duplicate';
        else seen.add(k);
    });
    return notes;
}
// <<< harness-extract:imageRoutingModel

// ── User-facing strings (English only — Python-rendered admin page) ────
const IR_TEXT = {
    rulesTitle: 'Routing', overviewTitle: 'Routing overview',
    rulesIntro: 'One chain per render occasion. A render uses the FIRST entry that names a usable '
              + 'backend right now; a failure re-runs the whole occasion on the next entry. An empty '
              + 'chain uses the cheapest available backend of the right kind; a chain whose entries '
              + 'are all unusable fails instead of falling back to the cheapest.',
    position0: 'Position 0: the character\'s own backend match (Characters → Image) comes before this chain.',
    emptyChain: 'empty — cheapest available backend of this kind',
    addPlaceholder: 'Backend name or glob, e.g. Flux*', add: 'Add',
    moveUp: 'Move up (earlier)', moveDown: 'Move down (later)', remove: 'Remove',
    noMatch: 'matches no backend', wrongKind: 'only backends of the wrong kind',
    matches: 'matches: {names}', more: '+{n} more', duplicate: 'Already in this chain.',
    entryEmpty: 'empty entry — ignored', entryDuplicate: 'listed twice — ignored, remove one',
    malformed: 'The stored chain is not a list of patterns and is ignored: {raw}. Remove it to edit this occasion.',
    removeChain: 'Remove chain',
    rootMalformed: 'The stored routing is not an object {occasion: [pattern, …]} and is ignored: {raw}.',
    rootReset: 'Replace with an empty routing',
    unknownTitle: 'Chains for unknown occasions',
    unknownHint: 'These occasion ids are not in the catalog (removed or renamed). They have no effect — remove them.',
    saveHint: 'Changes take effect after Save.',
    saveRefused: 'The last Save was refused — nothing was saved. Fix the chain below and save again:',
    saveWarnings: 'The last Save succeeded with warnings:',
    catalogFailed: 'Could not load the occasion catalog.',
    ovBanner: 'Shows the SAVED configuration as the server resolves it right now — unsaved changes are not included. Nothing is probed.',
    ovTie: 'When several usable backends of a chain entry cost the same, a render rotates between them and may use another one than shown here.',
    ovCharacter: 'For character:', ovNoCharacter: '— no character —', refresh: 'Refresh', loading: 'Loading…',
    ovError: 'Could not load the effective routing ({what}). After a code update the server needs a restart.',
    ovResolved: 'renders on', ovNone: 'no backend', ovCheapest: 'cheapest', ovCharPos: 'character',
    mediaImage: 'image', mediaVideo: 'video', mediaMesh: 'mesh', charScoped: 'per character',
};

let IR_OCCASIONS = null;   // catalog rows (GET …/occasions)
let IR_BACKENDS = null;    // backend rows (GET …/backends)
let IR_OV_CHARACTER = '';
let IR_CHARACTERS = null;
let IR_SAVE_NOTICE = null; // {kind: 'error'|'warn', lines: [..]} of the last Save

function irFmt(tpl, vars) {
    return String(tpl).replace(/\{(\w+)\}/g, (m, k) => (vars && vars[k] !== undefined ? String(vars[k]) : m));
}

// A stored value as short JSON for a notice (it is shown, not edited).
function irRaw(v) {
    let t;
    try { t = JSON.stringify(v); } catch (e) { t = String(v); }
    if (t === undefined) t = String(v);
    return t.length > 160 ? t.slice(0, 157) + '…' : t;
}

async function irFetchJson(url) {
    const r = await fetch(url, { credentials: 'same-origin', cache: 'no-store' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return r.json();
}

// The stored routing as loaded — read only, may be absent or malformed.
function irStored() {
    const ig = CONFIG.image_generation;
    return (ig && typeof ig === 'object') ? ig.routing : undefined;
}

// The routing object for an EDIT — created on the first edit only.
function irRouting() {
    if (!CONFIG.image_generation || typeof CONFIG.image_generation !== 'object') CONFIG.image_generation = {};
    const ig = CONFIG.image_generation;
    if (!ig.routing || typeof ig.routing !== 'object' || Array.isArray(ig.routing)) ig.routing = {};
    return ig.routing;
}

async function irLoadCatalog() {
    if (IR_OCCASIONS === null) {
        try { IR_OCCASIONS = (await irFetchJson('/admin/settings/image-routing/occasions')).occasions || []; }
        catch (e) { IR_OCCASIONS = null; toast(IR_TEXT.catalogFailed + ' ' + e.message, 'error'); }
    }
    if (IR_BACKENDS === null) {
        try {
            const d = await irFetchJson('/admin/settings/image-routing/backends');
            IR_BACKENDS = Array.isArray(d) ? d : [];
        } catch (e) { IR_BACKENDS = []; }
    }
}

function irTitle(label, icon) {
    const sec = SCHEMA.image_generation || {};
    return '<h1 class="section-title">' + esc(sec.icon || '') + ' ' + esc(sec.label || 'Media Generation')
         + ' <span style="color:#8b949e;">›</span> ' + esc(icon) + ' ' + esc(label) + '</h1>';
}

function irMediaBadge(o) {
    const m = o.media === 'video' ? IR_TEXT.mediaVideo : (o.media === 'mesh' ? IR_TEXT.mediaMesh : IR_TEXT.mediaImage);
    let t = m + (o.rig ? ' · ' + o.rig : '');
    if (o.character_scoped) t += ' · ' + IR_TEXT.charScoped;
    return '<span class="rt-taskchip">' + esc(t) + '</span>';
}

async function renderImageRoutingPage(pageId) {
    ACTIVE_PAGE = pageId;
    const content = document.getElementById('content');
    await irLoadCatalog();
    // The user may have navigated away while the catalog loaded.
    if (ACTIVE_SECTION !== 'image_generation' || ACTIVE_PAGE !== pageId) return;
    if (pageId === 'routing_overview') return renderImageRoutingOverview(content);
    return renderImageRoutingRules(content);
}

// Re-render the Rules page in place, keeping the scroll position.
function irRerender(msg) {
    const content = document.getElementById('content');
    const top = content ? content.scrollTop : 0;
    renderImageRoutingRules(content);
    if (content) content.scrollTop = top;
    if (msg) toast(msg, 'success');
}

// Called by saveConfig() in settings.js with every Save outcome. A refusal
// by the image routing validator (HTTP 400, "Image routing: …") and the
// save warnings stay on the Rules page until the next Save.
function imageRoutingSaveResult(ok, result) {
    const r = result || {};
    const detail = typeof r.detail === 'string' ? r.detail : '';
    const warnings = Array.isArray(r.warnings) ? r.warnings.filter(w => typeof w === 'string' && w) : [];
    if (!ok && detail.startsWith('Image routing:')) IR_SAVE_NOTICE = { kind: 'error', lines: [detail] };
    else if (ok && warnings.length) IR_SAVE_NOTICE = { kind: 'warn', lines: warnings };
    else IR_SAVE_NOTICE = null;
    if (ACTIVE_SECTION === 'image_generation' && ACTIVE_PAGE === 'routing' && IR_OCCASIONS !== null) irRerender();
}

function irSaveNoticeHtml() {
    const n = IR_SAVE_NOTICE;
    if (!n) return '';
    const err = n.kind === 'error';
    let html = '<div class="rt-card problem" style="margin-bottom:12px;">'
             + '<div style="font-size:12px; font-weight:600; color:' + (err ? '#f85149' : '#d29922') + ';">'
             + (err ? '✖ ' : '⚠ ') + esc(err ? IR_TEXT.saveRefused : IR_TEXT.saveWarnings) + '</div>';
    for (const line of n.lines) html += '<div class="desc ' + (err ? 'rt-err' : 'rt-warn') + '">' + esc(line) + '</div>';
    return html + '</div>';
}

// ── Rules page ─────────────────────────────────────────────────────────
function renderImageRoutingRules(content) {
    const stored = irStored();
    const occs = IR_OCCASIONS || [];
    const known = new Set(occs.map(o => o.id));
    const survey = irSurvey(stored, known);
    let html = '<div class="section active">' + irTitle(IR_TEXT.rulesTitle, '🧭');
    html += '<div class="desc" style="margin-bottom:12px;">' + esc(IR_TEXT.rulesIntro) + ' ' + esc(IR_TEXT.saveHint) + '</div>';
    html += irSaveNoticeHtml();
    if (IR_OCCASIONS === null) {
        html += '<div class="rt-err">' + esc(IR_TEXT.catalogFailed) + '</div></div>';
        content.innerHTML = html;
        return;
    }

    if (!survey.root_ok) {
        html += '<div class="rt-card problem" style="margin-bottom:12px;">'
             + '<div class="rt-err">' + esc(irFmt(IR_TEXT.rootMalformed, { raw: irRaw(stored) })) + '</div>'
             + '<div style="margin-top:6px;"><button class="btn btn-sm" onclick="irResetRouting()">'
             + esc(IR_TEXT.rootReset) + '</button></div></div></div>';
        content.innerHTML = html;
        return;
    }
    const routing = stored || {};

    if (survey.unknown.length) {
        html += '<div class="rt-card problem" style="margin-bottom:12px;">';
        html += '<div style="font-size:12px; font-weight:600; color:#d29922;">⚠ ' + esc(IR_TEXT.unknownTitle) + '</div>';
        html += '<div class="desc">' + esc(IR_TEXT.unknownHint) + '</div>';
        for (const occ of survey.unknown) {
            html += '<div class="rt-chain-row"><span class="rt-err">' + esc(occ) + '</span>'
                 + '<span class="rt-muted">' + esc(irRaw(routing[occ])) + '</span>'
                 + '<span style="margin-left:auto;"><button class="btn btn-sm" title="' + esc(IR_TEXT.remove) + '" '
                 + 'onclick="irDropOccasion(\'' + sJs(occ) + '\')">✕</button></span></div>';
        }
        html += '</div>';
    }

    const malformed = new Set(survey.malformed);
    for (const o of occs) {
        html += '<div class="rt-card">';
        html += '<div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;">'
             + '<span style="font-size:12px; color:#58a6ff; font-weight:600;" title="' + esc(o.covers || '') + '">'
             + esc(o.label) + '</span>' + irMediaBadge(o)
             + '<span class="rt-muted" style="font-size:11px;">— ' + esc(o.id) + '</span></div>';
        if (o.covers) html += '<div class="desc rt-muted">' + esc(o.covers) + '</div>';
        if (o.character_scoped) html += '<div class="desc rt-muted">' + esc(IR_TEXT.position0) + '</div>';
        if (malformed.has(o.id)) {
            html += '<div class="rt-chain-row"><span class="rt-err">'
                 + esc(irFmt(IR_TEXT.malformed, { raw: irRaw(routing[o.id]) })) + '</span>'
                 + '<span style="margin-left:auto;"><button class="btn btn-sm" '
                 + 'onclick="irDropOccasion(\'' + sJs(o.id) + '\')">' + esc(IR_TEXT.removeChain) + '</button></span></div>';
            html += '</div>';
            continue;
        }
        html += irChainHtml(o, irChain(routing, o.id));
        html += '</div>';
    }
    html += '</div>';
    content.innerHTML = html;
}

function irChainHtml(o, chain) {
    const backends = IR_BACKENDS || [];
    const fitting = backends.filter(b => irFits(o, b)).map(b => b.name);
    const dl = 'ir-dl-' + o.id;
    const notes = irEntryNotes(chain);
    let html = '<datalist id="' + esc(dl) + '">' + fitting.map(n => '<option value="' + esc(n) + '">').join('') + '</datalist>';
    if (!chain.length) html += '<div class="desc rt-muted">' + esc(IR_TEXT.emptyChain) + '</div>';
    chain.forEach((spec, i) => {
        html += '<div class="rt-chain-row">';
        html += '<span class="rt-muted" style="min-width:20px;">' + (i + 1) + '.</span>';
        html += '<input type="text" list="' + esc(dl) + '" value="' + esc(spec) + '" style="min-width:220px;" '
             + 'onchange="irSetEntry(\'' + sJs(o.id) + '\', ' + i + ', this.value)">';
        if (notes[i] === 'empty') html += '<span class="rt-warn">' + esc(IR_TEXT.entryEmpty) + '</span>';
        else if (notes[i] === 'duplicate') html += '<span class="rt-warn">' + esc(IR_TEXT.entryDuplicate) + '</span>';
        else {
            const verdict = irVerdict(o, spec, backends);
            if (verdict === 'no_match') html += '<span class="rt-warn">' + esc(IR_TEXT.noMatch) + '</span>';
            else if (verdict === 'wrong_kind') html += '<span class="rt-err">' + esc(IR_TEXT.wrongKind) + '</span>';
            else {
                const names = irMatches(spec, backends);
                const shown = names.slice(0, 4).join(', ') + (names.length > 4 ? ' ' + irFmt(IR_TEXT.more, { n: names.length - 4 }) : '');
                html += '<span class="rt-muted">' + esc(irFmt(IR_TEXT.matches, { names: shown })) + '</span>';
            }
        }
        html += '<span style="margin-left:auto; display:inline-flex; gap:4px;">';
        html += '<button class="btn btn-sm" title="' + esc(IR_TEXT.moveUp) + '"' + (i === 0 ? ' disabled' : '')
             + ' onclick="irMoveEntry(\'' + sJs(o.id) + '\', ' + i + ', -1)">↑</button>';
        html += '<button class="btn btn-sm" title="' + esc(IR_TEXT.moveDown) + '"' + (i === chain.length - 1 ? ' disabled' : '')
             + ' onclick="irMoveEntry(\'' + sJs(o.id) + '\', ' + i + ', 1)">↓</button>';
        html += '<button class="btn btn-sm" title="' + esc(IR_TEXT.remove) + '"'
             + ' onclick="irRemoveEntry(\'' + sJs(o.id) + '\', ' + i + ')">✕</button>';
        html += '</span></div>';
    });
    html += '<div style="margin-top:6px; display:flex; gap:6px; align-items:center;">'
         + '<input type="text" id="ir-new-' + esc(o.id) + '" list="' + esc(dl) + '" placeholder="' + esc(IR_TEXT.addPlaceholder) + '" '
         + 'style="min-width:220px;" onkeydown="if (event.key === \'Enter\') irAddFromInput(\'' + sJs(o.id) + '\')">'
         + '<button class="btn btn-sm" onclick="irAddFromInput(\'' + sJs(o.id) + '\')">' + esc(IR_TEXT.add) + '</button></div>';
    return html;
}

function irAddFromInput(occ) {
    const el = document.getElementById('ir-new-' + occ);
    if (!el) return;
    if (!irAdd(irRouting(), occ, el.value)) {
        if (irNormSpec(el.value)) toast(IR_TEXT.duplicate, 'error');
        return;
    }
    irRerender();
}

function irSetEntry(occ, idx, value) {
    if (!irSet(irRouting(), occ, idx, value)) toast(IR_TEXT.duplicate, 'error');
    irRerender();
}

function irMoveEntry(occ, idx, delta) {
    if (irMove(irRouting(), occ, idx, delta)) irRerender();
}

function irRemoveEntry(occ, idx) {
    if (irRemove(irRouting(), occ, idx)) irRerender();
}

function irDropOccasion(occ) {
    delete irRouting()[occ];
    irRerender();
}

function irResetRouting() {
    CONFIG.image_generation.routing = {};
    irRerender();
}

// ── Overview page ──────────────────────────────────────────────────────
async function renderImageRoutingOverview(content) {
    if (IR_CHARACTERS === null) {
        try { IR_CHARACTERS = ((await irFetchJson('/characters/list')).characters || []).map(c => c.name).filter(Boolean); }
        catch (e) { IR_CHARACTERS = []; }
    }
    let html = '<div class="section active">' + irTitle(IR_TEXT.overviewTitle, '📋');
    html += '<div class="desc" style="margin-bottom:4px;">' + esc(IR_TEXT.ovBanner) + '</div>';
    html += '<div class="desc" style="margin-bottom:8px;">' + esc(IR_TEXT.ovTie) + '</div>';
    html += '<div style="margin-bottom:12px; display:flex; gap:8px; align-items:center;">'
         + '<span class="desc">' + esc(IR_TEXT.ovCharacter) + '</span>'
         + '<select onchange="irOverviewCharacter(this.value)">'
         + '<option value="">' + esc(IR_TEXT.ovNoCharacter) + '</option>'
         + IR_CHARACTERS.map(n => '<option value="' + esc(n) + '"' + (n === IR_OV_CHARACTER ? ' selected' : '') + '>' + esc(n) + '</option>').join('')
         + '</select>'
         + '<button class="btn btn-sm" onclick="irOverviewRefresh()">' + esc(IR_TEXT.refresh) + '</button></div>';
    html += '<div id="ir-ov-body" class="desc">' + esc(IR_TEXT.loading) + '</div></div>';
    content.innerHTML = html;
    let data = null, what = '';
    try {
        data = await irFetchJson('/admin/settings/image-routing/effective?character=' + encodeURIComponent(IR_OV_CHARACTER));
    } catch (e) { what = e.message || String(e); }
    const body = document.getElementById('ir-ov-body');
    if (!body || ACTIVE_SECTION !== 'image_generation' || ACTIVE_PAGE !== 'routing_overview') return;
    if (what) { body.className = 'rt-err'; body.textContent = irFmt(IR_TEXT.ovError, { what: what }); return; }
    body.className = '';
    body.innerHTML = irOverviewBody(data || {});
}

function irOverviewCharacter(name) {
    IR_OV_CHARACTER = name || '';
    renderImageRoutingOverview(document.getElementById('content'));
}

function irOverviewRefresh() {
    IR_BACKENDS = null;
    renderImageRoutingPage('routing_overview');
}

function irOverviewBody(data) {
    let html = '';
    for (const o of (data.occasions || [])) {
        html += '<div class="rt-card" style="margin-bottom:4px;">';
        html += '<div style="font-size:12px; color:#58a6ff; font-weight:600;">' + esc(o.label) + ' ' + irMediaBadge(o)
             + ' <span class="rt-muted" style="font-weight:400;">— ' + esc(o.id) + '</span></div>';
        let status;
        if (o.via === 'none') status = '<span class="rt-warn">' + esc(IR_TEXT.ovNone) + '</span>';
        else status = '<span class="' + (o.via === 'cheapest' ? 'rt-muted' : 'rt-ok') + '">' + esc(IR_TEXT.ovResolved) + ' '
                    + esc(o.resolved || '') + (o.via === 'cheapest' ? ' (' + esc(IR_TEXT.ovCheapest) + ')' : '') + '</span>';
        html += '<div class="rt-chain-row">' + status + '</div>';
        if (o.reason) html += '<div class="desc rt-muted">' + esc(o.reason) + '</div>';
        for (const row of (o.chain || [])) {
            const cls = row.status === 'ok' ? 'rt-ok' : (row.status === 'wrong_kind' || row.status === 'no_match' ? 'rt-err' : 'rt-warn');
            const pos = row.position === 0 ? IR_TEXT.ovCharPos : String(row.position);
            html += '<div class="rt-chain-row">'
                 + '<span class="rt-muted" style="min-width:20px;">' + esc(pos) + '.</span>'
                 + '<span>' + esc(row.spec) + '</span>'
                 + '<span class="' + cls + '">' + esc(row.status_text || row.status) + '</span>'
                 + (row.backend ? '<span class="rt-muted">→ ' + esc(row.backend) + '</span>' : '')
                 + '</div>';
        }
        html += '</div>';
    }
    return html;
}
