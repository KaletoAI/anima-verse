// Run from the repository root: node frontend/src/tabs/quests/questsModel.test.mjs
// The pure model of the Quests tab (questsModel.ts): row <-> draft conversion, issue lookup by D7 path, step ids
// and the role filter. Expectations derived by hand from the plan header:
// - the reference quest "Errand" (header) survives rowToDraft -> draftToRow unchanged except for the defaults:
//   state: "draft", giver_role: "", setup_effects: [], rewards: [] (its steps have no on_done, so none is emitted);
// - time_limit_s 7200 is 2 game hours (7200 / 3600), and 2 hours go back to 7200 seconds;
// - issue paths are dot-joined with 0-based indices (D7), so "steps.1" is a prefix of
//   "steps.1.condition.params.item" but NOT of "steps.10.text" (a plain startsWith would match both);
// - step ids are "s<n>", the first free n from 1: [s1, s3] -> s2, [] -> s1, [s1, s2] -> s3;
// - rolesOfKinds keeps the roles whose kind is listed, in their order;
// - bindingFor builds the D6 shape of a role kind from a picker's state and nothing else: a room needs BOTH
//   location_id and room_id ({location_id: 'l1'} alone is incomplete -> null), a character is {name}, a location
//   {location_id}, an item {item_id}; keys of other kinds in the pick are dropped, an empty string counts as unpicked,
//   an unknown kind is null;
// - bindingsComplete is true only when EVERY role has a complete binding: the reference quest's three roles with
//   "thing" unpicked -> false, with all three -> true; a quest without roles -> true (nothing to bind);
// - stepProgress shows the current step 1-based over the step count: current_step 1 of 3 -> "2 / 3"; a done run
//   has current_step == count (3 of 3) and stays "3 / 3", never "4 / 3"; no steps -> "0 / 0".
// Final fix wave:
// - placeholderList of the Errand roles is "{giver} {place} {thing}"; a blank key and a repeated key are left out;
//   no roles -> "";
// - moveItem([a,b,c], 0, 2) -> [b,c,a] (to the end, what drag-and-drop could not reach); (2, 0) -> [c,a,b];
//   to beyond the end clamps (1, 9) -> [a,c,b]; a no-move (1, 1) returns the SAME array; from out of range -> same;
// - filterOptions over ["Old Key", "Lamp", "Key ring"] with "key" -> Old Key, Key ring (case-insensitive); "  "
//   keeps all; "lamp" with "Old Key" selected keeps Old Key (the shown value) and Lamp;
// - canSave: a new template (id "") -> true even when not dirty; a stored one only when dirty; no draft -> false;
// - questErrorText with an identity t: code "has_open_runs" -> its text; "bad_request" with message "title is
//   required" -> "The input was refused. title is required"; an unknown code "" -> the message itself.
// Stage 2 (Task 11):
// - "The big rock" round-trips rowToDraft -> draftToRow to {...bigRock, state: "draft"} (entries without permanent
//   omit it, rewards keep permanent: true, s1/s3 omit on_done) and a second rowToDraft is identical;
// - reachability on bigRock (setup: rock [world_prop], box [item], box_spot [room_item], hint [secret];
//   s2.on_done: told [no object]; rewards: charm [item], charm_given [grant]):
//   * step:1 sees setup + s1.on_done -> knows_secret.secret (object_kinds: [secret]) -> ['hint'];
//   * step:2 sees setup + s1/s2.on_done -> holds_item.item (role_kinds: [item], object_kinds: [item]) -> ['box']
//     (no item role is declared; 'told' has no object);
//   * reward:1 sees setup + all on_done + rewards[0] (charm) -> give_item.item -> ['box', 'charm'];
//   * reward:0 sees setup + all on_done (no rewards yet) -> give_item.item -> ['box'];
//   * setup:2 sees setup[0..1] (rock, box) -> place_item.item -> ['box']; setup:0 sees nothing -> [];
//   * step:0 sees setup -> near_object.object ([world_prop, room_prop, room_item]) -> ['rock', 'box_spot'];
//   * entryObjectKind(create_prop, {room: 'glade'}) -> 'room_prop'; ({near: 'wood'}) -> 'world_prop';
//     entryObjectKind(undefined, {}) -> '';
//   * scopeAt(draft, 'step:0', fx).later contains 'told', 'charm', 'charm_given' and not 'rock';
//   * scopeAt with 'nonsense' throws;
// - clientIssues: bigRock -> []; empty steps[0].condition -> [{path: 'steps.0.condition', code: 'required',
//   message: 'A step needs a condition'}];
// - draftWarnings: bigRock -> []; 4th step found_item('box_spot') (hidden: true, difficulty: 3) -> [];
//   same with box_spot difficulty 0 -> one warning (path 'steps.3.condition', code 'not_hidden');
//   nested in {all: [...]} -> still that one warning;
// - newEffectKey: bigRock -> 'e1'; with an extra role key 'e1' -> 'e2'.
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';
const require = createRequire(new URL('../../../package.json', import.meta.url));
const ts = require('typescript');
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
const { rowToDraft, draftToRow, issuesAt, newStepId, rolesOfKinds, bindingFor, bindingsComplete, stepProgress,
  placeholderList, moveItem, filterOptions, canSave, questErrorText, ERROR_CODE_TEXTS,
  entryObjectKind, scopeAt, targetOptions, clientIssues, draftWarnings, newEffectKey } = await import(moduleUrl(new URL('./questsModel.ts', import.meta.url)));

