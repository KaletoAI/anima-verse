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

## Administration

Game Admin → Character → Reiter „3D": Modell ansehen/hochladen/generieren/
entfernen. Gestaltung und Abläufe frei; einzige Erwartung: die
Workflow-Auswahl kommt dynamisch vom Gateway (keine hartkodierten Listen).

## Referenzwissen (kein Vertrag)

- Funktionierende ComfyUI-Kette + Einstellungen: `implementierung-3d-pipeline.md`
- Referenzbild-Anforderungen (A-Pose, Abstand zwischen Gliedmaßen usw.): ebd.
- Recherche/Lizenzen: `research-bild-zu-3d.md`
