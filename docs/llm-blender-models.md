# LLM-Blender models — parametric assets instead of image-to-3D

**Status:** v1 shipped 2026-08-20 — **the roof, and only the roof.**
Programme: `development_instructions/done/plan-assets-im-szenenkontext.md`, Etappe 4b.
Numbers: `./.venv/bin/python scripts/smoke_roof_model.py` — every expectation is
hand-derived in its docstring; its last section needs a Blender binary and is
skipped without one.

## Why

The far view of a location without a building model is the scene recipe's own
primitives — level plates and walls, standing outside instead of only inside
(`client3d/src/scene/sceneRecipe.ts buildFarShell`, 2026-08-20). That shell is
**roofless and says so**: the payload has no roof primitive family, and an
invented lid would be the struck procedural hut one storey higher.

But the roof is the one part of a simple building that needs no invention at
all. The outline is drawn, the storey height is a dial, so the eaves plane is
**known**. What is left is a taste question — form, pitch, overhang, material —
and that is exactly the kind of question an LLM can answer.

This is the WorldClaw approach (an agent authoring Blender) applied to **assets**
instead of terrain, with one deliberate change: the paper names generated
**code** as its main failure source, so the LLM here emits a **declarative build
description**, never Python. Nothing is `exec`'d, nothing can crash the builder,
and an answer that makes no sense becomes a plain gable.

Consequence for the world builder: for a simple building the image-to-3D path is
**not required** — recipe shell + generated roof is a complete building, which is
why the map stubs carry no building image prompts. It is not retired, though:
`shared/world_dev_schemas/location.md` still asks for `image_prompt_building`,
and `POST /world/locations/{id}/exterior/render` deliberately feeds the img2mesh
path from a rendered exterior (see „Other Blender jobs" below).

## The pipeline

```
build_roof_description(location_id)  what is KNOWN: outline, storeys, eaves
        ↓
propose_roof(location_id)            ONE LLM call (task `roof_design`)
        ↓                            → validate_description(): clamps, defaults
   [ the admin sees and edits every number — propose, THEN build ]
        ↓
build_job(location_id, description)  pure geometry: vertices, faces, materials
        ↓                          + the placement the sidecar needs
roof_build.py (Blender, dumb)      builds, paints, exports ONE unrigged GLB
        ↓
save_roof_model()                  the location's building model, roof_only
        ↓
GET /play/locations/{id}/scene     models[] spec with `roof_only: true`
        ↓
client                             recipe shell STAYS, roof sits on top
```

**The server thinks, Blender builds** — the same division of labour every
Blender job here follows (`app/core/*.py` decides, `app/blender/scripts/*.py`
executes).
The script receives finished vertex lists; it computes no geometry, so every
number in the GLB traces back to a function in `app/core/roof_model.py` and the
smoke can check the mesh **without a Blender binary**.

## 1. The build description — schema v1 (roof only)

What the LLM emits, and the only thing it may emit:

```json
{
  "form": "gable",          // gable | hip | shed | flat
  "pitch_deg": 35,          // 5 … 60, the SLOPE of the surface
  "overhang_m": 0.4,        // 0 … 1, how far the eaves pass the wall
  "ridge_axis": "auto",     // auto | x | z
  "material": {"tone": "#6b5f57", "kind": "shingle"},   // shingle|thatch|metal|tile
  "gable_tone": "#5a4f47"   // optional, gable only: the wall triangle
}
```

`gable_tone` is schema-only today: the template does not ask for it and the panel
has no field, so the second material path is reachable through a hand-written API
body alone.

`validate_description()` **never raises and never rejects**. An unknown form
becomes `gable`, a pitch outside the range is clamped to it, `#abc` is expanded
to `#aabbcc`, an unreadable colour becomes the kind's default tone, and a flat
roof's pitch is forced to 0 (a flat roof has no pitch, and carrying one would
only invite a renderer to use it). The worst a broken answer can do is produce
an ordinary gable — which is a roof, and a roof is what was asked for.