// The reference quest of the plan header, verbatim.
const errand = {"title": "Errand", "summary": "Run an errand for someone.", "gm_notes": "GM ONLY",
 "roles": [{"key": "giver", "kind": "character", "description": "who asks"},
           {"key": "place", "kind": "room", "description": "where to go"},
           {"key": "thing", "kind": "item", "description": "what to bring"}],
 "steps": [{"id": "s1", "text": "Talk to the giver.", "hint": "HINT ONE",
            "condition": {"type": "spoke_with", "params": {"character": "giver"}}},
           {"id": "s2", "text": "Go to the place.", "hint": "HINT TWO",
            "condition": {"type": "at_place", "params": {"place": "place"}}},
           {"id": "s3", "text": "Hold the thing.", "hint": "HINT THREE",
            "condition": {"type": "holds_item", "params": {"item": "thing", "count": 1}}}],
 "start_condition": {}, "prerequisites": {}, "time_limit_s": 0};

{
  const draft = rowToDraft(errand);
  assert.equal(draft.state, 'draft');
  assert.equal(draft.id, '');
  assert.equal(draft.time_limit_h, 0);
  assert.deepEqual(draft.prerequisites, { condition: {}, locked_text: '' });
  assert.deepEqual(draftToRow(draft), { ...errand, state: 'draft', giver_role: '', setup_effects: [], rewards: [] }, 'the reference quest round-trips');
  // The draft is a copy: editing it never reaches the row it came from.
  draft.steps[0].condition.params.character = 'other';
  assert.equal(errand.steps[0].condition.params.character, 'giver');
}
{
  const stored = { ...errand, id: 'qt_abc', revision: 4, state: 'ready', time_limit_s: 7200,
                   prerequisites: { condition: { type: 'relationship_at_least', params: { character: 'giver', strength: 50 } },
                                    locked_text: 'Not yet.' } };
  const draft = rowToDraft(stored);
  assert.equal(draft.id, 'qt_abc');
  assert.equal(draft.revision, 4);
  assert.equal(draft.state, 'ready');
  assert.equal(draft.time_limit_h, 2);
  const row = draftToRow(draft);
  assert.equal(row.time_limit_s, 7200);
  assert.deepEqual(row.prerequisites, stored.prerequisites);
  assert.equal('id' in row, false, 'the id is the URL, never a body field');
  assert.equal('revision' in row, false, 'the revision travels as base_revision');
  assert.equal(draftToRow({ ...draft, time_limit_h: 1.5 }).time_limit_s, 5400);
}
{
  const issues = [
    { path: 'steps.1.condition.params.item', code: 'unknown_role', message: 'A' },
    { path: 'steps.10.text', code: 'required', message: 'B' },
    { path: 'steps.1', code: 'shape', message: 'C' },
    { path: 'title', code: 'required', message: 'D' },
  ];
  assert.deepEqual(issuesAt(issues, 'steps.1').map(i => i.message), ['A', 'C']);
  assert.deepEqual(issuesAt(issues, 'steps.10').map(i => i.message), ['B']);
  assert.deepEqual(issuesAt(issues, 'title').map(i => i.message), ['D']);
  assert.deepEqual(issuesAt(issues, 'tit'), []);
}
{
  const step = id => ({ id, text: '', hint: '', condition: {} });
  assert.equal(newStepId([step('s1'), step('s3')]), 's2');
  assert.equal(newStepId([]), 's1');
  assert.equal(newStepId([step('s1'), step('s2')]), 's3');
}
{
  const draft = rowToDraft(errand);
  assert.deepEqual(rolesOfKinds(draft.roles, ['room', 'location']).map(r => r.key), ['place']);
  assert.deepEqual(rolesOfKinds(draft.roles, ['character', 'item']).map(r => r.key), ['giver', 'thing']);
  assert.deepEqual(rolesOfKinds(draft.roles, []), []);
}
{
  assert.equal(bindingFor('room', { location_id: 'l1' }), null);
  assert.deepEqual(bindingFor('room', { location_id: 'l1', room_id: 'r1' }), { location_id: 'l1', room_id: 'r1' });
  assert.equal(bindingFor('room', { room_id: 'r1' }), null);
  assert.deepEqual(bindingFor('location', { location_id: 'l1', room_id: 'r1' }), { location_id: 'l1' });
  assert.deepEqual(bindingFor('character', { name: 'Ann', item_id: 'i1' }), { name: 'Ann' });
  assert.equal(bindingFor('character', { name: '' }), null);
  assert.deepEqual(bindingFor('item', { item_id: 'i1' }), { item_id: 'i1' });
  assert.equal(bindingFor('item', {}), null);
  assert.equal(bindingFor('secret', { name: 'x' }), null);
}
{
  const roles = rowToDraft(errand).roles;
  const picks = { giver: { name: 'Ann' }, place: { location_id: 'l1', room_id: 'r1' } };
  assert.equal(bindingsComplete(roles, picks), false, 'one role unpicked');
  assert.equal(bindingsComplete(roles, { ...picks, place: { location_id: 'l1' } , thing: { item_id: 'i1' } }), false,
    'a room without its room is incomplete');
  assert.equal(bindingsComplete(roles, { ...picks, thing: { item_id: 'i1' } }), true);
  assert.equal(bindingsComplete([], {}), true);
}
{
  assert.equal(stepProgress(1, 3), '2 / 3');
  assert.equal(stepProgress(3, 3), '3 / 3');
  assert.equal(stepProgress(0, 0), '0 / 0');
}
{
  const roles = rowToDraft(errand).roles;
  assert.equal(placeholderList(roles), '{giver} {place} {thing}');
  assert.equal(placeholderList([...roles, { key: ' ', kind: 'item', description: '' }, roles[0]]), '{giver} {place} {thing}');
  assert.equal(placeholderList([]), '');
}
{
  const list = ['a', 'b', 'c'];
  assert.deepEqual(moveItem(list, 0, 2), ['b', 'c', 'a']);
  assert.deepEqual(moveItem(list, 2, 0), ['c', 'a', 'b']);
  assert.deepEqual(moveItem(list, 1, 9), ['a', 'c', 'b']);
  assert.equal(moveItem(list, 1, 1), list);
  assert.equal(moveItem(list, 5, 0), list);
}
{
  const items = [{ id: 'k1', name: 'Old Key' }, { id: 'l1', name: 'Lamp' }, { id: 'k2', name: 'Key ring' }];
  const names = (q, sel = '') => filterOptions(items, q, (o) => o.name, (o) => o.id, sel).map((o) => o.name);
  assert.deepEqual(names('key'), ['Old Key', 'Key ring']);
  assert.deepEqual(names('  '), ['Old Key', 'Lamp', 'Key ring']);
  assert.deepEqual(names('lamp', 'k1'), ['Old Key', 'Lamp']);
}
{
  const fresh = rowToDraft({});
  const stored = rowToDraft({ ...errand, id: 'qt_1', revision: 2 });
  assert.equal(canSave(fresh, false), true);
  assert.equal(canSave(stored, false), false);
  assert.equal(canSave(stored, true), true);
  assert.equal(canSave(null, true), false);
}
{
  const t = (s) => s;
  assert.equal(questErrorText({ code: 'has_open_runs', message: 'x' }, t), ERROR_CODE_TEXTS.has_open_runs);
  assert.equal(questErrorText({ code: 'bad_request', message: 'title is required' }, t),
    'The input was refused. title is required');
  assert.equal(questErrorText({ code: '', message: 'network down' }, t), 'network down');
}

