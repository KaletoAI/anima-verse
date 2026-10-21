"""PluginLoader — discovers and loads skill packages from ``plugins/``.

A skill package is a folder with a ``plugin.yaml`` manifest. Beyond skill
classes a package may contribute templates, admin config schema, character
template fragments and state-flag lifecycle declarations (see
``docs/plugins.md`` and development_instructions/plan-skill-plugin-architecture.md).

Manifest format (package format v1):

    name: training
    version: "1.0.0"
    description: ...
    # Verbs — single form (skill_id/module at top level) or list form:
    skills:
      - skill_id: start_training
        module: skill.py          # default skill.py
        class: TrainingSkill      # default: first PluginSkill subclass
        params: {active: true}    # constructor kwargs (parameterized verbs)
        always_load: true         # load always, activate per character
        default_enabled: false    # enabled for newly created characters
    templates:
      llm: templates/llm          # added to the prompt-template search path
      character:                  # character-template fragments (merged)
        - templates/character/courage.json
    llm_tasks:                    # routable package tasks
      demo_note: {label: Demo note, category: chat, fallback: chat_stream}
    config_schema:                # admin settings subsections under "skills"
      training:
        label: Training
        fields: {...}
    state_flags:                  # lifecycle declarations (flag executor)
      - flag: is_training
        cleared_by: end_training
        prompt_when_set: "..."
        ttl_minutes: 120
        reset_on_location_change: true

Skill name/description resolve from ``<llm templates>/skills/<skill_id>.md``
when present (same format as shared/templates/llm/skills/) — otherwise the
skill class sets them itself.
"""
import copy
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Tuple, Type

import yaml

from app.core.log import get_logger
from app.plugins.context import PluginContext
from app.plugins.base import PluginSkill
from app.plugins import registry
from app.plugins.registry import BodySlotSpec, FlagSpec, Package, SkillEntry

logger = get_logger("plugin_loader")

# Default directory: <project_root>/plugins/
PLUGIN_DIR = Path(__file__).resolve().parent.parent.parent / "plugins"
# Marketplace-installed packages live one level below in a fully gitignored
# dir — repo files and installed content never collide (same policy as
# world-level content packs). Repo packages win on id collision.
INSTALLED_DIR_NAME = "installed"

_discovered = False
# Capture world activation only at runtime discovery, never during the pure
# manifest scan used to bootstrap config scopes. Config saves require restart;
# force skill reload must not apply only part of a pending activation change.
_activation_enabled_ids: Optional[FrozenSet[str]] = None


