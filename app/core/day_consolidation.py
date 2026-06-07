"""Tages-Konsolidierung (plan-history-consolidation-cleanup.md, Phase 2).

Beim Hauptschlaf — bzw. als Stau-Fallback — werden die Szenen des Wach-Blocks
eines Characters zu EINEM Tages-Eintrag verdichtet (Tabelle ``summaries``,
kind='daily', partner=''). Danach liest man einen Tag als einen Eintrag statt
mehrere Szenen.

Auslöser-Kriterium ist die SCHLAF-LÄNGE (nicht die Uhrzeit — sonst kippt es bei
Nachtschicht). Szenen sind geteilt (mehrere Teilnehmer) → wir löschen sie NICHT,
sondern führen pro Character einen Cursor (world_kv): Szenen bis zum Cursor sind
in Tages-Einträge eingeklappt, neuere werden im Prompt einzeln gezeigt.
"""
from typing import Any, Dict, List, Tuple

from app.core.db import get_connection, transaction
from app.core.log import get_logger
from app.core.timeutils import utc_now, utc_now_iso, parse_iso

logger = get_logger("day_consolidation")

# Config-Defaults (admin-überschreibbar via memory.*)
_DEFAULT_MAIN_SLEEP_MIN_HOURS = 4
_DEFAULT_MAX_BLOCK_OPEN_HOURS = 30


def _cfg(key: str, default):
    try:
        from app.core import config
        val = config.get(key)
        return val if val not in (None, "") else default
    except Exception:
        return default


# --- world_kv (key/value) ---------------------------------------------------

def _kv_get(key: str) -> str:
    try:
        row = get_connection().execute(
            "SELECT value FROM world_kv WHERE key=?", (key,)).fetchone()
        return (row[0] or "") if row else ""
    except Exception:
        return ""


