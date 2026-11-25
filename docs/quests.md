# Quests (stage 1)

Hand-made quests: an admin builds a quest template in Game-Admin → **Quests**, starts it as a run that binds the
template's roles to this world, and avatars fulfil its steps by acting in the world. The player reads the progress
spoiler-free in the HUD's quest book. Quests replace the removed story arc engine.

Stage 1 of 5 — see [What later stages add](#what-later-stages-add). Code:

| File | Responsibility |
|---|---|
| `app/models/quests.py` | Storage: tables `quest_templates`, `quest_runs`, `quest_facts` in `world.db` (no engine logic) |
| `app/core/quest_catalog.py` | `QuestType`, the registry (capability `quest.types`), expression walking, generic parameter checks |
| `app/core/quest_types.py` | The built-in types and `QuestContext` |
| `app/core/quest_engine.py` | Template validation, start/cancel, signal-driven evaluation, the tick, notifications |
| `app/core/quest_book.py` | The player payload of `GET /play/quests` (whitelist + finished labels) |
| `app/routes/quests.py` | Admin HTTP adapter under `/quests` |
| `frontend/src/tabs/quests/` | The Game-Admin tab (Templates, Runs) |
| `packages/player-ui/src/QuestsPanel.tsx` | The quest book (`QuestBook` renders, `QuestsPanel` polls) |

The callable surface for packages is in [`docs/skill-core-api.md`](skill-core-api.md) → "Quest catalog".
The acceptance play-through is `scripts/smoke_quest_playthrough.py`.

## Model

**Template** — what the author writes. It refers to **roles**, never to world entities. Fields: `title`, `summary`,
`gm_notes` (admin only), `roles`, `steps`, `start_condition`, `prerequisites`, `time_limit_s` (game seconds,
`0` = none), `state` `draft` | `ready`, `origin` (`admin` in stage 1) and an integer `revision`. Only a
`ready` template can be started, and a `ready` template is always free of authoring issues (see
[Admin routes](#admin-routes)). Columns for later stages (`dependencies`, `setup_effects`, `rewards`, `repeat`,
`kept`) exist; nothing reads them yet.

**Run** — one playing of a template. It binds every role to a world entity (`bindings`) and freezes a copy of the
template at start (`template_snapshot`, D2): evaluation and the quest book read only the snapshot, so editing or
deleting the template never changes a running quest. Deleting a template while one of its runs has not ended is
refused (409 `has_open_runs`). A run carries `current_step`, a `step_log` (`{step, avatar, mind, game_ts}` per
done step), `issues` (why it broke), `started_game_ts` / `ended_game_ts` (GAME time), `expires_at`, the
`news_event_id` of its announcement and `binding_labels` (role key → display label, frozen at start — see
[Placeholders](#placeholders)).

**Fact** — something a MIND did, written once: `(mind, kind, subject)`. Stage 1 has one kind, `spoke_with`.

### Run states

| State | Meaning |
|---|---|
| `preparing` | Reserved for stage 2 (setup effects); nothing creates it in stage 1 |
| `hidden` | Started with a non-empty start condition that has not passed yet. Not in the quest book, no time limit running |
| `open` | Playing. Started with an empty start condition, or a hidden run whose start condition passed for an avatar that meets the prerequisites |
| `done` | The last step was fulfilled |
| `failed` | The time limit ran out (`expires_at` is set when the run opens: `time_limit_s` after that moment) |
| `cancelled` | Cancelled by the admin |
| `broken` | A bound entity is gone or a used type is no longer registered (at two consecutive ticks); `issues` says which |

`preparing`, `hidden` and `open` are the not-yet-ended states; an ended run never changes state again. Steps are
sequential: only the CURRENT step's condition is read, and when it passes the run moves on in the same evaluation as
long as the next step is already true too.

## Shapes

### Roles and bindings (D6)

A role is `{"key", "kind", "description"}`. Kinds and the binding each needs at start:

| Kind | Binding |
|---|---|
| `character` | `{"name"}` — exact name; a dormant linked body exists, a pooled NPC does not |
| `location` | `{"location_id"}` |
| `room` | `{"location_id", "room_id"}` |
| `item` | `{"item_id"}` — an item definition |

A role is checked by `quest_types.check_binding(kind, binding)`. It RAISES on a storage error and returns an issue only
when the entity is definitely gone (or the binding is malformed): a failed read is not a missing entity.

### Parameters (D5)

A type declares its parameters as a list of dicts in the `config_schema` field vocabulary plus `key`:
`key, type, label, description, default, min, max, step, choices, choice_labels, required`. Parameter types:
`str`, `text`, `int`, `float`, `bool`, `select`, `role`. A `role` parameter holds a role KEY of the template —
never a world entity id — and may restrict the role's kind with `role_kinds: [..]`.

### Expressions (D7)

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

**Issue paths** are dot-joined, indices 0-based: `title`, `roles.<i>.key`, `roles.<i>.kind`, `steps` (no step at
all), `steps.<i>.id`, `steps.<i>.text`, `steps.<i>.condition<expr>`, `start_condition<expr>`,
`prerequisites.condition<expr>`, `time_limit_s`; inside an expression `.all.<i>`, `.any.<i>`, `.not`; a leaf issue
ends in `.type` or `.params.<key>`. At start the bindings add `bindings.<role key>`. An issue is
`{"path", "code", "message"}`.

### Placeholders

A text the player reads may name a role: `{role_key}` in `title`, `summary`, a step's `text` and `hint`, and
`prerequisites.locked_text` (`gm_notes` is never substituted). `{{` and `}}` are literal braces. A placeholder
naming an undeclared role is the issue `unknown_role` at that field's path (`title`, `summary`,
`steps.<i>.text`, `steps.<i>.hint`, `prerequisites.locked_text`); a single `{` or `}` is `bad_text`.

The labels are frozen when the run starts (`binding_labels`): character → its name, location → the location's name,
room → the room's name, item → the item's name (a label that cannot be read falls back to the id). Renaming the room
afterwards does not change what the quest book says. `quest_engine.render_text(text, run)` is the one renderer: the
quest book (title, summary, step texts, lock text), the step and completion notices, the announcement and the admin
run row's title use it. A label is not a spoiler; ids and hints stay withheld.

### Steps and prerequisites (D8)

A step is `{"id", "text", "hint", "condition": expr}`. `prerequisites` is `{"condition": expr, "locked_text": str}`:
an avatar that does not meet them is **locked** — its actions do not count, it does not open a hidden run either — and the quest book shows the author's
`locked_text`, never an evaluator's reason (fallback "You do not meet the requirements.", translated). Prerequisite
positions accept types of kind `condition` and `prerequisite`; steps and the start condition only `condition`.

### Built-in types (`app/core/quest_types.py`, owner `core`)

| Id | Kind | Parameters | Signals |
|---|---|---|---|
| `at_place` | condition | `place` (role: location or room) | `character.entered_room` |
| `holds_item` | condition | `item` (role: item), `count` (int, default 1) | `inventory.changed` |
| `stat_compare` | condition | `stat` (str), `op` (`>=` `<=` `>` `<` `=`), `value` (int) | `world_tick` |
| `spoke_with` | condition | `character` (role: character) | `utterance.heard` |
| `time_elapsed` | condition | `hours` (int, game hours since the run opened); not allowed in a start condition | `world_tick` |
| `expression` | condition | `expression` (the activity condition grammar) | `world_tick`, `character.entered_room`, `inventory.changed` |
| `relationship_at_least` | prerequisite | `character` (role: character), `strength` (0–100) | — |

**Read rule.** Location, room and inventory are read for the ACTING BODY; facts are read for its MIND
(`linked_characters.mind_of`), and a bound character is compared by its mind too — "has spoken with" survives a body
swap on either side.

## Type contract (for packages)

A type is a `QuestType` (`app.core.quest_catalog`):

| Field | Meaning |
|---|---|
| `id` | Unique id; namespace a package's ids (`<package>.<name>`). Of two types with the same id the first registered wins |
| `kind` | `condition`, `prerequisite` or `effect` (`effect` has no consumer before stage 2) |
| `label`, `description` | English UI text; the description is one line (later also the LLM's catalog line) |
| `params` | Tuple of parameter dicts (D5) |
| `signals` | The hook events after which the type may have changed its answer. A step is re-read on those signals and on every tick |
| `evaluate(params, ctx)` | Returns `ConditionResult`; `ctx` is a `QuestContext` (`avatar`, `mind`, `profile`, `location_id`, `room_id`, `now`, `bindings`, `run`). Return unavailable (never false) when a read fails |
| `validate(params, bindings)` | Optional; returns `list[ConditionIssue]`. `bindings` is `None` at template time (check only what needs no world entity) and the run's bindings at start and at every tick |
| `needs_open_run` | Default `False`. `True` for a type that can only be read once the run has opened (it counts from `started_game_ts`, like `time_elapsed`): `validate_template` refuses it under `start_condition` (code `not_allowed_here`), where a hidden run has not opened and the type would stay unavailable forever |

What the catalog guarantees a type:

- **Parameters arrive cleaned.** The generic check (type, `min`/`max`, `choices`, role key and kind) runs first; the
  type's `validate` only sees a leaf that passed it. Before `evaluate` / `validate` the catalog fills the declared
  defaults in and DROPS an absent parameter that has no default (absent = missing, `null` or blank text) — so a type
  reads its parameters with `params.get(...)`.
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

Only `quest_engine` subscribes (hook tag `"quest_engine"`) to four events (D9):

| Event | Emitted by | What the engine does |
|---|---|---|
| `character.entered_room` | a successful real room change (`save_character_current_room`, a location change into its arrival room) | evaluates that character |
| `inventory.changed` | `add_to_inventory`, `remove_from_inventory`, `update_inventory_entry` with a `quantity` | evaluates that character |
| `utterance.heard` | `perception.record_utterance` | records "has spoken with", then evaluates the avatars it concerns |
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
- Only a player-controlled character fulfils anything: an NPC entering the bound room changes nothing. A run is read
  only when its current expression listens to the signal; a run whose start condition passes for an avatar that meets
  the prerequisites opens (without announcement).
- **Time limit.** A signal never records a step of an open run past its `expires_at`; the tick ends it `failed`
  (the tick does not run while the queue is paused, the game clock does).
- **Threading (D11).** The listeners only enqueue; one worker thread writes facts and evaluates.
  `quest_engine.drain()` waits for it (tests and smokes).
- **Freeze.** An avatar's own action is evaluated in a frozen world too; the tick is not (below), so nothing expires
  while the world is frozen.

### The tick (D10)

`world_tick` comes from the periodic runner's package tick: at most every 30 s, in practice every
`server.world_admin_tick_interval_seconds` (default 60 s), and the runner skips it while the world is frozen or the
task queue paused (`tick()` itself has no freeze check). Order:

1. **Expiry** — every hidden/open run past `expires_at` turns `failed`.
2. **Reference check** — per live run, each binding (`check_binding`) and each leaf type's `validate(params,
   bindings)`; a binding whose entity is definitely gone, or a type that was not registered at this AND the previous
   tick, turns the run `broken` with the issues. A storage error, a raising validator or a raising type contributor
   skips that run for this tick (neither checked nor evaluated, never marked broken). Deleting a character breaks its
   runs at once, after its rows are deleted (`delete_character` calls `quest_engine.on_character_deleted`; a failed
   delete breaks nothing); everything else is caught here, within one tick.
3. **Full re-evaluation** of every avatar against every live run — this is what notices changes that have no signal
   (stats, time, activity, the silent inventory writes).

## Notices and push (D15)

- A fulfilled step notifies only the avatar that fulfilled it: `create_notification(..., notification_type="quest",
  once_unread=True)`, text "Quest step done: <step text>" (or "Quest complete: <title>" for the last step), with the
  role placeholders rendered. Because of
  `once_unread`, two runs whose current steps have the same text store ONE unread notice.
- A run that opens at start (empty start condition) is announced as a global world event (`category "social"`, text
  "<title>: <summary>"); a run that opens from `hidden` is not announced. When an announced run ends `cancelled`,
  `failed` or `broken` its event is deleted, best effort.
- Every state change pushes the topic `notices` to every bound avatar — no quest topic of its own. The quest book's
  poll listens to `notices` (`packages/player-ui/src/syncEndpoints.ts`: interval 15 s, pushed interval 30 s, minimum
  spacing 15 s — `minSpacingMs >= intervalMs` is the documented rule, so a pushed refetch may wait up to 15 s).

## The player's quest book — `GET /play/quests` (D14)

```json
{"avatar": "A",
 "quests": [{"id", "title", "summary", "state",
             "steps": [{"text", "state", "done_by"?, "done_label"?}],
             "time_left_label"?, "locked"?, "ended_label"?}]}
```

- Built up from whitelists (`quest_book.QUEST_FIELDS`, `STEP_FIELDS`) out of the snapshot: `gm_notes`, roles,
  bindings, every `hint`, every condition and the text of every future step are never sent.
- Listed: every `open` run (newest first), then at most 10 ENDED runs that had opened (latest end first; the store
  query `list_chronicle` filters and cuts in SQL, so a poll decodes at most ten ended snapshots). `hidden` and
  `preparing` runs are not listed, and neither is an ended run that never opened — its title would be a spoiler.
- Steps: an open run shows its done steps and the current one (`state` `done` / `current`); an ENDED run that is not
  `done` shows only its done steps; a `done` run all of them. A done step carries `done_by` (the avatar) and
  `done_label`.
- `time_left_label` only on an open run with a time limit; `locked` only when this avatar is locked (D8);
  `ended_label` only on an ended run. Every `*_label` is a finished server string in the avatar's language.
- Quests are world-wide: every avatar sees the same runs; only `locked` is per avatar. Without an avatar the answer is
  `{"avatar": "", "quests": []}`.

## Admin routes

`/quests` is admin-only for reads AND writes (templates carry GM notes, D12): the prefix is on the auth gate's
`_ADMIN_PREFIXES` and the router carries `Depends(require_admin)`.

| Route | Does |
|---|---|
| `GET /quests/catalog` | Public type descriptors `{conditions, prerequisites, effects, role_kinds}` |
| `GET /quests/templates` | List rows with `open_runs` |
| `GET /quests/templates/{id}` | The full template plus its `issues` |
| `POST /quests/templates` | Create; always a `draft` of origin `admin` |
| `PUT /quests/templates/{id}` | Edit with `base_revision` (D13) |
| `DELETE /quests/templates/{id}` | Refused with 409 `has_open_runs` while a run has not ended |
| `POST /quests/templates/{id}/start` | `{"bindings": {role: binding}}` → the run |
| `GET /quests/runs?state=` | Not-yet-ended runs first, then the newest 50 ended ones; a row carries `binding_labels` and a `game_label` per step-log entry |
| `POST /quests/runs/{id}/cancel` | `{"ok": bool}` (false when it had ended or is unknown) |

Every error detail is an object with a `code`: `{code, message}`, `stale` adds the stored `current` revision, and the
two refusals with an issue list answer `{code, issues}`. Codes: `bad_json` (400, also a body nested too deep to
parse), `bad_request` (400: a text field that is not text, a `time_limit_s` outside 0..2⁶³−1, anything the store
cannot write), `not_found` (404), `revision_required` (428), `stale` (409), `invalid` (422), `has_open_runs` (409),
`refused` (422 at start), `too_large` (413, a body over 256 KiB). The Game-Admin translates the code; issue messages
stay English.

**The ready rule.** `PUT` checks the RESULTING template (stored fields merged with the body): whenever its state would
be `ready` with issues it answers 422 `invalid` and writes nothing — also when the body does not name `state`, so a
ready template that became invalid without an edit (a package it uses was removed) refuses every plain edit. The way
out is to save it with `"state": "draft"` in the same `PUT` as the fix, and set it `ready` again once its issues
are gone.

## What later stages add

Moved out of stage 1 (D17): the `knows_secret` condition with its `secret.learned` signal and a `secret` role kind →
stage 2, together with hints; the giver NPC's prompt block → stage 2; `llm_judgement` → stage 3 (the first stage with
new LLM tasks). Also not in stage 1: effects of any kind, generated objects, LLM authoring, automatic quests and their
caps, repeat, stories, import/export, a `quests` config section.

| Stage | Adds |
|---|---|
| 1 | Hand-made quests are playable (this document) |
| 2 | Quests put things into the world: object effects, run objects with lifetimes and cleanup, rewards, hints as secrets, media generation |
| 3 | The LLM writes quests: authoring pipeline, "Generate with LLM", automatic NPC-giver quests with caps |
| 4 | Stories: a frame, chapters generated during play, summaries, approval mode |
| 5 | Reuse across worlds: repeat modes, dependencies, role binding on import, `quest` / `story` pack types |
