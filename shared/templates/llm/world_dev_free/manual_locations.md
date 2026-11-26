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
  Any other number is refused.
- `indoor` — `"indoor"`, `"outdoor"` or `""` (unsure). A string, never true/false; any other
  value is refused (also in a room).
- `decency` — `"public"` (default), `"private"` or `"nude_ok"`; `""` = public. Any other
  value is refused.
- `swim_allowed` — true only where swimming fits (beach, pool, lake shore).
- `style_hint` — optional soft English style word ("cozy rustic", "neon nightclub").
- `activity_hint` — free text in the world's language: what characters typically do here.
- `image_prompt_day`, `image_prompt_night` — ENGLISH prompts for the background image, no
  people, no text. Set both.
- `image_prompt_building` — ENGLISH three-quarter exterior view of the whole building, neutral
  background, no people. Set it whenever the place is or contains a building; empty for open
  terrain (beach, clearing, lake).
- `terrain` — the ground kind of the place, one of the world's terrain kinds (`""` = none);
  a value outside them is refused, and the refusal lists them.
- `entry_room` — optional: the room NAME (or id) where one arrives and which one must stand in to
  leave; `""` = arrive on the open ground, leave freely. Only a room of this place (in an update
  also one the same patch adds to `rooms`); the refusal lists the room names. A `rooms` patch
  that drops the current entry room must send `entry_room` too. Leave it out for ordinary places.
- `default_door_style`, `default_window_style` — optional look of the place's doors and windows
  (`""` = default); a value the world does not know is refused, and the refusal lists them.
- `rooms` — list of rooms; every place needs at least one.
- `map3d` — optional 3D shape: `floors` (whole number > 0), `boundary` (outline, see below),
  `footprint`, `style`, `color`, `storey_height_m`, `ground_corridor`. Leave it out unless the
  task needs it. Stairs, plot openings and the building outline are part of the floor plan —
  `set_room_layout` (`read_manual layout`); the other editor keys (elevator, wall kinds, area
  model, hull openings) are set in the floor-plan editor. Both are refused here.
- Every place with rooms needs a floor plan (`set_room_layout`), or it cannot be drawn in 3D.
- `null` means "not given"; it never clears a field.

Access rules (who may enter) are not set here.

## Editor fields (`data` / `patch`)

The value lists come from `list_catalog{name}` (`stats`, `event_categories`, `event_settings`,
`room_types`, `furniture_kits`, `surface_kinds`, `door_props`, `terrain_kinds`,
`item_categories`). A value the editor would clamp, drop or rewrite is refused
(`'<field>' would be stored as … — send that value or leave it out`), never changed silently.

