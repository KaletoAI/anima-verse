"""World-Admin-Tick — zentraler Hintergrund-Job fuer alle administrativen
Welt-Aktionen.

Frueher liefen mehrere periodic-Tasks parallel (status, assignment-expiry,
random-events, relationship-decay). Konsolidiert auf EINEN Tick mit
konfigurierbarem Intervall (Default 60s, ``world.admin_tick_interval_seconds``).
Sub-Tasks haben eigene Frequenzen (per Modulo / Last-Run-Tracking) und
laufen sequenziell innerhalb des Ticks — verhindert Race-Conditions
zwischen den vorherigen parallelen Tasks und gibt einen einzigen
Anpassungspunkt fuer die Welt-Tick-Frequenz.

Sub-Tasks die laufen pro Tick (mit eigener Sub-Frequenz):
    - status_tick               — apply_hourly_status_tick (interner 1h-Gate)
    - force_rules               — Pruefe alle Force-Rules pro Char (jeder Tick)
    - assignment_expiry         — expire_overdue (jeder Tick)
    - random_events_generate    — alle 3600s
    - random_events_escalate    — alle 300s
    - random_events_resolve     — alle 300s
    - relationship_decay        — alle 24h (Handler hat eigenen Cooldown)

Tick-Intervall ist im Game Admin → Settings → Server konfigurierbar.
Bereich 10s-3600s. Jobs sind nicht einzeln deaktivierbar — wenn du sie
nicht willst, setz das Intervall hoch oder deaktiviere die jeweilige
Welt-Pause-Schalter.

Public API:
    start() / stop() — registriert vom server.py lifespan
"""
import asyncio
from datetime import datetime

from app.core.timeutils import utc_now
from typing import Callable, Dict, List, Optional

from app.core.log import get_logger

logger = get_logger("periodic_jobs")


# Default-Tick-Intervall wenn config-Wert fehlt oder ungueltig.
_DEFAULT_TICK_SECONDS = 60
# Untere/obere Grenzen — schuetzt vor versehentlich kaputter Config (z.B.
# 0s wuerde den Loop sofort spammen).
_MIN_TICK_SECONDS = 10
_MAX_TICK_SECONDS = 3600


def _is_paused() -> bool:
    """Mirrors AgentLoop pause source — task_queue 'default' pause flag —
    PLUS der persistente World-Freeze (autonome Simulation eingefroren)."""
    try:
        from app.models.world import is_world_frozen
        if is_world_frozen():
            return True
    except Exception:
        pass
    try:
        from app.core.task_queue import get_task_queue
        tq = get_task_queue()
        return bool(tq and tq._is_paused("default"))
    except Exception:
        return False


def _get_tick_interval() -> int:
    """Liest ``server.world_admin_tick_interval_seconds`` aus der Config,
    geclamped auf [_MIN_TICK_SECONDS, _MAX_TICK_SECONDS]."""
    try:
        from app.core import config as _cfg
        val = int(_cfg.get("server.world_admin_tick_interval_seconds")
                  or _DEFAULT_TICK_SECONDS)
    except Exception:
        val = _DEFAULT_TICK_SECONDS
    return max(_MIN_TICK_SECONDS, min(_MAX_TICK_SECONDS, val))


# ---------------------------------------------------------------------------
# Sub-Task Implementierungen — laufen synchron im Threadpool, weil sie
# DB/Disk-IO machen und das Event-Loop sonst blockieren wuerden.
# ---------------------------------------------------------------------------

def _sub_status_tick():
    """Apply hourly stat decay to all characters. Internal 1h gating in
    apply_hourly_status_tick — billig auch jede Minute aufzurufen."""
    try:
        from app.core.activity_engine import apply_hourly_status_tick, cleanup_expired_conditions
        from app.models.character import list_available_characters
        for name in list_available_characters():
            try:
                apply_hourly_status_tick(name)
                # Abklingzeit: abgelaufene Conditions (duration_hours) jede Minute
                # entfernen — NICHT am 1h-Gate des Status-Ticks haengen, sonst
                # klingen Effekte bis zu eine Stunde zu spaet ab.
                cleanup_expired_conditions(name)
            except Exception as e:
                logger.debug("status_tick failed for %s: %s", name, e)
    except Exception as e:
        logger.debug("status_tick sub error: %s", e)


