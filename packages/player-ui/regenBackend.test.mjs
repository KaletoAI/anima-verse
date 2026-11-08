// Usage: node packages/player-ui/regenBackend.test.mjs
// Exercise the shared picker and both actual panel submit handlers.
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import ts from 'typescript';
import React from 'react';
const require = createRequire(import.meta.url);
const cache = new Map(), requests = [];
let portal, control;
const options = { resolved: 'A', pose_check: { supported: true, default: true }, options: [
  { name: 'A', has_loras: true, lora_options: [{ name: 'style-a' }, { name: 'shared' }] },
  { name: 'B', has_loras: true, lora_options: [{ name: 'style-b' }, { name: 'shared' }] },
] };
// The animate dialog's "video" occasion: VidL takes LoRAs, VidN none.
const videoOptions = { resolved: 'VidL', options: [
  { name: 'VidL', has_loras: true, lora_options: [{ name: 'motion-l' }] },
  { name: 'VidN' },
] };
const image = { name: 'photo.png', url: '/photo.png', info: { prompt: 'Source prompt' } };
const galleries = { avatar: 'Ann', galleries: [{ character: 'Ann', is_self: true }] };
const gallery = { avatar: 'Ann', character: 'Ann', images: [image] };
const feed = { posts: [{ id: 'p1', image_filename: 'photo.png', image_meta: { prompt: 'Source prompt' }, agent_name: 'Ann', caption: '' }] };
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
    if (id === './api') return { ApiError: Error, apiGet: async url => {
      requests.push({ url });
      return url.startsWith('/world/imagegen-options') ? (url.includes('occasion=video') ? videoOptions : options) : {};
    }, apiPost: async (url, body) => {
      requests.push({ url, body });
      if (url === '/world/imagegen-enhance-prompt') return { prompt: 'Improved motion' };
      return url.endsWith('/detect-characters') ? { detected: ['Ann'], available: [{ name: 'Ann' }] } : {};
    } };
    if (id === './usePolling') return { usePoll: key => ({ data: key === 'play-galleries' ? galleries
      : key.startsWith('play-gallery:') ? gallery : feed, refresh: async () => {} }) };
    if (id === './clockSettings') return { clockSettings: () => ({}), useClockSettings() {} };
    if (id === './useQueue') return { useQueue: () => ({ agentActivity: [] }) };
    if (id === './Lightbox') return { useLightbox: () => ({ open() {} }) };
    if (id === './ZoomButton') return { useEnlarge: () => () => ({}) };
    if (id === './propActions') return { onPropActionChanged: () => () => {} };
    if (['./SceneView', './ScenesRecap', './GiftPicker', './ChatGalleryPicker', './PropActionsPanel'].includes(id)) return new Proxy({}, { get: () => () => null });
    if (id === './thumbs') return { thumbWidth: n => n, thumbUrl: url => url, transparentPortraitUrl: url => url };
    if (!['./PlayerRegenDialog', './PlayerAnimateDialog', './ImageBackendPicker', './useImageBackendPicker', './PromptImprover', './playerDialogPayloads'].includes(id)) {
      return new Proxy({}, { get: () => () => null });
    }
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
globalThis.window = { addEventListener() {}, removeEventListener() {}, setInterval() {}, clearInterval() {} };
const { PlayerRegenDialog } = load(resolve('packages/player-ui/src/PlayerRegenDialog.tsx'));
const { ImageBackendPicker } = load(resolve('packages/player-ui/src/ImageBackendPicker.tsx'));
const { GalleryPanel } = load(resolve('packages/player-ui/src/GalleryPanel.tsx'));
const { InstagramPanel } = load(resolve('packages/player-ui/src/InstagramPanel.tsx'));
const flush = async () => { await new Promise(resolve => setImmediate(resolve)); };
const all = (node, predicate) => {
  if (!node || typeof node !== 'object') return [];
  if (Array.isArray(node)) return node.flatMap(n => all(n, predicate));
  return [...(predicate(node) ? [node] : []), ...all(node.props?.children, predicate)];
};
const btn = (tree, title) => find(tree, n => n.type === 'button' && n.props.title === title);
const renderPicker = tree => {
  const node = find(tree, n => n.type === ImageBackendPicker);
  assert.ok(node, 'both dialogs must use the shared picker');
  return instance(ImageBackendPicker)(node.props);
};
for (const surface of ['gallery', 'instagram']) {
  const panel = instance(surface === 'gallery' ? GalleryPanel : InstagramPanel);
  const props = surface === 'gallery' ? { regenDialog: ctl => { control = ctl; return null; } }
    : { imageGenDialog: ctl => { control = ctl; return null; } };
  panel(props); panel(props); let tree = panel(props);
  if (surface === 'gallery') {
    btn(tree, 'photo.png').props.onClick(); tree = panel(props);
  }
  await btn(tree, 'Regenerate image').props.onClick(); panel(props);
  assert.ok(control);
  const dialog = instance(PlayerRegenDialog);
  const draw = () => dialog({ ctl: control });
  tree = draw(); await flush(); tree = draw(); tree = draw();
  assert.equal(requests.filter(r => r.url === '/world/imagegen-options?occasion=regenerate').length,
    surface === 'gallery' ? 1 : 2, 'one options request per dialog, also supplies pose-check defaults');
  let picker = renderPicker(tree);
  let selects = all(picker, n => n.type === 'select');
  assert.equal(selects.length, 5, 'backend plus four LoRA slots');
  assert.equal(selects[0].props.value, '', 'Auto is preselected');
  selects[1].props.onChange({ target: { value: 'style-a' } }); tree = draw();
  await tree.props.onSubmit();
  let posted = requests.at(-1);
  assert.match(posted.url, surface === 'gallery' ? /characters\/Ann\/images\/photo.png\/regenerate/ : /instagram\/post\/p1\/regenerate/);
  assert.equal(Object.hasOwn(posted.body, 'backend'), false);
  assert.deepEqual(posted.body.loras, [{ name: 'style-a', strength: 1 }], 'Auto sends no backend but keeps the auto-scoped LoRA pick');
  selects[0].props.onChange({ target: { value: 'A' } }); tree = draw();
  picker = renderPicker(tree); selects = all(picker, n => n.type === 'select');
  selects[1].props.onChange({ target: { value: 'style-a' } }); tree = draw();
  await tree.props.onSubmit(); posted = requests.at(-1);
  assert.equal(posted.body.backend, 'A');
  assert.deepEqual(posted.body.loras, [{ name: 'style-a', strength: 1 }]);
  assert.equal(posted.body.pose_check, true);
  selects[0].props.onChange({ target: { value: 'B' } }); tree = draw(); tree = draw();
  picker = renderPicker(tree); selects = all(picker, n => n.type === 'select');
  assert.equal(selects[1].props.value, '', 'backend switch clears unknown picks');
  assert.ok(find(picker, n => n.type === 'option' && n.props.value === 'style-b'));
  assert.equal(find(picker, n => n.type === 'option' && n.props.value === 'style-a'), null);
  selects[1].props.onChange({ target: { value: 'style-b' } }); tree = draw();
  all(renderPicker(tree), n => n.type === 'input' && n.props.type === 'number')[0].props.onChange({ target: { value: '0.65' } });
  tree = draw(); await tree.props.onSubmit();
  assert.deepEqual(requests.at(-1).body.loras, [{ name: 'style-b', strength: 0.65 }]);
}
{
  // Animate dialog: the same picker on the "video" occasion + the improver in video mode.
  const { PlayerAnimateDialog } = load(resolve('packages/player-ui/src/PlayerAnimateDialog.tsx'));
  const { PromptImprover } = load(resolve('packages/player-ui/src/PromptImprover.tsx'));
  const submitted = [];
  const suggested = [];
  const ctl = { prompt: 'She waves', sourceImageUrl: '', hasVideo: false,
    onSuggest: async opts => { suggested.push(opts); return 'x'; },
    onSubmit: payload => { submitted.push(payload); }, onClose() {} };
  const dialog = instance(PlayerAnimateDialog);
  const draw = () => dialog({ ctl });
  let tree = draw(); await flush(); tree = draw(); tree = draw();
  assert.equal(requests.filter(r => r.url === '/world/imagegen-options?occasion=video').length, 1);
  const improverNode = find(tree, n => n.type === PromptImprover);
  assert.equal(improverNode?.props.media, 'video');
  const improver = instance(PromptImprover);
  let imp = improver(improverNode.props);
  find(imp, n => n.type === 'input').props.onChange({ target: { value: 'slower' } });
  imp = improver(improverNode.props);
  btn(imp, 'Rewrite the prompt with this change via LLM').props.onClick(); await flush();
  assert.deepEqual(requests.at(-1), { url: '/world/imagegen-enhance-prompt',
    body: { prompt: 'She waves', improvement_request: 'slower', mode: 'video' } });
  tree = draw();
  let picker = renderPicker(tree);
  let selects = all(picker, n => n.type === 'select');
  assert.equal(selects.length, 5, 'Auto resolves to VidL: backend plus four LoRA slots');
  assert.match(find(selects[0], n => n.type === 'option' && n.props.value === '').props.children, /Auto \(routing\) → VidL/);
  selects[0].props.onChange({ target: { value: 'VidN' } }); tree = draw(); tree = draw();
  selects = all(renderPicker(tree), n => n.type === 'select');
  assert.equal(selects.length, 1, 'a backend without LoRAs hides the slots');
  selects[0].props.onChange({ target: { value: 'VidL' } }); tree = draw(); tree = draw();
  selects = all(renderPicker(tree), n => n.type === 'select');
  selects[1].props.onChange({ target: { value: 'motion-l' } }); tree = draw();
  await tree.props.onSubmit();
  assert.deepEqual(submitted.at(-1), { prompt: 'Improved motion', service: 'VidL', loras: [{ name: 'motion-l', strength: 1 }] });
  selects[0].props.onChange({ target: { value: '' } }); tree = draw(); tree = draw();
  await tree.props.onSubmit();
  assert.deepEqual(submitted.at(-1), { prompt: 'Improved motion', loras: [{ name: 'motion-l', strength: 1 }] },
    'Auto sends no service but keeps the auto-scoped LoRA pick');
  // "Suggest" asks with the system prompt only: the LLM is the routed one
  // (no per-call LLM pick — the field it once sent was never used).
  await find(draw(), n => n.type === 'button' && n.props.children === 'Suggest').props.onClick(); await flush();
  assert.deepEqual(suggested, [{ system_prompt: '' }]);
}
console.log('animate dialog: PASS (video picker, LoRA slots per backend, improver in video mode, service/loras payload)');
console.log('regenerate backend: PASS (shared picker, four scoped slots, Auto, explicit payloads through gallery + Instagram)');
