# Manual: map (terrain and height)

The world is one flat plane in metres: `x` east, `z` south, a point is `[x, z]`.
`world_overview{}` names the world bounds and the terrain kinds that exist; `map_region{min_x,
min_z, max_x, max_z}` shows what already lies in a box (add `"polygons": true` for outlines).

## Terrain areas — the painted ground

`add_terrain_area{kind, polygon | stroke, label?, z_order?}`,
`update_terrain_area{id, kind?, polygon? | stroke?, label?, z_order?}` (existing areas too —
reshaping a wood to make room for a lake is an edit; everything else stored on the area is kept).

- `kind` — EXACTLY one of the world's terrain kinds (see `world_overview`); anything else is
  refused. The overview also says which kinds are impassable.
- `label` — a short name shown in the map editor ("Eastern woods").
- `polygon` — the outline `[[x, z], …]`, 3 to 24 points (more is allowed but almost never
  needed: a wood is a shape, not a tracing). Do not repeat the first point; the ring closes
  itself; it must not cross itself.
- `stroke` — INSTEAD of a polygon for anything long and thin (river, road, forest edge, beach):
  `{"points": [[x, z], …], "width_m": 14, "style": "wavy", "spacing_m": 40, "amplitude_m": 8}`
  - `points` — the centre line, 2 to 40 points.
  - `width_m` — footpath 2–3, road 5–8, river 10–40.
  - `style` — `"straight"` (default), `"jagged"` (cliff edges, rough coast) or `"wavy"`
    (rivers, natural borders). `spacing_m` (2–100) and `amplitude_m` (0.5–30) shape the bends.
- `z_order` — which area is painted on top where two overlap; higher wins. Default 0; water and
  roads get a higher number than the ground they cross.

## Height areas — hills and hollows

`add_height_area{polygon, height_m, falloff_m?, label?}`,
`update_height_area{id, polygon?, height_m?, falloff_m?, label?}`.
`height_m` −50 … 50 (negative = hollow); `falloff_m` = over how many metres the ground climbs
there (gentle hill 30–80, plateau edge 5–10, 0 = a vertical wall). Only when the task asks for
relief.

## Composition

- Stay inside the world bounds.
- Compose, do not tile: a handful of large, well-placed shapes reads better than fifty small ones.
- Use water, rock or a dense forest belt as the world's edge.
- A meadow is terrain, not a location — create a place only where the task asks for one.
- `delete_created{kind: "terrain" | "height", id}` removes an area this run created, in this turn
  or an earlier one; an area that existed before the run is never deleted.
