# NPC slots, home areas and time windows

A **temporary NPC** is a throwaway character: no memory, no relationships, no
autonomous thoughts, one standing task, and a lifetime measured in game hours.
The world fills itself with them through **slots** — a declaration on a place
or on a painted area that says "this spot wants a barkeeper".

This page is the reference for authoring those slots and for the settings that
bound them. The mechanics live in `app/core/npc_spawn.py` (slots, approach
trigger, wanderers), `app/core/npc_home.py` (home areas),
`app/core/npc_windows.py` (time windows) and `app/core/npc_pool.py`
(recycling). The finish gate that holds an NPC back until its assets exist is
`app/core/npc_assets.py`; the admin routes are `app/routes/npc.py`. Checks:
`scripts/smoke_npc_*.py` (spawn, home, windows, actions, assets, conversation,
pool_size, skills, templates, ttl, addressable) and
`scripts/smoke_temporary_npc.py`.

## The slot object

The same object is authored on two surfaces (see below) and has these keys:

| key | type | default | meaning |
| --- | --- | --- | --- |
| `role` | string | — | The slot's identity. Required: without it the slot cannot be counted, filled or recycled. It is stamped on the NPC as `npc_slot_role`, and a pool hit is matched on it. |
| `template` | string | `""` | The character template a sheet must have to fill this slot. `""` = any temporary NPC. Keeps an animal slot from being handed a human. **The slot editor has no field for it** — today it is reachable through the API or a content pack only. |
| `count_min` | int 0…20 | `1` | How many NPCs of this role the place wants. The gap the spawn tries to close. |
| `count_max` | int 0…20 | `max(count_min, 1)` | The ceiling. Raised to `count_min` when an author inverts the two. Note the floor: a slot with `count_min: 0` and no `count_max` gets `1`. |
| `briefing` | string | `""` | One line of prose the generator is given ("a weary barkeeper who has run this place for thirty years"). |
| `room` | string | `""` | Which room of the location the NPC stands in. `""` is not "roomless": the NPC goes to the location's arrival room (`world.get_arrival_room_id`), which the editor offers as „— arrival room —". LOCATION slots only. |
| `radius_m` | int ≥ 0 | `0` | The slot's HOME AREA. `0` = the room placement above; above 0 the NPC stands at a free point within that many metres of the place and roams there. Wins over `room`. LOCATION slots only. |
| `when` | string | `""` | The slot's time window (see below). |
| `character` | string | `""` | BINDS the slot to one existing temporary NPC (see below). `""` = the ordinary pool-or-generate path. |

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
all) and only generates when the pool has nobody. The generation pipeline is
generate → validate → repair → apply; the automatic path **skips the LLM
validator** and runs one generate turn plus, if the sheet is rejected, one
repair turn.

**A frozen world spawns nobody.** The check runs in the worker, not in the
position report: the job is queued as usual and returns `{"skipped": "world
frozen"}`.

## Binding a slot to one NPC (`character`)

A slot may name **one existing temporary NPC** instead of describing a kind of
person (World tab or Map tab → the slot's "Character" select, which lists the
living NPCs and the pooled sheets together). That slot then takes neither of
the two roads above: it is staffed with that sheet and **never generates
anybody**. Only temporary NPCs can be bound — a full character has a place of
its own in this world and is not a sheet a slot may move around.

What happens depends on where the NPC is when the spawn check runs:

* **pooled** → it is revived directly, bypassing the role-matched pool draw.
  That draw skips a `npc_permanent` sheet on purpose, so a binding is the one
  documented way such a sheet comes back — and it keeps its empty lifetime;
* **alive somewhere else** → the slot's stamps are written on it and it is
  moved here. It is **not** pooled on the way, so nothing is erased: what the
  other characters remember about it and its own conversation stay;
* **already standing in this slot** → nothing happens at all;
* **waiting for its assets** → this pass does nothing; the finish job places
  it;
