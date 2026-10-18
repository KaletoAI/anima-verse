# LLM-Blender models — parametric building hulls

## Building hull

Game-Admin → World → location → building models offers **Building hull** when Blender is usable. Choose a style, optionally roll the
seed and edit overrides, then **Build hull**. **Suggest from description (LLM)**
fills the same fields; it does not start a build. No drawn outline means a
readable 409; Blender unavailable means 503. Both details appear in a toast.

The pipeline is `scene_recipe` facts → walls/roofs/ornaments → Blender.
`hull_facts` takes the outline, openings and level heights from the recipe's
geometry helpers. Python builds the vertices, faces, UVs and material groups;
Blender receives finished meshes, assigns textures and exports GLB. The LLM
supplies clamped JSON, never executable code or a replacement floor plan.

Five shipped styles live in `shared/building_styles/`: `fachwerk`, `steinhaus`,
`holzhuette`, `burg`, `modern` (Modern). A style document names material kinds (`wall`,
`wall_ground`, `plinth`, `roof`, `trim`, `door`, `chimney`, `facade_module`), glass/interior
palette, wall thickness and plinth height, corner/frame treatments, timber
framing, roof forms and pitch/overhang ranges, towers, chimneys and ornament
switches/densities. `hull_styles.validate_style` clamps the schema. Texture
kinds resolve through the surface library, with fallback colours when missing.
**Edit hull style** opens its JSON document. **Save as world override** uses
`PUT /world/hull-styles/{id}` to replace that whole entry in the world DB;
**Reset to shipped** deletes the override. Shipped files stay intact.

A build description is `{style, seed, overrides}`. Overrides support
`roof_form` (`gable`, `hip`, `shed`, `flat`), `pitch_deg` (5–60),
`ornament_density` (0–1), `storeys_total` (0–40), and optional hex `tint`. Empty pitch/form means the
style default; **none** removes tint. The same facts, validated style and
seed-bearing description produce the same job bytes. Random variation uses
`hull_mesh.rng(seed, tag)`; changing the seed changes the ornament choices.

**Storeys total** adds facade storeys above the plan (0 uses the plan height).
Storeys without rooms, including gaps, get blind windows and are not enterable.
Modern can use the `facade_module` texture for these storeys; missing textures
fall back to blind windows. For its surface texture prompt, use **front view**
instead of **top-down**.

Generation stores **full** and **low** tiers and immediately records both in
`selection.json`. Low retains the wall/opening geometry and roof but omits
expensive ornaments. The resulting model becomes active through the ordinary
building gallery and pending poll. There is no automatic rebuilding: an
outline, opening or height change marks the active hull stale, while moving
furniture does not. The old model stays active. **Rebuild** submits its saved
description, including seed; **Build hull** submits the edited fields.

Per-building material overrides select surface-texture kinds for roof, trim and
plinth; an empty selection uses the style default. Roof tint overrides the main
tint for the roof. Storey wall textures come from the floor plan's Wall / Shell
inspector. After changing textures, build the hull again.

The display contract is `plan_hull: true` with `display: "shell"`: entering
keeps the hull visible and cuts the interior along the recipe outlines, exposing
the matching recipe walls. It is not roof-faded and does not participate in
corridor occlusion fade. See the **Grundriss-Hülle (`plan_hull`)** addendum in
[schnittstellen-3d.md](schnittstellen-3d.md) for cutout limits, padding and the
embodied-mode rule.

## 6. Prerequisites and settings

Blender runs **locally**, not on a generation backend. Everything is configured
under `/admin/settings → Image/Video Generation → Blender refinement (3D)`
(config path prefix `image_generation.`):

