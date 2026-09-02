# Multi-view mesh input for props, buildings and rooms — design

Date: 2026-09-02. Status: approved design (brainstorming session), plan follows.

## 1. Goal

The multi-view img2mesh workflow that characters got (front + optional back /
left / right T-pose renders, `model_refs.py` → `model3d.py` →
`service.generate_mesh(view_images=…)` → slot mapping in `openai_mesh.py`) is
extended to the two other mesh subjects: **props** and **location models**
(building exterior and room diorama). A multi-view mesh alias then
reconstructs the back and the depth of a chair or a house from real renders
instead of hallucinating them.

Decisions taken with the user (2026-09-02):

1. Location: the central mesh dialog offers a **picker per view** (several
   gallery images may carry the same view type) — newest preselected, front
   required, the other three optional.
2. The existing gallery image type `building` is **renamed** to
   `building-front` with a one-time boot migration; the four types are
   `building-front` / `building-back` / `building-left` / `building-right`.
3. Back/left/right renders may take the **front image as a reference** —
   for props AND for locations/rooms (the character path stays text-only).
4. **Rooms** get the same four types and the same central button (the
   gallery and the model panel are shared components).
5. View prompts are **per-view use cases** (approach A below).

Unlike the character path, every extra view is rendered as its **own step**
(its own "New image" click) — there is no "render all views" button.

## 2. Approaches considered for the view prompts

* **A — one use case per view (chosen).** The T-pose precedent
  (`tpose` / `tpose_back` / `tpose_side`): every mesh-input base use case gets
  a `_back` and a `_side` sibling; left and right share `_side` plus a side
  phrase prepended to the subject. Admin-editable per view, negatives per
  view (a back render fails differently from a front one). Cost: ten style
  blocks of data, no new concept.
* **B — a view layer in the composer.** A `{view}` slot in the base styles
  and a phrase table. Fewer config entries, but a new composer concept, all
  five base styles rewritten, no per-view negative, no per-view admin tuning.
* **C — prefix only.** "seen from behind" in front of the base style —
  collides with "three-quarter view" inside the style. Rejected.

## 3. Shared vocabulary — `app/core/view_prompts.py` (new, small)

```python
VIEWS = ("front", "back", "left", "right")
EXTRA_VIEWS = ("back", "left", "right")

def is_view(name) -> bool
def view_use_case(base: str, view: str) -> str
    # front -> base; back -> f"{base}_back"; left/right -> f"{base}_side"
def view_prefix(view: str) -> str
    # "" for front; the phrase prepended to the SUBJECT for the others,
    # e.g. back:  "seen directly from behind, the rear side facing the camera"
    #      left:  "seen from the left side, the left flank facing the camera"
    #      right: "seen from the right side, the right flank facing the camera"
```

Props (`props.py`) and locations (`world_ops.py`) use it. The character path
(`model_refs.py`, `TPOSE_VIEW_PROMPTS`) is NOT touched — unifying it is a
separate, later step.

Reference-image rule for every view render (props and locations alike): the
reference travels as `params["reference_images"] =
{"input_reference_image_1": <front path>}` — the slot the gallery regenerate
already uses — and ONLY when the front file exists and the backend declares
`ref_slot_count >= 1`. Otherwise the render runs without it and logs why. A
reference supplies appearance only (CLAUDE.md); the view prompt still decides
the view. The front render itself never takes a reference.

## 4. Use-case data (`app/core/config.py`, `_DEFAULT_IMAGE_USE_CASES`)

Ten new use cases, both families (`keywords` / `natural`), each with
`prompt_style`, `prompt_negative`, `prompt_instruction`:

| base                 | new                                                  |
|----------------------|------------------------------------------------------|
| `prop`               | `prop_back`, `prop_side`                             |
| `building`           | `building_back`, `building_side`                     |
| `building_outdoor`   | `building_outdoor_back`, `building_outdoor_side`     |
| `room_model`         | `room_model_back`, `room_model_side`                 |
| `room_model_outdoor` | `room_model_outdoor_back`, `room_model_outdoor_side` |

Framing and lighting stay identical to the base (isolated, neutral
background, flat shadowless light, margin) so the views compose into one
consistent set; only the camera clause and the negatives differ. The `_back`
styles say the rear faces the camera (buildings: no entrance/front door
expected; props: the back of the object); the `_side` styles say a profile
view, the left/right decision comes from `view_prefix`. `_seed_default_use_cases`
backfills them into existing worlds automatically. The defaults are a
starting point — which camera geometry a given mesher wants (orthogonal vs.
three-quarter) is tuned in `/admin/settings`, not in code.

## 5. Props

### 5.1 Storage

Next to the variant's front image (`source.png` / `source-v<n>.png`,
unchanged) the extra views live as `source_<view>.png` /
`source-v<n>_<view>.png` (`view ∈ back, left, right`). `source_name(stem)`
gets a sibling `view_source_name(stem, view)`; `_source_file` /
`source_path` take a `view` keyword (default front = today's behaviour).

Provenance per view: the variant entry's `image` record (backend, prompt,
negative, generated_at) gets siblings under `image_views: {back: {...}, ...}`
(master record: `image_views` key next to the legacy master image fields).
`_image_meta` / `_set_image_meta` take a `view`.

