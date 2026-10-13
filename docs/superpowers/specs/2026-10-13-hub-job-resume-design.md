# Spec: Hub-Jobs überleben einen Anima-Neustart

Stand: 2026-10-13, **Revision 2**. Ersetzt Revision 1 („Fortsetzen durch erneutes Ausführen der ganzen
Operation“), die nach Review-Runde 1 verworfen wurde. Jede Code-Aussage hier ist gegen `main`
(`319d1bd`) geprüft; Zeilenangaben sind ungefähre Ankerpunkte.

## 0. Bindende Entscheidungen

### 0.1 Befunde aus Review-Runde 1 (Codex `gpt-6-astra`, 2026-10-13), gegen den Code bestätigt

| Befund | Beleg im Code |
|---|---|
| Vorverarbeitung würde wiederholt | Props rendern ihr Quellbild in `_generate` neu (`props.py` `_render_source` ~6201); Props und Locations ziehen mit `gallery.new_path()` ein neues Galerieziel (`props.py` ~6261, `location_model3d.py` ~1313) |
| Ketten zerfallen | `_checkpoint_mesh` veröffentlicht das ungeriggte Mesh als `<sig>.glb` vor dem Rig-Job; der Cache-Check in `generate_for_current_outfit` (`find_model3d`, ~1680) hält es danach für fertig und überspringt das Rig. Die Gesichtskorrektur schreibt `facefix/<sig>.glb` nur in den `_serial_model`-Stage-Ordner (~2302) |
| Zeilen zu früh gelöscht | Rev. 1 löschte die Zeile am Ende des Service-Aufrufs, also vor Prüfen, Rig, Veröffentlichen bzw. vor dem Instagram-Feed-Eintrag |
| `HubJobLost` ginge verloren | `run_on_backend` wickelt jede nicht gelistete Ausnahme in `BackendFailedError` + Abkühlpause (`selection.py` ~364), `run_routed` startet darauf den nächsten Ketteneintrag (`routing.py` ~541). `face_retexture_model` schluckt jede Upscale-Ausnahme außer drei Typen (~2278). Die Task-Queue wiederholt jede Ausnahme bis `max_retries` (`task_queue._worker_loop`), Improvements wiederholen einmal (`engine.MAX_ATTEMPTS = 2`) |
| Schlüssel instabil | `npc_assets._render_mesh` ruft `generate_for_current_outfit(name)` ohne Signatur (~382), also mit der gerade getragenen |
| Start-Reihenfolge | `server.py` startet AgentLoop (~651) vor `get_task_queue().start()` (~661); pausierte Queues (`queue_paused`) führen ihre Tasks gar nicht aus |
| Abholer würden geerntet | `_reap_stale_tracked_runtime` markiert getrackte Zeilen nach 20 min als `interrupted`; `track_finish` überschreibt danach jeden Status |
| Absendelücke | Zwischen Annahme des POST und dem Speichern der Job-ID kann ein Job entstehen, den Anima nicht kennt |
| Gesichtskorrektur-Backend | `openai_mesh` mit `category == "face_retexture"` (`openai_mesh.py` ~618) |
| 404/410 heute | `poll_job` meldet 410 sofort und 3× 404 als `GatewayRejectedError` (`_gateway_job.py` ~210–222) |

### 0.2 Nutzerentscheidungen

- 2026-10-13: Umfang **in einem Zug** (alle Arten aus § 1, keine Phasen).
- 2026-10-13: Die Absendelücke wird **hingenommen**. Der ai-hub bleibt unverändert, die Doku nennt die Lücke.
- 2026-10-13: Umsetzung auf dem Branch `feat/hub-job-resume`; diese Datei ist versioniert (Ausnahme von
  `development_instructions/`); der Plan liegt in `docs/superpowers/plans/2026-10-13-hub-job-resume-plan.md`.
