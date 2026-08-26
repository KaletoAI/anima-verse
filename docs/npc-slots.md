# NPC slots, home areas and time windows

A **temporary NPC** is a throwaway character: no memory, no relationships, no
autonomous thoughts, one standing task, and a lifetime measured in game hours.
The world fills itself with them through **slots** — a declaration on a place
or on a painted area that says "this spot wants a barkeeper".

This page is the reference for authoring those slots and for the settings that
bound them. The mechanics live in `app/core/npc_spawn.py` (slots, approach
trigger, wanderers), `app/core/npc_home.py` (home areas),
`app/core/npc_windows.py` (time windows) and `app/core/npc_pool.py`
(recycling).

## The slot object

The same object is authored on two surfaces (see below) and has these keys:

| key | type | default | meaning |
| --- | --- | --- | --- |
| `role` | string | — | The slot's identity. Required: without it the slot cannot be counted, filled or recycled. It is stamped on the NPC as `npc_slot_role`, and a pool hit is matched on it. |
| `template` | string | `""` | The character template a sheet must have to fill this slot. `""` = any temporary NPC. Keeps an animal slot from being handed a human. |
| `count_min` | int 0…20 | `1` | How many NPCs of this role the place wants. The gap the spawn tries to close. |
| `count_max` | int 0…20 | `count_min` | The ceiling. Raised to `count_min` when an author inverts the two. |
| `briefing` | string | `""` | One line of prose the generator is given ("a weary barkeeper who has run this place for thirty years"). |
| `room` | string | `""` | Which room of the location the NPC stands in. LOCATION slots only. |
| `radius_m` | int ≥ 0 | `0` | The slot's HOME AREA. `0` = the room placement above; above 0 the NPC stands at a free point within that many metres of the place and roams there. Wins over `room`. LOCATION slots only. |
| `when` | string | `""` | The slot's time window (see below). |

Nothing here raises. `normalize_slot` runs inside the location save, so every
unusable value falls back with a warning in the log — an unreadable `when`
becomes "always", an unreadable count or radius the default. That includes the
JSON literal `Infinity`, which `int()` rejects with `OverflowError` rather than
`ValueError`.

Roles are unique **per surface**: one slot per role on a location, one per role
on an area. The two counts never see each other — an NPC carries either
`npc_slot_location` or `npc_slot_area`, never both — so the same role name may
appear on a place and on an area and describes two independent slots.

## The two surfaces