| Key | Default | Meaning |
|---|---|---|
| `blender_enabled` | `true` | Master switch for every Blender job |
| `blender_executable` | `` | Explicit path. Empty = discovery: the newest binary in [5.2, 6.0) among `which blender`, `/opt/blender*/`, `/usr/local/blender*/`, `~/tools/blender*/` |
| `blender_timeout_s` | `120` | Per job |
| `blender_keep_original` | `true` | Keep the pre-refinement file |
| `blender_auto_retexture` | `true` | Re-encode textures after a generation |
| `blender_jpeg_quality` | `85` | for that re-encode |
| `blender_max_texture_size` | `0` | `0` = do not downscale |
| `blender_auto_normalize` | `true` | Real height, feet on the ground, origin |
| `blender_auto_bake_vc` | `true` | Vertex-colour meshes get UVs + a texture |
| `blender_bake_vc_target_tris` | `40000` | Triangle budget for that bake |
| `blender_auto_lod` | `true` | Build the reduced distance stage |
| `blender_lod_ratio_character` / `_prop` / `_room` / `_building` | `0.4` / `0.25` / `0.5` / `0.5` | Triangle ratio of that stage |

The hull path itself reads three of them: `blender_enabled`,
`blender_executable` and `blender_timeout_s`. The one gate every caller asks is
`app/blender/runner.is_available()` (enabled AND an executable AND a version),
surfaced to the UI as `model3d.blender.usable`.

**The runner contract.** `runner.run()` invokes
`blender --background --factory-startup --python-exit-code 1 --python <script> --
<job>/args.json` — arguments, never stdin. `args.json` is
`{inputs: {slot: path}, params: {}, out_dir, result}`; the script writes its
answer to the `result` file as `{ok, error, data, outputs}` (`_common.py` does
both halves), and the runner moves the declared outputs into `out_dir` and
returns `{ok, error, data, outputs, seconds}`.

## 7. Other Blender jobs

Building hulls accept LLM design suggestions; they are not the only Blender jobs.
`app/blender/scripts/` holds the rest, each one the same "the server thinks,
Blender builds" shape: geometry repair and measurement (`normalize.py`,
`measure.py`, `diagnose.py`), texture work (`bake_vc.py`, `retexture.py`,
`picture_areas.py`), distance stages (`lod.py`), the walkable-surface grid
(`heightgrid.py`), the clip pipeline (`fbx_clip.py`, `cmu_clip.py`,
`clip_orient.py`, `clip_roll.py`, `rig_export.py`, `_cmu.py`). `app/blender/refine.py` is the façade for the
character/prop refinement; it has no roof path.

The clip pipeline imports FBX with Blender's C++ ufbx importer,
`bpy.ops.wm.fbx_import` (Blender 5.2 or newer). A take with one animated layer
becomes one action with one slot per animated object. Multiple animated
layers produce multiple actions per take and are unsupported; the take-count
check rejects a mismatch. Selecting a take restores imported static object
transforms and pose-bone bases before binding the action and the object's
slot, so missing tracks cannot retain a previous take's transforms. A temporary
dependency-graph callback clears actions before the importer's first evaluation
to capture those static values. The shared mesh import in `_common.import_model`
continues to use the legacy Python importer: the tested mesh fixtures differ
in image datablocks and material extensions with the C++ importer, and
normalized mesh normals differ by up to 0.09.

`scripts/smoke_fbx_importer_parity.py` compares clips with the pinned revision
`a98f9ed543e0493e55790104ad2533d90e0bb2fd`. The migration is accepted with
rest-coordinate tolerance `1e-3` cm and pose-matrix component tolerance
`1e-3` (translation in cm, rotation part unitless, about 0.057 degrees).
Float32 spacing at 100–200 cm is 7.6e-6–1.5e-5 cm; bare imports already
differ by about 1.2e-4, and a few chained matrix products accumulate rounding.
The bounds cover that noise while rejecting centimetre or several-degree
behaviour changes; the synthetic two-take check catches a wrong mapping
with a 30 cm error. A second synthetic case animates an armature and its parent
in A, then only the armature in B; B after A must equal B alone within `1e-3`,
with the parent and an omitted finger at their hand-derived static transforms.
Bone sets, frame ranges, and fps must match exactly.

