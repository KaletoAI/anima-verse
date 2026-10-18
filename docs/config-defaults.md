# Interne Konfigurations-Anker und ihre Defaults

## Was hier steht — und was nicht

Die App liest Konfiguration **nicht** aus einer `.env` und nicht aus
Umgebungsvariablen (Ausnahmen: `queue_cli.py` für `TASK_QUEUE_DB` und das
`docker/`-Setup sowie die Pfad-Overrides `STORAGE_DIR` und `INSTANCE_DIR`).
Konfiguration hat **zwei Ebenen**: Server-Einstellungen liegen in
`instance/config.json` mit `instance/secrets.json` und werden unter `/admin/settings`
bearbeitet. Welt-Einstellungen liegen in `worlds/<welt>/config.json` und werden unter
Game-Admin → Setup bearbeitet (Untertabs nach `world_group`, einschließlich Bildstile).
Beide Dateien speichern nur Abweichungen; `/admin/settings` zeigt die Herkunft pro Feld.
Die Marken heißen „Default (GitHub)“ und „Instance“; „Reset to default“ entfernt eine
Abweichung, „Only my overrides“ filtert sie und „Shipped defaults“ zeigt die ausgelieferten Werte.
Die Instanz-Routen sind `/admin/settings/raw`, `/admin/settings/schema`,
`/admin/settings/origin`, `/admin/settings/shipped-defaults` und `/admin/settings/save`
(Speichern mit `{values, resets}`). Die Welt nutzt `GET`/`PUT /admin/world-settings`.

Eine frische Instanz bringt zwei Beispiel-Provider aus `config._DEFAULT_PROVIDERS` mit:
`ollama-local` (`http://localhost:11434/v1`) und `openai-compatible-local`
(`http://localhost:8080/v1`). Sie lassen sich unter LLM Providers anpassen oder ersetzen.
Eine Änderung macht die ganze Liste zur Instanz-Abweichung; ein leeres `[]` bleibt leer.

Die GROSSBUCHSTABEN-Namen unten sind trotzdem keine Fiktion: sie sind die internen
Anker einer **Env-Bridge**. `config.load()` ruft am Ende `_flatten_to_env(config)`
(`app/core/config.py`), das die JSON-Struktur in flache Namen in `os.environ`
schreibt — der historische Weg, den viele Module immer noch lesen. Es gibt deshalb
zwei Sorten Zeile in diesem Dokument:

| Sorte | Woran erkennbar | Wie man sie ändert |
|---|---|---|
| **gebrückt** | Spalte „Quelle" nennt einen `config.json`-Pfad und die Admin-Sektion | über `/admin/settings` (Instanz) oder Game-Admin → Setup (Welt). Der Wert landet über `_flatten_to_env` unter dem genannten Namen |
| **nur Code-Default** | Quelle „—" | gar nicht über die Admin-UI. Der genannte Wert ist der Default im `os.environ.get(...)`-Aufruf selbst; ihn zu ändern heißt, eine echte Prozess-Umgebungsvariable zu setzen oder den Code anzufassen |

Zwei Feinheiten der Bridge, die Überraschungen erklären:

- `_set(env, …)` **überspringt leere Werte**. Ist ein `config.json`-Feld leer, wird der
  Name gar nicht gesetzt, und es gilt der Code-Default des Lesers. Deshalb steht in der
  Default-Spalte unten der **effektiv wirksame** Wert.
- Die Bridge räumt nur die generierten `SKILL_IMAGEGEN_{N}_*`-Blöcke auf. Alle anderen
  Namen werden nur gesetzt, nie entfernt.
- **Fehlt** ein Feld in `config.json`, setzt die Bridge seinen **Schema-Default**
  (`config_schema.field_default(...)`) — eine Quelle statt zwei. Wo ein Leser noch einen
  eigenen Code-Default trägt, ist es derselbe Wert; `scripts/smoke_config_defaults_consistent.py`
  prüft beides. Ein auf den Default gesetztes und ein fehlendes Feld wirken also gleich.

