# Backend-Anforderungen an anima-verse (aus Sicht des 3D-Clients)

Nummerierte Wünsche des 3D-Map-Clients an die anima-verse-API. Jeder Eintrag:
Motivation, Vorschlag, aktueller Workaround im Client, Status.
Konvention: Der Client funktioniert immer auch OHNE die Erweiterung (graceful
degradation) — Einträge sind Verbesserungen, keine Blocker.

Status: `offen` · `drüben in Arbeit` · `umgesetzt (API-Version/Datum)` · `verworfen`

---

## AV3D-1: 3D-Metadaten pro Location — umgesetzt (Backend 2026-07-11, Client-Support eingebaut)

> Client wertet `map3d {style, floors, color}` aus (Priorität über Terrain und
> Namens-Heuristik). Verifiziert bisher nur per injizierten Testdaten — in der
> Kai-Welt waren noch keine Werte gesetzt; Feldform bitte gegenprüfen, falls
> das Backend andere Keys emittiert.

- **Motivation:** Gebäudedarstellung (Stockwerke, Grundfläche, Stilklasse) wird
  derzeit aus Namens-Keywords + Raumanzahl geraten.
- **Vorschlag:** optionales Meta-Feld `map3d` an der Location, z.B.
  `{"floors": 6, "footprint": [1,1], "style": "tower|house|shop|generic", "color": "#8fa3b0"}`.
  Editierbar im Game-Admin (Location-Editor), Template-fähig wie andere Felder.
- **Workaround:** Heuristik in `src/scene/tiles.ts` (`detectStyle`).

## AV3D-2: Raum-Layout + Raum-Modelle — GELIEFERT, Client angebunden (2026-07-16)

- **Umsetzung Backend:** `layout` am Raum-Objekt (`{x, y, w, d, level, exit}`),
  Modelle unter `GET /play/rooms/{room_id}/model[/meta]`; das Meta enthält
  `rotation {x,y,z}` (Grad, im Admin einstellbar) zur Orientierungs-Korrektur.
- **Client:** Layout-Räume ersetzen das Auto-Grid (Etagen via level × 3 m),
  Raum-Modelle werden auf die Bodenplatten gesetzt (hochkant gelieferte
  Reliefs legt der Client flach, solange keine explizite rotation gesetzt
  ist); Figuren folgen der Etagenhöhe und laufen bei Raumwechseln über die
  exit-Punkte. Räume ohne Layout/Modell bleiben Auto-Grid/Platte.
- **Nachtrag-Wunsch (2026-07-17): `signature` im Modell-Meta** (Räume UND
  Gebäude; z.B. Hash oder created_at) — wie bei den Charakter-Modellen.
  Ohne sie merkt der laufende Client nicht, dass ein Modell neu generiert
  wurde (Layout-/Meta-Änderungen erkennt er, neue Modell-DATEIEN nicht);
  heute hilft nur ein Reload. Mit signature frischt der Client automatisch
  auf. Ebenso nützlich: Layout-Änderungen erreichen den Haupt-Client erst
  beim Reload (/world/locations wird einmalig geladen) — mit signature am
  Location-Objekt (oder einem Bump-Feld in der Worldmap) könnte er gezielt
  nachladen.

Ursprüngliche Anforderung:

- **Motivation:** Räume haben keine Position/Größe; der Client legt sie als
  Auto-Grid in den Gebäude-Footprint — jeder Grundriss sieht gleich aus.
  Mit echten Layoutdaten wird die Innenansicht wiedererkennbar (Terrasse
  südlich, Kantine im Erdgeschoss, Apartment im 12. Stock) und Figuren
  stehen dort, wo sie wirklich sind.
- **Erwartung Layout:** pro Raum Position/Größe relativ zum Gebäude
  (x/y/Breite/Tiefe als Fraktionen 0..1), **`level`** (Etage, ganzzahlig,
  mehrere Räume pro Etage und mehrere Etagen pro Location — Tower: Raum
  im 4. und im 10. Stock) und `rotation` (Grad). Form der Daten
  entscheidet ihr.
- **Erwartung Modelle (analog AV3D-9):** jeder Raum = generiertes Bild +
  daraus generiertes 3D-Modell (Innenansicht, offen von oben), Endpoints
  analog zu den Gebäude-Modellen (`meta` mit 404-Normalfall + GLB mit
  ETag, z.B. `/play/rooms/{room_id}/model[/meta]`); Platzierung wie bei
  Gebäuden über die Layout-Felder.
