"""Scene lifecycle (plan-room-conversation §7).

- ``touch`` opens/refreshes a room's scene on every utterance
  (called from ``perception.record_utterance``).
- ``run_idle_consolidation`` closes ebbed-away scenes: LLM summary of the raw
  utterances → scene memory in every participant's memory → prune perceptions.
  The agent loop calls this periodically (in a thread). It also carries the
  wilderness prune (``prune_wilderness_stream``), the age-based exit for the
  location-less lines that have no scene to end them.
- Scenes that never fall idle (constant traffic, or a room forever waiting for
  an obligatory answer) are caught by the safety net of ``classify_scene``:
  ``max_age`` (``memory.scene_max_hours``) and ``max_len``
  (``memory.scene_max_perceptions``). The next utterance opens a new scene.

Consolidation is event-driven (scene end), not a 6h batch — the batch remains
only as a safety net. Raw perceptions are ephemeral (discarded after the
summary); utterances remain the canonical truth for the observer view.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Union

from app.core.log import get_logger
from app.core.timeutils import parse_iso, utc_now, utc_now_iso
from app.core.perception import STORYTELLER_SPEAKER

logger = get_logger("scene_manager")

# Silence threshold after which an open scene counts as ebbed away and is
# closed. Fallback default — configurable via memory.scene_idle_minutes
# (admin settings, Memory section).
DEFAULT_SCENE_IDLE_MINUTES = 30

# Safety net against scenes that never fall idle — a room with constant traffic
# (every utterance refreshes ``last_activity_ts``) or one whose obligatory answer
# never arrives would otherwise keep an unbounded perception context open.
# Fallback defaults — configurable via memory.scene_max_hours /
# memory.scene_max_perceptions (admin settings, Memory section); 0 = off.
DEFAULT_SCENE_MAX_HOURS = 6
DEFAULT_SCENE_MAX_PERCEPTIONS = 400

# How long a LOCATION-LESS line survives (SYSTEM time — see below).
#
# Every located line has an end: its scene ebbs away after
# ``scene_idle_minutes`` (30 min by default), the summary goes into the
# participants' memories and ``prune_scene_perceptions`` drops the raw rows; a
# scene whose summary keeps failing is force-closed after 24 h so it cannot
# linger either. Out in the open there is no scene at all (``touch`` skips it,
# and deliberately so — one bucket for the whole wilderness would mix
# strangers kilometres apart into each other's memories), so nothing ever ends
# those rows: utterances AND perceptions out there grow without bound.
#
# Until a wilderness scene has a spatial key of its own, AGE is the only exit.
# Seven days is not invented here: ``day_consolidation.THOUGHT_RETENTION_DAYS``
# is the same decision for the same kind of row (raw material with no other way
# out) and uses the same horizon, and everything that reads the wilderness
# stream reads its TAIL (small limits, recent lines). So a week outlasts every
# reader by a wide margin while still bounding growth — and it is 7× the 24 h
# ceiling a stuck located scene gets.
#
# SYSTEM days, not game days, although the horizon is about the world: the ts
# columns are stamped with ``utc_now_iso`` (like every other technical stamp —
# scene idle, thought retention, the 24 h valve), so comparing them against a
# game clock that can be stopped or run at a tick factor would re-date old rows
# whenever the factor changes. Retention is storage hygiene, and storage
# hygiene runs on the wall clock.
#
# That makes the horizon deliberately ASYMMETRIC to the readers: the daily
# recap reads back 7 GAME days (``recent_daily_entries``, DAILY_SUMMARY_DAYS),
# which at a factor > 1 is a much shorter real span than these 7 system days.
# The retention therefore keeps rows LONGER than any reader needs, never
# shorter — which is the safe direction for a cleanup rule.
WILDERNESS_RETENTION_DAYS = 7


def scene_idle_minutes() -> float:
    """Configured silence threshold in minutes (SYSTEM time)."""
    try:
        from app.core import config
        val = config.get("memory.scene_idle_minutes")
        if val not in (None, ""):
            return max(1.0, float(val))
    except Exception:  # noqa: BLE001
        pass
    return float(DEFAULT_SCENE_IDLE_MINUTES)


def scene_max_hours() -> float:
    """Configured maximum age of an open scene in hours (SYSTEM time).
    0 = the age net is off."""
    return _config_number("memory.scene_max_hours", DEFAULT_SCENE_MAX_HOURS)


def scene_max_perceptions() -> int:
    """Configured maximum number of raw perceptions an open scene may hold.
    0 = the size net is off."""
    return int(_config_number("memory.scene_max_perceptions",
                              DEFAULT_SCENE_MAX_PERCEPTIONS))


def _config_number(key: str, default: float) -> float:
    """Config value as a non-negative number; unset/garbage → ``default``."""
    try:
        from app.core import config
        val = config.get(key)
        if val not in (None, ""):
            return max(0.0, float(val))
    except Exception:  # noqa: BLE001
        pass
    return float(default)


def classify_scene(opened_ts: Union[str, datetime],
                   last_activity_ts: Union[str, datetime],
                   perception_count: int,
                   now: datetime,
                   idle_minutes: float,
                   max_hours: float,
                   max_perceptions: int,
                   in_skip: bool) -> Optional[str]:
    """Why an open scene should be consolidated — or ``None`` to leave it open.

    Pure decision function (no DB, no config, no clock of its own): the store
    queries (``get_idle_open_scenes`` / ``get_aged_open_scenes`` /
    ``get_oversized_open_scenes``) only gather candidates, this decides — so the
    rule can be checked by hand in ``scripts/smoke_scene_safety_net.py``.

    Returns:
      * ``"idle"``    — the room fell silent for ``idle_minutes``. The normal
        case; it loses against ``in_skip`` (a room with a pending obligatory
        answer must keep its perceptions until the addressed character replies).
      * ``"max_age"`` — the scene STARTED more than ``max_hours`` ago. Safety net
        for a room whose traffic never stops (every utterance refreshes the last
        activity) or whose obligatory answer never arrives; it beats ``in_skip``,
        because that is the whole point of the net. 0 h = off.
      * ``"max_len"`` — the scene holds at least ``max_perceptions`` raw
        perceptions. Same net, measured by size instead of time; also beats
        ``in_skip``. 0 = off.

    Precedence: idle first (the ordinary reason, unchanged semantics), then age,
    then size — a scene can qualify for several, the action is the same either
    way and only the logged reason differs. All timestamps are SYSTEM time, ISO
    strings or aware datetimes; unparsable stamps simply do not trigger their
    rule.
    """
    if not in_skip and _older_than(last_activity_ts, now, minutes=idle_minutes):
        return "idle"
    if max_hours > 0 and _older_than(opened_ts, now, hours=max_hours):
        return "max_age"
    if max_perceptions > 0 and perception_count >= max_perceptions:
        return "max_len"
    return None


def _older_than(ts: Union[str, datetime], now: datetime, **delta) -> bool:
    """True when ``ts`` lies before ``now - delta``. Unparsable → False."""
    try:
        dt = parse_iso(ts) if isinstance(ts, str) else ts
        return bool(dt) and dt < now - timedelta(**delta)
    except Exception:  # noqa: BLE001
        return False


def touch(location_id: str, room_id: str, speaker: str, ts: str = "") -> int:
    """Open/refresh the room's scene. Best effort, never blocking.

    The WILDERNESS has no scene (E6, v1 decision). A scene is keyed by
    location — ``scenes.location_id`` is NOT NULL — so every location-less
    line would land in the single bucket ``("", "")``. Consolidation writes
    ONE summary into the memory of EVERY participant of a scene, so that one
    bucket would mix characters kilometres apart into each other's memories:
    two people who never heard a word of each other would remember a shared
    conversation. Skipping the touch is the honest answer until a wilderness
    scene has a spatial key of its own; consolidating open-air conversations
    is deliberately still open.
    """
    if not location_id:
        return 0
    try:
        from app.models import scene_store
        return scene_store.touch_scene(location_id, room_id, speaker, ts or utc_now_iso())
    except Exception as e:  # noqa: BLE001
        logger.debug("scene touch failed (%s/%s): %s", location_id, room_id, e)
        return 0


def prune_wilderness_stream() -> int:
    """Drops location-less lines older than ``WILDERNESS_RETENTION_DAYS``.
    Returns the number of deleted utterances (their perceptions go with them).

    The wilderness counterpart of the scene prune — see the constant for why
    it exists and how the horizon was picked. Best-effort: a failing prune must
    never stop the consolidation pass it rides along with.
    """
    from app.models import perception_store
    cutoff = (utc_now() - timedelta(days=WILDERNESS_RETENTION_DAYS)
              ).isoformat(timespec="seconds")
    try:
        gone_u, gone_p = perception_store.prune_wilderness_rows(cutoff)
    except Exception as e:  # noqa: BLE001
        logger.debug("wilderness prune failed: %s", e)
        return 0
    if gone_u or gone_p:
        logger.info("Wilderness prune: %d utterance(s) + %d perception(s) older "
                    "than %d days dropped", gone_u, gone_p,
                    WILDERNESS_RETENTION_DAYS)
    return gone_u


def run_idle_consolidation(skip_room_keys=None) -> int:
    """Closes + consolidates all ebbed-away open scenes. Returns the number of
    consolidated scenes. Synchronous (LLM + DB) — the loop runs it via to_thread.

    ``skip_room_keys``: set of "loc/room" keys that are NOT consolidated
    (rooms with a pending obligatory answer) — otherwise the stream would be
    pruned before the addressed character could reply. The safety net
    (``max_age``/``max_len``, see :func:`classify_scene`) ignores that skip on
    purpose: a scene that can never fall idle must still end somewhere."""
    from app.models import scene_store
    skip = skip_room_keys or set()
    # The wilderness has no scene to consolidate, so it hangs on here — at the
    # TOP, before anything can return early: the open world must be swept even
    # in a world that has no open scene at all (or whose scene query just
    # failed), and a scene skipped for a pending answer must not hold it up.
    prune_wilderness_stream()

    now = utc_now()
    idle_minutes = scene_idle_minutes()
    max_hours = scene_max_hours()
    max_perceptions = scene_max_perceptions()

    # Three sources, ONE scene pool: a scene that is idle AND oversized must not
    # be consolidated twice in a pass. The size query is the only one that knows
    # the perception count, so the merge keeps the largest count it has seen.
    pool: Dict[Any, Dict[str, Any]] = {}

    def _collect(rows: List[Dict[str, Any]]) -> None:
        for row in rows:
            sid = row.get("id")
            prev = pool.get(sid)
            if prev is None:
                pool[sid] = dict(row)
                continue
            prev["perception_count"] = max(int(prev.get("perception_count") or 0),
                                           int(row.get("perception_count") or 0))

    def _query(what: str, fn, *args) -> None:
        """One source of candidates; a failing query must not cost the others."""
        try:
            _collect(fn(*args))
        except Exception as e:  # noqa: BLE001
            logger.debug("%s failed: %s", what, e)

    _query("get_idle_open_scenes", scene_store.get_idle_open_scenes,
           (now - timedelta(minutes=idle_minutes)).isoformat(timespec="seconds"))
    if max_hours > 0:
        _query("get_aged_open_scenes", scene_store.get_aged_open_scenes,
               (now - timedelta(hours=max_hours)).isoformat(timespec="seconds"))
    if max_perceptions > 0:
        _query("get_oversized_open_scenes", scene_store.get_oversized_open_scenes,
               max_perceptions)

    n = 0
    for scene in sorted(pool.values(), key=lambda s: str(s.get("last_activity_ts") or "")):
        key = f"{scene.get('location_id', '')}/{scene.get('room_id', '')}"
        reason = classify_scene(
            opened_ts=scene.get("started_ts") or "",
            last_activity_ts=scene.get("last_activity_ts") or "",
            perception_count=int(scene.get("perception_count") or 0),
            now=now, idle_minutes=idle_minutes, max_hours=max_hours,
            max_perceptions=max_perceptions, in_skip=key in skip)
        if reason is None:
            logger.debug("scene %s not consolidated: obligatory answer pending in %s",
                         scene.get("id"), key)
            continue
        try:
            logger.info("Consolidating scene %s (%s), reason=%s", scene.get("id"), key, reason)
            consolidate_scene(scene)
            n += 1
        except Exception as e:  # noqa: BLE001
            logger.warning("scene %s consolidation failed: %s", scene.get("id"), e)
    return n


def consolidate_scene(scene: Dict[str, Any]) -> None:
    """Consolidate one ebbed-away scene: LLM summary → participant memories →
    prune perceptions → mark as consolidated."""
    from app.models import scene_store
    from app.models.memory import add_memory

    sid = scene.get("id")
    utterances = scene_store.get_scene_utterances(scene)
    # The storyteller (narration) is not a character → no participant memory.
    # Its lines stay in the transcript (context).
    participants = [p for p in (scene.get("participants") or []) if p and p != STORYTELLER_SPEAKER]

    # Empty scene (only whisper meta or similar / nothing substantive) → close
    # without a summary, but still prune so it doesn't stay open.
    lines = []
    for u in utterances:
        sp = (u.get("speaker") or "").strip()
        content = (u.get("content") or "").strip()
        if sp and content:
            lines.append(f"{sp}: {content}")

    summary = ""
    if lines and participants:
        summary = _summarize(scene, lines)
        if not summary:
            # LLM summary failed for a scene WITH content: leave the scene
            # OPEN (no prune, no mark_consolidated) so the next idle pass
            # retries. Closing it with an empty summary would prune the raw
            # perceptions AND hide the scene from every recap
            # (summary != '' filter) — the conversation would vanish.
            # Safety valve: after 24h of failed retries give up and close
            # without a summary (logged as ERROR) so a permanently broken
            # consolidation LLM cannot hammer the queue forever.
            _last = scene.get("last_activity_ts") or ""
            _too_old = False
            try:
                from app.core.timeutils import parse_iso, utc_now as _unow
                _too_old = bool(_last) and (
                    (_unow() - parse_iso(_last)).total_seconds() > 24 * 3600)
            except Exception:
                pass
            if not _too_old:
                logger.warning("Szene %s: Summary-LLM lieferte nichts — Szene "
                               "bleibt offen für Retry (%d Äußerungen)",
                               sid, len(lines))
                return
            logger.error("Szene %s: Summary scheitert seit >24h — schließe ohne "
                         "Summary (%d Äußerungen gehen aus dem Recap verloren)",
                         sid, len(lines))

    if summary:
        for p in participants:
            try:
                add_memory(
                    p, summary, memory_type="episodic", importance=3,
                    tags=["scene"], context="scene",
                    extra_meta={"location_id": scene.get("location_id", ""),
                                "room_id": scene.get("room_id", ""),
                                "participants": participants,
                                "scene_id": sid})
            except Exception as e:  # noqa: BLE001
                logger.debug("scene-memory add failed for %s: %s", p, e)

    pruned = 0
    try:
        pruned = scene_store.prune_scene_perceptions(scene)
    except Exception as e:  # noqa: BLE001
        logger.debug("scene %s prune failed: %s", sid, e)
    try:
        scene_store.mark_consolidated(sid, summary)
    except Exception as e:  # noqa: BLE001
        logger.debug("scene %s mark_consolidated failed: %s", sid, e)
    logger.info("Szene %s konsolidiert (%d Äußerungen, %d Teilnehmer, %d Perceptions gepruned)",
                sid, len(lines), len(participants), pruned)


def _summarize(scene: Dict[str, Any], lines: list) -> str:
    """LLM summary of the scene (reused consolidation pattern)."""
    try:
        from app.core.llm_router import llm_call
        from app.core.prompt_templates import render_task
        from app.models.world import get_location_by_id
        loc = get_location_by_id(scene.get("location_id", "")) or {}
        loc_name = loc.get("name", "") or scene.get("location_id", "")
        room_name = ""
        for r in (loc.get("rooms") or []):
            if (r.get("id") or "") == scene.get("room_id", ""):
                room_name = r.get("name", "") or ""
                break
        # Derive the language from the participants → summary in the game
        # language (otherwise the LLM defaults to English).
        lang_instruction = ""
        try:
            from app.models.character import get_character_language, LANGUAGE_MAP
            _parts = [p for p in (scene.get("participants") or [])
                      if p and p != STORYTELLER_SPEAKER]
            if _parts:
                _code = (get_character_language(_parts[0]) or "en").strip()
                lang_instruction = f"\nWrite the summary in {LANGUAGE_MAP.get(_code, 'English')}."
        except Exception:
            pass
        sys_prompt, user_prompt = render_task(
            "consolidation_scene",
            location_name=loc_name, room_name=room_name,
            participants=", ".join(scene.get("participants") or []),
            transcript="\n".join(lines[:200]),
            lang_instruction=lang_instruction)
        resp = llm_call(task="consolidation", system_prompt=sys_prompt,
                        user_prompt=user_prompt)
        return (resp.content or "").strip() if resp else ""
    except Exception as e:  # noqa: BLE001
        logger.warning("scene summary LLM failed: %s", e)
        return ""
