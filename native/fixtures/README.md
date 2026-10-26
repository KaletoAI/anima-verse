# Fixtures of the `--check` mode

Offline stand-ins for the server answers the native client reads. Every number
the check compares with is derived **by hand** below, from these files and the
contract (docs/schnittstellen-3d.md) — not recorded from a run.
`Check/CheckRunner.cs` holds the same numbers as constants.

| File | Stands in for |
|---|---|
| `heightfield.json` | `GET /play/heightfield` (§ A16.5) |
| `tiles.json` | `GET /play/heightfield/tiles?keys=…` — the source answers only the requested keys |
| `worldmap.json` | `GET /play/worldmap` (§ A1.3) — location rows with `pos_x/pos_z/yaw_deg` |
| `locations.json` | `GET /world/locations?view=3d` — ids/names, **no position** (like the server) |
| `scene_<id>.json` | `GET /play/locations/<id>/scene` (§ B1); no file = 404 |
| `urls.json` | payload URL → file in this directory, or `repo:<path>` = a tracked repository file read in place |
| `building_original.glb` | a real stored location model (demo world, see provenance) |
| `building_meshopt.glb` | the server's Meshopt delivery copy of exactly that file |
| `model3d.json` | `GET /characters/<name>/model3d` (§ A7) per character name; `null` = 404 |
| `animation_clips.json` | `GET /assets/animation-clips` (§ A7/§ A8) |
| `worldmap_poll2.json` | the second world-map poll of the figure check (characters only) |
| `rest_reference.json` | the browser's rest-corrected rotations for three rigs — WRITTEN by `rest_reference.mjs` |
| `rest_reference.mjs` | node script that runs the browser's own `restCorrections` on three's loaders (see below) |
| `terrain.json` | `GET /play/terrain` (§ A9/§ A9b): one painted wood with two scatter rows, a path painted over it, one prop box |
| `scatter_reference.json` | the browser's sampler/LOD/undergrowth output for hand-chosen cases and for this fixture world — WRITTEN by `scatter_reference.mjs` |
| `scatter_reference.mjs` | node script that runs `scatter.ts` / `occupancy.ts` / `scatterLod.ts` / `undergrowth.ts` themselves (see "Scatter") |
| `terrain_layers.json` | `GET /play/terrain-layers` (§ A16.7) — the index: format, layer table, coarse id mask, tile keys — WRITTEN by `ground_fixture.mjs` |
| `terrain_layers_tiles.json` | `GET /play/terrain-layers?keys=…` — every tile; the source answers only the requested AND indexed keys — WRITTEN by `ground_fixture.mjs` |
| `surface_textures.json` | `GET /assets/surface-textures` — the library, a bare array like the server's — WRITTEN by `ground_fixture.mjs` |
| `ground_grass.png` | a 4 × 2 PNG of ONE colour (60, 140, 50, 255) — the `grass` surface image — WRITTEN by `ground_fixture.mjs` |
| `ground_fixture.mjs` | plain node script that bakes the cut-down masks in the server's encoding (see "Ground surfaces") |
| `ground_reference.json` | the browser's layer-cut / want-set / natural-ground / colour-slice values on these fixtures — WRITTEN by `ground_reference.mjs` |
| `ground_reference.mjs` | node script that runs `layerCut.ts`, `heightTiles.ts` `wantedTiles`, `naturalGroundMath.ts` and three's `Color` themselves |
| `s3c/` | Task S3c: a second, hand-written world (avatar, open/closed/far/gone locations, world props, a wet tile) — files missing there (`heightfield.json`, the ground files) are read from this directory; see "S3c world" |
| `storeys/` | Task 16: a third, hand-written world (a tower with a cellar, two storeys above and an always-visible terrace; a pit with a ground model over a basement) for the storey switch at runtime — the ground files come from this directory; see "Storeys world" |
| `fidelity/` | Task 17: a fourth, hand-written world (a plan hull with cutouts and padding, a room clip, two depth cuts on a turned location, a shell area, a changed scene for the sweep) — the ground files come from this directory; see "Fidelity world" |
| `props/` | Task 18: a fifth, hand-written world (8 lamps + a world-prop lantern, a picture frame with a picture and a glass slot, three mirror panes, a door prop with a leaf, rooms with ambience, a corridor, a cellar storey) — the ground files come from this directory; see "Props world" |

Read in place, never copied (`repo:` entries of `urls.json`; the fixture source looks
for the repository root above this directory, then above the working directory):
`shared/models/clips/idle.fbx`, `shared/models/clips/walk.fbx` (tracked clip library),
`worlds/demo/props/broadleaf-df5830/model_1792265756.glb` (full) and `…/model_1792265757.glb`
(low) — the tracked demo world's Broadleaf tree, the scatter prop of `terrain.json`,
`worlds/demo/characters/Minerva McGonagall/model3d/aa1f6d51558d.glb` (tracked demo-world
character model), `shared/models/rig/reference.fbx` (served as `/assets/animation-rig`) and,
for the rest-correction comparison only, the demo bakes of Johanna Falk and Rubeus Hagrid.

The directory carries a `.gdignore`, so the Godot editor never imports the GLBs
(the compressed one would fail: `EXT_meshopt_compression` is required).

## GLB provenance

- `building_original.glb` = `worlds/demo/locations/60820fd3/model3d/building_1792077236.glb`
  (tracked demo world), 184 176 bytes, sha256 `380f6ce1…a847a30f`.
- `building_meshopt.glb` = `worlds/demo/.cache/meshopt/380f6ce15ecfc5770183e4ee5d3ee00db8c031477b83453c470aa4d1e847a30f.glb`,
  147 740 bytes — the delivery cache names its entries by the SHA-256 of the source
  (`app/core/glb_delivery.py`), so this IS the copy the server sends for the file
  above, written by `app/blender/scripts/meshopt.py`. Copied read-only.

It uses all three codec modes: 24 `ATTRIBUTES`, 4 `TRIANGLES`, 3 `INDICES`
views; 8 image views stay uncompressed; one fallback buffer
(`{"byteLength": 162768, "extensions": {"EXT_meshopt_compression": {"fallback": true}}}`).

### Hand count of the building (from the original's glTF JSON)

One mesh, 8 primitives. `POSITION` accessor count / `indices` accessor count:

| prim | POSITION | indices |
|---|---|---|
| 0 | acc 0 → 360 | acc 3 → 540 |
| 1 | acc 4 → 48 | acc 7 → 72 |
| 2 | acc 8 → 18 | acc 11 → 24 |
| 3 | acc 12 → 600 | acc 15 → 972 |
| 4 | acc 16 → 283 | acc 19 → 525 |
| 5 | acc 20 → 314 | acc 23 → 480 |
| 6 | acc 24 → 549 | acc 27 → 645 |
| 7 | acc 28 → 48 | acc 7 → 72 |

**vertices = 360+48+18+600+283+314+549+48 = 2220**,
**indices = 540+72+24+972+525+480+645+72 = 3330**. The check demands these
totals from Godot's import of the original AND of the decoded delivery copy, and
byte equality of all 39 bufferViews between original and decoded (the server's
codec is lossless and keeps every view index).

## Terrain

**Overview** (`heightfield.json`): origin (−256, −256), step 256 m, 3 × 3 points, heights `[[0,0,0],[0,4,8],[0,8,16]]`
(`heights[j][i]`, i.e. h = 4·i·j at the lattice). `tile_step_m` 2, `mip_levels_m` [4, 8, 16, 32, 64], `tile_stats` {}.

**Tile index** `["0,0", "5,5"]`. Tiles within 384 m of the anchor (64, 128):
(0, 0) contains the point (distance 0); (5, 5) covers 1280…1536 — its nearest
corner (1280, 1280) is ≈ 1675 m away → not requested. So exactly ONE request
key `0,0` → **tiles = 1**. Tile (0, 0) in `tiles.json` is 5 × 5 at the batch
`step_m` 64 (the code reads dims and step from the payload; the real server
sends 129 × 129 at 2 m), heights `h[j][i] = 2·i + j` (= x/32 + z/64), stats min 0, max 12, err all 0.

The terrain drawn over it is the CDLOD of Task 23 — derivations in "CDLOD terrain" below: the build's first frame
(the bench start camera) is **41 pieces, 1 draw, 64 000 triangles**.

## Anchor (`--goto=harbour`)

