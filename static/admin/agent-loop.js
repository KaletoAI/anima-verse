
let _state = null;
let _lanes = null;

let _loadCounter = 0;

async function load() {
  _loadCounter++;
  const lbl = document.getElementById('status-label');
  if (lbl && lbl.textContent === 'loading…') {
    lbl.textContent = 'fetching… (#' + _loadCounter + ')';
  }
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 8000);
  try {
    const r = await fetch('/admin/agent-loop/status', {
      signal: ctrl.signal,
      cache: 'no-store',
      credentials: 'same-origin',
    });
    clearTimeout(timer);
    if (!r.ok) {
      let body = '';
      try { body = (await r.text()).slice(0, 200); } catch(_) {}
      if (lbl) lbl.textContent = 'HTTP ' + r.status + (body ? ' — ' + body : '');
      return;
    }
    _state = await r.json();
    render();
    // The lane table is its own endpoint: the AgentLoop status must keep
    // rendering even when the lane view fails, and vice versa.
    await loadLanes();
  } catch(e) {
    clearTimeout(timer);
    if (lbl) lbl.textContent = (e.name === 'AbortError')
      ? "timeout — server didn't respond in 8s (call #" + _loadCounter + ")"
      : "error: " + e.message + " (call #" + _loadCounter + ")";
    console.error('[agent-loop load failed]', e);
  }
}

// Verify the script runs at all — if 'loading…' has not been replaced
// after 1s, there was a pre-init error.
setTimeout(() => {
  const lbl = document.getElementById('status-label');
  if (lbl && lbl.textContent === 'loading…') {
    lbl.textContent = 'JS ran but fetch never started (check console)';
  }
}, 1500);