def _sub_flag_lifecycle():
    """TTL decay for package-declared state flags (flag lifecycle executor).
    Generic — flag names, prompts and TTLs come from the packages'
    plugin.yaml declarations."""
    try:
        from app.core.flag_lifecycle import decay_tick
        decay_tick()
    except Exception as e:
        logger.debug("flag_lifecycle sub error: %s", e)


def _sub_force_rules():
    """Force-Rules pro Char pruefen — z.B. Wake-Rule (stamina>X +
    activity:sleeping → activity=""). Vorher nur 1x/h im hourly tick;
    jetzt jeden Welt-Admin-Tick — Reaktion auf Schwellwert-Wechsel
    innerhalb Minuten statt Stunden."""
    try:
        from app.models.rules import (
            check_force_rules, resolve_force_destination)
        from app.models.character import (
            list_available_characters,
            get_character_current_location, get_character_current_room,
            get_effective_activity,
            save_character_current_location,
            save_character_current_room,
            enter_offmap_sleep, wake_from_offmap,
            OFFMAP_SLEEP_SENTINEL,
            _record_state_change)
        from app.models.account import is_player_controlled
        for name in list_available_characters():
            try:
                if is_player_controlled(name):
                    continue  # Avatar nicht zwingen
                force = check_force_rules(name)
                if not force:
                    continue
                go_to = force.get("go_to") or "stay"
                dest_loc, dest_room = resolve_force_destination(name, go_to)

                # Vorher-Snapshot: erlaubt am Ende zu erkennen ob die Regel
                # tatsaechlich was geaendert hat. Ohne Aenderung kein
                # _record_state_change(forced_action) — sonst spammt eine
                # Erschoepfungs-/Wake-Regel jede Minute das Tagebuch.
                _before_loc = (get_character_current_location(name) or "").strip()
                _before_room = (get_character_current_room(name) or "").strip()
                _before_act = (get_effective_activity(name) or "").strip().lower()

                # Offmap-Sentinel: nicht als echte Location speichern. Wenn
                # home=__offmap__ → Char vom Grid nehmen via enter_offmap_sleep.
                if dest_loc == OFFMAP_SLEEP_SENTINEL:
                    if _before_loc:  # nur wechseln wenn der Char gerade auf der Karte ist
                        try:
                            enter_offmap_sleep(name)
                        except Exception:
                            pass
                    dest_loc = ""  # kein weiterer save_character_current_location
                    dest_room = ""

                if dest_loc:
                    save_character_current_location(name, dest_loc)
                if dest_room:
                    save_character_current_room(name, dest_room)

                # B1: orthogonale State-Flags sind die Autoritaet (z.B.
                # is_sleeping false zum Wecken, true fuer einen Schlafzauber).
                # Das fruehere set_activity (sleeping/"") ist durch set_flags
                # ersetzt. Beim Aufwecken zusaetzlich vom Off-Map zurueckholen.
                _flags_changed = False
                _set_flags = force.get("set_flags") or {}
                if _set_flags:
                    from app.models.character import (
                        set_is_sleeping, set_is_wet, set_is_intimate,
                        set_decency_exempt, set_state_flag, get_state_flags)
                    # Flag-specific setters carry side effects (off-map etc.);
                    # every OTHER flag DECLARED by a skill package goes through
                    # the generic setter — values may be bool or string
                    # (value-carrying flags like body_reaction="erected").
                    _setters = {"is_sleeping": set_is_sleeping,
                                "is_wet": set_is_wet,
                                "is_intimate": set_is_intimate,
                                "decency_exempt": set_decency_exempt}
                    _declared = set()
                    try:
                        from app.plugins.registry import flag_specs
                        _declared = {s.flag for s in flag_specs()}
                    except Exception:
                        pass
                    def _norm(v):
                        return v if isinstance(v, str) and v else bool(v)
                    _before_flags = get_state_flags(name)
                    for _fk, _fv in _set_flags.items():
                        if _norm(_before_flags.get(_fk)) == _norm(_fv):
                            continue
                        if _fk in _setters:
                            _setters[_fk](name, bool(_fv))
                        elif _fk in _declared:
                            set_state_flag(name, _fk, _norm(_fv))
                        else:
                            continue  # unknown flag — not declared anywhere
                        _flags_changed = True
                        if _fk == "is_sleeping" and not _fv:
                            try:
                                wake_from_offmap(name)
                            except Exception:
                                pass

                # Nur loggen + ins Tagebuch wenn sich was geaendert hat.
                _after_loc = (get_character_current_location(name) or "").strip()
                _after_room = (get_character_current_room(name) or "").strip()
                _after_act = (get_effective_activity(name) or "").strip().lower()
                _changed = (_before_loc != _after_loc
                            or _before_room != _after_room
                            or _before_act != _after_act
                            or _flags_changed)
                if not _changed:
                    continue

                _record_state_change(
                    name, "forced_action",
                    force.get("message") or force.get("rule_name") or "",
                    metadata={"rule": force.get("rule_name", ""),
                              "go_to": go_to,
                              "flags": force.get("set_flags", {})})
                logger.info("Force-Rule %s -> %s (%s)",
                            force.get("rule_name", "?"), name, go_to)
            except Exception as _ce:
                logger.debug("force_rules check failed for %s: %s", name, _ce)
    except Exception as e:
        logger.debug("force_rules sub error: %s", e)


