// Decision models (development_instructions/plan-decision-models.md § 3.2).
// Endpoints = the generic paged-section page plus a test panel; Points and
// Shadow results are built here. Loaded after settings.js on /admin/settings
// and uses its esc(), sJs(), toast(), authHeaders(), renderPagedSection(),
// CONFIG, SCHEMA and ACTIVE_PAGE — no escaper of its own.

let DC_POINTS = [];

async function renderDecisionPage(pageId) {
    const page = pageId || 'endpoints';
    ACTIVE_PAGE = page;
    if (page === 'points') return renderDecisionPointsPage();
    if (page === 'shadow') return renderDecisionShadowPage(7);
    renderPagedSection('decision', 'endpoints');
    await appendDecisionTestPanel();
}

function dcSection() {
    if (!CONFIG.decision || typeof CONFIG.decision !== 'object') CONFIG.decision = {};
    return CONFIG.decision;
}

function dcPoints() {
    const s = dcSection();
    if (!s.points || typeof s.points !== 'object' || Array.isArray(s.points)) s.points = {};
    return s.points;
}

function dcPointCfg(id) {
    const p = dcPoints();
    if (!p[id] || typeof p[id] !== 'object') p[id] = {};
    return p[id];
}

function dcEndpointNames() {
    return (dcSection().endpoints || []).map(e => (e && e.name) || '').filter(Boolean);
}

function dcTitle(pageLabel, pageIcon) {
    const sec = SCHEMA.decision || {};
    return '<h1 class="section-title">' + esc(sec.icon || '') + ' ' + esc(sec.label || 'Decision models')
         + ' <span style="color:#8b949e;">›</span> ' + esc(pageIcon) + ' ' + esc(pageLabel) + '</h1>';
}

async function dcFetch(url, opts) {
    const r = await fetch(url, Object.assign({ headers: authHeaders() }, opts || {}));
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.detail || ('HTTP ' + r.status));
    return d;
}

// ── Endpoints: test panel ──────────────────────────────────────────────
async function appendDecisionTestPanel() {
    const section = document.querySelector('#content .section');
    if (!section) return;
    let status = {};
    try { status = (await dcFetch('/admin/settings/decision/points')).status || {}; } catch (e) { /* panel still usable */ }
    const names = dcEndpointNames();
    let html = '<div class="subsection" style="margin-top:18px;"><div class="subsection-title">Test</div>'
             + '<div class="desc">Sends one fixed probe question to a SAVED endpoint — save first. '
             + 'The first call after a pause also loads a cold llama-swap slot (10–20 s).</div>';
    if (!names.length) html += '<div class="desc">No endpoints yet.</div>';
    names.forEach((n, i) => {
        const st = status[n] || {};
        const blocked = st.blocked_for_s > 0
            ? ' <span style="color:#f85149;">blocked for ' + esc(st.blocked_for_s) + ' s after repeated failures</span>' : '';
        html += '<div style="display:flex;gap:10px;align-items:center;margin:6px 0;">'
              + '<code>' + esc(n) + '</code>' + blocked
              + '<button class="btn btn-sm" onclick="decisionTest(\'' + sJs(n) + '\', ' + i + ', this)">Test</button>'
              + '<span class="desc" id="dc-test-' + i + '"></span></div>';
    });
    html += '</div>';
    section.insertAdjacentHTML('beforeend', html);
}

async function decisionTest(name, idx, btn) {
    const out = document.getElementById('dc-test-' + idx);
    btn.disabled = true;
    if (out) out.textContent = 'Testing…';
    try {
        const d = await dcFetch('/admin/settings/decision/test', { method: 'POST', body: JSON.stringify({ name }) });
        if (out) out.textContent = d.ok
            ? ('OK — ' + d.duration_ms + ' ms, answer "' + d.answer.value + '" (confidence ' + Number(d.answer.confidence).toFixed(2) + ')')
            : ('Failed — ' + (d.error || 'unknown') + ' after ' + d.duration_ms + ' ms');
    } catch (e) {
        if (out) out.textContent = 'Failed — ' + e.message;
    }
    btn.disabled = false;
}

