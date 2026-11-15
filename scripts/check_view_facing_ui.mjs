#!/usr/bin/env node
/**
 * Check of the side views' facing line and Mirror button (Ruling A91) — the pure helpers in
 * `frontend/src/tabs/characters/viewFacingModel.ts` and their two consumers rendered with react-dom/server
 * (`ViewRenderTile` with a Mirror beside its button, `FieldModelRefs` layout "steps" from its `initialInfo`).
 *
 * Usage:  node scripts/check_view_facing_ui.mjs
 *
 * Self-bundling via esbuild (like scripts/check_figure_ui.mjs); no server, no world, no fetch. Exit 1 on a
 * mismatch list, 0 when every case holds.
 *
 * ============================================================================
 * THE CASES, DERIVED BY HAND (the convention of app/core/view_facing.py: a `left` view faces the LEFT edge of
 * the image, a `right` view the RIGHT edge; the coordinator's A91 UI brief)
 * ============================================================================
 * [1] facingLine(f, pair, view) — a line only when the view needs a look:
 *       f null                                        → null
 *       right, state ok, pair {same false}            → null (a correct view says nothing — A90's quiet tile)
 *       right, state wrong, facing left               → red, "Faces the wrong way", title
 *         "A right view faces the right edge of the image — this one faces the left edge. Mirror it (no image job)."
 *       left, state ok, pair {same true, facing left} → yellow, "Same way as the other", title
 *         "Both side views face the left edge of the image — one of them must be mirrored."
 *       right, state wrong + the same pair            → red wins (the sure verdict names the culprit)
 *       left, state unsure, facing null               → yellow, "Facing unsure", title "The facing check is not sure which way this view faces (it reads the feet). A left view
 *         faces the left edge of the image — check it and mirror it if needed."
 * [2] mirrorButton(f, followup, view, outfit) — label "⇋"; its title is the whole before the click:
 *       base right, not mirrored, followup {stale, 4, dressed true} → on false, disabled "", title lines
 *         "Mirror this view left-right on the CPU — no image job." /
 *         "Then the base model is out of date: the next Build rebuilds it — 4 hub jobs." /
 *         "The dressed right views are composited onto it again." /
 *         "Asymmetric details — a tattoo, a parting, an item worn on one side — swap sides." /
 *         "A second click turns it back."
 *       base right, mirrored {auto, confidence 0.97}, followup {restores, 0, dressed false} → on true, title
 *         "Mirrored automatically: it faced the other way (97 % sure)." /
 *         "Turn this view back to the picture as it was rendered — no image job." /
 *         "The base model was built from that picture — it is current again, no rebuild."
 *       base left, not mirrored, followup {no_model, 0, dressed false} → second line "No base model yet — no rebuild."
 *       base left, followup {already_stale, null} → "The base model is out of date already: the next Build
 *         rebuilds it — cost unknown."; {stale, 1} → "… — 1 hub job."
 *       dressed (outfit) right, followup {copy, 0} → disabled "This view is a copy of the body’s view — mirror the
 *         body’s view instead (Base body tab)." (the server refuses it: model_refs.MIRROR_COPY_REFUSED)
 *       dressed right, {repaint, 0} → "Then the outfit model is due: the Build repaints it on the CPU — no hub job."
 *       dressed right, {no_model, 0} → "No 3D model of this outfit yet — nothing else changes." (not the base text)
 *       dressed right, {model, 3} → "The outfit’s 3D model keeps the old view until it is made again — 3 hub jobs."
 *       mirrored by hand → first line "Mirrored by hand."
 * [3] Rendered ViewRenderTile (the Base body tab's row): with `beside` (the ViewMirrorButton of [2]'s first case)
 *     and `notice` (the wrong line of [1]) the markup holds the "⇋" button with aria-pressed="false" and its title
 *     inside the `ga-view-actions` box after "↻", and the notice text once; without either, no "⇋" and no notice.
 * [4] Rendered FieldModelRefs layout "steps" on the pipeline, left + right on, the right view wrong and mirrored by
 *     hand, the pair the same: two "⇋" buttons (left + right, none on the front view), one aria-pressed="true"
 *     (the right one), the red line "Faces the wrong way" once and the same-pair line once (the left
 *     view); with dressed_source.source "shape" (copies) both buttons are disabled with the copy reason.
 * [5] de.json carries every new English string of viewFacingModel.ts (FACING_*, MIRROR*, TURN_BACK_TITLE,
 *     FOLLOWUP_TEXT values, DRESSED_FOLLOW, "Turn back") — shared/languages/de.json `translations`.
 * [6] No native dialogs in the new files (window.confirm / alert / prompt).
 */
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { mkdtemp, rm } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const require_ = createRequire(import.meta.url);
const CHARS = join(ROOT, 'frontend/src/tabs/characters');

