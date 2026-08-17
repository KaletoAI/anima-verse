"""One-time boot migration: ISO game-time stamps → world-calendar GameTime.

plan-game-calendar.md §2.4 (decision E2). Before the world calendar the game
clock was a ``datetime`` and every persisted GAME stamp was an ISO string.
This module rewrites those stamps ONCE into the canonical GameTime form
(``Y0002-D109T14:00:00``), so that from then on exactly one representation
exists — the one that is also displayed.

The mapping keeps **relative distances exact**, which is what all the game
rules actually depend on (flag TTLs, journey progress, sleep length, the
anti-repetition window):

    total_seconds = (parse_iso(stamp) in the display timezone) − EPOCH_REAL

with ``EPOCH_REAL`` = 2026-01-01T00:00:00 in that timezone. One game day is
86400 s here just as it was there, so only the *label* changes (a real 17 Aug
2026 becomes "Winter, day 19 · Year 2" under the default 4×30 calendar).
Stamps from before 2026 clamp to the epoch (counted as ``clamped``).

Idempotent by FORMAT: a value that already parses as a canonical GameTime is
skipped, so a second boot converts nothing. Unparsable values are left alone
and counted (``unparsable``) — never guessed at, never dropped.

Every group runs in its own try/except: one broken table must not stop the
others, because a half-migrated world is exactly what we cannot have.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from app.core.game_time import Calendar, GameTime
from app.core.log import get_logger

logger = get_logger("game_calendar_migration")

# The real-world instant that becomes Year 1, Day 1, 00:00:00 — read in the
# configured display timezone, because that is the clock the old game stamps
# were shown and reasoned about in.
EPOCH_REAL_NAIVE = datetime(2026, 1, 1, 0, 0, 0)

_COUNTER_KEYS = ("anchor", "sleep_start", "thoughts", "profiles", "scheduler",
                 "cron_fields", "intents", "summaries", "memories", "events",
                 "diary", "state_history", "clamped", "unparsable")

# Rows per UPDATE batch for the table-wide backfills (memories/events/diary).
# A world can hold tens of thousands of memories, and one giant executemany
# would hold the whole rewrite in a single transaction at boot.
_BATCH = 500

# Already-migrated summary keys, one per rollup tier (day / week / season).
_GAME_KEY_RES = (re.compile(r"^Y\d{4,}-D\d{3,}$"),
                 re.compile(r"^Y\d{4,}-W\d{3,}$"),
                 re.compile(r"^Y\d{4,}-S\d{2,}$"))


def _epoch_real() -> datetime:
    from app.core.timeutils import _world_tz
    return EPOCH_REAL_NAIVE.replace(tzinfo=_world_tz())


def iso_to_game(value: Any, stats: Optional[Dict[str, int]] = None
                ) -> Optional[GameTime]:
    """ISO datetime string → :class:`GameTime`, or ``None`` if unusable.

    ``None`` means "leave the original value alone" — the caller counts it as
    ``unparsable`` and logs. Values before ``EPOCH_REAL`` clamp to the epoch
    and count as ``clamped``.
    """
    from app.core.timeutils import _world_tz, parse_iso
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = parse_iso(value.strip()).astimezone(_world_tz())
    except (ValueError, TypeError):
        if stats is not None:
            stats["unparsable"] += 1
        logger.warning("game calendar migration: unparsable stamp %r", value)
        return None
    total = int((dt - _epoch_real()).total_seconds())
    if total < 0:
        total = 0
        if stats is not None:
            stats["clamped"] += 1
    return GameTime(total)


def _convert(value: Any, stats: Dict[str, int]) -> Optional[str]:
    """Canonical string for a stored stamp, or ``None`` when nothing to do.

    ``None`` covers all three "leave it" cases: empty, already canonical,
    unparsable.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    if GameTime.is_canonical(value):
        return None
    gt = iso_to_game(value, stats)
    return gt.canonical() if gt is not None else None


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------


