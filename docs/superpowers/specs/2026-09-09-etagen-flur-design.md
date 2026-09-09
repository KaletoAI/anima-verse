# Etagen-Flur: ein automatischer Flur-Raum pro Etage

Stand 2026-09-09 · Design abgestimmt (Entscheidungen des Users in § 1.3) ·
Analyse und Ist-Befunde: `development_instructions/analyse-etagen-flur.md`

## 1. Ziel und Rahmen

### 1.1 Problem

Ein Charakter steht immer in genau einem Raum. Die Fläche zwischen den Räumen
einer Etage existiert geometrisch (Etagenplatte + Konturwände, § A6), hat aber
keine Identität. Folgen, im Code belegt:

- Eine Tür ohne `to` gilt als Außentür (`scene_recipe._doorways`:
  `outside = len(rooms) == 1`) und schneidet ein Loch in die Hülle ihrer
  Etage. Zwei Kellerräume öffnen so die Kellerhülle ins Erdreich.
- Der Avatar bleibt beim Verlassen eines Kellerraums im alten Raum: die
  Raumwechsel-Heuristik des 3D-Clients kennt als Fallback nur die
  Grundfläche, und die ist per Definition Etage 0.
- Fahrstuhl und Treppe liefern in den nächstgelegenen Raum der Zieletage;
  eine Etage ohne Raum wird gar nicht angeboten.
- Eine Figur in einem Raum ohne Mittelpunkt wird vom Client **vor dem
  Gebäude** platziert (`main.ts`, `slotOffset`-Zweig).

### 1.2 Lösung in einem Satz

**Der Flur einer Etage IST ein Raum** — ein gespeicherter, reservierter Raum
`__floor__<level>` nach dem Muster der Grundfläche `__ground__`
(`plan-grundflaeche.md` § 2: gespeichert, nie beim Lesen injiziert). Der
Server bringt ihn mit, der Autor benennt ihn höchstens. Chat, Hörweite,
Regeln, Anstand und Begrüßung behandeln ihn wie jeden Raum.

### 1.3 Entscheidungen des Users (2026-09-09)

1. **Etagen ≠ 0 bekommen den Flur automatisch.** Etage 0 hat nicht immer
   einen Flur (Gasthaus) → **Opt-in pro Location**. Eine Türkontrolle in
   allen Locations nach dem Umbau ist akzeptiert.
2. **Es gibt keine Balkontüren** → Türen ohne `to` auf Etagen ≠ 0 werden
   ohne Rückfrage zu Flurtüren (kein Hüllenloch mehr).
3. **v1 ohne Möblierung**; Flur-Furnish ist Entwicklungsidee (§ 9).
4. Ablauf: Planung + Review durch die Koordinations-Session, Umsetzung durch
   Opus-Subagenten.

### 1.4 Nicht Teil dieses Strangs

Innenraum-Wegfindung (der Flur ist ein **Zustand**, kein Wegpunkt; ein
NPC-Raumwechsel bleibt ein sofortiger Write), Flur-Möblierung, Props/Marker im
Flur, ein Flur-Rezept mit Geometrie, Balkontüren als Sonderfall.

## 2. Datenmodell

### 2.1 Reservierte Flur-Räume

- Id `__floor__<level>` mit `level` als ganzzahligem Vorzeichen-String:
  `__floor__-1`, `__floor__0`, `__floor__1`. Helfer in `app/models/world.py`:
  `floor_room_id(level) -> str`, `floor_room_level(room_id) -> Optional[int]`
  (None für jede andere Id), `is_floor_room(room_id) -> bool`.
- Raumeintrag `{id, name, description, activities: [], level: int}`. **Kein
  `layout`** — der Sanitizer verwirft eines ganz und protokolliert es (eine
  Zeile mit Location- und Raum-Id). Anders als die Grundfläche trägt der Flur
  in v1 auch kein reduziertes Layout.
- Name am Raum wie bei jedem anderen; ohne Namen der übersetzte Standard aus
  `get_room_name`/`get_floor_name(level, lang)`: Etage 0 → „Hallway",
  Etage −n → „Corridor (basement)" bzw. „Corridor (basement −2)" ab −2,
  Etage +n → „Corridor (floor n)". Deutsch in `shared/languages/de.json`.
