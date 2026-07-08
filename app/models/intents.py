"""Vereinheitlichte Intents (plan-intents-unified.md, Phase 1).

EIN Eintrag für alles, was ein Character tun soll/will — vom Menschen gesetzt
(``source=human``, frühere Assignments) oder vom Character (``source=character``:
Versprechen, Retrospect-Ziele). Mit Trigger-Bedingung (now/at_time/at_location/
standing) + optionaler Aktion (meist leer = „bumpen mit Hint", Entscheidung 4).

Phase 1: Datenmodell + CRUD + Migration der alten Assignments. Engine/Prompt/
Erzeugung/Panel folgen in Phase 2+ — daher liest in Phase 1 noch nichts diese
Tabelle (kein Verhaltenswechsel).
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

from app.core.db import get_connection, transaction
from app.core.log import get_logger
from app.core.timeutils import utc_now, utc_now_iso, parse_iso

logger = get_logger("intents")

_VALID_STATUS = {"active", "done", "expired", "cancelled"}
_VALID_SOURCE = {"human", "character"}
_JSON_FIELDS = ("participants", "trigger", "action", "meta")

# Tool-Name → generischer Typ (für Auto-Progress bei zähl-basierten Intents)
TOOL_NAME_MAP = {
    "ImageGeneration": "image",
    "ImageGenerator": "image",
    "WebSearch": "search",
    "SearxSearch": "search",
    "Searx": "search",
    "TalkTo": "talkto",
    "SendNotification": "notification",
    "InstagramPost": "instagram",
    "ExtractKnowledge": "research",
}

_TOOL_LABELS = {
    "image": "Foto generiert",
    "search": "Recherche durchgefuehrt",
    "instagram": "Instagram Post erstellt",
    "talkto": "Gespraech gefuehrt",
    "notification": "Benachrichtigung gesendet",
    "research": "Information extrahiert",
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
    """Tool-Nutzung als Intent-Fortschritt verbuchen.

    Wird nach einem Tool-Lauf (z.B. ImageGeneration) für einen Character mit
    aktiven Intents aufgerufen. Trägt ``count`` Progress-Einträge bei jedem
    aktiven Intent ein, an dem der Character beteiligt ist, und schließt den
    Intent ab, sobald ``target_count`` erreicht ist. Zähl-lose Intents
    (``target_count == 0``) bleiben aktiv — Progress ist dann nur eine Notiz.

    Gibt Info zum zuletzt berührten Intent zurück oder ``None``.
    """
    if count <= 0:
        return None
    active = list_intents(owner=character_name, status="active")
    if not active:
        return None

    label = _TOOL_LABELS.get(tool_type, tool_type)
    result = None
    for it in active:
        parts = dict(it.get("participants") or {})
        p = dict(parts.get(character_name) or {"role": "", "progress": []})
        prog = list(p.get("progress") or [])
        for _ in range(count):
            prog.append({"timestamp": utc_now_iso(), "note": label})
        p["progress"] = prog
        parts[character_name] = p

        target = int(it.get("target_count") or 0)
        completed = target > 0 and len(prog) >= target
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
        logger.info("[%s] Intent auto-progress: %s +%d (%s)",
                    character_name, it["id"], count, label)
    return result


def expire_overdue() -> int:
    """Aktive Intents mit überschrittenem ``expires_at`` auf ``expired`` setzen."""
    now = utc_now()
    n = 0
    for it in list_intents(status="active"):
        exp = (it.get("expires_at") or "").strip()
        if not exp:
            continue
        try:
            if parse_iso(exp) <= now:
                update_intent(it["id"], status="expired")
                n += 1
        except Exception:
            pass
    return n


def migrate_assignments_to_intents() -> int:
    """Idempotent: jede Assignment-Zeile, für die noch KEIN Intent mit gleicher
    id existiert, als Intent (trigger=standing) anlegen. Lässt die assignments-
    Tabelle unangetastet (Phase 1 = kein Verhaltenswechsel)."""
    migrated = 0
    try:
        from app.models import assignments as _asg
        rows = _asg._load_all()
    except Exception as e:
        logger.debug("migrate: load assignments failed: %s", e)
        return 0
    for a in rows or []:
        aid = a.get("id") or ""
        if not aid or get_intent(aid):
            continue
        parts = a.get("participants") or {}
        owner = next(iter(parts.keys()), "") or a.get("character_name", "")
        src = "character" if a.get("source") == "chat" else "human"
        st = {"completed": "done", "expired": "expired"}.get(a.get("status", ""), "active")
        create_intent(
            intent_id=aid, owner=owner, title=a.get("title", ""),
            description=a.get("description", ""), source=src,
            participants=parts, trigger={"kind": "standing"}, action={},
            priority=a.get("priority", 3), status=st,
            location_id=a.get("location_id", ""), target_count=a.get("target_count", 0),
            outfit_hint=a.get("outfit_hint", ""), expires_at=a.get("expires_at") or "",
            meta={"migrated_from": "assignment"})
        migrated += 1
    if migrated:
        logger.info("Intents-Migration: %d Assignment(s) -> intents", migrated)
    return migrated


# ====================================================================
# Engine (Phase 2): Prompt-Block · Character-Marker · Trigger-Anwendung
# ====================================================================

PRIORITY_LABELS = {1: "DRINGEND", 2: "HOCH", 3: "NORMAL", 4: "NIEDRIG", 5: "HINTERGRUND"}

import re as _re


def build_intents_prompt_section(character_name: str) -> str:
    """Prompt-Block der aktiven Intents eines Characters (ersetzt das frühere
    assignments_block). Zeigt laufende Vorhaben/Aufgaben nach Priorität. Leer,
    wenn keine aktiven Intents."""
    if not character_name:
        return ""
    active = list_intents(owner=character_name, status="active")
    if not active:
        return ""
    lines = ["\n== AKTUELLE VORHABEN & AUFGABEN (nach Prioritaet) =="]
    for it in active:
        plabel = PRIORITY_LABELS.get(it.get("priority", 3), "NORMAL")
        lines.append(f"[{plabel}] {it.get('title', '')}")
        if it.get("description"):
            lines.append(f"  → {it['description']}")
        loc_id = it.get("location_id", "")
        if loc_id:
            try:
                from app.models.world import get_location_name
                loc_name = get_location_name(loc_id) or loc_id
            except Exception:
                loc_name = loc_id
            lines.append(f"  → Ort: {loc_name} — dorthin begeben, um es zu erledigen.")
        if it.get("outfit_hint"):
            lines.append(f"  → Outfit: {it['outfit_hint']}")
        part = (it.get("participants") or {}).get(character_name) or {}
        if part.get("role"):
            lines.append(f"  → Deine Rolle: {part['role']}")
        progress = part.get("progress") or []
        target = it.get("target_count", 0)
        if target > 0:
            cnt = len(progress)
            lines.append(f"  → Fortschritt: {cnt} von {target}"
                         + ("  — ZIEL ERREICHT" if cnt >= target else ""))
        elif progress:
            notes = "; ".join(p.get("note", "") for p in progress[-3:])
            lines.append(f"  → Fortschritt: {notes}")
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
    """Parst das ``when=``-Feld des Markers in ein trigger-Dict."""
    w = (when or "standing").strip()
    low = w.lower()
    if low in ("standing", ""):
        return {"kind": "standing"}
    if low == "now":
        return {"kind": "now"}
    if low.startswith("in:"):
        secs = _parse_duration_to_seconds(w[3:])
        if secs > 0:
            from datetime import timedelta
            return {"kind": "at_time",
                    "run_date": (utc_now() + timedelta(seconds=secs)).isoformat()}
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


def parse_and_apply_intent_markers(character_name: str, text: str) -> int:
    """Verarbeitet die Character-Marker einer LLM-Antwort:
      ``[INTENT: <Titel> | <Beschreibung> | when=… | prio=N]`` → neuer Intent
      ``[INTENT_DONE: <id>]``        → Intent abschließen
      ``[INTENT_PROGRESS: <id>|...]`` → Fortschritt notieren
    Gibt die Anzahl verarbeiteter Marker zurück."""
    n = 0
    for m in _MARK_DONE.finditer(text or ""):
        if complete_intent(m.group(1)):
            n += 1
    for m in _MARK_PROG.finditer(text or ""):
        if add_progress(m.group(1), character_name, m.group(2).strip()):
            n += 1
    for m in _MARK_NEW.finditer(text or ""):
        parts = [p.strip() for p in m.group(1).split("|")]
        title = parts[0] if parts else ""
        if not title:
            continue
        desc, when, prio = "", "standing", 3
        for p in parts[1:]:
            if p.lower().startswith("when="):
                when = p.split("=", 1)[1].strip()
            elif p.lower().startswith("prio="):
                try:
                    prio = int(p.split("=", 1)[1].strip())
                except Exception:
                    prio = 3
            elif "=" not in p and not desc:
                desc = p
        trig = _when_to_trigger(when)
        it = create_intent(
            owner=character_name, title=title, description=desc, source="character",
            participants={character_name: {"role": "", "progress": []}},
            trigger=trig, priority=prio,
            location_id=trig.get("location_id", "") if trig.get("kind") == "at_location" else "",
            expires_at=trig.get("run_date", "") if trig.get("kind") == "at_time" else "")
        apply_trigger_on_create(it)
        n += 1
    return n


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
    """Hint-Text, der dem Owner beim Trigger in den Thought-Turn gegeben wird."""
    t = intent.get("title", "")
    d = intent.get("description", "")
    base = f"Dein Vorhaben '{t}' ist jetzt dran" + (f": {d}" if d else "") + "."
    return base + " Entscheide selbst, ob/wie du es umsetzt."


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
