# Schnittstellen & Erwartungen: 3D-Charaktere

Stand 2026-07-13. Nur die Verträge zwischen den Komponenten — die
Implementierung entscheidet die jeweilige Session selbst.

## LLM-Gateway → anima-verse

**Auftrag:** anima-verse beauftragt ein Charakter-Modell und übergibt dabei
ein Referenzbild sowie die Workflow-Wahl. Welche Workflows es gibt und
welche Parameter sie haben, definiert und meldet das Gateway (Discovery) —
anima-verse kodiert nichts davon fest.

**Ergebnis:** genau **eine GLB-Datei** pro Auftrag (binär, unverändert aus
ComfyUI) plus minimale Metadaten (Workflow-Kennung, Referenzbild, Hash).

**Erwartungen an die GLB, damit der 3D-Client sie nutzen kann:**
- ein Skin mit **Mixamo-Skelett** (52 Joints, `mixamorig:`-Namen) — darauf
  beruht die geteilte Animations-Bibliothek
- **Textur eingebettet** (Achtung: der bekannte Node-Bug liefert sonst ein
  2×2-Dummy-Image — das ist ein Fehlerfall, kein Ergebnis)
- web-taugliche Größe (Richtwert ≤ ~30 MB; dezimiertes Mesh, Textur ≤ 2048)
- Orientierung/Skalierung egal — normalisiert der Client

## anima-verse → 3D-Client

```
GET /characters/{name}/model        → GLB-Bytes | 404
GET /assets/animation-clips         → [{ "kind": "walk", "url": "…" }, …]
```

**Erwartungen:**
- **404 ist ein normaler Zustand** (Client zeigt Portrait-Marker) — kein Fehler
- **ETag/Caching** bei den GLBs (Dateien sind groß und ändern sich selten)
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
