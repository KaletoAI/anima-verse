"""Diary / timeline — generated day view per character.

Aggregates data from existing sources (no duplication):
- mood_history → mood changes
- state_history → location/activity/condition/outfit changes
- chat history → thought entries (tool calls, actions)
- instagram feed → posts and comments
- assignments → progress and completions

Only ``daily_summary`` entries are persisted (table ``diary_entries``);
everything else is regenerated on demand.

**A diary day is a GAME day** (plan-game-calendar.md, decision E4). The date of
an entry is a ``day_key`` like ``Y0002-D109``, never a real calendar date — a
diary is in-world content, and the world has no 17th of August. Persisted
entries carry their own canonical stamp (``diary_entries.game_ts``); the
aggregated sources carry SYSTEM stamps only, so the game day is turned into a
SYSTEM window once (``timeutils.system_window_of_game_day``) and every
collector selects against that window instead of matching a date prefix.
"""
import json
import re
import uuid

from app.core.game_time import GameTime
from app.core.timeutils import (game_time, game_time_at, parse_iso,
                                system_window_of_game_day, utc_now_iso)
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.core.log import get_logger
from app.core.db import get_connection, transaction

logger = get_logger("diary")

# SYSTEM window of one game day: (start_iso inclusive, end_iso exclusive).
Window = Tuple[str, str]


def _in_window(ts: Any, window: Window) -> bool:
    """Whether a SYSTEM stamp falls into the window.

    Plain string comparison: both ends are ISO stamps with the same UTC
    offset, so lexicographic order IS chronological order. Sub-second format
    differences (``…:00+00:00`` vs ``…:00.123456+00:00``) can only shift a row
    at the very edge of the window by under a second, which no day boundary
    cares about.
    """
    if not isinstance(ts, str) or not ts:
        return False
    return window[0] <= ts < window[1]


def _game_hhmm(ts: Any) -> str:
    """WORLD clock time of a SYSTEM stamp ("" when unusable).

    The diary shows the hour the world was at, not the hour the server was at.
    """
    gt = game_time_at(ts)
    return gt.time_hhmm() if gt is not None else ""


# ---------------------------------------------------------------------------
# Entry types & icons
# ---------------------------------------------------------------------------

ENTRY_TYPES = {
    "mood":               "Stimmung",
    "location":           "Ortswechsel",
    "activity":           "Aktivitaet",
    "condition":          "Zustand",
    "outfit":             "Outfit",
    "effects":            "Effekte",
    "thought":            "Gedanke",
    "assignment_update":  "Aufgaben-Update",
    "assignment_done":    "Aufgabe erledigt",
    "daily_summary":      "Tagesrueckblick",
    "instagram_post":     "Instagram Post",
    "instagram_comment":  "Instagram Kommentar",
    "forced_action":      "Erzwungen",
    "access_denied":      "Zugang verweigert",
    "event_resolved":     "Ereignis geloest",
    "event_attempt":      "Loesungsversuch",
}

ENTRY_ICONS = {
    "mood":               "\U0001f3ad",   # 🎭
    "location":           "\U0001f4cd",   # 📍
    "activity":           "\u26a1",       # ⚡
    "condition":          "\U0001f525",   # 🔥
    "outfit":             "\U0001f455",   # 👕
    "effects":            "\U0001f4ca",   # 📊
    "thought":            "\U0001f9e0",   # 🧠
    "assignment_update":  "\U0001f4cb",   # 📋
    "assignment_done":    "\u2705",       # ✅
    "daily_summary":      "\U0001f4d6",   # 📖
    "instagram_post":     "\U0001f4f8",   # 📸
    "instagram_comment":  "\U0001f4ac",   # 💬
    "forced_action":      "\u26a0\ufe0f",  # ⚠️
    "access_denied":      "\U0001f6ab",   # 🚫
    "event_resolved":     "\U0001f6a8",   # 🚨
    "event_attempt":      "\U0001f6e0️",  # 🛠️
}


# ---------------------------------------------------------------------------
# Storage (only for daily_summary persistence)
# ---------------------------------------------------------------------------

def _get_diary_path(character_name: str) -> Path:
    from app.models.character import get_character_dir
    return get_character_dir(character_name) / "diary.json"


def _load_stored(character_name: str) -> List[Dict[str, Any]]:
    """Load stored diary entries (currently only daily_summary) from DB."""
    try:
        conn = get_connection()
        rows = conn.execute(
            "SELECT id, ts, game_ts, content, tags, meta FROM diary_entries "
            "WHERE character_name=? ORDER BY ts ASC",
            (character_name,),
        ).fetchall()
        entries = []
        for r in rows:
            meta = {}
            try:
                meta = json.loads(r[5] or "{}")
            except Exception:
                pass
            entry = {
                "id": meta.get("str_id", str(r[0])),
                "type": meta.get("type", "daily_summary"),
                "content": r[3] or "",
                "timestamp": r[1] or "",
                "game_ts": r[2] or "",
                "metadata": meta.get("metadata", {}),
                "_db_id": r[0],
            }
            entries.append(entry)
        return entries
    except Exception as e:
        logger.warning("_load_stored diary DB-Fehler fuer %s: %s", character_name, e)
        # Fallback: JSON-Datei
        path = _get_diary_path(character_name)
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception as exc:
            logger.error("Failed to load diary for %s: %s", character_name, exc)
            return []


