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
    default_enabled: bool = False  # enabled by default for new characters
    # Tool metadata flags (F7) — stamped onto the instance by the loader:
    singleton: bool = False           # only the last call per stream sticks
    suppress_in_person: bool = False  # hidden while partners share a room
    cascade_brake: bool = False       # reply_only_to gate for messaging cascades
    search_intent: bool = False       # search-forcing hint targets this tool
    delivers_speech: bool = False     # verb delivers spoken dialogue (B-lite net)
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
    distracting: bool = False     # a set flag occupies the character's attention


@dataclass
class RigSpec:
    """Validated declaration; operation parameters remain opaque in P0."""
    id: str
    op: str
    chains: List[List[Dict[str, str]]]
    params: Dict[str, Any] = field(default_factory=dict)
    applies_to: Dict[str, List[Any]] = field(default_factory=dict)
    depends_on: str | None = None
    external_parents: List[str] = field(default_factory=list)
    length: float = 1.0
    girth: float = 1.0
    scale_axis: str = "centroid"
    freq_hz: float = 2.2
    zeta: float = 0.15
    gravity: float = 0.35
    spill: float = 0.0
    flatten: float = 0.0
    stretch: float = 0.0
    spread: float = 0.5
    flatten_floor: float | None = None
    translate: float = 0.0
    sag_max_deg: float = 25.0    # For chains, bounds the whole chain static droop.
    spill_max_deg: float = 25.0
    head_sag: float = 1.0
    attribute_profiles: Dict[str, Dict[str, Dict[str, float]]] = field(default_factory=dict)
    axis_gain: List[float] = field(default_factory=lambda: [1.0, 1.0, 1.0])
    gain: float = 1.0
    max_deg: float = 25.0
    squash: List[float] = field(default_factory=lambda: [0.6, 1.4])
    rest_max_deg: float = 90.0
    straighten_deg: float = 0.0
    freetext_clothing_gain: float = 1.0
    templates: Any = None
    controls: Optional[List[str]] = None

    @classmethod
    def parse(cls, raw, attributes=None):
        """Reject malformed chains, conditions and non-finite physics values."""
        import math
        from app.core.rig_contract import BASE_JOINT_KEYS, norm_bone_name
        if not isinstance(raw, dict):
            raise ValueError("rig must be a mapping")
        for key in ("id", "op"):
            if not isinstance(raw.get(key), str) or not raw[key].strip():
                raise ValueError(f"rig.{key} must be a non-empty string")
        params = raw.get("params", {})
        if not isinstance(params, dict):
            raise ValueError("rig.params must be a mapping")
        conditions = raw.get("applies_to", {})
        if not isinstance(conditions, dict) or any(
                not isinstance(k, str) or not k or not isinstance(v, list) or not v
                or any(not isinstance(x, (str, int, float, bool, type(None))) for x in v)
                for k, v in conditions.items()):
            raise ValueError("rig.applies_to must map fields to non-empty scalar lists")
        if "apply_to" in raw:
            raise ValueError("use rig.templates for template selection and rig.applies_to for conditions")
        templates = raw.get("templates")
        if "templates" in raw and not (
                templates == "*"
                or (isinstance(templates, list) and templates
                    and all(isinstance(v, str) and v.strip() for v in templates))
                or (isinstance(templates, dict) and set(templates) == {"feature"}
                    and isinstance(templates["feature"], str) and templates["feature"].strip())):
            raise ValueError("rig.templates requires template names, * or a feature selector")
        chains = raw.get("chains")
        if not isinstance(chains, list) or not chains:
            raise ValueError("rig.chains must be a non-empty list")
        seen = set()
        result = []
        for chain in chains:
            if not isinstance(chain, list) or not chain:
                raise ValueError("rig chain must be a non-empty list")
            earlier = set()
            clean = []
            for link in chain:
                if not isinstance(link, dict) or any(
                        not isinstance(link.get(k), str) or not link[k].strip()
                        for k in ("bone", "parent")):
                    raise ValueError("rig link requires bone and parent strings")
                bone, parent = link["bone"].strip(), link["parent"].strip()
                key = norm_bone_name(bone)
                if not key or key in seen or key in BASE_JOINT_KEYS:
                    raise ValueError(f"duplicate or reserved bone: {bone}")
                if norm_bone_name(parent) not in BASE_JOINT_KEYS and parent not in earlier and clean:
                    raise ValueError(f"parent must be a base joint or earlier chain link: {parent}")
                clean.append({"bone": bone, "parent": parent})
                earlier.add(bone)
                seen.add(key)
            result.append(clean)
        spec = cls(raw["id"].strip(), raw["op"].strip(), result,
                   dict(params), dict(conditions))
        spec.external_parents = [chain[0]["parent"] for chain in result
                                 if norm_bone_name(chain[0]["parent"]) not in BASE_JOINT_KEYS]
        from app.core.extension_rig import MOTION_FIELDS
        controls = raw.get("controls")
        if controls is not None and (
                not isinstance(controls, list) or not controls
                or any(not isinstance(name, str) or name not in (*MOTION_FIELDS, "bounce", "weight") for name in controls)
                or len(set(controls)) != len(controls)):
            raise ValueError("rig.controls requires unique known control names")
        spec.controls = list(controls) if controls is not None else None
        spec.templates = templates
        axis = raw.get("scale_axis", spec.scale_axis)
        if axis not in ("centroid", "bone"):
            raise ValueError("rig.scale_axis must be centroid or bone")
        spec.scale_axis = axis
        bounds = {"length": (.5, 3), "girth": (.5, 2), "freq_hz": (0, None), "zeta": (0, None),
                  "gravity": (0, None), "head_sag": (0, 1), "spill": (0, 1), "translate": (0, 1), "flatten": (0, 1), "stretch": (0, 1), "spread": (0, 1), "gain": (0, 1),
                  "max_deg": (0, 180), "rest_max_deg": (0, 180),
                  "straighten_deg": (0, 180), "freetext_clothing_gain": (0, 1)}
        for key, (lo, hi) in bounds.items():
            value = raw.get(key, getattr(spec, key))
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"rig.{key} must be numeric")
            if not math.isfinite(value) or value < lo or (hi is not None and value > hi) or (key == "freq_hz" and value == 0):
                raise ValueError(f"rig.{key} outside allowed range")
            setattr(spec, key, float(value))
        sag = raw.get("sag_max_deg", spec.max_deg)
        if isinstance(sag, bool) or not isinstance(sag, (int, float)) or not math.isfinite(sag) or not 0 <= sag <= 180:
            raise ValueError("rig.sag_max_deg outside allowed range")
        spec.sag_max_deg = float(sag)
        spill_max = raw.get("spill_max_deg", spec.sag_max_deg)
        if isinstance(spill_max, bool) or not isinstance(spill_max, (int, float)) or not math.isfinite(spill_max) or not 0 <= spill_max <= 180:
            raise ValueError("rig.spill_max_deg outside allowed range")
        spec.spill_max_deg = float(spill_max)
        profiles = raw.get("attribute_profiles", {})
        fields = {"freq_hz", "zeta", "gravity", "gain", "max_deg", "sag_max_deg", "spill_max_deg", "head_sag", "flatten", "stretch", "spread", "flatten_floor", "spill", "translate"}
        if not isinstance(profiles, dict):
            raise ValueError("rig.attribute_profiles must be a mapping")
        for key, choices in profiles.items():
            if not isinstance(key, str) or not key or (attributes is not None and key not in attributes):
                raise ValueError("attribute profile must name a declared slot attribute")
            if not isinstance(choices, dict):
                raise ValueError("attribute profile values must be a mapping")
            for value, multipliers in choices.items():
                if not isinstance(value, str) or not value or not isinstance(multipliers, dict) or set(multipliers) - fields:
                    raise ValueError("invalid attribute profile multipliers")
                if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0
                       or (f == "freq_hz" and v == 0) for f, v in multipliers.items()):
                    raise ValueError("attribute profile multipliers must be finite and nonnegative")
        spec.attribute_profiles = {key: {value: dict(row) for value, row in choices.items()}
                                   for key, choices in profiles.items()}
        axis_gain = raw.get("axis_gain", spec.axis_gain)
        if not isinstance(axis_gain, list) or len(axis_gain) != 3 or any(
                isinstance(v, bool) or not isinstance(v, (int, float))
                or not math.isfinite(v) or not 0 <= v <= 1 for v in axis_gain):
            raise ValueError("rig.axis_gain requires three finite gains in [0,1]")
        spec.axis_gain = list(axis_gain)
        squash = raw.get("squash", spec.squash)
        if not isinstance(squash, list) or len(squash) != 2 or any(
                isinstance(v, bool) or not isinstance(v, (int, float))
                or not math.isfinite(v) or v <= 0 for v in squash
        ) or not squash[0] <= 1 <= squash[1]:
            raise ValueError("rig.squash requires 0 < min <= 1 <= max")
        spec.squash = list(squash)
        if "flatten_floor" in raw:
            floor = raw["flatten_floor"]
            if isinstance(floor, bool) or not isinstance(floor, (int, float)) or not math.isfinite(floor) or not 0 <= floor <= 1:
                raise ValueError("rig.flatten_floor outside allowed range")
            spec.flatten_floor = float(floor)
        return spec


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
    face: bool = False  # fragment also belongs into face/portrait prompts
    back: bool = False  # Include fragments in rear-view renders.
    rigs: List[RigSpec] = field(default_factory=list)


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
    piece_slot_labels: Dict[str, str] = field(default_factory=dict)
    capability_label: str = ""   # one UI toggle for ALL verbs of the package
    capability_description: str = ""  # human-facing UI text (LLM descriptions address the character)
    being: str = ""               # species prompt noun: person/animal/... (scene composition)  # optional UI labels per slot
    # What an undressed free-text wardrobe says in prompts in place of the
    # core's "no clothes" (scoped by `apply_to` like the other species content).
    undressed_prompt: str = ""
    # Package dependencies (F9): ids of other packages.
    # requires — must be PRESENT for this package to load at all, and ACTIVE
    #            on a character before this package's skills can be enabled.
    # conflicts — while the other package is active on a character, this
    #             package's skills cannot be enabled (checked both ways).
    requires: List[str] = field(default_factory=list)
    conflicts: List[str] = field(default_factory=list)


