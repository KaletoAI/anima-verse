#!/usr/bin/env node
/**
 * Check of the Base body tab (Task UI1 of docs/superpowers/plans/2026-11-12-unified-worn-pieces.md: the base body
 * gets its own tab again, right before "Figure"; rules R1 "Run all" skips what is current, R2 single steps redo,
 * R3 settings are saved on their own, R4 a tab shows only today's flows) — the pure helpers of
 * `frontend/src/tabs/characters/baseBodyModel.ts` and the wiring by source greps.
 *
 * Usage:  node scripts/check_base_body_ui.mjs
 *
 * Self-bundling via esbuild (like scripts/check_figure_ui.mjs); no server, no world. Exit 1 with the mismatch
 * list, 0 when every case holds. The server half (the plan, the start, the face values) is
 * scripts/smoke_base_body_run_all.py.
 *
 * ============================================================================
 * THE CASES, DERIVED BY HAND (the brief's rules R1–R4)
 * ============================================================================
 * [1] runAllButton(r) — R1, the reason written under a disabled button:
 *       no answer yet (null)                         → "Run all", disabled, reason null
 *       running                                      → "Running…", disabled, reason "Run all is running"
 *       kind "", hub_jobs 0                          → "Everything is current", disabled, reason null
 *       kind "", hub_jobs null, note "cost unknown — boom" → "Run all", disabled, reason "cost unknown — boom"
 *       kind plain_body, 4                           → "Run all (4 hub jobs)", enabled
 *       kind face_retexture, 1                       → "Run all (1 hub job)" (singular)
 *       kind face_cleanup, 0 (a re-rig is unrouted…) → "Run all (0 hub jobs)", enabled (the CPU cleanup runs)
 *       kind face_cleanup, null                      → "Run all (cost unknown)", enabled
 * [2] runAllStep: "view back" → "Back view", "view left" → "Left view", "skin front" → "Skin detail step",
 *     "mesh" → "Mesh", "upscale" → "Upscale (face reference)", "face" → "Face retexture", "rig" → "Rig",
 *     "cleanup" → "Face cleanup (local)", an unknown "x" → "x". runAllWhat("") → "".
 * [3] chainRunAll (the Wardrobe piece dialog's Run all, R1 there): undefined → "Run all", enabled (the server
 *     decides); {steps []} → "Everything is current", disabled; {steps [fit], refit true} → "Run all (refit on
 *     the CPU)"; {steps [front, back, mesh], hub_jobs 6} → "Run all (6 hub jobs)"; hub_jobs null → "Run all (cost
 *     unknown)".
 * [4] Face values (R3) over the server defaults (face_photo_adjust.DEFAULTS, face_retexture.validated_params):
 *     facePhotoOf({balance 0.5}) = {balance 0.5, tone_match 1, skin_recolor 1, brightness 1};
 *     faceControlsOf(null) = {strength 1, feather 0.18, render_resolution 768, yaw 0};
 *     faceSettingsInvalid: the defaults → null; yaw 200 → "Yaw goes from −180 to 180 degrees"; render_resolution
 *     300.5 → "Render resolution is a whole number from 256 to 2048"; brightness 0.4 → "Face brightness goes from
 *     50 to 150 %"; feather 0.6 → "Feather goes from 0 to 0.5".
 *     faceSettingsChanged(defaults, defaults) → false; strength 0.8 in the draft → true.
 *     FACE_SETTINGS_NOTE begins "Saving runs nothing."
 * [5] Source greps — the tab:
 *     base-character.json: tab `base_body_tab` {Base body, Grundkörper} directly before `figure_tab`, its columns
 *     hold the section `base_body` (special "base_body") which has NO visible_when (an animal sees why it does
 *     not apply instead of no tab); CharactersTab lists 'base_body' in SPECIAL_SLOTS and renders
 *     `base_body: (<FieldBaseBody`; FieldBaseBody posts base-body/run-all, renders FaceSettings and writes the
 *     animal and the temporary-NPC reason; FigureBodyDetails.tsx is gone.
 * [6] Source greps — the Figure tab keeps the figure: FieldFigure neither imports nor renders FigureBodyDetails
 *     or FieldBaseBody, writes baseBodyLine(…) and "Open Base body tab"; the 3D tab's link reads
 *     "Open Base body tab" (not "Open Figure tab").
 * [7] Source greps — R3 and R4: FaceSettings posts model3d/options with face_photo AND face_controls;
 *     ModelFaceActions has no setOption (the switches moved to FaceSettings) and its dialog starts from the
 *     saved values (facePhotoOf / faceControlsOf); FieldModelRefs renders its "Generate" only when not every kind
 *     is the Build's (`pipelineViews ? null`) and lists Auto boxes only for kinds the Build does not decide;
 *     WardrobeGarment labels Run all with chainRunAll.
 * [8] Tip smoothing (Ruling A43): runAllStep("tip_smoothing") → "Tip smoothing (local)"; runAllWhat("tip_smoothing")
 *     → "Tip smoothing not applied to this model yet: rebuilds the extension bones (local, no hub job)";
 *     tipSmoothingLine: no record (due) → "Not applied to this model yet — rebuilds the extension bones (local, no hub
 *     job)"; a record {T applied, max_shift_mm 4.546, inverted [22, 0]} with the time "01:12" → "Applied 01:12 — max
 *     shift 4.5 mm, inverted normals 22 → 0"; status failed, error "boom" → "Last rebuild failed: boom"; a kept own
 *     tip (applied false, reason R) → R. FieldBaseBody renders <MeshRepairPanel, <TipSmoothingPanel and
 *     <ExtensionTipPanel in that source order.
 */
