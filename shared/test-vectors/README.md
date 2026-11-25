# Shared test vectors

Hand-derived inputs and expectations that the browser smokes (JavaScript) and the native
client's C# tests both read. One file per area: `shared/test-vectors/<area>.json`
(lowercase letters, digits, underscores). A vector is the drift guard between the two
implementations: when both pass the same file, they compute the same numbers.

## Rules

- **Every vector names where its numbers are derived.** A vector file carries only inputs,
  expectations and `source`, a repo path that is either
  (a) a smoke (JavaScript or Python) whose docstring derives every number by hand from the spec, or
  (b) a derivation document `native/tests/Derivations/<name>.md` whose numbers the C# vector tests
  execute — for logic that after E3 exists only natively (format: `native/tests/Derivations/README.md`).
  Case labels start with the `[n]` of that derivation.
- **E1 (2026-11-25) moved every derivation out of `client3d/`**, which E3 deletes with the browser
  scene: smokes that test only package code moved to `scripts/`, a vector a Python smoke already
  replays got the derivation in that smoke's docstring, and the rest moved word for word to
  `native/tests/Derivations/`; a browser smoke that stays until E3 keeps a pointer docstring
  (`Derivation moved to <new source>`). `scripts/smoke_vector_sources.py` guards this: `source` is an
  existing repo file outside `client3d/` that names the vector file literally.
- **A vector is never edited to match an implementation.** When an implementation disagrees with
  a vector, the implementation is fixed. A vector changes only when the spec (and with it the
  hand derivation in the docstring) changes.
- No code-generated values: every number in the file is written out. **One exception:** the hair-chain files
  of the native port (`collision_core.json`, `hair_chains.json`, see the last section) are generated from the
  TypeScript by `scripts/export_hair_vectors.mjs`, which first asserts the source smokes' hand numbers.
- No C# geometry code without a green vector from this directory.

## Format `anima-test-vectors/1`

```json
{ "format": "anima-test-vectors/1",
  "source": "native/tests/Derivations/bench_math.md",
  "fixtures": { "PATH": { "keys": [] } },
  "cases": [ { "label": "[1] a mid keyframe", "fn": "samplePath",
               "args": [ { "$fixture": "PATH" }, 2.5 ], "expect": { "pos": [0, 24, 40] }, "eps": 1e-9 } ] }
```

