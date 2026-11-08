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
 * c. "With Mia ▸ 2" opens a row "With Mia:" + "Cuddle ▸", "Dance ▸".
 *    "Dance ▸" opens "Dance · Mia:" with "Rug · 1.0 m · Ask" and
 *    "Rug · 1.0 m · Just do it"; only these pick the rug with Mia, carrying
 *    consent "ask" and "react" respectively. "With Ben ▸ 1" is disabled with
 *    the reason as hover text (the only action with Ben is blocked).
 * d. A menu that belongs to one partner (OthersPanel) shows that partner's actions as
 *    action chips, no partner chip: partner Mia → "Cuddle ▸", "Dance ▸".
 *    In a place menu (nameProps false), solo chips have no piece hover text
 *    and a one-piece pair row offers just "Ask" and "Just do it".
 * e. A GROUP action (G4, plan-gruppen-animationen.md): "Trio" for three on the
 *    bed (2.5 m), candidates Mia, Ben, Ola. The top row gains "Trio ▸"; it
 *    opens "Trio · choose 2:" with one chip per candidate and ✕, no Ask yet.
 *    Mia and Ben picked: Ola is disabled, Core's preflight is asked once with
 *    [Mia, Ben]; once it answers enabled the row offers "Bed · 2.5 m · Ask",
 *    which picks the bed with members [Mia, Ben] and consent "ask". A
 *    preflight refusal (roles_unfit) leaves "Ask" disabled with that reason.
 *    A partner's own menu shows no group action.
 * f. A group runs with fewer people than its clip has roles (2026-11-08): the
 *    picker asks for 2 up to the most any of its actions takes. The chat's
 *    action tree opens ONE picker per piece for all its group actions —
 *    here "Trio" (participants 3: at most 2 others, candidates Mia, Ben,
 *    Ola) and "Circle" (participants 5: at most 4, candidates Mia, Ben, Ola,
 *    Kai) on the bed, label "Group". Range 2 up to min(4 candidates, 4) = 4:
 *    "Group · choose 2–4:" with the chips Mia, Ben, Ola, Kai and ✕. Mia
 *    alone: no Ask, nothing checked. Mia + Ben: both actions are checked with
 *    [Mia, Ben]; then "Trio · Ask" and "Circle · Ask" (the action is named,
 *    the one piece is not). + Ola: Trio greyed with the hover text "Takes at
 *    most 2 others" and NOT checked; Circle checked once with [Mia, Ben, Ola]
 *    and usable. Kai stays pickable (3 < 4). The canvas menu's own picker for
 *    Circle alone reads "Circle · choose 2–4:" and asks with two people.
 * Design: 976efe70 (compact rows), a1c5af11 (per-request consent choices).
 */
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFile } from 'node:fs/promises';
import { runInNewContext } from 'node:vm';
const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const ts = require('typescript');
const jsx = (type, props) => ({ type, props });
// PropActionsPanel's one pure dependency, loaded for real (no React, no fetch).
const pieceModel = { exports: {} };
runInNewContext(ts.transpileModule(await readFile(new URL('../packages/player-ui/src/actionsTreeModel.ts', import.meta.url), 'utf8'),
  { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText,
  { module: pieceModel, exports: pieceModel.exports, require: () => ({}) });
const source = await readFile(new URL('../packages/player-ui/src/PropActionsPanel.tsx', import.meta.url), 'utf8');
const module = { exports: {} };
const HoverHint = function HoverHint() {};
// useState in call order, kept across renders: a click sets it, the next render reads it.
let states = [], cursor = 0;
const useState = initial => {
  const i = cursor++;
  if (!(i in states)) states[i] = initial;
  return [states[i], value => { states[i] = typeof value === 'function' ? value(states[i]) : value }];
};
// An effect runs when its deps changed since the last render at that position.
let effects = [];
const useEffect = (fn, deps) => {
  const i = cursor++;
  const key = JSON.stringify(deps);
  if (effects[i] !== key) { effects[i] = key; fn() }
};
let checks = [], verdict = { enabled: true, reason: '' };
const checkPropAction = (...args) => { checks.push(args); return Promise.resolve(verdict) };
runInNewContext(ts.transpileModule(source, { compilerOptions: {
  target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
} }).outputText, { module, exports: module.exports, require: id => ({
  react: { useState, useEffect },
  'react/jsx-runtime': { jsx, jsxs: jsx, Fragment: 'fragment' },
  './api': {}, './HoverHint': { HoverHint }, './I18nProvider': { useI18n: () => ({ t: text => text }) },
  './actionsTreeModel': pieceModel.exports,
  './propActionReasons': { propActionReason: reason => `reason:${reason}` },
  './usePropActions': {}, './propActions': { checkPropAction },
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
const render = (props = {}) => { cursor = 0; return PropActionOffers({ offers, onPick: (o, p, consent) => picks.push([o.placement_id, p, consent]), ...props }) };
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
  assert.equal(button[1], false, `cannot click disabled button ${name}`);
  button[3].props.onClick();
};

let tree = render();
assert.equal(nodes(tree).filter(n => n.type === 'select').length, 0);
let [top] = rows(tree);
assert.deepEqual(top[1].map(b => b[0]), ['Sit ▸', 'Read', 'With Mia ▸ 2', 'With Ben ▸ 1']);
assert.equal(top[1][1][2], 'Armchair · 2.0 m');
click(tree, 'Read');
assert.deepEqual(picks, [['d', undefined, undefined]]);
click(tree, 'Sit ▸');
assert.deepEqual(picks, [['d', undefined, undefined]]);
console.log('PASS a: one name-only chip per action, no select; a single piece starts at once');

tree = render();
let all = rows(tree);
assert.equal(all.length, 2);
assert.equal(all[1][0], 'Sit:');
assert.deepEqual(all[1][1].map(b => [b[0], b[1], b[2]]), [
  ['Wooden Stool · 1.2 m', false, undefined], ['Wooden Stool · 3.0 m', false, undefined],
  ['Bench · 0.5 m', true, 'reason:presence_not_met'], ['✕', false, undefined]]);
click(tree, 'Wooden Stool · 1.2 m');
assert.deepEqual(picks.at(-1), ['b', undefined, undefined]);
assert.equal(rows(render()).length, 1);
console.log('PASS b: several pieces open a row, usable and nearest first, the blocked one inert');

tree = render();
[top] = rows(tree);
assert.deepEqual(top[1][3].slice(1, 3), [true, 'reason:presence_not_met']);
click(tree, 'With Mia ▸ 2');
all = rows(render());
assert.equal(all[1][0], 'With Mia:');
assert.deepEqual(all[1][1].map(b => b[0]), ['Cuddle ▸', 'Dance ▸', '✕']);
assert.equal(picks.length, 2, 'opening the partner row requests nothing');
assert.equal(all[0][1][2][3].props['aria-expanded'], true);
assert.equal(all[1][1][1][3].props['aria-expanded'], false);
assert.equal(all[1][1][2][3].props['aria-label'], 'Close');
click(render(), 'Dance ▸');
all = rows(render());
assert.equal(picks.length, 2, 'even a one-piece pair action must wait for a consent choice');
assert.equal(all.length, 3);
assert.equal(all[1][1][1][3].props['aria-expanded'], true);
assert.equal(all[2][0], 'Dance · Mia:');
assert.deepEqual(all[2][1].map(b => [b[0], b[1], b[2]]), [
  ['Rug · 1.0 m · Ask', false, 'Ask Mia first'],
  ['Rug · 1.0 m · Just do it', false, 'Start at once; Mia reacts and may push you away'],
  ['✕', false, undefined],
]);
assert.equal(all[2][1][2][3].props['aria-label'], 'Close');
click(render(), 'Rug · 1.0 m · Ask');
assert.deepEqual(picks.at(-1), ['f', 'Mia', 'ask']);
assert.equal(rows(render()).length, 2, 'picking closes the piece row');
click(render(), 'Dance ▸');
click(render(), 'Rug · 1.0 m · Just do it');
assert.deepEqual(picks.at(-1), ['f', 'Mia', 'react']);
assert.equal(picks.length, 4);
console.log('PASS c: one chip per partner; pair actions open explicit Ask/Just do it choices');

states = [];
[top] = rows(render({ partner: 'Mia' }));
assert.deepEqual(top[1].map(b => b[0]), ['Cuddle ▸', 'Dance ▸']);
click(render({ partner: 'Mia' }), 'Cuddle ▸');
all = rows(render({ partner: 'Mia' }));
assert.equal(all[1][0], 'Cuddle · Mia:');
assert.deepEqual(all[1][1].map(b => b[0]), ['Sofa · 4.0 m · Ask', 'Sofa · 4.0 m · Just do it', '✕']);
states = [];
const place = render({ offers: [offer('Read', 'Armchair', 'd', 2.0)], nameProps: false });
assert.deepEqual(rows(place)[0][1].map(b => [b[0], b[2]]), [['Read', undefined]]);
states = [];
const placePair = { offers: [offers[5]], partner: 'Mia', nameProps: false };
click(render(placePair), 'Dance ▸');
assert.deepEqual(rows(render(placePair))[1][1].map(b => b[0]), ['Ask', 'Just do it', '✕']);
console.log('PASS d: a partner\'s own menu lists that partner\'s actions; the place menu names no piece');

// e. a group action: pick the people, then ask them on a piece
const trio = offer('Trio', 'Bed', 'g', 2.5, { participants: 3, required_partner: true, candidates: ['Mia', 'Ben', 'Ola'] });
const groupOffers = [offer('Read', 'Armchair', 'd', 2.0), trio];
const groupPicks = [];
states = []; effects = [];
const renderGroup = (props = {}) => {
  cursor = 0;
  const tree = PropActionOffers({ offers: groupOffers, onPick: (o, p, consent, members) => groupPicks.push([o.placement_id, p, consent, members]), ...props });
  const picker = nodes(tree).find(n => typeof n.type === 'function' && n.type.name === 'GroupPicker');
  return { tree, picker: picker ? picker.type(picker.props) : null };
};
const pickerRow = picker => rows({ props: { children: [picker] } })[0];
let view = renderGroup();
assert.deepEqual(rows(view.tree)[0][1].map(b => b[0]), ['Read', 'Trio ▸']);
assert.equal(view.picker, null);
click(view.tree, 'Trio ▸');
view = renderGroup();
let [label, buttons] = pickerRow(view.picker);
assert.equal(label, 'Trio · choose 2:');
assert.deepEqual(buttons.map(b => [b[0], b[1]]), [['Mia', false], ['Ben', false], ['Ola', false], ['✕', false]]);
buttons[0][3].props.onClick(); view = renderGroup();
pickerRow(view.picker)[1][1][3].props.onClick(); view = renderGroup();
// Arrays made inside the vm context: compared as JSON.
assert.equal(JSON.stringify(checks.map(c => c[3])), JSON.stringify([['Mia', 'Ben']]));
await Promise.resolve(); await Promise.resolve();
view = renderGroup();
[label, buttons] = pickerRow(view.picker);
assert.deepEqual(buttons.map(b => [b[0], b[1]]), [['Mia', false], ['Ben', false], ['Ola', true],
  ['Bed · 2.5 m · Ask', false], ['✕', false]]);
buttons[3][3].props.onClick();
assert.equal(JSON.stringify(groupPicks), JSON.stringify([['g', undefined, 'ask', ['Mia', 'Ben']]]));
states = []; effects = []; checks = []; verdict = { enabled: false, reason: 'roles_unfit' };
click(renderGroup().tree, 'Trio ▸');
view = renderGroup();
pickerRow(view.picker)[1][1][3].props.onClick(); view = renderGroup();
pickerRow(view.picker)[1][2][3].props.onClick(); view = renderGroup();
await Promise.resolve(); await Promise.resolve();
buttons = pickerRow(renderGroup().picker)[1];
assert.deepEqual(buttons.map(b => [b[0], b[1], b[2]]).slice(3), [
  ['Bed · 2.5 m · Ask', true, 'reason:roles_unfit'], ['✕', false, undefined]]);
assert.equal(checks.length, 1);
states = []; effects = [];
assert.deepEqual(rows(renderGroup({ partner: 'Mia' }).tree)[0][1].map(b => b[0]), []);
console.log('PASS e: a group action picks its people, waits for the preflight, then asks them');

// f. fewer people than roles; one picker for all group actions of a piece
const { GroupPicker } = module.exports;
const groupTrio = offer('Trio', 'Bed', 'g', 2.5, { participants: 3, required_partner: true, candidates: ['Mia', 'Ben', 'Ola'] });
const circle = offer('Circle', 'Bed', 'g', 2.5, { participants: 5, required_partner: true, candidates: ['Mia', 'Ben', 'Ola', 'Kai'] });
const pieceGroup = { key: 'group:g', label: 'Group', usable: true,
  entries: [groupTrio, circle].map(o => ({ offer: o, enabled: true, reason: '' })) };
const asked = [];
states = []; effects = []; checks = []; verdict = { enabled: true, reason: '' };
const renderPiece = (group = pieceGroup) => {
  cursor = 0;
  return pickerRow(GroupPicker({ group, busy: false, nameProps: false,
    onPick: (o, members) => asked.push([o.action_id, members]), onClose() {} }));
};
[label, buttons] = renderPiece();
assert.equal(label, 'Group · choose 2–4:');
assert.deepEqual(buttons.map(b => [b[0], b[1]]), [['Mia', false], ['Ben', false], ['Ola', false], ['Kai', false], ['✕', false]]);
buttons[0][3].props.onClick();
[, buttons] = renderPiece();
assert.deepEqual(buttons.map(b => b[0]), ['Mia', 'Ben', 'Ola', 'Kai', '✕'], 'one person: no Ask yet');
assert.equal(checks.length, 0);
buttons[1][3].props.onClick();
renderPiece();
assert.equal(JSON.stringify(checks.map(c => [c[0], c[3]])), JSON.stringify([['Trio', ['Mia', 'Ben']], ['Circle', ['Mia', 'Ben']]]));
await Promise.resolve(); await Promise.resolve();
[, buttons] = renderPiece();
assert.deepEqual(buttons.slice(4).map(b => [b[0], b[1]]), [['Trio · Ask', false], ['Circle · Ask', false], ['✕', false]]);
buttons[2][3].props.onClick();
checks = [];
renderPiece();
assert.equal(JSON.stringify(checks.map(c => [c[0], c[3]])), JSON.stringify([['Circle', ['Mia', 'Ben', 'Ola']]]));
await Promise.resolve(); await Promise.resolve();
[, buttons] = renderPiece();
assert.deepEqual(buttons.map(b => [b[0], b[1], b[2]]), [
  ['Mia', false, undefined], ['Ben', false, undefined], ['Ola', false, undefined], ['Kai', false, undefined],
  ['Trio · Ask', true, 'Takes at most 2 others'], ['Circle · Ask', false, 'Ask Mia, Ben, Ola first'], ['✕', false, undefined]]);
buttons[5][3].props.onClick();
assert.equal(JSON.stringify(asked), JSON.stringify([['Circle', ['Mia', 'Ben', 'Ola']]]));
states = []; effects = []; checks = [];
const circleOnly = { key: 'circle', label: 'Circle', usable: true, entries: [{ offer: circle, enabled: true, reason: '' }] };
[label, buttons] = renderPiece(circleOnly);
assert.equal(label, 'Circle · choose 2–4:');
buttons[3][3].props.onClick(); renderPiece(circleOnly);
buttons[0][3].props.onClick(); renderPiece(circleOnly);
await Promise.resolve(); await Promise.resolve();
[, buttons] = renderPiece(circleOnly);
assert.deepEqual(buttons.slice(4).map(b => [b[0], b[1]]), [['Ask', false], ['✕', false]]);
assert.equal(JSON.stringify(checks.map(c => c[3])), JSON.stringify([['Kai', 'Mia']]));
console.log('PASS f: a smaller group: 2 up to the most, one picker for a piece, too small actions greyed');