def _save_stored(character_name: str, entries: List[Dict[str, Any]]) -> None:
    """Save diary entries to DB and JSON backup."""
    try:
        with transaction() as conn:
            # Load existing db_id -> str_id mapping
            existing_rows = conn.execute(
                "SELECT id, meta FROM diary_entries WHERE character_name=?",
                (character_name,),
            ).fetchall()
            db_to_str: Dict[int, str] = {}
            str_to_db: Dict[str, int] = {}
            for db_id, meta_str in existing_rows:
                try:
                    m = json.loads(meta_str or "{}")
                    str_id = m.get("str_id", str(db_id))
                except Exception:
                    str_id = str(db_id)
                db_to_str[db_id] = str_id
                str_to_db[str_id] = db_id

            new_str_ids = {e.get("id") for e in entries if e.get("id")}

            # Remove deleted entries
            for db_id, str_id in db_to_str.items():
                if str_id not in new_str_ids:
                    conn.execute("DELETE FROM diary_entries WHERE id=?", (db_id,))

            # Upsert
            for entry in entries:
                str_id = entry.get("id")
                if not str_id:
                    continue
                ts = entry.get("timestamp", utc_now_iso())
                game_ts = entry.get("game_ts", "") or ""
                content = entry.get("content", "")
                tags = json.dumps([entry.get("type", "daily_summary")], ensure_ascii=False)
                meta_blob = json.dumps({
                    "str_id": str_id,
                    "type": entry.get("type", "daily_summary"),
                    "metadata": entry.get("metadata", {}),
                }, ensure_ascii=False)

                if str_id in str_to_db:
                    conn.execute(
                        "UPDATE diary_entries SET ts=?, game_ts=?, content=?, "
                        "tags=?, meta=? WHERE id=?",
                        (ts, game_ts, content, tags, meta_blob, str_to_db[str_id]),
                    )
                else:
                    conn.execute(
                        "INSERT INTO diary_entries "
                        "(character_name, ts, game_ts, content, tags, meta) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (character_name, ts, game_ts, content, tags, meta_blob),
                    )
    except Exception as e:
        logger.error("_save_stored diary DB-Fehler fuer %s: %s", character_name, e)


def _day_start_stamp(day_key: str) -> str:
    """Canonical game stamp of a game day's start ("" for a non-day-key)."""
    try:
        return GameTime.parse(f"{day_key}T00:00:00").canonical()
    except (ValueError, TypeError):
        return ""


def resolve_day_key(day_key: Optional[str]) -> str:
    """The game day to work on — the given one, or today's."""
    key = (day_key or "").strip()
    return key or game_time().day_key()


def day_label(day_key: str, lang: str = "en") -> str:
    """Readable world date of a game day ("" for a non-day-key).

    The server renders, clients display — a client never learns the calendar.
    """
    try:
        return GameTime.parse(f"{day_key}T00:00:00").date_label(lang)
    except (ValueError, TypeError):
        return ""


def add_summary(character_name: str, content: str, day_key: str) -> Dict[str, Any]:
    """Store a daily summary (LLM-generated). Only type that gets persisted.

    ``day_key`` is the GAME day the entry is about (``Y0002-D109``); the game
    stamp is that day's start, so the entry sorts and filters with it. The
    system ``timestamp`` records only when the text was written.
    """
    entry = {
        "id": uuid.uuid4().hex[:8],
        "type": "daily_summary",
        "content": content,
        "timestamp": utc_now_iso(),
        "game_ts": _day_start_stamp(day_key) or game_time().canonical(),
        "metadata": {"date": day_key},
    }
    stored = _load_stored(character_name)
    stored.append(entry)
    _save_stored(character_name, stored)
    return entry


def has_daily_summary(character_name: str, day_key: Optional[str] = None) -> bool:
    """Whether a daily summary already exists for that GAME day."""
    key = resolve_day_key(day_key)
    stored = _load_stored(character_name)
    return any(
        e.get("type") == "daily_summary" and (e.get("game_ts") or "").startswith(key)
        for e in stored
    )


# ---------------------------------------------------------------------------
# Source collectors — each returns List[Dict] with type/content/timestamp
# ---------------------------------------------------------------------------

def _collect_mood(character_name: str, window: Window) -> List[Dict[str, Any]]:
    """Mood changes from mood_history DB table."""
    try:
        conn = get_connection()
        rows = conn.execute(
            "SELECT ts, mood FROM mood_history "
            "WHERE character_name=? AND ts>=? AND ts<? ORDER BY ts ASC",
            (character_name, window[0], window[1]),
        ).fetchall()
        result = []
        for r in rows:
            mood = r[1] or ""
            if mood:
                result.append({
                    "type": "mood",
                    "content": f"Stimmung: {mood}",
                    "timestamp": r[0] or "",
                })
        return result
    except Exception as e:
        logger.debug("Mood collect DB error: %s — falling back to JSON", e)
    # Fallback: JSON-Datei
    from app.models.character import get_character_dir
    path = get_character_dir(character_name) / "mood_history.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        entries_raw = data.get("entries", []) if isinstance(data, dict) else data
        result = []
        for e in entries_raw:
            ts = e.get("timestamp", "")
            if not _in_window(ts, window):
                continue
            mood = e.get("mood", "")
            if mood:
                result.append({
                    "type": "mood",
                    "content": f"Stimmung: {mood}",
                    "timestamp": ts,
                })
        return result
    except Exception as e:
        logger.debug("Mood collect error: %s", e)
        return []