def _migrate_anchor(stats: Dict[str, int]) -> None:
    """world_kv ``game_time.anchor_game``.

    A world that never had an anchor keeps its old behaviour of starting
    "now": the anchor is set to the converted current system time, with the
    real anchor alongside it. The factor is not touched.
    """
    from app.core import timeutils
    from app.models.world import get_world_setting, set_world_setting

    raw_game = get_world_setting(timeutils._KEY_ANCHOR_GAME, "")
    raw_real = get_world_setting(timeutils._KEY_ANCHOR_REAL, "")

    if not (raw_game or "").strip():
        now = timeutils.utc_now()
        gt = iso_to_game(now.isoformat(timespec="seconds"), stats)
        if gt is None:
            return
        set_world_setting(timeutils._KEY_ANCHOR_GAME, gt.canonical())
        set_world_setting(timeutils._KEY_ANCHOR_REAL, now.isoformat(timespec="seconds"))
        stats["anchor"] += 1
        timeutils.invalidate_game_clock_cache()
        return

    canonical = _convert(raw_game, stats)
    if canonical is None:
        return
    set_world_setting(timeutils._KEY_ANCHOR_GAME, canonical)
    if not (raw_real or "").strip():
        set_world_setting(timeutils._KEY_ANCHOR_REAL,
                          timeutils.utc_now().isoformat(timespec="seconds"))
    stats["anchor"] += 1
    timeutils.invalidate_game_clock_cache()


def _migrate_sleep_start(stats: Dict[str, int]) -> None:
    """world_kv ``sleep_start:<character>`` (there is no prefix-listing helper
    for world_kv, so this is the one raw SELECT — on the same connection
    ``app.models.world`` uses)."""
    from app.core.db import get_connection
    from app.models.world import set_world_setting

    rows = get_connection().execute(
        "SELECT key, value FROM world_kv WHERE key LIKE 'sleep_start:%'"
    ).fetchall()
    for row in rows:
        key, value = row[0], row[1]
        canonical = _convert(value, stats)
        if canonical is None:
            continue
        set_world_setting(key, canonical)
        stats["sleep_start"] += 1


def _migrate_thoughts(stats: Dict[str, int]) -> None:
    """``thoughts.game_ts`` — ISO WITH a timezone offset, one row per thought.

    Read and written over the shared DB helpers of ``thought_store`` (it has
    no cursor helper of its own, it uses ``app.core.db`` directly).
    """
    from app.core.db import get_connection, transaction

    rows = get_connection().execute(
        "SELECT id, game_ts FROM thoughts WHERE game_ts IS NOT NULL AND game_ts != ''"
    ).fetchall()
    updates = []
    for row in rows:
        canonical = _convert(row[1], stats)
        if canonical is not None:
            updates.append((canonical, row[0]))
    if not updates:
        return
    with transaction() as conn:
        conn.executemany("UPDATE thoughts SET game_ts=? WHERE id=?", updates)
    stats["thoughts"] += len(updates)


def _migrate_profiles(stats: Dict[str, int]) -> None:
    """Character profiles: condition starts, state-flag stamps, journey start."""
    from app.models.character import (get_character_profile,
                                      list_available_characters,
                                      save_character_profile)

    for name in list_available_characters():
        try:
            profile = get_character_profile(name) or {}
        except Exception as e:  # noqa: BLE001 — one bad profile must not stop the rest
            logger.warning("game calendar migration: profile %s unreadable: %s", name, e)
            continue
        changed = False

        for cond in profile.get("active_conditions") or []:
            if not isinstance(cond, dict):
                continue
            canonical = _convert(cond.get("started_at"), stats)
            if canonical is not None:
                cond["started_at"] = canonical
                changed = True

        since = profile.get("state_flag_since")
        if isinstance(since, dict):
            for flag, value in list(since.items()):
                canonical = _convert(value, stats)
                if canonical is not None:
                    since[flag] = canonical
                    changed = True

        journey = profile.get("journey")
        if isinstance(journey, dict):
            canonical = _convert(journey.get("started_at_game"), stats)
            if canonical is not None:
                journey["started_at_game"] = canonical
                changed = True

        if changed:
            # NOT create_new: these are existing characters by definition.
            save_character_profile(name, profile)
            stats["profiles"] += 1


