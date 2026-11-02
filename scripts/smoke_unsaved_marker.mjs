/**
 * The "unsaved changes" marker of the Game-Admin detail toolbar
 * (`frontend/src/components/DetailToolbar.tsx`, prop `dirty`), rendered for
 * real — no backend, no browser.
 *
 * Usage: node scripts/smoke_unsaved_marker.mjs
 *
 * Hand-derived expectations:
 *   [1] dirty=false: no marker, Save without `ga-btn-dirty`; Cancel calls
 *       onCancel at once (1 call).
 *   [2] dirty=true: the marker "Unsaved changes" is there and Save carries
 *       `ga-btn-dirty`; Cancel does NOT call onCancel (it asks first — 0
 *       calls), the question is answered in the dialog.
 *   [3] German: the marker reads "Ungespeicherte Änderungen".
 *   [4] useDraft's rule, in the hook's own terms: a draft equal to its
 *       baseline (JSON) is clean, an edit is dirty, editing it back is clean.
 */
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('..', import.meta.url));
const require = createRequire(resolve(root, 'frontend/package.json'));
const ts = require('typescript');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');

const cache = new Map();
let nodes = [];
function load(path) {
  if (cache.has(path)) return cache.get(path).exports;
  const module = { exports: {} };
  cache.set(path, module);
  const code = ts.transpileModule(readFileSync(path, 'utf8'), { fileName: path, compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
  } }).outputText;
  new Function('require', 'module', 'exports', code)((spec) => {
    if (spec.endsWith('.css')) return {};
    if (spec === 'react/jsx-runtime') {
      const runtime = require(spec);
      return Object.fromEntries(Object.entries(runtime).map(([name, value]) => [name,
        name === 'jsx' || name === 'jsxs' ? (...args) => { const node = value(...args); nodes.push(node); return node; } : value]));
    }
    if (spec === '@anima/player-ui') return load(resolve(root, 'packages/player-ui/src/index.ts'));
    if (!spec.startsWith('.')) return require(spec);
    const base = resolve(dirname(path), spec);
    const target = [base + '.ts', base + '.tsx', base + '/index.ts'].find(existsSync);
    assert.ok(target, spec);
    return load(target);
  }, module, module.exports);
  return module.exports;
}

const { DetailToolbar } = load(resolve(root, 'frontend/src/components/DetailToolbar.tsx'));
const { I18nProvider } = load(resolve(root, 'frontend/src/i18n/I18nProvider.tsx'));
const text = (n) => Array.isArray(n) ? n.map(text).join('') : n && typeof n === 'object' ? text(n.props?.children)
  : n == null || n === false ? '' : String(n);

function render(dirty) {
  nodes = [];
  let cancels = 0;
  const html = renderToStaticMarkup(React.createElement(I18nProvider, null, React.createElement(DetailToolbar, {
    title: 'x', dirty, onSave: () => {}, onCancel: () => { cancels++; } })));
  const buttons = nodes.filter((n) => n.type === 'button');
  const save = buttons.find((b) => text(b.props.children) === 'Save');
  const cancel = buttons.find((b) => text(b.props.children) === 'Cancel');
  cancel.props.onClick();
  return { html, save, cancels };
}

const clean = render(false);
assert.ok(!clean.html.includes('Unsaved changes'), '[1] no marker');
assert.ok(!clean.save.props.className.includes('ga-btn-dirty'), '[1] plain Save');
assert.equal(clean.cancels, 1, '[1] Cancel acts at once');
console.log('[1] clean: no marker, plain Save, Cancel at once');

const dirty = render(true);
assert.ok(dirty.html.includes('Unsaved changes'), '[2] marker');
assert.ok(dirty.save.props.className.includes('ga-btn-dirty'), '[2] Save highlighted');
assert.equal(dirty.cancels, 0, '[2] Cancel asks first');
console.log('[2] dirty: marker, highlighted Save, Cancel asks first');

const de = JSON.parse(readFileSync(resolve(root, 'shared/languages/de.json'), 'utf8'));
const flat = (o) => Object.assign({}, ...Object.values(o).map((v) => (v && typeof v === 'object' ? flat(v) : {})), o);
assert.equal(flat(de)['Unsaved changes'], 'Ungespeicherte Änderungen', '[3] German marker');
console.log('[3] German marker text');

const src = readFileSync(resolve(root, 'frontend/src/lib/useDraft.tsx'), 'utf8');
assert.match(src, /JSON\.stringify\(draft\) !== base/, '[4] structural comparison against the baseline');
const isDirty = (draft, base) => draft !== null && JSON.stringify(draft) !== JSON.stringify(base);
const base = { id: 'a', field_overrides: {} };
assert.equal(isDirty({ ...base }, base), false);
assert.equal(isDirty({ ...base, field_overrides: { privacy: 'open' } }, base), true);
assert.equal(isDirty({ ...base, field_overrides: {} }, base), false);
console.log('[4] useDraft: clean / edited / edited back');
console.log('PASS: unsaved marker');
