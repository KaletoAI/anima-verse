# LLM Prompt Templates

All prompts that go to an LLM live as Markdown files under
`shared/templates/llm/` and are rendered at runtime via Jinja2
([app/core/prompt_templates.py](../app/core/prompt_templates.py)).

This document catalogs every template under `shared/templates/llm/tasks/`
and `shared/templates/llm/chat/` — its purpose, where it is called from, and
which `task` (in `llm_routing`) it uses for model selection. Completeness is
not a promise, it is checked: `scripts/smoke_docs_llm_templates.py` fails when
a file exists that no row here names (that guard was written because the list
had quietly fallen 17 templates behind).

The `task` column is the routing key handed to `llm_call`, which is often NOT
the template name — `consolidation_scene` routes as `consolidation`,
`scene_photo` as `image_prompt`. Unrouted tasks fall back through
`llm_router.fallback_parent`.

## Layout

```
shared/templates/llm/
├── chat/      # chat + thought composites, rendered with render()
├── skills/    # name + description metadata per skill (load_skill_meta)
└── tasks/     # one per llm_call() task, split into "## system" / "## user"
```

A skill package brings its own templates along: `plugins/<pkg>/templates/llm/`
is searched before the shared directory (`prompt_templates.template_search_dirs`),
which is where `tasks/instagram_caption.md` and every `skills/<verb>.md` of a
migrated package live.

| Template | Task | Caller | Purpose |
|---|---|---|---|
| `extraction_memory.md` | `extraction` | `memory_service.extract_memories_from_exchange` | After each chat turn: extract semantic facts + commitments |
| `extraction_chat_state.md` | `extraction_chat_state` | `routes/chat._extract_context_from_last_chat` (preview: `template_preview`) | Pull removed outfit pieces, the pose key from the shown menu + free detail, and stat deltas out of a chat reply |
| `consolidation_daily.md` | `consolidation` | `memory_service._consolidate_episodics_to_daily` | Compress one day's episodic memories into a 3-5 sentence summary |
| `consolidation_weekly.md` | `consolidation` | `memory_service._consolidate_daily_to_weekly` | Compress a week's daily summaries (5-8 sentences) |
| `consolidation_monthly.md` | `consolidation` | `memory_service._consolidate_weekly_to_monthly` | Compress a month's weekly summaries (5-10 sentences) |
| `consolidation_today.md` | `consolidation` | `history_manager._create_daily_summary` | Roleplay summary of today's chat (5-8 sentences, past tense) |
| `consolidation_history_summary.md` | `consolidation` | `history_manager.create_summary` | Sliding-window summary of older chat history (2-3 sentences) |
| `consolidation_daily_diary.md` | `consolidation` | `routes/diary._generate_summary_sync` | First-person diary entry from a day's events |
| `perceive_action.md` | `thought` | `act_engine` (passed as `perception_template="tasks/perceive_action.md"`) | Perception prompt of an AgentLoop bump: a character notices someone else's action and may react |
| `spell_detect.md` | `spell_detect` | `spell_engine` | Detect whether the avatar's chat message contains a magical/ritual cast that matches one of the spells in their inventory |
| `extraction_thought.md` | `extraction` | `memory_service.extract_memories_from_exchange` (the monologue branch) | Same extraction as `extraction_memory.md`, but for a turn without a partner |
| `consolidation_scene.md` | `consolidation` | `scene_manager` (scene summary) | Summarize one finished room scene from its transcript |
| `intro_memory.md` | `intro_memory` | `routes/content_packs.py` | First memories for a character that arrives through a content pack |
| `stat_effects.md` | `extraction_chat_state` | `stat_effects.evaluate` | Derive stat deltas for a situation from the character's stat list |
| `speech_retry.md` | the tool decision's own task | `streaming.StreamingAgent._render_speech_retry` | B-lite: the RP contained spoken lines but no speech verb — a targeted retry that offers only the speech tools |
| `storyteller_react.md` | `storyteller` | `act_engine` | The storyteller narrates what happens around an action |
| `translate_text.md` | `translation` | `routes/assist.py` (`POST /assist/translate`) | Admin-UI translation helper |
| `prompt_helper.md` | `image_prompt` | `routes/assist.py` (`POST /assist/prompt-help`) | Improve an image/surface prompt from the field it was typed in |


### Relationships

| Template | Task | Caller | Purpose |
|---|---|---|---|
| `relationship_summary.md` | `relationship_summary` | `chat_engine.post_process_response` | Sentiment + romantic-delta after a user-chat exchange |
| `relationship_summary_pair.md` | `relationship_summary` | `relationship_summary._generate_summary` | Narrative summary of one character's view of another |
| `relationship_summary_romantic_interests.md` (in `plugins/attraction/templates/`) | `relationship_summary` | `plugins/attraction/extraction.py` (`extract_romantic_interests`) | One-time extraction of romantic preferences from personality text; without the package the field stays unset |

