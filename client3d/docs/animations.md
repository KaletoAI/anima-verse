# Animations-Clips — was der 3D-Client erwartet

Die Bibliothek selbst und ihre Dateiregeln stehen in
[`shared/models/clips/README.md`](../../shared/models/clips/README.md), der
Vertrag in [`docs/schnittstellen-3d.md`](../../docs/schnittstellen-3d.md)
§ A8 (Clips, Sets, Loop) und § A8a (Paar-Clips). Hier steht nur, was die
Client-Seite davon sieht.

## Die drei Zusagen

1. **Ein Rig für alles.** Jeder Clip liegt auf `shared/models/rig/reference.fbx`
   (69 `mixamorig:`-Knochen). Der Importer retargetet jede Quelle darauf —
   CMU-Mocap, gekaufte Packs, fremde FBX aus dem Inbox-Import —, deshalb muss
   der Client nichts mehr umrechnen außer der Bind-Pose der jeweiligen Figur
   (`@anima/scene-render` → `restCorrections`, gegen die Rest-Pose aus
   `GET /assets/animation-rig`).
2. **FBX ohne Mesh/Skin** („Without Skin"), reine Keyframes.
3. **Bewegungsclips laufen IN PLACE.** Die Wurzel bewegt der Client (Laufen,
   Reise, Klick-Route); ein Clip mit eigener Wurzelbewegung zieht die Figur
   von der Position weg, an der das Spiel sie hält.

## Welchen Clip eine Figur spielt, sagt der SERVER

`activity_animation` je Charakter im Worldmap-Payload (§ A8) nennt die
Clip-Art. Nennt der Server keine, steht die Figur (`idle`). Die frühere
Keyword-Heuristik `activityToClipKind` im Client ist **gelöscht**
(2026-08-28) — der Client rät nicht mehr aus Freitext.

`loop` aus der Clip-Auflistung entscheidet, ob der Clip wiederholt oder sein
letztes Bild hält (`LoopOnce` + `clampWhenFinished`); eine Art ohne Eintrag
gilt als Loop, damit Lokomotion nie stehen bleibt.

## Prüfen

```
/figure-test.html?model=<charakter>&clip=<kind>&diag=1
```

Die Diagnose-Seite des Clients rendert eine Figur isoliert und loggt nach drei
Sekunden numerisch, ob sie aufrecht steht: `SpineUp-Y ≈ 1` = AUFRECHT,
< 0,3 = LIEGEND. Rechnen statt Hinsehen — dieselbe Regel wie § B5a.

Die Bodenlage misst `client3d/src/scene/clipGround.ts`: ein Clip, der über
seiner eigenen Null animiert wurde (ein Schwimmer auf der Wasserlinie), wird
beim Laufen auf den Boden gesetzt. Das rettet das Bild, nicht die Absicht —
solche Clips gehören auf dem Boden animiert, außer sie sollen darüber liegen
(ein Schlafender auf einem Bett).

## Woher Clips kommen

Zwei Wege, beide enden im selben Retarget auf das Referenz-Rig:

* **CMU-Mocap** (gemeinfrei, deshalb im Repo) — `scripts/clip_import_cmu.py`
  oder der Katalog-Browser im Game-Admin unter **Poses**.
* **Fremde FBX** (gekaufte Packs, Mixamo-Downloads) — in
  `shared/models/clips-inbox/` ablegen oder hochladen, dann importieren. Die
  Rohdateien bleiben aus dem Git; das Ziel ist per Default die
  LIZENZIERTE Bibliothek.

Die Blender-Seite sind `app/blender/scripts/cmu_clip.py`, `fbx_clip.py`,
`clip_orient.py` und `clip_roll.py`; welches Blender benutzt wird, entscheidet
`app/blender/runner.py` (Konfiguration `image_generation.blender_executable`,
sonst `blender` aus dem `PATH` oder ein Fund unter `~/tools/blender*/blender`).
