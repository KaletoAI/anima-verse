"""Saving ONE config layer from an admin page.

Two pages edit the config: /admin/settings the instance part, Game-Admin →
Setup the world part. Each page only ever sees and sends its own part;
``save_layer`` merges that against the CURRENT part of the same scope and
hands it to ``config.save_part``, which takes the other part from memory.
A world-scope path in an instance body (or the reverse) is a 400, never a
silent drop.
"""
from typing import Any, Dict, List

from app.core import config, config_scope
from app.core.log import get_logger

logger = get_logger("config_admin")


class LayerSaveError(ValueError):
    """The body cannot be saved as it is — the message goes to the admin (400)."""


def _other(scope: str) -> str:
    return config_scope.WORLD if scope == config_scope.INSTANCE else config_scope.INSTANCE


def layer_part(scope: str) -> Dict[str, Any]:
    inst, world, _unknown = config_scope.split_by_scope(config.get_all())
    return inst if scope == config_scope.INSTANCE else world


def layer_view(scope: str) -> Dict[str, Any]:
    data = layer_part(scope)
    apply_schema_defaults(data, config_scope.schema_for(scope))
    return data


def origin(scope: str) -> Dict[str, Any]:
    return {"overrides": config_scope.override_paths(
        config_scope.prune(layer_part(scope)))}


def duplicate_names(part: Any, path: str = "") -> List[str]:
    out: List[str] = []
    if isinstance(part, dict):
        for key, value in part.items():
            out += duplicate_names(value, f"{path}.{key}" if path else str(key))
    elif isinstance(part, list):
        seen = set()
        for entry in part:
            name = entry.get("name") if isinstance(entry, dict) else None
            if isinstance(name, str) and name:
                if name in seen:
                    out.append(f"{path}: duplicate name '{name}'")
                seen.add(name)
            out += duplicate_names(entry, path)
    return out


def check_resets(scope: str, resets: Any) -> List[str]:
    """The validated reset paths: strings, of ``scope``, never inside a
    list entry (a list is reset as a whole, its entries have no default)."""
    if not isinstance(resets, (list, tuple)) or not all(isinstance(p, str) and p for p in resets):
        raise LayerSaveError("resets must be a list of paths")
    for path in resets:
        if any(seg.isdigit() or "[" in seg for seg in path.split(".")):
            raise LayerSaveError(f"reset path '{path}' points into a list entry")
        if config_scope.scope_of(path) != scope:
            raise LayerSaveError(f"reset path '{path}' is not a {scope} setting")
    return list(resets)


def apply_resets(merged: Dict[str, Any], resets: List[str]) -> None:
    """Put the shipped value at every reset path, or drop the key when
    nothing ships there. Runs AFTER the preserve/strip steps, so neither can
    bring back what the admin reset."""
    for path in resets:
        parts = path.split(".")
        has, value = config_scope.shipped_default(path)
        node = merged
        for seg in parts[:-1]:
            nxt = node.get(seg)
            if not isinstance(nxt, dict):
                if not has:
                    node = None
                    break
                nxt = node[seg] = {}
            node = nxt
        if node is None:
            continue
        if has:
            node[parts[-1]] = value
        else:
            node.pop(parts[-1], None)

def apply_schema_defaults(data: dict, schema: dict) -> None:
    """Prefills empty config fields with their schema defaults.

    Iterates over the supplied scope schema and fills missing or empty
    values whenever a 'default' is defined — so the admin user immediately
    sees which fallback would be active.
    """
    for section_key, section_def in schema.items():
        # Virtual sections (e.g. llm_simple) have no config field of their
        # own — don't create one, or an empty {} lands in config.json.
        if section_def.get("virtual"):
            continue
        is_array = section_def.get("is_array", False)
        fields = section_def.get("fields", {})
        # sub_arrays (e.g. image_generation.backends): fill defaults on each
        # item, honoring applicable_for/visible_when so type-specific fields
        # don't get materialized on items they never render for.
        for sub_key, sub_def in (section_def.get("sub_arrays") or {}).items():
            sub_fields = (sub_def or {}).get("fields", {})
            section_data = data.get(section_key)
            items = section_data.get(sub_key) if isinstance(section_data, dict) else None
            if sub_fields and isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        _fill_item_defaults(item, sub_fields)
        if is_array:
            items = data.get(section_key)
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                _fill_defaults(item, fields)
                for nested_key, nested_def in fields.items():
                    if isinstance(nested_def, dict) and nested_def.get("is_array"):
                        nested_items = item.get(nested_key)
                        if isinstance(nested_items, list):
                            nested_fields = nested_def.get("item_fields", {})
                            for ni in nested_items:
                                if isinstance(ni, dict):
                                    _fill_defaults(ni, nested_fields)
        else:
            section_data = data.get(section_key)
            if not isinstance(section_data, dict):
                # Create a missing section; its fields must remain nested
                # so the frontend can render them in their section.
                section_data = {}
                data[section_key] = section_data
            _fill_defaults(section_data, fields)


