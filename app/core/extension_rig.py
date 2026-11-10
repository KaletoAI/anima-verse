"""Resolve package-declared extension groups and mesh-operation identity."""
from dataclasses import asdict
import hashlib
import json


def _revision(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True).encode()).hexdigest()


def rig_groups_for(character_name, profile=None, mesh_variant=None):
    """Applicable groups, with package physics defaults and ordered chains.

    Effective motion layers are resolved separately by motion_payload.
    Conditions use profile fields or ``attributes.<key>`` for this slot.
    A slot's procedural part (``mesh_part``) counts only where the mesh was
    rendered for it: ``mesh_variant`` is the token a stored model recorded
    (``model_refs.mesh_variant``); without it the worn outfit decides, the
    same rule that token follows. Where the part does not count, the slot's
    switch reads "off" for every condition, so no part op or part-only group
    is built over clothing or over anatomy the generator drew itself.
    """
    from app.core.body_slots import (is_slot_exposed, mesh_part_active, mesh_variant_token,
                                     normalize_condition_value, slots_for_character)
    if profile is None:
        from app.models.character import get_character_profile
        profile = get_character_profile(character_name) or {}
    from app.plugins.registry import packages
    from app.models.character_template import fragment_applies, template_features
    template_name = (profile.get("template") or "").strip()
    # The selectors below read only the template's ``features`` — no deep
    # copy of the whole template per character and poll.
    template = ({"features": template_features(template_name) or {}}
                if template_name else {})
    active_slots = {id(slot) for slot in slots_for_character(character_name, profile=profile)}
    groups = []
    for slot in (slot for package in packages() for slot in package.body_slots):
        values = (profile.get("body_slots") or {}).get(slot.id) or {}
        part_on = False
        if slot.mesh_part:
            part_on = (mesh_variant_token(slot) in mesh_variant if mesh_variant is not None
                       else mesh_part_active(slot, profile) and is_slot_exposed(slot, profile))
            if not part_on:
                values = {**values, slot.mesh_part.switch: "off"}
        for rig in slot.rigs:
            if rig.templates is None:
                if id(slot) not in active_slots:
                    continue
            elif not template_name or not fragment_applies({"apply_to": rig.templates}, template_name, template):
                continue
            matches = True
            for key, allowed in rig.applies_to.items():
                value = (values.get(key[len("attributes."):]) if key.startswith("attributes.")
                         else values.get(key) if key in slot.attributes else profile.get(key))
                if normalize_condition_value(value) not in [
                        normalize_condition_value(v) for v in allowed]:
                    matches = False
                    break
            if matches:
                group = asdict(rig)
                # The clothing slots that hide this group (``exposed_only``).
                group["covered_by"] = list(slot.covered_by)
                if part_on and rig.id in slot.mesh_part.rigs:
                    part = slot.mesh_part.rigs[rig.id]
                    if rig.op == "appendage_chain":
                        group["op"] = "attached_part"
                    group["params"] = dict(part["params"])
                    for param, mapping in part["attribute_params"].items():
                        selected = values.get(mapping["attribute"])
                        if selected in mapping["values"]:
                            group["params"][param] = mapping["values"][selected]
                groups.append(group)
    ordered = []
    while groups:
        ready = sorted([g for g in groups if not g["depends_on"] or any(
            parent["id"] == g["depends_on"] for parent in ordered)], key=lambda g: g["id"])
        if not ready:
            break
        ordered.extend(ready)
        groups = [g for g in groups if g not in ready]
    return ordered


def exposed_only_slots():
    """Clothing slots that cover a body slot carrying an ``exposed_only`` rig
    in any loaded package, sorted — the pieces the item editor offers the
    ``exposed_detail`` switch for. Never names a group or a slot itself."""
    from app.plugins.registry import packages
    return sorted({cover for package in packages() for slot in package.body_slots
                   if any(rig.exposed_only for rig in slot.rigs) for cover in slot.covered_by})


