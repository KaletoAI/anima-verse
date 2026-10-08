"""Resolve package-declared extension groups; no motion simulation in P0."""
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
    groups = rig_groups_for(character_name, profile)
    return {"fingerprint": _revision(groups), "groups": [g["id"] for g in groups],
            "status": "not_found" if groups else "none_applicable",
            "reason": "No extension operation has run" if groups else "",
            "per_tier": {}}