Für migrierte Skill-Pakete (Instagram, MarkdownWriter, NotifyUser, ImageGen …) liegt
die Config im **Paket-Manifest** (`config_schema` in `plugins/<pkg>/plugin.yaml`) und
wird über `ctx.get_config("skills.<paket>.<feld>")` gelesen — nicht mehr über die
`SKILL_*`-Namen hier.

Die Liste ist kuratiert, nicht generiert. `scripts/smoke_docs_config_defaults.py`
prüft mechanisch, dass jeder genannte Name im Code vorkommt und jede Dateiangabe
existiert.

---

## Service URLs

Keine mehr über die Env-Bridge. Die SearX-Instanz stand bis 2026-09-21 als
`SKILL_SEARX_URL` hier; seitdem deklariert `plugins/searx/plugin.yaml` ein eigenes
`config_schema` und das Paket liest `skills.searx.url` direkt über den Plugin-Kontext
(`/admin/settings → Skills → SearX Web Search`).

---

## TTS (Text-to-Speech)

Die fünf allgemeinen Felder stehen in `/admin/settings → Text-to-Speech`, die
Backend-URLs und -Stimmen darunter in dessen **Untersektionen** `XTTS v2`,
`Magpie (NVIDIA Riva)` und `F5-TTS` (`config_schema.SECTIONS["tts"]["subsections"]`).
Alles hier ist also admin-einstellbar; `app/core/tts_service.py` liest die Werte über
die Env-Bridge, deren Defaults den Schema-Defaults entsprechen.

| Name | Quelle | Default | Leser |
|---|---|---|---|
| `TTS_ENABLED` | `tts.enabled` → Text-to-Speech | `false` | app/core/tts_service.py |
| `TTS_AUTO` | `tts.auto` → Text-to-Speech | `false` | app/core/tts_service.py |
| `TTS_BACKEND` | `tts.backend` → Text-to-Speech | `xtts` | app/core/tts_service.py |
| `TTS_FALLBACK_BACKEND` | `tts.fallback_backend` → Text-to-Speech | `` | app/core/tts_service.py |
| `TTS_CHUNK_SIZE` | `tts.chunk_size` → Text-to-Speech | `300` | app/core/tts_service.py |
| `TTS_XTTS_URL` | `tts.xtts.url` → XTTS v2 | `http://localhost:8020` | app/core/tts_service.py |
| `TTS_XTTS_SPEAKER_WAV` | `tts.xtts.speaker_wav` → XTTS v2 | `` | app/core/tts_service.py |
| `TTS_XTTS_LANGUAGE` | `tts.xtts.language` → XTTS v2 | `de` | app/core/tts_service.py |
| `TTS_MAGPIE_URL` | `tts.magpie.url` → Magpie | `http://localhost:9000` | app/core/tts_service.py |
| `TTS_MAGPIE_VOICE` | `tts.magpie.voice` → Magpie | `` | app/core/tts_service.py |
| `TTS_MAGPIE_LANGUAGE` | `tts.magpie.language` → Magpie | `de-DE` | app/core/tts_service.py |
| `TTS_F5_URL` | `tts.f5.url` → F5-TTS | `http://localhost:7860` | app/core/tts_service.py |
| `TTS_F5_SPEED` | `tts.f5.speed` → F5-TTS | `1.0` | app/core/tts_service.py |
| `TTS_F5_NFE_STEPS` | `tts.f5.nfe_steps` → F5-TTS | `32` | app/core/tts_service.py |
| `TTS_F5_REMOVE_SILENCE` | `tts.f5.remove_silence` → F5-TTS | `false` | app/core/tts_service.py |

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
| `MOOD_HISTORY_MAX_ENTRIES` | — | `500` | app/models/memory.py |

Die Zahl der Tages-Zusammenfassungen stand bis 2026-09-22 als `DAILY_SUMMARY_DAYS`
hier; seitdem liest `app/utils/history_manager.py` `knowledge.daily_summary_days`
(Default `7`) direkt über `config.get(...)`, und die Bridge setzt den Namen nicht mehr
(`/admin/settings → Knowledge System`).