- **Ausgangspunkt statt Treppen/Aufzüge:** Vertikal-Verbindungen werden
  vorerst ignoriert; pro Raum ein `exit: [x, y]` (Fraktion der
  Raum-Grundfläche), damit der Client Figuren beim Betreten/Verlassen
  plausibel bewegt.
- **Pflege:** am sinnvollsten ein kleiner Grundriss-Editor im Game-Admin
  (Rechtecke ziehen + Etagen-Wahl + Ausgangspunkt) — analog zum
  bestehenden Map-Editor für Location-Positionen.
- **Fallback bleibt:** ohne Layout weiterhin Auto-Grid; ohne Raum-Modell
  weiterhin die einfache Bodenplatte.
- Vollständiger Vertrag: `docs/schnittstellen-3d.md` → „Raum-Layout &
  Raum-Modelle".

## AV3D-3: `location_changed`-Event im SSE-Stream — offen

- **Motivation:** NPC-Bewegung wird per Poll (3 s) entdeckt; Bewegungen springen
  dadurch und Reisen haben keine Dauer-Information.
- **Vorschlag:** im bestehenden Event-Stream (`app/routes/events.py`) ein Event
  `{"type":"location_changed","character":..., "from_id":..., "to_id":...,
  "room_id":..., "eta_seconds":...}`; analog `activity_changed`.
- **Workaround:** Polling `/play/worldmap` + Lerp-Animation im Client.

## AV3D-4: Isometrische Map-Icons (zweiter Icon-Slot) — offen

- **Motivation:** `map-icon-2d` ist top-down; für die 3D-Schrägansicht wären
  ¾-Perspektive-Sprites (klassischer AoE-Look) als Alternative zu prozeduralen
  Gebäuden attraktiv.
- **Vorschlag:** `image_prompt_map`-Pipeline um einen Slot `map-icon-iso`
  erweitern (gleiche Generierung, anderes Prompt-Template + Transparenz/rembg).
- **Workaround:** prozedurale Gebäude im Client.

## AV3D-5: 3D-Charakter-Assets pro Charakter (GLB/VRM) — spezifiziert, drüben umsetzbar — ⭐ Kernwunsch

> **Schnittstellen & Erwartungen:** `docs/schnittstellen-3d.md` — die
> Implementierung entscheiden die jeweiligen Sessions. Pipeline verifiziert
> mit KiraFast/BiancaHigh2.

- **Motivation:** Der Client soll NPCs als animierte 3D-Figuren zeigen. Die
  Erzeugung/Ablage gehört ins Backend (analog Galerie/Outfit-Bildern), der
  Client konsumiert nur.
- **Vorschlag, minimal (Stufe 1 — Upload):**
  - Ablage `characters/<name>/model/` (GLB oder VRM), Upload im Game-Admin.
  - `GET /characters/{name}/model` → Modell-Bytes; 404 wenn keins → Client
    fällt auf Portrait-Marker zurück.
  - `GET /characters/{name}/model/meta` → `{"format":"vrm|glb","scale":1.0}`.
  - **Konkretisiert nach Pipeline-Praxis (2026-07-11):**
    - Format: GLB mit Mixamo-Skelett (ComfyUI: TRELLIS.2 → ComfyUI-UniRig/MIA
      liefert genau das). Dateien sind 20–30 MB → unbedingt `ETag` +
      `Cache-Control` (Client cacht aggressiv, Modelle ändern sich selten).
    - `meta` zusätzlich: `{"rig":"mixamo|custom|none","source":"upload|generated"}`
      — Client entscheidet daran, ob geteilte Clips anwendbar sind.
    - Upload-Validierung: GLB-Magic + hat Skin/Joints (sonst Hinweis
      „ungeriggt — Figur wäre statisch").
    - Keine Orientierungs-/Größen-Pflicht: Client normalisiert selbst
      (Z-up/Y-up, Skalierung, Boden-Offset bereits implementiert).
- **Vorschlag, Ausbau (Stufe 2 — Generierung):** neuer Backend-Typ
  „3D-Asset-Generierung" in der BACKEND_REGISTRY (Bild-zu-3D + Auto-Rigging,
  lokal gehostet oder API-Dienst), Task-Queue-Job `character_model`:
  Referenzbild → Mesh → Rigging → Ablage wie Stufe 1.
  **Recherche liegt vor → `docs/research-bild-zu-3d.md`** (Kurzfassung:
  Hunyuan3D in der EU lizenzblockiert; TRELLIS.2 lokal für nicht-kommerzielle
  Betreiber, Tripo/Meshy als API-Alternative; Rigging selbsthostbar via
  Make-It-Animatable/UniRig, beide MIT).
  **Präzisierung Zielbild (2026-07-11):**
  - Quelle = EIN kanonisches Ganzkörper-Referenzbild pro Charakter/Outfit
    (humanoid: neutrale A-Pose; **Tiere: eigenes Prompt-Template** —
    symmetrische Standpose auf allen Vieren, Kopf geradeaus in
    Körperrichtung statt zur Kamera, 3/4-Ansicht; das humanoide
    A-/T-Pose-Template passt für Quadrupeden nicht. Ggf. eigener
    Prompt-Slot analog `image_prompt_map`, damit die Bildpipeline es
    gezielt erzeugen kann).
  - Outfits: pro Outfit(-Variante) ein GLB (`model/<outfit>.glb`), Server
    liefert das zum aktuellen Outfit passende; Client-Cache via ETag.
  - Expressions/Mood: NICHT pro Stimmung neu generieren (Blendshapes liefern
    Auto-Pipelines nicht zuverlässig) — Mood bleibt Sache von Animation/
    Haltung im Client bzw. später VRM-Expressions; Expression-Bilder bleiben
    das Medium für Chat-UI/Environment-Panel.
  - Rigging-Service: Make-It-Animatable läuft als Gradio-App → Anbindung über
    das vorhandene `gradio_client`-Muster (wie TTS-Backends).