- `stat_rates` — `[{stat, per_hour}]`, at most 10: how a stat changes per game hour while a
  character is here. `stat` one of `list_catalog stats`, `per_hour` a whole number -50…50.
  Also on a room (the room's rate applies there).
- `event_settings` — random events of the place, keys of `list_catalog event_settings`:
  `event_probability` 0…1, `allowed_categories` (of `list_catalog event_categories`, each
  once), `event_blacklist` (words, each once, no empty word, no leading or trailing spaces),
  `max_concurrent_events` (whole 1…10), `event_cooldown_hours` (whole 0…48 game hours),
  `stat_effects` `{category: {stat: whole -100…100}}`. In `update_location` only the keys you
  send change, the other stored keys stay (`stat_effects` is one key: send it whole;
  `stat_effects: {}` clears it). A key cannot be removed: to reset, send the default values
  `list_catalog event_settings` lists. Leave it out for ordinary places.
- `chattiness` — 0…1, how likely a bystander chimes in; `""` = the world value.
- `stat_rates: []` removes every rate (on the place or a room).
- `knowledge_item_id` — an existing item id the place teaches about; `""` = none.
- `default_door_prop_id` — the door every door opening of the place uses (one of
  `list_catalog door_props`); `""` = none.
- `npc_slots` — the temporary-NPC slots of the place, see "NPC slots" below.

`delete_created{kind: "location", id}` removes a place THIS run created — in this turn or an
earlier one; a place that existed before the run is never deleted. Refused while a character
lives there, knows it, has it in the schedule or stands there; in an earlier turn also while the
place has images or 3D models.

## NPC slots

A slot says "someone of this role is found here": the staff of a tavern or shop, guards at a
gate, a market crowd, fishers on a pier. Its NPCs are anonymous temporary characters, generated
when needed and recycled later. Slots fill on their own when the player's avatar comes near —
there is no fill tool, and nothing is spawned when you write a slot.

- A slot fits people who matter for what they do ("a barmaid", "two guards", "three to six
  market visitors").
- A person who matters by name — with a home, a daily schedule and relationships (the
  innkeeper everyone knows, the village elder) — is a full character: `create_character`
  (`read_manual characters`), with this place as home or schedule place. Not a slot.

`npc_slots` is the WHOLE list of the place's slots — in `update_location` send every slot you
keep; `[]` removes every slot: `[{role, count_min?, count_max?, when?, room?, radius_m?,
character?, template?, briefing?}]`. A value the slot store would rewrite is refused
(`'npc_slots[<i>].<key>' would be stored as …`), never changed silently.

- `role` (required) — short ("barmaid", "gate guard"). One slot per role (case-insensitive);
  the counts say how many.
- `count_min` — how many must be there, whole 0…20, default 1. `count_max` — the most there
  ever are, whole 0…20, at least `count_min`; default the larger of `count_min` and 1.
- `when` — when the slot is open: `""` always (default), `"day"` or `"night"` (the season's
  sun), or `"HH:MM-HH:MM"` game time with two-digit hours and minutes (`"22:00-05:00"` spans
  midnight; start and end must differ — an equal pair such as `"12:00-12:00"` never opens).
  Lowercase; any other word is refused. Outside its window a slot wants nobody.
- `room` — a STORED room id of the place (not the ground or a storey corridor, ids `__…`;
  `""` = anywhere). Room ids exist only after the place is created, so add a slot with a room
  through `update_location`; a `rooms` patch that removes a slot's room must send
  `npc_slots` too.
- `radius_m` — whole metres, 0 (default) = in a room. Above 0 the NPCs stand at free spots
  within that distance of the place and roam there (a guard post, a herdsman); it wins over
  `room`, so send one or the other.
- `character` — binds the slot to ONE existing temporary NPC (the full name): only that NPC
  staffs it, nothing is generated for it, so its counts are 0 or 1.
- `template` — one of the character templates (`""` = the NPC pipeline's default; the refusal
  lists them). `briefing` — a sentence or two on what the NPCs of this slot do here.

Painted areas carry slots too (`read_manual map`).

## Rooms

Each room: `name` (required), `description` (furnishings, atmosphere, function — in the world's
language), `indoor`, `decency`, `swim_allowed`, `style_hint` (a room value overrides the
place, empty = inherit), `image_prompt_day` / `image_prompt_night` (English), `activity_hint`,
`image_prompt_building` (English, the room seen as a model source; empty = its description),
`room_type` (one of `list_catalog room_types`, `""` = none — furnishing needs it),
`stat_rates` (as on the place), `ambience` `{daylight 0…1, tint? "#rrggbb"}` (lowercase tint;
daylight 1 without a tint is the default — leave `ambience` out then; `ambience: {}` clears a
stored one back to the default).

- A new room has NO `id`. Ids starting with `__` belong to the server (ground, corridors).
- In `update_location`, `rooms` is the full room list: send every room you keep WITH its `id`
  (only the keys you change besides it); a stored room you leave out is removed — refused while a
  character stands in it or lives in it.

## Room items

`add_room_item{location_id, room_id, item_id, quantity?, hidden?, discovery_difficulty?, note?}`
lays a catalog item (`find_items`; reuse an id, `create_item` only for a new kind of thing) in a
room — also the ground or a corridor. The same item again adds to its quantity; a
`hidden` / `discovery_difficulty` (whole 0…999: how hard a hidden item is to find) / `note` you
send replaces the stored one, one you leave out keeps it. An
item that reveals a secret is refused.

## Position and outline

- `x`, `z` — the pin, world metres (x east, z south). Give both or neither; `yaw` needs them.
- A new place drawn on the map (the map schema's stub: name, description, spot, outline) is
  `create_location{data: {name, description, indoor, danger_level}, x, z, yaw, boundary}`;
  rooms and the rest follow with `update_location` / `set_room_layout`.
- `boundary` — the ground the place covers, `[[x, z], …]` in metres measured FROM ITS OWN PIN
  (`[0, 0]` is the pin, `[8, 0]` is 8 m east of it), 3–24 points, the ring closes itself, it
  turns with `yaw`. Without one the place is a plain 10 × 10 m square. Draw it when the land has
  a shape (a shore along the lake edge, a yard between two woods).
- Two places must not share ground; leave streets and squares between them. An outline that
  overlaps another place's is stored, but the result ends
  `; warnings: '<new>' overlaps place <id> "<name>"` — move one of them (`place_location`) unless the overlap is meant (a stall on a square).
- A pin on impassable ground (deep water, rock — the kinds `world_overview` marks
  `impassable`) is refused in `create_location` and `place_location`: pick a spot on walkable
  ground. Turning a place where it stands (`place_location` with its own `x`, `z` and a new
  `yaw`) is never refused for its ground. An outline that encloses no area (all points on one
  line) is refused. A new `map3d.boundary` in `update_location` is checked for overlaps too. `map_region` shows each place's outline box and the ground under its pin
  (`· outline (x0,z0)-(x1,z1) · on <kind>`).

## Image prompts are ALWAYS English

Every `image_prompt_*` is English, even when the world speaks another language ("village
square", not "Dorfplatz"). Proper names may stay.