// ── Points ──────────────────────────────────────────────────────────────
async function renderDecisionPointsPage() {
    const content = document.getElementById('content');
    content.innerHTML = '<div class="section active">' + dcTitle('Points', '🎯') + '<div class="desc" id="dc-msg">Loading…</div></div>';
    try {
        DC_POINTS = (await dcFetch('/admin/settings/decision/points')).points || [];
    } catch (e) {
        document.getElementById('dc-msg').textContent = 'Could not load the points: ' + e.message;
        return;
    }
    dcRenderPoints();
}

function dcRenderPoints() {
    const names = dcEndpointNames();
    let html = '<div class="section active">' + dcTitle('Points', '🎯')
             + '<div class="desc" style="margin-bottom:14px;">Mode <b>off</b>: nothing is asked. '
             + '<b>shadow</b>: every listed endpoint is asked in the background and only recorded — the game does not change. '
             + '<b>on</b>: the FIRST endpoint decides when its answer reaches the minimum confidence; otherwise the usual path runs. '
             + 'Press <b>Save</b> — no restart needed.</div>';
    if (!dcSection().enabled) html += '<div class="desc" style="color:#d29922;margin-bottom:10px;">The master switch (Endpoints page) is off — no point runs.</div>';
    html += '<table class="data-table" style="width:100%;"><thead><tr><th>Point</th><th>Mode</th><th>Endpoints (first decides)</th><th>Min confidence</th><th>Timeout (s)</th></tr></thead><tbody>';
    for (const p of DC_POINTS) {
        const c = dcPoints()[p.id] || {};
        const mode = c.mode || 'off';
        const eps = Array.isArray(c.endpoints) ? c.endpoints : [];
        const origin = p.registered ? (p.origin === 'core' ? 'core' : 'plugin: ' + p.origin) : 'not loaded';
        html += '<tr' + (p.registered ? '' : ' style="opacity:.55;"') + '><td><b>' + esc(p.label) + '</b> <code>' + esc(p.id) + '</code>'
              + '<div class="desc">' + esc(p.description) + '</div><div class="desc">' + esc(origin) + '</div></td>';
        html += '<td><select onchange="dcSet(\'' + sJs(p.id) + '\', \'mode\', this.value)">'
              + ['off', 'shadow', 'on'].map(m => '<option value="' + m + '"' + (m === mode ? ' selected' : '') + '>' + m + '</option>').join('')
              + '</select></td>';
        html += '<td>';
        eps.forEach((n, i) => {
            const missing = names.indexOf(n) === -1 ? ' <span style="color:#f85149;">(no such endpoint)</span>' : '';
            html += '<div style="display:flex;gap:6px;align-items:center;margin:2px 0;"><code>' + esc(n) + '</code>' + missing
                  + (i > 0 ? '<button class="btn btn-sm" title="Move up" onclick="dcMoveUp(\'' + sJs(p.id) + '\', ' + i + ')">↑</button>' : '')
                  + '<button class="btn btn-sm" title="Remove" onclick="dcRemoveEp(\'' + sJs(p.id) + '\', ' + i + ')">×</button></div>';
        });
        const addable = names.filter(n => eps.indexOf(n) === -1);
        if (addable.length) {
            html += '<select onchange="dcAddEp(\'' + sJs(p.id) + '\', this.value)"><option value="">+ add endpoint</option>'
                  + addable.map(n => '<option value="' + esc(n) + '">' + esc(n) + '</option>').join('') + '</select>';
        }
        html += '</td>';
        html += '<td><input type="number" min="0" max="1" step="0.05" style="width:80px;" value="' + esc(c.min_confidence !== undefined ? c.min_confidence : p.default_min_confidence)
              + '" onchange="dcSetNum(\'' + sJs(p.id) + '\', \'min_confidence\', this.value)"></td>';
        html += '<td><input type="number" min="0.1" max="60" step="0.5" style="width:80px;" value="' + esc(c.timeout_s !== undefined ? c.timeout_s : p.default_timeout_s)
              + '" onchange="dcSetNum(\'' + sJs(p.id) + '\', \'timeout_s\', this.value)"></td></tr>';
    }
    html += '</tbody></table></div>';
    document.getElementById('content').innerHTML = html;
}

function dcSet(id, field, value) { dcPointCfg(id)[field] = value; }