def _migrate_scheduler(stats: Dict[str, int]) -> None:
    """Scheduler jobs: the GAME stamps of a job's dispatch bookkeeping.

    ``last_execution.game_timestamp`` (when it last fired in game time),
    ``_registered_game`` (the baseline for a job that never fired) and a
    date trigger's ``run_date``. The cron FIELDS are calendar semantics, not
    stamps — they are handled by :func:`_migrate_cron_fields`.
    """
    from app.models.character import (get_character_scheduler_jobs,
                                      list_available_characters,
                                      save_character_scheduler_jobs)

    for name in list_available_characters():
        try:
            jobs = get_character_scheduler_jobs(name) or []
        except Exception as e:  # noqa: BLE001
            logger.warning("game calendar migration: scheduler jobs of %s "
                           "unreadable: %s", name, e)
            continue
        touched = 0
        for job in jobs:
            if not isinstance(job, dict):
                continue
            job_changed = False
            last = job.get("last_execution")
            if isinstance(last, dict):
                canonical = _convert(last.get("game_timestamp"), stats)
                if canonical is not None:
                    last["game_timestamp"] = canonical
                    job_changed = True
            canonical = _convert(job.get("_registered_game"), stats)
            if canonical is not None:
                job["_registered_game"] = canonical
                job_changed = True
            trigger = job.get("trigger")
            if isinstance(trigger, dict) and trigger.get("run_date"):
                canonical = _convert(trigger.get("run_date"), stats)
                if canonical is not None:
                    trigger["run_date"] = canonical
                    job_changed = True
            touched += 1 if job_changed else 0
        if touched:
            save_character_scheduler_jobs(name, jobs)
            stats["scheduler"] += touched


def migrate_cron_fields(trigger: Dict[str, Any],
                        calendar: Calendar) -> tuple:
    """Real-date cron fields → world-calendar fields (pure function).

    ``day`` → ``day_of_season``, ``month`` → ``season`` (KEY),
    ``day_of_week`` → ``weekday``. Returns ``(new_trigger, changed)``; the
    input dict is never mutated. Idempotent: a trigger that carries none of
    the three old keys comes back unchanged.

    The mapping is heuristic on purpose — a real month is not a season, and a
    real weekday is not a world weekday. Keeping the numbers is closer to the
    author's intent than dropping the schedule, and every conversion is
    logged so the user can correct it in the Scheduler tab.
    """
    old_keys = [k for k in ("day", "month", "day_of_week") if k in trigger]
    if not old_keys:
        return trigger, False

    new = dict(trigger)
    day = new.pop("day", None)
    month = new.pop("month", None)
    dow = new.pop("day_of_week", None)
    seasons = calendar.seasons

    # month → season: same index, wrapped into the number of seasons.
    season_index: Optional[int] = None
    if month not in (None, "", "*"):
        try:
            season_index = (int(month) - 1) % len(seasons) if seasons else None
        except (TypeError, ValueError):
            logger.info("cron migration: month=%r is not a plain number — dropped "
                        "(schedule now matches any season)", month)
        if season_index is not None and "season" not in new:
            new["season"] = seasons[season_index].key
            logger.info("cron migration: month=%s → season=%r (heuristic: same "
                        "index, wrapped)", month, new["season"])

    # day → day_of_season, clamped to the season's length. Without a season
    # the job may land in ANY season, so the clamp uses the SHORTEST one —
    # a day number that exists everywhere.
    if day not in (None, "", "*"):
        try:
            day_int = int(day)
        except (TypeError, ValueError):
            logger.info("cron migration: day=%r is not a plain number — dropped "
                        "(schedule now matches any day)", day)
        else:
            if season_index is not None:
                limit = seasons[season_index].days
            else:
                limit = min((s.days for s in seasons), default=day_int)
            value = max(1, min(day_int, limit))
            if value != day_int:
                logger.info("cron migration: day=%d clamped to day_of_season=%d "
                            "(season length %d)", day_int, value, limit)
            new["day_of_season"] = value

    # day_of_week → weekday, only for worlds that HAVE weeks.
    if dow not in (None, "", "*"):
        if not calendar.week_days:
            logger.info("cron migration: day_of_week=%r dropped — this world's "
                        "calendar has no week days", dow)
        else:
            try:
                new["weekday"] = int(dow) % len(calendar.week_days)
                logger.info("cron migration: day_of_week=%s → weekday=%s "
                            "(heuristic: same index, wrapped)", dow, new["weekday"])
            except (TypeError, ValueError):
                logger.info("cron migration: day_of_week=%r is not a plain number "
                            "— dropped", dow)

    return new, True


def _migrate_cron_fields(stats: Dict[str, int]) -> None:
    """Scheduler cron triggers: real-date fields → world-calendar fields."""
    from app.core.game_time import get_calendar
    from app.models.character import (get_character_scheduler_jobs,
                                      list_available_characters,
                                      save_character_scheduler_jobs)

    calendar = get_calendar()
    for name in list_available_characters():
        try:
            jobs = get_character_scheduler_jobs(name) or []
        except Exception as e:  # noqa: BLE001
            logger.warning("game calendar migration: scheduler jobs of %s "
                           "unreadable: %s", name, e)
            continue
        touched = 0
        for job in jobs:
            if not isinstance(job, dict):
                continue
            trigger = job.get("trigger")
            if not isinstance(trigger, dict) or trigger.get("type") != "cron":
                continue
            new_trigger, changed = migrate_cron_fields(trigger, calendar)
            if changed:
                job["trigger"] = new_trigger
                touched += 1
        if touched:
            save_character_scheduler_jobs(name, jobs)
            stats["cron_fields"] += touched


