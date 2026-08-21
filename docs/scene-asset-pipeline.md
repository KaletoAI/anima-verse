# The scene-asset pipeline — an object drawn into its own place

Stand 2026-08-20. Stages 2–5 of the scene-context pipeline ("Prop-Welt statt
Dioramen", Etappe 4); stage 1 is `docs/scene-context-render.md`. Code:
`app/core/scene_asset.py` (all of it), `scripts/smoke_scene_asset.py`
(hand-derived numbers). Related: `development_instructions/analyse-worldclaw.md`
(the paper this is a reduction of) and `docs/schnittstellen-3d.md` § B2
(the placement contract the result is written into).

## Why it exists

A prop generated on neutral ground is a product shot: the right object, the
wrong world. It arrives with studio light in a forest at dusk, with a plastic
sheen where everything around it is wet stone, and at whatever size the mesher
felt like. The plate stage turned that around by rendering THE SPOT; this stage
lets an image model draw the object INTO that picture, cuts out what it drew,
and rebuilds it in 3D at the size the specification demands.

Four things separate this from the paper it comes from, and all four make it
simpler:

| WorldClaw | here | why |
|---|---|---|
| the image model decides what goes where | the anchor is authored | no back-projection, no position recovery — we put the picture where the position already is |
| SAM3 segments the object | mask difference (E4.3, decided) | the spot is known and the region was inpainted by us, so "what changed in there" is the whole answer |
| scale recovered from the image, iterated | metric from the spec (E4.4) | the prop declares its dimensions; the picture supplies appearance, never size |
| a vision model inspects the render | geometric checks | our rule: findings are numeric (§ B5a), and Blender runs without vision |

## The four steps

### 1. Insert

The plate (`context.png`) plus the sidecar's mask polygon, grown by
`scene_asset_mask_margin` × the mask bbox's LONGER side, rasterised to an
L-PNG where **white = the region to fill**.

Two paths, and the result record says which one ran (`path`):

* **`inpaint`** — plate and mask go to a backend that can take a mask. The
  surroundings stay pixel-identical and the position is guaranteed by
  construction. "Can take a mask" means **both** `api_type ==
  "openai_diffusion"` **and** `category == "inpaint"`:
  * the class is the transport — it routes a request to
    `POST /v1/images/edits` as soon as an `input_mask` reference slot is
    present (`_is_inpaint`), and its `mask_format` setting decides whether the
    L-PNG travels as-is or is inverted to the OpenAI RGBA form. **No other
    backend class in the tree consumes a mask at all** — LocalAI/Together fold
    every reference image into `ref_images`, A1111 and CivitAI take none — so
    handing one a mask would look like a successful edit while the whole plate
    was repainted.
  * the category is the MODEL. Being able to carry a mask says nothing about
    what is on the other end: an edits request against a plain txt2img/img2img
    alias reaches the gateway and dies there. Measured 2026-08-20/21 on
    `Flux1-Dev` (category `img2img`): `HTTP 502 (Generierung fehlgeschlagen)`
    after ~100 s, and once the alias had no warm worker, `HTTP 503 — No healthy
    backend for generation model 'Flux1-Dev'`. The world had `Flux1-Dev
    Inpaint` configured the whole time; only the category tells them apart.
* **`img2img`** — the fallback for backends without a mask: the plate goes in
  as reference slot 1 and the model redraws the frame. The position is then
  only as good as the model felt like being, and the cutout stage is what
  notices (it intersects with the mask region regardless). A run that lands
  here for want of an inpaint backend says so on the record (`backend_note`) —
  the cure is a config one and the pipeline never applies it itself.

Selection: an explicit backend glob wins. Without one the pool's normal
matching would never offer an inpaint backend — they are excluded from render
matching by design (`selection._is_inpaint_backend`) — so the preference is
applied over the pool's list here: cheapest available mask-capable backend
first, the normal image default second. The cheapest-first sort is **stable**,
so equal-cost backends keep their configured order; membership is what decides,
which is why the category belongs in `backend_takes_mask` and not beside it.

The prompt is the use case **`scene_asset`** (`config._DEFAULT_IMAGE_USE_CASES`,
both families, `llm_compose` off by default) with the prop's description as the
subject. It says: add ONE object at the marked spot, standing on the ground,
same light, same perspective, size true to the one-metre grid, surroundings
unchanged. `image_use_case` is deliberately NOT set on the generation params:
the central downscale would resize the result away from the plate and break the
pixel correspondence the next step lives on. A result that comes back at a
different size is resized back to the plate's size before anything is measured.

### 2. Cutout

`delta(before, after)` per pixel, where delta is the **largest absolute channel
difference** — a change in brightness and a pure change in hue both count,
where an average would let a strong single-channel change hide under a
threshold tuned on grey. Above `scene_asset_diff_threshold` (12/255) a pixel is
"the object".

Then, in this order:

1. intersect with the grown mask region (in the `img2img` path this is what
   keeps the rest of the redrawn frame out);
2. **open** (erode → dilate) — kills specks; then **close** (dilate → erode) —
   fills pinholes. Closing first would grow a speck into a blob the opening can
   no longer remove. Both use a 3 × 3 square in pure numpy; outside the image
   counts as empty, so an object that runs out of the plate does not get
   silently completed;
3. optionally intersect with **rembg** (u2net, the session helpers of
   `models/character`) run on the crop around the changed region — as CLEANUP
   only. It trims the halo the difference leaves on soft edges. Never used
   alone: it segments "the foreground", which on a plate full of scenery is not
   necessarily what we just added. An intersection that keeps less than a fifth
   of the mask is discarded as a mis-segmentation.

The crop that feeds image-to-3D is square, grown by `scene_asset_crop_margin`,
clamped into the plate and scaled to `scene_asset_crop_px`. The transform is
recorded as **`crop`** in `result.json` — offset, side, scale — together with
the paper's *equivalent intrinsics*: a crop is an affine change of image
coordinates, so the plate camera also describes the patch, with `fx' = fx·s`
and `cx' = (cx − x0)·s`. Any measurement taken in patch pixels can therefore be
read back in plate pixels, and from there in metres.

The cutout is stored as the target variant's **source image** before it is
meshed, and stamped with where it was taken: `origin "scene_context"`, the
location's id and display name, and the RUN's own `started_at` (never a fresh
clock read). A cutout carries the light, the ground and the surroundings of one
spot, so a variant made this way is not interchangeable with a product shot,
and the Props tab marks it 🎬 instead of leaving the two indistinguishable. A
product shot writes no origin key at all — absence IS the product shot, which
is why no existing prop needed migrating (`docs/schnittstellen-3d.md`,
"Ergänzung 2026-08-20: Woher das Bild stammt").

> **SAM3 remains the documented upgrade path.** If the difference proves too
> coarse in practice — a translucent object, a shadow that swallows the
> silhouette — a text-guided segment of the same crop slots in exactly where
> rembg does now: as another intersection, on the same crop, with the same
> affine recorded. Nothing else in the pipeline would change.

### 3. Mesh

The cutout (RGBA, transparent background) goes through
`service.generate_mesh(rig="none")` — which never falls back between mesh
backends — into a NEW variant of the prop (E2.3a: `target_variant` appends
while the cap allows, existing meshes are never replaced). The variant is
decided ONCE per run, so a retry refines the same slot instead of eating
another of the prop's active variants.

`blender/refine.normalize` then scales the delivery to the **declared** height
from the plate sidecar (`target.height_m`) behind the four gates of
`apply_script`, and the mesh is measured afterwards: a height outside
±`scene_asset_height_tolerance` is a failed attempt. Only a mesh that passed
becomes the variant's active file — a rejected one stays in the gallery
unselected, because the history is worth keeping but the world must not show
an object that would not scale to its own size.

### 4. Placement and contact

**Position never moves.** It is the authored anchor — that is the whole reason
this pipeline needs no back-projection.

**Yaw.** The plate camera stands at map azimuth `ψ` *as seen from the target*
(`solve_camera`: `position = centre + d·(cos ε·sin ψ, sin ε, cos ε·cos ψ)`, and
`ψ = target yaw + azimuth offset`). Image-to-3D reconstructs in the input view's
frame — what the picture showed faces the viewer, i.e. local `+Z`, which is
both the glTF convention ("the front of an asset faces +Z") and this contract's
prop convention (front = south = facing 0, `room_recipe.compose_prop_marker`),
because the scene frame is x east, y up, **z south**. `rot_y(yaw)` turns local
south to map azimuth `yaw`, so a prop's front points at `yaw`, and it has to
point AT the camera:

```
yaw_deg = ψ mod 360
```

**Not `ψ + 180`.** That is the direction the camera *looks*; turning the object
into it would show the plate's picture from behind. The check that makes the
sign visible: with the plate's azimuth offset at 0 the formula returns the
AUTHORED yaw unchanged — the default 45° three-quarter offset IS the whole
difference between the authored orientation and the drawn one, and the drawn
one is what the mesh reproduces. The per-model rotation fix stays available for
a mesher that does not honour the glTF convention.

**Contact, numeric.** The footprint is the placed mesh's own measured bbox
bottom rectangle (width/depth after normalisation), turned by the final yaw
around the anchor. It is sampled on a **3 × 3 lattice** — the corners alone
miss a ridge under the middle, one centre point misses everything — against the
ground:

```
ground(lx, lz) = world_geometry.ground_y(world point) − ground_y(pin)
               + relief.scene_ground_lift(loc, world point)
```

Both halves, exactly as `relief` splits them, with the world half taken
RELATIVE TO THE PIN because the scene frame's y = 0 *is* the pin's ground —
the same constant the plate sidecar records as `frame.world_ground_y`. On a
plateaued location the world half is flat and the term vanishes.

```
contact_ratio = |{ samples with |bottom − ground| ≤ contact_tolerance_m }| / 9
```

If the object **hovers** (every sample below its bottom edge), the placement
sinks: `offset_y` drops until the bottom sits on the LOWEST sample, so nothing
floats and at most the lower side is buried. A placement that already touches
somewhere is left alone, and one that sits *below* its lowest sample is
reported rather than lifted — that was authored, and overruling it is not this
pipeline's business. **Terrain is never edited.** When the drop across the
footprint exceeds `scene_asset_level_slope_m`, the result carries a
`suggest_level` block instead: the plan's "lokal planieren" as a suggestion a
human can act on, strictly local, never global, never automatic.

The successful run writes `variant`, `yaw` and `offset_y` back onto the
placement through `world_ops.update_prop_placement`, which re-runs the whole
list through `_sanitize_props` — this path cannot store a value the normal
editor could not. `variant` is new on a placement (it used to be dropped by the
sanitizer and by `room_recipe._place_props`, so a manual placement always
showed variant 0 no matter what was picked); `scene_recipe._variant_index` has
been reading it all along.

## The refinement loop

Bounded, `scene_asset_retries` extra attempts (default 2) with a fresh seed.
The plate is rendered ONCE — it does not depend on the seed. Each attempt runs
insert → cutout → mesh → place and records every check:

| check | fails when | a new seed helps |
|---|---|---|
| something changed in the region | the edit did nothing inside the mask | yes |
| drawn size | (cutout pixel height) / (expected pixel height) outside `[px_ratio_min, px_ratio_max]` | yes |
| mesh height | outside ±`height_tolerance` after normalisation | yes |
| contact ratio | below `contact_ratio` after the sink | **only partly** |

The expected pixel height is the target's own box projected with the plate
camera — literally the undilated mask hull of `scene_context.mask_polygon`. An
object drawn half the size of its own footprint is a failed edit, not a small
object.

The contact check is the honest exception: it depends on the terrain under the
footprint, which no seed changes. What a new mesh can move is its own footprint
size, so the check stays inside the loop — but a contact failure on flat-out
unsuitable terrain will repeat, and the `suggest_level` block beside it is the
part that is actually actionable. This is stated here rather than hidden,
because a retry budget spent on a defect it cannot fix is worse than none.

An attempt that RAISES is a failed attempt, not a failed run: a gateway hiccup
on the second seed must not throw away the first one's record.

## Job shape and artefacts

`trigger_scene_asset(location_id, room_id, placement_index, …) -> bool` — the
props job idiom verbatim: a double-start guard per placement, a daemon thread,
ONE tracked header task around the whole chain (the individual GPU jobs appear
in the queue panel through their own channel entries), and every image and mesh
call serialised on its backend's channel. False means this very placement is
already running.

Every run writes into the prop's own directory, `scene_asset/<ts>/`:

```
before.png      the source image of the variant this spot showed UNTIL NOW
context.png     the plate (stage 1)
mask.png        the grown inpaint region, white = fill
edit.png        what the image model drew          (per attempt: edit-2.png …)
cutout.png      the object, transparent background (per attempt)
result.json     paths, prompt, backend, path taken, every check, timings
```

`result.json` is written **before any work happens** and rewritten after every
stage — it is the run's state, not its epitaph. Three fields carry that:

| field | says |
|---|---|
| `stage` | where the run stands, or last stood: `plate` → `mask` → `backend` → `insert` → `cutout` → `mesh` → `place` → `done`. Each attempt carries its own `stage` too. |
| `failed_stage` | the stage it stopped in, empty on success |
| `failure_reason` | why, in one sentence, empty on success |

A stage that RAISES (a dying Blender render, a plate without a region, an empty
backend pool) persists both fields on its way out and then re-raises, so the
queue header still fails. A stage that merely fails (no image, ratio off the
band, mesh height, contact) is an ordinary result with `ok: false`. A run whose
PROCESS died writes nothing at all — its record keeps the stage it reached and
never gets a `finished_at`, and the READER joins that with `is_running`
(`settle_interrupted`) to tell a killed run from a live one.

which is also the picture strip the UI shows: **before → plate → edit →
after**. `before.png` is copied at trigger time, not afterwards — a run that
refines the very variant the placement pointed at overwrites that variant's
source image in stage 2, so a live URL would show the after in both frames.
`result.json` names the variant it came from as `previous_variant` (a STORE
index, resolved from the placement's POSITION the way both renderers resolve
it, modulo included). A first generation replaces nothing and has no before.

## Routes and UI

`app/routes/scene_asset.py`, prefix `/world/scene-asset` — a thin adapter, every
decision stays in the core:

| route | does |
|---|---|
| `POST /generate` | starts the chain for one placement. Body `{location_id, room_id, placement_index}` plus the optional `{subject, image_backend, mesh_backend, seed}`. **409 = this placement is already running** (the core's double-start guard reporting load, not a defect). A placement the world does not carry is a 404 — the yard is an ordinary room here, named by its reserved id `__ground__`; an empty `room_id` names nothing. |
| `GET /status` | `{running, prop_id, placement, last_run}` for one placement — the poll the editor runs while a job is out. `last_run` is the newest run **of this placement**; a prop stands in many places and its run directory holds all of them. |
| `GET /runs/{prop_id}` | the same summary for every run the prop ever had, newest first (the directory names are timestamps, so their reverse sort IS the chronology). A directory without a readable `result.json` is a run still writing and stays invisible. |
| `GET /runs/{prop_id}/{stamp}/{file}.png` | the run's artefacts, ETag + 304. Path-escape-checked exactly like `assets.resolve_clip_path`: two segments, no dot segment, no backslash, PNG only, and the resolved path must still lie inside the prop's run directory. |
| `POST /placement` | patches `variant` / `yaw` / `offset_y` of a stored placement through `world_ops.update_prop_placement` — the very writer the pipeline uses, sanitiser included. |

`seed` pins the **first** attempt only; retries keep drawing fresh ones, because
a retry on the same seed would redraw the same picture and fail the same way.

The **summary** the three read-routes return is built in one place
(`_summary`) and is the UI's whole contract: the run's `files` with the LAST
attempt's `edit`/`cutout` folded over them (a failed run never promotes them,
and they are exactly what explains the failure), the checks with the band they
are judged against beside them, and the core's own failure sentences verbatim
— plus `stage`, `failed_stage`, `failure_reason`, `unfinished` and
`backend_note`, so a reader never has to open a log to learn where a run died.

The UI is `frontend/src/tabs/world/ScenePropPanel.tsx`, inside the floor plan's
selected-placement strip next to the yaw/height dials: **"🎬 Generate in
scene"**, the placement's model-variant picker, and the collapsible picture
strip with the readouts. The button is **disabled while the location has
unsaved changes** — the pipeline renders the STORED world, and a run's own
writes would be lost to the next Save of a stale draft. When a run finishes the
editor reloads the location, so the draft picks up the variant, yaw and sink
the run wrote.

## Configuration

`image_generation.scene_asset_*` (Admin → Image/Video Generation → *Assets in
the scene context*): mask margin, change threshold, rembg cleanup, crop margin
and size, the drawn-size band, height tolerance, contact tolerance and ratio,
the levelling-suggestion threshold, retries. The defaults are mirrored as
constants in `app/core/scene_asset.py` so the module also runs with no world
loaded (smokes, CLI) — the same rule the context render follows.

## Verification

`scripts/smoke_scene_asset.py`, every value derived by hand in its docstring on
the SAME plate camera as `scripts/smoke_scene_context.py`:

* expected pixel size — the mask bbox `[307.20, 406.93, 716.80, 645.18]`, whose
  width 409.60 px is `H · fill` and `fy · span / d` at the same time;
* mask grow — 0.12 × 409.60 = 49.152 px, and the growth geometry on a unit
  square (a corner moves 1.2 · 0.7071068 = 0.8485281 px);
* rasterisation on pixel CENTRES (a square (2,2)…(7,7) is 25 pixels, not 36);
* the difference mask on an 8 × 8 plate with exact pixel sets, including a
  colour-only change that an average would have missed, and open/close with
  their exact results (speck gone, hole filled, block unchanged);
* the crop affine and its round trip, plus the equivalent intrinsics
  `fx' = 52428800/19188 = 2732.3744`, `cx' = 512.0`;
* the yaw formula (ψ = 45° → 45°, and the front direction it produces IS the
  direction to the camera);
* contact and sink on three synthetic grounds — flat + float (0.0 → 1.0),
  gentle slope + float (0.0 → 1.0, no suggestion), real slope (0.333 → 0.333,
  suggestion, and the honest finding that sinking cannot flatten a slope);
* the retry budget with injected attempts, and the `NO_NEW_IMAGE` cache
  sentinel in every shape it can arrive in.

`scripts/smoke_scene_asset_routes.py` does the same for the HTTP surface — the
router on a bare app, a faked world and trigger, a hand-written run history:
the 409 double-start guard, the status shape (a run on placement 4 must not
light up 3), the summary values read off a record written by hand, and the
path-escape rule in every shape it can be sent (the dot segments go
percent-encoded, because an HTTP client collapses them in the URL itself and a
plain spelling would never reach the handler).

## Known limits

* **The plate has colours, not textures** (stage 1's limit): the insert matches
  the LIGHT and the layout, not the material of the ground it stands on.
* **The `img2img` fallback redraws the frame.** Only the masked region is read
  back, so the object is correct — but the fallback cannot promise the
  untouched surroundings the inpaint path guarantees.
* **No characters.** Deliberate, per the programme's non-goals.
* **One object per run.** Multi-instance segmentation is exactly what the
  authored anchor makes unnecessary.
