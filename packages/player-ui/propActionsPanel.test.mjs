// Run from repository root: node packages/player-ui/propActionsPanel.test.mjs
// Render the actual shared UI: blocked partners must remain visible, general
// enabled offers must not enable a blocked exact partner, and consent/stop/wake
// controls must follow the private DTO rather than an optimistic place field.
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
const { I18nProvider } = await import(moduleUrl(new URL('./src/I18nProvider.tsx', import.meta.url)));
const { PropActionOffers, PropActionExecutionRow } = await import(moduleUrl(new URL('./src/PropActionsPanel.tsx', import.meta.url)));
const render = (Component, props) => renderToStaticMarkup(React.createElement(I18nProvider, null, React.createElement(Component, props)));
const target = { location_id: 'house', room_id: 'lounge', placement_id: 'sofa-2', variant_uid: 'green' };
const offer = { action_id: 'rest', definition_revision: 'rev-7', placement_id: 'sofa-2', variant_uid: 'green', target, label: 'Rest', description: 'On the sofa', enabled: true, reason: '', required_partner: true, available_targets: [{ partner: 'Kira', enabled: false, reason: 'slot_occupied' }, { partner: 'Mira', enabled: true, reason: '' }], effects: [] };
const markup = render(PropActionOffers, { offers: [offer], onPick() {} });
const buttons = [...markup.matchAll(/<button\b[^>]*>[^<]*<\/button>/g)].map(match => match[0]);
assert.match(buttons.find(button => button.includes('Kira')), /disabled=""/);
assert.doesNotMatch(buttons.find(button => button.includes('Mira')), /disabled/);
assert.match(markup, /slot_occupied/);
assert.match(markup, /2 people/);
const filtered = render(PropActionOffers, { offers: [offer], partner: 'Kira', onPick() {} });
assert.match(filtered, /Kira/);
assert.doesNotMatch(filtered, /Mira/);
const retainedOffers = render(PropActionOffers, { offers: [offer], busy: true, onPick() {} });
const retainedButtons = [...retainedOffers.matchAll(/<button\b[^>]*>[^<]*<\/button>/g)].map(match => match[0]);
assert.equal(retainedButtons.length, 2);
assert.ok(retainedButtons.every(button => button.includes('disabled=""')), 'retained offers cannot be requested while freshness is unavailable');
assert.match(retainedOffers, /slot_occupied/, 'disabled retained offers preserve authoritative blocked reason');
const solo = render(PropActionOffers, { offers: [{ ...offer, required_partner: false, enabled: false, reason: 'no_path', available_targets: [] }], onPick() {} });
assert.match(solo, /1 person/);
assert.match(solo, /no_path/);
assert.match(solo, /disabled=""/);
const execution = { execution_id: 'run-8', action_id: 'rest', definition_revision: 'rev-7', target, actor: 'Player', partner: 'Mira', status: 'awaiting_consent', phase: '', phase_label: '', reason: '', label: 'Rest', roles: { actor: 'Player', partner: 'Mira', clip: { actor: 'b', partner: 'a' }, access: { actor: 'right', partner: 'left' } }, can_respond: true, can_cancel: true };
const row = (changes, kind) => render(PropActionExecutionRow, { run: { ...execution, ...changes }, kind, busy: false, perform() {} });
const incoming = row({}, 'incoming');
assert.match(incoming, /Accept/);
assert.match(incoming, /Decline/);
assert.doesNotMatch(row({ can_respond: false }, 'current'), /Accept|Decline/);
assert.match(row({}, 'outgoing'), /Withdraw/);
assert.match(row({ status: 'approaching', phase: '' }, 'current'), /Approaching/);
assert.match(row({ status: 'approaching', phase: 'entry' }, 'current'), /Entering/);
assert.match(row({ status: 'active' }, 'current'), /Active/);
const authoredPhaseId = '65d1be74-2221-4c30-a5bf-d409d8297a71';
const combinedPhase = row({ status: 'active', phase: authoredPhaseId, phase_label: 'Brew coffee' }, 'current');
assert.match(combinedPhase, /Brew coffee/);
assert.doesNotMatch(combinedPhase, /65d1be74-2221-4c30-a5bf-d409d8297a71/);
assert.doesNotMatch(row({ status: 'active', phase: authoredPhaseId, phase_label: '' }, 'current'), /65d1be74-2221-4c30-a5bf-d409d8297a71/);
const sleep = row({ status: 'sleeping' }, 'current');
assert.match(sleep, /Sleeping/);
assert.match(sleep, /Wake up/);
assert.match(sleep, /Stop/);
const declined = row({ status: 'cancelled', reason: 'consent_declined', can_respond: false, can_cancel: false }, 'result');
assert.match(declined, /consent_declined/);
assert.doesNotMatch(declined, /<button/);
const result = row({ status: 'completed', can_respond: false, can_cancel: false, effects: { success: { energy: 5 } } }, 'result');
assert.match(result, /Results/);
assert.match(result, /energy/);
console.log('PASS semantic shared offers and private lifecycle components');