def get_state_history(character_name: str,
    entry_type: str = "", limit: int = 20) -> List[Dict[str, Any]]:
    """Gibt die letzten N Eintraege aus state_history zurueck (neueste zuerst).

    entry_type: Filter auf "activity", "location", "condition" etc. Leer = alle.
    """
    try:
        conn = get_connection()
        rows = conn.execute(
            "SELECT ts, state_json FROM state_history "
            "WHERE character_name=? ORDER BY ts DESC LIMIT ?",
            (character_name, limit * 4 if entry_type else limit),
        ).fetchall()
        entries = []
        for r in rows:
            state = {}
            try:
                state = json.loads(r[1] or "{}")
            except Exception:
                pass
            if not state:
                state = {"timestamp": r[0] or "", "type": "", "value": ""}
            if entry_type and state.get("type") != entry_type:
                continue
            entries.append({
                "timestamp": state.get("timestamp", r[0] or ""),
                "type": state.get("type", ""),
                "value": state.get("value", ""),
                "metadata": state.get("metadata", {}),
            })
            if len(entries) >= limit:
                break
        return entries
    except Exception as e:
        logger.debug("get_state_history DB error: %s — falling back to JSON", e)
    # Fallback: JSON-Datei
    from app.models.character import get_character_dir
    path = get_character_dir(character_name) / "state_history.json"
    if not path.exists():
        return []
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
        if entry_type:
            entries = [e for e in entries if e.get("type") == entry_type]
        return list(reversed(entries[-limit:]))
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Diary-Renderer-Registry
# ---------------------------------------------------------------------------
# state_history-types werden ueber Renderer-Funktionen in Diary-Eintraege
# umgewandelt. Neue Types kommen via ``register_diary_renderer`` rein —
# ohne Code-Aenderung in _process_state_entry.
#
# Ein Renderer bekommt (value, meta, ts) und liefert entweder:
#   - dict {type, content, timestamp, [metadata]} → Eintrag landet im Tagebuch
#   - None → Eintrag wird verworfen (z.B. Rauschen wie activity="none")
#
# Unbekannte Types werden via Fallback-Renderer als generischer Eintrag
# gerendert — damit kein neues state_history-Feld stillschweigend im Tagebuch
# verschluckt wird.

DiaryRenderer = "Callable[[str, Dict[str, Any], str], Optional[Dict[str, Any]]]"
_DIARY_RENDERERS: Dict[str, Any] = {}


def register_diary_renderer(state_type: str, renderer) -> None:
    """Registriert einen Renderer fuer einen state_history-Type.

    Mehrfach-Registrierung ueberschreibt — der zuletzt registrierte Renderer
    gewinnt. Fuer Plugins, Tests, oder neue Event-Types.
    """
    if not state_type:
        return
    _DIARY_RENDERERS[state_type] = renderer


# --- Builtin Renderers ------------------------------------------------------

def _render_location(value: str, meta: Dict[str, Any], ts: str) -> Optional[Dict[str, Any]]:
    if not value:
        return None
    loc_name = value
    try:
        from app.models.world import get_location_name
        resolved = get_location_name(value)
        if resolved:
            loc_name = resolved
    except Exception:
        pass
    return {"type": "location", "content": f"Ortswechsel: {loc_name}", "timestamp": ts}


def _render_activity(value: str, meta: Dict[str, Any], ts: str) -> Optional[Dict[str, Any]]:
    # "none"/leere Aktivitaet als Tagebuch-Rauschen rausfiltern — passiert
    # z.B. wenn der Scheduler eine Activity beendet (Reset auf "") oder
    # ein Char zwischen Activities "nichts tut".
    v_lower = (value or "").strip().lower()
    if not v_lower or v_lower in ("none", "null"):
        return None
    detail = meta.get("detail", "") or ""
    partner = meta.get("partner", "") or ""
    display = f"{value} ({detail})" if (detail and detail.lower() != value.lower()) else value
    if partner:
        display = f"{display} mit {partner}"
    entry: Dict[str, Any] = {"type": "activity", "content": f"Aktivitaet: {display}", "timestamp": ts}
    if partner:
        entry["metadata"] = {"partner": partner}
    return entry


def _render_condition(value: str, meta: Dict[str, Any], ts: str) -> Optional[Dict[str, Any]]:
    if not value:
        return None
    source = meta.get("source", "") or ""
    duration = meta.get("duration_hours")
    content = f"Zustand: {value}"
    if duration:
        content += f" ({duration}h)"
    if source:
        content += f" — {source}"
    return {"type": "condition", "content": content, "timestamp": ts, "metadata": meta}


#: Worn-state directions as they read in the timeline.
_OUTFIT_ACTIONS = {"equip": "Put on", "unequip": "Took off"}


