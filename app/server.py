"""Main FastAPI application - Refactored modular structure"""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.core.log import get_logger

logger = get_logger("server")


class _SuppressHealthPolling(logging.Filter):
    """Suppress noisy polling endpoints from uvicorn access logs."""
    _SUPPRESS = {
        "/queue/status",
        "/health",
        "/notifications/unread-count",
        "/history?limit=",  # Chat-History polling vom Frontend
    }

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not any(ep in msg for ep in self._SUPPRESS)


logging.getLogger("uvicorn.access").addFilter(_SuppressHealthPolling())
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path

# Initialize storage paths first (CLI --storage / --world / STORAGE_DIR env)
from app.core import paths as _paths
_paths.init()

# Load JSON config from the (now-known) storage directory. The load itself is
# read-only; migrate_file() is the ONE place that persists the dead-field strip
# and the default seeding — the running world's config.json stays current,
# while every script that merely loads a world leaves it untouched.
from app.core.config import load as _load_config, migrate_file as _migrate_config_file
_load_config(_paths.get_config_path())
_migrate_config_file(_paths.get_config_path())

# Welt-DB initialisieren (idempotent, legt world.db an falls noetig)
from app.core.db import init_schema as _init_db_schema
_init_db_schema()

# Einmalige Migration: alte status_modifiers.json -> prompt_filters-Tabelle.
# Idempotent: nur wenn die Datei existiert + Eintraege noch nicht in der DB
# stehen. Datei wird danach in *.migrated umbenannt.
try:
    from app.core.prompt_filters import migrate_status_modifiers_once
    migrate_status_modifiers_once()
except Exception:
    pass

# Import routers
from app.routes import auth, store, characters, chat, group_chat, scheduler, instagram, world, telegram, templates, story, story_dev, world_dev, tts, queue as queue_route, logs, admin, notifications, dashboard, events, relationships, intents, diary
from app.routes import admin_settings
from app.routes import user_gallery
from app.routes import assets
from app.routes import clip_catalog_loops
from app.routes import game_audio
from app.routes import poses as poses_route
from app.routes import secrets
from app.routes import inventory
from app.routes import account
from app.routes import i18n as i18n_route
from app.routes import state as state_route
from app.routes import game_admin as game_admin_route
from app.routes import world_setup as world_setup_route
from app.routes import storyteller as storyteller_route
from app.routes import observer as observer_route
from app.routes import play as play_route
from app.routes import api_images as api_images_route
from app.routes import assist as assist_route
from app.routes import prop_variants as prop_variants_route
from app.scheduler.scheduler_manager import SchedulerManager
from app.core.dependencies import initialize_channels, get_skill_manager
from app.core.provider_manager import initialize_provider_manager
from app.core.tts_service import initialize_tts_service, clear_tts_tmp

