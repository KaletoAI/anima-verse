#!/usr/bin/env node
/**
 * Check of Ruling A64's two UI pieces — the extension line beside the model viewer (3D tab only since Ruling A73) and the
 * Delete of a stored body shape (Figure tab's stored list and the piece dialog's body switch): the pure helpers of
 * `frontend/src/tabs/characters/extensionPresence.ts` and `storedDeleteModel.ts`, the note rendered once
 * (react-dom/server), and the wiring by source greps.
 *
 * Usage:  node scripts/check_a64_ui.mjs
 *
 * Self-bundling via esbuild (like scripts/check_base_body_ui.mjs); no server, no world. Exit 1 with the mismatch
 * list, 0 when every case holds. The server halves are scripts/smoke_extension_presence.py and
 * scripts/smoke_figure_stored_delete.py.
 *
 * ============================================================================
 * THE CASES, DERIVED BY HAND
 * ============================================================================
 * [1] presenceLines (en), the payload of the served outfit model in the incident, ids neutral here:
 *     {built [], missing [{id "chain_a", light grey, state "Covered", reason "Covered by {pieces} on this model: a
 *     covered slot has no part and no bones — correct, nothing to rebuild.", pieces ["Jeans", "Underwear"]}],
 *     not_declared ["pair_b", "inset_c"]} →
 *       line 1: light null, "Extension bones: none on this model";
 *       line 2: light grey, "chain_a: Covered — Covered by Jeans, Underwear on this model: a covered slot has no part
 *               and no bones — correct, nothing to rebuild.";
 *       line 3: light null, "Not declared for this character: pair_b, inset_c".
 *     The base: {built ["chain_a", "sack_d"], missing [], not_declared []} → one line, green, "Extension bones on this
 *     model: chain_a, sack_d". null → []; all three lists empty → [].
 *     A missing group with detail "D" carries title "D"; without one, no title.
 * [2] refusalText: "running" → "A run works on it now — delete it after the run."; "current" → "The figure stands
 *     on it now — take off what is worn in the body, then delete it."; "needed" with reason "shape of a live outfit"
 *     → "An outfit would be built on it now (shape of a live outfit)."; "" → "".
 * [3] deleteLines, shape {files 10, bytes 40960, outfit_models ["Casual"], running []} →
 *       removed ["10 files · 0.0 MB", "The outfit models built on it: Casual"];
 *       due ["Nothing becomes due now: no outfit would be built on it.", "An outfit that needs this body shape again
 *            meshes it anew (hub jobs).", "Wearing one of those outfits again builds its model anew."].
 *     Texture {files 3, bytes 2.5e6, outfit_models [], running ["k"]} → removed ["3 files · 2.5 MB"]; due [nothing
 *     due, "An outfit that needs this painted body again paints it anew (hub jobs).", "A run works on 1 of its parts
 *     — those stay."]. megabytes(1234567) = "1.2 MB".
 *     storedState (checklist point 8, a light per row): running → blue "a run works on it"; current → green "in use
 *     now"; not deletable → green "needed by an outfit now"; deletable with history → grey "kept only by an outfit
 *     model built on it"; deletable otherwise → grey "stored, not needed now". FigureStored renders that light.
 * [4] The note rendered once (en, react-dom/server) with [1]'s payload holds the three lines' text; with null it
 *     renders nothing ("").
 * [5] Source greps — the viewer: Model3DViewer takes `extensionNote` and renders `{extensionNote}`, and its toggle
 *     column shows when only the note is there (`|| extensionNote)`); FieldModel3D passes
 *     `<ExtensionPresenceNote presence={model.extension_presence} />`. Ruling A73 (user: "Im Figur-Tab 3D-Vorschau
 *     den Text raus"): FieldFigure names neither `extensionNote` nor `ExtensionPresenceNote`, and the Figure payload
 *     type (figureModel.ts) and figure_build.py carry no `served_extension`.
 * [6] Source greps — the Delete: StoredDeleteDialog renders through createPortal to document.body, loads
 *     `${path}/preview`, deletes with apiDelete(path), and shows no Delete button when the preview says not deletable
 *     (`preview && !preview.deletable ? null`); FigureStored uses StoredDeleteDialog and no ConfirmDialog, labels its
 *     button "Delete…", writes refusalText under a row that cannot be deleted. The piece dialog's body switch offers
 *     no Delete (Ruling A64 after A67: it lists only the base body and the current body, and the current one is
 *     never deletable) — FitBodySwitch names no StoredDeleteDialog and no "Delete this body shape". No
 *     window.confirm anywhere in these files. de.json holds a key for every string of [1]–[3] and the list's button.
 */
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
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

