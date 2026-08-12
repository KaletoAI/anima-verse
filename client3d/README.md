# client3d — 3D-Weltkarte

Zoombare 3D-Weltkarte im Age-of-Empires-Stil. Spricht das Backend
**ausschließlich über die HTTP-API** an und läuft deshalb genauso gut auf einem
anderen Rechner als der Server.

Seit 2026-07-26 ein npm-Workspace dieses Repos (vorher ein eigenes Repo
`anima-verse-3d`; per `git subtree` eingezogen, die Historie ist erhalten).
Geometrie, die auch die Admin-Vorschau braucht, liegt im geteilten Paket
[`@anima/scene-render`](../packages/scene-render) — nicht hier.

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

Der Vite-Dev-Proxy leitet `/auth /play /world /characters /state /events /assets`
dorthin weiter. `CLIENT3D_PORT` verschiebt den Port, wenn 5183 belegt ist.

## Verify (§ B5a)

Rechnen statt Screenshots: `http://localhost:5183/?verify=1` laden und ~5 Minuten
laufen lassen — jedes platzierte Objekt wird neu vermessen und gegen seine Spec
gediffrt. Ergebnis je Location in der Konsole und in `window.__sceneVerify`.
Stand 2026-07-26 (Welt `anima-dome`): **1757 geprüfte Zahlen, 0 Abweichungen,
85/85 Modelle**. Die absolute Zahl gilt nur, solange die Welt stillsteht — die
0 Abweichungen sind die Aussage.

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

- Vite + TypeScript + Three.js (vanilla, bewusst kein React), CSS2DRenderer für Labels.
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