def _kv_set(key: str, value: str) -> None:
    try:
        with transaction() as conn:
            conn.execute(
                "INSERT INTO world_kv (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
    except Exception as e:
        logger.debug("kv_set %s failed: %s", key, e)


def get_cursor(character_name: str) -> str:
    return _kv_get(f"day_cursor:{character_name}")


def set_cursor(character_name: str, ts: str) -> None:
    _kv_set(f"day_cursor:{character_name}", ts or "")


# --- Konsolidierung ---------------------------------------------------------

def consolidate_block_for(character_name: str, reason: str = "") -> int:
    """Verdichtet die noch nicht eingeklappten Szenen des Characters zu einem
    Tages-Eintrag. Gibt die Anzahl eingeklappter Szenen zurück (0 = nichts)."""
    if not character_name:
        return 0
    from app.models import scene_store
    cursor = get_cursor(character_name)
    scenes = [s for s in scene_store.get_recent_scenes_for(character_name, limit=50)
              if (s.get("last_activity_ts") or "") > cursor
              and (s.get("summary") or "").strip()]
    now = utc_now_iso()
    if not scenes:
        set_cursor(character_name, now)  # leerer Block geschlossen
        return 0
    scenes.sort(key=lambda s: s.get("last_activity_ts") or "")
    new_cursor = scenes[-1].get("last_activity_ts") or now
    date_key = (new_cursor or now)[:10]
    summary = _summarize_day(character_name, scenes)
    if summary:
        _save_daily(character_name, date_key, summary)
        # Tages-Eintrag auch als (gröberes) Memory ablegen → memory_service-Rollup
        # (daily→weekly→monthly) greift darauf, Quelle = Szenen statt chat_messages.
        try:
            from app.models.memory import add_memory
            add_memory(character_name, summary, memory_type="daily", importance=2,
                       tags=["day"], context="day",
                       extra_meta={"date_key": date_key})
        except Exception as e:
            logger.debug("daily memory add failed for %s: %s", character_name, e)
    set_cursor(character_name, new_cursor)
    logger.info("Tag konsolidiert: %s (%d Szenen, date=%s, reason=%s)",
                character_name, len(scenes), date_key, reason or "?")
    return len(scenes)


def _summarize_day(character_name: str, scenes: List[Dict[str, Any]]) -> str:
    """LLM-Verdichtung mehrerer Szenen-Summaries eines Tages zu EINEM Eintrag."""
    try:
        from app.core.llm_router import llm_call
        from app.models.character import get_character_language, LANGUAGE_MAP
        code = (get_character_language(character_name) or "en").strip()
        lang = LANGUAGE_MAP.get(code, "English")
        bullets = "\n".join(f"- {(s.get('summary') or '').strip()}"
                            for s in scenes if (s.get("summary") or "").strip())
        sys_prompt = (
            f"You compress a character's day into ONE short recap from the scene "
            f"summaries below. Write 2-4 sentences in {lang}, past tense, from "
            f"{character_name}'s perspective. Keep only what matters for later; drop "
            f"filler. No lists, no preamble — just the recap.")
        user_prompt = f"Scenes of the day for {character_name}:\n{bullets}"
        resp = llm_call(task="consolidation", system_prompt=sys_prompt,
                        user_prompt=user_prompt, agent_name=character_name)
        return (resp.content or "").strip() if resp else ""
    except Exception as e:
        logger.warning("day summary LLM failed for %s: %s", character_name, e)
        return ""


def _save_daily(character_name: str, date_key: str, content: str) -> None:
    try:
        with transaction() as conn:
            conn.execute(
                "INSERT INTO summaries (character_name, kind, date_key, partner, content) "
                "VALUES (?, 'daily', ?, '', ?) "
                "ON CONFLICT(character_name, kind, date_key, partner) DO UPDATE SET "
                "content=excluded.content", (character_name, date_key, content))
    except Exception as e:
        logger.error("save daily entry failed for %s/%s: %s", character_name, date_key, e)


def recent_daily_entries(character_name: str, limit: int = 7) -> List[Tuple[str, str]]:
    """(date_key, content) der jüngsten Tages-Einträge, neueste zuerst."""
    try:
        rows = get_connection().execute(
            "SELECT date_key, content FROM summaries WHERE character_name=? "
            "AND kind='daily' AND partner='' AND content!='' "
            "ORDER BY date_key DESC LIMIT ?", (character_name, max(1, limit))).fetchall()
        return [(r[0], r[1]) for r in rows]
    except Exception:
        return []


# --- Trigger (vom periodic-Job aufgerufen) ----------------------------------

def maybe_consolidate(character_name: str) -> int:
    """Prüft die Auslöser und konsolidiert ggf.:
      1) Hauptschlaf: beim Aufwachen wurde `woke_main_sleep:<c>` gesetzt.
      2) Stau-Fallback: offener Block (Cursor) älter als max_block_open_hours.
    """
    flag_key = f"woke_main_sleep:{character_name}"
    if _kv_get(flag_key):
        _kv_set(flag_key, "")
        return consolidate_block_for(character_name, "main_sleep")

    # Fallback: ältester noch nicht eingeklappter Block zu alt?
    cursor = get_cursor(character_name)
    max_hours = int(_cfg("memory.max_block_open_hours", _DEFAULT_MAX_BLOCK_OPEN_HOURS))
    try:
        from app.models import scene_store
        scenes = [s for s in scene_store.get_recent_scenes_for(character_name, limit=50)
                  if (s.get("last_activity_ts") or "") > cursor
                  and (s.get("summary") or "").strip()]
        if not scenes:
            return 0
        oldest = min(s.get("last_activity_ts") or "" for s in scenes)
        if oldest and (utc_now() - parse_iso(oldest)).total_seconds() >= max_hours * 3600:
            return consolidate_block_for(character_name, f"fallback_{max_hours}h")
    except Exception as e:
        logger.debug("maybe_consolidate fallback check failed for %s: %s", character_name, e)
    return 0


def note_sleep_start(character_name: str) -> None:
    """Beim Einschlafen: Startzeit merken (für die Schlaf-Längen-Messung)."""
    _kv_set(f"sleep_start:{character_name}", utc_now_iso())


def note_wake(character_name: str) -> None:
    """Beim Aufwachen: war es Hauptschlaf (≥ Schwelle)? Dann Flag für den
    periodic-Job setzen, der die Tages-Konsolidierung übernimmt (LLM dort)."""
    start = _kv_get(f"sleep_start:{character_name}")
    _kv_set(f"sleep_start:{character_name}", "")
    if not start:
        return
    try:
        slept_h = (utc_now() - parse_iso(start)).total_seconds() / 3600.0
    except Exception:
        return
    min_h = float(_cfg("memory.main_sleep_min_hours", _DEFAULT_MAIN_SLEEP_MIN_HOURS))
    if slept_h >= min_h:
        _kv_set(f"woke_main_sleep:{character_name}", utc_now_iso())
        logger.info("%s: Hauptschlaf erkannt (%.1fh ≥ %.1fh) → Tages-Konsolidierung vorgemerkt",
                    character_name, slept_h, min_h)
