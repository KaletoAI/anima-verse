/** Dot picking uses the same projection as the painted minimap. */
import assert from 'node:assert/strict';
import { existsSync } from 'node:fs';
import { build } from 'esbuild';
assert.ok(existsSync('client3d/src/game/travelPick.ts'), 'travel picking is missing');
const result = await build({ entryPoints: ['client3d/src/game/travelPick.ts'], bundle: true, write: false, format: 'esm' });
const { pickPlaceAt } = await import('data:text/javascript;base64,' + Buffer.from(result.outputFiles[0].text).toString('base64'));
const places = [{ id: 'A', name: 'A', x: 0, z: 0 }, { id: 'B', name: 'B', x: 5, z: 0 }];
const layout = { scale: 2, offX: 10, offY: 20 };
for (const [x, y, expected] of [[12,20,'A'], [16,20,'B'], [15,20,'A'], [10,30,'A'], [10,31,null]]) {
  assert.equal(pickPlaceAt(places, layout, x, y), expected);
}
assert.equal(pickPlaceAt([], layout, 10, 20), null);
console.log('travel pick: PASS (nearest, ties, inclusive radius, empty)');

const apiBuild = await build({ entryPoints: ['client3d/src/api.ts'], bundle: true, write: false, format: 'esm' });
const api = await import('data:text/javascript;base64,' + Buffer.from(apiBuild.outputFiles[0].text).toString('base64'));
const originalFetch = globalThis.fetch;
const requests = [];
try {
  globalThis.fetch = async (url, init) => {
    requests.push([url, init.method, JSON.parse(init.body)]);
    return new Response('{}');
  };
  await api.travelTo('harbor');
  await api.cancelTravel();
  assert.deepEqual(requests, [['/play/travel', 'POST', { target_id: 'harbor' }], ['/play/travel/cancel', 'POST', {}]]);
  for (const detail of ['The gate is locked.', { reason: 'locked', message: 'The gate is locked.' }]) {
    globalThis.fetch = async () => new Response(JSON.stringify({ detail }), { status: 403 });
    for (const action of [() => api.travelTo('harbor'), api.cancelTravel]) {
      await assert.rejects(action, error => error instanceof api.ApiError && error.status === 403 && error.message === 'The gate is locked.');
    }
  }
} finally { globalThis.fetch = originalFetch; }
console.log('travel API: PASS (request bodies, server detail, ApiError)');
