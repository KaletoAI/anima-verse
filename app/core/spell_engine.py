"""Spell items use the inventory system for direct effects, gifts and anchor teleports.

Items define an incantation, success chance, optional effect item, cost,
consumption policy and narrative success/failure text. Detection uses the
configured tool LLM; execution applies costs before rolling."""
import json
import random as _random
import re
from typing import Any, Dict, List, Optional

from app.core.log import get_logger

logger = get_logger("spell_engine")


def build_spell_catalog(character_name: str) -> List[Dict[str, Any]]:
    """Collect castable inventory items, including costs and teleport metadata."""
    try:
        from app.models.inventory import get_character_inventory, get_item
        inv = get_character_inventory(character_name, include_equipped=True) or {}
        items = inv.get("inventory", []) if isinstance(inv, dict) else []
        out: List[Dict[str, Any]] = []
        for entry in items:
            iid = entry.get("item_id") or ""
            if not iid:
                continue
            item = get_item(iid) or {}
            incant = (item.get("incantation") or "").strip()
            if not incant:
                continue
            out.append({
                "id": iid,
                "name": item.get("name") or iid,
                "incantation": incant,
                "description": (item.get("description") or "").strip(),
                "mode": (item.get("spell_mode") or "force").strip().lower(),
                "clone_item_id": (item.get("clone_item_id") or iid).strip(),
                "success_chance": int(item.get("success_chance") or 100),
                "copy_on_give": bool(item.get("copy_on_give", False)),
                "cost": item.get("cost") or {},
                "success_text": (item.get("success_text") or "").strip(),
                "fail_text": (item.get("fail_text") or "").strip(),
                "cast_activity": (item.get("cast_activity") or "").strip(),
                "anchor_item_id": (item.get("anchor_item_id") or "").strip(),
                "teleport_subject": (item.get("teleport_subject") or "caster").strip().lower(),
                "quantity": int(entry.get("quantity") or 1),
            })
        return out
    except Exception as e:
        logger.debug("build_spell_catalog failed for %s: %s", character_name, e)
        return []


def has_spell_detect_routing(avatar_name: str = "") -> bool:
    """Return whether the spell detection task has a routed LLM.

    The chat flow can use this to explain why incantations cannot be detected."""
    try:
        from app.core.llm_router import resolve_llm
        return resolve_llm("spell_detect", agent_name=avatar_name) is not None
    except Exception:
        return False


def _format_catalog(catalog: List[Dict[str, Any]]) -> str:
    """Format the spell catalogue for the detection prompt."""
    lines: List[str] = []
    for s in catalog:
        line = f"- id={s['id']} | incantation: \"{s['incantation']}\""
        if s.get("description"):
            line += f" | effect: {s['description'][:120]}"
        lines.append(line)
    return "\n".join(lines) if lines else "(none)"


def detect_cast(avatar_name: str, target_name: str, message: str,
                catalog: Optional[List[Dict[str, Any]]] = None,
                volume: str = "normal") -> Optional[Dict[str, Any]]:
    """Detect an incantation conservatively with the tool LLM.

    Return the catalogue entry with confidence and narration, or None.
    Require matching incantation tokens before calling the LLM and discard
    confidence below 60 to avoid treating related conversation as a cast."""
    if not message or not avatar_name:
        return None
    if catalog is None:
        catalog = build_spell_catalog(avatar_name)
    if not catalog:
        return None

    msg_lower = message.lower()
    incantation_match = False
    for s in catalog:
        inc = (s.get("incantation") or "").strip()
        if not inc:
            continue
        # Match significant incantation tokens, ignoring short filler words.
        toks = [t for t in re.findall(r"[\wÄÖÜäöüß]+", inc.lower()) if len(t) >= 3]
        if toks and all(t in msg_lower for t in toks):
            incantation_match = True
            break
    if not incantation_match:
        logger.debug("spell_detect skip: keine Incantation-Tokens in '%s'", message[:60])
        return None

    try:
        from app.core.llm_router import llm_call
        from app.core.prompt_templates import render_task
        from app.models.character import get_character_language, LANGUAGE_MAP
        lang_code = (get_character_language(avatar_name) or "en").strip()
        language_name = LANGUAGE_MAP.get(lang_code, "English")
        vol = (volume or "normal").strip().lower()
        volume_hint = {
            "whisper": "The caster is WHISPERING — the cast is barely audible, "
                       "murmured under the breath; bystanders can hardly hear it. "
                       "Phrase the observation accordingly (quiet, hushed).",
            "shout": "The caster is SHOUTING — the cast rings out loudly and "
                     "forcefully. Phrase the observation accordingly (loud).",
        }.get(vol, "The caster speaks at a normal, audible volume.")
        sys_prompt, user_prompt = render_task(
            "spell_detect",
            avatar_name=avatar_name,
            target_name=target_name or "(no target)",
            message=message,
            spell_catalog=_format_catalog(catalog),
            language_name=language_name,
            volume_hint=volume_hint)
        response = llm_call(
            task="spell_detect",
            system_prompt=sys_prompt,
            user_prompt=user_prompt,
            agent_name=avatar_name)
        raw = (response.content or "").strip()
    except Exception as e:
        logger.debug("spell_detect llm_call failed: %s", e)
        return None

    # Parse JSON defensively.
    try:
        # Strip Markdown fences.
        if raw.startswith("```"):
            raw = "\n".join(ln for ln in raw.split("\n") if not ln.strip().startswith("```"))
        # Find the first balanced JSON object.
        import re as _re
        m = _re.search(r"\{[^{}]*\}", raw)
        data = json.loads(m.group(0) if m else raw)
    except Exception:
        return None

    spell_id = (data.get("spell_id") or "").strip()
    if not spell_id:
        return None
    confidence = int(data.get("confidence") or 0)
    if confidence < 60:
        logger.info("spell_detect: low confidence (%d) for spell_id=%s — ignored",
                    confidence, spell_id)
        return None

    matched = next((s for s in catalog if s["id"] == spell_id), None)
    if not matched:
        logger.warning("spell_detect: LLM returned unknown spell_id=%s", spell_id)
        return None

    chat_substitute = (data.get("chat_substitute") or "").strip()
    return {**matched, "confidence": confidence, "chat_substitute": chat_substitute}


