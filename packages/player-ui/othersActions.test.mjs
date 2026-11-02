// Usage: node --test packages/player-ui/othersActions.test.mjs
// Catch missing/reordered standing chips, lost busy/Stop behavior, empty sections,
// and wrong pair request payloads by rendering the real card and shared offers.
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import test from 'node:test';
import ts from 'typescript';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const require = createRequire(import.meta.url);
const cache = new Map();
const nodes = [];
let others;
let refreshes = 0;
const refresh = async () => { refreshes++; };
function load(path) {
  if (cache.has(path)) return cache.get(path).exports;
  const module = { exports: {} };
  cache.set(path, module);
  const code = ts.transpileModule(readFileSync(path, 'utf8'), { fileName: path, compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
    jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
  }}).outputText;
  new Function('require', 'module', 'exports', code)(specifier => {
    // Polling is the scene-data boundary; HTTP actions and components stay real.
    if (specifier === './usePolling') return { usePoll: key => ({
      data: key === 'play-others' ? others : null, error: null, refresh,
    }) };
    if (specifier.endsWith('.css')) return {};
    if (specifier === 'react/jsx-runtime') {
      const runtime = require(specifier);
      return Object.fromEntries(Object.entries(runtime).map(([name, value]) => [name,
        name === 'jsx' || name === 'jsxs' ? (...args) => {
          const node = value(...args); nodes.push(node); return node;
        } : value]));
    }
    if (!specifier.startsWith('.')) return require(specifier);
    const base = resolve(dirname(path), specifier);
    const target = [base + '.ts', base + '.tsx'].find(existsSync);
    assert.ok(target, specifier);
    return load(target);
  }, module, module.exports);
  return module.exports;
}
const { OthersPanel } = load(resolve('packages/player-ui/src/OthersPanel.tsx'));
const { I18nProvider } = load(resolve('packages/player-ui/src/I18nProvider.tsx'));
const { PropActionsPanel } = load(resolve('packages/player-ui/src/PropActionsPanel.tsx'));
const propApi = load(resolve('packages/player-ui/src/propActions.ts'));
const render = tree => renderToStaticMarkup(React.createElement(I18nProvider, null, tree));
const text = node => Array.isArray(node) ? node.map(text).join('')
  : node && typeof node === 'object' ? text(node.props?.children)
    : node == null || node === false ? '' : String(node);
const descendants = node => Array.isArray(node) ? node.flatMap(descendants)
  : node && typeof node === 'object' ? [node, ...descendants(node.props?.children)] : [];
const buttons = node => descendants(node).filter(node => node.type === 'button');
const target = { location_id: 'house', room_id: 'lounge', placement_id: 'sofa', variant_uid: 'green' };
const offer = {
  action_id: 'rest', definition_revision: 'rev-7', placement_id: 'sofa', variant_uid: 'green', target,
  label: 'Rest', description: '', prop_label: 'Sofa', distance_m: 1.5, enabled: true, reason: '',
  required_partner: true, available_targets: [{ partner: 'Kira', enabled: true, reason: '' }], effects: [],
};
const poses = [{ key: 'hug', kind: 'hug', label: 'Hug' }, { key: 'pair_bow', kind: 'bow', label: '' }];
const character = { name: 'Kira', mood: '', activity: '', status_effects: {}, bar_meta: {}, conditions: [], profile_image: '' };
const emptyState = { incoming: [], outgoing: [], current: [], recent_results: [] };
globalThis.window = Object.assign(new EventTarget(), {
  location: { href: 'http://localhost/?lang=en' },
  localStorage: { getItem: () => null }, navigator: { language: 'en' },
});

// Like photoDialog.test.mjs, run root effects/state without a browser DOM, then
// use React SSR for all real descendants. No production-only test entry point.
async function mount({ pairPoses = poses, offers = [offer], interaction = null, rejectInvite = false } = {}) {
  others = { avatar: 'Player', characters: [{ ...character, interaction }] };
  propApi.setPropActionHost(true);
  propApi.publishHostedPropActions({ offers, state: emptyState });
  const requests = [];
  const savedFetch = globalThis.fetch;
  globalThis.fetch = async (url, options = {}) => {
    requests.push({ url, body: options.body && JSON.parse(options.body) });
    const payload = url === '/play/interact/options' ? { poses: pairPoses }
      : rejectInvite && url === '/play/interact' ? { detail: 'Kira is in another room' } : { ok: true };
    return new Response(JSON.stringify(payload), { status: rejectInvite && url === '/play/interact' ? 409 : 200 });
  };
  const state = [], effectDeps = [], pending = [], cleanup = [];
  let cursor = 0;
  const hooks = {
    useState(initial) {
      const index = cursor++;
      if (!(index in state)) state[index] = typeof initial === 'function' ? initial() : initial;
      return [state[index], next => { state[index] = typeof next === 'function' ? next(state[index]) : next; }];
    },
    useRef(initial) { return this.useState(() => ({ current: initial }))[0]; },
    useContext() { return { lang: 'en', t: source => source }; },
    useEffect(fn, deps) {
      const index = cursor++;
      if (!effectDeps[index] || deps.some((dep, i) => dep !== effectDeps[index][i])) {
        effectDeps[index] = deps;
        pending.push(fn);
      }
    },
    useCallback(fn) { return fn; },
  };
  const dispatcher = React.__SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED.ReactCurrentDispatcher;
  const draw = () => {
    nodes.length = 0;
    cursor = 0;
    const previous = dispatcher.current;
    let tree;
    dispatcher.current = hooks;
    try { tree = OthersPanel(); } finally { dispatcher.current = previous; }
    return render(tree);
  };
  draw();
  for (const effect of pending.splice(0)) cleanup.push(effect());
  await new Promise(resolve => setImmediate(resolve));
  return { requests, draw, dispose() {
    for (const off of cleanup) off?.();
    globalThis.fetch = savedFetch;
    propApi.publishHostedPropActions(null);
    propApi.setPropActionHost(false);
  } };
}
function actionRow() {
  const row = nodes.find(node => node.type === 'div'
    && node.props.style?.flexWrap === 'wrap'
    && buttons(node).some(button => text(button) === 'Hug'));
  assert.ok(row, 'standing poses must render in an action chip row');
  return row;
}

