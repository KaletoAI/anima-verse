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

**Overview** (`heightfield.json`): origin (−256, −256), step 256 m, 3 × 3
points → **9 vertices**. Its 4 cells: cell (i=1, j=1) spans x 0…256, z 0…256 =
exactly tile (0, 0); that tile is loaded (below), so the cell is left out →
3 cells → **6 triangles**.

Heights `[[0,0,0],[0,4,8],[0,8,16]]` (`heights[j][i]`).

**Tile index** `["0,0", "5,5"]`. Tiles within 384 m of the anchor (64, 128):
(0, 0) contains the point (distance 0); (5, 5) covers 1280…1536 — its nearest
corner (1280, 1280) is ≈ 1675 m away → not requested. So exactly ONE request
key `0,0` → **tiles = 1**. Tile (0, 0) in `tiles.json` is 5 × 5 at the batch
`step_m` 64 (the code reads dims and step from the payload; the real server
sends 129 × 129 at 2 m) → **25 vertices** (32 triangles). Heights
`h[j][i] = 2·i + j`.

terrain_vertices = 9 + 25 = **34**.

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
  `ng_field_size` (3, 3), `ng_strength` 1 (the field is not flat: 0…16), `tl_normal_span` = `tile_step_m` 2,
  `tl_far_geom` (−256, −256, 256, 1), `tl_far_level` (3, 3, 256, 0); the near height window = the loaded tile
  (0, 0) = 0…256 grown by max(16, 2 · 256) = 512 → **−512…768 at 2 m = 641 × 641**, rect (−512, −512, 768, 768).
  25 uniform declarations; Godot's dummy renderer runs the shader-language front end, so a shader that does
  not parse reports none.
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

### Models

loc-open: the plan-hull building is KEPT when open (cutouts instead of a fade) → placed, its triangles inside
the 6 × 6 cutout removed (**> 0 and < 1110**, and no remaining centroid inside); chair (`r-ground`) → prop;
lamp (`r-up`) → **storey**; the `door:` model (`measure: "fit"`) → door; the `window:` spec has no URL but
`placeholder_dims` → **placeholder**; the `room` diorama has neither → **missing**; bench (`r-garden`) → prop.
loc-closed: building; well (no room) → prop; shelf (`r-in`) → **interior**. loc-far: post → prop at **low**.
World props (camera (64, 160), landmark LOD = scatter × 3 = 105 / 135 / 360 m, cold start `low`):
wp1 (80, 150) d = 18.87 → **full**, variant 1 → `…?variant=1&tier=full`; wp2 (64, 600) d = 440 → **culled**;
wp3 (200, 160) d = 136 > 135 → **low**.
→ placed building 2, prop 4, door 1, world 2; placeholders 1, missing 1, interior 1, storey 1, culled 1;
tiers asked: full 6 (open building, chair, door, bench, well, wp1), low 3 (closed building, post, wp3);
building GLBs 2 × (2220 / 3330). The hidden lamp/shelf URLs are never requested.

Heights (§ A16.9 lift = ground(anchor) − datum, level 0, non-building):
- chair anchor (2, −1) → world (66, 119): tile h = 2x/64 + z/64 → 2.0625 + 1.859375 = 3.921875 → lift
  **0.046875** = its bottom in the location frame (bottom_y 0);
- door anchor (−5, −1.5) → (59, 118.5): 1.84375 + 1.8515625 = 3.6953125 → bottom **−0.1796875**, height
  **2.1** (`fit` scales y to `size_m[1]`);
- placeholder anchor (−5, −3.5) → (59, 116.5): 3.6640625 → y = 0.9 − 0.2109375 = **0.6890625**, yaw 90°;
- wp1 bottom = tile ground (80, 150) = 2.5 + 2.34375 = 4.84375 + 0.5 − 0.25 = **5.09375**.

### Water (tile 0, 0)

`h(i, j) = 2i + j` on the 5 × 5 lattice (step 64). Five lattice points carry a level of 6 m;
`liftedHeight = h + (w − h)·smoothstep(0, 0.5, sd)` where w > h:

| (i, j) | h | sd | gate | lifted | lift (UV2.x) |
|---|---|---|---|---|---|
| (0, 0) | 0 | 1.0 | 1 | **6** | **6** |
| (1, 0) | 2 | 0.25 | 0.5 | **4** | **2** |
| (0, 1) | 1 | 1.0 | 1 | **6** | **5** |
| (1, 1) | 3 | −0.5 | 0 | **3** | **0** |
| (0, 2) | 2 | 0.125 | 0.15625 | **2.625** | **0.625** |
| (2, 0) | 4 | dry | 0 | **4** | **0** |

→ **1 wet tile, 5 wet texels**, window 5 × 5 at (0, 0) step 64 (sd at (1, 0) = 0.25, a dry texel −10 000);
the layer table's only water layer `lake` → **1 look row**, its surface `water` has no library entry and no
painted area carries a profile → the default look, opaque depth ¾ · 2 = **1.5 m**, water areas **0**. With
`--no-water`: no lift (vertex (0, 0) stays at **0**), no tag, no variant, `water[off: --no-water]`.

### Shaders

Every spatial shader goes through the headless front end once and logs one line; the check requires
`ground`, `ground-water`, `recipe[opaque]`, `recipe[translucent]` and `recipe[opaque,both-sides]` to be
`compiled (N uniforms)` with N = the shader's own uniform count.
