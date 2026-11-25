# Manual: locations

`create_location{data, x?, z?, yaw?, boundary?}` creates a NEW place (a name is not a key: a
second place with the same name is a second place — check `find_locations` first).
`update_location{id, patch}` changes only the keys you send. `place_location{id, x, z, yaw?}`
moves a place on the map.

## Location fields (`data` / `patch`)

- `name` — short, like a signpost (at most 120 characters).
- `description` — 1–2 sentences: what the place is, what it looks like.
- `danger_level` — whole number 0–5: 0 safe, 1–2 mildly risky, 3 dangerous, 4–5 very dangerous.
  From 3 on, characters there lose courage and stamina each game hour. Ordinary places: 0.
- `indoor` — `"indoor"`, `"outdoor"` or `""` (unsure). A string, never true/false.
- `decency` — `"public"` (default), `"private"` or `"nude_ok"`; `""` = public.
- `swim_allowed` — true only where swimming fits (beach, pool, lake shore).
- `style_hint` — optional soft English style word ("cozy rustic", "neon nightclub").
- `activity_hint` — free text in the world's language: what characters typically do here.
- `image_prompt_day`, `image_prompt_night` — ENGLISH prompts for the background image, no
  people, no text. Set both.
- `image_prompt_building` — ENGLISH three-quarter exterior view of the whole building, neutral
  background, no people. Set it whenever the place is or contains a building; empty for open
  terrain (beach, clearing, lake).
- `rooms` — list of rooms; every place needs at least one.
- `map3d` — optional 3D shape: `floors` (whole number > 0), `boundary` (outline, see below)
  and the editor's other keys. Leave it out unless the task needs it.
- `null` means "not given"; it never clears a field.

Access rules (who may enter) are not set here.

`delete_created{kind: "location", id}` removes a place THIS run created — in this turn or an
earlier one; a place that existed before the run is never deleted. Refused while a character
lives there, knows it, has it in the schedule or stands there; in an earlier turn also while the
place has images or 3D models.

## Rooms

Each room: `name` (required), `description` (furnishings, atmosphere, function — in the world's
language), `indoor`, `decency`, `swim_allowed`, `style_hint` (a room value overrides the
place, empty = inherit), `image_prompt_day` / `image_prompt_night` (English), `activity_hint`.

- A new room has NO `id`. Ids starting with `__` belong to the server (ground, corridors).
- In `update_location`, `rooms` is the full room list: send every room you keep WITH its `id`
  (only the keys you change besides it); a stored room you leave out is removed — refused while a
  character stands in it or lives in it.

## Position and outline

- `x`, `z` — the pin, world metres (x east, z south). Give both or neither; `yaw` needs them.
- `boundary` — the ground the place covers, `[[x, z], …]` in metres measured FROM ITS OWN PIN
  (`[0, 0]` is the pin, `[8, 0]` is 8 m east of it), 3–24 points, the ring closes itself, it
  turns with `yaw`. Without one the place is a plain 10 × 10 m square. Draw it when the land has
  a shape (a shore along the lake edge, a yard between two woods).
- Two places must not share ground; leave streets and squares between them. Never place a house
  on impassable ground (deep water, cliff) — see `read_manual map` for the terrain kinds.

## Image prompts are ALWAYS English

Every `image_prompt_*` is English, even when the world speaks another language ("village
square", not "Dorfplatz"). Proper names may stay.
