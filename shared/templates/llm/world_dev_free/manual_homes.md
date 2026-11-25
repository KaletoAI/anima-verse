# Manual: homes and daily schedules

A character's home is the place where it lives and sleeps; it starts there. The daily schedule
tells it where to be at which game hour.

## Spellings

- `create_character`: the arguments `home`, `home_room`, `schedule` (or, inside `data`,
  `home_location`, `home_room`, `daily_schedule` — never both spellings for one value).
- `update_character` patch: ONLY `home`, `home_room`, `schedule`. They cannot be cleared here.

## Values

- `home` — a place of this world, by id (`loc_…`) or exact name. A place that does not exist is
  refused — create it first, then the character.
- `home_room` — one room of that home, by exact room name or id. A room alone (without `home`)
  refers to the character's stored home.
- `schedule` — a list of slots, one per game hour 0–23:
  `{"hour": 9, "location": "<place id or name>", "role": "<what it does there>"}` or
  `{"hour": 23, "sleep": true}` for the sleeping hours. `hour` is a whole number; `role` is in
  the character's language. Cover the whole day — an hour left out is decided freely by the
  character. It must fit the character's tasks and rhythm (a baker starts early, a tavern keeper
  works late).

Every place a schedule names must exist. A place that is still some character's home, known
place or schedule slot cannot be removed with `delete_created`.
