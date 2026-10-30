"""Unified intents (plan-intents-unified.md).

ONE entry for everything a character shall or wants to do — set by a human
(``source=human``) or by the character itself (``source=character``: promises,
long-term goals). With a trigger condition (now/at_time/at_location/standing)
plus an optional action (usually empty = "bump with a hint", decision 4).

Data model + CRUD live here; the engine (prompt block, character markers,
trigger application) follows further down in this module.
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

from app.core.db import get_connection, transaction
from app.core.hooks import emit, get_provider
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


def is_managed_intent(intent: Dict[str, Any]) -> bool:
    """Whether a package owns this action's execution instead of thought turns."""
    provider = get_provider("intent_action_managed")
    return bool(provider and provider(intent))


def apply_repeat_cycle(data: Dict[str, Any]) -> None:
    """Set today's cycle and server-owned GAME stamps, retaining the log."""
    trigger = dict(data.get("trigger") or {})
    if trigger.get("repeat") != "daily":
        return
    now = game_time()
    start = now.start_of_day()
    meta = dict(data.get("meta") or {})
    state = dict(meta.get("repeat_state") or {})
    state.update(day=now.day_key(), log=list(state.get("log") or [])[-14:])
    meta["repeat_state"] = state
    data["meta"] = meta
    data["expires_at"] = (start + GameDuration.of(days=1)).canonical()
    if trigger.get("kind") == "at_time":
        hour, minute = map(int, trigger["at"].split(":"))
        trigger["run_date"] = (start + GameDuration.of(hours=hour, minutes=minute)).canonical()
    else:
        trigger.pop("run_date", None)
    data["trigger"] = trigger


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
    cycle = {"trigger": trig, "meta": m, "expires_at": expires_at}
    apply_repeat_cycle(cycle)
    trig, m, expires_at = cycle["trigger"], cycle["meta"], cycle["expires_at"]
    prio = max(1, min(5, int(priority or 3)))
    try:
        with keyed_lock("intent_execution", iid), transaction() as conn:
            previous = get_intent(iid)
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
        return {}
    intent = get_intent(iid)
    if intent:
        if previous:
            emit("intent_changed", intent=intent, previous=previous)
        else:
            emit("intent_created", intent=intent)
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
    with keyed_lock("intent_execution", intent_id):
        previous = get_intent(intent_id)
        if not previous:
            return None
        if "trigger" in changes and changes["trigger"].get("repeat") == "daily":
            cycle = {**previous, **changes}
            apply_repeat_cycle(cycle)
            changes.update({key: cycle[key] for key in ("trigger", "meta", "expires_at")})
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
            return previous
        sets.append("updated_at=?")
        params.append(utc_now_iso())
        params.append(intent_id)
        try:
            with transaction() as conn:
                written = conn.execute(
                    f"UPDATE intents SET {', '.join(sets)} WHERE id=?", params).rowcount
            if not written:
                return None
        except Exception as e:
            logger.error("update_intent failed: %s", e)
            return None
        intent = get_intent(intent_id)
    if intent:
        emit("intent_changed", intent=intent, previous=previous)
        if ({"trigger", "status", "owner"}.intersection(changes)
                and (intent.get("trigger", {}).get("repeat") == "daily"
                     or previous.get("trigger", {}).get("repeat") == "daily")):
            from app.scheduler.scheduler_manager import get_scheduler_manager
            get_scheduler_manager().remove_job(f"intent_{intent_id}")
            if intent["status"] == "active":
                apply_trigger_on_create(intent)
    return get_intent(intent_id)


def cancel_intent(intent_id: str) -> bool:
    return update_intent(intent_id, status="cancelled") is not None


def complete_intent(intent_id: str) -> bool:
    with keyed_lock("intent_execution", intent_id):
        intent = get_intent(intent_id)
        if not intent:
            return False
        allowed = get_provider("intent_completion_allowed")
        if allowed and not allowed(intent):
            return False
        return update_intent(intent_id, status="done") is not None


