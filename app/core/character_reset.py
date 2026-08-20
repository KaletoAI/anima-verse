"""Character reset — the ONE place that erases a character's own past.

Two callers, two scopes, one implementation and one declarative store list:

``memory``
    The Game-Admin "Wipe memory" button. Erases everything the character
    *derived* about its own past in THIS world — memories, summaries, diary,
    the whole day timeline (mood/state history, thoughts, action log) and the
    consolidation cursor. Correspondence (``chat_messages``) and the shared
    room record (``utterances``/``scenes``) stay: they are not derived, and
    the room stream is other minds' truth as much as this character's.

``reinit``
    The character import's "Fresh start" (re-initialize). Everything ``memory``
    erases PLUS every other world-bound store: correspondence, knowledge,
    relationships in BOTH directions, obligations, schedules, party/group/story
    membership, the explored map, notifications, the Retrospect soul files —
    and the mechanical state, which falls back to the profile's own values.

Doctrine (why a store is on a list or not)
------------------------------------------
Re-init means "this character starts fresh in THIS world".

* Their OWN memory, relations and history go. A relationship edge is the
  character's own record of a bond, so a re-init drops it in both directions —
  the fixation on a rival from the previous world is exactly what must not
  survive.
* WORLD facts about them held by OTHERS stay. Another character's memories,
  another character's daily summary about them (``summaries.partner``), the
  utterances they spoke into a room that others heard — other minds are not
  this character's state, and erasing them would rewrite somebody else's past.
* Mechanical state (position, room, activity, pose) resets to the imported
  profile's values instead of being carried over.
* Identity stays: profile, soul/personality, outfits, inventory, secrets,
  daily routine, gallery.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from app.core.log import get_logger

logger = get_logger("character_reset")

#: The two scopes, widest last.
SCOPE_MEMORY = "memory"
SCOPE_REINIT = "reinit"
SCOPES: Tuple[str, ...] = (SCOPE_MEMORY, SCOPE_REINIT)

#: Retrospect writes these three soul files from lived experience — they are
#: accumulated world history in file form, not authored identity, and they are
#: the one carrier the read-side dangling filter can never see (free prose, no
#: character reference to match on). A re-init resets them to an empty
#: scaffold; ``personality``/``presence``/``roleplay_rules``/``soul``/``tasks``
#: are authored and stay untouched.
RETROSPECT_SOUL_FILES: Tuple[str, ...] = ("beliefs", "lessons", "goals")


@dataclass(frozen=True)
class Store:
    """One erasable per-character store.

    ``where`` is a WHERE clause over ``table`` and ``params`` names how often
    the character name is bound into it. ``json_column`` marks the stores whose
    character link lives inside a JSON list — those cannot be deleted by a
    plain column match and are handled by their own pruner.
    """
    key: str
    table: str
    where: str
    scopes: Tuple[str, ...]
    what: str
    params: int = 1
    json_column: str = ""


#: The store table. Everything a re-init or a memory wipe touches is here —
#: adding a per-character table means adding one row, not editing two wipes.
STORES: Tuple[Store, ...] = (
    # ── derived memory ────────────────────────────────────────────────────
    Store("memories", "memories", "character_name=?", SCOPES,
          "tiered memories (episodic/daily/weekly/relationship)"),
    Store("summaries", "summaries", "character_name=?", SCOPES,
          "own daily/weekly/season summaries — rows where this character is "
          "another one's `partner` are that character's summary and stay"),
    Store("diary_entries", "diary_entries", "character_name=?", SCOPES,
          "persisted daily recaps (the diary timeline)"),
    Store("thoughts", "thoughts", "character_name=?", SCOPES,
          "private thought journal"),
    Store("mood_history", "mood_history", "character_name=?", SCOPES,
          "mood time series (diary lane)"),
    Store("state_history", "state_history", "character_name=?", SCOPES,
          "location/activity/outfit changes — the day timeline itself"),
    Store("evolution_history", "evolution_history", "character_name=?", SCOPES,
          "personality/soul snapshots and diffs"),
    Store("character_action_log", "character_action_log", "character_name=?", SCOPES,
          "storyteller action log"),
    # ── world-bound state, re-init only ───────────────────────────────────
    Store("chat_messages", "chat_messages", "character_name=? OR partner=?",
          (SCOPE_REINIT,), "1:1 correspondence, both as owner and as partner",
          params=2),
    Store("perceptions", "perceptions", "perceiver=?", (SCOPE_REINIT,),
          "what this character heard (the utterances themselves stay — "
          "they are the room's record, which other characters share)"),
    Store("knowledge", "knowledge", "character_name=?", (SCOPE_REINIT,),
          "facts learned in the previous world"),
    Store("relationships", "relationships", "from_char=? OR to_char=?",
          (SCOPE_REINIT,),
          "relationship edges in BOTH directions — a rival from the previous "
          "world lives here", params=2),
    Store("assignments", "assignments", "character_name=?", (SCOPE_REINIT,),
          "open tasks"),
    Store("scheduler_jobs", "scheduler_jobs", "character_name=?", (SCOPE_REINIT,),
          "scheduled actions bound to old places/times"),
    Store("stories", "stories", "character_name=?", (SCOPE_REINIT,),
          "generated stories"),
    Store("events", "events", "character_name=?", (SCOPE_REINIT,),
          "world events anchored on this character"),
    Store("party_invites", "party_invites", "inviter=? OR invitee=?",
          (SCOPE_REINIT,), "pending party invitations", params=2),
    Store("explored_cells", "explored_cells", "character_id=?", (SCOPE_REINIT,),
          "fog-of-war cells of the previous world"),
    Store("telegram_mapping", "telegram_mapping", "character_name=? OR avatar=?",
          (SCOPE_REINIT,), "Telegram chat bindings of the previous world",
          params=2),
    # ── JSON-participant stores: pruned, not deleted ──────────────────────
    Store("intents", "intents", "", (SCOPE_REINIT,),
          "intents owned by or naming this character", json_column="participants"),
    Store("story_arcs", "story_arcs", "", (SCOPE_REINIT,),
          "membership in story arcs", json_column="participants"),
    Store("group_chats", "group_chats", "", (SCOPE_REINIT,),
          "membership in group chats", json_column="participants"),
    Store("parties", "parties", "", (SCOPE_REINIT,),
          "party membership / leadership", json_column="members"),
    Store("notifications", "notifications", "", (SCOPE_REINIT,),
          "notifications about this character", json_column="meta"),
)

#: Stores a scope deliberately leaves alone, with the reason. Reported back so
#: the caller (and the import result) can SAY what survived.
KEPT: Dict[str, Tuple[str, ...]] = {
    SCOPE_MEMORY: (
        "chat_messages — correspondence, not derived memory",
        "utterances / scenes — the room's shared record",
        "knowledge, relationships, secrets — identity, not day history",
        "inventory, outfits, gallery, daily routine",
    ),
    SCOPE_REINIT: (
        "utterances — this character's speech acts are the room's record and "
        "other characters' perception history references them",
        "scenes — shared room truth of ALL participants",
        "summaries where this character is another one's `partner` — that is "
        "the other character's memory of them",
        "other characters' memories mentioning them — other minds are not "
        "this character's state",
        "profile, soul/personality, secrets, daily routine — identity",
        "inventory, equipped pieces, outfit sets, gallery metadata",
    ),
}


def stores_for(scope: str) -> List[Store]:
    """Every store the given scope erases, in table order."""
    if scope not in SCOPES:
        raise ValueError(f"unknown reset scope: {scope!r} (expected one of {SCOPES})")
    return [s for s in STORES if scope in s.scopes]


def restore_skip_tables() -> frozenset:
    """Exported tables a re-init import must NOT restore from the pack.

    Derived from the same store table the wipe uses, so a pack can never
    re-seed what a re-init just decided to drop — the failure mode that let an
    old rival ride back in on the character's own export.
    """
    skip = {s.table for s in STORES if SCOPE_REINIT in s.scopes and not s.json_column}
    # Mechanical state resets to the profile's values instead of the pack's.
    skip.add("character_state")
    return frozenset(skip)


# ---------------------------------------------------------------------------
# Pruners for the JSON-participant stores
# ---------------------------------------------------------------------------

def _prune_json_members(conn, store: Store, character_name: str) -> int:
    """Drop the character from a JSON participant list; delete rows that are
    only about them. Returns the number of rows changed or removed."""
    import json as _json

    id_col = {
        "intents": "id",
        "story_arcs": "id",
        "group_chats": "id",
        "parties": "party_id",
        "notifications": "id",
    }[store.table]

    if store.table == "notifications":
        return _prune_notifications(conn, character_name)

    extra = ", owner" if store.table == "intents" else (
        ", leader" if store.table == "parties" else "")
    rows = conn.execute(
        f"SELECT {id_col}, {store.json_column}{extra} FROM {store.table}"
    ).fetchall()
    lowered = character_name.strip().lower()
    touched = 0
    for row in rows:
        row_id, raw = row[0], row[1]
        owner = (row[2] or "").strip().lower() if extra else ""
        try:
            members = _json.loads(raw or "[]")
        except Exception:
            members = []
        # `intents.participants` is a dict {role: name}; everything else a list.
        if isinstance(members, dict):
            names = [str(v) for v in members.values()]
        elif isinstance(members, list):
            names = [str(v) for v in members]
        else:
            names = []
        involved = lowered in {n.strip().lower() for n in names}
        if not involved and owner != lowered:
            continue
        # Owner/leader is this character, or nobody else is left → the row is
        # only about them.
        rest = [n for n in names if n.strip().lower() != lowered]
        if owner == lowered or not rest:
            conn.execute(f"DELETE FROM {store.table} WHERE {id_col}=?", (row_id,))
            touched += 1
            continue
        if isinstance(members, dict):
            new_members: Any = {k: v for k, v in members.items()
                                if str(v).strip().lower() != lowered}
        else:
            new_members = rest
        conn.execute(
            f"UPDATE {store.table} SET {store.json_column}=? WHERE {id_col}=?",
            (_json.dumps(new_members, ensure_ascii=False), row_id))
        touched += 1
    return touched


def _prune_notifications(conn, character_name: str) -> int:
    """Notifications name their character in `title` and in `meta.character`
    — neither is a column a plain sweep can see."""
    import json as _json

    lowered = character_name.strip().lower()
    rows = conn.execute("SELECT id, title, meta FROM notifications").fetchall()
    removed = 0
    for row_id, title, meta in rows:
        hit = (title or "").strip().lower() == lowered
        if not hit:
            try:
                hit = str((_json.loads(meta or "{}") or {}).get("character") or
                          "").strip().lower() == lowered
            except Exception:
                hit = False
        if hit:
            conn.execute("DELETE FROM notifications WHERE id=?", (row_id,))
            removed += 1
    return removed


# ---------------------------------------------------------------------------
# Non-table steps
# ---------------------------------------------------------------------------

def _reset_day_cursor(character_name: str) -> str:
    """Cursor to NOW + clear the sleep flags, so already-collapsed old scenes
    are not re-consolidated into fresh day entries after the wipe."""
    try:
        from app.core import day_consolidation as _dc
        from app.core.timeutils import utc_now
        _dc.set_cursor(character_name, utc_now().isoformat(timespec="seconds"))
        _dc._kv_set(f"sleep_start:{character_name}", "")
        _dc._kv_set(f"woke_main_sleep:{character_name}", "")
        return "reset"
    except Exception as e:
        logger.error("reset [%s]: day cursor failed: %s", character_name, e)
        return "error"


def _reset_retrospect_soul_files(character_name: str) -> int:
    """Rewrite beliefs/lessons/goals as an empty scaffold and forget the last
    retrospect stamp. These files ARE the fixation carrier: Retrospect writes
    lines like "About others: …" from lived experience, the export ships them
    verbatim under ``files/soul/``, and nothing downstream can filter free
    prose the way the dangling filter filters a relationship row."""
    from app.core.soul_writer import rewrite_file
    from app.models.character import get_character_language

    try:
        language = get_character_language(character_name)
    except Exception:
        language = "en"
    done = 0
    for file_id in RETROSPECT_SOUL_FILES:
        try:
            rewrite_file(character_name, file_id, [], language=language)
            done += 1
        except Exception as e:
            logger.error("reset [%s]: soul/%s rewrite failed: %s",
                         character_name, file_id, e)
    try:
        from app.core.db import transaction
        with transaction() as conn:
            conn.execute("DELETE FROM world_kv WHERE key=?",
                         (f"retrospect.last_at:{character_name}",))
    except Exception as e:
        logger.debug("reset [%s]: retrospect stamp: %s", character_name, e)
    return done


def _reset_mechanical_state(character_name: str) -> str:
    """Drop the character_state row. The profile's own values (start location,
    equipped outfit) take over on the next read, which is exactly what
    "resets to the imported profile's values" means."""
    try:
        from app.core.db import transaction
        with transaction() as conn:
            conn.execute("DELETE FROM character_state WHERE character_name=?",
                         (character_name,))
        return "reset"
    except Exception as e:
        logger.error("reset [%s]: character_state failed: %s", character_name, e)
        return "error"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def reset_character(character_name: str, scope: str = SCOPE_MEMORY) -> Dict[str, Any]:
    """Erase the character's own past at the given scope.

    Returns a per-store count dict plus ``scope`` and ``kept`` (what the scope
    deliberately left alone, in plain words). Never raises for a single failing
    store — one broken table must not leave the rest of the wipe undone.
    """
    if scope not in SCOPES:
        raise ValueError(f"unknown reset scope: {scope!r} (expected one of {SCOPES})")
    name = (character_name or "").strip()
    if not name:
        raise ValueError("character_name required")

    from app.core.db import transaction

    result: Dict[str, Any] = {"character": name, "scope": scope}

    for store in stores_for(scope):
        try:
            with transaction() as conn:
                if store.json_column:
                    result[store.key] = _prune_json_members(conn, store, name)
                else:
                    cur = conn.execute(
                        f"DELETE FROM {store.table} WHERE {store.where}",
                        tuple([name] * store.params))
                    result[store.key] = cur.rowcount if cur.rowcount is not None else 0
        except Exception as e:
            logger.error("reset [%s]: %s failed: %s", name, store.table, e)
            result[store.key] = 0

    result["day_cursor"] = _reset_day_cursor(name)
    if scope == SCOPE_REINIT:
        result["soul_files"] = _reset_retrospect_soul_files(name)
        result["character_state"] = _reset_mechanical_state(name)

    result["kept"] = list(KEPT[scope])
    logger.info("Character reset [%s] scope=%s: %s", name, scope,
                {k: v for k, v in result.items() if k not in ("kept", "character")})
    return result


def describe_scope(scope: str) -> Dict[str, Any]:
    """Machine-readable description of what a scope does — used by the import
    result so a caller can SAY which of the two modes ran and what it meant."""
    if scope not in SCOPES:
        raise ValueError(f"unknown reset scope: {scope!r}")
    return {
        "scope": scope,
        "cleared": [{"store": s.key, "what": s.what} for s in stores_for(scope)],
        "kept": list(KEPT[scope]),
    }