- **Workaround:** Portrait-Kreis-Sprites; Stufe-1-Beweis im Client läuft mit
  lokal mitgelieferten Beispiel-GLBs.

## AV3D-6: Aktivitäts→Animations-Mapping — offen

- **Motivation:** `activity` ist Freitext („Coffee", „Meeting"); der Client
  braucht eine Abbildung auf Animations-Kategorien (idle/sit/walk/drink/…).
- **Vorschlag:** Activities haben bereits Datensätze im Backend — optionales
  Feld `animation: "sit|stand|walk|lie|dance|…"` je Activity; Fallback `idle`.
- **Workaround:** Keyword-Mapping im Client.

## AV3D-7: Expliziter Terrain-Typ pro Location — umgesetzt (Backend 2026-07-11, Client-Support eingebaut)

> `terrain` wird in `/play/worldmap` emittiert (bestätigt). Client matcht
> tolerant de/en (`water|see|lake|…`, `forest|wald|…`, `road|street|…`,
> `grass|wiese|…`); nicht-passable Natur-Locations (See!) rendern als
> Naturfläche mit Raum-Slabs statt als Gebäude. In der Kai-Welt sind noch
> keine Werte gesetzt — z.B. Mondscheinsee auf `lake` setzen.

- **Motivation:** Wald/Straße wird per Namens-Match erkannt — bricht bei
  anderssprachigen Weltennamen. Praxisbeleg (Kai-Welt, 2026-07-11): der See
  „Mondscheinsee" rendert als braunes Bürogebäude mit fünf Zimmern, weil er
  eine nicht-passable Location ohne Terrain-Info ist.
- **Vorschlag:** optionales Feld `terrain: "grass|forest|road|water|sand|rock"`
  an (Template-)Locations.
- **Workaround:** Regex auf den Namen in `detectStyle()`.

## AV3D-8: Worldmap um Raum & Stimmung erweitern — umgesetzt & verifiziert (Backend 2026-07-11)

> `room_id` + `mood` kommen in `/play/worldmap.characters` (gegen Kai-Welt
> bestätigt). Client nutzt `room_id` direkt für die Raum-Platzierung; der
> `/characters/at-location`-Zweitpoll läuft nur noch als Fallback für ältere
> Backends. `mood` erscheint im Info-Panel.

- **Motivation:** `/play/worldmap` liefert pro Charakter keinen Raum und keine
  Stimmung; der Client pollt dafür zusätzlich `/characters/at-location`.
- **Vorschlag:** optionale Felder `room_id`, `mood` im `characters`-Eintrag von
  `/play/worldmap` (billig, Daten liegen im selben Store).
- **Workaround:** Zweit-Poll nur für die herangezoomte Location.

## AV3D-9: 3D-Modelle für Locations — GELIEFERT (2026-07-15), Client angebunden (2026-07-16)

