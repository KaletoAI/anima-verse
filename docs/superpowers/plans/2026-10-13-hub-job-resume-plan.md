# Plan: Hub-Jobs überleben einen Anima-Neustart

Grundlage: `docs/superpowers/specs/2026-10-13-hub-job-resume-design.md` (Rev. 2). Branch `feat/hub-job-resume`.
Jeder Task endet mit einem Commit; nach jedem Task ein Review durch einen Subagenten, Befunde werden vor dem
nächsten Task behoben. Prüfung je Task: `py_compile` der berührten Dateien, `smoke_imports_resolve.py` und
die genannten Smokes.

## T1 — `HubJobLost` und terminale Behandlung

- `app/imagegen/base.py`: `class HubJobLost(RuntimeError)`, Docstring mit dem Vertrag (terminal: kein Retry,
  kein Fallback, keine Abkühlpause). Konstruktor normalisiert den Text auf `Hub job lost: <Grund>`.
- `selection.run_on_backend`: eigener `except HubJobLost: raise` vor dem Sammelzweig.
- `service.py`: `generate_mesh`, `generate_video`, `generate_mesh_variant`, `generate_mesh_animation` lassen
  `HubJobLost` durch. `skills/animate.animate_image` ebenso.
- `model3d.face_retexture_model`: Upscale-`except` lässt `HubJobLost` durch.
- `task_queue._worker_loop`: `HubJobLost` → `failed` ohne Retry.
- `improvements/engine.handle_step`: `HubJobLost` → Schritt `skipped` sofort.
- Smokes: `smoke_mesh_gateway`, `smoke_upscale_backends`, `smoke_face_retexture_rollback`.

## T2 — Job-Protokoll: Stufen-Haken und Anhänge-Modus

- `_gateway_job.submit_job(…, stage=None, attach_params=None)`: `stage.posting(backend)` vor jedem POST,
  `stage.not_posted()` bei Busy-Wiederholung/Fehler ohne Job-ID, `stage.submitted(backend, job_id,
  attach_params)` nach Erfolg.
- `poll_job(…, attach_since=None)`: Anhänge-Semantik nach Spec § 3.4 (404/410/failed/cancelled → `HubJobLost`,
  Netz/5xx geduldig mit bis zu 30 s Abstand bis 24 h, Budget D5, leerer Download 10× → `HubJobLost`).
  Ohne `attach_since` byte-gleich zum bisherigen Verhalten.
- Smokes: `smoke_mesh_gateway`, `smoke_mesh_animation_backend`, `smoke_upscale_backends`.

## T3 — `attach` in den Hub-Backends

- `openai_mesh`: `_collect(job_id, *, since, should_cancel)` aus `_generate` herausziehen; `attach()` setzt
  die Thread-Locals (Job-ID, Eingabe-Hashes aus `attach_params`).
- `openai_video`: `_download` → Methode `_download_video`; `_collect`, `attach`.
- `openai_upscale`: `done` → `_download_upscale`; `attach` mit `digest` aus `attach_params`.
- `openai_mesh_animation`: `_collect(job_id, variants, …)`, `attach`.
- Alle übergeben `stage=params.get("hub_stage")` und ihre Abhol-Parameter an `submit_job`.

## T4 — `app/core/hub_ops.py` und Tabelle

- Tabelle `hub_ops` + Index (teilweise eindeutig auf `subject` bei `status='running'`) in
  `world_db_schema.SCHEMA_STATEMENTS`.
- `Op` (laden/speichern, `stage()`, `done()`, `result()`, `complete()`, `dir`, `path()`),
  `HubStage` (`prepare()`, `posting()`, `not_posted()`, `submitted()`, `note_route()`, `collected()`,
  `collect()`), `HubOpBusy`.
- `create()`, `find_open()`, `fail()`, `finish()`, `running(op)` (Kontextmanager: Fehler speichern → Anzeige →
  löschen), `register_kind()`, `resume_tracking(op)`.
- Eigentümer über `task_queue.current_task_id()`; `create(thread_owned=True)` für Video (D10).
- Grabstein (D8): ein verlorener Task-Auftrag bleibt `failed`, bis `release_task_ops` ihn beim Task-Ende
  löscht; `find_open` liefert ihn, `raise_failed` meldet `HubJobLost` erneut. `open_task_inputs()` für
  Batch-Handler. Improvements: `HubOpBusy` wie `CandidateBusy`.
