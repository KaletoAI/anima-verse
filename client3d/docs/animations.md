# Animations-Clips: Quellen & Konvertierung

## Anforderung an jeden Clip

- **Mixamo-52-Bone-Skelett** (`mixamorig:`-Namen) — darauf riggt der
  Auto-Rigger unsere Charaktere; nur so passen Clips ohne Retargeting.
- **FBX ohne Mesh/Skin** (reine Keyframes).
- Der Client mappt Aktivitäten auf Kategorien (`idle`, `walk`, `run`,
  `sit`, `dance`, `wave`, …) — die Kategorie steckt im Dateinamen bzw.
  in der Liste, die das Backend ausliefert.

## Zwei Wege, einen Clip zu bekommen

### 1. Mixamo (mixamo.com, Adobe-Login)

Export „FBX, **Without Skin**", 30 fps. Direkt verwendbar.

- **Vorteil:** kuratiert, sauber geloopt, kein Nacharbeiten.
- **Grenze:** Adobes Nutzungsbedingungen untersagen u.a. den Einsatz in
  pornografischen/obszönen Kontexten und die Weitergabe als
  Asset-Bibliothek. Für ein NSFW-fähiges Projekt heißt das: Basis-Clips
  ja, explizite Bewegungen **nicht** von hier.
- **Wichtig:** alle Mixamo-Clips aus derselben Quelle beziehen. Fremd-FBX
  aus Modell-Repos (z.B. das `Standard Run.fbx` aus dem MIA-Repo) haben
  abweichende Skelett-Konventionen und kippen die Figuren um.

### 2. Beliebige Mocap-Quelle + Retargeting (Adobe-frei)

`tools/retarget-to-mixamo.py` konvertiert BVH/FBX von fremden Skeletten
auf unser Mixamo-Skelett:

```bash
blender --background --python tools/retarget-to-mixamo.py -- \
    --ref public/models/Idle.fbx \      # Mixamo-Referenzskelett
    --in  <datei.bvh|.fbx|ordner> \     # Quelle(n)
    --out <ausgabeordner> [--kind walk] # Ausgabename
```

Verfahren: Knochen-Zuordnung per Namens-Heuristik (Tabelle `MAP` im
Skript erweiterbar), Rotationsübertragung über den Weltraum (kompensiert
abweichende Ruhe-Orientierungen), Hüftbewegung auf die Zielgröße skaliert,
Export als Mixamo-kompatible FBX. Ganze Ordner in einem Lauf.

**Verifiziert** mit der CMU-Motion-Capture-Datenbank (Public Domain,
2.548 Bewegungen, BVH-Mirror: github.com/una-dinosauria/cmu-mocap):
Gehzyklus retargetet, läuft aufrecht und sauber auf den generierten
Charakteren (`figure-test.html?model=…&clip=cmuwalk`).

- **Vorteil:** keine Lizenz- oder Inhaltsbeschränkung (CMU ist gemeinfrei),
  beliebige Quellen nutzbar, für NSFW-Bewegungen der einzig saubere Weg.
- **Grenze:** Rohes Mocap ist ungefiltert — kann zittern, Füße können
  rutschen, Loops sind nicht garantiert. Pro Clip prüfen.

**Blender** liegt auf diesem CT unter `/home/dev/tools/blender-4.2.5-linux-x64/`.

## Prüfen

`figure-test.html?model=<Modell>&clip=<kind>` im 3D-Client — mit `&diag=1`
loggt der Viewer numerisch, ob die Figur aufrecht steht (SpineUp-Y ≈ 1).
