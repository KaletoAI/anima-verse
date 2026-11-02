// Run from repository root: node packages/player-ui/propActionFinale.test.mjs
// The finale marks of the shared prop-action UI (schnittstellen-3d § A8c):
// an offer whose pose has a finale clip carries the chip class
// player-chip-finale and the hover word "With finale"; an active run shows one
// gauge per participant from the state row `meters`, clamped to 0..100,
// named with the neutral word "Finale" unless the package labels it, and
// none while the run is not active yet.
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
const offer = { action_id: 'rest', definition_revision: 'rev-7', placement_id: 'sofa-2', variant_uid: 'green', target, label: 'Rest', description: '', prop_label: 'Sofa', distance_m: 1.5, enabled: true, reason: '', required_partner: false, available_targets: [], effects: [] };

const marked = render(PropActionOffers, { offers: [{ ...offer, finale: true }], onPick() {} });
assert.match(marked, /class="player-chip player-chip-finale"/);
assert.match(marked, /data-hint="Sofa · 1.5 m · With finale"/);
const plain = render(PropActionOffers, { offers: [offer], onPick() {} });
assert.doesNotMatch(plain, /player-chip-finale|With finale/);
const unnamed = render(PropActionOffers, { offers: [{ ...offer, finale: true }], nameProps: false, onPick() {} });
assert.match(unnamed, /data-hint="With finale"/);

const execution = { execution_id: 'run-8', action_id: 'rest', definition_revision: 'rev-7', target, actor: 'Player', partner: 'Mira', status: 'active', phase: '', phase_label: '', reason: '', label: 'Rest', roles: { actor: 'Player', partner: 'Mira', clip: {}, access: {} }, can_respond: false, can_cancel: true };
const row = changes => render(PropActionExecutionRow, { run: { ...execution, ...changes }, kind: 'current', busy: false, perform() {} });
const gauged = row({ has_finale: true, meters: [{ name: 'Player', value: 42.4, label: '' }, { name: 'Mira', value: 130, label: 'Heat' }] });
assert.equal([...gauged.matchAll(/role="meter"/g)].length, 2);
assert.match(gauged, /aria-valuenow="42"[^>]*aria-label="Player · Finale"/);
assert.match(gauged, /aria-valuenow="100"[^>]*aria-label="Mira · Heat"/);
assert.match(gauged, /width:42.4%/);
assert.match(gauged, /width:100%/);
assert.match(row({ meters: [{ name: 'Player', value: -3, label: '' }] }), /aria-valuenow="0"/);
assert.doesNotMatch(row({ status: 'approaching', meters: [{ name: 'Player', value: 10, label: '' }] }), /role="meter"/);
assert.doesNotMatch(row({}), /role="meter"/);
// Hold back: a toggle only on the viewer's OWN holdable gauge (own_role picks
// the side), pressed while held; never on the partner's row.
const holding = row({ own_role: 'actor', meters: [{ name: 'Player', value: 20, label: '', holdable: true, held: true }, { name: 'Mira', value: 30, label: '', holdable: true }] });
assert.equal([...holding.matchAll(/>Hold back<\/button>/g)].length, 1);
assert.match(holding, /class="player-chip on"[^>]*aria-pressed="true"[^>]*>Hold back</);
assert.match(holding, /class="player-prop-meter held"/);
assert.equal([...row({ own_role: 'partner', meters: [{ name: 'Player', value: 20, label: '', holdable: true }, { name: 'Mira', value: 30, label: '', holdable: true }] }).matchAll(/aria-pressed="false"/g)].length, 1);
assert.doesNotMatch(row({ own_role: 'actor', meters: [{ name: 'Player', value: 20, label: '' }] }), /Hold back/);
console.log('PASS finale chip mark, per-participant gauges and the hold toggle');