| Key | Required | Meaning |
|---|---|---|
| `format` | yes | exactly `"anima-test-vectors/1"` |
| `source` | yes | repo path of the smoke or derivation document holding the hand derivations (see Rules) |
| `fixtures` | no | object, name → any JSON value, referenced from `args` |
| `cases` | yes | non-empty array of cases |
| `cases[].label` | yes | non-empty string, unique within the file (it is the test's display name) |
| `cases[].fn` | yes | name of the function under test, looked up in the runner's dispatch table |
| `cases[].args` | yes | array; the call is `fn(...args)` after fixture resolution and sentinel decoding |
| `cases[].expect` | yes | expected return value (`null` is a valid expectation) or `{"$throws": true}` |
| `cases[].eps` | no | absolute tolerance for every number in `expect`, `>= 0`, default `1e-9` |

### Fixtures

`{"$fixture": "NAME"}` anywhere inside `args` (at any depth) is replaced by a fresh deep copy of
`fixtures.NAME`, so a function that mutates its input cannot leak into the next case.
`{"$fixture": "NAME", "$with": {...}}` copies an **object** fixture and overrides its top-level
keys with those of `$with` (shallow: a key in `$with` replaces the fixture's value whole).
`$with` on a non-object fixture, an unknown fixture name, or any other key next to
`$fixture` is an error. References are not resolved inside `fixtures` or `expect`.

### Argument sentinels (P3-R20)

After fixture expansion and shallow `$with` overrides, both loaders recursively decode
these **exact whole-string values in arguments only**:

| JSON string | JavaScript | C# (`JsonArray` dispatch API) |
|---|---|---|
| `"$NaN"` | `NaN` | `JsonValue<double>(double.NaN)` |
| `"$Infinity"` | `Infinity` | `JsonValue<double>(double.PositiveInfinity)` |
| `"$-Infinity"` | `-Infinity` | `JsonValue<double>(double.NegativeInfinity)` |
| `"$undefined"` | `undefined` | `JsonValue<JsonElement>` with `ValueKind.Undefined` |

C# numeric adapters read the first three through `VectorCompare.Num`; undefined stays
distinct from JSON null and can be detected with `GetValue<JsonElement>().ValueKind`.
Undefined array entries and object keys remain present. Raw fixtures, case metadata and
expectations stay unchanged; expectations use the existing finite-number/null/string rules.
Strings such as `"x$NaN"`, `"$Inf"`, `"$Infinity suffix"` and `" $undefined"` stay strings.
Exact sentinel spellings are reserved in arguments; there is no substring replacement.
Fixture references inside fixtures remain data and are not expanded recursively.

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
  raw non-finite numbers are forbidden everywhere (the string sentinels below are valid);
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
| `bench_math.json` | `native/tests/Derivations/bench_math.md` | `percentile`, `summarize` (`client3d/src/bench/benchStats.ts`) |
| `ground_polygons.json` | `scripts/smoke_ground_math.mjs` | `signedArea`, `polygonArea`, `cleanRing` (`packages/scene-render/src/groundAreas.ts`) |
| `scatter.json` | `client3d/scripts/smoke_scatter_math.mjs` | the C#-ported functions of `packages/scene-render/src/scatter.ts` and `client3d/src/scene/scatterLod.ts` (TS↔C# table in the smoke's header). A sampler's `rng` option is a list of numbers, fed in order; drawing past its end throws |
| `camera.json` | `native/tests/Derivations/camera_math.md` | the overview camera: `fitDistance`, `worldCentreXZ`, `wheelZoom`, `zoomTowardCursor`, `damp`, `flyAdvance`, `flyEase`, `orbitStep`, `clampPitchDeg`, `cameraPose` (`client3d/src/scene/cameraMath.ts`) and `basePitchDeg` (`client3d/src/scene/cameraFraming.ts`). Points are `[x, y, z]` / `[x, z]` lists, a bounds object `{min_x, max_x, min_z, max_z}`; an optional last argument may be omitted |
| `occlusion.json` | `client3d/scripts/smoke_occlusion.mjs` | Task 53 / E7-T8: `occlusionUniforms`, clamped segment/rim hide and Bayer threshold/discard; 47 hand-derived cases |
| `view_shift.json` | `native/tests/Derivations/view_shift.md` | `viewShiftFor` (`client3d/src/scene/viewShift.ts`); the panel is `{x, y, w, h}` or `null` |
| `overview_hud.json` | `native/tests/Derivations/walk_math.md` | `bubbleText`, `bubbleMs` (`game/bubble.ts`), `bootProgress` (`game/boot.ts`; the finished stages as a LIST), `infoPanelData` (`game/infoPanel.ts`; `roomOf` as an object name → room, `null` for an absent view / avatar), `checkScatterPrefs`, `scatterLodCfgOf` (`game/prefs.ts`) — all under `client3d/src/` |
| `poll_schedule.json` | `scripts/smoke_sync_client.mjs` | `pollIntervalMs`, `nextErrorFactor` (`packages/player-ui/src/pollCore.ts`) |
| `event_pins.json` | `native/tests/Derivations/event_pins.md` | `pinGlyph`, `pinY` (`client3d/src/game/eventPins.ts`); events are `{category}` objects, `null` = no list |
| `overview_labels.json` | `native/tests/Derivations/overview_labels.md` | `tagVisible`, `tagTravelling`, `tagName`, `tagAnchorY`, `locationLabelLift` (`client3d/src/scene/nameTags.ts`; `travel` is the `{starts_in_s, eta_hhmm}` block or `null`, `tagAnchorY(null)` = a portrait), `closeTargetDist`, `openViewShouldClose` (`client3d/src/game/openView.ts`) |

| `scene_place.json` | `scripts/smoke_place_rotation.mjs` | Three-free `placeTransform(spec, meshBoxes)`; each mesh box has local `min`/`max` triples and an optional column-major glTF `matrix`. Returns `fixPos`, `fitScale`, scalar `outerScale`, `outerPos`. |
| `scene_primitives.json` | `scripts/smoke_scene_primitives.mjs` | `wallTransform`, `boxFaceUVs`, `extraCorners` (intrinsic XYZ, unlike model fix YXZ), `plateShape`, `placeholderBox`; aggregate measurement arrays preserve all wall/extra/plate geometry assertions. |
| `scene_verify.json` | `scripts/smoke_scene_verify.mjs` | `inFrame`, `primitiveRows`, `placementRows`, `wallTargets`. Boxes are `{min:{x,y,z},max:{x,y,z}}`; rows return `{checked,rows}`; wall targets serialize as `{field,target}`. |
| `scene_view.json` | `client3d/scripts/smoke_scene_view.mjs` | Pure `sceneView.ts` decisions and transforms, `storeyPieceOpacity`, `farShellSource`, `ringFor`, `placeDistance`, `detectStyle`; tile frames are `{center:{x,y,z},yaw}` with radians. |
| `scene_models.json` | `client3d/scripts/smoke_scene_models.mjs` | Model variants, hinge/terrain/marker/slot/glyph/surface arithmetic, material looks, cut planes and clip/cutout point predicates. JSON wrappers and dispatch conventions are documented in the source smoke. |
| `light_pool.json` | `client3d/scripts/smoke_light_pool.mjs` | `pickLights` (`visibleRooms` as a LIST), `flickerFactor`, `nightLightGain`, `haloVisible`, `fireColourMix`, `stepLightSlot`, `lightPositionInFrame` (column-major frame), `lightPoolSize` (`client3d/src/scene/lightPool.ts`) |
| `ambience.json` | `client3d/scripts/smoke_ambience.mjs` | `ambienceTarget`, `stepAmbience`, `stepAmbienceN` (n steps), `nightFactorAt` (`client3d/src/scene/ambience.ts`), `roomRectOf`, `roomAtRects` (rects as `[id, rect]` pairs), `corridorAtOutline` (`client3d/src/game/roomAt.ts`), `worldToTile` (`{center:{x,z}, yaw}`, tiles.ts → scene-render `worldToLocalXZ`) |
| `mirror_plane.json` | `scripts/smoke_mirror_plane.mjs` | `planeOfFaces`, `planeOfSquareMix`, `mirrorBudgetRun`, `mirrorRefreshes` (`null` = Infinity), `mirrorPreset` (`packages/scene-render/src/mirrorSurface.ts`); wrappers in the smoke's header |
| `slot_materials.json` | `scripts/smoke_slot_materials.mjs` | `slotFill`, `glassPreset`, `materialPresets` (`packages/scene-render/src/slotMaterials.ts`) |
| `door_swing.json` | `native/tests/Derivations/door_swing.md` | `doorConstants`, `doorTargetAngle`, `doorDistance`, `easeAngle`, `doorSwingFrames` (`client3d/src/game/doorSwing.ts`); a `null` distance is Infinity |
| `figure_clips.json` | `native/tests/Derivations/figure_clips.md` | `resolveMovementPoses`, `moveClip`, `idleClip`, `standingClipFor` (`null` animation = none), `movementOf`, `canRun`, `movementPoseOf`, `resolveClipTransitions`, `clipTransition`, `bridgePace` (`client3d/src/game/walk.ts`), `clipKindChain`, `resolveClipKind`, `proceduralGait` (`client3d/src/scene/clipCoverage.ts`). The server tables are explicit arguments: a pose table is the resolved `{pose: {kind, publicKind}}` form, a transition table the resolved rule list |
| `prop_water.json` | `scripts/smoke_prop_water.py` | `waterRegionAt`, `pointInRegion` (`client3d/src/scene/propWaterMath.ts`), `propWaterWord`, `propWaterCarry`, `groundWaterLevel` (`client3d/src/game/walk.ts`); `waterRegionAt(specs, x, z, lift=0)` takes a numeric lift wrapped as `() => lift` (mirrored by C#) |
| `graphics_prefs.json` | `scripts/smoke_graphics_prefs.mjs` | `loadGraphicsPrefs` (stored string or `null`), `checkGraphicsPrefs`, `saveGraphicsPrefs` (exact string), `msaaSamplesOf`, `browserAntialias`, `pickBrowserAntiAliasing` (`hud/src/game/prefs.ts`); `graphicsPrefsConstants()` is a smoke adapter → `{key, levels, defaults}` |
| `audio.json` | `client3d/scripts/smoke_audio_math.mjs` | Task 58 / E8-T1: 145 cases for audio prefs, soundtrack decisions, eight-segment equal-power gains, playlist scheduling, stop/volume ramps, seeded shuffle and the browser's waiting-speech queue. Adapter signatures below. |

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
| `clip_commit.json` | `native/tests/Derivations/clip_order.md` | `commitInListOrderValue` — `commitInListOrder` with plain clip records and the smoke's flag/rename callbacks; the pair roots are `pairRootsOf` over the committed index (root = `"root:" + id`), keyed kind, then set (first file per (kind, set) wins). The last argument selects a result path through `{index, pairRoots}` (`["pairRoots", kind, set]`); `["hasKind", kind]` / `["hasPairRoot", kind]` test membership. `pairRootForValue(sources, results, kind, chain)` is `pairRootFor` along a set chain ending in `""`, null for none. Missing results remain absent. |
| `clip_coverage.json` | `native/tests/Derivations/clip_coverage.md` | Missing kinds, alias/family matching, clip chains/resolution, procedural gait and animatable pool. Pose tables are explicit resolved tables. `animatablePool` returns names in the adapter; null for `animFamily` represents the original undefined argument. Local mutation, module-state and consumer-source probes remain in the smoke. |
| `hips_tracks.json` | `native/tests/Derivations/rig_stand_ref.md` | `standingHipsRef`, `clipHipsDrop`, structural `hipsTrackMedian`, `mapHipsTrack`. Tracks are `{name, values}`; matrices are column-major. Mapper outputs typed arrays as ordinary arrays; `rootPath` is null when disabled. The non-finite input probe and real-rig checks stay local. |
| `retarget.json` | `scripts/smoke_clip_retarget.mjs` | Hand cases [1]–[10] through the pose-data form of `restCorrections`, including heel/toe stance data, quaternion values, driven heads, deformation and counter-probes. The complete adapter contract is in the source smoke and `scripts/retargetVectorDispatch.mjs`; quaternions are `[x,y,z,w]`. Original scene-object/skinning/identity probes also remain. |

Run the four source smokes above with `timeout 300 node <source>`.

## E5 room placement (Task 29, TypeScript side)

A non-finite **input** is written `{"$number": "NaN" | "Infinity"}` and decoded by the
dispatch (never a non-finite JSON number); other conventions are named per file.

| File | Canonical source smoke | Functions |
|---|---|---|
| `npc_placement.json` | `native/tests/Derivations/npc_placement.md` | `huddleOffset`, `placeAtLocationValue` — the room ladder of `computeNpcPlacements` (`client3d/src/game/npcPlacement.ts`): rows, `roomOf` (object), the tile's view state + inventory as JSON (`yaw` in radians, maps as objects, `corridors` as room ids) and a context whose standing heights / huddle ground are `[a, b, c]` planes (tile-local resp. world). The seat point is `slotFor` (`scene_models.json`). Returns one `{name, branch, pos, face, lean, inRoom, interiorShown, hidden, transition}` per row, in `localeCompare` order; `null` = no facing / lean |
| `figure_ground.json` | `native/tests/Derivations/walk_math.md` | `placementOf`, `figureTransition` (`game/placement.ts`; an absent point = an omitted argument), `gateStandY` (`game/walk.ts`), `standY`, `tileWalkLadder` (`game/ground.ts`, the rung order of `tiles.tileWalkY`) |
| `room_spots.json` | `native/tests/Derivations/room_spots.md` | `polygonCentroid`, `roomSpotGridHead` (`roomSpotGrid` → `{length, first, firstDist}`), `roomSpotConstants`, `furnitureUse`, `roomFloorLadder` / `roomStandLadder` (`game/ground.ts`; `null` = undefined for `declared` / `centreY`), `roomSpotsOfValue` (`game/roomSpots.ts`, the core of `tiles.deriveRoomSpots`; samplers as `[a, b, c]` planes over tile-local metres) |
| `place_poll.json` | `native/tests/Derivations/places_client.md` | `pollIsStale` (`game/placement.ts`); `null` = Infinity | They execute
every new case; unknown function names fail through the unchanged shared runner.
These files do not depend on recorded model output or `native/fixtures/rest_reference.json`.

## E5 NPC walking (Task 30, TypeScript side)

Run `timeout 300 node client3d/scripts/smoke_npc_walk.mjs` and
`timeout 300 node client3d/scripts/smoke_walk_math.mjs`.

| File | Canonical source smoke | Functions |
|---|---|---|
| `npc_walk.json` | `native/tests/Derivations/npc_walk.md` | `npcGoal`, `npcStepValue`, `neighbourFacing`, `standingFacing`, `facingYaw`, `easeNpcYaw`, `easeNpcY`, `liftStops` (`game/npcWalk.ts`). Points are `{x,y,z}` world metres; yaw is radians. `npcStepValue(d, hasWaypoint, movement, reckoning, dt, pace, paceLimit, reckonedStep=null)` constructs the goal plan with horizontal distance `d`, `dist=d+10` while a waypoint remains, and `moving=d>0.05`. `liftStops` takes `[level, point]` pairs instead of a Map. |
| `npc_ground.json` | `native/tests/Derivations/walk_math.md` | `groundScope`, `terrainPace`, `sinkForState`, `groundSink`, `floatRootY`, `wadeGate`, `ghostCutY` (`game/walk.ts`); `roomDoor`, `doorwayBetween` (`game/doors.ts`); `elevatorLevels`, `elevatorTargetRoom` (`game/elevator.ts`). `floatBodyY(bed, level, sink)` returns `floatRootY(bed, level, sink)-sink`. A `nameValue(args, fields)` adapter calls `name(...args)` and selects the property path `fields`. Non-finite inputs use `{"$number":"NaN"}`. |

`npc_ground.json` moves 96 existing checks without reducing the source smoke's
1,151 passing checks. Local chain, counter-probe, invariant and state checks
remain. The new walking smoke also executes all 25 cases of the unchanged
`prop_water.json`, including `propWaterWord` and `groundWaterLevel`; those
expectations are neither copied nor re-derived here. Stair rides keep the
existing `stairs.rideStep` browser implementation; a native port can use waypoint
Y easing until E7, as allowed by the Task 30 brief.

## E5 bridge root motion (Task 31, TypeScript side)

Run `timeout 300 node client3d/scripts/smoke_bridge_vectors.mjs` for all Task 31
vectors without real models or live configuration. Each source smoke
also runs its own JSON; since E1 the hand derivations live in the derivation document
named in the table (`native/tests/Derivations/`), the smoke keeps a pointer docstring.
The original real-rig, consumer, mutation and bake-invariance checks stay local.

| File | Canonical source smoke | Cases | Functions |
|---|---|---:|---|
| `foot_lock.json` | `native/tests/Derivations/foot_lock_math.md` | 20 | `ramp`, `footLockPath`, `constant`, `footLockValue` (ground → weights → path / drift) |
| `leg_pin.json` | `native/tests/Derivations/leg_pin.md` | 19 | `pinRuns`, `soleDown`, `rotationBetween`, `qrot`, `ikValue`, `legPinConstants`, `constant` |
| `bridge_lift.json` | `native/tests/Derivations/bridge_lift.md` | 32 | `liftRamp`, `liftAt`, `fadeCarry`, `finiteLiftAt`, `constant` |
| `bridge_travel.json` | `native/tests/Derivations/bridge_root.md` | 18 | `rootPathAt`, `travelAt`, `toWorld` |
| `bridge_heading.json` | `native/tests/Derivations/bridge_heading.md` | 10 | `headingTrack`, `turnAt`, `constant` |
| `stand_settle.json` | `native/tests/Derivations/stand_settle.md` | 8 | `settleOffset`, `constant` |
| `foot_lock_measure.json` | `native/tests/Derivations/foot_lock_measure.md` | 58 | `relockValue`, `groundValue`, `hasGroundLiftTolerance` |
| `stairs.json` | `native/tests/Derivations/walk_math.md` | 126 | `stairChain`, `stairsAt`, `stairY`, `stairLegTo`, `stairChainValue`, `stairLegToValue`, `stairLegsValue`, `rideSequenceValue`, `rideWalkValue`, `nearestRoomAt`, `rideArrivalClearsRun`, `constant` |

The native consumer should mirror `client3d/scripts/bridgeVectorDispatch.mjs`.
These are test adapters; no browser production functions were added or changed:

- JSON positions and paths use the production field names. Root paths are
  `{times, xz}` (interleaved X/Z); turns are `{times, yaw, pivot}`. Plain arrays
  are accepted by the interpolation functions. `headingTrack` outputs an
  ordinary array instead of its production Float32Array.
- Foot-lock and leg-pin values use centimetres; bridge lift and stairs use
  metres; times use seconds; angles use radians. `qrot` and `rotationBetween`
  use **(w,x,y,z)** quaternions. Explicit skeleton quaternion inputs use
  Three's **(x,y,z,w)** order.
- `{"$number":"NaN" | "Infinity" | "-Infinity"}` is a non-finite **input**,
  decoded recursively by the adapter. Expectations are always finite JSON.
- `constant(name)` reads the named exported constant; unknown names throw.
  `legPinConstants()` returns `{PIN_MIN_S, PIN_FADE_S}`.
- `footLockValue({tracks,rest,fps}, field)` runs `groundHeights`,
  `contactWeights`, `footLockPath`, then returns `path`, `drift_path`, or
  `drift_zero_path`. The latter uses an all-zero path of the same length.
  The smoke additionally compares all wrapped hand inputs/expectations against
  `scripts/fixtures/root_motion_cases.json`, preserving the Python contract.
- `ikValue([hip,knee,ankle,target,pole], fields)` calls `twoBoneIk`, then applies
  its quaternion deltas using the original smoke's independent rotation matrix.
  Selectable results: `knee`, `ankle`, `kneeX`, `upperLength`, `lowerLength`,
  `finite` (all quaternion/point components finite).
- `finiteLiftAt(t,start,end,contact)` returns `Number.isFinite(liftAt(...))`.
- `relockValue(data, fields)` constructs a fresh skeleton and clips exclusively
  from `data`: `bones: [{name,parent,position,quaternion?}]`, `unitsPerCm`,
  `clips: [{name,duration,tracks:[{name,times,values}],path?:{times,xz}}]`,
  optional `options` passed unchanged to `relockRootPaths`. A null parent means
  the identity root Group; tracks ending in `.quaternion` use quaternion
  interpolation, other tracks are vector tracks. Missing path means an
  ordinary non-travelling clip. Results are `{reports,paths,logs,samePaths,
  reportNames,untouched,emptyAndSilent,finite}`. Each path is null or
  `{times,x,z}`. `samePaths` checks path object identity; `untouched` checks all
  input bones' local positions/quaternions before/after; `finite` checks each
  report's drift, imported drift and travel components. `emptyAndSilent` means
  no report and no log. Each case starts afresh, including identity checks.
- `groundValue(tracks,rest,fields)` selects from `groundHeights`.
  `hasGroundLiftTolerance()` tests whether the removed `GROUND_LIFT_TOL_CM`
  export is present (expected false).
- A `fields` argument is a property path (string keys / integer indices),
  selected after the production call; an empty path returns the whole result.
  `stairLegToValue(stairs,dest,fields)` and
  `stairLegsValue(stairs,chain,fields)` follow this convention.
  `stairChainValue(stairs,from,to,fields)` additionally exposes
  `["landingHeights"]` as `[chain[1].y,chain[2].y]`.
- `rideSequenceValue(initialRide, points, fields)` copies the initial ride,
  calls `rideStep(ride,x,y,z)` for each `[x,y,z]` — or
  `rideStep(ride,x,y,z,{x:fromX,z:fromZ})` for a `[x,y,z,fromX,fromZ]`, the
  frame's swept start — and writes back `leg` and `armed` between steps
  exactly as the NPC does. It selects from the last result, also exposing
  `state: {leg,armed,done}`.
- `rideWalkValue(walk, dt, fields)` runs the NPC frame of `scene/npcs.ts`
  `tick` on dry ground: `walk = {ride, start:[x,y,z], orders:[{waypoints:
  [[x,y,z]…], target:[x,y,z], seconds}]}`; each order replaces waypoints and
  target (never the ride) and runs `round(seconds/dt)` frames. A frame:
  `from` = the position's xz; `npcGoal(pos, target, waypoints,
  ride ? RIDE_ARRIVE_M : default)`, drop the retired waypoints; if `moving`,
  step `npcStep(plan,'walk_run',false,dt,1,1).step` along
  `delta / distToGoal`; if a ride runs, `rideStep(ride, pos.x, pos.y, pos.z,
  from)` — `done` drops it (recording the frame and xz), otherwise write back
  `leg`/`armed` and take its `y`; the height is that `y` when not null, else
  `easeNpcY(pos.y, (waypoints[0] ?? target).y, dt)`. Result: `{doneFrame,
  doneTime: doneFrame·dt, doneAt:[x,z], ride:{leg,armed}|null,
  orders:[{pos:[x,y,z], peakY}]}` (frames count from 1 across all orders;
  `null` where the ride never ended; `peakY` = the highest height at a
  frame end of that order).
  `rideArrivalClearsRun()` checks `RIDE_ARRIVE_M < 0.5` (pad half + gap).

No Task 31 vector reads `shared/config/clip_transitions.json` or any other
live server table. Real-clip source selection through `bridgeSources.mjs`
stays in the integration sections of the root/lift smokes. The known three
`smoke_bridge_root` [B14] hand-over failures keep their original bounds and
production implementation; they are not converted into passing vectors.

## Pair clips and figure normalisation (Task 32)

`smoke_pair_vectors.mjs` runs all 110 cases without live tables, model files,
network or a DOM. The smokes `client3d/scripts/smoke_<name>.mjs` also run their own vectors;
the table names each vector's `source`:

| JSON | Source | Cases |
|---|---|---:|
| `pair_blend.json` | `native/tests/Derivations/pair_blend.md` | 12 |
| `pair_clip_phase.json` | `native/tests/Derivations/pair_realtime.md` | 30 |
| `pair_clip_geometry.json` | `native/tests/Derivations/clip_pair.md` | 28 |
| `pair_height.json` | `native/tests/Derivations/pair_storey.md` | 12 |
| `figure_normalisation.json` | `native/tests/Derivations/figure_normalisation.md` | 4 |
| `group_role_points.json` | `scripts/smoke_group_role_points.py` | 24 |

Since E1 the derivations of the client3d smokes live word for word in
`native/tests/Derivations/` (the smokes keep a pointer docstring); the derivation of
`group_role_points.json` moved to the Python smoke that replays it against the server. `pairVectorDispatch.mjs` only constructs Three objects,
executes production functions and selects result fields. A placement fixture
with `clip` (a group role, `group_role_points.json`) plays that half, and its
library stand-in answers the root only for that name. No production code
was extracted or changed. The real-FBX/GLB integration checks in
`smoke_clip_pair.mjs` remain, including track shape and the RED counter-probe;
they still use real model files and sidecars, outside the standalone vectors.

`pair_scale.json` (source `scripts/smoke_pair_scale.mjs`, 42 cases, replayed by that smoke and native
`PairScaleVectorTests`): scene-render `pairScale.ts` — `pairFigureScale`, `pairPivotOf`, `scalePairRoot`,
`scalePairShift`; `pairContactPoint(p, pivotCm, heightM)` = `scalePairRoot(p, C, a) + a·(C − p)` (the body-fixed contact
after scaling, = C); `pairPlacedRoot(root, pivot, heightM, anchor)` = scale, then `x = ax + rx·cos + rz·sin`,
`z = az − rx·sin + rz·cos` (npcs.ts `tickInteraction`'s order; the numbers of `smoke_pair_root_sets.mjs` [B]).

`role_turn.json` (source `scripts/smoke_role_turn_vectors.mjs`, 19 cases, eps 1e-12, replayed by that smoke and
native `RoleTurnVectorTests`): scene-render `pairFit.ts` — `roleTurnFix(tilt, roll, frame, yaw)` → `{shift, turn}`,
`turnMatrix`, `matrixTurn` (incl. the half-turn branch), `fixPivot(root, frame, hipsBind)`, `fixRoot(fix, pivot, root)` →
`{position, quaternion [x,y,z,w]}`; frames row-major. `roleTurnPlaced(map, role, root, yawDeg, hipsBind)` is the whole
placement chain of npcs.ts `applyPairFix`: the role's entry of `orientation.role_turn_deg` (exactly three finite numbers,
else no turn), frame `eulerYXZ(0, yaw, 0)`, `fixPivot`, `roleTurnFix`, `fixRoot`.

Task 84 adds `pairBlend(from, target, elapsedS)` / native `PairBlend.Sample`:
`u = clamp(elapsedS / .4, 0, 1)`, weight `u²(3−2u)`, position interpolated
from the rendered adoption pose toward this frame's target, yaw along the
shortest arc (radians). It is real-time view state, including a frozen world.
`smoke_pair_entry.mjs` checks adoption, moving targets, reseeks and own-avatar
facing ownership; `smoke_pair_facing.mjs` checks invite/accept before HTTP,
`asked`, `declined`, errors and explicit rejection without a visual turn.

Native-facing adapter signatures (all distances metres except raw track
values in centimetres; all times seconds, yaw radians):

- `pairClipValue(input, field) -> number`: selects `clipT` or `phase` from
  `pairClipPhase(input)`. `input` has `clipS` (the server's clip clock,
  number/null), `tempo`, `frozen`, `loop`, `clipDurationS`, optional
  `localClipT`, optional `dt` (real frame seconds, advanced by dt · tempo
  unless frozen), optional `snapS`. Omitted local time means adoption.
  `pairSnapS() -> number` reads the production constant.
  `pairFrames(input, frames, field)` calls `pairClipPhase` once per real
  frame with that frame as `dt` and no server value, carrying the returned
  clock to the next frame.
- `isPairClipName(name) -> boolean` calls production directly.
- `extractPairRootPath(tracks) -> {times,xz}` constructs an AnimationClip of
  VectorKeyframeTracks (`{name,times,values}`), calls `extractRootPath`, and
  converts its Float32 arrays to JSON arrays. `xz` is interleaved X,Z. Values
  and times are quantised to float32 as in the browser; these cases use 1e-6
  tolerance where needed. Missing hips returns `{times:[0],xz:[0,0]}`.
- `pairRootPathValue(path,t,field) -> number` constructs Float32 path arrays,
  calls `rootPathAt`, and selects `x` or `z`.
- `pairRoomStandY(tile,room,x,z) -> number|null`: calls `roomStandY` with an
  explicit tile. `center` is `[x,y,z]`, `roomFloors` is an array of
  `[roomId,{hull,declared}]`, `roomCenters` an array of `[roomId,[x,y,z]]`;
  the adapter restores Three vectors and Maps. These fixtures have no surfaces.
- `pairPlacementValue(data,field) -> number` runs one real `NpcManager.tick`
  (dt 1/30) with a minimal injected NPC and a stub figure whose `playPair`
  succeeds, `holdsTravel` is false and `setFirstPerson` is available.
  Explicit inputs: `tile`, `root:{x,z}` (the returned pair root),
  `anchor:{x,z,yaw}`, `terrainY`, `room` (id/null), `placeId` (id/null),
  `seatSlots` (`[{y},...]`/null). Room coordinates subtract anchor XZ as in the
  original storey smoke. A non-null place id permits the slot lookup; null
  slots represent a missing place. Selects root position `x`, `y` or `z`.
  This exercises the browser's actual anchor transform and height precedence,
  rather than implementing a second formula in the adapter.
- `anchorFigureBindValue({min,max,height,initialPosition,initialScale})`
  creates a bind geometry with the two bbox corners, calls production
  `anchorFigureBind(THREE,pivot,height)` and returns
  `{scale,position:[x,y,z],min:[x,y,z],max:[x,y,z]}` of the grounded result.
  The helper resets pivot scale/position, scales to height, centres XZ and
  grounds the feet. Empty geometry is outside these cases; a flat bbox tests
  its existing zero-height denominator fallback. The separate Figure
  constructor's centring block is unchanged.

No Task 32 vector imports live config or reads current animation tables.
Unknown function names fail through the shared runner; none are skipped.

## Secondary motion and extension bones (Task 33)

`timeout 300 node client3d/scripts/smoke_secondary_vectors.mjs` runs 22 cases
without live config, assets, DOM, network or historical git sources. All four
JSON files have the single source `native/tests/Derivations/secondary_motion.md`,
which holds the numbered hand derivations moved word for word from
`client3d/scripts/smoke_secondary_motion.mjs` (E1). That smoke runs the
same vectors and retains the integration, historical parity, allocation,
reset/tier, normal and admin checks.

| JSON | Cases | Dispatch function |
|---|---:|---|
| `secondary_particle.json` | 7 | `stepSecondaryParticle` |
| `secondary_angle.json` | 6 | `softMotionAngle` |
| `secondary_params.json` | 5 | `blendMotionParams` |
| `secondary_chain.json` | 4 | `secondaryChain` |

Native-facing test adapter signatures (metres, real seconds, radians unless
an explicit parameter name ends in `_deg`):

- `stepSecondaryParticle(p, v, target, targetVelocity, params, h) -> {p,v}`:
  vectors are numeric `[x,y,z]` arrays; `params` is an explicit MotionGroup.
  Calls the production exact oscillator and converts output vectors to arrays.
- `softMotionAngle(angle, limit) -> number`: production function directly.
- `blendMotionParams(from, to, elapsed) -> MotionGroup`: production function;
  explicit configs, optional fields remain omitted to test documented fallbacks.
  Only expected object keys are compared, as in the common vector contract.
- `secondaryChain(data) -> {matrices,samples}`: `data.bones` is an ordered array
  of `{name,parent,matrix}`, where parent is an index or null and matrix is a
  16-number **column-major local bind matrix** (translation at indices 12–14).
  Matrices decompose to Three position/quaternion/scale before binding. Input
  matrices here are identity or translations (no shear). `positions`, `indices`,
  `weights` are flat geometry attributes (3,4,4 components per vertex); positions
  and weights use Float32, indices Uint16. The adapter creates a SkinnedMesh,
  binds all bones in input order, creates the production solver with `payload`,
  calls `update(dt)` exactly `frames` times and updates world matrices.
  `matrices` contains all world bone matrices in input order, column-major.
  For each `[a,b]` in `pairs`, `samples` contains `halfWidth` (half the world
  distance between skinned vertices a,b) and `distance` (their midpoint's world
  distance from the origin). This measures the same two ring pairs as the old
  inline chain cases; no solver formula is duplicated in the adapter.

The adapter is `client3d/scripts/secondaryVectorDispatch.mjs`; unknown functions
fail through the common runner. No production TypeScript changed for Task 33.

## Animals and clip-less rigs (Task 34, TypeScript side)

Run `timeout 300 node client3d/scripts/smoke_animal_vectors.mjs`.
Both files have the single source `native/tests/Derivations/animal_vectors.md`,
which derives every expected number (moved word for word from that smoke's docstring in E1). No assets or config are read.

| JSON | Cases | Functions |
|---|---:|---|
| `animal_legs.json` | 19 | `findLegChains` |
| `animal_gait.json` | 15 | `proceduralGaitAmplitudes`, `proceduralIdleAmplitudes`, `advanceProceduralPhase` |

Production functions live in `packages/scene-render/src/proceduralGait.ts` and
are exported from the package. `animalVectorDispatch.mjs` bundles that pure module
without converting arguments or outputs. Native-facing signatures:

- `findLegChains(bones, box) -> [{bone, foot, axis, phaseWalk, phaseRun}]`:
  bones are ordered `{name, parent, position:{x,y,z}}` records in traversal order;
  `parent` is an index or null for an immediate non-bone parent. Supply a valid
  acyclic skeleton. Names need not be unique. Positions and box `min`/`max`
  `{x,y,z}` share world space. Output `bone` and `foot` are top/leaf indices;
  `axis` is a world-space `[x,y,z]` unit vector. The browser keeps quaternion
  conversion into the bone parent's frame. Sorts are stable, including ties.
- `proceduralGaitAmplitudes(phase, legPhase, height) -> {swing,bob}`:
  phases and swing are radians, bob uses height's units.
- `proceduralIdleAmplitudes(phase) -> {bob,scale}`: bob is metres; scale is a
  multiplier applied to the figure's base scale.
- `advanceProceduralPhase(phase, dt, gait) -> number`: dt is seconds; gait is
  `"walk"`, `"run"` or null for idle. Phases stay unwrapped; no delta clamping.

Gait selection reuses `proceduralGait` in the unchanged `figure_clips.json`;
run `timeout 300 node client3d/scripts/smoke_figure_clips.mjs` for those cases.
The new smoke additionally exercises the real Figure's bind restoration,
parent-frame axis, walk/run phase update, bob/scale and no-leg idle fallback.
Unknown dispatch functions fail through the common vector runner.

## E4 scatter rows, impostors, undergrowth and world props

| File | Canonical source | Consumer |
|---|---|---|
| `scatter_rows.json` | `client3d/scripts/smoke_scatter_math.mjs` | Scatter smoke; stroke smoke also runs its station/decoration subset |
| `impostors.json` | `client3d/scripts/smoke_impostors.mjs` | Impostor smoke; scatter smoke also runs `[W...]` seam cases |
| `undergrowth.json` | `client3d/scripts/smoke_undergrowth.mjs` | Undergrowth smoke |
| `world_props.json` | `client3d/scripts/smoke_world_props.mjs` | World-prop smoke |

`client3d/scripts/e4VectorDispatch.mjs` supplies the row shape adapters:
`areaAxis({line,ring,sides,at})`, sampler `axisFrom:{line,ring,sides}`, finite
`rng`/`jitterRng` lists that throw on exhaustion, and `occupied:[{x,z,r,tag?}]`.
`occupancy(ops,routed=false)` runs `{op:'add'|'blocks',x,z,r,tag?}` or
`{op:'sample',fn,options,ring?}` on one grid; its result lists block answers
and sample arrays in order. `routed=true` uses the real `cellOccupancy` adapter.
`decorateStroke` also exposes `pointCount` and `xs` projections, leaving random
amplitudes to the original independent derivation checks.

Undergrowth geometry becomes `{positions:[[x,y,z],...],normals:[[x,y,z],...],indices:[...]}`.
`undergrowthTexel(row,column,channel?)` returns RGBA or one channel, and
`undergrowthRowInk(row)` sums alpha/255. `worldPropTier(d,previous,baseCfg)` composes
the scaled world-prop cfg and the existing tier function. These adapters call
production functions and convert shapes; they contain no expected-value tables.

New-file C# consumers arrive with E4 porting tasks. The existing scatter C#
dispatch adds only the already-ported `WantedCells`, `InstanceHash`, `OccupyR`
and `SeedEpochSuffix` functions. `scatter.json` also pins both JS sway ties.

## Travel and residency (Task 41, E6-T1)

| File | Canonical source | Cases |
|---|---|---:|
| `travel.json` | `native/tests/Derivations/travel_math.md` | 134 |
| `residency.json` | `client3d/scripts/smoke_residency_gen.mjs` | 18 |

The travel source collects the reckon and relief/densify hand derivations (moved word for word
from the opening docstring of `client3d/scripts/smoke_travel_math.mjs` in E1); that smoke runs every case. `smoke_travel_reckon.mjs` consumes the two dead-reckoning
functions; `smoke_relief_math.mjs` consumes `[15]` (full densified point arrays and its
midpoint). Their frame/ground integration checks remain inline. Source-import and copy
identity guards remain in the canonical smoke. `travelVectorDispatch.mjs` transpiles the
production import-free `travelPath.ts`; its only state adapter is
`errWindowMax(samples, nowMs) -> number`, with samples `[[tMs, err], ...]` pushed in order
through the production error-window functions. All other function names call production
directly, using XZ point pairs, metres, real seconds, and monotonic milliseconds for ages
and error-window stamps. No live server tables or world content are read.

Residency is asynchronous and uses `residencyScenario(kind, steps)` in
`residencyVectorDispatch.mjs`. The source smoke awaits each case and compares through
`near` after `resolveArgs`; unknown function/operation names fail. `kind` is `"driver"`
or `"library"`. Each step is an array of op tuples and yields one state snapshot. There is
no implicit flush: `['flush']` drains microtasks; `['settled',id]` awaits lifecycle work.
Op tuples (optional arguments shown with `?`):

- Driver: `['want',id,version,ring,priority?]`, `['rebuild',id,version]`, `['drop',id]`,
  `['gate',name]` (block the next up), `['release',name]`, `['fail']` (fail the next up),
  `['retry']` (fire the first fake timer), `['watch',id]` (count resolved settled waiters).
- Library: `['sweep',handle,ids]`, `['request',handle,id]`, `['forget',id]`,
  `['reply',fetchIndex,signature]`, `['await',handle]`, `['samePromise',handleA,handleB]`.

Driver snapshots expose `rings`, `targets`, `jobs` (maps by id), incremental `calls`
(`['up'|'down',id,version,fromRing]`), `live` (`[[id,version],...]`), cumulative `max`
concurrency/`rollback`/`resolved`, and pending timer delays. Library snapshots expose all
requested `pending` ids, published `events`, cache signatures/null by id, and promise
`results`. Expectations select keys but compare call order/array length exactly. The 18
scenarios include the original 13 driver/queue/retry cases and five SceneLibrary epoch/
dedup cases; renderer pins and real fetch/mount rollback stay integration checks in the
source smoke. A blocked scenario fails after one second instead of hanging.

C# travel/residency consumers arrive with Tasks 42/44. Task 41 changes only the common
C# sentinel loader and its test; it adds no travel/residency C# test classes.

## Embodiment and controls (Task 46, E7-T1)

| File | Canonical source smoke | Cases | Functions |
|---|---|---:|---|
| `walk_control.json` | `native/tests/Derivations/walk_math.md` | 151 | Walk direction/slide, terrain/slope gates, ground-storey filter, click goals/stall, talk, room switch/candidates, elevator offers/options, locks |
| `collide.json` | `native/tests/Derivations/walk_math.md` | 45 | Body radius, wall segments (storeys, door gaps, windows, origin), capsule clamp/slide and narrow-corridor cases |
| `enter.json` | `native/tests/Derivations/enter_math.md` | 57 | Local transform, authored/free/locked entry, polygon sanitize/area/bounds/containment/distance/rim |
| `embody.json` | `native/tests/Derivations/embody_vectors.md` | 100 | Offer resolution, place picking, driver/answer/suppression, echo ring, readiness, Esc/key routing |
| `camera.json` (extended) | `native/tests/Derivations/camera_math.md` | 83 (62 existing + 21 E7) | Adds first-person dwell sequence, rest eye/eye height, view/body yaw and zoom floor/ceiling |

Run `node client3d/scripts/smoke_embody_vectors.mjs` for all **436** cases,
without live config, assets, server or renderer. The source documents
(`native/tests/Derivations/`, moved word for word from the smokes' docstrings in E1)
contain the numbered hand derivations; the embodiment source
collects the offer, place and position smoke headers. The original source
smokes consume their migrated cases and retain their integration/invariant
checks. Both first-person smokes consume their camera subset and retain the
synthetic Figure rig checks. `node client3d/scripts/smoke_embody_fixture.mjs`
checks the separate synthetic world and scripted answers in
`native/fixtures/embody/`; its README derives the path frames and offer probes.

`client3d/scripts/embodyVectorDispatch.mjs` bundles the existing pure production
modules and provides test adapters only. It contains no expected-value tables.
All distances are metres, times are seconds except `nowMs`/echo protocol stamps
in milliseconds, and angles are radians except explicitly degree arguments.
There is one `source` per JSON file. C# consumers for the new functions arrive
in Task 47; the existing camera tests explicitly defer these seven function
names until then: `firstPersonZoomSequence`, `restEyePoint`, `eyeHeight`,
`viewHeading`, `bodyYawForView`, `zoomFloorOf`, `zoomCeiling`. Every old camera
case still runs and every other unknown function still fails. Task 47 must
remove that deferral when the ports and dispatch bindings land.

Native-facing adapter conventions:

- `walkDir(keys, yaw)` takes an array of key strings; the adapter restores a Set.
- `slideBlocked(from,to,data)` and `planClickWalk(from,to,data)` restore a blocked
  callback from `rects:[[minX,minZ,maxX,maxZ],...]` and `discs:[[x,z,r],...]`.
  Rectangles use strict bounds by default, inclusive bounds with
  `inclusive:true`; discs use strict radius. Optional `footprints` are inclusive
  rectangles where terrain passability is overridden through `terrainBlocks`.
  Bounds can use the common string sentinels for infinity.
- `groundStoreyFloors(floors, levels)` restores the room-id → level callback;
  missing/undefined levels retain the ground-storey fallback.
- `roomSwitchSequence(current,rooms,level,steps,holdS=1.5,locks=null)` starts
  with `idleRoomWalk`, applies lock filtering preserving `current`, then calls
  `nearestRoomSwitch` for `[pos,nowMs]` steps. It returns `{next:[...],state}`.
  `current` stays fixed for the sequence, matching an unconfirmed server room.
- `roomWalkCandidatesValue(data)` uses explicit `insideRooms`, `insideLevels`
  membership lists and `floorIds` keyed by level in place of the three
  callbacks. It returns the complete room candidate list. `talkName` selects
  a talk offer's name, normalizing absent offers to null.
- `avatarDriver(state,event,cancelled)` accepts/returns the reserved string
  **`$NO_CANCEL`** for the production unique symbol. It is adapter-specific,
  not a fifth common-loader sentinel. JSON null remains a distinct, legitimate
  legacy journey key. `suppressedJourney` uses the same cancellation argument.
- `echoSequence(sent,session,origins,cap=64)` pushes each explicit report number
  through production `pushSeq`, then returns `{ring,own:[...]}` using
  `isOwnEcho`. This models SEND time, rather than reception or reservation.
- `holdForSequence(steps)` starts with both pins null. Each step supplies
  `{id,ready,x?,z?,clear?}` for fake deps; it returns `{frames:[{held,state}],
  calls:[['pin'|'release',id,owner],...]}`. `clear:true` calls `clearApproach`.
  Owner strings and call ordering are compared exactly.
- `firstPersonZoomSequence(steps)` constructs one fresh `FirstPersonZoom` and
  returns each `update(distance,enabled,dt)` result for explicit tuples.
- `constant(name)` reads an actual exported constant; unknown names throw.
  A projection adapter named `<fn>Value(args,path)` calls its production
  function with the nested `args` and selects the explicit `path`. Paths use
  property names/integer indices; `$ids` maps room ids, `$roomIds` maps floor
  room ids, `$length` measures an XZ direction's unit norm. The explicit
  `roomWalkCandidatesValue(data)` signature above takes precedence.
- `polygonDistanceInfinite(...)` checks the production result `=== Infinity`;
  finite JSON expectations remain mandatory. Invalid polygon coordinates use
  `$NaN`. No production algorithm is copied into the test dispatch.

The capsule-clamp invariant based on the source smoke's independent
`minWallDistance`, room/ride hook simulations, source pins and Figure rig
checks stay inline. Prop integration references in the position harness are
inert stubs only: no prop-action API or native prop behavior was added.

## Prop actions (Task 56 / E7-T11; B1 own playback, Task 83)

Run `node client3d/scripts/smoke_prop_action_motion.mjs`. The 98 cases in
`prop_action_motion.json` use `anima-test-vectors/1`; their single canonical
source is `native/tests/Derivations/prop_action_motion.md`, moved word for word from
that smoke's opening docstring in E1. All 24 original local-route,
entry-clock and support cases retain their hand-derived inputs and values.
The format guard includes this file. The smoke retains 27 inline lifecycle
and mesh assertions. Task 83 removes the obsolete own-approach catch-up,
projection and server-lead cases, retaining observer timing. The 26 B1 cases
exercise the same production motion sampler in both clients.

`client3d/scripts/propActionVectorDispatch.mjs` calls the production exports
through shape adapters. Native-facing signatures:

- `sampleMotion(plan, elapsedS)` → `{phase,x,y,z,yaw}` on the own client
  clock. Phases are `departure`, `walking`, `frozen`, `entry`, `arrived`; yaw
  uses compass degrees. Walking and departure use `floor_y ?? access.y`
  before renderer clearance. A null per-leg pace is timeless; a null pace
  array holds after departure. Entry samples hold access while the renderer
  plays the measured bridge, then finish at the exact server anchor.
- `localApproachPoint(path, ageS)` → `[x,z]`; path has `waypoints`, nullable
  segment `paces_m_s_real`, `progress_m`, optional `starts_in_s`.
- `entryPhase(entry, ageS)` → fraction; `entryClipSample(entry, ageS)` →
  `{phase,clip_s}`, multiplying by the entry argument's `clip_duration_s`.
  The original `height_cm` input remains to document that timing is independent.
- `entrySupportLift(firstY,lastY,currentY,accessY,anchorY,rootOffset)` → number
  or null. `entrySupportSample(v)` adapts the legacy named fields to that
  export and returns `{supported,lift}`; the original support-height datum
  stays in the argument. `anchorY` already includes the root-offset correction.
- `entryIdentity(entry)` → stable kind/start/access/anchor string.
- `pickablePropRows({props,entries,offers})` → `{id,role,places}[]`; props use
  JSON `id` and `mounted` in place of a Three object. Entries are `[id,entry]`
  pairs with `slots:[[x,y,z]]`. The adapter creates object identities/vectors,
  calls `pickableProps`, then returns the matching prop IDs and place rows.
- `propActionChoices(offer)` → Core's exact enabled/reason/partner choices,
  preserving blocked offers and never selecting a partner implicitly.
- `manualGateTrace(steps,journeys)` → snapshots `{pending,calls,withdrawn}`.
  `cancel` takes `id,execution,journey` and optional `same_as` (snapshot adds
  `samePromise`); `settle` takes the first caller's `id` and `accept` boolean
  (snapshot adds `result:resolved|rejected`). These use real deferred Promises.
- `preparationTrace(steps)` → `{pending,expired?}[]`; operations are
  `begin(id,now?)`, `changed(id?)`, `adopt`, `expire(now)`. Times are milliseconds.
- `positionDrainTrace(steps,waiters)` → `{drained:boolean[]}[]`, probing the
  supplied waiter IDs in order after each microtask. Operations are
  `begin(id)`, `finish(id)`, `wait(id)`; both preceding and queued writes drain.

The last three adapters exercise fresh instances of the exported browser
state machines; they contain no copied state-transition rules. Because the
common runner is synchronous, the smoke awaits each actual result first,
then passes it (or its error) through `runVectors`. Shared fixture/sentinel
resolution, expectation comparison and failure accounting apply unchanged;
unknown functions fail before cases run. Native dispatch lives in
`native/tests/PropActionDispatch.cs`; the B1 headless check also consumes
the shared sampler cases without VSTest.

The separate synthetic world and route answer table are documented in
[`native/fixtures/propactions/README.md`](../../native/fixtures/propactions/README.md).
`node client3d/scripts/smoke_prop_action_fixture.mjs` verifies their consistency
and hand arithmetic against production motion helpers; the embody inputs stay
unchanged.

## Audio (Task 58 / E8-T1)

Run `node client3d/scripts/smoke_audio_math.mjs`. All 145 cases have one canonical
source: that smoke's numbered hand derivations. The existing walk, voiceover
and bridge smokes keep their checks. C# consumers arrive in Task 59.
P3-R31 keeps `client3d/src` and `packages/` unchanged: the smoke transforms the
original modules in a sandbox and exposes private engine functions there.
It reads the production PRNG functions from `scatter.ts`, without importing
the renderer. There are no expected-value tables in the dispatch adapters.

Native-facing signatures (times are seconds except the terrain hold):

- `audioPrefsConstants()` → `{key,defaults}`; `loadAudioPrefs(rawStringOrNull)`;
  `saveAudioPrefs(prefs)` → ordered JSON string; `audioPrefsRoundTrip(prefs)`.
- `soundtrackConstants()` → `{nightOn,nightOff,holdMs}`; `readManifest(raw)`;
  `nightForMusic(wasNight,factor)`; `nightForMusicSeq(start,factors)` → states.
- `pickMusic(manifest,night)`; `pickAmbient(manifest,terrain)` → URL arrays.
- `ambientTerrainFor(mode,avatar,camera,rows)` takes points `{x,z}` or null;
  rows are `[x,z,terrain]` for exact-point lookup, absent point → empty terrain.
- `terrainSwitchSeq(steps,holdMs=5000)` starts with `newTerrainSwitch()` and
  returns every full state `{applied,pending,since,started}`. Steps are
  `[candidate,nowMs]`; `since` and `holdMs` are milliseconds.
- `equalPowerGainAt(t0,duration,up,time)` samples the actual scheduled
  eight-segment linear ramps, holding the first/last value outside the fade.
- `playlistSchedule(requested,now,duration,crossfadeS=3)` returns
  `{begin,fade,seam,wakeInS}`. The sandbox observes the production locals after
  calculation; the real `Playlist.play` applies crossfade defaults/clamping,
  and its real `startTrack` runs against a fake decoder and audio clock.
  The wake value comes from the engine's captured timer, which never fires.
- `stopRamp(g0,now,fadeS,time)` → `{gain,end}`; `volumeRamp(g0,target,now,time,bus)`
  → gain, with optional bus defaulting to `master`. Both sample the production
  AudioParam events; the latter exercises the actual `AudioEngine.setVolume`.
- `shuffle(urls,seed)` → a new array, using the browser's seeded Fisher-Yates.
- `enqueueSpeech(waiting,incoming)` → FIFO waiting entries capped at three,
  dropping the oldest on overflow. Entries are opaque strings in these cases.
  This is `voiceover.ts`'s waiting queue, not the engine's unbounded Promise
  chain. P3-R30 carries that waiting-queue rule into the native implementation;
  Bridge v3 remains fire-and-forget.

The smoke also checks the synthetic manifest, worldmap/detail terrain consistency,
camera/avatar terrain choice, URL mappings, file size cap and codec signatures in
[`native/fixtures/audio/`](../../native/fixtures/audio/README.md).
The fixture README derives decoded lengths, seams and terrain transitions.

## Hair chains and the collision core (native hair-chain port)

These two files are the exception to "no code-generated values": every expectation is the output of the
TypeScript implementation (`packages/scene-render/src/collision.ts`, `garmentCollision.ts`,
`secondaryMotion.ts`, bundled unchanged by esbuild), written by `node scripts/export_hair_vectors.mjs`.
The hand derivations stay in the source smokes named per label prefix; the exporter asserts those hand
numbers on the TypeScript before it writes anything, so drift away from the derivation stops the export.
`node scripts/export_hair_vectors.mjs --check` replays the files through the TypeScript and fails when a file
differs from what the TypeScript gives now. The native replay is `native/tests/HairVectorTests.cs`.

| File | Cases | Functions | eps |
|---|---:|---|---|
| `collision_core.json` | 129 | `jointNowFrom`, `capsuleNow`, `linearScale`, `tipBindFactors`, `hairChainCapsules`, `pushOutOfCapsules`, `contactAngleTurn`, `bindCollision` | 1e-9 (default) |
| `hair_chains.json` | 11 | `hairChain` (end to end: `createSecondaryMotion` + `setCollision` + `update` per frame) | 1e-8 |
| `rigid_shaft.json` | 11 | `hairChain` (the RIGID SHAFT end to end; frames may also `move` bones and `configure` a payload) | 1e-8 |

Label prefixes and their sources: `[g…]` `scripts/smoke_garment_collision.mjs` [1]–[6b]; `[sq…]` and the random
sample `[r…]` (LCG seed 4242) `scripts/smoke_collision_squeeze.mjs`; `[e…]` the endpoint rule of
`scripts/smoke_collision_endpoints.mjs`; `[h1]`/`[hc…]` `scripts/smoke_hair_chain_contact.mjs`; `[ts…]`
`scripts/smoke_hair_today_skin.mjs`; `[x…]` the contact rig with a squeeze pair and a bind-capped capsule (no
hand derivation beyond the bind factor). `contactAngle` is module-private in `secondaryMotion.ts`: the
exporter appends one `export` line to that file's text inside the bundle, leaving the function itself as it is.
The full adapter contract (matrices column-major, the rig description of `bindCollision` / `hairChain`, the
recorded frames, `contactTips()`) is in the exporter's docstring and mirrored in the C# file's summary.
`[rs…]` (`rigid_shaft.json`) runs on the fixture of `scripts/smoke_rigid_shaft.mjs`; the exporter asserts that
smoke's hand numbers (droop split 4.5:2:.5 / 4.5:1:.25 / 4.5:0:0 of 1.18628°, inner joints still under the shake at
r 1) and the own-capsule hold of the shaft tip at φ ≈ 0.4584° (derived in the exporter's docstring) before writing.

### Per-strand hair (`strand_sim.json`, `strand_clock.json`)

Generated from the TypeScript (`hairSimMath.ts`, `hairSim.ts`, `strandBudget.ts`, `collision.ts`, bundled unchanged by
esbuild) by `node scripts/export_strand_vectors.mjs`; `--check` replays both files through the TypeScript and fails
on any difference. The fixtures are recipes (the build spec in the exporter's docstring: the head sphere SDF, the
curved fan, straight cards, the Spine2 follow, the torso capsule of `scripts/smoke_hair_sim.mjs`); `[fx]` pins a
digest of the built inputs so both sides provably build the same. The exporter asserts the smoke's hand numbers
(`[2]`, `[6]`, `[7]`, `[9]`, `[13c]`, `[13d]`, `[14]`) before writing. Float rows are written at 9 significant digits.

| file | cases | functions | eps |
|---|---|---|---|
| `strand_sim.json` | 55 | `strandParams`, `limitSegmentAngle`, `lerpFrame`, `boxDepth`, `sdfAt`, `fixtureDigest`, `bind`, `run`, `rest1`, `haar6`, `follow7`, `clamp9`, `tether10`, `walk11`, `lastWord12`, `inertia13`, `carry13e`, `gravity14`, `gravityOff14`, `mismatch8`, `pick` | 1e-12 maths, 0 rest / hang, 1e-8 bind, 1e-7 m sim runs |
| `strand_clock.json` | 2 | `strandClock` (`createStrandHair` + `update` per frame on a three rig) | 1e-7 m; 0 at rest |
