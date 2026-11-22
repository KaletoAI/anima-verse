# Pair scene Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One running-scene layer for free pair poses and furniture actions — finale, gauges' hooks, tempo, channel readouts (live + estimate), lead role, quiet narration — with the meaning (gauges, thresholds) in the private intimacy package.

**Architecture:** A new core module `app/core/pose_scene.py` owns everything that today lives only in `prop_action_engine` (finale store, `begin_finale`, `finale_for`, meters, hold, the per-beat hook) keyed by a SCENE id (a furniture run's `execution_id`, a free pair's interaction id) and adds tempo, readouts and "end after the finale". Both engines call it; the package answers through providers and hooks. Clients get `tempo` + a server clip clock in the existing interaction payload.

**Tech Stack:** Python/FastAPI (core), TypeScript (client3d, `@anima/scene-render`, Game-Admin React), C#/Godot (`native/`), the private packs repo (`plugins/intimacy`, `plugins/nsfw_anatomy` — symlinks, own git repo `../anima-verse-packs`, branch `master`).

**Spec:** `docs/superpowers/specs/2026-11-22-pair-scene-design.md` and `../anima-verse-packs/docs/specs/2026-11-22-intimacy-pair-scene-design.md`.

## Global Constraints

- No package-content word, value or example in this repo's code, comments, docs, smokes or commit messages; neutral names only (scene, tempo, readout, finale, lead role, meter). Package content lives in the packs repo.
- Tempo range [0.2, 1]; 1 = the clip's own speed. Without a provider answer the tempo is 1.
- Animation time = REAL seconds; scene beat time = GAME seconds (`delta_game_s`), as `prop_action.active` today.
- Server computes, clients render: tempo and clip clock come from the server; client3d, the admin preview (`@anima/scene-render`) and `native/` apply them identically.
- No backward-compat shims: renamed hooks/providers are renamed in the package in the same task, old names removed.
- Every smoke derives its numbers by hand in its docstring; storage smokes `paths.init(<tmp>)` first; never `HEAD:` in a before-proof.
- Commit with `git commit -- <paths>` (shared work tree), never amend/stash; end messages with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Packs-repo changes are committed in `../anima-verse-packs`.
- Client bundles: `npm run build` (frontend → `static/game_admin/`), `npm run build -w client3d` (→ `static/client3d/`) are committed with the task that changes them.

## Review Focus

1. A scene whose interaction ends while a finale or a "end after" timer is pending → nothing ends a NEW interaction of the same people (timer bound to the scene id).
2. Readout reports from a client whose avatar is not in that room, or for an interaction that is over → dropped, never stored.
3. A world freeze during a scene → tempo clock and beats stop; clip clock does not jump on unfreeze.
4. A free-pair pose switch (`together_in`, commit 42ca7c4f3) mid-scene → the scene id stays, meters/finale/tempo continue.
5. Places preview with a character whose base body has no extension groups → no pose picker, no error, base body still the default body.

---

### Task 1: Places preview — pose pickers instead of the state picker, base body by default

**Files:**
- Modify: `app/core/extension_rig.py` (`motion_payload`: new `preview_poses` kwarg), `app/routes/figure.py` (new `GET /characters/{c}/base-body/pose-motion`; `extension.groups` in the plain payload carry `poses` + `preview_pose`)
- Modify: `frontend/src/tabs/poses/PlacePreview.tsx` (`BodyPick`), `frontend/src/tabs/characters/baseBodyModel.ts` (helpers)
- Packs: `plugins/nsfw_anatomy/plugin.yaml` (`preview_pose` on its group, value from the pack spec)
- Test: `scripts/smoke_place_preview_poses.py`, `scripts/smoke_place_picker.mjs` (extend)

