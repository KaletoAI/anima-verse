// Usage: node packages/player-ui/photoBackground.test.mjs
// Execute the real submit/push-notice code with a small React hook dispatcher.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { resolve } from 'node:path';
import ts from 'typescript';
import React from 'react';
const require = createRequire(import.meta.url);
const state = [], effects = [], toasts = [];
let cursor = 0, polled = null;
const hooks = {
  useState(initial) { const i = cursor++; if (!(i in state)) state[i] = typeof initial === 'function' ? initial() : initial;
    return [state[i], next => { state[i] = typeof next === 'function' ? next(state[i]) : next; }]; },
  useSyncExternalStore(_subscribe, get) { return get(); },
  useRef(initial) { return this.useState(() => ({ current: initial }))[0]; },
  useEffect(fn) { effects.push(fn); }, useCallback(fn) { return fn; }, useMemo(fn) { return fn(); },
};
function load(name) {
  const path = resolve(`packages/player-ui/src/${name}.tsx`);
  const code = ts.transpileModule(readFileSync(path, 'utf8'), { fileName: path, compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
  }}).outputText;
  const m = { exports: {} };
  new Function('require', 'module', 'exports', code)(id => {
    if (!id.startsWith('.')) return require(id);
    if (id === './I18nProvider') return { useI18n: () => ({ t: x => x }) };
    if (id === './Toast') return { useToast: () => ({ toast: (msg, kind) => toasts.push({ msg, kind }) }) };
    if (id === './api') return {
      apiPost: async (url, body) => { requests.push({ url, body }); if (rejection) throw new Error(rejection);
        return url.endsWith('/prepare') ? { ok: true, prompt: 'A photo', subjects: ['Bob'], present: ['Bob'] }
          : { status: 'accepted', photo_id: 'id-1', discovered_by: ['Bob'] }; },
      apiGet() {}, ApiError: Error,
    };
    if (id === './usePolling') return { usePoll: () => ({ data: polled }) };
    if (id === './syncEndpoints') return { SYNC_ENDPOINTS: { notices: {} } };
    if (id === './useQueue') return { useQueue: () => ({ agentActivity: [] }) };
    if (id === './Lightbox') return { useLightbox: () => ({ open() {} }) };
    if (id === './ZoomButton') return { useEnlarge: () => () => ({}) };
    if (id === './propActions') return { onPropActionChanged: () => () => {} };
    if (id === './ShowPhotoButton') return { PhotoReadyActions: ({ filename }) => React.createElement('button', { 'data-file': filename }, 'Show in chat') };
    return new Proxy({}, { get: () => () => null });
  }, m, m.exports);
  return m.exports;
}
function render(Component, props) {
  const dispatcher = React.__SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED.ReactCurrentDispatcher;
  const previous = dispatcher.current; cursor = 0; effects.length = 0; dispatcher.current = hooks;
  try { return Component(props); } finally { dispatcher.current = previous; }
}
function find(node, predicate) {
  if (!node || typeof node !== 'object') return null;
  if (Array.isArray(node)) return node.map(n => find(n, predicate)).find(Boolean) ?? null;
  if (predicate(node)) return node;
  return find(node.props?.children, predicate);
}
const requests = []; let rejection = '', control;
const { ScenePanel } = load('ScenePanel');
const props = { data: { capability_actions: { scene_photo: 'camera' } }, avatar: 'Ann',
  hasCapability: () => true, refreshScene: async () => {}, onEnterRoom() {},
  photoDialog: ctl => { control = ctl; return React.createElement('div', { role: 'dialog' }); } };
let tree = render(ScenePanel, props);
await find(tree, n => n.type === 'button' && n.props.children === '📷').props.onClick();
tree = render(ScenePanel, props);
assert.ok(find(tree, n => n.props?.role === 'dialog'));
await control.onSubmit({ prompt: 'A photo', secret: true });
tree = render(ScenePanel, props);
assert.equal(find(tree, n => n.props?.role === 'dialog'), null, '202 closes the dialog');
assert.match(toasts.at(-1).msg, /Rendering photo….*Bob noticed!/);
assert.equal(requests.at(-1).body.secret, true);
// Up-front validation stays inside the dialog for retry.
await find(tree, n => n.type === 'button' && n.props.children === '📷').props.onClick();
render(ScenePanel, props); rejection = 'Invalid LoRA';
await control.onSubmit({ prompt: 'A photo' });
render(ScenePanel, props);
assert.equal(control.error, 'Invalid LoRA');
rejection = '';
// Notices remain outside the scene dock, so idle-chat hiding cannot lose results.
state.length = 0;
const { NoticeBanner } = load('NoticeBanner');
polled = { avatar: 'Ann', events: [], leave_blocked: null, force_warning: null, unread_count: 1,
  notifications: [{ id: 'n1', kind: 'scene_photo', body: 'Photo ready',
    photo: { photo_id: 'id-1', status: 'ready', filename: 'photo.png', url: '/characters/Ann/images/photo.png' } }] };
let opened = 0;
render(NoticeBanner, { onOpenGallery: () => { opened++; } }); effects.forEach(fn => fn());
tree = render(NoticeBanner, { onOpenGallery: () => { opened++; } });
assert.ok(find(tree, n => n.props?.role === 'status'));
assert.ok(find(tree, n => n.props?.filename === 'photo.png'), 'completion exposes ShowPhotoButton');
assert.equal(find(tree, n => n.props?.role === 'dialog' || n.props?.className === 'ga-modal-backdrop'), null);
find(tree, n => n.props?.filename === 'photo.png').props.onOpenGallery();
assert.equal(opened, 1);
polled = { ...polled, notifications: [{ id: 'n2', kind: 'scene_photo', body: 'Generation failed.',
  photo: { photo_id: 'id-2', status: 'failed' } }] };
render(NoticeBanner, {}); effects.forEach(fn => fn());
tree = render(NoticeBanner, {});
assert.ok(find(tree, n => n.props?.role === 'alert'));
assert.equal(find(tree, n => n.props?.filename), null);
console.log('photo background: PASS (accept/close, rendering/discovery toast, inline validation, ready actions, error notice)');
