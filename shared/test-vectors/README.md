# Shared test vectors

Hand-derived inputs and expectations that the browser smokes (JavaScript) and the native
client's C# tests both read. One file per area: `shared/test-vectors/<area>.json`
(lowercase letters, digits, underscores). A vector is the drift guard between the two
implementations: when both pass the same file, they compute the same numbers.

## Rules

- **The derivation stays in the source smoke's docstring.** A vector file carries only inputs,
  expectations and `source`, the repo path of the smoke whose docstring derives every number by
  hand from the spec. Case labels start with the `[n]` of that derivation.
- **A vector is never edited to match an implementation.** When an implementation disagrees with
  a vector, the implementation is fixed. A vector changes only when the spec (and with it the
  hand derivation in the docstring) changes.
- No code-generated values: every number in the file is written out.
- No C# geometry code without a green vector from this directory.

## Format `anima-test-vectors/1`

```json
{ "format": "anima-test-vectors/1",
  "source": "client3d/scripts/smoke_bench_math.mjs",
  "fixtures": { "PATH": { "keys": [] } },
  "cases": [ { "label": "[1] a mid keyframe", "fn": "samplePath",
               "args": [ { "$fixture": "PATH" }, 2.5 ], "expect": { "pos": [0, 24, 40] }, "eps": 1e-9 } ] }
```