def _sub_assignment_expiry():
    # Intents (plan-intents-unified.md): überfällige Intents auf 'expired' setzen.
    try:
        from app.models.intents import expire_overdue
        expire_overdue()
    except Exception as e:
        logger.debug("intent_expiry sub error: %s", e)


def _sub_random_events_generate():
    try:
        from app.core.random_events import check_and_generate
        check_and_generate()
    except Exception as e:
        logger.debug("random_events_generate sub error: %s", e)


def _sub_random_events_escalate():
    try:
        from app.core.random_events import check_escalation
        check_escalation()
    except Exception as e:
        logger.debug("random_events_escalate sub error: %s", e)


def _sub_random_events_resolve():
    try:
        from app.core.random_events import try_resolve_events
        try_resolve_events()
    except Exception as e:
        logger.debug("random_events_resolve sub error: %s", e)


def _sub_relationship_decay():
    try:
        from app.core.background_queue import get_background_queue
        get_background_queue().submit(
            "relationship_decay", {"user_id": ""}, deduplicate=True)
    except Exception as e:
        logger.debug("relationship_decay sub error: %s", e)


def _sub_variant_prune():
    """LRU-Eviction stale Expression-Variants pro Character.

    Cap kommt aus ``server.variants_max_per_character`` (Default 30). Variants
    mit aktuellstem ``last_used_at`` ueberleben.
    """
    try:
        from app.core.expression_regen import prune_variants_all
        removed = prune_variants_all()
        if removed:
            logger.info("variant_prune: %d alte Variants entfernt", removed)
    except Exception as e:
        logger.debug("variant_prune sub error: %s", e)


def _sub_reap_orphaned_avatars():
    """Avatar-only Characters von Usern ohne gueltige Session offmap setzen
    (Session-Timeout ohne Logout). Siehe plan-avatar-only-presence.md."""
    try:
        from app.models.account import reap_orphaned_avatars
        reaped = reap_orphaned_avatars()
        if reaped:
            logger.info("reap_orphaned_avatars: %d verwaiste Avatar(s) verschwunden", reaped)
    except Exception as e:
        logger.debug("reap_orphaned_avatars sub error: %s", e)


def _sub_day_consolidation():
    """Tages-Konsolidierung: pro Character prüfen, ob ein Wach-Block zu schließen
    ist (Hauptschlaf erkannt oder Stau-Fallback) → Szenen → 1 Tages-Eintrag.
    (plan-history-consolidation-cleanup.md, Phase 2)
    """
    try:
        from app.core import day_consolidation as dc
        from app.models.character import list_available_characters
        total = 0
        for name in list_available_characters():
            try:
                total += dc.maybe_consolidate(name)
            except Exception as e:
                logger.debug("day_consolidation(%s) error: %s", name, e)
        if total:
            logger.info("day_consolidation: %d Szenen in Tages-Einträge eingeklappt", total)
    except Exception as e:
        logger.debug("day_consolidation sub error: %s", e)


