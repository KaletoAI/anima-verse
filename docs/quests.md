# Quests (stages 1 and 2)

Hand-made quests: an admin builds a quest template in Game-Admin → **Quests**, starts it as a run that binds the
template's roles to this world, and avatars fulfil its steps by acting in the world. In stage 2, a quest can also put
objects into the world at start (items, hidden room items, props — including generated 3D props), give hints to NPCs as
secrets, pay effects when a step is done and rewards when the quest finishes, and clean up every non-permanent object
when the run ends. The player reads the progress spoiler-free in the HUD's quest book. Quests replace the removed story
arc engine.

Stages 1 and 2 of 5 — see [What later stages add](#what-later-stages-add). Code:

| File | Responsibility |
|---|---|
| `app/models/quests.py` | Storage: tables `quest_templates`, `quest_runs`, `quest_facts`, `quest_run_objects`, `quest_run_payouts` in `world.db` (no engine logic) |
| `app/core/quest_catalog.py` | `QuestType`, `Scope`, the registry (capability `quest.types`), expression walking, effect-list and parameter checks |
| `app/core/quest_objects.py` | Core registry of run object kinds (`exists`, `remove`, `label`) |
| `app/core/quest_effects.py` | `EffectContext`, `CreatedObject`, `EffectFailed`, the `quest-effects` worker (`pass_once`, `wake`, `retry`), built-in effect types |
| `app/core/quest_types.py` | Built-in condition and prerequisite types, `QuestContext`, binding checks |
| `app/core/quest_engine.py` | Template validation, start/cancel, signal-driven evaluation, the tick, notifications, `_after_run_ended` |
| `app/core/quest_prompt.py` | Per-turn quest giver and hint lines (`lines_for`, `block_for`) |
| `app/core/quest_book.py` | The player payload of `GET /play/quests` (whitelist + finished labels, including `rewards_label`) |
| `app/routes/quests.py` | Admin HTTP adapter under `/quests` |
| `plugins/share_secret/` | Skill package providing the `share_secret` verb so NPCs can tell quest hints to characters in the same room |
| `frontend/src/tabs/quests/` | The Game-Admin tab (Templates with effect editor, Runs with objects, payouts and retry) |
| `packages/player-ui/src/QuestsPanel.tsx` | The quest book (`QuestBook` renders, `QuestsPanel` polls) |

The callable surface for packages is in [`docs/skill-core-api.md`](skill-core-api.md) → "Quest catalog".
The acceptance play-through is `scripts/smoke_quest_playthrough.py` (two parts: part 1 plays the stage-1 reference
quest "Errand"; part 2 plays the stage-2 reference quest "The big rock" with stubbed media).

## Model

**Template** — what the author writes. It refers to **roles**, never to world entities. Fields: `title`, `summary`,
`gm_notes` (admin only), `giver_role` (optional character role key), `roles`, `steps` (each with an optional `on_done`
effect list), `start_condition`, `prerequisites`, `setup_effects`, `rewards`, `time_limit_s` (game seconds, `0` =
none), `state` `draft` | `ready`, `origin` (`admin` in stages 1–2) and an integer `revision`. Only a `ready` template
can be started, and a `ready` template is always free of authoring issues (see [Admin routes](#admin-routes)). Columns
for later stages (`dependencies`, `repeat`, `kept`) exist; nothing reads them yet.

**Run** — one playing of a template. It binds every role to a world entity (`bindings`) and freezes a copy of the
template at start (`template_snapshot`, D2): evaluation, effects and the quest book read only the snapshot, so editing
or deleting the template never changes a running quest. Deleting a template while one of its runs has not ended is
refused (409 `has_open_runs`). A run carries `current_step`, a `step_log` (`{step, avatar, mind, game_ts}` per done
step), `issues` (why it broke or stalled in preparing), `started_game_ts` / `ended_game_ts` (GAME time),
`step_started_at` (SYSTEM time, UTC microseconds, stamped when the run opens and whenever a step advances — used for
`spoke_with` `since_step` ordering so a frozen world clock never blocks a quest), `expires_at`, the `news_event_id` of
its announcement and `binding_labels` (role key → display label, frozen at start — see [Placeholders](#placeholders)).

**Fact** — something a MIND did: `(mind, kind, subject)` with `game_ts` (first time, game clock), `created_at` (first
time, system clock), and `last_at` (UTC system time in microseconds, updated on every repeat observation; read via
`quests.fact_last_at`, falling back to `created_at` if empty). Ordering uses system time rather than game time so a
frozen world does not stall `since_step` conditions. Built-in kinds: `spoke_with` (subject = speaker's mind, written on
`utterance.heard`) and `found` (subject = `<location_id>/<room_id>/<item_id>`, written on `item.discovered`).

### Run states

| State | Meaning |
|---|---|
| `preparing` | Started from a template with `setup_effects`; the effects worker applies setup and moves the run to `hidden` or `open` once every setup object is `live`. Not in the quest book, not announced yet, and never expires while preparing |
| `hidden` | Started with a non-empty start condition that has not passed yet. Not in the quest book, no time limit running |
| `open` | Playing. Started (or finished preparing) with an empty start condition, or a hidden run whose start condition passed for an avatar that meets the prerequisites |
| `done` | The last step was fulfilled |
| `failed` | The time limit ran out (`expires_at` is set when the run opens: `time_limit_s` after that moment) |
| `cancelled` | Cancelled by the admin |
| `broken` | A bound entity is gone, a used type is no longer registered (two consecutive ticks), or a live run object is gone (`object_gone`, two consecutive ticks); `issues` says which |

`preparing`, `hidden` and `open` are the not-yet-ended states (`RUN_OPEN_STATES`); an ended run (`RUN_ENDED_STATES`:
`done`, `failed`, `cancelled`, `broken`) never changes state again. Steps are sequential: only the CURRENT step's
condition is read, and when it passes the run moves on in the same evaluation as long as the next step is already true
too.

## Shapes

### Roles and bindings

A role is `{"key", "kind", "description"}`. Kinds and the binding each needs at start:

| Kind | Binding |
|---|---|
| `character` | `{"name"}` — exact name; a dormant linked body exists, a pooled NPC does not |
| `location` | `{"location_id"}` |
| `room` | `{"location_id", "room_id"}` |
| `item` | `{"item_id"}` — an item definition |

A role is checked by `quest_types.check_binding(kind, binding)`. It RAISES on a storage error and returns an issue only
when the entity is definitely gone (or the binding is malformed): a failed read is not a missing entity.

`giver_role` (optional string, default `""`) must be empty or the key of a declared `character` role (otherwise issue
`giver_role` / `unknown_role`). It is frozen in the run's `template_snapshot`.

### Parameters and targets

A type declares its parameters as a list of dicts in the `config_schema` field vocabulary plus `key`:
`key, type, label, description, default, min, max, step, choices, choice_labels, required`. Parameter types
(`PARAM_TYPES`): `str`, `text`, `int`, `float`, `bool`, `select`, `role`, `target`.

- A `role` parameter holds a role KEY of the template — never a world entity id — and may restrict the role's kind with
  `role_kinds: [..]`. An optional `role` parameter on an effect may also declare `"avatar_default": True` ("empty
  defaults to the avatar who fulfilled the step"); leaving it empty in `setup_effects` is a validation issue
  (`required`), because setup has no acting avatar.
- A `target` parameter holds either a ROLE key (its kind in `role_kinds`) or a REACHABLE EFFECT key (its resolved
  object kind in `object_kinds`), checked against a `Scope(roles, objects, later)` built for that template position
  (`quest_engine.scope_at`). Reachability:
  - `setup_effects[j]` reaches earlier setup entries (`0 .. j-1`);
  - `start_condition` and `prerequisites.condition` reach all `setup_effects`;
  - `steps[i].condition` reaches `setup_effects` and `on_done` of earlier steps (`0 .. i-1`);
  - `steps[i].on_done[j]` reaches those plus earlier entries of its own list (`0 .. j-1`);
  - `rewards[j]` reaches all `setup_effects`, all `steps[].on_done`, and earlier reward entries (`0 .. j-1`).
  Violations report `unknown_target`, `wrong_kind`, or `not_yet_created` (when naming an effect key defined later in
  the template).
- A `text` parameter accepts `{role_key}` placeholders unless its spec sets `"placeholders": False` (used for JSON
  parameters such as `create_item.effects` and `create_item.stat_bonuses`).

### Expressions

Steps, the start condition and the prerequisites are expressions:

```json
{}                                     // true
{"type": "<type id>", "params": {...}} // one registered type
{"all": [expr, ...]}
{"any": [expr, ...]}
{"not": expr}
```

Evaluation is three-state (`ConditionResult(available, passed, reason)` of `app.core.activity_engine`). Unavailable is
contagious through `all` / `any` / `not`, which evaluate every child (the strict rule of
`evaluate_condition_strict`). Unavailable never counts as passed: a type that is not registered, has no evaluate
function, raises, or answers something that is not a `ConditionResult` is unavailable.

An empty step condition (`{}` or missing) is a validation issue (`steps.<i>.condition`, code `required`); `{}` remains
legal for `start_condition` and `prerequisites.condition`.

**Issue paths** are dot-joined, indices 0-based: `title`, `giver_role`, `roles.<i>.key`, `roles.<i>.kind`, `steps` (no
step at all), `steps.<i>.id`, `steps.<i>.text`, `steps.<i>.condition<expr>`, `steps.<i>.on_done.<j>…`,
`steps.<i>.role_notes.<j>…`, `start_condition<expr>`, `prerequisites.condition<expr>`, `setup_effects.<i>…`,
`rewards.<i>…`, `time_limit_s`; inside an expression `.all.<i>`, `.any.<i>`, `.not`; a leaf issue ends in `.type` or
`.params.<key>`. At start the bindings add `bindings.<role key>`. At the tick, missing live objects report
`objects.<effect_key>` with code `object_gone`. An issue is `{"path", "code", "message"}`.

### Effect lists

A template may carry effect lists in three places: `setup_effects`, `steps[i].on_done`, and `rewards`. Each entry has
the shape:

```json
{"key": "box", "type": "create_item", "params": {"name": "Old tin box"}, "permanent": false}
```

- `key` matches `^[a-z][a-z0-9_]{0,39}$` and shares ONE namespace with all role keys and all other effect keys of the
  template (duplicates report `duplicate`).
- `permanent` defaults to `false`. Non-permanent objects are removed when the run ends; permanent ones stay. In
  `rewards`, every object is always permanent (`permanent: false` on a reward entry is refused with `not_allowed_here`).
- Limits: at most **20** entries per effect list (`MAX_EFFECTS`, code `too_many`), and at most **3** `create_prop`
  entries across the whole template (`MAX_CREATE_PROP`, code `too_many`).

### Placeholders

A text the player reads may name a role: `{role_key}` in `title`, `summary`, a step's `text`, `hint` and
`role_notes[].text`, `prerequisites.locked_text`, and effect `text` parameters without `"placeholders": False`
(`gm_notes` is never substituted). `{{` and `}}` are literal braces. A placeholder naming an undeclared role is the
issue `unknown_role` at that field's path; a single `{` or `}` is `bad_text`.

The labels are frozen when the run starts (`binding_labels`): character → its name, location → the location's name,
room → the room's name, item → the item's name (a label that cannot be read falls back to the id). Renaming the room
afterwards does not change what the quest book says. `quest_engine.render_text(text, run)` is the one renderer: the
quest book, the step and completion notices, the announcement, the admin run row's title, the quest prompt block, and
effect `text` parameters (rendered before `apply` is called) all use it. A label is not a spoiler; ids and hints stay
withheld.

### Steps and prerequisites

A step is `{"id", "text", "hint", "condition": expr, "on_done"?: [effect, ...], "role_notes"?: [{"role", "text"}, ...]}`.
Each `role_notes` entry names a declared `character` role and a non-empty text of at most 500 characters; while that
step is current on an `open` run, the bound character sees the note in its per-turn quest prompt block (never shown to
the player). `prerequisites` is `{"condition": expr, "locked_text": str}`: an avatar that does not meet them is
**locked** — its actions do not count, it does not open a hidden run either — and the quest book shows the author's
`locked_text`, never an evaluator's reason (fallback "You do not meet the requirements.", translated). Prerequisite
positions accept types of kind `condition` and `prerequisite`; steps and the start condition only `condition`; effect
lists only `effect`.

### Built-in condition and prerequisite types (`app/core/quest_types.py`, owner `core`)

| Id | Kind | Parameters | Signals |
|---|---|---|---|
| `at_place` | condition | `place*` (role: location or room) | `character.entered_room` |
| `holds_item` | condition | `item*` (target: item role or item object), `count` (int >= 1, default 1) | `inventory.changed` |
| `stat_compare` | condition | `stat*` (str), `op` (`>=` `<=` `>` `<` `=`, default `>=`), `value*` (int) | `world_tick` |
| `spoke_with` | condition | `character*` (role: character), `since_step` (bool, default false: count only a talk strictly after the current step started) | `utterance.heard` |
| `time_elapsed` | condition | `hours*` (int >= 1, game hours since the run opened); `needs_open_run=True` | `world_tick` |
| `expression` | condition | `expression*` (text, activity condition grammar) | `world_tick`, `character.entered_room`, `inventory.changed` |
| `knows_secret` | condition | `secret*` (target: secret object) | `secret.learned` |
| `found_item` | condition | `placement*` (target: room_item object) | `item.discovered` |
| `near_object` | condition | `object*` (target: world_prop, room_prop or room_item object), `radius_m` (float 1–200, default 10) | `character.entered_room`, `world_tick` |
| `relationship_at_least` | prerequisite | `character*` (role: character), `strength*` (int 0–100) | — |

**Read rule.** Location, room and inventory are read for the ACTING BODY; facts (`spoke_with`, `found`) and secret
knowledge (`knows_secret`) are read for its MIND (`linked_characters.mind_of`), and a bound character is compared by
its mind too — they survive a body swap on either side. `near_object` compares a `world_prop` against the avatar's
journey-aware world position (`_avatar_point`) in metres, and a `room_prop` / `room_item` by whether the avatar stands
in that room.

### Built-in effect types (`app/core/quest_effects.py`, owner `core`)

| Id | Parameters (`*` = required) | Object kind(s) | Notes |
|---|---|---|---|
| `create_item` | `name*` str, `description` text, `category` select (`tool`, `key`, `consumable`, `evidence`, `gift`, `quest`, `decoration`, `document`; default `quest`), `consumable` bool (false), `effects` text (JSON object, no placeholders), `stat_bonuses` text (JSON `{stat: int -100..100}`, no placeholders), `bonus_when` select (`equipped` / `carried`, default `equipped`), `image_prompt` text | `item` | Mints `item_q_<hex>`; starts background image render (D16) |
| `place_item` | `item*` target[role: item / object: item], `room*` role[room], `quantity` int 1–20 (1), `hidden` bool (false), `difficulty` int 0–10 (0), `note` str | `room_item` | `discovery_difficulty = difficulty * 10` |
| `give_item` | `item*` target[role: item / object: item], `to` role[character] (`avatar_default`), `quantity` int 1–20 (1) | `grant` | Empty `to` refused in setup; notifies recipient (reward grants to the fulfilling avatar are summarized once by the reward notice) |
| `take_item` | `item*` target[role: item / object: item], `from` role[character] (`avatar_default`), `to` role[character] (empty = used up), `quantity` int 1–20 (1) | none (`marker`) | Takes up to `min(held, quantity)` under profile lock (0 held = no-op); if `to` is set, adds under a separate profile lock; never undone; notifies `from` and `to` |
| `create_prop` | `name*` str, `prompt*` text, `width_m` / `depth_m` / `height_m` float 0.1–20, `room` role[room], `near` role[location], `offset_x` / `offset_z` float −200..200 (0), `yaw` int 0–359 (0) | `world_prop` or `room_prop` (first), then `prop` (second) | Exactly one of `room` / `near`; pre-checks media and `prop` / `mesh_object` routes; holds `preparing` until mesh lands; tags sidecar with `quest_run` (D17) |
| `place_prop` | `prop_id*` str, `room` role[room], `near` role[location], `offset_x` / `offset_z` float −200..200 (0), `yaw` int 0–359 (0) | `world_prop` or `room_prop` | Exactly one of `room` / `near`; `prop_id` checked at start (`unknown_prop`) |
| `give_hint` | `holder*` role[character], `text*` text | `secret` | Stores a secret on `holder`'s mind with `source="quest"`, `source_ref="quest_run:<id>"` |
| `reveal_secret` | `secret*` target[object: secret], `to` role[character] (`avatar_default`) | none (`marker`) | Calls `secrets.add_known_by`; knowledge is not reverted; notifies recipient |
| `change_stat` | `stat*` str, `delta*` int −100..100, `to` role[character] (`avatar_default`) | `stat` | Fails if the character lacks `stat`; never reverted; notifies recipient |
| `post_news` | `text*` text, `place` role[location] (empty = global), `category` select (`ambient`/`social`/`disruption`/`danger`, default `social`), `ttl_hours` int 0–720 (24) | `event` | Global or location-scoped world event |
| `narrate` | `text*` text, `to` role[character] (`avatar_default`) | none (`marker`) | Anchored display-only storyteller line (`source="quest"`, `perception_meta={"display_only": True, "quest": True}`) |

## Effects, objects, payouts and preparing

### Objects (`app/core/quest_objects.py` and `quest_run_objects`)

Every world entity a run creates is recorded in `quest_run_objects`: `(id, run_id, effect_key, position, kind, ref,
label, permanent, status, created_at, updated_at)`. Statuses:

- `pending` — pre-recorded before an external write (or waiting for a `create_prop` 3D mesh);
- `live` — created and active in the world;
- `revert_pending` — cleanup was deferred (`remove` returned `"later"`, e.g. a mesh still running);
- `reverted` — removed by cleanup (`remove` returned `"done"`);
- `gone` — already absent or modified by hand (`remove` returned `"gone"`).

A `target` parameter resolves to the **first `live` object row** of that `effect_key` in creation (`id`) order
(`quests.live_object_refs`, marker rows excluded). `create_prop` records the placement row (`world_prop` or `room_prop`)
first and the library entry (`prop`) second, so `near_object` targeting the `create_prop` key resolves to its placement.

Object kinds are a core registry (`app/core/quest_objects.py`, not package-extensible in stage 2). Each kind implements
`exists(ref) -> bool | None` (`None` = read error, never treated as gone), `remove(ref) -> "done" | "gone" | "later"`,
and `label(ref) -> str`:

| Kind | `ref` shape | `exists` | `remove` | `label` |
|---|---|---|---|---|
| `item` | `{"item_id"}` | Item exists in catalog | `inventory.remove_item_everywhere` (unequips, removes from all inventories with `inventory.changed`, room placements, discoveries, deletes item; skips shared items as `gone`) | Item name (or id) |
| `room_item` | `{"location_id", "room_id", "item_id", "quantity"}` | Pending: room qty >= `before + qty`; live: item, location and room still exist (being picked up does not break the run) | Removes remaining qty from the room (`gone` if already picked up) | `<name> in <loc>/<room>` |
| `world_prop` | `{"placement_id", "written"}` | Row exists in `world_props` | Deletes row if unchanged since `written`; if edited by hand returns `gone` and leaves it alone | `<name> (<placement_id>)` |
| `room_prop` | `{"location_id", "room_id", "place_id", "prop_id"}` | `place_id` present in room's `layout.props` | `world.remove_room_props` | `<name> in <loc>/<room>` |
| `prop` | `{"prop_id"}` | Sidecar exists | Returns `later` while `props.is_pending(pid)`; otherwise deletes all world/room placements, `props.delete_prop`, invalidates prop library token | Prop name (or id) |
| `secret` | `{"owner", "secret_id"}` | Secret present for `owner` | `secrets.delete_secret` | Secret content (or id) |
| `event` | `{"event_id", "expires_at"?}` | Event exists, or `expires_at` has passed in game time | `events.delete_event` | Event text (or id) |
| `grant` | `{"character", "item_id", "quantity"}` | Pending: held qty >= `before + qty`; live: item definition exists (using/dropping does not break the run) | Reclaims up to `quantity` under profile lock (`remove_from_inventory(force=True)`) | `<name> -> <character>` |
| `stat` | `{"character", "changes"}` | Always `True` | No-op (`done`; stat changes are never undone) | `<character>: <stat> <old> -> <new>` |
| `marker` | `{"effect_key"}` | Always `True` | No-op (`done`) | `effect_key` (internal idempotence row for objectless effects; hidden from `live_object_refs` and admin UI) |

### Payouts (`quest_run_payouts`)

Every effect position owed by a run is written as a row `(run_id, position, avatar, state, issues, created_at,
updated_at)` in `quest_run_payouts`, in the **same transaction** as the state change that owes it (D7):

- `create_run` sets `state='preparing'` and inserts a pending `setup` payout when `setup_effects` is non-empty.
- `record_step_done` inserts a pending `step:<i>` payout (when step `i` has `on_done`) and, on the last step, a pending
  `reward` payout (when `rewards` is non-empty), both carrying `avatar` = the fulfilling body.

Payout states are `pending`, `applied`, and `failed`. Nothing is applied inline on the request or evaluation thread.

### Preparing

A run with `setup_effects` starts in state `preparing` (not listed in `/play/quests`, not announced, never expired by
`expire_runs`). Once every setup entry has completed and every setup object row is `live`, the worker calls
`quests.finish_preparing(run_id, to_state=..., started_game_ts=..., expires_at=...)`:

- With a non-empty `start_condition`, `to_state` is `hidden`.
- Otherwise `to_state` is `open`, `started_game_ts` and `expires_at` are stamped, and the run is announced.

If a setup effect fails non-retryably, the run stays `preparing` with `issues` populated and the worker skips it until
the admin retries or cancels. Only `create_prop` meshes hold a run in `preparing`; if a mesh is still pending more than
30 minutes (`MESH_TIMEOUT_S = 1800`) after its anchor timestamp, the run records issue `mesh_timeout` (D9).

### The effects worker (`app/core/quest_effects.py`)

One daemon thread named `quest-effects` (started in `app/server.py` after the hub resumer, stopped on shutdown), woken
immediately by `wake()` (on start, step done, end, retry) and otherwise every 15 seconds (`PASS_INTERVAL_S`). It is
**not** gated by world freeze or task-queue pause (a World Dev run freezes the world while still expecting setup and
cleanup to complete).

`pass_once()` (serialized by `_pass_lock`, also callable directly from smokes) runs four phases in order:

1. **Pending `setup` payouts** — apply `setup_effects` in list order, stopping at the first entry that waits or fails;
   when all setup objects are `live`, call `finish_preparing` and mark the `setup` payout `applied`.
2. **Pending `step:<i>` and `reward` payouts** — apply `on_done` / `rewards` for `open`, `hidden`, or `done` runs; mark
   `applied` or `failed` with `issues`. If a run ended `cancelled`, `failed`, or `broken`, its pending payouts are
   marked `failed` (`run_ended`); a `done` run's `reward` payout still pays out (including after a crash/restart) and
   sends a single `Reward: <items>` notice to the fulfilling avatar.
3. **Cleanup of ended runs** — iterate `quests.objects_to_clean()` (non-permanent objects of ended runs in status
   `live`, `pending`, or `revert_pending`) in reverse effect creation order (rows within one effect keep creation order,
   so placements are removed before their library prop), calling `remove(ref)`.
4. **Untag permanent props** — iterate `quests.permanent_props_of_ended_runs()` (`kind='prop'`, `permanent=1`, status
   `live` or `pending` of ended runs) and clear their `quest_run` sidecar tag (D17).

**Idempotence and restart reconciliation (D8).** Before an external write, an effect calls `ctx.record_pending(...)`
with a pre-minted id (or a `before` count). On a later pass or after a restart, any `pending` row is reconciled with
`exists(ref)`: `True` promotes it to `live` without re-running (stripping pending-only ref keys `before`,
`mesh_failed`, `mesh_started_at`); `False` re-applies the entry reusing the existing row(s) via `ctx.previous`; `None`
skips the entry for that pass. Objectless effects (`reveal_secret`, `narrate`) get a permanent `marker` row once they
succeed so a later failing entry in the same list never re-runs them.

### Retry

`POST /quests/runs/{id}/retry` (calling `quest_effects.retry(run_id)`) re-arms every `failed` payout of a not-ended (or
`done`) run back to `pending` with empty `issues`, clears `issues` on a `preparing` run, and wakes the worker. Nothing
retries silently.

### Cleanup and end path

All five end sites (`done` in `_evaluate_run`, `cancel_run`, expired runs in `tick`, broken runs in `tick`, and
`on_character_deleted`) call `quest_engine._after_run_ended(run_id)`, which withdraws any announcement (for
`cancelled`/`failed`/`broken`) and wakes the effects worker (D10). Cleanup itself runs in the worker's phase (3), so a
crash between the state change and cleanup heals automatically on the next pass. Non-permanent objects are removed;
permanent objects (including all reward objects) stay.

### Item images (D16)

`create_item` creates the item immediately with `image=None` and starts `app.core.item_images.generate_item_image_sync`
on a background daemon thread (`quest-item-image-<id>`). `preparing` never waits for item images. If media generation
is off, unrouted, or fails, the item keeps `image=None` and every client displays the category emoji as its
placeholder.

### Quest props (D17)

Every prop created by `create_prop` carries the sidecar key `quest_run: <run_id>` (managed via
`app.core.props.set_quest_run`). Props with a non-empty `quest_run` are excluded from `room_furnish._library()` and
refused by export/publish pickers. When a run ends, non-permanent quest props are deleted (once not pending); permanent
quest props lose the `quest_run` sidecar key in phase (4) of `pass_once()` and join the regular prop library.

## Hints, secrets and the quest prompt block

- **`give_hint`** stores a secret on the holder's mind with `source="quest"` and `source_ref="quest_run:<run_id>"`
  (`app/models/secrets.py`). Quest secrets are excluded from `build_secrets_prompt_section` so they never enter the
  stable system prompt and do not depend on the template's `secrets_enabled` switch.
- **`secret.learned`** is emitted by `secrets.add_known_by` (outside locks, only when the knower was newly added and
  saved) with `{owner, secret_id, knower, discovered, source_ref}`.
- **`plugins/share_secret/`** provides the verb `share_secret{secret_id, to}` (default enabled, works in single and
  rp_first). The speaker must be in a real room and must own or already know the secret; `to` must be in the same room.
  The verb calls `secrets.add_known_by(owner, secret_id, to)` and nothing else. Deletion test: removing
  `plugins/share_secret/` removes the verb cleanly; hints still reach avatars through `reveal_secret` effects.
- **Quest prompt block (`app/core/quest_prompt.py`, D15).** `lines_for(character_name)` (no locks, never raises,
  early-out on `quest_engine.has_live_runs()`) returns at most 4 lines (`MAX_LINES = 4`):
  - For each `hidden` or `open` run where `character_name` is bound to `giver_role`:
    - `open`: `You want an adventurer to: <summary> — next: <current step text>` (em dash U+2014; omits `— next: …` if
      the current step has no text);
    - `hidden`: `You want an adventurer to: <summary>` (never leaks step text or secret ids).
  - For each `open` run whose current step has `role_notes` whose `role` is bound to `character_name`:
    - `Quest "<title>": <rendered text>` (never for `hidden` or `preparing` runs).
  - For each `open` run's `live` `secret` object owned by `mind_of(character_name)`:
    - `You know something you may tell an adventurer who asks [secret <secret_id>]: <content>`.
  `block_for(character_name)` formats the lines as `- …` bullets. It is injected **only** into per-turn prompts —
  `shared/templates/llm/chat/chat_moment.md` (`quest_section`), `app/core/thought_context.py` (`quest_block`, also
  suppressible by prompt filters), and `app/core/npc_actions.py` (`_with_action_context`) — never into the stable chat
  system prompt.

## Type contract (for packages)

A type is a `QuestType` (`app.core.quest_catalog`):

| Field | Meaning |
|---|---|
| `id` | Unique id; namespace a package's ids (`<package>.<name>`). Of two types with the same id the first registered wins |
| `kind` | `condition`, `prerequisite` or `effect` |
| `label`, `description` | English UI text; the description is one line (also used by World Dev's catalog) |
| `params` | Tuple of parameter dicts |
| `signals` | The hook events after which a condition may have changed its answer. A step is re-read on those signals and on every tick |
| `evaluate(params, ctx)` | For conditions/prerequisites: returns `ConditionResult`; `ctx` is a `QuestContext` (`avatar`, `mind`, `profile`, `location_id`, `room_id`, `now`, `bindings`, `run`, `objects`). Return unavailable (never false) when a read fails |
| `apply(params, ctx)` | For effects: runs on the effects worker with an `EffectContext` and returns `list[CreatedObject]` (or raises `EffectFailed`) |
| `object_kind` | Default `""`. Kind of the first object the effect records, which a `target` parameter resolves to (`""` = none) |
| `object_kind_for` | Optional `params -> str` callable when the first object's kind depends on params |
| `object_kind_when` | Optional tuple of `(param_key, object_kind)` pairs (declarative equivalent sent to the admin client) |
| `validate(params, bindings)` | Optional; returns `list[ConditionIssue]`. `bindings` is `None` at template time (check only what needs no world entity) and the run's bindings at start and at every tick |
| `needs_open_run` | Default `False`. `True` for a type that can only be read once the run has opened (it counts from `started_game_ts`, like `time_elapsed`): `validate_template` refuses it under `start_condition` (code `not_allowed_here`), and under `prerequisites.condition` when `start_condition` is non-empty |

What the catalog guarantees a type:

- **Parameters arrive cleaned.** The generic check (type, `min`/`max`, `choices`, role/target key and kind) runs first;
  the type's `validate` only sees a leaf that passed it. Before `evaluate` / `validate` / `apply`, the catalog fills
  the declared defaults in and DROPS an absent parameter that has no default (absent = missing, `null` or blank text) —
  so a type reads its parameters with `params.get(...)`. For effects, `text` parameters without `"placeholders": False`
  already have `{role}` placeholders rendered before `apply` is called.
- **The type list is never cached.** `quest_catalog.types()` is rebuilt from the provider registry on every call, so
  an unloaded package's types are gone at once: its leaves evaluate unavailable ("type not registered"). The tick
  marks such a run `broken` only when the type is missing at TWO consecutive ticks — one catalog read without it (a
  package reloading, a contributor that raised once) is no evidence, and the tick reads the catalog strictly
  (`types(strict=True)`): a raising contributor skips the run for that tick.
- **Expressions nest at most 16 group levels** (`quest_catalog.MAX_DEPTH`); a deeper node is a `shape` issue, so
  such an expression never becomes ready.
- **A raising type is contained.** A raising `evaluate` makes that leaf unavailable; the other runs are evaluated as
  usual. A raising `validate` becomes a `bad_param` issue when the template is checked and REFUSES a start; at the
  tick the run is SKIPPED for that tick — a failed read or a raising validator is no evidence that a reference is
  gone, and `broken` is final, so the tick never marks a run broken because of one.

**Registration.** One capability, `quest.types`. A contributor is a function `fn() -> list[QuestType]` that answers
ALL of its owner's types; contributors are per OWNER (`register_provider(..., owner=..., multiple=True)` under the
hood), so a second registration by the same owner replaces the first and the plugin loader's
`unregister_owned_providers(<package id>)` removes it. Register from the package's `on_load` module.

### Minimal package

`plugins/busy_quests/plugin.yaml`:

```yaml
name: busy_quests
version: "1.0.0"
description: A quest condition "is doing an activity"
on_load: quest_types.py
```

`plugins/busy_quests/quest_types.py`:

```python
"""on_load: the quest types of the busy_quests package."""
from app.core.activity_engine import ConditionIssue, ConditionResult
from app.core.quest_catalog import QuestType, register

OWNER = "busy_quests"


def _doing(params, ctx):
    want = (params.get("activity") or "").strip().lower()
    if not want:
        return ConditionResult(False, False, "No activity given")
    current = str(ctx.profile.get("current_activity") or "").lower()
    if want in current:
        return ConditionResult(True, True, "")
    return ConditionResult(True, False, f"Not {want}")


def _validate(params, bindings):
    want = params.get("activity")
    if isinstance(want, str) and len(want) > 80:
        return [ConditionIssue("bad_param", "Keep the activity short")]
    return []


def _types():
    return [QuestType(
        id="busy_quests.doing", kind="condition", label="Is doing an activity",
        description="The avatar's current activity contains the given text.",
        params=({"key": "activity", "type": "str", "label": "Activity", "required": True},),
        # An activity changes without a signal of its own: the tick re-reads it.
        signals=("world_tick",), validate=_validate, evaluate=_doing)]


register(OWNER, _types)
```

The Game-Admin's condition editor offers it at once (`GET /quests/catalog`); removing the folder removes the type, and
a run that used it turns `broken` once the type has been missing at two ticks (the deletion test).

## Evaluation and signals

Only `quest_engine` subscribes (hook tag `"quest_engine"`) to six events (`SIGNALS`):

| Event | Emitted by | What the engine does |
|---|---|---|
| `character.entered_room` | a successful real room change (`save_character_current_room`, a location change into its arrival room) | evaluates that character |
| `inventory.changed` | `add_to_inventory`, `remove_from_inventory`, `update_inventory_entry` with a `quantity` | evaluates that character |
| `utterance.heard` | `perception.record_utterance` | records `spoke_with`, then evaluates the avatars it concerns |
| `secret.learned` | `secrets.add_known_by` (when a new knower is stored) | evaluates every avatar belonging to that mind |
| `item.discovered` | `inventory.placement_visible_to` (when a hidden placement is first revealed) | records `found`, then evaluates every avatar belonging to that mind |
| `world_tick` | the periodic runner | the tick (below) |

- `inventory.changed` carries the REAL stored `delta` (signed; an add onto a stack capped by `max_stack` reports what
  was actually added) and nothing is emitted for a zero change or a failed write. Some inventory writes emit no event
  at all: an item definition deleted (`delete_item` and its cleanup), a character import or reset. The tick's full
  re-evaluation covers them — read quantities (`get_item_quantity`), never sum deltas.
- `utterance.heard`'s `heard_by` and `avatars` EXCLUDE the speaker.
- **"Has spoken with"** is recorded for every line of an NPC (`source` `"loop"`, the speaker not an avatar) addressed
  to an avatar that heard it: the fact `(mind_of(avatar), "spoke_with", mind_of(speaker))`. It is written whether or
  not a quest is running — a talk before the quest started counts — and it belongs to the MIND, so it survives a
  body swap.
- **"Has found"** is recorded when `placement_visible_to` reveals a hidden room item: `(mind_of(character), "found",
  "<location_id>/<room_id>/<item_id>")`.
- Only a player-controlled character fulfils anything: an NPC entering the bound room changes nothing. A run is read
  only when its current expression listens to the signal; a run whose start condition passes for an avatar that meets
  the prerequisites opens (without announcement).
- **Time limit.** A signal never records a step of an open run past its `expires_at`; the tick ends it `failed`
  (the tick does not run while the queue is paused, the game clock does).
- **Threading.** The listeners only enqueue; one worker thread (`quest-engine`) writes facts and evaluates.
  `quest_engine.drain()` waits for it (tests and smokes). Effects never run on this thread — only on `quest-effects`.
- **Freeze.** An avatar's own action is evaluated in a frozen world too; the tick is not (below), so nothing expires
  while the world is frozen. The effects worker is not gated by world freeze.

### The tick

`world_tick` comes from the periodic runner's package tick: at most every 30 s, in practice every
`server.world_admin_tick_interval_seconds` (default 60 s), and the runner skips it while the world is frozen or the
task queue paused (`tick()` itself has no freeze check). Order:

1. **Expiry** — every `hidden`/`open` run past `expires_at` turns `failed` (`preparing` runs never expire).
2. **Reference check** — per not-ended run (`preparing`, `hidden`, `open`):
   - each binding (`check_binding`) and each leaf/effect validator `validate(params, bindings)`;
   - unregistered types in expressions or in still-owed effect positions (broken after TWO consecutive ticks);
   - every `live` run object's `exists(ref)` (broken with `objects.<effect_key>` / `object_gone` after TWO consecutive
     ticks returning `False`; `None` skips).
   A storage error, a raising validator or a raising type contributor skips that run for this tick (neither checked nor
   evaluated, never marked broken). Deleting a character breaks its runs at once, after its rows are deleted
   (`delete_character` calls `quest_engine.on_character_deleted`; a failed delete breaks nothing); everything else is
   caught here. Every newly ended run goes through `_after_run_ended`.
3. **Full re-evaluation** of every avatar against every live run — this is what notices changes that have no signal
   (stats, time, activity, free-map position for `near_object`, the silent inventory writes).

## Notices and push

- A fulfilled step notifies only the avatar that fulfilled it: `create_notification(..., notification_type="quest",
  once_unread=True)`, text "Quest step done: <step text>" (or "Quest complete: <title>" for the last step), with the
  role placeholders rendered. Because of `once_unread`, two runs whose current steps have the same text store ONE
  unread notice.
- Applying a `reward` payout notifies the fulfilling avatar once with "Reward: <items>" (when it granted items).
  Non-reward `give_item`, `reveal_secret` and `change_stat` effects notify their player-controlled recipient.
- A run that opens at start (or finishes `preparing` into `open`) is announced as a global world event (`category
  "social"`, text "<title>: <summary>"); a run that opens from `hidden` is not announced. When an announced run ends
  `cancelled`, `failed` or `broken` its event is deleted, best effort.
- Every state change pushes the topic `notices` to every bound avatar — no quest topic of its own. The quest book's
  poll listens to `notices` (`packages/player-ui/src/syncEndpoints.ts`: interval 15 s, pushed interval 30 s, minimum
  spacing 15 s — `minSpacingMs >= intervalMs` is the documented rule, so a pushed refetch may wait up to 15 s).

## The player's quest book — `GET /play/quests`

```json
{"avatar": "A",
 "quests": [{"id", "title", "summary", "state",
             "steps": [{"text", "state", "done_by"?, "done_label"?}],
             "time_left_label"?, "locked"?, "ended_label"?, "rewards_label"?}]}
```

- Built up from whitelists (`quest_book.QUEST_FIELDS`, `STEP_FIELDS`, `OPTIONAL_FIELDS`) out of the snapshot:
  `gm_notes`, roles, bindings, every `hint`, every `role_notes`, every condition, every effect definition and the text
  of every future step are never sent.
- Listed: every `open` run (newest first), then at most 10 ENDED runs that had opened (latest end first; the store
  query `list_chronicle` filters and cuts in SQL, so a poll decodes at most ten ended snapshots). `hidden` and
  `preparing` runs are not listed, and neither is an ended run that never opened — its title would be a spoiler.
- Steps: an open run shows its done steps and the current one (`state` `done` / `current`); an ENDED run that is not
  `done` shows only its done steps; a `done` run all of them. A done step carries `done_by` (the avatar) and
  `done_label`.
- `time_left_label` only on an open run with a time limit; `locked` only when this avatar is locked; `ended_label` only
  on an ended run; `rewards_label` only on a `done` run that granted reward items to THIS avatar (names only, e.g.
  `Lucky charm` or `2 × Coin`, via `quest_book.reward_items_label`). Every `*_label` is a finished server string in the
  avatar's language.
- Quests are world-wide: every avatar sees the same runs; only `locked` and `rewards_label` are per avatar. Without an
  avatar the answer is `{"avatar": "", "quests": []}`.

## Admin routes

`/quests` is admin-only for reads AND writes (templates carry GM notes): the prefix is on the auth gate's
`_ADMIN_PREFIXES` and the router carries `Depends(require_admin)`.

| Route | Does |
|---|---|
| `GET /quests/catalog` | Public type descriptors `{conditions, prerequisites, effects, role_kinds}` |
| `GET /quests/templates` | List rows with `open_runs` |
| `GET /quests/templates/{id}` | The full template plus its `issues` |
| `POST /quests/templates` | Create; always a `draft` of origin `admin` |
| `PUT /quests/templates/{id}` | Edit with `base_revision` |
| `DELETE /quests/templates/{id}` | Refused with 409 `has_open_runs` while a run has not ended |
| `POST /quests/templates/{id}/start` | `{"bindings": {role: binding}}` → the run |
| `GET /quests/runs?state=` | Not-yet-ended runs first, then the newest 50 ended ones; each row carries `binding_labels`, `game_label` per step-log entry, `objects: [{kind, label, permanent, status}]` (markers excluded), and `payouts: [{position, state, issues}]` |
| `POST /quests/runs/{id}/cancel` | `{"ok": bool}` (false when it had ended or is unknown) |
| `POST /quests/runs/{id}/retry` | `{"ok": bool}` — re-arms failed payouts of a not-ended (or `done`) run, clears `preparing` issues, and wakes the effects worker |

Every error detail is an object with a `code`: `{code, message}`, `stale` adds the stored `current` revision, and the
two refusals with an issue list answer `{code, issues}`. Codes: `bad_json` (400, also a body nested too deep to
parse), `bad_request` (400: a text field that is not text, a `time_limit_s` outside 0..2⁶³−1, anything the store
cannot write), `not_found` (404), `revision_required` (428), `stale` (409), `invalid` (422), `has_open_runs` (409),
`refused` (422 at start), `too_large` (413, a body over 256 KiB). The Game-Admin translates the code; issue messages
are translated on display where keys exist.

**The ready rule.** `PUT` checks the RESULTING template (stored fields merged with the body): whenever its state would
be `ready` with issues it answers 422 `invalid` and writes nothing — also when the body does not name `state`, so a
ready template that became invalid without an edit (a package it uses was removed) refuses every plain edit. The way
out is to save it with `"state": "draft"` in the same `PUT` as the fix, and set it `ready` again once its issues
are gone.

## What later stages add

Not yet in stages 1–2: LLM authoring, `llm_judgement`, automatic quests and their caps, a `quests` config section,
repeat modes, dependencies, stories, import/export, reward bounds / media budget settings, and a `secret` role kind.

| Stage | Adds |
|---|---|
| 1 | Hand-made quests are playable (built) |
| 2 | Quests put things into the world: object effects, run objects with lifetimes and cleanup, rewards, hints as secrets, `share_secret`, prompt block, media generation (built) |
| 3 | The LLM writes quests: authoring pipeline, "Generate with LLM", `llm_judgement`, automatic NPC-giver quests with caps |
| 4 | Stories: a frame, chapters generated during play, summaries, approval mode |
| 5 | Reuse across worlds: repeat modes, dependencies, role binding on import, `quest` / `story` pack types |