def clothing_lift_slots():
    """``{clothing slot: default lift}`` over every loaded package rig that
    declares ``clothing_lift_default`` (the largest default when two rigs
    name the same slot) — the pieces the item editor offers
    ``outfit_piece.lift`` for, with the placeholder it shows."""
    from app.plugins.registry import packages
    result = {}
    for package in packages():
        for slot in package.body_slots:
            for rig in slot.rigs:
                for cover, value in rig.clothing_lift_default.items():
                    result[cover] = max(result.get(cover, 0.0), value)
    return dict(sorted(result.items()))


def motion_damping_slots():
    """Clothing slots that cover a body slot carrying a moving rig (one with
    chains) in any loaded package, sorted — where ``outfit_piece.motion_damping``
    has an effect. Never names a group or a slot itself."""
    from app.plugins.registry import packages
    return sorted({cover for package in packages() for slot in package.body_slots
                   if any(rig.chains for rig in slot.rigs) for cover in slot.covered_by})


def piece_covering_slots(occupied, outfit_piece):
    """Every clothing slot a worn piece covers: the slots it occupies (the
    outfit's ``pieces`` mapping and its own ``slots``) plus ``covers`` and
    ``partially_covers`` — a partial cover counts as covering here."""
    piece = outfit_piece or {}
    return (set(occupied) | set(piece.get("slots") or []) | set(piece.get("covers") or [])
            | set(piece.get("partially_covers") or []))


def hides_exposed_detail(groups, pieces, items):
    """Whether an outfit hides its ``exposed_only`` groups.

    ``groups``: the applicable declarations (``rig_groups_for``, each with
    ``covered_by``); ``pieces``: the outfit's ``{clothing slot: item id}``;
    ``items``: ``{item id: item}``. True when ANY worn piece covers a slot in
    the ``covered_by`` of an ``exposed_only`` group (``piece_covering_slots``)
    and does not set ``outfit_piece.exposed_detail``; False when nothing
    covers such a slot or every covering piece shows the detail through."""
    targets = {cover for group in groups if group.get("exposed_only")
               for cover in group.get("covered_by") or []}
    if not targets:
        return False
    for item_id in sorted(set((pieces or {}).values())):
        piece = ((items or {}).get(item_id) or {}).get("outfit_piece") or {}
        occupied = {slot for slot, worn in (pieces or {}).items() if worn == item_id}
        if piece_covering_slots(occupied, piece) & targets and piece.get("exposed_detail") is not True:
            return True
    return False


def extension_bone_names(character_name, profile=None):
    """Validation context: full names mapped to parent and group identity."""
    return {link["bone"]: {"parent": link["parent"], "group": group["id"]}
            for group in rig_groups_for(character_name, profile)
            for chain in group["chains"] for link in chain}


# Bump an operation when its builder changes geometry for the same declaration;
# defaults live in the Blender scripts, so only that part variant rebuilds.
PART_BUILDS = {"attached_part": 6, "inset_part": 3}
# The same for the other operations; pair_tip 1: a geometry apex (no colour
# marker) is a tip suggestion too, and the tip override moves it.
OP_BUILDS = {**PART_BUILDS, "pair_tip": 1}


def extension_rig_fingerprint(groups, overrides=None):
    """Versioned identity of applicable declarations and model overrides."""
    geometry = [{**{key: group[key] for key in ("id", "op", "chains", "params", "enabled", "flip") if key in group},
                 **({"build": OP_BUILDS[group["op"]]} if group.get("op") in OP_BUILDS else {})}
                for group in groups]
    return _revision({"version": 19, "groups": sorted(geometry, key=lambda g: g["id"]),
                      "overrides": overrides or {}})


def model_extension_overrides(profile, signature):
    """Mesh switches for one model; absent signatures use declaration defaults."""
    return ((profile.get("model3d_opts") or {}).get("extension_rig_models") or {}).get(signature) or {}


#: Shown wherever an outfit model's group is off because the base is.
BASE_OFF_REASON = "Switched off on the base body"


def _base_signature_of(signature, meta):
    """The base model an outfit model ``signature`` is built on, or None
    (no base pipeline outfit, or a base itself)."""
    meta = meta or {}
    base = meta.get("base_signature")
    if not base or meta.get("base") or base == signature:
        return None
    return base


