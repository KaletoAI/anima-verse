"""Canonical list of all LLM task types.

This is meant to replace the rigid split into llm_defaults.chat /
llm_defaults.tools / llm_defaults.image_prompt. Instead of roles we have a
flat list of tasks that the llm_routing admin tab maps onto concrete
provider+model pairs via LLM/Order.

Every task also carries a `requirements` profile (see TASK_REQUIREMENTS below)
that states what a model must be able to do for this task — the admin UI
renders it generically from REQUIREMENT_LABELS / MODEL_CLASS_LABELS.
"""
from typing import Dict

from app.core.llm_queue import Priority


# Task catalog: task_id -> {label, priority, category, gate?, thinking?, requirements}
# `gate` = dot path to a bool field in the config. When that field is False,
# NO routing entry is required for this task (feature inactive).
# Task categories — guidance for which LLM kind a task expects.
# Shown as a label next to each task in the admin LLM-Routing UI.
#   "image"  → vision-capable model required (image input)
#   "tool"   → reliable tool-calling / structured-output needed
#   "chat"   → big chat / RP model (creative writing, streaming)
#   "helper" → small/cheap helper model is enough
#
# `thinking` (tool/helper tasks only): True = the task benefits from a
# reasoning/thinking pass, route it to the gateway's thinking alias; absent/False
# = run WITHOUT thinking (the default — extraction/classification/tool-calling
# only get slower and worse with thinking). Drives the "+ All No-Thinking" /
# "+ All Thinking" bulk-assign buttons in the LLM-Routing admin UI. Chat/image/
# embedding tasks ignore this flag (they route to their own models).
TASK_TYPES: Dict[str, Dict[str, object]] = {
    # Streaming / RP
    "chat_stream":        {"label": "Chat (Stream)",            "priority": Priority.CHAT,   "category": "chat"},
    "story_stream":       {"label": "Story (Stream)",           "priority": Priority.HIGH,   "category": "chat",   "gate": "story_engine.enabled"},
    "group_chat_stream":  {"label": "Group-Chat (Stream)",      "priority": Priority.CHAT,   "category": "chat"},
    "storyteller":        {"label": "Storyteller (Action)",     "priority": Priority.CHAT,   "category": "chat"},

    # Tool / Decision LLM
    "extraction":         {"label": "Memory Extraction",        "priority": Priority.NORMAL, "category": "helper"},
    # Chat-state extractor (chat.py): removed outfit pieces + pose + stat deltas
    # from the last chat text. Its own task (formerly filed under "extraction" →
    # indistinguishable from memory extraction in the LLM log). Falls back to the
    # "extraction" routing through resolve_llm's parent fallback as long as it is
    # not assigned separately.
    "extraction_chat_state": {"label": "Chat State Extract (Outfit/Pose/Stats)", "priority": Priority.NORMAL, "category": "tool"},
    "random_event":       {"label": "Random Event",             "priority": Priority.LOW,    "category": "tool",   "gate": "random_events.enabled", "thinking": True},
    "secret_generation":  {"label": "Secret Generation",        "priority": Priority.LOW,    "category": "tool",   "thinking": True},
    "outfit_generation":  {"label": "Outfit Generation",        "priority": Priority.NORMAL, "category": "tool",   "gate": "image_generation.enabled", "thinking": True},
    "send_message":       {"label": "Send Message",             "priority": Priority.NORMAL, "category": "chat",   "gate": "skills.send_message.enabled"},
    "talk_to":            {"label": "Talk-To (Char-to-Char)",   "priority": Priority.LOW,    "category": "chat",   "gate": "skills.talk_to.enabled"},
    "thought":            {"label": "Thought (Fallback)",       "priority": Priority.LOW,    "category": "chat"},
    # "intent" stays as the fallback when a specific intent_* task has no
    # routing (see llm_router.resolve_llm). New code should not use it directly
    # any more — use one of the intent_* sub-tasks instead.
    "intent":             {"label": "Intent (Fallback)",        "priority": Priority.NORMAL, "category": "tool"},
    "spell_detect":       {"label": "Spell Cast Detection",      "priority": Priority.NORMAL, "category": "tool"},
    # Pose consolidation: vector for the similarity match against existing
    # variants (the free-text normalizer is gone — poses come from the catalog,
    # plan-pose-katalog.md).
    "pose_embedding":     {"label": "Pose Embedding",            "priority": Priority.LOW,    "category": "embedding"},
    # `world_dev_validate` removed: validator model is now picked
    # dynamically in the World Dev UI right next to the chat model — no
    # separate task entry to maintain in /admin/settings → LLM Routing.

    # Room furnishing ("✨ Furnish", plan-room-furnish.md): three strict-JSON
    # steps of one job — pick library props, propose the missing pieces,
    # arrange them relationally (the solver turns that into geometry).
    # No thinking: the answers must be a bare JSON object — a reasoning pass
    # only adds prose around it.
    "furnish_select":     {"label": "Furnish: Pick Library Props", "priority": Priority.NORMAL, "category": "tool"},
    "furnish_new":        {"label": "Furnish: Propose New Pieces", "priority": Priority.NORMAL, "category": "tool"},
    "furnish_place":      {"label": "Furnish: Placement Plan",     "priority": Priority.NORMAL, "category": "tool"},

    # LLM-Blender models (docs/llm-blender-models.md): the roof form of ONE
    # building as a small declarative JSON object. Everything the answer says
    # is clamped server-side and shown to the admin BEFORE anything is built,
    # so an unrouted task is not a broken feature — it is the default gable.
    "roof_design":        {"label": "Roof Design (Blender)",       "priority": Priority.LOW,    "category": "tool"},

    # Temporary NPCs, generated without a human in the loop
    # (plan-npc-auto-spawn.md): the same character sheet the manual dialog
    # produces, but the model comes from the routing table because an
    # automatic spawn has nobody to ask. Creative prose in a JSON fence, so it
    # is chat class; unrouted it falls back to `chat_stream` (resolve_llm).
    "npc_generate":       {"label": "NPC Generation (automatic)", "priority": Priority.LOW, "category": "chat"},

    # The action tick (plan-npc-leben § 0 B): one room + one sentence per
    # background NPC, a few times per game hour. The smallest recurring task
    # in the catalog — route it at a SMALL model, or the `npc_*` fallback
    # sends it to `chat_stream` and every idle NPC costs a chat turn.
    "npc_action":         {"label": "NPC action tick", "priority": Priority.LOW, "category": "helper", "gate": "npc.action_tick_enabled"},

    # Summaries
    "consolidation":         {"label": "Consolidation (3-Tier)",   "priority": Priority.LOW, "category": "helper"},
    "relationship_summary":  {"label": "Relationship Summary",     "priority": Priority.LOW, "category": "helper", "gate": "relationships.summary_enabled"},

    # Image / Prompt
    "image_prompt":       {"label": "Image Prompt Enhancer",    "priority": Priority.NORMAL, "category": "helper", "gate": "image_generation.enabled"},
    "image_comment":      {"label": "Image Comment",            "priority": Priority.NORMAL, "category": "helper", "gate": "image_generation.enabled"},
    "instagram_caption":  {"label": "Instagram Caption",        "priority": Priority.NORMAL, "category": "image",  "gate": "skills.instagram.enabled"},

    # Vision
    "image_recognition":  {"label": "Image Recognition",        "priority": Priority.NORMAL, "category": "image",  "gate": "image_generation.enabled"},
    "image_analysis":     {"label": "Image Analysis",           "priority": Priority.NORMAL, "category": "image",  "gate": "image_generation.enabled"},

    # Misc
    "intro_memory":       {"label": "Intro Memory (Fresh Import)", "priority": Priority.NORMAL, "category": "helper"},
    "translation":        {"label": "Translation",              "priority": Priority.NORMAL, "category": "helper"},
}


