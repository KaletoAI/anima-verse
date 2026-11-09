/* Roleplay tab of /admin/models — setup, result table and report of the RP test.
 * Loaded after models.js and uses its globals: esc/escJs (HTML + inline-JS
 * escaping, the one escaper of that page), allModels, suitEntries, loadData,
 * suitJobsRefresh, modelsTab and ModelCombobox. Backend: app/core/rp_test.py,
 * routes /admin/settings/llm-rp-test/*.
 */
let rpSortField = 'overall';
let rpSortDir = -1;
let rpCur = '';
let rpPollTimer = null;
let rpCombobox = null;
let rpJudgeCombobox = null;
let rpDeleteArmed = false;
let rpLastStatus = '';
let rpEntriesShown = -1;
let rpPrompts = {job: '', prompts: null};  // the case prompts are fetched once per report

const RP_DIMENSIONS = [
    ['repetition', 'Repetition', 'Loops, copied replies and the same reply shape turn after turn — measured with the game\'s own repetition rule.'],
    ['prose', 'Prose', 'Concrete sensory detail, playing the moment out instead of summarising it, a voice of its own.'],
    ['character', 'Character', 'Stays the character: personality, speech, a cat that does not talk.'],
    ['logic', 'Logic', 'Absent people stay absent, night stays night, a hot cup stays in the hand, facts from the history hold.'],
    ['discipline', 'Discipline', 'No tool syntax, leaked reasoning or speaker labels, the mood marker, the right language, never speaks for the player, length follows the moment.'],
];
const RP_FLAGS = {
    tool_syntax: 'tool syntax', thinking_leak: 'reasoning leak', name_prefix: 'speaker label',
    image_markdown: 'image markdown', truncated: 'cut off', mood_marker: 'mood marker', language: 'language',
    salad: 'token salad', refusal: 'refusal', empty: 'empty', cat_speech: 'cat speaks',
};

function rpLevel(score) {
    if (score == null) return 'none';
    return score >= 80 ? 'good' : score >= 55 ? 'mid' : 'bad';
}
function rpNum(value, digits = 0) {
    return value == null || Number.isNaN(Number(value)) ? '—' : Number(value).toFixed(digits);
}
function rpVerdictClass(verdict) {
    const v = String(verdict || '');
    if (v === 'yes') return 'good';
    if (v === 'borderline') return 'mid';
    if (v.startsWith('incomplete')) return 'none';
    return v ? 'bad' : 'none';
}
function rpVerdictText(verdict) {
    const v = String(verdict || '');
    if (v === 'yes') return 'Suited';
    if (v === 'borderline') return 'Borderline';
    if (v.startsWith('no — ')) return 'Not suited · ' + v.slice(5);
    if (v.startsWith('incomplete')) return 'Incomplete';
    return v || '—';
}
function rpRing(score, size = 'small') {
    const value = score == null ? 0 : Math.max(0, Math.min(100, Number(score)));
    return '<span class="rp-ring rp-ring-' + size + ' lvl-' + rpLevel(score) + '" style="--v:' + value + '">'
        + '<span>' + esc(rpNum(score)) + '</span></span>';
}
function rpBar(score) {
    const value = score == null ? 0 : Math.max(0, Math.min(100, Number(score)));
    return '<span class="rp-mini" title="' + esc(score == null ? 'not judged' : rpNum(score, 1)) + '">'
        + '<span class="rp-mini-track"><span class="rp-mini-fill lvl-' + rpLevel(score) + '" style="width:' + value + '%"></span></span>'
        + '<b>' + esc(rpNum(score)) + '</b></span>';
}
function rpSettingsText(settings) {
    if (!settings) return '';
    const judge = settings.judge ? 'judge ' + settings.judge.provider + '::' + settings.judge.model : '';
    if (settings.temperature === undefined) return judge ? 'Re-judge · ' + judge : '';
    return ['temp ' + rpNum(settings.temperature, 2),
        settings.top_p != null ? 'top_p ' + settings.top_p : '',
        settings.repetition_penalty != null ? 'penalty ' + settings.repetition_penalty : '',
        'max ' + (settings.max_tokens || 'provider default'),
        settings.thinking_budget ? 'thinking ' + settings.thinking_budget : 'thinking off',
        judge].filter(Boolean).join(' · ');
}

