/** Every pair furniture action offers both beginnings — "Ask" and "Just do
 * it" — and the requester picks one per request
 * (packages/player-ui/src/PropActionsPanel.tsx, PropActionOffers: the one
 * offer menu of the panel, the browser HUD's place menu and the native HUD).
 * Usage: node scripts/smoke_prop_action_consent_choice.mjs
 *
 * Hand-derived; t() is the identity. Offers: "Sit" (solo) on "Chair" 1.0 m,
 * "Hug" (pair, partner Kira usable) on "Sofa" 2.5 m.
 * a. The panel's menu (no partner): chips "Sit" and "With Kira ▸ 1".
 * b. Kira's menu (partner Kira): ONE chip "Hug ▸" — a pair chip opens its
 *    row even for a single piece; clicking it picks nothing yet.
 * c. Hug's row open, place menu (nameProps false): "Hug · Kira:" with the
 *    buttons "Ask" and "Just do it" (plus the row's close button);
 *    "Ask" picks (Hug, Kira, "ask"), "Just do it" picks (Hug, Kira, "react").
 * d. The same row in the panel (nameProps true): "Sofa · 2.5 m · Ask" and
 *    "Sofa · 2.5 m · Just do it".
 * e. A solo chip still picks at once, without a consent: (Sit, undefined,
 *    undefined).
 * f. requestPropAction sends `consent` only for a pair "react"; "ask" is the
 *    server default and stays off the wire.
 */
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFile } from 'node:fs/promises';
import { runInNewContext } from 'node:vm';
const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const ts = require('typescript');
const jsx = (type, props) => ({ type, props });
const load = async (file, imports) => {
  const module = { exports: {} };
  const source = await readFile(new URL(file, import.meta.url), 'utf8');
  runInNewContext(ts.transpileModule(source, { compilerOptions: {
    target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText, { module, exports: module.exports, require: id => imports[id] ?? (() => { throw new Error(`Unexpected import ${id}`) })() });
  return module.exports;
};
// useState returns the preset values in call order (openPartner, openAction).
let preset = [];
const { PropActionOffers } = await load('../packages/player-ui/src/PropActionsPanel.tsx', {
  react: { useState: initial => [preset.length ? preset.shift() : initial, () => {}] },
  'react/jsx-runtime': { jsx, jsxs: jsx, Fragment: 'fragment' },
  './api': { apiPost() {} }, './HoverHint': { HoverHint() {} },
  './I18nProvider': { useI18n: () => ({ t: text => text }) },
  './propActionReasons': { propActionReason: reason => reason }, './usePropActions': {},
  './propActions': { cancelPropAction() {}, respondPropAction() {}, notifyPropActionChanged() {}, requestPropAction() {} },
});

const nodes = tree => Array.isArray(tree) ? tree.flatMap(nodes)
  : tree && typeof tree === 'object' ? [tree, ...nodes(tree.props?.children)] : [];
const text = tree => Array.isArray(tree) ? tree.map(text).join('')
  : tree && typeof tree === 'object' ? text(tree.props?.children) : tree == null || tree === false ? '' : String(tree);
const target = { location_id: 'l', room_id: 'r', placement_id: 'p', variant_uid: 'v' };
const sit = { prop_label: 'Chair', distance_m: 1, action_id: 'sit', definition_revision: 'r1', target, label: 'Sit',
  enabled: true, reason: '', required_partner: false, available_targets: [] };
const hug = { prop_label: 'Sofa', distance_m: 2.5, action_id: 'hug', definition_revision: 'r1', target, label: 'Hug',
  enabled: false, reason: 'partner_required', required_partner: true, available_targets: [{ partner: 'Kira', enabled: true, reason: '' }] };
const picks = [];
const render = (props, state = []) => {
  preset = [...state];
  const all = nodes(PropActionOffers({ offers: [sit, hug], onPick: (...args) => picks.push(args), ...props }));
  const buttons = all.filter(n => n.type === 'button');
  return { all, buttons, names: buttons.map(text) };
};
const named = (view, name) => view.buttons.find(button => text(button) === name);

// a.
assert.deepEqual(render({}).names, ['Sit', 'With Kira ▸ 1']);
// b.
let view = render({ partner: 'Kira' });
assert.deepEqual(view.names, ['Hug ▸']);
named(view, 'Hug ▸').props.onClick();
assert.equal(picks.length, 0);
// c.
const hugKey = JSON.stringify(['Hug', 'Kira']);
view = render({ partner: 'Kira', nameProps: false }, ['', hugKey]);
assert.deepEqual(view.names, ['Hug ▸', 'Ask', 'Just do it', '✕']);
assert(view.all.some(node => node.type === 'span' && text(node) === 'Hug · Kira:'));
named(view, 'Ask').props.onClick();
named(view, 'Just do it').props.onClick();
assert.deepEqual(picks.map(([offer, partner, consent]) => [offer.label, partner, consent]),
  [['Hug', 'Kira', 'ask'], ['Hug', 'Kira', 'react']]);
// d.
view = render({ partner: 'Kira' }, ['', hugKey]);
assert.deepEqual(view.names.slice(1, 3), ['Sofa · 2.5 m · Ask', 'Sofa · 2.5 m · Just do it']);
// e.
picks.length = 0;
named(render({}), 'Sit').props.onClick();
assert.deepEqual(picks.map(([offer, partner, consent]) => [offer.label, partner, consent]), [['Sit', undefined, undefined]]);

// f. The wire format.
const bodies = [];
const source = await readFile(new URL('../packages/player-ui/src/propActions.ts', import.meta.url), 'utf8');
const body = source.match(/export function requestPropAction[\s\S]*?mutate\('\/play\/prop-actions\/request', ([\s\S]*?)\)\n\}/)[1];
const build = new Function('actionId', 'target', 'revision', 'partner', 'consent', `return ${body}`);
bodies.push(build('hug', target, 'r1', 'Kira', 'react'), build('hug', target, 'r1', 'Kira', 'ask'), build('sit', target, 'r1'));
assert.equal(bodies[0].consent, 'react');
assert(!('consent' in bodies[1]) && !('consent' in bodies[2]));
console.log('prop action consent choice: PASS (pair chip opens, Ask/Just do it pick ask/react, solo picks at once, react only on the wire)');
