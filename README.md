# anima-verse-3d

Prototyp einer zoombaren 3D-Weltkarte im Age-of-Empires-Stil für
[anima-verse](../anima-verse). Nutzt ausschließlich die Backend-HTTP-API —
das anima-verse-Projekt selbst bleibt unangetastet.

## Features (Prototyp)

- **AoE-Kamera:** Pan (Ziehen/WASD), Zoom Richtung Mauszeiger (Rad), Drehen in
  45°-Schritten (Q/E).
- **3D-Locations:** prozedurale Gebäude per Stil-Heuristik (Café, Haus, Hochhaus,
  Generisch), Terrain-Kacheln (Wald mit Bäumen, Straßen) — Kachelbilder kommen,
  wenn vorhanden, vom Backend (`/world/locations/{id}/map-icon-2d`).
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
# 1. anima-verse-Backend auf :8000 starten (z.B. ./start.sh --world demo)
# 2. hier:
npm install
npm run dev        # http://localhost:5183, Login mit Backend-Benutzer
```

Anderes Backend-Ziel: `ANIMA_API=http://host:port npm run dev`
(Vite-Dev-Proxy leitet `/auth /play /world /characters /state /events` weiter).

## Architektur

- Vite + TypeScript + Three.js (vanilla), CSS2DRenderer für Labels.
- `src/scene/engine.ts` — Kamera/Input/Licht/Renderloop
- `src/scene/tiles.ts` — Location-Kacheln, Gebäude, Innenraum-Crossfade
- `src/scene/npcs.ts` — NPC-Sprites, Bewegung, Reiserouten
- `src/main.ts` — API-Polling, LOD-Logik, Verdrahtung
- Plan & API-Analyse: `development_instructions/plan-3d-map-prototype.md` (lokal)
