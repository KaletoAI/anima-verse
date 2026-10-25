# Anima Verse — native client (spike)

A Godot 4.7.2 (.NET / C#) client for Phase 2 of `plan-native-client.md`: it
renders THE SAME world as the browser 3D client (`client3d/`) so both can be
timed on the same camera drive (`shared/bench/camera_path_v1.json`). Spike
quality — no game logic. Task S1a covers login, terrain, buildings, recipe
shells and a free camera; Task S1b adds the figures with idle/walk clips and
live positions; the bench drive comes in a later task.

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
  name — rotations verbatim, hips height scaled (see `Figures/ClipLibrary.cs`
  for what the browser does on top);
- a sun + fill light and ambient comparable to the browser, sky colour, no fog.

## Requirements (build machine)

- Godot **4.7.2 stable .NET** editor binary (`Godot_v4.7.2-stable_mono_linux.x86_64`)
  and its Linux export templates (`~/.local/share/godot/export_templates/4.7.2.stable.mono/`)
- .NET **8** SDK (`dotnet` on PATH)
- `g++` (compiles `third_party/meshoptimizer` into `bin/libmeshoptimizer.so`)

## Build, check, export

```bash
cd native
dotnet build                                  # C# + bin/libmeshoptimizer.so (csproj target)
$GODOT --headless --path . --import           # first import (creates .godot/)
$GODOT --headless --path . -- --check         # offline self-test → "CHECK ok …", exit 0

GODOT=/path/to/Godot_v4.7.2-stable_mono_linux.x86_64 ./build.sh [out_dir]
                                              # build + import + export "Linux" preset
                                              # default out_dir: native/export/
```

`build.sh` produces `anima-native.x86_64` (PCK embedded), the .NET folder
`data_AnimaNative_linuxbsd_x86_64/` and `libmeshoptimizer.so` — keep the three
together.

## Start

```bash
./anima-native.x86_64 -- --server=http://192.168.8.244:8000 --user=demo --goto=LOCATION
```

Arguments after `--` (no .env, no config file):

| Argument | Meaning |
|---|---|
| `--server=URL` | Anima server base URL (default `http://localhost:8000`) |
| `--user=NAME` | pre-fills the login field (the password is typed in, never passed or stored) |
| `--goto=ID\|NAME` | anchor: location id, or a case-insensitive name substring (the browser bench's `&goto=`) — the start camera looks at it, the 2 m tiles load around it |
| `--check` | offline self-test from `fixtures/` (see `fixtures/README.md`), then exit 0/1 |

Camera: drag with the left or right mouse button to orbit, wheel to zoom,
W/A/S/D to move, F to follow the next figure (name order; W/A/S/D lets go).
The status line top left reports what was loaded; per-location
failures are logged to the console (`[native] …`).

The exported build can run the check too: copy `fixtures/` next to the binary
and start it with `--headless -- --check` from inside the repository (the figure
fixtures read the clip FBX files and a demo character GLB in place — `repo:`
entries of `fixtures/urls.json`, resolved above the fixtures directory, then
above the working directory).

## Layout

| Path | Content |
|---|---|
| `Main.cs`, `Main.tscn` | entry scene: login → world build → camera; `--check` dispatch |
| `Cli.cs` | command-line parameters |
| `Api/AnimaApi.cs` | HttpClient + cookie session, the server getters, `IWorldSource` |
| `World/` | payload parsing, height sampling + anchor, terrain, `place()`, recipe meshes, the builder |
| `Gltf/` | Meshopt decode (P/Invoke) and runtime GLB import |
| `Figures/` | world-map characters: placement rule, figures + poll loop, clip library (import, pick, retarget) |
| `Ui/` | login screen, fly camera |
| `Check/` | `--check`: fixture source and expectations |
| `fixtures/` | offline payloads + a real Meshopt GLB pair + character/clip answers (hand-derived numbers in its README) |
| `third_party/meshoptimizer/` | meshoptimizer v1.3 sources (MIT, `src/*.cpp`, `meshoptimizer.h`, LICENSE) |
