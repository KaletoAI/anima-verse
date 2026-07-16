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
| **generic** (UniRig, z.B. Tiere) | **2 Dateien:** das geriggte `*.fbx` **+** die basecolor-PNG (die FBX bettet die Textur nicht ein) | dieselben Zwischenstufen; metallic-PNG optional/verzichtbar |

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

### Raum-Layout (AV3D-2)

Räume haben heute keine Position und keine Größe. Der Client legt sie als
Auto-Grid ins Gebäude — jeder Grundriss sieht gleich aus, und Figuren stehen
nicht dort, wo sie wirklich sind.

**Erwartung:** Position und Größe pro Raum, relativ zum Gebäude — Fraktionen
(x, y, Breite, Höhe im Bereich 0..1), optional eine Etage. Datenform frei.

**Pflege:** am sinnvollsten ein kleiner Grundriss-Editor im Game-Admin (Räume
als Rechtecke ziehen, analog zum Map-Editor für Location-Positionen).
Ableiten lässt sich das nicht sinnvoll.

**Fallback bleibt:** ohne Layout weiterhin Auto-Grid — kein Alles-oder-nichts.

## Administration

Game Admin → Character → Reiter „3D": Modell ansehen/hochladen/generieren/
entfernen. Gestaltung und Abläufe frei; einzige Erwartung: die
Workflow-Auswahl kommt dynamisch vom Gateway (keine hartkodierten Listen).

## Referenzwissen (kein Vertrag)

- Funktionierende ComfyUI-Kette + Einstellungen: `implementierung-3d-pipeline.md`
- Referenzbild-Anforderungen (humanoid: A-Pose; Tiere: symmetrische
  Standpose, Kopf in Körperrichtung statt zur Kamera; Abstand zwischen
  Gliedmaßen usw.): ebd.
- Recherche/Lizenzen: `research-bild-zu-3d.md`
