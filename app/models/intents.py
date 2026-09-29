"""Unified intents (plan-intents-unified.md).

ONE entry for everything a character shall or wants to do — set by a human
(``source=human``) or by the character itself (``source=character``: promises,
retrospect goals). With a trigger condition (now/at_time/at_location/standing)
plus an optional action (usually empty = "bump with a hint", decision 4).

Data model + CRUD live here; the engine (prompt block, character markers,
trigger application) follows further down in this module.
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

from app.core.db import get_connection, transaction
from app.core.keyed_lock import keyed_lock
from app.core.log import get_logger
from app.core.game_time import GameDuration, GameTime
from app.core.timeutils import game_time, utc_now_iso

logger = get_logger("intents")

_VALID_STATUS = {"active", "done", "expired", "cancelled"}
_VALID_SOURCE = {"human", "character"}
_JSON_FIELDS = ("participants", "trigger", "action", "meta")

# Tool name → generic progress type: declared by the skills themselves
# (PROGRESS_TYPE attribute / manifest progress_type — wave 4). The former
# hardcoded map here had already gone stale after tool renames.
def progress_type_for_tool(tool_name: str) -> str:
    try:
        from app.core.dependencies import get_skill_manager
        return get_skill_manager().progress_type_for_tool(tool_name)
    except Exception:
        return ""

_TOOL_LABELS = {
    "image": "photo generated",
    "search": "research done",
    "instagram": "Instagram post created",
    "talkto": "conversation held",
    "notification": "notification sent",
    "research": "information extracted",
}


def _row_to_intent(r) -> Dict[str, Any]:
    d = dict(r)
    for k in _JSON_FIELDS:
        v = d.get(k)
        if isinstance(v, str):
            try:
                d[k] = json.loads(v or "{}")
            except Exception:
                d[k] = {}
    return d


def create_intent(*, owner: str, title: str, description: str = "",
                  source: str = "character",
                  participants: Optional[Dict[str, Any]] = None,
                  trigger: Optional[Dict[str, Any]] = None,
                  action: Optional[Dict[str, Any]] = None,
                  priority: int = 3, status: str = "active",
                  location_id: str = "", target_count: int = 0,
                  outfit_hint: str = "", expires_at: str = "",
                  meta: Optional[Dict[str, Any]] = None,
                  intent_id: str = "") -> Dict[str, Any]:
    iid = intent_id or uuid.uuid4().hex[:8]
    now = utc_now_iso()
    src = source if source in _VALID_SOURCE else "character"
    st = status if status in _VALID_STATUS else "active"
    parts = participants if isinstance(participants, dict) else {}
    trig = trigger if isinstance(trigger, dict) else {"kind": "standing"}
    act = action if isinstance(action, dict) else {}
    m = meta if isinstance(meta, dict) else {}
    prio = max(1, min(5, int(priority or 3)))
    try:
        with transaction() as conn:
            conn.execute(
                "INSERT INTO intents (id, source, owner, participants, title, "
                "description, trigger, action, priority, status, location_id, "
                "target_count, outfit_hint, created_at, updated_at, expires_at, meta) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET source=excluded.source, "
                "owner=excluded.owner, participants=excluded.participants, "
                "title=excluded.title, description=excluded.description, "
                "trigger=excluded.trigger, action=excluded.action, "
                "priority=excluded.priority, status=excluded.status, "
                "location_id=excluded.location_id, target_count=excluded.target_count, "
                "outfit_hint=excluded.outfit_hint, updated_at=excluded.updated_at, "
                "expires_at=excluded.expires_at, meta=excluded.meta",
                (iid, src, owner or "", json.dumps(parts, ensure_ascii=False),
                 title or "", description or "", json.dumps(trig, ensure_ascii=False),
                 json.dumps(act, ensure_ascii=False), prio, st, location_id or "",
                 int(target_count or 0), outfit_hint or "", now, now,
                 expires_at or "", json.dumps(m, ensure_ascii=False)))
        if not intent_id:
            logger.info("Intent created: %s owner=%s title=%r source=%s trigger=%s",
                        iid, owner, title, src, trig.get("kind", "standing"))
    except Exception as e:
        logger.error("create_intent failed: %s", e)
    return get_intent(iid) or {}


def get_intent(intent_id: str) -> Optional[Dict[str, Any]]:
    if not intent_id:
        return None
    try:
        r = get_connection().execute(
            "SELECT * FROM intents WHERE id=?", (intent_id,)).fetchone()
        return _row_to_intent(r) if r else None
    except Exception:
        return None


def list_intents(owner: str = "", status: str = "", source: str = "") -> List[Dict[str, Any]]:
    sql = "SELECT * FROM intents WHERE 1=1"
    params: List[Any] = []
    if owner:
        sql += " AND (owner=? OR participants LIKE ?)"
        params += [owner, f"%{json.dumps(owner, ensure_ascii=False)}%"]
    if status:
        sql += " AND status=?"
        params.append(status)
    if source:
        sql += " AND source=?"
        params.append(source)
    sql += " ORDER BY priority ASC, created_at DESC"
    try:
        rows = get_connection().execute(sql, params).fetchall()
        return [_row_to_intent(r) for r in rows]
    except Exception as e:
        logger.debug("list_intents failed: %s", e)
        return []


def update_intent(intent_id: str, **changes) -> Optional[Dict[str, Any]]:
    if not get_intent(intent_id):
        return None
    allowed = {"source", "owner", "participants", "title", "description",
               "trigger", "action", "priority", "status", "location_id",
               "target_count", "outfit_hint", "expires_at", "meta"}
    sets, params = [], []
    for k, v in changes.items():
        if k not in allowed:
            continue
        if k in _JSON_FIELDS:
            v = json.dumps(v if isinstance(v, (dict, list)) else {}, ensure_ascii=False)
        sets.append(f"{k}=?")
        params.append(v)
    if not sets:
        return get_intent(intent_id)
    sets.append("updated_at=?")
    params.append(utc_now_iso())
    params.append(intent_id)
    try:
        with transaction() as conn:
            conn.execute(f"UPDATE intents SET {', '.join(sets)} WHERE id=?", params)
    except Exception as e:
        logger.error("update_intent failed: %s", e)
    return get_intent(intent_id)


def cancel_intent(intent_id: str) -> bool:
    return update_intent(intent_id, status="cancelled") is not None


def complete_intent(intent_id: str) -> bool:
    return update_intent(intent_id, status="done") is not None


def delete_intent(intent_id: str) -> bool:
    try:
        with transaction() as conn:
            conn.execute("DELETE FROM intents WHERE id=?", (intent_id,))
        return True
    except Exception:
        return False


def add_progress(intent_id: str, character: str, note: str) -> Optional[Dict[str, Any]]:
    it = get_intent(intent_id)
    if not it:
        return None
    parts = dict(it.get("participants") or {})
    p = dict(parts.get(character) or {"role": "", "progress": []})
    prog = list(p.get("progress") or [])
    prog.append({"timestamp": utc_now_iso(), "note": note})
    p["progress"] = prog
    parts[character] = p
    return update_intent(intent_id, participants=parts)


def auto_track_progress(character_name: str, tool_type: str,
                        count: int = 1) -> Optional[Dict[str, Any]]:
    """Book a tool use as progress on the character's COUNTED intents.

    Called after a tool run (e.g. ImageGeneration) for a character with active
    intents. Only intents with a ``target_count > 0`` have progress semantics:
    each gets ``count`` progress entries and is completed once the target is
    reached. Count-less intents (``target_count <= 0`` — every intent an LLM
    marker creates) are left alone; booking "+1 conversation held" onto all of
    them was pure noise in the prompt.

    Returns info about the last touched intent, or ``None``.
    """
    if count <= 0:
        return None
    counted = [it for it in list_intents(owner=character_name, status="active")
               if int(it.get("target_count") or 0) > 0]
    if not counted:
        return None

    label = _TOOL_LABELS.get(tool_type, tool_type)
    result = None
    for it in counted:
        parts = dict(it.get("participants") or {})
        p = dict(parts.get(character_name) or {"role": "", "progress": []})
        prog = list(p.get("progress") or [])
        for _ in range(count):
            prog.append({"timestamp": utc_now_iso(), "note": label})
        p["progress"] = prog
        parts[character_name] = p

        target = int(it.get("target_count") or 0)
        completed = len(prog) >= target
        update_intent(it["id"], participants=parts,
                      **({"status": "done"} if completed else {}))
        if completed:
            logger.info("Intent auto-completed: %s '%s' (%d/%d)",
                        it["id"], it.get("title"), len(prog), target)
        result = {
            "intent_id": it["id"],
            "title": it.get("title", ""),
            "progress_count": len(prog),
            "target_count": target,
            "completed": completed,
        }
    logger.info("[%s] Intent auto-progress: %d counted intent(s) +%d (%s)",
                character_name, len(counted), count, label)
    return result


def expire_overdue() -> int:
    """Active intents whose ``expires_at`` has passed are set to ``expired``.

    ``expires_at`` is a canonical GAME-time stamp (an at_time trigger's
    ``run_date`` plus grace, a character's own plan's lifetime from
    ``_marker_expiry``, or an admin's ``duration_minutes``) — compare against
    the game clock.
    """
    now = game_time()
    n = 0
    for it in list_intents(status="active"):
        exp = (it.get("expires_at") or "").strip()
        if not exp:
            continue
        try:
            if GameTime.parse(exp) <= now:
                update_intent(it["id"], status="expired")
                n += 1
        except Exception:
            pass
    return n


# ====================================================================
# Engine (Phase 2): Prompt-Block · Character-Marker · Trigger-Anwendung
# ====================================================================

PRIORITY_LABELS = {1: "URGENT", 2: "HIGH", 3: "NORMAL", 4: "LOW", 5: "BACKGROUND"}

import re as _re


def build_intents_prompt_section(character_name: str, max_entries: int = 0) -> str:
    """Prompt block of a character's active intents, by priority.

    Every entry carries its ``(id <8-hex>)`` — the id is what
    ``[INTENT_PROGRESS: <id> | …]`` / ``[INTENT_DONE: <id>]`` need, and a model
    that never sees it cannot use either marker. ``max_entries > 0`` caps the
    list by ENTRIES (never mid-entry); the rest is summed up in one line.
    Empty when there are no active intents.
    """
    if not character_name:
        return ""
    active = list_intents(owner=character_name, status="active")
    if not active:
        return ""
    shown = active[:max_entries] if max_entries > 0 else active
    lines = ["\n== CURRENT PLANS & TASKS (by priority) =="]
    for it in shown:
        plabel = PRIORITY_LABELS.get(it.get("priority", 3), "NORMAL")
        lines.append(f"[{plabel}] {it.get('title', '')} (id {it.get('id', '')})")
        if it.get("description"):
            lines.append(f"  → {it['description']}")
        loc_id = it.get("location_id", "")
        if loc_id:
            try:
                from app.models.world import get_location_name
                loc_name = get_location_name(loc_id) or loc_id
            except Exception:
                loc_name = loc_id
            lines.append(f"  → Place: {loc_name} — go there to get it done.")
        if it.get("outfit_hint"):
            lines.append(f"  → Outfit: {it['outfit_hint']}")
        part = (it.get("participants") or {}).get(character_name) or {}
        if part.get("role"):
            lines.append(f"  → Your role: {part['role']}")
        progress = part.get("progress") or []
        target = it.get("target_count", 0)
        if target > 0:
            cnt = len(progress)
            lines.append(f"  → Progress: {cnt} of {target}"
                         + ("  — GOAL REACHED" if cnt >= target else ""))
        elif progress:
            notes = "; ".join(p.get("note", "") for p in progress[-3:])
            lines.append(f"  → Progress: {notes}")
    if len(active) > len(shown):
        lines.append(f"(+{len(active) - len(shown)} more)")
    return "\n".join(lines)


def build_open_intents_brief(character_name: str, max_entries: int = 12) -> str:
    """The compact open-intent list (``<id> | <title>`` per line) for a
    tool-decision prompt, so ``[INTENT_PROGRESS]``/``[INTENT_DONE]`` can name
    an id and a plan that is already open is not created again. Per turn, so
    it belongs in the USER part of that prompt. Empty when nothing is open."""
    if not character_name:
        return ""
    active = list_intents(owner=character_name, status="active")
    if not active:
        return ""
    lines = [f"  {it.get('id', '')} | {it.get('title', '')}"
             for it in active[:max_entries]]
    if len(active) > max_entries:
        lines.append(f"  (+{len(active) - max_entries} more)")
    return "\n".join(lines)


def _parse_duration_to_seconds(s: str) -> int:
    """'2h' / '30m' / '1d' / '90' → Sekunden (0 bei ungültig)."""
    s = (s or "").strip().lower()
    m = _re.match(r"^(\d+)\s*([smhd]?)$", s)
    if not m:
        return 0
    n = int(m.group(1))
    return n * {"": 60, "s": 1, "m": 60, "h": 3600, "d": 86400}[m.group(2)]


def _when_to_trigger(when: str) -> Dict[str, Any]:
    """Parses the marker's ``when=`` field into a trigger dict."""
    w = (when or "standing").strip()
    low = w.lower()
    if low in ("standing", ""):
        return {"kind": "standing"}
    if low == "now":
        return {"kind": "now"}
    if low.startswith("in:"):
        secs = _parse_duration_to_seconds(w[3:])
        if secs > 0:
            # "in 2h" is an in-world delay — run_date is a canonical GAME-time
            # stamp (the scheduler dispatches character jobs on the game clock).
            run_at = game_time() + GameDuration.of(seconds=secs)
            return {"kind": "at_time", "run_date": run_at.canonical()}
        return {"kind": "standing"}
    if low.startswith("at_location:"):
        name = w.split(":", 1)[1].strip()
        loc_id = ""
        try:
            from app.models.world import resolve_location
            obj = resolve_location(name)
            loc_id = obj.get("id", "") if obj else ""
        except Exception:
            loc_id = ""
        if loc_id:
            return {"kind": "at_location", "location_id": loc_id}
    return {"kind": "standing"}


_MARK_NEW = _re.compile(r"\[INTENT:\s*([^\]]+)\]", _re.IGNORECASE)
_MARK_DONE = _re.compile(r"\[INTENT_DONE:\s*(\w+)\s*\]", _re.IGNORECASE)
_MARK_PROG = _re.compile(r"\[INTENT_PROGRESS:\s*(\w+)\s*\|\s*([^\]]+)\]", _re.IGNORECASE)

# Titles shorter than this (normalized) never count as duplicates — neither
# equal nor contained: "Talk" inside "Talk to the harbour master" says nothing.
DUPLICATE_MIN_CHARS = 6
_TITLE_SPLIT_RE = _re.compile(r"[\W_]+", _re.UNICODE)

# A character's own plan without an explicit deadline is not kept forever:
# "now" is over after one game hour, standing/at_location after this many
# game days (config ``intents.self_intent_ttl_days``; 0 = never).
_NOW_TTL = GameDuration.of(hours=1)
# An at_time intent stays open this long past its run_date, so the scheduled
# bump still finds it active.
_AT_TIME_GRACE = GameDuration.of(hours=1)
_DEFAULT_SELF_TTL_DAYS = 3


def _normalize_title(text: str) -> str:
    """Lowercase words separated by single spaces — punctuation, underscores
    and repeated whitespace fold away, word boundaries stay."""
    return " ".join(_TITLE_SPLIT_RE.sub(" ", (text or "").lower()).split())


def find_duplicate(owner: str, title: str) -> Optional[Dict[str, Any]]:
    """The active intent of ``owner`` that already covers ``title``, or None.

    Both titles are normalized word by word (lowercase, punctuation dropped).
    A duplicate is an EQUAL title or one CONTAINED in the other on word
    boundaries ("buy bread" in "buy bread at the market") — and only when the
    shorter of the two has at least ``DUPLICATE_MIN_CHARS`` characters, for
    equality too. Compared against every active intent ``list_intents(owner)``
    returns (owned or taking part), i.e. the same list the prompt shows.

    Check-then-create callers hold ``keyed_lock("intents", owner)`` around this
    call AND the ``create_intent`` that follows, so two turns of the same
    character cannot both pass the check.
    """
    new = _normalize_title(title)
    if len(new) < DUPLICATE_MIN_CHARS or not owner:
        return None
    for it in list_intents(owner=owner, status="active"):
        old = _normalize_title(it.get("title", ""))
        shorter, longer = sorted((new, old), key=len)
        if len(shorter) < DUPLICATE_MIN_CHARS:
            continue
        if shorter == longer or f" {shorter} " in f" {longer} ":
            return it
    return None


def _self_intent_ttl_days() -> int:
    """Configured lifetime of a character's own open-ended plan, in GAME days
    (0 = never expires). Defaults to 3 when unset or unreadable."""
    try:
        from app.core import config
        val = config.get("intents.self_intent_ttl_days")
        if val in (None, ""):
            return _DEFAULT_SELF_TTL_DAYS
        return max(0, int(val))
    except (TypeError, ValueError):
        return _DEFAULT_SELF_TTL_DAYS
    except Exception:  # noqa: BLE001 — a broken config must not block a turn
        return _DEFAULT_SELF_TTL_DAYS


def _marker_expiry(trigger: Dict[str, Any], source: str) -> str:
    """The canonical GAME-time ``expires_at`` a marker-created intent gets.

    at_time (any source): run_date + one game hour of grace. A character's own
    plan (``source="character"``): now -> +1 game hour, standing/at_location ->
    +``intents.self_intent_ttl_days`` game days. A task from the player stays
    open until it is done.
    """
    kind = trigger.get("kind", "standing")
    if kind == "at_time":
        run = trigger.get("run_date", "")
        try:
            return (GameTime.parse(run) + _AT_TIME_GRACE).canonical() if run else ""
        except Exception:
            return run
    if source != "character":
        return ""
    if kind == "now":
        return (game_time() + _NOW_TTL).canonical()
    days = _self_intent_ttl_days()
    if days <= 0:
        return ""
    return (game_time() + GameDuration.of(days=days)).canonical()


def _takes_part(intent: Optional[Dict[str, Any]], character_name: str) -> bool:
    """True when ``character_name`` owns ``intent`` or is one of its participants."""
    if not intent or not character_name:
        return False
    return (intent.get("owner") == character_name
            or character_name in (intent.get("participants") or {}))


def parse_and_apply_intent_markers(character_name: str,
                                   text: str) -> List[Dict[str, Any]]:
    """Applies the character markers of an LLM answer.

      ``[INTENT: <title> | <description> | when=… | prio=N | by=player]``
                                      → new intent
      ``[INTENT_DONE: <id>]``         → complete an intent
      ``[INTENT_PROGRESS: <id>|...]`` → note progress

    ``by=player`` means the other person explicitly asked for it, which is
    exactly what ``source="human"`` records; anything else (and a missing
    ``by=``) is the character's own plan, ``source="character"``. The marker
    grammar itself is taught by ``shared/templates/llm/chat/intent_markers.md``.

    DONE/PROGRESS only touch an intent the character owns or takes part in —
    an id from someone else's list is ignored. A new intent whose title an
    active one already covers (``find_duplicate``) is not created.

    Returns the intents CREATED by this text (in marker order) — the caller
    uses them for the player feedback line.
    """
    created: List[Dict[str, Any]] = []
    for m in _MARK_DONE.finditer(text or ""):
        iid = m.group(1)
        if _takes_part(get_intent(iid), character_name):
            complete_intent(iid)
        else:
            logger.info("[%s] INTENT_DONE ignored: %s is not an intent of this character",
                        character_name, iid)
    for m in _MARK_PROG.finditer(text or ""):
        iid = m.group(1)
        if _takes_part(get_intent(iid), character_name):
            add_progress(iid, character_name, m.group(2).strip())
        else:
            logger.info("[%s] INTENT_PROGRESS ignored: %s is not an intent of this character",
                        character_name, iid)
    for m in _MARK_NEW.finditer(text or ""):
        parts = [p.strip() for p in m.group(1).split("|")]
        title = parts[0] if parts else ""
        if not title:
            continue
        desc, when, prio, source = "", "standing", 3, "character"
        for p in parts[1:]:
            low = p.lower()
            if low.startswith("when="):
                when = p.split("=", 1)[1].strip()
            elif low.startswith("prio="):
                try:
                    prio = int(p.split("=", 1)[1].strip())
                except Exception:
                    prio = 3
            elif low.startswith("by="):
                source = "human" if p.split("=", 1)[1].strip().lower() == "player" \
                    else "character"
            elif "=" not in p and not desc:
                desc = p
        trig = _when_to_trigger(when)
        with keyed_lock("intents", character_name):
            dup = find_duplicate(character_name, title)
            if dup:
                logger.info("[%s] Intent not created, duplicate of %s %r: %r",
                            character_name, dup.get("id"), dup.get("title"), title)
                continue
            it = create_intent(
                owner=character_name, title=title, description=desc, source=source,
                participants={character_name: {"role": "", "progress": []}},
                trigger=trig, priority=prio,
                location_id=trig.get("location_id", "") if trig.get("kind") == "at_location" else "",
                expires_at=_marker_expiry(trig, source))
        apply_trigger_on_create(it)
        if it:
            created.append(it)
    return created


def strip_intent_markers(text: str) -> str:
    """Entfernt die [INTENT*]-Marker aus dem Text (vor dem Speichern in History)."""
    t = _MARK_NEW.sub("", text or "")
    t = _MARK_DONE.sub("", t)
    t = _MARK_PROG.sub("", t)
    return t


def apply_trigger_on_create(intent: Dict[str, Any]) -> None:
    """Wendet den Trigger eines frisch erzeugten Intents an:
      now      → Owner sofort bumpen (mit Hint)
      at_time  → Scheduler-Job, der den Owner zur Zeit bumpt
      at_location/standing → passiv (room_entry-Hook bzw. Prompt-Block)."""
    if not intent:
        return
    trig = intent.get("trigger") or {}
    kind = trig.get("kind", "standing")
    owner = intent.get("owner", "")
    if not owner:
        return
    hint = _intent_hint(intent)
    try:
        if kind == "now":
            from app.core.agent_loop import get_agent_loop
            get_agent_loop().bump(owner, hint=hint)
        elif kind == "at_time" and trig.get("run_date"):
            from app.scheduler.scheduler_manager import get_scheduler_manager
            get_scheduler_manager().add_job(
                agent=owner,
                trigger={"type": "date", "run_date": trig["run_date"], "one_time": True},
                action={"type": "intent_bump", "intent_id": intent.get("id", ""),
                        "hint": hint},
                job_id=f"intent_{intent.get('id', '')}")
    except Exception as e:  # noqa: BLE001
        logger.debug("apply_trigger_on_create failed: %s", e)


def _intent_hint(intent: Dict[str, Any]) -> str:
    """Hint text handed to the owner's thought turn when the trigger fires."""
    t = intent.get("title", "")
    d = intent.get("description", "")
    base = (f"Your plan '{t}' (id {intent.get('id', '')}) is due now"
            + (f": {d}" if d else "") + ".")
    return base + " Decide for yourself whether and how you carry it out."


def fire_location_intents(character_name: str, location_id: str) -> int:
    """``at_location``-Trigger: betritt der Character einen Ort, die passenden
    aktiven Intents anstoßen (Owner bumpen mit Hint). Gibt Anzahl zurück."""
    if not (character_name and location_id):
        return 0
    n = 0
    try:
        from app.core.agent_loop import get_agent_loop
        for it in list_intents(owner=character_name, status="active"):
            trig = it.get("trigger") or {}
            if trig.get("kind") == "at_location" and trig.get("location_id") == location_id:
                get_agent_loop().bump(character_name, hint=_intent_hint(it))
                n += 1
    except Exception as e:  # noqa: BLE001
        logger.debug("fire_location_intents failed: %s", e)
    return n