def inherited_extension_switches(profile, signature, meta, declarations):
    """``{group_id: {"enabled": False, "reason": BASE_OFF_REASON}}`` for each
    ``pair_tip`` group of ``declarations`` the base model switched off, when
    ``signature`` is an outfit model on the base body (``meta``) — that
    switch is the outfit's whatever its own says. {} otherwise."""
    base = _base_signature_of(signature, meta)
    if not base:
        return {}
    tips = {group["id"] for group in declarations or () if group.get("op") == "pair_tip"}
    return {group_id: {"enabled": False, "reason": BASE_OFF_REASON}
            for group_id, values in model_extension_overrides(profile, base).items()
            if group_id in tips and isinstance(values, dict) and values.get("enabled") is False}


def effective_extension_overrides(profile, signature, meta, declarations):
    """``model_extension_overrides`` of ``signature``, plus — for an outfit
    model on the base body (``meta`` names a ``base_signature`` and is no base
    itself) — what it takes from the base model for its ``pair_tip`` groups
    (``declarations``: the groups the model carries): the base's ``tip``
    override of every group the outfit sets none for (its tips and colour
    discs are those of the body it was painted onto), and the base's
    ``enabled: False`` (``inherited_extension_switches``), which the
    outfit's own switch cannot turn back on — one source of truth, so a
    base switched off is off on every outfit, built before or after."""
    own = model_extension_overrides(profile, signature)
    base = _base_signature_of(signature, meta)
    if not base:
        return own
    merged = {group_id: dict(values) for group_id, values in own.items() if isinstance(values, dict)}
    for group_id, values in model_extension_overrides(profile, base).items():
        if isinstance(values, dict) and "tip" in values and "tip" not in merged.get(group_id, {}):
            merged.setdefault(group_id, {})["tip"] = values["tip"]
    for group_id in inherited_extension_switches(profile, signature, meta, declarations):
        merged.setdefault(group_id, {})["enabled"] = False
    return merged


# Millimetres: the tip offset range per direction and the colour disc's
# diameter range, its soft-edge range and defaults (Blender clamps the same).
TIP_OFFSET_MAX_MM = 30.0
DISC_DIAMETER_MM = (10.0, 50.0)
DISC_SOFT_MAX_MM = 10.0
DISC_DEFAULTS = {"enabled": False, "color": "#c07a72", "diameter_mm": 28.0, "soft_mm": 3.0}


def _finite_number(value, label):
    import math
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number")
    return float(value)