- 2026-10-13 (Auftrag): **Nicht** zurück zu „ganze Operation erneut ausführen“. Richtung: Auftragsdatensatz mit
  eingefrorenen Eingaben, Stufen-Zustandsmaschine, Stufenfunktionen für Normallauf und Fortsetzung gemeinsam.
  `HubJobLost` ist durch alle Ebenen terminal. Verlorene Jobs werden **nie** automatisch neu abgeschickt.

### 0.3 Entscheidungen dieser Revision (im Sinne von § 0, im PR genannt)

- **D1 Absendelücke:** Ein Datensatz, dessen Stufe beim Neustart im Zustand `posting` steht (POST abgeschickt,
  keine Job-ID gespeichert), endet als `HubJobLost` („interrupted while submitting“). Kein erneutes Absenden.
- **D2 Nur beansprucht:** Eine Stufe, die beansprucht, aber noch nicht im POST war (z. B. wartete sie im
  GPU-Kanal), hat beim Hub nichts hinterlassen. Sie wird bei der Fortsetzung normal abgeschickt. Das ist kein
  Neu-Absenden eines verlorenen Jobs.
- **D3 Zweiter Start:** Läuft für dasselbe Ziel schon ein Auftrag, wird ein zweiter Start **abgelehnt**
  (`HubOpBusy`), nicht angehängt. Ergebnis wie in Rev. 1 gefordert: kein zweiter Job.
- **D4 Verwaiste Task-Aufträge:** Endet ein Task, ohne seinen offenen Auftrag fortgesetzt zu haben (z. B.
  `npc_assets` hält das veröffentlichte statische Mesh für fertig), übernimmt ein Thread den Auftrag.
  Bei einem abgebrochenen Task wird der Hub-Job storniert und der Auftrag verworfen.
- **D5 Zeitbudget beim Anhängen:** `submitted_at + max_queue_wait + max_wait`, höchstens 24 h. Danach Hub-Job
  stornieren (best effort) und `HubJobLost`.
- **D6 Abbrechen:** Der `should_cancel`-Weg gilt für Fortsetzungs-Einträge. Normale Läufe verhalten sich wie
  heute (E4).
- **D7 Posen-Animation:** nutzt denselben Auftragsdatensatz (Eigentümer = ihr Task). Der Task-`progress`
  behält `hub_job` zur Anzeige.
- **D8 Grabstein:** Ein Task-Auftrag, der mit `HubJobLost` endet, bleibt als `failed`-Datensatz stehen, bis
  sein Task endgültig vorbei ist. Läuft der Handler erneut (Neustart, `outfit_combos` fängt Fehler je
  Kombination ab), findet der Einstieg den Grabstein und meldet `HubJobLost`, statt neu abzuschicken.
  Andere Fehler (kein Verlust) löschen den Datensatz wie gehabt; ein Retry ist dann normales Verhalten.
- **D9 Abgrenzung:** „Nie automatisch neu abgeschickt“ gilt für den Fortsetzungsweg und den besitzenden
  Task. Unabhängige Auto-Produzenten, die ein fehlendes Asset später aus eigenem Anlass erzeugen
  (Auto-Mesh-Hook nach einem T-Pose-Render, stehende Improvements beim nächsten Scan, NPC-Gate), behandeln das
  Asset wie heute als fehlend. Ein „verloren“-Merker pro Ziel ist nicht Teil dieser Revision (Grenze, § 7).
- **D10 Video-Aufträge gehören immer einem Thread:** Der Video-Skill kann im Handler eines nicht
  deterministischen Tasks laufen (Intent, Social), der den Einstieg nach einem Neustart nicht wieder
  erreicht. Instagram- und Skill-Videos setzt deshalb immer der Resumer fort.
- **D11 Zielschlüssel = bestehende Guards:** Der `subject` jeder Art entspricht dem heutigen
  Doppelstart-Schlüssel (Props: Prop + Varianten-Index + Backend bzw. `shrink:<Datei>`; Locations: Bild +
  Backend + Stufe bzw. Shrink-Datei; Charakter: Charakter + Signatur; Video: Ziel-Datei). Was heute parallel
  laufen darf, darf es weiter (E4). Improvements werten `HubOpBusy` wie `CandidateBusy` (kein Versuch
  verbraucht).