# Human-readable label per category (used in the admin UI).
CATEGORY_LABELS: Dict[str, str] = {
    "image":  "Image Input",
    "tool":   "Tools Required",
    "chat":   "Large Chat Model",
    "helper": "Small Helper Model",
    "embedding": "Embedding Model",
}


# Display strings for the requirement profile (admin UI renders generically
# from this mapping — key order here is the render order).
REQUIREMENT_LABELS: Dict[str, str] = {
    "tools":              "Tool text format",
    "vision":             "Image input",
    "json":               "Strict JSON",
    "min_context":        "Prompt size (tokens)",
    "model_class":        "Model class",
    "arch":               "Architecture",
    "hallucination_risk": "Hallucination risk",
    "creative":           "Creative writing",
    "language_de":        "German prose",
    "latency_sensitive":  "Latency sensitive",
}


MODEL_CLASS_LABELS: Dict[str, str] = {
    "small":  "Small (up to ~15B)",
    "medium": "Medium (15-70B)",
    "large":  "Large (>70B / frontier API)",
}


# Short badge text per requirement VALUE — the compact soft-requirement line in
# the admin routing UI ("large · dense · fact-critical · DE · interactive").
# Display metadata only: no profile keys, no values are defined here.
#
# A value that is NOT listed renders NO badge. That is how the "hide the
# default" rule is expressed without a second table: `arch: "any"` and the
# False side of the boolean flags simply have no entry, so only what sets a
# task apart from the norm shows up. Booleans are keyed by their lowercase
# string form ("true"/"false") so the table survives the JSON hop to the UI.
# Hard requirements (tools/vision/json/min_context) are rendered as icons and
# are deliberately absent here.
REQUIREMENT_BADGE_LABELS: Dict[str, Dict[str, str]] = {
    "model_class": {
        "small":  "small",
        "medium": "medium",
        "large":  "large",
    },
    "arch": {
        "dense": "dense",
        "moe":   "MoE",
    },
    "hallucination_risk": {
        "low":    "facts uncritical",
        "medium": "facts matter",
        "high":   "fact-critical",
    },
    "creative":          {"true": "creative"},
    "language_de":       {"true": "DE"},
    "latency_sensitive": {"true": "interactive"},
}


