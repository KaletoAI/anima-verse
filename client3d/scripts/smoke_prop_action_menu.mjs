/** Task 80: the real canvas menu preserves Core's enabled verdict beside an active owned run. */
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { build } from 'esbuild';
process.env.NODE_ENV = 'production';
const require = createRequire(new URL('../package.json', import.meta.url));
const compiled = await build({
  stdin: { contents: `
    import { createElement as h } from 'react';
    import { renderToStaticMarkup } from 'react-dom/server';
    import { PlaceMenu } from './client3d/src/hud/PlaceMenu';
    import { I18nProvider } from './packages/player-ui/src/I18nProvider';
    import { PropActionExecutionRow } from './packages/player-ui/src/PropActionsPanel';
    export function render(menu, run) {
      return renderToStaticMarkup(h(I18nProvider, null,
        h(PropActionExecutionRow, { run, kind: 'current', busy: false, perform() {} }),
        h(PlaceMenu, { menu })));
    }`, resolveDir: new URL('../../', import.meta.url).pathname, loader: 'ts' },
  bundle: true, jsx: 'automatic', platform: 'node', format: 'cjs', write: false,
  external: ['react', 'react/*', 'react-dom/*'], loader: { '.css': 'empty' },
});
const module = { exports: {} };
new Function('require', 'module', 'exports', compiled.outputFiles[0].text)(require, module, module.exports);
const target = { location_id: 'house', room_id: 'room', placement_id: 'sofa', variant_uid: 'green' };
const offer = { target, definition_revision: 'rev', label: 'Change seat', description: '',
  required_partner: false, available_targets: [], effects: [], reason: '', enabled: true, action_id: 'other' };
const run = { execution_id: 'old', status: 'active', can_cancel: true, can_respond: false,
  label: 'Already seated', target, actor: 'avatar', partner: '', reason: '' };
const markup = module.exports.render({ x: 10, y: 20, offer: { id: 'sofa', label: 'Sofa', poses: [],
  prop_actions: [offer, { ...offer, action_id: 'same', label: 'Same action', enabled: false, reason: 'participant_claimed' }] } }, run);
const buttons = [...markup.matchAll(/<button\b[^>]*>[^<]*<\/button>/g)].map(match => match[0]);
assert.match(markup, /Already seated/);
assert.match(markup, /Active/);
assert.doesNotMatch(buttons.find(button => button.includes('Change seat')), /disabled/);
assert.match(buttons.find(button => button.includes('Same action')), /disabled/);
console.log('prop action menu: PASS (enabled switch beside active owned run; same action remains blocked)');