- **D12 Verlorener Upscale ist terminal** für die ganze Gesichtskorrektur (Auftrag: „durch alle Ebenen“);
  andere Upscale-Fehler bleiben wie heute nicht fatal.

## 1. Ziel

Nutzerbefund: „Beim Neustart sollen Generierungsaufträge nicht verloren gehen. Der AI-Hub macht die
Generierungen eh zu Ende, und nach dem Neustart kann das Ergebnis geholt werden.“

- **(E1)** Ein Hub-Job (Mesh, Rig, Gesichtskorrektur, Upscale, Posen-Animation, Video, Mesh-Verkleinerung), der
  beim Neustart von Anima auf dem Hub läuft oder fertig ist, wird nach dem Start **abgeholt und normal
  weiterverarbeitet**: gleiche Dateien, gleiche Sidecars, gleiche Folgeschritte.
- **(E2)** Nach dem Neustart wird **kein zweiter Hub-Job** für dieselbe Arbeit abgeschickt.
- **(E3)** Ist der Job nicht mehr abholbar, endet der Auftrag als fehlgeschlagen („Hub job lost: …“). Nichts
  startet ungefragt neu.
- **(E4)** Ohne Neustart ändert sich am Verhalten nichts außer dem Datensatz, der während des Laufs existiert.

**Nicht im Umfang:** synchrone Bilder (`openai_diffusion`), fremde Async-APIs (CivitAI, `localai_video`,
`together_video`), ein Neustart **des Hubs** (der Hub markiert seine Jobs dann `failed` → E3).

## 2. Ist-Zustand (verifiziert)

- Die Job-ID lebt in Thread-Locals (`openai_mesh._tls.job_id`) bzw. Closures; einzig die Posen-Animation
  persistiert sie (`progress.hub_job` über `on_job_id`) und **storniert** den Job nach dem Neustart (`_handle`).
  Von Hand abholen kann der Admin heute nur Charakter-Meshes per Job-ID (`openai_mesh.fetch_job` →
  `service.fetch_mesh_job` → `model3d.fetch_job_for_current_outfit`, einmalig, ohne Poll). `attach` nutzt
  dieselbe Download-Funktion `_download_results`; der Admin-Weg bleibt unverändert.
- Ein Rig mit falschem Skelett löst heute über `BackendFailedError` den nächsten Ketteneintrag aus. Nach dem
  Anhängen gibt es kein Routing: dort ist es ein einfacher Fehler des Auftrags.
- `TaskQueue.__init__` → `_reset_stale_running`: Queue-Tasks `running` → `pending` (Handler läuft erneut),
  getrackte Zeilen → `interrupted`.
- Thread-Aufträge: `model3d.trigger_generation`/`trigger_rerig`/`trigger_face_retexture`,
  `props`/`location_model3d` `trigger_generation`/`trigger_shrink`, Instagram-Animate (`routes/instagram.py`),
  Video-Skill (`video_generation_skill.py`). Task-Aufträge mit Hub-Jobs: `npc_assets`, `outfit_combos`,
  `improvement_step` (Mesh, Gesichtskorrektur, Prop-/Location-Mesh), `pose_animation`.
- Hub-Backends mit Job-Protokoll: `openai_mesh` (img2mesh, mesh2mesh, mesh2rig, face_retexture),
  `openai_video`, `openai_upscale`, `openai_mesh_animation`. Alle nutzen `_gateway_job.submit_job`/`poll_job`.
- Hub-Aufbewahrung: Standard-TTL 86 400 s, danach 404.

## 3. Entwurf

### 3.1 Auftragsdatensatz `hub_ops` (world.db)

