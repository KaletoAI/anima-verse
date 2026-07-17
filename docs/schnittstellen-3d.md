# Schnittstellen & Erwartungen: 3D-Charaktere

Stand 2026-07-13. Nur die Verträge zwischen den Komponenten — die
Implementierung entscheidet die jeweilige Session selbst.

## LLM-Gateway → anima-verse

**Auftrag:** anima-verse beauftragt ein Charakter-Modell und übergibt dabei
ein Referenzbild sowie die Workflow-Wahl. Welche Workflows es gibt und
welche Parameter sie haben, definiert und meldet das Gateway (Discovery) —
anima-verse kodiert nichts davon fest.

**Ergebnis:** die **Rig-Dateien** des Laufs plus minimale Metadaten
(Workflow-Kennung, Referenzbild, Hash). Ein ComfyUI-Lauf erzeugt mehrere
Dateien — geliefert wird nur, was der Client wirklich braucht:

| Rig-Typ | zu liefern | verwerfen |
|---|---|---|
| **humanoid** (MIA-Rigger) | **1 Datei:** `*_mia.glb` — Rig, Mesh und Texturen sind darin eingebettet | `*_mia.fbx`, `*.fbm/`, texturiertes/refined Zwischen-Mesh, lose PNGs |
| **generic** (UniRig, z.B. Tiere) | **2 Dateien:** das geriggte `*.fbx` **+** das basecolor-Bild (PNG oder JPEG — JPEG bevorzugt, außer die Textur braucht Alpha; die FBX bettet die Textur nicht ein) | dieselben Zwischenstufen; metallic-Bild optional/verzichtbar |

**Der Rig-Typ muss mitgeliefert werden** (`rig: "mixamo" | "generic"`) — er
entscheidet, ob die geteilte Animations-Bibliothek anwendbar ist:
`mixamo` = Figur läuft/sitzt, `generic` = keine passenden Clips (Client zeigt
ein prozedurales Idle).

**Erwartungen an die Dateien, damit der Client sie nutzen kann:**
- **humanoid:** ein Skin mit **Mixamo-Skelett** (52 Joints, `mixamorig:`-Namen)
  und **eingebetteter Textur**. Ein 2×2-Pixel-Bild als Textur ist ein bekannter
  Node-Fehlerfall — dann ist der Lauf gescheitert, kein Ergebnis.
- **generic:** FBX mit Skin und UVs; die mitgelieferte PNG muss zu genau
  diesem Mesh passen (gleicher Lauf, keine Dezimierung dazwischen).
- web-taugliche Größe (Richtwert ≤ ~30 MB; dezimiertes Mesh, Textur ≤ 2048)
- Orientierung/Skalierung egal — normalisiert der Client

## anima-verse → 3D-Client

```
GET /characters/{name}/model3d      → Metadaten mit Datei-URL(s) | 404
GET /assets/animation-clips         → [{ "kind": "walk", "url": "…" }, …]
```

**Erwartungen:**
- **404 ist ein normaler Zustand** (Client zeigt Portrait-Marker) — kein Fehler
- Die Metadaten nennen **Format und Rig-Typ** und — im `generic`-Fall — eine
  **zweite URL für die Textur** (`format: "fbx"`, `texture_url: …`).
  Humanoide bleiben der einfache Fall: ein GLB, eine URL.
