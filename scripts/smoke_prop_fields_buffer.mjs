/**
 * Smoke run for `frontend/src/tabs/props/pendingFields.ts` — the prop detail's
 * change buffer, the local half of its batch save.
 *
 * Usage:  node scripts/smoke_prop_fields_buffer.mjs
 *         (transforms the module with esbuild — a Vite dependency, already
 *          installed; no bundler, no jsdom, no server)
 *
 * Every expectation below is derived BY HAND from the rules the module states,
 * never recorded from its output.
 *
 * ---------------------------------------------------------------------------
 * [1] FIELDS MERGE, AND WITHIN A FIELD THE LAST ONE WINS
 * ---------------------------------------------------------------------------
 * This is the ONE difference to the map editor's `pendingBuffer`, which holds
 * whole objects and lets the last one replace the one before it. A prop detail
 * edits FIELDS of records that already exist, so the size, then the subject,
 * then a marker of the SAME variant must all survive:
 *
 *   queueFields(∅,  "v:0", {dims: D1})            -> {dims: D1}
 *   queueFields(…,  "v:0", {description: "a"})    -> {dims: D1, description: "a"}
 *   queueFields(…,  "v:0", {description: "b"})    -> {dims: D1, description: "b"}
 *
 * Two fields of one variant, not two entries and not one that ate the other.
 *
 * ---------------------------------------------------------------------------
 * [2] THE NUMBER IN "SAVE (n)" COUNTS FIELDS
 * ---------------------------------------------------------------------------
 * Fields, not targets — "Save (1)" for a whole rewritten variant would say
 * nothing about how much work is unsaved. The buffer above is therefore 2, and
 * with the prop's own name on top it is 3:
 *
 *   general {name}          1
 *   v:0     {dims, description}   2      -> pendingFieldCount = 3
 *
 * THE DIMS TRIO IS ONE FIELD. It travels as one `dims` object because a prop
 * is scaled uniformly — the three numbers are one statement (how big, and what
 * shape) — so one resize is "Save (1)" and not "Save (3)".
 *
 * ---------------------------------------------------------------------------
 * [3] THE REQUEST BODY
 * ---------------------------------------------------------------------------
 * The same buffer produces exactly
 *
 *   {general: {name: "Bench"},
 *    variants: {"0": {dims: D1, description: "b"}}}
 *
 * — the variant key is the STORE INDEX as a string, which is what the batch
 * route reads, and an empty half is left out entirely so a body says what it
 * changes and nothing else. An empty buffer is `{}`.
 *
 * ---------------------------------------------------------------------------
 * [4] A DELETED VARIANT TAKES ITS FIELDS WITH IT — AND RENUMBERS THE REST
 * ---------------------------------------------------------------------------
 * Deleting a variant is an IMMEDIATE operation (it removes meshes and a source
 * image and renumbers the stored list), so the draft has to follow it. With
 *
 *   general {name}, v:0 {description}, v:1 {dims}, v:2 {markers}
 *
 * deleting variant 1 gives
 *
 *   general {name}, v:0 {description}, v:1 {markers}
 *
 * The deleted variant's field is gone — there is nothing left to save it onto
 * — and the one that stood BEHIND it moved down by one, because the server pops
 * the entry out of the list and renumbers exactly that way. Leaving it at "v:2"
 * would write one variant's unsaved marker list onto a stranger, and leaving it
 * at "v:2" with only two variants stored would be a 400.
 *
 * ---------------------------------------------------------------------------
 * [5] THE DRAFT OVER THE SERVER'S LIST
 * ---------------------------------------------------------------------------
 * `applyVariantDraft` is what keeps a reload from eating unsaved work — and a
 * reload happens on its own here, because the immediate operations beside the
 * draft (a finished mesh, an added variant) refetch the list. Server list
 *
 *   [0] 1 × 1 × 1, estimated true,  description ""
 *   [1] 2 × 2 × 2, estimated false, description "grown"
 *
 * with a buffer holding v:1 {dims: {height_m: 4}, description: "sapling"}:
 *
 *   [0] untouched — the very same object
 *   [1] 2 × 2 × 4  (the patch MERGES into the stored trio: a patch may name
 *                   one metre, the other two are still the stored ones)
 *       estimated FALSE (storing a size clears the flag, so the "estimated"
 *                        hint must not go on claiming the number is a guess)
 *       description "sapling"
 *
 * An empty buffer hands the very same array back, so nothing re-renders for
 * nothing.
 *
 * ---------------------------------------------------------------------------
 * [6] WHAT A FIELD SAYS RIGHT NOW
 * ---------------------------------------------------------------------------
 * `draftValue` answers with the buffered value once the field was edited and
 * with the stored one before that. Every commit compares against THAT: a field
 * typed away and back must end up with what is on screen, and a comparison
 * against the server's value would leave the first edit standing in the buffer
 * while the input shows the second.
 */
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const SRC = join(fileURLToPath(new URL('..', import.meta.url)),
  'frontend/src/tabs/props/pendingFields.ts');

/** The module, transformed and imported — it has no imports of its own, so a
 *  single-file transform is enough (the `smoke_pending_buffer.mjs` recipe). */