**A location** carries its slots in `npc_slots` on the location itself (World
tab → the location's NPC-slot editor). Its NPC is placed into `room`, or —
with `radius_m` above 0 — at a free point around the place.

**A painted terrain area** carries them in `meta.npc_slots` (Map tab → select
an area → its slot editor). Its NPC has no location and no room at all: the
polygon itself becomes its home (`npc_home` of kind `area`), and it roams
inside it. `room` and `radius_m` are forced empty on this surface — the
polygon already is the home area.

An area with slots **must have a label**. This is the only thing the whole
area sanitizer refuses rather than repairs (`ValueError`, HTTP 400 at the
save): the label is what the generator's briefing calls the place ("They are
the poacher of the Hunting Ground, out in the open — no house, no room") and
what the roaming prompt and the Game-Admin list render. An area named `""`
cannot be described to an LLM at all.

## Time windows (`when`)

Four forms, and nothing else. All in **game** time.

| value | meaning |
| --- | --- |
| `""` | always — the slot has no time condition |
| `"night"` | outside the season's sunrise…sunset |
| `"day"` | inside it |
| `"HH:MM-HH:MM"` | a literal span, half-open, **wrapping over midnight** (`"22:00-04:00"` is six hours) |

`night` and `day` are the world calendar's own definition — the season's
sunrise and sunset, so a world with long winter nights gets long winter nights
for free. It is the same answer the `night`/`day` rule condition asks; there is
no second copy of that comparison.

A window governs both directions: outside it nothing spawns for that slot, and
the NPCs already standing there are pooled by `npc_ops.sweep_closed_windows`.
A slot whose window is shut therefore leaves no NPC behind when the hour comes.

Spans are stored canonically (`"8:00-12:00"` → `"08:00-12:00"`), so the editor
round-trip has one shape.

## When a slot is filled

The **approach trigger** runs inside an accepted position report: when the
avatar comes within `npc.spawn_radius_m` of a place or a slot-bearing area
(distance 0 anywhere inside the polygon, so "standing in the wood" and
"walking up to it" are one comparison), a spawn job is queued — at most one per
object per `npc.spawn_cooldown_game_minutes` of game time.

The job then counts: a slot is filled when enough LIVING NPCs carry its tag.
NPCs the finish gate is still holding back count too — their assets are already
paid for and they will walk in by themselves. For each gap the job takes a
**pool hit** of the same role first (a finished character sheet, no LLM turn at
all) and only runs the three-stage generation pipeline when the pool has
nobody.

## NPC settings (`/admin/settings → NPCs (automatic)`)

| key | default | meaning |
| --- | --- | --- |
| `npc.auto_spawn_enabled` | `true` | Off = temporary NPCs are created by hand only. |
| `npc.max_alive` | `10` | Hard cap on temporary NPCs in the world at once — held-back ones included. |
| `npc.max_pool_size` | `50` | Size of the recycling pool (FIFO). On overflow the longest-pooled sheet is deleted for good, with its images and 3D model. |
| `npc.wanderer_quota` | `3` | Travelling NPCs kept walking between known places. They count towards `max_alive`. |
| `npc.spawn_radius_m` | `150` | How close the avatar has to come (world metres). |
| `npc.spawn_cooldown_game_minutes` | `10` | Minimum game time between two spawn checks of the same place. |
| `npc.slot_ttl_game_hours` | `12` | Game hours a slot NPC lives before the sweep pools it. `0` = until an admin removes it. |
| `npc.wanderer_ttl_game_hours` | `24` | Game hours a wanderer lives even if it never arrives. |
| `npc.require_assets` | `true` | An NPC enters the world only once it has a profile image, a 3D model for its worn outfit, an outfit description and a default expression variant. Until then it waits in the pool while a background job renders the missing pieces, and the Game-Admin pool row says what it is waiting for. |
| `npc.action_tick_enabled` | `true` | Let living NPCs change room and activity on their own, guided by a small LLM turn. |
| `npc.action_interval_game_minutes` | `30` | Minimum game time between two action turns of the SAME NPC. |
| `npc.action_batch` | `2` | How many NPCs at most get an action turn in one check — the cap on what the tick costs per minute. |

## The action tick and roaming

A living temporary NPC gets an action turn every
`npc.action_interval_game_minutes`, at most `npc.action_batch` per check. The
turn has two variants:

* **Room variant** — the NPC is asked which room of its location it moves to
  and what it is doing there.
* **Home variant** — an NPC with `npc_home` is asked only what it is DOING; the
  tick then walks it to a fresh random point of its own home area (a point
  journey, so its position is a pure function of the game clock like every
  other journey).

Not a candidate: a sleeping NPC, one mid-journey, one in a conversation with an
avatar, and — for the home variant — anyone in a **party**. A follower is
dragged along by its leader and loses its own travel; a leader's roaming
journey to a free point would move it and nobody else and strand its followers
where they set out from.

## The `activity_home_enabled` template feature

`shared/templates/character/npc-temporary.json` declares
`features.activity_home_enabled: false`. A temporary NPC gets its timing from
its slot's window and its whereabouts from its home area, so a per-character
daily schedule and a per-character home location would be a second,
contradicting source of both.

The gate closes every surface at once:

* the Game-Admin "Activity & Home" sub-tab is hidden;
* `save_character_daily_schedule` refuses the write, which closes the
  `POST /scheduler/daily-schedule` route, the DELETE asymmetry and the
  `schedule:` rule condition that reads those rows;
* `SchedulerManager.sync_daily_schedule` writes no jobs;
* `POST /characters/{name}/home-location` answers 409.

It is fail-open and it is the FEATURE, not the template name: a per-character
config override switches the whole subject back on for one NPC.

## `place_labels` — for plugin authors

The NPC generation schema (`shared/world_dev_schemas/npc_character.md`) has two
header lines the model reads as "where this NPC belongs": a location name and a
room name. `npc_ops.build_npc_schema_text` and `generate_npc_blocking` accept a
`place_labels=(place, room)` pair that replaces both. An area-anchored NPC has
no location id and no room, so it passes its area's label plus an explicit
`"(none — this NPC stands outdoors, not in a building)"` — spelled out rather
than left blank, so the model does not invent an interior for an NPC that lives
on open ground. A plugin that spawns NPCs somewhere the world model has no id
for uses the same door.