| Spalte | Inhalt |
|---|---|
| `op_id` (PK) | `hop_<hex12>` |
| `kind` | registrierte Auftragsart, z. B. `character_mesh` |
| `subject` | Zielschlüssel (D11); **teilweise eindeutig** (`UNIQUE … WHERE status='running'`) = atomarer Claim des Auftrags |
| `status` | `running` oder `failed` (Fehler gespeichert, Meldung steht noch aus) |
| `inputs` | eingefrorene Eingaben (JSON): Signatur, Zielangaben, Backend-Wahl, Parameter, Dateinamen, SHA-256 der Quelle |
| `state` | Stufenzustand (JSON): je Stufe `job` (`phase`, `job_id`, `backend`, `api_url`, `submitted_at`, `attach_params`, `route`, `collected`) und `result` |
| `owner_kind`, `owner` | `task` + Task-ID oder `thread` + `''` |
| `track_id` | getrackte Anzeigezeile des laufenden Prozesses |
| `label`, `error`, `created_at`, `updated_at` | Anzeige, letzter Fehler, Systemzeit (`utc_now_iso`) |

Dateien des Auftrags liegen dauerhaft unter `<world>/hub_ops/<op_id>/` (eingefrorene Eingabedateien,
abgeholte Rohdaten, Zwischenergebnisse jeder Stufe). Kein API-Key in der DB.

Lebenslauf: Anlegen, sobald die Vorverarbeitung fertig ist (vorher gibt es nichts abzuholen) → Stufen →
Veröffentlichen → Datensatz und Ordner löschen. Fehler: zuerst `status='failed'` + `error` speichern, dann
Anzeigezeile abschließen, dann löschen — außer beim Grabstein (D8), der bis zum Ende seines Tasks bleibt.
Ein beim Start gefundener `failed`-Datensatz eines Threads oder eines beendeten Tasks wird gemeldet und
gelöscht; der eines lebenden Tasks bleibt für dessen Handler.

Beim Charakter gilt „Veröffentlichen“ erst, wenn der `_serial_model`-Wrapper die Stage veröffentlicht hat:
Der Datensatz wird außerhalb des Wrappers abgeschlossen, ein `stale`-Ergebnis endet als Fehler.

### 3.2 Stufen-Zustandsmaschine und Stufenfunktionen

Jede Auftragsart besteht aus Stufen. Eine **Hub-Stufe** hat die Phasen
`claimed → posting → submitted → collected → done`; lokale Stufen nur `done`. Die Stufenfunktionen sind
dieselben im Normallauf und in der Fortsetzung; sie lesen ausschließlich `inputs` und die Ergebnisse
früherer Stufen, nie den aktuellen Zustand der Welt (Signatur, getragenes Outfit, Galerie-Auswahl).
Hat eine Stufe schon einen Job, wird **vor** jeder Verfügbarkeits-, Routing-, Eignungs- oder
Hauptschalter-Prüfung abgeholt (z. B. `_wait_for_explicit_backend`, `resolve_spec`,
`face_retexture.runnable`, `resolve_animation_backend`, `prepare_motion`): Ein beim Start noch nicht
erreichbares Backend darf ein abholbares Ergebnis nicht verwerfen.

Charakter-Aufträge laufen in Normallauf und Fortsetzung durch **dieselbe** mit `_serial_model` dekorierte
Funktion; der öffentliche Einstieg sucht den offenen Auftrag **vor** dem Wrapper und übergibt die
eingefrorene Signatur (sonst würde der Wrapper bei `signature=None` die getragene stagen). Die Fortsetzung
setzt `mesh_published` aus dem Zustand (Stufe `checkpoint`), damit ein Rig-Fehler das statische Mesh wie
heute mit `rig_error` markiert. Für die Rig-Stufe einer Gesichtskorrektur wird die korrigierte Quelle aus
dem Auftragsordner vorher nach `facefix/<sig>.glb` der Stage zurückgeschrieben, damit `_rig_from_source`
Metadaten und die Erhaltungsprüfung wie gewohnt findet.