def _load_yaml(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _import_module(plugin_dir: Path, module_file: str):
    module_path = plugin_dir / module_file
    if not module_path.exists():
        logger.error("Module not found: %s", module_path)
        return None
    module_name = f"plugins.{plugin_dir.name}.{module_path.stem}"
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        logger.error("Cannot create module spec: %s", module_path)
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _import_skill_class(plugin_dir: Path, module_file: str,
                        class_name: str = "") -> Optional[Type[PluginSkill]]:
    """Import a skill class from the package module.

    With ``class_name`` the class is looked up explicitly (required when one
    module hosts several skill classes); otherwise the first PluginSkill
    subclass found in the module is used.
    """
    module = _import_module(plugin_dir, module_file)
    if module is None:
        return None

    if class_name:
        attr = getattr(module, class_name, None)
        if isinstance(attr, type) and issubclass(attr, PluginSkill):
            return attr
        logger.error("Class '%s' not found (or no PluginSkill) in %s/%s",
                     class_name, plugin_dir.name, module_file)
        return None

    for attr_name in dir(module):
        attr = getattr(module, attr_name)
        if (isinstance(attr, type)
                and issubclass(attr, PluginSkill)
                and attr is not PluginSkill):
            return attr

    logger.error("No PluginSkill subclass found in %s", plugin_dir / module_file)
    return None


def _parse_skill_entries(meta: Dict[str, Any]) -> List[SkillEntry]:
    """Normalize single-skill and multi-skill manifests into SkillEntry list."""
    entries: List[SkillEntry] = []
    plugin_always = bool(meta.get("always_load", False))

    def _entry(d: Dict[str, Any]) -> Optional[SkillEntry]:
        sid = (d.get("skill_id") or "").strip()
        if not sid:
            return None
        return SkillEntry(
            skill_id=sid,
            module=d.get("module", "skill.py"),
            class_name=(d.get("class") or "").strip(),
            params=d.get("params") or {},
            always_load=bool(d.get("always_load", plugin_always)),
            default_enabled=bool(d.get("default_enabled", False)),
            singleton=bool(d.get("singleton", False)),
            suppress_in_person=bool(d.get("suppress_in_person", False)),
            cascade_brake=bool(d.get("cascade_brake", False)),
            search_intent=bool(d.get("search_intent", False)),
            delivers_speech=bool(d.get("delivers_speech", False)),
            intents=[str(x).strip() for x in (d.get("intents") or []) if str(x).strip()],
            intent_payload_keys=[str(x).strip() for x in (d.get("intent_payload_keys") or [])
                                 if str(x).strip()],
            user_notification=bool(d.get("user_notification", False)),
            remote_comm=bool(d.get("remote_comm", False)),
            progress_type=str(d.get("progress_type", "") or "").strip(),
        )

    skills_list = meta.get("skills")
    if skills_list and isinstance(skills_list, list):
        for d in skills_list:
            e = _entry(d if isinstance(d, dict) else {})
            if e:
                entries.append(e)
    elif meta.get("skill_id"):
        e = _entry(meta)
        if e:
            entries.append(e)
    return entries


def _parse_package(entry_dir: Path, meta: Dict[str, Any], *,
                   register_tasks: bool = True) -> Optional[Package]:
    """Parse a manifest; inventory callers defer task registration until discovery."""
    pkg = Package(id=entry_dir.name, dir=entry_dir, manifest=meta)
    pkg.capability_label = str(meta.get("capability_label", "") or "").strip()
    pkg.capability_description = str(meta.get("capability_description", "") or "").strip()
    pkg.being = str(meta.get("being", "") or "").strip().lower()
    pkg.undressed_prompt = str(meta.get("undressed_prompt", "") or "").strip()
    pkg.skills = _parse_skill_entries(meta)
    if not meta.get("name"):
        logger.warning("Package %s: name missing in plugin.yaml", entry_dir.name)
        return None

    task_specs = meta.get("llm_tasks") or {}
    if not isinstance(task_specs, dict):
        logger.warning("Package %s: llm_tasks must be a mapping", pkg.id)
        task_specs = {}

    tmpl = meta.get("templates") or {}
    llm_rel = (tmpl.get("llm") or "").strip()
    if llm_rel:
        llm_dir = (entry_dir / llm_rel).resolve()
        if llm_dir.is_dir():
            pkg.llm_template_dir = llm_dir
        else:
            logger.warning("Package %s: templates.llm dir missing: %s",
                           pkg.id, llm_dir)

    for frag_rel in tmpl.get("character") or []:
        frag_path = entry_dir / frag_rel
        try:
            frag = json.loads(frag_path.read_text(encoding="utf-8"))
            frag["_package_id"] = pkg.id
            pkg.character_fragments.append(frag)
        except Exception as e:
            logger.error("Package %s: character fragment %s unreadable: %s",
                         pkg.id, frag_rel, e)

    cfg_schema = meta.get("config_schema") or {}
    if isinstance(cfg_schema, dict):
        pkg.config_subsections = cfg_schema

    pkg.requires = [str(x).strip() for x in (meta.get("requires") or []) if str(x).strip()]
    pkg.conflicts = [str(x).strip() for x in (meta.get("conflicts") or []) if str(x).strip()]

    # Species content (plan-body-slots.md): silhouette, body slots and the
    # clothing-slot topology, scoped by the package-level apply_to selector.
    pkg.apply_to = meta.get("apply_to")
    sil = meta.get("silhouette") or {}
    if isinstance(sil, dict):
        pkg.silhouette = sil
    for bdef in meta.get("body_slots") or []:
        if not isinstance(bdef, dict) or not bdef.get("id"):
            continue
        rigs = []
        if "rig" in bdef:
            logger.error("Package %s slot %s: use rigs list; no rigs loaded", pkg.id, bdef["id"])
        else:
            from app.plugins.registry import RigSpec
            entries = bdef.get("rigs", [])
            if not isinstance(entries, list):
                logger.warning("Package %s slot %s: rig dropped: rigs must be a list", pkg.id, bdef["id"])
                entries = []
            for entry in entries:
                try:
                    rigs.append(RigSpec.parse(entry, attributes=bdef.get("attributes") or {}))
                except (ValueError, TypeError, OverflowError) as exc:
                    logger.warning("Package %s slot %s: rig dropped: %s", pkg.id, bdef["id"], exc)
            rigs = _resolve_rig_dependencies(rigs, pkg.id, bdef["id"])
        for attribute, declaration in (bdef.get("attributes") or {}).items():
            if isinstance(declaration, dict) and "applies_to" in declaration:
                conditions = declaration["applies_to"]
                if not isinstance(conditions, dict) or any(
                        not isinstance(key, str) or not key.strip()
                        or (key.startswith("attributes.") and key[11:] not in (bdef.get("attributes") or {}))
                        or not isinstance(values, list) or not values
                        or any(not isinstance(value, (str, int, float, bool, type(None))) for value in values)
                        for key, values in conditions.items()):
                    logger.error("Package %s slot %s: invalid attribute applies_to: %s", pkg.id, bdef["id"], attribute)
                    return None
        mesh_part = None
        if "mesh_part" in bdef:
            from app.plugins.registry import MeshPartSpec
            try:
                mesh_part = MeshPartSpec.parse(bdef["mesh_part"], bdef.get("attributes") or {}, rigs)
            except (ValueError, TypeError, OverflowError) as exc:
                logger.error("Package %s slot %s: invalid mesh_part: %s", pkg.id, bdef["id"], exc)
                return None
        pkg.body_slots.append(BodySlotSpec(
            id=str(bdef["id"]).strip(),
            package_id=pkg.id,
            covered_by=[str(x).strip() for x in (bdef.get("covered_by") or [])],
            applies_to={str(k): [str(v).strip() for v in vals]
                        for k, vals in (bdef.get("applies_to") or {}).items()
                        if isinstance(vals, list)},
            attributes={str(k): dict(v) for k, v in (bdef.get("attributes") or {}).items()
                        if isinstance(v, dict)},
            prompt={str(k): str(v) for k, v in (bdef.get("prompt") or {}).items()},
            face=bool(bdef.get("face", False)),
            back=bool(bdef.get("back", False)),
            rigs=rigs,
            mesh_part=mesh_part,
        ))
    # piece_slots entries: plain string OR {id, label}
    for pdef in meta.get("piece_slots") or []:
        if isinstance(pdef, dict):
            pid = str(pdef.get("id") or "").strip()
            if not pid:
                continue
            pkg.piece_slots.append(pid)
            if pdef.get("label"):
                pkg.piece_slot_labels[pid] = str(pdef["label"])
        else:
            pid = str(pdef).strip()
            if pid:
                pkg.piece_slots.append(pid)

    for fdef in meta.get("state_flags") or []:
        if not isinstance(fdef, dict) or not fdef.get("flag"):
            continue
        pkg.flags.append(FlagSpec(
            flag=fdef["flag"],
            package_id=pkg.id,
            cleared_by=(fdef.get("cleared_by") or "").strip(),
            prompt_when_set=(fdef.get("prompt_when_set") or "").strip(),
            ttl_minutes=int(fdef.get("ttl_minutes") or 0),
            reset_on_location_change=bool(fdef.get("reset_on_location_change", False)),
            distracting=bool(fdef.get("distracting", False)),
        ))

    # Content-only packages (no verbs) are allowed as long as they contribute
    # SOMETHING (templates, fragments, config, flags, species content).
    # Contributions apply whenever the package is active in this world; the
    # skills.<id>.enabled gate only governs non-always_load verb loading.
    if not pkg.skills and not (pkg.llm_template_dir or pkg.character_fragments
                               or pkg.config_subsections or pkg.flags
                               or pkg.silhouette or pkg.body_slots
                               or pkg.piece_slots or pkg.undressed_prompt
                               or meta.get("on_load") or task_specs):
        logger.warning("Package %s: neither skills nor contributions in plugin.yaml",
                       entry_dir.name)
        return None

    if register_tasks:
        from app.core.llm_tasks import register_plugin_task
        for task_id, task_spec in task_specs.items():
            register_plugin_task(task_id, task_spec, pkg.id)
    return pkg


def _collect_packages(base: Path, *, warn: bool = True,
                      enabled_ids: Optional[FrozenSet[str]] = None) -> List[Package]:
    """Scan ``base`` and ``base/installed`` for eligible manifests — no side effects.

    With ``enabled_ids`` supplied, only those exact directory IDs are eligible,
    including when the set is empty. Filter both roots before parsing,
    dependency pruning and rig conflict resolution; repo packages win over an
    installed one of the same id. Packages whose ``requires`` are not all
    present are dropped repeatedly until dependency chains unwind.
    The default, ``None``, scans all packages for manifest/schema inventory,
    regardless of world activation. Reads files only: no package code is
    imported, no registry is touched. ``warn=False`` silences duplicate
    shadow/inert warnings.
    """
    found: Dict[str, Package] = {}

    def _scan(root: Path, *, installed: bool) -> None:
        if not root.exists():
            if not installed and warn:
                logger.info("Plugin directory not found: %s", root)
            return
        for entry in sorted(root.iterdir()):
            manifest = entry / "plugin.yaml"
            if not entry.is_dir() or not manifest.exists():
                continue
            if enabled_ids is not None and entry.name not in enabled_ids:
                continue
            if installed and entry.name in found:
                if warn:
                    logger.warning(
                        "Installed package '%s' shadows a repo package — skipped",
                        entry.name)
                continue
            try:
                meta = _load_yaml(manifest)
            except Exception as e:
                logger.error("Error reading %s: %s", manifest, e)
                continue
            pkg = _parse_package(entry, meta, register_tasks=False)
            if pkg:
                found[pkg.id] = pkg

    _scan(base, installed=False)
    _scan(base / INSTALLED_DIR_NAME, installed=True)

    # Dependency presence (F9): a package whose `requires` are not all
    # present stays completely inert (no verbs, no contributions).
    while True:
        broken = [p for p in found.values()
                  if any(r not in found for r in p.requires)]
        if not broken:
            break
        for p in broken:
            if warn:
                missing = [r for r in p.requires if r not in found]
                logger.warning("Package '%s' inert — required package(s) missing: %s",
                               p.id, ", ".join(missing))
            found.pop(p.id, None)
    from app.core.rig_contract import norm_bone_name
    # Collect the COMPLETE declaration set before dropping anything: no owner
    # wins by discovery order, including overlapping bone/group conflicts.
    declarations = []
    owners = {}
    for pkg in [found[k] for k in sorted(found)]:
        for slot in pkg.body_slots:
            for rig in slot.rigs:
                index = len(declarations)
                declarations.append((pkg.id, slot, rig))
                keys = [("bone", norm_bone_name(link["bone"]))
                        for chain in rig.chains for link in chain]
                keys.append(("group", rig.id))
                for key in keys:
                    owners.setdefault(key, set()).add(index)
    disabled = set()
    for (kind, key), indices in sorted(owners.items()):
        if len(indices) > 1:
            disabled.update(indices)
            names = [f"{declarations[i][0]}/{declarations[i][1].id}" for i in sorted(indices)]
            logger.error("Conflicting extension %s %s: rigs disabled for ALL owners: %s",
                         kind, key, ", ".join(names))
    for index in disabled:
        _, slot, rig = declarations[index]
        slot.rigs.remove(rig)
    for pkg in found.values():
        for slot in pkg.body_slots:
            slot.rigs = _resolve_rig_dependencies(slot.rigs, pkg.id, slot.id)
    # A part variant is only usable while its owning geometry group survives.
    for pkg in list(found.values()):
        if any(slot.mesh_part and not set(slot.mesh_part.rigs).issubset({rig.id for rig in slot.rigs})
               for slot in pkg.body_slots):
            logger.error("Package %s: mesh_part rig lost during conflict resolution", pkg.id)
            found.pop(pkg.id)
    while True:
        broken = [pkg for pkg in found.values() if any(dep not in found for dep in pkg.requires)]
        if not broken:
            break
        for pkg in broken:
            logger.warning("Package %s inert after mesh_part dependency rejection", pkg.id)
            found.pop(pkg.id)
    return [found[k] for k in sorted(found)]


def is_discovered() -> bool:
    """True once ``discover_packages()`` populated the registry from PLUGIN_DIR."""
    return _discovered


_manifest_schemas: Optional[Dict[str, Dict[str, Any]]] = None


def manifest_config_schemas() -> Dict[str, Dict[str, Any]]:
    """The packages' ``config_schema`` subsections, read from the manifests only.

    For code that needs the skills' settings schema BEFORE discovery has run
    (the config scope split at config load, app/core/config_scope.py).
    Same roots as ``discover_packages`` — repo wins over installed, packages
    with missing ``requires`` contribute nothing — but includes packages not
    enabled in the world so their settings retain scope/default metadata. Side-effect free:
    no package code is imported, no on_load runs, no activation snapshot is
    captured, and the registry stays untouched. The result is cached until
    runtime rediscovery refreshes installed inventory; the caller gets a copy.
    """
    global _manifest_schemas
    if _manifest_schemas is None:
        subs: Dict[str, Dict[str, Any]] = {}
        for pkg in _collect_packages(PLUGIN_DIR, warn=False):
            subs.update(pkg.config_subsections)
        _manifest_schemas = subs
    return copy.deepcopy(_manifest_schemas)


PACKAGE_CATEGORIES = ("skill", "content", "adult")


def package_category(meta: Dict[str, Any]) -> str:
    """The Setup grouping of a manifest: its ``category`` when it names one of
    ``PACKAGE_CATEGORIES``, else "skill" for a package with verbs and
    "content" for one without (species, templates, providers)."""
    declared = str(meta.get("category", "") or "").strip().lower()
    if declared in PACKAGE_CATEGORIES:
        return declared
    return "skill" if _parse_skill_entries(meta) else "content"


def package_inventory(plugin_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Every package folder with a readable manifest, for Game-Admin → Setup →
    Packages — independent of world activation and of missing requirements
    (those are reported, not dropped). Reads manifests only: no package code
    is imported, no registry is touched. Repo wins over installed, as in
    ``discover_packages``; ``loaded`` says whether the package is active in
    this server right now."""
    base = plugin_dir or PLUGIN_DIR
    found: Dict[str, Dict[str, Any]] = {}
    for root, installed in ((base, False), (base / INSTALLED_DIR_NAME, True)):
        if not root.is_dir():
            continue
        for entry in sorted(root.iterdir()):
            manifest = entry / "plugin.yaml"
            if not entry.is_dir() or not manifest.exists() or entry.name in found:
                continue
            try:
                meta = _load_yaml(manifest)
            except Exception as e:
                logger.error("Error reading %s: %s", manifest, e)
                continue
            if not isinstance(meta, dict):
                continue
            found[entry.name] = {
                "id": entry.name,
                "label": str(meta.get("capability_label") or meta.get("name") or entry.name),
                "description": str(meta.get("capability_description")
                                   or meta.get("description") or "").strip(),
                "version": str(meta.get("version", "") or ""),
                "category": package_category(meta),
                "source": ("installed" if installed
                           else "linked" if entry.is_symlink() else "repo"),
                "requires": [str(x).strip() for x in (meta.get("requires") or []) if str(x).strip()],
                "conflicts": [str(x).strip() for x in (meta.get("conflicts") or []) if str(x).strip()],
                "loaded": registry.get_package(entry.name) is not None,
            }
    return [found[k] for k in sorted(found)]


def discover_packages(plugin_dir: Optional[Path] = None,
                      force: bool = False) -> List[Package]:
    """Discover explicitly enabled packages and (re)populate the registry.

    Idempotent: subsequent calls return the registered packages unless
    ``force`` is set (skill reload). Wires cross-module contributions:
    prompt-template search path and template caches. Whole-package activation
    is fixed at the first runtime discovery and changes only after restart.
    """
    global _discovered, _activation_enabled_ids, _manifest_schemas
    if _discovered and not force and plugin_dir is None:
        return registry.packages()

    # Installation/removal changes dormant settings metadata too. Invalidate
    # only on a real rebuild, never on ordinary reads or cached discovery.
    _manifest_schemas = None
    base = plugin_dir or PLUGIN_DIR
    if _activation_enabled_ids is None:
        from app.core import config
        _activation_enabled_ids = frozenset(
            package_id.strip()
            for package_id in (config.get("packages.enabled", "") or "").split(",")
            if package_id.strip()
        )
    from app.core.llm_tasks import _clear_plugin_tasks, register_plugin_task
    _clear_plugin_tasks()
    registry.clear_registry()
    for pkg in _collect_packages(base, enabled_ids=_activation_enabled_ids):
        registry.register_package(pkg)
    for pkg in registry.packages():
        task_specs = pkg.manifest.get("llm_tasks") or {}
        if isinstance(task_specs, dict):
            for task_id, task_spec in task_specs.items():
                register_plugin_task(task_id, task_spec, pkg.id)

    if plugin_dir is None:
        _discovered = True

    # Wire contributions into their consumers (idempotent).
    try:
        from app.core.prompt_templates import register_package_template_dirs
        register_package_template_dirs(registry.llm_template_dirs())
    except Exception as e:
        logger.error("Registering package template dirs failed: %s", e)
    try:
        from app.models.character_template import clear_template_cache
        clear_template_cache()
    except Exception as e:
        logger.debug("Character template cache clear failed: %s", e)

    # on_load hook (generic): a package may declare `on_load: <module.py>`
    # in its manifest to run registration code at load — e.g. registering a
    # capability provider (app.core.hooks.register_provider). This is how a
    # content package contributes CODE without a verb. The module runs in a
    # fresh state each force-reload; registration is expected to be
    # idempotent (register_provider overwrites).
    for pkg in registry.packages():
        rel = str(pkg.manifest.get("on_load", "") or "").strip()
        if not rel:
            continue
        try:
            _run_on_load(pkg, rel)
        except Exception as e:
            logger.error("Package '%s' on_load '%s' failed: %s", pkg.id, rel, e)

    return registry.packages()


def _run_on_load(pkg: Package, rel: str) -> None:
    """Import a package's on_load module so its top-level registration runs.
    Loaded by file path (same mechanism as skill modules) so installed and
    repo packages behave identically."""
    import importlib.util
    mod_path = (pkg.dir / rel).resolve()
    if not str(mod_path).startswith(str(pkg.dir.resolve())):
        raise ValueError(f"on_load path escapes package dir: {rel}")
    if not mod_path.exists():
        raise FileNotFoundError(f"on_load module not found: {mod_path}")
    spec = importlib.util.spec_from_file_location(
        f"plugins_onload_{pkg.id}", mod_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    logger.info("Package '%s' on_load ran: %s", pkg.id, rel)


def _package_gate(pkg: Package) -> bool:
    """Enabled gate for a package's NON-always_load verbs.

    Order: explicit ``skills.<id>.enabled`` in the world config wins, then
    the legacy env bridge (SKILL_<ID>_ENABLED), then the manifest's
    ``enabled_default`` (for packages that should load out of the box,
    e.g. core communication verbs like talk_to).

    Applied per verb entry: ``always_load`` entries ignore the gate (they
    load always, activation is per character) — a package can mix both,
    e.g. instagram's always-loaded reaction verbs next to the gated
    posting verb.
    """
    try:
        from app.core import config
        val = config.get(f"skills.{pkg.id}.enabled", None)
        if val is not None:
            return bool(val) if not isinstance(val, str) else val.lower() == "true"
    except Exception:
        pass
    env_prefix = pkg.manifest.get("env_prefix", f"SKILL_{pkg.id.upper()}_")
    env_val = os.getenv(f"{env_prefix}ENABLED", "")
    if env_val:
        return env_val.lower() == "true"
    return bool(pkg.manifest.get("enabled_default", False))


def _apply_skill_meta(skill: PluginSkill, entry: SkillEntry) -> None:
    """Resolve tool name/description from the package's skill template.

    Uses the shared skills/<id>.md format via load_skill_meta — the package
    template dir is part of the search path, so packages carry their own
    metadata. Falls back to whatever the class set itself.
    """
    try:
        from app.core.prompt_templates import load_skill_meta, template_exists
        if template_exists(f"skills/{entry.skill_id}.md"):
            meta = load_skill_meta(entry.skill_id)
            skill.name = meta.get("name") or skill.name
            skill.description = meta.get("description") or skill.description
            skill.action_hint = meta.get("action_hint", "") or getattr(
                skill, "action_hint", "")
    except Exception as e:
        logger.debug("Skill meta for %s not applied: %s", entry.skill_id, e)
    # One normal form: the description carries no closing period. Verbs that
    # extend it in as_tool append ". <more>" — a template sentence ending in
    # "." used to come out as "..".
    skill.description = (skill.description or "").rstrip(".")


def load_plugin(pkg: Package) -> List[Tuple[str, PluginSkill]]:
    """Instantiate the enabled verbs of one package.

    always_load entries load unconditionally; the others follow the
    package gate (config/env/enabled_default). Returns (skill_id,
    instance) pairs.
    """
    gate = _package_gate(pkg) if any(not e.always_load for e in pkg.skills) else True
    ctx = PluginContext(pkg.id)
    results: List[Tuple[str, PluginSkill]] = []
    for entry in pkg.skills:
        if not entry.always_load and not gate:
            logger.debug("Package verb '%s/%s' disabled (gate)", pkg.id, entry.skill_id)
            continue
        skill_class = _import_skill_class(pkg.dir, entry.module, entry.class_name)
        if skill_class is None:
            continue
        try:
            skill = skill_class({"enabled": True}, ctx, **entry.params)
            if not getattr(skill, "SKILL_ID", ""):
                skill.SKILL_ID = entry.skill_id
            if entry.always_load:
                skill.ALWAYS_LOAD = True
            # Tool metadata flags (F7) — manifest can only switch ON
            # (class attributes remain the baseline).
            if entry.singleton:
                skill.SINGLETON = True
            if entry.suppress_in_person:
                skill.SUPPRESS_IN_PERSON = True
            if entry.cascade_brake:
                skill.CASCADE_BRAKE = True
            if entry.search_intent:
                skill.SEARCH_INTENT = True
            if entry.delivers_speech:
                skill.DELIVERS_SPEECH = True
            if entry.intents:
                skill.INTENT_TYPES = tuple(entry.intents)
            if entry.intent_payload_keys:
                skill.INTENT_PAYLOAD_KEYS = tuple(entry.intent_payload_keys)
            if entry.user_notification:
                skill.USER_NOTIFICATION = True
            if entry.remote_comm:
                skill.REMOTE_COMM = True
            if entry.progress_type:
                skill.PROGRESS_TYPE = entry.progress_type
            _apply_skill_meta(skill, entry)
            logger.info("Package skill loaded: %s/%s (skill_id=%s)",
                        pkg.id, entry.module, entry.skill_id)
            results.append((entry.skill_id, skill))
        except Exception as e:
            logger.error("Error instantiating '%s/%s': %s", pkg.id, entry.skill_id, e)
    return results


def load_all_plugins(plugin_dir: Optional[Path] = None) -> Dict[str, PluginSkill]:
    """Discover and load all packages.

    Returns:
        Dict[skill_id, skill_instance]
    """
    results: Dict[str, PluginSkill] = {}
    for pkg in discover_packages(plugin_dir, force=True):
        for skill_id, skill in load_plugin(pkg):
            results[skill_id] = skill
    return results


def _resolve_rig_dependencies(rigs, package_id, slot_id):
    owners = {}
    for rig in rigs:
        for chain in rig.chains:
            for link in chain:
                owners.setdefault(link["bone"], []).append(rig.id)
    valid = []
    for rig in rigs:
        parents = [owners.get(name, []) for name in rig.external_parents]
        dependencies = {row[0] for row in parents if len(row) == 1}
        if any(len(row) != 1 for row in parents) or len(dependencies) > 1 or rig.id in dependencies:
            logger.warning("Package %s slot %s: rig dropped: unresolved parent for %s", package_id, slot_id, rig.id)
            continue
        rig.depends_on = next(iter(dependencies), None)
        valid.append(rig)
    accepted = set()
    while True:
        ready = {rig.id for rig in valid if rig.depends_on is None or rig.depends_on in accepted}
        if ready <= accepted:
            break
        accepted.update(ready)
    for rig in valid:
        if rig.id not in accepted:
            logger.warning("Package %s slot %s: rig dropped: missing dependency or cycle for %s", package_id, slot_id, rig.id)
    return [rig for rig in valid if rig.id in accepted]
