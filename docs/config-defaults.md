# Interne Konfigurations-Anker und ihre Defaults

## Was hier steht — und was nicht

Die App liest Konfiguration **nicht** aus einer `.env` und nicht aus
Umgebungsvariablen (Ausnahmen: `queue_cli.py` für `TASK_QUEUE_DB` und das
`docker/`-Setup). Konfiguriert wird **pro Welt** in `worlds/<welt>/config.json`, über
die Admin-UI `/admin/settings`.

Die GROSSBUCHSTABEN-Namen unten sind trotzdem keine Fiktion: sie sind die internen
Anker einer **Env-Bridge**. `config.load()` ruft am Ende `_flatten_to_env(config)`
(`app/core/config.py`), das die JSON-Struktur in flache Namen in `os.environ`
schreibt — der historische Weg, den viele Module immer noch lesen. Es gibt deshalb
zwei Sorten Zeile in diesem Dokument:

| Sorte | Woran erkennbar | Wie man sie ändert |
|---|---|---|
| **gebrückt** | Spalte „Quelle" nennt einen `config.json`-Pfad und die Admin-Sektion | über `/admin/settings`. Der Wert landet über `_flatten_to_env` unter dem genannten Namen |
| **nur Code-Default** | Quelle „—" | gar nicht über die Admin-UI. Der genannte Wert ist der Default im `os.environ.get(...)`-Aufruf selbst; ihn zu ändern heißt, eine echte Prozess-Umgebungsvariable zu setzen oder den Code anzufassen |

Zwei Feinheiten der Bridge, die Überraschungen erklären:

- `_set(env, …)` **überspringt leere Werte**. Ist ein `config.json`-Feld leer, wird der
  Name gar nicht gesetzt, und es gilt der Code-Default des Lesers. Deshalb steht in der
  Default-Spalte unten der **effektiv wirksame** Wert.
- Die Bridge räumt nur die generierten `SKILL_IMAGEGEN_{N}_*`-Blöcke auf. Alle anderen
  Namen werden nur gesetzt, nie entfernt.

Für migrierte Skill-Pakete (Instagram, MarkdownWriter, NotifyUser, ImageGen …) liegt
die Config im **Paket-Manifest** (`config_schema` in `plugins/<pkg>/plugin.yaml`) und
wird über `ctx.get_config("skills.<paket>.<feld>")` gelesen — nicht mehr über die
`SKILL_*`-Namen hier.

Die Liste ist kuratiert, nicht generiert. `scripts/smoke_docs_config_defaults.py`
prüft mechanisch, dass jeder genannte Name im Code vorkommt und jede Dateiangabe
existiert.

---

## Service URLs

| Name | Quelle | Default | Leser |
|---|---|---|---|
| `SKILL_SEARX_URL` | `skills.searx.url` (nur config.json) | `http://localhost:8888` | plugins/searx/skill.py |

---

## TTS (Text-to-Speech)

