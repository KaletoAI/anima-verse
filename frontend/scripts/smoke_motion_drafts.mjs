/** Usage: node frontend/scripts/smoke_motion_drafts.mjs
 * Hand expectations: gain .5 is the sole scalar edit; two edited squash
 * endpoints produce [.7, 1.3], preserving an existing gravity override.
 */
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { readFileSync } from 'node:fs'
const require = createRequire(import.meta.url)
const ts = require('typescript')
const source = readFileSync('frontend/src/lib/motionDraft.ts', 'utf8')
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText
const result = { exports: {} }
new Function('exports', compiled)(result.exports)
const { makeDraft, editDraft, draftOverrides, validNumber, draftChanged } = result.exports
const defaults = { gain: 1, freq_hz: 2, squash: [.8, 1.2] }
const initial = makeDraft(defaults)
const edited = editDraft(initial, 'gain', '.5')
const polled = makeDraft({ ...defaults, gain: .9 })
assert.equal(edited.values.gain, '.5')
assert.equal(draftChanged(edited), true)
assert.notDeepEqual(edited, polled)
assert.deepEqual(draftOverrides(edited, defaults, { gravity: .4 }), { gravity: .4, gain: .5 })
const squash = editDraft(editDraft(initial, 'squash_min', '.7'), 'squash_max', '1.3')
assert.deepEqual(draftOverrides(squash, defaults, {}), { squash: [.7, 1.3] })
for (const value of ['', '-', '1e', 'Infinity', '-1']) assert.equal(validNumber(value, 0), false)
assert.equal(validNumber('0', 0, undefined, true), false)
assert.equal(validNumber('.5', 0, 1), true)
assert.deepEqual(draftOverrides(editDraft(initial, 'squash_min', '.7'), { ...defaults, squash: [.8, 1.4] }, {}), { squash: [.7, 1.4] })

// Execute the shared Setup/State input with a persistent local state slot.
const inputSource = readFileSync('frontend/src/tabs/characters/MotionNumberInput.tsx', 'utf8')
const inputCode = ts.transpileModule(inputSource.replace(/^import .*$/gm, '').replace(/export /g, ''), {
  compilerOptions: { jsx: ts.JsxEmit.React, target: ts.ScriptTarget.ES2020 },
}).outputText
let editing
let value = .7
const commits = []
const useState = initial => {
  if (editing === undefined) editing = initial
  return [editing, next => { editing = next }]
}
const React = { createElement: (tag, props, ...children) => ({ tag, props, children }), Fragment: 'fragment' }
const Component = new Function('React', 'useState', 'useI18n', 'validNumber', inputCode + '; return MotionNumberInput')(
  React, useState, () => ({ t: text => text }), validNumber)
const render = (optional = false) => Component({ value, optional, onCommit: text => { commits.push(text); value = text === '' ? '' : Number(text) } }).children[0]
render().props.onChange({ target: { value: '-' } })
assert.equal(render().props.value, '-')
assert.equal(render().props['aria-invalid'], true)
render().props.onBlur()
assert.equal(commits.length, 0)
assert.equal(render().props.value, '0.7')
render().props.onChange({ target: { value: '.4' } })
render().props.onKeyDown({ key: 'Enter', preventDefault() {} })
assert.equal(commits.pop(), '.4')
assert.equal(render().props.value, '0.4')
render(true).props.onChange({ target: { value: '' } })
render(true).props.onBlur()
assert.equal(commits.pop(), '')
console.log('PASS draft survives poll; exact overrides and current untouched squash endpoint; invalid blur reverts; Enter/blank commit')

// State angle bounds must permit signed drafts and retain the per-character hint.
const stateSource=readFileSync('frontend/src/tabs/states/StatesTab.tsx','utf8')
const minimum=new Function('field', 'return '+stateSource.match(/min=\{(field === 'rest_deg'[^}]+)\}/)[1])('rest_deg')
const maximum=new Function('field', 'return '+stateSource.match(/max=\{(field === 'rest_deg'[^}]+)\}/)[1])('rest_deg')
assert.equal(minimum,-180);assert.equal(maximum,180)
assert.equal(validNumber('-60',minimum,maximum),true)
assert.equal(validNumber('150',minimum,maximum),true)
assert.equal(validNumber('181',minimum,maximum),false)
assert.ok(stateSource.includes("t('Clamped per character to its maximum rest angle.')"))
console.log('PASS state rest drafts accept -60/150, reject 181, and explain character clamp')

const axisDefaults={...defaults,axis_gain:[1,1,1]};
const axisDraft=editDraft(makeDraft(axisDefaults),'axis_gain_longitudinal','.15');
assert.deepEqual(draftOverrides(axisDraft,axisDefaults,{gravity:.4}),{gravity:.4,axis_gain:[1,1,.15]});
assert.deepEqual(draftOverrides(axisDraft,{...axisDefaults,axis_gain:[.5,1,1]},{}),{axis_gain:[.5,1,.15]});
assert.deepEqual(draftOverrides(editDraft(makeDraft({...axisDefaults,axis_gain:[1,1,.15]}),'axis_gain_longitudinal','1'),axisDefaults,{axis_gain:[1,1,.15]}),{});
console.log('PASS axis_gain draft preserves untouched current axes and removes default override');

const translationDefaults={...defaults,translate:0};
assert.deepEqual(draftOverrides(editDraft(makeDraft(translationDefaults),'translate','.6'),translationDefaults,{}),{translate:.6});
assert.equal(validNumber('1.1',0,1),false);
console.log('PASS translate scalar draft sends .6 and rejects values above 1');

// Slider defaults are 1; save preserves raw overrides, returning to 1 prunes.
const sliders=makeDraft({gain:1});
assert.equal(sliders.values.bounce,'1');
const sliderEdit=editDraft(editDraft(sliders,'bounce','1.25'),'weight','.8');
assert.deepEqual(draftOverrides(sliderEdit,{gain:1},{gravity:.4}),{gravity:.4,bounce:1.25,weight:.8});
assert.equal(makeDraft(draftOverrides(sliderEdit,{gain:1},{})).values.weight,'0.8');
assert.deepEqual(draftOverrides(editDraft(makeDraft({bounce:1.25}),'bounce','1'),{}, {bounce:1.25}),{});
console.log('PASS Bounce/Weight draft round-trip and default pruning');