def _sub_lora_library_sync():
    """LoRA-library discovery: reconciles image_generation.lora_triggers
    against every backend with a LoRA listing (lora_url). Adds discovered
    LoRAs, flags manual ones as missing, drops vanished untouched discoveries.
    """
    try:
        from app.core.lora_library import sync_lora_library
        sync_lora_library()  # logs its own summary when something changed
    except Exception as e:
        logger.debug("lora_library_sync sub error: %s", e)


# Sub-Task-Tabelle: (callable, min_interval_seconds, label).
# min_interval_seconds = wie oft soll dieser Sub-Task LAUFEN. Der Tick
# selbst feuert haeufiger; jeder Sub-Task wird nur ausgefuehrt wenn seit
# der letzten Ausfuehrung mindestens min_interval_seconds vergangen sind.
# Sub-Tasks ohne minimum (=0) laufen jeden Tick.
_SUB_TASKS: List[tuple] = [
    # (func,                         min_interval_s,        label)
    (_sub_status_tick,               60,                    "status_tick"),
    (_sub_flag_lifecycle,            60,                    "flag_lifecycle"),
    (_sub_force_rules,               0,                     "force_rules"),
    (_sub_assignment_expiry,         60,                    "assignment_expiry"),
    # 60s tick — the generator gates itself to one roll per GAME hour
    # (random_events._LAST_GENERATE_GAME), so events keep pace with the
    # game-clock factor instead of rolling once per REAL hour.
    (_sub_random_events_generate,    60,                    "random_events_generate"),
    (_sub_random_events_escalate,    300,                   "random_events_escalate"),
    (_sub_random_events_resolve,     300,                   "random_events_resolve"),
    (_sub_relationship_decay,        24 * 3600,             "relationship_decay"),
    (_sub_variant_prune,             3600,                  "variant_prune"),
    (_sub_day_consolidation,         600,                   "day_consolidation"),
    (_sub_reap_orphaned_avatars,     300,                   "reap_orphaned_avatars"),
    (_sub_lora_library_sync,         3600,                  "lora_library_sync"),
]


# ---------------------------------------------------------------------------
# Tick-Loop
# ---------------------------------------------------------------------------

_tick_task: Optional[asyncio.Task] = None
_last_run: Dict[str, float] = {}  # label -> unix-ts of last successful run


async def _world_admin_tick_loop():
    """Eine asyncio-Task fuer alle Welt-Admin-Aktionen. Ruft Sub-Tasks
    sequenziell, jeder mit eigener Sub-Frequenz."""
    # Initial-Delay: vermeidet dass alle Sub-Tasks beim ersten Tick gemeinsam
    # feuern (CPU-Spike). Default 30s damit der Server zuerst hochkommt.
    try:
        await asyncio.sleep(30)
    except asyncio.CancelledError:
        return

    while True:
        try:
            interval = _get_tick_interval()
            if not _is_paused():
                now = utc_now().timestamp()
                for func, min_iv, label in _SUB_TASKS:
                    last = _last_run.get(label, 0.0)
                    if min_iv and (now - last) < min_iv:
                        continue
                    started = utc_now()
                    try:
                        await asyncio.to_thread(func)
                        _last_run[label] = utc_now().timestamp()
                    except Exception as _se:
                        logger.error("admin_tick sub %s error: %s",
                                     label, _se, exc_info=True)
                    duration = (utc_now() - started).total_seconds()
                    if duration > 5:
                        logger.info("admin_tick %s done in %.1fs", label, duration)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("admin_tick loop error: %s", e, exc_info=True)
        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            return


def start() -> None:
    """Startet den zentralen World-Admin-Tick als asyncio-Task."""
    global _tick_task
    if _tick_task is not None and not _tick_task.done():
        return
    _tick_task = asyncio.create_task(_world_admin_tick_loop())
    logger.info("World-Admin-Tick gestartet (interval=%ds)", _get_tick_interval())


async def stop() -> None:
    global _tick_task
    if _tick_task is None:
        return
    _tick_task.cancel()
    try:
        await _tick_task
    except (asyncio.CancelledError, Exception):
        pass
    _tick_task = None
    _last_run.clear()
    logger.info("World-Admin-Tick gestoppt")