// Stage 2 reference quest "The big rock", verbatim.
const bigRock = {"title": "The big rock", "summary": "{giver} lost something near {wood}.", "gm_notes": "GM ONLY",
 "giver_role": "giver",
 "roles": [{"key": "giver", "kind": "character", "description": "who asks"},
           {"key": "wood", "kind": "location", "description": "the wood"},
           {"key": "glade", "kind": "room", "description": "where the box lies"}],
 "setup_effects": [
   {"key": "rock", "type": "create_prop", "params": {"name": "Big rock", "prompt": "a large mossy boulder",
     "height_m": 2.0, "near": "wood", "offset_x": 12, "offset_z": -4}},
   {"key": "box", "type": "create_item", "params": {"name": "Old tin box", "category": "tool"}},
   {"key": "box_spot", "type": "place_item", "params": {"item": "box", "room": "glade", "hidden": true, "difficulty": 3}},
   {"key": "hint", "type": "give_hint", "params": {"holder": "giver", "text": "The box lies hidden in {glade}."}}],
 "steps": [
   {"id": "s1", "text": "Find the big rock near {wood}.", "hint": "",
    "condition": {"type": "near_object", "params": {"object": "rock", "radius_m": 15}}},
   {"id": "s2", "text": "Find out where the box is.", "hint": "",
    "condition": {"type": "knows_secret", "params": {"secret": "hint"}},
    "on_done": [{"key": "told", "type": "narrate", "params": {"text": "You remember the hollow under the roots."}}]},
   {"id": "s3", "text": "Bring the tin box.", "hint": "",
    "condition": {"type": "holds_item", "params": {"item": "box", "count": 1}}}],
 "rewards": [
   {"key": "charm", "type": "create_item", "permanent": true,
    "params": {"name": "Lucky charm", "category": "tool", "stat_bonuses": "{\"luck\": 5}", "bonus_when": "carried"}},
   {"key": "charm_given", "type": "give_item", "permanent": true, "params": {"item": "charm"}}],
 "start_condition": {}, "prerequisites": {}, "time_limit_s": 0};