- **Umsetzung Backend:** `GET /play/locations/{id}/model/meta` →
  `{format:"glb", rig:"none", url}` | 404; GLB-Bytes unter
  `GET /play/locations/{id}/model` (mit ETag). Generierung/Status im
  Admin unter `/world/locations/{id}/model3d/*` (Backend Trellis2-Object-Low).
- **Client:** `src/scene/buildings.ts` lädt lazy, normalisiert und ersetzt
  die prozedurale Hülle; 404-Retry alle 60 s (frisch generierte Gebäude
  erscheinen ohne Reload).
- **Backend-Wunsch (klein):** Während eine Generierung läuft, lieferte
  `/model` kurz das Referenz-PNG mit 200 statt 404 — der Client fängt das
  ab (GLB-Parse schlägt fehl → Retry), sauberer wäre 404 bis zum fertigen GLB.
- **Backend-Wunsch (Nachtrag 2026-07-16):** Ausrichtung/Größe pro Location
  einstellbar machen — zwei neue `map3d`-Felder, die der Client bereits
  liest: `rotation` (Grad um die Hochachse; Fallback: `map_rotation_2d`)
  und `size` (Kachel-Anteil 0..1, Default 0.92). Pflege idealerweise im
  Map-Editor des Game-Admin. **UMGESETZT (2026-07-16), verifiziert.**
- **Qualitäts-Hinweis Referenzbilder:** Aus Top-down-Kartenbildern
  (`image_prompt_map`) macht Trellis2 flache Reliefs statt Gebäude mit
  Volumen (beobachtet: Academy, Rohhöhe 0,18 bei Grundfläche ~1×1).
  Für plastische Gebäude braucht die Generierung eine **Außenansicht als
  Referenz** (3/4-Perspektive, Gebäude freigestellt) — analog zum eigenen
  Prompt-Slot der Charaktere.

Ursprüngliche Anforderung:

- **Motivation:** Die Charaktere sind fotorealistisch generiert, die Gebäude
  sind noch prozedurale Kisten aus der Prototyp-Phase — das beißt sich.
  Locations sollen dieselbe Pipeline nutzen wie Charaktere.
- **Erwartung:** analog zu AV3D-5 ein 3D-Modell pro Location
  (`GET /world/locations/{id}/model3d` o.ä.), erzeugt aus dem bereits
  vorhandenen `image_prompt_map` (bzw. einem Referenzbild der Location).
  Kein Rig nötig (`rig: "none"`), Textur eingebettet, dezimiert.
- **Wichtig für die Zoomstufen:** Das Modell ist die **Außenansicht**. Beim
  Reinzoomen blendet der Client es aus und zeigt die Räume (AV3D-2) — die
  Innenansicht kommt also NICHT aus dem Modell. Ein Modell ohne Innenraum
  ist genau richtig.
- **Erwartung an die Form:** aufrecht stehendes Gebäude, Grundfläche
  ungefähr quadratisch (eine Kachel = eine Location); Skalierung egal,
  normalisiert der Client.
- **Fallback bleibt:** ohne Modell weiterhin die prozeduralen Formen
  (Stil aus `map3d.style`/`terrain`).

## AV3D-10: Game-Admin — Location-Reiter „Floorplan" — angefordert (2026-07-16), korrigiert (2026-07-17)

- **Neuer 3. Reiter „Floorplan"** pro Location: **links der Grundriss-Editor**
  (zieht aus dem 3D-Reiter um), **rechts eine 3D-Vorschau**.
- **KORREKTUR (2026-07-17): Die 3D-Vorschau ist die VORHANDENE
  Admin-Vorschau, korrekt erweitert** — die zwischenzeitlich empfohlene
  iframe-Einbettung der Client-Seite (`floorplan.html`) war ein Vorschlag
  des 3D-Clients, **nie Anforderung** — falls schon eingebaut, wieder
  entfernen. Die Admin-Vorschau soll zeigen: Räume an Layout-Position mit
  Etagen, Raum-Modelle mit `rotation`/`offset_y`, Exit-Punkte. Damit sie
  exakt dasselbe rendert wie der Spiel-Client, ist die
  **Platzierungs-Semantik jetzt als Vertrag dokumentiert**:
  `docs/schnittstellen-3d.md` → „Platzierungs-Semantik (Referenz für
  Vorschauen)". `floorplan.html` bleibt nur als Debug-Werkzeug des Clients.
- **3D-Reiter:** die Bilder rücken hoch an die Stelle, wo bisher der
  Grundriss-Editor war.