`material.kind` is a word for the LOOK, not a texture: v1 paints one principled
material with the tone and the roughness the kind implies (shingle 0.80, thatch
0.95, metal 0.35, tile 0.60). The tone is named in sRGB and handed to Blender in
**linear** light (`tone_to_linear`) — a raw hand-over comes out washed out.

**The LLM stage is optional by construction.** `roof_design` is a normal task in
`llm_tasks.TASK_TYPES` and is routed in `/admin/settings → LLM Routing` like any
other. Unrouted, unreachable or unparsable, `propose_roof` returns the clamped
DEFAULT description and flags it `llm: false` — the panel says which of the two
it is showing. The feature works without an LLM; the LLM makes it interesting.

## 2. The server module — `app/core/roof_model.py`

### Footprint precedence (state, never guess)

| # | Source | Why |
|---|---|---|
| 1 | `map3d.outline` | the DRAWN building contour — the author said where the building is |
| 2 | `map3d.boundary` | the drawn plot boundary — coarser, but authored |
| 3 | union of the room shells (`room_recipe.compose_recipe`) | derived, and marked as such |

**Known gap:** `scene_recipe._plates` no longer reads the bare `map3d.outline`.
Since the per-storey outlines (2026-09-06) it resolves `map3d.level_outlines` for
the level it draws, while `roof_model.footprint()` still reads `map3d.outline`
only. A building that narrows upward therefore gets a roof sized to its ground
floor. The third exists because a
location may have rooms and neither of the drawn shapes; it is composed through
`room_recipe` rather than read off `layout`, because that is where a room's
outline is decided. No source at all → `ok: false`, and the route answers 409
with what to draw. The result names its source, and the UI shows it.

### Rectangularization, stated out loud

V1 roofs the **minimum-area rectangle** (convex hull + rotating calipers) of the
footprint, not the polygon itself. An L-shaped or curved contour therefore gets
the rectangle that hugs it. A real roof over a concave outline needs a
straight-skeleton solver; that is a stage of its own. A rectangle is honest,
deterministic and right for the huts and houses this exists for.

### Eaves height

```
storeys        = max(room level ≥ 0) + 1        (a basement raises nothing)
eaves height   = storeys × storey_height_m      2 × 3.00 m = 6.00 m
roof base plane = eaves − EAVES_SINK_M (0.10)   = 5.90 m
```

Why the sink: the contour walls of the top storey really end at
`(S−1)·storey + 0.08 + max(0.6, storey − 0.15)` = **5.93 m** for the example —
0.07 m below the nominal eaves. Sitting the roof on 6.00 m would leave a 7 cm
slit the far view looks straight through; 5.90 m overlaps the wall head by
0.03 m. The offset is constant for every storey height ≥ 0.75 m.

### The geometry (all four forms)

y is measured from the **base plane**, which the roof surface passes through at
the **wall line**. The pitch is the slope of that surface, so the overhang does
not raise the ridge — it extends the same plane outward and **downward**.

```
slope   = tan(pitch)
ridge   = (span/2) · slope           over the WALL line
eaves   = −overhang · slope          the outer edge hangs below the wall head
```

| form | body | vertices | faces |
|---|---|---|---|
| `gable` | 4 eaves corners + a ridge line, closed underneath | 6 | 5 |
| `hip` | ridge shortened by the hip run `(length − span)/2` each side | 6 (5 over a square: a pyramid) | 5 |
| `shed` | one rising plane, closed down to the low level | 6 | 5 |
| `flat` | a slab of 0.12 m on the wall head | 8 | 6 |

`ridge_axis: auto` runs the ridge along the **long** side (what a builder does),
so the slopes face the two long walls. `x`/`z` force the world axis: whichever
rectangle axis points more that way becomes the ridge.

Every body is **closed** — a roof has an underside, and a one-sided plane is
invisible from below with the renderers' default face culling.

### The metric law (why nothing has to be calibrated)

The mesh is built in the location's own scene frame, so the sidecar can state
the placement instead of leaving it to a dial:

