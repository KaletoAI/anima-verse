#!/usr/bin/env node
/**
 * Check of the figure UI's pure helpers — `frontend/src/tabs/characters/figureModel.ts`
 * (plan docs/superpowers/plans/2026-11-12-unified-worn-pieces.md, Task 9; Task 10 extends it).
 *
 * Usage:  node scripts/check_figure_ui.mjs
 *
 * Self-bundling via esbuild (like scripts/check_footwear.mjs); no server, no world. Exit 1 on the first
 * mismatch list, 0 when every case holds.
 *
 * ============================================================================
 * THE CASES, DERIVED BY HAND (plan "Global Constraints", Task 9 "Interfaces", spec rulings 3, 5, 6)
 * ============================================================================
 * [1] Labels, verbatim from the plan:
 *       MESH_MODE_LABELS  own_mesh → "Own mesh", painted → "Painted", in_body → "In the body"
 *       HAIR_MODE_LABELS  hairdeck → "HairDeck", haar → "HAAR", body → "In the body"
 *     MESH_MODES / HAIR_MODES list them in that order (the select's order).
 * [2] hairModeDisabled: HAAR is listed but not built (ruling 6) → 'haar' = "not built yet";
 *     'hairdeck' and 'body' are selectable → null.
 * [3] wearersLine(n, hubJobs) — ruling 3, "worn by K characters now" + "Build for them (cost)":
 *       (0, 0)    → text "worn by 0 characters now", button null, reason "Nobody wears it now"
 *       (2, 7)    → text "worn by 2 characters now", button "Build for them (7 hub jobs)", reason null
 *       (2, null) → button "Build for them (cost unknown)" (a wearer's cost is unknown → the total is)
 *       (1, 1)    → singular both ways: "worn by 1 character now", "Build for them (1 hub job)"
 * [4] defaultMeshMode(slots) mirrors `garment_set.default_mesh_mode` (spec Q2): exactly feet → own_mesh;
 *       outer among them, or both top and bottom → in_body; everything else → painted:
 *       ['feet'] → own_mesh · ['legs','feet'] → painted (not feet ALONE) · ['outer'] → in_body ·
 *       ['top','bottom'] → in_body · ['top'] → painted · [] → painted
 * [5] meshModeOf(stored, slots): a stored valid mode wins ('in_body' on ['feet'] → in_body); '' or an
 *       unknown word → the kind default (''/['feet'] → own_mesh, 'own'/['top'] → painted).
 * [6] figureBuildLine(changes, hubJobs) — the hair row's line after a mode change (the character's own
 *       Build, POST /characters/{c}/figure/build):
 *       (0, 0)    → text "No changes", button null, reason "Nothing to build"
 *       (2, 7)    → text "2 changes", button "Build (7 hub jobs)", reason null
 *       (1, null) → text "1 change", button "Build (cost unknown)"
 *       (1, 0)    → button "Build (0 hub jobs)" (CPU-only work is still a Build)
 * [7] Source greps: `WardrobeGarment.tsx` exports no `OwnMeshToggle` (MeshModeSelect replaces it);
 *     `ItemForm.tsx` has no mode checkbox (`mesh_mode === 'own_mesh'` gone — the mode is read-only
 *     there) and `itemsModel.ts`'s draftToBody no longer sends `mesh_mode` (a stale form never
 *     overwrites a Wardrobe choice: `inventory.update_item` keeps the stored mode when the key is
 *     absent); `FootwearSteps.tsx` no longer claims "×1.50 high" for every shoe (Ruling 15i: the
 *     height scale is only for a closed toe box, only as a second try).
 *
 * Task 10 — the Figure tab (spec "The UI" sketch and "Rules for the buttons", rulings 8, 7a, 8a):
 * [8] headerLine(status, changes, hubJobs), verbatim from the plan:
 *       ('up_to_date', 0, 0) → "Status: up to date"
 *       ('changes', 2, 7)    → "2 changes · Build (7 hub jobs)"
 *       ('changes', 1, 1)    → "1 change · Build (1 hub job)" (singular both ways)
 *       ('changes', 0, 0)    → "Out of date · Build (0 hub jobs)" (plan has steps — an assembly or a fit —
 *                              without a pending change of a piece: still a Build, said as such)
 *       ('failed', 1, null)  → "1 change · a step failed · Build (cost unknown)"
 *       ('building', 2, 7)   → "Status: building · 2 changes";  ('building', 0, 0) → "Status: building"
 * [9] buildButton(f) — rule 2, the disabled reason written under it:
 *       off the pipeline                → disabled "Off the figure pipeline"
 *       no planned step, no run          → label "Build (0 hub jobs)", disabled "Nothing to build"
 *       no planned step, a run goes      → disabled null (a click queues the next one — NOT a disable)
 *       steps costing 7, run or not      → label "Build (7 hub jobs)", disabled null
 *     BUILD_RUNNING_NOTE = "A Build is running — the next one is queued".
 * [10] singleAction(kind, jobs) — rule 3 (one thing, its cost before the click):
 *       ('view', 1) → "Regenerate this view — 1 image job";  ('view', 2) → "… — 2 image jobs"
 *       ('model', 3) → "Regenerate the plain body's mesh — 3 hub jobs";  ('model', null) → "… — cost unknown"
 *       ('face', 1) → "Redo the plain body's face — 1 hub job"
 *     AUTO_BUILD_NOTE = "then Build runs automatically"; staleBaseNote(7) (the skin step's note, the base-skin
 *     review) → "Makes the base model stale — the next Build rebuilds it (7 hub jobs)".
 * [11] wornState(row) / bodyLine — the sketch's state column and Body line:
 *       ready → "✓ ready"; own_mesh interim with 3 jobs → "⏳ mesh · 3 hub jobs" + "shown painted until ready";
 *       failed "mesh — refused" → "failed — mesh — refused"; left_out "no fit yet" → "left out: no fit yet";
 *       in_body pending → "⏳ waiting for the Build" (no line under it: not interim).
 *       bodyLine(all ready, ['hair'], ['Black Blazer']) → 'plain body ✓ · shape "hair" ✓ · texture "Black Blazer" ✓';
 *       (plain older_prompts, shape plain, texture missing, [], ['Blazer'])
 *         → 'plain body: older prompts · no shape (nothing in the body) · texture "Blazer" ⏳'.
 * [12] Source greps: the Wardrobe's "Mesh steps" opens only on a row that is NOT worn on the pipeline (T9
 *      concern 2 — a worn piece's only entry is the Figure tab); FigureBodyDetails writes staleBaseNote
 *      under "Run skin step"; FieldFigure starts nothing but the Build (its POSTs, all through its one
 *      `post()` helper — `apiPost` named twice: import + that call: figure/build, figure/auto-build,
 *      base-body/pipeline, and since Task 11b the other state's single action garments/{item}/run — a
 *      template-literal path, written with its `${…}` as `{}`); the template has tab `figure_tab` {Figure, Figur} with the
 *      humanoid-only section `figure` (special "figure"), and CharactersTab renders the slot `figure`.
 * [13] Task 11 source greps: the Figure tab opens GarmentPieceDialog with `noRunAll`, and the dialog's
 *      "Run all" renders only `!noRunAll` (Ruling 10a: there only Build and Retry start chains); the
 *      Wardrobe's hair row has "Create hair" (POST `/characters/${enc}/hair` with `{}`) and "Wear hair"
 *      (POST …/hair/equipped) — the hair tab they lived in is gone (T9 concern 4).
 *
 * Task 11b — open / closed (spec Addendum A, plan Task 11b "Interfaces", rulings A6/A7):
 * [14] PIECE_STATE_LABELS open → "Open", closed → "Closed"; PIECE_STATES = [closed, open] (the toggle's order).
 *      closableDisabled(['feet']) → "Footwear has no open/closed state"; ['outer'], ['top'], ['legs','feet']
 *      (not feet alone) → null.
 *      stateMeshAction('open', 6) → "Build the open mesh — 6 hub jobs"; ('open', null) → "Build the open mesh —
 *      cost unknown"; ('open', 0) → "Open mesh built"; ('closed', 1) → "Build the closed mesh — 1 hub job";
 *      ('closed', 0) → "Closed mesh built".
 * [15] Source greps: the Wardrobe row renders ClosableCheckbox next to MeshModeSelect and PieceStateToggle only on
 *      an equipped closable row; the Figure tab renders PieceStateToggle on a row with `piece_state` and its
 *      state-mesh button through stateMeshAction; both toggles reach the server only through `setPieceState`
 *      (lib/api.ts: POST `/outfit-options/piece-state` with {item_id, state}); the checkbox PUTs the whole
 *      outfit_piece with `closable`; ItemForm shows "Open / closed: yes — set in a wearer's Wardrobe" and
 *      itemsModel's draftToBody does not send `closable` (like `mesh_mode`).
 */
