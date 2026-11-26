# Manual: systems

## Access rules

`add_block_rule` stops characters from entering (`action: "enter"`, the default) or leaving
(`action: "leave"`) a place — or only some of its rooms (`rooms`: room ids or names of that
place; leave `rooms` out to block the whole place — naming every room still leaves its
corridors and grounds open) — WHILE its `condition` holds. `message` is what a blocked character is told; `character`
limits the rule to that one character (leave it out for everyone).

When a rule is the right tool:
- A tavern closed at night: `{"name": "Closed at night", "message": "The tavern is closed.",
  "location_id": "<tavern id>", "condition": "night"}`.
- A cellar only the bold go into: `"rooms": ["Cellar"], "condition": "<stat><40"` with a stat
  name from `list_catalog stats`.
- A gate a character may not pass: `"action": "leave", "character": "<name>", "condition": "always"`.

Access for residents only (a private house) cannot be built with a rule: a condition reads the
character's profile, and the home is stored in the character settings, so
`home_location!=<id>` blocks the residents as well. `at_home` does not help either: it means the
character is standing at its own home RIGHT NOW, so `NOT at_home` also blocks a resident who is
coming home. Name it under *left open* instead, or use a condition that does work (`night`, an
item as key: `NOT has_item:<item>`).

A rule without a condition never blocks anyone — `condition` is required, and a condition with
an unknown word or a name that does not exist is refused.

Condition grammar (the same as in Game-Admin → Rules): atoms joined with `AND` / `OR`, each atom
optionally preceded by `NOT` (`AND` binds tighter than `OR`; no brackets). The atoms most useful
for access (not the full list — an atom the engine does not know is refused):
- `night`, `day` — sunset to sunrise / sunrise to sunset; `night+30` / `night-30` move the start
  by minutes;
- `<stat>>40`, `<stat><20`, `<stat>=0` — a stat of the character (`list_catalog stats`);
- `present:<name>` — that character is at the place;
- `mood:<mood>` — the character's current mood;
- `relationship:<name>>50`, `romantic:<name>>50` — the character's relation to that character;
- `location_danger>2` — the danger level of the place;
- `has_item:<item id or name>`, `room_has_item:<item>` — in the inventory / in the room;
- `schedule:<activity>`, `schedule:sleeping`, `schedule:awake` — the current daily-schedule slot;
- `current_activity:<text>` — what the character is doing now;
- `condition:<name>` — an active condition of the character; `state:<id>` — a defined state;
- `<field>=<value>`, `<field>!=<value>` — a top-level profile field (e.g. `gender=female`);
- `alone`, `at_home`, `travelling`, `always`.

## World events

`add_event` puts ONE happening into the world: a travelling merchant in the square, a storm, a
fight in the tavern. Characters at that place read it in their scene; without `location_id` it
happens everywhere. `category` is one of `list_catalog event_categories` (leave it out for none);
it decides who notices it beyond the place — `danger` reaches everyone, `disruption` the nearby
places, `ambient` and `social` only the place itself.

`ttl_hours` is how long it lasts in GAME hours (default 24, at most 720; `0` = it never ends on its
own). After that it is gone.

- A merchant for the afternoon: `{"text": "A travelling merchant sets up in the square.",
  "location_id": "<square id>", "category": "social", "ttl_hours": 6}`.
- A storm over the whole land: `{"text": "A storm rolls in from the sea.", "category":
  "disruption", "ttl_hours": 12}`.

An event is a one-off. A weekly market or a daily bell is not an event — describe it in the place
description instead. A place cannot be deleted while any active event is at it. The run can delete
only its own events, and only in the turn that created them: delete such an event first. An event
that is not the run's own stays — report it in the summary instead of deleting the place.

## Quests

`create_quest_template` writes a quest as a DRAFT template. The admin reviews it in Game-Admin →
Quests, makes it ready and starts it — you cannot do either.

A quest names ROLES instead of fixed characters, places or items: `roles` is a list of
`{"key": "<role key>", "kind": "<kind>"}` with a kind from `list_catalog quest_roles`. Who or what
fills a role is decided when the admin starts the quest. Steps are done one after another; each is
`{"id": "<step id>", "text": "<what the player is told>", "hint"?: "<a nudge>",
"condition": {"type": "<type id>", "params": {...}}}` with a condition type from
`list_catalog quest_types` (its params are listed there; a `role` param takes a role key).
`{role_key}` in the title, summary and step texts is replaced by the role's name in play.
`gm_notes` are for the admin only and never reach the player. `time_limit_s` is a limit in
seconds (0 = none).

- The lost mill: `{"title": "The lost mill", "summary": "{miller} has lost the mill wheel.",
  "gm_notes": "The apprentice took it.", "roles": [{"key": "miller", "kind": "character"}],
  "steps": [{"id": "s1", "text": "Speak with {miller}.", "condition": {"type": "spoke_with",
  "params": {"character": "miller"}}}]}`.

The result line lists what the draft still lacks under `issues:`. To fix them, remove the draft
with `delete_created` in the same turn and create it again; otherwise name them in your summary —
the admin finishes the draft. The run can delete only its own templates, and only in the turn that created them.
