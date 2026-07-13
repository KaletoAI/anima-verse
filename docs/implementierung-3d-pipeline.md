# Implementierungs-Anleitung: 3D-Charakter-Pipeline

Stand 2026-07-13, verifiziert mit Kira („Fast") und Bianca („High") in der
Kai-Welt. Zielbild: **LLM-Gateway** orchestriert ComfyUI und erzeugt pro
Charakter ein fertiges GLB; **anima-verse** speichert und liefert es aus
(AV3D-5 Stufe 1, siehe `backend-wishlist.md`).

## Die Kette (final)

**ComfyUI, zwei Node-Packs:**
`visualbruno/ComfyUI-Trellis2` (Mesh + Texturierung) und
`PozzettiAndrea/ComfyUI-UniRig` (nur der MIAAutoRig-Node).

```
LoadImage → TRELLIS.2-Mesh-Generierung (vb)
  → Simplify Trimesh (Ziel ~20.000–30.000 Faces)
  → Mesh Texturing Multi-View (Textur 2048)
  → MIAAutoRig  →  <name>_mia.glb   ← DIE eine Datei pro Charakter
```

- **MIAAutoRig-Einstellungen:** `use_normal=true`, **`reset_to_rest=false`**
  (die vb-Kette liefert die Mixamo-kompatible Bind-Pose von sich aus;
  `true` verbiegt sie), `no_fingers` nach Hand-Qualität (bei zersplitterten
  Händen `true` = Finger-Gewichte in die Hand mergen), `fbx_name=<charakter>`.
- **Varianten:** „Fast" ~200 s, „High" ~600 s Generierungszeit — Rigging
  selbst ~10 s. Beide liefern 52-Bone-Mixamo-Rigs mit eingebetteter Textur.
- **Zielgröße:** ~10 MB pro Charakter (bei Textur 2048; 4K-Texturen
  verdreifachen die Datei ohne sichtbaren Gewinn auf Kartendistanz).
- Der frühere Reparatur-Schritt (`tools/fix-rig-uv.py`) ist **obsolet** —
  er gehörte zur alten Kette (RasterizePBR→UniRig-Node, drei Node-Bugs)
  und bleibt nur als Werkzeug für Altbestände im Repo.

## Animations-Clips (global, einmalig)

- Quelle: **Mixamo** (mixamo.com, kostenloser Adobe-Login), Export
  „FBX, **Without Skin**", 30 fps. **Alle Clips aus dieser einen Quelle** —
  Fremd-FBX (z.B. aus Modell-Repos) haben abweichende Skelett-Konventionen
  und kippen die Figur.
- Aktueller Bestand: Walking, Sitting, Breathing Idle. Wunschliste: Standard
  Run, Dance, Wave, Lie/Sleep.
- Der Client wendet die Clips direkt an (kein Retargeting nötig) und
  transformiert dabei automatisch den Hüft-Track in den Skelett-Raum des
  Rigs (Rotations-Konjugation; von der Hüft-Position wird nur das vertikale
  Wippen übernommen, Lokomotion verworfen — die Wurzel bewegt der Client).
  Das ist generisch für alle MIA-Rigs und braucht keine Konfiguration.

## Anleitung A: LLM-Gateway (ComfyUI ansprechen)

Job `character_model`: Referenzbild → fertiges GLB.

1. **Referenzbild-Prompt (fest):** Ganzkörper, frontal, freigestellt,
   A-Pose (`arms angled 45 degrees away from body`), `legs clearly apart`,
   eng anliegende Kleidung, Hose oder Rock mit Schlitz, flache Schuhe,
   Haare hinter den Schultern. (Berührungen/Verschmelzungen im Bild werden
   zu verschmolzener Geometrie — Gliedmaßen brauchen sichtbaren Abstand.)
2. **ComfyUI HTTP-API:** `POST /prompt` mit dem Workflow-JSON (API-Format),
   `GET /history/<id>` pollen, `<name>_mia.glb` aus `output/` einsammeln.