---

## Bildgenerierung

| Name | Quelle | Default | Leser |
|---|---|---|---|
| `IMAGE_ANALYSIS_PROMPT` | `image_generation.image_analysis_prompt` → Media Generation | langer Vorgabetext im Schema | app/imagegen/service.py |
| `IMAGE_ANALYSIS_LANGUAGE` | — | `de` | app/imagegen/service.py |

Welches Backend einen Anlass rendert, steht nicht mehr in Env-Variablen, sondern in
`image_generation.routing` (Admin → Media Generation → Routing); siehe
`app/imagegen/occasions.py`.

**Mesh-Animation** (`api_type: openai_mesh_animation`, Anlass `pose_animation`): ein Backend-Eintrag pro
Bewegungsmodell, Key in `instance/secrets.json`. Was die Modelle unterscheidet, steht als Feld am Eintrag
(Defaults = UniMate): `motion_source` (`puppet` | `reference_rig`), `source_slot`, `caption_style`
(`object` | `person`), `segment_seconds`, `variant_param`, `duration_param`, `max_variants` (1–4), `generator`,
`license`, `credit`, `model_revision`.

| Feld | `mesh-unimate` | `motion-kimodo` |
|---|---|---|
| `model` | `mesh-unimate` | `motion-kimodo` |
| `extra_params` | `{"input_cfg_scale": 3.0, "input_chain_overlap": 10}` | — |
| `motion_source` / `source_slot` | `puppet` / `input_mesh_path` (Default) | `reference_rig` / `input_rig_path` |
| `caption_style` / `segment_seconds` | `object` / 2 (Default) | `person` / 4 |
| `variant_param` / `duration_param` | `input_num_repetitions` / leer (Default) | `input_num_samples` / `input_duration` |
| `generator` / `license` | `unimate` / `CC-BY-NC-4.0` (Default) | `kimodo` / `NVIDIA-Open-Model-License` |

Der Anlass verlangt eine konfigurierte Kette — leer heißt `NoRouteError`, nie das günstigste Backend. Der
Poses-Dialog bietet „Auto (Routing)" (erster nutzbarer Ketteneintrag) oder ein bestimmtes Backend der Kette
(ohne Ersatz) und 1 bis `max_variants` Varianten (Default 3). Kein Default-Eintrag: ohne Kette bleibt die
Funktion im Poses-Tab mit klarer Meldung aus.

