"""Outfit compliance: the central function that reconciles equipped_pieces
with the decency rules and the outfit intent.

Plan: development_instructions/plan-outfit-system-rethink.md §2

Replaces the old apply_outfit_type_compliance + outfit_types model.
Decency is the only hard rule — style/weather are mere LLM hints.

Decency values:
- public:   top + bottom MUST be covered
- private:  alone_in_room OR is_intimate → everything is fine; else like public
- nude_ok:  always fine

Modifier swim_allowed: with is_wet=True, top/bottom may be replaced by
swimwear pieces or stay empty.

A free-text wardrobe (no outfit system, e.g. npc-temporary) has no pieces:
its ``outfit_worn`` switch covers every required slot or none.
"""
from typing import Any, Dict, List, Optional, Set

from app.core.log import get_logger
from app.models.inventory import (
    VALID_PIECE_SLOTS, _piece_slots, get_item, _load_inventory,
)

logger = get_logger("outfit_compliance")


# Slots that must be covered under "decency=public".
# (top + bottom — underwear does not count as "covered" socially.)
PUBLIC_REQUIRED_SLOTS: Set[str] = {"top", "bottom"}


def _get_room_and_location(character_name: str) -> tuple[Optional[Dict], Optional[Dict]]:
    """(room, location) of the character's current position."""
    from app.models.character import (
        get_character_current_location, get_character_current_room,
    )
    from app.models.world import get_location_by_id
    loc_id = get_character_current_location(character_name) or ""
    if not loc_id:
        return None, None
    loc = get_location_by_id(loc_id) or {}
    if not loc:
        return None, None
    room_id = get_character_current_room(character_name) or ""
    room = None
    if room_id:
        for r in (loc.get("rooms") or []):
            if r.get("id") == room_id or r.get("name") == room_id:
                room = r
                break
    return room, loc


def _present_other_characters(character_name: str, room_id: str,
                              location_id: str) -> List[str]:
    """Names of every other character in the same room.

    Reads character_state directly — unfiltered (a player-controlled
    character counts as present, it matters for decency).
    """
    if not (character_name and room_id and location_id):
        return []
    try:
        from app.core.db import get_connection
        conn = get_connection()
        rows = conn.execute(
            "SELECT character_name FROM character_state "
            "WHERE current_location=? AND current_room=? "
            "AND character_name != ?",
            (location_id, room_id, character_name),
        ).fetchall()
        return [r[0] for r in rows if r and r[0]]
    except Exception as e:
        logger.debug("_present_other_characters failed: %s", e)
        return []  # unclear → nobody → grant privacy


def _is_humanoid(character_name: str) -> bool:
    """True when this character is humanoid (generic template feature
    ``humanoid``). Drives the decency escalation, among others: only
    humanoid people present count as "onlookers".

    Animals and the like (animal templates: humanoid=False) do not escalate
    private to public. Default True (fail-open) for templates without it.
    """
    try:
        from app.models.character_template import is_feature_enabled
        return is_feature_enabled(character_name, "humanoid")
    except Exception as e:
        logger.debug("_is_humanoid failed: %s", e)
        return True  # when in doubt, count as a person (covered)


def _all_present_are_intimate(character_name: str,
                              others: List[str]) -> bool:
    """True when EVERY person present is a romantic partner (a couple).

    Uses the generic relationship ``type`` (core system: friend/romantic/
    rival/... — no template field). A couple may stay private in front of
    each other; as soon as a non-romantic person joins, public applies again.
    Empty list = vacuously True (alone).
    """
    if not others:
        return True
    try:
        from app.models.relationship import get_relationship
        for other in others:
            rel = get_relationship(character_name, other) or {}
            if (rel.get("type") or "").strip().lower() != "romantic":
                return False
        return True
    except Exception as e:
        logger.debug("_all_present_are_intimate failed: %s", e)
        return False  # when in doubt, public (covered)


