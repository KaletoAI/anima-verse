/** Real read-only room-check component, with deterministic hook scheduling.
 * Usage: node scripts/smoke_prop_admin_controls.mjs
 * By hand: before actor selection there are 0 placement POSTs; selecting one
 * actor admits exactly 1 read-only POST. Its result remains visible after a
 * draft change, marked as previous. Opening admits 1 locations GET and no
 * recovery GET. No world-execution endpoint may be requested by this UI.
 */
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFile } from 'node:fs/promises';
import { runInNewContext } from 'node:vm';
const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const ts = require('typescript');
const modules = new Map();
let cells = [], cursor = 0, effects = [], dirty = false;
const hooks = {
  useState(initial) {
    const slot = cursor++;
    if (!(slot in cells)) cells[slot] = typeof initial === 'function' ? initial() : initial;
    return [cells[slot], next => { cells[slot] = typeof next === 'function' ? next(cells[slot]) : next; dirty = true; }];
  },
  useRef(initial) {
    const slot = cursor++;
    if (!(slot in cells)) cells[slot] = { current: initial };
    return cells[slot];
  },
  useMemo: fn => fn(),
  useEffect(fn, deps) {
    const slot = cursor++, previous = cells[slot];
    if (!previous || deps.some((value, index) => value !== previous[index])) effects.push(fn);
    cells[slot] = deps;
  },
};
const requests = [];
const target = { location_id: 'room-location', room_id: 'room', placement_id: 'placed', prop_id: 'bench', variant_uid: 'A' };
const api = {
  ApiError: class extends Error {},
  async apiGet(path) {
    requests.push(['GET', path]);
    if (path === '/world/locations') return { locations: [{ id: 'room-location', name: 'Location' }] };
    if (path.includes('/check-targets?')) return { revision: 'r1', rooms: [{ id: 'room', name: 'Room', placements: [{ target }], persons: [{ name: 'demo', sleeping: false }] }] };
    throw new Error('Unexpected read: ' + path);
  },
  async apiPost(path, body) {
    requests.push(['POST', path, body]);
    assert.equal(path, '/world/props/bench/check-placement');
    return { enabled: true, reason: '' };
  },
};
for (const name of ['pendingFields', 'propActionAuthoring', 'propActionChecks', 'PropActionChecks']) {
  const source = await readFile(new URL(`../frontend/src/tabs/props/${name}.${name.startsWith('Prop') ? 'tsx' : 'ts'}`, import.meta.url), 'utf8');
  const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } });
  const module = { exports: {} };
  runInNewContext(outputText, { module, exports: module.exports, require: id => {
    if (id === 'react') return hooks;
    if (id === '@anima/player-ui') return { Field: () => null };
    if (id === '../../lib/api') return api;
    if (id.startsWith('./') && modules.has(id.slice(2))) return modules.get(id.slice(2));
    return require(id);
  } });
  modules.set(name, module.exports);
}
const workspace = { t: text => text, prop: { id: 'bench', name: 'Bench', revision: 'r1', actions: [{ id: 'rest', name: 'Rest', participants: 1 }] },
  variants: [], buf: modules.get('pendingFields').emptyFields(), catalog: { status: 'ready' }, selectedActionId: 'rest', dirtyCount: 0, saving: false, revisionReady: true };
let tree;
function render() {
  cursor = 0; effects = []; dirty = false;
  tree = modules.get('PropActionChecks').PropActionChecks({ workspace, onIssue() {} });
  for (const effect of effects) effect();
}
async function flush() {
  for (let n = 0; n < 10; n++) {
    await Promise.resolve();
    if (dirty) render();
  }
}
function nodes(node) {
  if (!node || typeof node !== 'object') return [];
  if (Array.isArray(node)) return node.flatMap(nodes);
  return [node, ...nodes(node.props?.children)];
}
function texts(node) {
  if (typeof node === 'string') return node;
  if (!node || typeof node !== 'object') return '';
  return Array.isArray(node) ? node.map(texts).join(' ') : texts(node.props?.children);
}
function choose(label, value) {
  const select = nodes(tree).find(node => node.type === 'select' && node.props['aria-label'] === label);
  assert(select, label);
  select.props.onChange({ target: { value } });
}
render(); await flush();
assert.equal(requests.filter(([method, path]) => method === 'GET' && path === '/world/locations').length, 1);
assert(texts(tree).includes('Missing: choose a location'));
choose('Saved location', 'room-location'); await flush();
assert(texts(tree).includes('Missing: choose a room'));
choose('Actual room', 'room'); await flush();
assert(texts(tree).includes('Missing: choose a placement'));
choose('Saved placement', 'placed'); await flush();
assert(texts(tree).includes('Missing: choose a person in the room'));
assert.equal(requests.filter(([method]) => method === 'POST').length, 0);
choose('Actor in the room', 'demo'); await flush();
const button = nodes(tree).find(node => node.type === 'button' && texts(node) === 'Check in room (read only)');
assert.equal(button.props.disabled, false);
button.props.onClick(); await flush();
assert.equal(requests.filter(([method]) => method === 'POST').length, 1);
assert(texts(tree).includes('Currently available: availability, path and entry checked. No execution started.'));
workspace.dirtyCount = 1; render(); await flush();
assert(texts(tree).includes('Missing: save or discard the draft'));
assert(texts(tree).includes('Previous check:'));
assert(texts(tree).includes('Currently available:'));
assert(requests.every(([, path]) => !/execute-test|test-state|test-respond|test-cancel|test-wake|prop-action-tests/.test(path)));
console.log('PASS: automatic locations, missing prerequisites, read-only POST and retained result');