Der **Hauptschalter** `image_generation.enabled` („Media generation enabled",
Admin-Sektion „Media Generation") wird NICHT in eine Env-Variable gebrückt: er
wird live gelesen (`app/imagegen/base.py::media_generation_enabled`). Aus ist
aus — jede Bild-, Video- und Mesh-Erzeugung der Welt wird an der zentralen
Übergabe `ImageService.run_on_backend_channel` mit `MediaGenerationDisabled`
abgelehnt (HTTP 409), es wird kein Task eingereiht, und vorhandene Medien
werden weiter ausgeliefert. Default: `true`.

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
| `EVENT_BASE_PROBABILITY` | `random_events.base_probability` (Prozent) → Zufaellige Events | `5` ⇒ Wahrscheinlichkeit `0.05` | app/core/random_events.py |
| `EVENT_RESOLUTION_COOLDOWN_MINUTES` | `random_events.resolution_cooldown_minutes` → Zufaellige Events | `15` | app/core/random_events.py |
| `EVENT_RESOLUTION_PROACTIVE` | `random_events.resolution_proactive` → Zufaellige Events | `true` | app/core/random_events.py |

Die Bridge teilt den Prozentwert durch 100. Der Schema-Default ist **5** (seit
2026-10-03; vorher stand im Schema `0`, die Bridge setzte für ein fehlendes Feld aber
schon immer `5`, und das war der wirksame Wert). Abschalten geht über
`random_events.enabled`.

---

## Story Engine

| Name | Quelle | Default | Leser |
|---|---|---|---|
| `STORY_ENGINE_ENABLED` | `story_engine.enabled` → Story Engine | `false` | app/core/story_engine.py |
| `STORY_ENGINE_MAX_ACTIVE_ARCS` | `story_engine.max_active_arcs` → Story Engine | `2` | app/core/story_engine.py |
| `STORY_ENGINE_COOLDOWN_HOURS` | `story_engine.cooldown_hours` → Story Engine | `6` | app/core/story_engine.py |
| `STORY_ENGINE_MAX_BEATS` | `story_engine.max_beats` → Story Engine | `5` | app/core/story_engine.py |
| `STORY_ENGINE_BEAT_IMAGES` | `story_engine.beat_images` → Story Engine | `true` | app/core/story_engine.py |

Der Story-Player (`app/routes/story.py`, `story_dev.py`) hat heute **keine UI** — er
bleibt für eine spätere Wiederverwendung im Code.

---

## Beziehungen

Hier gibt es keine env-Brücke mehr. Die einzige Einstellung ist
`relationships.summary_enabled` (Game-Admin → Setup → Gameplay → Relationships, Default `true`), und
`app/core/chat_engine.py` liest sie direkt per `config.get()`: steht sie auf
`false`, entfällt der Sentiment-LLM-Call nach einem Gespräch und die Beziehung
bekommt nur die festen Default-Deltas.

Der Beziehungs-Zerfall ist nicht einstellbar: die Raten stehen als
`DECAY_STRENGTH_PER_WEEK` (1.0) und `DECAY_ROMANTIC_PER_WEEK` (0.02) in
`app/core/relationship_decay.py`. Gemessen wird auf der SPIEL-Uhr — eine
"Woche" sind sieben Spieltage (`GameDuration.of(days=7)`), die Schonfrist
ebenfalls sieben Spieltage, und pro Lauf werden hoechstens zwei Wochen
verrechnet. Der periodische Job wird stuendlich (Echtzeit) eingereiht; ein
Paar wird erst wieder angefasst, wenn seit seinem `last_decay_game` ein ganzer
Spieltag vergangen ist. Steht die Weltuhr still, zerfaellt nichts.

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

Die Instanz wird separat mit `./start.sh --instance /pfad` gewählt, sonst über
`INSTANCE_DIR`, sonst `./instance`. `paths.init_instance()` selbst hat keinen Default.
In Docker liegt sie auf `anima_instance` unter `/app/instance`. Jede Ebene überlagert
nur ihre eigene `config.json` mit ihrer eigenen `secrets.json`; Secrets gehören zur
jeweiligen Ebene. Für die Migration alter Welten muss der Server gestoppt sein.
Bevorzugt den exakten Befehl aus der Startverweigerung verwenden: Er enthält den
gewählten Instanzpfad und bei Bedarf das eigene Weltverzeichnis. Beispiel:

```bash
./.venv/bin/python scripts/migrate_instance_config.py --from <welt> --instance <instanzverzeichnis> --worlds-dir <weltverzeichnis>
```

Ohne `--instance` verwendet das Werkzeug `<repo>/instance`, ohne `--worlds-dir`
`<repo>/worlds`. Es übernimmt die Instanz-Einstellungen aus der mit `--from`
gewählten Welt und entfernt Instanz-Einstellungen aus **jeder geeigneten Welt**
unter `--worlds-dir` (Unterverzeichnisse mit `config.json`; Symlinks und außerhalb
liegende Ziele werden ohne `--follow-symlinks` übersprungen). Vor dem Schreiben
legt es byte-identische Backups der Config-/Secrets-Dateien der Welten und der
bereits vorhandenen Instanz an. Mit `--dry-run` wird nur der Bericht ausgegeben,
ohne Dateien oder Backups zu schreiben. Der Docker-Entrypoint ruft die Migration
mit `--if-needed` auf.
LLM-Template-Änderungen unter `/admin/templates` liegen als Welt-Overrides in `world.db`
(Tabelle `llm_template_overrides`), nicht in `shared/templates/llm/`.

| Name | Quelle | Default | Leser |
|---|---|---|---|
| `STORAGE_DIR` | — (Pfad-Override, kein `config.json`-Feld) | `./worlds/demo` (gesetzt von `start.sh` / `docker/docker-entrypoint.sh`, nicht von `paths.py`) | app/core/paths.py |

Achtung, Henne und Ei: **welche Welt geöffnet wird, entscheidet der Start**
(`./start.sh --world NAME` / `--storage /pfad`, sonst die Umgebungsvariable, sonst
`./worlds/demo` — diesen Default setzt `start.sh`; `paths.init()` selbst kennt keinen
und wirft ohne Argument und ohne `STORAGE_DIR` `StorageNotInitialised`). `paths.init()`
läuft VOR `config.load()` — die Welt kann ihren eigenen Ort nicht festlegen, deshalb
gibt es dafür kein `config.json`-Feld (das frühere `server.storage_dir` wählte nichts
aus und ist gestrichen).

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
| `memory.chat_retention_days` | `90` | Aufbewahrung der rohen Chat-Zeilen (`chat_messages`). Zeilen, die älter sind, werden gelöscht — aber nur, wenn ihr SPIELTAG bereits zusammengefasst wurde (Tages-Summary, oder die Wochen-/Saison-Summary, in die sie später eingeklappt wurde). Ein Tag ohne Zusammenfassung behält seine Zeilen unabhängig vom Alter. `0` = nie löschen. SYSTEM-Zeit (echte Tage), läuft täglich im World-Admin-Tick (`app/core/chat_retention.py`). |
| `npc.*` (16 Felder) | — | Automatische NPCs: Slots, Fenster, Pool, Aktions- und Szenen-Takt — `docs/npc-slots.md`. |
| `image_generation.blender_*` (15 Felder) | — | Blender-Nacharbeit an 3D-Modellen — `docs/llm-blender-models.md`. |

Nicht in `config.json`, aber im selben Atemzug oft gesucht: die **Sprache des
Accounts** steht pro WELT am Account und wird über `GET/POST /account/language`
gelesen und gesetzt (Sprachcode + Übersetzungsmodus). Die Auswahlliste kommt aus
`shared/config/languages.json` über `app.core.i18n.list_languages()` /
`language_name(code)`; die Übersetzungs-Maps liegen in
`shared/languages/<lang>.json` und werden erst beim Neustart neu gelesen.

**Die Schema-Texte selbst sind englisch und werden NICHT übersetzt.** `label` und
`description` in `app/core/config_schema.py` rendert `static/admin/settings.js`
roh; `/admin/settings` und die übrigen serverseitig gebauten Admin-Seiten
(`/admin/users`, `/admin/llm-stats`, `/admin/models`, `/admin/agent-loop`,
`/admin/templates`, `/logs/*`, `/dashboard`) haben bewusst keine `t()`-Schicht und
bekommen auch keine. Ein Eintrag für einen dieser Strings in
`shared/languages/<lang>.json` wird nie gelesen — `scripts/smoke_i18n_orphans.py`
schlägt darauf an. Übersetzbar sind nur die React-Strings (`t()` aus `useI18n()`)
und Server-Strings, die durch `t(en, lang)` laufen.

---

## Offene Punkte (Befunde, kein Ist-Zustand)

- `_apply_schema_defaults` (`app/routes/admin_settings.py`) füllt Defaults nur für
  `fields` einer Sektion und für `sub_arrays`, **nicht für `subsections`**. Die
  TTS-Backend-Felder und die Skill-Untersektionen zeigen ihren Default daher als
  grauen Platzhalter, materialisieren ihn aber nicht in `config.json`. Wirksam ist er
  trotzdem — die Env-Bridge setzt für ein fehlendes Feld den Schema-Default
  (`field_default`), und die Leser tragen denselben Wert als Code-Default.

Erledigt (2026-09-21, Teil der Config-Altlasten-Runde):

- `server.jwt_secret` ist entfernt — Schema-Feld, Validator-Warnung, `JWT_SECRET`-Bridge
  und der `SENSITIVE_FIELDS`-Eintrag. Sitzungen sind undurchsichtige Zufalls-Tokens
  (`app/core/sessions.py`, `secrets.token_urlsafe(32)`); es gab nie ein JWT im Code. Ein
  Weltordner, der das Feld noch in `config.json` trägt, wird beim Laden bereinigt
  (`config.DEAD_CONFIG_FIELDS["server"]`).
- Die TTS-Backend-URLs (`tts.xtts.*`, `tts.magpie.*`, `tts.f5.*`) haben sehr wohl
  Schema-Felder — sie liegen in den `subsections` der TTS-Sektion, die die Admin-Seite
  rendert (`static/admin/settings.js`). Der frühere Befund war falsch; er kam daher,
  dass der Doku-Wächter `subsections` nicht durchlief. Beides ist korrigiert.
- `skills.searx.url`: `plugins/searx/plugin.yaml` deklariert jetzt ein eigenes
  `config_schema` (Admin-Seite „Skills → SearX Web Search"), das Paket liest die Werte
  über `ctx.get_config`, und `env_prefix` samt Env-Lesern ist weg.

### World extension motion

`extension_motion.groups` is world-scoped, default `{}` (inherit package physics).
Example: `{"extension_motion":{"groups":{"example_group":{"gain":0.6}}}}`.
Instance writes are rejected; foreign-scope instance-file values are ignored.
Setup → Extension motion edits currently loaded group IDs and resets a group by
removing its override. Numeric rules match declarations: frequency > 0; zeta and
gravity ≥ 0; gain, flatten, stretch, spread, flatten_floor, spill, translate and head_sag 0..1 (flatten/spill/translate default 0);
dynamic/static/rest angle limits 0..180 (`sag_max_deg` defaults to the declared `max_deg`); squash requires
`0 < min <= 1 <= max`. Unknown physics fields are rejected. Stored overrides for
a currently absent package are retained and have no effective group to modify.

`axis_gain: [lateral, vertical, longitudinal]` defaults to `[1,1,1]`, with three
finite entries in [0,1]. Package defaults, world Setup and absolute character
physics overrides support it; attribute multipliers and state `bone_pose` do not.
It filters only dynamic `p-T'` in the current rest lever frame, before dynamic
soft angle/gain. Vertical follows projected bind body up rotated with the anchor;
a vertical lever uses projected bind body front (bind world +Z if geometry
cannot define front). Only longitudinal dynamics change length. Static sag,
flatten, spill and rest pose retain their existing effect.

`flatten`, `stretch`, `spill` and `translate` are finite in [0,1], default 0.
`flatten_floor` is finite in [0,1]; omission inherits effective `squash_min`
server-side, before attribute multipliers (an absolute character floor overrides them).
For unit world gravity `g_hat`, current rest lever `u` and immutable bind lever
`u_bind` under upright gravity, define
`f_in=clamp(-g_hat.dot(u)-max(0,-g_hat.dot(u_bind)),0,1)` and
`f_out=clamp(g_hat.dot(u)-max(0,g_hat.dot(u_bind)),0,1)`.
Upright in the bind posture gives exactly zero for either target, including
an upward 15-degree bind lever. Static length is the direct target
`s=1-flatten*(1-flatten_floor)*f_in+stretch*(squash_max-1)*f_out`,
independent of gravity, character gravity scale and frequency (including zero).
Outward stretch narrows both perpendicular axes by `1/sqrt(s)`; stretch=1,
squash_max=1.45 and f_out=1 give length 1.45 and transverse .8304547985.
Flatten=1, floor=.15 and f_in=1 give length .15 even with squash_min=.6.
Zero floor uses a positive numerical epsilon to keep transforms finite. Paired spill is the direct
outward rotation `spill*spill_max_deg*f_in` degrees along the projected lateral
`L`; single chains have no spill. For paired groups, define `L_bind` once
from this chain-root head minus the mean of the group's chain-root heads
in the bind pose: remove its bind-pose body-up component and normalize.
At runtime rotate `L_bind` with the anchor rotation, then project it
perpendicular to the current lever `u` and normalize (Gram-Schmidt).
Use this outward `L` for the spill rotation. Paired FLATTENING does not act
along the oblique lever: it presses along the BODY FRONT (bind-pose body front,
rotated with the anchor; where gravity presses when lying) and widens along the
body lateral axis, both expressed in the frame the bone scale acts in. The frame
(front, L ⟂ front, front × L) is orthonormal, so the scale has no shear; the
third axis keeps factor 1. Width = min(1.6, 1 + spread·(1/s − 1)). (An outward-
pointing lever would otherwise tilt the width axis into the height: measured on
a real rig the lying height grew with a lower floor.) Single chains keep the
symmetric lever-frame compensation. Degenerate L uses the symmetric fallback.
Remaining inward axial force is removed.
Non-axial static sag still uses `gravity*(m*g-R_anchor*R_rest*g_rest)/omega²`
and the static angle limit; upright m=1 has no additional sag, m=2 sags and
m=.5 lifts. The force-based static angle is capped by `sag_max_deg`; the subsequent spill target uses its independent limit.
`spread` is finite in [0,1], default 0.5. For shortening (`s<1`), paired
transverse compensation along L is `c=min(spread_cap,1+spread*(1/s-1))`;
the third axis stays 1. Single chains use symmetric transverse compensation
`c=min(spread_cap,1+spread*(1/sqrt(s)-1))`. The documented constant
`spread_cap=1.6` bounds mesh widening, deliberately relaxing volume conservation.
At spread=.5, s=.15 gives c=1.6 and s=.8 gives paired c=1.125.
The scale is diagonal in the orthonormal bone frame `(u,L,u cross L)`;
L is projected perpendicular to u and normalized, so it introduces no shear.

`translate` applies that fraction of the perpendicular static and dynamic
rendered displacement to the bone head; the remainder supplies rotation.
Both components are projected perpendicular to the original rest lever, so
uncapped translate=1 leaves its direction unchanged even with combined sag
and bounce. Longitudinal behaviour means the rendered length scalar is preserved.
Dynamic axis gains, soft angle limits and gain are applied before this split.
Each translated component is capped before multiplying by `translate`:
static <= rest lever length * sin(sag_max_deg), dynamic <= static lever length
* sin(max_deg), with angles in radians for sine. Longitudinal displacement and
length scaling are unchanged by the split. Weighted borders blend into the
anchor. Supported layers are package defaults/attribute profiles, world overrides
and absolute character overrides; state `bone_pose` has no translate multiplier.
The mesh fingerprint excludes all physics fields. Preview category is `tilt`
for flatten/stretch/spread/flatten_floor/spill/translate: Tilt exposes posture targets and static translation;
play a clip for translate's bounce. Flatten/spill hints explicitly state that
these targets are independent of gravity and frequency.

Package `rig.attribute_profiles` selects physics multipliers by the character's
stored slot attribute values after world overrides. Unknown values are ignored;
profile multipliers are finite and nonnegative (frequency strictly positive).
Unit-interval results cap at 1; angle results cap at 180. Absolute character
physics overrides in `model3d_opts.extension_motion` apply next, then clothing
damping scales gain, then active state `bone_pose` multipliers apply (rest angle
uses the maximum present value). The 3D panel's Extension bones numeric inputs and Reset edit
these profile overrides via the admin-only character extension-motion endpoint,
under the character profile lock. The editor shows values before clothing damping and state composition.
`motion_gravity_scale` remains separate: `gravity*(m*g-R_anchor*g_rest)`;
it scales current gravity against the baked rest gravity. Static sag uses its own
limit, so gravity does not consume the dynamic angle range. Physics-only changes
update `motion.rev`, with no mesh fingerprint/signature/revision change.


### Extension motion calibration: spill, static pull and character sliders

`spill_max_deg` is finite in [0,180], defaulting server-side to the group's
`sag_max_deg` when omitted; every resolved payload carries a number. Lying paired
spill is `spill*spill_max_deg*f_in` degrees, independent of the force sag limit.
For sag 5, spill maximum 30, spill .5 and f_in=1, the outward target is 15 degrees.
`head_sag` is finite in [0,1], default 1: **vertical static pull when not upright**.
After force sag limits, let d be the static force displacement and U the anchor's
bind-pose body up in the current world frame. Replace only that displacement by
`d + (head_sag-1)*(d·U)*U`. Flatten and spill are applied subsequently;
front/back and lateral force components, rest pose and dynamics remain unchanged.
Final length rendering preserves this post-limit static target even with squash [1,1].

Per-character `model3d_opts.extension_motion[group]` stores `bounce` and `weight`
next to raw overrides. Both are finite in [.5,1.5], default 1. Resolution order:
package → world → attribute profile → raw character overrides → bounce/weight →
clothing → state. The provisional mapping is a **calibration point**:
bounce b multiplies gain (clamp 1) and max_deg by b, and freq_hz and zeta by
`b^-0.5`; weight w multiplies gravity, sag_max_deg, spill_max_deg, flatten and stretch (both clamp 1)
and translate (clamp 1) by w. Angle limits remain capped at 180 degrees.
For raw gain .6, max 20, frequency 4, zeta .5, gravity 2, sag 5, spill maximum 30,
flatten .5 and translate .6, b=1.25/w=.8 yield .75, 25, 3.577708764,
.4472135955, 1.6, 4, 24, .4 and .48 respectively before clothing/state.
The client consumes these effective numbers without applying the sliders again.

The character Extension bones editor shows Bounce and Weight sliders with
range .5..1.5, step .05 and value labels. Raw fields are under collapsed Advanced;
Save/Revert/Reset retain draft semantics. Bounce uses the motion preview hint;
Weight, spill_max_deg, head_sag, stretch, spread and flatten_floor use Tilt. World overrides expose the raw
fields but do not accept character sliders. Motion changes leave mesh fingerprints
unchanged. Editor defaults precede raw character overrides and sliders.

### Bind-relative calibration and state extent

Setup and character Advanced expose `stretch`, `spread` and `flatten_floor` with Tilt
hints. Attribute profiles may multiply both fields. Weight additionally maps
`stretch -> min(1,stretch*w)` (and `flatten -> min(1,flatten*w)`).
The admin Tilt follows its sliders at at most 120 degrees per real second,
including simultaneous forward/sideways movement.

For anchor turns faster than 360 degrees/s, every spring substep bounds both
the dynamic deviation increment and its magnitude. With static lever length r,
`B=r*sin(min(pi/2,max_deg*pi/180))`: increment <= `B*min(1,120*h)`,
magnitude <= B. On a cap hit velocity follows the target; non-finite spring
results reset to the current substep target. The existing soft angular limit
still bounds rendered deviation around the static target. A one-frame 90-degree
jump stays within `max_deg*1.05`; normal motion retains exact propagation.
Gaps, reset and LOD transitions clear anchor history with particle history.

State `bone_pose[group]` additionally accepts optional `length` and `girth`,
each finite in [.5,2], default multiplier 1. Active states multiply these fields
(e.g. length 1.5*.5=.75, girth .8*1.5=1.2), preserving sparse storage and
ZIP import/export. Effective products blend with smoothstep over 1.5 real
seconds, including interrupted transitions and far LOD, like `rest_deg`.
They scale the immutable lever and both perpendicular directions respectively
on top of the static/dynamic deformation; they do not change volume compensation.
State editor hints are `live`. Resolved payloads always include numeric
`stretch`, `spread`, `flatten_floor`, `length` and `girth`; all five affect only motion
revision, leaving mesh fingerprints unchanged.