# Requirement profile per task — what a model has to bring to do this job.
# Kept in its own table so the catalog above stays a readable one-line-per-task
# list; the loop below attaches each profile to its TASK_TYPES entry, so
# TASK_TYPES[<id>]["requirements"] is the single place the UI reads.
#
# HARD keys (a violation makes the routing unusable):
#   tools        — the answer must hit the TEXT tool-call format of
#                  app/core/tool_formats.py (tag / natural_en / natural_de),
#                  parsed by regex. This repo has NO native function calling,
#                  so "tools" means instruction-following discipline on a text
#                  format, not an OpenAI tools= parameter.
#   vision       — image input required.
#   json         — must return strict JSON, no prose wrapper.
#   min_context  — tokens the prompt regularly occupies (P90 of the observed
#                  input, rounded up the ladder 2048/4096/8192/16384/32768/65536).
# SOFT keys (quality guidance for model selection):
#   model_class       — "small" | "medium" | "large" (see MODEL_CLASS_LABELS).
#   arch              — "dense" | "moe" | "any"; only set it where the
#                       architecture is MEASURABLY the cause. "Repetition" is
#                       not such a reason by itself — A1 measured the chat echo
#                       on dense and MoE models alike (A1.1 § 2.6).
#   hallucination_risk— "low" | "medium" | "high": the cost of invented facts.
#   creative          — creative prose vs. precision/extraction.
#   language_de       — must write good German prose (user-facing or stored
#                       as German text). English-only output (image prompts,
#                       canonical poses) is False.
#   latency_sensitive — someone is actively waiting (user turn, streaming, the
#                       tool phase of a reply); False = background job.
#
# STATUS: mixed. The five creative-chat tasks (`chat_stream`,
# `group_chat_stream`, `talk_to`, `thought`, `send_message`) carry REASONED
# values from section A1 of plan-llm-routing-review.md — measurement in
# .superpowers/sdd/plan-llm-routing-review/task-A1.1-report.md, decisions in
# task-A1.3-report.md. Every OTHER profile is still the first pass derived from
# category + the A0 inventory (development_instructions/llm-routing-review/
# findings.md); sections A2-A5 replace those with reasoned values.
# `pose_embedding` has NO profile on purpose: it does not run over the chat
# providers but over app/core/embedding.py and the /v1/embeddings endpoint.
#
# A1 result that shapes all five chat profiles: the dominant repetition is a
# COPY out of the task's own prompt (the "recent thoughts" block), measured
# across three models on two providers and on a MoE as well as on dense models
# — so it is not an architecture property and `arch` stays "any" (A1.1 § 2.6,
# § 2.7). And the fact complaints traced to a missing data model, not to the
# model: kinship cannot be expressed in `relationships.type` at all, so no
# model can know it (A1.1 § 3.2, findings B11/B12).
TASK_REQUIREMENTS: Dict[str, Dict[str, object]] = {
    # --- Streaming / RP -----------------------------------------------------
    "chat_stream": {
        "tools": True, "vision": False, "json": False, "min_context": 16384,
        "model_class": "large", "arch": "any", "hallucination_risk": "medium",
        "creative": True, "language_de": True, "latency_sensitive": True,
    },
    "story_stream": {
        "tools": False, "vision": False, "json": False, "min_context": 16384,
        "model_class": "large", "arch": "dense", "hallucination_risk": "high",
        "creative": True, "language_de": True, "latency_sensitive": True,
    },
    "group_chat_stream": {
        "tools": True, "vision": False, "json": False, "min_context": 16384,
        "model_class": "large", "arch": "any", "hallucination_risk": "medium",
        "creative": True, "language_de": True, "latency_sensitive": True,
    },
    "storyteller": {
        "tools": True, "vision": False, "json": False, "min_context": 16384,
        "model_class": "large", "arch": "dense", "hallucination_risk": "high",
        "creative": True, "language_de": True, "latency_sensitive": True,
    },

    # --- Tool / decision LLM ------------------------------------------------
    "extraction": {
        # A2: model_class raised to medium — of 84 stored entries read against
        # their source, 5 contradicted it, and every one of those was an
        # attribution error (who said or did it; an intention turned into an
        # accomplished action). That is this task's expensive failure mode, and
        # it is what a smaller model gets wrong. No live evidence for
        # min_context: the path has not fired since 2026-06-07 (findings.md A2).
        "tools": False, "vision": False, "json": True, "min_context": 2048,
        "model_class": "medium", "arch": "any", "hallucination_risk": "high",
        "creative": False, "language_de": True, "latency_sensitive": False,
    },
    "extraction_chat_state": {
        # A2: latency_sensitive corrected to False — chat.py hands the call to
        # run_in_executor WITHOUT awaiting it, from post_process_response, which
        # runs after the stream is complete; no SSE event carries the result.
        # The stat_effects branch is a daemon thread without a turn at all.
        # small confirmed: 0 parse errors and 0 invented piece names in 880 calls.
        "tools": False, "vision": False, "json": True, "min_context": 2048,
        "model_class": "small", "arch": "any", "hallucination_risk": "medium",
        "creative": False, "language_de": False, "latency_sensitive": False,
    },
    "random_event": {
        "tools": False, "vision": False, "json": True, "min_context": 2048,
        "model_class": "medium", "arch": "any", "hallucination_risk": "low",
        "creative": True, "language_de": True, "latency_sensitive": True,
    },
    "secret_generation": {
        "tools": False, "vision": False, "json": True, "min_context": 4096,
        "model_class": "medium", "arch": "any", "hallucination_risk": "low",
        "creative": True, "language_de": True, "latency_sensitive": True,
    },
    "outfit_generation": {
        "tools": False, "vision": False, "json": True, "min_context": 4096,
        "model_class": "medium", "arch": "any", "hallucination_risk": "low",
        "creative": True, "language_de": True, "latency_sensitive": True,
    },
    # `send_message` and `talk_to` are never resolved under their own name
    # (findings [D2]/Q4): both skills only drop the line into the recipient's
    # inbox and return; the answer is written later by the recipient's AgentLoop
    # turn through chat_engine.run_chat_turn, whose LLM comes from
    # resolve_llm("chat_stream"). Their profiles therefore describe the chat
    # turn that actually fulfils them — same requirements as `chat_stream`,
    # except that nobody waits for it (the sending skill does not block).
    "send_message": {
        "tools": True, "vision": False, "json": False, "min_context": 16384,
        "model_class": "large", "arch": "any", "hallucination_risk": "medium",
        "creative": True, "language_de": True, "latency_sensitive": False,
    },
    "talk_to": {
        "tools": True, "vision": False, "json": False, "min_context": 16384,
        "model_class": "large", "arch": "any", "hallucination_risk": "medium",
        "creative": True, "language_de": True, "latency_sensitive": False,
    },
    "thought": {
        "tools": True, "vision": False, "json": False, "min_context": 8192,
        "model_class": "large", "arch": "any", "hallucination_risk": "medium",
        "creative": True, "language_de": True, "latency_sensitive": False,
    },
    "intent": {
        # A3: language_de False -> True. The tool INPUTS are German: of 1255
        # extracted TalkTo/SendMessage/SetActivity inputs 1151 were
        # classifiable — 1115 German, 36 English (104 too short to decide).
        # In a thought turn the prose is thrown away and a
        # spoken line reaches the room ONLY through the speech verb, verbatim
        # (streaming.py:265-279); SetActivity's free-text pose is stored and
        # displayed. creative stays False all the same — the model re-describes
        # what the prose already said, it must not embellish.
        # min_context: the log under-reports this task. `task=intent` is 213 of
        # 974 calls; the thought turn's tool phase logs as task="thought" /
        # llm_role="Tool-LLM" (A3.1 § 0). Over the FULL population P90 is 6513
        # tokens, max 7075 -> 8192 confirmed.
        # latency_sensitive True per the definition above ("the tool phase of a
        # reply"), mixed case like `consolidation`, all three callers: in
        # `single` mode the entry is resolved only as a mode discriminator
        # (chat_engine.py:367 -> dependencies.determine_mode) and never called,
        # the chat tool phase runs after the visible answer (chat_engine.py:604)
        # and the thought one blocks only a background turn — but either way
        # the world state the player is watching waits for it: chat path P50
        # 21 s / P90 99 s, thought path P50 60 s / P90 105 s (August).
        # hallucination_risk stays high: an invented call EXECUTES (19 of 283
        # SetLocation targets were outside the catalog, invented dialogue lands
        # in the room as if spoken). model_class stays medium: format
        # discipline was perfect over 974 answers, and the content failures
        # traced to the hard-wired action mapping fixed in 37e2214 — nothing
        # measured argues for large.
        "tools": True, "vision": False, "json": False, "min_context": 8192,
        "model_class": "medium", "arch": "any", "hallucination_risk": "high",
        "creative": False, "language_de": True, "latency_sensitive": True,
    },
    "spell_detect": {
        # A3: all ten confirmed. latency_sensitive True is hard — both call
        # sites await the call before the turn continues AND hold the player's
        # own words back, because chat_substitute replaces them in the room
        # (play.py:1064, chat.py:811); measured 5.6/5.9 s. small stays: the
        # prefilter (every incantation token verbatim, spell_engine.py:128)
        # reduces the job to picking among the avatar's own spell items, and
        # small + German prose is an established pair here (translation,
        # intro_memory, image_comment). hallucination_risk medium, not low: an
        # invented spell_id cannot fire (catalog check :199, confidence < 60
        # discarded), but chat_substitute is unvalidated German prose that
        # REPLACES the player's line and is what the room then reacts to.
        "tools": False, "vision": False, "json": True, "min_context": 2048,
        "model_class": "small", "arch": "any", "hallucination_risk": "medium",
        "creative": False, "language_de": True, "latency_sensitive": True,
    },

    # --- Room furnishing ----------------------------------------------------
    # A3: two decisions are shared by all three. (1) latency_sensitive stays
    # False: the job is a daemon thread tracked in the TaskQueue, it survives a
    # restart (_resume_phase), it ends in a notification, and the admin UI polls
    # at 3 s while the dialog is open and 15 s while it is CLOSED, precisely so
    # the dialog may be closed while it runs (FurnishDialog.tsx:70-125). Between
    # the LLM stages the chain waits up to 30 min on mesh generation, so seconds
    # of LLM latency are not what anyone waits on. (2) hallucination_risk is low
    # wherever the output is checked against a catalog AND against the admin —
    # nothing reaches the room without passing a validator and the review gate
    # (confirm/accept, room_furnish.py:869/888).
    "furnish_select": {
        # A3: hallucination_risk high -> low. An invented prop_id is dropped by
        # _valid_existing against the filtered library (:522-525) — it reaches
        # neither the admin nor the room; the cost is a missing pick. medium
        # stays because the footprint budget is NOT enforced at select time
        # (the solver only catches the overflow later as "area budget
        # exhausted"), so the arithmetic is the model's job. min_context stays
        # 4096 with no measurement (n=0): the user prompt carries the WHOLE
        # filtered library, one line per prop, and the library only grows —
        # furnish_new writes its inventions back into it (create_prop, :567).
        "tools": False, "vision": False, "json": True, "min_context": 4096,
        "model_class": "medium", "arch": "any", "hallucination_risk": "low",
        "creative": False, "language_de": False, "latency_sensitive": False,
    },
    "furnish_new": {
        # A3: the only one of the three whose main output is checked against
        # NOTHING — name/description are free text, and after the confirm gate
        # the description becomes the prop's image prompt (props.py:1061-1067)
        # and a mesh in the shared library, so hallucination_risk stays medium.
        # creative True confirmed (inventing pieces is the job); language_de
        # False for the same reason every image prompt is English.
        "tools": False, "vision": False, "json": True, "min_context": 4096,
        "model_class": "medium", "arch": "any", "hallucination_risk": "medium",
        "creative": True, "language_de": False, "latency_sensitive": False,
    },
    "furnish_place": {
        # A3: hallucination_risk medium -> low. No invented value can place a
        # piece: unknown prop, unknown anchor and an unresolved ref all come
        # back as `unplaced` with a reason, feed the ONE re-plan round and end
        # in the review UI; count is clamped to 1..12 and an unknown `facing`
        # is not rejected but simply falls through to the room-facing branch
        # (furnish_solver.solve :390-423). Measured 509/541 input tokens including the re-plan errors
        # block; 2048 is the bottom rung and holds even for a 20-piece plan.
        "tools": False, "vision": False, "json": True, "min_context": 2048,
        "model_class": "medium", "arch": "any", "hallucination_risk": "low",
        "creative": False, "language_de": False, "latency_sensitive": False,
    },
    "roof_design": {
        # The smallest structured-output task in the catalog: a handful of
        # lines in, one flat JSON object out. hallucination_risk low because
        # NOTHING the model returns survives unchecked — an unknown form or an
        # out-of-range pitch is clamped in `roof_model.validate_description`,
        # and the admin sees and edits every number before the build runs.
        # latency_sensitive True: this one call sits between the button and
        # the dialog the user is looking at.
        "tools": False, "vision": False, "json": True, "min_context": 2048,
        "model_class": "small", "arch": "any", "hallucination_risk": "low",
        "creative": True, "language_de": False, "latency_sensitive": True,
    },
    "npc_action": {
        # Two fields out, a room list and a standing task in. Nothing the
        # model returns survives unchecked: an unknown room id is discarded
        # whole and a move the block rules deny never happens, so
        # hallucination_risk is low. language_de True — the activity sentence
        # is written in the language of the NPC's standing task, which is the
        # world's language. latency_sensitive False: nobody waits for it, it
        # is a background tick.
        "tools": False, "vision": False, "json": True, "min_context": 2048,
        "model_class": "small", "arch": "any", "hallucination_risk": "low",
        "creative": True, "language_de": True, "latency_sensitive": False,
    },

    # --- Summaries ----------------------------------------------------------
    "consolidation": {
        # A2: min_context 2048 -> 4096, measured input maximum 4390 tokens (the
        # retrospect branch alone has P90 3286). latency_sensitive stays False
        # and is now confirmed: history_manager became fire-and-forget, and the
        # slowest branches (daily/today, P50 55-67 s) are pure background jobs.
        # json=False holds for the summary branches ONLY — retrospect and
        # story_arc_* share this routing entry and demand strict JSON (Q3).
        "tools": False, "vision": False, "json": False, "min_context": 4096,
        "model_class": "medium", "arch": "any", "hallucination_risk": "high",
        "creative": False, "language_de": True, "latency_sensitive": False,
    },
    # Two templates share this task and disagree on the output format:
    # relationship_summary.md returns JSON (sentiment/romantic deltas), while
    # relationship_summary_pair.md returns a 1-3 sentence narrative summary that
    # is stored as the relationship text. `json` describes the stricter branch.
    "relationship_summary": {
        "tools": False, "vision": False, "json": True, "min_context": 2048,
        "model_class": "medium", "arch": "any", "hallucination_risk": "high",
        "creative": False, "language_de": True, "latency_sensitive": False,
    },

    # --- Image / prompt -----------------------------------------------------
    "image_prompt": {
        "tools": False, "vision": False, "json": False, "min_context": 2048,
        "model_class": "small", "arch": "any", "hallucination_risk": "medium",
        "creative": False, "language_de": False, "latency_sensitive": True,
    },
    "image_comment": {
        "tools": False, "vision": False, "json": False, "min_context": 2048,
        "model_class": "small", "arch": "any", "hallucination_risk": "low",
        "creative": False, "language_de": True, "latency_sensitive": False,
    },
    "instagram_caption": {
        "tools": False, "vision": True, "json": False, "min_context": 2048,
        "model_class": "medium", "arch": "any", "hallucination_risk": "medium",
        "creative": True, "language_de": True, "latency_sensitive": True,
    },

    # --- Vision -------------------------------------------------------------
    "image_recognition": {
        "tools": False, "vision": True, "json": False, "min_context": 2048,
        "model_class": "medium", "arch": "any", "hallucination_risk": "medium",
        "creative": False, "language_de": True, "latency_sensitive": True,
    },
    "image_analysis": {
        "tools": False, "vision": True, "json": False, "min_context": 2048,
        "model_class": "medium", "arch": "any", "hallucination_risk": "medium",
        "creative": False, "language_de": True, "latency_sensitive": False,
    },

    # --- Misc ---------------------------------------------------------------
    "intro_memory": {
        "tools": False, "vision": False, "json": False, "min_context": 4096,
        "model_class": "small", "arch": "any", "hallucination_risk": "medium",
        "creative": True, "language_de": True, "latency_sensitive": True,
    },
    "translation": {
        "tools": False, "vision": False, "json": False, "min_context": 4096,
        "model_class": "small", "arch": "any", "hallucination_risk": "medium",
        "creative": False, "language_de": True, "latency_sensitive": True,
    },
}


for _task_id, _profile in TASK_REQUIREMENTS.items():
    TASK_TYPES[_task_id]["requirements"] = _profile
del _task_id, _profile


def _get_by_path(obj: dict, path: str):
    parts = path.split(".")
    cur: object = obj
    for p in parts:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
    return cur


def is_task_gated_off(task: str, cfg: dict) -> bool:
    """True when the task is not needed because its feature gate is off."""
    entry = TASK_TYPES.get(task)
    if not entry:
        return False
    gate = entry.get("gate")
    if not gate:
        return False
    val = _get_by_path(cfg, str(gate))
    return val is False


def get_default_priority(task: str) -> int:
    entry = TASK_TYPES.get(task)
    if entry:
        return int(entry.get("priority", Priority.NORMAL))
    return int(Priority.NORMAL)