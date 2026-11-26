# Manual: homes and daily schedules

A character's home is the place where it lives and sleeps; it starts there. The daily schedule
tells it where to be at which game hour.

## Spellings

- `create_character`: the arguments `home`, `home_room`, `schedule`, `known_places` (or, inside
  `data`, `home_location`, `home_room`, `daily_schedule`, `known_places` — never both spellings
  for one value).
- `update_character` patch: ONLY `home`, `home_room`, `schedule`, `known_places`. They cannot be
  cleared here: an empty `home` or `home_room` and an empty `schedule` list are refused (in
  `create_character` too) — leave the key out instead.

## Values

- `home` — a place of this world, by id (`loc_…`) or exact name. A place that does not exist is
  refused — create it first, then the character.
- `home_room` — one room of that home, by exact room name or id. A room alone (without `home`)
  refers to the character's stored home.
- `schedule` — a list of slots, one per game hour 0–23:
  `{"hour": 9, "location": "<place id or name>", "role": "<what it does there>"}` or
  `{"hour": 23, "sleep": true}` for the sleeping hours. `hour` is a whole number 0–23 and each
  hour appears at most once; a slot needs a `location`, a `role` or `"sleep": true`, and a sleep
  slot takes no `location` or `role`. An empty or blank `location` is refused — leave the key out. A schedule that breaks one of these rules is refused as a
  whole. `role` is in the character's language. Cover the whole day — an hour left out is
  decided freely by the character. It must fit the character's tasks and rhythm (a baker starts
  early, a tavern keeper works late).

## Known places

A character travels only to places it knows. Its home and every place of its schedule are known
automatically. `known_places` — a non-empty list of place ids or exact names — adds more; it only
adds, it never removes a place (removing is done in the character editor). Give villagers the
places they share: the square, the market, their neighbours' houses. `get_character` shows how
many places a character knows.

Every place a schedule names must exist. A place that is still some character's home, known
place or schedule slot cannot be removed with `delete_created`.
