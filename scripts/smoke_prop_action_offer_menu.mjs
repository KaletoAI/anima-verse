/** Player furniture offers, compact: a chip per action that carries only its
 * name; several pieces open a row of pieces, pair actions sit behind one chip
 * per partner (packages/player-ui/src/PropActionsPanel.tsx).
 * Usage: node scripts/smoke_prop_action_offer_menu.mjs
 *
 * Hand-derived from six offers: "Sit" on stool A (3.0 m), stool B (1.2 m) and
 * the bench (0.5 m, blocked: presence_not_met); "Read" on the armchair
 * (2.0 m); pair "Cuddle" on the sofa (4.0 m) with Mia enabled and Ben blocked;
 * pair "Dance" on the rug (1.0 m) with Mia enabled.
 * a. Top row, all buttons, no select: "Sit ▸", "Read", "With Mia ▸ 2",
 *    "With Ben ▸ 1". "Read" starts at once and names its piece as hover text
 *    ("Armchair · 2.0 m"); "Sit ▸" picks nothing, it opens a row.
 * b. That row reads "Sit:" then the pieces usable first, nearest first:
 *    "Wooden Stool · 1.2 m", "Wooden Stool · 3.0 m", "Bench · 0.5 m" (disabled,
 *    hover text reason:presence_not_met), then ✕. A click on stool B picks it.
 * c. "With Mia ▸ 2" opens a row "With Mia:" + "Cuddle", "Dance"; a click on
 *    "Dance" picks the rug with Mia. "With Ben ▸ 1" is disabled with the reason
 *    as hover text (the only action with Ben is blocked).
 * d. A menu that belongs to one partner (OthersPanel) shows that partner's actions as
 *    plain chips, no partner chip: partner Mia → "Cuddle", "Dance". The place
 *    menu (nameProps false) has no piece hover text.
 */
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFile } from 'node:fs/promises';
import { runInNewContext } from 'node:vm';
const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const ts = require('typescript');
const jsx = (type, props) => ({ type, props });
const source = await readFile(new URL('../packages/player-ui/src/PropActionsPanel.tsx', import.meta.url), 'utf8');
const module = { exports: {} };
const HoverHint = function HoverHint() {};
// useState in call order, kept across renders: a click sets it, the next render reads it.
let states = [], cursor = 0;
const useState = initial => {
  const i = cursor++;
  if (!(i in states)) states[i] = initial;
  return [states[i], value => { states[i] = value }];
};
runInNewContext(ts.transpileModule(source, { compilerOptions: {
  target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
} }).outputText, { module, exports: module.exports, require: id => ({
  react: { useState },
  'react/jsx-runtime': { jsx, jsxs: jsx, Fragment: 'fragment' },
  './api': {}, './HoverHint': { HoverHint }, './I18nProvider': { useI18n: () => ({ t: text => text }) },
  './propActionReasons': { propActionReason: reason => `reason:${reason}` },
  './usePropActions': {}, './propActions': {},
})[id] ?? (() => { throw new Error(`Unexpected import ${id}`) })() });
const { PropActionOffers } = module.exports;

const nodes = tree => Array.isArray(tree) ? tree.flatMap(nodes)
  : tree && typeof tree === 'object' ? [tree, ...nodes(tree.props?.children)] : [];
const text = tree => Array.isArray(tree) ? tree.map(text).join('')
  : tree && typeof tree === 'object' ? text(tree.props?.children) : tree == null || tree === false ? '' : String(tree);
const offer = (label, prop, placement, distance, extra = {}) => ({
  action_id: label, definition_revision: 'rev', placement_id: placement, variant_uid: 'v',
  prop_label: prop, distance_m: distance, target: { location_id: 'l', room_id: 'r', placement_id: placement, variant_uid: 'v' },
  label, description: '', enabled: true, reason: '', required_partner: false, available_targets: [], effects: [], ...extra });
