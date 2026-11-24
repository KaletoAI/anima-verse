"""Contact clips and the clothes in the way (owner decisions 2026-11-25).

A pair or group clip declares CONTACT RELATIONS (``animation_clips.clip_contact_target``: the clip's own
``contact_relations``, else a package default for its kind; each ``{part: role, at: role, target}``). Before
such a clip is offered or started, the people who fill its roles must have the clothes off that would be in the
way:

* R1 — the ``part`` role of a relation needs its attached part free;
* R2 — the ``at`` role of a relation whose target is ``channel`` needs its channel free; a ``mouth`` or
  hand target needs nothing from the receiving role;
* R3 — a piece declared ``outfit_piece.open_below`` (a skirt, a dress, a kilt) never blocks; any other piece
  that sits on, or ``covers``, a required clothing slot does, unless it is worn open (``covering_pieces``).

WHICH clothing slots a part or a channel needs free is DECLARED by the anatomy package, never named here: a rig
group or a ``channel`` region of a body slot lists them under ``contact_free`` (docs/plugins.md). A body
without such a declaration (no part, no channel) has no requirement. The requirement follows the anatomy, not
the built mesh: a slot's ``mesh_part`` switch is read as "on" here, so a body whose procedural part is not
built yet still has its declared channel.

DEFAULT — a clip WITHOUT effective relations (none authored, no package default for its kind) is checked by its
participants' own anatomy when a package declares it a contact clip (capability :data:`DEFAULT_CAPABILITY`, asked
with the pose key and the clip kind): whoever carries an attached part needs the part free, whoever has no part but a
channel needs the channel free (:func:`default_needs`) — the renderer's own auto-detection without relations. A
little strict for a third person in a group who only watches or uses hands or mouth; an authored relation is exact
and wins. Without such a package nothing is gated (the deletion test).

R4 — a rule that is not met BLOCKS the clip with a reason naming who still wears what; nothing is taken off
automatically. A character dressed by free text (no outfit system) has no pieces and keeps the start-time
undress of the package that owns the moment, so it never blocks here.

:func:`refusal` is the ONE gate every place that offers or starts a contact clip calls (free pair: invitation,
acceptance, start, switch in place; furniture runs before they are active; finale; alt halves). A running clip
is never interrupted by a piece put back on — the next switch is gated. Reads the profiles as they are (the
caller passes the ones it already holds); takes no lock.
"""
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from app.core.log import get_logger

logger = get_logger("contact_clothing")

#: The refusal code every gated surface reports (``participation``-style: code + message).
REASON = "clothing"
#: What a role needs free: its attached part (R1) or its channel (R2).
PART = "part"
CHANNEL = "channel"
#: The LLM-facing reason text (names who wears what and how to take it off).
TEMPLATE = "chat/contact_clothing.md"
#: Provider capability (``hooks.register_provider(..., multiple=True)``): a package that knows which poses are contact
#: moments answers ``fn(pose_key="", kind="") -> bool`` — True = a clip WITHOUT effective contact relations is checked
#: by the per-anatomy default (:func:`default_needs`). No contributor = no default (nothing is gated without relations).
DEFAULT_CAPABILITY = "contact.default_requirement"


def _profile_of(name: str, profiles: Optional[Dict[str, Dict[str, Any]]]) -> Dict[str, Any]:
    if profiles is not None and name in profiles and profiles[name] is not None:
        return profiles[name]
    from app.models.character import get_character_profile
    return get_character_profile(name) or {}


def contact_free_slots(name: str, profile: Dict[str, Any], need: str) -> Set[str]:
    """The clothing slots ``name``'s body needs free for ``need`` (:data:`PART` / :data:`CHANNEL`): the
    ``contact_free`` of every applicable rig group (part) or ``channel`` region (channel) of the loaded
    packages, by the rig rules (``extension_rig._rule_applies``) with the slot's mesh-part switch read "on"."""
    from app.core.extension_rig import _applicability_context, _rule_applies
    from app.plugins.registry import packages
    template_name, template, active_slots = _applicability_context(name, profile)
    out: Set[str] = set()
    for package in packages():
        for slot in package.body_slots:
            declared = ([rig for rig in slot.rigs if rig.contact_free] if need == PART else
                        [region for region in slot.regions if region.kind == "channel" and region.contact_free])
            if not declared:
                continue
            values = dict((profile.get("body_slots") or {}).get(slot.id) or {})
            if slot.mesh_part:
                values[slot.mesh_part.switch] = "on"
            for rule in declared:
                if _rule_applies(slot, rule, values, profile, template_name, template, active_slots):
                    out.update(rule.contact_free)
    return out