def resolve_decency(
    character_name: str,
    *,
    is_intimate: bool = False,
) -> tuple[str, Dict[str, Any]]:
    """The effective decency value + context info.

    Order:
        1. is_intimate=True OR the decency_exempt flag → "nude_ok" (override)
        2. room.decency
        3. location.decency
        4. Default: "public"

    private escalates to "public" when a non-romantic humanoid person is
    in the room.

    Returns: (decency, context dict with debug info)
    """
    if is_intimate:
        return "nude_ok", {"reason": "is_intimate"}

    # decency_exempt: a lasting override set by hand, rule or skill (== nude_ok)
    try:
        from app.models.character import get_state_flags
        if get_state_flags(character_name).get("decency_exempt"):
            return "nude_ok", {"reason": "decency_exempt"}
    except Exception:
        pass

    room, loc = _get_room_and_location(character_name)
    raw_decency = ""
    source = ""
    if room and room.get("decency"):
        raw_decency = (room.get("decency") or "").strip().lower()
        source = "room"
    elif loc and loc.get("decency"):
        raw_decency = (loc.get("decency") or "").strip().lower()
        source = "location"
    else:
        raw_decency = "public"
        source = "default"

    ctx: Dict[str, Any] = {
        "source": source,
        "raw": raw_decency,
        "room_id": (room or {}).get("id"),
        "location_id": (loc or {}).get("id"),
        "swim_allowed": bool(
            (room or {}).get("swim_allowed") or (loc or {}).get("swim_allowed")
        ),
        "style_hint": (
            (room or {}).get("style_hint") or (loc or {}).get("style_hint") or ""
        ),
    }

    if raw_decency == "private":
        others = _present_other_characters(
            character_name, ctx["room_id"] or "", ctx["location_id"] or "")
        # Only humanoid people are "onlookers"; animals do not escalate
        # private.
        relevant = [o for o in others if _is_humanoid(o)]
        if not relevant:
            ctx["alone"] = True
            return "private", ctx
        # Couple exception: when everyone (who counts) present is a romantic
        # partner, the room stays private (nobody dresses for a partner).
        if _all_present_are_intimate(character_name, relevant):
            ctx["private_with_partner"] = True
            return "private", ctx
        ctx["escalated_to_public"] = True
        return "public", ctx

    return raw_decency, ctx


def _check_decency_violations(
    eq_pieces: Dict[str, str],
    decency: str,
    *,
    required_slots: Set[str],
    swim_allowed: bool = False,
    is_wet: bool = False,
) -> Set[str]:
    """The slots decency wants occupied that are empty. Empty set = no
    violation.

    required_slots comes from the caller: PUBLIC_REQUIRED_SLOTS cut to the
    clothing topology of the species — a cat without 'top'/'bottom' can
    never be uncovered.
    """
    if decency in ("nude_ok", "private"):
        return set()
    if decency != "public":
        # Unknown decency: defensively report no violation
        return set()
    # public: the species' required slots must be covered
    missing = {s for s in required_slots if not eq_pieces.get(s)}
    if swim_allowed and is_wet:
        # Swim exemption: swimwear slots count as covered
        if eq_pieces.get("swimwear_top"):
            missing.discard("top")
        if eq_pieces.get("swimwear_bottom"):
            missing.discard("bottom")
    return missing


def _find_inventory_piece_for_slot(
    character_name: str,
    target_slot: str,
    *,
    style_hint: str = "",
    exclude_ids: Optional[Set[str]] = None,
) -> Optional[str]:
    """Find an outfit piece in the inventory that fills the slot.

    Takes the first matching single-slot piece. (The former outfit_types/
    style_hint preference is gone with the outfit_types model; style_hint is
    only a creation hint now, no mechanical selection rule.) Multi-slot
    pieces are skipped — they come through ChangeOutfit / the wardrobe,
    otherwise they would displace occupied slots.
    """
    exclude_ids = exclude_ids or set()
    inv = _load_inventory(character_name).get("inventory", [])
    for entry in inv:
        iid = entry.get("item_id")
        if not iid or iid in exclude_ids:
            continue
        item = get_item(iid)
        if not item or item.get("category") != "outfit_piece":
            continue
        slots = _piece_slots(item)
        if target_slot not in slots or len(slots) > 1:
            continue
        return iid
    return None


def _required_slots(character_name: str) -> Set[str]:
    """PUBLIC_REQUIRED_SLOTS cut to the clothing topology of the species
    (body-slot packages): a species without top/bottom (a cat) can never be
    uncovered. Fail-open to the full set."""
    try:
        from app.core.body_slots import piece_slots_for_character
        return PUBLIC_REQUIRED_SLOTS & set(piece_slots_for_character(character_name))
    except Exception:
        return set(PUBLIC_REQUIRED_SLOTS)


