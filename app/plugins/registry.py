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
    # Tool metadata flags (F7) — stamped onto the instance by the loader:
    singleton: bool = False           # only the last call per stream sticks
    suppress_in_person: bool = False  # hidden while partners share a room
    cascade_brake: bool = False       # reply_only_to gate for messaging cascades
    search_intent: bool = False       # search-forcing hint targets this tool
    # Declarative intents (F6): [INTENT: <type>] markers this verb executes
    # (handle_intent on the class) + params carrying comparable content.
    intents: List[str] = field(default_factory=list)
    intent_payload_keys: List[str] = field(default_factory=list)
    user_notification: bool = False   # result becomes a user notification
    remote_comm: bool = False         # verb reaches characters not present
    progress_type: str = ""           # count-based intent/assignment progress type


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
class BodySlotSpec:
    """A body slot declared by a species package (plan-body-slots.md).

    The core executes these declarations generically: visibility comes from
    ``equipped_pieces`` vs ``covered_by``; prompt fragments carry ``{attr}``
    placeholders resolved from the character's stored slot values. ``always``
    renders unconditionally, ``covered`` only while covered, ``exposed`` only
    while uncovered — covered/always flow into the general person description
    (decision F1), exposed is the explicit variant.
    """
    id: str
    package_id: str
    covered_by: List[str] = field(default_factory=list)   # clothing slots that cover it
    applies_to: Dict[str, List[str]] = field(default_factory=dict)  # profile field -> allowed values
    attributes: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    prompt: Dict[str, str] = field(default_factory=dict)  # always | covered | exposed


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
    # Species content (plan-body-slots.md): scoped by `apply_to` (template
    # selector, same semantics as fragment apply_to; fallback = the package's
    # fragment selectors). A species defines the FULL slot topology:
    # body slots AND the clothing-slot list AND the UI silhouette.
    apply_to: Any = None
    silhouette: Dict[str, Any] = field(default_factory=dict)  # {"asset": relpath, "anchors": {slot: [x,y]}, ...}
    body_slots: List[BodySlotSpec] = field(default_factory=list)
    piece_slots: List[str] = field(default_factory=list)      # clothing-slot topology; empty = core default
    piece_slot_labels: Dict[str, str] = field(default_factory=dict)  # optional UI labels per slot
    # Package dependencies (F9): ids of other packages.
    # requires — must be PRESENT for this package to load at all, and ACTIVE
    #            on a character before this package's skills can be enabled.
    # conflicts — while the other package is active on a character, this
    #             package's skills cannot be enabled (checked both ways).
    requires: List[str] = field(default_factory=list)
    conflicts: List[str] = field(default_factory=list)


_packages: Dict[str, Package] = {}


def clear_registry() -> None:
    _packages.clear()


def register_package(pkg: Package) -> None:
    _packages[pkg.id] = pkg


def unregister_package(package_id: str) -> None:
    _packages.pop(package_id, None)


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


def package_of_skill(skill_id: str) -> Optional[Package]:
    """The package that provides a skill id (None for built-ins)."""
    for p in packages():
        for s in p.skills:
            if s.skill_id == skill_id:
                return p
    return None


def skill_pairs() -> Dict[str, str]:
    """Map primary skill_id -> paired skill_id, declared direction only
    (the declaring verb is the pair's primary; the partner is rendered as
    part of the primary's coupled toggle in the skills UI)."""
    pairs: Dict[str, str] = {}
    for p in packages():
        for s in p.skills:
            if s.pair_with:
                pairs[s.skill_id] = s.pair_with
    return pairs