* **not a temporary NPC any more** (deleted, or a full character) → the slot
  stays empty, with a warning in the log. It never falls back to generating a
  stand-in: the point of naming somebody is that nobody else will do.

Everything else about the slot applies unchanged. Its **time window** closes
over the bound NPC like over any other (`sweep_closed_windows` pools it at
closing time and the next open window brings the very same sheet back), and its
**home area** — `radius_m` or the polygon — is where the NPC is placed and
roams.

The **counts** collapse: a bound slot is at most `1/1`, because there is only
one of her. An authored `count_min: 3` would report a gap that can never close.
`count_min: 0` survives — that is still "wants nobody right now".

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
| `npc.conversation_mode` | `turns` | How temporary NPCs talk to each other at a place the avatar is at. `turns`: the action tick may open a conversation and the replies run one turn at a time (task `npc_talk`). `scene`: one small director call writes a short exchange per room (task `npc_scene`). `off`: NPCs only answer when addressed. |
| `npc.scene_interval_game_minutes` | `45` | Minimum GAME time between two director scenes in the SAME room (scene mode). |
| `npc.scene_batch` | `1` | How many rooms at most get a director scene in one check. |
| `npc.scene_max_npcs` | `3` | Participants of one director scene. |

## Lifetime: slot TTL, or the NPC's own setting

`npc.slot_ttl_game_hours` is the default. A single NPC can override it in
**Character config → Temporary NPC → Lifetime**, which knows three modes:

* `default` — the world setting applies;
* `custom` — `lifetime_hours` game hours instead;
* `permanent` — `npc_permanent` is written and `expires_at` cleared.

A permanent sheet is never TTL-swept, never drawn from the role-matched pool,
invisible to the pool cap, and not pooled when a wanderer arrives. Binding a
slot to it (`character`) is the documented way to bring it back.

## Wanderers

`npc.wanderer_quota` NPCs are kept walking between known places; they count
towards `npc.max_alive` and live at most `npc.wanderer_ttl_game_hours`. The
wanderer tick settles arrivals first and then queues at most **one** new
wanderer. On arrival the NPC either turns around towards a new place or is
pooled — a coin flip, except that a permanent wanderer always turns around and
one that is currently in a conversation is left standing.

## How often the server looks

The settings above are in GAME minutes and hours; these are the REAL intervals
at which the server checks them (`app/core/periodic_jobs.py`):

| Job | Every |
| --- | --- |
| TTL sweep (`npc_ops.sweep_expired_npcs`) | 3600 s |
| Time-window sweep (`npc_ops.sweep_closed_windows`) | 120 s |
| Wanderer tick | 300 s |
| Action tick | 60 s |
| Director scenes | 60 s |

## Admin actions and the `/npc` API

`app/routes/npc.py` (all admin):

| Route | What it does |
| --- | --- |
| `GET /npc/list` | Living and pooled temporary NPCs, with what a held-back one is waiting for |
| `POST /npc/sweep` | Run the TTL and window sweeps now |
| `POST /npc/{name}/pool` | Pool this NPC by hand |
| `POST /npc/slots/{location_id}/fill` | Run the slot check of one location now — the same check the approaching avatar triggers. This is the editor's **"Fill now"** button |
| `POST /npc/areas/{area_id}/fill` | The same for a painted area |
| `POST /npc/generate` | The manual generation dialog (SSE) |

## When an NPC goes away

Pooling (`npc_pool.pool_npc`) and deleting (`character.delete_character`) run
the same detach sequence, and in this order: traces in other characters'
memories are cleaned up, then **party → journey → pair interaction** are ended
through each engine's own public entry, then the NPC is unplaced. Pooling then
scrubs the profile (`expires_at`, `npc_wanderer`, `npc_home`, a
`npc_pooled_reason`) and sets the character status to pooled; deleting goes on
to wipe every table row that carries the name and the character's directory.

