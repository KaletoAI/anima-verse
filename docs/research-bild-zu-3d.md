# Recherche: Bild-zu-3D-Pipeline für Charakter-Figuren (AV3D-5 Stufe 2)

Stand: 2026-07-11 · Methode: Deep-Research mit adversarialer Verifikation
(25 Top-Claims, 3 unabhängige Prüfer je Claim; 24 bestätigt, 1 widerlegt).
Frage: Referenzbild (SD/Flux) → animierbare Figur (GLB/VRM, Humanoid-Rig),
Priorität selbsthostbar > API, Lizenz muss öffentliches OSS-Projekt erlauben.

## Kernergebnis in einem Satz

Rigging und Animation sind selbsthostbar sauber gelöst (MIT-Tools), aber beim
Schritt Bild→Mesh ist die naheliegende Open-Source-Option **Hunyuan3D in der
EU lizenzrechtlich blockiert** — für den Start ist eine API (Tripo/Meshy,
~0,30–0,85 $ pro Charakter) der pragmatische Weg, exakt passend zur
Backend-Registry-Philosophie von anima-verse.

## Verifizierte Befunde

### 1. Bild → Mesh

- **Hunyuan3D-2 / 2.1 (Tencent): in der EU NICHT nutzbar.** ⚠ Hoch-konfident,
  3-0 verifiziert gegen die Original-LICENSE: *„THIS LICENSE AGREEMENT DOES NOT
  APPLY IN THE EUROPEAN UNION …"* — Nutzer in der EU haben keinerlei
  Lizenzgrant, inkl. Verbot der Nutzung/Weitergabe der Outputs. Technisch wäre
  es 10/21/29 GB VRAM (Shape/Textur/beides) — irrelevant für uns.
  Nebenbefund: Der Claim „liefert PBR-Texturen" wurde 0-3 **widerlegt**.
- **TRELLIS / TripoSR / Stable-Fast-3D: Lücke.** Kein Claim zu diesen (im
  Auftrag explizit genannten) Alternativen hat die Verifikation überlebt —
  Lizenz (TRELLIS vermutlich MIT), VRAM und Qualität bei stilisierten
  Charakteren sind **unbelegt** und brauchen eine Nachrecherche, bevor eine
  selbsthostbare Mesh-Stufe eingeplant wird.
- **Rodin/Hyper3D:** durch keinen verifizierten Claim abgedeckt.

### 2. Auto-Rigging (selbsthostbar — gute Lage)

