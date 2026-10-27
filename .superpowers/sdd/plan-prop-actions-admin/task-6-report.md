# Task 6 implementation handoff

BASE `060a42eb`; approved worktree `/home/dev/projekte/anima-verse/.claude/worktrees/props-actions-admin`, branch `feat/props-actions-admin`. This report is included with the explicitly staged implementation; the final handoff supplies the resulting commit hash.

**Evidence boundary:** implementation and deterministic acceptance/scenario drivers are prepared. This worker ran no tests, builds, linters, formatters, smoke/scenario commands, HTTP server, model, media job, live-world access, restart or deployment. No RED/GREEN observation, passing count, exercised HTTP result or playable-client proof is claimed. Controller verification is required.

## Core and exact HTTP contracts

- `prop_actions.offers(actor)` resolves actual current-room recipe placements, current stable variant/revision, authored actions, descriptions/effects, exact target and partner-specific enabled/blocked reasons. It calls the real executor's read-only `check`, not a separate permissive rules implementation or a trial `request`.
- The authoritative `_plan` now checks the actual measured entry transition before accepting an execution/reserving anything, not only after walking. `_entry_spec` shares the existing discovered solo-kind capability set and rejects pair metadata, paired-only A/B files, absent/unusable duration, mismatching measured travel or blocked entry geometry. This same seam governs offers, admin checks, requests and real entry. Default missing walking-to-pose rules expose `missing_entry_transition`; no fake/default intro was installed.
- Current room authorization is checked before resolving a caller-supplied target's scene, preventing foreign scene/revision existence probing. Actor-scoped exact nonce replay remains prior to that check, preserving legitimate replay after the participant has moved.
- Hard requirements/presence are always rechecked during approach/entry. During activity/sleep they are rechecked when the existing configured interruption policy requests it; structural revision/ownership/availability checks remain authoritative independently. Sleeping bystanders count in the whole-room census; sleeping partners cannot join.
- `prop_action_engine.state_for(actor)` returns only own `{incoming,outgoing,current,recent_results}` with required execution/action/revision/label/target/participants/roles/status/phase/reason/respond/cancel fields. Incoming uses the exact recipient. Terminal own results/effects expire from projection after 30 system minutes, not game time. Semantic actor/partner and physical clip/access roles remain distinct.
- Targeted sync invalidation uses only participating avatars' `self`/`scene` topics after commit and existing outer-lock deferral. Invitations/results are not broadcast as public payloads.
- New `app/routes/prop_actions.py` is registered by `server.py`. Player routes are exactly `GET /play/prop-actions`, `GET /play/prop-actions/state`, and `POST /play/prop-actions/request`, `/respond`, `/cancel`.
- Request payload is `{target,action_id,revision,partner?,request_id?}`; respond is `{execution_id,accept:bool}`; cancel is `{execution_id}`. Strict typed payloads forbid extra fields, including actor selection. Actor comes from a fresh explicit lookup of the authenticated user's current authorized avatar, not a body/query actor or global account fallback.
- Explicit admin-only routes: `POST /world/props/{id}/validate` with `{document}` (issues plus placement `not_checked`); `POST /world/props/{id}/check-placement` with saved request identity plus selected actor; separate `POST /world/props/{id}/execute-test` additionally requires strict `confirmed:true`. Real execution calls the normal executor and still asks for exact pair consent. No admin consent bypass or second executor was added.
- Refused player operations use HTTP 409, unauthorized recipient/participant use 403, malformed payloads use 422. An actual run that becomes terminal while answering consent remains a real state-machine result rather than fabricated refusal/success.

## Production read-only composition, not only fixture isolation

The previously observed lazy scene side effects are addressed in production code:

- Explicit bounded `read_only` options propagate through `scene_inputs`, `get_client_meta`, `compose_scene`, its actual prop/problem readers, `compose_recipe`, placement/scatter joining and `props.get_prop`/`_prop_record`.
- Prop read-only records do not persist lazy bbox measurement or demand LOD. Filename-only `_stem_of` resolution now reads sidecars without UID persistence; otherwise a nested gallery/source/surface lookup could bypass the top-level read-only flag.
- Read-only scene composition skips visual door/window model generation while keeping real room hulls, wall openings, surfaces, dimensions, support transforms, markers and collision geometry. No global monkeypatch or fake geometry replacement is used in production.
- Places' actual composer and room-standing collision reader use that no-build path. Admin checks and offers therefore also remain safe on cold production geometry, not merely under the older fixture's disabled media workers.
- `read_sidecar(...,read_only=True)` prevents author normalization writes on these paths. Ordinary author reads retain their previous normalization behavior.
- Server lifespan registers the actual prop journey owner, logs a dry migration inventory, refuses invalid/unreadable inventory, and applies valid idempotent world-store normalization before runtime jobs. No Shared source-asset write or live-world activation was performed by the worker. The branch still requires the later client cutover before deployment.