```
width_m  = max(AABB.x, AABB.z)       → scale = width_m / measured = exactly 1
offset_x = AABB centre x             → place() re-centres it on its own centre
offset_z = AABB centre z
offset_y = roof base + AABB min y − LEVEL_PLATE_TOP
```

The standard § B2 building placement then puts the mesh exactly on the vertices
it was built from. For the 10 × 8 m example at 30°/0.40 m:
`width_m 10.80`, `offset 5.00 / 4.00`, `offset_y 5.5891`, ridge at **8.2094 m**.
(Every vertex is rounded to four decimals server-side, so 5.5891 is the stored
value — the un-rounded ideal is 5.58906.)

### The frame, converted once

`(x, y, z)_scene → (x, −z, y)_blender` in `build_job`. The glTF exporter's own conversion
(`Blender (x, y, z) → glTF (x, z, −y)`) brings it back, so the stored GLB speaks
the **scene frame** like every other building model. The smoke checks the job's
own vertex list against `roof_geometry()`, and — with a Blender binary — the
script's reported counts and bbox against the same numbers. Never a screenshot.

## 3. The Blender script — `app/blender/scripts/roof_build.py`

Consumes `{mesh: {vertices, faces, face_material}, materials, export}`, builds
the mesh, assigns one material index per face, shades flat (a smoothed ridge
reads as a dent), exports ONE GLB, and reports back what it built — vertex,
face, triangle and material counts, the GLB's `bytes`, plus the bbox in the job's
own frame. That report is the § B5a verification: numbers against numbers. The
script also runs Blender's own `mesh.validate()` before exporting.

Deterministic: same description over the same footprint → the same job JSON to
the last decimal (rounded server-side) → the same mesh.

## 4. Storage, serving, and the display contract

`save_roof_model()` writes the GLB into the location's **building-model gallery**
(`app/core/location_model3d.py`) with the sidecar

```
rig "none", format glb, source "roof_build", backend "blender",
tier full (+ selected for low), roof_only true, roof {the description},
width_m/offset_x/offset_z/offset_y, eaves_height_m, footprint_source,
location, created_at
```

so **the whole existing display path serves it unchanged**: `/play/locations/{id}/model`,
the tier signatures, the crossfade, the admin viewer, the map. It serves both
tiers on purpose — a roof is a handful of triangles, and asking the distance-mesh
path to decimate it would risk destroying it while an empty `low` tier would make
`_demand_low` try exactly that on every payload build.

Contract v2 (`model_validate`) wants buildings as ONE unrigged GLB, which this
is. It carries **no texture**: a roof tone is a material, not an image. The
embedded-texture rule is an *upload* check (`validate_static_glb`) and is not
applied to our own deterministic output.

### The roof-only flag — the one contract change

A building model normally **replaces** the far-view recipe shell: the client
calls `dropFarShell()` the moment a server model arrives, because the model IS
the building. A roof stored as a building model would therefore **hide the very
walls it belongs on** — a roof floating over a socle plate.

Rejected fix: "store the roof as the building model only when it contains
everything". That is a rule nobody can check and it throws away the point of the
feature (walls from the recipe, roof from the builder).

**Adopted:** the spec carries `roof_only: true`, and a renderer that builds its
own far-view shell **keeps it** and puts the roof on top. Minimal and guarded:

* `app/core/scene_recipe.py` — `_building_model` copies the sidecar flag into
  the spec.
