/**
 * Smoke run for `frontend/src/tabs/map/pendingBuffer.ts` — the map editor's
 * change buffer, the local half of the batch save (plan-map-save-batch.md).
 *
 * Usage:  node scripts/smoke_pending_buffer.mjs
 *         (transforms the module with esbuild — a Vite dependency, already
 *          installed; no bundler, no jsdom, no server)
 *
 * Every expectation below is derived BY HAND from the rules the module states,
 * never recorded from its output.
 *
 * ---------------------------------------------------------------------------
 * [1] LAST WINS, AND THE STAMP IS THE ONE FROM THE LOAD
 * ---------------------------------------------------------------------------
 * The buffer holds the last DECISION per object, not a journal: dragging one
 * vertex six times is one upsert on the wire, and the six intermediate
 * polygons were never anything the server would have kept.
 *
 *   queueUpsert(∅,  "a", v1, "S1")            -> size 1, op upsert, obj v1
 *   queueUpsert(…,  "a", v2, "S9")            -> size 1, op upsert, obj v2,
 *                                                stamp STILL "S1"
 * The stamp must not follow the later call: it is the version the object was
 * LOADED at, and it is what the server judges the change against. A stamp
 * refreshed on every edit would make the concurrency check always pass, i.e.
 * silently overwrite whatever somebody else saved in between.
 *
 * ---------------------------------------------------------------------------
 * [2] THE FOUR SEQUENCES
 * ---------------------------------------------------------------------------
 *   upsert(a) then delete(a)   -> ONE entry, op delete   (a stored object)
 *   delete(a) then upsert(a)   -> ONE entry, op upsert   (drawn over again)
 *   NEW(t1)  then delete(t1)   -> the buffer is EMPTY: an object that never
 *                                 reached the server has nothing to delete
 *                                 there, and sending its temp id would ask
 *                                 the server about a name it never heard
 *   NEW(t1)  then upsert(t1)   -> ONE entry, still carrying tempId "t1"
 *
 * ---------------------------------------------------------------------------
 * [3] THE REQUEST BODY
 * ---------------------------------------------------------------------------
 * With a buffer holding
 *   "a"  upsert, stamp "S1"          (a stored area, edited)
 *   "t1" upsert, tempId "t1"          (a new area)
 *   "b"  delete, stamp "S2"
 * `toBulkBody` produces
 *   upserts: [{id: "a", kind: "grass", updated_at: "S1"},
 *             {kind: "water", temp_id: "t1"}]        <- NO id at all
 *   deletes: [{id: "b", updated_at: "S2"}]
 * The new object drops its local id on purpose: it is a placeholder the server
 * has never seen, and sending it as `id` would make the server treat a
 * never-stored object as an existing one (and refuse it as "deleted on the
 * server"). An entry whose stamp is unknown ("") sends NO `updated_at`, which
 * the server reads as a deliberate overwrite — what the singular PUT did.
 *
 * ---------------------------------------------------------------------------
 * [4] WHAT SURVIVES A SAVE
 * ---------------------------------------------------------------------------
 * Three objects go out; the answer refuses two of them:
 *   [{op: "upsert", id: "a",  temp_id: "",   reason: "changed on the server"},
 *    {op: "upsert", id: "",   temp_id: "t1", reason: "at most 500 …"}]
 * `keepRejected` keeps EXACTLY those two, each with its reason, and drops the
 * third — it is on the server now. A rejection names a new object by its temp
 * id (the server knows no other name for it) and an existing one by its id.
 *   hasConflicts -> true
 *   dropConflicts -> empty (what an explicit Reload does: taking the
 *                    server's version IS the resolution)
 *
 * ---------------------------------------------------------------------------
 * [5] THE DRAFT OVER THE SERVER'S LIST
 * ---------------------------------------------------------------------------
 * `applyPending` is what keeps a refetch from eating unsaved work. Server list
 * [a, b, c] with a buffer holding "a" edited, "b" deleted and "t1" newly drawn
 * gives [a', c, t1]: the server's ORDER is kept, the deleted one is gone, and
 * the new one comes last — where it was drawn. An empty buffer returns the
 * very same array (no copy, so nothing re-renders for nothing).
 */
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const SRC = join(fileURLToPath(new URL('..', import.meta.url)),
  'frontend/src/tabs/map/pendingBuffer.ts');

/** The module, transformed and imported — it has no imports of its own, so a
 *  single-file transform is enough (the `smoke_height_math.mjs` recipe). */