def _visible_when_ok(item: dict, cond: dict) -> bool:
    """Evaluates a schema `visible_when` condition against a config item.

    Every entry must match: a plain value compares for equality, a LIST means
    "one of these" (e.g. Category in [txt2img, img2img]). Mirrors the client
    side in static/admin/settings.js.
    """
    for key, want in cond.items():
        cur = item.get(key) or ""
        if isinstance(want, (list, tuple, set)):
            if cur not in want:
                return False
        elif cur != want:
            return False
    return True


def _fill_item_defaults(item: dict, fields: dict) -> None:
    """Like _fill_defaults, but skips fields the item never renders:
    `applicable_for` mismatching the item's api_type, and `visible_when`
    conditions on sibling values (evaluated in field order, so a default
    filled earlier — e.g. category='generate' — gates later fields).
    Placeholder-type fields are never materialized (_PLACEHOLDER_TYPES)."""
    for key, field_def in fields.items():
        if not isinstance(field_def, dict):
            continue
        if field_def.get("type") in _PLACEHOLDER_TYPES:
            continue
        applicable = field_def.get("applicable_for")
        if applicable and (item.get("api_type") or "") not in applicable:
            continue
        not_applicable = field_def.get("not_applicable_for")
        if not_applicable and (item.get("api_type") or "") in not_applicable:
            continue
        cond = field_def.get("visible_when")
        if isinstance(cond, dict) and not _visible_when_ok(item, cond):
            continue
        default = field_def.get("default")
        if default is None:
            continue
        current = item.get(key)
        if current is None or current == "":
            item[key] = default
            logger.debug("Config default filled (item): %s = %r", key, default)


# Field types whose default is shown GREYED as a placeholder in the empty
# field instead of being materialized (user directive 2026-07-06, like the
# use-case styles editor): writing the default in would persist it on save
# and freeze future built-in updates. Bool/select cannot display a
# placeholder and keep real default values.
_PLACEHOLDER_TYPES = {"str", "text", "int", "float", "number"}


def _fill_defaults(obj: dict, fields: dict) -> None:
    """Sets missing/empty values in obj to the field default (bool/select
    only — see _PLACEHOLDER_TYPES) and clears legacy-default leftovers."""
    for key, field_def in fields.items():
        if not isinstance(field_def, dict):
            continue
        current = obj.get(key)
        # Legacy cleanup: a stored value that is just an old shipped default
        # (persisted by the former prefill) counts as "not customized" —
        # clear it so the placeholder + current built-in apply again.
        legacy = field_def.get("legacy_defaults")
        if legacy and isinstance(current, str) and current.strip() in legacy:
            obj[key] = ""
            continue
        if field_def.get("type") in _PLACEHOLDER_TYPES:
            continue
        default = field_def.get("default")
        if default is None:
            continue
        if current is None or current == "":
            obj[key] = default
            logger.debug("Config default filled: %s = %r", key, default)


def _preserve_unsent_subarray_fields(merged: dict, current: dict, schema: dict) -> None:
    """Keep schema fields of sub_array/is_dict items the payload leaves out.

    Frontend bug: `setVal()` updates CONFIG only on `onchange`. A field that
    is undefined before its first edit (e.g. a new schema field an old world
    config still lacks) and that the user never touches stays undefined ->
    JSON.stringify drops the key -> `merge_sensitive` reads the missing key
    as 'deliberately deleted'.

    We walk all schema `sub_arrays` (e.g. image_generation.backends) and
    carry missing fields over from the current config. List items pair via
    `config.pair_entries` — by name for named lists — so an entry inserted
    mid-list never inherits its neighbour's fields.
    """
    for sec_key, sec_def in schema.items():
        sub_arrays = sec_def.get("sub_arrays") or {}
        if not sub_arrays:
            continue
        cur_sec = current.get(sec_key)
        new_sec = merged.get(sec_key)
        if not isinstance(cur_sec, dict) or not isinstance(new_sec, dict):
            continue
        for sub_key, sub_def in sub_arrays.items():
            field_keys = list((sub_def.get("fields") or {}).keys())
            if not field_keys:
                continue
            cur_sub = cur_sec.get(sub_key)
            new_sub = new_sec.get(sub_key)
            if cur_sub is None or new_sub is None:
                continue
            if sub_def.get("is_dict"):
                if not isinstance(cur_sub, dict) or not isinstance(new_sub, dict):
                    continue
                for item_id, new_item in new_sub.items():
                    cur_item = cur_sub.get(item_id)
                    if not isinstance(cur_item, dict) or not isinstance(new_item, dict):
                        continue
                    for f in field_keys:
                        if f not in new_item and f in cur_item:
                            new_item[f] = cur_item[f]
            else:
                if not isinstance(cur_sub, list) or not isinstance(new_sub, list):
                    continue
                for new_item, cur_item in zip(new_sub, config.pair_entries(new_sub, cur_sub)):
                    if not isinstance(cur_item, dict) or not isinstance(new_item, dict):
                        continue
                    for f in field_keys:
                        if f not in new_item and f in cur_item:
                            new_item[f] = cur_item[f]