- Nicht welteindeutig (wie `__ground__`): `GET /play/rooms/{id}/recipe`
  antwortet 400 für Flur-Ids, Furnish-Ziele gibt es nicht.

### 2.2 Wann ein Flur existiert (`ensure_floor_rooms`)

Reine Funktion `floor_levels(location) -> set[int]`: die `level`-Werte aller
Räume mit Layout (die „genutzten Etagen" von § A6), **ohne 0**, plus 0 genau
dann, wenn `map3d.ground_corridor` wahr ist UND Etage 0 einen Raum mit Layout
hat. `ensure_floor_rooms(rooms, map3d, previous)` gleicht `rooms[]` in beiden
Richtungen ab:

- fehlt ein Flur einer genutzten Etage → anhängen (Name/Beschreibung aus
  `previous`, wie `ensure_ground_room`),
- ein Flur einer nicht mehr genutzten Etage → entfernen,
- vorhandene Einträge bleiben unberührt (ein Autor kann die Id nicht
  vergeben: der Raum-Sanitizer lehnt eine Flur-Id im Editor-Payload eines
  neuen Raums ab).

Aufruf an denselben Stellen wie `ensure_ground_room` (jeder Location-Write:
`add_location`/`update_location`, Layout-Apply, World-Dev-Apply,
Content-Import). Reihenfolge: erst Grundfläche, dann Flure, beide am Ende der
Liste — Position trägt keine Bedeutung.

### 2.3 Opt-in Etage 0

`map3d.ground_corridor: bool` (Sanitizer `_sanitize_map3d`, Default fehlt =
aus). Gehört zum Gebäude-Block, weil die Frage „hat das Erdgeschoss eine
Diele" ein Gebäude-Fakt ist. Editor: Schalter im Etagen-Inspektor
(`PlanInspectorLevel`), nur auf Etage 0 sichtbar: „Ground floor has a hallway
between the rooms". Beschriftung darunter: „Doors without a target lead into
the hallway; mark the front door with target ‚outside'."

### 2.4 Charakter-Zustand

Unverändert: `current_room` trägt die Flur-Id. `ground_room_target` bleibt —
ein Charakter mit ungültigem Raum landet auf der Grundfläche, weil der Server
seine Etage nicht kennt. Ein Charakter, dessen Flur durch `ensure_floor_rooms`
verschwindet (letzter Raum der Etage gelöscht), wird beim nächsten
`ensure` auf die Grundfläche gesetzt: `ensure_floor_rooms` gibt die entfernten
Ids zurück, der Aufrufer (`update_location`) setzt betroffene
`character_state.current_room` und `utterances.room_id` auf `__ground__`
(dieselben zwei Tabellen wie die Grundflächen-Migration).

## 3. Türen und Szenen-Rezept (Server)

### 3.1 Türregel (`_doorways._rooms_of`)

Eine Tür/Passage mit **leerem `to`** auf Etage `L` bekommt als zweiten Raum
`__floor__L`, wenn dieser Flur existiert (Etage ≠ 0 mit Layout-Raum, oder
Etage 0 mit `ground_corridor`). Dann ist `outside = False`: **kein Hüllenloch,
kein Beitrag zu `no_building_entrance`.** Ohne Flur (Etage 0 ohne Opt-in)
gilt die heutige Regel: Außentür mit Loch. `to: "outside"` bleibt in jedem
Fall die ausdrückliche Außentür (heute schon Sonderfall in `_rooms_of`).

Die Prüfung „existiert der Flur" liest `rooms[]` der Location (der Raum ist
gespeichert), nicht die Opt-in-Logik ein zweites Mal.

### 3.2 Flur-Anker (`corridors[]` im Rezept, § B1)

Der Rezept-Payload bekommt einen Block `corridors: [{room_id, level,
anchor: [x, z]}]`, einen Eintrag je Flur-Raum, Metern im Szenen-Rahmen wie
`markers[].at`. Der Anker ist der Punkt, an dem Clients Figuren dieses Flurs
aufstellen und von dem Lift/Treppe „in den Flur" führen. Deterministisch, in
dieser Reihenfolge (`scene_recipe.floor_anchor`):