## Actual LLM/tool consumers

- The already enabled `set_pose` package now declares a second real executable capability `prop_action`, implemented in `plugins/set_pose/skill_prop_action.py`, with a real `PropAction` descriptor. This deliberately avoids a new separately disabled package ID that would leave current worlds with prompt-only/non-executable hooks. Existing package activation, per-character enablement, manager discovery and rule/cost gates remain the conventions; no fake Hook/no-op was introduced.
- Bound `as_tool(character_name=...)` wrappers overwrite actor identity and discard ordinary trusted chat wrapper metadata before strict semantic payload validation. The actual request/cancel implementation calls the same Core used by HTTP. Exact-execution-ID InteractWith answers from Task5 remain unchanged.
- `places.room_offer` contains the real semantic action block plus free-body/room-marker poses; prop markers no longer advertise every pose in their group. Short room selection summaries also stop representing furniture as unchecked raw pose capacity.
- Shared `chat_moment`, both thought templates and `tasks/npc_action` explicitly render `prop_actions_block`. It includes current IDs/revisions/exact targets, enabled/blocked reasons, exact enabled partners, real effect timing/amounts and executable request/cancel/consent signatures.
- Chat no longer computes semantic tool context only when the legacy activity-marker flag is on. The flag retains its marker-syntax purpose; semantic action context is independent.
- Effective Shared/World rendering goes through the existing overlay loader. Mandatory actor context is checked. If an override omits the real runtime block, its custom text is preserved, a warning identifies the missing mandatory field, and the renderer appends the actual block instead of silently omitting it. Existing room-offer snapshots are reused to avoid repeating the planner unnecessarily.
- `npc_actions.prompt_vars` supplies actual semantic context. Structured `{prop_action:<same payload>}` answers execute the installed skill/Core before any implicit pose/room/status adoption. A proposal cannot simultaneously move rooms or execute unrelated pose/say/pair/action fields. No parallel consent engine exists.
- Implicit `**I do**` adoption and actual automatic chat-context pose extraction do not interrupt an owned semantic action. This also protects later narration while an explicit action owns the body, not just its first turn. Explicit pose tools, movement and cancellation retain their existing authority. Unrelated stat/outfit extraction remains available.
- Raw solo/pair automatic allocation excludes prop markers; explicit preferred prop poses are rejected before pose interruption or waking. Free body poses and room-owned marker behavior remain. Existing general temporary Together auto-yes was not changed.

## Public local motion contract for Task9

`worldmap.characters[].local_approach` is nullable and contains public same-room motion only:

```
{journey_id, room_id, waypoints, progress_m:0, walked_m, remaining_m,
 paces_m_s_real, starts_in_s}
```

Waypoints are the remaining world-XZ polyline starting at the current interpolated position. `progress_m` is relative to that trimmed path; `walked_m` is already walked local distance. Segment paces correspond to the remaining segments. Pending/frozen movement has no extrapolatable pace. Projection requires an actually visible/addressable foreign character in the same current room, exact live approach ownership and current valid room geometry for every segment. It includes no target, execution/consent identity, partner, overland segment or foreign room. Sight/room/ownership/route loss yields null. Task9 clients must clear their cached local path when it disappears. Existing foreign overland travel remains thinned.

## Prepared acceptance and consumer updates

New `scripts/smoke_prop_action_api.py` uses private storage **and** instance roots before world imports, privately copied complete shipped template/config/terrain/filter/stat/rule/language catalogs, actual profiles/DB/scene/route/claims/executor, actual sessions/users/auth middleware/routers, actual Shared/World renderers and real loaded skill/streaming execution.

Prepared cases include:

