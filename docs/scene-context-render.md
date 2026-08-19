# The context render — a placement spot with a known camera

Stand 2026-08-20. Stage 1 of the scene-context pipeline ("Prop-Welt statt
Dioramen", Etappe 4). Code: `app/core/scene_context.py` (decides),
`app/blender/scripts/scene_context.py` (executes), `scripts/smoke_scene_context.py`
(hand-derived numbers). Related contracts: `docs/schnittstellen-3d.md` § B1/B2
(the scene payload this render is built from) and § B5a (numeric verification).

## Why it exists

Assets are generated on neutral ground today: a product shot, then a mesh, then
a placement. The result never quite belongs where it is put — wrong light, wrong
style, wrong sense of size. The scene-context pipeline turns that around: first
render THE SPOT, then let the image model draw the object INTO that picture, and
only then cut it out and rebuild it in 3D.

Everything after this stage is metric **only because of the camera sidecar**.
The paper this pipeline is derived from (WorldClaw) records the camera κ = (K, E)
for exactly that reason but leaves its setup completely open — FOV, height,
framing and light are ours to define, and this document is that definition. Where
the paper has to recover scale from the image, we know the anchor, the size and
the camera in metres up front; the sidecar is what keeps that knowledge attached
to the picture.

## The frame

The render happens in the location's own **scene frame** — the very frame
`scene_recipe.compose_scene` emits: origin at the anchor pin, **x east, y up,
z south**, metres, yaw turning clockwise seen from above (§ A1.1). The pin
transform (`pos_x`, `pos_z`, `yaw_deg`) travels in the sidecar, so any point is
one `world_geometry.local_to_world` away from a world coordinate.

The WORLD relief under the location (`world_geometry.ground_y`) is **not** baked
into the geometry — the scene payload does not carry it either — it is recorded
in the sidecar as `frame.world_ground_y`. The relief the render DOES show is the
location's own scene relief (`relief.scene_ground_lift`), which is what every y
value in the payload already includes.

Blender is Z-up, so vectors are converted **once, on the server**:

```
(x, y, z)_scene  ->  (x, -z, y)_blender          # M, a proper rotation
R_blender        =   M · R_scene · Mᵀ            # a MESH: its own frame is
                                                 # converted too (glTF importer)
R_blender_camera =   M · R_scene                 # a CAMERA: its local frame
                                                 # (x right, y up, −z forward)
                                                 # is the SAME in both, so only
                                                 # the world side converts
```

That last distinction is not cosmetic: converting the camera's local frame as
well turns the camera a second time and points it at empty sky, with nothing
failing anywhere. The smoke therefore measures the rendered pixel of a probe
patch against its projected pixel — the only check that can see this.

## The target

One of three, all ending in the same five numbers (anchor, ground height,
footprint polygon, height, yaw):

| kind | what it is | where the numbers come from |
|---|---|---|
| `prop` | the `index`-th prop placement of `room_id` (the GROUND room included — a yard placement is a placement) | anchor/yaw/standing height from the scene payload's `models[]` spec, the real dims from the room recipe's `placements[]` (a prop WITH a mesh carries no dims in the payload) |
| `spot` | a free point on the ground with a declared size — "put something HERE" without an authored placement | the target dict itself |
| `building` | the location's footprint | `scene.boundary`, height = `storey_m` |

For a `prop` target the target's OWN model is left out of the render: the plate
has to show the spot **empty**, or the edit stage is asked to add an object that
is already standing there.

## The camera

Three numbers decide it, and nothing else:

**Distance.** An object of size `s` at distance `d` projects to `fy · s / d`
pixels, and `fy = H · f / sensor`. Asking for `fill · H` pixels gives

```
d = f · s / (sensor · fill)
```

The resolution cancels out — changing the render size reframes nothing. `s` is
the diameter of the smallest **sphere** around the target's centre that holds its
footprint corners and its height, `2·√(r_h² + (h/2)²)`. A sphere and not a box
because a sphere projects to the same disc from every direction, so "40 % of the
image height" holds at the 35° elevation exactly as it would head-on.

**Azimuth.** `ψ = target yaw + 45°` in map yaw; the camera stands in the
direction `(sin ψ, cos ψ)` from the target — the target's own "south", turned by
its own yaw. A given kind of object is therefore always seen from the same side
of ITSELF.

**Elevation.** `ε = 35°` above the horizontal: low enough to keep a silhouette
against the background, high enough to show the footprint as a surface.

The camera then looks at the target's centre (anchor lifted by half its height).
Its basis is `right = unit(up × back)`, `up = back × right`, `back = unit(P − C)`
— the Blender/OpenGL convention, looking along `−z_cam`. Straight down has no
defined "right"; there the world's south axis stands in, so the solve never
degenerates.

Intrinsics: sensor fit **vertical**, `sensor = 36 mm`, `f = 50 mm` by default, so

```
fx = fy = H · f / sensor        cx = W/2      cy = H/2
u = cx + fx · x_cam / depth     v = cy − fy · y_cam / depth
```

with `depth = −z_cam`, negative behind the camera. Same input, same camera —
the solve is deterministic, and the smoke checks that too.

## The light

The world calendar gives sunrise and sunset **per season** and nothing else — no
latitude, no declination — so the sun's arc is derived from those two times:

* `f` = how far the day (or the night) has run, 0 at sunrise, 1 at sunset;
* elevation `= ceiling · sin(π f)`, floored at 6° (a light lying flat on the
  ground lights nothing). The ceiling is 60° by day, 28° at night;
* azimuth `= 90° − 180° f` in map yaw: 90° east, 0° south, 270° west.

Night runs the same arc with the moon ceiling and **trades sun energy for
ambient**: a moonlit plate with a physically honest contrast ratio is a black
picture with two lit faces, and the plate has to stay readable for an image
model. The world is a flat sky colour plus one sun lamp — no Nishita sky, whose
`sun_rotation` would be a second angle convention nobody can verify.

## What is in the picture

* **the terrain patch** — the location's relief, sampled on a 32 × 32 grid over
  1.5 × the visible frame;
* **the recipe primitives near the spot** — level and room plates as extruded
  outlines, walls as boxes, straight from the payload, in the contract's own
  colours (`scene_recipe.STYLE`). No second idea of what a room looks like;
* **the stored meshes near the spot** — building, room dioramas and other props,
  imported as GLB/FBX and placed with the contract's `place()` routine (§ B2:
  measure with the fix rounded to 90°, one uniform factor, yaw as the parent
  rotation, then bottom edge and XZ centre onto the spec). Both rotations are
  prepared server-side as quaternions;