def validate_tip_override(value):
    """Clean one ``pair_tip`` group's ``tip`` override, or None for "none".

    ``{"offsets": [{"up", "out"}, {"up", "out"}], "mirror": bool, "disc":
    {"enabled", "color", "diameter_mm", "soft_mm"}}``, one offset per chain
    (the declaration's side order; ``out`` is away from the midline). Offsets
    are clamped to +-TIP_OFFSET_MAX_MM, the diameter to DISC_DIAMETER_MM, the
    soft edge to [0, DISC_SOFT_MAX_MM]; ``mirror`` makes the second side the
    first one's. Missing values take the defaults. A result equal to the
    defaults (no offset, no mirror, the default disc switched off) is None —
    "reset". ValueError for anything malformed."""
    import re
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) - {"offsets", "mirror", "disc"}:
        raise ValueError("tip override accepts offsets, mirror and disc only")
    mirror = value.get("mirror", False)
    if type(mirror) is not bool:
        raise ValueError("tip mirror must be a boolean")
    rows = value.get("offsets", [])
    if not isinstance(rows, list) or len(rows) > 2:
        raise ValueError("tip offsets must be a list of at most two sides")
    offsets = []
    for index in range(2):
        row = rows[index] if index < len(rows) else {}
        if not isinstance(row, dict) or set(row) - {"up", "out"}:
            raise ValueError("a tip offset accepts up and out only")
        offsets.append({key: round(max(-TIP_OFFSET_MAX_MM, min(TIP_OFFSET_MAX_MM, _finite_number(
            row.get(key, 0), f"tip offset {key}"))), 3) for key in ("up", "out")})
    if mirror:
        offsets[1] = dict(offsets[0])
    raw_disc = value.get("disc", {})
    if not isinstance(raw_disc, dict) or set(raw_disc) - set(DISC_DEFAULTS):
        raise ValueError("tip disc accepts enabled, color, diameter_mm and soft_mm only")
    disc = dict(DISC_DEFAULTS)
    if "enabled" in raw_disc:
        if type(raw_disc["enabled"]) is not bool:
            raise ValueError("tip disc enabled must be a boolean")
        disc["enabled"] = raw_disc["enabled"]
    if "color" in raw_disc:
        if not isinstance(raw_disc["color"], str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", raw_disc["color"]):
            raise ValueError("tip disc color must be #rrggbb")
        disc["color"] = raw_disc["color"].lower()
    if "diameter_mm" in raw_disc:
        disc["diameter_mm"] = round(max(DISC_DIAMETER_MM[0], min(DISC_DIAMETER_MM[1], _finite_number(
            raw_disc["diameter_mm"], "tip disc diameter_mm"))), 3)
    if "soft_mm" in raw_disc:
        disc["soft_mm"] = round(max(0.0, min(DISC_SOFT_MAX_MM, _finite_number(
            raw_disc["soft_mm"], "tip disc soft_mm"))), 3)
    cleaned = {"offsets": offsets, "mirror": mirror, "disc": disc}
    if not mirror and disc == DISC_DEFAULTS and all(v == 0 for row in offsets for v in row.values()):
        return None
    return cleaned


def migrate_extension_rig_models_once():
    """Copy retired character switches to stored full models, once by content.

    Runs before the legacy model-store import, so the signature that import
    will fill (the current outfit's) receives the switches as well. Pooled
    characters keep their models and may be revived, so they are included.
    """
    import copy
    from app.core.keyed_lock import keyed_lock
    from app.core.model3d import get_model3d_dir
    from app.core.model_refs import current_outfit_state, is_state_fork
    from app.models.character import (list_available_characters, get_character_dir,
                                      get_character_profile, save_character_profile)
    migrated = 0
    for name in list_available_characters(include_pooled=True):
        with keyed_lock("character_profile", name):
            profile = get_character_profile(name) or {}
            opts = dict(profile.get("model3d_opts") or {})
            if "extension_rig" not in opts:
                continue
            old = opts.pop("extension_rig")
            if old:
                models = dict(opts.get("extension_rig_models") or {})
                directory = get_model3d_dir(name)
                for suffix in ("*.glb", "*.fbx"):
                    for path in directory.glob(suffix):
                        if path.is_file() and not is_state_fork(path.stem):
                            models[path.stem] = copy.deepcopy(old)
                if any((get_character_dir(name) / "model").glob("model.*")):
                    models[current_outfit_state(name)[2]] = copy.deepcopy(old)
                opts["extension_rig_models"] = models
            profile["model3d_opts"] = opts
            if not save_character_profile(name, profile):
                raise RuntimeError("Character profile could not be saved during extension rig migration")
            migrated += 1
    return migrated


def resolved_extension_groups(character_name, profile=None, signature=None, mesh_variant=None,
                              overrides=None):
    """Return applicable groups with enabled/flip flags, including disabled ones.

    Overrides live per signature in the model options block. They affect mesh
    operations only; package applicability and motion defaults stay independent.
    ``mesh_variant`` is the stored model's token (see ``rig_groups_for``).
    ``overrides`` replaces the signature's own (``effective_extension_overrides``).
    A ``pair_tip`` group carries its ``tip`` override as ``tip_override``.
    """
    if profile is None:
        from app.models.character import get_character_profile
        profile = get_character_profile(character_name) or {}
    if overrides is None:
        overrides = model_extension_overrides(profile, signature)
    result = []
    for group in rig_groups_for(character_name, profile, mesh_variant):
        override = overrides.get(group["id"]) or {}
        result.append({**group, "enabled": override.get("enabled", True) and all(
            parent["enabled"] for parent in result if parent["id"] == group["depends_on"]),
                       "flip": override.get("flip", False),
                       **({"tip_override": override.get("tip")} if group["op"] == "pair_tip" else {})})
    return result


# sag_max_deg bounds the whole chain static droop for each root chain.
MOTION_FIELDS = ("length", "girth", "freq_hz", "zeta", "gravity", "spill", "flatten", "stretch", "spread", "flatten_floor", "translate", "gain", "max_deg", "sag_max_deg", "spill_max_deg", "head_sag", "squash", "axis_gain", "rest_max_deg", "straighten_deg", "freetext_clothing_gain")


def control_allowed(group, field):
    """Resolve state aliases against the optional control declaration."""
    control = {"freq": "freq_hz", "rest_deg": "rest_max_deg"}.get(field, field)
    return group.get("controls") is None or control in group["controls"]


def declared_motion_groups():
    """All loaded declarations, including character-inapplicable groups."""
    from app.plugins import registry
    return sorted([{"id": rig.id, "controls": rig.controls,
                    "defaults": {key: (rig.squash[0] if key == "flatten_floor" and rig.flatten_floor is None else getattr(rig, key)) for key in MOTION_FIELDS}}
                   for package in registry.packages() for slot in package.body_slots
                   for rig in slot.rigs if rig.chains], key=lambda group: group["id"])


def validate_motion_overrides(section, *, character=False):
    """Validate partial physics overrides; sliders are character-only."""
    import math
    from app.plugins.registry import RigSpec
    if not isinstance(section, dict) or set(section) - {"groups"}:
        raise ValueError("extension_motion requires a groups object")
    groups = section.get("groups", {})
    if not isinstance(groups, dict):
        raise ValueError("extension_motion.groups must be an object")
    declarations = {group["id"]: group for group in declared_motion_groups()}
    for group_id, values in groups.items():
        if not isinstance(group_id, str) or not group_id or not isinstance(values, dict):
            raise ValueError("motion group overrides must be objects with non-empty ids")
        allowed = set(MOTION_FIELDS) | ({"bounce", "weight"} if character else set())
        if set(values) - allowed:
            raise ValueError("unknown motion physics field")
        for key in values:
            if not control_allowed(declarations.get(group_id, {}), key):
                raise ValueError(f"extension_motion.{group_id}.{key} is not allowed")
        for key in ("bounce", "weight"):
            if key in values:
                value = values[key]
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not .5 <= value <= 1.5:
                    raise ValueError(f"{key} outside allowed range")
        RigSpec.parse({"id": group_id, "op": "validation",
                       "chains": [[{"bone": "ValidationBone", "parent": "Hips"}]], **values})


def motion_payload(character_name, profile=None, *, apply_clothing=True, apply_states=True, preview_states=None):
    """Package → world → attribute multipliers → raw character → bounce/weight → clothing → state; mesh-independent.

    Clothing: the product of the covering pieces' ``motion_damping`` (or the
    free-text gain) scales gain, max_deg, translate and spill and makes
    freq_hz/zeta stiffer by 1/sqrt(factor); the strongest covering piece's
    ``lift`` (absent = the group's ``clothing_lift_default`` for that slot,
    half for a partial cover) scales gravity and sag_max_deg by (1 - lift) and
    adds lift * rest_max_deg to the rest angle before its clamp."""
    import math
    from app.core import config
    from app.core.body_slots import slots_for_character
    from app.core.motion_item_cache import item_snapshot
    if profile is None:
        from app.models.character import get_character_profile
        profile = get_character_profile(character_name) or {}
    declarations = rig_groups_for(character_name, profile)
    if not declarations:
        return {"rev": _revision({"declarations": []}), "groups": {}}
    world = config.get("extension_motion.groups", {}) or {}
    scale = profile.get("motion_gravity_scale", 1)
    try:
        scale = float(scale)
        if not math.isfinite(scale):
            scale = 1.0
        scale = max(0.0, min(3.0, scale))
    except (TypeError, ValueError):
        scale = 1.0
    equipment = (profile.get("equipped_pieces") or {}) if apply_clothing else {}
    pieces = {}
    items = item_snapshot() if equipment else {}
    for iid in sorted(set(equipment.values())):
        item = items.get(iid)
        if item and item.get("outfit_piece"):
            op = item["outfit_piece"]
            pieces[iid] = {key: op.get(key, 1 if key == "motion_damping" else [])
                           for key in ("motion_damping", "covers", "partially_covers")}
            # Absent = the group's ``clothing_lift_default`` for the slot.
            pieces[iid]["lift"] = op.get("lift")
            pieces[iid]["occupied_slots"] = sorted(slot for slot, worn in equipment.items() if worn == iid)
    slots = slots_for_character(character_name, profile=profile)
    attributes = {rig.id: ((profile.get("body_slots") or {}).get(slot.id) or {})
                  for slot in slots for rig in slot.rigs}
    coverage = {rig.id: list(slot.covered_by) for slot in
                slots for rig in slot.rigs}
    from app.core.prompt_filters import BONE_POSE_FIELDS, collect_bone_poses, valid_bone_pose_number
    if preview_states is not None:
        from app.core.prompt_filters import load_filters
        selected = set(preview_states)
        states = sorted([{"id": row["id"], "bone_pose": row.get("bone_pose") or {}}
                         for row in load_filters() if row["id"] in selected],
                        key=lambda row: row["id"])
    else:
        states = collect_bone_poses(character_name, profile.get("current_location", ""), profile=profile) if apply_states else []
    groups = {}
    for group in declarations:
        if not group["chains"]:
            continue
        values = {key: group[key] for key in MOTION_FIELDS}
        values.update({key: value for key, value in world.get(group["id"], {}).items()
                       if key in MOTION_FIELDS and control_allowed(group, key)})
        inherited_floor = values["flatten_floor"] is None
        if inherited_floor:
            values["flatten_floor"] = values["squash"][0]
        floor_multiplier = 1.0
        for key, choices in group.get("attribute_profiles", {}).items():
            selected = attributes.get(group["id"], {}).get(key)
            if selected is None:
                continue
            for field, multiplier in choices.get(str(selected), {}).items():
                values[field] *= multiplier
                if field == "flatten_floor":
                    floor_multiplier *= multiplier
        # Multipliers may exceed absolute limits; enforce the physics contract.
        for key in ("gain", "flatten", "stretch", "spread", "flatten_floor", "spill", "translate", "head_sag"):
            values[key] = min(1.0, values[key])
        for key in ("max_deg", "sag_max_deg", "spill_max_deg"):
            values[key] = min(180.0, values[key])
        overrides = ((profile.get("model3d_opts") or {}).get("extension_motion") or {}).get(group["id"], {})
        overrides = {key: value for key, value in overrides.items() if control_allowed(group, key)}
        values.update({key: value for key, value in overrides.items() if key in MOTION_FIELDS})
        if inherited_floor and "flatten_floor" not in overrides:
            values["flatten_floor"] = min(1.0, values["squash"][0] * floor_multiplier)
        bounce, weight = overrides.get("bounce", 1), overrides.get("weight", 1)
        for key in ("gain", "max_deg"):
            values[key] *= bounce
        for key in ("freq_hz", "zeta"):
            values[key] *= bounce ** -.5
        for key in ("gravity", "sag_max_deg", "spill_max_deg", "flatten", "stretch", "translate"):
            values[key] *= weight
        for key in ("gain", "flatten", "stretch", "translate"):
            values[key] = min(1.0, values[key])
        for key in ("max_deg", "sag_max_deg", "spill_max_deg"):
            values[key] = min(180.0, values[key])
        free_text = any(isinstance(profile.get(key), str) and profile[key].strip()
                        for key in ("outfit_description", "outfit_worn"))
        factor = values["freetext_clothing_gain"] if apply_clothing and not pieces and free_text else 1.0
        targets = set(coverage.get(group["id"], []))
        lift_defaults = group.get("clothing_lift_default") or {}
        lift = 0.0
        for piece in pieces.values():
            f = piece["motion_damping"]
            full = targets.intersection(set(piece["covers"]) | set(piece["occupied_slots"]))
            partial = targets.intersection(piece["partially_covers"])
            if full:
                factor *= f
            elif partial:
                factor *= 1 - (1 - f) / 2
            # Lift: only the slots the group declares a default for lift it;
            # a piece's own value replaces that default, a partial cover
            # counts half, and the strongest piece wins.
            hit, half = full & set(lift_defaults), False
            if not hit:
                hit, half = partial & set(lift_defaults), True
            if hit:
                own = piece["lift"]
                value = own if own is not None else max(lift_defaults[slot] for slot in hit)
                lift = max(lift, value / 2 if half else value)
        # The clothing factor holds the whole motion like ``bounce`` does:
        # amplitude, swing limit, follow-through and outward spill shrink,
        # the spring gets stiffer and better damped by 1/sqrt(factor).
        for key in ("gain", "max_deg", "translate", "spill"):
            values[key] *= factor
        if factor < 1:
            # Zero stops the motion anyway; the floor keeps 0 * inf out.
            for key in ("freq_hz", "zeta"):
                values[key] *= max(factor, 1e-4) ** -.5
        # Lift carries the group: less static sag and a raised rest angle.
        for key in ("gravity", "sag_max_deg"):
            values[key] *= 1 - lift
        rest = None
        for state in states:
            pose = state["bone_pose"].get(group["id"], {})
            if not isinstance(pose, dict):
                continue
            for field, multiplier in pose.items():
                if field not in BONE_POSE_FIELDS or not control_allowed(group, field):
                    continue
                if not valid_bone_pose_number(multiplier, signed=field == "rest_deg"):
                    continue
                if field in ("length", "girth") and not .5 <= multiplier <= 2:
                    continue
                if field == "rest_deg":
                    rest = max(rest if rest is not None else multiplier, multiplier)
                else:
                    target = "freq_hz" if field == "freq" else field
                    values[target] = 0 if multiplier == 0 else values[target] * multiplier
        # Clamp EFFECTIVE values after all layers; finite factors may overflow.
        for field, upper in {"freq_hz": 20, "zeta": 10, "gravity": 10,
                             "gain": 1, "flatten": 1, "stretch": 1, "spread": 1, "flatten_floor": 1, "spill": 1, "translate": 1, "head_sag": 1}.items():
            values[field] = max(0.0, min(float(upper), values[field]))
        for field in ("length", "girth"):
            values[field] = max(.25, min(4., values[field]))
        values["gravity_scale"] = scale
        groups[group["id"]] = {
            "bones": [link["bone"] for chain in group["chains"] for link in chain],
            **values, "scale_axis": group["scale_axis"], "rigid_tail": group["rigid_tail"],
            "rest_deg": max(-values["rest_max_deg"], min((rest or 0) + lift * values["rest_max_deg"], values["rest_max_deg"])),
        }
    inputs = {"declarations": declarations, "world": world, "equipment": equipment,
              "pieces": pieces, "coverage": coverage, "attributes": attributes,
              "character": (profile.get("model3d_opts") or {}).get("extension_motion") or {},
              "gravity_scale": scale, "states": states, "groups": groups}
    return {"rev": _revision(inputs), "groups": groups}


def extension_metadata(character_name, profile=None, signature=None):
    """Reserved sidecar state; P0 never claims an application succeeded."""
    if profile is None:
        from app.models.character import get_character_profile
        profile = get_character_profile(character_name) or {}
    groups = rig_groups_for(character_name, profile)
    overrides = model_extension_overrides(profile, signature)
    return {"fingerprint": extension_rig_fingerprint(groups, overrides),
            "groups": [g["id"] for g in groups],
            "group_ops": {g["id"]: g["op"] for g in groups},
            "group_params": {g["id"]: g["params"] for g in groups if g["op"] in PART_BUILDS},
            "attempted": False,
            "status": "not_found" if groups else "none_applicable",
            "reason": "No extension operation has run" if groups else "",
            "metrics": {}, "per_tier": {}}
