# Bewegungs-Modell: SetLocation, Reisen, Terrain

Wie sich eine Figur in dieser Welt von A nach B bewegt — und was ein Skill dafür
rufen darf. Die aufrufbaren Funktionen stehen mit Signatur in
`docs/skill-core-api.md` → „Reise".

## Die Bewegungs-Verben

Alle drei liegen im Paket `plugins/movement`. `Move` (ein Grid-Schritt in eine
Himmelsrichtung) ist **ersatzlos gelöscht** — die Welt ist eine Meter-Ebene ohne
Zellen-Nachbarschaft, in der ein Schritt nichts mehr bedeutet.

| skill_id | Klasse | Default | Sichtbarkeit |
|---|---|---|---|
| `setlocation` | `SetLocationSkill` (`skill_set_location.py`) | `default_enabled: true` — neue Charaktere haben es | Party-Follower nicht |
| `go_to_character` | `GoToCharacterSkill` (`skill_go_to_character.py`) | `default_enabled: true` | Party-Follower nicht |
| `cancel_travel` | `CancelTravelSkill` (`skill_set_location.py`) | `always_load: true` ⇒ **standardmäßig AUS**, pro Charakter zu aktivieren | alle, auch Follower |

**`SetLocation`** nimmt einen Ortsnamen (+ optional Raum/Pose). Ein Raumwechsel am
aktuellen Ort passiert sofort; ein Ortswechsel startet eine **zeitgebundene Reise**.
Beide Verben tragen `SUPPRESS_IN_PERSON` und `SINGLETON`.

**`GoToCharacter`** ist kein zweiter Bewegungs-Skill, sondern eine Ziel-Auflösung
davor: Eingabe ist ein **Personenname** (exakt, case-insensitiv — keine
Vor-/Nachnamen-Auflösung, Haus-Regel), Ziel ist deren **tatsächlicher**
`current_location`/`current_room`, nicht ihr Reiseziel. Gleicher Raum → keine Aktion;
sonst delegiert der Skill an `SetLocationSkill.execute` (die ganze Regelkette bleibt).
Eine fremde Location muss in den `known_locations` des Akteurs stehen, sonst
verweigert der Skill mit der Liste der bekannten Orte — er lehrt kein neues Wissen.
Ist die Zielperson gerade **im freien Gelände unterwegs**, hat sie keine
`current_location`; dann antwortet der Skill „unbekannt" statt irgendwohin zu laufen.

**`CancelTravel`** bricht eine laufende Reise ab.

`visible_for` (Party-Follower haben kein Bewegungs-Verb) greift auf der
**Laufzeit**-Toolliste. Der Skills-Tab im Game-Admin zeigt das Verb trotzdem an —
Konfigurationsfläche und Laufzeitfläche sind absichtlich zweierlei.

## Eine Reise, kein Sprung

Ein Ortswechsel über Ortsgrenzen ist seit der Reise-Engine eine
**server-autoritative Reise** (`app/core/travel_engine.py`):

- `start_journey(name, target_id)` legt eine **Polylinie in Welt-Metern** fest
  (A* über das Nav-Raster, `app/core/nav_grid.py`, anschließend geglättet; Gebäude und
  unpassierbares Gelände sind Hindernisse). Rückgabe ist `(journey, reason)` mit
  `reason` = `''` (läuft) · `unknown_target` (Ort existiert nicht ODER der Charakter
  kennt ihn nicht) · `unplaced_target` (nicht auf der Karte) · `no_route`.
- `start_journey_to_point(name, x, z)` ist die Variante zu einem freien Punkt. Sie
  setzt **kein** `movement_target`, nur die `journey` — wer Ankunft oder Abbruch
  prüft, muss beides abfragen.
- `journey_state(waypoints, started_at_game, now_game)` ist eine **reine Funktion**:
  die Position folgt aus Polylinie + Startzeit + **Spieluhr**. Deshalb leiten alle
  Clients dieselbe Position aus derselben Payload ab, und eine eingefrorene Welt friert
  jede Reise mit ein.
- Ein Hintergrund-**TravelTicker** (`get_travel_ticker`, im Server-Lifespan) führt
  Ankünfte herbei; der Agent-Loop läuft keine Schritte mehr selbst.
- Wer gerade reist, beantwortet **eine** Query:
  `app.models.character.list_active_journeys()`. Nie über alle Profile iterieren.

Das Tempo ist die Welt-Einstellung `game.travel_speed_m_s` (Admin → Game, Default
**1,4** Meter pro Spiel-Sekunde, geklemmt auf 0,1…20). Es wird beim START auf die
Reise geschrieben — laufende Reisen behalten ihr Tempo.

Bei Ankunft greifen Entry-Room, Auto-Discovery und ein AgentLoop-Bump.
`GET /play/worldmap` liefert die Reise als `travel`-Payload
(`docs/schnittstellen-3d.md` § A11).

Der **Wissens-Gate sitzt nur auf dem ZIEL**: `start_journey` verlangt, dass der
Charakter die Ziel-Location kennt (`known_locations`) und dass sie platziert ist; der
WEG dorthin darf über unbekanntes Gelände führen. Reisen gelten für NPCs wie für den
Spieler-Avatar — der Avatar reist allerdings über `POST /play/travel`, nicht über den
Skill (`is_player_controlled` überspringt den Skill-Zweig).

## Der Marker `**I am at …**` — nur für Figuren ohne Verb