1. Missing/paired-only/pair-metadata entry capability blocks both offers and requests with no claims or profile changes.
2. Real cold read-only scene/author/admin checks compare logical DB/file snapshots and tripwire actual bbox/LOD/door/window/surface generation boundaries, rather than substituting successful geometry.
3. Anonymous/user/admin authorization, forbidden body actor, ignored query actor selection, foreign scene tripwire, stale revision, invalid partner, exact actor/parameter nonces, exact incoming recipient, two-player acceptance/decline/cancel, reload, outsider privacy, 30-system-minute expiry.
4. Admin checks do not execute; false confirmation refuses; true confirmation creates the normal awaiting-consent pair without claims.
5. Actual rendered Chat/thought/in-chat/NPC prompts for available, blocked and empty rooms, with both activity-marker states; real World override preservation/mandatory-block repair; exact target/reason/effects assertions.
6. Captured external model tool text passes the real tool-format parser, loaded skill, skill gate and streaming `_execute_tools`, then the actual marker and automatic chat-context postprocessing, then the real executor through entry/prepare/drink to one actual 15-point success receipt. Pose narration cannot cancel its run; explicit pose change still cancels.
7. Actual NPC structured-action response through its real renderer/loaded skill/executor to effects, not a Hook echo.
8. Presence includes a sleeping non-slot bystander; unavailable actions and raw prop-pose HTTP refusals do not wake or move sleeping figures. HTTP requirement reasons distinguish unknown reference, unreadable actor stat and unmet comparison; approach loss always stops and active loss follows configured interruption.
9. Normal authenticated `/play/worldmap` without `all=1`: local visible owned approach around furniture bends, private question exclusion, foreign travel thinning, and projection withdrawal on room/visibility/owner loss.

Only external model/response workers are substituted/captured by the deterministic fixture; real Core results, profiles, path ownership, consent and effects are not echoed or mocked successful.

Existing lifecycle fixture now authors a measured entry by default because requests honestly reject a missing bridge before walking; the dedicated missing-transition case now expects immediate refusal and unchanged position. The previous path-departure fixture explicitly seeds a historical persisted seat rather than invoking the removed raw-pose prop allocator. Room-marker offer/cap regressions are retained while obsolete prop-wide raw-pose expectations are removed. Synthetic prompt regression consumers now supply mandatory actor context and initialize private instance/schema where the renderer's real action/state reads need it.

Existing product documentation updated: `docs/schnittstellen-3d.md`, `docs/llm-templates.md`, and the SetActivity descriptor. No original checkout, importer recovery, live world, secret or client code was changed.

## Exact controller commands

From the approved worktree:

```sh
./.venv/bin/python scripts/smoke_prop_action_api.py
./.venv/bin/python scripts/smoke_auth_gate.py
./.venv/bin/python scripts/smoke_prop_action_runs.py
./.venv/bin/python scripts/smoke_prop_action_paths.py
./.venv/bin/python scripts/smoke_prop_action_effects.py
./.venv/bin/python scripts/smoke_prop_action_migration.py
./.venv/bin/python scripts/smoke_places.py
./.venv/bin/python scripts/smoke_room_stand.py
./.venv/bin/python scripts/smoke_interaction.py
./.venv/bin/python scripts/smoke_npc_actions.py
./.venv/bin/python scripts/smoke_npc_home.py
./.venv/bin/python scripts/smoke_npc_conversation.py
./.venv/bin/python scripts/smoke_intent_undertaking.py
./.venv/bin/python scripts/smoke_decision_invites.py
./.venv/bin/python scripts/smoke_chat_prompt_order.py
./.venv/bin/python scripts/smoke_thought_focus.py
./.venv/bin/python scripts/smoke_daily_rhythm_lookahead.py
./.venv/bin/python scripts/smoke_commitments_into_intents.py
./.venv/bin/python scripts/smoke_reply_shape.py
./.venv/bin/python scripts/smoke_game_weather_prompts.py
./.venv/bin/python scripts/smoke_stat_boosts.py
./.venv/bin/python scripts/smoke_stat_activity_tick.py
./.venv/bin/python scripts/smoke_scene_recipe.py
./.venv/bin/python scripts/smoke_scene_prop_lookups.py
./.venv/bin/python scripts/smoke_furnish_findings.py
```

Actual non-unittest temporary HTTP/prompt/tool/effect driver:

```sh
./.venv/bin/python scripts/smoke_prop_action_api.py --api-scenario-dir /tmp/prop-actions-task6-http-prompt-001
```

Use a never-existing directory. This branch starts a minimal real ephemeral loopback HTTP app, not production `app.server` lifespan. It performs authenticated GET, actor-spoof refusal, real HTTP request/nonce replay/cancel, actual rendered prompt consumption and captured external-model tool text through the real parser/streaming/skill/postprocessing, then advances the real executor through effectful completion. It retains private DB/instance/catalog data and `api-prompt-scenario.json` with actual HTTP results, effective prompts, tool events/result, extraction prompts, final run state/value and real effect receipts. The worker did not exercise it.