* **the scale reference** — a 1 m grid draped over the terrain and a 1.70 m
  figure (§ A3) beside the spot, at 90° to the camera azimuth so it never covers
  it. Both switchable ("Maße brauchen Bezug": the grid gives the unit, the figure
  gives the feeling).

## The sidecar

`context.json` beside `context.png`, written by the Blender script **verbatim**
from what it was handed plus what the render actually did:

```
version, location_id
frame    { kind: "location_local", axes, pin {x, z, yaw_deg},
           world_ground_y, extent_m, storey_m }
target   { kind, room_id, index, prop_id, anchor, ground_y, footprint,
           dims_m, height_m, yaw_deg, span_m }
camera   { lens_mm, sensor_mm, sensor_fit, resolution, fx, fy, cx, cy,
           position, look_at, distance_m, azimuth_deg, elevation_deg,
           rotation_matrix,          # rows = camera axes in scene coords;
                                     # v_cam = R·(p − position)
           quaternion_blender, position_blender,
           fov_v_deg, fov_h_deg, frame_width_m, frame_height_m,
           fill_fraction, span_m }
sun      { night, phase_fraction, elevation_deg, azimuth_deg, direction,
           direction_blender, color, strength, angle_deg, sky_color,
           sky_strength, sunrise_min, sunset_min }
game_time{ canonical, label, season, time, day_bucket, is_night }
mask     { polygon_px, bbox_px, dilate_px }
scale_reference { grid, grid_step_m, figure, figure_height_m, figure_at }
content  { terrain_patch_m, terrain_cells, content_radius_m, models }
render   { width, height, samples, engine, blender_version, png, objects }
```

`mask.polygon_px` is the target's footprint (and the box over it) projected to
pixels, as a convex hull — the silhouette of a box seen from a three-quarter
angle IS the hull of its eight corners, and an inpaint mask has no business being
concave. `dilate_px` grows it about its own centroid so the object's contact with
the ground lands inside the region too.

## Configuration

`image_generation.context_render_*` (Admin → Image/Video Generation → *Scene
context render*): plate size, samples, lens, elevation, azimuth offset, fill,
grid on/off, figure on/off, mask dilation, timeout. The defaults are mirrored as
constants in `app/core/scene_context.py` so the module also runs with no world
loaded (smoke checks, CLI).

What counts as "near the spot" is measured against the WHOLE primitive: a plate
counts when the spot stands on it (its corners are usually all outside the
frame), a wall when its SEGMENT comes within the patch radius (a 40 m contour
wall has both ends outside the picture and still crosses it).

## Known limits of stage 1

* **Surfaces have colours, not textures.** Plates and walls use the contract's
  palette and the terrain a neutral ground colour; the surface library's
  textures are not applied yet. Light, scale and layout are right, the material
  is not — enough for the inpaint stage to match the LIGHT, and the obvious next
  refinement once the edit results are judged.
* **Texture-only surfaces (§ A5, `thickness` 0) are skipped.** They carry no
  geometry, so an outdoor room shows the terrain under it instead of its own
  surface.
* **No characters.** Deliberate, per the programme's non-goals — the only figure
  in the frame is the grey scale reference.

## Verification

`scripts/smoke_scene_context.py`, all values derived by hand in its docstring:

* the camera solve for a 4 m footprint at (3, −2) — distance 19.641855 m,
  position (14.377112, 11.266105, 9.377112), an orthonormal right-handed basis;
* five projected pixels, three of which fall on a line the geometry forces
  (the anchor on the principal point, two corners on the vertical centre line,
  one corner exactly at the framing distance);
* the mask hull and its bounding box, and what a dilation does to them;
* sun angles at noon, 09:00, 15:00, midnight and sunrise;
* the assembled job on a synthetic location (patch size, figure position,
  excluded target model, determinism, all three target kinds);
* **with Blender present**: one real render — the sidecar is verbatim, the
  rendered pixel of a probe patch matches its projected pixel to under half a
  pixel, and a 2 m cube placed with `max_m` 1.0 lands in its hand-derived box.
  Without Blender the section prints a loud SKIP instead.