Deleting a variant removes its view images with it (they are the variant's
files). Deleting a view image is a new explicit action (below).

### 5.2 API

* `POST /world/props/{id}/variants/{i}/generate` with `image_only: true`
  additionally accepts `view` (`back|left|right`; absent = front) and
  `front_reference: bool`. An unknown view is a 400. The double-start key is
  extended by the view so a back and a left render of the same variant may
  run side by side while the same view stays one job.
* `POST /world/props/{id}/variants/{i}/source?view=back` — upload a view
  image (same normalisation as the front, alpha kept).
* `DELETE /world/props/{id}/variants/{i}/source?view=back` — remove a view
  image (new; front images are not deletable this way, as today).
* `GET /assets/props/{id}/source?variant=&view=back` — serve a view image
  (404 when absent).
* The prop record the admin list returns gets, per variant, `images:
  {front: {...}, back: {...}, left: {...}, right: {...}}` (present keys =
  existing files, each with its provenance record). The existing `image`
  key stays the front record (it is what the strip and the list thumbnail
  read).
* Mesh runs (`POST …/generate` with `mesh_only`, and the full chain on the
  variant route) accept `views: ["back", "left"]`. `_generate` collects the
  files that exist among the requested views and passes them as
  `view_images` to `generate_mesh`; a requested view without a file is
  skipped with a log line, never an error. The mesh sidecar records
  `view_images: {back: "source_back.png", …}` (file names, like the character
  mesh).
* `GET /world/props` → `image_backends[].ref_slot_count` (the dialog needs it
  for the reference toggle).

### 5.3 Render

`_render_source(prop_id, backend_glob, prompt, negative, variant, *, view="front",
front_reference=False)`:

* use case `view_use_case("prop", view)`; `compose_prompt` composes from that
  use case; `view_prefix(view)` is prepended to the SUBJECT before composing
  (early tokens steer diffusion — same reason the shape hint is prepended).
  A prompt the dialog sends back is final and used as is.
* reference per § 3 rule.
* result via `save_source_image(..., view=view)`.

### 5.4 UI (`PropDetail`, `PropImageDialog`, `PropsTab`, `MeshBackendDialog`)

* Source-image panel: the front stays as today. Below it a row of three
  small tiles **Back / Left / Right** — thumbnail when the file exists, a
  dashed placeholder otherwise — each with 🖼 (New image for THIS view),
  ⬆ (upload) and × (delete, armed click like the gallery). The tile's 🖼
  opens `PropImageDialog` with the view fixed.
* `PropImageDialog`: title names the view; for back/left/right a checkbox
  **"Use the front image as reference"** — shown only when the variant has
  a front image; disabled with a hint when the chosen backend has no
  reference slot. The prefilled prompt composes from the view's use case
  (the dialog's `composePropPrompt` gets the view's style from the backend
  entry: `image_backends[].prompt_styles[<use case>]` — the list route
  resolves all four prop use cases per backend, not just `prop`).
* `MeshBackendDialog` (re-mesh from the source image, and the "regenerate as
  another variant" run) gets the generic **Views** section (§ 7) fed with
  this variant's existing view files: one checkbox per existing view,
  checked by default. The create form and the plain regenerate have no views
  yet (a new variant has no images) and show none.

## 6. Locations and rooms

### 6.1 Image types

`IMAGE_TYPES = ['', 'day', 'night', 'map_2d', 'building-front',
'building-back', 'building-left', 'building-right']` (frontend
`worldTypes.ts`); the server validation in `assign_gallery_image_type`
accepts the same set. Everywhere the code asked `type == 'building'` it now
asks "is a building view" (`startsWith('building-')` / `is_building_type`):
the 3D-mode filter, the 2D-mode exclusion, the hidden 🌙 button, the type
assignment on save, the replace/blend rules in `generate_gallery_image_core`,
the batch use-case list. `exterior_render` writes `building-front`. The
world-dev prompt field `image_prompt_building` keeps its name — it is the
one SUBJECT for all four views (`resolve_gallery_subject` treats every
building view like `building` today).

`gallery_use_case(location, room_id, prompt_type)` keeps its indoor/outdoor
and room logic for the BASE and returns `view_use_case(base, view)` for a
building view; `prompt_type` of a building view is `building-<view>`. All
four render at 1024 × 1024 unless the caller picks a size (rooms do).

### 6.2 Migration

`migrate_building_image_type_once()` (in `app/models/world.py`, called from
`app/server.py` next to `migrate_scale_frame_once`): walks
`<storage>/world_gallery/*/gallery_meta.json`, rewrites every `image_types`
value `building` → `building-front`, writes only files that changed, logs
the count. Idempotent by construction (no marker file needed). The pure
rewrite of one meta dict is its own function so the smoke script can check
it without a world.

### 6.3 Render with reference

`POST /world/locations/{id}/gallery` body: `prompt_type: "building-back"`,
optional `front_reference: "<gallery file name>"`. The server resolves the
name against the location's gallery dir (path-escape check as for
`reference_image`) and applies the § 3 rule. `use_source_as_reference` keeps
its meaning (regenerate = literal prompt, no style) and is NOT reused; a
view render always goes through the composer. A room-scoped render carries
`room_id` as today; the reference is expected to be a `building-front` image
of the same scope (the dialog offers only those; the server checks only
existence).