import { readFileSync } from 'node:fs';
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
  const dir = await mkdtemp(join(tmpdir(), 'check-figure-ui-'));
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

let m;
try {
  m = await loadBundled(join(ROOT, 'frontend/src/tabs/characters/figureModel.ts'));
} catch (e) {
  console.error(`FAIL figureModel.ts not loadable: ${e.message}`);
  process.exit(1);
}

// [1]
check('[1] MESH_MODE_LABELS', m.MESH_MODE_LABELS,
  { own_mesh: 'Own mesh', painted: 'Painted', in_body: 'In the body' });
check('[1] HAIR_MODE_LABELS', m.HAIR_MODE_LABELS,
  { hairdeck: 'HairDeck', haar: 'HAAR', body: 'In the body' });
check('[1] MESH_MODES order', m.MESH_MODES, ['own_mesh', 'painted', 'in_body']);
check('[1] HAIR_MODES order', m.HAIR_MODES, ['hairdeck', 'haar', 'body']);

// [2]
check('[2] haar disabled', m.hairModeDisabled('haar'), 'not built yet');
check('[2] hairdeck selectable', m.hairModeDisabled('hairdeck'), null);
check('[2] body selectable', m.hairModeDisabled('body'), null);

// [3]
check('[3] wearersLine(0, 0)', m.wearersLine(0, 0),
  { text: 'worn by 0 characters now', button: null, reason: 'Nobody wears it now' });