def delete_intent(intent_id: str) -> bool:
    with keyed_lock("intent_execution", intent_id):
        previous = get_intent(intent_id)
        if not previous:
            return False
        try:
            with transaction() as conn:
                removed = conn.execute("DELETE FROM intents WHERE id=?", (intent_id,)).rowcount
        except Exception:
            return False
    if removed:
        emit("intent_deleted", intent=previous)
    return bool(removed)


def add_progress(intent_id: str, character: str, note: str) -> Optional[Dict[str, Any]]:
    it = get_intent(intent_id)
    if not it:
        return None
    parts = dict(it.get("participants") or {})
    p = dict(parts.get(character) or {"role": "", "progress": []})
    prog = list(p.get("progress") or [])
    normalized = _normalize_title(note)
    if any(_normalize_title(entry.get("note", "")) == normalized for entry in prog):
        logger.debug("Duplicate intent progress ignored: %s participant=%s", intent_id, character)
        return it
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
               if int(it.get("target_count") or 0) > 0 and not is_managed_intent(it)
               and (not (it.get("meta") or {}).get("progress_type")
                    or it["meta"]["progress_type"] == tool_type)]
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


def expire_intent(intent_id: str, reason: str) -> bool:
    """Expire an active intent and preserve its metadata with the reason."""
    if reason not in {"cap", "deadline", "replaced", "duplicate", "cleanup", "participant_gone"}:
        raise ValueError("Unknown intent expiry reason")
    with keyed_lock("intent_execution", intent_id):
        intent = get_intent(intent_id)
        if not intent or intent["status"] != "active":
            return False
        meta = dict(intent.get("meta") or {})
        meta["expired_reason"] = reason
        return update_intent(intent_id, status="expired", meta=meta) is not None


def expire_intents_involving(name: str) -> int:
    """Expire active plans owned by or involving a departing participant.

    A managed intent (a package runs its action, e.g. a shared trip) is left
    to that package: it ends its own rows when a participant leaves.
    """
    folded_name = name.casefold()
    expired = 0
    for intent in list_intents(owner=name, status="active"):
        if is_managed_intent(intent):
            continue
        if (intent["owner"].casefold() == folded_name
                or any(participant.casefold() == folded_name
                       for participant in (intent.get("participants") or {}))):
            if expire_intent(intent["id"], "participant_gone"):
                expired += 1
    return expired


def _cap_class(intent: Dict[str, Any]) -> str:
    if is_managed_intent(intent):
        return ""
    origin = (intent.get("meta") or {}).get("origin")
    if origin and origin != "marker":
        return ""
    return "player" if intent.get("source") == "human" else "self"


def _intent_setting(key: str, default: int) -> int:
    from app.core import config
    try:
        return max(0, int(config.get(f"intents.{key}", default)))
    except (TypeError, ValueError):
        return default


def _cap_victims(active: List[Dict[str, Any]], keep_ids=()) -> List[Dict[str, Any]]:
    """Select cap evictions for enforcement and previews: protected last,
    then fixed-time last, then worst priority and oldest first.
    """
    victims = []
    protected = set(keep_ids)
    for cap_class, default in (("self", 6), ("player", 4)):
        cap = _intent_setting(f"max_active_{cap_class}", default)
        if not cap:
            continue
        candidates = [it for it in active if _cap_class(it) == cap_class]
        candidates.sort(key=lambda it: (it["id"] in protected,
                                        (it.get("trigger") or {}).get("kind") == "at_time",
                                        -it["priority"], it["created_at"], it["id"]))
        victims.extend(candidates[:max(0, len(candidates) - cap)])
    return victims


def enforce_active_caps(owner: str, keep_ids=()) -> int:
    """Expire excess owned plans, fixed-time last, then worst priority and oldest first.

    Protected ids are evicted only after all other candidates in their class.
    A zero cap leaves that class unlimited; package-managed plans are exempt.
    """
    expired = 0
    with keyed_lock("intents", owner):
        active = [it for it in list_intents(owner=owner, status="active")
                  if it["owner"] == owner]
        for it in _cap_victims(active, keep_ids):
            if expire_intent(it["id"], "cap"):
                expired += 1
                logger.info("Intent expired (cap): %s owner=%s title=%r",
                            it["id"], owner, it["title"])
    return expired