function render() {
  const s = _state || {};
  const btn = document.getElementById('btn-pause');
  const lbl = document.getElementById('status-label');
  if (s.paused) {
    btn.textContent = 'Resume';
    btn.classList.add('paused');
    lbl.textContent = 'PAUSED — Loop is sleeping. Persistent across restarts.';
  } else if (s.standby) {
    btn.textContent = 'Pause';
    btn.classList.remove('paused');
    lbl.textContent = "STANDBY — no 'thought' LLM reachable. Loop polls every 30s.";
  } else if (s.running) {
    btn.textContent = 'Pause';
    btn.classList.remove('paused');
    lbl.textContent = 'Running.';
  } else {
    btn.textContent = 'Pause';
    btn.classList.remove('paused');
    lbl.textContent = 'Loop not started.';
  }
  document.getElementById('current').textContent = s.current_agent || '(idle)';
  // Respond lane: runs parallel to the serial round-robin (own asyncio tasks,
  // no turn gap). Fields arrive from AgentLoop.status(); read defensively.
  const act = s.respond_active || [];
  const rq = s.respond_queue || [];
  document.getElementById('respond').textContent =
    (act.length ? '▶ ' + act.join(', ') : '(idle)')
    + (rq.length ? '  |  waiting: ' + rq.join(' → ') : '');
  // Why each queued answer did not start on the dispatcher's last look. The
  // reason is recorded by the dispatcher itself (AgentLoop.status ->
  // respond_waiting); nothing is guessed here. This is the AgentLoop's own
  // queue — the lane manager's waiting calls are a different list and live in
  // the lane table below.
  const rw = s.respond_waiting || {};
  const rwEl = document.getElementById('respond-waiting');
  if (rwEl) {
    const names = rq.filter(n => rw[n]);
    rwEl.innerHTML = names.length
      ? names.map(n => '<div class="wait-row"><span class="wait-name">'
          + escapeHtml(n) + '</span><span class="wait-reason">'
          + escapeHtml(respondReasonText(rw[n])) + '</span></div>').join('')
      : '';
  }
  const bumped = s.bumped || [];
  document.getElementById('bumped').textContent = bumped.length ? bumped.join(' → ') : '(none)';
  const round = s.remaining_in_round || [];
  document.getElementById('round').textContent = round.length ? round.join(' → ') : '(round empty — refilling on next pick)';
  const tbody = document.querySelector('#recent-table tbody');
  tbody.innerHTML = '';
  for (const r of (s.recent || []).slice().reverse()) {
    const tr = document.createElement('tr');
    let cls = 'outcome-ok';
    if (r.outcome && r.outcome.startsWith('error')) cls = 'outcome-err';
    else if (r.outcome === 'timeout' || r.outcome === 'no_llm') cls = 'outcome-timeout';
    else if (r.outcome === 'in_chat_skip') cls = 'outcome-skip';
    const tools = (r.tools || []).map(t => `<span class="tag tool">${escapeHtml(t)}</span>`).join('');
    const intents = (r.intents || []).map(i => `<span class="tag intent">${escapeHtml(i)}</span>`).join('');
    const tagsCell = (tools + intents) || '<span class="muted">—</span>';
    // Link to the LLM log: only for outcomes where an LLM call actually ran.
    // Auto-sleep / in_chat_skip / no_llm have no entry in the LLM log.
    const _llmRanOutcomes = !(
      (r.outcome || '').startsWith('auto_sleep') ||
      r.outcome === 'in_chat_skip' || r.outcome === 'no_llm'
    );
    let logLink = '';
    if (_llmRanOutcomes && r.agent && r.started_at) {
      // Search filter: ISO format with "T" + minute of the turn start (matches
      // the raw format in llm_calls.jsonl 'starttime'). Example:
      // "2026-05-05T13:35". The LLM log viewer reads the URL params, applies
      // the filters and auto-expands the first match.
      const tsMin = (r.started_at || '').slice(0, 16);
      const url = '/logs/llm?character=' + encodeURIComponent(r.agent)
                + '&search=' + encodeURIComponent(tsMin);
      // The URL travels in a data- attribute and the click is wired up with
      // addEventListener below, NOT in an inline onclick: the agent name is
      // part of the URL and encodeURIComponent deliberately leaves `'` alone,
      // so an inline handler would let a name like `x'-alert(1)-'x` close the
      // JS string literal inside the attribute.
      logLink = ` <a href="${escapeHtml(url)}" class="log-link" data-log-url="${escapeHtml(url)}" title="Open in LLM log" style="margin-left:6px;text-decoration:none;color:#58a6ff;">🔍</a>`;
    }
    // Multi-line preview: untruncated RP answer + Tool-LLM answer when the
    // turn captured them; otherwise fall back to the short preview string.
    const rp = (r.rp_response || '').trim();
    const tool = (r.tool_response || '').trim();
    let preview;
    if (rp || tool) {
      const blocks = [];
      if (rp) blocks.push(`<div class="pv-block"><span class="pv-label rp">RP</span><div class="pv-text">${escapeHtml(rp)}</div></div>`);
      if (tool) blocks.push(`<div class="pv-block"><span class="pv-label tool">Tool</span><div class="pv-text">${escapeHtml(tool)}</div></div>`);
      preview = blocks.join('') + logLink;
    } else {
      preview = r.preview
        ? `<span class="preview">${escapeHtml(r.preview)}</span>${logLink}`
        : (logLink ? `<span class="muted">—</span>${logLink}` : '<span class="muted">—</span>');
    }
    let startedShort = '';
    if (r.started_at) {
      // Seconds now follow the configured format (24h_seconds / 12h_seconds)
      // instead of always showing — one setting, one shape on every page.
      startedShort = AdminClock.stamp(r.started_at, {month: '2-digit', day: '2-digit'})
        || r.started_at.replace('T', ' ').split('.')[0];
    }
    tr.innerHTML = `<td>${escapeHtml(r.agent)}</td><td>${escapeHtml(startedShort)}</td><td>${escapeHtml(r.duration_s)}s</td><td class="${cls}">${escapeHtml(r.outcome)}</td><td>${tagsCell}</td><td>${preview}</td>`;
    // Try the admin sidebar navigation (parent.activateIframe) first — then
    // only the iframe content is swapped inside the admin layout and the
    // sidebar links stay intact. Fallback: direct navigation (e.g. when the
    // agent-loop page was opened standalone).
    for (const a of tr.querySelectorAll('a.log-link')) {
      a.addEventListener('click', (ev) => {
        ev.preventDefault();
        const target = a.dataset.logUrl || '';
        try {
          if (window.parent && window.parent.activateIframe) {
            window.parent.activateIframe('_llm_log', target, 'LLM Log');
            return;
          }
        } catch (e) { /* cross-origin parent: fall through to navigation */ }
        window.location = target;
      });
    }
    tbody.appendChild(tr);
  }
}