3. **Validierung:** GLB-Magic, `skins` vorhanden (52 Joints), Größe < 30 MB.
4. **Ablieferung:** Upload an anima-verse (Anleitung B).
5. **Betrieb:** ein Job zur Zeit (VRAM); RAM-Watchdog für ComfyUI
   (UniRig-Worker leckt über Läufe; Neustart nach N Jobs oder RAM-Schwelle);
   nur den MIA-Modus verwenden (deterministisch — der UniRig-Modus würfelt
   sporadisch "Expected 52 bones").

## Anleitung B: anima-verse (Dateien liefern — AV3D-5 Stufe 1)

1. **Ablage:** `characters/<name>/model/default.glb` (später pro Outfit
   `<outfit>.glb`, Server wählt passend zum aktuellen Outfit).
2. **Endpoints:**
   - `GET /characters/{name}/model` → GLB-Bytes.
     **Pflicht: `ETag` + `Cache-Control`** (Dateien 8–10 MB, ändern sich
     selten; der Client cacht aggressiv). 404 wenn keins → Client fällt
     automatisch auf Portrait-Marker zurück.
   - `GET /characters/{name}/model/meta` →
     `{"format":"glb","rig":"mixamo","source":"generated|upload"}`.
   - Upload: `POST /characters/{name}/model` (Admin bzw. Gateway-Token).
     Validierung: GLB-Magic, `skins` vorhanden (sonst Warnung „ungeriggt —
     Figur wäre statisch"), Größenlimit.
3. **Globale Animations-Bibliothek** (einmalig):
   - Ablage z.B. `shared/models/clips/*.fbx`.
   - `GET /assets/animation-clips` → `[{"kind":"walk","url":"/assets/animation-clips/Walking.fbx"}, ...]`
     (kind ∈ walk/run/sit/idle/dance/…; Freitext-Activities werden im Client
     bzw. via AV3D-6 auf diese Kategorien gemappt).
4. **Keine Format-Auflagen** an Orientierung/Skalierung: Der Client richtet
   Z-up auf, normalisiert Größe und Boden-Offset selbst.

## Client (dieses Repo) — was sich dann ändert

`FigureLibrary` tauscht die Manifest-Quelle gegen die API:
Modelle von `GET /characters/{name}/model` (mit meta.rig-Check),
Clips von `GET /assets/animation-clips`. Fallback-Kette bleibt identisch:
Modell → Portrait-Marker. Das lokale `public/models/manifest.json` bleibt
als Dev-/Offline-Modus erhalten. Aufwand: klein, Schnittstellen sind isoliert.

## Bekannte Qualitätsgrenzen (Stand heute)

- **Achsel-Webbing** bei T-Pose-Referenzbildern (TRELLIS verschmilzt
  Arm/Torso-Zwischenraum) → A-Pose-Referenz, ggf. ImageToShape-Auflösung 1024.
- **Schwingende lose Kleidung** (Auto-Skinning bindet Stoff voll an
  Armknochen) → eng anliegende Kleidung im Referenzbild, `use_normal=true`.
- Kleine Geometrie-Fetzen → `floater_threshold` erhöhen.
- **Dritter Node-Bug (bestätigt): Gewichtsspalten falsch zugeordnet.** Die
  Spine-Kette ist rotiert (Head-Spalte hält Torso-Vertices usw.) und
  Fuß/Zehe sind vertauscht — Ursache des „Klebens" an Gliedmaßen. 
  `fix-rig-uv.py` erkennt und korrigiert das automatisch (Spalten-Schwerpunkt
  vs. Knochensegment, optimale Zuordnung) und loggt die Korrekturen.
- Upstream-Fix wünschenswert: ComfyUI-UniRig müsste PBR-Texturen übernehmen,
  UVs erhalten und die Gewichtsspalten korrekt zuordnen — bis dahin bleibt
  `fix-rig-uv.py` (UV-Transfer + Welding + Spalten-Korrektur) Teil der Pipeline.
