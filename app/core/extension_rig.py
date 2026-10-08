"""Resolve package-declared extension groups and mesh-operation identity."""
from dataclasses import asdict
import hashlib
import json


def _revision(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True).encode()).hexdigest()


def rig_groups_for(character_name, profile=None):
    """Applicable groups, with package physics defaults and ordered chains.

    Effective motion layers are resolved separately by motion_payload.
    Conditions use profile fields or ``attributes.<key>`` for this slot.
    """
    from app.core.body_slots import normalize_condition_value, slots_for_character
    if profile is None:
        from app.models.character import get_character_profile
        profile = get_character_profile(character_name) or {}
    groups = []
    for slot in slots_for_character(character_name, profile=profile):
        rig = slot.rig
        if rig is None:
            continue
        values = (profile.get("body_slots") or {}).get(slot.id) or {}
        matches = True
        for key, allowed in rig.applies_to.items():
            value = (values.get(key[len("attributes."):]) if key.startswith("attributes.")
                     else values.get(key) if key in slot.attributes else profile.get(key))
            if normalize_condition_value(value) not in [
                    normalize_condition_value(v) for v in allowed]:
                matches = False
                break
        if matches:
            groups.append(asdict(rig))
    return sorted(groups, key=lambda group: group["id"])


def extension_bone_names(character_name, profile=None):
    """Validation context: full names mapped to parent and group identity."""
    return {link["bone"]: {"parent": link["parent"], "group": group["id"]}
            for group in rig_groups_for(character_name, profile)
            for chain in group["chains"] for link in chain}


def extension_rig_fingerprint(groups, overrides=None):
    """Versioned identity of applicable declarations and character overrides."""
    return _revision({"version": 2, "groups": sorted(groups, key=lambda g: g["id"]),
                      "overrides": overrides or {}})


def resolved_extension_groups(character_name, profile=None):
    """Return applicable groups with enabled/flip flags, including disabled ones.

    Overrides live in the existing model options block. They affect mesh
    operations only; package applicability and motion defaults stay independent.
    """
    if profile is None:
        from app.models.character import get_character_profile
        profile = get_character_profile(character_name) or {}
    overrides = (profile.get("model3d_opts") or {}).get("extension_rig") or {}
    result = []
    for group in rig_groups_for(character_name, profile):
        override = overrides.get(group["id"]) or {}
        result.append({**group, "enabled": override.get("enabled", True),
                       "flip": override.get("flip", False)})
    return result


MOTION_FIELDS = ("freq_hz", "zeta", "gravity", "gain", "max_deg", "squash", "rest_max_deg")


def declared_motion_groups():
    """All loaded declarations, including character-inapplicable groups."""
    from app.plugins import registry
    return sorted([{"id": slot.rig.id,
                    "defaults": {key: getattr(slot.rig, key) for key in MOTION_FIELDS}}
                   for package in registry.packages() for slot in package.body_slots
                   if slot.rig is not None], key=lambda group: group["id"])


def validate_motion_overrides(section):
    """Validate partial world overrides against the P0 physics contract."""
    from app.plugins.registry import RigSpec
    if not isinstance(section, dict) or set(section) - {"groups"}:
        raise ValueError("extension_motion requires a groups object")
    groups = section.get("groups", {})
    if not isinstance(groups, dict):
        raise ValueError("extension_motion.groups must be an object")
    for group_id, values in groups.items():
        if not isinstance(group_id, str) or not group_id or not isinstance(values, dict):
            raise ValueError("motion group overrides must be objects with non-empty ids")
        if set(values) - set(MOTION_FIELDS):
            raise ValueError("unknown motion physics field")
        RigSpec.parse({"id": group_id, "op": "validation",
                       "chains": [[{"bone": "ValidationBone", "parent": "Hips"}]], **values})


def motion_payload(character_name, profile=None):
    """Package → world → worn-piece gain and character gravity; mesh-independent."""
    import math
    from app.core import config
    from app.core.body_slots import slots_for_character
    from app.models.inventory import get_item
    if profile is None:
        from app.models.character import get_character_profile
        profile = get_character_profile(character_name) or {}
    declarations = rig_groups_for(character_name, profile)
    world = config.get("extension_motion.groups", {}) or {}
    scale = profile.get("motion_gravity_scale", 1)
    try:
        scale = float(scale)
        if not math.isfinite(scale):
            scale = 1.0
        scale = max(0.0, min(3.0, scale))
    except (TypeError, ValueError):
        scale = 1.0
    equipment = profile.get("equipped_pieces") or {}
    pieces = {}
    for iid in sorted(set(equipment.values())):
        item = get_item(iid)
        if item and item.get("outfit_piece"):
            op = item["outfit_piece"]
            pieces[iid] = {key: op.get(key, 1 if key == "motion_damping" else [])
                           for key in ("motion_damping", "covers", "partially_covers")}
    coverage = {slot.rig.id: list(slot.covered_by) for slot in
                slots_for_character(character_name, profile=profile) if slot.rig is not None}
    groups = {}
    for group in declarations:
        values = {key: group[key] for key in MOTION_FIELDS}
        values.update(world.get(group["id"], {}))
        factor = 1.0
        targets = set(coverage.get(group["id"], []))
        for piece in pieces.values():
            f = piece["motion_damping"]
            if targets.intersection(piece["covers"]):
                factor *= f
            elif targets.intersection(piece["partially_covers"]):
                factor *= 1 - (1 - f) / 2
        values["gain"] *= factor
        values["gravity"] *= scale
        groups[group["id"]] = {
            "bones": [link["bone"] for chain in group["chains"] for link in chain],
            **values, "rest_deg": 0,
        }
    inputs = {"declarations": declarations, "world": world, "equipment": equipment,
              "pieces": pieces, "coverage": coverage, "gravity_scale": scale, "groups": groups}
    return {"rev": _revision(inputs), "groups": groups}


def extension_metadata(character_name, profile=None):
    """Reserved sidecar state; P0 never claims an application succeeded."""
    if profile is None:
        from app.models.character import get_character_profile
        profile = get_character_profile(character_name) or {}
    groups = rig_groups_for(character_name, profile)
    overrides = (profile.get("model3d_opts") or {}).get("extension_rig") or {}
    return {"fingerprint": extension_rig_fingerprint(groups, overrides),
            "groups": [g["id"] for g in groups], "attempted": False,
            "status": "not_found" if groups else "none_applicable",
            "reason": "No extension operation has run" if groups else "",
            "metrics": {}, "per_tier": {}}
