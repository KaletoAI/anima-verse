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

## AV3D-2: Raum-Layout-Geometrie — offen

- **Motivation:** Räume haben keine Position/Größe; der Client legt sie als
  Auto-Grid in den Gebäude-Footprint. Für wiedererkennbare Grundrisse
  (Terrasse südlich, Apartment im 12. Stock) braucht es echte Layoutdaten.
- **Vorschlag:** optionales `room.layout = {"x":0.0,"y":0.5,"w":0.5,"h":0.5,"floor":0}`
  (Fraktionen des Footprints; `floor` für mehrgeschossige Gebäude).
- **Workaround:** Auto-Grid in `buildInterior()`.

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

## AV3D-5: 3D-Charakter-Assets pro Charakter (GLB/VRM) — offen — ⭐ Kernwunsch

- **Motivation:** Der Client soll NPCs als animierte 3D-Figuren zeigen. Die
  Erzeugung/Ablage gehört ins Backend (analog Galerie/Outfit-Bildern), der
  Client konsumiert nur.
- **Vorschlag, minimal (Stufe 1 — Upload):**
  - Ablage `characters/<name>/model/` (GLB oder VRM), Upload im Game-Admin.
  - `GET /characters/{name}/model` → Modell-Bytes; 404 wenn keins → Client
    fällt auf Portrait-Marker zurück.
  - `GET /characters/{name}/model/meta` → `{"format":"vrm|glb","scale":1.0}`.
- **Vorschlag, Ausbau (Stufe 2 — Generierung):** neuer Backend-Typ
  „3D-Asset-Generierung" in der BACKEND_REGISTRY (Bild-zu-3D + Auto-Rigging,
  lokal gehostet oder API-Dienst), Task-Queue-Job `character_model`:
  Referenzbild → Mesh → Rigging → Ablage wie Stufe 1.
  **Recherche liegt vor → `docs/research-bild-zu-3d.md`** (Kurzfassung:
  Hunyuan3D in der EU lizenzblockiert; Start mit Tripo/Meshy-API empfohlen,
  Rigging selbsthostbar via Make-It-Animatable/UniRig, beide MIT).
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
