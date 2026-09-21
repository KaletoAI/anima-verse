# LLM Task Mapping

Every LLM call in this repo names a **task**. This document lists the task
catalog, how a task is resolved to a concrete provider + model, and the admin
pages that edit that mapping.

## Architecture

Routing is **task-based**: no code names a model. A caller passes a task id
(`llm_call(task="…")`, `resolve_llm("…")`), and `app/core/llm_router.py`
resolves it against the `llm_routing` list in the world's `config.json`.

`llm_routing` is a list of **LLM entries** — one per provider+model pair:

```jsonc
{"name": "Big RP", "enabled": true, "preload_on_startup": false,
 "provider": "LocalAI", "model": "…", "temperature": 0.8, "max_tokens": 2048,
 "chat_template": "", "tasks": [{"task": "chat_stream", "order": 1}]}
```

### Cache lanes — how many calls a model runs at once

`max_concurrent` on an entry (admin label **"Lanes"**, LLMs page) is not a
throughput dial, it is how many different **prompt beginnings** may live on
that model at the same time. One lane = one serialized execution slot of that
model; it remembers the **cache key** of its last call, `<prompt class>:<character>`
(`chat:Pip`, `thought:Pip`, `tool:Pip`, `bg:`). A call takes the lane
that already holds its key, else an unused one, else the least recently used
(`app/core/llm_lanes.py`).

Why per model and not per provider: a prompt cache lives on the model instance
that serves the alias. One router provider (an AI-Hub, say) hands several
aliases to several hosts, so the provider is the wrong unit. The provider's own
`max_concurrent` still sizes the channel's worker pool and caps GPU jobs — it
does not limit LLM calls any more.

Entries that share provider+model share ONE set of lanes (several sampling
profiles — a temperature per task group — on one backend slot). A different
temperature touches neither the lane nor the prompt cache: the cache key is
`<prompt class>:<character>`, and sampling happens after the prompt is read.
The LLMs page therefore keeps `max_concurrent` ONE number per model: a change
is written to every entry on that model, an entry that joins a model takes its
number, the field names who shares it, and a config that still disagrees is
aligned to the value in force when the page opens. `lane_count_in()`
(`app/core/llm_lanes.py`) is the one folding rule behind the pool, the
Overview page and `/admin/agent-loop` — highest value among the enabled
entries.

What the rules guarantee, in short:

- a conversation is not evicted by background work while it is fresh, and a
  background call waits a few seconds for its own lane before taking a foreign
  one;
- a waiting call of a higher class goes first, and one that has waited too long
  counts one class higher, so background work cannot starve;
- a turn that hands its lane over for its own nested tool call gets that lane
  back before anyone else;
- the agent loop starts as many replies as there are free lanes — there is no
  second parallelism knob.

Live state, per model: **`/admin/agent-loop`** — lanes free/busy, the key on
each lane, who waits and why, and the share of prompt tokens the backend served
from its cache (`tokens.cached` in `logs/llm_calls.jsonl`; "not reported" stays
distinct from 0 %).

A task's **chain** is its assignments across all entries, sorted by `order`
(1 = primary). `resolve_llm` walks that chain and returns the first entry whose
provider exists, is available and whose model is not in model cooldown; a
disabled entry (`enabled: false`) is skipped entirely. Per enabled entry a
`(task, order)` pair must be unique — `_validate_llm_routing` in
`app/routes/admin_settings.py` rejects a save that violates it, and the admin
UI writes the order as position 1..n per task, so the constraint holds by
construction.

Resolution order in `resolve_llm(task, agent_name)`:

1. the task must be **enabled** (`app/core/llm_task_state.py` — persistent
   `llm_task_state.disabled_tasks` plus a runtime-only set for presets like
   `world_dev`); a disabled task resolves to `None` and callers take their
   own fallback path.
2. **character override** — `llm_routing_overrides[task]` in the character
   config, `"Provider::Model"` or a bare `"Model"`, used only when that
   provider is available.
3. the **global chain** as described above.
4. **fallback parent** when the task has no chain at all (see below).
5. `None`.

### The unrouted-task rule

`llm_router.fallback_parent(task)` is the ONE place this rule lives — a pure
function without config access, so `resolve_llm`, the admin Tasks page and the
Overview page all show the same answer:

