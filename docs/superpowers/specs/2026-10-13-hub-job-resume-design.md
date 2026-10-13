# Spec: Hub-Jobs überleben einen Anima-Neustart

Stand: 2026-10-13, **Revision 1, ÜBERHOLT. Revision 2 ist nötig, bevor ein Plan entsteht.**
Design mit dem Nutzer abschnittsweise abgestimmt (Umfang, Fehlerfall, Ansatz A, Abschnitte 1–3).

## 0. Stand nach Review-Runde 1 (Codex `gpt-6-astra`, 2026-10-13). Hier weitermachen.

**Befund:** § 3 („Fortsetzen durch erneutes Ausführen der ganzen Operation“) ist nicht tragfähig.
- **Vorverarbeitung wird mit wiederholt:** Props rendern ihr Quellbild neu, und Props und Locations
  legen neue Galerieziele an (`props.py` ~6200/6261, `location_model3d.py` ~1313).
- **Ketten zerfallen:** Der Cache-Check in `generate_for_current_outfit` (~1680) überspringt einen
  ausstehenden Rig-Job. Die Gesichtskorrektur legt die korrigierte Quelle nur im Staging ab.
- **Zeilen werden zu früh gelöscht:** Sie verschwinden vor Prüfen, Rig und Veröffentlichen bzw. vor dem
  Instagram-Feed.
- **`HubJobLost` geht verloren:** Die Ausnahme wird als Backend-Fehler eingewickelt
  (`selection.py` ~364 → Routing-Fallback `routing.py` ~541). Upscale-Fehler werden geschluckt
  (`model3d.py` ~2278), dazu kommen die Wiederholungen von Queue und Improvements.
- **Schlüssel instabil:** `npc_assets` nimmt die gerade getragene Signatur (~382). Beim Video fehlen
  LoRAs und Dauer im Schlüssel.
- **Weitere Lücken:** Die Start-Reihenfolge (AgentLoop vor den TaskQueue-Workern, `server.py` ~651/661)
  und pausierte Queues sind nicht berücksichtigt. Abholer würden nach 20 min als `interrupted` geerntet,
  und `track_finish` überschreibt unbedingt.
- **Absendelücke:** Zwischen der Annahme des POST und dem Speichern der Job-ID kann ein doppelter
  Job entstehen.
- Das Gesichtskorrektur-Backend ist `openai_mesh` (`openai_mesh.py` ~618). `poll_job` meldet 404/410
  schon heute als `GatewayRejectedError`.

**Neue Richtung (vom Nutzer noch nicht im Detail abgenommen):**
- **Auftragsdatensatz** mit eingefrorenen Eingaben: Signatur, Hash der Quelldatei, Zieldateien,
  Backend und Route.
- **Stufen-Zustandsmaschine**, z. B. `mesh → rig → publish` oder `upscale → face → rig → publish`.
- **Pipelines in Stufenfunktionen zerlegt**, die der Normallauf und die Fortsetzung GEMEINSAM nutzen.
- **Zwischenergebnisse dauerhaft abgelegt** statt nur im Staging.
- **Datensatz bis zum Veröffentlichen behalten.** Ein terminaler Fehler wird gespeichert, bevor der
  Datensatz gelöscht wird.
- **`HubJobLost` typisiert** durch alle Ebenen durchgereicht.
- **Atomarer Claim** vor dem Absenden.
- **Resumer** vor AgentLoop und Workern starten. Zusätzlich ein Abholweg für pausierte Queues.

**Nutzerentscheidungen:**
- 2026-10-13: Umfang **in einem Zug** (alle Arten aus § 1, keine Phasen), aber **nicht sofort**.
- 2026-10-13: Die Absendelücke wird **hingenommen**. Der ai-hub bleibt unverändert, die Doku nennt die Lücke.
- 2026-10-13: Umsetzung als **Cloud-Code-Auftrag** auf dem Branch `feat/hub-job-resume`. Die Spec Rev. 2
  ersetzt DIESE Datei (versioniert als Ausnahme von `development_instructions/`); der Plan kommt nach
  `docs/superpowers/plans/2026-10-13-hub-job-resume-plan.md`.

**Nächster Schritt:** Spec Revision 2 schreiben → erneutes Codex-Review → Nutzer-Review → Plan.

## 1. Ziel

Nutzerbefund: „Beim Neustart sollen Generierungsaufträge nicht verloren gehen. Der AI-Hub macht die
Generierungen eh zu Ende, und nach dem Neustart kann das Ergebnis geholt werden.“

**Erfolg heißt:**

