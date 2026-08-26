"""The temporary-NPC recycling pool (plan-npc-auto-spawn.md § 3).

An expired NPC is not deleted any more: its profile is kept and the row is
marked ``status='pooled'``. A pooled NPC is NOT in the world — it stands
nowhere, it is in no roster, no payload and no earshot list, because the ONE
roster gate (``list_available_characters``) filters the status out. What it
still is: a finished character sheet with a name, a face, a personality and a
role, which the next spawn of that role can put back on the map without three
LLM turns.

Two things are deliberately DESTROYED on the way into the pool, even though
the profile survives:

* what the other characters remember about the NPC (``cleanup_npc_traces``) —
  the decision from plan-temporary-npcs.md § 10.4 is unchanged by pooling;
* the NPC's own conversation rows. A pooled NPC comes back as a stranger,
  possibly in another town; carrying yesterday's tavern talk into the room
  perception stream would give a disposable NPC exactly the continuity the
  whole temp-NPC design switches off.

The pool has the same size as the living cap (``npc.max_alive``): it is a
FIFO, the longest-pooled entry is the one a spawn re-uses and the one that is
deleted for good when the pool overflows.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.core.log import get_logger

logger = get_logger("npc_pool")


def max_pool_size() -> int:
    """Pool size = the living cap (§ 3, "Pool-Größe = Limit")."""
    from app.core.npc_spawn import max_alive
    return max_alive()


# ---------------------------------------------------------------------------
# Into the pool
# ---------------------------------------------------------------------------

def _forget_own_conversation(name: str) -> Dict[str, int]:
    """Delete the NPC's own chat/perception rows.

    ``delete_character`` would take these along; pooling keeps the row, so the
    conversation has to be cut explicitly. Utterances cascade into perceptions
    via the FK, but the perceptions the NPC HEARD hang off other speakers'
    utterances and are removed by perceiver.
    """
    from app.core.db import transaction
    removed = {"chat_messages": 0, "utterances": 0, "perceptions": 0}
    try:
        with transaction() as conn:
            def _has(table: str) -> bool:
                return bool(conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                    (table,)).fetchone())
            if _has("chat_messages"):
                cur = conn.execute(
                    "DELETE FROM chat_messages WHERE character_name=? OR partner=?",
                    (name, name))
                removed["chat_messages"] = int(cur.rowcount or 0)
            if _has("perceptions"):
                cur = conn.execute("DELETE FROM perceptions WHERE perceiver=?",
                                   (name,))
                removed["perceptions"] = int(cur.rowcount or 0)
            if _has("utterances"):
                cur = conn.execute("DELETE FROM utterances WHERE speaker=?",
                                   (name,))
                removed["utterances"] = int(cur.rowcount or 0)
    except Exception as e:  # noqa: BLE001
        logger.warning("pool: conversation cleanup for %s failed: %s", name, e)
    return removed


def _unplace(name: str) -> None:
    """Take the NPC off the map: no point, no location, no room.

    Written directly because every structured setter has side effects that
    belong to a character that IS somewhere — arrival events, discovery,
    outfit compliance, party drag. A pooled NPC is not moving, it is leaving
    the world.
    """
    from app.core.db import transaction
    try:
        with transaction() as conn:
            conn.execute(
                "UPDATE character_state SET current_location='', current_room='',"
                " pos_x=NULL, pos_z=NULL WHERE character_name=?", (name,))
    except Exception as e:  # noqa: BLE001
        logger.warning("pool: could not unplace %s: %s", name, e)


def pool_npc(name: str, reason: str = "") -> bool:
    """Move a living temporary NPC into the pool. True when it went in.

    Only a temporary NPC can be pooled — an ordinary character has a place in
    this world and never becomes spare parts.
    """
    from app.models.character import (POOLED_STATUS, get_character_profile,
                                      is_temporary_npc, save_character_profile,
                                      set_character_status)
    if not name or not is_temporary_npc(name):
        return False

    # 1) Everything that must not survive the NPC.
    try:
        from app.core.memory_service import cleanup_npc_traces
        cleanup_npc_traces(name)
    except Exception as e:  # noqa: BLE001
        logger.warning("pool: trace cleanup for %s failed: %s", name, e)
    _forget_own_conversation(name)

    # 2) Out of every running mechanic that assumes a present character.
    for step in (lambda: _end_party(name), lambda: _end_journey(name),
                 lambda: _end_interaction(name)):
        try:
            step()
        except Exception as e:  # noqa: BLE001
            logger.debug("pool(%s) detach step failed: %s", name, e)

    # 3) Off the map, then out of the roster.
    _unplace(name)
    profile = get_character_profile(name) or {}
    profile["expires_at"] = ""           # a pooled NPC has no lifetime left
    profile["npc_wanderer"] = False
    profile.pop("wander_target", None)
    profile["npc_pooled_reason"] = (reason or "").strip()
    save_character_profile(name, profile)
    set_character_status(name, POOLED_STATUS)
    logger.info("Temporary NPC '%s' pooled (%s)", name, reason or "expired")

    _enforce_pool_cap()
    return True


def _end_party(name: str) -> None:
    from app.core.party_engine import clear_invites_for, is_in_party, leave_party
    if is_in_party(name):
        leave_party(name)
    clear_invites_for(name)


def _end_journey(name: str) -> None:
    from app.core.travel_engine import cancel_journey
    cancel_journey(name)


def _end_interaction(name: str) -> None:
    from app.core.interaction_engine import end_interaction
    end_interaction(name, reason="pooled")


def _enforce_pool_cap() -> int:
    """Delete the oldest pooled NPCs beyond the cap. Returns how many went."""
    from app.models.character import delete_character, list_pooled_characters
    cap = max(0, max_pool_size())
    pooled = list_pooled_characters()
    dropped = 0
    for name in pooled[:max(0, len(pooled) - cap)]:
        # delete_character sweeps the row, the storage dir and (temp NPC) the
        # foreign traces — for a pooled NPC the traces are already gone, which
        # makes this the plain, final removal.
        if delete_character(name):
            dropped += 1
            logger.info("Pool overflow: '%s' deleted for good", name)
    return dropped


# ---------------------------------------------------------------------------
# Out of the pool
# ---------------------------------------------------------------------------

def take_from_pool(role: str = "", template: str = "") -> Optional[str]:
    """The longest-pooled NPC of that role, or None.

    The role is the SLOT TAG on the profile, never a name match
    (feedback_no_name_resolution). An empty role means "any pooled NPC" — that
    is what a wanderer asks for, since a wanderer has no slot.

    ``template`` is only checked when the SLOT names one: a slot that insists
    on its own NPC kind (an animal, a guard variant) must not be handed a
    sheet built from the default template, while a default slot happily takes
    any temporary NPC back.

    An NPC that a queued ``npc_assets`` job still owes a placement is NOT free
    stock, even though it sits in the pool: that job carries the FIRST
    claimant's location, so handing the same sheet out twice would place it
    there and leave the second slot silently empty.
    """
    from app.core.npc_assets import is_awaiting_assets
    from app.models.character import get_character_profile, is_temporary_npc
    from app.models.character import list_pooled_characters
    wanted = (role or "").strip().lower()
    wanted_tmpl = (template or "").strip()
    for name in list_pooled_characters():
        if not is_temporary_npc(name) or is_awaiting_assets(name):
            continue
        profile = get_character_profile(name) or {}
        if wanted_tmpl and str(profile.get("template") or "") != wanted_tmpl:
            continue
        if not wanted:
            return name
        if str(profile.get("npc_slot_role") or "").strip().lower() == wanted:
            return name
    return None


def revive_from_pool(name: str, location_id: str, room_id: str = "",
                     ttl_hours: Optional[float] = None, slot_role: str = "",
                     briefing: str = "", wanderer: bool = False,
                     wander_target: str = "") -> bool:
    """Put a pooled NPC back into the world at a place. True on success.

    The same bookkeeping ``npc_ops.apply_npc`` stamps after a generated NPC —
    one function later in the chain, because the character sheet itself is
    already there. NO name refresh: renaming a character means moving its
    storage directory and rewriting every row keyed by its name, which is the
    opposite of the cheap re-use this path exists for (see the plan note).
    """
    from app.core.npc_ops import expiry_stamp
    from app.models.character import (get_character_profile, is_temporary_npc,
                                      save_character_current_location,
                                      save_character_current_room,
                                      save_character_profile,
                                      set_character_status)
    if not name or not is_temporary_npc(name):
        return False

    profile = get_character_profile(name) or {}
    profile["expires_at"] = expiry_stamp(ttl_hours)
    profile["npc_slot_role"] = (slot_role or "").strip()
    profile["npc_slot_location"] = (location_id or "").strip() if slot_role else ""
    profile["npc_wanderer"] = bool(wanderer)
    # The road before the placement — the gate's job is what sends a
    # held-back wanderer off, so it must already know where to (see
    # ``npc_ops.apply_npc`` for the same three lines on the generated path).
    if wanderer and wander_target:
        profile["wander_origin"] = location_id
        profile["wander_target"] = wander_target
    profile["npc_briefing"] = (briefing or "").strip() or profile.get("npc_briefing", "")
    profile["outfit_worn"] = True
    task = str(profile.get("standing_task") or "").strip()
    if task:
        profile["current_activity"] = task
    profile.pop("npc_pooled_reason", None)
    save_character_profile(name, profile)

    # THE FINISH GATE (plan-npc-leben § 0 A), before the NPC is back in the
    # roster: a pooled sheet may be missing its portrait or its mesh, and an
    # unfinished NPC is not put on the map. TRUE for the caller all the same —
    # `npc_spawn.spawn_for_slot` reads False as "the pool did not deliver" and
    # would run the three-turn pipeline for an NPC that is already claimed.
    from app.core.npc_assets import gate_placement
    if gate_placement(name, location_id, room_id, wanderer=wanderer,
                      wander_target=wander_target):
        logger.info("Pooled NPC '%s' claimed for %s (role %r) — placed once "
                    "its assets exist", name, location_id or "(nowhere)",
                    slot_role or "-")
        return True

    # Back into the roster BEFORE the placement: the location setter runs the
    # ordinary arrival side effects, and those read the roster.
    set_character_status(name, "")
    if location_id:
        try:
            save_character_current_location(name, location_id)
            if room_id:
                save_character_current_room(name, room_id)
        except Exception as e:  # noqa: BLE001
            logger.warning("revive %s at %s failed: %s", name, location_id, e)
            return False
    logger.info("Pooled NPC '%s' revived at %s (role %r)",
                name, location_id or "(nowhere)", slot_role or "-")
    return True


# ---------------------------------------------------------------------------
# Listing (Game-Admin)
# ---------------------------------------------------------------------------

def list_pool() -> List[Dict[str, Any]]:
    """One row per pooled NPC for the Game-Admin NPC section."""
    from app.models.character import get_character_profile, is_temporary_npc
    from app.models.character import list_pooled_characters
    rows: List[Dict[str, Any]] = []
    for name in list_pooled_characters():
        if not is_temporary_npc(name):
            continue
        profile = get_character_profile(name) or {}
        rows.append({
            "name": name,
            "template": profile.get("template") or "",
            "role": profile.get("npc_slot_role") or "",
            "standing_task": profile.get("standing_task") or "",
            "reason": profile.get("npc_pooled_reason") or "",
        })
    return rows