def _render_outfit(value: str, meta: Dict[str, Any], ts: str) -> Optional[Dict[str, Any]]:
    """Outfit change (M4) — what was put on/taken off, and by whom.

    ``source`` is the caller context recorded at the equip/unequip call
    (skill / compliance / wardrobe_ui / avatar / …); it is exactly the part
    that used to be missing when asking "why is this character undressed".
    """
    if not value:
        return None
    label = _OUTFIT_ACTIONS.get((meta.get("action") or "").strip(), "Outfit")
    content = f"{label}: {value}"
    displaced = [d for d in (meta.get("displaced") or []) if d]
    if displaced:
        content += f" (replaces {', '.join(displaced)})"
    source = (meta.get("source") or "").strip()
    if source:
        content += f" — {source}"
    return {"type": "outfit", "content": content, "timestamp": ts, "metadata": meta}


def _render_access_denied(value: str, meta: Dict[str, Any], ts: str) -> Optional[Dict[str, Any]]:
    loc_name = meta.get("location_name") or value
    reason = meta.get("reason", "") or ""
    action = meta.get("action", "enter")
    if action == "leave":
        content = f"Wollte {loc_name} verlassen" + (f" — {reason}" if reason else "")
    else:
        content = f"Wollte zu {loc_name}" + (f" — {reason}" if reason else "")
    return {"type": "access_denied", "content": content, "timestamp": ts, "metadata": meta}


def _render_discovery(value: str, meta: Dict[str, Any], ts: str) -> Optional[Dict[str, Any]]:
    if not value:
        return None
    rule_name = (meta.get("rule_name") or "").strip()
    content = f"Entdeckt: {value}"
    if rule_name:
        content += f" — {rule_name}"
    return {"type": "discovery", "content": content, "timestamp": ts, "metadata": meta}


def _render_room(value: str, meta: Dict[str, Any], ts: str) -> Optional[Dict[str, Any]]:
    room_name = (meta.get("name") or value).strip()
    if not room_name:
        return None
    return {"type": "room", "content": f"Raum: {room_name}", "timestamp": ts, "metadata": meta}


# The travel_failed vocabulary of the travel engine. unplaced_target reads
# like unknown_target on purpose: a character cannot tell "nobody ever told
# me about this place" from "this place stands on no map", and the diary is
# written from the character's point of view (the raw reason stays in the
# entry's metadata for anyone debugging the world).
_TRAVEL_FAILED_REASONS = {
    "unknown_target": "does not know the way there",
    "unplaced_target": "does not know the way there",
    "no_route": "no passable route",
}


def _render_travel_failed(value: str, meta: Dict[str, Any], ts: str) -> Optional[Dict[str, Any]]:
    reason = _TRAVEL_FAILED_REASONS.get((meta.get("reason") or "").strip(), "")
    content = f"Journey to {value} called off"
    if reason:
        content += f" — {reason}"
    return {"type": "travel_failed", "content": content, "timestamp": ts, "metadata": meta}


def _render_effects(value: str, meta: Dict[str, Any], ts: str) -> Optional[Dict[str, Any]]:
    changes = meta.get("changes") or {}
    if not changes:
        return None
    entry_meta: Dict[str, Any] = {"changes": changes}
    if meta.get("elapsed_minutes"):
        entry_meta["elapsed_minutes"] = meta["elapsed_minutes"]
    return {"type": "effects", "content": f"Effekte ({value})", "timestamp": ts, "metadata": entry_meta}


# Builtin-Registry — neue Types einfach hier ergaenzen oder via
# register_diary_renderer von ausserhalb registrieren.
register_diary_renderer("location", _render_location)
register_diary_renderer("activity", _render_activity)
register_diary_renderer("condition", _render_condition)
register_diary_renderer("outfit", _render_outfit)
register_diary_renderer("access_denied", _render_access_denied)
register_diary_renderer("discovery", _render_discovery)
register_diary_renderer("room", _render_room)
register_diary_renderer("travel_failed", _render_travel_failed)
register_diary_renderer("effects", _render_effects)


def _render_unknown_fallback(state_type: str, value: str,
                              meta: Dict[str, Any], ts: str) -> Optional[Dict[str, Any]]:
    """Fallback fuer state-types ohne registrierten Renderer.

    Statt None zu returnen (= verschwindet) bauen wir einen Generic-Eintrag,
    damit neue Event-Types sichtbar werden — der Admin sieht im Tagebuch
    sofort wenn ein Type nicht dokumentiert ist.
    """
    if not value:
        return None
    content = f"{state_type}: {value}"
    if meta:
        # Maximal ein paar Meta-Felder mit reinen — Kuerze halten.
        meta_str = ", ".join(f"{k}={v}" for k, v in list(meta.items())[:3]
                              if v not in (None, "", []))
        if meta_str:
            content += f" ({meta_str})"
    logger.debug("Diary-Fallback fuer unbekannten state-type '%s'", state_type)
    return {"type": state_type, "content": content, "timestamp": ts, "metadata": meta}


