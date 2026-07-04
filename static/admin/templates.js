
let _state = { templates: [], characters: [], dirty: false };

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
  sel.innerHTML = '';
  let lastKind = '';
  for (const t of _state.templates) {
    if (t.kind !== lastKind) {
      const og = document.createElement('optgroup');
      og.label = t.kind;
      og.id = 'optgroup-' + t.kind;
      sel.appendChild(og);
      lastKind = t.kind;
    }
    const o = document.createElement('option');
    o.value = t.path;
    o.textContent = t.path.split('/').pop().replace('.md', '') + (t.has_preview ? '' : '  (no preview)');
    if (!t.has_preview) o.classList.add('no-preview');
    document.getElementById('optgroup-' + t.kind).appendChild(o);
  }
}

async function loadCharacters() {
  const r = await fetch('/characters/list');
  if (!r.ok) return;
  const d = await r.json();
  const chars = d.characters || [];
  const av = document.getElementById('sel-avatar');
  const ag = document.getElementById('sel-agent');
  av.innerHTML = '<option value="">(none)</option>';
  ag.innerHTML = '';
  for (const c of chars) {
    const oa = document.createElement('option'); oa.value = c; oa.textContent = c; av.appendChild(oa);
    const og = document.createElement('option'); og.value = c; og.textContent = c; ag.appendChild(og);
  }
  if (chars.length >= 2) av.value = chars[0];
  if (chars.length >= 1) ag.value = chars[chars.length >= 2 ? 1 : 0];
}

async function loadFile(path) {
  setStatus('loading…');
  try {
    const r = await fetch('/admin/templates/file?path=' + encodeURIComponent(path));
    if (!r.ok) throw new Error(await r.text());
    const d = await r.json();
    document.getElementById('editor').value = d.content || '';
    _state.dirty = false;
    setStatus('loaded', 'ok');
    await render();
  } catch (e) {
    setStatus('load failed: ' + e.message, 'err');
  }
}

async function saveFile() {
  const path = document.getElementById('sel-template').value;
  const content = document.getElementById('editor').value;
  if (!path) return;
  setStatus('saving…');
  try {
    const r = await fetch('/admin/templates/file', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path, content }),
    });
    if (!r.ok) throw new Error(await r.text());
    _state.dirty = false;
    setStatus('saved', 'ok');
    await render();
  } catch (e) {
    setStatus('save failed: ' + e.message, 'err');
  }
}

async function render() {
  const path = document.getElementById('sel-template').value;
  const avatar = document.getElementById('sel-avatar').value;
  const agent = document.getElementById('sel-agent').value;
  if (!path) return;
  setStatus('rendering…');
  try {
    const r = await fetch(`/admin/templates/render?path=${encodeURIComponent(path)}&agent=${encodeURIComponent(agent)}&avatar=${encodeURIComponent(avatar)}`);
    const d = await r.json();
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
    setStatus('render failed: ' + e.message, 'err');
  }
}

document.getElementById('sel-template').addEventListener('change', e => loadFile(e.target.value));
document.getElementById('sel-avatar').addEventListener('change', render);
document.getElementById('sel-agent').addEventListener('change', render);
document.getElementById('btn-save').addEventListener('click', saveFile);
document.getElementById('btn-render').addEventListener('click', render);
document.getElementById('editor').addEventListener('input', () => { _state.dirty = true; setStatus('unsaved changes'); });

(async () => {
  await Promise.all([loadTemplates(), loadCharacters()]);
  const sel = document.getElementById('sel-template');
  if (sel.options.length) {
    sel.value = sel.options[0].value;
    await loadFile(sel.value);
  }
})();
