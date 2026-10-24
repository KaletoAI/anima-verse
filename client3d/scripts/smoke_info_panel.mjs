/** Pure location information: area rules, room membership and optional fields. */
import assert from 'node:assert/strict';
import { existsSync } from 'node:fs';
import { build } from 'esbuild';
assert.ok(existsSync('client3d/src/game/infoPanel.ts'), 'pure infoPanelData is missing');
const result = await build({ entryPoints: ['client3d/src/game/infoPanel.ts'], bundle: true, write: false, format: 'esm' });
const { infoPanelData } = await import('data:text/javascript;base64,' + Buffer.from(result.outputFiles[0].text).toString('base64'));
const loc = { id: 'loc1', name: 'Home', rooms: [{ id: 'r1', name: 'Kitchen' }, { id: 'r2', name: 'Hall' }] };
const chars = [{ name: 'A', movement_target_name: 'Harbor', travel: { eta_hhmm: '14:30' } }, { name: 'B' }, { name: 'C' }];
const rooms = new Map([['A', 'Kitchen'], ['B', 'r2']]);
const data = infoPanelData(loc, chars, [{ category: 'danger', text: 'Fire' }, { category: 'other', text: 'News' }], rooms);
assert.deepEqual(infoPanelData({ ...loc, terrain: 'forest' }, chars, [], rooms).rooms, []);
assert.deepEqual(infoPanelData({ ...loc, map3d: { area_model: 'area' } }, chars, [], rooms).rooms, []);
assert.deepEqual(data.rooms, [{ name: 'Kitchen', who: ['A'] }, { name: 'Hall', who: ['B'] }]);
assert.deepEqual(data.present, [{ name: 'A', activity: '', mood: '', travelTo: 'Harbor', eta: '14:30' }, { name: 'B', activity: '', mood: '', travelTo: '', eta: '' }, { name: 'C', activity: '', mood: '', travelTo: '', eta: '' }]);
assert.deepEqual(data.events, [{ danger: true, text: 'Fire' }, { danger: false, text: 'News' }]);
assert.equal(data.view, null);
assert.equal(data.description, '');
assert.deepEqual(infoPanelData(loc, [], [], rooms, { openable: true, open: false }).view, { openable: true, open: false });
assert.deepEqual(JSON.parse(JSON.stringify(data)), data);
console.log('info panel: PASS (areas, rooms, present order, travel, events, view, JSON)');

const avatar = { locationId: 'L2', pos: { x: 3, z: 4 } };
const placed = { ...loc, id: 'L1', pos_x: 0, pos_z: 0 };
assert.equal(infoPanelData(placed, [], [], rooms, undefined, avatar).travel.distanceM, 5);
assert.equal(infoPanelData({ ...placed, id: 'L2' }, [], [], rooms, undefined, avatar).travel, null);
assert.equal(infoPanelData(placed, [], [], rooms).travel, null);
assert.equal(infoPanelData(loc, [], [], rooms, undefined, avatar).travel.distanceM, null);
console.log('info travel: PASS (distance, current location, missing avatar/position)');