| Auftragsart | Stufen | Normaler Einstieg |
|---|---|---|
| `character_mesh` | `mesh` → `checkpoint` → `rig` → Veröffentlichen | `model3d.generate_for_current_outfit` |
| `character_rerig` | `rig` → Veröffentlichen | `model3d.rerig_model` |
| `face_retexture` | `upscale` (optional) → `face` → `bake` → `rig` → Veröffentlichen | `model3d.face_retexture_model` |
| `prop_mesh` | `mesh` → Veröffentlichen | `props._generate` (nach dem Quellbild-Render) |
| `prop_shrink` | `shrink` → Veröffentlichen | `props._shrink` |
| `location_mesh` | `mesh` → Veröffentlichen | `location_model3d._generate` |
| `location_shrink` | `shrink` → Veröffentlichen | `location_model3d._shrink` |
| `video_instagram` | `video` → Veröffentlichen (Feed + Bild-Meta) | Instagram-Animate |
| `video_character` | `video` → Veröffentlichen (Bild-Meta) | Video-Skill (nach dem Standbild) |
| `pose_animation` | `animation` → Konvertieren → `awaiting_choice` | `pose_animation._handle` |

Zwischenergebnisse liegen im Auftragsordner, nicht im Staging: Hub-Mesh-Stufen schreiben ihr Ergebnis dorthin
(statt direkt in die Galerie); das Veröffentlichen kopiert es ans Ziel. Der Galeriepfad wird beim ersten
Veröffentlichen gewählt und im Zustand festgehalten, damit ein wiederholtes Veröffentlichen kein zweites Ziel
anlegt. Die Gesichtskorrektur legt korrigierte Quelle, Vergleichsbild, Sidecar-Daten und die Ersetzungsmaske
(`.npy`) im Auftragsordner ab. Das statische Mesh (`checkpoint`) wird wie heute sofort veröffentlicht; die
Fortsetzung beginnt danach beim Rig, ohne Cache-Check.

### 3.3 Service-Ebene: Stufen-Griff

Die Service-Methoden `generate_mesh`, `generate_mesh_variant`, `generate_rig`, `generate_face_retexture`,
`upscale_image`, `generate_video`, `generate_mesh_animation` bekommen `hub_stage=None` (Griff auf eine Stufe).

- **Ohne Griff:** unverändert (E4).
- **Griff ohne Job:** Die Stufe wird atomar beansprucht (`prepare()`), dann läuft der normale Weg (Routing,
  GPU-Kanal, `run_on_backend`). Der Griff wandert in `params["hub_stage"]` mit, weil der GPU-Kanal auf einem
  anderen Thread läuft. `submit_job` setzt vor jedem POST `posting`, nach der Antwort `submitted` mit Job-ID,
  Backend, `api_url`, `submitted_at`, den Abhol-Parametern (z. B. SHA-256 der Eingaben, Variantenzahl) und der
  Route (`run_routed(on_route=…)`). Ein Wiederholungslauf von `run_routed` auf dem nächsten Ketteneintrag
  überschreibt den Job — das ist derselbe Prozess, kein Neu-Absenden nach Neustart.
- **Griff mit Job:** kein Routing, kein POST, kein GPU-Slot, kein Hauptschalter. `HubStage.collect()` nimmt das
  Backend über den Namen, prüft URL und Alter, ruft `backend.attach(job_id, attach_params, since=…)` und legt
  die Rohdaten im Auftragsordner ab (`collected`). Danach dieselbe Nachbearbeitung wie im Normalweg.
- **Griff mit `posting` ohne Job-ID:** `HubJobLost` (D1).

Jedes Hub-Backend bekommt `attach(job_id, params, *, since, should_cancel=None)`: die Poll- und Download-Hälfte
des bisherigen `_generate`, **herausgezogen**, nicht kopiert (`_collect`).

### 3.4 Verloren vs. nicht erreichbar (`poll_job(attach_since=…)`)

