# Client-Ausführung: Bewegung, Wegfindung und Animationsketten im nativen Client

Datum 2026-11-25 · Status: Entwurf, Entscheidungen des Nutzers vom 2026-11-24/25 und die Review-Runde vom
2026-11-25 eingearbeitet

Kennzeichnung: Was der Nutzer entschieden hat, ist bindend und steht ohne Zusatz oder mit „(Nutzer)“.
Jede Wahl, die dieses Dokument selbst trifft, ist als **Vorschlag (Claude)** markiert. Ein Vorschlag darf
vom Bauenden mit Begründung (Messung, Fakt) geändert werden, eine Nutzerentscheidung nicht.
**Entscheidung (Claude)** markiert eine Frage, die der Nutzer ausdrücklich Claude überlassen hat („entscheide du und
setze es um“, 2026-11-25). Mit demselben Auftrag gelten alle Vorschläge (Claude) dieses Dokuments als angenommen.
Beide sind für den Bauenden verbindlich; geändert werden sie nur mit Messung oder Fakt, eingetragen unter
„Review-Entscheidungen“ (Abschnitt 9).

## 1. Absicht und Warum

Zwei Ziele, gleich gewichtet: **den Server entlasten** und **dem Spiel ein besseres Gefühl geben**.

Alles wird dafür neu gedacht. Frühere Projektentscheidungen wie „der Server rechnet, die Clients stellen dar“,
server-autoritative Anlaufwege, die Server-Clip-Uhr oder das Gate pro Schritt in `/play/pos` sind ausdrücklich
**keine Argumente** mehr. Es zählen nur Fakten, Messungen und Nutzen (Nutzer).

Das Beispiel, an dem sich alles messen lässt: **„Geh zum Bett und leg dich hin.“**

- **NPC heute:** Der Server plant einen Anlauf (`travel_engine.start_approach_journey`). Der TravelTicker
  (`app/core/travel_engine.py:2219ff.`) prüft pro Beat jedes Segment, schreibt die Position in einer
  DB-Transaktion (`_commit_approach_position`) und validiert die Claims (`owner_guard` → `_validate`). Der Client
  führt die Server-Route nach (`JourneyRoute`, `DeadReckoning`, `TravelPath.CatchUpStep`). Jeder Poll
  (`PollScheduler`, Worldmap alle 3 s) kann über `ApplyPlan` (`FigureManager.cs:441`), `TickPlacement` (`:636`)
  und `AdoptPropEntry` (`FigureManager.PropActions.cs:50`, Aufruf `FigureManager.cs:451`) die laufende Kette neu
  setzen. Ergebnis: Die Kette Aufstehen → Gehen → Einstieg →
  Liegen bricht sichtbar an Poll-Grenzen, springt oder beginnt neu.
- **Avatar heute:** Der Klick dreht die Figur nur (`PreviewPropTarget`, `AvatarOffersController.PropActions.cs:107`).
  Gelaufen wird erst nach `MotionReceived` (`:116`), also nach Reservierung, Planung und Antwort des Servers:
  **0,7–3 s Stillstand vor dem ersten Schritt.**
- **Server heute:** Pro Anlauf 2–6 Beats mit Geometrie-Abfrage, Prop-Dokumenten, Segmentprüfung, zwei
  Profil-Lesezugriffen, einer Transaktion und einem `_validate`, je Figur. Dazu `/play/pos`: Der Client
  meldet alle 330 ms (`PositionChannel.ReportMs`, rund 3 pro Sekunde), der Server nimmt bis zu 4 pro Sekunde an
  (`_POS_REPORT_INTERVAL_S = 0.25`, `play.py:814`); jede Meldung kostet rund einem Dutzend
  DB-Lesezugriffen (Gelände-Gate, zweimal `stand_height_at`, Location-Auflösung …).

Nach dem Umbau entscheidet der Server **was** passiert und **wann der Spielzustand kippt**. Der Client entscheidet
**wie** es aussieht und spielt die ganze Kette auf seiner eigenen Uhr, ohne dass ein Poll sie unterbricht.

## 2. Ziele, Nicht-Ziele, Anti-Ziele

### Ziele

- **Bewegung, Wegfindung, Kollision beim Gehen und ganze Animationsketten laufen im Client** auf dessen Uhr
  (Nutzer): Aufstehen → Gehen → Übergangsclip → Loop, ohne Unterbrechung durch Polls.
- **NPC:** Der Server sendet **einen** Auftrag beim Start (Ziel, Slot, Phasenfolge, geschätzte Dauer). Der Client
  spielt die Kette mit eigener Wegfindung und Kollision. Der Server kippt den Spielzustand („liegt im Bett“) nach
  der **geschätzten** Dauer. Bild und Zustand dürfen ~1–2 s auseinanderliegen (Nutzer).
- **Avatar:** Loslaufen **sofort** beim Klick (optimistisch), Reservierung im Hintergrund, bei Ablehnung bleibt
  die Figur stehen bzw. wendet sich ab. Der Avatar meldet „angekommen“, der Server prüft nur Plausibilität
  (Nutzer).
- **Freies Laufen** meldet die Position nur bei Halt, Raumwechsel, Aktionsstart und höchstens alle 2 s beim
  Laufen (statt alle 330 ms). Der Server braucht die Position nur für Sichtbarkeit und Raumzugehörigkeit (Nutzer).
- **Überland:** grobe Server-Route pro Reise, Verfeinerung durch den Client in Spielernähe (Nutzer).
- **Paar- und Gruppenanimationen:** alle Beteiligten im selben Client, client-seitig (Nutzer).
- **Ein Auftrags-Abspieler** führt jede Kette auf der Client-Uhr für **alle** Figuren aus, als Verallgemeinerung
  von `FigureManager.OwnPropMotion.cs` (Nutzer).
- Messbar weniger Server-CPU und weniger Requests (Abschnitt 7).

### Nicht-Ziele

- Der Browser-Client `client3d/` bekommt nichts davon. Er wird abgeschaltet, sobald der native Client es kann
  (Nutzer). **Entscheidung (Claude): kein Doppelbetrieb.** Ab der Etappe, in der der Server die Anläufe von NPC und
  Avatar auf Aufträge umstellt (E3), ist die Browser-3D-Szene nicht mehr unterstützt und wird in derselben Etappe
  gelöscht; der alte Server-Anlaufweg ebenso, er bleibt nicht bis zum Ende stehen. Der HUD zieht **vorher** (E1) in
  einen eigenen Workspace, damit der CEF-HUD des nativen Clients weiterläuft.
- Game-Admin und Server-Admin bleiben unverändert (Nutzer). Die Admin-Grundrissvorschau (`packages/scene-render`)
  bleibt, wie sie ist.
- Bildsynchronität zwischen mehreren Clients. Jeder spielt den Auftrag selbst, kleine Abweichungen sind akzeptiert
  (Nutzer).
- Physik-Simulation von Props (Umstoßen, Schieben). Kollision dient nur dem Gehen.
- Eine Änderung an der WAS-Entscheidung (LLM, `prop_action_engine.request`, Einwilligung, Claims, Effekte).

### Anti-Ziele

- **Eine Kette, die noch an einem Poll hängt.** Kein Poll, kein Push und keine Worldmap-Zeile darf eine laufende
  Kette neu setzen, zurückspulen oder neu starten. Unterbrechen dürfen nur ein **neuer Auftrag** (neue
  `order_id`) für dieselbe Figur oder eine **Ablehnung**. Eine höhere `revision` desselben Auftrags ändert ihn an Ort
  und Stelle und spult nie zurück (5b).
- **Serverarbeit, die wächst.** Keine neue Arbeit pro Beat oder pro Frame auf dem Server. Was der Server pro
  laufendem Auftrag noch tut, ist ein Zeitvergleich.
