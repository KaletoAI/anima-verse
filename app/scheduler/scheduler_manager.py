"""
SchedulerManager - manages time-driven jobs per character.

Jobs are stored per character:
  storage/users/{user}/characters/{name}/scheduler/jobs.json
  storage/users/{user}/characters/{name}/scheduler/job_logs.json

On startup every character directory is scanned for schedulers.

All schedule semantics run on the GAME clock and the world calendar
(plan-game-calendar.md §2.6): trigger stamps are canonical ``GameTime``
strings, cron fields are ``minute``/``hour``/``day_of_season``/``season``/
``weekday`` — there are no real-world months or weekdays here.
"""

import json

from app.core.game_time import DAY_SECONDS, GameDuration, GameTime, get_calendar
from app.core.timeutils import game_time, parse_iso, utc_now, utc_now_iso
from pathlib import Path
from typing import Dict, List, Any, Optional
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.core.log import get_logger

logger = get_logger("scheduler")

# Catch-up window: an occurrence older than this is skipped silently instead
# of fired late (mirrors the former 3-day misfire grace, in GAME days).
CATCH_UP_WINDOW = GameDuration.of(days=3)

# Sentinel value for home_location: the character sleeps outside the world
# (no concrete location/room). While asleep it does not appear on the map but
# in the "no location" tray with a sleep marker.
OFFMAP_SLEEP_SENTINEL = "__offmap__"