# Global Scheduler Instance
_scheduler_manager = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle Manager für Server-Start und Shutdown"""
    global _scheduler_manager

    # Startup
    # Temporaere Dateien loeschen
    from app.routes.story import clear_story_tmp
    clear_story_tmp()
    clear_tts_tmp()

    # Log retention: entries older than the window are moved out of
    # llm_calls.jsonl + image_prompts.jsonl into their monthly bucket under
    # logs/archive/ (default 5 days, configurable via server.log_retention_days
    # in the admin config). Keeps the live logs from growing without bound
    # without losing the history.
    try:
        from app.utils.llm_logger import prune_logs_on_startup
        _log_pruned = prune_logs_on_startup()
        if _log_pruned.get("archived"):
            logger.info("Log retention: %s", _log_pruned)
    except Exception as _le:
        logger.warning("Log retention at startup failed: %s", _le)

    # Multiuser: Default-Admin bootstrappen falls noch kein User existiert
    from app.core.users import ensure_default_admin
    ensure_default_admin()

    # Migration: Persistente Location-IDs hinzufuegen, Filesystem bereinigen
    from app.models.world import migrate_location_ids
    migrate_location_ids()

    # World calendar: the game clock stopped being a datetime. Every persisted
    # GAME stamp (clock anchor, sleep starts, thought game_ts, condition /
    # state-flag / journey stamps, scheduler + intent run dates) is rewritten
    # ONCE into the canonical GameTime form. Idempotent by format — an already
    # migrated world converts nothing. See plan-game-calendar.md §2.4.
    try:
        from app.core.game_calendar_migration import migrate_game_calendar_once
        _gc = migrate_game_calendar_once()
        if any(_gc.values()):
            logger.info("Game calendar migration: %s", _gc)
    except Exception as _gce:
        logger.warning("game calendar migration failed: %s", _gce)

    # 3D-Massstab: EIN Rahmen (das Bezugsquadrat = der Fussabdruck der
    # Location, Kante map3d.plan_width_m) + EIN Skalierungsfaktor.
    # Traegt plan_width_m/storey_height_m aus den alten Modell-Feldern
    # heraus, bevor diese verschwinden (2026-07-28).
    try:
        from app.core.location_model3d import migrate_scale_frame_once
        _sf = migrate_scale_frame_once()
        if _sf:
            logger.info("3D-Massstab migriert: %s", _sf)
    except Exception as _sfe:
        logger.warning("scale-frame migration failed: %s", _sfe)

    # Surface textures are shared across all worlds, not per world: leftover
    # world folders hand their files to shared/surface_textures/ once, on boot
    # (E5 Task 4, 2026-08-12). The sweep covers EVERY world under the worlds
    # root, not just the one that is open — otherwise a world without an old
    # folder migrates nothing and strands the others (finding B9). Must run
    # BEFORE the kind-meta migration below — that one reads the shared library.
    try:
        from app.core.surface_textures import migrate_world_dirs_once
        _sd = migrate_world_dirs_once()
        if _sd:
            logger.info("Surface texture folder handover to shared: %s", _sd)
    except Exception as _sde:
        logger.warning("surface texture move to shared failed: %s", _sde)

    # Surface kinds: name / ID / description kept apart. Writes the curated
    # wording ONCE into the description field so it stops being an invisible
    # runtime precedence (2026-07-28). Idempotent by content.
    try:
        from app.core.surface_textures import migrate_kind_meta_once
        _km = migrate_kind_meta_once()
        if _km:
            logger.info("Surface kinds migrated: %s", _km)
    except Exception as _kme:
        logger.warning("surface kind-meta migration failed: %s", _kme)

    # A terrain kind now SAYS which surface it wears (terrain_types.surface);
    # the old "same name = same material" match is gone without a fallback.
    # Writes the assignment the old rule derived into every world row, once,
    # so no existing ground is undressed. Runs AFTER the two library
    # migrations above — it asks the library which ids exist.
    try:
        from app.core.terrain_surface_migration import (
            migrate_terrain_surfaces_once)
        _ts = migrate_terrain_surfaces_once()
        if _ts.get("assigned"):
            logger.info("Terrain surfaces assigned: %s", _ts)
    except Exception as _tse:
        logger.warning("terrain surface migration failed: %s", _tse)

    # The micro-relief belongs to the painted AREA now, not to the terrain KIND
    # (2026-08-23): a kind-level amplitude made every meadow in a world equally
    # bumpy. The kind lost the two keys without a fallback reader, so the value
    # the old rule would have used is copied onto every area of that kind once
    # — otherwise every existing world would flatten on this boot. Runs AFTER
    # the surface migration for no reason but order; the two do not touch.
    try:
        from app.core.terrain_relief_migration import migrate_area_relief_once
        _tr = migrate_area_relief_once()
        if _tr and (_tr.get("areas") or _tr.get("kept")):
            logger.info("Terrain relief moved to the areas: %s", _tr)
    except Exception as _tre:
        logger.warning("terrain relief migration failed: %s", _tre)

    # Prop-Marker benennen jetzt die OBERFLAECHE; der Sitz-Absatz reist als
    # root_offset im Payload mit. Hebt die gespeicherten Brueche um genau
    # diesen Betrag an, damit sich optisch nichts bewegt (2026-07-28).
    try:
        from app.core.props import migrate_marker_surface_once
        _pm = migrate_marker_surface_once()
        if _pm:
            logger.info("Prop-Marker migriert: %s", _pm)
    except Exception as _pme:
        logger.warning("prop marker migration failed: %s", _pme)

    # Vereinheitlichte Intents (plan-intents-unified.md, Phase 1): bestehende
    # Assignments idempotent in die intents-Tabelle spiegeln. Kein Verhaltens-
    # wechsel — assignments bleiben in Phase 1 die treibende Quelle.
    try:
        from app.models.intents import migrate_assignments_to_intents
        migrate_assignments_to_intents()
    except Exception as _ie:
        logger.debug("intents migration failed: %s", _ie)

    # Klon-Hygiene: off-map / Duplikate / Waisen entfernen.
    from app.models.world import cleanup_orphan_clones
    _cleanup_stats = cleanup_orphan_clones()
    if _cleanup_stats.get("removed"):
        logger.info("Klon-Cleanup beim Start: %s", _cleanup_stats)

    # Background-Hygiene: tote Datei-Referenzen in background_images +
    # gallery_meta.json + prompts.json prunen. Loescht keine Dateien.
    from app.models.world import cleanup_orphan_backgrounds
    _bg_stats = cleanup_orphan_backgrounds()
    if _bg_stats.get("pruned_bgs") or _bg_stats.get("pruned_meta"):
        logger.info("Background-Cleanup beim Start: %s", _bg_stats)

    # Orphan-Files: Galerie-PNGs ohne jegliche Referenz nach
    # world_gallery_backup/ verschieben (nicht loeschen). Laeuft NACH
    # dem DB/Meta-Cleanup, damit gerade-erst gepunete Referenzen nicht
    # faelschlich Files am Leben halten.
    from app.models.world import move_orphan_gallery_files
    _orphan_stats = move_orphan_gallery_files()
    if _orphan_stats.get("moved"):
        logger.info("Orphan-Bilder verschoben: %s", _orphan_stats)

    # Migration: Variant-Dateinamen mit Character-Name prefixen
    from app.core.expression_regen import migrate_variant_filenames
    migrate_variant_filenames()

    # Migration: legacy weekly/monthly rollup JSON files -> summaries table
    # (DB-only convention; idempotent — no-op once the files are gone).
    try:
        from app.core.memory_service import migrate_rollup_summaries_to_db
        migrate_rollup_summaries_to_db()
    except Exception as _rme:
        logger.debug("rollup-summaries migration failed: %s", _rme)

    # Migration: rename the legacy narrator-speaker sentinel to the canonical
    # STORYTELLER_SPEAKER in all persisted rows (idempotent, world_kv-marked).
    try:
        from app.models.perception_store import migrate_storyteller_speaker_once
        migrate_storyteller_speaker_once()
    except Exception as _se:
        logger.debug("storyteller-speaker migration failed: %s", _se)

    # Migration: normalize any character whose template is not installed here
    # (e.g. the deleted human-roleplay-nsfw, whose substance lives in packages
    # now) to an installed one. Catches post-migration imports; idempotent,
    # world_kv-marked.
    try:
        from app.models.character_template import migrate_stale_templates_once
        migrate_stale_templates_once()
    except Exception as _te:
        logger.debug("stale-template migration failed: %s", _te)

    # Migration: drop stat values a character's template no longer declares
    # (e.g. a package-declared stat on an animal template without it).
    try:
        from app.models.character_template import migrate_prune_stale_stats_once
        migrate_prune_stale_stats_once()
    except Exception as _pe:
        logger.debug("stale-stats prune failed: %s", _pe)

    # Migration: height moved out of the human package (a word in the build
    # slot) into a standard profile field in centimetres — the 3D client needs
    # a number to scale the figures. Idempotent, world_kv-marked.
    try:
        from app.core.height import migrate_height_to_profile_once
        migrate_height_to_profile_once()
    except Exception as _he:
        logger.debug("height migration failed: %s", _he)

    # Migration: appearance/face prompts saved with tokens the body-slot
    # shrink (bc98b6a) orphaned — every character created from the stale
    # template defaults carries literal {skin_color}/{size}/... into its
    # image and chat prompts. Idempotent, world_kv-marked.
    try:
        from app.core.appearance_token_migration import (
            migrate_dead_appearance_tokens_once)
        _at = migrate_dead_appearance_tokens_once()
        if _at.get("texts"):
            logger.info("Dead appearance tokens cleaned: %s", _at)
    except Exception as _ate:
        logger.debug("dead-appearance-token migration failed: %s", _ate)

    # Migration: per-character render targets saved in the ComfyUI-era
    # "workflow:<glob>" shape (profile override + skill configs) — they resolve
    # to None today, so the configured backend was silently ignored.
    # Idempotent, world_kv-marked. (The config side runs in the config load path.)
    try:
        from app.core.workflow_spec_migration import (
            migrate_legacy_workflow_specs_once)
        _ws = migrate_legacy_workflow_specs_once()
        if _ws.get("fields") or _ws.get("skill_files"):
            logger.info("Legacy render specs rewritten: %s", _ws)
    except Exception as _wse:
        logger.debug("legacy workflow-spec migration failed: %s", _wse)

    # Migration: the pre-per-outfit global 3D-model store (characters/<name>/
    # model/) lost its routes; import its GLB/FBX into the current outfit's v2
    # slot and drop the legacy folder, so the banned serving fallback can go.
    try:
        from app.core.model3d import migrate_legacy_model_store_once
        migrate_legacy_model_store_once()
    except Exception as _me:
        logger.debug("legacy-model migration failed: %s", _me)

    # Migration: the ground of a location becomes a room of its own — every
    # location gets the reserved ground room, and every character and
    # utterance that stood in no room moves onto it
    # (plan-grundflaeche.md § 8). Idempotent, world_kv-marked.
    try:
        from app.models.world import migrate_ground_rooms_once
        _gr = migrate_ground_rooms_once()
        if any(_gr.values()):
            logger.info("Ground-room migration: %s", _gr)
    except Exception as _gre:
        logger.debug("ground-room migration failed: %s", _gre)

    # Migration: a stored exit point becomes a door opening on the nearest
    # wall — the doors are the way in and out now
    # (plan-betreten-und-tueren.md § 6). Idempotent (the exit is removed),
    # world_kv-marked.
    try:
        from app.models.world import migrate_room_exits_once
        _rx = migrate_room_exits_once()
        if any(_rx.values()):
            logger.info("Exit-door migration: %s", _rx)
    except Exception as _rxe:
        logger.debug("exit-door migration failed: %s", _rxe)

    # Migration: every location drops its entry room — arriving on the ground
    # is the default now, and a declared entry room is the deliberate
    # exception an author sets by hand (plan-grundflaeche.md § 6). Runs after
    # the ground-room migration, which is what makes that ground exist.
    # Idempotent, world_kv-marked.
    try:
        from app.models.world import migrate_clear_entry_rooms_once
        _er = migrate_clear_entry_rooms_once()
        if any(_er.values()):
            logger.info("Entry-room migration: %s", _er)
    except Exception as _ere:
        logger.debug("entry-room migration failed: %s", _ere)

    # Initialisiere Multi-Channel Support
    logger.info("Initialisiere Multi-Channel Support...")
    initialize_channels()

    logger.info("Initializing Providers...")
    provider_manager = initialize_provider_manager()

    logger.info("Initializing LLM Routing...")
    from app.core import config as _cfg
    _routing = _cfg.get("llm_routing", []) or []
    logger.info("llm_routing: %d Einträge", len(_routing))

    # Modelle mit preload_on_startup=True asynchron warm laden, damit
    # llama-swap & Co. das Model schon in den Speicher legen, bevor der
    # erste echte User-Request kommt. create_task = nicht blockierend.
    try:
        import asyncio as _asyncio
        from app.core.llm_router import preload_models as _preload_models
        _asyncio.create_task(_preload_models())
    except Exception as _pe:
        logger.warning("LLM-Preload Task konnte nicht gestartet werden: %s", _pe)

    logger.info("Initialisiere Skills (Image Backends, etc.)...")
    skill_manager = get_skill_manager()

    logger.info("Registriere Task-Queue Handler...")
    # Social reactions live in the instagram package now — it registers its
    # queue handlers + hook subscriptions itself when its skills load.
    from app.core.social_dialog import register_social_dialog_handler
    register_social_dialog_handler()
    from app.core.story_engine import register_story_engine_handler
    register_story_engine_handler()
    from app.core.relationship_summary import register_relationship_summary_handler
    register_relationship_summary_handler()
    from app.core.relationship_decay import register_relationship_decay_handler
    register_relationship_decay_handler()
    from app.core.intent_engine import register_intent_handlers
    register_intent_handlers()
    from app.core.memory_service import register_consolidation_handler, register_migration_handler
    register_consolidation_handler()
    register_migration_handler()
    from app.core.outfit_batch import register_outfit_batch_handler
    register_outfit_batch_handler()

    logger.info("Initializing TTS Service...")
    tts_service = initialize_tts_service()

    # Preload rembg/u2net in the background — avoids a ~5s event-loop block
    # on the first outfit post-processing request.
    try:
        from app.models.character import preload_rembg_session
        preload_rembg_session()
    except Exception as _rembg_err:
        logger.warning("rembg-Preload nicht gestartet: %s", _rembg_err)

    # ── Startup Availability Summary ──
    import os as _os
    _summary_lines = ["-" * 80, "AVAILABILITY SUMMARY", "-" * 80]
    for prov in provider_manager.providers.values():
        status = "OK" if prov.available else "FAIL"
        _summary_lines.append(
            f"  Prov  {status:4s}  {prov.name} "
            f"({prov.type}, concurrent={prov.max_concurrent})")
    if not provider_manager.providers:
        _summary_lines.append("  Prov  --    No providers configured")
    for _entry in _routing:
        _ts = ", ".join(f"{t.get('task')}:{t.get('order')}" for t in (_entry.get("tasks") or []))
        _summary_lines.append(
            f"  LLM   OK    {_entry.get('provider','?')} / {_entry.get('model','?')} -> {_ts}")
    if not _routing:
        _summary_lines.append("  LLM   --    No routing entries configured")
    for skill in skill_manager.skills:
        _summary_lines.append(f"  Skill OK    {skill.name}")
    if not skill_manager.skills:
        _summary_lines.append("  Skill --    No skills loaded")
    tts_info = tts_service.status_info()
    if tts_info["enabled"]:
        tts_status = "OK" if tts_info["available"] else "FAIL"
        _summary_lines.append(
            f"  TTS   {tts_status:4s}  {tts_info['backend'].upper()} "
            f"({tts_info['url']}, voice={tts_info['voice']})")
    else:
        _summary_lines.append(f"  TTS   --    Disabled")
    _summary_lines.append(f"  Tele  OK    Telegram Channel (per-agent bot tokens)")
    _summary_lines.append("-" * 80)
    logger.info("\n%s", "\n".join(_summary_lines))

    # Character-Validierung (LLM-Overrides, etc.)
    logger.info("Validiere Character-Konfigurationen...")
    from app.core.character_validation import validate_all_characters
    validate_all_characters()

    logger.info("Initialisiere Scheduler...")
    _scheduler_manager = SchedulerManager()
    from app.routes.scheduler import set_scheduler_manager
    set_scheduler_manager(_scheduler_manager)
    logger.info("Scheduler bereit!")

    # Telegram Long Polling starten
    from app.core.telegram_polling import get_polling_manager
    _telegram_polling = get_polling_manager()
    await _telegram_polling.start()

    # Gedanken-Container instanziieren — kein Background-Task mehr,
    # nur Zugriffsobjekt fuer ``run_thought_turn``. AgentLoop ruft die
    # Funktion ueber ``get_thought_runner()``.
    from app.core.thoughts import ThoughtRunner, set_thought_runner
    _thought_runner = ThoughtRunner()
    set_thought_runner(_thought_runner)
    logger.info("ThoughtRunner initialisiert")

    # AgentLoop starten — kontinuierliche Gedanken-Schleife mit
    # importance-gewichtetem Round-Robin. Ersetzt den alten periodischen
    # Tick. Pause haengt am world-pause-Toggle (task_queue 'default').
    from app.core.agent_loop import get_agent_loop
    _agent_loop = get_agent_loop()
    await _agent_loop.start()
    logger.info("AgentLoop bereit!")

    # TravelTicker: settles running journeys independently of the AgentLoop.
    from app.core.travel_engine import get_travel_ticker
    await get_travel_ticker().start()

    # Task-Queue Worker erst starten, wenn ALLE Handler registriert sind
    # (sonst schlagen recovered persistierte Tasks beim Recovery fehl).
    from app.core.task_queue import get_task_queue
    get_task_queue().start()
    logger.info("Task-Queue Worker gestartet")

    # Chat-Task-Manager: Cleanup-Loop starten
    from app.core.chat_task_manager import get_chat_task_manager
    get_chat_task_manager().start_cleanup_loop()
    logger.info("ChatTaskManager bereit!")

    # Memory-System: Knowledge -> Memory Migration
    logger.info("Memory-System: Migration pruefen...")
    from app.core.memory_service import run_migration_for_all_users
    run_migration_for_all_users()
    logger.info("Memory-System bereit!")

    # Startup event: packages hook one-time bootstrap here (e.g. the
    # attraction package's romantic-interests extraction). Core names only
    # the event; without the package nobody listens (R1).
    try:
        from app.core import hooks
        hooks.emit("startup")
    except Exception as _se:
        logger.debug("startup hook failed: %s", _se)

    # Memory-Konsolidierung: periodisch im Hintergrund
    import asyncio as _aio

    async def _periodic_consolidation():
        """Konsolidiert Memories alle 6h, unabhaengig von Server-Neustarts."""
        from app.core.paths import get_storage_dir as _get_sd
        _ts_file = _get_sd() / ".last_consolidation"

        def _hours_since_last() -> float:
            if not _ts_file.exists():
                return 999.0
            try:
                from datetime import datetime as _dt
                last = _dt.fromisoformat(_ts_file.read_text().strip())
                return (_dt.now() - last).total_seconds() / 3600
            except Exception:
                return 999.0

        def _mark_done():
            from datetime import datetime as _dt
            _ts_file.parent.mkdir(parents=True, exist_ok=True)
            _ts_file.write_text(_dt.now().isoformat())

        await _aio.sleep(60)  # Kurz warten bis Server bereit
        while True:
            hours = _hours_since_last()
            if hours >= 6:
                try:
                    from app.core.memory_service import run_consolidation_for_all_users
                    run_consolidation_for_all_users()
                    _mark_done()
                except Exception as ce:
                    logger.error("Memory consolidation error: %s", ce)
            # Alle 30 Min pruefen ob 6h vergangen
            await _aio.sleep(30 * 60)

    _consolidation_task = _aio.create_task(_periodic_consolidation())

    # Periodic background jobs (replace old ThoughtRunner tick).
    from app.core import periodic_jobs
    periodic_jobs.start()

    from app.core import channel_health
    channel_health.start()

    from app.core import event_loop_watchdog
    event_loop_watchdog.start(tick=0.1, threshold_ms=1000.0)

    yield

    event_loop_watchdog.stop()
    _consolidation_task.cancel()
    try:
        from app.core import periodic_jobs
        await periodic_jobs.stop()
    except Exception as _pe:
        logger.debug("periodic_jobs stop failed: %s", _pe)

    # Shutdown
    await _telegram_polling.stop()
    try:
        from app.core.travel_engine import get_travel_ticker
        await get_travel_ticker().stop()
    except Exception as _te:
        logger.debug("TravelTicker stop failed: %s", _te)
    try:
        from app.core.agent_loop import get_agent_loop
        await get_agent_loop().stop()
    except Exception as _ae:
        logger.debug("AgentLoop stop failed: %s", _ae)
    # ThoughtRunner hat keinen Background-Task mehr → kein stop() noetig
    if _scheduler_manager:
        logger.info("Fahre Scheduler herunter...")
        _scheduler_manager.shutdown()


# Initialize FastAPI app
app = FastAPI(title="Agent System API", version="2.0", lifespan=lifespan)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Erlaubt alle Domains (nur für Entwicklung!)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"])

# User-Context-Middleware: setzt current_user_ctx aus Session-Cookie pro Request
from app.core.auth_dependency import user_context_middleware
app.middleware("http")(user_context_middleware)


# Include routers
app.include_router(auth.router)
app.include_router(store.router)
app.include_router(assets.router)
app.include_router(clip_catalog_loops.router)
app.include_router(game_audio.router)
app.include_router(poses_route.router)
app.include_router(characters.router)
app.include_router(chat.router)
app.include_router(group_chat.router, tags=["group_chat"])
app.include_router(scheduler.router, prefix="/scheduler", tags=["scheduler"])
app.include_router(instagram.router, tags=["instagram"])
app.include_router(world.router, tags=["world"])
# Prop MODEL VARIANTS — the variant-scoped twins of the prop gallery routes
# above. Registered AFTER world.router: the paths are disjoint
# (…/props/{id}/variants/…), so this is order-independent, but the variant
# routes are an extension of the prop library and belong beside it.
app.include_router(prop_variants_route.router)
app.include_router(telegram.router, tags=["telegram"])
app.include_router(templates.router)
app.include_router(story.router)
app.include_router(story_dev.router)
app.include_router(world_dev.router)
app.include_router(tts.router)
app.include_router(queue_route.router)
app.include_router(logs.router)
app.include_router(dashboard.router)
app.include_router(admin.router)
app.include_router(admin_settings.router)
app.include_router(notifications.router, tags=["notifications"])
app.include_router(events.router, tags=["events"])
from app.routes import rules
app.include_router(rules.router, tags=["rules"])
from app.routes import content_packs
app.include_router(content_packs.router)
app.include_router(relationships.router, tags=["relationships"])
app.include_router(intents.router, tags=["intents"])
app.include_router(diary.router, tags=["diary"])
app.include_router(user_gallery.router)
app.include_router(secrets.router, tags=["secrets"])
app.include_router(inventory.router, tags=["inventory"])
app.include_router(i18n_route.router, tags=["i18n"])
app.include_router(account.router)
app.include_router(state_route.router)
app.include_router(game_admin_route.router)
app.include_router(world_setup_route.router)
app.include_router(storyteller_route.router)
app.include_router(observer_route.router)
app.include_router(play_route.router)
app.include_router(api_images_route.router)
app.include_router(assist_route.router)

# Static files (the legacy vanilla-JS UI in templates/index.html was removed)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def read_root():
    """Redirect to the Player UI (legacy index.html removed)."""
    return RedirectResponse(url="/play")


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "version": "2.0"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