def cleanup_intents(owner: str = "", *, merge_duplicates: bool = True,
                    set_deadlines: bool = True, end_all: bool = False,
                    dry_run: bool = True) -> Dict[str, Any]:
    """Preview or apply cleanup of owned active plans, locked per owner.

    Merge and deadline changes affect only marker/legacy rows. End-all also
    expires admin/package rows, but always leaves managed actions alone.
    Preview simulates caps after duplicate removal without writing anything.
    """
    if end_all and not owner:
        raise ValueError("Ending all open plans requires an owner")
    items: List[Dict[str, Any]] = []
    counts: Dict[str, int] = {}

    def record(intent, action, **extra):
        items.append({"id": intent["id"], "owner": intent["owner"],
                      "title": intent["title"], "action": action, **extra})
        counts[action] = counts.get(action, 0) + 1

    def expire(intent, reason):
        # A row that stopped being active meanwhile (done in a turn, expired
        # by the tick) is simply not reported; the rest of the run goes on.
        if dry_run or expire_intent(intent["id"], reason):
            record(intent, reason)

    owners = [owner] if owner else sorted({it["owner"] for it in list_intents(status="active")})
    for name in owners:
        with keyed_lock("intents", name):
            active = sorted((it for it in list_intents(owner=name, status="active")
                             if it["owner"] == name), key=lambda it: it["id"])
            removed = set()
            if end_all:
                for it in active:
                    if not is_managed_intent(it):
                        expire(it, "cleanup")
                        removed.add(it["id"])
            else:
                eligible = [it for it in active if _cap_class(it)]
                if merge_duplicates:
                    groups: Dict[str, List[Dict[str, Any]]] = {}
                    for it in eligible:
                        title = _normalize_title(it["title"])
                        if title:
                            groups.setdefault(title, []).append(it)
                    for group in groups.values():
                        keep = max(group, key=lambda it: (it["created_at"], it["id"]))
                        for it in group:
                            if it["id"] != keep["id"]:
                                expire(it, "duplicate")
                                removed.add(it["id"])
                if set_deadlines:
                    for it in eligible:
                        if it["id"] in removed or it.get("expires_at"):
                            continue
                        deadline = default_intent_expiry(it.get("trigger") or {}, it["source"])
                        if deadline and (dry_run or update_intent(it["id"], expires_at=deadline)):
                            record(it, "deadline", expires_at=deadline)
            remaining = [it for it in active if it["id"] not in removed]
            victims = _cap_victims(remaining)
            if dry_run:
                for it in victims:
                    record(it, "cap")
            else:
                enforce_active_caps(name)
                for it in victims:
                    current = get_intent(it["id"])
                    if current and current["status"] == "expired" and current["meta"].get("expired_reason") == "cap":
                        record(it, "cap")
    return {"dry_run": dry_run, "items": items, "counts": counts}


