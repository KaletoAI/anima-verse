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
// the order in the list is the position (1..n). Saved with the Save button.

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

function irNormalize(routing, knownIds) {
    const unknown = [];
    for (const occ of Object.keys(routing || {})) {
        if (!knownIds.has(occ)) { unknown.push(occ); continue; }
        const out = [];
        for (const raw of irChain(routing, occ)) {
            const s = irNormSpec(raw);
            if (s && !_irHas(out, s, -1)) out.push(s);
        }
        if (out.length) routing[occ] = out; else delete routing[occ];
    }
    return { unknown: unknown };
}
// <<< harness-extract:imageRoutingModel