def _migrate_intents(stats: Dict[str, int]) -> None:
    """Intents: ``expires_at`` and the ``at_time`` trigger's ``run_date``.

    Both are GAME stamps (``intents._when_to_trigger`` / ``intent_engine.
    _schedule_intent`` build them off the game clock); ``created_at`` /
    ``updated_at`` are SYSTEM stamps and stay ISO.
    """
    from app.models.intents import list_intents, update_intent

    for intent in list_intents():
        changes: Dict[str, Any] = {}
        canonical = _convert(intent.get("expires_at"), stats)
        if canonical is not None:
            changes["expires_at"] = canonical
        trigger = intent.get("trigger")
        if isinstance(trigger, str):
            try:
                trigger = json.loads(trigger or "{}")
            except ValueError:
                trigger = {}
        if isinstance(trigger, dict) and trigger.get("run_date"):
            canonical = _convert(trigger.get("run_date"), stats)
            if canonical is not None:
                trigger = dict(trigger)
                trigger["run_date"] = canonical
                changes["trigger"] = trigger
        if changes:
            update_intent(intent.get("id"), **changes)
            stats["intents"] += 1


def _summary_key_to_game(date_key: str, kind: str,
                         stats: Dict[str, int]) -> Optional[str]:
    """Old ``summaries.date_key`` → game-calendar key, or ``None`` to leave it.

    The three tiers used real-calendar keys: ``YYYY-MM-DD`` (daily),
    ``YYYY-WNN`` (weekly, ISO week) and ``YYYY-MM`` (monthly). Each is read as
    midnight of its FIRST day in the display timezone and mapped through the
    same :func:`iso_to_game` as every other stamp, then re-keyed with the
    game-calendar helpers — so a day keeps the game day its real date became,
    and week/season follow from that day.
    """
    from app.core.memory_service import _season_key, _week_key
    if not isinstance(date_key, str) or not date_key.strip():
        return None
    key = date_key.strip()
    if any(rx.match(key) for rx in _GAME_KEY_RES):
        return None  # already migrated
    try:
        if kind == "weekly":
            year, week = key.split("-W")
            first = date.fromisocalendar(int(year), int(week), 1)
        elif kind == "monthly":
            year, month = key.split("-")
            first = date(int(year), int(month), 1)
        else:
            first = date.fromisoformat(key[:10])
    except (ValueError, TypeError):
        stats["unparsable"] += 1
        logger.warning("game calendar migration: unusable %s key %r", kind, key)
        return None
    from app.core.timeutils import _world_tz
    midnight = datetime.combine(first, datetime.min.time(), tzinfo=_world_tz())
    gt = iso_to_game(midnight.isoformat(), stats)
    if gt is None:
        return None
    if kind == "weekly":
        return _week_key(gt)
    if kind == "monthly":
        return _season_key(gt)
    return gt.day_key()


def _migrate_summaries(stats: Dict[str, int]) -> None:
    """``summaries.date_key`` of the rollup tiers → game-calendar keys.

    Decision E4: the day of a consolidation is the GAME day. Old rows carry
    real dates, and a mixed table would strand them — the weekly rollup would
    never pick them up again and no reader would find them.

    ``kind='history'`` is untouched: its key is the literal 'current', not a
    date. Two old keys can land on the same new key (ISO weeks are 7 days, a
    game week follows the world calendar), so rows are merged text-wise
    instead of colliding with the UNIQUE index.
    """
    from app.core.db import get_connection, transaction

    rows = get_connection().execute(
        "SELECT id, character_name, kind, date_key, partner, content "
        "FROM summaries WHERE kind IN ('daily','weekly','monthly') "
        "ORDER BY id ASC").fetchall()

    # {(character, kind, new_key, partner): (row ids, texts, converted count)}
    groups: Dict[Tuple[str, str, str, str], Tuple[List[Any], List[str], List[int]]] = {}
    for row in rows:
        row_id, character, kind, date_key, partner, content = (
            row[0], row[1], row[2], row[3], row[4] or "", row[5] or "")
        new_key = _summary_key_to_game(date_key, kind, stats)
        converted = new_key is not None
        # Rows that are already migrated still take part in the grouping, so a
        # converted row landing on the same key MERGES with them instead of
        # overwriting them.
        key = (character, kind, new_key if converted else date_key, partner)
        ids, texts, count = groups.setdefault(key, ([], [], [0]))
        ids.append(row_id)
        texts.append(content)
        count[0] += 1 if converted else 0

    with transaction() as conn:
        for (character, kind, new_key, partner), (ids, texts, count) in groups.items():
            if not count[0]:
                continue  # nothing converted in this group — leave it alone
            text = "\n\n".join(t for t in texts if t.strip())
            conn.execute(
                "DELETE FROM summaries WHERE id IN (%s)"
                % ",".join("?" for _ in ids), ids)
            conn.execute(
                "INSERT INTO summaries (character_name, kind, date_key, partner, content) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(character_name, kind, date_key, partner) DO UPDATE SET "
                "content=excluded.content",
                (character, kind, new_key, partner, text))
            stats["summaries"] += count[0]


