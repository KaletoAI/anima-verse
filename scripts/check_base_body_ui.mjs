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
 *     tip (applied false, reason R) → R. FieldBaseBody renders <MeshRepairPanel, <TipSmoothingPanel and the tip
 *     panels (`tipPanels.slice(0, 1).map(tipPanel)`) in that source order.
 * [9] A switched-off tip part left neutral (Rulings A44, A53 — the mesh only): a record entry {mode neutralised,
 *     reason "Smoothed — part is off", height_mm [[3.982, .05], [5.188, .004]], bump_mm [[7.58, 0], [12.68, 0]]} → the
 *     line is that reason; the detail "Tips: <reason>, tip height 4.0 → 0.1 / 5.2 → 0.0 mm, source bump 7.6 → 0.0 /
 *     12.7 → 0.0 mm" (one decimal each); with a switched-on part U beside it, the line is the reason, "; ", then U's
 *     "Applied 01:12 — …" line. NEUTRALISED_LINE is "Smoothed — part is off" (the server's NEUTRALISED_REASON).
 * [10] The Extension bones box in the Base body tab (Ruling A45; the overlay is A56's, see [12]):
 *     extensionGroupIds({groups: {P: {bones: ["mixamorig:ExtA", "ExtB"]}, H: {hair: true, bones: ["hair_c01_0"]},
 *     E: {bones: []}}}) → ["P"] (hair groups and groups without bones left out).
 *     The readout on the hand-built rig of [12] (the extension bone ExtA bound at rest under Spine2): upright
 *     swingDeg 0; ExtA turned 30° about its parent's X: its +Y becomes (0, cos 30°, sin 30°), so swingDeg 30.
 *     Source greps: FieldBaseBody renders <ExtensionBonesBox inside `ga-ext-grid` after the first tip panel and before
 *     the others (tipPanels.slice(0, 1) … extensionBox … tipPanels.slice(1)) — only for the groups without a tip
 *     panel (`boxGroups`, Ruling A53) and only when there is one; hands the viewer `motion=` (the overlay starts off,
 *     see [13]); the CSS grid is `minmax(0, 1fr) minmax(0, 1fr)`, `align-items: start`, one column under an
 *     `@container (max-width: 520px)`; FieldModel3D leaves the Bounce / Weight sliders out on the pipeline (the 3D
 *     tab's Extension bones sub-tab is off the pipeline only — [14] and check_model3d_ui.mjs [3]).
 * [11] The tab checklist (Task UI5):
 *     baseViewRow: running → blue "Rendering"; failed "E" → red "Failed", "E"; nothing stored → yellow "Not rendered
 *     yet"; stale {reason R, action A} → yellow "Outdated", "R", mouse-over "R\nA"; stale without a reason → "Made from
 *     older data"; current with warning W → yellow "Kept with a warning", "W"; current → green "Current".
 *     baseModelRow: none → yellow "Not built yet"; running → blue "Building now"; failed "boom" → red "Failed", "boom";
 *     unrigged → yellow "Static mesh without a rig"; ready but stale R → yellow "Outdated", "R"; ready → green "Ready".
 *     baseHead(runAll, lights, baseBusy): Run all running → blue "Building now"; base-body work in flight (the third
 *     argument, `plain_body.activity.base` — never an outfit build, Ruling A55 / smoke_base_status_isolated.py) → blue;
 *     a red light → red "A step failed"; nothing planned but the last Run all failed → red; plan of 3 steps → yellow
 *     "3 steps due" (Run all's steps, not the lights); a plan with an empty step list → "1 step due"; no plan, one yellow light
 *     → "1 step due"; nothing → green "Up to date".
 *     runAllPlanLine([view back 1, mesh 1, cleanup 0, face 2, rig null]) → "Back view (1) · Mesh (1) · Face cleanup
 *     (local) · Face retexture (2) · Rig (cost unknown)"; no plan → "".
 *     Source greps: FieldBaseBody has SubTabs, no <details>, the viewer without a side toolbar and with builtAt; each
 *     tip panel carries its own Rebuild (Ruling A53: no `rebuildElsewhere`); the tip panel, the mesh repair panel, the
 *     motion values and
 *     the collision sliders say "Discard changes" and (where a reset exists) "Reset to default", never "Revert" /
 *     "Reset" (both "Zurücksetzen" in German); the motion value rows show the name before " (" or ";" with the full
 *     wording as mouse-over.
 * [12] The extension-group overlay (Ruling A56): the surface a group moves, as a weighted wire, not bone lines.
 *     A skinned strip of one triangle — v0 (0, 0, 0), v1 (0.1, 0, 0), v2 (0.2, 0.1, 0), all with normal (0, 0, 1) —
 *     on the skeleton [Spine2, ExtA]: v0 weight 1 to ExtA; v1 0.5 to ExtA + 0.5 to Spine2; v2 1 to Spine2 (0 to
 *     ExtA). weightedRegion(strip, {1}, 0.1): v0 (1 > 0.1) and v1 (0.5 > 0.1) are in, v2 (0) is out → vertices
 *     [0, 1], alpha [1, 0.5], and of the triangle's edges only v0–v1 has both ends in → edges [0, 1]. A threshold of
 *     0.6 keeps v0 alone (vertices [0], no edge).
 *     The overlay of group G {bones: ["mixamorig:ExtA"]} on root (scale 2) ▸ Spine2 ▸ ExtA + the strip: 1 wire, the
 *     legend list [{id G, colour 0, 2 vertices}]; the wire's index [0, 1]; its colour alphas [1, 0.5]; its skin
 *     indices of v1 [1, 0, 0, 0] with weights [0.5, 0.5, 0, 0] (copied as they stand); its positions are the
 *     strip's pushed OFFSET_M (0.0015 m) out along the normal in the strip's own units — the world scale is 2, so
 *     0.0015 / 2 = 0.00075: (0, 0, 0.00075) and (0.1, 0, 0.00075); it is skinned by the strip's OWN skeleton
 *     object (isSkinnedMesh, same skeleton), so the GPU deforms it with the mesh. After update() its matrix is the
 *     strip's world matrix (scale 2).
 *     A pure chain — group C {bones: ["ChainA"]} that skins nothing, with a plain one-triangle mesh hung under ChainA
 *     — takes that attached part: 3 vertices, alpha 1 each, 3 edges, not skinned.
 *     dispose(): the overlay group and its wire leave the scene; exactly the wire's own geometry and material fire
 *     "dispose" — the strip's geometry and material, the part's geometry and the skeleton's bone texture fire
 *     nothing.
 *     Source greps: Model3DViewer builds createExtensionGroupOverlay (no bone lines module left) and renders the
 *     legend `ga-ext-legend` from the overlay's groups with groupColorCss.
 * [13] Both switches start off (Ruling A62) — view switches of the open tab, held in component state only (no
 *     localStorage, no profile option), so a fresh load is always off:
 *     TIP_MARKERS_START_SHOWN is false. tipPreviewDots on a hand-built panel — left {suggested (0.1, 1.3, 0.2), built
 *     tip (0.1, 1.28, 0.19), tangent_up (0, 1, 0), tangent_out (1, 0, 0), offset 0}, right {suggested (−0.1, 1.3, 0.2),
 *     not built, tangent_out (−1, 0, 0)}, a zero draft:
 *       hidden (the fresh load)              → null (no dots reach the viewer);
 *       shown (the box ticked)               → left at its built tip (0.1, 1.28, 0.19), right at its suggestion
 *                                              (−0.1, 1.3, 0.2), both "#3fb950" (built);
 *       left up 4 mm, out 2 mm               → du 0.004, dout 0.002: left (0.102, 1.284, 0.19) "#f0b35c" (draft),
 *                                              right unchanged;
 *       the same with mirror                 → right takes offsets[0] too: (−0.1 − 0.002, 1.304, 0.2) = (−0.102,
 *                                              1.304, 0.2), draft colour;
 *       shown but the group off              → null; shown but no side found → null.
 *     The panel rendered fresh (react-dom/server, en): its "Show markers" box is unchecked; it starts from
 *     TIP_MARKERS_START_SHOWN, the box sets it, a moved slider sets it true, and the dots come from tipPreviewDots.
 *     The viewer: `extensionBones = false` and `useState(extensionBones)`; no other file names `extensionBones`, so
 *     the Base body, 3D and Figure tabs' viewers all start with the grid off; the toggle flips it
 *     (`setBonesOn(on => !on)`, aria-pressed) and the frame loop builds the overlay of [12] once it is on — the
 *     overlay itself is [12]'s numbers. Neither switch is persisted: no localStorage / usePersistentState in the
 *     viewer or the tip panel.
 * [14] The state preview beside the base body viewer (Ruling A66, moved from the 3D tab):
 *     statePicker(groups, states):
 *       0 groups, any states                      → no options, "This base model has no extension bones — a state has
 *                                                   nothing to move here."
 *       2 groups, []                              → no options, "No state moves the extension bones of this base model."
 *       2 groups, [{lifted, "Lifted"}, {calm, ""}] → options ["" "None (at rest)", lifted "Lifted", calm "calm" (no
 *                                                   label: the id)], "Preview only — nothing is saved, nothing runs."
 *     stateMotionUrl("demo x", "a/b") → "/characters/demo%20x/base-body/state-motion?state=a%2Fb" (a GET).
 *     The motion handed to the viewer = previewMotionSliders(viewerStateMotion(rest, picked state, fetched, signature),
 *     defaults, overrides, drafts). Rest R: group G {rest_deg 0, length 1, max_deg 30}; the fetched state S for
 *     "lifted" on signature "s1": G {rest_deg 12, length 1.5, max_deg 15}; defaults G {max_deg 30}:
 *       nothing picked                             → R itself;
 *       "lifted" picked, S arrived for "lifted"/s1 → S itself (rest_deg 12, length 1.5);
 *       "calm" picked while only S is there        → R (it loads; never another state's motion);
 *       S fetched for signature "s0" (another base model) → R;
 *       "lifted" + a Bounce 2 draft on G           → the state stays under the draft: max_deg 15 × min(180, 30·2) /
 *                                                   min(180, 30·1) = 30, rest_deg 12, length 1.5;
 *       back to "" (None)                          → R again (rest restored).
 *     The row rendered (react-dom/server, en) with the picker of the third case: a <select> with exactly those three
 *     options in that order and the note; with the picker of the first case: no <select>, the no-groups line.
 *     Source greps: FieldBaseBody hands the viewer `motion={ready ? previewMotion : undefined}`, previewMotion is
 *     `previewMotionSliders(restOrState, …)` with `restOrState = viewerStateMotion(extPayload, pickedState, stateMotion,
 *     extSignature)`, the motion is fetched with `apiGet<…>(stateMotionUrl(character, pickedState))`, the row
 *     <StatePreviewRow sits after the viewer; the state preview code (StatePreviewRow.tsx, the block between
 *     `const picker = statePicker(` and previewMotion) holds no apiPost / POST — nothing is saved, nothing runs; it
 *     does not depend on the grid switch (no `bonesOn` / `extensionBones` in it), so a state moves the parts with the
 *     grid off. The 3D tab: Model3DSidePanels lists the Extension bones sub-tab only through `hasExtensionSection`
 *     (off the pipeline, with groups) and no longer carries the pipeline pointer ("Set on the base body"), FieldModel3D
 *     renders "Preview state" only under `statePreviewHere ?` with `statePreviewHere = hasExtensionSection(st)`.
 */
import { existsSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
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

/** The tip panel rendered once, as a fresh load does (react-dom/server: no effects, no clicks), inside the i18n and
 *  toast providers — one bundle, so React is a single instance. */
async function renderTipPanelFresh(panel) {
  const esbuild = esbuildModule();
  const dir = await mkdtemp(join(tmpdir(), 'check-base-body-ui-ssr-'));
  try {
    const entry = join(dir, 'entry.tsx');
    const file = join(dir, 'ssr.cjs');
    const at = (rel) => JSON.stringify(join(ROOT, rel));
    writeFileSync(entry, [
      `import { renderToStaticMarkup } from 'react-dom/server'`,
      `import { I18nProvider } from ${at('frontend/src/i18n/I18nProvider.tsx')}`,
      `import { ToastProvider } from ${at('frontend/src/lib/Toast.tsx')}`,
      `import { ExtensionTipPanel } from ${at('frontend/src/tabs/characters/ExtensionTipPanel.tsx')}`,
      `export const render = (panel) => renderToStaticMarkup(<I18nProvider><ToastProvider><ExtensionTipPanel`,
      `  character="demo" signature="s" panel={panel} disabled={false} onPreview={() => {}} onStarted={() => {}} />`,
      `</ToastProvider></I18nProvider>)`,
    ].join('\n'));
    await esbuild.build({
      entryPoints: [entry], outfile: file, bundle: true, format: 'cjs', platform: 'node', jsx: 'automatic',
      logLevel: 'silent', absWorkingDir: ROOT, nodePaths: [join(ROOT, 'node_modules')],
      define: { 'process.env.NODE_ENV': '"production"' }, loader: { '.css': 'empty' },
    });
    return require_(file).render(panel);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

/** The state preview row rendered once (react-dom/server, en) with a given picker. */
async function renderStateRow(picker) {
  const esbuild = esbuildModule();
  const dir = await mkdtemp(join(tmpdir(), 'check-base-body-ui-row-'));
  try {
    const entry = join(dir, 'entry.tsx');
    const file = join(dir, 'ssr.cjs');
    const at = (rel) => JSON.stringify(join(ROOT, rel));
    writeFileSync(entry, [
      `import { renderToStaticMarkup } from 'react-dom/server'`,
      `import { I18nProvider } from ${at('frontend/src/i18n/I18nProvider.tsx')}`,
      `import { StatePreviewRow } from ${at('frontend/src/tabs/characters/StatePreviewRow.tsx')}`,
      `export const render = (picker) => renderToStaticMarkup(<I18nProvider><StatePreviewRow picker={picker}`,
      `  value="" loading={false} error="" onChange={() => {}} /></I18nProvider>)`,
    ].join('\n'));
    await esbuild.build({
      entryPoints: [entry], outfile: file, bundle: true, format: 'cjs', platform: 'node', jsx: 'automatic',
      logLevel: 'silent', absWorkingDir: ROOT, nodePaths: [join(ROOT, 'node_modules')],
      define: { 'process.env.NODE_ENV': '"production"' }, loader: { '.css': 'empty' },
    });
    return require_(file).render(picker);
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
check('[7] Dressed views: no Generate on the pipeline', /\{pipelineViews \? null : \(/.test(refs), true);
check('[7] Dressed views: Auto only for kinds the Build does not decide',
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
// [9]
const neutral = tipGroup({ mode: 'neutralised', reason: 'Smoothed — part is off', inverted: null,
  off_60: null, height_mm: [[3.982, 0.05], [5.188, 0.004]], bump_mm: [[7.58, 0], [12.68, 0]] });
check('[9] NEUTRALISED_LINE', m.NEUTRALISED_LINE, 'Smoothed — part is off');
check('[9] neutralised line', m.tipSmoothingLine(tipState({ version: 1, at: 'x', status: 'built', error: '',
  groups: { T: neutral } })), 'Smoothed — part is off');
check('[9] neutralised detail', m.tipSmoothingDetail(tipState({ version: 1, at: 'x', status: 'built', error: '',
  groups: { T: neutral } }))[0],
  'Tips: Smoothed — part is off, tip height 4.0 → 0.1 / 5.2 → 0.0 mm, source bump 7.6 → 0.0 / 12.7 → 0.0 mm');
check('[9] neutralised + smoothed', m.tipSmoothingLine(tipState({ version: 1, at: 'x', status: 'built', error: '',
  groups: { T: neutral, U: tipGroup({}) } }), undefined, () => '01:12'),
  'Smoothed — part is off; Applied 01:12 — max shift 4.5 mm, inverted normals 22 → 0');
// The tip panels render through the tab's `tipPanel` helper (Ruling A53); their place is where the grid maps it.
const panelOrder = ['<MeshRepairPanel', '<TipSmoothingPanel', 'tipPanels.slice(0, 1).map(tipPanel)'].map((tag) => baseTab.indexOf(tag));
check('[8] panels in step order', panelOrder.every((at, i) => at >= 0 && (i === 0 || at > panelOrder[i - 1])), true);

// [10]
const overlay = await loadBundled('frontend/src/tabs/characters/extensionGroupOverlay.ts');
check('[10] group ids', overlay.extensionGroupIds({ rev: 'r', groups: {
  P: { bones: ['mixamorig:ExtA', 'ExtB'] }, H: { hair: true, bones: ['hair_c01_0'] }, E: { bones: [] } } }), ['P']);
const THREE = require_(join(ROOT, 'node_modules/three/build/three.cjs'));
const disposed = [];
const spy = (obj, name) => { obj.addEventListener('dispose', () => disposed.push(name)); return obj; };
const rigRoot = new THREE.Scene();
const figureRoot = new THREE.Group();
figureRoot.scale.setScalar(2);
rigRoot.add(figureRoot);
const spine = new THREE.Bone();
spine.name = 'mixamorigSpine2';
spine.position.set(0, 0.6, 0);
const leaf = new THREE.Bone();
leaf.name = 'mixamorig:ExtA';
leaf.position.set(0.05, 0.05, 0.04);
spine.add(leaf);
const chain = new THREE.Bone();
chain.name = 'ChainA';
chain.position.set(0, 0.1, 0);
spine.add(chain);
const strip = spy(new THREE.BufferGeometry(), 'strip geometry');
strip.setAttribute('position', new THREE.Float32BufferAttribute([0, 0, 0, 0.1, 0, 0, 0.2, 0.1, 0], 3));
strip.setAttribute('normal', new THREE.Float32BufferAttribute([0, 0, 1, 0, 0, 1, 0, 0, 1], 3));
strip.setAttribute('skinIndex', new THREE.Uint16BufferAttribute([1, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0], 4));
strip.setAttribute('skinWeight', new THREE.Float32BufferAttribute([1, 0, 0, 0, 0.5, 0.5, 0, 0, 1, 0, 0, 0], 4));
strip.setIndex([0, 1, 2]);
const skin = new THREE.SkinnedMesh(strip, spy(new THREE.MeshBasicMaterial(), 'strip material'));
const part = new THREE.Mesh(spy(new THREE.BufferGeometry(), 'part geometry'), new THREE.MeshBasicMaterial());
part.geometry.setAttribute('position', new THREE.Float32BufferAttribute([0, 0, 0, 0.01, 0, 0, 0, 0.01, 0], 3));
chain.add(part);
figureRoot.add(spine, skin);
rigRoot.updateMatrixWorld(true);
skin.bind(new THREE.Skeleton([spine, leaf, chain]));
skin.skeleton.boneTexture = { dispose: () => disposed.push('bone texture') };
const groupsG = { rev: 'r', groups: { G: { bones: ['mixamorig:ExtA'] } } };
const ov = overlay.createExtensionGroupOverlay(THREE, figureRoot, groupsG);
rigRoot.add(ov.group);
ov.update();
check('[10] upright swing', ov.swingDeg(), 0);
leaf.quaternion.setFromAxisAngle(new THREE.Vector3(1, 0, 0), Math.PI / 6);
rigRoot.updateMatrixWorld(true);
check('[10] turned 30°', ov.swingDeg(), 30);
leaf.quaternion.identity();
rigRoot.updateMatrixWorld(true);

// [12]
const round = (a) => Array.from(a, (v) => Math.round(v * 1e6) / 1e6);
const region = overlay.weightedRegion(strip, new Set([1]), 0.1);
check('[12] region of the strip', [region.vertices, region.alpha, region.edges], [[0, 1], [1, 0.5], [0, 1]]);
const tight = overlay.weightedRegion(strip, new Set([1]), 0.6);
check('[12] a higher threshold', [tight.vertices, tight.edges], [[0], []]);
check('[12] one wire, the legend', [ov.count, ov.groups], [1, [{ id: 'G', color: 0, vertices: 2 }]]);
const wire = ov.group.children[0];
const wg = wire.geometry;
check('[12] wire index and alphas', [Array.from(wg.getIndex().array),
  [0, 1].map((i) => wg.getAttribute('color').getW(i))], [[0, 1], [1, 0.5]]);
check('[12] wire skin of v1', [[0, 1, 2, 3].map((k) => wg.getAttribute('skinIndex').getComponent(1, k)),
  [0, 1, 2, 3].map((k) => wg.getAttribute('skinWeight').getComponent(1, k))], [[1, 0, 0, 0], [0.5, 0.5, 0, 0]]);
check('[12] wire sits OFFSET_M above the skin', round(wg.getAttribute('position').array), [0, 0, 0.00075, 0.1, 0, 0.00075]);
check('[12] skinned by the strip\'s own skeleton', [wire.isSkinnedMesh, wire.skeleton === skin.skeleton, wire.isLineSegments],
  [true, true, true]);
check('[12] wire takes the strip\'s world matrix', round(wire.matrixWorld.elements), round(skin.matrixWorld.elements));
const chainOv = overlay.createExtensionGroupOverlay(THREE, figureRoot, { rev: 'c', groups: { C: { bones: ['ChainA'] } } });
const cw = chainOv?.group.children[0];
check('[12] a pure chain takes its attached part', [chainOv?.groups, Array.from(cw.geometry.getIndex().array).length / 2,
  [0, 1, 2].map((i) => cw.geometry.getAttribute('color').getW(i)), !!cw.isSkinnedMesh],
[[{ id: 'C', color: 0, vertices: 3 }], 3, [1, 1, 1], false]);
chainOv.dispose();
disposed.length = 0;
spy(wg, 'wire geometry');
spy(wire.material, 'wire material');
ov.dispose();
check('[12] dispose frees only its own', [ov.group.parent, rigRoot.children.length, wire.parent, disposed.sort()],
  [null, 1, null, ['wire geometry', 'wire material']]);
const viewerSrc = src('frontend/src/tabs/characters/Model3DViewer.tsx');
check('[12] viewer: group overlay and legend', [/createExtensionGroupOverlay\(THREE, object, motionRef\.current\)/.test(viewerSrc),
  existsSync(join(ROOT, 'frontend/src/tabs/characters/extensionBoneOverlay.ts')),
  /className="ga-ext-legend"[\s\S]{0,400}bonesLegend\.map[\s\S]{0,300}groupColorCss\(g\.color\)/.test(viewerSrc)],
[true, false, true]);
const gridAt = baseTab.indexOf('className="ga-ext-grid"');
const firstTip = baseTab.indexOf('tipPanels.slice(0, 1)', gridAt);
const boxAt = baseTab.indexOf('{extensionBox}', gridAt);
const restTips = baseTab.indexOf('tipPanels.slice(1)', gridAt);
check('[10] box beside the first tip panel', gridAt > 0 && gridAt < firstTip && firstTip < boxAt && boxAt < restTips, true);
check('[10] box element', /<ExtensionBonesBox legend=\{t\('Extension bones'\)\}/.test(baseTab), true);
check('[10] viewer plays the base motion',
  /motion=\{ready \? previewMotion : undefined\}/.test(baseTab), true);
const css = src('frontend/src/styles/game-admin.css');
check('[10] two equal columns, top-aligned',
  /\.ga-ext-grid \{ display: grid; grid-template-columns: minmax\(0, 1fr\) minmax\(0, 1fr\);[^}]*align-items: start;/.test(css), true);
check('[10] one column when narrow',
  /@container \(max-width: 520px\) \{ \.ga-ext-grid \{ grid-template-columns: minmax\(0, 1fr\); \} \}/.test(css), true);
const sidePanels = src('frontend/src/tabs/characters/Model3DSidePanels.tsx');
check('[10] 3D tab: no sliders on the pipeline', /const sliderTools = rigless \|\| pipeline \? null : motionToolbar/.test(model3d), true);

// [11]
const vrow = (o) => { const r = m.baseViewRow({ running: false, failed: false, stored: true, ...o }); return [r.light, r.state, r.reason]; };
check('[11] view running', vrow({ running: true }), ['blue', 'Rendering', '']);
check('[11] view failed', vrow({ failed: true, error: 'E' }), ['red', 'Failed', 'E']);
check('[11] view missing', vrow({ stored: false }), ['yellow', 'Not rendered yet', '']);
check('[11] view stale', m.baseViewRow({ running: false, failed: false, stored: true,
  freshness: { state: 'stale', reason: 'R', action: 'A' } }).detail, 'R\nA');
check('[11] view stale reason', vrow({ freshness: { state: 'stale', reason: 'R' } }), ['yellow', 'Outdated', 'R']);
check('[11] view stale without a reason', vrow({ freshness: { state: 'stale' } })[2], 'Made from older data');
check('[11] view warning', vrow({ warning: 'W', freshness: { state: 'current' } }), ['yellow', 'Kept with a warning', 'W']);
check('[11] view current', vrow({ freshness: { state: 'current' } }), ['green', 'Current', '']);
const mrow = (o) => { const r = m.baseModelRow(o); return [r.light, r.state, r.reason]; };
check('[11] model rows', [mrow(null), mrow({ status: 'running' }), mrow({ status: 'failed', error: 'boom' }),
  mrow({ status: 'unrigged' }), mrow({ status: 'ready', freshness: { state: 'stale', reason: 'R' } }), mrow({ status: 'ready' })],
[['yellow', 'Not built yet', ''], ['blue', 'Building now', ''], ['red', 'Failed', 'boom'],
  ['yellow', 'Static mesh without a rig', ''], ['yellow', 'Outdated', 'R'], ['green', 'Ready', '']]);
const bh = (r, l, b = false) => { const h = m.baseHead(r, l, b); return [h.light, h.words]; };
const step = (name, jobs) => ({ name, jobs });
check('[11] head', [bh(ra({ running: true }), []), bh(null, ['green'], true), bh(null, ['green', 'red']),
  bh(ra({ last: { error: 'x', finished_at: '' } }), ['green']),
  bh(ra({ kind: 'plain_body', steps: [step('mesh', 1), step('face', 2), step('rig', 1)] }), ['green']),
  bh(ra({ kind: 'face_cleanup', steps: [] }), ['green']), bh(null, ['yellow', 'green']), bh(ra({}), ['green', 'green'])],
[['blue', 'Building now'], ['blue', 'Building now'], ['red', 'A step failed'], ['red', 'A step failed'],
  ['yellow', '3 steps due'], ['yellow', '1 step due'], ['yellow', '1 step due'], ['green', 'Up to date']]);
check('[11] plan line', [m.runAllPlanLine(ra({ kind: 'plain_body', steps: [step('view back', 1), step('mesh', 1),
  step('cleanup', 0), step('face', 2), step('rig', null)] })), m.runAllPlanLine(ra({}))],
['Back view (1) · Mesh (1) · Face cleanup (local) · Face retexture (2) · Rig (cost unknown)', '']);
const baseViewer = (baseTab.match(/<Model3DViewer[\s\S]*?\/>/) || [''])[0];
check('[11] sub-tabs, no <details>, viewer', [/<SubTabs\b/.test(baseTab), /<details>/.test(baseTab),
  /sideToolbar/.test(baseViewer), /builtAt=\{model\.created_at\}/.test(baseViewer)], [true, false, false, true]);
const tipSrc = src('frontend/src/tabs/characters/ExtensionTipPanel.tsx');
check('[11] each tip panel has its own Rebuild', [/rebuildElsewhere/.test(baseTab + tipSrc),
  (tipSrc.match(/t\(TIP_REBUILD_LABEL\)/g) || []).length], [false, 1]);
const labelled = ['ExtensionTipPanel', 'MeshRepairPanel', 'ExtensionMotionDraft', 'CollisionScales']
  .map((f) => src(`frontend/src/tabs/characters/${f}.tsx`));
check('[11] distinct reset labels', labelled.map((x) => [/t\('Discard changes'\)/.test(x), /t\('(Revert|Reset)'\)/.test(x)]),
  [[true, false], [true, false], [true, false], [true, false]]);
check('[11] motion values: the name, the full wording on mouse-over',
  /title=\{t\(label\)\}>[\s\S]{0,80}\{t\(label\)\.split\(\/ \\\(\|;\/\)\[0\]\}/.test(labelled[2]), true);

// [13]
check('[13] markers start hidden', m.TIP_MARKERS_START_SHOWN, false);
const tipSides = [
  { side: 'left', suggested: [0.1, 1.3, 0.2], tip: [0.1, 1.28, 0.19], tangent_up: [0, 1, 0], tangent_out: [1, 0, 0], offset_mm: [0, 0] },
  { side: 'right', suggested: [-0.1, 1.3, 0.2], tip: null, tangent_up: [0, 1, 0], tangent_out: [-1, 0, 0], offset_mm: [0, 0] },
];
const zeroDraft = { offsets: [{ up: 0, out: 0 }, { up: 0, out: 0 }], mirror: false };
const movedDraft = { offsets: [{ up: 4, out: 2 }, { up: 0, out: 0 }], mirror: false };
const dotsOf = (d) => d && d.map((x) => ({ at: x.at.map((v) => Math.round(v * 1e6) / 1e6), color: x.color }));
check('[13] fresh load: no dots', m.tipPreviewDots({ sides: tipSides }, zeroDraft, m.TIP_MARKERS_START_SHOWN, false), null);
check('[13] shown: built tip + suggestion', dotsOf(m.tipPreviewDots({ sides: tipSides }, zeroDraft, true, false)),
  [{ at: [0.1, 1.28, 0.19], color: '#3fb950' }, { at: [-0.1, 1.3, 0.2], color: '#3fb950' }]);
check('[13] left moved', dotsOf(m.tipPreviewDots({ sides: tipSides }, movedDraft, true, false)),
  [{ at: [0.102, 1.284, 0.19], color: '#f0b35c' }, { at: [-0.1, 1.3, 0.2], color: '#3fb950' }]);
check('[13] mirrored', dotsOf(m.tipPreviewDots({ sides: tipSides }, { ...movedDraft, mirror: true }, true, false)),
  [{ at: [0.102, 1.284, 0.19], color: '#f0b35c' }, { at: [-0.102, 1.304, 0.2], color: '#f0b35c' }]);
check('[13] group off / no side', [m.tipPreviewDots({ sides: tipSides }, zeroDraft, true, true),
  m.tipPreviewDots({ sides: [null, null] }, zeroDraft, true, false)], [null, null]);
const tipHtml = await renderTipPanelFresh({
  id: 'G', label: 'G', enabled: true, active: true, status: 'applied', reason: '', tip_source: 'colour', sides: tipSides,
  override: null, disc: null, running: false, due: false, error: '', light: null, controls: [], built_at: null,
  limits: { offset_max_mm: 30, diameter_mm: [10, 50], soft_max_mm: 10,
    disc_defaults: { enabled: false, color: '#c07a72', diameter_mm: 28, soft_mm: 3 } },
});
const markerBox = (tipHtml.match(/<input([^>]*)\/>Show markers/) || [])[1];
check('[13] panel renders "Show markers" unchecked', [markerBox !== undefined, /\bchecked/.test(markerBox ?? 'checked')], [true, false]);
check('[13] panel: start value, the box, a moved slider, the dots helper', [
  /useState\(TIP_MARKERS_START_SHOWN\)/.test(tipSrc),
  /checked=\{showDots\} onChange=\{\(event\) => setShowDots\(event\.target\.checked\)\}/.test(tipSrc),
  /const setOffset = [^\n]*\{ setShowDots\(true\)/.test(tipSrc),
  /onPreview\(panel\.id, tipPreviewDots\(panel, draft, showDots, off\)\)/.test(tipSrc)], [true, true, true, true]);
const frontFiles = (dir) => readdirSync(join(ROOT, dir), { recursive: true }).filter((f) => /\.tsx?$/.test(f))
  .map((f) => join(dir, f));
const namesOverlayStart = ['frontend/src', 'packages/player-ui/src', 'client3d/src'].flatMap(frontFiles)
  .filter((f) => !f.endsWith('Model3DViewer.tsx') && /\bextensionBones\b/.test(src(f)));
check('[13] viewer starts with the grid off, everywhere', [/\bextensionBones = false\b/.test(viewerSrc),
  /const \[bonesOn, setBonesOn\] = useState\(extensionBones\)/.test(viewerSrc), namesOverlayStart], [true, true, []]);
check('[13] the toggle turns it on and the frame loop builds the overlay', [
  /aria-pressed=\{bonesOn\} onClick=\{\(\) => setBonesOn\(on => !on\)\}/.test(viewerSrc),
  /bonesWanted = bonesOnRef\.current && motionRef\.current \? motionRef\.current\.rev : null[\s\S]{0,300}createExtensionGroupOverlay\(/
    .test(viewerSrc)], [true, true]);
check('[13] neither switch is persisted', [viewerSrc, tipSrc].map((x) => /localStorage|sessionStorage|usePersistentState/.test(x)),
  [false, false]);

// [14]
check('[14] no groups', m.statePicker(0, [{ id: 'lifted', label: 'Lifted' }]),
  { options: [], note: 'This base model has no extension bones — a state has nothing to move here.' });
check('[14] no state moves them', m.statePicker(2, []),
  { options: [], note: 'No state moves the extension bones of this base model.' });
const picker = m.statePicker(2, [{ id: 'lifted', label: 'Lifted' }, { id: 'calm', label: '' }]);
check('[14] the declared states', picker, { options: [{ value: '', label: 'None (at rest)' },
  { value: 'lifted', label: 'Lifted' }, { value: 'calm', label: 'calm' }], note: 'Preview only — nothing is saved, nothing runs.' });
check('[14] the GET', m.stateMotionUrl('demo x', 'a/b'), '/characters/demo%20x/base-body/state-motion?state=a%2Fb');
const sliders = await loadBundled('frontend/src/tabs/characters/motionFieldPreview.ts');
const R = { rev: 'r', groups: { G: { bones: ['b'], rest_deg: 0, length: 1, max_deg: 30 } } };
const S = { rev: 's', groups: { G: { bones: ['b'], rest_deg: 12, length: 1.5, max_deg: 15 } } };
const fetched = { state: 'lifted', signature: 's1', motion: S };
const handed = (selected, picked, drafts = {}) => sliders.previewMotionSliders(
  m.viewerStateMotion(R, selected, picked, 's1'), { G: { max_deg: 30 } }, {}, drafts);
check('[14] nothing picked → rest', handed('', fetched) === R, true);
check('[14] a pick drives the viewer with that state', handed('lifted', fetched) === S, true);
check('[14] another pick loads: rest, never another state', handed('calm', fetched) === R, true);
check('[14] a pick of another base model → rest', handed('lifted', { ...fetched, signature: 's0' }) === R, true);
const drafted = handed('lifted', fetched, { G: { bounce: 2 } }).groups.G;
check('[14] the Bounce draft rides on the state', [drafted.max_deg, drafted.rest_deg, drafted.length], [30, 12, 1.5]);
check('[14] None restores rest', handed('', fetched) === R, true);
const rowHtml = await renderStateRow(picker);
const optionsHtml = [...rowHtml.matchAll(/<option value="([^"]*)"[^>]*>([^<]*)<\/option>/g)].map((x) => [x[1], x[2]]);
check('[14] the row lists the declared states', [/<select/.test(rowHtml), optionsHtml,
  rowHtml.includes('Preview only — nothing is saved, nothing runs.')],
[true, [['', 'None (at rest)'], ['lifted', 'Lifted'], ['calm', 'calm']], true]);
const emptyRow = await renderStateRow(m.statePicker(0, []));
check('[14] no groups: the line, no picker', [/<select/.test(emptyRow),
  emptyRow.includes('This base model has no extension bones')], [false, true]);
check('[14] the viewer plays the state motion', [/motion=\{ready \? previewMotion : undefined\}/.test(baseTab),
  /previewMotionSliders\(restOrState,/.test(baseTab),
  /const restOrState = viewerStateMotion\(extPayload, pickedState, stateMotion, extSignature\)/.test(baseTab),
  /apiGet<[^>]*>\(stateMotionUrl\(character, pickedState\)\)/.test(baseTab)], [true, true, true, true]);
check('[14] the row sits after the viewer', baseTab.indexOf('<Model3DViewer') > 0
  && baseTab.indexOf('<StatePreviewRow', baseTab.indexOf('<Model3DViewer')) > 0, true);
const stateBlock = baseTab.slice(baseTab.indexOf('const picker = statePicker('), baseTab.indexOf('const previewMotion = useMemo'))
  + src('frontend/src/tabs/characters/StatePreviewRow.tsx');
check('[14] a read only, independent of the grid', [stateBlock.length > 400, /apiPost|'POST'|method:/.test(stateBlock),
  /bonesOn|extensionBones/.test(stateBlock)], [true, false, false]);
check('[14] the 3D tab: no pipeline pointer, the sub-tab only via hasExtensionSection', [
  /Set on the base body/.test(sidePanels), /\.\.\.\(extensions \? \[\{ id: 'extensions'/.test(sidePanels),
  /const extensions = !!panel && hasExtensionSection\(panel\.st\)/.test(sidePanels)], [false, true, true]);
check('[14] the 3D tab: Preview state only off the pipeline', [
  /const statePreviewHere = hasExtensionSection\(st\)/.test(model3d),
  /\{statePreviewHere \? \([\s\S]{0,200}t\('Preview state'\)/.test(model3d),
  (model3d.match(/t\('Preview state'\)/g) || []).length], [true, true, 1]);

if (failures.length) {
  console.error('\nFAILED:\n' + failures.join('\n'));
  process.exit(1);
}
console.log('\nALL OK');