- **(E1)** Ein langer Hub-Job (Mesh, Rig, Gesichtskorrektur, Posen-Animation, Video, Upscale), der beim
  Neustart von Anima auf dem Hub läuft oder schon fertig ist, wird nach dem Start **abgeholt und normal
  weiterverarbeitet**: gleiche Dateien, gleiche Sidecars, gleiche Folgeschritte wie ohne Neustart.
- **(E2)** Nach dem Neustart wird **kein zweiter Hub-Job** für dieselbe Arbeit abgeschickt (heute
  passiert das bei Task-Queue-Aufträgen; der alte Job läuft verwaist weiter).
- **(E3)** Ist der Job nicht mehr abholbar, wird der Auftrag **als fehlgeschlagen markiert**
  („Hub job lost“). Nichts startet ungefragt neu (Nutzerentscheidung 2).
- **(E4)** Ohne Neustart ändert sich am Verhalten nichts; das Register ist im Normalbetrieb leer.

**Nicht im Umfang** (Nutzerentscheidung 1):

- Normale Bilder über `openai_diffusion`: synchron, ohne Job-ID. Sie bleiben, wie sie sind.
- Fremde Async-APIs (CivitAI-Workflows, `localai_video`, `together_video`): eigene Job-IDs, nicht der Hub.
- Ein Neustart **des Hubs**: Der Hub markiert dabei seine laufenden Jobs als `failed`
  (`jobs.reconcile_orphans()` im ai-hub). Das ist der Fall „verloren“ aus E3, nicht mehr.

## 2. Ist-Zustand (Kurzfassung)

- Die Job-ID existiert nur in Thread-Locals und Closures (`_gateway_job.submit_job` → `poll_job`).
  Persistiert wird sie einzig in der Posen-Animation (Task-`progress`, `pose_animation.py` ~L359), und
  dort wird der Job nach dem Neustart **abgebrochen** (`_handle`, ~L304–312).
- Task-Queue-Aufträge (`npc_assets`, `outfit_combos`, `improvement_step`, `pose_animation`) werden beim
  Start auf `pending` gesetzt und **von vorn** ausgeführt (`task_queue._reset_stale_running` /
  `_recover_stale_running`).
- Thread-Aufträge (`model3d.trigger_generation`, `trigger_rerig`, `trigger_face_retexture`,
  `props`/`location_model3d` `_generate`/`_shrink`, Video aus Instagram/Video-Skill) sind nach dem
  Neustart weg; ihre `track_start`-Zeile wird `interrupted`.
- Vorhandene Bausteine: `openai_mesh.fetch_job` (einmaliges Abholen ohne Poll und ohne GPU-Slot),
  `service.fetch_mesh_job`, `model3d.fetch_job_for_current_outfit` (Admin-Route, nimmt die **aktuelle**
  Signatur), `_checkpoint_mesh` + `_rig_from_source` (Rig aus gespeicherter Quelle).
- Hub-Aufbewahrung: Standard-TTL 86 400 s (`jobs.default_ttl_s`), abgelaufene Jobs antworten **404**.

## 3. Ansatz: Fortsetzen durch erneutes Ausführen

Es gibt **keine** zweite Nachbearbeitung. Nach dem Neustart wird die **ursprüngliche Operation** erneut
ausgeführt; die Service-Methode erkennt am **Schlüssel**, dass zu dieser Arbeit schon ein Hub-Job läuft,
und hängt sich an ihn, statt neu abzuschicken. Alles danach läuft auf dem normalen Code-Weg.

### 3.1 Register `hub_jobs` (world.db)

| Spalte | Inhalt |
|---|---|
| `key` (PK) | fester Schlüssel aus den Eingaben, siehe 3.2 |
| `job_id` | Hub-Job-ID |
| `backend` | Backend-Name (kein API-Key in der DB) |
| `api_url` | zur Plausibilisierung; Abweichung vom konfigurierten Backend = verloren |
| `media` | `mesh` / `rig` / `face` / `upscale` / `video` / `animation` |
| `owner_kind` | `task` oder `op` |
| `owner` | Task-ID bzw. registrierter Operationsname (z. B. `model3d.generate`) |
| `op_args` | JSON-Argumente der Operation (nur bei `owner_kind = op`) |
| `submitted_at` | Systemzeit (`utc_now`), technischer Stempel |
| `label` | Anzeigetext für die Task-Liste |

Schreibzugriffe unter einer Sperre. Eine Zeile wird **beim Absenden** geschrieben (direkt nachdem
`submit_job` die Job-ID hat) und **beim Ende des Aufrufs** gelöscht, egal ob Erfolg oder Fehler. Ausnahme:
Endet der Prozess, bleibt sie stehen. Genau das ist der Fortsetzungsfall.