**Verloren** → `HubJobLost` (neu in `app/imagegen/base.py`, Text beginnt mit „Hub job lost:“):
410, 3× 404, Job-Status `failed`/`error`/`cancelled`, Backend nicht mehr konfiguriert oder `api_url` geändert,
`submitted_at` älter als 24 h (ohne HTTP-Aufruf), Zeitbudget D5 überschritten, Absendelücke D1, Ergebnis nach
10 Versuchen nicht herunterladbar.

**Nicht erreichbar**: Verbindungsfehler oder 5xx. Beim Anhängen kein Abbruch nach 10 Fehlern; Wartezeit steigt
auf 30 s, bis 24 h ab `submitted_at` erreicht sind.

`HubJobLost` ist terminal in jeder Ebene:
- `selection.run_on_backend`: eigener Zweig, re-raise, **keine** Abkühlpause, **kein** `BackendFailedError`
  (also auch kein Ketten-Fallback in `run_routed`).
- Service-Methoden mit Sammel-`except`: re-raise (`generate_mesh`, `generate_video`, `generate_mesh_variant`,
  `generate_mesh_animation`), ebenso `animate.animate_image`.
- `model3d.face_retexture_model`: der Upscale-Fehler-Zweig lässt `HubJobLost` durch.
- `TaskQueue`: `HubJobLost` → `failed` ohne Wiederholung, unabhängig von `max_retries`.
- Improvements: Schritt sofort `skipped`, kein zweiter Versuch.

### 3.5 Eigentümer und wer fortsetzt

- **Task-Eigentümer:** Läuft ein Einstieg im Handler eines Queue-Tasks, ist der Task Eigentümer
  (`task_queue.current_task_id()`, Thread-Local im Worker). Nach dem Neustart läuft der Handler erneut; der
  Einstieg sucht zuerst einen offenen Auftrag **seines** Tasks (`hub_ops.find_open`) und setzt diesen fort —
  mit der eingefrorenen Signatur, nicht der getragenen (Befund `npc_assets`). Ohne Signatur-Argument passt jeder
  offene Auftrag des Tasks für dieses Ziel, mit Signatur nur der gleichen.
- **Thread-Eigentümer:** setzt der Resumer fort.
- **D4:** Endet ein Task endgültig (erledigt, fehlgeschlagen ohne Wiederholung) mit offenem Auftrag, wird
  dieser zum Thread-Auftrag und läuft sofort weiter. Abgebrochen → Hub-Job stornieren, verwerfen.
- **Handler-Vorverarbeitung:** `outfit_combos` überspringt eine Signatur nicht, solange ihr Task dafür einen
  offenen Auftrag hat (das veröffentlichte statische Mesh ließe sie sonst „fertig“ aussehen), und rendert
  ihre T-Pose nicht neu. Die Posen-Animation nutzt bei der Fortsetzung den eingefrorenen Clip-Namen
  (`reserve_kind` ist nicht idempotent) und überspringt den LLM-Schritt.

### 3.6 Resumer beim Start

`hub_ops.start_resumer()` läuft im Lifespan **nach** der Handler-Registrierung (der Image-Service ist ein
lazy Singleton und wird beim ersten Abholen gebaut), **vor** AgentLoop
und `TaskQueue.start()`. Er arbeitet synchron nur das Einlesen ab und startet Daemon-Threads:

1. `failed`-Datensätze melden und löschen.
2. Unbekannte Art (Code entfernt): `failed` mit „resume operation unknown“, Hub-Job stornieren, löschen.
3. Task-Eigentümer, Task `pending`/`running`: Abholweg — die laufende Hub-Stufe wird im Hintergrund abgeholt
   (`collect`), auch wenn die Queue pausiert ist; den Rest macht der Handler. Abholen und Handler teilen
   eine Sperre je Stufe; der Handler wartet und nimmt das abgelegte Ergebnis. Ein Verlust beim Abholen wird
   als Grabstein gespeichert (D8). Task beendet oder fehlt → D4.
