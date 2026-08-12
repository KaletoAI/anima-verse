#!/usr/bin/env python3
"""Check the `requirements` profile of the LLM task catalog (A0.2).

Usage:
    ./.venv/bin/python scripts/test_task_requirements.py

Runs standalone: no server, no world DB, no network. It only imports
`app.core.llm_tasks` and validates the profile table against rules derived by
hand from `development_instructions/plan-llm-routing-review.md` (section A0.2)
and the A0 inventory in
`development_instructions/llm-routing-review/findings.md`.

What is checked (all expectations are written out here, nothing is snapshotted
from the current values):

  1. Every task in TASK_TYPES except the `embedding` category carries a
     `requirements` dict.
  2. `pose_embedding` (category `embedding`) carries NO profile — it bypasses
     the chat providers via app/core/embedding.py.
  3. Each profile has EXACTLY the ten documented keys — no more, no less.
  4. Every value has the documented type / enum value:
       tools, vision, json, creative, language_de, latency_sensitive -> bool
       min_context  -> int on the ladder 2048/4096/8192/16384/32768/65536
       model_class  -> small | medium | large
       arch         -> dense | moe | any
       hallucination_risk -> low | medium | high
  5. category "chat"  => creative is True (the catalog says this is prose work).
  6. category "image" => vision is True (image input is what the category means).
  7. REQUIREMENT_LABELS covers exactly the ten keys, MODEL_CLASS_LABELS exactly
     the three model classes — the admin UI renders generically from both, so a
     missing entry would render a blank row.
  8. The three task ids that were removed on purpose (see REMOVED_TASKS) stay
     out of the catalog. They were never resolved through resolve_llm, so an
     assignment in the admin UI had no effect at all.
  9. Every task named in llm_task_state.PRESETS exists in the catalog. The
     presets are shown to the user as "disable this group"; a name that is not
     a task claims to switch off something that does not exist
     (set_runtime_disabled silently drops it).

NOT checked here on purpose: a TASK_REQUIREMENTS entry without a TASK_TYPES
counterpart. The attach loop at the bottom of app/core/llm_tasks.py already
raises KeyError on import for that case, so the module cannot even load — a
second check in this script could never fire.

Exit code 0 = all good (prints a summary), non-zero = at least one violation
(one concrete line per violation on stderr).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.llm_tasks import (  # noqa: E402
    TASK_TYPES,
    TASK_REQUIREMENTS,
    REQUIREMENT_LABELS,
    MODEL_CLASS_LABELS,
)
from app.core.llm_task_state import PRESETS  # noqa: E402

# --- expectations, derived by hand from the plan -----------------------------

BOOL_KEYS = (
    "tools",
    "vision",
    "json",
    "creative",
    "language_de",
    "latency_sensitive",
)

ENUM_KEYS = {
    "model_class": ("small", "medium", "large"),
    "arch": ("dense", "moe", "any"),
    "hallucination_risk": ("low", "medium", "high"),
}

# The ten keys of the profile, exactly as specified.
EXPECTED_KEYS = frozenset(BOOL_KEYS) | frozenset(ENUM_KEYS) | {"min_context"}

# min_context ladder from the plan: the P90 input is rounded UP to one of these.
CONTEXT_LADDER = (2048, 4096, 8192, 16384, 32768, 65536)

# The one category that routes outside the chat providers and therefore gets no
# profile at all.
NO_PROFILE_CATEGORY = "embedding"

# Category implications the plan states explicitly.
CATEGORY_IMPLIES_TRUE = {
    "chat": "creative",
    "image": "vision",
}

# Task ids that were deliberately dropped from the catalog (findings.md [D1],
# [D3], [D5]). A catalog entry is a promise that the admin-UI assignment for it
# reaches a real LLM call; for these three there was no such call, so the entry
# only faked control. The reason is spelled out per id because the names still
# exist elsewhere in the code and invite a well-meaning re-add.
REMOVED_TASKS = {
    "social_reaction":
        "no call site ever passes it to resolve_llm — the real social-reaction "
        "path (plugins/instagram/social_reactions.py) uses 'image_recognition' "
        "for the image description and then a plain 'thought' turn. The "
        "social_reactions.enabled gate stays; only the routing entry is gone",
    "thought_greeting":
        "no caller passes llm_task='thought_greeting'; run_thought_turn is only "
        "ever called with its default 'thought'",
    "memory_consolidation":
        "not an LLM task at all but a BackgroundQueue task_type "
        "(app/core/memory_service.py). Its handler calls _llm_summarize, which "
        "routes on 'consolidation'. The queue task keeps the name — do not "
        "confuse the two",
}


def main() -> int:
    errors = []

    if len(EXPECTED_KEYS) != 10:
        errors.append(
            "check itself is broken: EXPECTED_KEYS has %d entries, expected 10"
            % len(EXPECTED_KEYS))

    profiled = 0
    for task_id, entry in TASK_TYPES.items():
        category = str(entry.get("category", ""))
        profile = entry.get("requirements")

        if category == NO_PROFILE_CATEGORY:
            if profile is not None:
                errors.append(
                    "%s: category '%s' must NOT carry a requirements profile "
                    "(it bypasses the chat providers), but one is set"
                    % (task_id, category))
            if task_id in TASK_REQUIREMENTS:
                errors.append(
                    "%s: must not appear in TASK_REQUIREMENTS (category '%s')"
                    % (task_id, category))
            continue

        if profile is None:
            errors.append("%s: no requirements profile (category '%s')"
                          % (task_id, category))
            continue
        if not isinstance(profile, dict):
            errors.append("%s: requirements must be a dict, got %s"
                          % (task_id, type(profile).__name__))
            continue

        profiled += 1

        keys = frozenset(profile)
        for missing in sorted(EXPECTED_KEYS - keys):
            errors.append("%s: requirements is missing the key '%s'"
                          % (task_id, missing))
        for extra in sorted(keys - EXPECTED_KEYS):
            errors.append("%s: requirements has the unknown key '%s'"
                          % (task_id, extra))

        for key in BOOL_KEYS:
            if key in profile and not isinstance(profile[key], bool):
                errors.append("%s: requirements['%s'] must be bool, got %r"
                              % (task_id, key, profile[key]))

        for key, allowed in ENUM_KEYS.items():
            if key in profile and profile[key] not in allowed:
                errors.append("%s: requirements['%s'] = %r is not one of %s"
                              % (task_id, key, profile[key], list(allowed)))

        ctx = profile.get("min_context")
        if "min_context" in profile:
            if not isinstance(ctx, int) or isinstance(ctx, bool):
                errors.append("%s: requirements['min_context'] must be int, "
                              "got %r" % (task_id, ctx))
            elif ctx not in CONTEXT_LADDER:
                errors.append("%s: requirements['min_context'] = %r is not a "
                              "step of the ladder %s"
                              % (task_id, ctx, list(CONTEXT_LADDER)))

        implied = CATEGORY_IMPLIES_TRUE.get(category)
        if implied and profile.get(implied) is not True:
            errors.append("%s: category '%s' requires requirements['%s'] to be "
                          "True, got %r"
                          % (task_id, category, implied, profile.get(implied)))

    # Label tables the admin UI renders from.
    label_keys = frozenset(REQUIREMENT_LABELS)
    for missing in sorted(EXPECTED_KEYS - label_keys):
        errors.append("REQUIREMENT_LABELS is missing the key '%s'" % missing)
    for extra in sorted(label_keys - EXPECTED_KEYS):
        errors.append("REQUIREMENT_LABELS has the unknown key '%s'" % extra)

    class_keys = frozenset(MODEL_CLASS_LABELS)
    expected_classes = frozenset(ENUM_KEYS["model_class"])
    for missing in sorted(expected_classes - class_keys):
        errors.append("MODEL_CLASS_LABELS is missing the class '%s'" % missing)
    for extra in sorted(class_keys - expected_classes):
        errors.append("MODEL_CLASS_LABELS has the unknown class '%s'" % extra)

    # Tasks that must stay out of the catalog.
    for task_id, reason in REMOVED_TASKS.items():
        if task_id in TASK_TYPES:
            errors.append(
                "'%s' is back in TASK_TYPES — it must stay out: %s. A routing "
                "entry the router never resolves offers the user a setting "
                "that does nothing." % (task_id, reason))
        if task_id in TASK_REQUIREMENTS:
            errors.append(
                "'%s' is back in TASK_REQUIREMENTS — it must stay out: %s"
                % (task_id, reason))

    # Preset groups may only name tasks that exist.
    for preset, tasks in PRESETS.items():
        for task_id in tasks:
            if task_id not in TASK_TYPES:
                errors.append(
                    "PRESETS['%s'] names '%s', which is not in the catalog. The "
                    "preset promises to disable it, but set_runtime_disabled "
                    "drops unknown ids silently — so nothing happens."
                    % (preset, task_id))

    if errors:
        for line in errors:
            print("FAIL  %s" % line, file=sys.stderr)
        print("\n%d violation(s) in %d task(s)." % (len(errors), len(TASK_TYPES)),
              file=sys.stderr)
        return 1

    no_profile = [t for t, e in TASK_TYPES.items()
                  if str(e.get("category", "")) == NO_PROFILE_CATEGORY]
    chat_tasks = [t for t, e in TASK_TYPES.items()
                  if str(e.get("category", "")) == "chat"]
    image_tasks = [t for t, e in TASK_TYPES.items()
                   if str(e.get("category", "")) == "image"]

    print("OK  task requirements")
    print("    %d tasks in the catalog, %d with a complete 10-key profile"
          % (len(TASK_TYPES), profiled))
    print("    %d without a profile by design: %s"
          % (len(no_profile), ", ".join(no_profile) or "-"))
    print("    %d id(s) kept out of the catalog: %s"
          % (len(REMOVED_TASKS), ", ".join(sorted(REMOVED_TASKS))))
    print("    %d preset(s) checked against the catalog: %s"
          % (len(PRESETS),
             ", ".join("%s:%d" % (p, len(t)) for p, t in sorted(PRESETS.items()))))
    print("    chat tasks with creative=True:  %d (%s)"
          % (len(chat_tasks), ", ".join(sorted(chat_tasks))))
    print("    image tasks with vision=True:   %d (%s)"
          % (len(image_tasks), ", ".join(sorted(image_tasks))))
    print("    min_context distribution: %s"
          % ", ".join("%d:%d" % (step,
                                 sum(1 for p in TASK_REQUIREMENTS.values()
                                     if p.get("min_context") == step))
                      for step in CONTEXT_LADDER
                      if any(p.get("min_context") == step
                             for p in TASK_REQUIREMENTS.values())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