Neues Modul `app/core/hub_jobs.py`: `record(...)`, `find(key)`, `forget(key)`, `pending_ops()`,
`register_op(name, fn)`, `resume_pending()`.

### 3.2 Schlüssel

Deterministisch aus den Eingaben, die die Arbeit bestimmen. Bei Charakteren gilt die **Signatur zum
Zeitpunkt des Absendens**:

| Medium | Schlüssel |
|---|---|
| Charakter-Mesh | `mesh:<Charakter>:<Signatur>` |
| Rig | `rig:<Charakter>:<Signatur>` |
| Gesichtskorrektur | `face:<Charakter>:<Signatur>` |
| Upscale (Gesichtskorrektur) | `upscale:<Charakter>:<Signatur>` |
| Prop-Mesh / Prop-Variante | `prop_mesh:<Prop>:<Variante>`, `prop_shrink:<Prop>:<Variante>` |
| Location-Mesh / -Variante | `loc_mesh:<Location>:<Raum>:<Ansicht>`, `loc_shrink:…` |
| Video | `video:<Quelldatei>:<sha1(Prompt)[:12]>` |
| Posen-Animation | bleibt im Task-`progress` (eigener Weg, 3.6) |

Die genaue Zusammensetzung bei Props und Locations legt der Umsetzungsplan anhand der `_generate`- und
`_shrink`-Argumente fest. Bedingung: Zwei Aufrufe für **dieselbe** Zieldatei haben denselben Schlüssel.

### 3.3 Service-Ebene: anhängen statt absenden

Die Service-Methoden `generate_mesh`, `generate_mesh_variant`, `generate_rig`, `generate_face_retexture`,
`upscale_image`, `generate_video` (Hub-Backend `openai_video`) bekommen ein optionales Argument
`resume: Optional[ResumeSpec]` (`key`, `owner_kind`, `owner`, `op_args`, `label`).

- **Ohne vorhandene Zeile:** normaler Weg (Routing, GPU-Kanal, `run_on_backend`). Ein `on_job_id`-Hook
  wird in die Backend-Parameter gelegt (Muster aus `openai_mesh_animation`); `_gateway_job.submit_job`
  ruft ihn nach dem Absenden auf, und er schreibt die Zeile. Der Hook steckt in den Parametern, weil der
  GPU-Kanal `_gen` auf einem anderen Thread ausführt; ein Thread-Local käme dort nicht an.
- **Mit vorhandener Zeile:** kein Routing, kein POST, **kein GPU-Slot** (der Job belegt schon die GPU
  des Hubs). Das Backend wird über den Namen aus dem Pool genommen, `poll_job` mit derselben
  `on_done`-Download-Funktion wie im Normalfall aufgerufen und das Ergebnis genauso abgelegt wie sonst
  (`_store_mesh_files` usw.). Rückgabe im normalen Ergebnisformat, ergänzt um `resumed: True`.
- **Ende des Aufrufs** (Erfolg, Fehler, Abbruch): Zeile löschen.

Dafür bekommt jedes betroffene Backend (`openai_mesh`, `openai_video`, `openai_upscale`,
`openai_mesh_animation` sowie das Gesichtskorrektur-Backend) eine Methode `attach(job_id, params)`, die
die Poll- und Download-Hälfte seines `generate` ohne Absenden ausführt. Sie wird aus dem bestehenden
`generate` herausgezogen, nicht kopiert.

### 3.4 Verloren vs. nicht erreichbar

- **Verloren**, also endgültig: Hub antwortet 404 oder 410, Job-Status `failed` oder `cancelled`, das
  Backend ist nicht mehr konfiguriert oder seine URL weicht ab, die Zeile ist älter als 24 h.
  → neue Ausnahme `HubJobLost` (in `app/imagegen/base.py`). Sie ist **terminal**: kein Retry, kein
  Fallback auf den nächsten Ketteneintrag, **keine Abkühlpause** für das Backend. Die Zeile wird
  gelöscht.
- **Nicht erreichbar**: Verbindungsfehler oder 5xx. Das gilt **nicht** als verloren. Beim Anhängen
  wird alle 30 s erneut gefragt, bis die 24 h erreicht sind. Die Lost-Job-Kappen von `poll_job`
  (3× 404, 10 andere Fehler) gelten beim Anhängen nur für 404/410. Für Netzfehler zählt die 24-h-Grenze.