_packages: Dict[str, Package] = {}

# Bumped on every change of the registry, so a consumer that caches a view
# derived from it (app/core/config_scope.py) knows when to rebuild.
_generation = 0


def generation() -> int:
    """A counter that changes whenever a package is (un)registered."""
    return _generation


def clear_registry() -> None:
    global _generation
    _packages.clear()
    _generation += 1


def register_package(pkg: Package) -> None:
    global _generation
    from app.core.rig_contract import norm_bone_name
    owners = {}
    group_ids = {}
    for candidate in [p for p in packages() if p.id != pkg.id] + [pkg]:
        for slot in candidate.body_slots:
            for rig in slot.rigs:
                if rig.id in group_ids:
                    raise ValueError(f"duplicate rig group {rig.id}: {group_ids[rig.id]} and {candidate.id}")
                group_ids[rig.id] = candidate.id
                for chain in rig.chains:
                    for link in chain:
                        key = norm_bone_name(link["bone"])
                        if key in owners:
                            raise ValueError(f"duplicate extension bone {link['bone']}: packages {owners[key]} and {candidate.id}")
                        owners[key] = candidate.id
    _packages[pkg.id] = pkg
    _generation += 1


def unregister_package(package_id: str) -> None:
    global _generation
    _packages.pop(package_id, None)
    _generation += 1


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


