/** Behavioral editor checks. By hand: server supplies two places; a lie solo
 * shows the sleep checkbox; choosing 2 persons derives pair; effects summarize
 * energy +5/min and mood relaxed. Advanced and Effects start collapsed.
 * Package actions (plan-pack-prop-actions.md): the one server-listed package
 * action "Doze" (package label "Test pack", bound on "left") is shown read-only
 * under "From packages" with "Applies to: 1 places"; unticking "Offer on this
 * furniture" queues exclude_actions [pack-doze] beside the stored [pack-old],
 * and it appears as "Doze (Test pack)" among a marker's exclusions and in
 * "Used by". */
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFile } from 'node:fs/promises';
import { runInNewContext } from 'node:vm';
const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const ts = require('typescript');
const jsx = (type, props) => ({ type, props });
const React = { useState: value => [value, () => {}], useEffect() {} };
const I18n = { useI18n: () => ({ t: text => text }) };
async function load(file, imports) {
  const source = await readFile(new URL(`../frontend/src/tabs/props/${file}`, import.meta.url), 'utf8');
  const module = { exports: {} };
  runInNewContext(ts.transpileModule(source, { compilerOptions: {
    target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText, { module, exports: module.exports, require: id => {
    if (id === 'react') return React;
    if (id === 'react/jsx-runtime') return { jsx, jsxs: jsx };
    if (id.includes('I18nProvider')) return I18n;
    if (imports[id]) return imports[id];
    throw new Error(`Unexpected import ${id}`);
  } });
  return module.exports;
}
const author = await load('propActionAuthoring.ts', {});
const effects = await load('PropActionEffects.tsx', {
  '../../lib/moods': { useMoods: () => ['relaxed'] }, './propActionAuthoring': author,
});
const pending = await load('pendingFields.ts', {});
const { PropActionsPanel } = await load('PropActionsPanel.tsx', {
  '../../lib/api': {}, './PropWorkspaceDialog': { PropWorkspaceDialog() {} },
  './PropActionChecks': { PropActionChecks() {} }, './PropActionEffects': effects,
  './propActionAuthoring': author, './pendingFields': pending,
});
function nodes(tree) {
  if (Array.isArray(tree)) return tree.flatMap(nodes);
  if (!tree || typeof tree !== 'object') return [];
  return [tree, ...nodes(tree.props?.children)];
}
function text(tree) {
  if (Array.isArray(tree)) return tree.map(text).join('');
  return tree && typeof tree === 'object' ? text(tree.props?.children) : tree == null ? '' : String(tree);
}
const action = { id: 'rest', name: 'Rest', description: '', enabled: true,
  ability: 'pose', pose_key: 'lie', participants: 1, presence: 'any',
  interrupt_on_presence_change: false, phases: [], requirements: [], effects: [] };
const catalog = { status: 'ready', stats: ['energy'], conditions: [], groups: {},
  poses: [{ key: 'lie', group: 'lie', animation: 'lie' },
    { key: 'sit', group: 'seat', animation: 'sit' },
    { key: 'pair', group: 'lie', animation: 'duo', solo: false }],
  kinds: ['lie', 'sit'], pairKinds: ['duo'] };
let patch;
const workspace = { t: value => value, actions: [action], shownVariant: { uid: 'v', markers: [
  { id: 'left', group: 'lie' }, { id: 'right', group: 'lie' }] },
  derivedBindings: { v: [{ action_id: 'rest', marker_ids: ['left', 'right'] }, { action_id: 'pack-doze', marker_ids: ['left'] }] },
  selectedActionId: 'rest', variants: [], catalog, authoringIssues: [], prop: { id: 'bed', exclude_actions: ['pack-old'] },
  buf: pending.emptyFields(),
  packActions: [{ id: 'pack-doze', name: 'Doze', description: '', ability: 'pose', participants: 1,
    pose_key: 'lie', package: 'testpack', package_label: 'Test pack', excluded: false }],
  queueGeneral: value => { patch = value; }, setSelectedActionId() {}, queueVariant() {},
};
const tree = PropActionsPanel({ workspace, onIssue() {} });
const all = nodes(tree);
assert(text(tree).includes('Applies to: 2 places on this variant (lie x2)'));
assert(!all.some(node => node.props?.label === 'Executable ability'));
const poses = all.find(node => node.props?.label === 'Pose');
assert.deepEqual(Array.from(poses.props.options, p => p.value), ['lie', 'sit']);
const packSection = all.find(node => node.type === 'section' && text(node).startsWith('From packages'));
assert(packSection && text(packSection).includes('Doze From package Test pack · 1 People'));
assert(text(packSection).includes('Applies to: 1 places on this variant'));
assert(!nodes(packSection).some(node => node.type === 'input' && node.props.type !== 'checkbox'), 'read-only');
const offerHere = nodes(packSection).find(node => node.type === 'input' && node.props.type === 'checkbox');
assert.equal(offerHere.props.checked, true);
offerHere.props.onChange({ target: { checked: false } });
assert.deepEqual(Array.from(patch.exclude_actions), ['pack-old', 'pack-doze']);
assert(!('actions' in patch), 'a package action never enters the draft');
const sleep = all.find(node => node.type === 'label' && text(node).includes('Really fall asleep'));
nodes(sleep).find(node => node.type === 'input').props.onChange({ target: { checked: true } });
assert.equal(patch.actions[0].ability, 'sleep');
const persons = all.find(node => node.props?.label === 'Persons');
nodes(persons).find(node => node.type === 'select').props.onChange({ target: { value: '2' } });
assert.equal(patch.actions[0].ability, 'pair');
assert.equal(patch.actions[0].pose_key, 'pair');
const advanced = all.find(node => node.type === 'details' && text(node.props.children[0]) === 'Advanced');
assert(advanced && !advanced.props.open);
assert(nodes(advanced).some(node => node.type === effects.PropActionRequirements));
assert(nodes(advanced).some(node => text(node) === 'Copy from another prop'));
const effectTree = effects.PropActionEffects({ action: { ...action, ability: 'combined', effects: [
  { id: 'e', target: 'actor', when: 'active', type: 'stat_delta', stat: 'energy', amount: 5 },
  { id: 'm', target: 'actor', when: 'success', type: 'mood', mood: 'relaxed' },
] }, catalog, path: 'actions.0', onChange() {} });
assert.equal(effectTree.type, 'details');
assert(!effectTree.props.open);
assert.equal(text(effectTree.props.children[0]), 'Effects · While active: Energy +5/min · On success: Mood relaxed');
const { PropPlaces } = await load('PropPlaces.tsx', {
  '../../components/SliderInput': { SliderInput() {} },
  '../world/placeTypes': { groupLabel: (_, group) => group },
  './usePropWorkspace': { AT_AXES: [], AT_MAX: 2 },
  './accessGeometry': { propMetresPerUnit: () => 1 },
});
let markerPatch;
const marker = { id: 'left', group: 'lie', at: [.5, .5, .5], capacity: 2 };
const markerTree = PropPlaces({ workspace: { ...workspace, markers: [marker], selMarker: marker,
  selIdx: 0, groups: {}, groupOptions: ['lie'], selPoses: [], selCapacity: 2,
  shownDims: { width_m: 2, depth_m: 2, height_m: 1 },
  patchMarker: (_, change) => { markerPatch = change; },
} });
assert(text(markerTree).includes('Used by: Rest, Doze'));
assert(text(markerTree).includes('Doze (Test pack)'));
const markerAdvanced = nodes(markerTree).find(node => node.type === 'details');
assert(!markerAdvanced.props.open);
assert(text(markerAdvanced).includes('Not for these actions'));
assert(text(markerAdvanced).includes('Access override'));
const exclusion = nodes(markerAdvanced).find(node => node.type === 'input' && node.props.type === 'checkbox');
exclusion.props.onChange({ target: { checked: true } });
assert.deepEqual(Array.from(markerPatch.exclude_actions), ['rest']);
console.log('PASS: server-derived counts, all-group solo poses, sleep/pair derivation, collapsed advanced, effect summary and marker exclusions');