function esbuildModule() {
  for (const cand of ['esbuild', join(ROOT, 'frontend/node_modules/esbuild'), join(ROOT, 'client3d/node_modules/esbuild')]) {
    try {
      return require_(cand);
    } catch { /* next candidate */ }
  }
  console.error('esbuild not found (npm install) — nothing was checked');
  process.exit(1);
}

async function loadRendered() {
  const esbuild = esbuildModule();
  const dir = await mkdtemp(join(tmpdir(), 'check-view-facing-ui-'));
  try {
    const entry = join(dir, 'entry.tsx');
    writeFileSync(entry, `
import { createElement } from 'react'
import { renderToString } from 'react-dom/server'
import { I18nProvider } from ${JSON.stringify(join(ROOT, 'frontend/src/i18n/I18nProvider.tsx'))}
import { ToastProvider } from ${JSON.stringify(join(ROOT, 'frontend/src/lib/Toast.tsx'))}
export * from ${JSON.stringify(join(CHARS, 'viewFacingModel.ts'))}
export { ViewRenderTile } from ${JSON.stringify(join(CHARS, 'ViewRenderTile.tsx'))}
export { ViewMirrorButton } from ${JSON.stringify(join(CHARS, 'ViewMirrorButton.tsx'))}
export { FieldModelRefs } from ${JSON.stringify(join(CHARS, 'FieldModelRefs.tsx'))}
export const h = createElement
export const render = (el) => renderToString(createElement(I18nProvider, null, createElement(ToastProvider, null, el)))
`);
    const file = join(dir, 'rendered.mjs');
    await esbuild.build({
      entryPoints: [entry], outfile: file, bundle: true, format: 'esm', platform: 'node', jsx: 'automatic',
      logLevel: 'silent', absWorkingDir: ROOT, loader: { '.css': 'empty', '.png': 'empty', '.svg': 'empty' },
      nodePaths: [join(ROOT, 'frontend/node_modules'), join(ROOT, 'node_modules')],
      banner: { js: "import { createRequire as __cr } from 'module'; const require = __cr(import.meta.url);" },
    });
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

const failures = [];
function check(label, got, want) {
  const g = JSON.stringify(got);
  const w = JSON.stringify(want);
  if (g !== w) failures.push(`${label}\n    got:  ${g}\n    want: ${w}`);
}
const count = (s, needle) => s.split(needle).length - 1;
// renderToString escapes quotes and apostrophes in attributes and text.
const esc = (s) => s.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/'/g, '&#x27;').replace(/</g, '&lt;')
  .replace(/>/g, '&gt;');

const m = await loadRendered();
const tile = (expected, state, facing, mirrored = null, followup = undefined) => ({
  expected, facing, confidence: state === 'unsure' ? 0.4 : 1, state, mirrored, restorable: !!mirrored, followup });

// [1]
check('[1] null', m.facingLine(null, null, 'right'), null);
check('[1] ok', m.facingLine(tile('right', 'ok', 'right'), { same: false, facing: null }, 'right'), null);
check('[1] wrong', m.facingLine(tile('right', 'wrong', 'left'), { same: false, facing: null }, 'right'), {
  light: 'red', text: 'Faces the wrong way',
  title: 'A right view faces the right edge of the image — this one faces the left edge. Mirror it (no image job).' });
check('[1] same pair', m.facingLine(tile('left', 'ok', 'left'), { same: true, facing: 'left' }, 'left'), {
  light: 'yellow', text: 'Same way as the other',
  title: 'Both side views face the left edge of the image — one of them must be mirrored.' });
check('[1] wrong beats same', m.facingLine(tile('right', 'wrong', 'left'), { same: true, facing: 'left' }, 'right')?.light,
  'red');
check('[1] unsure', m.facingLine(tile('left', 'unsure', null), null, 'left'), {
  light: 'yellow', text: 'Facing unsure',
  title: 'The facing check is not sure which way this view faces (it reads the feet). A left view faces the left '
    + 'edge of the image — check it and mirror it if needed.' });

// [2]
const SWAPS = 'Asymmetric details — a tattoo, a parting, an item worn on one side — swap sides.';
const AGAIN = 'A second click turns it back.';
const b1 = m.mirrorButton(tile('right', 'wrong', 'left'), { kind: 'stale', jobs: 4, dressed: true }, 'right', false);
check('[2] base stale', b1, { label: '⇋', title: ['Mirror this view left-right on the CPU — no image job.',
  'Then the base model is out of date: the next Build rebuilds it — 4 hub jobs.',
  'The dressed right views are composited onto it again.', SWAPS, AGAIN].join('\n'), on: false, disabled: '' });
const b2 = m.mirrorButton(tile('right', 'ok', 'right', { auto: true, confidence: 0.97, reason: 'facing', at: 'x' }),
  { kind: 'restores', jobs: 0, dressed: false }, 'right', false);
check('[2] base auto restores', b2, { label: '⇋', title: ['Mirrored automatically: it faced the other way (97 % sure).',
  'Turn this view back to the picture as it was rendered — no image job.',
  'The base model was built from that picture — it is current again, no rebuild.'].join('\n'), on: true, disabled: '' });
check('[2] base no model', m.mirrorButton(tile('left', 'ok', 'left'), { kind: 'no_model', jobs: 0, dressed: false },
  'left', false).title.split('\n')[1], 'No base model yet — no rebuild.');
check('[2] already stale unknown', m.mirrorButton(tile('left', 'ok', 'left'), { kind: 'already_stale', jobs: null },
  'left', false).title.split('\n')[1], 'The base model is out of date already: the next Build rebuilds it — cost unknown.');
check('[2] stale 1', m.mirrorButton(tile('left', 'ok', 'left'), { kind: 'stale', jobs: 1 }, 'left', false)
  .title.split('\n')[1], 'Then the base model is out of date: the next Build rebuilds it — 1 hub job.');
check('[2] outfit copy', m.mirrorButton(tile('right', 'ok', 'right'), { kind: 'copy', jobs: 0 }, 'right', true).disabled,
  'This view is a copy of the body’s view — mirror the body’s view instead (Base body tab).');
const second = (kind, jobs) => m.mirrorButton(tile('right', 'ok', 'right'), { kind, jobs }, 'right', true)
  .title.split('\n')[1];
check('[2] outfit repaint', second('repaint', 0), 'Then the outfit model is due: the Build repaints it on the CPU — no hub job.');
check('[2] outfit no model', second('no_model', 0), 'No 3D model of this outfit yet — nothing else changes.');
check('[2] outfit model', second('model', 3), 'The outfit’s 3D model keeps the old view until it is made again — 3 hub jobs.');
check('[2] by hand', m.mirrorButton(tile('right', 'ok', 'right', { auto: false, reason: 'manual', at: 'x' }),
  { kind: 'repaint', jobs: 0 }, 'right', true).title.split('\n')[0], 'Mirrored by hand.');

// [3]
const wrongTile = tile('right', 'wrong', 'left', null, { kind: 'stale', jobs: 4, dressed: true });
const withMirror = m.render(m.h(m.ViewRenderTile, {
  label: 'Right', state: 'Current', stateColor: 'green', url: '/x.png', height: 120, running: false, disabled: false,
  actionLabel: '↻ 1 image', onRender: () => undefined,
  notice: m.facingLine(wrongTile, null, 'right'),
  beside: m.h(m.ViewMirrorButton, { facing: wrongTile, followup: wrongTile.followup, view: 'right', outfit: false,
    label: 'Right', busy: false, onMirror: () => undefined }),
}));
const actions = withMirror.slice(withMirror.indexOf('ga-view-actions'));
check('[3] ⇋ after ↻ in the actions box', actions.indexOf('↻') >= 0 && actions.indexOf('⇋') > actions.indexOf('↻'), true);
check('[3] pressed false', /ga-view-mirror"[^>]*aria-pressed="false"/.test(withMirror), true);
check('[3] title', withMirror.includes(esc(b1.title)), true);
check('[3] notice once', count(withMirror, 'Faces the wrong way'), 1);
const plain = m.render(m.h(m.ViewRenderTile, { label: 'Front', url: '/x.png', height: 120, running: false,
  disabled: false, onRender: () => undefined }));
check('[3] plain: no ⇋, no notice', [plain.includes('⇋'), plain.includes('ga-view-notice')], [false, false]);

// [4]
const refInfo = (facing) => ({ filename: 'f.png', created_at: '2026-11-15T10:00:00Z', freshness: 'current', facing });
const refs = (source) => ({
  signature: 'abc', pipeline: true, auto: { tpose: true }, build: { running: false },
  tpose: { filename: 'front.png', created_at: '2026-11-15T10:00:00Z' },
  views: {
    left: { enabled: true, info: refInfo(tile('left', 'ok', 'left')) },
    right: { enabled: true, info: refInfo(tile('right', 'ok', 'right', { auto: false, reason: 'manual', at: 'x' })) },
  },
  drafts: {}, dressed_source: { source, shape: 'base1234abcd', jobs: source === 'shape' ? 0 : 1 },
  facing_pair: { same: true, facing: 'left' }, mirror_followup: { kind: source === 'shape' ? 'copy' : 'repaint', jobs: 0 },
  status: {},
});
const html = m.render(m.h(m.FieldModelRefs, { character: 'demo', kinds: ['tpose'], layout: 'steps',
  initialInfo: refs('edit') }));
check('[4] two ⇋', count(html, '>⇋<'), 2);
check('[4] one pressed', count(html, 'aria-pressed="true"'), 1);
check('[4] same pair line', count(html, 'Same way as the other'), 2);
const wrongRefs = refs('edit');
wrongRefs.views.right.info.facing = tile('right', 'wrong', 'left');
wrongRefs.facing_pair = { same: true, facing: 'left' };
const html2 = m.render(m.h(m.FieldModelRefs, { character: 'demo', kinds: ['tpose'], layout: 'steps',
  initialInfo: wrongRefs }));
check('[4] wrong line once', count(html2, 'Faces the wrong way'), 1);
check('[4] same line on the left one', count(html2, 'Same way as the other'), 1);
const copies = m.render(m.h(m.FieldModelRefs, { character: 'demo', kinds: ['tpose'], layout: 'steps',
  initialInfo: refs('shape') }));
const mirrorTags = copies.match(/<button[^>]*ga-view-mirror[^>]*>/g) || [];
check('[4] copies: both disabled', mirrorTags.map((tg) => / disabled=""/.test(tg)), [true, true]);
check('[4] copies: reason', mirrorTags.every((tg) => tg.includes(esc(
  'This view is a copy of the body’s view — mirror the body’s view instead (Base body tab).'))), true);

// [5]
const de = JSON.parse(readFileSync(join(ROOT, 'shared/languages/de.json'), 'utf8')).translations;
const strings = [m.FACING_WRONG, m.FACING_WRONG_REASON, m.FACING_UNSURE, m.FACING_UNSURE_REASON, m.FACING_SAME,
  m.FACING_SAME_REASON, m.MIRRORED_AUTO, m.MIRRORED_HAND, m.MIRROR_TITLE, m.TURN_BACK_TITLE, m.MIRROR_SWAPS,
  m.MIRROR_AGAIN, m.MIRROR_DONE, m.MIRROR_UNDONE, m.MIRROR_WAIT_MODEL, m.DRESSED_FOLLOW,
  ...Object.values(m.FOLLOWUP_TEXT), 'Turn back', 'Mirror', 'left', 'right', 'cost unknown', '1 hub job', '{n} hub jobs'];
check('[5] de.json keys', strings.filter((s) => !(s in de)), []);

// [6]
for (const f of ['viewFacingModel.ts', 'ViewMirrorButton.tsx', 'ViewRenderTile.tsx']) {
  const path = join(CHARS, f);
  check(`[6] no native dialog in ${f}`, existsSync(path) && !/window\.(confirm|alert|prompt)\s*\(/.test(readFileSync(path, 'utf8')),
    true);
}

if (failures.length) {
  console.error(`check_view_facing_ui: ${failures.length} failure(s)\n  ${failures.join('\n  ')}`);
  process.exit(1);
}
console.log('check_view_facing_ui: all cases hold');
