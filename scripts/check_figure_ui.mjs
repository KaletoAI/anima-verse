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
 * [2] hairModeDisabled(mode, built): data-driven since H3 — with the server's built list ['hairdeck', 'haar', 'body']
 *     every mode is selectable → null; a mode missing from the list (built ['hairdeck', 'body']) → "not built yet";
 *     the default list is HAIR_MODES (all three).
 * [3] wearersLine(n, hubJobs) — ruling 3, "worn by K characters now" + "Build for them (cost)":
 *       (0, 0)    → text "worn by 0 characters now", button null, reason "Nobody wears it now"
 *       (2, 7)    → text "worn by 2 characters now", button "Build for them (7 hub jobs)", reason null
 *       (2, null) → button "Build for them (cost unknown)" (a wearer's cost is unknown → the total is)
 *       (1, 1)    → singular both ways: "worn by 1 character now", "Build for them (1 hub job)"
 * [4] defaultMeshMode(slots) mirrors `garment_set.default_mesh_mode` (Ruling A10, replaced spec Q2's kind
 *       default): in_body for every slot set, footwear included:
 *       ['feet'] → in_body · ['legs','feet'] → in_body · ['outer'] → in_body ·
 *       ['top','bottom'] → in_body · ['top'] → in_body · [] → in_body
 * [5] meshModeOf(stored, slots): a stored valid mode wins ('painted' on ['outer'] → painted, 'own_mesh' on
 *       ['feet'] → own_mesh); '' or an unknown word → the default (''/['feet'] → in_body, 'own'/['top'] →
 *       in_body).
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
 * [9] buildButton(f) — rule 2, the disabled reason written under it (Task 11h, Ruling A13: every humanoid is
 *     on the pipeline, the "Off the figure pipeline" case is gone with the switch):
 *       no plain body yet (body.plain.state "missing"), steps costing 9 → label "Build base body (9 hub jobs)",
 *                                          disabled null; noBaseBody → true; with plain "ready" → false;
 *       no body block (null)             → noBaseBody false, label "Build (…)";
 *       BUILD_STATUS.off = "No figure — humanoid characters that are not temporary NPCs only";
 *       no planned step, no run          → label "Build (0 hub jobs)", disabled "Nothing to build"
 *       no planned step, a run goes      → disabled null (a click queues the next one — NOT a disable)
 *       steps costing 7, run or not      → label "Build (7 hub jobs)", disabled null
 *     BUILD_RUNNING_NOTE = "A Build is running — the next one is queued".
 * [10] singleAction(kind, jobs) — rule 3 (one thing, its cost before the click):
 *       ('view', 1) → "Regenerate this view — 1 image job";  ('view', 2) → "… — 2 image jobs"
 *       ('model', 3) → "Regenerate the plain body's mesh — 3 hub jobs";  ('model', null) → "… — cost unknown"
 *       ('face', 1) → "Redo the plain body's face — 1 hub job"
 *     AUTO_BUILD_NOTE = "then Build runs automatically"; staleBaseNote(7) (the skin step's note, the base-skin
 *     review) → "Makes the base model stale — the next Build you start rebuilds it (7 hub jobs)" (Task 11h: an
 *     automatic Build never rebuilds the plain body, ruling 8a — was "the next Build rebuilds it").
 *     staleModelText (Task 11h, the Pose and 3D tabs' line under a stale outfit model): 'before_pipeline' →
 *     "Made without the base body — the Figure tab’s Build replaces it"; 'outfit_body' → "Built on an older body
 *     shape — rebuild it"; 'figure' → "Built as another figure than the worn pieces show now — rebuild it";
 *     null / 'older_base' → "Built on an older base body — rebuild it".
 * [11] wornState(row) / bodyLine — the sketch's state column and Body line:
 *       ready → "✓ ready"; own_mesh interim with 3 jobs, in_body_until 'mesh' (ruling A11, task 11c-2: in the
 *       body until its mesh is ready; was "shown painted until ready") → "⏳ mesh · 3 hub jobs" + "in the body
 *       until its own mesh is ready"; own_mesh pending, in_body_until 'build' (its mesh ready, the next Build
 *       takes it out of the shape) → "⏳ waiting for the Build" + "own mesh ready — in the body until the next
 *       Build", building → "⏳ building" + the same line; in_body interim (no in_body_until) → the sub
 *       "not in the 3D figure until its body shape is built" (its shape not built yet; Ruling C4 of Task 11g
 *       fix round 2: nothing is painted in its place any more — was "shown painted until ready");
 *       failed "mesh — refused" → "failed — mesh — refused"; left_out "no fit yet" → "left out: no fit yet";
 *       in_body pending → "⏳ waiting for the Build" (no line under it: not interim).
 *       bodyLine(all ready, ['hair'], ['Black Blazer']) → 'plain body ✓ · shape "hair" ✓ · texture "Black Blazer" ✓';
 *       (plain older_prompts, shape plain, texture missing, [], ['Blazer'])
 *         → 'plain body: older prompts · no shape (nothing in the body) · texture "Blazer" ⏳'.
 * [12] Source greps: the Wardrobe's "Mesh steps" opens only on a row that is NOT worn on the pipeline (T9
 *      concern 2 — a worn piece's only entry is the Figure tab); the Base body tab (FieldBaseBody — was
 *      FigureBodyDetails inside the Figure tab until Task UI1) writes staleBaseNote under "Run skin step"; FieldFigure starts nothing but the Build (its POSTs, all through its one
 *      `post()` helper — `apiPost` named twice: import + that call: figure/build, figure/auto-build,
 *      (base-body/pipeline until Task 11h removed the switch) and since Task 11b the other state's single
 *      action garments/{item}/run (also the refused piece's Regenerate mesh), and since Ruling A23 b the CPU-only
 *      Re-fit figure/refit (Ruling FR-I2: never a hub step) — a
 *      template-literal path, written with its `${…}` as `{}`); the template has tab `figure_tab` {Figure, Figur} with the
 *      humanoid-only section `figure` (special "figure"), and CharactersTab renders the slot `figure`.
 * [13] Task 11 source greps: the Figure tab opens GarmentPieceDialog with `noRunAll`, and the dialog's
 *      "Run all" renders only `!noRunAll` (Ruling 10a: there only Build and Retry start chains; since Task UI1
 *      its label is `runAll.label`, the count from `chainRunAll`). (The Wardrobe hair row's "Create hair" /
 *      "Wear hair" cases went with the row — Task 14, Ruling P3; their successors are case [19].)
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
 * [16] Fix round T12-F1 (rulings F13 a–c), changeLine(change) — a pending change names its cost:
 *       {key 'hair', name 'Hair', note 'in the body → plain body rebuild', jobs 9}
 *         → "Hair · in the body → plain body rebuild, 9 hub jobs" (F13 a)
 *       {key 'j:state', name 'Black Lederjacket', note 'worn open — open mesh missing', jobs 6}
 *         → "Black Lederjacket worn open — open mesh missing (6 hub jobs)" (F13 b: ONE row, the name first)
 *       {key 'j', name 'Shirt', note 'x', jobs 0} → "Shirt: x" (nothing planned: no cost)
 *       {key 'j', name 'Shirt', jobs null} → "Shirt (cost unknown)" · without `jobs` → "Shirt"
 *     hairState({state 'pending', rebuild true, jobs 9, note n}) → text "⏳ plain body rebuild · 9 hub jobs",
 *     sub n; without `rebuild` → "⏳ HairDeck · 9 hub jobs". ESTIMATE_NOTE = "Hub jobs are an estimate —
 *     retries extra" (F13 c) and FieldFigure renders it under the Build button and the changes through
 *     changeLine.
 * [17] Ruling A13b (source greps): FigureBuildButton posts only figure/build and labels itself with
 *       buildButton (the Figure tab's "Build (N jobs)"); BaseBodyOutfitStatus (Pose tab) and FieldModel3D (3D tab)
 *       render it instead of "Rebuild outfit model" / "Rebuild from base body" (no model3d/generate); the
 *       Wardrobe chip has no status.painted branch.
 * [18] Task UI2 (user 2026-11-13: "the tilt dialog is not needed in the Figure tab; make the 3D preview wider")
 *      — source greps: the Figure tab's Model3DViewer has no `sideToolbar` (since Ruling A41 no viewer has Tilt
 *      sliders at all; the drag turns and tilts the figure), height 600; the grid is the class `ga-split-figure` with columns minmax(360px, 1.2fr) minmax(320px, 1fr)
 *      in game-admin.css (at a 1280 px window the right column keeps ~440 px for the header, Build and pieces) and
 *      collapses to one column under 1000 px like every `ga-split-views`.
 *
 * Task 14 — the Hairstyles tab (Rulings P2/P3, the user's rule R1–R4; helpers in figureModel.ts):
 * [19] hairstyleRows(owned, wornId) — the worn hairstyle first, then the server's order; label "<name> · <mode
 *      label>" (HAIR_MODE_LABELS):
 *        owned [a "Short bob" body, b "Long braid" hairdeck, c "Bun" haar], wornId "b"
 *          → ids [b, a, c], labels ["Long braid · HairDeck", "Short bob · In the body", "Bun · HAAR"], worn
 *            [true, false, false];
 *        the same with wornId "" and a stale worn flag on b → ids [a, b, c], worn all false (wornId wins);
 *        a nameless entry {id "hair_x", name ""} → "hair_x · HairDeck".
 *      newHairstyleDisabled(description, mode) — the New hairstyle dialog's Create:
 *        ("", body) → "Describe the hairstyle"; ("   ", hairdeck) → "Describe the hairstyle" (blank = empty);
 *        ("a bun", haar) → null (HAAR is built since H3), ("a bun", haar, built [hairdeck, body]) → "not built yet";
 *        ("a bun", hairdeck) → null; ("a bun", body) → null.
 *      hairstyleActions(mode, run) — R1 Run all only where the flow has more than one step (HairDeck: hairdeck → fit),
 *      R2 single steps with their cost:
 *        (body, any) → runAll / regenerate / refit all null (the Build makes a body hairstyle);
 *        (haar, null) → runAll {"Run all", enabled}, no regenerate / refit (its cases: smoke_haar_variant_rows.mjs);
 *        (hairdeck, null) → runAll {"Run all", enabled} (no estimate: the server decides);
 *        (hairdeck, {steps [], hub_jobs 0}) → {"Everything is current", disabled};
 *        (hairdeck, {steps [hairdeck, fit], hub_jobs 1}) → "Run all: create + fit (1 hub job)";
 *        (hairdeck, {steps [fit], hub_jobs 0}) → "Run all: re-fit (no hub job)";
 *        (hairdeck, {steps [hairdeck, fit], hub_jobs null}) → "Run all: create + fit (cost unknown)";
 *        (hairdeck, {refit true, steps [hairdeck, fit]}) → "Run all (refit on the CPU)";
 *        regenerate "Regenerate hair (HairDeck) — 1 hub job", refit "Re-fit — no hub job" (HUB_JOBS hair:hairdeck
 *        = {hairdeck 1, fit 0} in app/core/garments.py).
 *      Source greps: the Wardrobe has no hair row (WardrobeHairRow.tsx gone, WardrobeTab names neither it nor a
 *      `/hair` route) but its saved-outfit panel renders OutfitHairstyleSelect, which posts
 *      `/outfit-sets/{id}/hairstyle` (D5); CharactersTab lists `hairstyles` directly after the Wardrobe entry in
 *      the order that places it (`afterAussehen`), gates it on the template feature `humanoid` and renders
 *      FieldHairstyles; FieldHairstyles' dialog is a createPortal to document.body, "New hairstyle" posts
 *      `/hairstyles`, Wear posts `/hairstyles/{id}/wear`, the detail reads `/hair?item_id=`; R3 — the placement,
 *      colour and Swing saves (HairLiveControls, one `post(path, body)` adding `item_id`) start no garment run; FieldFigure's hair row shows
 *      `hair.name` and links to the Hairstyles tab.
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
check('[2] haar selectable', [m.hairModeDisabled('haar'), m.hairModeDisabled('haar', ['hairdeck', 'haar', 'body'])],
  [null, null]);
check('[2] not in the built list', m.hairModeDisabled('haar', ['hairdeck', 'body']), 'not built yet');
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
check('[4] feet', m.defaultMeshMode(['feet']), 'in_body');
check('[4] legs+feet', m.defaultMeshMode(['legs', 'feet']), 'in_body');
check('[4] outer', m.defaultMeshMode(['outer']), 'in_body');
check('[4] top+bottom', m.defaultMeshMode(['top', 'bottom']), 'in_body');
check('[4] top', m.defaultMeshMode(['top']), 'in_body');
check('[4] none', m.defaultMeshMode([]), 'in_body');

// [5]
check('[5] stored wins (painted)', m.meshModeOf('painted', ['outer']), 'painted');
check('[5] stored wins (own_mesh)', m.meshModeOf('own_mesh', ['feet']), 'own_mesh');
check('[5] empty -> default', m.meshModeOf('', ['feet']), 'in_body');
check('[5] unknown -> default', m.meshModeOf('own', ['top']), 'in_body');

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
const fig = (plain, steps, running) => ({
  body: plain === null ? null : { plain: { key: 'b', state: plain }, shape: { key: '', state: 'plain' },
    texture: { key: '', state: 'none' } },
  cost: { hub_jobs: steps.reduce((a, s) => a + s.jobs, 0), note: '', steps }, build: { running } });
check('[9] no base body', m.buildButton(fig('missing', [step(4), step(5)], false)),
  { label: 'Build base body (9 hub jobs)', disabled: null });
check('[9] noBaseBody', [m.noBaseBody(fig('missing', [], false)), m.noBaseBody(fig('ready', [], false)),
  m.noBaseBody(fig(null, [], false))], [true, false, false]);
check('[9] no body block', m.buildButton(fig(null, [step(2)], false)).label, 'Build (2 hub jobs)');
check('[9] off status', m.BUILD_STATUS.off, 'No figure — humanoid characters that are not temporary NPCs only');
check('[9] nothing to build', m.buildButton(fig('ready', [], false)),
  { label: 'Build (0 hub jobs)', disabled: 'Nothing to build' });
check('[9] running, nothing planned: not disabled', m.buildButton(fig('ready', [], true)).disabled, null);
check('[9] 7 jobs', m.buildButton(fig('ready', [step(3), step(4)], false)),
  { label: 'Build (7 hub jobs)', disabled: null });
check('[9] 7 jobs while running', m.buildButton(fig('ready', [step(7)], true)),
  { label: 'Build (7 hub jobs)', disabled: null });
check('[9] running note', m.BUILD_RUNNING_NOTE, 'A Build is running — the next one is queued');

// [10]
check('[10] view 1', m.singleAction('view', 1), 'Regenerate this view — 1 image job');
check('[10] view 2', m.singleAction('view', 2), 'Regenerate this view — 2 image jobs');
check('[10] model 3', m.singleAction('model', 3), "Regenerate the plain body's mesh — 3 hub jobs");
check('[10] model null', m.singleAction('model', null), "Regenerate the plain body's mesh — cost unknown");
check('[10] face 1', m.singleAction('face', 1), "Redo the plain body's face — 1 hub job");
check('[10] auto note', m.AUTO_BUILD_NOTE, 'then Build runs automatically');
check('[10] skin note', m.staleBaseNote(7), 'Makes the base model stale — the next Build you start rebuilds it (7 hub jobs)');
check('[10] stale model texts', ['before_pipeline', 'outfit_body', 'figure', null, 'older_base'].map((r) => m.staleModelText(r)), [
  'Made without the base body — the Figure tab’s Build replaces it', 'Built on an older body shape — rebuild it',
  'Built as another figure than the worn pieces show now — rebuild it', 'Built on an older base body — rebuild it',
  'Built on an older base body — rebuild it']);

// [11]
const row = (o) => ({ state: 'pending', mode: 'painted', jobs: 0, failure: '', left_out: '', note: '',
  interim: false, ...o });
check('[11] ready', m.wornState(row({ state: 'ready' })), { text: '✓ ready', sub: null });
check('[11] interim own mesh', m.wornState(row({ state: 'interim', mode: 'own_mesh', jobs: 3, interim: true,
  in_body_until: 'mesh' })), { text: '⏳ mesh · 3 hub jobs', sub: 'in the body until its own mesh is ready' });
check('[11] own mesh ready, in the body until the Build', m.wornState(row({ mode: 'own_mesh', in_body_until: 'build' })),
  { text: '⏳ waiting for the Build', sub: 'own mesh ready — in the body until the next Build' });
check('[11] ... while the Build runs', m.wornState(row({ state: 'building', mode: 'own_mesh', in_body_until: 'build' })),
  { text: '⏳ building', sub: 'own mesh ready — in the body until the next Build' });
check('[11] in_body interim keeps its line', m.wornState(row({ state: 'interim', mode: 'in_body', interim: true })).sub,
  'not in the 3D figure until its body shape is built');
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
const details = src('frontend/src/tabs/characters/FieldBaseBody.tsx');
const skin = details.split("t('Run skin step')")[1] || '';
check('[12] skin step: stale-base note under the button', /staleBaseNote\(/.test(skin.slice(0, 600)), true);
const fieldFigure = src('frontend/src/tabs/characters/FieldFigure.tsx');
// Every POST of the tab goes through its one `post(path, …)` helper (one apiPost call).
const posts = [...fieldFigure.matchAll(/\bpost\(\s*['`]([^'`]+)['`]/g)].map((x) => x[1].replace(/\$\{[^}]*\}/g, '{}'));
check('[12] FieldFigure starts only the Build (+ the other state\'s mesh, the CPU Re-fit)', [[...new Set(posts)].sort(),
  (fieldFigure.match(/\bapiPost\b/g) || []).length],
  [['figure/auto-build', 'figure/build', 'figure/refit', 'garments/{}/run'], 2]);
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
const runAll = garmentSrc.split('label={runAll.label}')[0].split('\n').slice(-10).join('\n');
check('[13] dialog: Run all only without noRunAll', /info\?\.pipeline && !noRunAll \?/.test(runAll), true);

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

// [16] fix round T12-F1
check('[16] hair rebuild', m.changeLine({ key: 'hair', name: 'Hair', wanted: 'body', delivered: 'hairdeck',
  note: 'in the body → plain body rebuild', jobs: 9 }), 'Hair · in the body → plain body rebuild, 9 hub jobs');
check('[16] open mesh missing', m.changeLine({ key: 'j:state', name: 'Black Lederjacket', wanted: 'open',
  delivered: 'closed', note: 'worn open — open mesh missing', jobs: 6 }),
  'Black Lederjacket worn open — open mesh missing (6 hub jobs)');
check('[16] nothing planned', m.changeLine({ key: 'j', name: 'Shirt', wanted: 'own', delivered: 'painted',
  note: 'x', jobs: 0 }), 'Shirt: x');
check('[16] unknown', m.changeLine({ key: 'j', name: 'Shirt', wanted: 'own', delivered: 'painted', jobs: null }),
  'Shirt (cost unknown)');
check('[16] no jobs field', m.changeLine({ key: 'j', name: 'Shirt', wanted: 'own', delivered: 'painted' }), 'Shirt');
check('[16] hair state rebuild', m.hairState({ mode: 'body', state: 'pending', note: 'n', jobs: 9, rebuild: true }),
  { text: '⏳ plain body rebuild · 9 hub jobs', sub: 'n' });
check('[16] hair state HairDeck', m.hairState({ mode: 'hairdeck', state: 'pending', note: '', jobs: 9 }).text,
  '⏳ HairDeck · 9 hub jobs');
check('[16] estimate note', m.ESTIMATE_NOTE, 'Hub jobs are an estimate — retries extra');
check('[16] FieldFigure uses them', [/t\(ESTIMATE_NOTE\)/.test(fieldFigure),
  /data\.changes\.map\(\(c\) => changeLine\(c, t\)\)/.test(fieldFigure)], [true, true]);

// [17] Ruling A13b: the Pose tab's and the 3D tab's rebuild buttons are the Figure tab's Build.
const fbb = src('frontend/src/tabs/characters/FigureBuildButton.tsx');
const bbos = src('frontend/src/tabs/characters/BaseBodyOutfitStatus.tsx');
const fm3 = src('frontend/src/tabs/characters/FieldModel3D.tsx');
check('[17] FigureBuildButton posts only figure/build, labelled by buildButton',
  [[...fbb.matchAll(/apiPost[^(]*\(`\/characters\/\$\{enc\}\/([^`?]+)/g)].map((x) => x[1]),
    /buildButton\(data, t\)/.test(fbb)], [['figure/build'], true]);
check('[17] Pose tab: the Build, no model3d/generate', [/<FigureBuildButton/.test(bbos), /model3d\/generate/.test(bbos),
  /Rebuild outfit model/.test(bbos)], [true, false, false]);
check('[17] 3D tab: the Build instead of "Rebuild from base body"', [/<FigureBuildButton/.test(fm3),
  /rebuildFromBase|Rebuild from base body'/.test(fm3)], [true, false]);
check('[17] Wardrobe: no painted status branch', /status\.painted/.test(src('frontend/src/tabs/characters/WardrobeGarment.tsx')),
  false);

// [18] Task UI2: the Figure tab's preview — no tilt toolbar, wider and taller.
const figureViewer = (fieldFigure.match(/<Model3DViewer[^>]*\/>/) || [''])[0];
check('[18] Figure preview without the side toolbar, height 600',
  [/sideToolbar/.test(figureViewer), /height=\{600\}/.test(figureViewer)], [false, true]);
check('[18] Figure grid by class, no inline columns',
  [/className="ga-split ga-split-views ga-split-figure"/.test(fieldFigure), /gridTemplateColumns/.test(fieldFigure)],
  [true, false]);
const adminCss = src('frontend/src/styles/game-admin.css');
check('[18] its columns', /\.ga-split-views\.ga-split-figure \{ grid-template-columns: minmax\(360px, 1\.2fr\) minmax\(320px, 1fr\); \}/
  .test(adminCss), true);
check('[18] one column when narrow',
  /@media \(max-width: 1000px\) \{\s*\.ga-split-views, \.ga-split-views\.ga-split-figure \{ grid-template-columns: minmax\(0, 1fr\); \}/
    .test(adminCss), true);

// [19] Task 14: the Hairstyles tab.
const hs = (id, name, mode, worn = false) => ({ id, name, description: '', mode, worn, plain: false, freshness: null });
const owned = [hs('a', 'Short bob', 'body'), hs('b', 'Long braid', 'hairdeck', true), hs('c', 'Bun', 'haar')];
const worn = m.hairstyleRows(owned, 'b');
check('[19] worn first', worn.map((h) => h.id), ['b', 'a', 'c']);
check('[19] labels', worn.map((h) => h.label), ['Long braid · HairDeck', 'Short bob · In the body', 'Bun · HAAR']);
check('[19] worn flags', worn.map((h) => h.worn), [true, false, false]);
const none = m.hairstyleRows(owned, '');
check('[19] none worn: server order, stale flag ignored', [none.map((h) => h.id), none.map((h) => h.worn)],
  [['a', 'b', 'c'], [false, false, false]]);
check('[19] nameless', m.hairstyleRows([hs('hair_x', '', 'hairdeck')], '')[0].label, 'hair_x · HairDeck');
check('[19] dialog: empty', m.newHairstyleDisabled('', 'body'), 'Describe the hairstyle');
check('[19] dialog: blank', m.newHairstyleDisabled('   ', 'hairdeck'), 'Describe the hairstyle');
check('[19] dialog: HAAR', [m.newHairstyleDisabled('a bun', 'haar'),
  m.newHairstyleDisabled('a bun', 'haar', ['hairdeck', 'body'])], [null, 'not built yet']);
check('[19] dialog: ok', [m.newHairstyleDisabled('a bun', 'hairdeck'), m.newHairstyleDisabled('a bun', 'body')],
  [null, null]);
const nothing = { runAll: null, regenerate: null, refit: null };
check('[19] body: no run of its own', m.hairstyleActions('body', { steps: [], hub_jobs: 0, note: '', refit: false }),
  nothing);
check('[19] haar: Run all', m.hairstyleActions('haar', null),
  { runAll: { label: 'Run all', disabled: false }, regenerate: null, refit: null });
const run = (steps, hubJobs, refit = false) => ({ steps, hub_jobs: hubJobs, note: '', refit });
check('[19] no estimate', m.hairstyleActions('hairdeck', null).runAll, { label: 'Run all', disabled: false });
check('[19] current', m.hairstyleActions('hairdeck', run([], 0)).runAll,
  { label: 'Everything is current', disabled: true });
check('[19] create + fit', m.hairstyleActions('hairdeck', run(['hairdeck', 'fit'], 1)).runAll,
  { label: 'Run all: create + fit (1 hub job)', disabled: false });
check('[19] re-fit only', m.hairstyleActions('hairdeck', run(['fit'], 0)).runAll,
  { label: 'Run all: re-fit (no hub job)', disabled: false });
check('[19] cost unknown', m.hairstyleActions('hairdeck', run(['hairdeck', 'fit'], null)).runAll.label,
  'Run all: create + fit (cost unknown)');
check('[19] refit on the CPU', m.hairstyleActions('hairdeck', run(['hairdeck', 'fit'], 0, true)).runAll.label,
  'Run all (refit on the CPU)');
const single = m.hairstyleActions('hairdeck', run([], 0));
check('[19] single steps', [single.regenerate, single.refit],
  ['Regenerate hair (HairDeck) — 1 hub job', 'Re-fit — no hub job']);
check('[19] Wardrobe: no hair row', [src('frontend/src/tabs/characters/WardrobeHairRow.tsx'),
  /WardrobeHairRow|\/hair[`/]/.test(wardrobe)], ['', false]);
check('[19] Wardrobe: set editor hairstyle select posts the set route', [/<OutfitHairstyleSelect\b/.test(wardrobe),
  /\/outfit-sets\/\$\{encodeURIComponent\(outfitId\)\}\/hairstyle`/.test(wardrobe)], [true, true]);
const charactersTab = src('frontend/src/tabs/characters/CharactersTab.tsx');
const afterAussehen = (charactersTab.split('const afterAussehen')[1] || '').split('].filter')[0];
check('[19] tab sits directly after the Wardrobe',
  /\{ id: 'wardrobe', label: 'Wardrobe' \}\]\),\s*\{ id: 'hairstyles', label: 'Hairstyles' \},/.test(afterAussehen), true);
check('[19] tab gated on humanoid, renders FieldHairstyles', [/hairstyles: 'humanoid'/.test(charactersTab),
  /subTab === 'hairstyles' \? \(\s*<FieldHairstyles/.test(charactersTab)], [true, true]);
const tabSrc = src('frontend/src/tabs/characters/FieldHairstyles.tsx');
check('[19] dialog through createPortal', /return createPortal\([\s\S]*?document\.body,\s*\)/.test(tabSrc), true);
check('[19] routes', [tabSrc.includes('`/characters/${encodeURIComponent(character)}/hairstyles`'),
  tabSrc.includes('/hairstyles/${encodeURIComponent(id)}/wear`'),
  tabSrc.includes('/hair?item_id=${encodeURIComponent(itemId)}`')], [true, true, true]);
const liveSrc = src('frontend/src/tabs/characters/HairLiveControls.tsx');
check('[19] R3: placement, colour and Swing saved with item_id, no run', [
  /apiPost\(`\/characters\/\$\{enc\}\/hair\/\$\{path\}`, \{ \.\.\.body, item_id: itemId \}\)/.test(liveSrc),
  /post\('placement', \{ forward_m: /.test(liveSrc), /post\('colour', \{ hex: /.test(liveSrc),
  /post\('motion', \{ swing: e\.target\.checked, stiffness: /.test(liveSrc), /garments\//.test(liveSrc)],
  [true, true, true, true, false]);
check('[19] Figure tab hair row: name + mode, link to Hairstyles', [/\{hair\.name \|\| t\('Hair'\)\}/.test(fieldFigure),
  /<td style=\{CELL\}>\{hairstyles\}<\/td>/.test(fieldFigure)], [true, true]);

if (failures.length) {
  console.error(`\nFAIL (${failures.length})`);
  for (const f of failures) console.error(`  ${f}`);
  process.exit(1);
}
console.log('\nALL OK');
