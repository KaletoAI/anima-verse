
let _state = { templates: [], characters: [], dirty: false, shipped: '', origin: '', world: '…', orphan: false, base_changed: false, view: 'preview' };
let _fileGeneration = 0;

function isCurrentFile(path, generation) {
  return generation === _fileGeneration && document.getElementById('sel-template').value === path;
}

function setStatus(msg, kind) {
  const el = document.getElementById('status');
  el.textContent = msg;
  el.className = kind || '';
}

async function loadTemplates() {
  const r = await fetch('/admin/templates/list');
  if (!r.ok) { setStatus('list failed: ' + r.status, 'err'); return; }
  const d = await r.json();
  _state.templates = d.templates || [];
  const sel = document.getElementById('sel-template');
  const selected = sel.value;
  sel.replaceChildren();
  const groups = new Map();
  for (const t of _state.templates) {
    if (!groups.has(t.kind)) {
      const og = document.createElement('optgroup');
      og.label = t.kind;
      groups.set(t.kind, og);
      sel.appendChild(og);
    }
    const o = document.createElement('option');
    o.value = t.path;
    o.textContent = t.path.split('/').pop().replace('.md', '') + (t.has_preview ? '' : '  (no preview)') + (t.override ? '  ● override' : '') + (t.base_changed ? '  ⚠' : '') + (t.shadowed ? '  (shadowed)' : '');
    if (!t.has_preview) o.classList.add('no-preview');
    groups.get(t.kind).appendChild(o);
  }
  if (_state.templates.some(t => t.path === selected)) sel.value = selected;
  return selected;
}

async function loadCharacters() {
  const r = await fetch('/characters/list');
  if (!r.ok) return;
  const d = await r.json();
  // /characters/list ships {name, template, temporary} rows — names only here.
  const chars = (d.characters || []).map(c => c.name);
  const av = document.getElementById('sel-avatar');
  const ag = document.getElementById('sel-agent');
  av.replaceChildren();
  const none = document.createElement('option');
  none.value = ''; none.textContent = '(none)'; av.appendChild(none);
  ag.replaceChildren();
  for (const c of chars) {
    const oa = document.createElement('option'); oa.value = c; oa.textContent = c; av.appendChild(oa);
    const og = document.createElement('option'); og.value = c; og.textContent = c; ag.appendChild(og);
  }
  if (chars.length >= 2) av.value = chars[0];
  if (chars.length >= 1) ag.value = chars[chars.length >= 2 ? 1 : 0];
}

async function loadFile(path) {
  const generation = ++_fileGeneration;
  _state.origin = '';
  updateOriginUi();
  setStatus('loading…');
  try {
    const r = await fetch('/admin/templates/file?path=' + encodeURIComponent(path));
    if (!r.ok) throw new Error(await r.text());
    const d = await r.json();
    if (!isCurrentFile(path, generation)) return;
    document.getElementById('editor').value = d.content || '';
    Object.assign(_state, { shipped: d.shipped, origin: d.origin, world: d.world, orphan: d.orphan, base_changed: d.base_changed, dirty: false });
    updateOriginUi();
    renderDiff();
    setStatus('loaded', 'ok');
    await render();
  } catch (e) {
    if (!isCurrentFile(path, generation)) return;
    setStatus('load failed: ' + e.message, 'err');
  }
}

async function saveFile() {
  const path = document.getElementById('sel-template').value;
  const generation = _fileGeneration;
  const content = document.getElementById('editor').value;
  if (!path || _state.orphan || !_state.origin) return;
  setStatus('saving…');
  try {
    const r = await fetch('/admin/templates/file', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path, content }),
    });
    if (!r.ok) throw new Error(await r.text());
    await loadTemplates();
    if (!isCurrentFile(path, generation)) return;
    const reload = loadFile(path);
    const reloadGeneration = _fileGeneration;
    await reload;
    if (isCurrentFile(path, reloadGeneration)) setStatus('saved', 'ok');
  } catch (e) {
    if (!isCurrentFile(path, generation)) return;
    setStatus('save failed: ' + e.message, 'err');
  }
}

async function render() {
  const path = document.getElementById('sel-template').value;
  const generation = _fileGeneration;
  const avatar = document.getElementById('sel-avatar').value;
  const agent = document.getElementById('sel-agent').value;
  if (!path) return;
  if (!_state.templates.find(t => t.path === path)?.has_preview) {
    document.getElementById('preview').textContent = '(no preview)';
    document.getElementById('note').textContent = '';
    return;
  }
  setStatus('rendering…');
  try {
    const r = await fetch(`/admin/templates/render?path=${encodeURIComponent(path)}&agent=${encodeURIComponent(agent)}&avatar=${encodeURIComponent(avatar)}`);
    const d = await r.json();
    if (!isCurrentFile(path, generation)) return;
    const prev = document.getElementById('preview');
    const note = document.getElementById('note');
    if (d.ok) {
      prev.textContent = d.output || '(empty)';
      note.textContent = d.note || '';
      setStatus('rendered', 'ok');
    } else {
      prev.textContent = '(no output)';
      note.textContent = d.note || 'preview failed';
      setStatus('preview failed', 'err');
    }
  } catch (e) {
    if (!isCurrentFile(path, generation)) return;
    setStatus('render failed: ' + e.message, 'err');
  }
}

