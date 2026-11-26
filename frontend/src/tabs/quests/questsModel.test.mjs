// Run from the repository root: node frontend/src/tabs/quests/questsModel.test.mjs
// The pure model of the Quests tab (questsModel.ts): row <-> draft conversion, issue lookup by D7 path, step ids
// and the role filter. Expectations derived by hand from the plan header:
// - the reference quest "Errand" (header) survives rowToDraft -> draftToRow unchanged; the row has no state, the
//   draft defaults to "draft", so the round trip adds exactly state: "draft";
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
  placeholderList, moveItem, filterOptions, canSave, questErrorText, ERROR_CODE_TEXTS } = await import(moduleUrl(new URL('./questsModel.ts', import.meta.url)));

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
  assert.deepEqual(draftToRow(draft), { ...errand, state: 'draft' }, 'the reference quest round-trips');
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
console.log('questsModel: all checks passed');