def cast_blocked_reason(profile: dict, spell: Dict[str, Any]) -> str:
    """Use the shared effective-stat cost gate for casts and their buttons."""
    from app.core.skill_gate import stat_costs_shortfall
    if stat_costs_shortfall(profile, spell.get("cost") or {}):
        return f"Too exhausted to cast {spell.get('name') or spell.get('id') or ''}."
    return ""


def execute_cast(avatar_name: str, target_name: str,
                 spell: Dict[str, Any]) -> Dict[str, Any]:
    """Check and charge the caster, roll success, then apply the spell.

    Cost refusal preserves the regular result keys and consumes no item.
    Eligible attempts pay once regardless of the roll or subsequent effects."""
    from app.core.modifiers import factor
    chance = max(0, min(100, round(int(spell.get("success_chance", 100))
                                   * factor(avatar_name, "spell_success"))))
    from app.models.character import get_character_profile, adjust_status_effects
    from app.core.keyed_lock import keyed_lock
    # Keep eligibility and payment together; no external work runs under this lock.
    with keyed_lock("character_profile", avatar_name):
        reason = cast_blocked_reason(get_character_profile(avatar_name) or {}, spell)
        if reason:
            return {
                "success": False, "hint": reason, "reason": "cost",
                "spell_id": spell.get("id") or "",
                "spell_name": spell.get("name") or spell.get("id") or "",
                "chance": chance, "roll": None,
                "delivered_item_id": "", "delivered_item_name": "", "teleport": {},
                "chat_substitute": (spell.get("chat_substitute") or "").strip(),
            }
        adjust_status_effects(avatar_name,
                              {key: -value for key, value in (spell.get("cost") or {}).items()},
                              source=f"spell:{spell.get('name') or spell.get('id') or ''}")
    roll = _random.randint(1, 100)
    success = roll <= chance
    hint = ""
    spell_id = spell.get("id") or ""
    clone_id = spell.get("clone_item_id") or spell_id
    mode = spell.get("mode") or "force"
    anchor_item_id = (spell.get("anchor_item_id") or "").strip()
    teleport_subject = (spell.get("teleport_subject") or "caster").strip().lower()

    delivered_item_id = ""
    delivered_item_name = ""
    teleport_info: Dict[str, Any] = {}

    # Anchor teleports override ordinary item delivery. Room anchors support
    # caster travel only; pulling an anchor holder requires a character.
    if success and anchor_item_id:
        try:
            from app.models.inventory import find_item_location
            from app.models.character import (
                get_character_current_location,
                get_character_current_room,
                save_character_current_location,
                save_character_current_room)
            # Exclude the caster to prevent a teleport to the same character.
            anchor = find_item_location(anchor_item_id, exclude_character=avatar_name)
            if not anchor:
                logger.info("Cast %s: Anker %s nirgends gefunden — Fail",
                            spell_id, anchor_item_id)
                success = False
            else:
                if teleport_subject == "anchor_holder":
                    # Pull a character holding the anchor to the caster.
                    if anchor["kind"] != "character":
                        logger.info("Cast %s: subject=anchor_holder aber Anker im Raum — Fail",
                                    spell_id)
                        success = False
                    else:
                        moved = anchor["character"]
                        dest_loc = get_character_current_location(avatar_name) or ""
                        dest_room = get_character_current_room(avatar_name) or ""
                        if dest_loc:
                            save_character_current_location(moved, dest_loc)
                        if dest_room:
                            save_character_current_room(moved, dest_room)
                        teleport_info = {
                            "moved_character": moved,
                            "to_location": dest_loc,
                            "to_room": dest_room,
                            "subject": "anchor_holder",
                        }
                else:
                    # Move the caster to the anchor location.
                    if anchor["kind"] == "character":
                        holder = anchor["character"]
                        dest_loc = get_character_current_location(holder) or ""
                        dest_room = get_character_current_room(holder) or ""
                    else:
                        dest_loc = anchor.get("location_id") or ""
                        dest_room = anchor.get("room_id") or ""
                    if not dest_loc:
                        logger.info("Cast %s: Anker hat keinen Standort — Fail", spell_id)
                        success = False
                    else:
                        save_character_current_location(avatar_name, dest_loc)
                        if dest_room:
                            save_character_current_room(avatar_name, dest_room)
                        teleport_info = {
                            "moved_character": avatar_name,
                            "to_location": dest_loc,
                            "to_room": dest_room,
                            "subject": "caster",
                        }
        except Exception as e:
            logger.error("anchor teleport failed: %s", e)
            success = False
        # Consume single-use spells only after a successful teleport.
        if success and not spell.get("copy_on_give"):
            try:
                from app.models.inventory import remove_from_inventory
                remove_from_inventory(avatar_name, spell_id, quantity=1, force=True)
            except Exception as e:
                logger.debug("spell consume failed: %s", e)

    elif success:
        # Deliver ordinary effects; copy_on_give preserves learned spells.
        if not spell.get("copy_on_give"):
            try:
                from app.models.inventory import remove_from_inventory
                remove_from_inventory(avatar_name, spell_id, quantity=1, force=True)
            except Exception as e:
                logger.debug("spell consume failed: %s", e)
        # Without a separate effect item, apply effects directly to the target.
        # Giving the spell itself would create a castable copy and self-gifts
        # would conflict with the unique character/item inventory key.
        is_direct_effect = (clone_id == spell_id)
        try:
            from app.models.inventory import give_item, get_item, apply_item_effects
            if is_direct_effect:
                # Attribute the condition to the caster as its giver.
                apply_item_effects(target_name, clone_id, giver=avatar_name)
                _eff_item = get_item(clone_id) or {}
                delivered_item_id = clone_id
                delivered_item_name = (_eff_item.get("name") or clone_id).strip()
            else:
                # Force delivery locks the item and applies its condition.
                ok = give_item(
                    from_character=avatar_name,
                    to_character=target_name,
                    item_id=clone_id,
                    mode=mode,                  # "force" or "gift"
                    consume_source=False,       # already consumed above
                )
                if ok:
                    delivered_item_id = clone_id
                    _eff_item = get_item(clone_id) or {}
                    delivered_item_name = (_eff_item.get("name") or clone_id).strip()
                else:
                    logger.warning("give_item returned False during cast: %s -> %s (item=%s)",
                                   avatar_name, target_name, clone_id)
                    success = False
        except Exception as e:
            logger.error("give_item failed during cast: %s", e)
            success = False

    if success:
        # Set the avatar pose — default "casting a spell", overridable per
        # spell via cast_activity. Applies on both paths (classic + anchor
        # teleport) and on a self-cast from the inventory.
        cast_activity = (spell.get("cast_activity") or "casting a spell").strip()
        if cast_activity:
            from app.core.pose_catalog import PairPoseWithoutPartner
            try:
                from app.models.character import set_pose_intent
                set_pose_intent(avatar_name, cast_activity)
                logger.info("Cast pose set: %s -> %s", avatar_name, cast_activity)
            except PairPoseWithoutPartner as e:
                # A spell cannot conscript a partner — the cast succeeds, the
                # pose does not.
                logger.info("Cast pose skipped: '%s' is the two-person pose "
                            "'%s'", cast_activity, e)
            except Exception as e:
                logger.warning("Cast pose could not be set: %s", e)

        hint = (spell.get("success_text") or "").strip()
        if not hint:
            if teleport_info:
                hint = (f"A teleport spell ({spell.get('name') or spell_id}) "
                        f"shifts the scene.")
            else:
                hint = f"A spell hits you ({spell.get('name') or spell_id})."
    else:
        hint = (spell.get("fail_text") or "").strip()
        if not hint:
            if anchor_item_id:
                hint = (f"The cast of {spell.get('name') or spell_id} fizzled — "
                        "the anchor could not be reached.")
            else:
                hint = (f"Someone tried to cast {spell.get('name') or spell_id} on you "
                        "but it failed — only a faint tingle.")

    logger.info("Cast %s by %s on %s: %s (roll %d/%d)",
                spell_id, avatar_name, target_name,
                "SUCCESS" if success else "FAIL", roll, chance)
    return {
        "success": success,
        "hint": hint,
        "spell_id": spell_id,
        "spell_name": (spell.get("name") or spell_id),
        "chance": chance,
        "roll": roll,
        "delivered_item_id": delivered_item_id,
        "delivered_item_name": delivered_item_name,
        # Optional teleport details for map refresh and player feedback.
        "teleport": teleport_info,
        # Use LLM narration instead of the raw incantation in chat.
        "chat_substitute": (spell.get("chat_substitute") or "").strip(),
    }


def detect_and_cast(avatar_name: str, target_name: str,
                    message: str, volume: str = "normal") -> Optional[Dict[str, Any]]:
    """Detect an incantation and execute it, or return None.

    Volume informs the detection narration. Callers can pass the returned hint
    to the target's next prompt."""
    detected = detect_cast(avatar_name, target_name, message, volume=volume)
    if not detected:
        return None
    return execute_cast(avatar_name, target_name, detected)