def declared_slots() -> List[str]:
    """Every clothing slot any loaded package names under ``contact_free``, sorted — the pieces the item editor
    offers the ``open_below`` switch for."""
    from app.plugins.registry import packages
    out: Set[str] = set()
    for package in packages():
        for slot in package.body_slots:
            for rule in list(slot.rigs) + list(slot.regions):
                out.update(rule.contact_free)
    return sorted(out)


def piece_blockers(profile: Dict[str, Any], slots: Iterable[str]) -> List[Dict[str, Any]]:
    """The worn pieces of ``profile`` that keep ``slots`` from being free: ``[{item_id, item, slots}]`` in
    worn order, each piece once. A piece worn open covers nothing (``outfit_renderer.covering_pieces``); a piece
    declared ``outfit_piece.open_below`` never blocks; ``partially_covers`` does not count. A free-text
    wardrobe has no pieces: ``[]``."""
    wanted = {str(s).strip().lower() for s in slots if str(s).strip()}
    if not wanted:
        return []
    from app.core.outfit_renderer import covering_pieces, is_free_text_wardrobe
    if is_free_text_wardrobe(profile):
        return []
    from app.models.inventory import get_item
    out: Dict[str, Dict[str, Any]] = {}
    for worn_slot, iid in covering_pieces(profile).items():
        item = get_item(iid) or {}
        piece = item.get("outfit_piece") or {}
        if piece.get("open_below") is True:
            continue
        touched = {str(worn_slot).strip().lower()} | {str(c).strip().lower() for c in piece.get("covers") or []}
        hit = sorted(touched & wanted)
        if not hit:
            continue
        entry = out.setdefault(iid, {"item_id": iid, "item": item, "slots": []})
        entry["slots"] = sorted(set(entry["slots"]) | set(hit))
    return list(out.values())


def default_applies(pose_key: str = "", kind: str = "") -> bool:
    """Whether a package declares the clip (by its pose key, else its kind) a contact clip whose missing
    relations are filled by the per-anatomy default (:data:`DEFAULT_CAPABILITY`). A raising contributor counts as
    "no" and is logged."""
    from app.core import hooks
    for fn in hooks.get_providers(DEFAULT_CAPABILITY):
        try:
            if fn(pose_key=(pose_key or "").strip().lower(), kind=kind or "") is True:
                return True
        except Exception as e:  # noqa: BLE001 — a broken package must not break an offer or a start
            logger.warning("contact default provider failed: %s", e)
    return False


def default_needs(name: str, profile: Dict[str, Any]) -> Set[str]:
    """The DEFAULT requirement of one participant of a contact clip without relations, by its OWN anatomy (what the
    renderer's auto-detection does without relations: the part enters the channel that accepts it): a body with an
    attached part (some rig group with ``contact_free`` applies) needs the part free; a body without a part but with
    a declared channel needs the channel free; a body with neither needs nothing. Strict on purpose for a person who
    only watches or uses hands or mouth in a group clip — an authored relation on the clip is exact."""
    if contact_free_slots(name, profile, PART):
        return {PART}
    if contact_free_slots(name, profile, CHANNEL):
        return {CHANNEL}
    return set()


def role_needs(relations: Sequence[Dict[str, str]]) -> Dict[str, Set[str]]:
    """``{role: {part, channel}}`` the contact relations ask for: every ``part`` role its part (R1), the ``at``
    role of a ``channel`` target its channel (R2); mouth and hand targets ask nothing of the receiving role."""
    needs: Dict[str, Set[str]] = {}
    for rel in relations or ():
        needs.setdefault(rel["part"], set()).add(PART)
        if rel.get("target") == "channel":
            needs.setdefault(rel["at"], set()).add(CHANNEL)
    return needs


def blockers(kind: str, roles: Dict[str, str], *,
             profiles: Optional[Dict[str, Dict[str, Any]]] = None, pose_key: str = "") -> List[Dict[str, Any]]:
    """What keeps the clip ``kind`` with ``roles`` (``{clip role: character}``) from being played:
    ``[{character, role, need, item_id, item_name, item, slots}]`` — empty when nothing is in the way or a role is
    unfilled. The clip's effective contact relations decide (:func:`role_needs`); a clip without any is checked by
    the per-anatomy default (:func:`default_needs`) when a package declares it a contact clip (:func:`default_applies`,
    asked with ``pose_key`` and ``kind``), else it needs nothing."""
    from app.core.animation_clips import clip_contact_target, clip_meta
    if not kind or not roles:
        return []
    meta = clip_meta(kind) or {}
    relations = clip_contact_target(meta, kind).get("relations") or []
    if relations:
        per_role = [(role, needs, _profile_of(roles[role], profiles))
                    for role, needs in role_needs(relations).items() if roles.get(role)]
    elif default_applies(pose_key, kind):
        per_role = []
        for role, name in roles.items():
            if not name:
                continue
            profile = _profile_of(name, profiles)
            per_role.append((role, default_needs(name, profile), profile))
    else:
        return []
    out: List[Dict[str, Any]] = []
    for role, needs, profile in per_role:
        name = roles[role]
        for need in sorted(needs, key=lambda n: (n != PART, n)):
            for hit in piece_blockers(profile, contact_free_slots(name, profile, need)):
                if any(b["character"] == name and b["item_id"] == hit["item_id"] for b in out):
                    continue
                out.append({"character": name, "role": role, "need": need, "item_id": hit["item_id"],
                            "item_name": str(hit["item"].get("name") or hit["item_id"]),
                            "item": hit["item"], "slots": hit["slots"]})
    return out


