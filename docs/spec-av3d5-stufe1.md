# Spezifikation: AV3D-5 Stufe 1 — 3D-Modelle in anima-verse

Stand 2026-07-13. Gegenstück zur Gateway-Spec (`spec-character-model-job.md`):
anima-verse **speichert, verwaltet und liefert** die Charakter-GLBs.
Administration im **Game Admin → Character → neuer Reiter „3D"**.

## 1. Ablage (Welt-Storage)

```
characters/<name>/model/
  default.glb          # das aktive Modell (MIA-Rig, Textur eingebettet)
  meta.json            # siehe unten
```

`meta.json`:
```json
{
  "format": "glb",
  "rig": "mixamo",
  "joints": 52,
  "vertices": 58953,
  "size_bytes": 10537644,
  "sha256": "e3b0c442…",
  "source": "generated",            // "generated" | "upload"
  "variant": "fast",                // nur bei generated
  "workflow": "trellis2-vb-fast",   // nur bei generated
  "reference_image": "Kira_1773….png",
  "created_at": "2026-07-13T09:12:44Z"
}
```

Später (Stufe 1b, jetzt schon im Layout vorgesehen): `<outfit_id>.glb` pro
Outfit; der Server wählt dann passend zum aktuellen Outfit, `default.glb`
bleibt Fallback.

## 2. Endpoints

### Auslieferung (konsumiert der 3D-Client)

```
GET  /characters/{name}/model
  → 200  Content-Type: model/gltf-binary
         ETag: "<sha256>"            ← PFLICHT (Dateien 10–25 MB, ändern
         Cache-Control: private, max-age=86400          sich selten)
  → 304  bei If-None-Match-Treffer
  → 404  wenn kein Modell → Client fällt auf Portrait-Marker zurück
HEAD /characters/{name}/model        (gleiche Header, kein Body)
GET  /characters/{name}/model/meta   → meta.json | 404
```

### Verwaltung (Game-Admin + Gateway)

```
POST /characters/{name}/model        (require_admin ODER Gateway-Token)
  Content-Type: model/gltf-binary
  X-Model-Meta: {"rig":"mixamo","source":"generated",…}   // JSON, optional
  → 201 + meta.json | 422 mit Fehlercode (Validierung s.u.)

DELETE /characters/{name}/model      (require_admin)
  → 204  (Client zeigt danach wieder Portrait-Marker)

POST /characters/{name}/model/generate          (require_admin)
  { "reference_image": "<dateiname aus galerie>",
    "variant": "fast" | "high",
    "no_fingers": false }
  → 202 { "job_id": "…" }            // Server ruft LLM-Gateway (character_model)
                                     // mit callback_url auf sich selbst auf
GET /characters/{name}/model/generate/status
  → { "status": "queued|running|succeeded|failed", "progress": 0.7,
      "error": {…} }                 // Proxy auf den Gateway-Job
```

### Validierung beim Upload (identisch zur Gateway-Tabelle)

GLB-Magic v2 · genau 1 Skin · 52 Joints mit `mixamorig:`-Namen · erstes
eingebettetes Image > 100 KB (2×2-Dummy-Abfang) · POSITION 5k–150k ·
≤ 30 MB. Bei Verstoß **422** mit `{code, message}` — dieselben Codes wie in
der Gateway-Spec (`invalid_glb`, `invalid_rig`, `missing_texture`, …).
Ausnahme: ungeriggte GLB (0 Skins) wird mit Warnung akzeptiert
(`"warning": "unrigged"`) — Figur wäre statisch, aber anzeigbar.

## 3. Globale Animations-Bibliothek

```
shared/models/clips/               # Walking.fbx, Sitting.fbx, Idle.fbx, …
GET /assets/animation-clips
  → [ { "kind": "walk", "url": "/assets/animation-clips/Walking.fbx" },
      { "kind": "sit",  "url": "/assets/animation-clips/Sitting.fbx" },
      { "kind": "idle", "url": "/assets/animation-clips/Idle.fbx" } ]
GET /assets/animation-clips/{datei} → FBX-Bytes (ETag)
```

`kind` ∈ `idle|walk|run|sit|dance|wave|lie` (erweiterbar; Ableitung aus dem
Dateinamen reicht: `Walking.fbx → walk`). Verwaltung V1: Dateien in den
Ordner legen; Admin-UI optional später. **Regel dokumentieren:** nur frische
Mixamo-Exporte („FBX Without Skin", 30 fps) — Fremd-FBX kippen die Figuren.

## 4. Game Admin → Character → Reiter „3D"

Neuer Tab im bestehenden React-Charaktereditor (`/game-admin`), gleiche
Konventionen wie die übrigen Tabs (template-getrieben, keine JS-Dialoge,
Defaults grau).

**Zustand A — kein Modell vorhanden:**
- Hinweistext („Kein 3D-Modell — auf der Karte erscheint der Portrait-Marker").
- **Generieren-Karte:** Bild-Auswahl aus der Charakter-Galerie (Vorschau-Grid,
  vorausgewählt: Profilbild), Variante `fast`/`high` (Radio, fast default,
  grauer Hinweis „~3 min / ~10 min"), Checkbox `no_fingers` (aus),
  Button „3D-Modell generieren" → `POST …/generate`, danach Fortschritts-
  anzeige (Poll auf `…/generate/status`), bei `succeeded` automatisch
  Zustand B laden, bei `failed` Fehlertext inline.
- **Upload-Karte:** Drag&Drop/Dateiwahl für `.glb` → `POST …/model`;
  Validierungsfehler (422) inline anzeigen.

**Zustand B — Modell vorhanden:**
- **Info-Karte** aus `meta.json`: Quelle (generiert/hochgeladen), Variante,
  Größe, Vertices, Joints, erstellt am, sha256 (gekürzt), Download-Link.
- **3D-Vorschau:** rotierbarer Viewer (three.js GLTFLoader + OrbitControls,
  neutrale Beleuchtung; Referenz-Implementierung: `figure-test.html` im
  3d-Client-Repo — Bind-Pose reicht, Clips sind fürs Admin nicht nötig).
- **Aktionen:** „Neu generieren" (öffnet Generieren-Karte, ersetzt bei
  Erfolg), „Ersetzen" (Upload), „Entfernen" (Inline-Zweischritt-Bestätigung,
  KEIN window.confirm) → `DELETE`.

**Statuszeile im Charakter-Listing** (optional, nice-to-have): kleines
Würfel-Icon bei Charakteren mit Modell.

## 5. Zusammenspiel (Ende-zu-Ende)

1. Admin klickt „Generieren" → anima-verse startet Gateway-Job
   (`spec-character-model-job.md`) mit `callback_url`.
2. Gateway validiert und pusht das GLB an `POST /characters/{name}/model`.
3. anima-verse validiert erneut (Defense in depth), schreibt Datei + Meta,
   invalidiert das ETag.
4. Der 3D-Client bemerkt das neue Modell beim nächsten Laden (bzw. Stufe 2:
   Push-Hinweis); bis dahin: Portrait-Marker-Fallback.
5. Animationen kommen NICHT aus dem Charakter-GLB, sondern aus der globalen
   Clip-Bibliothek (Abschnitt 3) — ein Clip-Satz für alle Charaktere.
