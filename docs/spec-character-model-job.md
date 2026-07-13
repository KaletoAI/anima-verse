# Spezifikation: Job `character_model` (LLM-Gateway)

Stand 2026-07-13. Vertrag zwischen **anima-verse** (Auftraggeber),
**LLM-Gateway** (führt ComfyUI aus) und dem, was am Ende beim 3D-Client
ankommt. Ergänzt `implementierung-3d-pipeline.md` (dort steht die
ComfyUI-Kette; hier steht das **Interface**).

## 1. Auftrag (anima-verse → Gateway)

```
POST /jobs/character_model
Content-Type: application/json
{
  "character":       "Kira",              // Anzeigename, für Dateinamen/Logs
  "reference_image": { "url": "http://<anima-verse>/characters/Kira/images/ref.png" },
                     // alternativ: { "base64": "<...>" } (PNG/JPEG)
  "variant":         "fast",              // "fast" (~200s) | "high" (~600s), default "fast"
  "target_faces":    20000,               // optional, default 20000
  "texture_size":    2048,                // optional, default 2048
  "no_fingers":      false,               // optional, default false
  "callback_url":    "http://<anima-verse>/internal/model-jobs/<id>"  // optional
}
→ 202 { "job_id": "cm_7f3a...", "status": "queued" }
```

## 2. Status

```
GET /jobs/{job_id}
→ 200 {
  "job_id": "cm_7f3a...",
  "status": "queued" | "running" | "succeeded" | "failed",
  "progress": 0.0–1.0,                    // optional (ComfyUI-Fortschritt)
  "error":   { "code": "...", "message": "..." }   // nur bei failed
}
```

## 3. Ergebnis — WAS zurückkommt und in welcher Form

**Zwei Endpunkte** (Metadaten und Binärdatei getrennt — kein Base64-GLB
in JSON, die Dateien sind 10–25 MB):

```
GET /jobs/{job_id}/result            → 200 application/json  (nur bei succeeded)
{
  "character":    "Kira",
  "format":       "glb",              // Konstante
  "rig":          "mixamo",           // Konstante der Kette (52-Bone-MIA-Rig)
  "joints":       52,                 // aus der Datei gelesen, MUSS 52 sein
  "vertices":     58953,              // aus der Datei gelesen
  "size_bytes":   10537644,
  "sha256":       "e3b0c442...",
  "texture_size": 2048,
  "variant":      "fast",
  "generated_at": "2026-07-13T09:12:44Z",
  "source": {
    "workflow":          "trellis2-vb-fast",   // Workflow-Kennung + Version
    "comfyui_prompt_id": "…",
    "reference_image":   "…"                    // URL/Hash des Eingangsbilds
  },
  "model_url": "/jobs/cm_7f3a.../model.glb"
}

GET /jobs/{job_id}/model.glb         → 200
Content-Type: model/gltf-binary
Content-Length: <size_bytes>
<GLB-Bytes>                          // die MIAAutoRig-Ausgabedatei, unverändert
```

Die GLB-Datei ist **das `<name>_mia.glb` aus ComfyUI, byte-identisch** —
das Gateway transformiert nichts, es validiert nur (siehe 4) und reicht durch.
Aufbewahrung: mindestens bis zum ersten erfolgreichen Abruf + 24 h.

## 4. Validierung im Gateway (Pflicht, vor `succeeded`)

Ein Job darf nur `succeeded` melden, wenn die GLB-Datei alle Prüfungen
besteht — sonst `failed` mit dem passenden Fehlercode:

| Prüfung | Bedingung | Fehlercode |
|---|---|---|
| GLB-Magic | Bytes 0–3 == `glTF`, Version 2 | `invalid_glb` |
| Rig | genau 1 `skins`-Eintrag, **52 Joints**, Knochennamen beginnen mit `mixamorig:` | `invalid_rig` |
| Geometrie | POSITION-Count 5.000–150.000 | `bad_geometry` |
| Textur | ≥1 eingebettetes Image (`images[].bufferView`), erstes Image > 100 KB (2×2-Dummy-Erkennung!) | `missing_texture` |
| Größe | Datei ≤ 30 MB | `too_large` |
| ComfyUI | Workflow-Fehler / Timeout (Fast > 10 min, High > 20 min) | `generation_failed` |

(Alle Prüfungen sind reine Header-/JSON-Chunk-Reads — kein 3D-Parsing nötig.
Die 2×2-Dummy-Prüfung fängt den bekannten Node-Bug der alten Kette ab.)

## 5. Ablieferung an anima-verse (Push, empfohlen)

Bei `succeeded` und gesetztem `callback_url` pusht das Gateway selbst:

```
POST http://<anima-verse>/characters/{name}/model
Authorization: Bearer <gateway-token>
Content-Type: model/gltf-binary
X-Model-Meta: {"rig":"mixamo","source":"generated","variant":"fast",
               "sha256":"…","workflow":"trellis2-vb-fast"}   // JSON, eine Zeile
<GLB-Bytes>
→ 201 (anima-verse speichert unter characters/<name>/model/default.glb
       + meta.json; liefert danach via GET /characters/{name}/model aus)
```

Ohne `callback_url` holt anima-verse das Ergebnis selbst über 3. ab (Pull).

## 6. Fehlerbilder & Betrieb

- **Ein Job zur Zeit** pro GPU (gleiche Channel-Logik wie Bild-Jobs).
- ComfyUI-RAM-Watchdog: Neustart nach N Jobs oder RAM-Schwelle;
  laufender Job wird danach **einmal automatisch wiederholt** (`retry: 1`).
- `failed`-Jobs behalten die ComfyUI-Logs (`error.message` = letzte
  Fehlerzeile) für die Diagnose.
- Idempotenz: gleicher `character` + gleicher `reference_image`-Hash +
  gleiche Parameter ⇒ Gateway DARF das gecachte Ergebnis liefern.

## 7. Was der 3D-Client am Ende sieht (zur Einordnung)

`GET /characters/{name}/model` (anima-verse, mit ETag) → genau diese
GLB-Datei. Der Client normalisiert Orientierung/Größe selbst und wendet
die globale Mixamo-Clip-Bibliothek an — es gibt KEINE weiteren
Anforderungen an das Gateway als die obigen.
