/** Render resolution: real engine methods and Graphics-tab React output with lightweight host doubles. */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import ts from 'typescript';
const require = createRequire(import.meta.url);
function load(file, dependencies, window) {
  const module = { exports: {} };
  const code = ts.transpileModule(readFileSync(file, 'utf8'), { fileName: file,
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  new Function('require', 'module', 'exports', 'window', code)(dependencies, module, module.exports, window);
  return module.exports;
}
const events = new Map();
const window = { innerWidth: 3840, innerHeight: 1080, devicePixelRatio: 1,
  addEventListener: (name, fn) => events.set(name, fn), removeEventListener: name => events.delete(name) };
const P = load('client3d/src/game/prefs.ts', require, window);
const { Engine } = load('client3d/src/scene/engine.ts', name => name === 'three' ? require(name)
  : name === '../game/prefs' ? P : {}, window);
const ratios = [], sizes = [], labels = [];
const container = { clientWidth: 3840, clientHeight: 1080 };
const engine = Object.assign(Object.create(Engine.prototype), { container, renderScalePref: 'auto',
  camera: { updateProjectionMatrix() {} }, renderer: { setSize: (...a) => sizes.push(a), setPixelRatio: v => ratios.push(v) },
  labelRenderer: { setSize: (...a) => labels.push(a) } });
engine.resize(container);
assert.equal(ratios.at(-1), 0.7, 'ultrawide auto ratio');
engine.setRenderScale(0.85);
assert.equal(ratios.at(-1), 0.85, 'runtime fixed scale');
window.devicePixelRatio = 3;
engine.resize(container);
assert.equal(ratios.at(-1), 1.7, 'existing DPR cap precedes fixed scale');
engine.setRenderScale('auto');
assert.equal(ratios.at(-1), 1, 'capped DPR 2 and auto minimum .5');
container.clientWidth = 1600; container.clientHeight = 900; window.devicePixelRatio = 1;
engine.resize(container);
assert.equal(ratios.at(-1), 1, 'resize recomputes auto');
assert.deepEqual(labels.at(-1), [1600, 900], 'CSS labels keep CSS size');

let native = false, states = [], stateIndex = 0, effectIndex = 0;
const effects = new Set();
const hooks = { useState(initial) { const i = stateIndex++; if (!(i in states)) states[i] = typeof initial === 'function' ? initial() : initial;
  return [states[i], value => { states[i] = typeof value === 'function' ? value(states[i]) : value; }]; },
  useEffect(fn) { const i = effectIndex++; if (!effects.has(i)) { effects.add(i); fn(); } },
  useSyncExternalStore: () => ({ clientCache: null }) };
const { GameMenu } = load('client3d/src/hud/GameMenu.tsx', name => {
  if (name === 'react') return hooks;
  if (name === 'react/jsx-runtime') return require(name);
  if (name === '@anima/player-ui') return { useI18n: () => ({ t: s => s }) };
  if (name === './bridge') return { isNativeHud: () => native };
  if (name === '../game/prefs') return P;
  if (name === '../api') return { listPlayableCharacters: async () => ({ characters: [] }) };
  return {};
}, window);
let changed;
const props = { graphicsPrefs: { ...P.DEFAULT_GRAPHICS_PREFS }, scatterPrefs: P.DEFAULT_SCATTER_PREFS,
  prefs: P.DEFAULT_PREFS, onGraphicsChange: p => { changed = p; } };
function render() { stateIndex = effectIndex = 0; return GameMenu(props); }
function all(node) { return Array.isArray(node) ? node.flatMap(all) : node && typeof node === 'object'
  ? [node, ...all(node.props?.children)] : [node]; }
let tree = render();
all(tree).find(n => n?.type === 'button' && n.props.children === 'Graphics').props.onClick();
tree = render();
let select = all(tree).find(n => n?.type === 'select' && n.props['aria-label'] === 'Render resolution');
assert.ok(select, 'Graphics tab exposes accessible Render resolution select');
assert.deepEqual(all(select.props.children).filter(n => n?.type === 'option').map(n => n.props.children),
  ['Auto', '100 %', '85 %', '75 %', '66 %', '50 %']);
assert.ok(all(tree).includes('Auto: 70 % · 2688 × 756'), 'auto hint shows effective physical resolution');
select.props.onChange({ target: { value: '0.66' } });
assert.deepEqual(changed, { antiAliasing: '2x', shadows: true, renderScale: 0.66 });
select.props.onChange({ target: { value: 'auto' } });
assert.equal(changed.renderScale, 'auto');
window.innerWidth = 1600; window.innerHeight = 900;
events.get('resize')(); tree = render();
assert.ok(all(tree).includes('Auto: 100 % · 1600 × 900'), 'hint updates on resize');
props.graphicsPrefs.renderScale = 0.85;
assert.ok(all(render()).includes('85 % · 1360 × 765'), 'fixed hint');
native = true; window.devicePixelRatio = 3;
events.get('resize')();
props.graphicsPrefs.renderScale = 'auto';
assert.ok(all(render()).includes('Auto: 50 % · 2400 × 1350'), 'native hint uses physical page DPR');
console.log('render scale smoke: engine auto/fixed/resize/DPR, CSS labels, Graphics select/change/hints OK');
