"""Character Template System

Templates live in shared/templates/character/ as JSON files (e.g. human-default.json).
Each character stores which template it uses in its profile ("template": "...").

Character templates support a base system: a template with "base": "base-character"
is merged with base-character.json at load time. The base provides core fields,
the extension adds profile-specific fields.

Field types:
  - text: Single-line or multi-line text (multiline: true)
  - number: Numeric value
  - season_day: World-calendar day without a year, "<season_key>:<day>"
  - select: Dropdown with predefined options [{value, label}]
"""
import copy
import json
import os
from collections import OrderedDict
from threading import RLock
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from app.core.log import get_logger

logger = get_logger("char_template")

# Templates directory
from app.core.paths import get_templates_dir


def list_templates(template_type: Optional[str] = None) -> List[Dict[str, str]]:
    """List all character templates.

    Reads only shared/templates/character/ — the expression/pose preset files
    live in their own subfolders and are no longer offered as character
    templates by mistake.

    template_type: still accepted but ignored; everything in the character/
    folder already is type="character".
    """
    templates = []
    for path in sorted(get_templates_dir().glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("selectable") is False:
                continue
            templates.append({
                "name": path.stem,
                "label": data.get("label", path.stem),
                "type": "character",
            })
        except Exception:
            templates.append({"name": path.stem, "label": path.stem, "type": "character"})
    return templates


def _merge_templates(base: Dict[str, Any], extension: Dict[str, Any]) -> Dict[str, Any]:
    """Merge an extension template into a base template.

    - features: merged (extension values win)
    - tabs: extension fully overrides if present
    - sections with matching ID: column/row overridable, fields merged with
      key-based deduplication (extension field wins over base field of same key)
    - new sections from extension: appended in order
    - top-level metadata (label, template_version): taken from extension
    """
    result = copy.deepcopy(base)

    # features: merge dicts, extension wins per key
    if "features" in extension:
        result.setdefault("features", {}).update(extension["features"])

    # tabs: extension fully overrides if present
    if "tabs" in extension:
        result["tabs"] = copy.deepcopy(extension["tabs"])

    # sections: merge by id
    base_section_index = {s["id"]: s for s in result.get("sections", [])}

    for ext_section in extension.get("sections", []):
        sid = ext_section["id"]
        if sid in base_section_index:
            base_sec = base_section_index[sid]
            # Allow extension to override layout attributes
            for attr in ("column", "row"):
                if attr in ext_section:
                    base_sec[attr] = ext_section[attr]
            # Merge fields: section row determines order (lower row = fields first).
            # Extension fields override base fields with matching key.
            base_fields = base_sec.get("fields", [])
            ext_fields = copy.deepcopy(ext_section.get("fields", []))
            ext_by_key = {f["key"]: f for f in ext_fields if "key" in f}
            ext_key_set = set(ext_by_key.keys())
            base_key_set = {f["key"] for f in base_fields if "key" in f}
            base_row = base_sec.get("row", 1)
            ext_row = ext_section.get("row", 1)
            if ext_row < base_row:
                # Extension fields first, then base-only fields at end
                merged = list(ext_fields)
                for bf in base_fields:
                    if bf.get("key") not in ext_key_set:
                        merged.append(copy.deepcopy(bf))
            else:
                # Base fields first (extension overrides matching keys), then ext-only at end
                merged = []
                for bf in base_fields:
                    key = bf.get("key")
                    if key and key in ext_by_key:
                        merged.append(ext_by_key[key])  # extension wins
                    else:
                        merged.append(copy.deepcopy(bf))
                for ef in ext_fields:
                    if ef.get("key") not in base_key_set:
                        merged.append(ef)
            base_sec["fields"] = merged
        else:
            result.setdefault("sections", []).append(copy.deepcopy(ext_section))

    # top-level metadata from extension
    for key in ("label", "template_version"):
        if key in extension:
            result[key] = extension[key]

    # Take over every remaining top-level field of the extension — the
    # extension wins. Without this, fields such as extra_activities,
    # outfit_imagegen, outfit_exceptions etc. are silently lost.
    _handled = {"features", "tabs", "sections", "label",
                "template_version", "base"}
    for key, value in extension.items():
        if key in _handled:
            continue
        result[key] = copy.deepcopy(value)

    return result


# Template cache — templates only change through admin save or a plugin
# reload; both invalidate via clear_template_cache(). Avoids disk I/O in the
# asyncio main loop on hot-path calls like ThoughtLoop._get_eligible_characters.
_template_cache: Dict[str, Optional[Dict[str, Any]]] = {}
_template_cache_lock = __import__("threading").RLock()
#: Bumped by every ``clear_template_cache``. A cache DERIVED from a template
#: (``soul_source_fields``) captures it before reading the template and
#: publishes only when it is unchanged — a clear that lands mid-read must not
#: be followed by the stale derivation being stored.
_template_generation = 0


def clear_template_cache() -> None:
    """Invalidate the template cache — called after save_template() and
    after plugin (re)discovery."""
    global _override_fields_cache, _template_generation
    with _template_cache_lock:
        _template_generation += 1
        _template_cache.clear()
        _field_keys_cache.clear()
        _soul_fields_cache.clear()
        _features_cache.clear()
        _override_fields_cache = None


def fragment_applies(frag: Dict[str, Any], template_name: str,
                     tmpl: Dict[str, Any]) -> bool:
    """Public check whether a package fragment's ``apply_to`` selector matches
    a template — also used by the skill dependency evaluation (F9)."""
    return _fragment_applies(frag, template_name, tmpl)


def _fragment_applies(frag: Dict[str, Any], template_name: str,
                      tmpl: Dict[str, Any]) -> bool:
    """Check a package fragment's ``apply_to`` selector against a template.

    Selector forms:
      "*"                          — every template
      ["human-roleplay", …]        — explicit template names
      {"feature": "<flag>"}        — templates with that feature enabled
    Missing/empty apply_to = fragment never applies (must be explicit).
    """
    sel = frag.get("apply_to")
    if sel == "*":
        return True
    if isinstance(sel, list):
        return template_name in sel
    if isinstance(sel, dict) and sel.get("feature"):
        return bool((tmpl.get("features") or {}).get(sel["feature"], False))
    return False


def _apply_package_fragments(name: str, tmpl: Dict[str, Any]) -> Dict[str, Any]:
    """Merge character-template fragments contributed by skill packages.

    Fragments use the regular extension-template format plus an ``apply_to``
    selector and are merged via _merge_templates — a removed package takes
    its fields (e.g. package-owned status_effects stats) with it.
    """
    try:
        # Declared view: the same fragments with or without plugin discovery.
        from app.plugins.loader import declared_character_fragments
        frags = declared_character_fragments()
    except Exception:
        return tmpl
    for frag in frags:
        if not _fragment_applies(frag, name, tmpl):
            continue
        body = {k: v for k, v in frag.items()
                if k not in ("apply_to", "_package_id")}
        try:
            tmpl = _merge_templates(tmpl, body)
        except Exception as e:
            logger.error("Package fragment (%s) failed on template '%s': %s",
                         frag.get("_package_id", "?"), name, e)
    return tmpl


def get_template(name: str = "default") -> Optional[Dict[str, Any]]:
    """Load a character template by name from shared/templates/character/.

    If the template declares "base": "<name>", the base template is loaded
    first and the extension is merged on top via _merge_templates; skill
    package fragments are merged afterwards.
    Base templates themselves must not declare a base (no recursion).
    Returns None if the template file is not found.

    The result is cached module-wide — changes require clear_template_cache
    (save_template and the plugin loader do that automatically).
    """
    with _template_cache_lock:
        if name in _template_cache:
            cached = _template_cache[name]
            # Deep copy so consumers cannot mutate the cached original
            if cached is None:
                return None
            return copy.deepcopy(cached)

    path = get_templates_dir() / f"{name}.json"
    if not path.exists():
        with _template_cache_lock:
            _template_cache[name] = None
        return None
    try:
        tmpl = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error("Error loading template '%s': %s", name, e)
        return None

    base_name = tmpl.get("base")
    if base_name:
        base_path = get_templates_dir() / f"{base_name}.json"
        if not base_path.exists():
            logger.warning("Base '%s' not found, using '%s' standalone", base_name, name)
        else:
            try:
                base = json.loads(base_path.read_text(encoding="utf-8"))
                tmpl = _merge_templates(base, tmpl)
            except Exception as e:
                logger.error("Error loading base '%s': %s", base_name, e)

    # Skill packages may extend templates (e.g. contribute status_effects
    # stats they own) — merged after base resolution, before caching.
    tmpl = _apply_package_fragments(name, tmpl)

    with _template_cache_lock:
        _template_cache[name] = tmpl
    return copy.deepcopy(tmpl)


def is_roleplay_character(character_name: str) -> bool:
    """True when the character is a roleplay character (vs. a chatbot).

    Criterion: profile["roleplay_instructions"] is set. That field exists only
    in the human-roleplay* templates and holds the "Important rules" (stay in
    character, you are a real person, ...).
    """
    try:
        from app.models.character import get_character_profile
        profile = get_character_profile(character_name) or {}
        return bool((profile.get("roleplay_instructions") or "").strip())
    except Exception:
        return False


def is_feature_enabled(character_name: str, feature: str, *, profile=None, config=None) -> bool:
    """Whether a feature is active for the character.

    Order:
      1. Per-character config override (a UI toggle like "Thoughts: on") —
         when the key is set explicitly in character_config.json it wins and
         can both switch the template default on and off.
      2. Template feature (e.g. ``human-default.features.thoughts_enabled``).
      3. Default: True (fail-open).

    Typical features (see the templates):
      memory_enabled, relationships_enabled, secrets_enabled,
      inventory_enabled, activities_enabled, locations_enabled,
      mood_tracking_enabled, thoughts_enabled, retrospect_enabled,
      status_effects_enabled, social_dialog_enabled, random_events_enabled,
      outfit_system_enabled, expression_variants_enabled, story_enabled,
      storydev_enabled
    """
    try:
        from app.models.character import get_character_profile, get_character_config
        # 1) Per-character config override
        try:
            cfg = config if config is not None else (get_character_config(character_name, profile=profile) or {})
            if feature in cfg:
                val = cfg[feature]
                # UI selects sometimes store strings instead of booleans
                if isinstance(val, str):
                    return val.lower() in ("true", "1", "yes", "ja")
                return bool(val)
        except Exception:
            pass
        # 2) Template default
        profile = profile if profile is not None else (get_character_profile(character_name) or {})
        tmpl_name = profile.get("template", "human-default")
        features = template_features(tmpl_name)
        if features is None:
            return True
        return bool(features.get(feature, True))
    except Exception:
        return True


def template_feature(character_name: str, feature: str,
                     default: bool = False) -> bool:
    """Template-only feature lookup that fails CLOSED.

    ``is_feature_enabled`` is deliberately fail-open: a template that omits a
    key grants the feature. That is right for capabilities that older templates
    predate, and wrong for a POSITIVE marker — a marker that every template
    silently carries marks nothing. This variant reads the template features
    only, ignores the per-character config override (a marker is a property of
    the KIND of character, not a per-character toggle) and returns ``default``
    (False) whenever the key, the template or the profile is missing.
    """
    try:
        from app.models.character import get_character_profile
        profile = get_character_profile(character_name) or {}
        features = template_features(profile.get("template") or "human-default")
        if features is None:
            return default
        return bool(features.get(feature, default))
    except Exception:
        return default


def feature_disabled(character_name: str, feature: str) -> bool:
    """True only when this character EXPLICITLY disables ``feature``.

    The mirror image of :func:`is_feature_enabled`, for WRITE gates.
    ``is_feature_enabled`` falls back to the ``human-default`` template when the
    profile names none — and that template disables everything. Using it to gate
    a write therefore turns a missing ``template`` field into silent data loss
    (a character that quietly stops remembering). A write gate must only fire on
    an explicit "off", never on an absent answer, so:

      * per-character config override wins, as always;
      * a profile without a template is never disabled;
      * an unknown template is never disabled;
      * a template that omits the key is never disabled (fail-open, as above).
    """
    try:
        from app.models.character import get_character_profile, get_character_config
        cfg = get_character_config(character_name) or {}
        if feature in cfg:
            val = cfg[feature]
            if isinstance(val, str):
                return val.strip().lower() not in ("true", "1", "yes", "ja")
            return not bool(val)
        profile = get_character_profile(character_name) or {}
        if not str(profile.get("template") or "").strip():
            return False
        return not template_feature(character_name, feature, default=True)
    except Exception:
        return False


def save_template(name: str, template: Dict[str, Any]) -> bool:
    """Save a template by name."""
    get_templates_dir().mkdir(parents=True, exist_ok=True)
    path = get_templates_dir() / f"{name}.json"
    try:
        path.write_text(
            json.dumps(template, ensure_ascii=False, indent=2),
            encoding="utf-8")
        clear_template_cache()
        return True
    except Exception as e:
        logger.error("Error saving template '%s': %s", name, e)
        return False


def delete_template(name: str) -> bool:
    """Delete a template by name. Cannot delete 'human-default'."""
    if name == "human-default":
        return False
    path = get_templates_dir() / f"{name}.json"
    if path.exists():
        path.unlink()
        return True
    return False


def get_all_template_fields(template: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Flatten all fields from all sections into a single list."""
    fields = []
    for section in template.get("sections", []):
        fields.extend(section.get("fields", []))
    return fields


def _select_options(field: Dict[str, Any]) -> List[Dict[str, str]]:
    """The options of a ``select`` field as ``{value, label, label_de}``;
    an option is a plain string or ``{value|id, label?, label_de?}``."""
    out = []
    for o in field.get("options") or []:
        if isinstance(o, str):
            o = {"value": o}
        v = o.get("value") if o.get("value") is not None else o.get("id")
        if v is None or str(v) == "":
            continue
        out.append({"value": str(v), "label": str(o.get("label") or v),
                    "label_de": str(o.get("label_de") or "")})
    return out


#: template name -> the field keys it carries (``template_field_keys``)
_field_keys_cache: Dict[str, frozenset] = {}


def template_field_keys(name: str) -> frozenset:
    """The field keys of one template (package fragments merged), cached
    with the template cache. A cheap "does this character have field X"
    for per-poll callers — ``get_template`` hands out a deep copy."""
    if not name:
        return frozenset()
    with _template_cache_lock:
        hit = _field_keys_cache.get(name)
    if hit is not None:
        return hit
    keys = frozenset(f.get("key") for f in get_all_template_fields(get_template(name) or {})
                     if f.get("key"))
    with _template_cache_lock:
        _field_keys_cache[name] = keys
    return keys


#: template name -> its ``(key, source_file)`` pairs (``soul_source_fields``)
_soul_fields_cache: Dict[str, Tuple[Tuple[str, str], ...]] = {}


def soul_source_fields(name: str) -> Tuple[Tuple[str, str], ...]:
    """The ``(profile key, source_file)`` pairs of one template, in template
    order — what ``_inject_soul_md_values`` reads on EVERY profile load.

    ``get_template`` hands out a deep copy of the whole template (sections,
    options, labels), which made it the hottest frame of the worldmap poll
    only for this walk over ``sections[].fields[]``. The walk is the same as
    there (``source_file`` truthy, ``key`` truthy, first-to-last), its result
    an immutable tuple, cached with the template cache: ``clear_template_cache``
    (save_template, the plugin loader) drops it. An unknown template is ``()``;
    a template that failed to load is not cached, so it is retried like
    ``get_template`` retries it.
    """
    with _template_cache_lock:
        hit = _soul_fields_cache.get(name)
        gen = _template_generation
    if hit is not None:
        return hit
    tmpl = get_template(name)
    if not tmpl:
        return ()
    pairs = []
    for section in tmpl.get("sections", []):
        for field in section.get("fields", []):
            source_file = field.get("source_file")
            if not source_file:
                continue
            key = field.get("key", "")
            if not key:
                continue
            pairs.append((key, source_file))
    fields = tuple(pairs)
    with _template_cache_lock:
        # Publish only under the generation captured BEFORE the read, and only
        # for a name the template cache holds (a load error is not cached).
        if _template_generation == gen and name in _template_cache:
            _soul_fields_cache[name] = fields
    return fields


#: template name -> its ``features`` value (``template_features``)
_features_cache: Dict[str, Any] = {}


def template_features(name: str) -> Optional[Any]:
    """A template's ``features`` value (``tmpl.get("features") or {}``) as a
    fresh copy, or None when ``get_template`` returns nothing for ``name``.

    For the per-character feature checks on the worldmap poll
    (``is_feature_enabled``, the species/extension-rig template selectors):
    they read ONLY ``features``, and ``get_template`` deep-copies the whole
    template for it. Cached with the template cache like
    ``soul_source_fields`` (same generation rule, load errors not cached).
    """
    with _template_cache_lock:
        hit = _features_cache.get(name, _features_cache)
        gen = _template_generation
    if hit is not _features_cache:
        return copy.deepcopy(hit)
    tmpl = get_template(name)
    if not tmpl:
        return None
    features = tmpl.get("features") or {}
    with _template_cache_lock:
        if _template_generation == gen and name in _template_cache:
            _features_cache[name] = features
    return copy.deepcopy(features)


_warned_override_fields: set = set()
#: ``(templates dir, fields)`` — rebuilt after ``clear_template_cache``
_override_fields_cache = None


def state_override_fields() -> List[Dict[str, Any]]:
    """Every character field a STATE may override, over all templates.

    A template field opts in with ``"state_override": true``. Only a
    ``select`` stored in the profile qualifies: the state editor offers its
    options and the save validates against them, and the effective value is
    read from the profile (``field_overrides.effective_field``). Any other
    field so marked is skipped with one warning. First template wins on a key
    that two templates define. Package fragments are included — they are
    merged into the templates by ``get_template``. Cached until the next
    ``clear_template_cache``; every call hands out a copy.
    """
    global _override_fields_cache
    tdir = str(get_templates_dir())
    with _template_cache_lock:
        cached = _override_fields_cache
    if cached is not None and cached[0] == tdir:
        return copy.deepcopy(cached[1])
    out: Dict[str, Dict[str, Any]] = {}
    # Every template file, not just the selectable ones (``list_templates``
    # hides those) — a field may live in a template nobody picks by hand.
    for path in sorted(get_templates_dir().glob("*.json")):
        tmpl = get_template(path.stem) or {}
        for field in get_all_template_fields(tmpl):
            key = field.get("key")
            if not key or not field.get("state_override") or key in out:
                continue
            options = _select_options(field)
            if field.get("type") != "select" or field.get("store") or not options:
                if key not in _warned_override_fields:
                    _warned_override_fields.add(key)
                    logger.warning("Template field %r: state_override needs a select "
                                   "with options stored in the profile — ignored", key)
                continue
            out[key] = {
                "key": key,
                "label": field.get("label") or key,
                "label_de": field.get("label_de") or "",
                "default": field.get("default"),
                "options": options,
            }
    fields = list(out.values())
    with _template_cache_lock:
        _override_fields_cache = (tdir, fields)
    return copy.deepcopy(fields)


import re


def get_prompt_fields(template: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return all fields where in_prompt is true, in template order."""
    fields = []
    for section in template.get("sections", []):
        for field in section.get("fields", []):
            if field.get("in_prompt", False):
                fields.append(field)
    return fields


def is_prompt_volatile(field: Dict[str, Any]) -> bool:
    """True when a prompt field's value changes from turn to turn.

    The chat prompt keeps such fields out of the cached identity block and
    renders them in the per-turn scene state instead (``chat/chat_moment.md``):
    one changed byte in the identity block would make everything behind it,
    the conversation history included, uncacheable for the backend.

    The template says so with ``"prompt_volatile": true``. Without the key a
    field counts as volatile when its value lives in ``status_effects`` — those
    are the stats that drift every hour, whatever pack declares them.
    """
    if "prompt_volatile" in field:
        return bool(field["prompt_volatile"])
    return field.get("store") == "status_effects"


def source_file_keys(template: Dict[str, Any]) -> Dict[str, str]:
    """Map profile key -> relative MD path for every ``source_file`` field.

    The template is the ONE place that says which fields live in a file
    instead of in the profile blob; every caller that has to tell the two
    apart (profile save, soul reader, the blob migration) asks here.
    """
    keys: Dict[str, str] = {}
    for section in template.get("sections", []):
        for field in section.get("fields", []):
            src = field.get("source_file")
            key = field.get("key")
            if src and key:
                keys[key] = src
    return keys


def build_prompt_section(
    template: Dict[str, Any], data: Dict[str, Any],
    active_features: Optional[Dict[str, Any]] = None,
    is_partner: bool = False, character_name: str = "",
    volatile: Optional[bool] = None) -> List[str]:
    """Build prompt lines from template + profile data.

    Handles: empty values (skip), lists (join), calendar days (label).
    If active_features is given, fields with "prompt_requires_feature"
    are only included when that feature is true in active_features.
    When is_partner=True, fields with "prompt_self_only": true are skipped
    (e.g. traits, goals, beliefs, rules belong only into the own character
    block, never into the partner block), and a field's "prompt_label_partner"
    replaces its "prompt_label" there — a label written to the speaker ("How
    others perceive you") would otherwise describe the partner as "you".

    Fields with "source_file" are loaded from an MD file in the character
    directory instead of from the profile data (character_name must be set for
    that). A missing or empty file means the field is skipped — there is no
    fallback to the profile blob.

    ``volatile`` filters by :func:`is_prompt_volatile`: None = every field,
    False = only the stable ones, True = only the per-turn ones.

    Returns a list of "Label: value" strings.
    """
    from app.core.stat_hints import active_band
    from app.core.stat_rules import rules_for_character, rules_for_template

    lines = []
    stat_rules = None
    for field in get_prompt_fields(template):
        if volatile is not None and is_prompt_volatile(field) != volatile:
            continue
        # Feature gate: include the field only when the feature is on. Order:
        #   1. per-character config override via is_feature_enabled (e.g.
        #      retrospect_enabled from the character config)
        #   2. template features dict (active_features)
        # That way the UI toggle "Retrospect: no" wins even when the template
        # has the underlying features (beliefs_enabled etc.) switched on.
        required_feature = field.get("prompt_requires_feature")
        if required_feature:
            if character_name:
                if not is_feature_enabled(character_name, required_feature):
                    continue
            elif active_features is not None:
                if not active_features.get(required_feature):
                    continue
        # Self-only: skip such fields in the partner block (avatar)
        if is_partner and field.get("prompt_self_only"):
            continue

        key = field["key"]

        # source_file: content comes from the MD file, NEVER from the profile.
        # There is deliberately no fallback to `data[key]`: a stale blob value
        # would outlive a reset that cleared the file (the file IS the truth).
        source_file = field.get("source_file")
        if source_file:
            # A linked character's SHARED sections are its leader's file.
            from app.core.linked_characters import soul_owner
            value = (load_source_file(soul_owner(character_name, source_file), source_file)
                     if character_name else "")
        elif field.get("store") == "status_effects":
            from app.core.stat_boosts import effective_stat
            value = effective_stat(data, key)
        elif field.get("state_override"):
            # An active state may override the stored value — the prompt
            # renders what is in effect, never the stored value under it.
            from app.core.field_overrides import effective_field
            value = effective_field(data, key)[0]
        else:
            value = data.get(key)

        # A stat of 0 is a value; for every other field an empty value falls
        # back to the template default as before.
        is_stat = field.get("store") == "status_effects" and not source_file
        if (value is None) if is_stat else (not value):
            value = field.get("default")
            if (value is None) if is_stat else (not value):
                continue

        label = ((is_partner and field.get("prompt_label_partner"))
                 or field.get("prompt_label") or field.get("label", key))
        if is_stat:
            if stat_rules is None:
                stat_rules = (rules_for_character(character_name, profile=data)
                              if character_name else rules_for_template(template))
            band = active_band(stat_rules.get(key, {}), value)
            note = f" — {band['text']}" if band and band.get("text") else ""
            lines.append(f"{label}: {value}/100{note}")
            continue

        # Special handling
        prompt_format = field.get("prompt_format")
        if prompt_format == "list":
            if isinstance(value, list):
                value = ", ".join(str(v) for v in value if v)
                if not value:
                    continue
        elif prompt_format == "season_day":
            # A world-calendar day without a year, stored as
            # "<season_key>:<day>" — a recurring day such as a birthday, not
            # the current date the prompts get elsewhere. A value the calendar
            # no longer knows (season deleted, shortened) drops the line.
            from app.core.game_time import parse_season_day, season_day_label
            parsed = parse_season_day(value)
            if not parsed:
                continue
            value = season_day_label(parsed[0], parsed[1])
            if not value:
                continue

        # Multiline value (e.g. structured MD): label on its own line.
        # Multiline blocks are separated visually (blank line before + after) so
        # that following single-line fields (Attention, Appearance, ...) do not
        # stick to the body.
        if isinstance(value, str) and "\n" in value:
            if lines and lines[-1] != "":
                lines.append("")
            lines.append(f"{label}:")
            lines.append(value)
            lines.append("")
        else:
            lines.append(f"{label}: {value}")
    # Trim the trailing blank
    while lines and lines[-1] == "":
        lines.pop()
    return lines


_SOURCE_CACHE = OrderedDict()
_SOURCE_CACHE_LOCK = RLock()


def invalidate_source_file(path: Path) -> None:
    """Discard the cached source after a writer updates its file."""
    with _SOURCE_CACHE_LOCK:
        _SOURCE_CACHE.pop(Path(os.path.abspath(path)), None)


def load_source_file(character_name: str, relpath: str) -> str:
    """Load the content of an MD/text file from the character directory.

    This is THE reader for every ``source_file`` field — the MD file is the
    single source of truth for those fields; save_character_profile keeps
    them out of the profile blob (see ``source_file_keys``).

    Preparation for consumers (system prompt, thoughts, secrets, ...):
    - drop lock/edit markers (HTML comments)
    - drop the top `# ...` heading (the label takes that role)
    - drop empty `## Section` headings (no body -> noise)

    Empty string when the file is missing, empty or only holds empty sections.
    """
    try:
        from app.models.character import get_character_dir
        p = Path(os.path.abspath(get_character_dir(character_name) / relpath))
        with _SOURCE_CACHE_LOCK:
            try:
                st = os.stat(p)
            except OSError:
                _SOURCE_CACHE.pop(p, None)
                return ""
            identity = (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)
            cached = _SOURCE_CACHE.get(p)
            if cached is not None and cached[:5] == identity:
                _SOURCE_CACHE.move_to_end(p)
                return cached[5]
            text = strip_empty_sections(p.read_text(encoding="utf-8"))
            _SOURCE_CACHE[p] = (*identity, text)
            _SOURCE_CACHE.move_to_end(p)
            if len(_SOURCE_CACHE) > 2048:
                _SOURCE_CACHE.popitem(last=False)
            return text
    except Exception:
        return ""


def strip_empty_sections(text: str) -> str:
    """Reduce soul markdown to what actually says something.

    Drops lock/edit markers, the top `# ...` heading and every `## Section`
    without a body. THE yardstick for "is this empty": a file holding nothing
    but headings is a scaffold, and so is a value that looks like one. Both
    have to answer the same way, or a migration counts a scaffold as content.
    """
    try:
        import re as _re
        # Strip every HTML comment: lock markers (<!-- EDITABLE -->) and the
        # writing hints the soul scaffolds carry. Neither is content — a
        # section holding only a hint is empty, and a hint must never reach
        # a prompt (a fresh character used to send them to the model).
        text = _re.sub(r"<!--.*?-->[ \t]*\n?", "", text or "", flags=_re.S)

        # Split into sections, drop empty ones, drop the top heading.
        lines = text.splitlines()
        result_parts = []
        cur_heading = None  # None = before the first ## heading
        cur_body = []

        def _flush():
            if cur_heading is None:
                # Prelude before the first ## (top `# Title`, blank lines) — discard
                return
            body_text = "\n".join(cur_body).strip()
            if body_text:
                result_parts.append(f"## {cur_heading}")
                result_parts.append(body_text)
                result_parts.append("")  # separator

        for line in lines:
            if line.startswith("# ") and not line.startswith("## "):
                # Ignore the top heading
                _flush()
                cur_heading = None
                cur_body = []
            elif line.startswith("## "):
                _flush()
                cur_heading = line[3:].strip()
                cur_body = []
            else:
                cur_body.append(line)
        _flush()

        return "\n".join(result_parts).strip()
    except Exception:
        return ""


def build_replacement_map(
    template: Dict[str, Any], profile: Dict[str, Any], target_key: str
) -> Dict[str, str]:
    """Build a map of {token} -> resolved value for a given target field.

    Only fields with a "replacement" config whose "target" matches target_key
    are included. Supports computed values (e.g. the height phrase from the
    height in centimetres).
    """
    token_map = {}
    for field in get_all_template_fields(template):
        # Skip fields hidden by visible_when
        if not _is_field_visible(field, profile):
            continue
        repl = field.get("replacement")
        if not repl:
            continue
        # Check target match (string or list)
        targets = repl.get("target", "")
        if isinstance(targets, str):
            targets = [targets]
        if target_key not in targets:
            continue

        token = repl.get("token", field["key"])
        source_key = field["key"]
        raw_value = profile.get(source_key)

        if raw_value is None or not str(raw_value).strip() or str(raw_value) == "__custom__":
            continue

        # Apply compute transform
        compute = repl.get("compute")
        if compute == "height_phrase":
            # Stored in centimetres (for the 3D client), rendered as the
            # descriptive phrase the prompts have always used.
            from app.core.height import height_phrase
            computed = height_phrase(profile)
            if computed:
                token_map[token] = computed
        else:
            token_map[token] = str(raw_value)

    return token_map


def resolve_profile_tokens(
    text: str,
    profile: Dict[str, Any],
    template: Optional[Dict[str, Any]] = None,
    target_key: str = ""
) -> str:
    """Replace {key} tokens in text with values from the profile.

    When template is provided, only tokens explicitly configured via
    "replacement" fields targeting target_key are resolved.
    When template is None, falls back to replacing all {key} with profile values.
    """
    if not text or "{" not in text:
        return text

    if template and target_key:
        token_map = build_replacement_map(template, profile, target_key)
        def replacer(match):
            key = match.group(1)
            return token_map.get(key, match.group(0))
    else:
        # Fallback: replace any {key} with profile value
        def replacer(match):
            key = match.group(1)
            value = profile.get(key)
            if value is not None and str(value).strip() and str(value) != "__custom__":
                return str(value)
            return match.group(0)

    return re.sub(r"\{(\w+)\}", replacer, text)


def _is_field_visible(field: Dict[str, Any], data: Dict[str, Any]) -> bool:
    """Check if a field is visible given the current data (visible_when support)."""
    vw = field.get("visible_when")
    if not vw:
        return True
    dep_key = vw.get("field", "")
    dep_value = data.get(dep_key, "")
    return dep_value in vw.get("values", [])






def resolve_template_name(name: str) -> Optional[str]:
    """Resolve a template reference to an INSTALLED template name.

    Returns the name unchanged if a matching template file exists; otherwise
    maps by family to an installed template:
      - anything containing "animal" (or "pet") -> animal-default
      - anything containing "roleplay"           -> human-roleplay
      - exactly "human" / "default"              -> human-default

    Returns ``None`` if the name is empty or no family match is installed —
    the caller decides how to surface that (warn vs. hard fallback).

    This is the single source of truth for "the referenced template is not
    present in this world". The prime case: a character exported from a world
    that had the private ``human-roleplay-nsfw`` template (it only ships in
    the NSFW pack repo) is imported here, where only the SFW templates exist.
    The "roleplay" heuristic maps it to human-roleplay without this module
    having to name the deleted template.
    """
    n = (name or "").strip()
    if not n:
        return None
    if get_template(n) is not None:
        return n
    low = n.lower()
    order: List[str] = []
    if "animal" in low or low == "pet":
        order.append("animal-default")
    if "roleplay" in low:
        order.append("human-roleplay")
    if low in ("human", "default"):
        order.append("human-default")
    for cand in order:
        if get_template(cand) is not None:
            return cand
    return None


def normalize_character_template(name: str) -> bool:
    """Remap a character whose template is not installed here to an installed
    one (DB column + profile blob). Returns True if the template changed.

    Used at character import (marketplace / content packs) so a character
    referencing a template absent from this world — e.g. the private
    ``human-roleplay-nsfw`` — renders instead of dangling on a missing file.
    Import must always land on a valid template, so an unresolvable name
    falls back to human-default.
    """
    try:
        from app.models.character import (get_character_profile,
                                          save_character_profile)
    except Exception:
        return False
    profile = get_character_profile(name) or {}
    cur = (profile.get("template") or "").strip()
    if not cur or get_template(cur) is not None:
        return False  # empty or already installed — nothing to do
    resolved = resolve_template_name(cur)
    if not resolved and get_template("human-default") is not None:
        resolved = "human-default"
    if not resolved or resolved == cur:
        return False
    profile["template"] = resolved
    save_character_profile(name, profile)
    clear_template_cache()
    logger.info("template normalize: %s '%s' -> '%s'", name, cur, resolved)
    return True


def migrate_stale_templates_once() -> None:
    """One-time, idempotent boot migration: normalize every character whose
    template is not installed in this world to an installed one (via
    :func:`normalize_character_template`).

    Catches characters imported *after* an earlier per-world migration ran
    (e.g. a character carrying the deleted ``human-roleplay-nsfw`` template,
    imported once the marketplace shipped it). Guarded by a world_kv marker.
    Generalizes the former nsfw-only migration — no template name is hardcoded
    here; the resolver's family heuristic does the mapping.
    """
    try:
        from app.models.world import get_world_setting, set_world_setting
        from app.models.character import list_available_characters
    except Exception:
        return
    if get_world_setting("migration.stale_templates_v1", "") == "done":
        return
    changed = []
    try:
        for name in list_available_characters():
            if normalize_character_template(name):
                changed.append(name)
        set_world_setting("migration.stale_templates_v1", "done")
        if changed:
            logger.info("stale-template migration: %d character(s) remapped: %s",
                        len(changed), ", ".join(changed))
    except Exception as e:
        logger.warning("stale-template migration failed: %s", e)


def migrate_prune_stale_stats_once() -> None:
    """One-time, idempotent prune of stale status_effects: after a template
    change (e.g. a stat moving out of the core template into package
    content) a character may carry stat values its template no longer
    declares. Drops
    every status_effects key not declared by the character's template.

    Template-driven (no hardcoded stat names), world_kv-marked.
    """
    try:
        from app.models.world import get_world_setting, set_world_setting
        from app.models.character import (list_available_characters,
                                          get_character_profile,
                                          save_character_profile)
        from app.core.stat_hints import template_stat_keys
    except Exception:
        return
    if get_world_setting("migration.prune_stale_stats_v1", "") == "done":
        return
    changed = []
    try:
        tmpl_keys: dict = {}
        for name in list_available_characters():
            profile = get_character_profile(name) or {}
            stats = profile.get("status_effects")
            if not isinstance(stats, dict) or not stats:
                continue
            tname = (profile.get("template") or "").strip()
            if tname not in tmpl_keys:
                tmpl_keys[tname] = template_stat_keys(get_template(tname) or {})
            allowed = tmpl_keys[tname]
            stale = [k for k in stats if k not in allowed]
            if stale:
                for k in stale:
                    stats.pop(k, None)
                profile["status_effects"] = stats
                save_character_profile(name, profile)
                changed.append(f"{name}({','.join(stale)})")
        set_world_setting("migration.prune_stale_stats_v1", "done")
        if changed:
            logger.info("stale-stats prune: %s", ", ".join(changed))
    except Exception as e:
        logger.warning("stale-stats prune failed: %s", e)
