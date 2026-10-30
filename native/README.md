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

- **terrain** — the browser's CDLOD terrain (Task 23, see "CDLOD terrain"): one instanced 33 × 33 patch on a
  6-level quadtree over the whole world frame (`world_bounds` ± 60 m), heights out of two R32F pyramids — the
  `/play/heightfield` overview (far) and the 2 m tiles (`/play/heightfield/tiles`) loaded within 560 m of the
  anchor (`HEIGHT_TILE_RADIUS_M` = `FOG_FAR_M` 520 + 40, the browser's rule; near) — morphed per vertex; dressed in
  the browser's ground material — the painted layers cut per texel from the
  server's masks, the surface textures, colour patches, height AO and the
  per-fragment shading normal (see "Ground surfaces"); the plain one-colour
  material when that fails or with `--plain-ground`;
- **water** — the browser's Wasser v2 terrain water: the pieces over a wet tile run the second program, whose
  vertex stage lifts each tap onto the mirror inside the outline, shaded by the water variant of the ground shader
  (see "Scene content"); off with `--no-water`;
- **locations** — per placed location in reach, what the browser's overview shows
  of its scene recipe (`/play/locations/{id}/scene`): the `role: building` model
  (loaded from its variant URL, Meshopt-decoded client-side —
  `Core/Gltf/GlbMeshoptDecoder.cs` + vendored meshoptimizer — and placed by the
  contract's `place()`, § B2), the outdoor model specs (props, door/window models,
  dioramas), the outdoor rooms' primitives, the far-view shell of a place without
  a model, and the avatar's OPEN location with its interior (see "Scene content");
- **world props** — the single props of `/play/worldmap` `world_props` (§ A9a);
- **figures** — the characters of `/play/worldmap`, polled at the browser's cadence
  (see "Polling, push stream, boot stages" below) and placed once a second from the cached map like the browser
  (Task 29, see "Figures in their rooms"): journey point along the route, free point in the wilderness, and per
  location the room ladder — seat, sit/lie surface, corridor stand, the server's point at the room floor, room
  centre — or the huddle in front of / around the location on the TILE ground; hidden on another storey and in a
  closed interior; every frame a figure WALKS to its point like the browser's NPC (Task 30, see "NPC walking"):
  3.4 m/s, running beyond 6 m, through doors, stair landings and lift stops, swimming where the ground says so —
  standing, it plays `standingClipFor(activity_animation)`: every figure plays its activity (read, cook, sit …). Model: `/characters/{name}/model3d` → the humanoid GLB
  (Meshopt-decoded), scaled to `height_cm`, metalness forced to 0; every load is a job of a width-3 queue (the
  avatar first, then the figure nearest the camera target), a transient failure retries after 30 s; an FBX
  (animals, rig `generic`) comes through Godot's `FBXDocument`, dressed in its separate `texture_url` (rows flipped
  once: Godot's import turns v into 1 − v, the browser samples with `flipY = false`) and plays its own takes with the
  `model.clips` loop flags (Task 34); a model without any action (no takes, rig `none`) walks procedurally — the
  browser's leg chains swing (`Core/Figures/ProceduralGait.cs`, vectors `animal_legs` / `animal_gait`), standing it
  breathes; "no model" is the browser's fallback pool model, else the portrait sprite; a changed `model_sig` or `model_rev` reloads it; distance tiers
  `full`/`low` (`low_url`) at 25/35 m with hysteresis, re-evaluated every second. Clips (Task 28): the WHOLE
  `/assets/animation-clips` library — downloaded through a width-4 queue in listing order, imported one per
  frame (`FBXDocument`), committed in listing order (first file per kind and set) — and per character the first
  file of each kind along its set chain (`animation_sets` + neutral), with that file's loop flag (a one-shot holds
  its last frame); one action per kind plus the browser's synonym aliases, played through `resolveClipKind` with
  the stand-in paces and a 0.25 s crossfade. Retarget by bone name with the browser's rest-pose correction against
  `/assets/animation-rig` (`Core/Figures/RestCorrections.cs` on plain pose data, vectors
  `shared/test-vectors/retarget.json`; the Godot side only reads rests and samples soles,
  `Figures/RestCorrection.cs`) and the browser's hips mapper (`Core/Figures/HipsTrack.cs`, bounce, scale healing,
  root path; vectors `hips_tracks.json`). Transition clips are parsed, played in Task 31;
- a sun + fill light and ambient comparable to the browser, sky colour, no fog (since Task 21: the game-hour stage,
  see "Game-hour light, sky and shadows");
- with `--scatter`: the authored scatter of the painted areas and the automatic
  undergrowth (see "Scatter").

### What stage E2 shows (Phase 3, Tasks 13–19)

The scene recipe and the interiors with storeys, as the browser's overview shows them, every number on the shared
vectors of `shared/test-vectors/scene_*.json` (and `light_pool`, `ambience`, `mirror_plane`, `slot_materials`,
`door_swing`):

- **Look inside** crossfades in ~0.75 s (`Hineinsehen` / "Close view"), taller neighbours in front fade out
  (see "Mounted once, opened by a crossfade");
- **storeys**: the in-world switch `-1. G 1. …`, slabs/walls/rooms/props of the shown storey only, the cellar through
  a hole in the ground, door marks in the thresholds, room names, boundary marks of refused places
  (see "Storeys at runtime");
- **model fidelity**: room dioramas clipped to their hull, half furniture cut at the wall, area/plan-hull cutouts
  opening with the fade, metalness neutralised, the building tier swapping at 45/60 m, re-datum on height revisions,
  a remount when a scene's signature moves (see "Model fidelity");
- **props**: pictures in frames, glass, mirrors, prop lights (night, flicker, halos), room ambience, door leaves
  (see "Slots, mirrors, lights, ambience and doors");
- **places data and problems**: the place markers with their lift, lift stops, stair flights, vertical targets and
  corridor stands on every mounted location (for E5/E7, nothing drawn — the browser draws place rings only
  embodied), and the composer's problems of the avatar's location as a HUD toast (see "Places data and problems");
- **§ B5a verify** after every mount: `-- --verify` prints `[verify] <loc>: N numbers checked, no deviation > 0.01 m`
  per location (otherwise only a location with a deviation is logged).

### What stage E3 shows (Phase 3, Tasks 20–26)

The browser's open world round the places, every number on the E3 vectors (`terrain_lod`, `height_tiles`,
`layer_ground`, `water`, `sky_light`, `backdrop`, `fog_veil`, `prop_water`):

- **terrain without holes**: the CDLOD quadtree over the whole world frame, streamed 2 m tiles while flying (no
  frame-sized stall: the field is built on a worker), the layer masks streamed with it (see "CDLOD terrain",
  "Terrain streaming");
- **the game hour**: the sun moves over the day, sky, light colours and intensities follow the clock, the shadow box
  sits on the camera target, MSAA 4× by default (see "Game-hour light, sky and shadows");
- **distance fog** 220–520 m in the sky's colour and the **mountain backdrop** rings (Task 22);
- **water**: shore gradient and foam, flowing rivers, waterfalls, the underwater ghost, prop water sheets (see "Water");
- **the exploration veil** over ground the avatar has never walked, in the overview only (see "Exploration veil");
- **scatter without hitches**: the 64 m window rebuild of the scatter and the undergrowth runs on a worker (see
  "Scatter").

### What stage E5 shows (Phase 3, Tasks 27–35)

The figures of the browser, every number on the E5 vectors (`figure_clips`, `retarget`, `clip_commit`,
`clip_coverage`, `hips_tracks`, `npc_placement`, `figure_ground`, `room_spots`, `npc_walk`, `npc_ground`, `stairs`,
`foot_lock`, `foot_lock_measure`, `leg_pin`, `stand_settle`, `bridge_*`, `pair_clip_*`, `pair_height`, `place_poll`,
`figure_normalisation`, `secondary_*`, `animal_*`):

- **every character plays its activity** from the server's WHOLE clip library along its set chain (`female`/`male`/
  `animal` + neutral), one-shots hold their last frame, distance tiers full/low at 25/35 m (Tasks 27/28);
- **sitting, lying, standing in the right room**: seats, beds, corridor stands, hidden on another storey or in a
  closed interior (Task 29); **walking** like the browser's NPC — through doors, up stairs and in lifts, swimming and
  wading with the underwater ghost (Task 30);
- **getting up** through the transition clips with planted feet, travel and turn (Task 31); **pair clips** in
  lockstep at one anchor, the bodies' feet on the ground (bind anchoring, Task 32);
- **hair and extension sway** (secondary motion with the exact skin normals, Task 33); **animals** with their own FBX
  takes, else the procedural gait (Task 34);
- **measured** (Task 35, see "Clip memory and figure cost"): clip memory per template, fit time per model, the frame
  cost of the figures (`--bench-matrix=no-figures`) and the figure keys of every bench result;
- **clips fitted on first play** (Task 35b, see "Lazy clip fit"): the boot's `figures` stage ~9 s instead of ~44 s on
  the world copy; a clip a figure plays for the first time arrives a few frames later (the figure keeps what it plays).

## Requirements (build machine)

- Godot **4.7.2 stable .NET** editor binary (`Godot_v4.7.2-stable_mono_linux.x86_64`)
  and its Linux export templates (`~/.local/share/godot/export_templates/4.7.2.stable.mono/`)
- .NET **8** SDK (`dotnet` on PATH)
- `g++` (compiles `third_party/meshoptimizer` into `bin/libmeshoptimizer.so`)
- for the HUD: the **gdCEF 0.21.0** release artifacts (CEF 156, Linux; the
  `cef_artifacts/` folder of github.com/Lecrapouille/gdcef, ~560 MB — never
  committed). Without them everything builds and runs, just without the HUD.

## Build, check, export

