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
const newDefaults = {straighten_deg:0,freetext_clothing_gain:1}
const newDraft = editDraft(editDraft(makeDraft(newDefaults), 'straighten_deg', '60'), 'freetext_clothing_gain', '.25')
assert.deepEqual(draftOverrides(newDraft,newDefaults,{}),{straighten_deg:60,freetext_clothing_gain:.25})
assert.equal(validNumber('181',0,180),false);assert.equal(validNumber('1.1',0,1),false)
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

const formDefaults={...defaults,stretch:0,spread:.5,flatten_floor:.6};
assert.deepEqual(draftOverrides(editDraft(editDraft(makeDraft(formDefaults),'stretch','1'),'flatten_floor','.15'),formDefaults,{}),{stretch:1,flatten_floor:.15});
const hintCode=ts.transpileModule(readFileSync('frontend/src/tabs/characters/motionFieldPreview.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText;
const hintModule={exports:{}};new Function('exports',hintCode)(hintModule.exports);
const {rateLimitPreviewTilt,motionFieldPreview}=hintModule.exports;
assert.equal(motionFieldPreview.spread,'tilt');assert.equal(motionFieldPreview.stretch,'tilt');assert.equal(motionFieldPreview.flatten_floor,'tilt');
assert.equal(motionFieldPreview.length,'live');assert.equal(motionFieldPreview.girth,'live');
const diagonal=rateLimitPreviewTilt({forward:0,sideways:0},{forward:90,sideways:-90},.1);
assert.ok(Math.abs(diagonal.forward-12/Math.SQRT2)<1e-12);
assert.ok(Math.abs(diagonal.sideways+12/Math.SQRT2)<1e-12);
assert.deepEqual(rateLimitPreviewTilt({forward:0,sideways:0},{forward:90,sideways:0},.1),{forward:12,sideways:0});
assert.deepEqual(rateLimitPreviewTilt({forward:89,sideways:-89},{forward:90,sideways:-90},.1),{forward:90,sideways:-90});
assert.equal(rateLimitPreviewTilt({forward:0,sideways:0},{forward:90,sideways:0},NaN).forward,0);
for(const field of ['length','girth']) {
  const lo=new Function('field','return '+stateSource.match(/min=\{(field === 'rest_deg'[^}]+)\}/)[1])(field);
  const hi=new Function('field','return '+stateSource.match(/max=\{(field === 'rest_deg'[^}]+)\}/)[1])(field);
  assert.equal(lo,.5);assert.equal(hi,2);
}
console.log('PASS stretch/floor drafts; live state extent bounds; Tilt follows at 120 deg/s');

assert.deepEqual(draftOverrides(editDraft(makeDraft(formDefaults),'spread','.2'),formDefaults,{}),{spread:.2});

const fieldSource = readFileSync('frontend/src/tabs/characters/FieldModel3D.tsx', 'utf8')
assert.match(fieldSource, /setExtensionMotion\(group.id, values, true\)/)
assert.match(fieldSource, /if \(slidersOnly\) overrides\[id\] = \{ \.\.\.overrides\[id\], bounce: Number\(values\?\.bounce\), weight: Number\(values\?\.weight\) \}/)
console.log('PASS toolbar save merges only Bounce/Weight into the selected group')

