// Run from repository root: node packages/player-ui/actionsTree.test.mjs
// The chat's action drawer (ActionsTree.tsx + the pure folding in
// actionsTreeModel.ts) and the chat mount of PropActionsPanel that no longer
// offers anything. Expectations are derived by hand from the fixture below.
//
// Fixture — avatar Ann, present [Mira, Kira, Ann]. Offers:
//   Sofa  (sofa/green,  2.5 m): Cuddle pair, targets Kira ok / Ben slot_occupied / Ann
//                               Sit solo ok; Rest solo blocked (no_path)
//   Chair (chair/oak,   1.0 m): Sit solo blocked (slot_occupied)
//   Bench (bench/pine,  1.0 m): Sit solo ok
//   Table (table/round, no position): Feast group of 3, candidates Kira, Ben
// [1] offerKind: Sit solo, Cuddle pair, Feast group.
// [2] pieceNodes: nearest first, a tie by label, no position last:
//     Bench (1.0), Chair (1.0), Sofa (2.5), Table (null). Sofa's actions:
//     usable first, then by label -> Cuddle, Sit, Rest.
// [3] partnerNodes: present minus the avatar plus every pair target minus the
//     avatar, by name -> Ben, Kira, Mira. Ben: Cuddle blocked
//     (slot_occupied); Kira: Cuddle usable; Mira: nothing (present only).
//     Feast (a group) belongs to nobody. Ann never appears.
// [4] Rendered with the three top levels open (localStorage), nothing
//     fetched (server render runs no effects, so no solo poses and no pair
//     poses): "Independent actions 0" + "No poses available.", "All
//     furniture 4" with closed pieces "Bench · 1.0 m 1", "Chair · 1.0 m 1"
//     (dimmed: nothing usable), "Sofa · 2.5 m 3", "Table 1"; "All potential
//     partners 3" with Ben 1, Kira 1, Mira 0. No piece's action is shown
//     while its piece is closed. Spectator ('' avatar) renders nothing.
// [5] The chat mount `PropActionsPanel showOffers={false}`: offers alone
//     render nothing (they were a section with chips before); with a running
//     row it shows the row and its Stop, but no offer chip ("With Kira").
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';
const require = createRequire(new URL('../../client3d/package.json', import.meta.url));
const ts = require('typescript');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const modules = new Map();
function moduleUrl(file) {
  const key = file.href;
  if (modules.has(key)) return modules.get(key);
  const source = ts.transpileModule(readFileSync(file, 'utf8'), { compilerOptions: {
    module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX,
  }}).outputText.replace(/from (['"])([^'"]+)\1/g, (_, quote, specifier) => {
    if (!specifier.startsWith('.')) return `from '${pathToFileURL(require.resolve(specifier)).href}'`;
    const base = new URL(specifier, file);
    const dependency = ['.ts', '.tsx'].map(extension => new URL(base.href + extension)).find(candidate => existsSync(fileURLToPath(candidate)));
    assert.ok(dependency, `missing source dependency ${specifier}`);
    return `from '${moduleUrl(dependency)}'`;
  });
  const url = 'data:text/javascript;base64,' + Buffer.from(source).toString('base64');
  modules.set(key, url);
  return url;
}
const src = name => moduleUrl(new URL(`./src/${name}`, import.meta.url));
const { offerKind, pieceNodes, partnerNodes } = await import(src('actionsTreeModel.ts'));
const { I18nProvider } = await import(src('I18nProvider.tsx'));
const { ActionsTree } = await import(src('ActionsTree.tsx'));
const { PropActionsPanel } = await import(src('PropActionsPanel.tsx'));
const propApi = await import(src('propActions.ts'));

const target = (placement_id, variant_uid) => ({ location_id: 'house', room_id: 'lounge', placement_id, variant_uid });
const base = { definition_revision: 'r1', description: '', effects: [], enabled: true, reason: '',
  required_partner: false, available_targets: [], participants: 1 };
const offer = (fields) => ({ ...base, placement_id: fields.target.placement_id,
  variant_uid: fields.target.variant_uid, ...fields });
const sofa = target('sofa', 'green');
const offers = [
  offer({ action_id: 'sit', label: 'Sit', prop_label: 'Sofa', distance_m: 2.5, target: sofa }),
  offer({ action_id: 'rest', label: 'Rest', prop_label: 'Sofa', distance_m: 2.5, target: sofa, enabled: false, reason: 'no_path' }),
  offer({ action_id: 'cuddle', label: 'Cuddle', prop_label: 'Sofa', distance_m: 2.5, target: sofa,
    required_partner: true, participants: 2, available_targets: [
      { partner: 'Kira', enabled: true, reason: '' },
      { partner: 'Ben', enabled: false, reason: 'slot_occupied' },
      { partner: 'Ann', enabled: false, reason: 'self' }] }),
  offer({ action_id: 'sit', label: 'Sit', prop_label: 'Chair', distance_m: 1.0, target: target('chair', 'oak'),
    enabled: false, reason: 'slot_occupied' }),
  offer({ action_id: 'sit', label: 'Sit', prop_label: 'Bench', distance_m: 1.0, target: target('bench', 'pine') }),
  offer({ action_id: 'feast', label: 'Feast', prop_label: 'Table', distance_m: null, target: target('table', 'round'),
    participants: 3, candidates: ['Kira', 'Ben'] }),
];
const present = ['Mira', 'Kira', 'Ann'];

// [1]
assert.deepEqual(['sit', 'cuddle', 'feast'].map(id => offerKind(offers.find(o => o.action_id === id))),
  ['solo', 'pair', 'group']);

// [2]
const pieces = pieceNodes(offers);
assert.deepEqual(pieces.map(p => [p.label, p.distance_m]),
  [['Bench', 1.0], ['Chair', 1.0], ['Sofa', 2.5], ['Table', null]]);
assert.deepEqual(pieces[2].offers.map(o => o.label), ['Cuddle', 'Sit', 'Rest']);

// [3]
const partners = partnerNodes(offers, present, 'Ann');
assert.deepEqual(partners.map(p => p.name), ['Ben', 'Kira', 'Mira']);
assert.deepEqual(partners.map(p => p.entries.map(e => [e.offer.label, e.enabled, e.reason])),
  [[['Cuddle', false, 'slot_occupied']], [['Cuddle', true, '']], []]);
console.log('PASS action tree folding');

// [4]
const textNodes = html => html.replace(/<[^>]*>/g, '');
const render = (Component, props) => renderToStaticMarkup(React.createElement(I18nProvider, null, React.createElement(Component, props)));
globalThis.localStorage = { getItem: () => JSON.stringify(['solo', 'furniture', 'partners', 'piece:x']), setItem() {} };
propApi.setPropActionHost(true);
propApi.publishHostedPropActions({ offers, state: { incoming: [], outgoing: [], current: [], recent_results: [] } });
const tree = render(ActionsTree, { avatar: 'Ann', present, interaction: null, onChanged() {} });
assert.equal(textNodes(tree), [
  '▸Independent actions0', 'No poses available.',
  '▸All furniture4', '▸Bench · 1.0 m1', '▸Chair · 1.0 m1', '▸Sofa · 2.5 m3', '▸Table1',
  '▸All potential partners3', '▸Ben1', '▸Kira1', '▸Mira0',
].join('').replace(/▸(Independent|All)/g, '▾$1'));
assert.match(tree, /class="player-actions-tree-node off"><button[^>]*aria-expanded="false"[^>]*>[\s\S]*?Chair · 1.0 m/);
assert.doesNotMatch(tree, /Cuddle|Feast|Ask/, 'a closed piece shows none of its actions');
assert.equal(render(ActionsTree, { avatar: '', present, interaction: null, onChanged() {} }), '');
console.log('PASS action tree rendering');

// [5]
assert.equal(render(PropActionsPanel, { showOffers: false }), '', 'offers alone: nothing in the chat');
const run = { execution_id: 'run-1', action_id: 'sit', definition_revision: 'r1', target: sofa, actor: 'Ann', members: [],
  viewer: 'Ann', status: 'active', phase: '', phase_label: '', reason: '', label: 'Sit',
  roles: { clip: {}, access: {} }, can_respond: false, can_cancel: true };
propApi.publishHostedPropActions({ offers, state: { incoming: [], outgoing: [], current: [run], recent_results: [] } });
const chat = render(PropActionsPanel, { showOffers: false });
assert.match(chat, /Sit · Active/);
assert.match(chat, />Stop<\/button>/);
assert.doesNotMatch(chat, /With Kira|player-prop-offers/);
propApi.publishHostedPropActions(null);
propApi.setPropActionHost(false);
console.log('PASS chat keeps only the running rows');