| Task shape | Parent |
|---|---|
| `intent_*`, `thought_*`, `extraction_*` | `intent` / `thought` / `extraction` |
| `furnish`, `prop_mount_classify`, `room_description_sync` | `intent` |
| `npc_*` | `chat_stream` |
| anything else | none — the task simply has no LLM |

A fallback is a convenience, not a recommendation: an unrouted `npc_action`
runs every idle background NPC on the big RP model.

### Task metadata

Each entry in `app/core/llm_tasks.py` → `TASK_TYPES` carries:

- **category** (`chat`, `tool`, `image`, `helper`, `embedding`) — which kind of
  model the task expects; `CATEGORY_LABELS` supplies the UI label.
- **priority** (`CHAT`, `HIGH`, `NORMAL`, `LOW`) — the provider queue's ordering.
- **gate** (optional) — a dot path to a bool in the config. While that flag is
  off, the feature is inactive and the task needs no LLM (`is_task_gated_off`).
- **thinking** (tool/helper tasks) — the task benefits from a reasoning pass.
- **requirements** — a profile of what a model must bring (hard: `tools`,
  `vision`, `json`, `min_context`; soft: `model_class`, `arch`,
  `hallucination_risk`, `creative`, `language_de`, `latency_sensitive`). Only
  `pose_embedding` has none, because it does not run over the chat providers.

`scripts/smoke_llm_task_catalog.py` guards the catalog: no removed id may come
back, every task except `pose_embedding` has a requirements profile, every
preset names a real id, the `fallback_parent` table matches, and every catalog
id must occur as a string literal in some caller under `app/` or `plugins/`
(the dead-task guard).

---

## Admin routing pages

`/admin/settings → LLM Routing (Advanced)` is a paged section
(`llm_routing.pages` in `app/core/config_schema.py`, rendered by
`static/admin/settings-routing.js`) with three sub-pages:

- **Tasks** — the working surface: one card per catalog task with its
  requirement badges, its active toggle, its gate note and its ordered LLM
  chain (↑ ↓ ✕). Problems are named on the card: no LLM assigned (plus the
  fallback hint from `fallback_parent`), entry disabled, provider missing,
  model not on the server, capability mismatch against
  `shared/config/model_capabilities.json`. "Assign LLM ▾" picks an existing
  entry or opens an inline "New LLM…" form; each category group can assign one
  LLM to all of its unassigned tasks at once. Filters: search, category,
  thinking, only problems. A separate block lists assignments to task ids that
  are no longer in the catalog, with a remove button.
  **Order is written as the position in the chain (1..n), not typed in.**
- **LLMs** — the per-entry editor: name, enabled, preload on startup, provider,
  model, temperature, max tokens, chat template. The tasks of an entry are
  read-only chips here; deleting an entry asks inline and names the tasks that
  would lose their only LLM.
- **Overview** — read-only mirror of what the server would route right now.

### `GET /admin/settings/llm-routing/effective`

The Overview page reads this endpoint (`app/routes/admin_settings.py`), which
is a thin wrapper around `llm_router.explain_routing()`. It resolves the
**saved** config — provider availability, model cooldowns and task state
included, character overrides NOT applied — and returns `providers`, `entries`
and one row per task with `chain`, `resolved`, `via`
(`direct` / `fallback` / `gated_off` / `disabled` / `none`) and a `reason`.
Unsaved edits on the other two pages are not part of it.
`GET /admin/settings/llm-tasks` serves the catalog itself (label, category,
`thinking`, `requirements`, `priority`, `gate`, `gated_off`, `fallback`) plus
the label tables the UI renders the badges from.
`scripts/smoke_llm_routing_explain.py` checks `explain_routing` against
hand-derived expectations; `scripts/check_routing_model.js` checks the chain
mutations of the UI model.

---

## Task catalog

27 tasks, in the order they stand in
[`app/core/llm_tasks.py`](../app/core/llm_tasks.py).

### Streaming / RP

| Task id | Label | Category | Gate | Caller | Purpose |
|---|---|---|---|---|---|
| `chat_stream` | Chat (Stream) | chat | — | `routes/chat.py`, `core/streaming.py` | The main conversation with the user. Also the fallback parent of every `npc_*` task. |
| `story_stream` | Story (Stream) | chat | `story_engine.enabled` | `routes/story.py` | Story mode: longer narrative text over the same streaming pipeline. |
| `storyteller` | Storyteller (Action) | chat | — | `core/act_engine.py`, `models/storyteller.py` | The storyteller reaction to a player action. |