```bash
cd native
./link_cef.sh [/path/to/gdcef/cef_artifacts]  # ONCE: links the gdCEF artifacts as res://cef_artifacts/
                                              # (default source $GDCEF_DIR, else /home/dev/tools/gdcef-0.21.0/gdcef/cef_artifacts)
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
`*.pak`, `icudtl.dat`, `v8_context_snapshot.bin` (ANGLE is linked into `libcef.so` since CEF 152),
`libvk_swiftshader.so`, `libvulkan.so.1`, `vk_swiftshader_icd.json`, `locales/`
(hard links into the artifact folder where possible, copies otherwise).
Keep everything in one folder: gdCEF looks for its subprocess and resources
next to `libgdcef.so`.

Known: with gdCEF linked, Godot 4.7.2's editor-mode `--import` sometimes
segfaults (exit 139) while the process exits, AFTER the import has finished
(godot-cpp's static data outliving the engine); `build.sh` tolerates exactly
that code in exactly that case. The export and the game itself are not
affected (`--check` exits 0 with the extension loaded).

## AppImage packaging and publication

`package.sh` exports the Linux preset through `build.sh`, assembles an AppDir,
and packs it using the official [AppImage/appimagetool](https://github.com/AppImage/appimagetool).
It requires bash, Python 3, the build tools above, and the complete gdCEF artifacts.
A missing appimagetool is downloaded from official release 1.9.1 into
`/home/dev/tools/appimagetool/appimagetool-x86_64.AppImage` (curl required).
`APPIMAGETOOL=/path/to/appimagetool` overrides this host tool; it never goes in
this repository. The tool may download its AppImage runtime on first use;
`APPIMAGETOOL_RUNTIME_FILE` can select a pre-downloaded runtime for offline CI.

```bash
# From the repository root, with dotnet on PATH and GODOT set as above:
bash native/package.sh                         # native/export/appimage/
bash native/package.sh /absolute/output/path
bash native/package.sh --publish               # clean worktree required
python3 native/tests/package_test.py           # packaging contracts, no engine required

image="$PWD/native/export/appimage/AnimaNative-<version>-x86_64.AppImage"
"$image" --version                             # only the baked version; no engine/display needed
"$image" --headless -- --version                # read the version from the exported assembly
"$image" --headless -- --check                  # from inside the repository, see offline checks below
# Hosts without FUSE can use APPIMAGE_EXTRACT_AND_RUN=1 for these commands.
```

The version is `<UTC commit timestamp yyyyMMddHHmmss>-<short commit hash>`,
with `-dirty` for tracked changes or untracked source files anywhere in the
worktree. `build.sh` computes it before export; `ANIMA_BUILD_VERSION` becomes
`AnimaNative.Version` assembly metadata, exposed by `BuildInfo.Version` to the
launcher. `version.txt` beside the executable carries the identical value for
AppRun and `run.sh --version`. Plain editor/dotnet builds report `development`.
AppRun accepts client flags directly, or Godot flags followed by `--` and client
flags; `--headless` also works without a separator. Bare `--version` is handled
by AppRun because Godot reserves that engine flag for its own version.

AppRun writes the console transcript to
`${XDG_DATA_HOME:-$HOME/.local/share}/godot/app_userdata/Anima Native/logs/native-*.log`.
Its first line is `Anima Native <version>`, followed by the engine output.
Godot's separate `--log-file` also points into this directory (`*.engine.log`);
its own engine banner is retained. Launching never writes into the mounted
AppImage. The unpacked export's `run.sh` continues to repair executable bits
and log next to the build.

`--publish` refuses dirty sources, copies the image into `static/native/`, then
atomically renames a temporary `version.json` containing `version`, `file`,
`size` (bytes), `sha256` (lowercase hex), and `built_utc` (ISO 8601 UTC).
The image itself is also staged and renamed before the manifest becomes
visible; older `AnimaNative-*-x86_64.AppImage` files are deleted afterwards.
Concurrent publishers are serialized by `.publish.lock`. `static/native/` is
ignored by git and served by the existing static route.

The AppDir root holds `AppRun`, `anima-native.desktop`, `anima-native.svg`, and
`.DirIcon`. `usr/bin/` holds the Godot executable (embedded PCK), .NET data
folder, `version.txt`, `libmeshoptimizer.so`, every gdCEF artifact including
executable `gdCefRenderProcess`, and `fixtures/` for the offline check. No build
tool or repository model library is shipped. The full `--check` still needs a
repository working directory for its `repo:` references; normal play does not.

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

**Taking over another character** (game menu, Task 12). The HUD switches the
avatar on the server, sends `markResume` and reloads its page (the browser
reloads everything). Natively `markResume` is acknowledged, and the reloaded
`hud.html` that follows makes the scene rebuild the world for the new avatar
with the SAME session: the scene reloads like back to the title, but without a
logout and without the login screen — the loading screen comes up at once.
The trigger is the reload (`Core/Ui/SessionFlow.cs`): every `hud.html` load
after the session's first one (the handoff's own navigation) rebuilds, whether
`markResume` arrived before or after it — inside CEF a reload only ever means
"resume with the current session". Log: `markResume: acknowledged …`,
`character switch: the HUD page reloaded …`, `session carried over (role '…')
…`, then the usual boot stages.

**HUD settings across starts** (Task 12). CEF's profile lives in memory, so the
HUD's `localStorage` (show all, scatter distances, volumes, dock and chat sizes,
…) would be gone at every start. In gdCEF mode the page mirrors every
`localStorage` write to Godot (`window.godotMethods.hud_storage`, a binding
method of its own, not the bridge protocol); Godot keeps the entries per server
origin in `user://hud_storage.json` (Linux:
`~/.local/share/godot/app_userdata/Anima Native/hud_storage.json`, written
0.3 s after the last change, at most 256 KB — a larger write is dropped and
logged) and writes them back into `localStorage` in the login handoff on
`/health`, before `hud.html` loads. The scene reads the same entries at the
start like main.ts does: an admin's "show all locations" picks the first view,
the scatter distances the scatter LOD (`stored HUD settings: …` in the log).
No cookie and no session token is ever stored there. Delete the file to reset
the HUD settings.

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
| `--msaa=0\|2\|4\|8` | 3D multisample anti-aliasing of the main view; overrides the menu's Graphics tab for the whole run. Not given: the stored Graphics tab level (`av3d.view.graphics.v1`, default 2×), a bench run 4× as before; `0` for a weak GPU or a bench comparison (the bench start line logs it) |
| `--offline=DIR` | build from a payload dump (`tools/dump_payloads.py`) instead of a server: no login, no HUD; prints the world/scatter/figure/shader summary lines and quits (with `--bench`: runs the drive, then quits) |
| `--verify` | § B5a: log the full verify table of every mounted location (default: only a location with a deviation is logged, like the browser without `?verify=1`), plus each mount's `places[…]` line (Task 19) |
| `--check` | offline self-test from `fixtures/` (see `fixtures/README.md`), then exit 0/1 |
| `--check verify` | only the § B5a section of the self-test (both fixture worlds, `Check/VerifyCheck.cs`), then exit 0/1 |
| `--check storeys` | only the storey section (`fixtures/storeys/`, `Check/StoreysCheck.cs`: the switch at runtime, hole, marks, labels, pointer), then exit 0/1 |
| `--check fidelity` | only the model-fidelity section (`fixtures/fidelity/`, `Check/FidelityCheck.cs`: neutralisation, clip, cutouts, depth cut, tier swap, re-datum, sweep), then exit 0/1 |
| `--check props` | only the props section (`fixtures/props/`, `Check/PropsCheck.cs`: slots, mirrors, prop lights, doors, ambience), then exit 0/1 |
| `--check terrain` | only the CDLOD terrain section (`Check/TerrainCheck.cs`), then exit 0/1 |
| `--check water` | only the water section (`Check/WaterCheck.cs`, `fixtures/water/`: shaders, shore gradient and foam band, waterfalls, underwater ghost, prop water sheets), then exit 0/1 |
| `--check scatter` | only the scatter section (`Check/ScatterCheck.cs` on the fixture world: the S3 reference vectors, the runtime layers, and the Task 26 worker build — a moved window returns before it is rebuilt, a stale build is thrown away, the way back equals the reference), then exit 0/1 |
| `--check veil` | only the exploration veil (`Check/VeilCheck.cs`, `fixtures/explored.json`: shaders, cells texture, soft edge, crossfade, strength, colour), then exit 0/1 |
| `--check stream` | only the terrain streaming section (`Check/StreamCheck.cs`: a fake server answering height, statistics and mask batches for a ten-tile strip — batches, LRU, windows, `height_sig`/`terrain_sig` reloads, re-datum, re-index), then exit 0/1 |
| `--fly=M[,DEG]` | after the boot, fly the camera target M metres in a straight line (heading DEG: 0 = +x, 90 = +z) at 50 m/s, let the stream settle and log `fly done …` (tiles taken/evicted, the longest frame, the longest frame while streaming); with `--offline` it then quits |
| `--check shadow` | only the shadow section (`Check/ShadowCheck.cs` on `fixtures/s3c`: the browser's caster classes, the 140 m caster box gate, the cluster budget, the scatter hemisphere term, the compute-fog default), then exit 0/1 |
| `--check light` | only the light section (`Check/LightCheck.cs`: the game-hour stage at 6/7/9/12/18/22 h, hemisphere, shadow fit, material policy, MSAA option), then exit 0/1 |
| `--check placement` | only the room placement section (`Check/PlacementCheck.cs` on `fixtures/placement`: seats, sit/lie surfaces, server points at the room floor, corridor stand, huddle on the tile ground, storey switch, closed interior, the fallback pool), then exit 0/1 |
| `--check walk` | only the NPC walk section (`Check/WalkCheck.cs` on `fixtures/walk`: neighbour facing, treading water with the root eased to the mirror and the ghost, a door route, a 10 m run, a stair ride, swimming), then exit 0/1 |
| `--check bridges` | only the bridge-clip section (`Check/BridgeCheck.cs` on `fixtures/bridges`: get-up-chair / get-up-bed re-locked, pinned, lifted and turned per rig, planted feet measured on the rendered bones, the hand-over and the kept spot, a ramping start-walk, the deadline), then exit 0/1 |
| `--check pairs` | only the pair-clip section (`Check/PairCheck.cs` on `fixtures/pairs`: the halves' root paths, the anchor transform on the ground / a seat / a room, lockstep and the 0.3 s resync, a frozen world, the solo fallback, a handshake ending a bridge, the one-shot's end, the bind anchoring of every body), then exit 0/1 |
| `--check clips` | only the lazy clip-fit section (`Check/ClipFitCheck.cs` on `fixtures/bridges` + `fixtures/pairs`: what the build fits, bridges and a pair half asked for the first time later — the figures hold, then play — and every lazily fitted clip against an eager fit: keys, extras and poses bit for bit), then exit 0/1 |
| `--check figures` | only the figure section (`Check/CheckRunner.cs` `CheckFigures` on the fixture world: whole library, set chain, actions and aliases, activity clips, one-shot hold, model revision, model queue, tiers 25/35, the importer cross-check `rest_reference.json`), then exit 0/1 |
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
`godot`, `gpu`, `cpu`, `msaa` (the 3D samples of the run, Task 26), and after the stream keys `figures`,
`figuresAnimated` (the figures moving every frame) and `clipMemMiB` (their clip memory, Task 35). Per frame: `dt` = wall delta (unclamped), `cpuMs` =
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

### The E3 gate (Task 26)

Against the spike's numbers (`development_instructions/bericht-native-spike.md`, Mondscheinsee at **3816×1030**:
61.0 fps / 16.0 / 19.9 ms median / P95 with scatter and water, 77.7 / 12.5 / 16.0 ms without; 226 / 193 draws,
5.70 M / 4.04 M triangles) at the SAME size — `--size=3816x1030` (or fullscreen on that monitor):

