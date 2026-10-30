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
const { propActionReason } = await import(moduleUrl(new URL('./src/propActionReasons.ts', import.meta.url)));
const { PropActionsPanel, PropActionOffers, PropActionExecutionRow } = await import(moduleUrl(new URL('./src/PropActionsPanel.tsx', import.meta.url)));
const de = JSON.parse(readFileSync(new URL('../../shared/languages/de.json', import.meta.url), 'utf8')).translations;
const translate = source => de[source] || source;
assert.equal(propActionReason('start_not_walkable', translate), 'Geh zuerst etwas vom Möbelstück weg');
assert.equal(propActionReason('future_code', translate), 'Zurzeit nicht möglich');
assert.equal(propActionReason('constructor', translate), 'Zurzeit nicht möglich');
const render = (Component, props) => renderToStaticMarkup(React.createElement(I18nProvider, null, React.createElement(Component, props)));
const target = { location_id: 'house', room_id: 'lounge', placement_id: 'sofa-2', variant_uid: 'green' };
const offer = { action_id: 'rest', definition_revision: 'rev-7', placement_id: 'sofa-2', variant_uid: 'green', target, label: 'Rest', description: 'On the sofa', enabled: true, reason: '', required_partner: true, available_targets: [{ partner: 'Kira', enabled: false, reason: 'slot_occupied' }, { partner: 'Mira', enabled: true, reason: '' }], effects: [{ when: 'success', target: 'actor', stat: 'energy', amount: 5 }] };
const markup = render(PropActionOffers, { offers: [offer], onPick() {} });
const buttons = [...markup.matchAll(/<button\b[^>]*>[^<]*<\/button>/g)].map(match => match[0]);
assert.equal(buttons.length, 2, 'one chip per exact partner target');
assert.match(markup, />Rest · Kira<\/button>/);
assert.match(markup, />Rest · Mira<\/button>/);
assert.match(markup, /flex-wrap:wrap/);
assert.doesNotMatch(markup, /flex-direction:column|<select/);
assert.doesNotMatch(markup, /2 people|1 person/);
const textNodes = html => html.replace(/<[^>]*>/g, '');
assert.doesNotMatch(textNodes(markup), /On the sofa|success|energy|occupied|Needs a partner/);
assert.match(markup, /title="This place is occupied"/);
assert.match(markup, /aria-disabled="true"/);
const filtered = render(PropActionOffers, { offers: [offer], partner: 'Kira', onPick() {} });
assert.match(filtered, /Kira/);
assert.doesNotMatch(filtered, /Mira/);
assert.match(filtered, /disabled=""/);
assert.match(filtered, /This place is occupied/);
assert.doesNotMatch(filtered, /<div[^>]*>slot_occupied<\/div>/);
const available = render(PropActionOffers, { offers: [offer], partner: 'Mira', onPick() {} });
assert.doesNotMatch(available, /disabled=""/);
const retainedOffers = render(PropActionOffers, { offers: [offer], partner: 'Kira', busy: true, onPick() {} });
assert.match(retainedOffers, /disabled=""/);
assert.match(retainedOffers, /This place is occupied/);
const solo = render(PropActionOffers, { offers: [{ ...offer, required_partner: false, enabled: false, reason: 'no_path', available_targets: [] }], onPick() {} });
assert.doesNotMatch(solo, /1 person/);
assert.match(solo, /title="Not possible right now"/);
assert.doesNotMatch(textNodes(solo), /Not possible right now/);
assert.match(solo, /Not possible right now/);
assert.match(solo, /disabled=""/);
const soloEnabled = render(PropActionOffers, { offers: [{ ...offer, required_partner: false, available_targets: [] }], onPick() {} });
assert.match(soloEnabled, />Rest<\/button>/);
const stepOut = render(PropActionOffers, { offers: [{ ...offer, required_partner: false, enabled: false, reason: 'start_not_walkable' }], onPick() {} });
assert.match(stepOut, /Step away from the furniture first/);
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
assert.equal(textNodes(combinedPhase), 'Rest · ActiveStop');
assert.doesNotMatch(combinedPhase, /65d1be74-2221-4c30-a5bf-d409d8297a71/);
assert.doesNotMatch(row({ status: 'active', phase: authoredPhaseId, phase_label: '' }, 'current'), /65d1be74-2221-4c30-a5bf-d409d8297a71/);
const sleep = row({ status: 'sleeping' }, 'current');
assert.match(sleep, /Sleeping/);
assert.match(sleep, /Wake up/);
assert.match(sleep, /Stop/);
const declined = row({ status: 'cancelled', reason: 'consent_declined', can_respond: false, can_cancel: false }, 'result');
assert.equal(textNodes(declined), 'Rest · Cancelled');
assert.doesNotMatch(declined, /<button/);
const result = row({ status: 'completed', can_respond: false, can_cancel: false, effects: { success: { energy: 5 } } }, 'result');
assert.equal(textNodes(result), 'Rest · Completed');
assert.doesNotMatch(result, /Results|energy/);
console.log('PASS semantic shared offers and private lifecycle components');

// The embedded panel renders the scene snapshot through the actual hook.
const propApi = await import(moduleUrl(new URL('./src/propActions.ts', import.meta.url)));
propApi.setPropActionHost(true);
propApi.publishHostedPropActions({ offers: [offer], state: { incoming: [], outgoing: [], current: [{ ...execution, status: 'active' }], recent_results: [] } });
const hostedPanel = render(PropActionsPanel, {});
assert.match(hostedPanel, /Furniture actions/);
assert.match(hostedPanel, /Active/);
assert.match(hostedPanel, /Stop/);
// Finished runs are not listed (the storyteller narrates them): only results -> no panel at all.
propApi.publishHostedPropActions({ offers: [], state: { incoming: [], outgoing: [], current: [],
  recent_results: [{ ...execution, status: 'completed', can_respond: false, can_cancel: false }] } });
assert.equal(render(PropActionsPanel, {}), '', 'finished runs are not listed');
propApi.publishHostedPropActions(null);
assert.equal(render(PropActionsPanel, {}), '', 'reconnecting host clears old private snapshot');
propApi.setPropActionHost(false);
console.log('PASS hosted prop panel snapshot through actual usePropActions hook');

// Collect literal runtime reasons, excluding author-validation issue codes.
for (const file of ['prop_action_paths.py', 'prop_action_engine.py', 'prop_action_access.py']) {
  const source = readFileSync(new URL(`../../app/core/${file}`, import.meta.url), 'utf8');
  // A literal followed by a comma is the route MODE of a (route, mode, reason)
  // tuple, not a reason; that tuple's reason is the third element.
  const patterns = [/_blocked\(["']([^"']+)["']\)/g, /last_reason = ["']([^"']+)["']/g,
    /return (?:None, )?["']([a-z_]+)["'](?!,)/g, /return None, ["'][a-z_]+["'], ["']([a-z_]+)["']/g,
    /_refused\(["']([^"']+)["']\)/g];
  for (const pattern of patterns) for (const [, code] of source.matchAll(pattern)) {
    assert.notEqual(propActionReason(code, text => text), 'Not possible right now', `missing player reason: ${code}`);
    assert.notEqual(propActionReason(code, translate), propActionReason(code, text => text), `missing German reason: ${code}`);
  }
}