async function loadModule() {
  const esbuild = await import('esbuild');
  const dir = await mkdtemp(join(tmpdir(), 'propfields-smoke-'));
  try {
    const source = await readFile(SRC, 'utf8');
    const out = esbuild.transformSync(source, { loader: 'ts', format: 'esm' });
    const file = join(dir, 'pendingFields.mjs');
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
  GENERAL_TARGET, variantTarget, emptyFields, queueFields, pendingFieldCount,
  isFieldsDirty, draftValue, dropDeletedVariant, toBulkFieldBody,
  applyVariantDraft,
} = await loadModule();

const D1 = { width_m: 1, depth_m: 1, height_m: 1 };

console.log('[1] fields merge, and within a field the last one wins');
let buf = emptyFields();
check('an empty buffer is not dirty', [pendingFieldCount(buf), isFieldsDirty(buf)],
  [0, false]);
buf = queueFields(buf, variantTarget(0), { dims: D1 });
check('one edit is one field', pendingFieldCount(buf), 1);
buf = queueFields(buf, variantTarget(0), { description: 'a' });
check('another field of the same variant is kept beside it',
  buf.get('v:0'), { dims: D1, description: 'a' });
buf = queueFields(buf, variantTarget(0), { description: 'b' });
check('…and the same field again is the last value only',
  [buf.size, buf.get('v:0')], [1, { dims: D1, description: 'b' }]);

console.log('\n[2] the number in "Save (n)" counts fields');
check('two fields of one variant', pendingFieldCount(buf), 2);
buf = queueFields(buf, GENERAL_TARGET, { name: 'Bench' });
check('…plus the prop\'s own name', pendingFieldCount(buf), 3);
check('a whole resize is ONE field, not three',
  pendingFieldCount(queueFields(emptyFields(), variantTarget(2),
    { dims: { width_m: 3, depth_m: 4, height_m: 5 } })), 1);

console.log('\n[3] the request body');
check('general and variants, keyed by store index', toBulkFieldBody(buf), {
  general: { name: 'Bench' },
  variants: { 0: { dims: D1, description: 'b' } },
});
check('an empty buffer asks for nothing', toBulkFieldBody(emptyFields()), {});
check('a variant-only draft carries no general half',
  toBulkFieldBody(queueFields(emptyFields(), variantTarget(1), { seasons: [] })),
  { variants: { 1: { seasons: [] } } });
check('a general-only draft carries no variants half',
  toBulkFieldBody(queueFields(emptyFields(), GENERAL_TARGET, { tags: 'a, b' })),
  { general: { tags: 'a, b' } });

console.log('\n[4] a deleted variant takes its fields with it');
let del = emptyFields();
del = queueFields(del, GENERAL_TARGET, { name: 'Bench' });
del = queueFields(del, variantTarget(0), { description: 'grown' });
del = queueFields(del, variantTarget(1), { dims: D1 });
del = queueFields(del, variantTarget(2), { markers: [] });
del = dropDeletedVariant(del, 1);
check('its own field is gone, the one behind it moved down by one',
  toBulkFieldBody(del),
  { general: { name: 'Bench' },
    variants: { 0: { description: 'grown' }, 1: { markers: [] } } });
check('…and the count follows', pendingFieldCount(del), 3);
check('deleting a variant nothing was drafted for changes nothing',
  toBulkFieldBody(dropDeletedVariant(
    queueFields(emptyFields(), variantTarget(0), { dims: D1 }), 3)),
  { variants: { 0: { dims: D1 } } });

console.log('\n[5] the draft over the server\'s list');
const SERVER = [
  { index: 0, dims: { width_m: 1, depth_m: 1, height_m: 1 },
    dims_estimated: true, description: '', ground_offset_m: 0, markers: [],
    seasons: [] },
  { index: 1, dims: { width_m: 2, depth_m: 2, height_m: 2 },
    dims_estimated: false, description: 'grown', ground_offset_m: 0,
    markers: [], seasons: [] },
];
const draft = queueFields(
  queueFields(emptyFields(), variantTarget(1), { dims: { height_m: 4 } }),
  variantTarget(1), { description: 'sapling' });
const shown = applyVariantDraft(SERVER, draft);
check('the untouched variant is the very same object', shown[0] === SERVER[0],
  true);
check('the patched one merges into the stored trio', shown[1].dims,
  { width_m: 2, depth_m: 2, height_m: 4 });
check('…a typed size is no longer an estimate', shown[1].dims_estimated, false);
check('…and the other field of the same patch is there too',
  shown[1].description, 'sapling');
check('the server\'s record is not mutated', SERVER[1].dims.height_m, 2);
check('an empty buffer hands the very same array back',
  applyVariantDraft(SERVER, emptyFields()) === SERVER, true);

console.log('\n[6] what a field says right now');
check('an edited field answers with the draft',
  draftValue(buf, GENERAL_TARGET, 'name', 'Chair'), 'Bench');
check('an untouched one answers with what is stored',
  draftValue(buf, GENERAL_TARGET, 'category', 'seating'), 'seating');
check('…and so does every field of an untouched target',
  draftValue(buf, variantTarget(9), 'description', 'stored'), 'stored');

console.log(`\n${passed + failed} checks, ${failed} failures`);
process.exit(failed ? 1 : 0);