def roles_for(kind: str, names: Sequence[str], *,
              profiles: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, str]:
    """``{clip role: character}`` for ``names`` (the initiator first), by the engine's own role assignment
    (``interaction_engine.group_roles``; a pair by ``assign_roles``). ``{}`` when they do not fit the clip."""
    from app.core.animation_clips import clip_meta
    from app.core.interaction_engine import group_roles
    names = [n for n in names if n]
    if not kind or len(names) < 2:
        return {}
    try:
        return group_roles(names, {n: _profile_of(n, profiles) for n in names}, clip_meta(kind) or {})
    except ValueError:
        return {}


def refusal(pose_key: str = "", names: Sequence[str] = (), *, kind: str = "",
            roles: Optional[Dict[str, str]] = None,
            profiles: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
    """THE gate: ``{}`` when the contact clip may be offered/started, else
    ``{"reason": REASON, "message": <English text for the LLM>, "blockers": [...]}``.

    The clip is ``kind``, else the pair/group clip ``pose_key`` names (``interaction_engine.pair_kind_for_pose``);
    the roles are ``roles``, else assigned to ``names`` (the initiator first, :func:`roles_for`). Pass the
    ``pose_key`` whenever it is known, also with ``kind``: it is what a package's contact default is asked by. A pose
    without a pair clip, a clip without relations and without a package default, and unfit roles pass here — other
    checks name those."""
    if not kind and pose_key:
        from app.core.interaction_engine import pair_kind_for_pose
        try:
            kind = pair_kind_for_pose(pose_key.strip().lower())
        except Exception as e:  # noqa: BLE001 — an unknown pose is the start's own refusal
            logger.debug("contact gate: no clip for %r: %s", pose_key, e)
            kind = ""
    if not kind:
        return {}
    if not roles:
        roles = roles_for(kind, list(names), profiles=profiles)
    found = blockers(kind, roles or {}, profiles=profiles, pose_key=pose_key)
    if not found:
        return {}
    return {"reason": REASON, "message": llm_message(found), "blockers": [public(b) for b in found]}


def public(blocker: Dict[str, Any]) -> Dict[str, Any]:
    """A blocker as JSON for a client (the item dict stays inside)."""
    return {k: v for k, v in blocker.items() if k != "item"}


def _by_person(found: Sequence[Dict[str, Any]], lang: str = "") -> List[Dict[str, Any]]:
    from app.core.i18n import localized
    people: Dict[str, Dict[str, Any]] = {}
    for b in found:
        row = people.setdefault(b["character"], {"name": b["character"], "pieces": [], "ids": []})
        item = b.get("item")
        if item is None:
            from app.models.inventory import get_item
            item = get_item(b["item_id"]) or {}
        label = (localized(item, "name", lang) if lang else "") or b.get("item_name") or b["item_id"]
        row["pieces"].append(label)
        row["ids"].append(b["item_id"])
    return list(people.values())


def llm_message(found: Sequence[Dict[str, Any]]) -> str:
    """The reason as the characters read it (template :data:`TEMPLATE`): who still wears what, by item name and
    id, and that it has to come off before the clip can start."""
    from app.core.prompt_templates import render
    return render(TEMPLATE, people=_by_person(found))


def player_text(found: Sequence[Dict[str, Any]], lang: str = "") -> str:
    """The reason for a player's UI, translated (``i18n.t``): "Kai still wears Jeans, Boxer shorts" per person,
    joined with "; ". Item names in ``lang`` where the item has them."""
    from app.core.i18n import t
    line = t("{name} still wears {items}", lang or None)
    return "; ".join(line.replace("{name}", p["name"]).replace("{items}", ", ".join(p["pieces"]))
                     for p in _by_person(found, lang))