- Die Modell-Justierung der Räume (`offset_y`, `rotation`) idealerweise
  ebenfalls auf den Floorplan-Reiter neben die Vorschau — kein
  Fensterwechsel beim Einstellen.

## AV3D-11: Generische Animations-Marker pro Raum — angefordert (2026-07-17)

- **Motivation:** Sitzende/liegende Figuren sollen auf Stühlen/Betten
  landen. Der Client rät Möbel heuristisch aus der Modell-Geometrie —
  funktioniert oft, aber nicht immer; kuratierte Marker sind verlässlich.
- **Erwartung:** optionale Marker in den Raum-Layout-Daten, generisch über
  das Animations-Vokabular (nicht nur sit/sleep — jedes Clip-Kind):
  `markers: [{ "at": [x, y], "animation": "sit" }, ...]`
  (`at` als Fraktion der Raum-Grundfläche).
- **Pflege:** im Grundriss-Editor (Klick + Animations-Kind aus
  `/assets/animation-clips`, dynamisch). Die Admin-Vorschau zeigt an
  jedem Marker idealerweise eine Testfigur mit der Animation
  (Platzierungs-Semantik und Figuren-Maßstab: `schnittstellen-3d.md`).
- **Erweiterung (2026-07-17) — Marker-Editor statt nur Setzen/Löschen:**
  - Marker-Felder ergänzen: **`rotation`** (Grad; Blickrichtung der Figur:
    0 = Süd, 90 = Ost, 180 = Nord, 270 = West) und **`offset_y`** (Meter,
    ±; additiv zur vom Client abgetasteten Auflagehöhe). Der Client liest
    beide bereits.
  - **Jeder Marker bekommt eine Nummer** (= Array-Position, 1-basiert);
    die Nummer wird in der Vorschau über der Figur angezeigt.
  - **Marker-Liste im Editor:** Marker auswählen und dann Löschen,
    Position neu setzen, **Ausrichtung drehen (Schieberegler)** und
    **Höhe verändern (Schieberegler)**.
  - **Vorschau: echte Mixamo-Figur mit der jeweiligen Animation** statt
    der grünen Platzhalter-Figuren — Figuren und Clips sind im Server
    vorhanden; Figuren-Maßstab in Räumen: 1/3 (siehe
    Platzierungs-Semantik).
- **Client-Verhalten:** Marker schlagen die Heuristik; Höhe ermittelt der
  Client selbst (Abtastung). Ohne Marker: Heuristik (Sitz-/Liegeflächen
  aus der Modell-Geometrie) — bereits eingebaut.
- **Fallback bleibt:** ohne Marker und ohne Modell stehen Figuren auf der
  Bodenplatte wie bisher.

## AV3D-12: Gebäude-Grundriss zeichnen + Fahrstuhl — angefordert (2026-07-17)

- **Motivation:** Der Grundriss im Editor ist bisher ein Viereck. Gebäude
  sollen einen echten, selbst gezeichneten Grundriss bekommen; die Räume
  darin bleiben Rechtecke. Wände rendert der Client automatisch pro Etage.
- **Erwartung Server (Editor):**
  - Grundriss **zeichnen** statt Rechteck: Punkte setzen / Linien
    verbinden zu einem geschlossenen Polygon; Ablage als
    `map3d.outline: [[x, y], ...]` (Fraktionen des 8×8-Referenzquadrats,
    gleiche Fläche wie die Raum-Layouts).
  - **Fahrstuhl platzieren** (ein Klick auf einer Etage):
    `map3d.elevator: [x, y]` — gilt automatisch für alle Etagen.
  - **Checkbox „immer sichtbar" pro Raum** → `layout.always_visible`
    (bool, Default false): Raum wird unabhängig von der Innenansicht
    dauerhaft gezeigt — für Outdoor-Räume, die nicht schon im
    Gebäude-3D-Modell abgebildet sind. Client liest das Feld bereits.
- **Client (bereits eingebaut, mit Testdaten verifiziert):** pro genutzter
  Etage Bodenplatte in Konturform + Wände (Tür im EG am südlichsten
  Wandstück; Obergeschosse halbtransparent); Fahrstuhl als Schacht mit
  Plattform je Etage; Figuren nutzen ihn beim Etagenwechsel (Raum-Ausgang
  → Fahrstuhl → vertikale Fahrt → weiter; im EG durch die Tür hinaus).
- **Details/Vertrag:** `docs/schnittstellen-3d.md` → „Gebäude-Grundriss &
  Fahrstuhl".