function dcSetNum(id, field, value) {
    const n = parseFloat(value);
    if (!isNaN(n)) dcPointCfg(id)[field] = n;
}

function dcAddEp(id, name) {
    if (!name) return;
    const c = dcPointCfg(id);
    c.endpoints = (Array.isArray(c.endpoints) ? c.endpoints : []).filter(x => x !== name);
    c.endpoints.push(name);
    dcRenderPoints();
}

function dcRemoveEp(id, i) {
    const c = dcPointCfg(id);
    if (Array.isArray(c.endpoints)) c.endpoints.splice(i, 1);
    dcRenderPoints();
}

function dcMoveUp(id, i) {
    const a = dcPointCfg(id).endpoints || [];
    if (i > 0 && i < a.length) { const t = a[i - 1]; a[i - 1] = a[i]; a[i] = t; }
    dcRenderPoints();
}

// ── Shadow results ──────────────────────────────────────────────────────
async function renderDecisionShadowPage(days) {
    const content = document.getElementById('content');
    content.innerHTML = '<div class="section active">' + dcTitle('Shadow results', '📊') + '<div class="desc" id="dc-msg">Loading…</div></div>';
    let data;
    try {
        data = await dcFetch('/admin/settings/decision/stats?days=' + encodeURIComponent(days));
    } catch (e) {
        document.getElementById('dc-msg').textContent = 'Could not load the statistics: ' + e.message;
        return;
    }
    const pct = (a, b) => (b > 0 ? Math.round(100 * a / b) + ' %' : '—');
    let html = '<div class="section active">' + dcTitle('Shadow results', '📊')
             + '<div class="desc" style="margin-bottom:10px;">Last <select onchange="renderDecisionShadowPage(this.value)">'
             + [1, 7, 30, 90].map(d => '<option value="' + d + '"' + (Number(d) === Number(data.days) ? ' selected' : '') + '>' + d + ' day' + (d > 1 ? 's' : '') + '</option>').join('')
             + '</select> (system days). <b>Agreement</b> counts CONFIDENT answers only — the ones that would act in mode on. '
             + '<b>Unsure</b> = answers below the minimum confidence. <b>No outcome</b> = the usual path never reported back; '
             + '<b>taken</b> = mode on acted, nothing to compare.</div>';
    const rows = data.rows || [];
    if (!rows.length) {
        html += '<div class="desc">No decisions recorded in this period.</div></div>';
        content.innerHTML = html;
        return;
    }
    html += '<table class="data-table" style="width:100%;"><thead><tr><th>Point</th><th>Endpoint</th><th>Question</th>'
          + '<th>Calls</th><th>Errors</th><th>p50</th><th>p95</th><th>No outcome</th><th>Taken</th>'
          + '<th>Answers</th><th>Unsure</th><th>Agreement</th></tr></thead><tbody>';
    for (const r of rows) {
        const call = r.question === '';
        const errs = Object.entries(r.errors || {}).map(([k, v]) => esc(k) + ' ' + esc(v)).join(', ') || '—';
        const judged = (r.agree || 0) + (r.disagree || 0);
        html += '<tr><td><code>' + esc(r.point) + '</code></td><td><code>' + esc(r.endpoint) + '</code></td>'
              + '<td>' + (call ? '<i>calls</i>' : '<code>' + esc(r.question) + '</code>') + '</td>'
              + '<td>' + (call ? esc(r.calls) : '') + '</td><td>' + (call ? errs : '') + '</td>'
              + '<td>' + (call ? esc(r.p50 || '—') : '') + '</td><td>' + (call ? esc(r.p95 || '—') : '') + '</td>'
              + '<td>' + (call ? esc(r.no_outcome) : '') + '</td><td>' + (call ? esc(r.taken) : '') + '</td>'
              + '<td>' + (call ? '' : esc(r.answers)) + '</td>'
              + '<td>' + (call ? '' : pct(r.low_conf || 0, r.answers || 0)) + '</td>'
              + '<td>' + (call ? '' : pct(r.agree || 0, judged) + ' <span class="desc">(' + esc(judged) + ')</span>') + '</td></tr>';
    }
    html += '</tbody></table></div>';
    content.innerHTML = html;
}