Anything that hangs its own state on a character name has to ride along on that
sequence — see `docs/skill-core-api.md` → „Charakter-Profil & Ort".

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

Not a candidate: a sleeping NPC, one mid-journey, one busy in a running pair
interaction, one in a conversation with an avatar, and — for the home variant —
anyone in a **party**. A follower is
dragged along by its leader and loses its own travel; a leader's roaming
journey to a free point would move it and nobody else and strand its followers
where they set out from.

A home-variant turn that OPENS a conversation does not walk in that turn — the
NPC stays where it is so the line has somebody to be said to.

## The `activity_home_enabled` template feature

`shared/templates/character/npc-temporary.json` declares
`features.activity_home_enabled: false`. A temporary NPC gets its timing from
its slot's window and its whereabouts from its home area, so a per-character
daily schedule and a per-character home location would be a second,
contradicting source of both.

The gate closes every surface at once:

* the Game-Admin "Activity & Home" sub-tab is hidden;
* `save_character_daily_schedule` refuses the write, which empties the
  `POST /scheduler/daily-schedule` route, the DELETE asymmetry and the
  `schedule:` rule condition that reads those rows. Careful: the route still
  answers `{"status": "success"}` — it ignores the `False` return, so nothing
  is stored but the caller is told otherwise;
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

## NPC conversations

Temporary NPCs talk to each other only at a place the avatar is at — inside a
location any room of it, outdoors within `npc.spawn_radius_m` of the NPC — and
only to other temporary NPCs. `npc.conversation_mode` picks how:

| mode | what happens | LLM task |
| --- | --- | --- |
| `turns` (default) | The action tick may add `say` (an opening line to someone within earshot) or `pair` (a two-person pose) to its answer, guided by the NPC's goals, reason for being here and dialogue style. The line enters the perception stream, the room's chime budget starts over, and the addressee answers through the ordinary respond lane. | opener: `npc_action`; replies: `npc_talk` |
| `scene` | One director call per room (at most every `scene_interval_game_minutes` game minutes) writes a 2–4 line exchange for up to `scene_max_npcs` NPCs, plus an optional pair pose (recorded as an invitation the partner accepts at once) and new activities. The participants get no cascade of their own; a full character present may still chime in. Outdoors the `turns` opener applies. Storyteller movement traces are left out of the lines the director sees. | `npc_scene` |
| `off` | NPCs only answer when addressed. | `npc_talk` |

**Every chat reply of a temporary NPC** — answer, chime, exit beat, TalkTo —
resolves its model through the task `npc_talk` (`chat_engine.chat_llm_task`).
Route `npc_talk` and `npc_scene` at a fast model in `/admin/settings → LLM
Routing`; unrouted, `npc_*` falls back to `chat_stream`, i.e. the RP model.

With the avatar in the SAME room and active within
`chat.avatar_floor_timeout_minutes`, the player-priority rule still holds: an
opener gets one answer, then the stage is the player's. Next door the cascade
runs to the room backstop.

An exchange the avatar OVERHEARS counts as "in chat" for both speakers. The
in-chat rule asks the perception stream for the last speech act a character
shared with an avatar, and a line the avatar perceives is exactly that — so
every NPC that says something in the player's earshot sits in the agent loop's
HOT window for the next 10 REAL minutes (`_IN_CHAT_HOT_MIN` in
`app/core/agent_loop.py`). Inside that window the action tick skips those NPCs
(no room change, no new opener), the director drops them from its participant
list (so a room whose only two NPCs just talked gets no new scene), and the
TTL and time-window sweeps defer them instead of pooling them. That is
deliberate — nobody walks out of a running scene and nobody is swept away
mid-sentence. The practical effect in the player's own room is about one
exchange per 10 minutes.

A pair invitation to a temporary NPC is accepted at once (the interact
package's hook); the engine's own state check decides whether the pair can
start.
