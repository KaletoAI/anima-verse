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

The pool has its own size (``npc.max_pool_size``, default 50) — how much
finished work a world keeps in stock is a different question from how crowded
it is (``npc.max_alive``). It is a FIFO: the longest-pooled entry is the one a
spawn re-uses and the one that is deleted for good when the pool overflows.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.core.log import get_logger

logger = get_logger("npc_pool")


def max_pool_size() -> int:
    """How many pooled sheets are kept. Beyond it the oldest one is deleted."""
    from app.core.npc_spawn import _cfg
    try:
        return max(0, int(_cfg("max_pool_size", 50)))
    except (TypeError, ValueError):
        return 50


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
    # The HOME AREA goes with the slot stamps: a recycled sheet may come back
    # as a barkeeper in another town, and yesterday's forest circle would send
    # it walking into a place it has nothing to do with (spec § E3).
    profile.pop("npc_home", None)
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
    """Delete the oldest pooled NPCs beyond the cap. Returns how many went.

    A PERMANENT sheet (``npc_permanent``) is invisible to the cap in both
    directions: it is never deleted, and it never counts towards the overflow.
    The cap exists to stop recycled stock from piling up, and a permanent sheet
    is not stock — since ``take_from_pool`` skips it, no spawn will ever touch
    it again, so it would otherwise sit at the FRONT of the deletion queue
    (``list_pooled_characters`` is oldest-first) and the one character an admin
    explicitly marked as kept would be the first one deleted for good.
    """
    from app.models.character import (delete_character, get_character_profile,
                                      list_pooled_characters)
    cap = max(0, max_pool_size())
    pooled = [n for n in list_pooled_characters()
              if not (get_character_profile(n) or {}).get("npc_permanent")]
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

    A PERMANENT sheet (``npc_permanent``) is not stock either. An admin took
    that character's lifetime away on purpose, and an automatic spawn grabbing
    it would drop somebody's kept NPC into the next inn as its barkeeper. Its
    way out of the pool is a SLOT BINDING — a bound slot revives exactly that
    sheet; there is no other exit today. It is invisible to the pool cap in
    exchange (see ``_enforce_pool_cap``), so waiting there costs it nothing.
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
        if profile.get("npc_permanent"):
            continue
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
                     wander_target: str = "", radius_m: float = 0,
                     home: Optional[Dict[str, Any]] = None) -> bool:
    """Put a pooled NPC back into the world at a place. True on success.

    The same bookkeeping ``npc_ops.apply_npc`` stamps after a generated NPC —
    one function later in the chain, because the character sheet itself is
    already there. NO name refresh: renaming a character means moving its
    storage directory and rewriting every row keyed by its name, which is the
    opposite of the cheap re-use this path exists for (see the plan note).

    ``radius_m`` is the slot's home area (spec § E3.1): above 0 the NPC is put
    at a free point around the place instead of into ``room_id`` — see
    ``npc_home.place_npc``, the one helper all three placement paths share.

    ``home`` is the OTHER home shape (§ E3.2): a ready ``npc_home`` dict, in
    practice the painted area of an area slot. It comes with no location at
    all, so the NPC's slot stamp is ``npc_slot_area`` and its
    ``current_location`` is whatever the point turns out to lie in (usually
    nothing).
    """
    from app.core.npc_ops import expiry_stamp
    from app.models.character import (POOLED_STATUS, get_character_profile,
                                      is_temporary_npc,
                                      save_character_profile,
                                      set_character_status)
    if not name or not is_temporary_npc(name):
        return False

    profile = get_character_profile(name) or {}
    # THE SHEET'S OWN LIFETIME DECISION SURVIVES THE POOL, in both non-default
    # modes. `lifetime` is what an admin picked in the config form (Character
    # config → Temporary NPC → Lifetime); pooling keeps every key but the
    # stamp, so a revive must not overwrite that decision with the slot's TTL:
    #
    # * `permanent` — no stamp at all. `npc_permanent` is what stops the sheet
    #   being handed the lifetime it was just relieved of.
    # * `custom` — its OWN hours. Stamping the slot TTL here left the dropdown
    #   saying "3 hours" while the NPC actually died after the slot's 24, and
    #   the disagreement came back on every single revive.
    #
    # Everyone else is stamped exactly as `npc_ops.apply_npc` stamps a fresh
    # NPC: the TTL the caller (slot or wanderer) hands in.
    own_hours = 0.0
    if str(profile.get("lifetime") or "").strip().lower() == "custom":
        try:
            own_hours = float(profile.get("lifetime_hours") or 0)
        except (TypeError, ValueError):
            own_hours = 0.0
    profile["expires_at"] = (
        "" if profile.get("npc_permanent")
        else expiry_stamp(own_hours if own_hours > 0 else ttl_hours))
    profile["npc_slot_role"] = (slot_role or "").strip()
    # BOTH slot stamps are written on every revive, one of them empty: a
    # recycled sheet may carry yesterday's stamp of the OTHER kind (pooling
    # keeps them, so `take_from_pool` can match on the role), and a stale
    # `npc_slot_area` would keep counting towards a wood this NPC has left.
    area_id = str((home or {}).get("area_id") or "").strip()
    profile["npc_slot_location"] = (location_id or "").strip() if slot_role else ""
    profile["npc_slot_area"] = area_id if slot_role else ""
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

    # THE STANDARD SKILL SET, exactly as `apply_npc` writes it for a freshly
    # generated NPC — this is the SECOND way an NPC enters the world, and
    # every sheet pooled before the set existed still carries the old, open
    # repertoire (`searx`/`setlocation`/`act` among them). It overwrites the
    # per-skill configs of this NPC, which is the accepted price: a temporary
    # NPC's repertoire is template data, not something an admin tunes per
    # sheet. Before the gate, so a sheet held back for its portrait comes back
    # with the same verbs as one that walks straight in.
    from app.core.npc_ops import activate_default_skills
    activate_default_skills(name, str(profile.get("template") or ""))

    # THE FINISH GATE (plan-npc-leben § 0 A), before the NPC is back in the
    # roster: a pooled sheet may be missing its portrait or its mesh, and an
    # unfinished NPC is not put on the map. TRUE for the caller all the same —
    # `npc_spawn.spawn_for_slot` reads False as "the pool did not deliver" and
    # would run the three-turn pipeline for an NPC that is already claimed.
    from app.core.npc_assets import gate_placement
    if gate_placement(name, location_id, room_id, wanderer=wanderer,
                      wander_target=wander_target, radius_m=radius_m,
                      home=home):
        logger.info("Pooled NPC '%s' claimed for %s (role %r) — placed once "
                    "its assets exist", name, location_id or "(nowhere)",
                    slot_role or "-")
        return True

    # Back into the roster BEFORE the placement: the location setter runs the
    # ordinary arrival side effects, and those read the roster.
    set_character_status(name, "")
    if location_id or home:
        from app.core.npc_home import place_npc
        if not place_npc(name, location_id, room_id, radius_m, home):
            # BACK INTO THE POOL, exactly as ``npc_assets._place`` does it. On
            # "" the sheet is LIVING and positionless: it counts against
            # ``max_alive``, it holds its slot through the stamps written
            # above, and it stands nowhere at all. The caller
            # (``npc_spawn.spawn_for_slot``) reads False as "the pool did not
            # deliver" and runs the generation pipeline for the same slot, so
            # the ghost would come with an LLM bill attached.
            set_character_status(name, POOLED_STATUS)
            logger.warning("revive %s at %s failed — the sheet stays pooled",
                           name, location_id or area_id)
            return False
    logger.info("Pooled NPC '%s' revived at %s (role %r)",
                name, location_id or area_id or "(nowhere)", slot_role or "-")
    return True


