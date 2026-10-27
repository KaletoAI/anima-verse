# Task 9 — semantic client cutover handoff

BASE `485800bc`, worktree `/home/dev/projekte/anima-verse/.claude/worktrees/props-actions-admin`, branch `feat/props-actions-admin`. The scoped commit hash is supplied in the final handoff.

## Superseding user scope

The user explicitly excluded the unfinished native client after this handoff.
Commit `58402fea` restores all Task9 `native/` implementation, tests and native
documentation to the pre-Task9 state. The controller stopped its own native
process and display. Native build observations below belong to the superseded
scope, not to the remaining acceptance. Only browser/shared browser HUD,
authoritative server motion and the final effective LLM prompt check remain.

## Evidence boundary

This worker and its children ran **no checks, tests, builds, linters, formatters, browser/native sessions, servers, model/media jobs, or fixture operations**. No RED/GREEN, compilation result, playable-client parity, anatomical contact, successful live input, or acceptance result is claimed. The implementation and behavioral regressions are prepared for the controller. Existing parent-observed admin coffee completion is not Task9 client proof.

Only this isolated branch was edited. The original checkout and its user changes were not modified/reset/stashed. No user world was deployed or restarted. The parent-owned synthetic world, template, actual models/clips, accounts and display remain outside this commit.

## Consumer migration inventory

| Consumer | Cutover |
|---|---|
| Browser `main.ts`, place picking and meshes | Real semantic offers/state, exact action/target/revision/partner; blocked furniture stays pickable even with zero free slots; no successful-request seating assumption. |
| Browser `api.ts`, `types.ts` | Real shared semantic HTTP helpers and public local/entry motion DTOs; pure helper subpath avoids importing React panels into the API dependency graph. |
| Browser HUD `bus.ts`, `bridge.ts`, `PlaceMenu.tsx` | v3 commands and exact correlated position-drain barrier; semantic menu, explicit partner choices, visible authoritative blocking reasons. |
| Shared `SelfPanel`, `ScenePanel`, `OthersPanel` | Shared lifecycle/offer presentation, private invitations, exact accept/decline/withdraw/stop, authored phase labels, result receipts and real wake. Existing frontend and both embedded HUDs consume these same panels. |
| Native `HudProtocol`, `HudOverlay`, `MainHud`, `MainPropActions` | Actual native v3 routing and HTTP execution, not just a registered DTO name. Mesh menus preserve stable placement/variant provenance. |
| Native `MainControl`, `MainSync`, `MainWorld`, `FigureManager` | Genuine declared embodied/take-control path, actual manual input and server position writes, fresh semantic state/motion, awaited cancellation and position-drain ownership. |
| Both actual figure renderers | Authoritative polylines, measured live entry at floor access, once-only committed-anchor handoff, explicit missing representation instead of a visible teleport. |
| Shared scene types | `SceneModelSpec` now declares already-emitted `placement_id`, `variant_uid`, `definition_revision`; clients do not infer semantic targets from mesh IDs or variant array indices. |

`pickPlacePose` is removed from executable bridge commands, handlers and menus; its only intentional test mention checks that the removed alias is not installed. Furniture never falls back to raw marker-group poses. Room markers retain `pickRoomPose(placeId,poseKey)` and free-body poses remain valid. Existing general temporary Together auto-acceptance is unchanged; new semantic prop pairs use the real exact-execution consent API.

The existing `prepare_runtime()` preparation remains the single startup migration boundary: existing place/field/group prerequisites, read-only inventory, validated idempotent world-store application and execution-owner registration. No second cutover flag, permanent marker fallback, migration of Shared assets on startup, or live-world activation was introduced. Repair-required legacy bindings stay honestly blocked by Core offers rather than gaining a client escape path.

## Exact semantic and bridge protocols

The existing real endpoints remain:

