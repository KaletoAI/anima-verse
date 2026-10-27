# Decision models

Optional typed decisions from a fast non-generative model. Spec:
`development_instructions/plan-decision-models.md`.

## What it is

A decision model answers questions about a state — `noul` (yes/no), `choice` (one of up to 255
keys), `score` (a point on a scale) — with probabilities, in 10–500 ms, without generating text.
Laya (Apache 2.0), openjev (MIT) and TypeSafe Jev all speak the same protocol:

    POST <base-url>/v1/systemone
    {"model": "", "state": {...}, "questions": {"<name>": {"type": "choice", "instructions": "...",
      "criteria": {"<key>": "<description>", ...}}}}

Response: `{"answers": {"<name>": {"choice"|"noul"|"score": ..., "probabilities": {...}}}}`.

## The contract

`app.core.decision.decide()` returns `None` whenever the caller should take its usual path:
master switch off, point unknown or `off`, no usable endpoint, timeout/HTTP/JSON error, an answer
that does not fit, or mode `shadow`. It never raises. Nothing may depend on a decision model.

## Configuration — `/admin/settings → Decision models`

- **Endpoints:** master switch + list of `{name, url, api_key, model, enabled}`. With llama-swap
  the URL is `http://<host>:8080/upstream/<model>` (`POST /v1/systemone` directly on llama-swap is a
  404). Leave `model` empty: jev-serve then routes German text to Laya's multilingual checkpoint;
  `laya` would force the English one. **Test** sends one probe question (30-s timeout, warms a
  cold slot).
- **Points:** per decision point the mode (`off` / `shadow` / `on`), the endpoint list (the first
  decides in `on`; `shadow` asks all), `min_confidence`, `timeout_s`. Read live, no restart.
- **Shadow results:** per point × endpoint × question — calls, errors, latency p50/p95, answers,
  share below the minimum confidence, agreement with the usual path (confident answers only),
  no outcome, taken.

## Confidence

Computed by the client from `probabilities`, never taken from the server: `choice` → probability
of the chosen key, `score` → largest probability, `noul` → `max(p, 1 − p)`. Laya reports
`1 − normalised entropy` and openjev the largest probability as `confidence`; one threshold would
otherwise mean two things.

## Failures

No retry. Three failures in a row block an endpoint for 60 s (shown on the Endpoints page).
Warnings are throttled to one per endpoint and reason per 10 minutes. Shadow calls run in a
background pool (8 at most, further calls are skipped) and never add latency.

## Log and statistics

`logs/decisions.jsonl` (archived monthly like `llm_calls.jsonl`, joins on `trace_id`) and the
`decision_stats` table in `world.db`.

Every call row carries `min_confidence` and, per question, its option keys as `options` (Choice: the
option keys; Score: `"0"` … `"n-1"`; Noul: `yes` / `no`). A call row in mode `shadow` also carries
`state` — what the model was shown, each field as text cut to `STATE_EXCERPT_MAX` = 3000 characters
with the END kept (prefix `…`), since the newest context sits at the end. Rows in mode `on` never
carry the state.