### Quadruped rig (`quadruped_rig`)

The `local_quadruped_rig` backend runs locally in the `rig_creature` chain
before UniRig (the seeded order; existing non-empty routing is preserved).
A “not a quadruped” rejection falls through to the next backend without cooldown.
`app/imagegen/backends/local_quadruped_rig.py` sends the unrigged mesh and
basecolor PNG to `app/blender/scripts/quadruped_rig.py`, which fits the
Mesh2Motion fox skeleton to the mesh's body and leg landmarks. Distance skin
weights are smoothed in weld space, capped to **four influences** per vertex,
then re-smoothed only within those retained influences.

All takes in `shared/models/quadruped/clips.json` are baked at 24 fps with paw
IK and source contact masks; run keeps its flight phase. After IK, a per-frame
ground rule lifts the root only when needed, ignoring tail vertices and the
paws currently controlled by contact IK. Tail clearance is handled separately,
with a lift capped at **30°**. Export is **FBX + basecolor PNG** (`generic` rig).
`app/core/model3d.py` stores metrics and `clips: {take: {loop}}` in model meta;
the admin viewer and 3D client use those loop flags (`applyEmbeddedClipLoops`
in `client3d/src/scene/figures.ts`).

The catalog maps take names to `src` (only `fox`), `action`, `loop` and an
optional `tail` override mapping the selected mode to the effective mode.
Unknown declaration keys are errors. The five takes are `idle` (`Idle`),
`walk` (`Walk`), `run` (`Run`), `sit` and `sit-ground` (both `Sit`). The first
three loop; both sitting takes hold their last frame and use
`"tail": {"calm": "still"}`. All catalog takes are baked on every rig.

The animal template's `tail_motion` selects `full` (source motion), `calm`
(yaw amplitude × 0.2, inclination retained), or `still` (rest rotation).
Empty means the backend's `tail_mode_default`, whose default is `calm`.
Changing this field requires **Re-rig from mesh**; it is baked into the takes.

Assets live in `shared/models/quadruped/`: `fox-animations.glb` supplies the
reference mesh, skeleton and actions, `clips.json` declares the takes, and
`LICENSE.txt` credits **Mesh2Motion (mesh2motion.org), CC0 1.0**.
Limits: no lying or crawling takes; one skeleton serves all quadrupeds, and
multiview mesh quality decides the resulting stance.

Measured fixtures (stretch = p99.9 edge stretch factor; ground = maximum root
lift as % of height; contact = maximum contact error as % of height).
A dash means no value is listed here.

| Animal / tail mode | Take | Stretch | Ground (%) | Contact (%) |
|---|---|---|---|---|
| Cat 7 / calm | idle | 2.19 | — | — |
| Cat 7 / calm | walk | 4.15 | 1.2 | — |
| Cat 7 / calm | run | 7.26 | 4.5 | — |
| Cat 7 / calm | sit | 4.10 | 3.8 | 3.75 |
| Cat 21 | walk | 6.24 | — | — |
| Cat 21 | run | 10.49 | — | — |
| Cat 21 | sit | 5.05 | 9.4 | 11.5 |
| Dog 21 / full | walk | 7.29 | — | — |
| Dog 21 / full | run | 12.1 | — | — |
| Dog 21 / full | sit | 7.6 | 1.6 | — |

Known open points: hind hocks rise high during run; Cat 21 floats about 9% of
its height when sitting. Verification: `scripts/smoke_quadruped_fit.py`,
`scripts/smoke_quadruped_clips.py` (also `--numpy-only`) and
`client3d/scripts/smoke_quadruped_takes.mjs`.

## Hull boundaries

The hull follows authored floor plan facts; the LLM cannot replace the outline.
Geometry is deterministic for the same facts, style, seed and description.
Changes to the outline, openings or heights require an explicit rebuild.

## Lossless GLB delivery copies