EINE Regel entscheidet, wie eine Figur sich bewegen darf: `_marker_travel_refusal`.
Sie beantwortet dieselbe Frage für den Chat-Prompt, den Tool-Prompt des Streaming-Pfads
und den des Raum-Pfads; ihre Verbraucher sind `app/core/chat_engine.py` und
`app/core/streaming.py`.

| Figur | Weg | Was die Prompts sagen |
|---|---|---|
| hat `SetLocation` | das Verb | „ruf das Tool" — der Marker wird nicht gelehrt und vom Server verworfen |
| hat kein Bewegungs-Verb | der Marker | Raum am aktuellen Ort sofort, ein bekannter Ort startet eine **Reise** (derselbe `start_journey`-Pfad wie das Verb) |
| Party-Follower | keiner | nichts zum Ortswechsel — nur der Leader bewegt die Gruppe |
| vom Spieler gesteuerter Avatar | `/play` | nichts zum Ortswechsel |

Die Prüfung läuft in dieser Reihenfolge: Avatar → Party-Follower → hat ein
Bewegungs-Verb → erlaubt. Wirft sie, gilt `check_failed` und der Marker wird ebenfalls
nicht angeboten.

Wichtig: Der Marker teleportiert NIE. Er startet dieselbe getaktete Reise wie
`SetLocation`, inklusive Wegfindung und Wissens-Gate (ein unbekannter Ort wird
abgelehnt). Ein Raumwechsel am aktuellen Ort bleibt sofort.

Check: `scripts/smoke_marker_travel.py` (alle vier Fälle plus Raumwechsel und
unbekannter Ort), Prompt-Seite in `scripts/test_a32b_tool_prompt.py` § 9.

## Terrain: gemalte Flächen

Gelände ist **gemalte Fläche** (`GET /play/terrain`): ein Terrain-Typ bringt
Passierbarkeit und einen `speed_factor` mit, den das Nav-Raster als Hindernis bzw. als
Zeitgewicht der Route liest (jeder Schritt kostet `Distanz / speed_factor`). Auf
gemaltes Gelände „geht" niemand — es wird durchquert.

Ein **Flächenort** (See, Hof, Dorfplatz) ist dagegen eine ganz normale Location; dass
sie Fläche ist und kein Gebäude, sagt allein `map3d.area_model` (serverseitig
`world_geometry.is_area_location`, im 3D-Client `tiles.isAreaLocation`). Es gibt keinen
zweiten Ortstyp und kein Flag „Durchgangsort" mehr.

**Vorlagen und Klone sind ersatzlos gestrichen**: keine Template-Location, keine Kopien
auf der Karte. `template_location_id` und `passable` werden nirgends mehr gelesen — ein
Datensatz, der sie noch trägt, wird beim Boot gelöscht
(`world.migrate_transit_places_once`, läuft bei jedem Start). Jeder Ort steht genau
einmal in der Welt-Datenhaltung, unter seinem eigenen Namen — eine Namens-Suche findet
ihn also wieder. SetLocation lehnt keinen Ort mehr wegen seines eigenen Flags ab; die
Route läuft ohnehin frei über die Fläche, nicht von Kachel zu Kachel.

## Wer einen Bewegungs-Skill schreibt

- **Nie selbst eine Position schreiben**, um jemanden woanders hin zu bringen. Der
  zentrale Weg ist `save_character_current_location` (löst Entry-Room, Compliance,
  Party-Drag, Flag-Location-Resets und Discovery aus) bzw. `start_journey` für den
  Ortswechsel.
- **Profil-Schreiber sperren.** Jedes Read-Modify-Write auf einem Profil läuft unter
  `keyed_lock("character_profile", name)`, in der dokumentierten Lock-Reihenfolge
  (Plätze vor Profil; zwei Profile nur über `interaction_engine.pair_profile_locks`;
  nie ein Profil-Lock über einen LLM-/HTTP-Call halten). Details und der AST-Check
  `scripts/smoke_profile_rmw_lock.py`: `docs/skill-core-api.md` → „Sperren".
- **Beim Löschen eines Charakters** räumt `delete_character` selbst auf: Party
  verlassen + Einladungen, laufende Reise abbrechen, laufende Paar-Interaktion beenden.
  Wer eigenen Zustand an einem Charakternamen hängt, räumt ihn auf demselben Weg
  (`scripts/smoke_delete_character_detach.py`).

## Skills pro Character aktivieren

Per-Character-Skill-Config liegt als JSON unter
`<welt>/characters/<name>/skills/<SKILL_ID>.json` mit Inhalt `{"enabled": true}`. Der
Dateiname ist die kleingeschriebene `skill_id` (`setlocation.json`,
`go_to_character.json`, `cancel_travel.json`), nicht der Klassenname. Das ist die
bewusste Ausnahme zur DB-only-Regel für Welt-Daten.

Die Datei wird bei **jeder** Skill-Auflösung frisch gelesen — Thought-Turn, Chat-Turn,
Toolliste, Marker-Prüfung — kein Server-Restart nötig.

In der UI erledigt das der generische **Skills-Tab** im Game-Admin
(`frontend/src/tabs/characters/SkillsTab.tsx`); er listet auch `ALWAYS_LOAD`-Skills mit
Enable-Toggle (Route `GET /characters/{c}/skills/available` liefert sie mit
`enabled=false`).

Diese Configs sind Runtime-/Welt-Daten und gehören nicht ins Repo (`worlds/<welt>` ist
gitignored außer `worlds/demo`).
