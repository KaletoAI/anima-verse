#!/usr/bin/env node
/**
 * Check of Ruling A64's remaining UI piece — the Delete of a stored body shape (Figure tab's stored list and the piece
 * dialog's body switch): the pure helpers of `frontend/src/tabs/characters/storedDeleteModel.ts` and the wiring by
 * source greps. A64's other piece, the extension line beside the model viewer, is gone: Ruling A73 took it out of
 * the Figure tab, Ruling A78 (user: "remove this text from all 3D previews") out of every preview, with its helper,
 * component, payload field and de.json keys — [3] pins that.
 *
 * Usage:  node scripts/check_a64_ui.mjs
 *
 * Self-bundling via esbuild (like scripts/check_base_body_ui.mjs); no server, no world. Exit 1 with the mismatch
 * list, 0 when every case holds. The server half is scripts/smoke_figure_stored_delete.py.
 *
 * ============================================================================
 * THE CASES, DERIVED BY HAND
 * ============================================================================
 * [1] refusalText: "running" → "A run works on it now — delete it after the run."; "current" → "The figure stands
 *     on it now — take off what is worn in the body, then delete it."; "needed" with reason "shape of a live outfit"
 *     → "An outfit would be built on it now (shape of a live outfit)."; "" → "".
 * [2] deleteLines, shape {files 10, bytes 40960, outfit_models ["Casual"], running []} →
 *       removed ["10 files · 0.0 MB", "The outfit models built on it: Casual"];
 *       due ["Nothing becomes due now: no outfit would be built on it.", "An outfit that needs this body shape again
 *            meshes it anew (hub jobs).", "Wearing one of those outfits again builds its model anew."].
 *     Texture {files 3, bytes 2.5e6, outfit_models [], running ["k"]} → removed ["3 files · 2.5 MB"]; due [nothing
 *     due, "An outfit that needs this painted body again paints it anew (hub jobs).", "A run works on 1 of its parts
 *     — those stay."]. megabytes(1234567) = "1.2 MB".
 *     storedState (checklist point 8, a light per row): running → blue "a run works on it"; current → green "in use
 *     now"; not deletable → green "needed by an outfit now"; deletable with history → grey "kept only by an outfit
 *     model built on it"; deletable otherwise → grey "stored, not needed now". FigureStored renders that light.
 * [3] Source greps — no extension note anywhere (Rulings A73, A78): Model3DViewer names no `extensionNote`; neither
 *     FieldFigure nor FieldModel3D names `extensionNote`, `ExtensionPresenceNote` or `extension_presence`;
 *     `extensionPresence.ts` and `ExtensionPresenceNote.tsx` do not exist; app/core/model3d.py names no
 *     `extension_presence` (the 3D payload carries no note); the Figure payload type (figureModel.ts) and
 *     figure_build.py carry no `served_extension`; de.json holds none of the note's six strings ("Extension bones on
 *     this model: {ids}", "Extension bones: none on this model", "Not declared for this character: {ids}", "Covered",
 *     the covered reason, the not-on-this-model reason).
 * [4] Source greps — the Delete: StoredDeleteDialog renders through createPortal to document.body, loads
 *     `${path}/preview`, deletes with apiDelete(path), and shows no Delete button when the preview says not deletable
 *     (`preview && !preview.deletable ? null`); FigureStored uses StoredDeleteDialog and no ConfirmDialog, labels its
 *     button "Delete…", writes refusalText under a row that cannot be deleted. The piece dialog's body switch offers
 *     no Delete (Ruling A64 after A67: it lists only the base body and the current body, and the current one is
 *     never deletable) — FitBodySwitch names no StoredDeleteDialog and no "Delete this body shape". No
 *     window.confirm anywhere in these files. de.json holds a key for every string of [1]–[2] and the list's button.
 */