The Shadow results page lists **recent disagreements** below the statistics
(`GET /admin/settings/decision/disagreements?point=&limit=50&include_unsure=false`, limit 1..200,
`decision_log.recent_disagreements`): it reads the last 8 MB of the log, pairs call rows with the
outcome of the same `(point, key)`, skips keys that were `taken`, and lists each question whose
prediction differs from the outcome, newest first, with the state and options of that call. Unsure
answers (below the row's `min_confidence`) are listed only on request; rows written before
`min_confidence` was logged count as confident.

## Decision points of the core

| Point | Where | Question | `on` does |
|---|---|---|---|
| `thought_skip` | `AgentLoop._run_turn`, idle thought without perception, hint or unread inbox | `turn`: `act` / `idle` — asks the template's own question ("do or say something now, or reply SKIP?"); the state carries a mode line (in the middle of a conversation with the player → quiet by default, or on their own) taken from the template the turn uses | `idle` → no LLM turn, outcome `decision_skip` |
| `pose_match` | `pose_catalog.resolve_to_catalog(axis="pose")` after the exact alias | `group`, then `entry` of that group (+ `none`) — a group is described by its poses (label + the default + up to 9 more pose keys spread evenly over the group, as many as fit), an entry by its synonyms — in an entry question of at most 12 options by its `prompt` first, as for expressions; option texts share the budget `_option_budget(n) = max(80, min(220, 1400 // n))` | confident key wins over the embedding; `none` → candidate list |
| `expression_match` | same, `axis="expression"` | `entry` (+ `none`) — an entry is described by its face description (`prompt`) followed by as many synonyms as the budget allows; the face description is offered only while the question has at most 12 options (today 9 incl. `none`), a bigger one gets synonyms only | same |

## Decision points of packages

Registered by the package in its `on_load` module (`origin` = the package); without the package
the point does not exist.

| Point | Package | Where | Question | `on` does | Outcome |
|---|---|---|---|---|---|
| `pair_invite` | `interact` | `interaction.invited` and exact `prop_action.invited` hooks, normal or temporary NPC invitee (never a player), after request locks/transaction exit | `answer`: `accept` / `decline` (`decision_points.invite_questions`; `invite_state`; prop offer pins action/revision/target/semantic and physical roles) | General invitations use `resolve_invite(id,bool)`; exact prop questions use `prop_action_engine.respond(invitee,execution_id,bool)`. No confident answer requests an on-demand reply, never automatic acceptance. | Invitee's explicit `InteractWith` answer; prop questions require the exact `execution_id` and `answer=yes/no`, not a same-pose counter-call |
| `party_join` | `party` | After an invitation is persisted, before its answer is requested. Ordinary NPC invitations exclude avatars and temporary NPCs; destination-bound trips also support temporary NPCs, but avatars always decide in the UI | `answer`: `accept` / `decline` (`decision_points.invite_questions`; state `invite_state`, offer names destination and exact group) | Both choices use `resolve_pending_invite(invite_id, bool)`. A linked plan revalidates consent before joining and moves only under its normal world/queue/access gates. Unsettled decisions fall back to an answer turn: direct on-demand chat/tools for trips, ordinary agent turns for ordinary invitations | Linked `JoinParty` responses include the exact `invite_id`; explicit yes/no is never inferred from prose |

`npc_scenes` may create several pair invitations in one tick, so in mode `on` each of them can wait up
to `timeout_s` in the periodic-jobs thread, one after the other. A decline the model settled writes
one narrator line into the invitee's room (the counterpart of `start_interaction`'s line for a pair
that starts), so the room — and a temporary-NPC inviter that never reads the row back — hears it.

Without a decision-model answer, the `interact` hook queues an explicit
`bump_respond(..., on_demand=True)` turn. Its invitation hint reaches the
chat/tool path even during an active conversation; it is not subject to
autonomous thought HOT-skip or chime substitution. This requested answer
may run during world freeze. Ordinary room reactions and autonomous thoughts
remain frozen; queue pause and world sleep still block all queued answers.
Acceptance remains an `InteractWith` call, never a match on reply prose.
Temporary NPCs use that same explicit answer lane without enabling autonomous
thoughts. Prop questions never inherit consent from general Together or another
object; changing the action revision or physical role allocation invalidates
the pending question. The tool reply path is installed by the `interact`
package; final scene/action-offer prompting is a separate integration.

## Adding a point (core or plugin)

1. `register_point("my_point", label=..., description=..., origin="<package>")` — a plugin in its
   `on_load` module.
2. At the call site: `if decision.is_active("my_point"):` build state + questions, `key = …`,
   `d = decide(...)`; act only on `d.answers.get(...)`; otherwise run the usual path and
   `record_outcome("my_point", key, {...})`; after acting in `on`, `mark_taken("my_point", key)`.
3. The usual path stays complete — the point must work with the master switch off.
