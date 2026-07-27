# Movement-Modell: SetLocation vs. Move (+ Terrain-Tiles)

Stand: 2026-06-11, aktualisiert 2026-07-28 (Reise-Engine). Ursprünglich
festgehalten aus einer Bugfix-Session (NPC Gorvoth wollte einer Figur an die
„Küste" folgen, kam aber nie an).

## Die zwei Bewegungs-Skills

| | `SetLocation` (`plugins/movement/skill_set_location.py`) | `Move` (`plugins/movement/skill_move.py`) |
|---|---|---|
| Eingabe | Ortsname (+ optional Raum/Pose) | Himmelsrichtung: north / east / south / west |
| Ziel | benannter, eindeutiger Ort | orthogonaler Grid-Nachbar (1 Tile) |
| Ablauf (NPC, Cross-Location) | startet eine **zeitgebundene Reise** über bekannte Orte (`start_journey`, Pfad via `find_path_through_known`) | sofort, ein Tile pro Aufruf |
| Passable Terrain | **abgelehnt** (`skill_set_location.py`: „Durchgangsort, kein Ziel") | **erlaubt** — genau dafür gebaut |
| Default-Verfügbarkeit | an (kein `ALWAYS_LOAD`) | **aus** (`ALWAYS_LOAD = True` → per Default deaktiviert) |

Cross-Location-SetLocation ist seit der Reise-Engine (2026-07) keine
Sofort-Teleportation und kein AgentLoop-Schrittmechanismus mehr, sondern eine
**server-autoritative Reise** (`app/core/travel_engine.py`): `start_journey`
legt die Zellenkette über bekannte Orte fest, ein Hintergrund-**TravelTicker**
führt die Position auf der **Spieluhr** nach — aktuell 60 Spiel-Sekunden pro
Zelle (eingefrorene Welt = stehende Reise). Bei Ankunft greifen Entry-Room,
Auto-Discovery und ein AgentLoop-Bump; der `CancelTravel`-Skill bricht eine
laufende Reise ab. `GET /play/worldmap` liefert die Reise als `travel`-Payload
(§ A11 in `docs/schnittstellen-3d.md`). Reisen gelten nur für NPCs; der
Spieler-Avatar bewegt sich weiterhin sofort (Skip via `is_player_controlled`).
`find_path_through_known` traversiert ausschließlich bekannte Orte
(`known_locations`) plus direkte Grid-Nachbarn (Auto-Discovery beim Ankommen).

## Terrain-Tiles sind passable Klone

Geländetypen (Küste, Wald, Meer, Dunkler Wald) existieren als **Template**
(off-grid, ohne Koordinaten) plus beliebig viele **Klone**, die auf Grid-Tiles
gemalt werden. Ein Klon speichert minimal `id`, `template_location_id`,
`grid_x/grid_y` und erbt Name + Rest vom Template (`_resolve_clones`,
`world.py:614`). Beim Lesen mergen `list_locations()` Template und Klone.

Konsequenz: Es gibt typischerweise **mehrere gleichnamige Tiles** (z.B. 5×
„Küste" in Anima-Dome). Eine reine Namens-Suche in der `locations`-Tabelle
findet sie nicht — Klone haben den Namen leer und erben ihn erst beim Merge.

**Wichtig:** Alle Terrain-Klone sind `passable`. SetLocation lehnt passable
grundsätzlich ab → **Terrain-Tiles sind nur über `Move` erreichbar.** Wer einen
NPC an ein Geländeziel (Küste etc.) führen oder folgen lassen will, **muss
`Move` für ihn aktivieren.**

## Move pro Character aktivieren

Per-Character-Skill-Config liegt als JSON unter
`<storage>/characters/<name>/skills/<SKILL_ID>.json` mit Inhalt
`{"enabled": true}` (SKILL_ID = Klassenattribut, für Move `move`). Die Datei
wird pro Thought-Turn frisch gelesen — kein Server-Restart nötig.

In der UI erledigt das der generische **Skills-Tab** im Game-Admin
(`frontend/src/tabs/characters/SkillsTab.tsx`); er listet auch
`ALWAYS_LOAD`-Skills wie Move mit Enable-Toggle (Route
`GET /characters/{c}/skills/available` liefert sie mit `enabled=false`).

Diese Configs sind Runtime-/Welt-Daten und gehören nicht ins Repo
(`worlds/<welt>` ist gitignored außer `worlds/demo`).
