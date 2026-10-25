# Anima Verse — native client (spike)

A Godot 4.7.2 (.NET / C#) client for Phase 2 of `plan-native-client.md`: it
renders THE SAME world as the browser 3D client (`client3d/`) so both can be
timed on the same camera drive (`shared/bench/camera_path_v1.json`). Spike
quality — no game logic. Task S1a covers login, terrain, buildings, recipe
shells and a free camera; Task S1b adds the figures with idle/walk clips and
live positions; Task S2 adds the bench drive (see "Bench" below); Task S3 adds
the scatter and the undergrowth behind `--scatter` (see "Scatter" below);
Task S4 lays the React HUD over the world through gdCEF (see "HUD" below).

What it draws after login:

- **terrain** — the `/play/heightfield` overview as one mesh, plus the 2 m tiles
  (`/play/heightfield/tiles`) within 384 m of the anchor as separate meshes;
  one neutral vertex colour, no textures/water/LOD;
- **buildings** — per placed location of `/play/worldmap`, the `role: building`
  model of its scene recipe (`/play/locations/{id}/scene`), loaded from
  `/play/locations/{id}/model` and placed by the contract's `place()` (§ B2);
  the server's Meshopt-compressed GLBs are decoded client-side
  (`Gltf/GlbMeshoptDecoder.cs` + vendored meshoptimizer);
- **recipe shells** — locations without a building model get their recipe
  plates/walls/extras as untextured meshes;
- **figures** — the characters of `/play/worldmap`, polled every 5 s, where the
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
dotnet build                                  # C# + bin/libmeshoptimizer.so (csproj target)
$GODOT --headless --path . --import           # first import (creates .godot/)
$GODOT --headless --path . -- --check         # offline self-test → "CHECK ok …", exit 0
$GODOT --headless --path . -- --check-bench   # offline bench smoke → "CHECK-BENCH ok …", exit 0

GODOT=/path/to/Godot_v4.7.2-stable_mono_linux.x86_64 ./build.sh [out_dir]
                                              # build + import + export "Linux" preset
                                              # default out_dir: native/export/
```

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
./anima-native.x86_64 -- --server=http://192.168.8.244:8000 --user=demo --goto=LOCATION
```

Arguments after `--` (no .env, no config file):

| Argument | Meaning |
|---|---|
| `--server=URL` | Anima server base URL (default `http://localhost:8000`) |
| `--user=NAME` | pre-fills the login field (the password is typed in, never passed or stored) |
| `--goto=ID\|NAME` | anchor: location id, or a case-insensitive name substring (the browser bench's `&goto=`) — the start camera looks at it, the 2 m tiles load around it; without it the avatar's location, else the world origin |
| `--bench` | run the camera drive once the world has loaded (see "Bench") |
| `--size=WxH` | window size; a bench run defaults to `1920x1080` (the result reports the size actually rendered) |
| `--vsync=on` | keep V-sync during the bench (default: off for the run, restored after) |
| `--quit-after-bench` | exit after the result file is written |
| `--scatter` | draw the scatter AND the undergrowth (default off — what the browser's `&scatter=0` hides); the bench flags say `scatter: true` |
| `--no-hud` | no HUD even when gdCEF is linked (the S2/S3 bench numbers were taken without it) |
| `--check` | offline self-test from `fixtures/` (see `fixtures/README.md`), then exit 0/1 |
| `--check-bench` | offline bench smoke: fixture world + a 0.5 s warm-up / 2 s drive on the headless dummy renderer, then exit 0/1 (with `--scatter`: the fixture's scatter layers ride along) |

Camera: drag with the left or right mouse button to orbit, wheel to zoom,
W/A/S/D to move, F to follow the next figure (name order; W/A/S/D lets go).
With the HUD up, F and Enter open the chat instead, M opens/closes the menu,
a click on a figure shows its plaque, and the plaque's "Zoom to" follows it.
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

Compare with the browser at the same window size:
`http://192.168.8.244:8000/play?bench=auto&goto=<loc>&scatter=0&water=0` (the
native client draws no water; without `--scatter` its flags say `scatter: false, water: false`).

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

## Scatter (Task S3)

`--scatter` turns on BOTH layers the browser bench's `&scatter=0` hides
(`terrainGround.debugParts().scatter` + `.undergrowth`), from the same inputs:
`GET /play/terrain` (areas bottom to top with their `meta.scatter` rows — the
server already puts the prop's `variants`, `model_variants`, `prop_height_m`,
`sway_factor` on each row — the type catalog's `meta.undergrowth`/`sway_m`/
`color`, and `prop_boxes`) plus the worldmap rows' `boundary` (location
footprints) and `game_time.total_seconds`. `/assets/props` is not read: the
browser's ground does not read it either (§ A9: the row carries the prop facts).

- **Where** — `Scatter/ScatterMath.cs` is an exact port of the shared sampler
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
  `backToTitle`; the others are logged once, and a player-triggered one
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
  then Godot returns to its login screen.

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
   mood) appears; "Zoom to" makes the camera follow it; the close button or a
   click on empty ground clears it.
5. The menu: M opens it, M or Esc closes it; "Back to title" returns to the
   Godot login screen and a second login brings the HUD back.
6. A click (and a drag, and the wheel) on a half-transparent chat panel does
   NOT reach the world: the camera neither orbits nor zooms; a camera drag that
   starts in the world keeps orbiting when it crosses a panel.

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
| `Cli.cs` | command-line parameters |
| `Api/AnimaApi.cs` | HttpClient + cookie session, the server getters, `IWorldSource` |
| `World/` | payload parsing, height sampling + anchor, terrain, `place()`, recipe meshes, the builder |
| `Gltf/` | Meshopt decode (P/Invoke) and runtime GLB import |
| `Figures/` | world-map characters: placement rule, figures + poll loop, clip library (import, pick, retarget), rest-pose correction |
| `Ui/` | login screen, fly camera (W/A/S/D gated while the HUD types) |
| `Hud/` | gdCEF wrapper (`GdCef.cs`, the one class that calls the extension), protocol v1 scene side (`HudProtocol.cs`), input routing + figure picking (`HudRouting.cs`), the overlay node (`HudOverlay.cs`) |
| `link_cef.sh`, `cef_artifacts/` | the one-time gdCEF link; the linked folder is gitignored |
| `Scatter/` | `/play/terrain` payload, the exact sampler port, the LOD/undergrowth maths, prop GLB → grounded mesh, the two MultiMesh layers, the sway shaders, the cadence driver |
| `Bench/` | camera path (`loadPath`/`samplePath`), statistics (`summarize`/`percentile`), the bench driver and its output |
| `Check/` | `--check`: fixture source and expectations, bench maths, scatter (`ScatterCheck.cs`), HUD (`HudCheck.cs`: rects incl. the CSS/window scale, routing table, message validation, outgoing strings, picking, cookie script, name lists vs. the TS sources, every gdCEF method this client calls when the extension is linked); `--check-bench [--scatter]`: offline bench smoke |
| `fixtures/` | offline payloads (incl. `terrain.json` and the scatter reference vectors) + a real Meshopt GLB pair + character/clip answers (hand-derived numbers in its README) |
| `third_party/meshoptimizer/` | meshoptimizer v1.3 sources (MIT, `src/*.cpp`, `meshoptimizer.h`, LICENSE) |
