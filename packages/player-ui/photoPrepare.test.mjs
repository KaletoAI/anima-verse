// Usage: node packages/player-ui/photoPrepare.test.mjs
// Held HTTP promises exercise the real ScenePanel and dialog with deterministic hooks.
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import ts from 'typescript';
import React from 'react';
const require = createRequire(import.meta.url);
const cache = new Map(), requests = [];
let portal, control;
const t = x => x;
const toast = () => {};
function load(path) {
  if (cache.has(path)) return cache.get(path).exports;
  const m = { exports: {} }; cache.set(path, m);
  const code = ts.transpileModule(readFileSync(path, 'utf8'), { fileName: path, compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
  }}).outputText;
  new Function('require', 'module', 'exports', code)(id => {
    if (id === 'react-dom') return { createPortal: children => { portal = children; return children; } };
    if (!id.startsWith('.')) return require(id);
    if (id === './I18nProvider') return { useI18n: () => ({ t }) };
    if (id === './Toast') return { useToast: () => ({ toast }) };
    if (id === './api') return { ApiError: Error, apiGet: async () => ({}), apiPost: (url, body) => {
      if (!url.endsWith('/prepare')) { requests.push({ url, body }); return Promise.resolve({ status: 'accepted' }); }
      return new Promise((resolve, reject) => requests.push({ url, body, resolve, reject }));
    } };
    if (id === './useQueue') return { useQueue: () => ({ agentActivity: [] }) };
    if (id === './Lightbox') return { useLightbox: () => ({ open() {} }) };
    if (id === './ZoomButton') return { useEnlarge: () => () => ({}) };
    if (id === './propActions') return { onPropActionChanged: () => () => {} };
    if (['./SceneView', './ScenesRecap', './GiftPicker', './ChatGalleryPicker', './PropActionsPanel'].includes(id)) return new Proxy({}, { get: () => () => null });
    const base = resolve(dirname(path), id);
    return load([base + '.ts', base + '.tsx'].find(existsSync));
  }, m, m.exports);
  return m.exports;
}
function instance(Component) {
  const slots = []; let cursor, effects;
  const slot = initial => { const i = cursor++; if (!(i in slots)) slots[i] = typeof initial === 'function' ? initial() : initial;
    return [slots[i], next => { slots[i] = typeof next === 'function' ? next(slots[i]) : next; }]; };
  const hooks = {
    useState: slot, useRef: initial => slot(() => ({ current: initial }))[0],
    useCallback: fn => fn, useMemo: fn => fn(),
    useSyncExternalStore: (_subscribe, get) => get(),
    useEffect(fn, deps) {
      const i = cursor++, old = slots[i];
      if (!old || !deps || deps.some((v, j) => !Object.is(v, old.deps[j]))) {
        effects.push(() => { old?.cleanup?.(); slots[i] = { deps, cleanup: fn() }; });
      }
    },
  };
  return props => {
    const dispatcher = React.__SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED.ReactCurrentDispatcher;
    const previous = dispatcher.current; cursor = 0; effects = []; dispatcher.current = hooks;
    let tree; try { tree = Component(props); } finally { dispatcher.current = previous; }
    effects.forEach(fn => fn()); return tree;
  };
}
function find(node, predicate) {
  if (!node || typeof node !== 'object') return null;
  if (Array.isArray(node)) return node.map(n => find(n, predicate)).find(Boolean) ?? null;
  return predicate(node) ? node : find(node.props?.children, predicate);
}
globalThis.document = { body: {} };
globalThis.window = { addEventListener() {}, removeEventListener() {} };
const { ScenePanel } = load(resolve('packages/player-ui/src/ScenePanel.tsx'));
const { PlayerPhotoDialog } = load(resolve('packages/player-ui/src/PlayerPhotoDialog.tsx'));
let panel = instance(ScenePanel), dialog = instance(PlayerPhotoDialog);
const props = { data: { capability_actions: { scene_photo: 'camera' }, present: [] }, avatar: 'Ann',
  hasCapability: () => true, refreshScene: async () => {}, onEnterRoom() {},
  photoDialog: ctl => { control = ctl; return React.createElement('div', { role: 'dialog' }); } };