const offers = [
  offer('Sit', 'Wooden Stool', 'a', 3.0), offer('Sit', 'Wooden Stool', 'b', 1.2),
  offer('Sit', 'Bench', 'c', 0.5, { enabled: false, reason: 'presence_not_met' }),
  offer('Read', 'Armchair', 'd', 2.0),
  offer('Cuddle', 'Sofa', 'e', 4.0, { required_partner: true, available_targets: [
    { partner: 'Mia', enabled: true, reason: '' }, { partner: 'Ben', enabled: false, reason: 'presence_not_met' }] }),
  offer('Dance', 'Rug', 'f', 1.0, { required_partner: true, available_targets: [{ partner: 'Mia', enabled: true, reason: '' }] }),
];
let picks = [];
const render = (props = {}) => { cursor = 0; return PropActionOffers({ offers, onPick: (o, p) => picks.push([o.placement_id, p]), ...props }) };
// A rendered row: [label text, [[button text, disabled, hover text], ...]] — hints wrap their button.
const rows = tree => tree.props.children.filter(Boolean).map(row => {
  const kids = nodes(row.props.children).filter(n => n.type === HoverHint || n.type === 'button' || n.type === 'span');
  const buttons = [];
  for (const n of kids) {
    if (n.type === HoverHint) buttons.push([text(n.props.children), !!n.props.children.props.disabled, n.props.text, n.props.children]);
    else if (n.type === 'button' && !buttons.some(b => b[3] === n)) buttons.push([text(n), !!n.props.disabled, undefined, n]);
  }
  const label = kids.find(n => n.type === 'span');
  return [label ? text(label) : '', buttons];
});
const click = (tree, name) => {
  const button = rows(tree).flatMap(([, b]) => b).find(b => b[0] === name);
  assert.ok(button, `no button ${name}`);
  button[3].props.onClick();
};

let tree = render();
assert.equal(nodes(tree).filter(n => n.type === 'select').length, 0);
let [top] = rows(tree);
assert.deepEqual(top[1].map(b => b[0]), ['Sit ▸', 'Read', 'With Mia ▸ 2', 'With Ben ▸ 1']);
assert.equal(top[1][1][2], 'Armchair · 2.0 m');
click(tree, 'Read');
assert.deepEqual(picks, [['d', undefined]]);
click(tree, 'Sit ▸');
assert.deepEqual(picks, [['d', undefined]]);
console.log('PASS a: one name-only chip per action, no select; a single piece starts at once');

tree = render();
let all = rows(tree);
assert.equal(all.length, 2);
assert.equal(all[1][0], 'Sit:');
assert.deepEqual(all[1][1].map(b => [b[0], b[1], b[2]]), [
  ['Wooden Stool · 1.2 m', false, undefined], ['Wooden Stool · 3.0 m', false, undefined],
  ['Bench · 0.5 m', true, 'reason:presence_not_met'], ['✕', false, undefined]]);
click(tree, 'Wooden Stool · 1.2 m');
assert.deepEqual(picks.at(-1), ['b', undefined]);
assert.equal(rows(render()).length, 1);
console.log('PASS b: several pieces open a row, usable and nearest first, the blocked one inert');

tree = render();
[top] = rows(tree);
assert.deepEqual(top[1][3].slice(1, 3), [true, 'reason:presence_not_met']);
click(tree, 'With Mia ▸ 2');
all = rows(render());
assert.equal(all[1][0], 'With Mia:');
assert.deepEqual(all[1][1].map(b => b[0]), ['Cuddle', 'Dance', '✕']);
click(render(), 'Dance');
assert.deepEqual(picks.at(-1), ['f', 'Mia']);
console.log('PASS c: pair actions sit behind one chip per partner');

states = [];
[top] = rows(render({ partner: 'Mia' }));
assert.deepEqual(top[1].map(b => b[0]), ['Cuddle', 'Dance']);
states = [];
const place = PropActionOffers({ offers: [offer('Read', 'Armchair', 'd', 2.0)], nameProps: false, onPick() {} });
assert.deepEqual(rows(place)[0][1].map(b => [b[0], b[2]]), [['Read', undefined]]);
console.log('PASS d: a partner\'s own menu lists that partner\'s actions; the place menu names no piece');
