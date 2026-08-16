# Movement-Modell: SetLocation (+ Terrain)

Stand: 2026-06-11, aktualisiert 2026-08-09 (Reise-Engine v2, Meter-Welt).
Ursprünglich festgehalten aus einer Bugfix-Session (ein NPC wollte einer Figur
an die „Küste" folgen, kam aber nie an).

## Der Bewegungs-Skill

Es gibt genau EINEN Bewegungs-Skill. `Move` (ein Grid-Schritt in eine
Himmelsrichtung) ist mit E3 **ersatzlos gelöscht** — die Welt ist seit E1 eine
Meter-Ebene ohne Zellen-Nachbarschaft, in der ein Schritt nichts mehr bedeutet.

| | `SetLocation` (`plugins/movement/skill_set_location.py`) |
|---|---|
| Eingabe | Ortsname (+ optional Raum/Pose) |
| Ziel | benannter, eindeutiger Ort |
| Ablauf (NPC, Cross-Location) | startet eine **zeitgebundene Reise** (`start_journey`, Route über das Nav-Raster) |
| Ablauf (innerhalb des Orts) | sofortiger Raumwechsel |
| Passable Terrain | **abgelehnt** (`skill_set_location.py`: „Durchgangsort, kein Ziel") |
| Default-Verfügbarkeit | an (kein `ALWAYS_LOAD`) |

Dazu kommt `CancelTravel` (dieselbe Datei), der eine laufende Reise abbricht.

`GoToCharacter` (`plugins/movement/skill_go_to_character.py`, Entscheid A10) ist
kein zweiter Bewegungs-Skill, sondern eine Ziel-Auflösung davor: Eingabe ist ein
**Personenname** (exakt, case-insensitiv, keine Vor-/Nachnamen-Auflösung), Ziel
ist deren **tatsächlicher** `current_location`/`current_room` — bei laufender
Reise also die nächste Zelle, nicht das Reiseziel. Gleicher Raum → keine Aktion;
sonst delegiert der Skill an `SetLocationSkill.execute` (ganze Regelkette bleibt).
Eine fremde Location muss in den `known_locations` des Akteurs stehen, sonst
verweigert der Skill mit der Liste der bekannten Orte — er lehrt kein neues
Wissen. Sichtbarkeit wie SetLocation: Party-Follower haben ihn nicht.

Cross-Location-SetLocation ist seit der Reise-Engine (2026-07) keine
Sofort-Teleportation und kein AgentLoop-Schrittmechanismus mehr, sondern eine
**server-autoritative Reise** (`app/core/travel_engine.py`): `start_journey`
legt eine **Polylinie in Welt-Metern** fest (A* über das Nav-Raster,
`app/core/nav_grid.py`, geglättet; Gebäude und unpassierbares Gelände sind
Hindernisse), ein Hintergrund-**TravelTicker** führt die Position auf der
**Spieluhr** nach (eingefrorene Welt = stehende Reise). Das Tempo ist die
Welt-Einstellung `game.travel_speed_m_s` (Admin → Game, Default 1,4 Meter pro
Spiel-Sekunde, geklemmt auf 0,1…20); es wird beim START auf die Reise
geschrieben, laufende Reisen behalten also ihr Tempo. Bei Ankunft greifen
Entry-Room, Auto-Discovery und ein AgentLoop-Bump. `GET /play/worldmap` liefert
die Reise als `travel`-Payload (§ A11 in `docs/schnittstellen-3d.md`).

Der **Wissens-Gate sitzt nur auf dem ZIEL**: `start_journey` verlangt, dass der
Charakter die Ziel-Location kennt (`known_locations`) und dass sie platziert
ist; der WEG dorthin darf über unbekanntes Gelände führen. Reisen gelten für
NPCs wie für den Spieler-Avatar — der Avatar reist allerdings über die
`/play/travel`-Route, nicht über den Skill (`is_player_controlled` überspringt
den Skill-Zweig).

## Terrain: gemalte Flächen und passable Klone

Gelände ist seit E2 primär **gemalte Fläche** (`GET /play/terrain`): ein
Terrain-Typ bringt Passierbarkeit und einen `speed_factor` mit, den das
Nav-Raster als Hindernis bzw. als Zeitgewicht der Route liest. Auf gemaltes
Gelände „geht" niemand — es wird durchquert.

Daneben existieren Geländetypen weiterhin als **Location-Template** (ohne
Position) plus beliebig viele **Klone** auf der Karte. Ein Klon speichert
minimal `id`, `template_location_id`, `pos_x/pos_z` und erbt Name + Rest vom
Template (`_resolve_clones` in `app/models/world.py`). Beim Lesen mergen
`list_locations()` Template und Klone.

Konsequenz: Es gibt typischerweise **mehrere gleichnamige Orte** (z.B. 5×
„Küste"). Eine reine Namens-Suche in der `locations`-Tabelle findet sie nicht —
Klone haben den Namen leer und erben ihn erst beim Merge.

**Wichtig:** Alle Terrain-Klone sind `passable`. SetLocation lehnt passable
grundsätzlich ab → **ein Durchgangsort ist kein Reiseziel.** Wer einen NPC an
ein Geländeziel führen will, legt dort eine richtige Location an; die Route
läuft ohnehin frei über die Fläche, nicht von Kachel zu Kachel.

## Skills pro Character aktivieren

Per-Character-Skill-Config liegt als JSON unter
`<storage>/characters/<name>/skills/<SKILL_ID>.json` mit Inhalt
`{"enabled": true}` (SKILL_ID = Klassenattribut). Die Datei wird pro
Thought-Turn frisch gelesen — kein Server-Restart nötig.

In der UI erledigt das der generische **Skills-Tab** im Game-Admin
(`frontend/src/tabs/characters/SkillsTab.tsx`); er listet auch
`ALWAYS_LOAD`-Skills mit Enable-Toggle (Route
`GET /characters/{c}/skills/available` liefert sie mit `enabled=false`).

Diese Configs sind Runtime-/Welt-Daten und gehören nicht ins Repo
(`worlds/<welt>` ist gitignored außer `worlds/demo`).