def _backfill_game_ts(table: str, stats: Dict[str, int], counter: str) -> None:
    """Fill an empty ``<table>.game_ts`` from the SYSTEM stamp in ``ts``.

    Unlike every other group here, the source is NOT an old game stamp but a
    technical one, so the mapping is the BACK-PROJECTION
    (``timeutils.game_time_at``) and not the absolute ``iso_to_game``: these
    rows never carried a game time, and the best available answer is "the game
    time this instant corresponds to at the current rate".

    Idempotent by filter — only rows whose ``game_ts`` is still empty are
    touched, so a second boot converts nothing. Rows with an unusable ``ts``
    keep their empty stamp (counted as ``unparsable``); readers then simply
    show no world date for them.
    """
    from app.core.db import get_connection, transaction
    from app.core.timeutils import game_time_at

    rows = get_connection().execute(
        f"SELECT id, ts FROM {table} "  # noqa: S608 — table name is a literal
        f"WHERE game_ts IS NULL OR game_ts=''").fetchall()
    updates: List[Tuple[str, Any]] = []
    for row in rows:
        gt = game_time_at(row[1])
        if gt is None:
            stats["unparsable"] += 1
            logger.warning("game calendar migration: %s row %s has an unusable "
                           "ts %r", table, row[0], row[1])
            continue
        updates.append((gt.canonical(), row[0]))
    for start in range(0, len(updates), _BATCH):
        chunk = updates[start:start + _BATCH]
        with transaction() as conn:
            conn.executemany(
                f"UPDATE {table} SET game_ts=? WHERE id=?", chunk)  # noqa: S608
        stats[counter] += len(chunk)


def _migrate_memories(stats: Dict[str, int]) -> None:
    """``memories.game_ts`` — the world time a memory was formed at."""
    _backfill_game_ts("memories", stats, "memories")


def _migrate_state_history(stats: Dict[str, int]) -> None:
    """``state_history.game_ts`` — the world time of a state change.

    The rows feed the character's own "Recently experienced" block and the
    diary day, both of which speak world time; before the calendar the block
    cut HH:MM straight out of the SYSTEM stamp and presented it as the world
    hour.
    """
    _backfill_game_ts("state_history", stats, "state_history")


def _migrate_events(stats: Dict[str, int]) -> None:
    """``events.game_ts`` plus the game stamps inside a world event's payload.

    Two things move here:

    * ``game_ts`` (column AND payload) is back-projected from the creation
      stamp, like every other technical row.
    * ``expires_at`` becomes a GAME stamp, because an event's TTL is a WORLD
      duration ("the storm lasts two hours"). Existing values are
      back-projected rather than recomputed from ``ttl_hours``, so an event
      already ticking keeps disappearing at the real moment it would have —
      only events created from now on use the new game-duration semantics.
    """
    from app.core.db import get_connection, transaction
    from app.core.timeutils import game_time_at

    rows = get_connection().execute(
        "SELECT id, ts, game_ts, payload FROM events WHERE kind='world_event'"
    ).fetchall()
    updates: List[Tuple[str, str, Any]] = []
    for row_id, ts, game_ts, raw_payload in rows:
        try:
            payload = json.loads(raw_payload or "{}")
        except ValueError:
            stats["unparsable"] += 1
            logger.warning("game calendar migration: event row %s has an "
                           "unreadable payload", row_id)
            continue
        if not isinstance(payload, dict):
            continue
        changed = False

        stamp = (game_ts or payload.get("game_ts") or "").strip()
        if not GameTime.is_canonical(stamp):
            gt = game_time_at(payload.get("created_at") or ts)
            if gt is None:
                stats["unparsable"] += 1
                logger.warning("game calendar migration: event %s has no usable "
                               "creation stamp", payload.get("id", row_id))
                stamp = ""
            else:
                stamp = gt.canonical()
            payload["game_ts"] = stamp
            changed = True
        elif payload.get("game_ts") != stamp:
            payload["game_ts"] = stamp
            changed = True

        expires = payload.get("expires_at")
        if isinstance(expires, str) and expires.strip() \
                and not GameTime.is_canonical(expires):
            gt = game_time_at(expires)
            if gt is None:
                stats["unparsable"] += 1
            else:
                payload["expires_at"] = gt.canonical()
                changed = True

        if changed or (game_ts or "") != stamp:
            updates.append((stamp, json.dumps(payload, ensure_ascii=False), row_id))

    for start in range(0, len(updates), _BATCH):
        chunk = updates[start:start + _BATCH]
        with transaction() as conn:
            conn.executemany(
                "UPDATE events SET game_ts=?, payload=? WHERE id=?", chunk)
        stats["events"] += len(chunk)