def _process_state_entry(e: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Verarbeitet einen einzelnen State-History-Eintrag in einen Diary-Eintrag.

    Dispatch via ``_DIARY_RENDERERS``. Unbekannte Types werden ueber den
    Fallback gerendert (statt verworfen), damit nichts im Tagebuch versickert.
    """
    ts = e.get("timestamp", "")
    change_type = e.get("type", "")
    value = e.get("value", "")
    meta = e.get("metadata") or {}
    if not isinstance(meta, dict):
        meta = {}

    renderer = _DIARY_RENDERERS.get(change_type)
    if renderer is None:
        return _render_unknown_fallback(change_type, value, meta, ts)
    try:
        return renderer(value, meta, ts)
    except Exception as ex:
        logger.warning("Diary-Renderer fuer '%s' fehlgeschlagen: %s",
                       change_type, ex)
        return _render_unknown_fallback(change_type, value, meta, ts)


def _collect_state_changes(character_name: str, window: Window,
                           day_key: str) -> List[Dict[str, Any]]:
    """Location and activity changes from state_history DB table.

    Consecutive identical activities (same value + same partner) collapse
    into a single range entry like ``Aktivitaet: Sleeping (22:00 - 06:00)``
    instead of repeating once per hourly tick. Same goes for location
    pings — if a character was at the same location for hours, only one
    entry with the time range is emitted.
    """
    raw_entries = _read_state_history_raw(character_name, window, day_key)
    return _aggregate_state_entries(raw_entries)


def _read_state_history_raw(character_name: str, window: Window,
                            day_key: str) -> List[Dict[str, Any]]:
    """Return raw state_history entries for the game day, oldest first.

    The day is selected on ``game_ts`` — the exact world stamp written with
    the row — not on the back-projected system window: back-projection uses
    the CURRENT anchor and factor, so every speed change would shuffle old
    rows into neighbouring game days. ``window`` is only left for the legacy
    JSON fallback below, whose entries carry no game stamp.
    """
    try:
        conn = get_connection()
        rows = conn.execute(
            "SELECT ts, state_json FROM state_history "
            "WHERE character_name=? AND game_ts LIKE ? ORDER BY game_ts ASC",
            (character_name, f"{day_key}T%"),
        ).fetchall()
        out = []
        for r in rows:
            state = {}
            try:
                state = json.loads(r[1] or "{}")
            except Exception:
                pass
            if not state:
                state = {"timestamp": r[0] or "", "type": "", "value": ""}
            out.append({
                "timestamp": state.get("timestamp", r[0] or ""),
                "type": state.get("type", ""),
                "value": state.get("value", ""),
                "metadata": state.get("metadata") or {},
            })
        return out
    except Exception as e:
        logger.debug("_read_state_history_raw DB error: %s — falling back to JSON", e)

    from app.models.character import get_character_dir
    path = get_character_dir(character_name) / "state_history.json"
    if not path.exists():
        return []
    try:
        raw_entries = json.loads(path.read_text(encoding="utf-8"))
        out = []
        for e in raw_entries:
            ts = e.get("timestamp", "")
            if not _in_window(ts, window):
                continue
            out.append({
                "timestamp": ts,
                "type": e.get("type", ""),
                "value": e.get("value", ""),
                "metadata": e.get("metadata") or {},
            })
        return out
    except Exception as e:
        logger.debug("State history collect error: %s", e)
        return []


def _aggregate_state_entries(raw: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Collapse runs of identical state entries into time-range entries.

    Two entries belong to the same run when:
      - same ``type``
      - same ``value`` (case-insensitive)
      - for ``activity``: same partner (different partners → different runs)

    The collapsed entry keeps the FIRST timestamp (start) and adds
    ``end_timestamp`` from the LAST entry in the run. The diary renderer
    can format that as ``HH:MM - HH:MM``.

    ``effects`` ticks are not collapsed (each one carries unique deltas).
    """
    runs: List[List[Dict[str, Any]]] = []
    for entry in raw:
        if not runs:
            runs.append([entry])
            continue
        last = runs[-1][-1]
        if entry["type"] != last["type"] or entry["type"] == "effects":
            runs.append([entry])
            continue
        # Same type — also compare value case-insensitively.
        if (entry.get("value") or "").strip().lower() != (last.get("value") or "").strip().lower():
            runs.append([entry])
            continue
        # For activity, partners must match.
        if entry["type"] == "activity":
            p1 = (entry.get("metadata") or {}).get("partner", "")
            p2 = (last.get("metadata") or {}).get("partner", "")
            if (p1 or "") != (p2 or ""):
                runs.append([entry])
                continue
        runs[-1].append(entry)

    result: List[Dict[str, Any]] = []
    for run in runs:
        first = run[0]
        last = run[-1]
        processed = _process_state_entry(first)
        if not processed:
            continue
        if len(run) > 1 and last["timestamp"] != first["timestamp"]:
            # Aggregate: keep start, expose end via end_timestamp + content range.
            processed["end_timestamp"] = last["timestamp"]
            processed["repeat_count"] = len(run)
            # Reformat content with a time-range hint (HH:MM - HH:MM) — the
            # WORLD clock, which is the only clock the diary talks about.
            try:
                start_hm = _game_hhmm(first["timestamp"])
                end_hm = _game_hhmm(last["timestamp"])
                if start_hm and end_hm and start_hm != end_hm:
                    processed["content"] = f"{processed['content']} ({start_hm} - {end_hm})"
            except Exception:
                pass
        result.append(processed)
    return result


def _collect_chat_events(character_name: str, window: Window) -> List[Dict[str, Any]]:
    """Thought-driven messages and TalkTo results from chat history.

    Scans this character's own chats (outgoing thoughts + TalkTo) AND other
    characters' chats (incoming TalkTo where this character was the target).
    Legacy JSON chat files only — live chat lives in ``chat_messages`` — so the
    files are no longer pre-filtered by a date in their NAME (a game day has no
    such name): every file is read and its messages are matched against the
    window.
    """
    from app.models.character import get_character_dir, get_user_characters_dir

    result = []

    # --- Own chat: outgoing thoughts + TalkTo ---
    chat_dir = get_character_dir(character_name) / "chats"
    if chat_dir.exists():
        for chat_file in chat_dir.glob("*.json"):
            _parse_chat_file(chat_file, window, character_name, result, is_own=True)

    # --- Other characters' chats: incoming TalkTo ---
    chars_dir = get_user_characters_dir()
    if chars_dir.exists():
        for char_dir in chars_dir.iterdir():
            if not char_dir.is_dir() or char_dir.name == character_name:
                continue
            other_chat_dir = char_dir / "chats"
            if not other_chat_dir.exists():
                continue
            for chat_file in other_chat_dir.glob("*.json"):
                _parse_chat_file(chat_file, window, character_name, result,
                                 is_own=False, sender_name=char_dir.name)

    return result


def _parse_chat_file(
    chat_file: Path,
    window: Window,
    character_name: str,
    result: List[Dict[str, Any]],
    is_own: bool = True,
    sender_name: str = "") -> None:
    """Parse a chat file for diary-relevant entries."""
    try:
        messages = json.loads(chat_file.read_text(encoding="utf-8"))
    except Exception:
        return

    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content", "")
        ts = msg.get("timestamp", "")
        if not _in_window(ts, window):
            continue

        if is_own:
            # Thought-generated messages
            thought_match = re.match(
                r'\[Gedanken-Nachricht\s*\|\s*([^|]*?)\s*\|\s*[^\]]*\]\s*(.*)',
                content, re.DOTALL
            )
            if thought_match:
                location = thought_match.group(1).strip()
                text = thought_match.group(2).strip()
                text = re.sub(r'<tool[^>]*>.*?(?:</tool>|$)', '', text, flags=re.DOTALL).strip()
                if text and text.upper() != "SKIP":
                    result.append({
                        "type": "thought",
                        "content": text,
                        "timestamp": ts,
                        "metadata": {"location": location},
                    })


def _collect_instagram(character_name: str, window: Window) -> List[Dict[str, Any]]:
    """Instagram posts and comments — reads from DB events table or feed.json fallback."""
    try:
        from app.models.instagram import load_feed
        feed = load_feed()
    except Exception:
        from app.core.paths import get_storage_dir
        feed_path = get_storage_dir() / "instagram_feed.json"
        if not feed_path.exists():
            return []
        try:
            feed = json.loads(feed_path.read_text(encoding="utf-8"))
        except Exception:
            return []

    result = []
    try:
        for post in feed:
            ts = post.get("timestamp", "")
            agent = post.get("agent_name", "")

            # Posts by this character
            if agent == character_name and _in_window(ts, window):
                caption = post.get("caption", "")
                result.append({
                    "type": "instagram_post",
                    "content": f"Instagram Post: {caption}",
                    "timestamp": ts,
                    "metadata": {"post_id": post.get("id", "")},
                })

            # Comments by this character on any post
            for comment in post.get("comments", []):
                cts = comment.get("timestamp", "")
                if comment.get("author") == character_name and _in_window(cts, window):
                    post_author = post.get("agent_name", "")
                    result.append({
                        "type": "instagram_comment",
                        "content": f"Kommentar bei {post_author}: {comment.get('text', '')}",
                        "timestamp": cts,
                        "metadata": {"post_id": post.get("id", "")},
                    })
    except Exception as e:
        logger.debug("Instagram collect error: %s", e)
    return result


def _collect_assignments(character_name: str, window: Window) -> List[Dict[str, Any]]:
    """Assignment progress from assignments.json."""
    from app.models.assignments import _load_all
    result = []
    try:
        for a in _load_all():
            participant = a.get("participants", {}).get(character_name)
            if not participant:
                continue
            title = a.get("title", a.get("id", ""))
            for p in participant.get("progress", []):
                ts = p.get("timestamp", "")
                if not _in_window(ts, window):
                    continue
                note = p.get("note", "")
                # Detect completion vs update
                is_done = a.get("status") == "completed" and p == participant["progress"][-1]
                etype = "assignment_done" if is_done else "assignment_update"
                result.append({
                    "type": etype,
                    "content": f"[{title}] {note}",
                    "timestamp": ts,
                    "metadata": {"assignment_id": a.get("id", "")},
                })
    except Exception as e:
        logger.debug("Assignment collect error: %s", e)
    return result


def _enrich_with_relationships(
    entries: List[Dict[str, Any]], character_name: str,
    window: Window) -> None:
    """Tag existing diary entries with relationship sentiment if a matching
    relationship history entry exists (matched by timestamp within 120s)."""
    try:
        from app.models.relationship import get_character_relationships
        rels = get_character_relationships(character_name)
    except Exception:
        return

    # Build list of (datetime, target, sentiment_delta) from relationship history
    rel_events = []
    name_lower = character_name.lower()
    for rel in rels:
        is_a = rel.get("character_a", "").lower() == name_lower
        other = rel.get("character_b", "") if is_a else rel.get("character_a", "")

        # Fallback for old history entries without sentiment_delta:
        # estimate from overall sentiment / interaction_count
        overall_sent = rel.get("sentiment_a_to_b", 0.0) if is_a else rel.get("sentiment_b_to_a", 0.0)
        count = max(rel.get("interaction_count", 1), 1)
        estimated_delta = overall_sent / count

        for h in rel.get("history", []):
            ts = h.get("timestamp", "")
            if not _in_window(ts, window):
                continue
            try:
                dt = parse_iso(ts)
            except Exception:
                continue
            stored_delta = h.get("sentiment_delta")
            # Use stored delta if present, otherwise estimate
            delta = stored_delta if stored_delta is not None else estimated_delta
            rel_events.append({
                "dt": dt,
                "target": other,
                "sentiment_delta": delta,
            })

    if not rel_events:
        return

    # For each diary entry, find closest relationship event within 120s.
    # Collect all candidates first, then assign each rel_event only to the
    # single closest diary entry to avoid duplicate tags.
    candidates = []  # (entry_index, rel_event_index, time_diff)
    for ei, entry in enumerate(entries):
        ts = entry.get("timestamp", "")
        if not ts:
            continue
        try:
            entry_dt = parse_iso(ts)
        except Exception:
            continue
        for ri, rev in enumerate(rel_events):
            diff = abs((entry_dt - rev["dt"]).total_seconds())
            if diff <= 120:
                candidates.append((ei, ri, diff))

    # Sort by time_diff so the closest match wins
    candidates.sort(key=lambda c: c[2])
    used_entries: set = set()
    used_events: set = set()
    for ei, ri, _ in candidates:
        if ei in used_entries or ri in used_events:
            continue
        rev = rel_events[ri]
        delta = rev["sentiment_delta"]
        if abs(delta) < 0.005:
            used_events.add(ri)
            continue
        meta = entries[ei].setdefault("metadata", {})
        meta["relationship_target"] = rev["target"]
        meta["relationship_sentiment"] = round(delta, 2)
        used_entries.add(ei)
        used_events.add(ri)


def _collect_event_resolutions(character_name: str, window: Window) -> List[Dict[str, Any]]:
    """Sammelt Loesungsversuche + geloeste Events in denen der Character aktiv war.

    Quelle: `events`-Tabelle, pro Event gibt es `resolution.attempts: [...]` mit
    {when, who, text, outcome, reason, joint_with}. Sowie das finale
    `resolved_by` / `resolved_text`. Alle mit Timestamp im Tagesbereich werden
    als Diary-Entries gerendert.
    """
    result: List[Dict[str, Any]] = []
    try:
        from app.models.events import get_all_events
        events = get_all_events()
    except Exception:
        return result
    for evt in events:
        resolution = evt.get("resolution") or {}
        attempts = resolution.get("attempts") or []
        evt_text = (evt.get("text") or "").strip()
        for att in attempts:
            who = att.get("who") or ""
            joint = att.get("joint_with") or []
            if character_name != who and character_name not in joint:
                continue
            when = att.get("when") or ""
            if not _in_window(when, window):
                continue
            solution_text = (att.get("text") or "").strip()
            outcome = att.get("outcome") or "fail"
            joint_txt = f" (mit {', '.join(joint)})" if joint else ""
            if outcome == "success":
                content = f"Ereignis geloest{joint_txt}: {evt_text[:120]} — Aktion: {solution_text[:200]}"
                etype = "event_resolved"
            else:
                reason = (att.get("reason") or "").strip()
                tail = f" — Erfolglos: {reason[:100]}" if reason else " — Erfolglos"
                content = f"Loesungsversuch{joint_txt}: {evt_text[:120]} — Aktion: {solution_text[:180]}{tail}"
                etype = "event_attempt"
            result.append({
                "type": etype,
                "content": content,
                "timestamp": str(when),
                "metadata": {"event_id": evt.get("id", ""),
                             "category": evt.get("category", ""),
                             "joint_with": joint,
                             "outcome": outcome},
            })
    return result


# ---------------------------------------------------------------------------
# Main generation
# ---------------------------------------------------------------------------

def generate_for_day(character_name: str,
    day_key: Optional[str] = None) -> List[Dict[str, Any]]:
    """Generate diary entries for one GAME day by pulling from all sources.

    ``day_key`` is a game day (``Y0002-D109``), defaulting to today's. All
    aggregated sources carry SYSTEM stamps, so the day is resolved to a system
    window once and handed to every collector. A key that is not a game day
    yields nothing and says so in the log — a real date arriving here is a
    defect, not a case to fall back for.

    Returns a chronologically sorted list.
    """
    key = resolve_day_key(day_key)
    window = system_window_of_game_day(key)
    if window is None:
        logger.warning("generate_for_day(%s): %r is not a game day key",
                       character_name, day_key)
        return []

    entries = []
    entries.extend(_collect_mood(character_name, window))
    entries.extend(_collect_state_changes(character_name, window, key))
    entries.extend(_collect_chat_events(character_name, window))
    entries.extend(_collect_instagram(character_name, window))
    entries.extend(_collect_event_resolutions(character_name, window))
    entries.extend(_collect_assignments(character_name, window))

    # Add stored daily summaries — those carry their own game stamp.
    for e in _load_stored(character_name):
        if e.get("type") == "daily_summary" and (e.get("game_ts") or "").startswith(key):
            entries.append(e)

    # Sort chronologically
    entries.sort(key=lambda x: x.get("timestamp", ""))

    # Tag entries that had relationship impact
    _enrich_with_relationships(entries, character_name, window)

    return entries


def get_available_dates_fast(character_name: str) -> List[str]:
    """The GAME days that have data, newest first.

    The sources are SYSTEM-stamped, so each distinct stamp is projected onto
    its game day (``game_day_of``). Projecting the STAMPS, not a truncated real
    date, is what makes this correct at a speed factor > 1: one real day then
    covers many game days, and a ``substr(ts, 1, 10)`` would collapse them all
    into one. Stored diary entries bring their own game stamp and need no
    projection.
    """
    from app.core.day_consolidation import game_day_of
    from app.models.character import get_character_dir
    days = set()

    def _add(ts: Any) -> None:
        key = game_day_of(ts)
        if key:
            days.add(key)

    conn = None
    try:
        conn = get_connection()
    except Exception:
        conn = None

    # Mood history
    try:
        if conn is None:
            raise RuntimeError("no DB connection")
        for r in conn.execute(
            "SELECT DISTINCT ts FROM mood_history WHERE character_name=?",
            (character_name,),
        ).fetchall():
            _add(r[0])
    except Exception:
        # Fallback: JSON
        mood_path = get_character_dir(character_name) / "mood_history.json"
        if mood_path.exists():
            try:
                data = json.loads(mood_path.read_text(encoding="utf-8"))
                for e in (data.get("entries", []) if isinstance(data, dict) else []):
                    _add(e.get("timestamp", ""))
            except Exception:
                pass

    # State history — carries its own game stamp, so the day is read off it
    # instead of being projected (same selection the day view uses).
    try:
        if conn is None:
            raise RuntimeError("no DB connection")
        for r in conn.execute(
            "SELECT DISTINCT substr(game_ts, 1, instr(game_ts, 'T') - 1) "
            "FROM state_history WHERE character_name=? AND game_ts LIKE '%T%'",
            (character_name,),
        ).fetchall():
            if r[0]:
                days.add(r[0])
    except Exception:
        # Fallback: JSON
        state_path = get_character_dir(character_name) / "state_history.json"
        if state_path.exists():
            try:
                for e in json.loads(state_path.read_text(encoding="utf-8")):
                    _add(e.get("timestamp", ""))
            except Exception:
                pass

    # Chat history
    try:
        if conn is None:
            raise RuntimeError("no DB connection")
        for r in conn.execute(
            "SELECT DISTINCT ts FROM chat_messages WHERE character_name=?",
            (character_name,),
        ).fetchall():
            _add(r[0])
    except Exception:
        # Fallback: legacy chat files — the file NAME carries a real date, so
        # the messages inside are what gets projected.
        chat_dir = get_character_dir(character_name) / "chats"
        if chat_dir.exists():
            for f in chat_dir.glob("*.json"):
                try:
                    for msg in json.loads(f.read_text(encoding="utf-8")):
                        _add(msg.get("timestamp", ""))
                except Exception:
                    continue

    # Stored diary entries carry their own game stamp
    for e in _load_stored(character_name):
        stamp = e.get("game_ts") or ""
        if len(stamp) >= 10:
            days.add(stamp[:10])

    return sorted(days, reverse=True)


def build_daily_summary_input(character_name: str,
                              day_key: Optional[str] = None) -> str:
    """Build a text summary of one GAME day's events for LLM consumption.

    Deduplicates consecutive identical entries (e.g. same mood repeated),
    truncates long thought messages, and limits total length to fit within
    small model context windows. Every time is the WORLD clock — the character
    writing this diary has never seen the server's clock.
    """
    entries = generate_for_day(character_name, day_key)
    entries = [e for e in entries if e.get("type") != "daily_summary"]
    if not entries:
        return ""

    lines = []
    last_content = ""
    for e in entries:
        time_str = _game_hhmm(e.get("timestamp", ""))
        etype = ENTRY_TYPES.get(e.get("type", ""), e.get("type", ""))
        content = e.get("content", "")

        # Deduplicate consecutive identical content (e.g. same mood 16x)
        if content == last_content:
            continue
        last_content = content

        # Truncate long thought messages for summary input
        if len(content) > 200:
            content = content[:200] + "..."

        lines.append(f"- {time_str} [{etype}] {content}")

    result = "\n".join(lines)
    # Hard limit to ~3000 chars to fit in small model context
    if len(result) > 3000:
        result = result[:3000] + "\n... (gekuerzt)"
    return result
