"""Location events — situational happenings per place.

Stores short-lived events that are injected into the system prompt of every
character at the same place.

Storage: world.db, table ``events`` (kind='world_event'); the event dict itself
lives in the ``payload`` JSON column.

**Two stamps per event.** ``ts``/``created_at`` is SYSTEM time (ordering,
technical bookkeeping). ``game_ts`` is the canonical GAME time the event
started at, and so is ``expires_at``: an event's TTL is a WORLD duration — a
storm that lasts two hours lasts two hours *in the world*, which with a game
factor > 1 is minutes of real time. Everything a character or the UI reads
about WHEN an event happened comes off ``game_ts``.
"""
import json
import uuid

from app.core.game_time import GameDuration, GameTime
from app.core.i18n import t
from app.core.timeutils import game_time, game_time_at, utc_now, utc_now_iso
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

DEFAULT_TTL_HOURS = 24

from app.core.log import get_logger
from app.core.db import get_connection, transaction

logger = get_logger("events")

from app.core.paths import get_storage_dir


def _get_events_file() -> Path:
    sd = get_storage_dir()
    sd.mkdir(parents=True, exist_ok=True)
    return sd / "events.json"


def _row_to_event(row) -> Dict[str, Any]:
    """Converts a DB row (id, ts, game_ts, payload) into an event dict."""
    payload = {}
    try:
        payload = json.loads(row[3] or "{}")
    except Exception:
        pass
    # Ensure the event's "id" string field stays consistent
    if "id" not in payload:
        payload["id"] = str(row[0])
    if "created_at" not in payload:
        payload["created_at"] = row[1] or ""
    # The column is the authority for the game stamp; the payload copy exists
    # so the dict stays self-contained once it leaves this module.
    if not payload.get("game_ts"):
        payload["game_ts"] = row[2] or ""
    return payload


def _load_events() -> List[Dict[str, Any]]:
    """Loads all events from the DB."""
    try:
        conn = get_connection()
        rows = conn.execute(
            "SELECT id, ts, game_ts, payload FROM events "
            "WHERE kind='world_event' ORDER BY ts ASC"
        ).fetchall()
        events = [_row_to_event(r) for r in rows]
        return events
    except Exception as e:
        logger.warning("_load_events DB error: %s", e)
        # Fallback: JSON file
        path = _get_events_file()
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            events = data.get("events", [])
        except Exception:
            return []
        # Fill in TTL fields old JSON dumps may lack (JSON fallback only).
        # The TTL is GAME hours, so the expiry is a game stamp too.
        for evt in events:
            if "ttl_hours" not in evt:
                evt["ttl_hours"] = DEFAULT_TTL_HOURS
            if not evt.get("game_ts"):
                gt = game_time_at(evt.get("created_at"))
                evt["game_ts"] = gt.canonical() if gt is not None else ""
            if "expires_at" not in evt and evt.get("ttl_hours", 0) > 0:
                try:
                    started = GameTime.parse(evt["game_ts"])
                    evt["expires_at"] = (
                        started + GameDuration.of(hours=evt["ttl_hours"])).canonical()
                except (ValueError, TypeError, KeyError):
                    pass
        return events


def _row_id_for(conn, event_id: str) -> Optional[int]:
    """Integer row id of an event, looked up by its string id.

    The string id lives inside the ``payload`` JSON (the table's own ``id`` is
    the autoincrement key), so the lookup goes through ``json_extract``.
    """
    row = conn.execute(
        "SELECT id FROM events WHERE kind='world_event' "
        "AND json_extract(payload, '$.id')=? LIMIT 1",
        (event_id,),
    ).fetchone()
    if row:
        return row[0]
    # A row whose payload carries no id is handed out by ``_row_to_event``
    # under the integer row id — it has to be addressable under that id too.
    if event_id.isdigit():
        row = conn.execute(
            "SELECT id FROM events WHERE kind='world_event' AND id=? "
            "AND json_extract(payload, '$.id') IS NULL LIMIT 1",
            (int(event_id),),
        ).fetchone()
        if row:
            return row[0]
    return None


def _insert_event(event: Dict[str, Any]) -> None:
    """Writes ONE new event row.

    Never a save-everything: an event added by another thread between a load
    and a save used to be deleted by absence (review 2026-09-20, DATA-2).
    """
    try:
        with transaction() as conn:
            conn.execute(
                "INSERT INTO events (ts, game_ts, kind, character_name, payload) "
                "VALUES (?, ?, 'world_event', NULL, ?)",
                (event.get("created_at", utc_now_iso()),
                 event.get("game_ts", "") or "",
                 json.dumps(event, ensure_ascii=False)),
            )
    except Exception as e:
        logger.error("_insert_event DB error: %s", e)