* `packages/scene-render/src/types.ts` — `SceneModelSpec.roof_only?: boolean`
  (absent = false = the model IS the building, i.e. exactly today's behaviour).
* `client3d/src/scene/sceneRecipe.ts` — three guarded spots:
  1. `hasBuildingModel` ignores roof-only specs, so the shell is built at all;
  2. `applySceneBuilding(..., roofOnly)` skips `dropFarShell` and **appends** to
     `roofParts`/`roofMats` instead of resetting them, so shell and roof fade
     together on the way in and the label rises to the roof ridge;
  3. the tier swap disposes only the material clones the swap really replaced
     (`!tile.roofMats.includes(m)`) — the kept shell's clones must survive.

Everything else about the spec stays a building's, `display` included — it is
computed per location (`shell_area` for a detailed area, `ground`, otherwise
`shell`), and in the ordinary `shell` case the roof fades on zoom-in exactly as a
roof should, and the admin's floor-plan
preview renders it through the same shared `place()`.

Written up for both renderers in `docs/schnittstellen-3d.md`,
*Nachtrag 2026-08-20 (§ B1/B2): Dach-Modelle (`roof_only`)*.

## 5. UI

`frontend/src/tabs/world/BuildingModelPanel.tsx` → **`RoofBuilder`**, in the
Blender block right after the exterior render, buildings only (no room), hidden
without a usable Blender — `model3d.blender.usable`, i.e. `runner.is_available()`
server-side, the same gate the distance-mesh action uses.

1. **🏠 Generate roof (LLM)** → `POST /world/locations/{id}/roof/propose`
2. The proposal is shown **editable**: form dropdown, pitch slider (disabled for
   a flat roof), overhang, ridge axis, material kind, tone picker — beside the
   facts it rests on (footprint size + its source, storeys, eaves height) and a
   note saying whether the LLM answered or the defaults are showing.
3. **Build roof** → `POST /world/locations/{id}/roof/generate` → background job,
   the panel's existing pending poll shows it and picks up the new model.
   **Cancel** drops the proposal.

A second build writes a NEW gallery file and re-points both tier selections; the
old roof stays in the gallery. Two builds cannot overlap: the generate route
claims the job for that location (`claim_job(location_id, kind="roof")`) and
answers `{"status": "already_running"}` while one is in flight.

What the two routes answer when something is missing: **404** unknown location ·
**409** no footprint to roof (with the hint what to draw) · **503** Blender not
usable ("the roof is built locally, not on a backend") · **400** a request body
that is not an object.

Propose-then-build, no silent magic. The description is validated again on the
way in: what the UI sends is a suggestion, not a contract.

## 6. Prerequisites and settings

Blender runs **locally**, not on a generation backend. Everything is configured
under `/admin/settings → Image/Video Generation → Blender refinement (3D)`
(config path prefix `image_generation.`):

| Key | Default | Meaning |
|---|---|---|
| `blender_enabled` | `true` | Master switch for every Blender job |
| `blender_executable` | `` | Explicit path. Empty = discovery: `which blender`, then `/opt/blender*/blender`, `/usr/local/blender*/blender`, `~/tools/blender*/blender` |
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

The roof path itself reads three of them: `blender_enabled`,
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

The roof is the only job an LLM designs; it is not the only Blender job.
`app/blender/scripts/` holds the rest, each one the same "the server thinks,
Blender builds" shape: geometry repair and measurement (`normalize.py`,
`measure.py`, `diagnose.py`), texture work (`bake_vc.py`, `retexture.py`,
`picture_areas.py`), distance stages (`lod.py`), the walkable-surface grid
(`heightgrid.py`), the clip pipeline (`fbx_clip.py`, `cmu_clip.py`,
`clip_orient.py`, `clip_roll.py`, `rig_export.py`, `_cmu.py`) and the building
exterior render (`exterior.py`). `app/blender/refine.py` is the façade for the
character/prop refinement; it has no roof path.

`exterior.py` is worth knowing about here: it renders a building exterior from a
stated vertex list and files the result as a `building-front` gallery image, so
the ordinary image→mesh route can take it from there. Its button sits directly
above the roof builder in the same panel.

## 8. What v1 deliberately does NOT do

* no free-form Blender code — see the top of this file;
* no roof over a concave polygon (rectangularized, § 2);
* no dormers, chimneys, gutters, ridge caps or textures;
* no other asset kinds yet — fences, wells, jetties and simple building bodies
  are the same machinery with another schema, and they are a stage of their own;
* no automatic re-build when the outline or the storey count changes: the roof
  is a stored model like any other, and the button is one click.