1. der Fahrstuhl-Haltepunkt (`map3d.elevator`) der Etage, wenn er innerhalb
   des aufgelösten Etagengrundrisses (`outline_source_level`) und außerhalb
   jeder Raumhülle dieser Etage liegt;
2. sonst das Treppen-Pad (Kopf oder Fuß, was auf dieser Etage liegt) mit
   derselben Bedingung, in Reihenfolge von `map3d.stairs`;
3. sonst der Punkt eines 0,5-m-Rasters über der Bounding-Box des
   Etagengrundrisses, der innerhalb des Grundrisses und außerhalb aller
   Raumhüllen liegt und den **größten Abstand** zur nächsten Kante (Hülle
   oder Grundriss) hat; Gleichstand → kleinstes x, dann kleinstes z;
4. gibt es keinen solchen Punkt (Räume füllen die Etage), dann der
   Mittelpunkt des Grundrisses — der Flur existiert dann als Zustand, aber
   Figuren stehen sichtbar in einem Raum; ein `problems[]`-Befund
   `corridor_without_floor` (`level`) sagt es dem Autor.

Ohne Etagengrundriss (kein `outline`, keine Boundary) gibt es keine Platte und
keinen Anker: kein `corridors[]`-Eintrag, der Flur existiert nur als Zustand.

### 3.3 Spieler-Payload `GET /play/scene → rooms[]` (§ A14)