def _preserve_unsent_image_routing(merged: dict, current: dict) -> None:
    """Keep the stored ``image_generation.routing`` when the payload's
    image_generation section carries no routing (key missing or null).

    The settings page posts ``JSON.stringify(CONFIG)``; a tab loaded before
    the chains existed has no ``routing`` key, and ``merge_sensitive`` reads
    a missing key as deleted. A dropped routing would make the next config
    load re-seed the chains from the old default fields, silently discarding
    every edited chain — so absence never deletes. An explicit ``{}`` is a
    real clear and is saved as such."""
    cur_ig = current.get("image_generation")
    new_ig = merged.get("image_generation")
    if not isinstance(cur_ig, dict) or not isinstance(new_ig, dict):
        return
    if new_ig.get("routing") is None and cur_ig.get("routing") is not None:
        new_ig["routing"] = cur_ig["routing"]


def drop_masked(value: Any) -> Any:
    """``value`` with every '***'-masked string blanked to "" — for a payload
    part that has no stored counterpart to unmask from. A mask is never
    persisted literally."""
    if isinstance(value, dict):
        return {k: drop_masked(v) for k, v in value.items()}
    if isinstance(value, list):
        return [drop_masked(v) for v in value]
    if isinstance(value, str) and value.startswith("***"):
        return ""
    return value


def merge_sensitive(new: Any, current: Any) -> Any:
    """Recursively merge, keeping current values where new has masked placeholders.

    IMPORTANT: keys MISSING from the new dict were deleted on purpose and are
    NOT restored from current. Only leaf values masked with '***' are
    protected. List items pair via `config.pair_entries` — by name for named
    lists, so a masked key stays with its entry when entries move. A masked
    value without a counterpart (new key, unpaired entry) becomes "".
    """
    if isinstance(new, dict) and isinstance(current, dict):
        result = {}
        # Take only the keys of new — a missing key means deleted.
        for key in new:
            if key in current:
                result[key] = merge_sensitive(new[key], current[key])
            else:
                result[key] = drop_masked(new[key])
        return result
    if isinstance(new, list) and isinstance(current, list):
        return [
            drop_masked(item) if counterpart is None else merge_sensitive(item, counterpart)
            for item, counterpart in zip(new, config.pair_entries(new, current))
        ]
    # If new value is a masked placeholder, keep current
    if isinstance(new, str) and new.startswith("***"):
        return current
    return new


def diff_sections(current: dict, merged: dict) -> list:
    """Return changed top-level sections using a nested JSON comparison."""
    import json
    keys = set(current.keys()) | set(merged.keys())
    changed = []
    for k in keys:
        if json.dumps(current.get(k), sort_keys=True, default=str) != \
           json.dumps(merged.get(k), sort_keys=True, default=str):
            changed.append(k)
    return sorted(changed)


def apply_section_reloads(changed_keys: list, scope: str) -> list:
    """Reload services for changed sections, logging failures without raising."""
    if scope == config_scope.WORLD:
        changed_keys = [key for key in changed_keys if key == "skills"]
    if not changed_keys:
        return []

    from app.core.log import get_logger as _gl
    _log = _gl("admin_settings")
    triggered = []

    def _run(label: str, fn):
        try:
            fn()
            triggered.append(label)
            _log.info("settings_save: reloaded '%s' (trigger: %s)", label, changed_keys)
        except Exception as e:
            _log.warning("settings_save: reload '%s' failed: %s", label, e)

    # Provider manager: providers + image_generation (image backends get
    # their own channels, so both sections affect the channel setup).
    if "providers" in changed_keys or "image_generation" in changed_keys:
        from app.core.provider_manager import reload_provider_manager
        _run("providers", reload_provider_manager)

    # Skills read image backend env blocks during initialization.
    if "skills" in changed_keys or "image_generation" in changed_keys:
        from app.core.dependencies import _skill_manager
        if _skill_manager is not None:
            _run("skills", _skill_manager.reload_skills)

    # TTS service.
    if "tts" in changed_keys:
        from app.core.tts_service import reload_tts_service
        _run("tts", reload_tts_service)

    # Video backends live in image_generation.backends now, so the image
    # service reload above (image_generation changed_keys) covers them — no
    # separate animation hook anymore.

    return triggered



