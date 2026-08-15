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

This module owns the per-character side of the cleanup: the render override on
the profile (world.db) AND the file-backed skill configs
(``characters/<name>/skills/<skill>.json``, field ``imagegen_workflow``). The
CONFIG side runs in the config load path
(``config._rewrite_legacy_workflow_specs``), right next to the dead-field
strip — one mechanism per storage kind, no second migration framework.

Note the distinction the finding rests on: the FIELD NAME ``workflow`` is
alive and stays (it holds a backend glob — see app/core/expression_regen.py).
Only a ``workflow:`` PREFIX inside the VALUE is legacy.

Idempotent, world_kv-marked, never guesses: ``workflow:Flux`` becomes
``Flux``, a bare ``workflow:`` becomes the empty value (= auto-selection).
"""
import json
from typing import Dict

from app.core.log import get_logger

logger = get_logger("workflow_spec_migration")

# v2 because the scope grew after v1 could already have run: v1 swept the
# profiles only, the skill-config files came with the review. A world that
# booted on v1 must not skip the new half, and a fresh guard key is the
# cheapest way to say that (one world_kv row; re-running the profile sweep is
# a no-op by construction).
_GUARD_KEY = "migrated_legacy_workflow_specs_v2"

LEGACY_PREFIX = "workflow:"

# Character-profile render overrides: (holder block, field). ``outfit_imagegen``
# is written by the character editor (character_ops.apply_outfit_imagegen) and
# read for outfit renders and expression regens.
PROFILE_SPEC_FIELDS = (("outfit_imagegen", "workflow"),)

# Per-character skill configs live as FILES (characters/<name>/skills/*.json),
# not in world.db. Every skill that renders images carries the render target
# under the same key, so the sweep goes by FIELD NAME across all skill files
# instead of naming a skill (the core never names one).
SKILL_SPEC_FIELD = "imagegen_workflow"


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


def rewrite_skill_config_file(path) -> bool:
    """Rewrite ``imagegen_workflow`` in ONE skill config file.

    Returns True when the file was changed. A file without the field, with an
    already-canonical value, or one that cannot be read as JSON text is left
    alone — a single broken file must never abort the sweep around it (that
    would leave the guard unset and repeat silently on every boot). ``OSError``
    covers unreadable files, ``ValueError`` covers both ``JSONDecodeError`` and
    the ``UnicodeDecodeError`` of a binary file.
    """
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        logger.debug("Skipping unreadable skill config %s: %s", path, e)
        return False
    if not isinstance(cfg, dict) or SKILL_SPEC_FIELD not in cfg:
        return False
    old = cfg.get(SKILL_SPEC_FIELD)
    new = strip_legacy_workflow_prefix(old)
    if new == old:
        return False
    cfg[SKILL_SPEC_FIELD] = new
    try:
        path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    except OSError as e:
        logger.warning("Failed to rewrite %s: %s", path, e)
        return False
    logger.info("Legacy render spec rewritten: %s/%s.%s %r -> %r",
                path.parent.parent.name, path.name, SKILL_SPEC_FIELD, old, new)
    return True


def rewrite_skill_configs_of_character(char_dir) -> int:
    """Rewrite the skill configs of ONE character directory.

    Used by the boot sweep and by the character import — an old export ZIP
    carries its skills/*.json verbatim and would smuggle legacy specs back into
    the world long after the migration ran.
    """
    skills_dir = char_dir / "skills"
    if not skills_dir.is_dir():
        return 0
    return sum(1 for p in sorted(skills_dir.glob("*.json"))
               if rewrite_skill_config_file(p))


def rewrite_skill_config_files() -> int:
    """Rewrite ``imagegen_workflow`` in every per-character skill config file.

    Walks ``characters/*/skills/*.json`` of the current world and returns the
    number of files changed. Reads the characters root through
    ``get_user_characters_dir()``, which materializes ``characters/`` for a
    brand-new world — the one directory the world gets anyway; no character or
    skills directory is ever created here.
    """
    from app.models.character import get_user_characters_dir
    root = get_user_characters_dir()
    if not root.is_dir():
        return 0
    return sum(rewrite_skill_configs_of_character(d)
               for d in sorted(root.iterdir()) if d.is_dir())


def migrate_legacy_workflow_specs_once() -> Dict[str, int]:
    """Rewrite the legacy specs of every character, once per world.

    Two storage kinds, one guard: the render override on the profile (DB) and
    the ``imagegen_workflow`` of the skill config files.
    """
    result = {"characters": 0, "fields": 0, "skill_files": 0}
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
        result["skill_files"] = rewrite_skill_config_files()
        set_world_setting(_GUARD_KEY, "1")
    except Exception as e:
        logger.warning("Legacy workflow-spec migration failed: %s", e)
    return result