`image_generation.blender_meshopt_delivery` is an instance setting in the
Blender group, enabled by default. On the first inline GLB request,
`app/core/glb_delivery.py` serves the stored original and schedules one build
on a dedicated single-worker thread. Blender must be usable. The job
`app/blender/scripts/meshopt.py` rewrites GLB buffers directly using Blender's
bundled meshopt bridge; it never imports or exports a scene. Stored files,
Python model readers, downloads and exports retain their original bytes. The
character Download link explicitly requests `model3d/file?download=true`,
which uses attachment disposition and bypasses the delivery cache.

Delivery copies require `EXT_meshopt_compression`. Buffer 0 holds aligned
compressed streams and raw views; buffer 1 is a URI-less fallback placeholder.
Geometry streams carry no filter (the spec default `NONE`, lossless); the key is
omitted because Blender's own glTF importer rejects an explicit `NONE`. Images, animation data,
inverse bind matrices, sparse and mixed-use storage remain raw. Every encoded
view is decoded and compared byte-for-byte before an output is accepted.
The triangle codec can cyclically rotate triangle corners: when that changes
index bytes, the job uses `INDICES` instead of `TRIANGLES` to retain the exact
index array. No vertex, triangle, accessor, mesh or node indices are reordered.
Unknown required extensions, existing compression, multiple source buffers,
no eligible geometry, or savings below 5 percent keep the source unchanged.

Copies live at `<storage>/.cache/meshopt/<source-sha256>.glb`. Hashes are
memoized by resolved source path, inode, mtime_ns, ctime_ns and size, and a
file that changes while it is hashed is not memoized. Successful deterministic
skips create a `.skip` marker; timeouts and failures remain retryable. Builds
verify their input snapshot against the requested hash and publish atomically.
Cache requests touch mtime, but the content hash provides a stable HTTP ETag;
the response filename remains the original name. A daily periodic sub-job
removes copies and markers unused for more than 30 system days, under the
normal world-pause gate.

Both clients configure every GLTFLoader through their app's `gltfLoader.ts`
factory with Three.js's MeshoptDecoder. Admin previews keep lazy loading and
`parser.associations` still maps to unchanged glTF indices. Clients do not
parse GLB bufferViews themselves.

Verification (temporary storage only):

```bash
ALSOFT_DRIVERS=null .venv/bin/python scripts/smoke_blender_meshopt.py
node scripts/smoke_glb_meshopt_three.mjs
.venv/bin/python scripts/smoke_glb_delivery.py
```

The first smoke derives its synthetic geometry layouts by hand and checks
source-byte preservation, raw views, skip gates and the rigged puppet. The
second uses the real Three.js decoder to compare loaded attributes, indices,
ordered rig data and parser associations. The third checks deduplication,
source changes, deterministic skips, retryable failures, HTTP behavior and
30-day retention with a fake runner.

## Stored roof display contract

Stored roof models from before 2026-10 retain `roof_only: true`. These GLBs
use the ordinary gallery placement (width and offsets) and may serve both full
and low tiers. They are lids over the recipe walls: renderers keep the recipe
shell visible underneath them and preserve roof fading when entering.
`scene_recipe`, `client3d` and `packages/scene-render` continue to support this
flag. New parametric buildings use the hull pipeline and `plan_hull: true`.

## Hull interfaces and checks

`POST /world/locations/{id}/hull/propose` returns a validated editable proposal;
`POST /world/locations/{id}/hull/generate` builds the submitted description.
`GET /world/locations/{id}/hull` reports styles and stale state.
`hull_model` prepares the job; `app/blender/scripts/hull_build.py` exports it,
and `location_model3d.save_hull_model` stores the result. Shared colour, JSON,
bounding-box and timeout helpers live in `app/core/hull_util.py`.

Pure verification: `scripts/smoke_hull_styles.py`, `smoke_hull_facts.py` and
`smoke_hull_geometry.py`. Blender and route integration are covered by
`smoke_hull_model.py` and `smoke_hull_routes.py`.
