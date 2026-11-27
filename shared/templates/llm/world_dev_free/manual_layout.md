# Manual: layout

`set_room_layout{location_id, layout}` writes the FLOOR PLAN of one place: where each room stands
inside the place's outline, how big it is, which walls carry doors and windows, how storeys
connect and where one walks onto the plot. Get the room ids first with
`get_location{id, fields: ["rooms", "map3d"]}`.

The plan is written as a whole, but only for the rooms it names: a room you omit keeps what it
had. A room you name gets its layout REPLACED by the one you send (send its whole layout, not a
patch) — only its geometry: the furniture, figure spots and model anchor other editors placed in
it (`props`, `markers`, `model_at`, `model_offset_y`) stay, and a plan may not send them (place single props with `place_room_prop`, whole kits with `furnish_rooms`). A plan never removes a room — use `update_location` for that.

## Coordinates

Metres, in the place's own frame — the same frame as its `map3d.boundary` (the outline you gave
`create_location`, measured from the place's pin):

- `x` grows to the **east**, `y` grows to the **south** (the place's own z). Negative values are
  normal: the origin is the pin.
- A room is placed by its **minimum corner** (`x`, `y`) plus its size (`w` east–west, `d`
  north–south). `x: -2, y: 1, w: 4, d: 3` covers x −2…2 and y 1…4.
- `level` stacks storeys: `0` ground floor, `1` the floor above, `-1` a cellar. Rooms on
  different levels may stand on top of each other; rooms on the SAME level must not.

Real sizes (a person is 1.70 m tall; keep rooms within realistic `max_m2` guidelines — larger rooms trigger a warning and furnish poorly):

| room | typical | max_m2 guideline |
|---|---|---|
| bathroom | 2 × 2.5 m | 15 m² |
| bedroom, study | 3 × 4 m | 25 m² |
| kitchen, hall, storage | 3 × 4 m / 1.5–2 m wide | 30 m² |
| living room / parlour | 5 × 6 m | 45 m² |
| dining room | 5 × 6 m | 50 m² |
| workshop | 8 × 10 m | 100 m² |
| tavern / taproom | 8 × 10 m and up | 200 m² |
| door | 0.9 m wide, 2.1 m high | — |
| double door / gateway | 1.8–3 m wide | — |
| window | 1.2 m wide, 1.4 m high, sill 0.9 m | — |

## `layout`

```json
{
  "summary": "Taproom at the front, kitchen behind it, a guest room upstairs.",
  "entry_room": "r1a2b3c4",
  "rooms": [
    {"id": "r1a2b3c4", "x": -8, "y": -6, "w": 8, "d": 6, "level": 0, "room_type": "tavern",
     "openings": [
       {"edge": 2, "at": 0.5, "width_m": 1.2, "type": "door", "to": "outside"},
       {"edge": 1, "at": 0.5, "width_m": 0.9, "type": "door", "to": "r9f8e7d6"},
       {"edge": 0, "at": 0.3, "width_m": 1.2, "height_m": 1.4, "sill_m": 0.9, "type": "window"}]},
    {"id": "r9f8e7d6", "x": 0, "y": -6, "w": 4, "d": 6},
    {"name": "Guest room", "description": "A low chamber over the taproom.",
     "x": -8, "y": -6, "w": 5, "d": 6, "level": 1}
  ],
  "stairs": [{"at": [-7.4, -5.5], "from_level": 0, "dir_deg": 0}],
  "storey_height_m": 3
}
```

Allowed keys: `rooms` (required), `entry_room`, `boundary_openings`, `stairs`,
`storey_height_m`, `summary` (a note on what the plan does; it is not stored). The plan writes the
building contour (`map3d.outline` / `level_outlines`) from its CLOSED rooms automatically: closed
rooms of one place must form ONE building (touching walls, no gaps or holes, and an upper storey
standing on the one below) or the plan is refused. Open rooms (`open: true`) are not part of the
contour. Room edges closer than 0.3 m are aligned to each other automatically and the result line
says when rooms moved.

### `rooms`

- `id` — an EXISTING room id, copied exactly. Or instead `name` (+ `description`, 1–2 sentences)
  for a NEW room; a name that matches an existing room edits that room's layout. Never both.
  A plan writes no name or description of an existing room — `update_location` does.
  The ground and the storey corridors (ids `__…`) carry no layout.
- `x`, `y`, `w`, `d` — metres, `w` and `d` greater than 0. `level` — default 0.
- `room_type` — optional, one of `list_catalog room_types` (furnishing needs it).
- `open` — `true` (a boolean) for an open sub-area (yard, terrace, market stall): no walls, visible from
  outside. Default `false` = a closed room. Outdoor rooms (`open: true`) of a square get their props
  via `place_room_prop`.
- `surfaces` — give every CLOSED room `surfaces` `{"floor": "<kind>", "wall": "<kind>"}` from
  `list_catalog surface_kinds` — without them the floor is plain `wooden_floor` and the walls have
  no texture. Pick by the building's style: e.g. a log house `wooden_floor` / `log_wood`, a kitchen
  or storeroom `dark_stone` / `fieldstone`, a town house `tiled_floor` / `plaster_infill`. Open
  rooms may carry a floor kind too.
- `outline` — optional, instead of a plain rectangle: 3–32 points in metres relative to the
  room's own minimum corner (spanning 0…`w`, 0…`d`), first point not repeated.
- `openings` — a list of the holes in THIS room's walls, one object each:
  - `edge` — which wall: `0` north, `1` east, `2` south, `3` west (with an `outline`,
    edge `i` runs from point `i` to point `i+1`).
  - `at` — where the opening's centre sits along that wall, `0`…`1` (0.5 = middle), measured from
    point `i` to point `i+1` of the edge: on a rectangle, edge `0` (north) runs west→east, edge `1`
    (east) runs north→south, edge `2` (south) runs **EAST→WEST** (so `at` 0.2 on edge `2` is near
    the EAST end), and edge `3` (west) runs south→north.
  - `width_m`, `height_m` — 0.4…10 m; `sill_m` 0…3 m. `type` `"door"` (default),
    `"window"` or `"passage"`. A missing height/sill gets the sizes of the table above
    (door/passage 2.1 m high, sill 0; window 1.4 m high, sill 0.9 m).
  - `to` — optional: the room on the other side (an id, or `"outside"`). A house's entrance is an
    OUTSIDE DOOR on the room edge the plan says (`"to": "outside"`).
  **Doors connect ADJACENT rooms**: put the door on the wall two rooms share, at an `at`
  inside the shared stretch. One door in the shared wall suffices for both rooms — it is
  mirrored onto the neighbour's wall automatically.

### `boundary_openings` — gates in a fence around a plot

`boundary_openings` are **gates in a fence** around a plot — use them ONLY when the plot is fenced
(a yard with a fence and a gate, a walled market). Once a place has any `boundary_openings`, people
can enter its plot ONLY through those openings. A house without a fence has NO `boundary_openings`;
the building is entered through its outside doors (`"to": "outside"`), never through a boundary
opening.

Each entry is an object in a list (a single gate is a list of one): `edge` = index into
`map3d.boundary` (edge `i` runs from point `i` to point `i+1`), `at` `0`…`1`, `width_m` from 0.5 m
up to the plot's width. Where one arrives follows from where one stands (the plot's ground or an open
room there). Sending the list replaces the stored one; leave it out to keep what is there.

