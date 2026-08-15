"""Boot migration: rewrite legacy ``workflow:<glob>`` render-target specs.

Why this exists
---------------
A render target is a BACKEND GLOB since ComfyUI was removed ("Flux2*", or an
exact backend name); ``backend:<glob>`` survives as a tolerated legacy prefix.
The third form, ``workflow:<glob>``, is dead: ``BackendPool.resolve_spec``
(app/imagegen/selection.py) resolves it to ``None``, so every caller silently
dropped into its own auto-selection — the configured backend was ignored
without anyone noticing. Values in that shape are still stored in worlds that
lived through the ComfyUI era.

This module owns the DB side of the cleanup: the per-character render
override. The CONFIG side runs in the config load path
(``config._rewrite_legacy_workflow_specs``), right next to the dead-field
strip — one mechanism per storage kind, no second migration framework.

Note the distinction the finding rests on: the FIELD NAME ``workflow`` is
alive and stays (it holds a backend glob — see app/core/expression_regen.py).
Only a ``workflow:`` PREFIX inside the VALUE is legacy.

Idempotent, world_kv-marked, never guesses: ``workflow:Flux`` becomes
``Flux``, a bare ``workflow:`` becomes the empty value (= auto-selection).
"""
from typing import Dict

from app.core.log import get_logger

logger = get_logger("workflow_spec_migration")

_GUARD_KEY = "migrated_legacy_workflow_specs"

LEGACY_PREFIX = "workflow:"

# Character-profile render overrides: (holder block, field). ``outfit_imagegen``
# is written by the character editor (character_ops.apply_outfit_imagegen) and
# read for outfit renders and expression regens.
PROFILE_SPEC_FIELDS = (("outfit_imagegen", "workflow"),)


def strip_legacy_workflow_prefix(value: str) -> str:
    """Rewrite one stored spec to its canonical form.

    ``"workflow:Flux"`` -> ``"Flux"``, ``"workflow:"`` -> ``""``; anything
    else (a bare glob, a ``backend:`` spec, an empty value, a non-string) is
    returned unchanged. Pure — no config, no DB, no imports of its own.
    """
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped.lower().startswith(LEGACY_PREFIX):
        return value
    return stripped[len(LEGACY_PREFIX):].strip()


def migrate_legacy_workflow_specs_once() -> Dict[str, int]:
    """Rewrite the legacy specs stored on character profiles, once per world."""
    result = {"characters": 0, "fields": 0}
    try:
        from app.models.world import get_world_setting, set_world_setting
        from app.models.character import (list_available_characters,
                                          get_character_profile,
                                          save_character_profile)
        if get_world_setting(_GUARD_KEY):
            return result
        for name in list_available_characters():
            profile = get_character_profile(name) or {}
            touched = False
            for holder, field in PROFILE_SPEC_FIELDS:
                block = profile.get(holder)
                if not isinstance(block, dict):
                    continue
                old = block.get(field)
                new = strip_legacy_workflow_prefix(old)
                if new == old:
                    continue
                block[field] = new
                touched = True
                result["fields"] += 1
                logger.info("Legacy render spec rewritten: %s.%s.%s %r -> %r",
                            name, holder, field, old, new)
            if touched:
                save_character_profile(name, profile)
                result["characters"] += 1
        set_world_setting(_GUARD_KEY, "1")
    except Exception as e:
        logger.warning("Legacy workflow-spec migration failed: %s", e)
    return result