```bash
./anima-native.x86_64 -- --server=http://192.168.8.244:8000 --goto=Mondscheinsee --bench --quit-after-bench --size=3816x1030 --msaa=0
./anima-native.x86_64 -- --server=http://192.168.8.244:8000 --goto=Mondscheinsee --bench --quit-after-bench --size=3816x1030 --msaa=0 --no-scatter --no-water
./anima-native.x86_64 -- --server=http://192.168.8.244:8000 --goto=Mondscheinsee --bench --quit-after-bench --size=3816x1030
./anima-native.x86_64 -- --server=http://192.168.8.244:8000 --goto=Mondscheinsee --bench --quit-after-bench --size=3816x1030 --no-scatter --no-water
./anima-native.x86_64 -- --server=http://192.168.8.244:8000 --goto=Mondscheinsee --fly=2000
./anima-native.x86_64 -- --server=http://192.168.8.244:8000 --goto=Mondscheinsee --fly=2000 --no-scatter
```

The spike ran WITHOUT MSAA (it came with Task 21) and with the HUD, so the `--msaa=0` runs are the comparison; the
default runs (MSAA 4×) say what the anti-aliasing costs. Pass: median and P95 of the `--msaa=0` runs not worse than the
spike's run with the same scatter/water switches (the result's `size` must read 3816x1030); draws, triangles and `msaa` reported;
the fly drive's `max while streaming` below 33 ms with scatter on (the bench drive stays inside the boot ring, so
its `streamMaxFrameMs` is normally null — the fly drive is the streaming probe). Every result also goes to the
server's `logs/bench.jsonl`.

### Figures on the gate (Task 35)

Since E5 every figure animates during the drive (clips, walking, secondary motion), and figures that cross the 25/35 m
tier band during the drive fit their other tier then (sliced at 12 ms per job and frame, like the browser). The E3 pass
numbers are the reference — with scatter + water 60.5 fps, 15.5 / 18.3 ms; without 81.7 fps, 12.0 / 14.2 ms — the
same two `--msaa=0` commands as above; target: median ≤ 16.0 ms with scatter + water. What the figures alone cost:

```bash
./anima-native.x86_64 -- --server=http://192.168.8.244:8000 --goto=Mondscheinsee --bench-matrix=no-figures --quit-after-bench --size=3816x1030 --msaa=0
```

Offline on the world copy (headless, dummy renderer, so CPU only; `cpuMs` = `Performance.TimeProcess`): 14 animated
figures cost **2.4–2.7 ms** of process time per frame in the median (baselines 4.8–5.9 / 5.0–5.4 ms, no-figures
2.6 / 2.7 ms, with / without scatter + water). The first pass's P95 (29 / 35 ms against 6–7 ms) is the low-tier fits of
five figures the drive passes: a single `--bench` run carries them too.

### Bench matrix (Task 26b, interleaved since Task 26c)

`--bench-matrix` runs the drive of `--bench` once per variant, in ONE process, on the SAME world and anchor, with the
same warm-up and duration — each pass with exactly ONE feature switched off (or one technique swapped) at runtime
(`Bench/BenchSwitches.cs`: a node hidden, a uniform zeroed, a light flag, a renderer setting; nothing is rebuilt) and put
back after it. It implies `--bench` (window size, start, `--quit-after-bench`); `--bench-matrix=A,B,…` runs only those
variants (the baseline is always added).

**Drift.** A laptop iGPU warms up and clocks down over the minutes a matrix takes (the second run of 2026-10-26 had
its middle passes 2–3 ms slower than the baseline although each switched something off). So a **baseline pass runs
between every two variants** (B V₁ B V₂ … Vₙ B, `BenchMatrix.Schedule`) and every variant is reported against the MEAN
of the two baselines right around it (`BenchMatrix.NeighbourDeltas`) — a drift that is linear over those three passes
cancels; each baseline shows its own drift against the first. The full matrix is 14 variants + 15 baselines = 29 passes
× 23 s ≈ 11 min; a subset (`--bench-matrix=no-shadow,fog-pass`) is 2n + 1 passes:

```bash
./anima-native.x86_64 -- --server=http://192.168.8.244:8000 --goto=Mondscheinsee --bench-matrix --quit-after-bench --size=3816x1030 --msaa=0
```

| variant | what is switched (and restored) |
|---|---|
| `baseline` | nothing (between every two variants) |
| `no-shadow` | the sun's `ShadowEnabled` off: no shadow pass, no shadow sampling |
| `shadow-full-view` | the browser's 140 m caster box off (`ShadowCasterGate.Off`): every caster in Godot's own frustum fit draws into the shadow pass (the pre-26c caster area) |
| `no-hemi-extra-lights` | ambient only: the two hemisphere pair lights hidden AND the hemisphere shader term (`av_hemi`: terrain, scatter, undergrowth) zeroed |
| `no-fog-pass` | the distance fog off (`DistanceFog.Off`): no compute pass, no screen pass, no copies |
| `no-veil` | `fv_alpha` 0 on every ground material (`VeilUniforms.Off`) — its uniform branch reads no texture |
| `no-backdrop` | the mountain backdrop rings hidden |
| `no-water-extras` | the terrain water's ripple (`tw_ripple_on` 0), every underwater ghost (`SubmergedGhost.Off`), the waterfalls and the prop water sheets |
| `no-mirrors` | no mirror reflection pass is granted (`MirrorPanes.Suspended`; the panes keep their picture) |
| `no-prop-lights` | the prop light pool hidden: six lamps and every halo |
| `no-cut-shader` | every cut surface wears its plain source material instead of the cut shader port (`CutMaterials.Plain`; holes and clips are gone meanwhile) |
| `terrain-lod-coarse` | the CDLOD selection with the pixel scale × 0.5 (`TerrainLodNode.PixelScaleFactor`) = allowed screen error 2 → 4 px |
| `shadow-atlas-2048` | `RenderingServer.DirectionalShadowAtlasSetSize(2048)` instead of 4096 |
| `fog-pass` | the fallback (not a feature off): the distance fog as the screen-texture pass instead of the compute pass (see `--fog`) |
| `no-figures` | every figure hidden AND its frame tick stopped (no walk, no clip advance, no skinning, nothing drawn; Task 35) — the figures' whole frame cost |