- `GET /play/prop-actions` returns an **array**, including `available_targets: [{partner,enabled,reason}]` for pair actions.
- `GET /play/prop-actions/state` returns only own `{incoming,outgoing,current,recent_results}`.
- Request: `{action_id,target:{location_id,room_id,placement_id,variant_uid},revision,partner?,request_id?}`.
- Respond: `{execution_id,accept}`; cancel: `{execution_id}`.
- Waking uses the real `POST /play/self/activity` with `{activity:""}`. `/play/pose` and `/play/self/pose` do not exist and are not used.
- Native manual `/play/pos` reports include the complete canonical `{x,z,seq,t_ms,session}` stamp. A stable 32-character token and API-owned sequence rotate/reset on genuine control ownership acquisition, after draining the prior write; the server rejects partial stamps.

Private state rows additionally expose `phase_label`, derived from the immutable admitted combined-action definition. Machine `phase` remains unchanged and can be a UUID. Panels display the authored label, not a UUID or assumed fixed prepare/drink IDs. Rendering still follows Core's actual current entry/profile pose, not a combined definition's unused top-level pose.

HUD bridge **v3** commands:

```ts
pickPropAction(actionId,target,revision,partner?)
pickRoomPose(placeId,poseKey)
closePlaceMenu()
respondPropAction(executionId,accept)
cancelPropAction(executionId)
```

Pure shared API/event seam:

```ts
getPropActions()
getPropActionState()
requestPropAction(actionId,target,revision,partner?)
respondPropAction(executionId,accept)
cancelPropAction(executionId)
setPropActionPreparation(handler: (requestId: string) => Promise<void>)
onPropActionChanged(listener: (requestId?: string) => void)
notifyPropActionChanged(requestId?: string)
```

A mutation first awaits preparation. The iframe sends `{v:3,kind:'prop-action-prepare',request_id}`; the host synchronously pauses position publication, drains its pending position work and answers `{v:3,kind:'prop-action-prepared',request_id,error?}`. Only the matching acknowledgement allows HTTP. The internal `gameActions.preparePropAction(requestId)` is not an exposed game command. Timeout is ten seconds, with no retry; disconnect clears/rejects pending HUD waits.

The helper's `finally` sends bidirectional `{v:3,kind:'prop-actions-changed',request_id?}` even on refusal/preparation failure. Matching settlement releases the host barrier only after fresh authoritative reads; ordinary lifecycle polling emits no ID and cannot release another in-flight mutation. A lost completion has a bounded host lease and still requires a fresh canonical read. These transport IDs are not server request nonces or public execution identities. This specifically prevents a previously sent manual position report from overtaking a newly accepted request from a shared panel.

The shared action feed deduplicates offers/private state across panels under `play-prop-actions`, reads both concurrently every second and subscribes to presence/scene/self/world invalidation. Self/Scene/Others refresh their actual existing host data. An errored offer refresh retains visible context/error but disables stale request buttons; stop/respond remain callable. Both hosts refresh motion immediately and use 150ms short-motion/burst reads rather than inheriting the normal three-second minimum spacing during approach/entry.

## Public motion and measured entry

The existing nullable `characters[].local_approach` remains visible same-room motion only: remaining world-XZ polyline, relative progress, segment real paces, departure delay and local journey key. Both renderers consume it along its segments, including two bends, rather than taking a straight line between polled positions. Own motion uses the actual own journey. Visibility/room/projection loss clears cached local motion; old cancelled journey keys are tombstoned before manual cancellation awaits.

New nullable `characters[].prop_action_entry`:

```ts
{
  kind: string, pose_key: string,
  access: {x:number,y:number,z:number,yaw:number},
  anchor: {x:number,y:number,z:number,yaw:number},
  root_offset: number,
  duration_game_s: number, elapsed_game_s: number,
  game_seconds_per_real_second: number,
  height_cm: number, role: 'a' | 'b' | null,
  started_game_s: number
}
```