The browser bench rule (`pickBenchAnchor`, `Core/World/WorldHeight.cs` `Anchor`):
rows = the `worldmap.json` locations; no id equals `harbour`, so the first row
whose name contains it wins → `loc-house` "Harbour House" (the fogged "Harbour
Cellar" exists only in `locations.json`, which lends names, not rows).
Position from that worldmap row: (64, 128).
y = overview, bilinear: fx = (64+256)/256 = 1.25 → i = 1, tx = 0.25;
fz = (128+256)/256 = 1.5 → j = 1, tz = 0.5.
north = 4·0.75 + 8·0.25 = 5; south = 8·0.75 + 16·0.25 = 10;
y = 5·0.5 + 10·0.5 = **7.5** → anchor **(64, 7.5, 128)**.

Extra rule checks: `LOC-YARD` (id, case-insensitive) → (−100, 2.91357421875, 50)
(overview value, derivation below); no goto → origin (the fixture has no
avatar); `cellar` (in view=3d, not in the world map = fogged), `template`
(pos null), `nowhere` → error.

The bench maths (`Check/BenchMathCheck.cs`) use no fixture file: the path is
the embedded `shared/bench/camera_path_v1.json` (checked byte-identical to the
repository file), the numbers are the hand values of
`client3d/scripts/smoke_bench_path.mjs` / `smoke_bench_math.mjs` /
`smoke_bench_anchor.mjs` (derivations in their docstrings), plus one quarter
point t = 0.3125 → [3.725, 23.84025, 38.99275] (u = 0.25 between keyframes 0
and 1), which — unlike the midpoints — rejects cosine easing.

`--check-bench` drives this fixture world: anchor (64, 7.5, 128) with the
bench label, 0.5 s warm-up + 2 s drive, last camera pose = end keyframe
(0, 24, 40) + anchor = (64, 31.5, 168), target (64, 9, 128).

## Locations

World map rows: house (64, 128), yard (−100, 50, yaw 30°), template (no
position), meadow (300, −200) → **3 placed locations**. Scene files exist for
house and yard; meadow has none (404) → **2 scenes**.

**Datum of each location group** = ground at the pin, fine tile where loaded:

- house (64, 128) lies in tile (0, 0): fx = 64/64 = 1, fz = 128/64 = 2 →
  h = 2·1 + 2 = **4** (the overview there would say 7.5 — the anchor reads the
  overview on purpose, the group the finest ground).
- yard (−100, 50) lies in tile (−1, 0), not loaded → overview:
  fx = 156/256 = 0.609375 (i = 0), fz = 306/256 = 1.1953125 (j = 1, tz = 0.1953125);
  north = 4·0.609375 = 2.4375, south = 8·0.609375 = 4.875,
  h = 2.4375·0.8046875 + 4.875·0.1953125 = **2.91357421875**.
- yard yaw = 30° → rotation.y = 0.5236 rad.

### House scene

`models[0]`: building, `fix_euler` y = 90 (a multiple of 90°, so the snapped and
the exact fix agree), `yaw_deg` 0, `measure` `yawed_xz`, `max_m` 12, anchor
(1.5, −2), `bottom_y` −0.25. By § B2: the turned box's larger XZ side is scaled
to 12, the box centre lands on the anchor, the underside on `bottom_y` →
measured in the location frame: **max(size.x, size.z) = 12, min.y = −0.25,
centre xz = (1.5, −2)**. The variant URL maps to `building_meshopt.glb` →
**buildings = 1, buildings_meshopt = 1, 2220 / 3330**.

`models[1]` (the crate) is an OUTDOOR spec (no room) → placed like the browser's `mountShell` does; its URL
has no fixture → not loadable, no `placeholder_dims` → **models missing = 1**. The house has a (non-roof)
building model, so its recipe plate/wall stay in the (closed, invisible) interior group → **interior +2**.
Mounted there since Task 15, every storey since Task 16: the level-0 wall and the level-1 storey plate (a slab,
shown only on storey 1) → **interior mounted 2**.

### Yard scene (no model → its far-view shell, Task S3c)

No avatar in this world → nothing is open. The yard has no building model, its name carries no nature word
(`detectStyle` → generic, not an area location) → `farShellSource` = **recipe**: the browser stands copies of
the LEVEL plates (no room, level ≥ 0) and of every non-GLASS wall (level ≥ 0, door leaves included, even the
one a door prop fills) outside; everything else stays in the invisible interior group.

- plates: the 8 × 6 plate with a 2 × 1 hole → shell copy (**1**); the 2-point plate → **degenerate +1**.
  Top area = 48 − 2 = **46 m²** (check sums the triangles).
- walls: 4 plain + 1 leaf + the `door_prop` leaf → shell copies (**6**); the glass pane is not part of a shell
  → **interior +1**; the zero-length wall → **degenerate +1**.
- extras: tread + rotated stringer hang in the interior group → **interior +2**; the box with size x = 0 →
  **degenerate +1**.

primitives = 1 + 6 = **7** (all **7 shell copies**); skipped = degenerate 3 + interior (2 house + 1 + 2) 5 = **8**;
panes 0.

Interior mounted (Task 15, hidden at fade 0; every storey since Task 16): the 4 contour walls + the glass pane +
the plain leaf (the `door_prop` leaf is a pane a model would fill — not drawn inside, only in the shell) + the
tread and the stringer + the level-1 plate (its storey's slab) = 9. With the house: **interior mounted = 2 + 9 = 11**.

## Figures (Task S1b)

### The three characters of `worldmap.json`

| name | row | model3d answer | rule |
|---|---|---|---|
| Ada Wren | `location_id ""`, `pos` (−50, 30), `height_cm` 160, `model_sig` `ada-1` | GLB, rig `mixamo`, not `normalized` | **free** (wilderness) |
| Bram Holt | `location_id` `loc-house`, `room_id` set, `pos` (63, 127), `height_cm` 180 | `format` `fbx`, rig `generic`, `texture_url` | **tile** (far-view huddle) |
| Cleo Marsh | `location_id ""`, `travel` with waypoints, no `height_cm`, no `model_sig` | `null` = 404 | **journey** |

→ **figures = 3, glb_figures = 1, placeholders = 2** (FBX → capsule, 404 → capsule).
The FBX file is never downloaded (the check asserts no byte request for Bram).

**Ada** stands on her own point (no placed location): (−50, 30). Tile (−1, 0) is not
loaded → overview: fx = (−50+256)/256 = 0.8046875 (i = 0, tx = 0.8046875),
fz = (30+256)/256 = 1.1171875 (j = 1, tz = 0.1171875);
north = 0·(1−tx) + 4·tx = 3.21875, south = 0 + 8·tx = 6.4375,
y = 3.21875·0.8828125 + 6.4375·0.1171875 = **3.595947265625** → (−50, 3.595947265625, 30).

**Bram** is in `loc-house` (placed, no `map3d.area_model` → building), so the browser's
far view puts him in the row in front of the building, whatever `pos`/`room_id` say:
one character of one → x = (0 − 0)·2.3 = 0, z = width·0.36 with width = bounding box of
the boundary ±6 = 12 → z = 4.32; yaw 0 → world (64 + 0, 128 + 4.32) = (64, 132.32).
That lies in the loaded tile (0, 0): h = 2·(64/64) + 132.32/64 = 2 + 2.0675 = **4.0675**
(the tile is linear in i and j, so bilinear = linear) → (64, 4.0675, 132.32).

**Cleo** walks the polyline (300, −200) → (300, −100) → (200, −100) (100 m + 100 m);
`progress_m` 137 = 100 + 37 → 37 m along the second leg: (300 − 37, −100) = (263, −100).
Overview: fx = (263+256)/256 > 2 → clamped to 2 (i = 1, tx = 1); fz = 156/256 = 0.609375
(j = 0, tz = 0.609375); north = heights[0][2] = 0, south = heights[1][2] = 8;
y = 8·0.609375 = **4.875** → (263, 4.875, −100).

**Heights.** Ada's GLB is 1.74 m tall in the file (glTF POSITION max y 1.7400002,
min y −1.8e−7; Blender's `measured.dims_m` z = 1.74), not normalised in the fixture
answer → scale = 1.60 / 1.74 → measured body height **1.60**. (The real server marks this
file `normalized` — its sidecar lists the `normalize` step — and would draw it at 1.74;
the fixture says `false` to exercise the scale rule.) Bram's capsule = 180 cm → **1.80**,
Cleo has no `height_cm` → the browser default **1.70**.

### Clips

`locomotion` maps `idle → "Stand-Relaxed"` (lower-cased: `stand-relaxed`), `walk → walk`,
`run → ""` (keeps `run`). The list carries decoys that a wrong pick would hit (their URLs
are not in `urls.json`, so a wrong pick fails the check with a 404): a pair half
(`role: a`) and a `female`-set entry of `stand-relaxed`, a plain `idle` (the unmapped
role name), a `female` walk. The neutral solo `stand-relaxed` maps to
`shared/models/clips/idle.fbx`, the neutral `walk` to `shared/models/clips/walk.fbx`
→ **clips_loaded = 2**, each URL downloaded exactly once over both polls.

**Track list of the clip files** (from the FBX connection table, read with a 60-line
binary-FBX reader outside the repo — not from Godot): both files hold 70 Model nodes
(Armature + 69 LimbNodes of the reference rig) and 53 AnimationCurveNodes with curves:
`Lcl Rotation` on 52 bones — Hips, Spine, Spine1, Spine2, Neck, Head, and per side
Shoulder, Arm, ForeArm, Hand, UpLeg, Leg, Foot, ToeBase (16) and Thumb/Index/Middle/Ring/
Pinky 1–3 (30) — and `Lcl Translation` on Hips only. Not keyed: HeadTop_End, LeftEye, RightEye,
LeftRibbon1, LeftRibbon2, both Toe_End and the ten `…4` finger/thumb tips (17 bones).

**Ada's skeleton** (glTF `skins[0].joints`): 52 joints — exactly those 52 keyed bones
(`mixamorig:` names; the 17 unkeyed reference bones are absent).

Bound per clip = 52 rotation tracks + 1 hips position = **53**; idle + walk on the one
GLB figure → **bound_tracks = 106**, unbound_clips = 0.

Godot's FBX importer emits only the curves that move (idle 40 rotation tracks, walk 20 —
the check log shows them) and keeps the constant ones as the node default; the retarget
writes those back as one-key tracks, which is why the count is the file's 53 and not
41/21. The check proves both kinds bind: after one evaluation Ada's `LeftUpLeg` (a moving
track) holds the idle clip's key 0 and her `LeftForeArm` (no Godot track — constant in
the file) the clip's node default; both differ from her own rest, so an unbound track
would fail.

### Second poll (`worldmap_poll2.json`)

Bram is gone → **figures = 2**. Ada moves to (−40, 30) and her `model_sig` becomes
`ada-2` → `model3d` is asked again (2 requests), the GLB URL is unchanged → no second
download (template cache), clips not downloaded again. Cleo has no `model_sig` (absent
both times) → not asked again. Cleo's `progress_m` 144 → (300 − 44, −100) = (256, −100).

Lerp over the poll interval (5 s): Ada plans 10 m / 5 s = 2 m/s > 0.2 → **walk**, facing +x
(rotation.y = atan2(10, 0) = π/2). After 2.5 s: Ada (−45, 30), y: fx = 211/256 =
0.82421875, north = 3.296875, south = 6.59375, y = 3.296875·0.8828125 + 6.59375·0.1171875
= **3.68316650390625**; Cleo (259.5, −100), y = 4.875 (same clamped cell). After 5 s: Ada
at (−40, 30), fx = 216/256 = 0.84375, north = 3.375, south = 6.75, y = 2.9794921875 +
0.791015625 = **3.7705078125**, arrived → **idle**.

### Placement rule on its own (`CheckPlacementRule`)

A building `h` at (10, 20), yaw 90°, width 10 with Amy and Zed (sorted: Amy i = 0,
Zed i = 1 of 2): local x = ∓1.15, z = 3.6; world = (10 + lz·sin 90°, 20 − lx·sin 90°)
→ Amy (13.6, 21.15), Zed (13.6, 18.85). An area place `m` at (−5, 5) with one character:
ring angle 0 → (−2.4, 5) (its own `pos` is ignored — the tile wins). A traveller with a
withheld route (`waypoints` null) but a `pos` → its pos; a one-point route without `pos`
and a row with neither location nor `pos` → off the map; `progress_m` 99 on a 5 m line →
the end point (3, 4).

### Rest-pose correction against the browser (`rest_reference.json`)

The figure clips are rest-corrected like client3d does it (`q = K_p⁻¹·c·K_b`,
`restCorrections` in `packages/scene-render/src/clipRetarget.ts`). The expected values are
not hand-derived — they are the BROWSER'S OWN FUNCTION's output:

    node native/fixtures/rest_reference.mjs      # from the repo root; needs npm install

The script bundles itself with esbuild (like `scripts/smoke_clip_retarget.mjs`), loads the
reference rig and the clips with three's `FBXLoader` and three demo bakes with
`GLTFLoader` (images stripped — node cannot decode them; geometry/skin/skeleton intact),
runs `restPoseOf` → `restCorrections` → `bindRelativeValues` and writes per model the
corrected-bone count, the bones a stance rule turned, and for idle @ 0 s / 5 s and walk
@ 0 s / 0.4 s the raw clip quaternion and the corrected one for 16 bones. Re-run it when
the browser function, a clip or one of the rigs changes, and commit the JSON.

| model | corrected bones | stance rule | why it is in |
|---|---|---|---|
| Minerva McGonagall | 51 (all but the hips) | none | the `--check` figure (Ada) |
| Johanna Falk | 51 | **leg** (both legs, upleg → toebase) | exercises `legStance` |
| Rubeus Hagrid | 51 | **foot** (both feet + toebase) | exercises `footStance` (sole read off the skinned mesh) |

No demo rig trips `torsoStance` (Hagrid's trunk mean is 1.05°, the gate 6°), so that
branch is ported but not compared.

`CheckRestReference` demands, per model, the same corrected-bone count and stance set,
and per sample and bone: Godot's clip value within 0.5° of three's (the two FBX importers
agree — measured 0°) and the corrected rotation within **0.5°** of the browser's (measured
max 0.056°, 192 comparisons). End to end on Ada: after `Seek` of the bound clip her
skeleton's pose rotations are within 0.5° of the browser's corrected values (measured
max 0.04°). Example, Minerva idle @ 5 s, RightArm: clip
(0.5371679, -0.0387975, -0.114042, 0.8348292) → browser-corrected (0.316868, -0.5165012, -0.4071294, 0.6834235) — 72.3° apart, which
is what the old verbatim copy put on her arm; the check allows 0.5°.

## Scatter (Task S3)

### Reference vectors (`scatter_reference.json`)

    node native/fixtures/scatter_reference.mjs      # from the repo root; needs npm install

The script bundles itself with esbuild (like `rest_reference.mjs`) and runs the
browser's own functions. Re-run it when `scatter.ts`, `occupancy.ts`,
`scatterLod.ts`, `undergrowth.ts`, `terrain.json` or the fixture camera change,
and commit the JSON. `Check/ScatterCheck.cs` demands every instance (x, z, yaw,
variant) within **1e-6 m** of the TS output:

| case | input | what it exercises |
|---|---|---|
| `plain-ring` | concave L ring, 5 / 100 m² | the stream, the ring test |
| `footprint-hole-clearance` | 50 × 40 box, a 10 × 10 footprint + a prop box turned 30°, clearance 1.5 m | `footprintDistance` / `propBoxFootprint` |
| `occluder-above` | same box, a triangle painted above | the occluder subtraction |
| `spacing` | 30 / 100 m², `min_spacing_m` 2.5 | the spacing buckets |
| `maxpoints-prefix` | the same with `maxPoints` 25 | must be the PREFIX of `spacing` (checked) |
| `cell-variants-occupancy` | half-painted cell (1, 0), 3 variants, epoch seed `…:e4` (7265 s / 30 min), a pre-filled occupancy with two foreign circles and one of the row's OWN tag, `occupyR` 2 > spacing 1.5 | `scatterCellInstances`, the variant formula, the own-tag exemption |
| `cell-pinned-aligned` | the same with `variant` 1 and `yaw_mode aligned` 90° | the pin, the aligned yaw without an axis |

Plus `instanceHash`, `undergrowthShade`, FNV-1a seed hashes and the sha256 of the
64 × 64 blade texture (with four sample texels).

### The fixture world (`terrain.json`, anchor of `--goto=harbour`)

- **Areas**: `area-wood` (forest) `[[8,72],[200,72],[200,200],[8,200],[8,72]]` —
  `cleanRing` drops the closing duplicate → 192 × 128 m; `area-path` (path) the
  strip 100…110 × 60…210 painted OVER it (an occluder for both layers).
  `forest` carries `meta.undergrowth` 0.02 and `sway_m` 0.2; `path` none.
- **Rows** of the wood: #0 the Broadleaf (`prop_height_m` 8, `min_spacing_m` 3,
  `sway_factor` 0.5 → wind 0.2 · 0.5 = 0.10 m, `ground_offset_m` −0.1, tiers
  `full`/`low`), #1 the built-in tuft (no model, h = 0.8).
- **Window**: anchor (64, 128) lies in cell (1, 2); k = ceil(120 / 64) = 2 →
  cells x −1…3, z 0…4 = **25**, row-major from (−1, 0). The wood's box 8…200 ×
  72…200 meets cells x 0…3, z 1…3 = 12 of them.
- **Wanted per cell**: trees round(4096 / 100 · 1.0) = round(40.96) = **41**,
  tufts round(61.44) = **61**; undergrowth density 0.8 · 100 · 0.02 = 1.6 per
  100 m² → round(65.536) = **66** (each per-cell layer must stay ≤ 66).
- **Footprints**: house ±6 at (64, 128), yaw 0 → the square 58…70 × 122…134
  (inside the wood); the yard turned 30° at (−100, 50) (outside); the prop box
  (150, 160), yaw 30°, half 3 × 1.5 → corners (150 + lx·cos30 + lz·sin30,
  160 − lx·sin30 + lz·cos30) = (146.652, 160.201), (151.848, 157.201),
  (153.348, 159.799), (148.152, 162.799).