- **Zwei Implementierungen (TypeScript und C#).** Die neue Logik entsteht nur in `native/`. Was heute nur in
  `client3d/` liegt (z. B. `bridgeLift.ts`, `bridgeHeading.ts`), wird nicht parallel gepflegt.
- Ein stilles Auseinanderlaufen, das nie heilt: Wo Bild und Zustand auseinanderlaufen, gibt es eine feste Regel,
  wann das Bild dem Zustand nachgibt (Abschnitt 5c, 6).

## 3. Randbedingungen

- **Nur der native Client** (`native/`, Godot 4.7.2 mono, .NET 8; `native/project.godot`, `AnimaNative.csproj`).
- **`native/Core` bleibt Godot-frei**, geprüft durch `native/tests/CoreIsGodotFreeTests.cs`. Logik dort wird mit
  xUnit (`native/tests`) und, wo Server und Client dieselbe Zahl brauchen, gegen `shared/test-vectors/*.json`
  geprüft. Erwartungswerte werden **von Hand aus der Spezifikation hergeleitet**, im Docstring bzw. in
  `native/fixtures/README.md`, nie als Schnappschuss der aktuellen Ausgabe.
- **Headless prüfbar:** `native/test.sh` (Verträge, `dotnet test`, `dotnet build`, `godot --headless -- --check`).
  Neue Funktionen bekommen einen Check in `native/Check/` gegen eine Fixture in `native/fixtures/`.
  NavigationServer3D läuft auch headless; ob der Dummy-Renderer Mesh-Arrays liefert, ist **nicht** verifiziert,
  deshalb kommt die Navmesh-Quelle nicht aus gerenderten Meshes (5d).
- Game-Admin unverändert. Server-Admin-Seiten unverändert.
- **Wenige Clients, meist einer.** Null Clients muss funktionieren (die Welt läuft weiter), mehrere ebenfalls.
- Der Nutzer startet, lädt neu und testet selbst. Bauen und Committen ist die Lieferung.
- Server-Regeln des Projekts gelten weiter: zwei Uhren (`motion_time()` für Bewegung, `game_time()` für
  Spielzustand), Push nur über `sync_topics.notify` mit Empfänger und ohne Daten, Profil-RMW nur unter
  `keyed_lock("character_profile", name)`, keine Rückwärtskompatibilitäts-Aliase bei Umbenennungen.
- Physik-Backend: In `project.godot` ist weder `physics/` noch `navigation/` gesetzt. Jolt ist seit Godot 4.4
  eingebaut. Die erste Stufe nutzt keinen Physik-Körper (5d), der Punkt ist deshalb gegenstandslos. Erst wenn ein
  `CharacterBody3D` kommt, wird das Backend (Jolt) ausdrücklich eingetragen und im Check abgefragt.

## 4. Ansätze

### A — Godot-Navigation + Physik (vom Nutzer gewählt)

NavigationServer3D mit Navmesh-Baking zur Laufzeit aus der Szene, die der Client ohnehin baut; RVO-Avoidance;
Physik-Körper für Kollision.

- \+ Fertige, gepflegte Pfadsuche (Recast/Detour), Links für Treppen und Aufzug, Avoidance zwischen Figuren.
- \+ Asynchrones Backen außerhalb des Main-Threads (`BakeFromSourceGeometryDataAsync`).
- \+ Kein eigener Pfadsucher, den man testen und pflegen muss.
- − Nicht deterministisch (RVO hängt von der Frame-Reihenfolge ab) — akzeptiert, jeder Client spielt selbst.
- − Engine-Abhängigkeit, die in `native/Core` nicht vorkommen darf: Die Pfadsuche liegt hinter einer
  Schnittstelle (`IPathProvider`), Core testet mit einer Fake-Implementierung.
- − Fallstricke beim Backen (Zellgröße, Map-Synchronisierung, stille Link-Deaktivierung), siehe 5d.

### B — eigene Wegfindung in `native/Core`

Sichtbarkeitsgraph oder Gitter-A* in reinem C#, wie der Server es mit `prop_action_paths.visibility_path` tut.

- \+ Deterministisch, voll mit xUnit und Vektoren prüfbar, Server und Client könnten denselben Algorithmus haben.
- − Avoidance, Links, dynamische Hindernisse alles selbst bauen. Viel eigener Code für etwas, das die Engine hat.
- − Genau die Doppelung, die bisher Drift erzeugt hat (Server-Pfad gegen Client-Nachführung).

### C — Server backt das Navmesh

Server erzeugt das Navmesh pro Location und liefert es im Szenen-Payload aus.

- \+ Ein Navmesh für alle Clients und für die Server-Schätzung.
- − Widerspricht dem Ziel Nummer eins: **mehr** Serverarbeit, größere Payloads, ein neuer Cache mit
  Generationsschlüssel.
- − Recast in Python ist eine neue native Abhängigkeit.

### Wahl

**A** (Nutzer). Begründung in Fakten: Es ist der einzige Ansatz, der Serverarbeit wegnimmt **und** fertige
Avoidance und Links bringt; die Kosten des Nicht-Determinismus sind durch die Nutzerentscheidung „jeder Client
spielt selbst“ bereits akzeptiert. Der Server behält seine billige Pfadsuche (`prop_action_paths.visibility_path`,
`plan_approach`) **nur** für Dauerschätzung und Plausibilitätsprüfung.

## 5. Der Entwurf

### 5a. Rollen nach dem Umbau

| | Server | Client (nativ) |
|---|---|---|
| Entscheidung | WAS: Aktion, Möbel, Slot, Partner, Einwilligung, Claims | — |
| Reservierung | Slot-Belegung (`places.assign`/`occupancy`/`can_take`) bleibt Spielzustand | optimistisch losgehen, Ablehnung umsetzen |
| Weg | Weglänge im Raum für die Schätzung; grobe Route draußen und über Land | Navmesh-Pfad, Avoidance, Kollision, Türen, Treppen, Aufzug |
| Animation | semantische **Phasen** im Auftrag (Ausstieg, Gehen, Einstiegsart/Pose, Loop-Pose); nominelle Katalogdauern nur für die Schätzung | Wahl der konkreten Ausstiegs-, Brücken- und Einstiegsclips; Abspielen, FootLock, Hebung, Drehung |
| Uhr | Zustand kippt nach `eta`/`flip` auf der Motion-Uhr | eigene Uhr pro Auftrag, ab Start nie nachgestellt |
| Position | Wahrheit für den Spielzustand (Sichtbarkeit, Raum, Regeln) | Wahrheit fürs Bild; meldet selten |
| Prüfung | Plausibilität (Distanz, Raum, Slot frei, Regeln) | — |

Der Satz „`pos` ist die Wahrheit“ (Vertrag A1.4) bleibt für den Spielzustand, gilt aber nicht mehr fürs Bild.

### 5b. Der eine Auftrag

Ein Auftrag (`order`) ersetzt für den nativen Client `motion_for`/`_motion_snapshot`
(`prop_action_engine.py:992–1050`), den Anlauf-Teil von `travel` in der Worldmap-Zeile, `local_approach`,
`prop_action_entry` und die Server-Clip-Uhr von Paar und Finale. Er gilt für **alle** Figuren, nicht nur für den
eigenen Teilnehmer (heute `:1042`).

Felder (Vorschlag (Claude), Ausgangspunkt der heutige `motion`-Snapshot):

| Feld | Inhalt |
|---|---|
| `order_id` | `prop_action`: `execution_id` des durablen Runs · `pair` aus `interaction_engine`: Interaktions- bzw. Invite-Id · `walk`: neue Id, im Profil beim Auftrag gespeichert · `travel`: Journey-Id · `cancel`: neue Id |
| `revision` | steigt bei jeder Änderung **dieses** Auftrags; Semantik siehe unten |
| `kind` | `prop_action` · `walk` · `pair` · `travel` · `cancel` (Definitionen unten) |
| `issued_motion_s` | Startzeit auf der Motion-Uhr (`timeutils.motion_time()`) |
| `eta_motion_s` | geschätzte Ankunft am Zugang bzw. Ziel (Ende `walk`) |
| `flip_motion_s` | geschätzter Zustandswechsel (Ende Einstieg); fehlt, solange `awaits` gesetzt ist |
| `deadline_motion_s` | spätester Abbruchzeitpunkt des Servers |
| `status` | `approaching` · `waiting` · `entering` · `active` · `ended` (der Run-Zustand, nur informativ für den Client) |
| `awaits` | leer oder `reaction` (der Partner muss erst per LLM reagieren) bzw. `grant` (Avatar: Zusage fehlt) |
| `gait`, `speed_m_s` | Gangart und Tempo; `speed_m_s` ist für `walk` **bindend** (5d, Avoidance) |
| `tempo` | nur `pair`: Clip-Tempo 0,2–1 (`pose_scene.py:16–31`); eine Änderung kommt als Revision |
| `actors[]` | `name`, `role`, `clip_role`, `height_cm`, `start` {x, y, z, yaw, room_id, level} |
| `target` | `location_id`, `room_id`, `level`, `floor_y`, `placement_id`, `marker_id`, `place_id`, `slot`; bei `walk` nur Ort, Raum, Ebene und Punkt |
| `access` | {x, y, z, yaw} — Zugangspunkt auf dem Boden (Ziel der Wegfindung) |
| `anchor` | {x, y, z, yaw, `root_offset`} — Slot auf dem Möbel |
| `entry_mode` | `bridge` · `direct` |
| `sequence[]` | semantische Phasen {`step`: `exit` · `walk` · `entry` · `loop` · `phase` · `finale`; `pose_kind`; `pose_key`; `nominal_s`} |
| `hint_route` | grobe Wegpunkte des Servers (Pflicht bei `travel` und bei `walk` draußen, sonst leer) |
| `travel` | nur `kind=travel`: `target_location_id`, Route, Journey-Felder wie heute (`journey_state` bleibt reine Funktion) |
| `pair` | nur `pair`: `anchor`, `partner_roles`, `role_points`, `pair_yaw`, `phase_index`, `finale` |
| `stand` | nur `cancel`: {x, y, z, yaw} — wohin der Ausstieg führt (heute `_exit_motion` `:1411–1422`: `stand`, `stand_yaw_deg`) |

**Phasen statt Clips — Entscheidung (Claude).** Der Auftrag nennt keine konkreten Brücken-, Ausstiegs- oder
Einstiegsclips. Er nennt die Phase und ihre Art: `exit` (aus welcher Pose-Art, ggf. welcher Sitz), `walk`,
`entry` (Pose-Art und `entry_mode`), `loop` (`pose_key`). Die konkreten Clips wählt der **Client**, weil nur er
das Modell, dessen Rig und die geladenen Clips kennt. Der Server schätzt mit den **nominellen** Dauern des
Clip-Katalogs (`nominal_s`). Weicht die echte Clipdauer davon ab, ist das akzeptiert; es fällt unter dieselbe
1–2-s-Abweichung wie der Weg.

Die Phasen für „zum Bett, hinlegen“ eines sitzenden NPCs, als Beispiel:
`exit(pose_kind=seat, 1.2 s) → walk → entry(pose_kind=lie, bridge, 2.4 s) → loop(lie_idle)`.

**Auftragsarten** (Entscheidung (Claude); `sleep`, `follow` und `group` aus dem ersten Entwurf entfallen als eigene
Arten):

- `prop_action`: ein Möbel-Slot, wie heute der durable Run. Ins Bett gehen (`take_bed_to_sleep`) ist ein
  `prop_action` mit Loop-Pose Liegen. Ein Platzwechsel am selben Möbel (`_switches_in_place`/`_settle_in_place`)
  ist ein `prop_action` ohne `walk`: `exit` (falls die Pose-Art wechselt) → `entry` → `loop`,
  `flip = issued + Σ nominal_s`. Eine Folge-Pose nach Run-Ende (`_follow_targets`, `prop_action_engine.py:1300`)
  ist ein neuer Auftrag mit neuer `order_id`.
- `walk` (neu, Nutzerauftrag zu offener Frage 2): Bewegung ohne Möbel und ohne Überlandreise — Raumwechsel
  innerhalb einer Location, Gang zu einem Punkt, Herumschlendern (`npc_actions.py:824`, `npc_home`). Dieselbe
  Schätzung und derselbe Timer-Flip wie bei Möbel-Anläufen (5g). Phasen `exit` (falls die Figur sitzt) → `walk` →
  `loop` (Ruhepose).
- `pair`: zwei **oder mehr** Beteiligte (Gruppen sind Paare mit mehr Rollen); beide Paar-Systeme (5i).
- `travel`: Überland (5h).
- `cancel`: Abbruch ohne Folgeauftrag. Phasen `exit` (aus der aktuellen Pose-Art) → Stand auf `stand` → Ruhepose.
  Der Client spielt den Ausstieg **aus seinem aktuellen Bildzustand**, nicht aus dem des Servers.

**Revision — Entscheidung (Claude), zwei getrennte Fälle:**

1. **Neue `order_id`** für dieselbe Figur ersetzt die laufende Kette. Der Client führt sie aus dem aktuellen
   Bildzustand fort: aus `walk` direkt ein neuer Pfad, aus `entry`/`loop` zuerst ein Ausstieg.
2. **Dieselbe `order_id` mit höherer `revision`** ist eine Änderung an Ort und Stelle und spult nie zurück:
   Statuswechsel (z. B. nach `active`), Wegfall von `awaits` mit gesetztem `flip`, angehängte Schritte, neue
   `phase`/`finale`, `tempo`, Zielkorrektur (nur das Wegziel wird ersetzt). Eine Revision, die nur den Status
   ändert, lässt das Bild unverändert.

Phasenwechsel bei `combined` (läuft auf der Spielzeit, `duration_game_s`, `:2156–2166`), das Finale (ein Paket
startet es mitten in der Szene, `pose_scene.begin_finale`) und Tempoänderungen kommen deshalb als Revision vom
Server. Der Client taktet sie nie selbst nach einer Dauer: Die Spieluhr mit ihrem Faktor gehört nicht in die lokale
Kettenuhr.

**Wann gesendet:** beim Start, danach nur bei echter Änderung (Fall 1 oder 2). Nie pro Beat.

**Transportweg — Entscheidung, Vorschlag (Claude):** Feld **und** Push-Signal, kein eigener Datenkanal.

1. Der aktuelle Auftrag einer Figur steht als Feld `order` in ihrer Charakter-Zeile der Worldmap
   (`world_ops`-Zeilen). So bekommt ein Client, der später kommt oder neu startet, alle laufenden Aufträge mit dem
   nächsten Poll, ohne Sonderweg.
2. Bei Start, Abbruch und jeder Revision sendet der Server ein Signal `order_changed` über
   `sync_topics.notify` an die Empfänger, die die Figur sehen (Projektregel: Empfänger, keine Daten, nie
   `Everyone` für Spielaktivität). `order_changed` ist ein **neues** Topic; `travel_changed` bleibt für Überland
   (Entscheidung (Claude)). Der Client holt daraufhin sofort `GET /play/orders?since=<rev>` — ein schlanker
   Endpunkt, der nur die Aufträge mit höherer Revision liefert, nicht die ganze Worldmap.
3. Der **eigene** Avatar-Auftrag kommt direkt in der Antwort auf seine Reservierung (5e).

`motion_now` ist ein **neues** Feld in der Worldmap-Wurzel und in der `/play/orders`-Antwort; `world_ops` kennt
es heute nicht.

Begründung: Ein eigener Endpunkt allein ließe späte Clients ohne Auftrag; die Worldmap-Zeile allein hätte bis zu
3–6 s Latenz (Poll-Takt `PollScheduler.cs:32`). Beides zusammen braucht keine neue Push-Art mit Daten.
`/play/orders` liest nur, was der Run ohnehin persistiert; keine neue Berechnung.

**Bewegungsfälle** (Entscheidung (Claude)) — jeder Fall, in dem sich heute eine Figur bewegt:

| Bewegungsfall | Auftragsart oder Regel |
|---|---|
| NPC oder Avatar nimmt ein Möbel im **eigenen** Raum | `prop_action` (5e, 5g) |
| NPC geht ins Bett | `prop_action`, Loop-Pose Liegen |
| Platzwechsel am selben Möbel | `prop_action` ohne `walk` |
| Möbel in einem **anderen** Raum | erst `walk` in den Raum, danach ein eigener `prop_action` (Aufträge sind raumgebunden, 5g) |
| NPC wechselt den Raum innerhalb der Location | `walk`; der Client plant den Weg im Navmesh, `NpcRoute.Plan` (`CharacterRows.cs:364`) entfällt |
| NPC geht zu einem Punkt / schlendert (`npc_actions`, `npc_home`) | `walk`; draußen mit `hint_route` aus dem heutigen Punkt-Bake |
| Freies Paar (`interaction_engine._walk_to_partner`) | `pair`, `order_id` = Invite-Id (5i) |
| Paar/Gruppe am Möbel | `pair` |
| Überlandreise | `travel` |
| Party-Follower | **kein** Auftrag: der Client stellt Follower lokal hinter der Leiterfigur dar (5h) |
| Abbruch durch Server, Teleport, Deadline | `cancel` bzw. neue `order_id` |
| Fremder Avatar eines anderen Spielers | kein Auftrag beim freien Laufen: Interpolation der Meldungen (5j) |
| Tiere | wie Menschen; gemeinsames Navmesh mit `agent_radius` 0,25, Avoidance-Radius aus dem Footprint (5d) |

### 5c. Der Auftrags-Abspieler (`OrderPlayer`)

**Ort:** Zustandsautomat in `native/Core/Orders/OrderPlayer.cs` (Godot-frei), Godot-Brücke in
`native/Figures/FigureManager.Orders.cs` (beides Vorschlag (Claude)). Er ersetzt `FigureManager.OwnPropMotion.cs`
(heute nur Avatar, `OwnPropPlayback` :11, `TickOwnPropMotion` ab :176) und gilt für jede Figur mit Auftrag.

**Zustände** (Verallgemeinerung von `departure → walking → entry → arrived` plus `frozen`):

```
idle ──order──► exit (Ausstieg) ──► walk (Navmesh-Pfad) ──► wait_access ──► entry (Einstieg / Brücke)
                                                                 │                 │
                                                                 └─ awaits gesetzt (Avatar-Zusage, Reaktion,
                                                                    Partner noch nicht da)
                                                                                   ▼
                                                            loop / phase / finale ──► (nächster Auftrag)
jeder Zustand ──refuse / cancel / neue order_id──► abort (Ausstieg aus dem Bildzustand, stehen, Ruhepose) ──► idle
jeder Zustand ──gleiche order_id, höhere revision──► derselbe Zustand, Felder an Ort und Stelle übernommen
jeder Zustand ──world_frozen──► frozen (Uhr hält) ──unfreeze──► vorheriger Zustand
```

- `wait_access`: Die Figur steht am `access` und schaut zum Möbel bzw. Anker. Gilt für **jede** Figur, deren Auftrag
  `awaits` trägt: der Avatar ohne Zusage, ein NPC, dessen React-Run auf die LLM-Reaktion des Partners wartet
  (heute auf der Systemuhr bis `REACTION_WAIT_S`, `prop_action_engine.py:2115–2120, 2203–2209, 2379–2391`), und
  jeder Paar-Beteiligte, dessen Partner noch läuft. Es endet mit der Revision, die `awaits` löscht und `flip`
  setzt, oder mit einem Abbruch.
- `walk` endet, wenn die Figur innerhalb der Toleranz am `access` steht (Vorschlag (Claude): 0,15 m; den Yaw
  richtet die Entry-Brücke aus), nicht nach `eta`. Der Client folgt seinem Weg, nicht der Schätzung. Das letzte
  Stück zum `access` ist ein gerades Schlussstück (5d).
- `entry` spielt die Brücke mit Hüftspur, Turn und Lift über die vorhandenen Bausteine: `PlayPropEntry`
  (`Figure.PropActions.cs:21`), `PlayOwnPropDeparture` (`:69`), `FinishPropEntry` (`:118`), `HoldClipAt`
  (`Figure.cs:806`), `PlayPair`; Mathematik aus `Core/Bridges.cs`, `FinaleClip.cs`, `PairClip.cs` (`AnchorPoint`,
  `StandY`). Welche Brücke, welcher Ausstiegs- und welcher Einstiegsclip, entscheidet der Abspieler aus Pose-Art,
  `entry_mode` und dem geladenen Modell (5b, Phasen statt Clips). `PropActionMotion.SampleMotion` verliert das
  Wegstück und behält `HandBackYaw`, `EntrySupportLift`, `EntryPhase`.

**Uhr:** Jeder Auftrag hat eine lokale Uhr `t = clientClock − startedAtClient`. Sie wird **einmal** beim Annehmen
gesetzt und danach nie nachgestellt (Anti-Ziel). Beim Annehmen rechnet der Client den Rückstand
`lag = motion_now − issued_motion_s` aus (Worldmap- und `/play/orders`-Antwort tragen `motion_now`). Regel,
Vorschlag (Claude):

- `lag ≤ 2 s`: Kette normal von vorn spielen; die Abweichung liegt im akzeptierten Fenster.
- `2 s < lag < flip − issued`: **Einstieg mitten in der Kette.** Der Client plant seinen eigenen Weg und setzt die
  Figur an die Stelle `max(lag − exit_s, 0) · speed_m_s` entlang dieses Wegs bzw. an die passende Stelle im
  Einstiegsclip (Seek **einmal**, beim Annehmen).
- `lag ≥ flip − issued` bzw. `status = active`: Endzustand direkt zeigen (Loop auf dem Slot), ohne Lauf.

Diese Regel gilt für spät kommende Clients und nach einem Client-Neustart. Ein Poll, der denselben Auftrag
(gleiche `order_id` und `revision`) wiederholt, ist ein No-op. Eine höhere Revision desselben Auftrags setzt die
lokale Uhr **nicht** neu.

**`phase`, `finale` und `tempo`** laufen nicht auf einer client-getakteten Dauer. Der Client spielt die aktuelle
Phase im Loop, bis eine Revision die nächste Phase, das Finale oder ein neues Tempo bringt; dann wechselt er mit
einer Überblendung, ohne die Kette neu zu starten. Das Ende nach dem Finale meldet ebenfalls der Server (Revision
mit `status = ended` oder neue `order_id`).

**Was unterbricht:**

1. Ein Auftrag mit **neuer `order_id`** für dieselbe Figur (neue LLM-Entscheidung, `cancel`, Teleport, Deadline).
2. Eine Ablehnung (`refused`) auf die Reservierung oder das `arrived` des Avatars.
3. `world_frozen` hält nur an, unterbricht nicht.

Nichts anderes. Eine höhere `revision` derselben `order_id` unterbricht nicht (5b). Insbesondere setzt `ApplyPlan`
(`FigureManager.cs:441`) eine Figur mit laufendem Auftrag nicht mehr um; `NpcPlacement`, `RoomSpots` und
`FigureStands` bestimmen nur die Ruheposition **ohne** Auftrag und liefern weiter die Höhen.

**Ende der Kette und Zustand — Heilregeln** (Vorschlag (Claude)):

1. Erreicht der Client `loop` vor `flip_motion_s`, bleibt er im Loop; erreicht der Server `flip` zuerst, ändert
   sich am Bild nichts.
2. Ist der Zustand gekippt („liegt im Bett“), das Bild aber bei `flip + 5 s` noch nicht im Einstieg (Figur steckt
   fest), gibt das Bild nach: kurze Überblendung auf den Slot, dann Loop.
3. Beendet der Server den Auftrag, während das Bild noch im `walk` oder `entry` ist (z. B. `_validate` schlägt nach
   `flip` fehl), kommt das als neue `order_id` (`cancel` oder Folgeauftrag); der Client spielt den Ausstieg aus
   seinem **aktuellen** Bildzustand, nicht aus dem, den der Server annimmt.
4. Paar-Start: Steht ein Beteiligter bei `max(eta_i) + 5 s` noch nicht am `access`, wird er auf den `access`
   übergeblendet und der gemeinsame Clip startet (5i).

Alle Heilregeln laufen im Client, nicht als Poll-Snap. Den Fall „kein Client schaut“ deckt der Server allein
über seine Timer ab (5j); dort gibt es kein Bild, das heilen müsste.

### 5d. Navigation und Kollision im Client

**Quellgeometrie prozedural aus Core** (Vorschlag (Claude), gestützt auf die Godot-Docs): Eine Godot-freie Funktion
`native/Core/Nav/NavSource.cs` baut aus dem ScenePayload Dreiecke, Hindernisse und Links:

- begehbare Fläche: `ScenePlate` (`Payloads.cs:303`, Umriss mit Löchern) pro Stockwerk; Ebene 0 ohne Platte nimmt
  den Geländeausschnitt der Location;
- Wände: `SceneWall` (`:313`) bzw. `Collide.WallSegments`, extrudiert; Öffnungen (`Openings` :341,
  `SceneDoorway`, `BoundaryOpenings`) bleiben Lücken wie heute (`Collide.cs:24`), Glas sperrt;
- Props: Grundflächen als Boxen aus `RoomPropBoxes` (`WorldBuilder.Stands.cs:131`). Ziel der Wegfindung ist
  immer der `access` am Boden neben dem Möbel. Der Server prüft den Zugang in `access_space` mit ausgenommenem
  Zielmöbel und `ACCESS_BODY_R_M = 0.15` für die übrigen Möbel (`prop_action_paths.py:330–335`,
  `room_stand.py:62–63`); das Navmesh erodiert dagegen **alle** Boxen um 0,25 m, auch das Zielmöbel. Der `access`
  liegt deshalb oft außerhalb des Navmeshs. Regel (Vorschlag (Claude)): `QueryPath` bis
  `MapGetClosestPoint(access)`, danach ein **gerades Schlussstück** bis `access`. Diese Sichtlinie hat der Server
  bereits geprüft (`_entry_spec`, `prop_action_engine.py:1826`). Der `NavCheck` prüft für jede Fixture, dass der
  Abstand `access` → nächster Navmesh-Punkt kleiner als 0,4 m ist und das Schlussstück keine Wand schneidet;
- Treppenboxen **nicht** in der Quelle (wie heute `ExpSkipped`), stattdessen Links.

Gerenderte Meshes taugen nicht als Quelle: Sie sind geschnitten (`CutPlacement`) und je nach Stufe Platzhalter,
`parse_source_geometry_data` läuft nur im Main-Thread und liest von der GPU, und im headless Check ist unklar, ob
Mesh-Arrays kommen. Die Godot-Schicht (`native/World/NavBake.cs`) packt die Core-Daten in
`NavigationMeshSourceGeometryData3D` (`AddFaces`/`AppendArrays`) und ruft `BakeFromSourceGeometryDataAsync`.

**Bake-Parameter** (Vorschlag (Claude)): `agent_radius` 0,25 m (= `Collide`-Kapsel, `Collide.cs:19`; der
Godot-Default 0,5 würde Türen schließen), `agent_height` 1,8 m, `agent_max_climb` 0,25 m, `agent_max_slope`
passend zu `Walk.SlopeBlocks`, innen `cell_size` = `cell_height` = 0,1 m. Begründung: Eine 0,9-m-Tür lässt nach
2 × 0,25 m nur 0,4 m, und mit 0,25-m-Zellen schließt das Raster sie. Map-Zellgröße per `MapSetCellSize` gleich
der Mesh-Zellgröße. Eine Untergrenze für `cell_size` im Code erzwingen (zu kleine Zellen frieren laut Docs ein).

**Maps, Regionen, Stockwerke:** eine Navigation-Map pro gemounteter Location plus eine Welt-Map für draußen; eine
Region pro Stockwerk. Die Stockwerke trennt die Höhe; `navigation_layers` dienen nur der Kennzeichnung, und die
Abfragemaske von `QueryPath` enthält **alle** Stockwerke plus Links, sonst gibt es keinen Treppenpfad. Jede Map wird
mit `MapSetActive(true)`, `MapSetCellSize` und `MapSetCellHeight` passend zum Mesh angelegt. Betritt eine Figur die Location, wechseln
Avoidance-Agent und Pfadabfragen per `AgentSetMap`. Ein per Kamera ausgeblendetes Stockwerk bleibt navigierbar.

**Wann gebacken, Cache:** direkt hinter `DeriveStands` in `WorldBuilder.BuildShellAsync`
(`WorldBuilder.cs:573/:818`); neu nur, wenn sich der `scene_etag` ändert oder ein Rebuild-Pfad
(`WorldBuilder.Models.cs:139/:325`, `WorldBuilder.Residency.cs:250/:338`) die Quelle ändert. Cache im Speicher,
Schlüssel = `scene_etag` + Version der Bake-Parameter (Vorschlag (Claude); ein Plattencache erst, wenn Backzeiten
über 300 ms gemessen werden). Beim Rebake die alte Region erst freigeben, wenn die neue synchronisiert ist, sonst
gibt es einen Frame ohne Pfad. Große Locations in Chunks mit `filter_baking_aabb` + `border_size`. Messbare Alternative in E2: Die Quelle sind
bereits 2D-Polygone; ein direkt aus ihnen gebautes Navmesh (bzw. der 2D-Bake pro Stockwerk) wäre exakt, ohne
Voxelraster und ohne das Zellgrößenproblem an Türen. E2 misst beide und nimmt das genauere, sofern es Links und
Abfragen gleich bedient. Vor der ersten
Pfadabfrage auf `MapGetIterationId(map) > 0` warten; bis dahin bleibt die Figur in `exit` bzw. am Start.

Geschätzte Kosten (nicht gemessen, mit `native/Bench/` messen): Raum ~10⁴ Zellen, wenige ms; Location bis
100 m ~10⁶ Zellen, 50–300 ms asynchron, Main-Thread unberührt.

**Links:**

- Treppen: ein Link pro Lauf von Absatz zu Absatz. Ein Link bewegt nichts; das Überqueren übernimmt der
  vorhandene `Stairs.RideStep` (`Core/Scene/Stairs.cs`), weil er die Höhenkurve kennt.
- Aufzug: Link mit hohen `enter_cost`; die vorhandenen Aufzugsstopps fahren. Gesperrter Aufzug = Link aus.
- Türen: keine Links, sie sind Lücken. Die Türschwelle wird eine **eigene kleine Region**; eine verschlossene Tür
  schaltet sie mit `RegionSetEnabled(false)` ab, ohne Rebake (Entscheidung (Claude)). Ein `NavigationObstacle3D`
  taugt dafür nicht: `affect_navigation_mesh` wirkt nur beim Backen, zur Laufzeit beeinflussen Obstacles nur die
  Avoidance.
- Check: Jeder Link muss mit beiden Enden innerhalb `link_connection_radius` eines Polygons liegen, sonst ist er
  still deaktiviert. Der `NavCheck` prüft das für jede Fixture.

**Avoidance:** direkt über `NavigationServer3D.Agent*`-RIDs mit `AgentSetAvoidanceCallback`, keine
`NavigationAgent3D`-Nodes, denn der Abspieler besitzt Zeit und Pfadverfolgung selbst. 2D-Avoidance pro Map.
`max_speed` = `order.speed_m_s` (bindend, 5b); der Gang-Clip wird auf dieses Tempo skaliert. Das heutige
`NpcWalk.WalkSpeed` 3,4 entfällt als Lauftempo. Gleiche Layer und Masken für alle Figuren (sonst ignorieren sie sich
still). Sobald `entry` oder `exit` beginnt, wird die Figur mit `AgentSetAvoidanceEnabled(false)` aus der Avoidance
genommen, damit RVO sie nicht vom Bettrand schubst; Figuren im `loop` sind statische Agenten mit Geschwindigkeit 0.
Tiere: Avoidance-Radius aus ihrem Footprint, Navmesh gemeinsam mit `agent_radius` 0,25 (Entscheidung (Claude));
ein großes Tier darf an engen Türen leicht clippen, ein eigenes Navmesh pro Radius erst nach Messung.

**Pfadsuche:** `NavigationServer3D.QueryPath` einmal pro `walk`, neu nur bei Abweichung über 1 m vom Pfad oder
Blockade über 1 s (Vorschlag (Claude)), nie pro Frame. Drehung geglättet wie in `NpcWalk` (gegen den kurzen
Rückwärtsblick auf Navmesh-Kanten). Fußhöhe weiter aus `FigureGround`/`SurfaceHeight`, nicht vom Pfad (das
Navmesh liegt bis zu `cell_height` über dem Boden).

**Kollision:**

- NPCs laufen kinematisch entlang Pfad + RVO-Geschwindigkeit, **ohne** Physik-Body; Clips und FootLock steuern den
  Körper. RVO kennt weder Navmesh noch Wände, die Safe-Velocity kann eine Figur durch Wand oder Möbel schieben.
  Deshalb wird nach jedem Schritt geklemmt: `MapGetClosestPoint` auf das Navmesh, innen zusätzlich
  `Collide.ClampAgainstWalls`. Ausgenommen ist das gerade Schlussstück zum `access`.
- Avatar beim freien Laufen (Tastatur), Vorschlag (Claude): **kein** `CharacterBody3D` in der ersten Stufe. Der
  Avatar behält `Collide.ClampAgainstWalls` (getestet gegen `collide.json`) und bekommt `MapGetClosestPoint` als
  zusätzliche Klemme, die jetzt auch **Möbel** sperrt (heute blockieren Möbel den Avatar nicht). Ausgenommen sind
  das gerade Schlussstück eines Auftrags und, bis E3 ihn ersetzt, der alte `OwnPropMotion`-Weg, der in den
  `access` 0,15 m am Möbel läuft; sonst wäre das Hinsetzen in E2 kaputt. Ein
  `CharacterBody3D` (Wände als `BoxShape3D`, Figuren-Layer nicht in der Maske, Treppen über die Fahrt statt
  `floor_snap`) kommt nur, wenn diese Klemme sich im Test als ruckelig erweist. Begründung: Gegenüber Navmesh-Klemme
  und `Collide` hat die Physik keinen belegten Nutzen, bringt aber einen zweiten Weltbegriff.
- Klick-Laufen (`ClickMove.PlanClickWalk`, heute gerade Linie und Abbruch nach 20 Frames Stillstand) wird
  `QueryPath` + Abspieler.

**Außenwelt:** **kein Navmesh** für Terrain-Kacheln (256 m bei 2 m Schritt, `Payloads.cs:586`; draußen blockiert
fast nichts). Draußen gelten die vorhandenen Regeln (`Walk.SlopeBlocks`, `WalkGround.TerrainPace`, Wasser-Gates)
plus RVO auf der Welt-Map (Avoidance braucht keine Region). Ein lokales Chunk-Navmesh (Zelle 0,5 m, Radius
≤ 64 m um den Spieler) erst, wenn Streuobjekte nachweislich Wege versperren (offen, Abschnitt 8).

### 5e. Avatar-Ablauf

0. **Angebote sind raumgebunden** (Entscheidung (Claude), folgt aus 5g): Der Avatar bekommt Möbel-Angebote nur im
   eigenen Raum. Ein Klick auf ein Möbel im Nachbarraum ist Klick-Laufen dorthin; das Angebot erscheint nach dem
   bestätigten Raumeintritt (`room`-Meldung, 5f). Reserviert wird nie raumübergreifend.
1. **Klick auf ein Angebot** (Möbel-Slot). Der Client kennt bereits Slot-Punkt, Facing, Gruppe, Raum, Ebene
   (`ScenePlaces` :11–46), freie Slots (`PropActionMotion.PickablePropRows` :126) und die Wurzelspuren der Clips.
   Neu nötig (Vorschlag (Claude)):
   - Marker-`access` mitparsen (der Server schreibt ihn schon, `scene_recipe.py:3988–3990`; der native Parser
     liest ihn nicht);
   - Entry-Clip bzw. Pose-Kind je Gruppe sowie `role_point`/`pair_yaw` in die Angebotszeile aufnehmen;
   - den automatischen Zugang lokal berechnen: Slot minus gedrehte Entry-Travel, nach der Regel in
     `docs/schnittstellen-3d.md:8236–8245`, als Core-Funktion mit Vektor gegen den Server.
2. **Sofort losgehen:** Der Abspieler bekommt einen **lokalen Vorab-Auftrag** (lokale Id,
   `exit → walk → wait_access`) und läuft zum berechneten `access`.
3. **Im Hintergrund reservieren:** derselbe Request wie heute (`prop_action_engine.request`), gleichzeitig mit dem
   Loslaufen. Die Antwort enthält bei Erfolg den echten Auftrag (`order_id`, `access`, `sequence`). Der Client
   übernimmt ihn **ohne Neustart**: Weicht der Server-`access` um mehr als 0,15 m ab, wird nur das Wegziel ersetzt
   (neues `QueryPath` ab der aktuellen Position); die Uhr läuft weiter.
4. **Ankunft:** Steht die Figur am `access` und die Zusage ist da → `POST /play/order/arrived`
   {`order_id`, x, z, yaw, room_id} und sofort `entry` spielen, ohne auf die Antwort zu warten. Fehlt die Zusage
   noch → `wait_access` (Figur steht, schaut zum Möbel), bis sie kommt.
5. **Plausibilitätsprüfung auf dem Server** bei `arrived`: Abstand zum `access` unter 0,5 m (statt heute 0,02 m,
   `prop_action_engine.py:2137`), gleicher Raum (`places.where`), Slot noch per Claim gehalten
   (`_validate(require_claims=True)`). Bestanden → `_begin_entry`; es schreibt die Position unter
   `_internal_mutation()` **exakt** auf `access`, auch für den Avatar, denn `_validate` verlangt in `entry` höchstens
   0,05 m zu `access` (`:492–495`) und in `active` höchstens 0,05 m zum Anker (`:501–503`). Danach `_activate` nach
   `entry_elapsed ≥ duration_s` (der vorhandene Timer), das den Slot schreibt. Nicht bestanden → Ablehnung
   (Schritt 6).
   **Positionsmeldungen während `approaching`:** Heute beendet jeder fremde Positions-Write den Run
   (`interrupt(..., "position")`, `character.py:938–947`, `prop_action_engine.py:1652–1664`), deshalb verwirft
   `play.py:1110–1121` sie. Neu (Entscheidung (Claude)): Meldungen des eigenen Avatars während `approaching` werden
   **ohne Interrupt** angenommen (Sichtbarkeit und Raum bleiben aktuell); erst eine Meldung aus einem anderen Raum
   bricht den Run ab.
6. **Ablehnung** (Reservierung oder `arrived` abgelehnt, `MutationRejected`): Abspieler → `abort`. Die Figur
   bleibt stehen, wendet sich vom Möbel ab (kurze Drehung, Ruhepose), ein HUD-Hinweis nennt den Grund. Lief der
   Einstieg schon, spielt der Client den Ausstiegsclip zurück auf den `access`.
7. **Kein `arrived`:** Der Server bricht den Run bei `deadline_motion_s` ab (Vorschlag (Claude):
   `eta + max(10 s, 0,5 · (eta − issued))`) und gibt den Slot frei. Der Client bekommt das als `cancel` mit neuer
   `order_id`.

`PropActionControl` verliert die Pausen- und Unsicherheitslogik (`Paused` :33, `PrepareWrites`, das vorherige
Flushen in `PreparePropActionAsync`); übrig bleibt die Reservierung mit Ablehnung (`MutationRejected` :47,
`RunEnded`).

### 5f. Positionsmeldungen beim freien Laufen und der verschlankte `/play/pos`

**Melderegel** (Nutzer): Meldung bei Halt, Raumwechsel und Aktionsstart, beim Laufen höchstens alle 2 s.
`PositionChannel.ReportMs = 330` (`Core/Embody/PositionChannel.cs:19`) wird durch eine Ereignisregel ersetzt
(Details Vorschlag (Claude)):

- `stop`: Geschwindigkeit unter 0,1 m/s für 0,3 s;
- `room`: Raum- oder Stockwerkswechsel nach `RoomWalk`;
- `action`: unmittelbar vor einer Reservierung (der Server prüft die Aktion ab diesem Punkt);
- `tick`: beim Laufen, wenn seit der letzten Meldung mindestens 2 s vergangen sind;
- `location`: Betreten oder Verlassen einer Location (die Regel-Gates brauchen das sofort).

Die Meldung trägt ihren Grund (`reason`) und wie heute die Sequenznummer.

**Server-Seite:** `_POS_REPORT_INTERVAL_S` wird 1,5 s (Puffer unter 2 s). Es **bleiben** Party-Follower-Sperre,
`isfinite`, Session/Seq, Location-Übergang mit Regeln (`check_leave`, `accessible_when`,
`check_location_access`), Discovery, Erkundung und NPC-Spawn. **Plausibilität statt Gate wird:**

- Sprungprüfung: die vorhandene `pos_step_allowance` (`play.py:853`, mit `_POS_CLIENT_ELAPSED_CAP_S = 30`) wird
  wiederverwendet, keine neue Formel; sonst Absage mit der letzten gültigen Position (Snap, wie heute bei einer
  Absage).
- Gelände-Gate `impassable` und Höhen-/Hang-Gate (`play.py:1395–1460`) prüfen nur noch den gemeldeten **Punkt**,
  nicht den Weg dorthin (den erzwingt das Navmesh); `stand_height_at` wird nicht mehr pro Meldung gerufen.

Die Snap- und Korrektur-Logik im Client (`AvatarPositionController.cs:194–245`) schrumpft auf das
Plausibilitäts-Nein. `RoomEntryChannel` (Halten 1,5 s, Bestätigung 10 s) bleibt als Meldung, blockiert das Laufen
aber nicht mehr. Ein verbotener Raum ist dem Client meist schon über die verschlossene Tür im Navmesh bekannt; eine
Regel-Absage des Servers setzt die Figur auf die letzte gültige Position zurück.

### 5g. NPC-Ablauf mit Schätz-Timer

Die Auslöser bleiben unverändert (`take_furniture_for_pose`, `take_bed_to_sleep`/`going_to_bed`; Aufrufer
`plugins/set_pose/skill.py:79`, `app/routes/chat.py:939`, `app/models/character.py:5254`). Sie rufen
`request()`; Entscheidung, Einwilligung, Claims und durabler Run bleiben.

**Ein Auftrag bleibt raumgebunden — Entscheidung (Claude), Variante a der Review.** Prop-Aktionen sind heute strikt
raumgebunden (`target_not_in_actor_room` in `prop_action_paths.py:495–497`, `travel_engine.py:1151/1195` und
`_validate`, `prop_action_engine.py:380ff.`), `visibility_path` rechnet auf genau einem Raumpolygon, und der Server
hat keinen Raum-zu-Raum-Pfad. Daran ändert dieser Umbau nichts. Ein Raumwechsel ist ein eigener `walk`-Auftrag
davor (5b, Bewegungsfälle).

**`_start` (`prop_action_engine.py:961–989`):** Slot reservieren wie heute, dann **schätzen statt eine Journey
starten**:

```
L      = Länge(visibility_path(start → access))          # prop_action_paths.py:323, im Raum, bleibt
walk_s = L / speed_m_s                                   # speed_m_s beim Start eingefroren
eta    = issued + exit_nominal_s + walk_s + start_slack
flip   = eta + entry_nominal_s
```

- `speed_m_s` = `get_travel_speed_m_s()` (Default 1,4 m/s, `travel_engine.py:86, 1117`), beim Start eingefroren
  und in den Auftrag geschrieben. Er ist für den Client **bindend** (5d); Schätzung und Bild laufen mit derselben
  Zahl. Ein Pace-Faktor kommt heute im Anlauf nicht vor und wird nicht eingeführt. Wirkt 1,4 m/s im Bild zu langsam,
  wird der eine Konfigurationswert angehoben, nicht der Client.
- `exit_nominal_s`, `entry_nominal_s`: nominelle Dauern aus dem Clip-Katalog (dieselben, die heute
  `entry_elapsed` misst); den echten Clip wählt der Client (5b).
- `start_slack` (Vorschlag (Claude)): 0,5 s für den Pfadstart im Client (Map-Synchronisierung, Drehen).
- Ist `visibility_path` leer (der Server findet keinen Weg), wird der Auftrag wie heute nicht angenommen.
- **React-Runs:** Wartet der Run nach der Ankunft auf die LLM-Reaktion des Partners, trägt der Auftrag
  `awaits: reaction` und noch kein `flip`. Trifft die Reaktion ein, setzt der Server `flip = jetzt + entry_nominal_s`
  und sendet eine Revision (5b, Fall 2). Läuft `REACTION_WAIT_S` ab, kommt der Abbruch als neue `order_id`.

**`walk`-Aufträge** (Raumwechsel, Punkt, Schlendern) nutzen dieselbe Rechnung: `L` = `visibility_path` im Raum,
bei Raumwechsel die Luftlinie über die Türpunkte des Rezepts × 1,3 (kein Server-Raumgraph nötig), draußen die Länge
der heutigen Punkt-Route als `hint_route`; `flip = eta`. Der **Raum** im Spielzustand wechselt bei einem
Raumwechsel wie heute sofort beim Befehl; zu `flip` schreibt der Server einmal die Zielposition.

Es entfallen `register_owner` mit seinen Callbacks (`:1715–1784`), die Approach-Journey im Profil und das
Profilfeld `prop_action_entry` als Anzeige-Zustand.

**`_advance_run` (`:2067–2182`, Approach-Zweig `:2109–2145`):**

- `approaching`: `motion_now ≥ eta` → `_begin_entry` (statt `last_journey_result` und dem 2-cm-Positionsbeweis
  `:2137`). Journey- und Receipt-Zweig entfallen ganz, weil ab E3 kein Run mehr eine Journey hat (5k).
- `waiting` (`awaits` gesetzt): kein Zeitvergleich, bis die Reaktion bzw. Zusage eintrifft; die Deadline gilt.
- `entering`: `entry_elapsed ≥ duration_s` → `_activate` (unverändert, schon ein reiner Timer).
- Der Deadline-Abbruch bleibt.

**Ticker:** Der TravelTicker bekommt einen Beat genau zu `eta` und `flip`; `due_in_s` bekommt dafür einen
`eta`-Zweig. Die Sonder-Beats für Approaches (`_early_beats`) entfallen. Damit „pro laufendem Auftrag nur ein
Zeitvergleich“ stimmt, validiert `advance()` nicht mehr bei jedem fälligen Beat alle Live-Runs (heute
`:2049–2060`), sondern nur die Runs, die in diesem Beat fällig sind.

**Motion-Uhr und Server-Neustart — Entscheidung (Claude), Variante a der Review.** `motion_time()` läuft über die
Downtime weiter (`timeutils.py:303, 350–358`); nur ein Freeze ankert neu. Absolute `eta`/`flip`/`deadline` wären
nach einem Neustart sofort fällig. Deshalb bleibt das akkumulierende Muster von `_clock` (`:1688–1710`: Delta 0
nach Neustart): Erkennt `_clock` den Neustart, verschiebt es `issued`, `eta`, `flip` und `deadline` des Auftrags um
die Downtime (`now_s − last_motion`) und erhöht die `revision`. Für `walk`- und freie `pair`-Aufträge, die keinen
durablen Run haben, macht das ein einmaliger Boot-Durchlauf. Variante b (Motion-Uhr beim Boot neu ankern) wird nicht
gewählt, weil sie `journey_state` aller Überlandreisen mit verschiebt.

**Position im Spielzustand:** Beim Auftragsstart bleibt die Position die Startposition, mit Status `approaching`
(Ziel bekannt). Bei `_begin_entry` setzt der Server die Position einmal exakt auf `access` (unter
`_internal_mutation()`, auch für den Avatar, 5e), bei `_activate` auf den Slot. Dazwischen wird nichts geschrieben.

**Was Wahrnehmung und LLM inzwischen sehen** (Vorschlag (Claude)): genau das, was heute der Zustand
`approaching` zeigt: Die Figur ist im Raum und hat die Aktivität „geht zum Bett“. Die Abweichung um den
Schätzfehler ist akzeptiert.

**Push:** `order_changed` bei Start, Abbruch und jeder Revision; keine Signale mehr pro Approach-Schritt (heute
`travel_changed`, `sync_topics.py:375`).

### 5h. Überland-Reisen

- Der Server bleibt Herr der Reise: `start_journey`, `_bake_route` (`travel_engine.py:658`), `journey_state` als
  reine Funktion der Motion-Uhr, Ankunfts-Gate (`_arrival_gate`, `:1659`), Party-Logik. Die Route wird **einmal
  pro Reise** gerechnet; sie dient der Dauer, der Position ohne Zuschauer und der Sichtbarkeit.
- Der Auftrag `kind=travel` trägt Route und Journey-Felder. Jeder Client kann daraus dieselbe grobe Position
  ableiten (`TravelPath.PolylineLength`, `PointAtDistance`, `DensifyPolyline` bleiben).
- **Client-Verfeinerung im Nahring** (Vorschlag (Claude): 64 m um Kamera bzw. Avatar): Die Figur folgt der groben
  Route, weicht per RVO anderen Figuren aus, nutzt innerhalb von Locations das Navmesh für Türen und Hindernisse
  und darf seitlich bis zu 3 m von der Route abweichen. Der **Fortschritt entlang** der Route bleibt die reine
  Funktion `journey_state`; der Client verschiebt die Figur nur quer, nie längs. So bleibt die Ankunft für alle
  Clients und den Server gleich, ohne Nachführung durch Polls.
- Außerhalb des Nahrings: Figur exakt auf der groben Route (billig, wie heute).
- Server: `_TICK_SECONDS` kann von 5 s auf 10 s oder mehr steigen (Vorschlag (Claude), nach Messung). Positionen
  werden pro Tick nur noch für Sichtbarkeit und Raumlogik geschrieben, nicht fürs Bild.
- **Party-Follower — Entscheidung (Claude):** Follower bekommen keine eigenen Aufträge. Der Server bewegt sie wie
  heute mit dem Leiter (`_move_party_followers`, `travel_engine.py:1542`, bzw. mit den gemeldeten Positionen des
  Leiters); pro Meldung entsteht kein Follower-Auftrag. Der Client stellt Follower lokal hinter der Leiterfigur dar,
  mit festen Formations-Versätzen (Reihe hinter dem Leiter, seitlich versetzt), auf dem Navmesh bzw. der groben
  Route geklemmt und per RVO ausweichend. Ein laufender eigener Auftrag eines Followers wird beim Beitritt mit
  `cancel` beendet; eigene Laufbefehle bleiben wie heute gesperrt.
- Avatar auf eigener Reise: dieselbe Regel; er meldet nur an Location-Grenzen und beim Halt. Die
  Browser-Zustandsmaschine `avatarDrive` hat kein Gegenstück.

### 5i. Paare und Gruppen

Es gibt **zwei** Paar-Systeme; beide werden zu `kind=pair` (Gruppen sind Paare mit mehr Rollen):

- **Paar am Möbel** über den durablen Run: `order_id` = `execution_id`.
- **Freies Paar** über `interaction_engine` (`_walk_to_partner` → `start_journey_to_point`, `:1845–1884`;
  `settle_approaches` im Ticker, `travel_engine.py:2272`; Tabelle `interaction_invites`): `order_id` = Interaktions-
  bzw. Invite-Id, Revision und Zeiten in der Invite-Zeile. `settle_approaches` wird durch denselben Timer wie bei
  NPCs ersetzt: Ankunft des Gehenden = sein `eta`, keine Journey mehr (Entscheidung (Claude)).

Gemeinsam für beide:

- Der Auftrag nennt alle `actors` mit Rolle, `anchor`, `role_points` und `pair_yaw`. **Jeder Client spielt alle
  Beteiligten** auf einer gemeinsamen lokalen Uhr (Nutzer). Der Snap auf die Server-Uhr `clip_s` in
  `PairClip.Phase` (`:49`) entfällt.
- Anlauf: Jeder Beteiligte hat seinen eigenen `walk` im selben Auftrag. Wer zuerst ankommt, wartet in
  `wait_access` mit Blick zum Anker. Die lokale Uhr des gemeinsamen Clips startet bei 0, sobald **alle** am
  `access` stehen, spätestens bei `max(eta_i) + 5 s`; wer dann noch fehlt, wird auf seinen `access` übergeblendet
  (Heilregel 4, 5c). So wartet der Start nie endlos auf eine feststeckende Figur.
- Die Geometrie bleibt (Anker + Yaw × Clip-Wurzel, `PairClip.AnchorPoint`, Vertrag A8a Z. 3127–3140).
- `tempo` (0,2–1, `pose_scene.py:16–31`) steht im Auftrag; ändert ein Paket es zur Laufzeit, kommt eine Revision.
- Server: Der Paarzustand wird bei `flip = max(eta_i) + entry_nominal_s` aktiv. Phasenwechsel (`combined`, auf
  der Spielzeit) und das Finale (A8c, `pose_scene.begin_finale`, mitten in der Szene) kommen als Revision; der
  Client taktet sie nicht nach einer Dauer (5b, 5c). Das Ende nach dem Finale meldet ebenfalls der Server.
- Ist der Avatar beteiligt, gilt für ihn 5e. Der gemeinsame Start wartet im Client auf seine Ankunft (mit derselben
  Frist), der Server kippt den Zustand erst nach seinem plausiblen `arrived`.

### 5j. Mehrere Clients, kein Client

- **Kein Client:** Der Server läuft rein auf Timern (`eta`, `flip`, Deadline) und `journey_state`. Für NPCs gibt
  es keinen Unterschied zum Fall mit Client; der Server wartet nie auf einen Client für einen NPC.
- **Mehrere Clients:** Jeder spielt jeden Auftrag selbst; RVO und Pfade dürfen sich leicht unterscheiden. Nur der
  Client, der einen Avatar steuert, meldet `arrived` und Positionen für diesen Avatar. Meldungen eines Clients über
  fremde Figuren gibt es nicht.
- Ein Client, der einen Auftrag mitten drin bekommt, folgt der Einstiegsregel aus 5c.
- **Fremde Avatare anderer Spieler — Entscheidung (Claude):** Beim freien Laufen gibt es für sie keinen Auftrag,
  nur ihre seltenen Positionsmeldungen (5f). Der Client interpoliert: Er bewegt die Figur gleitend zum neuesten
  gemeldeten Punkt und extrapoliert danach entlang der letzten Geschwindigkeit, höchstens 2 s lang; dann bleibt sie
  stehen, bis die nächste Meldung kommt. Ein Sprung über die Plausibilitätsgrenze wird gesetzt, nicht gelaufen.
  Akzeptiert, weil meist nur ein Client läuft. Für Möbel-Aufträge eines fremden Avatars gilt der normale Auftrag.

### 5k. Was entfällt; Rückbau des Browser-Clients

Was in welcher Etappe fällt, steht in Abschnitt 8; der alte Weg wird jeweils in **derselben** Etappe gelöscht, in der
der neue ihn ersetzt (Entscheidung (Claude), kein Doppelbetrieb).

**Server:**

- `travel_engine.start_approach_journey`, `_advance_approach`, `_commit_approach_position` (`:1089–1359`, rund
  270 Zeilen), komplett.
- In `prop_action_engine`: `register_owner` und die Owner-Callbacks (`:1715–1784`), das Verschieben der
  Journey-Startzeit beim Reanchor (`:1678–1712`); an seine Stelle tritt das Verschieben der Auftragszeiten um die
  Downtime (5g), das Spielzeit-Delta bleibt. Journey-, Receipt- und Positionsbeweis-Zweig in `_advance_run`.
- Beim ersten Boot mit E3 werden laufende Runs mit Approach-Journey einmal abgebrochen (Slot frei), ohne
  Übernahme-Pfad.
- `start_journey_to_point` als NPC-Weg (`npc_actions`, `npc_home`) und als Gang zum Partner
  (`interaction_engine._walk_to_partner`, `settle_approaches`): ersetzt durch `walk`- bzw. `pair`-Aufträge.
- In `world_ops`: `_local_prop_approach` (`:400`) und `_prop_action_entry` (`:451`), ersetzt durch das Feld `order`.
- `_early_beats` im TravelTicker; Approach-Signale in `sync_topics`.
- In `/play/pos`: die 4-Hz-Drosselung, die Weg-Gates, `stand_height_at` pro Meldung.
- `motion_for`/`_motion_snapshot` werden zum Auftrag umgebaut, ohne Alias.

**Client (nativ):** `JourneyRoute` (`ExactPath`, `Stamp`, `DepartureClip`), `DeadReckoning`, aus `TravelPath`
`CatchUpStep`, `DeadReckon*`, `AdoptTarget`, `HardSnapM`, `ErrWindow`, `TravelSync`, `MapReceipt`,
`AgeAtReceiptS`; `FigureManager.AdoptReckoning`/`AdoptRoute`/`StepRoute`, `AdoptExactPropRoute`/
`StepExactPropRoute`; `UpdateOwnPaces`; `NpcWalk.Goal/Step` als Schrittregel (Facing und Eases bleiben;
`WalkSpeed` weicht dem bindenden `order.speed_m_s`); `NpcRoute.Plan` innerhalb einer Location, ersetzt durch `walk` + Navmesh (Treppenfahrt und Aufzugsstopps
bleiben); das 330-ms-Melden in `PositionChannel`.

**Vertrag `docs/schnittstellen-3d.md`:** Ein neuer Abschnitt „Auftrag“ führt A11 (Anläufe), das C3-`motion` und
A8c zusammen; A15 wird „Plausibilitäts-Meldung“. Neu zu fassen sind A1.4 `travel`, A8 Z. 2510/2655/2739, A8a
Z. 2952–2986 und 3046–3093, C3 Z. 8385–8449, 8995–9039 und 9045–9051, C4 Z. 10525–10600 sowie die
Oberflächenraster-Regel C3 Z. 10093–10132. Browser-Teile werden gestrichen (A8 `client3d/src`-Verweise, A11
`avatarDrive` Z. 3989–4024, A14 „Was die Renderer daraus machen“, A15 Z. 4961–4978, C3 Z. 9040–9044, Kopf
Z. 1–120).

**Testvektoren:** Neu herleiten oder löschen: `travel.json`, `prop_action_motion.json`, `place_poll.json`,
`npc_placement.json`, `room_spots.json`, `figure_ground.json`, `npc_walk.json`, `npc_ground.json`,
`walk_control.json`, `enter.json`, `embody.json`, `pair_clip_phase.json`, `poll_schedule.json`. `collide.json`
bleibt, solange `Collide` als Klemme bleibt. Die Bridge-Vektoren (`bridge_*`, `stand_settle`, `foot_lock*`,
`leg_pin`) bleiben gültig, nur ihre Quelle zieht um. Neu (Vorschlag (Claude)): `order_estimate.json` (ETA und
Flip aus Pfadlänge und Clipdauern), `order_chain.json` (Kettenreihenfolge, Einstieg mitten drin, Abbruch bei
Ablehnung), `access_auto.json` (lokaler Zugang = Server-Zugang).

**Browser-Client** (Entscheidung (Claude): Umzug der Herleitungen und des HUD in E1, Löschen der Szene in E3):
Bei rund 70 der 82 Vektordateien liegt die Quell-Herleitung unter `client3d/scripts/`, und die
README von `shared/test-vectors/` verbietet Vektoren ohne Quell-Smoke. **Vor** dem Löschen von `client3d/` ziehen
diese Docstrings nach `scripts/` (Server-Herkunft) oder `native/tests` um. Danach werden `client3d/` (Szene) und
`static/client3d/` gelöscht, die Browser-Smokes `smoke_follow_bridge_client.mjs`, `smoke_mouth_approach.mjs` und
`smoke_sync_client.mjs` entfernt und `npm run build`, die Workspaces und CLAUDE.md angepasst.
**Achtung:** Der CEF-HUD des nativen Clients lädt `static/client3d/hud.html` (`native/Hud/HudOverlay.cs`). Der
HUD-Teil (`client3d/src/hud/` mit `@anima/player-ui`) zieht deshalb in E1 in den eigenen Workspace `hud/`
(Entscheidung (Claude)), der nach `static/hud/` baut; der CEF-HUD lädt danach `static/hud/hud.html`. Gelöscht
wird nur die 3D-Szene. `/play` zeigt nach dem Löschen eine schlichte Hinweisseite, dass der native Client nötig ist
(Entscheidung (Claude)). `packages/scene-render` bleibt (Admin-Vorschau).

## 6. Fehler- und Grenzfälle

| Fall | Verhalten |
|---|---|
| **Slot belegt während des optimistischen Laufens** | Die Reservierung kommt als Ablehnung zurück → `abort`: stehen bleiben, abwenden, Grund im HUD. Ist ein gleichwertiger Slot frei, bietet das HUD ihn an; kein automatischer Wechsel (Vorschlag (Claude)). |
| **Ziel für den Client unerreichbar, für den Server erreichbar** | NPC: `QueryPath` liefert keinen Pfad bis `access` oder endet mehr als 0,5 m davor → die Figur geht so weit wie möglich und wird dann kurz auf `access` übergeblendet; der Zustand kippt ohnehin per Timer. Avatar: HUD „kein Weg“, `abort`, der Client bricht den Run per Request ab. In beiden Fällen eine Logzeile mit Location und Slot, damit Navmesh-Fehler sichtbar werden. |
| **Ziel für den Server unerreichbar, für den Client erreichbar** | Der Server nimmt den Auftrag nicht an (heutige Annahmeprüfung). Der Avatar sieht die Ablehnung nach dem optimistischen Loslaufen; seltener Fall, akzeptiert. |
| **Figur steckt fest** (unter 0,05 m/s für 2 s) | Neues `QueryPath`; nach dem zweiten Fehlschlag Überblendung auf `access` (NPC) bzw. `abort` (Avatar). |
| **Raumwechsel** | Ein `prop_action` ist raumgebunden; einen Raumwechsel gibt es nur als `walk`-Auftrag, dessen Navmesh-Pfad durch Türen und über Treppen-Links führt. Der Raum im Spielzustand wechselt beim Befehl wie heute. Beim Avatar löst er eine `room`-Meldung aus; eine Regel-Absage setzt ihn auf die letzte gültige Position und bricht den Auftrag ab. Ein Möbel-Angebot im neuen Raum erscheint erst nach dem bestätigten Eintritt. |
| **World freeze** | Die Motion-Uhr steht, der Server tut nichts. Der Client liest `world_frozen` aus dem Payload und setzt alle Abspieler auf `frozen` (Uhr hält, Clip hält per `HoldClipAt`). Beim Auftauen läuft die lokale Uhr weiter. `eta` und `flip` liegen auf der Motion-Uhr und verschieben sich dadurch von selbst. |
| **Server-Neustart mitten im Auftrag** | Die Motion-Uhr läuft über die Downtime weiter. `_clock` erkennt den Neustart und verschiebt `issued`/`eta`/`flip`/`deadline` um die Downtime, mit höherer `revision` derselben `order_id` (Boot-Durchlauf für `walk` und freie `pair`, 5g). Der Client übernimmt die neuen Zeiten an Ort und Stelle, ohne Rückspulen; eine Kette, die im Bild schon weiter ist, bleibt, wo sie ist. Überlandreisen laufen wie heute über die Downtime weiter. |
| **Client-Neustart mitten im Auftrag** | Einstiegsregel aus 5c (einmal Seek beim Annehmen). |
| **Poll kommt mitten in der Kette** | Gleiche `order_id` und `revision` → No-op. Positionsfelder der Zeile werden auf Figuren mit laufendem Auftrag **nicht** angewandt. Wird im Check geprüft (Abschnitt 7). |
| **Avatar teleportiert** (Zauber, Admin) | Der Server sendet `cancel` mit neuer `order_id` und setzt die Position; der Client bricht den Auftrag ab und setzt die Figur hart. Der Teleport ist der einzige harte Snap des Avatars. |
| **NPC durch eine neue LLM-Entscheidung unterbrochen** | Der Server bricht den alten Run ab (Slot frei) und startet einen neuen: neue `order_id`. Client: aus `walk` direkt ein neuer Pfad; aus `entry`/`loop` zuerst ein Ausstieg aus dem **aktuellen Bildzustand**, auch wenn der Server die Figur schon als „steht“ führt. |
| **Avatar wird während des Laufens Party-Follower** | Sein laufender Auftrag endet mit `cancel`; danach stellt der Client ihn als Follower hinter der Leiterfigur dar (5h), ohne eigenen Auftrag. Eigene Laufbefehle sind wie heute gesperrt. |
| **Szene ändert sich (`scene_etag`) während eines Auftrags** | Rebake asynchron; der laufende `walk` behält seinen Pfad bis zur nächsten Abweichung; neue Abfragen nach der Synchronisierung auf der neuen Region. |
| **Auftrag für eine Figur, deren Location nicht gemountet ist** | Kein Bild, nur Zustand. Beim späteren Mounten gilt die Einstiegsregel. |
| **Server wartet auf eine Reaktion (`awaits: reaction`)** | Alle Clients zeigen die Figur in `wait_access` am Möbel. Die Revision mit `flip` startet den Einstieg; ein Ablauf von `REACTION_WAIT_S` kommt als neue `order_id` (Ausstieg bzw. Abwenden). |
| **Phasenwechsel, Finale oder Tempoänderung während eines Paars** | Revision derselben `order_id`; der Client wechselt mit Überblendung, die lokale Uhr läuft weiter. |
| **Fremder Avatar läuft frei** | Interpolation zur neuesten Meldung, danach höchstens 2 s Extrapolation entlang der letzten Geschwindigkeit (5j). |
| **Browser-Client nach E3** | Nicht mehr unterstützt; `/play` zeigt die Hinweisseite. |

## 7. Messung und Erfolg

**Baseline vor jeder Änderung (E0)** und dieselbe Messung nach jeder Etappe, in der Testwelt (Klon), mit einem
festen Szenario: Ein Avatar läuft 60 s frei und nimmt dann einen Sessel; drei NPCs gehen nacheinander ins Bett;
eine Überlandreise läuft.

- **Server-CPU pro Minute:** Delta von `utime+stime` aus `/proc/<pid>/stat` des Uvicorn-Prozesses über das
  Szenario, als Skript `scripts/measure_client_execution.py` (Vorschlag (Claude)), das nur liest. Erwartung (nicht
  gemessen): die Senkung kommt vor allem aus `/play/pos` (rund 6× weniger Meldungen: heute etwa 3 pro Sekunde, danach höchstens 0,5 plus Ereignisse) und den entfallenen
  Approach-Beats.
- **Request-Zahlen:** `/play/pos`, Worldmap und neu `/play/orders` pro Minute, gezählt über einen In-Memory-Zähler
  pro Route im Server (Vorschlag (Claude): einmal pro Minute in `logs/main.log`). Ziel: `/play/pos` beim Laufen im
  Mittel höchstens 0,7 pro Sekunde (einschließlich Ereignismeldungen), Worldmap-Takt unverändert, `/play/orders`
  nur nach Push.
- **TravelTicker-Beats** pro Minute (Zähler in `_next_beat_s`) und **`advance()`-Läufe** samt der darin validierten
  Runs (heute validiert jeder fällige Beat alle Live-Runs, `:2049–2060`). Ziel: ohne Approaches nur noch
  `eta`-/`flip`-Beats, und pro Beat werden nur die fälligen Runs validiert (5g).
- **Erster Schritt des Avatars:** Zeit vom Klick bis zur ersten Positionsänderung über 1 cm im Client-Log. Ziel:
  ein Frame nach der Klickverarbeitung (heute 0,7–3 s).

**Headless-Prüfung „Kette vollständig ab Phase 0“** (`native/Check/OrderCheck.cs`, `--check=orders`, Fixture
`native/fixtures/orders/`, Vorschlag (Claude)):

1. Szene mit Bett, Sessel, Tür und Treppe laden; Navmesh backen; auf `MapGetIterationId > 0` warten (Frames
   schrittweise weiterlaufen lassen).
2. Auftrag „sitzender NPC → Bett“ anwenden; die Frames mit fester Schrittweite laufen lassen. Der Abspieler
   protokolliert jeden Zustandswechsel mit lokaler Zeit.
3. Bei t = 1,0 s, 3,0 s und 5,0 s einen synthetischen Poll mit demselben Auftrag und abweichenden Positionsfeldern
   einspielen.
4. Erwartung: genau die Folge `exit → walk → entry → loop`, jede Phase **einmal**, `exit` beginnt bei t ≈ 0;
   keine Phase neu gestartet; die Kettendauer entspricht der von Hand hergeleiteten Summe (Clipdauern + Pfadlänge /
   Tempo) mit Toleranz; ein anschließender `walk` in den Raum im Obergeschoss geht durch die Tür und über den Treppen-Link; die Abweichung zur
   Server-Schätzung für dieselbe Fixture (Wert in `fixtures/README.md` hergeleitet) beträgt höchstens 1,5 s.
5. Zweiter Lauf: Ablehnung bei t = 0,8 s → `abort`, danach keine weitere Phase.
6. Dritter Lauf: Auftrag mit `lag = 4 s` → Start mitten im `walk` an der hergeleiteten Stelle.
7. Vierter Lauf: bei t = 2,0 s dieselbe `order_id` mit höherer `revision` (nur Status und verschobene Zeiten, wie
   nach einem Server-Neustart) → keine Phase neu gestartet, lokale Uhr unverändert; bei t = 3,0 s eine neue
   `order_id` (`cancel`) → Ausstieg aus dem aktuellen Bildzustand.
8. Fünfter Lauf: Auftrag mit `awaits: reaction` → `wait_access` am `access`; Revision mit `flip` bei t = 4,0 s →
   genau dann `entry`.
9. Jede Fixture: `access` liegt höchstens 0,4 m vom nächsten Navmesh-Punkt, das Schlussstück schneidet keine Wand,
   jeder Link liegt mit beiden Enden innerhalb `link_connection_radius`.

Server-Seite: `scripts/smoke_order_estimate.py` leitet `eta` und `flip` für eine Fixture-Geometrie **von Hand im
Docstring** her (Muster `smoke_scene_recipe.py`) und prüft `_start`/`_advance_run` gegen eine Fake-Motion-Uhr, einschließlich des Neustart-Falls (Zeiten um die
Downtime verschoben, Revision erhöht, nichts sofort fällig) und eines React-Runs (`awaits`, später `flip`).
`scripts/smoke_play_pos.py` wird für die neue Melde- und Plausibilitätsregel neu hergeleitet. Navmesh-Ergebnisse
werden mit Toleranz geprüft, nie bitgleich.

## 8. Etappen

Jede Etappe endet mit einer sichtbaren Abnahme durch den Nutzer und lässt ein spielbares Spiel im nativen Client
zurück. **Entscheidung (Claude): kein Doppelbetrieb.** Der alte Weg wird in der Etappe gelöscht, in der der neue ihn
ersetzt; es gibt keinen Übergangsschalter. Ab E3 ist der Browser-3D-Client nicht mehr unterstützt und gelöscht.

| Etappe | Lieferung | Sichtbare Abnahme |
|---|---|---|
| **E0 Messbasis** | Messskript, Routenzähler, Zähler für Beats und `advance()`-Läufe, Baseline-Zahlen | Nutzer sieht die Baseline-Tabelle |
| **E1 HUD-Workspace und Herleitungen** | HUD aus `client3d/src/hud/` in den Workspace `hud/` (→ `static/hud/`), CEF-HUD lädt `static/hud/hud.html`; Vektor-Herleitungen aus `client3d/scripts/` nach `scripts/` bzw. `native/tests`; kein Verhaltenswechsel | Nativer Client mit HUD wie bisher; alle Vektor-Smokes grün aus den neuen Orten |
| **E2 Navmesh im Client** | `Core/Nav/NavSource`, `NavBake`, Maps/Regionen/Links, Türschwellen-Regionen, `NavCheck`, Debug-Overlay (Taste); Messvergleich Voxel-Bake gegen 2D-Polygon-Navmesh; Klick-Laufen über `QueryPath`; Avatar-Klemme sperrt Möbel (alter `OwnPropMotion`-Weg ausgenommen) | Avatar läuft per Klick um Möbel herum, durch Türen und über Treppen; das Overlay zeigt das Navmesh |
| **E3 Aufträge: Abspieler, Avatar, NPC, walk** | `OrderPlayer` in Core, `FigureManager.Orders`; Marker-`access`, Angebotszeile, lokaler Zugang; Auftrag in der Reservierungsantwort, `POST /play/order/arrived`; Feld `order`, `motion_now`, `order_changed`, `/play/orders`; `_start`/`_advance_run` auf Timer inkl. React-Runs, Neustart-Verschiebung, Ticker nur fällige Runs; `walk`-Aufträge statt `NpcRoute` und Punkt-Journeys; Avoidance mit Klemme; `OrderCheck`. **Gelöscht in derselben Etappe:** Server-Anlaufcode (5k), Owner-Callbacks, `_local_prop_approach`/`_prop_action_entry`, alte Client-Nachführung für Anläufe, `OwnPropMotion`, Browser-3D-Szene, `static/client3d/`, Browser-Smokes; `/play`-Hinweisseite; Vertrag A11/C3-`motion` neu | Klick auf den Sessel → der Avatar geht sofort los und setzt sich ohne Stocken; bei belegtem Slot bleibt er stehen und wendet sich ab; ein NPC geht zum Bett und legt sich hin, ohne Abbruch oder Sprung; ein NPC wechselt den Raum über die Treppe |
| **E4 Melderegel** | Ereignis-`PositionChannel`, verschlankter `/play/pos` (`pos_step_allowance`, Punkt-Gates), nicht blockierender `RoomEntryChannel`, Interpolation fremder Avatare; gelöscht: 330-ms-Melden, Weg-Gates, `stand_height_at` pro Meldung | Freies Laufen fühlt sich unverändert an; der Zähler zeigt die gesunkene Rate |
| **E5 Paare und Gruppen** | `pair`-Aufträge für beide Paar-Systeme, gemeinsamer Start mit Frist, Phasen/Finale/Tempo als Revision; gelöscht: Server-Clip-Uhr-Snap, `settle_approaches`-Journeys, `_walk_to_partner`-Journey | Paar-Animation startet für beide gleichzeitig und läuft ohne Sprünge, auch über das Finale |
| **E6 Überland und Party** | Auftrag `travel`, Verfeinerung quer zur Route im Nahring, Follower in Formation, Ticker-Takt nach Messung; gelöscht: `DeadReckoning`, `JourneyRoute`, `TravelPath`-Nachführung | NPC weicht auf dem Weg anderen aus, statt durch sie zu laufen; Follower folgen geordnet; Ankunft wie bisher |
| **E7 Abschluss** | Messung wiederholen, Vertragskopf und CLAUDE.md nachziehen, Workspaces und `npm run build` bereinigen | Messvergleich gegen E0; alle Checks grün |

**Festgelegt, mit Messregel** (Entscheidung (Claude); vorher „offen für den Bauenden“):

- Physik: kein Körper in der ersten Stufe; ein `CharacterBody3D` (dann mit Jolt, ausdrücklich eingetragen) nur, wenn
  die Navmesh-Klemme im Test ruckelt.
- Chunk-Navmeshes draußen: werden nicht gebaut, solange keine Messung zeigt, dass Streuobjekte Wege versperren.
- Toleranzen als Startwerte, im Test zu justieren, ohne neue Entscheidung: Ankunft 0,15 m im Client und 0,5 m auf dem
  Server, Feststecken unter 0,05 m/s für 2 s, Heilfrist `flip + 5 s`, Paar-Startfrist `max(eta_i) + 5 s`, Nahring
  64 m, seitliche Abweichung 3 m, `lag`-Grenze 2 s, Extrapolation fremder Avatare 2 s, Raumwechsel-Umwegfaktor 1,3.
- `/play` nach dem Rückbau: Hinweisseite; HUD-Workspace `hud/` → `static/hud/`.
- Plattencache für Navmeshes nur, wenn Backzeiten über 300 ms gemessen werden.
- `order_changed` wird ein neues Topic; `travel_changed` bleibt für Überland.

## 9. Review-Entscheidungen

Review vom 2026-11-25: alle blockierenden (B1–B4) und wichtigen (W1–W9) Befunde sowie die kleinen Befunde sind
eingearbeitet. Abweichungen:

- B1, Variante b (raumübergreifende Aufträge mit Server-Raumgraph): nicht gewählt. Variante a reicht, weil der
  Raumwechsel als `walk`-Auftrag davor kommt; ein Server-Raumgraph wäre neue Serverarbeit gegen Ziel eins.
- B2, „befristeter, benannter Schalter“: nicht gewählt; ersetzt durch die Entscheidung „kein Doppelbetrieb“
  (Browser-Szene und alter Anlaufweg fallen in E3).
- B3, Variante b (Motion-Uhr beim Boot neu ankern): nicht gewählt, weil sie alle Überlandreisen mit verschiebt.
- Klein, „E4: Server drosselt den Browser-Client“: gegenstandslos, der Browser-Client ist ab E3 gelöscht.
- Klein, „Physik-Backend“: übernommen als „gegenstandslos bis zum ersten Physik-Körper“ (Abschnitt 3).
- W1, `travel_pace_factor`: nicht eingeführt. Der Server-Anlauf kennt heute keinen Pace-Faktor; die eine Zahl
  `speed_m_s` genügt für Schätzung und Bild.

- **E1 umgesetzt (2026-11-25, Plan `docs/superpowers/plans/2026-11-25-client-ausfuehrung-e0-e1.md`, Tasks 6–13).**
  Endgültige Zuordnung der Vektor-Herleitungen (Wächter `scripts/smoke_vector_sources.py`: 0 Verletzungen;
  `--verify-move`: 70 `MOVED`-Einträge, 0 Abweichungen):
  - **Klasse A** (getesteter Code nur in `packages/*` oder `hud/src`; Smoke per `git mv` nach `scripts/`):
    `ground_polygons` (`smoke_ground_math.mjs`), `hillshade`, `role_turn` (`smoke_role_turn_vectors.mjs`),
    `scene_place` (`smoke_place_rotation.mjs`), `scene_primitives`, `scene_verify`; mitgezogene Helfer ohne
    eigenen Vektor: `smoke_plate_hole.mjs` und `smoke_wall_uv.mjs` (von `smoke_scene_primitives.mjs` per Pfad
    gebündelt, im Plan nicht gelistet). Dazu `graphics_prefs` (`smoke_graphics_prefs.mjs`), die mit den reinen
    HUD-Smokes in Task 8 nach `scripts/` zog. Keine A-Smoke musste zurück nach Klasse B.
  - **Klasse C** (Herleitung im Docstring der Python-Zwillings-Smoke): `group_role_points`
    (`scripts/smoke_group_role_points.py`), `prop_water` (`scripts/smoke_prop_water.py`); die JS-Smokes tragen den Zeiger.
  - **Klasse B** (Herleitung wortgetreu nach `native/tests/Derivations/<basis>.md`, JS-Smoke mit Zeiger bis E3):
    61 Vektoren aus 51 Smokes (Task 10: 22/18, Task 11: 20/15, Task 12: 19/18); dazu `clip_shift`, dessen
    Quelle vorher eine Formel war (`native/tests/Derivations/clip_shift.md`, ohne `MOVED`-Eintrag).
  - **E3-Punkt `undergrowth.json`:** hat keinen C#-Verbraucher (`native/tests/Derivations/undergrowth.md`
    nennt bis E3 nur `client3d/scripts/smoke_undergrowth.mjs`). `UndergrowthMath.Shade` ist trotzdem geprüft —
    über `fixtures/scatter_reference.json` in `ScatterCheck`; E3 entscheidet, ob der Vektor einen C#-Test bekommt
    oder entfällt.
  - **HUD-Workspace `hud/`** (`@anima/hud`), baut nach `static/hud/`, Dev-Port 5184; der CEF-HUD lädt
    `/static/hud/hud.html` (`HudOverlay.HudPath`).
  - **Typkanten (Plan-Entscheidung 6) gekappt:** `FinaleBlock` liegt in `hud/src/types.ts` (`finaleClip.ts`
    importiert ihn aus `@anima/hud/types`); `game/soundtrack.ts` deklariert `interface Point` lokal;
    `game/photoMode.ts` exportiert `interface PhotoEngine` statt `Pick<Engine, …>`.
  - Bekannt rot schon vor E1, unverändert: `client3d/scripts/smoke_stand_settle.mjs` und
    `smoke_prop_action_motion.mjs` (Test-Figur ohne `setRootAngle`), `smoke_secondary_motion.mjs`
    („drag tilt before solver“); deren Vektoren laufen grün in den Vektor-Smokes und in C#.
