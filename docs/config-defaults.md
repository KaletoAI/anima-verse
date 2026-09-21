# Konfigurations-Defaults

> **Achtung — Lesart:** Die App liest Konfiguration **nicht** aus
> `.env`/Umgebungsvariablen (Ausnahmen nur `queue_cli.py` + `docker/`);
> konfiguriert wird pro Welt über `config.json` (Admin-UI `/admin/settings`).
> Die Namen unten sind die internen Anker, unter denen `config.py` Werte aus
> `config.json` in den Prozess legt (`_set(env, …)`) und der Code sie wieder
> liest — keine Einstellschraube für den Nutzer. Für migrierte Skill-Pakete
> (Instagram, MarkdownWriter, NotifyUser, ImageGen …) liegt die Config im
> **Paket-Manifest** (`config_schema` in `plugins/<pkg>/plugin.yaml`), nicht
> mehr in den unten gelisteten `SKILL_*`-Variablen.
>
> Diese Liste wird nicht automatisch generiert. Zuletzt mechanisch gegen den
> Code geprüft am **2026-09-21**: jeder Name wurde in `app/`, `plugins/`,
> `shared/`, `static/`, `docker/`, `queue_cli.py`, `frontend/src`,
> `client3d/src` und den privaten Paketen gesucht, jede Dateiangabe mit
> `test -f`. Entfallen sind dabei 19 Einträge ohne einen einzigen Treffer im
> Code, zwei weitere, die nur noch in einem veralteten Kommentar bzw. als
> Schreibzugriff ohne Leser vorkamen (`OUTFIT_IMAGE_PROMPT_PREFIX`,
> `SOCIAL_REACTIONS_ENABLED`), und vier Verweise auf inzwischen gelöschte
> Module — Befund DS-11. Die Prüfung läuft als
> `scripts/smoke_docs_config_defaults.py` weiter.

Weiterhin gültige Parameter (Provider-URLs, Timeouts, unmigrierte Skills) mit
ihren Standardwerten.

---

## Sicherheit

| Variable | Default | Datei |
|---|---|---|
| `JWT_SECRET` | `your-secret-key-change-in-production` | app/core/config.py (aus `server.jwt_secret`) |

---

## Service URLs & Ports

| Variable | Default | Datei |
|---|---|---|
| `SKILL_SEARX_URL` | `http://localhost:8888` | plugins/searx (config.json) |
| `TELEGRAM_API_URL` | `https://api.telegram.org/bot` | app/models/telegram_channel.py |

---

## TTS (Text-to-Speech)

| Variable | Default | Datei |
|---|---|---|
| `TTS_ENABLED` | `false` | app/core/tts_service.py |
| `TTS_AUTO` | `false` | app/core/tts_service.py |
| `TTS_BACKEND` | `xtts` | app/core/tts_service.py |
| `TTS_FALLBACK_BACKEND` | `` | app/core/tts_service.py |
| `TTS_CHUNK_SIZE` | `0` | app/core/tts_service.py |
| `TTS_XTTS_URL` | `http://localhost:8020` | app/core/tts_service.py |
| `TTS_XTTS_SPEAKER_WAV` | `` | app/core/tts_service.py |
| `TTS_XTTS_LANGUAGE` | `de` | app/core/tts_service.py |
| `TTS_MAGPIE_URL` | `http://localhost:9000` | app/core/tts_service.py |
| `TTS_MAGPIE_VOICE` | `` | app/core/tts_service.py |
| `TTS_MAGPIE_LANGUAGE` | `de-DE` | app/core/tts_service.py |
| `TTS_F5_URL` | `http://localhost:7860` | app/core/tts_service.py |
| `TTS_F5_SPEED` | `1.0` | app/core/tts_service.py |
| `TTS_F5_NFE_STEPS` | `32` | app/core/tts_service.py |
| `TTS_F5_REMOVE_SILENCE` | `false` | app/core/tts_service.py |

---

## LLM & Chat

