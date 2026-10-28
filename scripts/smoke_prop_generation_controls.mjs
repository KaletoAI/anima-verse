/** Real PropAssets generation controls, without browser or server.
 * By hand: a running prop admits 0 new requests, regardless of free slots.
 * Idle regeneration targets the selected UID and allocates 0 variants;
 * only the separate new-variant button may append, below the active cap.
 */
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFile } from 'node:fs/promises';
import { runInNewContext } from 'node:vm';

const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const ts = require('typescript');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const compile = async (name, imports) => {
  const source = await readFile(new URL(`../frontend/src/tabs/props/${name}`, import.meta.url), 'utf8');
  const result = ts.transpileModule(source, { compilerOptions: {
    target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
  } });
  const module = { exports: {} };
  runInNewContext(result.outputText, { module, exports: module.exports,
    require: id => Object.hasOwn(imports, id) ? imports[id] : require(id) });
  return module.exports;
};
const operations = await compile('propOperations.ts', {});
// Child components are not executed: inspect the real parent's React elements.
const child = () => null;
const { PropAssets } = await compile('PropAssets.tsx', {
  './propOperations': operations,
  './PropModelPanel': { PropModelPanel: child },
  './PropVariantStrip': { PropVariantStrip: child },
  './PropWorkspaceDialog': { PropWorkspaceDialog: child },
  './propTypes': { PROP_EXTRA_VIEWS: ['back', 'left', 'right'] },
  '../../components/SliderInput': { SliderInput: child },
  './variantFields': { DESC_ROWS_OPEN: 5, DESC_ROWS_REST: 2, DIM_FIELDS: [], SINK_LIMIT_M: 5 },
  './usePropWorkspace': { VIEW_LABEL: { back: 'Back view', left: 'Left view', right: 'Right view' } },
});
const row = (uid, index, tiers = []) => ({ uid, index, active: true, tiers,
  dims: { width_m: 1, height_m: 1, depth_m: 1 }, description: '', ground_offset_m: 0 });
const render = (variants, max, busy, selected = 0) => {
  const calls = [];
  const workspace = { t: text => text, pending: busy.length > 0, variantBusy: busy.includes(selected),
    prop: { id: 'private' }, enc: 'private', variant: selected, variants, variantMax: max,
    generatingVariants: busy, shownVariant: variants[selected], shownImage: undefined,
    dimDraft: {}, worldSeasons: [], currentSeason: '', generationRepairs: [],
    openRegeneration: append => calls.push({ append: !!append, uid: variants[selected].uid }) };
  let tree;
  function Probe() { tree = PropAssets({ workspace }); return null; }
  renderToStaticMarkup(React.createElement(Probe));
  const buttons = React.Children.toArray(tree.props.children).filter(node => node.type === 'button');
  return { button: buttons[0], appendButton: buttons[1], calls };
};
const firstPending = render([row('A', 0)], 2, [0]);
assert.equal(firstPending.button.props.disabled, true, 'running prop gates Regenerate');
assert.equal(firstPending.appendButton.props.disabled, true);
const idle = render([row('A', 0), row('B', 1)], 3, [], 1);
assert.equal(idle.button.props.disabled, false);
idle.button.props.onClick();
assert.deepEqual(idle.calls, [{ append: false, uid: 'B' }]);
idle.appendButton.props.onClick();
assert.deepEqual(idle.calls[1], { append: true, uid: 'B' });
const capped = render([row('A', 0), row('B', 1)], 2, [], 1);
assert.equal(capped.button.props.disabled, false, 'regeneration works at cap');
assert.equal(capped.appendButton.props.disabled, true, 'append never overwrites at cap');
console.log('PASS: selected regeneration, explicit append, running gate and cap');