def expire_overdue() -> int:
    """Active intents whose ``expires_at`` has passed are set to ``expired``.

    ``expires_at`` is a canonical GAME-time stamp (an at_time trigger's
    ``run_date`` plus grace, a character's own plan's lifetime from
    ``default_intent_expiry``, or an admin's ``duration_minutes``) — compare against
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
                if expire_intent(it["id"], "deadline"):
                    n += 1
        except Exception:
            pass
    return n


def renew_repeating(intent_id: str = "") -> int:
    """Reopen closed daily cycles, optionally for one row before an admin edit."""
    today = game_time().day_key()
    renewed = 0
    candidates = [get_intent(intent_id)] if intent_id else list_intents()
    for candidate in candidates:
        if not candidate or (candidate.get("trigger") or {}).get("repeat") != "daily":
            continue
        with keyed_lock("intent_execution", candidate["id"]):
            intent = get_intent(candidate["id"])
            if (not intent or intent["status"] not in {"active", "done", "expired"}
                    or intent["trigger"].get("repeat") != "daily"):
                continue
            meta = dict(intent.get("meta") or {})
            state = meta.get("repeat_state") or {}
            if state.get("day") == today:
                continue
            log = list(state.get("log") or [])
            parts = intent.get("participants") or {}
            if state.get("day"):
                log.append({"day": state["day"],
                            "result": "done" if intent["status"] == "done" else "missed",
                            "count": max((len(p.get("progress") or []) for p in parts.values()), default=0)})
            meta["repeat_state"] = {"day": today, "log": log[-14:]}
            meta.pop("expired_reason", None)
            parts = {name: {**part, "progress": []} for name, part in parts.items()}
            if update_intent(intent["id"], status="active", participants=parts,
                             trigger=intent["trigger"], meta=meta):
                renewed += 1
    return renewed


# ====================================================================
# Engine (Phase 2): prompt block, character marker and trigger application.
# ====================================================================

PRIORITY_LABELS = {1: "URGENT", 2: "HIGH", 3: "NORMAL", 4: "LOW", 5: "BACKGROUND"}

import re as _re


DEFAULT_PROMPT_MAX_ENTRIES = 12


def build_intents_prompt_section(character_name: str, max_entries: Optional[int] = None) -> str:
    """Prompt block of active intents and today's completed daily tasks.

    Every entry carries its ``(id <8-hex>)`` — the id is what
    ``[INTENT_PROGRESS: <id> | …]`` / ``[INTENT_DONE: <id>]`` need, and a model
    that never sees it cannot use either marker. ``max_entries > 0`` caps the
    list by ENTRIES (never mid-entry); the rest is summed up in one line.
    Completed daily tasks stay visible for their current day only.
    """
    if not character_name:
        return ""
    active = list_intents(owner=character_name, status="active")
    today = game_time().day_key()
    active += [it for it in list_intents(owner=character_name, status="done")
               if it["trigger"].get("repeat") == "daily"
               and (it.get("meta", {}).get("repeat_state") or {}).get("day") == today]
    active.sort(key=lambda it: it.get("priority", 3))
    if not active:
        return ""
    if max_entries is None:
        max_entries = DEFAULT_PROMPT_MAX_ENTRIES
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
        if (it.get("trigger") or {}).get("repeat") == "daily":
            today = (f"{len(progress)} of {target}" if target > 0
                     else "done" if it["status"] == "done" else "open")
            lines.append(f"  → Daily task — comes back every day; today: {today}")
        elif target > 0:
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
    """'2h' / '30m' / '1d' / '90' to seconds; invalid input returns zero."""
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
    if low.startswith("at:"):
        match = _re.fullmatch(r"at:(?:(tomorrow|\+(\d{1,2})d)\s+)?(\d{1,2}):(\d{2})", low)
        if not match:
            return {"kind": "standing"}
        day, offset, hour, minute = match.groups()
        hour, minute = int(hour), int(minute)
        days = 1 if day == "tomorrow" else int(offset or 0)
        if hour > 23 or minute > 59 or days > 30:
            return {"kind": "standing"}
        now = game_time()
        run_at = now.start_of_day() + GameDuration.of(days=days, hours=hour, minutes=minute)
        if day is None and run_at <= now:
            run_at += GameDuration.of(days=1)
        return {"kind": "at_time", "run_date": run_at.canonical()}
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

    Both titles are normalized (lowercase, punctuation dropped) and compared
    as word sets, independent of order. A duplicate has equal word sets or
    all words of the shorter title in the longer ("bread buy" in
    "buy bread at the market") — and only when the
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
        if set(shorter.split()) <= set(longer.split()):
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


def default_intent_expiry(trigger: Dict[str, Any], source: str) -> str:
    """The canonical GAME-time deadline for a newly proposed intent.

    at_time (any source): run_date + one game hour of grace. A character's own
    plan (``source="character"``): now -> +1 game hour, standing/at_location ->
    +``intents.self_intent_ttl_days`` game days. Player tasks use configurable
    lifetimes of one (now) or seven (standing/at_location) game days.
    """
    kind = trigger.get("kind", "standing")
    if kind == "at_time":
        run = trigger.get("run_date", "")
        try:
            return (GameTime.parse(run) + _AT_TIME_GRACE).canonical() if run else ""
        except Exception:
            return run
    if source == "human":
        key = "player_task_now_ttl_days" if kind == "now" else "player_task_ttl_days"
        days = _intent_setting(key, 1 if kind == "now" else 7)
        return (game_time() + GameDuration.of(days=days)).canonical() if days else ""
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


def create_own_intent(character_name: str, title: str, *, description: str = "",
                      trigger: Optional[Dict[str, Any]] = None, priority: int = 3,
                      source: str = "character",
                      extra_participants: Optional[Dict[str, Any]] = None
                      ) -> Optional[Dict[str, Any]]:
    """Create an own plan with duplicate protection, caps and trigger scheduling."""
    trig = trigger or {"kind": "standing"}
    with keyed_lock("intents", character_name):
        dup = find_duplicate(character_name, title)
        if dup:
            logger.info("[%s] Intent not created, duplicate of %s %r: %r",
                        character_name, dup.get("id"), dup.get("title"), title)
            return None
        it = create_intent(
            owner=character_name, title=title, description=description, source=source,
            participants={character_name: {"role": "", "progress": []},
                          **(extra_participants or {})},
            trigger=trig, priority=priority,
            location_id=trig.get("location_id", "") if trig.get("kind") == "at_location" else "",
            expires_at=default_intent_expiry(trig, source), meta={"origin": "marker"})
        if it:
            enforce_active_caps(character_name, keep_ids=(it["id"],))
    apply_trigger_on_create(it)
    return it


def complete_intent_as(character_name: str, intent_id: str) -> bool:
    """Complete an intent only as its owner or a participant."""
    if _takes_part(get_intent(intent_id), character_name):
        return complete_intent(intent_id)
    logger.info("[%s] INTENT_DONE ignored: %s is not an intent of this character",
                character_name, intent_id)
    return False


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
        complete_intent_as(character_name, iid)
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
        it = create_own_intent(character_name, title, description=desc,
                               trigger=trig, priority=prio, source=source)
        if it:
            created.append(it)
    return created


def strip_intent_markers(text: str) -> str:
    """Remove [INTENT*] markers before the text is saved in chat history."""
    t = _MARK_NEW.sub("", text or "")
    t = _MARK_DONE.sub("", t)
    t = _MARK_PROG.sub("", t)
    return t


def apply_trigger_on_create(intent: Dict[str, Any]) -> None:
    """Apply a new intent's trigger:
      now      → bump the owner immediately with a hint
      at_time  → schedule a job to bump the owner at that game time
      at_location/standing → passive (room-entry hook or prompt block)."""
    if not intent or is_managed_intent(intent):
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
            if trig.get("repeat") == "daily" and (
                    intent.get("status") != "active"
                    or GameTime.parse(trig["run_date"]) <= game_time()):
                return
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
    return (base + " Decide for yourself whether and how you carry it out."
            + " If you carry it out this turn, end your response with "
            + f"[INTENT_DONE: {intent.get('id', '')}].")


def fire_location_intents(character_name: str, location_id: str) -> int:
    """Bump the owner of active ``at_location`` plans matching this arrival.

    Return the number of matching intents."""
    if not (character_name and location_id):
        return 0
    n = 0
    try:
        from app.core.agent_loop import get_agent_loop
        for it in list_intents(owner=character_name, status="active"):
            if is_managed_intent(it):
                continue
            trig = it.get("trigger") or {}
            if trig.get("kind") == "at_location" and trig.get("location_id") == location_id:
                get_agent_loop().bump(character_name, hint=_intent_hint(it))
                n += 1
    except Exception as e:  # noqa: BLE001
        logger.debug("fire_location_intents failed: %s", e)
    return n
