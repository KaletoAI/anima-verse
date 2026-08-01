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
    # Pose consolidation (step 5, May 2026, plan-outfit-system-rethink.md §6.3)
    # pose_normalize:  free text "sitzt am Tisch und blaettert" → "sitting at table, reading"
    # pose_embedding:  vector for the similarity match against existing variants
    "pose_normalize":     {"label": "Pose Normalize",            "priority": Priority.NORMAL, "category": "helper"},
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
    "expression_map":     {"label": "Expression Map",           "priority": Priority.LOW,    "category": "tool",   "gate": "image_generation.enabled"},
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
#   arch              — "dense" | "moe" | "any"; "dense" only where repetition
#                       and self-consistency are the dominating risk.
#   hallucination_risk— "low" | "medium" | "high": the cost of invented facts.
#   creative          — creative prose vs. precision/extraction.
#   language_de       — must write good German prose (user-facing or stored
#                       as German text). English-only output (image prompts,
#                       canonical poses) is False.
#   latency_sensitive — someone is actively waiting (user turn, streaming, the
#                       tool phase of a reply); False = background job.
#
# STATUS: first pass, derived from category + the A0 inventory
# (development_instructions/llm-routing-review/findings.md). Sections A1-A5 of
# plan-llm-routing-review.md replace these with reasoned values.
# `pose_embedding` has NO profile on purpose: it does not run over the chat
# providers but over app/core/embedding.py and the /v1/embeddings endpoint.
TASK_REQUIREMENTS: Dict[str, Dict[str, object]] = {
    # --- Streaming / RP -----------------------------------------------------
    "chat_stream": {
        "tools": True, "vision": False, "json": False, "min_context": 16384,
        "model_class": "large", "arch": "dense", "hallucination_risk": "high",
        "creative": True, "language_de": True, "latency_sensitive": True,
    },
    "story_stream": {
        "tools": False, "vision": False, "json": False, "min_context": 16384,
        "model_class": "large", "arch": "dense", "hallucination_risk": "high",
        "creative": True, "language_de": True, "latency_sensitive": True,
    },
    "group_chat_stream": {
        "tools": True, "vision": False, "json": False, "min_context": 16384,
        "model_class": "large", "arch": "dense", "hallucination_risk": "high",
        "creative": True, "language_de": True, "latency_sensitive": True,
    },
    "storyteller": {
        "tools": True, "vision": False, "json": False, "min_context": 16384,
        "model_class": "large", "arch": "dense", "hallucination_risk": "high",
        "creative": True, "language_de": True, "latency_sensitive": True,
    },

    # --- Tool / decision LLM ------------------------------------------------
    "extraction": {
        "tools": False, "vision": False, "json": True, "min_context": 2048,
        "model_class": "small", "arch": "any", "hallucination_risk": "high",
        "creative": False, "language_de": True, "latency_sensitive": False,
    },
    "extraction_chat_state": {
        "tools": False, "vision": False, "json": True, "min_context": 2048,
        "model_class": "small", "arch": "any", "hallucination_risk": "medium",
        "creative": False, "language_de": False, "latency_sensitive": True,
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
    "send_message": {
        "tools": False, "vision": False, "json": False, "min_context": 16384,
        "model_class": "large", "arch": "dense", "hallucination_risk": "high",
        "creative": True, "language_de": True, "latency_sensitive": False,
    },
    "talk_to": {
        "tools": False, "vision": False, "json": False, "min_context": 16384,
        "model_class": "large", "arch": "dense", "hallucination_risk": "high",
        "creative": True, "language_de": True, "latency_sensitive": False,
    },
    "thought": {
        "tools": True, "vision": False, "json": False, "min_context": 8192,
        "model_class": "large", "arch": "dense", "hallucination_risk": "high",
        "creative": True, "language_de": True, "latency_sensitive": False,
    },
    "intent": {
        "tools": True, "vision": False, "json": False, "min_context": 8192,
        "model_class": "medium", "arch": "any", "hallucination_risk": "high",
        "creative": False, "language_de": False, "latency_sensitive": True,
    },
    "spell_detect": {
        "tools": False, "vision": False, "json": True, "min_context": 2048,
        "model_class": "small", "arch": "any", "hallucination_risk": "medium",
        "creative": False, "language_de": True, "latency_sensitive": True,
    },
    "pose_normalize": {
        "tools": False, "vision": False, "json": False, "min_context": 4096,
        "model_class": "small", "arch": "any", "hallucination_risk": "low",
        "creative": False, "language_de": False, "latency_sensitive": False,
    },

    # --- Room furnishing ----------------------------------------------------
    "furnish_select": {
        "tools": False, "vision": False, "json": True, "min_context": 4096,
        "model_class": "medium", "arch": "any", "hallucination_risk": "high",
        "creative": False, "language_de": False, "latency_sensitive": False,
    },
    "furnish_new": {
        "tools": False, "vision": False, "json": True, "min_context": 4096,
        "model_class": "medium", "arch": "any", "hallucination_risk": "medium",
        "creative": True, "language_de": False, "latency_sensitive": False,
    },
    "furnish_place": {
        "tools": False, "vision": False, "json": True, "min_context": 2048,
        "model_class": "medium", "arch": "any", "hallucination_risk": "medium",
        "creative": False, "language_de": False, "latency_sensitive": False,
    },

    # --- Summaries ----------------------------------------------------------
    "consolidation": {
        "tools": False, "vision": False, "json": False, "min_context": 2048,
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
    "expression_map": {
        "tools": False, "vision": False, "json": True, "min_context": 2048,
        "model_class": "small", "arch": "any", "hallucination_risk": "low",
        "creative": False, "language_de": False, "latency_sensitive": False,
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