World metres, compass-degree yaw. Access Y is the actual floor. Anchor Y is already the body-root height (`marker surface - root_offset`); support height is `anchor.y + root_offset`, so clients must not subtract the offset twice. Core's existing scene root offset is a fixed world-metre scalar, not a new actor-height multiplier. The actual actor height still controls the fitted figure/clip and measured root travel. Example raw offsets are not evidence of a height-200 actor's observed contact.

The server persists a stable entry origin, reads actual executor elapsed plus online fractional game progress and publishes zero rate while frozen. Projection checks actual live phase/profile/access/claims and same-room visibility, including self. No execution ID, target IDs, consent, question or partner is included; the physical A/B role is preserved. Cancellation/activation/visibility loss withdraws it.

Both renderers schedule the actual clip once at access at the projected phase. They reuse measured fitted root travel/turn, retain the original Y bone animation, and derive support progression from the actual fitted hips-Y curve, not a time/end-position correction or an unrelated reverse-transition prerequisite. The corrected support lift is held consistently through final Core anchor adoption. Flat/missing measured Y with a required support correction is explicitly unavailable. Failed/unplayed entries are not allowed to become visible access-to-anchor teleports when the projection disappears; the unavailable representation remains explicitly hidden/unavailable instead of fabricating movement. Semantic completion/effects still belong exclusively to Core, never clip-end callbacks.

## Prepared behavioral regressions

- `scripts/smoke_prop_action_api.py`: actual authenticated ordinary-player worldmap during real Core entry; own/visible projection, fractional/frozen progress, withdrawal, privacy, ownership/claims, swapped physical roles, root offsets, stable origin, UUID phase labels and immutable admitted phase definitions.
- `shared/test-vectors/prop_action_motion.json`: hand-derived two-bend/segment-pace/start-delay/freeze/trim/clamp cases; entry phase-to-clip timing; actual support/offset/upper-floor/flat-root cases consumed by browser and C# production helpers.
- Browser motion regression: real production path/entry helpers, cancellation tombstones, position draining, correlated concurrent preparations/lease expiry, measured support.
- Shared API/component regressions: exact HTTP bodies, explicit consent only, current partner blocking, actual lifecycle controls, UUID label rendering, failed preparation prevents HTTP, correlated finally invalidation and stale-offer disabling.
- Browser and gdCEF bridge regressions: real independent module realms, exact serialized action target/revision/partner, v3 rejection, prepare/ack ordering, no HTTP before host drain, failure correlation, no notification echo, cleanup. These use the workspace's declared TypeScript transpiler rather than undeclared esbuild.
- Native tests/checks: actual DTO/motion helpers and shared vectors, cancellation/wake ordering, correlated preparation, blocked provenance, and actual fitted-clip entry/missing-representation checks. Native runtime execution remains a separate required acceptance.

## Controller commands — not executed by worker

From the worktree root:

```sh
./.venv/bin/python scripts/smoke_prop_action_api.py
./.venv/bin/python scripts/smoke_prop_action_runs.py
./.venv/bin/python scripts/smoke_prop_action_paths.py
./.venv/bin/python scripts/smoke_prop_action_effects.py
./.venv/bin/python scripts/smoke_prop_action_migration.py
node packages/player-ui/propActions.test.mjs
node packages/player-ui/propActionsPanel.test.mjs
node client3d/scripts/smoke_prop_action_motion.mjs
node client3d/scripts/smoke_hud_bridge.mjs
node client3d/scripts/smoke_hud_gdcef.mjs
npm run build -w frontend
npm run build -w client3d
```

Native uses the documented installed toolchain; from `native/`:

```sh
export PATH=/home/dev/tools/dotnet:$PATH
export GODOT=/home/dev/tools/godot/Godot_v4.7.2-stable_mono_linux_x86_64/Godot_v4.7.2-stable_mono_linux.x86_64
dotnet test tests
dotnet build
"$GODOT" --headless --path . --import
"$GODOT" --headless --path . -- --check bridges
"$GODOT" --headless --path . -- --check
"$GODOT" --path . -- --server=http://127.0.0.1:8794 --user=FIXTURE_USER --goto=FIXTURE_LOCATION
```

