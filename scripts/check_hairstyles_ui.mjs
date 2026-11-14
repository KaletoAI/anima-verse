#!/usr/bin/env node
/**
 * Check: the pure helpers of the rebuilt Hairstyles tab (frontend/src/tabs/characters/hairstylesModel.ts,
 * Task UI4 of docs/superpowers/plans/2026-11-12-unified-worn-pieces.md) plus the source rules the tab must keep.
 *
 * Usage:  node scripts/check_hairstyles_ui.mjs      (no server; esbuild from the workspace bundles the module)
 *
 * THE CASES, DERIVED BY HAND
 * --------------------------
 * [1] jobsLabel: null → "cost unknown", 0 → "no hub job", 1 → "1 hub job", 9 → "9 hub jobs".
 * [2] hairStepRows, HairDeck hair, everything current (HUB_JOBS hair:hairdeck = {hairdeck 1, fit 0}):
 *       HairDeck green "Current", "Made <when> from the profile picture.", button
 *         "Regenerate — 1 hub job, then fit on the CPU" (enabled);
 *       Fit green "Current", "Fitted <when> on the current base model. 6 spring chains.", button
 *         "Re-fit — no hub job" (enabled).
 *     The same with the placement saved after the fit (stale_reasons [placement_changed], run.steps [fit]):
 *       Fit yellow "Due", "The placement setting changed after the fit in use (<when>) — Re-fit applies it
 *       (no hub job); that fit stays in use until then." — the HairDeck row stays green.
 *     The base model rebuilt (base_model_changed, body built at B): the reason names B in brackets.
 *     No profile picture, nothing made: HairDeck grey "Not made yet", its button disabled "Set a profile picture
 *       first"; Fit grey "Not fitted yet", "Waits for the HairDeck result.", its button disabled "Needs the
 *       HairDeck result first".
 *     A refused HairDeck: red "Refused", "<error> — Regenerate tries a new seed (1 hub job)."
 *     A temporary NPC (pipeline false): two grey rows "Not built", no button.
 *     HAAR with nothing made (the fixture's HairDeck-shaped garment: no HAAR seeds, step_jobs without haar → the
 *       panel's default 3): two grey rows — "HAAR strands · 3 hub jobs" "Not made yet" and "Fit · no hub job" "Not
 *       fitted yet" (a fit record without seeds is not current); the HAAR rows' other states are in
 *       smoke_haar_variant_rows.mjs. Hair in the body worn as the plain body's hair: one green
 *       row "Current", "… — built <when>.", no button (its flow is the Figure tab's Build).
 * [3] listLight / listReason: haar current → green like any mode (HAAR is built since H3); current + no due → green "Current"; current + due [fit] → yellow
 *     "Due: Fit"; stale → yellow with the server's reason; missing → grey.
 * [4] settingDue: placement with placement_changed and fit 0 jobs → "Saved, not applied — Re-fit applies it
 *     (no hub job)"; colour without colour_changed → null; stiffness → null (it acts on the motion at once).
 * [5] placementMap: pivot p = (0, 1.56, 0.03), fitted f0 = 6 mm, a0 = 4.5°, w0 = 1; dragged f1 = 16 mm,
 *     a1 = 34.5° (Δa = 30°: cos 0.8660254, sin 0.5), w1 = 1.5; mid plane cx = 0, half width h = 0.08.
 *       Q = (0, 1.66, 0.036): dy = 0.1, dz = 0.036 − 0.006 − 0.03 = 0 → y = 1.56 + 0.1·0.8660254 = 1.6466025,
 *         z = 0.03 + 0.1·0.5 + 0.016 = 0.096.
 *       x = ±0.1 (beyond h): ±(0.08 + 0.02·1.5) = ±0.11; x = 0.05 (inside h) stays 0.05.
 *     placementIdentity true for equal values, false for a 1 mm shift.
 * [6] placementRuler, pivot z 0.03, forward 14 mm: 1 rail + 16 ticks (−5 … +10 cm) + 4 cyan lines (the shift
 *     twice, 2 mm apart, and two end bars) = 21; the rail runs z −0.02 … 0.13; the tick at the pivot (cm 5) is
 *     12 mm long, cm 6 is 6 mm; the shift runs z 0.03 … 0.044. Forward 0 → 17 lines (no shift drawn).
 * [7] The preview runs the strands, not the chains (strand-hair plan 2026-11-13 Task 10, spec § 6.2.5): the HairDeck
 *     preview passes `strandHair=` and no `motion=` (the chains stay the server's distance fallback), the client
 *     helper `previewMotion` is gone; the viewer runs `createStrandHair(THREE, …)` with the three it imported
 *     DYNAMICALLY (`await import('three')`) and has no static value import of three (the admin's lazy chunk stays);
 *     the motion buttons Sway / Walk / Turn / Stop are in the viewer, and their three titles and the drag hint
 *     say "no jobs".
 * [8] hexToLinear: #ffffff → [1,1,1]; #000000 → [0,0,0]; #808080 → ((128/255 + 0.055)/1.055)^2.4 = 0.21586;
 *     "red" → null. colourTint(#808080 → #ffffff) = 1/0.21586 = 4.63 → clamped 4; (#ffffff → #808080) = 0.21586;
 *     same colour → null.
 * [9] wearButton: none → "Wear"; automatic 9 → "Wear · Build 9 hub jobs"; automatic 0 → "Wear · no hub job";
 *     manual 9 → "Wear · no job now", title "Nothing runs on the click; the Build you start then costs 9 hub jobs".
 * [10] Sources: no native dialog in the tab's files; HairDeckPlacement.tsx is gone (no legacy placement form);
 *     the tab names no other flow's run route (`/figure/build` only via FigureBuildLine, no `/model3d/`); every
 *     3D preview passes `builtAt`; the New-hairstyle dialog is a createPortal to document.body.
 * [11] Alpha cutoff (strand-hair plan 2026-11-13 Task 3, spec § 4 / § 6.1): the HairDeck preview (the viewer of
 *     `garment.preview_url`) passes the hair GET's `alpha_cutoff` (`alphaCutoff={info.alpha_cutoff}`), and no
 *     client source (frontend/src, client3d/src, packages/<pkg>/src) carries a cutoff of its own: no assignment of a
 *     non-zero number to `alphaTest` and no `alphaCutoff` number literal — except `client3d/src/scene/impostors.ts`
 *     (0.5: the client's own billboard material for distant props, no glTF material and no hair).
 * [12] The New-hairstyle dialog opens with the standard text (Ruling A54). GET …/hairstyles carries
 *     `appearance_hair_text` T = "short black hair, wavy hair with a side parting":
 *       standardHairText({appearance_hair_text: "  short black hair,\n wavy hair with a side parting "}) = T
 *       (whitespace collapsed like the server's create_hairstyle); {} / null / {appearance_hair_text: null} → "".
 *     newHairstyleText(standard, field):
 *       (T, T)        → reset false, fromStandard true,  hint null   (the field as it opens);
 *       (T, " " + T)  → the same (blank ends do not count);
 *       (T, "a bun")  → reset true,  fromStandard false, hint null   ("Reset to standard text" offered);
 *       (T, "")       → reset true,  fromStandard false, hint null   (Create's own "Describe the hairstyle");
 *       ("", "")      → reset false, fromStandard false, hint NO_HAIR_TEXT (said before Create);
 *       ("", "a bun") → reset false, fromStandard false, hint null.
 *     NO_HAIR_TEXT is the server's message word for word (the ValueError in garment_hair.create_hairstyle).
 *     Sources: the dialog's field state starts from `standard` (`useState(standard)`), the tab passes
 *     `standard={standardHairText(list)}` of the hairstyles GET, the reset link sets the field back to `standard`,
 *     and the route puts `appearance_hair_text` into the hairstyles GET.
 * [13] Delete a hairstyle (Ruling A59).
 *     sizeLabel: 12 → "12 B"; 2048 → "2 KB"; 1572864 (1.5·1024²) → "1.5 MB".
 *     deleteCost: null (no figure) → "no figure — nothing is built"; automatic 0 → "the Build starts by itself — local,
 *       no hub job"; automatic 9 → "the Build starts by itself — 9 hub jobs"; manual 0 → "nothing runs now; the Build
 *       you start then is local, no hub job"; manual 3 → "… costs 3 hub jobs"; manual null → "… costs cost unknown".
 *     deleteSummary of the worn, plain and last hairstyle with files [HairDeck jobs 3 / 2048 B, Fits and strand
 *       records 1 / 1572864 B], a picture, 2 assembled files, shapes [ob1 deletable, ob2 kept], sets ["Day"] and the
 *       estimate automatic 0:
 *       removed = ["The hairstyle item and its picture", "HairDeck jobs: 3 files (2 KB)", "Fits and strand records:
 *         1 file (1.5 MB)", "Assembled models with this hair: 2 files — re-assembled without it on the CPU",
 *         "Body shapes with only this hair: 1"];
 *       notes = ["This hairstyle is worn — the figure will be rebuilt without hair (the Build starts by itself —
 *         local, no hub job).", "It is the last hairstyle — the character then has none.", "Outfit sets that wear it
 *         then leave the hair as it is: Day.", "Body shapes kept for now: 1 — the Figure tab offers them once nothing
 *         stands on them.", "This cannot be undone."].
 *     An unworn hairstyle without files or picture: removed ["The hairstyle item", "No generated files are stored for
 *       it."], notes ["This cannot be undone."]. The plain body's (not worn), estimate manual 5: the first note
 *       "The plain body was made with this hairstyle — the figure will be rebuilt (nothing runs now; the Build you
 *       start then costs 5 hub jobs)."
 *     afterDeleteSelection: the worn id of the reloaded list ("b" of [a, b worn]); none worn → NONE_SELECTED; null
 *       (the reload failed) → NONE_SELECTED.
 *     Sources: every card has a "Delete" button that opens the dialog (`setDeleting({ id: h.id`) and stops the
 *     card's click; the dialog is a createPortal to document.body, loads `…/delete-preview`, shows
 *     `deleteSummary(preview, t)`, deletes with `apiDelete` and has Cancel; no native dialog; after the delete the
 *     selection is `afterDeleteSelection(next)` of the reloaded list and a NONE_SELECTED selection shows no detail;
 *     the route file has `@router.delete("/{character_name}/hairstyles/{item_id}")` and the preview GET, both with
 *     `Depends(require_admin)`.
 */
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { mkdtemp, rm } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const require_ = createRequire(import.meta.url);

