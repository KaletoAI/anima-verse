# Manual: map (terrain and height)

The world is one flat plane in metres: `x` east, `z` south, a point is `[x, z]`.
`world_overview{}` names the world bounds and the terrain kinds that exist, each as
`<kind> "<name>"` plus the flags that differ from plain ground: `impassable` (nobody can walk
there), `water`, `speed ×<f>` (walking pace). `map_region{min_x, min_z, max_x, max_z}` shows
what already lies in a box (add `"polygons": true` for outlines): a terrain line ends
`· scatter <n>` / `· along <n>` / `· slots <n>` when the area grows props, has rows of props
along its stroke or NPC slots; a place line ends `· outline (x0,z0)-(x1,z1) · on <kind>`.
An outline too long for that list reads `polygon: <n> points — get_area{"id": …}`:
`get_area{id}` returns one terrain or height area whole — for an area drawn as a stroke first
the centre line and width to send back in an update, then its full polygon. A list too long
for that result ends `,…]` with a `[cut — …]` line: never send a cut list back.

## Terrain areas — the painted ground

`add_terrain_area{kind, polygon | stroke, label?, z_order?, scatter?, npc_slots?, water?,
relief_amplitude_m?, relief_wave_m?}`,
`update_terrain_area{id, kind?, polygon? | stroke?, label?, z_order?, scatter?, npc_slots?, water?,
relief_amplitude_m?, relief_wave_m?}` (existing areas too — reshaping a wood to make room for a
lake is an edit; everything not sent is kept, including the rows of props along a stroke —
`along: <n> rows` in `get_area`). A new `stroke`
replaces the whole stroke: send `style`, `spacing_m` and `amplitude_m` again or they fall back
to their defaults. A `polygon` sent for an area drawn as a stroke drops the stroke and its
`along` rows.

- `kind` — EXACTLY one of the world's terrain kinds (see `world_overview`); anything else is
  refused. The overview also says which kinds are impassable. An impassable area painted under
  a place's pin is stored, and the result names the place (`place <id> "<name>" now stands on
  <kind>, which nobody can walk on`) — reshape the area or move the place. The same warning
  follows `update_terrain_area` and a `delete_created` of an area that bares such ground.
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

## What grows and lives on an area

Every value below is stored exactly as sent or the call is refused (`'<key>' would be stored as
<value> — send that value or leave it out`); read an area back with `get_area`, which ends with
`scatter: <n> entries (<prop id> d=<density> s=<spacing> …; …)`, `along: <n> rows (…)`,
`slots: <roles>`, `water: <key>=<value> …` and `relief: …` lines for what it has — resend the
entries you keep from there when you change one. The scatter and along lines are never cut: every
entry is on them, and every stored key of an entry is on that line
(`d` = `density_per_100m2`, `s` = `min_spacing_m`, `yaw` = `yaw_mode`, `spacing` / `offset` =
`spacing_m` / `offset_m`; any other key, e.g. `variant`, `reshuffle_min`, `start_m`,
`spacing_jitter_m`, under its own name) — resend those too, or the entry loses them.

- `scatter` — props spread over the area, at most 8 entries, e.g.
  `[{"model": "/assets/props/<id>/model", "density_per_100m2": 2, "min_spacing_m": 3}]`.
  `model` is the model URL of an existing prop exactly as `find_props` prints it (no model = a
  grass tuft). `density_per_100m2` = instances per 100 m², above 0 (required unless `place` is
  `"edge"` or `"center"`, which ignore it); `min_spacing_m` above 0 up to 100 (leave it out
  for none). Optional:
  `place` `"edge"` (an even row along the outline, with `offset_m` inside it; it needs
  `min_spacing_m` above 0, the distance between its props) or `"center"`
  (one instance), `yaw_mode` `"aligned"` with `yaw_deg`, `sides` `"longest"` / `"opposite"`.
  The list sent replaces the stored one; `[]` removes it.
- `stroke.along` — rows of props along a stroke's centre line (lamps along a road, trees along a
  river), at most 8: `[{"model": "/assets/props/<id>/model", "spacing_m": 25, "offset_m": 4,
  "side": "both"}]`. `model` is required; `spacing_m` 1–500 (default 20), `offset_m` 0–100 from
  the line (default 0), `side` `"left"` / `"both"` / `"alternate"` (absent = right). A stroke sent
  without `along` keeps the stored rows; `"along": []` removes them.
- `npc_slots` — who should be found here (`read_manual locations`, "NPC slots"): the same
  slot objects as a place's (`role`, `count_min`, `count_max`, `when`, `character`,
  `template`, `briefing`) but without `room` and `radius_m` — both are refused, the area
  itself is the home. An area with slots needs a `label` (it is what the NPCs are told they
  stand in). Slots fill on their own when the player's avatar comes near; there is no fill tool. `[]`
  removes them.
- `water` — only on a water kind (`world_overview` flags them): `{water_level, water_level_up,
  water_level_down, flow_dir_deg, flow_along, flow_speed_m_s, water_depth_m, shore_ramp_m,
  bed_kind}`. A water area drawn as a stroke flows along its line by default (`flow_along
  "forward"` = drawing order; the result says `flows forward`) — send `"flow_along": ""` for
  still water or `"reverse"`. `flow_along` only acts on a stroke and is refused on a polygon:
  a polygon lake stands still unless it gets `flow_dir_deg`. A stroke redrawn as a polygon
  loses its `flow_along` — and, when no `flow_dir_deg` is left, its `water_level_up` /
  `water_level_down` too (it settles as still water on `water_level`).
  `flow_speed_m_s` 0–2; `water_depth_m` 0.2–20 (how deep the bed lies under the surface);
  `shore_ramp_m` 0–20 (how far inside the rim that depth is reached); `bed_kind` is a terrain
  kind painted under the water. The levels are
  derived from the landscape when left out — set them only when the task asks. `""` removes a
  key — also on an area that is no longer a water kind, to clear what it kept.
- `relief_amplitude_m` (0.05–2) and `relief_wave_m` (4–200) — small random hills of this area:
  how high, and how wide one swell is; a wave needs an amplitude. `0` removes the value.

## Props — the library and single props on open ground

`find_props{query?, category?, tag?, mount?}` searches the prop library, one line per prop:
`<id> "<name>" <category> <w>×<d>×<h> m mount <mount> tags <…> model /assets/props/<id>/model`
(`· no mesh yet` when its 3D model is still missing — it is stored, but shows only once the mesh
exists). The `model` URL is what `scatter` and `stroke.along` take; `query` matches id, name,
description and tags, `mount` is `floor`, `wall`, `ceiling` or `surface`.

`place_world_prop{prop_id, x, z, yaw?, offset_y?, variant?}` stands ONE prop at one point of the
open world — a well in a village square, a signpost at a crossing, a lone rock. Use it for single,
deliberate landmarks; a wood or a field of stones is `scatter` on an area, a row of lamps is
`along` on a road. `yaw` 0 up to (not including) 360 degrees, `offset_y` −50 … 50 m (lift or
sink it), `variant` a whole variant index of the prop (leave it out and the placement picks one; an index past
the prop's variant count wraps around to the first again).
`x`/`z` keep two decimals. Values outside these are refused, never rewritten. A world prop is
decoration: nobody walks around it. The result warns when it stands on impassable ground or inside
the outline of a place — furniture of a place goes into its rooms (`furnish_rooms`). A world
holds a limited number of them (the call is refused when it is full). `map_region` lists them as `prop <id> <prop_id> (x,z)`.
`delete_created{kind: "world_prop", id}` removes one this run placed.

## Terrain kinds — new ground

`add_terrain_type{kind, name, color, passable?, speed_factor?, water?, surface?}` adds a NEW kind
to this world when none of the existing ones fits (cobblestone, salt flat, peat bog). Use it only
then: the shipped kinds cover most ground. An existing kind — shipped or the world's own — is
never changed here (that changes every area of it world-wide; the terrain editor does it), so
naming one is refused.
- `kind` — the id: lower-case letters, digits, `_` or `-`, at most 40 characters
  (`demo_cobble`); anything else is refused.
- `name` — what the map shows ("Cobblestone"), at most 60 characters. `color` — `#rrggbb` on the
  schematic map.