Jeder Eintrag bekommt zusätzlich `level: int|null` (Layout-Level, Flur-Level,
0 für die Grundfläche, null für einen Raum ohne Layout) und
`is_floor: bool`. `build_avatar_rooms` liefert beides; `check_access` prüft
den Flur wie jeden Raum (eine Block-Regel kann „Kellerflur" sperren).

### 3.4 Befunde (`_problems`)

Flur-Räume sind aus `rooms_without_layout` und `room_outside_level_outline`
ausgenommen (wie `is_ground`). Neu: `corridor_without_floor` (§ 3.2 Nr. 4).
Unverändert: `no_building_entrance` — mit Erdgeschoss-Flur greift er, sobald
keine Tür `to: "outside"` trägt und keine Hüllentür (§ 6) existiert; genau
das ist die Türkontrolle, die der User nach dem Opt-in macht.

### 3.5 Einmal-Migration (`migrate_floor_rooms_once`)

world_kv-Marker `migration.floor_rooms_v1`. Für jede Location
`ensure_floor_rooms` (Etage 0 nur mit Opt-in, also zu Beginn nie). Log je
Location: Anzahl angelegter Flure und Anzahl der Türen auf Etagen ≠ 0 ohne
`to`, die ihr Hüllenloch verlieren (Entscheidung 2, sichtbar im Boot-Log).
Keine Charakter-Verschiebung nötig.

## 4. Weitere Server-Verbraucher

| Stelle | Änderung |
|---|---|
| `content_io` Export/Import | reservierte Ids bleiben (`is_floor_room` neben `GROUND_ROOM_ID`, Zeile ~935); Import ruft `ensure_floor_rooms` |
| `layout_apply.py`, `world_dev.py` | Flur wie Grundfläche ausnehmen (kein Layout, kein LLM-Raum) |
| `describe_room_skill` | darf keinen neuen Raum anlegen, dessen Name einem Flur-Standardnamen der Location gleicht; Flur-Räume zählen nicht gegen `max_custom_rooms`; Beschreibung eines Flurs darf gesetzt werden |
| `rules._names_every_room` | unverändert — der Flur zählt mit, eine Location-weite Sperre muss ihn nennen (konsistent mit der Grundfläche). RulesTab bietet ihn an |
| `get_arrival_room_id`, `get_entry_room_id` | unverändert; **`__floor__0` ist als `entry_room` erlaubt** (Ankunft in der Diele), Flure anderer Etagen nicht (Editor bietet sie nicht an, Sanitizer verwirft sie) |
| `boundary_entry` | unverändert |
| Prompts (`get_room_name`, `elsewhere_block`, Raumliste der Bewegungs-Skills) | Flur erscheint mit seinem Namen wie die Grundfläche; keine Template-Änderung |
| Szenen-Hintergrund (`world.py` ~2012) | kein Sonderfall: ohne raumgetaggte Bilder greifen die ungetaggten Location-Bilder (das Innere) |
| `room_entry` Begrüßung, `outfit_compliance`, Party, Reise-Engine, `nav_grid` | unverändert (geprüft) |

## 5. Clients

### 5.1 3D-Client (`client3d/`)

- `tile.roomLevels` / `tile.roomCenters` für Flur-Räume aus `corridors[]`
  (Anker = Mittelpunkt). Damit funktionieren Figurenplatzierung
  (`roomSlot` um den Anker statt Hof), Etagenfilter `wrongStorey`,
  Türgatter-Etage und Etagen-Folge ohne Sonderfall. Der Sonderfall „nur die
  Grundfläche ist Etage 0" bleibt für die Grundfläche.
- Raumwechsel-Heuristik (`main.ts`, Kandidatenbildung vor
  `nearestRoomSwitch`): außerhalb jedes Raum-Rechtecks →
  auf der eigenen Etage `L ≠ 0` der Flur `__floor__L` (Kandidat mit
  `center = pos`, wie heute die Grundfläche); auf Etage 0 mit Flur: innerhalb
  des Etagen-0-Grundrisses der Flur, außerhalb die Grundfläche; ohne Flur wie
  heute. Gesperrter Flur = kein Kandidat (wie gesperrte Grundfläche).
  `insideOutline(tile, level, pos)` liest das Platten-Polygon der Etage aus
  dem Rezept — nichts wird neu hergeleitet.
- `elevator.ts` / `stairs.ts`: Zielraum auf der Zieletage = ihr Flur, wenn
  vorhanden, sonst nächster Raum (heutige Regel). `elevatorLevels`: ein Flur
  zählt als Raum. Reine Funktionen, Zahlen in
  `client3d/scripts/smoke_walk_math.mjs`.
- NPC-Stationen (Tür → Lift/Treppe → Tür): unverändert; Ziel Flur hat keine
  Zieltür, die Figur läuft zum Anker.

### 5.2 Game-Admin (`frontend/`)

- `worldTypes.ts`: `isFloorRoom(id)`, `floorRoomLabel(room, t)`.
- `WorldTab`/`LocationEditor`/`RoomEditor`: Flur-Räume wie die Grundfläche —
  nicht löschbar, nicht anlegbar, Name und Beschreibung editierbar, kein
  Layout-Bereich; `entry_room`-Auswahl bietet nur `__floor__0` an.
- `PlanInspectorLevel`: Opt-in-Schalter (§ 2.3), nur auf Etage 0.
- `PlanOpeningStrip`: Ziel-Anzeige einer Tür ohne `to` lautet auf einer Etage
  mit Flur „→ <Flurname>" statt „→ outside"; Auswahl „outside" schreibt
  `to: "outside"`.
- `PlanRoomPicker`/`RoomLayoutEditor`: Flur nicht als Planziel.
- `RulesTab`: Flur in der Raumauswahl (kommt über `rooms[]` automatisch;
  prüfen, dass das Label den Standardnamen zeigt).
- Alle neuen Strings Englisch + `t()`; deutsche Strings der berührten
  Abschnitte mitübersetzen.

### 5.3 Player-UI (`packages/player-ui`, `frontend/src/player`)

Flur als Raum-Chip mit seinem Namen (kommt über `rooms[]`); `is_floor` nur für
ein Icon/Tooltip, keine eigene Logik.

## 6. Hüllentür (Phase 3)

Ein Flur hat keine Wände, also keine Öffnungen. Auf Etagen ≠ 0 ist das
unerheblich. Ein Erdgeschoss mit Diele braucht aber eine Haustür **in der
Diele**, nicht in einem Raum. Deshalb:

- `map3d.hull_openings: [{level, edge, at, width_m, height_m, type,
  door_prop?, hinge?}]` — dieselben Felder wie eine Raumöffnung
  (`_sanitize_opening`), `edge` = Kantenindex des **aufgelösten**
  Etagengrundrisses (§ A6 `level_outlines`-Kaskade), `at` Bruchteil entlang
  der Kante. Max. 8 je Location. Sanitizer verwirft Einträge auf Etagen ohne
  Flur.
- Server: `_contour_walls` erhält je Hüllentür einen `outside_doors`-Eintrag
  (Punkt auf der Kante, Normale = Außennormale der Kante, keine Projektion
  nötig); `doorways[]` bekommt den Eintrag mit `rooms: [__floor__L]`,
  `outside: true`, `along` = Kantenrichtung. `no_building_entrance` zählt
  Hüllentüren auf Etage 0 mit. Türblatt/Prop wie bei jeder Außentür.
- Client: Türmarker, Schwelle, Türschwung und das Eintritts-Angebot lesen
  `doorways[]` — keine Änderung außer der Prüfung, dass `rooms[0]` ein Flur
  sein darf.
- Editor: im Öffnungs-Streifen der Etage 0 (nur mit Flur) ein Modus „Door on
  the building outline": Klick auf eine Konturkante setzt `edge`/`at`;
  Breite/Höhe/Typ/Prop wie bei Raumöffnungen.

## 7. Phasen und Abnahme

Jede Phase endet sichtbar; offene Punkte werden je Phase aufgelistet.

| Phase | Inhalt | Sichtbare Abnahme |
|---|---|---|
| P1 Server-Kern | § 2, § 3, § 4, Smoke, Doku § A13b + Änderungen § A6/§ A14/§ B1 | Kellerflur steht in `rooms[]` und in der Raumliste; Kellertüren schneiden in der Admin-Vorschau kein Hüllenloch mehr; Boot-Log nennt Migration; `curl /play/locations/{id}/scene` zeigt `corridors[]` |
| P2 Clients | § 5 | Avatar tritt im Keller aus dem Raum und der Chip wechselt auf „Flur, Keller"; Lift landet im Flur; NPC im Flur steht am Anker, nicht im Hof; Opt-in-Schalter auf Etage 0 |
| P3 Hüllentür | § 6 | Haus mit Diele: Haustür auf der Kontur gezeichnet, Loch in der Hülle, Eintreten durch die Haustür in die Diele |

Reihenfolge P1 → P2 → P3; P3 kann nach P2-Abnahme entfallen, wenn der User
die Haustür-über-Raumtür-Lösung (`to: "outside"`) als ausreichend erklärt.

## 8. Verifikation (§ B5a: Zahlen, keine Screenshots)

- `scripts/smoke_floor_rooms.py`: `floor_levels` (mit/ohne Opt-in),
  `ensure_floor_rooms` in beide Richtungen, `_rooms_of`-Regel für alle drei
  `to`-Zustände × Etage 0/≠0 × Opt-in, `floor_anchor` mit handgerechneten
  Beispielen (Lift im Flur; Lift im Raum → Treppen-Pad; nur Raster → Punkt
  mit maximalem Abstand; volle Etage → Mittelpunkt + Befund), Türzählung der
  Migration.
- `client3d/scripts/smoke_walk_math.mjs`: Kandidatenwahl der
  Raumwechsel-Heuristik (Etage −1 außerhalb Rechteck → Flur; Etage 0 mit
  Opt-in innerhalb/außerhalb Grundriss), `elevatorTargetRoom`/`nearestRoomAt`
  mit Flur, `elevatorLevels` mit Flur-only-Etage.
- P3: Hand-Rechnung der Hüllentür-Position aus `edge`/`at` gegen
  `doorways[].at_world` und das Konturstück-Paar in `walls[]`.
- Bestehende Smokes (`smoke_scene_recipe.py`, `smoke_ground_room.py`,
  `smoke_game_time_lint.py`) laufen weiter; `npm run lint`, `npm run build`,
  `npm run build -w client3d`.

## 9. Entwicklungsidee (nicht gebaut)

**Flur-Möblierung.** Der Flur als Furnish-Ziel mit der Fläche „aufgelöster
Etagengrundriss minus Raumhüllen minus Lift-/Treppen-Pads" als
Solver-Polygon (konkav), zusammengesetzte Job-Id `__floor__<L>@<location>`
wie beim Hof, reduziertes Layout (`props[]`/`markers[]`, Rahmen = Location),
Wand-Montage an Hüllen- und Konturwänden. Voraussetzung: der Anker aus § 3.2
weicht dann den Marker-Plätzen. Eintrag auch in
`development_instructions/analyse-etagen-flur.md` § 6.