check('[3] wearersLine(2, 7)', m.wearersLine(2, 7),
  { text: 'worn by 2 characters now', button: 'Build for them (7 hub jobs)', reason: null });
check('[3] wearersLine(2, null)', m.wearersLine(2, null),
  { text: 'worn by 2 characters now', button: 'Build for them (cost unknown)', reason: null });
check('[3] wearersLine(1, 1)', m.wearersLine(1, 1),
  { text: 'worn by 1 character now', button: 'Build for them (1 hub job)', reason: null });

// [4]
check('[4] feet', m.defaultMeshMode(['feet']), 'own_mesh');
check('[4] legs+feet', m.defaultMeshMode(['legs', 'feet']), 'painted');
check('[4] outer', m.defaultMeshMode(['outer']), 'in_body');
check('[4] top+bottom', m.defaultMeshMode(['top', 'bottom']), 'in_body');
check('[4] top', m.defaultMeshMode(['top']), 'painted');
check('[4] none', m.defaultMeshMode([]), 'painted');

// [5]
check('[5] stored wins', m.meshModeOf('in_body', ['feet']), 'in_body');
check('[5] empty -> default', m.meshModeOf('', ['feet']), 'own_mesh');
check('[5] unknown -> default', m.meshModeOf('own', ['top']), 'painted');

// [6]
check('[6] figureBuildLine(0, 0)', m.figureBuildLine(0, 0),
  { text: 'No changes', button: null, reason: 'Nothing to build' });
check('[6] figureBuildLine(2, 7)', m.figureBuildLine(2, 7),
  { text: '2 changes', button: 'Build (7 hub jobs)', reason: null });
