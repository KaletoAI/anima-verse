# client3d — 3D-Weltkarte

Zoombare 3D-Weltkarte im Age-of-Empires-Stil. Spricht das Backend
**ausschließlich über die HTTP-API** an und läuft deshalb genauso gut auf einem
anderen Rechner als der Server.

Seit 2026-07-26 ein npm-Workspace dieses Repos (vorher ein eigenes Repo
`anima-verse-3d`; per `git subtree` eingezogen, die Historie ist erhalten).
Geometrie, die auch die Admin-Vorschau braucht, liegt im geteilten Paket
[`@anima/scene-render`](../packages/scene-render) — nicht hier.

**Der Vertrag, gegen den dieser Client rendert, ist
[`docs/schnittstellen-3d.md`](../docs/schnittstellen-3d.md)** (Teil A: Karte,
Reise, Boden; Teil B: das Szenen-Rezept einer Location; Teil C: Ergänzungen
nach Thema). Er liegt im Wurzel-`docs/`, nicht hier. In `docs/` dieses
Workspaces stehen nur Client-Notizen: `animations.md` (was der Client von der
Clip-Bibliothek erwartet) und zwei als **historisch** markierte
Recherche-Protokolle aus dem Juli 2026.

## Features (Prototyp)

- **AoE-Kamera:** Pan (Ziehen/WASD), Zoom Richtung Mauszeiger (Rad), Drehen in
  45°-Schritten (Q/E), frei drehen/neigen (mittlere Maustaste oder
  Shift/Strg/Alt+Links; rechte Taste geht auch, kollidiert aber je nach
  Browser mit Maus-Gesten). **Während man den Avatar steuert, dreht schon das
  blanke Linksziehen** (`engine.orbitOnDrag`) — die Kamera hängt dort an der
  Figur, ein Pan-Ziehen wäre wirkungslos; ein Klick bis 4 px Bewegung bleibt
  ein Klick und damit der Geh-Befehl.
- **3D-Locations:** prozedurale Gebäude per Stil-Heuristik (Café, Haus, Hochhaus,
  Generisch), Terrain-Kacheln (Wald mit Bäumen, Straßen) — Boden- und
  Wandtexturen kommen, wenn vorhanden, vom Backend
  (`/assets/surface-textures`); 2D-Map-Icons werden im 3D-Pfad nicht genutzt.
- **Raumauflösung beim Reinzoomen:** nah herangezoomte Gebäude blenden Dach und
  Wände aus und zeigen ihre Räume als begehbaren Grundriss (Auto-Layout,
  Raum-Labels, Eingangs-Markierung).
- **NPCs live:** Portrait-Marker aus `/play/worldmap` (Poll alle 3 s), laufen
  animiert zwischen Orten, gestrichelte Route + 🚶 bei `movement_target`,
  in der Nahansicht stehen sie in ihrem tatsächlichen Raum
  (`/characters/at-location`).
- **Ereignis-Pins** (🔥/❗) aus `events_by_location`, Info-Panel je Ort
  (Beschreibung, Räume, Anwesende), Login über die Cookie-Session des Backends.

## Starten

```bash
# Alles in einem Rutsch, aus dem Wurzelverzeichnis des Repos:
./start.sh --with-3d --world demo    # Backend :8000 + 3D-Client :5183

# Oder getrennt:
npm install                          # EINMAL im Wurzelverzeichnis, für alle Workspaces
npm run dev -w client3d              # http://localhost:5183, Login mit Backend-Benutzer
npm run build -w client3d            # tsc --noEmit && vite build -> client3d/dist/
```

**Auf einem anderen Rechner** (Backend läuft woanders):

```bash
ANIMA_API=http://<server>:8000 npm run dev -w client3d
```

`ANIMA_API` ist das EINE Backend-Ziel (Default `http://localhost:8000`); es
wird nur vom Dev-Proxy gelesen. `CLIENT3D_PORT` verschiebt den Port — das
wertet `start.sh` aus (`vite --port`), nicht `vite.config.ts`, in dem 5183
fest steht. `./start.sh --with-3d` loggt nach `logs/client3d.log` und legt die
PID unter `.pids/client3d.pid` ab; `./start.sh --stop` beendet beide Prozesse.

**Der Dev-Server leitet alles weiter, was er nicht selbst beantwortet.** Eine
Liste von API-Präfixen gibt es nicht mehr: sie hatte 16 Einträge, davon einen
toten (`/state`), während 150 der 547 Backend-Routen fehlten — und ein
fehlendes Präfix liefert keinen 404, sondern Vites `index.html`: der Aufrufer
bekommt 200 + HTML, `res.json()` scheitert und der Fehler platzt weit weg von
der Ursache. Umgekehrt ist die Menge klein und bekannt. Was **Vite** gehört,
steht in [`dev-proxy-rule.js`](dev-proxy-rule.js) — die gemeinsame Regel aus
`packages/dev-proxy-rule/`, hier an die Seiten dieses Clients gebunden:

```
/@…  /__…  /src/…  /node_modules/…  index.html  figure-test.html  floorplan.html  public/
```