For an exported real client, the existing documented command is `GODOT="$GODOT" ./build.sh`, then `./export/anima-native.x86_64 -- --server=http://127.0.0.1:8794 --user=FIXTURE_USER --goto=FIXTURE_LOCATION`. Use the private fixture credentials in the actual launcher; no password flag, no offline mode as parity proof, no CEF debugging-port enablement. Isolate launcher preferences from production origins.

The Python additions require reloading **only the parent-owned synthetic 8794 service** before acceptance because its current uvicorn invocation does not reload code. Keep the already-authored private state/assets; do not deploy/restart a user world. Parent owns the fixture lifecycle and Xvfb :0 input/capture environment.

Optional controller-only read-only migration inventory against that same synthetic storage (not default live paths):

```sh
STORAGE_DIR=/tmp/props-admin-ui-001/world INSTANCE_DIR=/tmp/props-admin-ui-001/instance \
  ./.venv/bin/python -c 'import json; from app.core.prop_action_migration import migrate_actions; r=migrate_actions(dry_run=True); print(json.dumps({**r,"props":[{k:v for k,v in p.items() if k != "document"} for p in r["props"]]}, indent=2))'
```

It reports changed props, variants, actions, bindings, repair-required counts and `route_checked:false`; a valid document is not a proven placed route. No inventory command was run by this worker.

## Required real-client acceptance after handoff

Use both actual authenticated clients against the parent's real fixture, without `all=1`. Discover/copy actual offers from the array; do not hardcode revisions or phase IDs. Parent has actual Anna/Ben figures, authored solo/pair/sleep/combined actions, measured entry media, and the real two-bend obstacle. These are prerequisites, not observations by this worker.

1. In both clients request solo relaxation and coffee through the menu/shared panels. Capture actual position along both room bends, floor access during entry with `place:null`, measured clip phase/vertical support, final pose, phase labels and completed effects. Stool/bed height continuity must be observed on actual height-200 bodies; do not accept a raw-coordinate subtraction as contact proof.
2. Across the two sessions send an exact pair invitation. Observe outgoing and incoming states without movement/claims before consent; decline and separately accept. After acceptance capture **both** walkers, physical A/B roles and final pair. The observing client sees only public local motion, not a foreign private invitation/overland route.
3. While an owned approach is active, start actual browser/native manual steering. Observe awaited exact cancellation and real position control, no old future route revival. Repeat a shared-panel request while a position write is in flight to exercise prepare/ack correlation; test a rejected request and a dropped/expired preparation without permanent input lock.
4. Bring a newcomer into the room for configured presence interruption, compete for the same claimed slot from the other actor, stop during approach and activity, and make a genuine route unavailable. Record real terminal reason/claim release and no teleport/no success reward on refusal.
5. Execute real sleep, verify the actual sleep flag and bed ownership, then wake through the actual client control. Verify awake/shared flags, released bed and owned terminal state; raw prop-pose selection must remain unavailable.
6. Observe freeze/resume and room/visibility loss withdrawing cached public local/entry motion. Exercise missing client clip/support readiness: explicit unavailable representation, never a fabricated intro or access-to-anchor jump.
7. Retain screenshots/video plus actual ordinary worldmap/private state/profile/effect receipt samples and concrete command output. Offline checks, mocked bodies and DTO snapshots alone do not satisfy native parity.

## Separately pending final user requirement

After client cutover, the controller must still inspect the **actual effective rendered Chat, thought, in-chat thought and NPC-action prompts**, including Shared/World override resolution. Verify concrete available action IDs/exact targets and executable tool/envelope, honest blocked/empty offers and actual parsed execution to Core effects. Task6's earlier evidence does not replace this explicit final user-requested check. No external paid/model call is needed merely to prove that rendering/execution contract.