check('[6] figureBuildLine(1, null)', m.figureBuildLine(1, null),
  { text: '1 change', button: 'Build (cost unknown)', reason: null });
check('[6] figureBuildLine(1, 0)', m.figureBuildLine(1, 0),
  { text: '1 change', button: 'Build (0 hub jobs)', reason: null });

// [7]
const src = (p) => {
  try {
    return readFileSync(join(ROOT, p), 'utf8');
  } catch {
    return ''; // a missing file fails its cases below
  }
};
check('[7] no OwnMeshToggle export',
  /export\s+function\s+OwnMeshToggle\b/.test(src('frontend/src/tabs/characters/WardrobeGarment.tsx')), false);
check('[7] MeshModeSelect exported',
  /export\s+function\s+MeshModeSelect\b/.test(src('frontend/src/tabs/characters/WardrobeGarment.tsx')), true);
check('[7] Items form: no mode checkbox',
  src('frontend/src/tabs/items/ItemForm.tsx').includes("mesh_mode === 'own_mesh'"), false);
const draftToBody = src('frontend/src/tabs/items/itemsModel.ts').split('export function draftToBody')[1] || '';
check('[7] draftToBody sends no mesh_mode', /mesh_mode/.test(draftToBody.split('\nexport ')[0]), false);
check('[7] footwear hint: no flat ×1.50 high claim',
  src('frontend/src/tabs/characters/FootwearSteps.tsx').includes('×1.50 high'), false);

// [8]
check('[8] up to date', m.headerLine('up_to_date', 0, 0), 'Status: up to date');
check('[8] 2 changes', m.headerLine('changes', 2, 7), '2 changes · Build (7 hub jobs)');
check('[8] 1 change', m.headerLine('changes', 1, 1), '1 change · Build (1 hub job)');
check('[8] 0 changes', m.headerLine('changes', 0, 0), 'Out of date · Build (0 hub jobs)');
check('[8] failed', m.headerLine('failed', 1, null), '1 change · a step failed · Build (cost unknown)');
check('[8] building 2', m.headerLine('building', 2, 7), 'Status: building · 2 changes');
check('[8] building 0', m.headerLine('building', 0, 0), 'Status: building');

// [9]
const step = (jobs) => ({ name: 'pieces', label: 'x', jobs, item_id: 'a', failed: '', manual: '' });
const fig = (pipeline, steps, running) => ({
  pipeline, cost: { hub_jobs: steps.reduce((a, s) => a + s.jobs, 0), note: '', steps }, build: { running } });
check('[9] off pipeline', m.buildButton(fig(false, [], false)).disabled, 'Off the figure pipeline');
check('[9] nothing to build', m.buildButton(fig(true, [], false)),
  { label: 'Build (0 hub jobs)', disabled: 'Nothing to build' });
check('[9] running, nothing planned: not disabled', m.buildButton(fig(true, [], true)).disabled, null);
check('[9] 7 jobs', m.buildButton(fig(true, [step(3), step(4)], false)),
  { label: 'Build (7 hub jobs)', disabled: null });
check('[9] 7 jobs while running', m.buildButton(fig(true, [step(7)], true)),
  { label: 'Build (7 hub jobs)', disabled: null });
check('[9] running note', m.BUILD_RUNNING_NOTE, 'A Build is running — the next one is queued');

// [10]
check('[10] view 1', m.singleAction('view', 1), 'Regenerate this view — 1 image job');
check('[10] view 2', m.singleAction('view', 2), 'Regenerate this view — 2 image jobs');
check('[10] model 3', m.singleAction('model', 3), "Regenerate the plain body's mesh — 3 hub jobs");
check('[10] model null', m.singleAction('model', null), "Regenerate the plain body's mesh — cost unknown");
check('[10] face 1', m.singleAction('face', 1), "Redo the plain body's face — 1 hub job");
check('[10] auto note', m.AUTO_BUILD_NOTE, 'then Build runs automatically');
check('[10] skin note', m.staleBaseNote(7), 'Makes the base model stale — the next Build rebuilds it (7 hub jobs)');