Existing deeper process scenarios remain controller regressions:

```sh
./.venv/bin/python scripts/smoke_prop_action_runs.py --scenario-dir /tmp/prop-actions-task6-lifecycle-001
./.venv/bin/python scripts/smoke_prop_action_effects.py --scenario-dir /tmp/prop-actions-task6-effects-001
```

## Concerns / evidence limitations

- All checks/scenarios above remain unexecuted by this worker, by assignment. Controller must run them and review the commit before treating acceptance as observed.
- Deterministic fixture FBX bytes are not playable-media evidence. Parent's separate private `playable-fixture/clips/fixture-sit-down.{fbx,json}` was not installed, published or replaced by this task. Default real entry rules remain honestly blocked until real compatible media/rules are configured; actual browser/native validation remains Task9/10.
- Runtime/API/tool implementation is on this branch only. Do not deploy its intermediate state before remaining admin/client cutover tasks land.
- No automatic replacement of an already owned semantic execution was invented: explicit cancel/stop or explicit movement/pose remains the authoritative interruption before requesting a different semantic run.

## Fix round 1/5 — production defaults, startup order, gates and NPC override envelope

Fix BASE `9e826233`. The resulting scoped commit is supplied in the final handoff.
The original implementation narrative above is historical where superseded here.

### Controller evidence accepted, not rerun

Independent review `agent://ApiPromptsReview` reported five production findings
and the measured-entry receipt-recovery fixture defect. Controller ran API
**10 tests / 2 failures** (`artifact://154`) and lifecycle **31 / 1 failure**
(`artifact://157`). The failed arrival row already showed actual receipt recovery,
the participant at floor access, `approaching/entry`, measured two-second duration,
and zero elapsed entry time; another advance at the same clock was correctly not
activation. This runtime observation was accepted, not repeated.

Controller reported auth gate, paths **23**, effects **29**, places, room standing
and interaction passed (`artifact://159`). NPC/home/conversation/undertaking/
decision/chat-order/thought-focus passed before the daily-rhythm wording failure
(`artifact://158`). Commitments/reply-shape/weather passed before the obsolete
scene-version pin (`artifact://160`); lookup **13** and furnishing passed.
These are observations for the initial commit, not GREEN evidence for this fix.
The real HTTP/prompt/tool/effect scenario was not reached by the failed API chain.

This worker ran **no tests, builds, linters, formatters, scenario/server/model/
media commands or failure-confirmation probes** in this fix round.

### Applied root-cause corrections

1. **Existing-character activation:** `PropActionSkill.default_enabled_for`
   supplies its intended enabled package/global-skill runtime default. Manifest
   `always_load` no longer substitutes for activation; explicit per-character
   `enabled:false` remains the manager's first decision, and generic rules/cost
   blocks still filter the actual executable tool. No character override file
   is written merely to obtain this default; unrelated ALWAYS_LOAD skills retain
   their existing policy.
2. **Actual startup prerequisite chain:** `prop_action_migration.prepare_runtime`
   is the single production preparation used by lifespan before jobs. It runs
   stable marker/placement-ID migration, variant-field migration and place-group
   normalization in order, then performs dry action inventory and real application
   and registers the owner. The premature early inventory and duplicate later
   dry-only startup block were removed. Invalid post-prerequisite data still
   refuses startup visibly; supported legacy data gets its existing repair first.
3. **Player gate and successful-call cost:** player request uses the existing
   `_player_action_gate` declaration lookup before Core and the existing `charge`
   boundary only after an accepted nonfailed request. Rule/cost refusal is 403;
   a semantic Core refusal raises before charging. Accepted pair questions remain
   `awaiting_consent` with no claims: a cost never acts as consent. Respond/cancel
   endpoints remain free and retain exact participant authorization.
4. **Structured tool failures:** the shared `streaming.is_error_result` predicate,
   already consumed by `run_gated`, now recognizes dict/serialized-JSON explicit
   failures (`success:false`, `ok:false`, nonempty `error`, or failure status
   `refused`/`failed`/`error`) as well as legacy Error/Fehler prose. PropAction
   retains its machine-readable JSON result unchanged. Refused stale/claimed/
   invalid requests can no longer be mistaken for successful cost-bearing calls.
   This is the existing failure boundary, not an offer-only or PropAction-only
   exception; successful/terminal cancellation is not automatically a failure.
