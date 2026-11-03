/** The player's furniture run rows for pair actions, both consent modes
 * (packages/player-ui/src/PropActionsPanel.tsx, PropActionExecutionRow — the
 * one row web, browser HUD and native HUD all mount).
 * Usage: node scripts/smoke_prop_action_react_rows.mjs
 *
 * Hand-derived from prop_action_engine.state_for rows of one pair run, Kai
 * (actor) and Kira (partner), action "Hug"; t() is the identity here, so
 * '{pose} with {name}' reads "Hug with Kira":
 * a. react, Kira's view, approaching, can_resist: "Kai: Hug · Approaching",
 *    ONE button "Push away" that cancels the run (cancelPropAction) — no
 *    Accept/Decline, nothing to answer.
 * b. react, Kai's view, reaction pending: "Hug with Kira · Waiting for
 *    reaction", one button "Stop".
 * c. react, Kai's view, reaction accepted (or timeout/player): plain
 *    "Hug with Kira · Approaching"; phase entry: "Hug with Kira · Entering".
 * d. react, Kira's view, active (the sit has begun, can_resist false):
 *    "Kai: Hug · Active", button "Stop" — once it began it is ended, not
 *    pushed away.
 * e. ask, Kira's view, awaiting consent (incoming): "Kai: Hug · Awaiting
 *    consent", buttons Accept, Decline, Stop — unchanged except the name.
 * f. ask, Kai's view, outgoing: "Hug with Kira · Awaiting consent",
 *    "Withdraw". Solo run: just "Sit · Active", "Stop".
 * f2. ask, Kai's view of a group (members Kira, Ben): "Hug with Kira, Ben ·
 *    Awaiting consent".
 * g. A resisted run is not drawn here at all: it is terminal, state_for puts
 *    it in recent_results, which the panel does not list as a row.
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
const calls = [];
runInNewContext(ts.transpileModule(source, { compilerOptions: {
  target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
} }).outputText, { module, exports: module.exports, require: id => ({
  react: { useState: initial => [typeof initial === 'function' ? initial() : initial, () => {}], useEffect() {} },
  'react/jsx-runtime': { jsx, jsxs: jsx, Fragment: 'fragment' },
  './api': { apiPost: () => calls.push('wake') }, './HoverHint': { HoverHint() {} },
  './I18nProvider': { useI18n: () => ({ t: text => text }) },
  './propActionReasons': { propActionReason: reason => reason }, './usePropActions': {},
  './propActions': {
    cancelPropAction: id => calls.push(['cancel', id]), respondPropAction: (id, yes) => calls.push(['respond', id, yes]),
    notifyPropActionChanged() {}, requestPropAction() {},
  },
})[id] ?? (() => { throw new Error(`Unexpected import ${id}`) })() });
const { PropActionExecutionRow } = module.exports;

const nodes = tree => Array.isArray(tree) ? tree.flatMap(nodes)
  : tree && typeof tree === 'object' ? [tree, ...nodes(tree.props?.children)] : [];
const text = tree => Array.isArray(tree) ? tree.map(text).join('')
  : tree && typeof tree === 'object' ? text(tree.props?.children) : tree == null || tree === false ? '' : String(tree);
// [row text, [button texts]] and the buttons themselves.
const view = (run, kind = 'current') => {
  const tree = PropActionExecutionRow({ run, kind, busy: false, perform: operation => operation() });
  const all = nodes(tree);
  const buttons = all.filter(n => n.type === 'button');
  return { label: text(all.find(n => n.type === 'span')), names: buttons.map(text), buttons };
};
const pair = (extra) => ({ execution_id: 'x1', actor: 'Kai', members: ['Kira'], label: 'Hug', status: 'approaching',
  phase: '', reason: '', can_respond: false, can_cancel: true, consent: 'react', ...extra });

// a.
let row = view(pair({ own_role: 'partner', reaction: 'pending', can_resist: true }));
assert.equal(row.label, 'Kai: Hug · Approaching');
assert.deepEqual(row.names, ['Push away']);
row.buttons[0].props.onClick();
assert.deepEqual(calls.at(-1), ['cancel', 'x1']);
// b.
row = view(pair({ own_role: 'actor', reaction: 'pending', can_resist: false }));
assert.equal(row.label, 'Hug with Kira · Waiting for reaction');
assert.deepEqual(row.names, ['Stop']);
// c.
for (const reaction of ['accepted', 'timeout', 'player', 'none']) {
  assert.equal(view(pair({ own_role: 'actor', reaction })).label, 'Hug with Kira · Approaching', reaction);
}
assert.equal(view(pair({ own_role: 'actor', reaction: 'accepted', phase: 'entry' })).label, 'Hug with Kira · Entering');
// d.
row = view(pair({ own_role: 'partner', reaction: 'accepted', status: 'active', can_resist: false }));
assert.equal(row.label, 'Kai: Hug · Active');
assert.deepEqual(row.names, ['Stop']);
// e.
row = view(pair({ consent: 'ask', own_role: 'partner', reaction: '', status: 'awaiting_consent',
  can_respond: true }), 'incoming');
assert.equal(row.label, 'Kai: Hug · Awaiting consent');
assert.deepEqual(row.names, ['Accept', 'Decline', 'Stop']);
// f.
row = view(pair({ consent: 'ask', own_role: 'actor', reaction: '', status: 'awaiting_consent' }), 'outgoing');
assert.equal(row.label, 'Hug with Kira · Awaiting consent');
assert.deepEqual(row.names, ['Withdraw']);
row = view({ execution_id: 's', actor: 'Kai', members: [], label: 'Sit', status: 'active', phase: '', reason: '',
  can_respond: false, can_cancel: true, own_role: 'actor', consent: '', reaction: '', can_resist: false });
assert.equal(row.label, 'Sit · Active');
assert.deepEqual(row.names, ['Stop']);
// f2. A group row names every invitee for the one who started it.
row = view(pair({ members: ['Kira', 'Ben'], consent: 'ask', own_role: 'actor', reaction: '', status: 'awaiting_consent' }), 'outgoing');
assert.equal(row.label, 'Hug with Kira, Ben · Awaiting consent');
// g. The panel lists only incoming/outgoing/current as rows.
const listed = [...source.matchAll(/\['(\w+)', ownRuns\(data\.state\.(\w+)\)\]/g)].map(m => m[2]);
assert.deepEqual(listed, ['incoming', 'outgoing', 'current']);
console.log('prop action react rows: PASS (push away, waiting for reaction, names on pair rows, ask unchanged, resisted not drawn)');