// ── Cache lanes (plan-cache-lanes.md § 6, item 10) ─────────────────────────

// Why a queued ANSWER does not run — the dispatcher's own vocabulary
// (agent_loop._respond_wait_reason). An unknown code is printed as it came,
// never replaced by a plausible sentence.
function respondReasonText(code) {
  if (code === 'active') return 'already in a turn';
  if (code === 'no_lane') return 'its LLM entry has no free lane';
  return code || '';
}

// Why a call PARKED ON A POOL does not run — the lane manager's vocabulary
// (llm_lanes._waiter_view). Same rule: unknown codes are shown raw.
function laneReasonText(code) {
  if (code === 'all_busy') return 'every lane is busy';
  if (code === 'affinity_wait') return 'waiting briefly for its own lane (R3)';
  if (code === 'conversation_hold') return 'a conversation lane is protected (R4)';
  if (code === 'reserved') return 'a reply has reserved the pool — lower class waits';
  if (code === 'outranked') return 'another call goes first (R2)';
  if (code === 'starting') return 'has a lane — starting';
  return code || '';
}

function secs(v) { return (v === null || v === undefined) ? '' : (Math.round(v * 10) / 10) + 's'; }

async function loadLanes() {
  try {
    const r = await fetch('/admin/agent-loop/lanes', {
      cache: 'no-store', credentials: 'same-origin',
    });
    if (!r.ok) {
      document.getElementById('lanes').textContent = 'HTTP ' + r.status;
      return;
    }
    _lanes = await r.json();
    renderLanes();
  } catch(e) {
    document.getElementById('lanes').textContent = 'error: ' + e.message;
    console.error('[agent-loop lanes failed]', e);
  }
}

function renderLanes() {
  const el = document.getElementById('lanes');
  if (!el) return;
  const pools = (_lanes && _lanes.pools) || [];
  if (!pools.length) {
    el.innerHTML = '<span class="muted">(no LLM entry configured)</span>';
    return;
  }
  el.innerHTML = pools.map(renderPool).join('');
}