test('card renders standing poses first in the furniture chip row and submits the exact pose', async () => {
  const card = await mount();
  try {
    const html = card.draw();
    assert.match(html, /<section aria-label="Actions"/);
    assert.match(html, /<strong>Actions<\/strong>/);
    assert.equal((html.match(/<section/g) || []).length, 1);
    assert.doesNotMatch(html, /Together…|Furniture actions|role="menu"/);
    const chips = buttons(actionRow());
    assert.deepEqual(chips.map(text), ['Hug', 'pair_bow', 'Rest ▸']);
    assert.ok(chips.every(chip => chip.props.className === 'player-chip'));
    assert.ok(chips.every(chip => !chip.props.disabled));
    await chips[1].props.onClick();
    assert.deepEqual(card.requests.filter(request => request.url === '/play/interact'),
      [{ url: '/play/interact', body: { partner: 'Kira', pose: 'pair_bow' } }]);
    assert.equal(card.requests.filter(request => request.url === '/play/interact/options').length, 1,
      'standing choices load without opening a menu and do not reload on redraw');
  } finally { card.dispose(); }
});

test('busy character keeps standing poses visible, disabled, with native-safe hints', async () => {
  const card = await mount({ interaction: { partner: 'Mira', pose_key: 'dance' } });
  try {
    const html = card.draw();
    const row = actionRow();
    assert.ok(buttons(row).slice(0, 2).every(button => button.props.disabled));
    assert.equal(descendants(row).filter(node => node.props?.text === 'Busy with someone else').length, 2);
    assert.equal((html.match(/data-hint="Busy with someone else"/g) || []).length, 2);
    assert.ok(buttons(row).slice(0, 2).every(button => button.props.style?.pointerEvents === 'none'));
  } finally { card.dispose(); }
});

test('avatar partner keeps Stop first in the combined row and ends the interaction', async () => {
  const card = await mount({ interaction: { partner: 'Player', pose_key: 'hug' } });
  try {
    card.draw();
    const chips = buttons(actionRow());
    assert.deepEqual(chips.map(text), ['Stop', 'Hug', 'pair_bow', 'Rest ▸']);
    assert.ok(chips.every(chip => !chip.props.disabled));
    await chips[0].props.onClick();
    assert.deepEqual(card.requests.at(-1), { url: '/play/interact/end', body: {} });
  } finally { card.dispose(); }
});

test('standing-only actions render even before a prop snapshot arrives', async () => {
  const card = await mount({ offers: [] });
  try {
    propApi.publishHostedPropActions(null);
    assert.match(card.draw(), /<section aria-label="Actions"/);
    assert.deepEqual(buttons(actionRow()).map(text), ['Hug', 'pair_bow']);
  } finally { card.dispose(); }
});

test('empty choices render no section, while furniture-only and self headings stay unchanged', async () => {
  const card = await mount({ pairPoses: [], offers: [] });
  try {
    assert.doesNotMatch(card.draw(), /<section|Together…|No two-person actions/);
    propApi.publishHostedPropActions({ offers: [offer], state: emptyState });
    assert.match(card.draw(), /<section aria-label="Furniture actions"/);
    assert.match(render(React.createElement(PropActionsPanel)), /<section aria-label="Furniture actions"/);
  } finally { card.dispose(); }
});

test('Stop remains available without any standing poses or furniture offers', async () => {
  const card = await mount({ pairPoses: [], offers: [], interaction: { partner: 'Player', pose_key: 'hug' } });
  try {
    assert.match(card.draw(), /<section aria-label="Actions"/);
    assert.ok(nodes.some(node => node.type === 'button' && text(node) === 'Stop'));
  } finally { card.dispose(); }
});

test('pair refusal is shown on the card and a new proposal clears the old note', async () => {
  const card = await mount({ rejectInvite: true });
  try {
    card.draw();
    const before = refreshes;
    await buttons(actionRow())[0].props.onClick();
    assert.match(card.draw(), /Kira is in another room/);
    assert.ok(refreshes > before);
    const nextProposal = buttons(actionRow())[0].props.onClick();
    assert.doesNotMatch(card.draw(), /Kira is in another room/);
    await nextProposal;
  } finally { card.dispose(); }
});