import { existsSync, readFileSync } from 'node:fs';
import { mkdtemp, rm } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const require_ = createRequire(import.meta.url);
const fails = [];
const eq = (label, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${label}${ok ? '' : `\n      got  ${JSON.stringify(got)}\n      want ${JSON.stringify(want)}`}`);
  if (!ok) fails.push(label);
};

function esbuildModule() {
  for (const cand of ['esbuild', join(ROOT, 'frontend/node_modules/esbuild'), join(ROOT, 'client3d/node_modules/esbuild')]) {
    try { return require_(cand); } catch { /* next candidate */ }
  }
  console.error('esbuild not found (npm install) — nothing was checked');
  process.exit(1);
}

async function loadBundled(src) {
  const esbuild = esbuildModule();
  const dir = await mkdtemp(join(tmpdir(), 'check-a64-ui-'));
  try {
    const file = join(dir, 'module.mjs');
    await esbuild.build({ entryPoints: [join(ROOT, src)], outfile: file, bundle: true, format: 'esm',
      platform: 'neutral', logLevel: 'silent', absWorkingDir: ROOT });
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

const src = (rel) => readFileSync(join(ROOT, rel), 'utf8');
const has = (label, text, needle) => eq(label, text.includes(needle), true);
const lacks = (label, text, needle) => eq(label, text.includes(needle), false);

const S = await loadBundled('frontend/src/tabs/characters/storedDeleteModel.ts');

// [1]
eq('[1] running', S.refusalText('running', ''), 'A run works on it now — delete it after the run.');
eq('[1] current', S.refusalText('current', ''),
  'The figure stands on it now — take off what is worn in the body, then delete it.');
eq('[1] needed', S.refusalText('needed', 'shape of a live outfit'),
  'An outfit would be built on it now (shape of a live outfit).');
eq('[1] deletable', S.refusalText('', 'x'), '');

// [2]
const files = (n) => Array.from({ length: n }, (_, i) => `f${i}`);
eq('[2] shape', S.deleteLines({ kind: 'shape', files: files(10), bytes: 40960, outfit_models: ['Casual'], running: [] }), {
  removed: ['10 files · 0.0 MB', 'The outfit models built on it: Casual'],
  due: ['Nothing becomes due now: no outfit would be built on it.',
    'An outfit that needs this body shape again meshes it anew (hub jobs).',
    'Wearing one of those outfits again builds its model anew.'],
});
eq('[2] texture', S.deleteLines({ kind: 'texture', files: files(3), bytes: 2.5e6, outfit_models: [], running: ['k'] }), {
  removed: ['3 files · 2.5 MB'],
  due: ['Nothing becomes due now: no outfit would be built on it.',
    'An outfit that needs this painted body again paints it anew (hub jobs).',
    'A run works on 1 of its parts — those stay.'],
});
eq('[2] megabytes', S.megabytes(1234567), '1.2 MB');
const row = (o) => ({ running: false, current: false, deletable: true, refusal: '', history: false, ...o });
eq('[2] storedState', [row({ running: true, deletable: false, refusal: 'running' }),
  row({ current: true, deletable: false, refusal: 'current' }), row({ deletable: false, refusal: 'needed' }),
  row({ history: true }), row({})].map((e) => S.storedState(e)), [
  { light: 'blue', text: 'a run works on it' }, { light: 'green', text: 'in use now' },
  { light: 'green', text: 'needed by an outfit now' },
  { light: 'grey', text: 'kept only by an outfit model built on it' },
  { light: 'grey', text: 'stored, not needed now' }]);

// [3]
const NOTE = /extensionNote|ExtensionPresenceNote|extension_presence/;
eq('[3] viewer: no extensionNote (A78)', /extensionNote/.test(src('frontend/src/tabs/characters/Model3DViewer.tsx')), false);
eq('[3] Figure tab: no note (A73)', NOTE.test(src('frontend/src/tabs/characters/FieldFigure.tsx')), false);
eq('[3] 3D tab: no note (A78)', NOTE.test(src('frontend/src/tabs/characters/FieldModel3D.tsx')), false);
eq('[3] helper and component gone (A78)', ['extensionPresence.ts', 'ExtensionPresenceNote.tsx']
  .map((f) => existsSync(join(ROOT, 'frontend/src/tabs/characters', f))), [false, false]);
lacks('[3] 3D payload: no extension_presence (A78)', src('app/core/model3d.py'), 'extension_presence');
lacks('[3] Figure payload type: no served_extension (A73)', src('frontend/src/tabs/characters/figureModel.ts'),
  'served_extension');
lacks('[3] figure_build: no served_extension (A73)', src('app/core/figure_build.py'), 'served_extension');
const deAll = JSON.parse(src('shared/languages/de.json')).translations;
eq('[3] de.json: none of the note strings (A78)', ['Extension bones on this model: {ids}',
  'Extension bones: none on this model', 'Not declared for this character: {ids}', 'Covered',
  'Covered by {pieces} on this model: a covered slot has no part and no bones — correct, nothing to rebuild.',
  'Not on this model: it was built before the group applied. The next Build rebuilds it (local, no hub job).']
  .filter((k) => k in deAll), []);

// [4]
const dialog = src('frontend/src/tabs/characters/StoredDeleteDialog.tsx');
has('[4] dialog: portal', dialog, 'createPortal(');
has('[4] dialog: to body', dialog, 'document.body');
has('[4] dialog: loads the preview', dialog, 'apiGet<StoredDeletePreview>(`${path}/preview`)');
has('[4] dialog: deletes', dialog, 'await apiDelete(path)');
has('[4] dialog: no Delete when refused', dialog, '{preview && !preview.deletable ? null : (');
const stored = src('frontend/src/tabs/characters/FigureStored.tsx');
has('[4] stored list uses the dialog', stored, '<StoredDeleteDialog');
lacks('[4] stored list: no ConfirmDialog', stored, 'ConfirmDialog');
has('[4] stored list: Delete…', stored, "t('Delete…')");
has('[4] stored list: refusal in words', stored, 'refusalText(');
has('[4] stored list: a light per row', stored, '<StepLight light={storedState(e, t).light} />');
const sw = src('frontend/src/tabs/characters/FitBodySwitch.tsx');
lacks('[4] body switch: no Delete dialog (A67)', sw, 'StoredDeleteDialog');
lacks('[4] body switch: no Delete button (A67)', sw, 'Delete this body shape');
for (const [name, text] of [['dialog', dialog], ['stored', stored], ['switch', sw]]) {
  lacks(`[4] ${name}: no window.confirm`, text, 'window.confirm');
}
const de = JSON.parse(src('shared/languages/de.json')).translations;
const keys = ['A run works on it now — delete it after the run.',
  'The figure stands on it now — take off what is worn in the body, then delete it.',
  'An outfit would be built on it now ({reason}).', '{n} files · {size}', 'The outfit models built on it: {names}',
  'Nothing becomes due now: no outfit would be built on it.',
  'An outfit that needs this body shape again meshes it anew (hub jobs).',
  'An outfit that needs this painted body again paints it anew (hub jobs).',
  'Wearing one of those outfits again builds its model anew.', 'A run works on {n} of its parts — those stay.',
  'Delete…', 'a run works on it', 'needed by an outfit now', 'in use now',
  'kept only by an outfit model built on it', 'stored, not needed now'];
eq('[4] de.json keys', keys.filter((k) => !de[k]), []);
if (!existsSync(join(ROOT, 'frontend/src/tabs/characters/storedDeleteModel.ts'))) fails.push('model missing');

console.log(fails.length ? `\n${fails.length} FAILED` : '\nALL OK');
process.exit(fails.length ? 1 : 0);
