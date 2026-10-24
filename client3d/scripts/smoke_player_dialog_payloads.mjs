/** Player dialog payloads, bundled as consumed by the browser. */
import assert from 'node:assert/strict';
import { build } from 'esbuild';
const result = await build({ entryPoints: ['packages/player-ui/src/playerDialogPayloads.ts'], bundle: true, write: false, format: 'esm', platform: 'browser' });
const { regenPayload, animatePayload, profileImagePayload } = await import('data:text/javascript;base64,' + Buffer.from(result.outputFiles[0].text).toString('base64'));
const regen = { prompt: ' a ', names: ['Kira'], useRoom: true, useSource: false, negative: '  ' };
assert.deepEqual(regenPayload(regen), { prompt: 'a', character_names: ['Kira'], use_room: true, use_source_as_reference: false });
assert.equal(regenPayload({ ...regen, names: [] }), null);
assert.equal(regenPayload({ ...regen, prompt: '  ' }), null);
assert.deepEqual(regenPayload({ ...regen, negative: ' blur ' }), { prompt: 'a', character_names: ['Kira'], use_room: true, use_source_as_reference: false, negative_prompt: 'blur' });
for (const seconds of ['', '0', 'x', '-2', 'Infinity']) assert.deepEqual(animatePayload({ prompt: ' wave ', seconds }), { prompt: 'wave' });
assert.deepEqual(animatePayload({ prompt: 'wave', seconds: '4' }), { prompt: 'wave', seconds: 4 });
assert.deepEqual(animatePayload({ prompt: 'wave', seconds: '4.9' }), { prompt: 'wave', seconds: 4 });
assert.equal(animatePayload({ prompt: '', seconds: '4' }), null);
assert.equal(animatePayload({ prompt: '  ', seconds: '4' }), null);
assert.deepEqual(profileImagePayload({ prompt: ' p ', useSource: false, negative: '' }), { prompt: 'p', use_source_as_reference: false });
assert.deepEqual(profileImagePayload({ prompt: 'p', useSource: true, negative: ' x ' }), { prompt: 'p', use_source_as_reference: true, negative_prompt: 'x' });
assert.equal(profileImagePayload({ prompt: '  ', useSource: true, negative: '' }), null);
console.log('PASS smoke_player_dialog_payloads');
