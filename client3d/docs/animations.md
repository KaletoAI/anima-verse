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

Der Import läuft heute über `scripts/clip_import_cmu.py` im Repo-Wurzel-
verzeichnis (Blender-Seite: `app/blender/scripts/cmu_clip.py`, `fbx_clip.py`,
`clip_orient.py`, `clip_roll.py`). Jede Konvertierung treibt ihren Take auf
das Referenz-Rig `shared/models/rig/reference.fbx` (gebaut von
`scripts/make_reference_rig.py`) — nicht auf einen Clip. Das frühere
Client-Skript `tools/retarget-to-mixamo.py` (Mixamo-Referenzskelett) ist
damit abgelöst und entfernt.

**Historisch verifiziert** mit der CMU-Motion-Capture-Datenbank (Public Domain,
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