def _update_event(event: Dict[str, Any]) -> bool:
    """Writes ONE changed event back onto its own row."""
    str_id = event.get("id")
    if not str_id:
        return False
    try:
        with transaction() as conn:
            row_id = _row_id_for(conn, str_id)
            if row_id is None:
                return False
            conn.execute(
                "UPDATE events SET ts=?, game_ts=?, payload=? WHERE id=?",
                (event.get("created_at", utc_now_iso()),
                 event.get("game_ts", "") or "",
                 json.dumps(event, ensure_ascii=False), row_id),
            )
        return True
    except Exception as e:
        logger.error("_update_event DB error: %s", e)
        return False


def _delete_event_row(event_id: str) -> bool:
    """Deletes ONE event row. True when a row was actually removed."""
    try:
        with transaction() as conn:
            row_id = _row_id_for(conn, event_id)
            if row_id is None:
                return False
            conn.execute("DELETE FROM events WHERE id=?", (row_id,))
        return True
    except Exception as e:
        logger.error("_delete_event_row DB error: %s", e)
        return False


def add_event(text: str,
    location_id: Optional[str] = None,
    ttl_hours: Optional[int] = None,
    category: str = "",
    escalation_of: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Creates a new event.

    location_id=None -> global event.
    category: ambient, social, disruption, danger (empty = uncategorized)
    escalation_of: event id of the preceding event (escalation chain)
    metadata: optional dict for extra event data (e.g. secret-hint info).

    ``ttl_hours`` are GAME hours: how long the happening lasts *in the world*.
    """
    if ttl_hours is None:
        ttl_hours = DEFAULT_TTL_HOURS
    now = utc_now()
    started = game_time()
    event = {
        "id": f"evt_{uuid.uuid4().hex[:8]}",
        "text": text.strip(),
        "location_id": location_id or None,
        "category": category or "",
        "ttl_hours": ttl_hours,
        "created_at": now.isoformat(),
        "game_ts": started.canonical(),
        "expires_at": ((started + GameDuration.of(hours=ttl_hours)).canonical()
                       if ttl_hours > 0 else None),
    }
    if escalation_of:
        event["escalation_of"] = escalation_of
    if metadata:
        event["metadata"] = metadata
    _insert_event(event)
    logger.info("Event created: %s [%s] (location=%s, ttl=%d game hours)",
                event["id"], category or "?", location_id, ttl_hours)
    return event


def _is_expired(event: Dict[str, Any]) -> bool:
    """Whether an event's WORLD lifetime has run out.

    ``expires_at`` is a canonical game stamp — the TTL counts world hours, so
    a frozen world freezes the event with it. A stamp that is not a game time
    (unmigrated, hand-edited) never expires: silently dropping an event over
    an unreadable field is worse than keeping it around.
    """
    expires_at = event.get("expires_at")
    if not expires_at:
        return False  # no expiry (ttl=0)
    try:
        return game_time() > GameTime.parse(expires_at)
    except (ValueError, TypeError):
        return False


def _active_events(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Expired events filtered out IN MEMORY — the read path never writes.

    Removing the rows is the job of :func:`expire_events` in the periodic
    tick. A read path that deletes by absence dropped events another thread
    had just created (review 2026-09-20, DATA-2).
    """
    return [e for e in events if not _is_expired(e)]


def expire_events() -> int:
    """Deletes the rows of every event whose WORLD lifetime has run out.

    Runs from the periodic tick (``app/core/periodic_jobs.py``). One
    ``DELETE … WHERE``: ``expires_at`` is a canonical GameTime string
    (``Y0002-D109T14:23:45``), fixed-width and therefore sortable as text, so
    the comparison happens in the GAME clock the TTL is counted in. The block
    rules coupled to an event (danger events) are cleaned up with it — the
    cleanup that used to hang off the read path.
    """
    now_canonical = game_time().canonical()
    expired_ids: List[str] = []
    try:
        with transaction() as conn:
            rows = conn.execute(
                "SELECT id, json_extract(payload, '$.id') FROM events "
                "WHERE kind='world_event' "
                "AND json_extract(payload, '$.expires_at') IS NOT NULL "
                "AND json_extract(payload, '$.expires_at') < ?",
                (now_canonical,),
            ).fetchall()
            for row_id, str_id in rows:
                conn.execute("DELETE FROM events WHERE id=?", (row_id,))
                if str_id:
                    expired_ids.append(str_id)
    except Exception as e:
        logger.error("expire_events DB error: %s", e)
        return 0
    if expired_ids:
        try:
            from app.models.rules import delete_rules_by_event
            for str_id in expired_ids:
                delete_rules_by_event(str_id)
        except Exception as _e:
            logger.debug("delete_rules_by_event(expiry) failed: %s", _e)
        logger.info("%d expired events removed", len(expired_ids))
    return len(expired_ids)


def list_events(location_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Lists active events. Optionally filtered by location."""
    events = _active_events(_load_events())
    if location_id is not None:
        events = [e for e in events if e.get("location_id") == location_id or e.get("location_id") is None]
    return events


def get_all_events() -> List[Dict[str, Any]]:
    """All active events (expired ones are filtered out)."""
    return _active_events(_load_events())


RESOLVED_TTL_HOURS = 2  # a resolved event stays visible for 2 more GAME hours


def resolve_event(event_id: str,
    resolved_by: str = "", resolved_text: str = "") -> Optional[Dict[str, Any]]:
    """Marks an event as resolved.

    - only disruption/danger events can be resolved
    - the TTL is shortened to RESOLVED_TTL_HOURS (2 GAME hours) from now
    - resolved_by: name of the character who resolved it
    - resolved_text: short description of the resolution
    """
    evt = get_event(event_id)
    if evt is None:
        return None
    if evt.get("category", "") not in ("disruption", "danger"):
        return None  # only resolvable events
    if evt.get("resolved"):
        return evt  # already resolved

    evt["resolved"] = True
    evt["resolved_by"] = resolved_by
    evt["resolved_text"] = resolved_text
    evt["resolved_at"] = utc_now().isoformat()
    evt["resolved_game_ts"] = game_time().canonical()
    # Shorten the remaining lifetime to 2 world hours from now.
    evt["expires_at"] = (
        game_time() + GameDuration.of(hours=RESOLVED_TTL_HOURS)).canonical()

    if not _update_event(evt):
        return None
    logger.info("Event resolved: %s by %s — %s", event_id, resolved_by, resolved_text[:60])
    # Clean up the coupled block rules immediately — the way is clear as
    # soon as it is resolved, not only after the resolved TTL.
    try:
        from app.models.rules import delete_rules_by_event
        delete_rules_by_event(event_id)
    except Exception as _e:
        logger.debug("delete_rules_by_event(resolve) failed: %s", _e)
    # Generate the "after" image of the location (linger display). Runs
    # in a background thread and does not block the resolve path.
    try:
        from app.core.event_images import trigger_resolved_image_from_text
        trigger_resolved_image_from_text(event_id)
    except Exception as _e:
        logger.debug("trigger_resolved_image_from_text failed: %s", _e)
    return evt


def record_attempt(event_id: str,
    who: str, text: str, outcome: str, reason: str = "",
    joint_with: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
    """Records an attempt to resolve the event.

    outcome: "success" | "fail"
    joint_with: further participating characters (joint attempts)

    Resolution schema on the event:
      resolution = {
        "attempts": [{when, who, text, outcome, reason, joint_with}, ...],
        "last_attempt_at": iso timestamp,
      }

    ``when``/``last_attempt_at`` stay SYSTEM stamps: they are a technical log
    of who tried what and when the server saw it, not something the world
    reads back.
    """
    evt = get_event(event_id)
    if evt is None:
        return None
    now = utc_now()
    resolution = evt.setdefault("resolution", {"attempts": [], "last_attempt_at": None})
    resolution["attempts"].append({
        "when": now.isoformat(),
        "who": who,
        "text": (text or "")[:500],
        "outcome": outcome,
        "reason": (reason or "")[:200],
        "joint_with": joint_with or [],
    })
    resolution["last_attempt_at"] = now.isoformat()
    if not _update_event(evt):
        return None
    logger.info("Event attempt %s: %s by %s (%s)", event_id, outcome, who, reason[:60])
    return evt


def update_event_fields(event_id: str, **fields) -> Optional[Dict[str, Any]]:
    """Writes individual fields into an event's payload JSON.

    Used e.g. for image_path / resolved_image_path when an event spawns or is
    resolved. A value of None deletes the field.
    """
    evt = get_event(event_id)
    if evt is None:
        return None
    for k, v in fields.items():
        if v is None:
            evt.pop(k, None)
        else:
            evt[k] = v
    if not _update_event(evt):
        return None
    return evt


def get_event(event_id: str) -> Optional[Dict[str, Any]]:
    """Returns an event by id, or None."""
    for evt in _load_events():
        if evt.get("id") == event_id:
            return evt
    return None


def delete_event(event_id: str) -> bool:
    """Deletes an event by id."""
    if _delete_event_row(event_id):
        logger.info("Event deleted: %s", event_id)
        try:
            from app.models.rules import delete_rules_by_event
            delete_rules_by_event(event_id)
        except Exception as _e:
            logger.debug("delete_rules_by_event(delete) failed: %s", _e)
        return True
    return False


def build_events_prompt_section(location_id: Optional[str] = None,
                                character_name: str = "") -> str:
    """Build the events section of the system prompt.

    Visibility by criticality:
    - ambient/social: only at the same place (+ global events)
    - disruption: at the same place (+ global) and from NEARBY places
    - danger: ALL danger events, wherever they are

    "Nearby" is METRES, not grid neighbours (E7): every placed location whose
    footprint lies within the discovery range of the character's own point —
    the same distance vocabulary discovery and the hearing radius speak. It
    needs the character, because the point belongs to the character and not to
    its location: someone on the way out of town is closer to the next village
    than the town hall is. Without a name, and for a character with no point
    (never positioned / standing in an unplaced location), there are no nearby
    places — the empty set the grid answered on every metre world.
    """
    if not location_id:
        return ""

    lang = "en"
    if character_name:
        try:
            from app.models.character import get_character_language
            lang = (get_character_language(character_name) or "en").strip() or "en"
        except Exception:
            lang = "en"

    # Events at the current place (every category)
    local_events = list_events(location_id=location_id)
    local_ids = {e.get("id") for e in local_events}

    nearby_ids: Set[str] = set()
    if character_name:
        try:
            from app.core.discovery import get_discovery_range_m, locations_within
            from app.models.character import get_character_pos
            pos = get_character_pos(character_name)
            if pos:
                nearby_ids = set(locations_within(
                    pos["x"], pos["z"], get_discovery_range_m(),
                    exclude=(location_id,)))
        except Exception as e:
            logger.debug("nearby locations for events failed: %s", e)

    # Disruptions from nearby places + danger from everywhere
    all_events = get_all_events()
    nearby_events = []
    for e in all_events:
        if e.get("id") in local_ids:
            continue
        evt_loc = e.get("location_id", "")
        cat = e.get("category", "")
        if cat == "danger":
            nearby_events.append(e)  # Danger: visible everywhere
        elif cat == "disruption" and evt_loc in nearby_ids:
            nearby_events.append(e)  # Disruption: only from nearby places

    if not local_events and not nearby_events:
        return ""

    lines = []

    # Local events
    if local_events:
        lines.append("Events at your location:")
        for evt in local_events:
            ts = _format_event_timestamp(evt.get("game_ts", ""), lang)
            prefix = f"[{ts}] " if ts else ""
            cat = evt.get("category", "")
            cat_tag = f"[{cat.upper()}] " if cat else ""
            if evt.get("resolved"):
                who = evt.get("resolved_by", "someone")
                how = evt.get("resolved_text", "")
                resolution = f" — {who}: {how}" if how else f" — resolved by {who}"
                lines.append(f"- {prefix}[RESOLVED] {evt['text']}{resolution}")
            else:
                lines.append(f"- {prefix}{cat_tag}{evt['text']}")

    # Nearby events (disruptions from nearby places + danger from everywhere)
    if nearby_events:
        lines.append("Events nearby (you can hear/sense them from your location):")
        for evt in nearby_events:
            ts = _format_event_timestamp(evt.get("game_ts", ""), lang)
            prefix = f"[{ts}] " if ts else ""
            cat = evt.get("category", "").upper()
            lines.append(f"- {prefix}[{cat}] {evt['text']}")

    return "\n" + "\n".join(lines)


_RELATIVE_DAYS_LIMIT = 7   # beyond that the world date is more useful


def _format_event_timestamp(game_ts: str, lang: str = "en") -> str:
    """Compact, LLM-readable WORLD date of an event.

    Reads the GAME stamp only. An event without one (pre-migration) yields ""
    and is rendered without a time prefix — a real-world date inside the world
    is worse than no date at all.
    """
    try:
        gt = GameTime.parse(game_ts)
    except (ValueError, TypeError):
        return ""
    days = game_time().day_index - gt.day_index
    time_str = gt.time_hhmm()
    if days <= 0:
        return t("today {time}", lang).format(time=time_str)
    if days == 1:
        return t("yesterday {time}", lang).format(time=time_str)
    if days < _RELATIVE_DAYS_LIMIT:
        return t("{days} days ago", lang).format(days=days)
    return f"{gt.date_label(lang)} {time_str}"


def event_game_label(event: Dict[str, Any], lang: str = "en") -> str:
    """Full world label of an event for API payloads ("" without a stamp).

    The clients render, they never compute (docs/schnittstellen-3d.md) — so
    the server ships the finished string, not a stamp plus formatting rules,
    the configured clock format included.
    """
    try:
        return GameTime.parse(event.get("game_ts") or "").display_label(lang)
    except (ValueError, TypeError):
        return ""