- `passable` — `false` for ground nobody can walk on (default `true`). `speed_factor` — walking
  pace 0 … 2 with two decimals (1 = normal, 0.5 = half speed; default 1).
- `water` — makes the kind a water surface: `{}`, or `{"water_depth_m": 2, "shore_ramp_m": 4}`
  for how deep its bed lies and how wide the shore ramp is (the defaults every area of it inherits).
- `surface` — the ground texture, a kind of `list_catalog{name: "surface_kinds"}`; leave it out
  for the default ground.
Every value is stored exactly as sent or refused. The kind is usable at once in
`add_terrain_area`, `water.bed_kind` and a place's `terrain`. `delete_created{kind:
"terrain_type", id: <kind>}` removes one this run added — refused while an area (also as its water
bed) or a place still uses it.

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
  or an earlier one.
- `delete_area{kind: "terrain" | "height", id}` removes ANY area, also one that existed before
  the run (a wood that has to give way to a lake); the discard of the run brings it back
  exactly. An area created in THIS turn is refused there — use `delete_created` for it.

## From a map layout — every map-schema field and its tool

| map layout field | free tool |
|---|---|
| `terrain_areas[]` (kind, label, polygon or stroke, z_order) | `add_terrain_area` with the same keys — a water `stroke` flows forward here unless it sends `"water": {"flow_along": ""}` (still water, as in the map schema) |
| `height_areas[]` (polygon, height_m, falloff_m, label) | `add_height_area` with the same keys |
| `locations[]` with an `id` (pos_x, pos_z, yaw_deg) | `place_location{id, x, z, yaw}` |
| `locations[]` stub (name, description, indoor, danger_level, pos, yaw, boundary) | `create_location{data: {name, description, indoor, danger_level}, x, z, yaw, boundary}` (`read_manual locations`) |
| replace mode (wipe the painted ground first) | `delete_area` per area that has to go — never a blanket wipe |
| `bounds` | stay inside the bounds `world_overview` names |
| `why` / `summary` | your summary of the turn |