# ---------------------------------------------------------------------------
# Listing (Game-Admin)
# ---------------------------------------------------------------------------

#: Longest ``description`` a pool row carries — it is a hover card, not a
#: character sheet, and the appearance field can run to several paragraphs.
POOL_DESCRIPTION_CHARS = 300


def _pool_description(profile: Dict[str, Any]) -> str:
    """Who this pooled NPC is, in one line: role · standing task · appearance.

    Empty halves are skipped rather than rendered as gaps — a wanderer has no
    slot role, and a sheet the generation turn never finished may carry only
    an appearance.
    """
    parts = [str(profile.get(key) or "").strip()
             for key in ("npc_slot_role", "standing_task",
                         "character_appearance")]
    return " · ".join(p for p in parts if p)[:POOL_DESCRIPTION_CHARS]


def list_pool() -> List[Dict[str, Any]]:
    """One row per pooled NPC for the Game-Admin NPC section.

    ``image_url`` and ``description`` are what make the row readable: a name
    an LLM invented says nothing about who that NPC is, and the pool is the
    only surface these profiles appear on at all. Both come out of the
    profile this loop already reads (``profile_image`` is a profile field),
    so a pooled row still costs exactly one profile lookup.

    The URL is the same ``/characters/<name>/images/<file>`` shape the living
    roster builds (``character_ops.build_present_characters``), percent-
    encoded per segment; "" when there is no portrait, so the UI never has to
    render a broken image.

    ``permanent`` is the row's other invisible state — see the field below.
    """
    from urllib.parse import quote

    from app.models.character import get_character_profile, is_temporary_npc
    from app.models.character import list_pooled_characters
    rows: List[Dict[str, Any]] = []
    for name in list_pooled_characters():
        if not is_temporary_npc(name):
            continue
        profile = get_character_profile(name) or {}
        image = str(profile.get("profile_image") or "").strip()
        rows.append({
            "name": name,
            "template": profile.get("template") or "",
            "role": profile.get("npc_slot_role") or "",
            "standing_task": profile.get("standing_task") or "",
            "reason": profile.get("npc_pooled_reason") or "",
            # KEPT, not stock. `take_from_pool` skips a permanent sheet and
            # `_enforce_pool_cap` never drops one — so it neither leaves the
            # pool by itself nor counts against its size, and the row has to
            # say both. Without it the list showed a sheet that looks like
            # every other one and silently never comes back.
            "permanent": bool(profile.get("npc_permanent")),
            "image_url": (f"/characters/{quote(name, safe='')}/images/"
                          f"{quote(image, safe='')}" if image else ""),
            "description": _pool_description(profile),
        })
    return rows