The story player behind `story_stream` (`routes/story.py`, `routes/story_dev.py`)
has no UI today — it is kept for a later reuse.

### Tool / decision LLM

| Task id | Label | Category | Gate | Caller | Purpose |
|---|---|---|---|---|---|
| `extraction` | Memory Extraction | helper | — | `core/memory_service.py`, `plugins/knowledge/extract_utils.py` | Structured knowledge out of a chat exchange (facts, commitments). JSON. |
| `extraction_chat_state` | Chat State Extract (Outfit/Pose/Stats) | tool | — | `routes/chat.py`, `core/stat_effects.py` | Removed outfit pieces, the pose key + free detail and stat deltas out of the last reply. Falls back to `extraction`. |
| `random_event` | Random Event | tool | `random_events.enabled` | `core/random_events.py` | Generation, escalation, validation and RP text of location events. |
| `secret_generation` | Secret Generation | tool | — | `core/secret_engine.py` | Secrets for characters that have none. Background job. |
| `outfit_generation` | Outfit Generation | tool | `image_generation.enabled` | `skills/outfit_creation_skill.py` | A coherent outfit as a list of pieces. |
| `thought` | Thought (agent loop) | chat | — | `core/thoughts.py`, `core/agent_loop.py` | The autonomous turn of an idle character. |
| `intent` | Intent / tool calls | tool | — | `core/chat_engine.py`, `core/thoughts.py`, `core/act_engine.py` | The Tool-LLM: it turns prose into skill calls for chat AND thought turns. Also the fallback parent for the tool-class tasks below. |
| `spell_detect` | Spell Cast Detection | tool | — | `core/spell_engine.py` | Whether the avatar's message casts one of the spells in their inventory. |
| `pose_embedding` | Pose Embedding | embedding | — | `core/embedding.py` | The similarity vector for the pose catalog match. Runs over `/v1/embeddings`, not the chat queue. Only reached when `embedding.backend` is `external`, or `auto` and this task is routed; `internal` uses the built-in fastembed model on CPU. |

### World building: room furnishing / props

Furnish v2 (`development_instructions/plan-furnish-v2.md`): the three
strict-JSON steps of one job share ONE routing task (`furnish`) and stay apart
in the LLM log by their call labels `needs: <room>` / `match: <room>` /
`place: <room>`. The v1 task ids `furnish_select` / `furnish_new` and the
per-step ids `furnish_needs` / `furnish_match` / `furnish_place` no longer
exist as routing tasks — only as template file names.

| Task id | Label | Category | Caller | Templates | Purpose |
|---|---|---|---|---|---|
| `furnish` | Furnish (needs · match · placement) | tool | `core/room_furnish.py`, `core/furnish_place.py` | `tasks/furnish_needs.md`, `tasks/furnish_match.md`, `tasks/furnish_place.md` | Stage 1a the room's need list without the library; 1b the match of the setting-filtered catalog onto it; stage 2 the relational placement plan per mount pass. `core/furnish_solver.py` turns the plan into metres — the LLM never names a coordinate. |
| `room_description_sync` | Furnish: Sync Room Description | tool | `core/room_description_sync.py` | `tasks/room_description_sync.md` | Rewrites the room description so it names the props that really stand there. Prose, previewed in the Furnish dialog before anything is stored. |
| `prop_mount_classify` | Props: Classify Mount | tool | `core/props_mount.py` | `tasks/prop_mount_classify.md` | Classifies library props into `floor` / `wall` / `ceiling` / `surface` in batches; the answer lands as `mount_suggested` and the admin confirms it. |

### Buildings

| Task id | Label | Category | Caller | Purpose |
|---|---|---|---|---|
| `roof_design` | Roof Design (Blender) | tool | `core/roof_model.py` | The roof form of one building as a small declarative JSON object. Clamped server-side and shown to the admin first, so an unrouted task means the default gable, not a broken feature. |

### Temporary NPCs