- **Clearance**: estimated (no mesh yet) tree 8 · 0.5 = **4 m**, tuft 0.8 · 0.5 =
  0.4 m. Measured from the full GLB's POSITION bounds: x −0.70574…0.76030
  (1.46604), z −0.64740…0.75268 (1.40008), y −0.95243…0.78964 (1.74207) →
  spread 1.46604 / 1.74207 = **0.84155**; the low GLB gives 1.43363 / 1.71079 =
  0.83799; the widest wins → clearM = 0.84155 · 8 / 2 = **3.3662 m**, and the
  wood is re-sampled once the measurement lands (`noteSpread`).
- **Heights**: everything stands on tile (0, 0) of `tiles.json`, h = 2·i + j at
  64 m steps = x/32 + z/64; trees + `ground_offset_m` −0.1.
- **Triangles per instance**: full tier 17 727 indices / 3 = **5909**, low tier
  4431 / 3 = **1477** (the GLBs' accessor counts; the sidecar of the low file says
  `tris 1477, tris_before 5909`); the tuft cone 5 sides + 5 base = **10**; the
  undergrowth star 3 quads × 2 triangles × 2 windings = **12**.
- **Undergrowth cells** within 128 m of (64, 128): candidates x −1…3, z 0…4
  (25). Distance of the anchor to each cell's square per axis: x cells
  −1/0/1/2/3 → 64/0/0/64/128, z cells 0/1/2/3/4 → 64/0/0/64/128. A cell is in when
  dx² + dz² ≤ 128²: every pair except those combining 128 with a non-zero other
  axis — (3, 0), (3, 3), (3, 4), (−1, 4), (2, 4) → **20 cells**, nearest first,
  ties in string order (`0,1`, `0,2`, `1,1`, `1,2`, …).
- **Far camera** (2000, 50, 2000): every entry's instance sphere (the wood's,
  radius ≤ hypot(192, 128)/2 + 8.5 ≈ 124 m) is ~2.6 km away → every entry hidden,
  undergrowth beyond 60 m → **0 instances drawn**.
- **Counts after the LOD at the fixture camera** (40, 30, 110), forward (1, 0,
  0.5), vertical FOV 45°, aspect 16:9: NOT hand-derived — they are the reference
  script's run of `instanceTier`/`instanceVisible`/`inViewCone` over the TS
  sampler's points (fresh tiers, full tier mounted): trees 84 low + 16 full, tufts
  111 low; undergrowth 52 of 370. The check then demands triangles = 84 · 1477 +
  16 · 5909 + 111 · 10 = **219 722** for the scatter and 52 · 12 = **624** for the
  undergrowth.
- **Not in the fixture on purpose**: `along`/`edge`/`center` rows — the native
  client skips them (S3 report), and a fixture with one would make the browser's
  occupancy differ from the port's.

## Ground surfaces (Task S3b)

`node native/fixtures/ground_fixture.mjs` writes the layer bake, the library and the PNG;
`node native/fixtures/ground_reference.mjs` writes `ground_reference.json` (both deterministic: a re-run is
byte-identical). `Check/GroundCheck.cs` compares the C# port with the reference (1e-9; pairs, keys, bytes exact)
and the rest with the numbers below.

**The bake is cut down in ONE place**: `tile_m` = 32 instead of 256 (a 32² id mask and a 64² sd mask per tile;
32 because `wantedTiles` refuses more than 64 tiles per axis in its 560 m radius). Every other number is the
server's: id 1 m, sd 0.5 m, band 8 m, zero 128, 127/8 = 15.875 codes per metre,
`code = clamp(round(sd · 15.875) + 128, 1, 255)`; rule 3 of § A16.7 collapses an id texel to (own, own) when its
nearest sd texel lies farther from the line than ½ blend(A) + min(0.5, ½ blend(A)) + 1 m (path: 1 m,
forest: 2.25 m).

Layers: 0 grass (`grass`, 1.5 m), 1 forest (`forest`, 1.5), 2 path (`path_blend`, 0 = hard cut), 3 lake (water,
bed `grass`, surface `grass`, 1.5), 4 meadow (`meadow_tex`, 1.5). Tiles: 2,3 uniform forest; 3,3 forest | path at
x = 100 (path painted later = A, sd = x − 100); 4,3 path | forest at x = 140 (sd = 140 − x); 2,4 forest | grass at
z = 139 (forest = A, sd = 139 − z); 3,4 uniform meadow; 5,3 uniform lake. Overview: origin (32, 64), step 8,
24 × 24, forest except cell (0, 0) = lake and columns i ≥ 20 (x ≥ 192) = meadow.

Library: `grass` → `ground_grass.png` (4 m), `forest` → `repo:shared/surface_textures/dark_stone_2_1785267141.jpg`
(6 m; a tracked 1024 × 1024 JPEG, the SOF says so), `path_blend` = a blend (no url), `meadow_tex` → a URL the
fixture source answers 404, `unused` → never asked for. `terrain.json` types carry `surface`: forest `forest`,
path `"Path_Blend "` (trimmed + lower-cased → `path_blend`), meadow `meadow_tex`, lake `water`; grass has none.

- **Want set** around the anchor (64, 128), radius 560 m: all six tile keys; distance of the anchor to each
  32 m square: 2,3 and 2,4 → 0 (the anchor is on their corner), 3,3 and 3,4 → 32 (d² 1024), 4,3 → 64 (4096),
  5,3 → 96 (9216); ties in string order → **2,3; 2,4; 3,3; 3,4; 4,3; 5,3**, ONE request (≤ 16). Requests:
  the index (`""`), then that batch.
- **Window**: tiles x 2…5, z 3…4 → span max(4, 2) = 4 → **idSize 128, sdSize 256, origin (64, 96)**; tile 3,5
  (z 160…192) lies inside the square window but was never offered → neutral fill (0, 0) with sd byte 255 =
  (255 − 128)/15.875 = **8 m** → the point (110, 170) is bare ground although the coarse mask says forest.
- **Block distance 2 cm west of x = 100** at (99.98, 100.2): id texel ix = ⌊99.98 − 64⌋ = 35 → sd texels 70, 71,
  centres 99.25 / 99.75 → sd −0.75 / −0.25 → codes 128 + round(−11.906) = 116 / 128 + round(−3.969) = 124 →
  −12/15.875 = −0.755906 / −4/15.875 = −0.251969; fx = (99.98 − 99.25)/0.5 = 1.46 (EXTRAPOLATED past the centre)
  → sd = −0.755906 + 1.46 · 0.503937 = **−0.020157**. Pair (2, 1) (path, forest), path blend 0 → no noise push,
  hard cut at a 5 cm pixel: clamp(−0.020157/0.05 + 0.5) = **0.096850**.
- **Soft edge** at (80.4, 138.6): iz = ⌊138.6 − 96⌋ = 42 → sd texels 84, 85, centres 138.25 / 138.75 → +0.75 / +0.25
  → 0.755906 / 0.251969; fz = 0.7 → **0.403150**; pair (1, 0), forest blend 1.5 → push cap 0.5 (the noise value
  and the smoothstep come from the reference).
- **Far branch** (outside the window x 64…192, z 96…224): (33, 65) → cell (0, 0) → lake 3; (200, 100) → i 21 →
  meadow 4; (40, 150) → (1, 10) → forest 1; (−100, −100) → clamped to (0, 0) → lake 3; (192, 100) → the window's
  far edge is exclusive → i 20 → meadow 4; (63.99, 100) → i 3 → forest 1. Distance there = the band, 8 m.