- Die Laufzeitbudgets (`max_wait`, `max_queue_wait`) zählen beim Anhängen ab `submitted_at`, nicht ab
  dem Neustart.

### 3.5 Wer setzt fort

**Task-Queue-Aufträge** (`npc_assets`, `outfit_combos`, `improvement_step`): Die Queue führt den Handler
nach dem Start ohnehin erneut aus. Die Hub-Aufrufe darin geben `resume` mit `owner_kind = task` und
finden ihre Zeile. Kein eigener Fortsetzungscode. `HubJobLost` lässt den Task **ohne** Wiederholung
fehlschlagen, auch wenn der Task sonst Retries hätte (`npc_assets`: `ASSET_RETRIES = 2`).

**Thread-Aufträge**: Die auslösende Funktion registriert eine Operation (`hub_jobs.register_op`) und
gibt sie als Besitzer an:

| Operation | Fortsetzung |
|---|---|
| `model3d.generate(char, sig, …)` | ungeriggter Checkpoint der Signatur vorhanden → `_rig_from_source`; sonst `generate_for_current_outfit(signature=sig, force=True, …)` |
| `model3d.rerig(char, sig, backend_glob)` | `rerig_model` |
| `model3d.face_retexture(char, sig, …)` | `face_retexture_model`; das Upscale nutzt den Cache `facefix-ref`, der Gesichts-Job hängt sich an |
| `props.generate(…)`, `props.shrink(…)` | `_generate` / `_shrink` mit den gespeicherten Argumenten |
| `location_model3d.generate(…)`, `location_model3d.shrink(…)` | dito |
| `video.animate(…)` | Instagram-Animate bzw. Video-Skill mit den gespeicherten Argumenten |

`generate_for_current_outfit` ruft Mesh und Rig nacheinander auf. Steht beim Neustart der Rig-Job aus,
existiert schon der Checkpoint des ungeriggten Meshs; die Fortsetzung beginnt deshalb beim Rig.

**Posen-Animation** (3.6): eigener Weg über den Task-`progress`.

### 3.6 Posen-Animation

In `pose_animation._handle` wird der Zweig „`progress` vorhanden, kein `awaiting_choice`“ umgebaut:
Steht `hub_job` und `backend` im `progress`, wird **angehängt** (`attach` des Animations-Backends) und
mit den gespeicherten `captions`, `seed`, `key`, `entry` und `variants` an der Stelle nach
`generate_mesh_animation` weitergemacht (Konvertieren → `awaiting_choice`). Ohne `hub_job` (der Neustart
kam vor dem Absenden) bleibt es beim heutigen Fehler „interrupted by restart“. `HubJobLost` → Task
fehlgeschlagen mit „Hub job lost“.

### 3.7 Resumer beim Start

`hub_jobs.resume_pending()` wird im Server-Lifespan **nach** Task-Queue und Image-Service gestartet.

- Er nimmt nur Zeilen mit `owner_kind = op`; Task-Zeilen bedient der neu laufende Handler.
- Zeilen derselben Operation und derselben Argumente werden zu **einer** Fortsetzung zusammengefasst
  (z. B. ein verwaistes Mesh- und ein Rig-Schlüssel derselben Signatur).
- Pro Fortsetzung startet ein Daemon-Thread. Die vorhandenen Sperren (`_char_lock`, `_serial_model`,
  Prop-/Location-Sperren) sorgen für die Reihenfolge.
- Er läuft **auch bei eingefrorener Welt** und **auch bei ausgeschaltetem Medien-Hauptschalter**. Es wird
  nichts erzeugt, nur abgeholt. Folgeschritte, die einen **neuen** Hub-Job brauchen (z. B. das Rig
  nach einem abgeholten Mesh), unterliegen weiter dem Hauptschalter; bei `MediaGenerationDisabled`
  endet die Fortsetzung mit genau diesem Fehler.
- Ist die Operation unbekannt (Code entfernt, Plugin deinstalliert): Zeile löschen, Task-Eintrag
  fehlgeschlagen mit „resume operation unknown“.

### 3.8 Anzeige

- Jede Fortsetzung erhält einen `track_start`-Eintrag mit dem ursprünglichen Typ (z. B.
  `model3d_generation`) und dem Label `<label> — collecting after restart`. Am Ende `track_finish`:
  erfolgreich oder Fehler „Hub job lost: <Grund>“.
- Die beim Start als `interrupted` markierten Einträge der alten Laufzeit, deren Arbeit fortgesetzt
  wird, bekommen im Fehlertext den Zusatz „resumed as <neue Task-ID>“.