| Task id | Label | Category | Gate | Caller | Purpose |
|---|---|---|---|---|---|
| `npc_generate` | NPC Generation (automatic) | chat | — | `core/npc_ops.py` | The character sheet of an automatically spawned NPC — creative prose in a JSON fence. |
| `npc_action` | NPC action tick | helper | `npc.action_tick_enabled` | `core/npc_actions.py` | One room id plus one short activity sentence per background NPC, a few turns per game hour. Route this at a SMALL model. |
| `npc_talk` | NPC conversation reply | chat | — | `core/chat_engine.py` (`chat_llm_task`) | Every chat reply of a temporary NPC — respond lane, chime, exit beat and TalkTo alike. Same prompt as `chat_stream`, its own task so a fast model can be routed. |
| `npc_scene` | NPC scene (director) | helper | — | `core/npc_scenes.py` | One small JSON call per room writes a 2–4 line exchange plus optional pair pose and activities (`npc.conversation_mode = scene`). |

### Summaries

| Task id | Label | Category | Gate | Caller | Purpose |
|---|---|---|---|---|---|
| `consolidation` | Consolidation (3-Tier) | helper | — | `core/memory_service.py`, `utils/history_manager.py`, `core/day_consolidation.py`, `core/story_engine.py`, `core/scene_manager.py`, `routes/diary.py`, `plugins/retrospect/skill.py` | Everything that compresses history: episodic → daily → weekly → monthly memories, chat summaries, the diary entry, story arcs and the retrospect skill. |
| `relationship_summary` | Relationship Summary | helper | `relationships.summary_enabled` | `core/chat_engine.py` | Sentiment and romantic delta of both sides after a chat exchange; the gate is read in the call site, so off means no call and the default deltas. |

### Image / prompt / vision

| Task id | Label | Category | Gate | Caller | Purpose |
|---|---|---|---|---|---|
| `image_prompt` | Image Prompt Enhancer | helper | `image_generation.enabled` | `core/prompt_adapters.py`, `core/scene_photo.py` | Turns a short scene description into a detailed image prompt, in the image family of the selected backend. |
| `instagram_caption` | Instagram Caption | image | `skills.instagram.enabled` | `routes/instagram.py`, `core/character_ops.py`, `plugins/instagram/skill_post.py` | Post caption in the character's voice; also the image-to-video motion prompt. Vision model. |
| `image_recognition` | Vision (analysis · comments · recognition) | image | `image_generation.enabled` | `imagegen/service.py`, `routes/chat.py`, `plugins/instagram/social_reactions.py` | The ONE vision task — every image call resolves it. Objective analysis after a generation, the character's own comment on the picture, and the look at a photo before other characters react to it. `image_analysis` and `image_comment` are queue labels and metadata keys, not routing tasks. |

### Misc

| Task id | Label | Category | Caller | Purpose |
|---|---|---|---|---|
| `intro_memory` | Intro Memory (Fresh Import) | helper | `routes/content_packs.py` | Starting memories for a character imported from a content pack. |
| `translation` | Translation | helper | `routes/assist.py` | Translation between languages. |

---

## GPU tasks (no LLM)

These run on image/audio backends, not on a language model, and are not part of
`llm_routing`:

| Task | Backend | Purpose |
|---|---|---|
| Image generation | `localai` / `a1111` / `civitai` / `together` / `openai_diffusion` | Images from prompts. |
| Image regeneration | same | An existing image again, with changes. |
| TTS | XTTS / F5 / Magpie | Speech audio. |
| Video generation | `openai_video` / `localai_video` / `together_video` | One MP4 from an image. |
| Mesh generation | `openai_mesh` | A 3D model from reference renders. |

---

## Notes

- **Categories are guidance, not a constraint.** The category says which kind of
  model a task expects; nothing stops an admin from routing a task elsewhere.
  The Tasks page flags a capability mismatch (tool calling, vision) against the
  model capability table, but still saves it.
- **Gated tasks need no LLM.** While the gate flag is off the task is not
  reported as a problem anywhere.
- **Character overrides bypass the chain**, per character and per task
  (`llm_routing_overrides`), and are deliberately NOT part of the Overview page
  — that page answers what the server does by default.
- **Streaming bypasses the provider queue** for latency but registers for
  tracking; embeddings bypass it too (`/v1/embeddings`). Everything else is
  queued per provider.

## Cross-references

- [docs/llm-templates.md](llm-templates.md) — which Jinja template belongs to
  which task
- [app/core/llm_tasks.py](../app/core/llm_tasks.py) — the catalog itself, with
  the reasoning behind each requirements profile
- [app/core/llm_router.py](../app/core/llm_router.py) — `resolve_llm`,
  `fallback_parent`, `explain_routing`
