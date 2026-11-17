/** Review 13-hair#2: `FigureLibrary.strandRecord` (client3d/src/scene/figures.ts) keeps a strand record only under
 * the sha256 it really is. The route `GET …/model/hair-strands` always serves the CURRENT record with
 * `ETag: "<sha256>"` (app/routes/characters.py `_strands_response`), so:
 *   [a] an answer with ETag "bbb" for a request of sha "aaa" (the character was rebuilt in between) is NOT kept under
 *       "aaa": the call stays undefined (bone hair, no strands bound onto the wrong cards), and no second download
 *       starts before the retry time (STRAND_RETRY_MS = 30 s), but one does once it has passed;
 *   [b] a 503 (server restarting) is the same passing failure: undefined, retried later — never a session-long null;
 *   [c] a 404 is the definitive "no strands": null, no further download;
 *   [d] a 200 with ETag "aaa" and the current record version is the record.
 * The old code stored whatever came under the requested sha and null for every failure.
 * Usage: node client3d/scripts/smoke_strand_record.mjs   (run from the repository root; no server, no WebGL)
 */
import assert from 'node:assert/strict';
import { build } from 'esbuild';
const bundle = await build({ stdin: { contents: `export * from './client3d/src/scene/figures'; export { STRAND_RECORD_VERSION } from '@anima/scene-render';`,
  resolveDir: process.cwd(), loader: 'ts' }, bundle: true, write: false, platform: 'node', format: 'esm',
  define: { 'import.meta.env.BASE_URL': '"/"' }, logLevel: 'error' });
const c = await import(`data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].text).toString('base64')}`);
const sleep = ms => new Promise(r => setTimeout(r, ms));
const record = { version: c.STRAND_RECORD_VERSION, item_id: 'hair', fit_sha256: 'aaa' };
const resp = (status, etag, body = record) => ({ ok: status >= 200 && status < 300, status,
  headers: { get: k => (k.toLowerCase() === 'etag' ? etag : null) }, json: async () => body });
let answers = [], downloads = 0;
globalThis.fetch = async () => { downloads++; return answers.shift(); };
const origWarn = console.warn; console.warn = () => {};
const lib = new c.FigureLibrary();
const ref = sha => ({ url: '/characters/demo/model/hair-strands', sha256: sha });

answers = [resp(200, '"bbb"')];
assert.equal(lib.strandRecord(ref('aaa')), undefined); await sleep(0);
assert.equal(lib.strandRecord(ref('aaa')), undefined, '[a] another record is not kept under aaa');
assert.equal(downloads, 1, '[a] no second download inside the retry time');
lib.strandRetryAt.set('aaa', 0);                       // the retry time has passed
answers = [resp(200, '"aaa"')];
assert.equal(lib.strandRecord(ref('aaa')), undefined); await sleep(0);
assert.equal(downloads, 2, '[a] asked again after the retry time');
assert.deepEqual(lib.strandRecord(ref('aaa')), record, '[d] the matching record');
console.log('PASS [a] mismatching ETag not cached, retried; [d] matching record kept');

answers = [resp(503, null)];
assert.equal(lib.strandRecord(ref('ccc')), undefined); await sleep(0);
assert.equal(lib.strandRecord(ref('ccc')), undefined, '[b] a 503 is not a null for the session');
assert.equal(downloads, 3);
lib.strandRetryAt.set('ccc', 0);
answers = [resp(200, '"ccc"', { ...record, fit_sha256: 'ccc' })];
lib.strandRecord(ref('ccc')); await sleep(0);
assert.equal(lib.strandRecord(ref('ccc')).fit_sha256, 'ccc', '[b] loads once the server is back');
console.log('PASS [b] a passing failure is retried');

answers = [resp(404, null)];
lib.strandRecord(ref('ddd')); await sleep(0);
assert.equal(lib.strandRecord(ref('ddd')), null, '[c] 404 = no strands');
assert.equal(downloads, 5, '[c] no further download');
console.warn = origWarn;
console.log('PASS smoke_strand_record: 3 cases');
