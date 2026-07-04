
let _state = null;

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
  } catch(e) {
    clearTimeout(timer);
    if (lbl) lbl.textContent = (e.name === 'AbortError')
      ? "timeout — server didn't respond in 8s (call #" + _loadCounter + ")"
      : "error: " + e.message + " (call #" + _loadCounter + ")";
    console.error('[agent-loop load failed]', e);
  }
}

// Verifiziere dass der Script ueberhaupt laeuft — wenn 'loading…' nach 1s
// nicht ersetzt wurde, gab es einen Pre-Init-Error.
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
    // Link zum LLM Log: nur fuer Outcomes wo tatsaechlich ein LLM-Call lief.
    // Auto-Sleep / in_chat_skip / no_llm haben keinen Eintrag im LLM-Log.
    const _llmRanOutcomes = !(
      (r.outcome || '').startsWith('auto_sleep') ||
      r.outcome === 'in_chat_skip' || r.outcome === 'no_llm'
    );
    let logLink = '';
    if (_llmRanOutcomes && r.agent && r.started_at) {
      // Search-Filter: ISO-Format mit "T" + Minute des Turn-Starts (matcht
      // das Roh-Format in llm_calls.jsonl 'starttime'). Beispiel:
      // "2026-05-05T13:35". Der LLM-Log-Viewer liest die URL-Params, wendet
      // Filter an und auto-expanded den ersten Treffer.
      const tsMin = (r.started_at || '').slice(0, 16);
      const url = '/logs/llm?character=' + encodeURIComponent(r.agent)
                + '&search=' + encodeURIComponent(tsMin);
      // Wir versuchen die Admin-Sidebar-Navigation (parent.activateIframe) zu
      // nutzen — dann wird im Admin-Layout NUR der iframe-Inhalt getauscht
      // und Sidebar-Links bleiben erhalten. Fallback: direkte Navigation
      // (z.B. wenn Agent-Loop standalone geoeffnet wurde).
      const onclick = "event.preventDefault();"
        + " try { if (window.parent && window.parent.activateIframe) {"
        + " window.parent.activateIframe('_llm_log', '" + url + "', 'LLM Log'); return; } } catch(e) {}"
        + " window.location = '" + url + "';";
      logLink = ` <a href="${url}" onclick="${onclick}" title="Im LLM-Log oeffnen" style="margin-left:6px;text-decoration:none;color:#58a6ff;">🔍</a>`;
    }
    const preview = r.preview
      ? `<span class="preview">${escapeHtml(r.preview)}</span>${logLink}`
      : (logLink ? `<span class="muted">—</span>${logLink}` : '<span class="muted">—</span>');
    let startedShort = '';
    if (r.started_at) {
      const _d = new Date(r.started_at);
      startedShort = isNaN(_d.getTime()) ? r.started_at.replace('T', ' ').split('.')[0]
        : _d.toLocaleString('de-DE', {month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit'});
    }
    tr.innerHTML = `<td>${escapeHtml(r.agent)}</td><td>${escapeHtml(startedShort)}</td><td>${r.duration_s}s</td><td class="${cls}">${escapeHtml(r.outcome)}</td><td>${tagsCell}</td><td>${preview}</td>`;
    tbody.appendChild(tr);
  }
}

function escapeHtml(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }

async function togglePause() {
  const ep = (_state && _state.paused) ? '/admin/agent-loop/resume' : '/admin/agent-loop/pause';
  try { await fetch(ep, { method: 'POST' }); } catch(e) {}
  await load();
}

load();
setInterval(load, 5000);