Fenced-yard example:

```json
{
  "rooms": [{"id": "r_yard", "x": -6, "y": -6, "w": 12, "d": 12, "open": true}],
  "boundary_openings": [{"edge": 2, "at": 0.5, "width_m": 3}]
}
```

### `stairs` — one entry per flight

- `at` — the foot of the flight, `[x, y]` in the same frame as the rooms.
- `from_level` — the storey it starts on; it always leads to the storey directly above
  (ground floor to second floor = two flights). A cellar stair is `from_level: -1`.
  `stairs` is always a list, also for one flight.
- `dir_deg` — the climbing direction, exactly `0` (+y, south), `90` (+x, east), `180`
  (−y, north) or `270` (−x, west).
- A flight is about 1.2 m wide and needs about 3.9 m of floor in its direction (at a 3 m storey
  height): along a wall or in a hallway, not through the middle of a room. At most 8 per place.
  Every room on a level other than 0 needs a flight that reaches its storey.
- Sending the list replaces the stored one; leave it out to keep what is there.

### `entry_room`, `storey_height_m`

- `entry_room` — the arrival room for travel, teleport and scheduler (an id, or the `name` of a
  room this plan creates). Pick one that touches the outside — a hallway, taproom, yard.
- `storey_height_m` — the height of one storey in metres, 2.6…4.5 (absent = 3).