- **ETag/Caching** bei den Modelldateien (groß, ändern sich selten)
- Clips: Mixamo-FBX („Without Skin"), **alle aus derselben Quelle** —
  gemischte Skelett-Konventionen kippen die Figuren; `kind` ∈
  idle/walk/run/sit/dance/wave/… (erweiterbar, Client mappt Activities darauf)

## Locations: 3D-Modelle und Räume

### Gebäude-Modelle (AV3D-9) — geliefert & angebunden

Wie bei den Charakteren: ein 3D-Modell pro Location, erzeugt aus einem
Referenzbild (die Location hat mit `image_prompt_map` bereits eines).

```
GET /play/locations/{location_id}/model/meta  → { format, rig: "none", url } | 404
GET /play/locations/{location_id}/model       → GLB-Bytes (ETag)
```

**Erwartungen:**
- **Während eine Generierung läuft: 404**, keine Zwischenstände (beobachtet
  wurde kurz das Referenz-PNG mit 200 — der Client validiert und versucht
  später erneut, aber 404 wäre der saubere Vertrag).
- **Ausrichtung & Größe bestimmt der Server pro Location** über `map3d`
  in der Worldmap (der Client liest die Felder bereits):
  - `map3d.rotation` — Drehung um die Hochachse in Grad; fehlt sie, gilt
    `map_rotation_2d` (Modell dreht synchron zum 2D-Icon), sonst 0.
  - `map3d.size` — Grundflächen-Anteil an der Kachel (0..1, Default 0.92).
  - Pflege am sinnvollsten im Map-Editor des Game-Admin (Drehen/Skalieren
    am platzierten Gebäude, analog zur Location-Position).
  - Ohne diese Felder bleibt die Client-Heuristik: Z-up-Erkennung über
    Proportionen, keine Drehung, 92 % der Kachel.
- **Außenansicht**, kein Innenraum. Beim Reinzoomen blendet der Client das
  Gebäude aus und zeigt die Räume (s.u.) — die Innenansicht kommt NICHT aus
  dem Modell. Ein Gebäude ohne Interieur ist genau richtig.
- kein Rig nötig (`rig: "none"`), Textur eingebettet, Mesh dezimiert
- aufrecht stehend, Grundfläche ungefähr quadratisch (eine Karten-Kachel =
  eine Location). Skalierung/Orientierung egal — normalisiert der Client.
- **404 bleibt normal:** Locations ohne Modell rendert der Client weiterhin
  prozedural (aus `map3d.style` / `terrain`).

### Gebäude-Grundriss & Fahrstuhl (AV3D-12)

Der Grundriss des **Gebäudes** (nicht der Räume — die bleiben Rechtecke)
wird im Server-Editor **gezeichnet** (Linien/Punkte verbinden, beliebiges
Polygon statt Rechteck). Der **Client rendert daraus die Wände**, für jede
genutzte Etage.

Zwei Felder an der Location (`map3d`), der Client liest beide bereits:

- **`map3d.outline`**: `[[x, y], …]` — Polygonpunkte als Fraktionen des
  8×8-Referenzquadrats (dieselbe Fläche wie die Raum-Layouts), automatisch
  geschlossen. Client-Verhalten: pro genutzter Etage eine Bodenplatte in
  Konturform + Wände entlang der Kontur; Türöffnung im Erdgeschoss am
  südlichsten Wandstück; Obergeschosse halbtransparent, damit die
  Draufsicht aufs Erdgeschoss frei bleibt.
- **`map3d.elevator`**: `[x, y]` — Fahrstuhl-Position (Fraktion des
  Referenzquadrats). **Im Editor auf EINER Etage platziert, gilt er
  automatisch für alle.** Client-Verhalten: Schacht + Plattform auf jeder
  Etage; beim Etagenwechsel laufen Figuren Raum-Ausgang → Fahrstuhl,
  fahren vertikal zur Ziel-Etage und laufen dort weiter (im Erdgeschoss
  dann durch die Tür hinaus). Treppen gibt es weiterhin nicht.

### Raum-Layout & Raum-Modelle (AV3D-2, erweitert 2026-07-16)

Räume haben heute keine Position und keine Größe. Der Client legt sie als
Auto-Grid ins Gebäude — jeder Grundriss sieht gleich aus, und Figuren stehen
nicht dort, wo sie wirklich sind.

**Platzierung pro Raum (relativ zum Gebäude):** Die Felder hängen am
Raum-Objekt, das der Client heute schon liest (`/world/locations` →
`rooms`); die genaue Datenform entscheidet das Backend.
- **`level`** — Etage (ganzzahlig; 0 = Erdgeschoss, negativ = Keller).
  Eine Location kann Räume auf beliebigen Etagen haben (Tower: ein Raum
  im 4., einer im 10. Stock), und **mehrere Räume pro Etage** sind der
  Normalfall — beides muss die Datenform abbilden.
- Position und Größe als Fraktionen der Gebäude-Grundfläche
  (x, y, Breite, Tiefe im Bereich 0..1).
- `rotation` (Grad um die Hochachse) — Räume sind damit **genauso
  platzierbar wie die Gebäude selbst** (analog `map3d.rotation`/`size`).

**Raum-Modelle (analog zu den Gebäude-Modellen, AV3D-9):**
Jeder Raum besteht wie eine Location aus einem generierten Bild und dem
daraus generierten 3D-Modell (Innenansicht ohne Decke bzw. offen von oben,
damit die Draufsicht funktioniert).

```
GET /play/rooms/{room_id}/model/meta  → { format, rig: "none", url } | 404
GET /play/rooms/{room_id}/model       → GLB-Bytes (ETag)
```

- Pfadform frei (auch verschachtelt unter der Location möglich) — wichtig
  sind Meta-Endpoint mit 404-Normalfall und ETag auf der Modelldatei.
- Meta-Felder zur Feinjustierung am Modell (Admin-Regler, Client liest beide):
  `rotation {x,y,z}` (Grad) und **`offset_y`** (**Meter** = Welt-Einheiten,
  ± — hebt/senkt das Modell, z.B. Park ins Gelände; sinnvoller Bereich
  ca. ±0,5, sichtbar wird es ab ~0,1).
- Texturen in Raum-/Gebäude-GLBs gern als **JPEG einbetten** (statt PNG) —
  der Client liest beides; JPEG drittelt die Dateigröße. Humanoide GLBs
  bleiben wie sie sind (wenige, gecacht — kein Umpacken nötig).
- **404 bleibt normal:** ohne Modell rendert der Client den Raum weiter
  als einfache Bodenplatte (heutige Slabs).
- Während einer Generierung: 404, keine Zwischenstände (wie AV3D-9).

**Animations-Marker (generisch; Basis geliefert, erweitert 2026-07-17):**
- Optionale Marker pro Raum in den Layout-Daten — **generisch über das
  Animations-Vokabular**, nicht auf sit/sleep festgenagelt:
  `markers: [{ "at": [x, y], "animation": "sit", "rotation": 180, "offset_y": -0.05 }, …]`
  - `at` = Fraktion der Raum-Grundfläche; `animation` = Clip-Kind aus dem
    offenen Vokabular von `/assets/animation-clips` — später also auch
    `dance`, `cook`, … ohne Vertragsänderung.
  - **`rotation`** (Grad): Blickrichtung der Figur — 0 = Süd, 90 = Ost,
    180 = Nord, 270 = West. Fehlt sie, schaut die Figur wie üblich zu
    den Nachbarn.
  - **`offset_y`** (Meter, ±): Höhen-Feinjustierung, **additiv** zur vom
    Client abgetasteten Auflagehöhe (der Client setzt die Figur auf die
    Oberfläche unterm Marker, z.B. die Sofa-Sitzfläche; offset_y
    korrigiert von dort aus).
  - Die **Nummer** eines Markers ist seine Position im Array (1-basiert) —
    für Anzeige/Auswahl im Editor; der Client braucht sie nicht.
- **Client-Verhalten:** Eine Figur, deren aktive Animation zu einem Marker
  passt, nutzt den nächsten freien Marker (die exakte Höhe holt sich der
  Client per Abtastung an der Marker-Stelle). Marker **schlagen** die
  Client-Heuristik (Sitz-/Liegeflächen-Erkennung); ohne Marker bleibt die
  Heuristik der Fallback.
- **Pflege im Grundriss-Editor:** Marker per Klick setzen, Animations-Kind
  aus dem Clip-Vokabular wählen (dynamisch, keine feste Liste). Die
  **Admin-Vorschau** zeigt an jedem Marker idealerweise eine Testfigur mit
  der jeweiligen Animation — so lässt sich die Platzierung direkt
  beurteilen. Der Spiel-Client nutzt die Marker für die echten Figuren.

**Ausgang statt Treppen/Aufzüge:**
- Treppen und Aufzüge werden vorerst ignoriert — keine begehbare
  Vertikal-Verbindung nötig.
- Pro Raum **ein Ausgangspunkt**, damit der Client Figuren beim Betreten/
  Verlassen plausibel bewegen kann: `exit: [x, y]` als Fraktion der
  Raum-Grundfläche (0..1), Teil der Layout-Daten. Alternativ ein Node
  namens `exit` im GLB, falls die Pipeline das setzen kann — das
  Datenfeld hat Vorrang.
- Ohne Angabe nimmt der Client die Mitte der dem Gebäudezentrum
  zugewandten Raumkante als Fallback.

**Platzierungs-Semantik (Referenz für Vorschauen):** So rendert der
Spiel-Client — eine Admin-Vorschau, die dem folgt, zeigt exakt dasselbe:
- **Referenzfläche** = festes **8 × 8 m-Quadrat**, zentriert auf der
  Kachel (unabhängig vom Gebäudestil). `layout.x/y` = linke obere Ecke,
  `w/d` = Größe, alles als Fraktion 0..1 dieser Fläche; +x = Osten,
  +y = Süden.
- **Etage:** Bodenhöhe = `level × 3 m` (level 0 = Gelände).
- **Raum-Modell:** wird auf Einheits-Grundfläche normalisiert (größte
  XZ-Seite = 1, XZ zentriert, Unterkante y=0), dann uniform so skaliert,
  dass es in das Raum-Rechteck passt (Faktor `min(w/fp_x, d/fp_z) × 0,96`),
  Unterkante auf `Etagenboden + 0,12 m`. Danach wirken `rotation {x,y,z}`
  (Grad) und `offset_y` (Meter) aus dem Modell-Meta.
- **exit** = Fraktion der Raum-Grundfläche (gleiche Orientierung).
- **`always_visible`** (bool, Default `false`): Raum wird dauerhaft
  gezeigt, unabhängig von der aufgedeckten Innenansicht — gedacht für
  Outdoor-Räume, die **nicht** schon im Gebäude-3D-Modell abgebildet
  sind (sonst doppelt). Figuren stehen dann in jeder Zoomstufe an ihrer
  Raum-Position. Pflege: Checkbox im Raum-Editor.
- **`floor_source`** (bool, Default `false`): Die Boden-Textur dieses
  Raum-Modells wird auf die Etagen-Platte **seiner Etage** übernommen
  (der Client tastet den begehbaren Boden ab, schneidet den
  Textur-Ausschnitt aus und kachelt ihn im Welt-Maßstab). **Gilt pro
  Etage:** auf jeder Etage ist genau ein Raum wählbar, jede Platte
  bekommt ihren eigenen Boden. Pflege: Checkbox im Raum-Editor (Editor
  sollte pro Etage nur eine zulassen). Ist auf einer Etage kein Raum
  markiert, greift dort testweise der Raum „Bibliothek".
- Figuren stehen in Räumen im **Maßstab 1/3** ihrer Kartengröße —
  **pro Location übersteuerbar** via `map3d.figure_scale` (0..1;
  Regler/Feld im Editor, der Client liest es bereits).

**Pflege:** am sinnvollsten ein kleiner Grundriss-Editor im Game-Admin
(Räume als Rechtecke ziehen + Etagen-Wahl + Ausgangspunkt setzen, analog
zum Map-Editor für Location-Positionen). Ableiten lässt sich das nicht
sinnvoll. Die 3D-Vorschau daneben ist die **vorhandene Admin-Vorschau**,
erweitert nach obiger Semantik (die iframe-Einbettung der Client-Seite
war ein verworfener Vorschlag; `floorplan.html` bleibt Debug-Werkzeug
des Clients).

**Fallback bleibt:** ohne Layout weiterhin Auto-Grid — kein Alles-oder-nichts.

## Administration

Game Admin → Character → Reiter „3D": Modell ansehen/hochladen/generieren/
entfernen. Gestaltung und Abläufe frei; einzige Erwartung: die
Workflow-Auswahl kommt dynamisch vom Gateway (keine hartkodierten Listen).

## Kamera & Maussteuerung (Referenz für die Admin-Vorschau)

So steuert der Spiel-Client die Kamera — eine Vorschau, die dem folgt,
fühlt sich identisch an. Alle Werte aus `src/scene/engine.ts`.

**Kamera-Modell (Orbit um einen Zielpunkt auf dem Boden):**
- Perspektiv-Kamera, **FOV 45°**, near 0.5, far 800.
- Zustand: Zielpunkt `target` (auf y=0), Distanz `dist`
  (**min 2,5 / max 150** Welt-Einheiten; 1 Einheit = 1 m), Drehung `yaw`,
  freier Neigungs-Anteil `pitchOffset` (Grad).
- **Neigung ist an den Zoom gekoppelt:** Basis-Pitch =
  `lerp(18°, 62°, sqrt((dist − 2,5) / (150 − 2,5)))` — nah = flach auf
  Augenhöhe, fern = steile Draufsicht. Dazu `pitchOffset` (frei, geklemmt
  −35°..+35°); Gesamt-Pitch geklemmt 8°..85°.
- Kameraposition = `target + (sin(yaw)·cos(pitch), sin(pitch),
  cos(yaw)·cos(pitch)) · dist`, Blick auf `target`.
- **Glättung:** `dist` und `yaw` nähern sich ihren Zielwerten pro Frame
  mit Faktor `1 − exp(−8·dt)` (exponentiell, ~8/s).

**Maus:**
- **Links ziehen = Verschieben (boden-verankert):** Der beim Drücken
  unter dem Cursor liegende Bodenpunkt (Raycast auf die y=0-Ebene) bleibt
  unter dem Cursor — `target += (Startpunkt − aktueller Bodenpunkt)`.
  Kein fester Pixel-Faktor; die Rate ergibt sich aus der Geometrie.
- **Mitte ziehen ODER Shift/Strg/Alt + Links = Drehen/Neigen:**
  `yaw −= dx · 0.005 rad/Pixel` (≈ 0,29°/px);
  `pitchOffset += dy · 0.25°/Pixel` (geklemmt −35..35).
  Rechte Taste identisch (Alt-Belegung).
- **Rad = Zoom auf den Cursor:** `dist *= exp(deltaY · 0.0012)`, geklemmt
  2,5..150. Beim **Hinein**zoomen wandert `target` zusätzlich Richtung
  Bodenpunkt unter dem Cursor: `target = lerp(target, cursorPunkt,
  1 − distNeu/distAlt)`.
- **Klick = Auswahl** nur, wenn zwischen Drücken und Loslassen keine
  Bewegung > 0,15 Welt-Einheiten (sonst war es ein Drag).

**Tastatur (optional fürs Vorschau-Gefühl):** Q/E = ±45°-Drehschritte;
+/− = Zoom ×0,8 bzw. ×1,25; WASD/Pfeile = Verschieben entlang der
Blickrichtung mit `0,9 · dist` Einheiten pro Sekunde.

**Für die Raum-Vorschau passende Startwerte** (so startet auch
`floorplan.html`): `dist 22`, `pitchOffset +28°`, `target` = Kachelmitte.

## Referenzwissen (kein Vertrag)

- Funktionierende ComfyUI-Kette + Einstellungen: `implementierung-3d-pipeline.md`
- Referenzbild-Anforderungen (humanoid: A-Pose; Tiere: symmetrische
  Standpose, Kopf in Körperrichtung statt zur Kamera; Abstand zwischen
  Gliedmaßen usw.): ebd.
- Recherche/Lizenzen: `research-bild-zu-3d.md`