def strip_materialized_item_defaults(merged: dict, current: dict, schema: dict) -> None:
    """Remove view-only bool/select defaults from paired, existing entries.

    Lists are whole overrides, so pruning cannot remove their individual
    fields. Only defaults absent from the stored counterpart are stripped;
    new entries and explicit values on existing entries remain intact.
    """
    def strip_items(new, cur, fields):
        if not isinstance(new, list):
            return
        counterparts = config.pair_entries(new, cur if isinstance(cur, list) else [])
        for item, counterpart in zip(new, counterparts):
            if not isinstance(item, dict):
                continue
            for key, field in fields.items():
                if not isinstance(field, dict):
                    continue
                if (isinstance(counterpart, dict) and key not in counterpart
                        and key in item and field.get("type") not in _PLACEHOLDER_TYPES
                        and "default" in field and item[key] == field["default"]):
                    del item[key]
                if field.get("is_array"):
                    strip_items(item.get(key), counterpart.get(key) if isinstance(counterpart, dict) else None,
                                field.get("item_fields", {}))
    for key, section in schema.items():
        if section.get("virtual"):
            continue
        new, cur = merged.get(key), current.get(key)
        if section.get("is_array"):
            strip_items(new, cur, section.get("fields", {}))
        for sub_key, sub in (section.get("sub_arrays") or {}).items():
            if isinstance(new, dict):
                strip_items(new.get(sub_key), cur.get(sub_key) if isinstance(cur, dict) else None,
                            sub.get("fields", {}))


def prepare_layer(scope: str, values: dict, resets=()) -> tuple[dict, dict]:
    """Build the sole save candidate before route-specific validation."""
    schema = config_scope.schema_for(scope)
    if not isinstance(values, dict):
        raise LayerSaveError("body must be a JSON object")
    def check_objects(data, prefix=""):
        for key, value in data.items():
            path = f"{prefix}.{key}" if prefix else key
            if config_scope.scope_of(path) == config_scope.MIXED and not isinstance(value, dict):
                raise LayerSaveError(f"{path} must be an object")
            if isinstance(value, dict):
                check_objects(value, path)

    check_objects(values)
    resets = check_resets(scope, resets)
    inst, world, unknown = config_scope.split_by_scope(values)
    own, other = (inst, world) if scope == config_scope.INSTANCE else (world, inst)
    if other or unknown:
        rejected = dict(other)
        rejected.update({key: values[key] for key in unknown})
        count = len(config._split_keys(rejected))
        raise LayerSaveError(f"{count} path(s) belong to the {_other(scope)} settings: "
                             + config._key_list(rejected, limit=5))
    current = layer_part(scope)
    merged = merge_sensitive(own, current)
    _preserve_unsent_subarray_fields(merged, current, schema)
    if scope == config_scope.INSTANCE:
        _preserve_unsent_image_routing(merged, current)
    strip_materialized_item_defaults(merged, current, schema)
    apply_resets(merged, resets)
    if "extension_motion" in merged:
        from app.core.extension_rig import validate_motion_overrides
        try:
            validate_motion_overrides(merged["extension_motion"])
        except ValueError as e:
            raise LayerSaveError(str(e)) from e
    duplicates = duplicate_names(merged)
    if duplicates:
        raise LayerSaveError("; ".join(duplicates))
    return merged, current


def commit_layer(scope: str, merged: dict, current: dict) -> dict:
    """Persist exactly the prepared candidate and reload affected services."""
    changed = diff_sections(current, merged)
    try:
        config.save_part(scope, merged)
    except ValueError as e:
        raise LayerSaveError(str(e)) from e
    return {"changed_sections": changed,
            "reloaded": apply_section_reloads(changed, scope), "warnings": []}


def save_layer(scope: str, body: dict, resets=()) -> dict:
    """Prepare and commit one scope; instance routes validate between these steps."""
    merged, current = prepare_layer(scope, body, resets)
    return commit_layer(scope, merged, current)