async function loadBuffer() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'pendingbuffer-smoke-'));
  try {
    const source = await readFile(SRC, 'utf8');
    const out = esbuild.transformSync(source, { loader: 'ts', format: 'esm' });
    const file = join(dir, 'pendingBuffer.mjs');
    await writeFile(file, out.code, 'utf8');
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

let failed = 0;
let passed = 0;
function check(label, actual, expected) {
  const a = JSON.stringify(actual);
  const b = JSON.stringify(expected);
  if (a === b) {
    passed += 1;
    console.log(`  ok   ${label}`);
  } else {
    failed += 1;
    console.log(`  FAIL ${label}\n       expected ${b}\n       actual   ${a}`);
  }
}

const {
  emptyBuffer, pendingCount, isDirty, hasConflicts, queueUpsert, queueDelete,
  dropPending, dropConflicts, toBulkBody, keepRejected, applyPending,
} = await loadBuffer();

const V1 = { id: 'a', kind: 'grass', z: 1 };
const V2 = { id: 'a', kind: 'grass', z: 2 };

console.log('[1] last wins, and the stamp is the one from the load');
let buf = emptyBuffer();
check('an empty buffer is not dirty', [pendingCount(buf), isDirty(buf)],
  [0, false]);
buf = queueUpsert(buf, 'a', V1, 'S1');
check('one edit is one entry', pendingCount(buf), 1);
buf = queueUpsert(buf, 'a', V2, 'S9');
check('a second edit of the same object is still one entry',
  pendingCount(buf), 1);
check('…carrying the LAST version', buf.get('a').obj, V2);
check('…and the stamp of the FIRST one', buf.get('a').stamp, 'S1');
check('…which is what the request then sends',
  toBulkBody(buf).upserts, [{ id: 'a', kind: 'grass', z: 2, updated_at: 'S1' }]);

console.log('\n[2] the four sequences');
buf = queueDelete(queueUpsert(emptyBuffer(), 'a', V1, 'S1'), 'a', V1, 'S1');
check('upsert then delete is one delete',
  [pendingCount(buf), buf.get('a').op], [1, 'delete']);
buf = queueUpsert(queueDelete(emptyBuffer(), 'a', V1, 'S1'), 'a', V2, 'S1');
check('delete then upsert is one upsert',
  [pendingCount(buf), buf.get('a').op, buf.get('a').obj],
  [1, 'upsert', V2]);
const NEW1 = { id: 't1', kind: 'water' };
buf = queueDelete(queueUpsert(emptyBuffer(), 't1', NEW1, '', 't1'),
  't1', NEW1, '');
check('a NEW object deleted again leaves nothing behind',
  [pendingCount(buf), toBulkBody(buf)],
  [0, { upserts: [], deletes: [] }]);
buf = queueUpsert(queueUpsert(emptyBuffer(), 't1', NEW1, '', 't1'),
  't1', { id: 't1', kind: 'river' }, '');
check('a NEW object edited again keeps its temp id',
  [pendingCount(buf), buf.get('t1').tempId, buf.get('t1').obj.kind],
  [1, 't1', 'river']);

console.log('\n[3] the request body');
buf = emptyBuffer();
buf = queueUpsert(buf, 'a', { id: 'a', kind: 'grass' }, 'S1');
buf = queueUpsert(buf, 't1', { id: 't1', kind: 'water' }, '', 't1');
buf = queueDelete(buf, 'b', { id: 'b', kind: 'sand' }, 'S2');
check('the whole body, in buffer order', toBulkBody(buf), {
  upserts: [{ id: 'a', kind: 'grass', updated_at: 'S1' },
    { kind: 'water', temp_id: 't1' }],
  deletes: [{ id: 'b', updated_at: 'S2' }],
});
check('an object with no known stamp sends none',
  toBulkBody(queueUpsert(emptyBuffer(), 'a', { id: 'a', kind: 'grass' }, ''))
    .upserts, [{ id: 'a', kind: 'grass' }]);

console.log('\n[4] what survives a save');
const kept = keepRejected(buf, [
  { op: 'upsert', id: 'a', temp_id: '', reason: 'changed on the server' },
  { op: 'upsert', id: '', temp_id: 't1', reason: 'at most 500 world props per world' },
]);
check('exactly the refused objects stay, with their reason',
  [pendingCount(kept), kept.get('a').reason, kept.get('t1').reason,
    kept.has('b')],
  [2, 'changed on the server', 'at most 500 world props per world', false]);
check('a buffer with a refusal in it says so',
  [hasConflicts(kept), hasConflicts(buf)], [true, false]);
check('and an explicit reload clears exactly those',
  pendingCount(dropConflicts(kept)), 0);
check('a saved object can also be forgotten one by one',
  pendingCount(dropPending(buf, 'a')), 2);

console.log('\n[5] the draft over the server\'s list');
const SERVER = [{ id: 'a', kind: 'grass' }, { id: 'b', kind: 'sand' },
  { id: 'c', kind: 'rock' }];
let draft = emptyBuffer();
draft = queueUpsert(draft, 'a', { id: 'a', kind: 'water' }, 'S1');
draft = queueDelete(draft, 'b', { id: 'b', kind: 'sand' }, 'S2');
draft = queueUpsert(draft, 't1', { id: 't1', kind: 'river' }, '', 't1');
check('the edit replaces, the deletion is gone, the new one comes last',
  applyPending(SERVER, draft),
  [{ id: 'a', kind: 'water' }, { id: 'c', kind: 'rock' },
    { id: 't1', kind: 'river' }]);
check('an empty buffer hands the very same array back',
  applyPending(SERVER, emptyBuffer()) === SERVER, true);

console.log(`\n${passed + failed} checks, ${failed} failures`);
process.exit(failed ? 1 : 0);