- **UniRig** (Tsinghua/VAST, SIGGRAPH 2025) — **MIT, Code UND Checkpoints**,
  ab 8 GB VRAM, erzeugt Skelett + Skinning-Gewichte, Ein-/Ausgabe
  .obj/.fbx/.glb/**.vrm**, laut Autoren explizit auch Anime-/stilisierte
  Charaktere. Einschränkungen (verifiziert): veröffentlichtes Checkpoint nur
  Articulation-XL2.0 (volle Rig-XL/VRoid-Checkpoints seit ~1 Jahr nur
  angekündigt); Praxis: schwache Hand-/Fingerknochen, Phantom-Bones bei
  Capes/komplexer Kleidung.
- **Make-It-Animatable** (CVPR 2025, MIT) — Rigging+Skinning+Pose-Reset in
  **<1 s**, festes **Mixamo-kompatibles 52-Bone-Skelett** (inkl. Finger),
  akzeptiert Meshes aus Meshy/Tripo/TRELLIS-artigen Generatoren. Nur bipedale
  Humanoide — für unsere NPCs genau richtig.

### 3. API-Dienste (Mesh + Rigging aus einer Hand)

| Dienst | Kosten pro Charakter (texturiert + gerigged) | Lizenz Output |
|---|---|---|
| **Tripo** | ~0,55–0,85 $ (Image-to-Model 20–50 Cr. + Rig 25 Cr. + Retarget 10 Cr./Anim; 1 $ = 100 Cr.) | ⚠ nicht verifiziert |
| **Meshy** | Image-to-3D 30 Cr. (Meshy-6, texturiert) + Rig 5 Cr. + Anim 3 Cr. | ✓ Paid-Plan: volles Eigentum inkl. Redistribution; Free: CC BY 4.0 mit Attribution. Nicht-Enterprise-Daten darf Meshy zum Training nutzen |

Meshy-Rigging setzt Humanoid, <300k Faces, +Z-Ausrichtung voraus.

### 4. Animation / Retargeting → three.js

- **vrm-mixamo-retargeter** (MIT, TypeScript): Mixamo-FBX-Clips zur Laufzeit
  auf VRM-Avatare, automatisches Bone-Mapping (three ≥0.150, three-vrm ≥2.0).
- **fbx2vrma-converter** (MIT, CLI): Mixamo-FBX → **VRMA 1.0**-Dateien,
  abspielbar mit `@pixiv/three-vrm-animation` (three.js r177+).
- ⚠ Beide sind sehr kleine Community-Projekte (13/42 Stars); fbx2vrma hängt am
  archivierten FBX2glTF. Funktional bestätigt, Reife begrenzt — einplanen,
  dass wir notfalls forken.

### 5. Realistische Qualitätserwartung

Praxisbericht (nur Nebenevidenz, nicht hart verifiziert): grob **40 %
exzellent / 40 % Cleanup nötig / 20 % problematisch** bei Auto-Rigging
stilisierter Figuren; typische Schwächen Hände/Finger und Kleidungs-Extras.
End-to-End-Dauer wurde durch keinen verifizierten Claim quantifiziert.

## Empfehlung für anima-verse (AV3D-5 Stufe 2)

1. **Backend-Typ „3D-Asset-Generierung" als Registry-Backend bauen** — gerade
   WEIL die Selbsthosting-Lage beim Mesh-Schritt (EU-Lizenz!) wackelig ist,
   muss der Dienst austauschbar sein wie die Bild-Backends.
2. **Start mit Tripo ODER Meshy als erstem Backend** (Task-Queue-Job
   `character_model`: Referenzbild → Mesh+Rig → GLB in
   `characters/<name>/model/`). Vorher klären: Tripo-Output-Lizenz (offene
   Frage!) — sonst Meshy Paid (Ownership verifiziert).
3. **Rigging-Stufe selbsthostbar vorbereiten:** Make-It-Animatable (Mixamo-
   Skelett = passt zu unserem Animations-Fundus) oder UniRig (VRM-Weg) als
   zweites Backend für ungeriggte Meshes.
4. **Client:** GLB mit Mixamo-52-Skelett abspielen (haben wir mit Soldier/Xbot
   de facto schon); VRM-Weg (three-vrm + VRMA) erst, wenn VRoid-Upload kommt.
5. **Nachrecherche einplanen** (offene Fragen): TRELLIS/TripoSR/Stable-Fast-3D
   EU-Lizenz + Qualität bei stilisierten Charakteren; Tripo-Ownership;
   UniRig/MIA → VRM-Bone-Namen-Konformität.

## Quellen (Auswahl, primär)

- github.com/Tencent-Hunyuan/Hunyuan3D-2.1 + LICENSE (EU-Ausschluss, VRAM)
- github.com/VAST-AI-Research/UniRig + huggingface.co/VAST-AI/UniRig (MIT)
- arxiv.org/html/2411.18197v3 + github.com/jasongzy/Make-It-Animatable
- docs.meshy.ai/en/api/pricing · help.meshy.ai (Ownership) · meshy.ai/terms-of-use
- docs.tripo3d.ai/get-started/pricing.html · platform.tripo3d.ai/docs/animation
- github.com/saori-eth/vrm-mixamo-retargeter · github.com/tk256ailab/fbx2vrma-converter
