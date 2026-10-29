# Prop-action fixture (Task 56 / E7-T11)

Synthetic offline input for the Task 57 native consumer. Run the data and
production-math check from the repository root:

```sh
node client3d/scripts/smoke_prop_action_fixture.mjs
```

Ruling: use a separate `propactions/` world. The existing `embody/` fixture
and its checks keep their inputs. No C# consumer or API implementation is
added here. A future consumer can load the world through
`FixtureSource(dir, native/fixtures)` and implement the answer-table replay
below. `urls.json` is empty: models use placeholders, with no asset downloads.
The local heightfield and terrain are flat; the parent fixture's sloping
ground must not supply this world's height samples.

All IDs, participants and content are synthetic. `actions.json` supplies the
fixture's authored action definitions, rather than an additional HTTP route.
Its `pose-56` is a solo `pose`; `pair-56` is a two-person `pair`. The scene's
prop marker carries both derived `action_bindings`, including raw marker,
placement, variant and revision provenance. As in the server scene schema,
bindings belong to the placement's marker; the model carries its exact
`placement_id`, `variant_uid` and `definition_revision`.

These are scripted server verdicts. The fixture does not install a real entry
asset or pair clip. `fixture-sit-down` and `fixture-pair` are synthetic measured
contracts for later deterministic tests, not claims about installed clip
readiness. A native rendering check must supply its test rig/clip explicitly
or report unavailable readiness. It must not fabricate an intro.

## Hand layout and numbers

Coordinates are world metres, Y is up, XZ is east/south, yaw is compass degrees.
The location pin is (0,0), yaw 0, scale 1, so tile-local and world XZ coincide.

| Element | Authored values and derivation |
|---|---|
| Room | `loc-props` / `r-props`; boundary X -6..6, Z -4..4; level 0, floor Y 0 |
| Ground | Origin (-6,-6), step 6, 3 columns × 3 rows, all nine heights 0; grass passable at factor 1 |
| Prop | `fixture-bench`, placement `bench-56`, variant `variant-56`, revision `revision-56`; anchor (3,0); placeholder width 2.4, depth .8, height .527 |
| Marker | `prop-bench-56-seat56`, raw `seat56`, capacity 2; slots (2,0) and (4,0); support Y .527, measured root offset .398 |
| Final body root | .527 - .398 = .129; slot 0 body anchor (2,.129,0), slot 1 (4,.129,0) |
| Access | Floor points (2,0,-1) and (4,0,-1), yaw 180; entry travels one metre south to the corresponding slot |
| Participants | `fixture-avatar` starts (-3,-2); `fixture-npc` starts (4,2), both in `r-props`, height 170 cm |
| Avatar route | (-3,-2) → (0,-2) → (0,-1) → (2,-1); lengths 3 + 1 + 2 = 6 m; paces [1,1,1] m per real second |
| Avatar samples | Ages 0/3/4/5/6/20 s → (-3,-2)/(0,-2)/(0,-1)/(1,-1)/(2,-1)/(2,-1); last sample clamps at access, never body anchor |
| NPC route | (4,2) → (5,2) → (5,-1) → (4,-1); lengths 1 + 3 + 1 = 5 m; age 2 → (5,1) |
| Entry | Started game second 43206 (12:00:06 on fixture day 1); elapsed 2, duration 4 game seconds, rate 1 game second per real second; phase 2/4 = .5 |
| Clip time | A measured two-second entry at phase .5 samples at 1 second; height does not change this clock |
| Support correction | Measured hips 1 → .5 at .75 give (.75-1)/(.5-1)=.5; correction (.527-.398-0)*.5=.0645 |
| Invitation roles | NPC initiates, avatar receives; physical clip `a` = avatar, `b` = NPC; semantic actor uses access `partner`, semantic partner uses access `actor` |
| Cancellation | Explicit mid-route snapshot (0,-1), with travel/local approach/entry absent; accepted cancellation does not move to the seat or rewind to the starting point |

The routes stay inside the room and outside the bench footprint X 1.8..4.2,
Z -.4...4 while walking. The NPC detours at X 5; both approach endpoints
are at Z -1. Entry alone traverses the final access-to-body displacement.
Route fixtures are authoritative supplied paths, not a shortest-path planner
regression. No client-generated target or stand point is permitted.

## Snapshot files

| File | Meaning |
|---|---|
| `worldmap.json` | Idle participants; no travel, public local approach or entry |
| `worldmap_approach.json` | Own `journey-56-solo`, 6 m remaining, starting at progress 0 |
| `worldmap_entry.json` | Own entry at access with phase .5 and a distinct body anchor |
| `worldmap_active.json` | Entry removed; authoritative held place at slot 0 and its XZ/facing/room |
| `worldmap_pair.json` | Accepted incoming invitation: own avatar journey plus visible NPC `local_approach` |
| `worldmap_cancelled.json` | Mid-route cancelled position; no remaining motion projection |

Own travel contains its journey ID and complete polyline. The foreign public
local approach contains only journey/room/motion fields, with no action,
execution, target, partner or consent data. Private execution identity and
consent remain solely in `/play/prop-actions/state`. Journeys do not encode
execution IDs. A successful mutation alone never synthesizes seating.

## Scripted answer table

`answers.json` has format `anima-prop-action-answers/1`. Select one scenario;
consume steps in order, matching exact `method`, `path`, and `request` JSON
(GET request is null). Each step gives HTTP `status` and exactly one of:

- `body`: literal response JSON.
- `body_file`: a JSON filename relative to this directory. Read it and serve
  its contents as the body; this is fixture storage, not a server wire field.

Unknown scenarios, exhausted queues or mismatched requests fail. Queues are
independent. There is no implicit server mutation, wall clock, replay, user
switch or guessed movement between steps. A later adapter must explicitly
load the table; the existing C# `FixtureSource` does not support it yet.
Every scenario is viewed by the same authenticated `fixture-avatar` session;
actor selection is never part of a player request.

| Scenario | Ordered route answers |
|---|---|
| `solo` | GET offers → POST request exact solo action/target/revision → GET state current approaching `execution-56-solo` → GET worldmap own approach → GET worldmap entry → GET state entry phase → GET worldmap held place → GET state active |
| `pair-request` | POST request exact pair/partner `fixture-npc` → `execution-56-outgoing`, awaiting_consent → GET state outgoing (cannot respond) → GET idle worldmap; requesting is not acceptance |
| `pair-accept` | GET state incoming `execution-56-invite` from NPC (can respond) → POST respond accept true → approaching → GET state current with exact physical roles → GET worldmap two approaches |
| `pair-decline` | Same incoming state → POST respond accept false → cancelled/consent_declined → GET state recent result, cannot cancel → GET idle worldmap |
| `cancel` | From own running solo: POST cancel `execution-56-solo` → cancelled/cancelled → GET state recent result → GET mid-route cancelled worldmap |
| `stale-revision` | POST solo request with revision `stale` → HTTP 409 `{detail:{execution_id:"",status:"refused",reason:"stale_definition"}}` → GET empty private state |

Successful POST bodies use the actual route shape
`{execution_id,status,reason}`. The subsequent GET worldmap provides the
approach journey, rather than adding a journey to the POST response. State
always has `incoming`, `outgoing`, `current`, `recent_results`; each execution
carries the immutable action/target/revision, participants, semantic and
physical roles, phase label, reason and permission flags. Terminal rows
include empty effect receipts because these fixture definitions have no effects.