// [11]
const row = (o) => ({ state: 'pending', mode: 'painted', jobs: 0, failure: '', left_out: '', note: '',
  interim: false, ...o });
check('[11] ready', m.wornState(row({ state: 'ready' })), { text: '✓ ready', sub: null });
check('[11] interim own mesh', m.wornState(row({ state: 'interim', mode: 'own_mesh', jobs: 3, interim: true })),
  { text: '⏳ mesh · 3 hub jobs', sub: 'shown painted until ready' });
check('[11] failed', m.wornState(row({ state: 'failed', failure: 'mesh — refused' })),
  { text: 'failed — mesh — refused', sub: null });
check('[11] left out', m.wornState(row({ state: 'left_out', left_out: 'no fit yet' })),
  { text: 'left out: no fit yet', sub: null });
check('[11] in body pending', m.wornState(row({ mode: 'in_body' })),
  { text: '⏳ waiting for the Build', sub: null });
const part = (state) => ({ key: 'k', state });
check('[11] body line ready', m.bodyLine({ plain: part('ready'), shape: part('ready'), texture: part('ready') },
  ['hair'], ['Black Blazer']), 'plain body ✓ · shape "hair" ✓ · texture "Black Blazer" ✓');
check('[11] body line mixed', m.bodyLine({ plain: part('older_prompts'), shape: part('plain'),
  texture: part('missing') }, [], ['Blazer']),
  'plain body: older prompts · no shape (nothing in the body) · texture "Blazer" ⏳');

// [12]
const wardrobe = src('frontend/src/tabs/characters/WardrobeTab.tsx');
const meshSteps = wardrobe.split("{t('Mesh steps')}")[0].split('\n').slice(-6).join('\n');
check('[12] Wardrobe: Mesh steps only on rows not worn on the pipeline',
  /garmentStatus && !\(it\.equipped && garments\.pipeline\)/.test(meshSteps), true);