### Random World Events

| Template | Task | Caller | Purpose |
|---|---|---|---|
| `random_event_general.md` | `random_event` | `random_events._generate_event` | Atmospheric event for a location |
| `random_event_escalation.md` | `random_event` | `random_events._escalate_event` | Escalate an unanswered disruption/danger event |
| `random_event_secret_hint.md` | `random_event` | `random_events._try_generate_secret_hint_event` | Subtle event hint about a hidden secret |
| `random_event_validate_solution.md` | `random_event` | `random_events.validate_solution` | Check whether an action plausibly resolves an event |
| `random_event_solution_rp.md` | `thought` | `random_events._generate_solution_rp` | Character RP-describes how they resolve the event |
| `random_event_resolved_image.md` | `random_event` | `event_images` | Rewrite the event's image prompt for the resolved state |

### Story Arcs

| Template | Task | Caller | Purpose |
|---|---|---|---|
| `story_arc_generation.md` | `consolidation` | `story_engine.generate_arc` | Generate a multi-character mini-storyline |
| `story_arc_advancement.md` | `consolidation` | `story_engine.advance_arc` | Advance an arc by one beat after an interaction |
| `story_arc_resolve.md` | `consolidation` | `story_engine.resolve_arc` | Close an arc with résumé + per-character outcomes |

### Image / Vision

| Template | Task | Caller | Purpose |
|---|---|---|---|
| `image_prompt_scene.md` | `image_prompt` | `routes/chat._generate_image_prompt` | Extract a visual scene from chat narrative |
| `image_prompt_improver.md` | `image_prompt` | `skills/image_regenerate.py` | Modify an existing image prompt based on user feedback |
| `image_prompt_enhance.md` | `image_prompt` | `prompt_adapters._llm_enhance` | Workflow-specific stylistic rewrite of an image prompt |
| `image_prompt_compose.md` | `image_prompt` | `prompt_compose_llm` (`TEMPLATE`) | Compose the facts of a render occasion into one image prompt |
| `scene_photo.md` | `image_prompt` | `scene_photo` | Distill a photo prompt out of a room transcript |
| `image_analysis.md` | `image_recognition` | `plugins/instagram/skill_post.py` (`_analyze_image`) | Vision-LLM objective image description (every vision call resolves `image_recognition`; `image_analysis` is the queue label) |
| `instagram_caption.md` (in `plugins/instagram/templates/`) | `instagram_caption` | `plugins/instagram/skill_post.py` | Vision-LLM Instagram post caption |
| `animation_prompt.md` | `instagram_caption` | `routes/instagram`, `character_ops` (suggest-animate) | Image-to-video motion prompt |

### Skills (agent-callable)

| Template | Task | Caller | Purpose |
|---|---|---|---|
| `outfit_generation.md` | `outfit_generation` | `skills/outfit_creation_skill.py` | Generate a coherent outfit as a list of pieces |
| `secret_generation.md` | `secret_generation` | `secret_engine.generate_secrets` | Generate plausible secrets for a character |
| `retrospect.md` | `consolidation` | `plugins/retrospect/skill.py` | Self-reflection — extract beliefs + improvement intentions |

### Room furnishing / props (world building)

Furnish v2 (`development_instructions/plan-furnish-v2.md`) — stage 1 is split
into "what does the room need" and "what does the library already have";
`furnish_select` / `furnish_new` are gone.

| Template | Task | Caller | Purpose |
|---|---|---|---|
| `furnish_needs.md` | `furnish` (label `needs`) | `room_furnish._phase_needs` | Stage 1a: the room's complete need list (kind, category, count, mount, size, style, marker) invented from its purpose alone — the library is not in the prompt |
| `furnish_match.md` | `furnish` (label `match`) | `room_furnish._phase_needs` | Stage 1b: map the setting-filtered prop catalog (short ids `#n`) onto that need list; every unmatched need is built as a new prop |
| `furnish_place.md` | `furnish` (label `place`) | `furnish_place.run` (via `room_furnish._phase_place`) | Stage 2: relational placement plan per mount pass (anchors `around` / `under` / `wall_above` / `at_opening` / `above` / `on`), with one repair round per failing pass; `furnish_solver` turns it into metres |
| `room_description_sync.md` | `room_description_sync` | `room_description_sync.propose` | Rewrite a room's description so it names the props that now stand in it — preview in the Furnish dialog, the admin decides |
| `prop_mount_classify.md` | `prop_mount_classify` | `props_mount.classify_mounts` | Classify library props into `floor` / `wall` / `ceiling` / `surface` (batched); the guess lands as `mount_suggested` and the admin confirms it in the Props tab |
| `roof_design.md` | `roof_design` | `roof_model` | Pick form, pitch and overhang of a building's roof from its footprint |
| `world_dev_validate.md` | the model chosen in the dialog (`routes/world_dev.py`); `npc_ops` uses `npc_generate` | `routes/world_dev.py`, `npc_ops` | Check a world-dev draft against its schema and list what is wrong |

