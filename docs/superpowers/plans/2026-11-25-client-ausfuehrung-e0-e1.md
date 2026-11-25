# Client-Ausführung E0 (Messbasis) + E1 (HUD-Workspace und Herleitungen) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** E0 schafft die Messbasis (Server-Zähler, Messskript, Client-Sonde „erster Schritt“, Baseline-Tabelle); E1 zieht den React-HUD aus `client3d/` in einen eigenen Workspace `hud/` (→ `static/hud/`, der CEF-HUD des nativen Clients lädt `static/hud/hud.html`) und verlegt alle Vektor-Herleitungen aus `client3d/scripts/` an Orte, die das Löschen der Browser-Szene in E3 überleben — ohne Verhaltenswechsel.

**Architecture:** E0 hängt sich an das vorhandene `app/core/hot_path_stats` (eine Logzeile pro Name und Minute in `logs/main.log`) und ergänzt nur Zähler; das Messskript liest ausschließlich `/proc/<pid>/stat`, `logs/main.log` und ein Client-Log. E1 ist ein reiner Umzug: Dateien per `git mv` mit erhaltener Relativstruktur (`hud/src/hud/*`, `hud/src/game/*` …), `client3d` importiert die verschobenen Module als Paket `@anima/hud`, drei Typ-Kanten werden gekappt. Herleitungen gehen je nach Herkunft nach `scripts/` (ganze Smoke, wenn der getestete Code in `packages/*` oder `hud/src` lebt), in eine Python-Smoke (Server-Zwilling) oder in ein Herleitungsdokument `native/tests/Derivations/<name>.md` (C#-Tests führen die Vektoren aus). Ein Wächter `scripts/smoke_vector_sources.py` beweist die Verlegung wortgetreu gegen einen festen Commit.

**Tech Stack:** Python 3 / FastAPI (`./.venv/bin/python`), Node ESM-Smokes (esbuild aus dem Root-`node_modules`), npm-Workspaces + Vite 8 + TypeScript 5, Godot 4.7.2 mono / .NET 8 / xUnit (`native/test.sh`).

**Spec:** `docs/superpowers/specs/2026-11-25-client-ausfuehrung-design.md` (Abschnitte 5k „Browser-Client“, 7 „Messung und Erfolg“, 8 „Etappen“ Zeilen E0/E1).

## Global Constraints

- Geteilter Arbeitsbaum auf `main`, kein Worktree, kein `--amend`, kein `stash`, kein `rebase`. Andere Sessions committen parallel.
- **Pfadgenaue Commits:** `git add <genau die Pfade>` und `git commit -m "<msg>" -- <dieselben Pfade>`. Bei `git mv` gehören alter **und** neuer Pfad in die Liste. Vor dem ersten Edit einer Datei: `git diff --quiet -- <datei>`; hat sie fremde, nicht committete Hunks, Datei nicht anfassen und dem Orchestrator melden.
- Jede Commit-Nachricht endet mit der Zeile `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>` (Projekt-CLAUDE.md).
- **Kein Zugriff auf `worlds/`** (weder lesen noch schreiben, keine Live-`world.db`). Python-Checks: `paths.init(<tmpdir>)` vor jedem Welt-DB-Import; wer `app.server` importiert, setzt `STORAGE_DIR` **und** `INSTANCE_DIR` auf Temp-Verzeichnisse.
- Smokes leiten Erwartungswerte **von Hand im Docstring** her (Muster `scripts/smoke_scene_recipe.py`, `scripts/smoke_hot_path_stats.py`); keine Schnappschüsse. Ein Vorher-Beweis pinnt einen expliziten Commit-Hash, nie `HEAD:`. Für diesen Plan: **`PIN = 011cd048aa3cc2937186d7f35d2203af9491db8a`**.
- **`docs/superpowers/` ist gitignoriert** (`.gitignore:243`; getrackt sind nur einzelne per `-f` hinzugefügte Dateien). Jede Datei darunter (Spec, dieser Plan, Baseline) wird ausschließlich mit `git add -f <pfad>` gestaged. Spec und Plan dieses Vorhabens werden in Task 5 Step 2 einmalig per `-f` mitcommittet, damit Task 13 nur noch den Abschnitt-9-Diff der Spec committet.
- Gebaute Bundles `static/*` sind committet: Wer Quellen von `hud/`, `client3d/` oder `frontend/` ändert, baut im **selben Task** (`npm run build -w <ws>`) und nimmt `git add -A static/<ws>` mit in denselben Commit.
- Der native Client muss nach jedem Commit funktionieren (CEF-HUD lädt das HUD-Bundle). `native/test.sh` braucht `GODOT=<Pfad zu Godot_v4.7.2-stable_mono_linux.x86_64>`; finden mit `find / -name 'Godot_v4.7.2-stable_mono_linux.x86_64' -type f 2>/dev/null | head -1`.
- `grep` ist ein ugrep-Wrapper, der still nichts liefern kann: `command grep -rna` oder `git grep -a` benutzen.
- Code-Kommentare/Docstrings Englisch; deutsche Kommentare in angefassten Dateien ins Englische übersetzen. Keine Rückwärtskompatibilitäts-Aliase (kein Re-Export am alten Ort, kein Symlink `client3d/hud.html`).
- Kein `.env`, keine neuen Konfig-Felder. Der Nutzer startet/neustartet den Server selbst; kein Task startet, stoppt oder befragt den laufenden Server.
- `native/Core` bleibt Godot-frei (`native/tests/CoreIsGodotFreeTests.cs`).

## Entscheidungen dieses Plans (Claude, ohne Rückfrage getroffen)

1. **Zähler laufen über `hot_path_stats`**, kein neues Modul. Namen: `client_exec_routes` (Schlüssel `<METHOD>:<route-template>`, nur `/play/pos`, `/play/worldmap`, `/play/orders`) und `client_exec_ticker` (Schlüssel `beat`, `advance`, `advance_run`, `advance_validate`). Routenzähler zählen im `RequestTimingMiddleware` (kennt das Routen-Template) mit `flush=False`, damit auf dem Event-Loop nie geloggt wird; die Ticker-Zähler laufen im Worker-Thread des TravelTickers und flushen normal (spätestens alle 5 s ein Aufruf, also verlässlich einmal pro Minute).
2. **Messskript liest Logzeilen per Byte-Offset** — für `logs/main.log` **und** das Client-Log (Größe beim Start merken, am Ende nur den Zuwachs lesen; alte `first_step`-Zeilen zählen so nicht mit). Ist eine Datei am Ende kleiner als beim Start (`start.sh` leert `main.log` per `rotate_log` beim Neustart), bricht das Skript mit Fehlermeldung ab, statt zu rechnen. Die erste Zeile je Name im Fenster wird verworfen (sie trägt Zählungen von vor dem Start); Rate = Summe der restlichen Zeilen · 60 / (t_letzte − t_erste). Weil eine Zeile nur bei Zählung > 0 entsteht, überschätzt diese Rate, wenn die letzten Minuten ereignislos waren — die Tabelle zeigt deshalb zusätzlich Rohsumme und Fensterlänge (Messdauer N). `main.log` hat nur `HH:MM:SS` — Mitternachtsumbruch +86400 s. Empfohlene Messdauer 420 s (bei 300 s bleiben nach dem Verwerfen höchstens vier Intervalle).
3. **Erster Schritt** wird im nativen Client gemessen: Core-Klasse `FirstStepProbe`, Logzeile `[native] first_step source=<s> ms=<x> frames=<n>` bzw. `… timeout` nach 10 s. Schwelle 0,01 m (Spec: „über 1 cm“).
4. **Baseline-Lauf ist nutzergeführt** (Task 5): Er braucht laufenden Server auf einem Welt-Klon und den nativen Client — beides gehört dem Nutzer. Der Task liefert Befehl + Szenario-Checkliste; der Orchestrator trägt die Tabelle ein, sobald der Nutzer das Skriptergebnis liefert.
5. **HUD-Workspace `hud/`, Paketname `@anima/hud`**, Struktur unter `hud/src/` 1:1 wie bisher unter `client3d/src/` (`hud/src/hud/*`, `hud/src/game/*`, `hud/src/api.ts`, `hud/src/types.ts`, `hud/src/scene/fogConstants.ts`, `hud/src/hudPage.tsx`, `hud/hud.html`) — dadurch bleiben alle Relativimporte innerhalb der verschobenen Menge gültig. `exports` ist eine **explizite** Liste (wie `@anima/player-ui`), weil `.ts` und `.tsx` gemischt sind. Build `tsc --noEmit && vite build` → `static/hud/`, Dev-Port 5184. Kein ESLint (wie bisher `client3d`).
6. **Drei Typkanten werden gekappt:** `FinaleBlock` wandert von `client3d/src/game/finaleClip.ts` nach `hud/src/types.ts` (`finaleClip.ts` importiert ihn aus `@anima/hud/types`); `game/soundtrack.ts` deklariert lokal `interface Point { x: number; z: number }` statt `./walk` zu importieren; `game/photoMode.ts` ersetzt `Pick<Engine, …>` durch ein eigenes exportiertes `interface PhotoEngine` mit den sechs Membern (Signaturen aus `client3d/src/scene/engine.ts` übernommen) — `Engine` erfüllt es strukturell, `tsc` von `client3d` beweist es.
7. **Herleitungs-Ziele** (Spec 5k „ziehen nach scripts/ oder native/tests“):
   - **Klasse A** — getesteter Code liegt nur in `packages/*` oder `hud/src`: die ganze Smoke zieht per `git mv` nach `scripts/` und bleibt ausführbar; `source` zeigt dorthin.
   - **Klasse C** — Server-Zwilling mit eigener Python-Smoke, die denselben Vektor liest: Herleitung wandert in deren Docstring, `source` = die `.py`.
   - **Klasse B** — alles andere (Code stirbt mit der Szene in E3): Herleitung wortgetreu nach `native/tests/Derivations/<basis>.md` (`<basis>` = Smoke-Name ohne `smoke_` und `.mjs`), `source` = dieses Dokument; die JS-Smoke bleibt bis E3 lauffähig, ihr Docstring wird durch einen Zeiger ersetzt (eine Kopie, kein Drift).
8. HUD-only-Smokes (testen nur verschobenen Code) ziehen nach `scripts/`; gemischte bleiben in `client3d/scripts/` mit angepassten Pfaden.
9. `undergrowth.json` hat keinen C#-Verbraucher (geprüft: `native/Check/ScatterCheck.cs:321–325` prüft `UndergrowthMath.Shade` gegen `fixtures/scatter_reference.json` (Z. 45), nicht gegen die Vektordatei; `native/tests` liest `undergrowth.json` nicht); E1 verlegt nur die Herleitung. Ob E3 einen C#-Test baut oder die Datei löscht, entscheidet E3 (Übergabepunkt in Task 13).

## Review Focus

1. **Routenzähler ohne eigenen Flush:** `count(..., flush=False)` darf nie loggen, die Zählung muss aber in der nächsten Minutenzeile eines anderen Flush-Auslösers erscheinen — Test [C2] in Task 1.
2. **`/proc/<pid>/stat` mit Klammern/Leerzeichen im Prozessnamen** (`(uvicorn (w) 1)`): nach der **letzten** `)` splitten — Test [M1b] in Task 3.
3. **Mitternacht im Messfenster** (`23:59:30` → `00:00:30`) ergibt 60 s, nicht −86340 s — Test [M3] in Task 3.
4. **Zweite React-Instanz:** hätte `hud/` ein eigenes `node_modules/react`, brechen im Browser-`/play` die Hooks des eingebetteten HUD still — Prüfschritt `test ! -e hud/node_modules/react` in Task 6.
5. **Liegengebliebenes `static/client3d/hud.html`** würde den alten Pfad scheinbar weiter bedienen und einen vergessenen Native-Pfad verdecken — `smoke_play_shell.py` prüft in Task 6 `/static/client3d/hud.html` → 404 und `/static/hud/hud.html` → 200; `HudCheck` prüft den neuen `HudPath`.
6. **Server-PID statt `sg`-Wrapper:** unter `sg render` (`start.sh:287`) trifft `pgrep -f` den Wrapper — das Messskript nimmt `.pids/main.pid` und prüft die Kommandozeile (`is_server_cmdline`, Test [M7] in Task 3).
7. **Wächter nie rot zwischen Commits:** der HUD-Umzug (Task 6) enthält die Scanwurzel- und Doku-Anpassungen (früher Task 7) und eine Vorher/Nachher-Liste aller `.mjs`-Smokes.

---

## Dateiübersicht

| Pfad | Verantwortung | Task |
|---|---|---|
| `app/core/hot_path_stats.py` | `count(name, key, *, flush=True)` | 1 |
| `app/core/request_timing.py` | Routenzähler `client_exec_routes` in `_record` | 1 |
| `app/core/travel_engine.py` | Zähler `beat` in `_next_beat_s` | 2 |
| `app/core/prop_action_engine.py` | Zähler `advance`, `advance_run`, `advance_validate` | 2 |
| `scripts/smoke_client_exec_counters.py` | Smoke Tasks 1–2 | 1, 2 |
| `scripts/measure_client_execution.py` | Messskript (nur lesend) | 3 |
| `scripts/smoke_measure_client_execution.py` | Smoke des Messskripts | 3 |
| `native/Core/Embody/FirstStepProbe.cs` | Sonde Klick → erste Bewegung | 4 |
| `native/tests/FirstStepProbeTests.cs` | xUnit | 4 |
| `native/Figures/PlayerSteering.cs`, `native/Figures/AvatarOffersController.PropActions.cs`, `native/Check/PropActionsCheck.cs` | Sonde scharf schalten / abtasten / prüfen | 4 |
| `docs/superpowers/measurements/2026-11-25-client-ausfuehrung-e0-baseline.md` | Baseline-Tabelle | 5 |
| `hud/` (neu: `package.json`, `hud.html`, `vite.config.ts`, `tsconfig.json`, `dev-proxy-rule.js`, `dev-proxy-rule.d.ts`, `src/vite-env.d.ts`, `public/.gitkeep`, `src/**`) | HUD-Workspace | 6 |
| `.dockerignore` | `hud` neben `client3d` | 6 |
| `static/hud/` (neu, gebaut), `static/client3d/` (neu gebaut) | Bundles | 6 |
| `native/Hud/HudOverlay.cs`, `native/Check/HudCheck.cs`, `native/Check/ResumeCheck.cs` | neuer HUD-Pfad | 6 |
| `scripts/smoke_play_shell.py`, `scripts/smoke_vite_proxy.py` | Pfad-/Proxy-Wächter | 6 |
| Wächter mit Scan-Wurzel `client3d/src` + Doku | `hud/src` aufnehmen | 6 (früher 7) |
| `scripts/smoke_*.mjs` (aus `client3d/scripts` verschoben) | HUD-Smokes | 8 |
| `scripts/smoke_vector_sources.py` | Wächter Herleitungs-Orte | 9 |
| `native/tests/Derivations/*.md` | Herleitungsdokumente Klasse B | 10–12 |
| `shared/test-vectors/*.json` (nur Feld `source`), `shared/test-vectors/README.md`, `shared/test-vectors/smoke_vectors_format.mjs` | Quellen | 8–12 |

---

# E0 — Messbasis

### Task 1: Routenzähler ohne Flush auf dem Event-Loop

**Files:**
- Modify: `app/core/hot_path_stats.py` (`count`, Zeile 62–70)
- Modify: `app/core/request_timing.py` (`_record`, Zeile 76–80; neue Konstante oben)
- Create: `scripts/smoke_client_exec_counters.py`

**Interfaces:**
- Produces: `hot_path_stats.count(name: str, key: str, *, flush: bool = True) -> None`; `request_timing.CLIENT_EXEC_ROUTES: frozenset[str] = frozenset({"/play/pos", "/play/worldmap", "/play/orders"})`; Logzeile `hot_path client_exec_routes POST:/play/pos=<n> GET:/play/worldmap=<n> …`.

- [ ] **Step 1: Failing smoke schreiben.** `scripts/smoke_client_exec_counters.py` nach dem Muster von `scripts/smoke_hot_path_stats.py` (Temp-`STORAGE_DIR`/`INSTANCE_DIR`/`ANIMATION_CLIPS_DIR` vor jedem App-Import, Flush-Uhr per `hps._last_flush = t0` und `flush(now=…)` gesetzt). Docstring mit Herleitungen:
  - [C1] `hps.count("x", "k", flush=False)` mit `_last_flush = t0 - 120` (Minute längst um): Logger-Recorder hat **0** Aufrufe; `hps.flush(now=t0+61)` liefert `["hot_path x k=1"]`.
  - [C2] `count("client_exec_routes", "POST:/play/pos", flush=False)` ×3, dann `count("other", "a")` (flush=True) mit abgelaufener Minute → genau eine Flush-Runde mit den Zeilen `"hot_path client_exec_routes POST:/play/pos=3"` und `"hot_path other a=1"` (Namen alphabetisch, `_count_line`).
  - [C3] `request_timing._record("/play/pos", "POST", 200, 3.0, 10, "ok")` ×2, `_record("/play/worldmap", "GET", 200, 5.0, 10, "ok")` ×1, `_record("/characters/{name}", "GET", 200, 1.0, 10, "ok")` ×4 → nach `hps.flush(now=…)` genau `"hot_path client_exec_routes POST:/play/pos=2 GET:/play/worldmap=1"` (n absteigend, `_count_line`); die Characters-Route erscheint nicht.
  - [C4] `hps.count` wird so gepatcht, dass es wirft → `_record` wirft nicht.
- [ ] **Step 2:** `./.venv/bin/python scripts/smoke_client_exec_counters.py` → FAIL (`count() got an unexpected keyword argument 'flush'`).
- [ ] **Step 3: Implementieren.** `count` bekommt `flush: bool = True`; nur bei `True` wird `flush()` gerufen. In `_record` direkt nach dem `_samples`-Append: wenn `route in CLIENT_EXEC_ROUTES`, `hot_path_stats.count("client_exec_routes", f"{method}:{route}", flush=False)` in eigenem `try/except Exception: pass` (Import auf Modulebene, `hot_path_stats` importiert nichts aus `request_timing`). Docstring von `hot_path_stats` um den Satz zu `flush=False` ergänzen.
- [ ] **Step 4:** Smoke → PASS; zusätzlich `./.venv/bin/python scripts/smoke_hot_path_stats.py`, `scripts/smoke_request_timing.py`, `scripts/smoke_request_timing_writer.py` → PASS.
- [ ] **Step 5: Commit** `feat(stats): count the client-execution routes without flushing on the event loop` — Pfade: die drei Dateien.

### Task 2: Ticker- und advance-Zähler

**Files:**
- Modify: `app/core/travel_engine.py` (`_next_beat_s`, ab Zeile 2302)
- Modify: `app/core/prop_action_engine.py` (`advance` Zeile 2025ff., `_advance_run` Zeile 2067ff., der `_validate`-Aufruf Zeile 2093)
- Modify: `scripts/smoke_client_exec_counters.py`

**Interfaces:**
- Consumes: `hot_path_stats.count` (Task 1).
- Produces: Logzeile `hot_path client_exec_ticker beat=<n> advance=<n> advance_run=<n> advance_validate=<n>` (fehlende Schlüssel = 0).

- [ ] **Step 1: Smoke erweitern** (Recorder: `hps.count` durch `lambda name, key, **kw: calls.append((name, key))` ersetzt):
  - [T1] `travel_engine._next_beat_s()` mit `list_active_journeys` → `[]` und `timeutils.motion_rate` → `1.0`: genau ein `("client_exec_ticker", "beat")`. Mit `motion_rate` → `0` (eingefrorene Welt, früher Return): ebenfalls genau eines — gezählt wird **am Funktionsanfang**, jede Planung ist ein Beat.
  - [T2] `prop_action_engine.advance(now)` mit `store.pending_cleanup` → `[]`, `store.live_runs` → zwei Snapshots `{"execution_id": "r1"}`, `{"execution_id": "r2"}`, `_advance_run` → Stub mit Rückgabe 0, `pose_scene.end_finales` → no-op, `register_owner` → no-op (es läuft vor allem anderen, `prop_action_engine.py:2035`, und würde sonst den globalen Besitzer-Zustand anfassen): Zählungen `advance` ×1, `advance_run` ×2, `advance_validate` ×0.
  - [T3] `_advance_run("r1", now, [])` mit `store.get` → Run `{"status": "approaching", "definition": {"ability": "sit", "interrupt_on_presence_change": False}, "data": {}, "actor": "a", "members": [], "target": {}, "action_id": "x", "phase": "walk"}`, `_lock` → `contextlib.nullcontext`, `_clock` → `(0, 0.0)`, `is_world_frozen` → False, `_validate` → `"stop"`, `_finish` → no-op: genau ein `advance_validate`, Rückgabe 0. (Felder, die der Code vor `_validate` liest, ergänzt der Implementierer minimal; die Erwartung bleibt „ein Zähler, 0“.)
  - [T4] gleicher Run, `is_world_frozen` → True: **kein** `advance_validate`.
- [ ] **Step 2:** Smoke → FAIL ([T1] erwartet 1, bekommt 0).
- [ ] **Step 3: Implementieren.** Erste Zeile in `_next_beat_s`: `_count_ticker("beat")`. In `advance`: `_count_ticker("advance")` als erste Anweisung, `_count_ticker("advance_run")` unmittelbar vor jedem `_advance_run`-Aufruf. In `_advance_run`: `_count_ticker("advance_validate")` unmittelbar vor `reason = _validate(...)` (Zeile 2093). `_count_ticker(key)` je Modul als kleine private Funktion: lazy `from app.core import hot_path_stats`, `hot_path_stats.count("client_exec_ticker", key)`, alles in `try/except Exception: pass` (Muster `figure_build.py:2986`).
- [ ] **Step 4:** Smoke → PASS; `./.venv/bin/python scripts/smoke_imports_resolve.py` → PASS; die vorhandenen Prop-Action- und Travel-Smokes, die `advance`/`_next_beat_s` berühren (`ls scripts | command grep -E "prop_action|travel_tick|next_beat"`), → PASS.
- [ ] **Step 5: Commit** `feat(stats): count travel-ticker beats and prop-action advance/validate steps` — Pfade: drei Dateien.

### Task 3: Messskript

**Files:**
- Create: `scripts/measure_client_execution.py`
- Create: `scripts/smoke_measure_client_execution.py`

**Interfaces:**
- Consumes: Logzeilen aus Task 1/2; Client-Logzeile aus Task 4.
- Produces (reine Funktionen, von der Smoke importiert):
  - `cpu_ticks(stat_text: str) -> int` — utime+stime (Felder 14+15, 1-basiert; nach der letzten `)` gesplittet sind es Index 11 und 12).
  - `parse_hot_path(text: str, name: str) -> list[tuple[int, dict[str, int]]]` — Zeilen `^(\d\d):(\d\d):(\d\d) \[hot_path\] INFO hot_path <name> (k=v ...)$`, Zeit in Sekunden des Tages.
  - `window_rates(lines: list[tuple[int, dict[str, int]]]) -> dict | None` — Entscheidung 2; liefert `{"rates": {key: pro Minute}, "sums": {key: Rohsumme ohne erste Zeile}, "span_s": t_letzte − t_erste}`; `None` bei weniger als 2 Zeilen.
  - `is_server_cmdline(raw: bytes) -> bool` — `/proc/<pid>/cmdline` (NUL-getrennt): erstes Argument hat einen Basisnamen, der mit `python` beginnt, und ein Argument ist `uvicorn` bzw. endet auf `/uvicorn`; ein `sg`- oder `bash`-Wrapper ist `False`.
  - `read_growth(path, start_size) -> str` — liest ab Byte-Offset `start_size`; wirft `LogShrunk`, wenn die Datei jetzt kleiner ist.
  - `first_steps(text: str) -> list[tuple[str, float | None]]` — aus `[native] first_step source=<s> ms=<x> frames=<n>` bzw. `… source=<s> timeout` (`None`).
  - `render_table(r: dict) -> str` — Markdown-Tabelle (Spalten: Wert, Rohsumme, Zeitspanne der Logzeilen s, Messdauer s) mit den Zeilen: Server-CPU s/min, `/play/pos`/s, `/play/pos`/min, `/play/worldmap`/min, `/play/orders`/min, Ticker-Beats/min, `advance()`/min, `_advance_run`/min, `_validate` in advance/min, erster Schritt Median ms + Anzahl + Timeouts; fehlender Wert = `n/a`.
  - CLI: `./.venv/bin/python scripts/measure_client_execution.py record --seconds N [--pid PID] [--log logs/main.log] [--client-log PATH] [--label TEXT] [--out PATH]`. Ohne `--pid` wird `.pids/main.pid` gelesen (dort steht laut `start.sh:284–296` die Server-PID, nicht die des `sg`-Wrappers); fehlt die Datei: Fehler mit Hinweis auf `./start.sh --status`. Vor dem Messen `is_server_cmdline(/proc/<pid>/cmdline)`, sonst Abbruch mit Hinweis „PID ist nicht der uvicorn-Python-Prozess (sg-Wrapper?)“. `--client-log` ist das Log des nativen Clients, `<Exportordner>/logs/native-<Zeit>.log` (`native/build.sh`, `run.sh`-Zeile `--log-file`). Ablauf: `stat` lesen, Größe von `main.log` und Client-Log merken, `N` s schlafen (Fortschritt jede Minute auf stderr), erneut lesen; CPU s/min = Δticks/`os.sysconf("SC_CLK_TCK")` · 60/N; beide Logs nur über `read_growth` lesen (Schrumpfen → Abbruch, Entscheidung 2). Ausgabe auf stdout, mit `--out` zusätzlich angehängt an die Datei (Überschrift `## <label> — <ISO-Zeit>`). Liest nur — keine DB, kein HTTP.
- [ ] **Step 1: Smoke schreiben** mit Herleitungen:
  - [M1] `"4242 (python3) S 1 2 3 4 5 6 7 8 9 10 300 50 0 0 …"` → nach `)`: Index 0=`S` … Index 11=`300`, 12=`50` → 350.
  - [M1b] `"4242 (uvicorn (w) 1) S 1 2 3 4 5 6 7 8 9 10 300 50 0 0"` → 350 (letzte Klammer).
  - [M2] Zeilen `10:00:05 … client_exec_routes POST:/play/pos=100`, `10:01:05 … POST:/play/pos=180 GET:/play/worldmap=20`, `10:02:05 … POST:/play/pos=180 GET:/play/worldmap=20` → erste verworfen; Summe pos 360, worldmap 40; Dauer 120 s → `rates == {"POST:/play/pos": 180.0, "GET:/play/worldmap": 20.0}` pro Minute (180/60 = 3,0/s), `sums == {"POST:/play/pos": 360, "GET:/play/worldmap": 40}`, `span_s == 120`.
  - [M3] `23:59:30 … beat=12`, `00:00:30 … beat=12` → Dauer 60 s, `rates == {"beat": 12.0}`, `span_s == 60`.
  - [M4] eine einzige Zeile → `None`; Tabelle zeigt `n/a`.
  - [M5] Client-Log mit `[native] first_step source=click_walk ms=20.0 frames=1`, `[native] first_step source=prop_offer ms=1450.0 frames=87`, `[native] first_step source=prop_offer timeout` → `[("click_walk", 20.0), ("prop_offer", 1450.0), ("prop_offer", None)]`; Tabelle: Median 735.0 ms (Mittel aus 20.0 und 1450.0), n=2, Timeouts 1.
  - [M6] Zeilen anderer Namen (`hot_path notify …`) und Nicht-hot_path-Zeilen werden ignoriert.
  - [M7] `is_server_cmdline(b"/x/.venv/bin/python\0-m\0uvicorn\0app.server:app\0")` → True; `b"sg\0render\0-c\0exec setsid /x/.venv/bin/python -m uvicorn app.server:app\0"` → False (erstes Argument `sg`); `b"/usr/bin/python3\0-m\0http.server\0"` → False (kein `uvicorn`).
  - [M8] `read_growth` auf einer Temp-Datei: Start 10 Byte, danach 25 Byte → genau die 15 neuen Byte; Start 25, danach 5 Byte → `LogShrunk`.
- [ ] **Step 2:** `./.venv/bin/python scripts/smoke_measure_client_execution.py` → FAIL (Modul fehlt).
- [ ] **Step 3:** Skript implementieren (Usage-Docstring mit dem Szenario aus Spec 7: „Avatar läuft 60 s frei und nimmt dann einen Sessel; drei NPCs gehen nacheinander ins Bett; eine Überlandreise läuft“ und der Empfehlung `--seconds 420`; mindestens 180 s, sonst Warnung auf stderr).
- [ ] **Step 4:** Smoke → PASS; `./.venv/bin/python scripts/smoke_scripts_storage_lint.py` → PASS.
- [ ] **Step 5: Commit** `feat(measure): read-only client-execution measurement script` — Pfade: beide Dateien.

### Task 4: Sonde „erster Schritt“ im nativen Client

**Files:**
- Create: `native/Core/Embody/FirstStepProbe.cs`
- Create: `native/tests/FirstStepProbeTests.cs`
- Modify: `native/Figures/PlayerSteering.cs` (Property, `WalkTo` Zeile ~87–98, `Step` Zeile ~113ff.)
- Modify: `native/Figures/AvatarOffersController.PropActions.cs` (Handler `pickPropAction`, Zeile 81–89; `PickSemanticProp` Zeile 321–326 bleibt unberührt — es öffnet nur das HUD-Menü)
- Modify: `native/Check/PropActionsCheck.cs` (ein zusätzlicher Check)

**Interfaces:**
- Produces: `public sealed class FirstStepProbe` (Namespace wie die übrigen `Core/Embody`-Typen) mit `public const double MoveThresholdM = 0.01, TimeoutS = 10.0;`, `public void Arm(string source, double clockS, double x, double z)`, `public FirstStepResult? Sample(double clockS, double x, double z)`, `public bool Armed { get; }`; `public sealed record FirstStepResult(string Source, double? LatencyMs, int Frames)` (`LatencyMs == null` = Timeout). `PlayerSteering.FirstStep` (`FirstStepProbe`, get-only, neu instanziert).
- [ ] **Step 1: xUnit-Tests** (Herleitung im Klassenkommentar):
  - [F1] `Arm("click_walk", 10.0, 0, 0)`; `Sample(10.016, 0.005, 0)` → null (0,005 m < 0,01); `Sample(10.032, 0.02, 0)` → `("click_walk", 32.0 ±1e-6, 2)`; danach `Armed == false`, weiteres `Sample` → null.
  - [F2] Unscharf: `Sample` → null, `Frames` zählt nicht.
  - [F3] Erneutes `Arm` vor einem Treffer ersetzt Quelle, Startzeit, Startpunkt und setzt Frames auf 0.
  - [F4] `Arm("prop_offer", 0, 1, 1)`; `Sample(10.0, 1, 1)` → null (genau 10 s ist noch kein Timeout); `Sample(10.5, 1, 1)` → `("prop_offer", null, 2)`, danach unscharf.
  - [F5] Diagonale: Start (0,0), `Sample(…, 0.008, 0.008)` → Abstand 0,0113 > 0,01 → Treffer.
- [ ] **Step 2:** `dotnet test native/tests --filter FirstStepProbeTests` → FAIL (Typ fehlt).
- [ ] **Step 3:** Probe implementieren; einbauen: `WalkTo` ruft nach erfolgreichem `SetWalkTarget` `FirstStep.Arm("click_walk", _clock, pos.X, pos.Z)`. Der HUD-Handler `pickPropAction` ruft nach der Argumentprüfung und **direkt vor** `PreviewPropTarget(target)` `_steering.FirstStep.Arm("prop_offer", _steering.Clock, avatar.Position.X, avatar.Position.Z)` (nur wenn ein Avatar existiert) — erst dort startet die Aktion; ein Scharfschalten in `PickSemanticProp` würde die Lesezeit im Menü mitmessen und nach 10 s im Menü einen `timeout` erzeugen. `PropActionsCheck`: nach `hud.Handlers["pickPropAction"](…)` mit gültigem Ziel ist `steering.FirstStep.Armed == true`. `PlayerSteering.Step`: direkt nach `_clock+=dt` und **vor** allen frühen Returns — wenn `FirstStep.Armed` und `Avatar is { } a`, `FirstStep.Sample(_clock, a.Position.X, a.Position.Z)` auswerten und bei Ergebnis `GD.Print` mit exakt `[native] first_step source=<s> ms=<F1-Format "0.0"> frames=<n>` bzw. `[native] first_step source=<s> timeout` (Format muss zu `first_steps` aus Task 3 passen; Zahlen mit `CultureInfo.InvariantCulture`).
- [ ] **Step 4:** `GODOT=… native/test.sh` → `== all native checks passed` (umfasst `CoreIsGodotFreeTests`).
- [ ] **Step 5: Commit** `feat(native): first-step probe from click to the avatar's first centimetre` — Pfade: fünf Dateien.

### Task 5: Baseline aufnehmen (nutzergeführt)

**Files:**
- Create: `docs/superpowers/measurements/2026-11-25-client-ausfuehrung-e0-baseline.md`

- [ ] **Step 1:** Dokument anlegen: Zweck (Spec 7), Szenario-Checkliste (Avatar 60 s frei laufen, dann per Klick einen Sessel nehmen; drei NPCs nacheinander ins Bett schicken; eine Überlandreise starten), der exakte Befehl
  `./.venv/bin/python scripts/measure_client_execution.py record --seconds 420 --pid $(cat .pids/main.pid) --client-log <Exportordner>/logs/native-<Zeit>.log --label "E0 baseline" --out docs/superpowers/measurements/2026-11-25-client-ausfuehrung-e0-baseline.md`
  (PID aus der PID-Datei von `start.sh`, nie per `pgrep -f`: unter `sg render` träfe das den Wrapper; das Skript prüft die Kommandozeile zusätzlich und bricht sonst ab. Das Client-Log ist das aktuelle `native-*.log` des laufenden Clients; der Server darf im Messfenster nicht neu starten, sonst bricht das Skript ab.)
  und der Hinweis: Server mit den Commits aus Task 1–2 neu gestartet, Welt = Klon (nie die Spielwelt), nativer Client mit Task 4 gebaut.
- [ ] **Step 2: Commit** `docs(measure): E0 baseline procedure` — `docs/superpowers/` ist gitignoriert: `git add -f` für das Dokument **sowie** `docs/superpowers/specs/2026-11-25-client-ausfuehrung-design.md` und `docs/superpowers/plans/2026-11-25-client-ausfuehrung-e0-e1.md` (Erstaufnahme von Spec und Plan); `git commit -- <diese drei Pfade>`.
- [ ] **Step 3 (Orchestrator ↔ Nutzer):** Der Orchestrator meldet dem Nutzer (auf Deutsch) Befehl und Checkliste. Der Lauf selbst gehört dem Nutzer; kein Subagent startet einen Server oder öffnet eine Welt. Hängt das Skript seinen Abschnitt an, committet der Orchestrator die Datei pfadgenau mit `git add -f` (`docs(measure): E0 baseline numbers`). **Abnahme E0:** Nutzer sieht die Tabelle. E1 darf parallel beginnen; es ändert nichts, was gemessen wird.

---

# E1 — HUD-Workspace und Herleitungen

### Task 6: HUD-Workspace `hud/` anlegen, `client3d` umhängen, nativen HUD-Pfad umstellen, Wächter und Doku nachziehen (ein atomarer Commit)

Der frühere Task 7 (Scanwurzeln der Wächter, Doku) ist in diesen Task gezogen (Review B3): `smoke_docs_claude_md.py`, `smoke_docs_schnittstellen_3d.py` und `smoke_i18n_orphans.py` wären sonst zwischen zwei Commits auf dem geteilten `main` rot.

**Files:**
- Move (`git mv`, Ziel `hud/<gleicher Relativpfad>`): `client3d/hud.html` → `hud/hud.html`; `client3d/src/hudPage.tsx`; `client3d/src/hud/` (alle 26 Dateien inkl. `hud.css`, `theme-fantasy.css`); `client3d/src/api.ts`; `client3d/src/types.ts`; `client3d/src/scene/fogConstants.ts`; `client3d/src/game/{boot,channelReadouts,elevator,infoPanel,minimap,offers,perfstats,photoMode,photoView,prefs,readoutReports,soundtrack,stairs,travelPick,voiceover}.ts` (jeweils `client3d/src/X` → `hud/src/X`).
- Create: `hud/package.json`, `hud/vite.config.ts`, `hud/tsconfig.json`, `hud/dev-proxy-rule.js`, `hud/dev-proxy-rule.d.ts` (Kopie von `client3d/dev-proxy-rule.d.ts`), `hud/src/vite-env.d.ts` (Kopie von `client3d/src/vite-env.d.ts`), `hud/public/.gitkeep`
- Modify: `.dockerignore` (Z. 27: `hud` neben `client3d`), `package.json` (Wurzel), `client3d/package.json`, `client3d/vite.config.ts`, `client3d/dev-proxy-rule.js`, `client3d/src/game/finaleClip.ts`, alle `client3d/src/**`-Dateien, die verschobene Module importieren, `client3d/src/main.ts:505`, alle Pfadverweise in `client3d/scripts/*.mjs` und `scripts/*.mjs`/`scripts/*.py` auf verschobene Dateien
- Modify: `native/Hud/HudOverlay.cs` (Zeile 13, 50, 341), `native/Check/HudCheck.cs` (Zeilen 276–311, 348–349), `native/Check/ResumeCheck.cs` (Zeile 31), Doku-Kommentare `native/Core/Hud/HudProtocol.cs:11,67`, `native/Core/Overview/PerfStats.cs:76`
- Modify: `scripts/smoke_play_shell.py` (Zeile 38), `scripts/smoke_vite_proxy.py`, `scripts/smoke_docs_client3d_readme.py` (Zeile 67 `HUD`), `client3d/README.md`
- Modify (aus dem früheren Task 7): `scripts/smoke_auth_gate.py` (Zeile 154, 717), `scripts/smoke_dead_config_fields.py` (Zeile 66, 225), `scripts/smoke_docs_claude_md.py` (Zeile 24, 39, 139, 206, 264), `scripts/smoke_docs_config_defaults.py` (Zeile 22, 94), `scripts/smoke_docs_schnittstellen_3d.py` (Zeile 122), `scripts/smoke_i18n_orphans.py` (Zeile 66, 128), `scripts/smoke_no_native_dialogs.py` (Zeile 77), `scripts/smoke_docs_model_libraries.py` (Zeile 76), `scripts/smoke_piece_colour_meta_gone.py` (Zeile 51), `scripts/smoke_foot_pose_call_sites.py` (Zeile 92, `SCAN_DIRS`)
- Modify (Doku, aus dem früheren Task 7): `docs/schnittstellen-3d.md` (jeder Verweis `client3d/src/<verschobener pfad>`), `CLAUDE.md` (Commands + Frontend), `README.md` (Z. 88, 624), `native/README.md` (Z. 1560–1561: `client3d/hud.html`, `/static/client3d/hud.html?bridge=gdcef`), `docker/README.md`, `docker/DEPLOYMENT.md`, `docker/Dockerfile:39` (Kommentar), `start.sh:19` (Kommentar)
- Build: `static/hud/` (neu), `static/client3d/` (neu gebaut, ohne `hud.html`)

**Interfaces:**
- Produces: Workspace `hud`, Paket `@anima/hud` mit `"type": "module"`, `"private": true`, Skripten `dev: "vite"`, `build: "tsc --noEmit && vite build"`, Abhängigkeiten `@anima/player-ui`, `@anima/scene-render`, `react`, `react-dom`, `three` (verschobene Dateien importieren `three`; nicht auf Hoisting verlassen) — Versionen wie `client3d/package.json`; devDependencies `@types/react`, `@types/react-dom`, `@types/three`, `@types/node` (`vite.config.ts` nutzt `process.env`), `@vitejs/plugin-react`, `typescript`, `vite` (gleiche Versionen, fest eingetragen). `exports` explizit, je ein Eintrag `"./<pfad ohne Endung>": "./src/<pfad mit Endung>"` für: `api`, `types`, `hud/dom`, `hud/bus`, `hud/bridge`, `hud/mount`, `hud/photoMode`, `game/boot`, `game/channelReadouts`, `game/elevator`, `game/infoPanel`, `game/minimap`, `game/offers`, `game/perfstats`, `game/photoMode`, `game/photoView`, `game/prefs`, `game/readoutReports`, `game/soundtrack`, `game/stairs`, `scene/fogConstants` — plus jeder weitere Pfad, den `tsc` von `client3d` danach noch als fehlend meldet.
- Produces: `hud/src/game/photoMode.ts` exportiert `interface PhotoEngine` (Entscheidung 6); `hud/src/types.ts` exportiert `FinaleBlock`.
- Produces: `HudOverlay.HudPath == "static/hud/hud.html?bridge=gdcef"`.

- [ ] **Step 0: Vorprüfung und Vorher-Liste.** `git status --porcelain client3d packages hud scripts native/Hud native/Check native/Core/Hud native/Core/Overview docs/schnittstellen-3d.md CLAUDE.md README.md native/README.md docker start.sh .dockerignore package.json package-lock.json` muss frei von fremden Hunks sein (eigene gibt es noch keine) — sonst Task stoppen und dem Orchestrator melden. Dann die Vorher-Liste aufnehmen: jede `client3d/scripts/smoke_*.mjs` und `scripts/smoke_*.mjs` mit `timeout 300 node <datei>` laufen lassen, Ergebnis (grün/rot) je Datei in eine Scratch-Datei schreiben; ebenso die Python-Wächter aus „Files“ (`./.venv/bin/python <datei>`, `smoke_auth_gate.py`/`smoke_play_shell.py` mit Temp-`STORAGE_DIR`/`INSTANCE_DIR`).
- [ ] **Step 1: Wächter zuerst ändern (rot).** `scripts/smoke_play_shell.py`: `client.get("/static/hud/hud.html").status_code == 200` und `client.get("/static/client3d/hud.html").status_code == 404` (Docstring-Herleitung: der HUD zieht nach `static/hud`, Spec 5k; kein Alias am alten Ort). `native/Check/HudCheck.cs`: die erwarteten Strings auf `/static/hud/hud.html?bridge=gdcef`, die Quelldateien auf `repo:hud/src/hud/bridge.ts` / `bus.ts`; zusätzlich `HudOverlay.HudPath == "static/hud/hud.html?bridge=gdcef"` prüfen. `ResumeCheck.cs:31` analog.
- [ ] **Step 2:** `STORAGE_DIR=$(mktemp -d) INSTANCE_DIR=$(mktemp -d) ./.venv/bin/python scripts/smoke_play_shell.py` → FAIL (200 statt 404 bzw. 404 statt 200).
- [ ] **Step 3: Verschieben.** Alle `git mv` aus „Files“. `hud/hud.html`: `<script type="module" src="/src/hudPage.tsx">` bleibt textgleich (Vite-Root ist jetzt `hud/`).
- [ ] **Step 4: Workspace-Dateien.** `hud/vite.config.ts` nach `client3d/vite.config.ts`: `base: command === 'build' ? '/static/hud/' : '/'`, `build.outDir: '../static/hud'`, `emptyOutDir: true`, `rollupOptions.input: { hud: 'hud.html' }`, Dev-Server `host '0.0.0.0'`, `port: 5184`, derselbe Catch-all-Proxy über `viteDevTarget`. `hud/dev-proxy-rule.js`: `ENTRIES = ['hud.html']`, `createDevTarget({ publicDir: new URL('./public/', import.meta.url), entries: ENTRIES })` (wirft `createDevTarget` bei fehlendem Verzeichnis, `hud/public/.gitkeep` anlegen). `hud/tsconfig.json` = Kopie von `client3d/tsconfig.json`. Wurzel-`package.json`: `workspaces` `["frontend", "hud", "client3d", "packages/*"]`; Skripte `dev:hud`, `build:hud`; `build` = `npm run build -w frontend && npm run build -w hud && npm run build -w client3d`; `description` nennt den HUD. `client3d/package.json`: Abhängigkeit `"@anima/hud": "*"`. `client3d/vite.config.ts` und `client3d/dev-proxy-rule.js`: Eintrag `hud.html` entfernen.
- [ ] **Step 5: Kanten kappen und Importe umschreiben.** Entscheidung 6 umsetzen. In jeder verbleibenden `client3d/src`-Datei werden Relativimporte auf verschobene Module zu `@anima/hud/<pfad ohne Endung>` (CSS-Importe gibt es außerhalb von `hud/` keine; falls doch: `@anima/hud` exportiert sie zusätzlich). `client3d/src/main.ts:505`: `frame.src = '/static/hud/hud.html'` (der HUD ist kein Teil des 3D-Bundles mehr). Bewusste Folge: das ist nur der Debug-Pfad `?hud=iframe` (`main.ts:724`); im Vite-Dev von `client3d` lädt er das **gebaute** HUD-Bundle ohne HMR — wer am HUD selbst arbeitet, nutzt `npm run dev -w hud` (:5184). In `client3d/scripts/*.mjs`, `scripts/*.mjs`, `scripts/*.py` und `native/**/*.cs` jede Zeichenkette `client3d/src/<verschobener pfad>` bzw. `../src/<verschobener pfad>` auf `hud/src/<pfad>` bzw. den korrekten Relativpfad setzen; Liste der Treffer mit `command grep -rnaE "(client3d/src|\.\./src)/(hud/|hudPage|api\.ts|types\.ts|scene/fogConstants|game/(boot|channelReadouts|elevator|infoPanel|minimap|offers|perfstats|photoMode|photoView|prefs|readoutReports|soundtrack|stairs|travelPick|voiceover))" client3d/scripts scripts native` erzeugen und abarbeiten; zusätzlich die Komma-Form von `path.join` erfassen: `command grep -rnaE "'client3d', *'src'" client3d/scripts scripts` (Beispiel `client3d/scripts/smoke_graphics_prefs.mjs:110` baut `join(ROOT, 'client3d', 'src', 'game', 'prefs.ts')`) — jeder Treffer auf ein verschobenes Modul wird auf `'hud', 'src', …` umgestellt. Doku-Kommentare in `HudOverlay.cs:13`, `HudProtocol.cs`, `PerfStats.cs` auf `hud/…`. `HudOverlay.HudPath` und die `Contains`-Prüfung Zeile 341 auf `/static/hud/hud.html`.
- [ ] **Step 6: Doku-Wächter des Workspaces.** `scripts/smoke_vite_proxy.py` um die dritte App `hud` erweitern (gleiche Prüfungen A–F; Docstring: Einträge `/hud.html` → Vite, alles andere Backend). Die Präfix-Liste aus Prüfung E wird extrahiert für `client3d` aus `client3d/src` + `hud/src` + `packages/player-ui/src` (der Dev-Server von `client3d` bündelt `@anima/hud` weiter; `api.ts` liegt jetzt in `hud/src`) und für `hud` aus `hud/src` + `packages/player-ui/src`. Die erwartete Anzahl je App im Docstring herleiten (Zählung der Präfixe je Wurzel, Vereinigung), nicht aus einem Lauf übernehmen. `scripts/smoke_docs_client3d_readme.py`: `HUD = REPO / "hud" / "src" / "hud"` und die README-Prüfung C auf „`hud/`-Workspace“ umformulieren; `client3d/README.md` entsprechend (der HUD liegt in `../hud`, Anzahl `.tsx`-Dateien nennen).
- [ ] **Step 6b: Scanwurzeln und Doku (früher Task 7 Step 1–2).** In jedem Wächter aus „Files (aus dem früheren Task 7)“ steht `hud/src` (bzw. `"hud"` bei Wurzel-Listen wie `SRC_ROOTS`/`SCAN_DIRS`, `hud/package.json` neben `client3d/package.json`) **neben** `client3d/src`; Erwartung je Wächter im Docstring nachziehen (welche Wurzeln gescannt werden). `docs/schnittstellen-3d.md`: Verweise auf verschobene Dateien auf `hud/src/…` umschreiben (Liste: `command grep -naE "client3d/src/(hud/|hudPage|api\.ts|types\.ts|scene/fogConstants|game/(boot|channelReadouts|elevator|infoPanel|minimap|offers|perfstats|photoMode|photoView|prefs|readoutReports|soundtrack|stairs|travelPick|voiceover))" docs/schnittstellen-3d.md`). `CLAUDE.md`: Commands-Block um `npm run dev -w hud    # HUD-Seite allein auf :5184` und `npm run build` = „frontend, hud und client3d“ ergänzen; Frontend-Abschnitt: neuer Punkt „**HUD** in `hud/` (`@anima/hud`) — die React-HUD-Seite, baut nach committetem `static/hud/`; der CEF-HUD des nativen Clients lädt `/static/hud/hud.html?bridge=gdcef`, die Browser-Szene importiert den HUD als Paket“; im `client3d`-Punkt „The HUD is React (`src/hud/`)“ durch Verweis auf `hud/` ersetzen. `README.md` (Z. 88, 624), `native/README.md` (Z. 1560–1561) und Docker-Doku: `hud/` bzw. `static/hud/hud.html` statt `client3d/hud.html`, `static/hud/` neben `static/client3d/`.
- [ ] **Step 7: Installieren und bauen.** `npm install` (Wurzel), dann `test ! -e hud/node_modules/react && test ! -e client3d/node_modules/react` (genau eine React-Instanz, Review Focus 4). `npm run build -w hud` → `static/hud/hud.html` existiert; `npm run build -w client3d` → `static/client3d/hud.html` existiert **nicht**; `npm run build -w frontend` nur, falls `frontend`-Quellen berührt wurden (nicht vorgesehen).
- [ ] **Step 8: Prüfen.** `smoke_play_shell.py` (mit Temp-Dirs) → PASS; `./.venv/bin/python scripts/smoke_vite_proxy.py`, `scripts/smoke_docs_client3d_readme.py` → PASS; **alle** `client3d/scripts/smoke_*.mjs` und `scripts/smoke_*.mjs` (nicht nur die angefassten — eine Smoke, die eine nicht verschobene `client3d/src`-Datei mit esbuild bündelt, sieht jetzt `@anima/hud/…`-Importe, deren Auflösung über Alias/`external` sonst niemand prüft) sowie die Python-Wächter aus Step 0 erneut laufen lassen: die Grün/Rot-Liste muss **identisch** mit der Vorher-Liste aus Step 0 sein (Ausnahme: `smoke_play_shell.py` und die in Step 1 bewusst rot gemachten Prüfungen sind jetzt grün); `./.venv/bin/python scripts/smoke_docs_readme.py` → PASS; `GODOT=… native/test.sh` → `== all native checks passed`.
- [ ] **Step 9: Commit (ein Commit).** `git add -A hud static/hud static/client3d` plus alle geänderten und verschobenen Pfade (alte `client3d/…`-Pfade der `git mv` eingeschlossen, die Wächter und Doku aus Step 6b, `.dockerignore`), `package.json`, `package-lock.json`; Nachricht `refactor(hud): move the React HUD into its own workspace hud/ (static/hud); native CEF loads static/hud/hud.html`; `git commit -- <alle diese Pfade>`.

### Task 7: (aufgegangen in Task 6)

Scanwurzeln der Wächter und Doku-Verweise werden in Task 6 Step 6b im selben Commit wie der Umzug angepasst (Review B3). Die Nummer bleibt frei, damit die Verweise auf Task 8–13 gültig bleiben.

### Task 8: HUD-only-Smokes nach `scripts/`

**Files:**
- Move (`git mv client3d/scripts/X scripts/X`; vorher `test ! -e scripts/X`, bei Kollision Präfix `hud_` vor den Namen): `load_hud_realm.mjs`, `smoke_graphics_prefs.mjs`, `smoke_hud_bridge.mjs`, `smoke_hud_gdcef.mjs`, `smoke_hud_text.mjs` (Helfer: `smoke_hud_bridge.mjs:4` und `smoke_hud_gdcef.mjs:17` importieren ihn relativ), `smoke_hud_text_browser.mjs`, `smoke_photo_view.mjs`, `smoke_prop_action_menu.mjs`, `smoke_readout_reports.mjs`, `smoke_scene_tile.mjs`, `smoke_travel_pick.mjs`, `smoke_voiceover_narrator.mjs`
- Modify: `shared/test-vectors/graphics_prefs.json` (`source`), `shared/test-vectors/README.md` (Tabellenzeile), jede Datei, die eine der verschobenen per Pfad nennt (`command grep -rnaE "client3d/scripts/(load_hud_realm|smoke_(graphics_prefs|hud_bridge|hud_gdcef|hud_text|hud_text_browser|photo_view|prop_action_menu|readout_reports|scene_tile|travel_pick|voiceover_narrator))" .` ohne `node_modules`/`static`), **und** jede in `client3d/scripts` bleibende Datei, die einen verschobenen Helfer relativ importiert (`command grep -rnaE "\./(load_hud_realm|smoke_hud_text)\.mjs" client3d/scripts`): namentlich `client3d/scripts/smoke_prop_action_polling.mjs`, `client3d/scripts/smoke_photo_shot.mjs`, `client3d/scripts/smoke_prop_action_answer_bridge.mjs` — ihr Import wird `../../scripts/load_hud_realm.mjs`.

- [ ] **Step 1:** Jede Datei vor dem Verschieben am alten Ort ausführen und Ergebnis notieren (muss grün sein; sonst Task stoppen und melden).
- [ ] **Step 2:** Verschieben; in jeder Datei die Usage-Zeile auf `node scripts/<name>` und Relativpfade (Repo-Wurzel-Auflösung, Helper-Importe `./load_hud_realm.mjs`, Importe in `client3d/scripts`-Helfer) anpassen. Importiert eine Datei einen Helfer, der in `client3d/scripts` bleibt (z. B. `./embodyVectorDispatch.mjs`), bleibt diese Smoke in `client3d/scripts` und wird aus der Liste gestrichen (im Commit-Text nennen).
  Bewusste Prüfung: `smoke_prop_action_menu.mjs:6` und `smoke_readout_reports.mjs:34` lesen `'../package.json'` — nach dem Umzug ist das die **Wurzel**-`package.json`. Der Implementierer prüft, was die Smoke daraus liest; braucht sie ein Feld, das nur `client3d/package.json` (bzw. `hud/package.json`) hat, wird der Pfad explizit auf `../client3d/package.json` bzw. `../hud/package.json` gesetzt; die Entscheidung kommt in den Commit-Text.
- [ ] **Step 3:** Jede verschobene Datei am neuen Ort: `timeout 300 node scripts/<name>` → grün, gleiche Fall-Anzahl wie Step 1; dazu die drei angepassten Importeure (`timeout 300 node client3d/scripts/smoke_prop_action_polling.mjs`, `…/smoke_photo_shot.mjs`, `…/smoke_prop_action_answer_bridge.mjs`) → grün.
- [ ] **Step 4: Commit** `refactor(hud): HUD smokes live in scripts/` — pfadgenau (alte und neue Pfade).

### Task 9: Wächter `smoke_vector_sources.py`, Klasse A und C, `clip_shift`

**Files:**
- Create: `scripts/smoke_vector_sources.py`
- Create: `native/tests/Derivations/README.md`, `native/tests/Derivations/clip_shift.md`
- Move (`git mv client3d/scripts/X scripts/X`, Klasse A): `smoke_ground_math.mjs`, `smoke_hillshade.mjs`, `smoke_role_turn_vectors.mjs`, `smoke_place_rotation.mjs`, `smoke_scene_primitives.mjs` + Helfer `smoke_plate_hole.mjs`, `smoke_scene_verify.mjs`
- Modify (Klasse C): `scripts/smoke_group_role_points.py`, `scripts/smoke_prop_water.py` (Docstring), `client3d/scripts/smoke_group_role_points.mjs`, `client3d/scripts/smoke_prop_water.mjs` (Zeiger)
- Modify: `shared/test-vectors/{ground_polygons,hillshade,role_turn,scene_place,scene_primitives,scene_verify,group_role_points,prop_water,clip_shift}.json` (nur `source`), `shared/test-vectors/README.md`
- Modify (Verweise auf die Klasse-A-Smokes, Liste per `command grep -rnaE "client3d/scripts/smoke_(ground_math|hillshade|role_turn_vectors|place_rotation|scene_primitives|plate_hole|scene_verify)" . ` ohne `node_modules`/`static`): bekannt sind `native/tests/{GroundPolygon,ScenePrimitives,SceneVerify,ScenePlace,RoleTurn}VectorTests.cs`, `native/Core/Figures/RoleTurn.cs`, `native/README.md`, `packages/scene-render/src/{primitives,hillshade,verify,groundAreas}.ts`, `docs/schnittstellen-3d.md` (dessen Doku-Wächter sonst rot wird). Innerhalb der verschobenen Dateien: `smoke_role_turn_vectors.mjs:58` legt sein Temp-Verzeichnis unter `client3d/scripts/.smoke-role-turn-` an → unter `scripts/.smoke-role-turn-`; `smoke_scene_verify.mjs:55` sucht `client3d/node_modules/esbuild` → Wurzel-`node_modules/esbuild`.

**Interfaces:**
- Produces: `scripts/smoke_vector_sources.py` mit
  - `PIN = "011cd048aa3cc2937186d7f35d2203af9491db8a"`
  - `opening_docstring(text: str) -> str` — überspringt eine Shebang-Zeile, nimmt den ersten `/** … */`- bzw. `/* … */`-Block am Dateianfang, sonst die führende Folge von `//`-Zeilen, bei `.py` den Modul-Docstring.
  - `normalize(text: str) -> str` — entfernt Kommentarmarker (`/**`, `/*`, `*/`, führendes `*`, `//`, `///`, `"""`, `#`) am Zeilenanfang/-ende, streicht **nur** whitespace-getrennte Tokens, die auf `^[\w.@-]+(/[\w.@-]+)+\.(ts|tsx|mjs|js|py|json|cs|md)[,.;:)]*$` passen (Repo-Pfade ändern sich beim Umzug legitim: `client3d/src/game/prefs.ts` → `hud/src/game/prefs.ts`, `client3d/scripts/smoke_x.mjs` → `scripts/smoke_x.mjs`), ersetzt jede Whitespace-Folge durch ein Leerzeichen, trimmt. Divisionen und Einheiten (`(10 + 11) / 2`, `m/s`, `x=side/100*cos(yaw)…`) bleiben damit Teil des Vergleichs. Eingebauter Selbsttest (läuft bei jedem Aufruf vor den Prüfungen): `normalize("a/b m/s client3d/src/game/prefs.ts,") == "a/b m/s"`.
  - `MOVED: dict[str, tuple[str, str]]` — Vektorname → (alte Quelle bei `PIN`, neue Quelle); wächst mit Task 9–12.
  - CLI `--extract <alte-quelle>`: druckt `opening_docstring` der Datei bei `PIN` (`git show PIN:<pfad>`) unverändert, als Werkzeug für Task 10–12.
  - CLI `--verify-move`: führt **nur** Prüfung [V4] aus (einmaliger Umzugsbeweis, läuft in Task 9–12 Step „Prüfen“ und in Task 13; das Ergebnis — Anzahl geprüfter `MOVED`-Einträge, 0 Abweichungen — steht im Commit-Text von Task 13).
  - Prüfungen: [V1] jede `shared/test-vectors/*.json` hat `source` = existierende Repo-Datei; [V2] kein `source` beginnt mit `client3d/`; [V3] die Quelldatei enthält **exakt** `<name>.json` oder `loadVectors('<name>')` (bzw. `loadVectors("<name>")`) — ein bloßer Teilstring wie `water`, `travel`, `enter`, `audio`, `stairs` beweist nichts; [V4] (nur mit `--verify-move`, nicht im Standardlauf) für jeden `MOVED`-Eintrag ist `normalize(opening_docstring(git show PIN:<alt>))` Teilstring von `normalize(<neue Datei>)`; [V5] für jede Klasse-B/C-Altquelle, die noch existiert, enthält ihr `opening_docstring` den Satz `Derivation moved to <neue Quelle>`.
  - Standardlauf (dauerhafter Wächter) = [V1]–[V3] und [V5]; [V4] friert die Herleitungen nicht ein, damit E2–E6 sie legitim korrigieren dürfen.
  - Erwartung im Docstring: 81 Vektordateien; bei `PIN` haben 70 ein `source` unter `client3d/scripts/` und `clip_shift.json` einen Formeltext statt Pfad; Task 8 hat `graphics_prefs` bereits verlegt (sein `MOVED`-Eintrag gehört von Anfang an in die Tabelle); nach Task 12 keine Verletzung.
- [ ] **Step 1:** Wächter schreiben; Lauf → FAIL mit 70 Verletzungen (69 × [V2] = 70 bei `PIN` minus `graphics_prefs` aus Task 8, dazu 1 × [V1] `clip_shift`); diese Zahl im Docstring herleiten.
- [ ] **Step 2: Regel-Text.** `shared/test-vectors/README.md`, Abschnitt „Rules“: `source` ist (a) eine Smoke (JS oder Python), deren Docstring jede Zahl herleitet, oder (b) ein Herleitungsdokument `native/tests/Derivations/<name>.md`, dessen Zahlen die C#-Vektortests ausführen (für Logik, die nach E3 nur noch nativ existiert). Satz zur Verlegung E1 und zum Wächter. `native/tests/Derivations/README.md`: Format eines Dokuments (Kopf: Herkunft `<alte Quelle> @ PIN`, ausführende C#-Datei(en), Vektordateien; danach der wortgetreue Docstring in einem `text`-Codeblock; optional Abschnitt „Inline derivations“ mit weiteren Kommentarblöcken der Smoke, die von Fall-Labels zitierte `[n]`-Marken enthalten, in Dateireihenfolge).
- [ ] **Step 3: `clip_shift`.** `native/tests/Derivations/clip_shift.md` mit dem bisherigen `source`-Text wörtlich als Herleitung, ausführend `native/tests/ClipShiftTests.cs`; `clip_shift.json` → `"source": "native/tests/Derivations/clip_shift.md"`.
- [ ] **Step 4: Klasse A.** Je Datei: am alten Ort laufen lassen (grün, Fallzahl notieren), `git mv`, Pfade anpassen (wie Task 8 Step 2), am neuen Ort laufen lassen (grün, gleiche Fallzahl), `source` umstellen, `MOVED`-Eintrag ergänzen. Zieht eine Datei transitiv ein `client3d/src`-Modul nach (Fehler beim Lauf am neuen Ort oder `command grep -n "client3d/src" <datei>` nicht leer), wird sie zurückverschoben und in Task 10–12 als Klasse B behandelt (die Klassenzuordnung in Task 13 entsprechend nachtragen).
- [ ] **Step 5: Klasse C.** `scripts/smoke_group_role_points.py` und `scripts/smoke_prop_water.py`: Herleitung aus `--extract client3d/scripts/smoke_group_role_points.mjs` bzw. `…/smoke_prop_water.mjs` wortgetreu als Abschnitt „Hand derivation (moved from … @ PIN)“ in den Modul-Docstring; Vorher prüfen, dass die `.py` die Vektordatei tatsächlich liest (`command grep -n "<name>.json\|<name>'" <py>`); liest sie sie nicht, wird der Vektor Klasse B. `source` umstellen; die beiden JS-Smokes bekommen den Zeiger-Docstring (Format in Task 10 Step 3).
- [ ] **Step 6:** `./.venv/bin/python scripts/smoke_vector_sources.py --verify-move` → 0 Abweichungen für die bisherigen `MOVED`-Einträge. Wächter → FAIL nur noch mit den 61 [V2]-Verletzungen der Klasse B (70 − 6 A − 1 `graphics_prefs` [Task 8] − 2 C); jede verschobene/angepasste Smoke grün; `./.venv/bin/python scripts/smoke_group_role_points.py`, `scripts/smoke_prop_water.py` → PASS; `dotnet test native/tests` → PASS (C#-Tests lesen `source` nur für Fehlermeldungen).
- [ ] **Step 7: Commit** `test(vectors): derivation-location guard; package-code smokes move to scripts/` — pfadgenau. Der Wächter ist zu diesem Zeitpunkt bewusst rot (Docstring nennt die Zahl 61 und die Tasks 10–12, die ihn grün machen).

### Tasks 10–12: Klasse-B-Herleitungen nach `native/tests/Derivations/`

Gemeinsames Vorgehen je Quell-Smoke `client3d/scripts/smoke_<basis>.mjs` (ein Dokument pro Smoke, auch wenn sie mehrere Vektoren speist):

1. `./.venv/bin/python scripts/smoke_vector_sources.py --extract client3d/scripts/smoke_<basis>.mjs > /tmp/…` — wortgetreuer Docstring bei `PIN`.
2. `native/tests/Derivations/<basis>.md` nach dem Format aus `native/tests/Derivations/README.md`; ausführende C#-Dateien = die Verbraucher aus der Tabelle unten. Inline-Herleitungen: Kommentarblöcke der Smoke, die eine von den Fall-Labels des Vektors zitierte `[n]`-Marke enthalten (Labels per `python3 -c` aus der JSON lesen), in Dateireihenfolge anhängen.
3. Den Docstring der JS-Smoke ersetzen durch genau:
   `/**\n * Derivation moved to native/tests/Derivations/<basis>.md (E1, 2026-11-25).\n * <ursprüngliche Usage-Zeile(n)>\n * Runs until E3 deletes the browser scene; the C# vector tests keep executing the cases.\n */`
4. `source` jeder gespeisten Vektordatei → `native/tests/Derivations/<basis>.md`; README-Tabellenzeile(n) in `shared/test-vectors/README.md` nachziehen; `MOVED` im Wächter ergänzen; in `shared/test-vectors/smoke_vectors_format.mjs:185` die erwartete `audio.source` (Task 12) anpassen.
5. Prüfen: JS-Smoke läuft unverändert grün (`timeout 300 node client3d/scripts/smoke_<basis>.mjs`), `dotnet test native/tests` grün, `smoke_vector_sources.py --verify-move` ohne Abweichung, Wächter-Verletzungen sinken um genau die Zahl der umgestellten Vektoren.
6. Commit pfadgenau, Nachricht `test(vectors): move <gruppe> derivations to native/tests/Derivations`.

### Task 10: Gruppe Figuren, Brücken, Paare, Clips (18 Smokes, 22 Vektoren)

| Quell-Smoke (`client3d/scripts/`) | Vektoren | C#-Verbraucher (`native/tests/`) |
|---|---|---|
| `smoke_bridge_heading.mjs` | bridge_heading | BridgeVectorTests.cs |
| `smoke_bridge_lift.mjs` | bridge_lift | BridgeVectorTests.cs |
| `smoke_bridge_root.mjs` | bridge_travel | BridgeVectorTests.cs |
| `smoke_foot_lock_math.mjs` | foot_lock | BridgeVectorTests.cs |
| `smoke_foot_lock_measure.mjs` | foot_lock_measure | BridgeVectorTests.cs, BridgeCoreTests.cs |
| `smoke_leg_pin.mjs` | leg_pin | BridgeVectorTests.cs |
| `smoke_stand_settle.mjs` | stand_settle | BridgeVectorTests.cs |
| `smoke_rig_stand_ref.mjs` | hips_tracks | ClipLibraryVectorTests.cs |
| `smoke_clip_order.mjs` | clip_commit | ClipLibraryVectorTests.cs |
| `smoke_clip_coverage.mjs` | clip_coverage | ClipLibraryVectorTests.cs |
| `smoke_figure_clips.mjs` | figure_clips | FigureClipsVectorTests.cs |
| `smoke_figure_normalisation.mjs` | figure_normalisation | PairVectorTests.cs |
| `smoke_pair_blend.mjs` | pair_blend | PairBlendTests.cs |
| `smoke_clip_pair.mjs` | pair_clip_geometry | PairVectorTests.cs |
| `smoke_pair_realtime.mjs` | pair_clip_phase | PairVectorTests.cs |
| `smoke_pair_storey.mjs` | pair_height | PairVectorTests.cs |
| `smoke_secondary_motion.mjs` | secondary_angle, secondary_chain, secondary_params, secondary_particle | SecondaryVectorTests.cs |
| `smoke_animal_vectors.mjs` | animal_gait, animal_legs | AnimalVectorTests.cs |

- [ ] **Step 1–6** wie oben; Wächter danach: 61 − 22 = **39** [V2]-Verletzungen.

### Task 11: Gruppe Laufen, Embody, Reise, Platzierung, Übersicht (15 Smokes, 20 Vektoren)

| Quell-Smoke | Vektoren | C#-Verbraucher |
|---|---|---|
| `smoke_walk_math.mjs` | collide, figure_ground, npc_ground, overview_hud, stairs, walk_control | CollideVectorTests.cs, FigurePlacementVectorTests.cs, NpcWalkVectorTests.cs, OverviewHudVectorTests.cs, BridgeVectorTests.cs, WalkControlVectorTests.cs |
| `smoke_embody_vectors.mjs` | embody | EmbodyVectorTests.cs |
| `smoke_enter_math.mjs` | enter | EnterVectorTests.cs |
| `smoke_npc_placement.mjs` | npc_placement | FigurePlacementVectorTests.cs |
| `smoke_npc_walk.mjs` | npc_walk | NpcWalkVectorTests.cs |
| `smoke_places_client.mjs` | place_poll | FigurePlacementVectorTests.cs |
| `smoke_room_spots.mjs` | room_spots | FigurePlacementVectorTests.cs |
| `smoke_travel_math.mjs` | travel | TravelVectorTests.cs |
| `smoke_prop_action_motion.mjs` | prop_action_motion | PropActionMotionVectorTests.cs |
| `smoke_door_swing.mjs` | door_swing | DoorSwingVectorTests.cs |
| `smoke_event_pins.mjs` | event_pins | OverviewLabelsVectorTests.cs |
| `smoke_overview_labels.mjs` | overview_labels | OverviewLabelsVectorTests.cs |
| `smoke_camera_math.mjs` | camera | CameraVectorTests.cs |
| `smoke_view_shift.mjs` | view_shift | ViewShiftVectorTests.cs |
| `smoke_bench_math.mjs` | bench_math | BenchMathVectorTests.cs |

- [ ] **Step 1–6** wie oben; `overview_hud`-Funktionen, die jetzt in `hud/src` liegen (`boot`, `infoPanel`, `prefs`), ändern nichts an der Klasse (der Vektor mischt sie mit `client3d/src/game/bubble.ts`). Wächter danach: **19**.

### Task 12: Gruppe Gelände, Szene, Licht, Audio (18 Smokes, 19 Vektoren)

| Quell-Smoke | Vektoren | C#-Verbraucher |
|---|---|---|
| `smoke_ambience.mjs` | ambience | AmbienceVectorTests.cs |
| `smoke_audio_math.mjs` | audio | AudioVectorTests.cs |
| `smoke_backdrop_math.mjs` | backdrop | BackdropVectorTests.cs |
| `smoke_fog_veil.mjs` | fog_veil | FogVeilVectorTests.cs |
| `smoke_height_tiles.mjs` | height_tiles | HeightTilesVectorTests.cs |
| `smoke_impostors.mjs` | impostors | ImpostorVectorTests.cs |
| `smoke_layer_cut.mjs` | layer_ground | LayerGroundVectorTests.cs |
| `smoke_light_pool.mjs` | light_pool | LightPoolVectorTests.cs |
| `smoke_occlusion.mjs` | occlusion | OcclusionVectorTests.cs |
| `smoke_scatter_math.mjs` | scatter, scatter_rows | ScatterVectorTests.cs, ScatterRowVectorTests.cs |
| `smoke_scene_models.mjs` | scene_models | SceneModelsVectorTests.cs |
| `smoke_scene_view.mjs` | scene_view | SceneViewVectorTests.cs |
| `smoke_shadow_snap.mjs` | sky_light | SkyLightVectorTests.cs |
| `smoke_terrain_lod.mjs` | terrain_lod | TerrainLodVectorTests.cs |
| `smoke_undergrowth.mjs` | undergrowth | — (Entscheidung 9) |
| `smoke_water_shade.mjs` | water | WaterVectorTests.cs |
| `smoke_world_props.mjs` | world_props | WorldPropVectorTests.cs |
| `smoke_residency_gen.mjs` | residency | ResidencyVectorTests.cs |

- [ ] **Step 1–6** wie oben. Für die sieben E3-Dateien (`terrain_lod`, `height_tiles`, `layer_ground`, `water`, `sky_light`, `backdrop`, `fog_veil`) enthält der Docstring der kanonischen Smoke die gesammelten Begleit-Header (README „E3 terrain…“) — sie gehen wortgetreu mit; der README-Abschnitt „E3 terrain, water and atmosphere“ nennt danach die Dokumente als `source` und behält `client3d/scripts/smoke_e3_vectors.mjs` als Läufer bis E3. Für `undergrowth.md` lautet „ausführend“: „`client3d/scripts/smoke_undergrowth.mjs` bis E3; kein C#-Verbraucher — E3 entscheidet“. `smoke_vectors_format.mjs:185` erwartet `native/tests/Derivations/audio_math.md`. Wächter danach: **0 Verletzungen → PASS**.

### Task 13: E1-Abschluss — Gesamtprüfung und Übergabe

**Files:**
- Modify: `docs/superpowers/specs/2026-11-25-client-ausfuehrung-design.md` nur Abschnitt 9 „Review-Entscheidungen“ (ein Eintrag „E1 umgesetzt“ mit: Klassen A/B/C samt endgültiger Zuordnung, `undergrowth.json` ohne C#-Verbraucher als E3-Punkt (`UndergrowthMath.Shade` ist über `fixtures/scatter_reference.json` in `ScatterCheck` abgedeckt), Workspace `hud/` Port 5184, Typkanten aus Entscheidung 6)

- [ ] **Step 1: Gesamtlauf** (alles muss grün sein):
  - `./.venv/bin/python scripts/smoke_vector_sources.py` und `./.venv/bin/python scripts/smoke_vector_sources.py --verify-move` (Ergebnis notieren)
  - `node shared/test-vectors/smoke_vectors_format.mjs`
  - jede `scripts/smoke_*.mjs` aus Task 8 und 9; jede `client3d/scripts/smoke_*.mjs`, die in Task 10–12 einen Zeiger bekam; `timeout 300 node client3d/scripts/smoke_e3_vectors.mjs`
  - `npm run build -w hud && npm run build -w client3d`, danach `git status --porcelain static/hud static/client3d` leer (Bundles aktuell und committet). Nicht die Wurzel-`npm run build`: sie baut `frontend` mit, und dort liegen fremde, nicht committete Änderungen (`frontend/src/tabs/characters/CharactersTab.tsx`, `frontend/src/styles/game-admin.css`) — das Game-Admin-Bundle gehört nicht in diesen Commit.
  - `GODOT=… native/test.sh` → `== all native checks passed`
  - `STORAGE_DIR=$(mktemp -d) INSTANCE_DIR=$(mktemp -d) ./.venv/bin/python scripts/smoke_play_shell.py`
  - die Doku-Wächter `scripts/smoke_docs_*.py`
- [ ] **Step 2:** Spec-Abschnitt 9 ergänzen; `git add -f docs/superpowers/specs/2026-11-25-client-ausfuehrung-design.md` (gitignoriert, seit Task 5 getrackt); Commit `docs(spec): record E1 outcome` pfadgenau, der Commit-Text nennt das `--verify-move`-Ergebnis (Anzahl `MOVED`-Einträge, 0 Abweichungen).
- [ ] **Step 3 (Orchestrator):** Abnahme E1 an den Nutzer (Deutsch): „Nativer Client mit HUD wie bisher (lädt jetzt `/static/hud/hud.html`); alle Vektor-Smokes grün aus den neuen Orten“ — mit dem Hinweis, dass der Server die neuen Static-Pfade ohne Neustart ausliefert, der native Client aber neu gebaut werden muss (`HudOverlay.HudPath`).

## Review-Entscheidungen

Review vom 2026-11-25 (B1–B3, W1–W7, K1–K8) eingearbeitet. Festlegungen, wo das Review Optionen ließ oder ein Befund nur teilweise zutraf:

- **B3:** Option 1 gewählt — der frühere Task 7 ist in Task 6 aufgegangen (ein Commit, Step 6b). Die Variante „Wächter bis Task 7 rot eintragen“ wurde verworfen, weil auf dem geteilten `main` parallel andere Sessions committen und rote Doku-Wächter deren Prüfläufe stören würden. Die Nummer 7 bleibt als Platzhalter, damit Verweise auf Task 8–13 stimmen.
- **W4:** Spec und Plan werden per `git add -f` in Task 5 Step 2 erstmals committet (statt Ablage unter `development_instructions/`), weil die Baseline-Zahlen und das E1-Ergebnis nachvollziehbar versioniert sein sollen und vier Dateien unter `docs/superpowers/` bereits so getrackt sind.
- **K7:** Geprüft statt nur vertagt: `ScatterCheck.cs:321–325` liest die `shades` aus `fixtures/scatter_reference.json` (Z. 45), nicht aus `shared/test-vectors/undergrowth.json`. Entscheidung 9 bleibt damit richtig; der Befund ist als Präzisierung in Entscheidung 9 und Task 13 eingetragen.
- **W1 Zusatz (`'../package.json'`):** Keine pauschale Umstellung, sondern eine bewusste Prüfung pro Datei in Task 8 Step 2, weil nur der Implementierer sieht, welches Feld gelesen wird.
- **K4:** Die Rate bleibt nach Entscheidung 2 definiert (über die Zeitspanne der Logzeilen); statt sie über die Messdauer zu rechnen, zeigt die Tabelle Rohsumme, Zeitspanne und Messdauer nebeneinander — so bleibt [M2]/[M3] stabil und die Überschätzung ist ablesbar.
- Abgelehnt wurde kein Befund.