function updateOriginUi() {
  document.getElementById('world').textContent = 'World: ' + _state.world;
  const origin = document.getElementById('origin');
  origin.textContent = _state.origin === 'override'
    ? (_state.orphan ? 'Override (orphan — shipped template gone)' : 'Override')
    : (_state.origin ? 'Shipped' : '');
  origin.className = _state.origin === 'override' ? 'override' : '';
  document.getElementById('btn-save').disabled = _state.orphan || !_state.origin;
  document.getElementById('btn-delete-override').hidden = _state.origin !== 'override';
  const warning = document.getElementById('base-warning');
  warning.hidden = !_state.base_changed;
  warning.textContent = 'The shipped template changed since this override was saved — compare and update.';
}

async function deleteOverride() {
  const path = document.getElementById('sel-template').value;
  const generation = _fileGeneration;
  if (!path) return;
  try {
    const r = await fetch('/admin/templates/override?path=' + encodeURIComponent(path), { method: 'DELETE' });
    if (!r.ok) throw new Error(await r.text());
    const selection = await loadTemplates();
    // Removing an orphan can make the browser select a fallback option itself.
    if (generation !== _fileGeneration || selection !== path) return;
    const sel = document.getElementById('sel-template');
    const next = _state.templates.some(t => t.path === path) ? path : (_state.templates[0]?.path || '');
    sel.value = next;
    let reloadGeneration;
    if (next) {
      const reload = loadFile(next);
      reloadGeneration = _fileGeneration;
      await reload;
    }
    else {
      reloadGeneration = ++_fileGeneration;
      Object.assign(_state, { shipped: '', origin: '', orphan: false, base_changed: false, dirty: false });
      document.getElementById('editor').value = '';
      document.getElementById('preview').textContent = '';
      document.getElementById('note').textContent = '';
      document.getElementById('diff').replaceChildren();
      updateOriginUi();
    }
    if (isCurrentFile(next, reloadGeneration)) setStatus('override deleted', 'ok');
  } catch (e) {
    if (isCurrentFile(path, generation)) setStatus('delete failed: ' + e.message, 'err');
  }
}

// Line diff (LCS) between the shipped template and the editor content.
function lineDiff(a, b) {
  const A = a.split('\n'), B = b.split('\n');
  const n = A.length, m = B.length;
  const L = Array.from({ length: n + 1 }, () => new Int32Array(m + 1));
  for (let i = n - 1; i >= 0; i--)
    for (let j = m - 1; j >= 0; j--)
      L[i][j] = A[i] === B[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
  const out = [];
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (A[i] === B[j]) { out.push([' ', A[i]]); i++; j++; }
    else if (L[i + 1][j] >= L[i][j + 1]) { out.push(['-', A[i]]); i++; }
    else { out.push(['+', B[j]]); j++; }
  }
  while (i < n) out.push(['-', A[i++]]);
  while (j < m) out.push(['+', B[j++]]);
  return out;
}

function renderDiff() {
  const pre = document.getElementById('diff');
  pre.replaceChildren();
  for (const [op, line] of lineDiff(_state.shipped || '', document.getElementById('editor').value)) {
    const div = document.createElement('div');
    div.className = op === '+' ? 'add' : op === '-' ? 'del' : '';
    div.textContent = op + ' ' + line;
    pre.appendChild(div);
  }
}

function setView(view) {
  _state.view = view;
  document.getElementById('preview').hidden = view !== 'preview';
  document.getElementById('note').hidden = view !== 'preview';
  document.getElementById('diff').hidden = view !== 'diff';
  if (view === 'diff') renderDiff();
}

async function loadWorld() {
  try {
    const r = await fetch('/admin/world-name');
    if (!r.ok) throw new Error(await r.text());
    const d = await r.json();
    _state.world = d.world;
    updateOriginUi();
  } catch (e) { setStatus('world load failed: ' + e.message, 'err'); }
}

document.getElementById('sel-template').addEventListener('change', e => loadFile(e.target.value));
document.getElementById('sel-avatar').addEventListener('change', render);
document.getElementById('sel-agent').addEventListener('change', render);
document.getElementById('btn-delete-override').addEventListener('click', deleteOverride);
document.getElementById('btn-view-preview').addEventListener('click', () => setView('preview'));
document.getElementById('btn-view-diff').addEventListener('click', () => setView('diff'));
document.getElementById('btn-save').addEventListener('click', saveFile);
document.getElementById('btn-render').addEventListener('click', render);
document.getElementById('editor').addEventListener('input', () => { _state.dirty = true; if (_state.view === 'diff') renderDiff(); setStatus('unsaved changes'); });

(async () => {
  updateOriginUi();
  await Promise.all([loadWorld(), loadTemplates(), loadCharacters()]);
  const sel = document.getElementById('sel-template');
  if (sel.options.length) {
    sel.value = sel.options[0].value;
    await loadFile(sel.value);
  }
})();
