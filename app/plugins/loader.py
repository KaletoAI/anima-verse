"""PluginLoader — discovers and loads skill packages from ``plugins/``.

A skill package is a folder with a ``plugin.yaml`` manifest. Beyond skill
classes a package may contribute templates, admin config schema, character
template fragments and state-flag lifecycle declarations (see
``docs/plugins.md`` and development_instructions/plan-skill-plugin-architecture.md).

Manifest format (package format v1):

    name: intimacy
    version: "1.0.0"
    description: ...
    # Verbs — single form (skill_id/module at top level) or list form:
    skills:
      - skill_id: start_intimate
        module: skill.py          # default skill.py
        class: IntimateSkill      # default: first PluginSkill subclass
        params: {active: true}    # constructor kwargs (parameterized verbs)
        always_load: true         # load always, activate per character
        default_enabled: false    # enabled for newly created characters
    templates:
      llm: templates/llm          # added to the prompt-template search path
      character:                  # character-template fragments (merged)
        - templates/character/lust.json
    config_schema:                # admin settings subsections under "skills"
      intimacy:
        label: Intimacy
        fields: {...}
    state_flags:                  # lifecycle declarations (flag executor)
      - flag: is_intimate
        cleared_by: end_intimate
        prompt_when_set: "..."
        ttl_minutes: 120
        reset_on_location_change: true

Skill name/description resolve from ``<llm templates>/skills/<skill_id>.md``
when present (same format as shared/templates/llm/skills/) — otherwise the
skill class sets them itself.
"""
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Type

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


def _parse_package(entry_dir: Path, meta: Dict[str, Any]) -> Optional[Package]:
    """Parse one manifest into a Package (contributions resolved, no skills instantiated)."""
    pkg = Package(id=entry_dir.name, dir=entry_dir, manifest=meta)
    pkg.capability_label = str(meta.get("capability_label", "") or "").strip()
    pkg.capability_description = str(meta.get("capability_description", "") or "").strip()
    pkg.being = str(meta.get("being", "") or "").strip().lower()
    pkg.skills = _parse_skill_entries(meta)
    if not meta.get("name"):
        logger.warning("Package %s: name missing in plugin.yaml", entry_dir.name)
        return None

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
        ))

    # Content-only packages (no verbs) are allowed as long as they contribute
    # SOMETHING (templates, fragments, config, flags, species content).
    # Contributions apply as soon as the package sits in the filesystem; the
    # enabled gate only governs verb loading.
    if not pkg.skills and not (pkg.llm_template_dir or pkg.character_fragments
                               or pkg.config_subsections or pkg.flags
                               or pkg.silhouette or pkg.body_slots
                               or pkg.piece_slots or meta.get("on_load")):
        logger.warning("Package %s: neither skills nor contributions in plugin.yaml",
                       entry_dir.name)
        return None

    return pkg


def discover_packages(plugin_dir: Optional[Path] = None,
                      force: bool = False) -> List[Package]:
    """Discover all packages and (re)populate the registry.

    Idempotent: subsequent calls return the registered packages unless
    ``force`` is set (skill reload). Wires cross-module contributions:
    prompt-template search path and template caches.
    """
    global _discovered
    if _discovered and not force and plugin_dir is None:
        return registry.packages()

    base = plugin_dir or PLUGIN_DIR
    registry.clear_registry()

    def _scan(root: Path, *, installed: bool) -> None:
        if not root.exists():
            if not installed:
                logger.info("Plugin directory not found: %s", root)
            return
        for entry in sorted(root.iterdir()):
            manifest = entry / "plugin.yaml"
            if not entry.is_dir() or not manifest.exists():
                continue
            if installed and registry.get_package(entry.name):
                logger.warning(
                    "Installed package '%s' shadows a repo package — skipped",
                    entry.name)
                continue
            try:
                meta = _load_yaml(manifest)
            except Exception as e:
                logger.error("Error reading %s: %s", manifest, e)
                continue
            pkg = _parse_package(entry, meta)
            if pkg:
                registry.register_package(pkg)

    _scan(base, installed=False)
    _scan(base / INSTALLED_DIR_NAME, installed=True)

    # Dependency presence (F9): a package whose `requires` are not all
    # present stays completely inert (no verbs, no contributions) —
    # repeated until stable so dependency chains unwind.
    while True:
        present = {p.id for p in registry.packages()}
        broken = [p for p in registry.packages()
                  if any(r not in present for r in p.requires)]
        if not broken:
            break
        for p in broken:
            missing = [r for r in p.requires if r not in present]
            logger.warning("Package '%s' inert — required package(s) missing: %s",
                           p.id, ", ".join(missing))
            registry.unregister_package(p.id)

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