## What is refused, what warns

Nothing is changed silently. The whole call is REFUSED (nothing written) when the plan would
lose a part: a room id the place does not have, a ground/corridor id, a room named twice, a room
with neither id nor name (or both), an unusable rectangle or `outline`, an unknown surface kind,
an opening, plot opening or stair flight the editor would drop, an opening `type` other than
door/window/passage, an unknown entry room, a plot opening `room` that is no room, an unknown
`room_type` (see `list_catalog room_types`), a `description` on an existing room, a
`storey_height_m` outside 2.6…4.5, a `boundary_openings`/`stairs`/`openings` that is no list (or an
opening that is no object), an `open` that is no boolean, `props`/`markers`/`model_at`/`model_offset_y` on a
room, a new room name over 120 characters. It is also refused when a value you send would be stored
differently — a key the plan does not know, a level that is no whole number, a size or position
outside its range (`at` 0…1, `sill_m` 0…3, a plan coordinate beyond ±500 m): the refusal names
the value it would store. Only rounding to the centimetre passes. The first refusal of a plan
lists every dropped part — fix them all and send the plan again.

The whole call is also REFUSED when two rooms on the same level overlap (whether both are
in the plan or one is an omitted stored room).

The plan is written but the result ends `; warnings: …` for states of a plan in progress: a
room reaching over the place's outline, a room larger than its `room_type`'s `max_m2` guideline,
a door `to` a room that is not there (kept as a plain hole), a place without an outline, a stair
flight from or onto a level without rooms, a level other than 0 that no flight reaches (a level
above 0 needs a flight from the level below it; a cellar level a flight from itself). Fix them
with another `set_room_layout` unless meant.

After a successful `set_room_layout`, `furnish_rooms` or `place_room_prop`, the result also ends
`; findings: …` whenever the composed 3D scene reports reachability or furnishing issues (such as
`room_unreachable`, `prop_in_doorway`, `prop_outside_room`, ceiling/wall placement defects). Read
the `findings` and fix them.

## Rules

- Rooms on the same level must NEVER overlap.
- Every closed room needs a way in (a door or passage; one door in a shared wall suffices for both
  adjacent rooms); every storey needs a way up.
- Keep rooms within realistic sizes (`max_m2` guidelines above); smaller rooms furnish better.
- Keep the plan inside the outline; a plan much larger than the place is wrong.
- A place with rooms but no floor plan is reported by `check_run` as `no floor plan`: it
  cannot be drawn in 3D.

### `build_hull` — the outer shell

`build_hull{location_id, style, roof_form?}` requests the building's outer shell (facade, roof,
windows) in a fixed style:

- Requires a floor plan with at least one closed room first (`set_room_layout`).
- `style` — one of `list_catalog hull_styles` (refused otherwise).
- `roof_form` — optional (`gable`, `hip`, `shed`, `flat`, within the style's allowed roof forms).
- Builds nothing during the turn — Blender builds it locally after the turn when media are on, and
  it costs no LLM or GPU. A later `set_room_layout` in this run rebuilds it.
- Replaces the image-based 3D model of the place. Call it once per house after `set_room_layout`
  and before `furnish_rooms`.

## Furnishing: `furnish_rooms{location_id, kit}`

Fills the EMPTY rooms of a place with furniture from a kit (`list_catalog furniture_kits`: the
kit ids and, per room type, the roles a kit cannot fill). Deterministic and immediate — no
image or model generation. A room is furnished only when it has:

- a `room_type` (`list_catalog room_types`; set it with `update_location` or in the plan),
- a floor plan (`set_room_layout` first),
- no furniture yet — a furnished room is left alone, never refurnished.

The call is refused when no room qualifies; the refusal names every room with its reason. The
result names the furnished rooms with their piece count, the roles the kit had no piece for, and
the rooms it skipped, followed by `; findings: …` if any 3D scene findings remain — read and fix
them. Call it once per place after its floor plan stands. There is no LLM
furnishing here — the building panel does that; the hull is `build_hull`. To stand ONE library prop in a room (a
statue, a rug, a bench — even in a room that already has furniture), use `place_room_prop`
(`find_props` lists the library; name missing props under *left open*, never create an item
instead).
