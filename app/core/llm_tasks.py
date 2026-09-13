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
    "thought":            {"label": "Thought (agent loop)",     "priority": Priority.LOW,    "category": "chat"},
    # The tool-class task: the tool phase of a reply resolves it directly —
    # chat_engine loads the Tool-LLM from it for chat AND thought turns
    # (chat_engine.py:421). It is also the anchor llm_router.fallback_parent()
    # sends unrouted tool work to: furnish, prop_mount_classify,
    # room_description_sync and any "intent_<sub>" id.
    "intent":             {"label": "Intent / tool calls",      "priority": Priority.NORMAL, "category": "tool"},
    "spell_detect":       {"label": "Spell Cast Detection",      "priority": Priority.NORMAL, "category": "tool"},
    # Pose consolidation: vector for the similarity match against existing
    # variants (the free-text normalizer is gone — poses come from the catalog,
    # plan-pose-katalog.md).
    "pose_embedding":     {"label": "Pose Embedding",            "priority": Priority.LOW,    "category": "embedding"},
    # `world_dev_validate` removed: validator model is now picked
    # dynamically in the World Dev UI right next to the chat model — no
    # separate task entry to maintain in /admin/settings → LLM Routing.

    # Room furnishing ("✨ Furnish", plan-furnish-v2.md): three strict-JSON
    # steps of ONE job (needs → match → placement) on one routing task; the
    # steps stay distinguishable in the LLM log through their call labels.
    # No thinking: the answers must be a bare JSON object.
    "furnish":            {"label": "Furnish (needs · match · placement)", "priority": Priority.NORMAL, "category": "tool"},
    # The fourth step of the same feature, but the only one that answers PROSE:
    # after the furnishing has landed, the room's description is rewritten so it
    # names what really stands there (E8, B14b). Button with a preview — the
    # admin reads the text before anything is stored.
    "room_description_sync": {"label": "Furnish: Sync Room Description", "priority": Priority.NORMAL, "category": "tool"},
    # Which surface a prop may be set down on (floor / wall / ceiling / on
    # another prop) — a one-off classification of the LIBRARY, run from the
    # Props tab, that the furnish solver then reads. Same class of work as the
    # furnish steps above and no thinking, for the same reason.
    "prop_mount_classify": {"label": "Props: Classify Mount",       "priority": Priority.NORMAL, "category": "tool"},

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

    # Replies of temporary NPCs (spec-npc-conversation § 2): the SAME chat
    # prompt as chat_stream, resolved under its own name so a fast model can
    # be routed for background figures. No gate — an addressed NPC answers
    # whatever the conversation mode says. Unrouted it falls back to
    # `chat_stream` (resolve_llm's npc_* rule), i.e. the RP model.
    "npc_talk":           {"label": "NPC conversation reply", "priority": Priority.LOW, "category": "chat"},

    # Director scene (spec-npc-conversation § 4): 2–4 lines for one room in
    # one small JSON call — the cheap alternative to turn-by-turn replies.
    # No `gate` (gate keys are booleans; the sub-task reads
    # npc.conversation_mode itself). Route it at a SMALL model.
    "npc_scene":          {"label": "NPC scene (director)", "priority": Priority.LOW, "category": "helper"},

    # Summaries
    "consolidation":         {"label": "Consolidation (3-Tier)",   "priority": Priority.LOW, "category": "helper"},
    "relationship_summary":  {"label": "Relationship Summary",     "priority": Priority.LOW, "category": "helper", "gate": "relationships.summary_enabled"},

    # Image / Prompt
    "image_prompt":       {"label": "Image Prompt Enhancer",    "priority": Priority.NORMAL, "category": "helper", "gate": "image_generation.enabled"},
    "instagram_caption":  {"label": "Instagram Caption",        "priority": Priority.NORMAL, "category": "image",  "gate": "skills.instagram.enabled"},

    # Vision
    "image_recognition":  {"label": "Vision (analysis · comments · recognition)", "priority": Priority.NORMAL, "category": "image", "gate": "image_generation.enabled"},

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
# STATUS: mixed. The three creative-chat tasks (`chat_stream`,
# `group_chat_stream`, `thought`) carry REASONED values from section A1 of
# plan-llm-routing-review.md — measurement in
# .superpowers/sdd/plan-llm-routing-review/task-A1.1-report.md, decisions in
# task-A1.3-report.md. Every OTHER profile is still the first pass derived from
# category + the A0 inventory (development_instructions/llm-routing-review/
# findings.md); sections A2-A5 replace those with reasoned values.
# `pose_embedding` has NO profile on purpose: it does not run over the chat
# providers but over app/core/embedding.py and the /v1/embeddings endpoint.
#
# A1 result that shapes all three chat profiles: the dominant repetition is a
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
        # intro_memory). hallucination_risk medium, not low: an invented
        # spell_id cannot fire (catalog check :199, confidence < 60
        # discarded), but chat_substitute is unvalidated German prose that
        # REPLACES the player's line and is what the room then reacts to.
        "tools": False, "vision": False, "json": True, "min_context": 2048,
        "model_class": "small", "arch": "any", "hallucination_risk": "medium",
        "creative": False, "language_de": True, "latency_sensitive": True,
    },

    # --- Room furnishing ----------------------------------------------------
    # A3 for the whole job. (1) latency_sensitive stays False: the job is a
    # daemon thread tracked in the TaskQueue, it survives a restart
    # (_resume_phase), it ends in a notification, and the admin UI polls at 3 s
    # while the dialog is open and 15 s while it is CLOSED, precisely so the
    # dialog may be closed while it runs (FurnishDialog.tsx:70-125). After the
    # review the job waits up to 30 min per mesh (E6 moved that wait behind
    # accept), so seconds of LLM latency are not what anyone waits on.
    # (2) hallucination_risk is low wherever the output is checked against a
    # catalog AND against the admin — nothing reaches the room without passing
    # a validator and the review gate (``room_furnish.confirm`` /
    # ``room_furnish.accept``).
    "furnish": {
        # The UNION of the three steps that share this task, because one model
        # has to serve all of them: min_context 8192 is the MATCH step (its
        # prompt carries the whole filtered catalog, one line per prop, and the
        # library only grows); hallucination_risk medium is the NEEDS step (the
        # one output checked against nothing — kind, style and description are
        # free text and become the prop's image prompt and a mesh in the shared
        # library after the confirm gate), while match and placement stay low
        # (an invented ref resolves to nothing, an invented prop or anchor comes
        # back as `unplaced` and feeds a re-plan round); creative True because
        # the needs step INVENTS what a lived-in room holds, even though match
        # and placement only compare and arrange. language_de False: what these
        # steps write ends up in image prompts, and those are English.
        "tools": False, "vision": False, "json": True, "min_context": 8192,
        "model_class": "medium", "arch": "any", "hallucination_risk": "medium",
        "creative": True, "language_de": False, "latency_sensitive": False,
    },
    "room_description_sync": {
        # The one furnish task that answers PROSE, so json False — the room's
        # description in the author's own language (language_de True: the text
        # is written for the user, not for an image backend) and creative True
        # (tone, atmosphere and voice are the point; only the objects are
        # dictated). hallucination_risk medium: the model is handed the
        # inventory and told to name nothing else, but nothing CHECKS the
        # sentences it writes — the admin reads the proposal in the dialog and
        # decides, which is exactly why E8 made this a button with a preview.
        # latency_sensitive True: one call between the button and the textarea
        # the admin is waiting in front of. min_context 4096 with no
        # measurement (n=0): the current description plus one line per prop.
        "tools": False, "vision": False, "json": False, "min_context": 4096,
        "model_class": "medium", "arch": "any", "hallucination_risk": "medium",
        "creative": True, "language_de": True, "latency_sensitive": True,
    },
    "prop_mount_classify": {
        # hallucination_risk low: every answer is matched back against the
        # batch's own refs and against the four known kinds — an invented
        # reference or kind is dropped and the prop stays unclassified, and
        # the admin confirms or corrects each guess in the Props tab
        # (`mount_suggested`). min_context 4096 with no measurement (n=0):
        # one line per prop, up to 40 props per call.
        # latency_sensitive True, unlike the furnish job above: this one runs
        # behind a button the admin is waiting in front of, not inside a job
        # that already waits half an hour on a mesh.
        "tools": False, "vision": False, "json": True, "min_context": 4096,
        "model_class": "medium", "arch": "any", "hallucination_risk": "low",
        "creative": False, "language_de": False, "latency_sensitive": True,
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
    "npc_generate": {
        # A whole character sheet for an automatically spawned NPC: creative
        # prose (name, looks, character, standing task) inside a JSON fence, so
        # json True AND creative True. Chat class like the sheet the manual
        # dialog writes — a thin model produces interchangeable figures.
        # language_de True: the sheet is read by the player and is written in
        # the world's language. hallucination_risk low — there is nothing to
        # get wrong, every field is invented by design and validated on the way
        # in. latency_sensitive False: the spawn runs in the background, nobody
        # is looking at a dialog. min_context 4096: the world briefing plus the
        # spawn's own hints.
        "tools": False, "vision": False, "json": True, "min_context": 4096,
        "model_class": "large", "arch": "any", "hallucination_risk": "low",
        "creative": True, "language_de": True, "latency_sensitive": False,
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
    "npc_talk": {
        # One in-character reply from a background NPC. tools False: in
        # rp_first the tool phase runs on `intent`, and single-mode temporary
        # NPCs are not a supported setup. creative True, language_de True —
        # it speaks the world's language. latency_sensitive True: the reply
        # sits in the respond lane while the player watches the room.
        # min_context like chat_stream: it is the SAME chat prompt (sheet,
        # room perception, memories) — only the model class is smaller.
        "tools": False, "vision": False, "json": False, "min_context": 16384,
        "model_class": "small", "arch": "any", "hallucination_risk": "medium",
        "creative": True, "language_de": True, "latency_sensitive": True,
    },
    "npc_scene": {
        # A few sheets and six lines in, a small JSON object out. Every name
        # the model returns is matched against the participant list and every
        # pose against the catalog, so hallucination_risk is low.
        "tools": False, "vision": False, "json": True, "min_context": 4096,
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