function esbuildModule() {
  for (const cand of ['esbuild', join(ROOT, 'frontend/node_modules/esbuild'),
                      join(ROOT, 'client3d/node_modules/esbuild')]) {
    try {
      return require_(cand);
    } catch { /* next candidate */ }
  }
  console.error('esbuild not found (npm install) — nothing was checked');
  process.exit(1);
}

async function loadBundled(src) {
  const esbuild = esbuildModule();
  const dir = await mkdtemp(join(tmpdir(), 'check-hairstyles-ui-'));
  try {
    const file = join(dir, 'module.mjs');
    await esbuild.build({ entryPoints: [src], outfile: file, bundle: true, format: 'esm', platform: 'neutral',
      logLevel: 'silent', absWorkingDir: ROOT });
    return await import(`file://${file}`);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

const failures = [];
function check(label, got, want) {
  const g = JSON.stringify(got);
  const w = JSON.stringify(want);
  if (g !== w) failures.push(`${label}: got ${g}, want ${w}`);
  else console.log(`ok  ${label}`);
}
const r7 = (v) => Math.round(v * 1e7) / 1e7;
const r5 = (v) => Math.round(v * 1e5) / 1e5;

const m = await loadBundled(join(ROOT, 'frontend/src/tabs/characters/hairstylesModel.ts'));
const when = (s) => (s ? `<${s}>` : '');

// [1]
check('[1] jobsLabel', [null, 0, 1, 9].map((n) => m.jobsLabel(n)),
  ['cost unknown', 'no hub job', '1 hub job', '9 hub jobs']);

// [2]
const hd = (over = {}) => ({ status: 'accepted', created_at: 'H', error: null, seed: 7, backend: 'hub', attempt: 1,
  images: { input: { url: '/x.png' } }, input_source: 'profile', chains: { count: 6, fitted: true, swing: true },
  ...over });
const garment = (over = {}) => ({ running_step: null, failed: null, stale_reasons: [], preview_built_at: 'F',
  steps: { fit: { status: 'accepted', created_at: 'F' } }, ...over });
const info = (over = {}) => ({ pipeline: true, method: 'hairdeck', equipped: true, body_built_at: 'B',
  run: { steps: [], hub_jobs: 0, note: '', refit: false }, step_jobs: { hairdeck: 1, fit: 0 }, garment: garment(),
  hairdeck: hd(), ...over });
const brief = (rows) => rows.map((r) => [r.id, r.light, r.state, r.reason, r.button && r.button.label,
  r.button && r.button.disabled]);

check('[2] current', brief(m.hairStepRows(info(), undefined, when)), [
  ['hairdeck', 'green', 'Current', 'Made <H> from the profile picture.', 'Regenerate — 1 hub job, then fit on the CPU', null],
  ['fit', 'green', 'Current', 'Fitted <F> on the current base model. 6 spring chains.', 'Re-fit — no hub job', null],
]);
const placed = info({ garment: garment({ stale_reasons: ['placement_changed'] }),
  run: { steps: ['fit'], hub_jobs: 0, note: '', refit: false } });
check('[2] placement saved after the fit', brief(m.hairStepRows(placed, undefined, when)).map((r) => r.slice(0, 4)), [
  ['hairdeck', 'green', 'Current', 'Made <H> from the profile picture.'],
  ['fit', 'yellow', 'Due', 'The placement setting changed after the fit in use (<F>) — Re-fit applies it (no hub job); '
    + 'that fit stays in use until then.'],
]);
const rebuilt = info({ garment: garment({ stale_reasons: ['base_model_changed'] }),
  run: { steps: ['fit'], hub_jobs: 0, note: '', refit: false } });
check('[2] base model rebuilt names when', m.hairStepRows(rebuilt, undefined, when)[1].reason,
  'The base model was rebuilt (<B>) after the fit in use (<F>) — Re-fit applies it (no hub job); '
  + 'that fit stays in use until then.');
const nothing = info({ garment: garment({ preview_built_at: null, steps: { fit: { status: 'missing', created_at: null } } }),
  hairdeck: hd({ status: 'missing', created_at: null, images: { input: null }, chains: null }),
  run: { steps: ['hairdeck', 'fit'], hub_jobs: 1, note: '', refit: false } });
check('[2] no profile picture', brief(m.hairStepRows(nothing, undefined, when)), [
  ['hairdeck', 'grey', 'Not made yet', 'No profile picture — set one in the Profile tab, then Run all makes the hair.',
    'Regenerate — 1 hub job, then fit on the CPU', 'Set a profile picture first'],
  ['fit', 'grey', 'Not fitted yet', 'Waits for the HairDeck result.', 'Re-fit — no hub job',
    'Needs the HairDeck result first'],
]);
const refused = info({ hairdeck: hd({ status: 'refused', error: 'No hair found' }) });
check('[2] refused', brief(m.hairStepRows(refused, undefined, when))[0].slice(1, 4),
  ['red', 'Refused', 'No hair found — Regenerate tries a new seed (1 hub job).']);
check('[2] temporary NPC', brief(m.hairStepRows(info({ pipeline: false }), undefined, when)).map((r) => r.slice(0, 3)
  .concat([r[4]])), [['hairdeck', 'grey', 'Not built', null], ['fit', 'grey', 'Not built', null]]);
check('[2] HAAR', brief(m.hairStepRows(info({ method: 'haar' }), undefined, when)).map((r) => [r[0], r[1], r[2], r[4]]),
  [['haar', 'grey', 'Not made yet', 'HAAR strands · 3 hub jobs'], ['fit', 'grey', 'Not fitted yet', 'Fit · no hub job']]);
check('[2] body, plain', brief(m.hairStepRows(info({ method: 'body', plain: true, base_prompts: { state: 'current' } }),
  undefined, when)), [['body', 'green', 'Current', 'The plain body was rendered with this hairstyle — built <B>.', null,
  null]]);

// [3]
check('[3] list lights', [m.listLight('current', 'haar'), m.listLight('current', 'hairdeck'),
  m.listLight('current', 'hairdeck', ['fit']), m.listLight('stale', 'hairdeck'), m.listLight('missing', 'body')],
['green', 'green', 'yellow', 'yellow', 'grey']);
check('[3] list reasons', [m.listReason({ state: 'current' }), m.listReason({ state: 'current' }, ['fit']),
  m.listReason({ state: 'stale', reason: 'Fitted on an older body' }), m.listReason(null)],
['Current', 'Due: Fit', 'Fitted on an older body', '']);

// [4]
check('[4] settingDue', [m.settingDue('placement', placed), m.settingDue('colour', placed),
  m.settingDue('stiffness', placed)], ['Saved, not applied — Re-fit applies it (no hub job)', null, null]);

// [5]
const pivot = [0, 1.56, 0.03];
const fitted = { forward_m: 0.006, tilt_deg: 4.5, width_scale: 1 };
const map = m.placementMap(pivot, fitted, { forward_m: 0.016, tilt_deg: 34.5, width_scale: 1.5 }, 0, 0.08);
check('[5] turned and shifted', map([0, 1.66, 0.036]).map(r7), [0, 1.6466025, 0.096]);
check('[5] width beyond the head', [map([0.1, 1.56, 0.036])[0], map([-0.1, 1.56, 0.036])[0], map([0.05, 1.56, 0.036])[0]]
  .map(r7), [0.11, -0.11, 0.05]);
check('[5] identity', [m.placementIdentity(fitted, { ...fitted }),
  m.placementIdentity(fitted, { ...fitted, forward_m: 0.007 })], [true, false]);

// [6]
const ruler = m.placementRuler(pivot, 0.12, 1.6, 0.014);
check('[6] ruler lines', [ruler.length, ruler[0].points.map((p) => r7(p[2])), r7(ruler[6].points[0][1] - ruler[6].points[1][1]),
  r7(ruler[7].points[0][1] - ruler[7].points[1][1]), ruler[17].points.map((p) => r7(p[2])), ruler[17].color],
[21, [-0.02, 0.13], 0.012, 0.006, [0.03, 0.044], '#00e5ff']);
check('[6] no shift drawn at 0', m.placementRuler(pivot, 0.12, 1.6, 0).length, 17);

// [7]
{
  const viewerSrc = readFileSync(join(ROOT, 'frontend/src/tabs/characters/Model3DViewer.tsx'), 'utf8');
  const tabSrc = readFileSync(join(ROOT, 'frontend/src/tabs/characters/FieldHairstyles.tsx'), 'utf8');
  const hairdeck = (tabSrc.match(/<Model3DViewer\b[\s\S]*?\/>/g) || []).find((v) => /preview_url/.test(v)) || '';
  check('[7] strands, not chains', [/strandHair=\{/.test(hairdeck), /\bmotion=\{/.test(hairdeck),
    typeof m.previewMotion], [true, false, 'undefined']);
  check('[7] three injected, lazily', [/createStrandHair\(THREE,/.test(viewerSrc),
    /const THREE = await import\('three'\)/.test(viewerSrc), /^import (?!type)[^\n]*from 'three'/m.test(viewerSrc)],
  [true, true, false]);
  check('[7] motion buttons, no jobs', [["'sway'", "'walk'", "'turn'", "t('Stop')"].every((k) => viewerSrc.includes(k)),
    (viewerSrc.match(/preview only, no jobs/g) || []).length, /· no jobs'\)/.test(viewerSrc)], [true, 3, true]);
}

// [8]
check('[8] hexToLinear', [m.hexToLinear('#ffffff'), m.hexToLinear('#000000'), m.hexToLinear('#808080').map(r5),
  m.hexToLinear('red')], [[1, 1, 1], [0, 0, 0], [0.21586, 0.21586, 0.21586], null]);
check('[8] colourTint', [m.colourTint('#808080', '#ffffff'), m.colourTint('#ffffff', '#808080').map(r5),
  m.colourTint('#7a3b1e', '#7A3B1E')], [[4, 4, 4], [0.21586, 0.21586, 0.21586], null]);

// [9]
check('[9] wearButton', [m.wearButton(null).label, m.wearButton({ hub_jobs: 9, automatic: true }).label,
  m.wearButton({ hub_jobs: 0, automatic: true }).label, m.wearButton({ hub_jobs: 9, automatic: false }).label,
  m.wearButton({ hub_jobs: 9, automatic: false }).title],
['Wear', 'Wear · Build 9 hub jobs', 'Wear · no hub job', 'Wear · no job now',
  'Nothing runs on the click; the Build you start then costs 9 hub jobs']);

// [10]
const dir = join(ROOT, 'frontend/src/tabs/characters');
const tab = readFileSync(join(dir, 'FieldHairstyles.tsx'), 'utf8');
const live = readFileSync(join(dir, 'HairLiveControls.tsx'), 'utf8');
const parts = readFileSync(join(dir, 'HairstyleParts.tsx'), 'utf8');
const all = tab + live + parts;
check('[10] no native dialogs', /window\.(prompt|alert|confirm)\(/.test(all), false);
check('[10] no legacy placement form', existsSync(join(dir, 'HairDeckPlacement.tsx')), false);
check('[10] no other flow\'s run route', [/\/model3d\//.test(all), /figure\/build/.test(tab + live),
  /figure\/build/.test(parts)], [false, false, true]);
const viewers = tab.match(/<Model3DViewer\b[\s\S]*?\/>/g) || [];
check('[10] every 3D preview shows Built <time>', [viewers.length > 0, viewers.every((v) => /builtAt=/.test(v))],
  [true, true]);
check('[10] dialog through createPortal', /return createPortal\([\s\S]*?document\.body,\s*\)/.test(tab), true);

// [11]
const hairdeckViewer = viewers.find((v) => /preview_url/.test(v)) || '';
check('[11] the HairDeck preview applies the GET\'s cutoff', /alphaCutoff=\{info\.alpha_cutoff\}/.test(hairdeckViewer), true);
const sources = [];
const walk = (d) => {
  for (const name of readdirSync(d)) {
    const f = join(d, name);
    if (name === 'node_modules') continue;
    if (statSync(f).isDirectory()) walk(f);
    else if (/\.(ts|tsx|js|mjs)$/.test(name)) sources.push(f);
  }
};
for (const d of ['frontend/src', 'client3d/src', ...readdirSync(join(ROOT, 'packages')).map((p) => `packages/${p}/src`)]) {
  if (existsSync(join(ROOT, d))) walk(join(ROOT, d));
}
const hardCoded = sources.filter((f) => {
  const text = readFileSync(f, 'utf8');
  return /alphaTest\s*[:=]\s*(0*\.\d*[1-9]|[1-9])/.test(text) || /alphaCutoff\s*[:=]\s*\d/.test(text);
}).map((f) => f.slice(ROOT.length)).filter((f) => f !== 'client3d/src/scene/impostors.ts');
check('[11] no client carries a cutoff of its own', [sources.length > 100, hardCoded], [true, []]);

// [12]
{
  const T = 'short black hair, wavy hair with a side parting';
  check('[12] standardHairText', [m.standardHairText({ appearance_hair_text: '  short black hair,\n wavy hair with a side parting ' }),
    m.standardHairText({}), m.standardHairText(null), m.standardHairText({ appearance_hair_text: null })], [T, '', '', '']);
  const st = (std, d) => { const r = m.newHairstyleText(std, d); return [r.reset, r.fromStandard, r.hint]; };
  check('[12] newHairstyleText', [st(T, T), st(T, ` ${T}`), st(T, 'a bun'), st(T, ''), st('', ''), st('', 'a bun')],
    [[false, true, null], [false, true, null], [true, false, null], [true, false, null],
      [false, false, m.NO_HAIR_TEXT], [false, false, null]]);
  const serverHair = readFileSync(join(ROOT, 'app/core/garment_hair.py'), 'utf8');
  check('[12] the hint is the server\'s message', serverHair.includes(`raise ValueError("${m.NO_HAIR_TEXT}")`), true);
  const dialog = (tab.match(/function NewHairstyleDialog[\s\S]*?\n}\n/) || [''])[0];
  const route = readFileSync(join(ROOT, 'app/routes/characters.py'), 'utf8');
  const hairstylesGet = (route.match(/def get_character_hairstyles[\s\S]*?\n\n\n/) || [''])[0];
  check('[12] wiring', [/useState\(standard\)/.test(dialog), /standard=\{standardHairText\(list\)\}/.test(tab),
    /onClick=\{\(\) => setDescription\(standard\)\}/.test(dialog), /t\(field\.hint\)/.test(dialog),
    /"appearance_hair_text": \(garment_hair\.appearance_hair_text\(/.test(hairstylesGet)], [true, true, true, true, true]);
}

// [13]
{
  check('[13] sizeLabel', [m.sizeLabel(12), m.sizeLabel(2048), m.sizeLabel(1572864)], ['12 B', '2 KB', '1.5 MB']);
  const est = (hub_jobs, automatic) => ({ hub_jobs, automatic, note: '' });
  check('[13] deleteCost', [m.deleteCost(null), m.deleteCost(est(0, true)), m.deleteCost(est(9, true)),
    m.deleteCost(est(0, false)), m.deleteCost(est(3, false)), m.deleteCost(est(null, false))],
  ['no figure — nothing is built', 'the Build starts by itself — local, no hub job',
    'the Build starts by itself — 9 hub jobs', 'nothing runs now; the Build you start then is local, no hub job',
    'nothing runs now; the Build you start then costs 3 hub jobs',
    'nothing runs now; the Build you start then costs cost unknown']);
  const base = { item_id: 'hair_kai', name: 'Short black hair', worn: false, plain: false, last: false, files: [],
    total_files: 0, total_bytes: 0, item_files: 0, assembled: 0, shapes: [], outfit_sets: [], estimate: null };
  const worn = { ...base, worn: true, plain: true, last: true, item_files: 1, assembled: 2,
    files: [{ label: 'HairDeck jobs', files: 3, bytes: 2048 }, { label: 'Fits and strand records', files: 1, bytes: 1572864 }],
    shapes: [{ key: 'ob1', deletable: true, why: '' }, { key: 'ob2', deletable: false, why: 'x' }],
    outfit_sets: ['Day'], estimate: est(0, true) };
  check('[13] deleteSummary worn', m.deleteSummary(worn), {
    removed: ['The hairstyle item and its picture', 'HairDeck jobs: 3 files (2 KB)', 'Fits and strand records: 1 file (1.5 MB)',
      'Assembled models with this hair: 2 files — re-assembled without it on the CPU', 'Body shapes with only this hair: 1'],
    notes: ['This hairstyle is worn — the figure will be rebuilt without hair (the Build starts by itself — local, no hub job).',
      'It is the last hairstyle — the character then has none.', 'Outfit sets that wear it then leave the hair as it is: Day.',
      'Body shapes kept for now: 1 — the Figure tab offers them once nothing stands on them.', 'This cannot be undone.'],
  });
  check('[13] deleteSummary bare', m.deleteSummary(base),
    { removed: ['The hairstyle item', 'No generated files are stored for it.'], notes: ['This cannot be undone.'] });
  check('[13] deleteSummary plain', m.deleteSummary({ ...base, plain: true, estimate: est(5, false) }).notes[0],
    'The plain body was made with this hairstyle — the figure will be rebuilt (nothing runs now; the Build you start then costs 5 hub jobs).');
  check('[13] afterDeleteSelection', [
    m.afterDeleteSelection({ hairstyles: [{ id: 'a', worn: false }, { id: 'b', worn: true }] }),
    m.afterDeleteSelection({ hairstyles: [{ id: 'a', worn: false }] }) === m.NONE_SELECTED,
    m.afterDeleteSelection(null) === m.NONE_SELECTED], ['b', true, true]);
  const dlg = (tab.match(/function DeleteHairstyleDialog[\s\S]*?\n}\n/) || [''])[0];
  const route = readFileSync(join(ROOT, 'app/routes/characters.py'), 'utf8');
  const del = (route.match(/@router\.delete\("\/\{character_name\}\/hairstyles\/\{item_id\}"\)[\s\S]*?\n\n\n/) || [''])[0];
  const prev = (route.match(/@router\.get\("\/\{character_name\}\/hairstyles\/\{item_id\}\/delete-preview"\)[\s\S]*?\n\n\n/) || [''])[0];
  check('[13] wiring', [
    /onClick=\{\(e\) => \{ e\.stopPropagation\(\); setDeleting\(\{ id: h\.id/.test(tab),
    /return createPortal\([\s\S]*?document\.body,\s*\)/.test(dlg), /delete-preview/.test(dlg),
    /deleteSummary\(preview, t\)/.test(dlg), /apiDelete</.test(dlg), /t\('Cancel'\)/.test(dlg),
    /window\.(prompt|alert|confirm)\(/.test(dlg), /setSelected\(afterDeleteSelection\(next\)\)/.test(tab),
    /selected === NONE_SELECTED \? null/.test(tab),
    /Depends\(require_admin\)/.test(del), /Depends\(require_admin\)/.test(prev)],
  [true, true, true, true, true, true, false, true, true, true, true]);
}

if (failures.length) {
  console.error(`\nFAIL (${failures.length})`);
  for (const f of failures) console.error(`  ${f}`);
  process.exit(1);
}
console.log('\nALL OK');