def _migrate_diary(stats: Dict[str, int]) -> None:
    """``diary_entries.game_ts`` + the real date inside ``meta.metadata.date``.

    A diary entry is dated by the GAME day it covers. Old rows carry that day
    as a real ``YYYY-MM-DD`` in their meta, and that key — not the technical
    ``ts``, which is merely when the LLM finished writing — is what the entry
    is about. It is therefore mapped through the SAME conversion the summary
    rollups used (:func:`_summary_key_to_game`), so a diary day and a daily
    summary of the same real date land on the same game day. Only rows without
    a usable date fall back to back-projecting ``ts``.
    """
    from app.core.db import get_connection, transaction
    from app.core.timeutils import game_time_at

    rows = get_connection().execute(
        "SELECT id, ts, game_ts, meta FROM diary_entries "
        "WHERE game_ts IS NULL OR game_ts=''").fetchall()
    updates: List[Tuple[str, str, Any]] = []
    for row_id, ts, _game_ts, raw_meta in rows:
        try:
            meta = json.loads(raw_meta or "{}")
        except ValueError:
            meta = {}
        if not isinstance(meta, dict):
            meta = {}
        metadata = meta.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        date_key = str(metadata.get("date") or "").strip()

        day_key: Optional[str] = None
        if date_key:
            if _GAME_KEY_RES[0].match(date_key):
                day_key = date_key            # already a game day
            else:
                day_key = _summary_key_to_game(date_key, "daily", stats)
        if day_key:
            stamp = f"{day_key}T00:00:00"
            metadata["date"] = day_key
            meta["metadata"] = metadata
        else:
            gt = game_time_at(ts)
            if gt is None:
                stats["unparsable"] += 1
                continue
            stamp = gt.canonical()
        updates.append((stamp, json.dumps(meta, ensure_ascii=False), row_id))

    for start in range(0, len(updates), _BATCH):
        chunk = updates[start:start + _BATCH]
        with transaction() as conn:
            conn.executemany(
                "UPDATE diary_entries SET game_ts=?, meta=? WHERE id=?", chunk)
        stats["diary"] += len(chunk)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def migrate_game_calendar_once() -> Dict[str, int]:
    """Convert every persisted GAME stamp to the canonical GameTime form.

    Safe to call on every boot: already-canonical values are skipped, so a
    migrated world reports all-zero counters.
    """
    stats: Dict[str, int] = {key: 0 for key in _COUNTER_KEYS}
    groups = (
        ("anchor", _migrate_anchor),
        ("sleep_start", _migrate_sleep_start),
        ("thoughts", _migrate_thoughts),
        ("profiles", _migrate_profiles),
        ("scheduler", _migrate_scheduler),
        ("cron_fields", _migrate_cron_fields),
        ("intents", _migrate_intents),
        ("summaries", _migrate_summaries),
        ("memories", _migrate_memories),
        ("events", _migrate_events),
        ("diary", _migrate_diary),
        ("state_history", _migrate_state_history),
    )
    for label, fn in groups:
        try:
            fn(stats)
        except Exception as e:  # noqa: BLE001 — a group must not stop the others
            logger.warning("game calendar migration group %s failed: %s", label, e)
    if any(stats[k] for k in _COUNTER_KEYS):
        logger.info("Game calendar migration: %s", stats)
    return stats