- `routing.run_routed(…, on_route=None)` für die Route im Datensatz.

## T5 — Service-Methoden mit `hub_stage`

- Gemeinsamer Helfer `ImageService._hub_collected(stage)`: `prepare()` → bei Job `collect()`.
- `generate_mesh`, `generate_mesh_variant`, `generate_rig`, `generate_face_retexture`, `upscale_image`,
  `generate_video`, `generate_mesh_animation`: Griff in die Parameter, Anhänge-Zweig vor dem Routing, gleiche
  Nachbearbeitung.

## T6 — Task-Queue

- `current_task_id()` (Thread-Local im Worker), `task_status()`, `annotate_error()`, `track_hold()` +
  Reaper-Ausnahme, Freigabe in `track_finish`/`track_cancel`.
- Nach endgültigem Task-Ende: `hub_ops.release_task_ops(task_id, cancelled)` (D4).

## T7 — Charakter-Pipelines (`model3d`)

- `generate_for_current_outfit` (nicht dekoriert): Suche nach offenem Auftrag des Tasks **vor** dem
  `_serial_model`-Wrapper → dekorierte Funktion mit eingefrorener Signatur; sonst Vorverarbeitung → Auftrag
  `character_mesh` → Stufen `mesh`, `checkpoint`, `rig`, Veröffentlichen. Abschluss des Datensatzes erst nach
  dem Wrapper-Publish; `mesh_published` aus dem Zustand.
- `rerig_model` → `character_rerig`; `_rig_from_source` mit Stufen-Griff und dauerhaftem Rig-Ergebnis.
- `face_retexture_model` → `face_retexture` mit `upscale`, `face`, `bake` (Quelle, Vergleichsbild, Maske im
  Auftragsordner), `rig`; bei der Fortsetzung keine `runnable`/Eignungsprüfung, Quelle vor dem Rig nach
  `facefix/` der Stage zurückschreiben.
- `outfit_batch`: Signaturen mit offenem Auftrag des Tasks nicht überspringen und ihre T-Pose nicht neu
  rendern.
- `_serial_model` kennt die neuen Einstiegsfunktionen (Namensliste statt Einzelname).
- Fortsetzungs-Einstiege + Thread-Sperren (`_generating`, `_char_lock`) registrieren.

## T8 — Props und Locations

- `props._generate`/`_shrink`, `location_model3d._generate`/`_shrink`: Auftrag nach der Vorverarbeitung,
  Mesh-Ergebnis in den Auftragsordner, Veröffentlichen mit im Zustand festgehaltenem Galeriepfad (auch der
  LOD-Stufen); geerbte Rotation eingefroren. Zielschlüssel = bestehender `_gen_key` (D11).
  Fortsetzungs-Einstiege + Sperren registrieren.

## T9 — Video

- `animate.animate_image(…, hub_stage=None)`; Instagram-Animate und Video-Skill legen `video_instagram` /
  `video_character` an; Veröffentlichen als registrierte Funktionen.

## T10 — Posen-Animation

- Auftrag `pose_animation` nach dem LLM-Schritt und `reserve_kind`; `_build_candidates` (neu, aus der
  Schleife in `_handle` herausgezogen) als gemeinsame Funktion; Fortsetzung im Handler ohne LLM-Schritt und
  ohne `resolve_animation_backend`.

## T11 — Resumer und Server

- `hub_ops.start_resumer()` (Spec § 3.6), `register_builtin_kinds()`; Aufruf im Lifespan vor AgentLoop.

## T12 — `scripts/smoke_hub_job_resume.py`

- Fake-Hub (`http.server`), temporäre Welt, Fälle aus Spec § 5 plus § 0.

## T13 — Doku

- `docs/hub-job-resume.md`, README-Zeile; CLAUDE.md-Absatz in den PR (Datei gitignored).

## Abschluss

- Gesamtreview des Branches durch Subagent, Befunde beheben.
- Relevante Smokes laufen lassen, Ausgaben in den PR.
- PR auf Deutsch: Änderungen, verifiziert, nicht verifiziert (echter Hub, echter Neustart), Grenzen,
  Abweichungen Code ↔ Spec.
