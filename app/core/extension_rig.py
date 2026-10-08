"""Resolve package-declared extension groups and mesh-operation identity."""
from dataclasses import asdict
import hashlib
import json


def _revision(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True).encode()).hexdigest()


def rig_groups_for(character_name, profile=None):
    """Applicable groups, with package physics defaults and ordered chains.

    Future world, equipment, character and state layers belong after this
    package-default resolution. P0 does not read those layers.
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


def motion_payload(character_name, profile=None):
    """Stable revision of the resolved motion content, independent of mesh."""
    groups = {}
    for group in rig_groups_for(character_name, profile):
        groups[group["id"]] = {
            "bones": [link["bone"] for chain in group["chains"] for link in chain],
            **{key: group[key] for key in ("freq_hz", "zeta", "gravity", "gain",
                                          "max_deg", "squash", "rest_max_deg")},
            "rest_deg": 0,
        }
    return {"rev": _revision(groups), "groups": groups}


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