| Variable | Default | Datei |
|---|---|---|
| `LLM_REQUEST_TIMEOUT` | `120` | app/core/llm_router.py, app/imagegen/service.py |

---

## Memory & History

| Variable | Default | Datei |
|---|---|---|
| `MEMORY_SHORT_TERM_DAYS` | `3` | app/utils/history_manager.py |
| `MEMORY_MID_TERM_DAYS` | `30` | app/utils/history_manager.py |
| `MEMORY_LONG_TERM_DAYS` | `90` | app/utils/history_manager.py |
| `MOOD_HISTORY_MAX_ENTRIES` | `500` | app/models/memory.py |
| `CHAT_HISTORY_MAX_MESSAGES` | `100` | app/utils/history_manager.py |
| `CHAT_SESSION_GAP_HOURS` | `4` | app/utils/history_manager.py |
| `DAILY_SUMMARY_DAYS` | `7` | app/utils/history_manager.py, app/core/scene_manager.py |
| `MEMORY_COMMITMENT_MAX_DAYS` | `7` | app/core/memory_service.py |
| `MEMORY_COMMITMENT_COMPLETED_DAYS` | `3` | app/core/memory_service.py |
| `MEMORY_MAX_SEMANTIC` | `50` | app/models/memory.py |

---

## Image Generation

| Variable | Default | Datei |
|---|---|---|
| `OUTFIT_IMAGEGEN_DEFAULT` | `` | app/core/character_ops.py, app/core/expression_regen.py, app/core/world_ops.py |
| `LOCATION_IMAGEGEN_DEFAULT` | `` | app/core/world_ops.py, app/core/character_ops.py |
| `EXPRESSION_IMAGEGEN_DEFAULT` | `` | app/core/expression_regen.py, app/core/character_ops.py |
| `IMAGE_ANALYSIS_PROMPT` | `` | app/imagegen/service.py |
| `IMAGE_ANALYSIS_LANGUAGE` | `de` | app/imagegen/service.py |