{
  const draft = rowToDraft(bigRock);
  assert.deepEqual(draftToRow(draft), { ...bigRock, state: 'draft' }, 'bigRock round-trips');
  assert.deepEqual(rowToDraft(draftToRow(draft)), draft, 'bigRock draft round-trips');
}
{
  // subset of GET /quests/catalog, copied from app/core/quest_effects.py and quest_types.py
  const createProp = { id: 'create_prop', kind: 'effect', label: 'Create a prop', description: '', params: [],
    object_kind: 'world_prop', object_kind_when: [['room', 'room_prop']] };
  const fx = [
    createProp,
    { id: 'create_item', kind: 'effect', label: 'Create an item', description: '', params: [], object_kind: 'item' },
    { id: 'place_item', kind: 'effect', label: 'Place an item', description: '', params: [], object_kind: 'room_item' },
    { id: 'give_hint', kind: 'effect', label: 'Give a hint', description: '', params: [], object_kind: 'secret' },
    { id: 'narrate', kind: 'effect', label: 'Narrate', description: '', params: [], object_kind: '' },
    { id: 'give_item', kind: 'effect', label: 'Give an item', description: '', params: [], object_kind: 'grant' },
  ];
  const knowsSecretParam = { key: 'secret', type: 'target', role_kinds: [], object_kinds: ['secret'] };
  const holdsItemParam = { key: 'item', type: 'target', role_kinds: ['item'], object_kinds: ['item'] };
  const giveItemParam = { key: 'item', type: 'target', role_kinds: ['item'], object_kinds: ['item'] };
  const nearObjectParam = { key: 'object', type: 'target', role_kinds: [], object_kinds: ['world_prop', 'room_prop', 'room_item'] };
  const placeItemParam = { key: 'item', type: 'target', role_kinds: ['item'], object_kinds: ['item'] };

  const draft = rowToDraft(bigRock);
  assert.deepEqual(targetOptions(draft, 'step:1', knowsSecretParam, fx), ['hint']);
  assert.deepEqual(targetOptions(draft, 'step:2', holdsItemParam, fx), ['box']);
  assert.deepEqual(targetOptions(draft, 'reward:1', giveItemParam, fx), ['box', 'charm']);
  assert.deepEqual(targetOptions(draft, 'reward:0', giveItemParam, fx), ['box']);
  assert.deepEqual(targetOptions(draft, 'setup:2', placeItemParam, fx), ['box']);
  assert.deepEqual(targetOptions(draft, 'setup:0', placeItemParam, fx), []);
  assert.deepEqual(targetOptions(draft, 'step:0', nearObjectParam, fx), ['rock', 'box_spot']);

  assert.equal(entryObjectKind(createProp, { room: 'glade' }), 'room_prop');
  assert.equal(entryObjectKind(createProp, { near: 'wood' }), 'world_prop');
  assert.equal(entryObjectKind(undefined, {}), '');

  const s0 = scopeAt(draft, 'step:0', fx);
  assert.ok(s0.later.includes('told'));
  assert.ok(s0.later.includes('charm'));
  assert.ok(s0.later.includes('charm_given'));
  assert.ok(!s0.later.includes('rock'));
  assert.throws(() => scopeAt(draft, 'nonsense', fx));
}
{
  const draft = rowToDraft(bigRock);
  assert.deepEqual(clientIssues(draft), []);
  const broken = rowToDraft(bigRock);
  broken.steps[0].condition = {};
  assert.deepEqual(clientIssues(broken), [{ path: 'steps.0.condition', code: 'required', message: 'A step needs a condition' }]);
}
{
  const draft = rowToDraft(bigRock);
  assert.deepEqual(draftWarnings(draft), []);
  const withFound = rowToDraft(bigRock);
  withFound.steps.push({ id: 's4', text: 'Find the box.', hint: '',
    condition: { type: 'found_item', params: { placement: 'box_spot' } }, on_done: [] });
  assert.deepEqual(draftWarnings(withFound), []);
  const notHidden = rowToDraft(bigRock);
  notHidden.setup_effects[2].params.difficulty = 0;
  notHidden.steps.push({ id: 's4', text: 'Find the box.', hint: '',
    condition: { type: 'found_item', params: { placement: 'box_spot' } }, on_done: [] });
  const w1 = draftWarnings(notHidden);
  assert.equal(w1.length, 1);
  assert.equal(w1[0].path, 'steps.3.condition');
  assert.equal(w1[0].code, 'not_hidden');
  const nested = rowToDraft(bigRock);
  nested.setup_effects[2].params.difficulty = 0;
  nested.steps.push({ id: 's4', text: 'Find the box.', hint: '',
    condition: { all: [{ type: 'found_item', params: { placement: 'box_spot' } }] }, on_done: [] });
  const w2 = draftWarnings(nested);
  assert.equal(w2.length, 1);
  assert.equal(w2[0].path, 'steps.3.condition');
  assert.equal(w2[0].code, 'not_hidden');
}
{
  const draft = rowToDraft(bigRock);
  assert.equal(newEffectKey(draft), 'e1');
  draft.roles.push({ key: 'e1', kind: 'item', description: '' });
  assert.equal(newEffectKey(draft), 'e2');
}
console.log('questsModel: all checks passed');
