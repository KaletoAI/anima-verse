// Usage: node packages/player-ui/photoDialog.test.mjs
// Render the real dialog; only the portal transport is replaced for SSR.
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import ts from 'typescript';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
const require = createRequire(import.meta.url);
const cache = new Map();
let portal;
const nodes = [];
function load(path) {
  if (cache.has(path)) return cache.get(path).exports;
  const module = { exports: {} }; cache.set(path, module);
  const code = ts.transpileModule(readFileSync(path, 'utf8'), { fileName: path, compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
  }}).outputText;
  new Function('require', 'module', 'exports', code)(specifier => {
    if (specifier === 'react-dom') return { createPortal: children => { portal = children; return children; } };
    if (specifier === 'react/jsx-runtime') {
      const runtime = require(specifier);
      return { ...runtime, jsx: (...args) => { const node = runtime.jsx(...args); nodes.push(node); return node; } };
    }
    if (!specifier.startsWith('.')) return require(specifier);
    const base = resolve(dirname(path), specifier);
    const target = [base + '.ts', base + '.tsx'].find(existsSync);
    assert.ok(target, specifier);
    return load(target);
  }, module, module.exports);
  return module.exports;
}
globalThis.document = { body: {} };
const { PlayerPhotoDialog } = load(resolve('packages/player-ui/src/PlayerPhotoDialog.tsx'));
const { I18nProvider } = load(resolve('packages/player-ui/src/I18nProvider.tsx'));
const props = { prompt: 'Friends by the window', subjects: ['Bob'], available: ['Bob'], avatar: 'Ann', backendOptions: { options: [], resolved: 'Fake' }, onSubmit() {}, onClose() {} };
const render = extra => renderToStaticMarkup(React.createElement(I18nProvider, null, React.createElement(PlayerPhotoDialog, { ...props, ...extra })));
const ordinary = render({});
assert.match(ordinary, /Secretly/);
assert.match(render({ error: 'Invalid photo request' }), /role="alert">Invalid photo request/);
assert.doesNotMatch(ordinary, /<img|The screenshot sets/);
const screenshot = render({ referenceImageId: 'abc.jpg', referenceImageUrl: '/chat/me/upload-image/abc.jpg' });
assert.match(screenshot, /src="\/chat\/me\/upload-image\/abc.jpg"/);
assert.match(screenshot, /The screenshot sets composition and angle; the picture follows the photo style\./);
assert.match(screenshot, /Friends by the window/);
assert.match(screenshot, /Who is in the picture/);
assert.match(screenshot, /Negative prompt/);
assert.match(screenshot, /Auto \(routing\)/);
assert.match(screenshot, /Secretly/);
assert.doesNotMatch(render({ occasion: 'scene_view', hideSceneControls: true }), /Secretly/);
function findButton(node, text) {
  if (!node || typeof node !== 'object') return null;
  if (Array.isArray(node)) return node.map(child => findButton(child, text)).find(Boolean);
  if (node.type === 'button' && node.props.children === text) return node;
  return findButton(node.props?.children, text);
}
let submitted;
render({ referenceImageId: 'abc.jpg', referenceImageUrl: '/chat/me/upload-image/abc.jpg', onSubmit: payload => { submitted = payload; } });
await findButton(portal, 'Generate').props.onClick();
assert.equal(submitted.reference_image_id, 'abc.jpg');
assert.equal(submitted.prompt, 'Friends by the window');
assert.equal(submitted.secret, false);
assert.deepEqual(submitted.character_names, ['Bob']);
render({ onSubmit: payload => { submitted = payload; } });
await findButton(portal, 'Generate').props.onClick();
assert.equal(Object.hasOwn(submitted, 'reference_image_id'), false, 'ordinary photos carry no screenshot');
// Minimal hook dispatcher for an interactive render without a browser DOM.
// The production checkbox handler updates state; re-render and submit for real.
const dispatcher = React.__SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED.ReactCurrentDispatcher;
const state = [];
let cursor = 0;
const hooks = {
  useState(initial) {
    const index = cursor++;
    if (!(index in state)) state[index] = typeof initial === 'function' ? initial() : initial;
    return [state[index], next => { state[index] = typeof next === 'function' ? next(state[index]) : next; }];
  },
  useRef(initial) { return this.useState(() => ({ current: initial }))[0]; },
  useContext() { return { lang: 'en', t: text => text }; },
  useEffect() {},
  useMemo(fn) { return fn(); },
  useCallback(fn) { return fn; },
};
function interactiveDialog(extra) {
  const previous = dispatcher.current;
  cursor = 0;
  dispatcher.current = hooks;
  try { PlayerPhotoDialog({ ...props, ...extra, onSubmit: payload => { submitted = payload; } }); }
  finally { dispatcher.current = previous; }
}
function findSecret(node) {
  if (!node || typeof node !== 'object') return null;
  if (Array.isArray(node)) return node.map(findSecret).find(Boolean);
  if (node.type === 'label' && node.props.children?.[1]?.props.children === 'Secretly') return node.props.children[0];
  return findSecret(node.props?.children);
}
for (const extra of [{}, { referenceImageId: 'abc.jpg' }]) {
  state.length = 0;
  interactiveDialog(extra);
  assert.equal(findSecret(portal).props.checked, false);
  findSecret(portal).props.onChange({ target: { checked: true } });
  interactiveDialog(extra);
  assert.equal(findSecret(portal).props.checked, true);
  await findButton(portal, 'Generate').props.onClick();
  assert.equal(submitted.secret, true);
}
const { ToastProvider } = load(resolve('packages/player-ui/src/Toast.tsx'));
const { ShowPhotoButton, PhotoReadyActions } = load(resolve('packages/player-ui/src/ShowPhotoButton.tsx'));
let opened = false;
const resultMarkup = renderToStaticMarkup(React.createElement(I18nProvider, null,
  React.createElement(ToastProvider, null, React.createElement(PhotoReadyActions,
    { filename: 'own-photo.png', onOpenGallery: () => { opened = true; } }))));
assert.doesNotMatch(resultMarkup, /ga-modal-backdrop/);
assert.doesNotMatch(resultMarkup, /role="dialog"/);
assert.match(resultMarkup, /Show in chat/);
nodes.findLast(node => node.type === 'button' && node.props.children === 'Open gallery').props.onClick();
assert.equal(opened, true);
let posted;
globalThis.fetch = async (url, options) => {
  posted = { url, body: JSON.parse(options.body), credentials: options.credentials };
  return new Response(JSON.stringify({ ok: true }), { headers: { 'Content-Type': 'application/json' } });
};
let shown = 0;
const showMarkup = renderToStaticMarkup(React.createElement(I18nProvider, null,
  React.createElement(ToastProvider, null, React.createElement(ShowPhotoButton,
    { filename: 'own-photo.png', onShown: () => { shown++; } }))));
assert.match(showMarkup, /Show in chat/);
await nodes.findLast(node => node.type === 'button' && node.props.children === 'Show in chat').props.onClick();
assert.deepEqual(posted, { url: '/play/say', body: { photo_filename: 'own-photo.png' }, credentials: 'same-origin' });
assert.equal(shown, 1);
globalThis.fetch = async () => new Response(JSON.stringify({ detail: 'Photo not found' }), { status: 404 });
await nodes.findLast(node => node.type === 'button' && node.props.children === 'Show in chat').props.onClick();
assert.equal(shown, 1, 'a rejected show never closes the result as if it succeeded');
console.log('photo dialog: PASS (ordinary/screenshot render and real submit handlers)');
