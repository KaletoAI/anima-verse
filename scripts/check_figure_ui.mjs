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
 * [8] headerLine(status, changes) — the flow head's words beside its light (Task UI5: the Build button beside it
 *     names the cost, so the line no longer repeats "Build (N hub jobs)"):
 *       ('up_to_date', 0) → "Up to date"
 *       ('changes', 2)    → "2 changes";  ('changes', 1) → "1 change" (singular)
 *       ('changes', 0)    → "Out of date" (plan has steps — an assembly or a fit — without a pending change of a
 *                           piece: still due, said as such)
 *       ('failed', 1)     → "1 change · a step failed"
 *       ('building', 2)   → "Building now · 2 changes";  ('building', 0) → "Building now"
 *     statusLight: up_to_date green · changes yellow · failed red · building blue.
 * [9] buildButton(f) — rule 2, the disabled reason written under it (Task 11h, Ruling A13: every humanoid is
 *     on the pipeline, the "Off the figure pipeline" case is gone with the switch):
 *       no plain body yet (body.plain.state "missing"), steps costing 9 → label "Build base body (9 hub jobs)",
 *                                          disabled null; noBaseBody → true; with plain "ready" → false;
 *       no body block (null)             → noBaseBody false, label "Build (…)";
 *       BUILD_STATUS.off = "No figure — humanoid characters that are not temporary NPCs only";
 *       no planned step, no run          → label "Everything is current", disabled "Everything is current"
 *                                          (checklist 1, Task UI5; the tab writes no reason equal to the label)
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
 *     staleModelText (Task 11h, the Figure tab's Outfit model and the 3D tab's line under a stale outfit model): 'before_pipeline' →
 *     "Made without the base body — the Figure tab’s Build replaces it"; 'outfit_body' → "Built on an older body
 *     shape — rebuild it"; 'figure' → "Built as another figure than the worn pieces show now — rebuild it";
 *     null / 'older_base' → "Built on an older base body — rebuild it".
 * [11] wornState(row) — a worn row as a step (Task UI5: a light instead of the ✓ / ⏳ glyphs, the state short, the
 *       reason under it, the refusal's guidance on mouse-over):
 *       ready → {green, "Ready", no line}; own_mesh pending with 3 jobs → {yellow, "Due: own mesh · 3 hub jobs",
 *       no line}; Ruling A119 left_out "Body shape not built" (an in-body piece on the plain body) → {grey, "Left
 *       out", "Body shape not built"}; failed "mesh — refused" → {red, "Failed", "mesh — refused"}; left_out "no fit
 *       yet" → {grey, "Left out", "no fit yet"}; in_body pending → {yellow, "Waits for the Build", no line};
 *       fit_refused "sole sinks" on "T-shirt" with detail "d" → {red, "Refused on the body shape", "Fits the plain
 *       body — refused on the body shape (T-shirt): sole sinks", mouse-over FIT_REFUSED_NOTE + "\n" + "d"}.
 *       bodyRows(all ready, ['hair'], ['Black Blazer']) → plain {green, "Current"}, shape {green, "Current",
 *       "In the body: hair"}, texture {green, "Current", "Painted: Black Blazer"};
 *       (plain older_prompts, shape plain, texture missing, [], ['Blazer']) → plain {yellow, "Outdated"}, shape
 *       {grey, "Not needed", "Nothing is worn in the body"}, texture {yellow, "Due", "Painted: Blazer — the Build
 *       paints it"}; plain missing → {yellow, "None yet"}.
 * [12] Source greps: the Wardrobe's "Mesh steps" opens only on a row that is NOT worn on the pipeline (T9
 *      concern 2 — a worn piece's only entry is the Figure tab); the Base body tab (FieldBaseBody — was
 *      FigureBodyDetails inside the Figure tab until Task UI1) writes staleBaseNote on "Run skin step" (SkinStepLine, its mouse-over since Ruling A90); FieldFigure starts nothing but the Build (its POSTs, all through its one
 *      `post()` helper — `apiPost` named twice: import + that call: figure/build, figure/auto-build,
 *      (base-body/pipeline until Task 11h removed the switch) and since Task 11b the other state's single
 *      action garments/{item}/run (also the refused piece's Regenerate mesh), and since Ruling A23 b the CPU-only
 *      Re-fit figure/refit (Ruling FR-I2: never a hub step), and since Ruling A86 the front's Regenerate
 *      base-body/images on the plain body's change (the Base body tab's front tile's action) — a
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
 *     hairState({state 'pending', rebuild true, jobs 9, note n}) → {yellow, "Due: plain body rebuild · 9 hub
 *     jobs", n}; without `rebuild` → "Due: HairDeck · 9 hub jobs", mode haar → "Due: HAAR · 9 hub jobs" (the mode
 *     named, Task UI5); ready → {green, "Ready"}. ESTIMATE_NOTE = "Hub jobs are an estimate — retries extra"
 *     (F13 c) and FieldFigure puts it on the Build button (its mouse-over) and the changes through changeLine.
 * [17] Ruling A13b (source greps): FigureBuildButton posts only figure/build and labels itself with
 *       buildButton (the Figure tab's "Build (N jobs)"); FieldModel3D (3D tab) renders it instead of
 *       "Rebuild from base body" (no model3d/generate; the Pose tab that did too dissolved, Ruling A70); the
 *       Wardrobe chip has no status.painted branch.
 * [18] Task UI2 (user 2026-11-13: "the tilt dialog is not needed in the Figure tab; make the 3D preview wider")
 *      — source greps: the Figure tab's Model3DViewer has no `sideToolbar` (since Ruling A41 no viewer has Tilt
 *      sliders at all; the drag turns and tilts the figure), height 600; the grid is the class `ga-split-figure` with columns minmax(360px, 1.2fr) minmax(320px, 1fr)
 *      in game-admin.css (at a 1280 px window the right column keeps ~440 px for the header, Build and pieces) and
 *      collapses to one column under 1000 px like every `ga-split-views`. Ruling A73 (user: "Im Figur-Tab
 *      3D-Vorschau den Text raus"): the Figure viewer writes no extension-bone note — its Model3DViewer has no
 *      `extensionNote`, FieldFigure names no ExtensionPresenceNote. Ruling A78 (user: "remove this text from all 3D
 *      previews"): the 3D tab names neither either, and Model3DViewer.tsx takes no `extensionNote` at all.
 *      (Source greps only: the viewer renders its toggle column after the model has loaded.)
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
 * [20] Ruling A42 — "Pause automatic generation" (GenerationPausePanel):
 *      pauseLine: not paused → "Automatic generation on"; paused with 2 waiting → "Automatic generation paused —
 *        2 jobs held"; with 1 → "… — 1 job held" (singular).
 *      resumeLabel: nothing waits → "Resume — nothing waits"; resume_jobs 7, unknown 0 → "Resume — 7 hub jobs
 *        start"; 1, 0 → "Resume — 1 hub job starts"; 3, 1 → "Resume — 3 hub jobs start (+1 job of unknown cost)";
 *        3, 2 → "… (+2 jobs of unknown cost)".
 *      waitingLine({label "Wardrobe · Blazer", detail "worn 2 + mesh 1", jobs 3}) → "Waiting: Wardrobe · Blazer ·
 *        worn 2 + mesh 1 — 3 hub jobs"; detail "" and jobs null → "Waiting: Build (automatic) — cost unknown"; jobs 0
 *        → "… — no hub job".
 *      Source greps: the panel's Cancel opens ConfirmDialog (no native dialog); FieldFigure posts
 *      `figure/generation-pause` and `figure/waiting/cancel`; useFigure re-reads on the topic `generation`.
 * [21] Task UI5 — the Figure tab follows the tab checklist:
 *      planRows: steps [{pieces "Own mesh · Blazer", 3}, {fits, 0}, {texture, null}] while nothing runs →
 *        [yellow "3 hub jobs", yellow "no hub job", yellow "cost unknown"]; a step with failed "x" → red, its reason
 *        "Failed: x"; a step with manual "m" → reason "m"; the step in flight (build.running, step {pieces, item a})
 *        → blue.
 *      stateToggleNote (beside Closed / Open, checklist 2 and 9): auto off → "Saved at once — nothing runs; the
 *        change waits for Build"; auto on, own mesh with other_state_jobs 6 → "Switching starts the Build — 6 hub
 *        jobs for that mesh", 1 → "… — 1 hub job for that mesh", 0 → "Switching starts the Build — no hub job (that
 *        mesh is built)"; auto on, in_body (other_state_jobs null) → "Switching starts the Build — cost unknown".
 *      autoBuildNote(true) → "Saved — changes start the Build by themselves"; (false) → "Saved — changes wait for
 *        Build". retryLabel(3) → "Retry — 3 hub jobs", (null) → "Retry — cost unknown"; REFIT_LABEL = "Re-fit — no
 *        hub job".
 *      Source greps: FieldFigure draws its rows with StepRowView, its panel with SubTabs (Worn now · Build plan ·
 *      Body), the viewer with `builtAt`; neither it nor figureModel writes a ✓ or ⏳ glyph any more.
 * [23] Ruling A61 — a failed Build step says itself (checklist point 8), problemText(p):
 *      {kind mesh_mismatch, step_label "Assemble the figure", view back, body plain, jobs 3}
 *        → title "Assemble the figure failed — Back view", the reason names "its own back view" and says
 *          re-rendering does not help, action "Make the base mesh again — 3 hub jobs", note MESH_HELD_NOTE;
 *        body shape, jobs 1 → action "Make the body shape mesh again — 1 hub job";
 *      {kind failed, step_label "Texture", view "", detail "boom", jobs null, held true}
 *        → title "Texture failed", reason FAILED_PLAIN (the message "boom" only on mouse-over: it is the worker's
 *          English), action "Retry this step — cost unknown", note HELD_NOTE; at the back view, held false, jobs 0
 *        → reason "The step stopped at the back view — the message is on mouse-over.", note "", action "Retry
 *          this step — no hub job".
 *      Source greps: the 3D tab renders BuildProblemNote, the Figure and Base body tabs BuildProblemView.
 *
 * [24] Ruling A67 — the piece dialog's body switch offers the base body and the current body only (the server's list:
 *      scripts/smoke_dialog_two_bodies.py). Pure helpers: fitBodyName({role 'base'}) → "Base body", {role 'current'}
 *      → "Current body"; fitBodyLongName of the current body labelled "Body shape (Blouse, Jeans)" → "Current body
 *      (Blouse, Jeans)", of one labelled "Body shape ob0000000b" → "Current body", of the base → "Base body".
 *      defaultBodyKey([plain, B, B-derived]) → B (the current body, never its derived shoe); ([plain]) → "plain";
 *      ([]) → "plain". showBodySwitch([plain accepted, B]) → true; ([plain accepted]) → false (current == base: no
 *      selector); ([plain refused]) → true (its verdict and Accept stay).
 *      Rendered (react-dom/server, en, FitBodySwitch): the TWO-body payload of a figure with three stored shapes
 *      ([plain accepted, B refused], B selected) → one role="group" with exactly two buttons, "Base body" and
 *      "Current body", each with its light (a 10 px round span: green #3fb950 for the base, red #f85149 for B); the
 *      verdict lines "Base body: accepted" and "▸ Current body (Blouse, Jeans): refused — x"; "Re-fit on this body
 *      (0 hub jobs)" present; no "Plain body", no "Body shape" in the shown text (the current body's hover names its
 *      shape). The ONE-body payload ([plain accepted]) → no
 *      role="group", no button. The current body not built (refit_block = the server's CURRENT_NOT_BUILT) → no Re-fit
 *      button, the reason shown instead.
 *      Sources: WardrobeGarment opens on defaultBodyKey (useState<string | null>(null), `bodyKey ?? defaultBodyKey`)
 *      and its Re-fit posts the selected body (`{ ...run, body: refitBody }` and `onRun({ step: 'fit', force: true,
 *      body: b }`); FootwearSteps names its rows "Base body" / "Current body", never `Body shape {id}`; the de.json
 *      keys of the new strings exist and "The figure stands on this body now" is gone.
 * [25] Ruling A69 — a result its checks refused, accepted by the user, reads green with what and why:
 *      wornState(ready, accepted_by_user {step fit, on "Plain body", reason "deep_push_share 0.1512 > 0.12"})
 *        → {green, "Ready — Accepted by you", "Plain body: its checks refused it — deep_push_share 0.1512 > 0.12"}
 *          (Ruling A31's words; a row without `step` reads the same — an older server);
 *      {step mesh, on "", reason "largest component 0.82 < 0.9"} → sub "Mesh: its gate refused it — largest
 *        component 0.82 < 0.9";
 *      {step ghost, view back, reason "piece_share 0.02 < 0.03"} → "Piece-only views · Back view: its gate refused
 *        it — piece_share 0.02 < 0.03"; {step worn, view front, reason ""} → "Worn views · Front view: its gate
 *        refused it"; acceptedWhat({step fit, on "", reason r}) (the Wardrobe chip's fit) → "Fit: its checks
 *        refused it — r".
 *      Source greps: the Wardrobe chip adds ACCEPTED_BY_YOU on a fitted piece with `accepted_by_user`; the step
 *      grid's fit row shows "Accepted by you" for `fit.user_accepted` (not under a selected body shape).
 * [26] Ruling A70 — the Pose tab dissolves into the Figure tab's "Dressed views" and "Outfit model" sub-tabs:
 *      dressedViewsModel (the Pose tab's poseModel, folded from check_pose_ui): viewRow — running → blue
 *        "Rendering"; nothing stored → yellow "Not rendered yet"; current → green "Current"; the draft stale {R, A}
 *        → yellow "Outdated", "R", mouse-over "R\nA"; view stale V + draft stale D → "V" first; warning W → yellow
 *        "Kept with a warning", "W"; stale V + warning W → mouse-over "V\nW"; stale without reason → "Made from older
 *        data". outfitRow — running → blue "Building now" (warnings hidden); failed boom → red "Failed"; stale →
 *        yellow "Outdated", staleText; missing → yellow "Not built yet", "The Build makes it"; ready → green "Ready",
 *        the proof line; ready + [w1, w2] → yellow "Ready — with warnings", "w1", "w1\nw2". renderAllLabel 0 / 2 /
 *        -1 → 1 / 3 / 1 image jobs. viewAction (what a view's button does, server base_body.dressed_view_source):
 *        painted or unknown → "Regenerate this view — 1 image job", 1 job, no note; shape → "Copy this view again
 *        from the body shape — no job", 0, SHAPE_COPY_NOTE; plain → "… from the plain body — no job", 0,
 *        PLAIN_COPY_NOTE. VIEWS_BY_BUILD = "The Build above renders these views and builds the outfit model from them."
 *      No Pose tab: base-character.json has neither `tpose_tab` nor `model_refs`; CharactersTab has no model_refs slot
 *      and no FieldPose; FieldPose.tsx and poseModel.ts are gone. Its links: no quoted "Pose tab" string is left in
 *      frontend/src, player-ui or app; the occasions outfit_front / outfit_back_draft / outfit_side_draft read
 *      "Figure tab, Dressed views: …"; FieldFigure has the sub-tabs `views` and `model`, renders FieldModelRefs
 *      steps with onOpenBaseBody and onOpenBody (= setSub('body')), the VIEWS_BY_BUILD line and FigureOutfitModel.
 *      A view's button posts generateBody(view, …): generateBody('back' | 'main', [tpose], pipeline) → exactly
 *      {kinds [tpose], view}; no view on the pipeline with Auto off → {kinds [tpose]}; off it → {kinds []}. The 3D
 *      tab's "Pose render" sub-tab (off the pipeline only — `poseRender`; a chosen Pose render whose character went onto
 *      the pipeline falls back to Steps) renders FieldModelRefs steps.
 *      Rendered from fixtures (react-dom/server): Main + Back on the pipeline —
 *        (Ruling A90: the views are ONE row of tiles, where they come from ONE chip over the row with ONE link,
 *        each button's whole label on its mouse-over, a one-line note's whole text there too)
 *        shape copy (ob0a1b2c3d, 0 jobs): the tiles "Front view" 1 and "Back view" 1, the copy
 *          label 2 (the buttons' mouse-over), no "Regenerate this view", "Copy of the body shape’s view — nothing
 *          painted" 1, a ↗ Body button 1, the face view note 2 (its text + its mouse-over);
 *        painted: "Regenerate this view — 1 image job" 2, "Painted on the body shape’s view" 1, no "no job";
 *        plain copy (base1234abcd): the plain copy label 2, ↗ Base body 2 (the chip + the face view note);
 *        off the pipeline (main + the enabled left view, not rendered): Regenerate 2, "Render all views — 2 image
 *          jobs" 1, Auto 1, no "nothing painted";
 *      OutfitModelRows ready with texels 0.92 / 0.031: "Outfit model (base body)", "Ready", the reason "Garment
 *        coverage of the visible surface: 92.0 % · Garment filled in without a view: 3.1 %", one step → no "No
 *        model steps recorded"; FieldFigure (fixture payload) opened on `views`: the tab labels "Dressed views" and "Outfit
 *        model", the Build line, "Worn now (…)" tab once; opened on `model`: the outfit row with "92.0 %".
 * [27] Ruling A75 — servedLines(served_state, t), the viewer's status of the figure it shows:
 *      null → []; green {state "Shows the outfit worn now", reason ""} → one head line, light green, text the state
 *      alone, title "";
 *      red {state "Not the whole outfit", reason "Shown without {pieces}: …", pieces "Jeans", notes [n1],
 *        missing [{name Jeans, reason "Its fit on the base body was refused", detail "deep_push_share 0.1512 > 0.12"}]}
 *        → head "Not the whole outfit — Shown without Jeans: this is not the outfit worn now until the missing pieces
 *        are on it.", light red, title n1; then "Jeans: Its fit on the base body was refused", light null, title the
 *        detail; translated with de.json the head starts "Nicht das ganze Outfit — Gezeigt ohne Jeans:" and the
 *        piece line is "Jeans: Seine Anpassung an den Grundkörper wurde abgelehnt";
 *      every English key the server sends (figure_build SERVED_* / PIECE_* / NOT_ON_FIGURE) has a de.json entry;
 *      FieldFigure renders <ServedStateNote state={data.served_state} /> in the viewer column.
 * [28] Ruling A86 — the front's Regenerate where its outdated reason is written, frontRegenerate(method, jobs):
 *      jobs J = {view 1, front 2, model 4, after_front 7, model_followup {jobs 4, stages [mesh, upscale, face, rig]}}
 *      (a stored base model; the front 1 view + 1 skin step, after it the 3 other views + the 4 model stages):
 *        ("reference", J) → label "Regenerate front from the profile image — 2 image jobs + 7 hub jobs at the next
 *        Build", note "Makes the base model stale — the next Build you start rebuilds it (7 hub jobs)";
 *        ("text", J with front 1) → "Regenerate front from text — 1 image job + 7 hub jobs at the next Build";
 *        ("reference", J without model_followup) → "Regenerate front from the profile image — 2 image jobs", note "";
 *        ("reference", J with after_front null) → "… — 2 image jobs + cost unknown at the next Build";
 *        ("reference", undefined) → "Regenerate front from the profile image", note "".
 *      Translated with de.json the first label is "Vorderansicht aus dem Profilbild neu erzeugen — 2 Bild-Jobs + 7
 *      Hub-Jobs beim nächsten Build".
 *      frontBuildCovers: 9 → "Or Build: it renders the front, the other views and the base model in one go — 9 hub
 *      jobs"; null → "… — cost unknown"; 0 and undefined → "".
 *      The reasons (base_body FRONT_MADE_FROM_TEXT / FRONT_OTHER_REFERENCE / FRONT_OTHER_EDIT_TEXT /
 *      FRONT_NO_PROFILE_NOW): 4 found, none names the button ("Regenerate"), each has a de.json entry, and the
 *      German one names no button either („Neu generieren“).
 *      Source greps: figure.py puts `"front": front_ref["wanted"]["method"]` on the plain body's change; FieldFigure
 *      leaves that change out of the one-line list (`c !== frontChange`), renders it as the Notices line `front`
 *      (Ruling A90, was <FrontChangeRow above the viewer) and posts
 *      'base-body/images', { view: 'front', force: true }; FieldBaseBody's FrontReferenceRow gets the cost and posts
 *      'images', { view: 'front', force: true }.
 */
import { existsSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
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

/**
 * The two new sub-tabs rendered with react-dom/server (no DOM, no effects): FieldModelRefs from its `initialInfo`,
 * OutfitModelRows from its props, FieldFigure with useFigure / useBaseBody / useModel3DStatus answering the
 * fixtures in globalThis.__A70_FIGURE__ / __A70_BASE__ / __A70_M3D__ (stub modules; everything else is the real code).
 */
async function loadRendered() {
  const esbuild = esbuildModule();
  const dir = await mkdtemp(join(tmpdir(), 'check-figure-ui-render-'));
  const chars = join(ROOT, 'frontend/src/tabs/characters');
  try {
    const stub = (name, body) => {
      const f = join(dir, `${name}.ts`);
      writeFileSync(f, body);
      return f;
    };
    const stubs = {
      useFigure: stub('useFigure', `export function useFigure() {
  return { data: globalThis.__A70_FIGURE__ ?? null, error: '', startPoll: () => undefined } }`),
      useBaseBody: stub('useBaseBody', `export * from ${JSON.stringify(join(chars, 'useBaseBody.ts'))}
export function useBaseBody() {
  return { info: globalThis.__A70_BASE__ ?? null, figure: null, setInfo: () => undefined, startPoll: () => undefined } }`),
      useModel3DStatus: stub('useModel3DStatus', `export function useModel3DStatus() {
  return { st: globalThis.__A70_M3D__ ?? null, setSt: () => undefined, load: () => undefined, startPoll: () => undefined } }`),
    };
    const entry = stub('entry', `
import { createElement } from 'react'
import { renderToString } from 'react-dom/server'
import { I18nProvider } from ${JSON.stringify(join(ROOT, 'frontend/src/i18n/I18nProvider.tsx'))}
import { ToastProvider } from ${JSON.stringify(join(ROOT, 'frontend/src/lib/Toast.tsx'))}
export { FieldFigure } from ${JSON.stringify(join(chars, 'FieldFigure.tsx'))}
export { FieldModelRefs, generateBody } from ${JSON.stringify(join(chars, 'FieldModelRefs.tsx'))}
export { OutfitModelRows } from ${JSON.stringify(join(chars, 'FigureOutfitModel.tsx'))}
export const h = createElement
export const render = (el) => renderToString(createElement(I18nProvider, null, createElement(ToastProvider, null, el)))
`);
    const file = join(dir, 'rendered.mjs');
    await esbuild.build({
      entryPoints: [entry], outfile: file, bundle: true, format: 'esm', platform: 'node', jsx: 'automatic',
      logLevel: 'silent', absWorkingDir: ROOT, loader: { '.css': 'empty', '.png': 'empty', '.svg': 'empty' },
      nodePaths: [join(ROOT, 'frontend/node_modules'), join(ROOT, 'node_modules')],
      banner: { js: "import { createRequire as __cr } from 'module'; const require = __cr(import.meta.url);" },
      plugins: [{
        name: 'a70-hooks',
        setup(build) {
          build.onResolve({ filter: /^\.\/(useFigure|useBaseBody|useModel3DStatus)$/ }, (a) => (
            a.importer.startsWith(dir) || !a.importer.startsWith(chars) ? undefined
              : { path: stubs[a.path.slice(2)] }));
        },
      }],
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
  { own_mesh: 'Own mesh', painted: 'Painted', in_body: 'In the body', template: 'Template (fabric)' });
check('[1] HAIR_MODE_LABELS', m.HAIR_MODE_LABELS,
  { hairdeck: 'HairDeck', haar: 'HAAR', body: 'In the body' });
check('[1] MESH_MODES order', m.MESH_MODES, ['own_mesh', 'painted', 'in_body', 'template']);
// Ruling A138: the template row's summary and cost line, and its due light.
check('[1] templateSummary', m.templateSummary({ kind: 'skirt', length_m: 0.45, flare: 0.4, waist_height: 'natural',
  slit: 'left', slit_m: 0.2, sleeves: 'none', fabric: 'medium' }),
  'Skirt · 45 cm · flare 0.4 · Medium (cotton, linen) · slit Left 20 cm');
check('[1] templateSummary without params', m.templateSummary(null), 'No parameters yet');
// Ruling A142: a jacket's summary names its sleeves, neckline and open front, no flare; the built line folds the arm
// shapes' sides and names the lower layer it was draped over.
check('[1] templateSummary jacket', m.templateSummary({ kind: 'jacket', length_m: 0.68, flare: 0.3,
  waist_height: 'natural', slit: 'none', slit_m: 0, shoulders: 'covered', sleeves: 'long', sleeve_fit: 0.3, fit: 0.4,
  neckline: 'v', neck_depth_m: 0, front: 'open', collar: 'lapel', fabric: 'stiff' }),
  'Jacket · 68 cm · Long sleeves · V-neck · open front · Stiff (denim, wool)');
check('[1] templateBuilt arms + layer', m.templateBuilt({ state: 'ready', built_at: '2026-11-16T20:00:00',
  metrics: { wall_s: 48, cpu_s: 600, stretch_max: 1.2, coverage: 0.9, texture: 'item_image',
    pose_shapes: ['arms_down', 'arms_up'], layered_over: 1 } }),
  'Draped 2026-11-16 20:00 · 48 s · stretch 1.20 · texture from the item picture · shaped for Arms down, Arms raised'
  + ' · draped over 1 lower layer(s)');
check('[1] templateCost', m.templateCost({ llm_calls: 1, hub_jobs: 0, cpu_s: 20 }),
  'Suggest: 1 LLM call · Drape: 0 hub jobs, ~20 s CPU');
check('[1] template due light', m.wornState({ state: 'pending', mode: 'template', jobs: 0, failure: '', left_out: '',
  note: '' }).text, 'Due: template drape · CPU, 0 hub jobs');
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
check('[8] up to date', m.headerLine('up_to_date', 0), 'Up to date');
check('[8] 2 changes', m.headerLine('changes', 2), '2 changes');
check('[8] 1 change', m.headerLine('changes', 1), '1 change');
check('[8] 0 changes', m.headerLine('changes', 0), 'Out of date');
check('[8] failed', m.headerLine('failed', 1), '1 change · a step failed');
check('[8] building 2', m.headerLine('building', 2), 'Building now · 2 changes');
check('[8] building 0', m.headerLine('building', 0), 'Building now');
check('[8] lights', ['up_to_date', 'changes', 'failed', 'building'].map((x) => m.statusLight(x)),
  ['green', 'yellow', 'red', 'blue']);

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
  { label: 'Everything is current', disabled: 'Everything is current' });
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
const row = (o) => ({ state: 'pending', mode: 'painted', jobs: 0, failure: '', left_out: '', note: '', ...o });
const ws = (o) => { const w = m.wornState(row(o)); return [w.light, w.text, w.sub]; };
check('[11] ready', ws({ state: 'ready' }), ['green', 'Ready', null]);
check('[11] own mesh due', ws({ mode: 'own_mesh', jobs: 3 }), ['yellow', 'Due: own mesh · 3 hub jobs', null]);
check('[11] A119 left off: body shape not built', ws({ state: 'left_out', mode: 'in_body', left_out: 'Body shape not built' }),
  ['grey', 'Left out', 'Body shape not built']);
check('[11] failed', ws({ state: 'failed', failure: 'mesh — refused' }), ['red', 'Failed', 'mesh — refused']);
check('[11] left out', ws({ state: 'left_out', left_out: 'no fit yet' }), ['grey', 'Left out', 'no fit yet']);
check('[11] in body pending', ws({ mode: 'in_body' }), ['yellow', 'Waits for the Build', null]);
const refusedRow = m.wornState(row({ state: 'fit_refused', mode: 'own_mesh', fit_refused: 'sole sinks', refused_on: 'T-shirt',
  fit_refused_detail: 'd' }));
check('[11] fit refused', [refusedRow.light, refusedRow.text, refusedRow.sub, refusedRow.detail],
  ['red', 'Refused on the body shape', 'Fits the plain body — refused on the body shape (T-shirt): sole sinks',
    `${m.FIT_REFUSED_NOTE}\nd`]);
const part = (state) => ({ key: 'k', state });
const br = (body, shape, tex) => m.bodyRows(body, shape, tex).map((r) => [r.key, r.light, r.state, r.reason]);
check('[11] body rows ready', br({ plain: part('ready'), shape: part('ready'), texture: part('ready') }, ['hair'],
  ['Black Blazer']), [['plain', 'green', 'Current', m.baseBodyLine('ready')], ['shape', 'green', 'Current', 'In the body: hair'],
  ['texture', 'green', 'Current', 'Painted: Black Blazer']]);
check('[11] body rows mixed', br({ plain: part('older_prompts'), shape: part('plain'), texture: part('missing') }, [],
  ['Blazer']), [['plain', 'yellow', 'Outdated', m.baseBodyLine('older_prompts')],
  ['shape', 'grey', 'Not needed', 'Nothing is worn in the body'],
  ['texture', 'yellow', 'Due', 'Painted: Blazer — the Build paints it']]);
check('[11] body rows: no plain body', br({ plain: part('missing'), shape: part('plain'), texture: part('none') }, [], [])[0]
  .slice(1, 3), ['yellow', 'None yet']);

// [12]
const wardrobe = src('frontend/src/tabs/characters/WardrobeTab.tsx');
const meshSteps = wardrobe.split("{t('Mesh steps')}")[0].split('\n').slice(-6).join('\n');
check('[12] Wardrobe: Mesh steps only on rows not worn on the pipeline',
  /garmentStatus && !\(it\.equipped && garments\.pipeline\)/.test(meshSteps), true);
const details = src('frontend/src/tabs/characters/FieldBaseBody.tsx');
const skin = details.split('function SkinStepLine(')[1]?.split('\nfunction ')[0] || '';
check('[12] skin step: stale-base note on the button', [/staleBaseNote\(/.test(skin), /t\('Run skin step'\)/.test(skin)],
  [true, true]);
const fieldFigure = src('frontend/src/tabs/characters/FieldFigure.tsx');
// Every POST of the tab goes through its one `post(path, …)` helper (one apiPost call).
const posts = [...fieldFigure.matchAll(/\bpost\(\s*['`]([^'`]+)['`]/g)].map((x) => x[1].replace(/\$\{[^}]*\}/g, '{}'));
// Ruling A42 adds the pause (spends nothing; Resume releases what the user already let wait) and Cancel; Ruling A86
// the front's Regenerate on the plain body's change (the Base body tab's own action).
check('[12] FieldFigure starts only the Build (+ the other state\'s mesh, the CPU Re-fit, the front)', [[...new Set(posts)].sort(),
  (fieldFigure.match(/\bapiPost\b/g) || []).length],
  [['base-body/images', 'figure/auto-build', 'figure/build', 'figure/generation-pause', 'figure/refit', 'figure/waiting/cancel',
    'garments/{}/run'], 2]);
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
check('[15] Figure tab: toggle on a closable row', /row\.piece_state \? \([\s\S]{0,200}<PieceStateToggle\b/.test(fieldFigure), true);
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
  { light: 'yellow', text: 'Due: plain body rebuild · 9 hub jobs', sub: 'n' });
check('[16] hair state HairDeck / HAAR / ready', [
  m.hairState({ mode: 'hairdeck', state: 'pending', note: '', jobs: 9 }).text,
  m.hairState({ mode: 'haar', state: 'pending', note: '', jobs: 9 }).text,
  m.hairState({ mode: 'haar', state: 'ready', note: '', jobs: 0 })],
  ['Due: HairDeck · 9 hub jobs', 'Due: HAAR · 9 hub jobs', { light: 'green', text: 'Ready', sub: null }]);
check('[16] estimate note', m.ESTIMATE_NOTE, 'Hub jobs are an estimate — retries extra');
check('[16] FieldFigure uses them', [/t\(ESTIMATE_NOTE\)/.test(fieldFigure),
  /listed\.map\(\(c\) => changeLine\(c, t\)\)/.test(fieldFigure)], [true, true]);

// [17] Ruling A13b: the 3D tab's rebuild button is the Figure tab's Build (the Pose tab's went with it, Ruling A70).
const fbb = src('frontend/src/tabs/characters/FigureBuildButton.tsx');
const fm3 = src('frontend/src/tabs/characters/FieldModel3D.tsx');
check('[17] FigureBuildButton posts only figure/build, labelled by buildButton',
  [[...fbb.matchAll(/apiPost[^(]*\(`\/characters\/\$\{enc\}\/([^`?]+)/g)].map((x) => x[1]),
    /buildButton\(data, t\)/.test(fbb)], [['figure/build'], true]);
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
check('[18] A73/A78: no viewer has an extension note',
  [/extensionNote/.test(figureViewer), /ExtensionPresenceNote/.test(fieldFigure),
    /extensionNote|ExtensionPresenceNote/.test(src('frontend/src/tabs/characters/FieldModel3D.tsx')),
    /extensionNote/.test(src('frontend/src/tabs/characters/Model3DViewer.tsx'))],
  [false, false, false, false]);
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
check('[19] Figure tab hair row: name + mode, link to Hairstyles', [/name: hair\.name \|\| t\('Hair'\)/.test(fieldFigure),
  /HAIR_MODE_LABELS\[hair\.mode as HairMode\]/.test(fieldFigure),
  /<div style=\{BUTTONS\}>\s*\{hairstyles\}/.test(fieldFigure)], [true, true, true]);

// [20] Ruling A42: "Pause automatic generation".
const gp = (n, jobs, unknown) => ({ paused: true, since: 's', running: [], resume_jobs: jobs, resume_unknown: unknown,
  waiting: Array.from({ length: n }, (_, i) => ({ id: `task:${i}`, source: 'task', tab: '', label: 'x', detail: '',
    jobs: 1 })) });
check('[20] pauseLine', [m.pauseLine({ ...gp(0, 0, 0), paused: false }), m.pauseLine(gp(2, 2, 0)), m.pauseLine(gp(1, 1, 0))],
  ['Automatic generation on', 'Automatic generation paused — 2 jobs held', 'Automatic generation paused — 1 job held']);
check('[20] resumeLabel', [m.resumeLabel(gp(0, 0, 0)), m.resumeLabel(gp(2, 7, 0)), m.resumeLabel(gp(1, 1, 0)),
  m.resumeLabel(gp(4, 3, 1)), m.resumeLabel(gp(5, 3, 2))],
  ['Resume — nothing waits', 'Resume — 7 hub jobs start', 'Resume — 1 hub job starts',
    'Resume — 3 hub jobs start (+1 job of unknown cost)', 'Resume — 3 hub jobs start (+2 jobs of unknown cost)']);
check('[20] waitingLine', [
  m.waitingLine({ id: 'garment:b', source: 'garment', tab: 'Wardrobe', label: 'Wardrobe · Blazer',
    detail: 'worn 2 + mesh 1', jobs: 3 }),
  m.waitingLine({ id: 'trigger:build', source: 'trigger', tab: '', label: 'Build (automatic)', detail: '', jobs: null }),
  m.waitingLine({ id: 'trigger:build', source: 'trigger', tab: '', label: 'Build (automatic)', detail: '', jobs: 0 })],
  ['Waiting: Wardrobe · Blazer · worn 2 + mesh 1 — 3 hub jobs', 'Waiting: Build (automatic) — cost unknown',
    'Waiting: Build (automatic) — no hub job']);
const pauseSrc = src('frontend/src/tabs/characters/GenerationPausePanel.tsx');
const useFigureSrc = src('frontend/src/tabs/characters/useFigure.ts');
check('[20] Cancel behind ConfirmDialog, posts, push topic', [
  /<ConfirmDialog open=\{asking !== null\}/.test(pauseSrc), /window\.confirm/.test(pauseSrc),
  /post\('figure\/generation-pause', \{ paused \}/.test(fieldFigure),
  /post\('figure\/waiting\/cancel', \{ id: job\.id \}/.test(fieldFigure),
  /onTopics\(\['generation'\]/.test(useFigureSrc)], [true, false, true, true, true]);

// [21] Task UI5.
const pst = (name, jobs, extra = {}) => ({ name, label: name, jobs, item_id: name === 'pieces' ? 'a' : '', failed: '',
  manual: '', ...extra });
const plan = (steps, running = false, step = null) => m.planRows({ cost: { hub_jobs: 0, note: '', steps },
  build: { running, step } }).map((r) => [r.light, r.state, r.reason]);
check('[21] plan rows', plan([pst('pieces', 3), pst('fits', 0), pst('texture', null)]),
  [['yellow', '3 hub jobs', ''], ['yellow', 'no hub job', ''], ['yellow', 'cost unknown', '']]);
check('[21] plan rows: failed, manual, running', [plan([pst('pieces', 3, { failed: 'x' })])[0],
  plan([pst('plain_body', 9, { manual: 'm' })])[0], plan([pst('pieces', 3)], true, { name: 'pieces', item_id: 'a' })[0][0]],
  [['red', '3 hub jobs', 'Failed: x'], ['yellow', '9 hub jobs', 'm'], 'blue']);
check('[21] state toggle notes', [m.stateToggleNote({ mode: 'own_mesh', other_state_jobs: 6 }, false),
  m.stateToggleNote({ mode: 'own_mesh', other_state_jobs: 6 }, true), m.stateToggleNote({ mode: 'own_mesh', other_state_jobs: 1 }, true),
  m.stateToggleNote({ mode: 'own_mesh', other_state_jobs: 0 }, true), m.stateToggleNote({ mode: 'in_body', other_state_jobs: null }, true)],
  ['Saved at once — nothing runs; the change waits for Build', 'Switching starts the Build — 6 hub jobs for that mesh',
    'Switching starts the Build — 1 hub job for that mesh', 'Switching starts the Build — no hub job (that mesh is built)',
    'Switching starts the Build — cost unknown']);
check('[21] auto-build notes, retry, re-fit', [m.autoBuildNote(true), m.autoBuildNote(false), m.retryLabel(3), m.retryLabel(null),
  m.REFIT_LABEL], ['Saved — changes start the Build by themselves', 'Saved — changes wait for Build', 'Retry — 3 hub jobs',
  'Retry — cost unknown', 'Re-fit — no hub job']);
const figureModelSrc = src('frontend/src/tabs/characters/figureModel.ts');
check('[21] Figure tab source', [/<StepRowView\b/.test(fieldFigure), /<SubTabs\b/.test(fieldFigure),
  /builtAt=\{data\.served_built_at\}/.test(fieldFigure), /[✓⏳]/.test(fieldFigure), /[✓⏳]/.test(figureModelSrc)],
  [true, true, true, false, false]);

// [22] Ruling A48c — the mesh view's fit allowance (`fitWiden.ts`, pure helpers; the rule's parity with the fit is
//      scripts/smoke_fit_widen_parity.py). Hand-derived: +3 % → ×1.03, Auto has no factor of its own; ×1.04 is an
//      automatic step and no setting, ×1.10 is +10 %; Auto's factor is read only from a fit made with Auto (a fit set to
//      +10 % says nothing about Auto); "PwAAAQ==" is base64 of the bytes 63, 0, 0, 1: the little-endian 16-bit words 63
//      (bits 0..5) and 256 (bit 8, Ruling A76: nine factors since the choices reach +20 %); the factor list
//      [1, 1.02, 1.03, 1.04, 1.06, 1.08, 1.1] puts ×1.06 at bit 4; a gap of −3 mm reads "−3.0 mm".
{
  const w = await loadBundled(join(ROOT, 'frontend/src/tabs/characters/fitWiden.ts'));
  const choices = ['auto', 0, 3, 6, 10];
  check('[22] choice factors', [w.choiceFactor(3), w.choiceFactor(0), w.choiceFactor(10), w.choiceFactor('auto')],
    [1.03, 1, 1.1, null]);
  check('[22] factor → choice', [w.factorChoice(1.04, choices), w.factorChoice(1.1, choices), w.factorChoice(1, choices)],
    [null, 10, 0]);
  check('[22] Auto factor from the stored fit', [
    w.autoFactor({ allowance: { setting: 'auto', factor: 1.04, trigger: [] } }),
    w.autoFactor({ allowance: { setting: 10, factor: 1.1, trigger: [] } }),
    w.autoFactor({ allowance: { setting: 'auto', factor: 1.04, trigger: [], inherited: true } }),
    w.autoFactor(null)], [1.04, null, null, null]);
  const factors = [1, 1.02, 1.03, 1.04, 1.06, 1.08, 1.1];
  check('[22] labels, bits, mask', [w.factorText(1.04), w.factorText(1), w.maskBit(factors, 1.06), w.maskBit(factors, 1.05),
    Array.from(w.decodeMask('PwAAAQ==')), w.mmText(-3), w.mmText(12.44), w.mmText(null)],
    ['×1.04', '×1.00', 4, -1, [63, 256], '−3.0 mm', '12.4 mm', '–']);
  const table = { factors, steps: factors.map((f, i) => ({ factor: f, share: i / 10, face_share: 0, inside_faces: 0,
    gap_p50_mm: null, gap_min_mm: null })) };
  check('[22] step lookup', [w.stepAt(table, 1.06)?.share, w.stepAt(table, 1.05), w.stepAt(null, 1)], [0.4, null, null]);
  const xyz = [0.25, 1, 0.05, 0.6, 0.5, -0.05];
  w.widenInPlace(xyz, 1.06, { centre_x: 0.1, centre_z: -0.05, half_width: 0.2 });
  check('[22] widen (smoke_fit_widen_parity [1])', xyz.map((v) => Math.round(v * 1e9) / 1e9), [0.259, 1, 0.056, 0.612, 0.5, -0.05]);
  const meshView = src('frontend/src/tabs/characters/GarmentMeshView.tsx');
  check('[22] viewer source: larger view portalled, Esc goes back first, zoom reset on double-click, no native dialogs',
    [/createPortal\(/.test(meshView), /if \(large\) setLarge\(false\)/.test(meshView), /resetViewOnDoubleClick/.test(meshView),
      /window\.(prompt|alert|confirm)/.test(meshView)], [true, true, true, false]);
}

// [22b] Ruling A68 — the depth allowance's helpers (`fitWiden.ts`; parity: smoke_fit_widen_parity.py [4]..[6]).
//      Hand-derived: +10 % of the half depth 0.2 is 0.02, without the depth frame 0; frame cx 0, cz 0.02, x_limit
//      0.12, y_limit 1.3, ramp 0.03, ease 0.01: (0, 1, 0.15) in front +0.01, (0, 1, 0.035) at the side +0.005,
//      (0.13, 1, 0.15) a sleeve 0, (0, 1.35, -0.1) the neck opening 0; the gaps of depth +6 % at ×1.06 are the
//      third pair of that step; "+6 %"; the panel labels no longer say "(width only)" and Save posts the changes.
{
  const w = await loadBundled(join(ROOT, 'frontend/src/tabs/characters/fitWiden.ts'));
  const ax = { centre_x: 0, centre_z: 0.02, half_width: 0.2, x_limit: 0.12, y_limit: 1.3, ramp: 0.03, half_depth: 0.2 };
  const r = (v) => Math.round(v * 1e12) / 1e12;
  check('[22b] ease of a choice', [r(w.depthEase(ax, 10)), w.depthEase({ centre_x: 0, centre_z: 0, half_width: 1 }, 10),
    w.depthEase(null, 6)], [0.02, 0, 0]);
  check('[22b] depth shift by hand', [r(w.depthShift(0, 1, 0.15, 0.01, ax)), r(w.depthShift(0, 1, 0.035, 0.01, ax)),
    r(w.depthShift(0.13, 1, 0.15, 0.01, ax)), r(w.depthShift(0, 1.35, -0.1, 0.01, ax)), r(w.depthShift(0, 1, -0.1, 0.01, ax))],
  [0.01, 0.005, 0, 0, -0.01]);
  const view = { factors: [1, 1.06], depth: { choices: [0, 3, 6, 10], ease_mm: [0, 3.6, 7.2, 12] },
    steps: [1, 1.06].map((f) => ({ factor: f, depth_gaps: [[1, 2], [3, 4], [f === 1 ? 5 : 5.3, 6], [7, 8]] })) };
  check('[22b] gaps lookup', [w.depthGapsAt(view, 1.06, 6), w.depthGapsAt(view, 1.06, 5), w.depthGapsAt(null, 1, 0),
    w.depthText(6)], [[5.3, 6], null, null, '+6 %']);
  const meshView = src('frontend/src/tabs/characters/GarmentMeshView.tsx');
  const fitSettings = src('frontend/src/tabs/characters/FitSettings.tsx');
  check('[22b] sources: depth slider beside the viewer, no "(width only)", both settings saved, depth select',
    [/data-allowance-depth=/.test(meshView), /\(width only\)/.test(meshView + fitSettings),
      /change\.depth = depth/.test(meshView), /id="fit-depth"/.test(fitSettings)], [true, false, true, true]);
}

// [23] Ruling A61
const prob = (o) => ({ kind: 'mesh_mismatch', step: 'assemble', step_label: 'Assemble the figure', view: 'back',
  body: 'plain', detail: 'GLBBodyRetexture: back view: …', action: 'rebuild_mesh', jobs: 3, held: true, ...o });
const pm = m.problemText(prob({}));
check('[23] mesh mismatch, plain body', [pm.title, pm.reason.includes('its own back view'),
  pm.reason.includes('Rendering the view again does not help'), pm.action, pm.note, pm.detail],
  ['Assemble the figure failed — Back view', true, true, 'Make the base mesh again — 3 hub jobs', m.MESH_HELD_NOTE,
    'GLBBodyRetexture: back view: …']);
check('[23] mesh mismatch, body shape', m.problemText(prob({ body: 'shape', jobs: 1 })).action,
  'Make the body shape mesh again — 1 hub job');
const pf = m.problemText(prob({ kind: 'failed', step: 'texture', step_label: 'Texture', view: '', body: '',
  detail: 'boom', action: 'retry', jobs: null }));
check('[23] other failure', [pf.title, pf.reason, pf.action, pf.note, pf.detail],
  ['Texture failed', m.FAILED_PLAIN, 'Retry this step — cost unknown', m.HELD_NOTE, 'boom']);
const pn = m.problemText(prob({ kind: 'failed', held: false, jobs: 0 }));
check('[23] at a view, not held, no job', [pn.reason, pn.note, pn.action],
  ['The step stopped at the back view — the message is on mouse-over.', '', 'Retry this step — no hub job']);
check('[23] tabs render it', [/<BuildProblemNote\b/.test(src('frontend/src/tabs/characters/FieldModel3D.tsx')),
  /<BuildProblemView\b/.test(fieldFigure), /<BuildProblemView\b/.test(details)], [true, true, true]);

// [26] Ruling A70: the Pose tab dissolved into the Figure tab's Dressed views and Outfit model sub-tabs.
{
  let dv;
  try {
    dv = await loadBundled(join(ROOT, 'frontend/src/tabs/characters/dressedViewsModel.ts'));
  } catch (e) {
    failures.push(`[26] dressedViewsModel.ts not loadable: ${e.message}`);
  }
  if (dv) {
    // viewRow (folded from check_pose_ui [1])
    const cur = { state: 'current' };
    const tile = (freshness = cur, extra = {}) => ({ filename: 'f.png', freshness, ...extra });
    const vr = (info, draft, running = false) => { const r = dv.viewRow(info, draft, running); return [r.light, r.state, r.reason]; };
    check('[26] viewRow running', vr(tile(), tile(), true), ['blue', 'Rendering', '']);
    check('[26] viewRow nothing stored', vr(null, null), ['yellow', 'Not rendered yet', '']);
    check('[26] viewRow current', vr(tile(), tile()), ['green', 'Current', '']);
    const draftStale = dv.viewRow(tile(), tile({ state: 'stale', reason: 'R', action: 'A' }), false);
    check('[26] viewRow draft stale', [draftStale.light, draftStale.state, draftStale.reason, draftStale.detail],
      ['yellow', 'Outdated', 'R', 'R\nA']);
    check('[26] viewRow the view first', vr(tile({ state: 'stale', reason: 'V' }), tile({ state: 'stale', reason: 'D' }))[2], 'V');
    check('[26] viewRow warning', vr(tile(cur, { warning: 'W' }), null), ['yellow', 'Kept with a warning', 'W']);
    check('[26] viewRow stale + warning', dv.viewRow(tile({ state: 'stale', reason: 'V' }, { warning: 'W' }), null, false).detail, 'V\nW');
    check('[26] viewRow stale without a reason', vr(tile({ state: 'stale' }), null)[2], 'Made from older data');
    // outfitRow (folded from check_pose_ui [2])
    const o = (status, extra = {}) => ({ status, error: '', warnings: [], ...extra });
    const or = (x) => { const r = dv.outfitRow(x, 'S', 'P'); return [r.light, r.state, r.reason, r.detail]; };
    check('[26] outfitRow running', or(o('running', { warnings: ['w'] })), ['blue', 'Building now', '', '']);
    check('[26] outfitRow failed', or(o('failed', { error: 'boom' })), ['red', 'Failed', 'boom', 'boom']);
    check('[26] outfitRow stale', or(o('stale')).slice(0, 3), ['yellow', 'Outdated', 'S']);
    check('[26] outfitRow missing', or(o('missing')).slice(0, 3), ['yellow', 'Not built yet', 'The Build makes it']);
    check('[26] outfitRow ready', or(o('ready')), ['green', 'Ready', 'P', 'P']);
    check('[26] outfitRow ready with warnings', or(o('ready', { warnings: ['w1', 'w2'] })),
      ['yellow', 'Ready — with warnings', 'w1', 'w1\nw2']);
    // renderAllLabel (folded from check_pose_ui [4]; off the pipeline, now the 3D tab's Pose render)
    check('[26] render all', [dv.renderAllLabel(0), dv.renderAllLabel(2), dv.renderAllLabel(-1)],
      ['Render all views — 1 image job', 'Render all views — 3 image jobs', 'Render all views — 1 image job']);
    // viewAction: what a view's button does — an edit (1 image job) or a copy (no job)
    const va = (src) => { const a = dv.viewAction(src); return [a.label, a.jobs, a.note]; };
    check('[26] viewAction edit', va({ source: 'painted', shape: 'ob0a1b2c3d', jobs: 1 }),
      ['Regenerate this view — 1 image job', 1, '']);
    check('[26] viewAction unknown source = the edit', va(null), ['Regenerate this view — 1 image job', 1, '']);
    check('[26] viewAction shape copy', va({ source: 'shape', shape: 'ob0a1b2c3d', jobs: 0 }),
      ['Copy this view again from the body shape — no job', 0, dv.SHAPE_COPY_NOTE]);
    check('[26] viewAction plain copy', va({ source: 'plain', shape: 'base1234abcd', jobs: 0 }),
      ['Copy this view again from the plain body — no job', 0, dv.PLAIN_COPY_NOTE]);
    check('[26] VIEWS_BY_BUILD', dv.VIEWS_BY_BUILD,
      'The Build above renders these views and builds the outfit model from them.');
  }

  // No Pose tab: the template, the slot, the files.
  const tpl = JSON.parse(src('shared/templates/character/base-character.json') || '{}');
  const ids = [...(tpl.tabs || []), ...(tpl.sections || [])].map((b) => b.id);
  const chars = src('frontend/src/tabs/characters/CharactersTab.tsx');
  check('[26] no Pose tab in the template / the slots / the tree', [ids.includes('tpose_tab'), ids.includes('model_refs'),
    /\bmodel_refs\s*:/.test(chars), /'model_refs'/.test(chars), /FieldPose/.test(chars),
    existsSync(join(ROOT, 'frontend/src/tabs/characters/FieldPose.tsx')),
    existsSync(join(ROOT, 'frontend/src/tabs/characters/poseModel.ts'))], [false, false, false, false, false, false, false]);
  // Its links now open the Figure tab: no "Pose tab" left in the UI or server strings; the views' ↗ Body opens the
  // Figure tab's Body sub-tab; the occasions name the Figure tab's Dressed views.
  const walk = (dir, ext) => {
    const out = [];
    for (const e of readdirSync(join(ROOT, dir), { withFileTypes: true })) {
      const p = `${dir}/${e.name}`;
      if (e.isDirectory()) out.push(...walk(p, ext));
      else if (ext.some((x) => e.name.endsWith(x))) out.push(p);
    }
    return out;
  };
  const poseTab = [...walk('frontend/src', ['.ts', '.tsx']), ...walk('packages/player-ui/src', ['.ts', '.tsx']),
    ...walk('app', ['.py'])].filter((p) => /(['"`])[^'"`\n]*\bPose tab\b[^'"`\n]*\1/.test(src(p)));
  check('[26] no "Pose tab" string left in frontend/src, player-ui, app', poseTab, []);
  check('[26] FieldFigure: the two sub-tabs, the views with ↗ Body / ↗ Base body, the outfit model',
    [/id: 'views' as const, label:/.test(fieldFigure), /id: 'model' as const, label: t\('Outfit model'\)/.test(fieldFigure),
      /<FieldModelRefs character=\{character\} kinds=\{TPOSE\} layout="steps" onOpenBaseBody=\{onOpenBaseBody\}/.test(fieldFigure),
      /onOpenBody=\{openBody\}/.test(fieldFigure), /const openBody = useCallback\(\(\) => setSub\('body'\), \[\]\)/.test(fieldFigure),
      /t\(VIEWS_BY_BUILD\)/.test(fieldFigure), /<FigureOutfitModel\b/.test(fieldFigure)], [true, true, true, true, true, true, true]);
  const occ = src('app/imagegen/occasions.py');
  check('[26] occasions name the Figure tab', ['outfit_front', 'outfit_back_draft', 'outfit_side_draft'].map((k) =>
    new RegExp(`"${k}": _image\\(\\s*"[^"]+", "Figure tab, Dressed views: `).test(occ)), [true, true, true]);
  // Regenerate on a view posts exactly that view's job.
  const refsSrc = src('frontend/src/tabs/characters/FieldModelRefs.tsx');
  check('[26] a view button posts generateBody(view, …)', [/onClick=\{\(\) => generate\(view\)\}/.test(refsSrc),
    /\/model-refs\/generate`,\s*generateBody\(view, kindList,/.test(refsSrc), /action\.label/.test(refsSrc),
    /singleAction\('view', 1, t\)/.test(refsSrc)], [true, true, true, false]);
  check('[26] FieldModelRefs: steps layout (no stack), the face view link + its switch (from check_pose_ui [5])',
    [/layout === 'steps'/.test(refsSrc), /'stack'/.test(refsSrc), /onClick=\{onOpenBaseBody\}/.test(refsSrc),
      /setView\('face', e\.target\.checked\)/.test(refsSrc)], [true, false, true, true]);
  // Off the pipeline the T-pose views moved to the 3D tab's "Pose render" sub-tab.
  const side = src('frontend/src/tabs/characters/Model3DSidePanels.tsx');
  check('[26] 3D tab: Pose render off the pipeline only', [
    /const poseRender = !!panel && !panel\.st\.pipeline\b/.test(side)
      && /\(poseRender \? \[\{ id: 'pose' as const, label: t\('Pose render'\) \}\]/.test(side)
      && /\(sub === 'pose' && !poseRender\) \? 'steps'/.test(side),
    /<FieldModelRefs character=\{character\} kinds=\{TPOSE\} layout="steps" \/>/.test(side)], [true, true]);

  // Rendered from fixtures (react-dom/server; the hooks of FieldFigure / FigureOutfitModel answer the fixture).
  let r;
  try {
    r = await loadRendered();
  } catch (e) {
    failures.push(`[26] the sub-tabs not renderable: ${String(e.message).slice(0, 400)}`);
  }
  if (r) try {
    const b = r.generateBody;
    check('[26] generateBody: one view = exactly its job', [b('back', ['tpose'], { pipeline: true }),
      b('main', ['tpose'], { pipeline: true }), b(undefined, ['tpose'], { pipeline: true, auto: { tpose: false } }),
      b(undefined, ['tpose'], { pipeline: false, auto: { tpose: false } })],
    [{ kinds: ['tpose'], view: 'back' }, { kinds: ['tpose'], view: 'main' }, { kinds: ['tpose'] }, { kinds: [] }]);
    const refsInfo = (source, extra = {}) => ({
      signature: 'osig', pipeline: true, build: { running: false, step: '' }, status: {}, auto: { tpose: true, pose: true },
      now: '2026-11-14T21:00:00Z', drafts: { back: null },
      tpose: { filename: 'tpose_osig.png', created_at: '2026-11-14T20:00:00Z', freshness: { state: 'current' } },
      views: { back: { enabled: true, info: { filename: 'tpose_back_osig.png', freshness: { state: 'current' } } },
        face: { enabled: false, info: null } },
      face_view: { exists: false, stale: false, rendering: false, url: '/f' },
      dressed_source: source, ...extra });
    const count = (html, s) => html.split(s).length - 1;
    const steps = (info, links = true) => r.render(r.h(r.FieldModelRefs, { character: 'Kai', kinds: ['tpose'], layout: 'steps',
      initialInfo: info, ...(links ? { onOpenBody: () => undefined, onOpenBaseBody: () => undefined } : {}) }));
    const shape = steps(refsInfo({ source: 'shape', shape: 'ob0a1b2c3d', jobs: 0 }));
    check('[26] Dressed views, shape copy: two rows say it and cost no job, ↗ Body each', [
      count(shape, 'Front view</strong>'), count(shape, 'Back view</strong>'),
      count(shape, 'Copy this view again from the body shape — no job'), count(shape, 'Regenerate this view'),
      count(shape, 'Copy of the body shape’s view — nothing painted'), count(shape, 'Body</button>'),
      count(shape, 'Face view: it textures the plain body’s face')], [1, 1, 2, 0, 1, 1, 2]);
    const painted = steps(refsInfo({ source: 'painted', shape: 'ob0a1b2c3d', jobs: 1 }));
    check('[26] Dressed views, painted: 1 image job each', [count(painted, 'Regenerate this view — 1 image job'),
      count(painted, 'Painted on the body shape’s view'), count(painted, 'no job')], [2, 1, 0]);
    const plain = steps(refsInfo({ source: 'plain', shape: 'base1234abcd', jobs: 0 }));
    check('[26] Dressed views, plain copy: ↗ Base body each (+ the face view note)', [
      count(plain, 'Copy this view again from the plain body — no job'), count(plain, 'Base body</button>')], [2, 2]);
    const off = steps({ signature: 'asig', pipeline: false, status: {}, auto: { tpose: true }, now: '2026-11-14T21:00:00Z',
      tpose: { filename: 'tpose_asig.png', freshness: { state: 'current' } },
      views: { left: { enabled: true, info: null } } }, false);
    check('[26] off the pipeline (3D tab): edits, Render all, Auto', [count(off, 'Regenerate this view — 1 image job'),
      count(off, 'Render all views — 2 image jobs'), count(off, '>Auto<'), count(off, 'nothing painted')], [2, 1, 1, 0]);
    const outfit = r.render(r.h(r.OutfitModelRows, { outfit: { status: 'ready', error: '', warnings: [], stale_reason: null,
      proof: { texels: { garment_share_of_exposed: 0.92, unseen_filled_share_of_exposed_garment: 0.031 } } },
    steps: [{ id: 'mesh', label: 'Mesh', status: 'done', detail: '', numbers: {} }] }));
    check('[26] Outfit model: the step row with the proof numbers, the steps', [count(outfit, 'Outfit model (base body)'),
      count(outfit, '>Ready<'),
      count(outfit, '>Garment coverage of the visible surface: 92.0 % · Garment filled in without a view: 3.1 %<'),
      count(outfit, 'No model steps recorded')], [1, 1, 1, 0]);
    globalThis.__A70_FIGURE__ = { humanoid: true, pipeline: true, auto_build: false, status: 'current', outfit: 'Casual',
      build: { running: false, step: null, failed: {}, deferred: null, paused: null }, served_url: null,
      served_built_at: null, served_foot_pose: null, changes: [], cost: { hub_jobs: 0, steps: [] }, worn: [], hair: null,
      body: null, problem: null, generation_pause: null };
    const views = r.render(r.h(r.FieldFigure, { character: 'Kai', initialSub: 'views' }));
    check('[26] FieldFigure opens on Dressed views: its tab, the Build line, the hidden others', [
      count(views, '>Dressed views<'), count(views, '>Outfit model<'), count(views, 'The Build above renders these views'),
      count(views, '>Worn now (')], [1, 1, 1, 1]);
    globalThis.__A70_BASE__ = { pipeline: true, outfit: { status: 'ready', error: '', warnings: [], stale_reason: null,
      proof: { texels: { garment_share_of_exposed: 0.92 } } } };
    globalThis.__A70_M3D__ = { model: { steps: [] } };
    const model = r.render(r.h(r.FieldFigure, { character: 'Kai', initialSub: 'model' }));
    check('[26] FieldFigure opens on Outfit model: its rows (the hooks answer the fixture)', [
      count(model, 'Outfit model (base body)'), count(model, '>Garment coverage of the visible surface: 92.0 %<')], [1, 1]);
  } catch (e) {
    failures.push(`[26] rendering failed: ${String(e.stack || e).slice(0, 600)}`);
  }
}

// [24] Ruling A67 — the piece dialog's two bodies (header).
{
  const base = { body: '', key: 'plain', role: 'base', label: 'Plain body', status: 'accepted', reason: '',
    reason_detail: '', piece_broken: false, url: null, built_at: null, marks: [], foot_pose: null, can_accept: false,
    accept_block: '', accepted_at: null, method_note: '', variant: '', refit_block: '', arm_light: null, numbers: {},
    fit: null };
  const cur = { ...base, body: 'ob0000000b', key: 'ob0000000b', role: 'current', label: 'Body shape (Blouse, Jeans)',
    status: 'refused', reason: 'x' };
  const derived = { ...cur, key: 'ob0000000b-derived', variant: 'derived' };
  check('[24] names', [m.fitBodyName(base), m.fitBodyName(cur), m.fitBodyLongName(cur),
    m.fitBodyLongName({ role: 'current', label: 'Body shape ob0000000b' }), m.fitBodyLongName(base)],
  ['Base body', 'Current body', 'Current body (Blouse, Jeans)', 'Current body', 'Base body']);
  check('[24] defaultBodyKey', [m.defaultBodyKey([base, cur, derived]), m.defaultBodyKey([base]), m.defaultBodyKey([])],
    ['ob0000000b', 'plain', 'plain']);
  check('[24] showBodySwitch', [m.showBodySwitch([base, cur]), m.showBodySwitch([base]),
    m.showBodySwitch([{ ...base, status: 'refused' }])], [true, false, true]);

  const esbuild = esbuildModule();
  const dir = await mkdtemp(join(tmpdir(), 'check-figure-ui-ssr-'));
  let render;
  try {
    const entry = join(dir, 'entry.tsx');
    const file = join(dir, 'ssr.cjs');
    const at = (rel) => JSON.stringify(join(ROOT, rel));
    writeFileSync(entry, [
      `import { renderToStaticMarkup } from 'react-dom/server'`,
      `import { I18nProvider } from ${at('frontend/src/i18n/I18nProvider.tsx')}`,
      `import { ToastProvider } from ${at('frontend/src/lib/Toast.tsx')}`,
      `import { FitBodySwitch } from ${at('frontend/src/tabs/characters/FitBodySwitch.tsx')}`,
      `export const render = (bodies, selected) => renderToStaticMarkup(<I18nProvider><ToastProvider><FitBodySwitch`,
      `  character="demo" itemId="jacket" bodies={bodies} selected={selected} onSelect={() => {}}`,
      `  onChanged={() => {}} onRefit={() => {}} /></ToastProvider></I18nProvider>)`,
    ].join('\n'));
    await esbuild.build({
      entryPoints: [entry], outfile: file, bundle: true, format: 'cjs', platform: 'node', jsx: 'automatic',
      logLevel: 'silent', absWorkingDir: ROOT, nodePaths: [join(ROOT, 'node_modules')],
      define: { 'process.env.NODE_ENV': '"production"' }, loader: { '.css': 'empty' },
    });
    render = require_(file).render;
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
  const text = (html) => html.replace(/<[^>]+>/g, '|').replace(/\|+/g, '|');
  const two = render([base, cur], 'ob0000000b');
  const group = /<div[^>]*role="group"[^>]*>([\s\S]*?)<\/div>/.exec(two)?.[1] || '';
  const buttons = [...group.matchAll(/<button[^>]*>([\s\S]*?)<\/button>/g)].map((b) => b[1]);
  check('[24] two bodies: one group, two buttons', [(two.match(/role="group"/g) || []).length, buttons.length], [1, 2]);
  check('[24] button names', buttons.map((b) => text(b).split('|').filter(Boolean).join(' ')), ['Base body', 'Current body']);
  check('[24] each button its light', buttons.map((b) => /border-radius:50%;background:([^;"]+)/.exec(b)?.[1] || null),
    ['var(--success, #3fb950)', 'var(--danger, #f85149)']);
  check('[24] verdict lines', [text(two).includes('|Base body: accepted|'),
    text(two).includes('|▸ Current body (Blouse, Jeans): refused — x|')], [true, true]);
  check('[24] Re-fit on the current body; no old names shown', [two.includes('Re-fit on this body (0 hub jobs)'),
    text(two).includes('Plain body'), text(two).includes('Body shape')], [true, false, false]);
  const one = render([base], 'plain');
  check('[24] one body (current == base): no selector', [one.includes('role="group"'), (one.match(/<button/g) || []).length],
    [false, 0]);
  const block = "This body shape is not built yet — the Figure tab's Build makes it";
  const unbuilt = render([base, { ...cur, status: 'missing', reason: block, refit_block: block }], 'ob0000000b');
  check('[24] not built: the reason instead of Re-fit', [unbuilt.includes('Re-fit on this body'),
    unbuilt.includes(block.replace("'", '&#x27;'))], [false, true]);

  const wg = src('frontend/src/tabs/characters/WardrobeGarment.tsx');
  check('[24] dialog opens on the current body, Re-fit posts the selected body', [
    /useState<string \| null>\(null\)/.test(wg), /bodyKey \?\? defaultBodyKey\(bodies\)/.test(wg),
    /\{ \.\.\.run, body: refitBody \}/.test(wg), /onRun\(\{ step: 'fit', force: true, body: b \}/.test(wg)],
  [true, true, true, true]);
  const fs = src('frontend/src/tabs/characters/FootwearSteps.tsx');
  check('[24] footwear rows: Base body / Current body', [fs.includes("t('Current body')"), fs.includes("t('Base body')"),
    fs.includes("t('Body shape {id}')")], [true, true, false]);
  const de = JSON.parse(src('shared/languages/de.json')).translations;
  check('[24] de.json keys', ['Base body', 'Current body', 'Current body ({pieces})',
    'The body shape the worn outfit calls for: {shape}', block].map((k) => k in de)
    .concat(['The figure stands on this body now' in de]), [true, true, true, true, true, false]);
}

// [25] Ruling A69
const acc = (a) => { const w = m.wornState(row({ state: 'ready', mode: 'own_mesh', accepted_by_user: { detail: '',
  at: null, ...a } })); return [w.light, w.text, w.sub]; };
check('[25] fit on the plain body', acc({ step: 'fit', on: 'Plain body', reason: 'deep_push_share 0.1512 > 0.12' }),
  ['green', 'Ready — Accepted by you', 'Plain body: its checks refused it — deep_push_share 0.1512 > 0.12']);
check('[25] fit, older server (no step)', acc({ on: 'Plain body', reason: 'x' })[2], 'Plain body: its checks refused it — x');
check('[25] mesh', acc({ step: 'mesh', on: '', reason: 'largest component 0.82 < 0.9' }),
  ['green', 'Ready — Accepted by you', 'Mesh: its gate refused it — largest component 0.82 < 0.9']);
check('[25] image', acc({ step: 'ghost', view: 'back', on: '', reason: 'piece_share 0.02 < 0.03' })[2],
  'Piece-only views · Back view: its gate refused it — piece_share 0.02 < 0.03');
check('[25] image without a reason', acc({ step: 'worn', view: 'front', on: '', reason: '' })[2],
  'Worn views · Front view: its gate refused it');
check('[25] the Wardrobe chip\'s fit', m.acceptedWhat({ step: 'fit', on: '', reason: 'r' }), 'Fit: its checks refused it — r');
{
  const wardrobe = src('frontend/src/tabs/characters/WardrobeGarment.tsx');
  const grid = src('frontend/src/tabs/characters/GarmentStepGrid.tsx');
  check('[25] Wardrobe chip + fit row', [/status\.accepted_by_user\) text \+= ` · \$\{t\(ACCEPTED_BY_YOU\)\}`/.test(wardrobe),
    /!shownFit && fit\?\.status === 'accepted' && fit\.user_accepted/.test(grid)], [true, true]);
}

// [27] Ruling A75 — the viewer's status of the figure it shows.
{
  const id = (k) => k;
  check('[27] none', m.servedLines(null, id), []);
  check('[27] complete', m.servedLines({ light: 'green', state: 'Shows the outfit worn now', reason: '', missing: [] }, id),
    [{ light: 'green', text: 'Shows the outfit worn now', title: '', head: true }]);
  const red = { light: 'red', state: 'Not the whole outfit', pieces: 'Jeans', notes: ['n1'],
    reason: 'Shown without {pieces}: this is not the outfit worn now until the missing pieces are on it.',
    missing: [{ item_id: 'i', name: 'Jeans', reason: 'Its fit on the base body was refused',
      detail: 'deep_push_share 0.1512 > 0.12', pending: false }] };
  check('[27] without a piece', m.servedLines(red, id), [
    { light: 'red', text: 'Not the whole outfit — Shown without Jeans: this is not the outfit worn now until the missing pieces are on it.',
      title: 'n1', head: true },
    { light: null, text: 'Jeans: Its fit on the base body was refused', title: 'deep_push_share 0.1512 > 0.12', head: false }]);
  const de = JSON.parse(src('shared/languages/de.json')).translations;
  const tde = (k) => de[k] ?? k;
  const lines = m.servedLines(red, tde);
  check('[27] German', [lines[0].text.startsWith('Nicht das ganze Outfit — Gezeigt ohne Jeans:'), lines[1].text],
    [true, 'Jeans: Seine Anpassung an den Grundkörper wurde abgelehnt']);
  const py = src('app/core/figure_build.py');
  const keys = [...py.matchAll(/^(?:SERVED_[A-Z_]+|PIECE_[A-Z_]+|NOT_ON_FIGURE)(?:, [A-Z_]+)* = ("(?:[^"\\]|\\.)*")/gm)]
    .map((x) => JSON.parse(x[1]));
  check('[27] server keys found', keys.length >= 11, true);  // A119: stand-in / older-base states gone
  check('[27] server keys translated', keys.filter((k) => !(k in de)), []);
  check('[27] FieldFigure renders it',
    /<ServedStateNote state=\{data\.served_state\} \/>/.test(src('frontend/src/tabs/characters/FieldFigure.tsx')), true);
}

// [28] Ruling A86 — the front's Regenerate beside its outdated reason.
{
  const J = { view: 1, front: 2, model: 4, after_front: 7, model_followup: { jobs: 4, stages: ['mesh', 'upscale', 'face', 'rig'] } };
  check('[28] from the profile image', m.frontRegenerate('reference', J), {
    label: 'Regenerate front from the profile image — 2 image jobs + 7 hub jobs at the next Build',
    note: 'Makes the base model stale — the next Build you start rebuilds it (7 hub jobs)' });
  check('[28] from text', m.frontRegenerate('text', { ...J, front: 1 }).label,
    'Regenerate front from text — 1 image job + 7 hub jobs at the next Build');
  check('[28] no base model stored', m.frontRegenerate('reference', { ...J, model_followup: null }),
    { label: 'Regenerate front from the profile image — 2 image jobs', note: '' });
  check('[28] follow-up unknown', m.frontRegenerate('reference', { ...J, after_front: null }).label,
    'Regenerate front from the profile image — 2 image jobs + cost unknown at the next Build');
  check('[28] no counts', m.frontRegenerate('reference', undefined),
    { label: 'Regenerate front from the profile image', note: '' });
  const de = JSON.parse(src('shared/languages/de.json')).translations;
  const tde = (k) => de[k] ?? k;
  check('[28] German', m.frontRegenerate('reference', J, tde).label,
    'Vorderansicht aus dem Profilbild neu erzeugen — 2 Bild-Jobs + 7 Hub-Jobs beim nächsten Build');
  check('[28] Build covers it', [m.frontBuildCovers(9), m.frontBuildCovers(null), m.frontBuildCovers(0),
    m.frontBuildCovers(undefined)], ['Or Build: it renders the front, the other views and the base model in one go — 9 hub jobs',
    'Or Build: it renders the front, the other views and the base model in one go — cost unknown', '', '']);
  const reasons = [...src('app/core/base_body.py').matchAll(/^FRONT_(?:MADE_FROM_TEXT|OTHER_REFERENCE|OTHER_EDIT_TEXT|NO_PROFILE_NOW) = ("(?:[^"\\]|\\.)*")/gm)]
    .map((x) => JSON.parse(x[1]));
  check('[28] reasons found', reasons.length, 4);
  check('[28] reasons name no button', reasons.filter((r) => /Regenerate/.test(r)), []);
  check('[28] reasons translated', reasons.filter((r) => !(r in de)), []);
  check('[28] German reasons name no button', reasons.filter((r) => /Neu generieren/.test(de[r] || '')), []);
  const fig = src('frontend/src/tabs/characters/FieldFigure.tsx');
  const base = src('frontend/src/tabs/characters/FieldBaseBody.tsx');
  check('[28] wiring', [
    // Ruling A87: "full_body" when the front is made from the full-body reference, else the method.
    /else front_ref\["wanted"\]\["method"\]\)/.test(src('app/core/figure.py')),
    /data\.changes\.filter\(\(c\) => c !== frontChange\)/.test(fig),
    /line\('front', 'yellow',/.test(fig),
    /post\('base-body\/images', \{ view: 'front', force: true \}/.test(fig),
    /<FrontReferenceRow reference=\{info\.front_reference\} jobs=\{jobs\}/.test(base),
    /onRegenerate=\{\(\) => \{ void post\('images', \{ view: 'front', force: true \}\) \}\}/.test(base),
  ], [true, true, true, true, true, true]);
}

// [29] Ruling A87 — the full-body reference step, the same wording in the Base body and the Figure tab. Expected
// values by hand: one Generate = 1 image job; the plain body's follow-up is the front's Regenerate from [28]'s counts
// (2 image jobs + 7 hub jobs at the next Build while a base model is stored); an outfit's is the dressed views' image
// jobs (2 with front + back) while something is painted, else nothing.
{
  const fb = await loadBundled(join(ROOT, 'frontend/src/tabs/characters/fullBodyReferenceModel.ts'));
  const J = { view: 1, front: 2, model: 4, after_front: 7, model_followup: { jobs: 4, stages: ['mesh', 'upscale', 'face', 'rig'] } };
  check('[29] front from the full-body reference', m.frontRegenerate('full_body', J).label,
    'Regenerate front from the full-body reference — 2 image jobs + 7 hub jobs at the next Build');
  check('[29] Generate labels', [fb.generateLabel(false, 1), fb.generateLabel(true, 1)],
    ['Generate — 1 image job', 'Regenerate — 1 image job']);
  check('[29] base follow-up', fb.baseFollowup(J),
    'Then the front is due: Regenerate front from the full-body reference — 2 image jobs + 7 hub jobs at the next Build');
  check('[29] outfit follow-up', [fb.outfitFollowup(true, 2), fb.outfitFollowup(false, 2)],
    ['Then the dressed views are due with the next Build — 2 image jobs',
      'Nothing becomes due now: nothing is painted on this figure, so the picture is not used']);
  check('[29] Run all / Build notes', [fb.fullBodyBuildNote('base', false, 'reference'), fb.fullBodyBuildNote('base', false, 'text'),
    fb.fullBodyBuildNote('base', true, 'reference'), fb.fullBodyBuildNote('outfit', false)],
  ['Full-body reference: none — the front uses the profile image',
    'Full-body reference: none — no profile image, the front is made from text', '',
    'Outfit full-body reference: none — the dressed front is an edit of the body’s front']);
  const rec = { image: 'a.png', sha256: 'x', set_at: '2026-11-15T10:00:00+00:00', origin: 'generated' };
  const run = { running: false, started_at: null, error: null, failed_at: null };
  const rows = [
    fb.fullBodyRow('base', { record: null, gone: false, run }),
    fb.fullBodyRow('base', { record: null, gone: false, run: { ...run, running: true }, generate: { jobs: 1, source: 'profile' } }),
    fb.fullBodyRow('base', { record: rec, gone: false, run, front: { stored: true, current: false, source: 'full_body' } }),
    fb.fullBodyRow('base', { record: rec, gone: false, run, front: { stored: true, current: true, source: 'full_body' } }),
    fb.fullBodyRow('base', { record: rec, gone: true, run }),
    fb.fullBodyRow('base', { record: rec, gone: false, run: { ...run, error: 'no backend' } }),
    fb.fullBodyRow('outfit', { record: rec, gone: false, run, applies: false, note: 'n', label: 'Blue dress' }),
    fb.fullBodyRow('outfit', { record: rec, gone: false, run, applies: true, jobs: 2, label: 'Blue dress' }),
    fb.fullBodyRow('outfit', { record: rec, gone: false, run, applies: true, jobs: 0, label: 'Blue dress' }),
  ].map((r) => [r.light, r.state]);
  check('[29] rows', rows, [['grey', 'Not set'], ['blue', 'Generating'], ['yellow', 'Due'], ['green', 'Used'],
    ['red', 'Picture gone'], ['red', 'Failed'], ['grey', 'Not used now'], ['yellow', 'Due'], ['green', 'Used']]);
  check('[29] the same name in both places', [fb.fullBodyRow('base', { record: null, gone: false }).name,
    fb.fullBodyRow('outfit', { record: null, gone: false, label: 'Blue dress' }).name],
  ['Full-body reference', 'Full-body reference · Blue dress']);
  const de = JSON.parse(src('shared/languages/de.json')).translations;
  const tde = (k) => de[k] ?? k;
  check('[29] German', [fb.generateLabel(false, 1, tde), fb.fullBodyBuildNote('base', false, 'reference', tde)],
    ['Generieren — 1 Bild-Job', 'Ganzkörper-Referenz: keine — die Vorderansicht verwendet das Profilbild']);
  const tile = src('frontend/src/tabs/characters/FullBodyReferenceTile.tsx');
  check('[29] one tile in both places', [
    /<FullBodyReferenceTile /.test(src('frontend/src/tabs/characters/FieldBaseBody.tsx')),
    /<FullBodyReferenceTile /.test(src('frontend/src/tabs/characters/OutfitReferenceRow.tsx')),
    /createPortal\(/.test(tile), !/window\.(confirm|alert|prompt)/.test(tile)], [true, true, true, true]);
}

if (failures.length) {
  console.error(`\nFAIL (${failures.length})`);
  for (const f of failures) console.error(`  ${f}`);
  process.exit(1);
}
console.log('\nALL OK');