4. Thread-Eigentümer: **synchron** die prozessinternen Sperren der Art setzen (z. B. `model3d._generating`,
   `props._generating`), dann ein Thread pro Auftrag. Erst danach starten AgentLoop und Worker; ein
   Auto-Mesh-Hook sieht den Charakter also als beschäftigt.

Fortsetzung läuft auch bei eingefrorener Welt und bei ausgeschaltetem Medien-Hauptschalter: Abholen erzeugt
nichts. Folgestufen mit **neuem** Hub-Job laufen über `run_on_backend_channel` und damit weiter über den
Hauptschalter; `MediaGenerationDisabled` beendet den Auftrag mit genau diesem Fehler.

Ziel gelöscht (Charakter/Prop/Location/Post weg): Die Stufe prüft wie heute ihr Ziel; der Auftrag endet,
der Hub-Job wird storniert.

### 3.7 Posen-Animation

`_handle` legt nach dem LLM-Schritt einen `pose_animation`-Auftrag an (Eingaben: Captions, Seed, Key,
Eintrag, Gruppe, Loop, Varianten, Backend, Motion-Meta). Nach dem Neustart: Progress `awaiting_choice` → wie
heute fertig. Sonst offener Auftrag des Tasks → Stufe `animation` anhängen, dann die gemeinsame
Konvertier-Funktion (neu: `_build_candidates`, herausgezogen aus der Schleife in `_handle`; die
Einzelvariante bleibt `_build_candidate`) → `awaiting_choice`. Ohne Auftrag (Neustart vor dem Absenden) bleibt
es beim Fehler „interrupted by restart“; ein alter Progress mit `hub_job` ohne Auftrag (vor diesem Deploy)
wird wie bisher storniert.

### 3.8 Anzeige

- Normale Läufe: Anzeigezeilen wie heute; ihre ID steht im Auftrag.
- Fortsetzung: neue Zeile mit dem ursprünglichen Typ und dem Label `<label> — collecting after restart`; die
  alte (`interrupted`) Zeile erhält im Fehlertext „ — resumed as <neue ID>“.
- Die Fortsetzungszeile ist vom 20-min-Reaper ausgenommen (`track_hold`) und wird mit `track_finish_if_open`
  beendet, damit ein Abbruch nicht überschrieben wird.
- Abbrechen der Fortsetzungszeile (`track_cancel` in der Queue-Ansicht) → `should_cancel` im Poll → Hub-Job
  `POST /v1/jobs/{id}/cancel`, Auftrag gelöscht.
- Texte englisch; Task-Labels sind Daten (wie die bestehenden „3D model: …“), keine `t()`-Schlüssel.
  Neue UI-Fläche: keine.

### 3.9 Hub-TTL

Unverändert 24 h. Der Abholweg holt Task-Aufträge pausierter Queues sofort nach dem Start ab, damit die TTL
nicht abläuft, während die Queue steht.

## 4. Fehlerfälle

| Fall | Ergebnis |
|---|---|
| Neustart, Job in der Hub-Queue oder laufend | anhängen, warten, abholen, weiterverarbeiten |
| Neustart, Job fertig | anhängen, sofort abholen |
| Neustart nach Abholen, vor dem Löschen | `collected`: Rohdaten aus dem Auftragsordner; sonst Hub liefert erneut |
| Neustart zwischen zwei Stufen (Mesh fertig, Rig nicht abgeschickt) | Rig wird normal abgeschickt (neuer Job, Hauptschalter gilt) |
| Neustart während des POST (D1) | `HubJobLost`, kein neuer Job; die Doku nennt die Lücke |
| Hub beim Start nicht erreichbar | alle bis zu 30 s erneut, bis 24 h |
| Hub neu gestartet | `failed`/404 → `HubJobLost` |
| Zweiter Start desselben Ziels | abgelehnt (D3) |
| Ziel gelöscht | Auftrag endet, Hub-Job storniert |
| Zwei Welten | jede Welt hat ihr Register in ihrer `world.db` |
| Task pausiert | Abholweg sichert das Ergebnis, Handler macht später weiter |