- Abbrechen eines Fortsetzungs-Eintrags in der Task-Liste storniert den Hub-Job
  (`POST /v1/jobs/{id}/cancel`) und löscht die Zeile. Der Weg dafür ist derselbe `should_cancel`-Hook,
  den `poll_job` schon kennt.
- Texte englisch. Die Task-Liste in Game-Admin → Queue zeigt die Einträge schon heute an; eine neue
  UI-Fläche ist nicht nötig. Server-Texte, die an React gehen, laufen über `t()`.

### 3.9 Hub-TTL

Unverändert 24 h (Hub-Standard). Ein Anima-Neustart dauert Sekunden bis Minuten. Wird mehr gebraucht,
lässt sich `ttl_s` später pro Anfrage setzen; das ist nicht Teil dieser Spec.

## 4. Fehlerfälle

| Fall | Ergebnis |
|---|---|
| Neustart während der Job beim Hub in der Queue steht | anhängen, warten, abholen |
| Neustart, Job schon fertig | anhängen, sofort abholen |
| Neustart nach Abholen, vor dem Löschen der Zeile | anhängen; der Hub liefert dasselbe Ergebnis erneut (innerhalb der TTL); die Nachbearbeitung schreibt dieselben Zieldateien |
| Hub ist beim Start nicht erreichbar | alle 30 s erneut, bis 24 h |
| Hub wurde selbst neu gestartet | Status `failed` bzw. 404 → `HubJobLost` |
| Nutzer startet dieselbe Arbeit von Hand, während die Zeile steht | derselbe Schlüssel → hängt sich an den laufenden Job, kein zweiter Job |
| Charakter, Prop oder Location inzwischen gelöscht | die Operation prüft wie heute ihr Ziel (`character_gone` usw.); der Hub-Job wird storniert, die Zeile gelöscht |
| Zwei Welten | jede Welt hat ihr eigenes Register in ihrer `world.db` |

## 5. Tests

`scripts/smoke_hub_job_resume.py`, ohne Server: temporäre Welt (`paths.init(<tmp>)` vor jedem
Welt-Import), ein Fake-Hub als lokaler `http.server`, erwartete Werte von Hand im Docstring.

1. Absenden mit `resume` → genau eine Zeile mit Schlüssel, Job-ID und Besitzer. Normales Ende → Zeile weg.
2. Simulierter Neustart (Prozessspeicher leer, DB bleibt): Derselbe Aufruf erzeugt **0 POSTs** an
   `/v1/generations` und ≥ 1 GET auf `/v1/jobs/{id}`; das Ergebnis liegt am normalen Zielort.
3. Fake-Hub antwortet 404 → `HubJobLost`, keine Abkühlpause am Backend, kein zweiter
   Ketteneintrag, Zeile weg, Task-Eintrag fehlgeschlagen.
4. Fake-Hub antwortet 503 bzw. die Verbindung bricht ab → kein `HubJobLost`; nach Rückkehr wird
   abgeholt.
5. Der Resumer überspringt Task-Zeilen und fasst Mesh- und Rig-Zeile derselben Signatur zu einer
   Fortsetzung zusammen.
6. Posen-Animation: `progress` mit `hub_job` → `attach` statt `_cancel_lost_job`; Ende in
   `awaiting_choice`.
7. Signatur: Zeile mit Signatur A, Charakter trägt inzwischen B → das Ergebnis landet unter A.
8. Zeile älter als 24 h → `HubJobLost` ohne HTTP-Aufruf.

Außerdem müssen weiter grün sein: `smoke_imports_resolve.py`, `smoke_auth_gate.py`,
`smoke_profile_rmw_lock.py`, `smoke_game_time_lint.py` (der Stempel ist Systemzeit, keine
Spielzeit), `smoke_scripts_storage_lint.py`.

## 6. Doku

- `CLAUDE.md`: ein Absatz beim Image-Generation-Block: Register `hub_jobs`, Schlüsselregel,
  `HubJobLost` terminal, Resumer.
- README: eine Zeile in der Feature-Liste.
- `docs/skill-core-api.md` nur, falls `register_op` für Plugins öffentlich wird. In diesem Umfang
  nicht, alle Operationen sind Core.

## 7. Offene Punkte für den Umsetzungsplan

- Exakte Schlüssel für Props und Locations (3.2).
- Ob das Gesichtskorrektur-Backend `openai_mesh` ist oder ein eigenes. Davon hängt ab, wo `attach` liegt.
- Wie Instagram-Animate und Video-Skill ihr Ergebnis heute ablegen, damit `video.animate` die nötigen
  Argumente speichert.