// ── Setup ──
async function rpInit() {
    // models.js may have loaded its data before this file arrived: draw what is there.
    rpRenderTable();
    document.getElementById('rpModelPicker').innerHTML = ModelCombobox.render({id: 'rpModel'});
    document.getElementById('rpJudgeModelPicker').innerHTML = ModelCombobox.render({id: 'rpJudgeModel', ariaLabel: 'Judge model'});
    rpCombobox = ModelCombobox.attach('rpModel', {loadModels: () => rpFetchModels('rpProvider'), onChange: () => {}});
    rpJudgeCombobox = ModelCombobox.attach('rpJudgeModel', {loadModels: () => rpFetchModels('rpJudgeProvider'), onChange: rpRememberJudge});
    try {
        const response = await fetch('/admin/settings/providers-list');
        const data = await response.json();
        const options = '<option value="">Provider…</option>' + (data.providers || []).map(p =>
            '<option value="' + esc(p) + '">' + esc(p) + ((data.disabled || []).includes(p) ? ' (disabled in game)' : '') + '</option>').join('');
        document.getElementById('rpProvider').innerHTML = options;
        document.getElementById('rpJudgeProvider').innerHTML = options;
    } catch (e) { /* the selects stay empty; the status line explains on start */ }
    try {
        const judge = JSON.parse(localStorage.getItem('rp-judge') || 'null');
        if (judge && judge.provider) {
            document.getElementById('rpJudgeProvider').value = judge.provider;
            document.getElementById('rpJudgeModel').value = judge.model || '';
        }
    } catch (e) { /* Storage may be unavailable. */ }
    rpCasesInfo();
}
function rpRememberJudge() {
    const judge = rpJudge();
    try { localStorage.setItem('rp-judge', JSON.stringify(judge)); } catch (e) { /* Storage may be unavailable. */ }
}
function rpJudge() {
    return {provider: document.getElementById('rpJudgeProvider').value,
        model: document.getElementById('rpJudgeModel').value.trim()};
}
async function rpFetchModels(selectId) {
    const provider = document.getElementById(selectId).value;
    if (!provider) return [];
    const response = await fetch('/admin/settings/providers/' + encodeURIComponent(provider) + '/models');
    if (!response.ok) throw new Error('HTTP ' + response.status);
    const data = await response.json();
    if (data.error && !(data.models || []).length) throw new Error(data.error);
    return data.models || [];
}
function rpLoadModels() {
    document.getElementById('rpModel').value = '';
    return rpCombobox.reload();
}
function rpLoadJudgeModels() {
    document.getElementById('rpJudgeModel').value = '';
    rpRememberJudge();
    return rpJudgeCombobox.reload();
}
async function rpCasesInfo() {
    const box = document.getElementById('rpCases');
    try {
        const response = await fetch('/admin/settings/llm-rp-test/cases');
        if (!response.ok) throw new Error('HTTP ' + response.status);
        const info = await response.json();
        box.innerHTML = '<span class="rp-cases-head">' + esc(info.total) + ' cases · ' + esc(info.replies) + ' replies per run · '
            + esc(info.anchors) + ' judge anchors</span>' + (info.cases || []).map(c =>
                '<span class="rp-chip" title="' + esc(c.focus.join(', ') + ' · ' + c.repeats + ' run(s)' + (c.turns > 1 ? ' × ' + c.turns + ' turns' : '')) + '">'
                + esc(c.label) + (c.repeats > 1 ? ' <small>×' + esc(c.repeats) + '</small>' : '') + '</span>').join('');
    } catch (e) { box.textContent = 'Could not load the RP test cases: ' + e.message; }
}
function rpRenderEntries() {
    const select = document.getElementById('rpPrefill');
    if (!select || rpEntriesShown === suitEntries.length) return;
    rpEntriesShown = suitEntries.length;
    select.innerHTML = '<option value="">Choose an entry…</option>' + suitEntries.map(e =>
        '<option value="' + esc(e.index) + '">' + esc(e.name + ' · ' + e.provider + '::' + e.model) + '</option>').join('');
}
function rpPrefill() {
    const chosen = suitEntries.find(e => String(e.index) === document.getElementById('rpPrefill').value);
    if (!chosen) return;
    const providerSelect = document.getElementById('rpProvider');
    providerSelect.value = chosen.provider;
    if (providerSelect.value !== chosen.provider) {
        document.getElementById('rpStatus').textContent = 'Provider ' + chosen.provider + ' no longer exists — values copied, pick another provider.';
    }
    document.getElementById('rpModel').value = chosen.model;
    rpCombobox.reload();
    if (typeof chosen.temperature === 'number') document.getElementById('rpTemp').value = chosen.temperature;
    document.getElementById('rpPenalty').value = chosen.repetition_penalty ?? '';
    document.getElementById('rpMaxTokens').value = chosen.max_tokens || 0;  // no cap stays no cap
    document.getElementById('rpChatTemplate').value = chosen.chat_template || '';
    const budget = chosen.thinking === 'on' && chosen.thinking_budget > 0 ? chosen.thinking_budget : 0;
    const select = document.getElementById('rpThinking');
    select.value = String([...select.options].map(o => Number(o.value)).find(v => v >= budget) ?? 3000);
    document.getElementById('rpExtraParams').value = JSON.stringify(chosen.extra_params || {}, null, 2);
    rpValidateExtra();
    document.getElementById('rpPrefill').value = '';
}
function rpValidateExtra() {
    const input = document.getElementById('rpExtraParams');
    const error = document.getElementById('rpExtraError');
    try {
        const value = input.value.trim() ? JSON.parse(input.value) : {};
        if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Enter a JSON object (not an array or scalar).');
        if (!suitFinite(value)) throw new Error('Request parameters must contain only finite numbers.');
        error.textContent = '';
        return value;
    } catch (e) {
        error.textContent = e instanceof SyntaxError ? 'Invalid JSON: ' + e.message : e.message;
        return null;
    }
}
function rpOptionalNumber(id) {
    const value = document.getElementById(id).value;
    return value === '' ? null : Number(value);
}
async function rpStart() {
    const status = document.getElementById('rpStatus');
    const provider = document.getElementById('rpProvider').value;
    const model = document.getElementById('rpModel').value.trim();
    const judge = rpJudge();
    if (!provider || !model) { status.textContent = 'Pick the model to test.'; return; }
    if (!judge.provider || !judge.model) { status.textContent = 'Pick a judge model.'; return; }
    if ((judge.provider + '::' + judge.model).toLowerCase() === (provider + '::' + model).toLowerCase()) {
        status.textContent = 'The judge must be a different model than the one under test.'; return;
    }
    const concurrency = Number(document.getElementById('rpConcurrency').value);
    if (!Number.isInteger(concurrency) || concurrency < 1) { status.textContent = 'Parallel requests must be a positive integer.'; return; }
    const extra = rpValidateExtra();
    if (extra === null) { status.textContent = 'Fix extra params before starting.'; return; }
    const settings = {
        temperature: Number(document.getElementById('rpTemp').value),
        top_p: rpOptionalNumber('rpTopP'),
        repetition_penalty: rpOptionalNumber('rpPenalty'),
        max_tokens: Number(document.getElementById('rpMaxTokens').value),
        chat_template: document.getElementById('rpChatTemplate').value,
        thinking_budget: Number(document.getElementById('rpThinking').value),
        extra_params: extra, judge,
    };
    rpRememberJudge();
    await rpSubmit({provider, model, settings, concurrency}, document.getElementById('rpStartBtn'), status);
}
async function rpSubmit(body, button, status) {
    button.disabled = true;
    status.textContent = 'Queueing…';
    try {
        const response = await fetch('/admin/settings/llm-rp-test/start', {
            method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'HTTP ' + response.status);
        status.textContent = body.rejudge ? 'Re-judge queued' : 'Roleplay test queued';
        rpSelectJob(data.job_id);
        suitJobsRefresh();
    } catch (e) {
        status.textContent = 'Error: ' + e.message;
    } finally {
        button.disabled = false;
    }
}
async function rpRejudge(model, button) {
    const judge = rpJudge();
    const status = document.getElementById('rpReportStatus');
    if (!judge.provider || !judge.model) { status.textContent = 'Pick a judge model in the setup above first.'; return; }
    const [provider, ...rest] = model.split('::');
    await rpSubmit({provider, model: rest.join('::'), settings: {judge}, rejudge: true}, button, status);
}
async function rpDelete(model, button) {
    if (!rpDeleteArmed) { rpDeleteArmed = true; rpRenderLast(); return; }
    button.disabled = true;
    try {
        const response = await fetch('/admin/settings/llm-rp-test/delete', {
            method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({model})});
        if (!response.ok) throw new Error('HTTP ' + response.status);
        rpDeleteArmed = false;
        rpClose();
        loadData();
    } catch (e) {
        document.getElementById('rpReportStatus').textContent = 'Could not delete: ' + e.message;
        button.disabled = false;
    }
}

// ── Result table ──
function rpSort(field) {
    if (rpSortField === field) rpSortDir = -rpSortDir;
    else { rpSortField = field; rpSortDir = ['provider', 'name'].includes(field) ? 1 : -1; }
    rpRenderTable();
}
function rpSortValue(m, field) {
    const r = m.rp_result || {};
    if (field === 'provider' || field === 'name') return String(m[field] || '').toLowerCase();
    if (field === 'overall') return r.overall ?? -1;
    if (field === 'words') return r.speed?.median_words ?? -1;
    if (field === 'latency') return r.speed?.median_latency_s ?? Infinity;
    if (field === 'date') return r.rejudged || r.date || '';
    return r.dimensions?.[field]?.score ?? -1;
}
function rpRenderTable() {
    rpRenderEntries();
    const body = document.getElementById('rpBody');
    if (!body) return;
    const search = document.getElementById('searchInput').value.toLowerCase();
    const provider = document.getElementById('filterProvider').value;
    const rows = allModels.filter(m => m.rp_result
        && (!search || m.name.toLowerCase().includes(search) || m.provider.toLowerCase().includes(search))
        && (!provider || m.provider === provider));
    rows.sort((a, b) => {
        const va = rpSortValue(a, rpSortField), vb = rpSortValue(b, rpSortField);
        const cmp = typeof va === 'number' && typeof vb === 'number' ? va - vb : String(va).localeCompare(String(vb));
        return cmp * rpSortDir;
    });
    document.querySelectorAll('[id^="rpArrow-"]').forEach(el => {
        el.textContent = el.id === 'rpArrow-' + rpSortField ? (rpSortDir > 0 ? '▲' : '▼') : '';
    });
    if (!rows.length) {
        body.innerHTML = '<tr><td colspan="13" class="rp-empty">No roleplay results yet — start a test above.</td></tr>';
        return;
    }
    body.innerHTML = rows.map(m => {
        const r = m.rp_result;
        const full = m.provider + '::' + m.name;
        const caps = Object.entries(r.caps || {}).filter(([, n]) => n).map(([k, n]) => k + ' ' + n).join(', ');
        return '<tr class="rp-row' + (rpCur === 'saved:' + full ? ' rp-row-active' : '') + '" tabindex="0" onclick="rpSelectJob(\'saved:' + escJs(full) + '\')"'
            + ' onkeydown="if(event.key===\'Enter\')rpSelectJob(\'saved:' + escJs(full) + '\')">'
            + '<td><span class="badge-provider">' + esc(m.provider) + '</span></td>'
            + '<td class="rp-model">' + esc(m.name) + (m.listed ? '' : ' <small class="info-text">(not listed)</small>') + '</td>'
            + '<td class="rp-overall">' + rpRing(r.overall) + ' <span class="rp-pill lvl-' + rpVerdictClass(r.verdict) + '">'
                + esc(rpVerdictText(r.verdict)) + '</span>' + (caps ? '<div class="rp-caps">' + esc(caps) + '</div>' : '') + '</td>'
            + RP_DIMENSIONS.map(([key]) => '<td>' + rpBar(r.dimensions?.[key]?.score) + '</td>').join('')
            + '<td>' + esc(rpNum(r.speed?.median_words)) + '</td>'
            + '<td>' + esc(r.speed?.median_latency_s != null ? rpNum(r.speed.median_latency_s, 1) + ' s' : '—') + '</td>'
            + '<td class="rp-judge-cell" title="' + esc(r.judge?.calibrated ? 'passed calibration' : 'failed calibration') + '">'
                + esc(r.judge?.model || '—') + (r.judge?.calibrated ? '' : ' <span class="rp-warn-dot">!</span>') + '</td>'
            + '<td class="rp-settings-cell">' + esc(rpSettingsText(r.settings)) + '</td>'
            + '<td>' + esc(r.date || '') + (r.rejudged ? '<div class="info-text">re-judged ' + esc(r.rejudged) + '</div>' : '') + '</td></tr>';
    }).join('');
}

// ── Report ──
function rpSelectJob(jobId) {
    rpCur = jobId;
    rpDeleteArmed = false;
    rpLastStatus = '';
    modelsTab('rp');
    const report = document.getElementById('rpReport');
    report.hidden = false;
    report.innerHTML = '<div class="rp-loading">Loading report…</div>';
    report.scrollIntoView({behavior: 'smooth', block: 'start'});
    rpRenderTable();
    rpPoll();
}
function rpClose() {
    rpCur = '';
    if (rpPollTimer) { clearTimeout(rpPollTimer); rpPollTimer = null; }
    document.getElementById('rpReport').hidden = true;
    rpRenderTable();
}
let rpLastJob = null;
function rpRenderLast() { if (rpLastJob) rpRenderReport(rpLastJob); }
async function rpPoll() {
    if (rpPollTimer) { clearTimeout(rpPollTimer); rpPollTimer = null; }
    const selected = rpCur;
    if (!selected) return;
    try {
        const havePrompts = rpPrompts.job === selected && rpPrompts.prompts;
        const response = await fetch('/admin/settings/llm-rp-test/status?job_id=' + encodeURIComponent(selected)
            + (havePrompts ? '&prompts=0' : ''));
        if (selected !== rpCur) return;
        if (response.status === 404) {
            document.getElementById('rpReport').innerHTML = '<div class="rp-loading">Result no longer available.</div>';
            return;
        }
        if (!response.ok) throw new Error('HTTP ' + response.status);
        const job = await response.json();
        if (selected !== rpCur) return;
        if (job.case_prompts) rpPrompts = {job: selected, prompts: job.case_prompts};
        else job.case_prompts = rpPrompts.prompts || {};
        rpLastJob = job;
        rpRenderReport(job);
        if (job.status === 'queued' || job.status === 'running') rpPollTimer = setTimeout(rpPoll, 2000);
        else if (job.status === 'done' && rpLastStatus && rpLastStatus !== 'done') loadData();
        rpLastStatus = job.status;
    } catch (e) {
        if (selected === rpCur) rpPollTimer = setTimeout(rpPoll, 3000);
    }
}
function rpHighlight(text, shingles) {
    // Mark the words that belong to a 4-gram the character already used —
    // same tokens as history_manager.repetition_shingles ([a-z0-9äöüß]+, lowercased).
    const source = String(text || '');
    if (!shingles || !shingles.length) return esc(source);
    const set = new Set(shingles);
    const lower = source.toLowerCase();
    const tokens = [];
    const re = /[a-z0-9äöüß]+/g;
    let match;
    while ((match = re.exec(lower))) tokens.push({start: match.index, end: match.index + match[0].length, word: match[0]});
    const marked = new Array(tokens.length).fill(false);
    for (let i = 0; i + 4 <= tokens.length; i++) {
        if (set.has(tokens.slice(i, i + 4).map(t => t.word).join(' '))) for (let k = i; k < i + 4; k++) marked[k] = true;
    }
    let out = '', pos = 0, open = false;
    tokens.forEach((token, k) => {
        const gap = esc(source.slice(pos, token.start));
        if (open && !marked[k]) { out += '</mark>' + gap; open = false; }
        else out += gap;
        if (marked[k] && !open) { out += '<mark>'; open = true; }
        out += esc(source.slice(token.start, token.end));
        pos = token.end;
    });
    if (open) out += '</mark>';
    return out + esc(source.slice(pos));
}
function rpFlagChips(reply) {
    const flags = reply.flags || {};
    const chips = Object.entries(RP_FLAGS).filter(([key]) => flags[key]).map(([, label]) => '<span class="rp-flag">' + esc(label) + '</span>');
    (reply.cliches || []).forEach(c => chips.push('<span class="rp-flag rp-flag-soft">„' + esc(c) + '“</span>'));
    const meta = [flags.words != null ? flags.words + ' words' : '', reply.duration_s ? rpNum(reply.duration_s, 1) + ' s' : '',
        reply.finish_reason && reply.finish_reason !== 'stop' ? 'finish: ' + reply.finish_reason : ''].filter(Boolean).join(' · ');
    return '<div class="rp-reply-meta">' + chips.join('') + '<span class="info-text">' + esc(meta) + '</span></div>';
}
function rpReplyBlock(reply, shingles, character) {
    if (reply.error) return '<div class="rp-bubble rp-bubble-char rp-bubble-error"><b>' + esc(character) + '</b><p>Request failed: ' + esc(reply.error) + '</p></div>';
    const raw = reply.content && reply.content.trim() !== (reply.clean || '').trim()
        ? '<details class="rp-raw"><summary>Raw output</summary><pre>' + esc(reply.content) + '</pre></details>' : '';
    return '<div class="rp-bubble rp-bubble-char"><b>' + esc(character) + '</b><p>' + (reply.clean ? rpHighlight(reply.clean, shingles) : '<i>(empty reply)</i>')
        + '</p>' + rpFlagChips(reply) + raw + '</div>';
}
function rpRunBlock(run, index, prompt, caseInfo) {
    const replies = run.replies || [];
    let valid = 0;
    const body = replies.map(reply => {
        const shingles = !reply.error && run.repetition ? (run.repetition[valid] || {}).reused_shingles : null;
        if (!reply.error) valid += 1;
        return '<div class="rp-bubble rp-bubble-player"><b>' + esc(prompt.player || 'Player') + '</b><p>' + esc(reply.player_line || '') + '</p></div>'
            + rpReplyBlock(reply, shingles, prompt.character || caseInfo.label);
    }).join('');
    const judge = run.judge || {};
    const answers = Object.entries(judge.answers || {});
    const checks = Object.fromEntries((prompt.checks || []).map(c => [c.id, c]));
    const judged = answers.length ? '<ul class="rp-why">' + answers.map(([qid, a]) => {
        const check = checks[qid] || {};
        const ok = !check.expect || a.answer === check.expect;
        return '<li class="' + (ok ? 'ok' : 'fail') + '"><span>' + (ok ? '✓' : '✗') + '</span> <b>' + esc(check.question || qid) + '</b> — '
            + esc(a.answer) + (a.why ? ': ' + esc(a.why) : '') + '</li>';
    }).join('') + '</ul>' : (judge.error ? '<p class="rp-note">Judge: ' + esc(judge.error) + '</p>' : '');
    return '<div class="rp-run"><div class="rp-run-head">Run ' + (index + 1) + (run.aborted ? ' <span class="rp-flag">stopped early</span>' : '') + '</div>'
        + '<div class="rp-chat">' + body + '</div>' + judged + '</div>';
}
function rpCaseCard(caseInfo, runs, prompt) {
    const checks = Object.entries(caseInfo.checks || {});
    const chips = checks.map(([qid, c]) => {
        const total = c.pass + c.fail;
        const state = !total ? 'none' : c.fail ? (c.fail * 2 >= total ? 'bad' : 'mid') : 'good';
        const question = (prompt.checks || []).find(q => q.id === qid)?.question || qid;
        return '<span class="rp-check lvl-' + state + '" title="' + esc(question) + '">' + (state === 'good' ? '✓' : state === 'none' ? '?' : '✗') + ' '
            + esc(qid.replace(/_/g, ' ')) + ' <small>' + (total ? esc(c.pass) + '/' + esc(total) : 'not judged') + '</small></span>';
    }).join('');
    const failing = checks.some(([, c]) => c.fail) || caseInfo.errors || caseInfo.aborted_runs;
    const promptBlock = prompt.system ? '<details class="rp-prompt"><summary>Prompt sent to the model</summary>'
        + '<h4>Facts for the judge</h4><ul>' + (prompt.facts || []).map(f => '<li>' + esc(f) + '</li>').join('') + '</ul>'
        + '<h4>System prompt</h4><pre>' + esc(prompt.system) + '</pre>'
        + (prompt.messages || []).map(m => '<h4>' + esc(m.role) + '</h4><pre>' + esc(m.content) + '</pre>').join('') + '</details>' : '';
    return '<details class="rp-case' + (failing ? ' rp-case-failing' : '') + '"' + (failing ? ' open' : '') + '>'
        + '<summary><span class="rp-case-title">' + esc(caseInfo.label) + '</span>'
        + (caseInfo.focus || []).map(f => '<span class="rp-focus">' + esc(f) + '</span>').join('')
        + (caseInfo.repetition != null ? '<span class="rp-case-score">repetition ' + rpBar(caseInfo.repetition) + '</span>' : '')
        + '<span class="rp-case-checks">' + chips + '</span></summary>'
        + (runs || []).map((run, i) => rpRunBlock(run, i, prompt, caseInfo)).join('') + promptBlock + '</details>';
}
function rpHero(job, s) {
    const calibration = s.judge?.calibration || {};
    const saved = String(job.job_id || '').startsWith('saved:') || s.saved;
    const model = job.model || s.model;
    const actions = saved ? '<div class="rp-actions">'
        + (job.fixture_matches ? '<button type="button" class="btn" onclick="rpRejudge(\'' + escJs(model) + '\',this)" title="Judge the stored answers again with the judge selected in the setup">Re-judge</button>' : '')
        + (rpDeleteArmed
            ? '<span>Delete this roleplay result?</span> <button type="button" class="btn btn-danger" onclick="rpDelete(\'' + escJs(model) + '\',this)">Delete</button>'
                + ' <button type="button" class="btn" onclick="rpDeleteArmed=false;rpRenderLast()">Cancel</button>'
            : '<button type="button" class="btn" onclick="rpDelete(\'' + escJs(model) + '\',this)">Delete result</button>')
        + '</div>' : '';
    return '<div class="rp-hero">' + rpRing(s.overall, 'big')
        + '<div class="rp-hero-text"><div class="rp-pill rp-pill-big lvl-' + rpVerdictClass(s.verdict) + '">' + esc(rpVerdictText(s.verdict)) + '</div>'
        + '<div class="rp-hero-meta">Judge <b>' + esc((s.judge?.provider || '') + '::' + (s.judge?.model || '')) + '</b> · calibration '
        + esc(calibration.passed ?? '—') + '/' + esc(calibration.total ?? '—') + (calibration.ok ? ' ✓' : ' ✗')
        + ' · ' + esc(s.replies || 0) + ' replies · tested ' + esc(s.date || '') + (s.rejudged ? ' · re-judged ' + esc(s.rejudged) : '') + '</div>'
        + '<div class="rp-hero-meta">' + esc(rpSettingsText(s.settings)) + '</div>' + actions + '</div></div>';
}
function rpDimensions(s) {
    return '<div class="rp-dims">' + RP_DIMENSIONS.map(([key, label, description]) => {
        const d = (s.dimensions || {})[key] || {};
        const value = d.score == null ? 0 : d.score;
        const parts = key === 'repetition' && d.code != null ? 'code ' + rpNum(d.code) + (d.judge != null ? ' · judge ' + rpNum(d.judge) : '')
            : d.n ? 'judge ' + d.n : '';
        return '<div class="rp-dim"><div class="rp-dim-head"><b>' + esc(label) + '</b><span class="rp-dim-score lvl-' + rpLevel(d.score) + '">'
            + esc(d.score == null ? 'not judged' : rpNum(d.score)) + '</span></div>'
            + '<div class="rp-dim-track"><span class="rp-dim-fill lvl-' + rpLevel(d.score) + '" style="width:' + value + '%"></span>'
            + '<span class="rp-dim-mark" style="left:55%" title="minimum 55"></span></div>'
            + '<div class="info-text">' + esc(description) + (parts ? ' <span class="rp-dim-parts">' + esc(parts) + '</span>' : '') + '</div></div>';
    }).join('') + '</div>';
}
function rpTiles(s) {
    const length = s.length || {}, speed = s.speed || {}, caps = s.caps || {};
    const tiles = [
        ['Short moments', rpNum(length.brief_median), 'median words'],
        ['Long moments', rpNum(length.long_median), 'median words'],
        ['Length ratio', length.ratio != null ? Math.round(length.ratio * 100) + ' %' : '—', 'short ÷ long, ≤ 60 % is good'],
        ['Latency', speed.median_latency_s != null ? rpNum(speed.median_latency_s, 1) + ' s' : '—', 'median per reply'],
        ['Speed', speed.tok_s != null ? rpNum(speed.tok_s, 1) : '—', 'tokens / s'],
        ['Refusals', caps.refusal || 0, 'hard limit'],
    ];
    return '<div class="rp-tiles">' + tiles.map(([label, value, hint]) => '<div class="rp-tile"><span>' + esc(label) + '</span><b>' + esc(value)
        + '</b><small>' + esc(hint) + '</small></div>').join('') + '</div>';
}
function rpFindings(s) {
    const findings = s.findings || [];
    if (!findings.length) return '';
    const icon = {bad: '✗', warn: '!', good: '✓'};
    const order = {bad: 0, warn: 1, good: 2};
    return '<h3>Findings</h3><ul class="rp-findings">' + findings.slice().sort((a, b) => order[a.severity] - order[b.severity]).map(f =>
        '<li class="rp-finding-' + esc(f.severity) + '"><span>' + esc(icon[f.severity] || '·') + '</span>' + esc(f.text) + '</li>').join('') + '</ul>';
}
function rpHistory(job) {
    const history = (job.history || []).slice().reverse();
    if (!history.length) return '';
    return '<details class="rp-history"><summary>Earlier runs (' + history.length + ')</summary><table><thead><tr><th>Date</th><th>Overall</th><th>Verdict</th><th>Judge</th><th>Settings</th></tr></thead><tbody>'
        + history.map(h => '<tr><td>' + esc(h.date || '') + (h.rejudged ? ' <small>(re-judged ' + esc(h.rejudged) + ')</small>' : '') + '</td><td>' + rpRing(h.overall)
            + '</td><td><span class="rp-pill lvl-' + rpVerdictClass(h.verdict) + '">' + esc(rpVerdictText(h.verdict)) + '</span></td><td>'
            + esc(h.judge ? h.judge.model : '') + '</td><td class="rp-settings-cell">' + esc(rpSettingsText(h.settings)) + '</td></tr>').join('')
        + '</tbody></table></details>';
}
function rpRenderReport(job) {
    const report = document.getElementById('rpReport');
    const model = job.model || '';
    const head = '<div class="rp-report-head"><h2>' + esc(model) + ' <span class="kind-badge kind-' + esc(job.kind || 'rp') + '">'
        + esc(suitKindLabel(job.kind || 'rp')) + '</span></h2><button type="button" class="btn" onclick="rpClose()" aria-label="Close report">✕</button></div>'
        + '<div id="rpReportStatus" role="status" class="rp-report-status"></div>';
    const prompts = job.case_prompts || {};
    if (job.status === 'queued' || job.status === 'running' || job.status === 'interrupted') {
        const total = job.total || 0, done = job.done || 0;
        const pct = total ? Math.round(100 * Math.min(done, total) / total) : 0;
        report.innerHTML = head + '<div class="rp-progress"><div class="rp-progress-text">' + esc(job.status === 'queued' ? 'Waiting in the queue (position ' + (job.position || '?') + ')'
            : job.status === 'interrupted' ? 'Interrupted by a server restart — resume it in the queue above' : (job.phase || 'Running…'))
            + (/^(judging|calibrating)/.test(job.phase || '') ? '' : ' · ' + esc(done) + '/' + esc(total || '?') + ' cases') + '</div>'
            + '<div class="rp-dim-track"><span class="rp-dim-fill lvl-good" style="width:' + pct + '%"></span></div></div>'
            + (job.checks || []).map(c => rpCaseCard({label: c.label, focus: c.focus, checks: {}}, c.runs, prompts[c.id] || {})).join('');
        return;
    }
    if (job.status === 'error' || job.status === 'cancelled') {
        report.innerHTML = head + '<div class="rp-banner rp-banner-bad">' + esc(job.status === 'cancelled' ? 'Cancelled.' : 'Test failed: ' + (job.error || 'unknown error')) + '</div>';
        return;
    }
    const s = job.summary || {};
    const notes = [];
    if (s.infra) notes.push('<div class="rp-banner rp-banner-bad">Not saved: a provider error interrupted the run, so the result says nothing about the model. The answers are kept for inspection.</div>');
    if (!job.fixture_matches) notes.push('<div class="rp-banner rp-banner-warn">The test cases changed since this run — re-judging is not possible, run the test again for comparable numbers.</div>');
    const answers = job.answers || {};
    report.innerHTML = head + rpHero(job, s) + notes.join('') + rpDimensions(s) + rpTiles(s) + rpFindings(s)
        + '<h3>Cases</h3><div class="rp-cases">' + (s.cases || []).map(c => rpCaseCard(c, answers[c.id] || [], prompts[c.id] || {})).join('') + '</div>'
        + rpHistory(job);
}

rpInit();
