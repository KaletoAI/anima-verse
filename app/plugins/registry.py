"""Package registry — aggregated contributions of skill packages.

A skill package (a folder under ``plugins/`` with a ``plugin.yaml``) may
contribute more than skill classes. The registry holds the parsed
manifests and exposes aggregated views for the core mechanisms that
consume them:

- LLM template dirs      -> app/core/prompt_templates.py (search path)
- character fragments    -> app/models/character_template.py (merge)
- config subsections     -> app/core/config_schema.py (admin settings)
- state-flag specs       -> app/core/flag_lifecycle.py (lifecycle executor)
- default-enabled skills -> app/core/character_ops.py (new characters)
- skill pairs            -> character skills UI (paired verb toggles)

Rule R1 (plan-skill-plugin-architecture.md): core code never references a
concrete skill by name — everything the core knows about skills comes from
these declarations at runtime. The registry itself is pure data; the
wiring (template search paths, cache invalidation) is done by the loader.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.log import get_logger

logger = get_logger("plugin_registry")


@dataclass
class SkillEntry:
    """One verb (tool) provided by a package."""
    skill_id: str
    module: str = "skill.py"
    class_name: str = ""          # empty = first PluginSkill subclass in module
    params: Dict[str, Any] = field(default_factory=dict)  # constructor kwargs
    always_load: bool = False     # load always, activation per character
    pair_with: str = ""           # UI hint: render as one paired toggle
    default_enabled: bool = False  # enabled by default for new characters


@dataclass
class FlagSpec:
    """Declared lifecycle of a state flag owned by a package.

    The core flag-lifecycle executor renders ``prompt_when_set`` into the
    character's situation context while the flag is set, and auto-clears
    the flag by invoking the ``cleared_by`` verb — so decay runs exactly
    the same side effects as an LLM tool call.
    """
    flag: str                     # key in get_state_flags()
    package_id: str
    cleared_by: str = ""          # skill_id of the clearing verb
    prompt_when_set: str = ""     # situation line; {name}/{clear_tool} placeholders
    ttl_minutes: int = 0          # 0 = no time decay
    reset_on_location_change: bool = False


@dataclass
class Package:
    id: str
    dir: Path
    manifest: Dict[str, Any]
    skills: List[SkillEntry] = field(default_factory=list)
    llm_template_dir: Optional[Path] = None
    character_fragments: List[Dict[str, Any]] = field(default_factory=list)
    config_subsections: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    flags: List[FlagSpec] = field(default_factory=list)


_packages: Dict[str, Package] = {}


def clear_registry() -> None:
    _packages.clear()


def register_package(pkg: Package) -> None:
    _packages[pkg.id] = pkg


def get_package(package_id: str) -> Optional[Package]:
    return _packages.get(package_id)


def packages() -> List[Package]:
    return [_packages[k] for k in sorted(_packages)]


def llm_template_dirs() -> List[Path]:
    return [p.llm_template_dir for p in packages() if p.llm_template_dir]


def character_fragments() -> List[Dict[str, Any]]:
    frags: List[Dict[str, Any]] = []
    for p in packages():
        frags.extend(p.character_fragments)
    return frags


def config_subsections() -> Dict[str, Dict[str, Any]]:
    subs: Dict[str, Dict[str, Any]] = {}
    for p in packages():
        subs.update(p.config_subsections)
    return subs


def flag_specs() -> List[FlagSpec]:
    specs: List[FlagSpec] = []
    for p in packages():
        specs.extend(p.flags)
    return specs


def default_enabled_skill_ids() -> List[str]:
    ids: List[str] = []
    for p in packages():
        for s in p.skills:
            if s.default_enabled:
                ids.append(s.skill_id)
    return ids


def skill_pairs() -> Dict[str, str]:
    """Map skill_id -> paired skill_id (both directions)."""
    pairs: Dict[str, str] = {}
    for p in packages():
        for s in p.skills:
            if s.pair_with:
                pairs[s.skill_id] = s.pair_with
                pairs.setdefault(s.pair_with, s.skill_id)
    return pairs