5. **NPC-specific effective override contract:** the mandatory NPC renderer block
   now also includes structured `npc_action_request_shape` and
   `npc_action_cancel_shape` envelopes with top-level `prop_action`, exact target
   field shape and request/cancel operation. The NPC director is explicitly told
   not to emit bare tool payloads/tool syntax or a simultaneous pose/room change.
   This consumer-specific shape is enforced together with the common action block
   even when World replaces the whole task template. The formerly Shared-only
   duplicate instruction was removed.
6. **Measured receipt recovery:** the lifecycle regression now asserts actual
   recovered receipt/participant arrival, exact floor access, no premature place,
   `approaching/entry` and zero entry elapsed; it then advances the actual stored
   measured interval and asserts real active body placement/owned execution ID.
   No runtime entry duration or recovery guard was weakened.
7. **Obsolete snapshots deleted, not repinned:** removed the unrelated literal
   decision-prose snapshot from `smoke_daily_rhythm_lookahead.py`; its real daily
   schedule/lookahead checks remain. Removed only the old code-version-18 pin
   from `smoke_scene_recipe.py`; its real baked-surface and geometry assertions
   remain. No production wording/version was changed to satisfy either snapshot.

### New meaningful boundary regressions, prepared but not run

- Existing actor with no skill override: actual manager exposure without writing
  an activation file; explicit disable hides it; explicit enable plus a persisted
  real skill-block rule still hides/refuses it with no claims or stat spend.
- Real HTTP stale refusal leaves 50; accepted request spends configured five to
  45; cost shortfall refuses without changing the real run/profile; cancellation
  still works. A paid actual pair request remains pending/no claims until the
  real recipient's HTTP response, and response does not charge again.
- Captured tool text passes the actual parser, loaded bound skill, streaming tool
  executor and generic gate. A stale serialized refusal costs zero; a real
  accepted request spends five; the following real participant-claimed refusal
  remains structured JSON and spends nothing further.
- The actual NPC structured/effectful execution case now replaces the entire
  task with a genuine World override that knows no semantic fields. It checks the
  repaired *rendered* JSON envelope/target structure, preserves custom World text,
  and dispatches the captured external model response through the real NPC skill/
  executor to the real 50→65 success value.
- A fresh private subprocess creates an authentic raw legacy sidecar with
  animation-based markers lacking IDs and prop-level fields. It invokes the exact
  production `prepare_runtime` function, checks actual persisted stable marker IDs
  and binding references/action data, repeats to prove zero further action writes,
  and checks unchanged actor position/no claims. It never imports or starts full
  production lifespan/jobs and never uses live storage.

Product contracts updated in `docs/schnittstellen-3d.md`, `docs/llm-templates.md`
and the existing `docs/skill-core-api.md`. No original checkout, live world,
unrelated asset preparation, deployment or restart was touched.

### Exact controller commands for the fix

Run from the approved worktree:

```sh
./.venv/bin/python scripts/smoke_prop_action_api.py
./.venv/bin/python scripts/smoke_prop_action_runs.py
./.venv/bin/python scripts/smoke_auth_gate.py
./.venv/bin/python scripts/smoke_stat_skill_gate.py
./.venv/bin/python scripts/smoke_stat_skill_costs.py
./.venv/bin/python scripts/smoke_daily_rhythm_lookahead.py
./.venv/bin/python scripts/smoke_scene_recipe.py
./.venv/bin/python scripts/smoke_prop_action_paths.py
./.venv/bin/python scripts/smoke_prop_action_effects.py
./.venv/bin/python scripts/smoke_prop_action_migration.py
```

Then run the actual non-unittest HTTP/prompt/tool/effect driver with a
never-existing destination:

```sh
./.venv/bin/python scripts/smoke_prop_action_api.py --api-scenario-dir /tmp/prop-actions-task6-fix1-http-prompt-001
```

The broader existing NPC/chat/rendering/geometry command chain earlier in this
report remains applicable. No fix-commit passing count or actual scenario result
is claimed by the worker.

## Fix round 2/5 — nonce/cost idempotency and deterministic extraction completion

Fix BASE `a7e93525`; resulting scoped commit is supplied in the final handoff.

### Controller evidence accepted without rerunning

`agent://ApiFixReview` accepted production findings 1, 2, 4 and 5 plus measured
entry fixture 6. It identified the remaining positive-cost nonce interaction:
an exact HTTP replay was charged again, or refused by depleted funds before
Core could return the original execution. This is a real adapter regression;
the initial cost test and nonce test covered those features separately.