class SchedulerManager:
    """
    Manages time-driven jobs for characters.
    Jobs are stored per user + character.
    Supports interval, cron and one-time jobs.
    """

    def __init__(self):
        """Initializes the SchedulerManager and loads jobs from all character directories."""
        self.project_root = Path(__file__).parent.parent.parent

        # APScheduler
        self.scheduler = BackgroundScheduler()
        self.scheduler.start()
        # GAME-TIME dispatcher (user decision 2026-07-11): character jobs
        # ('at 08:00', 'every 2h', one-shot dates) are IN-WORLD schedules and
        # follow the game clock. Jobs register in _game_jobs instead of
        # per-job APScheduler triggers; one 30s real-time tick checks
        # due-ness in game time (factor-aware; frozen world = frozen clock =
        # nothing advances).
        self._game_jobs = {}
        self.scheduler.add_job(self._game_dispatch, IntervalTrigger(seconds=30),
                               id="_game_dispatch", replace_existing=True)

        # In-memory job data (one flat list of all jobs)
        self.jobs_data = {
            "jobs": [],
            "metadata": {
                "created_at": utc_now_iso(),
                "last_updated": utc_now_iso(),
                "total_jobs": 0
            }
        }

        # One-time migration away from the global storage
        self._migrate_global_jobs()

        # Load the jobs of every character directory
        self._load_all_character_jobs()

        # Legacy cleanup: world_hourly_tick was replaced by the central
        # world-admin tick (app/core/periodic_jobs.py). Purge leftover
        # entries so they do not show up in the scheduler UI, where the user
        # would see and could delete them.
        try:
            removed = self._purge_legacy_world_hourly_job()
            if removed:
                logger.info("world_hourly_tick: %d legacy entries removed "
                            "(replaced by periodic_jobs)", removed)
        except Exception as _ple:
            logger.debug("world_hourly_tick legacy purge: %s", _ple)

        # Legacy cleanup: activity_done_* one-time jobs were replaced by
        # the state-based path (profile.activity_started_at +
        # _sub_activity_expiry in the world_admin_tick). Purge leftover
        # entries so the scheduler UI stays clean.
        try:
            removed = self._purge_legacy_activity_done_jobs()
            if removed:
                logger.info("activity_done_*: %d legacy one-time jobs removed "
                            "(replaced by periodic_jobs._sub_activity_expiry)",
                            removed)
        except Exception as _ple:
            logger.debug("activity_done legacy purge: %s", _ple)

        logger.info("Initialized with %d jobs", len(self.jobs_data["jobs"]))

    def _migrate_global_jobs(self):
        """Moves jobs from the global storage/scheduler/jobs.json into the per-character directories."""
        from app.models.character import save_character_scheduler_jobs, save_character_scheduler_logs

        global_jobs_file = self.project_root / "storage" / "scheduler" / "jobs.json"
        global_logs_file = self.project_root / "storage" / "scheduler" / "job_logs.json"

        if not global_jobs_file.exists():
            return

        try:
            data = json.loads(global_jobs_file.read_text(encoding="utf-8"))
            jobs = data.get("jobs", []) if isinstance(data, dict) else data
        except Exception as e:
            logger.error("Migration: read failed: %s", e)
            return

        if not jobs:
            global_jobs_file.rename(global_jobs_file.with_suffix(".json.migrated"))
            return

        # Group the jobs by character
        grouped = {}
        for job in jobs:
            user_id = job.get("user_id", "")
            character = job.get("character", job.get("agent", ""))
            # Normalize: make sure the character field is set
            if character and "character" not in job:
                job["character"] = character
            key = (character)
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(job)

        migrated_count = 0
        for (character), char_jobs in grouped.items():
            if not character:
                logger.warning("Migration: skipping jobs without a character")
                continue
            try:
                save_character_scheduler_jobs(character, char_jobs)
                migrated_count += len(char_jobs)
            except Exception as e:
                logger.error("Migration failed for %s: %s", character, e)

        # Migrate the logs
        if global_logs_file.exists():
            try:
                logs = json.loads(global_logs_file.read_text(encoding="utf-8"))
                # Map the logs onto their jobs
                job_char_map = {}
                for job in jobs:
                    job_char_map[job["id"]] = (
                        job.get("user_id", ""),
                        job.get("character", job.get("agent", ""))
                    )

                logs_by_char = {}
                for log_entry in logs:
                    job_id = log_entry.get("job_id", "")
                    key = job_char_map.get(job_id, ("", ""))
                    if key[0] and key[1]:
                        if key not in logs_by_char:
                            logs_by_char[key] = []
                        logs_by_char[key].append(log_entry)

                for (character), char_logs in logs_by_char.items():
                    save_character_scheduler_logs(character, char_logs)

                global_logs_file.rename(global_logs_file.with_suffix(".json.migrated"))
                logger.info("Migration: logs migrated")
            except Exception as e:
                logger.error("Migration: log migration failed: %s", e)

        # Rename the global file
        global_jobs_file.rename(global_jobs_file.with_suffix(".json.migrated"))
        logger.info("Migration: %d jobs moved into per-character storage", migrated_count)

    def _load_all_character_jobs(self):
        """Scans every character directory and loads its scheduler jobs.

        Covers the active storage directory (worlds/) as well as the legacy
        one (storage/users/) for backwards compatibility.
        """
        scanned_dirs = set()

        # 1. Active storage directory (worlds/{name}/characters/)
        try:
            from app.core.paths import get_storage_dir
            storage_dir = get_storage_dir()
            for subdir_name in ("characters", "agents"):
                characters_dir = storage_dir / subdir_name
                if characters_dir.exists() and str(characters_dir) not in scanned_dirs:
                    scanned_dirs.add(str(characters_dir))
                    self._load_jobs_from_characters_dir(characters_dir)
        except Exception as e:
            logger.warning("Loading from the storage dir failed: %s", e)

        # 2. Legacy: storage/users/{user}/characters/
        users_dir = self.project_root / "storage" / "users"
        if users_dir.exists():
            for user_dir in users_dir.iterdir():
                if not user_dir.is_dir():
                    continue
                for subdir_name in ("characters", "agents"):
                    characters_dir = user_dir / subdir_name
                    if characters_dir.exists() and str(characters_dir) not in scanned_dirs:
                        scanned_dirs.add(str(characters_dir))
                        self._load_jobs_from_characters_dir(characters_dir)

        self.jobs_data["metadata"]["total_jobs"] = len(self.jobs_data["jobs"])
        logger.info("%d jobs loaded from the character directories", len(self.jobs_data["jobs"]))

        # 3. Re-sync daily schedules: a character with a daily_schedule.json
        #    but no matching job in memory gets its job recreated.
        self._resync_daily_schedules()

    def _load_jobs_from_characters_dir(self, characters_dir: Path):
        """Loads the jobs of one characters/ directory — DB first, JSON fallback."""
        from app.models.character import get_character_scheduler_jobs
        for char_dir in characters_dir.iterdir():
            if not char_dir.is_dir():
                continue
            char_name = char_dir.name
            try:
                jobs = get_character_scheduler_jobs(char_name)
            except Exception as e:
                logger.error("Loading the jobs of %s from the DB failed: %s", char_name, e)
                # JSON fallback
                jobs_path = char_dir / "scheduler" / "jobs.json"
                if not jobs_path.exists():
                    continue
                try:
                    data = json.loads(jobs_path.read_text(encoding="utf-8"))
                    jobs = data.get("jobs", []) if isinstance(data, dict) else data
                except Exception as e2:
                    logger.error("Loading %s from JSON failed: %s", jobs_path, e2)
                    continue

            for job in jobs:
                # make sure the character field is set
                if not job.get("character") and job.get("agent"):
                    job["character"] = job["agent"]
                if not job.get("character"):
                    job["character"] = char_name
                # avoid duplicates
                if not any(j["id"] == job["id"] for j in self.jobs_data["jobs"]):
                    self.jobs_data["jobs"].append(job)
                    if job.get("enabled", True):
                        self._schedule_job(job)

    def _resync_daily_schedules(self):
        """Phase-2/4 cleanup: daily-schedule enforcement is gone, the daily
        schedule only acts as a hint in the AgentLoop (``daily_schedule_block``).

        This only removes legacy cron-job entries from the jobs list
        (per-char ``daily_schedule`` type + ``daily_schedule_marker`` stubs)
        and no longer creates new markers. World-administrative tasks run
        via the ``world_admin_tick`` in ``app/core/periodic_jobs.py``
        (not through this scheduler anymore).
        """
        try:
            stale_types = {"daily_schedule", "daily_schedule_marker"}
            stale = [j for j in list(self.jobs_data["jobs"])
                     if (j.get("action", {}) or {}).get("type") in stale_types]
            for j in stale:
                logger.info("Removing legacy daily job: %s", j.get("id"))
                self.remove_job(j["id"])
        except Exception as e:
            logger.warning("Daily-schedule resync failed: %s", e)

    def _save_jobs_for_character(self, character: str):
        """Persists the jobs of one character only."""
        if not character:
            return

        from app.models.character import save_character_scheduler_jobs

        char_jobs = [
            j for j in self.jobs_data["jobs"]
            if j.get("character") == character or j.get("agent") == character
        ]
        try:
            save_character_scheduler_jobs(character, char_jobs)
        except Exception as e:
            logger.error("Saving the jobs of %s failed: %s", character, e)

        self.jobs_data["metadata"]["last_updated"] = utc_now_iso()
        self.jobs_data["metadata"]["total_jobs"] = len(self.jobs_data["jobs"])

    def _schedule_job(self, job_config: Dict[str, Any]):
        """Registers a job for game-time dispatch based on its config."""
        job_id = job_config.get('id')
        trigger_config = job_config.get('trigger', {})
        trigger_type = trigger_config.get('type', 'interval')

        # Marker jobs are purely visual (e.g. per-char daily-schedule
        # indicator) — never dispatched, only kept in jobs_data.
        if trigger_type == 'marker':
            return

        try:
            if trigger_type == 'date':
                # Stale-date check in GAME time: a run_date more than 3 game
                # days in the past is dropped instead of fired late.
                run_date = trigger_config.get('run_date')
                try:
                    rd = GameTime.parse(run_date) if run_date else None
                    if rd and (game_time() - rd) > CATCH_UP_WINDOW:
                        logger.info("Stale date job %s skipped (run_date %s is more "
                                    "than 3 game days in the past) — removing it",
                                    job_id, run_date)
                        self._purge_job_from_data(job_id)
                        return
                except (ValueError, TypeError) as _stale_e:
                    logger.warning("Job %s: run_date %r is not a canonical GameTime "
                                   "string — stale check skipped (%s)",
                                   job_id, run_date, _stale_e)
            elif trigger_type == 'interval':
                total = (int(trigger_config.get('seconds', 0) or 0)
                         + int(trigger_config.get('minutes', 0) or 0) * 60
                         + int(trigger_config.get('hours', 0) or 0) * 3600
                         + int(trigger_config.get('days', 0) or 0) * 86400)
                if total == 0:
                    logger.warning("Job %s is scheduled as an interval job but has no "
                                   "frequency. Skipping.", job_id)
                    return
            elif trigger_type != 'cron':
                logger.warning("Unknown trigger type: %s", trigger_type)
                return

            # Baseline for jobs without a prior execution: registration time
            # in GAME time — a daily-08:00 job created at 10:00 must not fire
            # for the already-passed occurrence.
            job_config.setdefault('_registered_game', game_time().canonical())
            self._game_jobs[job_id] = job_config
            logger.info("Job scheduled (game-time): %s (%s)", job_id, trigger_type)
        except Exception as e:
            logger.error("Failed to schedule job %s: %s", job_id, e)

    # ── Game-time dispatch ────────────────────────────────────────────────

    @staticmethod
    def _cron_field(cfg, key):
        """Cron field as int or None (=any). Expressions ('*/2', lists) are
        not supported by the game-time matcher — treated as 'any' with a
        warning (character jobs from the UI use plain values)."""
        v = cfg.get(key)
        if v in (None, "", "*"):
            return None
        try:
            return int(v)
        except (TypeError, ValueError):
            logger.warning("Cron field %s=%r is not supported (game-time) — treated as 'any'", key, v)
            return None

    @staticmethod
    def _cron_season(cfg, calendar):
        """``season`` field as a validated season KEY, or None (=any)."""
        v = cfg.get('season')
        if v in (None, "", "*"):
            return None
        key = str(v).strip()
        if calendar.season_by_key(key) is None:
            logger.warning("Cron field season=%r is not a season key of this world's "
                           "calendar — treated as 'any'", v)
            return None
        return key

    @staticmethod
    def _cron_weekday(cfg, calendar):
        """``weekday`` field as a 0-based index, or None (=any).

        Accepts the index itself or a name from the calendar's ``week_days``.
        A world without weeks has no weekday to match, so the constraint is
        dropped with a warning instead of never firing.
        """
        v = cfg.get('weekday')
        if v in (None, "", "*"):
            return None
        if not calendar.week_days:
            logger.warning("Cron field weekday=%r ignored: this world's calendar has "
                           "no week days — treated as 'any'", v)
            return None
        names = [n.strip().lower() for n in calendar.week_days]
        if isinstance(v, str) and not v.strip().lstrip("+-").isdigit():
            try:
                return names.index(v.strip().lower())
            except ValueError:
                logger.warning("Cron field weekday=%r is not one of %s — treated as "
                               "'any'", v, list(calendar.week_days))
                return None
        try:
            idx = int(v)
        except (TypeError, ValueError):
            logger.warning("Cron field weekday=%r is not supported — treated as 'any'", v)
            return None
        if not 0 <= idx < len(names):
            logger.warning("Cron field weekday=%d is out of range (0..%d) — treated as "
                           "'any'", idx, len(names) - 1)
            return None
        return idx

    @staticmethod
    def _last_cron_occurrence(cfg, now: GameTime) -> Optional[GameTime]:
        """Most recent cron occurrence <= ``now``, in GAME time.

        Fields are plain ints / a season key; None = any:
        ``minute``, ``hour``, ``day_of_season`` (1..season length),
        ``season`` (season KEY), ``weekday`` (index or week-day name).
        Real-world date fields are gone — the world calendar has seasons and
        days, not months and real weekdays; the boot migration in
        ``app.core.game_calendar_migration`` converts old jobs once.

        The walk is a bounded backwards loop over whole GAME days; the time
        of day inside a matching day is computed, not stepped, so a
        minute-granular schedule costs the same as a daily one.
        """
        cal = get_calendar()
        minute = SchedulerManager._cron_field(cfg, 'minute')
        hour = SchedulerManager._cron_field(cfg, 'hour')
        day_of_season = SchedulerManager._cron_field(cfg, 'day_of_season')
        season = SchedulerManager._cron_season(cfg, cal)
        weekday = SchedulerManager._cron_weekday(cfg, cal)

        def _date_ok(day: GameTime) -> bool:
            p = day.parts(cal)
            if day_of_season is not None and p.day_of_season != day_of_season:
                return False
            if season is not None:
                key = cal.seasons[p.season_index].key if cal.seasons else ""
                if key != season:
                    return False
            if weekday is not None and p.day_index % len(cal.week_days) != weekday:
                return False
            return True

        def _time_on(day_start: GameTime, limit: GameTime) -> Optional[GameTime]:
            """Latest occurrence within ``day_start``..``limit``, or None."""
            if hour is not None:
                # An unset minute means :00 of that hour (as before).
                cand = day_start.replace(hour=hour, minute=minute or 0, second=0)
                return cand if cand <= limit else None
            if minute is not None:
                # Every hour at :minute — pick the latest hour that fits.
                cand = day_start.replace(hour=limit.hour, minute=minute, second=0)
                if cand > limit:
                    if limit.hour == 0:
                        return None
                    cand = day_start.replace(hour=limit.hour - 1, minute=minute,
                                             second=0)
                return cand
            # Every minute.
            return limit.replace(second=0)

        # Iteration cap — the loop steps whole GAME days, so this is a number
        # of days. A season / day-of-season constraint repeats once per year,
        # so ``year_days`` steps always suffice (the old flat 400 did NOT:
        # reaching last year's winter day 19 takes ~year_days steps). Combined
        # with a weekday constraint the match drifts by (year_days mod week
        # length) days per year, so it can take up to ``week length`` years —
        # hence the factor. +100 is slack for calendars edited since the job
        # was created.
        year_days = cal.year_days or 1
        max_days = year_days + 100
        if weekday is not None and (season is not None or day_of_season is not None):
            max_days = year_days * len(cal.week_days) + 100

        day = now.start_of_day()
        for i in range(max_days):
            limit = now if i == 0 else day.replace(hour=23, minute=59, second=59)
            if _date_ok(day):
                cand = _time_on(day, limit)
                if cand is not None:
                    return cand
            if day.total_seconds < DAY_SECONDS:
                break  # reached the world epoch — nothing earlier exists
            day = day - GameDuration.of(days=1)
        return None

    @staticmethod
    def _game_anchor(job_config) -> Optional[GameTime]:
        """The job's GAME-time anchor, or None when it has none (yet).

        Cascade: last execution → registration baseline → creation stamp.
        ``last_execution.timestamp`` and ``created_at`` are SYSTEM stamps and
        only ever parse here for worlds whose migration wrote game stamps into
        them; anything unparsable is treated as "no anchor" and the cascade
        continues (warning only for the fields that ARE game stamps).
        """
        last = job_config.get('last_execution', {}) or {}
        candidates = (
            ('last_execution.game_timestamp', last.get('game_timestamp'), True),
            ('last_execution.timestamp', last.get('timestamp'), False),
            ('_registered_game', job_config.get('_registered_game'), True),
            ('created_at', job_config.get('created_at'), False),
        )
        for field, raw, is_game_stamp in candidates:
            if not raw:
                continue
            try:
                return GameTime.parse(raw)
            except (ValueError, TypeError):
                if is_game_stamp:
                    logger.warning("Job %s: %s=%r is not a canonical GameTime string "
                                   "— ignored as an anchor",
                                   job_config.get('id'), field, raw)
        return None

    def _job_due(self, job_config) -> bool:
        """Due-ness of a registered job in GAME time."""
        cfg = job_config.get('trigger', {}) or {}
        ttype = cfg.get('type', 'interval')
        now_g = game_time()
        last = job_config.get('last_execution', {}) or {}
        anchor = self._game_anchor(job_config)
        # Game clock set backwards: re-anchor to now instead of ghost-firing.
        if anchor and anchor > now_g:
            stamp = now_g.canonical()
            job_config['_registered_game'] = stamp
            if last:
                last['game_timestamp'] = stamp
            return False

        if ttype == 'date':
            rd_raw = cfg.get('run_date')
            if not rd_raw:
                return False
            try:
                rd = GameTime.parse(rd_raw)
            except (ValueError, TypeError):
                logger.warning("Job %s: run_date %r is not a canonical GameTime string "
                               "— job never fires", job_config.get('id'), rd_raw)
                return False
            fired = last.get('game_timestamp') or last.get('timestamp')
            return now_g >= rd and not fired

        if ttype == 'interval':
            period = (int(cfg.get('seconds', 0) or 0)
                      + int(cfg.get('minutes', 0) or 0) * 60
                      + int(cfg.get('hours', 0) or 0) * 3600
                      + int(cfg.get('days', 0) or 0) * 86400)
            if period <= 0 or not anchor:
                return False
            return (now_g - anchor).seconds >= period

        if ttype == 'cron':
            occ = self._last_cron_occurrence(cfg, now_g)
            if occ is None:
                return False
            if anchor and occ <= anchor:
                return False  # occurrence already covered
            # Catch-up window in GAME days; older occurrences are skipped.
            return (now_g - occ) <= CATCH_UP_WINDOW

        return False

    def _game_dispatch(self):
        """30s real-time tick: fires every registered job that is due in
        GAME time. _execute_job keeps its frozen-check, one-time cleanup and
        last_execution persistence."""
        # Frozen world = frozen game clock: nothing can become due, and a
        # job that was already due must wait (fires once after unfreeze).
        # Checking here once avoids a per-job skip log every 30s.
        try:
            from app.models.world import is_world_frozen
            if is_world_frozen():
                return
        except Exception:
            pass
        for job_id, job_config in list(self._game_jobs.items()):
            try:
                if not self._job_due(job_config):
                    continue
                self._execute_job(job_config)
                # Date jobs fire once — drop them from the live registry
                # (one_time additionally removes them from jobs_data inside
                # _execute_job; plain date jobs stay listed but done).
                if (job_config.get('trigger', {}) or {}).get('type') == 'date':
                    self._game_jobs.pop(job_id, None)
            except Exception as e:
                logger.error("Game dispatch of job %s failed: %s", job_id, e)

    def _purge_job_from_data(self, job_id: str):
        """Removes a job from jobs_data and persists it per character.
        Used for stale date jobs that are already more than 3 game days old
        when they are loaded.
        """
        try:
            removed = []
            kept = []
            for j in self.jobs_data.get('jobs', []):
                if j.get('id') == job_id:
                    removed.append(j)
                else:
                    kept.append(j)
            if not removed:
                return
            self.jobs_data['jobs'] = kept
            chars = {j.get('character', '') for j in removed if j.get('character')}
            from app.models.character import save_character_scheduler_jobs
            for ch in chars:
                ch_jobs = [j for j in kept if j.get('character') == ch]
                save_character_scheduler_jobs(ch, ch_jobs)
        except Exception as e:
            logger.error("Stale-job purge of %s failed: %s", job_id, e)

    def _execute_job(self, job_config: Dict[str, Any]):
        """Executes a job based on its configuration."""
        job_id = job_config.get('id')
        action = job_config.get('action', {})
        action_type = action.get('type')
        user_id = job_config.get('user_id', '')
        agent = job_config.get('character', job_config.get('agent', ''))

        logger.info("Executing job: %s (%s)", job_id, action_type)

        # World freeze: scheduled jobs do not fire while the world is
        # frozen (robust for jobs created during the freeze, too).
        try:
            from app.models.world import is_world_frozen
            if is_world_frozen():
                logger.info("Job %s skipped: world frozen", job_id)
                self._log_execution(job_id, "skipped", {"reason": "world frozen"})
                return
        except Exception:
            pass

        # Sleep check: sleeping characters do not execute jobs.
        if agent and user_id:
            from app.models.character import is_character_sleeping
            if is_character_sleeping(agent):
                logger.info("Job %s skipped: %s is asleep", job_id, agent)
                self._log_execution(job_id, "skipped", {"reason": "character asleep"})
                # Re-anchor: the occurrence counts as consumed ("slept
                # through it"), otherwise the game-time dispatcher would
                # retry every 30s until the character wakes up.
                job_config["last_execution"] = {
                    "timestamp": utc_now_iso(),
                    "game_timestamp": game_time().canonical(),
                    "success": False,
                    "skipped": "sleeping",
                }
                try:
                    self._save_jobs_for_character(agent)
                except Exception as e:
                    logger.error("Saving last_execution failed: %s", e)
                return

        try:
            result = None

            if action_type == 'send_message':
                result = self._action_send_message(action, agent)
            elif action_type == 'intent_bump':
                # at_time intent (plan-intents-unified.md): bump the owner
                # with a hint at the planned time — the character decides
                # itself whether and how to act.
                try:
                    from app.core.agent_loop import get_agent_loop
                    get_agent_loop().bump(agent, hint=action.get("hint", ""))
                    result = {"success": True, "action": "intent_bump",
                              "intent_id": action.get("intent_id", "")}
                except Exception as _ie:
                    result = {"success": False, "error": str(_ie)}
            elif action_type == 'notify':
                result = self._action_notify(action, agent)
            elif action_type == 'execute_tool':
                # Phase-4 cleanup: execute_tool as a character-driven action
                # is gone — tool use runs through the AgentLoop (the character
                # decides itself). Existing jobs are ignored.
                logger.warning("Action 'execute_tool' is deactivated (phase-4 cleanup) — "
                               "job %s ignored (tool=%s)", job_id,
                               action.get("tool_name") or "?")
                result = {"success": False, "error": "execute_tool action is deactivated"}
            elif action_type == 'set_status':
                result = self._action_set_status(action, agent)
            elif action_type == 'daily_schedule':
                # Phase-2 cleanup: daily_schedule is no longer enforced —
                # the AgentLoop reads the data as a hint via
                # daily_schedule_block.
                logger.warning("Action 'daily_schedule' is deactivated (phase-2 cleanup) — "
                               "character %s is driven by the AgentLoop itself", agent)
                result = {"success": False, "error": "daily_schedule action is deactivated"}
            elif action_type == 'world_hourly_tick':
                # Obsolete — replaced by the central world-admin tick
                # (app/core/periodic_jobs.py). Kept as a defensive no-op in
                # case a stored job entry was not removed by
                # _purge_legacy_world_hourly_job yet.
                result = {"success": True, "action": "world_hourly_tick",
                          "note": "deprecated — handled by app.core.periodic_jobs"}
            elif action_type == 'extract_files':
                result = self._action_extract_files(action, agent)
            elif action_type == 'custom':
                # Phase-1 cleanup: 'custom' was a dead stub feature without
                # any real function. Existing custom jobs are ignored with a
                # warning; the action handler method is gone.
                logger.warning("Action 'custom' is deactivated (phase-1 cleanup) — job %s ignored",
                               action.get("function") or "?")
                result = {"success": False, "error": "action 'custom' is disabled"}
            else:
                logger.warning("Unknown action type: %s", action_type)
                result = {"success": False, "error": f"Unknown action type: {action_type}"}

            self._log_execution(job_id, "success", result)
            logger.info("Job succeeded: %s", job_id)
            job_config["last_execution"] = {
                "timestamp": utc_now_iso(),
                "game_timestamp": game_time().canonical(),
                "success": True
            }

        except Exception as e:
            logger.error("Executing job %s failed: %s", job_id, e)
            self._log_execution(job_id, "error", {"error": str(e)})
            job_config["last_execution"] = {
                "timestamp": utc_now_iso(),
                "game_timestamp": game_time().canonical(),
                "success": False
            }

        # Remove one-time (date trigger) jobs after execution
        if job_config.get('trigger', {}).get('one_time'):
            try:
                self.jobs_data['jobs'] = [
                    j for j in self.jobs_data['jobs'] if j.get('id') != job_id
                ]
                self._game_jobs.pop(job_id, None)
                logger.info("One-time job removed: %s", job_id)
            except Exception as e:
                logger.error("One-time job cleanup: %s", e)

        # Persist last_execution
        if agent:
            try:
                self._save_jobs_for_character(agent)
            except Exception as e:
                logger.error("Saving last_execution failed: %s", e)

    def _action_send_message(self, action: Dict[str, Any], agent: str) -> Dict[str, Any]:
        """Phase-3: instead of writing the message straight into the
        history, the character is bumped in the AgentLoop with a hint.

        On its next thought turn the character sees the hint "you wanted to
        send this message: <text>" and decides itself whether to send it (via
        the SendMessage tool), to reword it, or to skip it because it no
        longer fits.
        """
        message = (action.get('message') or '').strip()
        if not message:
            return {"success": False, "error": "no message given"}
        if not agent:
            return {"success": False, "error": "no agent set"}

        try:
            from app.core.agent_loop import get_agent_loop
            from app.models.account import get_active_character
            avatar = (get_active_character() or "user").strip()
            hint = (
                f"You scheduled a message for {avatar}: \"{message}\". "
                f"Decide now whether to send it via SendMessage (you may "
                f"adjust the wording), or skip if it's no longer relevant."
            )
            ok = get_agent_loop().bump(agent, hint=hint)
            if ok:
                logger.info("send_message: %s bumped with a hint (%d chars)",
                            agent, len(message))
                return {"success": True, "action": "send_message",
                        "delivered_via": "agent_loop_bump"}
            return {"success": False,
                    "error": f"AgentLoop.bump rejected {agent} (ineligible)"}
        except Exception as e:
            logger.error("send_message bump failed: %s", e)
            return {"success": False, "error": str(e)}

    def _action_notify(self, action: Dict[str, Any], agent: str) -> Dict[str, Any]:
        """Creates a notification only (no chat POST).

        For lightweight notices such as status updates.
        """
        message = action.get('message', '')
        notification_type = action.get('notification_type', 'system')
        metadata = action.get('metadata', {})
        if not message:
            return {"success": False, "error": "no message given"}
        try:
            from app.models.notifications import create_notification
            nid = create_notification(
                character=agent,
                content=message,
                notification_type=notification_type,
                metadata=metadata)
            logger.info("Notification created: %s (%s)", nid, agent)
            return {"success": True, "action": "notify", "notification_id": nid}
        except Exception as e:
            logger.error("notify failed: %s", e)
            return {"success": False, "error": str(e)}


    def _action_set_status(self, action, agent):
        """Sets a character's location, room and/or mood directly.

        ``location`` in the action is a location ID (post-migration).
        Player-controlled characters are skipped (no autonomous status
        changes). The scheduler no longer sets an activity/pose (the activity
        library is gone) — poses emerge freely in chat / the AgentLoop.
        """
        from app.models.account import is_player_controlled
        if is_player_controlled(agent):
            return {"skipped": True, "reason": "Character player-controlled"}

        # Grace window against chat interference: a recent location change
        # via chat/user must not be steamrolled by the scheduler.
        try:
            from datetime import timedelta
            from app.models.character import get_character_profile
            _profile = get_character_profile(agent) or {}
            RECENT_CHAT_GRACE_MINUTES = 30
            _cutoff = utc_now() - timedelta(minutes=RECENT_CHAT_GRACE_MINUTES)
            _ts = (_profile.get("location_changed_at") or "").strip()
            if _ts:
                try:
                    if parse_iso(_ts) > _cutoff:
                        logger.info("Scheduler skip %s: location_changed_at is recent (%s)",
                                     agent, _ts[:19])
                        return {"skipped": True,
                                "reason": f"location_changed_at within {RECENT_CHAT_GRACE_MINUTES}min"}
                except Exception:
                    pass
        except Exception as _ge:
            logger.debug("Grace check for %s failed: %s", agent, _ge)

        location = action.get('location', '')
        mood = action.get('mood', '')

        # __llm_choice__ slot: the AgentLoop decides itself.
        if location == "__llm_choice__":
            return {"success": False, "error":
                    "__llm_choice__ slot ignored — AgentLoop chooses autonomously"}

        from app.models.world import (get_location_name as _get_loc_name,
                                       resolve_location, get_location,
                                       get_arrival_room_id)
        if location:
            loc_obj = resolve_location(location)
            if loc_obj:
                location = loc_obj.get("id", location)

        try:
            from app.models.character import (
                save_character_current_location,
                save_character_current_feeling, save_character_current_room,
                get_character_current_location)

            if location:
                # Leave check: pinning/confinement must not be bypassed.
                try:
                    from app.models.rules import check_leave
                    cur_loc_for_leave = get_character_current_location(agent) or ""
                    if cur_loc_for_leave:
                        leave_ok, leave_reason = check_leave(
                            agent, target_location_id=location)
                        if not leave_ok:
                            logger.info("Scheduler: leave blocked for %s (cur=%s -> tgt=%s): %s",
                                        agent, cur_loc_for_leave, location, leave_reason)
                            try:
                                from app.models.character import record_access_denied
                                from app.models.world import get_location_name as _gln
                                _cur_name = _gln(cur_loc_for_leave) or cur_loc_for_leave
                                record_access_denied(agent, cur_loc_for_leave, _cur_name,
                                                      leave_reason, action="leave")
                            except Exception:
                                logger.debug("record_access_denied(scheduler-leave) failed", exc_info=True)
                            location = cur_loc_for_leave
                except Exception:
                    pass

                # Access check: may the character enter that location?
                try:
                    from app.models.rules import check_access
                    rules_ok, rules_reason = check_access(agent, location)
                    if not rules_ok:
                        logger.info("Scheduler: rule blocked %s -> %s", agent, location)
                        try:
                            from app.models.character import record_access_denied
                            from app.models.world import get_location_name
                            loc_name = get_location_name(location) or location
                            record_access_denied(agent, location, loc_name, rules_reason)
                        except Exception:
                            logger.debug("record_access_denied failed", exc_info=True)
                        location = get_character_current_location(agent)  # stay put

                except Exception:
                    pass

                old_loc = get_character_current_location(agent)
                save_character_current_location(agent, location)
                # On a real location change, put the agent in the new place's
                # arrival room — the declared entry room, or its ground.
                if location and location != old_loc:
                    try:
                        _ld = get_location(location)
                        _room = get_arrival_room_id(_ld) if _ld else ""
                    except Exception:
                        _room = ""
                    save_character_current_room(agent, _room or "")

            if mood:
                save_character_current_feeling(agent, mood)

            parts = []
            if location:
                parts.append(f"{_get_loc_name(location)}")
            if mood:
                parts.append(f"Mood: {mood}")
            logger.info("Status set: %s -> %s", agent, ", ".join(parts))

            if location:
                self._try_social_dialog(agent, location)

            return {"success": True, "action": "set_status",
                    "location": location, "mood": mood}
        except Exception as e:
            logger.error("set_status failed: %s", e)
            return {"success": False, "error": str(e)}

    def _try_social_dialog(self, agent: str, location: str):
        """Checks for other characters at the same location and may start a dialog."""
        import random
        from app.models.character import (
            list_available_characters, get_character_current_location,
            get_character_config, is_character_sleeping)
        from app.models.character_template import is_feature_enabled as _feat

        # Feature gate: no start at all when the initiator lacks social_dialog
        if not _feat(agent, "social_dialog_enabled"):
            return

        all_chars = list_available_characters()
        chars_at_location = [
            c for c in all_chars
            if c != agent and get_character_current_location(c) == location
            and not is_character_sleeping(c)
            and _feat(c, "social_dialog_enabled")
        ]

        if not chars_at_location:
            return

        agent_config = get_character_config(agent)
        agent_prob = int(agent_config.get("social_dialog_probability", 50))

        for other in chars_at_location:
            other_config = get_character_config(other)
            other_prob = int(other_config.get("social_dialog_probability", 50))

            # Probability = the minimum of both values
            probability = min(agent_prob, other_prob)
            roll = random.randint(1, 100)

            if roll > probability:
                logger.debug("SocialDialog %s <-> %s: skip (roll %d > %d%%)", agent, other, roll, probability)
                continue

            logger.info("SocialDialog %s <-> %s: dialog! (roll %d <= %d%%)", agent, other, roll, probability)

            # Run asynchronously via the BackgroundQueue
            from app.core.background_queue import get_background_queue
            get_background_queue().submit("social_dialog", {
                "user_id": "",
                "sender": agent,
                "target": other,
                "location": location,
            })

    def _action_extract_files(self, action: Dict[str, Any], agent: str) -> Dict[str, Any]:
        """Administrative file-extraction action.

        Calls the knowledge-extraction skill directly (phase-4 cleanup;
        previously bridged via the removed ``_action_execute_tool``).
        Looked up by SKILL_ID, not tool name — the display name is package
        template data and may change. Stays admin-only — no character
        behaviour, no LLM in the character's name.
        """
        try:
            from app.core.dependencies import get_skill_manager
            sm = get_skill_manager()
            skill = sm.get_skill("knowledge_extract")
            if not skill:
                return {"success": False, "error": "knowledge_extract skill not loaded"}
            payload = json.dumps({
                "input": action.get("extraction_prompt", ""),
                "agent_name": agent,
                "user_id": "",
            })
            result = skill.execute(payload)
            logger.info("knowledge_extract result: %s",
                        result[:200] if result else "")
            return {"success": True, "action": "extract_files",
                    "result": result[:500] if result else ""}
        except Exception as e:
            logger.error("extract_files failed: %s", e)
            return {"success": False, "error": str(e)}

    def _log_execution(self, job_id: str, status: str, result: Any):
        """Logs a job execution into the per-character log file."""
        from app.models.character import get_character_scheduler_logs, save_character_scheduler_logs

        log_entry = {
            "timestamp": utc_now_iso(),
            "job_id": job_id,
            "status": status,
            "result": result
        }

        # Find the job to determine user_id + character
        job = None
        for j in self.jobs_data["jobs"]:
            if j["id"] == job_id:
                job = j
                break

        if job:
            character = job.get("character", job.get("agent", ""))
            if character:
                try:
                    logs = get_character_scheduler_logs(character)
                    logs.append(log_entry)
                    logs = logs[-1000:]
                    save_character_scheduler_logs(character, logs)
                    return
                except Exception as e:
                    logger.error("Logging failed: %s", e)

        # Global job without a character — no per-character log file, just
        # the DEBUG console.
        logger.debug("Global job log: %s", log_entry)

    def add_job(
        self, agent: str,
        trigger: Dict[str, Any],
        action: Dict[str, Any],
        job_id: Optional[str] = None,
        enabled: bool = True
    ) -> Dict[str, Any]:
        """
        Adds a new job.

        Args:
            agent: character name
            trigger: trigger configuration
            action: action configuration
            job_id: optional job ID (generated when omitted)
            enabled: whether the job is active
        """
        if job_id is None:
            job_id = f"{agent}_{utc_now().strftime('%Y%m%d_%H%M%S')}"

        if any(job['id'] == job_id for job in self.jobs_data['jobs']):
            return {"success": False, "error": f"job ID {job_id} already exists"}

        job_config = {
            "id": job_id,
            "user_id": "",
            "character": agent,
            "enabled": enabled,
            "trigger": trigger,
            "action": action,
            "created_at": utc_now_iso()
        }

        self.jobs_data['jobs'].append(job_config)

        if enabled:
            self._schedule_job(job_config)

        self._save_jobs_for_character(agent)

        return {
            "success": True,
            "job_id": job_id,
            "message": "job added"
        }

    def remove_job(self, job_id: str) -> Dict[str, Any]:
        """Removes a job"""
        job_index = None
        job = None
        for i, j in enumerate(self.jobs_data['jobs']):
            if j['id'] == job_id:
                job_index = i
                job = j
                break

        if job_index is None:
            return {"success": False, "error": f"job {job_id} not found"}

        self._game_jobs.pop(job_id, None)

        character = job.get("character", job.get("agent", ""))
        self.jobs_data['jobs'].pop(job_index)
        self._save_jobs_for_character(character)

        return {"success": True, "message": f"job {job_id} removed"}

    def sync_daily_schedule(self, character: str, schedule: Dict[str, Any]) -> int:
        """Persists the character's daily schedule.

        Since phase-2 the daily schedule is no longer enforced by cron jobs —
        it is only a hint block in the thought prompt
        (``daily_schedule_block`` in ``thought_context.py``). All that happens
        here is slot validation and resolving locations to IDs.

        Returns: 1 when the schedule is active, otherwise 0.
        """
        # 1. Remove legacy per-character daily jobs (they ran in parallel -> race)
        daily_jobs = [
            j for j in list(self.jobs_data["jobs"])
            if (j.get("character") == character or j.get("agent") == character)
            and j.get("source") == "daily_schedule"
        ]
        for j in daily_jobs:
            self.remove_job(j["id"])

        if not schedule.get("enabled", False):
            return 0

        slots = schedule.get("slots", [])
        if not slots:
            return 0

        # Resolve location names to IDs and persist them in the schedule
        from app.models.world import resolve_location as _resolve_loc
        for slot in slots:
            if slot.get("sleep"):
                continue
            raw_loc = slot.get("location", "")
            if raw_loc:
                loc_obj = _resolve_loc(raw_loc)
                if loc_obj and loc_obj.get("id"):
                    slot["location"] = loc_obj["id"]

        # 2. Per-character marker job — a purely visual signal in the UI
        #    that the daily schedule is active. The marker has NO cron
        #    trigger (it is never executed); world-administrative tasks
        #    (status decay, force rules, random events, ...) run centrally in
        #    app/core/periodic_jobs.py since the world-admin-tick refactor.
        #    The ``world_hourly_tick`` job created here before was a phase-2
        #    cleanup stub and is completely obsolete now.
        marker_id = f"daily_schedule_{character}"
        self.jobs_data["jobs"] = [
            j for j in self.jobs_data["jobs"] if j.get("id") != marker_id
        ]
        self.jobs_data["jobs"].append({
            "id": marker_id,
            "character": character,
            "enabled": True,
            "source": "daily_schedule",
            "trigger": {"type": "marker"},
            "action": {"type": "daily_schedule_marker",
                       "slots_count": len(slots)},
            "created_at": utc_now_iso(),
        })
        self._save_jobs_for_character(character)
        return 1

    def _purge_legacy_world_hourly_job(self) -> int:
        """Removes leftover entries of the obsolete world_hourly_tick job.

        Called from the SchedulerManager init. Since the refactor the
        world-admin actions run centrally in ``app/core/periodic_jobs.py``
        (asyncio tick, 60s by default, configurable). The old hourly cron job
        was a no-op stub the user could delete by accident — so it is cleaned
        out of the world data.

        Returns: number of removed entries.
        """
        job_id = "world_hourly_tick"
        before = len(self.jobs_data["jobs"])
        self.jobs_data["jobs"] = [
            j for j in self.jobs_data["jobs"] if j.get("id") != job_id]
        removed = before - len(self.jobs_data["jobs"])
        # Remove it from APScheduler too, in case it was scheduled already
        try:
            if self.scheduler.get_job(job_id):
                self.scheduler.remove_job(job_id)
        except Exception:
            pass
        return removed

    def _purge_legacy_activity_done_jobs(self) -> int:
        """Removes obsolete ``activity_done_*`` one-time jobs.

        ``set_activity_skill._schedule_duration_complete`` used to create one
        one-shot job per activity that reset the activity when it ran out.
        Since the refactor this runs in the ``world_admin_tick`` off
        profile-state fields (``activity_started_at`` +
        ``activity_duration_minutes``). Leftover entries could still show up
        in the scheduler UI — purge them once at init and unhook them from
        APScheduler.

        Returns: number of removed entries.
        """
        before = len(self.jobs_data["jobs"])
        legacy_ids = [
            j.get("id") for j in self.jobs_data["jobs"]
            if (j.get("id") or "").startswith("activity_done_")
        ]
        if not legacy_ids:
            return 0
        self.jobs_data["jobs"] = [
            j for j in self.jobs_data["jobs"]
            if not (j.get("id") or "").startswith("activity_done_")]
        for jid in legacy_ids:
            try:
                if self.scheduler.get_job(jid):
                    self.scheduler.remove_job(jid)
            except Exception:
                pass
        return before - len(self.jobs_data["jobs"])

    def _was_recently_chatting(self, character: str, minutes: int = 10) -> bool:
        """Whether the character chatted with the user in the last N minutes.

        Covers 1:1 chats (chat_messages table) as well as group chats.
        """
        threshold = minutes * 60  # in seconds
        now = utc_now()

        # 1:1 chat: the most recent ts in chat_messages for this character.
        # (Used to be the filesystem mtime — useless after the DB-only
        # migration.)
        try:
            from app.core.db import get_connection
            row = get_connection().execute(
                "SELECT ts FROM chat_messages WHERE character_name=? "
                "ORDER BY ts DESC LIMIT 1",
                (character,)).fetchone()
            if row and row[0]:
                try:
                    last_ts = parse_iso(row[0])
                except (ValueError, TypeError):
                    last_ts = None
                if last_ts:
                    age_s = (now - last_ts).total_seconds()
                    if 0 <= age_s < threshold:
                        logger.info("Location change blocked: %s was in a 1:1 chat "
                                    "%.0f min ago", character, age_s / 60)
                        return True
        except Exception as e:
            logger.debug("Checking the 1:1 chat activity failed: %s", e)

        # Group chat: last_activity of active sessions with this character
        try:
            from app.models.group_chat import load_sessions
            sessions = load_sessions()
            for s in sessions:
                if not s.get("active", True):
                    continue
                if character not in s.get("participants", []):
                    continue
                last_activity = s.get("last_activity", "")
                if last_activity:
                    activity_ts = parse_iso(last_activity).timestamp()
                    if (now_ts - activity_ts) < threshold:
                        logger.info("Location change blocked: %s was in group chat "
                                    "%s %.0f min ago", character, s.get("id", "?"),
                                    (now_ts - activity_ts) / 60)
                        return True
        except Exception as e:
            logger.debug("Checking the group chat activity failed: %s", e)

        return False

    def toggle_job(self, job_id: str) -> Dict[str, Any]:
        """Enables/disables a job"""
        job = None
        for j in self.jobs_data['jobs']:
            if j['id'] == job_id:
                job = j
                break

        if job is None:
            return {"success": False, "error": f"job {job_id} not found"}

        job['enabled'] = not job.get('enabled', True)

        if job['enabled']:
            self._schedule_job(job)
        else:
            self._game_jobs.pop(job_id, None)

        character = job.get("character", job.get("agent", ""))
        self._save_jobs_for_character(character)

        return {
            "success": True,
            "enabled": job['enabled'],
            "message": f"job {job_id} {'enabled' if job['enabled'] else 'disabled'}"
        }

    def run_job_now(self, job_id: str) -> Dict[str, Any]:
        """Runs a job immediately (regardless of its schedule)."""
        job = None
        for j in self.jobs_data['jobs']:
            if j['id'] == job_id:
                job = j
                break

        if job is None:
            return {"success": False, "error": f"job {job_id} not found"}

        self._execute_job(job)

        return {"success": True, "message": f"job {job_id} is running"}

    def get_jobs(self, agent: Optional[str] = None) -> List[Dict[str, Any]]:
        """Returns all jobs (optionally filtered by character)."""
        jobs = self.jobs_data['jobs']

        if agent:
            jobs = [j for j in jobs if j.get('character') == agent or j.get('agent') == agent]

        return jobs

    def get_job_logs(self, job_id: Optional[str] = None, limit: int = 100,
                     character: Optional[str] = None) -> List[Dict[str, Any]]:
        """Returns job logs (optionally filtered)."""
        from app.models.character import get_character_scheduler_logs

        # Load the per-character logs
        if character:
            logs = get_character_scheduler_logs(character)
            if job_id:
                logs = [log for log in logs if log.get('job_id') == job_id]
            return logs[-limit:]

        # Job ID given: determine the character from the job
        if job_id:
            for j in self.jobs_data["jobs"]:
                if j["id"] == job_id:
                    char = j.get("character", j.get("agent", ""))
                    if char:
                        logs = get_character_scheduler_logs(char)
                        logs = [log for log in logs if log.get('job_id') == job_id]
                        return logs[-limit:]

        # No filter: aggregate all logs (DB first, JSON fallback)
        from app.models.character import (
            list_available_characters, get_character_scheduler_logs)
        all_logs = []
        try:
            all_chars = list_available_characters()
        except Exception:
            all_chars = []
        for char in all_chars:
            try:
                all_logs.extend(get_character_scheduler_logs(char))
            except Exception:
                pass
        # JSON fallback for characters that were not found
        if not all_logs:
            users_dir = self.project_root / "storage" / "users"
            if users_dir.exists():
                for user_dir in users_dir.iterdir():
                    if not user_dir.is_dir():
                        continue
                    for subdir_name in ("characters", "agents"):
                        characters_dir = user_dir / subdir_name
                        if not characters_dir.exists():
                            continue
                        for char_dir in characters_dir.iterdir():
                            logs_path = char_dir / "scheduler" / "job_logs.json"
                            if logs_path.exists():
                                try:
                                    logs = json.loads(logs_path.read_text(encoding="utf-8"))
                                    all_logs.extend(logs)
                                except Exception:
                                    pass

        all_logs.sort(key=lambda x: x.get("timestamp", ""))
        return all_logs[-limit:]

    def shutdown(self):
        """Shuts the scheduler down."""
        logger.info("Shutting the scheduler down...")
        self.scheduler.shutdown()


def _was_chatted_recently(character_name: str,
                          within_minutes: int = 10) -> bool:
    """True when the last chat with this character is younger than
    ``within_minutes`` minutes.

    Reads the newest ``ts`` from ``chat_messages`` (world.db). This used to be
    the ``chats/*.json`` mtime, which finds nothing since the unified_chat
    refactor.
    """
    try:
        from app.core.db import get_connection
        from datetime import datetime
        conn = get_connection()
        row = conn.execute(
            "SELECT ts FROM chat_messages WHERE character_name=? "
            "ORDER BY ts DESC LIMIT 1",
            (character_name,)).fetchone()
        if not row or not row[0]:
            return False
        last_ts = parse_iso(row[0])
        age_s = (utc_now() - last_ts).total_seconds()
        return age_s < within_minutes * 60
    except Exception:
        return False