- **Slices**: 0 grass → `texture:grass`; 1 → `texture:forest`; 2 path → `path_blend` has no image →
  `colour:#a08a60`; 3 lake → its surface `grass` (the bed's) → `texture:grass`; 4 meadow → the image 404s →
  `colour:#7a9a50`. Metres per tile = the library `size_m` of `surfaceOf(bed_kind || kind)` when that image
  loaded, else 3: **(1.5, 4), (1.5, 6), (0, 3), (1.5, 4), (1.5, 3)**, the remaining 59 entries (0, 3).
  2 textures loaded, 1 failed, 2 colour slices; downloads: exactly the three URLs a layer names.
- **Colour-slice bytes** (three's `SRGBToLinear` of the hex, × 255, rounded): #a08a60 → r 160/255 = 0.627451 →
  (0.627451 · 0.947867 + 0.052133)^2.4 = 0.35153 → 89.6 → **90**; g 138 → 0.25415 → **65**; b 96 → 0.11697 →
  **30**; #7a9a50 → **(50, 82, 20)**. The grass slice is the PNG's one colour everywhere: **(60, 140, 50)**.
- **Shader parameters**: `lc_near` (64, 96, 1, 128), `lc_near_sd_geom` (64, 96, 0.5, 256), `lc_sd_code`
  (128, 15.875), `lc_band_m` 8, `lc_far` (32, 64, 8, 0), `lc_far_size` (24, 24), `ng_field` (−256, −256, 256, 0),
  `ng_field_size` (3, 3), `ng_strength` 1 (the field is not flat: 0…16); bound by the terrain node (Task 23):
  `tl_normal_span` = `tl_base_step` = `tile_step_m` 2, `tl_far_geom` (−256, −256, 256, **2** levels),
  `tl_far_levels[0]` (3, 3, 256, 0); the near height window = the loaded tile (0, 0) = 0…256 grown by
  max(16, 2 · 256) = 512 → **−512…768 at 2 m = 641 × 641**, `tl_near_geom` (−512, −512, 2, **6** levels),
  `tl_near_levels[0]` (641, 641, 2, 0), rect (−512, −512, 768, 768).
  **33** uniform declarations: 11 layer cut + 4 natural ground + 14 CDLOD stage (`tl_near`, `tl_far`, both geometries,
  both level arrays, the near rect, the frame, the rings, base step, normal span, the cap texture, its geometry and
  fit) + roughness/metallic + the basement hole's `hole_rect` / `hole_on` (Task 16, off at the build); the water
  variant adds 5 `tw_*` (`tw_wave`, `tw_kind`, `tw_flow`, `tw_look`, `tw_sky`) + 4 lift uniforms (`tl_water`,
  `tl_water_sd`, `tl_water_geom`, `tl_water_levels`) = **42** — since Task 25 the fragment reads the lift's own sd
  field and lattice (`tl_sd_at`, `tl_water_geom`), the old `tw_sd` / `tw_geom` window is gone; the
  plain terrain is the 14 + its colour = **15**. Godot's dummy renderer runs the shader-language front end, so a
  shader that does not parse reports none.
- **AO** on the overview h = 4·i·j (bilinear, exact everywhere inside): at the anchor (64, 128) the four taps of a
  bilinear field average to the centre → **0**. At (−255, 128): u = (−255 + 256)/256 = 0.00390625, v = 1.5 → own
  4uv = 0.0234375; tap x + 3 → u 0.015625 → 0.09375; tap x − 3 → u < 0 → CLAMPED to the border texel → 0; the two
  z taps average to own → ring mean (0.09375 + 0 + 2 · 0.0234375)/4 = 0.03515625 → t = 0.01171875/2 = 0.005859375
  > 0 → shade −0.12 · t = **−0.000703125**. Outside the raster (−400, 0): **0**.
- **Shading normal** (span s = 2 m, n = normalize(−Δx h, 2s, −Δz h)): at the anchor the fine tile h = x/32 + z/64 →
  Δx = 4/32 = 0.125, Δz = 4/64 = 0.0625 → **normalize(−0.125, 4, −0.0625)**; at (−200, −100) (margin of the near
  window, filled from the overview): h = 4uv, u = 56/256, v = 156/256 → Δx = 16v/256 = 0.0380859375,
  Δz = 16u/256 = 0.013671875 → **normalize(−0.0380859, 4, −0.0136719)**; at (800, 0) (beyond the near rect → the
  overview lattice, clamped to its last column, u = 2): Δx = 0, Δz = 4 · 2 · 4/256 = 0.125 →
  **normalize(0, 4, −0.125)**.
- **Fallbacks**: `/play/terrain-layers` answering 503 → the plain material stays on the mesh and the log says
  `ground surfaces failed, keeping the plain material: HTTP 503 …`; the library answering 503 → still the layer
  material, every slice its catalog colour (grass `#6f9a4a`, forest `#3f6e3a`, path `#a08a60`, lake → bed grass
  `#6f9a4a`, meadow `#7a9a50`), every tile 3 m; `--plain-ground` → no request at all.

## S3c world (`s3c/`, Task S3c)

A second small world, hand-written (no byte of a real world), for the scene shapes the real payloads have and
the S1a fixtures did not: an avatar whose location is OPEN, rooms on two storeys, outdoor rooms, door/window
models, world props, a wet height tile. `heightfield.json`, `terrain*.json` and `surface_textures.json` come
from the main fixtures (fallback directory). Built with `--goto=Glass` → anchor **loc-open (64, 7.34375, 120)**
(overview: fx = 320/256 = 1.25, fz = 376/256 = 1.46875 → north 4·0.75 + 8·0.25 = 5, south 10 →
5·0.53125 + 10·0.46875 = 7.34375).

### View: rings, open location, tiers

Stream points = the avatar Pia Lund's `pos` (64, 120) and the anchor (64, 120); footprint distances (yaw 0):

- loc-open: inside → 0, and pinned (the avatar's) → **near**, OPEN, storey of room `r-ground` = **0**;
- loc-closed (−40, 100), square ±4: local (104, 20) → nearest corner (4, 4) → √(100² + 16²) = 101.27 ≤ 150 → **near**;
- loc-far (600, 128): local (−536, −8) → corner (−4, −4) → √(532² + 4²) = 532.02 ≤ 520 + 40 → **far**;
- loc-gone (2000, 2000) → **gone**: no scene request at all → **4 locations, 1 gone, 3 scenes**.

Static tiers from the start camera = anchor + (0, 24, 40) = (64, 31.34375, 160):
- loc-open building: datum = tile ground (64, 120) = 2·1 + 1.875 = **3.875**; distance √(40² + 27.46875²) =
  48.52 − 10·√½ = 41.45 < 45 → **full**. loc-closed building: datum = overview (−40, 100): fx = 0.84375,
  fz = 1.390625 → north 3.375, south 6.75 → 4.69336; distance √(104² + 60² + 26.65²) = 122.99 − 8·√½ = 117.3
  → **low** (only `full` exists → that URL). Interior/outdoor specs: near → **full** (no area detail), far → **low**.

### Primitives

loc-open (open, storey 0): storey plate L1 → **storey**; room plate of `r-up` (L1) → **storey**; plate of the
always-visible `r-garden` (thickness 0, both sides, texture `grass`) → **drawn**. Walls: contour w1 + room wall w2
on L0 → **drawn, camera-culled**; w3 of `r-up` → **storey**; the `door_prop` leaf + the `window_model` pane →
**panes 2**; the plain glass pane → **drawn** (translucent, opacity 0.3, not culled); the zero-length wall →
**degenerate**. Extras: textured tread + lift glass → **drawn 2**.
loc-closed (closed): plate of outdoor room `o1` → **drawn**; wall of `r-in` + the lift pad → **interior 2**.
loc-far (closed, no model → far shell): 2 opaque walls → **shell copies 2**; the glass wall + the riser →
**interior 2**.

drawn = 6 + 1 + 2 = **9** (plates 2, walls 5, extras 2; shell 2; culled 2); skipped = degenerate 1 + interior 4 +
storey 3 + panes 2 = **10**.

Interior mounted (Task 15 — every location mounts its interior once; Task 16 — every storey of it): loc-open w1,
w2, the plain glass pane + 2 extras + the level-1 storey plate + the `r-up` plate + w3 = 8 (the garden plate hangs
outside; the panes a model fills are not drawn); loc-closed the `r-in` wall + the pad = 2; loc-far (far ring:
primitives are part of the shell mount there too) 3 walls + the riser = 4 → **14**. The counts above (drawn,
storey …) still describe the view at the build's storey 0.

### Models

loc-open: the plan-hull building is KEPT when open (cutouts instead of a fade) → placed ONCE, its 8 surfaces wear
cut materials (Task 17) with the cutout in world xz (61, 117) (67, 117) (67, 123) (61, 123) (pin (64, 120), yaw 0),
no padding, switched OFF at fade 0 and ON after one 1/60 s frame (f = 1 − e^(−1/15) = 0.0645 > 0.03); the pin and
(66.9, 122.9) are discarded, (67.1, 120) kept; chair (`r-ground`) → prop;
lamp (`r-up`, level 1) → mounted in its room group since Task 16 (hidden at storey 0), its URL has no fixture
→ **missing**, still counted **storey**; the `door:` model (`measure: "fit"`) → door; the `window:` spec has no URL but
`placeholder_dims` → **placeholder**; the `room` diorama has neither → **missing**; bench (`r-garden`) → prop.
loc-closed: building; well (no room) → prop; shelf (`r-in`) → mounted in the hidden interior since Task 15 (near
ring, `mountDetail`), its URL has no fixture → **missing**. loc-far: post → prop at **low**.
World props (camera (64, 160), landmark LOD = scatter × 3 = 105 / 135 / 360 m, cold start `low`):
wp1 (80, 150) d = 18.87 → **full**, variant 1 → `…?variant=1&tier=full`; wp2 (64, 600) d = 440 → **culled**;
wp3 (200, 160) d = 136 > 135 → **low**.
→ placed building 2, prop 4, door 1, world 2; placeholders 1, missing 3 (diorama, shelf, lamp), interior 0, storey 1,
culled 1; tiers placed: full 6 (open building, chair, door, bench, well, wp1), low 3 (closed building, post, wp3);
building GLBs 2 × (2220 / 3330). The lamp's and the shelf's URLs are requested at the mount.

Heights (§ A16.9 lift = ground(anchor) − datum, level 0, non-building):
- chair anchor (2, −1) → world (66, 119): tile h = 2x/64 + z/64 → 2.0625 + 1.859375 = 3.921875 → lift
  **0.046875** = its bottom in the location frame (bottom_y 0);
- door anchor (−5, −1.5) → (59, 118.5): 1.84375 + 1.8515625 = 3.6953125 → bottom **−0.1796875**, height
  **2.1** (`fit` scales y to `size_m[1]`);
- placeholder anchor (−5, −3.5) → (59, 116.5): 3.6640625 → y = 0.9 − 0.2109375 = **0.6890625**, yaw 90°;
- wp1 bottom = tile ground (80, 150) = 2.5 + 2.34375 = 4.84375 + 0.5 − 0.25 = **5.09375**.

### Parser fields (Task 15)

`scene_loc-open.json` carries, by hand, one entry of every § B1 block no native code draws yet, so
`tests/ScenePayloadParseTests.cs` can read each field back: a top-level `boundary`; `r-ground` an opening (edge 3,
at 0.65, 1 × 2.1 m door to `r-garden`, prop `door:s3c0001`, mirrored) and an ambience (daylight 0.6, tint
`#ffd9a0`); `r-garden` an overlay (centre (0, 3), rect x −5 z 1 w 10 d 4, y 0.02) and an ambience with a null
tint; the floor-plan entry `floor_kind` "planks" and a `map_water` (area-pond, lake); one flight of stairs, one
prop marker (m-chair), one doorway, two problems (one `scope: "editor"`), one corridor, one boundary opening; on
models: the door's `door` block (opening 0, left, swing −1, leaf box), the diorama's `clip_outline` and
`walk_y_world` 0.05, and on the storey-hidden lamp `walkable`, `width_estimated`, `cut_plane`, `slots`, `light`,
a 3 × 2 `surface`, a `water` region and a top-level `leaf_bbox`. None of them changes a count above: the floor plan only feeds `hasInterior` of a location that has an
interior anyway (the marker, the flight, the corridor and the problems feed the places data since Task 19, see
"Places"), the lamp has no mesh fixture
(missing since Task 16 mounts storey 1), the diorama has no mesh, the door block and the rest are read by no native code yet.

### Places (Task 19)

`PlaceInventory.Compose` on loc-open (pin (64, 120), yaw 0 → tileToWorld(lx, lz, ly) = (64 + lx, 3.875 + ly, 120 + lz)):
- **m-chair** (prop marker, `r-ground`, storey 0): lift point = its anchor (2, −1) → (66, 119), lift = 3.921875 − 3.875 =
  **0.046875**; slot (2, −1) at y_world 0.45 − root_offset 0.42 + lift → **(66, 3.951875, 119)**. view=3d has no room names,
  so the only key is `r-ground`.
- **flight 0**: foot (2, 0.01, −0.9) → **(66, 3.885, 119.1)**, head (2, 3.03, −3.1) → **(66, 6.905, 116.9)**, at (2, −1.5) →
  (66, 118.5), dir = normalize(head − at) = **(0, −1)**.
- **vertical targets**: the lift glass is an `elevator_*` box → (elevator, −1); the tread names stair 0 = flight 0 →
  (stairs, 0). No `elevator_pad` → **no stop**.
- **corridor** `__floor__1`: the storey-1 plate without a room id has top 3.0 → stand (0, −2.5) at 3.0 + 0.01 →
  **(64, 6.885, 117.5)**.
- loc-closed's pad (0, 0.05, −2), size y 0.1 → stop on storey 0 at **(−40, 4.693359375 + 0.1, 98)**; target (elevator, −1).
- **problems**: of the two, the `scope: "editor"` one is skipped → **one toast** "2 rooms cannot be reached", key
  `loc-open|unreachable_rooms|`; asked again → none.
- **re-datum**: a flat tile (0, 0) at 10 m moves loc-open's datum 3.875 → 10 (+6.125). Foot/head/stand ride the step →
  10.01 / 13.03 / 13.01; the chair seat rides to 10.076875, then its lift 0.046875 → 0 takes 0.046875 off → **10.03**
  (= 10 + 0.45 − 0.42), one location with moved seats; loc-closed (overview) keeps its stop.

### Verify (§ B5a, Task 15)

`Check/VerifyCheck.cs` builds both worlds and reads each location's report. A plate checks `top_y` (+ `bottom_y`
for a body), a wall `base_y`, `top_y`, `centre.x`, `centre.z`; a placement `bottom_y` (+ its storey-0 lift),
`anchor.x/z` and — where every angle keeps the box axis-parallel — `max_m` (or `size_m.w/h` for `fit`); a spec
that placed nothing one `geladen` row. Measured: every MOUNTED plate/wall of every storey (Task 16; a pane a model
fills from its geometry), not degenerate pieces. The GLB boxes come from the glTF accessors: `building_*.glb`
18.845 × 9.14 × 14.4 (x, y, z); every model's scale is chosen so its own measure equals its `max_m` / `size_m`.

- **loc-house**: wall 4 + the level-1 plate 2 (Task 16) + building 4 (fix 90 and yaw 0 are axis-parallel: bottom,
  anchor, `max_m` 12) + the crate `geladen` 1 → **11 checked, 1 row**, models 1/2.
- **loc-yard** (yaw 30°: the box centres turn back exactly, no extent is read): the level-1 plate via its shell
  copy 2 + 7 walls × 4 = **30, 0 rows**, models 0/0.
- **loc-open**: garden plate (bare) 1 + the level-1 storey plate 2 + the `r-up` plate 2 + walls w1, w2, w3, the
  glass pane and the two panes a model fills 6 × 4 = 24; building 4, chair 4, door 5 (fit at yaw 90: size 1 × 2.1 ×
  14.4/18.845 turned → max(x, z) = 1, y = 2.1), window placeholder 4 (max of 1 × 1.2 × 0.1 = 1.2), bench 4, the
  diorama and the level-1 lamp `geladen` 1 each → **52, 2 rows**, models 5/7.
- **loc-closed**: plate 2 + wall 4 + building 4 + well 4 + shelf `geladen` 1 → **15, 1 row**, models 2/3.
- **loc-far**: 3 walls 12 + post 4 → **16, 0 rows**, models 1/1.

Cross-checks: V1 the house's merged interior wall mesh measured on its own (4 numbers, clean) and against a spec
5 cm higher (base_y/top_y, delta −0.05 each); V2 loc-open's chair against `bottom_y` + 0.1 (one row, −0.1).

### Water (tile 0, 0)

`h(i, j) = 2i + j` on the 5 × 5 lattice (step 64). Five lattice points carry a level of 6 m;
`liftedHeight = h + (w − h)·smoothstep(0, 0.5, sd)` where w > h:

| (i, j) | h | sd | gate | lifted | lift (`v_wet`) |
|---|---|---|---|---|---|
| (0, 0) | 0 | 1.0 | 1 | **6** | **6** |
| (1, 0) | 2 | 0.25 | 0.5 | **4** | **2** |
| (0, 1) | 1 | 1.0 | 1 | **6** | **5** |
| (1, 1) | 3 | −0.5 | 0 | **3** | **0** |
| (0, 2) | 2 | 0.125 | 0.15625 | **2.625** | **0.625** |
| (2, 0) | 4 | dry | 0 | **4** | **0** |

→ **1 wet tile, 5 wet texels**; the fragment's fields ride on the NEAR lattice at 2 m with the lift's (Task 25): sd at
world (64, 0) = the tile's (1, 0) = **0.25**, at (32, 0) the mix (1 + 0.25)/2 = **0.625**, at the dry (128, 128)
**−10 000**; one look row and no flow → every row 0, every flow (0, 0);
the layer table's only water layer `lake` → **1 look row**, its surface `water` has no library entry and no
painted area carries a profile → the default look, opaque depth ¾ · 2 = **1.5 m**, water areas **0**. With
`--no-water`: no lift, no wet program, no variant, `water[off: --no-water]`. The lift is drawn by the wet program's
vertex stage (Task 23); the table's points inside the s3c frame (z ≥ 36) are checked through the shader twin in
"CDLOD terrain" T5.

### Shaders

Every spatial shader goes through the headless front end once and logs one line; the check requires
`ground`, `ground-water`, `terrain-plain` (Task 23), `recipe[opaque]`, `recipe[translucent]` and `recipe[opaque,both-sides]` to be
`compiled (N uniforms)` with N = the shader's own uniform count, and the plan hull's cut shader
`cut[std+cutouts]` with **18**: the generator's 14 uniforms of a glTF material without emission/normal/AO/alpha
(albedo, texture_albedo, albedo_texture_size, point_size, roughness, texture_metallic, metallic_texture_channel,
texture_roughness, specular, metallic, uv1_scale, uv1_offset, uv2_scale, uv2_offset) + cut_pts, cut_off, cut_len,
cut_on.

## Storeys world (`storeys/`, Task 16)

A third small world, hand-written, for the storey switch at runtime (`Check/StoreysCheck.cs`, `--check storeys`):
a tower with a cellar, a ground floor, an upper floor and an always-visible terrace on it, and a pit whose ground
model covers a basement. Heightfield, tiles, terrain layers and surface textures come from `fixtures/` (fallback).
Built with `--goto=Tower`; the avatar Tess Vale stands in `r-hall` of loc-tower → **loc-tower near, OPEN, storey 0**
(the browser's buildTile starts every tile at 0; the avatar's storey is followed only when embodied); loc-pit at
(−40, 100), the s3c loc-closed position → **near** (101.27 m), closed. Datums: tower = tile ground (64, 120) =
2·1 + 1.875 = **3.875**; pit = overview (−40, 100) = **4.693359375** (see "S3c world").

**Tower** (`scene_loc-tower.json`, yaw 90°, boundary ±6 × ±4, storey_m 3, levels −1 / 0 / 1 at floor_y −3 / 0 / 3).
Rooms: `r-cellar` (−1), `r-hall` (0), `r-study` (1) inside; `r-terrace` (1, always visible) off the tile.

| piece | unit | storey −1 | storey 0 | storey 1 |
|---|---|---|---|---|
| P1 slab −1 (ground) | interior, slab −1 | shown | – | – |
| P2 `r-cellar` plate (ground, ghost 1 → no twin) | room `r-cellar` | shown | – | – |
| P3 slab 1 (upper) | interior, slab 1 | – | – | shown |
| P4 `r-study` plate (upper, ghost 0.4) | room `r-study` | – | – | shown, **solid** |
| P5 `r-terrace` plate (upper, ghost 0.4, bare) | room `r-terrace` (outdoor) | shown, ghost | shown, **ghost** | shown, **solid** |
| W1 cellar wall | room `r-cellar`, wall −1 | shown | – | – |
| W2 hall wall | room `r-hall`, wall 0 | – | shown | – |
| W3 contour wall (no room, t 0.25) | interior, wall 0 | – | shown | – |
| W4 study wall (upper) | room `r-study`, wall 1 | – | – | shown |
| W5 glass pane (no room) | interior, other | shown | shown | shown |
| E1 stair tread, E2 lift shaft | interior, other | shown | shown | shown |

Rule per row: a room group shows when outdoor or on the storey (`roomVisible`); a slab on its storey; an outline
wall on its storey (fade > 0.03); a room plate solid on the displayed storey, its composed ghost elsewhere
(`storeyPieceOpacity` — so the terrace floor is 40 % at storeys 0 and −1 and solid at 1, both directions). The desk
(`r-study`, level 1) and the barrel (`r-cellar`, −1) are placeholders in their room groups → shown only at 1 / −1.

- **Interior mounted**: P1–P4 + W1–W5 + E1, E2 = **11** (P5 hangs off the tile); pit P1 + W1 = 2 → **13**.
- **Stats at the build (open, storey 0)**: drawn = P5 (outdoor) + W2, W3, W5 + E1, E2 = **6** (plates 1, walls 3,
  extras 2, culled walls 2 = W2, W3); storey = P1–P4 + W1, W4 = **6**; the pit (closed, its ground model stands)
  → interior **2**; models storey = desk + barrel = **2**; placeholders desk, barrel, the pit's model = **3**.
- **Verify (every storey)**: tower plates P1–P4 2 each + P5 1 = 9, walls 5 × 4 = 20, desk and barrel 4 each (yaw 0:
  bottom, anchor x/z, `max_m` = the largest placeholder side, 1.2 / 0.9) → **37, 0 rows, models 2/2**; pit slab 2 +
  wall 4 + its building placeholder 4 (8 × 0.5 × 8, `xz` 8) → **10, 0 rows, 1/1**.
- **Level switch**: 3 declared storeys → buttons **−1. EG 1.** (ascending; `EG` for 0); the first lift box E2 (the
  tread E1 comes first but never anchors) → (4, −1.5). Tile-local (4, floor_y(lv) + 2, −1.5), turned by 90°
  (x = 64 + lz, z = 120 − lx) → world **(62.5, 3.875 + 2 + floor_y, 116)**: y 5.875 / 8.875 / 2.875 at 0 / 1 / −1.
  The active button follows the filter. The pit (levels −1, 0) has buttons **−1. EG**.
- **Room labels** (names from `locations.json`; `__floor__1` has an empty name → none): hulls = `floor_plan` for
  `r-hall` (x −6…0 → centre (−3, 0)), the room outline for the other storeys (`r-cellar` (0, 0), `r-study` (−3, 0),
  `r-terrace` (3, 0)); y = floor_y + min(1.5, 0.8·3) = floor_y + 1.5; turned → Hall **(64, 5.375, 123)**, Study
  **(64, 8.375, 123)**, Cellar **(64, 2.375, 120)**, Terrace **(64, 8.375, 117)**. Drawn at fade > 0.5 where the room
  group shows: storey 0 → Hall, Terrace; 1 → Study, Terrace; −1 → Cellar, Terrace. The pit has a display-ground
  model → an area location → no labels.
- **Door marks** (a building in the near ring; one group per DECLARED storey): D1 (−1, width 1, depth max(0.3,
  W1 0.2) = 0.3, at (0, −3 + 0.02, −4)), D2 (0, width 1.2, depth max(0.36, W2 0.2 — the first non-pane wall of
  storey 0) = 0.36, at (−3, 0.02, 4)), D3 width 0 → none, D4 (1, width 0.9, depth max(0.27, W4 0.2) = 0.27, at
  (−3, 3.22, −4)), D5 storey 2 is not declared → none → **3 marks on 3 storeys**, yaw atan2(−0, 1) = 0 (tile frame).
  Shown at fade > 0.5, only the filter's storey.
- **Locks**: `lockedRooms {r-terrace}` answered for loc-tower, avatar in `r-hall` → D4 (`r-study`, `r-terrace`)
  red, D1/D2 gold; avatar on the terrace → its own room is left out → all gold; the same map answered for loc-pit →
  nothing painted in the tower. `lockedLocations {loc-tower}` → its boundary mark shows.
- **Boundary mark**: opening at (6, 0), width 2, inward (−1, 0) → world (64, 114), inward (0, 1) → yaw 0, scale
  (2, 1, max(0.6, 0.3) = 0.6), y = ground(64, 114) + 0.05 = 2 + 1.78125 + 0.05 = **3.83125**.
- **Basement hole**: storey −1 of the tower, camera (100, 30, 147): bounds of the turned boundary x 60…68,
  z 114…126; camera − centre = (36, 27), length 45 → u = (0.8, 0.6) → maxX + 12·0.8, maxZ + 12·0.6 →
  **[60, 114, 77.6, 133.2]**; off at storeys 0 and 1 and once the tower closes. The pit at −1 (camera (−10, 30, 140):
  u = (0.6, 0.8), width 8) → **[−44, 96, −31.2, 110.4]**, its ground model hidden; back at storey 0, or at fade
  exactly 0.03 (the gate is > 0.03).
- **Switch input** (1600 × 900, camera on the anchor at 20 m → the box centred at (800, 450) ± 1 px): a left click
  on `1.` → storey 1, the camera's click counter stays 0; a right-drag starting on `G` turns nothing; a click at
  (200, 800) → the camera's click (1).

## Fidelity world (`fidelity/`, Task 17)

A fourth small world, hand-written, for model fidelity (`Check/FidelityCheck.cs`, `--check fidelity`). The ground
files come from this directory (heightfield, tile (0,0) with h[j][i] = 2i + j at 64 m steps, i.e. ground(x, z) =
2x/64 + z/64 on the tile). The three GLBs are written by `fidelity/make_glbs.py` (stdlib, see its docstring):
`hull_full.glb` / `hull_low.glb` (a closed 10 × 2 × 10 m box, no metallicFactor, node extras
`interior_cutout_padding_m: 0.25`) and `box.glb` (1 m cube, metallicFactor 1 with a metallicRoughnessTexture).

| location | pin, yaw | datum | scene |
|---|---|---|---|
| loc-hull "Hull" | (64, 120), 0° | tile 2 + 1.875 = **3.875** | plan-hull building (full/low) with the cutout (−3,−3)…(3,3); room diorama `r-hall` (box, max_m 4) with clip (−5,−5)…(5,0) |
| loc-prop "Workshop" | (−40, 100), 90° | overview **4.693359375** | prop `table` (box, anchor (1, 2)) with cut_plane n (1,0,0) c −0.5; placeholder `crate` (no URL, 1 m dims) with cut_plane n (0,0,1) c 0 |
| loc-area "Quarry" | (20, 140), 0° | 40/64 + 140/64 = **2.8125** | `area_detail`, display `shell_area` building (hull_full) with the cutout (−2,−2)…(2,2); outdoor prop `stone` (box, anchor (3, 0)) |

`scene_loc-hull.v2.json` is the same hull scene with signature `hull-2` and the diorama's anchor at (0, −1).

- **F1** hull_full's material had no metallicFactor (glTF 1.0, untextured) → **0**; box keeps **1** (textured) →
  1 neutralised at the boot, **2** once hull_low is loaded by the first swap.
- **F2** cut shaders: `cut[std+cutouts+pad]` **18** (14 + 4, padding is a define), `cut[std+clip]` **15**,
  `cut[std+plane]` **15**, the placeholder `cut[shaderN+plane]` **N + 1** with N = the recipe placeholder shader's
  count. 5 cut placements (hull, diorama, table, crate, area), one surface each, the stone none.
- **F3** hull: scale 10 / 10 = 1 → padding 0.25 (square 0.0625); world cutout x 61…67, z 117…123: (64, 120) inside,
  (67.2, 120) and (60.8, 120) 0.2 m outside → discarded by the padding, (67.3, 120) and (64, 123.3) 0.3 m outside →
  kept; switched off nothing goes. Clip world (59, 115) (69, 115) (69, 120) (59, 120): (64, 118) kept, (64, 121)
  dropped. Table at yaw 90° (local x → world −z, local z → world +x): plane point (0.5, 0, 0) → world z 99.5,
  n (0, 0, −1), c **99.5** (z 99 kept, z 100 dropped); crate n (1, 0, 0), c = −(1 · −40) = **40** (x −39 kept, x −41
  dropped).
- **F4** both opened, one frame: the hull's cutouts on; the shell area's stay shut and its model is a roof part.
- **F5** boot camera = anchor (64, overview 7.34375, 120) + (0, 24, 40): |(0, 27.46875, 40)| = 48.5235, − 12·√½ =
  40.04 < 45 → **full**. Cameras straight behind the pin at d + 12·√½: 70 → **low** (swap), 44 → **full** (swap),
  50 → stays full (no swap), 61 → **low** (swap); each swap replaces the node in the group, the old one leaves the
  tree, the cut handle is new and on (the hull is open).
- **F6** a flat tile (0,0) at 10 m: hull 3.875 → **10**, area 2.8125 → **10** (2 datums), prop unchanged (overview);
  the stone's lift ground(23, 140) − 2.8125 = 2.90625 − 2.8125 = 0.09375 → **0** (moves by −0.09375, 1 re-lifted);
  the diorama's anchor is the pin (lift 0 before and after).
- **F7** a sweep with unchanged signatures remounts nothing (3 scene requests); with `scene_loc-hull.v2.json` only
  loc-hull is remounted: new slot, signature `hull-2`, still open, its group at today's datum 10, the diorama
  centred at z −1, the old group freed.

## Props world (`props/`, Task 18)

A fifth small world, hand-written, for texture slots, mirrors, prop lights, doors and ambience (`Check/PropsCheck.cs`,
`--check props`). Ground files from this directory (ground(x, z) = 2x/64 + z/64 on tile (0,0)). GLBs and the picture are
written by `props/make_glbs.py` (stdlib, see its docstring): `frame.glb` (wood / slot_picture_1 / slot_glass_1 quads,
extent 1), `mirror.glb` (wood quad + the pane of smoke_mirror_plane [1], extent 1.2), `door.glb` (nodes `frame` and
`leaf`, the leaf box (0.05, 0, 0)…(0.85, 2, 0)), `poster.png` (2 × 2). The world map carries `game_time.hour_fraction` 22.

**loc-room "Lamp House"**, pin (64, 120), yaw 0, datum tile 2 + 1.875 = **3.875**; levels −1 (floor −3) and 0. Rooms:
`r-parlour` (±5, ambience daylight 0.4, tint #ffcf9a; floor_plan ±5), `r-closet` (2…4, no ambience; floor_plan),
`r-cellar` level −1 (outline (−5…−3)², ambience 0.2 / #8899ff), `r-hall` (the corridor block, ambience 0.8, no tint;
`corridors[]` outline ±6). A storey-0 non-building placement at local (x, z) is lifted by ground − datum =
(2x + z)/64.

- **P1** `frame` (anchor (−3, −4), bottom 1, a keep-all cut_plane n (0,1,0) c 10 so every surface is cut): the picture
  surface's cut clone takes `texture_albedo` = the 2 × 2 poster, `albedo_texture_size` (2, 2), albedo white; the glass
  surface's cut clone comes from the glass preset (albedo alpha **0.3**, roughness **0.06**, metallic **0**, blend_mix,
  cull_disabled); the wood's clone has no texture and alpha 1; the template keeps no texture and an opaque glass
  material; `frame-2` (same GLB, no slots, no cut) has no override at all.
- **P2** mirrors `mirror-a/b/c` at anchors (0, 4), (−2, 4), (2, 4), max_m 1.2 = extent → scale 1; fix −centre
  (0.1, 0.3, 0.15) and outer y = 0.6 + lift seat the pane centre (0.1, 0.3, 0.2) at tile (x, 0.6 + lift, 4.05): A lift
  4/64 → world (64, **4.5375**, 124.05), B lift 0 → (62, 4.475, 124.05). The measured plane is the pane's own surface:
  (0.1, 0.3, 0.2), |n_z| = 1. Closed: the interior is hidden → **0** passes; opened and faded in, a camera at
  (64, 4.5375, 128.05) looking −z sees all three: budget 2 over the panes in list order P0, P1, P2 → frames
  **{P0,P1} {P0,P2} {P1,P2}**. Reflection of A: d = 4, eye′ (64, 4.5375, **120.05**), back (0,0,−1), right (−1,0,0),
  window x_c ∈ [−.25, .25], y_c ∈ [−.5, .5] → size **1**, offset (0, 0), near **4**. B: x_c = −(x − 64) ∈ [1.75, 2.25],
  y_c = y − 4.5375 ∈ [−0.5625, 0.4375] → offset (**2**, **−0.0625**), size 1, near 4. Godot's own
  `UnprojectPosition` of B's camera (512 px): the pane centre → (256, 256), the corner (61.75, 4.975, 124.05) → u =
  (2.25 − 1.5)/1 = 0.75, v = (0.4375 − 0.4375)/1 = 0 → **(384, 0)**, and the lookup rows give the same (0.5, 0.5) /
  (0.75, 0). A camera at z 160 (36 m) refreshes nothing (all panes have rendered).
- **P3** lamps 1…8 at local (x, 0), x = 1, −2, 3, −4, 5, −6, 7, −8 (range 4 → cutoff 34; lamp 2 `night` with glow 0.1,
  lamp 3 in the cellar at level −1 / bottom −3, lamp 4 candle with glow 0.12, lamp 5 fire), height 2: world
  (64 + x, 3.875 + x/32 + 2, 120) — lamp 1 (65, **5.90625**, 120); lamp 3 has no lift (level −1): (67, **2.875**, 120).
  The lantern row at (−40, 100) is 107 m from the focus (64, 5.875, 120). Night 1, storey 0 (cellar hidden): by
  distance **1, 2, 4, 5, 6, 7**. Second tick: gain 0.5 → lamp 1's energy 2 · 0.5 / π = **0.3183099** (Task 21: Godot energy = three intensity / π);
  candle within ±8 %; fire colour between #ffb35c and #ff6a20. Day (night 0): lamp 2 drops, survivors keep their
  slots, lamp 8 fills slot 1 → **1, 8, 4, 5, 6, 7**; lamp 2's halo hides. Cellar storey (night 1): only the cellar room
  is shown → **3**; the parlour's halos hide.
- **P4** `door:0` (fit, opening 0 → doorway at (0, −5), level 0, rooms [r-parlour], swing +1): pivot at
  LeafPivot((0.05,0,0)…(0.85,2,0), fix 0) = (min x, min y, centre z) = **(0.05, 0, 0)**, axis +y; the leaf's own position
  (−0.05, 0, 0) so leaf + pivot = its original (0, 0, 0). Overview: angle **0**. An avatar 1 m away for one 60-fps
  frame → **0.05** rad; the next overview frame eases it back to 0 (|0.05| ≤ one step).
- **P5** the open location, focus at local (0, 0) → parlour (area 100; the cellar rect (−4, −4) is elsewhere);
  (3, 3) → the closet (area 4) → no ambience; (5.5, 5.5) → no rect → the corridor r-hall → 0.8; (−4, −4) → the cellar
  rect (area 4 < 100, any storey) → 0.2; a closed / unknown location → none. Stage at noon (sun 2.25, fill 0.55, hemi
  1.55), from neutral towards the parlour for dt 0.5: k = 1 − 1/e, daylight 1 − 0.6k = **0.6207276647** → sun
  2.25·d/π = 0.444563, fill 0.55·d/π = 0.108671, ambient 1.55·d/π = 0.306255;
  tint g = 1 − (48/255)k = 0.8810126, b = 1 − (101/255)k = 0.7496307 (the sun's red stays 1); then 4 × 0.125 s back to
  neutral = one τ: 1 − (1 − 0.62073)/e = **0.8604735** → sun 2.25·0.8604735/π = 0.616269.
- **P6** a flat tile (0,0) at 10 m: datum 10, lamp 1's lift 0 → (65, **12**, 120).
- **P7** `game_time.hour_fraction` 22 → sin((16/12)π) < 0 → night **1**.

## Light (Task 21, `Check/LightCheck.cs`, no fixture world)

The stage of `World/StageAmbience.Build` (the call Main makes), read back from Godot. Sources: engine.ts (constructor,
`setGameHour`, `applyAmbience`, frame()), skyLight.ts `gameHourLights`, three r185 ColorManagement, Godot 4.7.2
`color.h` / `light_storage.cpp` / `render_scene_data_rd.cpp`.

**Mapping.** three lights a Lambert surface with albedo/π · I · colour · N·L (directional) and albedo/π · I · mix(G, S,
½ + ½·n.y) (hemisphere); Godot with albedo · E · colour · N·L (energy ×π in light_storage.cpp, Lambert ÷π) and albedo · E
· colour (ambient, no π). So **E = I / π**. A light/ambient/background `Color` is sRGB-encoded (Godot decodes it with
`srgb_to_linear`), so a three linear colour c goes in as `linear_to_srgb(c)` with Godot's exponent 1/2.4; an unblended
hex therefore arrives as **its bytes / 255** (three's decode and Godot's decode are the same formula). The water's
`tw_sky` takes the sRGB BYTES of `getHex(sky · daylight · tint)` / 255, as scene-render's `setSurfaceSky` does.

**Hours** (a = (h − 6)/12 · π, day = clamp(sin a, 0, 1), dusk = clamp(1 − |h − 12|/6, 0, 1); I_sun = 0.25 + 2·day,
I_hemi = 0.35 + 1.2·day, I_fill = 0.15 + 0.4·day; offset (60 cos a, 80 max(0.08, sin a), 25), the light's +Z = the offset
normalised; night = clamp(1 − 3·day, 0, 1)):

| h | day | sun → Godot | sky → Godot / tw_sky bytes | E sun / hemi / fill | +Z (towards the sun) | night |
|---|---|---|---|---|---|---|
| 6 | 0 | moon 9fb4e0 → (159, 180, 224)/255 | night 1a2340 → (26, 35, 64)/255 | 0.25/π, 0.35/π, 0.15/π | (60, 6.4, 25)/√4265.96 = (0.918635, 0.097988, 0.382764) | 1 |
| 7 | sin 15° = 0.258819 | warm→noon by smoothstep(0.522048) = 0.533050: linear (1, 0.676035, 0.428080) → (1, 0.841203, 0.685835) | day→dusk by (0.35 − 0.2588)/0.2 = 0.4559: → (0.771432, 0.707033, 0.732679); bytes (197, 180, 187) | 0.767638/π, 0.660583/π, 0.253528/π | (57.9555, 20.7055, 25)/66.4265 = (0.872468, 0.311703, 0.376352) | 1 − 3·0.2588 = 0.223543 |
| 9 | 0.707107 | noon fff2d8 → (255, 242, 216)/255 | day 9fc7e8 → (159, 199, 232)/255 | 1.664214/π, 1.198528/π, 0.432843/π | (42.4264, 56.5685, 25)/75 = (0.565685, 0.754247, 0.333333) | 0 |
| 12 | 1 | noon | day | 2.25/π = 0.716197, 1.55/π = 0.493380, 0.55/π = 0.175070 | (0, 80, 25)/83.8153 = (0, 0.954480, 0.298275) | 0 |
| 18 | 1.2e-16 (≤ 0.05) | moon | night (dusk 0 → factor 0.3 · 0) | 0.25/π, 0.35/π, 0.15/π | (−60, 6.4, 25) → (−0.918635, 0.097988, 0.382764) | 1 |
| 22 | 0 (sin 240° < 0) | moon | night | 0.25/π, 0.35/π, 0.15/π | (60 cos 240°, 6.4, 25) = (−30, 6.4, 25)/39.5722 = (−0.758108, 0.161730, 0.631756) | 1 |

Proof per hour: Godot's renderer colour `Color.SrgbToLinear() · E · π` equals three's linear colour · I (1e-5).

**Before the clock** (constructor): sun 2.0/π = 0.636620, hemi 1.5/π = 0.477465, fill 0.5/π = 0.159155, sun fff2d8,
sky 9fc7e8; an ambience applied now changes nothing (`applyAmbience` has no `baseLights` yet); `tw_sky` stays.

**Hemisphere** S = linear(dfeeff) = (0.737911, 0.854993, 1), G = linear(8a9a78) = (0.254152, 0.323470, 0.188021).
Ambient colour (S + G)/2 = (0.496031, 0.589068, 0.593910) → Godot (0.732737, 0.791229, 0.794121); pair colour (S − G)/2 =
(0.241879, 0.265925, 0.406090) → Godot (0.529008, 0.552531, 0.669733); all three at E = I_hemi/π. Godot's sum
ambient·E + pair·E·max(0, n.y) − pair·E·max(0, −n.y) at noon: n.y = 1 → 1.55·S/π = (0.364070, 0.421837, 0.493380); n.y = 0
→ 1.55·(S + G)/2/π = (0.244732, 0.290635, 0.293024); n.y = −1 → 1.55·G/π = (0.125394, 0.159433, 0.092667) — three's values.
Fill from (−30, 20, −25) to the origin: /√1925 → (−0.683763, 0.455842, −0.569803).

**Ambience** daylight 0.5 at noon: every energy halved; tw_sky = getHex(linear(9f, c7, e8) · 0.5) = (0.173352, 0.285562,
0.403476) → sRGB bytes (116, 146, 170); the background stays.

**Shadow fit** max distance ceil((d + 70)/10)·10: d 80 → 150, 5 → 80, 150 → 220. Godot's fit at 150 m (45° vertical,
16:9, near 0.2): far corners (±110.4569, ±62.1320, 150), centre z 75.1, radius √(110.4569² + 62.1320² + 74.9²) = 147.2112
× 4096/4094 = 147.2831 → texel 2r/4096 = **0.0719156 m** (browser 140/2048 = 0.0683594 m). Atlas 4096 (Godot default).

**Materials** `building_original.glb`: all 8 materials Lambert + `DisableReceiveShadows` after `GlbLoader.BrowserLook`;
the scatter shader `diffuse_lambert, shadows_disabled`; a terrain tile `CastShadow = Off`; `--msaa` default 4×, `0` off.


## Fog (Task 22, `Check/FogCheck.cs`, no fixture world)

Sources: three r185 `fog_vertex` / `fog_fragment` / `meshphysical.glsl.js` (fog AFTER `colorspace_fragment`),
`WebGLMaterials.refreshFogUniforms` + `getUnlitUniformColorSpace` (fog colour in the output space when the canvas is the
target), engine.ts (`THREE.Fog(sky, 220, 520)`, `setGameHour` copies the sky into it), fogConstants.ts; Godot 4.7.2
`scene_forward_clustered.glsl` (`fog_process`: `length(vertex)`, linear-space mix), `resolve.glsl` (MSAA depth = mean).

**One path.** Godot's Environment fog is off and no material fogs itself; one screen pass (`Sky/FogPost.cs`, a 2 × 2
quad under the camera, material priority 127) fogs the finished picture.

**Factor.** Overview camera near n = 0.2, far f = 800. Godot's reverse-Z depth d = n(f − z)/((f − n)z), the pass gets
the view depth back as z = nf/(d(f − n) + n) (z = 370 → d = 0.2·430/(799.8·370) = 2.906132e-4). t = (z − 220)/300,
fog = t²(3 − 2t): 0.2 m and 220 m → 0, 295 → ¼ → 0.15625, 370 → ½ → 0.5, 445 → ¾ → 0.84375, 520 and 799 → 1. Depth 0
(nothing drawn) is the sky and stays.

**Colour.** three shows mix(sRGB(colour), sRGB(sky), f). A wall pixel of bytes (60, 62, 58) at 370 m: noon sky 9fc7e8 →
((60 + 159)/2, (62 + 199)/2, (58 + 232)/2) = (109.5, 130.5, 145.0); 22:00 sky 1a2340 → (43, 48.5, 61). (A linear-space
mix — Godot's own fog — would show (122.4, 151.0, 174.3) at noon.) The pass's `fog_srgb` is three's LinearToSRGB of the
clock sky: boot 9fc7e8 → (159, 199, 232)/255, 07:00 → (0.771432, 0.707033, 0.732679), 22:00 → (26, 35, 64)/255; the
room ambience does not change it.

## Backdrop (Task 22, `Check/BackdropCheck.cs`, no fixture world)

Sources: backdrop.ts (`ridgeGeometry`, `applyTint`, `sync` key), backdropProfile.ts (vector-checked in
`BackdropVectorTests`), main.ts (`takeBackdrop` on every poll, the frame hook `position.set(target.x, 0, target.z)`).

**Strips.** 96 segments = 3.75°. Arc [90, 135]: start (90°, 0), nodes i = 25 … 35 (11), end (135°, 0) → 13 points →
12 quads → 48 vertices, 72 indices per ring. Full ring [0, 360]: 96 nodes + the closing one = 97 points → 96 quads → 384
/ 576. Two arcs [0, 45] + [45, 90]: 13 + 13 points, the join pair (45°, 0) → (45°, 0) skipped → 24 quads.

**Heights** (every draw ½, height 120): front node = 120·(0.45 + 0.55·½) = 87, back 150·0.725 = 108.75; node 30
(112.5°) is the peak vertex 25 at (380 sin 112.5°, 87, 380 cos 112.5°) = (351.0742224, 87, −145.4197043); node 25
(93.75°) is 3.75° into the arc → taper t = 0.3125 → t²(3 − 2t) = 0.2319336 → 20.17822266. Seeded:
backdrop.json "[20] ridge seeded north" (seed 7, [157.5, 202.5], 100 m, 8 segments) puts 66.38405470992438 at 180° →
quad 0's vertex 3 at (0, 66.384, −380).

**Winding.** Godot's front faces wind clockwise: three's (b, b+1, b+3)/(b, b+3, b+2) is emitted as (b, b+3, b+1)/(b, b+2,
b+3); the front normal −(v1 − v0)×(v2 − v0) of the first triangle at 0° is ∝ (−0.81h, 0, −24.85h) — towards the centre.

**Tint** mix = min(0.92, 0.30 + 0.55·night + 0.18·layer), linear lerp of the base rock to the sky, sent as Godot channels:
front by day lerp(5f6d84, 9fc7e8, 0.30) = linear (0.184116, 0.278386, 0.403604) → (0.466243, 0.564235, 0.667881); back by
day (0.48) → (0.547455, 0.662256, 0.773704); at night (sky 1a2340) front 0.85 → (0.175381, 0.212774, 0.309809), back
1.03 → capped 0.92 → (0.168005, 0.203566, 0.301058).

## CDLOD terrain (Task 23, `Check/TerrainCheck.cs`, `--check terrain`)

Sources: terrainLod.ts (`createTerrainLod`: `setField`, `buildFar`, `buildNear`, `buildWater`, `buildSd`, `update`,
`patchGeometry`, the GLSL generators), ground.ts (`plateExtent`, `BASE_MARGIN_M` 60). The selection maths
(`selectLodNodes`, `selectLodFitted`, `lodRanges`, `lodLambda`, `nodeBounds`, the cap functions, `lodVertex`) is
`Core/Terrain/TerrainLod.cs`, vector-checked in `dotnet test` (terrain_lod.json); `nodeHasWater` has no shared vector
yet — its hand cases (smoke_terrain_lod.mjs § (c)) run in `TerrainFieldTests`.

**T0 shaders.** ground **33**, ground-water **42** (Task 25: was 44 with the separate fragment window), terrain-plain **15** uniforms (counts under "Ground surfaces"). The
text prints `TL_PATCH_N = 32.0`, `TL_MORPH_START = 0.5`, `TL_CAP_NONE = 6.0`, six rings, the descent j = 5 … 1, the
outline band `sd / 0.5` and `TL_SD_DRY = -10000.0` — the twin (`Core/Terrain/TerrainShaderTwin.cs`) reads the same
numbers from C#. Only the wet program has `tl_lift`.

**T1 the main fixture's field.** Base step = `tile_step_m` 2 → leaf 32 · 2 = 64 m, root 64 · 2⁵ = 2048 m.
- Near pyramid: the near window (−512 … 768 at 2 m, "Ground surfaces") → 641; each next level (c − 1)/2 + 1 →
  321, 161, 81, 41, 21 (6 levels); first rows 0, 641, 962, 1123, 1204, 1245; texture 641 × **1266**.
- Far pyramid: the overview 3 × 3 at 256 m, round-to-nearest at its own lattice = the heights; next (3 − 1)/2 + 1 = 2
  → 2 × 2 at 512 m = the corners (0, 0, 0, 16); next would be 1 → stop: **2 levels**, texture 3 × 5 (the level-1 rows
  padded with 0): data 0,0,0, 0,4,8, 0,8,16, 0,0,0, 0,16,0.
- Frame: `world_bounds` (−104, −203) … (300, 134) ± 60 → **(−164, −263) … (360, 194)**.
- Range: from (0, 0) over both level-0 lattices: the far corner 16, the near window clamps the overview there too →
  **(0, 16)**. Stats: tile 0,0 (min 0, max 12, err 0) → every level error 0 → the rings are the geometric ladder
  **128, 256, 512, 1024, 2048, 4096** at any pixel scale.
- Node bounds: a square over tile 0,0 (and ≤ 64 tiles) = (0, 12) (0,0 seen; the other covered tiles unseen → min/max
  with 0); a square that covers no known tile = the range (0, 16).

**T2 far camera (98, 10000, −34.5).** Roots: x ⌊−164/2048⌋ = −1 … ⌊(360 − ε)/2048⌋ = 0, z −1 … 0 → 4 roots, each
overlaps the frame. Box distance ≈ 9984 > every ring → no split; λ = 6 (the last ring starts at 2048 + ½·2048 = 3072
and ends at 4096) → morph 6 − 5 = **1**. **4 pieces** (−2048, −2048), (0, −2048), (−2048, 0), (0, 0), size 2048,
level 5, 32 cells → 4 · 2048 = **8192 triangles**, 1 draw.

**T3 the bench start camera (64, 31.5, 168)** (anchor + (0, 24, 40)). A node at level L splits while its box distance
d < ring[L − 1]; each child that is still inside ring[L − 1] is visited at L − 1, else emitted as a parent QUADRANT
(child size, level L, 16 cells); a child outside the frame is skipped (x ≥ 360, z ≥ 194, x + size ≤ −164,
z + size ≤ −263). dy = 31.5 − 12 = 19.5 over tile 0,0, 31.5 − 16 = 15.5 elsewhere. Roots in z-then-x order:
- Root (−1, −1): d = √(64² + 168² + 15.5²) = 180.44 → down the only overlapping children (−1024, −1024) → (−512, −512)
  → level 3 children (−256, −512) d √(64² + 424² + 15.5²) = 429.08 < 512 → level 2, ≥ 256 → **whole L2**;
  (−256, −256) d 180.44 → level 2 splits: (−256, −256) d √(192² + 296² + …) = 353.16 ≥ 256 → **quadrant L2**,
  (−128, −256) d 303.24 → **quadrant L2**, (−256, −128) d 255.59 < 256 → level 1, ≥ 128 → **whole L1**,
  (−128, −128) 180.44 → **whole L1**. 5 pieces.
- Root (0, −1): d = √(168² + 15.5²) = 168.71 → (0, −1024) → (0, −512) → level 3 children: (0, −512) d 424.28 →
  **whole L2**; (256, −512) d 465.70 → **whole L2**; (0, −256) d 168.71 → splits: (0, −256) 296.41 **quadrant L2**,
  (128, −256) 303.24 **quadrant L2**, (0, −128) 168.71 **whole L1**, (128, −128) 180.44 **whole L1**; (256, −256)
  d 255.59 < 256 → splits: (256, −256) 353.16 **quadrant L2**, (384, ·) outside, (256, −128) 255.59 **whole L1**.
  8 pieces.
- Root (−1, 0): d = √(64² + 15.5²) = 65.85 → (−1024, 0) → (−512, 0) → (−256, 0) at level 2 splits: (−256, 0)
  196.73 **whole L1**; (−128, 0) 77.05 → level 1 splits into 64 m children: (−128, 0) dx 128, dz 104 → 165.6 ≥ 128
  **quadrant L1**, (−64, 0) √(64² + 104² + 15.5²) = 123.09 **leaf**, (−128, 64) 134.99 **quadrant L1**, (−64, 64)
  77.05 **leaf**; (−256, 128) 192.62 **whole L1**; (−128, 128) 65.85 splits: (−128, 128) 128.94 **quadrant**,
  (−64, 128) 65.85 **leaf**, (−128, 192) √(128² + 24² + …) **quadrant**, (−64, 192) 70.08 **leaf**. 10 pieces.
- Root (0, 0): d = 19.5 → (0, 0) → (0, 0) → level 3 children (0, 0) d 19.5 and (256, 0) d 192.62. (0, 0) at level 2
  splits into four 128 m nodes (d 44.5, 77.95, 19.5, 66.91 — all < 128), each into four 64 m children; a child's dx
  is 0, 0, 64, 128 for x₀ = 0, 64, 128, 192 and dz 104, 40, 0, 24 for z₀ = 0, 64, 128, 192; with dy 19.5 every
  child with x₀ ≤ 128 stays < 128 (worst √(64² + 104² + 19.5²) = 123.66) → **12 leaves**, the x₀ = 192 column
  ≥ √(128² + 19.5²) = 129.48 → **4 quadrants L1**. (256, 0) at level 2 splits: (256, 0) 196.73 and (256, 128)
  192.62 → **whole L1** each. 18 pieces.

**41 pieces**: 16 leaves, 13 quadrants, 12 whole nodes above level 0 → triangles (16 + 12) · 32² · 2 + 13 · 16² · 2 =
57 344 + 6 656 = **64 000**, one draw (no water). The dry instance buffer carries exactly these 41 rows in this order
(identity transform, custom = (x, z, size, level)); the wet one is empty. In T2, T3 and T5 the pieces cover the frame
exactly: they are disjoint quadtree squares and Σ area(piece ∩ frame) = the frame's area (`TerrainField.Coverage` = 1) —
no hole, and the clamp of every vertex to the frame closes the world edge.

**T4 the twin.** For 11 patch vertices of every piece (corners, edges, (1, 1), (7, 3), (16, 16), (17, 9), (31, 30),
(16, 32), (5, 16)) the twin run on the uniforms and textures READ BACK from the ground material equals
`TerrainLod.LodVertex` (x, z to 1e-9, y to 1e-6). A vertex closer than 63 m to the eye has λ = 0 (the first ring starts
at ½ · 128 = 64 m; a block owner of j ≥ 1 would need λ ≥ 1, i.e. ≥ 128 m, but lies within 2^j · 2 · √2 m) → it is drawn
at level 0 = `heightAt` (to 1e-4; the near lattice samples the tile, and h is linear in the tile).

**T5 the s3c world** (tile 0,0 wet, see "Water (tile 0, 0)"; `world_bounds` (−44, 96) … (2004, 2004) → frame
(−104, 36) … (2064, 2064)).
- Water cap of tile 0,0. The water pyramid lives on the near lattice; the level there is the masked bilinear of the
  64 m tile: all four corners of the cell [0, 64]² carry 6 m, so the whole cell is 6 m; the next cells have a dry
  corner (wet only on shared edges). Lifted solid = w > h (h ≤ 3 there) and sd > 0, with sd over the cell
  = 1 − 0.75·u·(1 + v) (u = x/64, v = z/64; corners 1, 0.25, 1, −0.5) — negative at the far corner (64, 64). A
  (2⁵ + 1)² = 33 × 33 block (64 m) would need the whole cell → no; a 17 × 17 block round (16, 16) has u, v ≤ 0.5 →
  sd ≥ 0.4375 → yes → **cap 4**. The grid: the tile plus a two-tile ring, 4 × 4 corners from (−256, −256) at 256 m,
  each the minimum of its 4 tiles → **4** at the corners (0, 0), (256, 0), (0, 256), (256, 256), 6 elsewhere.
- Far camera (1000, 10000, 1000): roots x −1 … 1, z 0 … 1 (6). λ = 6 everywhere. The cap over a square (corners in a
  one-corner ring, `lodCapOverSquare`) is 4 for the roots (0, 0) and (−1, 0), none for the rest. Level 5 > 4 forces
  the split: in root (0, 0) the child (0, 0) has cap 4 → visited at level 4 → not above its cap, d > 1024 → **whole L4
  (morph min(6, 4) − 4 = 0)**; (1024, 0), (0, 1024), (1024, 1024) have no cap → **quadrants L5** (morph 1). Root
  (−1, 0): (−2048, ·) outside, (−1024, 0) cap 4 → **whole L4**, (−1024, 1024) **quadrant L5**. Roots (1, 0), (−1, 1),
  (0, 1), (1, 1) → **whole L5**. 10 pieces; wet = a closed rectangle over tile 0,0: the two L4 nodes (x −1024 … 0
  reaches tile 0 at x = 0) → **2 wet, 8 dry**; triangles 6 · 2048 + 4 · 512 = **14 336**, two draws.
- Close camera (32, 10, 32): the lattice points of "Water (tile 0, 0)" inside the frame — (0, 64) **6 / 5**, (64, 64)
  **3 / 0**, (0, 128) **2.625 / 0.625** (lifted height / depth `v_wet`) — are drawn at exactly these numbers by EVERY
  piece that has a vertex there (all levels of both pyramids agree on these points: 512 + x and 512 + z are
  multiples of 64), and only by wet pieces (a piece touching tile 0,0's border is wet by the closed rectangle). With
  `--no-water`: no cap, the far camera draws the 6 roots dry, and (0, 64) is drawn on its bed, h = 1.

**T6.** Pixel scale = viewport height / (2 · tan 22.5°) = 1080 / (2 · (√2 − 1)) = **1303.6753236814712**; 0 without a
viewport or lens. The frame without bounds is the 200 m square (−100 … 100); a point bound (5, 7) keeps (−55, −53) …
(65, 67).

## Terrain streaming (Task 24, `Check/StreamCheck.cs`, `--check stream`)

Sources: ground.ts (`setHeightAnchor`, `refreshTiles`, `takeTiles`, `evictTiles`, `fillMissingStats`, `groundBusy`,
`refreshLayerTiles`, `reindexLayers`, `applyHeight`, `sync`, `reload`), heightTiles.ts (`wantedTiles`, `tileBatches`),
terrainLod.ts (`nearWindow`). The policy is unit-tested in `tests/TerrainStreamTests.cs`; this section is the client
wired to it.

**The world.** The main fixture (`--goto=harbour`, anchor (64, 128)) with the relief and the masks answered by hand
(`StreamSource`): a strip of ten indexed tiles `0,0` … `9,0` (256 m), each a 2 × 2 grid flat at height k (+ the lift,
0 then 5), its own stats min = max = height, err 0 except tile 9: err [0.5, 1, 2, 4, 8]. The overview: 12 × 4 at
256 m from (−256, −256), flat at the lift, `tile_stats` empty and `tile_stats_complete: false`. The masks: the same ten
keys (tile 256 m, id 1 m), each `uniform: 1`, under the cut `L1`. The LRU cap is shrunk to **4** for the check.

Want set per axis (box distance ≤ 560 m; the strip is row 0 and every anchor has z = 128, inside it, so dz = 0):
- anchor x = 64: tile 0 d 0, 1 d 192, 2 d 448, 3 d 704 → **0, 1, 2**;
- x = 1000 (tile 3): 3 d 0, 4 d 1024 − 1000 = 24, 2 d 1000 − 768 = 232, 5 d 280, 1 d 488, 6 d 536, 0 d 744, 7 d 792 →
  **3, 4, 2, 5, 1, 6**;
- x = 2000 (tile 7): 7 d 0, 8 d 48, 6 d 208, 9 d 304, 5 d 464, 4 d 720 → **7, 8, 6, 9, 5**.

**S0 boot.** Tiles `0,0;1,0;2,0` (one request), masks `0,0;1,0;2,0`, height revision 1 (one batch). Near window over
tiles 0 … 2: x 0 … 768, z 0 … 256, margin max(16, 2 · 256) = 512 → (−512, −512) … (1280, 768), 897 × 641 (no cap).

**S1 the statistics fill** (the overview is capped): 10 indexed, 3 known from the tiles → one request
`stats 3,0;4,0;5,0;6,0;7,0;8,0;9,0`. Level errors at base step 2: level L ↔ mip 2 · 2^L m = mip index L − 1 → max over
the tiles = tile 9's → **[0, 0.5, 1, 2, 4, 8]**. The idle poll (same signatures) reloads nothing; its frame:
`world_bounds` (−104, −203) … (2600, 134) ± 60 → **(−164, −263) … (2660, 194)**.

**S2 target (1000, 128).** Missing 3, 4, 5, 6 → `tiles 3,0;4,0;5,0;6,0` then `masks 3,0;4,0;5,0;6,0`.
- LRU: before the batch the held tiles are touched in want order (2, then 1) → order 0, 2, 1; the batch appends 3, 4, 5,
  6 → 7 > 4 → from the front, skipping wanted tiles: **0 evicted**, then 2, 1, 3 … 6 are all wanted → 6 held (over the
  cap, as the rule says). Held **1 … 6**, revision 2, one field build.
- Near window over tiles 1 … 6: x 256 … 1792 → −256 … 2304 → 1281 columns > 1025 → capped and centred on the anchor:
  x₀ = ⌊(1000 − 1025) / 2⌋ · 2 = **−26**, z: 641 rows → half 641 → z₀ = ⌊(128 − 641) / 2⌋ · 2 = **−514** →
  **(−26, −514) … (2022, 766)**. Ground at (1000, 128) = **3** (tile 3).
- Masks: held 0 … 6, tile 0 left the want set → dropped → window over 1 … 6: origin (256, 0), span max(6, 1) = 6 →
  id size 256 · 6 = **1536**.

**S3 target (2000, 128).** Missing 7, 8, 9 → `tiles 7,0;8,0;9,0`, `masks 7,0;8,0;9,0`.
- LRU: touch 6 then 5 → order 2, 1, 3, 4, 6, 5; append 7, 8, 9 → evict **2, 1, 3, 4** (5 evictions in all) → held
  **5 … 9**, revision 3; ground at (2000, 128) = **7**.
- Near window over 5 … 9: x 1280 … 2560 → 768 … 3072 → 1153 > 1025 → x₀ = ⌊(2000 − 1025) / 2⌋ · 2 = **974** →
  **(974, −514) … (3022, 766)**.
- Masks: 1 … 4 leave (5 dropped in all) → window over 5 … 9: origin 1280, span 5 → **1280**.

**S4 new `height_sig` `s2`** (everything 5 m higher). The poll reloads: `height-index`; the tiles go with the old relief
(0 held, revision **4**), the field is rebuilt at once without a near pyramid and with the new far pyramid (all **5**).
The anchor forgot its tile, so the next tick at (2000, 128) refetches the want set in its order:
`tiles 7,0;8,0;6,0;9,0;5,0` (revision 5, ground **12**); the fill (waiting while the ring was missing) then asks for the
rest in index order: `stats 0,0;1,0;2,0;3,0;4,0`. The model tick sees the new revision: the house's tile 0 is not held,
so its pin reads the overview, 5 instead of 0 → its datum moves **+5** (the yard too: 2 datums moved).

**S5 new `terrain_sig` `t2`.** A new ground for the anchor: `terrain`, `mask-index`, masks in want order
`7,0;8,0;6,0;9,0;5,0`; the terrain wears the new ground material; the held terrain signature is the payload's `t2`, so
the same poll again reloads nothing.

**S6 target back to (1000, 128) while the masks were re-cut (`L2`).** Height: missing 3, 4, 2, 1 (want order) →
`tiles 3,0;4,0;2,0;1,0`; touched 5, 6 → order 7, 8, 9, 5, 6, + 3, 4, 2, 1 → evict **7, 8, 9** (8 in all) → held 1 … 6.
Masks: missing 3, 4, 2, 1 → `masks 3,0;4,0;2,0;1,0` answers under `L2` ≠ `L1` → dropped, `mask-index` (says `L2`) →
re-indexed: a new ground with that index (`terrain`, then the masks of the want set `3,0;4,0;2,0;5,0;1,0;6,0`), held
masks 1 … 6, one re-index. Near window again (−26, −514) … (2022, 766).

## Water (Task 25, `Check/WaterCheck.cs`, `--check water`, fixtures `water/`)

Sources: waterShade.ts (`terrainWaterFragmentGlsl`, `twRipple`), waterPlaneMath.ts (shore, foam, opaque depth),
waterfall.ts (`waterfallQuad`, `buildWaterfall`, `patchCurtain`), pkg waterfall.ts (`waterfallsFrom`), submergedGhost.ts,
walk.ts (`ghostCutY`, `groundWaterLevel`, `groundScope`), propWater.ts + propWaterMath.ts, materials.ts
(`applyWaterShader`, `surfaceMaterial`). The pure functions are vector-checked in `dotnet test` (water.json,
prop_water.json); the ripple's sample coordinates have no shared vector — its identities (smoke_water_shade.mjs § [5]/[6])
are hand tests in `WaterExtrasTests`.

**W0 shaders.** `ground-water` **42** uniforms (its look reads the lift's `tl_sd_at` + `tl_inside` and `tl_water_geom`,
no `tw_sd` / `tw_geom`), `waterfall-curtain` 4, `waterfall-foam` 1, `prop-water` 4, `water-ghost[back|disabled|front]`
5 each; every one compiles in the headless front end (a bogus render mode does not — `depth_test_inverted` is a real
4.7.2 mode). The wave map is three's `CanvasTexture` uploaded with flipY, so three's sample (u, v) reads canvas row
(1 − v)·N = Godot's (u, −v) on the periodic map: the terrain ripple (`uv * f`, f = (1, −1), gradients too), the curtain
(`vec2(s.x, -s.y)`) and the sheet (`vec2(uv.x, -uv.y)`) all read it so.

**W1 shore gradient** (inside 1, opaque 1.5 m = ¾ · 2 m default, rim max(fwidth, 5 cm) = 5 cm). rim = min(d/0.05, 1),
shore = s(d/1.5), s(x) = x²(3 − 2x); absorption twA = shore·rim; surface twS = rim·(0.35 + 0.65·shore);
raw foam = 1 − s(d/0.6); foam = raw·min(shore + 0.15·raw, 1)·rim:

| d (m) | rim | shore | twA | twS | raw | foam |
|---|---|---|---|---|---|---|
| 0.025 | 0.5 | 0.0008240741 | **0.000412037** | **0.1752678241** | 0.9949363426 | **0.0746523251** |
| 0.05 | 1 | 0.0032592593 | **0.0032592593** | **0.3521185185** | 0.9803240741 | **0.1473504238** |
| 0.1 | 1 | 0.0127407407 | **0.0127407407** | **0.3582814815** | 0.9259259259 | **0.1403978052** |
| 0.3 | 1 | 0.2²·2.6 = 0.104 | **0.104** | 0.35 + 0.0676 = **0.4176** | 0.5 | 0.5·0.179 = **0.0895** |
| 0.59 | 1 | 0.3424272593 | **0.3424272593** | **0.5725777185** | 0.0008240741 | **0.0002822873** |
| 0.6 | 1 | 0.4²·2.2 = 0.352 | **0.352** | **0.5788** | 0 | **0** (the foam band's edge) |
| 0.75 | 1 | 0.5 | **0.5** | **0.675** | 0 | **0** |
| 1.5 | 1 | 1 | **1** (the opaque edge) | **1** | 0 | **0** |
| 2.0 | 1 | 1 | **1** | **1** | 0 | **0** |

**W2 waterfalls** (`water/terrain.json`, areas in z-order). `lake`: polygon water, profile flat at 5, no stroke → no
fall. `bank`: sand over the lake, no profile. `river`: stroke 4 m, axis (x, z, s, level) (0, 22, 0, 10), (10, 22, 10,
10), (12, 22, 12, 6), (20, 22, 20, 6): only segment 1 is steep (drop 4 over run 2 = 2 > 0.5), the run 1 … 2 drops 4 > 1
→ **one fall**, two knots → midpoint (11, 22), dir (1, 0), chord 2, width 4, 10 → 6. `sliver`: a fall of its own
(9 → 5 over 2 m) but its three collinear points enclose nothing (`buildAreaGeometry` = null) → skipped.
- Quad: h = 4, across = (dir.z, −dir.x) = (0, −1), half width 2, half run 1, lean 0.3 · 4 = 1.2; lip (10, 22), foot
  (11 + 1 + 1.2, 22) = (13.2, 22) → corners lip-left **(10, 10, 24)**, lip-right **(10, 10, 20)**, foot-left
  **(13.2, 6, 24)**, foot-right **(13.2, 6, 20)**; uvs (0, 1) (1, 1) (0, 0) (1, 0).
- Scroll √(9.81 · 4 / 2) = 4.4294469 m/s / 2.5 = **1.7717788 tiles/s**; tiles (4/2.5, 4/2.5) = **(1.6, 1.6)**.
- Foam: r = max(4/2, 0.5 · 4) = **2**, centre **(13.2, 6.05, 22)** alpha 0.6; rim point 0 (13.2 + 2, 6.05, 22), point 6
  (a = π/2: (r cos a, 0, −r sin a)) **(13.2, 6.05, 20)**, alpha 0; 26 vertices, 24 triangles, the first three's
  (1, 2, 0) emitted as (1, 0, 2).

**W3 the ghost.** A box (albedo texture, both sides, alpha scissor 0.5): dry → **nothing built**. A crate base at 4.6
in the lake (mirror 5, the topmost area's flat profile): 5 − 4.6 = 0.4 ≥ 0.05 → cut **5**; one twin under the box, same
mesh, identity transform, no shadow, the `cull_disabled` variant, the texture, alpha test 0.5, tint (63, 127, 184)/255.
The lake rises to 5.75 → the cut follows, nothing is built again. Dry → hidden, kept. The switch hides it. A skinned
body: the twin carries the same skin and resolves the same `Skeleton3D`. Figure gate: the river at (5, 22) = 10 over
a bed at 9 → **10**; in a built scope → dry; on the sandbank (topmost area without a profile) → dry.

**W4 prop water** (`water/prop_spec.json`, lift 0.25): region 0 (4 × 4 with a 1 × 1 hole, y 1.5) → **8** triangles at
**1.75**; region 1 (2 × 2, y 2) → **2** at **2.25**; one material for `#3f7fb8|0.7`, albedo 0.25 · raw + 0.75 · linear =
(**0.0990446**, **0.2836829**, **0.5398823**) (linear 0.0497066, 0.2122308, 0.4793202), opacity 0.7; re-lift 1.0 →
**2.5**; the hour's sky reaches the cached material; at (3.5, 3.5) the higher mirror 2 + 0.25 = **2.25** (bed 1.75).