*Einen Prompt-Prefix für Outfit-/Profilbilder gibt es nicht mehr: Stil und
Bildausschnitt kommen aus dem jeweiligen **Use-Case** (`image.use_cases.<uc>`,
Admin-Sektion „Image/Video Generation").*

---

## Skills

| Variable | Default | Datei |
|---|---|---|
| `SKILL_OUTFIT_CREATION_LANGUAGE` | `en` | app/skills/outfit_creation_skill.py |
| `SKILL_OUTFIT_CREATION_MAX_DAILY_ITEMS` | `8` | app/skills/outfit_creation_skill.py |
| `SKILL_OUTFIT_CREATION_MAX_INVENTORY` | `60` | app/skills/outfit_creation_skill.py |
| `SKILL_DESCRIBEROOM_MAX_ROOMS` | `3` | app/skills/describe_room_skill.py |

*ImageGen (`SKILL_IMAGEGEN_*`), MarkdownWriter, NotifyUser, Searx und Instagram sind zu Paketen/Service migriert — Config im Manifest bzw. `config.json`, nicht mehr per Env-Variable.*

---

## Random Events

| Variable | Default | Datei |
|---|---|---|
| `EVENT_GENERATION_ENABLED` | `true` | app/core/random_events.py |
| `EVENT_BASE_PROBABILITY` | `0.10` | app/core/random_events.py |
| `EVENT_RESOLUTION_COOLDOWN_MINUTES` | `15` | app/core/random_events.py |
| `EVENT_RESOLUTION_PROACTIVE` | `true` | app/core/random_events.py |

---

## Story Engine

| Variable | Default | Datei |
|---|---|---|
| `STORY_ENGINE_ENABLED` | `true` | app/core/story_engine.py |
| `STORY_ENGINE_MAX_ACTIVE_ARCS` | `2` | app/core/story_engine.py |
| `STORY_ENGINE_COOLDOWN_HOURS` | `6` | app/core/story_engine.py |
| `STORY_ENGINE_MAX_BEATS` | `5` | app/core/story_engine.py |
| `STORY_ENGINE_BEAT_IMAGES` | `true` | app/core/story_engine.py |
| `STORY_ENGINE_IMAGEGEN_DEFAULT` | `` | app/core/story_engine.py |

---

## Relationship System

| Variable | Default | Datei |
|---|---|---|
| `RELATIONSHIP_SUMMARY_ENABLED` | `true` | app/core/relationship_summary.py |
| `RELATIONSHIP_SUMMARY_INTERVAL_MINUTES` | `30` | app/core/relationship_summary.py |
| `RELATIONSHIP_SUMMARY_MAX_PER_RUN` | `5` | app/core/relationship_summary.py |

*Der Beziehungs-Zerfall ist nicht mehr über Variablen einstellbar: die Raten
stehen als `DECAY_STRENGTH_PER_WEEK` (1.0) und `DECAY_ROMANTIC_PER_WEEK` (0.02)
in `app/core/relationship_decay.py`.*

---

## Group Chat

| Variable | Default | Datei |
|---|---|---|
| `GROUP_CHAT_THRESHOLD` | `2.0` | app/core/turn_taking.py |
| `GROUP_CHAT_MIN_RESPONDERS` | `1` | app/core/turn_taking.py |
| `GROUP_CHAT_MAX_RESPONDERS` | `3` | app/core/turn_taking.py |
| `GROUP_CHAT_MENTION_BOOST` | `5.0` | app/core/turn_taking.py |
| `GROUP_CHAT_COOLDOWN` | `2.0` | app/core/turn_taking.py |

---

## Task Queue

| Variable | Default | Datei |
|---|---|---|
| `TASK_QUEUE_MAX_RETRIES` | `0` | app/core/task_queue.py |

---

## Logging

| Variable | Default | Datei |
|---|---|---|
| `LOG_LEVEL` | `INFO` | app/core/log.py |

---

## Storage

| Variable | Default | Datei |
|---|---|---|
| `STORAGE_DIR` | `./worlds/demo` | app/core/paths.py |
| `DEFAULT_THEME` | `default` | app/models/account.py |

---

## Animation / Video

Keine Variablen mehr. **Video-Backends sind heute Einträge in
`image_generation.backends`** (Admin-Sektion „Image/Video Generation":
`openai_video` / `localai_video` / `together_video`); `app/skills/animate.py`
ist nur noch ein Adapter über `service.generate_video()`. Welcher Task auf
welchem Backend landet, steht in `docs/llm-task-mapping.md` → GPU tasks.

---

## Neuere Einstellungen ohne Variablen-Anker

Diese drei werden direkt aus `config.json` gelesen (Admin-UI
`/admin/settings`), nicht über einen Namen wie oben. Defaults und
Beschreibungen stehen in `app/core/config_schema.py`.

| Einstellung | Default | Wirkung |
|---|---|---|
| `server.max_upload_mb` | `25` | Obergrenze für EINE hochgeladene Datei auf den Spieler-Routen (Chat-Bild, User-Galerie, Profilbild, Regel-Import). Darüber 413, bevor der Body gelesen wird. Content-Packs haben ihre eigene, größere Grenze (Content Marketplace → Max pack size). |
| `server.cors_origins` | `http://localhost:5173`, `http://127.0.0.1:5173`, `http://localhost:5183`, `http://127.0.0.1:5183` (eine Origin pro Zeile) | Welche fremden Origins die API aufrufen dürfen — für die beiden Vite-Dev-Server und einen 3D-Client auf einem anderen Rechner. `/play` und `/game-admin` liefert der Server selbst aus und brauchen keinen Eintrag. Leer = kein Cross-Origin-Zugriff. Kein Wildcard. Braucht Neustart. |
| `telegram.webhook_secret` | leer | Gemeinsames Geheimnis für `POST /telegram/webhook`; Telegram schickt es im Header `X-Telegram-Bot-Api-Secret-Token` zurück. Solange es leer ist, bleibt der Webhook GESCHLOSSEN. Liegt in `secrets.json`. |