Die drei HTML-Einstiege beantwortet Vite auch ohne Endung (`/floorplan`,
`/figure-test`), `index.html` zusätzlich unter `/`; `public/` ist vor allem
`/models/…` (Manifest und Test-Meshes). Alles andere geht ans Backend — auch
`/play/…`, `/static/…` und `/game-admin`, denn eine Player- oder Admin-Seite
hat dieser Client nicht. (`scripts/smoke_vite_proxy.py` prüft die Regel gegen
alle Routen der FastAPI-Dekoratoren, `scripts/smoke_docs_client3d_readme.py`
hält README und Config zusammen.)

## Seiten

Drei HTML-Einstiege, alle drei im Build (`rollupOptions.input`):

| Seite | Einstieg | Wofür |
|---|---|---|
| `index.html` | `src/main.ts` | die Weltkarte — die eigentliche Anwendung |
| `floorplan.html` | `src/floorplan.ts` | EINE Location isoliert, Innenansicht aufgedeckt, gepollt: `?location=<id-oder-name>[&verify=1]`. Gedacht als iframe neben dem Grundriss-Editor des Game-Admin; rendert ausschließlich aus dem Szenen-Rezept (§ B1), zeigt also dasselbe Bild wie die Admin-Vorschau über `/play/scene-preview` (§ B3) |
| `figure-test.html` | `src/figureTest.ts` | eine Figur isoliert, groß und neutral beleuchtet: `?model=<charakter>&clip=<kind>`, dazu `&diag=1` für die numerische Ausgabe (steht die Figur aufrecht: SpineUp-Y ≈ 1) |

Beide Diagnoseseiten brauchen eine bestehende Anmeldung im 3D-Client.

## Verify (§ B5a)

Rechnen statt Screenshots: `http://localhost:5183/?verify=1` laden und ~5 Minuten
laufen lassen — jedes platzierte Objekt wird neu vermessen und gegen seine Spec
gediffrt (ε = 0,01 m). Ergebnis je Location in der Konsole und in
`window.__sceneVerify`. **0 Abweichungen ist die Aussage**; die absolute Zahl
geprüfter Werte hängt an der Welt und sagt für sich nichts.

Dazu kommen die **49 Smoke-Skripte** unter `scripts/`. Sie laufen ohne Browser
und ohne Server auf reinem Node, weil sie die Module mit esbuild übersetzen und
pure Rechnungen prüfen:

```bash
node client3d/scripts/smoke_walk_math.mjs      # eines davon
for f in client3d/scripts/smoke_*.mjs; do node "$f" || break; done
```

Jede erwartete Zahl darin ist im Kopf der Datei **von Hand aus dem Vertrag
hergeleitet** — eine Prüfung, die nur die heutige Ausgabe festschreibt,
beweist nichts.

## Flächen-Locations

Ein Dorf oder ein See ist kein Gebäude: blendet man sein Modell für die
Innenansicht aus, verschwindet die Location. Trägt das Rezept
`map3d.area_model`, bleibt das Modell deshalb stehen und bekommt stattdessen
**Löcher** — den Gebäude-Grundriss als Ganzes plus den Umriss jedes platzierten
Indoor-Raums außerhalb davon (`cutouts` am building-Spec, Welt-Meter). In den
Löchern steht das normale Rezept-Innenleben. Der Crossfade blendet für diese
Kacheln nichts weg, er SCHALTET die Löcher (`applyCutouts(...).setEnabled`):
Fernsicht = intaktes Modell, Innenansicht = offene Räume.

Outdoor-Räume außerhalb des Grundrisses werden gar nicht gebaut — sie liegen
als Zonen AUF der Modelloberfläche. Ihr Payload-Raumeintrag trägt `overlay`
(Mitte, Rechteck, Höhe in Welt-Metern), und daraus kommen Raum-Mitte und
-Rechteck, damit NPCs, Marker und Labels dort stehen, wo die Zone liegt.

## Architektur

- Vite + TypeScript + Three.js, CSS2DRenderer für Labels. Die **Szene** ist
  vanilla Three.js — kein React, kein Framework darin. Das **HUD** dagegen ist
  React: `src/hud/` enthält acht `.tsx`-Dateien (`Hud`, `GameMenu`, `Minimap`,
  `PerfOverlay`, `TitleScreen`, `CharacterPlaque`, `ChatPortraits`, `mount`)
  und zieht die geteilten Spieler-Panels aus `@anima/player-ui`; `react`,
  `react-dom` und `@vitejs/plugin-react` stehen entsprechend in der
  `package.json`.
- `@anima/scene-render` — geteilt mit der Admin-Vorschau: `placeModelSpec()`
  (§ B2), Raum-Clip (§ B1), Verify-Diff (§ B5a), die Primitiv-Builder
  (Platte/Wand/Extra-Box/Platzhalter) samt ihren Verify-Soll-Feldern und die
  Payload-Typen. Hier liegt KEINE zweite Fassung davon.
- `src/scene/sceneRecipe.ts` — Aufbau der Szene aus dem Payload: Materialien
  für die geteilten Primitive (Surface-Texturen, Payload-Farben) und die
  Verdrahtung in die Kachel
- `src/scene/engine.ts` — Kamera/Input/Licht/Renderloop
- `src/scene/tiles.ts` — Location-Kacheln, Gebäude, Innenraum-Crossfade
- `src/scene/npcs.ts` — NPC-Sprites, Bewegung, Reiserouten
- `src/main.ts` — API-Polling, LOD-Logik, Verdrahtung
- Plan & API-Analyse: `development_instructions/plan-3d-map-prototype.md` (lokal)