def _notify_violations(character_name: str, decency: str,
                       violations: List[Dict[str, Any]]) -> None:
    """One notification for the hard violations — once while it is unread:
    compliance runs on every pose, room and flag change, and identical rows
    used to fill the whole notification window."""
    hard = [v for v in violations if v.get("reason") in
            ("no_inventory_piece", "forced_piece_not_equipped", "outfit_not_worn")]
    if not hard:
        return
    try:
        # ``add_notification`` never existed — the module has
        # ``create_notification``, and the ImportError was swallowed by
        # the except below, so this warning never arrived
        # (review 2026-09-20, KOORD-1).
        from app.models.notifications import create_notification
        from app.core.i18n import t
        from app.models.character import get_character_language
        lang = (get_character_language(character_name) or "en").strip() or "en"
        slots = ", ".join(v["slot"] for v in hard)
        if all(v["reason"] == "outfit_not_worn" for v in hard):
            content = t("Outfit does not fit a {decency} room — not dressed, "
                        "missing: {slots}.", lang).format(decency=decency, slots=slots)
        else:
            content = t("Outfit does not fit a {decency} room — missing: "
                        "{slots}. No suitable clothing in the inventory.",
                        lang).format(decency=decency, slots=slots)
        create_notification(character_name, f"⚠️ {content}",
                            notification_type="outfit_mismatch", once_unread=True)
    except Exception as e:
        logger.debug("outfit mismatch notification failed: %s", e)