function renderPool(p) {
  // Lane counts: what the config allows and what exists right now. They differ
  // while a shrink waits for running calls — showing only one would hide that.
  const cfg = (p.configured_lanes === null || p.configured_lanes === undefined)
    ? '?' : p.configured_lanes;
  let counts;
  if (!p.started) {
    counts = cfg + (cfg === 1 ? ' lane' : ' lanes') + ' configured · not used yet';
  } else {
    counts = p.lane_count + (p.lane_count === 1 ? ' lane' : ' lanes')
      + ' · ' + p.free + ' free · ' + p.busy + ' busy';
    if (p.lane_count !== cfg) counts += ' · config ' + cfg;
  }
  let html = '<div class="pool">';
  html += '<div class="pool-head"><span class="pool-key">' + escapeHtml(p.pool_key) + '</span>'
    + '<span class="pool-counts">' + escapeHtml(counts) + '</span>'
    + '<span class="pool-cache">⚡ ' + escapeHtml((p.cache && p.cache.text) || '') + '</span>';
  if (!p.configured) html += '<span class="badge-warn">not in the routing config</span>';
  html += '</div>';
  if (p.entries && p.entries.length) {
    html += '<div class="pool-entries">' + escapeHtml(p.entries.join(', ')) + '</div>';
  }
  if (p.started && (p.lanes || []).length) {
    html += '<table class="lane-table"><thead><tr>'
      + '<th>Lane</th><th>Hot key</th><th>Running</th><th>For</th><th>State</th>'
      + '</tr></thead><tbody>';
    for (const lane of p.lanes) {
      const state = lane.busy ? '<span class="lane-busy">busy</span>'
                              : '<span class="lane-idle">idle</span>';
      const forCell = lane.busy
        ? secs(lane.running_s)
        : (lane.used ? 'idle ' + secs(lane.idle_s) : '');
      html += '<tr><td>' + escapeHtml(lane.lane_id) + '</td>'
        + '<td>' + (lane.hot_key ? escapeHtml(lane.hot_key) : '<span class="muted">never used</span>') + '</td>'
        + '<td>' + (lane.busy ? escapeHtml(lane.label || '?') : '<span class="muted">—</span>') + '</td>'
        + '<td>' + escapeHtml(forCell) + '</td>'
        + '<td>' + state + '</td></tr>';
    }
    html += '</tbody></table>';
  }
  // Reservations first: a reply that is queued in the AgentLoop and holds
  // this pool against lower-class work while it waits for a lane. It is NOT a
  // waiting call — it occupies no lane and is parked nowhere — so it gets its
  // own block above the waiting table instead of a row inside it.
  const reserved = p.reservations || [];
  if (reserved.length) {
    html += '<div class="wait-head">Reserved for a reply (' + reserved.length + ')</div>';
    for (const r of reserved) {
      html += '<div class="reserved-row"><span class="reserved-tag">reserved</span>'
        + '<span class="reserved-key">' + escapeHtml(r.cache_key) + '</span>'
        + '<span class="reserved-note">' + escapeHtml(r.priority_label || '')
        + ' · held by ' + escapeHtml(r.holder || 'unknown')
        + ' · refreshed while the reply needs it (' + escapeHtml(secs(r.expires_in_s))
        + ' left if its holder stops)'
        + ' · a freed lane does not go to a lower class</span></div>';
    }
  }
  const waiting = p.waiting_calls || [];
  if (waiting.length) {
    html += '<div class="wait-head">Waiting on this pool (' + waiting.length + ')</div>';
    html += '<table class="lane-table wait-table"><thead><tr>'
      + '<th>Key</th><th>Class</th><th>Waiting</th><th>Reason</th>'
      + '</tr></thead><tbody>';
    for (const w of waiting) {
      const cls = w.aged
        ? escapeHtml(w.priority_label) + ' → ' + escapeHtml(w.effective_label)
        : escapeHtml(w.priority_label);
      // A resume or a nested tool call carries the TURN's arrival, not the
      // moment it started waiting — "40s" there means "40s into its turn",
      // not "parked for 40s". Saying which lane it is coming back to is what
      // tells the two apart.
      const key = (w.own_lane === null || w.own_lane === undefined)
        ? escapeHtml(w.cache_key)
        : escapeHtml(w.cache_key) + ' <span class="muted">(back to lane '
          + escapeHtml(String(w.own_lane)) + ')</span>';
      html += '<tr><td>' + key + '</td>'
        + '<td>' + cls + '</td>'
        + '<td>' + escapeHtml(secs(w.waiting_s)) + '</td>'
        + '<td>' + escapeHtml(laneReasonText(w.reason)) + '</td></tr>';
    }
    html += '</tbody></table>';
  } else if (p.started) {
    html += '<div class="wait-head muted">nobody waiting</div>';
  }
  html += '</div>';
  return html;
}

function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

async function togglePause() {
  const ep = (_state && _state.paused) ? '/admin/agent-loop/resume' : '/admin/agent-loop/pause';
  try { await fetch(ep, { method: 'POST' }); } catch(e) {}
  await load();
}

load();
setInterval(load, 5000);