import { existsSync, readFileSync } from 'node:fs';
import { mkdtemp, rm } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const require_ = createRequire(import.meta.url);

function esbuildModule() {
  for (const cand of ['esbuild',
                      join(ROOT, 'frontend/node_modules/esbuild'),
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
  const dir = await mkdtemp(join(tmpdir(), 'check-base-body-ui-'));
  try {
    const file = join(dir, 'module.mjs');
    await esbuild.build({
      entryPoints: [src], outfile: file, bundle: true, format: 'esm',
      platform: 'neutral', logLevel: 'silent', absWorkingDir: ROOT,
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
  if (g !== w) failures.push(`${label}: got ${g}, want ${w}`);
  else console.log(`ok  ${label}`);
}
const src = (rel) => {
  try { return readFileSync(join(ROOT, rel), 'utf8'); } catch { return ''; }
};

const m = await loadBundled('frontend/src/tabs/characters/baseBodyModel.ts');

// [1]
const ra = (o) => ({ kind: '', steps: [], hub_jobs: 0, note: '', running: false, last: null, ...o });
check('[1] no answer', m.runAllButton(null), { label: 'Run all', disabled: true, reason: null });
check('[1] running', m.runAllButton(ra({ kind: 'plain_body', hub_jobs: 4, running: true })),
  { label: 'Running…', disabled: true, reason: 'Run all is running' });
check('[1] everything current', m.runAllButton(ra({})), { label: 'Everything is current', disabled: true, reason: null });
check('[1] unreadable plan', m.runAllButton(ra({ hub_jobs: null, note: 'cost unknown — boom' })),
  { label: 'Run all', disabled: true, reason: 'cost unknown — boom' });
check('[1] plain body 4', m.runAllButton(ra({ kind: 'plain_body', hub_jobs: 4 })),
  { label: 'Run all (4 hub jobs)', disabled: false, reason: null });
check('[1] face 1 (singular)', m.runAllButton(ra({ kind: 'face_retexture', hub_jobs: 1 })).label, 'Run all (1 hub job)');
check('[1] cleanup 0', m.runAllButton(ra({ kind: 'face_cleanup', hub_jobs: 0 })),
  { label: 'Run all (0 hub jobs)', disabled: false, reason: null });
check('[1] cleanup unknown', m.runAllButton(ra({ kind: 'face_cleanup', hub_jobs: null })).label,
  'Run all (cost unknown)');

// [2]
check('[2] step labels', ['view back', 'view left', 'skin front', 'mesh', 'upscale', 'face', 'rig', 'cleanup', 'x']
  .map((s) => m.runAllStep(s)),
  ['Back view', 'Left view', 'Skin detail step', 'Mesh', 'Upscale (face reference)', 'Face retexture', 'Rig',
    'Face cleanup (local)', 'x']);
check('[2] nothing planned says nothing', m.runAllWhat(''), '');

// [3]
check('[3] no estimate', m.chainRunAll(undefined), { label: 'Run all', disabled: false });
check('[3] nothing due', m.chainRunAll({ steps: [], hub_jobs: 0, refit: false }),
  { label: 'Everything is current', disabled: true });
check('[3] refit first', m.chainRunAll({ steps: ['fit'], hub_jobs: 0, refit: true }).label, 'Run all (refit on the CPU)');
check('[3] six jobs', m.chainRunAll({ steps: ['front', 'back', 'mesh'], hub_jobs: 6, refit: false }),
  { label: 'Run all (6 hub jobs)', disabled: false });
check('[3] unknown', m.chainRunAll({ steps: ['mesh'], hub_jobs: null, refit: false }).label, 'Run all (cost unknown)');

// [4]
check('[4] photo over defaults', m.facePhotoOf({ balance: 0.5 }),
  { balance: 0.5, tone_match: 1, skin_recolor: 1, brightness: 1 });
const ctl = m.faceControlsOf(null);
check('[4] control defaults', ctl, { strength: 1, feather: 0.18, render_resolution: 768, yaw: 0 });
const photo = m.facePhotoOf(null);
check('[4] defaults valid', m.faceSettingsInvalid(photo, ctl), null);
check('[4] yaw 200', m.faceSettingsInvalid(photo, { ...ctl, yaw: 200 }), 'Yaw goes from −180 to 180 degrees');
check('[4] resolution 300.5', m.faceSettingsInvalid(photo, { ...ctl, render_resolution: 300.5 }),
  'Render resolution is a whole number from 256 to 2048');
check('[4] brightness 0.4', m.faceSettingsInvalid({ ...photo, brightness: 0.4 }, ctl),
  'Face brightness goes from 50 to 150 %');
check('[4] feather 0.6', m.faceSettingsInvalid(photo, { ...ctl, feather: 0.6 }), 'Feather goes from 0 to 0.5');
check('[4] unchanged', m.faceSettingsChanged({ photo, controls: ctl }, { photo, controls: ctl }), false);
check('[4] changed', m.faceSettingsChanged({ photo, controls: ctl }, { photo, controls: { ...ctl, strength: 0.8 } }), true);
check('[4] note', m.FACE_SETTINGS_NOTE.startsWith('Saving runs nothing.'), true);

// [5]
const tmpl = JSON.parse(src('shared/templates/character/base-character.json') || '{"tabs":[],"sections":[]}');
const ids = tmpl.tabs.map((x) => x.id);
const tab = tmpl.tabs.find((x) => x.id === 'base_body_tab') || {};
const section = tmpl.sections.find((x) => x.id === 'base_body') || {};
check('[5] tab right before Figure', ids.indexOf('base_body_tab') >= 0 && ids.indexOf('base_body_tab') + 1 === ids.indexOf('figure_tab'),
  true);
check('[5] tab labels + column', [tab.label, tab.label_de, (tab.columns || []).includes(section.column)],
  ['Base body', 'Grundkörper', true]);
check('[5] section special, no visible_when', [section.special, section.visible_when ?? null], ['base_body', null]);
const charactersTab = src('frontend/src/tabs/characters/CharactersTab.tsx');
check('[5] SPECIAL_SLOTS has base_body', /SPECIAL_SLOTS[\s\S]{0,400}'base_body'/.test(charactersTab), true);
check('[5] slot renders FieldBaseBody', /base_body:\s*\(?\s*<FieldBaseBody/.test(charactersTab), true);
const baseTab = src('frontend/src/tabs/characters/FieldBaseBody.tsx');
check('[5] FieldBaseBody posts run-all', /apiPost[^(]*\(`\/characters\/\$\{enc\}\/base-body\/run-all`/.test(baseTab), true);
check('[5] FieldBaseBody renders FaceSettings', /<FaceSettings\b/.test(baseTab), true);
check('[5] animal + temporary NPC reasons', [/An animal has no base body/.test(baseTab),
  /A temporary NPC has no base body/.test(baseTab)], [true, true]);
check('[5] FigureBodyDetails.tsx gone', existsSync(join(ROOT, 'frontend/src/tabs/characters/FigureBodyDetails.tsx')), false);

// [6]
const fieldFigure = src('frontend/src/tabs/characters/FieldFigure.tsx');
check('[6] Figure tab without the base-body details',
  /import[^\n]*(FigureBodyDetails|FieldBaseBody)|<(FigureBodyDetails|FieldBaseBody)\b/.test(fieldFigure), false);
check('[6] Figure tab: one status line + link', [/baseBodyLine\(/.test(fieldFigure),
  /t\('Open Base body tab'\)/.test(fieldFigure)], [true, true]);
const model3d = src('frontend/src/tabs/characters/FieldModel3D.tsx');
check('[6] 3D tab links the Base body tab', [/t\('Open Base body tab'\)/.test(model3d), /t\('Open Figure tab'\)/.test(model3d)],
  [true, false]);

// [7]
const faceSettings = src('frontend/src/tabs/characters/FaceSettings.tsx');
check('[7] FaceSettings saves both value sets without running',
  /apiPost\(`\/characters\/\$\{enc\}\/model3d\/options`,\s*\{\s*face_photo:\s*photo,\s*face_controls:\s*controls\s*\}/
    .test(faceSettings), true);
const faceActions = src('frontend/src/tabs/characters/ModelFaceActions.tsx');
check('[7] switches moved out of ModelFaceActions', /\bsetOption\b/.test(faceActions), false);
check('[7] dialog starts from the saved values', [/facePhotoOf\(/.test(faceActions), /faceControlsOf\(/.test(faceActions)],
  [true, true]);
const refs = src('frontend/src/tabs/characters/FieldModelRefs.tsx');
check('[7] Pose tab: no Generate on the pipeline', /\{pipelineViews \? null : \(/.test(refs), true);
check('[7] Pose tab: Auto only for kinds the Build does not decide',
  /kindList\.filter\(\(kind\) => !buildDecides\(kind\)\)\.map/.test(refs), true);
check('[7] piece dialog labels Run all by chainRunAll',
  /chainRunAll\(info\?\.run, t\)/.test(src('frontend/src/tabs/characters/WardrobeGarment.tsx')), true);

// [8]
check('[8] run-all step label', m.runAllStep('tip_smoothing'), 'Tip smoothing (local)');
check('[8] run-all what', m.runAllWhat('tip_smoothing'),
  'Tip smoothing not applied to this model yet: rebuilds the extension bones (local, no hub job)');
const tipState = (record, o = {}) => ({ groups: [{ id: 'T', label: 'Tips' }], record, due: false, light: 'ok',
  summary: '', running: false, last: null, version: 1, ...o });
const tipGroup = (o) => ({ applied: true, reason: '', max_shift_mm: 4.546, moved: 2522, radius_mm: 18.73, passes: 292,
  inverted: [22, 0], off_60: [92, 43], region_mm: 40, ...o });
check('[8] due without a record', m.tipSmoothingLine(tipState(null, { due: true })),
  'Not applied to this model yet — rebuilds the extension bones (local, no hub job)');
check('[8] applied with numbers', m.tipSmoothingLine(tipState({ version: 1, at: 'x', status: 'built', error: '',
  groups: { T: tipGroup({}) } }), undefined, () => '01:12'), 'Applied 01:12 — max shift 4.5 mm, inverted normals 22 → 0');
check('[8] failed', m.tipSmoothingLine(tipState({ version: 1, at: 'x', status: 'failed', error: 'boom', groups: {} })),
  'Last rebuild failed: boom');
check('[8] kept own tip', m.tipSmoothingLine(tipState({ version: 1, at: 'x', status: 'built', error: '',
  groups: { T: tipGroup({ applied: false, reason: 'R', max_shift_mm: null, inverted: null }) } })), 'R');
const panelOrder = ['<MeshRepairPanel', '<TipSmoothingPanel', '<ExtensionTipPanel'].map((tag) => baseTab.indexOf(tag));
check('[8] panels in step order', panelOrder.every((at, i) => at >= 0 && (i === 0 || at > panelOrder[i - 1])), true);

if (failures.length) {
  console.error('\nFAILED:\n' + failures.join('\n'));
  process.exit(1);
}
console.log('\nALL OK');