### 6.4 UI — gallery (3D mode, location and room)

* "🏛 Generate building image" / "🏛 Generate model image" open the
  `ImageGenDialog` with a new **View** selector (front / back / left / right,
  default front) at the top. Choosing a view sets `prompt_type` and re-runs
  the compose preview.
* For back/left/right the dialog shows **"Use front image as reference"**
  with a dropdown of the `building-front` images of this scope (newest
  preselected) — only when at least one exists. A backend without a
  reference slot gets a hint and the toggle disabled; the render is still
  allowed (the reference is optional, unlike the regenerate case).
* The per-tile 🧊 button is removed, together with `onGenerateModel` /
  `generateSource` / `onGenerateSourceConsumed` through `LocationGallery`,
  `LocationEditor`, `RoomEditor`, `WorldTab`. The type dropdown on a tile
  lists the four building views.

### 6.5 UI — central mesh button (`BuildingModelPanel`)

A **"🧊 Generate 3D model"** button in the panel head, next to Upload /
Roof / Exterior render (the other ways to a model). Click: the panel fetches
the gallery (`GET /world/locations/{id}/gallery`), derives per view the list
of images of that type within its scope (location = images without a room,
room = images of that room), sorted newest first, and opens the
`MeshBackendDialog` with the **Views** section (§ 7): front required (no
front image → the button is disabled with a tooltip saying which type is
missing), back/left/right with "— none —" plus the images, newest
preselected.

### 6.6 API

`POST /world/locations/{id}/model3d/generate` (and the room route) accepts
`view_images: {back: "<file>", left: "<file>", right: "<file>"}` next to
`source_image`. `trigger_generation(..., view_images=…)` → `_generate` →
`generate_mesh(view_images=…)`. File names are resolved and path-checked
like `source_image`; a missing view file is a 400 (the dialog just offered
it). The mesh sidecar records `view_images`; the gallery row tooltip names
the views that went in. The double-start key stays keyed by the front image
(the views do not change the job's identity).

## 7. `MeshBackendDialog` — generic Views section

New optional prop:

```ts
views?: Array<{
  view: 'front' | 'back' | 'left' | 'right'
  /** Candidate images: value = file name sent to the server, label = shown. */
  options: { value: string; label: string }[]
  required?: boolean   // front for locations
}>
```

Rendering rule per view: 0 options → not rendered (a required view with 0
options blocks Generate with a hint); 1 option → a checkbox (checked by
default); >1 options → a select with "— none —" (optional views) and the
first option preselected. `onGenerate(backend, opts)` gains
`opts.views?: Partial<Record<view, string>>` with the chosen file per view
(front included for locations). Props pass their existing files as
single-option views; the caller maps `opts.views` onto its own body shape
(`views: [...]` for props, `view_images: {...}` for locations).

## 8. What does not change

* `service.generate_mesh` and `openai_mesh` (view → alias slot mapping;
  single-slot aliases get the front only). Rig `none` multi-view aliases are
  gateway configuration, not code.
* The character path (`model_refs.py`, `model3d.py`, `FieldModelRefs.tsx`).
* Regenerate/adjust of gallery images (`use_source_as_reference`).
* Content packs: `content_io.py` does not carry gallery image types today
  and does not start to.

## 9. Verification

* `scripts/smoke_view_types.py` (no world, no server), expectations derived
  by hand in the docstring: `view_use_case` for all five bases and four
  views; `is_view`/type validation (the four types accepted, `building`
  rejected); the migration rewrite on an in-memory meta dict (`building` →
  `building-front`, other values untouched, second run changes nothing);
  prop view file names (`source_back.png`, `source-v2_left.png`, front
  unchanged); `view_prefix` empty for front and non-empty for the rest.
* Existing smokes stay green: `smoke_mesh_multiview.py`,
  `smoke_game_time_lint.py`, `smoke_scene_recipe.py`.
* `npm run lint`, `npm run build` (admin bundle committed).

## 10. Documentation touch points

* `CLAUDE.md` 3D-models paragraph: one sentence on the four building view
  types and the prop view images.
* `development_instructions/backend-status-3d.md`: ledger entry.
* `docs/` image use-case reference: the ten new use cases.

## 11. Out of scope (deliberately)

One-click "render all views"; a reference for the front render itself;
moving the T-pose views onto `view_prompts.py`; per-view badges in the
model gallery row beyond the tooltip; auto-meshing after a view render.