const render = extra => panel({ ...props, ...extra });
const camera = tree => find(tree, n => n.type === 'button' && n.props.children === '📷');
const input = () => find(portal, n => n.type === 'textarea');
const generate = () => find(portal, n => n.type === 'button' && n.props.children === 'Generate');
const ready = (prompt = 'Server prompt', name = 'Bob') => ({ ok: true, prompt, subjects: [name], present: [name] });
const flush = async () => { await new Promise(resolve => setImmediate(resolve)); };
let tree = render(); camera(tree).props.onClick(); tree = render();
assert.ok(find(tree, n => n.props?.role === 'dialog'), 'chat opens immediately, before prepare resolves');
dialog(control);
assert.equal(input().props.placeholder, 'Describing the scene…');
assert.equal(generate().props.disabled, true);
requests[0].resolve(ready()); await flush(); render(); dialog(control); dialog(control);
assert.equal(input().props.value, 'Server prompt');
assert.ok(find(portal, n => n.type === 'button' && n.props.children === 'Bob' && n.props['aria-pressed']));
control.onClose(); tree = render(); camera(tree).props.onClick(); render(); dialog = instance(PlayerPhotoDialog); dialog(control);
input().props.onChange({ target: { value: 'My own prompt' } }); render(); dialog(control);
assert.equal(generate().props.disabled, false, 'typed prompt can submit during prepare');
requests[1].resolve(ready('Do not overwrite', 'Cid')); await flush(); render(); dialog(control); dialog(control);
assert.equal(input().props.value, 'My own prompt');
assert.ok(find(portal, n => n.type === 'button' && n.props.children === 'Cid' && n.props['aria-pressed']));
control.onClose(); render();
const shot = id => ({ imageId: id, imageUrl: '/shot/' + id, view: { visible: [], camera: {} } });
const a = shot('a'), b = shot('b');
render({ screenshotPhoto: a }); render({ screenshotPhoto: a }); const old = requests.at(-1);
render({ screenshotPhoto: b }); render({ screenshotPhoto: b }); const newest = requests.at(-1);
assert.equal(control.referenceImageId, 'b');
dialog = instance(PlayerPhotoDialog); dialog(control);
assert.equal(find(portal, n => n.type === 'img').props.src, '/shot/b');
assert.equal(input().props.placeholder, 'Describing the scene…');
assert.equal(generate().props.disabled, true);
newest.resolve(ready('Newest')); await flush(); render({ screenshotPhoto: b });
assert.equal(control.prompt, 'Newest');
old.resolve(ready('Stale')); await flush(); render({ screenshotPhoto: b });
assert.equal(control.prompt, 'Newest', 'old answer never reopens or replaces the newest dialog');
control.onClose(); render(); camera(render()).props.onClick(); render(); const closed = requests.at(-1);
control.onClose(); render(); closed.resolve(ready()); await flush();
assert.equal(find(render(), n => n.props?.role === 'dialog'), null, 'close invalidates late prepare');
camera(render()).props.onClick(); render(); const failed = requests.at(-1);
failed.reject(new Error('Describe failed')); await flush(); render();
assert.equal(control.error, 'Describe failed');
dialog = instance(PlayerPhotoDialog); dialog(control);
assert.ok(find(portal, n => n.props?.role === 'alert' && n.props.children === 'Describe failed'));
input().props.onChange({ target: { value: 'Manual retry' } }); render(); dialog(control);
await generate().props.onClick();
assert.equal(requests.at(-1).body.prompt, 'Manual retry');
assert.equal(find(render(), n => n.props?.role === 'dialog'), null);
// A remount during preparation reuses the same request and receives its result.
const c = shot('c'); render({ screenshotPhoto: c }); render({ screenshotPhoto: c });
const count = requests.length, held = requests.at(-1), stableId = control.dialogId;
panel = instance(ScenePanel); render({ screenshotPhoto: c }); render({ screenshotPhoto: c });
assert.equal(requests.length, count); assert.equal(control.dialogId, stableId);
held.resolve(ready('After remount')); await flush(); render({ screenshotPhoto: c });
assert.equal(control.prompt, 'After remount');
dialog = instance(PlayerPhotoDialog); dialog(control);
input().props.onChange({ target: { value: 'Keep across remount' } });
panel = instance(ScenePanel); render({ screenshotPhoto: c });
dialog = instance(PlayerPhotoDialog); dialog(control);
assert.equal(input().props.value, 'Keep across remount');
assert.equal(control.dialogId, stableId);
control.onClose(); render();
camera(render()).props.onClick(); render();
requests.at(-1).resolve({ ok: false, error: 'Server prepare failure' }); await flush(); render();
assert.equal(control.error, 'Server prepare failure');
assert.equal(control.preparing, false);
control.onClose(); render();
camera(render()).props.onClick(); render();
requests.at(-1).resolve({ ok: false }); await flush(); render();
assert.equal(control.error, 'Photo failed.');
control.onClose(); render();
console.log('photo prepare: PASS (immediate, edits/chips, newest wins, close, error retry, remount)');