### Temporary NPCs

| Template | Task | Caller | Purpose |
|---|---|---|---|
| `npc_generate.md` | `npc_generate` | `npc_ops.generate_npc_blocking` | Write the sheet of a temporary NPC from a briefing |
| `npc_repair.md` | `npc_generate` | `npc_ops` (the repair turn) | Hand a rejected NPC sheet back with what has to change |
| `npc_action.md` | `npc_action` | `npc_actions` (`TASK`) | One NPC action turn |
| `npc_scene.md` | `npc_scene` | `npc_scenes` (`TASK`) | The director picks who talks to whom in a room |

## Top-level chat composites

### The chat prompt is TWO templates, and the order is a cache contract

`routes/chat._build_chat_prompt` returns `ChatPrompt(system, moment)`:

| Part | Template | Where it goes |
|---|---|---|
| `system` | `chat/chat_stream.md` | the system message |
| `moment` | `chat/chat_moment.md` | appended to the LAST user turn, BEHIND the history |

A backend caches a prompt by its prefix, so one changed byte at the top costs
everything after it — the conversation history included. `chat_stream.md`
therefore holds only what stays put between turns, ordered by how rarely it
changes: first what every character of the world shares (world setup, medium,
the rules and the marker instructions), then this character (language,
identity, partner sheet, tools), then the slow blocks (secrets, summaries,
earlier days and scenes). `chat_moment.md` is the `[SCENE STATE]` of THIS turn
— clock and place, moods, who is present, items, memories, relationships, "This
moment", the SKIP rules — framed so the model reads it as context, not as
something a person said.

Rules for editing them:

- anything that can differ between two turns belongs in `chat_moment.md`,
  never in the system prompt, and never interpolated into a rule text
  (a name inside a rule makes the rule change with the name);
- character-template fields marked `"prompt_volatile": true`, and everything
  stored in `status_effects`, leave the identity block for the scene state;
- the same rule holds for the thought prompt: its tool block is stable, the
  clock is not — keep the clock behind the tools.

`scripts/smoke_chat_prompt_order.py` pins the split: no per-turn variable may
appear in the system template or in its render call, and the block order is
checked against the contract.

### The other two `chat/` templates

| Template | Rendered by | Purpose |
|---|---|---|
| `chat/agent_thought_in_chat.md` | `agent_loop` (instead of `agent_thought.md` when the character is in a running chat) | The same thought turn, but written for a character that is mid-conversation |
| `chat/situational_memories.md` | `memory_situational` (`TEMPLATE`) | Pick the memories that fit the current message |

### `chat/agent_thought.md`

The AgentLoop's slim system prompt. Pre-decision logic in
[app/core/thought_context.py](../app/core/thought_context.py) builds a
dict with only the blocks that have content (inbox, events,
assignments, general task, commitments, outfit-decision, story arc,
retrospective). The template renders nothing for empty blocks.

`birthday_today` is part of the always-present situation data: True
only on the character's own birthday (a day of the WORLD calendar,
stored on the profile as `birthday` = `"<season_key>:<day>"`), and it
renders the single line `- Today is your birthday.` The standing
`Birthday: Summer, day 14` line is NOT built here — it comes
generically from the character template (`prompt_format: "season_day"`)
and therefore only appears in the chat system prompt. Both thought
templates read the key, so `thought_context` always sets it —
`StrictUndefined` would raise on a missing one.

Section ordering reflects priority — what comes first gets more LLM
attention:

1. Identity + situation (always)
2. Inbox (unread chat-history messages)
3. Active events at location
4. Active assignments
5. General task (`character_task` from profile)
6. Open commitments
7. Outfit-decision (after location change or wake)
8. Active story arc
9. Retrospective (existing beliefs/improvements + boost hint when overdue)
10. Tools hint
11. Decision instruction

## Loader API

```python
from app.core.prompt_templates import render, render_task

# Task templates with `## system` / `## user` markers:
system_prompt, user_prompt = render_task("extraction_memory",
    user_display="Player",
    user_message="...",
    character_name="Hellena",
    ...)

# Plain templates (no system/user split):
text = render("chat/agent_thought.md", **context_dict)
```

`StrictUndefined` is enabled — missing placeholders raise loud errors
instead of silently rendering empty.

## Cross-references

- **Task → model routing:** [docs/llm-task-mapping.md](llm-task-mapping.md)
  for the task catalog, the `fallback_parent` rule for unrouted tasks and the
  three admin pages under `/admin/settings → LLM Routing` (Tasks / LLMs /
  Overview) that pick each task's model
- **AgentLoop architecture:** [app/core/agent_loop.py](../app/core/agent_loop.py)
  — continuous worker, importance-weighted round-robin
- **Inbox model:** [app/core/agent_inbox.py](../app/core/agent_inbox.py)
  — chat_messages-backed, last_thought_at cutoff
