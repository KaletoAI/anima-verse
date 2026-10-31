/** Player furniture offers: one entry per action (and partner), a dropdown of
 * the pieces when several offer it (packages/player-ui/src/PropActionsPanel.tsx).
 * Usage: node scripts/smoke_prop_action_offer_menu.mjs
 *
 * Hand-derived from five offers: "Sit" on stool A (3.0 m), stool B (1.2 m) and
 * the bench (0.5 m, blocked: presence_not_met); "Read" on the armchair
 * (2.0 m); pair "Cuddle" on the sofa (4.0 m) with Mia enabled and Ben blocked.
 * a. Four entries in offer order: Sit (a select), Read, Cuddle · Mia,
 *    Cuddle · Ben (buttons).
 * b. The Sit select lists usable pieces nearest first, the blocked one last:
 *    "Wooden Stool · 1.2 m", "Wooden Stool · 3.0 m",
 *    "Bench · 0.5 m — reason:presence_not_met" (disabled); its placeholder
 *    reads "Sit ▾". Choosing option 0 picks stool B; the blocked one picks nothing.
 * c. A single piece is a button naming it: "Read · Armchair · 2.0 m"; without
 *    a distance only the name; nameProps false leaves the name out ("Read").
 * d. Cuddle · Ben is disabled with the reason as hover text.
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
runInNewContext(ts.transpileModule(source, { compilerOptions: {
  target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
} }).outputText, { module, exports: module.exports, require: id => ({
  react: { useState: value => [value, () => {}] },
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
];
const picks = [];
const tree = PropActionOffers({ offers, onPick: (o, partner) => picks.push([o.placement_id, partner]) });
const entries = Array.from(tree.props.children);
assert.equal(entries.length, 4);
const controls = entries.map(hint => hint.props.children);
assert.deepEqual(controls.map(c => c.type), ['select', 'button', 'button', 'button']);
assert.deepEqual(controls.slice(1).map(text), ['Read · Armchair · 2.0 m', 'Cuddle · Mia · Sofa · 4.0 m', 'Cuddle · Ben · Sofa · 4.0 m']);
console.log('PASS a: one entry per action and partner, a select for several pieces');

const [select] = controls;
const options = Array.from(nodes(select)).filter(n => n.type === 'option');
assert.equal(text(options[0]), 'Sit ▾');
assert.deepEqual(options.slice(1).map(text),
  ['Wooden Stool · 1.2 m', 'Wooden Stool · 3.0 m', 'Bench · 0.5 m — reason:presence_not_met']);
assert.deepEqual(options.slice(1).map(o => o.props.disabled), [false, false, true]);
select.props.onChange({ target: { value: '0' } });
select.props.onChange({ target: { value: '2' } });
assert.deepEqual(picks, [['b', undefined]]);
console.log('PASS b: usable pieces nearest first, the blocked one last and inert');

const single = PropActionOffers({ offers: [offer('Read', 'Armchair', 'd', null)], onPick() {} });
assert.equal(text(single.props.children[0].props.children), 'Read · Armchair');
const bare = PropActionOffers({ offers: [offer('Read', 'Armchair', 'd', 2.0)], nameProps: false, onPick() {} });
assert.equal(text(bare.props.children[0].props.children), 'Read');
console.log('PASS c: a single piece is named on its button, unless the menu belongs to it');

const ben = entries[3];
assert.equal(ben.props.text, 'reason:presence_not_met');
assert.equal(ben.props.children.props.disabled, true);
assert.equal(entries[2].props.text, undefined);
console.log('PASS d: a blocked partner keeps its reason as hover text');