| Key | Required | Meaning |
|---|---|---|
| `format` | yes | exactly `"anima-test-vectors/1"` |
| `source` | yes | repo path of the smoke holding the hand derivations |
| `fixtures` | no | object, name → any JSON value, referenced from `args` |
| `cases` | yes | non-empty array of cases |
| `cases[].label` | yes | non-empty string, unique within the file (it is the test's display name) |
| `cases[].fn` | yes | name of the function under test, looked up in the runner's dispatch table |
| `cases[].args` | yes | array; the call is `fn(...args)` after fixture resolution |
| `cases[].expect` | yes | expected return value (`null` is a valid expectation) or `{"$throws": true}` |
| `cases[].eps` | no | absolute tolerance for every number in `expect`, `>= 0`, default `1e-9` |

### Fixtures

`{"$fixture": "NAME"}` anywhere inside `args` (at any depth) is replaced by a fresh deep copy of
`fixtures.NAME`, so a function that mutates its input cannot leak into the next case.
`{"$fixture": "NAME", "$with": {...}}` copies an **object** fixture and overrides its top-level
keys with those of `$with` (shallow: a key in `$with` replaces the fixture's value whole).
`$with` on a non-object fixture, an unknown fixture name, or any other key next to
`$fixture` is an error. References are not resolved inside `fixtures` or `expect`.

### Throws

`"expect": {"$throws": true}` (exactly that object) means the call must throw; the case fails when
it returns. Any other expectation fails when the call throws.

### Comparison

`near(expect, actual, eps)` walks the expectation:

- **number**: `actual` must be a finite number with `|expect - actual| <= eps`. An actual
  `NaN` or `±Infinity` fails against every expectation. Integers are compared as doubles;
  `-0` equals `0`.
- **`null`**: equals only `null` (not `0`, not `false`, not a missing key / `undefined`).
- **string / boolean**: strict equality.
- **array**: `actual` must be an array of the same length; elements compare pairwise.
- **object**: `actual` must be an object (not an array); only the expectation's keys are
  checked, extra keys of `actual` are ignored, a missing key fails.

### Load errors

Loading throws (it never skips) when:

- the file is not valid JSON (this includes literals like `NaN` / `Infinity`);
- any number in the file is non-finite (JSON allows `1e400`, which parses to `Infinity`) —
  `NaN`/`Infinity` are forbidden everywhere in the format;
- `format` is not `anima-test-vectors/1`, `source` is missing, `cases` is empty;
- a case lacks `label`, `fn`, `args` (array) or `expect`, has a duplicate label, a bad `eps`,
  a malformed `$throws`, or a fixture reference that does not resolve.

A case whose `fn` is not in the runner's dispatch table is a failure, never a silent skip
(the JS runner throws before running any case).

## JavaScript

`shared/test-vectors/vectors.mjs` (Node built-ins only):

```js
import { loadVectors, runVectors } from '../../shared/test-vectors/vectors.mjs';
const { passed, failed } = runVectors(loadVectors('bench_math'), { percentile, summarize });
process.exit(failed ? 1 : 0);
```

- `loadVectors(name)` / `loadVectorFile(path)` / `parseVectors(text)` — load and validate.
- `resolveArgs(args, fixtures)` — fixture resolution.
- `near(expect, actual, eps)` → `{ok, diff}`.
- `runVectors(file, fns, {log}?)` → `{passed, failed}`; prints `  ok   <label>` /
  `  FAIL <label>` with expected, actual and the first difference.

`node shared/test-vectors/smoke_vectors_format.mjs` checks these semantics.

## C#

The native tests (`native/tests/Vectors/`) implement the same rules: `VectorFile.Load(name)`,
`VectorCompare.Near(expect, actual, eps, out diff)`, and each vector test class has a dispatch
table `fn → Func<JsonArray, JsonNode?>` that fails a case whose `fn` it does not know.

## Files

| File | Source smoke | Functions |
|---|---|---|
| `bench_math.json` | `client3d/scripts/smoke_bench_math.mjs` | `percentile`, `summarize` (`client3d/src/bench/benchStats.ts`) |
| `ground_polygons.json` | `client3d/scripts/smoke_ground_math.mjs` | `signedArea`, `polygonArea`, `cleanRing` (`packages/scene-render/src/groundAreas.ts`) |
| `scatter.json` | `client3d/scripts/smoke_scatter_math.mjs` | the C#-ported functions of `packages/scene-render/src/scatter.ts` and `client3d/src/scene/scatterLod.ts` (TS↔C# table in the smoke's header). A sampler's `rng` option is a list of numbers, fed in order; drawing past its end throws |
| `camera.json` | `client3d/scripts/smoke_camera_math.mjs` | the overview camera: `fitDistance`, `worldCentreXZ`, `wheelZoom`, `zoomTowardCursor`, `damp`, `flyAdvance`, `flyEase`, `orbitStep`, `clampPitchDeg`, `cameraPose` (`client3d/src/scene/cameraMath.ts`) and `basePitchDeg` (`client3d/src/scene/cameraFraming.ts`). Points are `[x, y, z]` / `[x, z]` lists, a bounds object `{min_x, max_x, min_z, max_z}`; an optional last argument may be omitted |
| `view_shift.json` | `client3d/scripts/smoke_view_shift.mjs` | `viewShiftFor` (`client3d/src/scene/viewShift.ts`); the panel is `{x, y, w, h}` or `null` |
| `overview_hud.json` | `client3d/scripts/smoke_walk_math.mjs` | `bubbleText`, `bubbleMs` (`game/bubble.ts`), `bootProgress` (`game/boot.ts`; the finished stages as a LIST), `infoPanelData` (`game/infoPanel.ts`; `roomOf` as an object name → room, `null` for an absent view / avatar), `checkScatterPrefs`, `scatterLodCfgOf` (`game/prefs.ts`) — all under `client3d/src/` |
| `poll_schedule.json` | `scripts/smoke_sync_client.mjs` | `pollIntervalMs`, `nextErrorFactor` (`packages/player-ui/src/pollCore.ts`) |
| `event_pins.json` | `client3d/scripts/smoke_event_pins.mjs` | `pinGlyph`, `pinY` (`client3d/src/game/eventPins.ts`); events are `{category}` objects, `null` = no list |
| `overview_labels.json` | `client3d/scripts/smoke_overview_labels.mjs` | `tagVisible`, `tagTravelling`, `tagName`, `tagAnchorY`, `locationLabelLift` (`client3d/src/scene/nameTags.ts`; `travel` is the `{starts_in_s, eta_hhmm}` block or `null`, `tagAnchorY(null)` = a portrait), `closeTargetDist`, `openViewShouldClose` (`client3d/src/game/openView.ts`) |

| `scene_place.json` | `client3d/scripts/smoke_place_rotation.mjs` | Three-free `placeTransform(spec, meshBoxes)`; each mesh box has local `min`/`max` triples and an optional column-major glTF `matrix`. Returns `fixPos`, `fitScale`, scalar `outerScale`, `outerPos`. |
| `scene_primitives.json` | `client3d/scripts/smoke_scene_primitives.mjs` | `wallTransform`, `boxFaceUVs`, `extraCorners` (intrinsic XYZ, unlike model fix YXZ), `plateShape`, `placeholderBox`; aggregate measurement arrays preserve all wall/extra/plate geometry assertions. |
| `scene_verify.json` | `client3d/scripts/smoke_scene_verify.mjs` | `inFrame`, `primitiveRows`, `placementRows`, `wallTargets`. Boxes are `{min:{x,y,z},max:{x,y,z}}`; rows return `{checked,rows}`; wall targets serialize as `{field,target}`. |
| `scene_view.json` | `client3d/scripts/smoke_scene_view.mjs` | Pure `sceneView.ts` decisions and transforms, `storeyPieceOpacity`, `farShellSource`, `ringFor`, `placeDistance`, `detectStyle`; tile frames are `{center:{x,y,z},yaw}` with radians. |
| `scene_models.json` | `client3d/scripts/smoke_scene_models.mjs` | Model variants, hinge/terrain/marker/slot/glyph/surface arithmetic, material looks, cut planes and clip/cutout point predicates. JSON wrappers and dispatch conventions are documented in the source smoke. |
| `light_pool.json` | `client3d/scripts/smoke_light_pool.mjs` | `pickLights` (`visibleRooms` as a LIST), `flickerFactor`, `nightLightGain`, `haloVisible`, `fireColourMix`, `stepLightSlot`, `lightPositionInFrame` (column-major frame), `lightPoolSize` (`client3d/src/scene/lightPool.ts`) |
| `ambience.json` | `client3d/scripts/smoke_ambience.mjs` | `ambienceTarget`, `stepAmbience`, `stepAmbienceN` (n steps), `nightFactorAt` (`client3d/src/scene/ambience.ts`), `roomRectOf`, `roomAtRects` (rects as `[id, rect]` pairs), `corridorAtOutline` (`client3d/src/game/roomAt.ts`), `worldToTile` (`{center:{x,z}, yaw}`, tiles.ts → scene-render `worldToLocalXZ`) |
| `mirror_plane.json` | `scripts/smoke_mirror_plane.mjs` | `planeOfFaces`, `planeOfSquareMix`, `mirrorBudgetRun`, `mirrorRefreshes` (`null` = Infinity), `mirrorPreset` (`packages/scene-render/src/mirrorSurface.ts`); wrappers in the smoke's header |
| `slot_materials.json` | `scripts/smoke_slot_materials.mjs` | `slotFill`, `glassPreset`, `materialPresets` (`packages/scene-render/src/slotMaterials.ts`) |
| `door_swing.json` | `client3d/scripts/smoke_door_swing.mjs` | `doorConstants`, `doorTargetAngle`, `doorDistance`, `easeAngle`, `doorSwingFrames` (`client3d/src/game/doorSwing.ts`); a `null` distance is Infinity |
| `figure_clips.json` | `client3d/scripts/smoke_figure_clips.mjs` | `resolveMovementPoses`, `moveClip`, `idleClip`, `standingClipFor` (`null` animation = none), `movementOf`, `canRun`, `movementPoseOf`, `resolveClipTransitions`, `clipTransition`, `bridgePace` (`client3d/src/game/walk.ts`), `clipKindChain`, `resolveClipKind`, `proceduralGait` (`client3d/src/scene/clipCoverage.ts`). The server tables are explicit arguments: a pose table is the resolved `{pose: {kind, publicKind}}` form, a transition table the resolved rule list |
| `prop_water.json` | `client3d/scripts/smoke_prop_water.mjs` | `waterRegionAt`, `pointInRegion` (`client3d/src/scene/propWaterMath.ts`), `propWaterWord`, `propWaterCarry`, `groundWaterLevel` (`client3d/src/game/walk.ts`); `waterRegionAt(specs, x, z, lift=0)` takes a numeric lift wrapped as `() => lift` (mirrored by C#) |

## E3 terrain, water and atmosphere

Run `timeout 300 node client3d/scripts/smoke_e3_vectors.mjs` to execute **every**
case in the seven E3 files. The original smokes also read their migrated cases;
their shader, integration, invariant and mutation checks remain in place.
Companion smoke headers are collected into the single canonical `source`'s
opening docstring as well as retained at their original sites. `[20]` and `[21]` labels
refer to the additional hand derivations in that docstring.

| File | Canonical source smoke | Areas |
|---|---|---|
| `terrain_lod.json` | `client3d/scripts/smoke_terrain_lod.mjs` | Rings, error maxima, bounds/selection/fit, morphs, pyramids, caps, fragment normals, water lift, near-window policy |
| `height_tiles.json` | `client3d/scripts/smoke_height_tiles.mjs` | Loading/batching, world/tile/lattice sampling, wire water-field decoding |
| `layer_ground.json` | `client3d/scripts/smoke_layer_cut.mjs` | Cut weights/noise/decode/window/readers; natural-ground UV/tint/AO and constants |
| `water.json` | `client3d/scripts/smoke_water_shade.mjs` | Look/packing, shore/foam/opaque/gate, profile and raster readers, waterfall detection/quad, wave-normal texel |
| `sky_light.json` | `client3d/scripts/smoke_shadow_snap.mjs` | Clock lights, night-factor cross-reference, shadow basis/snap, distance fog |
| `backdrop.json` | `client3d/scripts/smoke_backdrop_math.mjs` | Radius/height/clamp, compass, explicit-random and seeded ridge profiles |
| `fog_veil.json` | `client3d/scripts/smoke_fog_veil.mjs` | Cell/key/grid, texture addressing, height/veil alpha, constants |

The native consumer should mirror the adapters in
`client3d/scripts/e3VectorDispatch.mjs`. These are ordinary JSON argument values,
not extensions to the vector loader or comparator:

- `{"$map": [[key, value], ...]}` is a map; `{"$set": [value, ...]}` is a set.
- `{"$typed": "Float32Array" | "Uint8Array" | "Uint16Array", "values": [...]}`
  constructs that input buffer. Output buffers compare as ordinary arrays;
  output maps compare as ordered `[key, value]` pairs.
- `{"$grid": worldHeightField}` is a sampler through `sampleWorldHeight`.
- `{"$plane": [a, b, c]}` is the sampler `(x,z) => a*x+b*z+c`.
- `{"$pyramid": [sampler, originX, originZ, step, cols, rows, levelCount]}`
  constructs an input pyramid through `buildPyramid`.
- `{"$capGrid": [map, tileM]}` constructs a cap-grid input through
  `buildLodCapGrid`; `{"$layerWindow": [map, format]}` constructs a layer-window
  input through `packLayerWindow`.
- `{"$raster": {"tileM": n, "tiles": [[key, [originX, originZ, step, wire]], ...]}}`
  constructs the wire-decoded water tiles with `waterTileFrom`.
- `{"$rng": [number, ...]}` supplies a finite random stream; exhaustion throws.
  Omitting this argument exercises the production seeded stream.
- `{"$select": { ...selectionOptions, "bounds": {"min": n, "max": n}}}`
  supplies a constant `boundsOf` callback for a small hand world.
- `{"$number": "NaN"}` is a non-finite **input** for masked water interpolation.
  Water's non-finite dry **output** is explicitly represented as `null` by the
  E3 adapter; no non-finite JSON number or comparator exception is introduced.
- `latticeSample` takes a row matrix instead of the first callback; the adapter
  reads `matrix[j][i]`, with missing entries zero, and forwards the other args.
- `fooValue` takes `[fooArgs, propertyPath]` as its two arguments, invokes `foo`,
  and follows the path (strings for fields, integers for array indices). This
  preserves former individual scalar assertions, including buffer lengths,
  without combining them into fewer checks. For example,
  `waterLookFromValue([null,null],["skyMix"])` in call notation corresponds to
  `args: [[null,null],["skyMix"]]` and expects `0.55`.
- `gameHourLights` returns `sunAngle`, `sun`, `sky`, `sunIntensity`,
  `hemiIntensity`, `fillIntensity`. The two colours are packed **sRGB integers**
  in this JSON adapter; the production function retains Three's working-space
  `Color` objects so the engine performs exactly the same colour operations.
- `waterfallQuad` returns `{positions: [12 coordinates], bottom: [x,z]}` or
  `null` for non-positive height/width. Positions retain the original lip-left,
  lip-right, foot-left, foot-right order; `bottom` also places the foam disc.
- `e3Constants()` returns the exported numeric/string constants. As usual, only
  the expectation's keys are compared.

Fixture resolution happens before these adapters. None of the adapters derives
an expectation from production output. The original non-finite, relational,
shader-source and mutation probes that cannot be ordinary pure function calls
remain local checks; they are not dropped or silently skipped.

## E5 figure pipeline (Task 28, TypeScript side)

| File | Canonical source smoke | Functions |
|---|---|---|
| `clip_commit.json` | `client3d/scripts/smoke_clip_order.mjs` | `commitInListOrderValue` — `commitInListOrder` with plain clip records and the smoke's flag/rename/pair-root callbacks. The last argument selects a result path through objects/maps; `["hasKind", kind]` tests index membership. Missing results remain absent. |
| `clip_coverage.json` | `client3d/scripts/smoke_clip_coverage.mjs` | Missing kinds, alias/family matching, clip chains/resolution, procedural gait and animatable pool. Pose tables are explicit resolved tables. `animatablePool` returns names in the adapter; null for `animFamily` represents the original undefined argument. Local mutation, module-state and consumer-source probes remain in the smoke. |
| `hips_tracks.json` | `client3d/scripts/smoke_rig_stand_ref.mjs` | `standingHipsRef`, `clipHipsDrop`, structural `hipsTrackMedian`, `mapHipsTrack`. Tracks are `{name, values}`; matrices are column-major. Mapper outputs typed arrays as ordinary arrays; `rootPath` is null when disabled. The non-finite input probe and real-rig checks stay local. |
| `retarget.json` | `scripts/smoke_clip_retarget.mjs` | Hand cases [1]–[10] through the pose-data form of `restCorrections`, including heel/toe stance data, quaternion values, driven heads, deformation and counter-probes. The complete adapter contract is in the source smoke and `scripts/retargetVectorDispatch.mjs`; quaternions are `[x,y,z,w]`. Original scene-object/skinning/identity probes also remain. |

Run the four source smokes above with `timeout 300 node <source>`.

## E5 room placement (Task 29, TypeScript side)

A non-finite **input** is written `{"$number": "NaN" | "Infinity"}` and decoded by the
dispatch (never a non-finite JSON number); other conventions are named per file.

| File | Canonical source smoke | Functions |
|---|---|---|
| `npc_placement.json` | `client3d/scripts/smoke_npc_placement.mjs` | `huddleOffset`, `placeAtLocationValue` — the room ladder of `computeNpcPlacements` (`client3d/src/game/npcPlacement.ts`): rows, `roomOf` (object), the tile's view state + inventory as JSON (`yaw` in radians, maps as objects, `corridors` as room ids) and a context whose standing heights / huddle ground are `[a, b, c]` planes (tile-local resp. world). The seat point is `slotFor` (`scene_models.json`). Returns one `{name, branch, pos, face, lean, inRoom, interiorShown, hidden, transition}` per row, in `localeCompare` order; `null` = no facing / lean |
| `figure_ground.json` | `client3d/scripts/smoke_walk_math.mjs` | `placementOf`, `figureTransition` (`game/placement.ts`; an absent point = an omitted argument), `gateStandY` (`game/walk.ts`), `standY`, `tileWalkLadder` (`game/ground.ts`, the rung order of `tiles.tileWalkY`) |
| `room_spots.json` | `client3d/scripts/smoke_room_spots.mjs` | `polygonCentroid`, `roomSpotGridHead` (`roomSpotGrid` → `{length, first, firstDist}`), `roomSpotConstants`, `furnitureUse`, `roomFloorLadder` / `roomStandLadder` (`game/ground.ts`; `null` = undefined for `declared` / `centreY`), `roomSpotsOfValue` (`game/roomSpots.ts`, the core of `tiles.deriveRoomSpots`; samplers as `[a, b, c]` planes over tile-local metres) |
| `place_poll.json` | `client3d/scripts/smoke_places_client.mjs` | `pollIsStale` (`game/placement.ts`); `null` = Infinity | They execute
every new case; unknown function names fail through the unchanged shared runner.
These files do not depend on recorded model output or `native/fixtures/rest_reference.json`.

## E5 NPC walking (Task 30, TypeScript side)

Run `timeout 300 node client3d/scripts/smoke_npc_walk.mjs` and
`timeout 300 node client3d/scripts/smoke_walk_math.mjs`.

| File | Canonical source smoke | Functions |
|---|---|---|
| `npc_walk.json` | `client3d/scripts/smoke_npc_walk.mjs` | `npcGoal`, `npcStepValue`, `neighbourFacing`, `standingFacing`, `facingYaw`, `easeNpcYaw`, `easeNpcY`, `liftStops` (`game/npcWalk.ts`). Points are `{x,y,z}` world metres; yaw is radians. `npcStepValue(d, hasWaypoint, movement, reckoning, dt, pace, paceLimit, reckonedStep=null)` constructs the goal plan with horizontal distance `d`, `dist=d+10` while a waypoint remains, and `moving=d>0.05`. `liftStops` takes `[level, point]` pairs instead of a Map. |
| `npc_ground.json` | `client3d/scripts/smoke_walk_math.mjs` | `groundScope`, `terrainPace`, `sinkForState`, `groundSink`, `floatRootY`, `wadeGate`, `ghostCutY` (`game/walk.ts`); `roomDoor`, `doorwayBetween` (`game/doors.ts`); `elevatorLevels`, `elevatorTargetRoom` (`game/elevator.ts`). `floatBodyY(bed, level, sink)` returns `floatRootY(bed, level, sink)-sink`. A `nameValue(args, fields)` adapter calls `name(...args)` and selects the property path `fields`. Non-finite inputs use `{"$number":"NaN"}`. |

`npc_ground.json` moves 96 existing checks without reducing the source smoke's
1,151 passing checks. Local chain, counter-probe, invariant and state checks
remain. The new walking smoke also executes all 25 cases of the unchanged
`prop_water.json`, including `propWaterWord` and `groundWaterLevel`; those
expectations are neither copied nor re-derived here. Stair rides keep the
existing `stairs.rideStep` browser implementation; a native port can use waypoint
Y easing until E7, as allowed by the Task 30 brief.