Controller API run **14 tests / 5 failures** (`artifact://167`) exposed one
fixture scheduling race plus four contaminated teardowns, not five independent
runtime defects. `streamed_tool` called extraction on its running event loop,
where `run_follow_up` schedules executor work and returns. It removed the model
capture and checked `calls` before that real work completed. The external-model
tripwire then correctly recorded the uncaptured call and contaminated subsequent
teardowns. This did not establish that narration cancelled the semantic run.

Controller reports lifecycle **31 passed**, skill gate/cost passed, and daily
rhythm **ALL GREEN** (`artifact://165`). Scene recipe exposed a separate obsolete
literal `main.ts` quad-expression source pin, not incorrect door-mark geometry.
The actual HTTP/prompt/tool/effect scenario still had not been reached.

Worker ran **no tests, builds, linters, formatters, scenarios, server/model/media
commands or failure-confirmation probes** in this round.

### Applied changes

1. **Atomic new-creation versus replay metadata:** the unchanged public
   `prop_action_engine.request(...) -> dict` delegates to
   `request_with_creation(...) -> (result,created)`. Every refusal/nonce replay
   returns `created:false`; only the actual committed insert returns true. Its
   existing second actor/nonce/fingerprint check under SQLite `BEGIN IMMEDIATE`
   handles competing Core callers/processes. No caller infers creation from an
   `approaching`/successful status, and no metadata leaks into the public JSON.
2. **Nonce-scoped HTTP gate/charge boundary:** an existing weak-lifetime lock map
   supplies the existing deferred reentrant lock for one `(actor,request_id)`,
   not an actor-global claim lock or an unbounded permanent nonce lock registry.
   Player HTTP holds it around prior-row lookup, gate, admission and creator-only
   charge. An existing nonce returns through Core's real fingerprint comparison
   before any new-action gate; mismatches refuse without spending. If another
   Core caller/process publishes the nonce while the gate reads newly depleted
   stats, the refusal path rechecks it. Truly new executions still pass the
   configured skill gate. Only a new accepted/nonfailed creator charges.
   Domain/invitation/model callbacks use the existing outer-lock deferral and
   run after the charge/guard; the returned creation result is then projected
   from the real current run. Consent and executor/effect ownership are unchanged.
3. **Actual extraction completion, not weaker assertions:** the fixture now
   awaits `_extract_context_from_last_chat` through `asyncio.to_thread` while the
   captured external model remains installed. That real consumer takes its
   existing inline worker branch, so the model capture, actual pose guard and
   postprocessing finish before inspection. No runtime guard, model tripwire,
   effect assertion, unexpected-call list or acceptance check was relaxed.
4. **Obsolete quad expression pin deleted:** removed only the two-line assertion
   requiring literal `m.baseY + DOOR_MARK_LIFT` in `main.ts`. It was not repinned
   to `doorMarkTransform` source spelling. The real threshold/composer/surface
   geometry assertions remain.

### New interaction regressions prepared

- Positive-cost exact actor/nonce replay preserves its original execution and
  spends only once: both five-point (50→45) and exhausting fifty-point (50→0)
  cases. Changed revision under the same nonce refuses with
  `request_id_conflict`, not a new cost/refusal caused by funds. A newly persisted
  block rule still allows a read-only replay but rejects a genuinely new nonce.
- Two simultaneous authenticated HTTP requests sharing one actor/nonce both
  receive the same real execution; actual DB has one nonce row, actual journey
  owns that ID, real person/slot claims total two, and base energy is 45 rather
  than 40. Real sessions, routers, threads, gate, cost writer and executor are
  used; no successful response/receipt is mocked.

Product API documentation now states creator-only nonce charging explicitly.
All changes remain in the approved worktree; no original checkout, unrelated
asset work, live world, deployment or restart was touched.

### Exact controller commands

```sh
./.venv/bin/python scripts/smoke_prop_action_api.py
./.venv/bin/python scripts/smoke_prop_action_runs.py
./.venv/bin/python scripts/smoke_stat_skill_gate.py
./.venv/bin/python scripts/smoke_stat_skill_costs.py
./.venv/bin/python scripts/smoke_scene_recipe.py
./.venv/bin/python scripts/smoke_auth_gate.py
./.venv/bin/python scripts/smoke_prop_action_api.py --api-scenario-dir /tmp/prop-actions-task6-fix2-http-prompt-001
```

Use a never-existing scenario destination. Existing broader Core/NPC/geometry
regressions from the prior sections remain applicable. None of these fix-round
checks/scenarios were exercised by the worker; no GREEN claim is made.