// Execute the real save callback: the API replaces the map, so untouched values
// must be included unchanged rather than omitted or reset.
const saveSource = fieldSource.match(/const setExtensionMotion = useCallback\(async ([\s\S]*?)\n  }, \[enc/)[1] + '\n  }'
const saveCode = ts.transpileModule('const save = async ' + saveSource, { compilerOptions: { target: ts.ScriptTarget.ES2020 } }).outputText
let sent
const savedOverrides = { demo: { gravity: .4, axis_gain: [.2, .3, .4], bounce: .9 }, other: { gain: .6 } }
const saveToolbar = new Function('st','enc','setBusy','apiPost','setSt','toast','t','load','setSliderPreview', saveCode + '; return save')(
  { options: { extension_motion: savedOverrides } }, 'demo', () => {}, async (url, body) => { sent = { url, body }; return { options: body } },
  () => {}, () => {}, x => x, async () => {}, () => {})
assert.equal(await saveToolbar('demo', { bounce: 1.25, weight: .8, gain: .1 }, true), true)
assert.equal(sent.url, '/characters/demo/model3d/extension-motion')
assert.deepEqual(sent.body, { extension_motion: { demo: { gravity: .4, axis_gain: [.2,.3,.4], bounce: 1.25, weight: .8 }, other: { gain: .6 } } })
assert.equal(savedOverrides.demo.bounce, .9)
console.log('PASS toolbar request changes only selected group Bounce/Weight; raw and other groups preserved')

const sliderSource = readFileSync('frontend/src/tabs/characters/ExtensionMotionDraft.tsx', 'utf8')
const sliderCode = ts.transpileModule(sliderSource.replace(/^import .*$/gm, '').replace(/export /g, ''), {
  compilerOptions: { jsx: ts.JsxEmit.React, target: ts.ScriptTarget.ES2020 },
}).outputText
let sliderState
const previewCalls = [], saveCalls = []
const Slider = new Function('React','useState','useI18n','MotionPreviewHint','makeDraft','editDraft','draftChanged','draftOverrides','validNumber', sliderCode + '; return ExtensionMotionSliders')(
  React, initial => { sliderState ??= initial(); return [sliderState, next => { sliderState = next }] }, () => ({t:x=>x}), 'hint',
  makeDraft, editDraft, draftChanged, draftOverrides, validNumber)
const sliderProps = { overrides: { bounce: .9, gravity: .4 }, disabled: false,
  onPreview: value => previewCalls.push(value), onSave: async value => { saveCalls.push(value); sliderProps.overrides = value; return true } }
const allNodes = node => Array.isArray(node) ? node.flatMap(allNodes) : node?.children ? [node, ...node.children.flatMap(allNodes)] : []
const sliderNodes = () => allNodes(Slider(sliderProps))
sliderNodes().filter(node => node.tag === 'input')[0].props.onChange({target:{value:'1.25'}})
sliderNodes().filter(node => node.tag === 'input')[1].props.onChange({target:{value:'.8'}})
assert.deepEqual(previewCalls.at(-1), {bounce:1.25,weight:.8})
sliderProps.overrides = { bounce: 1, gravity: .7 }
assert.equal(sliderNodes().filter(node => node.tag === 'input')[0].props.value,'1.25','poll preserves slider draft')
assert.equal(saveCalls.length,0,'live changes do not persist')
sliderNodes().find(node => node.tag === 'button').props.onClick()
await Promise.resolve()
assert.deepEqual(saveCalls, [{bounce:1.25,weight:.8}])
assert.equal(sliderNodes().find(node => node.tag === 'button').props.disabled,true)
console.log('PASS toolbar live preview, poll-safe draft, independent Save and saved state')

const live = { rev: 'demo', groups: { demo: {gain:.2,max_deg:20,freq_hz:2,zeta:.7,gravity:.4,sag_max_deg:10,spill_max_deg:20,flatten:.4,stretch:.2,translate:.1}, other:{gain:.6} } }
const livePreview = hintModule.exports.previewMotionSliders(live, live.groups, {}, {demo:{bounce:1.25,weight:.8}})
assert.equal(livePreview.groups.demo.gain,.25)
assert.ok(Math.abs(livePreview.groups.demo.gravity - .32) < 1e-12)
assert.equal(livePreview.groups.other,live.groups.other)
assert.equal(live.groups.demo.gain,.2)
assert.notEqual(livePreview.rev,live.rev)
console.log('PASS live slider multipliers reach motion revision without mutating polled payload')