Die fünf allgemeinen Felder stehen in `/admin/settings → Text-to-Speech`. Die
**Backend-URLs und -Stimmen darunter haben kein Schema-Feld** — sie existieren nur in
`config.json` und werden gebrückt, aber nicht von der Admin-UI angeboten (siehe
„Offene Punkte").

| Name | Quelle | Default | Leser |
|---|---|---|---|
| `TTS_ENABLED` | `tts.enabled` → Text-to-Speech | `false` | app/core/tts_service.py |
| `TTS_AUTO` | `tts.auto` → Text-to-Speech | `false` | app/core/tts_service.py |
| `TTS_BACKEND` | `tts.backend` → Text-to-Speech | `xtts` | app/core/tts_service.py |
| `TTS_FALLBACK_BACKEND` | `tts.fallback_backend` → Text-to-Speech | `` | app/core/tts_service.py |
| `TTS_CHUNK_SIZE` | `tts.chunk_size` → Text-to-Speech | `300` | app/core/tts_service.py |
| `TTS_XTTS_URL` | `tts.xtts.url` (nur config.json) | `http://localhost:8020` | app/core/tts_service.py |
| `TTS_XTTS_SPEAKER_WAV` | `tts.xtts.speaker_wav` (nur config.json) | `` | app/core/tts_service.py |
| `TTS_XTTS_LANGUAGE` | `tts.xtts.language` (nur config.json) | `de` | app/core/tts_service.py |
| `TTS_MAGPIE_URL` | `tts.magpie.url` (nur config.json) | `http://localhost:9000` | app/core/tts_service.py |
| `TTS_MAGPIE_VOICE` | `tts.magpie.voice` (nur config.json) | `` | app/core/tts_service.py |
| `TTS_MAGPIE_LANGUAGE` | `tts.magpie.language` (nur config.json) | `de-DE` | app/core/tts_service.py |
| `TTS_F5_URL` | `tts.f5.url` (nur config.json) | `http://localhost:7860` | app/core/tts_service.py |
| `TTS_F5_SPEED` | `tts.f5.speed` (nur config.json) | `1.0` | app/core/tts_service.py |
| `TTS_F5_NFE_STEPS` | `tts.f5.nfe_steps` (nur config.json) | `32` | app/core/tts_service.py |
| `TTS_F5_REMOVE_SILENCE` | `tts.f5.remove_silence` (nur config.json) | `false` | app/core/tts_service.py |

Die Sprecher-WAVs für das Voice-Cloning liegen im Repo-Root unter `voices/` und werden
von `app/routes/tts.py` gelistet — lokale Nutzerdaten, nicht im Git.

---

## LLM

| Name | Quelle | Default | Leser |
|---|---|---|---|
| `LLM_REQUEST_TIMEOUT` | — | `120` (Sekunden) | app/core/llm_router.py, app/imagegen/service.py |

Greift nur, wenn der Provider kein eigenes Timeout mitbringt; pro Provider steht es in
`/admin/settings → LLM Provider`. Welcher Task auf welches Modell geht, steht nicht
hier, sondern in `docs/llm-task-mapping.md`.

---

## Memory & History

| Name | Quelle | Default | Leser |
|---|---|---|---|
| `MEMORY_SHORT_TERM_DAYS` | `memory.short_term_days` → Memory | `3` | app/utils/history_manager.py |
| `MEMORY_MID_TERM_DAYS` | `memory.mid_term_days` → Memory | `30` | app/utils/history_manager.py |
| `MEMORY_LONG_TERM_DAYS` | `memory.long_term_days` → Memory | `90` | app/utils/history_manager.py |
| `CHAT_HISTORY_MAX_MESSAGES` | `memory.max_messages` → Memory | `100` | app/utils/history_manager.py |
| `CHAT_SESSION_GAP_HOURS` | `memory.session_gap_hours` → Memory | `4` | app/utils/history_manager.py |
| `MEMORY_MAX_SEMANTIC` | `memory.max_semantic` → Memory | `50` | app/models/memory.py |
| `MEMORY_COMMITMENT_MAX_DAYS` | `memory.commitment_max_days` → Memory | `5` | app/core/memory_service.py |
| `MEMORY_COMMITMENT_COMPLETED_DAYS` | `memory.commitment_completed_days` → Memory | `3` | app/core/memory_service.py |
| `DAILY_SUMMARY_DAYS` | `knowledge.daily_summary_days` → Knowledge System | `7` | app/utils/history_manager.py, app/core/scene_manager.py |
| `MOOD_HISTORY_MAX_ENTRIES` | — | `500` | app/models/memory.py |

---

## Bildgenerierung

| Name | Quelle | Default | Leser |
|---|---|---|---|
| `OUTFIT_IMAGEGEN_DEFAULT` | `image_generation.outfit_imagegen_default` → Media Generation | `` | app/core/character_ops.py, app/core/expression_regen.py, app/core/world_ops.py |
| `EXPRESSION_IMAGEGEN_DEFAULT` | `image_generation.expression_imagegen_default` → Media Generation | `` | app/core/expression_regen.py, app/core/character_ops.py |
| `LOCATION_IMAGEGEN_DEFAULT` | `image_generation.location_imagegen_default` → Media Generation | `` | app/core/world_ops.py, app/core/character_ops.py |
| `IMAGE_ANALYSIS_PROMPT` | `image_generation.image_analysis_prompt` → Media Generation | langer Vorgabetext im Schema | app/imagegen/service.py |
| `IMAGE_ANALYSIS_LANGUAGE` | — | `de` | app/imagegen/service.py |

Einen Prompt-Prefix für Outfit-/Profilbilder gibt es nicht mehr: Stil und
Bildausschnitt kommen aus dem jeweiligen **Use-Case** (`image.use_cases.<uc>`,
Admin-Sektion „Image/Video Generation"). Die Blender-Einstellungen für 3D-Modelle
liegen ebenfalls dort (`image_generation.blender_*`, Unterseite „Blender refinement
(3D)") — beschrieben in `docs/llm-blender-models.md`.

---

## Unmigrierte Skills

| Name | Quelle | Default | Leser |
|---|---|---|---|
| `SKILL_OUTFIT_CREATION_LANGUAGE` | — | `en` | app/skills/outfit_creation_skill.py |
| `SKILL_OUTFIT_CREATION_MAX_DAILY_ITEMS` | — | `8` | app/skills/outfit_creation_skill.py |
| `SKILL_OUTFIT_CREATION_MAX_INVENTORY` | — | `60` | app/skills/outfit_creation_skill.py |
| `SKILL_DESCRIBEROOM_MAX_ROOMS` | — | `3` | app/skills/describe_room_skill.py |

---

## Zufällige Welt-Events

| Name | Quelle | Default | Leser |
|---|---|---|---|
| `EVENT_GENERATION_ENABLED` | `random_events.enabled` → Zufaellige Events | `true` | app/core/random_events.py |
| `EVENT_BASE_PROBABILITY` | `random_events.base_probability` (Prozent) → Zufaellige Events | `0` ⇒ Wahrscheinlichkeit `0.0` | app/core/random_events.py |
| `EVENT_RESOLUTION_COOLDOWN_MINUTES` | `random_events.resolution_cooldown_minutes` → Zufaellige Events | `15` | app/core/random_events.py |
| `EVENT_RESOLUTION_PROACTIVE` | `random_events.resolution_proactive` → Zufaellige Events | `true` | app/core/random_events.py |

Die Bridge teilt den Prozentwert durch 100. Der Schema-Default ist **0**, ein frisch
angelegtes `config.json` erzeugt also keine Events, bis jemand „Base probability %"
hochsetzt.

---

## Story Engine

| Name | Quelle | Default | Leser |
|---|---|---|---|
| `STORY_ENGINE_ENABLED` | `story_engine.enabled` → Story Engine | `false` | app/core/story_engine.py |
| `STORY_ENGINE_MAX_ACTIVE_ARCS` | `story_engine.max_active_arcs` → Story Engine | `2` | app/core/story_engine.py |
| `STORY_ENGINE_COOLDOWN_HOURS` | `story_engine.cooldown_hours` → Story Engine | `6` | app/core/story_engine.py |
| `STORY_ENGINE_MAX_BEATS` | `story_engine.max_beats` → Story Engine | `5` | app/core/story_engine.py |
| `STORY_ENGINE_BEAT_IMAGES` | `story_engine.beat_images` → Story Engine | `true` | app/core/story_engine.py |
| `STORY_ENGINE_IMAGEGEN_DEFAULT` | `story_engine.imagegen_default` → Story Engine | `` | app/core/story_engine.py |

Der Story-Player (`app/routes/story.py`, `story_dev.py`) hat heute **keine UI** — er
bleibt für eine spätere Wiederverwendung im Code.

---

## Beziehungen

| Name | Quelle | Default | Leser |
|---|---|---|---|
| `RELATIONSHIP_SUMMARY_ENABLED` | `relationships.summary_enabled` → Relationships | `true` | app/core/relationship_summary.py |
| `RELATIONSHIP_SUMMARY_INTERVAL_MINUTES` | `relationships.summary_interval_minutes` → Relationships | `120` | app/core/relationship_summary.py |
| `RELATIONSHIP_SUMMARY_MAX_PER_RUN` | — | `5` | app/core/relationship_summary.py |

Der Beziehungs-Zerfall ist nicht einstellbar: die Raten stehen als
`DECAY_STRENGTH_PER_WEEK` (1.0) und `DECAY_ROMANTIC_PER_WEEK` (0.02) in
`app/core/relationship_decay.py`.

---

## Task Queue & Logging

| Name | Quelle | Default | Leser |
|---|---|---|---|
| `TASK_QUEUE_MAX_RETRIES` | — | `0` | app/core/task_queue.py |
| `LOG_LEVEL` | `server.log_level` → Server | `INFO` | app/core/log.py |

`queue_cli.py` ist die eine Stelle, die eine echte `.env` liest — nur für
`TASK_QUEUE_DB`, damit das CLI die Queue auch ohne laufenden Server findet.

---

## Storage

| Name | Quelle | Default | Leser |
|---|---|---|---|
| `STORAGE_DIR` | `server.storage_dir` → Server | `./worlds/demo` | app/core/paths.py |

Achtung, Henne und Ei: **welche Welt geöffnet wird, entscheidet der Start**
(`./start.sh --world NAME` / `--storage /pfad`, sonst die Umgebungsvariable, sonst
`./worlds/demo`). `paths.init()` läuft VOR `config.load()`; der gebrückte Wert aus
`config.json` wird also gesetzt, wählt aber nichts mehr aus.

---

## Einstellungen ohne Env-Anker

Diese liest der Code direkt aus `config.json` (`config.get("<pfad>")`), ohne den Umweg
über die Bridge. Defaults und Beschreibungen stehen in `app/core/config_schema.py`.

| Einstellung | Default | Wirkung |
|---|---|---|
| `server.max_upload_mb` | `25` | Obergrenze für EINE hochgeladene Datei auf den Spieler-Routen (Chat-Bild, Galerie, Profilbild, Regel-Import). Darüber 413, bevor der Body gelesen wird. Content-Packs haben ihre eigene, größere Grenze (Content Marketplace → Max pack size). |
| `server.max_inflight_jobs_per_user` | `4` | Wie viele Bild-/Video-/Mesh-Jobs EIN Nicht-Admin gleichzeitig auf den Generierungs-Backends laufen haben darf. Ein weiterer Request wird mit 429 abgelehnt, bevor irgendetwas in die Queue geht — ein Skript in der Schleife kann die GPU nicht mehr für sich allein nehmen, und das Backend wird dafür nicht bestraft. Admins und die Server-eigene Arbeit (Agent-Loop, Scheduler, Ticker) sind nie begrenzt, Hintergrund-Tasks der persistenten Queue zählen nicht mit. `0` = unbegrenzt. |
| `server.cors_origins` | `http://localhost:5173`, `http://127.0.0.1:5173`, `http://localhost:5183`, `http://127.0.0.1:5183` (eine Origin pro Zeile) | Welche fremden Origins die API aufrufen dürfen — für die beiden Vite-Dev-Server und einen 3D-Client auf einem anderen Rechner. `/play` und `/game-admin` liefert der Server selbst aus und brauchen keinen Eintrag. Leer = kein Cross-Origin-Zugriff. Kein Wildcard. Braucht Neustart. |
| `game.travel_speed_m_s` | `1.4` | Reisegeschwindigkeit in Metern pro Spiel-Sekunde (0,1…20), siehe `docs/movement-model-and-skills.md`. |
| `chat.chattiness`, `chat.pair_window_game_minutes`, `chat.avatar_floor_timeout_minutes` | `0.5` / `5` / `8` | Wer auf eine Zeile im Raum antwortet — `docs/room-conversation.md`. |
| `npc.*` (16 Felder) | — | Automatische NPCs: Slots, Fenster, Pool, Aktions- und Szenen-Takt — `docs/npc-slots.md`. |
| `image_generation.blender_*` (15 Felder) | — | Blender-Nacharbeit an 3D-Modellen — `docs/llm-blender-models.md`. |

Nicht in `config.json`, aber im selben Atemzug oft gesucht: die **Sprache des
Accounts** steht pro WELT am Account und wird über `GET/POST /account/language`
gelesen und gesetzt (Sprachcode + Übersetzungsmodus). Die Auswahlliste kommt aus
`shared/config/languages.json` über `app.core.i18n.list_languages()` /
`language_name(code)`; die Übersetzungs-Maps liegen in
`shared/languages/<lang>.json` und werden erst beim Neustart neu gelesen.

---

## Offene Punkte (Befunde, kein Ist-Zustand)

- `server.jwt_secret` ist **tot**. Sitzungen sind seit der Auth-Überarbeitung
  undurchsichtige Zufalls-Tokens (`app/core/sessions.py`, `secrets.token_urlsafe(32)`),
  im Prozess gehalten — es gibt kein JWT mehr im Code. Das Feld steht noch im Schema
  (samt Validator-Warnung) und die Bridge setzt `JWT_SECRET`, aber niemand liest es.
- Die TTS-Backend-URLs (`tts.xtts.*`, `tts.magpie.*`, `tts.f5.*`) haben keine
  Schema-Felder und damit keine Admin-Oberfläche. Wer sie ändern will, muss
  `config.json` von Hand anfassen — bei laufendem Server überschreibt ein Speichern in
  der Admin-UI solche Edits.
- Dasselbe gilt für `skills.searx.url`: `plugins/searx/plugin.yaml` deklariert kein
  `config_schema`, das Paket hängt noch an der Env-Bridge (`env_prefix:
  "SKILL_SEARX_"`). Ein `config_schema` im Manifest würde ihm die Admin-Seite
  „Skills → SearX" geben — so, wie es für Pakete vorgesehen ist.
