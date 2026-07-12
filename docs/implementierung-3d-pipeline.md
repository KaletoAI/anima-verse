# Implementierungs-Anleitung: 3D-Charakter-Pipeline

Stand 2026-07-12, verifiziert mit Kira und Bianca (Kai-Welt).
Zielbild: **LLM-Gateway** orchestriert ComfyUI und erzeugt pro Charakter ein
fertiges GLB; **anima-verse** speichert es und liefert es an den 3D-Client aus
(AV3D-5 Stufe 1, siehe `backend-wishlist.md`).

## Die Dateien — was wovon gebraucht wird

Ein ComfyUI-Lauf erzeugt mehrere Dateien; **nur zwei davon werden verwendet**,
und sie müssen aus **demselben Lauf** stammen (die UV-Layouts sind pro Lauf
nicht deterministisch identisch):

| Datei (ComfyUI `output/`) | Inhalt | Verwendung |
|---|---|---|
| `<name>_<ts>.glb` (Trellis2ExportTrimesh) | Mesh **texturiert**, ungeriggt | Quelle für Textur + korrekte UVs |
| `<name>_mia.glb` (MIAAutoRig) | Mesh **geriggt** (52 Mixamo-Joints), Textur = 2×2-Dummy, UVs verwürfelt | Quelle für Skelett + Skinning-Gewichte |
| ~~`<name>_mia.fbx`~~, ~~`<name>_mia.fbm/`~~, ~~`preview_*.glb`~~ | | **nicht benötigt** (fbm enthält nur den Dummy) |

Nachbearbeitung (repariert die zwei bekannten Bugs des ComfyUI-UniRig-Nodes —
Texturverlust + UV-Verwürfelung):

```bash
python tools/fix-rig-uv.py <texturiert.glb> <gerigged.glb> <Name>.glb
# benötigt: numpy, scipy
```

Das Script matcht die identische Topologie Dreieck-für-Dreieck (mit
automatischer Achsen-/Spiegel-Ausrichtung), überträgt die UVs und bettet die
baseColor-Textur ein. **Output = die eine Datei pro Charakter** (~8–10 MB,
GLB, 52-Bone-Mixamo-Rig, Textur eingebettet). Validierung: GLB-Magic,
`skins`-Array nicht leer, Face-Matching-Ausgabe `mean < 0.01`.

**Einmalig global** (nicht pro Charakter): Mixamo-Animations-FBX
(Walking, Standard Run, Sitting, empfohlen zusätzlich Breathing Idle;
Export „FBX, Without Skin", 30 fps). Sie passen ohne Retargeting auf jedes
MIA-Rig, weil die Bind-Pose identisch ist.

## Anleitung A: LLM-Gateway (ComfyUI ansprechen)

Neuer Job-Typ `character_model`: Referenzbild → fertiges GLB.

1. **Input:** Ganzkörper-Referenzbild (aus der anima-verse-Bildpipeline).
   Prompt-Anforderungen: A-Pose (`arms angled 45 degrees down` — T-Pose
   erzeugt Achsel-Webbing), frontal, freigestellt/neutraler Hintergrund,
   eng anliegende Kleidung (lockere Kleidung schwingt beim Skinning),
   Hose oder Rock mit Schlitz (Beine müssen trennbar sein), flache Schuhe.
2. **ComfyUI-Aufruf** über dessen HTTP-API:
   - `POST /prompt` mit dem Workflow im API-JSON-Format. Workflow-Kette:
     `LoadImage → Trellis2GetConditioning → Trellis2ImageToShape →
     Trellis2ProcessMesh → Trellis2ShapeToTexturedMesh → Trellis2RasterizePBR
     → (a) Trellis2ExportTrimesh [GLB]  (b) MIAAutoRig [GLB]`
   - Feste Parameter: `ProcessMesh.target_face_count=20000`,
     `floater_threshold` ggf. auf 0.005 erhöhen (Geometrie-Fetzen),
     `RasterizePBR.texture_size=2048`, `MIAAutoRig.use_normal=true`,
     `fbx_name=<charakter>`, Seeds fest (Reproduzierbarkeit).
   - Fertigstellung pollen: `GET /history/<prompt_id>`; Output-Dateien aus
     `output/` einsammeln (`GET /view?filename=...` oder Dateisystem-Zugriff).
3. **Nachbearbeitung:** `fix-rig-uv.py` (siehe oben) → `<Name>.glb`.
4. **Ablieferung:** `PUT`/Upload an anima-verse (siehe Anleitung B).
5. **Betriebshinweise:**
   - **Ein Job zur Zeit** (VRAM; zwei Bildjobs parallel sind schon Tabu-Regel
     der bestehenden Queue — gleiche Channel-Logik verwenden).
   - **RAM-Leak im UniRig-Worker:** Nach mehreren Läufen steigt der RAM des
     ComfyUI-Prozesses (beobachtet >90 % bei 36 GB) und die Skelett-Vorhersage
     wird instabil. Watchdog einplanen: ComfyUI-Neustart nach N Jobs oder
     bei RAM-Schwelle.
   - Nur den **MIA-Modus** verwenden (deterministisch). Der UniRig-Modus
     würfelt sporadisch `Expected 52 bones, got N` (sampelnde Generierung,
     temperature 1.5) — wenn doch genutzt: einfach neu versuchen.

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
- Upstream-Fix wünschenswert: ComfyUI-UniRig müsste PBR-Texturen übernehmen
  und UVs erhalten — bis dahin bleibt `fix-rig-uv.py` Teil der Pipeline.