const details = src('frontend/src/tabs/characters/FigureBodyDetails.tsx');
const skin = details.split("t('Run skin step')")[1] || '';
check('[12] skin step: stale-base note under the button', /staleBaseNote\(/.test(skin.slice(0, 600)), true);
const fieldFigure = src('frontend/src/tabs/characters/FieldFigure.tsx');
// Every POST of the tab goes through its one `post(path, …)` helper (one apiPost call).
const posts = [...fieldFigure.matchAll(/\bpost\(\s*['`]([^'`]+)['`]/g)].map((x) => x[1].replace(/\$\{[^}]*\}/g, '{}'));
check('[12] FieldFigure starts only the Build (+ the other state\'s mesh)', [[...new Set(posts)].sort(),
  (fieldFigure.match(/\bapiPost\b/g) || []).length],
  [['base-body/pipeline', 'figure/auto-build', 'figure/build', 'garments/{}/run'], 2]);
const tmpl = JSON.parse(src('shared/templates/character/base-character.json') || '{"tabs":[],"sections":[]}');
const tab = tmpl.tabs.find((x) => x.id === 'figure_tab') || {};
const section = tmpl.sections.find((x) => x.id === 'figure') || {};
check('[12] template tab', [tab.label, tab.label_de, (tab.columns || []).includes(section.column)],
  ['Figure', 'Figur', true]);
check('[12] template section', [section.special, section.visible_when], ['figure', { feature: 'humanoid' }]);
check('[12] CharactersTab slot', /figure:\s*\(?\s*<FieldFigure/.test(src('frontend/src/tabs/characters/CharactersTab.tsx')),
  true);

// [13]
check('[13] Figure tab: piece dialog without Run all', /<GarmentPieceDialog[^>]*\bnoRunAll\b/.test(fieldFigure), true);
const garmentSrc = src('frontend/src/tabs/characters/WardrobeGarment.tsx');
const runAll = garmentSrc.split("label={t('Run all')}")[0].split('\n').slice(-10).join('\n');
check('[13] dialog: Run all only without noRunAll', /info\?\.pipeline && !noRunAll \?/.test(runAll), true);
const hairRow = src('frontend/src/tabs/characters/WardrobeHairRow.tsx');
check('[13] hair row: Create hair posts /hair', [hairRow.includes("t('Create hair')"),
  /call\(`\/characters\/\$\{enc\}\/hair`, \{\}/.test(hairRow)], [true, true]);
check('[13] hair row: Wear hair posts /hair/equipped', [hairRow.includes("t('Wear hair')"),
  hairRow.includes('/hair/equipped`')], [true, true]);

// [14]
check('[14] state labels', m.PIECE_STATE_LABELS, { open: 'Open', closed: 'Closed' });
check('[14] state order', m.PIECE_STATES, ['closed', 'open']);
check('[14] feet', m.closableDisabled(['feet']), 'Footwear has no open/closed state');
check('[14] outer / top / legs+feet', [m.closableDisabled(['outer']), m.closableDisabled(['top']),
  m.closableDisabled(['legs', 'feet'])], [null, null, null]);
check('[14] open 6', m.stateMeshAction('open', 6), 'Build the open mesh — 6 hub jobs');
check('[14] open null', m.stateMeshAction('open', null), 'Build the open mesh — cost unknown');
check('[14] open 0', m.stateMeshAction('open', 0), 'Open mesh built');
check('[14] closed 1', m.stateMeshAction('closed', 1), 'Build the closed mesh — 1 hub job');
check('[14] closed 0', m.stateMeshAction('closed', 0), 'Closed mesh built');

// [15]
const modeRow = wardrobe.split('<MeshModeSelect')[1] || '';
check('[15] Wardrobe: checkbox next to the mode', /^[\s\S]{0,600}<ClosableCheckbox\b/.test(modeRow), true);
check('[15] Wardrobe: toggle only on a worn closable row',
  /it\.equipped && garments\.closable\?\.\[it\.item_id\][^\n]*\n\s*<PieceStateToggle\b/.test(wardrobe), true);
check('[15] Figure tab: toggle on a closable row', /row\.piece_state \? \(\s*<PieceStateToggle\b/.test(fieldFigure), true);
check('[15] Figure tab: state-mesh action', /stateMeshAction\(other, row\.other_state_jobs, t\)/.test(fieldFigure), true);
const toggleSrc = (garmentSrc.split('export function PieceStateToggle')[1] || '').split('\nexport function')[0];
check('[15] toggle posts only through setPieceState', [/setPieceState\(character, itemId, next\)/.test(toggleSrc),
  /\bapi(Post|Put|Get)\b/.test(toggleSrc)], [true, false]);
const apiSrc = src('frontend/src/lib/api.ts');
check('[15] setPieceState route', /setPieceState[\s\S]{0,300}\/outfit-options\/piece-state`, \{ item_id: itemId, state \}/.test(apiSrc),
  true);
const boxSrc = (garmentSrc.split('export function ClosableCheckbox')[1] || '').split('\nexport function')[0];
check('[15] checkbox PUTs the whole outfit_piece', /apiPut\(url, \{ outfit_piece: \{ \.\.\.\(item\.outfit_piece \|\| \{\}\), closable: next \} \}\)/
  .test(boxSrc), true);
check('[15] Items form line', src('frontend/src/tabs/items/ItemForm.tsx')
  .includes(`t("Open / closed: yes — set in a wearer's Wardrobe")`), true);
const toBody = (src('frontend/src/tabs/items/itemsModel.ts').split('body.outfit_piece = {')[1] || '').split('}')[0];
check('[15] draftToBody does not send closable', [toBody.length > 0, /closable/.test(toBody)], [true, false]);

if (failures.length) {
  console.error(`\nFAIL (${failures.length})`);
  for (const f of failures) console.error(`  ${f}`);
  process.exit(1);
}
console.log('\nALL OK');