def apply_outfit_compliance(
    character_name: str,
    *,
    is_intimate: Optional[bool] = None,
    is_wet: Optional[bool] = None,
    is_sleeping: Optional[bool] = None,
) -> Dict[str, Any]:
    """The central compliance function (plan §2).

    State flags (is_intimate, is_wet, is_sleeping) are read from
    character_state unless passed explicitly; activity skills set them.

    Algorithm:
        1. is_sleeping=True → no-op (off-map)
        2. intent.locked → no-op
        3. a free-text wardrobe: ``outfit_worn`` alone decides, then 8.
        4. respect intent.forced_pieces (an occupied slot stays)
        5. intent.forbidden_slots → these slots are cleared
        6. decency check against the resulting equipped_pieces
        7. violated slots: auto-fill from the inventory
        8. still violated: one notification (once while unread)

    Returns:
        {
          "status": "ok" | "locked" | "skipped",
          "decency": str,
          "intent_locked": bool,
          "forced_kept": [slot, ...],
          "forbidden_cleared": [slot, ...],
          "auto_filled": [{slot, item_id}, ...],
          "violations": [{slot, reason}, ...],
        }
    """
    from app.models.character import (
        get_character_profile, save_character_profile, get_outfit_intent,
        get_state_flags,
    )

    # State flags from the profile unless overridden
    if is_intimate is None or is_wet is None or is_sleeping is None:
        flags = get_state_flags(character_name)
        if is_intimate is None:
            is_intimate = flags["is_intimate"]
        if is_wet is None:
            is_wet = flags["is_wet"]
        if is_sleeping is None:
            is_sleeping = flags["is_sleeping"]

    result: Dict[str, Any] = {
        "status": "ok",
        "decency": "",
        "intent_locked": False,
        "forced_kept": [],
        "forbidden_cleared": [],
        "auto_filled": [],
        "violations": [],
    }

    if is_sleeping:
        # Sleeping characters are off-map — no compliance.
        result["status"] = "skipped"
        result["reason"] = "is_sleeping"
        return result

    intent = get_outfit_intent(character_name)
    if intent.get("locked"):
        result["status"] = "locked"
        result["intent_locked"] = True
        return result

    decency, ctx = resolve_decency(character_name, is_intimate=is_intimate)
    result["decency"] = decency
    result["decency_context"] = ctx

    profile = get_character_profile(character_name) or {}
    from app.core.outfit_renderer import is_free_text_wardrobe, is_outfit_worn
    if is_free_text_wardrobe(profile):
        # A free-text wardrobe (npc-temporary) has no pieces to fill, clear
        # or force: its one switch ``outfit_worn`` covers every required
        # slot or none — undressed in a room that wants clothes is a
        # violation, a described outfit never is.
        required = _required_slots(character_name)
        worn = {slot: "outfit_description" for slot in required} if is_outfit_worn(profile) else {}
        for slot in sorted(_check_decency_violations(
                worn, decency, required_slots=required,
                swim_allowed=bool(ctx.get("swim_allowed")), is_wet=is_wet)):
            result["violations"].append({"slot": slot, "reason": "outfit_not_worn"})
        _notify_violations(character_name, decency, result["violations"])
        return result

    eq_pieces: Dict[str, str] = dict(profile.get("equipped_pieces") or {})
    changed = False

    # 1. forced_pieces: check that the demanded items are worn.
    forced = intent.get("forced_pieces") or {}
    for slot, iid in forced.items():
        if eq_pieces.get(slot) != iid:
            # Not equipped actively — that is the job of ChangeOutfit /
            # equip_piece (multi-slot mirroring, displacement etc.).
            # Compliance respects the status quo and reports a forced
            # piece that is not worn.
            result["violations"].append(
                {"slot": slot, "reason": "forced_piece_not_equipped",
                 "expected": iid, "actual": eq_pieces.get(slot)}
            )
        else:
            result["forced_kept"].append(slot)

    # 2. forbidden_slots: clear them if still occupied (and not forced).
    forbidden = set(intent.get("forbidden_slots") or [])
    if forbidden:
        from app.models.inventory import unequip_piece
        for slot in sorted(forbidden):
            if slot in forced:
                continue  # forced beats forbidden (the conflict special case)
            if eq_pieces.get(slot):
                # unequip_piece takes care of the multi-slot mirrors
                try:
                    res = unequip_piece(character_name, slot=slot, source="compliance")
                    # A refused unequip leaves the slot.
                    if res.get("status") == "ok":
                        eq_pieces.pop(slot, None)
                        result["forbidden_cleared"].append(slot)
                        changed = True
                except Exception as e:
                    logger.debug("forbidden_slots clear [%s/%s]: %s",
                                 character_name, slot, e)

    # 3. Decency check against the required slots (see _required_slots).
    swim_allowed = bool(ctx.get("swim_allowed"))
    _required = _required_slots(character_name)
    missing = _check_decency_violations(
        eq_pieces, decency,
        required_slots=_required,
        swim_allowed=swim_allowed, is_wet=is_wet,
    )

    # 4. Auto-fill: fix violations UNLESS the slot is forbidden
    style_hint = ctx.get("style_hint") or intent.get("target_outfit_type") or ""
    auto_fill_attempted = []
    for slot in sorted(missing):
        if slot in forbidden:
            # user/LLM marked the slot explicitly empty — do not fill
            result["violations"].append(
                {"slot": slot, "reason": "forbidden_but_decency_violated"}
            )
            continue
        # inventory search
        exclude = set(eq_pieces.values())
        cand_id = _find_inventory_piece_for_slot(
            character_name, slot,
            style_hint=style_hint, exclude_ids=exclude,
        )
        auto_fill_attempted.append(slot)
        if not cand_id:
            result["violations"].append(
                {"slot": slot, "reason": "no_inventory_piece"}
            )
            continue
        # Equip through equip_piece (handles mirrors and persistence)
        from app.models.inventory import equip_piece
        try:
            res = equip_piece(character_name, cand_id, source="compliance")
            if res.get("status") != "ok":
                result["violations"].append(
                    {"slot": slot, "reason": f"equip_failed: {res.get('reason', '')}"})
                continue
            eq_pieces[slot] = cand_id
            result["auto_filled"].append({"slot": slot, "item_id": cand_id})
            changed = True
        except Exception as e:
            logger.warning("auto_fill [%s/%s] failed: %s",
                           character_name, slot, e)
            result["violations"].append(
                {"slot": slot, "reason": f"equip_failed: {e}"}
            )

    # 5. Persist + Event
    if changed:
        # equipped_pieces were persisted by equip/unequip_piece already.
        # Their outfit events were published there as well.
        logger.info(
            "outfit_compliance [%s] decency=%s: filled=%d, cleared=%d, violations=%d",
            character_name, decency,
            len(result["auto_filled"]),
            len(result["forbidden_cleared"]),
            len(result["violations"]),
        )

    # 6. Notification for the hard decency violations (not forbidden ones).
    _notify_violations(character_name, decency, result["violations"])

    return result