Every pass prints its `[bench] result {json}` line with the extra keys `variant`, `switch` (what it did, with counts),
`applied` (false = there was nothing to switch, e.g. no mirror in reach, or no GPU for the compute fog so `fog-pass`
changes nothing — the pass still runs), `matrixId`, `matrixPass`, `matrixPasses`, and `shadowCasters` (below); appends it
to ONE file `user://bench-matrix-<yyyyMMdd-HHmmss>.jsonl` (path printed) and posts it to `/play/bench-result` (→ the
server's `logs/bench.jsonl`). After the last pass the summary table (per pass: fps, frame median/P95, GPU median, the
reference = the neighbouring baselines' mean, ΔGPU against it, draws, triangles), the variants sorted by ΔGPU and the
baselines' drift are printed as `[bench-matrix] …` lines and shown in a panel; one closing `matrixSummary` line with
every pass's `gpuRefMs` / `gpuDeltaMs` goes into the local file. `--check matrix` switches every variant on the props
fixture and proves each restore puts back exactly what was there.

**`shadowCasters`** (every bench result, Task 26c, `Bench/ShadowCensus.cs`): what the directional shadow pass draws at
the drive's last pose, counted on the CPU against Godot's own caster volume (light-space box of the camera frustum slice,
at the requested `--size` aspect) and the sun's caster mask: `shadow-casters[draws=… tris=… instances=… <class>=instances/draws/tris …]`
plus the gate's `registered`/`inside`/`passes`/`last_ms`. Godot's light culler can only drop more, so it is an upper bound;
the headless renderer reports no draws at all, which is why it exists.

**`--fog=compute|pass`** — the distance fog as ONE compute pass on the colour buffer (**the default since Task 26c**;
`World/FogComputeEffect.cs`, a `CompositorEffect` at post-transparent on the overview camera; kernel and its CPU twin in
`Core/Sky/FogCompute.cs`) or as the screen-texture pass (`--fog=pass`, the fallback). The numbers are the screen pass's
(opaque pixels: identical display bytes, unit-tested to 1e-12 against the pass's own blend), the road is cheaper: no copy
of the colour buffer with its full mip chain and no depth copy every frame (with MSAA also no extra pre-transparent
resolves). Needs a GPU; without one, or when the kernel does not compile (logged), the screen pass fogs by itself. The
pass quad stays visible on render layer 18 for the mirrors' cameras (their reflections are fogged as before); only the
overview camera leaves that layer out while the compute pass runs. Difference: a transparent surface beyond 220 m
(glass, a fading location) is mixed in display space with the opaque depth behind it, where the screen pass attenuated
it by (1 − f) in linear space — neither is the browser's per-material fog for transparents.

## CDLOD terrain (Task 23)

Port of `client3d/src/scene/terrainLod.ts` (`createTerrainLod`), contract § A16.6:

- `Core/Terrain/TerrainLod.cs` — the selection maths (rings from the tile stats' error bounds and the pixel scale,
  `lodLambda`, `selectLodNodes` with parent quadrants, `selectLodFitted` under 4096 pieces, pyramids, the water mip
  cap, the CPU vertex twins), vector-checked against `shared/test-vectors/terrain_lod.json`;
- `Core/Terrain/TerrainField.cs` — `setField` / `update`: the far pyramid from the overview, the near pyramid over the
  loaded tiles' window (`nearWindow`, filled through the tile-first height), the water level pyramid + outline
  distance on the near lattice, the cap grid, the range, the level errors (overview `tile_stats` + every tile's own
  `stats`), the frame, and per frame the pieces split into the dry and the wet program (`nodeHasWater`);
- `Core/Terrain/TerrainLodGlsl.cs` — the vertex stage (and the shared sampler + shading normal) as Godot shading
  language, printed from the C# constants; `Core/Terrain/TerrainShaderTwin.cs` — its statement-for-statement CPU twin;
- `World/TerrainLodNode.cs` — ONE patch mesh in two `MultiMesh`es (dry, wet) with `INSTANCE_CUSTOM` = (x, z, size,
  level), the pyramids as R32F textures, the uniforms on the ground material + its water variant (or the plain
  terrain shader). It selects in `_Process` at priority 2000 (after the camera and the bench driver), from the
  camera's position and the real viewport height (pixel scale = height / (2·tan 22.5°), logged when it changes);
  the instance buffers are rewritten only when the piece list changes. No frustum culling (the browser's decision):
  world-sized AABBs. The terrain casts no shadow.

The world log line and the bench result carry `terrain[pieces= wet= draws= triangles= … cover=]` (`cover` = the share
of the frame the pieces cover, 1 = no hole).

## Terrain streaming (Task 24)

Port of the loaders of `client3d/src/scene/ground.ts` (`setHeightAnchor`, `refreshTiles`, `takeTiles`, `evictTiles`,
`fillMissingStats`, `refreshLayerTiles`, `reindexLayers`, `applyHeight`, `sync`/`reload`) with the want set of
`heightTiles.ts`:

- `Core/Terrain/TerrainStream.cs` — the Godot-free state machine: the anchor (the camera target; the avatar from E7),
  `wantedTiles` at 560 m, height batches of 64 by ONE loader, the LRU of 96 that never drops a wanted tile, a batch
  under another `height_sig` dropped whole, a tile whose origin is not its key dropped; the background statistics
  fill (64 per request, stepping aside while the ground is busy); mask batches of 16 with the want-set filter before
  every repack and the re-index when a batch answers under another cut; the poll's `height_sig` / `terrain_sig`
  reload chains. Plus `Coalescer` (one rebuild at a time, the rest folded into one) and `StreamProbe`. Unit-tested on
  simulated camera paths in `tests/TerrainStreamTests.cs`.
- `World/TerrainStreamer.cs` — the wiring: the anchor follows the camera target on main.ts' 1 Hz tick; a taken
  height batch rebuilds the field ON A WORKER (near pyramid, water fields on the near lattice, all images, from a
  `WorldHeight.Snapshot`) and only uploads on the main thread (`ImageTexture.Update` when the size held); a mask batch
  is packed on a worker and uploaded the same way; a new relief sets the AO, rebuilds the far pyramid and makes every
  location re-datum (the Task 17 hook, through the height revision); a new `terrain_sig` builds a new ground for the
  anchor and refetches the scatter's terrain; the scatter and the undergrowth re-sample the cells a changed tile
  touches. Every frame's wall time feeds the probe.
- `GET /play/heightfield/stats` is new to this client (`IWorldSource.GetHeightTileStatsAsync`); JSON bodies are now
  parsed off the main thread (`AnimaApi.ReadJson`).

The log says `stream: field rebuilt (… tiles, revision …) — … worker … ms, upload … ms` per build and every 10 s that
saw streaming a `stream stream[held= stats= tiles taken= evicted= … session probe[… streaming_max= …]]` line. The
bench result gets `streamMaxFrameMs` (the longest frame of the drive while the terrain streamed; null = nothing
streamed), `streamFrames` and `stream`.

## Water (Task 25)

Wasser v2 K-A has no water mesh for terrain water: the wet program lifts the terrain onto the mirror and shades the same
pixels as water (`GroundShader` water variant). Since Task 25 the look reads ONE field set on the near lattice with the
lift — the outline's signed distance through the vertex stage's own `tl_sd_at` / `tl_inside`, the look row
(`buildKindRows`) and the flow (`buildFlow`) over `tl_water_geom` (`TerrainField.KindRows` / `Flow`) — so held wet tiles
anywhere in the near window shade as water, and the old 560 m fragment window is gone. The ripple reads the wave map as
three's flipped canvas (`(u, −v)`, see `fixtures/README.md` "Water (Task 25)" W0); `tw_sky` and every prop water sheet
follow the game-hour sky (`StageAmbience`).

- **Waterfalls** (`World/WaterfallLayer.cs`): `waterfallsFrom` over every painted area's flow axis with a stroke width
  (`TerrainPayload` area `Falls`), one curtain quad (`waterfallQuad`, wave map scroll at the fall's mean speed, whiter
  downwards, edge fade, double-sided) + one foam disc per fall; rebuilt with every new ground. The log says
  `waterfalls: N [(x, z) top → bottom m, w m wide]`.
- **Underwater ghost** (`World/SubmergedGhost.cs`): a second draw of anything standing in water, `depth_test_inverted`
  (Godot 4.7.2: `COMPARE_OP_LESS` on the reverse-Z buffer = three's `GreaterDepth`), unshaded, water tint × own
  texture at 0.4, no depth write, cut at the waterline. Figures every frame (`FigureManager.WaterLevelAt` =
  `groundWaterLevel(typeAt(x, z).water_level, groundScope)`), scene placements at mount / re-lift / tier swap and world
  props at placement (`waterGhostAt`: level AND outline). `--no-water` turns every ghost off.
- **Prop water** (scene v18 `water.regions[]`, `World/PropWaterSheets.cs`, `Core/Water/PropWater.cs`): one flat
  transparent sheet per region at `y + lift` in the placement's parent (world props: world frame, the ground under the
  anchor), the still surface water look, cached per tint|opacity, moved with every re-lift. `waterRegionAt` and the
  walk gates (`Core/Water/WaterGates.cs`) are vector-checked against `prop_water.json` (figures swimming in them: E5).
  The log says `location … : N prop water sheet(s) [spec storey L, …], M underwater ghost(s)` per mount.

The build summary carries `water_extras[falls= prop_sheets= ghosts=]`; `--offline` adds `N in water [name bed … cut …]`
to the figures line.

## Exploration veil (Task 26)

Port of `client3d/src/scene/fogVeil.ts` + main.ts `syncExplored` (contract § A12): haze over the 64 m cells the avatar
has never walked, on the open world's ground only (the CDLOD terrain, dry, wet and plain) — props, scatter, places and
figures stay as they are (the server already withholds figures on unexplored ground).

- `Core/Sky/FogVeil.cs` (vector-checked, `fog_veil.json`) — cells, grid with one zero ring, texel centres on cell
  centres, the height ramp; `Core/Sky/FogVeilState.cs` — the cells texture of `setFogVeilCells`, the A/B crossfade
  (0.6 s), the strength `0.72 · smoothstep((h − 20)/25)` of the camera height above its target, `fogged`, and
  `ExploredSync` (`/play/explored` refetched only when `explored_sig` moves, the server's signature kept, a failure
  keeps the veil);
- `World/VeilUniforms.cs` — the shared uniforms (`fv_*`) on every bound ground material; a texture is made only when
  the memory changed, per frame only the alpha (and for 0.6 s the mix) is written;
- `Ground/GroundShader.cs` — two linear, clamped R8 samples mixed by `fv_mix`; the haze takes `alpha · (1 − explored)`
  of the finished colour (ALBEDO · (1 − a) + EMISSION colour · a; under the water's sky and foam on wet ground). Its
  colour is the clock's sky.

The admin's "show all" view (`fogged: false`) has no veil; a session without an avatar (`explored_sig` empty) is a
memory of nothing — the whole ground hazed in the overview, clear from about 20 m camera height down. The log says
`veil: N explored cells (sig S), grid (cx0, cz0, cols, rows)`; `--offline` prints `offline veil[…]` (a dump needs
`explored.json`, written by `tools/dump_payloads.py` since Task 26).

## Ground surfaces (Task S3b)

The terrain wears ONE Godot spatial shader (`Ground/GroundShader.cs`)
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
4 × 4 `texelFetch` of the near pyramid's level 0 at `tile_step_m`, else the overview's),
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
  (`arrivalLocId`, fade 1), at storey 0 (buildTile). Its interior group shows:
  storey plates only on the shown storey, room groups only on it
  (outdoor/always-visible rooms always), outline walls only on it and only where
  the camera is not on their outer side (`applyWallCulling`, per frame in the
  recipe shader), door leaves / window panes that a model fills stay hidden,
  extras (stairs, lift) always; its indoor model specs of every storey are placed
  in their room groups. A shell building model fades out (not drawn);
  a plan-hull or ground model stays and loses what lies inside its `cutouts` —
  per fragment, like the browser (see "Model fidelity" below).
- **Closed locations**: the building model(s), the outdoor model specs (no room
  or an outdoor / always-visible room) and the outdoor rooms' primitives; a place
  without a building model shows its far-view shell (`shellPlan`: copies of the
  level plates at or above ground and of every non-glass wall, leaves included).
  The interior group stays invisible until the location opens (its primitives are
  mounted and counted `interior`; its indoor specs are mounted in the near ring and
  counted `interior` in the far ring, where they are not).
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
- **Water** (`Core/Water/WaterShade.cs`, the water branch of `Ground/GroundShader.cs`):
  Wasser v2 K-A has no water mesh. A CDLOD piece over a wet height tile (`water` block of
  `/play/heightfield/tiles`) runs the wet program, whose vertex stage lifts each tap of the morph pair onto
  `liftedHeight(h, level, sd)` (`tlodLift`, the water level pyramid on the near lattice) and hands the depth to the
  fragment (`v_wet`, the browser's `vTlodWet`); the
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

Not ported yet (view-only, counted nowhere): door swinging (needs an avatar, E7), streaming in/out of rings while the
camera moves (E6; the tier swap does run, see "Model fidelity"). The underwater ghosts, waterfalls and prop water
landed in Task 25 ("Water", below). Slots, clip, depth cut and prop lights landed in Tasks 17/18 (sections below).

Summary line of a build (online log, `--offline`, `--check`): `primitives=N
skipped=M (degenerate=… interior=… storey=… panes=…) shell_copies=…
culled_walls=… interior_mounted=… models[building=… room=… prop=… door=… window=… world=…
placeholders=… missing=… interior=… storey=… faded=… culled=… full=… low=…]
… water[…] … verify[locations=… checked=… rows=…]`. `primitives`/`skipped` describe what the browser SHOWS at
each location's fade target; `interior_mounted` what stands in the interior groups.

### Mounted once, opened by a crossfade (Task 15)

Every location is mounted ONCE (`World/WorldBuilder.cs` `BuildFromScene`, the browser's `mountShell` +
`mountDetail`): building models, outdoor specs and outdoor primitives off the location group; the interior
(primitives of the mounted storey and, in the near ring, the indoor specs) in a child `Interior` held at fade 0;
for a place without a building model the far-shell copies. "Look inside" / "Close view" only flip the fade target
(`WorldBuilder.SetOpen`); `WorldBuilder.TickView` runs per frame (every run with a world) and drives
`World/LocationFade.cs` with the Core numbers (`SceneView.FadeStep` 4/s — 95 % in ~0.75 s — `FadeOpacities`, the
neighbour occlusion `NeighbourOccludes` + `OcclusionStep` 8/s). Opacities go into
`GeometryInstance3D.Transparency` (one per mesh instance, multiplied by Godot into the material's own alpha; the
recipe shader writes `ALPHA *= opacity`), set to 0 wherever Godot would draw opaque anyway (fade alpha ≥ 0.999), so a
mesh is in the transparent pass only while a fade runs. The cutouts of a building model switch on at fade
0.03 (a uniform, see "Model fidelity"). Only shown meshes are pickable.

### Model fidelity (Task 17)

- **Cuts per fragment** (`World/CutMaterials.cs`, `Core/Scene/CutShader.cs`): the room clip (`clip_outline`, keep
  inside, ≤ 64 points), the area cutouts (`cutouts`, discard inside any of ≤ 16 polygons or within the GLB's
  `interior_cutout_padding_m` × world scale of an edge, switched by `cut_on`) and the depth cut (`cut_plane`, keep
  n·p + c ≥ 0) are one test appended to each cut mesh's shader and evaluated on the fragment's world position, the
  last statement of `fragment()`; double-sided like the browser. A StandardMaterial3D cannot be patched (no
  onBeforeCompile, its generated code is not readable at runtime), so its shader is regenerated by
  `Core/Scene/StandardShaderCode.cs` — a port of Godot 4.7.2's `BaseMaterial3D::_update_shader` for everything a
  glTF import sets, with the engine's uniform names fed the material's own values; a material with a feature the
  port lacks keeps its own look uncut (logged once). A ShaderMaterial source (the placeholder box) keeps its code.
  The clones belong to the placement (per-instance surface overrides); the template is never touched.
- **Metalness** (`ModelCache.NeutralizeMaterials`): every imported GLB once — untextured metal above 0.5 → 0.
- **Display rules**: `ground` / `plan_hull` stay, `shell` / `shell_area` / roof-only fade as roof parts, a ground
  model hides below ground, a shell area's cutouts stay shut, a roof-only lid keeps the far shell.
- **Tier swap at runtime** (`WorldBuilder.TickModels`, once a second from `TickView`): building tier with the 45/60 m
  hysteresis on the camera distance minus the footprint's half diagonal, interior tier (closed area scene → low);
  the old mesh stands until the new one has loaded, then the record's node is replaced in place with its cuts.
- **Height revisions** (`WorldHeight.Revision`): a new batch of height tiles re-datums every location under its pin
  and re-lifts its storey-0 placements (`tileDatumStep`, `storeyGroundRelift`).
- **Scene sweep** (`WorldBuilder.SweepAsync`, every 60 s online): a location whose scene `signature` moved is
  mounted again (open target and storey carried over).
- Checked by `--check fidelity` (fixtures/fidelity, README there) and `tests/CutShaderTests.cs`.

### Slots, mirrors, lights, ambience and doors (Task 18)

- **Texture slots** (`World/SlotMaterials.cs`, decision `Core/Scene/SlotFill.cs`): a material whose name (without one
  `slot_` prefix) matches a key of `models[].slots` takes a picture (loaded per placement, white tint, sRGB) or the
  glass preset (alpha 0.3, roughness 0.06, metallic 0, two-sided) — as a per-placement surface override, BEFORE the
  cuts, so the cut clones carry it; a picture that arrives after the cut is written into the cut clone's parameters.
- **Mirror panes** (`World/MirrorPanes.cs`, `Core/Scene/MirrorMath.cs`): the plane is measured from the pane surface's
  faces (`planeOfFaces`, coherence ≥ 0.9). Godot 4.7's Camera3D has no custom/oblique projection, so each pane has a
  512 px SubViewport whose camera stands at the viewer's mirror image and looks straight through the pane with an
  off-axis frustum whose near plane IS the pane (everything behind the mirror is clipped, as Reflector.js' oblique
  plane does); the pane samples it projectively and overlays the 0x777777 tint. At most 2 passes per frame across all
  panes in turns (`MirrorBudget`), no refresh beyond 12 m once a pane has a reflection, nothing for a hidden pane.
- **Prop lights** (`World/PropLightPool.cs`, `Core/Scene/PropLights.cs`): six OmniLight3D slots (no shadows,
  attenuation 2 = three's decay 2 with the range window), re-picked at 5 Hz from every source (`pickLights`: night
  gate, shown room, range + 30 m, nearest, sticky slots), 0.4 s fades, candle/fire flicker, additive billboard halos
  of 2·glow_m; energy = intensity / π (the stage's mapping, Task 21). The night factor comes from the world map's
  `game_time.hour_fraction` (every 60 s), like the browser's.
- **Room ambience** (`World/StageAmbience.cs`, `Core/Scene/Ambience.cs`): the room under the camera target in the open
  location (smallest room rectangle, else the storey corridor) eases daylight/tint with τ 0.5 onto sun, fill, ambient
  and the water's sky — multiplied onto the game-hour base since Task 21.
- **Door props** (`World/DoorProps.cs`): the `leaf` node hangs in a pivot from `leafPivot`; shut in the overview, the
  swing (`Core/Scene/DoorSwing.cs`) waits for an avatar (E7).
- Checked by `--check props` (fixtures/props, README there), the vector tests (light_pool, ambience, mirror_plane,
  slot_materials, door_swing) and `tests/PropsCoreTests.cs`.

### Game-hour light, sky and shadows (Task 21)

`World/StageAmbience.cs` builds the browser engine's stage once and `Core/Sky/StageLight.cs` (Godot-free, unit-tested)
computes every value of it:

- **The clock** (`engine.setGameHour`, `gameHourLights` on `sky_light.json`): read from the worldmap poll's
  `game_time.hour_fraction` at boot and every 60 s; it moves the sun (`(60 cos a, 80 max(0.08, sin a), 25)` from the
  texel-snapped camera target, `snapShadowCentre`), sets the sun colour, the three intensities, the sky background and the
  water's `tw_sky`, and the night factor for the lamps. Before the first reading the browser constructor's stage stands.
  The room ambience multiplies this base (`applyAmbience`); the sky background stays.
- **Units: Godot energy = three intensity / π** for sun, fill, hemisphere and prop lamps (three divides every light by π
  in its BRDF, Godot multiplies directional/omni energy by π and divides by π in Lambert, and its ambient has no π). The
  old stage factor 1/2.032 was 1.55× too bright. Light/ambient/background colours are three's LINEAR colours encoded
  with the exact inverse of Godot's `srgb_to_linear` (`GodotSrgb.Encode`).
- **Hemisphere**: an ambient colour (S + G)/2 plus two shadowless, specular-free directional lights of colour (S − G)/2,
  one straight down and one straight up with `light_negative` — exactly three's `mix(G, S, ½ + ½·n.y)` on a Lambert
  surface. On the TERRAIN the pair is a shader term instead (Task 26b, `World/HemiUniforms.cs`): the terrain instances
  sit on render layer 20, which the two pair lights skip (`light_cull_mask`), and every ground shader adds
  `ALBEDO · (1 − METALLIC) · av_hemi · n.y` to its emission — the exact sum Godot forms for the pair — so the screen's
  largest surface no longer runs two extra `light_compute` per pixel. Since Task 26c the scatter and the undergrowth do
  the same (`Scatter/ScatterShaders.cs`, their nodes on layer 20, n = the shading normal after Godot's back-face flip).
  Models, recipe pieces and figures (StandardMaterial3D) keep the lights. No sky reflection (`ReflectedLightSource.Disabled`), sun/fill `light_specular` 1 (Godot's 0.5 halves the
  directional GGX; omni lights already double theirs), linear tone map (three's NoToneMapping).
- **Materials**: Lambert diffuse like three's MeshStandardMaterial on every imported GLB (`GlbLoader.BrowserLook`), the
  scatter, the recipe fallback and the placeholders; GLB meshes and the scatter receive no shadow (three's
  `receiveShadow = false` there — only ground, plates and placeholders receive); the terrain casts none.
- **Shadow**: one orthogonal directional shadow (Godot fits it to the camera frustum up to
  `ceil((camera distance + 70)/10)·10` m and snaps it to texels itself) on the 4096 atlas — 3.8–10.6 cm per texel over
  the zoom range, 7.2 cm at the boot zoom against the browser's 6.8 cm.
- **Shadow casters like the browser** (Task 26c). *Where*: three draws into its shadow map only what its orthographic
  shadow camera sees — ±70 m around the snapped centre in the light plane, 0.5–300 m from the sun. Godot culls casters
  against the light-space box of the whole camera slice instead (at aspect 3.7 several times that). `World/ShadowCasterGate.cs`
  registers every GeometryInstance3D through the tree's `node_added`/`node_removed`, puts render layer 19 on the
  casters whose bounds meet the browser's prism + 8 m (`Core/Sky/ShadowBoxGate.cs`; a pass when the centre moved 4 m,
  the light turned, casters came or went, and every 0.5 s for walkers) and the sun's `shadow_caster_mask` is that layer:
  inside the box the shadow is the browser's, outside there is none — as in the browser. *What*: three's per-class
  `castShadow` — building models and the far-shell copies cast; inside an interior only the plates of a storey above
  ground with a thickness (`plate.level > 0 && plate.thickness > 0`); walls, extras, recipe placements, world props,
  stand-ins, sprites, scatter, undergrowth, terrain never; outside an interior everything follows the shell flag of the
  crossfade (on below fade 0.4), and a location without an interior keeps its construction flags (`applyTileFade`
  returns early). Bench variant `shadow-full-view` switches the box off.
- **Clustered lights** (Task 26c, `project.godot`): `rendering/limits/cluster_builder/max_clustered_elements` = 32
  (default 512). Godot clears, rasterises into and packs its cluster render buffer every frame in which ANY omni light is
  visible; at 3816×1030 that buffer is 41.8 MB at 512 and 2.6 MB at 32. The world has at most the six prop lamps and no
  spot lights, decals or probes. The lamps themselves follow the browser exactly (`pickLights`: a `when: night` lamp only
  above night 0.3, an `always` lamp — most of them, by day too — only in a shown room and within range + 30 m); an
  empty or dark slot is hidden (Task 26b).
- **MSAA** 4× by default (`--msaa=0|2|4|8`).
- **Prop lamps** (Task 26b): a pool slot without a source or at energy 0 is hidden — Godot clusters every visible omni
  light by its range (4096 m for a range-0 lamp) whatever its energy.
- Checked by `--check light` and `tests/StageLightTests.cs`.

### Storeys at runtime (Task 16)

Every storey is mounted (one room group per declared room — outdoor ones off the location group, the rest in
`Interior`; recipe meshes per unit: slab / room plate / outline wall per storey). `LocationSlot.LevelFilter` is
view state (0 at the mount); `World/LocationStoreys.cs` applies it per frame from `TickView` with the Core's rules
(`SceneView.RoomVisible` / `StoreyPieceOpacity`, `StoreyView`): room groups by storey, slabs and outline walls of the
shown storey only (fade > 0.03), room plates on their solid twin (`MaterialOverride`) on the displayed storey,
a ground model hidden and the basement hole (`GroundShader` `hole_rect`/`hole_on`, the rectangle grown towards the
camera) while a storey below ground is shown. Overlays: door marks per declared storey (near-ring buildings, gold /
locked red from the HUD's lock fields), boundary marks (world frame, shown while the avatar is refused the place),
room labels (label overlay, fade > 0.5, not on area locations) and the in-world level switch
(`Ui/LevelSwitchOverlay.cs`, scene-owned like the browser's — no bridge message): a button row on the first lift
box (else (2.2, 0)) ⅔ of a storey above the shown floor; a press on it is taken by Godot's GUI pass before the
camera's `_UnhandledInput`, so it never picks, orbits or drags.

### Places data and problems (Task 19)

`Core/Scene/ScenePlaces.cs` composes what the browser's `mountShell` files on the tile for the figures and the embodied
mode — `LocationSlot.Places` (`PlaceInventory`), every point through the vector-checked `tileToWorld` /
`storeyGround*` / `markerLiftPoint`:

| Field | Shape | Browser twin |
|---|---|---|
| `Markers[room id or name][marker id]` | `PlaceEntry`: `Slots` (world `Vec3[]`, figure-root height = surface − `Drop` + `Lift`, re-lifted IN PLACE), `RoomId`, `Group`, `Rotation`/`Tilt`/`Roll` (deg, tile frame), `Drop`, `OffsetY`, `Fixed` (prop marker), `Diorama`, `Level`, `Lift`, `LiftAt` (world xz), `Anchor` (tile xz, prop markers) | `tile.roomMarkers` (`PlaceEntry`, placeSlot.ts) |
| `ElevatorStops[level]` | world `Vec3`: the pad's top face | `tile.elevatorStops` |
| `Stairs[]` | `StairLink`: `Id`, `Foot`/`Head` (`Level`, world `Pos`), `At` (run foot, world xz), `Dir` (unit, world xz), `RunM`, `WidthM`, `Steps`, `Footprint` (world xz) | `tile.stairs` (`StairWorldLink`) |
| `VerticalTargets[]` | `(Kind "elevator"/"stairs", Flight)` — flight −1 = the lift | `tile.verticalTargets` (without the mesh groups: native draws extras merged) |
| `Corridors[]` | `CorridorStand`: `RoomId`, `Level`, `Anchor`/`Outline` (tile frame), `PlateTop`, `Stand` (world; storey 0 on the tile ground ladder since Task 29) | `tile.corridors` + `roomCenters` |

`PlaceInventory.SlotFor` (`slotFor`) and `GlyphRows` (`buildGlyphs` over `/play/places` offers) read it; the rings
are not drawn (the browser draws them only embodied — E7). The re-datum (`WorldBuilder.Redatum`) carries it like
`reliftScene`: world-composed points and PROP markers ride the datum step and re-lift; ROOM markers are re-derived
from their room's floor afterwards (Task 29, `deriveRoomSpots` → `roomBaseFloorY − drop + offsetY`), and the storey-0
corridor stands stand on the tile's ground ladder.

The scene's `problems[]` (`LocationSlot.Problems`) of the AVATAR's location are toasted through the HUD's `toast` action
on every world-map poll, once per (location, kind, room), never one with `scope: "editor"` (`SceneProblems.Announce`,
main.ts `announceSceneProblems`), and logged as `[scene] <loc>: <kind> — <message>`. With `--verify` / `--check` every
mount logs a `places[markers=… prop=… slots=… stops=… flights=… targets=… corridors=… stands=… problems=… toastable=…]`
line. Checked by `tests/ScenePlacesTests.cs` and the S3c section of `--check` (fixtures/README "Places").

### Figures in their rooms (Task 29)

The browser's `computeNpcPlacements` once a second over the cached map (`FigureManager.TickPlacement`, and on every
poll), with each mounted location's view state NOW — interior fade (> 0.5 = revealed), shown storey, near ring:

- **Core rules, vector-checked**: `Core/Figures/NpcPlacement.cs` (`huddleOffset`, `placeAtLocation` — the room ladder,
  `npc_placement.json`), `Core/Figures/FigureGround.cs` (`placementOf`, `figureTransition`, `pollIsStale`,
  `gateStandY`, `standY`, `tileWalkLadder`, `roomFloorLadder`, `roomStandLadder` — `figure_ground.json`,
  `room_spots.json`, `place_poll.json`), `Core/Figures/RoomSpots.cs` (`polygonCentroid`, `roomSpotGrid`,
  `furnitureUse`, `roomSpotsOf` — `room_spots.json`). The sort is JavaScript's `localeCompare` (`LocaleCompare`: .NET
  InvariantCulture on ICU, proven against V8's order in `tests/FigurePlacementVectorTests.cs`). The floor rungs
  `recipeFloorAt` / `declaredFloorAt` / `plateCeiling` have no shared vector yet: `tests/FigureGroundRungTests.cs`
  holds the hand cases of `smoke_walk_math.mjs`.
- **The tile's ground and stands** (`Core/Figures/FigureStands.cs`, filled by `World/WorldBuilder.Stands.cs` after the
  mount, every re-lift and an interior tier swap): the ground ladder (`tileGroundY` = baked storey-0 lattices >
  declared room floors > declared storey plates under the ceiling > the datum, against the world ground — the higher
  wins; this fixes drift D6, figures used to stand on the world height alone), room floors (hull + declaration:
  plate top, overlay y, diorama `walk_y_world + lift`), centres, sit/lie surfaces measured on the placed props'
  world boxes, ROOM marker heights, corridor stands.
- **Per figure**: seat by `place.id` (marker facing turned into the world, `tilt`/`roll` as the lean, Euler YXZ), the
  sit/lie pool of its activity's family, the corridor stand, the server's `pos` at the room's standing height, the
  centre; else the huddle on the tile ground. A standing figure faces its movement target's place. Hidden on another
  storey (the switch of Task 16) and in a closed interior (the fade of Task 15). A view change SNAPS (no walk); a
  real room change WALKS its door route (Task 30, below).
- **No model** (ruling P3-R10): the browser's fallback pool from `/static/client3d/models/manifest.json` (Soldier,
  Xbot, Robot; assignments first, else `seededRandom('model:' + name)` over the rigs the clip library fits — their
  own takes win their kinds), scaled to the manifest height; while the pool loads or when it fails, the portrait
  sprite (`Figures/Portrait.cs`: seeded ring colour, the cut-out `avatar_url?transparent=1`, initials until it
  arrives, sized `clamp(camDist·0.055, 1.7, 3.4)`, bobbing while it moves; its tag hangs below it).
- `--check placement` (`Check/PlacementCheck.cs`, `fixtures/placement/`, README there) and `--offline` print a
  `offline placement <loc> open[…] closed[…]` census per location.

### NPC walking (Task 30)

The browser's `NpcManager` walk (`client3d/src/scene/npcs.ts` `update`/`tick`, pure rules `game/npcWalk.ts`), ported
to `Core/Figures/NpcWalk.cs` (vectors `npc_walk.json`, `npc_ground.json`), `Core/Scene/Doors.cs`, `Core/Scene/Stairs.cs`
(the stair module by hand, `tests/StairsTests.cs`) and `Core/Figures/NpcRoute.cs`; the frame is
`FigureManager.Tick`:
- **Once a second** (the placement pass) a NEW goal adopts its stations; a snap (first sight, a view change) puts the
  figure on it. A real room change is ROUTED (main.ts): the party-wall doorway if the two rooms share one, else out by
  the old room's door (`roomDoor`: the outside door first), the storey change by STAIRS first (`stairChain`, the legs
  become the figure's ride, unarmed) else the lift stops, in by the new room's door.
- **Every frame**: stations retire at 1.5 m (0.4 m during a ride); the step is 3.4 m/s, ×1.8 beyond 6 m (+10 m while a
  station is left) on a ground that lets one run, never for a travelling character (journeys follow their polled
  point until E6); the yaw eases ×10/s; standing, the marker's facing beats the neighbours' centroid within 4.5 m.
- **The ground word** under the figure (`WorldBuilder.FigureGroundMove`: ground.ts `typeAt` + the scope + prop water;
  `FigureGroundY`: the tile ladder inside a footprint, the world outside): swim / crawl / walk / walk_run, the sinks,
  the mirror. The clip is `moveClip(movement, run)` moving, `standingClipFor(activity, idleClip(movement))` standing;
  a clip the ground names drops the body by the ground's sink (move / idle depth); over water the root rides
  `floatRootY` = max(bed + sink, mirror), eased ×4/s; the underwater ghost is cut at the UNGATED mirror over the bed.
- **Stairs** (ruling P3-R9: `rideStep` ported here, E7 reuses it for the avatar): once the start landing is reached the
  ride owns the height — the ramp along the run — and it ends at the far landing.
- Not yet: journey routes and dead reckoning (E6), the player-driven figure and first person (E7).
- `--check walk` (`Check/WalkCheck.cs`, `fixtures/walk/`, README there); `--offline` logs `offline walk …` lines: a
  figure moved 12 m over open ground, into the first painted water, and a room figure sent to another storey.

### Pair clips and bind anchoring (Task 32)

A worldmap row's `interaction` (§ A8a) runs the browser's pair (npcs.ts `adoptInteraction` / `tickInteraction`,
figures.ts `playPair`; core `Core/Figures/PairClip.cs`, vectors `pair_clip_phase.json`, `pair_clip_geometry.json`,
`pair_height.json`, `pair_blend.json`):
- **Adoption** per poll (the stamp is the poll count: the 1 Hz pass over the cached map reconciles nothing): a new id
  adopts the clip clock `elapsed_s / rate` and drops the figure's stations and climb; the same id takes rate and anchor
  at once and snaps its local clock only when a NEW poll is more than 0.3 s off.
- **Every frame**: the clip clock runs in REAL seconds while `rate > 0` (frozen = the player stands, `SpeedScale 0`);
  the half `<kind>__<role>` plays at the phase (cycle wrapped, one-shot clamped a millisecond short of its end) and
  re-seeks only beyond 0.2 s of drift; a running bridge ends there and its travel is dropped; the root stands at
  `anchor + R_y(yaw) · pairRootAt(phase)` — at the place's first slot when the anchor names one, else the room's stand
  (`roomStandY`), else the ground — and turns to the anchor's yaw. A half the library lacks (or a rig without a player)
  falls back to the ordinary placement and the solo clip.
- **Pair entry** (Task 84): each new interaction id blends from the rendered position and yaw for 0.4 real seconds,
  with smoothstep weight toward the moving clip root and shortest yaw. Polls, clip reseeks and same-id half changes
  preserve that view clock; world freeze stops the clip but keeps the blend running. Furniture keeps its slot height.
  First-sighted figures are placed before the adoption pose is captured.
- **Invite/accept feedback**: the shared HUD sends `pairFacing` before HTTP, turning only the own avatar toward the
  rendered partner without reporting position. `asked` retains the turn (including an arrived B1 seat); HTTP failure
  or a `declined` response restores the previous facing. Steering or pair adoption releases the preview so a late
  answer cannot overwrite the newer facing.
- **The root path** of a half is its hips XZ (`extractRootPath`) — METRES as Godot imports the clip (the browser's
  FBXLoader keeps Mixamo centimetres and divides by 100); a still-standing half whose constant hips curve Godot dropped
  gets the one key of its node default.
- **Bind anchoring** (ruling P3-R14, the Figure constructor / `anchorFigureBind`, vector `figure_normalisation.json`):
  every model body is centred on its SKINNED bind box in XZ with its lowest point on the root (`FigureBind.Offset`);
  the bridges' travel base and the body's `groundY` carry it. Test3_mia's mesh had its origin in the middle: it stood
  0.85 m deep in the ground before.
- `--check pairs` (`Check/PairCheck.cs`, `fixtures/pairs/`, README there).

### Clip memory and figure cost (Task 35, ruling P3-R11)

Measured on the world copy (`--offline`, 14 model figures + 1 portrait, the dump's model rotation as in Task 28):

- **What a template holds.** Every character model is fitted once per tier (the template key is URL + set chain +
  height) with the whole library: ~110 clips, 5 800 tracks, 312 000–320 000 keys. Godot keeps a key as
  `TKey<Quaternion>` (32 B); inserted one by one, a track's vector grows by 1.5× and keeps the spare slots. Measured
  with `FigureManager.ProbeClipMemory` (one template re-fitted, the static memory its Animations give back): **41.4 B
  per key = 12.6 MiB per template** before Task 35.
- **One-call keys** (`KeyWriter` in `Figures/ClipLibrary.cs`): a retargeted track's keys are written with ONE
  `tracks/N/keys` set — exact vector size — whenever that stores exactly what the inserts would (every time a float,
  strictly ascending far above Godot's merge tolerance; else key by key). On the world copy every track qualified:
  **35.7 B per key = 10.9 MiB per template** (−14 %), the fit's interop calls drop from one per key to one per track.
  `--check pairs` Q9 retargets a whole template both ways and compares every key bit for bit.
- **Identical clips shared** (`FigureManager.ShareIdentical`): a retargeted clip carries a SHA-256 of everything
  written into it; a later template whose clip comes out bit-identical binds the earlier Animation instead of a copy.
  That happens for the same model at another height or set chain and for the fallback pool, NOT across the two tiers
  of one model (the server's low bake moves the rests by ~1e-6 and the fitted clips then differ by up to 2.5° on a
  bone: a near-match would change what plays). Root-motion clips are re-locked per template and never shared.
- **Retired models** (figures.ts `retireModels`/`freeRetired`): once a character's model changed (new URL) and no
  figure shows the old template, both tiers of the old model are freed on the 1 Hz tier tick (`--check figures`).
- **The loop flag is per figure** (Task 32's minor): Godot keeps `loop_mode` on the shared Animation, three on the
  per-figure action. The shared Animation keeps the listing's flag; a figure that needs the other one (a pair stored
  with another `loop`, a bridge — always one-shot like the browser's `bridge.setLoop(LoopOnce)`) plays its own
  bit-identical twin `loop/<clip>` (`Figure.PlayName`, `--check pairs` Q8).

The offline log's `figures memory:` line (and the bench log's `bench figures memory:`) states figures, templates, build
fit times min/median/max, keys planned / fitted / held, the estimate at `FigureManager.KeyBytes` = 36 B/key, the per-clip
fit times at build and on first use (wall, main thread, worker) with the longest main-thread turn and body swap, the
probe (debug engine only), Godot's static memory / objects / resources and the managed heap (with the probe: live after
a full collection). Every bench result carries `figures`, `figuresAnimated` and `clipMemMiB`;
`--bench-matrix=no-figures` measures what the figures cost per frame (all hidden and their tick stopped against the
interleaved baselines).

### Lazy clip fit (Task 35b, ruling P3-R15)

Task 35 measured the cost of fitting the WHOLE library per template: ~40 s of the boot (mostly the per-clip ground
measurement of Task 31), ~11 MiB per template (~300 MiB in a world where every character has its own model at both
tiers) and main-thread frames of 30–60 ms whenever a figure's other tier was fitted during play. Now
(`Figures/TemplateClips.cs`, `FigureManager.ClipFit`):

- **The build only PLANS** the library: per candidate clip whether it binds on the rig (the fit's own loop, counting
  only) and the action table — so a figure's kinds, bound tracks and keys, missing kinds are what they were. It FITS
  the movement poses (standing, walking, running, swimming, treading water, crawling) and, before a figure is shown on
  a template, what that figure plays (its activity, its current clip on a tier swap, its pair half).
- **Every other clip is fitted when a figure first needs it** (play / crossfade / bridge / pair) and then serves every
  figure of the template. Until it is in, the figure keeps what it plays; a bridge waiting for its clip holds the figure
  (pace 0, the height too), a pair half holds it on its point.
- **Off the main thread**: the retarget's key math (`ClipLibrary.Compute`, on keys read once at the clip import), the
  bridge relock and the ground measurement run on worker threads; the engine work (writing the Animation, sampling it,
  adding it to the library) runs on the main thread in turns of ≤ `FigureManager.ClipBudgetMs` (4 ms) per frame. The
  model's GLB is parsed on a worker too; the scene generation, bind box gathering, rest correction and plan each take
  their own frame. A template keeps only the ~1 000 vertices the ground measurement samples, not a copy of its mesh.
- **Identity**: `--check clips` compares every lazily fitted clip (the bridges fitted on their first play, the rest
  afterwards) with an eager fit of the same world — every key, the travel/turn/lift/ground extras and the skeleton pose
  at five times per clip bit for bit. Every other check runs `ClipFitMode.OnDemandSync` (the same plan, a needed clip
  fitted inside the call that asks for it) and gives the numbers of the eager fit.

On the world copy (`--offline`, same dump as Task 35): boot `figures` stage 44.6 s → 9.1 s; fit per template
2.3–5.6 s → 24–75 ms (plan + movement poses); a clip on first use ~13 ms wall, ≤ 4 ms per main-thread turn; after the
bench drive (28 templates) clip keys held 2.69 M ≈ 92 MiB → 0.17 M ≈ 6 MiB, fitted (= what a world with a distinct model
per character holds) 8.83 M ≈ 300 MiB → 0.41 M ≈ 14 MiB; Godot's static memory 2728 → 2527 MiB; no headless frame
over 15 ms of process time in the drive (before: ~490 samples).

### § B5a verify (Task 15)

After each mount `Core/Scene/SceneVerifier.cs` diffs every mounted plate and wall (its box from the emitted
vertices, through the location group's transform, back into the tile frame) and every placement (world box +
outer position, with its storey-0 lift; `surface_scale`/`surface_box` where a spec bakes a surface) against the
payload through the vector-checked cores of `SceneVerify`; a spec that placed nothing is a `geladen` row (the
browser's field name). The log line is the browser's, in English: `[verify] <loc>: N numbers checked, no deviation
> 0.01 m (models P/T)`, or the deviation count plus a table. Differences to `window.__sceneVerify`: one report per
location (the browser's detail report overwrites its shell report), degenerate pieces are not built here and
therefore not measured; every storey is (Task 16).

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
the dump) and prints `offline world …`, `offline scatter …` (with a `digest=` of every placed instance — two runs
that placed the same scatter print the same digest), `offline figures …`, `offline veil[…]`
and the shader lines, then quits; with `--verify` it also prints every location's verify table. The dump tool
refuses every non-loopback connection and stubs the image service (a copy's config never makes it probe a gateway).

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
- **Off the main thread** (Task 26): a moved window, a re-drape, a measured
  clearance or a new terrain asks for ONE rebuild (`Coalescer`); the sampling,
  the ground heights and the instance buffers are made on a worker from frozen
  inputs (`ScatterField.SampleWindow`, `UndergrowthField.SampleCells`, a
  `WorldHeight.Snapshot`), only the MultiMesh nodes on the main thread; the old
  props draw until the new ones stand. The boot's first window runs the same
  functions inline. The summary line carries `worker_ms= mount_ms= ug_worker_ms=
  ug_mount_ms= discarded=` (last/largest). On the real world: worker 85–145 ms,
  mount ≤ 3 ms per 64 m step (was 100–160 ms of one frame).

Not drawn (this favours Godot): the impostor billboards beyond 120 m
(`impostors.ts`), the `along`/`edge`/`center` rows (counted, logged as
`skipped`), the camera corridor fade. Different but cost-neutral: the
`aligned` yaw uses the angle without the surface axis; the undergrowth's layer
mask gate is the geometric "topmost painted area" test.

## Audio (Task 59 / E8-T2)

Task 59 (E8-T2) owns native audio. `Music`, `Ambient` and `Voice` send to
`Master`; all are non-positional linear-amplitude buses with a 50-ms volume
ramp. `av3d.audio.v1` is read from the per-server HUD storage mirror before
HUD handoff, including with `--no-hud`. Defaults match the browser:
master .8, music .5, ambient .6, voices 1, music/ambient enabled, TTS auto.

`App/Audio/AudioOut.PlayPlaylist(PlaylistBus.Music|Ambient, urls,
crossfadeS: 3, seed: null)` is the Task 60 driver boundary. An identical URL
list keeps playing; an empty list stops. Lists shuffle with the browser's
seeded PRNG, preload six seconds before the seam, and crossfade through eight
linear sin/cos segments. Fade is capped at one third of the decoded duration;
the seam is begin + duration − fade. Playlist changes fade old sources out
linearly. Godot starts at the first frame at/after the seam, so timing has
frame jitter compared with Web Audio's scheduled clock.

All formats are detected by signature and fetched through the current
session's `IWorldSource.GetBytesAsync`, including `/tts/tmp/` URLs. Runtime
MP3/Ogg/WAV decoding occurs on the Godot thread. Playlist streams cache per
URL; speech streams release at end/stop and are never cached. Broken files
are skipped with one application log line per failed attempt; an all-broken
round becomes silence.

The Graphics tab shows a Local cache section when the host publishes
`clientCache {bytes, limitBytes, entries}` (the browser publishes null).
Clear cache writes `pending_clear` under `--cache-dir` (default
`user://cache`), shows zero immediately and leaves all active files usable.
The next process start removes the cache's version trees before any worker
loads. `--clear-cache` performs the same cold start without the HUD; scene
and character reloads do not consume the flag. If clearing fails, that process
runs without disk caching, logs the failure and retains the flag for a later
restart. The limit is 4 GiB.

Bridge v4 `speak(url)` waits for a correlated `speech-done` acknowledgement
on playback end, failure, stop or overflow (Task 65 / P3-R38). The HUD renders
and plays one line at a time, as in the browser. The native cap of three
waiting lines remains as a safety net. `stopSpeech`
stops now and clears the queue; a late download cannot restart it. HUD page
reload also stops speech. `setVolumes` applies only changed volume targets;
`applyAudioPrefs` updates music/ambient switches and raises `PrefsChanged`
for Task 60. TTS selection, rendering and its switch remain in CEF.

`--headless -- --check=audio` (also `--check audio`, included in full
`--check`) loads `fixtures/audio/` and checks codec durations, real bus and
player gains on a fake clock, capped fades, seams, stop ramps, queue overflow,
handler wiring and broken-file skipping. It does not assert audible sound.
Task 60 supplies the live day/night/terrain soundtrack driver; listening
acceptance against real music and TTS remains Task 61.

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
- **Bridge**: protocol v4 of `client3d/src/hud/bridge.ts` (prop-action preparation and
  correlated mutation invalidation, plus speech completion), one JSON string per
  message over gdCEF's JS binding (`window.godotMethods.hud_bridge(json)` →
  `HudOverlay.hud_bridge`, Godot's `js_emit("hud_bridge", json)` →
  `window.godotEvents`); the page picks `gdcefTransport` by `?bridge=gdcef`.
  Godot is the scene side: it sends `boot`, the game state the chat, plaque
  and menu read (`clock`, `connection`, `mode: overview`, `selected`,
  `openView`), and `ui` actions; it receives the HUD's ui state
  (`hitRects`, `typing`, `overlayOpen`, `menuOpen`) and game actions
  (`zoomTo`, `clearSelection`, `closeOpenView`, `setVolumes`, `applyAudioPrefs`, `speak`, `stopSpeech`,
  `backToTitle`, `setShowAll` (admin only), `applyScatterPrefs`, `markResume`
  (acknowledged; the page reload after it rebuilds the world, see "Taking over another character"); the others
  are logged once, and a player-triggered one answers with a toast "Not available in the native client yet").
  The page's `localStorage` writes go over a second binding method, `hud_storage` (see "HUD settings across
  starts").
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
  cookie on disk; the HUD settings are kept by Godot instead), without a DevTools port; its log (incl. the page's console
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
| `Core/` | the Godot-free library `AnimaNative.Core` (same namespaces `AnimaNative.*`, same subfolders): `Api/AnimaApi.cs` (HttpClient + cookie session, the server getters, `IWorldSource`), `World/` (payloads, `WorldHeight` + bench `Anchor`, `LocationView`), `Ground/` (`LayerCut`, `TerrainNormal`, `WaterTileField`), `Water/` (`WaterShade` + the ripple twin, `WaterRaster`, `WaterProfile`, `Waterfalls`, `WaterGates`, `PropWater`), `Terrain/` (`TerrainLod`, `TerrainField`, `TerrainLodGlsl`, `TerrainShaderTwin`, `HeightTiles`), `Scatter/` (terrain payload, sampler, LOD and undergrowth maths), `Hud/HudProtocol.cs`, `Ui/LauncherSettings.cs` (the launcher file's rules: parse, serialise, merge with the flags, server-address normalising), `Ui/SessionFlow.cs` (login / character switch / back to title / lost session as one decision), `Ui/HudStorage.cs` (the kept HUD settings: file model, 256 KB cap, the handoff's seed script), `Bench/` (path + statistics, the embedded `camera_path_v1.json`), `Figures/` (CharacterRows + the placement orchestration, NpcPlacement, FigureGround, RoomSpots, FigureStands, the clip rules), `Gltf/` (Meshopt decoder + its P/Invoke), `Sync/` (Task 10: `PollScheduler` = pollCore.ts, `SyncStream` = syncHub.ts + `HttpEventSource`/`SseParser` for `/events/sync`, `BootTracker` + `BootRetry` = game/boot.ts + `retryBoot`, `LocationsCache`/`LocationsSync` = the ETag'd `/world/locations?view=3d`, `ConnectionState`, the frame-pumped `TimerQueue`) |
| `tests/` | xUnit project on Core (`dotnet test tests`) |
| `test.sh` | `dotnet test` + build + headless `--check` |
| `World/` | the Godot side of the world (payloads, height + anchor and the view rules are in `Core/World/`): the CDLOD terrain node (`TerrainLodNode.cs`), the waterfalls / underwater ghost / prop water sheets (`WaterfallLayer.cs`, `SubmergedGhost.cs`, `PropWaterSheets.cs`, `WorldBuilder.Water.cs`), `place()`, recipe meshes + materials, model cache + placements (`SceneModels.cs`), surface library, shader safety, the builder |
| `tools/dump_payloads.py` | Task S3c: dumps the client's HTTP answers from a COPY of a world for `--offline` |
| `Gltf/` | runtime GLB import (the Meshopt decode is in `Core/Gltf/`) |
| `Figures/` | world-map characters: figures (fed by Main's poll, placed by the room ladder once a second), portrait sprite, fallback pool, clip library (import, pick, retarget), rest-pose correction |
| `Ui/` | login screen (server, user, password), `LauncherStore` (`user://launcher.json`), `HudStorageStore` (`user://hud_storage.json`), the overview camera, the label overlay (`LabelOverlay.cs`: projection, order, the label CSS in `LabelStyle`), the performance probe (`PerfProbe.cs`) |
| `Hud/` | gdCEF wrapper (`GdCef.cs`, the one class that calls the extension), protocol v4 scene side (`Core/Hud/HudProtocol.cs`), input routing + figure picking (`HudRouting.cs`), the overlay node (`HudOverlay.cs`) |
| `link_cef.sh`, `cef_artifacts/` | the one-time gdCEF link; the linked folder is gitignored |
| `Ground/` | Task S3b: the layer-cut port + payload (`Core/Ground/LayerCut.cs`, incl. `wantedTiles` and the natural-ground maths), the shading-normal twin (`Core/Ground/TerrainNormal.cs`), the ground shader (`GroundShader.cs`, + its water variant), the loader that builds slices/masks/material (`GroundSurfaces.cs`); the water numbers are `Core/Water/` (the tile field `Core/Ground/WaterTileField.cs`), the water's fields ride on the terrain's near lattice (`Core/Terrain/TerrainField.cs`) |
| `Scatter/` | (payload, sampler and LOD/undergrowth maths are in `Core/Scatter/`) prop GLB → grounded mesh, the two MultiMesh layers, the sway shaders, the cadence driver |
| `Bench/` | the bench driver and its output (camera path `loadPath`/`samplePath` and statistics `summarize`/`percentile` are in `Core/Bench/`) |
| `Check/` | `--check`: fixture source and expectations, the S3c world (`S3cCheck.cs`: view rules, models, world props, water, shaders), § B5a (`VerifyCheck.cs`), the crossfade and occlusion (`PickCheck.cs` G), bench maths, scatter (`ScatterCheck.cs`, incl. the Task 26 worker build), the exploration veil (`VeilCheck.cs`), ground surfaces (`GroundCheck.cs`: requests, window bytes and probes vs. the TS functions, slices, shader parameters and its front-end compile, AO and normal by hand, the fallbacks), HUD (`HudCheck.cs`: rects incl. the CSS/window scale, routing table, message validation, outgoing strings, picking, cookie script, name lists vs. the TS sources, every gdCEF method this client calls when the extension is linked); `--check-bench [--scatter]`: offline bench smoke |
| `fixtures/` | offline payloads (incl. `terrain.json`, the scatter reference vectors, the cut-down layer bake + surface library + the ground reference values) + a real Meshopt GLB pair + character/clip answers (hand-derived numbers in its README) |
| `third_party/meshoptimizer/` | meshoptimizer v1.3 sources (MIT, `src/*.cpp`, `meshoptimizer.h`, LICENSE) |


### Soundtrack driver (Task 60 / E8-T3)

The mounted world starts one session-authenticated `GET /assets/audio` through
`IWorldSource.GetAudioManifestAsync`. Each scene session fetches once, including
a failed request; a world reload (including a character switch) starts a fresh
fetch. Errors or malformed data become an empty manifest, with no retries. An
audio-only HTTP 401 also stays silent without expiring the game session.

Selection runs every second and immediately on manifest arrival, GAME-clock
updates and changes to `musicOn`/`ambientOn`. Music becomes night above 0.8 and
day below 0.2; values on or between those thresholds preserve the previous
choice. Music uses a 4-second list-change fade, ambience 3 seconds. Missing
buckets stay silent. Task 59 still owns shuffle, track seams and stop ramps.

Ambience reads the smallest mounted footprint under the overview camera target,
or under the rendered avatar in embodied mode. Missing positions/footprints
mean silence. Terrain is trimmed and lowercased; manifest keys prefer an exact
match, then a case-insensitive match. The first nonempty terrain applies
immediately. Later changes (including silence and returns from silence) must
hold for 5000 ms. Switches apply immediately from stored/live preferences;
terrain tracking continues while ambience is disabled. Volume changes alone
do not re-tick the driver.

`--check audio`, `--check=audio` and the full `--check` include the fixture-world
driver cases: day/night hysteresis, terrain hold, rendered-avatar selection,
missing matching playlists, one-fetch lifetime and the 4-second music stop.
Headless checks verify state and routing; real device listening is Task 61.
