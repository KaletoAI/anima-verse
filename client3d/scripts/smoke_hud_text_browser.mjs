/** Real Chromium + controlled React inputs, shared by both bridge wire smokes. */
import assert from 'node:assert/strict';
import { buildSync } from 'esbuild';
import { spawnSync } from 'node:child_process';
import { existsSync, mkdtempSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { homedir, tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

export function smokeHudText(wire) {
  const cache = join(homedir(), '.cache/ms-playwright');
  const candidates = process.env.CHROME_BIN ? [process.env.CHROME_BIN] : [
    ...(existsSync(cache) ? readdirSync(cache).sort().reverse().map(dir => join(cache, dir, 'chrome-headless-shell-linux64/chrome-headless-shell')) : []),
    '/usr/bin/chromium', '/usr/bin/chromium-browser', '/usr/bin/google-chrome',
  ];
  const chrome = candidates.find(path => existsSync(path));
  assert.ok(chrome, 'HUD text smoke needs Chromium (set CHROME_BIN)');
  const script = buildSync({
    stdin: { resolveDir: fileURLToPath(new URL('../../', import.meta.url)), contents: `
      import React, { useState } from 'react';
      import { createRoot } from 'react-dom/client';
      import { flushSync } from 'react-dom';
      import { connectHudSide, gdcefTransport, loopbackPair } from './client3d/src/hud/bridge';
      const equal = (got, want, why) => { if (got !== want) throw new Error(why + ': got ' + JSON.stringify(got) + ', want ' + JSON.stringify(want)); };
      try {
        let send;
        let stop;
        if (${JSON.stringify(wire)} === 'gdcef') {
          let receive;
          const host = { godotMethods: { hud_bridge: () => true }, godotEvents: { on: (_, fn) => { receive = fn; } } };
          stop = connectHudSide(gdcefTransport(host));
          send = msg => receive(JSON.stringify(msg));
        } else {
          const [scene, hud] = loopbackPair();
          stop = connectHudSide(hud);
          send = msg => scene.send(msg);
        }
        const text = value => flushSync(() => send({ v: 4, kind: 'text', value }));
        function App() {
          const [input, setInput] = useState('');
          const [area, setArea] = useState('');
          return React.createElement('div', null,
            React.createElement('input', { id: 'input', value: input, onChange: e => setInput(e.target.value) }),
            React.createElement('output', { id: 'inputState' }, input),
            React.createElement('textarea', { id: 'area', value: area, onChange: e => setArea(e.target.value) }),
            React.createElement('output', { id: 'areaState' }, area));
        }
        const root = createRoot(document.getElementById('root'));
        flushSync(() => root.render(React.createElement(App)));
        const input = document.getElementById('input');
        input.focus();
        for (const c of ['.', '(', 'ö']) text(c);
        equal(input.value, '.(ö', 'native text inserts into focused input');
        equal(document.getElementById('inputState').textContent, '.(ö', 'React sees execCommand input events');
        input.setSelectionRange(1, 3); text('!');
        equal(input.value, '.!', 'selection replaced');
        equal(document.getElementById('inputState').textContent, '.!', 'React sees replacement');
        const exec = document.execCommand;
        for (const unavailable of [undefined, () => false, () => { throw new Error('unavailable'); }]) {
          document.execCommand = unavailable;
          input.setSelectionRange(1, 2); text('ö');
          equal(input.value, '.ö', 'fallback replaces selection');
          equal(input.selectionStart, 2, 'fallback places caret after text');
          equal(document.getElementById('inputState').textContent, '.ö', 'React sees native setter fallback');
          input.setSelectionRange(1, 2); text('!');
          const area = document.getElementById('area'); area.focus(); text('ö');
          equal(document.getElementById('areaState').textContent, area.value, 'React textarea state updates');
          input.focus();
        }
        document.execCommand = exec;
        const editable = document.createElement('div'); editable.contentEditable = 'true'; document.body.append(editable);
        editable.focus(); text('.'); text('('); text('ö');
        equal(editable.textContent, '.(ö', 'contenteditable receives native text');
        const disabled = document.createElement('input'); disabled.disabled = true; document.body.append(disabled);
        input.readOnly = true; input.focus(); text('x'); equal(input.value, '.!', 'readonly ignored'); input.readOnly = false;
        const button = document.createElement('button'); document.body.append(button); button.focus(); text('x');
        equal(button.textContent, '', 'noneditable focus ignored');
        button.blur(); text('x'); equal(document.activeElement, document.body, 'no focused editable ignored');
        equal(input.value, '.!', 'unfocused input unchanged');
        input.focus(); text(7); text(null); equal(input.value, '.!', 'non-string message ignored');
        stop(); text('x'); equal(input.value, '.!', 'disconnect removes text receiver');
        document.body.dataset.result = 'PASS';
      } catch (error) { document.body.dataset.result = 'FAIL'; document.body.append(String(error.stack)); }
    ` },
    bundle: true, format: 'iife', platform: 'browser', write: false,
    define: { 'process.env.NODE_ENV': '"production"' },
  }).outputFiles[0].text;
  const dir = mkdtempSync(join(tmpdir(), 'hud-text-'));
  try {
    const html = join(dir, 'smoke.html');
    writeFileSync(html, `<meta charset="utf-8"><body><div id="root"></div><script>${script.replaceAll('</script', '<\\/script')}</script>`);
    const result = spawnSync(chrome, ['--headless', '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage',
      `--user-data-dir=${dir}/profile`, '--dump-dom', '--virtual-time-budget=1000', `file://${html}`],
    { encoding: 'utf8', timeout: 30_000, maxBuffer: 4 * 1024 * 1024 });
    assert.equal(result.status, 0, JSON.stringify({ error: result.error?.message, stderr: result.stderr }));
    assert.match(result.stdout, /data-result="PASS"/, result.stdout.replace(/<script>[\s\S]*?<\/script>/g, ''));
  } finally { rmSync(dir, { recursive: true, force: true }); }
  console.log('hud text: PASS (' + wire + ', real Chromium + React, execCommand/fallback, selection, editable focus, cleanup)');
}