## 5. Tests

`scripts/smoke_hub_job_resume.py`, ohne Server, temporäre Welt (`paths.init(<tmp>)`), Fake-Hub als lokaler
`http.server`, erwartete Werte im Docstring von Hand hergeleitet. Schwere Blender-Schritte werden ersetzt.

1. Absenden mit Stufen-Griff → genau ein Datensatz mit Job-ID, Backend, Besitzer; Ende → Datensatz und Ordner weg.
2. Simulierter Neustart (Prozessspeicher leer, DB bleibt): **0 POSTs**, ≥ 1 GET, Ergebnis am normalen Ziel.
3. 404 → `HubJobLost`, keine Abkühlpause, kein zweiter Ketteneintrag, Datensatz weg, Task `failed` ohne Retry.
4. 503 bzw. Verbindungsabbruch → kein `HubJobLost`; nach Rückkehr abgeholt.
5. Resumer: Task-Aufträge nur abholen (auch bei pausierter Queue), Thread-Aufträge fortsetzen, Sperren vor dem
   Start gesetzt.
6. Posen-Animation: Fortsetzung hängt an statt zu stornieren, Ende `awaiting_choice`.
7. Signatur A eingefroren, Charakter trägt B → Ergebnis unter A.
8. `submitted_at` älter als 24 h → `HubJobLost` ohne HTTP.

§-0-Fälle: Quellbild nicht neu gerendert, kein zweites Galerieziel; offenes Rig trotz veröffentlichtem
statischem Mesh fortgesetzt; korrigierte Gesichtsquelle dauerhaft; Datensatz bis Veröffentlichen, Fehler vor
dem Löschen gespeichert; `HubJobLost` durch `run_on_backend`, `run_routed`, Face-Upscale, Task-Queue,
Improvements; Absendelücke D1; Claim D2/D3; Reaper und `track_finish_if_open`; D4-Übergabe.

Weiter grün: `smoke_imports_resolve.py`, `smoke_auth_gate.py`, `smoke_profile_rmw_lock.py`,
`smoke_game_time_lint.py`, sowie die Hub-Smokes `smoke_mesh_gateway`, `smoke_mesh_rig_split`,
`smoke_face_retexture_rollback`, `smoke_mesh_animation_backend`, `smoke_upscale_backends`. Auf `main` schon rot
(vorbestehend): `smoke_scripts_storage_lint`, `smoke_mesh_fetch_job`, `smoke_gateway_503_mapping` (C7a/C7d).

## 6. Doku

- `CLAUDE.md` ist gitignored und liegt nicht im Repository; der Absatz (Register, Stufen, `HubJobLost`,
  Resumer, Absendelücke) steht im PR zum Einfügen und in `docs/hub-job-resume.md`.
- README: eine Zeile in der Feature-Liste mit Verweis auf `docs/hub-job-resume.md`.
- `docs/skill-core-api.md` bleibt unverändert: alle Auftragsarten sind Core.

## 7. Bekannte Grenzen

- Absendelücke (D1): Ein im POST-Fenster angenommener Job läuft auf dem Hub verwaist.
- Der Video-Skill kann seine Chat-Antwort nach einem Neustart nicht mehr zustellen; das Video landet trotzdem
  in der Galerie.
- Mehr als 24 h Ausfall (Hub-TTL) → `HubJobLost`.
- Ein Absturz mitten im lokalen Veröffentlichen (Sekunden) wiederholt das Veröffentlichen; Galeriepfade
  (Haupt- und LOD-Dateien) stehen vorher im Zustand, Seiteneffekte wie `request_lod` können doppelt anlaufen
  (idempotent).
- D9: Unabhängige Auto-Produzenten können ein nach Verlust fehlendes Asset später neu erzeugen.
- Die Posen-Animation holt pausierte Queues über denselben Abholweg ab; ihr Konvertieren braucht Blender und
  läuft erst im Handler.