async function renderNote(presence) {
  const esbuild = esbuildModule();
  const dir = await mkdtemp(join(tmpdir(), 'check-a64-ui-ssr-'));
  try {
    const entry = join(dir, 'entry.tsx');
    const file = join(dir, 'ssr.cjs');
    const at = (rel) => JSON.stringify(join(ROOT, rel));
    writeFileSync(entry, [
      `import { renderToStaticMarkup } from 'react-dom/server'`,
      `import { I18nProvider } from ${at('frontend/src/i18n/I18nProvider.tsx')}`,
      `import { ExtensionPresenceNote } from ${at('frontend/src/tabs/characters/ExtensionPresenceNote.tsx')}`,
      `export const render = (p) => renderToStaticMarkup(<I18nProvider><ExtensionPresenceNote presence={p} /></I18nProvider>)`,
    ].join('\n'));
    await esbuild.build({ entryPoints: [entry], outfile: file, bundle: true, format: 'cjs', platform: 'node',
      jsx: 'automatic', logLevel: 'silent', absWorkingDir: ROOT, nodePaths: [join(ROOT, 'node_modules')],
      define: { 'process.env.NODE_ENV': '"production"' }, loader: { '.css': 'empty' } });
    return require_(file).render(presence);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

const src = (rel) => readFileSync(join(ROOT, rel), 'utf8');
const has = (label, text, needle) => eq(label, text.includes(needle), true);
const lacks = (label, text, needle) => eq(label, text.includes(needle), false);
const unescape = (s) => s.replace(/&amp;/g, '&').replace(/&#x27;/g, "'").replace(/&quot;/g, '"');

const COVERED = 'Covered by {pieces} on this model: a covered slot has no part and no bones — correct, nothing to rebuild.';
const OUTFIT = {
  built: [],
  missing: [{ id: 'chain_a', light: 'grey', state: 'Covered', reason: COVERED, detail: '', pieces: ['Jeans', 'Underwear'] }],
  not_declared: ['pair_b', 'inset_c'],
};

const P = await loadBundled('frontend/src/tabs/characters/extensionPresence.ts');
const S = await loadBundled('frontend/src/tabs/characters/storedDeleteModel.ts');

// [1]
const covered = 'chain_a: Covered — Covered by Jeans, Underwear on this model: a covered slot has no part and no bones — correct, nothing to rebuild.';
eq('[1] outfit model lines', P.presenceLines(OUTFIT).map((l) => [l.light, l.text]), [
  [null, 'Extension bones: none on this model'],
  ['grey', covered],
  [null, 'Not declared for this character: pair_b, inset_c'],
]);
eq('[1] base lines', P.presenceLines({ built: ['chain_a', 'sack_d'], missing: [], not_declared: [] })
  .map((l) => [l.light, l.text]), [['green', 'Extension bones on this model: chain_a, sack_d']]);
eq('[1] null → []', P.presenceLines(null), []);
eq('[1] empty → []', P.presenceLines({ built: [], missing: [], not_declared: [] }), []);
eq('[1] detail → title', P.presenceLines({ ...OUTFIT, missing: [{ ...OUTFIT.missing[0], detail: 'D' }] })[1].title, 'D');
eq('[1] no detail → no title', P.presenceLines(OUTFIT)[1].title, undefined);

// [2]
eq('[2] running', S.refusalText('running', ''), 'A run works on it now — delete it after the run.');
eq('[2] current', S.refusalText('current', ''),
  'The figure stands on it now — take off what is worn in the body, then delete it.');
eq('[2] needed', S.refusalText('needed', 'shape of a live outfit'),
  'An outfit would be built on it now (shape of a live outfit).');
eq('[2] deletable', S.refusalText('', 'x'), '');

// [3]
const files = (n) => Array.from({ length: n }, (_, i) => `f${i}`);
eq('[3] shape', S.deleteLines({ kind: 'shape', files: files(10), bytes: 40960, outfit_models: ['Casual'], running: [] }), {
  removed: ['10 files · 0.0 MB', 'The outfit models built on it: Casual'],
  due: ['Nothing becomes due now: no outfit would be built on it.',
    'An outfit that needs this body shape again meshes it anew (hub jobs).',
    'Wearing one of those outfits again builds its model anew.'],
});
eq('[3] texture', S.deleteLines({ kind: 'texture', files: files(3), bytes: 2.5e6, outfit_models: [], running: ['k'] }), {
  removed: ['3 files · 2.5 MB'],
  due: ['Nothing becomes due now: no outfit would be built on it.',
    'An outfit that needs this painted body again paints it anew (hub jobs).',
    'A run works on 1 of its parts — those stay.'],
});
eq('[3] megabytes', S.megabytes(1234567), '1.2 MB');
const row = (o) => ({ running: false, current: false, deletable: true, refusal: '', history: false, ...o });
eq('[3] storedState', [row({ running: true, deletable: false, refusal: 'running' }),
  row({ current: true, deletable: false, refusal: 'current' }), row({ deletable: false, refusal: 'needed' }),
  row({ history: true }), row({})].map((e) => S.storedState(e)), [
  { light: 'blue', text: 'a run works on it' }, { light: 'green', text: 'in use now' },
  { light: 'green', text: 'needed by an outfit now' },
  { light: 'grey', text: 'kept only by an outfit model built on it' },
  { light: 'grey', text: 'stored, not needed now' }]);

// [4]
const html = unescape(await renderNote(OUTFIT));
eq('[4] note holds the three lines', ['Extension bones: none on this model', covered,
  'Not declared for this character: pair_b, inset_c'].map((s) => html.includes(s)), [true, true, true]);
eq('[4] null renders nothing', await renderNote(null), '');

// [5]
const viewer = src('frontend/src/tabs/characters/Model3DViewer.tsx');
has('[5] viewer takes extensionNote', viewer, 'extensionNote?: ReactNode');
has('[5] viewer renders it', viewer, '{extensionNote}');
has('[5] the column shows for the note alone', viewer, '|| extensionNote)');
const figureTab = src('frontend/src/tabs/characters/FieldFigure.tsx');
lacks('[5] Figure tab: no note (A73)', figureTab, 'extensionNote');
lacks('[5] Figure tab: no ExtensionPresenceNote (A73)', figureTab, 'ExtensionPresenceNote');
lacks('[5] Figure payload type: no served_extension (A73)', src('frontend/src/tabs/characters/figureModel.ts'),
  'served_extension');
lacks('[5] figure_build: no served_extension (A73)', src('app/core/figure_build.py'), 'served_extension');
has('[5] 3D tab passes extension_presence', src('frontend/src/tabs/characters/FieldModel3D.tsx'),
  '<ExtensionPresenceNote presence={model.extension_presence} />');

// [6]
const dialog = src('frontend/src/tabs/characters/StoredDeleteDialog.tsx');
has('[6] dialog: portal', dialog, 'createPortal(');
has('[6] dialog: to body', dialog, 'document.body');
has('[6] dialog: loads the preview', dialog, 'apiGet<StoredDeletePreview>(`${path}/preview`)');
has('[6] dialog: deletes', dialog, 'await apiDelete(path)');
has('[6] dialog: no Delete when refused', dialog, '{preview && !preview.deletable ? null : (');
const stored = src('frontend/src/tabs/characters/FigureStored.tsx');
has('[6] stored list uses the dialog', stored, '<StoredDeleteDialog');
lacks('[6] stored list: no ConfirmDialog', stored, 'ConfirmDialog');
has('[6] stored list: Delete…', stored, "t('Delete…')");
has('[6] stored list: refusal in words', stored, 'refusalText(');
has('[6] stored list: a light per row', stored, '<StepLight light={storedState(e, t).light} />');
const sw = src('frontend/src/tabs/characters/FitBodySwitch.tsx');
lacks('[6] body switch: no Delete dialog (A67)', sw, 'StoredDeleteDialog');
lacks('[6] body switch: no Delete button (A67)', sw, 'Delete this body shape');
for (const [name, text] of [['dialog', dialog], ['stored', stored], ['switch', sw]]) {
  lacks(`[6] ${name}: no window.confirm`, text, 'window.confirm');
}
const de = JSON.parse(src('shared/languages/de.json')).translations;
const keys = ['Extension bones: none on this model', 'Extension bones on this model: {ids}', COVERED, 'Covered',
  'Not declared for this character: {ids}', 'A run works on it now — delete it after the run.',
  'The figure stands on it now — take off what is worn in the body, then delete it.',
  'An outfit would be built on it now ({reason}).', '{n} files · {size}', 'The outfit models built on it: {names}',
  'Nothing becomes due now: no outfit would be built on it.',
  'An outfit that needs this body shape again meshes it anew (hub jobs).',
  'An outfit that needs this painted body again paints it anew (hub jobs).',
  'Wearing one of those outfits again builds its model anew.', 'A run works on {n} of its parts — those stay.',
  'Delete…', 'a run works on it', 'needed by an outfit now', 'in use now',
  'kept only by an outfit model built on it', 'stored, not needed now'];
eq('[6] de.json keys', keys.filter((k) => !de[k]), []);
if (!existsSync(join(ROOT, 'frontend/src/tabs/characters/storedDeleteModel.ts'))) fails.push('model missing');

console.log(fails.length ? `\n${fails.length} FAILED` : '\nALL OK');
process.exit(fails.length ? 1 : 0);
