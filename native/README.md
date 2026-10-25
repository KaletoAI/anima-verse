# Anima Verse — native client (spike)

A Godot 4.7.2 (.NET / C#) client for Phase 2 of `plan-native-client.md`: it
renders THE SAME world as the browser 3D client (`client3d/`) so both can be
timed on the same camera drive (`shared/bench/camera_path_v1.json`). Spike
quality — no game logic. Task S1a covers login, terrain, buildings, recipe
shells and a free camera; Task S1b adds the figures with idle/walk clips and
live positions; Task S2 adds the bench drive (see "Bench" below); Task S3 adds
the scatter and the undergrowth behind `--scatter` (see "Scatter" below);
Task S4 lays the React HUD over the world through gdCEF (see "HUD" below);
Task S3b dresses the terrain in the browser's ground surfaces (see "Ground
surfaces" below); Task S3c brings the scene content to parity with the
browser — recipe primitives, props, world props, water — and an offline mode
on a payload dump of a real world (see "Scene content" and "Offline").

What it draws after login:

- **terrain** — the `/play/heightfield` overview as one mesh, plus the 2 m tiles
  (`/play/heightfield/tiles`) within 560 m of the anchor (`HEIGHT_TILE_RADIUS_M` =
  `FOG_FAR_M` 520 + 40, the browser's rule) as separate meshes, no LOD; dressed in
  the browser's ground material — the painted layers cut per texel from the
  server's masks, the surface textures, colour patches, height AO and the
  per-fragment shading normal (see "Ground surfaces"); the plain one-colour
  material when that fails or with `--plain-ground`;
- **water** — the browser's Wasser v2 terrain water: a wet tile's vertices lifted
  onto the mirror, shaded by the water variant of the ground shader (see "Scene
  content"); off with `--no-water`;
- **locations** — per placed location in reach, what the browser's overview shows
  of its scene recipe (`/play/locations/{id}/scene`): the `role: building` model
  (loaded from its variant URL, Meshopt-decoded client-side —
  `Core/Gltf/GlbMeshoptDecoder.cs` + vendored meshoptimizer — and placed by the
  contract's `place()`, § B2), the outdoor model specs (props, door/window models,
  dioramas), the outdoor rooms' primitives, the far-view shell of a place without
  a model, and the avatar's OPEN location with its interior (see "Scene content");
- **world props** — the single props of `/play/worldmap` `world_props` (§ A9a);
- **figures** — the characters of `/play/worldmap`, polled at the browser's cadence
  (see "Polling, push stream, boot stages" below), where the
  browser's far view draws them (journey point along the route, the huddle in
  front of / around their location, or their free point in the wilderness), on
  the world ground; a moved figure lerps to its new point over the poll
  interval and plays `walk` above 0.2 m/s, `idle` otherwise. Model:
  `/characters/{name}/model3d` → the humanoid GLB (Meshopt-decoded), scaled to
  `height_cm`; FBX (generic rig) and "no model" are capsule placeholders; a
  changed `model_sig` reloads it. Clips: the neutral-set `idle`/`walk` of
  `/assets/animation-clips` (through its `locomotion` mapping), each FBX
  downloaded and imported once at runtime (`FBXDocument`), retargeted by bone
  name with the browser's rest-pose correction against `/assets/animation-rig`
  (`Figures/RestCorrection.cs`, port of `restCorrections` in
  `packages/scene-render/src/clipRetarget.ts`), hips height scaled (see
  `Figures/ClipLibrary.cs` for what the browser does on top);
- a sun + fill light and ambient comparable to the browser, sky colour, no fog;
- with `--scatter`: the authored scatter of the painted areas and the automatic
  undergrowth (see "Scatter").

## Requirements (build machine)

- Godot **4.7.2 stable .NET** editor binary (`Godot_v4.7.2-stable_mono_linux.x86_64`)
  and its Linux export templates (`~/.local/share/godot/export_templates/4.7.2.stable.mono/`)
- .NET **8** SDK (`dotnet` on PATH)
- `g++` (compiles `third_party/meshoptimizer` into `bin/libmeshoptimizer.so`)
- for the HUD: the **gdCEF 0.20.0** release artifacts (CEF 151, Linux; the
  `cef_artifacts/` folder of github.com/Lecrapouille/gdcef, ~560 MB — never
  committed). Without them everything builds and runs, just without the HUD.

## Build, check, export

```bash
cd native
./link_cef.sh [/path/to/gdcef/cef_artifacts]  # ONCE: links the gdCEF artifacts as res://cef_artifacts/
                                              # (default source $GDCEF_DIR, else /home/dev/tools/gdcef/gdcef/cef_artifacts)
dotnet build                                  # C# (+ Core/) + bin/libmeshoptimizer.so (csproj target)
dotnet test tests                             # xUnit tests of the Godot-free core (no engine needed)
$GODOT --headless --path . --import           # first import (creates .godot/)
$GODOT --headless --path . -- --check         # offline self-test → "CHECK ok …", exit 0
$GODOT --headless --path . -- --check-bench   # offline bench smoke → "CHECK-BENCH ok …", exit 0

GODOT=/path/to/Godot_v4.7.2-stable_mono_linux.x86_64 ./build.sh [out_dir]
                                              # build + import + export "Linux" preset
                                              # default out_dir: native/export/
GODOT=… ./test.sh                             # all checks: dotnet test tests + build + --check, exit ≠ 0 on any failure
```

The code is split in two assemblies: `Core/` (`AnimaNative.Core`, a plain
net8.0 library without any Godot reference — payload parsing, the HUD protocol,
the ports of the browser's maths, the Meshopt decoder, the embedded bench path)
and the Godot project around it (`AnimaNative`, a `ProjectReference` on Core).
`tests/CoreIsGodotFreeTests.cs` keeps Core free of Godot. The Godot project's
default compile glob excludes `Core/**` and `tests/**`; both folders carry a
`.gdignore` so the editor does not import them. `build.sh` fails when the
export lacks `AnimaNative.Core.dll`.

`build.sh` produces `anima-native.x86_64` (PCK embedded), the .NET folder
`data_AnimaNative_linuxbsd_x86_64/` and `libmeshoptimizer.so`, and — when the
gdCEF artifacts are linked (build.sh runs `link_cef.sh` itself if
`native/cef_artifacts/` is missing and the artifacts exist) — the CEF runtime
next to them: `libgdcef.so`, `libcef.so` (1.4 GB), `gdCefRenderProcess`,
`*.pak`, `icudtl.dat`, `v8_context_snapshot.bin`, `libEGL.so`, `libGLESv2.so`,
`libvk_swiftshader.so`, `libvulkan.so.1`, `vk_swiftshader_icd.json`, `locales/`
(hard links into the artifact folder where possible, copies otherwise).
Keep everything in one folder: gdCEF looks for its subprocess and resources
next to `libgdcef.so`.

Known: with gdCEF linked, Godot 4.7.2's editor-mode `--import` sometimes
segfaults (exit 139) while the process exits, AFTER the import has finished
(godot-cpp's static data outliving the engine); `build.sh` tolerates exactly
that code in exactly that case. The export and the game itself are not
affected (`--check` exits 0 with the extension loaded).

## Start

```bash
./anima-native.x86_64                 # or: sh run.sh — no flag is required
./anima-native.x86_64 -- --server=http://192.168.8.244:8000 --user=demo --goto=LOCATION
```

**The launcher.** The client starts on its login screen: server address, user,
password. The server field takes the address the way one types it —
`192.168.8.244:8000` becomes `http://192.168.8.244:8000` (scheme added when
missing, blanks and trailing `/` removed; anything but http(s) is refused with a
message). After a successful login the server and the user name are remembered
and pre-filled at the next start; the **password is never stored** (nor
accepted as a flag). F11 toggles full screen (`Fullscreen`, not exclusive) at
any time — on the login screen, in the world, while the HUD types — and the
mode is remembered too (a `--bench` run and an explicit `--size` ignore the
remembered mode). Pre-fill order per field: the flag (`--server`, `--user`) >
the remembered value > empty. One log line says what was used:
`[native] launcher: server '…' (cli|file|none) user '…' (cli|file|none) fullscreen on|off — settings <path>`.

The settings file is `user://launcher.json` — Linux:
`~/.local/share/godot/app_userdata/Anima Native/launcher.json` — with exactly
the keys `server`, `user`, `fullscreen` (pure rules: `Core/Ui/LauncherSettings.cs`,
file side: `Ui/LauncherStore.cs`). A missing, empty or broken file only costs
the pre-fill; delete it to forget server and user.

**Back to the title.** The HUD's "Back to title" (game menu) and "Log out" (top
bar) end the session and return to the login screen, server and user filled in:
the HUD page ends ITS session first (`GET /auth/status`, then `POST /auth/logout`
only for a live session — only the server can drop CEF's HttpOnly cookie, and an
anonymous logout is not a no-op on the server), CEF goes to `about:blank`, Godot
logs out its own copy if it is still alive and empties its cookie container,
and the scene is reloaded — like the browser's `location.reload()`, that frees
the world, figures, scatter and timers; the worldmap poll, the push stream and
every sync timer stop first (`StopSync`). Logging in again builds the world anew. A leave that cannot
reach the server still returns to the title; the next login's handoff ends a
session CEF may still hold before it writes the new cookie.

Polling, push stream, boot stages (Task 10) — the browser's, ported to `Core/Sync/`:

- **World-map poll** (`c3d-worldmap`, `PollSpec.Worldmap3d`): a 1-s tick; every 3 s, every 6 s while the
  push stream is connected, at least 3 s apart; a failure doubles the interval up to the 60-s cap (3, 6, 12,
  24, 48, 60, 60 s), a success resets it; one request at a time. `GET /play/worldmap?all=1` while an admin
  has "show all locations" on (applied live: dropped places go, added ones are built, a failure rolls back with
  the toast "The view could not be switched.").
- **Push stream** `GET /events/sync` (online): `presence`/`world` frames poll at once (respecting the 3 s); a
  resync after the first drops what was in flight; 35 s deadline (+10 s sleep tolerance), retries 5 s doubling
  to 60 s, `bye` stops it. One line `sync stream connected|connecting|waiting …` per change in the log.
- **Locations** `GET /world/locations?view=3d` with `If-None-Match` (304 keeps the cache): re-synced every 120 s,
  when a poll's `locations_rev` differs, and forced when a poll brings a place the world does not have yet
  (which is then built).
- **Connection**: a failed poll (not a 401) → HUD `connection: lost`, the next good one → `ok`; the clock is
  sent only when it changes. **Any 401** → back to the login screen like "Back to title" but without a logout
  call; server and user stay filled in, the screen says the session ended.
- **Boot stages**: the login screen stays up as the loading screen (bar, stage in words, the retry/failed
  line) and fades at `visible`; the HUD gets the same `boot` messages. Native points: world (boot data in,
  retried 1, 2, 4, 8, 15 s), scenes (start-ring recipes fetched), tiles (start ring + world props built),
  visible (next frame), figures (first map's figures + their models), arrival (immediately after; no
  embodied take-over yet). `boot stages: world … ms, …` in the log.

Labels and the performance readout (Task 11) — the browser's CSS2D layer as a screen-space overlay
(`Ui/LabelOverlay.cs`, canvas layer 1, under the HUD; never takes the mouse):

- **Name tags** (`Figures/NameTags.cs`): a column [speech bubble, name, activity] centred over each figure's head
  (height + 0.45 m), shown while the camera is closer than 55 m; the name of a traveller reads `🚶 HH:MM Name`,
  the avatar's in gold. The HUD's `sayBubble` puts a bubble over the speaker (at most 140 characters, 22ch wide,
  3.5–12 s). Rules: `Core/Overview/OverviewLabels.cs`, vector-checked (`shared/test-vectors/overview_labels.json`).
- **Location names** (`World/LocationLabels.cs`): every non-area place, serif small capitals in gold, 2.2 m above
  the place's height on its ground; no distance limit.
- **Event pins** float 3.5 m above the top of their place measured from its ground (`pinY`, vectors in
  `event_pins.json`); a pin whose event turns into a danger is rebuilt; every poll places them again.
- **Performance readout**: while the HUD's overlay is on (game menu), the `perf` message every 300 ms — fps over
  1 s, worst frame, triangles and draw calls (Godot's frame monitors), visible vertices (1 s walk); the other
  fields are 0 (no native source). The status line shows `N labels (x ms)`.

Arguments after `--` (no .env; all optional):

| Argument | Meaning |
|---|---|
| `--server=URL` | pre-fills the server field for this start, over the remembered one (http(s); `host:port` gets `http://`) |
| `--user=NAME` | pre-fills the user field, over the remembered one (the password is typed in, never passed or stored) |
| `--goto=ID\|NAME` | anchor: location id, or a case-insensitive name substring (the browser bench's `&goto=`) — the start camera looks at it, the 2 m tiles load around it; without it the avatar's location, else the world origin |
| `--bench` | run the camera drive once the world has loaded (see "Bench") |
| `--size=WxH` | window size; a bench run defaults to `1920x1080` (the result reports the size actually rendered) |
| `--vsync=on` | keep V-sync during the bench (default: off for the run, restored after) |
| `--quit-after-bench` | exit after the result file is written |
| `--no-scatter` | hide the scatter AND the undergrowth (default on, like the browser; = `&scatter=0`); the bench flags say `scatter: false` |
| `--plain-ground` | keep the S1a one-colour terrain (no `/play/terrain-layers`, no surface textures); the bench result's `ground` key says `ground[plain: --plain-ground]` |
| `--no-hud` | no HUD even when gdCEF is linked (the S2/S3 bench numbers were taken without it) |
| `--no-water` | no water lift / water variant (= the browser's `&water=0`); the bench flags say `water: false` |
| `--offline=DIR` | build from a payload dump (`tools/dump_payloads.py`) instead of a server: no login, no HUD; prints the world/scatter/figure/shader summary lines and quits (with `--bench`: runs the drive, then quits) |
| `--check` | offline self-test from `fixtures/` (see `fixtures/README.md`), then exit 0/1 |
| `--check-bench` | offline bench smoke: fixture world + a 0.5 s warm-up / 2 s drive on the headless dummy renderer, then exit 0/1 (with `--scatter`: the fixture's scatter layers ride along) |

Camera (the browser's overview camera, `Ui/OverviewCamera.cs` + `Core/Overview/OverviewControl.cs`):
the world starts framed whole (`world_bounds`); left drag pans by grabbing the ground, right/middle drag
or Shift/Ctrl/Alt + left drag orbits and tilts, the wheel zooms towards the cursor, W/A/S/D and the
arrows move, Q/E turn by 45°, + / − zoom. A release under 4 px (orbit) / 0.15 m (pan) is a click.
With the HUD up, F and Enter open the chat, M opens/closes the menu, a click on a figure shows its
plaque, and the plaque's "Zoom to" flies to it (4.5 m, no follow); an open chat shifts the picture
out of its way (the browser's view shift, as a Godot frustum offset).
The status line top left reports what was loaded; per-location
failures are logged to the console (`[native] …`).

## Bench

The same drive as the browser's `client3d/?bench=auto&goto=<loc>`: THE file
`shared/bench/camera_path_v1.json` (embedded into the assembly from the
repository at build time — no copy in `native/`), relative to THE same anchor
(`pickBenchAnchor`: `--goto` exact id beats name substring, position from the
`/play/worldmap` row, y = the `/play/heightfield` overview bilinear and
border-clamped, frozen at run start; no goto → the avatar's location → origin),
the same phase rule (warm-up `warmup` s at keyframe 0, then `duration` s; the
transition frame establishes t = 0, only later intervals count) and the same
summary (`summarize`/`percentile` of `client3d/src/bench/benchStats.ts`).

Measuring (on the PC with the GPU; login screen first, the run starts after
terrain, tiles, buildings and the first poll's figures have loaded):

```bash
./anima-native.x86_64 -- --server=http://192.168.8.244:8000 --goto=<loc> --bench
./anima-native.x86_64 -- --server=http://192.168.8.244:8000 --goto=<loc> --bench --quit-after-bench --size=1920x1080
```

Compare with the browser at the same window size and the same switches: the
native client draws water and scatter by default like the browser
(`flags.water` / `flags.scatter` say what was drawn); `--no-water` ↔ `&water=0`,
`--no-scatter` ↔ `&scatter=0`, e.g.
`http://192.168.8.244:8000/play?bench=auto&goto=<loc>&scatter=0&water=0` against
`… --bench --no-scatter --no-water`.

With scatter on (both layers, see "Scatter"):

```bash
./anima-native.x86_64 -- --server=http://192.168.8.244:8000 --goto=<loc> --bench --scatter
./anima-native.x86_64 -- --server=http://192.168.8.244:8000 --goto=<loc> --bench --scatter --quit-after-bench --size=1920x1080
```

against `http://192.168.8.244:8000/play?bench=auto&goto=<loc>&water=0` (scatter
on is the browser's default). The run waits until the prop meshes of the start
window have landed (≤ 60 s, logged as `scatter settled …`); the result carries
an extra key `scatterLayers` (what both layers drew at the end of the drive), and
every 5 s a `[native] scatter …` line logs instances and triangles per layer.

The result is printed as ONE line `[bench] result {json}`, written to
`user://bench-<yyyyMMdd-HHmmss>.json` (Linux: `~/.local/share/godot/app_userdata/Anima Native/`,
the path is printed) and shown in a panel (selectable, "Copy JSON"). Keys: the
browser's (`backend: "godot-forward+"`, `path`, `pathVersion`, `duration`,
`warmup`, `flags` {goto, scatter, water, vsync}, `anchor` {pos, locationId,
heightSource}, `size`, `frames`, `seconds`, `fpsMean`, `frameMsMedian`,
`frameMsP95`, `cpuMsMedian`, `cpuMsP95`, `gpuMsMedian`, `callsMedian`,
`trisMedian`, `fps`, `gpuMs`, `draws`, `triangles`) plus `renderCpuMsMedian`,
`godot`, `gpu`, `cpu`. Per frame: `dt` = wall delta (unclamped), `cpuMs` =
`Performance.TimeProcess`, `renderCpuMs`/`gpuMs` = the viewport's measured render
CPU/GPU time, draws/triangles = `RenderTotalDrawCallsInFrame` /
`RenderTotalPrimitivesInFrame` (read in `_Process`, so they describe the
previous rendered frame). V-sync is off during the run unless `--vsync=on`.
The free camera is switched off for the run and handed back afterwards.

Every result ends with the extra keys `ground` (Task S3b): `ground[layers=…]`
when the browser's ground material was drawn, `ground[plain…]` (with the
reason) when the plain one was — compare only runs where it says `layers` —
and `water` (Task S3c): `water[areas=… tiles=… kinds=… wet_texels=…]` when the
water variant was drawn, `water[off: --no-water]` / `water[none…]` otherwise.

## Ground surfaces (Task S3b)

The terrain meshes of S1a wear ONE Godot spatial shader (`Ground/GroundShader.cs`)
that is the browser's open-world ground material (`client3d/src/scene/ground.ts`
`rebuildBase`), fed from the same requests (`Ground/GroundSurfaces.cs`):

- `GET /play/terrain` — the type catalog: colour (`kindColor`, else `#888888`)
  and library surface per kind (`surfaceOf`);
- `GET /assets/surface-textures` — the library (`url`, `size_m || 3`; a failure
  is an empty library; `blend` entries have no image and load nothing, the ground
  has not read blends since E4);
- `GET /play/terrain-layers` — the index (format, layer table, coarse id mask,
  tile keys), then `?keys=…` for `wantedTiles(tile_keys, tile_m, anchor, 560 m)`,
  nearest first, 16 per request (§ A16.7);
- the image of every surface a layer names, once per library id, drawn onto a
  512² slice of ONE texture array (mipmaps, anisotropic); a layer without a
  loaded image gets a slice of its flat catalog colour — with the browser's
  three.js quirk: the hex goes through `THREE.Color` (→ linear) and is written
  into an sRGB-tagged texture, so it comes out darker than the catalog says.

Per fragment, like the browser: the layer cut of `layerCut.ts` (`lcCompose`:
pair from the id mask — near window, else coarse overview, else bare ground —,
distance rebuilt from the four sd texels of the own id texel, edge-noise push,
`smoothstep` of layer A's `edge_blend_m` or the pixel-wide hard cut, two
`textureGrad` samples per layer = narrow + broad anti-tile), then the natural
ground's colour patches and height AO (`naturalGround.ts`, overview field in an
R16F texture), then the shading normal from the height field (`tlodNormalAt`:
4 × 4 `texelFetch` of the near window at `tile_step_m`, else the overview),
lit as three's `MeshStandardMaterial` (roughness 0.85, metalness 0.02, Lambert).
`Core/Ground/LayerCut.cs` and `Core/Ground/TerrainNormal.cs` are the CPU twins `--check`
compares with the TS functions (`fixtures/ground_reference.mjs`).

Not ported (favours Godot, a little fragment work): the fog-of-war veil
(`applyFogVeil`) and the basement hole discard (`patchHole`). The water branch
is the separate water variant (Task S3c, "Scene content"). The masks are loaded ONCE around the anchor (the browser re-fetches
as its anchor moves). If anything of the index/masks/texture array fails, the
plain material stays and the log says why (`ground surfaces failed, …`); a single
image that fails only turns its slice into the colour slice, like the browser.

## Scene content (Task S3c)

What the browser's overview shows of every location, decided like client3d
(`Core/World/LocationView.cs`, `World/RecipeMeshes.cs`, `World/SceneModels.cs`) —
nothing here is a native choice:

- **Reach** (`streamRings.ringFor` over `placeDistance` to the stream points: the
  avatar's position and the camera focus = the bench anchor): `near` ≤ 150 m or
  pinned (the avatar's location), `far` ≤ 560 m, beyond that the browser does not
  mount the location at all (`gone`, counted, not built).
- **The open location**: the avatar's location is open from the first mount on
  (`arrivalLocId`, fade 1). Its interior group shows: storey plates only on the
  avatar's storey, room groups only on it (outdoor/always-visible rooms always),
  outline walls only on it and only where the camera is not on their outer side
  (`applyWallCulling`, per frame in the recipe shader), door leaves / window panes
  that a model fills stay hidden, extras (stairs, lift) always; its indoor model
  specs on that storey are placed. A shell building model fades out (not drawn);
  a plan-hull or ground model stays and loses what lies inside its `cutouts` (the
  browser discards those fragments; here the triangles whose centroid lies
  inside are dropped from a per-placement copy — same pixels, no per-fragment
  polygon loop, which favours Godot).
- **Closed locations**: the building model(s), the outdoor model specs (no room
  or an outdoor / always-visible room) and the outdoor rooms' primitives; a place
  without a building model shows its far-view shell (`shellPlan`: copies of the
  level plates at or above ground and of every non-glass wall, leaves included).
  The interior group stays invisible — its primitives and indoor specs are
  counted as `interior`, not built.
- **Tiers** (static, from the anchor and the bench path's start camera
  anchor + (0, 24, 40)): building — far → `low`, near → `full` under 45 m camera
  distance minus the footprint's half diagonal; outdoor/indoor specs — far → `low`,
  near → `full` (`low` for a closed area-detail scene); world props —
  `instanceTier` at 3 × the scatter distances (105 / 135 / 360 m) from the camera,
  hidden beyond 360 m. The variant is `pickModelVariant` (model variant first,
  then the tier, a missing tier → the best existing one).
- **Placement**: every spec through `place()` (§ B2, `World/ModelPlacement.cs`,
  incl. `measure: "fit"` door/window models), one import per GLB URL
  (`World/ModelCache.cs`, placements are `Duplicate()`s sharing meshes and
  materials), the § A16.9 terrain lift for level-0 specs, a grey placeholder box
  for a spec without a loadable mesh but with `placeholder_dims`.
- **Primitive materials** (`World/RecipeMaterials.cs`): the kind's surface texture
  tiled in world metres (plates: outline metres / `size_m`, walls and extras: each
  face's own metres) or the payload style colour; glass / door-leaf / stair / lift
  colours and opacities from `style`; matte 0.85 / 0.02 unless the kind's
  `material` says otherwise. One mesh per material per location (the browser draws
  one per primitive — fewer draw calls, favours Godot).
- **Water** (`Ground/Water.cs`, the water branch of `Ground/GroundShader.cs`):
  Wasser v2 K-A has no water mesh. A wet height tile (`water` block of
  `/play/heightfield/tiles`) is lifted onto `liftedHeight(h, level, sd)` (the
  vertex stage's `tlodLift`, done once on the CPU) with the lift in `UV2.x`; the
  water variant samples the signed distance, the kind row and the flow per pixel
  (one window over the loaded wet tiles) and runs `tlodWaterSurface` /
  `tlodWaterNormal` / `tlodWaterOut` (absorption, surface share, foam, the
  three-sheet ripple of the procedural wave map, the fresnel sky share). The look
  table is `refreshWaterLook`'s (one row per water layer kind, the kind surface's
  `material`, the last painted area's bed depth). The final sky/foam mixes go in
  as ALBEDO scale + EMISSION (Godot has no post-light hook; the specular share is
  not scaled — a hair brighter highlight on deep water).
- **Shader safety** (`World/ShaderSafety.cs`): every spatial shader (ground, the
  water variant, the recipe variants, every scatter/undergrowth variant) goes
  through Godot's shader-language front end once and logs
  `shader <name>: compiled (N uniforms)`; a failure logs `FAILED … plain material
  fallback` and that material falls back (ground → the plain vertex colour, water
  → the dry tile, recipe → a StandardMaterial3D, scatter → the same shader
  without the wind).

Not ported (all view-only, counted nowhere): picture/glass slot materials, the
room clip and the depth cut of props (`clip_outline`, `cut_plane`), door
swinging, prop lights, the underwater ghosts, waterfalls, LOD re-evaluation while
the camera moves (the bench drive keeps its focus on the anchor).

Summary line of a build (online log, `--offline`, `--check`): `primitives=N
skipped=M (degenerate=… interior=… storey=… panes=…) shell_copies=…
culled_walls=… models[building=… room=… prop=… door=… window=… world=…
placeholders=… missing=… interior=… storey=… faded=… culled=… full=… low=…]
… water[…]`.

## Offline: the real world without the server (Task S3c)

`tools/dump_payloads.py` opens a COPY of a world directory through the FastAPI
app itself (`TestClient`, no lifespan — no agent loop, no LLM), logs in as a
temporary player that mirrors a user of that copy, and writes exactly the
answers the client reads, laid out like `fixtures/` (binaries as hard links into
the copy where possible). It refuses a world inside the repository's `worlds/`
and an output inside the repository — the user's content stays out of git.

```bash
./.venv/bin/python native/tools/dump_payloads.py --world /path/to/COPY --out /path/to/dump --as-user NAME
$GODOT --headless --path native -- --offline=/path/to/dump --goto=LOCATION
```

The offline run builds the same world as online (`Check/FixtureSource.cs` serves
the dump) and prints `offline world …`, `offline scatter …`, `offline figures …`
and the shader lines, then quits.

## Scatter (Task S3)

`--scatter` turns on BOTH layers the browser bench's `&scatter=0` hides
(`terrainGround.debugParts().scatter` + `.undergrowth`), from the same inputs:
`GET /play/terrain` (areas bottom to top with their `meta.scatter` rows — the
server already puts the prop's `variants`, `model_variants`, `prop_height_m`,
`sway_factor` on each row — the type catalog's `meta.undergrowth`/`sway_m`/
`color`, and `prop_boxes`) plus the worldmap rows' `boundary` (location
footprints) and `game_time.total_seconds`. `/assets/props` is not read: the
browser's ground does not read it either (§ A9: the row carries the prop facts).

- **Where** — `Core/Scatter/ScatterMath.cs` is an exact port of the shared sampler
  `packages/scene-render/src/scatter.ts` (+ `occupancy.ts`): same PRNG, same
  candidate stream, same verdict order. `--check` compares it with vectors the
  TS function itself wrote (`fixtures/scatter_reference.mjs`) within 1e-6 m.
- **Scattered props** (`Scatter/ScatterField.cs`, port of `ground.ts`
  `buildScatter`/`binProp`/`mountUrl`): the 64 m cell window around the camera
  target (k = ceil(120/64)), one occupancy grid per cell, clearance estimated
  until the mesh is measured, then re-sampled; one `MultiMeshInstance3D` per
  (row, model variant, tier) — the tuft cone until the GLB lands, the `low` tier
  on the cheap buffer and the `full` tier on its own buffer; the per-instance LOD
  of `scatterLod.ts` with its defaults (full < 35 m, hysteresis 35–45, low to
  120 m with the share sinking to 0.25, `instanceHash` thinning, view cone).
- **Undergrowth** (`Scatter/UndergrowthField.cs`, port of `undergrowth.ts`):
  cells within 128 m of the target, seed per (area, cell), density
  `0.8/m² × meta.undergrowth`, the three-plane star tuft with the procedural
  blade texture (alpha cut 0.35), colour variation per instance, cull at 60 m.
- **Wind** (`Scatter/ScatterShaders.cs`): the browser's `applySway` vertex
  displacement as a Godot spatial shader on every scatter/undergrowth material.
- **Cadence** (`Scatter/ScatterLayer.cs`): the browser's 1 Hz tick (LOD pass,
  then the window/cells follow the camera target) plus its movement driver
  (another pass after ≥ 100 ms when the camera moved > 8 m or turned > 10°).

Not drawn (this favours Godot): the impostor billboards beyond 120 m
(`impostors.ts`), the `along`/`edge`/`center` rows (counted, logged as
`skipped`), the camera corridor fade. Different but cost-neutral: the
`aligned` yaw uses the angle without the surface axis; the undergrowth's layer
mask gate is the geometric "topmost painted area" test.

## HUD (Task S4)

The browser HUD itself — `client3d/hud.html`, served by the Anima server at
`/static/client3d/hud.html?bridge=gdcef` — runs in an off-screen Chromium
(gdCEF) and is drawn over the world (`Hud/HudOverlay.cs`):

- **View**: a full-window `TextureRect` on canvas layer 5 (above the status
  line, below the login screen), 60 fps. gdCEF never sets a CEF
  `background_color`, so the windowless page paints with a transparent
  background and the alpha arrives in the texture; Chromium's alpha is
  premultiplied, so the rect blends premultiplied. 3 s after the page loaded a
  log line `hud: transparency probe: … alpha=…` reports the painted alpha
  outside every HUD surface (0 = transparent) and inside the first one.
- **Bridge**: protocol v1 of `client3d/src/hud/bridge.ts`, one JSON string per
  message over gdCEF's JS binding (`window.godotMethods.hud_bridge(json)` →
  `HudOverlay.hud_bridge`, Godot's `js_emit("hud_bridge", json)` →
  `window.godotEvents`); the page picks `gdcefTransport` by `?bridge=gdcef`.
  Godot is the scene side: it sends `boot`, the game state the chat, plaque
  and menu read (`clock`, `connection`, `mode: overview`, `selected`,
  `openView`), and `ui` actions; it receives the HUD's ui state
  (`hitRects`, `typing`, `overlayOpen`, `menuOpen`) and game actions
  (`zoomTo`, `clearSelection`, `closeOpenView`, `setVolumes` (no-op),
  `backToTitle`, `setShowAll` (admin only), `applyScatterPrefs`, `markResume`
  (acknowledged: no page reload exists natively); the others are logged once, and a player-triggered one
  answers with a toast "Not available in the native client yet").
- **Input**: a mouse event goes to CEF over a HUD surface (`hitRects`) or
  anywhere while an overlay is open, otherwise to the camera; the side that
  got the press keeps the pointer until release; CEF always sees the pointer
  for hover. Keys go to CEF while the HUD types (or an overlay is open) — the
  camera's W/A/S/D are gated then — otherwise Enter/F → open chat,
  M → menu, Esc → close the menu.
- **One login**: the Godot login screen logs in; its session cookie
  (`av_session`) is then written into CEF by a script on `/health` (the
  server's smallest anonymous page, same origin) — gdCEF exposes no cookie
  manager — and the HUD opens already signed in. CEF runs incognito (no
  cookie on disk), without a DevTools port; its log (incl. the page's console
  at "info") is `user://cef/debug.log` (Linux:
  `~/.local/share/godot/app_userdata/Anima Native/cef/debug.log`). "Back to
  title" in the menu logs out through the HUD page (CEF drops its cookie),
  then Godot returns to its login screen (see "Start" → "Back to the title").

Start (the HUD is on whenever the gdCEF artifacts are next to the binary):

```bash
./anima-native.x86_64 -- --server=http://192.168.8.244:8000 --user=demo --goto=LOCATION
```

What to look at on the PC with a display:

1. After the login: the HUD appears over the world (rail, chat corner,
   clock) and the world is visible everywhere between the panels — no grey or
   black page background; half-transparent panels have no dark fringe. The log
   line `hud: transparency probe` says `alpha=0` outside the surfaces.
2. The chat: F or Enter opens it; click into the composer, type a line, send
   it — the line appears in the transcript and a character answers (the
   HUD's own requests are signed in).
3. While typing in the chat, W/A/S/D/M/F type letters and do NOT move the
   camera or open the menu.
4. The plaque: click a figure in the world → its plaque (name, activity,
   mood) appears; "Zoom to" flies the camera to it; the close button or a
   click on empty ground clears it.
5. The menu: M opens it, M or Esc closes it; "Back to title" returns to the
   Godot login screen and a second login brings the HUD back.
6. A click (and a drag, and the wheel) on a half-transparent chat panel does
   NOT reach the world: the camera neither pans nor zooms; a camera drag that
   starts in the world keeps going when it crosses a panel.

## Offline checks of the export

The exported build can run the check too: copy `fixtures/` next to the binary
and start it with `--headless -- --check` from inside the repository (the figure
fixtures read the clip FBX files and a demo character GLB in place — `repo:`
entries of `fixtures/urls.json`, resolved above the fixtures directory, then
above the working directory; the bench check compares the embedded camera path
with `shared/bench/camera_path_v1.json` the same way). `--headless -- --check-bench`
works the same way.

## Layout

| Path | Content |
|---|---|
| `Main.cs`, `Main.tscn` | entry scene: login → world build → camera → (`--bench`) the drive; `--check`/`--check-bench` dispatch |
| `App/Main*.cs` | the rest of the entry scene's class, by concern: `MainSession` (login, session, back to the title), `MainWorld` (world build, boot stages, bench/offline), `MainSync` (poll, push stream, show all), `MainHud` (HUD game actions, picking, info panel) |
| `Cli.cs` | command-line parameters |
| `Core/` | the Godot-free library `AnimaNative.Core` (same namespaces `AnimaNative.*`, same subfolders): `Api/AnimaApi.cs` (HttpClient + cookie session, the server getters, `IWorldSource`), `World/` (payloads, `WorldHeight` + bench `Anchor`, `LocationView`), `Ground/` (`LayerCut`, `TerrainNormal`, `WaterTileField`), `Scatter/` (terrain payload, sampler, LOD and undergrowth maths), `Hud/HudProtocol.cs`, `Ui/LauncherSettings.cs` (the launcher file's rules: parse, serialise, merge with the flags, server-address normalising), `Bench/` (path + statistics, the embedded `camera_path_v1.json`), `Figures/CharacterRows.cs`, `Gltf/` (Meshopt decoder + its P/Invoke), `Sync/` (Task 10: `PollScheduler` = pollCore.ts, `SyncStream` = syncHub.ts + `HttpEventSource`/`SseParser` for `/events/sync`, `BootTracker` + `BootRetry` = game/boot.ts + `retryBoot`, `LocationsCache`/`LocationsSync` = the ETag'd `/world/locations?view=3d`, `ConnectionState`, the frame-pumped `TimerQueue`) |
| `tests/` | xUnit project on Core (`dotnet test tests`) |
| `test.sh` | `dotnet test` + build + headless `--check` |
| `World/` | the Godot side of the world (payloads, height + anchor and the view rules are in `Core/World/`): terrain, `place()`, recipe meshes + materials, model cache + placements (`SceneModels.cs`), surface library, shader safety, the builder |
| `tools/dump_payloads.py` | Task S3c: dumps the client's HTTP answers from a COPY of a world for `--offline` |
| `Gltf/` | runtime GLB import (the Meshopt decode is in `Core/Gltf/`) |
| `Figures/` | world-map characters: placement rule, figures (fed by Main's poll), clip library (import, pick, retarget), rest-pose correction |
| `Ui/` | login screen (server, user, password), `LauncherStore` (`user://launcher.json`), the overview camera, the label overlay (`LabelOverlay.cs`: projection, order, the label CSS in `LabelStyle`), the performance probe (`PerfProbe.cs`) |
| `Hud/` | gdCEF wrapper (`GdCef.cs`, the one class that calls the extension), protocol v1 scene side (`Core/Hud/HudProtocol.cs`), input routing + figure picking (`HudRouting.cs`), the overlay node (`HudOverlay.cs`) |
| `link_cef.sh`, `cef_artifacts/` | the one-time gdCEF link; the linked folder is gitignored |
| `Ground/` | Task S3b: the layer-cut port + payload (`Core/Ground/LayerCut.cs`, incl. `wantedTiles` and the natural-ground maths), the shading-normal twin (`Core/Ground/TerrainNormal.cs`), the ground shader (`GroundShader.cs`, + its water variant), the loader that builds slices/masks/material (`GroundSurfaces.cs`); Task S3c: the water numbers and window (`Water.cs`; the tile field is `Core/Ground/WaterTileField.cs`) |
| `Scatter/` | (payload, sampler and LOD/undergrowth maths are in `Core/Scatter/`) prop GLB → grounded mesh, the two MultiMesh layers, the sway shaders, the cadence driver |
| `Bench/` | the bench driver and its output (camera path `loadPath`/`samplePath` and statistics `summarize`/`percentile` are in `Core/Bench/`) |
| `Check/` | `--check`: fixture source and expectations, the S3c world (`S3cCheck.cs`: view rules, models, world props, water, shaders), bench maths, scatter (`ScatterCheck.cs`), ground surfaces (`GroundCheck.cs`: requests, window bytes and probes vs. the TS functions, slices, shader parameters and its front-end compile, AO and normal by hand, the fallbacks), HUD (`HudCheck.cs`: rects incl. the CSS/window scale, routing table, message validation, outgoing strings, picking, cookie script, name lists vs. the TS sources, every gdCEF method this client calls when the extension is linked); `--check-bench [--scatter]`: offline bench smoke |
| `fixtures/` | offline payloads (incl. `terrain.json`, the scatter reference vectors, the cut-down layer bake + surface library + the ground reference values) + a real Meshopt GLB pair + character/clip answers (hand-derived numbers in its README) |
| `third_party/meshoptimizer/` | meshoptimizer v1.3 sources (MIT, `src/*.cpp`, `meshoptimizer.h`, LICENSE) |