**Interfaces:**
- Produces: `motion_payload(character_name, *, profile, apply_clothing, preview_states=(), preview_poses: dict[str, str] | None = None)` — `preview_poses` = `{group_id: pose_id}` applied like one synthetic state's `bone_pose`; unknown group/pose ignored.
- Produces: plain payload `extension.groups[i]` gains `poses: list[str]` (declared pose ids, sorted) and `preview_pose: str` (the group's declared `preview_pose` when it names a declared pose, else "").
- Produces: `GET /characters/{c}/base-body/pose-motion?poses=<group>:<pose>,…` (admin) → `{poses, motion}`; 400 on an undeclared pair.
- Produces (TS): `Assignment` becomes `{ character, role, body, poses: Record<string,string> }` (`state` removed; place memory stores `poses`).

- [ ] Step 1: smoke `smoke_place_preview_poses.py` — with a fake declared group `{id: "g1", poses: {"up": {"rest_deg": 80}}, preview_pose: "up"}` (monkeypatched `declared_motion_groups`): (a) `motion_payload(..., preview_poses={"g1": "up"})` rest angle of g1 == 80; (b) `preview_poses={"g1": "nope"}` == the rest payload; (c) the plain payload lists `poses == ["up"]`, `preview_pose == "up"`; (d) the route answers 400 for `g1:nope`.
- [ ] Step 2: run it, expect FAIL (kwarg/route missing).
- [ ] Step 3: implement the kwarg, the payload fields and the route.
- [ ] Step 4: UI — `BodyPick` drops the state select; for a base body it shows one select per group with `poses.length` ("Rest" + pose ids), pre-selected `preview_pose`; motion from the new route. A new figure's body is `'base'` when its plain body is built (`plain[c] !== null`), else `'outfit'` (default fill, manual pick and Fill all). Strings English, `t()`.
- [ ] Step 5: packs — add the group's `preview_pose` (pack spec); commit there.
- [ ] Step 6: run the smoke + `node scripts/smoke_place_picker.mjs` + `cd frontend && npm run lint && npm run build`; expect PASS / 0 errors.
- [ ] Step 7: commit (core + `static/game_admin`), commit packs.

### Task 2: Lead role on pose entries

**Files:**
- Modify: `app/core/pose_catalog.py` (normalize `lead_role`), `app/routes/poses.py` (accept/validate on POST/PUT), `frontend/src/tabs/poses/PosesTab.tsx` (field), new boot migration `app/core/pose_lead_role_migration.py` wired in `app/server.py` boot migrations
- Packs: `plugins/intimacy/register.py` + new provider in `plugins/intimacy/pair_poses.py`
- Test: `scripts/smoke_pose_lead_role.py`

**Interfaces:**
- Produces: catalog entry field `lead_role: str` — "" or a role in `ROLES[:participants]`; solo poses always "". Invalid on write → 400.
- Produces: `pose_catalog.lead_role_of(pose_key: str) -> str` — the stored role, else role "a" for a multi-person pose, "" for solo.
- Produces: provider `pose.lead_role_default(pose_key: str, roles: list[str], role_gender: dict[str, str]) -> str` (multiple=False); the migration asks it once per multi-person pose without `lead_role` (WORLD layer write for world entries, shared file for shared ones — same store the editor writes), using the role_gender of the pose's `animation` clip; empty answer → nothing stored.

- [ ] Step 1: smoke — catalog with a pair pose without `lead_role` and a fake provider returning "b": after the migration `lead_role_of == "b"`; a second run changes nothing (returns 0); without provider `lead_role_of == "a"`; PUT with `lead_role: "c"` on a pair → 400; solo pose → `""`.
- [ ] Step 2: run, FAIL. Step 3: implement. Step 4: PosesTab select "Lead role" (only `participants > 1`; options "— (a)", a, b, …) sent in the PUT/POST body.
- [ ] Step 5: packs provider (rule in the pack spec: the lead is the role `role_gender` gives the gender the pack names).
- [ ] Step 6: run smoke, lint, build. Step 7: commit both repos.

### Task 3: `pose_scene` — finale, meters, hold for every scene (moved out of `prop_action_engine`)

**Files:**
- Create: `app/core/pose_scene.py`
- Modify: `app/core/prop_action_engine.py` (finale/meters/hold/beat delegate; old code removed), `app/core/world_ops.py:1075` (`pose_scene.finale_for`), `app/routes/prop_actions.py` (hold/alt unchanged URLs, call the module), `app/routes/play.py` (new `POST /play/interact/hold`, `POST /play/interact/alt`; `/play/self`/`/play/scene` interaction block gains `meters`), `packages/player-ui/src/ScenePanel.tsx` + `pairActions.tsx` (meters row + hold + alt for a free pair, same component the furniture row uses), `frontend/src/tabs/poses/ClipLibrary.tsx` (loop-count field shown for finale clips without the Loop switch)
- Packs: `plugins/intimacy/register.py`, `finale.py`, `pair_poses.py` (hook/provider renames)
- Docs: `docs/skill-core-api.md` (hooks/providers table), `docs/schnittstellen-3d.md` ` A8c
- Test: `scripts/smoke_pose_scene_finale.py`; existing `smoke_prop_action_*` must stay green

**Interfaces:**
- Produces (renames, old names removed): hook `scene.active(scene_id, kind, members, roles, pose_key, lead_role, delta_game_s, readouts)` (replaces `prop_action.active`; `kind` = `"interaction"` | `"prop_action"`; `roles` = `{role: name}` or `{}` solo; `readouts` filled from Task 6, `[]` until then); hooks `scene.finale_started(scene_id, name, kind, pose_key)`, `scene.finale_done(scene_id, name)`; providers `scene.meters(scene_id, members, pose_key)`, `scene.meter_hold(scene_id, name, hold)`.
- Produces: `pose_scene.begin_finale(scene_id: str, name: str, *, tempo: float = 1.0) -> dict` (`{ok, reason}`; reasons as today + `"no_scene"`); the finale's real length = clip length × cycles / tempo; `finale_for(name)` block gains `tempo`.
- Produces: `pose_scene.end_after_finale(scene_id: str, name: str, delay_s: float) -> bool` — ends the scene (`end_interaction(..., interaction_id=…)` / `prop_action_engine.cancel`) `delay_s` REAL seconds after that person's finale has fully played; a scene that ended or changed id meanwhile is left alone.
- Produces: `pose_scene.meters(scene_id) -> list[dict]`, `pose_scene.hold(scene_id, name, hold) -> dict`, `pose_scene.scene_of(name) -> dict | None` (`{scene_id, kind, members, roles, pose_key}` from the running interaction or furniture run).
- Produces: `pose_scene.advance(now: GameTime) -> int` — beats for free-pair interactions (furniture beats come from `prop_action_engine.advance` through `pose_scene.emit_active(...)`); called next to `engine.advance` in `travel_engine.py:2355` and `periodic_jobs.py:599`.

- [ ] Step 1: smoke — a free pair (two profiles with one interaction blob, fake finale clip sidecar `duration_s 1.2, loop_count 3`): `begin_finale(id, "A", tempo=0.5)` ok, `finale_for("A").duration_s == 7.2` (1.2·3/0.5), a second call → `finale_playing`; `end_after_finale(id, "A", 3)` ends the interaction 10.2 s after start (fake clock), and does NOT end a new interaction started after the old one ended; `advance` emits one `scene.active` with `kind "interaction"` and `delta_game_s` = game time since the last beat; a frozen world emits none.
- [ ] Step 2: run, FAIL. Step 3: implement the module; move the furniture code over; rename hooks in the package (same behaviour); remove the old names.
- [ ] Step 4: UI — free pair shows the same meters row/hold/alt as a furniture action; ClipLibrary shows the count field for clips used as `finale_animation` (or always for one-shots, labelled "Times played as a finale").
- [ ] Step 5: run the new smoke + every `scripts/smoke_prop_action_*.py`, `smoke_interaction*.py`, `smoke_follow_pose.py`; lint; builds.
- [ ] Step 6: docs; commit core (+ bundles), commit packs.

### Task 4: Tempo and the server clip clock

**Files:**
- Modify: `app/core/pose_scene.py` (tempo + clock), `app/core/interaction_engine.py` (`payload_for` fields), `client3d/src/game/pairClip.ts`, `client3d/src/scene/npcs.ts` (`adoptInteraction`/`tickInteraction`), `native/Core/Figures/PairClip.cs` (+ its caller), `docs/schnittstellen-3d.md` ` A8a
- Test: `scripts/smoke_pose_scene_tempo.py`, `client3d/scripts/smoke_pair_clip_tempo.mjs`, a `native/Check` case

**Interfaces:**
- Consumes: provider `scene.tempo(scene_id, members, roles, pose_key, lead_role) -> float | None`.
- Produces: per scene a clip clock `clip_s` integrated on every beat and on every payload read: `clip_s += Δreal_unfrozen · tempo_previous`; `tempo` refreshed each beat, clamped to [0.2, 1], 1 without provider/answer; reset to 0 on a pose switch.
- Produces: interaction payload gains `tempo: float` and `clip_s: float`; clients advance `clipT += dt · tempo` (frozen: 0) and snap to `clip_s` beyond `PAIR_SNAP_S`; `elapsed_s` stays for everything else. Same id + same clip never restarts the blend.

- [ ] Step 1: smokes — Python: provider answering 0.2 then 1.0 across two beats 10 s apart: `clip_s` = 2.0 after the first span, +10 after the second; answer 5 → 1; answer None → 1; freeze 30 s → `clip_s` unchanged. JS: `pairClipPhase` with `tempo 0.5`, `dt 1` advances `clipT` by 0.5; snap when server `clip_s` differs by > `PAIR_SNAP_S`.
- [ ] Step 2: FAIL. Step 3: implement server, client3d, native. Step 4: run smokes + `npm run build -w client3d` + native check. Step 5: docs, commit.

### Task 5: Channel readouts to the server

**Files:**
- Modify: `packages/scene-render/src/channelReadout.ts` (+ `partRadiusM` = largest surface radius of the links inside, 0 when none), its README row
- Create: `client3d/src/game/readoutReports.ts` (≤ 1 report/s per key: mean `insertionOfDepth`, mean `partRadiusM`, `restRadiusM`, `depthM`, count of frames where `insertionOfDepth ≥ 1` starts — a "reach" edge — since the last report)
- Modify: `client3d/src/scene/npcs.ts` (feed the reporter), `app/routes/play.py` (`POST /play/scene/readouts`), `app/core/pose_scene.py` (store + hand to `scene.active`)
- Test: `scripts/smoke_scene_readouts.py`, `client3d/scripts/smoke_readout_reports.mjs`, extend the scene-render channel readout smoke

**Interfaces:**
- Produces: route body `{scene_id, readouts: [{receiver, channel, entering, insertion_of_depth, part_radius_m, rest_radius_m, depth_m, reaches}]}`; accepted only when the user's avatar is in the scene's room (or admin) and the scene is live; ≤ 1/s per (scene, receiver, channel, entering), extra dropped; 200 `{accepted: n}`.
- Produces: `pose_scene.readouts(scene_id) -> list[dict]` — the latest per key no older than `READOUT_FRESH_S = 5`, each with `source: "client"`; `reaches` summed since the previous beat.

- [ ] Step 1: smokes — accepted/dropped cases (foreign room 403-free drop → `accepted 0`, ended scene → 0, second report within 1 s → 0); freshness 5 s; `reaches` summed then reset per beat. JS: reporter emits once per second with the hand-computed means and edge count.
- [ ] Step 2: FAIL. Step 3: implement. Step 4: run, builds. Step 5: commit.

### Task 6: Readout estimate without a client

**Files:**
- Modify: `frontend/src/tabs/poses/PlacePreview.tsx` ("Measure channel profile" button on a pair place: one clip cycle of the frame readouts → PATCH), `app/routes/assets.py` + `app/core/animation_clips.py` (sidecar field `channel_profile`), `app/core/pose_scene.py` (estimate)
- Test: `scripts/smoke_scene_readout_estimate.py`

**Interfaces:**
- Produces: sidecar `channel_profile: {channel: {"share_max": float, "reaches_per_cycle": int}}` per clip kind (share of the entering chain's length inside at the deepest frame; how many reach edges one cycle had on the measuring figures); `set_clip_channel_profile(library, rel, value)` like `set_clip_loop_count`.
- Produces: `pose_scene.estimate_readouts(scene_id) -> list[dict]` with `source: "estimate"`: per profiled channel, using the receiver's collision record (channel `depth`, rest radius `R`) and the entering figure's attached part (length `L`, surface radius `r`): `insertion_of_depth = share_max · L / depth`, `part_radius_m = r`, `rest_radius_m = R`, `depth_m = depth`, `reaches = reaches_per_cycle · cycles since the last beat` (cycles from `clip_s`) when `share_max · L ≥ depth`, else 0. Missing record or profile → no entry. `readouts()` falls back to the estimate per key without a fresh client report.

- [ ] Step 1: smoke with hand numbers (depth 0.15, R 0.017, L 0.16, r 0.02, share_max 0.95 → insertion 1.0133, reaches counted; share 0.8 → 0.853, reaches 0); missing profile → [].
- [ ] Step 2: FAIL. Step 3: implement (button: English label, `t()`). Step 4: run, lint, build. Step 5: commit.

### Task 7: Quiet narration

**Files:**
- Modify: `app/core/perception.py` (`record_utterance(..., quiet: bool = False)` → utterance meta `quiet: true`), `app/models/perception_store.py` (chat-view readers exclude `json_extract(u.meta,'$.quiet')` when asked: new kwarg `include_quiet=True` default, chat routes pass False), `app/routes/play.py` (`/play/scene` reader at `~281` and `~2392`), Game-Admin chat readers (find every caller that renders a player/admin chat transcript), `app/core/interaction_engine.py` + `app/core/prop_action_engine.py` (start / switch / end lines pass `quiet=pose_scene.quiet(pose_key)`)
- Test: `scripts/smoke_quiet_narration.py`

**Interfaces:**
- Consumes: provider `scene.quiet_narration(pose_key: str) -> bool` (multiple=True, any True = quiet).
- Produces: `pose_scene.quiet(pose_key) -> bool`.

- [ ] Step 1: smoke — a quiet start line is in `get_character_room_stream(...)` (prompt view) and absent from the `/play/scene` transcript; a non-quiet pose's line is in both; invitations stay in both.
- [ ] Step 2: FAIL. Step 3: implement. Step 4: run + `smoke_chat_prompt_order.py`, `smoke_sync_writers.py`. Step 5: commit.

### Task 8: The package rules (packs repo)

**Files (packs):** `plugins/intimacy/` (finale, register, admission, plugin.yaml settings) and its tests under `../anima-verse-packs/tests/`. Rules, settings, defaults and the hand-derived test numbers: `../anima-verse-packs/docs/specs/2026-11-22-intimacy-pair-scene-design.md` ("Rules", "Settings") — this core plan does not repeat package content.

**Interfaces:**
- Consumes: `scene.active` (with `readouts`), `scene.tempo`, `scene.quiet_narration`, `scene.meters`/`scene.meter_hold`, `pose_scene.begin_finale(..., tempo=…)`, `pose_scene.end_after_finale`, `pose_catalog.lead_role_of`.

- [ ] Step 1: pack tests with the numbers derived by hand from the pack spec (base rate, width factor at both clamps, per-channel weight on rate AND bonus, reach bonus per edge, no readout = plain rate, tempo at the lead member's 0 / 50 / 100 %, the closing sequence for an ending member and the go-on for any other member).
- [ ] Step 2: FAIL. Step 3: implement. Step 4: run pack tests + core smokes of Tasks 3–7. Step 5: commit packs.

### Task 9: End-to-end check and docs

- [ ] Step 1: in the Anima-Divide clone world (not the original), run a free pair and a furniture pair with the 3D client: tempo rises, meters fill, the finale plays 3× at 0.5, the scene ends 3 s later, chat shows no start/end line but the storyteller's closing line. Record numbers (tempo per beat, meter values) from `logs/main.log` debug lines.
- [ ] Step 2: `docs/skill-core-api.md` (pose_scene API, providers/hooks), `docs/schnittstellen-3d.md` (A8a tempo/clip_s, A8c finale tempo), README feature line; `scripts/smoke_docs_*.py` green.
- [ ] Step 3: commit.
